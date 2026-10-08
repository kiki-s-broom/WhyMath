"""비유·예시 결함 검출기 — 정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §6.3.

`l4/pedagogy/mode_guard.py`(금지모드 검출기·reason_code | None)의 *생성측 콘텐츠* 짝이다.
비유·실생활 예시 생성 산출(DRAFT)이 04g §6.3의 4대 결함 축을 위반하는지 **규칙 기반**으로
검사한다 — 위반 결함 코드 튜플을 반환하면 검수 게이트(review)가 그 산출을 REJECT한다
(fail-closed). LLM·IO 0의 순수 함수라 하네스(`harness/analogy_fidelity_eval.py`)가 같은 함수를
결함주입 시험지로 상시 측정한다(검출력의 기계 증거·강등전).

────────────────────────────────────────────────────────────────────────────
정직한 커버리지 (overclaim 금지 — mode_guard RULE_DETECTABLE/DEFERRED 선례)
────────────────────────────────────────────────────────────────────────────
04g §6.3의 결함 축 ①오개념 유발 비유는 *의미론* 판정(예: "함수=자판기"가 일대일대응 오개념을
심는가)이라 규칙 전수 검출이 불가능하다. 규칙이 잡을 수 있는 **양성 프록시 2축**만 검출기를
붙이고, 의미론 축은 DEFERRED로 명시한다(조용히 통과시키지 않고 커버리지를 코드로 회계):

  - **MISSING_BREAK_CLAUSE** (①-a 구조 프록시) — 04g §6.3은 생성 비유에 "비유가 어디서
    깨지는지" 동봉을 요구한다. 한계·차이 명시 어휘가 전무한 비유는 그 자체로 오개념 유발
    *위험* 산출이다(구조 검사라 결정 가능).
  - **OVERIDENTIFICATION** (①-b 문면 프록시) — "완전히 같다·똑같다·그 자체다" 류 동일시
    단정은 비유 매핑을 과잉 주장해 오개념을 심는 문면 신호다(likeness("~처럼") ≠ identity).
  - **DEFINITION_USURPATION** (②) — 비유가 정의를 참칭("이것이 정의다"). 렌더측
    AnalogyAdapter의 reflection 세그먼트("비유는 정의를 대신하지 않는다")와 이중 방어.
  - **ANSWER_LEAK** (③) — 예시 본문에 정답 문자열 노출(`l3/pedagogy/review.py`의
    answer_leak 게이트와 동형 규칙 — 예시 grain 전용·비유는 answer가 없어 비적용).
  - **GAMIFIED** (④) — 게임화 메커닉 어휘(레벨업·퀘스트·경험치 등). CLAUDE.md 절대 금기
    "무자비한 게임화" + 04g §8-② 게임형 전 축 거부의 기계 시행. **수학 소재로서의 게임
    언급(예: "주사위 게임에서 두 눈의 합")은 정당한 실생활 예시라 잡지 않는다** — 어휘를
    게임화 *메커닉*(보상·레벨·랭킹)에 한정해 오탐을 막는다(변별 설계·eval clean 셀이 검증).

  - **DEFERRED**: `SEMANTIC_MISCONCEPTION` — 형식은 갖췄으나 의미상 오개념을 심는 비유
    (규칙 판정 불가·후속 샘플드 Claude audit/인간 폴백 소관). 이 축의 무검출은 "clean 선언"이
    아니다(mode_guard DEFERRED_MODES 동형 회계).

7계층: L3 콘텐츠 검증(순수 규칙). schema·표준 라이브러리만 사용(l4 import 금지 — import-linter).
"""

from __future__ import annotations

import unicodedata
from typing import Final

# ──────────────────────────────────────────────────────────────────────────
# 결함 코드 폐쇄 어휘 — reason_code 계약(동결 테스트 대상·자유 문자열 금지)
# ──────────────────────────────────────────────────────────────────────────
ANALOGY_DEFECT_CODES: Final[frozenset[str]] = frozenset(
    {
        "MISSING_BREAK_CLAUSE",  # ①-a 한계(깨짐) 명시 부재 — 오개념 유발 위험(구조 프록시)
        "OVERIDENTIFICATION",  # ①-b 동일시 단정 — 오개념 유발 위험(문면 프록시)
        "DEFINITION_USURPATION",  # ② 정의 대체(비유가 정의를 참칭)
        "ANSWER_LEAK",  # ③ 정답 유출(예시 본문에 답 노출)
        "GAMIFIED",  # ④ 게임형 산출(게임화 메커닉 어휘)
    }
)
"""검출기가 낼 수 있는 결함 코드 전량 — 폐쇄 어휘(이 밖의 코드는 결함·동결 테스트가 봉인)."""

