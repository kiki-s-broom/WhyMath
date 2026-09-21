"""분석 이벤트 envelope 계약 — 멱등성·시간 의미·PII allowlist 경계."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from whymath_backend.schema.analytics_event import (
    AnalyticsEventEnvelope,
    AnalyticsEventSource,
    build_analytics_event_envelope,
)
from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import EVENT_DATA_CONTRACT

# tests/backend/schema/ 에서 저장소 루트까지 3단계 상위.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _valid_kwargs() -> dict[str, object]:
    return {
        "event_uuid": uuid4(),
        "occurred_at": datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        "received_at": datetime(2026, 8, 2, 10, 0, 1, tzinfo=timezone.utc),
        "source": AnalyticsEventSource.BACKEND,
        "event_type": EventType.힌트제공,
        "payload": {"hint_level": 2},
    }


def test_envelope_preserves_idempotency_and_timestamp_meaning() -> None:
    envelope = AnalyticsEventEnvelope(**_valid_kwargs())

    assert envelope.schema_version == 1
    assert envelope.event_uuid is not None
    assert envelope.occurred_at < envelope.received_at
    # 기존 event_data 계약은 선택 필드를 None으로 명시해 정규화한다.
    assert envelope.payload["hint_level"] == 2
    assert envelope.payload["mode"] is None
    assert envelope.payload["persona"] is None


def test_envelope_rejects_unknown_top_level_fields() -> None:
    with pytest.raises(ValidationError):
        AnalyticsEventEnvelope(**_valid_kwargs(), device_id="permanent-device")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "chat_text",
        "student_answer",
        "solution_latex",
        "image",
        "url_query",
        "x_coordinate",
        "device_id",
    ],
)
def test_envelope_rejects_forbidden_pii_payload_keys(forbidden_key: str) -> None:
    kwargs = _valid_kwargs()
    kwargs["payload"] = {"hint_level": 2, forbidden_key: "sensitive"}

    with pytest.raises(ValidationError, match="금지"):
        AnalyticsEventEnvelope(**kwargs)


def test_envelope_rejects_payload_key_not_allowlisted_for_event_type() -> None:
    kwargs = _valid_kwargs()
    kwargs["payload"] = {"hint_level": 2, "unexpected": True}

    with pytest.raises(ValidationError, match="allowlist"):
        AnalyticsEventEnvelope(**kwargs)


def test_builder_normalizes_allowed_payload() -> None:
    envelope = build_analytics_event_envelope(
        event_uuid=uuid4(),
        occurred_at=datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 8, 2, 10, 0, 1, tzinfo=timezone.utc),
        source=AnalyticsEventSource.BACKEND,
        event_type=EventType.검산결과,
        payload={"passed": True},
    )

    assert envelope.payload["passed"] is True
    assert envelope.payload["error_kind"] is None
    assert envelope.event_type == EventType.검산결과


def test_mobile_event_requires_session_id() -> None:
    kwargs = _valid_kwargs()
    kwargs["source"] = AnalyticsEventSource.MOBILE

    with pytest.raises(ValidationError, match="session_id"):
        AnalyticsEventEnvelope(**kwargs)


def test_received_at_before_occurred_at_rejected() -> None:
    kwargs = _valid_kwargs()
    kwargs["received_at"] = datetime(2026, 8, 2, 9, 59, tzinfo=timezone.utc)

    with pytest.raises(ValidationError, match="received_at"):
        AnalyticsEventEnvelope(**kwargs)


def _pii_grade_table_event_types() -> set[str]:
    """개인정보 정책 문서의 'PII 등급' 표에서 첫 열의 EventType 값을 뽑는다.

    문자열 금지 목록이 아니라 *구성된 산출물*(실제 표의 행)을 읽는다 — 표기를 바꿔도
    행이 없으면 없는 것으로 잡히게 하기 위해서다.
    """
    doc = _REPO_ROOT / "docs" / "data" / "analytics_event_privacy_policy.md"
    # 문서 부재는 skip이 아니라 실패다 — 정책 문서가 사라지면 계약도 무효다.
    assert doc.is_file(), f"개인정보 정책 문서 부재: {doc}"
    lines = doc.read_text(encoding="utf-8").splitlines()

    try:
        start = next(
            i for i, ln in enumerate(lines) if ln.startswith("## 현재 생산 이벤트의 PII 등급")
        )
    except StopIteration:  # pragma: no cover - 표 제목이 바뀌면 즉시 드러나야 한다
        raise AssertionError("'현재 생산 이벤트의 PII 등급' 절을 찾지 못했다") from None

    found: set[str] = set()
    for line in lines[start + 1 :]:
        if line.startswith("## "):  # 다음 절로 넘어가면 표 끝
            break
        m = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if m:
            found.add(m.group(1))
    # 전수 가드가 0건을 훑고 공허하게 통과하는 것을 막는다.
    assert found, "등급표에서 EventType 행을 한 건도 파싱하지 못했다 — 표 형식이 바뀌었는가"
    return found


def test_pii_policy_covers_all_produced_event_types() -> None:
    """생산 계약(EVENT_DATA_CONTRACT)에 있는 EventType은 전부 PII 등급표에 행이 있어야 한다.

    등재 이유: v1 문서(2026-08-14)가 3종만 담은 사이 생산 좌석이 7종으로 늘었는데
    (S3-16 막힘·힌트요청·답입력 · EOS-57 문제시도) 한 달간 어떤 검사도 그 드리프트를
    지적하지 못했다. 등급 미상 payload가 분석 저장으로 흘러가는 것을 막는 가드다.
    """
    documented = _pii_grade_table_event_types()
    produced = {et.value for et in EVENT_DATA_CONTRACT}

    missing = produced - documented
    assert not missing, (
        f"생산 EventType {sorted(missing)}의 PII 등급이 문서화되지 않았다 — "
        f"docs/data/analytics_event_privacy_policy.md의 등급표에 행을 추가하라"
    )
