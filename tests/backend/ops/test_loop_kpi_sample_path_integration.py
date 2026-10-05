"""루프 KPI ①②④ 판정 표본 경로(EOS-38) — 실 PG 위 **변별력** 시험.

판정 CLI를 *운영과 같은 방식*(서브프로세스·`--json`)으로 합성 부하 전용 DB 위에서 돌린다.

  대조군 : 정상 표본(합성 부하 그대로) → ①②④ PASS.
  주입   : 끊긴 세션(①) · 불일치 행(②) · 운영자 감사 행(④) → 각 KPI가 FAIL로 바뀐다.
  원복   : 주입 행을 지우면 다시 PASS — 상태가 원래 FAIL이었던 것이 아니라 *주입이 원인*이다.

**② 주입 건수가 1이 아닌 이유(정직 표기)**: 이 규모(스캔 542행)에서 위반 **1건**은 ②를 뒤집지 못한다
(Wilson 상한 0.0082 ≤ 기준 0.01). 설계 의도("불일치 ≤ 1%")대로다 — 결함이 아니다. 2건부터 FAIL(0.0110).
그래서 1건에서는 *분자가 센다 · 판정은 아직 PASS*, 2건에서는 FAIL을 양쪽 다 고정한다.

전용 DB는 이 모듈이 `CREATE DATABASE`로 만들고 `alembic upgrade head`를 적용한 뒤 끝나면 지운다.
권한이 없거나 PG가 없으면 **skip**한다(측정 실패 ≠ 통과).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from whymath_backend.config import Settings
from whymath_backend.ops import loop_kpi_sample_load as load

pytestmark = pytest.mark.integration

_REPO = Path(__file__).resolve().parents[3]
_BACKEND = _REPO / "src" / "backend"
_TAG = uuid.uuid4().hex[:8]
_DB_NAME = f"whymath_t{_TAG}{load.SAMPLE_DB_SUFFIX}"

# KPI 식별자(`LoopKpi` 값) — JSON `kpis[].kpi`의 키.
_K1, _K2, _K4 = "loop_completion_rate", "state_integrity", "manual_intervention"
_K3, _K5 = "explainability", "traceability"


def _admin_url() -> str:
    return make_url(Settings().database_url).set(database="postgres").render_as_string(False)


def _sample_url() -> str:
    return make_url(Settings().database_url).set(database=_DB_NAME).render_as_string(False)


async def _admin(sql: str) -> None:
    engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


def _run(args: list[str], *, cwd: Path = _BACKEND) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "WHYMATH_DATABASE_URL": _sample_url()}
    return subprocess.run(  # noqa: S603 - 고정 인자 · 셸 미사용
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


@pytest.fixture(scope="module")
def sample_db() -> Iterator[str]:
    """전용 DB 생성 → 마이그레이션 → 합성 부하(기본 학습자 수) → 테스트 → 삭제."""
    try:
        asyncio.run(_admin(f'CREATE DATABASE "{_DB_NAME}"'))
    except Exception as exc:  # noqa: BLE001 - PG 부재·권한 부족은 판정 불가(skip)
        pytest.skip(f"전용 DB 생성 불가({type(exc).__name__}) — 판정 불가. 통과가 아니다.")
    try:
        migrated = _run(["-m", "alembic", "upgrade", "head"])
        assert migrated.returncode == 0, f"alembic 실패: {migrated.stderr[-600:]}"
        loaded = _run(["-m", "whymath_backend.ops.loop_kpi_sample_load"])
        assert loaded.returncode == 0, f"합성 부하 실패: {loaded.stderr[-600:]}"
        yield _sample_url()
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{_DB_NAME}" WITH (FORCE)'))


def _gate(tmp_path: Path) -> dict[str, Any]:
    """판정 CLI를 운영 방식 그대로 돌리고 JSON을 돌려준다(종료 코드도 함께 검증 가능하게 포함)."""
    out = tmp_path / f"report-{uuid.uuid4().hex[:6]}.json"
    result = _run(
        [
            "-m",
            "whymath_backend.ops.loop_kpi_gate",
            "--since-hours",
            "24",
            "--sample-basis",
            "synthetic",
            "--json",
            str(out),
        ]
    )
    assert out.exists(), f"판정 JSON이 없다(exit={result.returncode}): {result.stderr[-400:]}"
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    report["_cli_exit"] = result.returncode
    return report


def _kpi(report: dict[str, Any], key: str) -> dict[str, Any]:
    (row,) = [k for k in report["kpis"] if k["kpi"] == key]
    return row


async def _exec(sql: str, **params: Any) -> Any:
    engine = create_async_engine(_sample_url())
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            # INSERT/DELETE(RETURNING 없음)는 행을 돌려주지 않는다 — 읽으면 ResourceClosedError.
            return result.fetchall() if result.returns_rows else []
    finally:
        await engine.dispose()


def _sql(sql: str, **params: Any) -> Any:
    return asyncio.run(_exec(sql, **params))


class TestControlGroup:
    def test_normal_sample_passes_the_three_kpis_that_were_unmeasurable(
        self, sample_db: str, tmp_path: Path
    ) -> None:
        """대조군 — 판정 4회가 분모 0·표본 부족으로 막혔던 ①②④가 측정되고 PASS다."""
        report = _gate(tmp_path)
        for key in (_K1, _K2, _K4):
            row = _kpi(report, key)
            assert row["verdict"] == "pass", (
                key,
                row["verdict"],
                row["numerator"],
                row["denominator"],
            )
            assert row["denominator"] and row["denominator"] > 0
        needed = load.required_sample_sizes()
        assert _kpi(report, _K1)["denominator"] >= needed.loop_completion_sessions
        assert _kpi(report, _K2)["denominator"] >= needed.state_integrity_rows

    def test_all_five_pass_and_the_basis_is_stamped(self, sample_db: str, tmp_path: Path) -> None:
        """삭제하지 않으므로 ⑤도 오염되지 않는다(EOS-37 선행) · 표지는 synthetic이다."""
        report = _gate(tmp_path)
        assert report["_cli_exit"] == 0, report["counts"]
        assert report["counts"] == {"total": 5, "passed": 5, "failed": 0, "unmeasured": 0}
        assert report["sample_basis"] == "synthetic"
        assert _kpi(report, _K5)["numerator"] == 0
        assert _kpi(report, _K3)["numerator"] == 0

    def test_the_load_leaves_every_learner_in_place(self, sample_db: str) -> None:
        """부하 직후 학습자·세션이 전부 남아 있다 — 삭제가 없었다는 DB 쪽 증거."""
        needed = load.required_sample_sizes()
        (learners,) = _sql("SELECT count(*) FROM user_profile")[0]
        (sessions,) = _sql("SELECT count(*) FROM learning_session")[0]
        assert learners >= needed.loop_completion_sessions
        assert sessions == learners


class TestSyntheticContentGoesThroughTheProvenanceGate:
    def test_every_synthetic_problem_has_a_ledger_row(self, sample_db: str) -> None:
        """LIC-03 — 생성물(`자체생성`) 문항은 원장 없이 들어가지 않는다. 합성 문항도 예외가 아니다."""
        (problems,) = _sql("SELECT count(*) FROM problem")[0]
        (ledgered,) = _sql(
            "SELECT count(DISTINCT problem_id) FROM content_provenance"
            " WHERE problem_id IN (SELECT problem_id FROM problem)"
        )[0]
        assert problems > 0
        assert ledgered == problems


class TestViolationInjectionFlipsEachKpi:
    def test_kpi1_a_session_that_never_reaches_a_recommendation_flips_to_fail(
        self, sample_db: str, tmp_path: Path
    ) -> None:
        """끊긴 세션: 시도는 있는데 그 뒤 추천이 없다 → 분모만 +1이라 Wilson 하한이 기준 아래로 간다."""
        before = _kpi(_gate(tmp_path), _K1)
        assert before["verdict"] == "pass"
        session_id = uuid.uuid4()
        _sql(
            "INSERT INTO learning_session (session_id, started_at, last_activity_at)"
            " VALUES (:s, now(), now())",
            s=session_id,
        )
        _sql(
            "INSERT INTO problem_attempt (attempt_id, session_id, ingested_at)"
            " VALUES (gen_random_uuid(), :s, now())",
            s=session_id,
        )
        try:
            broken = _kpi(_gate(tmp_path), _K1)
            assert broken["denominator"] == before["denominator"] + 1
            assert broken["numerator"] == before["numerator"]
            assert broken["verdict"] == "fail"
        finally:
            _sql("DELETE FROM learning_session WHERE session_id = :s", s=session_id)
        restored = _kpi(_gate(tmp_path), _K1)
        assert restored["verdict"] == "pass"
        assert restored["denominator"] == before["denominator"]

    def _inject_invalid_events(self, count: int) -> list[int]:
        """계약 위반 `attempt_event` — 계약 있는 타입인데 필수 필드가 없다(② `EVENT_SCHEMA_INVALID`)."""
        ids: list[int] = []
        for _ in range(count):
            rows = _sql(
                "INSERT INTO attempt_event (event_at, event_type, event_data)"
                " VALUES (now(), CAST('문제시도' AS event_type_enum), CAST('{}' AS jsonb))"
                " RETURNING event_id"
            )
            ids.append(int(rows[0][0]))
        return ids

    def test_kpi2_one_violation_is_counted_but_does_not_flip_at_this_scale(
        self, sample_db: str, tmp_path: Path
    ) -> None:
        """1건: 분자는 센다. 판정은 PASS다 — Wilson 상한 0.0082 ≤ 0.01(설계 의도, 결함 아님)."""
        before = _kpi(_gate(tmp_path), _K2)
        ids = self._inject_invalid_events(1)
        try:
            one = _kpi(_gate(tmp_path), _K2)
            assert one["numerator"] == before["numerator"] + 1
            assert one["denominator"] == before["denominator"] + 1
            assert one["verdict"] == "pass"
        finally:
            _sql("DELETE FROM attempt_event WHERE event_id = ANY(:ids)", ids=ids)
        assert _kpi(_gate(tmp_path), _K2)["numerator"] == before["numerator"]

    def test_kpi2_two_violations_flip_to_fail_and_restore_to_pass(
        self, sample_db: str, tmp_path: Path
    ) -> None:
        before = _kpi(_gate(tmp_path), _K2)
        assert before["verdict"] == "pass"
        ids = self._inject_invalid_events(2)
        try:
            two = _kpi(_gate(tmp_path), _K2)
            assert two["numerator"] == before["numerator"] + 2
            assert two["verdict"] == "fail"
        finally:
            _sql("DELETE FROM attempt_event WHERE event_id = ANY(:ids)", ids=ids)
        restored = _kpi(_gate(tmp_path), _K2)
        assert restored["verdict"] == "pass"
        assert restored["numerator"] == before["numerator"]

    def test_kpi4_one_operator_audit_row_flips_to_fail_zero_tolerance(
        self, sample_db: str, tmp_path: Path
    ) -> None:
        """무관용 축 — 운영자 감사 1건이 곧 FAIL이다(Wilson 미적용). 학생 본인 행위는 세지 않는다."""
        before = _kpi(_gate(tmp_path), _K4)
        assert before["verdict"] == "pass"
        actor = uuid.uuid4()
        _sql("INSERT INTO privacy_audit (user_id, event_kind) VALUES (:u, 'export_data')", u=actor)
        try:
            student_own = _kpi(_gate(tmp_path), _K4)
            assert student_own["verdict"] == "pass", "학생 본인 행위(반출)를 개입으로 세면 안 된다"
            _sql(
                "INSERT INTO privacy_audit (user_id, event_kind) VALUES (:u, 'role_change')",
                u=actor,
            )
            operator = _kpi(_gate(tmp_path), _K4)
            assert operator["numerator"] == before["numerator"] + 1
            assert operator["verdict"] == "fail"
        finally:
            _sql("DELETE FROM privacy_audit WHERE user_id = :u", u=actor)
        restored = _kpi(_gate(tmp_path), _K4)
        assert restored["verdict"] == "pass"
        assert restored["numerator"] == before["numerator"]
