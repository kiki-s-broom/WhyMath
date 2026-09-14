"""연령별 설명 언어 수준 결함주입 강등전(EOS-98 acceptance ④) — F7 미검출률 Wilson 상한 게이트.

`harness/analogy_fidelity_eval.py`(비유·예시 결함주입 강등전)를 그대로 미러한다: **정답지를
우리가 100% 아는** 결함 주입 시험지를 `l3/pedagogy/explanation_checker.py`(순수 규칙 검출기)에
태우고, 검출을 기계 판정해 Wilson 단측 **상한**으로 게이트한다(exit 0/1·점추정 금지). 라이브
LLM 0 — 스크립트 텍스트 주입(hermetic·결정론·고정 그리드)이라 컨테이너·CI에서 완결된다.

시험지 그리드 — 학년 레지스터(`SpeechGradeBand`)별 `l4/speech/profiles.py::PROFILES`의
`introduced_constructs`를 정답지로 삼는다:
  - violating(정답지=F7) 셀: 그 밴드에 **아직 도입되지 않은** 구조 어휘가 포함된 문장
    (초등 8종·중등 6종 — 고등/대학은 전 구조 도입 상태라 이 시험지에서 violating 셀이 없다.
    이는 회귀가 아니라 실제 제약 집합을 그대로 반영한 것이다 — `PROFILES` 정합).
  - clean(정답지=무결함) 셀: 그 밴드에 **이미 도입된** 구조·어휘만 쓴 문장 — 경계 스트레스로
    중등은 root/trig 포함 문장을 clean에 넣어 "도입된 구조는 잡지 않는다"를 함께 검증한다.

**변별력 대조군**(`--control`): 검출기를 무력화한 널 검출기로 같은 시험지를 돌리면 violating
셀이 전부 미검출 → 미검출률≈1 → exit 1이 *실측*된다("보호 장치 실패 주입 검증" 준수).

또한 `measure_generated_f7_rate`는 실제 생성 배치(`run_explanation_review`가 낸
`ExplanationOutcome` 시퀀스)의 F7 발생률을 Wilson 상한으로 계산한다 — "작동한 비율" 원칙(정상
응답이 알고리즘이 일했다는 증거가 아니다) 준수: 생성기 자체가 F7을 낼 확률을 별도로 실측한다.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.pedagogy.explanation_checker import check_explanation_language_level_defect
from whymath_backend.l4.speech.profiles import PROFILES
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand

if TYPE_CHECKING:
    from whymath_backend.l3.pedagogy.explanation_generator import ExplanationOutcome

_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 검출기 시그니처 — (band, text) → F7|None. 대조군 스왑 지점.
CheckerFn = Callable[[SpeechGradeBand, str], "GenerationFailureCode | None"]

_VARIANT_TOKENS = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"

# ──────────────────────────────────────────────────────────────────────────
# violating 은행 — (band, construct) → 그 밴드에 미도입된 구조 어휘를 쓴 문장
# ──────────────────────────────────────────────────────────────────────────
_초등_VIOLATING: dict[str, str] = {
    "root": "이 수의 제곱근을 구하면 원래 넓이를 만드는 한 변의 길이를 알 수 있다.",
    "trig": "사인 값을 이용하면 삼각형의 높이를 각도만으로 구할 수 있다.",
    "log": "로그를 쓰면 아주 큰 수의 자릿수를 손쉽게 셀 수 있다.",
    "integral": "적분을 하면 곡선 아래의 넓이를 정확히 구할 수 있다.",
    "sum": "시그마 기호로 여러 항을 한 번에 더한 값을 나타낸다.",
    "limit": "극한을 생각하면 한없이 가까워지는 값을 알 수 있다.",
    "derivative": "미분은 어떤 순간의 변화율을 구하는 방법이다.",
    "binom": "조합을 이용하면 순서를 따지지 않고 고르는 경우의 수를 셀 수 있다.",
}
_중등_VIOLATING: dict[str, str] = {
    "log": "로그를 쓰면 아주 큰 수의 자릿수를 손쉽게 셀 수 있다.",
    "integral": "적분을 하면 곡선 아래의 넓이를 정확히 구할 수 있다.",
    "sum": "시그마 기호로 여러 항을 한 번에 더한 값을 나타낸다.",
    "limit": "극한을 생각하면 한없이 가까워지는 값을 알 수 있다.",
    "derivative": "미분은 어떤 순간의 변화율을 구하는 방법이다.",
    "binom": "조합을 이용하면 순서를 따지지 않고 고르는 경우의 수를 셀 수 있다.",
}
# 고등·대학은 `PROFILES`상 전 구조 도입 상태라 violating 셀이 구조적으로 없다(정직 회계).
_VIOLATING_BANK: dict[SpeechGradeBand, dict[str, str]] = {
    SpeechGradeBand.초등: _초등_VIOLATING,
    SpeechGradeBand.중등: _중등_VIOLATING,
    SpeechGradeBand.고등: {},
    SpeechGradeBand.대학: {},
}

# ──────────────────────────────────────────────────────────────────────────
# clean 은행 — 그 밴드에 이미 도입된 어휘만 사용(경계 스트레스: 중등은 root/trig 포함)
# ──────────────────────────────────────────────────────────────────────────
_CLEAN_BANK: dict[SpeechGradeBand, tuple[str, ...]] = {
    SpeechGradeBand.초등: (
        "분수는 전체를 똑같이 나눈 것 중 몇 조각인지를 나타낸다.",
        "거듭제곱은 같은 수를 여러 번 곱한 것을 짧게 쓰는 방법이다.",
        "절댓값은 수직선에서 원점까지의 거리를 뜻한다.",
        "계승은 1부터 그 수까지를 차례로 곱한 값이다.",
    ),
    SpeechGradeBand.중등: (
        # 경계 스트레스 — root/trig는 중등에 도입됐으므로 등장해도 무결함이어야 한다.
        "제곱근은 어떤 수를 두 번 곱해서 그 수가 되게 하는 값이다.",
        "사인은 직각삼각형에서 각도와 변의 비율을 나타낸다.",
        "분수와 거듭제곱을 함께 쓰면 더 복잡한 식도 나타낼 수 있다.",
    ),
    SpeechGradeBand.고등: (
        "미분은 순간의 변화율을 구하는 방법이고, 적분은 그 변화를 다시 쌓아 넓이를 구하는 "
        "방법이다.",
        "로그와 지수는 서로 역함수 관계에 있어 큰 수를 다루기 쉽게 해 준다.",
        "극한은 시그마로 나타낸 합이 무한히 이어질 때 다가가는 값을 뜻한다.",
    ),
    SpeechGradeBand.대학: (
        "미분과 적분은 해석학의 기본 도구이며, 집합과 논리 기호로 그 정의를 엄밀히 서술한다.",
        "극한의 엡실론-델타 정의는 시그마·로그를 포함한 여러 구조 위에서 성립한다.",
    ),
}


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """시험지 1건 — (band×construct×카테고리) 셀. 정답지 = 기대 F7 여부(clean은 None)."""

    band: SpeechGradeBand
    axis: str  # construct 키(clean 셀은 "-")
    category: str  # "violating" | "clean"
    text: str
    expected: GenerationFailureCode | None


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    spec: CaseSpec
    detected: GenerationFailureCode | None
    missed: bool  # violating인데 F7 미검출(false negative)
    false_alarm: bool  # clean인데 F7 검출(false positive)


def _real_checker(band: SpeechGradeBand, text: str) -> GenerationFailureCode | None:
    """정상 검출기 — `PROFILES`에서 밴드별 도입 구조를 조회해 그대로 판정에 주입."""
    return check_explanation_language_level_defect(
        band, text, introduced_constructs=PROFILES[band].introduced_constructs
    )


def _null_checker(band: SpeechGradeBand, text: str) -> GenerationFailureCode | None:
    """대조군 널 검출기 — 무력화(항상 무결함). 보호 계층 OFF의 변별력 실측용."""
    del band, text
    return None


def build_exam(n_per_cell: int) -> list[CaseSpec]:
    """전수 그리드 × 셀당 n 변형 — 결정론(순서 고정·무숫자 변형 접미)."""
    if n_per_cell < 1:
        raise ValueError("n_per_cell은 1 이상이어야 합니다.")
    if n_per_cell > len(_VARIANT_TOKENS):
        raise ValueError(f"n_per_cell은 최대 {len(_VARIANT_TOKENS)}입니다(변형 토큰 한계).")
    cases: list[CaseSpec] = []
    for band in SpeechGradeBand:
        for construct, template in sorted(_VIOLATING_BANK[band].items()):
            for variant in range(n_per_cell):
                cases.append(
                    CaseSpec(
                        band=band,
                        axis=construct,
                        category="violating",
                        text=f"{template} ({_VARIANT_TOKENS[variant]}변형)",
                        expected=GenerationFailureCode.F7,
                    )
                )
        for template in _CLEAN_BANK[band]:
            for variant in range(n_per_cell):
                cases.append(
                    CaseSpec(
                        band=band,
                        axis="-",
                        category="clean",
                        text=f"{template} ({_VARIANT_TOKENS[variant]}변형)",
                        expected=None,
                    )
                )
    return cases


def _judge(spec: CaseSpec, detected: GenerationFailureCode | None) -> CaseOutcome:
    if spec.category == "violating":
        missed = detected != spec.expected
        return CaseOutcome(spec=spec, detected=detected, missed=missed, false_alarm=False)
    return CaseOutcome(spec=spec, detected=detected, missed=False, false_alarm=detected is not None)


def run_machine(cases: list[CaseSpec], checker: CheckerFn) -> list[CaseOutcome]:
    """전 케이스를 검출기에 태워 판정 — 순수·결정론(IO 0·LLM 0). checker 스왑이 대조 지점."""
    return [_judge(spec, checker(spec.band, spec.text)) for spec in cases]


@dataclass(frozen=True, slots=True)
class FidelityReport:
    violating_total: int
    missed: int
    clean_total: int
    false_alarm: int
    by_cell: dict[str, tuple[int, int]]

    def miss_upper_bound(self, confidence: float = 0.95) -> float:
        """미검출률 Wilson 단측 상한 — violating 셀이 0건이면 정의 불가(호출자가 가드)."""
        return wilson_upper_bound(self.missed, self.violating_total, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float:
        return wilson_upper_bound(self.false_alarm, self.clean_total, confidence)


def summarize(outcomes: list[CaseOutcome]) -> FidelityReport:
    violating_total = missed = clean_total = false_alarm = 0
    by_cell: dict[str, tuple[int, int]] = {}
    for outcome in outcomes:
        spec = outcome.spec
        key = f"{spec.band.value}/{spec.axis}/{spec.category}"
        bad, total = by_cell.get(key, (0, 0))
        if spec.category == "violating":
            violating_total += 1
            missed += int(outcome.missed)
            by_cell[key] = (bad + int(outcome.missed), total + 1)
        else:
            clean_total += 1
            false_alarm += int(outcome.false_alarm)
            by_cell[key] = (bad + int(outcome.false_alarm), total + 1)
    return FidelityReport(
        violating_total=violating_total,
        missed=missed,
        clean_total=clean_total,
        false_alarm=false_alarm,
        by_cell=by_cell,
    )


def render_report(report: FidelityReport, *, confidence: float, control: bool) -> str:
    banner = "연령별 설명 언어 수준(F7) 결함주입 강등전 (EOS-98)"
    if control:
        banner += " — [대조군: 널 검출기]"
    lines = ["=" * 64, banner + " — Wilson 상한 게이트", "=" * 64]
    lines.append(f"violating 셀: {report.violating_total}건 중 미검출 {report.missed}건")
    lines.append(
        f"  미검출률 Wilson 상한({confidence:.0%}): {report.miss_upper_bound(confidence):.4f}"
    )
    lines.append(f"clean 셀: {report.clean_total}건 중 오검출 {report.false_alarm}건")
    alarm_upper = report.false_alarm_upper_bound(confidence)
    lines.append(f"  오검출률 Wilson 상한({confidence:.0%}): {alarm_upper:.4f}")
    problem_cells = {k: v for k, v in report.by_cell.items() if v[0] > 0}
    if problem_cells:
        lines.append("[문제 셀 — (문제건수/총건수)]")
        for key in sorted(problem_cells):
            bad, total = problem_cells[key]
            lines.append(f"  {key}: {bad}/{total}")
    else:
        lines.append("[문제 셀 없음 — 전 셀 무결]")
    lines.append("[DEFERRED] SENTENCE_COMPLEXITY — 문장 난이도(가독성) 축은 규칙 판정 불가·미측정")
    lines.append("=" * 64)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# 실제 생성 배치의 F7 발생률 측정 — "작동한 비율" 원칙(정상 응답 ≠ 알고리즘이 일함)
# ──────────────────────────────────────────────────────────────────────────
_ALL_FAILURE_CODES: tuple[str, ...] = tuple(code.value for code in GenerationFailureCode)


@dataclass(frozen=True, slots=True)
class GeneratedF7Report:
    """실제 생성 배치(`ExplanationOutcome` 시퀀스)의 F-코드 발생 집계 — dense dict(8종 전량).

    `ops/validation_scorecard.py`의 dense-dict·canonical `.value` 관례를 따른다(`_fc_sum` 동형) —
    발생 0건인 코드도 키로 남겨 "관측 0 = 미측정"과 구별한다.
    """

    trials: int
    failure_counts: dict[str, int]

    def f7_rate_upper_bound(self, confidence: float = 0.95) -> float:
        """F7 발생률 Wilson 단측 상한 — "낮을수록 좋은" 결함율(오검출률과 동형 방향)."""
        if self.trials == 0:
            raise ValueError("trials=0 — 측정할 생성 결과가 없습니다(생성 배치를 먼저 실행).")
        return wilson_upper_bound(self.failure_counts["F7"], self.trials, confidence)


def measure_generated_f7_rate(outcomes: Sequence[ExplanationOutcome]) -> GeneratedF7Report:
    """생성·검수 배치 결과에서 F7 발생률 측정 재료(dense 8코드 dict)를 집계한다.

    `reject_reason`이 폐쇄 8코드 중 하나와 일치하는 건만 그 코드로 계상한다(구조 결함
    `empty_body` 등은 F-코드가 아니므로 집계에서 제외 — 이 게이트는 *콘텐츠 품질* 실패율만
    잰다). `outcomes`가 비어 있으면(trials=0) 나중에 `f7_rate_upper_bound` 호출 시 명시적으로
    거부한다(0건을 조용히 0%로 보고하지 않는다 — "관측 0 ≠ 확정 0").
    """
    counts: dict[str, int] = {code: 0 for code in _ALL_FAILURE_CODES}
    for outcome in outcomes:
        reason = outcome.reject_reason
        if reason in counts:
            counts[reason] += 1
    return GeneratedF7Report(trials=len(outcomes), failure_counts=counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.explanation_f7_eval",
        description=(
            "연령별 설명 언어 수준(F7) 결함주입 강등전 — 학년 레지스터별 미도입 구조 어휘의 "
            "미검출을 Wilson 상한으로 게이트한다(hermetic·라이브 LLM 0·exit 0/1)."
        ),
    )
    parser.add_argument("--n-per-cell", type=int, default=12, help="셀당 변형 수(표본 크기).")
    parser.add_argument("--confidence", type=float, default=0.95, help="Wilson 단측 신뢰수준.")
    parser.add_argument(
        "--max-miss-upper",
        type=float,
        default=0.05,
        help="미검출률 Wilson 상한 임계 — 초과면 exit 1(핵심 게이트).",
    )
    parser.add_argument(
        "--max-false-alarm-upper",
        type=float,
        default=0.2,
        help="오검출률 Wilson 상한 임계 — 초과면 exit 1(과차단 방지).",
    )
    parser.add_argument(
        "--control",
        action="store_true",
        help="변별력 대조군 — 검출기 무력화(널 검출기) 측정(미검출≈전량 실측돼 exit 1이 정상).",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로(선택).")
    args = parser.parse_args(argv)

    checker: CheckerFn = _null_checker if args.control else _real_checker
    outcomes = run_machine(build_exam(args.n_per_cell), checker)
    report = summarize(outcomes)
    print(render_report(report, confidence=args.confidence, control=args.control))
    if args.json is not None:
        payload = dataclasses.asdict(report)
        payload["miss_upper_bound"] = report.miss_upper_bound(args.confidence)
        payload["false_alarm_upper_bound"] = report.false_alarm_upper_bound(args.confidence)
        payload["control"] = args.control
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 리포트 저장: {args.json}")

    gate_ok = (
        report.miss_upper_bound(args.confidence) <= args.max_miss_upper
        and report.false_alarm_upper_bound(args.confidence) <= args.max_false_alarm_upper
    )
    verdict = "PASS" if gate_ok else "FAIL"
    print(
        f"게이트 판정(미검출 상한 ≤{args.max_miss_upper}·"
        f"오검출 상한 ≤{args.max_false_alarm_upper}): {verdict}"
    )
    return _EXIT_OK if gate_ok else _EXIT_GATE_FAIL


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
