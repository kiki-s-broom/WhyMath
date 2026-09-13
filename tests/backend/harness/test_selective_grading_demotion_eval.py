"""선택형·수치 단답 채점 강등전 테스트(REC-08) — acceptance①~⑤ 대응.

구성:
  - 정규화·비교기 단위 테스트(순수·DB 0·코퍼스 0)
  - 시더 결정론·결함 주입 테스트(합성 `Problem`로 hermetic)
  - 집계 테스트(분모 없는 0 금지·판정 불가가 오답으로 강등되지 않음)
  - CLI exit 0/1 **양방향** 대조군(변별력 봉인 — `test_defect_detection_eval.py` 관례 답습)
  - 범위 밖 동결(acceptance⑤) — `api/me.py` 미배선 소스 레벨 확인

코퍼스를 읽는 테스트는 `main([...])` 경유 1건뿐이고 나머지는 전부 합성 픽스처다(빠르고 결정론).
"""

from __future__ import annotations

import inspect

import pytest

from whymath_backend.api import me as api_me
from whymath_backend.harness import selective_grading_demotion_eval as ev
from whymath_backend.harness.selective_grading_demotion_eval import (
    FALSE_ALARM_UPPER_CONVENTION,
    BucketHeadroom,
    InsufficientPoolError,
    SelectiveTrial,
    bucket_headroom,
    build_selective_demotion_set,
    format_headroom,
    format_report,
    grade_selective,
    main,
    normalize_choice_answer,
    summarize,
)
from whymath_backend.schema.enums import (
    AnswerFormat,
    Curriculum,
    QuestionFormat,
    SourceType,
    Subject,
)
from whymath_backend.schema.problem import Problem

pytestmark = pytest.mark.filterwarnings("ignore")


# ──────────────────────────────────────────────────────────────────────────
# 헬퍼 — 합성 Problem / SelectiveTrial
# ──────────────────────────────────────────────────────────────────────────
def _mc_problem(slug: str, answer: str, choices: list[str]) -> Problem:
    """A버킷(선택형 정확일치) 문항."""
    return Problem(
        slug=slug,
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.공통,
        unit_codes=["U-TEST"],
        answer=answer,
        choices=choices,
        question_format=QuestionFormat.객관식,
    )


def _sa_problem(slug: str, answer: str) -> Problem:
    """B버킷(수치 단답) 문항."""
    return Problem(
        slug=slug,
        source_type=SourceType.자체생성,
        curriculum_version=Curriculum.REVISION_2022,
        valid_from_year=2022,
        subject=Subject.공통,
        unit_codes=["U-TEST"],
        answer=answer,
        question_format=QuestionFormat.단답형,
        answer_format=AnswerFormat.자연수,
    )


def _trial(
    *,
    bucket: str,
    correct: str,
    submitted: str,
    defect: str | None,
) -> SelectiveTrial:
    return SelectiveTrial(
        slug="s-test",
        bucket=bucket,  # type: ignore[arg-type]
        correct_answer=correct,
        submitted_answer=submitted,
        defect_class=defect,  # type: ignore[arg-type]
    )


# ──────────────────────────────────────────────────────────────────────────
# A버킷 정규화 — 화이트리스트(의미 변형 0)
# ──────────────────────────────────────────────────────────────────────────
class TestNormalizeChoiceAnswer:
    def test_strips_and_collapses_whitespace(self) -> None:
        assert normalize_choice_answer("  3  ") == "3"
        assert normalize_choice_answer("1 /  2") == "1 / 2"

    def test_folds_fullwidth_digits_and_letters(self) -> None:
        assert normalize_choice_answer("３") == "3"
        assert normalize_choice_answer("１／２") == "１／２".replace("１", "1").replace("２", "2")
        assert normalize_choice_answer("Ａ") == "A"
        assert normalize_choice_answer("ａ") == "a"

    def test_does_not_change_meaning_unlike_nfkc(self) -> None:
        """NFKC와 달리 원문자·위첨자를 붕괴시키지 않는다(acceptance② '의미 변형 정규화 0')."""
        # NFKC였다면 '③'→'3'(선지 라벨→선지 값)·'x²'→'x2'(지수 파괴)가 된다.
        assert normalize_choice_answer("③") == "③"
        assert normalize_choice_answer("x²") == "x²"
        assert normalize_choice_answer("½") == "½"


