"""①오개념 atom → `misconception_catalog` 승격 적재기 — atom 백본 graph.json 투영.

`catalog_loader.py`(misconceptions_v1 코퍼스 → `misconception_catalog`)의 *원자 백본* 짝이다.
Phase 1 산출 코퍼스 `data/corpus/atom_graph_v1/graph.json`의 원자(세부개념) ①오개념(`misconception`
서술 + `misconception_type` 6종)을 *정식 콘텐츠 소스 테이블* `misconception_catalog`로 승격한다
(로드맵 Phase 3 결정 ③ — 4요소를 정식 소스로 승격, 그 첫 조각 ①오개념).

`atom_node_projection.py`(메타 프로젝션)는 ①②③ 4요소 *본문을 의도적으로 미적재*했다(redaction·
이중 보관 금지·Phase 3 승격 대상 명시). 이 모듈이 그 ①오개념의 *유일 승격 좌석*이다 — 메타 시트는
`atom_node`(인지축·전이 등 안전 메타)에, 오개념 본문은 `misconception_catalog`(자체 저작)에 둔다.

────────────────────────────────────────────────────────────────────────────
기존 loader/schema/store 재사용 (신규 마이그레이션·data-pipeline 변경 0)
────────────────────────────────────────────────────────────────────────────
`misconception_catalog` 테이블·계약(`schema.MisconceptionCatalog`)·멱등 upsert
(`MisconceptionCatalogStore`·`load_misconceptions`)는 *그대로 재사용*한다 — 이 모듈은 graph.json의
원자 ①오개념을 `MisconceptionCatalog` 행 dict로 *투영*만 하고, 검증·dedup·`ON CONFLICT(mis_id)`
멱등 upsert는 기존 `load_misconceptions`에 위임한다(신규 store/마이그레이션 0).

매핑(자체 작성 필드만·날조 0 — atom ①오개념 원천에 없는 칸은 None):
  - `mis_id` = `"ATOM:" + code`     (합성·결정론·구 M-series와 네임스페이스 분리·멱등)
  - `canonical_statement` = `misconception`(서술 본문·자체 저작 보유 허용)
  - `error_type` = `misconception_type`(6종 — free str·강제 없음)
  - `concept_src_id` = `code`(원자 code·느슨참조·`atom_node.code`와 동일 공간)
  - `standard_code` = `standard_codes[0]`(원자는 전건 보유·없으면 None·느슨참조)
  - `school_level`·`domain`(←`subject_area`)·`subunit` = 원자 안전 메타 그대로
  - `provenance_note` = `"atom_graph_v1"`(출처 표기·구 839과 구분)
  - 나머지(student_wrong_thinking·distractor_rule·correction_point·difficulty·ccss_code·
    mapping_*) = None(원자 ①오개념 원천 미보유 — 날조하지 않는다)

구 839(misconceptions_v1·개념-grain·`N1` 출처)와는 mis_id 네임스페이스(`ATOM:` 접두)·
`provenance_note`로 분리되며 *additive 병존*한다(Phase 1이 원자를 기존 `concept`/`concept_edge`에
additive 적재한 것과 동형). 구 839는 Phase 5에서 폐기 예정.

7계층: L1 데이터 기반의 *런타임 엔티티 적재*. 소비(진단·distractor 생성)는 이 행을 *조회*하되
여기서 구현하지 않는다(역방향 의존 금지·후속).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from whymath_backend.l1.misconception.catalog_loader import load_misconceptions

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from whymath_backend.config import Settings
    from whymath_backend.l1.misconception.catalog_loader import MisconceptionCatalogStore

# atom mis_id 접두 — 구 M-series(misconceptions_v1)와 네임스페이스 분리(무충돌·결정론).
ATOM_MIS_ID_PREFIX = "ATOM:"
# provenance 메모 — atom 백본 출처 표기(구 839과 구분·Phase 5 폐기 대상 식별).
ATOM_PROVENANCE_NOTE = "atom_graph_v1"
# atom 판별 level 값(세부개념 = 원자) — 단원·소단원은 ①오개념 미보유.
_ATOM_LEVEL = "세부개념"


def _opt_str(value: object) -> str | None:
    """빈 문자열·None → None, 그 외 strip한 str(atom_node_projection `_opt_str` 미러)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def atom_misconception_rows(graph_path: Path) -> list[dict[str, Any]]:
    """atom 백본 `graph.json` → `misconception_catalog` 행 dict 목록(원자 ①오개념 투영).

    `concepts` 배열에서 **원자(level=='세부개념')이고 `misconception` 서술이 빈 값이 아닌** 항목만
    골라 `MisconceptionCatalog` schema 필드 dict로 투영한다(schema `extra=forbid` 호환 — 스키마
    필드만 채운다). 단원·소단원(①오개념 없음)·빈 오개념·code 없는 항목은 *건너뛴다*(정직·조용한
    빈 적재 금지). mis_id는 `"ATOM:" + code`로 합성한다(결정론·멱등).

    빈/누락 `concepts`는 빈 목록을 낸다(graceful). 형식 검증은 `load_misconceptions`가 행마다
    `MisconceptionCatalog.model_validate`로 게이트한다(extra=forbid·필수 mis_id).

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    payload = json.loads(graph_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for record in payload.get("concepts", []):
        if _opt_str(record.get("level")) != _ATOM_LEVEL:
            continue  # 단원·소단원은 ①오개념 없음 — 원자만 승격.
        statement = _opt_str(record.get("misconception"))
        if statement is None:
            continue  # 빈 오개념 서술 skip(의미 없는 행 방지·정직).
        code = _opt_str(record.get("code"))
        if code is None:
            continue  # code 없으면 mis_id 합성 불가 — skip(방어).

        raw_codes = record.get("standard_codes")
        standard_code: str | None = None
        if isinstance(raw_codes, (list, tuple)) and raw_codes:
            standard_code = _opt_str(raw_codes[0])

        rows.append(
            {
                "mis_id": f"{ATOM_MIS_ID_PREFIX}{code}",
                "canonical_statement": statement,
                "error_type": _opt_str(record.get("misconception_type")),
                "concept_src_id": code,
                "standard_code": standard_code,
                "school_level": _opt_str(record.get("school_level")),
                "domain": _opt_str(record.get("subject_area")),
                "subunit": _opt_str(record.get("subunit")),
                "provenance_note": ATOM_PROVENANCE_NOTE,
            }
        )
    return rows


def load_atom_misconceptions(
    graph_path: Path,
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    store: MisconceptionCatalogStore | None = None,
    overwrite_cms_edits: bool = False,
    conflicts: list[str] | None = None,
) -> int:
    """atom 백본 `graph.json` ①오개념 → `misconception_catalog` 멱등 적재. 반환=적재 행 수.

    `overwrite_cms_edits`·`conflicts`는 CMS 편집 보호(P3-25)로 `load_misconceptions`에 그대로
    위임된다 — 보호로 건너뛴 행은 반환 행 수에서 빠진다.

    `atom_misconception_rows`로 graph.json을 행 dict 목록으로 투영한 뒤 `{"misconceptions": rows}`
    Collection으로 감싸 **기존 `load_misconceptions`에 위임**한다 — 검증(extra=forbid)·mis_id 기준
    dedup·`ON CONFLICT(mis_id)` 멱등 upsert는 모두 기존 loader/store가 담당한다(신규 적재 로직 0).
    store/engine/settings 미주입 시 `load_misconceptions`가 슬3 sync 엔진 재사용 store를 만든다.

    Raises:
        FileNotFoundError: graph.json 부재.
    """
    rows = atom_misconception_rows(graph_path)
    collection: dict[str, Any] = {"misconceptions": rows}
    return load_misconceptions(
        None,
        collection,
        engine=engine,
        settings=settings,
        store=store,
        overwrite_cms_edits=overwrite_cms_edits,
        conflicts=conflicts,
    )


__all__ = [
    "ATOM_MIS_ID_PREFIX",
    "ATOM_PROVENANCE_NOTE",
    "atom_misconception_rows",
    "load_atom_misconceptions",
]
