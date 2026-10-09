"""Publish Gate — 개념 버전의 Draft→Publish 검증 파이프라인 + 전이 실행 + Rollback (EOS-50).

설계 정본: `docs/architecture/44_eos_version_management.md` §9("Publish는 단순 status 변경이
아니라 검증 파이프라인이다")·§12(MVP "Publish with validation")·§16-6.
축 판정(기존 `review_status`·PB-03 노출 계약과 **다른 축** — 경계 5항):
`docs/reviews/eos50_publish_gate_axis_judgment_2026-09-29.md`.

## 이 모듈이 하는 일 — 세 층

1. **검증 파이프라인**(순수 함수, DB 0): `run_gate(version, gate)`가 게이트 종류별 검사를 전부
   돌리고, 하나라도 실패하면 `PublishGateError`로 거부한다(점추정·인상 판정 없음 — 각 검사는
   참/거짓). 검사 항목:
     · `schema_valid`          — 버전 전체를 Pydantic으로 재검증(model_copy 경유 우회 차단)
     · `schema_version_format` — `<이름>@<정수>[.<정수>]` 형식
     · `entity_type`           — 'Concept'
     · `content_hash`          — QA: payload 해시 산출·각인 / PUBLISH·RESTORE: 재계산 == 각인값
     · `governance_complete`   — QA: 작성·검토자 / PUBLISH·RESTORE: 작성·검토·승인자
     · `qa_record_bound`       — PUBLISH·RESTORE: 지금 내용의 해시로 통과한 QA 기록이 있다
     · `previously_published`  — RESTORE: 과거에 발행된 적이 있다(`published_at`)
2. **전이 계획**(순수 함수): `plan_transition`이 전이표(`schema/version_lifecycle.py`)를 조회해
   도착 상태를 얻고, 거버넌스를 기록하고, 게이트가 붙은 간선이면 파이프라인을 강제 경유시킨다.
   이 함수는 도착 상태를 스스로 고르지 않는다 — 표에 없는 전이는 `UndefinedTransitionError`.
3. **전이 실행**(DB): `create_draft`·`apply_transition`·`rollback`. 운영 코드에서
   `concept_version` 행과 `concept.current_published_version_id`를 쓰는 **유일한 자리**다
   (AST 동결 — `tests/backend/l3/test_publish_gate_enforcement.py`).

## 트랜잭션 계약

실행 함수는 `flush`까지만 하고 `commit`하지 않는다 — 호출자가 트랜잭션 경계를 가진다. 게이트가
실패하면 **아무 것도 쓰기 전에** 예외가 난다(계획이 먼저, 쓰기는 나중). rollback도 복원 대상의
게이트를 현재 발행본을 건드리기 전에 통과시킨다.

## 이 모듈이 하지 않는 것

- 학생 노출 판정 — 문항 노출은 `review_status`·저작권 두 축이 소유한다(판정 문서 B2).
  이 모듈은 `ReviewStatus`를 읽지도 쓰지도 않는다(B1 · AST 동결).
- Impact Analysis·Dependency lock(§13, Phase 2 — acceptance ④).
- 실패 기록의 영속 — 통과한 게이트만 `qa.records`에 남는다. 실패는 예외 + 경고 로그(예외 타입명
  포함)이며, 전이는 일어나지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.concept import Concept
from whymath_backend.db.models.concept_version import ConceptVersion
from whymath_backend.schema.concept_version import ConceptVersion as SchemaConceptVersion
from whymath_backend.schema.concept_version import ConceptVersionPayload
from whymath_backend.schema.version_header import (
    GateKind,
    GateRecord,
    TransitionAction,
    VersionChange,
    VersionGovernance,
    VersionIntegrity,
    VersionQA,
    VersionSource,
    VersionStatus,
)
from whymath_backend.schema.version_lifecycle import resolve_transition

logger = logging.getLogger("whymath.l3.publish_gate")

# 검사 묶음 버전 — 검사 항목·판정 규칙을 바꾸면 올린다(§9 `validator_bundle_version`).
VALIDATOR_BUNDLE_VERSION = "eos50-publish-gate@1"

# 해시 알고리즘 접두 — 알고리즘을 바꿔도 옛 해시와 새 해시가 섞여 오판되지 않게 값에 박는다.
_HASH_PREFIX = "sha256:"

_SCHEMA_VERSION_RE = re.compile(r"^[a-z][a-z0-9_-]*@\d+(\.\d+)?$")
_ENTITY_TYPE = "Concept"

# 게이트별 필수 거버넌스 필드 — QA 시점엔 승인자가 아직 없다(승인이 그 게이트의 결과다).
_REQUIRED_GOVERNANCE: dict[GateKind, tuple[str, ...]] = {
    GateKind.QA: ("created_by", "reviewed_by"),
    GateKind.PUBLISH: ("created_by", "reviewed_by", "approved_by"),
    GateKind.RESTORE: ("created_by", "reviewed_by", "approved_by"),
}


class PublishGateError(RuntimeError):
    """게이트 검사 미통과 — 전이는 일어나지 않는다."""

    def __init__(self, gate: GateKind | str | None, failures: Sequence[str]) -> None:
        self.gate = gate
        self.failures = tuple(failures)
        label = gate.value if isinstance(gate, GateKind) else gate
        super().__init__(f"게이트 {label} 미통과: {'; '.join(self.failures)}")


class RollbackUnavailableError(RuntimeError):
    """롤백할 수 없다 — 현재 발행본이 없거나 복원할 직전 발행본이 없다."""


class StalePublishedPointerError(RuntimeError):
    """호출자가 본 현재 발행본이 잠금 후 실제 발행본과 다르다 — 롤백은 일어나지 않는다(P3-12).

    화면이 "이 판이 발행 중이니 내려라"고 요청했는데 그사이 다른 판이 발행됐다면, 그대로 롤백하면
    **엉뚱한 판**이 내려간다. `rollback(expected_current_version_id=...)`가 개념 행 잠금 후
    비교한다.
    """

    def __init__(self, expected: uuid.UUID, actual: uuid.UUID | None) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"발행본 불일치: 기대 {expected} / 실제 {actual}")


class StaleStatusError(RuntimeError):
    """호출자가 본 상태와 잠금 후 실제 상태가 다르다 — 그사이 다른 사람이 전이를 실행했다(P3-12).

    `apply_transition(expected_status=...)`가 **행 잠금을 잡은 뒤** 비교하므로 검사와 전이 사이에
    틈이 없다(화면이 읽은 상태로 전이를 요청하는 낙관적 동시성). 전이는 일어나지 않는다.
    """

    def __init__(self, expected: VersionStatus, actual: VersionStatus) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"상태 불일치: 기대 {expected.value} / 실제 {actual.value}")


@dataclass(frozen=True)
class RollbackResult:
    """롤백 결과 — 내려간 판과 복원된 판."""

    concept_code: str
    rolled_back_version_id: uuid.UUID
    restored_version_id: uuid.UUID


# ──────────────────────────────────────────────────────────────────────────
# 1) 검증 파이프라인 (순수)
# ──────────────────────────────────────────────────────────────────────────
def compute_content_hash(payload: ConceptVersionPayload) -> str:
    """payload의 결정론 해시 — 필드 순서·JSONB 왕복과 무관하게 같은 내용이면 같은 값.

    `model_dump(mode="json")`로 enum·UUID를 문자열로 고정한 뒤 키 정렬 JSON을 sha256한다.
    """
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _HASH_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revalidate(version: SchemaConceptVersion) -> SchemaConceptVersion:
    """직렬화 → 재검증. `model_copy(update=...)`는 검증을 건너뛰므로 게이트는 이것으로 본다."""
    return SchemaConceptVersion.model_validate(version.model_dump(mode="json"))


def _qa_record_bound(version: SchemaConceptVersion, content_hash: str) -> bool:
    """지금 내용의 해시로 통과한 QA 게이트 기록이 있는가."""
    return any(
        record.gate == GateKind.QA.value
        and record.verdict == "PASSED"
        and record.content_hash == content_hash
        for record in version.qa.records
    )


def run_gate(version: SchemaConceptVersion, gate: GateKind) -> tuple[tuple[str, ...], str]:
    """게이트 검사를 **전부** 돌린다 — (통과 검사 이름들, 산출 해시). 하나라도 실패하면 예외.

    실패를 첫 건에서 멈추지 않고 모아 보고한다(한 번에 무엇을 고쳐야 하는지 보이게).
    """
    failures: list[str] = []
    passed: list[str] = []

    try:
        checked = _revalidate(version)
        passed.append("schema_valid")
    except ValidationError as exc:
        # 구조가 깨지면 나머지 검사가 볼 대상 자체를 믿을 수 없다 — 여기서 거부한다.
        raise PublishGateError(gate, [f"schema_valid: {type(exc).__name__}"]) from exc

    if _SCHEMA_VERSION_RE.match(checked.schema_version):
        passed.append("schema_version_format")
    else:
        failures.append(f"schema_version_format: {checked.schema_version!r}")

    if checked.entity_type == _ENTITY_TYPE:
        passed.append("entity_type")
    else:
        failures.append(f"entity_type: {checked.entity_type!r} != {_ENTITY_TYPE!r}")

    content_hash = compute_content_hash(checked.payload)
    stamped = checked.integrity.content_hash
    if gate is GateKind.QA:
        # QA는 해시를 *산출*한다 — 이전 QA 회차의 낡은 각인은 새 값으로 덮인다.
        passed.append("content_hash")
    elif stamped is None:
        failures.append("content_hash: 승인 시점 해시가 각인되지 않았다")
    elif stamped != content_hash:
        failures.append("content_hash: 승인 이후 payload가 바뀌었다(재계산 불일치)")
    else:
        passed.append("content_hash")

    governance = checked.governance
    missing = [
        name for name in _REQUIRED_GOVERNANCE[gate] if not (getattr(governance, name) or "").strip()
    ]
    if missing:
        failures.append(f"governance_complete: 비어 있음 {missing}")
    else:
        passed.append("governance_complete")

    if gate in (GateKind.PUBLISH, GateKind.RESTORE):
        if _qa_record_bound(checked, content_hash):
            passed.append("qa_record_bound")
        else:
            failures.append("qa_record_bound: 지금 내용으로 통과한 QA 기록이 없다")

    if gate is GateKind.RESTORE:
        if checked.published_at is not None:
            passed.append("previously_published")
        else:
            failures.append("previously_published: 발행된 적 없는 판은 복원 대상이 아니다")

    if failures:
        raise PublishGateError(gate, failures)
    return tuple(passed), content_hash


# ──────────────────────────────────────────────────────────────────────────
# 2) 전이 계획 (순수) — 전이표를 조회만 한다
# ──────────────────────────────────────────────────────────────────────────
def plan_transition(
    version: SchemaConceptVersion,
    action: TransitionAction | str,
    *,
    actor: str,
    now: datetime | None = None,
    allow_compound: bool = False,
) -> SchemaConceptVersion:
    """전이 1건을 계획한다 — 반영할 새 스냅숏을 돌려준다(payload는 절대 바꾸지 않는다).

    도착 상태는 전이표가 정한다. 게이트가 붙은 간선이면 `run_gate`를 통과해야 하며, 통과
    기록(`GateRecord`)을 `qa.records`에 덧붙인다.
    """
    if not actor or not actor.strip():
        raise ValueError("actor가 비었다 — 누가 전이했는지 모르는 전이는 기록할 수 없다")
    actor = actor.strip()
    moment = now or datetime.now(UTC)

    row = resolve_transition(action, version.status, allow_compound=allow_compound)

    governance = version.governance
    if row.stamp is not None:
        governance = governance.model_copy(update={row.stamp: actor})
    candidate = version.model_copy(update={"governance": governance})

    update: dict[str, object] = {"status": row.target.value}
    if row.gate is not None:
        checks, content_hash = run_gate(candidate, row.gate)
        run_id = f"QA-{uuid.uuid4().hex[:12]}"
        record = GateRecord(
            gate=row.gate,
            action=row.action,
            judged_by=actor,
            judged_at=moment,
            checks=list(checks),
            content_hash=content_hash,
            validator_bundle_version=VALIDATOR_BUNDLE_VERSION,
            qa_run_id=run_id,
            bypassed=False,
        )
        update["qa"] = VersionQA(
            qa_status=record.verdict,
            qa_run_id=run_id,
            validator_bundle_version=VALIDATOR_BUNDLE_VERSION,
            records=[*candidate.qa.records, record],
        )
        if row.gate is GateKind.QA:
            update["integrity"] = candidate.integrity.model_copy(
                update={"content_hash": content_hash}
            )
    # published_at = "처음 발행된 시각". 복원은 발행 이력을 보존한다(복원 시각은 게이트 기록에).
    if row.target is VersionStatus.PUBLISHED and candidate.published_at is None:
        update["published_at"] = moment

    planned = candidate.model_copy(update=update)
    # 계획 결과 자체도 계약을 만족해야 한다 — 쓰기 전에 마지막으로 재검증한다.
    return _revalidate(planned)


# ──────────────────────────────────────────────────────────────────────────
# 3) 전이 실행 (DB) — concept_version·발행 포인터의 유일한 쓰기 자리
# ──────────────────────────────────────────────────────────────────────────
def _load_schema(row: ConceptVersion) -> SchemaConceptVersion:
    """ORM → 스키마. 저장된 행이 계약을 어기면 어떤 전이도 허용하지 않는다."""
    try:
        return row.to_schema()
    except ValidationError as exc:
        logger.warning(
            "publish_gate: 저장된 버전이 스키마 계약 위반 — 전이 거부 (%s, version_id=%s)",
            type(exc).__name__,
            row.version_id,
        )
        raise PublishGateError(None, [f"schema_valid: 저장된 행 {type(exc).__name__}"]) from exc


def _write_back(row: ConceptVersion, planned: SchemaConceptVersion) -> None:
    """계획된 스냅숏의 *상태 축*만 ORM 행에 반영한다 — payload는 쓰지 않는다."""
    row.status = VersionStatus(planned.status)
    row.governance = planned.governance.model_dump(mode="json")
    row.integrity = planned.integrity.model_dump(mode="json")
    row.qa = planned.qa.model_dump(mode="json")
    row.published_at = planned.published_at


async def list_versions(session: AsyncSession, concept_code: str) -> list[SchemaConceptVersion]:
    """한 개념의 모든 판 — 최신(`version_no` 큰 것)부터. **읽기 전용**(잠금·쓰기 없음).

    API 계층은 ORM `ConceptVersion`을 import할 수 없다(AST 동결 R1) — 읽기도 이 모듈을 거친다.
    저장된 행이 계약을 어기면 그 판은 건너뛰지 않고 `PublishGateError`로 알린다(조용한 누락 금지).
    """
    rows = await session.execute(
        select(ConceptVersion)
        .where(ConceptVersion.concept_id == concept_code)
        .order_by(ConceptVersion.version_no.desc())
    )
    return [_load_schema(row) for row in rows.scalars()]


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> SchemaConceptVersion:
    """판 1건 — 없으면 `LookupError`. **읽기 전용**."""
    row = (
        await session.execute(select(ConceptVersion).where(ConceptVersion.version_id == version_id))
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"concept_version {version_id} 없음")
    return _load_schema(row)


async def _lock_version(session: AsyncSession, version_id: uuid.UUID) -> ConceptVersion:
    row = (
        await session.execute(
            select(ConceptVersion)
            .where(ConceptVersion.version_id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"concept_version {version_id} 없음")
    return row


async def _lock_concept(session: AsyncSession, concept_code: str) -> Concept:
    # `populate_existing`: 잠금을 잡은 뒤의 값을 **항상 새로 읽는다**. 이미 세션에 올라온 엔티티가
    # 있으면 `FOR UPDATE`만으로는 속성이 갱신되지 않아, 호출자가 앞서 읽어 둔 낡은 발행 포인터를
    # 잠금 후 판정(`expected_current_version_id` 비교 등)에 쓰게 된다.
    concept = (
        await session.execute(
            select(Concept)
            .where(Concept.code == concept_code)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if concept is None:
        raise LookupError(f"concept {concept_code!r} 없음")
    return concept


async def _published_siblings(
    session: AsyncSession, concept_code: str, exclude: uuid.UUID
) -> list[ConceptVersion]:
    rows = await session.execute(
        select(ConceptVersion)
        .where(
            ConceptVersion.concept_id == concept_code,
            ConceptVersion.status == VersionStatus.PUBLISHED,
            ConceptVersion.version_id != exclude,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


def _refuse(exc: Exception, action: TransitionAction | str, version_id: object) -> None:
    """거부를 조용히 넘기지 않는다 — 예외 타입명과 함께 경고를 남긴다(호출자가 다시 올린다)."""
    logger.warning(
        "publish_gate: 전이 거부 (%s, action=%s, version_id=%s): %s",
        type(exc).__name__,
        getattr(action, "value", action),
        version_id,
        exc,
    )


async def create_draft(
    session: AsyncSession,
    *,
    concept_code: str,
    payload: ConceptVersionPayload,
    schema_version: str,
    created_by: str,
    change: VersionChange | None = None,
    source: VersionSource | None = None,
) -> SchemaConceptVersion:
    """새 DRAFT 판을 만든다 — `version_no`는 최신+1, `previous_version_id`는 최신 판.

    수정은 항상 새 판이다(44 §1 원칙 3). 발행본을 고치려면 그 payload로 새 DRAFT를 만든다.
    """
    if not created_by or not created_by.strip():
        raise ValueError("created_by가 비었다")
    await _lock_concept(session, concept_code)  # 같은 개념의 동시 판 생성 직렬화
    latest = (
        await session.execute(
            select(ConceptVersion)
            .where(ConceptVersion.concept_id == concept_code)
            .order_by(ConceptVersion.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    schema = SchemaConceptVersion(
        concept_id=concept_code,
        version_no=(latest.version_no + 1) if latest is not None else 1,
        schema_version=schema_version,
        status=VersionStatus.DRAFT,
        previous_version_id=latest.version_id if latest is not None else None,
        change=change or VersionChange(),
        source=source or VersionSource(),
        governance=VersionGovernance(created_by=created_by.strip()),
        integrity=VersionIntegrity(),
        qa=VersionQA(),
        payload=payload,
        created_at=datetime.now(UTC),
    )
    session.add(ConceptVersion.from_schema(schema))
    await session.flush()
    return schema


async def apply_transition(
    session: AsyncSession,
    version_id: uuid.UUID,
    action: TransitionAction | str,
    *,
    actor: str,
    now: datetime | None = None,
    expected_status: VersionStatus | None = None,
) -> SchemaConceptVersion:
    """직접 호출 가능한 전이 1건을 실행한다(복합 전용 전이는 거부).

    - publish: 같은 개념의 다른 발행본을 `supersede`하고 발행 포인터를 이 판으로 옮긴다.
    - deprecate: 발행 포인터가 이 판을 가리키면 포인터를 비운다(발행본 없음).
    - `expected_status`를 주면 **잠금 후** 실제 상태와 비교해 다르면 `StaleStatusError`로 거부한다
      (P3-12 — 화면이 읽은 상태가 그사이 바뀌었는데 같은 이름의 다른 전이가 실행되는 것을 막는다).
    """
    moment = now or datetime.now(UTC)
    # 잠금 순서 = 개념 → 판. `create_draft`·`rollback`과 같은 순서로 잡아야 같은 개념에 대한
    # 발행과 롤백이 동시에 와도 교착(deadlock)하지 않는다. 개념 코드는 잠금 없이 먼저 읽는다.
    concept_code = (
        await session.execute(
            select(ConceptVersion.concept_id).where(ConceptVersion.version_id == version_id)
        )
    ).scalar_one_or_none()
    if concept_code is None:
        raise LookupError(f"concept_version {version_id} 없음")
    concept = await _lock_concept(session, concept_code)
    row = await _lock_version(session, version_id)
    current = _load_schema(row)
    if expected_status is not None and VersionStatus(current.status) is not expected_status:
        stale = StaleStatusError(expected_status, VersionStatus(current.status))
        _refuse(stale, action, version_id)
        raise stale
    try:
        planned = plan_transition(current, action, actor=actor, now=moment)
    except Exception as exc:
        _refuse(exc, action, version_id)
        raise

    target = VersionStatus(planned.status)
    if target is VersionStatus.PUBLISHED:
        siblings = await _published_siblings(session, planned.concept_id, row.version_id)
        # 계획을 전부 끝낸 뒤에 쓴다 — 중간 실패가 반쯤 쓴 상태를 남기지 않게.
        superseded = [
            plan_transition(
                _load_schema(sibling),
                TransitionAction.SUPERSEDE,
                actor=actor,
                now=moment,
                allow_compound=True,
            )
            for sibling in siblings
        ]
        for sibling, plan in zip(siblings, superseded, strict=True):
            _write_back(sibling, plan)
        _write_back(row, planned)
        concept.current_published_version_id = row.version_id
    else:
        _write_back(row, planned)
        if VersionStatus(current.status) is VersionStatus.PUBLISHED:
            if concept.current_published_version_id == row.version_id:
                concept.current_published_version_id = None
    await session.flush()
    return planned


async def rollback(
    session: AsyncSession,
    concept_code: str,
    *,
    actor: str,
    now: datetime | None = None,
    expected_current_version_id: uuid.UUID | None = None,
) -> RollbackResult:
    """현재 발행본을 내리고 직전 발행본을 복원한다(P3-11 ⑪).

    `expected_current_version_id`를 주면 **개념 행 잠금 후** 실제 발행본과 비교해 다르면
    `StalePublishedPointerError`로 거부한다(P3-12 — 화면이 본 발행본이 그사이 바뀐 경우).

    내려간 판은 RETIRED가 된다(결함 판정 — 전이표 `rollback`). 복원 대상 = 현재 발행본보다
    `version_no`가 작은 판 중, 발행된 적이 있고(`published_at`) 지금 DEPRECATED인 가장 최근 판.
    롤백으로 내린 판은 RETIRED라 이후 롤백의 복원 후보가 되지 않는다. 복원 대상은 RESTORE
    게이트(해시 재계산 일치 포함)를 **현재 발행본을 건드리기 전에** 통과해야 한다 —
    DEPRECATED 판의 payload는 DB 트리거가 보호하지 않으므로, 내려가 있는 동안 바뀌었다면
    복원을 거부한다.
    """
    moment = now or datetime.now(UTC)
    concept = await _lock_concept(session, concept_code)
    if (
        expected_current_version_id is not None
        and concept.current_published_version_id != expected_current_version_id
    ):
        stale = StalePublishedPointerError(
            expected_current_version_id, concept.current_published_version_id
        )
        _refuse(stale, TransitionAction.ROLLBACK, expected_current_version_id)
        raise stale
    if concept.current_published_version_id is None:
        raise RollbackUnavailableError(f"{concept_code}: 현재 발행본이 없다")
    current_row = await _lock_version(session, concept.current_published_version_id)
    current = _load_schema(current_row)
    if VersionStatus(current.status) is not VersionStatus.PUBLISHED:
        raise RollbackUnavailableError(
            f"{concept_code}: 발행 포인터가 PUBLISHED가 아닌 판을 가리킨다({current.status})"
        )

    target_row = (
        await session.execute(
            select(ConceptVersion)
            .where(
                ConceptVersion.concept_id == concept_code,
                ConceptVersion.status == VersionStatus.DEPRECATED,
                ConceptVersion.published_at.is_not(None),
                ConceptVersion.version_no < current_row.version_no,
            )
            .order_by(ConceptVersion.version_no.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if target_row is None:
        raise RollbackUnavailableError(f"{concept_code}: 복원할 직전 발행본이 없다")

    try:
        restored = plan_transition(
            _load_schema(target_row),
            TransitionAction.RESTORE,
            actor=actor,
            now=moment,
            allow_compound=True,
        )
        rolled_back = plan_transition(
            current, TransitionAction.ROLLBACK, actor=actor, now=moment, allow_compound=True
        )
    except Exception as exc:
        _refuse(exc, TransitionAction.RESTORE, target_row.version_id)
        raise

    _write_back(current_row, rolled_back)
    _write_back(target_row, restored)
    concept.current_published_version_id = target_row.version_id
    await session.flush()
    return RollbackResult(
        concept_code=concept_code,
        rolled_back_version_id=current_row.version_id,
        restored_version_id=target_row.version_id,
    )


__all__ = [
    "VALIDATOR_BUNDLE_VERSION",
    "PublishGateError",
    "RollbackUnavailableError",
    "StaleStatusError",
    "StalePublishedPointerError",
    "RollbackResult",
    "compute_content_hash",
    "run_gate",
    "plan_transition",
    "create_draft",
    "list_versions",
    "get_version",
    "apply_transition",
    "rollback",
]