# ──────────────────────────────────────────────────────────────────────────
# 비교기 — A는 정확일치, B는 SymPy 동치(identity_status)
# ──────────────────────────────────────────────────────────────────────────
class TestGradeSelective:
    def test_choice_exact_match_is_correct(self) -> None:
        trial = _trial(bucket="selectable_exact_match", correct="576", submitted="576", defect=None)
        assert grade_selective(trial) == "correct"

    def test_choice_mismatch_is_incorrect(self) -> None:
        trial = _trial(
            bucket="selectable_exact_match",
            correct="576",
            submitted="488",
            defect="distractor_substitution",
        )
        assert grade_selective(trial) == "incorrect"

    def test_choice_fullwidth_and_whitespace_still_correct(self) -> None:
        trial = _trial(
            bucket="selectable_exact_match", correct="576", submitted=" ５７６ ", defect=None
        )
        assert grade_selective(trial) == "correct"

    @pytest.mark.parametrize(
        ("correct", "submitted"),
        [("1/2", "0.5"), ("0.5", "1/2"), ("2", "2.0"), ("-3/2", "-1.5"), ("2", "sqrt(4)")],
    )
    def test_numeric_notation_variants_are_correct(self, correct: str, submitted: str) -> None:
        """표기 변형(분수↔소수↔근호)은 SymPy가 흡수한다 — 새 확률모델 0."""
        trial = _trial(
            bucket="numeric_short_answer_candidate",
            correct=correct,
            submitted=submitted,
            defect=None,
        )
        assert grade_selective(trial) == "correct"

    def test_numeric_approximation_is_incorrect_not_correct(self) -> None:
        """근사값은 정답이 아니다 — 관대하게 통과시키지 않는다."""
        trial = _trial(
            bucket="numeric_short_answer_candidate",
            correct="1/3",
            submitted="0.333",
            defect="answer_shift",
        )
        assert grade_selective(trial) == "incorrect"

    def test_unparseable_submission_is_undecidable_not_incorrect(self) -> None:
        """판정 불가는 오답이 아니다(교수학 금기 승계) — 학생을 틀렸다고 강등하지 않는다."""
        trial = _trial(
            bucket="numeric_short_answer_candidate", correct="3", submitted="½", defect=None
        )
        assert grade_selective(trial) == "undecidable"

    def test_non_numeric_correct_answer_is_undecidable(self) -> None:
        """정답이 수치로 읽히지 않으면 채점 자체를 시도하지 않는다(is_number 게이트)."""
        trial = _trial(
            bucket="numeric_short_answer_candidate",
            correct="서술 답안",
            submitted="3",
            defect=None,
        )
        assert grade_selective(trial) == "undecidable"


# ──────────────────────────────────────────────────────────────────────────
# 시더 — 결정론 + 결함 주입이 실제로 값을 바꾸는가
# ──────────────────────────────────────────────────────────────────────────
def _synthetic_pool() -> list[Problem]:
    mc = [_mc_problem(f"mc-{i}", str(100 + i), [str(100 + i), "1", "2", "3"]) for i in range(40)]
    sa = [_sa_problem(f"sa-{i}", str(200 + i)) for i in range(40)]
    return [*mc, *sa]


