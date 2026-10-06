"""이벤트 페이로드 타입별 계약 거버넌스 게이트 — invariant ⑫.

`event_data`가 자유 JSONB로 방치되던 것을 *생산 7종*(검산결과·힌트제공·시각화조작·막힘·힌트요청·
답입력·문제시도)에 대해 계약(`schema/event_data_contract.py`)으로 고정했다(S3-16: 막힘·힌트요청·
답입력 3종이 휴면에서 편입 — 소생 / EOS-57: 문제시도는 *신규* EventType 추가). 이 테스트는 그
계약이:
  1) 생산 7종을 빠짐없이 덮고(휴면 5종은 명시적 면제·분류 누락 0),
  2) 하네스가 실제로 읽는 키(passed·hint_level)를 포함하며,
  3) stray key(자유 JSONB의 씨앗)를 produce 좌석에서 거부하고,
  4) `시각화조작.payload` 내부 자유형은 의도적으로 보존하는지
를 고정한다 — 계약이 코드(생산자)와 드리프트하면 즉시 red.

`test_render_contract.py`(⑩)·`test_embedding_namespace_governance.py`(⑨)와 동형 —
계약 단일원 + 거버넌스 테스트 패턴.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import (
    CONTRACT_EXEMPT_EVENT_TYPES,
    EVENT_DATA_CONTRACT,
    AttemptedEventData,
    DemandEventData,
    HintEventData,
    InteractionEventData,
    ResponseLatencyEventData,
    StuckEventData,
    VerifyEventData,
    build_event_data,
)

# 코드가 실제로 event_data를 *쓰는* EventType — 탐사(producer 전수 grep)로 확정한 7종.
# (api/coach.py: 검산결과·힌트제공·막힘·힌트요청·답입력, api/interactions.py: 시각화조작,
#  l2/attempt_skill_event.py: 문제시도 — EOS-57.)
_PRODUCED = {
    EventType.검산결과,
    EventType.힌트제공,
    EventType.시각화조작,
    EventType.막힘,
    EventType.힌트요청,
    EventType.답입력,
    EventType.문제시도,
}


def test_contract_covers_exactly_the_produced_types() -> None:
    """계약 키 == 실제 생산 7종(누락·잉여 0) — 단일 진실원 완전성."""
    assert set(EVENT_DATA_CONTRACT) == _PRODUCED


def test_every_event_type_is_classified() -> None:
    """계약 ∪ 면제 == 전체 EventType — 분류 누락 0(새 EventType 추가 시 어느 한쪽에 편입 강제)."""
    assert set(EVENT_DATA_CONTRACT) | CONTRACT_EXEMPT_EVENT_TYPES == set(EventType)
    # 겹침 0 — 한 타입이 계약이면서 동시에 면제일 수 없다.
    assert set(EVENT_DATA_CONTRACT).isdisjoint(CONTRACT_EXEMPT_EVENT_TYPES)


def test_dormant_types_are_exempt_not_contracted() -> None:
    """휴면 5종(문제읽기·조건분석·그래프그리기·계산·지움)은 면제 집합 — 계약으로 구속하지 않는다
    (premature 회피). S3-16으로 막힘·힌트요청·답입력 3종은 생산자를 얻어 계약으로 이동했다."""
    dormant = {
        EventType.문제읽기,
        EventType.조건분석,
        EventType.그래프그리기,
        EventType.계산,
        EventType.지움,
    }
    assert dormant == CONTRACT_EXEMPT_EVENT_TYPES


def test_harness_consumed_keys_are_in_contract() -> None:
    """하네스가 읽는 활성 키(passed·hint_level)가 계약 필드에 존재 — 소비처↔계약 정합.

    `wh1_evaluation.py`가 `event_data['passed']`(지표 ①)·`event_data['hint_level']`(지표 ⑤)를
    읽는다. 이 키가 계약에서 빠지면 지표가 조용히 깨지므로 여기서 고정한다.

    S4-19: `compute_step_verification_accounting`이 읽는 3상태 키(n_correct·n_incorrect·
    n_unverifiable·ocr_gated)도 같은 이유로 고정한다(reader↔계약 정합).
    """
    assert "passed" in VerifyEventData.model_fields
    assert "hint_level" in HintEventData.model_fields
    assert "n_correct" in VerifyEventData.model_fields
    assert "n_incorrect" in VerifyEventData.model_fields
    assert "n_unverifiable" in VerifyEventData.model_fields
    assert "ocr_gated" in VerifyEventData.model_fields


def test_s3_16_producer_fields_exist_in_contract() -> None:
    """S3-16 신규 페이로드 필드(mode·turn_count·server_latency_ms) 존재 — writer↔계약 정합.

    `api/coach.py`의 `_log_demand_event`·`_log_stuck_event`·`_log_response_latency_event`가
    각각 mode/turn_count/server_latency_ms를 싣는다. 이 키가 계약에서 빠지면 writer가
    조용히 깨지므로(`build_event_data`가 KeyError/ValidationError로 즉시 드러내긴 하나) 계약
    자체의 형태를 여기서 고정한다.
    """
    assert "mode" in DemandEventData.model_fields
    assert "persona" in DemandEventData.model_fields
    assert "turn_count" in StuckEventData.model_fields
    assert "server_latency_ms" in ResponseLatencyEventData.model_fields


def test_verify_normalizes_missing_error_kind() -> None:
    """`검산결과`를 passed만 주면 error_kind·mode·persona=None으로 정규화 — 드리프트 무해화.

    S3-03: 계약에 mode/persona(선택 태그)가 추가돼 미지정 시 None으로 채워진다(mode-agnostic·
    기존 생산 경로 의미 불변). S4-19: 3상태 6키도 미지정 시 None으로 채워진다(구판/무검증
    모양 — 신판 payload에는 키가 항상 존재하되 값 None 가능). MATH-03: 사유 분포 키도 동형.
    """
    data = build_event_data(EventType.검산결과, passed=True)
    assert data == {
        "passed": True,
        "error_kind": None,
        "mode": None,
        "persona": None,
        "n_correct": None,
        "n_incorrect": None,
        "n_unverifiable": None,
        "unverifiable_by_reason": None,
        "unverified_ratio": None,
        "first_incorrect_index": None,
        "ocr_gated": None,
    }


def test_verify_full_shape() -> None:
    data = build_event_data(EventType.검산결과, passed=False, error_kind="arithmetic")
    assert data == {
        "passed": False,
        "error_kind": "arithmetic",
        "mode": None,
        "persona": None,
        "n_correct": None,
        "n_incorrect": None,
        "n_unverifiable": None,
        "unverifiable_by_reason": None,
        "unverified_ratio": None,
        "first_incorrect_index": None,
        "ocr_gated": None,
    }


def test_verify_mode_persona_tag() -> None:
    """S3-03: 검산결과에 mode/persona 태그를 실으면 event_data에 그대로 보존(수능 세션 식별)."""
    data = build_event_data(EventType.검산결과, passed=True, mode="suneung", persona="A_일반고고3")
    assert data == {
        "passed": True,
        "error_kind": None,
        "mode": "suneung",
        "persona": "A_일반고고3",
        "n_correct": None,
        "n_incorrect": None,
        "n_unverifiable": None,
        "unverifiable_by_reason": None,
        "unverified_ratio": None,
        "first_incorrect_index": None,
        "ocr_gated": None,
    }


def test_s4_19_step_verification_fields_exist_in_contract() -> None:
    """S4-19 신규 페이로드 6필드 존재 — writer(coach `_log_verify_event`)↔계약 정합(S3-16형).

    `api/coach.py`의 `_log_verify_event`가 verify_solution 3상태 결과를 이 6키로 싣는다.
    키가 계약에서 빠지면 writer가 즉시 깨지므로(build_event_data가 ValidationError) 계약
    자체의 형태를 여기서 고정한다. 전건 default None(구판/무검증 하위호환)도 함께 고정.
    """
    for field in (
        "n_correct",
        "n_incorrect",
        "n_unverifiable",
        "unverified_ratio",
        "first_incorrect_index",
        "ocr_gated",
    ):
        assert field in VerifyEventData.model_fields
        assert VerifyEventData.model_fields[field].default is None  # 미지정=None(기존 동작 불변)


def test_s4_19_verify_step_counts_round_trip() -> None:
    """S4-19: 3상태 카운트를 실으면 그대로 보존 — 0은 0으로(None과 구분·S3-07 규약)."""
    data = build_event_data(
        EventType.검산결과,
        passed=True,
        n_correct=2,
        n_incorrect=0,
        n_unverifiable=1,
        unverifiable_by_reason={"parse_error": 1},
        unverified_ratio=1 / 3,
        first_incorrect_index=None,
        ocr_gated=False,
    )
    assert data == {
        "passed": True,
        "error_kind": None,
        "mode": None,
        "persona": None,
        "n_correct": 2,
        "n_incorrect": 0,  # 실측 0 — None(미지정)과 구분 보존
        "n_unverifiable": 1,
        "unverifiable_by_reason": {"parse_error": 1},  # MATH-03 — 문자열 키 그대로 보존
        "unverified_ratio": 1 / 3,
        "first_incorrect_index": None,  # n_incorrect==0이라 '없음'(미지정 아님 — 카운트로 구분)
        "ocr_gated": False,
    }


def test_math03_unverifiable_by_reason_contract() -> None:
    """MATH-03: 사유 분포 필드 — additive optional(default None)·writer↔계약 정합(S4-19 동형).

    `api/coach.py._log_verify_event`가 폐쇄 사유 코드(VerifyStepReasonCode 값) → 건수 dict를
    문자열 키로 싣는다. None=미지정(구판)·{}=검증 실행·보류 0 — 두 상태를 구분한다(분모 없는
    0 금지의 적재 축). 자유문 reason·steps는 계약에 아예 없다(비식별 규약).
    """
    assert "unverifiable_by_reason" in VerifyEventData.model_fields
    assert VerifyEventData.model_fields["unverifiable_by_reason"].default is None
    # {}(보류 0)와 None(미지정) 구분 보존.
    data = build_event_data(EventType.검산결과, passed=True, unverifiable_by_reason={})
    assert data["unverifiable_by_reason"] == {}
    # 자유문·단계 본문 키는 계약에 부재(넣으면 extra=forbid로 즉시 거부됨을 아래 stray 테스트가
    # 일반 검증) — 필드 목록 자체로 고정한다.
    assert "steps" not in VerifyEventData.model_fields
    assert "reason" not in VerifyEventData.model_fields


def test_hint_shape() -> None:
    assert build_event_data(EventType.힌트제공, hint_level=3) == {
        "hint_level": 3,
        "mode": None,
        "persona": None,
        # PED-04 D2: 불일치 태그 — 미지정 시 기본 False(기존 픽스처 무손상).
        "client_state_mismatch": False,
        # S4-11: 검수 힌트 미서빙 턴은 reveal_score·hint_id가 None(0으로 날조 금지).
        "reveal_score": None,
        "hint_id": None,
        # EOS-178: 라벨 없는 단계·적용된 라벨 — 미지정이면 구판 행과 같다(None).
        "base_level": None,
        "ability_level": None,
    }


def test_hint_mode_persona_tag() -> None:
    """S3-03: 힌트제공에 mode/persona 태그를 실으면 event_data에 그대로 보존(⑤⑧ mode-scoped)."""
    data = build_event_data(EventType.힌트제공, hint_level=2, mode="suneung")
    assert data == {
        "hint_level": 2,
        "mode": "suneung",
        "persona": None,
        "client_state_mismatch": False,
        "reveal_score": None,
        "hint_id": None,
        # EOS-178: 라벨 없는 단계·적용된 라벨 — 미지정이면 구판 행과 같다(None).
        "base_level": None,
        "ability_level": None,
    }


def test_hint_client_state_mismatch_tag() -> None:
    """PED-04 D2: client_state_mismatch=True 명시 시 event_data에 그대로 보존(집계 가능 좌석)."""
    data = build_event_data(EventType.힌트제공, hint_level=1, client_state_mismatch=True)
    assert data == {
        "hint_level": 1,
        "mode": None,
        "persona": None,
        "client_state_mismatch": True,
        "reveal_score": None,
        "hint_id": None,
        # EOS-178: 라벨 없는 단계·적용된 라벨 — 미지정이면 구판 행과 같다(None).
        "base_level": None,
        "ability_level": None,
    }


def test_interaction_envelope_shape() -> None:
    """`시각화조작` 봉투 5키 — 생산자(interactions.py)가 쓰던 키와 정확히 일치."""
    data = build_event_data(
        EventType.시각화조작,
        interaction="param_change",
        payload={"name": "a", "value": 2},
        client_at=123,
        concept_id="math.calculus.limit",
        scene_id="scene-1",
    )
    assert set(data) == {
        "interaction",
        "payload",
        "client_at",
        "concept_id",
        "scene_id",
    }
    assert data["payload"] == {"name": "a", "value": 2}


def test_interaction_payload_stays_free() -> None:
    """봉투는 계약이지만 내부 payload는 자유형(조작 종류별 상이) — 임의 중첩 dict 허용."""
    model = InteractionEventData(
        interaction="surface_range",
        payload={"axis": "x", "range": [-5, 5], "nested": {"deep": True}},
    )
    assert model.payload["nested"] == {"deep": True}


def test_interaction_optional_context_defaults() -> None:
    """concept_id·scene_id·client_at은 선택(약점개념 흐름 밖에선 없음) → None 기본."""
    data = build_event_data(EventType.시각화조작, interaction="param_play")
    assert data == {
        "interaction": "param_play",
        "payload": {},
        "client_at": None,
        "concept_id": None,
        "scene_id": None,
    }


def test_demand_shape() -> None:
    """`힌트요청`은 값 필드 없이 mode·persona만(발생 자체가 신호·supply와 대칭이나 값 없음)."""
    assert build_event_data(EventType.힌트요청) == {"mode": None, "persona": None}
    data = build_event_data(EventType.힌트요청, mode="suneung", persona="A_일반고고3")
    assert data == {"mode": "suneung", "persona": "A_일반고고3"}


def test_stuck_shape() -> None:
    """`막힘`은 turn_count 필수 + mode·persona 선택."""
    data = build_event_data(EventType.막힘, turn_count=5)
    assert data == {"turn_count": 5, "mode": None, "persona": None}
    data_tagged = build_event_data(EventType.막힘, turn_count=7, mode="suneung")
    assert data_tagged == {"turn_count": 7, "mode": "suneung", "persona": None}


def test_response_latency_shape() -> None:
    """`답입력`은 server_latency_ms(기본 None) + mode·persona 선택."""
    assert build_event_data(EventType.답입력) == {
        "server_latency_ms": None,
        "mode": None,
        "persona": None,
    }
    data = build_event_data(EventType.답입력, server_latency_ms=1500, persona="A_일반고고3")
    assert data == {"server_latency_ms": 1500, "mode": None, "persona": "A_일반고고3"}


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (EventType.검산결과, {"passed": True, "bogus": 1}),
        (EventType.힌트제공, {"hint_level": 2, "extra": "x"}),
        (EventType.시각화조작, {"interaction": "p", "unknown": True}),
        (EventType.힌트요청, {"mode": "suneung", "bogus": 1}),
        (EventType.막힘, {"turn_count": 5, "extra": "x"}),
        (EventType.답입력, {"server_latency_ms": 100, "unknown": True}),
    ],
)
def test_stray_keys_rejected(event_type: EventType, payload: dict[str, object]) -> None:
    """계약에 없는 키는 produce 좌석에서 거부(extra='forbid') — 자유 JSONB 드리프트 차단."""
    with pytest.raises(ValidationError):
        build_event_data(event_type, **payload)


def test_type_coercion_enforced() -> None:
    """passed는 bool·hint_level은 int — 타입 강제(잘못된 타입 거부)."""
    with pytest.raises(ValidationError):
        build_event_data(EventType.힌트제공, hint_level="셋")  # 숫자 아님


def test_dormant_type_is_not_a_build_target() -> None:
    """휴면 EventType으로 build_event_data 호출은 오용 → KeyError(생산 경로 없어야 함).

    `막힘`은 S3-16으로 계약 대상이 됐으므로(위 test_stuck_shape) 휴면 예시로는 `지움`을 쓴다."""
    with pytest.raises(KeyError):
        build_event_data(EventType.지움, foo="bar")


class TestAttemptedEventContract:
    """`문제시도`(EOS-57) 계약 — 스킬 배열이 event_data로 새지 않는 경계를 못박는다."""

    def test_source_and_is_correct_are_required(self) -> None:
        """두 필드 모두 required — 경로 라벨 없는 기록은 경로별 분모를 만들 수 없다."""
        with pytest.raises(ValidationError):
            AttemptedEventData(is_correct=True)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            AttemptedEventData(source="attempt_submit")  # type: ignore[call-arg]

    def test_skill_ids_is_rejected_in_payload(self) -> None:
        """`skill_ids`는 event_data에 담기지 않는다 — 1급 컬럼이 정본 좌석이다.

        JSONB에 병기하면 두 진실원이 생기고("유지보수 지옥" 방어), 집계가 매번 JSON 파싱이
        된다. extra='forbid'가 그 유혹을 produce 좌석에서 구조적으로 차단한다.
        """
        with pytest.raises(ValidationError):
            build_event_data(
                EventType.문제시도,
                is_correct=True,
                source="attempt_submit",
                skill_ids=["skill.a"],
            )

    def test_build_event_data_round_trip(self) -> None:
        payload = build_event_data(EventType.문제시도, is_correct=False, source="coach_completion")
        assert payload == {"is_correct": False, "source": "coach_completion"}
