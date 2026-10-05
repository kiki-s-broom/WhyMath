"""Phase 3 대표 과정 범위 명세 — 코퍼스 로더 + 참조 실재 무결성 게이트 (P3-01).

범위 명세란
-----------
Phase 3 의 모든 Coverage 계측(P3-02)이 **분모**로 삼는 "무엇을 완성할 것인가"의 동결본이다
(`data/corpus/phase3_scope_v1/scope_spec.yaml`). 과정 1개·학년/과목/단원 범위·Curriculum Node·
Concept(핵심 표시)·Skill·핵심 오개념·필수 Problem Type·수량 목표·completeness 기준의 9항을
데이터로 둔다. 본문은 담지 않고 기존 자산의 ID 만 가리킨다 — 새 ID 체계를 만들지 않는다.

이 모듈이 있는 이유
-------------------
분모가 참조하는 ID 가 코퍼스에서 사라지거나 오타가 나도 아무도 소리내지 않으면, 이후 모든
Coverage 수치가 **존재하지 않는 대상을 센 값**이 된다. 이 모듈은 명세가 스키마를 어기거나(빈 목록·
중복·산술 불일치) 존재하지 않는 ID 를 참조하면 **CI 가 적색을 내게** 한다.

두 단계로 나눈 이유
-------------------
  · 구조 위반(필수 필드 결손·빈 목록·중복·알 수 없는 어휘) → `ScopeSpecError` 로 즉시 실패.
    구조가 깨진 명세는 참조 검사를 해도 의미가 없다.
  · 참조 실재 위반(없는 성취기준 코드·Concept ID·원자·스킬·M-id·문제유형) → `verify_spec` 이
    위반 목록으로 **모아서** 돌려준다. 한 번의 실행으로 고칠 곳을 전부 보여 주기 위해서다.

단방향 관례 (CLAUDE.md "YAML=소스 · DB=산출물")
----------------------------------------------
YAML 이 소스다. 이 모듈은 **읽기 전용**이며 DB 에 쓰지 않는다.

침묵 실패 금지
--------------
파일 부재·파싱 실패·코퍼스 0건은 전부 명시 실패한다. "못 읽었으니 위반 없음"과 "대상이 0건이라
통과"는 게이트를 상시 green 으로 만드는 형태이므로 둘 다 막는다. 예외 메시지에는 예외 타입명을
포함한다.

계층 경계
---------
L1(데이터 기반) 코퍼스 리더다. 상위 계층(L2~L6)을 import 하지 않고 DB 세션도 잡지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

# l1/standards/phase3_scope.py → parents[5]가 레포 루트(anchor_registry 와 같은 관용구).
_REPO_ROOT = Path(__file__).resolve().parents[5]

_DEFAULT_SPEC = Path("data/corpus/phase3_scope_v1/scope_spec.yaml")

SPEC_VERSION = 1

#: P3-18 검증 가능성 판정 어휘 — 오타를 통과시키면 어떤 개념이 부분 가능인지 조용히 틀어진다.
KNOWN_PROBE_VERDICTS: frozenset[str] = frozenset(
    {"possible", "partial", "replaced_by_derived", "not_probed"}
)

#: 로더가 읽는 코퍼스 소스 키 — 하나라도 빠지면 그 종류의 참조는 검사되지 않는다.
_REQUIRED_SOURCE_KEYS: tuple[str, ...] = (
    "standards",
    "concept_ids",
    "crosswalk",
    "atoms",
    "skills",
    "misconceptions",
    "problem_types",
)


class ScopeSpecError(RuntimeError):
    """범위 명세 적재·구조 검증 실패 — 조용한 0건 대신 던진다."""


# ──────────────────────────────────────────────────────────────────────────
# 명세 모델
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CurriculumNode:
    """항 3 — 성취기준 코드 1건(교육과정 Overlay 의 노드)."""

    code: str
    sub_domain: str


@dataclass(frozen=True)
class ConceptEntry:
    """항 4 — 성취기준당 대표 개념 1개(437 입도)."""

    code: str
    concept_id: str
    source_id: str
    primary_atom_code: str
    core: bool
    probe_verdict: str
    probe_note: str | None


@dataclass(frozen=True)
class CoreMisconception:
    """항 6 — 핵심 오개념 1건(M-id)과 그것이 속한 개념의 성취기준 코드."""

    mis_id: str
    concept_code: str


@dataclass(frozen=True)
class Slot:
    """항 8 — 문제 유형 슬롯 1종(대표·기본·응용·오개념 유발·진단·숙련도 확인)."""

    id: str
    name_ko: str


@dataclass(frozen=True)
class Target:
    """항 9 — 목표 수치 1건. 수치가 없으면 `value=None` 이고 사유를 반드시 나른다."""

    value: float | None
    reason: str | None


@dataclass(frozen=True)
class ScopeSpec:
    """범위 명세 전체 — 9항 + 동결 표지."""

    spec_id: str
    frozen_at: str
    frozen_by_gate: str
    disposition_gate: str
    design_doc: str
    # 항 1
    course_id: str
    course_name_ko: str
    # 항 2
    subject_code: str
    domain: str
    curriculum_revision: str
    grade: str
    school_level: str
    excluded_domains: tuple[str, ...]
    # 항 3~7
    nodes: tuple[CurriculumNode, ...]
    concepts: tuple[ConceptEntry, ...]
    skills: tuple[str, ...]
    core_misconceptions: tuple[CoreMisconception, ...]
    misconception_selection_rule: str
    problem_types: tuple[str, ...]
    # 항 8
    slots: tuple[Slot, ...]
    min_distinct_per_slot: int
    total_min_distinct_problems: int
    # 항 9
    targets: Mapping[str, Target]
    concept_required_links: tuple[str, ...]
    graph_path: tuple[str, ...]
    curriculum_path: tuple[str, ...]
    problem_required_fields: tuple[str, ...]
    # 코퍼스 소스(레포 루트 기준 경로) + 성취기준 개정 필터
    sources: Mapping[str, str]
    source_path: Path

    @property
    def node_codes(self) -> tuple[str, ...]:
        return tuple(n.code for n in self.nodes)

    @property
    def core_concepts(self) -> tuple[ConceptEntry, ...]:
        """Coverage 분모가 되는 핵심 개념."""
        return tuple(c for c in self.concepts if c.core)


def default_spec_path() -> Path:
    """저장소 정본 명세 경로."""
    return _REPO_ROOT / _DEFAULT_SPEC


# ──────────────────────────────────────────────────────────────────────────
# 구조 파싱 — 위반은 ScopeSpecError (참조 검사는 verify_spec)
# ──────────────────────────────────────────────────────────────────────────
def _require(raw: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise ScopeSpecError(f"{where}: 필수 필드 {key!r} 결손")
    return raw[key]


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ScopeSpecError(f"{where}: 매핑이 아니다 (실제 {type(value).__name__})")
    return value


def _text(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = _require(raw, key, where)
    if not isinstance(value, str) or not value.strip():
        raise ScopeSpecError(f"{where}: {key!r}가 빈 문자열이거나 문자열이 아니다")
    return value


def _items(value: Any, where: str) -> list[Any]:
    """비어 있지 않은 리스트 — 빈 목록은 분모를 0 으로 만들므로 허용하지 않는다."""
    if not isinstance(value, list) or not value:
        raise ScopeSpecError(f"{where}: 비어 있거나 리스트가 아니다")
    return value


def _unique_texts(value: Any, where: str) -> tuple[str, ...]:
    items = _items(value, where)
    if any(not isinstance(i, str) or not i.strip() for i in items):
        raise ScopeSpecError(f"{where}: 빈 문자열·비문자열이 있다")
    if len(set(items)) != len(items):
        raise ScopeSpecError(f"{where}: 중복이 있다 — {items}")
    return tuple(items)


def _ensure_unique(values: list[str], where: str) -> None:
    if len(set(values)) != len(values):
        dup = sorted({v for v in values if values.count(v) > 1})
        raise ScopeSpecError(f"{where}: 중복이 있다 — {dup}")


def _parse_nodes(raw: Any, where: str) -> tuple[CurriculumNode, ...]:
    nodes = tuple(
        CurriculumNode(
            code=_text(_mapping(item, f"{where}[{i}]"), "code", f"{where}[{i}]"),
            sub_domain=_text(_mapping(item, f"{where}[{i}]"), "sub_domain", f"{where}[{i}]"),
        )
        for i, item in enumerate(_items(raw, where))
    )
    _ensure_unique([n.code for n in nodes], f"{where}.code")
    return nodes


def _parse_concepts(raw: Any, where: str) -> tuple[ConceptEntry, ...]:
    entries: list[ConceptEntry] = []
    for i, item in enumerate(_items(raw, where)):
        w = f"{where}[{i}]"
        row = _mapping(item, w)
        core = _require(row, "core", w)
        if not isinstance(core, bool):
            raise ScopeSpecError(f"{w}: core 는 true/false 여야 한다 (실제 {core!r})")
        verdict = _text(row, "probe_verdict", w)
        if verdict not in KNOWN_PROBE_VERDICTS:
            raise ScopeSpecError(
                f"{w}: 알 수 없는 probe_verdict {verdict!r} — 허용: {sorted(KNOWN_PROBE_VERDICTS)}"
            )
        note = row.get("probe_note")
        entries.append(
            ConceptEntry(
                code=_text(row, "code", w),
                concept_id=_text(row, "concept_id", w),
                source_id=_text(row, "source_id", w),
                primary_atom_code=_text(row, "primary_atom_code", w),
                core=core,
                probe_verdict=verdict,
                probe_note=str(note) if note else None,
            )
        )
    # 437 입도 = 성취기준당 대표 개념 1개. 한 코드에 둘이 걸리면 분모가 이중 계상된다.
    _ensure_unique([e.code for e in entries], f"{where}.code")
    _ensure_unique([e.concept_id for e in entries], f"{where}.concept_id")
    _ensure_unique([e.source_id for e in entries], f"{where}.source_id")
    if not any(e.core for e in entries):
        # 핵심 개념 0건은 분모 0 이다 — 통과가 아니라 실패(지시문 [04] ④).
        raise ScopeSpecError(f"{where}: 핵심(core: true) 개념이 0건이다 — 분모가 0 이 된다")
    return tuple(entries)


def _parse_core_misconceptions(raw: Any, where: str) -> tuple[tuple[CoreMisconception, ...], str]:
    block = _mapping(raw, where)
    rule = _text(block, "selection_rule", where)
    items = tuple(
        CoreMisconception(
            mis_id=_text(_mapping(item, f"{where}.items[{i}]"), "mis_id", f"{where}.items[{i}]"),
            concept_code=_text(
                _mapping(item, f"{where}.items[{i}]"), "concept_code", f"{where}.items[{i}]"
            ),
        )
        for i, item in enumerate(_items(_require(block, "items", where), f"{where}.items"))
    )
    _ensure_unique([m.mis_id for m in items], f"{where}.items.mis_id")
    return items, rule


def _parse_slots(raw: Any, where: str) -> tuple[Slot, ...]:
    slots = tuple(
        Slot(
            id=_text(_mapping(item, f"{where}[{i}]"), "id", f"{where}[{i}]"),
            name_ko=_text(_mapping(item, f"{where}[{i}]"), "name_ko", f"{where}[{i}]"),
        )
        for i, item in enumerate(_items(raw, where))
    )
    _ensure_unique([s.id for s in slots], f"{where}.id")
    return slots


def _positive_int(raw: Mapping[str, Any], key: str, where: str) -> int:
    value = _require(raw, key, where)
    # bool 은 int 의 하위 클래스라 True 가 1 로 통과한다 — 명시적으로 막는다.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ScopeSpecError(f"{where}: {key!r}는 1 이상의 정수여야 한다 (실제 {value!r})")
    return value


def _parse_targets(raw: Any, where: str) -> Mapping[str, Target]:
    block = _mapping(raw, where)
    if not block:
        raise ScopeSpecError(f"{where}: 목표 수치가 0건이다")
    targets: dict[str, Target] = {}
    for name, item in block.items():
        w = f"{where}.{name}"
        row = _mapping(item, w)
        value = _require(row, "value", w)
        if value is None:
            # 수치가 없다는 사실은 허용하되 **왜 없는지**가 데이터로 남아야 한다.
            reason = _text(row, "reason", w)
            targets[str(name)] = Target(value=None, reason=reason)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
            raise ScopeSpecError(
                f"{w}: value 는 0 초과 1 이하의 수치이거나 null 이어야 한다 ({value!r})"
            )
        targets[str(name)] = Target(value=float(value), reason=None)
    return targets


def parse_scope_spec(doc: Any, source: Path) -> ScopeSpec:
    """YAML 문서 → `ScopeSpec`. 구조 위반은 전부 `ScopeSpecError`."""
    where = str(source)
    top = _mapping(doc, where)
    version = _require(top, "spec_version", where)
    if version != SPEC_VERSION:
        raise ScopeSpecError(
            f"{where}: 지원하지 않는 spec_version {version!r} (지원 {SPEC_VERSION})"
        )

    course = _mapping(_require(top, "course", where), f"{where}.course")
    scope = _mapping(_require(top, "scope", where), f"{where}.scope")
    # 항 1(과정)과 항 2(범위)가 같은 과목·단원을 가리켜야 한다 — 어긋나면 분모의 주어가 둘이 된다.
    for key in ("subject_code", "domain"):
        if _text(course, key, f"{where}.course") != _text(scope, key, f"{where}.scope"):
            raise ScopeSpecError(f"{where}: course.{key} 와 scope.{key} 가 다르다")

    sources_raw = _mapping(_require(top, "sources", where), f"{where}.sources")
    sources: dict[str, str] = {}
    for key in _REQUIRED_SOURCE_KEYS:
        entry = _require(sources_raw, key, f"{where}.sources")
        path = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(path, str) or not path.strip():
            raise ScopeSpecError(f"{where}.sources.{key}: 경로가 비어 있다")
        sources[key] = path

    pt_block = _mapping(
        _require(top, "required_problem_types", where), f"{where}.required_problem_types"
    )
    qt = _mapping(_require(top, "quantity_targets", where), f"{where}.quantity_targets")
    comp = _mapping(_require(top, "completeness", where), f"{where}.completeness")
    if comp.get("empty_denominator") != "fail":
        raise ScopeSpecError(f"{where}.completeness: empty_denominator 는 'fail' 이어야 한다")
    misconceptions, rule = _parse_core_misconceptions(
        _require(top, "core_misconceptions", where), f"{where}.core_misconceptions"
    )

    return ScopeSpec(
        spec_id=_text(top, "spec_id", where),
        frozen_at=_text(top, "frozen_at", where),
        frozen_by_gate=_text(top, "frozen_by_gate", where),
        disposition_gate=_text(top, "disposition_gate", where),
        design_doc=_text(top, "design_doc", where),
        course_id=_text(course, "id", f"{where}.course"),
        course_name_ko=_text(course, "name_ko", f"{where}.course"),
        subject_code=_text(scope, "subject_code", f"{where}.scope"),
        domain=_text(scope, "domain", f"{where}.scope"),
        curriculum_revision=_text(course, "curriculum_revision", f"{where}.course"),
        grade=_text(scope, "grade", f"{where}.scope"),
        school_level=_text(scope, "school_level", f"{where}.scope"),
        excluded_domains=tuple(
            str(d) for d in _require(scope, "excluded_domains", f"{where}.scope") or ()
        ),
        nodes=_parse_nodes(_require(top, "curriculum_nodes", where), f"{where}.curriculum_nodes"),
        concepts=_parse_concepts(_require(top, "concepts", where), f"{where}.concepts"),
        skills=_unique_texts(_require(top, "skills", where), f"{where}.skills"),
        core_misconceptions=misconceptions,
        misconception_selection_rule=rule,
        problem_types=_unique_texts(
            _require(pt_block, "items", f"{where}.required_problem_types"),
            f"{where}.required_problem_types.items",
        ),
        slots=_parse_slots(
            _require(qt, "slots", f"{where}.quantity_targets"), f"{where}.quantity_targets.slots"
        ),
        min_distinct_per_slot=_positive_int(
            qt, "min_distinct_problems_per_slot", f"{where}.quantity_targets"
        ),
        total_min_distinct_problems=_positive_int(
            qt, "total_min_distinct_problems", f"{where}.quantity_targets"
        ),
        targets=_parse_targets(
            _require(comp, "targets", f"{where}.completeness"), f"{where}.completeness.targets"
        ),
        concept_required_links=_unique_texts(
            _require(comp, "concept_required_links", f"{where}.completeness"),
            f"{where}.completeness.concept_required_links",
        ),
        graph_path=_unique_texts(
            _require(comp, "graph_path", f"{where}.completeness"),
            f"{where}.completeness.graph_path",
        ),
        curriculum_path=_unique_texts(
            _require(comp, "curriculum_path", f"{where}.completeness"),
            f"{where}.completeness.curriculum_path",
        ),
        problem_required_fields=_unique_texts(
            _require(comp, "problem_required_fields", f"{where}.completeness"),
            f"{where}.completeness.problem_required_fields",
        ),
        sources=sources,
        source_path=source,
    )


def load_scope_spec(path: Path | None = None) -> ScopeSpec:
    """명세 YAML → `ScopeSpec`. 실패는 전부 `ScopeSpecError`(침묵 0건 금지)."""
    source = path or default_spec_path()
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScopeSpecError(
            f"범위 명세를 읽지 못했다 ({source}): {type(exc).__name__}: {exc}"
        ) from exc
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScopeSpecError(
            f"범위 명세 YAML 파싱 실패 ({source}): {type(exc).__name__}: {exc}"
        ) from exc
    return parse_scope_spec(doc, source)


# ──────────────────────────────────────────────────────────────────────────
# 참조 색인 — 명세가 가리키는 코퍼스를 직접 읽는다 (DB·백엔드 설정 import 없음)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StandardRef:
    """성취기준 코퍼스 1행 — 범위 소속 판정에 쓰는 축."""

    subject: str | None
    domain: str | None
    sub_domain: str | None
    grade_band: str | None


@dataclass(frozen=True)
class AtomRef:
    """원자 백본 리프(세부개념) 1건."""

    grade_band: str | None
    standard_codes: tuple[str, ...]
    behavior_skills: tuple[str, ...]


@dataclass(frozen=True)
class CrosswalkRef:
    """크로스워크 1행 — 437 개념 → primary 원자 + 원자 목록."""

    primary_atom_code: str | None
    atom_codes: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceIndex:
    """명세가 참조하는 코퍼스 색인 — 테스트가 임시 코퍼스로 바꿔 끼울 수 있게 값 객체로 둔다."""

    standards: Mapping[str, StandardRef]
    concept_src: Mapping[str, str]
    crosswalk: Mapping[str, CrosswalkRef]
    atoms: Mapping[str, AtomRef]
    skill_ids: frozenset[str]
    misconceptions: Mapping[str, str | None]
    problem_type_ids: frozenset[str]


def _read_json(target: Path, label: str) -> Any:
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScopeSpecError(
            f"{label} 코퍼스를 읽지 못했다 ({target}): {type(exc).__name__}: {exc}"
        ) from exc


def _read_jsonl(target: Path, label: str) -> list[Mapping[str, Any]]:
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ScopeSpecError(
            f"{label} 코퍼스를 읽지 못했다 ({target}): {type(exc).__name__}: {exc}"
        ) from exc
    rows: list[Mapping[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScopeSpecError(
                f"{label} 코퍼스 {number}행 파싱 실패 ({target}): {type(exc).__name__}: {exc}"
            ) from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _nonzero(label: str, count: int) -> None:
    """0건은 '위반 없음'이 아니라 '읽기 실패'다 — 통과시키면 게이트가 상시 green 이 된다."""
    if count == 0:
        raise ScopeSpecError(f"{label} 코퍼스가 0건이다 — 경로·형식을 확인하라(게이트 무력화 방지)")


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _text_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def load_reference_index(spec: ScopeSpec, repo_root: Path | None = None) -> ReferenceIndex:
    """명세의 `sources` 가 가리키는 코퍼스 7종 → 참조 색인. 실패·0건은 `ScopeSpecError`."""
    root = repo_root or _REPO_ROOT

    def at(key: str) -> Path:
        return root / spec.sources[key]

    payload = _read_json(at("standards"), "성취기준")
    rows = payload.get("standards") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ScopeSpecError(f"{at('standards')}: 최상위 'standards' 배열이 없다")
    standards = {
        str(r["code"]): StandardRef(
            subject=_optional_text(r.get("subject")),
            domain=_optional_text(r.get("domain")),
            sub_domain=_optional_text(r.get("sub_domain")),
            grade_band=_optional_text(r.get("grade_band")),
        )
        for r in rows
        # 폐지된 2015 개정 코드가 분모를 살려 주지 않도록 개정 필터를 건다.
        if isinstance(r, dict)
        and "code" in r
        and r.get("curriculum_revision") == spec.curriculum_revision
    }
    _nonzero("성취기준", len(standards))

    try:
        ids_doc = yaml.safe_load(at("concept_ids").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScopeSpecError(
            f"개념 ID 코퍼스를 읽지 못했다 ({at('concept_ids')}): {type(exc).__name__}: {exc}"
        ) from exc
    id_rows = ids_doc.get("concepts") if isinstance(ids_doc, dict) else None
    if not isinstance(id_rows, list):
        raise ScopeSpecError(f"{at('concept_ids')}: 최상위 'concepts' 배열이 없다")
    concept_src = {
        str(r["canonical_id"]): str(r.get("src_id"))
        for r in id_rows
        if isinstance(r, dict) and "canonical_id" in r
    }
    _nonzero("개념 ID", len(concept_src))

    crosswalk = {
        str(r["concept_id"]): CrosswalkRef(
            primary_atom_code=_optional_text(r.get("primary_atom_code")),
            atom_codes=_text_tuple(r.get("atom_codes")),
        )
        for r in _read_jsonl(at("crosswalk"), "크로스워크")
        if "concept_id" in r
    }
    _nonzero("크로스워크", len(crosswalk))

    atom_payload = _read_json(at("atoms"), "원자 백본")
    atom_rows = atom_payload.get("concepts") if isinstance(atom_payload, dict) else None
    if not isinstance(atom_rows, list):
        raise ScopeSpecError(f"{at('atoms')}: 최상위 'concepts' 배열이 없다")
    atoms = {
        str(r["code"]): AtomRef(
            grade_band=_optional_text(r.get("grade_band")),
            standard_codes=_text_tuple(r.get("standard_codes")),
            behavior_skills=_text_tuple(r.get("behavior_skills")),
        )
        for r in atom_rows
        # 문항이 닿는 것은 리프(세부개념)뿐이다 — 단원·소단원 노드를 대표 원자로 인정하지 않는다.
        if isinstance(r, dict) and r.get("level") == "세부개념" and "code" in r
    }
    _nonzero("원자 백본 리프", len(atoms))

    skill_ids = frozenset(
        str(r["skill_id"]) for r in _read_jsonl(at("skills"), "스킬") if "skill_id" in r
    )
    _nonzero("스킬", len(skill_ids))

    mis_payload = _read_json(at("misconceptions"), "오개념")
    mis_rows = mis_payload.get("misconceptions") if isinstance(mis_payload, dict) else None
    if not isinstance(mis_rows, list):
        raise ScopeSpecError(f"{at('misconceptions')}: 최상위 'misconceptions' 배열이 없다")
    misconceptions = {
        str(r["mis_id"]): _optional_text(r.get("standard_code"))
        for r in mis_rows
        if isinstance(r, dict) and "mis_id" in r
    }
    _nonzero("오개념", len(misconceptions))

    problem_type_ids = frozenset(
        str(r["problem_type_id"])
        for r in _read_jsonl(at("problem_types"), "문제유형")
        if "problem_type_id" in r
    )
    _nonzero("문제유형", len(problem_type_ids))

    return ReferenceIndex(
        standards=standards,
        concept_src=concept_src,
        crosswalk=crosswalk,
        atoms=atoms,
        skill_ids=skill_ids,
        misconceptions=misconceptions,
        problem_type_ids=problem_type_ids,
    )


# ──────────────────────────────────────────────────────────────────────────
# 참조 실재 검증 — 반환 = 위반 목록(빈 튜플이면 통과)
# ──────────────────────────────────────────────────────────────────────────
def _verify_nodes(spec: ScopeSpec, index: ReferenceIndex) -> list[str]:
    out: list[str] = []
    for node in spec.nodes:
        ref = index.standards.get(node.code)
        if ref is None:
            out.append(
                f"curriculum_nodes[{node.code}]: 성취기준 코퍼스({spec.curriculum_revision})에 없다"
            )
            continue
        if ref.subject != spec.subject_code or ref.domain != spec.domain:
            out.append(
                f"curriculum_nodes[{node.code}]: 범위({spec.subject_code}·{spec.domain}) 밖이다 "
                f"— 실제 {ref.subject}·{ref.domain}"
            )
        if ref.sub_domain != node.sub_domain:
            out.append(
                f"curriculum_nodes[{node.code}]: 소단원이 다르다 — 명세 {node.sub_domain!r} "
                f"/ 코퍼스 {ref.sub_domain!r}"
            )
        if ref.grade_band is not None and ref.grade_band != spec.school_level:
            out.append(
                f"curriculum_nodes[{node.code}]: 학교급이 다르다 — 명세 {spec.school_level!r} "
                f"/ 코퍼스 {ref.grade_band!r}"
            )
    # 범위 누락 — 이 대단원에 속한 성취기준이 분모에서 조용히 빠지면 Coverage 가 부풀려진다.
    declared = set(spec.node_codes)
    for code, ref in sorted(index.standards.items()):
        if ref.subject == spec.subject_code and ref.domain == spec.domain and code not in declared:
            out.append(f"curriculum_nodes: 대단원 성취기준 {code}가 명세에 없다(범위 누락)")
    return out


def _verify_concepts(spec: ScopeSpec, index: ReferenceIndex) -> list[str]:
    out: list[str] = []
    node_codes = set(spec.node_codes)
    for concept in spec.concepts:
        where = f"concepts[{concept.code}]"
        if concept.code not in node_codes:
            out.append(f"{where}: 성취기준 코드가 curriculum_nodes 에 없다")
        if concept.concept_id not in index.concept_src:
            out.append(f"{where}: Concept ID {concept.concept_id!r}가 개념 ID 코퍼스에 없다")
        elif index.concept_src[concept.concept_id] != concept.source_id:
            out.append(
                f"{where}: source_id 가 다르다 — 명세 {concept.source_id!r} "
                f"/ 코퍼스 {index.concept_src[concept.concept_id]!r}"
            )
        cross = index.crosswalk.get(concept.concept_id)
        if cross is None:
            out.append(f"{where}: Concept ID {concept.concept_id!r}가 크로스워크에 없다")
            continue
        if cross.primary_atom_code != concept.primary_atom_code:
            out.append(
                f"{where}: primary 원자가 다르다 — 명세 {concept.primary_atom_code!r} "
                f"/ 크로스워크 {cross.primary_atom_code!r}"
            )
        primary = index.atoms.get(concept.primary_atom_code)
        if primary is None:
            out.append(f"{where}: primary 원자 {concept.primary_atom_code!r}가 원자 리프에 없다")
        elif concept.code not in primary.standard_codes:
            out.append(f"{where}: primary 원자가 이 성취기준에 귀속돼 있지 않다")
        for atom_code in cross.atom_codes:
            atom = index.atoms.get(atom_code)
            if atom is None:
                out.append(f"{where}: 크로스워크 원자 {atom_code!r}가 원자 리프에 없다")
            elif atom.grade_band != spec.grade:
                out.append(
                    f"{where}: 원자 {atom_code} 의 학년이 다르다 — 명세 {spec.grade!r} "
                    f"/ 코퍼스 {atom.grade_band!r}"
                )
    covered = {c.code for c in spec.concepts}
    for node in spec.nodes:
        if node.code not in covered:
            out.append(f"curriculum_nodes[{node.code}]: 이 성취기준에 대표 Concept 가 없다")
    return out


def _verify_skills(spec: ScopeSpec, index: ReferenceIndex) -> list[str]:
    out: list[str] = []
    listed = set(spec.skills)
    for skill in spec.skills:
        if skill not in index.skill_ids:
            out.append(f"skills[{skill}]: 스킬 코퍼스에 없다")
    used: set[str] = set()
    for concept in spec.concepts:
        cross = index.crosswalk.get(concept.concept_id)
        atom_skills = {
            s
            for code in (cross.atom_codes if cross else ())
            for s in (index.atoms[code].behavior_skills if code in index.atoms else ())
        }
        overlap = atom_skills & listed
        used |= overlap
        if not overlap:
            # 개념에 스킬이 하나도 이어지지 않으면 Concept → Skill → Problem 경로가 처음부터 끊긴다.
            out.append(f"concepts[{concept.code}]: 원자 스킬과 겹치는 명세 스킬이 없다")
    for skill in spec.skills:
        if skill not in used:
            out.append(f"skills[{skill}]: 어느 개념의 원자에도 쓰이지 않는다(고아 스킬)")
    return out


def _verify_misconceptions(spec: ScopeSpec, index: ReferenceIndex) -> list[str]:
    out: list[str] = []
    concept_codes = {c.code for c in spec.concepts}
    for item in spec.core_misconceptions:
        where = f"core_misconceptions[{item.mis_id}]"
        if item.mis_id not in index.misconceptions:
            out.append(f"{where}: M-id 가 오개념 코퍼스에 없다")
        elif index.misconceptions[item.mis_id] != item.concept_code:
            out.append(
                f"{where}: 귀속 성취기준이 다르다 — 명세 {item.concept_code!r} "
                f"/ 코퍼스 {index.misconceptions[item.mis_id]!r}"
            )
        if item.concept_code not in concept_codes:
            out.append(f"{where}: concept_code {item.concept_code!r}가 concepts 에 없다")
    covered = {m.concept_code for m in spec.core_misconceptions}
    for concept in spec.core_concepts:
        if concept.code not in covered:
            # 핵심 개념에 핵심 오개념이 없으면 오개념 유발 슬롯이 신호 없이 비게 된다.
            out.append(f"concepts[{concept.code}]: 핵심 개념인데 핵심 오개념이 없다")
    return out


def verify_spec(spec: ScopeSpec, index: ReferenceIndex) -> tuple[str, ...]:
    """명세의 모든 참조가 코퍼스에 실재하고 목록끼리 어긋나지 않는지 검사한다.

    반환 = 위반 목록(빈 튜플이면 통과). 구조 위반은 이미 `parse_scope_spec` 이 막았다.
    """
    out = _verify_nodes(spec, index)
    out += _verify_concepts(spec, index)
    out += _verify_skills(spec, index)
    out += _verify_misconceptions(spec, index)
    for ptype in spec.problem_types:
        if ptype not in index.problem_type_ids:
            out.append(f"required_problem_types[{ptype}]: 문제유형 코퍼스에 없다")
    expected = len(spec.core_concepts) * len(spec.slots) * spec.min_distinct_per_slot
    if spec.total_min_distinct_problems != expected:
        out.append(
            f"quantity_targets: total_min_distinct_problems {spec.total_min_distinct_problems} "
            f"≠ 핵심 개념 {len(spec.core_concepts)} × 슬롯 {len(spec.slots)} "
            f"× 슬롯당 {spec.min_distinct_per_slot} = {expected}"
        )
    return tuple(out)


# ──────────────────────────────────────────────────────────────────────────
# CLI — `python -m whymath_backend.l1.standards.phase3_scope`
# 판정은 exit 0/1(CLAUDE.md "게이트 판정은 항상 CLI exit 0/1" — 인상 판정 금지).
# ──────────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3 범위 명세 무결성 점검 — 참조 실재·구조 검사(exit 0=통과·1=위반)."
    )
    parser.add_argument("--spec", type=Path, default=None, help="범위 명세 YAML 경로")
    parser.add_argument("--json", action="store_true", help="요약을 JSON 으로 출력")
    args = parser.parse_args(argv)

    try:
        spec = load_scope_spec(args.spec)
        index = load_reference_index(spec)
    except ScopeSpecError as exc:
        # 적재 실패를 exit 0 으로 가리지 않는다 — 측정 실패는 측정 실패로 보여야 한다.
        print(f"[적재 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    violations = verify_spec(spec, index)
    summary = {
        "spec": str(spec.source_path),
        "spec_id": spec.spec_id,
        "frozen_at": spec.frozen_at,
        "frozen_by_gate": spec.frozen_by_gate,
        "course": spec.course_id,
        "curriculum_nodes": len(spec.nodes),
        "concepts": len(spec.concepts),
        "core_concepts": len(spec.core_concepts),
        "skills": len(spec.skills),
        "core_misconceptions": len(spec.core_misconceptions),
        "required_problem_types": len(spec.problem_types),
        "total_min_distinct_problems": spec.total_min_distinct_problems,
        "violations": list(violations),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"범위 명세: {summary['spec']} (동결 {spec.frozen_at} · 게이트 {spec.frozen_by_gate})"
        )
        print(
            f"  과정 {spec.course_id} · 노드 {summary['curriculum_nodes']} · "
            f"Concept {summary['concepts']}(핵심 {summary['core_concepts']}) · "
            f"스킬 {summary['skills']} · 핵심 오개념 {summary['core_misconceptions']} · "
            f"문제유형 {summary['required_problem_types']} · "
            f"수량 목표 {spec.total_min_distinct_problems}"
        )
        for violation in violations:
            print(f"  ✗ {violation}")
        print("판정: " + ("통과" if not violations else f"위반 {len(violations)}건"))
    return 1 if violations else 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    raise SystemExit(main())
