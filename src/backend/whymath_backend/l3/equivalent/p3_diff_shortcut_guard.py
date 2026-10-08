"""P3-03 미분 문항 은행 — '선수 계산 우회로' 판정기(순수 함수·결정론·LLM 0).

독립 감사 3회차(`docs/data/p3_calculus1_diff_audit/round3/defects.json`·κ 0.854)의 결함
대부분은 "미분 없이 선수 계산만으로 풀린다"(bad_tag) 한 부류였다. 생성기가 기계 검증을 위해
정수 중근·깔끔한 인수를 가진 다항식을 고르는데, 바로 그 성질이 인수분해·판별식·대입 우회로를
연다. 1·2회차 교정은 지적된 *발문 서명*을 지우는 방식이라 같은 원인이 새 틀로 재발했다
(74 → 90 → 122).

이 모듈은 서명이 아니라 **수학 재료**를 본다 — 발문에 보이는 다항식·검산 조건(`verify`)·
해설에서 "이 문항이 그 개념의 인지 행동(미분) 없이 풀리는가"를 개념별 규칙으로 판정한다.
생성기 빌드(`p3_diff_skeleton_base.P3DiffSlotGenerator._validate_slot`)가 문항마다 부르고
위반이 하나라도 있으면 빌드를 멈춘다(fail-loud). 은행 전수 0건은 테스트
(`test_p3_diff_shortcut_guard`)가 단언한다.

입력은 생성기의 `DiffItem`이 아니라 **중립 표본**(`ShortcutProbe`)이다 — 같은 판정기를 은행
JSONL 레코드(`probe_from_record`)에도 그대로 적용해 감사 회차의 교정 전 은행에서 재현율을 잴
수 있게 한다.

독립 감사 4회차(`round4/defects.json`·합집합 88·둘 다 27)는 이 판정기를 통과한 은행에서 다시
결함을 찾았다 — ① 학생 대면 텍스트의 코드식 부등호 '<='·'>='와 근호 'sqrt(' ② 극값 위치를 둘
이상 주는 02-08 문항(대입·대소 비교) ③ 복이차 사차식(완전제곱) ④ 포물선 꼭짓점의 수평 접선·직선의
접선(02-05) ⑤ 위치가 일차 이하인 운동의 속도·가속도(02-10) ⑥ x^n의 도함수를 0에서 보는 문항(오답
경로도 전부 0) ⑦ 방정식·부등식 맥락이 없는 02-09 최솟값 ⑧ 발문에 없는 '두 점'·'접점'을 쓰는 해설.
4회차 규칙(아래 [4회차])이 그 부류를 생성 시점에 막는다.

은행 감사 5회차(2026-10-08 · `bank_audit/disposition.json` · 결함 68건 · 원인 14종)는 4회차 규칙을
통과한 은행에서 다시 결함을 찾았다 — ① 이차함수의 평균값 정리·롤·속도 0(c가 늘 구간의 중점·꼭짓점)
② 발문이 답을 알려 줌(근 나열·구간 안 자연수 하나·접점 좌표) ③ 오답 경로가 정답과 일치(함숫값 대입·
일차항 계수 읽기·상수의 미분·차수/임계점 세기) ④ 해설 결함(전제 역전·정의 없는 기호·버린 근 미기술·
v(t) 누락·멈춤의 뜻·y축 x = 0·비문·롤 용어) ⑤ 오개념 귀속(절차 값이 아닌 선지·설명 손상 M0677)
⑥ 발문–검산 불일치(284122b4). 5회차 규칙(아래 [5회차] · `ROUND5_RULE_IDS`)이 그 부류를 막는다.
그중 *매개변수 선택의 우연 일치*(`COINCIDENCE_RULE_IDS`)는 생성기 라운드로빈이 그 파라미터를
건너뛰는 거부 조건으로 쓰고(`parameter_coincidences`), 나머지는 틀 설계 결함이라 빌드를 멈춘다.

규칙(위반 id — 사유는 `ShortcutViolation.reason`)
--------------------------------------------
[공통 · 표기]
  W-notation         학생 대면 문면(발문·선지·해설·정답)에 SymPy 표기('*'·'Derivative(' 등)가
                     있다.
  W-ascii-inequality [4회차] 학생 대면 문면에 코드식 부등호 '<='·'>='가 있다 — 승인 은행 4종은
                     '≤'·'≥'만 쓴다(Flutter 렌더는 '<='를 그대로 두 글자로 낸다).
  W-sqrt-call        [4회차] 학생 대면 문면에 함수 호출꼴 근호 'sqrt('가 있다 — 승인 은행 관례는
                     '8√3'이다(3회차 교정이 고른 '8sqrt(3)'은 감사자 둘이 모두 코드 표기로 봤다).
  W-point-x          '곡선 … 위의 x = 1에서의'처럼 점을 x값으로만 부른다('x좌표가 1인 점').
  W-trivial-ineq     '(-1 < 0 < 2)'처럼 상수만으로 된 자명한 부등식이 괄호로 붙어 있다
                     (템플릿 흔적).
  W-zero-hour        '출발 후 0시간부터'(템플릿 값 0이 그대로 들어간 시각 표현).
  W-extremum-josa    'f(x) …의 극값을 갖는'(주어 조사 오류)·'점이 x = '(점을 x값과 등치).
[공통 · 해설(핵심 중간 단계)]
  E-derivative       발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·
                     v(t) = …)이 없다.
  E-parameter        발문 함수식의 미지 상수(x^n의 n·ax^2의 a)가 해설에 결론('n은 3')으로만
                     나오고 세운 식(nx^(n - 1)·6a + 18 = 0) 안에 한 번도 들지 않는다.
  E-kinematics       발문이 (순간)속도·운동 방향을 다루는데 해설에 v(t) 식이 없거나,
                     가속도를 다루는데 a(t) 식이 없다.
  E-sign             운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다.
  E-symbol-intro     해설이 발문에 없는 기호(f'(c)의 c)를 소개 없이 쓴다.
  E-tautology        'q = 3에서 q = 3이다' 같은 순환 서술.
  E-term             '기울기 0인 일차함수'(상수함수를 일차함수라 부름).
  E-object-intro     [4회차] 해설이 발문에 없는 도형 대상('두 점을 잇는 직선'·'접점'·'접선')을
                     소개 없이 쓴다(발문에 점·곡선·직선·그래프가 하나도 없다).
[개념 · 우회로(bad_tag)]
  T05-quadratic-tangency  (02-05) 접할 조건·곡선 밖의 점에서 그은 접선을 묻는데 곡선이
                          이차 이하라 판별식만으로 풀린다(곡선 차수 ≥ 3이어야 한다).
  T-value-determines      (02-05·02-08) 발문의 함숫값 조건(극값의 값·두 곡선이 만나는 점)
                          만으로 구하는 상수가 정해진다 — 미분계수 조건이 풀이에 쓰이지 않는다.
  T06-given-rate          (02-06) 발문이 평균변화율의 값을 직접 준다(평균값 정리의 행위가
                          빠진다).
  T08-derivative-inequality
                          (02-08) 발문이 f'(x) < 0 같은 도함수 부등식을 직접 준다(증감 판정이
                          빠진다).
  T08-pinned-kind         (02-08) 극값의 위치(x = a)와 종류를 함께 주고 그 값을 묻는다(대입만).
  T09-rational-root       (02-09) 발문에 보이는 방정식·부등식의 다항식이 유리수 근을 갖는다
                          (인수정리).
  T09-biquadratic         (02-09) 발문의 사차식이 어떤 x = h에 대해 대칭이라((x - h)^2 = u)
                          이차방정식으로 환원된다(복이차식 — 근의 공식·판별식).
  T09-repeated-root       (02-09) 등호가 성립하는 점(근)을 묻는데 그 점이 중근이다
                          (완전제곱·인수 우회로).
  T09-low-degree          (02-09) 발문에 보이는 방정식이 이차 이하다(판별식·근의 공식).
  T09-pinned-minimizer    (02-09) 최솟값을 묻는데 발문이 최솟값을 갖는 x를 알려 주거나 그 x가
                          0이다(상수항이 곧 답 — 대입만).
  T10-average-only        (02-10) 평균속도만 묻는다(위치 대입·차분몫 — 미분 불요).
  T-zero-monomial         [4회차] (전 개념) 발문의 함수가 단항식 c·x^n(n ≥ 2)인데 x = 0(원점)에서의
                          미분계수나 방정식 f'(x) = 0의 근을 묻는다 — 정답도, 원함수 대입도,
                          거듭제곱 미분법의 어떤 오답 경로도 0이라 변별이 없다.
  T05-vertex-tangent      [4회차] (02-05) 곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선·기울기 0을
                          묻는다 — 꼭짓점 공식 -b/(2a)·완전제곱으로 풀린다.
  T05-line-tangent        [4회차] (02-05) 직선 위의 점에서의 접선을 묻는다 — 직선의 기울기를 읽기만
                          하면 된다.
  T08-given-critical-points
                          [4회차] (02-08) 발문이 극값을 갖는 x 위치를 둘 이상 준다 — 대입하고 대소를
                          비교하면 극댓값·극솟값이 정해진다(삼차·사차에서 '큰 값이 극댓값'이 늘
                          맞는다). 부호가 바뀌지 않는 임계점이 섞여 *극값인지* 가려야 하는 경우는
                          세지 않는다(극값 위치는 둘 미만이 된다).
  T08-biquadratic         [4회차] (02-08) 발문의 사차식이 x = h에 대해 대칭(복이차)이라
                          (x - h)^2 = u로 두면 완전제곱만으로 극값의 위치·값이 나온다.
  T09-no-application      [4회차] (02-09) 발문에 방정식·부등식·교점·위치 관계 맥락이 없다 — 최댓값·
                          최솟값 기술(02-07/02-08 영역)만으로 풀리는 문항이다.
  T10-linear-position     [4회차] (02-10) 위치가 일차 이하(x = 7·x = 2t + 1)인데 속도·가속도를
                          묻는다 — 정지·등속이라는 상식(일차함수의 기울기)으로 풀린다.
[5회차 · 우회로·우연 일치(*는 매개변수 거부 조건 — `COINCIDENCE_RULE_IDS`)]
  T-quadratic-mean-value  (02-06·02-10) 이차 이하 함수의 평균값 정리·롤·평균속도 = 순간속도 — c가
                          늘 구간의 중점이라 '가운데 값'으로 풀린다.
  T10-quadratic-rest      (02-10) 위치가 이차 이하인데 속도 0 시각을 묻는다(포물선 꼭짓점).
  T-midpoint-answer*      (02-06·02-10) 정답이 구간의 중점(끝점 미지수형이면 2c - 고정 끝점).
  T-integer-pinned-by-interval*
                          자연수 답인데 발문 구간 안의 자연수가 정답 하나뿐.
  T06-roots-given         (02-06) 발문이 f'(x) = (평균변화율)의 근을 모두 적는다.
  T-function-value-path*  미분계수 대신 함숫값(가속도면 위치·속도)을 넣어도 같은 답.
  T-coefficient-reading*  발문 다항식의 x = 0 미분계수 — 일차항 계수를 읽으면 끝난다('상수항' 과제
                          제외).
  T-constant-derivative*  발문의 두 함수 차가 상수라 미분하는 식이 상수(답·오답 전부 0).
  T09-degree-count*       (02-09) 실근 개수 = 방정식의 차수.
  T09-critical-count*     (02-09) 실근 개수 = f'(x) = 0의 서로 다른 실근 개수.
  T09-given-extremum-values
                          (02-09) 개수 문항의 방정식이 발문에 없고 극값을 발문이 준다.
  T05-quadratic-tangent-constant
                          (02-05) 곡선이 이차 이하인데 접선의 y절편·곡선의 상수·원점에서 그은 접선을
                          판별식형으로 검산한다(중근만으로 풀린다).
  T05-given-coordinate*   (02-05) 정답이 발문에 적힌 점의 y좌표.
  M-link-procedure        오개념 귀속 선지가 그 오개념 절차(M0615 차수 · 임계점=극값 · M0674 f'(c) =
                          0)의 값이 아니거나, 묻는 대상(극대·극소)이 그 절차의 산출과 다르다.
  M-link-undescribed      설명에 절차가 적히지 않은 오개념(M0677 — 원문 손상·QUAL-14 소관)에 귀속.
  V05-touch-verify-mismatch
                          (02-05) 접점이 발문에서 고정된 문항(두 곡선이 x = a에서 접함 · 위의 점/
                          x좌표가 a인 점에서의 접선의 y절편)의 검산 조건 해집합이 발문 문제의
                          해집합과 다르다(보호 조건은 읽지 않는다 — 발문에 없는 보호로 해를 고르는
                          것이 결함).
[5회차 · 해설]
  E-premise-reversal      발문은 'f'(x) = 0의 한 근이 x = p'인데 해설이 'x = p에서 극값을 가지므로'.
  E-undefined-letter      발문에 없는 기호(k·v 등)를 소개 없이 식에 쓴다(운동 문항의 v·a는 '속도'·
                          '가속도'를 말하면 관례 기호).
  E-excluded-root         보호 조건이 버리는 근을 해설이 보이지 않는다(a = 0 배제·± 단계 누락).
  E-velocity-before-acceleration
                          가속도를 묻는데 해설에 v(t) 식이 없다.
  E-rest-meaning          멈추는 시각을 묻는데 해설이 'v(t)는 위치의 도함수'·'멈춤 ⇔ v(t) = 0'을
                          말하지 않는다.
  E-y-axis-zero           y축과 만나는 점을 다루는데 해설에 'x좌표는 0' 단계가 없다.
  E-run-on                한 문장에 '~인데, ~인데,'가 겹친다(비문).
  E-term-rolle            수 하나를 '롤의 정리의 결론'이라 부른다.

정직 범위(이 판정기가 보증하지 **않는** 것)
-------------------------------------------
· 발문 문자열의 *템플릿 표현*을 정규식으로 읽는 휴리스틱이 섞여 있다. 같은 수학을 다른 어휘로
  쓴 문항(예: '접할 때' 대신 '한 점에서만 만날 때')은 T05 규칙이 읽지 못할 수 있다.
· '미분 없이 풀린다'의 판정은 이 규칙들이 아는 우회로(인수정리·판별식·대입·이차부등식·
  평균속도 차분몫)에 한정된다. 학생이 쓸 수 있는 모든 우회로(산술·기하 평균 등)를 열거하지
  않는다.
· 해설 규칙은 *형식*(도함수 식·세운 식의 존재)을 본다 — 그 식이 옳은지는 Tier1·
  corpus_reverify의 몫이다.

7계층: L3 지역. SymPy 문자열 파싱은 `l3.safe_parse`(CONST-09 단일 진입점)로만 한다 — 입력은
저작 코퍼스·생성기 산출이지만 진입점을 우회하지 않는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import sympy

from whymath_backend.l3.safe_parse import safe_sympify

__all__ = [
    "COINCIDENCE_RULE_IDS",
    "ROUND4_RULE_IDS",
    "ROUND5_RULE_IDS",
    "RULE_IDS",
    "ShortcutProbe",
    "ShortcutViolation",
    "has_rational_root",
    "is_shifted_biquadratic",
    "parameter_coincidences",
    "probe_from_record",
    "shortcut_violations",
    "violations_by_rule",
    "visible_polynomials",
]

#: 판정기가 낼 수 있는 규칙 id 전부(테스트·보고가 참조하는 단일 원천).
RULE_IDS: Final[tuple[str, ...]] = (
    "W-notation",
    "W-point-x",
    "W-trivial-ineq",
    "W-zero-hour",
    "W-extremum-josa",
    "E-derivative",
    "E-parameter",
    "E-kinematics",
    "E-sign",
    "E-symbol-intro",
    "E-tautology",
    "E-term",
    "T05-quadratic-tangency",
    "T-value-determines",
    "T06-given-rate",
    "T08-derivative-inequality",
    "T08-pinned-kind",
    "T09-rational-root",
    "T09-biquadratic",
    "T09-repeated-root",
    "T09-low-degree",
    "T09-pinned-minimizer",
    "T10-average-only",
    # ── 4회차(2026-10-07) 결함 부류 — `ROUND4_RULE_IDS` ──
    "W-ascii-inequality",
    "W-sqrt-call",
    "E-object-intro",
    "T-zero-monomial",
    "T05-vertex-tangent",
    "T05-line-tangent",
    "T08-given-critical-points",
    "T08-biquadratic",
    "T09-no-application",
    "T10-linear-position",
    # ── 5회차(2026-10-08 · 은행 감사 S5 불합격 k = 68) 결함 부류 — `ROUND5_RULE_IDS` ──
    "T-quadratic-mean-value",
    "T10-quadratic-rest",
    "T-midpoint-answer",
    "T-integer-pinned-by-interval",
    "T06-roots-given",
    "T-function-value-path",
    "T-coefficient-reading",
    "T-constant-derivative",
    "T09-degree-count",
    "T09-critical-count",
    "T09-given-extremum-values",
    "T05-quadratic-tangent-constant",
    "T05-given-coordinate",
    "M-link-procedure",
    "M-link-undescribed",
    "E-premise-reversal",
    "E-undefined-letter",
    "E-excluded-root",
    "E-velocity-before-acceleration",
    "E-rest-meaning",
    "E-y-axis-zero",
    "E-run-on",
    "E-term-rolle",
    "V05-touch-verify-mismatch",
)

#: 4회차 감사(합집합 88·둘 다 27)를 계기로 더한 규칙 — 3회차 재현율·과잉 거부 동결 테스트는 이
#: 규칙들을 빼고 본다(3회차 판정자는 '<=' 등을 결함으로 보지 않았다 — 같은 원문에 대한 기준이
#: 회차마다 다르므로, 회차별 측정은 그 회차의 규칙 집합으로 한다).
ROUND4_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("W-ascii-inequality") : RULE_IDS.index("T-quadratic-mean-value")]
)

#: 5회차 은행 감사(2026-10-08 · `docs/data/p3_calculus1_diff_audit/bank_audit/` · as-found k = 68)를
# 계기로 더한 규칙. 4회차 이전 회차의 재현율·과잉 거부 동결은 이 규칙들을 빼고 본다(회차별 측정은 그
#: 회차의 규칙 집합으로 한다 — `ROUND4_RULE_IDS`와 같은 원칙).
ROUND5_RULE_IDS: Final[frozenset[str]] = frozenset(
    RULE_IDS[RULE_IDS.index("T-quadratic-mean-value") :]
)

#: 5회차 규칙 중 *매개변수 선택*의 우연 일치를 보는 규칙 — 틀(frame)의 설계가 아니라 고른 수치가
#: 오답 경로와 정답을 겹치게 만든 경우다(f'(1) 대신 f(1)로 풀어도 같은 a · 구간 안 자연수가 하나뿐 ·
#: 차수로 센 개수가 정답 등). 생성기는 이 규칙에 걸리는 매개변수를 *건너뛴다*
#: (`p3_diff_skeleton_base.round_robin_items`의 `standard_code` 인자 — 매개변수 거부 조건의 단일
#: 원천). 나머지 규칙은 틀 설계 결함이라 빌드가 멈춘다(fail-loud).
COINCIDENCE_RULE_IDS: Final[frozenset[str]] = frozenset(
    {
        "T-midpoint-answer",
        "T-integer-pinned-by-interval",
        "T-function-value-path",
        "T-coefficient-reading",
        "T-constant-derivative",
        "T09-degree-count",
        "T09-critical-count",
        "T05-given-coordinate",
    }
)

_C05: Final = "[12미적Ⅰ-02-05]"
_C06: Final = "[12미적Ⅰ-02-06]"
_C08: Final = "[12미적Ⅰ-02-08]"
_C09: Final = "[12미적Ⅰ-02-09]"
_C10: Final = "[12미적Ⅰ-02-10]"
_REAL_ROOT_COUNT: Final = "real_root_count"


@dataclass(frozen=True, slots=True)
class ShortcutProbe:
    """판정 대상 문항 1건의 중립 표본 — 생성기 문항과 은행 레코드가 같은 모양으로 들어온다."""

    standard_code: str
    question_text: str
    answer: str
    explanation: str
    choices: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None
    #: [5회차] 답 형식('자연수'·'분수'·'실수') — 자연수 답과 구간 단서가 답을 하나로 좁히는지 본다.
    answer_format: str | None = None
    # [5회차] 오답 선지–오개념 연결 (선지 인덱스, 오개념 id) — 연결 선지가 그 오개념 절차의 값인지
    # 본다.
    distractors: tuple[tuple[int, str], ...] = ()
    #: [5회차] 슬롯 id(`p3-slot:` 태그 값) — 보고용(규칙 판정에는 쓰지 않는다).
    slot: str | None = None

    @property
    def answer_dict(self) -> dict[str, str]:
        return dict(self.answer_map)


@dataclass(frozen=True, slots=True)
class ShortcutViolation:
    """위반 1건 — 어느 규칙을 왜 어겼는지(사람이 틀을 고칠 수 있게)."""

    rule: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.reason}"


def probe_from_record(record: Mapping[str, object]) -> ShortcutProbe:
    """은행 JSONL 레코드 → 표본(`verify` 재료·선지·해설을 그대로 옮긴다)."""
    codes = record.get("achievement_standard_codes")
    code = str(codes[0]) if isinstance(codes, list) and codes else ""
    verify = record.get("verify")
    conditions: tuple[str, ...] = ()
    answer_map: tuple[tuple[str, str], ...] = ()
    answer_kind: str | None = None
    if isinstance(verify, Mapping):
        raw = verify.get("conditions")
        if isinstance(raw, str):
            conditions = (raw,)
        elif isinstance(raw, list):
            conditions = tuple(str(c) for c in raw)
        amap = verify.get("answer_map")
        if isinstance(amap, Mapping):
            answer_map = tuple((str(k), str(v)) for k, v in amap.items())
        kind = verify.get("answer_kind")
        answer_kind = str(kind) if isinstance(kind, str) else None
    choices = record.get("choices")
    raw_format = record.get("answer_format")
    distractors: list[tuple[int, str]] = []
    raw_map = record.get("distractor_map")
    if isinstance(raw_map, list):
        for entry in raw_map:
            if isinstance(entry, Mapping):
                index, mid = entry.get("choice_index"), entry.get("misconception_id")
                if isinstance(index, int) and isinstance(mid, str):
                    distractors.append((index, mid))
    tags = record.get("tags")
    slot = next(
        (
            str(t)[len("p3-slot:") :]
            for t in (tags if isinstance(tags, list) else [])
            if str(t).startswith("p3-slot:")
        ),
        None,
    )
    return ShortcutProbe(
        standard_code=code,
        question_text=str(record.get("question_text") or ""),
        answer=str(record.get("answer") or ""),
        explanation=str(record.get("answer_explanation") or ""),
        choices=tuple(str(c) for c in choices) if isinstance(choices, list) else (),
        conditions=conditions,
        answer_map=answer_map,
        answer_kind=answer_kind,
        answer_format=str(raw_format) if isinstance(raw_format, str) else None,
        distractors=tuple(distractors),
        slot=slot,
    )


# ──────────────────────────────────────────────────────────────────────────
# 학생 표기 다항식 읽기 — '2x^3 - 3x + 1'·'x^3 + ax^2 - 9x + 4'·'x^n'
# ──────────────────────────────────────────────────────────────────────────
# 항: (정수 계수)(문자^지수)… 또는 정수. 지수는 숫자 또는 문자 하나(x^n).
_TERM = r"(?:\d+)?(?:[a-z](?:\^(?:\d+|[a-z]))?)+|\d+"
#: 발문의 다항식 덩어리 — 함수 기호의 인자 'f(x)'의 x나 프라임 'f'(x)'의 일부는 잡지 않는다.
_POLY_RE = re.compile(
    rf"(?<![A-Za-z0-9'^(/])-?(?:{_TERM})(?:\s[-+]\s(?:{_TERM}))*(?![A-Za-z0-9^'(/])"
)


def _student_to_sympy_text(text: str) -> str:
    """학생 표기 → SymPy 표기('2ax^2' → '2*a*x**2'). 곱을 명시하고 캐럿을 거듭제곱으로 바꾼다."""
    out = re.sub(r"(\d)([a-z])", r"\1*\2", text)
    while True:
        nxt = re.sub(r"([a-z])([a-z])", r"\1*\2", out)
        if nxt == out:
            break
        out = nxt
    out = re.sub(r"([a-z0-9])\^", r"\1**", out)
    return out


def _parse_student(text: str) -> sympy.Expr | None:
    try:
        value = safe_sympify(_student_to_sympy_text(text.strip()))
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    return value if isinstance(value, sympy.Expr) else None


def visible_polynomials(question_text: str) -> list[sympy.Expr]:
    """발문에 학생이 *보는* 다항식 덩어리(문자를 하나 이상 포함한 것)를 SymPy 식으로 모은다."""
    out: list[sympy.Expr] = []
    for match in _POLY_RE.finditer(question_text):
        chunk = match.group(0)
        if not re.search(r"[a-z]", chunk):
            continue
        expr = _parse_student(chunk)
        if expr is not None and expr.free_symbols:
            out.append(sympy.expand(expr))
    return out


# ──────────────────────────────────────────────────────────────────────────
# 검산 조건 읽기
# ──────────────────────────────────────────────────────────────────────────
_REL_RE = re.compile(r"\s(<=|>=|!=|=|<|>)\s")


@dataclass(frozen=True, slots=True)
class _Relation:
    lhs: sympy.Expr
    op: str
    rhs: sympy.Expr

    @property
    def difference(self) -> sympy.Expr:
        return sympy.expand(self.lhs - self.rhs)


def _parse_relation(condition: str) -> _Relation | None:
    """'lhs op rhs'(공백으로 감싼 관계 연산자 하나) → 관계. 미분 조건은 읽지 않는다(None)."""
    if "Derivative" in condition:
        return None
    match = _REL_RE.search(condition)
    if match is None:
        return None
    try:
        lhs = safe_sympify(condition[: match.start()])
        rhs = safe_sympify(condition[match.end() :])
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    if not isinstance(lhs, sympy.Expr) or not isinstance(rhs, sympy.Expr):
        return None
    return _Relation(lhs, match.group(1), rhs)


def _variable_of(probe: ShortcutProbe) -> sympy.Symbol:
    """문항의 독립변수 — 검산 조건에 t가 있으면 t(운동), 아니면 x."""
    joined = " ".join(probe.conditions)
    return (
        sympy.Symbol("t") if re.search(r"(?<![A-Za-z])t(?![A-Za-z])", joined) else sympy.Symbol("x")
    )


def has_rational_root(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """유리수 근이 있는가(일차 인수) — 생성기가 같은 술어로 미리 거른다(판정 정의의 단일 원천)."""
    _, factors = sympy.factor_list(expr, var)
    return any(sympy.degree(f, var) == 1 for f, _ in factors)


def is_shifted_biquadratic(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """사차식이 어떤 x = h에 대해 대칭인가 — P(x + h)가 짝수 차 항만 가지면 이차식으로 환원된다."""
    poly = sympy.Poly(expr, var)
    if poly.degree() != 4:
        return False
    coeffs = poly.all_coeffs()
    h = sympy.Rational(-coeffs[1], 4 * coeffs[0])
    shifted = sympy.Poly(sympy.expand(expr.subs(var, var + h)), var)
    return all(c == 0 for (e,), c in shifted.terms() if e % 2 == 1)


def _has_repeated_factor(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    _, factors = sympy.factor_list(expr, var)
    return any(mult >= 2 and sympy.degree(f, var) >= 1 for f, mult in factors)


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 표기]
# ──────────────────────────────────────────────────────────────────────────
#: 학생 문면에 새어 나온 SymPy 함수명(근호 'sqrt('는 4회차 규칙 W-sqrt-call이 따로 본다).
_SYMPY_FUNCTION = re.compile(r"\b(?:Derivative|Abs|Rational|Integer|Symbol|Poly|Eq)\(")
#: [4회차] 코드식 부등호 — 학생 표기는 '≤'·'≥'(승인 은행 관례). '=>'·'=<'는 쓰지 않으므로
#: 보지 않는다.
_W_ASCII_INEQ = re.compile(r"<=|>=")
#: [4회차] 함수 호출꼴 근호 — 학생 표기는 '√3'·'8√3'.
_W_SQRT_CALL = re.compile(r"sqrt\(")
_W_POINT_X = re.compile(r"위의 [xt] = -?\d+(?:/\d+)?에서")
_NUM = r"-?\d+(?:/\d+)?"
#: 부등호는 코드식('<=')과 학생 표기('≤') 둘 다 읽는다 — 표기를 바꿔도 자명 부등식 검출이 꺼지지
#: 않게(4회차 표기 교정이 이 규칙을 무력화하지 않게) 한다.
_LE = r"(?:<=?|≤)"
_W_TRIVIAL_INEQ = re.compile(rf"\(\s*{_NUM}\s*{_LE}\s*{_NUM}\s*{_LE}\s*{_NUM}\s*\)")
_W_ZERO_HOUR = re.compile(r"(?<!\d)0\s*시간\s*(?:부터|후|동안)|후\s+0\s*시간")
_W_EXTREMUM_JOSA = re.compile(r"의 극(?:값|댓값|솟값)을 갖는|점이 [xt] = ")


def _notation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    fields = [("발문", probe.question_text), ("해설", probe.explanation)]
    fields += [(f"선지 {i + 1}", c) for i, c in enumerate(probe.choices)]
    fields += [("정답", probe.answer)]
    for name, text in fields:
        if "*" in text or _SYMPY_FUNCTION.search(text):
            out.append(
                ShortcutViolation(
                    "W-notation",
                    f"{name} {text!r}에 SymPy 표기('*'·'Derivative(' 등)가 학생에게 노출된다 — "
                    "곱은 이어 쓴다('3x^2'·'8√3').",
                )
            )
        if _W_ASCII_INEQ.search(text):
            out.append(
                ShortcutViolation(
                    "W-ascii-inequality",
                    f"{name} {text!r}에 코드식 부등호('<='·'>=')가 있다 — 학생 표기 "
                    "'≤'·'≥'로 쓴다.",
                )
            )
        if _W_SQRT_CALL.search(text):
            out.append(
                ShortcutViolation(
                    "W-sqrt-call",
                    f"{name} {text!r}에 함수 호출꼴 근호 'sqrt('가 있다 — 학생 표기 '√'로 쓴다"
                    "('8sqrt(3)' → '8√3').",
                )
            )
    q = probe.question_text
    if _W_POINT_X.search(q):
        out.append(
            ShortcutViolation(
                "W-point-x", "'위의 x = a에서의'는 점을 x값으로만 부른다 — 'x좌표가 a인 점'."
            )
        )
    if _W_TRIVIAL_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "W-trivial-ineq",
                "상수만으로 된 자명한 부등식 괄호(예 '(-1 < 0 < 2)')는 템플릿 흔적이다.",
            )
        )
    if _W_ZERO_HOUR.search(q):
        out.append(
            ShortcutViolation("W-zero-hour", "'출발 후 0시간'은 템플릿 값 0이 그대로 든 표현이다.")
        )
    if _W_EXTREMUM_JOSA.search(q):
        out.append(
            ShortcutViolation(
                "W-extremum-josa",
                "'f(x)…의 극값을 갖는'(주어 조사)·'점이 x = '(점과 x값 등치)는 잘못된 표현이다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [공통 · 해설]
# ──────────────────────────────────────────────────────────────────────────
#: 도함수 식의 머리 — 'f'(x) = …'·"f'(x)는 3x^2"·"y' = …"·'v(t) = …'·'a(t) = …'·'dy/dx = …'·
#: "f'(a)는 9a^8"(문자에서의 미분계수를 문자식으로)·'도함수는 6x^2 - 2'·'도함수 -3x^2 + 4x'.
#: 우변(그룹 rhs)이 독립변수(또는 괄호 안 문자)를 품어야 *식*이다 — 'f'(x) = 0의 근'은 식이 아니다.
_DERIV_FORMULA = re.compile(
    r"(?<![A-Za-z])(?:(?P<fn>[a-z]'{1,2})\((?P<arg>[a-z])\)|y'|v\(t\)|a\(t\)|dy/dx)"
    r"\s*(?:=|는|은)\s*(?P<rhs>[^가-힣]+)"
    r"|도함수(?:는|가|인|)\s+(?P<rhs2>\(?-?[\dxt(][^가-힣]*)"
)
_VELOCITY_FORMULA = re.compile(r"(?<![A-Za-z])(?:v\(t\)|[a-z]'\(t\))\s*=\s*\S")
_ACCEL_FORMULA = re.compile(r"(?<![A-Za-z])(?:a\(t\)|v'\(t\)|[a-z]''\(t\))\s*=\s*\S")
#: 함수 정의 — 'f(x) = …'·'y = …'·'x = …'(운동의 위치)·'x(t) = …'·'s(t) = …'.
_DEFINITION = re.compile(
    r"(?<![A-Za-z'])(?P<name>[a-z])(?:\((?P<arg>[xt])\))?\s*=\s*(?P<rhs>[^가-힣,=]+)"
)
_FUNCTION_NAMES: Final = frozenset("fghy")


def _clean_rhs(raw: str, var: str) -> str:
    """정의 우변에서 다항식 부분만 남긴다.

    닫히지 않은 괄호 꼬리('(n')·변수 없는 괄호 꼬리('(km)')를 뗀다.
    """
    rhs = raw.strip()
    rhs = re.sub(r"\s*\([^)]*$", "", rhs)
    tail = re.search(r"\s+\(([^()]*)\)\s*$", rhs)
    if tail and var not in tail.group(1):
        rhs = rhs[: tail.start()]
    return rhs.strip()


def _definitions(text: str, var: str) -> list[tuple[str, str]]:
    """발문의 다항함수 정의 (이름, 우변) — 'x = a'(점 지정)·'h(x) = 4f(x) - 2g(x)'(추상 함수 결합)는
    다항함수 정의가 아니다."""
    out: list[tuple[str, str]] = []
    for m in _DEFINITION.finditer(text):
        name, rhs = m.group("name"), _clean_rhs(m.group("rhs"), var)
        if m.group("arg") is None and name == var:
            continue
        if m.group("arg") is None and name not in ("y", "x"):
            continue
        if re.search(r"[a-z]\(", rhs):
            continue
        if not re.search(rf"(?<![A-Za-z]){var}|\d*{var}", rhs):
            continue
        out.append((name, rhs))
    return out


def _max_degree(definitions: Iterable[tuple[str, str]], var: str) -> int:
    """정의된 다항함수의 최고 차수(파싱 불가는 2로 본다 — 상수 도함수 예외를 열지 않는다)."""
    symbol = sympy.Symbol(var)
    best = 0
    for _, rhs in definitions:
        expr = _parse_student(rhs)
        if expr is None or symbol not in expr.free_symbols:
            best = max(best, 2 if expr is None else 0)
            continue
        try:
            best = max(best, int(sympy.degree(sympy.expand(expr), symbol)))
        except sympy.PolynomialError:
            best = max(best, 2)
    return best


def _has_derivative_formula(explanation: str, var: str, max_degree: int) -> bool:
    """해설에 도함수 *식*이 있는가 — 우변이 독립변수(또는 미분계수의 문자 인자)를 품거나, 함수가
    일차 이하라 도함수가 상수일 때(우변 상수 허용)."""
    for m in _DERIV_FORMULA.finditer(explanation):
        rhs = m.group("rhs") if m.group("rhs") is not None else (m.group("rhs2") or "")
        letters = {var}
        if m.group("arg"):
            letters.add(m.group("arg"))
        if any(re.search(rf"\d*{letter}(?![A-Za-z(])", rhs) for letter in letters):
            return True
        # 미분 차수 — 프라임 개수(f''는 2)·a(t)는 2계·그 밖(y'·v(t)·dy/dx·'도함수')은 1계.
        head = m.group(0)
        order = len(m.group("fn")) - 1 if m.group("fn") else (2 if head.startswith("a(") else 1)
        if max_degree <= order and re.search(r"-?\d", rhs):
            return True  # 차수 이하로 미분한 도함수는 상수다(우변 상수 허용)
    return False


def _parameters(definitions: Iterable[tuple[str, str]], var: str) -> set[str]:
    """함수 정의 우변의 미지 상수 — 독립변수·함수 기호(뒤에 '('가 오는 문자)를 뺀 문자."""
    params: set[str] = set()
    for _, rhs in definitions:
        for m in re.finditer(r"[a-z]", rhs):
            letter = m.group(0)
            after = rhs[m.end() : m.end() + 1]
            if letter == var or after == "(" or letter in _FUNCTION_NAMES:
                continue
            params.add(letter)
    return params


def _algebraic_use(text: str, letter: str) -> bool:
    """해설에서 `letter`가 결론('a = 3'·'n은 3')이 아니라 *세운 식* 안에 한 번이라도 드는가."""
    for m in re.finditer(letter, text):
        i, j = m.start(), m.end()
        prev = text[i - 1] if i > 0 else ""
        nxt = text[j] if j < len(text) else ""
        if prev and (prev.isascii() and (prev.isalnum() or prev in ")^")):
            return True
        if nxt and (nxt.isascii() and (nxt.isalnum() or nxt in "^(")):
            return True
        before = text[:i].rstrip()
        after = text[j:].lstrip()
        if before and before[-1] in "+-*/^(":
            return True
        if after and after[0] in "+-*/^)":
            return True
    return False


_INTRO = (
    r"{L}\s*(?:이라|라)\s*(?:하|두|놓)|{L}로\s*(?:두|놓)|[을를]\s+{L}(?![A-Za-z])"
    r"|[xt]\s*=\s*{L}(?![A-Za-z])|인\s+{L}(?:가|이|는|를|의)"
)
_TAUTOLOGY = re.compile(
    r"(?<![A-Za-z0-9])([a-z])\s*=\s*(-?\d+(?:/\d+)?)에서\s*\1\s*=\s*\2(?![\d/])"
)
_TERM_LINEAR = re.compile(r"기울기(?:가)?\s*((?:-?\d+)(?:\s*,\s*-?\d+)*)\s*인\s*일차함수")
#: [4회차] 해설이 꺼내는 도형 대상 — 발문(`_Q_OBJECT`)에 그 대상을 소개하는 말이 하나도 없으면 결함.
_E_OBJECT = re.compile(r"두 점을 잇는|접점|접선")
_Q_OBJECT = re.compile(r"점|접|곡선|직선|그래프")


def _explanation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    out: list[ShortcutViolation] = []
    q, e = probe.question_text, probe.explanation
    var = str(_variable_of(probe))
    defs = _definitions(q, var)
    if defs and not _has_derivative_formula(e, var, _max_degree(defs, var)):
        out.append(
            ShortcutViolation(
                "E-derivative",
                "발문이 다항함수를 주는데 해설에 도함수 식(f'(x) = …·도함수는 …·v(t) = …)이 없다 — "
                "결론만 적은 해설이다.",
            )
        )
    for letter in sorted(_parameters(defs, var)):
        if not _algebraic_use(e, letter):
            out.append(
                ShortcutViolation(
                    "E-parameter",
                    f"발문 함수식의 미지 상수 {letter}가 해설에 세운 식(예 {letter}를 포함한 "
                    "방정식) "
                    "없이 결론으로만 나온다.",
                )
            )
    instant_q = re.sub(r"평균\s*속도", "", q).replace("가속도", "")
    if re.search(r"속도|속력|멈추|정지|운동 방향|방향을 바|방향이 바뀌", instant_q):
        if not _VELOCITY_FORMULA.search(e):
            out.append(
                ShortcutViolation("E-kinematics", "속도를 다루는 문항인데 해설에 v(t) 식이 없다.")
            )
    if "가속도" in q and not _ACCEL_FORMULA.search(e):
        out.append(
            ShortcutViolation("E-kinematics", "가속도를 묻는 문항인데 해설에 a(t) 식이 없다.")
        )
    if re.search(r"방향을 바|방향이 바뀌", q) and "부호" not in e:
        out.append(
            ShortcutViolation(
                "E-sign",
                "운동 방향 전환을 묻는데 해설에 속도의 부호 판정이 없다(v = 0이 곧 방향 전환은 "
                "아니다).",
            )
        )
    q_letters = set(re.findall(r"(?<![A-Za-z])[a-z](?![A-Za-z])", q))
    for m in re.finditer(r"(?<![A-Za-z])[a-z]'{1,2}\(([a-z])\)", e):
        letter = m.group(1)
        if letter in ("x", "t") or letter in q_letters:
            continue
        if not re.search(_INTRO.format(L=letter), e):
            out.append(
                ShortcutViolation(
                    "E-symbol-intro",
                    f"해설이 발문에 없는 기호 {letter}를 소개 없이 쓴다('구하는 x좌표를 {letter}라 "
                    "하자').",
                )
            )
            break
    if _TAUTOLOGY.search(e):
        out.append(ShortcutViolation("E-tautology", "'q = 3에서 q = 3이다' 같은 순환 서술이 있다."))
    for m in _TERM_LINEAR.finditer(e):
        slopes = [s.strip() for s in m.group(1).split(",")]
        if "0" in slopes:
            out.append(
                ShortcutViolation("E-term", "기울기가 0인 함수는 상수함수이지 일차함수가 아니다.")
            )
    named = _E_OBJECT.search(e)
    if named is not None and not _Q_OBJECT.search(q):
        out.append(
            ShortcutViolation(
                "E-object-intro",
                f"해설이 발문에 없는 대상 '{named.group(0)}'을(를) 소개 없이 쓴다 — 발문에 점·곡선·"
                "직선·그래프가 없으면 '구간에서의 평균변화율'·'f'(c)'처럼 발문의 말로 쓴다.",
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# [개념 · 우회로]
# ──────────────────────────────────────────────────────────────────────────
_TANGENCY = re.compile(r"접할 때|접하도록|접한다|접하는 (?:점|직선)|그은 (?:두 )?접선")
_CURVE = re.compile(r"곡선 y = ")


def _curve_degrees(q: str) -> list[int]:
    degrees: list[int] = []
    for m in _CURVE.finditer(q):
        chunk = _POLY_RE.match(q, m.end())
        if chunk is None:
            continue
        expr = _parse_student(chunk.group(0))
        if expr is None:
            continue
        x = sympy.Symbol("x")
        if x in expr.free_symbols:
            degrees.append(int(sympy.degree(expr, x)))
    return degrees


#: [4회차] 수평 접선을 묻는 표현 — 포물선이면 꼭짓점 공식으로 바로 풀린다.
_HORIZONTAL = re.compile(r"꼭짓점|x축에 평행|수평|기울기가 0(?:일|인)")
#: [4회차] 직선 위의 점에서의 접선 — '직선 y = 2x - 5 위의 점 (2, -1)에서의 접선'.
_LINE_POINT = re.compile(r"직선 y = [^가-힣]+ 위의")


def _tangent_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    degrees = _curve_degrees(q)
    if _TANGENCY.search(q) and degrees and max(degrees) <= 2:
        out.append(
            ShortcutViolation(
                "T05-quadratic-tangency",
                "접할 조건을 묻는데 곡선이 이차 이하라 연립 이차방정식의 판별식만으로 풀린다 — "
                "곡선 차수가 3 이상이거나 접점의 미분계수가 풀이에 필수여야 한다.",
            )
        )
    if degrees and max(degrees) <= 2 and _HORIZONTAL.search(q):
        out.append(
            ShortcutViolation(
                "T05-vertex-tangent",
                "곡선이 이차 이하인데 꼭짓점·x축에 평행한 접선(기울기 0)을 묻는다 — 포물선의 수평 "
                "접선은 꼭짓점에만 생기므로 -b/(2a)·완전제곱으로 미분 없이 풀린다.",
            )
        )
    if "접선" in q and _LINE_POINT.search(q):
        out.append(
            ShortcutViolation(
                "T05-line-tangent",
                "직선 위의 점에서의 접선을 묻는다 — 직선의 접선은 그 직선 자신이라 기울기를 읽기만 "
                "하면 되고, 미분계수 개념이 없는 학생도 맞힌다.",
            )
        )
    return out


#: [4회차] x = 0에서의 값을 묻는 표현 — 대입('10을 대입'은 아니다)·미분계수 f'(0)·원점·
#: 'x좌표가 0인'.
#: 'x = 0'은 x 위치 고정 읽기(`_PIN_X` — 분수까지 수 하나를 통째로 읽는다)를 그대로 쓴다.
_ZERO_PHRASE = re.compile(r"(?<!\d)0을 대입|[a-z]'\(0\)|원점|x좌표가 0인")
#: [4회차] 방정식 f'(x) = 0의 근을 묻는 표현.
_DERIV_ROOT = re.compile(r"[a-z]'\(x\) = 0의 (?:실근|근|해)")


def _is_power_monomial(expr: sympy.Expr, var: sympy.Symbol) -> bool:
    """x에 대해 항이 하나뿐이고 차수가 2 이상인가(c·x^n).

    계수 c는 문자여도 된다 — kx^2도 x = 0에서의 미분계수가 0이다.
    """
    try:
        poly = sympy.Poly(expr, var)
    except sympy.PolynomialError:
        return False
    return len(poly.terms()) == 1 and poly.degree() >= 2


def _zero_monomial_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """단항식 c·x^n의 x = 0(또는 f'(x) = 0의 근) — 정답·원함수 대입·오답 경로가 모두 0이다."""
    q = probe.question_text
    x = sympy.Symbol("x")
    if not any(_is_power_monomial(p, x) for p in visible_polynomials(q)):
        return []
    pinned = {sympy.Rational(v) for v in _PIN_X.findall(q)}  # `_PIN_X`는 02-08 절에 정의(같은 경계)
    at_zero = _ZERO_PHRASE.search(q) is not None or 0 in pinned
    if at_zero or _DERIV_ROOT.search(q):
        return [
            ShortcutViolation(
                "T-zero-monomial",
                "단항식 c·x^n(n ≥ 2)의 x = 0에서의 미분계수(또는 f'(x) = 0의 근)를 묻는다 — "
                "정답이 0이고 원함수에 대입해도, 지수를 안 줄이거나 계수를 빠뜨려도 0이라 거듭제곱 "
                "미분법을 변별하지 못한다.",
            )
        ]
    return []


_EXTREMUM_VALUE = re.compile(r"(?<![A-Za-z])[xt] = (-?\d+)에서 극(?:댓|솟)?값 (-?\d+)")
_TOUCH_AT = re.compile(r"(?:(?<![A-Za-z])x = |x좌표가 )(-?\d+)인 점에서 (?:서로 )?접")
_ASKED_CONSTANT = re.compile(r"상수 ([a-z])의 값")


def _asked_parameter(probe: ShortcutProbe) -> str | None:
    amap = probe.answer_dict
    for key, value in amap.items():
        if key not in ("x", "y", "t", "s") and value.strip() == probe.answer.strip():
            return key
    m = _ASKED_CONSTANT.search(probe.question_text)
    return m.group(1) if m else None


def _value_equations(probe: ShortcutProbe, var: sympy.Symbol) -> list[sympy.Expr]:
    """발문이 주는 *미분 없는* 조건 — 극값의 값(f(a) = V)·두 곡선이 a에서 만남(C1(a) = C2(a))."""
    q = probe.question_text
    defs = _definitions(q, str(var))
    funcs = [e for e in (_parse_student(rhs) for _, rhs in defs) if e is not None]
    eqs: list[sympy.Expr] = []
    m = _EXTREMUM_VALUE.search(q)
    if m and funcs:
        a, value = int(m.group(1)), int(m.group(2))
        with_params = [f for f in funcs if f.free_symbols - {var}]
        if with_params:
            eqs.append(with_params[0].subs(var, a) - value)
    touch = _TOUCH_AT.search(q)
    curves = visible_polynomials(q)
    curves = [c for c in curves if var in c.free_symbols and sympy.degree(c, var) >= 1]
    if touch and len(curves) >= 2:
        a = int(touch.group(1))
        eqs.append(curves[0].subs(var, a) - curves[1].subs(var, a))
    return eqs


def _value_determines_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    asked = _asked_parameter(probe)
    if asked is None:
        return []
    eqs = _value_equations(probe, var)
    if not eqs:
        return []
    target = sympy.Symbol(asked)
    unknowns = sorted(set().union(*(e.free_symbols for e in eqs)) - {var}, key=str)
    if target not in unknowns:
        return []
    solutions = sympy.solve(eqs, unknowns, dict=True)
    values = {sol.get(target) for sol in solutions}
    if len(values) == 1 and None not in values and not next(iter(values)).free_symbols:
        return [
            ShortcutViolation(
                "T-value-determines",
                f"발문의 함숫값 조건만으로 상수 {asked}가 정해진다 — 미분계수 조건이 풀이에 쓰이지 "
                "않는다(대입만으로 풀린다).",
            )
        ]
    return []


_GIVEN_RATE = re.compile(r"평균변화율(?:은|이|는)?\s+-?\d")


def _mvt_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _GIVEN_RATE.search(probe.question_text):
        return [
            ShortcutViolation(
                "T06-given-rate",
                "발문이 평균변화율의 값을 직접 준다 — 평균변화율을 구해 미분계수와 잇는 평균값 "
                "정리의 "
                "행위가 빠진다.",
            )
        ]
    return []


#: 도함수 부등식 — 코드식('<=')과 학생 표기('≤') 둘 다 읽는다(표기 교정이 규칙을 끄지 않게).
_DERIV_INEQ = re.compile(r"(?<![A-Za-z])[a-z]'\((?:x|t)\)\s*(?:<|>|<=|>=|≤|≥)\s")
_PINNED_KIND = re.compile(r"(?<![A-Za-z])x = -?\d+에서(?:의)? 극(?:댓|솟)값")
#: [4회차] 발문이 고정한 x 위치 — 'x = -1과 x = 3'·'x = 1/2'.
_PIN_X = re.compile(r"(?<![A-Za-z])x = (-?\d+(?:/\d+)?)")


def _sign_change_roots(expr: sympy.Expr, var: sympy.Symbol) -> set[sympy.Rational]:
    """f'의 유리수 근 중 좌우에서 부호가 바뀌는 근(= 극값을 갖는 x) — 판정 정의의 단일 원천."""
    deriv = sympy.expand(sympy.diff(expr, var))
    if deriv.free_symbols != {var}:
        return set()
    roots = sorted(
        r for r in sympy.roots(sympy.Poly(deriv, var)) if r.is_rational  # 정수·분수 근만
    )
    if not roots:
        return set()
    middles = [(a + b) / 2 for a, b in zip(roots, roots[1:], strict=False)]
    probes = [roots[0] - 1, *middles, roots[-1] + 1]
    signs = [sympy.sign(deriv.subs(var, p)) for p in probes]
    return {r for i, r in enumerate(roots) if signs[i] * signs[i + 1] < 0}


def _graph_shape_round4_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[4회차] 02-08 — 극값 위치를 둘 이상 준 문항·복이차 사차식."""
    q = probe.question_text
    x = sympy.Symbol("x")
    pins = {sympy.Rational(v) for v in _PIN_X.findall(q)}
    out: list[ShortcutViolation] = []
    given = False
    biquadratic = False
    for poly in visible_polynomials(q):
        if x not in poly.free_symbols:
            continue
        if len(pins & _sign_change_roots(poly, x)) >= 2:
            given = True
        if poly.free_symbols == {x} and is_shifted_biquadratic(poly, x):
            biquadratic = True
    if given:
        out.append(
            ShortcutViolation(
                "T08-given-critical-points",
                "발문이 극값을 갖는 x 위치를 둘 이상 준다 — 그 위치에 대입해 대소를 비교하면 "
                "극댓값·극솟값이 정해져(삼차·사차에서 '큰 값이 극댓값') 도함수와 부호 판정이 필요 "
                "없다. 임계점은 학생이 f'(x) = 0을 풀어 찾게 한다.",
            )
        )
    if biquadratic:
        out.append(
            ShortcutViolation(
                "T08-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(복이차)이라 (x - h)^2 = u로 두면 완전제곱만으로 "
                "극값의 위치·값이 나온다 — 비대칭 사차식을 쓴다.",
            )
        )
    return out


def _graph_shape_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    out: list[ShortcutViolation] = []
    if _DERIV_INEQ.search(q):
        out.append(
            ShortcutViolation(
                "T08-derivative-inequality",
                "발문이 도함수 부등식(f'(x) < 0 등)을 직접 준다 — 증가·감소 판정 없이 이차부등식만 "
                "풀면 된다.",
            )
        )
    if _PINNED_KIND.search(q) and _asked_parameter(probe) is None:
        out.append(
            ShortcutViolation(
                "T08-pinned-kind",
                "극값의 위치와 종류를 발문이 모두 주고 그 값을 묻는다 — 대입만으로 풀린다.",
            )
        )
    return out


def _equation_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    var = _variable_of(probe)
    amap = probe.answer_dict
    out: list[ShortcutViolation] = []
    has_derivative_condition = any("Derivative" in c for c in probe.conditions)
    if probe.answer_kind == _REAL_ROOT_COUNT:
        form = "count"
    elif set(amap) == {str(var)} and not has_derivative_condition:
        form = "root"
    elif str(var) in amap and has_derivative_condition:
        form = "extremum"
    else:
        return []
    if form == "extremum":
        pinned = amap[str(var)]
        if pinned.strip() == "0":
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 x = 0에서 갖는다 — 다항식의 상수항이 곧 답이라 미분이 필요 "
                    "없다.",
                )
            )
        if re.search(rf"(?<![A-Za-z]){var} = {re.escape(pinned)}(?![\d/])", probe.question_text):
            out.append(
                ShortcutViolation(
                    "T09-pinned-minimizer",
                    "최솟값(극값)을 묻는데 발문이 그 값을 갖는 x를 알려 준다 — 대입만으로 풀린다.",
                )
            )
        return out
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    if relation is None:
        return []
    poly = relation.difference
    if poly.free_symbols != {var}:
        return []
    visible = visible_polynomials(probe.question_text)
    for side in (relation.lhs, relation.rhs):
        if side.free_symbols and not any(sympy.expand(side - v) == 0 for v in visible):
            return []  # 학생이 보지 못하는 대표 함수(극값 증인)로 검산하는 문항
    if sympy.degree(poly, var) <= 2:
        out.append(
            ShortcutViolation(
                "T09-low-degree",
                "발문의 방정식·부등식이 이차 이하라 판별식·근의 공식만으로 풀린다.",
            )
        )
    if has_rational_root(poly, var):
        out.append(
            ShortcutViolation(
                "T09-rational-root",
                f"발문에 보이는 다항식 {poly}이 유리수 근을 갖는다 — 인수정리·인수분해로 근(또는 "
                "등호점)을 바로 얻어 도함수가 필요 없다.",
            )
        )
    if is_shifted_biquadratic(poly, var):
        out.append(
            ShortcutViolation(
                "T09-biquadratic",
                "발문의 사차식이 x = h에 대해 대칭(짝수 차 항만)이라 (x - h)^2 = u로 두면 "
                "이차방정식이 "
                "된다 — 도함수 없이 근의 공식·판별식으로 풀린다.",
            )
        )
    if form == "root" and _has_repeated_factor(poly, var):
        out.append(
            ShortcutViolation(
                "T09-repeated-root",
                "등호가 성립하는 점(근)을 묻는데 그 점이 중근이다 — 완전제곱·인수로 바로 얻는다.",
            )
        )
    return out


#: [4회차] 02-09의 '활용' 맥락 — 방정식·부등식·교점·위치 관계 중 하나는 발문에 있어야 한다.
_APPLICATION = re.compile(
    r"방정식|부등식|실근|만나|교점|위쪽|아래쪽|보이려|성립|보다 크|보다 작|오른쪽|왼쪽"
    r"|시각의 개수|x축"
)


def _application_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    if _APPLICATION.search(probe.question_text):
        return []
    return [
        ShortcutViolation(
            "T09-no-application",
            "발문에 방정식·부등식·교점·위치 관계 맥락이 없는 최댓값·최솟값 문항이다 — "
            "02-09(방정식과 부등식에의 활용)의 인지 행동 없이 극값 비교(02-07/02-08 영역)만으로 "
            "풀린다.",
        )
    ]


#: [4회차] 운동 문항의 위치 함수 — '위치가 x = 7로'·'위치가 x = -3t + 2일 때'·'위치가 x(t) = …'.
_POSITION = re.compile(r"위치가 (?:x|x\(t\)) = (?P<rhs>[^가-힣,]+)")


def _velocity_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q = probe.question_text
    instant = re.sub(r"평균\s*속도", "", q)
    out: list[ShortcutViolation] = []
    if re.search(r"평균\s*속도", q) and not re.search(r"속도|속력|멈추|정지|방향", instant):
        out.append(
            ShortcutViolation(
                "T10-average-only",
                "평균속도만 묻는다 — 위치에 두 시각을 대입한 차분몫이라 미분(순간속도)이 필요 "
                "없다.",
            )
        )
    t = sympy.Symbol("t")
    if re.search(r"속도|속력", instant):
        for m in _POSITION.finditer(q):
            expr = _parse_student(_clean_rhs(m.group("rhs"), "t"))
            if expr is None:
                continue
            degree = int(sympy.degree(expr, t)) if t in expr.free_symbols else 0
            if degree <= 1:
                out.append(
                    ShortcutViolation(
                        "T10-linear-position",
                        f"위치 {m.group('rhs').strip()!r}가 t의 일차 이하인데 속도·가속도를 "
                        "묻는다 — "
                        "정지(속도 0)·등속(가속도 0)·일차함수의 기울기라는 선수 지식으로 풀린다.",
                    )
                )
                break
    return out


# ──────────────────────────────────────────────────────────────────────────
# [5회차] 은행 감사 S5(2026-10-08 · as-found k = 68) — 레코드 *구조*를 읽는 규칙
# ──────────────────────────────────────────────────────────────────────────
# 발문 어휘보다 레코드 구조(검산 조건의 미분 평가·함수 차수·정답 맵·선지·답 형식)를 먼저 읽는다.
# 미분 평가는 `Derivative(식, 변수[, 변수|횟수]).doit().subs(변수, 점)` 꼴로 쓰인다(Tier1 표기).
@dataclass(frozen=True, slots=True)
class _DerivCall:
    """검산 조건 문자열 안의 미분 평가 1개(바깥쪽 호출만 — 안에 든 Derivative는 몸통의 일부)."""

    body: str
    var: str
    order: int
    point: str | None
    start: int
    end: int


def _match_paren(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split_args(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _derivative_calls(text: str) -> list[_DerivCall]:
    """조건 문자열의 바깥쪽 `Derivative(...)` 호출 목록(몸통·변수·미분 횟수·대입점·위치)."""
    out: list[_DerivCall] = []
    cursor = 0
    head = "Derivative("
    while True:
        start = text.find(head, cursor)
        if start < 0:
            return out
        open_index = start + len(head) - 1
        close = _match_paren(text, open_index)
        if close < 0:
            return out
        args = _split_args(text[open_index + 1 : close])
        body = args[0]
        var = args[1] if len(args) > 1 else "x"
        rest = args[2:]
        if not rest:
            order = 1
        elif len(rest) == 1 and rest[0].isdigit():
            order = int(rest[0]) if rest[0] != var else 2
        else:
            order = 1 + len(rest)
        end = close + 1
        point: str | None = None
        if text.startswith(".doit()", end):
            end += len(".doit()")
            if text.startswith(".subs(", end):
                subs_open = end + len(".subs")
                subs_close = _match_paren(text, subs_open)
                if subs_close > 0:
                    subs_args = _split_args(text[subs_open + 1 : subs_close])
                    if len(subs_args) == 2 and subs_args[0] == var:
                        point = subs_args[1]
                    end = subs_close + 1
        out.append(_DerivCall(body, var, order, point, start, end))
        cursor = end


def _sides(condition: str) -> tuple[str, str, str] | None:
    """'lhs op rhs' → (lhs, op, rhs) 원문(공백으로 감싼 첫 관계 연산자)."""
    match = _REL_RE.search(condition)
    if match is None:
        return None
    return condition[: match.start()].strip(), match.group(1), condition[match.end() :].strip()


def _plain_call(side: str) -> _DerivCall | None:
    """한 변이 통째로 미분 평가 하나인가(`Derivative(F, x).doit().subs(x, P)`) — 그 호출."""
    calls = _derivative_calls(side)
    if len(calls) == 1 and calls[0].start == 0 and calls[0].end == len(side):
        return calls[0]
    return None


def _sym(text: str) -> sympy.Expr | None:
    try:
        value = safe_sympify(text)
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    return value if isinstance(value, sympy.Expr) else None


def _poly_degree(body: str, var: str) -> int | None:
    """몸통이 var의 다항식이면 차수(몸통에 Derivative가 섞이면 None — 단순 함수만 본다)."""
    if "Derivative" in body:
        return None
    expr = _sym(body)
    if expr is None:
        return None
    symbol = sympy.Symbol(var)
    try:
        return int(sympy.Poly(sympy.expand(expr), symbol).degree())
    except (sympy.PolynomialError, sympy.GeneratorsError):
        return None


@dataclass(frozen=True, slots=True)
class _MainRelation:
    """미분 평가가 한 변을 통째로 차지하는 등식 — (호출, 다른 변의 식)."""

    call: _DerivCall
    other: sympy.Expr


def _main_relations(probe: ShortcutProbe) -> list[_MainRelation]:
    out: list[_MainRelation] = []
    for condition in probe.conditions:
        parts = _sides(condition)
        if parts is None or parts[1] != "=":
            continue
        lhs, _, rhs = parts
        for side, other in ((lhs, rhs), (rhs, lhs)):
            call = _plain_call(side)
            if call is None or "Derivative" in other:
                continue
            other_expr = _sym(other)
            if other_expr is not None:
                out.append(_MainRelation(call, other_expr))
    return out


def _answer_var(probe: ShortcutProbe) -> sympy.Symbol | None:
    """정답이 가리키는 미지수 — 정답 맵에서 값이 정답과 같은 키(하나일 때)."""
    amap = probe.answer_dict
    keys = [k for k, v in amap.items() if v.strip() == probe.answer.strip()]
    if len(keys) == 1:
        return sympy.Symbol(keys[0])
    if len(amap) == 1:
        return sympy.Symbol(next(iter(amap)))
    return None


def _rational(text: str) -> sympy.Rational | None:
    expr = _sym(text)
    if expr is None or expr.free_symbols or not expr.is_rational:
        return None
    return sympy.Rational(expr)


def _side_filters(probe: ShortcutProbe, var: sympy.Symbol) -> list[_Relation]:
    """var에 대한 부등식·≠ 조건(한 변이 var, 다른 변이 수)."""
    out: list[_Relation] = []
    for condition in probe.conditions:
        relation = _parse_relation(condition)
        if relation is None or relation.op == "=":
            continue
        if relation.lhs == var and not relation.rhs.free_symbols:
            out.append(relation)
    return out


def _passes(value: sympy.Expr, filters: Sequence[_Relation]) -> bool:
    for f in filters:
        if f.op == ">" and not value > f.rhs:
            return False
        if f.op == ">=" and not value >= f.rhs:
            return False
        if f.op == "<" and not value < f.rhs:
            return False
        if f.op == "<=" and not value <= f.rhs:
            return False
        if f.op == "!=" and value == f.rhs:
            return False
    return True


def _open_bounds(probe: ShortcutProbe, var: sympy.Symbol) -> tuple[sympy.Expr | None, ...]:
    """var의 (하한, 상한) — 조건 목록의 부등식에서 읽는다(없으면 None)."""
    lows = [f.rhs for f in _side_filters(probe, var) if f.op in (">", ">=")]
    highs = [f.rhs for f in _side_filters(probe, var) if f.op in ("<", "<=")]
    return (max(lows) if lows else None, min(highs) if highs else None)


def _solutions(eq: sympy.Expr, var: sympy.Symbol, filters: Sequence[_Relation]) -> set[sympy.Expr]:
    """eq = 0의 실수 해 중 보호 조건을 통과하는 것(풀 수 없으면 빈 집합 — 판정 보류)."""
    if eq.free_symbols != {var}:
        return set()
    try:
        raw = sympy.solve(eq, var)
    except (NotImplementedError, ValueError, TypeError):
        return set()
    return {r for r in raw if r.is_real and _passes(r, filters)}


def _answer_value(probe: ShortcutProbe) -> sympy.Rational | None:
    return _rational(probe.answer.strip())


_MVT_CODES: Final = frozenset({"[12미적Ⅰ-02-06]", "[12미적Ⅰ-02-10]"})


def _shown_functions(question: str, var: str) -> list[sympy.Expr]:
    """발문에 학생이 보는 var의 다항식 중 변수 하나('x = 1에서'의 x)가 아닌 것."""
    v = sympy.Symbol(var)
    return [p for p in visible_polynomials(question) if v in p.free_symbols and p != v]


def _is_shown(body: sympy.Expr, question: str, var: str) -> bool:
    """미분하는 식이 발문의 다항식 그대로인가(전개해 비교)."""
    expanded = sympy.expand(body)
    return any(sympy.expand(expanded - p) == 0 for p in _shown_functions(question, var))


def _quadratic_mean_value_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 이차함수의 평균값 정리·롤의 정리·평균속도 = 순간속도 — c는 늘 구간의 중점이다."""
    code = probe.standard_code
    hit = False
    if code == _C06:
        for condition in probe.conditions:
            for call in _derivative_calls(condition):
                degree = _poly_degree(call.body, call.var)
                if degree is not None and degree <= 2:
                    hit = True
        if probe.answer_kind == _REAL_ROOT_COUNT:
            relation = next(
                (r for r in map(_parse_relation, probe.conditions) if r is not None), None
            )
            if relation is not None:
                diff = relation.difference
                free = sorted(diff.free_symbols, key=str)
                if len(free) == 1 and sympy.degree(diff, free[0]) <= 1:
                    hit = True
    elif code == _C10:
        for rel in _main_relations(probe):
            call = rel.call
            if call.order != 1 or call.point is None or _rational(call.point) is not None:
                continue
            degree = _poly_degree(call.body, call.var)
            if degree is None or degree > 2 or rel.other.free_symbols:
                continue
            low, high = _open_bounds(probe, sympy.Symbol(call.point))
            if low is None or high is None or low == high:
                continue
            body = _sym(call.body)
            assert body is not None
            v = sympy.Symbol(call.var)
            rate = (body.subs(v, high) - body.subs(v, low)) / (high - low)
            if sympy.simplify(rate - rel.other) == 0:
                hit = True
    if not hit:
        return []
    return [
        ShortcutViolation(
            "T-quadratic-mean-value",
            "이차 이하 함수에 평균값 정리·롤의 정리(평균속도 = 순간속도)를 쓴다 — 도함수가 일차라 "
            "c가 늘 구간의 중점(롤은 대칭축)이어서 미분 없이 '가운데 값'으로 풀린다. 삼차 "
            "이상으로 쓴다.",
        )
    ]


def _quadratic_rest_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-10) 이차 위치함수의 속도 0 시각 — 위치 포물선의 꼭짓점이다."""
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) is not None:
            continue
        degree = _poly_degree(call.body, call.var)
        body = _sym(call.body)
        if body is None or not _is_shown(body, probe.question_text, call.var):
            # 두 점의 위치 차처럼 발문에 그대로 보이지 않는 식의 꼭짓점은 학생의 경로가 아니다
            continue
        if degree is not None and degree <= 2 and rel.other == 0:
            return [
                ShortcutViolation(
                    "T10-quadratic-rest",
                    "위치가 이차 이하인데 속도가 0인(멈추는·방향이 바뀌는) 시각을 묻는다 — 위치 "
                    "포물선의 꼭짓점 -b/(2a)로 미분 없이 풀린다. 위치를 삼차 이상으로 쓴다.",
                )
            ]
    return []


def _midpoint_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-06·02-10) 정답이 구간의 중점 — '가운데 값' 추측이 정답이 된다(변별 없음)."""
    if probe.standard_code not in _MVT_CODES:
        return []
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    low, high = _open_bounds(probe, var)
    hit = low is not None and high is not None and answer == (low + high) / 2
    if not hit:
        # 끝점 미지수형 — c와 한 끝점이 주어지고 다른 끝점을 묻는다(중점이면 2c - 끝점).
        for rel in _main_relations(probe):
            point = _rational(rel.call.point) if rel.call.point is not None else None
            if point is None or var not in rel.other.free_symbols:
                continue
            for fixed in (low, high):
                if fixed is not None and answer == 2 * point - fixed:
                    hit = True
    if not hit:
        return []
    return [
        ShortcutViolation(
            "T-midpoint-answer",
            "정답이 구간의 중점(끝점 미지수형이면 2c - 끝점)과 같다 — 평균값 정리를 모르고 '구간의 "
            "가운데'를 고르는 경로가 정답에 닿는다. c ≠ 중점인 매개변수를 쓴다.",
        )
    ]


