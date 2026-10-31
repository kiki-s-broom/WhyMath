# EOS-194 acceptance (3) measurement - ASCII only (PowerShell 5.1 safe).
# Modes:
#   preflight : READ ONLY. counts + publishable candidate scan. exit 0 if >=1 candidate, 3 if none.
#   publish   : WRITE. 2 users (content_admin staff, learner) + draft..publish via CMS HTTP surface
#               + 1 attempt via POST /v1/me/attempts. Re-runs preflight first and refuses if none.
#   deprecate : WRITE (undo). deprecate the published version via CMS surface (pointer -> NULL)
#               and erase the measurement learner via DELETE /v1/me. Reads state file.
# Every mode prints KEY=VALUE lines. No secret values, no problem text/answers are printed.
import asyncio
import json
import logging
import os
import secrets
import sys
import uuid
from pathlib import Path

if not os.environ.get("WHYMATH_JWT_SECRET_KEY"):
    # per-process signing key: tokens minted here are valid only inside this process
    os.environ["WHYMATH_JWT_SECRET_KEY"] = secrets.token_hex(32)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import exists, func, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

import whymath_backend  # noqa: E402
from whymath_backend.app import create_app  # noqa: E402
from whymath_backend.config import Settings  # noqa: E402
from whymath_backend.db.models.hint import Hint  # noqa: E402
from whymath_backend.db.models.problem import Problem  # noqa: E402
from whymath_backend.db.models.user import UserProfile  # noqa: E402
from whymath_backend.l2.next_problem_selection import candidate_pool_conditions  # noqa: E402
from whymath_backend.l3 import problem_publish_gate as pgate  # noqa: E402
from whymath_backend.l3.problem_metadata_evidence import load_metadata_evidence  # noqa: E402
from whymath_backend.schema.enums import Persona, Role  # noqa: E402
from whymath_backend.schema.problem_metadata import evaluate_metadata  # noqa: E402
from whymath_backend.schema.user import UserProfile as UserProfileSchema  # noqa: E402
from whymath_backend.security import create_access_token  # noqa: E402

STATE = Path(os.environ.get("EOS194_STATE", "eos194_state.json"))
SCAN_LIMIT = 300
PIN_LOGGER = "whymath_backend.l2.attempt_version_pin"
# persona enum value "A_\uc77c\ubc18\uace0\uace03" written with escapes to stay ASCII
PERSONA_A = "A_\uc77c\ubc18\uace0\uace03"
RUNBOOK_SQL = (
    "SELECT count(*) AS total_problems, "
    "count(*) FILTER (WHERE problem.difficulty_overall IS NOT NULL AND (problem.source_type NOT IN "
    "('EBS', U&'\\D3C9\\AC00\\C6D0', U&'\\AD50\\ACFC\\C11C')) AND problem.review_status = 'approved') "
    "AS exposed, "
    "count(*) FILTER (WHERE problem.difficulty_overall IS NOT NULL AND (problem.source_type NOT IN "
    "('EBS', U&'\\D3C9\\AC00\\C6D0', U&'\\AD50\\ACFC\\C11C')) AND problem.review_status = 'approved' "
    "AND problem.problem_version_id IS NOT NULL) AS exposed_with_pointer, "
    "count(*) FILTER (WHERE problem.problem_version_id IS NOT NULL) AS any_with_pointer, "
    "(SELECT count(*) FROM problem_version WHERE status = 'PUBLISHED') AS published_versions "
    "FROM problem"
)


