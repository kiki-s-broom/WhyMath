"""EOS-55 집행 별항(정본화≠집행) — 두 생성 경로가 GenerationLog를 **실제로 적재**하는지 동결.

스키마 좌석의 실재(acceptance ①)와 적재 배선은 다르다 — 이 테스트가 없으면 컬럼만 있고
아무도 쓰지 않는 상태가 "돌아간다"로 읽힌다(이 태스크의 존재 이유). 동결 축:

  A. **pregenerate 경로**: `CachePrewarmer`가 항목마다(성공·스킵·검증실패·오류 전부)
     GenerationLog를 싱크로 흘리고, CLI(`l3.pregenerate.__main__._run`)가 기본 사이드카
     JSONL에 적재하며, `main`이 `--generation-log`를 관통시킨다.
  B. **problem_corpus_accumulate 경로**: `LLMEquivalentProblemGenerator`가 LLM 호출마다
     (성공·provider 예외·JSON 파싱 실패 전부) 로그를 흘리고, `main()`이 기본 사이드카
     JSONL 싱크를 생성기에 배선한다.
  공통: 적재된 레코드는 **레코드만으로 입력이 복원**된다(acceptance ② 계약이 실제 배선
  산출물 위에서도 성립) + 관측 적재 실패는 배치를 깨지 않는다(never-break·타입명 로그).

전부 hermetic — 실 네트워크·LLM·Redis 0(FakeProvider·InMemoryCache 주입).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.problem_corpus_accumulate import (
    default_generation_log_path,
    run_corpus_accumulate,
)
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.interfaces import InMemoryCache
from whymath_backend.l3.models import GenerationResult, RoutingDecision, RoutingRequest, Usage
from whymath_backend.l3.pregenerate.__main__ import _run
from whymath_backend.l3.pregenerate.__main__ import main as pregen_main
from whymath_backend.l3.pregenerate.models import PregenItem
from whymath_backend.l3.pregenerate.prewarmer import CachePrewarmer
from whymath_backend.l3.pregenerate.provenance_bridge import (
    append_generation_log_jsonl,
    load_generation_logs_jsonl,
    model_name_for_decision,
)
from whymath_backend.l3.router import Router
from whymath_backend.schema.provenance import GenerationLog, restore_input_snapshot, text_sha256


# ──────────────────────────────────────────────────────────────────────
# 공용 대역 — 네트워크 0
# ──────────────────────────────────────────────────────────────────────
class FakeProvider:
    """스크립트 응답 provider 대역 — 프롬프트·결정 캡처(usage 실측 시뮬)."""

    def __init__(self, responses: Sequence[str], *, raises: Exception | None = None) -> None:
        self._responses = list(responses)
        self._raises = raises
        self._index = 0
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.decisions: list[RoutingDecision] = []
        # EOS-73 — provider에 실제로 실려 온 시드(호출 순서대로). None이면 안 실림.
        self.seeds: list[int | None] = []

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
        self.prompts.append(prompt)
        self.systems.append(system)
        self.decisions.append(decision)
        self.seeds.append(seed)
        if self._raises is not None:
            raise self._raises
        out = self._responses[self._index % len(self._responses)]
        self._index += 1
        return GenerationResult(
            out, usage=Usage(input_tokens=50, output_tokens=120, latency_ms=42.6)
        )


class AlwaysPassValidator:
    """검증 게이트 통과 대역."""

    def validate(self, item: PregenItem, response: str) -> None:
        return None


class AlwaysFailValidator:
    """검증 게이트 실패 대역 — failed_validation 경로 유도."""

    def validate(self, item: PregenItem, response: str) -> Any:
        from whymath_backend.l3.pregenerate.models import ValidationSignal

        return ValidationSignal(kind="other", reason="테스트 실패 사유")


def _request(**overrides: object) -> RoutingRequest:
    base: dict[str, object] = {
        "task_type": "explain",
        "difficulty": "easy",
        "requires_reasoning": False,
        "student_subscription": "free",
        "sync": True,
    }
    base.update(overrides)
    return RoutingRequest(**base)  # type: ignore[arg-type]


def _item(**overrides: object) -> PregenItem:
    base: dict[str, object] = {
        "prompt": "사전적재 프롬프트",
        "system": "시스템",
        "request": _request(),
    }
    base.update(overrides)
    return PregenItem(**base)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# A-1. CachePrewarmer — 항목마다 싱크 적재(성공 경로만 보지 않는다)
# ──────────────────────────────────────────────────────────────────────
class TestPrewarmerEmitsGenerationLog:
    def _prewarm(
        self,
        items: list[PregenItem],
        *,
        provider: FakeProvider | None = None,
        validator: object | None = None,
        cache: object | None = None,
    ) -> tuple[list[GenerationLog], object]:
        sink_logs: list[GenerationLog] = []
        prewarmer = CachePrewarmer(
            provider=provider if provider is not None else FakeProvider(["시드 응답"]),
            cache=cache if cache is not None else InMemoryCache(),  # type: ignore[arg-type]
            validator=validator if validator is not None else AlwaysPassValidator(),  # type: ignore[arg-type]
            generation_log_sink=sink_logs.append,
        )
        report = asyncio.run(prewarmer.prewarm(items))
        return sink_logs, report

    def test_written_item_logged_with_reproducibility_seats(self) -> None:
        """written 항목 → success=True + 모델명·비용 0원 확정·시드·스냅샷 복원(재현 계약 성립)."""
        item = _item()
        provider = FakeProvider(["시드 응답"])
        logs, _ = self._prewarm([item], provider=provider)
        provider_seeds = provider.seeds
        assert len(logs) == 1
        log = logs[0]
        assert log.success is True
        assert log.model_name == model_name_for_decision(Router().route(item.request))
        assert log.cost_usd == 0.0  # LOCAL 0원 확정
        assert log.input_tokens == 50 and log.output_tokens == 120  # provider 실측 전달
        assert log.problem_id is None  # 사전적재 시드=problem 레코드 없음(정직 NULL)
        assert log.prompt_version is None  # 템플릿 체계 없는 경로 — 미기록(번호 발명 금지)
        # EOS-73: seed 좌석이 더 이상 비어 있지 않다 — provider에 실려 나간 값과 **같은 값**이
        # 기록된다(기록≠전달이면 재현 계약이 성립하지 않는다).
        assert log.seed is not None
        assert log.seed == provider_seeds[0]
        assert log.cu_slug is None  # CU 정체성 없는 경로 — 미기록(#912 P1-2 정직 NULL)
        # 강화 재현 계약(#912 P1-1): 레코드만으로 provider에 **다시 넣을 전문**이 나온다.
        restored = restore_input_snapshot(log)
        assert restored["prompt"] == item.prompt  # 전문(verbatim) — 재투입 가능 바이트
        assert restored["system"] == item.system
        assert restored["prompt_sha256"] == text_sha256(restored["prompt"])  # 핀 자기정합
        assert RoutingRequest.model_validate(restored["request"]) == item.request

    def test_failed_validation_logged_false_with_reason(self) -> None:
        """검증 실패 항목도 기록된다 — success=False + 사유(성공 경로만 보는 계측 금지)."""
        logs, _ = self._prewarm([_item()], validator=AlwaysFailValidator())
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].error_detail == "테스트 실패 사유"

    def test_async_quality_error_logged(self) -> None:
        """QUALITY async 오류 항목도 기록 — 모델명은 QUALITY 해석(family 무관·크래시 없음)."""
        item = _item(
            request=_request(
                task_type="prove", difficulty="killer", requires_reasoning=True, sync=False
            )
        )
        logs, report = self._prewarm([item])
        assert report.errored == 1  # type: ignore[attr-defined]
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].model_name == "qwen3:30b-a3b"  # QUALITY_MODEL_ID(03a §A.0)
        assert restore_input_snapshot(logs[0])["prompt_sha256"] == text_sha256(item.prompt)

    def test_skipped_exists_logged_true(self) -> None:
        """이미 적재된 키 스킵도 기록 — 유효 시드 확보=success True(브리지 계약 그대로)."""
        cache = InMemoryCache()
        first_logs: list[GenerationLog] = []
        prewarmer = CachePrewarmer(
            provider=FakeProvider(["시드 응답"]),
            cache=cache,  # type: ignore[arg-type]
            validator=AlwaysPassValidator(),  # type: ignore[arg-type]
            generation_log_sink=first_logs.append,
        )
        asyncio.run(prewarmer.prewarm([_item()]))  # 1회차 written
        asyncio.run(prewarmer.prewarm([_item()]))  # 2회차 skipped_exists
        assert [log.success for log in first_logs] == [True, True]
        assert first_logs[1].input_tokens is None  # 스킵=호출 없음 → usage 미기록(날조 금지)

    def test_sink_failure_never_breaks_batch(self, caplog: pytest.LogCaptureFixture) -> None:
        """싱크 예외는 배치를 깨지 않고 **타입명**이 경고에 남는다(침묵 실패 금지)."""

        def _raising_sink(log: GenerationLog) -> None:
            raise OSError("디스크 가득(테스트)")

        prewarmer = CachePrewarmer(
            provider=FakeProvider(["시드 응답"]),
            cache=InMemoryCache(),  # type: ignore[arg-type]
            validator=AlwaysPassValidator(),  # type: ignore[arg-type]
            generation_log_sink=_raising_sink,
        )
        with caplog.at_level(logging.WARNING, logger="whymath.l3.pregenerate.prewarmer"):
            report = asyncio.run(prewarmer.prewarm([_item()]))
        assert report.written == 1  # 사전적재 자체는 성공(관측 장애 비차단)
        assert any("OSError" in rec.message for rec in caplog.records)

    def test_no_sink_keeps_legacy_behavior(self) -> None:
        """싱크 미주입(기본) — 종전 동작 그대로(기존 호출부 무영향)."""
        prewarmer = CachePrewarmer(
            provider=FakeProvider(["시드 응답"]),
            cache=InMemoryCache(),  # type: ignore[arg-type]
            validator=AlwaysPassValidator(),  # type: ignore[arg-type]
        )
        report = asyncio.run(prewarmer.prewarm([_item()]))
        assert report.written == 1


# ──────────────────────────────────────────────────────────────────────
# A-2. pregenerate CLI — 기본 사이드카 적재 + --generation-log 관통
# ──────────────────────────────────────────────────────────────────────
class TestPregenerateCliWiring:
    def _specs_file(self, tmp_path: Path) -> Path:
        specs = tmp_path / "specs.jsonl"
        item = _item()
        specs.write_text(item.model_dump_json() + "\n", encoding="utf-8")
        return specs

    def test_run_writes_default_sidecar_genlog(self, tmp_path: Path) -> None:
        """CLI 본처리(_run)가 기본 사이드카 `<specs>.genlog.jsonl`에 실제 적재한다(③ 본체)."""
        specs = self._specs_file(tmp_path)
        code = asyncio.run(
            _run(
                specs,
                overwrite=False,
                ttl_seconds=0,
                min_length=1,
                provider=FakeProvider(["시드 응답"]),  # type: ignore[arg-type]
                cache=InMemoryCache(),  # type: ignore[arg-type]
            )
        )
        assert code == 0
        sidecar = tmp_path / "specs.genlog.jsonl"
        assert sidecar.exists()
        loaded, errors = load_generation_logs_jsonl(sidecar)
        assert errors == []
        assert len(loaded) == 1
        assert loaded[0].success is True
        # 적재 산출물 위에서 재현 계약 성립(레코드만으로 입력 복원).
        assert restore_input_snapshot(loaded[0])["kind"] == "l3.pregenerate.prewarm"

    def test_run_honors_custom_genlog_path(self, tmp_path: Path) -> None:
        """--generation-log 경로 지정 시 그 경로에만 적재된다."""
        specs = self._specs_file(tmp_path)
        custom = tmp_path / "다른곳" / "runlog.jsonl"
        code = asyncio.run(
            _run(
                specs,
                overwrite=False,
                ttl_seconds=0,
                min_length=1,
                generation_log_path=custom,
                provider=FakeProvider(["시드 응답"]),  # type: ignore[arg-type]
                cache=InMemoryCache(),  # type: ignore[arg-type]
            )
        )
        assert code == 0
        assert custom.exists()
        assert not (tmp_path / "specs.genlog.jsonl").exists()

    def test_main_forwards_generation_log_arg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI 파서가 --generation-log를 _run까지 관통시킨다(인자 배선 동결)."""
        captured: dict[str, object] = {}

        async def _fake_run(specs_path: Path, **kwargs: object) -> int:
            captured.update(kwargs)
            captured["specs_path"] = specs_path
            return 0

        import whymath_backend.l3.pregenerate.__main__ as cli

        monkeypatch.setattr(cli, "_run", _fake_run)
        specs = self._specs_file(tmp_path)
        custom = tmp_path / "cli.genlog.jsonl"
        assert pregen_main([str(specs), "--generation-log", str(custom)]) == 0
        assert captured["generation_log_path"] == custom
        assert pregen_main([str(specs)]) == 0
        assert captured["generation_log_path"] is None  # 미지정 → _run이 사이드카 기본값 적용


