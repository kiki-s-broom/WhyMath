"""서버측 답안 채점 shadow 리포트 테스트(NLP-02) — acceptance①~⑤ 대응.

구성:
  - `derive_verify_inputs` 단위 테스트(파생 정확성 위험 — 학생 답을 엉뚱한 변수에 대입하지
    않는지 등, 순수·DB 0). NLP-09 이후 게이트는 미지수의 *이름*이 아니라 *개수*를 본다.
  - `build_report` 회귀 테스트(unverifiable이 mismatch로 새지 않음 — 순수·DB 0)
  - `submit_attempt` BKT 입력 동결 구조 테스트(소스 레벨 — api/me.py 무변경 증명)
  - 변별력 discriminating 테스트(acceptance⑤) — 실 PostgreSQL 필요(`pytest.mark.integration`,
    `tests/backend/api/test_me_integration.py`의 async 엔진 seed/cleanup 관례 답습)
"""

from __future__ import annotations

import inspect
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from whymath_backend.api import me as api_me
from whymath_backend.config import Settings
from whymath_backend.db.models.activity import ProblemAttempt
from whymath_backend.db.models.problem import Problem as ProblemORM
from whymath_backend.db.models.user import UserProfile
from whymath_backend.harness.attempt_grading_shadow_report import (
    AttemptRecord,
    _derive_from_conditions_parsed,
    _derive_from_corpus,
    _load_corpus_verify_blocks,
    build_gradability_ceiling_report,
    build_report,
    classify_gradability,
    derive_verify_inputs,
    fetch_attempt_records,
    gradability_report_to_json,
    grade_attempt,
    main,
    render_gradability_ceiling_report,
    render_report,
    report_to_json,
)
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    Persona,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Condition, Problem
from whymath_backend.schema.user import UserProfile as UserProfileSchema

pytestmark = pytest.mark.filterwarnings("ignore")


# ──────────────────────────────────────────────────────────────────────────
# 헬퍼 — 최소 Problem(schema) 구성
# ──────────────────────────────────────────────────────────────────────────
def _problem(
    *,
    conditions: list[Condition] | None = None,
    answer: str | None = "3",
    choices: list[str] | None = None,
    question_format: QuestionFormat | None = None,
    answer_format: AnswerFormat | None = None,
    slug: str | None = None,
) -> Problem:
    return Problem(
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.공통,
        unit_codes=["U-TEST"],
        conditions_parsed=conditions if conditions is not None else [],
        answer=answer,
        choices=choices,
        question_format=question_format,
        answer_format=answer_format,
        slug=slug,
    )


def _cond(formal: str | None, label: str = "가") -> Condition:
    return Condition(label=label, text="조건", formal=formal)


