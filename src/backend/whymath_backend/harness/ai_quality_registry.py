"""P3-10 AI 품질 평가 — 판정 재료 레지스트리(개념·성취기준·오개념·표기 범위·대표 과정 범위).

8축 판정기(`ai_quality_judges`)가 "이 id가 실재하는가 / 범위 안인가 / 학생이 이미 배운 개념인가"를
묻는 재료를 **기존 정본 코퍼스에서만** 읽어 한 값 객체로 묶는다. 새 ID 체계·새 어휘를 만들지 않는다.

읽는 정본(전부 읽기 전용 · DB 0 · LLM 0)
----------------------------------------
- 대표 과정 범위 = `l1.standards.phase3_scope.load_scope_spec` (P3-01 동결본).
- 오개념 M-id 실재 = 같은 모듈의 `load_reference_index(spec).misconceptions` (P3-01 무결성 게이트와
  같은 색인 — 두 번째 로더를 만들지 않는다).
- 런타임 오개념 kebab 실재 = `l4.misconception.catalog.CATALOG_BY_ID` (P3-09 출력 스키마가 쓰는 것과
  같은 카탈로그).
- 성취기준 코드 → 학교급 밴드 = `l3.curriculum_notation_gate.load_standard_bands` (MATH-04 정본 —
  2015·2022 개정 코드 모두).
- 표기 토큰 → 구조 키 · 밴드별 도입 구조 = `l3.curriculum_notation_gate.load_range_table` +
  `harness.curriculum_notation_gate_cli.constructs_by_band` (MATH-04 정본).
- 개념 그래프 = `data/corpus/concept_graph_v1/` 의 `ids.yaml`(canonical_id↔src_id) ·
  `concepts.jsonl`(이름·성취기준) · `prerequisite_edges.jsonl`(선수 관계). 같은 파일을 읽는 코드는
  data-pipeline 패키지의 `concept_graph` 변환 CLI(그래프 산출물 생성용)뿐이고, 백엔드 런타임에서
  부를 공용 로더는 내가 찾은 방법으로는 0건이라(역할 기반 검색 — 파일명·`prerequisite` 소비자)
  여기서 필요한 필드만 읽는다.

대표 과정 범위 안의 개념(범위 이탈 축의 허용 집합)
-------------------------------------------------
명세의 개념 10개 **+ 그 선수 조상(깊이 ≤ 2)** 이다. 선수 개념을 짚는 교정은 정상 튜터링이고
(P3-06 사다리의 '선수 개념' 등급), 깊이 2는 CLAUDE.md 그래프 조회 상한(depth ≤ 2)과 같다.
후속 개념(예: 부정적분)·무관한 개념(예: 확률)은 범위 밖이다.

아직 배우지 않은 개념(학생 수준 적합성 축)
-----------------------------------------
현재 개념의 **선수 그래프 후손**(엄격 — 자기 자신 제외)이다. 미분계수를 배우는 학생에게 극대·극소를
끌어오면 범위 안이어도 수준 밖이다. 두 축이 다른 것을 잰다 — 범위는 *명세 소속*, 수준은 *학생의 현재
위치 대비 순서*다.

텍스트 속 개념 이름 탐지(사각을 명시한다)
---------------------------------------
`concepts.jsonl`의 `name_ko`가 응답 본문에 **정확히**(NFKC·공백 제거 후 부분 문자열) 나올 때만 그
개념을 언급한 것으로 본다. 정규화 길이 4자 미만 이름(약분·순열·확률 등 24개)은 우연 일치가 커서
제외한다. 같은 이름의 개념이 둘 이상이면 후보를 모두 돌려준다(판정기가 보수적으로 접는다). 긴 이름이
먼저 잡히고 그 구간은 짧은 이름이 다시 잡지 않는다. **약칭·동의어·풀어 쓴 표현은 못 잡는다** —
예: "극대·극소"는 개념 이름 "함수의 증가·감소와 극대·극소"가 아니라 잡히지 않는다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from whymath_backend.harness.curriculum_notation_gate_cli import constructs_by_band
from whymath_backend.l1.standards.phase3_scope import (
    ScopeSpec,
    load_reference_index,
    load_scope_spec,
)
from whymath_backend.l3.curriculum_notation_gate import (
    RangeTable,
    load_range_table,
    load_standard_bands,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.speech import SpeechGradeBand

__all__ = [
    "BAND_RANK",
    "MIN_NAME_CHARS",
    "PREREQ_SCOPE_DEPTH",
    "ConceptInfo",
    "Registry",
    "RegistryError",
    "default_repo_root",
    "load_registry",
    "normalize_text",
]

#: 범위 이탈 축 — 명세 개념의 선수 조상을 몇 단계까지 범위 안으로 볼지(CLAUDE.md depth ≤ 2).
PREREQ_SCOPE_DEPTH: Final[int] = 2

#: 텍스트 개념 이름 탐지 최소 길이(정규화 후). 3자 이하 이름은 우연 일치가 커서 제외한다.
MIN_NAME_CHARS: Final[int] = 4

#: 학교급 밴드 순서 — `curriculum_notation_gate._BAND_RANK`와 같은 순서(그쪽은 비공개라 공개 상수로
#: 둔다).
BAND_RANK: Final[Mapping[SpeechGradeBand, int]] = {
    SpeechGradeBand.초등: 0,
    SpeechGradeBand.중등: 1,
    SpeechGradeBand.고등: 2,
    SpeechGradeBand.대학: 3,
}

_CONCEPT_GRAPH = Path("data/corpus/concept_graph_v1")
_STANDARDS = Path("data/corpus/standards_v1/standards.json")
_RANGE_TABLE = Path("data/curriculum_notation_ranges.json")


class RegistryError(RuntimeError):
    """레지스트리 적재 실패 — 0건·파싱 실패·구조 위반을 통과로 접지 않는다(예외 타입명 포함)."""


def default_repo_root() -> Path:
    """harness/ → whymath_backend/ → backend/ → src/ → 저장소 루트(parents[4] 관용구)."""
    return Path(__file__).resolve().parents[4]


def normalize_text(text: str) -> str:
    """비교용 정규화 — NFKC + 공백 제거(`l4/hint_content/gates._norm`과 같은 규약)."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