class TestBuildSelectiveDemotionSet:
    def test_deterministic_for_same_seed(self) -> None:
        pool = _synthetic_pool()
        a = build_selective_demotion_set(pool, n_defective=10, n_clean=10, seed=7)
        b = build_selective_demotion_set(pool, n_defective=10, n_clean=10, seed=7)
        assert [(t.slug, t.defect_class, t.submitted_answer) for t in a] == [
            (t.slug, t.defect_class, t.submitted_answer) for t in b
        ]

    def test_counts_and_bucket_balance(self) -> None:
        trials = build_selective_demotion_set(_synthetic_pool(), n_defective=10, n_clean=10, seed=7)
        assert len(trials) == 20
        defective = [t for t in trials if t.defect_class is not None]
        clean = [t for t in trials if t.defect_class is None]
        assert len(defective) == 10
        assert len(clean) == 10
        # 결함이 한 버킷에 몰리지 않는다(절반씩).
        assert sum(1 for t in defective if t.bucket == "selectable_exact_match") == 5
        assert sum(1 for t in defective if t.bucket == "numeric_short_answer_candidate") == 5

    def test_defective_trials_actually_mutate_the_answer(self) -> None:
        """결함 trial은 제출값이 정답과 반드시 달라야 한다(무변조 결함 = GT 오염)."""
        trials = build_selective_demotion_set(_synthetic_pool(), n_defective=20, n_clean=0, seed=11)
        assert trials
        for trial in trials:
            assert trial.defect_class is not None
            assert trial.submitted_answer != trial.correct_answer, trial

    def test_clean_trials_submit_the_correct_answer(self) -> None:
        trials = build_selective_demotion_set(_synthetic_pool(), n_defective=0, n_clean=20, seed=11)
        assert trials
        for trial in trials:
            assert trial.defect_class is None
            assert trial.submitted_answer == trial.correct_answer

    def test_distractor_substitution_picks_a_non_answer_choice(self) -> None:
        trials = build_selective_demotion_set(_synthetic_pool(), n_defective=10, n_clean=0, seed=3)
        mc_trials = [t for t in trials if t.bucket == "selectable_exact_match"]
        assert mc_trials
        for trial in mc_trials:
            assert trial.defect_class == "distractor_substitution"
            assert trial.submitted_answer != trial.correct_answer

    def test_exhausted_pool_raises_instead_of_silent_partial_set(self) -> None:
        """풀 소진은 조용한 부분 셋이 아니라 예외다(defect_seeder 관례)."""
        with pytest.raises(ValueError, match="풀 소진"):
            build_selective_demotion_set(_synthetic_pool(), n_defective=500, n_clean=0, seed=1)

    def test_exhausted_pool_raises_the_specific_type_not_bare_valueerror(self) -> None:
        """풀 소진은 `InsufficientPoolError`다 — `main()`이 exit 2로 갈라내는 근거(NLP-10).

        위 테스트는 `ValueError`만 보므로 타입을 `ValueError`로 되돌려도 통과한다. 그러면
        `main()`의 `except InsufficientPoolError`가 안 잡히고 아래 일반 절로 떨어진다 —
        지금은 둘 다 exit 2라 종료 코드로도 안 드러난다. 그래서 타입 자체를 동결한다.
        """
        with pytest.raises(InsufficientPoolError) as caught:
            build_selective_demotion_set(_synthetic_pool(), n_defective=500, n_clean=0, seed=1)
        assert caught.value.bucket in {
            "selectable_exact_match",
            "numeric_short_answer_candidate",
        }
        assert caught.value.available == 40  # _synthetic_pool은 버킷당 40건

    def test_defective_and_clean_phases_share_the_cursor(self) -> None:
        """한 문항은 결함·무결함 양쪽에 쓰이지 않는다 — 버킷 소비가 두 단계의 **합**인 근거.

        이 성질이 `_bucket_demand`가 결함분과 무결함분을 더하는 이유다. 커서가 단계마다
        리셋된다면 소비는 max(75,75)=75일 것이고, 여유 계산이 2배로 낙관된다.
        """
        trials = build_selective_demotion_set(_synthetic_pool(), n_defective=20, n_clean=20, seed=5)
        slugs = [t.slug for t in trials]
        assert len(slugs) == len(set(slugs)), "같은 문항이 두 trial에 재사용됐다"


