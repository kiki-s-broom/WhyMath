"""EOS Learning Loop Contract v1 동결 — 정본 `docs/architecture/learning_loop_contract_v1.md`의
기계 집행(`EOS-100`).

이 파일이 **강제하는 것**(정본화≠집행 — CLAUDE.md):
  ① 루프 객체 14종 고정 — 15번째가 생기면 RED(노드 폭발 방어).
  ② 관계 삼중항 18건 고정 — 미선언 관계가 생기면 RED(관계 폭발 방어).
  ③ 어휘 폐쇄성 — 관계 성분이 전부 enum 멤버이고, 죽은 엣지 타입이 없다.
  ④ 좌석 귀속이 14객체를 전수 1:1 커버.
  ⑤ 귀속이 지목한 엔티티가 `ARCH-37` §2-A 표에 실재(유령 엔티티·오탈자 차단).
  ⑥ 고립 객체 집합이 관계에서 **계산한 값**과 일치(상수 두 벌 금지).
  ⑦ `prerequisite` DAG 축 — 제약 선언·집행 지점 실재·순환 검출·기존 구현과의 판정 일치.
  ⑧ 정본 문서 §2·§3 표 ↔ 코드 상수 1:1(드리프트 차단).
  ⑨ 파서가 위장하지 않는다 — 표를 못 찾으면 "0건 통과"가 아니라 예외.

이 파일이 **강제하지 않는 것**(있는 척 금지):
  · **서빙 배선.** 오늘 이 계약을 읽는 API·엔진은 0건이다. 배선은 `EOS-10`·`EOS-12`·`EOS-13`·
    `EOS-14`가 각자 소유하며, 이 스위트가 초록이라고 "루프가 계약대로 돈다"는 뜻이 아니다.
  · **관계의 옳음.** 코드와 문서가 서로 일치하는지만 본다 — 둘이 사이좋게 틀리면 통과한다.
  · **실데이터 DAG 무결성.** 실적재 차단은 `DAG_ENFORCEMENT_POINTS` 2지점 소관이며, 여기서는
    그 파일의 *실재*와 알고리즘 *판정 일치*까지만 본다(적재 실행은 DB가 필요해 스위트 밖).
  · **좌석 축.** 테이블↔엔티티 배정은 여전히 `ARCH-37` 정본 하나가 소유한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from whymath_backend.l1.atom_graph.atom_backend_edge import AtomBackendEdgeRecord
from whymath_backend.l1.atom_graph.populate import _find_prerequisite_cycle_in_records
from whymath_backend.schema.enums import EdgeType
from whymath_backend.schema.learning_loop_contract import (
    CANONICAL_ENTITY_DOC_PATH,
    CANONICAL_SEAT_BINDINGS,
    CONTRACT_DOC_PATH,
    DAG_CONSTRAINED_EDGES,
    DAG_ENFORCEMENT_POINTS,
    LOOP_OBJECTS_WITHOUT_RELATIONS,
    LOOP_RELATIONS,
    LoopEdge,
    LoopObject,
    SeatStatus,
    find_prerequisite_cycle,
    is_declared_relation,
    reachable_from,
    relations_from,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ── 동결 입력 경로의 단일 진실 원천 ──────────────────────────────────────────
# `tests/infra/test_ci_contract_fixture_trigger_wiring.py`가 `tests/backend/**`를 전수 스캔해
# **이 상수를 AST로 파싱**하고 전건이 CI backend 잡 경로 필터 안에 있는지 동결한다(OPS-62).
# 필터 밖이면 이 문서들만 고치는 PR에서 backend 잡이 SKIP되고, skip은 required check에서
# 충족으로 계상돼 **드리프트가 무검출로 통과한다**.
# ⚠️ 리터럴 튜플 형태를 유지할 것 — AST 파서가 문자열 상수만 읽는다(f-string·연산 금지).
FROZEN_INPUT_PATHS: tuple[str, ...] = (
    "docs/architecture/learning_loop_contract_v1.md",
    "docs/architecture/canonical_entity_model_v1.md",
)


class LoopContractDocParseError(RuntimeError):
    """정본 문서에서 기대한 표를 찾지 못했다 — **0건 통과로 위장하지 않는다**(검사 ⑨).

    CLAUDE.md "측정 실패가 0건 통과로 위장되면 안 된다" · "침묵 실패 금지"(예외 타입명 동반).
    """


# ══════════════════════════════════════════════════════════════════════════
# 문서 파서 — 표를 못 찾으면 예외(검사 ⑨)
# ══════════════════════════════════════════════════════════════════════════

#: `| 1 | `Learner` | `has` | `LearnerState` |` 형태의 관계 표 행.
_RELATION_ROW = re.compile(
    r"^\|\s*(\d+)\s*\|\s*`([A-Za-z]+)`\s*\|\s*`([a-z_]+)`\s*\|\s*`([A-Za-z]+)`\s*\|\s*$"
)

#: `| `Learner` | `Learner` | `seated` | 아니오 | ... |` 형태의 귀속 표 행.
#: 정본 엔티티 칸은 `no_seat`일 때 백틱 없는 `—`이므로 두 형태를 모두 받는다.
_SEAT_ROW = re.compile(
    r"^\|\s*`([A-Za-z]+)`\s*\|\s*(?:`([A-Za-z]+)`|—)\s*\|\s*`([a-z_]+)`\s*\|\s*(예|아니오)\s*\|"
)

#: `ARCH-37` §2-A 표 행 — `| 1 | **Subject** | — **좌석 부재**(§3) | 0 |`
_CANON_ENTITY_ROW = re.compile(r"^\|\s*\d+\s*\|\s*\*\*([A-Za-z]+)\*\*\s*\|")


def _read(path: str) -> str:
    target = _REPO_ROOT / path
    if not target.is_file():
        raise LoopContractDocParseError(f"정본 문서 부재: {path}")
    return target.read_text(encoding="utf-8")


def _parse_doc_relations(text: str) -> list[tuple[int, str, str, str]]:
    rows = [
        (int(m.group(1)), m.group(2), m.group(3), m.group(4))
        for line in text.splitlines()
        if (m := _RELATION_ROW.match(line.rstrip()))
    ]
    if not rows:
        raise LoopContractDocParseError(
            f"{CONTRACT_DOC_PATH} §2 관계표를 한 행도 파싱하지 못했다 — 표 형식이 바뀌었거나 "
            "정규식이 낡았다. 스캔 0건은 통과가 아니라 실패다."
        )
    return rows


def _parse_doc_seats(text: str) -> list[tuple[str, str | None, str, bool]]:
    rows = [
        (m.group(1), m.group(2), m.group(3), m.group(4) == "예")
        for line in text.splitlines()
        if (m := _SEAT_ROW.match(line.rstrip()))
    ]
    if not rows:
        raise LoopContractDocParseError(
            f"{CONTRACT_DOC_PATH} §3 귀속표를 한 행도 파싱하지 못했다 — 스캔 0건은 실패다."
        )
    return rows


def _parse_canonical_entities(text: str) -> list[str]:
    names = [
        m.group(1) for line in text.splitlines() if (m := _CANON_ENTITY_ROW.match(line.rstrip()))
    ]
    if not names:
        raise LoopContractDocParseError(
            f"{CANONICAL_ENTITY_DOC_PATH} §2-A 좌석표를 한 행도 파싱하지 못했다 — 스캔 0건은 실패다."
        )
    return names


# ══════════════════════════════════════════════════════════════════════════
# 검사 ① — 루프 객체 14종 고정
# ══════════════════════════════════════════════════════════════════════════

#: 계획서 300 §1 EOS Kernel 그대로. **이 집합을 늘리는 것이 곧 계약 변경이다.**
#: 지시문 `P-01`은 "13개"라고 적었으나 열거된 이름은 14개다(목록이 정본·개수 표기가 오기).
_EXPECTED_OBJECTS: frozenset[str] = frozenset(
    {
        "Learner",
        "LearnerState",
        "Curriculum",
        "Objective",
        "Concept",
        "Skill",
        "Content",
        "Problem",
        "Attempt",
        "AssessmentEvidence",
        "Misconception",
        "Mastery",
        "Recommendation",
        "LearningSession",
    }
)


def test_loop_objects_are_exactly_fourteen() -> None:
    actual = {member.value for member in LoopObject}
    assert actual == _EXPECTED_OBJECTS, (
        "루프 어휘가 바뀌었다. 객체 추가·삭제는 계약 변경이므로 "
        f"{CONTRACT_DOC_PATH} §1과 이 상수를 함께 고쳐라. "
        f"추가={sorted(actual - _EXPECTED_OBJECTS)} 삭제={sorted(_EXPECTED_OBJECTS - actual)}"
    )
    assert len(list(LoopObject)) == 14


# ══════════════════════════════════════════════════════════════════════════
# 검사 ② — 관계 삼중항 18건 고정
# ══════════════════════════════════════════════════════════════════════════

_EXPECTED_RELATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("Learner", "has", "LearnerState"),
        ("LearnerState", "mastery", "Concept"),
        ("LearnerState", "mastery", "Skill"),
        ("LearnerState", "misconception", "Misconception"),
        ("LearnerState", "current_goal", "Objective"),
        ("Objective", "requires", "Concept"),
        ("Concept", "prerequisite", "Concept"),
        ("Concept", "taught_by", "Content"),
        ("Concept", "assessed_by", "Problem"),
        ("Concept", "associated_with", "Misconception"),
        ("Problem", "assesses", "Concept"),
        ("Problem", "assesses", "Skill"),
        ("Problem", "triggers", "Misconception"),
        ("Attempt", "made_by", "Learner"),
        ("Attempt", "on", "Problem"),
        ("Attempt", "produces", "AssessmentEvidence"),
        ("AssessmentEvidence", "updates", "LearnerState"),
        ("LearnerState", "feeds", "Recommendation"),
    }
)


def _as_triples() -> frozenset[tuple[str, str, str]]:
    return frozenset((r.source.value, r.edge.value, r.target.value) for r in LOOP_RELATIONS)


def test_loop_relations_are_exactly_eighteen() -> None:
    actual = _as_triples()
    assert actual == _EXPECTED_RELATIONS, (
        "관계 계약이 바뀌었다. 미선언 관계 추가는 CLAUDE.md 붕괴 연쇄 2단계(관계 폭발)다. "
        f"추가={sorted(actual - _EXPECTED_RELATIONS)} 삭제={sorted(_EXPECTED_RELATIONS - actual)}"
    )
    # 중복 선언 금지 — 튜플 길이와 집합 크기가 같아야 한다.
    assert len(LOOP_RELATIONS) == len(actual) == 18


def test_is_declared_relation_accepts_only_declared_triples() -> None:
    assert is_declared_relation(LoopObject.ATTEMPT, LoopEdge.ON, LoopObject.PROBLEM)
    # 방향을 뒤집으면 거짓 — 단방향 canonical edge 원칙.
    assert not is_declared_relation(LoopObject.PROBLEM, LoopEdge.ON, LoopObject.ATTEMPT)
    # 엣지 타입만 바꿔도 거짓.
    assert not is_declared_relation(LoopObject.ATTEMPT, LoopEdge.HAS, LoopObject.PROBLEM)


def test_relations_from_matches_registry() -> None:
    for obj in LoopObject:
        assert relations_from(obj) == tuple(r for r in LOOP_RELATIONS if r.source == obj)
    assert len(relations_from(LoopObject.LEARNER_STATE)) == 5
    assert relations_from(LoopObject.CURRICULUM) == ()


# ══════════════════════════════════════════════════════════════════════════
# 검사 ③ — 어휘 폐쇄성(성분이 enum 멤버 · 죽은 엣지 타입 0)
# ══════════════════════════════════════════════════════════════════════════


def test_relation_components_are_closed_over_the_vocabulary() -> None:
    for relation in LOOP_RELATIONS:
        assert isinstance(relation.source, LoopObject), f"미정의 source: {relation}"
        assert isinstance(relation.target, LoopObject), f"미정의 target: {relation}"
        assert isinstance(relation.edge, LoopEdge), f"미정의 edge: {relation}"


def test_no_dead_edge_types() -> None:
    """선언만 되고 아무 관계도 쓰지 않는 엣지 타입은 어휘 오염이다."""
    used = {r.edge for r in LOOP_RELATIONS}
    dead = set(LoopEdge) - used
    assert not dead, f"어느 관계도 쓰지 않는 엣지 타입: {sorted(e.value for e in dead)}"


def test_traversal_forbidden_edge_names_are_absent() -> None:
    """`similar_to`·`related_to`는 traversal 사용 금지 대상이라 어휘에 없어야 한다(CLAUDE.md)."""
    names = {e.value for e in LoopEdge}
    assert "similar_to" not in names
    assert "related_to" not in names


# ══════════════════════════════════════════════════════════════════════════
# 검사 ④⑤ — 좌석 귀속 전수성 + 정본 엔티티 실재
# ══════════════════════════════════════════════════════════════════════════


def test_seat_bindings_cover_every_loop_object_exactly_once() -> None:
    bound = [b.loop_object for b in CANONICAL_SEAT_BINDINGS]
    assert len(bound) == len(set(bound)) == 14, f"중복·누락 귀속: {bound}"
    assert set(bound) == set(LoopObject)


def test_seat_bindings_point_at_entities_that_exist_in_arch37_canon() -> None:
    canonical = set(_parse_canonical_entities(_read(CANONICAL_ENTITY_DOC_PATH)))
    assert len(canonical) == 19, f"ARCH-37 §2-A 표에서 19종이 아니라 {len(canonical)}종을 읽었다"
    for binding in CANONICAL_SEAT_BINDINGS:
        if binding.status is SeatStatus.NO_SEAT:
            assert binding.canonical_entity is None, f"no_seat인데 엔티티를 지목: {binding}"
            continue
        assert binding.canonical_entity in canonical, (
            f"{binding.loop_object} 가 지목한 '{binding.canonical_entity}' 는 "
            f"{CANONICAL_ENTITY_DOC_PATH} §2-A 19종에 없다(유령 엔티티·오탈자)."
        )


def test_alias_bindings_really_have_a_different_name() -> None:
    """`seated_alias`인데 이름이 같으면 분류가 거짓말이다 — 반대 방향도 본다."""
    for binding in CANONICAL_SEAT_BINDINGS:
        same_name = binding.canonical_entity == binding.loop_object.value
        if binding.status is SeatStatus.SEATED_ALIAS:
            assert not same_name, f"alias인데 동명: {binding.loop_object}"
        if binding.status is SeatStatus.SEATED:
            assert same_name, f"seated인데 이름이 다르다: {binding.loop_object}"


def test_no_new_entity_seat_is_introduced() -> None:
    """이 계약은 20번째 엔티티를 만들지 않는다 — `ARCH-37` 배제 판정 불변(§0)."""
    named = {b.canonical_entity for b in CANONICAL_SEAT_BINDINGS if b.canonical_entity}
    canonical = set(_parse_canonical_entities(_read(CANONICAL_ENTITY_DOC_PATH)))
    assert named <= canonical, f"정본 19종 밖의 엔티티를 신설했다: {sorted(named - canonical)}"


def test_no_semantic_name_collisions_remain() -> None:
    """이름 충돌은 **0건**이어야 한다 — 2026-09-16 Kiki 판정(A안)으로 해소됐다(§3-1).

    유일한 충돌이던 `Assessment`를 계획서 쪽에서 `AssessmentEvidence`로 개명했다. 저장소 정본
    `Assessment`(진단 평가 세션·`ARCH-37` #15)는 이름을 유지한다 — ORM `Assessment`→테이블
    `assessment`가 백엔드 29파일·테스트 18파일·마이그레이션 4건에 물려 있어 정본 개명(B안)은
    파급이 크다는 실측이 근거다.

    충돌이 새로 생기면 이 검사가 RED다. 즉 **조용히 늘어날 수 없다** — 새 충돌은 판정을 거쳐
    상수에 적히거나, 개명으로 해소되거나 둘 중 하나다.
    """
    collisions = {b.loop_object for b in CANONICAL_SEAT_BINDINGS if b.semantic_collision}
    assert collisions == set(), (
        "이름 충돌이 되살아났다. 같은 글자가 서로 다른 것을 가리키는 상태는 판정 없이 두지 "
        f"않는다(§3-1). 현재={sorted(o.value for o in collisions)}"
    )


def test_plan_side_assessment_is_renamed_not_the_canonical_entity() -> None:
    """A안의 방향을 동결한다 — 개명된 쪽은 **계획서 어휘**이지 정본 엔티티가 아니다.

    반대 방향(정본 `Assessment`를 건드리는 것)은 `ARCH-37` 좌석 동결이 별도로 막지만, 루프
    어휘가 `Assessment`라는 글자를 **다시 쓰기 시작하는 것**은 여기서만 막힌다.
    """
    names = {o.value for o in LoopObject}
    assert "AssessmentEvidence" in names
    assert "Assessment" not in names, (
        "루프 어휘가 'Assessment'를 다시 쓴다 — 정본 엔티티(진단 세션)와 글자가 겹쳐 "
        "2026-09-16에 해소한 충돌이 되살아난다."
    )


# ══════════════════════════════════════════════════════════════════════════
# 검사 ⑩ — 루프 어휘 밖 엔티티 목록은 계산값과 일치한다
# ══════════════════════════════════════════════════════════════════════════

#: `| `Subject` · `CurriculumNode` · ...` 꼴 §3-2 산문 목록의 백틱 이름.
_BACKTICK_NAME = re.compile(r"`([A-Za-z]+)`")


def _parse_doc_outside_entities(text: str) -> frozenset[str]:
    """정본 §3-2가 "루프 어휘 밖"으로 적은 엔티티 이름 집합."""
    marker = "### 3-2."
    if marker not in text:
        raise LoopContractDocParseError(
            f"{CONTRACT_DOC_PATH} §3-2 절을 찾지 못했다 — 스캔 0건은 실패다."
        )
    section = text.split(marker, 1)[1].split("\n---", 1)[0]
    # 목록은 "> 이 목록은" 로 시작하는 해설 앞까지다(해설의 백틱까지 세면 오염된다).
    listing = section.split("\n>", 1)[0]
    names = frozenset(_BACKTICK_NAME.findall(listing))
    if not names:
        raise LoopContractDocParseError(
            f"{CONTRACT_DOC_PATH} §3-2 목록에서 엔티티 이름을 한 건도 파싱하지 못했다."
        )
    return names


def test_doc_outside_entity_list_matches_the_computed_set() -> None:
    """§3-2 목록 = (`ARCH-37` 19종) − (귀속표가 지목한 엔티티). **하드코딩 두 벌 금지.**

    `EOS-100`이 이 목록을 손으로 적으면서 `LearningEvent`를 잘못 포함시켰다 —
    `Attempt`·`LearningSession`이 이미 그 엔티티에 귀속되므로 '밖'이 아니다(8종이 아니라 7종이
    맞았다). 그리고 문서는 "이 목록은 하드코딩이 아니다 — 검사 ⑤가 계산한다"고 적었는데
    **검사 ⑤는 그 집합을 계산하지 않았다**(정본화를 집행으로 착각한 표기). 이 검사가 그 주장을
    비로소 참으로 만든다.
    """
    canonical = frozenset(_parse_canonical_entities(_read(CANONICAL_ENTITY_DOC_PATH)))
    named = frozenset(b.canonical_entity for b in CANONICAL_SEAT_BINDINGS if b.canonical_entity)
    computed = canonical - named
    documented = _parse_doc_outside_entities(_read(CONTRACT_DOC_PATH))
    assert documented == computed, (
        f"{CONTRACT_DOC_PATH} §3-2 목록이 계산값과 다르다. "
        f"문서만={sorted(documented - computed)} 계산만={sorted(computed - documented)}"
    )


def test_canonical_assessment_entity_is_outside_the_loop_vocabulary() -> None:
    """A안의 귀결 — 정본 `Assessment`(진단 세션)는 루프 어휘 밖이다.

    개명 전에는 루프 객체 `Assessment`가 이 엔티티를 좌석으로 지목해 **안쪽**에 있었다.
    A안으로 그 지목이 끊겼으므로 밖으로 이동해야 하며, 이 검사가 그 이동을 동결한다.
    """
    named = {b.canonical_entity for b in CANONICAL_SEAT_BINDINGS if b.canonical_entity}
    assert "Assessment" not in named, (
        "정본 Assessment(진단 세션)를 루프 객체가 다시 좌석으로 지목한다 — "
        "AssessmentEvidence는 LearningEvent에 흡수되지 진단 세션에 앉지 않는다."
    )
    assert "Assessment" in _parse_doc_outside_entities(_read(CONTRACT_DOC_PATH))


# ══════════════════════════════════════════════════════════════════════════
# 검사 ⑥ — 고립 객체는 상수가 아니라 계산과 일치해야 한다
# ══════════════════════════════════════════════════════════════════════════


def test_isolated_objects_match_what_the_relations_actually_say() -> None:
    touched = {r.source for r in LOOP_RELATIONS} | {r.target for r in LOOP_RELATIONS}
    computed = frozenset(set(LoopObject) - touched)
    assert computed == LOOP_OBJECTS_WITHOUT_RELATIONS, (
        "고립 객체 상수가 관계 레지스트리와 어긋났다(진실 원천 두 벌). "
        f"계산={sorted(o.value for o in computed)} "
        f"상수={sorted(o.value for o in LOOP_OBJECTS_WITHOUT_RELATIONS)}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 검사 ⑦ — prerequisite DAG 축
# ══════════════════════════════════════════════════════════════════════════


def test_prerequisite_is_the_only_dag_constrained_edge() -> None:
    assert DAG_CONSTRAINED_EDGES == frozenset({LoopEdge.PREREQUISITE})


def test_prerequisite_is_the_only_self_referencing_relation() -> None:
    """자기참조 관계가 늘면 DAG 강제 대상도 함께 늘어야 한다 — 조용한 증가 차단."""
    self_refs = {r.edge for r in LOOP_RELATIONS if r.source == r.target}
    assert self_refs == DAG_CONSTRAINED_EDGES, (
        f"자기참조 엣지={sorted(e.value for e in self_refs)} 인데 "
        f"DAG 제약={sorted(e.value for e in DAG_CONSTRAINED_EDGES)} — 둘이 어긋났다."
    )


def test_dag_enforcement_points_exist() -> None:
    """정본화 ≠ 집행 — 실적재 차단자가 실제로 저장소에 있는지 본다(경로 rename 차단)."""
    for path in DAG_ENFORCEMENT_POINTS:
        assert (_REPO_ROOT / path).is_file(), (
            f"DAG 집행 지점이 사라졌다: {path}. 이 계약은 순환을 *선언*만 하고 "
            "적재 차단은 그 파일들이 소유한다 — 사라지면 선언만 남는다."
        )


@pytest.mark.parametrize(
    ("edges", "expected_cycle_nodes"),
    [
        pytest.param([("a", "a")], {"a"}, id="자기루프"),
        pytest.param([("a", "b"), ("b", "a")], {"a", "b"}, id="2-사이클"),
        pytest.param([("a", "b"), ("b", "c"), ("c", "a")], {"a", "b", "c"}, id="3-사이클"),
        pytest.param(
            [("root", "a"), ("a", "b"), ("b", "c"), ("c", "a")],
            {"a", "b", "c"},
            id="진입경로가_있는_사이클",
        ),
        pytest.param(
            [("x", "y"), ("p", "q"), ("q", "r"), ("r", "p")],
            {"p", "q", "r"},
            id="DAG와_사이클이_공존하는_분리그래프",
        ),
    ],
)
def test_find_prerequisite_cycle_detects_injected_cycles(
    edges: list[tuple[str, str]], expected_cycle_nodes: set[str]
) -> None:
    cycle = find_prerequisite_cycle(edges)
    assert cycle is not None, f"순환을 주입했는데 못 찾았다: {edges}"
    # 반환 경로는 닫힘 노드를 반복 포함한다 — 첫 노드와 끝 노드가 같아야 한다.
    assert cycle[0] == cycle[-1], f"닫힘 노드 미포함: {cycle}"
    assert set(cycle) == expected_cycle_nodes, f"순환 경로가 기대와 다르다: {cycle}"


@pytest.mark.parametrize(
    "edges",
    [
        pytest.param([], id="빈그래프"),
        pytest.param([("a", "b")], id="엣지1"),
        pytest.param([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")], id="다이아몬드"),
        pytest.param([(f"n{i}", f"n{i + 1}") for i in range(400)], id="깊은체인_400"),
    ],
)
def test_find_prerequisite_cycle_passes_clean_dags(edges: list[tuple[str, str]]) -> None:
    """성공 방향 대조군 — "전부 순환"이라는 과잉 수정이 통과하지 못하게 한다."""
    assert find_prerequisite_cycle(edges) is None


def test_deep_chain_does_not_blow_the_stack() -> None:
    """원자 백본은 2,683노드 규모다 — 재귀 구현이면 여기서 RecursionError로 죽는다."""
    edges = [(f"n{i}", f"n{i + 1}") for i in range(5000)]
    assert find_prerequisite_cycle(edges) is None
    assert len(reachable_from("n0", edges)) == 5000


def test_contract_primitive_agrees_with_the_existing_l1_enforcer() -> None:
    """순환 탐지 구현이 3벌이므로(§2-1 정직한 공백) **판정이 갈리는지**를 기계가 본다.

    통합 자체는 `EOS-101` 소관이다. 그때까지 조용한 분기만은 막는다.
    """
    fixtures: list[list[tuple[str, str]]] = [
        [],
        [("a", "b")],
        [("a", "b"), ("b", "c"), ("c", "a")],
        [("a", "a")],
        [("root", "a"), ("a", "b"), ("b", "c"), ("c", "a")],
        [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
        [("x", "y"), ("p", "q"), ("q", "r"), ("r", "p")],
    ]
    for edges in fixtures:
        records = [
            AtomBackendEdgeRecord(
                from_code=src,
                to_code=dst,
                edge_type=EdgeType.PREREQUISITE,
                edge_strength=None,
                relation_subtype=None,
            )
            for src, dst in edges
        ]
        mine = find_prerequisite_cycle(edges)
        theirs = _find_prerequisite_cycle_in_records(records)
        assert (mine is None) == (theirs is None), (
            f"계약층 primitive와 l1 집행자의 판정이 갈렸다: edges={edges} "
            f"contract={mine} l1={theirs}"
        )
        if mine is not None and theirs is not None:
            assert set(mine) == set(theirs), f"같은 순환을 다르게 짚었다: {mine} vs {theirs}"


@pytest.mark.parametrize(
    ("edges", "start", "expected"),
    [
        pytest.param([("a", "b"), ("b", "c")], "a", {"b", "c"}, id="선형"),
        pytest.param([("a", "b"), ("b", "c")], "c", set(), id="말단"),
        pytest.param([("a", "b"), ("b", "a")], "a", {"a", "b"}, id="순환은_자기자신_포함"),
        pytest.param([("a", "b")], "없는노드", set(), id="미존재_시작점"),
    ],
)
def test_reachable_from(edges: list[tuple[str, str]], start: str, expected: set[str]) -> None:
    assert reachable_from(start, edges) == frozenset(expected)


def test_reachability_check_flags_a_node_that_is_its_own_prerequisite() -> None:
    """Reachability Check 본체 — `start in reachable_from(start)` 이면 그 노드가 순환 안에 있다."""
    acyclic = [("a", "b"), ("b", "c")]
    cyclic = [("a", "b"), ("b", "c"), ("c", "a")]
    assert "a" not in reachable_from("a", acyclic)
    assert "a" in reachable_from("a", cyclic)


# ══════════════════════════════════════════════════════════════════════════
# 검사 ⑧ — 정본 문서 ↔ 코드 상수 1:1
# ══════════════════════════════════════════════════════════════════════════


def test_doc_relation_table_matches_the_registry() -> None:
    rows = _parse_doc_relations(_read(CONTRACT_DOC_PATH))
    assert [n for n, *_ in rows] == list(
        range(1, len(rows) + 1)
    ), f"§2 표의 번호가 1..N 연속이 아니다: {[n for n, *_ in rows]}"
    doc_triples = frozenset((s, e, t) for _, s, e, t in rows)
    assert doc_triples == _as_triples(), (
        f"{CONTRACT_DOC_PATH} §2 표 ↔ LOOP_RELATIONS 드리프트. "
        f"문서만={sorted(doc_triples - _as_triples())} 코드만={sorted(_as_triples() - doc_triples)}"
    )


def test_doc_seat_table_matches_the_bindings() -> None:
    rows = _parse_doc_seats(_read(CONTRACT_DOC_PATH))
    doc = {obj: (entity, status, collision) for obj, entity, status, collision in rows}
    code = {
        b.loop_object.value: (b.canonical_entity, b.status.value, b.semantic_collision)
        for b in CANONICAL_SEAT_BINDINGS
    }
    assert doc == code, (
        f"{CONTRACT_DOC_PATH} §3 귀속표 ↔ CANONICAL_SEAT_BINDINGS 드리프트. "
        f"문서만={sorted(set(doc.items()) - set(code.items()))} "
        f"코드만={sorted(set(code.items()) - set(doc.items()))}"
    )


def test_doc_lists_every_loop_object_in_section_one() -> None:
    """§1 산문 목록도 14종을 전부 적어야 한다 — 표만 고치고 산문을 두는 드리프트 차단."""
    text = _read(CONTRACT_DOC_PATH)
    section = text.split("## §1.", 1)[-1].split("## §2.", 1)[0]
    missing = [o.value for o in LoopObject if f"`{o.value}`" not in section]
    assert not missing, f"{CONTRACT_DOC_PATH} §1 산문에 빠진 객체: {missing}"


# ══════════════════════════════════════════════════════════════════════════
# 검사 ⑨ — 파서가 위장하지 않는다
# ══════════════════════════════════════════════════════════════════════════


def test_parsers_raise_instead_of_passing_on_zero_rows(tmp_path: Path) -> None:
    """스캔 0건은 통과가 아니라 실패다(CLAUDE.md "스캔 0건은 실패")."""
    with pytest.raises(LoopContractDocParseError):
        _parse_doc_relations("표가 하나도 없는 문서")
    with pytest.raises(LoopContractDocParseError):
        _parse_doc_seats("표가 하나도 없는 문서")
    with pytest.raises(LoopContractDocParseError):
        _parse_canonical_entities("표가 하나도 없는 문서")
    with pytest.raises(LoopContractDocParseError):
        _read("docs/architecture/존재하지_않는_정본.md")


def test_frozen_input_paths_actually_exist() -> None:
    """동결 입력이 사라지면 CI 필터 가드가 죽은 경로를 지키게 된다."""
    for path in FROZEN_INPUT_PATHS:
        assert (_REPO_ROOT / path).is_file(), f"동결 입력 부재: {path}"
