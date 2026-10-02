"""L6 수능 모드 *출제 범위* 정의 — 게이트(파이썬)와 SQL 사전필터가 함께 쓰는 단일 정본 (EOS-31).

왜 이 모듈이 있나: 수능 적격 게이트(`gating.py`)의 ③ 신호는 기출 유형·시그니처 패턴·persona_fit
셋이고, 그중 persona_fit은 **난이도 구간 하나만의 함수**다(`l1/problem_bank/persona_fit_rules.py`
`_BAND_BASE_FIT`). 페르소나 A(일반고 고3)는 난이도 라벨이 있는 모든 구간에서 0.70 이상이라
"난이도 라벨이 있는 승인 문항은 전부 수능 적격"이었다 — 초·중 성취기준 전용 문항까지(2026-10-01
실 PG 실측: 승인 2,480건 전부 적격·그중 888건이 초·중 전용). 게이트가 문항이 **어느 학년·어느
범위의 내용인지**를 한 번도 보지 않았기 때문이다.

판정 단위는 선택과목 틀이 아니라 **학년도별 출제 범위**다(EOS-25 독립 비판 놓친 것 2):
  - 2027학년도 수능 — 2015 개정 수학Ⅰ·Ⅱ + 선택(확률과 통계·미적분·기하).
  - 2028학년도 수능 — 2022 개정 대수·미적분Ⅰ·확률과 통계(통합형·선택 없음).
이 저장소의 승인 코퍼스는 전량 `2022_REVISION`이므로 목표 학년도는 2028이다. 2027 규칙은 2015
개정 성취기준 코드가 적재된 뒤에 같은 레지스트리에 한 줄 추가한다(아래 `SUNEUNG_SCOPES`) —
지금 코퍼스에는 그 코드가 0건이라 규칙을 만들어도 검증할 입력이 없다(날조 방지).

**성취기준 코드 접두어로 판정하는 이유**: `Problem.subject`는 코퍼스 전량이 "공통"이고 교과 축
(E1-02)은 2027 이월이라 거기에 기댈 수 없다. 반면 성취기준 고시 코드는 사실정보이고 접두어가
학교급·과목을 가른다 — `[9수…]` 중학교, `[10공수…]` 공통수학, `[12대수…]`·`[12미적Ⅰ…]`·`[12확통…]`
선택 이수 과목 (`concept_standard_link`로 L1이 문항에 이미 잇는다). 코드는
`atom_node.standard_codes`(원자 축)가 정본이며 문항에는 비영속 필드 `achievement_standard_codes`로
주입된다(L5가 조인).

**세 값 판정(모른다 ≠ 아니다)**: 코드가 있고 범위 안 접두어를 하나라도 가지면 `IN_SCOPE`, 코드가
있는데 범위 안 접두어가 없으면 `OUT_OF_SCOPE`, 코드가 아예 없으면 `UNKNOWN`이다. 게이트는
`IN_SCOPE`만 통과시킨다 — 범위를 모르는 문항을 "수능 적격"이라고 말하지 않는다(fail-closed). 세
값을 둔 것은 사후 관측이 "범위 밖이라 거름"과 "범위를 몰라 거름"을 같은 글자로 읽지 않게 하기
위해서다.

**"하나라도"인 이유**: 한 문항이 여러 성취기준을 잇는다(예 `[12대수…]`+`[9수…]`). 출제 범위 안의
성취기준을 하나라도 다루면 수능이 낼 수 있는 문항이고(수능 문항도 중학 지식을 쓴다), **범위 안
코드가 하나도 없는** 문항만 범위 밖이다. 교집합 비공집합 의미는 `l6/school_progress/gating.py`의
성취기준 정합과 같다.

공통수학(`[10공수…]`·`[10기수…]`)은 2028 수능 출제 범위가 **아니다** — 선수 영역이다. 선수 영역
복습은 수능 적격 게이트가 아니라 EOS-35(재선택 재판정)의 "모드 밖 선수 복습 제안"이 소유한다.

레이어 규칙: L6은 sqlalchemy·db를 import하지 않는다(import-linter 계약). 이 모듈은 접두어 *데이터*와
순수 판정 함수만 둔다 — SQL 절은 같은 접두어 상수를 읽어 api 쪽이
조립한다(`api/_next_problem_policy.py`).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from whymath_backend.schema.enums import Curriculum
from whymath_backend.schema.problem import Problem

__all__ = [
    "SUNEUNG_SCOPE",
    "SUNEUNG_SCOPES",
    "SUNEUNG_TARGET_EXAM_YEAR",
    "ScopeVerdict",
    "SuneungScope",
    "code_in_scope",
    "suneung_scope_verdict",
]


@dataclass(frozen=True, slots=True)
class SuneungScope:
    """한 학년도 수능의 출제 범위 — 교육과정 개정 + 성취기준 코드 접두어 집합.

    `code_prefixes`의 각 원소는 대괄호 **뒤**부터의 접두어다(`"12대수"` → `[12대수01-01]`에 일치).
    대괄호를 포함해 비교하므로 `"12대수"`가 `[112대수…]` 같은 값에 우연히 닿지 않는다.
    """

    exam_year: int
    curriculum: Curriculum
    code_prefixes: tuple[str, ...]

    def code_startswith_patterns(self) -> tuple[str, ...]:
        """고시 코드 앞머리 문자열(`"[12대수"`) 목록 — 파이썬·SQL `LIKE '…%'`가 같은 값을 쓴다."""
        return tuple(f"[{prefix}" for prefix in self.code_prefixes)


#: 2028학년도 — 2022 개정 대수·미적분Ⅰ·확률과 통계. 기하(`12기하`)는 2028 수능 범위가 아니다.
_SCOPE_2028 = SuneungScope(
    exam_year=2028,
    curriculum=Curriculum.REVISION_2022,
    code_prefixes=("12대수", "12미적Ⅰ", "12확통"),
)

#: 학년도 → 출제 범위 레지스트리. 2027학년도(2015 개정)는 그 코드가 코퍼스에 적재되면 추가한다
#: (같은 접두어가 2015·2022 양쪽에 있을 수 있어 `curriculum`이 함께 일치해야 범위 안이다).
#: **미적분은 `12미적Ⅰ`까지 써야 한다** — `12미적`만 쓰면 진로 선택 과목 미적분Ⅱ(`[12미적Ⅱ-…]`)와
#: 2015 개정 숫자형(`[12미적01-…]`)까지 걸린다. 2022 개정 과목 구조: 일반 선택 = 대수·미적분Ⅰ·
#: 확률과 통계, 진로 선택 = 기하·미적분Ⅱ·경제 수학·인공지능 수학·직무 수학 등(수능 범위 밖).
SUNEUNG_SCOPES: dict[int, SuneungScope] = {_SCOPE_2028.exam_year: _SCOPE_2028}

#: 수능 모드가 목표로 하는 학년도. 승인 코퍼스가 전량 2022 개정이라 2028이다(모듈 docstring).
SUNEUNG_TARGET_EXAM_YEAR: int = 2028

#: 게이트·SQL 사전필터가 공유하는 *현행* 범위(단일 진실 원천).
SUNEUNG_SCOPE: SuneungScope = SUNEUNG_SCOPES[SUNEUNG_TARGET_EXAM_YEAR]


class ScopeVerdict(str, Enum):
    """출제 범위 판정 — 세 값(모른다 ≠ 아니다). 게이트는 `IN_SCOPE`만 통과시킨다."""

    IN_SCOPE = "in_scope"
    """성취기준 코드 중 범위 안 접두어가 하나 이상 있고 교육과정 개정이 일치."""

    OUT_OF_SCOPE = "out_of_scope"
    """코드가 있으나 범위 안 접두어가 없거나, 교육과정 개정이 목표 학년도와 다르다."""

    UNKNOWN = "unknown"
    """성취기준 코드가 하나도 없다 — 범위를 판정할 근거가 없다(통과시키지 않는다)."""


def code_in_scope(code: str, scope: SuneungScope = SUNEUNG_SCOPE) -> bool:
    """성취기준 고시 코드 하나가 출제 범위 접두어에 일치하는가(`[12대수01-01]` → True)."""
    return code.startswith(scope.code_startswith_patterns())


def _normalized_curriculum(problem: Problem) -> str:
    """`curriculum_version`을 문자열 값으로 정규화 — `use_enum_values=True`로 enum/문자열이
    섞인다."""
    value = problem.curriculum_version
    return value.value if isinstance(value, Curriculum) else str(value)


def suneung_scope_verdict(problem: Problem, scope: SuneungScope = SUNEUNG_SCOPE) -> ScopeVerdict:
    """문항의 출제 범위 판정 — 교육과정 개정 일치 + 성취기준 코드 접두어 교집합.

    판정 순서: ① 코드가 없으면 `UNKNOWN`(개정이 달라도 범위를 판정할 근거 자체가 없으므로 이 값이
    먼저다 — 사후 관측이 "코드 미주입"을 "범위 밖"으로 오독하지 않게) ② 교육과정 개정이 목표
    학년도의 것과 다르면 `OUT_OF_SCOPE`(같은 접두어가 개정마다 다른 내용을 가리킨다) ③ 범위 안
    접두어가 하나라도 있으면 `IN_SCOPE`, 없으면 `OUT_OF_SCOPE`.
    """
    codes: Iterable[str] = problem.achievement_standard_codes
    if not codes:
        return ScopeVerdict.UNKNOWN
    if _normalized_curriculum(problem) != scope.curriculum.value:
        return ScopeVerdict.OUT_OF_SCOPE
    if any(code_in_scope(code, scope) for code in codes):
        return ScopeVerdict.IN_SCOPE
    return ScopeVerdict.OUT_OF_SCOPE
