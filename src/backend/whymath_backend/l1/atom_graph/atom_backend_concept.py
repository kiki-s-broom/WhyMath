"""원자 백본 코퍼스 → backend `concept` ORM 적재 — 3계층 노드 + parent 위계(원자 Phase 1).

`l1/concept_graph/backend_concept.py`(구 개념그래프 노드 적재)의 *원자 백본* 짝이다. 차이점:
  - graph.json 키가 다르다: `code`/`name`/`level`/`parent_code`/`subject_area`/
    `intrinsic_difficulty`(구 `concept_id`/`name_ko`/`domain`/`difficulty_tier`가 아님).
  - **level이 실제 값**(단원/소단원/세부개념·`ConceptLevel` 직대응) — 구 적재기의 *세부개념
    고정*과 달리 3계층을 그대로 적재한다.
  - **난이도가 이미 1~5 정수** — 구 `scale_difficulty`(0~24 tier 스케일)를 쓰지 않고
    `clamp_difficulty`로 [1,5] 범위만 방어한다(세부개념만 보유·단원/소단원은 None).
  - **parent_concept_id 해소(2-pass)**: UUID는 server 발급이라, ① 전 concept upsert(parent 없이) →
    ② code→concept_id 맵 조회 → ③ parent_code 있는 노드의 parent_concept_id를 UPDATE한다(멱등).

redaction(우선순위 #2): 레코드에 `description`·`formal_definition`·`core_proposition`(대학 핵심명제)
슬롯이 *없다* — 읽지도 채우지도 않는다(구조적 차단·NULL 유지·코퍼스/검수 보존). 풍부 메타(인지축·
노드유형·전이·원자성·학교급·연결성취기준·4요소)도 이 슬라이스 미적재(Phase 2 `concept_node` 투영).

멱등: `code`(원자ID/소단원코드/단원코드)가 UNIQUE라 `ON CONFLICT(code) DO UPDATE`로 멱등 적재하고
**UUID PK(concept_id)는 보존**한다(재적재가 PK 불변 — L2 mastery·problem_concept FK 안정성). sync
엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0). 자격증명 env·하드코딩 0.

7계층: L1 데이터 기반의 런타임 엔티티 적재. 소비(L2/L4)는 이 행을 쓰되 여기서 구현하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — backend_concept/edge·node_projection과 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.schema.enums import ConceptLevel

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.engine import Engine


# 난이도 정합 — graph.json `intrinsic_difficulty`는 1~5 정수(세부개념만·단원/소단원 None).
_DIFFICULTY_MIN: float = 1.0
_DIFFICULTY_MAX: float = 5.0
_DIFFICULTY_DECIMALS: int = 2


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(backend_concept `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clamp_difficulty(value: object) -> float | None:
    """graph `intrinsic_difficulty`(1~5 정수) → float[1.0, 5.0](None→None).

    구 `scale_difficulty`(0~24 tier 선형 스케일)와 *다르다* — 원자 백본은 이미 1~5라 스케일하지 않고
    범위만 방어 clamp한다(컬럼 Numeric(3,2)·schema ge=1 le=5 위반 방지). 비수치/빈/None은 None
    (단원·소단원 노드는 난이도가 없다). 소수 2자리 반올림(재적재 결정론).
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        num = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return None
    clamped = max(_DIFFICULTY_MIN, min(_DIFFICULTY_MAX, num))
    return round(clamped, _DIFFICULTY_DECIMALS)


@dataclass(frozen=True, slots=True)
class AtomBackendConceptRecord:
    """backend `concept` 행으로 적재할 한 노드의 *런타임 최소 식별* 값 — 원자 백본.

    `graph.json`의 한 concept(원자/단원/소단원)에서 backend 런타임 엔티티에 필요한 최소만 추린
    값이다. **`description`·`formal_definition`·`core_proposition` 슬롯이 *없다*** — 본문/검수
    책임 필드라 적재기가 채우지 않으므로 레코드에도 두지 않는다(redaction·구조적 차단).
    `parent_code`는 적재 시 code→UUID로 해석되어 `parent_concept_id`가 된다(2-pass).
    """

    code: str  # 원자ID/소단원코드/단원코드 — UNIQUE 키
    name_ko: str
    level: ConceptLevel  # 단원/소단원/세부개념 — 직대응(고정 아님)
    parent_code: str | None  # 부모 노드 code(원자→소단원·소단원→단원·단원→None)
    intrinsic_difficulty: float | None  # 1~5(세부개념만·단원/소단원 None)


