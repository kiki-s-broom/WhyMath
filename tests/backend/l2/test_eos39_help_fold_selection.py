"""EOS-39 — 코치 도움 완료를 추천 **표적**에서 실패 1건으로 접는 규칙 (hermetic · DB 0).

결함(판정문 `docs/reviews/eos39_app_help_completion_selection_judgment_2026-10-06.md` §1): 앱 학생의
추천열이 학생 행동에 반응하지 않았다. 도움을 받아 완료해도 `is_correct=True` 행이 독립 성공과 똑같이
표적을 올렸고, EOS-146 이후 "오답 행 + 도움 완료 행"이 쌓여도 추정기가 그것을 "반반 맞힌 문항"으로 읽어
표적이 내려오지 않았다. 판정은 **추정기를 그대로 두고** 표적용 응답에서 도움을 쓴 문항을 **문항 단위
실패 1건**으로 접는 것이다(`l2.irt.selection_evidence`).

이 파일의 두 반쪽(EOS-147 테스트와 같은 구도):

① **바뀌는 것** — 접기 규칙(문항 단위·오답 행이 있어도 실패 1건·미상은 정답·도움 없이 고친 문항은 한
   쌍)과 하한 사다리(도움 접기가 만든 전부 실패에만), 로더 결선, 킬 스위치, 처치 기록의 계측 키.
② **바뀌지 않는 것** — 추정 θ·SE·`measurement_sufficient`·`administered_count`(어느 라벨이어도 같다),
   **실제 오답만 있는 이력의 하한(−4.0)**(R3·R6 기준선 — 판정문 §4-4 이월), 킬 스위치가 꺼졌을 때의
   종전 동작.

**기대값은 전부 리터럴이다**(MISC-30 교훈 — 상수를 읽어 기대값을 만들면 그 상수를 바꾸는 뮤테이션을
테스트가 따라 움직인다). 난이도 라벨 L의 b는 L − 3이다(`difficulty_to_logit`): 라벨 2.9 → b = −0.1,
3.0 → 0.0, 4.5 → 1.5. 하한 사다리는 `max(−4.0, min(0.0, 실패한 최저 b − 0.5))`다.
변별력은 `scripts/analysis/mutate_eos39_help_fold_guards.py`가 뮤테이션으로 확인한다.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.l2.irt import (
    IrtItem,
    SelectionAttempt,
    ability_for_help_folded_selection,
    ability_for_selection,
    estimate_ability,
    selection_evidence,
)
from whymath_backend.l2.next_problem_selection import (
    AttemptHistoryState,
    load_attempt_history_state,
)
from whymath_backend.l2.recommendation_evidence import (
    META_KEY_SELECTION_HELP_COUNT,
    META_KEY_SELECTION_HINT_UNKNOWN_COUNT,
    META_KEY_SELECTION_THETA,
    record_recommendation_treatment,
)

_ABS = 1e-9


def _item(b: float) -> IrtItem:
    return IrtItem(difficulty=b)


def _att(key: str, b: float, correct: bool, used_hint: bool | None) -> SelectionAttempt:
    return SelectionAttempt(key, _item(b), correct, used_hint)


def _pairs(evidence_responses: list[tuple[IrtItem, bool]]) -> list[tuple[float, bool]]:
    return [(item.difficulty, correct) for item, correct in evidence_responses]


# ══════════════════════════════════════════════════════════════════════════
# ① 접기 규칙 — `selection_evidence`
# ══════════════════════════════════════════════════════════════════════════
class TestSelectionEvidence:
    def test_independent_success_is_kept_as_correct(self) -> None:
        ev = selection_evidence([_att("p", -0.1, True, False)])
        assert _pairs(ev.responses) == [(-0.1, True)]
        assert ev.help_failure_count == 0 and ev.hint_unknown_count == 0

    def test_help_completion_is_folded_into_one_failure(self) -> None:
        """도움을 쓴 문항(`used_hint=True`인 정답)은 실패 응답 1건이다 — 규칙의 핵심."""
        ev = selection_evidence([_att("p", -0.1, True, True)])
        assert _pairs(ev.responses) == [(-0.1, False)]
        assert ev.help_failure_count == 1

    def test_a_wrong_row_plus_a_help_completion_counts_the_failure_once(self) -> None:
        """EOS-146 이후의 실제 흐름 — 오답 행 + 도움 완료 행이 **같은 문항**이면 실패는 1건이다.

        행 단위로 뒤집으면(초안 `a1`) 이 문항은 [오답, 오답] 두 건이 되거나, 오답 행이 있다는 이유로
        뒤집기를 건너뛰어 [오답, 정답]으로 남는다 — 후자는 효과가 0이다(판정문 §3). 둘 다 틀렸다.
        """
        ev = selection_evidence([_att("p", -0.1, False, None), _att("p", -0.1, True, True)])
        assert _pairs(ev.responses) == [(-0.1, False)]  # 정확히 한 건
        assert ev.help_failure_count == 1

    def test_wrong_then_self_corrected_without_help_stays_a_pair(self) -> None:
        """도움 없이 오답 뒤 스스로 고친 문항은 종전 그대로 오답+정답 한 쌍이다(가치 판단 — §4-5).

        게이트 `G-eos146-disposition` (가): "틀린 뒤 스스로 고치는 것은 Polya의 정상 경로".
        """
        ev = selection_evidence([_att("p", -0.1, False, None), _att("p", -0.1, True, False)])
        assert _pairs(ev.responses) == [(-0.1, False), (-0.1, True)]
        assert ev.help_failure_count == 0

    def test_unknown_hint_attribution_is_counted_as_correct(self) -> None:
        """미상(NULL)은 정답 그대로다 — "모른다 ≠ 아니다". 개수는 계측으로 남는다."""
        ev = selection_evidence([_att("p", -0.1, True, None), _att("q", 0.5, True, None)])
        assert _pairs(ev.responses) == [(-0.1, True), (0.5, True)]
        assert ev.help_failure_count == 0
        assert ev.hint_unknown_count == 2

    def test_unknown_after_a_wrong_row_is_kept_as_a_pair_and_counted(self) -> None:
        ev = selection_evidence([_att("p", -0.1, False, None), _att("p", -0.1, True, None)])
        assert _pairs(ev.responses) == [(-0.1, False), (-0.1, True)]
        assert ev.hint_unknown_count == 1  # 정답 행의 미상만 센다(오답 행은 애초에 NULL이다)

    def test_a_wrong_row_never_triggers_the_fold_even_with_the_flag(self) -> None:
        """`is_correct` 절의 반례 — 오답 행의 `used_hint=True`는 접기 대상이 아니다.

        접기는 "도움을 받아 **완료**했다"는 신호다. 오답 행에 힌트 귀속이 붙어 있어도(현행은 오답 행의
        `used_hint`가 항상 NULL이지만 계약이 그렇게 좁지 않다) 실패가 실패로 한 번 더 접히지 않는다.
        """
        ev = selection_evidence([_att("p", -0.1, False, True)])
        assert _pairs(ev.responses) == [(-0.1, False)]
        assert ev.help_failure_count == 0

    def test_hint_false_is_not_help(self) -> None:
        """`used_hint is True` 절의 반례 — `False`(도움 없이 완료)는 정답 그대로, 미상도 아니다."""
        ev = selection_evidence([_att("p", -0.1, True, False)])
        assert ev.help_failure_count == 0 and ev.hint_unknown_count == 0

    def test_two_completion_rows_of_one_problem_fold_once(self) -> None:
        ev = selection_evidence([_att("p", -0.1, True, False), _att("p", -0.1, True, True)])
        assert _pairs(ev.responses) == [(-0.1, False)]
        assert ev.help_failure_count == 1

    def test_problems_are_folded_independently_and_keep_first_seen_order(self) -> None:
        ev = selection_evidence(
            [
                _att("a", -1.0, True, False),  # 독립 성공
                _att("b", 0.5, True, True),  # 도움 완료 → 실패
                _att("c", 1.5, True, None),  # 미상 → 정답
            ]
        )
        assert _pairs(ev.responses) == [(-1.0, True), (0.5, False), (1.5, True)]
        assert ev.help_failure_count == 1 and ev.hint_unknown_count == 1

    def test_empty_history(self) -> None:
        ev = selection_evidence([])
        assert ev.responses == [] and ev.help_failure_count == 0 and ev.hint_unknown_count == 0

    @pytest.mark.parametrize("seed", range(5))
    def test_result_is_independent_of_row_order(self, seed: int) -> None:
        rows = [
            _att("a", -1.0, True, False),
            _att("b", 0.5, False, None),
            _att("b", 0.5, True, True),
            _att("c", 1.5, True, None),
            _att("d", 0.0, False, None),
            _att("d", 0.0, True, False),
        ]
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        base = selection_evidence(rows)
        got = selection_evidence(shuffled)
        assert sorted(_pairs(got.responses)) == sorted(_pairs(base.responses))
        assert got.help_failure_count == base.help_failure_count == 1
        assert got.hint_unknown_count == base.hint_unknown_count == 1


# ══════════════════════════════════════════════════════════════════════════
# ① 하한 사다리 — 도움 접기가 만든 전부 실패에만
# ══════════════════════════════════════════════════════════════════════════
class TestAbilityForHelpFoldedSelection:
    def test_all_failure_steps_half_a_logit_below_the_failed_difficulty(self) -> None:
        """실패한 최저 b = −1.0 → −1.0 − 0.5 = −1.5."""
        folded = [(_item(-1.0), False)]
        assert ability_for_help_folded_selection(folded) == pytest.approx(-1.5, abs=_ABS)

    def test_the_ladder_never_rises_above_the_cold_start(self) -> None:
        """ "한 단계 아래"가 아니라 `min(콜드스타트, …)`다 — 어려운 문항(b=1.5)에서 실패해도 0.0이다.

        초안의 산문("한 단계 아래")이 이 상한을 빠뜨렸다(비판 #6). 1.5 − 0.5 = 1.0이 아니라 0.0이다.
        """
        folded = [(_item(1.5), False)]
        assert ability_for_help_folded_selection(folded) == pytest.approx(0.0, abs=_ABS)

    def test_uses_the_lowest_failed_difficulty(self) -> None:
        folded = [(_item(0.5), False), (_item(-1.0), False), (_item(1.0), False)]
        assert ability_for_help_folded_selection(folded) == pytest.approx(-1.5, abs=_ABS)

    def test_is_floored_at_the_lower_bound(self) -> None:
        """실패 b = −3.9 → −4.4가 아니라 하한 −4.0이다."""
        folded = [(_item(-3.9), False)]
        assert ability_for_help_folded_selection(folded) == pytest.approx(-4.0, abs=_ABS)

    def test_step_argument_overrides_the_default(self) -> None:
        folded = [(_item(-1.0), False)]
        assert ability_for_help_folded_selection(folded, step=1.0) == pytest.approx(-2.0, abs=_ABS)

    def test_mixed_folded_history_is_the_mle(self) -> None:
        """실패 b=1.0 · 성공 b=−1.0 — 대칭이라 MLE는 정확히 0.0이다(σ(−1)+σ(1)=1)."""
        folded = [(_item(1.0), False), (_item(-1.0), True)]
        assert ability_for_help_folded_selection(folded) == pytest.approx(0.0, abs=1e-6)
        assert ability_for_help_folded_selection(folded) == estimate_ability(folded)

    def test_mixed_folded_history_is_not_the_cold_start(self) -> None:
        """콜드스타트(0.0)와 MLE가 **다른** 혼합 이력 — 위 대칭 사례는 둘이 같아 구별하지 못한다.

        실패 b=1.0 · 성공 b=0.0 → P(θ−1)+P(θ)=1의 해 θ=0.5(두 문항 중점). 실패 b=0.0 · 성공
        b=−1.0 → θ=−0.5. 혼합 가지가 `estimate_ability([])`(=0.0)를 돌려주면 둘 다 깨진다.
        """
        up = [(_item(1.0), False), (_item(0.0), True)]
        down = [(_item(0.0), False), (_item(-1.0), True)]
        assert ability_for_help_folded_selection(up) == pytest.approx(0.5, abs=1e-6)
        assert ability_for_help_folded_selection(down) == pytest.approx(-0.5, abs=1e-6)

    def test_the_real_all_wrong_lower_bound_is_untouched(self) -> None:
        """EOS-147 §4-4 비대칭 동결 — `ability_for_selection`은 전부 오답이면 추정값 그대로다.

        이 사다리는 `ability_for_help_folded_selection` 전용이다(도움 접기가 **일어난** 이력). 실제
        오답만 있는 이력의 하한(−4.0)은 R3·R6 기준선이라 이번에 바꾸지 않았다(판정문 §4-4 — 이월).
        """
        wrong = [(_item(-1.0), False)]
        assert ability_for_selection(wrong, estimate_ability(wrong)) == pytest.approx(
            -4.0, abs=_ABS
        )


# ══════════════════════════════════════════════════════════════════════════
# ① 로더 결선 — 가짜 세션(6열 행)
# ══════════════════════════════════════════════════════════════════════════
class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _HistorySession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)  # 가짜 세션이 쿼리를 무시하는 사각을 막으려고 문장을 붙잡는다
        return _Result(self._rows)


def _row(
    correct: bool | None,
    label: float | None,
    used_hint: bool | None = None,
    problem_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, bool | None, float | None, float | None, float | None, bool | None]:
    """`(problem_id, is_correct, difficulty_overall, irt_difficulty_b, irt_a, used_hint)`."""
    return (problem_id or uuid.uuid4(), correct, label, None, None, used_hint)


async def _load(rows: list[Any]) -> AttemptHistoryState:
    return await load_attempt_history_state(cast(AsyncSession, _HistorySession(rows)), uuid.uuid4())


@pytest.fixture
def fold_disabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """킬 스위치를 끈다 — 환경변수를 **먼저** 지운 뒤 캐시를 비워 다른 테스트로 새지 않게 한다."""
    monkeypatch.setenv("WHYMATH_L2_SELECTION_HELP_FOLD_ENABLED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("WHYMATH_L2_SELECTION_HELP_FOLD_ENABLED", raising=False)
    get_settings.cache_clear()


class TestLoaderFoldsHelpCompletions:
    async def test_help_completion_lowers_the_target_and_independent_success_does_not(
        self,
    ) -> None:
        """같은 이력(라벨 2.9 정답 1건)인데 힌트 귀속만 다르다 — 표적이 갈라진다(규칙의 존재 이유)."""
        independent = await _load([_row(True, 2.9, used_hint=False)])
        helped = await _load([_row(True, 2.9, used_hint=True)])
        # 독립 성공: EOS-147 그대로 — 맞힌 최고 b(−0.1) + 0.5 = 0.4.
        assert independent.selection_theta == pytest.approx(0.4, abs=_ABS)
        assert independent.selection_help_count == 0
        # 도움 완료: 실패 1건 → 하한 사다리 min(0, −0.1 − 0.5) = −0.6.
        assert helped.selection_theta == pytest.approx(-0.6, abs=_ABS)
        assert helped.selection_help_count == 1
        assert helped.selection_theta < independent.selection_theta

    async def test_the_estimate_and_precision_do_not_depend_on_the_hint_label(self) -> None:
        """**추정기 불변**(판정문 §2) — 라벨이 달라도 추정 θ·SE·중단 규칙·응답 수가 바이트 동일하다."""
        independent = await _load([_row(True, 2.9, used_hint=False), _row(True, 3.5, False)])
        helped = await _load([_row(True, 2.9, used_hint=True), _row(True, 3.5, True)])
        assert helped.theta == independent.theta == 4.0
        assert helped.theta_boundary == independent.theta_boundary == "upper"
        assert helped.standard_error == independent.standard_error
        assert helped.measurement_sufficient == independent.measurement_sufficient
        assert helped.administered_count == independent.administered_count == 2
        assert helped.discrimination_applied_count == independent.discrimination_applied_count
        assert helped.attempted_ids != set()  # 후보 필터는 그대로 문항을 제외한다

    async def test_a_wrong_row_and_a_help_completion_of_one_problem_fold_to_one_failure(
        self,
    ) -> None:
        pid = uuid.uuid4()
        state = await _load(
            [_row(False, 2.9, None, pid), _row(True, 2.9, True, pid)]  # EOS-146 이후의 흐름
        )
        # 추정기는 한 문항의 오답+정답을 반반으로 읽는다 → θ = b = −0.1(혼합이라 경계 아님).
        assert state.theta == pytest.approx(-0.1, abs=1e-6)
        assert state.theta_boundary is None
        # 표적용 응답은 그 문항을 실패 **1건**으로 접는다 → 전부 실패 → 사다리 −0.1 − 0.5 = −0.6.
        assert state.selection_theta == pytest.approx(-0.6, abs=_ABS)
        assert state.selection_help_count == 1
        assert state.selection_theta_override == pytest.approx(-0.6, abs=_ABS)

    async def test_self_correction_without_help_is_not_folded(self) -> None:
        pid = uuid.uuid4()
        state = await _load([_row(False, 2.9, None, pid), _row(True, 2.9, False, pid)])
        assert state.theta == pytest.approx(-0.1, abs=1e-6)
        assert state.selection_theta == state.theta  # 접히지 않았다 → 선택 θ = 추정 θ
        assert state.selection_theta_override is None
        assert state.selection_help_count == 0

    async def test_the_ladder_applies_when_folding_makes_a_mixed_history_all_failure(self) -> None:
        """다른 문항의 실제 오답 + 도움 완료 — 원래 이력은 혼합이지만 접으면 전부 실패다.

        오답 문항 b=0.0(라벨 3.0) · 도움 완료 문항 b=0.0 → 접힌 응답 [실패, 실패] → min(0, −0.5).
        원래 이력에는 정답 행이 있었으므로 이것은 "실제 오답만 있는 이력"이 아니다(§4-4).
        """
        state = await _load([_row(False, 3.0), _row(True, 3.0, True)])
        assert state.theta == pytest.approx(0.0, abs=1e-6)
        assert state.theta_boundary is None
        assert state.selection_theta == pytest.approx(-0.5, abs=_ABS)
        assert state.selection_help_count == 1

    async def test_a_real_all_wrong_history_keeps_the_lower_bound(self) -> None:
        """R3·R6 기준선 — 실제 오답만 있는 이력은 추정 θ(−4.0) 그대로이고 도움 채널이 닿지 않는다."""
        state = await _load([_row(False, 3.0)])
        assert state.theta == -4.0
        assert state.theta_boundary == "lower"
        assert state.selection_theta == -4.0
        assert state.selection_theta_override is None
        assert state.selection_help_count == 0

    async def test_rows_without_a_difficulty_source_do_not_count(self) -> None:
        """난이도 라벨이 없는 도움 완료는 응답에 들어가지 않는다 — 접힘으로도 세지 않는다."""
        state = await _load([_row(True, None, True), _row(True, 2.9, False)])
        assert state.selection_help_count == 0
        assert state.selection_theta == pytest.approx(0.4, abs=_ABS)  # 독립 성공 1건의 EOS-147 값

    async def test_unknown_labels_are_counted_and_do_not_change_the_target(self) -> None:
        state = await _load([_row(True, 2.9, None), _row(True, 3.5, None), _row(True, 3.0, False)])
        assert state.selection_hint_unknown_count == 2
        assert state.selection_help_count == 0
        # 전부 정답 — 맞힌 최고 b(0.5) + 0.5 = 1.0(EOS-147 상한 사다리 그대로).
        assert state.selection_theta == pytest.approx(1.0, abs=_ABS)

    async def test_legacy_history_is_unchanged(self) -> None:
        """EOS-133 이전·API 클라이언트의 이력(전부 NULL)은 종전과 같은 표적이다 — 회귀 0."""
        state = await _load([_row(True, 2.9), _row(False, 4.0), _row(True, 3.0)])
        assert state.selection_help_count == 0
        assert state.selection_theta_override is None  # 혼합 → 선택 θ = 추정 θ


class TestLoaderSelectsTheHintColumn:
    async def test_the_attempt_query_selects_used_hint_after_the_item_columns(self) -> None:
        """가짜 세션은 행을 그대로 돌려줘 쿼리가 `used_hint`를 빼먹어도 위의 테스트가 통과한다.

        그래서 **쿼리 자체**를 단언한다 — 조회 열의 마지막이 `problem_attempt.used_hint`다(6열 행의 계약).
        열을 빼면 서빙 경로에서는 항상 미상(NULL)으로 읽혀 도움 채널이 조용히 꺼진다(무증상).
        """
        session = _HistorySession([_row(True, 2.9, used_hint=True)])
        await load_attempt_history_state(cast(AsyncSession, session), uuid.uuid4())
        assert len(session.statements) == 1
        columns = [column.key for column in session.statements[0].selected_columns]
        assert columns == [
            "problem_id",
            "is_correct",
            "difficulty_overall",
            "irt_difficulty_b",
            "irt_a",
            "used_hint",
        ], columns


class TestKillSwitch:
    async def test_the_default_is_on(self) -> None:
        assert get_settings().l2_selection_help_fold_enabled is True

    async def test_off_restores_the_pre_eos39_behavior_bit_for_bit(
        self, fold_disabled: None
    ) -> None:
        """끄면 도움 완료도 정답이다 — 접힘·미상 수도 0이다(규칙이 일하지 않으면 계측도 없다)."""
        assert get_settings().l2_selection_help_fold_enabled is False
        state = await _load([_row(True, 2.9, used_hint=True), _row(True, 3.5, used_hint=None)])
        assert state.selection_help_count == 0
        assert state.selection_hint_unknown_count == 0
        assert state.theta == 4.0 and state.theta_boundary == "upper"
        # 전부 정답 — 맞힌 최고 b(0.5) + 0.5 = 1.0.
        assert state.selection_theta == pytest.approx(1.0, abs=_ABS)

    async def test_off_matches_the_independent_history_exactly(self, fold_disabled: None) -> None:
        off = await _load([_row(True, 2.9, used_hint=True)])
        assert off.selection_theta == pytest.approx(0.4, abs=_ABS)
        assert off.selection_theta_override == pytest.approx(0.4, abs=_ABS)


# ══════════════════════════════════════════════════════════════════════════
# ① 처치 기록 — 계측 키(작동한 비율의 재료)
# ══════════════════════════════════════════════════════════════════════════
class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)


async def _meta(**over: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"theta": 4.0, "pool_size": 3, "applied_weights": False}
    params.update(over)
    row = await record_recommendation_treatment(
        cast(AsyncSession, _FakeSession()), problem_id=uuid.uuid4(), **params
    )
    assert row.meta is not None
    return cast(dict[str, Any], row.meta)


class TestTreatmentRecordsHelpFoldKeys:
    async def test_keys_are_written_when_positive(self) -> None:
        meta = await _meta(selection_help_count=2, selection_hint_unknown_count=3)
        assert meta[META_KEY_SELECTION_HELP_COUNT] == 2
        assert meta["selection_help_count"] == 2  # 소비처(리포트)가 읽는 리터럴 키 이름 동결
        assert meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] == 3
        assert meta["selection_hint_unknown_count"] == 3

    async def test_keys_are_absent_when_zero_or_not_passed(self) -> None:
        """0이면 키를 넣지 않는다 — "키가 있는 처치의 비율"이 곧 발동률이다."""
        assert META_KEY_SELECTION_HELP_COUNT not in await _meta()
        assert META_KEY_SELECTION_HELP_COUNT not in await _meta(selection_help_count=0)
        assert META_KEY_SELECTION_HINT_UNKNOWN_COUNT not in await _meta(
            selection_hint_unknown_count=0
        )

    async def test_the_two_keys_are_decided_independently(self) -> None:
        only_help = await _meta(selection_help_count=1)
        assert META_KEY_SELECTION_HELP_COUNT in only_help
        assert META_KEY_SELECTION_HINT_UNKNOWN_COUNT not in only_help
        only_unknown = await _meta(selection_hint_unknown_count=1)
        assert META_KEY_SELECTION_HELP_COUNT not in only_unknown
        assert META_KEY_SELECTION_HINT_UNKNOWN_COUNT in only_unknown

    async def test_they_are_independent_of_the_selection_theta_key(self) -> None:
        meta = await _meta(selection_theta=-0.6, selection_help_count=1)
        assert meta[META_KEY_SELECTION_THETA] == -0.6
        assert meta[META_KEY_SELECTION_HELP_COUNT] == 1

    @pytest.mark.parametrize(
        "over", [{"selection_help_count": -1}, {"selection_hint_unknown_count": -1}]
    )
    async def test_negative_counts_are_a_caller_error(self, over: dict[str, int]) -> None:
        with pytest.raises(ValueError):
            await _meta(**over)
