"""외부 업타임 프로브 단위테스트 — hermetic(네트워크 0)·OPS-30 ②.

동결하는 것
-----------
1. **판정은 실제 응답뿐** — up = HTTP 200 + body `ready=true`(+우리 body 모양). 연결 거부·타임아웃·503·
   JSON 아님·`ready` 아님은 전부 down이고, 사유엔 타입명/`HTTP<코드>`/`BadBody`만 남는다.
2. **정상은 조용, 전이만 알린다** — up→down 1건, down→up 1건. 알림 실패·미설정은 기록(`unsent`)에
   남아 다음 폴링에서 재시도된다(알림 1건 유실 = 아무도 모름 방지).
3. **S4는 표본이 모자라면 판정하지 않는다** — 빈 로그·낮은 coverage는 `insufficient`(통과 아님),
   창 밖(KST 15:00 미만/24:00 이후) 표본은 버린다. 경계(14:59/15:00/23:59/00:00)를 전부 건드린다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from whymath_backend.ops import uptime_probe as up

_URL = "http://127.0.0.1:8000/health/ready"
_HOOK = "https://hooks.example.test/services/T000/B000/SECRETTOKEN"
_T0 = datetime(2026, 10, 5, 7, 0, 0, tzinfo=UTC)  # = 2026-10-05 16:00 KST (창 안)


def _ready_body(ready: bool = True) -> dict[str, Any]:
    return {"ready": ready, "components": {"database": {}}, "alerts": [{"metric": "m"}]}


def _patch_get(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> None:
    def fake_get(url: str, *, timeout: float) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(httpx, "get", fake_get)


# ── poll_once: 판정 ────────────────────────────────────────────────────────
def test_poll_up(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, httpx.Response(200, json=_ready_body()))
    rec = up.poll_once(_URL, timeout_s=1, now=_T0)
    assert rec["ok"] is True
    assert (rec["status"], rec["ready"], rec["alerts"], rec["error"]) == (200, True, 1, None)
    assert rec["ts"] == "2026-10-05T07:00:00Z"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503, json=_ready_body(False)), "HTTP503"),
        (httpx.Response(500, text="oops"), "HTTP500"),
        (httpx.Response(404, json={"detail": "nf"}), "HTTP404"),
        (httpx.Response(200, text="<html>다른 서버</html>"), "BadBody"),  # JSON 아님
        (httpx.Response(200, json={"status": "ok"}), "BadBody"),  # /health/live 모양 — 간접 신호
        (httpx.Response(200, json=_ready_body(False)), "BadBody"),  # 200인데 ready 아님
        # 다른 프로세스가 {"ready": true}만 흉내내 포트를 점유한 경우 — components 없는 body는 우리 것이 아니다
        (httpx.Response(200, json={"ready": True}), "BadBody"),
        (httpx.Response(200, json=["x"]), "BadBody"),
        (httpx.ConnectError("refused"), "ConnectError"),
        (httpx.ReadTimeout("slow"), "ReadTimeout"),
    ],
)
def test_poll_down_variants_use_type_or_code_labels(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception, error: str
) -> None:
    _patch_get(monkeypatch, response)
    rec = up.poll_once(_URL, timeout_s=1, now=_T0)
    assert rec["ok"] is False
    assert rec["error"] == error


def test_poll_record_never_contains_body_or_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_get(monkeypatch, httpx.Response(503, text="DSN=postgres://user:pw@host/db"))
    rec = json.dumps(up.poll_once(_URL, timeout_s=1, now=_T0), ensure_ascii=False)
    assert "postgres" not in rec
    assert "127.0.0.1" not in rec


# ── decide_notice 진리표 ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("prev", "ok_now", "expected"),
    [
        (None, True, None),  # 첫 기록이 정상 — 조용
        (None, False, up.NOTICE_DOWN),  # 첫 기록이 다운 — 알림
        ({"ok": True, "unsent": None}, True, None),  # 정상 지속 — 조용
        ({"ok": True, "unsent": None}, False, up.NOTICE_DOWN),  # up→down
        ({"ok": False, "unsent": None}, False, None),  # 다운 지속 — 조용(스팸 방지)
        ({"ok": False, "unsent": "down"}, False, up.NOTICE_DOWN),  # 다운 알림 유실 → 재시도
        ({"ok": False, "unsent": None}, True, up.NOTICE_UP),  # down→up
        ({"ok": False, "unsent": "down"}, True, up.NOTICE_UP),  # 유실된 채 복구 → 복구 알림
        ({"ok": True, "unsent": "up"}, True, up.NOTICE_UP),  # 복구 알림 유실 → 재시도
        ({"ok": True, "unsent": "up"}, False, up.NOTICE_DOWN),  # 재다운
    ],
)
def test_decide_notice_truth_table(
    prev: dict[str, Any] | None, ok_now: bool, expected: str | None
) -> None:
    assert up.decide_notice(prev, ok_now=ok_now) == expected


# ── run_probe: 시퀀스 ──────────────────────────────────────────────────────
class _Sender:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.sent: list[str] = []

    def __call__(self, url: str, text: str, *, timeout_s: float) -> str | None:
        self.sent.append(text)
        return self.error


def _run(
    log: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response | Exception,
    minute: int,
    sender: _Sender,
    webhook: str = _HOOK,
) -> dict[str, Any]:
    _patch_get(monkeypatch, response)
    return up.run_probe(
        url=_URL,
        log_path=log,
        timeout_s=1,
        webhook_url=webhook,
        now=_T0 + timedelta(minutes=minute),
        sender=sender,
    )


_OK = httpx.Response(200, json=_ready_body())
_DOWN = httpx.ConnectError("refused")


def test_up_up_up_is_silent_and_appends_one_line_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "u.jsonl"
    sender = _Sender()
    for m in range(3):
        rec = _run(log, monkeypatch, _OK, m, sender)
        assert rec["notice"] is None
    assert sender.sent == []
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3


def test_down_then_still_down_alerts_once_then_recovery_alerts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "u.jsonl"
    sender = _Sender()
    _run(log, monkeypatch, _OK, 0, sender)
    first = _run(log, monkeypatch, _DOWN, 1, sender)
    _run(log, monkeypatch, _DOWN, 2, sender)
    _run(log, monkeypatch, _DOWN, 3, sender)
    assert first["notice"] == "down:sent"
    assert len(sender.sent) == 1
    assert "서버 다운" in sender.sent[0]
    assert "ConnectError" in sender.sent[0]

    rec = _run(log, monkeypatch, _OK, 4, sender)
    assert rec["notice"] == "up:sent"
    assert len(sender.sent) == 2
    assert "복구" in sender.sent[1]
    assert "다운 시작 2026-10-05T07:01:00Z" in sender.sent[1]  # 다운 구간의 첫 기록 시각

    _run(log, monkeypatch, _OK, 5, sender)  # 복구 후 정상 — 다시 조용
    assert len(sender.sent) == 2


def test_failed_delivery_is_recorded_and_retried_until_it_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "u.jsonl"
    broken = _Sender("ConnectError")
    r1 = _run(log, monkeypatch, _DOWN, 0, broken)
    r2 = _run(log, monkeypatch, _DOWN, 1, broken)
    assert (r1["notice"], r1["unsent"]) == ("down:failed:ConnectError", "down")
    assert (r2["notice"], r2["unsent"]) == ("down:failed:ConnectError", "down")  # 재시도했다
    assert len(broken.sent) == 2

    healthy = _Sender()
    r3 = _run(log, monkeypatch, _DOWN, 2, healthy)
    r4 = _run(log, monkeypatch, _DOWN, 3, healthy)
    assert (r3["notice"], r3["unsent"]) == ("down:sent", None)
    assert r4["notice"] is None  # 도달한 뒤엔 다시 조용
    assert len(healthy.sent) == 1


@pytest.mark.parametrize(("webhook", "outcome"), [("", "unset"), ("not-a-url", "invalid")])
def test_unconfigured_webhook_is_recorded_not_silently_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, webhook: str, outcome: str
) -> None:
    log = tmp_path / "u.jsonl"
    sender = _Sender()
    rec = _run(log, monkeypatch, _DOWN, 0, sender, webhook=webhook)
    assert sender.sent == []  # 보내지 않았다
    assert rec["notice"] == f"down:{outcome}"  # 그러나 "못 보냈다"가 기록에 남는다
    assert rec["unsent"] == "down"


def test_record_survives_a_sender_that_returns_failure_and_log_is_valid_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "sub" / "dir" / "u.jsonl"  # 상위 디렉터리 없음 → 생성
    _run(log, monkeypatch, _DOWN, 0, _Sender("HTTP500"))
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["error"] == "ConnectError"


# ── channel 기록 · test-notify ─────────────────────────────────────────────
@pytest.mark.parametrize(
    ("webhook", "channel"), [(_HOOK, "configured"), ("", "unset"), ("not-a-url", "invalid")]
)
def test_every_record_carries_channel_state_even_when_nothing_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, webhook: str, channel: str
) -> None:
    # 정상(알림 없음) 폴링에서도 채널 상태가 남는다 — 스케줄러 환경의 env 상속 실패를 평상시에 본다.
    rec = _run(tmp_path / "u.jsonl", monkeypatch, _OK, 0, _Sender(), webhook=webhook)
    assert rec["notice"] is None
    assert rec["channel"] == channel


def test_test_notify_success_failure_and_unconfigured(capsys: pytest.CaptureFixture[str]) -> None:
    ok, bad = _Sender(), _Sender("HTTP403")
    assert up.run_test_notify(_HOOK, timeout_s=1, sender=ok) == 0
    assert len(ok.sent) == 1
    assert up.run_test_notify(_HOOK, timeout_s=1, sender=bad) == 1
    assert "HTTP403" in capsys.readouterr().out
    never = _Sender()
    assert up.run_test_notify("", timeout_s=1, sender=never) == 1
    assert up.run_test_notify("not-a-url", timeout_s=1, sender=never) == 1
    assert never.sent == []  # 미설정이면 발송 시도 자체를 하지 않는다


def test_test_notify_output_never_contains_the_url(capsys: pytest.CaptureFixture[str]) -> None:
    up.run_test_notify(_HOOK, timeout_s=1, sender=_Sender("ConnectError"))
    up.run_test_notify(_HOOK, timeout_s=1, sender=_Sender())
    assert "SECRETTOKEN" not in capsys.readouterr().out


def test_cli_test_notify_reports_unset_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", raising=False)
    assert up.main(["test-notify"]) == 1
    assert "unset" in capsys.readouterr().out


# ── read_tail / read_all ───────────────────────────────────────────────────
def test_read_tail_missing_file_is_empty(tmp_path: Path) -> None:
    assert up.read_tail(tmp_path / "none.jsonl") == []
    assert up.read_all(tmp_path / "none.jsonl") == []


def test_read_skips_corrupt_and_foreign_lines(tmp_path: Path) -> None:
    log = tmp_path / "u.jsonl"
    good = {"ts": "2026-10-05T07:00:00Z", "ok": True}
    log.write_text(
        json.dumps(good) + "\n" + '{"ts": "2026-10-05T07:01:0' + "\n" + '["list"]\n{"x":1}\n',
        encoding="utf-8",
    )
    assert up.read_tail(log) == [good]
    assert up.read_all(log) == [good]


def test_read_tail_only_reads_the_end_of_a_large_file(tmp_path: Path) -> None:
    log = tmp_path / "u.jsonl"
    rows = [
        json.dumps({"ts": f"2026-10-05T07:{i % 60:02d}:00Z", "ok": i % 2 == 0, "n": i})
        for i in range(20000)
    ]
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert log.stat().st_size > up._TAIL_BYTES
    tail = up.read_tail(log)
    assert 0 < len(tail) < 20000
    assert tail[-1]["n"] == 19999  # 마지막 기록은 반드시 보인다(직전 상태 판정의 근거)
    assert all(isinstance(r, dict) and "n" in r for r in tail)  # 잘린 첫 줄은 버려졌다


# ── S4 계산 ────────────────────────────────────────────────────────────────
# 창: 매일 15:00–24:00 KST = 06:00Z–15:00Z. 하루치 기대 표본 = 9h × 60 = 540 (간격 60초).
_DAY_START = datetime(2026, 10, 4, 15, 0, tzinfo=UTC)  # 2026-10-05 00:00 KST
_DAY_END = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)  # 2026-10-06 00:00 KST


def _samples(
    start_utc: datetime, count: int, *, down_every: int | None = None
) -> list[dict[str, Any]]:
    out = []
    for i in range(count):
        ts = (start_utc + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ok = not (down_every and i % down_every == 0)
        out.append({"ts": ts, "ok": ok})
    return out


def _s4(records: list[dict[str, Any]]) -> up.S4Report:
    return up.compute_s4(records, since=_DAY_START, until=_DAY_END, interval_seconds=60.0)


def test_s4_contract_constants() -> None:
    assert up.S4_AVAILABILITY_TARGET == 0.99
    assert (up.S4_WINDOW_START_KST_HOUR, up.S4_WINDOW_END_KST_HOUR) == (15, 24)


def test_s4_full_window_all_up_passes() -> None:
    report = _s4(_samples(datetime(2026, 10, 5, 6, 0, tzinfo=UTC), 540))
    assert report.expected_samples == 540
    assert (report.samples, report.ok_samples) == (540, 540)
    assert report.coverage == 1.0
    assert report.availability_observed == 1.0
    assert report.verdict == "pass"


def test_s4_below_target_fails_at_the_boundary() -> None:
    start = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
    # 540개 중 6개 down = 534/540 = 98.89% < 99% → fail
    bad = _samples(start, 540)
    for i in range(6):
        bad[i]["ok"] = False
    assert _s4(bad).verdict == "fail"
    # 540개 중 5개 down = 535/540 = 99.07% ≥ 99% → pass
    ok = _samples(start, 540)
    for i in range(5):
        ok[i]["ok"] = False
    assert _s4(ok).verdict == "pass"


def test_s4_empty_log_is_insufficient_not_pass() -> None:
    report = _s4([])
    assert report.verdict == "insufficient"
    assert report.availability_observed is None  # 0.0도 1.0도 아닌 '미측정'
    assert report.coverage == 0.0


def test_s4_low_coverage_is_insufficient_even_if_every_sample_is_up() -> None:
    # 스케줄러가 대부분 죽어 있었다: 540 중 100개만 있고 전부 up → 99% 같은 숫자가 나와도 판정 불가
    report = _s4(_samples(datetime(2026, 10, 5, 6, 0, tzinfo=UTC), 100))
    assert report.availability_observed == 1.0
    assert report.availability_lower_bound == pytest.approx(100 / 540)
    assert report.verdict == "insufficient"


def test_s4_coverage_threshold_boundary() -> None:
    start = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)
    assert _s4(_samples(start, 486)).verdict == "pass"  # 486/540 = 0.90 (경계 포함)
    assert _s4(_samples(start, 485)).verdict == "insufficient"


def test_s4_lower_bound_counts_missing_samples_as_down() -> None:
    report = _s4(_samples(datetime(2026, 10, 5, 6, 0, tzinfo=UTC), 500))
    assert report.availability_observed == 1.0
    assert report.availability_lower_bound == pytest.approx(500 / 540)
    assert report.verdict == "pass"  # coverage 92.6% ≥ 90%


def test_s4_window_edges_in_kst() -> None:
    def rec(ts: str) -> dict[str, Any]:
        return {"ts": ts, "ok": True}

    rows = [
        rec("2026-10-05T05:59:00Z"),  # 14:59 KST — 창 밖
        rec("2026-10-05T06:00:00Z"),  # 15:00 KST — 창 안(시작 포함)
        rec("2026-10-05T14:59:00Z"),  # 23:59 KST — 창 안
        rec("2026-10-05T15:00:00Z"),  # 24:00 KST = 다음날 00:00 — 창 밖(+ until 밖)
        rec("2026-10-04T20:00:00Z"),  # 05:00 KST — 창 밖
    ]
    assert _s4(rows).samples == 2


def test_s4_out_of_range_and_garbage_rows_are_ignored() -> None:
    rows = [
        {"ts": "2026-09-01T07:00:00Z", "ok": True},  # 기간 밖
        {"ts": "garbage", "ok": True},
        {"ts": None, "ok": True},
        {"ts": "2026-10-05T07:00:00Z", "ok": "yes"},  # ok가 True가 아니면 down으로 센다
    ]
    report = _s4(rows)
    assert (report.samples, report.ok_samples) == (1, 0)


def test_s4_expected_samples_for_partial_and_multi_day_ranges() -> None:
    # 시작이 창 중간(18:00 KST)이면 그날은 6시간치만 기대한다.
    partial = up.compute_s4(
        [],
        since=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),  # 18:00 KST
        until=_DAY_END,
        interval_seconds=60.0,
    )
    assert partial.expected_samples == 6 * 60
    # 3일 = 3창
    three = up.compute_s4(
        [],
        since=_DAY_START,
        until=_DAY_START + timedelta(days=3),
        interval_seconds=60.0,
    )
    assert three.expected_samples == 3 * 540
    # 창 밖 구간만 — 기대 0 → coverage 미측정
    off = up.compute_s4(
        [],
        since=datetime(2026, 10, 4, 15, 0, tzinfo=UTC),
        until=datetime(2026, 10, 5, 5, 0, tzinfo=UTC),  # 00:00–14:00 KST
        interval_seconds=60.0,
    )
    assert off.expected_samples == 0
    assert off.coverage is None
    assert off.verdict == "insufficient"


def test_format_s4_says_unmeasured_not_zero() -> None:
    text = up.format_s4(_s4([]))
    assert "INSUFFICIENT" in text
    observed_row = next(line for line in text.splitlines() if "가용성(관측)" in line)
    assert "미측정" in observed_row  # 표본 0의 관측 가용성은 0%가 아니라 '미측정'이다
    assert "0.0000%" not in observed_row


# ── CLI ────────────────────────────────────────────────────────────────────
def test_cli_probe_exit_code_follows_up_down_and_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "u.jsonl"
    monkeypatch.delenv("WHYMATH_OPS_ALERT_WEBHOOK_URL", raising=False)
    argv = ["probe", "--url", _URL, "--log", str(log)]
    _patch_get(monkeypatch, _OK)
    assert up.main(argv) == 0
    _patch_get(monkeypatch, _DOWN)
    assert up.main(argv) == 1
    out = capsys.readouterr().out
    assert '"notice": "down:unset"' in out  # 채널 없음이 출력에도 드러난다
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


def test_cli_report_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "none.jsonl"
    assert up.main(["report", "--log", str(missing), "--days", "7"]) == 1  # 표본 0 = 통과 아님
    assert "INSUFFICIENT" in capsys.readouterr().out


def test_cli_rejects_bad_numbers(tmp_path: Path) -> None:
    log = str(tmp_path / "u.jsonl")
    assert up.main(["probe", "--log", log, "--timeout", "0"]) == 2
    assert up.main(["report", "--log", log, "--days", "0"]) == 2
    assert up.main(["report", "--log", log, "--interval-seconds", "0"]) == 2
