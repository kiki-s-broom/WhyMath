"""생성 산출물 리콜 — 선별 조회 + 처분 계획 (EOS-97).

**왜 필요한가**: `GenerationLog`는 EOS-55/EOS-73으로 재현 재료를 강하게 갖췄지만
(프롬프트 전문 스냅샷·해시·모델·시드), 그것을 **선별해 처분하는 축이 비어 있었다** —
genlog JSONL 소비 도구 2종은 집계만 하고 개별 산출물을 골라내지 않는다. 그래서 결함을
발견해도 *"이 프롬프트 버전으로 만든 것만 골라 격리"* 가 기계로 불가능했다(설계서 §3
리콜 시나리오 · 갭 리뷰 §6 G-2).

## 조회 원천 — JSONL 사이드카 (정본화 ≠ 집행)

**이 도구는 `<out>.genlog.jsonl` 사이드카만 읽는다. DB 직접 조회는 지원하지 않는다.**

`generation_log` 테이블은 실재하고 `run_id` 컬럼도 이 태스크에서 함께 추가했지만, 적재
경로가 오프라인 배치(DB 세션 없음)라 **1차 매체가 JSONL**이다. `ops/hit_cu_metrics`가
같은 이유로 DB 조회 모드를 "정직한 공백"으로 자인한다 — 같은 공백을 여기서도 그대로
안고 간다(있는 척 금지). DB 적재 경로가 생기면 이 모듈에 `--from-db`를 더한다.

## 처분 — 표면을 늘리지 않는다

격리 경로는 **이미 실재한다**: `PATCH /v1/problems/{id}`(`RequireContentAdmin`)가
`review_status`·`quarantine_reason`·`quarantined_at` 3필드를 함께 받고,
`problem_quarantine_contract.md` §5가 이를 정본으로 규정한다. 같은 계약 §7이 전용 격리
엔드포인트를 **의도적으로 미채택**했으므로 이 도구도 전용 표면을 만들지 않고 그 PATCH를
호출한다.

**dry-run이 기본이다.** `--apply`를 명시해야 실제로 PATCH를 보낸다. 되돌리기 어려운
행위는 기본값이 되면 안 된다.

## 정체성 해결 — genlog의 `problem_id`는 배치 경로에서 항상 None이다 (#992 P1-1)

이것이 이 도구의 급소다. 주 입력인 `problem_corpus_accumulate` 사이드카에서
`LLMEquivalentProblemGenerator._emit_generation_log`는 **`problem_id=None`을 의도적으로**
기록한다 — 배치 저작 산출물은 JSONL 코퍼스 레코드이지 DB problem 행이 아니므로, DB PK를
적으면 날조다. 그래서 genlog만 읽으면 **성공 행 전부가 격리 불가로 분류돼 `--apply`가 0건
PATCH를 보내고도 성공으로 끝난다** — 지원 원천에서 도구가 아무것도 못 하는 상태다.

해결은 `cu_slug`다. 코퍼스 JSONL(`<out>.jsonl`)의 각 레코드가 `slug`와 `problem_id`를
함께 들고 있고, `l1/problem_bank/populate.py`가 **`ON CONFLICT(slug)`로 upsert**하므로
slug가 DB 영속 문항의 안정 식별 축이다. 따라서 `--corpus`로 코퍼스 사이드카를 함께 주면
`cu_slug → problem_id`를 해결해 격리 대상으로 승격한다.

**한계 명시(날조 금지)**: 같은 slug가 *이전에* 적재된 적이 있으면 DB는 기존 행의
problem_id를 유지하므로(populate가 `problem_id`를 SET 제외) 코퍼스의 UUID와 갈라질 수
있다. 그 경우 PATCH는 **404로 실패**하며 그 실패는 건별 결과에 그대로 남는다 — 조용히
엉뚱한 문항을 격리하지 않는다(UUID 공간에서 오조준 성공은 사실상 불가).

## 처분 불가를 조용히 버리지 않는다 — 3분류

  - `quarantinable` — problem_id 확보(genlog 직접 또는 코퍼스 해결). PATCH 대상.
  - `corpus_only` — `cu_slug`는 있으나 problem_id 미해결. **격리가 아니라 코퍼스 행
    제거·재생성 대상**이며 `regeneration_slugs`로 slug를 낸다(acceptance ③ 후반부).
  - `unidentifiable` — cu_slug도 problem_id도 없음. 정체성이 생기기 전에 실패한 호출
    (provider 예외·파싱 실패)이라 처분 대상 자체가 아니다.

셋 다 **집계에서 빼지 않는다** — 분모에서 조용히 사라지면 "전건 처분됨"으로 오독된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from whymath_backend.l3.pregenerate.provenance_bridge import load_generation_logs_jsonl
from whymath_backend.schema.provenance import GenerationLog

__all__ = [
    "RecallPlan",
    "RecallSelector",
    "TargetRow",
    "apply_quarantine",
    "build_plan",
    "load_slug_index",
    "main",
    "select_logs",
]

#: 해시류 셀렉터의 **접두 일치**를 허용하는 최소 길이. 설계서가 `--source-hash aa31`처럼
#: 짧은 접두로 부르는 것을 지원하되, 너무 짧으면 무관한 산출물이 딸려 오므로 하한을 둔다.
#: 4자면 16^4=65,536 공간이라 소규모 회차에서 충돌은 드물고, 그래도 열거 결과를 눈으로
#: 확인하는 것이 dry-run 기본값의 존재 이유다.
MIN_HASH_PREFIX = 4


@dataclass(frozen=True, slots=True)
class RecallSelector:
    """무엇을 골라낼 것인가 — 지정된 조건만 AND로 겹친다(미지정은 무조건).

    전부 None이면 `matches`가 항상 True다. 그 상태를 허용할지는 호출자 판단인데,
    CLI는 **거부한다** — 셀렉터 없는 리콜은 "전건 처분"이고 그건 사고다.
    """

    run_id: str | None = None
    prompt_version: str | None = None
    model_name: str | None = None
    seed: int | None = None
    input_sha256: str | None = None

    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (
                self.run_id,
                self.prompt_version,
                self.model_name,
                self.seed,
                self.input_sha256,
            )
        )

    def matches(self, log: GenerationLog) -> bool:
        """이 로그가 셀렉터에 걸리는가.

        `input_sha256`은 **접두 일치**(설계서의 짧은 해시 호출 지원), 나머지는 완전 일치다.
        `prompt_version`도 접두를 허용한다 — 값 자체가 `l3.equivalent@sha256:…` 형태라
        해시 꼬리를 자르는 호출이 자연스럽다.
        """
        if self.run_id is not None and log.run_id != self.run_id:
            return False
        if self.prompt_version is not None:
            if log.prompt_version is None or not log.prompt_version.startswith(self.prompt_version):
                return False
        if self.model_name is not None and log.model_name != self.model_name:
            return False
        if self.seed is not None and log.seed != self.seed:
            return False
        if self.input_sha256 is not None:
            if log.input_sha256 is None or not log.input_sha256.startswith(self.input_sha256):
                return False
        return True


@dataclass(frozen=True, slots=True)
class TargetRow:
    """리콜 대상 1건 — 처분에 필요한 정체성만 추린 투영."""

    problem_id: str | None
    cu_slug: str | None
    run_id: str | None
    prompt_version: str | None
    model_name: str | None
    seed: int | None
    input_sha256: str | None
    generated_at: str | None
    #: problem_id의 출처 — "genlog"(로그가 직접 들고 있었다) / "corpus"(cu_slug로 해결했다)
    #: / None(미해결). 어디서 온 식별자인지 밝히지 않으면 해결분과 원본이 구분되지 않는다.
    problem_id_source: str | None = None

    @classmethod
    def from_log(
        cls, log: GenerationLog, *, slug_index: Mapping[str, str] | None = None
    ) -> TargetRow:
        """로그 1행 → 처분 대상 투영. `slug_index`가 있으면 cu_slug로 problem_id를 해결한다.

        genlog가 직접 들고 있는 problem_id가 **우선**이다 — 코퍼스 해결은 그것이 없을 때만
        쓰는 보조 축이다(로그가 아는 값을 코퍼스 추정으로 덮어쓰지 않는다).
        """
        problem_id = str(log.problem_id) if log.problem_id is not None else None
        source: str | None = "genlog" if problem_id is not None else None
        if problem_id is None and slug_index is not None and log.cu_slug is not None:
            resolved = slug_index.get(log.cu_slug)
            if resolved is not None:
                problem_id, source = resolved, "corpus"
        return cls(
            problem_id=problem_id,
            problem_id_source=source,
            cu_slug=log.cu_slug,
            run_id=log.run_id,
            prompt_version=log.prompt_version,
            model_name=log.model_name,
            seed=log.seed,
            input_sha256=log.input_sha256,
            generated_at=log.generated_at.isoformat() if log.generated_at is not None else None,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "problem_id_source": self.problem_id_source,
            "cu_slug": self.cu_slug,
            "run_id": self.run_id,
            "prompt_version": self.prompt_version,
            "model_name": self.model_name,
            "seed": self.seed,
            "input_sha256": self.input_sha256,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True, slots=True)
class RecallPlan:
    """처분 계획 — 무엇을 격리할 수 있고 무엇을 못 하는가.

    `scanned`(분모)를 항상 싣는다. 매치 수만 내면 "3건 걸림"이 전체 3건 중인지 3만 건
    중인지 알 수 없다(CLAUDE.md 절단 출력 부재 판정 축의 같은 논리).
    """

    scanned: int
    matched: int
    quarantinable: list[TargetRow] = field(default_factory=list)
    unquarantinable: list[TargetRow] = field(default_factory=list)
    load_errors: list[str] = field(default_factory=list)

    @property
    def corpus_only(self) -> list[TargetRow]:
        """cu_slug는 있으나 problem_id 미해결 — 격리가 아니라 **재생성·제거** 대상."""
        return [row for row in self.unquarantinable if row.cu_slug is not None]

    @property
    def unidentifiable(self) -> list[TargetRow]:
        """cu_slug도 problem_id도 없음 — 정체성 생기기 전에 실패한 호출."""
        return [row for row in self.unquarantinable if row.cu_slug is None]

    @property
    def regeneration_slugs(self) -> list[str]:
        """재생성 대상 slug 목록(중복 제거·발견 순서 보존) — acceptance ③ 후반부 산출물."""
        seen: dict[str, None] = {}
        for row in self.corpus_only:
            if row.cu_slug is not None:
                seen.setdefault(row.cu_slug, None)
        return list(seen)

    def to_json(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "quarantinable_count": len(self.quarantinable),
            "unquarantinable_count": len(self.unquarantinable),
            "corpus_only_count": len(self.corpus_only),
            "unidentifiable_count": len(self.unidentifiable),
            "quarantinable": [row.to_json() for row in self.quarantinable],
            "unquarantinable": [row.to_json() for row in self.unquarantinable],
            "regeneration_slugs": self.regeneration_slugs,
            "load_errors": self.load_errors,
        }


def select_logs(logs: Sequence[GenerationLog], selector: RecallSelector) -> list[GenerationLog]:
    """셀렉터에 걸리는 로그만 순서 그대로 반환한다(순수 함수)."""
    return [log for log in logs if selector.matches(log)]


def load_slug_index(paths: Sequence[Path]) -> tuple[dict[str, str], list[str]]:
    """코퍼스 JSONL에서 `slug → problem_id` 색인을 만든다 — (색인, 실패 사유) 튜플.

    스키마 전체 검증(`Problem.model_validate`)을 하지 **않는다** — 필요한 것은 두 키뿐이고,
    무관한 필드의 검증 실패로 해결 가능한 행까지 잃는 것이 더 나쁘다. 대신 파싱·키 부재는
    사유로 수집한다(침묵 실패 금지 — 타입명 + 줄 번호만, 필드 값은 싣지 않는다).

    같은 slug가 여러 코퍼스에 있으면 **먼저 읽은 쪽을 유지**하고 충돌을 사유로 남긴다 —
    조용히 덮어쓰면 어느 UUID로 PATCH가 나갔는지 사후에 알 수 없다.
    """
    index: dict[str, str] = {}
    errors: list[str] = []
    for path in paths:
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.name}: {type(exc).__name__}")
            continue
        with handle as fh:
            for line_no, line in enumerate(fh, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path.name} line {line_no}: {type(exc).__name__}")
                    continue
                if not isinstance(record, dict):
                    errors.append(f"{path.name} line {line_no}: TypeError(not an object)")
                    continue
                slug, problem_id = record.get("slug"), record.get("problem_id")
                if not isinstance(slug, str) or not isinstance(problem_id, str):
                    errors.append(f"{path.name} line {line_no}: KeyError(slug/problem_id)")
                    continue
                existing = index.get(slug)
                if existing is not None:
                    if existing != problem_id:
                        errors.append(
                            f"{path.name} line {line_no}: SlugCollision(slug={slug} — 먼저 읽은 "
                            "problem_id 유지)"
                        )
                    continue
                index[slug] = problem_id
    return index, errors


def build_plan(
    logs: Sequence[GenerationLog],
    selector: RecallSelector,
    *,
    load_errors: Sequence[str] = (),
    slug_index: Mapping[str, str] | None = None,
) -> RecallPlan:
    """선별 결과를 처분 계획으로 조립한다 — 격리 가능/불가를 **나눠서** 센다.

    `slug_index`(코퍼스 `slug → problem_id`)를 주면 genlog가 `problem_id=None`으로 남긴
    배치 산출물을 `cu_slug`로 해결해 격리 대상으로 승격한다 — 이 해결이 없으면 주 입력에서
    격리 가능 대상이 **구조적으로 0건**이다(모듈 docstring "정체성 해결" 참조).

    끝내 problem_id가 없는 행은 격리 대상이 될 수 없다. 빼지 않고 `unquarantinable`로
    옮겨 담고 cu_slug 유무로 재생성 대상/미착지를 다시 가른다 — 조용히 사라지면 전건
    처분으로 오독된다.
    """
    matched = select_logs(logs, selector)
    quarantinable: list[TargetRow] = []
    unquarantinable: list[TargetRow] = []
    for log in matched:
        row = TargetRow.from_log(log, slug_index=slug_index)
        (quarantinable if row.problem_id is not None else unquarantinable).append(row)
    return RecallPlan(
        scanned=len(logs),
        matched=len(matched),
        quarantinable=quarantinable,
        unquarantinable=unquarantinable,
        load_errors=list(load_errors),
    )


def apply_quarantine(
    plan: RecallPlan,
    *,
    client: httpx.Client,
    reason: str,
    quarantined_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """격리 가능 대상에 `PATCH /v1/problems/{id}`를 보낸다 — 계약 §5의 3필드 동시 기입.

    전용 격리 엔드포인트를 만들지 않는다(`problem_quarantine_contract.md` §7이 의도적으로
    미채택). 실패는 **삼키지 않고** 건별 결과에 상태·사유를 담아 돌려준다 — 일부만 성공한
    처분을 전건 성공으로 보고하면 남은 결함이 살아 있는 채 "처리됨"이 된다.
    """
    stamp = (quarantined_at or datetime.now(UTC)).isoformat()
    results: list[dict[str, Any]] = []
    for row in plan.quarantinable:
        payload = {
            "review_status": "quarantined",
            "quarantine_reason": reason,
            "quarantined_at": stamp,
        }
        try:
            resp = client.patch(f"/v1/problems/{row.problem_id}", json=payload)
        except httpx.HTTPError as exc:
            # 예외 타입명을 남긴다(침묵 실패 금지) — 시크릿·본문은 싣지 않는다.
            results.append({"problem_id": row.problem_id, "ok": False, "error": type(exc).__name__})
            continue
        ok = 200 <= resp.status_code < 300
        entry: dict[str, Any] = {
            "problem_id": row.problem_id,
            "ok": ok,
            "status_code": resp.status_code,
        }
        if not ok:
            entry["body"] = resp.text[:500]  # 원인 규명용(2026-08-22 규칙 ②)
        results.append(entry)
    return results


def _build_selector(args: argparse.Namespace) -> RecallSelector:
    return RecallSelector(
        run_id=args.run_id,
        prompt_version=args.prompt_version,
        model_name=args.model,
        seed=args.seed,
        input_sha256=args.input_sha256,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI — 선별 열거(기본) / 처분(`--apply`). 판정은 exit code로 한다.

    exit 0 = 매치 있음(열거 성공) · 1 = 매치 0건 또는 처분 실패 · 2 = 인자·입력 오류
    또는 **불완전한 계획으로의 처분 거부**(읽지 못한 행이 있는데 --apply — 측정 실패).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.generation_recall",
        description=(
            "생성 산출물 리콜(EOS-97) — genlog JSONL을 셀렉터로 선별해 처분 계획을 내고, "
            "--apply 시 기존 PATCH /v1/problems/{id}로 격리한다(dry-run 기본)."
        ),
    )
    parser.add_argument(
        "--genlog",
        type=Path,
        required=True,
        help=(
            "생성 로그 JSONL 경로(<out>.genlog.jsonl). DB 직접 조회는 미지원 — "
            "모듈 docstring 참조."
        ),
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        action="append",
        default=None,
        help=(
            "코퍼스 JSONL 경로(반복 가능·<out>.jsonl). cu_slug → problem_id를 해결해 배치 "
            "산출물을 격리 대상으로 승격한다. 없으면 배치 genlog는 problem_id가 전부 None이라 "
            "격리 가능 대상이 구조적으로 0건이다(모듈 docstring '정체성 해결')."
        ),
    )
    parser.add_argument("--run-id", default=None, help="회차 식별자 완전 일치.")
    parser.add_argument(
        "--prompt-version",
        default=None,
        help="프롬프트 정본 식별자 접두 일치(예 'l3.equivalent@sha256:aa31').",
    )
    parser.add_argument("--model", default=None, help="모델명 완전 일치.")
    parser.add_argument("--seed", type=int, default=None, help="샘플링 시드 완전 일치.")
    parser.add_argument(
        "--input-sha256",
        default=None,
        help=f"입력 스냅샷 해시 접두 일치(최소 {MIN_HASH_PREFIX}자).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "열거 상한(기본 없음 — **전건**). 지정하면 잘린 사실과 분모를 함께 낸다"
            "(CLAUDE.md: 도구가 알아서 자르는 출력을 부재 판정에 쓰면 안 된다). "
            "표시 전용이라 --apply와 함께 쓸 수 없다."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제로 격리 PATCH를 보낸다(기본은 dry-run). --api-base·--token 필요.",
    )
    parser.add_argument("--api-base", default=None, help="API 베이스 URL(--apply 시 필수).")
    parser.add_argument("--token", default=None, help="관리자 토큰(--apply 시 필수).")
    parser.add_argument(
        "--reason", default=None, help="격리 사유(--apply 시 필수) — 계약 §3 의무 필드."
    )
    args = parser.parse_args(argv)

    selector = _build_selector(args)
    if selector.is_empty():
        # 셀렉터 없는 리콜은 "전건 처분"이다 — 사고를 기본값으로 두지 않는다.
        parser.error(
            "셀렉터를 하나 이상 지정해야 한다"
            "(--run-id/--prompt-version/--model/--seed/--input-sha256)."
        )
    for name, value in (
        ("--input-sha256", args.input_sha256),
        ("--prompt-version", args.prompt_version),
    ):
        if value is not None and len(value) < MIN_HASH_PREFIX:
            parser.error(f"{name}는 최소 {MIN_HASH_PREFIX}자여야 한다(받은 값 {value!r}).")
    if args.limit is not None and args.limit <= 0:
        parser.error(f"--limit는 1 이상이어야 한다(받은 값 {args.limit}).")
    if args.limit is not None and args.apply:
        # 표시 상한과 처분 범위가 갈리면 **보이는 것보다 많이 격리된다** — 미리보기가 더
        # 넓은 파괴를 승인하는 형태(#992 P2). 잘라서 처분하는 대신 조합 자체를 거부한다:
        # 범위를 좁히려면 셀렉터를 좁혀야지 표시 상한을 쓰면 안 된다.
        parser.error(
            "--limit와 --apply는 함께 쓸 수 없다 — 표시 상한이 처분 범위를 결정하면 안 된다."
        )
    if args.apply and not all((args.api_base, args.token, args.reason)):
        parser.error("--apply에는 --api-base·--token·--reason이 모두 필요하다(계약 §5 3필드 기입).")

    if not args.genlog.exists():
        # 파일 부재는 "매치 0건"이 아니라 **측정 실패**다(불량 0% 위장 금지).
        sys.stderr.write(f"[측정 실패] genlog 파일 없음: {args.genlog}\n")
        return 2

    corpus_paths: list[Path] = list(args.corpus or [])
    missing_corpus = [p for p in corpus_paths if not p.exists()]
    if missing_corpus:
        joined = ", ".join(str(p) for p in missing_corpus)
        sys.stderr.write(f"[측정 실패] 코퍼스 파일 없음: {joined}\n")
        return 2
    slug_index: dict[str, str] | None = None
    index_errors: list[str] = []
    if corpus_paths:
        slug_index, index_errors = load_slug_index(corpus_paths)

    logs, load_errors = load_generation_logs_jsonl(args.genlog)
    all_errors = [*load_errors, *index_errors]
    plan = build_plan(logs, selector, load_errors=all_errors, slug_index=slug_index)
    payload = plan.to_json()
    payload["dry_run"] = not args.apply
    payload["slug_index_size"] = len(slug_index) if slug_index is not None else 0

    if args.limit is not None:
        # 자를 때는 **자른 사실과 분모**를 함께 낸다.
        payload["quarantinable"] = payload["quarantinable"][: args.limit]
        payload["unquarantinable"] = payload["unquarantinable"][: args.limit]
        payload["truncated"] = {
            "limit": args.limit,
            "quarantinable_total": plan.to_json()["quarantinable_count"],
            "unquarantinable_total": plan.to_json()["unquarantinable_count"],
        }

    if args.apply and all_errors:
        # 불완전한 계획으로는 처분하지 않는다(#992 P1-2). 건너뛴 행이 바로 이 회차 소산일
        # 수 있고, 그러면 "처분 완료"인데 결함이 노출된 채 남는다. **PATCH를 한 건도 보내기
        # 전에** 거부하고 측정 실패로 끝낸다 — 부분 처분은 전건 처분보다 위험하다.
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        sys.stderr.write(
            f"[측정 실패] 읽지 못한 행 {len(all_errors)}건이 있어 --apply를 거부한다 — 그 행이 "
            f"이 회차 소산이면 격리에서 빠진다. 첫 사유: {all_errors[0]}\n"
        )
        return 2

    if args.apply:
        with httpx.Client(
            base_url=args.api_base, headers={"Authorization": f"Bearer {args.token}"}
        ) as client:
            payload["applied"] = apply_quarantine(plan, client=client, reason=args.reason)

    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if all_errors:
        sys.stderr.write(f"[로드 실패 {len(all_errors)}행] 첫 사유: {all_errors[0]}\n")
    if plan.corpus_only:
        hint = "" if corpus_paths else " --corpus로 코퍼스 사이드카를 주면 격리 대상으로 승격된다."
        sys.stderr.write(
            f"[격리 불가·재생성 대상 {len(plan.corpus_only)}건] cu_slug는 있으나 problem_id "
            f"미해결 — 코퍼스 행 제거·재생성 대상이다(regeneration_slugs).{hint}\n"
        )
    if plan.unidentifiable:
        sys.stderr.write(
            f"[처분 대상 아님 {len(plan.unidentifiable)}건] cu_slug·problem_id 둘 다 없음 — "
            "정체성이 생기기 전에 실패한 호출이다(집계에서 빼지 않았다).\n"
        )
    if plan.matched == 0:
        sys.stderr.write(f"[매치 0건] 전체 {plan.scanned}행을 훑었다 — 셀렉터를 확인하라.\n")
        return 1
    if args.apply:
        failed = [entry for entry in payload["applied"] if not entry["ok"]]
        if failed:
            sys.stderr.write(
                f"[처분 실패 {len(failed)}건] 일부만 격리됐다 — 남은 결함이 살아 있다.\n"
            )
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