def load_atom_concepts_from_graph_json(path: Path) -> list[AtomBackendConceptRecord]:
    """원자 코퍼스 `graph.json` → backend `concept` 적재 레코드 목록(redaction 청결).

    `concepts` 배열의 각 항목에서 **`code`·`name`·`level`·`parent_code`** 직결 +
    `intrinsic_difficulty`→clamp를 유도한다. `level`은 `ConceptLevel`로 변환(잘못된 값이면
    그 노드 skip — 정상 코퍼스는 단원/소단원/세부개념만). `name`이 빈/None이면 skip(NOT NULL
    위반 방지·조용한 빈 적재 금지). **`description`·`core_proposition` 등 본문은 읽지 않는다**
    (슬롯 부재).

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: code 없는 항목(코퍼스 산출은 항상 code 보유 — 방어).
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[AtomBackendConceptRecord] = []
    for record in payload.get("concepts", []):
        code = _opt_str(record.get("code"))
        if code is None:
            raise ValueError(f"graph.json 개념에 code가 없습니다: {record!r}")

        name_ko = _opt_str(record.get("name"))
        if name_ko is None:
            # name 누락(오염 입력) — NOT NULL 위반 대신 건너뛴다(정직). 정상 코퍼스는 항상 보유.
            continue

        level_raw = _opt_str(record.get("level"))
        try:
            level = ConceptLevel(level_raw)
        except ValueError:
            # 미지원 level(오염) — 조용히 넘기지 않고 건너뛴다(정상 코퍼스는 3종만).
            continue

        out.append(
            AtomBackendConceptRecord(
                code=code,
                name_ko=name_ko,
                level=level,
                parent_code=_opt_str(record.get("parent_code")),
                intrinsic_difficulty=clamp_difficulty(record.get("intrinsic_difficulty")),
            )
        )
    return out


class AtomBackendConceptStore:
    """원자 백본 → backend `concept` 적재기 — `code` 충돌 멱등 upsert + 2-pass parent 해소(sync).

    `BackendConceptStore`(구 개념그래프)의 원자 짝이다(같은 sync 좌석·멱등 규약). `upsert`는
    `INSERT ... ON CONFLICT(code) DO UPDATE`로 name_ko·level·intrinsic_difficulty를 갱신하고
    **PK(concept_id)는 보존**한다(parent_concept_id는 upsert 단계에서 *건드리지 않는다* — 2-pass).
    `resolve_parents`가 code→UUID 맵으로 parent_concept_id를 UPDATE한다(멱등). sync 엔진은 슬3
    `_build_sync_engine`을 재사용해 지연 생성·캐시한다(신규 seam 0).
    """

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def upsert(
        self, record: AtomBackendConceptRecord, *, overwrite_cms_edits: bool = False
    ) -> bool:
        """단일 노드를 backend `concept`에 upsert (멱등·`code` 충돌 갱신·UUID PK·parent 보존).

        **CMS 소유 보호(P3-26)**: `cms_edited_at`이 채워진 행(CMS가 만든 개념)은 갱신하지 않고
        False를
        돌려준다(`overwrite_cms_edits=True`면 덮어쓰고 표지를 비운다 — 파일이 다시 소유). 적재가
        새로 만든
        행·갱신한 행은 True.

        `parent_concept_id`는 INSERT/SET 컬럼에 *없다* — 2-pass(`resolve_parents`)에서 별도 UPDATE
        한다(UUID 발급 순서 비의존). `description`·`formal_definition`도 컬럼에 없다(redaction).
        `level`은 enum 값(문자열)으로 바인딩(use_enum_values 등가·PG enum 한글 값).
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from whymath_backend.db.cms_edit_marker import upsert_guard, upsert_skipped
        from whymath_backend.db.models.concept import Concept

        stmt = pg_insert(Concept).values(
            code=record.code,
            name_ko=record.name_ko,
            level=record.level.value,
            intrinsic_difficulty=record.intrinsic_difficulty,
        )
        where, release = upsert_guard(Concept, overwrite=overwrite_cms_edits)
        upsert = stmt.on_conflict_do_update(
            index_elements=[Concept.code],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "level": stmt.excluded.level,
                "intrinsic_difficulty": stmt.excluded.intrinsic_difficulty,
                **release,
            },
            where=where,
        ).returning(Concept.concept_id)
        with self._get_engine().begin() as conn:
            return not upsert_skipped(conn.execute(upsert))

    def load_code_to_uuid(self) -> dict[str, uuid.UUID]:
        """backend `concept` 전량을 단일 조회해 `{code: concept_id(UUID)}` 맵 구축(N+1 0).

        parent_code/엣지 양끝을 UUID로 해석하는 데 쓴다. 구 개념(UC code)도 포함되나 원자 code와
        공간이 달라 무해(원자 parent_code는 원자 code만 가리킴).
        """
        from sqlalchemy import select

        from whymath_backend.db.models.concept import Concept

        stmt = select(Concept.code, Concept.concept_id)
        with self._get_engine().connect() as conn:
            rows = conn.execute(stmt).all()
        return {row.code: row.concept_id for row in rows}

    def resolve_parents(self, records: Sequence[AtomBackendConceptRecord]) -> tuple[int, list[str]]:
        """2-pass parent 해소 — parent_code 있는 노드의 `parent_concept_id`를 UPDATE(멱등).

        ① code→UUID 맵 단일 구축 → ② parent_code가 있는 각 레코드의 parent를 UUID로 해석해
        `UPDATE concept SET parent_concept_id WHERE code` 실행. parent_code가 맵에 없으면 skip+로그
        (조용한 무시 금지). 반환: (해소 행 수, 미해소 skip 메시지 목록).
        """
        from sqlalchemy import bindparam, update

        from whymath_backend.db.models.concept import Concept

        code_to_uuid = self.load_code_to_uuid()
        resolved = 0
        skipped: list[str] = []
        stmt = (
            update(Concept)
            .where(Concept.code == bindparam("b_code"))
            # CMS 소유 행(P3-26)은 부모도 CMS가 정한다 — 건너뛴 행의 부모를 파일 값으로 덮지 않는다.
            # 덮어쓰기 모드에서는 upsert가 표지를 먼저 비우므로 이 조건이 자연히 통과한다.
            .where(Concept.cms_edited_at.is_(None))
            .values(parent_concept_id=bindparam("b_parent"))
        )
        with self._get_engine().begin() as conn:
            for record in records:
                if record.parent_code is None:
                    continue
                parent_uuid = code_to_uuid.get(record.parent_code)
                if parent_uuid is None:
                    skipped.append(
                        f"parent 미해소 skip: {record.code} → parent={record.parent_code}(맵 부재)"
                    )
                    continue
                conn.execute(stmt, {"b_code": record.code, "b_parent": parent_uuid})
                resolved += 1
        return resolved, skipped


