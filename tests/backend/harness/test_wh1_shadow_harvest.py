"""wh1_shadow_harvest 수확·축적기 hermetic 테스트 — 라이브 0·파일은 tmp_path.

픽스처 라인은 emit 실물에서 도출한다: 레코드 페이로드는 실제 `Wh1HarnessShadowObservation.
model_dump_json()`이고, 서버-로그 스타일 라인은 실제 `record_logger`(wh1_shadow.py의 그
로거)에 표준 Formatter를 태워 만든다 — 가짜 포맷 픽스처 금지(외부 표면 시임 검증 금지 규칙의
내부 판, 로거 이름·직렬화 드리프트를 테스트가 동결).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pytest

from whymath_backend.harness import wh1_shadow_harvest as hv
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation, record_logger


def _obs(
    verdict: str | None,
    *,
    status: str = "ended",
    action: str | None = "질문",
    dialogue: str | None = "d-1",
    turn: int = 1,
    observed: str = "2026-07-17T09:00:00+00:00",
    counts: tuple[int, int, int] | None = None,
) -> Wh1HarnessShadowObservation:
    """관측 픽스처 — emit 측 실물 모델로 구성(스키마 드리프트 시 여기서 즉시 깨진다).

    `counts`=(n_correct, n_incorrect, n_unverifiable)는 전이별 카운트(S3-07·신판). 기본 None은
    카운트 미기록(구판 의미) — 전이별 집계에서 legacy로 분리 회계되는 쪽이다.
    """
    return Wh1HarnessShadowObservation(
        status=status,
        action_type=action,
        verify_verdict=verdict,
        n_correct=counts[0] if counts is not None else None,
        n_incorrect=counts[1] if counts is not None else None,
        n_unverifiable=counts[2] if counts is not None else None,
        tool_calls=3,
        hypothesis_count=1,
        dialogue_id=dialogue,
        turn_index=turn,
        problem_id=None,
        observed_at=datetime.fromisoformat(observed),
    )


def _server_log_line(obs: Wh1HarnessShadowObservation) -> str:
    """실제 record_logger에 표준 Formatter를 태워 서버-로그 스타일 라인 생성(emit 표면 실측)."""
    record = record_logger.makeRecord(
        record_logger.name, logging.INFO, __file__, 0, obs.model_dump_json(), (), None
    )
    return logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s").format(record)


# ──────────────────────────────────────────────────────────────────────────
# 로거 이름 — emit 측과 파서의 단일 진실원천 동결
# ──────────────────────────────────────────────────────────────────────────
def test_record_logger_name_matches_emitter() -> None:
    """파서가 필터하는 로거 이름 = emit 로거 이름(재타이핑 드리프트 차단)."""
    assert hv.RECORD_LOGGER_NAME == record_logger.name
    assert hv.RECORD_LOGGER_NAME == "whymath.harness.wh1_shadow.record"


# ──────────────────────────────────────────────────────────────────────────
# parse_log_text — verdict 3종+None·깨진 JSON·비해당 라인 정직 회계
# ──────────────────────────────────────────────────────────────────────────
def test_parse_mixed_server_log_accounting(caplog: pytest.LogCaptureFixture) -> None:
    """서버-로그 스타일 + 순수 JSONL 혼재 입력에서 record만 파싱하고 skip/broken을 회계한다."""
    good = [
        _obs("correct", observed="2026-07-17T09:00:01+00:00"),
        _obs("incorrect", observed="2026-07-17T09:00:02+00:00"),
        _obs("unverifiable", observed="2026-07-17T09:00:03+00:00"),
        _obs(None, observed="2026-07-17T09:00:04+00:00"),
    ]
    lines = [
        _server_log_line(good[0]),  # 서버-로그 스타일(마커 + prefix)
        _server_log_line(good[1]),
        good[2].model_dump_json(),  # 순수 JSONL 캡처 스타일(bare JSON)
        good[3].model_dump_json(),
        # 깨진 record 라인 — 마커는 있으나 JSON 절단(로테이션 컷 모사).
        _server_log_line(good[0])[:-20],
        # 비해당 라인들 — uvicorn 평문·타 로거 JSON·타 스키마 bare JSON.
        'INFO:     127.0.0.1:5000 - "POST /v1/coach/sessions HTTP/1.1" 201 Created',
        '2026-07-17 INFO whymath.l4.misconception.shadow.record {"substr_ids": []}',
        '{"other_logger": true, "not_our_schema": 1}',
        "",  # 빈 줄 — 회계 제외
    ]
    with caplog.at_level(logging.WARNING, logger=hv.logger.name):
        observations, acct = hv.parse_log_text("\n".join(lines))
    assert acct.parsed == 4
    assert [o.verify_verdict for o in observations] == [
        "correct",
        "incorrect",
        "unverifiable",
        None,
    ]
    # 비해당: 평문 1 + 타 스키마 bare JSON 1. 타 로거 마커 라인은 marker 미포함(다른 이름)이라
    # bare JSON도 아니고 평문 취급 → skip. 총 3.
    assert acct.skipped == 3
    assert acct.broken == 1
    assert acct.lines_total == 8  # 빈 줄 제외
    # 침묵 실패 금지 — 깨진 라인 경고에 예외 *타입명*이 실려야 한다.
    warnings = [r.getMessage() for r in caplog.records]
    assert any("ValidationError" in m or "JSONDecodeError" in m for m in warnings)


def test_parse_broken_bare_json_is_broken(caplog: pytest.LogCaptureFixture) -> None:
    """bare JSON 절단(로테이션 컷)은 skip이 아니라 broken — 부식을 조용히 덮지 않는다."""
    truncated = _obs("correct").model_dump_json()[:-5]
    with caplog.at_level(logging.WARNING, logger=hv.logger.name):
        observations, acct = hv.parse_log_text(truncated)
    assert observations == []
    assert acct.broken == 1
    assert acct.skipped == 0
    assert any("JSONDecodeError" in r.getMessage() for r in caplog.records)


# ──────────────────────────────────────────────────────────────────────────
# dedupe — (dialogue_id, turn_index, observed_at) 키
# ──────────────────────────────────────────────────────────────────────────
def test_dedupe_key_and_counts() -> None:
    """같은 키는 1건만 남고 중복 수가 회계된다. observed_at·turn이 다르면 별건이다."""
    a1 = _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:00+00:00")
    a1_dup = _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:00+00:00")
    a2 = _obs("correct", dialogue="d-1", turn=2, observed="2026-07-17T09:00:00+00:00")
    b1 = _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:05+00:00")
    unique, duplicates = hv.dedupe([a1, a1_dup, a2, b1])
    assert len(unique) == 3
    assert duplicates == 1
    # create_session 관측(dialogue_id=None·turn=1)은 observed_at으로 구분된다.
    n1 = _obs("correct", dialogue=None, observed="2026-07-17T09:01:00+00:00")
    n2 = _obs("correct", dialogue=None, observed="2026-07-17T09:01:01+00:00")
    unique2, duplicates2 = hv.dedupe([n1, n2])
    assert len(unique2) == 2 and duplicates2 == 0


# ──────────────────────────────────────────────────────────────────────────
# summarize — verdict/status/turn 분포·고유 dialogue·시각 범위
# ──────────────────────────────────────────────────────────────────────────
def test_summarize_distribution() -> None:
    """4-라벨 분포(0건 라벨 포함)·비율·turn별 분포·status·dialogue·시각 범위."""
    observations = [
        _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:00+00:00"),
        _obs("correct", dialogue="d-1", turn=2, observed="2026-07-17T09:00:10+00:00"),
        _obs("incorrect", dialogue="d-2", turn=2, observed="2026-07-17T09:00:20+00:00"),
        _obs(
            None,
            dialogue=None,
            turn=1,
            observed="2026-07-17T09:00:30+00:00",
            status="budget_exhausted",
            action=None,
        ),
    ]
    summary = hv.summarize(observations)
    assert summary.total == 4
    assert summary.verdict_counts == {"correct": 2, "incorrect": 1, "unverifiable": 0, "none": 1}
    assert summary.verdict_ratios["correct"] == pytest.approx(0.5)
    assert summary.verdict_ratios["unverifiable"] == pytest.approx(0.0)
    assert summary.status_counts == {"budget_exhausted": 1, "ended": 3}
    assert summary.turn_verdicts == {
        1: {"correct": 1, "none": 1},
        2: {"correct": 1, "incorrect": 1},
    }
    assert summary.distinct_dialogues == 2  # None은 고유 dialogue로 세지 않는다
    assert summary.observed_at_min is not None and summary.observed_at_min.second == 0
    assert summary.observed_at_max is not None and summary.observed_at_max.second == 30


def test_summarize_empty_is_honest() -> None:
    """관측 0건 — 비율은 빈 dict(0%로 위장 금지)·시각 범위 None."""
    summary = hv.summarize([])
    assert summary.total == 0
    assert summary.verdict_ratios == {}
    assert summary.verdict_counts == {"correct": 0, "incorrect": 0, "unverifiable": 0, "none": 0}
    assert summary.observed_at_min is None and summary.observed_at_max is None


# ──────────────────────────────────────────────────────────────────────────
# harvest_files + --store 원장 — 축적·중복 제거·재실행 멱등
# ──────────────────────────────────────────────────────────────────────────
def _write_log(path: Path, observations: list[Wh1HarnessShadowObservation]) -> None:
    path.write_text("\n".join(_server_log_line(o) for o in observations) + "\n", encoding="utf-8")


def test_store_accumulates_and_rerun_is_idempotent(tmp_path: Path) -> None:
    """--store: 신규만 append·같은 로그 재수확은 appended 0(멱등)·리포트는 원장 전체 기준."""
    ledger = tmp_path / "ledger.ndjson"
    log1 = tmp_path / "log1.log"
    _write_log(
        log1,
        [
            _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:00+00:00"),
            _obs("incorrect", dialogue="d-1", turn=2, observed="2026-07-17T09:00:10+00:00"),
        ],
    )
    first = hv.harvest_files([log1], store=ledger)
    assert first.appended == 2
    assert first.ledger_existing == 0
    assert first.summary.total == 2

    # 같은 로그 재수확 — 원장 불변(멱등)·리포트는 여전히 원장 전체 2건.
    second = hv.harvest_files([log1], store=ledger)
    assert second.appended == 0
    assert second.input_duplicates == 2
    assert second.ledger_existing == 2
    assert second.summary.total == 2
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2

    # 새 세션 로그(신규 1 + 기존 중복 1) — 신규만 축적돼 원장 3건.
    log2 = tmp_path / "log2.log"
    _write_log(
        log2,
        [
            _obs("correct", dialogue="d-1", turn=1, observed="2026-07-17T09:00:00+00:00"),  # 중복
            _obs("unverifiable", dialogue="d-9", turn=1, observed="2026-07-17T10:00:00+00:00"),
        ],
    )
    third = hv.harvest_files([log2], store=ledger)
    assert third.appended == 1
    assert third.input_duplicates == 1
    assert third.summary.total == 3
    assert third.summary.verdict_counts["unverifiable"] == 1


def test_ledger_broken_line_counted_not_fatal(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """원장 부식 1줄은 회계(ledger_broken)·경고(타입명)하되 축적 자체는 계속된다."""
    ledger = tmp_path / "ledger.ndjson"
    good = _obs("correct", observed="2026-07-17T09:00:00+00:00")
    ledger.write_text(good.model_dump_json() + "\n" + '{"broken":' + "\n", encoding="utf-8")
    log = tmp_path / "log.log"
    _write_log(log, [_obs("incorrect", turn=2, observed="2026-07-17T09:00:10+00:00")])
    with caplog.at_level(logging.WARNING, logger=hv.logger.name):
        report = hv.harvest_files([log], store=ledger)
    assert report.ledger_broken == 1
    assert report.ledger_existing == 1
    assert report.appended == 1
    assert report.summary.total == 2
    assert any("원장 라인 파싱 실패" in r.getMessage() for r in caplog.records)


def test_without_store_reports_input_only(tmp_path: Path) -> None:
    """--store 미지정 — 이번 입력(중복 제거)만 집계·원장 필드는 0/None."""
    log = tmp_path / "log.log"
    obs = _obs("correct")
    _write_log(log, [obs, obs])  # 입력 내 중복
    report = hv.harvest_files([log])
    assert report.store_path is None
    assert report.summary.total == 1
    assert report.input_duplicates == 1
    assert report.appended == 0


# ──────────────────────────────────────────────────────────────────────────
# CLI(main) — 렌더·--json·입력 오류 종료 코드
# ──────────────────────────────────────────────────────────────────────────
def test_main_renders_and_writes_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main: 사람용 렌더(분포·회계·판정선 없음 명시) + --json 왕복."""
    log = tmp_path / "log.log"
    _write_log(
        log,
        [
            _obs("correct", observed="2026-07-17T09:00:00+00:00"),
            _obs("unverifiable", turn=2, observed="2026-07-17T09:00:10+00:00"),
        ],
    )
    ledger = tmp_path / "ledger.ndjson"
    json_out = tmp_path / "report.json"
    exit_code = hv.main([str(log), "--store", str(ledger), "--json", str(json_out)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "verify verdict" in out
    assert "판정선 없음" in out
    assert "correct" in out and "unverifiable" in out
    loaded = json.loads(json_out.read_text(encoding="utf-8"))
    assert loaded["summary"]["total"] == 2
    assert loaded["summary"]["verdict_counts"]["correct"] == 1
    assert loaded["accounting"]["parsed"] == 2
    assert loaded["appended"] == 2


def test_main_missing_file_exits_error(tmp_path: Path) -> None:
    """입력 파일 부재 — 부분 수확 리포트로 위장하지 않고 종료 코드 2."""
    assert hv.main([str(tmp_path / "없는파일.log")]) == 2


# ──────────────────────────────────────────────────────────────────────────
# 전이별 집계(S3-07) — 구판 하위호환·신/구 분리 정직 회계·왜곡 가시화
# ──────────────────────────────────────────────────────────────────────────
def _legacy_line(obs: Wh1HarnessShadowObservation) -> str:
    """진짜 구판 레코드 라인 — 카운트 *키 자체가 없는* JSON(S3-07 이전 원장·로그 재현).

    신판 모델에서 카운트 키를 지워 만든다(값 null이 아니라 키 부재 — 구판 emit과 동형).
    """
    payload = json.loads(obs.model_dump_json())
    for key in ("n_correct", "n_incorrect", "n_unverifiable"):
        del payload[key]
    return json.dumps(payload, ensure_ascii=False)


def test_parse_legacy_line_without_count_fields() -> None:
    """구판 라인(카운트 필드 부재)도 깨지지 않고 파싱 — 카운트 None(미기록·'전이 0'과 구분)."""
    legacy = _obs("unverifiable")
    # bare JSON(순수 JSONL 캡처)과 서버-로그 스타일(record 마커 + prefix) 양쪽 다 하위호환.
    record = record_logger.makeRecord(
        record_logger.name, logging.INFO, __file__, 0, _legacy_line(legacy), (), None
    )
    server_style = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s").format(
        record
    )
    observations, acct = hv.parse_log_text(_legacy_line(legacy) + "\n" + server_style)
    assert acct.parsed == 2
    assert acct.broken == 0
    for obs in observations:
        assert obs.verify_verdict == "unverifiable"  # 기존 턴 라벨 축은 그대로 읽힌다
        assert obs.n_correct is None  # 구판 = 카운트 미기록(None) — 0으로 위장하지 않는다
        assert obs.n_incorrect is None
        assert obs.n_unverifiable is None


def test_ledger_legacy_lines_load_and_rerun_idempotent(tmp_path: Path) -> None:
    """기존 원장의 구판 라인 — load_ledger 하위호환·재수확 멱등(원장 연속성·dedup 키 불변)."""
    ledger = tmp_path / "ledger.ndjson"
    legacy = _obs("correct", observed="2026-07-17T09:00:00+00:00")
    ledger.write_text(_legacy_line(legacy) + "\n", encoding="utf-8")
    loaded, broken = hv.load_ledger(ledger)
    assert broken == 0 and len(loaded) == 1
    assert loaded[0].n_correct is None
    # 같은 관측(신판 직렬화라도 dedup 키 동일)을 재수확해도 append 0 — 멱등 유지.
    log = tmp_path / "log.log"
    _write_log(log, [legacy])
    report = hv.harvest_files([log], store=ledger)
    assert report.appended == 0
    assert report.input_duplicates == 1
    assert report.summary.total == 1


def test_summarize_transition_split_and_sums() -> None:
    """신판만 Σ 합산 + 신/구 분리 회계 — 마지막 판정이 가린 앞 전이 correct가 분포에 보인다."""
    # 2026-07-19 실측 왜곡꼴: 이차방정식 자연 풀이 — 전이 (correct·correct·unverifiable)인데
    # 턴 라벨은 마지막 판정(unverifiable) 하나만 남는다.
    distorted = _obs("unverifiable", counts=(2, 0, 1), turn=1, observed="2026-07-17T09:00:00+00:00")
    plain = _obs("correct", counts=(1, 0, 0), turn=2, observed="2026-07-17T09:00:10+00:00")
    legacy = _obs("correct", turn=3, observed="2026-07-17T09:00:20+00:00")  # 구판(카운트 없음)
    summary = hv.summarize([distorted, plain, legacy])
    # 기존 턴 라벨 축(verdict_counts)은 의미 불변 — 왜곡이 *그대로* 남는다(원장 비교 연속성).
    assert summary.verdict_counts["unverifiable"] == 1
    assert summary.verdict_counts["correct"] == 2
    # 새 전이 축 — distorted의 앞 전이 correct 2가 합산에 보인다(왜곡 가시화·acceptance).
    assert summary.transition_counts == {"correct": 3, "incorrect": 0, "unverifiable": 1}
    # 정직 회계 — 합산 표본(신판 2)과 구판 1을 분리한다(구판을 '전이 0'으로 위장 금지).
    assert summary.transition_records == 2
    assert summary.legacy_records == 1


def test_summarize_empty_transition_axis() -> None:
    """관측 0건 — 전이 축도 정직하게 0/0/0 + 표본 0(비율·합산 위장 없음)."""
    summary = hv.summarize([])
    assert summary.transition_counts == {"correct": 0, "incorrect": 0, "unverifiable": 0}
    assert summary.transition_records == 0
    assert summary.legacy_records == 0


def test_render_transition_section_honest_split(tmp_path: Path) -> None:
    """render에 전이별 집계 섹션 — Σ 표기 + 신/구 분리 회계. 기존 섹션은 불변 유지."""
    log = tmp_path / "log.log"
    log.write_text(
        _server_log_line(_obs("unverifiable", counts=(2, 0, 1)))
        + "\n"
        + _legacy_line(_obs("correct", turn=2, observed="2026-07-17T09:00:10+00:00"))
        + "\n",
        encoding="utf-8",
    )
    report = hv.harvest_files([log])
    out = hv.render_report(report)
    # 새 섹션 — Σ와 신/구 분리 표기(구판을 0으로 합산하지 않음).
    assert "전이별 집계" in out
    assert "카운트 보유(신판) 1건" in out
    assert "구판(카운트 미보유) 1건" in out
    assert "Σn_correct" in out and ": 2건" in out
    assert "Σn_unverifiable" in out
    # 기존 verdict 분포 섹션 불변 — 턴 라벨 축은 여전히 마지막 판정 기준.
    assert "verify verdict 분포" in out
    assert report.summary.verdict_counts == {
        "correct": 1,
        "incorrect": 0,
        "unverifiable": 1,
        "none": 0,
    }


def test_render_transition_section_no_new_records(tmp_path: Path) -> None:
    """카운트 보유 레코드 0건(전부 구판) — Σ를 0으로 위장하지 않고 '합산 불가'를 명시한다."""
    log = tmp_path / "log.log"
    log.write_text(_legacy_line(_obs("correct")) + "\n", encoding="utf-8")
    report = hv.harvest_files([log])
    out = hv.render_report(report)
    assert "구판(카운트 미보유) 1건" in out
    assert "합산 불가" in out
    assert "Σn_correct" not in out  # 표본 없는 Σ 행은 아예 내지 않는다


# ──────────────────────────────────────────────────────────────────────────
# 회차 구간 분리·판정 모집단·전이 형태 축 (S3-51)
# ──────────────────────────────────────────────────────────────────────────
def _obs_at(observed: str, verdict: str | None, *, turn: int, forms: tuple[int, int] | None = None):
    """구간·형태 축 픽스처 — `forms`=(등호 전이 수, 혼합 전이 수). None이면 구판(축 미보유)."""
    return Wh1HarnessShadowObservation(
        status="ended",
        action_type="질문",
        verify_verdict=verdict,
        n_correct=1 if verdict == "correct" else 0,
        n_incorrect=1 if verdict == "incorrect" else 0,
        n_unverifiable=1 if verdict == "unverifiable" else 0,
        n_equation_transitions=forms[0] if forms is not None else None,
        n_mixed_form_transitions=forms[1] if forms is not None else None,
        tool_calls=3,
        hypothesis_count=0,
        dialogue_id="d-win",
        turn_index=turn,
        problem_id=None,
        observed_at=datetime.fromisoformat(observed),
    )


def test_filter_window_boundaries_are_inclusive() -> None:
    # 경계는 양끝 포함 — 시작·끝 시각에 찍힌 관측이 빠지면 회차가 잘린다.
    observations = [
        _obs_at("2026-09-22T08:59:59+00:00", "correct", turn=1),
        _obs_at("2026-09-22T09:00:00+00:00", "correct", turn=2),
        _obs_at("2026-09-22T09:30:00+00:00", "correct", turn=3),
        _obs_at("2026-09-22T10:00:00+00:00", "correct", turn=4),
        _obs_at("2026-09-22T10:00:01+00:00", "correct", turn=5),
    ]
    kept, excluded = hv.filter_window(
        observations,
        since=datetime.fromisoformat("2026-09-22T09:00:00+00:00"),
        until=datetime.fromisoformat("2026-09-22T10:00:00+00:00"),
    )
    assert [o.turn_index for o in kept] == [2, 3, 4]
    assert excluded == 2


def test_filter_window_without_bounds_is_noop() -> None:
    observations = [_obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1)]
    kept, excluded = hv.filter_window(observations)
    assert kept == observations
    assert excluded == 0


