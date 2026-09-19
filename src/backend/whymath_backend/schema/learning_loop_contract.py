"""EOS Learning Loop Contract v1 — 14객체·18관계 계약의 코드 정본.

계획서 300 「Phase 2 — EOS Closed Learning Loop」 §1(EOS Kernel)·§2(알고리즘보다 Contract)가
요구하는 **학습 루프의 최소 어휘**를 코드 상수로 고정한다. 정본 산문은
`docs/architecture/learning_loop_contract_v1.md`이며, 이 모듈과 그 문서는 1:1이다
(`tests/backend/schema/test_learning_loop_contract.py` 검사 ⑧이 어긋남을 RED로 낸다).

이 모듈이 **하는 것**
---------------------
① 루프 어휘를 14객체로 닫는다 — 15번째 객체가 조용히 생기지 못하게 한다(노드 폭발 방어).
② 객체 사이에 허용된 관계를 (source, edge, target) 삼중항 18건으로 닫는다 — 관계 폭발 방어.
   CLAUDE.md 붕괴 연쇄 2단계(`Edge ≈ N²`)의 계약층 방어선이다.
③ 14객체를 `ARCH-37` 핵심 엔티티 19종 좌석 정본에 **귀속**시킨다 — 좌석 없는 객체(`NO_SEAT`)와
   다른 좌석에 흡수된 객체(`ABSORBED`)를 날조하지 않고 그대로 적는다.
④ `prerequisite` 관계의 DAG 불변식을 선언하고, 계약층 검사용 순환 탐지 primitive를 제공한다.

이 모듈이 **하지 않는 것** (있는 척 금지 — CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지")
------------------------------------------------------------------------------------------
- **신규 DB 테이블·신규 좌석을 만들지 않는다.** `ARCH-37`이 엣지 테이블(`concept_edge` 등)을
  '핵심 외'로 명시 배제한 판정은 이 모듈로 뒤집히지 않는다 — 여기서 고정하는 것은 *호출 어휘*이지
  *저장 좌석*이 아니다. 좌석 축의 정본은 여전히 `canonical_entity_model_v1.md` 하나다.
- **서빙 코드 배선을 하지 않는다.** 어떤 API·엔진도 아직 이 상수를 읽지 않는다. 배선 지점은
  후속 태스크(`EOS-10`·`EOS-12`·`EOS-13`·`EOS-14`)가 소유하며, 그 사실을 문서 §집행 별항이
  명시한다. "이 계약이 서빙에서 지켜진다"고 말할 수 있는 상태가 **아니다**.
- **적재 경로의 순환 차단을 소유하지 않는다.** 실적재 방어선은 기존 2지점
  (`l1/atom_graph/populate.py`·`data_pipeline/atom_graph/validate.py`)이며, 여기 있는
  `find_prerequisite_cycle`은 계약층 검사용 primitive다. 셋의 통합 여부는 `EOS-101` 소관이다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

# ── 동결 입력 경로의 단일 진실 원천 ────────────────────────────────────────────
# `tests/backend/schema/test_learning_loop_contract.py`가 이 경로를 파싱해 상수와 대조한다.
# 테스트 쪽 `FROZEN_INPUT_PATHS`가 CI 경로 필터 편입까지 기계로 강제한다(OPS-62 가드).
CONTRACT_DOC_PATH = "docs/architecture/learning_loop_contract_v1.md"
CANONICAL_ENTITY_DOC_PATH = "docs/architecture/canonical_entity_model_v1.md"


class LoopObject(StrEnum):
    """계획서 300 §1 EOS Kernel의 14객체 — 이 목록이 루프 어휘의 **전부**다.

    새 객체를 여기 추가하는 것은 계약 변경이며, 정본 문서 §2 표를 함께 고치지 않으면
    검사 ⑧이 RED를 낸다. "일단 넣어 두기"를 비싸게 만드는 것이 이 enum의 목적이다.
    """

    LEARNER = "Learner"
    LEARNER_STATE = "LearnerState"
    CURRICULUM = "Curriculum"
    OBJECTIVE = "Objective"
    CONCEPT = "Concept"
    SKILL = "Skill"
    CONTENT = "Content"
    PROBLEM = "Problem"
    ATTEMPT = "Attempt"
    ASSESSMENT_EVIDENCE = "AssessmentEvidence"
    MISCONCEPTION = "Misconception"
    MASTERY = "Mastery"
    RECOMMENDATION = "Recommendation"
    LEARNING_SESSION = "LearningSession"


class LoopEdge(StrEnum):
    """허용된 관계 타입 — CLAUDE.md "관계 타입 폭발 금지"의 계약층 집행.

    `similar_to`·`related_to`는 **의도적으로 없다**(traversal 사용 금지 원칙). 여기 없는
    엣지 이름으로 관계를 선언하면 타입 단계에서 막힌다.
    """

    HAS = "has"
    MASTERY = "mastery"
    MISCONCEPTION = "misconception"
    CURRENT_GOAL = "current_goal"
    REQUIRES = "requires"
    PREREQUISITE = "prerequisite"
    TAUGHT_BY = "taught_by"
    ASSESSED_BY = "assessed_by"
    ASSOCIATED_WITH = "associated_with"
    ASSESSES = "assesses"
    TRIGGERS = "triggers"
    MADE_BY = "made_by"
    ON = "on"
    PRODUCES = "produces"
    UPDATES = "updates"
    FEEDS = "feeds"


@dataclass(frozen=True, slots=True)
class LoopRelation:
    """단방향 canonical edge 하나 — (source) --edge--> (target).

    양방향 저장을 하지 않는 이유는 구축 플레이북 하드 게이트("단방향 canonical edge로
    저장했는가")다. 역방향이 필요하면 조회 시점에 뒤집는다.
    """

    source: LoopObject
    edge: LoopEdge
    target: LoopObject

    def __str__(self) -> str:  # pragma: no cover - 진단 출력 편의
        return f"{self.source} --{self.edge}--> {self.target}"


#: 계획서 300 §1이 고정한 관계 전량. **이 튜플 밖의 관계는 계약 위반이다.**
#: 순서는 계획서 §1의 서술 순서를 그대로 따른다(대조 가능성 유지).
LOOP_RELATIONS: tuple[LoopRelation, ...] = (
    # Learner has→ LearnerState
    LoopRelation(LoopObject.LEARNER, LoopEdge.HAS, LoopObject.LEARNER_STATE),
    # LearnerState: mastery→Concept, mastery→Skill, misconception→Misconception,
    #               current_goal→Objective
    LoopRelation(LoopObject.LEARNER_STATE, LoopEdge.MASTERY, LoopObject.CONCEPT),
    LoopRelation(LoopObject.LEARNER_STATE, LoopEdge.MASTERY, LoopObject.SKILL),
    LoopRelation(LoopObject.LEARNER_STATE, LoopEdge.MISCONCEPTION, LoopObject.MISCONCEPTION),
    LoopRelation(LoopObject.LEARNER_STATE, LoopEdge.CURRENT_GOAL, LoopObject.OBJECTIVE),
    # Objective requires→ Concept
    LoopRelation(LoopObject.OBJECTIVE, LoopEdge.REQUIRES, LoopObject.CONCEPT),
    # Concept: prerequisite→Concept, taught_by→Content, assessed_by→Problem,
    #          associated_with→Misconception
    LoopRelation(LoopObject.CONCEPT, LoopEdge.PREREQUISITE, LoopObject.CONCEPT),
    LoopRelation(LoopObject.CONCEPT, LoopEdge.TAUGHT_BY, LoopObject.CONTENT),
    LoopRelation(LoopObject.CONCEPT, LoopEdge.ASSESSED_BY, LoopObject.PROBLEM),
    LoopRelation(LoopObject.CONCEPT, LoopEdge.ASSOCIATED_WITH, LoopObject.MISCONCEPTION),
    # Problem: assesses→Concept, assesses→Skill, triggers→Misconception
    LoopRelation(LoopObject.PROBLEM, LoopEdge.ASSESSES, LoopObject.CONCEPT),
    LoopRelation(LoopObject.PROBLEM, LoopEdge.ASSESSES, LoopObject.SKILL),
    LoopRelation(LoopObject.PROBLEM, LoopEdge.TRIGGERS, LoopObject.MISCONCEPTION),
    # Attempt: made_by→Learner, on→Problem, produces→AssessmentEvidence
    LoopRelation(LoopObject.ATTEMPT, LoopEdge.MADE_BY, LoopObject.LEARNER),
    LoopRelation(LoopObject.ATTEMPT, LoopEdge.ON, LoopObject.PROBLEM),
    LoopRelation(LoopObject.ATTEMPT, LoopEdge.PRODUCES, LoopObject.ASSESSMENT_EVIDENCE),
    # AssessmentEvidence updates→ LearnerState
    LoopRelation(LoopObject.ASSESSMENT_EVIDENCE, LoopEdge.UPDATES, LoopObject.LEARNER_STATE),
    # LearnerState feeds→ Recommendation
    LoopRelation(LoopObject.LEARNER_STATE, LoopEdge.FEEDS, LoopObject.RECOMMENDATION),
)

#: DAG 불변식이 걸린 엣지 — 순환이 생기면 학습 경로가 구성 불가가 된다.
#: CLAUDE.md 7대 붕괴 연쇄 3단계("순환참조") 방어: `prerequisite`만 DAG를 강제한다.
DAG_CONSTRAINED_EDGES: frozenset[LoopEdge] = frozenset({LoopEdge.PREREQUISITE})

#: `prerequisite` 순환을 **실적재 경로에서** 실제로 막는 지점(정본화 ≠ 집행).
#: 이 모듈이 아니라 아래 두 곳이 집행자다. 경로가 사라지면 검사 ⑦-b가 RED를 낸다.
DAG_ENFORCEMENT_POINTS: tuple[str, ...] = (
    "src/backend/whymath_backend/l1/atom_graph/populate.py",
    "src/data-pipeline/data_pipeline/atom_graph/validate.py",
)


class SeatStatus(StrEnum):
    """루프 객체가 `ARCH-37` 19종 좌석 정본에 어떻게 귀속되는가."""

    #: 같은 이름의 핵심 엔티티가 있고 좌석 테이블도 있다.
    SEATED = "seated"
    #: 좌석은 있으나 정본의 엔티티 이름이 다르다(계획서가 약칭을 썼다).
    SEATED_ALIAS = "seated_alias"
    #: 독립 좌석이 없고 다른 핵심 엔티티의 좌석에 흡수돼 있다.
    ABSORBED = "absorbed"
    #: 19종 어디에도 대응이 없다. **여기에 좌석을 만드는 것은 이 태스크 범위 밖이다.**
    NO_SEAT = "no_seat"


@dataclass(frozen=True, slots=True)
class SeatBinding:
    """루프 객체 1건 ↔ `ARCH-37` 핵심 엔티티 귀속.

    `canonical_entity`는 `canonical_entity_model_v1.md` §2-A 표의 엔티티 이름이어야 한다
    (검사 ⑤가 문서를 파싱해 대조 — 오탈자·유령 엔티티 차단). `NO_SEAT`만 None이다.
    """

    loop_object: LoopObject
    canonical_entity: str | None
    status: SeatStatus
    #: 같은 이름인데 **뜻이 다른** 경우 True. 이름 축(`SEATED_ALIAS`)과 독립된 축이다.
    #: 2026-09-16 Kiki 판정(A안)으로 현재 **전건 False**다 — 계획서 쪽을
    #: `AssessmentEvidence`로 개명해 유일한 충돌을 해소했다. 필드는 남겨 둔다:
    #: 새 충돌이 생기면 여기 적어야 하고, 검사가 "0건"을 강제하므로 조용히 늘 수 없다.
    semantic_collision: bool
    note: str


#: 14객체 전건의 귀속. 이 튜플이 곧 정본 문서 §2 매핑표이며 검사 ⑧이 1:1을 강제한다.
CANONICAL_SEAT_BINDINGS: tuple[SeatBinding, ...] = (
    SeatBinding(
        LoopObject.LEARNER,
        "Learner",
        SeatStatus.SEATED,
        False,
        "좌석 user_profile. 동명 1:1.",
    ),
    SeatBinding(
        LoopObject.LEARNER_STATE,
        "LearnerState",
        SeatStatus.SEATED,
        False,
        "좌석 user_state_snapshot. 동명이나 writer 0 — 단일 조회 표면 신설은 EOS-10 소관.",
    ),
    SeatBinding(
        LoopObject.CURRICULUM,
        "Curriculum",
        SeatStatus.SEATED,
        False,
        "좌석 curriculum_framework·curriculum_version. 동명 1:1.",
    ),
    SeatBinding(
        LoopObject.OBJECTIVE,
        "LearningObjective",
        SeatStatus.SEATED_ALIAS,
        False,
        "계획서 약칭 Objective ↔ 정본 LearningObjective. 저장소 정본 이름을 유지한다"
        "(개명하면 좌석·ORM·문서 3곳이 동시에 흔들린다).",
    ),
    SeatBinding(
        LoopObject.CONCEPT,
        "Concept",
        SeatStatus.SEATED,
        False,
        "좌석 concept·concept_node·atom_node·concept_version(혼재 3좌석은 ARCH-37 §5가 소유).",
    ),
    SeatBinding(
        LoopObject.SKILL,
        "Skill",
        SeatStatus.SEATED,
        False,
        "좌석 skill_node. 동명 1:1.",
    ),
    SeatBinding(
        LoopObject.CONTENT,
        "Content",
        SeatStatus.SEATED,
        False,
        "좌석 concept_content·pedagogy_content_slot. 동명 1:1.",
    ),
    SeatBinding(
        LoopObject.PROBLEM,
        "Problem",
        SeatStatus.SEATED,
        False,
        "좌석 problem·problem_step. 동명 1:1.",
    ),
    SeatBinding(
        LoopObject.ATTEMPT,
        "LearningEvent",
        SeatStatus.ABSORBED,
        False,
        "독립 엔티티가 아니라 LearningEvent 좌석에 흡수(problem_attempt·attempt_event·"
        "answer_submission). 루프 어휘에서는 1급 객체이나 저장 축에서는 아니다.",
    ),
    SeatBinding(
        LoopObject.ASSESSMENT_EVIDENCE,
        "LearningEvent",
        SeatStatus.ABSORBED,
        False,
        "독립 좌석이 없고 LearningEvent 좌석에 혼재 흡수(attempt_event의 skill_ids · "
        "answer_submission의 error_analysis · evidence_event). EOS-79 4층 경계가 이미 "
        "'이름이 층을 정하지 않는다 — assessment 테이블은 Assessment 층이 아니다'를 정본화했고, "
        "그 문서의 Assessment 층 정의('어느 Skill·오개념의 어떤 증거인가')가 이 객체다. "
        "ARCH-37 #15의 Assessment(진단 세션)는 이 객체가 아니며 루프 어휘 밖이다(§3-2).",
    ),
    SeatBinding(
        LoopObject.MISCONCEPTION,
        "Misconception",
        SeatStatus.SEATED,
        False,
        "좌석 misconception_catalog. 동명 1:1. 학생 개인의 오개념 '추정'은 별개 축이다.",
    ),
    SeatBinding(
        LoopObject.MASTERY,
        "MasteryState",
        SeatStatus.SEATED_ALIAS,
        False,
        "계획서 약칭 Mastery ↔ 정본 MasteryState. 좌석 concept_mastery_history·"
        "skill_mastery_history·ability_snapshot.",
    ),
    SeatBinding(
        LoopObject.RECOMMENDATION,
        None,
        SeatStatus.NO_SEAT,
        False,
        "ARCH-37 19종에 대응 엔티티가 없다. 20번째 엔티티를 만들면 ARCH-37 검사 ②가 RED다 — "
        "좌석 신설은 이 태스크가 하지 않는다. 호출 계약은 EOS-14 소관.",
    ),
    SeatBinding(
        LoopObject.LEARNING_SESSION,
        "LearningEvent",
        SeatStatus.ABSORBED,
        False,
        "LearningEvent 좌석의 learning_session 테이블에 흡수. 좌석은 있으나 writer 0이라 "
        "KPI 분모가 비어 있다(별건).",
    ),
)

#: 계획서 §1 관계도 어디에도 등장하지 않는 루프 객체 — 목록에는 있으나 엣지가 0건이다.
#: 날조로 관계를 만들어 채우지 않고 **고립 사실 그대로** 적는다. 검사 ⑥이 이 집합과
#: `LOOP_RELATIONS`에서 실제로 계산한 고립 집합이 같은지 대조한다.
LOOP_OBJECTS_WITHOUT_RELATIONS: frozenset[LoopObject] = frozenset(
    {LoopObject.CURRICULUM, LoopObject.MASTERY, LoopObject.LEARNING_SESSION}
)


def relations_from(source: LoopObject) -> tuple[LoopRelation, ...]:
    """한 객체에서 나가는 관계 전량."""
    return tuple(r for r in LOOP_RELATIONS if r.source == source)


def is_declared_relation(source: LoopObject, edge: LoopEdge, target: LoopObject) -> bool:
    """이 삼중항이 계약에 선언돼 있는가 — 소비자가 관계를 쓰기 전에 묻는 자리."""
    return LoopRelation(source, edge, target) in LOOP_RELATIONS


def find_prerequisite_cycle(edges: Iterable[tuple[str, str]]) -> list[str] | None:
    """`prerequisite` 엣지 집합에서 순환을 찾는다 — 없으면 None.

    `edges`는 (선행, 후행) 쌍이다. 반환값은 순환 경로이며 **닫힘 노드를 반복 포함**한다
    (예: ``["a", "b", "a"]``) — 사람이 읽고 어디를 끊을지 바로 알 수 있게 한다.

    재귀가 아니라 **명시 스택**을 쓴다. 원자 백본은 2,683노드·2,210엣지 규모라 깊은 체인에서
    재귀는 `RecursionError`로 죽는다 — 기존 집행 2지점이 같은 이유로 비재귀다. 세 구현이 같은
    판정을 내는지는 검사 ⑦-c가 대조한다.

    계약층 검사용 primitive다. 실적재 경로의 집행자는 `DAG_ENFORCEMENT_POINTS`의 2지점이며,
    이 함수가 그것들을 대체하지 않는다(정본화 ≠ 집행).
    """
    adjacency: dict[str, list[str]] = {}
    for prerequisite, dependent in edges:
        adjacency.setdefault(prerequisite, []).append(dependent)

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {}

    for start in list(adjacency):
        if color.get(start, white) != white:
            continue
        # stack 원소 = (노드, 다음에 볼 자식 인덱스). path는 현재 회색 경로.
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        color[start] = gray
        while stack:
            node, child_idx = stack[-1]
            children = adjacency.get(node, [])
            if child_idx < len(children):
                stack[-1] = (node, child_idx + 1)
                nxt = children[child_idx]
                state = color.get(nxt, white)
                if state == gray:  # back-edge → 순환
                    return [*path[path.index(nxt) :], nxt]
                if state == white:
                    color[nxt] = gray
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = black
                stack.pop()
                path.pop()
    return None


def reachable_from(start: str, edges: Iterable[tuple[str, str]]) -> frozenset[str]:
    """`start`에서 `prerequisite` 방향으로 도달 가능한 노드 집합(자기 자신 제외).

    Reachability Check의 본체 — 구축 플레이북 하드 게이트("`prerequisite`이면 DAG를 깨지
    않는가? Reachability Check 통과")가 요구하는 검사다. ``start in reachable_from(start, ...)``
    이면 그 노드가 자기 자신의 선행이라는 뜻이므로 순환이다.

    visited set을 반드시 쓴다 — 순환이 있는 입력에서도 **멈춘다**(traversal guard 원칙).
    """
    adjacency: dict[str, list[str]] = {}
    for prerequisite, dependent in edges:
        adjacency.setdefault(prerequisite, []).append(dependent)
        adjacency.setdefault(dependent, [])

    visited: set[str] = set()
    stack: list[str] = list(adjacency.get(start, ()))
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(adjacency.get(node, ()))
    return frozenset(visited)
