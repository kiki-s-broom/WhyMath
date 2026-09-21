"""HARN-30 ③⑤ — PR 배송 상태 분류의 계약 동결 (양방향).

**왜**: '체크런 0건'과 'green인데 미머지'는 처방이 다르다 — 전자는 트리거를 깨워야
하고 후자는 사람 결정 대기다. 한 덩어리("미머지 PR")로 보면 처방을 못 고른다.
이 상태는 **무증상**이라 아무도 보지 않으면 조용히 방치된다(실측: 도구 첫 실행에서
열린 PR 13건 중 NO_CHECKS 5건·READY_UNMERGED 7건이 드러났다).

**양방향 요구(acceptance ⑤)**: 체크런 0건 PR과 green PR **양쪽**에서 서로 다른
신호가 나야 한다. 한쪽만 확인하고 통과 선언하면, 모든 PR을 같은 상태로 뭉개는
분류기도 절반은 맞는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "pr_delivery_audit",
    Path(__file__).resolve().parents[2] / "scripts" / "ops" / "pr_delivery_audit.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod  # @dataclass/모듈 조회 대비 — exec 전 등록
_spec.loader.exec_module(_mod)
classify = _mod.classify
PRESCRIPTION = _mod.PRESCRIPTION
ATTENTION = _mod.ATTENTION

REQUIRED = {"policy-guard", "backend — 마이그레이션·통합 (실 PG)"}
LONG_JOB = "backend — lint·type·test"  # 필수 아님


class TestBidirectionalDiscrimination:
    """⑤ 핵심 — 체크런 0건과 green이 **서로 다른** 상태를 내야 한다."""

    def test_no_checks_and_ready_differ(self):
        empty = classify(REQUIRED, {}, mergeable_state="clean")
        green = classify(REQUIRED, {n: "success" for n in REQUIRED}, mergeable_state="clean")
        assert empty == "NO_CHECKS"
        assert green == "READY_UNMERGED"
        assert empty != green, "두 상태를 같게 판정하면 처방을 고를 수 없다"

    def test_each_state_carries_a_distinct_prescription(self):
        """상태만 알려주고 처방이 없으면 다음 세션이 다시 판단해야 한다."""
        seen = {PRESCRIPTION[s] for s in PRESCRIPTION}
        assert len(seen) == len(PRESCRIPTION), "처방이 중복되면 상태 분리의 의미가 없다"
        # OPS-77이 확장했다 — 런 부재의 *원인*(STALLED_CONFLICT)과 **미판정** 2종을
        # 주의에 넣는다. "재지 못했다"를 조용히 넘기면 그 PR은 화면에서 사라지고,
        # 사라진 것은 정상과 구별되지 않는다.
        assert ATTENTION == {
            "STALLED_CONFLICT",
            "NO_CHECKS",
            "NO_CHECKS_CAUSE_UNKNOWN",
            "MERGE_STATE_UNKNOWN",
            "READY_UNMERGED",
        }


class TestNoChecksDetection:
    """부분 미발화도 미발화다 — 필수가 하나라도 없으면 다른 판정이 무의미하다."""

    def test_completely_empty_is_no_checks(self):
        assert classify(REQUIRED, {}, mergeable_state="clean") == "NO_CHECKS"

    def test_missing_one_required_is_no_checks(self):
        runs = {"policy-guard": "success", LONG_JOB: "success"}
        assert classify(REQUIRED, runs, mergeable_state="clean") == "NO_CHECKS"

    def test_nonrequired_only_is_no_checks(self):
        """비필수만 돌았다 — green처럼 보이지만 배송은 안 됐다."""
        assert classify(REQUIRED, {LONG_JOB: "success"}, mergeable_state="clean") == "NO_CHECKS"

    def test_empty_checks_is_no_checks_even_with_no_required(self):
        """필수 목록이 비어도 체크런 0건은 NO_CHECKS다 — 이 줄이 지키는 엣지.

        뮤테이션 O1(첫 가드 제거)이 최초 생존했다: required가 비어 있지 않으면
        아래 루프가 같은 결론을 내므로 첫 가드가 중복으로 보였다. 그러나 required가
        빈 경우(규칙 조회가 부분 실패한 상태 등) 가드가 없으면 **아무것도 안 돌았는데
        READY_UNMERGED**가 나온다 — 측정 실패를 '머지 준비 완료'로 위장하는 최악의 오판이다.
        """
        assert classify(set(), {}, mergeable_state="clean") == "NO_CHECKS"


class TestPriorityOrder:
    """순서가 곧 처방 우선순위 — 실패는 대기보다, 대기는 머지 상태보다 앞선다."""

    def test_failing_beats_pending(self):
        runs = {"policy-guard": "failure", "backend — 마이그레이션·통합 (실 PG)": None}
        assert classify(REQUIRED, runs, mergeable_state="clean") == "REQUIRED_FAILING"

    def test_pending_beats_behind(self):
        runs = {"policy-guard": "success", "backend — 마이그레이션·통합 (실 PG)": None}
        assert classify(REQUIRED, runs, mergeable_state="behind") == "REQUIRED_PENDING"

    def test_conflict_and_behind_are_distinct(self):
        runs = {n: "success" for n in REQUIRED}
        assert classify(REQUIRED, runs, mergeable_state="dirty") == "CONFLICT"
        assert classify(REQUIRED, runs, mergeable_state="behind") == "BEHIND"


class TestSkippedSatisfies:
    """doc-only PR에서 data-pipeline 잡은 skipped다 — 이걸 미충족으로 보면 전부 막힌다."""

    def test_skipped_required_is_ready(self):
        runs = {n: "skipped" for n in REQUIRED}
        assert classify(REQUIRED, runs, mergeable_state="clean") == "READY_UNMERGED"


# ── OPS-77 · 런 부재의 *원인*을 가른다 / 미판정을 확정으로 접지 않는다 ─────
#
# 실측 근거(판정 기준 main `7408c4fd`): 충돌한 PR은 GitHub이 `refs/pull/N/merge`를
# 계산하지 못해 `pull_request` 워크플로를 아예 발화시키지 않는다 — 새 head sha의
# 런이 0건이 되고 PR 화면에는 *이전* sha의 낡은 실패가 남는다. "안 돈다"가
# "실패했다"로 보이는 위장이며, 이때 NO_CHECKS의 처방(재푸시)은 틀린 처방이다.

_GREEN = {n: "success" for n in REQUIRED}


class TestStallCauseSeparation:
    """런 0건을 한 덩어리로 보지 않는다 — 처방이 갈리기 때문이다."""

    def test_conflict_stall_is_not_plain_no_checks(self) -> None:
        assert classify(REQUIRED, {}, mergeable_state="dirty") == "STALLED_CONFLICT"

    def test_no_checks_survives_when_cause_is_known_not_conflict(self) -> None:
        """대조군 — 충돌이 아닌 런 부재는 여전히 NO_CHECKS다(과잉 수정 방지)."""
        assert classify(REQUIRED, {}, mergeable_state="clean") == "NO_CHECKS"

    def test_partial_trigger_with_conflict_is_also_a_stall(self) -> None:
        """부분 미발화도 미발화다 — 그 축이 충돌 원인을 잃지 않는지 본다."""
        partial = {next(iter(REQUIRED)): "success"}
        assert classify(REQUIRED, partial, mergeable_state="dirty") == "STALLED_CONFLICT"

    def test_prescriptions_differ_and_stall_forbids_repush(self) -> None:
        """처방이 같으면 상태를 가른 의미가 없다."""
        stall = _mod.PRESCRIPTION["STALLED_CONFLICT"]
        plain = _mod.PRESCRIPTION["NO_CHECKS"]
        assert stall != plain
        assert "재푸시" in stall and "해소" in stall
        assert "push" in plain


class TestUnknownIsNotFolded:
    """모른다 ≠ 아니다 — 3상태를 2상태로 접으면 모르는 데이터로 확정 신호를 낸다."""

    def test_absent_field_does_not_become_ready(self) -> None:
        """**이것이 이 태스크의 본체다.** 초판은 `str(None)`='None'이라 맨 아래
        READY_UNMERGED로 떨어졌다 — 미판정이 '머지만 남음'으로 보고됐다."""
        assert classify(REQUIRED, _GREEN, mergeable_state=None) == "MERGE_STATE_UNKNOWN"

    def test_literal_unknown_does_not_become_ready(self) -> None:
        assert classify(REQUIRED, _GREEN, mergeable_state="unknown") == "MERGE_STATE_UNKNOWN"

    def test_stringified_none_does_not_become_ready(self) -> None:
        """호출측이 `str()`로 감싸 넘겨도 미판정으로 읽혀야 한다(표기 변형)."""
        assert classify(REQUIRED, _GREEN, mergeable_state="None") == "MERGE_STATE_UNKNOWN"

    def test_unknown_with_no_runs_says_cause_unknown(self) -> None:
        assert classify(REQUIRED, {}, mergeable_state=None) == "NO_CHECKS_CAUSE_UNKNOWN"

    def test_known_clean_still_reaches_ready(self) -> None:
        """대조군 — 정규화가 확정 값까지 미판정으로 만들지 않는다."""
        assert classify(REQUIRED, _GREEN, mergeable_state="clean") == "READY_UNMERGED"

    def test_case_and_whitespace_variants_are_normalized(self) -> None:
        assert classify(REQUIRED, _GREEN, mergeable_state="  DIRTY ") == "CONFLICT"


class TestAttentionCoverage:
    """새 상태가 조용히 빠지면 그 PR은 화면에서 사라진다 — 사라진 것은 정상과 같다."""

    def test_every_state_has_a_prescription(self) -> None:
        produced = {
            classify(REQUIRED, runs, mergeable_state=ms)
            for runs in ({}, _GREEN, {next(iter(REQUIRED)): "failure"}, {n: None for n in REQUIRED})
            for ms in (None, "unknown", "clean", "dirty", "behind")
        }
        missing = produced - set(_mod.PRESCRIPTION)
        assert not missing, f"처방 없는 상태: {missing}"

    def test_unknown_states_are_attention(self) -> None:
        assert "MERGE_STATE_UNKNOWN" in _mod.ATTENTION
        assert "NO_CHECKS_CAUSE_UNKNOWN" in _mod.ATTENTION
        assert "STALLED_CONFLICT" in _mod.ATTENTION

    def test_quiet_states_stay_quiet(self) -> None:
        """대조군 — 진행 중·실패는 주의로 세지 않는다(이 잡은 남의 PR로 red를 내지 않는다)."""
        assert "REQUIRED_PENDING" not in _mod.ATTENTION
        assert "REQUIRED_FAILING" not in _mod.ATTENTION

    def test_print_order_covers_every_prescribed_state(self) -> None:
        """출력 순서 목록에서 빠진 상태는 버킷에 담겨도 화면에 안 나온다."""
        import inspect

        src = inspect.getsource(_mod.main)
        for state in _mod.PRESCRIPTION:
            assert f'"{state}"' in src, f"main()의 출력 순서에 {state}가 없다"


class TestMergeStateRequery:
    """목록 응답을 그대로 믿지 않되, 필요할 때만 단건을 부른다(호출 비용)."""

    def test_known_listed_value_skips_the_requery(self) -> None:
        calls: list[str] = []

        def _fake_get(path: str):
            calls.append(path)
            return 200, {}

        orig, _mod._get = _mod._get, _fake_get
        try:
            state, n = _mod._merge_state("o/r", {"number": 7, "mergeable_state": "dirty"})
        finally:
            _mod._get = orig
        assert (state, n) == ("dirty", 0)
        assert calls == [], "확정 값인데 단건을 불렀다 — 호출 비용이 PR 수만큼 늘어난다"

    def test_absent_value_triggers_exactly_one_requery(self) -> None:
        calls: list[str] = []

        def _fake_get(path: str):
            calls.append(path)
            return 200, {"number": 7, "mergeable_state": "behind"}

        orig, _mod._get = _mod._get, _fake_get
        try:
            state, n = _mod._merge_state("o/r", {"number": 7})
        finally:
            _mod._get = orig
        assert (state, n) == ("behind", 1)
        assert calls == ["/repos/o/r/pulls/7"]

    def test_still_unknown_after_requery_stays_unknown(self) -> None:
        def _fake_get(path: str):
            return 200, {"number": 7, "mergeable_state": None}

        orig, _mod._get = _mod._get, _fake_get
        try:
            state, n = _mod._merge_state("o/r", {"number": 7})
        finally:
            _mod._get = orig
        assert (state, n) == ("unknown", 1), "모른다를 확정으로 낮추지 않는다"

    def test_requery_failure_is_measurement_failure_not_unknown(self) -> None:
        """API 실패를 `unknown`으로 낮추면 **실패가 정상 판정으로 위장된다**."""

        def _fake_get(path: str):
            return 403, {"message": "rate limit"}

        orig, _mod._get = _mod._get, _fake_get
        try:
            with pytest.raises(SystemExit) as err:
                _mod._merge_state("o/r", {"number": 7})
        finally:
            _mod._get = orig
        assert "측정 실패" in str(err.value)
