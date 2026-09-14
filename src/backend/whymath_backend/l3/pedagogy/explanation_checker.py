"""연령별(학년 레지스터) 설명 언어 수준 결함 검출기 — EOS-98 F7 판정 경로.

`l3/pedagogy/analogy_checker.py`(비유 결함 검출기)의 *언어 수준* 짝이다. 개념 설명을 4개
학년 레지스터(`SpeechGradeBand` — 초등/중등/고등/대학, `schema/speech.py` 재사용)로 생성할 때,
그 밴드에 아직 도입되지 않은 구조(construct)를 가리키는 한국어 어휘가 본문에 등장하면
`GenerationFailureCode.F7`("언어 수준 부적합 — 학교급 어휘·문장 수준 불일치")로 판정한다.

────────────────────────────────────────────────────────────────────────────
정직한 커버리지 (overclaim 금지 — analogy_checker/mode_guard 선례)
────────────────────────────────────────────────────────────────────────────
F7이 가리키는 "언어 수준 부적합"은 원칙적으로 **어휘+문장 구조** 두 축이다. 이 검출기가 규칙으로
결정 가능한 것은 **어휘(구조 도입 여부) 축뿐**이다 — 문장 길이·구문 복잡도 같은 *문체* 축은
가독성 분석기 없이 규칙으로 결정 불가능해 `DEFERRED_DEFECT_AXES`로 명시하고 검출 대상에서
제외한다(조용히 통과시키지 않고 커버리지를 코드로 회계 — mode_guard/analogy_checker 동형).

어휘 판정은 **미도입 구조 어휘의 존재**만 본다 — `l4/speech/profiles.py::PROFILES`의
`introduced_constructs`(학년별 도입 구조 집합)를 **함수 인자로 주입**받는다(L3→L4 직접 import는
역방향 의존이라 금지 — `l3/speech.py`·`speech.py::GradeProfile` DI 선례와 동일 규약).

7계층: L3 콘텐츠 검증(순수 규칙). schema만 사용(l4 import 금지 — import-linter).
"""

from __future__ import annotations

import unicodedata
from typing import Final

from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.speech import SpeechGradeBand

# ──────────────────────────────────────────────────────────────────────────
# 구조 어휘 사전 — 한국어 낱말 → 구조 키(`GradeProfile.introduced_constructs`와 동일 어휘)
# ──────────────────────────────────────────────────────────────────────────
# 검출 대상은 학년 간 실제로 갈리는 구조만 고른다(`l4/speech/profiles.py::_ARITHMETIC` = 분수·
# 거듭제곱·절댓값·계승은 전 학년 공통 도입이라 어휘 게이팅 대상에서 제외 — 오탐 방지).
CONSTRUCT_VOCABULARY: Final[dict[str, str]] = {
    "제곱근": "root",
    "근호": "root",
    "사인": "trig",
    "코사인": "trig",
    "탄젠트": "trig",
    "삼각함수": "trig",
    "로그": "log",
    "적분": "integral",
    "부정적분": "integral",
    "정적분": "integral",
    "시그마": "sum",
    "급수": "sum",
    "극한": "limit",
    "수렴": "limit",
    "미분": "derivative",
    "도함수": "derivative",
    "순열": "binom",
    "조합": "binom",
    "이항정리": "binom",
}
"""검출 어휘 → 구조 키. 값은 `l4/speech/profiles.py::PROFILES`의 introduced_constructs 원소와
동일 어휘라야 매칭이 성립한다(단일 진실 원천 — 어휘 추가 시 두 파일을 함께 갱신)."""

DEFERRED_DEFECT_AXES: Final[frozenset[str]] = frozenset({"SENTENCE_COMPLEXITY"})
"""규칙 판정 불가 축 — 문장 길이·구문 복잡도(가독성 분석기 없이 결정 불가). 정직한 공백."""


def _nfkc(text: str) -> str:
    """NFKC 정규화 — 전각 문자 우회를 붕괴시켜 신호 검사가 잡게 한다(analogy_checker 미러)."""
    return unicodedata.normalize("NFKC", text)


def check_explanation_language_level_defect(
    band: SpeechGradeBand,
    text: str,
    *,
    introduced_constructs: frozenset[str],
) -> GenerationFailureCode | None:
    """설명 본문이 `band`에 아직 도입되지 않은 구조 어휘를 쓰면 `F7`, 아니면 `None`.

    `introduced_constructs`는 호출자가 주입한다(`l4/speech/profiles.py::PROFILES[band]
    .introduced_constructs` 선례 — L3가 L4 데이터를 직접 import하지 않는다). 어휘 매칭은
    `CONSTRUCT_VOCABULARY`의 낱말이 본문에 부분 문자열로 등장하는지만 본다(결정론·오탐 최소화
    목적으로 다의어는 어휘 사전에서 제외 — 예: "곱"·"나눔" 같은 일상어는 넣지 않는다).
    """
    normalized = _nfkc(text)
    for term, construct in CONSTRUCT_VOCABULARY.items():
        if construct in introduced_constructs:
            continue  # 이 밴드에 이미 도입된 구조 — 등장해도 결함 아님.
        if term in normalized:
            return GenerationFailureCode.F7
    return None


__all__ = [
    "CONSTRUCT_VOCABULARY",
    "DEFERRED_DEFECT_AXES",
    "check_explanation_language_level_defect",
]