def test_filter_window_handles_naive_observed_at() -> None:
    # 수기 편집·외부 도구가 시간대 없는 값을 넣어도 비교가 터지지 않는다(UTC 간주).
    naive = Wh1HarnessShadowObservation(
        status="ended",
        action_type=None,
        verify_verdict="correct",
        n_correct=1,
        n_incorrect=0,
        n_unverifiable=0,
        tool_calls=1,
        hypothesis_count=0,
        dialogue_id=None,
        turn_index=1,
        problem_id=None,
        observed_at=datetime.fromisoformat("2026-09-22T09:30:00"),
    )
    kept, excluded = hv.filter_window(
        [naive], since=datetime.fromisoformat("2026-09-22T09:00:00+00:00")
    )
    assert len(kept) == 1
    assert excluded == 0


def test_ledger_keeps_everything_while_window_narrows_the_view(tmp_path: Path) -> None:
    """원장은 전부 축적하고 *집계 창*만 좁힌다 — 축적과 판정 분모를 분리한다.

    원장은 누적이 목적이라 이전 회차(2026-07 합성분 포함)가 늘 함께 있다. 구간을 안 주면
    그 전부가 분모가 되므로, 회차 하나를 판정하려는 사람이 *이전 회차 덕분에* 통과하는 수를
    읽게 된다(거짓 green). 필터는 원장 파일을 건드리지 않는다.
    """
    old = [
        _obs_at("2026-07-19T03:00:00+00:00", "correct", turn=i, forms=(1, 0)) for i in range(1, 9)
    ]
    new = [
        _obs_at("2026-09-22T09:10:00+00:00", "unverifiable", turn=10, forms=(0, 1)),
        _obs_at("2026-09-22T09:20:00+00:00", "correct", turn=11, forms=(2, 0)),
    ]
    log = tmp_path / "records.log"
    _write_log(log, old + new)
    ledger = tmp_path / "ledger.ndjson"

    report = hv.harvest_files(
        [log], store=ledger, since=datetime.fromisoformat("2026-09-22T00:00:00+00:00")
    )
    assert report.appended == 10  # 축적은 무필터 — 원장은 전부 보존
    assert report.filtered_out == 8
    assert report.summary.total == 2  # 집계 창은 이번 회차만
    assert report.summary.verdict_counts["correct"] == 1
    assert len(ledger.read_text(encoding="utf-8").strip().splitlines()) == 10