# ──────────────────────────────────────────────────────────────────────
# B. problem_corpus_accumulate 경로 — 생성기 호출별 적재 + main 배선
# ──────────────────────────────────────────────────────────────────────
_STANDARD = "[10공수1-02-02]"

# 조립·게이트 재료를 갖춘 정상 응답(테스트 스크립트) — 큰 근 3(검증 가능 단답).
_HAPPY = json.dumps(
    {
        "question_text": "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오.",
        "answer": "3",
        "answer_explanation": "인수분해하면 (x-2)(x-3)=0, 두 근은 2와 3, 큰 근은 3.",
        "conditions": "x**2 - 5*x + 6 = 0",
        "answer_map": {"x": "3"},
        "answer_selection": "largest",
        "difficulty_overall": 3.0,
        "unit_codes": ["ALG-QUAD-EQ"],
        "answer_format": "자연수",
        "achievement_standard_codes": [_STANDARD],
    },
    ensure_ascii=False,
)


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({_STANDARD}),
        target_misconception_ids=frozenset(),
        difficulty_overall=3.0,
        answer_format=None,
    )


def _generator(
    provider: FakeProvider, sink_logs: list[GenerationLog]
) -> LLMEquivalentProblemGenerator:
    return LLMEquivalentProblemGenerator(
        provider,  # type: ignore[arg-type]
        misconception_catalog={},
        topic_hint="이차방정식 — 두 근 중 큰 근",
        generation_log_sink=sink_logs.append,
    )