def _integer_pin_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 자연수 답인데 발문의 구간 안 자연수가 하나뿐 — 구간 단서가 답을 알려 준다."""
    if probe.choices:
        return []
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None or not answer.is_integer or answer <= 0:
        return []
    if probe.answer_format not in (None, "자연수"):
        return []
    low, high = _open_bounds(probe, var)
    if low is None or high is None:
        return []
    inside = [n for n in range(int(sympy.floor(low)) + 1, int(sympy.ceiling(high))) if n > 0]
    inside = [n for n in inside if low < n < high]
    if inside == [int(answer)]:
        return [
            ShortcutViolation(
                "T-integer-pinned-by-interval",
                f"답 형식이 자연수인데 구간 ({low}, {high}) 안의 자연수가 {answer} 하나뿐이다 — "
                "구간 단서만으로 답이 정해진다. 구간을 넓히거나 정수가 아닌 답을 쓴다.",
            )
        ]
    return []


_NUMBER_TOKEN = re.compile(r"(?<![A-Za-z0-9_.^/])-?\d+(?:/\d+)?(?![A-Za-z0-9_^/])")


def _roots_given_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-06) 발문이 방정식 f'(x) = (평균변화율)의 근을 모두 적는다 — 고르기만 남는다."""
    if probe.standard_code != _C06 or "근" not in probe.question_text:
        return []
    numbers = set(_NUMBER_TOKEN.findall(probe.question_text))
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) is not None:
            continue
        body = _sym(call.body)
        if body is None or rel.other.free_symbols:
            continue
        v = sympy.Symbol(call.var)
        roots = _solutions(sympy.diff(body, v) - rel.other, v, ())
        texts = {str(sympy.Rational(r)) for r in roots if r.is_rational}
        if len(texts) >= 2 and len(texts) == len(roots) and texts <= numbers:
            return [
                ShortcutViolation(
                    "T06-roots-given",
                    "발문이 평균값 정리 방정식 f'(x) = (평균변화율)의 근을 모두 적는다 — "
                    "도함수·평균변화율 계산 없이 구간 안의 값을 고르기만 하면 된다.",
                )
            ]
    return []