def schema_heads():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = Path(whymath_backend.__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(ini.parent / "alembic"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


async def schema_current(session):
    rows = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    return set(rows)


def out(key, value):
    print(f"{key}={value}", flush=True)


def settings():
    return Settings()


def engine():
    return create_async_engine(settings().database_url)


async def runbook_counts(session):
    row = (await session.execute(text(RUNBOOK_SQL))).mappings().one()
    return {k: int(v) for k, v in row.items()}


async def scan_candidates(session):
    """Exposed problems without pointer, with >=1 verified hint, no versions yet, 7 fields complete."""
    has_hint = exists(
        select(Hint.problem_id).where(Hint.problem_id == Problem.problem_id, Hint.verified.is_(True))
    )
    base = [*candidate_pool_conditions(), Problem.problem_version_id.is_(None)]
    exposed_no_ptr = (
        await session.execute(select(func.count()).select_from(Problem).where(*base))
    ).scalar_one()
    with_hint = (
        await session.execute(select(func.count()).select_from(Problem).where(*base, has_hint))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(Problem).where(*base, has_hint).order_by(Problem.problem_id).limit(SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    complete, missing_by_field = [], {}
    if not rows:
        # no candidate has a verified hint - sample the rest so the blocking fields are visible
        sample = (
            (
                await session.execute(
                    select(Problem).where(*base).order_by(Problem.problem_id).limit(50)
                )
            )
            .scalars()
            .all()
        )
        for problem in sample:
            verdict = evaluate_metadata(await load_metadata_evidence(session, problem))
            for field in (*verdict.missing, *verdict.unknown):
                key = "sample50_" + field.value
                missing_by_field[key] = missing_by_field.get(key, 0) + 1
    for problem in rows:
        verdict = evaluate_metadata(await load_metadata_evidence(session, problem))
        if not verdict.complete:
            for field in (*verdict.missing, *verdict.unknown):
                missing_by_field[field.value] = missing_by_field.get(field.value, 0) + 1
            continue
        if await pgate.list_versions(session, problem.problem_id):
            missing_by_field["has_existing_versions"] = (
                missing_by_field.get("has_existing_versions", 0) + 1
            )
            continue
        try:
            pgate.snapshot_payload(problem)
        except Exception as exc:  # live row violates snapshot contract
            key = "snapshot_invalid_" + type(exc).__name__
            missing_by_field[key] = missing_by_field.get(key, 0) + 1
            continue
        complete.append(problem.problem_id)
    return exposed_no_ptr, with_hint, len(rows), complete, missing_by_field


async def preflight():
    eng = engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as session:
            heads, current = schema_heads(), await schema_current(session)
            out("SCHEMA_HEAD", ",".join(sorted(heads)))
            out("SCHEMA_CURRENT", ",".join(sorted(current)) or "none")
            out("SCHEMA_AT_HEAD", current == heads)
            if current != heads:
                return None, []
            counts = await runbook_counts(session)
            for k, v in counts.items():
                out(k.upper(), v)
            exposed_no_ptr, with_hint, scanned, complete, missing = await scan_candidates(session)
    finally:
        await eng.dispose()
    out("EXPOSED_WITHOUT_POINTER", exposed_no_ptr)
    out("EXPOSED_WITH_VERIFIED_HINT", with_hint)
    out("SCANNED", scanned)
    out("PUBLISHABLE", len(complete))
    out("NOT_PUBLISHABLE_REASONS", json.dumps(missing, sort_keys=True))
    out("TARGET_PROBLEM_ID", complete[0] if complete else "none")
    return counts, complete


async def add_user(uid, role, nickname):
    eng = engine()
    try:
        async with async_sessionmaker(eng, expire_on_commit=False)() as session:
            session.add(
                UserProfile.from_schema(
                    UserProfileSchema(
                        user_id=uid,
                        persona_primary=Persona(PERSONA_A),
                        role=role,
                        nickname=nickname,
                    )
                )
            )
            await session.commit()
    finally:
        await eng.dispose()


async def read_one(sql, params):
    eng = engine()
    try:
        async with eng.connect() as conn:
            return (await conn.execute(text(sql), params)).first()
    finally:
        await eng.dispose()


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def headers(uid):
    return {"Authorization": f"Bearer {create_access_token(uid, settings=settings())}"}


def publish():
    if STATE.exists():
        out("WRITE_REFUSED", f"state file exists ({STATE}) - a previous publish run is recorded")
        return 4
    before, complete = asyncio.run(preflight())
    if before is None:
        out("WRITE_REFUSED", "DB schema is not at alembic head - nothing written")
        return 3
    if not complete:
        out("WRITE_REFUSED", "no publishable candidate (PUBLISHABLE=0) - nothing written")
        return 3
    pid = complete[0]
    staff, learner = uuid.uuid4(), uuid.uuid4()
    state = {"problem_id": str(pid), "staff_user_id": str(staff), "learner_user_id": str(learner)}
    asyncio.run(add_user(staff, Role.CONTENT_ADMIN, "eos194-measure-staff"))
    asyncio.run(add_user(learner, Role.STUDENT, "eos194-measure-learner"))
    STATE.write_text(json.dumps(state), encoding="ascii")
    out("STAFF_USER_ID", staff)
    out("LEARNER_USER_ID", learner)
    cap = _Capture()
    logging.getLogger(PIN_LOGGER).addHandler(cap)
    logging.getLogger(PIN_LOGGER).setLevel(logging.INFO)
    sh, lh = headers(staff), headers(learner)
    with TestClient(create_app()) as client:
        created = client.post(
            f"/v1/admin/cms/problems/{pid}/drafts", headers=sh, json={"reason": "EOS-194 (3) measure"}
        )
        out("DRAFT_HTTP", created.status_code)
        if created.status_code != 201:
            out("DRAFT_ERROR", created.text[:300])
            return 5
        version_id = str(created.json()["version_id"])
        state["version_id"] = version_id
        STATE.write_text(json.dumps(state), encoding="ascii")
        out("VERSION_ID", version_id)
        for action, expected in (
            ("submit", "DRAFT"),
            ("pass_review", "IN_REVIEW"),
            ("approve", "IN_QA"),
            ("publish", "APPROVED"),
        ):
            resp = client.post(
                f"/v1/admin/cms/problem-versions/{version_id}/transitions",
                headers=sh,
                json={"action": action, "expected_status": expected},
            )
            out(f"TRANSITION_{action.upper()}_HTTP", resp.status_code)
            if resp.status_code != 200:
                out(f"TRANSITION_{action.upper()}_ERROR", resp.text[:400])
                return 6
        attempt = client.post(
            "/v1/me/attempts",
            headers=lh,
            json={"problem_id": str(pid), "is_correct": True, "student_answer": "eos194-measure"},
        )
        out("ATTEMPT_HTTP", attempt.status_code)
        if attempt.status_code != 201:
            out("ATTEMPT_ERROR", attempt.text[:300])
            return 7
        attempt_id = attempt.json()["attempt_id"]
        state["attempt_id"] = attempt_id
        STATE.write_text(json.dumps(state), encoding="ascii")
    out("ATTEMPT_ID", attempt_id)
    out("LOG_OUTCOME_PINNED", any("outcome=pinned" in m for m in cap.lines))
    out("LOG_HAS_VERSION_ID", any(version_id in m for m in cap.lines))
    pointer = asyncio.run(
        read_one("SELECT problem_version_id FROM problem WHERE problem_id = :p", {"p": pid})
    )[0]
    pinned = asyncio.run(
        read_one(
            "SELECT problem_version_id FROM problem_attempt WHERE attempt_id = CAST(:a AS uuid)",
            {"a": attempt_id},
        )
    )[0]
    status = asyncio.run(
        read_one(
            "SELECT status::text FROM problem_version WHERE version_id = CAST(:v AS uuid)",
            {"v": version_id},
        )
    )[0]
    out("VERSION_STATUS", status)
    out("PROBLEM_POINTER_MATCH", str(pointer) == version_id)
    out("ATTEMPT_PIN_MATCH", str(pinned) == version_id)
    after = asyncio.run(_counts_only())
    for k, v in after.items():
        out("AFTER_" + k.upper(), v)
    out("DELTA", json.dumps({k: after[k] - before[k] for k in after}, sort_keys=True))
    drift = asyncio.run(_drift())
    out("DRIFT", json.dumps(drift, sort_keys=True))
    ok = (
        status == "PUBLISHED"
        and str(pointer) == version_id
        and str(pinned) == version_id
        and any("outcome=pinned" in m for m in cap.lines)
    )
    out("EOS194_ACCEPTANCE3_OK", ok)
    return 0 if ok else 8


async def _counts_only():
    eng = engine()
    try:
        async with async_sessionmaker(eng)() as session:
            return await runbook_counts(session)
    finally:
        await eng.dispose()


async def _drift():
    from whymath_backend.harness import published_problem_drift_report as drift

    eng = engine()
    try:
        async with async_sessionmaker(eng)() as session:
            report = await drift.collect_report(session)
    finally:
        await eng.dispose()
    data = drift.report_to_json(report)
    return {
        k: data[k]
        for k in ("pointer_filled", "measurable", "in_sync", "drifted", "indeterminate")
        if k in data
    }


def deprecate():
    if not STATE.exists():
        out("WRITE_REFUSED", f"no state file ({STATE}) - nothing recorded to undo")
        return 4
    state = json.loads(STATE.read_text(encoding="ascii"))
    if "version_id" not in state:
        out("WRITE_REFUSED", "state has no version_id - publish never created a version")
        return 4
    sh, lh = headers(uuid.UUID(state["staff_user_id"])), headers(uuid.UUID(state["learner_user_id"]))
    with TestClient(create_app()) as client:
        resp = client.post(
            f"/v1/admin/cms/problem-versions/{state['version_id']}/transitions",
            headers=sh,
            json={"action": "deprecate", "expected_status": "PUBLISHED"},
        )
        out("DEPRECATE_HTTP", resp.status_code)
        if resp.status_code != 200:
            out("DEPRECATE_ERROR", resp.text[:300])
        erased = client.request(
            "DELETE", "/v1/me", headers=lh, json={"confirmation": "DELETE_MY_ACCOUNT"}
        )
        out("LEARNER_ERASE_HTTP", erased.status_code)
    pointer = asyncio.run(
        read_one(
            "SELECT problem_version_id FROM problem WHERE problem_id = CAST(:p AS uuid)",
            {"p": state["problem_id"]},
        )
    )[0]
    out("POINTER_AFTER_UNDO", pointer)
    after = asyncio.run(_counts_only())
    for k, v in after.items():
        out("AFTER_UNDO_" + k.upper(), v)
    ok = resp.status_code == 200 and pointer is None and erased.status_code == 200
    out("UNDO_OK", ok)
    if ok:
        STATE.rename(STATE.with_suffix(".undone.json"))
    return 0 if ok else 9


if __name__ == "__main__":
    out("CODE_FROM", Path(whymath_backend.__file__).resolve().parent)
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "preflight":
        _, cands = asyncio.run(preflight())
        sys.exit(0 if cands else 3)
    if mode == "publish":
        sys.exit(publish())
    if mode == "deprecate":
        sys.exit(deprecate())
    out("USAGE", "preflight | publish | deprecate")
    sys.exit(2)