class TestAccumulateGeneratorEmitsGenerationLog:
    def test_successful_call_logged_with_prompt_version_and_snapshot(self) -> None:
        """성공 호출 → success=True + prompt_version(정본 해시)·모델명·**전문 복원**·cu_slug."""
        provider = FakeProvider([_HAPPY])
        logs: list[GenerationLog] = []
        candidate = _generator(provider, logs).generate(_spec())
        assert candidate is not None  # 전제: 조립 성공
        assert len(logs) == 1
        log = logs[0]
        assert log.success is True
        assert log.prompt_version is not None
        assert log.prompt_version.startswith("l3.equivalent@sha256:")
        assert log.model_name == model_name_for_decision(provider.decisions[0])
        assert log.cost_usd == 0.0  # free 구독 → LOCAL 0원 확정
        # EOS-73: 실려 나간 시드와 기록된 시드가 같아야 재투입 좌표가 의미를 갖는다.
        assert log.seed is not None
        assert log.seed == provider.seeds[0]
        # CU 조인 정체성(#912 P1-2) — 조립된 후보의 코퍼스 키(안정 slug)와 동일.
        assert log.cu_slug == candidate.problem.slug
        # 강화 재현 계약(#912 P1-1): 레코드만으로 provider에 **다시 넣은 전문 그대로**가
        # 나온다 — 해시 일치만으로는 계약 미성립(specs·정본이 바뀌면 재구성 불가).
        restored = restore_input_snapshot(log)
        assert restored["kind"] == "l3.equivalent.llm_generate"
        assert restored["prompt"] == provider.prompts[0]  # 전문(verbatim) = 실제 전송 바이트
        assert restored["system"] == provider.systems[0]
        assert restored["prompt_sha256"] == text_sha256(restored["prompt"])  # 핀 자기정합
        assert restored["system_sha256"] == text_sha256(restored["system"])
        assert restored["spec"]["achievement_standard_codes"] == [_STANDARD]
        assert restored["topic_hint"] == "이차방정식 — 두 근 중 큰 근"

    def test_provider_failure_logged_false_with_type_name(self) -> None:
        """provider 예외 → None 폴백이어도 호출 *시도*가 success=False로 남는다(usage 미상)."""
        provider = FakeProvider([], raises=RuntimeError("provider 다운(테스트)"))
        logs: list[GenerationLog] = []
        assert _generator(provider, logs).generate(_spec()) is None
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].error_detail is not None and "RuntimeError" in logs[0].error_detail
        assert logs[0].input_tokens is None  # 실측 없음 — 날조 금지
        assert logs[0].cu_slug is None  # 후보 조립 전 실패 — CU 정체성 미기록(정직)

    def test_parse_failure_logged_false_with_usage(self) -> None:
        """JSON 파싱 실패 → success=False, 단 실측 usage(비용 발생분)는 기록된다."""
        provider = FakeProvider(["JSON 아님)))"])
        logs: list[GenerationLog] = []
        assert _generator(provider, logs).generate(_spec()) is None
        assert len(logs) == 1
        assert logs[0].success is False
        assert logs[0].error_detail == "응답 JSON 파싱 실패"
        assert logs[0].input_tokens == 50  # 호출은 성사 — 실측 보존
        assert logs[0].cu_slug is None  # 후보 조립 전 실패 — CU 정체성 미기록(정직)

    def test_run_corpus_accumulate_glue_produces_logs(self, tmp_path: Path) -> None:
        """main()이 잇는 조립 그대로(생성기+싱크 → run_corpus_accumulate) 호출별 적재."""
        provider = FakeProvider([_HAPPY])
        logs: list[GenerationLog] = []
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=_generator(provider, logs),
            spec=_spec(),
            n=3,
        )
        assert report.attempted == 3
        assert len(logs) == 3  # LLM 호출 1건당 로그 1건(게이트 판정과 무관하게 전건)
        assert all(
            restore_input_snapshot(log)["kind"] == "l3.equivalent.llm_generate" for log in logs
        )


