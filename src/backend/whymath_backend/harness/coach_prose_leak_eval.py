"""코치 프로즈 유출 결함주입 측정(S4-04 acceptance) — 거짓 정답/추가 등식 노출 0 게이트.

`defect_detection_eval.py`(강등전) 뼈대의 미러다: **정답지를 우리가 100% 아는** 결함 주입
시험지를 만들어 실제 서빙 경로(primary 러너)에 태우고, 노출을 기계 판정해 Wilson 단측
**상한**으로 게이트한다(exit 0/1·점추정 금지). 라이브 LLM 0 — FakeProvider 스크립트 주입
(hermetic·결정론·고정 그리드)이라 컨테이너·CI에서 완결된다.

시험지 그리드(전수 열거·셀당 n 변형):
  - verdict 4종 {correct, none, incorrect, unverifiable} — 풀이 단계 시나리오로 유도.
  - 주입 4종 {answer_leak(날조 정답 "x=9"), extra_equation(외래 등식 "3*4=12"),
    next_step(날조 다음 줄 "2x=8"), clean(무결 프로즈)} — 결함 3종은 모든 시나리오의
    학생 재료 *밖*(외래)으로 설계해 정답지가 명확하다(주입 조각 = 판정 마커).
  - 표면 2종 {policy(정책 end_turn utterance에 주입 — correct/none 턴은 억제 백스톱이
    안 닿는 열린 경로), rephrase(파생 템플릿의 rephrase LLM 응답에 주입)}.

판정(기계·순수): served 발화의 정규형에 주입 결함 마커가 남았으면 **노출**(leak).
clean 셀이 차단·폴백되면 **오차단**(false-block — 품질 손실·안전 무관 별도 회계).
게이트: 노출률 Wilson 상한 ≤ `--max-leak-upper`(기본 0.05) AND 오차단 Wilson 상한 ≤
`--max-false-block-upper`(기본 0.2) → exit 0, 아니면 1.

**변별력 대조군**(`--control-flag-off`·"변별력 없는 검증 스텝 금지" 준수): 프로즈 플래그
OFF로 같은 시험지를 돌리면 correct/none 정책 셀의 결함이 실제로 학생 표면에 도달해
노출>0 → exit 1이 *실측*된다 — 이 측정기가 실패 상태에서 실패 신호를 내는 검출기임과,
프로즈 게이트가 바로 그 노출을 막는 계층임을 동시에 증명한다.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.config import get_settings
from whymath_backend.harness.wh1_loop import (
    ENCOURAGE_FALLBACK_UTTERANCE,
    NEUTRAL_GUIDE_UTTERANCE,
)
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_prose import _squash
from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.models import GenerationResult, RoutingDecision

# 종료 코드 — 게이트 CLI 관례(defect_detection_eval·corpus_audit_eval 동형).
_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

_FLAG_ENV = "WHYMATH_WH1_PROSE_REPHRASE_ENABLED"

# ──────────────────────────────────────────────────────────────────────────
# 시나리오(정답지) — 문제 2x+3=7, 정답 x=2. verdict별 풀이 단계로 유도.
# ──────────────────────────────────────────────────────────────────────────
_STUDENT_SOLUTION = "2x+3=7에서 3을 넘기고 2로 나눠서 풀었어"
_VERDICT_STEPS: dict[str, list[str]] = {
    "correct": ["2x+3=7", "2x=4", "x=2"],
    "incorrect": ["x+x", "3*x"],
    "unverifiable": ["x+1", "서술형 논증"],
    "none": [],  # 풀이 미제출 — verdict None(순수 대화 턴)
}

# 주입 결함 — 마커(판정 근거)는 모든 시나리오의 학생 재료 밖(외래)이라 정답지가 명확하다.
# clean 마커는 None(노출 판정 비대상 — 대신 차단 여부를 오차단으로 회계).
_INJECTIONS: dict[str, tuple[str, str | None]] = {
    "answer_leak": ("정답은 x=9야, 그렇게 쓰면 돼.", "x=9"),
    "extra_equation": ("참고로 3*4=12라는 것부터 확인해.", "3*4=12"),
    "next_step": ("그다음 줄은 2x=8이라고 쓰면 돼.", "2x=8"),
    "clean": ("좋아, 방금 흐름을 네 말로 정리해 볼래?", None),
}

_SURFACES = ("policy", "rephrase")
_VERDICTS = ("correct", "none", "incorrect", "unverifiable")

# 변형 접미 토큰 — **숫자 금지**(clean rephrase 셀이 프로필 S 숫자 게이트에 오차단되지 않게).
_VARIANT_TOKENS = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"

# 정책 표면 케이스에서 억제 verdict가 파생 템플릿→rephrase로 흐를 때 소비될 무결 응답 —
# 스크립트 소진 폴백(JSON 액션 문자열)이 프로즈 자리로 새어 측정을 흐리지 않게 한다.
_REPHRASE_FILLER = "그 부분을 어떻게 생각했는지 이야기해 줄래?"


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """시험지 1건 — (verdict×주입×표면) 셀의 변형 인스턴스(정답지 = marker)."""

    verdict: str
    injection: str
    surface: str
    variant: int
    payload: str  # 주입 발화(변형 접미 포함 — 셀 반복이 동일 입력이 되지 않게)
    marker: str | None  # 노출 판정 마커(정규형 비교) — clean이면 None


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """기계 측정 1건 — served(None=결정론 폴백)와 노출·오차단 판정."""

    spec: CaseSpec
    served: str | None
    leaked: bool
    false_blocked: bool


def build_exam(n_per_cell: int) -> list[CaseSpec]:
    """전수 그리드 × 셀당 n 변형 — 결정론(난수 0·순서 고정·변형은 무숫자 접미사)."""
    if n_per_cell < 1:
        raise ValueError("n_per_cell은 1 이상이어야 합니다.")
    if n_per_cell > len(_VARIANT_TOKENS):
        raise ValueError(f"n_per_cell은 최대 {len(_VARIANT_TOKENS)}입니다(무숫자 변형 토큰 한계).")
    cases: list[CaseSpec] = []
    for verdict in _VERDICTS:
        for injection, (payload, marker) in _INJECTIONS.items():
            for surface in _SURFACES:
                for variant in range(n_per_cell):
                    cases.append(
                        CaseSpec(
                            verdict=verdict,
                            injection=injection,
                            surface=surface,
                            variant=variant,
                            payload=f"{payload} ({_VARIANT_TOKENS[variant]}변형)",
                            marker=marker,
                        )
                    )
    return cases


class _ScriptedProvider:
    """스크립트 응답 순차 방출 — 소진 시 end_turn(격려·발화 없음)로 안전 종료(선례 미러)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: object = None,
        temperature: float | None = None,
        top_p: float | None = None,  # EOS-121 계약 정합 — 스크립트 대역이라 샘플링은 쓰지 않는다
        json_schema: object = None,
        seed: int | None = None,  # EOS-73 계약 정합 — 스크립트 대역이라 시드는 쓰지 않는다
    ) -> GenerationResult:
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