# ──────────────────────────────────────────────────────────────────────────
# 집계 — 분모 없는 0 금지 · 판정 불가 분리 회계
# ──────────────────────────────────────────────────────────────────────────
class TestSummarize:
    def test_perfect_grader_detects_all_and_no_false_alarm(self) -> None:
        trials = [
            _trial(
                bucket="selectable_exact_match",
                correct="1",
                submitted="2",
                defect="distractor_substitution",
            ),
            _trial(bucket="selectable_exact_match", correct="1", submitted="1", defect=None),
        ]
        report = summarize(trials)
        assert report.defective_detected == 1
        assert report.defective_total == 1
        assert report.false_alarm == 0
        assert report.clean_total == 1

    def test_empty_denominator_bounds_are_none(self) -> None:
        report = summarize([])
        assert report.detection_lower_bound() is None
        assert report.false_alarm_upper_bound() is None

    def test_undecidable_on_defective_counts_as_missed_not_detected(self) -> None:
        """모른다고 답한 것은 잡은 게 아니다(보수적)."""
        trials = [
            _trial(
                bucket="numeric_short_answer_candidate",
                correct="서술",
                submitted="3",
                defect="answer_shift",
            )
        ]
        report = summarize(trials)
        assert report.defective_detected == 0
        assert report.undecidable_defective == 1

    def test_undecidable_on_clean_is_not_a_false_alarm(self) -> None:
        """판정 불가는 학생을 틀렸다고 한 것이 아니다 — 오검출로 세지 않는다."""
        trials = [
            _trial(
                bucket="numeric_short_answer_candidate",
                correct="서술",
                submitted="서술",
                defect=None,
            )
        ]
        report = summarize(trials)
        assert report.false_alarm == 0
        assert report.undecidable_clean == 1

    def test_report_to_json_structure(self) -> None:
        report = summarize(
            [_trial(bucket="selectable_exact_match", correct="1", submitted="1", defect=None)]
        )
        payload = report.to_json()
        assert payload["clean_total"] == 1
        assert payload["detection_lower_bound"] is None  # 결함 표본 0
        assert payload["false_alarm_upper_bound"] is not None


class TestFormatReport:
    def test_states_threshold_is_a_project_convention_not_literature(self) -> None:
        """임계 근거를 정직 표기한다 — 문헌값으로 위장하지 않는다(acceptance③)."""
        rendered = format_report(summarize([]), confidence=0.95)
        assert str(FALSE_ALARM_UPPER_CONVENTION) in rendered
        assert "규약 채용" in rendered

    def test_states_authority_is_not_transferred(self) -> None:
        """범위 밖 동결(acceptance⑤)이 리포트 본문에 명시된다."""
        rendered = format_report(summarize([]), confidence=0.95)
        assert "권위는 이관되지 않는다" in rendered


# ──────────────────────────────────────────────────────────────────────────
# CLI exit 0/1 — 양방향 변별력 봉인(대조군)
# ──────────────────────────────────────────────────────────────────────────
class TestCliGate:
    def test_gate_off_by_default_returns_zero(self) -> None:
        assert main(["--n-defective", "6", "--n-clean", "6"]) == 0

    def test_gate_passes_with_realistic_thresholds(self) -> None:
        """실측 여유값(n=150에서 검출 하한 0.982·오검출 상한 0.018)의 축소판."""
        assert (
            main(
                [
                    "--n-defective",
                    "40",
                    "--n-clean",
                    "40",
                    "--min-detection-lower",
                    "0.90",
                ]
            )
            == 0
        )

    def test_gate_fails_on_unreachable_detection_threshold(self) -> None:
        """대조군 — 임계를 도달 불가로 올리면 실제로 exit 1이 나온다(변별력 앵커)."""
        assert main(["--n-defective", "10", "--n-clean", "10", "--min-detection-lower", "1.0"]) == 1

    def test_gate_fails_when_sample_too_small_to_prove_upper_bound(self) -> None:
        """표본이 작으면 오검출 0건이어도 상한을 증명 못 해 실패한다(작은 표본 거짓 통과 차단)."""
        assert (
            main(["--n-defective", "10", "--n-clean", "10", "--max-false-alarm-upper", "0.02"]) == 1
        )


