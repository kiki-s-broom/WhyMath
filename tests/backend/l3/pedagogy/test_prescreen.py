"""슬라이스2 예심 단계 테스트 — prescreen_slot 루브릭·PrescreenStore 전이.

hermetic: 순수 루브릭 + 가짜 sync 엔진. 변별력: 답 틀린 숫자형·구조 결함 슬롯은 2점 미만.
"""

from __future__ import annotations

from types import TracebackType

from whymath_backend.composition import default_expression_equivalence
from whymath_backend.l3.pedagogy.prescreen import (
    PRESCREEN_PASS_THRESHOLD,
    PrescreenStore,
    prescreen_rows,
    prescreen_slot,
)
from whymath_backend.l3.pedagogy.slot_generator import build_slot_rows

_GOOD_NUMERIC = {
    "body": "이차함수 $f(x)=x^{2}-4x+3$ 의 최솟값을 구하시오.",
    "reasoning_type": "diag_item",
    "structure_tags": ["quadratic"],
}
_GOOD_CONCEPT = {
    "body": "이차함수 $y=x^{2}$ 의 예와 비예를 들어보시오.",
    "reasoning_type": "example_pair",
    "structure_tags": ["quadratic"],
}


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진
# ──────────────────────────────────────────────────────────────────────────
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

    # literal_binds — 바인드 파라미터 대신 실제 값('DRAFT' 등)을 드러내 단언 변별력 확보.
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


# ──────────────────────────────────────────────────────────────────────────
# 루브릭
# ──────────────────────────────────────────────────────────────────────────
class TestPrescreenRubric:
    def test_good_numeric_passes(self) -> None:
        score = prescreen_slot(_GOOD_NUMERIC, sympy_verified=True, tts_safe=True)
        assert score == 3
        assert score >= PRESCREEN_PASS_THRESHOLD

    def test_good_conceptual_passes(self) -> None:
        # 개념형(sympy_verified None)도 구조 3요건이면 통과.
        score = prescreen_slot(_GOOD_CONCEPT, sympy_verified=None, tts_safe=True)
        assert score >= PRESCREEN_PASS_THRESHOLD

    def test_wrong_math_hard_fails(self) -> None:
        # 답 틀린 숫자형(sympy_verified False) → 0(fail-closed·2점 미만).
        score = prescreen_slot(_GOOD_NUMERIC, sympy_verified=False, tts_safe=True)
        assert score == 0
        assert score < PRESCREEN_PASS_THRESHOLD

    def test_structural_defect_fails(self) -> None:
        # TTS 불안전 + 태그 없음 → 본문+유형(1)만 → 2점 미만.
        broken = {"body": "짝 안맞는 $x", "reasoning_type": "diag_item"}
        score = prescreen_slot(broken, sympy_verified=None, tts_safe=False)
        assert score < PRESCREEN_PASS_THRESHOLD

    def test_score_clamped_0_3(self) -> None:
        for sv in (True, False, None):
            s = prescreen_slot(_GOOD_NUMERIC, sympy_verified=sv, tts_safe=True)
            assert 0 <= s <= 3

    def test_prescreen_rows_from_generated(self) -> None:
        rows = build_slot_rows(
            "U:OBJ-01",
            [{"type": "diag_item", "count": 2}],
            equivalence=default_expression_equivalence(),
        )
        scored = prescreen_rows(rows)
        assert len(scored) == 2
        assert all(score >= PRESCREEN_PASS_THRESHOLD for _id, score in scored)


# ──────────────────────────────────────────────────────────────────────────
# PrescreenStore — DRAFT만 전이(WHERE 가드)
# ──────────────────────────────────────────────────────────────────────────
class TestPrescreenStore:
    def test_apply_updates_only_draft(self) -> None:
        engine = _FakeEngine()
        n = PrescreenStore(engine=engine).apply([("U:OBJ-01:diag_item:0", 3)])  # type: ignore[arg-type]
        assert n == 1
        sql = _compile_sql(engine.executed[0])
        assert "UPDATE pedagogy_content_slot SET" in sql
        # 승격 목표 상태 = PRESCREENED, 전이 대상 가드 = DRAFT만(fail-closed).
        assert "'PRESCREENED'" in sql
        assert "WHERE" in sql and "'DRAFT'" in sql