class TestSidecarJoinsHitCuMetrics:
    """#912 P1-2 본체 — accumulate 사이드카가 문서화된 소비자(hit_cu_metrics)와 실제 조인.

    cu_slug가 없으면 aggregate의 CU당 비용 조인이 전건 unmatched로 떨어져 CU당 토큰·비용
    측정이 0이 된다(codex 지적 그대로). 실경로 사이드카 산출물을 genlog_rows로 넣어 조인
    성립을 동결한다 — 소비자 접속이 이 태스크의 집행 별항(acceptance ③)이다.
    """

    def test_accumulate_sidecar_rows_join_cu_costs(self, tmp_path: Path) -> None:
        """사이드카 행 → aggregate 조인: matched 전건·cu_with_cost ≥ 1·$0 실기록≠미기록."""
        from whymath_backend.harness.review_timer import finish_review, start_review
        from whymath_backend.ops.hit_cu_metrics import aggregate

        # ① 실경로 그대로 사이드카 생산 — 생성기+JSONL appender 싱크+run_corpus_accumulate.
        provider = FakeProvider([_HAPPY])
        sidecar = tmp_path / "acc.genlog.jsonl"
        generator = LLMEquivalentProblemGenerator(
            provider,  # type: ignore[arg-type]
            misconception_catalog={},
            topic_hint="이차방정식 — 두 근 중 큰 근",
            generation_log_sink=lambda log: append_generation_log_jsonl(sidecar, log),
        )
        run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=generator,
            spec=_spec(),
            n=2,
        )
        # ② 문서화된 소비자가 읽는 형태 그대로 — JSONL 행 dict(model dump라 cu_slug가
        #    top-level에 실려 aggregate의 조인 키 `row.get("cu_slug")`에 바로 잡힌다).
        rows = [
            json.loads(line)
            for line in sidecar.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == 2
        slug = rows[0]["cu_slug"]
        assert isinstance(slug, str) and slug  # 성공 종단 전건에 CU 정체성 실림
        # ③ 같은 CU의 검수 타이머 페어와 함께 집계 — CU당 비용 조인 성립.
        started = start_review(cu_slug=slug, reviewer_id="rev-1")
        finished = finish_review(
            review_session_id=started.review_session_id,
            cu_slug=slug,
            reviewer_id="rev-1",
            verdict="approved",
            elapsed_ms=60_000,
        )
        report = aggregate([started, finished], genlog_rows=rows)
        assert report.cost_rows_matched == 2  # 전건 조인 — unmatched 전락(P1 증상) 해소
        assert report.cost_rows_unmatched == 0
        # 로컬 경로 cost_usd=0.0은 **실기록**이다 — 미기록(null)으로 오독되면 CU가
        # 불완전 계측으로 강등돼 cu_with_cost=0이 된다(0.0≠null 구분의 변별 단언).
        assert report.cu_with_cost == 1
        assert report.cost_usd_total == 0.0  # $0 확정(미산출 None과 구분)
        assert report.tokens_total == 2 * (50 + 120)  # provider 실측 토큰 합


class TestAccumulateMainWiring:
    def test_main_wires_default_sidecar_sink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """main()이 기본 사이드카 싱크를 생성기에 배선한다 — 싱크로 흘린 로그가 파일에 실재.

        라이브 생성기 조립을 스텁으로 바꾸되 **main이 만든 싱크를 그대로 사용**해, 인자
        파싱→싱크 생성→생성기 주입→JSONL 적재의 전 배선을 실측한다(정본화≠집행).
        """
        emitted = GenerationLog(model_name="stub-model", input_snapshot={"kind": "stub"})

        class _SinkUsingGenerator:
            def __init__(self, sink: object) -> None:
                self._sink = sink

            def generate(self, spec: EquivalenceSpec) -> None:
                # 실제 생성기처럼 호출 시점에 싱크로 로그를 흘린다(그 후 생성 실패 폴백).
                assert callable(self._sink)
                self._sink(emitted)
                return None

        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _SinkUsingGenerator(kwargs.get("generation_log_sink")),
        )
        out = tmp_path / "accumulated.jsonl"
        code = problem_corpus_accumulate.main(["--out", str(out), "--n", "2"])
        assert code == 1  # 전건 generation_failed → 무진전(기존 계약 그대로)
        capsys.readouterr()  # 리포트 stdout 소거
        sidecar = default_generation_log_path(out)
        assert sidecar == tmp_path / "accumulated.genlog.jsonl"
        loaded, errors = load_generation_logs_jsonl(sidecar)
        assert errors == []
        assert len(loaded) == 2  # 시도 2회 = 로그 2건
        assert all(log.model_name == "stub-model" for log in loaded)

    def test_main_honors_custom_genlog_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--generation-log 지정 시 사이드카 대신 그 경로에 적재된다."""
        captured_paths: list[GenerationLog] = []

        class _EmittingGenerator:
            def __init__(self, sink: object) -> None:
                self._sink = sink

            def generate(self, spec: EquivalenceSpec) -> None:
                assert callable(self._sink)
                self._sink(GenerationLog(model_name="stub-model"))
                return None

        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _EmittingGenerator(kwargs.get("generation_log_sink")),
        )
        out = tmp_path / "accumulated.jsonl"
        custom = tmp_path / "로그" / "run.jsonl"
        code = problem_corpus_accumulate.main(
            ["--out", str(out), "--n", "1", "--generation-log", str(custom)]
        )
        assert code == 1
        capsys.readouterr()
        assert custom.exists()
        assert not default_generation_log_path(out).exists()
        del captured_paths  # 명시적 미사용(경로 검증이 목적)
