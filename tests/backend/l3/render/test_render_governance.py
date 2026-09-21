"""렌더 거버넌스 — 조합폭발 방지·개념 무관성·폐쇄 enum 동결(구조 불변식 소스 스캔).

선례: `tests/backend/l1/test_embedding_namespace_governance.py`(소스 스캔+allowlist 동결)·
`tests/backend/l1/test_skill_governance.py`(폐쇄 집합 동결).

이 테스트가 지키는 것은 **저장 자산이 곱이 아니라 합**이라는 03c의 핵심 구조다. 어댑터가 개념을
알기 시작하면(개념명 하드코딩·개념별 어댑터 분기) 어댑터 수가 개념 수를 따라 자라고, 그 순간
조합폭발이 시작된다. 규칙을 문서에만 두지 않고 기계가 막는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.l3.render import registry
from whymath_backend.l3.render.dsl import ConceptDSL
from whymath_backend.schema.enums import PedagogyStrategy

# 폐쇄 10종 동결 — 확장은 거버넌스 결정 전제(03c §2.1). 특히 GAME은 "무자비한 게임화 금지"
# 정체성 축이라 의도적으로 부재하며, 이 테스트가 그 부재를 지킨다.
_EXPECTED_STRATEGIES: frozenset[str] = frozenset(
    {
        "DIRECT",
        "SOCRATIC",
        "WORKED_EXAMPLE",
        "PROBLEM_BASED",
        "RETRIEVAL",
        "SPACING",
        "INTERLEAVING",
        "SELF_EXPLANATION",
        "ANALOGY",
        "VISUALIZATION",
    }
)

# 어댑터 소스에 나타나면 안 되는 *개념명*(주제 명사). 어댑터는 DSL 필드를 일반 조작할 뿐,
# 특정 개념을 알아선 안 된다. `schema/pedagogy_pack.py::SUBJECT_NOUN_BLOCKLIST`와 같은 성격의
# best-effort lint다.
_CONCEPT_NOUN_DENYLIST: tuple[str, ...] = (
    "일차방정식",
    "이차방정식",
    "일차함수",
    "이차함수",
    "삼각함수",
    "지수함수",
    "로그함수",
    "미분",
    "적분",
    "도함수",
    "확률변수",
    "등차수열",
    "등비수열",
    "벡터",
    "행렬",
)

# 렌더 패키지 소스 파일(테스트 대상 스캔 범위).
_RENDER_DIR = Path(registry.__file__).parent


def _render_sources() -> dict[str, str]:
    """`l3/render/` 내 모든 파이썬 소스 — {파일명: 본문}."""
    return {
        path.name: path.read_text(encoding="utf-8") for path in sorted(_RENDER_DIR.rglob("*.py"))
    }


def _strip_docs_and_comments(source: str) -> str:
    """docstring·주석을 제거한 *실행 코드*만 반환 — 개념명 스캔의 정밀도를 위해.

    설계 의도를 설명하는 산문("특정 개념(일차방정식·미분)을 알지 못한다")은 개념 결합이 아니라
    그 반대의 선언이다. 코드가 개념을 아는지만 검사해야 규칙이 의미를 갖는다(주석 때문에 규칙을
    약화시키지 않고, 검사 대상을 정확히 좁힌다).
    """
    tree = ast.parse(source)
    # docstring 노드 수집(모듈·클래스·함수의 첫 문자열 표현식).
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    doc_nodes.add(id(body[0]))

    class _DocStripper(ast.NodeTransformer):
        def visit_Expr(self, node: ast.Expr) -> ast.Expr | None:
            return None if id(node) in doc_nodes else node

    stripped = _DocStripper().visit(tree)
    # ast.unparse는 주석을 애초에 보존하지 않으므로, 이 왕복으로 주석도 함께 제거된다.
    return ast.unparse(stripped)


class TestPedagogyStrategyFrozen:
    """폐쇄 enum 동결 — 확장은 의도적 결정이어야 한다."""

    def test_exactly_ten_strategies(self) -> None:
        assert len(PedagogyStrategy) == 10

    def test_value_set_frozen(self) -> None:
        assert {s.value for s in PedagogyStrategy} == _EXPECTED_STRATEGIES

    def test_member_name_equals_value(self) -> None:
        # house style — 멤버명 == 값(KnowledgeType 선례).
        for strategy in PedagogyStrategy:
            assert strategy.name == strategy.value

    def test_game_strategy_absent(self) -> None:
        # CLAUDE.md 절대 금기 "무자비한 게임화·중독성 설계 금지" — 추가는 별도 거버넌스 결정.
        assert "GAME" not in {s.value for s in PedagogyStrategy}
        assert "GAMIFICATION" not in {s.value for s in PedagogyStrategy}


class TestAdaptersAreConceptAgnostic:
    """개념 무관성 — 어댑터가 특정 개념을 알면 조합폭발이 시작된다."""

    def test_no_concept_noun_hardcoded_in_render_sources(self) -> None:
        # 검사 대상은 *실행 코드*다 — 설계 의도를 설명하는 docstring은 개념 결합이 아니다.
        offenders: dict[str, list[str]] = {}
        for filename, source in _render_sources().items():
            code = _strip_docs_and_comments(source)
            hits = [noun for noun in _CONCEPT_NOUN_DENYLIST if noun in code]
            if hits:
                offenders[filename] = hits
        assert not offenders, (
            f"렌더 소스에 개념명이 하드코딩됐습니다: {offenders}. 어댑터는 ConceptDSL 필드를 "
            "일반 조작해야 하며 특정 개념을 알아선 안 됩니다(개념 무관 — 조합폭발 방지)."
        )

    def test_denylist_scan_detects_real_violation(self) -> None:
        # 변별력 확인 — 실제 코드에 개념명이 박히면 반드시 잡힌다(CLAUDE.md "변별력 없는 검증
        # 스텝 금지"). 이 검사가 없으면 위 테스트가 항상 통과하는 위장일 수 있다.
        violating = 'def render():\n    return "일차방정식 전용 처리"\n'
        code = _strip_docs_and_comments(violating)
        assert [noun for noun in _CONCEPT_NOUN_DENYLIST if noun in code] == ["일차방정식"]

    def test_docstring_mention_is_not_a_violation(self) -> None:
        # 반대 방향 — 산문 속 개념명은 통과해야 한다(오탐 없음).
        documented = (
            '"""특정 개념(일차방정식·미분)을 알지 못한다."""\n\ndef render():\n    return 1\n'
        )
        code = _strip_docs_and_comments(documented)
        assert [noun for noun in _CONCEPT_NOUN_DENYLIST if noun in code] == []

    def test_adapter_count_scales_with_strategies_not_concepts(self) -> None:
        # 등록 어댑터 수 ≤ 전략 수. 개념(원자 2,697)과 무관하게 상한이 걸린다.
        assert len(registry.registered_strategies()) <= len(PedagogyStrategy)

    def test_one_adapter_per_strategy_no_duplicates(self) -> None:
        # EOS-89: 어댑터는 과목 능력을 생성 시 주입받는다 — 테스트가 그 상류 역할을 한다.
        strategies = [
            registry.get_adapter(
                s,
                seal=default_expression_seal(),
                assessment_verifier=default_assessment_answer_verifier(),
            ).strategy
            for s in registry.registered_strategies()
        ]
        assert len(strategies) == len(set(strategies))


class TestNoVariantEnumeration:
    """변형 열거 금지 — 숫자·이름 변이는 렌더 바인딩이지 새 자산이 아니다."""

    def test_render_package_has_no_per_concept_modules(self) -> None:
        # 개념별 모듈(예: linear_equation_adapter.py)이 생기면 곧 자산이 곱으로 자란다.
        # `assessment_bank.py`는 개념별 모듈이 아니라 **개념 무관 조회 레이어**다(개념 code →
        # 참조 1건). 개념이 늘어도 이 파일은 자라지 않고 코퍼스 산출물의 행만 늘어난다.
        allowed = {
            "__init__.py",
            "adapter.py",
            "adapters.py",
            "assessment_bank.py",
            "dsl.py",
            "registry.py",
        }
        actual = set(_render_sources())
        assert actual == allowed, (
            f"렌더 패키지 모듈 구성이 바뀌었습니다: {sorted(actual - allowed)} 추가/"
            f"{sorted(allowed - actual)} 삭제. 개념별 모듈 추가는 조합폭발의 신호이므로, "
            "의도한 변경이면 이 allowlist를 함께 갱신하세요."
        )

    def test_bindings_are_render_time_not_stored_variants(self) -> None:
        # 치환 자리는 DSL에 열거되지 않는다 — 렌더 시점 입력(RenderContext.bindings)이다.
        assert "bindings" not in ConceptDSL.model_fields


class TestDslStaysPedagogyNeutral:
    """DSL 필드 축 동결 — 콘텐츠 계약에 *방식* 필드가 들어오면 위반."""

    def test_no_method_field_names(self) -> None:
        method_field_names = {
            "pedagogy",
            "strategy",
            "presentation_mode",
            "mode",
            "teaching_style",
            "render_style",
        }
        actual = set(ConceptDSL.model_fields)
        leaked = actual & method_field_names
        assert not leaked, (
            f"ConceptDSL에 교수 방식 필드가 들어왔습니다: {sorted(leaked)}. 콘텐츠는 '무엇을 "
            "가르치나'만 담고, 방식은 렌더 어댑터가 결정합니다(Renderer=Plugin)."
        )

    def test_field_set_frozen(self) -> None:
        assert set(ConceptDSL.model_fields) == {
            "code",
            "name",
            "subject",
            "unit",
            "definition",
            "intuition",
            "examples",
            "misconceptions",
            "relations",
            "assessment",
        }


class TestLayerBoundary:
    """계층 경계 — 렌더(L3)는 선택(L4)을 임포트하지 않는다(import-linter 보강)."""

    def test_render_does_not_import_upper_layers(self) -> None:
        offenders: dict[str, list[str]] = {}
        for filename, source in _render_sources().items():
            hits = [
                layer
                for layer in ("whymath_backend.l4", "whymath_backend.l5", "whymath_backend.l6")
                if layer in source
            ]
            if hits:
                offenders[filename] = hits
        assert not offenders, (
            f"렌더가 상위 계층을 임포트합니다: {offenders}. 전략 *선택*은 L4 소관이며 "
            "L4가 L3를 임포트합니다(역방향 금지)."
        )