@dataclass(frozen=True)
class ConceptInfo:
    """개념 1개 — canonical id(DB `concept.code`)·원천 src id·이름·성취기준·학교급 밴드."""

    concept_id: str
    src_id: str
    name_ko: str
    standard_codes: tuple[str, ...]
    band: SpeechGradeBand | None
    """성취기준 코드들의 최고 밴드 — 정본에 없는 코드뿐이면 None(미분류)."""


@dataclass(frozen=True)
class Registry:
    """판정 재료 묶음(불변) — 판정기는 이것만 읽는다(파일 I/O 0)."""

    scope: ScopeSpec
    concepts: Mapping[str, ConceptInfo]
    """canonical_id → 개념."""
    src_to_concept: Mapping[str, str]
    parents: Mapping[str, frozenset[str]]
    """canonical_id → 직접 선수(부모) canonical_id 집합."""
    children: Mapping[str, frozenset[str]]
    scope_concepts: frozenset[str]
    """명세 개념 10개(canonical_id)."""
    allowed_scope_concepts: frozenset[str]
    """명세 개념 ∪ 선수 조상(깊이 ≤ `PREREQ_SCOPE_DEPTH`)."""
    allowed_scope_standards: frozenset[str]
    """허용 개념들의 성취기준 코드 ∪ 명세 Curriculum Node 코드."""
    standard_bands: Mapping[str, SpeechGradeBand]
    misconception_mids: frozenset[str]
    catalog_kebabs: frozenset[str]
    range_table: RangeTable
    band_constructs: Mapping[SpeechGradeBand, frozenset[str]]
    name_lexicon: tuple[tuple[str, frozenset[str]], ...]
    """(정규화 이름, 그 이름을 가진 canonical_id 집합) — 긴 이름 먼저."""

    def descendants(self, concept_id: str) -> frozenset[str]:
        """엄격 후손(선수 그래프에서 이 개념 뒤에 배우는 개념) — 자기 자신 제외."""
        seen: set[str] = set()
        stack = list(self.children.get(concept_id, frozenset()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self.children.get(node, frozenset()))
        seen.discard(concept_id)
        return frozenset(seen)

    def mentioned_concepts(self, text: str) -> tuple[frozenset[str], ...]:
        """본문에서 개념 이름 정확 일치를 찾는다 — 언급 1건마다 후보 canonical_id 집합 1개.

        긴 이름부터 잡고, 잡힌 구간은 가린다(짧은 이름이 긴 이름 안에서 다시 잡히지 않게).
        """
        body = normalize_text(text)
        found: list[frozenset[str]] = []
        for name, ids in self.name_lexicon:
            start = body.find(name)
            if start < 0:
                continue
            found.append(ids)
            # 같은 이름이 여러 번 나와도 언급 1건으로 센다 — 가린 뒤 계속(짧은 이름 재일치 차단).
            body = body.replace(name, "\x00" * len(name))
        return tuple(found)


# ──────────────────────────────────────────────────────────────────────────
# 적재
# ──────────────────────────────────────────────────────────────────────────
def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RegistryError(f"{path}: 읽지 못했다 ({type(exc).__name__})") from exc
    rows: list[Mapping[str, object]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"{path}:{number}: {type(exc).__name__}") from exc
        if not isinstance(row, dict):
            raise RegistryError(f"{path}:{number}: 객체가 아니다")
        rows.append(row)
    if not rows:
        raise RegistryError(f"{path}: 0건 — 빈 코퍼스를 통과로 접지 않는다")
    return rows


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str))


