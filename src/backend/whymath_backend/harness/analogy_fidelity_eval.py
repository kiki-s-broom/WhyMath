"""비유·예시 결함주입 강등전(PED-09 acceptance ③) — 검출기 미검출률 Wilson 상한 게이트.

정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §6.3 — "`analogy_fidelity_eval`
결함주입 강등전 신설(CLI exit 0/1·`pedagogy_pack_fidelity_eval` 선례)". 그 선례를 그대로
미러한다: **정답지를 우리가 100% 아는** 결함 주입 시험지를 만들어
`l3/pedagogy/analogy_checker`(순수 규칙 검출기)에 태우고, 검출을 기계 판정해 Wilson 단측
**상한**으로 게이트한다(exit 0/1·점추정 금지). 라이브 LLM 0 — 스크립트 텍스트 주입
(hermetic·결정론·고정 그리드)이라 컨테이너·CI에서 완결된다.

시험지 그리드(전수 열거·셀당 n 변형) — 04g §6.3 결함 축의 규칙 검출 가능 프록시 전량:
  - violating(정답지=결함) 셀: grain×축별 6 템플릿
      · analogy/MISSING_BREAK_CLAUSE — 한계 명시가 전무한 비유(①-a 오개념 유발 위험 구조)
      · analogy/OVERIDENTIFICATION — "완전히 같다/똑같다/그 자체" 동일시 단정(①-b)
      · analogy/DEFINITION_USURPATION — 비유가 정의를 참칭(②)
      · analogy/GAMIFIED · example/GAMIFIED — 게임화 메커닉 산출(④ — acceptance "게임형
        산출 0 검사"의 검출력 측정 축)
      · example/ANSWER_LEAK — 예시 본문에 정답 노출(③)
  - clean(정답지=무결함) 셀: grain별 6 템플릿 — **경계 스트레스** 포함: 한계 명시를 갖춘
    정상 비유("정의가 아니라 디딤돌"), 수학 소재로서의 게임 언급("주사위 게임"·"보드게임" —
    게임화 메커닉이 아니므로 잡으면 오검출), 정답 미노출 예시. 검출이 하나라도 나오면
    **오검출**(false alarm·과차단 회계).

의미론 축(SEMANTIC_MISCONCEPTION)은 규칙 판정 불가라 **이 시험지에 없다** — 검출기의
DEFERRED_DEFECT_AXES가 그 공백을 명시하며, 이 eval은 규칙 검출 가능 축의 변별력만 주장한다
(정직한 커버리지·overclaim 금지).

**변별력 대조군**(`--control`·"변별력 없는 검증 스텝 금지" 준수): 검출기를 무력화한 널 검출기
(항상 빈 튜플)로 같은 시험지를 돌리면 violating 셀이 전부 미검출 → 미검출률≈1 → exit 1이
*실측*된다 — (a) 시험지에 실제 결함이 있고 (b) 정상 경로의 0 미검출이 검출기 덕분임을 동시에
증명한다(pedagogy_pack_fidelity_eval `--control` 동형 철학).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from whymath_backend.harness.wilson import wilson_upper_bound
from whymath_backend.l3.pedagogy.analogy_checker import (
    check_analogy_defects,
    check_example_defects,
)

# 종료 코드 — 게이트 CLI 관례(pedagogy_pack_fidelity_eval·coach_prose_leak_eval 동형).
_EXIT_OK = 0
_EXIT_GATE_FAIL = 1

# 검출기 시그니처 — (grain, text, answer) → 결함 코드 튜플. 대조군 스왑 지점.
CheckerFn = Callable[[str, str, "str | None"], tuple[str, ...]]

# 변형 접미 토큰 — 무숫자·무신호(검출 어휘에 없는 한글)라 셀 반복이 동일 입력이 되지 않게 하되
# 검출 결과는 바꾸지 않는다(pedagogy_pack_fidelity_eval 동형).
_VARIANT_TOKENS = "가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허"

# ANSWER_LEAK 축의 주입 정답 — violating 본문에 이 값이 노출되고 clean 본문에는 없다.
_LEAK_ANSWER = "12"


# ──────────────────────────────────────────────────────────────────────────
# 결함 축별 violating 은행 (정답지=결함) — 각 6 템플릿
# ──────────────────────────────────────────────────────────────────────────
# ①-a 한계 명시 부재 — BREAK_CLAUSE_SIGNALS 어휘가 전무한 비유(빗댐만 있고 깨짐이 없다).
_MISSING_BREAK_VIOLATING: tuple[str, ...] = (
    "함수는 자판기와 같아. 동전을 넣으면 음료가 나오듯 입력을 넣으면 출력이 나온다.",
    "극한은 과녁으로 날아가는 화살과 같다. 계속 가까워진다.",
    "미분은 순간의 속도계와 같다. 속도계 바늘이 곧 기울기다.",
    "집합은 서랍장과 같다. 물건을 서랍에 나눠 담듯 원소를 담는다.",
    "확률은 날씨 예보와 같다. 내일 비가 올 가능성을 숫자로 말해 준다.",
    "수열은 계단과 같다. 한 칸씩 오르며 다음 항으로 간다.",
)

# ①-b 동일시 단정 — 완전 동일성 주장("~처럼"이 아니라 "완전히 같다").
_OVERIDENTIFICATION_VIOLATING: tuple[str, ...] = (
    "함수는 자판기와 완전히 같다. 자판기를 알면 함수를 아는 것이다.",
    "극한은 화살이 과녁에 닿는 것과 똑같다.",
    "미분은 속도계 그 자체다. 속도계를 읽으면 된다.",
    "확률은 주사위 놀이와 다름없다.",
    "집합은 서랍장과 정확히 같다.",
    "수열은 계단과 완전히 같은 것이다.",
)

# ② 정의 참칭 — 정의 단정 신호 보유 + 면책(정의가 아니다) 부재.
_DEFINITION_USURPATION_VIOLATING: tuple[str, ...] = (
    "함수란 자판기라고 정의된다. 그렇게 외우면 된다.",
    "극한을 정의하면 화살이 과녁에 다가가는 일이다.",
    "속도계 비유, 이것이 정의다. 속도계가 가리키는 값이 미분이다.",
    "집합의 정의는 바로 서랍장이다.",
    "확률은 가능성의 놀이로 정의된다. 이대로 받아들이자.",
    "수열은 계단이라고 정의하면 된다.",
)

# ④ 게임형(비유 grain) — 게임화 메커닉 어휘.
_GAMIFIED_ANALOGY_VIOLATING: tuple[str, ...] = (
    "함수를 공부하면 경험치가 쌓이고 레벨업한다. 자판기 비유로 퀘스트를 깨자.",
    "극한 개념을 스테이지 삼아 하나씩 미션 클리어 하듯 나아가자.",
    "미분 문제를 풀 때마다 포인트 적립이 되고 랭킹이 오른다.",
    "집합 개념을 아이템처럼 모아 보자.",
    "확률 단원을 게임화 해서 보상을 획득 하며 배우자.",
    "수열 공부는 콤보를 쌓는 일이다. 연속으로 맞히면 뱃지를 받는다.",
)

# ③ 정답 유출(예시 grain) — 본문에 정답(_LEAK_ANSWER)이 그대로 노출.
_ANSWER_LEAK_VIOLATING: tuple[str, ...] = (
    "편의점 아르바이트를 하는 지우의 근무 시간 이야기 — 답은 12 시간이라고 본문에 적는다.",
    "동아리 발표에 필요한 의자 수를 세어 보니 정답은 12 개였다.",
    "매점 앞 줄에서 기다리는 사람을 세는 상황. 결국 12 명이므로 그대로 쓰면 된다.",
    "버스 배차 간격을 재는 이야기 속에서 간격은 12 분으로 결론 난다.",
    "화분에 물을 주는 주기를 정하는 문제 — 주기는 12 일이라는 결론까지 적어 둔다.",
    "케이크를 나누는 상황에서 조각 수는 12 조각이라고 미리 알려 준다.",
)

# ④ 게임형(예시 grain) — 실생활 예시를 게임화 메커닉으로 포장.
_GAMIFIED_EXAMPLE_VIOLATING: tuple[str, ...] = (
    "학교 매점 구매 상황을 퀘스트로 만들어 미션 클리어 때마다 경험치를 주자.",
    "용돈 기입장 예시를 게임화 해서 포인트 적립 이벤트로 바꾼다.",
    "버스 시간표 읽기를 스테이지 방식으로 깨며 레벨업 하는 이야기.",
    "마트 할인 계산을 맞히면 뱃지를 획득하는 상황극.",
    "도서관 좌석 배치를 아이템 뽑기처럼 구성한 예시.",
    "분식집 주문 금액 맞히기 랭킹을 만들어 콤보 보너스를 주는 장면.",
)

# ──────────────────────────────────────────────────────────────────────────
# clean 은행 (정답지=무결함) — grain별 6 템플릿·경계 스트레스 포함
# ──────────────────────────────────────────────────────────────────────────
# 비유 clean — 전 축 무결함: 한계 명시(깨짐·차이·주의) 보유 + 빗댐 서법 + 정의 면책 스트레스.
_CLEAN_ANALOGY: tuple[str, ...] = (
    "함수는 자판기와 같아. 다만 실제 함수는 버튼 없는 입력도 받는다는 점이 다르다 — "
    "이 비유는 정의가 아니라 디딤돌이다.",
    "극한은 과녁에 다가가는 화살처럼 생각할 수 있어. 하지만 화살은 결국 닿는 반면 "
    "극한은 닿음을 요구하지 않는다는 차이가 있다.",
    "미분은 속도계와 비슷하다. 주의: 속도계는 실제 장치지만 미분은 순간 변화율이라는 "
    "점에서 비유가 깨진다.",
    "집합을 서랍장처럼 떠올려 보자. 다만 서랍은 같은 물건을 두 칸에 둘 수 있지만 "
    "집합의 원소는 중복을 세지 않는다는 점이 다르다.",
    "확률은 날씨 예보와 같이 가능성을 숫자로 말한다. 물론 예보는 경험적 추정이고 "
    "수학적 확률은 모형에서 계산된다는 한계를 기억하자.",
    "수열은 계단을 오르는 일과 닮았다. 그러나 계단은 유한하지만 수열은 무한히 이어질 "
    "수 있다는 점에서 이 비유는 깨진다.",
)

# 예시 clean — 정답 미노출·게임화 메커닉 0. "주사위 게임"·"보드게임"은 수학 *소재*라 무결함
# (게임형 오검출 축을 실제로 시험하는 경계 스트레스 — 잡으면 false alarm).
_CLEAN_EXAMPLE: tuple[str, ...] = (
    "편의점 아르바이트를 하는 지우는 시급과 근무 시간표를 보며 이번 주 급여를 어떻게 "
    "셈할지 고민한다.",
    "주사위 게임을 하던 두 친구가 두 눈의 합이 특정 값이 될 가능성을 두고 내기를 걸었다.",
    "버스 정류장에서 배차 간격을 재던 민서는 규칙을 찾아 다음 버스 시각을 예상해 보기로 했다.",
    "케이크를 여러 조각으로 공평하게 나누려는 생일 파티 장면에서 조각 수를 정하는 문제가 생겼다.",
    "체육대회 계주 순서를 정하며 가능한 배열의 수를 궁금해하는 반 아이들 이야기.",
    "보드게임 카페에서 카드 조합의 수를 세어 보려는 상황.",
)

# grain·축 → violating 은행(+ 예시 grain의 주입 정답). 검출기가 있는 축만 시험지에 올린다
# (의미론 축은 DEFERRED — 은행 없음·미측정 명시).
_VIOLATING_BANK: dict[tuple[str, str], tuple[tuple[str, ...], str | None]] = {
    ("analogy", "MISSING_BREAK_CLAUSE"): (_MISSING_BREAK_VIOLATING, None),
    ("analogy", "OVERIDENTIFICATION"): (_OVERIDENTIFICATION_VIOLATING, None),
    ("analogy", "DEFINITION_USURPATION"): (_DEFINITION_USURPATION_VIOLATING, None),
    ("analogy", "GAMIFIED"): (_GAMIFIED_ANALOGY_VIOLATING, None),
    ("example", "ANSWER_LEAK"): (_ANSWER_LEAK_VIOLATING, _LEAK_ANSWER),
    ("example", "GAMIFIED"): (_GAMIFIED_EXAMPLE_VIOLATING, None),
}

# grain → clean 은행(+ 예시 clean은 정답을 실어 정답 유출 오검출 축을 실제로 시험).
_CLEAN_BANK: dict[str, tuple[tuple[str, ...], str | None]] = {
    "analogy": (_CLEAN_ANALOGY, None),
    "example": (_CLEAN_EXAMPLE, _LEAK_ANSWER),
}


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """시험지 1건 — (grain×축×카테고리×템플릿×변형) 셀. 정답지 = 기대 결함 코드(clean은 None)."""

    grain: str  # "analogy" | "example"
    axis: str  # 결함 축(clean 셀은 "-")
    category: str  # "violating" | "clean"
    text: str
    answer: str | None  # 예시 grain의 주입 정답(비유는 None)
    expected: str | None  # violating→기대 결함 코드, clean→None


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """기계 측정 1건 — 검출 결과와 미검출·오검출 판정."""

    spec: CaseSpec
    detected: tuple[str, ...]
    missed: bool  # violating인데 기대 코드 미검출(false negative)
    false_alarm: bool  # clean인데 무언가 검출(false positive)


def _real_checker(grain: str, text: str, answer: str | None) -> tuple[str, ...]:
    """정상 검출기 — grain별 실제 규칙 검출기로 디스패치(analogy_checker 그대로)."""
    if grain == "analogy":
        return check_analogy_defects(text)
    return check_example_defects(text, answer)


def _null_checker(grain: str, text: str, answer: str | None) -> tuple[str, ...]:
    """대조군 널 검출기 — 무력화(항상 빈 튜플). 보호 계층 OFF의 변별력 실측용."""
    del grain, text, answer  # 항상 무검출 — 시험지의 실제 결함이 그대로 새어 exit 1이 정상.
    return ()


def build_exam(n_per_cell: int) -> list[CaseSpec]:
    """전수 그리드 × 셀당 n 변형 — 결정론(난수 0·순서 고정·무숫자·무신호 접미 변형).

    violating은 (grain, 축)별 은행 전량, clean은 grain별 은행 1회(축 중복 계상 없음 —
    같은 clean 텍스트를 축마다 재계상해 표본을 부풀리지 않는다·정직 회계).
    """
    if n_per_cell < 1:
        raise ValueError("n_per_cell은 1 이상이어야 합니다.")
    if n_per_cell > len(_VARIANT_TOKENS):
        raise ValueError(f"n_per_cell은 최대 {len(_VARIANT_TOKENS)}입니다(무숫자 변형 토큰 한계).")
    cases: list[CaseSpec] = []
    for (grain, axis), (templates, answer) in sorted(_VIOLATING_BANK.items()):
        for template in templates:
            for variant in range(n_per_cell):
                cases.append(
                    CaseSpec(
                        grain=grain,
                        axis=axis,
                        category="violating",
                        text=f"{template} ({_VARIANT_TOKENS[variant]}변형)",
                        answer=answer,
                        expected=axis,
                    )
                )
    for grain, (templates, answer) in sorted(_CLEAN_BANK.items()):
        for template in templates:
            for variant in range(n_per_cell):
                cases.append(
                    CaseSpec(
                        grain=grain,
                        axis="-",
                        category="clean",
                        text=f"{template} ({_VARIANT_TOKENS[variant]}변형)",
                        answer=answer,
                        expected=None,
                    )
                )
    return cases


def _judge(spec: CaseSpec, detected: tuple[str, ...]) -> CaseOutcome:
    """기계 판정(순수) — violating: 기대 코드가 검출 집합에 없으면 miss / clean: 검출=false_alarm.

    violating 판정은 *멤버십*이다 — 한 텍스트가 복수 결함을 겸할 수 있으므로(예: 정의 참칭
    비유가 한계 명시도 없음) 기대 축이 잡히기만 하면 검출 성공이다(부수 검출은 무해).
    """
    if spec.category == "violating":
        missed = spec.expected not in detected
        return CaseOutcome(spec=spec, detected=detected, missed=missed, false_alarm=False)
    return CaseOutcome(spec=spec, detected=detected, missed=False, false_alarm=bool(detected))


def run_machine(cases: list[CaseSpec], checker: CheckerFn) -> list[CaseOutcome]:
    """전 케이스를 검출기에 태워 판정 — 순수·결정론(IO 0·LLM 0). checker 스왑이 대조 지점."""
    return [_judge(spec, checker(spec.grain, spec.text, spec.answer)) for spec in cases]


@dataclass(frozen=True, slots=True)
class FidelityReport:
    """측정 요약 — 미검출·오검출 계수 + 셀별 분해(정직 회계·관측 0 ≠ 확정 0)."""

    violating_total: int
    missed: int
    clean_total: int
    false_alarm: int
    by_cell: dict[str, tuple[int, int]]  # "grain/축/카테고리" → (문제건수, 총건수)

    def miss_upper_bound(self, confidence: float = 0.95) -> float:
        """미검출률 Wilson 단측 상한 — '낮을수록 좋은' 핵심 지표는 상한(보수·과신 금지)."""
        return wilson_upper_bound(self.missed, self.violating_total, confidence)

    def false_alarm_upper_bound(self, confidence: float = 0.95) -> float:
        """오검출률 Wilson 단측 상한 — 과차단(품질 손실) 회계."""
        return wilson_upper_bound(self.false_alarm, self.clean_total, confidence)


def summarize(outcomes: list[CaseOutcome]) -> FidelityReport:
    """순수 집계 — LLM·IO 0 (pedagogy_pack_fidelity_eval.summarize 동형)."""
    violating_total = missed = clean_total = false_alarm = 0
    by_cell: dict[str, tuple[int, int]] = {}
    for outcome in outcomes:
        spec = outcome.spec
        key = f"{spec.grain}/{spec.axis}/{spec.category}"
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
    """사람용 요약 — 텍스트 원문 미출력(카운트·상한·셀 라벨만)."""
    miss_upper = report.miss_upper_bound(confidence)
    alarm_upper = report.false_alarm_upper_bound(confidence)
    banner = "비유·예시 결함주입 강등전 (PED-09 · 04g §6.3)"
    if control:
        banner += " — [대조군: 널 검출기]"
    lines = ["=" * 64, banner + " — Wilson 상한 게이트", "=" * 64]
    lines.append(f"violating 셀: {report.violating_total}건 중 미검출 {report.missed}건")
    lines.append(f"  미검출률 Wilson 상한({confidence:.0%}): {miss_upper:.4f}")
    lines.append(f"clean 셀: {report.clean_total}건 중 오검출 {report.false_alarm}건")
    lines.append(f"  오검출률 Wilson 상한({confidence:.0%}): {alarm_upper:.4f}")
    problem_cells = {k: v for k, v in report.by_cell.items() if v[0] > 0}
    if problem_cells:
        lines.append("[문제 셀 — (문제건수/총건수)]")
        for key in sorted(problem_cells):
            bad, total = problem_cells[key]
            lines.append(f"  {key}: {bad}/{total}")
    else:
        lines.append("[문제 셀 없음 — 전 셀 무결]")
    lines.append("[DEFERRED] SEMANTIC_MISCONCEPTION — 규칙 판정 불가 축·이 시험지 밖(미측정)")
    lines.append("=" * 64)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.analogy_fidelity_eval",
        description=(
            "비유·예시 결함주입 강등전 — 규칙 검출 가능한 결함 축(오개념 유발 프록시·정의 참칭·"
            "정답 유출·게임형)의 미검출을 Wilson 상한으로 게이트한다(hermetic·라이브 LLM 0·"
            "exit 0/1)."
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