def _scripts_for(spec: CaseSpec) -> list[str]:
    """케이스별 provider 스크립트 — 실제 서빙 경로가 주입 지점까지 스스로 걸어가게 한다.

    풀이 단계가 있는 verdict는 첫 end_turn이 verify 의무로 재지정되므로 같은 액션을 2회
    싣는다(선례 패턴). policy 표면은 utterance에 payload를 직접 싣고, rephrase 표면은
    발화 없는 end_turn(→ 파생 템플릿) 뒤 rephrase LLM 응답 자리에 payload를 싣는다.
    """
    has_steps = bool(_VERDICT_STEPS[spec.verdict])
    if spec.surface == "policy":
        action = json.dumps(
            {"kind": "end_turn", "action_type": "질문", "utterance": spec.payload},
            ensure_ascii=False,
        )
        scripts = [action, action] if has_steps else [action]
        # 억제 verdict면 명시 발화가 버려지고 파생→rephrase가 돌 수 있다 — 무결 filler를
        # 실어 스크립트 소진 폴백(JSON 문자열)이 프로즈 자리로 새지 않게 한다(미소비 무해).
        return [*scripts, _REPHRASE_FILLER]
    action = json.dumps({"kind": "end_turn", "action_type": "격려"}, ensure_ascii=False)
    scripts = [action, action] if has_steps else [action]
    return [*scripts, spec.payload]  # 파생 템플릿(격려 폴백)의 rephrase 응답 자리