# ──────────────────────────────────────────────────────────────────────────
# NLP-10 — 표본 수급: 판정 불가(exit 2)와 기준 미달(exit 1)의 분리
# ──────────────────────────────────────────────────────────────────────────
class TestSamplePopulationFloor:
    """모집단이 말라 게이트를 못 돌리는 상태가 '채점기 회귀'로 읽히지 않게 한다.

    발단(NLP-09 실측): 파생 게이트 일반화로 B버킷이 7,130 → 154로 줄었다. 요구는 150이라
    여유가 **4건**이다. 그 개선은 게이트를 깨뜨릴 의도가 전혀 없는 정상 작업이었고, 다음
    개선은 예고 없이 깬다.
    """

    def test_demand_counts_both_phases_not_just_one(self) -> None:
        """버킷 요구량은 결함분 + 무결함분이다 — 한 단계만 세면 여유가 2배로 낙관된다.

        이것이 NLP-10 등재 당시 내가 실제로 저지른 오독이다("여유 2배"라고 적었는데
        실측은 4건이었다). 산식을 테스트로 고정해 같은 오독이 코드로 들어오지 못하게 한다.
        """
        rows = {r.bucket: r for r in bucket_headroom(_synthetic_pool(), n_defective=10, n_clean=10)}
        # 짝수 index → A, 홀수 → B. 각 단계 10건이면 버킷당 5건씩, 두 단계 합쳐 10건.
        assert rows["selectable_exact_match"].required == 10
        assert rows["numeric_short_answer_candidate"].required == 10

    def test_headroom_pool_matches_what_the_builder_actually_sees(self) -> None:
        """여유 계산의 풀과 셋 구성의 풀이 같아야 한다 — 다르면 경고가 위장이 된다.

        `_synthetic_pool`은 버킷당 40건이므로, 요구 40에서는 여유 0(가능)이고 41에서는
        음수(불가)여야 한다. 그리고 그 경계가 실제 builder의 경계와 일치해야 한다.
        """
        pool = _synthetic_pool()
        exactly = {r.bucket: r for r in bucket_headroom(pool, n_defective=40, n_clean=40)}
        assert exactly["selectable_exact_match"].headroom == 0
        assert exactly["selectable_exact_match"].sufficient
        # 여유 0이면 builder도 성공해야 한다(경고와 실제가 어긋나지 않는다).
        assert len(build_selective_demotion_set(pool, n_defective=40, n_clean=40, seed=7)) == 80

        over = {r.bucket: r for r in bucket_headroom(pool, n_defective=42, n_clean=42)}
        assert not over["selectable_exact_match"].sufficient
        with pytest.raises(InsufficientPoolError):
            build_selective_demotion_set(pool, n_defective=42, n_clean=42, seed=7)

    def test_headroom_excludes_problems_the_builder_cannot_use(self) -> None:
        """`answer`·`slug`가 없는 문항은 가용 풀이 아니다 — builder가 안 쓰기 때문이다.

        `_synthetic_pool`은 전건이 둘 다 갖고 있어 이 절을 **한 번도 밟지 않는다**. 실제로
        뮤테이션에서 `and problem.answer and problem.slug`를 지웠는데 43건이 전부 통과했다
        (CLAUDE.md "픽스처가 그 절을 실제로 밟는가"). 그래서 반례를 직접 만든다 — 이 절이
        없으면 여유가 실제보다 크게 보고되어, 경고가 켜져야 할 때 안 켜진다.
        """
        usable = _synthetic_pool()
        # 두 하위 절(`problem.answer`·`problem.slug`)을 각각 밟는 반례를 따로 둔다.
        # **둘 다 B버킷이어야 한다** — 첫 시도에서 answer 없는 *객관식*을 썼는데, 그것은
        # `classify_gradability`가 이미 `unclassified`로 물려서 이 절에 닿지도 않았다
        # (실측: answer=""/None 객관식 → unclassified · answer=None 단답형 → B버킷).
        # 이름이 의도를 말한다고 코드가 그 의도를 실행하는 것은 아니다.
        no_answer = _sa_problem("sa-no-answer", "")
        no_answer = no_answer.model_copy(update={"answer": None})
        no_slug = _sa_problem("", "999")
        assert ev.classify_gradability(no_answer) == "numeric_short_answer_candidate"
        assert ev.classify_gradability(no_slug) == "numeric_short_answer_candidate"

        base = {r.bucket: r.available for r in bucket_headroom(usable, n_defective=2, n_clean=2)}
        padded = {
            r.bucket: r.available
            for r in bucket_headroom([*usable, no_answer, no_slug], n_defective=2, n_clean=2)
        }
        assert padded == base, "쓸 수 없는 문항이 가용 풀에 계상됐다"

    def test_tight_flags_shrinking_headroom_before_it_breaks(self) -> None:
        """아직 되지만 곧 안 되는 상태를 `tight`으로 구분한다 — 사후 진단이 아니라 예고."""
        plenty = BucketHeadroom(bucket="selectable_exact_match", available=1000, required=150)
        assert plenty.sufficient and not plenty.tight

        tight = BucketHeadroom(bucket="numeric_short_answer_candidate", available=154, required=150)
        assert tight.sufficient and tight.tight  # 실제 NLP-09 이후 상태

        broken = BucketHeadroom(
            bucket="numeric_short_answer_candidate", available=100, required=150
        )
        assert not broken.sufficient
        assert not broken.tight  # 이미 부족한 것은 '경고'가 아니라 '실패'다(분류 혼선 금지)

    def test_headroom_report_always_prints_the_denominator(self) -> None:
        """0건도 값으로 읽히게 — 가용·요구·여유를 항상 낸다(분모 없는 0 금지)."""
        rendered = format_headroom(bucket_headroom(_synthetic_pool(), n_defective=10, n_clean=10))
        assert "가용" in rendered and "최소요구" in rendered and "여유" in rendered
        assert "selectable_exact_match" in rendered
        assert "numeric_short_answer_candidate" in rendered

    def test_cli_actually_prints_the_headroom_report(self, capsys) -> None:
        """집행 지점 — `main()`이 그 리포트를 **실제로 낸다**(정본화 ≠ 집행).

        위 테스트는 `format_headroom`을 직접 부르므로, CLI에서 그 호출을 통째로 지워도
        통과한다(뮤테이션 실측: 43건 전건 GREEN). 계약을 만들어 놓고 서빙 경로가 안 부르는
        상태를 CLAUDE.md가 "정본화를 집행으로 착각한 완료 선언"이라 부른다 — 여기서 막는다.
        """
        main(["--n-defective", "6", "--n-clean", "6"])
        out = capsys.readouterr().out
        assert "[표본 수급" in out
        assert "최소요구" in out

    def test_insufficient_population_exits_2_not_1(self) -> None:
        """[결함 주입] 표본이 모자라면 exit **2**(판정 불가) — exit 1(기준 미달)이 아니다.

        이 한 줄이 이 태스크의 본체다. 같은 코드로 뭉치면 표본 부족이 채점기 회귀로 읽히고,
        가장 자연스러운 처방(`--n-*` 낮추기)이 게이트를 공허하게 만든다.
        """
        assert main(["--n-defective", "100000", "--n-clean", "100000"]) == 2

    def test_insufficient_population_says_do_not_lower_n(self, capsys) -> None:
        """실패 메시지가 **틀린 처방을 명시적으로 막는다** — 종료 코드만으론 사람이 안 읽는다."""
        main(["--n-defective", "100000", "--n-clean", "100000"])
        err = capsys.readouterr().err
        assert "판정 불가" in err
        assert "게이트 실패가 아니다" in err
        assert "낮추지 말 것" in err

    def test_sufficient_population_still_exits_0(self) -> None:
        """[대조군] 표본이 충분하면 exit 0 — 과잉 정지가 아님을 봉인한다.

        이 대조군이 없으면 "무조건 exit 2"라는 과잉 수정이 위 두 테스트를 통과한다
        (CLAUDE.md v0.2.20 — 실패 방향만 검사하면 과잉 차단이 안 잡힌다).
        """
        assert main(["--n-defective", "6", "--n-clean", "6"]) == 0

    def test_gate_failure_still_exits_1_when_population_is_fine(self) -> None:
        """[대조군] 모집단이 멀쩡하면 기준 미달은 여전히 exit 1이다 — 두 신호가 안 섞인다."""
        assert main(["--n-defective", "10", "--n-clean", "10", "--min-detection-lower", "1.0"]) == 1


# ──────────────────────────────────────────────────────────────────────────
# acceptance⑤ — 범위 밖 동결(권위 이관 0)
# ──────────────────────────────────────────────────────────────────────────
class TestScopeFrozen:
    def test_grader_not_wired_into_live_request_path(self) -> None:
        """이 강등전의 채점기가 `api/me.py`에 배선되지 않았음(권위 이관 아님)."""
        source = inspect.getsource(api_me)
        assert "selective_grading_demotion_eval" not in source
        assert "grade_selective" not in source

    def test_module_reads_no_database(self) -> None:
        """hermetic — 이 모듈은 DB 세션을 물지 않는다(코퍼스 JSONL만 읽는다)."""
        source = inspect.getsource(ev)
        assert "get_session" not in source
        assert "AsyncSession" not in source
