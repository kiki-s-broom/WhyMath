"""슬라이스3 검수 단계 테스트 — review_slot 기계 게이트·verb_confirms_k_type·ReviewStore.

hermetic: 순수 게이트 + 가짜 sync 엔진. 변별력: 답 틀림·구조 결함·정답 유출은 실제 REJECT.
"""

from __future__ import annotations

from types import TracebackType

from whymath_backend.composition import default_expression_equivalence
from whymath_backend.l3.pedagogy.review import (
    REVIEWER_TAG,
    ReviewStore,
    ReviewVerdict,
    review_rows,
    review_slot,
    verb_confirms_k_type,
)
from whymath_backend.l3.pedagogy.slot_generator import build_slot_rows

# EOS-89: 항등 판정 능력은 상류가 준다 — 이 파일에서는 테스트가 상류(엔트리포인트)다.
_EQ = default_expression_equivalence()

_VALID_NUMERIC = {
    "body": "이차함수 $f(x)=x^{2}-4x+3$ 의 최솟값을 구하시오.",
    "answer": "-1",
    "reasoning_type": "diag_item",
    "structure_tags": ["quadratic"],
    "verification": {"claim_lhs": "(2)**2 - 4*(2) + 3", "claim_rhs": "-1"},
}


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> None:
        self._engine.executed.append(statement)


class _FakeEngine:
    def __init__(self) -> None:
        self.executed: list[object] = []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _compile_sql(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


# ──────────────────────────────────────────────────────────────────────────
# review_slot — 기계 게이트 변별력
# ──────────────────────────────────────────────────────────────────────────
class TestReviewGate:
    def test_valid_numeric_approved(self) -> None:
        assert review_slot(_VALID_NUMERIC, equivalence=_EQ) == ReviewVerdict(True, None)

    def test_wrong_math_rejected(self) -> None:
        broken = {
            **_VALID_NUMERIC,
            "verification": {"claim_lhs": "1", "claim_rhs": "2"},
        }
        v = review_slot(broken, equivalence=_EQ)
        assert v.approved is False
        assert v.reason == "sympy_reverify_failed"

    def test_answer_leak_rejected(self) -> None:
        # 문제 본문에 답(-1)이 그대로 노출 → 반려.
        leaked = {
            "body": "최솟값은 -1 이다. 확인하시오.",
            "answer": "-1",
            "reasoning_type": "diag_item",
            "structure_tags": ["quadratic"],
            "verification": {"claim_lhs": "(2)**2 - 4*(2) + 3", "claim_rhs": "-1"},
        }
        v = review_slot(leaked, equivalence=_EQ)
        assert v.approved is False
        assert v.reason == "answer_leak"

    def test_missing_tags_rejected(self) -> None:
        no_tags = {"body": "이차함수 $y=x^{2}$ 발문", "reasoning_type": "example_pair"}
        v = review_slot(no_tags, equivalence=_EQ)
        assert v.approved is False
        assert v.reason == "missing_structure_tags"

    def test_generated_pilot_slots_all_approved(self) -> None:
        # 생성 단계가 낸 정상 슬롯은 전부 승인돼야 릴리스 게이트(fill_pct=100)에 도달한다.
        rows = build_slot_rows(
            "U:OBJ-01",
            [{"type": "example_pair", "count": 2}, {"type": "diag_item", "count": 2}],
            equivalence=default_expression_equivalence(),
        )
        verdicts = review_rows(rows, equivalence=_EQ)
        assert all(v.approved for _id, v in verdicts)


# ──────────────────────────────────────────────────────────────────────────
# verb_confirms_k_type — 성숙 팩만 확정(MODELING 스텁 제외)
# ──────────────────────────────────────────────────────────────────────────
class TestVerbConfirmsKType:
    def test_full_pack_verbs_confirm(self) -> None:
        assert verb_confirms_k_type("이해한다", "CONCEPT") is True
        assert verb_confirms_k_type("구한다", "PROCEDURE") is True
        assert verb_confirms_k_type("해석한다", "REPRESENT") is True

    def test_modeling_stub_not_confirmed(self) -> None:
        # OBJ-04(해결한다/MODELING 스텁)은 미확정 — k_type_verified False 유지.
        assert verb_confirms_k_type("해결한다", "MODELING") is False

    def test_mismatch_not_confirmed(self) -> None:
        assert verb_confirms_k_type("이해한다", "PROCEDURE") is False
        assert verb_confirms_k_type(None, "CONCEPT") is False


# ──────────────────────────────────────────────────────────────────────────
# ReviewStore — 승격 SQL(PRESCREENED 가드·기계 각인)
# ──────────────────────────────────────────────────────────────────────────
class TestReviewStore:
    def test_apply_sets_status_and_reviewer(self) -> None:
        engine = _FakeEngine()
        n = ReviewStore(engine=engine).apply(  # type: ignore[arg-type]
            [("U:OBJ-01:diag_item:0", ReviewVerdict(True, None))]
        )
        assert n == 1
        sql = _compile_sql(engine.executed[0])
        assert "'APPROVED'" in sql
        assert REVIEWER_TAG in sql
        # 검수 대상은 PRESCREENED만(fail-closed 가드).
        assert "WHERE" in sql and "'PRESCREENED'" in sql

    def test_reject_records_reason(self) -> None:
        engine = _FakeEngine()
        ReviewStore(engine=engine).apply(  # type: ignore[arg-type]
            [("U:OBJ-01:diag_item:0", ReviewVerdict(False, "answer_leak"))]
        )
        sql = _compile_sql(engine.executed[0])
        assert "'REJECTED'" in sql
        assert "answer_leak" in sql

    def test_set_k_type_verified(self) -> None:
        engine = _FakeEngine()
        n = ReviewStore(engine=engine).set_k_type_verified(["U:OBJ-01", "U:OBJ-02"])  # type: ignore[arg-type]
        assert n == 2
        sql = _compile_sql(engine.executed[0])
        assert "UPDATE learning_objective SET" in sql
        assert "k_type_verified" in sql

    def test_set_k_type_verified_empty_noop(self) -> None:
        engine = _FakeEngine()
        n = ReviewStore(engine=engine).set_k_type_verified([])  # type: ignore[arg-type]
        assert n == 0
        assert engine.executed == []