RULE_DETECTABLE_DEFECT_AXES: Final[frozenset[str]] = ANALOGY_DEFECT_CODES
"""규칙 검출 가능 축(=코드 전량). mode_guard RULE_DETECTABLE_MODES 동형 회계."""

DEFERRED_DEFECT_AXES: Final[frozenset[str]] = frozenset({"SEMANTIC_MISCONCEPTION"})
"""규칙 판정 불가 축 — 의미론적 오개념 유발(후속 샘플드 audit·인간 폴백). 정직한 공백."""


def _nfkc(text: str) -> str:
    """NFKC 정규화 — 전각 문자 우회를 붕괴시켜 신호 검사가 잡게 한다(mode_guard `_nfkc` 미러)."""
    return unicodedata.normalize("NFKC", text)


# ──────────────────────────────────────────────────────────────────────────
# 신호 어휘 — 각 축의 양성/면책 신호(보수적·오탐 최소화)
# ──────────────────────────────────────────────────────────────────────────
# 한계(깨짐) 명시 신호 — 하나라도 있으면 "비유가 어디서 깨지는지"를 밝힌 것으로 본다.
# 넓게 잡는다(존재 검사라 넓을수록 오탐(위반 아닌데 위반 판정)이 *줄어든다* — 보수 방향).
BREAK_CLAUSE_SIGNALS: Final[tuple[str, ...]] = (
    "깨진",
    "깨지",
    "다른 점",
    "다르",
    "차이",
    "한계",
    "성립하지 않",
    "맞지 않",
    "어긋",
    "주의",
    "전부는 아니",
    "만능이 아니",
    "정의가 아니",
    "정의는 아니",
    "정의를 대신하지",
    "정확한 정의",
    "엄밀한 정의",
)

# 동일시 단정 신호 — 비유 대상과 개념의 *완전 동일성*을 주장하는 문면(likeness 아님).
# "~처럼"·"~같이"·"비슷"은 정당한 비유 서법이라 넣지 않는다(오탐 방지). **조사(와/과) 결합형만**
# 잡는다 — 부사형 "똑같이 나누기"(등분·수학적 상등)·"모양과 크기가 완전히 같다"(합동 서술)는
# 개념 내부의 정당한 수학 서술이라 잡으면 안 된다(코퍼스 846행 실측으로 오탐 계급 확인·조임).
IDENTITY_ASSERTION_SIGNALS: Final[tuple[str, ...]] = (
    "와 똑같",  # "[비유물]와 똑같다" — 동일시 단정
    "과 똑같",
    "와 완전히 같",
    "과 완전히 같",
    "와 정확히 같",
    "과 정확히 같",
    "그 자체",
    "다름없",
)

# 정의 참칭 신호 — 비유 문면이 "정의"를 단정 서술하는 형태. 함수 정의역의 정당한 수학 서술
# "~에서만 정의된다"를 잡지 않도록 **연결형("라고/로 정의된다")만** 잡는다(코퍼스 실측 조임).
DEFINITION_ASSERTION_SIGNALS: Final[tuple[str, ...]] = (
    "라고 정의",
    "이라고 정의",
    "로 정의된다",
    "으로 정의된다",
    "정의하면",
    "이것이 정의",
    "가 곧 정의",
    "정의는 바로",
)

# 정의 면책(디스클레이머) 신호 — "정의가 아니다"를 밝힌 문면은 참칭이 아니다(오탐 방지).
DEFINITION_DISCLAIMER_SIGNALS: Final[tuple[str, ...]] = (
    "정의가 아니",
    "정의는 아니",
    "정의를 대신하지",
    "정확한 정의",
    "엄밀한 정의",
    "정의라고 할 수는 없",
)

# 게임화 메커닉 어휘 — 폐쇄 어휘(frozenset·동결 테스트). *메커닉*(보상·레벨·랭킹)에 한정한다:
# 맨 "게임"·"점수"·"포인트"는 수학 소재(주사위 게임 확률·시험 점수 평균·퍼센트 포인트)로 정당하게
# 등장하므로 넣지 않는다 — 넣으면 실생활 예시 축이 통째로 오탐된다(변별 설계).
GAMIFICATION_VOCAB: Final[frozenset[str]] = frozenset(
    {
        "게임형",
        "게임화",
        "레벨업",
        "레벨 업",
        "퀘스트",
        "랭킹",
        "콤보",
        "스테이지",
        "경험치",
        "뱃지",
        "아이템",
        "포인트 적립",
        "미션 클리어",
        "보상을 획득",
        "출석 보상",
    }
)


