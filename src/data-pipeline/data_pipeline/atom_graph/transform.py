"""원자_통합마스터·선수엣지_통합(행 dict) → `AtomConcept`/`AtomEdge` 정형화(결정론).

정본: `docs/data/atom_graph_v1.md`(스키마·§3 redaction) + 마이그레이션 플랜 Phase 1.

전부 **결정론**(정렬·안정 출력)이라 동일 입력 2회 → byte 동일 산출이 보장된다. 입력은 추출
레이어(`extract.py`)가 만든 Korean-header dict 행이다 — 이 모듈은 openpyxl을 import하지 않는다
(ncic/transform이 추출과 분리된 선례 미러).

수행 단계(`transform_atoms`·`transform_edges`):
  1. **계층 노드 dedup 승격**: 소단원코드 → 소단원 노드, 그 `-S` 앞 prefix → 단원 노드를
     dedup 생성. 원자.parent=소단원코드·소단원.parent=단원코드·단원.parent=None. 같은
     소단원코드는 같은 소단원명이어야 함(불일치 시 validate가 error).
  2. **표기 정규화(사이시옷)**: 모든 텍스트 필드의 `자리값→자릿값`·`경계값→경곗값` 치환. 회색지대
     (고유값·진리값·실고유값 등)는 *정확히 `자리값`·`경계값` 토큰만* 치환하므로 건드리지 않는다.
  3. **연결성취기준 미적Ⅰ/Ⅱ 하이픈 정규화**: `12미적Ⅰ01-01`→`12미적Ⅰ-01-01`(43개). 공수·기수는
     이미 하이픈이라 무변경.
  4. **관계유형 매핑**: 선수엣지 `관계유형`→`relation_subtype`. `from_유형=원자ID` → `AtomEdge`.
     **`from_유형=서술형`은 FK 불가 → `narrative_edges_raw`로 패스스루**(현재 건수는
     `docs/data/corpus_facts.md`의 `atom_graph.edges`·`atom_graph.narrative_edges_raw`).
  5. **redaction**: K-12(학교급≠대학) 원자의 `핵심명제/성취기준내용`(=NCIC 본문)은 산출에 싣지
     않고 `redacted_fields` 마커만 남긴다. 대학 핵심명제는 자체작성 → `core_proposition` 보존.

치환·정규화 건수는 `TransformResult.provenance`에 기록(결정성·문서화).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from data_pipeline.atom_graph.models import (
    AtomConcept,
    AtomEdge,
    AtomRelation,
    NodeLevel,
    SchoolLevel,
)

logger = logging.getLogger("data_pipeline.atom_graph.transform")

# ──────────────────────────────────────────────────────────────────────
# 컬럼명(원본 한글 헤더) — 추출 레이어가 이 키로 행 dict를 만든다.
# ──────────────────────────────────────────────────────────────────────
COL_ATOM_ID = "원자ID"
COL_ATOM_NAME = "원자명"
COL_ATOM_NAME_DISPLAY = "원자명_표시"
COL_SCHOOL = "학교급"
COL_GRADE_BAND = "학년/학년군"
COL_SUBJECT_AREA = "영역/과목"
COL_UNIT = "단원"
COL_SUBUNIT = "소단원"
COL_SUBUNIT_CODE = "소단원코드"
COL_COGNITIVE = "인지축"
COL_NODE_TYPE = "노드유형"
COL_MISCONCEPTION_TYPE = "오개념유형"
COL_DIFFICULTY = "난이도"
COL_LINKED_STANDARDS = "연결성취기준"
COL_CORE_PROPOSITION = "핵심명제/성취기준내용"
COL_MISCONCEPTION = "①오개념"
COL_DIAGNOSTIC_ITEM = "②진단문항"
COL_DIAGNOSTIC_ANSWER = "②정답·통과기준"
COL_DIAGNOSTIC_SIGNAL = "②미통과·오답신호"
COL_SOCRATIC = "③소크라테스질문"
COL_TRANSFER = "④전이"
COL_TRANSFER_EXAMPLE = "④전이예시"
COL_ATOMICITY = ("원자성a", "원자성b", "원자성c", "원자성d")
COL_NOTES = "비고"

# 엣지 컬럼.
EDGE_RELATION_SUBTYPE = "관계유형"
EDGE_FROM = "from(선수)"
EDGE_FROM_NAME = "from_원자명"
EDGE_FROM_KIND = "from_유형"
EDGE_TO = "to(후행)"
EDGE_TO_NAME = "to_원자명"
EDGE_SCHOOL_LINK = "학교급연계"

# from_유형 값.
FROM_KIND_ATOM_ID = "원자ID"
FROM_KIND_NARRATIVE = "서술형"

# ──────────────────────────────────────────────────────────────────────
# 학교급 정규화(원본 '초등학교' → enum '초등').
# ──────────────────────────────────────────────────────────────────────
_SCHOOL_LEVEL_MAP: dict[str, SchoolLevel] = {
    "초등학교": SchoolLevel.ELEMENTARY,
    "중학교": SchoolLevel.MIDDLE,
    "고등학교": SchoolLevel.HIGH,
    "대학교": SchoolLevel.UNIVERSITY,
    # 방어적: 이미 정규화된 값도 수용(재처리 안전).
    "초등": SchoolLevel.ELEMENTARY,
    "중학": SchoolLevel.MIDDLE,
    "고등": SchoolLevel.HIGH,
    "대학": SchoolLevel.UNIVERSITY,
}

# 사이시옷 정규화 — *정확히 이 토큰만* 치환(회색지대 고유값·진리값 등은 건드리지 않음).
_SAISIOT_MAP: dict[str, str] = {
    "자리값": "자릿값",
    "경계값": "경곗값",
}

# 미적Ⅰ/Ⅱ 하이픈 정규화 — `미적Ⅰ01-01`→`미적Ⅰ-01-01`(공수·기수는 이미 하이픈이라 무변경).
_MIJEOK_HYPHEN_RE: re.Pattern[str] = re.compile(r"(미적[ⅠⅡ])(\d{2}-\d{2})")
# 정규화 *후* 미적Ⅰ/Ⅱ 코드 식별(고유 코드 집계용 — 하이픈 포함 형태 매칭).
_MIJEOK_DISTINCT_RE: re.Pattern[str] = re.compile(r"미적[ⅠⅡ]-\d{2}-\d{2}")

# K-12 redaction 대상(=NCIC 본문). 대학은 자체작성이라 보존.
_REDACTED_K12_FIELD = COL_CORE_PROPOSITION


@dataclass(slots=True)
class TransformResult:
    """정형화 산출.

    `concepts`는 원자 + 단원 + 소단원 노드(전부 `AtomConcept`). `edges`는 원자ID 선수 엣지.
    `narrative_edges_raw`는 서술형 엣지 패스스루(원본 보존·후속 해소). `provenance`는 정규화·
    치환·redaction 카운트(결정성·문서화). `skipped`는 제외 항목 메시지(검수용).
    """

    concepts: list[AtomConcept] = field(default_factory=list)
    edges: list[AtomEdge] = field(default_factory=list)
    narrative_edges_raw: list[dict[str, object]] = field(default_factory=list)
    provenance: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """사람 가독 요약."""
        atoms = sum(1 for c in self.concepts if c.level == NodeLevel.ATOM.value)
        units = sum(1 for c in self.concepts if c.level == NodeLevel.UNIT.value)
        subunits = sum(1 for c in self.concepts if c.level == NodeLevel.SUBUNIT.value)
        return (
            f"정형화: 노드 {len(self.concepts)}개(원자 {atoms}·단원 {units}·소단원 {subunits}), "
            f"엣지 {len(self.edges)}개, 서술형(raw) {len(self.narrative_edges_raw)}개, "
            f"skip {len(self.skipped)}건"
        )


# ──────────────────────────────────────────────────────────────────────
# 셀/텍스트 헬퍼
# ──────────────────────────────────────────────────────────────────────
def _opt(value: object) -> str | None:
    """빈 문자열·None·공백만 → None, 그 외 str(strip). 사이시옷 정규화는 호출측에서 별도 적용."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_saisiot(text: str, counter: dict[str, int] | None = None) -> str:
    """사이시옷 정규화 — `자리값→자릿값`·`경계값→경곗값`만(회색지대 제외).

    counter가 주어지면 토큰별 치환 건수를 누적한다(provenance 기록). `고유값`·`진리값`·`실고유값`
    등은 `자리값`·`경계값` 토큰을 포함하지 않으므로 자연히 무변경이다.
    """
    for src, dst in _SAISIOT_MAP.items():
        if src in text:
            n = text.count(src)
            text = text.replace(src, dst)
            if counter is not None and n:
                counter[src] = counter.get(src, 0) + n
    return text