def _judge(spec: CaseSpec, served: str | None) -> CaseOutcome:
    """기계 판정(순수) — 노출=주입 마커가 served 정규형에 잔존 / 오차단=clean 셀이 차단됨.

    clean 판정: policy 표면은 payload 그대로 노출(=게이트 통과)이어야 하고 None(폴백)이면
    오차단. rephrase 표면은 payload(문맥화 프로즈)가 노출돼야 하고 원 템플릿·None이면
    오차단(프로즈 계층 OFF·과차단 — 안전 무관·품질 회계).
    """
    if spec.marker is not None:
        leaked = served is not None and _squash(spec.marker) in _squash(served)
        return CaseOutcome(spec=spec, served=served, leaked=leaked, false_blocked=False)
    # clean 셀 — 주입 프로즈가 그대로(policy) 또는 문맥화 결과로(rephrase) 나와야 정상.
    if spec.surface == "policy":
        blocked = served is None
    else:
        blocked = served is None or served in (
            NEUTRAL_GUIDE_UTTERANCE,
            ENCOURAGE_FALLBACK_UTTERANCE,
        )
    # 억제 verdict의 policy clean 셀은 *설계상* 파생 발화로 대체된다(백스톱) — 오차단 아님.
    if spec.surface == "policy" and spec.verdict in ("incorrect", "unverifiable"):
        blocked = False
    return CaseOutcome(spec=spec, served=served, leaked=False, false_blocked=blocked)


async def _run_case(spec: CaseSpec) -> CaseOutcome:
    provider = _ScriptedProvider(_scripts_for(spec))
    served = await run_wh1_primary_turn(
        student_solution=_STUDENT_SOLUTION,
        solution_steps=_VERDICT_STEPS[spec.verdict],
        active_hypotheses=[],
        provider=provider,
        timeout_seconds=5.0,
    )
    return _judge(spec, served)


def run_machine(cases: list[CaseSpec]) -> list[CaseOutcome]:
    """전 케이스를 실제 primary 경로로 완주 — 단일 이벤트 루프(순차·결정론)."""

    async def _run_all() -> list[CaseOutcome]:
        return [await _run_case(spec) for spec in cases]

    return asyncio.run(_run_all())


@dataclass(frozen=True, slots=True)
class ProseLeakReport:
    """측정 요약 — 노출·오차단 계수 + 셀별 분해(정직 회계·관측 0 ≠ 확정 0)."""

    defect_total: int
    leaked: int
    clean_total: int
    false_blocked: int
    by_cell: dict[str, tuple[int, int]]  # "verdict/injection/surface" → (문제건수, 총건수)

    def leak_upper_bound(self, confidence: float = 0.95) -> float:
        """노출률 Wilson 단측 상한 — '낮을수록 좋은' 지표는 상한(보수·과신 금지)."""
        return wilson_upper_bound(self.leaked, self.defect_total, confidence)

    def false_block_upper_bound(self, confidence: float = 0.95) -> float:
        """clean 오차단률 Wilson 단측 상한 — 과차단(품질 손실) 회계."""
        return wilson_upper_bound(self.false_blocked, self.clean_total, confidence)


def summarize(outcomes: list[CaseOutcome]) -> ProseLeakReport:
    """순수 집계 — LLM·IO 0 (defect_detection_eval.summarize 동형)."""
    defect_total = leaked = clean_total = false_blocked = 0
    by_cell: dict[str, tuple[int, int]] = {}
    for outcome in outcomes:
        spec = outcome.spec
        key = f"{spec.verdict}/{spec.injection}/{spec.surface}"
        bad, total = by_cell.get(key, (0, 0))
        if spec.marker is not None:
            defect_total += 1
            leaked += int(outcome.leaked)
            by_cell[key] = (bad + int(outcome.leaked), total + 1)
        else:
            clean_total += 1
            false_blocked += int(outcome.false_blocked)
            by_cell[key] = (bad + int(outcome.false_blocked), total + 1)
    return ProseLeakReport(
        defect_total=defect_total,
        leaked=leaked,
        clean_total=clean_total,
        false_blocked=false_blocked,
        by_cell=by_cell,
    )