# ──────────────────────────────────────────────────────────────────────────
# derive_verify_inputs 단위 테스트
# ──────────────────────────────────────────────────────────────────────────
class TestDeriveVerifyInputs:
    def test_single_condition_x_derives(self) -> None:
        """단일 조건·자유기호 x·유효 answer → 정확한 (conditions, answer_map)."""
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        result = derive_verify_inputs(problem)
        assert result is not None
        conditions, answer_map = result
        assert conditions == ["2*x - 6"]
        assert answer_map == {"x": "3"}

    def test_unknown_is_y_not_x_derives_with_key_y(self) -> None:
        """조건의 미지수가 y(≠x)여도 **하나뿐이면** 파생한다 — 키는 `y`다(NLP-09).

        이 테스트는 원래 `... _returns_none`이었다. 당시 위험 시나리오는 "`{"x": answer}`를
        순진하게 만들어 엉뚱한 변수에 대입"이었고, 이름을 `x`로 못 박는 것이 그 방어였다.
        NLP-09가 방어를 이름에서 **개수**로 옮기면서 그 위험은 뿌리에서 사라졌다 — 답산맵
        키를 조건식의 자유기호에서 읽어 오므로, 대입할 자리가 애초에 하나뿐이다.

        그래서 여기서 확인할 것은 두 가지다: ①파생이 되는가 ②키가 `x`로 **바뀌어 있지
        않은가**. ②가 없으면 "이름을 y로 넓혔다"와 "전부 x로 이름을 갈아 끼웠다"가 같은
        초록을 낸다 — 후자는 `y`가 미결 자유기호로 남는 바로 그 사고다.
        """
        problem = _problem(conditions=[_cond("2*y - 6")], answer="3")
        result = derive_verify_inputs(problem)
        assert result is not None
        conditions, answer_map = result
        assert conditions == ["2*y - 6"]
        assert answer_map == {"y": "3"}

    def test_two_unknowns_still_return_none(self) -> None:
        """미지수가 둘이면 여전히 비파생 — 개수 게이트가 남아 있음을 고정한다.

        NLP-09가 이름 게이트를 걷어냈으므로, 개수 게이트가 실제로 남았는지 별도로 밟아야
        한다. 이 픽스처가 없으면 "게이트를 통째로 없앴다"도 초록으로 통과한다.
        """
        problem = _problem(conditions=[_cond("2*y - 6"), _cond("t - 1")], answer="3")
        assert derive_verify_inputs(problem) is None

    def test_no_unknown_at_all_returns_none(self) -> None:
        """자유기호가 0개(상수식)여도 비파생 — 학생 답을 대입할 자리가 없다.

        `len(free_symbols) != 1`의 **아래쪽** 경계다. `> 1`만 막는 구현으로 바꿔도
        위 두 테스트는 통과하므로, 이 픽스처가 그 절의 반례를 맡는다.
        """
        problem = _problem(conditions=[_cond("2 - 2")], answer="0")
        assert derive_verify_inputs(problem) is None

    def test_no_formal_at_all_returns_none(self) -> None:
        """formal이 아예 없는 조건(None) → None(비파생)."""
        problem = _problem(conditions=[_cond(None)], answer="3")
        assert derive_verify_inputs(problem) is None

    def test_formal_parsing_to_bare_bool_returns_none(self) -> None:
        """파싱 결과에 자유기호를 물을 수 없으면(파이썬 `bool`) 비파생 — 모른다 ≠ 0개.

        `sympy.sympify("True")`는 SymPy 식이 아니라 파이썬 `True`를 돌려주므로
        `free_symbols` 속성 자체가 없다. `_free_symbol_names`가 이때 빈 집합을 돌려주면
        "미지수 0개"라는 *확정* 신호가 되어 아래쪽 경계와 구분이 사라진다 — 그래서
        `None`(모름)으로 돌려주고 보수적으로 후퇴한다.

        이 픽스처가 없으면 `names is None` 절을 통째로 지워도 전건 초록이다(실제 코퍼스에
        이 형태가 0건이라 모집단 테스트도 안 밟는다). CLAUDE.md "전건 RED ≠ 커버리지".

        **사유까지 단언하는 이유**: 처음엔 `is None`만 봤는데 뮤테이션 M7이 살아남았다 —
        절을 `_free_symbol_names(parsed) or set()`으로 바꿔도 자유기호가 빈 집합이 되어
        개수 게이트에 걸리므로 반환값은 똑같이 `None`이었다. 달라지는 것은 **사유**뿐이다
        (`parse_error` → `multi_symbol`). 결과만 보는 단언은 그 절을 밟고도 변별하지 못한다.
        """
        problem = _problem(conditions=[_cond("True")], answer="3")
        assert derive_verify_inputs(problem) is None
        # 사유는 "미지수가 0개"가 아니라 "물어볼 수 없었다"여야 한다.
        assert _derive_from_conditions_parsed(problem) == "parse_error"

    def test_multiple_conditions_combined_symbols_not_exactly_x_returns_none(self) -> None:
        """여러 조건의 자유기호 **합집합 크기가 1이 아님**(다중 변수) → None(비파생).

        이 슬라이스는 단일 미지수 문항만 지원한다(모듈 docstring 명시 스코프 밖).
        NLP-09 이후 판정은 "합집합이 {"x"}인가"가 아니라 "합집합이 한 개인가"다 —
        조건별로는 미지수가 하나씩이어도 합쳐서 둘이면 걸린다는 축은 그대로다.
        """
        problem = _problem(
            conditions=[_cond("x + y - 3"), _cond("x - y - 1")],
            answer="2",
        )
        assert derive_verify_inputs(problem) is None

    def test_no_conditions_returns_none(self) -> None:
        problem = _problem(conditions=[], answer="3")
        assert derive_verify_inputs(problem) is None

    def test_no_answer_returns_none(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer=None)
        assert derive_verify_inputs(problem) is None

    def test_unparseable_formal_returns_none(self) -> None:
        """formal이 SymPy로 파싱 불가(단일 등호 등) → None(보수적 비파생·크래시 금지).

        단일 `=`는 파이썬 대입문이라 sympify가 예외를 던진다 — verify_answer._parse_condition과
        달리 이 파생 게이트는 등호 전처리를 하지 않는다(단순 자유기호 추출용 — 모듈 docstring).
        """
        problem = _problem(conditions=[_cond("2*x - 6 = 0")], answer="3")
        assert derive_verify_inputs(problem) is None

    def test_multiple_conditions_all_x_derives(self) -> None:
        """여러 조건이 모두 x만 포함 → 파생 성공(연립 conditions 리스트로 전달)."""
        problem = _problem(
            conditions=[_cond("x - 2", label="가"), _cond("x**2 - 4", label="나")],
            answer="2",
        )
        result = derive_verify_inputs(problem)
        assert result is not None
        conditions, answer_map = result
        assert conditions == ["x - 2", "x**2 - 4"]
        assert answer_map == {"x": "2"}


