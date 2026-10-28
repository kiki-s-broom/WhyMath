"""저작 회차 오케스트레이터 — 설정 계약·순수 헬퍼·실행기·탐침 (EOS-208 ②⑤⑥).

흐름·거부 가드는 `test_authoring_round.py`가 본다. 여기는 그 부품을 단위로 동결한다:

- 설정: 유료 좌석 시도 예산 필수·절대 상한·로컬 좌석의 클라우드 신호 금지·예시 설정(EOS-197)이
  런북의 spec 계획 파일과 같은 내용인가.
- 헬퍼: 회차 크기가 남은 예산을 넘지 않는다·큐는 번갈아 섞고 slug 중복을 뺀다.
- 실행기: 타임아웃·stderr 꼬리·실행 불가를 RunResult에 남긴다(실패 원인이 사라지지 않는다).
- 탐침: 실제 코드에 대해 돌아 필드를 내고, 키 값은 싣지 않는다(외부 표면 실측 — 시임만으로 정합 선언 금지).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import authoring_round as ar
from whymath_backend.harness.authoring_round_config import (
    CLOUD_ATTEMPT_HARD_CAP,
    RoundConfigError,
    load_round_config,
    parse_round_config,
)
from whymath_backend.harness.authoring_round_ports import RunResult, SubprocessRunner
from whymath_backend.harness.authoring_round_probe import run_probe

_REPO = Path(__file__).resolve().parents[3]
_EXAMPLE = _REPO / "docs" / "ops" / "authoring_round_eos197.yaml"


def _base(**over: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "round_name": "r",
        "task_id": "EOS-208",
        "worktree": "/tmp/wt",
        "seats": [
            {
                "name": "openrouter",
                "kind": "cloud",
                "provider": "openrouter",
                "model": "m",
                "subscription": "premium",
                "budget_krw": 5000,
                "expected_jurisdiction": "us",
                "target_cu": 3,
                "attempt_budget": 10,
            }
        ],
        "anchors": [{"spec_id": "a", "standard_code": "[x]", "difficulty": 2.5, "topic_hint": "h"}],
        "review": {"reviewer_id": "kiki"},
        "deliver": {"branch": "out/r"},
    }
    data.update(over)
    return data


def _parse(data: dict[str, Any]) -> Any:
    return parse_round_config(data, source_path=Path("c.yaml"), source_sha256="0" * 64)


# ── 설정 계약 ────────────────────────────────────────────────────────────


def test_example_config_matches_runbook_spec_plan() -> None:
    cfg = load_round_config(_EXAMPLE)
    plan = [
        json.loads(ln)
        for ln in (_REPO / "docs/ops/eos197_a6_spec_plan.jsonl").read_text("utf-8").splitlines()
        if ln.strip()
    ]
    assert [json.loads(ln) for ln in cfg.spec_plan_text().splitlines()] == plan
    assert cfg.ollama_request_timeout_s == 180.0
    assert [s.kind for s in cfg.seats] == ["local", "cloud"]
    assert cfg.seat_dir(cfg.seats[0]).name == "eos197-a6-local"
    assert cfg.review_dir().name == "eos197-a6-review"
    for seed in cfg.seeds:
        assert (_REPO / seed).is_file(), seed


def test_cloud_seat_without_attempt_budget_is_rejected() -> None:
    data = _base()
    del data["seats"][0]["attempt_budget"]
    with pytest.raises(RoundConfigError, match="attempt_budget"):
        _parse(data)


def test_cloud_seat_budget_above_hard_cap_is_rejected() -> None:
    data = _base()
    data["seats"][0]["attempt_budget"] = CLOUD_ATTEMPT_HARD_CAP + 1
    with pytest.raises(RoundConfigError, match="attempt_budget"):
        _parse(data)
    data["seats"][0]["attempt_budget"] = CLOUD_ATTEMPT_HARD_CAP
    assert _parse(data).seats[0].attempt_budget == CLOUD_ATTEMPT_HARD_CAP


def test_local_seat_with_cloud_signal_is_rejected() -> None:
    data = _base()
    data["seats"] = [
        {
            "name": "local",
            "kind": "local",
            "model": "q",
            "target_cu": 1,
            "attempt_budget": 5,
            "subscription": "premium",
        }
    ]
    with pytest.raises(RoundConfigError, match="local 좌석"):
        _parse(data)


def test_deliver_branch_main_is_rejected() -> None:
    with pytest.raises(RoundConfigError, match="deliver.branch"):
        _parse(_base(deliver={"branch": "main"}))


def test_bool_is_not_accepted_as_int() -> None:
    data = _base()
    data["seats"][0]["target_cu"] = True
    with pytest.raises(RoundConfigError, match="정수"):
        _parse(data)


def test_unreadable_config_names_exception_type(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_bytes(b"\xff\xfe: [")
    with pytest.raises(RoundConfigError, match="UnicodeDecodeError|YAMLError|ScannerError"):
        load_round_config(bad)


# ── 순수 헬퍼 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("lines", "tried", "target", "budget", "expected"),
    [
        (0, 0, 15, 45, 20),  # 런북 첫 회차
        (13, 40, 15, 45, 5),  # 최소 5 · 남은 예산 5
        (0, 43, 15, 45, 2),  # 남은 예산이 최소보다 작으면 남은 만큼만
        (0, 45, 15, 45, 0),  # 소진
        (20, 0, 27, 90, 14),  # EOS-197 openrouter 4회차 역산
    ],
)
def test_next_round_size_never_exceeds_remaining_budget(
    lines: int, tried: int, target: int, budget: int, expected: int
) -> None:
    assert ar.next_round_size(lines, tried, target, budget) == expected


def test_assemble_queue_interleaves_and_dedupes() -> None:
    a = [json.dumps({"slug": s}) for s in ("a1", "a2", "dup")]
    b = [json.dumps({"slug": s}) for s in ("b1", "dup")]
    out, dup = ar.assemble_queue([a, b])
    assert [json.loads(x)["slug"] for x in out] == ["a1", "b1", "a2", "dup"]
    assert dup == 1


def test_parse_porcelain_z_handles_rename_and_untracked() -> None:
    raw = "?? data/runs/x/cu.jsonl\0R  new.txt\0old.txt\0 M README.md\0"
    assert ar.parse_porcelain_z(raw) == [
        "data/runs/x/cu.jsonl",
        "new.txt",
        "old.txt",
        "README.md",
    ]


def test_is_under_rejects_sibling_prefix(tmp_path: Path) -> None:
    wt = tmp_path / "WhyMath-eos197"
    assert ar.is_under(wt / "src" / "a.py", wt)
    # 이름 앞부분만 같은 형제 폴더(평소 클론 WhyMath ↔ 워크트리 WhyMath-eos197)는 아래가 아니다.
    assert not ar.is_under(tmp_path / "WhyMath-eos197x" / "a.py", wt)
    assert not ar.is_under(tmp_path / "WhyMath" / "a.py", wt)


def test_last_json_object_skips_progress_lines() -> None:
    text = 'progress 1\n{"a": 1}\nprogress 2\n{\n  "outcome_counts": {"x": 1}\n}\n'
    assert ar.last_json_object(text) == {"outcome_counts": {"x": 1}}
    assert ar.last_json_object("no json") is None


def test_seat_artifact_stats_counts_missing_fields(tmp_path: Path) -> None:
    (tmp_path / "cu.jsonl").write_text(
        '{"slug": "s1", "subject": "미적분"}\n{"slug": "s2", "subject": "미적분"}\n', "utf-8"
    )
    (tmp_path / "cu.genlog.jsonl").write_text(
        json.dumps(
            {
                "cu_slug": "s1",
                "success": True,
                "model_name": "m",
                "prompt_version": None,
                "seed": 1,
                "input_sha256": "x",
                "cost_usd": 0.0,
            }
        )
        + "\n",
        "utf-8",
    )
    st = ar.seat_artifact_stats(tmp_path)
    assert st["missing"]["genlog"] == 1  # s2는 성공 genlog가 없다
    assert st["missing"]["prompt_version"] == 1


def test_read_jsonl_raises_on_broken_line(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n{broken\n', "utf-8")
    with pytest.raises(ValueError, match="JSONDecodeError"):
        ar.read_jsonl(p)


# ── 실행기 ────────────────────────────────────────────────────────────────


def test_runner_reports_timeout(tmp_path: Path) -> None:
    res = SubprocessRunner().run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        env={"PATH": ""},
        timeout_s=0.5,
    )
    assert res.timed_out and res.returncode is None
    assert "TimeoutExpired" in res.failure_reason()


def test_runner_keeps_stderr_tail_in_stream_mode(tmp_path: Path) -> None:
    code = "import sys; print('{\"ok\": 1}'); sys.stderr.write('마지막 원인\\n'); sys.exit(3)"
    res = SubprocessRunner().run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={"PYTHONIOENCODING": "utf-8"},
        timeout_s=30,
        mode="stream",
    )
    assert res.returncode == 3
    assert json.loads(res.stdout) == {"ok": 1}
    assert "마지막 원인" in res.failure_reason()


def test_runner_reports_launch_error(tmp_path: Path) -> None:
    res = SubprocessRunner().run(
        [str(tmp_path / "no-such-binary")], cwd=tmp_path, env={}, timeout_s=5
    )
    assert res.launch_error in ("FileNotFoundError", "PermissionError")
    assert not res.ok


def test_run_result_ok_requires_zero_exit() -> None:
    assert RunResult(0, "", "").ok
    assert not RunResult(1, "", "").ok
    assert not RunResult(None, "", "", timed_out=True).ok


# ── 탐침(실제 코드 대상) ──────────────────────────────────────────────────


def test_probe_against_real_code_reports_routing_and_hides_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-or-" + "z" * 30
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    monkeypatch.setenv("WHYMATH_OLLAMA_REQUEST_TIMEOUT_S", "180")
    cfg = load_round_config(_EXAMPLE)
    plan = tmp_path / "plan.jsonl"
    plan.write_text(cfg.spec_plan_text(), encoding="utf-8")
    result = run_probe(
        spec_plan=plan,
        local_tier="quality",
        cloud_subscription="premium",
        cloud_budget_krw=5000.0,
        check_tk=False,
    )
    assert result["errors"] == {}
    assert result["cli_flags_missing"] == []
    assert result["spec_ids"] == [a.spec_id for a in cfg.anchors]
    assert (result["subject"], result["slug_prefix"]) == ("미적분", "wm-gen-calc1")
    assert result["local_model"] == "qwen3:30b-a3b" and result["local_only"] is True
    assert result["cloud_reach_paid"] is True
    assert result["ollama_request_timeout_s"] == 180.0
    # 키는 길이·형태만 — 값은 어디에도 없다.
    assert secret not in json.dumps(result)
    assert result["key_length"] == len(secret) and result["key_shape_ok"] is True
