"""예시 생성기(example_generator) 단위 테스트 — 슬롯 상태기계 재사용·잔여 발주·결함 검수.

hermetic(라이브 LLM 0 — FakeProvider 주입). 검증 축:
  ① 잔여 슬롯 계획(발주 − 승인·숫자형 제외·충족 슬롯 발주 금지)
  ② DRAFT 슬롯 행 형태(build_slot_rows 동형 키 — 기존 ContentSlotStore/전이 무수정 소비)
  ③ 검수 확장(review_example_rows) — 기존 review_slot + 정답 유출·게임형 축(게임형 0 검사)
  ④ 시스템 프롬프트 분리 — 예시 grain은 EXAMPLE_SYSTEM_PROMPT로 호출(비유 프롬프트 오배선 방지)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

import pytest

from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.pedagogy.example_generator import (
    EXAMPLE_SYSTEM_PROMPT,
    ExampleGenerator,
    ExampleTarget,
    build_example_slot_row,
    plan_remaining_slots,
    review_example_rows,
)

_OBJ = "10공수1-이차함수-최대최소:OBJ-01"
_TARGET = ExampleTarget(
    objective_id=_OBJ,
    slot_type="example_pair",
    count=2,
    statement="정의역이 제한된 이차함수의 최대·최소의 뜻을 이해한다",
)

_GOOD_BODY = (
    "편의점 아르바이트를 하는 지우는 시급과 근무 시간표를 보며 이번 주 급여를 어떻게 "
    "셈할지 고민한다."
)
_GOOD_JSON = json.dumps(
    {"body": _GOOD_BODY, "structure_tags": ["real_life", "quadratic"]}, ensure_ascii=False
)


class FakeProvider:
    """스크립트 응답 provider 대역 — 호출 캡처(시스템 프롬프트 검증용)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self.decisions: list[RoutingDecision] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        self.calls.append((prompt, system))
        self.decisions.append(decision)
        text = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return GenerationResult(text=text)


class _NullTrace:
    def record(self, fields: dict[str, object]) -> None:
        del fields


def _generator(provider: FakeProvider) -> ExampleGenerator:
    return ExampleGenerator(provider, trace=_NullTrace())  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────
# ① 잔여 슬롯 계획
# ──────────────────────────────────────────────────────────────────────────
class TestPlanRemainingSlots:
    _WORK_ORDER = [
        {"objective_id": _OBJ, "slot_type": "example_pair", "count": 4},
        {"objective_id": _OBJ, "slot_type": "diag_item", "count": 2},  # 숫자형 — 제외 대상
        {"objective_id": _OBJ, "slot_type": "contrast_case", "count": 2},
    ]

    def test_remaining_arithmetic(self) -> None:
        """잔여 = 발주 − 승인. 승인 수는 호출자가 DB에서 계수해 주입(순수 함수)."""
        targets = plan_remaining_slots(
            self._WORK_ORDER, {(_OBJ, "example_pair"): 3}, statements={_OBJ: "목표 진술"}
        )
        by_type = {t.slot_type: t.count for t in targets}
        assert by_type == {"example_pair": 1, "contrast_case": 2}

    def test_numeric_slot_types_excluded(self) -> None:
        """숫자형(diag_item 등)은 표적 제외 — 검증 불가능한 답 저작 금지(동등문제 생성기 소관)."""
        targets = plan_remaining_slots(self._WORK_ORDER, {})
        assert all(t.slot_type != "diag_item" for t in targets)

    def test_fulfilled_slot_not_ordered(self) -> None:
        """충족(승인≥발주) 슬롯은 발주 0 — 사전 대량 생성 금지(04g §6.4)."""
        targets = plan_remaining_slots(
            self._WORK_ORDER, {(_OBJ, "example_pair"): 4, (_OBJ, "contrast_case"): 5}
        )
        assert targets == []

    def test_invalid_target_count_rejected(self) -> None:
        with pytest.raises(ValueError):
            ExampleTarget(objective_id=_OBJ, slot_type="example_pair", count=0, statement="s")