# ──────────────────────────────────────────────────────────────────────────
# grade_attempt — student_answer가 항상 채점 대상값임을 확인
# ──────────────────────────────────────────────────────────────────────────
class TestGradeAttempt:
    def test_grades_student_answer_not_problem_answer(self) -> None:
        """Problem.answer(정답 본문)가 아니라 student_answer가 실제 채점 대상."""
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        # 문항 정답은 3이지만 학생 제출은 5(오답) — verdict는 fail이어야 한다.
        verdict = grade_attempt(problem, "5")
        assert verdict is not None
        assert verdict.state == "fail"

    def test_correct_student_answer_passes(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        verdict = grade_attempt(problem, "3")
        assert verdict is not None
        assert verdict.state == "pass"

    def test_no_student_answer_returns_none(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        assert grade_attempt(problem, None) is None
        assert grade_attempt(problem, "   ") is None

    def test_non_derivable_problem_returns_none(self) -> None:
        # NLP-09: 비파생 픽스처를 `2*y - 6`(단일 미지수 y — 이제 파생된다)에서
        # 미지수 2개로 바꿨다. 이름이 아니라 개수가 게이트이므로.
        problem = _problem(conditions=[_cond("2*y - 6"), _cond("t - 1")], answer="3")
        assert grade_attempt(problem, "3") is None

    def test_unverifiable_via_singularity(self) -> None:
        """특이점(0으로 나눔)에서 unverifiable — pass/fail로 위장하지 않음."""
        problem = _problem(conditions=[_cond("1/(x-3)")], answer="3")
        verdict = grade_attempt(problem, "3")
        assert verdict is not None
        assert verdict.state == "unverifiable"


# ──────────────────────────────────────────────────────────────────────────
# build_report 회귀 테스트 — unverifiable이 mismatch/오답으로 새지 않음(acceptance②)
# ──────────────────────────────────────────────────────────────────────────
class TestBuildReportRegression:
    def test_unverifiable_never_counted_as_mismatch(self) -> None:
        """unverifiable verdict는 client_is_correct와 무관하게 mismatch에 절대 반영 안 됨."""
        problem = _problem(conditions=[_cond("1/(x-3)")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",  # 특이점 → unverifiable
                client_is_correct=True,
                problem=problem,
            ),
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",
                client_is_correct=False,  # 클라 보고가 반대여도 mismatch 0이어야 함
                problem=problem,
            ),
        ]
        report = build_report(records)
        assert report.verdict_counts["unverifiable"] == 2
        assert report.client_grade_mismatch_count == 0
        assert report.verifiable_count == 2
        assert report.not_derivable_count == 0

    def test_unverifiable_not_downgraded_to_fail(self) -> None:
        """unverifiable은 verdict_counts에서 fail 버킷으로 새지 않는다(별도 키로 집계)."""
        problem = _problem(conditions=[_cond("1/(x-3)")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",
                client_is_correct=True,
                problem=problem,
            )
        ]
        report = build_report(records)
        assert report.verdict_counts["fail"] == 0
        assert report.verdict_counts["unverifiable"] == 1

    def test_not_derivable_and_unverifiable_are_disjoint_buckets(self) -> None:
        """비파생(재료 없음)과 unverifiable(검증기 결과)은 겹치지 않는 별개 분모."""
        derivable_but_unverifiable = _problem(conditions=[_cond("1/(x-3)")], answer="3")
        # NLP-09: 단일 미지수 y는 이제 파생되므로 비파생 대역은 미지수 2개가 맡는다.
        non_derivable = _problem(conditions=[_cond("2*y - 6"), _cond("t - 1")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",
                client_is_correct=True,
                problem=derivable_but_unverifiable,
            ),
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",
                client_is_correct=True,
                problem=non_derivable,
            ),
        ]
        report = build_report(records)
        assert report.total_attempts == 2
        assert report.not_derivable_count == 1
        assert report.verifiable_count == 1
        assert report.verdict_counts["unverifiable"] == 1

    def test_client_is_correct_none_excluded_from_mismatch_but_counted_verifiable(self) -> None:
        """client_is_correct가 None(레거시 미채점)이면 mismatch 대상에서 제외되나 verdict는 집계."""
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",  # pass
                client_is_correct=None,
                problem=problem,
            )
        ]
        report = build_report(records)
        assert report.verifiable_count == 1
        assert report.verdict_counts["pass"] == 1
        assert report.client_grade_mismatch_count == 0

    def test_zero_verifiable_denominator_is_not_bare_zero(self) -> None:
        """분모(verifiable_count)가 0이면 rate 프로퍼티는 None(0%로 위장 금지)."""
        # NLP-09: 비파생은 이제 미지수 2개다(단일 y는 파생된다).
        problem = _problem(conditions=[_cond("2*y - 6"), _cond("t - 1")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",
                client_is_correct=True,
                problem=problem,
            )
        ]
        report = build_report(records)
        assert report.verifiable_count == 0
        assert report.mismatch_rate is None
        assert report.unverifiable_rate is None
        rendered = render_report(report)
        assert "측정 불가" in rendered

    def test_mismatch_zero_with_positive_denominator_shows_denominator(self) -> None:
        """acceptance④ 리터럴 문구 — 검산 가능 표본 N건 중 0건(분모 없는 '0건' 금지)."""
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(),
                student_answer="3",  # pass, 클라도 True → mismatch 0
                client_is_correct=True,
                problem=problem,
            )
        ]
        report = build_report(records)
        assert report.client_grade_mismatch_count == 0
        assert report.verifiable_count == 1
        rendered = render_report(report)
        assert "검산 가능 표본 1건 중 0건" in rendered

    def test_report_to_json_roundtrip(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(), student_answer="3", client_is_correct=True, problem=problem
            ),
            AttemptRecord(
                attempt_id=uuid.uuid4(), student_answer="5", client_is_correct=True, problem=problem
            ),
        ]
        report = build_report(records)
        payload = report_to_json(report)
        assert payload["total_attempts"] == 2
        assert payload["client_grade_mismatch_count"] == 1  # 두 번째는 fail인데 클라는 True
        assert payload["mismatch_rate"] == pytest.approx(0.5)


