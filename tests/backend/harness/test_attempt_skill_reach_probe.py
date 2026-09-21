"""OPS-68 표본 생성 프로브 — 순수 코어·실패 변별 계약 (hermetic·DB 없이).

이 프로브의 존재 이유는 리포트가 *관측만* 하기 때문이다 — 표본이 없으면 전 지표가 "측정
불가(분모 0)"로 나와 측정 회차가 공전한다. 따라서 테스트도 "숫자가 나온다"가 아니라
**혼동을 막는 변별력**을 본다:

  ① 수용 0건의 해소율이 `0.0`이 아니라 `None`이다(모른다 ≠ 아니다).
  ② 제출 실패 건의 해소 개수가 `0`이 아니라 `None`이다 — 0으로 접으면 "해소 0건"과
     "측정 실패"가 같은 글자가 된다.
  ③ 준비 실패 3종(스키마 뒤처짐·후보 0건·DB 미도달)이 **서로 다른 exit**로 갈린다.
     같은 exit로 뭉개면 대책이 다른 실패가 한 글자가 된다.
  ④ 실패 사유가 **타입명 단위**로 집계된다(8가지 실패가 같은 글자로 보이지 않게).
  ⑤ 창 경계(`since_arg`)가 회차 시작 시각 그대로이고, 렌더된 다음 단계 명령에 그 값이
     자리표시자 없이 박혀 나온다(런북이 값을 사람에게 치환시키지 않게).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import whymath_backend.harness.attempt_skill_reach_probe as probe
from whymath_backend.harness.attempt_skill_reach_probe import (
    AttemptOutcome,
    CandidateShortageError,
    ProbeResult,
    SchemaBehindError,
    dump_json,
    ensure_skill_ids_column,
    probe_to_json,
    render_probe,
    summarize,
)

_T0 = datetime(2026, 9, 7, 3, 0, tzinfo=UTC)


def _outcome(**over: Any) -> AttemptOutcome:
    base: dict[str, Any] = {
        "problem_id": uuid.uuid4(),
        "is_correct": True,
        "status_code": 201,
        "skill_updates": 2,
        "concept_updates": 1,
        "error": None,
    }
    base.update(over)
    return AttemptOutcome(**base)  # type: ignore[arg-type]


def _result(outcomes: tuple[AttemptOutcome, ...], candidates: int | None = None) -> ProbeResult:
    return ProbeResult(
        started_at=_T0,
        requested=len(outcomes),
        candidates=candidates if candidates is not None else len(outcomes),
        outcomes=outcomes,
    )


# ── ① 분모 0 ────────────────────────────────────────────────────────────────
def test_resolution_rate_is_none_when_nothing_accepted() -> None:
    """수용 0건이면 해소율은 `None` — 0.0으로 위장하면 '해소 실패'로 오독된다."""
    result = _result((_outcome(status_code=500, skill_updates=None, error="HTTP 500: boom"),))
    assert result.accepted == 0
    assert result.resolution_rate is None
    assert "측정 불가(분모 0)" in render_probe(result)


def test_resolution_rate_counts_only_accepted_attempts() -> None:
    """실패 건은 분자에도 분모에도 들어가지 않는다(수용 2건 중 1건 해소 → 50%)."""
    result = _result(
        (
            _outcome(skill_updates=3),
            _outcome(skill_updates=0),
            _outcome(status_code=422, skill_updates=None, error="HTTP 422: bad"),
        )
    )
    assert (result.accepted, result.with_skill, result.failed) == (2, 1, 1)
    assert result.resolution_rate == pytest.approx(0.5)


# ── ② 모른다 ≠ 아니다 ────────────────────────────────────────────────────────
def test_failed_outcome_keeps_skill_updates_unknown() -> None:
    """제출 실패 건의 해소 개수는 `None`(모름)이고, 해소 ≥1 집계에 끼지 않는다."""
    failed = _outcome(status_code=None, skill_updates=None, error="ConnectError: refused")
    assert failed.accepted is False
    assert failed.skill_updates is None
    assert _result((failed,)).with_skill == 0


# ── ③ 실패 변별(exit) ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("exc", "expected_exit"),
    [
        (SchemaBehindError("컬럼 없음"), 3),
        (CandidateShortageError("후보 없음"), 4),
        (OSError("connection refused"), 2),
    ],
)
def test_preparation_failures_map_to_distinct_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exc: Exception,
    expected_exit: int,
) -> None:
    """준비 실패 3종이 서로 다른 exit로 갈리고, stderr에 **예외 타입명**이 남는다."""

    async def _boom(settings: Any, *, count: int) -> tuple[datetime, list[uuid.UUID]]:
        raise exc

    monkeypatch.setattr(probe, "prepare", _boom)
    assert probe.main(["--count", "5"]) == expected_exit
    assert type(exc).__name__ in capsys.readouterr().err


def test_all_submits_failed_exits_five(monkeypatch: pytest.MonkeyPatch) -> None:
    """준비는 됐는데 201이 하나도 없으면 exit 5 — 배선 회귀를 '해소 0%'로 위장하지 않는다."""

    async def _ok(settings: Any, *, count: int) -> tuple[datetime, list[uuid.UUID]]:
        return _T0, [uuid.uuid4()]

    monkeypatch.setattr(probe, "prepare", _ok)
    monkeypatch.setattr(
        probe,
        "submit_attempts",
        lambda ids, *, settings: (
            _outcome(status_code=503, skill_updates=None, error="HTTP 503: down"),
        ),
    )
    assert probe.main(["--count", "1"]) == 5


def test_successful_round_exits_zero_even_when_resolution_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """해소율 0%는 **성공한 측정**이다 — 게이트가 아니므로 exit 0."""

    async def _ok(settings: Any, *, count: int) -> tuple[datetime, list[uuid.UUID]]:
        return _T0, [uuid.uuid4()]

    monkeypatch.setattr(probe, "prepare", _ok)
    monkeypatch.setattr(
        probe, "submit_attempts", lambda ids, *, settings: (_outcome(skill_updates=0),)
    )
    assert probe.main(["--count", "1"]) == 0


def test_count_below_one_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    """`--count 0`은 조용히 '후보 없음'으로 흘러가지 않고 즉시 거부된다."""
    assert probe.main(["--count", "0"]) == 4
    assert capsys.readouterr().err.strip() != ""


# ── ④ 실패 사유 집계 ─────────────────────────────────────────────────────────
def test_summarize_groups_failures_by_reason() -> None:
    """같은 사유는 합치고 다른 사유는 갈린다 — 성공 건은 사유 표에 들어가지 않는다."""
    reasons = summarize(
        (
            _outcome(),
            _outcome(status_code=422, skill_updates=None, error="HTTP 422: bad"),
            _outcome(status_code=422, skill_updates=None, error="HTTP 422: bad"),
            _outcome(status_code=None, skill_updates=None, error="ConnectError: refused"),
        )
    )
    assert reasons == {"HTTP 422: bad": 2, "ConnectError: refused": 1}


def test_render_lists_failure_reasons(tmp_path: Path) -> None:
    """실패가 있으면 사유가 화면에 남는다(조용한 실패 금지)."""
    result = _result((_outcome(status_code=422, skill_updates=None, error="HTTP 422: bad"),))
    assert "HTTP 422: bad" in render_probe(result)
    assert "실패 사유" in render_probe(result)


# ── ⑤ 창 경계 인계 ───────────────────────────────────────────────────────────
def test_since_arg_is_round_start_and_is_embedded_in_next_command() -> None:
    """다음 단계 명령에 창 경계가 **값으로** 박힌다 — 사람이 치환할 자리표시자를 남기지 않는다."""
    result = _result((_outcome(),))
    assert result.since_arg == _T0.isoformat()
    rendered = render_probe(result)
    assert f"--since {_T0.isoformat()}" in rendered
    assert "여기에" not in rendered and "<" not in rendered.split("```")[1]


def test_json_round_trip_carries_probe_user_and_window(tmp_path: Path) -> None:
    """JSON 산출물이 창 경계·프로브 사용자·사유 표를 모두 실어 나른다(사후 추적 가능)."""
    result = _result((_outcome(skill_updates=0), _outcome(skill_updates=1)))
    payload = probe_to_json(result)
    assert payload["started_at"] == _T0.isoformat()
    assert payload["probe_user_id"] == str(probe.PROBE_USER_ID)
    assert payload["accepted"] == 2 and payload["with_skill"] == 1
    assert payload["resolution_rate"] == pytest.approx(0.5)
    written = tmp_path / "probe.json"
    written.write_text(dump_json(result), encoding="utf-8")
    assert '"probe_user_id"' in written.read_text(encoding="utf-8")


def test_probe_user_id_is_deterministic() -> None:
    """프로브 사용자는 고정 UUID여야 정리·식별이 user_id 한 개로 끝난다."""
    assert probe.PROBE_USER_ID == uuid.uuid5(
        uuid.NAMESPACE_URL, "whymath://harness/attempt-skill-reach-probe"
    )


# ── 스키마 선행 검사(변별력) ─────────────────────────────────────────────────
class _FakeInspector:
    def __init__(self, tables: list[str], columns: list[str]) -> None:
        self._tables = tables
        self._columns = columns

    def get_table_names(self) -> list[str]:
        return self._tables

    def get_columns(self, name: str) -> list[dict[str, str]]:
        return [{"name": c} for c in self._columns]


class _FakeSession:
    def __init__(self, inspector: _FakeInspector) -> None:
        self._inspector = inspector

    async def connection(self) -> "_FakeSession":
        return self

    async def run_sync(self, fn: Any) -> Any:
        return fn(object())


async def _check(tables: list[str], columns: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    inspector = _FakeInspector(tables, columns)
    monkeypatch.setattr(probe.sa, "inspect", lambda _conn: inspector)
    await ensure_skill_ids_column(_FakeSession(inspector))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_schema_check_passes_when_column_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 상태에서는 통과한다 — 이 절이 없으면 아래 RED가 '항상 빨강'과 구별되지 않는다."""
    await _check(["attempt_event"], ["event_id", "skill_ids"], monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tables", "columns"),
    [
        (["attempt_event"], ["event_id"]),  # 컬럼만 없음(마이그레이션 뒤처짐)
        ([], []),  # 테이블 자체가 없음(스키마 미적용)
    ],
)
async def test_schema_check_raises_when_column_missing(
    monkeypatch: pytest.MonkeyPatch, tables: list[str], columns: list[str]
) -> None:
    """결손 상태를 주입하면 RED — 그리고 그 예외는 exit 3으로 번역된다."""
    with pytest.raises(SchemaBehindError) as excinfo:
        await _check(tables, columns, monkeypatch)
    assert excinfo.value.exit_code == 3


