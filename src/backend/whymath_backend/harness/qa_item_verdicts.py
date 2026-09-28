"""QA 엔진 문항별 판정 어댑터 — 골든 혼동행렬의 predictions 생산자 (EOS-137 ①).

왜 필요한가
-----------
`ops/qa_confusion_matrix`는 골든(정답지) 대비 QA 엔진의 FN율을 재는 계산기이고, 저장소의 유일한
append 평가 원장을 쓴다. 그런데 그 계산기가 요구하는 입력 — **QA 엔진이 문항마다 내린
pass/fail**(`--predictions`) — 을 만드는 도구가 저장소에 0건이었다(2026-09-25 MP-03 착수 실측:
`qa_verdict` 키는 그 모듈·테스트·계약 문서에만 나온다). 원인은 더 아래에 있었다 — QA 엔진
(`harness/qa_pipeline`)의 9축이 전부 코퍼스·시험지 단위로 게이트를 낼 뿐 "이 문항을 통과시켰는가"
를 내는 좌석이 없었다. 그 좌석(`qa_pipeline.judge_item`)을 먼저 만들고, 이 모듈이 그것을 문항
파일에 적용해 predictions JSONL을 쓴다.

판정은 여기서 만들지 않는다
-------------------------
판정 로직은 전부 `qa_pipeline.judge_item`(그 아래 기존 축 함수)의 것이다. 이 모듈이 하는 일은
①문항을 읽고 ②정체성(`cu_slug`)을 확정하고 ③판정 불가를 사유와 함께 **분리**하고 ④계약 형식으로
쓰는 것뿐이다.

입력 — 검수자가 본 그대로 읽는다
-------------------------------
문항 읽기는 `review_session.load_review_items`를 **그대로 재사용**한다. 그래서
  - 코퍼스 JSONL(`problems.jsonl` — 축적 회차 코퍼스 포함, `problem_bank_*` 글롭에 묶이지 않고
    경로를 직접 받는다)과 검수 큐 JSONL(`canary_review_queue.jsonl`·`problems.review.jsonl` —
    본문이 `candidate_payload`에 있다)을 같은 규칙으로 받고,
  - 정체성 키(`slug`/`cu_slug`)·파일 안 중복 처리(첫 행 채택)·본문 해석이 **검수 세션이 검수자에게
    보여 준 것과 바이트 단위로 같다.**
골든 라벨은 검수자가 본 입력(as-found)의 라벨이므로(계약 §3), 엔진이 판정하는 입력도 검수자가 본
입력이어야 혼동행렬의 두 축이 같은 대상을 말한다. 로더를 따로 쓰면 그 등식이 조용히 깨진다.

판정 불가 — pass로 채우지 않는다 (미측정 ≠ 통과)
-----------------------------------------------
다음은 predictions에 **쓰지 않고** 사유와 함께 요약에 전건 싣는다(절단 없음). 혼동행렬 쪽에서는
이 문항들이 "미평가"로 분리 카운트된다(계약 §6):

  - `no_cu_slug`      — 정체성 키가 없는 행. 골든과 대응시킬 근거가 없다(추측으로 잇지 않는다).
  - `no_payload`      — 검수 큐 행인데 본문(`candidate_payload`)이 없다(생성 실패 후보 등).
  - `payload_slug_mismatch` — 행의 slug와 본문 안 slug가 다르다. 어느 쪽이 정체성인지 모른다.
  - `conflicting_payload_across_inputs` — 서로 다른 입력 파일에 같은 slug가 **다른 본문**으로
    있다. 어느 본문이 검수자가 본 것인지 이 도구는 모른다(같은 본문이면 1건으로 합친다).
  - `axis_unjudgeable` — 위반은 없는데 판정 불가 축이 있다(필드 타입 위반·판정 함수 예외 등).

작동한 비율 — 판정된 문항 / 입력 문항
-----------------------------------
분모 = 고유 slug 수 + 정체성 없는 행 수(파일 안 중복 행은 같은 문항이라 세지 않는다). 요약에
판정기 좌석의 범위(문항 단위 3축 / 9축)와 축별 상태 분포를 함께 낸다 — pass가 "3축이 이의
없음"이지 "9축 전부 통과"가 아니라는 사실이 산출물에서 보여야 한다.

출력 형식 (golden_benchmark_contract.md §7)
-----------------------------------------
    {"cu_slug": "...", "qa_verdict": "pass"|"fail", "verdict_source": "qa_engine",
     "failed_axes": [...]}
`verdict_source`는 판정기 종류다(EOS-137 ④) — 혼동행렬 리포트 머리와 평가 원장 행에 그대로
실린다. `failed_axes`는 사람용 부기이며 혼동행렬 파서는 읽지 않는다.

종료 코드 (측정 도구 실패 경로 — 2026-08-22 규칙)
-----------------------------------------------
  0 = 판정 1건 이상 + 입력 손상 0 → predictions 파일을 쓴다.
  1 = 입력 문항 0건 또는 판정 0건 → **측정 실패**(통과 아님). 파일을 쓰지 않는다.
  2 = 입력 오류(파일 부재·JSON 파싱 실패 1건 이상) → 파일을 쓰지 않는다. 깨진 행이 하필 fail
      판정 문항이었다면 부분 입력의 판정은 FN을 조용히 늘린다(`golden_inputs` 동일 규약).
요약 JSON은 stdout으로 **항상** 낸다(실패해도 원인이 남는다). 외부 프로세스·네트워크·DB 0.

사용법(운영자):
    python -m whymath_backend.harness.qa_item_verdicts \\
        --input <canary_review_queue.jsonl> [--input <problems.jsonl> ...] \\
        --out <qa_verdicts.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.golden_benchmark import VERDICT_SOURCE_QA_ENGINE
from whymath_backend.harness.qa_pipeline import (
    AXIS_NAMES,
    CORPUS_LEVEL_ONLY_AXES,
    ITEM_AXIS_SCOPE,
    ITEM_LEVEL_AXES,
    ITEM_REQUIRED_AXES,
    ITEM_SEAT_AXES,
    ITEM_VERIFICATION_SCOPE,
    judge_item,
)
from whymath_backend.harness.review_session import load_review_items

__all__ = [
    "REASON_AXIS_UNJUDGEABLE",
    "REASON_CONFLICTING_PAYLOAD",
    "REASON_NO_CU_SLUG",
    "REASON_NO_PAYLOAD",
    "REASON_PAYLOAD_SLUG_MISMATCH",
    "UNJUDGEABLE_REASONS",
    "AdapterResult",
    "ItemVerdictRow",
    "UnjudgeableItem",
    "build_item_verdicts",
    "main",
]

_EXIT_OK = 0
_EXIT_MEASUREMENT_FAIL = 1
_EXIT_INPUT_ERROR = 2

REASON_NO_CU_SLUG = "no_cu_slug"
REASON_NO_PAYLOAD = "no_payload"
REASON_PAYLOAD_SLUG_MISMATCH = "payload_slug_mismatch"
REASON_CONFLICTING_PAYLOAD = "conflicting_payload_across_inputs"
REASON_AXIS_UNJUDGEABLE = "axis_unjudgeable"
UNJUDGEABLE_REASONS = (
    REASON_NO_CU_SLUG,
    REASON_NO_PAYLOAD,
    REASON_PAYLOAD_SLUG_MISMATCH,
    REASON_CONFLICTING_PAYLOAD,
    REASON_AXIS_UNJUDGEABLE,
)
"""판정 불가 사유 5종 — 조치가 달라 뭉뚱그리지 않는다(모듈 docstring 표)."""

# `review_session.load_review_items`가 내는 사유 문자열의 분류 토큰. 그 로더는 손상(JSON 파싱
# 실패·객체 아님)·정체성 부재·파일 안 중복을 한 목록으로 돌려준다 — 뒤의 둘은 입력 손상이
# 아니라 **문항의 사정**이므로 여기서 갈라 읽는다. 토큰이 바뀌면 이 분류가 조용히 틀어지므로
# 결합은 `tests/backend/harness/test_qa_item_verdicts.py`가 실물 로더로 동결한다.
_TOKEN_NO_IDENTITY = "MissingIdentityKey"
_TOKEN_DUPLICATE = "DuplicateSlug"


@dataclass(frozen=True, slots=True)
class ItemVerdictRow:
    """predictions 1행 — 판정이 선 문항만(판정 불가는 여기 오지 않는다)."""

    cu_slug: str
    qa_verdict: str
    failed_axes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "cu_slug": self.cu_slug,
            "qa_verdict": self.qa_verdict,
            "verdict_source": VERDICT_SOURCE_QA_ENGINE,
            "failed_axes": list(self.failed_axes),
        }


@dataclass(frozen=True, slots=True)
class UnjudgeableItem:
    """판정 불가 문항 1건 — 사유·출처(파일·줄)·상세(필드 이름·예외 타입명만, 본문 미포함)."""

    cu_slug: str | None
    reason: str
    source: str
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "cu_slug": self.cu_slug,
            "reason": self.reason,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """어댑터 1회 실행 결과 — 판정분·판정 불가분·손상을 한 값에 묶는다(버릴 수 없게)."""

    verdicts: list[ItemVerdictRow] = field(default_factory=list)
    unjudgeable: list[UnjudgeableItem] = field(default_factory=list)
    damage: list[str] = field(default_factory=list)
    """입력 손상(JSON 파싱 실패·객체 아닌 행) — 1건이라도 있으면 산출하지 않는다."""
    duplicate_rows_within_input: int = 0
    """파일 안 같은 slug의 2번째 이후 행 — 검수 세션과 같이 첫 행만 쓰고 버린다."""
    duplicate_identical_across_inputs: int = 0
    """다른 입력 파일에 같은 slug·같은 본문으로 다시 나온 행 — 1건으로 합쳤다."""
    axis_status_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    """판정을 돌린 문항의 축별 상태 분포 — 어느 축이 실제로 적용됐는지."""

    @property
    def input_items(self) -> int:
        """분모 — 판정 대상이 된 고유 문항 수 + 정체성 없는 행 수."""
        return len(self.verdicts) + len(self.unjudgeable)

    @property
    def judged(self) -> int:
        return len(self.verdicts)

    @property
    def operating_rate(self) -> float | None:
        """작동한 비율 = 판정된 문항 / 입력 문항. 입력 0건이면 미산출(0이 아니다)."""
        if self.input_items == 0:
            return None
        return self.judged / self.input_items


@dataclass(frozen=True, slots=True)
class _Candidate:
    """로더가 준 문항 1건 — 어느 입력의 몇 번째였는지를 함께 들고 다닌다."""

    slug: str
    payload: Mapping[str, Any] | None
    absent_reason: str | None
    source: str


def _classify_loader_errors(path: Path, errors: Sequence[str]) -> tuple[list[str], list[str], int]:
    """로더 사유 → (손상, 정체성 부재 사유, 파일 안 중복 수). 분류 규칙은 모듈 상수 주석."""
    damage: list[str] = []
    no_identity: list[str] = []
    duplicates = 0
    for error in errors:
        _, _, kind = error.partition(": ")
        if kind.startswith(_TOKEN_NO_IDENTITY):
            no_identity.append(f"{path.name} {error}")
        elif kind.startswith(_TOKEN_DUPLICATE):
            duplicates += 1
        else:
            damage.append(f"{path.name} {error}")
    return damage, no_identity, duplicates


def build_item_verdicts(inputs: Sequence[Path]) -> AdapterResult:
    """입력 파일들 → 문항별 판정(순수 판정 + 파일 읽기만 — 쓰기 없음).

    입력 순서가 곧 우선순위다: 같은 slug가 여러 입력에 있으면 첫 입력의 행이 기준이고, 뒤
    입력의 본문이 **같으면** 합치고 **다르면** 그 slug 전체를 판정 불가로 돌린다(어느 본문이
    검수자가 본 것인지 모르므로 — 먼저 온 쪽을 조용히 고르지 않는다).
    """
    damage: list[str] = []
    unjudgeable: list[UnjudgeableItem] = []
    duplicates_within = 0
    duplicates_across = 0
    chosen: dict[str, _Candidate] = {}
    conflicted: dict[str, list[str]] = {}

    for path in inputs:
        items, errors = load_review_items(path)
        file_damage, no_identity, dup = _classify_loader_errors(path, errors)
        damage.extend(file_damage)
        duplicates_within += dup
        for reason in no_identity:
            unjudgeable.append(
                UnjudgeableItem(
                    cu_slug=None,
                    reason=REASON_NO_CU_SLUG,
                    source=reason,
                    detail="정체성 키(slug/cu_slug) 없음 — 골든과 대응시킬 근거가 없다",
                )
            )
        for item in items:
            candidate = _Candidate(
                slug=item.slug,
                payload=item.payload,
                absent_reason=item.payload_absent_reason,
                source=path.name,
            )
            if item.slug in conflicted:
                conflicted[item.slug].append(path.name)
                continue
            first = chosen.get(item.slug)
            if first is None:
                chosen[item.slug] = candidate
                continue
            same_body = first.payload == candidate.payload
            if same_body and first.absent_reason == candidate.absent_reason:
                duplicates_across += 1
                continue
            conflicted[item.slug] = [first.source, path.name]
            del chosen[item.slug]

    for slug in sorted(conflicted):
        unjudgeable.append(
            UnjudgeableItem(
                cu_slug=slug,
                reason=REASON_CONFLICTING_PAYLOAD,
                source=", ".join(conflicted[slug]),
                detail="입력 파일마다 본문이 다르다 — 어느 본문이 검수자가 본 것인지 모른다",
            )
        )

    verdicts: list[ItemVerdictRow] = []
    axis_counts: dict[str, Counter[str]] = {name: Counter() for name in ITEM_SEAT_AXES}
    for slug in sorted(chosen):
        candidate = chosen[slug]
        if candidate.payload is None:
            unjudgeable.append(
                UnjudgeableItem(
                    cu_slug=slug,
                    reason=REASON_NO_PAYLOAD,
                    source=candidate.source,
                    detail=candidate.absent_reason or "본문 없음",
                )
            )
            continue
        inner_slug = candidate.payload.get("slug")
        if isinstance(inner_slug, str) and inner_slug and inner_slug != slug:
            unjudgeable.append(
                UnjudgeableItem(
                    cu_slug=slug,
                    reason=REASON_PAYLOAD_SLUG_MISMATCH,
                    source=candidate.source,
                    detail="행의 slug와 본문 안 slug가 다르다 — 정체성을 정할 수 없다",
                )
            )
            continue
        judgement = judge_item(candidate.payload)
        for name, axis_result in judgement.axes.items():
            axis_counts[name][axis_result.status] += 1
        verdict = judgement.verdict
        if verdict is None:
            detail = "; ".join(
                f"{name}: {judgement.axes[name].reason or '사유 미기재'}"
                for name in judgement.unjudgeable_axes
            ) or "; ".join(f"{name}: 필수 성분 미확인" for name in judgement.missing_required_axes)
            unjudgeable.append(
                UnjudgeableItem(
                    cu_slug=slug,
                    reason=REASON_AXIS_UNJUDGEABLE,
                    source=candidate.source,
                    detail=detail,
                )
            )
            continue
        verdicts.append(
            ItemVerdictRow(cu_slug=slug, qa_verdict=verdict, failed_axes=judgement.failed_axes)
        )

    return AdapterResult(
        verdicts=verdicts,
        unjudgeable=unjudgeable,
        damage=damage,
        duplicate_rows_within_input=duplicates_within,
        duplicate_identical_across_inputs=duplicates_across,
        axis_status_counts={name: dict(counter) for name, counter in axis_counts.items()},
    )


def _summary(result: AdapterResult, inputs: Sequence[Path], out: Path) -> dict[str, Any]:
    """요약 JSON — 작동한 비율·판정 불가 전건·판정기 좌석 범위를 한 화면에."""
    verdict_counts = Counter(row.qa_verdict for row in result.verdicts)
    return {
        "command": "qa_item_verdicts",
        "verdict_source": VERDICT_SOURCE_QA_ENGINE,
        "inputs": [str(path) for path in inputs],
        "input_items": result.input_items,
        "judged": result.judged,
        "pass": verdict_counts.get("pass", 0),
        "fail": verdict_counts.get("fail", 0),
        "operating_rate": result.operating_rate,
        "unjudgeable_count": len(result.unjudgeable),
        "unjudgeable_counts": dict(Counter(item.reason for item in result.unjudgeable)),
        # 전건을 싣는다(절단 없음) — 여기서 자르면 그 문항이 조용히 사라진다.
        "unjudgeable": [item.to_json() for item in result.unjudgeable],
        "duplicate_rows_within_input": result.duplicate_rows_within_input,
        "duplicate_identical_across_inputs": result.duplicate_identical_across_inputs,
        "axis_status_counts": result.axis_status_counts,
        "engine_scope": {
            "item_level_axes": list(ITEM_LEVEL_AXES),
            "item_axis_scope": dict(ITEM_AXIS_SCOPE),
            "item_verification_scope": dict(ITEM_VERIFICATION_SCOPE),
            "item_required_axes": list(ITEM_REQUIRED_AXES),
            "corpus_level_only_axes": dict(CORPUS_LEVEL_ONLY_AXES),
            "total_axes": len(AXIS_NAMES),
            "note": (
                "pass = 정답 재검산 통과 + 문항 단위 "
                f"{len(ITEM_LEVEL_AXES)}축이 이의 없음(9축 전부 통과가 아니다) — "
                "골든 대비 FN율은 이 좌석의 FN율이다"
            ),
        },
        "damage": list(result.damage),
        "out": str(out),
        "written": False,
    }


def _emit(summary: Mapping[str, Any]) -> None:
    """요약 JSON을 stdout에 낸다 — 성공·실패 모두(원인이 남아야 한다)."""
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — exit 0=산출, 1=입력 0건·판정 0건(측정 실패), 2=입력 오류."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.qa_item_verdicts",
        description=(
            "QA 엔진 문항별 판정 어댑터(EOS-137 ①) — 코퍼스·검수 큐 JSONL의 문항마다 "
            "qa_pipeline.judge_item 판정을 predictions JSONL로 쓴다. 판정 불가는 pass로 "
            "채우지 않고 사유와 함께 요약에 싣는다."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        required=True,
        help="문항 JSONL(복수·순서가 우선순위) — 코퍼스 행 또는 candidate_payload를 가진 큐 행.",
    )
    parser.add_argument("--out", type=Path, required=True, help="predictions JSONL 출력 경로.")
    args = parser.parse_args(argv)
    inputs: list[Path] = list(args.input)
    out: Path = args.out

    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        _emit(
            {
                "command": "qa_item_verdicts",
                "written": False,
                "error": "input_missing",
                "missing": missing,
            }
        )
        return _EXIT_INPUT_ERROR

    result = build_item_verdicts(inputs)
    summary = _summary(result, inputs, out)
    if result.damage:
        # 손상된 입력 위의 판정은 권위가 없다 — 쓰지 않는다(golden_inputs exit 2와 같은 판단).
        summary["error"] = "input_damaged"
        _emit(summary)
        return _EXIT_INPUT_ERROR
    if result.input_items == 0:
        summary["error"] = "no_input_items"
        _emit(summary)
        return _EXIT_MEASUREMENT_FAIL
    if result.judged == 0:
        summary["error"] = "no_judged_items"
        _emit(summary)
        return _EXIT_MEASUREMENT_FAIL

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in result.verdicts:
            handle.write(json.dumps(row.to_json(), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    summary["written"] = True
    _emit(summary)
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
