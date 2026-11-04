"""PED-51 — 학생 의도 섀도 수확기 회귀 테스트.

실물 표면: `fixtures/intent_shadow_records_v41_20261103.ndjson`는 2026-11-03 Phaiakes9에서 WhyMath main을
거쳐 laya v4.1이 남긴 실측 레코드 15건(레코드 v1·Windows CRLF·학생 원문 없음)이다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.api._intent_shadow import RECORD_SCHEMA_VERSION, IntentShadowObservation
from whymath_backend.harness import intent_shadow_harvest as h

_FIXTURE = Path(__file__).parent / "fixtures" / "intent_shadow_records_v41_20261103.ndjson"


def _rec(**over: Any) -> str:
    """emit 측 모델로 직렬화한 레코드 1줄 — 손으로 키를 쓰지 않는다."""
    base: dict[str, Any] = {
        "route": "append_turns",
        "rule_intent": "답시도",
        "has_solution": True,
        "laya_intent": "check",
        "laya_confidence": 0.95,
        "pii_prob": 0.01,
        "routed_model": "multilingual",
        "latency_ms": 300.0,
        "failure": None,
        "http_status": 200,
        "pii_rule": False,
        "pii_rule_kinds": [],
        "observed_at": "2026-11-05T01:00:00Z",
    }
    base.update(over)
    return IntentShadowObservation.model_validate(base).model_dump_json()


def _summ(*lines: str) -> h.IntentShadowHarvestSummary:
    recs, _ = h.parse_log_text("\n".join(lines))
    return h.summarize(recs)


# ── 실물 표면 ────────────────────────────────────────────────────────────


def test_real_phaiakes9_records_parse_and_agree_15_of_15() -> None:
    report = h.harvest_files([_FIXTURE])
    a, s = report.accounting, report.summary
    assert (a.parsed, a.skipped, a.broken) == (15, 0, 0)
    assert s.total == 15 and s.succeeded == 15 and s.working_ratio == 1.0
    assert s.cross_table == {"답시도": {"check": 15}}
    assert (s.agreement.agree, s.agreement.n) == (15, 15)
    assert s.agreement.wilson_lower is not None and 0.8 < s.agreement.wilson_lower < 1.0
    assert s.by_route == {"append_turns": 10, "create_session": 5}
    # 레코드 v1 — 규칙 필드 이전이라 '아님'이 아니라 '미기록'이다
    assert s.schema_versions == {"1": 15}
    assert s.pii_rule_unrecorded == 15 and s.pii_neither == 0
    assert s.latency_median_ms == 291.5


def test_crlf_and_bom_are_accepted() -> None:
    text = "﻿" + _rec() + "\r\n" + _rec() + "\r\n"
    recs, acc = h.parse_log_text(text)
    assert len(recs) == 2 and acc.broken == 0


# ── 회계 분리 ────────────────────────────────────────────────────────────


def test_accounting_separates_skipped_and_broken_with_type_names() -> None:
    lines = [
        _rec(),
        "INFO: Uvicorn running on http://0.0.0.0:8000",  # 평문 → skipped
        json.dumps({"other": "json"}),  # 다른 JSON → skipped
        '{"route": "append_turns", "questions_version": "questions_v1", "latency_ms": "x"',  # 절단
        json.dumps(
            {"route": "nope", "questions_version": "questions_v1", "latency_ms": 1}
        ),  # 스키마
    ]
    recs, acc = h.parse_log_text("\n".join(lines))
    assert len(recs) == 1
    assert (acc.parsed, acc.skipped, acc.broken) == (1, 2, 2)
    assert acc.broken_types == {"JSONDecodeError": 1, "ValidationError": 1}


def test_same_file_twice_is_counted_once(tmp_path: Path) -> None:
    p = tmp_path / "a.log"
    p.write_text(_rec() + "\n", encoding="utf-8")
    report = h.harvest_files([p, p])
    assert report.summary.total == 1 and report.accounting.duplicate_files == 1


# ── 작동 비율 · 일치도 ───────────────────────────────────────────────────


def test_failures_stay_in_the_denominator() -> None:
    s = _summ(
        _rec(),
        _rec(laya_intent=None, laya_confidence=None, pii_prob=None, failure="ConnectError"),
        _rec(laya_intent=None, laya_confidence=None, pii_prob=None, failure="Overloaded"),
    )
    assert (s.total, s.succeeded, s.working_ratio) == (3, 1, round(1 / 3, 4))
    assert s.failure_types == {"ConnectError": 1, "Overloaded": 1}
    assert s.agreement.n == 1  # 일치도는 성공 레코드만


def test_mapping_drives_agreement_and_cross_table() -> None:
    s = _summ(
        _rec(rule_intent="포기", laya_intent="answer_only"),  # 일치
        _rec(rule_intent="막힘표현", laya_intent="hint"),  # 일치(hint→막힘표현)
        _rec(rule_intent="이해확인", laya_intent="chitchat"),  # 일치
        _rec(rule_intent="이해확인", laya_intent="answer_only"),  # 불일치
    )
    assert (s.agreement.agree, s.agreement.n) == (3, 4)
    assert s.cross_table["이해확인"] == {"answer_only": 1, "chitchat": 1}
    assert (s.agreement_by_laya["answer_only"].agree, s.agreement_by_laya["answer_only"].n) == (
        1,
        2,
    )


def test_missing_rule_intent_is_excluded_and_counted() -> None:
    s = _summ(_rec(), _rec(rule_intent=None))
    assert s.no_rule_intent == 1 and s.agreement.n == 1


def test_confidence_bins_include_upper_edge_and_split_has_solution() -> None:
    s = _summ(
        _rec(laya_confidence=1.0),
        _rec(laya_confidence=0.5),
        _rec(laya_confidence=0.49, has_solution=False, rule_intent="이해확인"),
    )
    assert s.agreement_by_confidence["[0.9,1.0]"].n == 1
    assert s.agreement_by_confidence["[0.5,0.7)"].n == 1
    assert s.agreement_by_confidence["[0.0,0.5)"].n == 1
    assert s.agreement_by_has_solution["발화만"].n == 1


def test_empty_group_reports_none_not_zero() -> None:
    c = h._rate(0, 0)
    assert c.rate is None and c.wilson_lower is None


# ── 개인정보 겹침 ────────────────────────────────────────────────────────


def test_pii_two_by_two_and_unknown_rule_is_not_negative() -> None:
    s = _summ(
        _rec(pii_prob=0.9, pii_rule=True, pii_rule_kinds=["address"]),  # 둘 다
        _rec(pii_prob=0.9, pii_rule=False),  # laya만
        _rec(
            pii_prob=0.1, pii_rule=True, pii_rule_kinds=["phone"]
        ),  # 규칙만 — OR 정책이 더 잡는 몫
        _rec(pii_prob=0.1, pii_rule=False),  # 둘 다 아님
        _rec(pii_prob=0.1, pii_rule=None),  # 규칙 판정 실패 → 미기록
        _rec(pii_prob=0.5, pii_rule=False),  # 경계 0.5는 laya 양성
        _rec(pii_prob=0.5, pii_rule=True, pii_rule_kinds=["email"]),  # 경계 0.5 + 규칙 = 둘 다
    )
    assert (s.pii_both, s.pii_laya_only, s.pii_rule_only, s.pii_neither) == (2, 2, 1, 1)
    assert s.pii_rule_unrecorded == 1
    assert s.pii_rule_kinds == {"address": 1, "email": 1, "phone": 1}


def test_record_schema_is_v2_or_later() -> None:
    """PED-50 필드에 기대는 집계 — emit 측 버전이 내려가면 겹침 계산의 전제가 깨진다."""
    assert RECORD_SCHEMA_VERSION >= 2


# ── 구간 · CLI ───────────────────────────────────────────────────────────


def test_window_filter_is_inclusive_and_counts_outside() -> None:
    recs, _ = h.parse_log_text(
        "\n".join(
            _rec(observed_at=t)
            for t in ("2026-11-03T07:00:00Z", "2026-11-04T00:00:00Z", "2026-11-05T00:00:00Z")
        )
    )
    kept, outside = h.filter_window(
        recs,
        since=datetime(2026, 11, 4, tzinfo=timezone.utc),
        until=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    assert len(kept) == 2 and outside == 1


def test_cli_writes_json_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.json"
    assert h.main([str(_FIXTURE), "--json", str(out)]) == h.EXIT_OK
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["agreement"]["agree"] == 15
    assert "판정선 없음" in capsys.readouterr().out


def test_cli_empty_scan_is_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = tmp_path / "empty.log"
    p.write_text("INFO: nothing here\n", encoding="utf-8")
    assert h.main([str(p)]) == h.EXIT_INPUT_ERROR
    assert "HARVEST_EMPTY=True" in capsys.readouterr().out


def test_cli_window_excluding_everything_is_failure() -> None:
    assert h.main([str(_FIXTURE), "--since", "2027-01-01T00:00:00Z"]) == h.EXIT_INPUT_ERROR


def test_cli_missing_file_is_input_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert h.main([str(tmp_path / "nope.log")]) == h.EXIT_INPUT_ERROR
    assert "FileNotFoundError" in capsys.readouterr().out
