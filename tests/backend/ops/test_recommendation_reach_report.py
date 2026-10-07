"""recommendation_reach_report 단위테스트 — hermetic(라이브 DB 0)·REC-01·REC-11.

집계 코어(`build_report`)는 순수 함수라 픽스처로 경계까지 전수 단언하고,
`fetch_reach_counts`는 큐 기반 가짜 세션(FakeSession — test_me.py `_QueueSession` 관례
답습)으로 실 DB 없이 쿼리 11회의 매핑을 검증한다(EOS-39가 선택 θ 규칙 발동률 5개를 더했다). 실 JOIN·DISTINCT·필터·JSONB `has_key`의
SQL 정확성은 FakeSession이 stmt를 무시하므로 검증하지 않는다(test_me.py 동일 관례 —
통합테스트 영역).

acceptance ③(변별력) 핵심: attempt 총계가 0→1로 바뀌면 '미도달'이 해제되고, 1→0으로
되돌리면 다시 '미도달'이 나오는지 *양방향*으로 확인한다(성공/실패가 같은 값을 내면
검증이 아니다). REC-11 기록률 축도 같은 원칙으로 0/0→None, N/0(불가능 조합 방지)이 아니라
분모>0일 때만 비율이 나오는지 확인한다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.ops import recommendation_reach_report as rr


# ──────────────────────────────────────────────────────────────────────────
# 가짜 세션 — execute()마다 큐잉된 스칼라 값을 순서대로 반환(stmt는 무시).
# ──────────────────────────────────────────────────────────────────────────
class _FakeScalarResult:
    def __init__(self, value: int, rows: list[tuple[Any, ...]] | None = None) -> None:
        self._value = value
        self._rows = rows or []

    def scalar_one(self) -> int:
        return self._value

    def all(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _QueueSession:
    """`fetch_reach_counts`의 execute 18회(①attempt ②eligible ③pair ④pool ⑤treatment
    ⑥with_policy_metadata ⑦selection_theta키 ⑧boundary=upper ⑨boundary=lower ⑩help키
    ⑪hint_unknown키 ⑫공급 2+ ⑬분류 가능 ⑭라벨-단독 ⑮라벨-단독 서빙 ⑯라벨-단독 쌍 ⑰신호 없는 쌍
    ⑱라벨 타당도 행 묶음 — 스칼라가 아니라 `.all()` 행)를 큐로 반환. 뒤쪽을 생략하면 0으로 채운다
    (EOS-39·EOS-178 이전 호출 호환)."""

    def __init__(
        self, values: list[int], validity_rows: list[tuple[Any, ...]] | None = None
    ) -> None:
        self._values = values + [0] * (17 - len(values))
        self._validity_rows = validity_rows or []
        self._calls = 0
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> _FakeScalarResult:
        index = self._calls
        self._calls += 1
        self.statements.append(stmt)
        if index == 17:  # ⑱ 라벨 예측 타당도 — (라벨, 출처, 분류 가능, 쌍 수, 신호 쌍 수) 행
            return _FakeScalarResult(0, self._validity_rows)
        return _FakeScalarResult(self._values[index])


def _counts(
    attempt: int = 0,
    eligible: int = 0,
    pair: int = 0,
    pool: int = 0,
    treatment: int = 0,
    with_policy: int = 0,
    selection_theta_key: int = 0,
    boundary_upper: int = 0,
    boundary_lower: int = 0,
    help_key: int = 0,
    hint_unknown_key: int = 0,
    supply_help: int = 0,
    supply_classified: int = 0,
    supply_label_only: int = 0,
    supply_label_only_served: int = 0,
    label_only_pair: int = 0,
    label_only_unsignaled_pair: int = 0,
    validity_cells: tuple[tuple[str, str | None, int, int], ...] = (),
    unlabeled_pair: int = 0,
    unclassified_pair: int = 0,
    min_evidence_n: int | None = None,
) -> rr.ReachCounts:
    return rr.ReachCounts(
        problem_attempt_total=attempt,
        theta_eligible_response_total=eligible,
        weak_concept_signal_pair_total=pair,
        candidate_pool_structural_cap=pool,
        recommendation_treatment_total=treatment,
        recommendation_treatment_with_policy_metadata_total=with_policy,
        selection_theta_key_total=selection_theta_key,
        theta_boundary_upper_total=boundary_upper,
        theta_boundary_lower_total=boundary_lower,
        selection_help_key_total=help_key,
        selection_hint_unknown_key_total=hint_unknown_key,
        coach_supply_help_row_total=supply_help,
        coach_supply_classified_row_total=supply_classified,
        coach_supply_label_only_row_total=supply_label_only,
        coach_supply_label_only_served_row_total=supply_label_only_served,
        coach_label_only_pair_total=label_only_pair,
        coach_label_only_unsignaled_pair_total=label_only_unsignaled_pair,
        coach_label_validity_cells=validity_cells,
        coach_label_unlabeled_pair_total=unlabeled_pair,
        coach_label_unclassified_pair_total=unclassified_pair,
        coach_label_min_evidence_n=min_evidence_n,
    )


# ──────────────────────────────────────────────────────────────────────────
# fetch_reach_counts — 쿼리 6회 → ReachCounts 매핑(순서 계약).
# ──────────────────────────────────────────────────────────────────────────
async def test_fetch_reach_counts_maps_eighteen_queries_in_order() -> None:
    session = _QueueSession([5, 3, 2, 120, 40, 25, 11, 7, 2, 9, 4, 60, 50, 20, 6, 15, 12])
    counts = await rr.fetch_reach_counts(session)  # type: ignore[arg-type]
    assert counts == _counts(
        attempt=5,
        eligible=3,
        pair=2,
        pool=120,
        treatment=40,
        with_policy=25,
        selection_theta_key=11,
        boundary_upper=7,
        boundary_lower=2,
        help_key=9,
        hint_unknown_key=4,
        supply_help=60,
        supply_classified=50,
        supply_label_only=20,
        supply_label_only_served=6,
        label_only_pair=15,
        label_only_unsignaled_pair=12,
    )


async def test_every_query_is_consumed_and_the_order_is_a_contract() -> None:
    """큐를 서로 다른 소수로 채워 **어느 쿼리가 어느 필드로 가는지**를 고정한다 — 순서가 바뀌면 RED."""
    values = [101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163, 167, 173, 179, 181]
    session = _QueueSession(values)
    counts = await rr.fetch_reach_counts(session)  # type: ignore[arg-type]
    assert session._calls == 18  # 쿼리를 하나 빠뜨리거나 더하면 RED
    assert [
        counts.problem_attempt_total,
        counts.theta_eligible_response_total,
        counts.weak_concept_signal_pair_total,
        counts.candidate_pool_structural_cap,
        counts.recommendation_treatment_total,
        counts.recommendation_treatment_with_policy_metadata_total,
        counts.selection_theta_key_total,
        counts.theta_boundary_upper_total,
        counts.theta_boundary_lower_total,
        counts.selection_help_key_total,
        counts.selection_hint_unknown_key_total,
        counts.coach_supply_help_row_total,
        counts.coach_supply_classified_row_total,
        counts.coach_supply_label_only_row_total,
        counts.coach_supply_label_only_served_row_total,
        counts.coach_label_only_pair_total,
        counts.coach_label_only_unsignaled_pair_total,
    ] == values


# ──────────────────────────────────────────────────────────────────────────
# build_report — 순수 집계. count>0 ⇔ reached=True(분모 없는 0 방지 원칙).
# ──────────────────────────────────────────────────────────────────────────
def test_build_report_all_zero_marks_not_reached() -> None:
    """전 축 0행 → 전부 미도달(reached=False). candidate_pool_structural_cap은 그대로 노출."""
    report = rr.build_report(_counts())
    assert report.problem_attempt_reached is False
    assert report.theta_eligible_reached is False
    assert report.weak_concept_signal_reached is False
    assert report.candidate_pool_structural_cap == 0
    assert report.request_counter_status == rr.REQUEST_COUNTER_STATUS
    # REC-11: 처치 기록 0건 → 분모 없음 → rate는 None(0/0을 지어내지 않는다).
    assert report.recommendation_treatment_total == 0
    assert report.recommendation_treatment_policy_metadata_rate is None


def test_build_report_positive_counts_mark_reached() -> None:
    report = rr.build_report(_counts(attempt=5, eligible=3, pair=2, pool=200))
    assert report.problem_attempt_reached is True
    assert report.theta_eligible_reached is True
    assert report.weak_concept_signal_reached is True
    assert report.problem_attempt_total == 5
    assert report.theta_eligible_response_total == 3
    assert report.weak_concept_signal_pair_total == 2
    assert report.candidate_pool_structural_cap == 200


# ──────────────────────────────────────────────────────────────────────────
# acceptance ③ 변별력 — attempt 1건 주입 → 미도달 해제, 되돌리면 다시 미도달(양방향).
# ──────────────────────────────────────────────────────────────────────────
async def test_reach_toggles_bidirectionally_when_attempt_row_injected_and_removed() -> None:
    """problem_attempt 0행 ↔ 1행 왕복 — '미도달' 표시가 실제로 켜지고 꺼진다(양방향 확인)."""
    # ① 0행 — '미도달'
    zero_session = _QueueSession([0, 0, 0, 10, 0, 0])
    zero_report = rr.build_report(await rr.fetch_reach_counts(zero_session))  # type: ignore[arg-type]
    assert zero_report.problem_attempt_reached is False
    zero_rendered = rr.render_report(zero_report)
    assert "전체 행 수: **0** (미도달)" in zero_rendered
    assert rr.NOT_REACHED in zero_rendered

    # ② fixture row 1건 주입 — '미도달' 해제(측정됨으로 전환)
    one_session = _QueueSession([1, 1, 0, 10, 0, 0])
    one_report = rr.build_report(await rr.fetch_reach_counts(one_session))  # type: ignore[arg-type]
    assert one_report.problem_attempt_reached is True
    one_rendered = rr.render_report(one_report)
    assert "전체 행 수: **1** (측정됨)" in one_rendered
    assert "전체 행 수: **1** (미도달)" not in one_rendered

    # ③ fixture 제거(되돌림) — 다시 '미도달'
    back_session = _QueueSession([0, 0, 0, 10, 0, 0])
    back_report = rr.build_report(await rr.fetch_reach_counts(back_session))  # type: ignore[arg-type]
    assert back_report.problem_attempt_reached is False
    assert "전체 행 수: **0** (미도달)" in rr.render_report(back_report)


def test_theta_eligible_auto_not_reached_when_attempt_is_zero() -> None:
    """problem_attempt 0행이면 θ 유효 응답도 구조적으로 0 → 자동 미도달(부분집합 관계)."""
    report = rr.build_report(_counts(pair=5, pool=10))
    assert report.problem_attempt_reached is False
    assert report.theta_eligible_reached is False  # count 자체가 0이라 자동


# ──────────────────────────────────────────────────────────────────────────
# REC-11 — candidates·policy_version 기록률("작동한 비율"). 양방향 변별력.
# ──────────────────────────────────────────────────────────────────────────
def test_policy_metadata_rate_is_none_when_no_treatment_recorded() -> None:
    """처치 기록 자체가 0건이면 비율은 None — 0/0을 0.0으로 위장하지 않는다."""
    report = rr.build_report(_counts(treatment=0, with_policy=0))
    assert report.recommendation_treatment_policy_metadata_rate is None
    rendered = rr.render_report(report)
    assert f"기록률: {rr.NOT_REACHED}" in rendered


def test_policy_metadata_rate_computed_when_partially_recorded() -> None:
    """처치 40건 중 25건만 신 필드 보유 → 비율 0.625(REC-11 배선 이전 데이터가 섞인 상태)."""
    report = rr.build_report(_counts(treatment=40, with_policy=25))
    assert report.recommendation_treatment_policy_metadata_rate == 25 / 40
    rendered = rr.render_report(report)
    assert "62.5%" in rendered
    assert "REC-11 이전" in rendered  # 1.0 미만이므로 설명 문구가 붙는다


def test_policy_metadata_rate_full_coverage_omits_partial_note() -> None:
    """전건 기록(비율 1.0)이면 'REC-11 이전' 부분 커버리지 설명을 붙이지 않는다."""
    report = rr.build_report(_counts(treatment=10, with_policy=10))
    assert report.recommendation_treatment_policy_metadata_rate == 1.0
    rendered = rr.render_report(report)
    assert "100.0%" in rendered
    assert "REC-11 이전" not in rendered


def test_policy_metadata_rate_toggles_bidirectionally() -> None:
    """분모 0→N 왕복 — None↔비율 전환이 양방향으로 실제로 일어난다."""
    zero_report = rr.build_report(_counts(treatment=0, with_policy=0))
    assert zero_report.recommendation_treatment_policy_metadata_rate is None

    populated_report = rr.build_report(_counts(treatment=4, with_policy=4))
    assert populated_report.recommendation_treatment_policy_metadata_rate == 1.0

    back_report = rr.build_report(_counts(treatment=0, with_policy=0))
    assert back_report.recommendation_treatment_policy_metadata_rate is None


# ──────────────────────────────────────────────────────────────────────────
# 추천 요청 수 — 카운터 부재를 지어내지 않고 정직 보고(핵심 acceptance①).
# ──────────────────────────────────────────────────────────────────────────
def test_request_counter_status_reports_absence_honestly() -> None:
    """새 카운터를 지어내지 않고 '관측 불가(요청 카운터 없음)'를 명시한다."""
    assert "관측 불가" in rr.REQUEST_COUNTER_STATUS
    assert "요청 카운터 없음" in rr.REQUEST_COUNTER_STATUS
    report = rr.build_report(_counts())
    rendered = rr.render_report(report)
    assert rr.REQUEST_COUNTER_STATUS in rendered


# ──────────────────────────────────────────────────────────────────────────
# JSON 직렬화 — report_to_json/dump_json 구조.
# ──────────────────────────────────────────────────────────────────────────
def test_report_to_json_structure() -> None:
    report = rr.build_report(_counts(attempt=1, eligible=1, pool=50, treatment=4, with_policy=2))
    payload: dict[str, Any] = rr.report_to_json(report)
    assert payload["problem_attempt"] == {"total": 1, "reached": True}
    assert payload["theta_eligible_response"] == {"total": 1, "reached": True}
    assert payload["weak_concept_signal_pair"] == {"total": 0, "reached": False}
    assert payload["candidate_pool_structural_cap"] == 50
    assert payload["request_counter"]["status"] == rr.REQUEST_COUNTER_STATUS
    assert payload["recommendation_treatment_policy_metadata"] == {
        "total": 4,
        "with_policy_metadata": 2,
        "rate": 0.5,
    }


def test_report_to_json_rate_is_none_when_no_denominator() -> None:
    report = rr.build_report(_counts())
    payload: dict[str, Any] = rr.report_to_json(report)
    assert payload["recommendation_treatment_policy_metadata"]["rate"] is None


def test_dump_json_round_trips() -> None:
    report = rr.build_report(_counts(attempt=2, eligible=1, pair=1, pool=30))
    parsed = json.loads(rr.dump_json(report))
    assert parsed["problem_attempt"]["total"] == 2


# ──────────────────────────────────────────────────────────────────────────
# CLI main() — 성공/실패 exit code·stdout/stderr·--json 산출물.
# ──────────────────────────────────────────────────────────────────────────
def test_main_success_prints_report_and_returns_zero(monkeypatch: Any, capsys: Any) -> None:
    fake_report = rr.build_report(_counts(pool=10))

    async def _fake_run(min_label_evidence_n: int | None = None) -> rr.ReachReport:
        return fake_report

    monkeypatch.setattr(rr, "_run", _fake_run)
    exit_code = rr.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "추천 도달 관측 리포트" in out
    assert "미도달" in out


def test_main_writes_json_when_requested(tmp_path: Any, monkeypatch: Any, capsys: Any) -> None:
    fake_report = rr.build_report(_counts(attempt=1, eligible=1, pair=1, pool=5))

    async def _fake_run(min_label_evidence_n: int | None = None) -> rr.ReachReport:
        return fake_report

    monkeypatch.setattr(rr, "_run", _fake_run)
    json_path = tmp_path / "reach.json"
    exit_code = rr.main(["--json", str(json_path)])
    assert exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["problem_attempt"] == {"total": 1, "reached": True}
    out = capsys.readouterr().out
    assert str(json_path) in out


def test_main_runtime_error_reports_exception_type_name(monkeypatch: Any, capsys: Any) -> None:
    """DB 접속 등 실행 오류 시 exit 2 + stderr에 예외 **타입명**(침묵 실패 금지)."""

    class _BoomError(Exception):
        """주입 실패용 커스텀 예외 — 타입명 로그 검증이 이 이름을 찾는다."""

    async def _fake_run_raises(min_label_evidence_n: int | None = None) -> rr.ReachReport:
        raise _BoomError("DB 접속 실패(주입)")

    monkeypatch.setattr(rr, "_run", _fake_run_raises)
    exit_code = rr.main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "_BoomError" in err


# ──────────────────────────────────────────────────────────────────────────
# EOS-39 — 선택 θ 규칙 발동률("작동한 비율"): 순수 집계·렌더·JSON.
# ──────────────────────────────────────────────────────────────────────────
def test_selection_rule_rates_are_none_without_a_denominator() -> None:
    """처치 기록 0건이면 전 축 비율이 None이다 — 0/0을 0.0으로 지어내지 않는다."""
    report = rr.build_report(_counts())
    assert report.selection_theta_key_rate is None
    assert report.theta_boundary_upper_rate is None
    assert report.theta_boundary_lower_rate is None
    assert report.selection_help_key_rate is None
    assert report.selection_hint_unknown_key_rate is None
    rendered = rr.render_report(report)
    assert "## 6. 선택 θ 규칙 발동률" in rendered
    assert f"발동률 전 축: {rr.NOT_REACHED}" in rendered


def test_selection_rule_rates_use_the_treatment_total_as_the_denominator() -> None:
    report = rr.build_report(
        _counts(
            treatment=40,
            with_policy=40,
            selection_theta_key=10,
            boundary_upper=8,
            boundary_lower=2,
            help_key=5,
            hint_unknown_key=20,
        )
    )
    assert report.selection_theta_key_rate == 0.25
    assert report.theta_boundary_upper_rate == 0.2
    assert report.theta_boundary_lower_rate == 0.05
    assert report.selection_help_key_rate == 0.125
    assert report.selection_hint_unknown_key_rate == 0.5


def test_selection_rule_axes_are_rendered_with_counts_and_percentages() -> None:
    rendered = rr.render_report(
        rr.build_report(_counts(treatment=40, selection_theta_key=10, help_key=5))
    )
    assert "`selection_theta` 키(선택 θ ≠ 추정 θ): **10** (25.0%)" in rendered
    assert "`selection_help_count` 키(코치 도움 완료를 실패로 접음): **5** (12.5%)" in rendered
    # 값이 0인 축도 '0건'으로 보인다(0.0%) — 분모가 있으므로 지어낸 값이 아니다.
    assert "`theta_boundary=lower`(전부 오답): **0** (0.0%)" in rendered
    # 킬 스위치 기간과 구분되지 않는다는 한계가 리포트 자체에 적혀 있다.
    assert "l2_selection_help_fold_enabled" in rendered


def test_selection_rule_json_structure_and_none_rates() -> None:
    payload = rr.report_to_json(rr.build_report(_counts(treatment=4, help_key=1)))
    rules = payload["selection_theta_rules"]
    assert rules["treatment_total"] == 4
    assert rules["selection_help_key"] == {"total": 1, "rate": 0.25}
    assert rules["selection_theta_key"] == {"total": 0, "rate": 0.0}
    none_payload = rr.report_to_json(rr.build_report(_counts()))
    assert none_payload["selection_theta_rules"]["selection_help_key"] == {
        "total": 0,
        "rate": None,
    }


# ──────────────────────────────────────────────────────────────────────────
# EOS-178 — 코치 단계 공급 구성(§7): 순수 집계·렌더·JSON. 실 JSONB·bool_or SQL은 통합 테스트가 본다.
# ──────────────────────────────────────────────────────────────────────────
def test_supply_composition_rates_are_none_without_a_denominator() -> None:
    """단계 2+ 공급 행이 0건이면 전 비율이 None이고 '미도달'로 적힌다 — 0.0으로 위장하지 않는다."""
    report = rr.build_report(_counts())
    assert report.coach_supply_classified_rate is None
    assert report.coach_supply_label_only_rate is None
    assert report.coach_supply_label_only_served_rate is None
    assert report.coach_label_only_unsignaled_rate is None
    rendered = rr.render_report(report)
    assert "## 7. 코치 단계 공급 구성" in rendered
    assert f"구성 전 축: {rr.NOT_REACHED}" in rendered


def test_supply_composition_rates_use_literal_denominators() -> None:
    """분모가 축마다 다르다 — 분류율은 단계 2+ 행, 라벨-단독율은 분류된 행, 서빙율은 라벨-단독 행,
    미확인율은 라벨-단독 쌍. 소수로 채워 어느 분모를 쓰는지 리터럴로 고정한다."""
    report = rr.build_report(
        _counts(
            supply_help=80,
            supply_classified=40,
            supply_label_only=10,
            supply_label_only_served=2,
            label_only_pair=8,
            label_only_unsignaled_pair=6,
        )
    )
    assert report.coach_supply_classified_rate == 0.5
    assert report.coach_supply_label_only_rate == 0.25
    assert report.coach_supply_label_only_served_rate == 0.2
    assert report.coach_label_only_unsignaled_rate == 0.75


def test_supply_composition_partial_denominators_stay_none() -> None:
    """구판 행뿐이면(분류된 행 0건) 라벨-단독율은 None이다 — '라벨-단독이 0%'로 읽히면 안 된다."""
    report = rr.build_report(_counts(supply_help=30, supply_classified=0))
    assert report.coach_supply_classified_rate == 0.0
    assert report.coach_supply_label_only_rate is None
    assert report.coach_supply_label_only_served_rate is None
    assert report.coach_label_only_unsignaled_rate is None


def test_supply_composition_render_and_json() -> None:
    report = rr.build_report(
        _counts(
            supply_help=80,
            supply_classified=40,
            supply_label_only=10,
            supply_label_only_served=2,
            label_only_pair=8,
            label_only_unsignaled_pair=6,
        )
    )
    rendered = rr.render_report(report)
    assert "단계 2+ 행(도움 후보): **80**" in rendered
    assert "분류 가능한 행: **40** (50.0%)" in rendered
    assert "라벨만으로 올라간** 행(`base_level<2`): **10** (25.0%)" in rendered
    assert "학생 신호 공급이 하나도 없는 쌍: **6** (75.0%)" in rendered
    assert "l4_hint_attribution_label_free_enabled" in rendered
    payload: dict[str, Any] = rr.report_to_json(report)
    assert payload["coach_hint_supply"] == {
        "help_row_total": 80,
        "classified": {"total": 40, "rate": 0.5},
        "label_only": {"total": 10, "rate": 0.25},
        "label_only_served": {"total": 2, "rate": 0.2},
        "label_only_pair": {"total": 8, "unsignaled_total": 6, "unsignaled_rate": 0.75},
    }


# ──────────────────────────────────────────────────────────────────────────
# EOS-179 — 코치 라벨의 예측 타당도(§8): ⑱ 쿼리 매핑·순수 집계·Wilson·렌더·JSON·CLI.
# 실 JSONB의 창 함수·bool_or/bool_and 의미는 가짜 세션이 못 본다(stmt를 무시) — 통합 테스트
# (`test_eos179_label_provenance_integration.py`)가 합성 원장 행의 주입으로 변별한다.
# ──────────────────────────────────────────────────────────────────────────
#: (라벨, 출처, 신호 판정 가능, 쌍 수, 신호 쌍 수) — ⑱ 쿼리가 돌려주는 행 모양.
_VRows = list[tuple[Any, ...]]


class _RowsSession:
    """`fetch_label_validity` 단독 호출용 — 첫 execute가 준비된 행 묶음을 낸다(stmt는 기록)."""

    def __init__(self, rows: _VRows) -> None:
        self._rows = rows
        self.statements: list[object] = []

    async def execute(self, stmt: object) -> _FakeScalarResult:
        self.statements.append(stmt)
        return _FakeScalarResult(0, self._rows)


async def _read_validity(rows: _VRows, **kwargs: Any) -> Any:
    return await rr.fetch_label_validity(_RowsSession(rows), **kwargs)  # type: ignore[arg-type]


async def test_validity_rows_are_split_into_cells_unlabeled_and_unclassified() -> None:
    read = await _read_validity(
        [
            ("초보", "server_bkt", True, 10, 6),
            ("숙달", "server_bkt", True, 4, 1),
            ("초보", None, True, 3, 1),
            (None, None, True, 7, 2),  # 첫 행에 라벨 없음 — 신호가 있어도 표에서 제외
            (None, None, False, 2, 0),  # 라벨도 없고 분류도 불가 — 라벨 없음이 먼저다
            ("초보", "server_bkt", False, 5, 0),  # 구판 행이 섞여 신호 판정 불가
            (
                "발전 중",
                "client_bkt",
                None,
                1,
                0,
            ),  # bool_and가 NULL이어도 접어 신호 없음이 되지 않는다
        ]
    )
    assert read.unlabeled_pair_total == 9
    assert read.unclassified_pair_total == 6
    # 정렬 계약: (라벨, 출처 — None은 빈 문자열) — 출력이 쿼리 반환 순서에 기대지 않는다.
    assert read.cells == (
        ("숙달", "server_bkt", 4, 1),
        ("초보", None, 3, 1),
        ("초보", "server_bkt", 10, 6),
    )


async def test_an_empty_ledger_reads_as_no_cells_not_zero_rates() -> None:
    read = await _read_validity([])
    assert (read.cells, read.unlabeled_pair_total, read.unclassified_pair_total) == ((), 0, 0)


async def test_fetch_reach_counts_carries_the_validity_read_and_the_floor() -> None:
    session = _QueueSession(
        [], validity_rows=[("초보", "server_bkt", True, 8, 5), (None, None, True, 3, 0)]
    )
    counts = await rr.fetch_reach_counts(session, min_label_evidence_n=12)  # type: ignore[arg-type]
    assert counts.coach_label_validity_cells == (("초보", "server_bkt", 8, 5),)
    assert counts.coach_label_unlabeled_pair_total == 3
    assert counts.coach_label_unclassified_pair_total == 0
    assert counts.coach_label_min_evidence_n == 12  # 읽기가 적용한 하한이 리포트에 남는다
    # 하한은 기록만 되는 것이 아니라 ⑱ 쿼리에 **실제로 걸린다** — 리포트에 "하한 적용"이라 적고
    # 걸지 않으면 표본이 다른 것을 같은 것으로 읽게 된다.
    stmt: Any = session.statements[-1]
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    assert "evidence_n >= 12" in str(compiled).lower().replace("anon_1.", "")


def _validity_sql(**kwargs: Any) -> str:
    """⑱ 쿼리를 PG 방언·리터럴 바인딩으로 컴파일한 소문자 SQL(구조 가드 전용)."""
    import asyncio

    session = _RowsSession([])
    asyncio.run(rr.fetch_label_validity(session, **kwargs))  # type: ignore[arg-type]
    stmt: Any = session.statements[-1]
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled).lower().replace("anon_1.", "")


def test_the_validity_query_uses_the_first_row_window_and_the_pair_partition() -> None:
    """구조 가드(보조) — 의미의 변별은 통합 테스트가 한다. 창·분할 키가 통째로 사라지면 RED."""
    sql = _validity_sql()
    assert "row_number() over (partition by attempt_event.user_id, attempt_event.problem_id" in sql
    assert "order by attempt_event.event_at asc" in sql
    assert "bool_or" in sql and "bool_and" in sql
    assert "rn = 1" in sql  # 쌍의 *첫* 행만


def test_the_evidence_floor_is_a_filter_only_when_given() -> None:
    assert "evidence_n >=" not in _validity_sql()
    assert "evidence_n >= 5" in _validity_sql(min_evidence_n=5)


# --- 순수 집계 -------------------------------------------------------------
def test_validity_view_literals_for_precision_recall_and_the_contrast() -> None:
    report = rr.build_report(
        _counts(
            validity_cells=(
                ("발전 중", "server_bkt", 40, 4),
                ("숙달", "server_bkt", 20, 1),
                ("초보", "server_bkt", 30, 12),
            )
        )
    )
    view = report.coach_label_validity_all
    assert (view.pair_total, view.signal_pair_total) == (90, 17)
    assert [(r.label, r.signal.numerator, r.signal.denominator) for r in view.rows] == [
        ("초보", 12, 30),
        ("발전 중", 4, 40),  # 고정 순서 — 원장 정렬(가나다)이 아니다
        ("숙달", 1, 20),
    ]
    assert view.novice_precision.rate == pytest.approx(12 / 30)
    assert (view.novice_recall.numerator, view.novice_recall.denominator) == (12, 17)
    assert (view.other_signal_rate.numerator, view.other_signal_rate.denominator) == (5, 60)


def test_wilson_bounds_are_attached_and_a_small_sample_keeps_its_wide_interval() -> None:
    zero_of_thirty = rr.build_report(_counts(validity_cells=(("초보", "server_bkt", 30, 0),)))
    rate = zero_of_thirty.coach_label_validity_all.novice_precision
    assert rate.rate == 0.0 and rate.lower95 == 0.0
    # 0/30의 95% 단측 상한은 약 8.3% — "관측 0 = 확정 0"이 아니다(1%대 비율은 이 표본이 가리지 못한다).
    assert rate.upper95 == pytest.approx(0.0827, abs=5e-4)


def test_zero_denominators_are_none_not_zero() -> None:
    """라벨이 한 쌍도 없으면 그 칸은 None — 0.0%로 위장하지 않는다."""
    report = rr.build_report(_counts(validity_cells=(("초보", "server_bkt", 6, 3),)))
    view = report.coach_label_validity_all
    empty = {r.label: r.signal for r in view.rows}["숙달"]
    assert (empty.numerator, empty.denominator) == (0, 0)
    assert (empty.rate, empty.lower95, empty.upper95) == (None, None, None)
    # 신호 쌍이 있어도 '초보' 쌍이 없으면 정밀도는 None, 신호가 하나도 없으면 재현율이 None이다.
    none_report = rr.build_report(_counts(validity_cells=(("숙달", "server_bkt", 5, 0),)))
    none_view = none_report.coach_label_validity_all
    assert none_view.novice_precision.rate is None
    assert none_view.novice_recall.rate is None  # 분모(신호 쌍)가 0
    assert none_view.other_signal_rate.rate == 0.0  # 분모 5 — 0이 맞다(None과 구별)


def test_an_empty_validity_table_is_all_none() -> None:
    view = rr.build_report(_counts()).coach_label_validity_all
    assert (view.pair_total, view.signal_pair_total) == (0, 0)
    assert view.novice_precision.rate is None and view.novice_recall.rate is None
    assert view.other_signal_rate.rate is None


def test_the_server_view_drops_client_chosen_and_unknown_sources() -> None:
    report = rr.build_report(
        _counts(
            validity_cells=(
                ("초보", "client_bkt", 10, 10),  # 클라가 정한 라벨 — 서버 라벨의 정확도가 아니다
                ("초보", "explicit", 5, 5),
                ("초보", None, 4, 4),  # EOS-179 이전 행 — 출처를 모른다
                ("초보", "server_bkt", 20, 8),
                ("초보", "server_theta", 10, 2),
            )
        )
    )
    server = report.coach_label_validity_server
    assert (server.novice_precision.numerator, server.novice_precision.denominator) == (10, 30)
    everything = report.coach_label_validity_all
    assert (everything.novice_precision.numerator, everything.novice_precision.denominator) == (
        29,
        49,
    )
    assert report.coach_label_source_unknown_pair_total == 4


def test_an_unfamiliar_label_is_kept_after_the_canonical_rows() -> None:
    """원장에만 있는 라벨을 조용히 버리면 분모가 어긋난다 — 표 끝에 남긴다."""
    view = rr.build_report(
        _counts(validity_cells=(("고급", "server_bkt", 3, 1), ("초보", "server_bkt", 2, 1)))
    ).coach_label_validity_all
    assert [r.label for r in view.rows] == ["초보", "발전 중", "숙달", "고급"]
    assert view.pair_total == 5


# --- 렌더·JSON·CLI ---------------------------------------------------------
def test_validity_section_renders_counts_bounds_and_the_exclusions() -> None:
    report = rr.build_report(
        _counts(
            validity_cells=(("초보", "server_bkt", 30, 12), ("숙달", "server_bkt", 20, 1)),
            unlabeled_pair=9,
            unclassified_pair=6,
        )
    )
    text = rr.render_report(report)
    assert "## 8. 코치 라벨의 예측 타당도" in text
    assert "**12/30** = 40.0% (Wilson 단측 95% 하한" in text
    # 하한·상한이 제 자리에 찍힌다(서로 바뀌면 좁은 쪽이 넓은 쪽으로 읽힌다).
    lo, up = wilson_lower_bound(12, 30), wilson_upper_bound(12, 30)
    assert f"하한 {lo:.1%} · 상한 {up:.1%}" in text
    assert "'초보' 정밀도" in text and "'초보' 재현율" in text
    assert "첫 공급 행에 라벨 없음: **9**" in text and "신호 판정 불가" in text
    assert "**6**" in text
    assert "임계·판정은 이 리포트가 내지 않는다" in text  # 합성 표본으로 임계를 정하지 않는다
    assert "증거 수 하한 적용" not in text  # 하한을 안 걸었으면 그 줄이 없다


def test_validity_section_is_not_reached_without_pairs() -> None:
    text = rr.render_report(rr.build_report(_counts()))
    assert "라벨·신호 판정이 모두 있는 쌍 0건 — 분모 없음" in text
    assert "0.0%" not in text.split("## 8.")[-1]


def test_validity_section_states_the_evidence_floor_when_applied() -> None:
    report = rr.build_report(_counts(min_evidence_n=7))
    assert "관측 **7건 이상**" in rr.render_report(report)


def test_validity_json_structure_keeps_none_for_missing_denominators() -> None:
    report = rr.build_report(
        _counts(
            validity_cells=(("초보", "server_bkt", 30, 12),),
            unlabeled_pair=2,
            unclassified_pair=1,
            min_evidence_n=3,
        )
    )
    payload: dict[str, Any] = rr.report_to_json(report)["coach_label_validity"]
    assert payload["min_evidence_n"] == 3
    assert (payload["unlabeled_pair_total"], payload["unclassified_pair_total"]) == (2, 1)
    server = payload["server"]
    assert server["pair_total"] == 30 and server["signal_pair_total"] == 12
    assert server["by_label"]["초보"]["numerator"] == 12
    assert server["by_label"]["숙달"]["rate"] is None  # 쌍 0 — 0.0이 아니다
    assert server["novice_recall"]["denominator"] == 12
    json.dumps(payload)  # 직렬화 가능


def test_the_floor_flag_is_forwarded_to_the_run(monkeypatch: Any) -> None:
    seen: list[int | None] = []

    async def _fake_run(min_label_evidence_n: int | None = None) -> rr.ReachReport:
        seen.append(min_label_evidence_n)
        return rr.build_report(_counts())

    monkeypatch.setattr(rr, "_run", _fake_run)
    assert rr.main([]) == 0
    assert rr.main(["--min-label-evidence-n", "5"]) == 0
    assert seen == [None, 5]


def test_a_negative_floor_is_rejected(capsys: Any) -> None:
    with pytest.raises(SystemExit) as exc:
        rr.main(["--min-label-evidence-n", "-1"])
    assert exc.value.code == 2