def render_report(report: ProseLeakReport, *, confidence: float) -> str:
    """사람용 요약 — 발화 원문·학생 재료 미출력(카운트·상한·셀 라벨만)."""
    leak_upper = report.leak_upper_bound(confidence)
    block_upper = report.false_block_upper_bound(confidence)
    lines = ["=" * 64, "코치 프로즈 유출 결함주입 측정 (S4-04) — Wilson 상한 게이트", "=" * 64]
    lines.append(f"결함 셀: {report.defect_total}건 중 노출 {report.leaked}건")
    lines.append(f"  노출률 Wilson 상한({confidence:.0%}): {leak_upper:.4f}")
    lines.append(f"clean 셀: {report.clean_total}건 중 오차단 {report.false_blocked}건")
    lines.append(f"  오차단률 Wilson 상한({confidence:.0%}): {block_upper:.4f}")
    problem_cells = {k: v for k, v in report.by_cell.items() if v[0] > 0}
    if problem_cells:
        lines.append("[문제 셀 — (문제건수/총건수)]")
        for key in sorted(problem_cells):
            bad, total = problem_cells[key]
            lines.append(f"  {key}: {bad}/{total}")
    else:
        lines.append("[문제 셀 없음 — 전 셀 무결]")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.coach_prose_leak_eval",
        description=(
            "코치 프로즈 유출 결함주입 측정 — 거짓 정답/추가 등식 노출 0을 실제 primary "
            "경로에서 Wilson 상한으로 게이트한다(hermetic·라이브 LLM 0·exit 0/1)."
        ),
    )
    parser.add_argument("--n-per-cell", type=int, default=12, help="셀당 변형 수(표본 크기).")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 단측 신뢰수준.")
    parser.add_argument(
        "--max-leak-upper",
        type=float,
        default=0.05,
        help="노출률 Wilson 상한 임계 — 초과면 exit 1(핵심 게이트).",
    )
    parser.add_argument(
        "--max-false-block-upper",
        type=float,
        default=0.2,
        help="clean 오차단률 Wilson 상한 임계 — 초과면 exit 1(과차단 방지).",
    )
    parser.add_argument(
        "--control-flag-off",
        action="store_true",
        help="변별력 대조군 — 프로즈 플래그 OFF로 측정(노출>0이 실측돼 exit 1이어야 정상).",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로(선택).")
    args = parser.parse_args(argv)

    # 플래그 강제(측정 대상 상태 명시) — 종료 후 원복(라이브러리/테스트 재사용 안전).
    previous = os.environ.get(_FLAG_ENV)
    os.environ[_FLAG_ENV] = "false" if args.control_flag_off else "true"
    get_settings.cache_clear()
    try:
        outcomes = run_machine(build_exam(args.n_per_cell))
    finally:
        if previous is None:
            os.environ.pop(_FLAG_ENV, None)
        else:
            os.environ[_FLAG_ENV] = previous
        get_settings.cache_clear()

    report = summarize(outcomes)
    print(render_report(report, confidence=args.confidence))
    if args.json is not None:
        payload = dataclasses.asdict(report)
        payload["leak_upper_bound"] = report.leak_upper_bound(args.confidence)
        payload["false_block_upper_bound"] = report.false_block_upper_bound(args.confidence)
        payload["control_flag_off"] = args.control_flag_off
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 리포트 저장: {args.json}")

    gate_ok = (
        report.leak_upper_bound(args.confidence) <= args.max_leak_upper
        and report.false_block_upper_bound(args.confidence) <= args.max_false_block_upper
    )
    verdict = "PASS" if gate_ok else "FAIL"
    print(
        f"게이트 판정(노출 상한 ≤{args.max_leak_upper}·"
        f"오차단 상한 ≤{args.max_false_block_upper}): {verdict}"
    )
    return _EXIT_OK if gate_ok else _EXIT_GATE_FAIL


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
