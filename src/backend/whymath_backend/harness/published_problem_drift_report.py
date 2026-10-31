"""발행된 문항의 판-라이브 드리프트 리포트 — EOS-195 acceptance ②(읽기 전용 실측).

**존재 이유**: 문항 판(`problem_version`)은 *스냅숏*이고 학생에게 서빙되는 원본은 여전히 라이브
`problem` 행이다. 발행 뒤 라이브 행이 바뀌면 EOS-47이 시도에 고정한 판의 payload가 학생이 실제로 푼
문항과 달라진다. EOS-195는 그 변경 경로 셋(CMS 편집·`PATCH /v1/problems`·코퍼스 재적재)을
**차단**하는 처분을 골랐다(`api/admin_cms._edit_block_reason` · `api/problems.patch_problem` ·
`l1/problem_bank/populate`의 upsert WHERE). 이 리포트는
그 차단이 *실제로 지켜지는지*를 보는 **탐지 통제**다 — 차단 세 경로 밖의 쓰기(직접 SQL·새 writer·
차단 이전 시기에 생긴 드리프트)는 이 숫자로만 보인다.

**분자·분모(acceptance ②)**: 분모 = 발행 포인터(`problem.problem_version_id`)가 채워진 문항 수.
분자 = 그중 *라이브 행의 스냅숏 해시*(`snapshot_payload` → `compute_content_hash`)가 *포인터 판
payload 해시*와 다른 문항 수. 해시 함수는 발행 게이트가 쓰는 것을 그대로 부른다(재구현 0 — 두 곳이
갈라지면 "게이트는 일치라는데 리포트는 어긋남"이 생긴다).

**세 상태를 뭉개지 않는다** — 문항 1건은 다음 셋 중 하나다:
  1. `in_sync`(일치) — 해시가 같다.
  2. `drifted`(어긋남) — 해시가 다르다. 어느 필드가 다른지 이름만 남긴다(값은 싣지 않는다 — 정답은
     내부 전용이고 본문은 저작권 레일 대상이라 리포트 산출물에 복제하지 않는다).
  3. `indeterminate`(판정 불가) — 대조 자체를 못 했다: 라이브 행이 스냅숏 계약을 어긴다 /
     판을 읽지 못했다 / 포인터가 PUBLISHED 아닌 판이나 다른 문항의 판을 가리킨다. **일치로도
     어긋남으로도 세지 않는다**(모른다 ≠ 통과). 분모에는 들어가므로 "어긋남 0%"가 "검증 못 한
     것이 많다"를 가리지 못하게 `판정 불가` 줄이 따로 나온다.

**분모 0 = 측정 불성립**이다. 통과가 아니다(0건 통과 위장 금지). 발행 호출 표면(EOS-194)이 없으면
운영 DB의 포인터는 전부 NULL이라 이 상태가 *정상*이고, 그때 이 리포트는 "아직 아무것도 못 쟀다"를
말해야지 "드리프트 없음"을 말하면 안 된다.

**게이트가 아니다**(`attempt_skill_event_reach_report` 동일 원칙) — 어긋남이 있어도 exit 1을 내지
않는다. 차단은 쓰기 경로가 하고 이 리포트는 가시화다. exit는 **0=성공 / 2=DB 오류**뿐이고, 조회
실패는 예외 타입명과 함께 stderr로 보고한다(측정 실패가 "0건"으로 위장되지 않게).

**"상시 보고"의 집행 지점(정본화≠집행)**: 판정 로직(3상태 변별·분모 0 처리·필드 이름 추출·CLI exit
0/2)은 `tests/backend/harness/test_published_problem_drift_report.py`가 CI에서 상시 검증한다. 수치는
실 PG의 발행 이력이 분모라 CI(매 잡 빈 DB)에서 돌리면 전부 분모 0이다 —
`ops/declared_unwired_audit`에 `_NEEDS_LIVE_SAMPLE`로 의도를 선언했고, 주기 실행은 관측 리포트
러너(`ops/observation_report_runner`)에 등록했다.

사용:
    python -m whymath_backend.harness.published_problem_drift_report
    python -m whymath_backend.harness.published_problem_drift_report --json out/eos195.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import Problem
from whymath_backend.db.session import get_sessionmaker
from whymath_backend.l3.problem_publish_gate import (
    PointerPair,
    compute_content_hash,
    iter_pointer_filled,
    snapshot_payload,
)
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.problem_version import ProblemVersionPayload
from whymath_backend.schema.version_header import VersionStatus

__all__ = [
    "SAMPLE_LIMIT",
    "DriftReport",
    "DriftSample",
    "IndeterminateReason",
    "PointerObservation",
    "PointerState",
    "Verdict",
    "aggregate",
    "classify",
    "collect_report",
    "dump_json",
    "main",
    "render_report",
    "report_to_json",
]

_EXIT_OK = 0
_EXIT_DB_ERROR = 2

#: 난이도 외 필드가 하나도 안 어긋난 건을 가르는 키 — payload 필드명과 같다.
_DIFFICULTY_FIELD = "difficulty_at_publish"

#: 어긋난 문항 표본의 상한 — 문항 id와 필드 이름만 싣는다(값 미포함).
SAMPLE_LIMIT = 20


class PointerState(StrEnum):
    IN_SYNC = "in_sync"
    DRIFTED = "drifted"
    INDETERMINATE = "indeterminate"


class IndeterminateReason(StrEnum):
    """판정 불가 사유 — 대책 축이 서로 달라 한 숫자로 뭉개지 않는다."""

    LIVE_SNAPSHOT_INVALID = "live_snapshot_invalid"
    VERSION_UNREADABLE = "version_unreadable"
    VERSION_NOT_PUBLISHED = "version_not_published"
    VERSION_PROBLEM_MISMATCH = "version_problem_mismatch"


@dataclass(slots=True, frozen=True)
class PointerObservation:
    """포인터가 채워진 문항 1건의 대조 입력 — DB 조회와 순수 판정을 가르는 seam.

    `live`가 None이면 라이브 행이 스냅숏 계약을 어겼다는 뜻이고(`live_error`=예외 타입명),
    `version`이 None이면 판을 읽지 못했다는 뜻이다(`version_error`=예외 타입명).
    """

    problem_id: uuid.UUID
    live: ProblemVersionPayload | None
    live_error: str | None
    version: SchemaProblemVersion | None
    version_error: str | None


@dataclass(slots=True, frozen=True)
class Verdict:
    state: PointerState
    reason: IndeterminateReason | None = None
    #: 어긋난 payload 필드 이름(정렬). `drifted`일 때만 비어 있지 않다. 값은 싣지 않는다.
    changed_fields: tuple[str, ...] = ()


def classify(obs: PointerObservation) -> Verdict:
    """한 문항의 3상태 판정(순수·부작용 0).

    판정 불가 사유를 해시 대조보다 **먼저** 가른다 — 포인터가 PUBLISHED 아닌 판이나 남의 판을
    가리키면 payload를 비교하는 것 자체가 의미가 없다(그 비교가 우연히 같더라도 포인터 불변식이
    깨진 상태다).
    """
    version = obs.version
    if version is None:
        return Verdict(PointerState.INDETERMINATE, IndeterminateReason.VERSION_UNREADABLE)
    if version.problem_id != obs.problem_id:
        return Verdict(PointerState.INDETERMINATE, IndeterminateReason.VERSION_PROBLEM_MISMATCH)
    if version.status != VersionStatus.PUBLISHED.value:
        return Verdict(PointerState.INDETERMINATE, IndeterminateReason.VERSION_NOT_PUBLISHED)
    if obs.live is None:
        return Verdict(PointerState.INDETERMINATE, IndeterminateReason.LIVE_SNAPSHOT_INVALID)

    if compute_content_hash(obs.live) == compute_content_hash(version.payload):
        return Verdict(PointerState.IN_SYNC)
    live_dump = obs.live.model_dump(mode="json")
    version_dump = version.payload.model_dump(mode="json")
    changed = tuple(
        sorted(
            k
            for k in live_dump.keys() | version_dump.keys()
            if live_dump.get(k) != version_dump.get(k)
        )
    )
    return Verdict(PointerState.DRIFTED, changed_fields=changed)


@dataclass(slots=True, frozen=True)
class DriftSample:
    """어긋난 문항 1건의 표본 — id와 필드 이름뿐(값 미포함)."""

    problem_id: uuid.UUID
    changed_fields: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class DriftReport:
    """드리프트 실측 결과 전량(불변·렌더/직렬화의 단일 입력)."""

    problems_total: int
    pointer_filled: int
    in_sync: int
    drifted: int
    indeterminate: int
    indeterminate_by_reason: dict[str, int] = field(default_factory=dict)
    drifted_by_field: dict[str, int] = field(default_factory=dict)
    drifted_difficulty_only: int = 0
    samples: tuple[DriftSample, ...] = ()

    @property
    def measurable(self) -> bool:
        """분모(포인터가 채워진 문항)가 있어야 측정이 성립한다."""
        return self.pointer_filled > 0

    @property
    def drift_rate(self) -> float | None:
        """어긋남 비율(분자=어긋남·분모=포인터 채워진 전체). **None**이면 비율을 말할 수 없다.

        분모가 0이거나, 분모는 있어도 해시를 **한 건도 대조하지 못했으면**(전부 판정 불가)
        None이다 —
        후자를 0%로 내면 JSON 소비자가 "측정됨·어긋남 0%"로 읽는다(0건 통과 위장 금지).
        """
        if self.pointer_filled == 0 or self.verified == 0:
            return None
        return self.drifted / self.pointer_filled

    @property
    def verified(self) -> int:
        """해시를 실제로 대조한 건수(일치+어긋남). 판정 불가는 빠진다."""
        return self.in_sync + self.drifted


def aggregate(verdicts: Iterable[tuple[uuid.UUID, Verdict]], *, problems_total: int) -> DriftReport:
    """판정 목록 → 리포트(순수). 표본은 처음 `SAMPLE_LIMIT`건(입력 순서)."""
    in_sync = drifted = indeterminate = difficulty_only = 0
    by_reason: dict[str, int] = {}
    by_field: dict[str, int] = {}
    samples: list[DriftSample] = []
    for problem_id, verdict in verdicts:
        if verdict.state is PointerState.IN_SYNC:
            in_sync += 1
        elif verdict.state is PointerState.DRIFTED:
            drifted += 1
            for name in verdict.changed_fields:
                by_field[name] = by_field.get(name, 0) + 1
            if verdict.changed_fields == (_DIFFICULTY_FIELD,):
                difficulty_only += 1
            if len(samples) < SAMPLE_LIMIT:
                samples.append(DriftSample(problem_id, verdict.changed_fields))
        else:
            indeterminate += 1
            key = verdict.reason.value if verdict.reason is not None else "unknown"
            by_reason[key] = by_reason.get(key, 0) + 1
    return DriftReport(
        problems_total=problems_total,
        pointer_filled=in_sync + drifted + indeterminate,
        in_sync=in_sync,
        drifted=drifted,
        indeterminate=indeterminate,
        indeterminate_by_reason=by_reason,
        drifted_by_field=by_field,
        drifted_difficulty_only=difficulty_only,
        samples=tuple(samples),
    )


def observe(pair: PointerPair) -> PointerObservation:
    """게이트 모듈의 조회 결과 → 대조 입력. 라이브 스냅숏 실패는 예외 타입명으로 남긴다."""
    live: ProblemVersionPayload | None
    live_error: str | None = None
    try:
        live = snapshot_payload(pair.problem)
    except ValidationError as exc:
        live, live_error = None, type(exc).__name__
    return PointerObservation(
        problem_id=pair.problem.problem_id,
        live=live,
        live_error=live_error,
        version=pair.version,
        version_error=pair.version_error,
    )


async def collect_report(session: AsyncSession) -> DriftReport:
    """DB를 훑어 리포트를 만든다(유일한 DB 접근 지점·쓰기 0).

    판 행은 게이트 모듈의 읽기 조회로만 읽는다(ORM `ProblemVersion` import 동결 R1).
    """
    problems_total = (await session.execute(select(func.count()).select_from(Problem))).scalar_one()
    verdicts: list[tuple[uuid.UUID, Verdict]] = []
    async for pair in iter_pointer_filled(session):
        obs = observe(pair)
        verdicts.append((obs.problem_id, classify(obs)))
    return aggregate(verdicts, problems_total=problems_total)


def _pct(value: float | None) -> str:
    """비율 렌더 — 분모 0(None)은 `측정 불성립`으로 말한다(0%로 위장 금지)."""
    return "측정 불성립(분모 0)" if value is None else f"{value * 100:.1f}%"


def render_report(report: DriftReport) -> str:
    """실측 결과를 마크다운으로 렌더(순수·입력 외 계산 없음)."""
    lines: list[str] = [
        "# 발행 문항 판-라이브 드리프트 리포트 (EOS-195 ②)",
        "",
        "> 관측 리포트다 — **exit 게이트가 아니다**(어긋남이 있어도 실패시키지 않는다).",
        "> 차단은 쓰기 경로(CMS 편집·`PATCH /v1/problems`·코퍼스 재적재)가 한다. "
        "이 숫자는 그 차단 밖의 쓰기를 본다.",
        "",
        f"- 전체 문항: **{report.problems_total}**",
        f"- 발행 포인터가 채워진 문항(분모): **{report.pointer_filled}**",
        "",
    ]
    if not report.measurable:
        lines += [
            "## 측정 불성립",
            "",
            "**발행 포인터가 채워진 문항이 0건이다 — 이것은 '드리프트 없음'이 아니라 "
            "'아직 아무것도 재지 못했다'이다.** 발행 호출 표면(EOS-194)이 없으면 운영 포인터는 "
            "전부 NULL이라 이 상태가 정상이다. 이 리포트는 첫 발행이 생긴 뒤부터 의미를 갖는다.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        "## 1. 3상태 (일치 / 어긋남 / 판정 불가)",
        "",
        "| 상태 | 건수 | 뜻 |",
        "|---|---:|---|",
        f"| 일치 | {report.in_sync} | 라이브 스냅숏 해시 == 포인터 판 payload 해시 |",
        f"| **어긋남** | {report.drifted} | 해시가 다르다 — 푼 문항과 고정된 판이 갈라졌다 |",
        f"| 판정 불가 | {report.indeterminate} | 대조를 못 했다(앞의 둘에 세지 않는다) |",
        "",
        f"- **어긋남 비율**(어긋남/포인터 채워진 전체): {_pct(report.drift_rate)} "
        f"({report.drifted}/{report.pointer_filled})",
        f"- 해시를 실제로 대조한 건수: {report.verified}/{report.pointer_filled}",
        "",
    ]
    if report.indeterminate:
        lines += ["### 판정 불가 사유", "", "| 사유 | 건수 |", "|---|---:|"]
        for reason in IndeterminateReason:
            count = report.indeterminate_by_reason.get(reason.value, 0)
            if count:
                lines.append(f"| `{reason.value}` | {count} |")
        lines.append("")
        lines.append(
            "> 어긋남 비율이 낮아 보여도 판정 불가가 많으면 '검증 못 한 것'이 많다는 뜻이다 — "
            "위 해시 대조 건수를 함께 본다."
        )
        lines.append("")
    if report.drifted:
        lines += [
            "## 2. 어긋난 필드 (payload 필드 이름별 건수 — 값은 싣지 않는다)",
            "",
            "| 필드 | 건수 |",
            "|---|---:|",
        ]
        for name in sorted(report.drifted_by_field):
            lines.append(f"| `{name}` | {report.drifted_by_field[name]} |")
        lines += [
            "",
            f"- 난이도(`{_DIFFICULTY_FIELD}`)**만** 어긋난 건: "
            f"{report.drifted_difficulty_only}건 — "
            "내용 변경이 아니라 라벨 변경이지만 같은 차단 대상이라 함께 센다.",
            "",
            f"## 3. 표본 (최대 {SAMPLE_LIMIT}건)",
            "",
        ]
        for sample in report.samples:
            lines.append(f"- `{sample.problem_id}` — {', '.join(sample.changed_fields)}")
        lines.append("")
    return "\n".join(lines)


def report_to_json(report: DriftReport) -> dict[str, Any]:
    """리포트 → JSON 직렬화 가능 dict(키 정렬은 dump 시 `sort_keys=True`)."""
    return {
        "problems_total": report.problems_total,
        "pointer_filled": report.pointer_filled,
        "measurable": report.measurable,
        "in_sync": report.in_sync,
        "drifted": report.drifted,
        "indeterminate": report.indeterminate,
        "verified": report.verified,
        "drift_rate": report.drift_rate,
        "indeterminate_by_reason": dict(sorted(report.indeterminate_by_reason.items())),
        "drifted_by_field": dict(sorted(report.drifted_by_field.items())),
        "drifted_difficulty_only": report.drifted_difficulty_only,
        "samples": [
            {"problem_id": str(s.problem_id), "changed_fields": list(s.changed_fields)}
            for s in report.samples
        ],
    }


def dump_json(report: DriftReport) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ──────────────────────────────────────────────────────────────────────────
# CLI (얇은 껍데기 — DB 조회·입출력만, 판정은 위 순수 코어)
# ──────────────────────────────────────────────────────────────────────────
async def _run() -> DriftReport:  # pragma: no cover — PG glue
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        return await collect_report(session)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 리포트를 stdout에 출력. **0=성공(어긋남이 있어도) / 2=DB 오류**."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.published_problem_drift_report",
        description=(
            "발행 문항 판-라이브 드리프트 리포트(EOS-195 ②) — 포인터가 채워진 문항 중 라이브 행이 "
            "발행된 판 payload와 어긋난 비율. 게이트 아님(exit 0/2)."
        ),
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로(선택)"
    )
    args = parser.parse_args(argv)

    try:
        report = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 — DB 오류는 타입명과 함께 보고하고 exit 2
        print(
            f"DB 오류 — 드리프트 집계 실패({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return _EXIT_DB_ERROR

    print(render_report(report))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(dump_json(report), encoding="utf-8")
        print(f"JSON 산출물: {args.json_path}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    raise SystemExit(main())