def _norm_text(value: object, counter: dict[str, int] | None = None) -> str | None:
    """텍스트 셀 → None|str(strip + 사이시옷 정규화). 카운터에 치환 건수 누적."""
    text = _opt(value)
    if text is None:
        return None
    return normalize_saisiot(text, counter)


def normalize_standard_code(code: str, counter: dict[str, int] | None = None) -> str:
    """연결성취기준 코드 정규화 — 미적Ⅰ/Ⅱ 하이픈 추가(공수·기수는 무변경).

    counter['미적Ⅰ/Ⅱ 하이픈']에 정규화된 코드 수를 누적한다(token 단위).
    """
    new = _MIJEOK_HYPHEN_RE.sub(r"\1-\2", code)
    if counter is not None and new != code:
        counter["미적하이픈"] = counter.get("미적하이픈", 0) + 1
    return new


def parse_linked_standards(value: object, counter: dict[str, int] | None = None) -> list[str]:
    """연결성취기준 셀 → 정규화 코드 목록. '없음'·빈 셀 → []. ';'·',' 구분 분할."""
    text = _opt(value)
    if text is None or text == "없음":
        return []
    codes = [c.strip() for c in re.split(r"[;,]", text) if c.strip()]
    return [normalize_standard_code(c, counter) for c in codes]


