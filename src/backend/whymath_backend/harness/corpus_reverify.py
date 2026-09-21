"""전 코퍼스 재검증 CLI — 초인간 검증 §2 "S6 상시성"(순수·결정론·LLM 0).

정본: `docs/standards/superhuman_verification_standard.md` §2 S6. 사람은 승인 후 문항을
다시 보지 않지만(재검수 0회), 기계는 **전 코퍼스를 매일 밤 전수 재검증**할 수 있다.
코퍼스 JSONL의 `verify{conditions, answer_map, answer_selection, solution_steps}` 재료로 각
문항의 정답을 Tier1(`verify_answer`) + Tier2 단계 연쇄(`verify_solution`·steps 보유 시·S2-02)
+ 수치 반례 fuzz(`counterexample_fuzz`)로 다시 검산해,
**fail이 하나라도 있으면 exit 1**(정본 변경·데이터 오염을 야간 CI가 즉시 잡는다).

정직성: verify 재료가 없거나 파싱 불가한 문항은 skip(집계에 skipped로)하고, *fail만*
게이트를 깬다 — 재검증 불가를 오염으로 오판하지 않는다(모르면 모른다). `--fuzz`를 켜면
수치 반례까지 돌려 심볼릭 사각지대도 훑는다(느리지만 야간 배치엔 적합).

사용:
    python -m whymath_backend.harness.corpus_reverify <코퍼스.jsonl>          # Tier1+근선택
    python -m whymath_backend.harness.corpus_reverify <코퍼스.jsonl> --fuzz   # 수치 반례까지
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.l3.equivalent.acceptance import (
    _CONCEPTUAL_VERIFIERS as _ACCEPTANCE_CONCEPTUAL_VERIFIERS,
)
from whymath_backend.l3.equivalent.counterexample_fuzz import fuzz_answer
from whymath_backend.l3.verify_answer import (
    AnswerVerdict,
    verify_answer,
    verify_root_aggregate,
    verify_root_selection,
)
from whymath_backend.l3.verify_solution import verify_solution

# 개념형 검증기 디스패치 — **acceptance의 표를 그대로 쓴다**(EOS-85 ④·사본 금지).
#
# 종전엔 같은 표를 여기 손으로 한 벌 더 적어 두고 주석에 "acceptance와 동일 표"라고 썼는데,
# **실제로는 달랐다**: acceptance 17종 · 여기 15종으로 `finite_probability`·`finite_count`가
# 빠져 있었다(2026-09-06 실측). 그 두 종은 `problem_bank_probability_finite_v0`에 34행
# (26+8) 실재하므로, 이 파일로 그 코퍼스를 재검증하면 두 종이 디스패치에 없어 **조용히
# 건너뛴다** — S6 상시성이 지키는 척만 하는 구간이 생긴다. 지금 야간 잡이 도는 코퍼스 3종
# (generated·rephrased·killer)에는 answer_kind가 0건이라 아직 드러나지 않았을 뿐이다.
#
# 사본을 고치는 대신 **없앤다**(CLAUDE.md "유지보수 지옥 ← truth source가 하나가 아님").
# 판정 어휘의 단일 원천은 `l3.equivalent.acceptance`이며, 이 모듈은 이미 같은 계층의
# `l3.verify_answer`·`l3.verify_solution`·`l3.equivalent.counterexample_fuzz`를 쓰고 있어
# 새 의존이 생기지 않는다.
_CONCEPTUAL_VERIFIERS: dict[str, Callable[[str | Sequence[str], str], AnswerVerdict]] = (
    _ACCEPTANCE_CONCEPTUAL_VERIFIERS
)

_EXIT_OK = 0
_EXIT_FAIL = 1


@dataclass(slots=True, frozen=True)
class ReverifyReport:
    """재검증 배치 결과 — 통과·실패·skip 카운트 + 실패 상세. 불변."""

    passed: int
    failed: int
    skipped: int
    failures: tuple[tuple[str, str], ...]  # (slug/id, 사유)

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.skipped


def _iter_records(text: str) -> list[dict[str, object]]:
    """JSONL 텍스트 → 레코드 리스트(빈 줄·주석 무시)."""
    records: list[dict[str, object]] = []
    for line_num, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_num}: {exc}") from exc
    return records


def _reverify_one(record: dict[str, object], *, use_fuzz: bool) -> tuple[str, str | None]:
    """레코드 1건 재검증 → (상태, 사유). 상태: 'pass'/'fail'/'skip'. 사유는 fail/skip 때만.

    verify 재료(conditions/answer_map)가 없으면 skip. Tier1 fail 또는 근 선택 위반 또는
    (use_fuzz 시) 수치 반례 fail이면 fail. unverifiable은 오염이 아니므로 skip 처리.
    """
    verify = record.get("verify")
    if not isinstance(verify, dict):
        return "skip", "verify 재료 없음"
    conditions = verify.get("conditions")
    answer_map = verify.get("answer_map")
    selection = verify.get("answer_selection")
    if not isinstance(conditions, str) or not isinstance(answer_map, dict):
        return "skip", "conditions/answer_map 형식 부적합"
    amap = {str(k): str(v) for k, v in answer_map.items()}

    # 근 집계(합/곱) 문항 — 답이 근이 아니라 근들의 집계값(Vieta)이라 Tier1(답이 근) 부적합.
    aggregate = verify.get("answer_aggregate")
    if aggregate in ("sum", "product"):
        claimed = record.get("answer")
        if not isinstance(claimed, str):
            return "skip", "근 집계 문항인데 answer 없음"
        agg = verify_root_aggregate(conditions, claimed, aggregate)
        if agg.state == "fail":
            return "fail", f"근 {aggregate} 불일치: {agg.reason}"
        if agg.state == "pass":
            return "pass", None
        return "skip", f"근 집계 unverifiable: {agg.reason}"

    # 개념형 문항 — 답이 값이 아니라 개수/판정(실근·극값 개수·일대일·등비급수 수렴)이라 SymPy
    # 독립 계산으로 재검증(축 확장은 _CONCEPTUAL_VERIFIERS에 등록).
    kind = verify.get("answer_kind")
    if isinstance(kind, str) and kind in _CONCEPTUAL_VERIFIERS:
        claimed = record.get("answer")
        if not isinstance(claimed, str):
            return "skip", "개념형 문항인데 answer 없음"
        cnt = _CONCEPTUAL_VERIFIERS[kind](conditions, claimed)
        if cnt.state == "fail":
            return "fail", f"{kind} 불일치: {cnt.reason}"
        if cnt.state == "pass":
            return "pass", None
        return "skip", f"{kind} unverifiable: {cnt.reason}"

    # Tier1 답 검산.
    tier1 = verify_answer(conditions, amap)
    if tier1.state == "fail":
        return "fail", f"Tier1 fail: {tier1.reason}"

    # 근 선택(있으면) — 위반은 fail, 확인 불가는 오염 아님.
    if isinstance(selection, str) and selection in ("largest", "smallest", "unique"):
        sel = verify_root_selection(conditions, amap, selection)  # type: ignore[arg-type]
        if sel.state == "fail":
            return "fail", f"근 선택({selection}) 위반: {sel.reason}"

    # Tier2 단계 재검증(S2-02) — verify.solution_steps가 있으면 전이 연쇄를 SymPy 동치로
    # 재검산한다(생성기는 100% 증명 가능 체인만 방출 — 수용 게이트가 적재 시 봉인). 여기서도
    # 모듈 정직 규약을 따른다: **incorrect(확정 오염)만 fail**, unverifiable은 오염으로
    # 오판하지 않는다(정본 SymPy 변화 등 — 적재 게이트가 재생성 시 잡는다).
    steps = verify.get("solution_steps")
    if isinstance(steps, list) and steps:
        tier2 = verify_solution([str(s) for s in steps])
        if tier2.has_incorrect:
            return "fail", (
                f"Tier2 단계 incorrect: 전이 {tier2.first_incorrect_index} "
                f"(correct {tier2.n_correct}·unverifiable {tier2.n_unverifiable})"
            )

    # 수치 반례 fuzz(옵션) — fail만 오염으로 본다.
    if use_fuzz:
        fuzz = fuzz_answer(conditions, amap, selection if isinstance(selection, str) else None)
        if fuzz.state == "fail":
            return "fail", f"수치 반례: {fuzz.reason}"

    # Tier1 pass면 통과, unverifiable(파라미터·판정 불가)은 skip(오염 아님).
    if tier1.state == "pass":
        return "pass", None
    return "skip", f"Tier1 unverifiable: {tier1.reason}"


def reverify_corpus(records: list[dict[str, object]], *, use_fuzz: bool) -> ReverifyReport:
    """레코드 리스트 전수 재검증 → 집계 리포트(순수)."""
    passed = failed = skipped = 0
    failures: list[tuple[str, str]] = []
    for record in records:
        ident = str(record.get("slug") or record.get("problem_id") or "?")
        state, reason = _reverify_one(record, use_fuzz=use_fuzz)
        if state == "pass":
            passed += 1
        elif state == "fail":
            failed += 1
            failures.append((ident, reason or ""))
        else:
            skipped += 1
    return ReverifyReport(passed=passed, failed=failed, skipped=skipped, failures=tuple(failures))


def format_report(report: ReverifyReport, *, path: str) -> str:
    """사람 가독 요약 — 통과/실패/skip + 실패 상세."""
    lines = [
        "=" * 60,
        "전 코퍼스 재검증 — 상시성(초인간 검증 S6)",
        "=" * 60,
        f"코퍼스: {path}",
        f"총 {report.total}  통과 {report.passed}  실패 {report.failed}  skip {report.skipped}",
    ]
    if report.failures:
        lines.append("[실패 상세]")
        for ident, reason in report.failures[:50]:
            lines.append(f"  {ident}: {reason}")
        if len(report.failures) > 50:
            lines.append(f"  … 외 {len(report.failures) - 50}건")
    lines.append("=" * 60)
    return "\n".join(lines)


def _run(paths: list[Path], *, use_fuzz: bool) -> int:
    exit_code = _EXIT_OK
    for path in paths:
        records = _iter_records(path.read_text(encoding="utf-8"))
        report = reverify_corpus(records, use_fuzz=use_fuzz)
        print(format_report(report, path=str(path)))
        if report.failed > 0:
            exit_code = _EXIT_FAIL
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """CLI — 코퍼스 JSONL(들) 전수 재검증. 실패 1건이라도 있으면 exit 1."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.corpus_reverify",
        description="전 코퍼스 verify 재료로 정답을 전수 재검산(상시성 게이트·S6).",
    )
    parser.add_argument("paths", nargs="+", help="코퍼스 JSONL 경로(들).")
    parser.add_argument(
        "--fuzz",
        action="store_true",
        help="수치 반례 fuzz까지 실행(느리지만 야간 배치용).",
    )
    args = parser.parse_args(argv)
    return _run([Path(p) for p in args.paths], use_fuzz=args.fuzz)


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