def test_verify_target_population_excludes_none(tmp_path: Path) -> None:
    # 사전등록 판정문의 모집단은 verify 호출 턴(3-state)뿐이다 — none(대화 턴)은 분모 밖.
    observations = [
        _obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(1, 0)),
        _obs_at("2026-09-22T09:01:00+00:00", "unverifiable", turn=2, forms=(0, 1)),
        _obs_at("2026-09-22T09:02:00+00:00", None, turn=3, forms=(0, 0)),
        _obs_at("2026-09-22T09:03:00+00:00", None, turn=4, forms=(0, 0)),
    ]
    summary = hv.summarize(observations)
    assert summary.total == 4
    assert summary.verify_target_total == 2
    # 전체 분모(25%)와 모집단 분모(50%)가 다르다 — 화면 숫자를 그대로 읽으면 오판한다.
    assert summary.verdict_ratios["unverifiable"] == pytest.approx(0.25)
    assert summary.verify_target_ratios["unverifiable"] == pytest.approx(0.5)


def test_verify_target_ratios_empty_when_population_zero() -> None:
    summary = hv.summarize([_obs_at("2026-09-22T09:00:00+00:00", None, turn=1, forms=(0, 0))])
    assert summary.verify_target_total == 0
    assert summary.verify_target_ratios == {}  # 0%로 위장하지 않는다


