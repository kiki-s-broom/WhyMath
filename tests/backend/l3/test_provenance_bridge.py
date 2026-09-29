"""`provenance_bridge.generation_log_from_result` 단위 테스트 — status별 success 매핑.

설계 정본: `l3/pregenerate/provenance_bridge.py`. 계층 규칙상 사전생성 결과를
`GenerationLog`(schema)로 바꾸는 연결 코드는 L3쪽에 있다(schema는 l3 import 0).

검증:
  - status별 success 매핑(written/skipped_exists=True, failed_validation/error=False)
  - error 전달(error_detail로 그대로 옮겨짐)
  - 기본 None 텔레메트리(토큰/비용/지연 — provider가 usage 미노출)
  - 인자 전달(problem_id/model_name/provenance_id/prompt_template_id)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.data_grade_defaults import SELF_AUTHORED_CORPUS
from whymath_backend.l3.models import RoutingRequest, Usage
from whymath_backend.l3.pregenerate.models import PregenItem, PrewarmItemResult, PrewarmStatus
from whymath_backend.l3.pregenerate.provenance_bridge import (
    actual_cost_usd_or_none,
    append_generation_log_jsonl,
    generation_log_from_result,
    input_snapshot_for_prewarm,
    load_generation_logs_jsonl,
    model_name_for_decision,
)
from whymath_backend.l3.router import Router
from whymath_backend.schema.provenance import (
    input_snapshot_sha256,
    restore_input_snapshot,
    text_sha256,
)


def _result(status: PrewarmStatus, error: str | None = None) -> PrewarmItemResult:
    """주어진 status의 PrewarmItemResult(테스트 헬퍼)."""
    return PrewarmItemResult(cache_key="k1", status=status, error=error)


# ──────────────────────────────────────────────────────────────────────
# status → success 매핑
# ──────────────────────────────────────────────────────────────────────
class TestSuccessMapping:
    @pytest.mark.parametrize("status", ["written", "skipped_exists"])
    def test_success_statuses_map_true(self, status: PrewarmStatus) -> None:
        """written·skipped_exists = 유효 시드 확보 = success True."""
        log = generation_log_from_result(
            _result(status),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.success is True

    @pytest.mark.parametrize("status", ["failed_validation", "error"])
    def test_failure_statuses_map_false(self, status: PrewarmStatus) -> None:
        """failed_validation·error = 시드 미확보 = success False."""
        log = generation_log_from_result(
            _result(status, error="some reason"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.success is False


# ──────────────────────────────────────────────────────────────────────
# error 전달
# ──────────────────────────────────────────────────────────────────────
class TestErrorPropagation:
    def test_error_passed_to_error_detail(self) -> None:
        """result.error → GenerationLog.error_detail로 그대로 옮겨짐."""
        log = generation_log_from_result(
            _result("failed_validation", error="SymPy: 1=2 거짓"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.error_detail == "SymPy: 1=2 거짓"

    def test_none_error_on_success(self) -> None:
        """성공 status는 error=None → error_detail None."""
        log = generation_log_from_result(
            _result("written"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.error_detail is None


# ──────────────────────────────────────────────────────────────────────
# 텔레메트리 — 항상 None(provider usage 미노출)
# ──────────────────────────────────────────────────────────────────────
class TestTelemetryNone:
    def test_telemetry_fields_are_none(self) -> None:
        """토큰/비용/지연은 지어내지 않고 None(provider가 usage 미노출)."""
        log = generation_log_from_result(
            _result("written"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.input_tokens is None
        assert log.output_tokens is None
        assert log.cost_usd is None
        assert log.latency_ms is None
        assert log.generated_at is None


# ──────────────────────────────────────────────────────────────────────
# 인자 전달
# ──────────────────────────────────────────────────────────────────────
class TestArgumentPassthrough:
    def test_required_args_passed(self) -> None:
        """problem_id·model_name은 필수 인자에서 그대로 옮겨짐."""
        pid = uuid.uuid4()
        log = generation_log_from_result(
            _result("written"),
            problem_id=pid,
            model_name="claude-opus-4-7",
        )
        assert log.problem_id == pid
        assert log.model_name == "claude-opus-4-7"

    def test_optional_args_default_none(self) -> None:
        """provenance_id·prompt_template_id는 기본 None."""
        log = generation_log_from_result(
            _result("written"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
        )
        assert log.provenance_id is None
        assert log.prompt_template_id is None

    def test_optional_args_passed(self) -> None:
        """provenance_id·prompt_template_id를 주면 그대로 옮겨짐."""
        prov = uuid.uuid4()
        tmpl = uuid.uuid4()
        log = generation_log_from_result(
            _result("skipped_exists"),
            problem_id=uuid.uuid4(),
            model_name="qwen3-32b",
            provenance_id=prov,
            prompt_template_id=tmpl,
        )
        assert log.provenance_id == prov
        assert log.prompt_template_id == tmpl


# ──────────────────────────────────────────────────────────────────────
# 텔레메트리 — usage(실측) 주입 시 GenerationLog 적재 (S1 게이트 ②)
# ──────────────────────────────────────────────────────────────────────
class TestTelemetryFromUsage:
    def test_usage_fields_loaded(self) -> None:
        """result.usage(토큰·지연 실측) + cost_usd 인자 → GenerationLog 4필드 적재."""
        result = PrewarmItemResult(
            cache_key="k1",
            status="written",
            usage=Usage(input_tokens=120, output_tokens=340, latency_ms=1234.6),
        )
        log = generation_log_from_result(
            result,
            problem_id=uuid.uuid4(),
            model_name="qwen3:30b-a3b",
            cost_usd=0.0,  # 로컬 사전생성 = 0달러 확정
        )
        assert log.input_tokens == 120
        assert log.output_tokens == 340
        assert log.latency_ms == 1235  # float(ms) 실측 → int 반올림(스키마 계약)
        assert log.cost_usd == 0.0
        assert log.success is True

    def test_partial_usage_only_known_fields(self) -> None:
        """usage에 지연만 있으면 지연만 적재 — 토큰은 None 유지(지어내지 않음)."""
        result = PrewarmItemResult(
            cache_key="k1",
            status="written",
            usage=Usage(input_tokens=None, output_tokens=None, latency_ms=88.2),
        )
        log = generation_log_from_result(
            result, problem_id=uuid.uuid4(), model_name="qwen2-math:7b"
        )
        assert log.input_tokens is None
        assert log.output_tokens is None
        assert log.latency_ms == 88
        assert log.cost_usd is None  # cost_usd 미지정 → None(기본)


# ──────────────────────────────────────────────────────────────────────
# EOS-55 재현 좌석 — 스냅샷 조립·모델명 해석·비용 미상 구분·JSONL 적재
# ──────────────────────────────────────────────────────────────────────
def _request(**overrides: object) -> RoutingRequest:
    # `data_licenses`는 *반출 가능*(자체 저작)으로 고정한다 — 이 파일은 provenance 좌석·비용
    # 산정을 재는 곳이고, 데이터 등급 게이트(EOS-59)가 켜져 있으면 클라우드 단언이 전부 그
    # 게이트 탓에 LOCAL이 되어 원래 재려던 축을 못 재게 된다(등급 축은 test_data_export_policy).
    base: dict[str, object] = {
        "task_type": "explain",
        "difficulty": "easy",
        "requires_reasoning": False,
        "student_subscription": "free",
        "sync": True,
        "data_licenses": SELF_AUTHORED_CORPUS,
    }
    base.update(overrides)
    return RoutingRequest(**base)  # type: ignore[arg-type]


def _item(**overrides: object) -> PregenItem:
    base: dict[str, object] = {
        "prompt": "이차방정식 x^2-5x+6=0의 큰 근은?",
        "system": "간결히 답하라.",
        "request": _request(),
    }
    base.update(overrides)
    return PregenItem(**base)  # type: ignore[arg-type]


class TestReproducibilitySeatsPassthrough:
    def test_prompt_version_seed_snapshot_passed(self) -> None:
        """재현 좌석 4인자(prompt_version·seed·input_snapshot·cu_slug)가 실리고 해시가 봉인된다."""
        snapshot = input_snapshot_for_prewarm(_item())
        log = generation_log_from_result(
            _result("written"),
            problem_id=None,
            model_name="qwen2-math:1.5b",
            prompt_version="v-test",
            seed=1234,
            input_snapshot=snapshot,
            cu_slug="wm-gen-quad-abc123def456",
        )
        assert log.problem_id is None  # 사전적재 시드=problem 레코드 없음(정직 NULL)
        assert log.prompt_version == "v-test"
        assert log.seed == 1234
        assert log.cu_slug == "wm-gen-quad-abc123def456"  # CU 조인 정체성(#912 P1-2)
        assert log.input_sha256 == input_snapshot_sha256(snapshot)
        assert restore_input_snapshot(log) == snapshot

    def test_seats_default_unrecorded(self) -> None:
        """좌석 미전달 시 전부 None=미기록 — 값을 지어내지 않는다(기존 계약 후방호환)."""
        log = generation_log_from_result(
            _result("written"), problem_id=uuid.uuid4(), model_name="qwen2-math:1.5b"
        )
        assert log.prompt_version is None
        assert log.seed is None
        assert log.input_sha256 is None
        assert log.input_snapshot is None
        assert log.cu_slug is None


class TestInputSnapshotForPrewarm:
    def test_snapshot_is_self_contained_verbatim_plus_pins(self) -> None:
        """스냅샷 자기완결(#912 P1-1) — prompt/system **전문** + sha256 병기 + request 원문.

        해시만으로는 모델 입력을 재구성할 수 없다 — specs 파일이 사라져도 스냅샷의 전문이
        provider에 재투입할 정확한 바이트다(재현 계약 본체).
        """
        item = _item()
        snapshot = input_snapshot_for_prewarm(item)
        assert snapshot["kind"] == "l3.pregenerate.prewarm"
        # 전문(verbatim) — provider에 다시 넣을 텍스트 그 자체.
        assert snapshot["prompt"] == item.prompt
        assert snapshot["system"] == item.system
        # 무결성 핀 — 담긴 전문과 해시가 자기모순 없이 정합.
        assert snapshot["prompt_sha256"] == text_sha256(snapshot["prompt"])
        assert snapshot["system_sha256"] == text_sha256(snapshot["system"])
        # request는 원문 복원 가능 — 재검증하면 원 라우팅 신호와 동치.
        revived = RoutingRequest.model_validate(snapshot["request"])
        assert revived == item.request

    def test_ingest_mode_stores_precomputed_response_verbatim(self) -> None:
        """인제스트 모드는 외부 시드 응답도 입력 — 전문+sha256 핀(생성 모드엔 키 없음)."""
        generated = input_snapshot_for_prewarm(_item())
        assert "precomputed_response" not in generated
        assert "precomputed_response_sha256" not in generated
        ingest = input_snapshot_for_prewarm(_item(precomputed_response="답은 3."))
        assert ingest["precomputed_response"] == "답은 3."
        assert ingest["precomputed_response_sha256"] == text_sha256("답은 3.")

    def test_snapshot_is_jsonb_safe(self) -> None:
        """스냅샷은 JSON 원시형만 — canonical 직렬화가 예외 없이 성립(JSONB 왕복 안정)."""
        assert isinstance(input_snapshot_sha256(input_snapshot_for_prewarm(_item())), str)


class TestModelNameForDecision:
    def test_local_decision_resolves_matrix_model(self) -> None:
        """LOCAL 결정은 라우터 매트릭스 해석과 동일한 실제 모델 ID를 낸다."""
        decision = Router().route(_request())
        assert model_name_for_decision(decision) == "qwen2-math:1.5b"

    def test_cloud_decisions_read_settings_models(self) -> None:
        """CLOUD_MID/HIGH는 Anthropic provider와 같은 설정 좌석을 읽는다(단일 근거).

        좌석을 `anthropic`으로 **명시**한다 — ARCH-64 이후 기본 좌석은 openrouter라, 명시하지 않으면
        이 테스트가 재는 축(anthropic 핀 오버라이드가 기록에 반영되는가)이 아니라 기본값 전환을 잰다.
        """
        settings = Settings(
            cloud_provider="anthropic",
            anthropic_model_mid="mid-model-x",
            anthropic_model_high="high-model-y",
        )
        mid = Router().route(
            _request(
                task_type="prove",
                difficulty="killer",
                requires_reasoning=True,
                student_subscription="basic",
                budget_krw=100.0,
            )
        )
        assert mid.cost_tier == "cloud_mid"  # 전제 확인(가드가 MID로 낙착)
        assert model_name_for_decision(mid, settings=settings) == "mid-model-x"
        high = Router().route(
            _request(
                task_type="prove",
                difficulty="killer",
                requires_reasoning=True,
                student_subscription="gifted",
                budget_krw=1000.0,
            )
        )
        assert high.cost_tier == "cloud_high"
        assert model_name_for_decision(high, settings=settings) == "high-model-y"


class TestActualCostUsdOrNone:
    def test_local_is_zero_even_without_usage(self) -> None:
        """LOCAL = 0원 확정(usage 유무 무관) — Phaiakes9 0원."""
        decision = Router().route(_request())
        assert actual_cost_usd_or_none(decision, None) == 0.0
        assert actual_cost_usd_or_none(decision, Usage(latency_ms=10.0)) == 0.0

    def test_cloud_unknown_tokens_is_none(self) -> None:
        """클라우드 + usage 없음/토큰 미상 → None(미상) — 0원 날조 금지."""
        decision = Router().route(
            _request(
                task_type="prove",
                difficulty="killer",
                requires_reasoning=True,
                student_subscription="basic",
                budget_krw=100.0,
            )
        )
        assert decision.cost_tier == "cloud_mid"  # 전제 확인
        assert actual_cost_usd_or_none(decision, None) is None
        assert actual_cost_usd_or_none(decision, Usage(input_tokens=10)) is None

    def test_cloud_measured_tokens_priced(self) -> None:
        """클라우드 + 실측 토큰 → 단가표 산정(0보다 큰 실측 비용)."""
        decision = Router().route(
            _request(
                task_type="prove",
                difficulty="killer",
                requires_reasoning=True,
                student_subscription="basic",
                budget_krw=100.0,
            )
        )
        cost = actual_cost_usd_or_none(decision, Usage(input_tokens=1000, output_tokens=1000))
        assert cost is not None and cost > 0.0


class TestGenerationLogJsonl:
    def test_append_and_load_roundtrip_restores_input(self, tmp_path: Path) -> None:
        """JSONL 왕복 후에도 레코드만으로 입력 복원(재현 계약의 매체측) + generated_at 스탬프."""
        path = tmp_path / "gen.genlog.jsonl"
        snapshot = input_snapshot_for_prewarm(_item())
        log = generation_log_from_result(
            _result("written"),
            problem_id=None,
            model_name="qwen2-math:1.5b",
            input_snapshot=snapshot,
        )
        stamped = append_generation_log_jsonl(path, log)
        assert stamped.generated_at is not None  # append=기록 시각 스탬프(JSONL 매체 계약)
        assert log.generated_at is None  # 원본 불변(model_copy)

        loaded, errors = load_generation_logs_jsonl(path)
        assert errors == []
        assert len(loaded) == 1
        assert restore_input_snapshot(loaded[0]) == snapshot
        assert loaded[0].model_name == "qwen2-math:1.5b"

    def test_append_flushes_per_record(self, tmp_path: Path) -> None:
        """레코드마다 즉시 flush — 2건 append 후 파일에 2행(도중 사망에도 이력 보존)."""
        path = tmp_path / "gen.genlog.jsonl"
        for _ in range(2):
            append_generation_log_jsonl(
                path,
                generation_log_from_result(_result("written"), problem_id=None, model_name="m"),
            )
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_load_collects_failure_reasons_without_values(self, tmp_path: Path) -> None:
        """파손 줄은 삼키지 않고 타입명+줄 번호로 수집 — 필드 값·원문은 싣지 않는다."""
        path = tmp_path / "gen.genlog.jsonl"
        good = generation_log_from_result(_result("written"), problem_id=None, model_name="m")
        append_generation_log_jsonl(path, good)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("깨진 JSON 줄\n")  # JSONDecodeError 유도
            fh.write('{"input_sha256": "XYZ"}\n')  # ValidationError 유도(형식 위반)
        loaded, errors = load_generation_logs_jsonl(path)
        assert len(loaded) == 1
        assert len(errors) == 2
        assert any("JSONDecodeError" in e for e in errors)
        assert any("ValidationError" in e and "input_sha256" in e for e in errors)
        assert all("XYZ" not in e for e in errors)  # 값 미출력(시크릿/필드값 제외 규칙)

    def test_load_rejects_tampered_snapshot_rows(self, tmp_path: Path) -> None:
        """디스크에서 변조된 스냅샷 행은 로드가 실패 사유로 드러낸다(읽기측 봉인)."""
        path = tmp_path / "gen.genlog.jsonl"
        snapshot = input_snapshot_for_prewarm(_item())
        log = generation_log_from_result(
            _result("written"), problem_id=None, model_name="m", input_snapshot=snapshot
        )
        append_generation_log_jsonl(path, log)
        # 파일 내용 변조 재현 — 스냅샷 kind만 바꾼다(해시는 그대로 → 불일치).
        tampered = path.read_text(encoding="utf-8").replace(
            "l3.pregenerate.prewarm", "l3.pregenerate.TAMPER"
        )
        path.write_text(tampered, encoding="utf-8")
        loaded, errors = load_generation_logs_jsonl(path)
        assert loaded == []
        assert len(errors) == 1 and "ValidationError" in errors[0]

    def test_missing_file_raises_not_empty(self, tmp_path: Path) -> None:
        """파일 부재는 FileNotFoundError 전파 — '없음'과 '0건'은 다른 실패(미측정≠0)."""
        with pytest.raises(FileNotFoundError):
            load_generation_logs_jsonl(tmp_path / "없는파일.jsonl")
