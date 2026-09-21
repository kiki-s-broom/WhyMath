"""437-키 자산의 원자 축 이전 — 크로스워크 경유 behavior_skills 전파·K-12 원자 연결 (S0-2).

원자 백본 정합성 회복(로드맵 S0) Phase 4-ⓒ. S0-1이 커밋한 437↔원자 크로스워크 코퍼스
(`data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl`·437행·데이터카드
`docs/data/concept_atom_crosswalk_v1.md`)를 *읽기만* 하여(rekey 금지 — 구 437 키 자산의 키는
불변·크로스워크가 다리) 두 437-키 자산을 원자 축에 투영한다:

  ① **behavior_skills 전파**: #419가 `concept_graph_v1/concepts.jsonl`에 저작한 concept→skill
     매핑(skill_id 1~3개·404/437)을 크로스워크 경유로 `atom_node.behavior_skills`에 전파.
  ② **K-12 콘텐츠 원자 연결**: `concept_content` K-12 행(code=구 437 개념코드)에 크로스워크의
     atom_codes를 투영(Phase 3 Slice 1이 "원자 연결은 Phase 4"로 예고한 좌석). **대학 행(409·
     소단원코드 키)은 무변경** — 대학 code는 이미 원자 그래프와 같은 키 공간이라 원자 정합(다리
     불요)이며, 갱신 SQL이 `scope='K-12'` 필터로 구조적으로 차단한다.
  ③ **런타임 concept.behavior_skills 전파(SKB-01)**: ①과 *같은* 원자→skills 매핑을 런타임
     `concept` 테이블(atom_backend_concept 적재·`concept.code`=원자/소단원/단원 code)에도 전파한다.
     `l1/atom_graph/atom_backend_concept.py`가 `concept` 행을 채우지만 `behavior_skills`는 건드리지
     않아(신규 행은 `server_default '{}'`) 이 컬럼이 항상 비어 있었다(EOS-63 실측: 2,683/2,683
     전량 빈 배열). `concept.code`는 원자 code와 같은 키 공간이므로(atom_backend_concept docstring)
     ①의 매핑을 다리 없이 그대로 재사용한다 — 별도 유도 불요.

────────────────────────────────────────────────────────────────────────────
전파 규칙 (S0-2 확정 — 메인 세션 결정·데이터카드 §소비처 동기)
────────────────────────────────────────────────────────────────────────────
각 크로스워크 행의 **atom_codes 전체**(primary만 아님)에 해당 concept의 behavior_skills를
전파한다. 한 원자에 복수 concept이 닿으면 **union + dedup + 사전순 정렬**.

근거: 스킬(인지 행동)은 개념의 *구성 원자 전체*에 적용되는 속성이지 배타 귀속이 아니다 —
"이차방정식 풀이" 스킬은 이차방정식 개념을 이루는 원자 모두에서 발휘된다. 크로스워크의
primary 귀속 규칙(`primary_atom_code` 1개 귀속)은 mastery/오개념 *이력 귀속*용 계약이지
(데이터카드 §4) 스킬 *전파*용이 아니다. `unmapped`(atom_codes 빈) 행은 강제 귀속 없이
skip + 보고한다(조용히 넘기지 않음 — 크로스워크 소비 계약 §4).

────────────────────────────────────────────────────────────────────────────
조인 축 (derive.py 미러 — 크로스워크 유도와 동일 다리)
────────────────────────────────────────────────────────────────────────────
크로스워크 키는 canonical `concept_id`(`math.<area>.<slug>`)인데, behavior_skills 저작 좌석
(concepts.jsonl)과 concept_content K-12 키는 원천 `src_id`(예 'N1'·'A1') 축이다. 크로스워크
유도(`data_pipeline/concept_atom_crosswalk/derive.py`)와 동일하게 `concept_graph_v1/graph.json`
의 `concept_id`↔`source_id`(=`src_id`)로 조인한다. 조인 실패는 즉시 오류(조용히 빠뜨리지 않음).

────────────────────────────────────────────────────────────────────────────
갱신 의미론 — UPDATE(upsert 아님)
────────────────────────────────────────────────────────────────────────────
대상 행은 각자의 정본 projection(`atom_node_projection`·`concept_content/projection`)이 이미
적재한 *기존 행*이다 — 이 모듈은 이전 컬럼만 멱등 UPDATE한다(행 생성 없음·다른 컬럼 무접촉).
대상 행 부재(선행 populate 미실행)는 조용히 넘기지 않고 `missing`으로 보고한다. 크로스워크가
닿지 않는 원자(비크로스워크 원자)는 server_default '{}' 그대로다.

sync 엔진은 슬3 `_build_sync_engine`을 재사용한다(신규 seam 0·형제 projection 동형).
7계층: L1 데이터 기반의 *영속 프로젝션 갱신*. 소비(L2 mastery·L4)는 후속(역방향 의존 금지).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.concept_content import CONTENT_SCOPE_K12

# 슬3 sync 엔진 빌더 재사용(신규 seam 0) — atom_node_projection·concept_content 동일 규약.
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class CrosswalkRecord:
    """크로스워크 1행 — 이전에 필요한 최소 필드만(437↔원자·데이터카드 §2).

    `atom_codes`가 빈 튜플이면 `unmapped`(강제 귀속 금지·skip+보고 대상)다. 감사 필드
    (match_method·confidence·evidence)는 이전에 불요라 슬롯을 두지 않는다.
    """

    concept_id: str
    atom_codes: tuple[str, ...]
    primary_atom_code: str | None


def load_crosswalk_records(path: Path) -> list[CrosswalkRecord]:
    """크로스워크 코퍼스 crosswalk.jsonl → 레코드 목록(concept_id 유일성 검증).

    Raises:
        FileNotFoundError: crosswalk.jsonl 부재.
        ValueError: concept_id 누락/중복(코퍼스 계약 위반 — 조용히 넘기지 않음).
    """
    records: list[CrosswalkRecord] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        concept_id = str(row.get("concept_id") or "").strip()
        if not concept_id:
            raise ValueError(f"crosswalk 행에 concept_id 없음: {row!r}")
        if concept_id in seen:
            raise ValueError(f"crosswalk concept_id 중복: {concept_id!r}")
        seen.add(concept_id)
        raw_codes = row.get("atom_codes")
        codes = tuple(str(c) for c in raw_codes) if isinstance(raw_codes, (list, tuple)) else ()
        raw_primary = row.get("primary_atom_code")
        records.append(
            CrosswalkRecord(
                concept_id=concept_id,
                atom_codes=codes,
                primary_atom_code=str(raw_primary) if raw_primary else None,
            )
        )
    return records


def load_concept_src_bridge(graph_path: Path) -> dict[str, str]:
    """구 437 코퍼스 graph.json → `concept_id`(canonical) → `source_id`(src_id) 다리.

    크로스워크 유도(derive.py)와 동일 조인 축이다 — 크로스워크는 concept_id 키, behavior_skills
    저작 좌석(concepts.jsonl)·concept_content K-12 키는 src_id 축이라 이 다리가 필요하다.

    Raises:
        FileNotFoundError: graph.json 부재.
        ValueError: concept_id/source_id 누락 또는 concept_id 중복(조인 실패 — 즉시 오류).
    """
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    bridge: dict[str, str] = {}
    for node in payload.get("concepts", []):
        concept_id = str(node.get("concept_id") or "").strip()
        src_id = str(node.get("source_id") or "").strip()
        if not concept_id or not src_id:
            raise ValueError(f"graph.json 개념 노드에 concept_id/source_id 없음: {node!r}")
        if concept_id in bridge:
            raise ValueError(f"graph.json concept_id 중복: {concept_id!r}")
        bridge[concept_id] = src_id
    return bridge


def load_behavior_skills_by_src(concepts_jsonl_path: Path) -> dict[str, tuple[str, ...]]:
    """#419 저작 좌석 concepts.jsonl → `src_id` → behavior_skills(dedup·사전순).

    concepts.jsonl이 behavior_skills의 저작 정본이다(#419·404/437 커버·미매핑 33은 `[]`).
    graph.json에도 같은 필드가 복제돼 있으나 저작 좌석을 원천으로 읽는다.

    Raises:
        FileNotFoundError: concepts.jsonl 부재.
        ValueError: src_id 누락/중복(코퍼스 계약 위반).
    """
    skills_by_src: dict[str, tuple[str, ...]] = {}
    for line in concepts_jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        src_id = str(row.get("src_id") or "").strip()
        if not src_id:
            raise ValueError(f"concepts.jsonl 행에 src_id 없음: {row!r}")
        if src_id in skills_by_src:
            raise ValueError(f"concepts.jsonl src_id 중복: {src_id!r}")
        raw_skills = row.get("behavior_skills")
        skills = (
            tuple(sorted({str(s) for s in raw_skills}))
            if isinstance(raw_skills, (list, tuple))
            else ()
        )
        skills_by_src[src_id] = skills
    return skills_by_src


def derive_atom_behavior_skills(
    crosswalk: list[CrosswalkRecord],
    concept_src_bridge: Mapping[str, str],
    skills_by_src: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """전파 규칙 본체 — 원자 code → behavior_skills(union+dedup·사전순) 유도.

    각 크로스워크 행의 **atom_codes 전체**에 concept의 behavior_skills를 전파한다(primary만
    아님 — 스킬은 개념의 구성 원자 전체에 적용되는 인지 행동·배타 귀속 아님·모듈 docstring 참조).
    한 원자에 복수 concept이 닿으면 union+dedup, 결과는 사전순 정렬(결정론). `unmapped`
    (atom_codes 빈) 행은 skip한다(강제 귀속 금지 — skip 보고는 호출자 몫). 스킬이 빈 concept의
    원자도 키로 남긴다(빈 튜플 — 재실행 시 stale 값 청소·멱등).

    Raises:
        ValueError: 크로스워크 concept_id가 다리/저작 좌석에 없음(코퍼스 조인 실패).
    """
    acc: dict[str, set[str]] = {}
    for record in crosswalk:
        if not record.atom_codes:  # unmapped — 강제 귀속 금지(계약 §4)
            continue
        src_id = concept_src_bridge.get(record.concept_id)
        if src_id is None:
            raise ValueError(f"크로스워크 concept_id가 graph.json에 없음: {record.concept_id!r}")
        if src_id not in skills_by_src:
            raise ValueError(f"concepts.jsonl에 src_id {src_id!r} 없음 — 코퍼스 조인 실패")
        skills = skills_by_src[src_id]
        for atom_code in record.atom_codes:
            acc.setdefault(atom_code, set()).update(skills)
    return {atom: tuple(sorted(skills)) for atom, skills in acc.items()}


def derive_k12_content_atom_codes(
    crosswalk: list[CrosswalkRecord],
    concept_src_bridge: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """K-12 콘텐츠 원자 연결 유도 — `concept_content` code(=src_id) → atom_codes(dedup·사전순).

    크로스워크 행 1건 = 구 개념 1건 = K-12 콘텐츠 행 1건(코드 축 동일·src_id)이다. `unmapped`
    행은 skip(강제 귀속 금지). 대학 행은 이 유도에 아예 등장하지 않는다(크로스워크가 437 구
    개념만 다룸 — 대학 무변경은 갱신 SQL scope 필터가 이중으로 보장).

    Raises:
        ValueError: 다리 조인 실패 또는 src_id 중복(한 콘텐츠 행에 두 크로스워크 행 — 계약 위반).
    """
    out: dict[str, tuple[str, ...]] = {}
    for record in crosswalk:
        if not record.atom_codes:
            continue
        src_id = concept_src_bridge.get(record.concept_id)
        if src_id is None:
            raise ValueError(f"크로스워크 concept_id가 graph.json에 없음: {record.concept_id!r}")
        if src_id in out:
            raise ValueError(f"src_id {src_id!r}에 크로스워크 행이 중복으로 닿음")
        out[src_id] = tuple(sorted(dict.fromkeys(record.atom_codes)))
    return out


@dataclass(frozen=True, slots=True)
class CrosswalkTransferReport:
    """이전 갱신 결과 — 갱신 행 수 + 대상 행 부재 키(조용히 넘기지 않음·운영 가시성)."""

    updated: int
    missing: tuple[str, ...]


class CrosswalkTransferStore:
    """크로스워크 이전 갱신기 — `atom_node`/`concept_content` 이전 컬럼 멱등 UPDATE(sync).

    형제 projection store(`AtomNodeStore`·`ConceptContentStore`)와 같은 엔진 규약(주입 우선·
    슬3 `_build_sync_engine` 지연 생성)을 따르되, upsert가 아니라 **기존 행의 이전 컬럼만
    UPDATE**한다(행 생성 없음·다른 컬럼 무접촉 — 정본 적재는 각자의 projection 소관).
    rowcount 0(대상 행 부재)은 `missing`으로 수집해 보고한다(조용히 넘기지 않음).
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
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings(형제 store 패턴)."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _get_engine(self) -> Engine:
        """sync 엔진 지연 해석 — 주입 우선, 없으면 슬3 빌더로 생성·캐시(신규 seam 0)."""
        if self._engine is None:
            self._engine = _build_sync_engine(self._resolved_settings)
        return self._engine

    def update_atom_behavior_skills(
        self, mapping: Mapping[str, tuple[str, ...]]
    ) -> CrosswalkTransferReport:
        """원자별 behavior_skills 멱등 UPDATE — `UPDATE atom_node ... WHERE code=...`.

        code 사전순으로 단일 트랜잭션 실행(결정론·부분 적용 방지). 대상 행 부재(rowcount 0)는
        missing 수집(선행 `atom_node` populate 미실행 신호). 값은 유도 함수가 이미 사전순이다.
        """
        from sqlalchemy import func, update

        from whymath_backend.db.models.atom_node import AtomNode

        missing: list[str] = []
        updated = 0
        with self._get_engine().begin() as conn:
            for code in sorted(mapping):
                stmt = (
                    update(AtomNode)
                    .where(AtomNode.code == code)
                    .values(behavior_skills=list(mapping[code]), updated_at=func.now())
                )
                result = conn.execute(stmt)
                if result.rowcount == 0:
                    missing.append(code)
                else:
                    updated += 1
        return CrosswalkTransferReport(updated=updated, missing=tuple(missing))

    def update_concept_behavior_skills(
        self, mapping: Mapping[str, tuple[str, ...]]
    ) -> CrosswalkTransferReport:
        """원자→skills 매핑을 런타임 `concept.behavior_skills`에 멱등 UPDATE(SKB-01).

        `update_atom_behavior_skills`(atom_node 짝)와 *같은 mapping*(atom code 키)을 받아
        `concept.code`(atom_backend_concept 적재·원자와 같은 키 공간)로 조인한다. `Concept`에는
        `updated_at` 컬럼이 없어(atom_node와 달리) 그 필드는 SET하지 않는다. 대상 행 부재
        (rowcount 0)는 missing 수집(선행 `atom_backend_concept` populate 미실행 신호).
        """
        from sqlalchemy import update

        from whymath_backend.db.models.concept import Concept

        missing: list[str] = []
        updated = 0
        with self._get_engine().begin() as conn:
            for code in sorted(mapping):
                stmt = (
                    update(Concept)
                    .where(Concept.code == code)
                    .values(behavior_skills=list(mapping[code]))
                )
                result = conn.execute(stmt)
                if result.rowcount == 0:
                    missing.append(code)
                else:
                    updated += 1
        return CrosswalkTransferReport(updated=updated, missing=tuple(missing))

    def update_k12_content_atom_codes(
        self, mapping: Mapping[str, tuple[str, ...]]
    ) -> CrosswalkTransferReport:
        """K-12 콘텐츠 행 atom_codes 멱등 UPDATE — `scope='K-12'` 필터로 대학 행 구조 차단.

        `UPDATE concept_content SET atom_codes=... WHERE code=... AND scope='K-12'`. 대학 행은
        WHERE가 걸러 절대 갱신되지 않는다('{}' 유지 — 이미 원자 정합). 대상 행 부재는 missing
        수집(선행 `concept_content` populate 미실행 신호).
        """
        from sqlalchemy import func, update

        from whymath_backend.db.models.concept_content import ConceptContent

        missing: list[str] = []
        updated = 0
        with self._get_engine().begin() as conn:
            for code in sorted(mapping):
                stmt = (
                    update(ConceptContent)
                    .where(ConceptContent.code == code, ConceptContent.scope == CONTENT_SCOPE_K12)
                    .values(atom_codes=list(mapping[code]), updated_at=func.now())
                )
                result = conn.execute(stmt)
                if result.rowcount == 0:
                    missing.append(code)
                else:
                    updated += 1
        return CrosswalkTransferReport(updated=updated, missing=tuple(missing))


def transfer_atom_behavior_skills(
    mapping: Mapping[str, tuple[str, ...]],
    *,
    settings: Settings | None = None,
    store: CrosswalkTransferStore | None = None,
) -> CrosswalkTransferReport:
    """유도된 원자→skills 매핑을 `atom_node.behavior_skills`에 멱등 갱신(형제 populate_* 골격)."""
    resolved = settings if settings is not None else get_settings()
    transfer_store = store if store is not None else CrosswalkTransferStore(settings=resolved)
    return transfer_store.update_atom_behavior_skills(mapping)


def transfer_concept_behavior_skills(
    mapping: Mapping[str, tuple[str, ...]],
    *,
    settings: Settings | None = None,
    store: CrosswalkTransferStore | None = None,
) -> CrosswalkTransferReport:
    """같은 원자→skills 매핑을 런타임 `concept.behavior_skills`에 멱등 갱신(SKB-01·③)."""
    resolved = settings if settings is not None else get_settings()
    transfer_store = store if store is not None else CrosswalkTransferStore(settings=resolved)
    return transfer_store.update_concept_behavior_skills(mapping)


def transfer_k12_content_atom_codes(
    mapping: Mapping[str, tuple[str, ...]],
    *,
    settings: Settings | None = None,
    store: CrosswalkTransferStore | None = None,
) -> CrosswalkTransferReport:
    """유도된 K-12 콘텐츠→원자 매핑을 `concept_content.atom_codes`에 멱등 갱신(대학 무변경)."""
    resolved = settings if settings is not None else get_settings()
    transfer_store = store if store is not None else CrosswalkTransferStore(settings=resolved)
    return transfer_store.update_k12_content_atom_codes(mapping)


__all__ = [
    "CrosswalkRecord",
    "CrosswalkTransferReport",
    "CrosswalkTransferStore",
    "derive_atom_behavior_skills",
    "derive_k12_content_atom_codes",
    "load_behavior_skills_by_src",
    "load_concept_src_bridge",
    "load_crosswalk_records",
    "transfer_atom_behavior_skills",
    "transfer_concept_behavior_skills",
    "transfer_k12_content_atom_codes",
]
