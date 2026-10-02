"""L6 수능 출제 범위 정의 단위테스트 — EOS-31 (hermetic · DB 0).

`l6/suneung/scope.py`가 지키는 것:
  ① 접두어 판정 — 범위 안 코드(`[12대수…]`·`[12미적…]`·`[12확통…]`)만 안이다. 중학교·공통수학·기하·
     진로선택 과목은 2028학년도 수능 범위 밖이다.
  ② 세 값 — 코드 없음(`UNKNOWN`)과 범위 밖(`OUT_OF_SCOPE`)은 다른 값이다("모른다 ≠ 아니다").
  ③ "하나라도" 의미 — 범위 안 코드가 하나 이상 있으면 안이다(교집합 비공집합).
  ④ 교육과정 개정 일치 — 같은 접두어라도 개정이 목표 학년도와 다르면 밖이다.

**변별력**: 각 경계마다 정반대 입력(대조군)을 쌍으로 둔다 — "전부 안"이나 "전부 밖"인 판정기를
통과시키지 않도록. 접두어 목록은 하드코딩 값이 아니라 `SUNEUNG_SCOPE`에서 읽어, 이 파일이 정의의
사본이 되지 않게 한다(범위가 바뀌면 이 테스트가 아니라 `scope.py`를 고친다).
"""

from __future__ import annotations

import pytest

from whymath_backend.l6.suneung.scope import (
    SUNEUNG_SCOPE,
    SUNEUNG_SCOPES,
    SUNEUNG_TARGET_EXAM_YEAR,
    ScopeVerdict,
    SuneungScope,
    code_in_scope,
    suneung_scope_verdict,
)
from whymath_backend.schema.enums import Curriculum, ReviewStatus, SourceType, Subject
from whymath_backend.schema.problem import Problem


def _problem(codes: list[str], **over: object) -> Problem:
    kwargs: dict[str, object] = {
        "source_type": SourceType.자체생성,
        "review_status": ReviewStatus.approved,
        "curriculum_version": Curriculum.REVISION_2022,
        "valid_from_year": 2022,
        "subject": Subject.공통,
        "unit_codes": ["U-EOS31"],
        "achievement_standard_codes": codes,
    }
    kwargs.update(over)
    return Problem(**kwargs)  # type: ignore[arg-type]


class TestDefinition:
    def test_registry_resolves_the_target_exam_year(self) -> None:
        assert SUNEUNG_SCOPE is SUNEUNG_SCOPES[SUNEUNG_TARGET_EXAM_YEAR]
        assert SUNEUNG_SCOPE.exam_year == SUNEUNG_TARGET_EXAM_YEAR

    def test_target_year_scope_matches_the_judgment(self) -> None:
        """2028학년도 = 2022 개정 대수·미적분Ⅰ·확률과 통계 — 이 판정이 바뀌면 판정문을 먼저 고친다."""
        assert SUNEUNG_SCOPE.curriculum is Curriculum.REVISION_2022
        assert set(SUNEUNG_SCOPE.code_prefixes) == {"12대수", "12미적Ⅰ", "12확통"}

    def test_patterns_include_the_opening_bracket(self) -> None:
        """대괄호까지 포함해 비교한다 — 접두어가 코드 중간에 우연히 닿지 않게."""
        assert SUNEUNG_SCOPE.code_startswith_patterns() == ("[12대수", "[12미적Ⅰ", "[12확통")