def _function_value_path_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 미분계수 대신 함숫값(가속도면 위치·속도)을 넣어도 같은 답 — 대표 오답 경로와 일치."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    for rel in _main_relations(probe):
        call = rel.call
        if call.point is None or "Derivative" in call.body:
            continue
        body, point = _sym(call.body), _sym(call.point)
        if body is None or point is None:
            continue
        v = sympy.Symbol(call.var)
        # 학생이 보는 다항식이 없으면(추상 함수 f·g의 미분계수만 준 문항) 검산 조건의 함수는 증인일
        # 뿐이라 그 함숫값은 학생의 경로가 아니다. 미지수가 지수에 든 검산식(cx^m 꼴 대조)도 같은
        # 이유로 본다.
        shown = _shown_functions(probe.question_text, call.var) or re.search(
            rf"(?<![A-Za-z]){call.var}\^\d", probe.question_text
        )
        if not shown:
            continue
        if var in rel.other.free_symbols and not rel.other.is_polynomial(var):
            continue
        wrong_sides = [body] + [sympy.diff(body, v, k) for k in range(1, call.order)]
        for wrong in wrong_sides:
            eq = sympy.expand(wrong.subs(v, point) - rel.other)
            if var not in eq.free_symbols:
                continue
            if _solutions(eq, var, filters) == {answer}:
                return [
                    ShortcutViolation(
                        "T-function-value-path",
                        "미분계수 대신 함숫값(가속도 문항이면 위치·속도)을 대입하는 대표 오답 "
                        "경로로 풀어도 정답과 같은 값이 나온다 — 변별이 없다. 그 매개변수를 쓰지 "
                        "않는다.",
                    )
                ]
    return []