def _max_band(codes: Iterable[str], bands: Mapping[str, SpeechGradeBand]) -> SpeechGradeBand | None:
    known = [bands[c] for c in codes if c in bands]
    return max(known, key=lambda b: BAND_RANK[b]) if known else None


def _load_concepts(
    root: Path, bands: Mapping[str, SpeechGradeBand]
) -> tuple[dict[str, ConceptInfo], dict[str, str]]:
    ids_path = root / _CONCEPT_GRAPH / "ids.yaml"
    try:
        doc = yaml.safe_load(ids_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"{ids_path}: 읽지 못했다 ({type(exc).__name__})") from exc
    id_rows = doc.get("concepts") if isinstance(doc, dict) else None
    if not isinstance(id_rows, list) or not id_rows:
        raise RegistryError(f"{ids_path}: 'concepts' 배열이 없거나 비었다")
    src_to_concept: dict[str, str] = {}
    for row in id_rows:
        if isinstance(row, dict) and "canonical_id" in row and "src_id" in row:
            src_to_concept[str(row["src_id"])] = str(row["canonical_id"])
    if not src_to_concept:
        raise RegistryError(f"{ids_path}: canonical_id↔src_id 0건")

    concepts: dict[str, ConceptInfo] = {}
    for row in _read_jsonl(root / _CONCEPT_GRAPH / "concepts.jsonl"):
        src = row.get("src_id")
        name = row.get("name_ko")
        if not isinstance(src, str) or not isinstance(name, str):
            continue
        concept_id = src_to_concept.get(src)
        if concept_id is None:
            continue
        codes = _str_tuple(row.get("standard_codes"))
        concepts[concept_id] = ConceptInfo(
            concept_id=concept_id,
            src_id=src,
            name_ko=name,
            standard_codes=codes,
            band=_max_band(codes, bands),
        )
    # ids.yaml 에만 있고 concepts.jsonl 에 없는 개념도 실재한다 — 이름 없이 등록(환각 판정의 분모).
    for src, concept_id in src_to_concept.items():
        concepts.setdefault(
            concept_id,
            ConceptInfo(
                concept_id=concept_id, src_id=src, name_ko="", standard_codes=(), band=None
            ),
        )
    return concepts, src_to_concept