# ── 후보 선정 쿼리(NULL 함정 동결) ───────────────────────────────────────────
def test_candidate_query_uses_not_exists_not_not_in() -> None:
    """`problem_attempt.problem_id`는 nullable이라 `NOT IN`이면 후보가 **조용히 0건**이 된다.

    SQL 3값 논리에서 `x NOT IN (…, NULL)`은 전건 false다 — 그 0건은 exit 4로 나가 "코퍼스가
    비었다"로 오독된다(실제로는 이미 시도한 행 하나가 원인). 컴파일된 SQL을 동결해 회귀를
    막는다: 조건 축이 아니라 **산출된 결과**를 검사한다.
    """
    from sqlalchemy.dialects import postgresql

    sql = str(probe.candidate_statement(limit=7).compile(dialect=postgresql.dialect()))
    assert "NOT (EXISTS" in sql
    assert "NOT IN" not in sql
    assert "difficulty_overall IS NOT NULL" in sql
    assert "random()" in sql


# ── 창 경계의 출처(DB 시계) ─────────────────────────────────────────────────
def test_window_boundary_comes_from_prepare_not_wall_clock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """창 경계는 `prepare`가 돌려준 값(=DB 시계) 그대로여야 한다.

    파이썬 프로세스의 벽시계로 창을 자르면 DB와의 미세한 시계 차만으로 방금 만든 표본이 창
    밖으로 새고, 그 결과가 `측정 불가(분모 0)`로 보인다 — 원인을 짐작할 수 없는 실패다.
    """

    async def _ok(settings: Any, *, count: int) -> tuple[datetime, list[uuid.UUID]]:
        return _T0, [uuid.uuid4()]

    monkeypatch.setattr(probe, "prepare", _ok)
    monkeypatch.setattr(probe, "submit_attempts", lambda ids, *, settings: (_outcome(),))
    out_path = tmp_path / "probe.json"
    assert probe.main(["--count", "1", "--json", str(out_path)]) == 0
    assert f"--since {_T0.isoformat()}" in capsys.readouterr().out
    assert _T0.isoformat() in out_path.read_text(encoding="utf-8")


