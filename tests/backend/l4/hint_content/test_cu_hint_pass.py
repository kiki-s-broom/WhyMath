"""CU 사후 LLM 힌트 패스 — `l4/hint_content/cu_hint_pass` · `harness/cu_hint_pass` (EOS-211).

hermetic(LLM 0·DB 0·네트워크 0) — 가짜 provider가 스크립트된 응답을 돌려준다.

검증 축(판정 분기마다 반례 + 대조군):
  ① 정상 3힌트 → verified 3 · `cu.hints.jsonl` 3행 → **EOS-207 측정기가 그 파일을 읽어 그 CU를 판정**
     (PASS — 입력 계약 동결 · 실데이터 EOS-197 CU 픽스처)
  ② L2 정답 누설 → 거부 파일로 · `cu.hints.jsonl`엔 없음 → 측정기에서 그 CU가 UNDECIDED
  ③ JSON 파싱 실패·스키마 위반 → 재시도 후 실패 기록 · genlog error_detail에 예외 타입명
  ④ provider 예외 → 재시도(성공 대조군 포함) · 실패면 타입명 기록
  ⑤ 재개 — 두 번째 실행 호출 0·파일 바이트 동일 / 끊긴 CU의 고아 행은 걷어내고 다시 만든다(중복 0)
  ⑥ 종료 코드 0·1·2 — 2는 LLM을 한 번도 부르지 않는다
  ⑦ 라우터 경유 — 기본 신호 LOCAL(QUALITY·스키마·seed) / premium+예산 → CLOUD_MID(스키마·seed 없음)
  ⑧ 값 축 능력 None → 전 힌트 거부(fail-closed) · 프롬프트 정본 문서와 코드 상수 바이트 동일
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import cu_hint_pass as harness_entry
from whymath_backend.l3.models import GenerationResult, RoutingDecision, Usage
from whymath_backend.l3.prompt_assets import parse_prompt_blocks
from whymath_backend.l4.hint_content import cu_hint_pass as chp
from whymath_backend.l4.hint_content.cu_hint_prompts import (
    CU_HINT_OUTPUT_SCHEMA,
    CU_HINT_SYSTEM,
    CU_HINT_USER_TEMPLATE,
    cu_hint_prompt_version,
)
from whymath_backend.l4.hint_content.models import Hint
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure
from whymath_backend.ops import g3_content_measures as g3

_REPO = Path(__file__).resolve().parents[4]
_OR_RUN = _REPO / "data" / "runs" / "eos197-a6-openrouter"
_LOCAL_RUN = _REPO / "data" / "runs" / "eos197-a6-local"
# 실데이터 픽스처: EOS-197 A6 openrouter 좌석 CU 1건(삼차함수 극댓값 · 정답 14 · 해설 있음).
_REAL_SLUG = "wm-gen-calc1-ef3b1971fcd3"
_ROUND = "r1"


# ──────────────────────────────────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────────────────────────────────
def _real_rows(run: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run / "cu.jsonl").read_text("utf-8").splitlines() if line]


def _real_cu() -> dict[str, Any]:
    rows = [r for r in _real_rows(_OR_RUN) if r["slug"] == _REAL_SLUG]
    assert len(rows) == 1, "실데이터 픽스처 CU가 사라졌다"
    return rows[0]


def _good(**override: Any) -> str:
    """정답 14 문항(f(x)=2x^3-3x^2-12x+7의 극댓값)에 대한 게이트 3종 통과 응답."""
    hints = {
        "L1": "이 문제는 「삼차함수의 극값」이 중심이야. 극값이 생기는 곳에서 도함수는 어떤 성질을 "
        "가질까?",
        "L2": "풀이는 모두 3단계로 이어져. 지금은 첫 단계야 — 함수를 미분해 도함수를 구하는 자리지. "
        "그다음엔 도함수가 0이 되는 곳을 찾고, 끝으로 극대가 되는 곳의 함숫값을 구해. 첫 단계에서 "
        "무엇부터 해 볼까?",
        "L3": "첫 단계를 같이 해 볼게.\n함수를 미분하면 다음과 같아: f'(x) = 6*x^2 - 6*x - 12\n"
        "이 도함수가 0이 되는 곳은 어떻게 찾을 수 있을까?",
    }
    hints.update(override.pop("hints", {}))
    body: dict[str, Any] = {
        "steps": ["f'(x) = 6*x^2 - 6*x - 12", "6*(x + 1)*(x - 2) = 0", "M = 14"],
        "concept_name": "삼차함수의 극값",
        "hints": hints,
    }
    body.update(override)
    return json.dumps(body, ensure_ascii=False)


def _seat(tmp: Path, rows: Sequence[Mapping[str, Any]], name: str = f"{_ROUND}-or") -> Path:
    run = tmp / name
    run.mkdir(parents=True)
    (run / "cu.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    return run


class _Provider:
    """스크립트된 가짜 provider — 응답 문자열 또는 던질 예외를 순서대로 낸다."""

    def __init__(self, script: Sequence[str | BaseException]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision, **kwargs: Any
    ) -> GenerationResult:
        self.calls.append({"prompt": prompt, "system": system, "decision": decision, **kwargs})
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return GenerationResult(text=item, usage=Usage(input_tokens=10, output_tokens=20))


class _Trace:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.flushed = 0

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)

    def flush(self) -> None:
        self.flushed += 1


def _run(
    run: Path,
    provider: _Provider,
    *,
    value_exposure: Any = "default",
    trace: _Trace | None = None,
    **kw: Any,
) -> chp.PassReport:
    import asyncio

    exposure = math_answer_value_exposure() if value_exposure == "default" else value_exposure
    return asyncio.run(
        chp.run_cu_hint_pass(
            run,
            provider=provider,
            value_exposure=exposure,
            trace=trace,
            seed_source=lambda: 7,
            run_id="test-run",
            **kw,
        )
    )


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _measure(tmp: Path, hints_path: Path) -> dict[str, Any]:
    """EOS-207 측정기를 CLI 그대로 돌려 힌트 축 리포트를 받는다(입력 계약 동결)."""
    out = tmp / "report.json"
    g3.main(
        [
            "--round",
            _ROUND,
            "--runs-root",
            str(tmp),
            "--hints-jsonl",
            str(hints_path),
            "--json",
            str(out),
        ]
    )
    report: dict[str, Any] = json.loads(out.read_text("utf-8"))
    return report


def _with_genlog(run: Path, slug: str) -> None:
    """측정기는 좌석 폴더에 cu.genlog.jsonl을 요구한다 — 실데이터에서 그 CU의 성공 행을 옮긴다."""
    rows = [
        line
        for line in (_OR_RUN / "cu.genlog.jsonl").read_text("utf-8").splitlines()
        if line.strip() and json.loads(line).get("cu_slug") == slug
    ]
    (run / "cu.genlog.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# ① 정상 3힌트 + 측정기 통합(실데이터 CU)
# ──────────────────────────────────────────────────────────────────────
class TestNormalPathWithMeasurer:
    def test_three_verified_hints_are_written_and_measured(self, tmp_path: Path) -> None:
        cu = _real_cu()
        run = _seat(tmp_path, [cu])
        provider = _Provider([_good()])
        trace = _Trace()
        report = _run(run, provider, trace=trace)

        assert report.exit_code == chp.EXIT_OK
        lines = report.render_lines()
        assert lines[-1] == "EXIT=0"
        assert "CU_COMPLETE=1" in lines and "HINTS_VERIFIED=3" in lines
        hints = _lines(run / chp.HINTS_FILE)
        assert [h["level"] for h in hints] == [1, 2, 3]
        assert all(h["verified"] is True for h in hints)
        assert {h["hint_id"] for h in hints} == {
            f"hint-cu-{_REAL_SLUG}-s1-l{level}" for level in (1, 2, 3)
        }
        assert {h["solution_step_ref"]["problem_id"] for h in hints} == {cu["problem_id"]}
        assert _lines(run / chp.REJECTED_FILE) == []
        # 문맥 행 = 완료 표지 + 게이트가 본 맥락
        (context,) = _lines(run / chp.CONTEXT_FILE)
        assert context["verified_levels"] == [1, 2, 3] and context["final_answer"] == "14"
        assert context["solution_path_id"] == f"cu-{_REAL_SLUG}"
        # 생성 로그 — 기존 GenerationLog 4필드 + 성공 여부
        (log,) = _lines(run / chp.GENLOG_FILE)
        assert log["success"] is True and log["error_detail"] is None
        assert log["model_name"] and log["prompt_version"] == cu_hint_prompt_version()
        assert len(log["input_sha256"]) == 64 and log["seed"] == 7
        assert log["cu_slug"] == _REAL_SLUG and log["run_id"] == "test-run"
        assert context["attempt_id"] == log["log_id"]  # 시도 ID = 생성 로그 log_id
        # 관측 — 성공 호출마다 1건 + 배치 끝 flush
        assert len(trace.records) == 1 and trace.flushed == 1
        # 프롬프트에 해설이 실린다(해설 있는 좌석)
        assert cu["answer_explanation"] in provider.calls[0]["prompt"]

        # EOS-207 측정기가 이 파일을 그대로 읽어 그 CU를 판정한다(입력 계약 동결)
        _with_genlog(run, _REAL_SLUG)
        loaded, errors = g3.load_hints([run / chp.HINTS_FILE])
        assert errors == [] and len(loaded) == 3
        hint_leak = _measure(tmp_path, run / chp.HINTS_FILE)["hint_leak"]
        assert hint_leak["status"] == "PASS", hint_leak["reason"]
        assert hint_leak["cu_with_hints"] == 1 and hint_leak["judged_l12"] == 2
        assert hint_leak["unmatched_hints"] == 0
        assert len(hint_leak["per_cu"][_REAL_SLUG]["judged"]) == 3

    def test_local_seat_cu_without_explanation_asks_to_solve(self, tmp_path: Path) -> None:
        local = _real_rows(_LOCAL_RUN)[0]
        assert not local.get("answer_explanation")  # 로컬 좌석 CU는 해설이 없다(실데이터)
        run = _seat(tmp_path, [local])
        provider = _Provider(["{}"] * 3)
        _run(run, provider)
        assert "(해설 없음" in provider.calls[0]["prompt"]
        assert local["question_text"] in provider.calls[0]["prompt"]


# ──────────────────────────────────────────────────────────────────────
# ② 누설 → 거부 → 측정기 UNDECIDED
# ──────────────────────────────────────────────────────────────────────
class TestLeakIsRejected:
    def test_l2_leaking_answer_goes_to_rejected_and_measure_is_undecided(
        self, tmp_path: Path
    ) -> None:
        run = _seat(tmp_path, [_real_cu()])
        leak = (
            "풀이는 모두 3단계로 이어져. 지금은 첫 단계야. 끝에 극댓값 14가 나와. 어떻게 시작할까?"
        )
        report = _run(run, _Provider([_good(hints={"L2": leak})]), retries=0)

        assert report.exit_code == chp.EXIT_INCOMPLETE
        assert report.incomplete_cus == [_REAL_SLUG]
        assert [h["level"] for h in _lines(run / chp.HINTS_FILE)] == [1, 3]
        (rejected,) = _lines(run / chp.REJECTED_FILE)
        assert rejected["level"] == 2 and rejected["verified"] is False
        assert rejected["gate_report"]["answer_leakage"]["passed"] is False
        assert report.rejected_by_gate["answer_leakage"] == 1

        _with_genlog(run, _REAL_SLUG)
        hint_leak = _measure(tmp_path, run / chp.HINTS_FILE)["hint_leak"]
        assert hint_leak["status"] == "UNDECIDED"
        assert hint_leak["cu_without_l12"] == 1

    def test_missing_value_capability_rejects_everything(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        report = _run(run, _Provider([_good()]), value_exposure=None, retries=0)
        assert _lines(run / chp.HINTS_FILE) == []
        assert len(_lines(run / chp.REJECTED_FILE)) == 3
        assert report.exit_code == chp.EXIT_INCOMPLETE


# ──────────────────────────────────────────────────────────────────────
# ③④ 파싱·스키마·provider 실패 → 재시도 → 타입명 기록
# ──────────────────────────────────────────────────────────────────────
class TestFailuresAreRecorded:
    def test_json_parse_failure_is_retried_and_logged_with_type_name(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        provider = _Provider(["이건 JSON이 아니다"] * 3)
        report = _run(run, provider)
        assert len(provider.calls) == 3  # 최초 1 + 재시도 2(기본)
        logs = _lines(run / chp.GENLOG_FILE)
        assert [log["success"] for log in logs] == [False, False, False]
        assert all("JSONDecodeError" in log["error_detail"] for log in logs)
        assert all(log["cu_slug"] == _REAL_SLUG for log in logs)
        assert report.failed_cus == [_REAL_SLUG] and report.exit_code == chp.EXIT_INCOMPLETE
        assert f"FAILED_CUS={_REAL_SLUG}" in report.render_lines()
        assert not (run / chp.HINTS_FILE).exists() and not (run / chp.CONTEXT_FILE).exists()

    def test_schema_violation_names_the_location_not_the_value(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        bad = _good(answer="14")  # 계약 밖 키(정답 필드) — 스키마 위반
        report = _run(run, _Provider([bad]), retries=0)
        (log,) = _lines(run / chp.GENLOG_FILE)
        assert log["error_detail"].startswith("응답 스키마 위반: ValidationError")
        assert "answer" in log["error_detail"] and "14" not in log["error_detail"]
        assert report.failure_kinds["schema"] == 1

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"steps": ["M = 14"]}, id="single-step"),
            pytest.param({"concept_name": "3차 함수"}, id="digit-in-concept"),
        ],
    )
    def test_contract_rejects_one_step_and_valued_concept(self, body: dict[str, Any]) -> None:
        with pytest.raises(chp.DraftError, match="ValidationError"):
            chp.parse_draft(_good(**body))

    def test_fenced_json_is_accepted(self) -> None:
        draft = chp.parse_draft("설명입니다\n```json\n" + _good() + "\n```")
        assert draft.concept_name == "삼차함수의 극값"

    def test_provider_exception_is_retried_then_succeeds(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        provider = _Provider([TimeoutError("느림"), _good()])
        report = _run(run, provider)
        logs = _lines(run / chp.GENLOG_FILE)
        assert [log["success"] for log in logs] == [False, True]
        assert logs[0]["error_detail"].startswith("provider.generate failed: TimeoutError")
        assert report.exit_code == chp.EXIT_OK and report.calls_failed == 1

    def test_provider_exception_every_attempt_fails_the_cu(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        provider = _Provider([ConnectionError("x")] * 2)
        report = _run(run, provider, retries=1)
        logs = _lines(run / chp.GENLOG_FILE)
        assert len(provider.calls) == 2 and len(logs) == 2
        assert all("ConnectionError" in log["error_detail"] for log in logs)
        assert report.failed_cus == [_REAL_SLUG] and report.exit_code == chp.EXIT_INCOMPLETE


# ──────────────────────────────────────────────────────────────────────
# ⑤ 재개
# ──────────────────────────────────────────────────────────────────────
class TestResume:
    def test_second_run_makes_zero_calls_and_changes_nothing(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good()]))
        before = {p.name: p.read_bytes() for p in run.iterdir()}
        second = _Provider([])
        report = _run(run, second)
        assert second.calls == []
        assert {p.name: p.read_bytes() for p in run.iterdir()} == before
        assert report.cu_resumed == 1 and report.exit_code == chp.EXIT_OK

    def test_inconsistent_rows_of_an_interrupted_cu_are_replaced_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good()]))
        (run / chp.CONTEXT_FILE).unlink()  # 채택본은 썼는데 문맥 행 교체 전에 끊긴 상태
        report = _run(run, _Provider([_good()]))
        assert report.discarded_inconsistent_rows == 3
        hint_ids = [h["hint_id"] for h in _lines(run / chp.HINTS_FILE)]
        assert len(hint_ids) == 3 and len(set(hint_ids)) == 3
        assert len(_lines(run / chp.GENLOG_FILE)) == 2  # 호출 기록은 걷어내지 않는다

    def test_limit_leaves_unprocessed_cus_pending(self, tmp_path: Path) -> None:
        cus = [r for r in _real_rows(_OR_RUN) if r.get("answer_explanation")][:2]
        run = _seat(tmp_path, cus)
        first = _run(run, _Provider(["{}"]), limit=1, retries=0)
        assert first.pending_cus == [cus[1]["slug"]] and first.exit_code == chp.EXIT_INCOMPLETE
        assert first.cu_processed == 1


# ──────────────────────────────────────────────────────────────────────
# ⑥ 입력 오류 = exit 2 · LLM 호출 0
# ──────────────────────────────────────────────────────────────────────
class TestInputErrors:
    def test_missing_cu_file(self, tmp_path: Path) -> None:
        provider = _Provider([])
        report = _run(tmp_path / "nope", provider)
        assert report.exit_code == chp.EXIT_INPUT_ERROR and provider.calls == []
        assert report.render_lines()[-1] == "EXIT=2"

    def test_empty_cu_file_is_not_success(self, tmp_path: Path) -> None:
        provider = _Provider([])
        report = _run(_seat(tmp_path, []), provider)
        assert report.exit_code == chp.EXIT_INPUT_ERROR and provider.calls == []

    def test_non_self_authored_cu_is_refused_before_any_call(self, tmp_path: Path) -> None:
        cu = dict(_real_cu(), license="KOGL_TYPE1")
        provider = _Provider([])
        report = _run(_seat(tmp_path, [cu]), provider)
        assert report.exit_code == chp.EXIT_INPUT_ERROR and provider.calls == []
        assert any("자체 저작" in e for e in report.input_errors)

    def test_corrupt_existing_output_stops_the_run(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good()]))
        rows = _lines(run / chp.HINTS_FILE)
        rows[0]["verified"] = False  # 통과 파일에 미검수 행이 섞였다
        (run / chp.HINTS_FILE).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        provider = _Provider([])
        report = _run(run, provider)
        assert report.exit_code == chp.EXIT_INPUT_ERROR and provider.calls == []

    def test_negative_retries_is_input_error(self, tmp_path: Path) -> None:
        report = _run(_seat(tmp_path, [_real_cu()]), _Provider([]), retries=-1)
        assert report.exit_code == chp.EXIT_INPUT_ERROR


# ──────────────────────────────────────────────────────────────────────
# ⑦ 라우터 경유 좌석 선택
# ──────────────────────────────────────────────────────────────────────
class TestRouting:
    def test_default_signals_route_local_quality_with_schema_and_seed(self, tmp_path: Path) -> None:
        provider = _Provider([_good()])
        _run(_seat(tmp_path, [_real_cu()]), provider)
        call = provider.calls[0]
        decision: RoutingDecision = call["decision"]
        assert decision.cost_tier == "local" and decision.local_model == "quality"
        assert call["json_schema"] == CU_HINT_OUTPUT_SCHEMA and call["seed"] == 7
        assert call["system"] == CU_HINT_SYSTEM

    def test_premium_with_budget_routes_cloud_without_schema_or_seed(self, tmp_path: Path) -> None:
        provider = _Provider([_good()])
        run = _seat(tmp_path, [_real_cu()])
        _run(run, provider, subscription="premium", budget_krw=5000.0)
        call = provider.calls[0]
        assert call["decision"].cost_tier == "cloud_mid"
        assert "json_schema" not in call and "seed" not in call
        (log,) = _lines(run / chp.GENLOG_FILE)
        assert log["seed"] is None  # 클라우드는 seed 미기록(날조 금지)

    def test_routing_probe_is_the_function_the_pass_uses(self) -> None:
        """런북 [C]가 부르는 공개 함수 — 기본 신호는 LOCAL, premium+예산은 CLOUD_MID로 변별된다."""
        from whymath_backend.l3.router import Router

        local = Router().route(chp.routing_request_for(subscription=None, budget_krw=None))
        cloud = Router().route(chp.routing_request_for(subscription="premium", budget_krw=5000.0))
        assert (local.cost_tier, local.local_model) == ("local", "quality")
        assert cloud.cost_tier == "cloud_mid"

    def test_progress_line_per_cu(self, tmp_path: Path) -> None:
        cus = [r for r in _real_rows(_OR_RUN) if r.get("answer_explanation")][:2]
        seen: list[str] = []
        _run(_seat(tmp_path, cus), _Provider([_good(), "{}"]), retries=0, on_progress=seen.append)
        assert seen[0].startswith(f"CU_DONE slug={cus[0]['slug']}")
        assert seen[1] == f"CU_FAILED slug={cus[1]['slug']} attempts_total=1"


# ──────────────────────────────────────────────────────────────────────
# ⑧ 프롬프트 정본 정합 · CLI
# ──────────────────────────────────────────────────────────────────────
class TestPromptAndCli:
    def test_prompt_doc_blocks_equal_code_constants(self) -> None:
        doc = (_REPO / "docs" / "prompts" / "cu_hint_pass.md").read_text("utf-8")
        blocks = parse_prompt_blocks(doc, origin="cu_hint_pass.md")
        assert blocks == {
            "l4.cu_hint.system": CU_HINT_SYSTEM,
            "l4.cu_hint.user": CU_HINT_USER_TEMPLATE,
        }
        assert cu_hint_prompt_version().startswith("l4.cu_hint@sha256:")

    def test_run_cli_prints_summary_ending_with_exit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run = _seat(tmp_path, [_real_cu()])
        code = chp.run_cli(
            ["--run-dir", str(run)],
            prog="t",
            provider_factory=lambda: _Provider([_good()]),
            trace_factory=lambda: None,
            value_exposure=math_answer_value_exposure(),
        )
        out = capsys.readouterr().out.strip().splitlines()
        assert code == 0 and out[-1] == "EXIT=0"

    def test_harness_entry_passes_the_math_value_capability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_run_cli(argv: Any, **kwargs: Any) -> int:
            seen.update(kwargs)
            return 0

        monkeypatch.setattr(harness_entry, "run_cli", fake_run_cli)
        assert harness_entry.main(["--run-dir", "x"]) == 0
        assert seen["value_exposure"] is not None  # None이면 전 힌트가 fail-closed로 거부된다
        assert type(seen["value_exposure"]).__name__ == "MathAnswerValueExposure"
        provider = seen["provider_factory"]()  # 지연 연결 — 구성만으로 네트워크 0
        assert type(provider).__name__ == "CompositeProvider"

    def test_written_rows_are_hint_model_json(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good(hints={"L2": "극댓값은 14야. 몇 단계일까?"})]), retries=0)
        for name in (chp.HINTS_FILE, chp.REJECTED_FILE):
            for row in _lines(run / name):
                Hint.model_validate(row)


# ──────────────────────────────────────────────────────────────────────
# P2-1 게이트 거부 재생성 · 시도 예산 · 재개 정의
# ──────────────────────────────────────────────────────────────────────
_LEAK_L2 = "풀이는 모두 3단계로 이어져. 지금은 첫 단계야. 끝에 극댓값 14가 나와. 어떻게 시작할까?"


def _summary(report: chp.PassReport) -> dict[str, str]:
    return dict(line.split("=", 1) for line in report.render_lines())


class TestRegeneration:
    def test_gate_rejection_is_regenerated_within_budget(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        provider = _Provider([_good(hints={"L2": _LEAK_L2}), _good()])
        report = _run(run, provider)
        assert len(provider.calls) == 2 and report.exit_code == chp.EXIT_OK
        assert [h["level"] for h in _lines(run / chp.HINTS_FILE)] == [1, 2, 3]
        assert [h["level"] for h in _lines(run / chp.REJECTED_FILE)] == [2]  # 이력은 남는다
        logs = _lines(run / chp.GENLOG_FILE)
        assert [log["success"] for log in logs] == [True, True]  # 시도마다 1행
        (context,) = _lines(run / chp.CONTEXT_FILE)
        assert context["attempt_no"] == 2 and context["attempts_total"] == 2
        assert context["attempt_id"] == logs[1]["log_id"]
        hints = _lines(run / chp.HINTS_FILE)
        assert all(h["generator_version"].endswith(uuid_hex12(logs[1]["log_id"])) for h in hints)
        summary = _summary(report)
        assert summary["HINT_ATTEMPTS_TOTAL"] == "2"
        assert summary["HINT_GATED_ATTEMPTS_TOTAL"] == "2"
        assert summary["HINT_GATE_REJECTED_HINTS_TOTAL"] == "1"
        assert summary["HINT_GATE_REJECT_RATE"] == "0.1667"
        assert summary["CU_REGENERATED"] == "1" and summary["REGENERATED_CUS"] == _REAL_SLUG

    def test_best_candidate_is_kept_when_budget_runs_out(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        worse = _good(hints={"L1": "어떤 성질을 쓸 수 있을까?", "L2": _LEAK_L2})
        report = _run(run, _Provider([_good(hints={"L2": _LEAK_L2}), worse, "{}"]))
        assert [h["level"] for h in _lines(run / chp.HINTS_FILE)] == [1, 3]
        (context,) = _lines(run / chp.CONTEXT_FILE)
        assert context["attempt_no"] == 1 and context["attempts_total"] == 3
        assert context["gated_attempts_total"] == 2 and context["rejected_hints_total"] == 3
        assert _summary(report)["HINT_GATE_REJECT_RATE"] == "0.5000"
        assert report.incomplete_cus == [_REAL_SLUG] and report.exit_code == chp.EXIT_INCOMPLETE

    def test_budget_counts_from_the_first_attempt_across_runs(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good(hints={"L2": _LEAK_L2})]), retries=0)
        second = _Provider([_good(), _good()])
        report = _run(run, second, retries=1)  # 총 2회 중 1회는 이미 썼다
        assert len(second.calls) == 1 and report.exit_code == chp.EXIT_OK
        assert _summary(report)["HINT_ATTEMPTS_TOTAL"] == "2"

    def test_exhausted_budget_skips_until_redo_incomplete(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good(hints={"L2": _LEAK_L2})]), retries=0)
        idle = _Provider([])
        report = _run(run, idle, retries=0)
        assert idle.calls == [] and report.budget_exhausted_cus == [_REAL_SLUG]
        assert report.exit_code == chp.EXIT_INCOMPLETE
        redo = _Provider([_good()])
        report = _run(run, redo, retries=0, redo_incomplete=True)
        assert len(redo.calls) == 1 and report.exit_code == chp.EXIT_OK
        hint_ids = [h["hint_id"] for h in _lines(run / chp.HINTS_FILE)]
        assert len(hint_ids) == 3 and len(set(hint_ids)) == 3  # 채택본은 교체(중복 0)
        assert len(_lines(run / chp.REJECTED_FILE)) == 1  # 거부 이력은 지우지 않는다
        assert len(_lines(run / chp.GENLOG_FILE)) == 2
        (context,) = _lines(run / chp.CONTEXT_FILE)
        assert context["verified_levels"] == [1, 2, 3] and context["attempts_total"] == 2


def uuid_hex12(log_id: str) -> str:
    return log_id.replace("-", "")[:12]


# ──────────────────────────────────────────────────────────────────────
# P3 — 원문 비노출 · 개념 이름 정규화 · 손상 줄 격리 · 최상위 예외
# ──────────────────────────────────────────────────────────────────────
class _HttpError(Exception):
    def __init__(self) -> None:
        super().__init__("Bearer sk-or-SECRET1234 at https://api.example/v1?key=abc")
        self.status_code = 429


class _BrokenStatusError(Exception):
    @property
    def status_code(self) -> int:
        raise RuntimeError("속성 접근이 터진다")


class TestP3Hardening:
    def test_error_detail_has_type_and_status_but_no_message(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_HttpError()]), retries=0)
        (log,) = _lines(run / chp.GENLOG_FILE)
        assert log["error_detail"] == "provider.generate failed: _HttpError(HTTP 429)"
        assert "SECRET" not in (run / chp.GENLOG_FILE).read_text("utf-8")

    def test_safe_summary_never_raises(self) -> None:
        assert chp._safe_exc_summary(_BrokenStatusError("x")) == "_BrokenStatusError"
        assert chp._safe_exc_summary(ValueError("민감한 원문")) == "ValueError"

    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("３차 함수의 극값", id="fullwidth-digit"),
            pytest.param("½ 공식의 활용", id="vulgar-fraction"),
            pytest.param("원주율 π의 뜻", id="pi"),
        ],
    )
    def test_concept_name_is_checked_after_nfkc(self, name: str) -> None:
        with pytest.raises(chp.DraftError, match="concept_name"):
            chp.parse_draft(_good(concept_name=name))

    def test_concept_name_containing_the_answer_is_rejected(self) -> None:
        with pytest.raises(chp.DraftError, match="concept_name"):
            chp.parse_draft(_good(concept_name="ａｂ 꼴의 성질"), answer="ab")

    def test_one_char_answer_is_not_judged_by_containment(self) -> None:
        # 1자 정답은 개념 이름의 흔한 글자와 우연히 겹친다 — 판정하지 않는다(근거는 모듈 상수 주석)
        draft = chp.parse_draft(_good(concept_name="자연상수 e의 성질"), answer="e")
        assert draft.concept_name == "자연상수 e의 성질"

    def test_truncated_genlog_tail_is_quarantined_before_append(self, tmp_path: Path) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([TimeoutError("x")]), retries=0)
        with (run / chp.GENLOG_FILE).open("ab") as handle:
            handle.write(b'{"log_id": "cut-mid-wri')  # 쓰는 도중 끊긴 마지막 줄(개행 없음)
        report = _run(run, _Provider([_good()]), retries=2)
        assert report.exit_code == chp.EXIT_OK, report.input_errors
        assert _summary(report)["GENLOG_QUARANTINED_LINES"] == "1"
        corrupt = (run / (chp.GENLOG_FILE + ".corrupt")).read_bytes()
        assert corrupt == b'{"log_id": "cut-mid-wri\n'
        logs = _lines(run / chp.GENLOG_FILE)  # 남은 줄은 전부 온전한 JSON
        assert [log["success"] for log in logs] == [False, True]

    def test_damaged_state_file_stops_then_recovers_with_quarantine_switch(
        self, tmp_path: Path
    ) -> None:
        run = _seat(tmp_path, [_real_cu()])
        _run(run, _Provider([_good()]))
        data = (run / chp.CONTEXT_FILE).read_bytes()
        (run / chp.CONTEXT_FILE).write_bytes(data[: len(data) // 2])  # 외부 손상(잘린 줄)
        stopped = _run(run, _Provider([]))
        assert stopped.exit_code == chp.EXIT_INPUT_ERROR
        recovered = _run(run, _Provider([_good()]), quarantine_damaged_state=True)
        assert recovered.exit_code == chp.EXIT_OK, recovered.input_errors
        assert _summary(recovered)["STATE_QUARANTINED_LINES"] == "1"
        assert (run / (chp.CONTEXT_FILE + ".corrupt")).is_file()
        assert [h["level"] for h in _lines(run / chp.HINTS_FILE)] == [1, 2, 3]

    def test_unhandled_error_exits_3_with_type_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = _seat(tmp_path, [_real_cu()])

        def denied(path: Path, data: bytes) -> None:
            raise PermissionError("/비밀/경로 접근 거부")

        monkeypatch.setattr(chp, "_atomic_write_bytes", denied)
        code = chp.run_cli(
            ["--run-dir", str(run)],
            prog="t",
            provider_factory=lambda: _Provider([_good()]),
            trace_factory=lambda: None,
            value_exposure=math_answer_value_exposure(),
        )
        out = capsys.readouterr().out.strip().splitlines()
        assert code == chp.EXIT_UNHANDLED == 3
        assert out[-2:] == ["UNHANDLED_ERROR=PermissionError", "EXIT=3"]
        assert "비밀" not in "\n".join(out)
