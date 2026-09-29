"""CUR-09 관측 동결 — EOS 『2_단원 구조 관리』 가설 3종의 *현행 부재*를 실측으로 고정.

배경: 외부 EOS 설계안 『2_단원 구조 관리』(116항) 검토 수용(`curriculum_module_gap_review_r2.md`
§후속 2026-08-23)은 제안서의 Curriculum→Subject→Course→UnitNode 1급 트리를 도입하지 않고,
충돌하지 않는 가설 3종 — ①Sequence/Prerequisite 분리 ②Unit-Concept 역할 enum
③coverage_weight — 만 *관측*으로 선행한다고 결정했다. 이 테스트는 그 관측의 기계 동결이다:
5측정(순서 컬럼·계층 표현·엣지 관계·역할 enum·배분 가중치)의 "현재 없음"을 ORM 메타데이터·
DSL 코퍼스·원자 그래프 코퍼스를 *실제로 스캔*해 단언한다.

red가 나면: 가설이 현실이 된 것이다(누군가 순서 컬럼·역할 필드·가중치를 추가했다).
그때 할 일은 이 테스트를 조용히 고치는 것이 아니라, 가설 명세 문서
`docs/architecture/curriculum_module_gap_review_unit_structure_hypotheses.md`의 해당 가설
절(채택 트리거·승격 형태)을 함께 갱신하고 스키마 태스크로 승격하는 것이다 — 각 단언
메시지가 그 문서를 가리킨다.

측정 5종(가설 명세 문서 §0과 1:1):
  M1  순서(ordering)-족 컬럼: 전 테이블에서 제안 이름(order_index 등) 0개 · ordering-족
      전수는 런타임/콘텐츠 내부 순서 8개뿐(allowlist 등식) · 커리큘럼 구조 테이블 위 0개.
  M2  계층(parent)-족 컬럼: 전수 9개 등식 동결 — 커리큘럼 축은 원자 백본 parent_code
      단일 원천(+ 그 UUID 프로젝션·교과서 Overlay 트리)뿐 · 1급 트리 테이블 부재.
  M3  Unit 간 의미 관계: 코퍼스 실적재 엣지의 관계 타입 = {prerequisite} 단일 ·
      단원급(단원/소단원) 노드 사이 엣지 0건 · EdgeType 어휘 6종 동결.
  M4  unit_concept 역할: 역할 enum 미정의(제안 6값 집합과 일치하는 enum 0개) ·
      concept_nodes는 스칼라 텍스트 배열(role 동반 불가) · DSL에 role 키 0개.
  M5  coverage_weight: 컬럼명 coverage_weight 전 테이블 0개 · weight-족 전수는 노드/헤더
      속성 3개뿐(N:M 링크 배분 가중치 아님) · DSL에 coverage_weight 키 0개 ·
      기반 사실(성취기준→원자 1:N)은 이미 실재.

변별력(④): 관측기 `_observe_unit_yaml`은 파일럿 DSL 정본에서 제안 필드 0을 재현하고,
가설 필드를 *서로 다른 깊이에* 임시 주입한 tmp 사본에서는 수치가 실제로 변한다(정본 무수정).
추가로 `UnitDSL`(extra="forbid")이 주입 사본을 *거부*함을 기계 증명한다 — 가설 필드는
현행 계약에 조용히 들어올 수 없고, 채택은 반드시 명시적 스키마 태스크를 거친다.

기존 자산과의 관계: `test_edge_relation_governance.py`는 *적재기*가 PREREQUISITE 외를
거부함을 동결하고, 본 테스트 M3는 *코퍼스 실측*(실제 적재 원장)을 동결한다 — 상보적.

hermetic: DB 불요(ORM 메타데이터 introspection + 코퍼스 파일 스캔만).
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
import yaml
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import ARRAY

import whymath_backend.db.models as models_pkg
from whymath_backend.db.base import Base
from whymath_backend.schema import enums as enums_module
from whymath_backend.schema.enums import ConceptRole, EdgeType
from whymath_backend.schema.unit_dsl import ObjectiveDSL, UnitDSL

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UNITS_DIR = _REPO_ROOT / "data" / "corpus" / "units_v1"
_GRAPH_JSON = _REPO_ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
# 가설 명세 문서 — red 시 갱신 대상(단언 메시지가 가리키는 곳).
_SPEC_DOC_REL = "docs/architecture/curriculum_module_gap_review_unit_structure_hypotheses.md"
_SPEC_HINT = f"가설이 현실이 됐다 — {_SPEC_DOC_REL} 를 갱신하고 스키마 태스크로 승격하라."


def _load_all_models() -> None:
    """모든 모델 모듈을 적재해 `Base.metadata`를 완성한다(부분 적재면 측정이 새는다).

    `test_jsonb_none_as_null_governance.py` 선례 — `__init__` 수록 여부와 무관하게 pkgutil로
    전 모듈을 쓸어 담아, 새 모델 파일이 생겨도 측정 대상에 자동 포함되게 한다.
    """
    for module in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"whymath_backend.db.models.{module.name}")


def _all_columns() -> list[tuple[str, str, sa.types.TypeEngine[Any]]]:
    """(테이블, 컬럼, 타입) 전수 — 선언 문자열이 아니라 *실제 ORM 메타데이터*를 스캔한다."""
    _load_all_models()
    return [
        (table.name, column.name, column.type)
        for table in Base.metadata.sorted_tables
        for column in table.columns
    ]


# ──────────────────────────────────────────────────────────────────────────
# 측정 상수 — 실측 2026-08-30 기준(가설 명세 문서 §0 표와 1:1)
# ──────────────────────────────────────────────────────────────────────────

# 제안서가 명명하는 순서 컬럼 이름(정확 일치 금지 목록) — 하나라도 생기면 가설 1이 현실.
_PROPOSED_ORDERING_NAMES = frozenset(
    {"order_index", "sequence_order", "sort_order", "display_order", "unit_order"}
)

# ordering-족 광역 패턴 — 이름에 순서 의미 토큰이 들어간 컬럼을 전부 잡는다.
_ORDERING_RE = re.compile(r"(seq|order|position|rank|sort)", re.IGNORECASE)

# 실측 allowlist: 런타임 이벤트·콘텐츠 *내부* 순서 — 커리큘럼 형제(단원 간) 순서가 아니다.
# 의미를 잃지 않도록 한 건씩 주석으로 스코프를 못박는다(새 항목 추가 시 같은 규율).
_RUNTIME_ORDERING_ALLOWLIST = frozenset(
    {
        ("answer_submission", "sequence_no"),  # attempt 내 제출 순번(런타임 이벤트)
        ("device_credential", "seq"),  # 기기 자격 증명 시퀀스(인증 인프라)
        ("dialogue_turn", "turn_order"),  # 대화 턴 순서(런타임 세션)
        ("problem", "session_position"),  # 세션 내 권장 출제 순서(문제 배치·세션 스코프)
        ("problem_step", "step_order"),  # 문제 내부 풀이 step 순서(콘텐츠 내부 구조)
        # S4-11(2026-09-29): 힌트가 *어느 풀이 단계의 것인지* 가리키는 참조 키 — 위
        # `problem_step.step_order`와 같은 축의 사본(yaml `SolutionStepRef = 경로 ID + 단계 order`).
        # 새 순서 축이 아니다: 값의 출처가 풀이 경로의 단계 order이고, 커리큘럼 형제(단원 간)
        # 순서와 무관하며, 커리큘럼 구조 테이블이 아니다. 판정 근거는 명세 문서 §0 M1 각주.
        ("hints", "step_order"),
        ("solution_paths", "concept_sequence"),  # 풀이 경로 개념 순서열(풀이 스코프)
        ("student_solution_step", "sequence_no"),  # 학생 풀이 step 순번(런타임 이벤트)
    }
)

# 커리큘럼 구조 테이블(백본·Overlay·명세·링크) — 이 위의 ordering-족 0개가 측정 1의 본체다.
_CURRICULUM_STRUCTURE_TABLES = frozenset(
    {
        "unit_spec",
        "learning_objective",
        "pedagogy_pack",
        "pedagogy_content_slot",
        "curriculum_entry",
        "curriculum_framework",
        "curriculum_version",
        "achievement_standard",
        "achievement_level_unit",
        "concept_standard_link",
        "atom_node",
        "concept",
        "concept_edge",
        "concept_node",
        "textbook_mapping",
        "textbook_unit",
    }
)

# parent-족 컬럼 전수(실측 9개) — 의미 분류 주석과 함께 등식 동결.
_PARENT_FAMILY_ALLOWLIST = frozenset(
    {
        ("atom_node", "parent_code"),  # 커리큘럼: 원자 백본 트리 원문(단일 원천의 프로젝션)
        ("concept", "parent_concept_id"),  # 커리큘럼: 같은 parent_code의 UUID 해소 프로젝션(2-pass)
        ("textbook_unit", "parent_unit_id"),  # 커리큘럼: 교과서 목차 Overlay 트리(외부 사실)
        ("achievement_standard", "parent_codes"),  # 비트리: 선수 성취기준 코드 *배열*(계층 아님)
        ("content_provenance", "parent_problem_id"),  # 비커리큘럼: 변형 출처 계보(provenance)
        ("problem_relation", "parent_problem_id"),  # 비커리큘럼: 문제 변형 관계
        ("solution_nodes", "parent_id"),  # 비커리큘럼: WH-S 풀이 탐색 트리
        ("user_profile", "parent_consent_at"),  # 비커리큘럼: 학부모(보호자) 동의 시각
        ("user_profile", "parent_email_hash"),  # 비커리큘럼: 학부모(보호자) 이메일 해시
    }
)

# 제안서의 1급 트리 구성 요소 — 이 이름의 테이블이 생기면 미채택 결정이 뒤집힌 것이다.
_PROPOSED_FIRST_CLASS_TABLES = frozenset(
    {
        "course",
        "unit_node",
        "subject",
        "curriculum_node",
        "unit_edge",
        "unit_alignment",
        "unit_concept",
    }
)

# weight-족 컬럼 전수(실측 3개) — 전부 노드/헤더 *속성*이고 N:M 링크 배분 가중치가 아니다.
_WEIGHT_RE = re.compile(r"(weight|coverage)", re.IGNORECASE)
_WEIGHT_FAMILY_ALLOWLIST = frozenset(
    {
        ("concept", "weight_in_curriculum"),  # 개념 노드 단일축 중요도(§4.2 — 링크 배분 아님)
        ("evidence_links", "weight"),  # L2 증거 링크 가중(학습자 모델 — 커리큘럼 아님)
        ("problem", "exam_authority_weight"),  # 문제 헤더 기출 권위 가중(콘텐츠 속성)
    }
)

# EdgeType 어휘 동결(6종) — 순서/역할용 신규 엣지 타입이 생기면 red(관계 타입 5~8개 제한).
_EDGE_TYPE_VOCABULARY = frozenset(
    {"PREREQUISITE", "COMPOSED_OF", "ANALOGOUS_TO", "EXTENDS", "CONTRASTS", "TRIGGERS_DISTRACTOR"}
)

# 제안 역할 enum 6값 — 이 값 집합과 일치하는 enum이 생기면 가설 2가 현실.
_PROPOSED_ROLE_VALUES = frozenset(
    {"CORE", "SUPPORTING", "PREREQUISITE", "EXTENSION", "ENRICHMENT", "REVIEW"}
)

# 관측기(④)가 세는 제안 필드 키 — DSL 트리 어느 깊이에 나타나도 잡는다.
_PROPOSED_FIELD_KEYS = frozenset({"order_index", "sequence_order", "role", "coverage_weight"})


# ──────────────────────────────────────────────────────────────────────────
# 관측기 본체 (④ 변별력 — 파일럿 DSL 스캔)
# ──────────────────────────────────────────────────────────────────────────


def _count_proposed_keys(node: object) -> Counter[str]:
    """YAML 트리를 *재귀* 순회하며 제안 필드 키 등장 횟수를 센다(깊이 무관 검출).

    재귀가 관측기의 변별력 그 자체다 — 목표(objectives) 리스트 안, 개념 원소 dict 안처럼
    중첩 위치에 가설 필드가 생겨도 잡아야 "필드가 생기면 관측이 감지한다"가 성립한다.
    (뮤테이션 검증: 리스트 하강을 제거하면 중첩 주입 사본에서 검출 0이 되어 red.)
    """
    counter: Counter[str] = Counter()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _PROPOSED_FIELD_KEYS:
                counter[key] += 1
            counter.update(_count_proposed_keys(value))
    elif isinstance(node, list):
        for item in node:
            counter.update(_count_proposed_keys(item))
    return counter


def _observe_unit_yaml(text: str) -> dict[str, int]:
    """소단원 DSL 원문 → 제안 필드 관측 수치(키별 등장 횟수·부재=0)."""
    data = yaml.safe_load(text)
    counts = _count_proposed_keys(data)
    return {key: counts.get(key, 0) for key in sorted(_PROPOSED_FIELD_KEYS)}


def _unit_yaml_paths() -> list[Path]:
    """정본 소단원 DSL 전수(glob) — 파일이 늘어나도 자동 포함."""
    return sorted(_UNITS_DIR.glob("*.unit.yaml"))


# ──────────────────────────────────────────────────────────────────────────
# M1 — 순서(ordering) 컬럼: 제안 이름 0개 · 광역 전수 allowlist 등식 · 구조 테이블 위 0개
# ──────────────────────────────────────────────────────────────────────────


def test_m1_no_proposed_ordering_column_anywhere() -> None:
    """제안서가 명명하는 순서 컬럼(order_index 등)은 전 테이블에 정확히 0개다."""
    hits = [
        (table, column)
        for table, column, _ in _all_columns()
        if column.lower() in _PROPOSED_ORDERING_NAMES
    ]
    assert hits == [], f"제안 순서 컬럼이 생겼다: {hits}. {_SPEC_HINT}"


def test_m1_ordering_family_equals_runtime_allowlist() -> None:
    """ordering-족 컬럼 전수는 런타임/콘텐츠 내부 순서 8개뿐이다(등식 — 신규는 red).

    새 ordering-족 컬럼이 *어디에든* 생기면 이 등식이 깨진다. 커리큘럼 순서 컬럼이면 가설 1
    승격 절차를 밟고, 런타임 순번이면 allowlist에 스코프 주석과 함께 추가하라(명세 문서 §0).
    """
    found = frozenset(
        (table, column) for table, column, _ in _all_columns() if _ORDERING_RE.search(column)
    )
    assert found == _RUNTIME_ORDERING_ALLOWLIST, (
        f"ordering-족 컬럼 전수가 변했다. 추가={sorted(found - _RUNTIME_ORDERING_ALLOWLIST)} "
        f"제거={sorted(_RUNTIME_ORDERING_ALLOWLIST - found)}. {_SPEC_HINT}"
    )


def test_m1_curriculum_structure_tables_have_no_ordering_column() -> None:
    """커리큘럼 구조 테이블(백본·Overlay·명세·링크) 위에는 ordering-족 컬럼이 0개다.

    이것이 Sequence/Prerequisite 분리 가설의 본체 측정 — 공식 진도 '순서' 축은 오늘 어느
    구조 테이블에도 없다(기계 정렬 가능한 순서 좌석 부재).
    """
    columns = _all_columns()
    tables_in_metadata = {table for table, _, _ in columns}
    # 오타 방어: 측정 대상 테이블이 실제 존재하는지 먼저 단언한다(빈 측정 = 위장 통과 방지).
    missing = _CURRICULUM_STRUCTURE_TABLES - tables_in_metadata
    assert missing == set(), f"측정 대상 테이블이 메타데이터에 없다(이름 변경?): {sorted(missing)}"
    hits = [
        (table, column)
        for table, column, _ in columns
        if table in _CURRICULUM_STRUCTURE_TABLES and _ORDERING_RE.search(column)
    ]
    assert hits == [], f"커리큘럼 구조 테이블에 순서 컬럼이 생겼다: {hits}. {_SPEC_HINT}"


# ──────────────────────────────────────────────────────────────────────────
# M2 — 계층 표현: parent-족 전수 등식 · 1급 트리 테이블 부재
# ──────────────────────────────────────────────────────────────────────────


def test_m2_parent_family_equals_allowlist() -> None:
    """parent-족 컬럼 전수는 실측 9개와 등식이다 — 새 계층 축이 생기면 red.

    커리큘럼 계층의 단일 원천은 원자 백본 코퍼스의 parent_code 한 축이고, PG에는 그 두
    프로젝션(atom_node.parent_code 원문·concept.parent_concept_id UUID 해소)과 교과서
    Overlay 트리(textbook_unit.parent_unit_id — 외부 사실의 별도 축)만 있다. 나머지는
    비커리큘럼(풀이 트리·변형 계보·보호자 필드)이다 — allowlist 주석이 의미를 못박는다.
    """
    found = frozenset(
        (table, column)
        for table, column, _ in _all_columns()
        if column.lower().startswith("parent")
    )
    assert found == _PARENT_FAMILY_ALLOWLIST, (
        f"parent-족 컬럼 전수가 변했다. 추가={sorted(found - _PARENT_FAMILY_ALLOWLIST)} "
        f"제거={sorted(_PARENT_FAMILY_ALLOWLIST - found)}. {_SPEC_HINT}"
    )


def test_m2_no_first_class_tree_table() -> None:
    """제안서의 1급 트리 테이블(course·unit_node·unit_concept 등)은 존재하지 않는다.

    UnitNode 1급 Aggregate 미채택(범위 밖 ⑤)의 기계 동결 — 이 이름의 테이블이 생기면
    미채택 결정 자체가 뒤집힌 것이므로 명세 문서 §5와 r2 §후속을 함께 갱신해야 한다.
    """
    _load_all_models()
    present = _PROPOSED_FIRST_CLASS_TABLES & set(Base.metadata.tables)
    assert present == set(), f"1급 트리 테이블이 생겼다: {sorted(present)}. {_SPEC_HINT}"


# ──────────────────────────────────────────────────────────────────────────
# M3 — Unit 간 의미 관계: 코퍼스 실적재 = prerequisite 단일 · 단원급 간 0건 · 어휘 6종
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def atom_graph() -> dict[str, Any]:
    """원자 백본 코퍼스(graph.json) — 실적재 원장(2,683 노드·2,210 엣지 규모)."""
    loaded: dict[str, Any] = json.loads(_GRAPH_JSON.read_text(encoding="utf-8"))
    return loaded


def test_m3_loaded_edge_relations_are_prerequisite_only(atom_graph: dict[str, Any]) -> None:
    """코퍼스 실적재 엣지의 관계 타입은 {prerequisite} 단일이다(전수 스캔).

    `test_edge_relation_governance.py`가 *적재기*의 거부를 동결한다면, 여기는 *코퍼스 원장*
    자체를 동결한다 — SEQUENCE류·역할류 관계가 원장에 유입되면 red.
    """
    edges = atom_graph["edges"]
    assert len(edges) > 0, "엣지 0건 — 코퍼스가 비었다(측정 불능을 통과로 위장하지 않는다)"
    relations = {edge["relation"] for edge in edges}
    assert relations == {
        "prerequisite"
    }, f"prerequisite 외 관계가 적재됐다: {sorted(relations - {'prerequisite'})}. {_SPEC_HINT}"


def test_m3_no_unit_level_to_unit_level_edge(atom_graph: dict[str, Any]) -> None:
    """단원급(단원/소단원) 노드 *사이*의 의미 관계 엣지는 0건이다.

    단원 간 순서/의존을 엣지로 표현하는 축이 오늘 원장에 없다는 실측 — 가설 1(순서)을
    PREREQUISITE 엣지로 흉내내는 붕괴 경로(명세 문서 §1 붕괴 지점 ①)의 유입 감시이기도 하다.
    """
    level_by_code = {c["code"]: c.get("level") for c in atom_graph["concepts"]}
    unit_levels = {"단원", "소단원"}
    unit_to_unit = [
        (e["from_code"], e["to_code"])
        for e in atom_graph["edges"]
        if level_by_code.get(e["from_code"]) in unit_levels
        and level_by_code.get(e["to_code"]) in unit_levels
    ]
    assert unit_to_unit == [], f"단원급 간 엣지가 생겼다: {unit_to_unit[:5]} …. {_SPEC_HINT}"


def test_m3_edge_type_vocabulary_frozen_at_six() -> None:
    """EdgeType 선언 어휘는 6종 그대로다(관계 타입 5~8개 제한의 상한 감시).

    순서(SEQUENCE_NEXT류)·역할(HAS_CORE류) 엣지 타입 신설은 가설의 *잘못된* 승격 형태다
    (순서는 Overlay 컬럼, 역할은 membership 속성 — 명세 문서 §1·§2 경계). 어휘가 변하면
    red를 내고 명세 문서와 대조하게 한다.
    """
    assert {
        member.value for member in EdgeType
    } == _EDGE_TYPE_VOCABULARY, (
        f"EdgeType 어휘가 변했다: {sorted(member.value for member in EdgeType)}. {_SPEC_HINT}"
    )


# ──────────────────────────────────────────────────────────────────────────
# M4 — unit_concept 역할: enum 미정의 · 스칼라 배열 · DSL role 0
# ──────────────────────────────────────────────────────────────────────────


def test_m4_no_enum_matches_proposed_role_vocabulary() -> None:
    """schema.enums 전수(62종 규모)에 제안 6값 집합과 일치하는 enum이 없다.

    ConceptRole(4종·문제-개념 축)·KnowledgeType(7종·목표 유형 축)은 존재하나 *다른 축*이다
    — 값 집합 대조가 그 구분을 기계화한다. 일치 enum이 생기면 가설 2가 현실.
    """
    import enum as enum_module

    matching = [
        name
        for name in dir(enums_module)
        if isinstance(candidate := getattr(enums_module, name), type)
        and issubclass(candidate, enum_module.Enum)
        and {member.value for member in candidate} == _PROPOSED_ROLE_VALUES
    ]
    assert matching == [], f"제안 역할 enum이 생겼다: {matching}. {_SPEC_HINT}"
    # 이름 축도 함께 — 값이 달라도 UnitConceptRole 이름의 enum이 생기면 같은 신호다.
    assert not hasattr(enums_module, "UnitConceptRole"), f"UnitConceptRole 등장. {_SPEC_HINT}"


def test_m4_adjacent_role_axes_frozen() -> None:
    """인접 축 동결 — ConceptRole은 4종(문제-개념)이고 제안 축(단원-개념)이 아니다.

    가설 2 채택 시 기존 축에 값을 *덧대는* 오염(SUPPORTING 공유 어휘 유혹)을 막는 감시:
    ConceptRole 값 집합이 변하면 red — 별 enum·별 좌석 원칙(명세 문서 §2 분리할 것).
    """
    assert {member.value for member in ConceptRole} == {
        "PRIMARY",
        "SUPPORTING",
        "IMPLICIT",
        "TESTED",
    }, f"ConceptRole 어휘가 변했다. {_SPEC_HINT}"


def test_m4_unit_concept_link_is_scalar_text_array() -> None:
    """unit_spec/learning_objective.concept_nodes는 스칼라 TEXT 배열이다 — role 동반 불가형.

    역할·가중치를 담으려면 원소가 dict(JSONB)거나 연결 테이블이어야 한다. 타입이 ARRAY(Text)
    에서 벗어나면(예: JSONB 전환) 가설 2/3의 승격이 시작된 것이다.
    """
    _load_all_models()
    for table_name in ("unit_spec", "learning_objective"):
        column = Base.metadata.tables[table_name].columns["concept_nodes"]
        assert isinstance(
            column.type, ARRAY
        ), f"{table_name}.concept_nodes 가 배열이 아니게 됐다: {column.type!r}. {_SPEC_HINT}"
        assert isinstance(column.type.item_type, sa.Text), (
            f"{table_name}.concept_nodes 원소가 스칼라 TEXT가 아니다: "
            f"{column.type.item_type!r}. {_SPEC_HINT}"
        )


def test_m4_dsl_surface_has_no_proposed_field() -> None:
    """UnitDSL/ObjectiveDSL 모델 표면에 제안 필드(order_index·role·coverage_weight 등)가 없다."""
    for model in (UnitDSL, ObjectiveDSL):
        overlap = _PROPOSED_FIELD_KEYS & set(model.model_fields)
        assert (
            overlap == set()
        ), f"{model.__name__} 에 제안 필드 등장: {sorted(overlap)}. {_SPEC_HINT}"


# ──────────────────────────────────────────────────────────────────────────
# M5 — coverage_weight: 컬럼 0개 · weight-족 allowlist 등식 · 기반 사실(1:N) 실재
# ──────────────────────────────────────────────────────────────────────────


def test_m5_no_coverage_weight_column_anywhere() -> None:
    """컬럼명 coverage_weight는 전 테이블에 정확히 0개다."""
    hits = [(t, c) for t, c, _ in _all_columns() if c.lower() == "coverage_weight"]
    assert hits == [], f"coverage_weight 컬럼이 생겼다: {hits}. {_SPEC_HINT}"


def test_m5_weight_family_equals_node_attribute_allowlist() -> None:
    """weight-족 컬럼 전수는 노드/헤더 속성 3개뿐이다(등식) — N:M 링크 가중치는 0개.

    특히 링크 테이블(concept_standard_link·problem_concept 등)에 weight-족이 생기면 가설 3
    승격의 시작이다. concept.weight_in_curriculum(노드 단일축 중요도)과의 이중 정본 위험은
    명세 문서 §3 붕괴 지점 ③이 다룬다.
    """
    found = frozenset(
        (table, column) for table, column, _ in _all_columns() if _WEIGHT_RE.search(column)
    )
    assert found == _WEIGHT_FAMILY_ALLOWLIST, (
        f"weight-족 컬럼 전수가 변했다. 추가={sorted(found - _WEIGHT_FAMILY_ALLOWLIST)} "
        f"제거={sorted(_WEIGHT_FAMILY_ALLOWLIST - found)}. {_SPEC_HINT}"
    )


def test_m5_standard_to_atom_multiplicity_substrate_exists(atom_graph: dict[str, Any]) -> None:
    """기반 사실: 성취기준→원자 1:N이 이미 실재한다(실측 510건 규모 — 오늘은 균등 가중 해석).

    가설 3의 존재 이유가 서 있는 땅 — N:M이 실재하는데 배분 가중치 좌석이 없으므로 도달률
    계산은 균등 가중일 수밖에 없다. 이 실재가 사라지면(1:1로 재편) 가설 자체를 재검토한다.
    """
    standard_counts: Counter[str] = Counter()
    for concept in atom_graph["concepts"]:
        for standard_code in concept.get("standard_codes") or []:
            standard_counts[standard_code] += 1
    multi = [code for code, count in standard_counts.items() if count > 1]
    assert len(multi) >= 1, "성취기준→원자 1:N 기반 사실이 사라졌다 — 가설 3 재검토(명세 문서 §3)."


# ──────────────────────────────────────────────────────────────────────────
# ④ 변별력 — 파일럿 DSL 부재 재현 + 가설 필드 주입 사본에서 관측 수치 변화
# ──────────────────────────────────────────────────────────────────────────


def test_observation_canonical_dsl_has_zero_proposed_fields() -> None:
    """정본 소단원 DSL 전수에서 제안 필드 관측 수치는 전부 0이다(부재 재현)."""
    paths = _unit_yaml_paths()
    assert paths, f"소단원 DSL 정본이 없다: {_UNITS_DIR}(측정 불능을 통과로 위장하지 않는다)"
    for path in paths:
        observation = _observe_unit_yaml(path.read_text(encoding="utf-8"))
        assert observation == {
            key: 0 for key in sorted(_PROPOSED_FIELD_KEYS)
        }, f"{path.name} 에 제안 필드가 등장했다: {observation}. {_SPEC_HINT}"


def test_observation_detects_injected_fields_in_tmp_copy(tmp_path: Path) -> None:
    """가설 필드를 *서로 다른 깊이에* 주입한 tmp 사본에서 관측 수치가 실제로 변한다.

    주입 위치를 일부러 흩뿌린다 — 최상위(order_index)·목표 dict(coverage_weight)·목표 리스트
    안 개념 원소 dict(role) — 재귀 하강이 살아 있어야만 셋 다 잡힌다(뮤테이션 감시 지점).
    정본은 만지지 않는다(사본은 tmp_path).
    """
    canonical_path = _UNITS_DIR / "quadratic_maxmin.unit.yaml"
    canonical_text = canonical_path.read_text(encoding="utf-8")
    baseline = _observe_unit_yaml(canonical_text)

    data = yaml.safe_load(canonical_text)
    data["order_index"] = 1  # 최상위 주입(가설 1)
    data["objectives"][0]["coverage_weight"] = 0.5  # 목표 dict 주입(가설 3)
    data["objectives"][1]["concept_nodes"] = [  # 리스트 안 원소 dict 주입(가설 2)
        {"code": code, "role": "CORE"} for code in data["objectives"][1]["concept_nodes"]
    ]
    augmented_path = tmp_path / "quadratic_maxmin.augmented.unit.yaml"
    augmented_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    observation = _observe_unit_yaml(augmented_path.read_text(encoding="utf-8"))
    assert observation != baseline, "주입 사본의 관측이 정본과 같다 — 관측기가 죽어 있다"
    for key in ("order_index", "coverage_weight", "role"):
        assert (
            observation[key] > baseline[key]
        ), f"주입 필드 {key!r} 를 관측이 감지하지 못했다(깊이 하강 결함?): {observation}"


def test_unit_dsl_contract_rejects_proposed_fields(tmp_path: Path) -> None:
    """UnitDSL(extra=forbid)은 가설 필드 주입 사본을 *거부*한다 — 조용한 유입 불가의 기계 증명.

    변별력 확보: 같은 정본이 주입 *전*에는 UnitDSL 검증을 통과함을 먼저 단언한다(거부가
    '원래 깨진 문서'가 아니라 *주입 때문*임을 보인다). 이 거부가 사라지면(extra 완화 또는
    필드 정식 채택) 가설이 계약 표면에 들어온 것이므로 red가 난다.
    """
    canonical_text = (_UNITS_DIR / "quadratic_maxmin.unit.yaml").read_text(encoding="utf-8")
    canonical_data = yaml.safe_load(canonical_text)
    UnitDSL.model_validate(canonical_data)  # 주입 전: 통과(변별력 기준선)

    augmented = yaml.safe_load(canonical_text)
    augmented["order_index"] = 1
    with pytest.raises(ValidationError):
        UnitDSL.model_validate(augmented)

    augmented_objective = yaml.safe_load(canonical_text)
    augmented_objective["objectives"][0]["coverage_weight"] = 0.5
    with pytest.raises(ValidationError):
        UnitDSL.model_validate(augmented_objective)


# ──────────────────────────────────────────────────────────────────────────
# 문서 연동 — red 메시지가 가리키는 명세 문서의 실재
# ──────────────────────────────────────────────────────────────────────────


def test_spec_document_exists_and_covers_five_measurements() -> None:
    """가설 명세 문서가 실재하고 5측정(M1~M5)·가설 3절·범위 밖 절을 담는다(포인터 무결성)."""
    spec_path = _REPO_ROOT / _SPEC_DOC_REL
    assert spec_path.is_file(), f"명세 문서가 없다: {_SPEC_DOC_REL}"
    text = spec_path.read_text(encoding="utf-8")
    for marker in ("M1", "M2", "M3", "M4", "M5", "채택 트리거", "범위 밖", __name__.split(".")[-1]):
        assert marker in text, f"명세 문서에 {marker!r} 절이 없다 — 문서와 테스트가 갈라졌다"
