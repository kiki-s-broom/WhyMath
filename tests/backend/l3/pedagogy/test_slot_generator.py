"""슬라이스1 생성 단계 테스트 — build_slot_rows·verify_slot_payload·ContentSlotStore.

hermetic(PG 불요): 순수 함수 + 가짜 sync 엔진(`_FakeEngine`, 컴파일러 테스트 패턴 재사용).
변별력 원칙: 검증 스텝은 실패 상태에서 실제로 실패 신호를 내야 한다(틀린 답 reject·홀수 $ False).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import pytest

from whymath_backend.composition import default_expression_equivalence
from whymath_backend.l3.pedagogy.slot_generator import (
    NUMERIC_SLOT_TYPES,
    ContentSlotStore,
    build_slot_rows,
    verify_slot_payload,
)

# CONCEPT 팩 슬롯 구조(개념형 3종 + diag_item 숫자형) — 파일럿 OBJ-01 미러.
_CONCEPT_MANIFEST: list[dict[str, Any]] = [
    {"type": "example_pair", "count": 4},
    {"type": "contrast_case", "count": 2},
    {"type": "boundary_probe", "count": 3},
    {"type": "diag_item", "count": 2},
]
_OBJ_ID = "10공수1-이차함수-최대최소:OBJ-01"


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 (compiler/pack_loader 테스트 패턴 재사용)
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

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# build_slot_rows
# ──────────────────────────────────────────────────────────────────────────
class TestBuildSlotRows:
    def test_count_matches_manifest_total(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID, _CONCEPT_MANIFEST, equivalence=default_expression_equivalence()
        )
        assert len(rows) == 4 + 2 + 3 + 2  # slot_manifest count 합

    def test_ids_deterministic_and_shaped(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID, _CONCEPT_MANIFEST, equivalence=default_expression_equivalence()
        )
        ids = [r["id"] for r in rows]
        assert f"{_OBJ_ID}:example_pair:0" in ids
        assert f"{_OBJ_ID}:diag_item:1" in ids
        # 결정론 — 같은 입력이면 같은 행(재실행 안정).
        assert (
            build_slot_rows(
                _OBJ_ID, _CONCEPT_MANIFEST, equivalence=default_expression_equivalence()
            )
            == rows
        )

    def test_all_draft_and_no_provenance(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID, _CONCEPT_MANIFEST, equivalence=default_expression_equivalence()
        )
        assert all(r["status"] == "DRAFT" for r in rows)
        assert all(r["provenance_id"] is None for r in rows)

    def test_numeric_slot_verified_true(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID,
            [{"type": "diag_item", "count": 2}],
            equivalence=default_expression_equivalence(),
        )
        assert all(r["slot_type"] in NUMERIC_SLOT_TYPES for r in rows)
        # 숫자형은 SymPy 검증 통과 → True(개념형 None 아님).
        assert all(r["sympy_verified"] is True for r in rows)

    def test_conceptual_slot_verified_none(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID,
            [{"type": "example_pair", "count": 3}],
            equivalence=default_expression_equivalence(),
        )
        assert all(r["slot_type"] not in NUMERIC_SLOT_TYPES for r in rows)
        # 개념형은 수치 검증 대상 아님 → None(정직 표기).
        assert all(r["sympy_verified"] is None for r in rows)

    def test_all_rows_tts_safe(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID, _CONCEPT_MANIFEST, equivalence=default_expression_equivalence()
        )
        assert all(r["tts_safe"] is True for r in rows)


# ──────────────────────────────────────────────────────────────────────────
# verify_slot_payload — 변별력(틀린 답은 실제로 reject)
# ──────────────────────────────────────────────────────────────────────────
class TestVerifyDiscrimination:
    def test_correct_answer_verified(self) -> None:
        payload = {"verification": {"claim_lhs": "(2)**2 - 4*(2) + 3", "claim_rhs": "-1"}}
        assert verify_slot_payload(payload, equivalence=default_expression_equivalence()) is True

    def test_wrong_answer_rejected(self) -> None:
        # 답을 일부러 틀리게(-1이 맞는데 0 주장) → not_identity → False.
        payload = {"verification": {"claim_lhs": "(2)**2 - 4*(2) + 3", "claim_rhs": "0"}}
        assert verify_slot_payload(payload, equivalence=default_expression_equivalence()) is False

    def test_no_verification_returns_none(self) -> None:
        # 주장이 없으면 능력을 건드리지 않는다 — 미주입이어도 None(EOS-89 fail-loud의 경계).
        assert verify_slot_payload({"body": "개념 발문"}) is None

    def test_claim_without_injected_capability_fails_loudly(self) -> None:
        """주장이 있는데 능력이 없으면 **터진다** — 조용히 통과하거나 False로 위장하지 않는다.

        EOS-89가 기본값 폴백(`default_expression_equivalence()`)을 걷어낸 자리의 변별력 검사다.
        폴백이 남아 있었다면 이 호출은 True를 냈을 것이다(그래서 이 테스트는 뮤테이션 검출력이
        있다 — 폴백을 되살리면 RED).
        """
        payload = {"verification": {"claim_lhs": "(2)**2 - 4*(2) + 3", "claim_rhs": "-1"}}
        with pytest.raises(LookupError, match="ExpressionEquivalence"):
            verify_slot_payload(payload)


# ──────────────────────────────────────────────────────────────────────────
# _is_tts_safe — 변별력(홀수 $ 는 False)
# ──────────────────────────────────────────────────────────────────────────
class TestTtsSafeDiscrimination:
    def test_unbalanced_dollar_is_unsafe(self) -> None:
        from whymath_backend.l3.pedagogy.slot_generator import _is_tts_safe

        assert _is_tts_safe({"body": "짝 안 맞는 $x^2 수식"}) is False

    def test_empty_body_is_unsafe(self) -> None:
        from whymath_backend.l3.pedagogy.slot_generator import _is_tts_safe

        assert _is_tts_safe({"body": "   "}) is False
        assert _is_tts_safe({}) is False


# ──────────────────────────────────────────────────────────────────────────
# ContentSlotStore — 멱등 upsert(PK id는 SET 제외)
# ──────────────────────────────────────────────────────────────────────────
class TestContentSlotStore:
    def test_seed_upsert_excludes_pk(self) -> None:
        rows = build_slot_rows(
            _OBJ_ID,
            [{"type": "diag_item", "count": 1}],
            equivalence=default_expression_equivalence(),
        )
        engine = _FakeEngine()
        n = ContentSlotStore(engine=engine).seed(rows)  # type: ignore[arg-type]
        assert n == 1
        assert len(engine.executed) == 1
        sql = _compile_sql(engine.executed[0])
        assert "ON CONFLICT" in sql
        assert "pedagogy_content_slot" in sql
        # PK id는 갱신 SET에서 제외돼야 한다(멱등·PK 보존).
        assert "SET" in sql and "id = excluded.id" not in sql