def test_window_statement_reads_db_clock() -> None:
    """창 경계 쿼리가 **DB의 `now()`**를 읽는다 — 조건이 아니라 컴파일된 SQL로 동결한다.

    파이썬 벽시계로 바꿔치기하는 회귀는 hermetic 테스트가 관측할 수 없어(DB가 없다) 이
    산출물 검사가 유일한 검출 지점이다.
    """
    from sqlalchemy.dialects import postgresql

    assert "now()" in str(probe.window_statement().compile(dialect=postgresql.dialect()))


# ── 이벤트 루프 경계(Codex P1) ───────────────────────────────────────────────
def test_probe_settings_disable_the_connection_pool() -> None:
    """프로브는 **여러 이벤트 루프**에 걸쳐 같은 전역 엔진을 쓴다 — 준비는 `asyncio.run()`의
    루프, 제출은 컨텍스트매니저 없는 `TestClient`가 **요청마다** 여는 포털의 루프다.

    풀이 살아 있으면 닫힌 루프에 바인딩된 asyncpg 연결이 재사용돼 `Event loop is closed` /
    `attached to a different loop`로 제출이 전건 실패하고 회차가 exit 5로 끝난다. 즉
    `db_disable_pool`은 취향이 아니라 **정상 동작 조건**이라 계약으로 동결한다.
    """
    assert probe.probe_settings().db_disable_pool is True


async def test_prepare_disposes_the_cached_engine_before_building_the_probe_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`dispose_engine()`이 `get_sessionmaker(settings)`보다 **먼저** 불려야 한다.

    `get_sessionmaker`는 전역 캐시가 비어 있을 때만 주입 settings로 엔진을 만든다 — 캐시를
    비우지 않으면 환경 기본값(풀 활성)으로 이미 만들어진 엔진이 그대로 쓰여 위 계약이
    조용히 무효가 된다(순서가 곧 보호다).
    """
    order: list[str] = []
    sentinel = RuntimeError("여기까지만 — 실제 DB 왕복은 이 테스트의 대상이 아니다")
    marker = object()

    async def _dispose() -> None:
        order.append("dispose")

    def _sessionmaker(settings: Any = None) -> Any:
        order.append("sessionmaker")
        assert settings is marker, "prepare가 주입 settings를 넘기지 않았다"
        raise sentinel

    monkeypatch.setattr(probe, "dispose_engine", _dispose)
    monkeypatch.setattr(probe, "get_sessionmaker", _sessionmaker)
    with pytest.raises(RuntimeError):
        await probe.prepare(marker, count=1)  # type: ignore[arg-type]
    assert order == ["dispose", "sessionmaker"]
