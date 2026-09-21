"""recommendation_reach_report 단위테스트 — hermetic(라이브 DB 0)·REC-01·REC-11.

집계 코어(`build_report`)는 순수 함수라 픽스처로 경계까지 전수 단언하고,
`fetch_reach_counts`는 큐 기반 가짜 세션(FakeSession — test_me.py `_QueueSession` 관례
답습)으로 실 DB 없이 쿼리 6회의 매핑을 검증한다. 실 JOIN·DISTINCT·필터·JSONB `has_key`의
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

from whymath_backend.ops import recommendation_reach_report as rr


# ──────────────────────────────────────────────────────────────────────────
# 가짜 세션 — execute()마다 큐잉된 스칼라 값을 순서대로 반환(stmt는 무시).
# ──────────────────────────────────────────────────────────────────────────
class _FakeScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _QueueSession:
    """`fetch_reach_counts`의 execute 6회(①attempt ②eligible ③pair ④pool ⑤treatment
    ⑥with_policy_metadata)를 큐로 반환."""

    def __init__(self, values: list[int]) -> None:
        self._values = values
        self._calls = 0

    async def execute(self, _stmt: object) -> _FakeScalarResult:
        value = self._values[self._calls]
        self._calls += 1
        return _FakeScalarResult(value)


def _counts(
    attempt: int = 0,
    eligible: int = 0,
    pair: int = 0,
    pool: int = 0,
    treatment: int = 0,
    with_policy: int = 0,
) -> rr.ReachCounts:
    return rr.ReachCounts(
        problem_attempt_total=attempt,
        theta_eligible_response_total=eligible,
        weak_concept_signal_pair_total=pair,
        candidate_pool_structural_cap=pool,
        recommendation_treatment_total=treatment,
        recommendation_treatment_with_policy_metadata_total=with_policy,
    )


# ──────────────────────────────────────────────────────────────────────────
# fetch_reach_counts — 쿼리 6회 → ReachCounts 매핑(순서 계약).
# ──────────────────────────────────────────────────────────────────────────
async def test_fetch_reach_counts_maps_six_queries_in_order() -> None:
    session = _QueueSession([5, 3, 2, 120, 40, 25])
    counts = await rr.fetch_reach_counts(session)  # type: ignore[arg-type]
    assert counts == _counts(attempt=5, eligible=3, pair=2, pool=120, treatment=40, with_policy=25)


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

    async def _fake_run() -> rr.ReachReport:
        return fake_report

    monkeypatch.setattr(rr, "_run", _fake_run)
    exit_code = rr.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "추천 도달 관측 리포트" in out
    assert "미도달" in out


def test_main_writes_json_when_requested(tmp_path: Any, monkeypatch: Any, capsys: Any) -> None:
    fake_report = rr.build_report(_counts(attempt=1, eligible=1, pair=1, pool=5))

    async def _fake_run() -> rr.ReachReport:
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

    async def _fake_run_raises() -> rr.ReachReport:
        raise _BoomError("DB 접속 실패(주입)")

    monkeypatch.setattr(rr, "_run", _fake_run_raises)
    exit_code = rr.main([])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "_BoomError" in err