def _coefficient_reading_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 발문에 보이는 다항식의 x = 0(t = 0) 미분계수 — 일차항 계수를 읽으면 끝난다.

    '도함수 f'(x)의 상수항'을 묻는 문항은 검산이 같은 f'(0)이지만 과제 자체가 '도함수를 구해
    상수항을 읽는 것'이고, 미분을 모르는 학생은 어느 계수를 읽을지 정하지 못한다 — 이 규칙의 대상이
    아니다.
    """
    if "상수항" in probe.question_text:
        return []
    for rel in _main_relations(probe):
        call = rel.call
        if call.order != 1 or call.point is None or _rational(call.point) != 0:
            continue
        body = _sym(call.body)
        if body is None or "Derivative" in call.body:
            continue
        if _is_shown(body, probe.question_text, call.var):
            return [
                ShortcutViolation(
                    "T-coefficient-reading",
                    "발문의 다항식을 x = 0(t = 0, y축 위의 점·출발 순간)에서 미분한 값을 묻는다 — "
                    "그 값은 일차항 계수 그대로라 계수를 읽기만 해도(거듭제곱 미분 오류가 있어도) "
                    "정답이 나온다.",
                )
            ]
    return []


def _constant_derivative_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 미분하는 식이 상수 — f - g가 상수인 두 함수처럼 모든 경로가 0이다.

    발문이 두 함수를 *따로 명시*할 때만 본다. 'g(x) = f(x) + 2일 때 g'(a) - f'(a)'처럼 상수 차이
    자체가 진단 대상인 문항(상수의 미분이 0임을 묻는다)은 상수가 살아남는다고 보는 오답 경로가
    정답과 갈린다.
    """
    for condition in probe.conditions:
        for call in _derivative_calls(condition):
            body = _sym(call.body)
            if body is None or len(_shown_functions(probe.question_text, call.var)) < 2:
                continue
            if sympy.Symbol(call.var) not in sympy.expand(body).free_symbols:
                return [
                    ShortcutViolation(
                        "T-constant-derivative",
                        "미분하는 식이 변수에 대한 상수다(예: f - g가 상수인 두 함수의 f'(a) - "
                        "g'(a)) — 답이 늘 0이고 어떤 오답 경로도 0이라 변별이 없다.",
                    )
                ]
    return []