# ──────────────────────────────────────────────────────────────────────────
# acceptance② — verifiable_count==0의 구조적 원인 구분(표본 없음 vs 파생 가능 문항 0)
# ──────────────────────────────────────────────────────────────────────────
class TestVerifiableZeroReason:
    def test_no_sample_when_total_attempts_zero(self) -> None:
        report = build_report([])
        assert report.total_attempts == 0
        assert report.verifiable_count == 0
        assert report.verifiable_zero_reason == "no_sample"

    def test_not_derivable_when_attempts_exist_but_none_verifiable(self) -> None:
        # 조건 없는 문항(파생 불가) — attempt는 있는데 전량 not_derivable.
        problem = _problem(conditions=[], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(), student_answer="3", client_is_correct=True, problem=problem
            )
        ]
        report = build_report(records)
        assert report.total_attempts == 1
        assert report.verifiable_count == 0
        assert report.verifiable_zero_reason == "not_derivable"

    def test_none_when_verifiable_positive(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        records = [
            AttemptRecord(
                attempt_id=uuid.uuid4(), student_answer="3", client_is_correct=True, problem=problem
            )
        ]
        report = build_report(records)
        assert report.verifiable_count == 1
        assert report.verifiable_zero_reason is None

    def test_render_report_distinguishes_two_zero_causes(self) -> None:
        """같은 값(둘 다 '0건')이면 검증이 아니다 — 원인별로 실제로 다른 문구가 나와야 한다."""
        no_sample_report = build_report([])
        problem = _problem(conditions=[], answer="3")
        not_derivable_report = build_report(
            [
                AttemptRecord(
                    attempt_id=uuid.uuid4(),
                    student_answer="3",
                    client_is_correct=True,
                    problem=problem,
                )
            ]
        )
        no_sample_text = render_report(no_sample_report)
        not_derivable_text = render_report(not_derivable_report)
        assert "표본 없음" in no_sample_text
        assert "표본 없음" not in not_derivable_text
        assert "파생 가능 문항 0건" in not_derivable_text
        assert "파생 가능 문항 0건" not in no_sample_text

    def test_report_to_json_includes_verifiable_zero_reason(self) -> None:
        payload = report_to_json(build_report([]))
        assert payload["verifiable_zero_reason"] == "no_sample"


# ──────────────────────────────────────────────────────────────────────────
# REC-05 acceptance① — 채점 가능성 상한(코퍼스 정적, attempt 무관) 분류
# ──────────────────────────────────────────────────────────────────────────
class TestClassifyGradability:
    def test_choices_exact_match_is_selectable(self) -> None:
        problem = _problem(choices=["1", "2", "3", "4"], answer="3")
        assert classify_gradability(problem) == "selectable_exact_match"

    def test_choices_present_but_answer_mismatch_falls_through(self) -> None:
        """이상치(choices에 answer가 없음)는 A로 오분류되지 않고 정직하게 unclassified로 간다."""
        problem = _problem(choices=["1", "2", "4"], answer="3")
        assert classify_gradability(problem) == "unclassified"

    @pytest.mark.parametrize(
        "answer_format", [AnswerFormat.자연수, AnswerFormat.실수, AnswerFormat.분수]
    )
    def test_numeric_short_answer_is_bucket_b(self, answer_format: AnswerFormat) -> None:
        problem = _problem(
            answer="3", question_format=QuestionFormat.단답형, answer_format=answer_format
        )
        assert classify_gradability(problem) == "numeric_short_answer_candidate"

    def test_expression_answer_format_excluded_from_bucket_b(self) -> None:
        problem = _problem(
            answer="x+1", question_format=QuestionFormat.단답형, answer_format=AnswerFormat.식
        )
        assert classify_gradability(problem) == "unclassified"

    def test_condition_formal_derivable_is_bucket_c(self) -> None:
        problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        assert classify_gradability(problem) == "condition_formal_derivable"

    def test_priority_a_over_c_when_both_satisfiable(self) -> None:
        """A와 C를 동시에 만족해도 A가 우선(하드 우선순위 계약)."""
        problem = _problem(choices=["1", "2", "3", "4"], answer="3", conditions=[_cond("2*x - 6")])
        assert classify_gradability(problem) == "selectable_exact_match"

    def test_no_match_anywhere_is_unclassified(self) -> None:
        problem = _problem(choices=None, answer="서술 답안", conditions=[])
        assert classify_gradability(problem) == "unclassified"


class TestBuildGradabilityCeilingReport:
    def test_buckets_are_mutually_exclusive_and_sum_to_total(self) -> None:
        problems = [
            _problem(choices=["1", "2"], answer="1"),
            _problem(
                answer="3", question_format=QuestionFormat.단답형, answer_format=AnswerFormat.자연수
            ),
            _problem(conditions=[_cond("2*x - 6")], answer="3"),
            _problem(choices=None, answer="서술", conditions=[]),
        ]
        report = build_gradability_ceiling_report(problems)
        assert report.total_problems == 4
        assert sum(report.bucket_counts.values()) == 4
        assert report.bucket_counts["selectable_exact_match"] == 1
        assert report.bucket_counts["numeric_short_answer_candidate"] == 1
        assert report.bucket_counts["condition_formal_derivable"] == 1
        assert report.bucket_counts["unclassified"] == 1

    def test_zero_total_denominator_rate_is_none(self) -> None:
        report = build_gradability_ceiling_report([])
        assert report.total_problems == 0
        for bucket in (
            "selectable_exact_match",
            "numeric_short_answer_candidate",
            "condition_formal_derivable",
            "unclassified",
        ):
            assert report.bucket_rate(bucket) is None

    def test_zero_condition_derivable_renders_not_derivable_not_bare_zero(self) -> None:
        problems = [_problem(choices=["1", "2"], answer="1")]
        report = build_gradability_ceiling_report(problems)
        assert report.bucket_counts["condition_formal_derivable"] == 0
        rendered = render_gradability_ceiling_report(report)
        assert "파생 불가" in rendered
        assert "formal 전건 결측" in rendered

    def test_gradability_report_to_json_structure(self) -> None:
        report = build_gradability_ceiling_report([_problem(choices=["1", "2"], answer="1")])
        payload = gradability_report_to_json(report)
        assert payload["total_problems"] == 1
        assert set(payload["bucket_counts"]) == {
            "selectable_exact_match",
            "numeric_short_answer_candidate",
            "condition_formal_derivable",
            "unclassified",
        }
        assert set(payload["bucket_rates"]) == set(payload["bucket_counts"])
        assert payload["bucket_rates"]["selectable_exact_match"] == pytest.approx(1.0)
        assert set(payload["unclassified_reason_counts"]) == {
            "no_verify_block",
            "parse_error",
            "multi_symbol",
        }

    def test_unclassified_reason_counts_sum_equals_unclassified_bucket(self) -> None:
        """unclassified_reason_counts 합은 bucket_counts['unclassified']와 같아야 한다."""
        problems = [
            _problem(choices=None, answer="서술", conditions=[]),  # no_verify_block
            _problem(conditions=[_cond("x + y - 3")], answer="1"),  # multi_symbol
            _problem(conditions=[_cond("2*x - 6 = 0")], answer="3"),  # parse_error
        ]
        report = build_gradability_ceiling_report(problems)
        assert report.bucket_counts["unclassified"] == 3
        assert sum(report.unclassified_reason_counts.values()) == 3
        assert report.unclassified_reason_counts["no_verify_block"] == 1
        assert report.unclassified_reason_counts["multi_symbol"] == 1
        assert report.unclassified_reason_counts["parse_error"] == 1

    def test_render_includes_unclassified_reason_section(self) -> None:
        problems = [_problem(choices=None, answer="서술", conditions=[])]
        report = build_gradability_ceiling_report(problems)
        rendered = render_gradability_ceiling_report(report)
        assert "## 미분류 사유" in rendered
        assert "no_verify_block: 1" in rendered


class TestGradabilityCeilingDiscriminates:
    """REC-05 acceptance④ — formal 보유 문항 주입/제거로 C버킷이 양방향으로 실제로 움직인다."""

    def test_c_bucket_toggles_bidirectionally_when_formal_problem_injected_and_removed(
        self,
    ) -> None:
        baseline = [
            _problem(choices=["1", "2"], answer="1"),
            _problem(choices=None, answer="서술", conditions=[]),
        ]
        before = build_gradability_ceiling_report(baseline)
        assert before.bucket_counts["condition_formal_derivable"] == 0

        formal_problem = _problem(conditions=[_cond("2*x - 6")], answer="3")
        after_inject = build_gradability_ceiling_report([*baseline, formal_problem])
        assert after_inject.bucket_counts["condition_formal_derivable"] == 1

        after_remove = build_gradability_ceiling_report(baseline)
        assert after_remove.bucket_counts["condition_formal_derivable"] == 0

    def test_no_verify_block_reason_counts_toggle_with_injected_missing_problem(self) -> None:
        """acceptance⑦ — verify 재료가 없는 문항 주입/제거로 no_verify_block 카운터가 양방향으로 움직인다."""
        baseline = [
            _problem(choices=["1", "2"], answer="1"),
            _problem(conditions=[_cond("2*x - 6")], answer="3"),
        ]
        before = build_gradability_ceiling_report(baseline)
        assert before.unclassified_reason_counts["no_verify_block"] == 0

        missing = _problem(choices=None, answer="서술", conditions=[])
        after_inject = build_gradability_ceiling_report([*baseline, missing])
        assert after_inject.unclassified_reason_counts["no_verify_block"] == 1

        after_remove = build_gradability_ceiling_report(baseline)
        assert after_remove.unclassified_reason_counts["no_verify_block"] == 0

    def test_parse_error_reason_counted(self) -> None:
        """formal이 SymPy로 파싱 불가하면 parse_error 사유로 unclassified에 잡힌다."""
        problem = _problem(conditions=[_cond("2*x - 6 = 0")], answer="3")
        report = build_gradability_ceiling_report([problem])
        assert report.bucket_counts["unclassified"] == 1
        assert report.unclassified_reason_counts["parse_error"] == 1

    def test_multi_symbol_reason_counted(self) -> None:
        """다중 미지수는 multi_symbol 사유로 unclassified에 잡힌다."""
        problem = _problem(conditions=[_cond("x + y - 3")], answer="1")
        report = build_gradability_ceiling_report([problem])
        assert report.bucket_counts["unclassified"] == 1
        assert report.unclassified_reason_counts["multi_symbol"] == 1


# ──────────────────────────────────────────────────────────────────────────
# REC-05 CLI — --mode ceiling 배선 확인(기본 shadow는 회귀 0)
# ──────────────────────────────────────────────────────────────────────────
class TestMainCeilingMode:
    def test_mode_ceiling_dispatches_to_ceiling_report(self, monkeypatch, capsys) -> None:
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        async def _fake_run_ceiling(args):
            return build_gradability_ceiling_report([_problem(choices=["1", "2"], answer="1")])

        called = {"shadow": False}

        async def _fake_run_shadow(args):
            called["shadow"] = True
            return build_report([])

        monkeypatch.setattr(mod, "_run_ceiling", _fake_run_ceiling)
        monkeypatch.setattr(mod, "_run_shadow", _fake_run_shadow)

        exit_code = main(["--mode", "ceiling"])
        assert exit_code == 0
        assert called["shadow"] is False
        out = capsys.readouterr().out
        assert "코퍼스 채점 가능성 상한 리포트" in out

    def test_default_mode_is_shadow_unchanged(self, monkeypatch, capsys) -> None:
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        called = {"ceiling": False}

        async def _fake_run_ceiling(args):
            called["ceiling"] = True
            return build_gradability_ceiling_report([])

        async def _fake_run_shadow(args):
            return build_report([])

        monkeypatch.setattr(mod, "_run_ceiling", _fake_run_ceiling)
        monkeypatch.setattr(mod, "_run_shadow", _fake_run_shadow)

        exit_code = main([])
        assert exit_code == 0
        assert called["ceiling"] is False
        out = capsys.readouterr().out
        assert "서버측 답안 채점 shadow 리포트" in out


# ──────────────────────────────────────────────────────────────────────────
# acceptance③ — submit_attempt BKT 입력 불변 동결(소스 레벨 구조 테스트)
# ──────────────────────────────────────────────────────────────────────────
class TestSubmitAttemptUnchanged:
    """이 태스크는 api/me.py를 건드리지 않는다 — 소스 레벨로 그 사실과 BKT 입력 불변을 동결."""

    def test_verify_answer_not_wired_into_live_path(self) -> None:
        """`api/me.py`가 shadow 채점기(`verify_answer`)를 import/사용하지 않음(라이브 미배선)."""
        source = inspect.getsource(api_me)
        assert "verify_answer" not in source
        assert "attempt_grading_shadow_report" not in source

    def test_gradability_ceiling_symbols_not_wired_into_live_path(self) -> None:
        """REC-05 채점가능성 분류기도 api/me.py에 배선되지 않았음(acceptance③ 승계 확인).

        모듈명 검사(위 테스트)로 이미 충분하나, 신규 심볼 이름으로 스코프 계약을 리뷰어가
        바로 확인할 수 있게 실행 가능한 증거로 남긴다.
        """
        source = inspect.getsource(api_me)
        assert "classify_gradability" not in source
        assert "GradabilityCeilingReport" not in source
        assert "build_gradability_ceiling_report" not in source

    def test_mastery_propagation_still_takes_client_is_correct(self) -> None:
        """두 mastery 전파 콜사이트가 여전히 body.is_correct를 그대로 넘김(권위 이관 아님)."""
        submit_source = inspect.getsource(api_me.submit_attempt)
        concept_call = re.search(
            r"record_problem_attempt_mastery\(\s*session,\s*user\.user_id,\s*"
            r"body\.problem_id,\s*body\.is_correct\s*\)",
            submit_source,
        )
        skill_call = re.search(
            r"record_problem_attempt_skill_mastery\(\s*session,\s*user\.user_id,\s*"
            r"body\.problem_id,\s*body\.is_correct\s*\)",
            submit_source,
        )
        assert concept_call is not None, "개념 숙달 전파 콜사이트가 body.is_correct를 넘기지 않음"
        assert skill_call is not None, "스킬 숙달 전파 콜사이트가 body.is_correct를 넘기지 않음"


# ──────────────────────────────────────────────────────────────────────────
# acceptance⑤ — 변별력 discriminating 테스트(실 PostgreSQL 필요)
# ──────────────────────────────────────────────────────────────────────────
_SECRET_SETTINGS = Settings()


async def _pg_reachable() -> bool:
    engine = create_async_engine(_SECRET_SETTINGS.database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


async def _add_all(*objs: object) -> None:
    engine = create_async_engine(_SECRET_SETTINGS.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add_all(list(objs))
            await session.commit()
    finally:
        await engine.dispose()


async def _cleanup(user_id: uuid.UUID, problem_id: uuid.UUID) -> None:
    """FK 순서(자식→부모): problem_attempt → problem → user_profile."""
    engine = create_async_engine(_SECRET_SETTINGS.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM problem_attempt WHERE user_id = :uid"), {"uid": str(user_id)}
            )
            await conn.execute(
                text("DELETE FROM problem WHERE problem_id = :pid"), {"pid": str(problem_id)}
            )
            await conn.execute(
                text("DELETE FROM user_profile WHERE user_id = :uid"), {"uid": str(user_id)}
            )
    finally:
        await engine.dispose()


def _user(uid: uuid.UUID) -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=uid, persona_primary=Persona.A_일반고고3)
    )


def _problem_orm(pid: uuid.UUID) -> ProblemORM:
    suffix = pid.hex[:8]
    return ProblemORM.from_schema(_problem_with_id(pid, suffix))


def _problem_with_id(pid: uuid.UUID, suffix: str) -> Problem:
    return Problem(
        problem_id=pid,
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.공통,
        unit_codes=[f"U-{suffix}"],
        conditions_parsed=[_cond("2*x - 6")],
        answer="3",
    )


def _attempt(
    aid: uuid.UUID,
    uid: uuid.UUID,
    pid: uuid.UUID,
    *,
    student_answer: str,
    is_correct: bool,
) -> ProblemAttempt:
    return ProblemAttempt(
        attempt_id=aid,
        user_id=uid,
        problem_id=pid,
        student_answer=student_answer,
        is_correct=is_correct,
        ended_at=None,
    )


@pytest.mark.integration
class TestDiscriminatingMismatchCounter:
    """acceptance⑤ — 의도적 불일치 주입 → 카운터 실측 증가 → 복원 → 원복 실측(변별력 증명).

    단일 이벤트 루프 내에서 전 과정을 `await`한다(asyncio_mode=auto가 이 `async def` 테스트를
    그대로 코루틴으로 실행) — 헬퍼별로 `asyncio.run()`을 반복 호출하면 각 호출이 *새 이벤트
    루프*를 열어, 먼저 만든 엔진의 커넥션 풀이 죽은 루프에 바인딩된 채 재사용되며
    "Event loop is closed"/"attached to a different loop"로 깨진다(`db/session.py`
    `db_disable_pool` 독스트링이 경고하는 바로 그 실패 모드).
    """

    async def test_mismatch_counter_rises_and_falls_with_injected_disagreement(self) -> None:
        if not await _pg_reachable():
            pytest.skip("PostgreSQL 미도달 — 통합 테스트 건너뜀(WHYMATH_DATABASE_URL 확인)")

        uid = uuid.uuid4()
        pid = uuid.uuid4()
        aid1 = uuid.uuid4()
        aid2 = uuid.uuid4()

        try:
            # 1. 사용자 + 검산 가능 문항(2*x-6=0, 정답 x=3) 시딩.
            await _add_all(_user(uid), _problem_orm(pid))

            # 2. 정상 attempt(학생 답 3=정답, 클라도 True → 서버판정 pass, 불일치 0).
            await _add_all(_attempt(aid1, uid, pid, student_answer="3", is_correct=True))

            engine = create_async_engine(_SECRET_SETTINGS.database_url)
            try:
                sm = async_sessionmaker(engine, expire_on_commit=False)

                async def _report() -> object:
                    async with sm() as session:
                        records = await fetch_attempt_records(session, user_id=uid)
                    return build_report(records)

                report_before = await _report()
                assert report_before.verifiable_count == 1
                assert report_before.client_grade_mismatch_count == 0

                # 3. 의도적으로 어긋난 attempt 주입: 학생 답 3(=정답, 서버판정 pass)인데
                #    클라는 is_correct=False로 오보고 → 불일치 1건 발생해야 함.
                await _add_all(_attempt(aid2, uid, pid, student_answer="3", is_correct=False))
                report_injected = await _report()
                assert report_injected.verifiable_count == 2
                assert (
                    report_injected.client_grade_mismatch_count
                    == report_before.client_grade_mismatch_count + 1
                ), "의도적으로 주입한 불일치가 카운터에 반영되지 않음(변별력 없음)"

                # 4. 주입한 attempt 제거 → 원복 실측(같은 값으로 돌아옴).
                async with sm() as session:
                    await session.execute(
                        text("DELETE FROM problem_attempt WHERE attempt_id = :aid"),
                        {"aid": str(aid2)},
                    )
                    await session.commit()

                report_restored = await _report()
                assert (
                    report_restored.client_grade_mismatch_count
                    == report_before.client_grade_mismatch_count
                )
                assert report_restored.verifiable_count == report_before.verifiable_count
            finally:
                await engine.dispose()
        finally:
            await _cleanup(uid, pid)


# ──────────────────────────────────────────────────────────────────────────
# NLP-05 acceptance — 코퍼스 verify 블록 입력 공급
# ──────────────────────────────────────────────────────────────────────────
class TestCorpusVerifyBlockSupply:
    """`derive_verify_inputs`가 `Problem.conditions_parsed` 외에 코퍼스 verify 블록을 공급원으로 쓴다."""

    def test_loads_real_corpus_verify_blocks(self) -> None:
        """코퍼스 로더가 13,570개의 유효한 verify 블록을 읽는다.

        2,124(NLP-05 실측) → 13,520. 증분 11,446은 PB-13이 회수한 저작 확장 코퍼스
        30종의 문항수와 **정확히 일치**한다(우연한 드리프트가 아니라 회수의 산술 결과).
        """
        blocks = _load_corpus_verify_blocks()
        assert len(blocks) == 13520

    def test_corpus_slug_derives_when_conditions_parsed_empty(self) -> None:
        """DB conditions_parsed가 비어 있어도 코퍼스 slug 매칭 시 파생 재료가 생긴다.

        표본은 *파생 가능한* 첫 블록으로 고정한다 — dict 선두는 코퍼스 구성이 바뀌면
        따라 바뀌고(PB-13 회수로 실제로 바뀌었다), 그때 파생 불가 블록이 선두에 오면
        이 테스트가 '파생 경로 고장'이 아니라 '표본 추첨 결과'로 실패한다.
        파생 불가 모집단 자체는 test_multi_symbol_population_is_frozen이 따로 동결한다.
        """
        blocks = _load_corpus_verify_blocks()
        slug, (expected_conditions, expected_answer_map) = next(
            (s, v)
            for s, v in blocks.items()
            if derive_verify_inputs(_problem(conditions=[], answer="3", slug=s)) is not None
        )
        problem = _problem(conditions=[], answer="3", slug=slug)
        result = derive_verify_inputs(problem)
        assert result is not None
        conditions, answer_map = result
        assert conditions == expected_conditions
        assert answer_map == expected_answer_map

    def test_multi_symbol_population_is_frozen(self) -> None:
        """파생 불가 블록 **0건** — NLP-09가 7,048건을 전량 회수했다.

        경위(이 테스트가 개선을 수치로 증명하는 계량기다 · NLP-09 acceptance④):
          · NLP-05 시점 — 코퍼스 2,124블록, 파생 성공률 100%.
          · PB-13 회수 후 — 13,520블록 중 6,472건만 파생(47.9%). 실패 7,048건은 전량
            단일 사유 `multi_symbol`이었고 `no_verify_block`·`parse_error`는 0이었다.
          · NLP-09 실측 — 그 7,048건 중 **진짜 다중 미지수는 0건**이었다. 전량 단일
            미지수이고 이름이 `y`일 뿐이다(`4*1/5 = y`). 즉 데이터 결함이 아니라
            파생기가 미지수 이름을 `x`로 못 박은 것이 원인이었다.
          · 파생 게이트를 이름에서 개수로 옮긴 뒤 → **13,520/13,520 (100.0%)**.

        0을 동결하는 이유는 7,048을 동결했던 이유와 같다. 그때는 "회수분의 62%가 섀도 채점
        경로에서 소비되지 않는다"가 조용히 묻히는 것을 막았고, 지금은 그 62%가 **다시**
        비파생으로 돌아가는 회귀를 막는다. 사유 딕셔너리 자체를 비교하므로, 새 실패 사유가
        하나라도 생기면 건수와 무관하게 red다.
        """
        blocks = _load_corpus_verify_blocks()
        reasons: dict[str, int] = {}
        for slug in blocks:
            problem = _problem(conditions=[], answer="3", slug=slug)
            if derive_verify_inputs(problem) is None:
                reason = _derive_from_corpus(problem)
                reasons[reason] = reasons.get(reason, 0) + 1
        assert reasons == {}

    def test_corpus_answer_map_key_must_match_condition_symbol(self) -> None:
        """답산맵 키가 조건식의 자유기호와 **다르면** 비파생 — NLP-09가 새로 닫은 구멍.

        이전 코퍼스 경로는 자유기호를 아예 보지 않고 키가 `{"x"}`인지만 봤다. 그래서
        `answer_map {"x": ...}` + `conditions "y + 1 = 0"` 같은 어긋난 짝이 통과했고,
        학생 답은 `x`에 들어가는데 `y`는 미결 자유기호로 남았다 — 모듈 docstring이
        경고하는 "엉뚱한 변수" 사고가 정확히 이 형태다.

        실측상 현재 코퍼스에는 이런 블록이 0건이지만, 0건이라는 것은 **이 절이 실제로
        밟히는 픽스처가 없다**는 뜻이기도 하다. 그러면 절을 지워도 전건 초록이 나온다.
        그래서 이 픽스처가 그 반례를 직접 만든다.
        """
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        fake_blocks = {"wm-key-symbol-mismatch": (["y + 1 = 0"], {"x": "-1"})}
        mod._load_corpus_verify_blocks.cache_clear()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(mod, "_load_corpus_verify_blocks", lambda: fake_blocks)
                problem = _problem(conditions=[], answer="-1", slug="wm-key-symbol-mismatch")
                assert derive_verify_inputs(problem) is None
                assert _derive_from_corpus(problem) == "multi_symbol"
        finally:
            mod._load_corpus_verify_blocks.cache_clear()

    def test_corpus_condition_parsing_to_bare_bool_is_not_derivable(self) -> None:
        """코퍼스 경로에서도 자유기호를 물을 수 없는 조건은 비파생이다.

        DB 경로 쪽 짝은 `test_formal_parsing_to_bare_bool_returns_none`이다. 두 경로가
        `_free_symbol_names`의 `None`을 각각 따로 처리하므로 픽스처도 각각 필요하다 —
        한쪽만 두면 다른 쪽 절이 뮤테이션에서 살아남는다.
        """
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        fake_blocks = {"wm-bare-bool": (["True"], {"x": "1"})}
        mod._load_corpus_verify_blocks.cache_clear()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(mod, "_load_corpus_verify_blocks", lambda: fake_blocks)
                problem = _problem(conditions=[], answer="1", slug="wm-bare-bool")
                assert derive_verify_inputs(problem) is None
                assert _derive_from_corpus(problem) == "multi_symbol"
        finally:
            mod._load_corpus_verify_blocks.cache_clear()

    def test_corpus_unparseable_condition_is_parse_error_not_absence(self) -> None:
        """코퍼스 조건이 파싱 불가면 사유는 `parse_error` — 부재(`no_verify_block`)가 아니다.

        둘의 차이는 "블록이 없다"(정상·데이터 상태)와 "블록은 있는데 우리가 못 읽었다"
        (측정 실패)다. 후자를 전자로 접으면 파서 결함이 사유 집계에서 사라진다.

        기존 `test_parse_error_reason_counted`는 **DB 경로**(`conditions_parsed`)를 밟으므로
        코퍼스 경로의 같은 절을 대신 검사하지 못한다 — 뮤테이션 M9이 그 공백에서 살아남아
        드러났다. 경로가 둘이면 픽스처도 둘이다.
        """
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        fake_blocks = {"wm-unparseable": (["2*x +* 6"], {"x": "1"})}
        mod._load_corpus_verify_blocks.cache_clear()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(mod, "_load_corpus_verify_blocks", lambda: fake_blocks)
                problem = _problem(conditions=[], answer="1", slug="wm-unparseable")
                assert derive_verify_inputs(problem) is None
                assert _derive_from_corpus(problem) == "parse_error"
        finally:
            mod._load_corpus_verify_blocks.cache_clear()

    def test_corpus_non_x_unknown_derives_with_its_own_key(self) -> None:
        """코퍼스 블록의 미지수가 `y`여도 파생하고, 키는 코퍼스가 적어 둔 `y` 그대로다.

        회수 7,048건의 대표 형태(`4*1/5 = y`)를 단위 수준에서 고정한다 — 모집단 동결
        테스트는 "몇 건인가"를, 이 테스트는 "무엇이 나오는가"를 잰다.
        """
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        fake_blocks = {"wm-single-y": (["4*1/5 = y"], {"y": "4/5"})}
        mod._load_corpus_verify_blocks.cache_clear()
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(mod, "_load_corpus_verify_blocks", lambda: fake_blocks)
                problem = _problem(conditions=[], answer="4/5", slug="wm-single-y")
                result = derive_verify_inputs(problem)
                assert result == (["4*1/5 = y"], {"y": "4/5"})
        finally:
            mod._load_corpus_verify_blocks.cache_clear()

    def test_unknown_slug_returns_no_verify_block(self) -> None:
        """코퍼스에 없는 slug는 verify 블록 공급 없이 비파생이다."""
        problem = _problem(conditions=[], answer="3", slug="wm-definitely-not-in-corpus-12345")
        assert derive_verify_inputs(problem) is None
        assert _derive_from_corpus(problem) == "no_verify_block"

    def test_corpus_single_equals_condition_is_parseable(self) -> None:
        """코퍼스 conditions의 단일 `=`(`x**2 - 5*x = 0`)도 verify_answer 수준으로 파생 가능."""
        problem = _problem(conditions=[], answer="5", slug="wm-skel-d782cf61cf93")
        result = derive_verify_inputs(problem)
        assert result is not None
        assert result[0] == ["x**2 - 5*x = 0"]
        assert result[1] == {"x": "5"}

    def test_corpus_multi_symbol_answer_map_returns_none(self, monkeypatch) -> None:
        """answer_map 키가 {"x"}가 아니면 비파생 — 다중 미지수는 스코프 밖."""
        from whymath_backend.harness import attempt_grading_shadow_report as mod

        fake_blocks = {"wm-multi-x-y": (["x + y - 3"], {"x": "1", "y": "2"})}
        monkeypatch.setattr(mod, "_load_corpus_verify_blocks", lambda: fake_blocks)
        problem = _problem(conditions=[], answer="1", slug="wm-multi-x-y")
        assert derive_verify_inputs(problem) is None

    def test_numeric_short_answer_with_corpus_becomes_bucket_c(self) -> None:
        """단답형·수치 answer_format이라도 코퍼스 verify 블록이 있으면 C버킷( symbolic)으로 계상."""
        problem = _problem(
            conditions=[],
            answer="5",
            slug="wm-skel-d782cf61cf93",
            question_format=QuestionFormat.단답형,
            answer_format=AnswerFormat.자연수,
        )
        assert classify_gradability(problem) == "condition_formal_derivable"


class TestCorpusCeilingReportDiscriminates:
    """NLP-05 acceptance④ — 코퍼스 verify 블록 공급으로 C버킷이 0에서 실제로 오른다."""

    def test_c_bucket_toggles_with_corpus_derived_problem(self) -> None:
        baseline = [
            _problem(choices=["1", "2"], answer="1"),
            _problem(choices=None, answer="서술", conditions=[]),
        ]
        before = build_gradability_ceiling_report(baseline)
        assert before.bucket_counts["condition_formal_derivable"] == 0

        corpus_derived = _problem(
            conditions=[],
            answer="5",
            slug="wm-skel-d782cf61cf93",
            question_format=QuestionFormat.단답형,
            answer_format=AnswerFormat.자연수,
        )
        after_inject = build_gradability_ceiling_report([*baseline, corpus_derived])
        assert after_inject.bucket_counts["condition_formal_derivable"] == 1

        after_remove = build_gradability_ceiling_report(baseline)
        assert after_remove.bucket_counts["condition_formal_derivable"] == 0

    def test_full_corpus_snapshot_has_nonzero_c_bucket(self) -> None:
        """실제 코퍼스 전 bank를 Problem 스키마로 읽어 ceiling 리포트를 돌리면 C > 0.

        C버킷(조건 기반 symbolic 파생) 스냅샷: **5,220 → 12,268**(NLP-09 · +7,048).
        증분은 파생 게이트가 미지수 이름 `x` 하드코딩을 버리고 개수로 판정하게 되면서
        회수된 단일 미지수 `y` 블록 수와 **정확히 일치**한다(우연한 드리프트가 아니라
        `test_multi_symbol_population_is_frozen`이 7,048 → 0으로 간 것의 산술 결과).
        """
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        corpus_root = repo_root / "data" / "corpus"
        problems: list[Problem] = []
        for path in sorted(corpus_root.glob("problem_bank_*/problems.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                record = json.loads(line)
                problems.append(
                    Problem(
                        source_type=SourceType.자체생성,
                        curriculum_version=Curriculum.REVISION_2022,
                        valid_from_year=2022,
                        subject=Subject.공통,
                        unit_codes=["U-CORPUS"],
                        slug=record.get("slug"),
                        answer=record.get("answer"),
                        choices=record.get("choices"),
                        question_format=record.get("question_format"),
                        answer_format=record.get("answer_format"),
                        conditions_parsed=[],
                    )
                )

        report = build_gradability_ceiling_report(problems)
        assert report.total_problems == 14034
        assert report.bucket_counts["condition_formal_derivable"] > 0
        assert report.bucket_counts["condition_formal_derivable"] == 12268
