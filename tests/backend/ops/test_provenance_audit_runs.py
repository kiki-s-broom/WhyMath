"""provenance_audit의 저작 회차 산출물 검사(EOS-198 ④ · 공백 G-F).

정본: `ops/provenance_audit.py`의 `audit_runs_root`·`--runs-root`·`--require-runs`.
종전 감사는 `data/corpus/`만 봐서 `data/runs/*/cu.jsonl`이 무엇이든 exit 0이었다(변별력 0).

검증 축:
  ① 정상 회차(로컬 좌석 seed 있음 · 클라우드 좌석 seed=null) → exit 0, seed 미검사 수는 리포트에
  ② 결함 주입 — license 결손·생성 로그 부재·조인 불가·model_name/prompt_version/input_sha256 결손·
     로컬 좌석 seed 결손·파싱 실패 → 각각 해당 kind로 exit 1
  ③ 대상 0건 — 기본 경로 부재는 정상(exit 0), 명시 경로 부재는 위반, --require-runs면 0건 위반
  ④ **실 생산자 산출물** — 저작 CLI(`problem_corpus_accumulate.main`)를 대본 provider로 돌려 만든
     cu.jsonl·cu.genlog.jsonl을 그대로 감사한다(픽스처를 손으로만 만들면 실제 모양과 어긋나도
     모른다). 같은 산출물의 prompt_version을 지우면 RED.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.models import GenerationResult, RoutingDecision, Usage
from whymath_backend.l3.router import QUALITY_MODEL_ID
from whymath_backend.ops import provenance_audit as pa
from whymath_backend.schema.enums import Subject

_LOCAL_MODEL = QUALITY_MODEL_ID  # 라우터 매트릭스 좌석 — capability_for_model이 "지원"으로 분류
_CLOUD_MODEL = "deepseek/deepseek-v4.1-flash"
_SHA = "a" * 64


def _cu(slug: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "slug": slug,
        "license": "WHYMATH_GENERATED",
        "source_type": "자체생성",
        "achievement_standard_codes": ["[12미적Ⅰ-02-05]"],
    }
    row.update(overrides)
    return row


def _log(slug: str | None, model: str, *, seed: int | None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cu_slug": slug,
        "model_name": model,
        "prompt_version": "l3.equivalent@sha256:abc123def456",
        "seed": seed,
        "input_sha256": _SHA,
        "success": True,
    }
    row.update(overrides)
    return row


def _write(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _two_seat_runs(root: Path) -> Path:
    runs = root / "runs"
    _write(runs / "eos197-a6-local" / "cu.jsonl", [_cu("wm-l-1"), _cu("wm-l-2")])
    _write(
        runs / "eos197-a6-local" / "cu.genlog.jsonl",
        [
            _log("wm-l-1", _LOCAL_MODEL, seed=11),
            _log(None, _LOCAL_MODEL, seed=12, success=False),  # 실패 호출 — 조인 대상 아님
            _log("wm-l-2", _LOCAL_MODEL, seed=13),
        ],
    )
    _write(runs / "eos197-a6-openrouter" / "cu.jsonl", [_cu("wm-o-1")])
    _write(
        runs / "eos197-a6-openrouter" / "cu.genlog.jsonl",
        [_log("wm-o-1", _CLOUD_MODEL, seed=None)],
    )
    (runs / "eos197-a6-review").mkdir(parents=True)  # 검수 폴더 — cu.jsonl 없음
    return runs


def _audit(runs: Path, *, explicit: bool = True, require_runs: bool = False) -> pa.AuditReport:
    report = pa.AuditReport(corpus_root="<test>", corpora_scanned=0)
    pa.audit_runs_root(runs, report, explicit=explicit, require_runs=require_runs)
    return report


def _kinds(report: pa.AuditReport) -> list[str]:
    return [v.kind for v in report.violations]


class TestCleanRunsPass:
    def test_two_seats_with_cloud_null_seed_pass(self, tmp_path: Path) -> None:
        report = _audit(_two_seat_runs(tmp_path))
        assert report.violations == []
        assert report.runs_scanned == 2
        assert report.run_cu_records == 3
        assert report.seed_checked == 2  # 로컬 2건만 seed를 검사했다
        assert report.seed_unchecked_by_model == {f"{_CLOUD_MODEL}(미상)": 1}
        assert report.run_dirs_without_records == ["eos197-a6-review"]
        assert report.exit_code == 0

    def test_run_with_zero_cu_rows_and_no_genlog_is_not_a_violation(self, tmp_path: Path) -> None:
        """무진전 회차 — CU 0행이면 조인할 것도 없다(생성 로그 부재도 정상)."""
        runs = tmp_path / "runs"
        (runs / "r").mkdir(parents=True)
        (runs / "r" / "cu.jsonl").write_text("", "utf-8")
        report = _audit(runs)
        assert report.violations == []
        assert report.runs_scanned == 1


class TestInjectedDefectsAreCaught:
    @pytest.mark.parametrize("field", ["license", "source_type"])
    def test_record_meta_missing(self, tmp_path: Path, field: str) -> None:
        runs = _two_seat_runs(tmp_path)
        _write(runs / "eos197-a6-local" / "cu.jsonl", [_cu("wm-l-1"), _cu("wm-l-2", **{field: ""})])
        assert _kinds(_audit(runs)) == ["RUN_RECORD_FIELDS_MISSING"]

    def test_record_json_invalid(self, tmp_path: Path) -> None:
        runs = _two_seat_runs(tmp_path)
        with (runs / "eos197-a6-openrouter" / "cu.jsonl").open("a", encoding="utf-8") as fh:
            fh.write("{깨짐\n")
        assert _kinds(_audit(runs)) == ["RUN_RECORD_JSON_INVALID"]

    def test_genlog_missing(self, tmp_path: Path) -> None:
        runs = _two_seat_runs(tmp_path)
        (runs / "eos197-a6-openrouter" / "cu.genlog.jsonl").unlink()
        assert _kinds(_audit(runs)) == ["RUN_GENLOG_MISSING"]

    def test_genlog_json_invalid(self, tmp_path: Path) -> None:
        runs = _two_seat_runs(tmp_path)
        (runs / "eos197-a6-local" / "cu.genlog.jsonl").write_text("[1, 2]\n", "utf-8")
        assert _kinds(_audit(runs)) == ["RUN_GENLOG_JSON_INVALID"]

    def test_cu_without_successful_call_is_unlinked(self, tmp_path: Path) -> None:
        """같은 slug의 호출이 있어도 실패 호출뿐이면 그 CU를 만든 호출이 아니다."""
        runs = _two_seat_runs(tmp_path)
        _write(
            runs / "eos197-a6-openrouter" / "cu.genlog.jsonl",
            [_log("wm-o-1", _CLOUD_MODEL, seed=None, success=False)],
        )
        assert _kinds(_audit(runs)) == ["RUN_GENLOG_UNLINKED"]

    @pytest.mark.parametrize("field", ["model_name", "prompt_version", "input_sha256"])
    def test_always_required_genlog_field_missing(self, tmp_path: Path, field: str) -> None:
        runs = _two_seat_runs(tmp_path)
        _write(
            runs / "eos197-a6-openrouter" / "cu.genlog.jsonl",
            [_log("wm-o-1", _CLOUD_MODEL, seed=None, **{field: None})],
        )
        report = _audit(runs)
        assert _kinds(report) == ["RUN_GENLOG_FIELDS_MISSING"]
        assert field in report.violations[0].detail

    def test_local_seat_seed_missing_is_a_violation(self, tmp_path: Path) -> None:
        """대조 — 클라우드 seed=null은 통과(위 정상 케이스), 로컬 seed=null은 위반."""
        runs = _two_seat_runs(tmp_path)
        _write(
            runs / "eos197-a6-local" / "cu.genlog.jsonl",
            [_log("wm-l-1", _LOCAL_MODEL, seed=11), _log("wm-l-2", _LOCAL_MODEL, seed=None)],
        )
        report = _audit(runs)
        assert _kinds(report) == ["RUN_GENLOG_FIELDS_MISSING"]
        assert "seed" in report.violations[0].detail

    def test_main_exit_1_on_injected_defect(self, tmp_path: Path) -> None:
        runs = _two_seat_runs(tmp_path)
        _write(
            runs / "eos197-a6-local" / "cu.jsonl",
            [_cu("wm-l-1", license=None), _cu("wm-l-2")],
        )
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        assert pa.main(["--corpus-root", str(corpus), "--runs-root", str(runs)]) == 1


class TestEmptyTargets:
    def test_default_root_absent_is_normal(self, tmp_path: Path) -> None:
        report = _audit(tmp_path / "없음", explicit=False)
        assert report.violations == []
        assert report.runs_scanned == 0
        assert report.runs_root is not None  # 검사는 했다 — None(검사 안 함)과 구분

    def test_explicit_root_absent_is_violation(self, tmp_path: Path) -> None:
        assert _kinds(_audit(tmp_path / "없음", explicit=True)) == ["RUNS_ROOT_MISSING"]

    def test_require_runs_turns_zero_runs_into_violation(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        (runs / "eos197-a6-review").mkdir(parents=True)  # 폴더는 있어도 cu.jsonl이 없다
        assert _kinds(_audit(runs, require_runs=True)) == ["RUNS_EMPTY"]
        assert _audit(_two_seat_runs(tmp_path / "x"), require_runs=True).violations == []

    def test_corpus_root_only_skips_runs_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        json_path = tmp_path / "r.json"
        assert pa.main(["--corpus-root", str(corpus), "--json", str(json_path)]) == 0
        assert "저작 회차      : 검사 안 함" in capsys.readouterr().out
        assert json.loads(json_path.read_text("utf-8"))["runs_root"] is None

    def test_require_runs_without_runs_root_is_argument_error(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            pa.main(["--corpus-root", str(tmp_path), "--require-runs"])
        assert excinfo.value.code == 2

    def test_default_runs_root_is_repo_data_runs(self) -> None:
        assert pa.default_runs_root() == pa.default_corpus_root().parent / "runs"

    def test_bare_cli_audits_default_runs_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """인자 없는 CLI(= CI 스텝·EOS-197 완료 검사의 형태)가 기본 회차 루트를 실제로 검사한다.

        정본 경로 두 개를 tmp로 바꾸고, 회차에 결함을 넣어 exit 1을 본다 — 기본 경로 분기가
        회차를 건너뛰면 corpus는 비어 있으므로 exit 0이 나와 RED가 된다.
        """
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        runs = _two_seat_runs(tmp_path)
        monkeypatch.setattr(pa, "default_corpus_root", lambda: corpus)
        monkeypatch.setattr(pa, "default_runs_root", lambda: runs)
        assert pa.main([]) == 0  # 대조 — 결함 없는 회차
        _write(runs / "eos197-a6-local" / "cu.jsonl", [_cu("wm-l-1", source_type=None)])
        assert pa.main([]) == 1
        assert pa.main(["--require-runs"]) == 1


# ──────────────────────────────────────────────────────────────────────
# ④ 실 생산자 산출물 — 저작 CLI가 쓴 파일을 그대로 감사
# ──────────────────────────────────────────────────────────────────────
_STANDARD = "[12미적Ⅰ-02-07]"
_ACCEPT = json.dumps(
    {
        "question_text": "이차방정식 x^2 - 40x + 391 = 0 의 두 근 중 더 큰 근을 구하시오.",
        "answer": "23",
        "answer_explanation": "(x-17)(x-23)=0 이므로 두 근은 17과 23이고, 더 큰 근은 23이다.",
        "conditions": "x**2 - 40*x + 391 = 0",
        "answer_map": {"x": "23"},
        "answer_selection": "largest",
        "difficulty_overall": 2.5,
        "unit_codes": ["CALC1-EXT"],
        "answer_format": "자연수",
        "achievement_standard_codes": [_STANDARD],
    },
    ensure_ascii=False,
)


class _ScriptedProvider:
    """대본 provider — 유일한 대역(LLM 호출부). 소진 시 IndexError(조용한 순환 금지)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        out = self._responses[self._index]
        self._index += 1
        return GenerationResult(
            out, usage=Usage(input_tokens=50, output_tokens=120, latency_ms=42.0)
        )


