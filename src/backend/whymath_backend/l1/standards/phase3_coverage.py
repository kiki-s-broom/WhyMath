"""Phase 3 Coverage 계측기 4종 (P3-02) — 대표 과정의 '연결 상태'를 숫자로 재는 CLI.

분모는 P3-01 이 동결한 범위 명세(`phase3_scope`)다. 이 모듈은 명세가 가리키는 코퍼스를 DB 없이
직접 읽어 4개 지표를 계산하고, **미충족 개념 목록(무엇이 빠졌는지 포함)** 과 함께 내며, 목표
미달이면 exit 1 을 낸다. 사람이 세지 않는다 — 지표값은 오직 이 CLI 의 출력이다.

사용법
------
    python -m whymath_backend.l1.standards.phase3_coverage [--spec PATH] [--json]

종료 코드: 0 = 목표가 있는 지표가 전부 충족 · 1 = 목표 미달 또는 분모 0(측정 불가) ·
2 = 명세·코퍼스 적재 실패(측정 자체를 못 했다 — 통과로 위장하지 않는다).

────────────────────────────────────────────────────────────────────────────
'완전 연결'의 정의 — 이 절이 정본이다 (정의를 한 곳에 둬야 지표가 조작되지 않는다)
────────────────────────────────────────────────────────────────────────────
기호: c = 분모의 핵심 개념 · atoms(c) = c 의 크로스워크 원자 중 원자 백본 리프에 실재하는 것 ·
skills(c) = atoms(c) 의 행동 스킬 합집합 중 명세 스킬 · 적격 문항(c) = 검수 상태가 `approved`
이고 문항의 개념 태그에 c 의 원 개념 ID 가 `PRIMARY` 로 달린 문항.

  ① 문항의 스킬 = 문항의 문제유형 코드가 가리키는 문제유형의 행동 스킬 합집합.
  ② 스킬 연결된 문항(c) = 적격 문항(c) 중 skills(c) 와 문항의 스킬이 겹치는 것.
     '스킬이 있다'와 '문항이 있다'를 따로 세면 서로 무관한 두 사실이 '연결'로 계상된다 —
     같은 스킬을 매개로 개념과 문항이 이어져야 한다.

  ● Content Coverage Rate = 완전 연결 개념 / 핵심 개념.
      완전 연결(c) = 개념 콘텐츠 행이 있고 ∧ 스킬 연결된 문항(c)이 1건 이상.
      (검수 상태는 조건이 아니다 — 아래 'CONT-05 판정' 참조.)
  ● Curriculum Coverage = 교육과정 노드 중 Curriculum → Concept → Skill → Problem 경로가 있는 비율.
      노드 n 은 `code` 가 같은 개념이 있고 그 개념의 스킬 연결된 문항이 1건 이상일 때 연결이다.
      분모는 노드이고 개념 콘텐츠 행은 요구하지 않는다 — Content 와 분모·조건이 달라 따로 움직인다.
  ● Concept Completeness = 핵심 개념 중 5개 연결(Prerequisite · Misconception · Solution · Hint ·
      Pedagogy)이 **모두** 'linked' 인 비율. 연결의 정의는 `_completeness_links` 에 있다.
  ● Graph Connectivity Coverage = 핵심 개념 중 Concept → Skill → Problem → Misconception →
      Pedagogy 경로가 **한 줄로** 이어지는 비율. 한 개념에서 (스킬 s, 문항 p, 핵심 오개념 m)
      이 동시에 성립해야 한다 — s 는 skills(c) 이고, p 는 s 를 행사하는 적격 문항이며, m 은 p 의
      오답 보기가 크로스링크(직접매핑)로 닿는 c 의 핵심 오개념이다. 마지막 고리는 c 의 교수 경로다.

────────────────────────────────────────────────────────────────────────────
Concept Completeness 를 '필드 채움 검사'로 만들지 않은 이유 (acceptance ④ · ARCH-43)
────────────────────────────────────────────────────────────────────────────
원 문서의 정의("Prerequisite·Misconception·Solution·Hint·Pedagogy가 모두 연결된 비율")를 필드가
비어 있지 않은지로 구현하면 ARCH-43 이 이미 기각한 형태가 된다 — 임의 문자열을 받는 필드는
어떤 개념이든(배제를 선언한 과목까지) 채워지므로 성공/실패 양쪽에서 같은 값을 내고 반증력이 0 이다.
그래서 각 연결을 **다른 코퍼스에 실재하는 개체로 해석되는 관계**로 정의했다.

  prerequisite  개념의 원자로 들어오는 선수 간선이 있고, 그 간선의 시작 원자가 원자 백본에 실재한다.
  misconception 명세의 핵심 오개념 중 이 개념에 귀속된 M-id 가 오개념 코퍼스에 실재하고 귀속
                성취기준이 일치한다.
  solution      적격 문항 중 해설과 풀이 단계가 둘 다 있는 문항이 있다.
  hint          힌트가 달린 적격 문항이 있다 — 단 힌트의 저장 좌석이 없어 **현재는 측정 불가**다.
  pedagogy      이 개념의 원자를 목표로 삼는 단원 DSL 목표가 있고 그 목표의 지식 유형에 stub 이
                아닌 교수 팩이 있다.

반증력의 증거 = ① 기준선에서 이미 미충족을 낸다(상시 통과가 아니다) ② 개념별로 '무엇이 빠졌는지'를
적는다 ③ 연결을 하나씩 끊는 주입이 수치를 떨어뜨린다(테스트가 동결) ④ 고립된 개념(코퍼스에 이웃이
없는 개념)은 5개 연결 전부 'missing' 으로 나온다 — 필드 채움 검사가 통과시키던 바로 그 대조군이다.

연결 상태는 3가지다: linked · missing · unmeasured. **측정 불가는 충족이 아니다** — 개념은
5개가 전부 linked 일 때만 완전하다. 그래서 힌트 좌석이 생기기 전에는 Completeness 가 0 이다.
이것은 결함이 아니라 현재 사실이다(ARCH-39 가 힌트 저장 좌석을 '영구 부재'로 판정했고, 7필드 중
`hint_strategy` 의 저장 좌석은 P3-04 가 정한다). 진척이 보이도록 연결별 충족 수와 '측정 가능한
연결만 본 완전 비율'을 **보조 수치**로 함께 내되, 그 수치는 exit code 에 영향을 주지 않는다.

────────────────────────────────────────────────────────────────────────────
CONT-05 판정 — Content Coverage 의 '완전 연결'이 검수 상태를 조건으로 삼는가 (택 ⓑ)
────────────────────────────────────────────────────────────────────────────
학생 공급은 `review_status == "reviewed"` 인 개념 콘텐츠만 통과한다(`l4/content_supply.py`). 검수
전 콘텐츠를 '연결됨'으로 세면 "커버리지 95% 인데 학생 공급 0%" 가 성립한다. 그래서 두 수치를
**별도 지표로 병기**한다.

  · Content Coverage Rate — 연결 여부. 검수 상태와 무관하다(P3-03 이 채우는 대상이 연결이므로,
    검수 승격이라는 사람 서명 없이도 채움의 진척을 잴 수 있어야 한다). 명세 목표 0.95 의 대상이다.
  · 공급 가능 커버리지(supply_coverage) — 위 조건 ∧ 개념 콘텐츠가 `is_supply_eligible`(CONT-05 의
    단일 정본 술어)을 통과. **명세에 목표가 없어 exit code 에 영향을 주지 않는다** — 승격 시점은
    Kiki 의 서명(`G-kg02-review-promotion-llm-session`)이 정하므로 임의 목표를 박지 않는다.
  · 두 수치가 벌어지면 출력이 그 차이를 경고 줄로 적는다(연결 N · 공급 가능 M).

────────────────────────────────────────────────────────────────────────────
측정 방식의 한계 (정직한 공백)
────────────────────────────────────────────────────────────────────────────
· 이 계측기는 풀이의 수학적 정확성을 **재검증하지 않는다**. solution 연결은 해설·단계의 존재와
  문항의 검수 상태만 본다 — 정답 검증 권위는 별도 경로의 몫이다(Solution QA 는 P3-06).
· Misconception → Pedagogy 간선은 코퍼스에 **없다** — 오개념의 오류 유형 어휘와 교수 전략이 적는
  적합 오류 유형 어휘가 겹치지 않는다(2026-10-02 실측). 그래서 교수 경로는 개념 단위로 판정한다.
· 비율은 **전수 계수**다 — 명세가 동결한 모집단 전체를 센다(표본 추정이 아니므로 Wilson 경계가
  필요 없다). 분모가 작으므로 95% 목표는 사실상 '전부 충족'을 뜻한다(10개 중 9개 = 90%).
· 문항 은행은 전 디렉터리를 읽는다(`problem_bank_*`). 명세 밖 개념에 달린 문항은 세지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from whymath_backend.l1.concept_content.review_gate import is_supply_eligible
from whymath_backend.l1.standards.phase3_scope import (
    ConceptEntry,
    ReferenceIndex,
    ScopeSpec,
    ScopeSpecError,
    default_spec_path,
    load_reference_index,
    load_scope_spec,
    verify_spec,
)

# l1/standards/phase3_coverage.py → parents[5]가 레포 루트(phase3_scope 와 같은 관용구).
_REPO_ROOT = Path(__file__).resolve().parents[5]

#: 문항이 지표에 세어지는 검수 상태. 필드가 없거나 다른 값이면 세지 않는다(미검수는 연결 아님).
PROBLEM_ELIGIBLE_STATUS: Final = "approved"

#: 오답 보기 → M-id 도달로 인정하는 크로스링크 연결 의미(`crosslink_resolve` 의 canonical 후보층).
DIRECT_LINK_TYPE: Final = "직접매핑"

#: Concept Completeness 의 연결 5종 — 명세의 `concept_required_links` 와 어긋나면 적재 실패다.
COMPLETENESS_LINKS: Final[tuple[str, ...]] = (
    "prerequisite",
    "misconception",
    "solution",
    "hint",
    "pedagogy",
)

#: Graph Connectivity 경로의 고리(개념에서 출발) — 명세의 `graph_path` 와 어긋나면 적재 실패다.
GRAPH_PATH: Final[tuple[str, ...]] = ("concept", "skill", "problem", "misconception", "pedagogy")

#: Curriculum Coverage 경로 — 명세의 `curriculum_path` 와 어긋나면 적재 실패다.
CURRICULUM_PATH: Final[tuple[str, ...]] = ("curriculum", "concept", "skill", "problem")

#: 코퍼스 위치(레포 루트 기준). 명세의 `sources` 는 참조 검사용 7종이라 여기서 더 읽는 5종만 둔다.
_PROBLEM_GLOB: Final = "data/corpus/problem_bank_*/problems.jsonl"
_CROSSLINKS: Final = "data/corpus/misconception_crosslinks_v1/crosslinks.json"
_CONCEPT_CONTENT: Final = "data/corpus/concept_content_v1/content.json"
_UNITS_GLOB: Final = "data/corpus/units_v1/*.unit.yaml"
_PACKS_GLOB: Final = "data/corpus/pedagogy_packs_v1/*.yaml"

_MIS_ID_RE: Final = re.compile(r"^M\d{4,}$")

LinkStatus = Literal["linked", "missing", "unmeasured"]

#: 힌트 연결이 측정 불가인 이유 — 좌석이 생겨 `hint_problem_ids` 가 채워지면 사라진다.
HINT_UNMEASURED_REASON: Final = (
    "측정 불가 — 힌트 저장 좌석이 없다(ARCH-39 '영구 부재' 판정 · hint_strategy 좌석은 P3-04 소관)"
)


class CoverageError(RuntimeError):
    """계측 입력 적재 실패 — 조용한 0건·빈 통과 대신 던진다(CLI 는 exit 2)."""


# ──────────────────────────────────────────────────────────────────────────
# 계측 입력 모델
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ProblemRef:
    """문항 1건 — 지표가 읽는 축만 담는다."""

    problem_id: str
    primary_src_ids: frozenset[str]
    review_status: str | None
    has_explanation: bool
    has_steps: bool
    problem_type_codes: tuple[str, ...]
    distractor_ids: tuple[str, ...]


@dataclass(frozen=True)
class UnitObjective:
    """단원 DSL 학습 목표 1건 — 교수 경로가 개념에 닿는 유일한 간선(목표의 개념 노드)."""

    unit_id: str
    k_type: str
    concept_nodes: frozenset[str]


@dataclass(frozen=True)
class CoverageCorpus:
    """지표가 읽는 코퍼스 — 테스트가 합성 코퍼스로 바꿔 끼울 수 있게 값 객체로 둔다.

    `hint_problem_ids` 가 `None` 이면 힌트 좌석이 없는 것이다(측정 불가). 집합이면 그 문항들에
    힌트가 달려 있다는 측정 결과다 — P3-04 가 좌석을 정하면 이 자리를 채운다.
    """

    atom_nodes: frozenset[str]
    prerequisite_edges: tuple[tuple[str, str], ...]
    problems: tuple[ProblemRef, ...]
    problems_scanned: int
    type_skills: Mapping[str, tuple[str, ...]]
    crosslinks: Mapping[str, frozenset[str]]
    content_status: Mapping[str, str | None]
    objectives: tuple[UnitObjective, ...]
    full_pack_k_types: frozenset[str]
    stub_pack_k_types: frozenset[str]
    hint_problem_ids: frozenset[str] | None = None


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 적재 — 읽기 실패·0건은 CoverageError
# ──────────────────────────────────────────────────────────────────────────
def _read_json(target: Path, label: str) -> Any:
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverageError(
            f"{label} 코퍼스를 읽지 못했다 ({target}): {type(exc).__name__}: {exc}"
        ) from exc


def _read_yaml(target: Path, label: str) -> Any:
    try:
        return yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CoverageError(
            f"{label} 코퍼스를 읽지 못했다 ({target}): {type(exc).__name__}: {exc}"
        ) from exc


def _nonzero(label: str, count: int) -> None:
    """0건은 '문제 없음'이 아니라 '읽기 실패'다 — 통과시키면 계측이 상시 0 이나 green 이 된다."""
    if count == 0:
        raise CoverageError(f"{label} 코퍼스가 0건이다 — 경로·형식을 확인하라(계측 무력화 방지)")


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _problem_from_row(row: Mapping[str, Any]) -> ProblemRef | None:
    """문항 행 → `ProblemRef`. 개념 태그가 없거나 ID 가 없으면 None(지표가 닿을 수 없는 행)."""
    problem_id = row.get("problem_id")
    if not isinstance(problem_id, str):
        return None
    primary: set[str] = set()
    for tag in row.get("concepts") or []:
        if isinstance(tag, dict) and tag.get("role") == "PRIMARY":
            src = tag.get("concept_src_id")
            if isinstance(src, str):
                primary.add(src)
    verify = row.get("verify")
    steps = verify.get("solution_steps") if isinstance(verify, dict) else None
    types = row.get("problem_type_codes")
    distractors: list[str] = []
    for item in row.get("distractor_map") or []:
        if isinstance(item, dict) and isinstance(item.get("misconception_id"), str):
            distractors.append(item["misconception_id"])
    return ProblemRef(
        problem_id=problem_id,
        primary_src_ids=frozenset(primary),
        review_status=_text(row.get("review_status")),
        has_explanation=_non_empty_text(row.get("answer_explanation")),
        has_steps=isinstance(steps, list) and len(steps) > 0,
        problem_type_codes=tuple(str(t) for t in types) if isinstance(types, list) else (),
        distractor_ids=tuple(distractors),
    )


def _load_problems(root: Path, scope_srcs: frozenset[str]) -> tuple[tuple[ProblemRef, ...], int]:
    """전 문제은행 디렉터리를 읽는다. 명세 범위 개념에 달린 문항만 남기고 읽은 총 행 수를 센다."""
    kept: list[ProblemRef] = []
    scanned = 0
    for path in sorted(root.glob(_PROBLEM_GLOB)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise CoverageError(
                f"문항 코퍼스를 읽지 못했다 ({path}): {type(exc).__name__}: {exc}"
            ) from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CoverageError(
                    f"문항 코퍼스 {number}행 파싱 실패 ({path}): {type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                continue
            scanned += 1
            problem = _problem_from_row(row)
            if problem is not None and problem.primary_src_ids & scope_srcs:
                kept.append(problem)
    _nonzero("문항", scanned)
    return tuple(kept), scanned


def _load_atom_graph(
    spec: ScopeSpec, root: Path
) -> tuple[frozenset[str], tuple[tuple[str, str], ...]]:
    """원자 백본의 전 노드 코드와 선수 간선. 간선의 시작점이 노드로 실재하는지는 지표가 본다."""
    path = root / spec.sources["atoms"]
    payload = _read_json(path, "원자 백본")
    nodes = payload.get("concepts") if isinstance(payload, dict) else None
    edges = payload.get("edges") if isinstance(payload, dict) else None
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise CoverageError(f"{path}: 'concepts'·'edges' 배열이 없다")
    codes = frozenset(str(n["code"]) for n in nodes if isinstance(n, dict) and "code" in n)
    pairs = tuple(
        (str(e["from_code"]), str(e["to_code"]))
        for e in edges
        if isinstance(e, dict)
        and e.get("relation") == "prerequisite"
        and "from_code" in e
        and "to_code" in e
    )
    _nonzero("원자 노드", len(codes))
    _nonzero("선수 간선", len(pairs))
    return codes, pairs


def _load_type_skills(spec: ScopeSpec, root: Path) -> Mapping[str, tuple[str, ...]]:
    """문제유형 → 행동 스킬. 문항이 스킬에 닿는 유일한 간선이다."""
    path = root / spec.sources["problem_types"]
    mapping: dict[str, tuple[str, ...]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CoverageError(
                f"문제유형 코퍼스 {number}행 파싱 실패 ({path}): {type(exc).__name__}: {exc}"
            ) from exc
        if isinstance(row, dict) and isinstance(row.get("problem_type_id"), str):
            skills = row.get("behavior_skills")
            mapping[row["problem_type_id"]] = (
                tuple(str(s) for s in skills) if isinstance(skills, list) else ()
            )
    _nonzero("문제유형", len(mapping))
    return mapping


def _load_crosslinks(root: Path) -> Mapping[str, frozenset[str]]:
    """오답 보기 식별자(kebab) → 직접매핑 M-id 집합."""
    path = root / _CROSSLINKS
    payload = _read_json(path, "오개념 크로스링크")
    rows = payload.get("crosslinks") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CoverageError(f"{path}: 최상위 'crosslinks' 배열이 없다")
    collected: dict[str, set[str]] = {}
    for row in rows:
        if (
            isinstance(row, dict)
            and row.get("link_type") == DIRECT_LINK_TYPE
            and isinstance(row.get("kebab_id"), str)
            and isinstance(row.get("mis_id"), str)
        ):
            collected.setdefault(row["kebab_id"], set()).add(row["mis_id"])
    _nonzero("오개념 크로스링크", len(rows))
    return {k: frozenset(v) for k, v in collected.items()}


def _load_content_status(root: Path) -> Mapping[str, str | None]:
    """개념 콘텐츠 행의 원 개념 ID(`code`) → 검수 상태. 행이 있다는 사실과 상태를 함께 나른다."""
    path = root / _CONCEPT_CONTENT
    payload = _read_json(path, "개념 콘텐츠")
    rows = payload.get("content") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise CoverageError(f"{path}: 최상위 'content' 배열이 없다")
    status = {
        str(r["code"]): _text(r.get("review_status"))
        for r in rows
        if isinstance(r, dict) and "code" in r
    }
    _nonzero("개념 콘텐츠", len(status))
    return status


def _load_objectives(root: Path) -> tuple[UnitObjective, ...]:
    """단원 DSL 의 학습 목표. 개념 노드는 원자 코드다."""
    out: list[UnitObjective] = []
    paths = sorted(root.glob(_UNITS_GLOB))
    _nonzero("단원 DSL", len(paths))
    for path in paths:
        doc = _read_yaml(path, "단원 DSL")
        if not isinstance(doc, dict):
            raise CoverageError(f"{path}: 최상위가 매핑이 아니다")
        unit_id = str(doc.get("unit_id", path.name))
        for obj in doc.get("objectives") or []:
            if not isinstance(obj, dict):
                continue
            nodes = obj.get("concept_nodes")
            k_type = obj.get("k_type")
            if isinstance(k_type, str) and isinstance(nodes, list):
                out.append(UnitObjective(unit_id, k_type, frozenset(str(n) for n in nodes)))
    return tuple(out)


def _load_packs(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """교수 팩의 지식 유형 — (stub 아닌 것, stub). stub 은 자리표시자라 연결로 세지 않는다."""
    full: set[str] = set()
    stub: set[str] = set()
    paths = sorted(root.glob(_PACKS_GLOB))
    _nonzero("교수 팩", len(paths))
    for path in paths:
        doc = _read_yaml(path, "교수 팩")
        if isinstance(doc, dict) and isinstance(doc.get("k_type"), str):
            (stub if doc.get("is_stub") is True else full).add(doc["k_type"])
    return frozenset(full), frozenset(stub)


def load_corpus(
    spec: ScopeSpec,
    repo_root: Path | None = None,
    *,
    hint_problem_ids: frozenset[str] | None = None,
) -> CoverageCorpus:
    """명세 범위의 계측 입력을 코퍼스에서 읽는다. 실패·0건은 `CoverageError`."""
    root = repo_root or _REPO_ROOT
    scope_srcs = frozenset(c.source_id for c in spec.concepts)
    atom_nodes, edges = _load_atom_graph(spec, root)
    problems, scanned = _load_problems(root, scope_srcs)
    full_packs, stub_packs = _load_packs(root)
    return CoverageCorpus(
        atom_nodes=atom_nodes,
        prerequisite_edges=edges,
        problems=problems,
        problems_scanned=scanned,
        type_skills=_load_type_skills(spec, root),
        crosslinks=_load_crosslinks(root),
        content_status=_load_content_status(root),
        objectives=_load_objectives(root),
        full_pack_k_types=full_packs,
        stub_pack_k_types=stub_packs,
        hint_problem_ids=hint_problem_ids,
    )


# ──────────────────────────────────────────────────────────────────────────
# 개념별 사실 — 연결의 정의는 여기(와 `_completeness_links`) 한 곳에만 있다
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ConceptFacts:
    """개념 1건에서 코퍼스를 따라가 얻은 사실. 지표 4종은 이 값만 읽는다."""

    concept: ConceptEntry
    atoms: tuple[str, ...]
    skills: tuple[str, ...]
    content_present: bool
    content_status: str | None
    eligible: tuple[ProblemRef, ...]
    skill_linked: tuple[ProblemRef, ...]
    chain_problems: tuple[ProblemRef, ...]
    prerequisite_sources: tuple[str, ...]
    core_misconceptions: tuple[str, ...]
    objective_k_types: tuple[str, ...]


def _problem_skills(problem: ProblemRef, corpus: CoverageCorpus) -> frozenset[str]:
    found: set[str] = set()
    for code in problem.problem_type_codes:
        found.update(corpus.type_skills.get(code, ()))
    return frozenset(found)


def _reached_misconceptions(problem: ProblemRef, corpus: CoverageCorpus) -> frozenset[str]:
    """문항의 오답 보기가 닿는 M-id — kebab 은 크로스링크로, M-id 는 그대로."""
    reached: set[str] = set()
    for ident in problem.distractor_ids:
        if ident in corpus.crosslinks:
            reached.update(corpus.crosslinks[ident])
        elif _MIS_ID_RE.match(ident):
            reached.add(ident)
    return frozenset(reached)


def _facts(
    spec: ScopeSpec, index: ReferenceIndex, corpus: CoverageCorpus, concept: ConceptEntry
) -> ConceptFacts:
    cross = index.crosswalk.get(concept.concept_id)
    atoms = tuple(a for a in (cross.atom_codes if cross else ()) if a in index.atoms)
    skill_set = {s for a in atoms for s in index.atoms[a].behavior_skills if s in spec.skills}
    skills = tuple(sorted(skill_set))

    eligible = tuple(
        p
        for p in corpus.problems
        if p.review_status == PROBLEM_ELIGIBLE_STATUS and concept.source_id in p.primary_src_ids
    )
    skill_linked = tuple(p for p in eligible if skill_set & _problem_skills(p, corpus))

    # 개념의 핵심 오개념 — 명세가 귀속했고 오개념 코퍼스에 실재하며 귀속 성취기준이 일치한다.
    core_mis = tuple(
        m.mis_id
        for m in spec.core_misconceptions
        if m.concept_code == concept.code and index.misconceptions.get(m.mis_id) == concept.code
    )
    core_set = set(core_mis)
    chain = tuple(p for p in skill_linked if core_set & _reached_misconceptions(p, corpus))

    atom_set = set(atoms)
    sources = tuple(
        sorted(
            {
                src
                for src, dst in corpus.prerequisite_edges
                if dst in atom_set and src != dst and src in corpus.atom_nodes
            }
        )
    )
    k_types = tuple(sorted({o.k_type for o in corpus.objectives if o.concept_nodes & atom_set}))
    return ConceptFacts(
        concept=concept,
        atoms=atoms,
        skills=skills,
        content_present=concept.source_id in corpus.content_status,
        content_status=corpus.content_status.get(concept.source_id),
        eligible=eligible,
        skill_linked=skill_linked,
        chain_problems=chain,
        prerequisite_sources=sources,
        core_misconceptions=core_mis,
        objective_k_types=k_types,
    )


# ──────────────────────────────────────────────────────────────────────────
# 결과 모델
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Unmet:
    """미충족 1건 — 무엇이(대상) 무엇을 못 채웠는지(빠진 것)."""

    subject: str
    missing: tuple[str, ...]


@dataclass(frozen=True)
class MetricResult:
    """지표 1종. `value` 가 None 이면 분모가 0 이라 측정 불가다(통과가 아니라 실패)."""

    key: str
    name_ko: str
    met_count: int
    population: int
    value: float | None
    target: float | None
    met: bool | None
    unmet: tuple[Unmet, ...]
    note: str | None = None

    @property
    def gated(self) -> bool:
        """명세에 목표 수치가 있는 지표만 exit code 에 반영한다."""
        return self.target is not None


@dataclass(frozen=True)
class CoverageReport:
    """계측 결과 전체 — 지표 4종 + 보조 수치."""

    spec_id: str
    frozen_at: str
    frozen_by_gate: str
    metrics: tuple[MetricResult, ...]
    supply: MetricResult
    link_counts: Mapping[str, Mapping[str, int]]
    chain_funnel: Mapping[str, int]
    completeness_measurable: tuple[int, int]
    problems_scanned: int
    warnings: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def exit_code(self) -> int:
        """0 = 충족 · 1 = 목표 미달 또는 측정 불가. 적재 실패(2)는 호출부가 정한다."""
        return 1 if self.failures else 0

    def metric(self, key: str) -> MetricResult:
        for result in (*self.metrics, self.supply):
            if result.key == key:
                return result
        raise KeyError(key)


def _ratio(met_count: int, population: int) -> float | None:
    return met_count / population if population > 0 else None


def _judge(value: float | None, target: float | None) -> bool | None:
    """목표가 없으면 판정하지 않는다(None). 분모 0(value=None)은 목표가 있어도 미충족이다."""
    if target is None:
        return None
    return value is not None and value >= target


# ──────────────────────────────────────────────────────────────────────────
# 지표 4종 — 정의는 모듈 docstring 의 정본과 같아야 한다
# ──────────────────────────────────────────────────────────────────────────
def _content_missing(facts: ConceptFacts) -> list[str]:
    out: list[str] = []
    if not facts.content_present:
        out.append("개념 콘텐츠 행이 없다")
    if not facts.skills:
        out.append("명세 스킬에 닿는 원자 스킬이 없다")
    if not facts.eligible:
        out.append("승인된 PRIMARY 문항이 0건이다")
    elif not facts.skill_linked:
        out.append(
            f"승인 문항 {len(facts.eligible)}건이 있으나 개념 스킬과 겹치는 문제유형 스킬이 없다"
        )
    return out


def _is_fully_linked(facts: ConceptFacts) -> bool:
    return facts.content_present and bool(facts.skill_linked)


def _content_coverage(
    spec: ScopeSpec, facts: tuple[ConceptFacts, ...]
) -> tuple[MetricResult, MetricResult]:
    """Content Coverage Rate(연결)와 공급 가능 커버리지(CONT-05 ⓑ)."""
    target = spec.targets["content_coverage_rate"].value
    linked = [f for f in facts if _is_fully_linked(f)]
    supplyable = [f for f in linked if is_supply_eligible(f.content_status)]
    value = _ratio(len(linked), len(facts))
    unmet = tuple(
        Unmet(f.concept.code, tuple(_content_missing(f))) for f in facts if not _is_fully_linked(f)
    )
    main = MetricResult(
        key="content_coverage_rate",
        name_ko="Content Coverage Rate",
        met_count=len(linked),
        population=len(facts),
        value=value,
        target=target,
        met=_judge(value, target),
        unmet=unmet,
        note="완전 연결 = 개념 콘텐츠 행 ∧ 스킬을 매개로 이어진 승인 문항 (검수 상태 무관)",
    )
    supply_missing = tuple(
        Unmet(
            f.concept.code,
            tuple(_content_missing(f))
            or (
                f"개념 콘텐츠 검수 상태가 {f.content_status!r} 이다(reviewed 만 학생에게 공급된다)",
            ),
        )
        for f in facts
        if f not in supplyable
    )
    supply = MetricResult(
        key="supply_coverage",
        name_ko="공급 가능 커버리지",
        met_count=len(supplyable),
        population=len(facts),
        value=_ratio(len(supplyable), len(facts)),
        target=None,
        met=None,
        unmet=supply_missing,
        note="연결 ∧ 개념 콘텐츠가 검수 통과(CONT-05 ⓐ). 명세에 목표가 없어 exit code 에 영향 없음",
    )
    return main, supply


def _curriculum_coverage(spec: ScopeSpec, all_facts: tuple[ConceptFacts, ...]) -> MetricResult:
    """노드 → 개념 → 스킬 → 문항 경로가 있는 노드의 비율. 개념 콘텐츠 행은 요구하지 않는다.

    핵심이 아닌 개념도 노드의 경로가 될 수 있으므로 핵심 한정이 아닌 전체 개념의 사실을 받는다.
    """
    target = spec.targets["curriculum_coverage"].value
    by_code: dict[str, list[ConceptFacts]] = {}
    for f in all_facts:
        by_code.setdefault(f.concept.code, []).append(f)
    connected = 0
    unmet: list[Unmet] = []
    for node in spec.nodes:
        candidates = by_code.get(node.code, [])
        if any(f.skill_linked for f in candidates):
            connected += 1
            continue
        if not candidates:
            unmet.append(Unmet(node.code, ("이 노드에 연결된 개념이 없다",)))
        else:
            missing = [m for f in candidates for m in _content_missing(f) if "콘텐츠 행" not in m]
            unmet.append(
                Unmet(node.code, tuple(missing) or ("스킬을 매개로 이어진 승인 문항이 없다",))
            )
    value = _ratio(connected, len(spec.nodes))
    return MetricResult(
        key="curriculum_coverage",
        name_ko="Curriculum Coverage",
        met_count=connected,
        population=len(spec.nodes),
        value=value,
        target=target,
        met=_judge(value, target),
        unmet=tuple(unmet),
        note="노드 → 개념 → 스킬 → 문항 (분모=교육과정 노드 · 개념 콘텐츠 행 불요)",
    )


def _completeness_links(
    facts: ConceptFacts, corpus: CoverageCorpus
) -> dict[str, tuple[LinkStatus, str]]:
    """개념의 연결 5종 상태와 근거·빠진 것. 연결의 정의는 모듈 docstring 의 정본과 같다."""
    code = facts.concept.code
    links: dict[str, tuple[LinkStatus, str]] = {}

    if facts.prerequisite_sources:
        links["prerequisite"] = ("linked", f"선수 원자 {len(facts.prerequisite_sources)}개")
    else:
        links["prerequisite"] = ("missing", "이 개념의 원자로 들어오는 선수 간선이 0건이다")

    if facts.core_misconceptions:
        links["misconception"] = ("linked", f"핵심 오개념 {len(facts.core_misconceptions)}개")
    else:
        links["misconception"] = (
            "missing",
            f"{code} 에 귀속된 핵심 오개념이 코퍼스에 실재하지 않는다",
        )

    solved = [p for p in facts.eligible if p.has_explanation and p.has_steps]
    if solved:
        links["solution"] = ("linked", f"해설·단계가 있는 승인 문항 {len(solved)}건")
    elif facts.eligible:
        links["solution"] = (
            "missing",
            f"승인 문항 {len(facts.eligible)}건에 해설 또는 풀이 단계가 없다",
        )
    else:
        links["solution"] = ("missing", "승인된 PRIMARY 문항이 0건이다")

    if corpus.hint_problem_ids is None:
        links["hint"] = ("unmeasured", HINT_UNMEASURED_REASON)
    else:
        hinted = [p for p in facts.eligible if p.problem_id in corpus.hint_problem_ids]
        if hinted:
            links["hint"] = ("linked", f"힌트가 달린 승인 문항 {len(hinted)}건")
        else:
            links["hint"] = ("missing", "힌트가 달린 승인 문항이 0건이다")

    ready = [k for k in facts.objective_k_types if k in corpus.full_pack_k_types]
    if ready:
        links["pedagogy"] = ("linked", f"단원 DSL 목표의 지식 유형 {', '.join(ready)}")
    elif facts.objective_k_types:
        links["pedagogy"] = (
            "missing",
            f"목표의 지식 유형 {', '.join(facts.objective_k_types)} 에 stub 이 아닌 교수 팩이 없다",
        )
    else:
        links["pedagogy"] = (
            "missing",
            "이 개념의 원자를 목표로 삼는 단원 DSL 학습 목표가 없다",
        )
    return links


def _completeness(
    spec: ScopeSpec,
    facts: tuple[ConceptFacts, ...],
    links_by_code: Mapping[str, dict[str, tuple[LinkStatus, str]]],
) -> tuple[MetricResult, Mapping[str, Mapping[str, int]], tuple[int, int]]:
    target = spec.targets["concept_completeness"].value
    counts: dict[str, dict[str, int]] = {
        name: {"linked": 0, "missing": 0, "unmeasured": 0} for name in COMPLETENESS_LINKS
    }
    complete = 0
    measurable_complete = 0
    unmet: list[Unmet] = []
    for f in facts:
        links = links_by_code[f.concept.code]
        for name, (status, _) in links.items():
            counts[name][status] += 1
        if all(status == "linked" for status, _ in links.values()):
            complete += 1
        else:
            unmet.append(
                Unmet(
                    f.concept.code,
                    tuple(
                        f"{name}: {detail}"
                        for name, (status, detail) in links.items()
                        if status != "linked"
                    ),
                )
            )
        if all(status != "missing" for status, _ in links.values()):
            measurable_complete += 1
    value = _ratio(complete, len(facts))
    result = MetricResult(
        key="concept_completeness",
        name_ko="Concept Completeness",
        met_count=complete,
        population=len(facts),
        value=value,
        target=target,
        met=_judge(value, target),
        unmet=tuple(unmet),
        note="연결 5종이 전부 linked (측정 불가는 충족이 아니다)",
    )
    return result, counts, (measurable_complete, len(facts))


def _connectivity(
    spec: ScopeSpec,
    facts: tuple[ConceptFacts, ...],
    links_by_code: Mapping[str, dict[str, tuple[LinkStatus, str]]],
) -> tuple[MetricResult, Mapping[str, int]]:
    """경로를 고리 순서로 깔때기로 센다 — 어느 고리에서 끊기는지가 보이게."""
    target = spec.targets["graph_connectivity_coverage"].value
    funnel = {"skill": 0, "problem": 0, "misconception": 0, "pedagogy": 0}
    unmet: list[Unmet] = []
    full = 0
    for f in facts:
        missing: list[str] = []
        has_skill = bool(f.skills)
        has_problem = bool(f.skill_linked)
        has_mis = bool(f.chain_problems)
        pedagogy_status, pedagogy_detail = links_by_code[f.concept.code]["pedagogy"]
        has_ped = pedagogy_status == "linked"
        if has_skill:
            funnel["skill"] += 1
        else:
            missing.append("concept→skill: 명세 스킬에 닿는 원자 스킬이 없다")
        if has_skill and has_problem:
            funnel["problem"] += 1
        elif has_skill:
            missing.append("skill→problem: 스킬을 매개로 이어진 승인 문항이 없다")
        if has_skill and has_problem and has_mis:
            funnel["misconception"] += 1
        elif has_skill and has_problem:
            missing.append("problem→misconception: 오답 보기가 핵심 오개념에 닿는 문항이 없다")
        if has_skill and has_problem and has_mis and has_ped:
            funnel["pedagogy"] += 1
            full += 1
        elif has_skill and has_problem and has_mis:
            missing.append(f"→pedagogy: {pedagogy_detail}")
        if missing:
            unmet.append(Unmet(f.concept.code, tuple(missing)))
    value = _ratio(full, len(facts))
    result = MetricResult(
        key="graph_connectivity_coverage",
        name_ko="Graph Connectivity Coverage",
        met_count=full,
        population=len(facts),
        value=value,
        target=target,
        met=_judge(value, target),
        unmet=tuple(unmet),
        note="개념 → 스킬 → 문항 → 오개념 → 교수가 한 줄로 이어짐 (목표는 기준선 실측 후 제안)",
    )
    return result, funnel


# ──────────────────────────────────────────────────────────────────────────
# 평가 — 순수 함수(입력은 값 객체뿐이라 합성 코퍼스로 주입 검증이 된다)
# ──────────────────────────────────────────────────────────────────────────
def _check_spec_alignment(spec: ScopeSpec) -> None:
    """명세의 연결·경로 선언이 이 모듈이 구현한 것과 같아야 한다 — 어긋나면 계측이 거짓이 된다."""
    if tuple(spec.concept_required_links) != COMPLETENESS_LINKS:
        raise CoverageError(
            f"명세 concept_required_links {list(spec.concept_required_links)} 가 계측기 정의 "
            f"{list(COMPLETENESS_LINKS)} 와 다르다 — 명세 변경은 PR 로, 계측 정의도 함께 갱신하라"
        )
    if tuple(spec.graph_path) != GRAPH_PATH:
        raise CoverageError(
            f"명세 graph_path {list(spec.graph_path)} 가 계측기 정의 {list(GRAPH_PATH)} 와 다르다"
        )
    if tuple(spec.curriculum_path) != CURRICULUM_PATH:
        raise CoverageError(
            f"명세 curriculum_path {list(spec.curriculum_path)} 가 계측기 정의 "
            f"{list(CURRICULUM_PATH)} 와 다르다"
        )
    for key in (
        "content_coverage_rate",
        "curriculum_coverage",
        "concept_completeness",
        "graph_connectivity_coverage",
    ):
        if key not in spec.targets:
            raise CoverageError(f"명세 targets 에 {key!r} 가 없다 — 지표의 목표를 알 수 없다")


def evaluate(spec: ScopeSpec, index: ReferenceIndex, corpus: CoverageCorpus) -> CoverageReport:
    """지표 4종 + 보조 수치를 계산한다. 분모 0 은 실패로 보고한다(통과로 위장하지 않는다)."""
    _check_spec_alignment(spec)
    all_facts = tuple(_facts(spec, index, corpus, c) for c in spec.concepts)
    facts = tuple(f for f in all_facts if f.concept.core)
    links_by_code = {f.concept.code: _completeness_links(f, corpus) for f in facts}

    content, supply = _content_coverage(spec, facts)
    curriculum = _curriculum_coverage(spec, all_facts)
    completeness, link_counts, measurable = _completeness(spec, facts, links_by_code)
    connectivity, funnel = _connectivity(spec, facts, links_by_code)
    metrics = (content, curriculum, completeness, connectivity)

    failures: list[str] = []
    for m in metrics:
        if m.population == 0:
            failures.append(f"{m.name_ko}: 분모가 0 이다 — 측정 불가(통과가 아니다)")
        elif m.gated and m.met is False:
            assert m.value is not None and m.target is not None
            failures.append(
                f"{m.name_ko}: {m.value:.1%} < 목표 {m.target:.1%} "
                f"({m.met_count}/{m.population}, 미충족 {len(m.unmet)}건)"
            )

    warnings: list[str] = []
    if supply.met_count < content.met_count:
        warnings.append(
            f"연결은 {content.met_count}/{content.population} 이지만 학생 공급 가능은 "
            f"{supply.met_count}/{supply.population} 이다 — 검수 승격(G-kg02) 전 개념 "
            f"{content.met_count - supply.met_count}개는 연결돼 있어도 학생에게 공급되지 않는다"
        )
    unmeasured = [name for name, c in link_counts.items() if c["unmeasured"] > 0]
    if unmeasured:
        warnings.append(
            f"측정 불가 연결: {', '.join(unmeasured)} — Concept Completeness 는 이 연결이 측정될 "
            "때까지 충족될 수 없다(측정 불가는 충족이 아니다)"
        )

    return CoverageReport(
        spec_id=spec.spec_id,
        frozen_at=spec.frozen_at,
        frozen_by_gate=spec.frozen_by_gate,
        metrics=metrics,
        supply=supply,
        link_counts=link_counts,
        chain_funnel=funnel,
        completeness_measurable=measurable,
        problems_scanned=corpus.problems_scanned,
        warnings=tuple(warnings),
        failures=tuple(failures),
    )


# ──────────────────────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────────────────────
def _metric_json(m: MetricResult) -> dict[str, Any]:
    return {
        "key": m.key,
        "name": m.name_ko,
        "met_count": m.met_count,
        "population": m.population,
        "value": m.value,
        "target": m.target,
        "met": m.met,
        "note": m.note,
        "unmet": [{"subject": u.subject, "missing": list(u.missing)} for u in m.unmet],
    }


def to_json(report: CoverageReport) -> dict[str, Any]:
    """기계 판독 출력 — P3-03 이 진척을 이 값으로만 보고한다."""
    return {
        "spec_id": report.spec_id,
        "frozen_at": report.frozen_at,
        "frozen_by_gate": report.frozen_by_gate,
        "exit_code": report.exit_code,
        "metrics": [_metric_json(m) for m in report.metrics],
        "supply_coverage": _metric_json(report.supply),
        "link_counts": {k: dict(v) for k, v in report.link_counts.items()},
        "chain_funnel": dict(report.chain_funnel),
        "completeness_measurable": {
            "complete": report.completeness_measurable[0],
            "population": report.completeness_measurable[1],
        },
        "problems_scanned": report.problems_scanned,
        "warnings": list(report.warnings),
        "failures": list(report.failures),
    }


def _pct(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value:.1%}"


def render(report: CoverageReport) -> str:
    """사람이 읽는 출력 — 지표값 + 미충족 목록(무엇이 빠졌는지)."""
    lines = [
        f"Phase 3 Coverage 계측 — {report.spec_id} (동결 {report.frozen_at} · "
        f"게이트 {report.frozen_by_gate})",
        f"읽은 문항 행 {report.problems_scanned}건",
        "",
        "지표                          값                목표      판정",
    ]
    for m in (*report.metrics, report.supply):
        target = "—" if m.target is None else f"≥{m.target:.0%}"
        verdict = "목표 없음" if m.met is None else ("충족" if m.met else "미달")
        lines.append(
            f"{m.name_ko:<28}  {m.met_count}/{m.population} = {_pct(m.value):<10}  "
            f"{target:<8}  {verdict}"
        )
    lines += ["", "연결별 충족 수 (핵심 개념 기준)"]
    for name, count in report.link_counts.items():
        lines.append(
            f"  {name:<14} linked {count['linked']} · missing {count['missing']} · "
            f"unmeasured {count['unmeasured']}"
        )
    done, total = report.completeness_measurable
    lines.append(f"  측정 가능한 연결만 본 완전 개념(참고·판정 불참여): {done}/{total}")
    funnel = report.chain_funnel
    lines += [
        "",
        "경로 깔때기(개념 → 스킬 → 문항 → 오개념 → 교수)",
        f"  스킬 {funnel['skill']} → 문항 {funnel['problem']} → 오개념 {funnel['misconception']} "
        f"→ 교수 {funnel['pedagogy']}",
    ]
    for m in (*report.metrics, report.supply):
        if not m.unmet:
            continue
        lines += ["", f"[미충족 — {m.name_ko}] {len(m.unmet)}건"]
        for u in m.unmet:
            lines.append(f"  {u.subject}")
            lines += [f"    · {why}" for why in u.missing]
    if report.warnings:
        lines += ["", "경고"]
        lines += [f"  ! {w}" for w in report.warnings]
    lines += ["", "판정: " + ("통과" if report.exit_code == 0 else "미달")]
    lines += [f"  - {f}" for f in report.failures]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3 Coverage 계측기 4종 — 동결 명세 대비 연결 상태를 잰다"
    )
    parser.add_argument("--spec", type=Path, default=None, help="범위 명세 YAML 경로")
    parser.add_argument("--json", action="store_true", help="기계 판독 JSON 으로 출력")
    args = parser.parse_args(argv)
    spec_path = args.spec or default_spec_path()
    try:
        spec = load_scope_spec(spec_path)
        index = load_reference_index(spec)
        violations = verify_spec(spec, index)
        if violations:
            # 분모(명세)가 오염된 상태에서 잰 수치는 의미가 없다 — 측정을 거부한다.
            raise CoverageError(
                "범위 명세가 코퍼스와 어긋나 있다 — 분모를 신뢰할 수 없어 측정을 거부한다:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )
        report = evaluate(spec, index, load_corpus(spec))
    except (ScopeSpecError, CoverageError) as exc:
        print(f"[적재 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(to_json(report), ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