def test_form_axis_counts_and_legacy_split() -> None:
    observations = [
        _obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(2, 0)),
        _obs_at("2026-09-22T09:01:00+00:00", "unverifiable", turn=2, forms=(0, 3)),
        _obs_at("2026-09-22T09:02:00+00:00", "correct", turn=3, forms=(1, 1)),
        _obs_at("2026-09-22T09:03:00+00:00", "correct", turn=4),  # 구판(축 미보유)
    ]
    summary = hv.summarize(observations)
    assert summary.form_transition_counts == {"equation": 3, "mixed": 4}
    assert summary.equation_turns == 2  # V3가 읽는 수 — 등호 전이 1건 이상인 턴
    assert summary.form_records == 3
    assert summary.form_legacy_records == 1  # 구판을 '0회'로 위장하지 않는다


def test_render_shows_window_population_and_form_sections(tmp_path: Path) -> None:
    log = tmp_path / "records.log"
    _write_log(
        log,
        [
            _obs_at("2026-07-19T03:00:00+00:00", "correct", turn=1, forms=(1, 0)),
            _obs_at("2026-09-22T09:00:00+00:00", "unverifiable", turn=2, forms=(0, 1)),
        ],
    )
    report = hv.harvest_files([log], since=datetime.fromisoformat("2026-09-22T00:00:00+00:00"))
    rendered = hv.render_report(report)
    assert "[집계 구간]" in rendered
    assert "구간 밖 제외 1건" in rendered
    assert "[판정 모집단" in rendered
    assert "[전이 형태" in rendered
    assert "등호 전이 >=1 턴" in rendered