class TestCodeInScope:
    @pytest.mark.parametrize("code", ["[12대수01-01]", "[12미적Ⅰ-02-03]", "[12확통01-02]"])
    def test_in_scope_codes(self, code: str) -> None:
        assert code_in_scope(code) is True

    @pytest.mark.parametrize(
        "code",
        [
            "[4수01-01]",  # 초등
            "[6수01-01]",  # 초등
            "[9수02-01]",  # 중학교
            "[10공수1-01-01]",  # 공통수학 — 선수 영역이지 출제 범위가 아니다
            "[10기수1-02-02]",  # 기본수학
            "[12기하02-05]",  # 기하 — 진로 선택, 2028 수능 범위가 아니다
            "[12미적Ⅱ-01-01]",  # 미적분Ⅱ — 진로 선택. 접두어 `12미적`만 쓰면 새는 형태(EOS-31 실측 72건)
            "[12미적01-01]",  # 2015 개정 숫자형 미적분 — 2022 범위의 미적분Ⅰ과 다른 코드다
            "[12직수01-01]",  # 직무수학(진로선택)
            "[12수문01-01]",  # 수학과 문화
            "[12인수01-01]",  # 인공지능 수학
        ],
    )
    def test_out_of_scope_codes(self, code: str) -> None:
        assert code_in_scope(code) is False

    @pytest.mark.parametrize(
        "code", ["12대수01-01", "x[12대수01-01]", " [12대수01-01]", "", "[12대"]
    )
    def test_prefix_must_be_anchored_with_bracket_at_the_start(self, code: str) -> None:
        """대괄호가 없거나 앞에 다른 글자가 있거나 접두어가 잘렸으면 안이 아니다(부분 일치 금지)."""
        assert code_in_scope(code) is False


class TestVerdict:
    def test_in_scope_when_any_code_is_in_scope(self) -> None:
        assert suneung_scope_verdict(_problem(["[12대수01-01]"])) is ScopeVerdict.IN_SCOPE

    def test_bridge_item_with_one_in_scope_code_is_in_scope(self) -> None:
        """중학교 코드와 범위 안 코드를 함께 잇는 문항은 안이다 — '하나라도'(교집합 비공집합)."""
        problem = _problem(["[9수02-01]", "[12대수01-01]"])
        assert suneung_scope_verdict(problem) is ScopeVerdict.IN_SCOPE

    def test_out_of_scope_when_no_code_is_in_scope(self) -> None:
        problem = _problem(["[9수02-01]", "[10공수1-01-01]"])
        assert suneung_scope_verdict(problem) is ScopeVerdict.OUT_OF_SCOPE

    def test_unknown_when_no_codes_is_not_out_of_scope(self) -> None:
        """코드가 없으면 `OUT_OF_SCOPE`가 아니라 `UNKNOWN` — 모른다와 아니다를 같은 글자로 쓰지 않는다."""
        verdict = suneung_scope_verdict(_problem([]))
        assert verdict is ScopeVerdict.UNKNOWN
        assert verdict is not ScopeVerdict.OUT_OF_SCOPE

    def test_unknown_wins_over_curriculum_mismatch(self) -> None:
        """코드가 없으면 개정이 달라도 `UNKNOWN`이다 — 범위를 판정할 근거 자체가 없다."""
        problem = _problem([], curriculum_version=Curriculum.REVISION_2015)
        assert suneung_scope_verdict(problem) is ScopeVerdict.UNKNOWN

    def test_same_prefix_in_another_curriculum_is_out_of_scope(self) -> None:
        """같은 접두어가 개정마다 다른 내용을 가리킬 수 있다 — 개정이 다르면 범위 밖이다."""
        inside = _problem(["[12대수01-01]"], curriculum_version=Curriculum.REVISION_2022)
        outside = _problem(["[12대수01-01]"], curriculum_version=Curriculum.REVISION_2015)
        assert suneung_scope_verdict(inside) is ScopeVerdict.IN_SCOPE
        assert suneung_scope_verdict(outside) is ScopeVerdict.OUT_OF_SCOPE

    def test_string_curriculum_value_is_normalized(self) -> None:
        """`use_enum_values=True`로 개정이 문자열일 수 있다 — enum/문자열 모두 같은 판정."""
        problem = _problem(["[12대수01-01]"]).model_copy(
            update={"curriculum_version": Curriculum.REVISION_2022.value}
        )
        assert suneung_scope_verdict(problem) is ScopeVerdict.IN_SCOPE

    def test_explicit_scope_argument_overrides_the_default(self) -> None:
        """범위는 인자로 바꿀 수 있다 — 다른 학년도 규칙이 레지스트리에 추가돼도 같은 함수가 쓰인다."""
        geometry_only = SuneungScope(
            exam_year=2099, curriculum=Curriculum.REVISION_2022, code_prefixes=("12기하",)
        )
        problem = _problem(["[12기하02-05]"])
        assert suneung_scope_verdict(problem, geometry_only) is ScopeVerdict.IN_SCOPE
        assert suneung_scope_verdict(problem) is ScopeVerdict.OUT_OF_SCOPE