def populate_atom_concepts(
    records: Sequence[AtomBackendConceptRecord],
    *,
    settings: Settings | None = None,
    store: AtomBackendConceptStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> tuple[int, list[str]]:
    """원자 백본 노드를 backend `concept`에 멱등 적재 + parent 해소. 반환=(적재 행 수, parent skip).

    ① 전 레코드 upsert(parent 없이) → ② `resolve_parents`로 parent_concept_id UPDATE. 멱등(재실행 시
    갱신·UUID 보존). store 미주입 시 슬3 sync 엔진 재사용 store를 만든다.

    **CMS 소유 보호(P3-26)**: CMS가 만든 개념(`cms_edited_at` 있음)과 코드가 같은 레코드는 건너뛰고
    `conflicts`에 `concept:<code>`로 보고한다 — 반환 행 수에는 포함하지 않는다.
    """
    from whymath_backend.db.cms_edit_marker import format_conflict

    resolved_settings = settings if settings is not None else get_settings()
    concept_store = (
        store if store is not None else AtomBackendConceptStore(settings=resolved_settings)
    )
    written = 0
    for record in records:
        if concept_store.upsert(record, overwrite_cms_edits=overwrite_cms_edits):
            written += 1
        elif conflicts is not None:
            conflicts.append(format_conflict("concept", record.code))
    _resolved, parent_skipped = concept_store.resolve_parents(records)
    return written, parent_skipped


__all__ = [
    "AtomBackendConceptRecord",
    "AtomBackendConceptStore",
    "clamp_difficulty",
    "load_atom_concepts_from_graph_json",
    "populate_atom_concepts",
]