def _count_polynomial(probe: ShortcutProbe) -> tuple[sympy.Expr, sympy.Symbol] | None:
    if probe.answer_kind != _REAL_ROOT_COUNT:
        return None
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    if relation is None:
        return None
    poly = relation.difference
    free = sorted(poly.free_symbols, key=str)
    if len(free) != 1:
        return None
    return poly, free[0]


def _count_path_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-09) 실근 개수의 대표 오답 경로 — 차수로 센 값·임계점 개수가 정답과 같다."""
    found = _count_polynomial(probe)
    answer = _answer_value(probe)
    if found is None or answer is None:
        return []
    poly, var = found
    out: list[ShortcutViolation] = []
    if answer == sympy.degree(poly, var):
        out.append(
            ShortcutViolation(
                "T09-degree-count",
                "실근의 개수가 방정식의 차수와 같다 — 'n차방정식이니 근이 n개'라는 차수 세기 오답 "
                "경로가 미분 없이 정답에 닿는다.",
            )
        )
    critical = sympy.real_roots(sympy.Poly(sympy.diff(poly, var), var))
    if answer == len(set(critical)):
        out.append(
            ShortcutViolation(
                "T09-critical-count",
                "실근의 개수가 f'(x) = 0의 서로 다른 실근(극값 후보)의 개수와 같다 — 극값 후보를 "
                "근으로 센 오답 경로가 정답에 닿는다.",
            )
        )
    return out


def _given_extremum_values_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-09) 개수 문항의 방정식이 발문에 보이지 않는다 — 극값을 발문이 알려 준다."""
    found = _count_polynomial(probe)
    if found is None:
        return []
    relation = next((r for r in map(_parse_relation, probe.conditions) if r is not None), None)
    assert relation is not None
    visible = visible_polynomials(probe.question_text)
    shown = [
        side
        for side in (relation.lhs, relation.rhs)
        if side.free_symbols and any(sympy.expand(side - v) == 0 for v in visible)
    ]
    if shown:
        return []
    return [
        ShortcutViolation(
            "T09-given-extremum-values",
            "실근 개수를 묻는데 방정식의 함수가 발문에 없고 극댓값·극솟값을 발문이 준다 — 도함수 "
            "없이 개형 상식과 대소 비교만으로 풀린다. 함수를 명시해 극값을 미분으로 구하게 한다.",
        )
    ]


