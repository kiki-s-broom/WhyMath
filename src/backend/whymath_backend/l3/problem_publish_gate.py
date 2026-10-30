"""Problem Publish Gate — 문항 판(problem_version)의 유일한 writer (EOS-190).

설계 정본: `docs/architecture/44_eos_version_management.md` §6.4(Entity의 현재 버전 포인터)·§7
(Lifecycle)·§9(Publish Gate). 짝 모듈은 `l3/publish_gate.py`(개념 판, EOS-50)이며 **같은 전이표**
(`schema/version_lifecycle.py`)를 조회한다 — 도착 상태를 이 모듈이 고르지 않는다.

## 왜 이 모듈이 있는가

`problem_version`에 행을 쓰는 운영 코드가 0건이라(ARCH-31 §5) EOS-47이 시도 행에 복사하는
`problem.problem_version_id` 포인터는 전부 NULL이었다 — 고정 장치는 정확했지만 고정할 판이 없었다.
이 모듈이 그 판을 만드는 **유일한 자리**다(AST 동결 — `tests/backend/l3/
test_problem_publish_gate_enforcement.py`).

## 세 층 (publish_gate와 동형)

1. **검증 파이프라인**(순수): `run_gate(version, gate, live_content_hash=...)`가 검사를 전부 돌리고
   하나라도 실패하면 `PublishGateError`. 검사: `schema_valid`·`schema_version_format`·
   `entity_type`('Problem')·`content_hash`·`governance_complete`·`qa_record_bound`, 그리고 이
   모듈 고유의 **`live_content_current`**·**`problem_metadata_complete`**(둘 다 PUBLISH 전용).
2. **전이 계획**(순수): `plan_transition`이 전이표를 조회해 새 스냅숏을 만든다.
3. **전이 실행**(DB): `create_draft`·`apply_transition`. `problem_version` 행과
   `problem.problem_version_id`를 쓰는 **유일한 자리**.

## 이 모듈 고유의 검사 — `live_content_current`

개념 판과 달리 문항은 **판과 별개로 라이브 행이 서빙된다**(`problem` 테이블이 곧 서빙 원본).
승인된 초안이 라이브 문항과 어긋난 채(그 사이 CMS가 정답을 고침) 발행되면, EOS-47이 시도에
박는 "그 학생이 푼 판"의 payload가 학생이 실제로 본 문항과 달라진다 — 고정의 의미가 사라진다.
그래서 PUBLISH 전이는 **잠금을 잡은 뒤의 라이브 문항 스냅숏 해시 == 판 payload 해시**를 요구한다.
대조하지 못하면(라이브 행이 스냅숏 계약을 어김) 통과가 아니라 **실패**다(모른다 ≠ 통과).
어긋나면 발행 대신 새 초안을 만들어 다시 승인받는다(수정은 항상 새 판 — 44 §1 원칙 3).

## 이 모듈 고유의 검사 — `problem_metadata_complete` (P3-04)

**7필드(난이도·스킬·개념·해설·정답·오개념 서명·힌트 전략) 중 하나라도 없으면 PUBLISH는 거부된다.**
정의는 `schema/problem_metadata.py`가, 측정은 `l3/problem_metadata_evidence.py`가 소유하고 이
모듈은 PUBLISH 게이트에서 그 판정을 부르기만 한다 — 문항이 Published가 되는 유일한 길이므로 여기
한 곳에서 막으면 우회로가 없다(CMS는 `status`·`is_published`·`current_published_version_id`를 직접
고칠 수 없다 — `api/admin_cms_resources.WORKFLOW_STATE_COLUMNS`).
증거를 못 쟀으면(`metadata_evidence is None`) 통과가 아니라 **실패**다(모른다 ≠ 통과).
7필드는 QA에서 요구하지 않는다 — 조건을 못 채운 판은 APPROVED에서 멈춘다(지시문 세트 16/20).
이 검사는 *발행 순간*의 라이브 행을 잰다 — 발행 이후 편집이 필드를 비우는 경우는 EOS-195 소관이다.

## 트랜잭션 계약

실행 함수는 `flush`까지만 하고 `commit`하지 않는다 — 호출자가 트랜잭션 경계를 가진다. 게이트가
실패하면 **아무 것도 쓰기 전에** 예외가 난다. 잠금 순서는 항상 **문항 → 판**(교착 방지, 동결).

## 이 모듈이 하지 않는 것 (추적: backlog 후속 태스크)

- **호출자는 이 모듈의 소유가 아니다.** 운영 호출자는 관리자 CMS의 문항 판 표면
  (`api/admin_cms_problem_versions.py`, EOS-194)이며, 이 모듈은 그 표면의 권한·감사·HTTP 매핑을
  모른다. `outcome=pinned` 비율은 운영자가 문항을 실제로 발행한 만큼만 0을 벗어난다.
- **Rollback·Restore 없음.** 전이표의 복합 전용 간선(rollback·restore)은 호출 경로가 없어
  구현하지 않았다. 필요해지면 이 모듈에 더한다(포인터 쓰기 자리를 하나로 유지).
- **발행 이후의 제자리 편집을 새 판으로 만들지 않는다.** CMS가 `problem` 행을 직접 고치면 발행된
  판의 payload와 라이브 행이 갈라진다 — `live_content_current`는 *발행 순간*만 막는다.
- **학생 노출 판정을 하지 않는다.** 문항 노출은 `review_status`·저작권 두 축이 소유한다. 이 모듈은
  `ReviewStatus`·`review_status`·`is_published`·`publish_at`을 읽지도 쓰지도 않는다(AST 동결 B1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.problem import Problem
from whymath_backend.db.models.problem_version import ProblemVersion
from whymath_backend.l3.problem_metadata_evidence import load_metadata_evidence
from whymath_backend.l3.publish_gate import PublishGateError, StaleStatusError
from whymath_backend.schema.problem_metadata import ProblemMetadataEvidence, evaluate_metadata
from whymath_backend.schema.problem_version import ProblemVersion as SchemaProblemVersion
from whymath_backend.schema.problem_version import ProblemVersionPayload
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
from whymath_backend.schema.version_lifecycle import UndefinedTransitionError, resolve_transition

logger = logging.getLogger("whymath.l3.problem_publish_gate")

# 검사 묶음 버전 — 검사 항목·판정 규칙을 바꾸면 올린다(§9 `validator_bundle_version`).
VALIDATOR_BUNDLE_VERSION = "eos190-problem-publish-gate@2"

#: `create_draft`가 payload 스키마 태그를 따로 받지 않을 때 쓰는 값(ARCH-31 docstring 예시와 동일).
PAYLOAD_SCHEMA_VERSION = "problem-schema@1"

# 해시 알고리즘 접두 — 알고리즘을 바꿔도 옛 해시와 새 해시가 섞여 오판되지 않게 값에 박는다.
_HASH_PREFIX = "sha256:"

_SCHEMA_VERSION_RE = re.compile(r"^[a-z][a-z0-9_-]*@\d+(\.\d+)?$")
_ENTITY_TYPE = "Problem"

# 게이트별 필수 거버넌스 필드 — QA 시점엔 승인자가 아직 없다(승인이 그 게이트의 결과다).
# 이 모듈은 QA·PUBLISH만 소유한다(RESTORE는 rollback과 함께 범위 밖 — 모듈 docstring).
_REQUIRED_GOVERNANCE: dict[GateKind, tuple[str, ...]] = {
    GateKind.QA: ("created_by", "reviewed_by"),
    GateKind.PUBLISH: ("created_by", "reviewed_by", "approved_by"),
}


# ──────────────────────────────────────────────────────────────────────────
# 1) 스냅숏·해시·검증 파이프라인 (순수)
# ──────────────────────────────────────────────────────────────────────────
def _text_hash(text: str | None) -> str | None:
    """발문·정답 변경 탐지용 해시. 값이 없으면 None(없는 본문에 해시를 날조하지 않는다)."""
    if text is None:
        return None
    return _HASH_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_payload(problem: Problem) -> ProblemVersionPayload:
    """라이브 `problem` 행 → 판 payload 스냅숏. 계약을 어기는 행이면 `ValidationError`.

    payload는 문항의 *내용을 정의하는* 필드만 담는다(`ProblemVersionPayload` docstring). 난이도
    5축·검수 상태·임베딩은 각자의 컬럼이 정본이라 복제하지 않는다. 평가원·EBS·교과서 출처에
    본문이 남아 있는 행이면 payload의 저작권 validator가 거부한다 — 판 경로가 우회로가 되지 않는다.
    """
    overall = problem.difficulty_overall
    return ProblemVersionPayload(
        source_type=problem.source_type,
        subject=problem.subject,
        curriculum_version=problem.curriculum_version,
        unit_codes=list(problem.unit_codes or []),
        question_format=problem.question_format,
        answer_format=problem.answer_format,
        points=problem.points,
        question_text=problem.question_text,
        choices=list(problem.choices) if problem.choices is not None else None,
        answer=problem.answer,
        answer_explanation=problem.answer_explanation,
        stem_hash=_text_hash(problem.question_text),
        answer_hash=_text_hash(problem.answer),
        difficulty_at_publish=float(overall) if overall is not None else None,
    )


def compute_content_hash(payload: ProblemVersionPayload) -> str:
    """payload의 결정론 해시 — 필드 순서·JSONB 왕복과 무관하게 같은 내용이면 같은 값.

    `model_dump(mode="json")`로 enum을 값으로 고정한 뒤 키 정렬 JSON을 sha256한다.
    """
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return _HASH_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revalidate(version: SchemaProblemVersion) -> SchemaProblemVersion:
    """직렬화 → 재검증. `model_copy(update=...)`는 검증을 건너뛰므로 게이트는 이것으로 본다."""
    return SchemaProblemVersion.model_validate(version.model_dump(mode="json"))


def _qa_record_bound(version: SchemaProblemVersion, content_hash: str) -> bool:
    """지금 내용의 해시로 통과한 QA 게이트 기록이 있는가."""
    return any(
        record.gate == GateKind.QA.value
        and record.verdict == "PASSED"
        and record.content_hash == content_hash
        for record in version.qa.records
    )


def run_gate(
    version: SchemaProblemVersion,
    gate: GateKind,
    *,
    live_content_hash: str | None = None,
    metadata_evidence: ProblemMetadataEvidence | None = None,
) -> tuple[tuple[str, ...], str]:
    """게이트 검사를 **전부** 돌린다 — (통과 검사 이름들, 산출 해시). 하나라도 실패하면 예외.

    `live_content_hash`·`metadata_evidence`는 PUBLISH 게이트에서만 쓰인다 — 잠금 후 라이브 문항의
    스냅숏 해시와 7필드 증거. PUBLISH인데 None이면 대조·측정하지 못한 것이므로 **실패**다
    (모른다 ≠ 통과).
    """
    if gate not in _REQUIRED_GOVERNANCE:
        raise ValueError(f"이 모듈은 QA·PUBLISH 게이트만 소유한다: {gate!r}")
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

    if gate is GateKind.PUBLISH:
        if _qa_record_bound(checked, content_hash):
            passed.append("qa_record_bound")
        else:
            failures.append("qa_record_bound: 지금 내용으로 통과한 QA 기록이 없다")

        if live_content_hash is None:
            failures.append("live_content_current: 라이브 문항 내용을 대조하지 못했다")
        elif live_content_hash != content_hash:
            failures.append(
                "live_content_current: 승인 이후 라이브 문항이 바뀌었다(새 초안으로 다시 승인)"
            )
        else:
            passed.append("live_content_current")

        if metadata_evidence is None:
            failures.append("problem_metadata_complete: 7필드를 측정하지 못했다")
        else:
            verdict = evaluate_metadata(metadata_evidence)
            if verdict.complete:
                passed.append("problem_metadata_complete")
            else:
                failures.extend(f"problem_metadata_complete: {line}" for line in verdict.failures())

    if failures:
        raise PublishGateError(gate, failures)
    return tuple(passed), content_hash


# ──────────────────────────────────────────────────────────────────────────
# 2) 전이 계획 (순수) — 전이표를 조회만 한다
# ──────────────────────────────────────────────────────────────────────────
def plan_transition(
    version: SchemaProblemVersion,
    action: TransitionAction | str,
    *,
    actor: str,
    live_content_hash: str | None = None,
    metadata_evidence: ProblemMetadataEvidence | None = None,
    now: datetime | None = None,
    allow_compound: bool = False,
) -> SchemaProblemVersion:
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
        checks, content_hash = run_gate(
            candidate,
            row.gate,
            live_content_hash=live_content_hash,
            metadata_evidence=metadata_evidence,
        )
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
    # published_at = "처음 발행된 시각".
    if row.target is VersionStatus.PUBLISHED and candidate.published_at is None:
        update["published_at"] = moment

    planned = candidate.model_copy(update=update)
    # 계획 결과 자체도 계약을 만족해야 한다 — 쓰기 전에 마지막으로 재검증한다.
    return _revalidate(planned)


# ──────────────────────────────────────────────────────────────────────────
# 3) 전이 실행 (DB) — problem_version·발행 포인터의 유일한 쓰기 자리
# ──────────────────────────────────────────────────────────────────────────
def _load_schema(row: ProblemVersion) -> SchemaProblemVersion:
    """ORM → 스키마. 저장된 행이 계약을 어기면 어떤 전이도 허용하지 않는다."""
    try:
        return row.to_schema()
    except ValidationError as exc:
        logger.warning(
            "problem_publish_gate: 저장된 판이 스키마 계약 위반 — 전이 거부 (%s, version_id=%s)",
            type(exc).__name__,
            row.version_id,
        )
        raise PublishGateError(None, [f"schema_valid: 저장된 행 {type(exc).__name__}"]) from exc


def _write_back(row: ProblemVersion, planned: SchemaProblemVersion) -> None:
    """계획된 스냅숏의 *상태 축*만 ORM 행에 반영한다 — payload는 쓰지 않는다."""
    row.status = VersionStatus(planned.status)
    row.governance = planned.governance.model_dump(mode="json")
    row.integrity = planned.integrity.model_dump(mode="json")
    row.qa = planned.qa.model_dump(mode="json")
    row.published_at = planned.published_at


def _refuse(exc: Exception, action: TransitionAction | str, version_id: object) -> None:
    """거부를 조용히 넘기지 않는다 — 예외 타입명과 함께 경고를 남긴다(호출자가 다시 올린다)."""
    logger.warning(
        "problem_publish_gate: 전이 거부 (%s, action=%s, version_id=%s): %s",
        type(exc).__name__,
        getattr(action, "value", action),
        version_id,
        exc,
    )


async def list_versions(session: AsyncSession, problem_id: uuid.UUID) -> list[SchemaProblemVersion]:
    """한 문항의 모든 판 — 최신(`version_no` 큰 것)부터. **읽기 전용**(잠금·쓰기 없음).

    API 계층은 ORM `ProblemVersion`을 import할 수 없다(AST 동결 R1) — 읽기도 이 모듈을 거친다.
    저장된 행이 계약을 어기면 그 판은 건너뛰지 않고 `PublishGateError`로 알린다(조용한 누락 금지).
    """
    rows = await session.execute(
        select(ProblemVersion)
        .where(ProblemVersion.problem_id == problem_id)
        .order_by(ProblemVersion.version_no.desc())
    )
    return [_load_schema(row) for row in rows.scalars()]


async def problem_exists(session: AsyncSession, problem_id: uuid.UUID) -> bool:
    """문항이 있는가 — **읽기 전용**(잠금·엔티티 적재 없음, id 한 컬럼만 읽는다).

    API 계층은 ORM을 직접 잡지 않는다(데이터 접근 baseline) — "없는 문항"(404)과 "판이 0건인 문항"
    (빈 목록)을 구분하려는 호출자는 이 함수를 거친다. 엔티티를 세션에 올리지 않으므로 호출자의
    트랜잭션 경계(commit 뒤 만료)에 영향을 주지 않는다.
    """
    found = (
        await session.execute(select(Problem.problem_id).where(Problem.problem_id == problem_id))
    ).scalar_one_or_none()
    return found is not None


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> SchemaProblemVersion:
    """판 1건 — 없으면 `LookupError`. **읽기 전용**."""
    row = (
        await session.execute(select(ProblemVersion).where(ProblemVersion.version_id == version_id))
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"problem_version {version_id} 없음")
    return _load_schema(row)


async def _lock_problem(session: AsyncSession, problem_id: uuid.UUID) -> Problem:
    # `populate_existing`: 잠금을 잡은 뒤의 값을 **항상 새로 읽는다**. 이미 세션에 올라온 엔티티가
    # 있으면 `FOR UPDATE`만으로는 속성이 갱신되지 않아, 호출자가 앞서 읽어 둔 낡은 문항 내용으로
    # `live_content_current`를 판정하게 된다(그러면 이 검사가 변경을 못 본다).
    problem = (
        await session.execute(
            select(Problem)
            .where(Problem.problem_id == problem_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if problem is None:
        raise LookupError(f"problem {problem_id} 없음")
    return problem


async def _lock_version(session: AsyncSession, version_id: uuid.UUID) -> ProblemVersion:
    row = (
        await session.execute(
            select(ProblemVersion)
            .where(ProblemVersion.version_id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"problem_version {version_id} 없음")
    return row


async def _published_siblings(
    session: AsyncSession, problem_id: uuid.UUID, exclude: uuid.UUID
) -> list[ProblemVersion]:
    rows = await session.execute(
        select(ProblemVersion)
        .where(
            ProblemVersion.problem_id == problem_id,
            ProblemVersion.status == VersionStatus.PUBLISHED,
            ProblemVersion.version_id != exclude,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


def _live_content_hash_if_needed(
    problem: Problem,
    action: TransitionAction | str,
    current: SchemaProblemVersion,
    version_id: uuid.UUID,
) -> str | None:
    """PUBLISH 게이트가 붙는 전이일 때만 라이브 문항 스냅숏 해시를 계산한다.

    다른 전이에서는 계산하지 않는다 — 라이브 행이 스냅숏 계약을 어겨도 SUBMIT 같은 전이를 막을
    이유가 없다. 계산이 필요한데 실패하면 None을 돌려 `run_gate`가 **실패로** 판정하게 한다
    (예외 타입명 포함 경고 — 조용히 삼키지 않는다).
    """
    try:
        transition = resolve_transition(action, current.status)
    except UndefinedTransitionError:
        return None  # 미정의 전이는 plan_transition이 같은 예외로 거부한다
    if transition.gate is not GateKind.PUBLISH:
        return None
    try:
        return compute_content_hash(snapshot_payload(problem))
    except ValidationError as exc:
        logger.warning(
            "problem_publish_gate: 라이브 문항이 스냅숏 계약 위반 — 대조 불가로 발행 거부 "
            "(%s, version_id=%s)",
            type(exc).__name__,
            version_id,
        )
        return None


async def _metadata_evidence_if_needed(
    session: AsyncSession,
    problem: Problem,
    action: TransitionAction | str,
    current: SchemaProblemVersion,
) -> ProblemMetadataEvidence | None:
    """PUBLISH 게이트가 붙는 전이일 때만 7필드 증거를 읽는다(읽기 전용 · 문항 잠금 뒤).

    다른 전이에서는 읽지 않는다 — 7필드는 발행의 조건이지 제출·검토의 조건이 아니다(조건을 못 채운
    판은 APPROVED에서 멈춘다). 읽다가 DB 예외가 나면 그대로 올라가 전이를 중단한다 — 측정 실패가
    "필드가 있다"로 위장되는 길은 없다.
    """
    try:
        transition = resolve_transition(action, current.status)
    except UndefinedTransitionError:
        return None  # 미정의 전이는 plan_transition이 같은 예외로 거부한다
    if transition.gate is not GateKind.PUBLISH:
        return None
    return await load_metadata_evidence(session, problem)


async def create_draft(
    session: AsyncSession,
    *,
    problem_id: uuid.UUID,
    created_by: str,
    payload: ProblemVersionPayload | None = None,
    schema_version: str = PAYLOAD_SCHEMA_VERSION,
    change: VersionChange | None = None,
    source: VersionSource | None = None,
) -> SchemaProblemVersion:
    """새 DRAFT 판을 만든다 — `version_no`는 최신+1, `previous_version_id`는 최신 판.

    `payload`를 생략하면 **문항 행을 잠근 뒤의 라이브 내용**을 스냅숏한다. 수정은 항상 새 판이다
    (44 §1 원칙 3) — 발행본을 고치려면 새 DRAFT를 만든다.
    """
    if not created_by or not created_by.strip():
        raise ValueError("created_by가 비었다")
    problem = await _lock_problem(session, problem_id)  # 같은 문항의 동시 판 생성 직렬화
    if payload is None:
        try:
            payload = snapshot_payload(problem)
        except ValidationError as exc:
            logger.warning(
                "problem_publish_gate: 라이브 문항이 스냅숏 계약 위반 — 초안 거부 "
                "(%s, problem_id=%s)",
                type(exc).__name__,
                problem_id,
            )
            raise PublishGateError(
                None, [f"schema_valid: 라이브 문항 {type(exc).__name__}"]
            ) from exc
    latest = (
        await session.execute(
            select(ProblemVersion)
            .where(ProblemVersion.problem_id == problem_id)
            .order_by(ProblemVersion.version_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    schema = SchemaProblemVersion(
        problem_id=problem_id,
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
    session.add(ProblemVersion.from_schema(schema))
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
) -> SchemaProblemVersion:
    """직접 호출 가능한 전이 1건을 실행한다(복합 전용 전이는 거부).

    - publish: 같은 문항의 다른 발행본을 `supersede`하고 `problem.problem_version_id`를 이 판으로
      옮긴다. 이 포인터 전환이 EOS-47의 시도 버전 고정이 읽는 값이다.
    - deprecate: 포인터가 이 판을 가리키면 포인터를 비운다(서빙 기준 판 없음).
    - `expected_status`를 주면 **잠금 후** 실제 상태와 비교해 다르면 `StaleStatusError`로 거부한다
      (화면이 읽은 상태가 그사이 바뀐 낙관적 동시성).
    """
    moment = now or datetime.now(UTC)
    # 잠금 순서 = 문항 → 판. 문항 id는 잠금 없이 먼저 읽는다(`create_draft`와 같은 순서여야
    # 같은 문항에 대한 초안 생성과 발행이 동시에 와도 교착하지 않는다).
    problem_id = (
        await session.execute(
            select(ProblemVersion.problem_id).where(ProblemVersion.version_id == version_id)
        )
    ).scalar_one_or_none()
    if problem_id is None:
        raise LookupError(f"problem_version {version_id} 없음")
    problem = await _lock_problem(session, problem_id)
    row = await _lock_version(session, version_id)
    current = _load_schema(row)
    if expected_status is not None and VersionStatus(current.status) is not expected_status:
        stale = StaleStatusError(expected_status, VersionStatus(current.status))
        _refuse(stale, action, version_id)
        raise stale
    live_hash = _live_content_hash_if_needed(problem, action, current, version_id)
    evidence = await _metadata_evidence_if_needed(session, problem, action, current)
    try:
        planned = plan_transition(
            current,
            action,
            actor=actor,
            live_content_hash=live_hash,
            metadata_evidence=evidence,
            now=moment,
        )
    except Exception as exc:
        _refuse(exc, action, version_id)
        raise

    target = VersionStatus(planned.status)
    if target is VersionStatus.PUBLISHED:
        siblings = await _published_siblings(session, problem_id, row.version_id)
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
        problem.problem_version_id = row.version_id
    else:
        _write_back(row, planned)
        if VersionStatus(current.status) is VersionStatus.PUBLISHED:
            if problem.problem_version_id == row.version_id:
                problem.problem_version_id = None
    await session.flush()
    return planned


__all__ = [
    "VALIDATOR_BUNDLE_VERSION",
    "PAYLOAD_SCHEMA_VERSION",
    "snapshot_payload",
    "compute_content_hash",
    "run_gate",
    "plan_transition",
    "create_draft",
    "list_versions",
    "get_version",
    "problem_exists",
    "apply_transition",
]