def test_render_says_when_no_window_given(tmp_path: Path) -> None:
    # 구간 미지정도 *명시적으로* 말한다 — 침묵하면 사람이 회차 분리된 줄 오해한다.
    log = tmp_path / "records.log"
    _write_log(log, [_obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(1, 0))])
    rendered = hv.render_report(hv.harvest_files([log]))
    assert "[집계 구간] 미지정" in rendered


def test_main_rejects_malformed_since(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 형식 오류를 무시하면 "필터가 걸린 줄 알았는데 원장 전체를 판정"이 된다 — exit 2로 거부.
    log = tmp_path / "records.log"
    _write_log(log, [_obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(1, 0))])
    assert hv.main([str(log), "--since", "어제"]) == 2
    assert "--since 파싱 실패" in capsys.readouterr().err


def test_main_rejects_inverted_window(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "records.log"
    _write_log(log, [_obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(1, 0))])
    exit_code = hv.main(
        [str(log), "--since", "2026-09-22T10:00:00+00:00", "--until", "2026-09-22T09:00:00+00:00"]
    )
    assert exit_code == 2
    assert "보다 늦다" in capsys.readouterr().err


def test_main_warns_on_naive_bound(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 시간대 없는 입력의 해석 규칙(UTC 간주)을 숨기지 않는다 — KST로 주면 9시간이 어긋난다.
    log = tmp_path / "records.log"
    _write_log(log, [_obs_at("2026-09-22T09:00:00+00:00", "correct", turn=1, forms=(1, 0))])
    assert hv.main([str(log), "--since", "2026-09-22T00:00:00"]) == 0
    assert "UTC로 해석한다" in capsys.readouterr().err