# ──────────────────────────────────────────────────────────────────────────
# 축별 검출기 (순수·결정론 — True=위반)
# ──────────────────────────────────────────────────────────────────────────
def _detect_missing_break_clause(text: str) -> bool:
    """①-a 한계 명시 부재 — 깨짐·차이·한계 신호가 전무하면 True(오개념 유발 위험 구조)."""
    return not any(sig in text for sig in BREAK_CLAUSE_SIGNALS)


def _detect_overidentification(text: str) -> bool:
    """①-b 동일시 단정 — 완전 동일성 주장 문면이 있으면 True."""
    return any(sig in text for sig in IDENTITY_ASSERTION_SIGNALS)


def _detect_definition_usurpation(text: str) -> bool:
    """② 정의 참칭 — 정의 단정 신호가 있고 면책(정의가 아니다) 신호가 없으면 True."""
    has_assertion = any(sig in text for sig in DEFINITION_ASSERTION_SIGNALS)
    if not has_assertion:
        return False
    return not any(sig in text for sig in DEFINITION_DISCLAIMER_SIGNALS)


def _detect_gamified(text: str) -> bool:
    """④ 게임형 — 게임화 메커닉 어휘가 있으면 True(수학 소재 게임 언급은 어휘 밖·통과)."""
    return any(word in text for word in GAMIFICATION_VOCAB)


def _detect_answer_leak(body: str, answer: str | None) -> bool:
    """③ 정답 유출 — 정답 문자열이 본문에 그대로 노출되면 True(review.py answer_leak 동형)."""
    if answer is None:
        return False
    stripped = str(answer).strip()
    return bool(stripped) and stripped in body


# ──────────────────────────────────────────────────────────────────────────
# 공개 API — grain별 결함 검사(검출 코드 튜플·결정론 순서)
# ──────────────────────────────────────────────────────────────────────────
def check_analogy_defects(text: str) -> tuple[str, ...]:
    """개념 비유 텍스트의 규칙 검출 결함 코드 튜플 — 무결함이면 빈 튜플(순서 결정론).

    검사 축(비유 grain): MISSING_BREAK_CLAUSE → OVERIDENTIFICATION → DEFINITION_USURPATION →
    GAMIFIED. ANSWER_LEAK은 비유에 answer 개념이 없어 비적용이다(예시 grain 전용).
    빈 튜플은 "규칙으로는 결함을 못 찾음"이지 "의미론까지 clean"이 아니다(DEFERRED 축은 이
    함수가 판정하지 않는다 — 모듈 docstring 회계 참조).
    """
    normalized = _nfkc(text)
    defects: list[str] = []
    if _detect_missing_break_clause(normalized):
        defects.append("MISSING_BREAK_CLAUSE")
    if _detect_overidentification(normalized):
        defects.append("OVERIDENTIFICATION")
    if _detect_definition_usurpation(normalized):
        defects.append("DEFINITION_USURPATION")
    if _detect_gamified(normalized):
        defects.append("GAMIFIED")
    return tuple(defects)


def check_example_defects(body: str, answer: str | None = None) -> tuple[str, ...]:
    """실생활 예시 본문의 규칙 검출 결함 코드 튜플 — 무결함이면 빈 튜플(순서 결정론).

    검사 축(예시 grain): ANSWER_LEAK → GAMIFIED. 비유 전용 축(한계 명시·동일시·정의 참칭)은
    예시에 요구하지 않는다 — 예시는 구조 매핑 주장이 아니라 서술이라 그 축이 성립하지 않는다
    (요구하면 정상 예시가 전량 오탐된다).
    """
    normalized = _nfkc(body)
    defects: list[str] = []
    if _detect_answer_leak(normalized, answer):
        defects.append("ANSWER_LEAK")
    if _detect_gamified(normalized):
        defects.append("GAMIFIED")
    return tuple(defects)


__all__ = [
    "ANALOGY_DEFECT_CODES",
    "RULE_DETECTABLE_DEFECT_AXES",
    "DEFERRED_DEFECT_AXES",
    "BREAK_CLAUSE_SIGNALS",
    "IDENTITY_ASSERTION_SIGNALS",
    "DEFINITION_ASSERTION_SIGNALS",
    "DEFINITION_DISCLAIMER_SIGNALS",
    "GAMIFICATION_VOCAB",
    "check_analogy_defects",
    "check_example_defects",
]