def _quadratic_tangent_constant_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 이차 곡선의 접선 조건을 미분 없이(판별식·중근) 검산한다 — 그 경로로
    풀린다."""
    if any("Derivative" in c for c in probe.conditions) or not probe.conditions:
        return []
    x = sympy.Symbol("x")
    degrees = [
        int(sympy.degree(p, x))
        for p in visible_polynomials(probe.question_text)
        if x in p.free_symbols
    ]
    if not degrees or max(degrees) > 2 or "접" not in probe.question_text:
        return []
    return [
        ShortcutViolation(
            "T05-quadratic-tangent-constant",
            "곡선이 이차 이하인데 접선의 y절편·곡선의 상수·곡선 밖의 점에서 그은 접선을 묻는다 — "
            "연립한 이차방정식의 중근(판별식)만으로 풀린다. 곡선을 삼차 이상으로 쓴다.",
        )
    ]


_GIVEN_POINT = re.compile(r"\((-?\d+(?:/\d+)?), (-?\d+(?:/\d+)?)\)")


def _given_coordinate_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 정답이 발문에 적힌 점의 y좌표 — 발문이 답을 알려 준다(x = 1의 m + n 등)."""
    answer = _answer_value(probe)
    if answer is None:
        return []
    for m in _GIVEN_POINT.finditer(probe.question_text):
        if sympy.Rational(m.group(2)) == answer:
            return [
                ShortcutViolation(
                    "T05-given-coordinate",
                    f"정답 {answer}이(가) 발문에 적힌 점 {m.group(0)}의 y좌표와 같다 — 접선을 "
                    "몰라도 그 좌표를 옮겨 적으면 맞는다(예: x = 1에서 m + n은 접점의 y좌표).",
                )
            ]
    return []