# ──────────────────────────────────────────────────────────────────────────
# ② DRAFT 슬롯 행 — 기존 파이프라인 동형 키
# ──────────────────────────────────────────────────────────────────────────
class TestSlotRowShape:
    def test_row_compatible_with_slot_pipeline(self) -> None:
        """행 키가 build_slot_rows 동형 — ContentSlotStore/Prescreen/Review 무수정 소비."""
        row = build_example_slot_row(_TARGET, _GOOD_BODY, ["real_life"], 0)
        assert row["status"] == "DRAFT"
        assert row["objective_id"] == _OBJ
        assert row["slot_type"] == "example_pair"
        assert row["provenance_id"] is None  # LLM provenance 결선은 라이브 런북 소관(정직 공백)
        assert row["sympy_verified"] is None  # verification 주장 없음 — 개념형 정직 표기
        assert row["tts_safe"] is True
        assert row["payload"]["generated_by"].startswith("llm:example_generator/")

    def test_llm_namespace_id_no_collision_with_pilot(self) -> None:
        """id 네임스페이스 `:llm:` — 파일럿 픽스처 id(`...:0`)와 충돌하지 않는다(멱등 안전)."""
        row = build_example_slot_row(_TARGET, _GOOD_BODY, [], 0)
        assert row["id"] == f"{_OBJ}:example_pair:llm:0"

    def test_generated_via_provider_uses_example_system_prompt(self) -> None:
        """④ 예시 grain은 EXAMPLE_SYSTEM_PROMPT로 호출 — 비유 프롬프트 오배선 회귀 방지."""
        provider = FakeProvider([_GOOD_JSON])
        row = _generator(provider).generate_slot_row(_TARGET, 0)
        assert row is not None
        _prompt, system = provider.calls[0]
        assert system == EXAMPLE_SYSTEM_PROMPT
        assert "실생활 예시 저작자" in system

    def test_router_decision_reaches_provider(self) -> None:
        """라우터 경유 — provider가 받는 결정은 라우터 산출(직접 호출 금지 준수)."""
        provider = FakeProvider([_GOOD_JSON])
        _generator(provider).generate_slot_row(_TARGET, 0)
        assert provider.decisions[0].cost_tier == "local"  # free 구독 → LOCAL

    def test_body_missing_returns_none(self) -> None:
        empty = json.dumps({"structure_tags": ["x"]}, ensure_ascii=False)
        assert _generator(FakeProvider([empty])).generate_slot_row(_TARGET, 0) is None


# ──────────────────────────────────────────────────────────────────────────
# ③ 검수 확장 — 정답 유출·게임형 반려(게임형 0 검사)
# ──────────────────────────────────────────────────────────────────────────
class TestReviewExampleRows:
    def test_clean_row_approved(self) -> None:
        row = build_example_slot_row(_TARGET, _GOOD_BODY, ["real_life"], 0)
        [(slot_id, verdict)] = review_example_rows([row])
        assert slot_id == row["id"]
        assert verdict.approved is True

    def test_gamified_body_rejected(self) -> None:
        """게임형 본문 REJECT(GAMIFIED) — APPROVED 산출의 게임형 0을 게이트가 보장."""
        row = build_example_slot_row(
            _TARGET, "미션 클리어 때마다 경험치를 주는 매점 이야기.", [], 0
        )
        [(_slot_id, verdict)] = review_example_rows([row])
        assert verdict.approved is False
        assert verdict.reason == "GAMIFIED"

    def test_answer_leak_rejected(self) -> None:
        """payload에 answer가 있고 본문에 노출되면 ANSWER_LEAK 계열 반려(fail-closed).

        기존 review_slot의 answer_leak과 예시 축 검사가 이중 방어라 사유는 둘 중 하나다.
        """
        row = build_example_slot_row(_TARGET, "의자 수는 12개라는 결론까지 적는다.", [], 0)
        row["payload"]["answer"] = "12"
        [(_slot_id, verdict)] = review_example_rows([row])
        assert verdict.approved is False
        assert verdict.reason in ("answer_leak", "ANSWER_LEAK")

    def test_structural_gate_reused(self) -> None:
        """빈 태그 없는 본문 등 구조 결함은 기존 review_slot이 반려 — 상태기계 재사용 실증."""
        row = build_example_slot_row(_TARGET, _GOOD_BODY, [], 0)
        row["payload"]["structure_tags"] = []
        [(_slot_id, verdict)] = review_example_rows([row])
        assert verdict.approved is False
        assert verdict.reason == "missing_structure_tags"

    def test_dice_game_example_not_falsely_blocked(self) -> None:
        """주사위 게임(확률 소재) 예시는 통과 — 게임형 축의 경계 변별(오차단 방지)."""
        row = build_example_slot_row(
            _TARGET, "주사위 게임을 하던 두 친구가 합의 가능성을 두고 내기를 걸었다.", ["prob"], 0
        )
        [(_slot_id, verdict)] = review_example_rows([row])
        assert verdict.approved is True
