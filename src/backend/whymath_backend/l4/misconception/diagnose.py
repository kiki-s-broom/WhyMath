"""오개념 진단 — `docs/prompts/misconception_diagnosis.md` "매칭 알고리즘"(L60-70).

v1.1: 규칙 기반 substring 공출현(AND) + **표기 정규화**(NFKC+공백). 학생 풀이에서 각 catalog
항목의 `signals` 부분집합이 얼마나 매칭되는지로 confidence 계산. top-K 후보 반환.

v1.1 정교화(슬 101·`concept_graph_dataset_v1.md` §5.3): 매칭 직전 양변을 `_normalize`로
정규화해 공백·유니코드 표기 변이(`a² + b²`↔`a²+b²`, 위첨자 `²`↔`2`, 전각/반각)에 의한
*거짓음성*을 제거한다. `matched_signals`·confidence는 *원본 신호* 기준이라 UI·디버그 표시 불변.

v1.2 정교화(슬 102): substring AND를 넘어 **정규식 보조 탐지 경로**(`regex_signals`, OR)를
추가한다. 헤드라인 역량은 *거짓 항등식의 수치 대입* 탐지 — 학생이 `(3+4)²=3²+4²`,
`√((-3)²)=-3`, `(2+4)/2=4`처럼 *틀린 항등식에 수를 대입한 흔적*을 잡는다. substring은
기호식(`(a+b)²=a²+b²`)은 잡지만 학생이 *구체 수치로* 계산해버린 흔적은 못 잡던 한계(§5.3·슬
101에서 문서화)를 줄인다. 정규식은 *정규화된 텍스트*에 `re.search`로 검사한다.

수치 정규식은 기호 substring 케이스와 *겹치지 않게*(disjoint) 작성해 `matched_signals` 집합·
기존 substring-only confidence를 보존한다(예: distribution 정규식은 `(3+4)²=3²+4²` *숫자*만
매치, 기호 `(a+b)²=a²+b²`엔 매치되지 않음).

v1.5 정정(MISC-22): 정규식 매치 1건 = substring 신호 **전체**와 동등한 완결 증거로 가산한다 —
`min(1.0, matched/len(signals) + matched_regex_count)`(코드는 통분해 `numerator = matched +
matched_regex*len(signals)`로 구현). v1.2의 옛 식(`min(1.0, (substr+regex)/len(signals))`)은
정규식 매치를 substring 신호 *1개*와만 동등하게 쳐서, 정규식이 disjoint 역참조로 이미
substring AND 전체에 준하는 확정 증거임에도 확신도가 0.5(수치 신호 종류가 흔히 2개)에 갇혔다 —
그 결과 `factor-sign-flip`을 비롯한 4개 v1.2 시연 채널의 "수치 대입 탐지" 헤드라인 역량이 서빙
품질 게이트(0.65)에 전혀 못 미쳐 **한 번도 학생에게 도달하지 못했다**(작동 신호 없는 알고리즘
부착 — `anchor_detection_channel_eval` 실측·MISC-22). substring만으로의 기존 confidence
(1.0/0.5)는 불변 — 이 정정은 *정규식이 매치했을 때만* 영향을 준다.

v1.3 정밀화(슬 109·라이브 FP 교정): **짧은 영숫자 signal의 경계 매칭**. `"0"` 같은 숫자-only
signal과 `"b"` 같은 단일 ASCII 문자 signal은 plain substring으로 두면 *다른 토큰 내부*에
오매칭된다 — 실증된 라이브 결함: `"분모가 10인 분수를 약분했어요"`(완전히 올바른 진술)가
`'0'∈'10'`으로 division-by-zero **풀매칭(1.0) → COUNTEREXAMPLE 개입 발화**. v1.3은 이런
signal을 영숫자 경계 정규식(`(?<![0-9A-Za-z.])sig(?![0-9A-Za-z.])`)으로 매칭해 `10`·`0.5`·
`a₀`(NFKC→`a0`)·`ab` 내부 오매칭을 차단한다. 내용성 있는 signal(한글 형태소 `"곱"`·연산자
`"√"`·복합 토큰)은 기존 substring 유지. confidence 식·분모·반환 계약은 전부 불변 —
*매칭 정밀도만* 올린다(매칭이 줄어드는 방향이라 거짓양성 감소·거짓음성 추가 없음: 정당한
사용처는 비영숫자 이웃[한글 조사·등호·괄호·쉼표]이라 계속 매칭된다).

후속(범위 밖, doc 명시): ① 풀이 단계별 파싱(PRM 활용) ② 처음 틀린 단계 식별 ③ 임베딩
유사도 매칭(text-embedding-3-large 등) ④ LLM-judged 패턴 추출. ③④는 *의미·방향* 차원
한계(방향맹)의 정본 해법이고, *어휘* 차원 거짓양성(짧은 토큰 오매칭)은 v1.3이 직접 줄인다.
잔여: 부분매칭(0.5) 자체의 정밀도 한계(예: `'분모'` 단독 0.5)는 substring 설계의 알려진
트레이드오프 — semantic/judge 계층(슬104~108)이 그 자리다.

v1.6 정정(MISC-24): MISC-22가 5개 정규식 채널(factor-sign-flip 등)의 정규식-단독 매치를
게이트 도달로 정정한 부수효과로, `extremum-value-vs-point-confused`가 `f(x₀)=x₀`인 *우연의
일치* 정답(예: 극대점 x=2에서 극댓값도 2)에도 confidence 1.0을 내 확신 오진단 위험이 있음이
드러났다 — 실은 MISC-22 이전부터 있던 사실(그 정규식이 리터럴 '극댓값'을 포함해 substring이
항상 함께 발화). 이 항목은 오개념 발화 텍스트와 우연의 일치 정답 텍스트가 **글자 그대로
동일**해 정규식으로도 반박(`refuting_regex`)으로도 원리상 구별이 불가능하다.
`ambiguous_regex_signals` 필드(models.py)로 이 항목만 예외적으로 정규식 가산을 0으로 둬
confidence가 항상 substring 신호만으로 결정되게 한다(다른 5개 채널의 MISC-22 정정은 완전히
불변).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from typing import Literal

from whymath_backend.l4.misconception.catalog import CATALOG
from whymath_backend.l4.misconception.models import (
    Misconception,
    MisconceptionMatch,
)

_DEFAULT_TOP_K = 3


# MISC-17: LaTeX 표기 접기 — OCR(`OcrResult.plain_latex`)·MathLive 산출물은 계약상 LaTeX라
# `(a+b)^2`·`a^{2}`·`\left(…\right)` 형태로 온다. NFKC는 `²`→`2`만 펴고 `^`·`{}`·크기 조정
# 표식은 남겨, 인식기의 *정상* 출력이 신호 2개 중 1개(0.5)만 맞아 게이트 ①(0.65)에서 탈락하던
# 실측 결함(PR #1034 Codex P1). `^`와 `{}`를 지우면 `a^{2}`·`a^2`·`a²` 모두 정규형 `a2`로 접힌다.
# 카탈로그 `signals`·`correct_form`에는 이 문자가 0건(2026-09-07 실측)이라 양변 정규화가 일관되고,
# `regex_signals`는 *정규형 텍스트*를 겨냥하므로 패턴 내부의 `[^0-9]` 같은 메타문자와는 무관하다.
# 분수(`\frac`)·곱셈 기호(`\cdot`) 등 다른 LaTeX 명령은 접지 않는다 — 신호가 그 형태를 쓰지 않아
# 필요가 실측되지 않았고, 과도한 접기는 거짓양성 축이 된다(필요 시 실측 후 확장).
_LATEX_FOLD = re.compile(r"\\left|\\right|[\^{}]")


def _normalize(text: str) -> str:
    """매칭용 표기 정규화 — NFKC 유니코드 정규화 + 모든 공백 제거 + LaTeX 표기 접기.

    학생 표기 변이를 흡수한다: `a² + b²`·`a²+b²`·`a 2 + b 2`·`a^2+b^2`·`a^{2}+b^{2}`가 모두
    같은 정규형 `a2+b2`로, 위첨자/아래첨자·전각 숫자도 일반 숫자로(NFKC). 비교에만 쓰며,
    반환되는 신호 문자열은 원본을 유지한다(표시·텔레메트리 일관성).

    참고: NFKC는 위첨자 `²`→`2`로 펴므로 정규식은 *지수 표기를 평문으로* 작성한다
    (예: `(3+4)²=3²+4²`의 정규형은 `(3+4)2=32+42`). 정규식 패턴은 이 정규형을 겨냥한다.
    LaTeX 접기(`_LATEX_FOLD`)로 `(3+4)^2=3^2+4^2`도 같은 정규형이 된다(MISC-17).
    """
    return _LATEX_FOLD.sub("", "".join(unicodedata.normalize("NFKC", text).split()))


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    """정규식 컴파일 캐시 — 카탈로그 패턴은 고정·소수라 무한정 증가하지 않는다."""
    return re.compile(pattern)


def _signal_hit(signal: str, norm_text: str) -> bool:
    """단일 signal 매칭 — v1.3: 짧은 영숫자 signal은 경계 검사, 그 외 substring.

    숫자-only(`"0"`·`"180"`)·단일 ASCII 문자(`"b"`) signal은 다른 토큰 내부에 오매칭된다
    (`'0'∈'10'/'0.5'/'a₀'`·`'b'∈'ab'` — 올바른 진술에 풀매칭→개입 발화한 실증 라이브 결함).
    이런 signal만 영숫자·소수점 경계 정규식으로 매칭하고, 내용성 있는 signal(한글 형태소·
    연산자 기호·복합 토큰)은 기존 substring을 유지한다. 비교는 양변 정규화(`_normalize`) 후.
    """
    norm_sig = _normalize(signal)
    if norm_sig.isdigit() or (len(norm_sig) == 1 and norm_sig.isascii() and norm_sig.isalpha()):
        # 경계: 영숫자·'.'가 이웃이면 다른 수/식별자의 일부로 보고 미매칭. 정당한 사용처
        # (한글 조사·`=`·`≠`·괄호·쉼표 이웃)는 전부 비영숫자라 계속 매칭된다.
        pattern = rf"(?<![0-9A-Za-z.]){re.escape(norm_sig)}(?![0-9A-Za-z.])"
        return _compile(pattern).search(norm_text) is not None
    return norm_sig in norm_text


def is_refuted(misconception: Misconception, text: str) -> bool:
    """이 텍스트가 그 오개념을 **반박**하는가 — 반박 조건의 단일 판정처(MISC-23).

    `_match_one`(substring 경로)과 **의미(임베딩) 경로**가 같이 쓴다. 한쪽에만 걸면 다른 쪽이
    같은 오개념을 되살린다 — `combine_diagnoses`는 substring이 뺀 id를 "semantic-only"로 보고
    아래에 붙이므로, substring에서만 거부하면 semantic 후보가 그대로 노출된다(PR #1039 Codex P2).

    `combine_diagnoses`가 아니라 여기에 두는 이유: 그 함수는 원문 텍스트를 받지 않는 순수
    결합기(두 리스트 재배치·변형 0)이고, 반박은 *텍스트에 대한 판정*이라 축이 다르다.
    """
    norm_text = _normalize(text)
    return any(_compile(rx).search(norm_text) is not None for rx in misconception.refuting_regex)


#: 절(clause) 경계 — 근접 창을 여기서 자른다(MISC-25).
#:
#: `_normalize`가 공백·줄바꿈을 지우므로 **정규화 전에** 잘라야 한다. 이것이 "문장 스코프"를
#: 단독으로 쓸 수 없는 기술적 이유이기도 하다 — 구두점 없는 손글씨 전사에서는 텍스트 전체가
#: 한 문장이 되어 문장 스코프가 텍스트 전체 스코프로 조용히 붕괴한다(교수학 판정 실측:
#: 번호 매김·구두점 없는 시나리오에서 문장 스코프가 64/64를 오억제).
#: 번호 매김(`1)`·`(2)`)을 포함하는 이유가 그것이다 — 손글씨 풀이의 실제 단계 구분자다.
#:
#: 연결어미 `-고`도 경계다(MISC-26에서 추가). 한국어 풀이는 구두점 없이 절을 잇는 일이
#: 흔한데, MISC-25 착지분은 구두점·번호만 봐서 그 형태를 통째로 놓쳤다 — **내가 넣은
#: 축의 실측된 결함**이다:
#:
#:     "부호를 잘못 봤**고** 양변을 x로 나누면 x=2다"   ← 근 손실인데 억제됐다
#:     "앞에서 틀린 부분을 고치**고** 양변을 x로 나누면 x=2다"  ← 같음
#:
#: 둘 다 *다른 것*을 정정하고 이 오개념을 저지른 문장이라 진단이 살아야 한다. MISC-25의
#: 대조군 픽스처가 전부 마침표·번호를 썼기 때문에 이 형태를 한 번도 밟지 않았다.
#:
#: **인용격 `라고`·`다고`는 제외한다** — 그것은 절 경계가 아니라 인용 조사다. 빼지 않으면
#: "친구는 (a+b)²를 a²+b²**라고** 했는데 틀렸어"가 인용 앞뒤로 갈려 억제가 풀린다(남의
#: 오답을 비판하는 문장에 확신 오진단이 나간다). 실측으로 이 예외를 확인했다.
#:
#: `-지만`·`-는데`는 경계로 두지 **않는다**: "A라고 봤**지만** 맞지 않다"의 `맞지 않다`는
#: 실제로 A를 반박하므로 갈라 놓으면 반박을 잃는다. `-고`만 넣은 것은 그 차이 때문이다.
_CLAUSE_BOUNDARY = re.compile(r"[\n.?!;。？！]+|(?:\(\s*\d+\s*\)|\d+\s*\))|(?<![라다])고\s+")

#: 정정 어휘가 신호에서 이만큼 떨어져 있으면 그 신호를 가리키는 말로 보지 않는다(정규형 기준).
#:
#: 앞뒤가 비대칭인 이유: 한국어 정정은 뒤에 붙는 형태("…라는 풀이는 **틀렸다**")가 길고,
#: 앞에 붙는 형태("**틀린** 풀이: …")는 짧다. 후치 전용 창은 전치 라벨을 전부 놓친다
#: (교수학 판정 실측: 후치 전용 스코프가 전치 라벨 66종 중 **0종**만 인지).
#:
#: **12를 고른 근거는 실측된 간격이다.** 교수학 검토가 합성 대조군에서 제안한 초기값은
#: 12/24였는데, 24로 두자 `test_input_is_not_masked_by_gate_or_topk`가 지키던 진짜 오개념
#: ("분모가 0이면 나눌 수 있다고 봤고 x=0은 근이 아니다")이 억제됐다 — 뒤쪽의 `아니다`는
#: *제로근*을 부정하는 말이지 나눗셈 오개념을 부정하는 말이 아닌데 창이 거기까지 닿았다.
#: 그래서 양쪽 거리를 전부 재 봤다(정규형 기준, 신호 끝 → 정정 어휘 시작):
#:
#:   억제돼야 하는 4종  : 5 · 7 · 9 · 9   (최대 9)
#:   억제되면 안 되는 1종: 16              (내용성 신호만 기준으로는 18)
#:
#: 9와 16 사이가 비어 있어 **12는 양쪽에 여유(3·4)를 두고 갈라진다** — 한 테스트에 맞춘
#: 값이 아니라 측정된 간격의 중앙이다. 앞뒤를 같게 둔 이유는 전치 라벨("틀린 풀이: …")이
#: 필요로 하는 거리가 5로 후치보다 짧아 12로 충분하기 때문이다(후치 전용 창이면 전치 라벨을
#: 66종 중 0종만 인지한다 — 교수학 검토 실측).
#:
#: **정직 표기 — 여전히 잠정값이다.** 실제 학생 손글씨 코퍼스가 저장소에 없어 학생 글 기준
#: 최적값은 **판정 불가**다. 위 간격은 5개 사례에서 얻은 것이라 표본이 작다. 실데이터가
#: 생기면 `explicit_correction_gap_eval`로 재측정해 조정한다.
_CORRECTION_LOOKBEHIND = 12
_CORRECTION_LOOKAHEAD = 12

#: 이 축이 쓰는 정정 어휘 — `catalog.EXPLICIT_CORRECTION_MENTION`과 **의도적으로 다르다**.
#:
#: 차이는 딱 하나, 맨어간 `아니`를 빼고 **종결형**(`아니다`·`아니야`·`아냐`·`아닙니다`)만
#: 남긴 것이다. 한국어에서 연결형 `아니라`·`아니므로`·`아닌`은 정정 표지가 아니라 **대조
#: 표지**이고, 대조는 오개념을 *부정*하는 말이 아니라 *주장*하는 가장 흔한 형식이다
#: ("A가 아니라 B다").
#:
#: 이 구별을 안 하면 이 저장소가 이미 한 번 싸운 결함이 되살아난다 — 회귀 테스트
#: `test_negated_zero_root_is_not_a_refutation`이 동결한 문장이 정확히 그것이다:
#:
#:     "x²=2x에서 x=0은 근이 **아니**므로 양변을 x로 나누면 x=2다"
#:
#: 명백한 근 손실 오답인데 `아니`가 있다는 이유로 진단이 꺼지면 진짜 오개념을 놓친다
#: (`_ZERO_ROOT_DENIAL` 주석의 같은 사례 · PR #1039 Codex P2). 교수학 판정도 같은 축을
#: 독립으로 지적했다 — 저장소가 *직접 오개념으로 라벨한* 프로브 2건
#: (`square-root-positivity`·`exponent-zero`)이 `아니라`를 달고 있다.
#:
#: `EXPLICIT_CORRECTION_MENTION` 쪽을 안 고치는 이유: 그것은 5개 정규식 채널의 **텍스트 전체**
#: 전방탐색에 쓰이고 있어 손대면 그 채널들의 계약이 함께 바뀐다. 스코프가 다르면 어휘도
#: 다를 수 있다 — 좁은 스코프가 넓은 어휘를 감당하고, 넓은 스코프는 못 한다.
_CORRECTION_NEAR_SIGNAL = (
    r"(?:틀리|틀렸|틀린|틀려|틀릴|틀림|오답|잘못|오류|아니다|아니야|아냐|아닙니다)"
)


def _clauses(text: str) -> list[str]:
    """원문을 절 단위로 자른다 — 정규화 **전에** 해야 경계가 살아 있다."""
    return [c for c in _CLAUSE_BOUNDARY.split(text) if c and c.strip()]


#: 정정 어구의 **귀속 판정** 3상태 (MISC-28 · Kiki 판정 2026-09-12 · 후보 ⓒ).
#:
#: `"refuted"`  — 정정 어구가 신호 **뒤**에 있다. `"…라는 풀이는 틀렸다"` 형태로, 정정이
#:                가리키는 대상이 방금 말한 그 주장이라는 것이 어순으로 확정된다 → **억제**.
#: `"unclear"`  — 정정 어구가 신호 **앞**에 있다. 여기엔 두 가지가 섞여 있고 **위치로는
#:                구별되지 않는다**(실측):
#:                  · 정당한 반박: `"틀린 풀이: <오개념>"`(라벨 후 인용)
#:                  · 무관한 정정: `"부호를 잘못 옮겨 적었지만 <오개념>"`
#:                → 억제도 진단도 아닌 **판정 보류**. 매칭은 유지하되 재확인을 요구한다.
#: `"none"`     — 정정 어구 없음 → 평소대로 진단.
#:
#: **왜 방향이 판별자인가 — 그리고 왜 그것만으로는 부족한가**: 두 축을 전수로 쟀더니 창을
#: 한쪽으로 접는 것만으로는 실패가 *옮겨질 뿐*이었다(MISC-28 실측, 카탈로그 66종):
#:
#:     현행(양방향 억제)  : 오억제 66/66(100%) · 선행정정 사각  0/66(  0%)
#:     뒤돌아보기 끔       : 오억제  2/66(  3%) · 선행정정 사각 66/66(100%)
#:
#: 즉 앞쪽 정정을 "억제"로 읽으면 무관한 정정까지 삼키고, "무시"로 읽으면 정당한 반박에
#: 확신 진단이 나간다. 어느 쪽도 **틀린 확신**을 만든다. 그래서 세 번째 상태를 둔다 —
#: 귀속이 불명할 때는 판정하지 않고 **묻는다**.
#:
#: Kiki 판정 원문 취지: "목표가 정답률 최대화가 아니라 학생에게 잘못된 확신을 주는 오류를
#: 최소화하는 것이다. 귀속이 불명확한데 바로 '네가 틀렸다'고 판정하는 것보다, 판정을
#: 보류하고 한 번 확인하는 상태를 두는 편이 교육적으로 안전하다." 이는
#: `models.py::refuting_regex` docstring의 기존 선언과 같은 축이다.
CorrectionVerdict = Literal["refuted", "unclear", "none"]


def classify_correction_attribution(misconception: Misconception, text: str) -> CorrectionVerdict:
    """정정 어구가 **이 오개념을 가리키는가**를 3상태로 판정한다 (MISC-28).

    `has_explicit_correction_near_signals`의 bool 판정을 대체하지 않고 **감싼다** — 그
    함수는 `"refuted"`만을 True로 보는 종전 계약을 유지해 기존 호출부·테스트가 그대로
    선다. 새 상태(`"unclear"`)를 소비하는 것은 `_match_one`이다.

    한계(정직 표기): 이 판정은 **어순**만 본다. 같은 방향 안의 귀속(무엇을 정정하는가)은
    여전히 미해결이며, 그것이 `"unclear"`를 억제가 아닌 *보류*로 두는 이유다 — 모르는
    것을 아는 척하지 않는다.
    """
    # `signals`가 비면 아래 루프가 아무 것도 내지 않아 자연히 `"none"`이다 — 조기 반환 가드를
    # 두지 **않는다**. 뮤테이션에서 그 가드를 지워도 전건 초록이었다(= 동작이 동일한 죽은 절).
    # 가드처럼 생겼는데 아무것도 막지 않는 코드는 없는 것보다 나쁘다: 읽는 사람이 그것을
    # 검증된 보호로 계상한다(CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지").
    correction = _compile(_CORRECTION_NEAR_SIGNAL)
    verdict: CorrectionVerdict = "none"
    for clause in _clauses(text):
        norm_clause = _normalize(clause)
        if not norm_clause:
            continue
        hits = [s for s in misconception.signals if _anchorable(s, norm_clause)]
        for signal in hits:
            span = _signal_span(signal, norm_clause)
            if span is None:  # pragma: no cover — _signal_hit가 True면 위치가 있다
                continue
            start, end = span
            # 뒤쪽(lookahead) 정정이 하나라도 있으면 확정 반박 — 즉시 확정한다.
            if correction.search(norm_clause[end : end + _CORRECTION_LOOKAHEAD]):
                return "refuted"
            # 앞쪽(lookbehind) 정정은 귀속 불명 — 뒤쪽 확정이 없을 때만 남는다.
            if correction.search(norm_clause[max(0, start - _CORRECTION_LOOKBEHIND) : start]):
                verdict = "unclear"
    return verdict


def has_explicit_correction_near_signals(misconception: Misconception, text: str) -> bool:
    """학생이 이 오개념을 **명시적으로 부정**하고 있는가 — 절 경계 안 근접 판정(MISC-25).

    `signals`의 공출현(AND)은 오개념을 *저지른* 풀이와 그것을 *인용해 부정한* 풀이를 구별하지
    못한다. 실측: 진단 카탈로그의 **측정 가능 66종 전부**가 "…라는 풀이는 틀렸다"를 붙여도
    서빙 게이트를 통과했다(`harness/explicit_correction_gap_eval.py`). 항목별 결함이 아니라
    구조적 공백이라 항목마다 `refuting_regex`를 다는 방식으로는 못 메운다(66곳 중복).

    **왜 텍스트 전체 스코프가 아닌가** — 그것이 이 함수 설계의 핵심이다. "정정 어휘가 어디든
    있으면 진단하지 않는다"로 하면 다음 풀이에서 진단이 통째로 사라진다:

        1) 처음에 -3을 +3으로 잘못 옮겨 적어서 고쳤다.
        2) x²=2x 이므로 양변을 x로 나누면 x=2.

    학생은 1단계에서 전사 실수를 *스스로 잡아냈고*(메타인지가 작동한 순간) 2단계에서 근 손실을
    저질렀다. "잘못" 한 단어 때문에 67종 전부가 꺼지면 **자기 오류를 언어화한 학생일수록 진단을
    덜 받는** 역선택이 된다 — 이 프로젝트가 기르려는 바로 그 행동에 침묵으로 보상하는 꼴이다.
    게다가 미검출은 아무도 소리내지 않는다(`_ZERO_ROOT_DENIAL`이 같은 이유로 이미 근접 창을
    택했다 — 이 저장소는 "반박 축이 너무 넓을 때 좁힌다"를 한 번 판정한 적이 있다).
    교수학 판정 실측: 전체 스코프는 위 유형 시나리오에서 정탐 66/66을 전부 침묵시켰고,
    절 경계 근접 창은 최악 3/66만 잃으면서 오진단 제거 이득의 88%를 지켰다.

    **왜 `refuting_regex`(거부)와 별도 함수인가**: `refuting_regex`는 *그 오개념의 정의에
    비추어 반박이 확정되는* 조건이다(`ZERO_ROOT_MENTION` — 0을 적었으면 근을 잃지 않았다는
    수학적 함의). 이 축은 확정 반박이 아니라 **귀속 불명**이라 성질이 다르다. 같은 이름으로
    묶으면 그 차이가 사라진다.

    **한계(정직 표기)**:
      · 정정 어휘 없는 인용("친구는 (a+b)²=a²+b²이라고 **했어**")은 원리상 못 잡는다 —
        스코프가 아니라 귀속(attribution) 문제이고 어휘·거리로는 미해결이다.
      · `EXPLICIT_CORRECTION_MENTION`은 `아닌가`·`맞지 않다`·`성립하지 않는다`·`착각했다`
        등을 아직 못 잡는다(실측). 넓히는 것은 이 스코프 축소가 **선행 조건**이다 —
        전체 스코프에서 패턴을 넓히면 오억제가 함께 커진다(MISC-26 등재).
      · 원격 후치 정정("{오개념}. 이렇게 쓰면 오답이다")은 절이 갈려 못 잡는다. 창을 다음 절
        머리까지 열면 회복되지만 "뒤 절의 무관한 정정"이 같은 규모로 오억제된다 —
        정확히 등가 교환이라 유지(=진단) 쪽으로 기울였다(우선순위: 미검출도 손해다).
    """
    # MISC-28 — 판정 구현은 `classify_correction_attribution` **하나**다. 이 함수는 그 3상태를
    # bool로 접은 얇은 뷰이며, 종전 계약(정정 어구가 신호 근접 창 안에 있는가 — 앞·뒤 무관)을
    # 그대로 보존한다. 카탈로그 전수 프로브 938건에서 두 구현의 판정이 100% 일치함을 확인한 뒤
    # 합쳤다(신호 문자열 자체에 정정 어휘가 든 항목은 0건이라 창 모양 차이도 무영향).
    #
    # **왜 합쳤나**: 같은 절 경계 루프를 두 벌 두면 한쪽만 뮤테이션에서 검사된다 — 실제로
    # 이 함수 쪽 루프의 경계 절을 지워도 전건 초록이었다(M7 생존). 사본은 검증되지 않은 채
    # "검증된 구현"의 일부로 계상된다.
    #
    # **주의**: `_match_one`은 더 이상 이 함수를 부르지 않는다(3상태를 직접 소비한다). 여기서
    # True는 "억제하라"가 아니라 "정정 어구가 근처에 있다"는 *탐지* 신호다 — 억제 여부는
    # 방향에 달렸다(뒤=억제·앞=보류).
    return classify_correction_attribution(misconception, text) != "none"


def _is_weak_signal(signal: str) -> bool:
    """숫자-only(`"0"`·`"180"`)·단일 ASCII 문자 signal인가 — **창을 열 자격이 없는** 신호.

    이런 신호는 v1.3이 경계 검사를 붙여 오매칭을 줄였지만, 여전히 *다른 주장 안*에서
    정당하게 등장한다. `"0"`은 정의역 조건(`x=0은 근이 아니다`·`분모는 0이 될 수 없다`)에
    나오고, 그 조건문에 붙은 부정 어미가 **엉뚱한 오개념을 반박한 것으로 읽힌다**:

        "분모가 0이면 나눌 수 있다고 봤고 x=0은 근이 아니다"

    앞 절이 나눗셈 오개념이고 뒤 절의 `아니다`는 *제로근*을 부정하는 말인데, 뒤 절의 `0`이
    창을 열어 `division-by-zero`를 삼켰다(실측 — `test_input_is_not_masked_by_gate_or_topk`).
    그래서 창은 **내용성 있는 신호**(한글 형태소·연산자·복합 토큰)만 연다.

    비용은 0이다 — 카탈로그에 신호가 전부 약한 항목은 없다(실측: 약한 신호를 가진 3종
    `division-by-zero`·`exponent-zero`·`angle-sum-non-triangle` 모두 내용성 신호를 함께
    가진다). 즉 어떤 항목도 이 축을 통째로 잃지 않는다.
    """
    norm_sig = _normalize(signal)
    return norm_sig.isdigit() or (len(norm_sig) == 1 and norm_sig.isascii() and norm_sig.isalpha())


def _anchorable(signal: str, norm_clause: str) -> bool:
    """이 절에서 이 signal이 매치되고, 창을 열 자격(내용성)이 있는가."""
    return not _is_weak_signal(signal) and _signal_hit(signal, norm_clause)


def _signal_span(signal: str, norm_clause: str) -> tuple[int, int] | None:
    """정규형 절에서 signal의 위치.

    `_anchorable`을 통과한 신호만 들어오므로 약한 신호(숫자·단일 영문자)의 경계 정규식
    갈래는 여기에 도달하지 않는다 — 그래서 substring `find` 하나로 충분하다. 갈래를 남겨
    두면 도달 불가 분기가 되어 "검사됐다"는 착시를 준다.
    """
    norm_sig = _normalize(signal)
    if not norm_sig:
        return None
    index = norm_clause.find(norm_sig)
    return (index, index + len(norm_sig)) if index >= 0 else None


def reject_refuted(candidates: Sequence[MisconceptionMatch], text: str) -> list[MisconceptionMatch]:
    """후보 목록에서 반박된 것을 제거 — 경로와 무관한 **공통 출구**용.

    substring·의미 어느 경로로 들어왔든 여기를 지나면 반박된 후보는 남지 않는다.
    """
    return [m for m in candidates if not is_refuted(m.misconception, text)]


def _match_one(misconception: Misconception, text: str) -> MisconceptionMatch | None:
    """단일 misconception 매칭 — substring 부분집합(정규형 비교) + 정규식 보조 경로(OR).

    confidence = min(1.0, substr매치/len(signals) + regex매치). 둘 다 0이면 None.
    v1.3: 개별 signal 매칭은 `_signal_hit`(짧은 영숫자 signal 경계 검사) 경유.

    MISC-22 정정(v1.5) — 정규식 매치 1건은 *전체 신호 AND*와 동등한 완결 증거로 가산한다
    (분자에 `len(signals)`를 더해 단독으로도 상한 1.0을 채운다). 카탈로그의 모든 `regex_signals`는
    명명그룹 역참조로 좌·우변이 글자 그대로 일치할 때만 매치하도록 설계돼 정답·기호식과
    *disjoint*가 이미 항목별로 증명돼 있다(각 항목 주석 참조) — 즉 규격상 "부분 신호"가 아니라
    substring AND 전체에 준하는 확정적 단서다. v1.2의 옛 가산식(정규식 매치를 substring 신호 1개와
    동등하게 취급)은 이 disjoint 보증을 과소평가해 `factor-sign-flip`(수치 입력에서 상징적
    substring이 구조적으로 0건)을 confidence 0.5에 가둬 서빙 품질 게이트(0.65)에 영원히 못 미치게
    했다(작동 신호 없는 알고리즘 부착) — 같은 결함이 `distribution-over-power`·
    `square-root-positivity`·`fraction-cancellation`·`log-distribution`의 수치 대입 탐지에도
    동일하게 있었다(실측: 4종 전부 conf 0.5). `extremum-value-vs-point-confused`는 회귀 없음 —
    그 정규식 패턴 자체가 substring 신호 `극댓값`을 리터럴로 포함해 regex 매치 시 substring도 항상
    함께 매치하므로 옛 식으로도 이미 conf 1.0이었다(실측 확인).

    MISC-23: `refuting_regex`가 하나라도 매치되면 **신호를 세기 전에** None이다. 공출현 AND는
    오개념을 *저지른* 풀이와 그것을 *설명한* 정답을 구별하지 못하므로, 반박 축이 없으면 정답에
    확신 오진단이 나간다(실측: conf 1.0으로 품질 게이트 통과).

    MISC-24: `ambiguous_regex_signals=True`인 항목은 정규식 매치가 `matched_regex_signals`
    (텔레메트리)에는 담기되 confidence 가산에는 기여하지 않는다(numerator에서 배제) —
    `extremum-value-vs-point-confused`처럼 오개념 발화와 우연의 일치 정답이 텍스트상 완전히
    동일해(`refuting_regex`로 반박할 대상 자체가 없음) 정규식 매치 자체가 확정 증거가 될 수
    없는 항목을 위한 것이다(models.py 필드 docstring 근거).
    """
    norm_text = _normalize(text)
    # 반박 조건 먼저(MISC-23) — 양성 단편을 세기 *전에* 판정한다. 나중에 감점하는 형태였다면
    # "얼마나 깎을 것인가"라는 답 없는 눈금 문제가 생기고, 깎인 후보가 하류에 약한 증거로 남는다.
    if is_refuted(misconception, text):
        return None
    # MISC-25 — 학생이 이 오개념을 *명시적으로 부정*하는 절에서 신호가 나왔다면 귀속이 성립하지
    # 않는다. `is_refuted`와 나란히(둘 다 세기 전에) 두는 이유는 같다 — 나중에 감점하면 "얼마나
    # 깎을 것인가"라는 답 없는 눈금 문제가 생기고, 깎인 후보가 하류에 약한 증거로 남는다.
    #
    # MISC-28(Kiki 판정 · 후보 ⓒ) — 그 판정을 **3상태**로 받는다. `"refuted"`(정정이 신호 뒤)만
    # 종전처럼 None이고, `"unclear"`(정정이 신호 앞)는 억제하지 않는다. 앞쪽 정정에는 정당한
    # 반박과 무관한 정정이 **위치로 구별되지 않게** 섞여 있어(실측 교환표: 억제하면 오억제
    # 66/66, 무시하면 선행정정 사각 66/66) 어느 쪽으로 단정해도 *틀린 확신*이 나간다. 그래서
    # 매칭은 살리되 플래그를 세워 하류가 **확인 질문**으로 내리게 한다.
    verdict = classify_correction_attribution(misconception, text)
    if verdict == "refuted":
        return None
    matched = tuple(s for s in misconception.signals if _signal_hit(s, norm_text))
    matched_regex = tuple(
        rs for rs in misconception.regex_signals if _compile(rs).search(norm_text) is not None
    )
    if not matched and not matched_regex:
        return None
    # MISC-22(v1.5): 정규식 매치 1건 = substring 신호 전체(len(signals))와 동등한 완결 증거로
    # 가산한다 — disjoint 역참조 정규식은 substring AND 전체에 준하는 확정적 단서이기 때문이다
    # (위 docstring 근거). 분모는 substring signals 개수(>=1, 카탈로그 불변식) 유지.
    # MISC-24: 단, `ambiguous_regex_signals`가 선 항목은 정규식 가산을 0으로 둔다 — 매치된
    # 정규식이 확정 증거가 아니라 원리상 반박 불가능한 모호 신호이기 때문이다(models.py 근거).
    if misconception.ambiguous_regex_signals:
        numerator = len(matched)
    else:
        numerator = len(matched) + len(matched_regex) * len(misconception.signals)
    if numerator == 0:
        # matched_regex만 있고(ambiguous 항목이라 가산 0) matched는 비었다면 세울 증거가 없다.
        return None
    confidence = min(1.0, numerator / len(misconception.signals))
    return MisconceptionMatch(
        misconception=misconception,
        confidence=confidence,
        matched_signals=matched,
        matched_regex_signals=matched_regex,
        # MISC-28 — confidence 눈금은 건드리지 않는다(`refuting_regex` docstring의 "왜 감점이
        # 아니라 거부인가"와 충돌 회피). 귀속 불명은 *신뢰도가 낮은 것*이 아니라 *다른 축*이다.
        attribution_unclear=verdict == "unclear",
    )


def correct_form_present(misconception: Misconception, text: str) -> bool:
    """학생 풀이에 오개념의 *정정 형태*(`correct_form`)가 나타나는지 — 정밀 반박 신호.

    `signals`와 *동일한* `_normalize`(NFKC+공백제거)로 양변을 정규화해 `correct_form`의 정규형이
    텍스트 정규형의 *부분문자열*인지 검사한다(표기 변이 흡수·신호 경로와 일관). `signals`의
    공출현(AND)·짧은 영숫자 경계 로직과 달리, 정정은 *식별 형태 1개*의 출현만으로 충분한 강한
    신호라 단일 substring 포함만 본다. `correct_form`이 None이거나 정규형이 빈 문자열(전체 매칭
    방지)이면 False(탐지 비활성·기존 약한 반박 동작 불변).

    이 함수가 True면 호출자(coach)는 그 오개념을 *강하게*(−1·강한 가중) 반박한다 — 도구 검증된
    풀이에 정정 형태가 실재하면 "학생이 그 오개념을 가졌다"는 예측과 *정밀하게* 모순되기 때문이다.
    """
    cf = misconception.correct_form
    if not cf:
        return False
    norm_cf = _normalize(cf)
    if not norm_cf:
        return False
    return norm_cf in _normalize(text)


def diagnose(student_solution: str, *, top_k: int = _DEFAULT_TOP_K) -> list[MisconceptionMatch]:
    """학생 풀이에서 오개념 후보 top-K를 confidence 내림차순으로 반환한다.

    매칭 0이면 빈 리스트. 동률은 catalog 순서(=doc 명시 순서) 안정 유지.
    """
    matches: list[MisconceptionMatch] = []
    for m in CATALOG:
        result = _match_one(m, student_solution)
        if result is not None:
            matches.append(result)
    matches.sort(key=lambda x: x.confidence, reverse=True)
    return matches[:top_k]