#: 설명에 *절차*가 적히지 않은 오개념 — 연결 선지가 그 절차의 값인지 판정할 수 없다(설명 손상).
#: M0677: '…관점을 — …관점을 못 쓴다'(서술어 절단·절차 미기술 — QUAL-14가 원문 정정을 소유한다).
_UNDESCRIBED_MISCONCEPTIONS: Final = frozenset({"M0677"})


def _misconception_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 오답 선지–오개념 연결 — 연결 선지가 그 오개념 절차로 실제로 나오는 값인가."""
    if not probe.distractors or not probe.choices:
        return []
    out: list[ShortcutViolation] = []
    linked: dict[str, list[sympy.Rational | None]] = {}
    for index, mid in probe.distractors:
        value = _rational(probe.choices[index]) if 0 <= index < len(probe.choices) else None
        linked.setdefault(mid, []).append(value)
    if _UNDESCRIBED_MISCONCEPTIONS & set(linked):
        out.append(
            ShortcutViolation(
                "M-link-undescribed",
                "연결한 오개념의 설명에 잘못된 절차가 적혀 있지 않다 — 선지 값이 그 오개념에서 "
                "나오는지 판정할 수 없다. 절차가 적힌 오개념에 연결하거나 연결하지 않는다.",
            )
        )
    bad = False
    count = _count_polynomial(probe)
    if "M0615" in linked:
        degree = sympy.degree(count[0], count[1]) if count is not None else None
        bad |= any(value is None or value != degree for value in linked["M0615"])
    if "critical-point-implies-extremum" in linked:
        roots = _critical_roots(probe)
        asks_kind = re.search(r"극대|극소|극댓값|극솟값", probe.question_text) is not None
        bad |= asks_kind or any(
            value is None or value not in roots
            for value in linked["critical-point-implies-extremum"]
        )
    if "M0674" in linked:
        roots = _critical_roots(probe)
        bad |= any(value is None or value not in roots for value in linked["M0674"])
    if bad:
        out.append(
            ShortcutViolation(
                "M-link-procedure",
                "오개념이 연결된 선지가 그 오개념의 절차(차수만큼 근을 센다 · f'(a) = 0이면 "
                "극값으로 본다 · 롤의 정리처럼 f'(c) = 0을 푼다)로 나오는 값이 아니다 — 또는 묻는 "
                "대상(극대·극소)이 그 절차의 산출과 다르다.",
            )
        )
    return out


def _critical_roots(probe: ShortcutProbe) -> set[sympy.Expr]:
    """검산 조건의 미분 대상 함수 F에 대해 F'(x) = 0의 실근(유리근) — 오개념 절차 값 판정용."""
    roots: set[sympy.Expr] = set()
    for condition in probe.conditions:
        for call in _derivative_calls(condition):
            if call.order != 1 or "Derivative" in call.body:
                continue
            body = _sym(call.body)
            if body is None:
                continue
            v = sympy.Symbol(call.var)
            if body.free_symbols != {v}:
                continue
            roots |= _solutions(sympy.diff(body, v), v, ())
    return roots


# ── [5회차] 해설 ──────────────────────────────────────────────────────────
_PREMISE_ROOT = re.compile(r"[a-z]'\(x\) = 0의 한 근이 x = (-?\d+)")
_LETTER_TOKEN = re.compile(r"(?<![A-Za-z])([a-z])(?![A-Za-z])")


def _math_use(text: str, index: int, letter: str) -> bool:
    """explanation[index]의 문자 하나가 수식 안에서 쓰였는가(앞뒤가 숫자·연산자·괄호·등호)."""
    before = text[:index].rstrip()
    after = text[index + len(letter) :].lstrip()
    prev = before[-1:] if before else ""
    nxt = after[:1] if after else ""
    return bool(
        (prev and (prev.isdigit() or prev in "=+-*/^(),"))
        or (nxt and (nxt in "=+-*/^()" or nxt.isdigit()))
    )


def _explanation_round5_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    q, e = probe.question_text, probe.explanation
    out: list[ShortcutViolation] = []
    premise = _PREMISE_ROOT.search(q)
    if premise is not None:
        p = premise.group(1)
        if re.search(rf"x = {re.escape(p)}에서 극값을 가지므로", e) and not re.search(
            rf"x = {re.escape(p)}에서 극", q
        ):
            out.append(
                ShortcutViolation(
                    "E-premise-reversal",
                    "발문은 'f'(x) = 0의 한 근이 x = p'만 주는데 해설은 'x = p에서 극값을 "
                    "가지므로'를 근거로 쓴다 — 발문 조건 f'(p) = 0을 그대로 쓴다(f'(p) = 0이 "
                    "극값을 뜻하지 않는다).",
                )
            )
    q_letters = set(_LETTER_TOKEN.findall(q))
    exempt = {"x", "t", "f", "g", "h", "y"}
    # 운동 문항의 v(t)·a(t)는 발문·해설이 '속도'·'가속도'를 말하면 관례 기호로 본다(멈춤 문항처럼 두
    # 말이 다 없으면 소개 없는 기호다 — 판정자 지적 be76bfc1).
    if "속도" in e or "속도" in q:
        exempt.add("v")
    if "가속도" in e or "가속도" in q:
        exempt.add("a")
    for m in _LETTER_TOKEN.finditer(e):
        letter = m.group(1)
        if letter in exempt or letter in q_letters or not _math_use(e, m.start(), letter):
            continue
        if re.search(_INTRO.format(L=letter), e):
            continue
        out.append(
            ShortcutViolation(
                "E-undefined-letter",
                f"해설이 발문에 없는 기호 {letter}를 소개 없이 식에 쓴다"
                f"('{e[max(0, m.start() - 8) : m.end() + 6]}') — 기호를 쓰지 않거나 먼저 "
                f"'…를 {letter}라 하자'로 정의한다.",
            )
        )
        break
    out += _excluded_root_rule(probe)
    if "가속도" in q and not _VELOCITY_FORMULA.search(e):
        out.append(
            ShortcutViolation(
                "E-velocity-before-acceleration",
                "가속도를 묻는데 해설에 속도 v(t)의 식이 없다 — 위치를 미분한 v(t)를 먼저 쓰고 "
                "다시 미분해 a(t)를 쓴다.",
            )
        )
    if re.search(r"멈추|정지", q) and not ("도함수" in e and re.search(r"v\(t\) = 0|속도가 0", e)):
        out.append(
            ShortcutViolation(
                "E-rest-meaning",
                "멈추는 시각을 묻는데 해설이 '속도 v(t)는 위치의 도함수'와 '멈춤 ⇔ v(t) = 0'을 "
                "말하지 않는다.",
            )
        )
    if "y축과 만나는 점" in q and not re.search(r"x좌표는 0|x = 0", e):
        out.append(
            ShortcutViolation(
                "E-y-axis-zero",
                "y축과 만나는 점을 다루는데 해설에 '그 점의 x좌표는 0'(x = 0) 단계가 없다.",
            )
        )
    if re.search(r"(?:인데|는데),[^.]*(?:인데|는데),", e):
        out.append(
            ShortcutViolation(
                "E-run-on", "해설 한 문장에 '~인데, ~인데,'가 겹친다(비문) — 문장을 나눈다."
            )
        )
    if re.search(r"롤의 정리의 결론(?:이다|인데)", e):
        out.append(
            ShortcutViolation(
                "E-term-rolle",
                "수 하나를 '롤의 정리의 결론'이라 부른다 — 결론은 'f'(c) = 0인 c가 존재한다'는 "
                "명제다.",
            )
        )
    return out