def _load_edges(
    root: Path, src_to_concept: Mapping[str, str]
) -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    parents: dict[str, set[str]] = {}
    children: dict[str, set[str]] = {}
    for row in _read_jsonl(root / _CONCEPT_GRAPH / "prerequisite_edges.jsonl"):
        src = src_to_concept.get(str(row.get("from_id")))
        dst = src_to_concept.get(str(row.get("to_id")))
        if src is None or dst is None or src == dst:
            continue
        parents.setdefault(dst, set()).add(src)
        children.setdefault(src, set()).add(dst)
    if not parents:
        raise RegistryError("선수 엣지 0건 — 범위·수준 판정이 공허해진다")
    return (
        {k: frozenset(v) for k, v in parents.items()},
        {k: frozenset(v) for k, v in children.items()},
    )


def _ancestors_within(
    start: Iterable[str], parents: Mapping[str, frozenset[str]], depth: int
) -> frozenset[str]:
    frontier = set(start)
    out = set(frontier)
    for _ in range(depth):
        frontier = {p for node in frontier for p in parents.get(node, frozenset())} - out
        if not frontier:
            break
        out |= frontier
    return frozenset(out)


def _name_lexicon(concepts: Mapping[str, ConceptInfo]) -> tuple[tuple[str, frozenset[str]], ...]:
    by_name: dict[str, set[str]] = {}
    for info in concepts.values():
        if not info.name_ko:
            continue
        name = normalize_text(info.name_ko)
        if len(name) < MIN_NAME_CHARS:
            continue
        by_name.setdefault(name, set()).add(info.concept_id)
    # 긴 이름 먼저 — 같은 길이는 사전순(결정론).
    ordered = sorted(by_name.items(), key=lambda kv: (-len(kv[0]), kv[0]))
    return tuple((name, frozenset(ids)) for name, ids in ordered)


def load_registry(repo_root: Path | None = None, *, scope: ScopeSpec | None = None) -> Registry:
    """정본 코퍼스 → `Registry`. 적재 실패는 `RegistryError`(측정 실패 — 통과로 접지 않는다)."""
    root = repo_root or default_repo_root()
    try:
        spec = scope or load_scope_spec(root / "data/corpus/phase3_scope_v1/scope_spec.yaml")
        index = load_reference_index(spec, root)
        bands = load_standard_bands(root / _STANDARDS)
        by_band = constructs_by_band()
        vocabulary = frozenset().union(*by_band.values())
        table = load_range_table(root / _RANGE_TABLE, vocabulary=vocabulary)
    except RegistryError:
        raise
    except Exception as exc:  # 적재 단계 예외를 타입명과 함께 측정 실패로 올린다
        raise RegistryError(f"정본 적재 실패: {type(exc).__name__}: {exc}") from exc

    concepts, src_to_concept = _load_concepts(root, bands)
    parents, children = _load_edges(root, src_to_concept)
    scope_ids = frozenset(c.concept_id for c in spec.concepts)
    missing = sorted(scope_ids - set(concepts))
    if missing:
        raise RegistryError(f"명세 개념이 개념 그래프에 없다: {missing}")
    allowed = _ancestors_within(scope_ids, parents, PREREQ_SCOPE_DEPTH)
    allowed_standards = frozenset(
        code for cid in allowed for code in concepts[cid].standard_codes
    ) | frozenset(spec.node_codes)
    return Registry(
        scope=spec,
        concepts=concepts,
        src_to_concept=src_to_concept,
        parents=parents,
        children=children,
        scope_concepts=scope_ids,
        allowed_scope_concepts=allowed,
        allowed_scope_standards=allowed_standards,
        standard_bands=bands,
        misconception_mids=frozenset(index.misconceptions),
        catalog_kebabs=frozenset(CATALOG_BY_ID),
        range_table=table,
        band_constructs=by_band,
        name_lexicon=_name_lexicon(concepts),
    )