def _int_opt(value: object) -> int | None:
    """난이도 등 정수 옵션. 빈/None/비정수는 None(검증은 Pydantic ge/le에 위임)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def unit_code_of(subunit_code: str) -> str:
    """소단원코드 → 단원코드(마지막 `-S` 앞까지). `-S` 없으면 원본 그대로.

    예: `초수연-U1-S1`→`초수연-U1`·`공수1-U1-S2`→`공수1-U1`·`CALC1-U1-S1`→`CALC1-U1`.
    """
    idx = subunit_code.rfind("-S")
    return subunit_code[:idx] if idx != -1 else subunit_code


def _atomicity(row: Mapping[str, object]) -> dict[str, str]:
    """원자성a~d → {'a':..,'b':..,'c':..,'d':..}(빈 값은 키 생략). 계층 노드는 빈 dict."""
    out: dict[str, str] = {}
    for col in COL_ATOMICITY:
        v = _opt(row.get(col))
        if v is not None:
            out[col[-1]] = v  # 'a'..'d'
    return out


# ──────────────────────────────────────────────────────────────────────
# 원자 + 계층 노드 정형화
# ──────────────────────────────────────────────────────────────────────
def transform_atoms(
    rows: Iterable[Mapping[str, object]],
    counter: dict[str, int] | None = None,
) -> tuple[list[AtomConcept], list[str]]:
    """원자_통합마스터 행 → 원자 노드 + dedup 승격된 단원·소단원 노드 + skip 메시지.

    결정론: 원자는 입력 순서 보존, 계층 노드는 첫 등장 순서로 dedup(안정). redaction은 학교급으로
    분기 — K-12 핵심명제는 싣지 않고 마커만, 대학 핵심명제는 core_proposition 보존.
    """
    cnt = counter if counter is not None else {}
    atoms: list[AtomConcept] = []
    skipped: list[str] = []

    # 계층 노드 dedup 버킷(첫 등장 순서 보존).
    subunit_nodes: dict[str, AtomConcept] = {}
    unit_nodes: dict[str, AtomConcept] = {}

    for row in rows:
        code = _opt(row.get(COL_ATOM_ID))
        if code is None:
            skipped.append(f"atom: 원자ID 없음 — {dict(row)!r}")
            continue

        school_raw = _opt(row.get(COL_SCHOOL)) or ""
        school = _SCHOOL_LEVEL_MAP.get(school_raw)
        if school is None:
            skipped.append(f"atom {code}: 미지원 학교급 {school_raw!r}")
            continue

        subunit_code = _opt(row.get(COL_SUBUNIT_CODE))

        # ── redaction 분기: 핵심명제. K-12 → drop(마커만)·대학 → core_proposition 보존.
        redacted: list[str] = []
        core_prop: str | None = None
        raw_core = _opt(row.get(COL_CORE_PROPOSITION))
        if raw_core is not None:
            if school == SchoolLevel.UNIVERSITY:
                core_prop = normalize_saisiot(raw_core, cnt)
            else:
                redacted.append(_REDACTED_K12_FIELD)
                cnt["redacted_핵심명제"] = cnt.get("redacted_핵심명제", 0) + 1

        try:
            atom = AtomConcept(
                code=code,
                name=normalize_saisiot(_opt(row.get(COL_ATOM_NAME)) or "", cnt),
                name_display=_norm_text(row.get(COL_ATOM_NAME_DISPLAY), cnt),
                level=NodeLevel.ATOM,
                parent_code=subunit_code,
                school_level=school,
                grade_band=_opt(row.get(COL_GRADE_BAND)),
                subject_area=_norm_text(row.get(COL_SUBJECT_AREA), cnt),
                unit=_norm_text(row.get(COL_UNIT), cnt),
                subunit=_norm_text(row.get(COL_SUBUNIT), cnt),
                subunit_code=subunit_code,
                cognitive_type=_opt(row.get(COL_COGNITIVE)),  # type: ignore[arg-type]
                node_type=_opt(row.get(COL_NODE_TYPE)),  # type: ignore[arg-type]
                misconception_type=_opt(row.get(COL_MISCONCEPTION_TYPE)),
                intrinsic_difficulty=_int_opt(row.get(COL_DIFFICULTY)),
                standard_codes=parse_linked_standards(row.get(COL_LINKED_STANDARDS), cnt),
                core_proposition=core_prop,
                misconception=_norm_text(row.get(COL_MISCONCEPTION), cnt),
                diagnostic_item=_norm_text(row.get(COL_DIAGNOSTIC_ITEM), cnt),
                diagnostic_answer=_norm_text(row.get(COL_DIAGNOSTIC_ANSWER), cnt),
                diagnostic_signal=_norm_text(row.get(COL_DIAGNOSTIC_SIGNAL), cnt),
                socratic=_norm_text(row.get(COL_SOCRATIC), cnt),
                transfer=_norm_text(row.get(COL_TRANSFER), cnt),
                transfer_example=_norm_text(row.get(COL_TRANSFER_EXAMPLE), cnt),
                atomicity=_atomicity(row),
                notes=_norm_text(row.get(COL_NOTES), cnt),
                redacted_fields=redacted,
            )
        except (ValueError, TypeError) as exc:
            skipped.append(f"atom {code}: {type(exc).__name__}: {exc}")
            continue
        atoms.append(atom)

        # ── 계층 노드 승격(dedup). 소단원코드 있을 때만.
        if subunit_code is not None and subunit_code not in subunit_nodes:
            unit_code = unit_code_of(subunit_code)
            subunit_name = _norm_text(row.get(COL_SUBUNIT), cnt) or subunit_code
            subunit_nodes[subunit_code] = AtomConcept(
                code=subunit_code,
                name=subunit_name,
                level=NodeLevel.SUBUNIT,
                parent_code=unit_code,
                school_level=school,
                subject_area=_norm_text(row.get(COL_SUBJECT_AREA), None),
                unit=_norm_text(row.get(COL_UNIT), None),
                subunit=subunit_name,
                subunit_code=subunit_code,
            )
            if unit_code not in unit_nodes:
                unit_name = _norm_text(row.get(COL_UNIT), None) or unit_code
                unit_nodes[unit_code] = AtomConcept(
                    code=unit_code,
                    name=unit_name,
                    level=NodeLevel.UNIT,
                    parent_code=None,
                    school_level=school,
                    subject_area=_norm_text(row.get(COL_SUBJECT_AREA), None),
                    unit=unit_name,
                )

    # 결정론적 출력: 원자(입력 순서) → 단원(첫 등장) → 소단원(첫 등장).
    concepts = atoms + list(unit_nodes.values()) + list(subunit_nodes.values())
    return concepts, skipped


# ──────────────────────────────────────────────────────────────────────
# 엣지 정형화
# ──────────────────────────────────────────────────────────────────────
def transform_edges(
    rows: Iterable[Mapping[str, object]],
    counter: dict[str, int] | None = None,
) -> tuple[list[AtomEdge], list[dict[str, object]], list[str]]:
    """선수엣지_통합 행 → (원자ID 엣지, 서술형 패스스루, skip).

    `from_유형=원자ID` → `AtomEdge`(관계유형→relation_subtype). `from_유형=서술형` → FK 불가라
    엣지로 만들지 않고 dict 패스스루(원본 보존). 그 외 from_유형은 skip.
    """
    cnt = counter if counter is not None else {}
    edges: list[AtomEdge] = []
    narrative: list[dict[str, object]] = []
    skipped: list[str] = []

    for row in rows:
        kind = _opt(row.get(EDGE_FROM_KIND))
        from_code = _opt(row.get(EDGE_FROM))
        to_code = _opt(row.get(EDGE_TO))
        ref = f"{from_code}→{to_code}"

        if kind == FROM_KIND_NARRATIVE:
            # 서술형: 정규화 없이 원본 보존(후속 원자ID 해소 대상).
            narrative.append({str(k): v for k, v in row.items()})
            cnt["narrative_edges"] = cnt.get("narrative_edges", 0) + 1
            continue
        if kind != FROM_KIND_ATOM_ID:
            skipped.append(f"edge {ref}: 미지원 from_유형 {kind!r}")
            continue
        if from_code is None or to_code is None:
            skipped.append(f"edge {ref}: from/to 코드 없음")
            continue

        try:
            edges.append(
                AtomEdge(
                    from_code=from_code,
                    from_name=_norm_text(row.get(EDGE_FROM_NAME), cnt),
                    to_code=to_code,
                    to_name=_norm_text(row.get(EDGE_TO_NAME), cnt),
                    relation=AtomRelation.PREREQUISITE,
                    relation_subtype=_opt(row.get(EDGE_RELATION_SUBTYPE)),
                    school_link=(_opt(row.get(EDGE_SCHOOL_LINK)) == "Y"),
                )
            )
        except (ValueError, TypeError) as exc:
            skipped.append(f"edge {ref}: {type(exc).__name__}: {exc}")
            continue

    return edges, narrative, skipped


def transform_dataset(
    *,
    atom_rows: Sequence[Mapping[str, object]],
    edge_rows: Sequence[Mapping[str, object]],
) -> TransformResult:
    """원자·엣지 행 → 정형화 산출(원자+계층 노드·엣지·서술형 패스스루·provenance).

    결정론적 — 동일 입력 2회 호출 시 동일 산출(정렬·안정 순서). provenance에 정규화·redaction
    카운트를 기록한다(`미적하이픈`=토큰 단위 치환 건수·`미적하이픈_distinct`=정규화된 *고유 코드* 수
    — 후자가 데이터카드의 '43'에 대응).
    """
    counter: dict[str, int] = {}
    concepts, a_skips = transform_atoms(atom_rows, counter)
    edges, narrative, e_skips = transform_edges(edge_rows, counter)

    # 미적 하이픈 정규화된 *고유 코드* 수(토큰 단위 카운트와 별개 — 데이터카드 '43' 대응).
    # 정규화 *후* 형태는 `미적Ⅰ-01-01`이므로 정규화 대상이었던 코드를 그 형태로 집계한다.
    mijeok_distinct = {
        code
        for concept in concepts
        for code in concept.standard_codes
        if _MIJEOK_DISTINCT_RE.search(code)
    }
    if mijeok_distinct:
        counter["미적하이픈_distinct"] = len(mijeok_distinct)

    result = TransformResult(
        concepts=concepts,
        edges=edges,
        narrative_edges_raw=narrative,
        provenance=dict(sorted(counter.items())),
        skipped=a_skips + e_skips,
    )
    logger.info(result.summary())
    return result


__all__ = [
    "TransformResult",
    "normalize_saisiot",
    "normalize_standard_code",
    "parse_linked_standards",
    "transform_atoms",
    "transform_dataset",
    "transform_edges",
    "unit_code_of",
]