class TestRealProducerOutput:
    def _produce(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

        def _build(
            topic_hint: str,
            *,
            generation_log_sink: object = None,
            subject: str = "공통",
            slug_prefix: str = "wm-gen-quad",
            **_routing: object,
        ) -> LLMEquivalentProblemGenerator:
            return LLMEquivalentProblemGenerator(
                _ScriptedProvider([_ACCEPT]),  # type: ignore[arg-type]
                misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
                topic_hint=topic_hint,
                subject=Subject(subject),
                slug_prefix=slug_prefix,
                generation_log_sink=generation_log_sink,  # type: ignore[arg-type]
            )

        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", _build)
        runs = tmp_path / "runs"
        out = runs / "eos197-a6-local" / "cu.jsonl"
        code = problem_corpus_accumulate.main(
            [
                "--out",
                str(out),
                "--n",
                "1",
                "--standard-code",
                _STANDARD,
                "--difficulty",
                "2.5",
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert code == 0, "대본 1건이 수용되지 않았다 — 픽스처가 게이트를 못 넘는다"
        assert len(out.read_text("utf-8").splitlines()) == 1
        return runs

    def test_producer_output_passes_and_seed_is_actually_checked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = self._produce(tmp_path, monkeypatch)
        record = json.loads((runs / "eos197-a6-local" / "cu.jsonl").read_text("utf-8"))
        # G-D 관통 — A6 코드로 돈 산출물은 과목 미적분·접두 wm-gen-calc1로 기록된다.
        assert record["subject"] == "미적분"
        assert record["slug"].startswith("wm-gen-calc1-")
        report = _audit(runs)
        assert report.violations == [], report.violations
        assert report.run_cu_records == 1
        # 대본 provider도 로컬 결정을 받으므로 seed가 실린다 — 검사가 실제로 일했다.
        assert report.seed_checked == 1

    def test_same_output_with_prompt_version_erased_is_red(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runs = self._produce(tmp_path, monkeypatch)
        genlog = runs / "eos197-a6-local" / "cu.genlog.jsonl"
        rows = [json.loads(line) for line in genlog.read_text("utf-8").splitlines() if line]
        assert any(r.get("prompt_version") for r in rows)
        for r in rows:
            r["prompt_version"] = None
        _write(genlog, rows)
        assert _kinds(_audit(runs)) == ["RUN_GENLOG_FIELDS_MISSING"]