#: 세운 방정식을 정리한 꼴 — 'a^2 = 16'·'a^2이 16'·'t^2 = 25'·'(3a + 10)(a - 4) = 0'·
#: 'a^8(a - 9) = 0'.
_REDUCED_EQUATION = re.compile(r"[a-z]\^\d+\s*(?:=|이|가)\s*-?\d|\)\s*=\s*0")
#: 보호 조건으로 근을 고르는 근거 — 양수·음수·부등식·0이 아님·'~가 아닌 근'.
_SELECTION = re.compile(r"양수|음수|[a-z] > -?\d|[a-z] < -?\d|0이 아니|≠ 0|아닌 근")
_ZERO_EXCLUDED = re.compile(r"0이 아니|≠ 0|[a-z] = 0")


def _excluded_root_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] 보호 조건(양수·0이 아님)이 버리는 근을 해설이 보이지 않는다(a = ±3 → 양수 3 단계
    누락)."""
    var, answer = _answer_var(probe), _answer_value(probe)
    if var is None or answer is None:
        return []
    filters = _side_filters(probe, var)
    if not filters:
        return []
    e = probe.explanation
    for rel in _main_relations(probe):
        call = rel.call
        body, point = _sym(call.body), _sym(call.point) if call.point else None
        if body is None or point is None or "Derivative" in call.body:
            continue
        v = sympy.Symbol(call.var)
        eq = sympy.expand(sympy.diff(body, v, call.order).subs(v, point) - rel.other)
        if eq.free_symbols != {var}:
            continue
        all_roots = _solutions(eq, var, ())
        dropped = [r for r in all_roots if r != answer and not _passes(r, filters)]
        if not dropped:
            continue
        tokens = set(_NUMBER_TOKEN.findall(e))
        named = all(
            str(sympy.Rational(r)) in tokens or (r == 0 and _ZERO_EXCLUDED.search(e))
            for r in dropped
            if r.is_rational
        ) and all(r.is_rational for r in dropped)
        # 근을 다 적지 않아도 *세운 방정식을 정리한 꼴*(a^2 = 16 · 인수분해 = 0)과 *고르는
        # 근거*(양수· t > 0·0이 아닌)가 함께 있으면 핵심 단계를 보인 것으로 본다(판정자 A가 받아들인
        # 형제 해설 형태).
        reduced = _REDUCED_EQUATION.search(e) is not None
        selected = _SELECTION.search(e) is not None
        missing = [] if (named or "±" in e or (reduced and selected)) else dropped
        if missing:
            return [
                ShortcutViolation(
                    "E-excluded-root",
                    f"방정식의 근 {', '.join(str(r) for r in missing)}을(를) 발문의 조건으로 "
                    "버리는 단계가 해설에 없다 — 세운 방정식·근 전부·조건으로 고르는 단계를 "
                    "보인다.",
                )
            ]
    return []


def _evaluated(condition: str) -> _Relation | None:
    """조건 문자열의 미분 평가를 SymPy로 계산해 넣은 관계(미분 몸통에 다른 미분이 섞이면 None)."""
    parts = _sides(condition)
    if parts is None:
        return None
    lhs_text, op, rhs_text = parts
    sides: list[sympy.Expr] = []
    for text in (lhs_text, rhs_text):
        calls = _derivative_calls(text)
        if any("Derivative" in c.body for c in calls):
            return None
        rebuilt = text
        for call in reversed(calls):
            body = _sym(call.body)
            if body is None:
                return None
            v = sympy.Symbol(call.var)
            value = sympy.diff(body, v, call.order)
            if call.point is not None:
                point = _sym(call.point)
                if point is None:
                    return None
                value = value.subs(v, point)
            rebuilt = rebuilt[: call.start] + f"({sympy.sstr(value)})" + rebuilt[call.end :]
        expr = _sym(rebuilt)
        if expr is None:
            return None
        sides.append(expr)
    return _Relation(sides[0], op, sides[1])


_TOUCH_STATEMENT = re.compile(
    r"곡선 y = (?P<family>[^가-힣]+?)(?:가|이) 곡선 y = (?P<curve>[^가-힣]+?)(?:와|과) "
    r"(?:x = |x좌표가 )(?P<a>-?\d+)인 점에서 (?:서로 )?접"
)


#: 접점이 발문에서 고정된 접선의 y절편 —
#: (a) '곡선 y = F 위의 점 (a, b)에서의 접선의 y절편을 구하시오'
#: (b) '곡선 y = H + c (c는 상수) 위의 x좌표가 a인 점에서의 접선의 y절편이 n일 때'.
_INTERCEPT_AT_POINT = re.compile(
    r"곡선 y = (?P<curve>[^가-힣]+?) 위의 점 \((?P<a>-?\d+), -?\d+\)에서의 접선의 y절편을 구하"
)
_INTERCEPT_GIVEN = re.compile(
    r"곡선 y = (?P<curve>[^가-힣]+?) \([a-z]는 상수\) 위의 x좌표가 (?P<a>-?\d+)인 점에서의 접선의 "
    r"y절편이 (?P<n>-?\d+)일 때"
)


def _touch_statement(probe: ShortcutProbe, var: sympy.Symbol) -> tuple[int, set[object]] | None:
    """발문이 접점 x = a를 고정하는 세 형태의 (a, 발문 문제의 답 해집합) — 해당 없으면 None.

    판정기 쪽 참값은 미분(sympy.diff)으로 낸다 — 생성기의 검산 경로(미분 없는 항등식·판별식)와
    독립이다.
    """
    x = sympy.Symbol("x")
    match = _TOUCH_STATEMENT.search(probe.question_text)
    if match is not None:
        family, curve = _parse_student(match["family"]), _parse_student(match["curve"])
        if family is None or curve is None:
            return None
        a = int(match["a"])
        unknowns = sorted(family.free_symbols - {x}, key=str)
        if var not in unknowns:
            return None
        gap = sympy.expand(family - curve)
        statement = sympy.solve(
            [gap.subs(x, a), sympy.diff(gap, x).subs(x, a)], unknowns, dict=True
        )
        return a, {sol.get(var) for sol in statement}
    match = _INTERCEPT_AT_POINT.search(probe.question_text)
    if match is not None:
        curve = _parse_student(match["curve"])
        if curve is None or curve.free_symbols != {x}:
            return None
        a = int(match["a"])
        return a, {sympy.expand(curve.subs(x, a) - a * sympy.diff(curve, x).subs(x, a))}
    match = _INTERCEPT_GIVEN.search(probe.question_text)
    if match is not None:
        curve = _parse_student(match["curve"])
        if curve is None or var not in curve.free_symbols:
            return None
        a, n = int(match["a"]), int(match["n"])
        intercept = curve.subs(x, a) - a * sympy.diff(curve, x).subs(x, a)
        return a, set(sympy.solve(sympy.expand(intercept - n), var))
    return None


def _touch_verify_rule(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """[5회차] (02-05) 접점이 발문에서 고정된 문항 — 검산 조건이 발문의 문제를 담는가.

    대상: '두 곡선이 x = a인 점에서 접할 때'(곡선족의 상수 전부 미지 — 함숫값 일치 + 기울기 일치)와
    '위의 점 (a, b) / x좌표가 a인 점에서의 접선의 y절편'(접점 고정). 검산 조건만 풀어 얻는 답 후보가
    발문의 해와 다르면(예: 상수 하나를 고정하고 접점을 풀어 둔 판별식, 기울기만 같은 다른 접선까지
    담는 판별식 — 발문에 없는 보호 조건으로 둘째 해를 버린다) 다른 문제를 가리킨다(판정자 지적
    284122b4). 보호 조건(부등식·`!=`)은 일부러 읽지 않는다 — 발문에 없는 보호로 해를 고르는 것이
    결함 자체다.
    """
    var = _answer_var(probe)
    if var is None:
        return []
    touched = _touch_statement(probe, var)
    if touched is None:
        return []
    a, expected = touched
    equations: list[sympy.Expr] = []
    for condition in probe.conditions:
        relation = _evaluated(condition)
        if relation is not None and relation.op == "=":
            equations.append(relation.difference)
    if not equations:
        return []
    free = sorted(set().union(*(e.free_symbols for e in equations)), key=str)
    if var not in free:
        return []
    verified = {sol.get(var) for sol in sympy.solve(equations, free, dict=True)}
    if verified == expected:
        return []
    return [
        ShortcutViolation(
            "V05-touch-verify-mismatch",
            f"발문(접점 x = {a} 고정 · {var} 미지)의 해 {sorted(map(str, expected))}와 검산 조건의 "
            f"해 {sorted(map(str, verified))}가 다르다 — 검산 조건이 다른 문제를 담는다. 함숫값 "
            "일치와 기울기 일치(또는 (x - a)^2 인수 조건)로 검산한다.",
        )
    ]


def _round5_rules(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """5회차 규칙 전부(성취기준별 분기 포함)."""
    code = probe.standard_code
    out = (
        _midpoint_rule(probe)
        + _integer_pin_rule(probe)
        + _function_value_path_rule(probe)
        + _coefficient_reading_rule(probe)
        + _constant_derivative_rule(probe)
        + _misconception_rules(probe)
        + _explanation_round5_rules(probe)
    )
    if code in _MVT_CODES:
        out += _quadratic_mean_value_rule(probe)
    if code == _C06:
        out += _roots_given_rule(probe)
    if code == _C10:
        out += _quadratic_rest_rule(probe)
    if code == _C09:
        out += _count_path_rules(probe) + _given_extremum_values_rule(probe)
    if code == _C05:
        out += (
            _quadratic_tangent_constant_rule(probe)
            + _given_coordinate_rule(probe)
            + _touch_verify_rule(probe)
        )
    return out


def parameter_coincidences(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """매개변수 선택의 우연 일치 위반만(`COINCIDENCE_RULE_IDS`) — 생성기의 매개변수 거부 조건."""
    return [v for v in _round5_rules(probe) if v.rule in COINCIDENCE_RULE_IDS]


def shortcut_violations(probe: ShortcutProbe) -> list[ShortcutViolation]:
    """문항 1건의 우회로·해설·표기 위반 목록 — 빈 리스트면 통과."""
    out = _notation_rules(probe) + _explanation_rules(probe) + _zero_monomial_rule(probe)
    code = probe.standard_code
    if code == _C05:
        out += _tangent_rules(probe)
    if code in (_C05, _C08):
        out += _value_determines_rule(probe)
    if code == _C06:
        out += _mvt_rules(probe)
    if code == _C08:
        out += _graph_shape_rules(probe) + _graph_shape_round4_rules(probe)
    if code == _C09:
        out += _equation_rules(probe) + _application_rule(probe)
    if code == _C10:
        out += _velocity_rules(probe)
    return out + _round5_rules(probe)


def violations_by_rule(probes: Sequence[ShortcutProbe]) -> dict[str, int]:
    """표본 묶음의 규칙별 위반 문항 수(보고용) — 한 문항이 같은 규칙을 여러 번 어겨도 1로 센다."""
    counts: dict[str, int] = {rule: 0 for rule in RULE_IDS}
    for probe in probes:
        for rule in {v.rule for v in shortcut_violations(probe)}:
            counts[rule] += 1
    return counts
