"""genlog 관측 축 — '설정이 뭐라고 했나'가 아니라 '누가 실제로 답했나' (EOS-112).

**왜 이 파일이 필요한가**: `GenerationLog.model_name`은 *설정이 지목한* 모델이다. ARCH-57이
클라우드 슬롯을 셀렉터로 바꾸고 ARCH-58이 그 선언값을 셀렉터와 정합하게 고쳤지만 둘 다
**선언 축**이라, provider 측 대체·폴백·프록시 라우팅은 기록에 흔적을 남기지 않는다. 이
파일은 응답에서 읽은 값(`served_model`)과 그 호출의 재시도(`retries`)가
①provider에서 포착되고 ②세 좌석(스키마·ORM·마이그레이션)에 영속되며 ③저작 경로가 실제로
나르고 ④요약이 선언값과 대조하는지를 판정한다.

**이 파일이 지키는 급소 셋**:
  - **미관측 ≠ 일치** — 응답에 모델 식별자가 없으면 None이지 설정값이 아니다. 설정값으로
    접는 순간 이 축이 `model_name`의 복사본이 되어 어긋남은 영영 0건이 된다.
  - **미계측 ≠ 0** — Anthropic SDK·Ollama는 우리 전송기를 타지 않아 재시도 카운터가 없다.
    0으로 접으면 그 경로가 '재시도 0회 실측'처럼 보인다.
  - **호출별 ≠ 누적** — 재시도 카운터는 ContextVar라 회차 내내 누적된다. 차분을 잡지
    않으면 뒤 호출일수록 남의 재시도를 물려받는다.
"""

from __future__ import annotations

import ast
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from whymath_backend.config import Settings
from whymath_backend.db.models.provenance import GenerationLog as OrmGenerationLog
from whymath_backend.db.schema_version import EXPECTED_ALEMBIC_HEAD, KNOWN_REVISIONS
from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates
from whymath_backend.l3.models import CostTier, RoutingDecision
from whymath_backend.l3.providers import _openai_compat
from whymath_backend.l3.providers._openai_compat import extract_usage
from whymath_backend.l3.providers._response_fields import read_response_model_id
from whymath_backend.l3.providers.anthropic import _extract_usage as anthropic_extract_usage
from whymath_backend.l3.providers.ollama import _extract_usage as ollama_extract_usage
from whymath_backend.l3.providers.openrouter import OpenRouterProvider
from whymath_backend.schema.provenance import GenerationLog

# 저장소 루트 — 상대 경로로 열면 pytest 작업 디렉터리에 따라 "파일 없음"이 되고, 그것이
# *배선 부재*처럼 보인다(실패 원인이 원인에서 멀어진다). __file__ 기준으로 고정한다.
# tests/backend/l3/<이 파일> → parents[0]=l3 · [1]=backend · [2]=tests · [3]=저장소 루트
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATIONS = _REPO_ROOT / "src/backend/alembic/versions"
_SRC = _REPO_ROOT / "src/backend/whymath_backend"


# ══════════════════════════════════════════════════════════════════════════
# ① 관측 모델 포착 — provider 3종
# ══════════════════════════════════════════════════════════════════════════
class TestOpenAiCompatObservesTheModel:
    """OpenAI 호환 응답의 payload 최상위 `model`을 읽는다."""

    def test_model_key_lands_in_served_model(self) -> None:
        usage = extract_usage({"model": "deepseek/deepseek-v4.1-flash", "usage": {}}, 10.0)
        assert usage.served_model == "deepseek/deepseek-v4.1-flash"

    def test_missing_model_key_is_none_not_a_guess(self) -> None:
        """응답이 모델을 안 밝히면 None이다 — **설정값으로 접지 않는다**.

        접으면 `served_model`이 `model_name`의 복사본이 되어 대조 축이 통째로 죽는다.
        """
        assert extract_usage({"usage": {}}, 10.0).served_model is None

    @pytest.mark.parametrize("raw", ["", "   ", 123, None, {"nested": "x"}, ["m"]])
    def test_non_string_or_blank_is_none(self, raw: Any) -> None:
        """빈 문자열을 그대로 실으면 '이름이 빈 모델이 답했다'는 거짓 관측이 된다."""
        assert extract_usage({"model": raw, "usage": {}}, 10.0).served_model is None

    def test_attribute_style_payload_also_read(self) -> None:
        """SDK 객체(Mapping이 아님)도 같은 자리를 읽는다."""

        class _Resp:
            model = "gmicloud/qwen"
            usage = {"prompt_tokens": 3, "completion_tokens": 1}

        assert extract_usage(_Resp(), 1.0).served_model == "gmicloud/qwen"

    def test_token_axes_survive_the_addition(self) -> None:
        """대조군 — 신설 축이 기존 포착을 깨뜨리지 않았다."""
        usage = extract_usage(
            {"model": "m", "usage": {"prompt_tokens": 11, "completion_tokens": 7}}, 5.0
        )
        assert (usage.input_tokens, usage.output_tokens, usage.latency_ms) == (11, 7, 5.0)


class TestAnthropicAndOllamaObserveToo:
    """세 provider가 같은 축을 채운다 — 한 곳만 배선하면 나머지가 영영 None이다."""

    def test_anthropic_reads_message_model(self) -> None:
        class _Msg:
            model = "claude-sonnet-4-6-20260101"
            usage = {"input_tokens": 5, "output_tokens": 2}

        assert anthropic_extract_usage(_Msg(), 1.0).served_model == "claude-sonnet-4-6-20260101"

    def test_anthropic_dict_form_also_read(self) -> None:
        message = {"model": "claude-opus-4-7", "usage": {"input_tokens": 1, "output_tokens": 1}}
        assert anthropic_extract_usage(message, 1.0).served_model == "claude-opus-4-7"

    def test_anthropic_without_model_is_none(self) -> None:
        assert anthropic_extract_usage({"usage": {}}, 1.0).served_model is None

    def test_ollama_reads_response_model(self) -> None:
        """로컬도 필요하다 — 데몬이 요청 태그를 해소해 *다른 태그*를 쓸 수 있다."""
        response = {"model": "qwen2-math:7b", "prompt_eval_count": 9, "eval_count": 4}
        assert ollama_extract_usage(response, 1.0).served_model == "qwen2-math:7b"

    def test_ollama_without_model_is_none(self) -> None:
        assert ollama_extract_usage({"eval_count": 1}, 1.0).served_model is None

    @pytest.mark.parametrize(
        "extractor",
        [anthropic_extract_usage, ollama_extract_usage],
        ids=["anthropic", "ollama"],
    )
    def test_retries_stay_none_where_uninstrumented(self, extractor: Any) -> None:
        """이 둘은 우리 전송기를 타지 않는다 — 0이면 '재시도 없었다'는 거짓 실측이 된다."""
        assert extractor({"model": "m"}, 1.0).retries is None

    def test_one_reader_serves_all_three(self) -> None:
        """구현이 하나인지 확인한다 — 세 벌이면 갈라진다(ARCH-58이 그 형태였다).

        세 provider 모듈이 전부 같은 좌석을 import하고, 자기만의 `model` 파싱을 들고
        있지 않아야 한다.
        """
        for name in ("anthropic.py", "ollama.py", "_openai_compat.py"):
            source = (_SRC / "l3/providers" / name).read_text(encoding="utf-8")
            assert "read_response_model_id" in source, f"{name}이 공용 리더를 쓰지 않는다"

    def test_shared_reader_rejects_non_strings(self) -> None:
        """공용 리더 자체의 계약 — 위 provider별 테스트의 대조군."""
        assert read_response_model_id({"model": "x"}) == "x"
        assert read_response_model_id({"model": 7}) is None
        assert read_response_model_id({}) is None
        assert read_response_model_id(object()) is None


# ══════════════════════════════════════════════════════════════════════════
# ② 재시도 포착 — 호출별(누적 아님)
# ══════════════════════════════════════════════════════════════════════════
class _BumpingTransport:
    """전송 중 재시도가 N회 일어난 상황을 만드는 시임.

    전송기 내부(백오프·상태코드 분기)를 재현하지 않는다 — 이 테스트가 판정하는 것은
    provider의 **차분 계산**이지 재시도 로직 자체가 아니다(그쪽은
    `test_openai_compat_transport.py`가 소유). 그래서 카운터만 올린다.
    """

    def __init__(self, bumps: int, model: str = "deepinfra/qwen") -> None:
        self._bumps = bumps
        self._model = model
        self.calls = 0

    async def post_chat(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout_s: float,
    ) -> Any:
        self.calls += 1
        for _ in range(self._bumps):
            _openai_compat._RETRY_COUNT.set(_openai_compat._RETRY_COUNT.get() + 1)
        return {
            "model": self._model,
            "choices": [{"message": {"role": "assistant", "content": "답"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1},
        }


def _openrouter_settings() -> Settings:
    return Settings(
        openrouter_api_key=SecretStr("sk-or-test"),
        openrouter_allowed_providers=("deepinfra", "gmicloud"),
    )


def _cloud_decision() -> RoutingDecision:
    return RoutingDecision(
        cost_tier=CostTier.CLOUD_MID,
        local_family=None,
        local_model=None,
        mode="sync",
        reason="cloud escalation",
        est_latency_ms=2000,
        est_cost_krw=1.0,
    )


class TestRetriesAreCountedPerCall:
    """ContextVar는 회차 내내 누적된다 — 차분을 안 잡으면 남의 재시도를 물려받는다."""

    async def test_single_call_reports_its_own_retries(self) -> None:
        _openai_compat.reset_retry_count()
        transport = _BumpingTransport(bumps=2)
        provider = OpenRouterProvider(transport=transport, settings=_openrouter_settings())
        result = await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert result.usage is not None
        assert result.usage.retries == 2

    async def test_second_call_does_not_inherit_the_first(self) -> None:
        """이 테스트가 이 축의 존재 이유다 — 누적을 그대로 읽으면 여기서 3이 나온다."""
        _openai_compat.reset_retry_count()
        provider_a = OpenRouterProvider(
            transport=_BumpingTransport(bumps=2), settings=_openrouter_settings()
        )
        await provider_a.generate("프롬프트", "시스템", _cloud_decision())

        provider_b = OpenRouterProvider(
            transport=_BumpingTransport(bumps=1), settings=_openrouter_settings()
        )
        second = await provider_b.generate("프롬프트", "시스템", _cloud_decision())
        assert second.usage is not None
        assert second.usage.retries == 1, (
            "두 번째 호출이 첫 호출의 재시도를 물려받았다 — 카운터 차분이 아니라 "
            "누적값을 읽고 있다."
        )

    async def test_zero_retries_is_measured_zero_not_none(self) -> None:
        """대조군 — 계측된 0과 미계측(None)은 다른 사실이다."""
        _openai_compat.reset_retry_count()
        provider = OpenRouterProvider(
            transport=_BumpingTransport(bumps=0), settings=_openrouter_settings()
        )
        result = await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert result.usage is not None
        assert result.usage.retries == 0

    async def test_provider_does_not_reset_shared_counter(self) -> None:
        """provider가 `reset_retry_count()`를 부르면 회차 단위로 세는 소비자
        (`harness/provider_accuracy_battle`)의 회계를 말없이 뒤엎는다."""
        _openai_compat.reset_retry_count()
        _openai_compat._RETRY_COUNT.set(5)  # 바깥에서 이미 5회 세고 있는 상태
        provider = OpenRouterProvider(
            transport=_BumpingTransport(bumps=1), settings=_openrouter_settings()
        )
        await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert (
            _openai_compat.retries_in_current_call() == 6
        ), "provider가 공유 카운터를 지웠다 — 바깥 회계가 무너진다."

    async def test_counter_moving_backwards_reports_unmeasured_not_zero(self) -> None:
        """차분이 음수면 **모른다**이지 '재시도 없었다'가 아니다.

        음수를 그대로 실으면 스키마의 `ge=0`에 걸려 **그 행 전체가 버려지고**(never-break가
        예외를 삼킨다), 0으로 접으면 계측 실패가 실측 0으로 위장된다. 둘 다 나쁘다.
        """

        class _ResettingTransport(_BumpingTransport):
            async def post_chat(self, url: str, **kwargs: Any) -> Any:
                response = await super().post_chat(url, **kwargs)
                _openai_compat.reset_retry_count()  # 호출 도중 누군가 되돌린 상황
                return response

        _openai_compat.reset_retry_count()
        _openai_compat._RETRY_COUNT.set(4)
        provider = OpenRouterProvider(
            transport=_ResettingTransport(bumps=0), settings=_openrouter_settings()
        )
        result = await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert result.usage is not None
        assert result.usage.retries is None
        # 그 행이 스키마를 통과하는지까지 본다 — 통과하지 못하면 로그가 통째로 사라진다.
        assert GenerationLog(retries=result.usage.retries).retries is None

    def test_retries_since_is_the_single_delta_seat(self) -> None:
        """두 provider가 각자 차분을 계산하면 갈라진다(ARCH-58이 그 형태였다)."""
        for name in ("openrouter.py", "deepseek.py"):
            source = (_SRC / "l3/providers" / name).read_text(encoding="utf-8")
            assert "retries_since(retries_before)" in source, f"{name}이 공용 차분 좌석을 안 쓴다"

    async def test_served_model_comes_from_the_response_not_the_pin(self) -> None:
        """provider가 *보낸* 모델이 아니라 *응답이 말한* 모델이 실린다."""
        _openai_compat.reset_retry_count()
        transport = _BumpingTransport(bumps=0, model="deepinfra/actually-served")
        provider = OpenRouterProvider(transport=transport, settings=_openrouter_settings())
        result = await provider.generate("프롬프트", "시스템", _cloud_decision())
        assert result.usage is not None
        assert result.usage.served_model == "deepinfra/actually-served"
        assert transport.calls == 1


# ══════════════════════════════════════════════════════════════════════════
# ③ 영속 좌석 — 스키마·ORM·마이그레이션이 함께 있는가
# ══════════════════════════════════════════════════════════════════════════
_NEW_FIELDS = ("served_model", "retries")


def _orm_columns() -> frozenset[str]:
    return frozenset(col.key for col in sa.inspect(OrmGenerationLog).mapper.column_attrs)


class TestSeatExistsInAllThreePlaces:
    """스키마에만 있고 DB에 없으면 `from_schema`의 컬럼 필터가 값을 **조용히 버린다**."""

    @pytest.mark.parametrize("field", _NEW_FIELDS)
    def test_schema_has_the_field(self, field: str) -> None:
        assert field in GenerationLog.model_fields

    @pytest.mark.parametrize("field", _NEW_FIELDS)
    def test_orm_has_the_column(self, field: str) -> None:
        assert field in _orm_columns(), (
            f"ORM에 {field} 컬럼이 없다 — from_schema/to_schema가 매핑 키로 필터링하므로 "
            "스키마 필드만 더하면 DB 왕복에서 값이 조용히 사라진다."
        )

    def test_orm_roundtrip_preserves_both(self) -> None:
        """컬럼 존재만으로는 왕복을 보장하지 못한다 — seam을 실제로 통과시킨다."""
        original = GenerationLog(
            model_name="claude-sonnet-4-6",
            served_model="claude-sonnet-4-6-20260101",
            retries=3,
        )
        restored = OrmGenerationLog.from_schema(original).to_schema()
        assert restored.served_model == "claude-sonnet-4-6-20260101"
        assert restored.retries == 3

    def test_roundtrip_keeps_none_as_none(self) -> None:
        """미관측·미계측이 왕복 뒤 0이나 ''으로 바뀌지 않는다."""
        restored = OrmGenerationLog.from_schema(GenerationLog(model_name="m")).to_schema()
        assert restored.served_model is None
        assert restored.retries is None

    def test_every_schema_field_is_a_mapped_column(self) -> None:
        """전수 거버넌스 — 이 축뿐 아니라 **앞으로 더해질 모든 필드**를 막는다.

        위 두 단언이 `served_model`·`retries`만 본다면 이것은 *다음번*을 본다. 필드를
        늘리며 컬럼을 빠뜨리는 형태가 이 모델에서 반복됐기 때문이다(EOS-97 run_id 주석·
        EOS-99 캐시 2종 주석이 같은 사고를 각각 적고 있다).
        """
        missing = sorted(set(GenerationLog.model_fields) - _orm_columns())
        assert not missing, (
            f"스키마에만 있고 ORM 컬럼이 없는 필드: {missing} — from_schema가 이 값들을 "
            "조용히 버린다(기록했다고 믿는데 DB에 없는 상태). 컬럼과 마이그레이션을 함께 "
            "추가하라."
        )

    def test_migration_declares_both_columns(self) -> None:
        """마이그레이션 없이 컬럼만 선언하면 실 DB에는 없다(배포 시 터진다)."""
        found = list(_MIGRATIONS.glob("*_generation_log_served_model.py"))
        assert len(found) == 1, f"마이그레이션 파일이 정확히 1개여야 한다(발견 {len(found)})"
        source = found[0].read_text(encoding="utf-8")
        assert 'revision: str = "d2a9e4b71c35"' in source
        assert 'down_revision: str | None = "c1f5a8b2d740"' in source
        for field in _NEW_FIELDS:
            assert f'sa.Column("{field}"' in source, f"upgrade가 {field}를 추가하지 않는다"
            assert (
                f'op.drop_column("generation_log", "{field}")' in source
            ), f"downgrade가 {field}를 되돌리지 않는다(대칭 깨짐)"

    def test_revision_is_registered_as_head(self) -> None:
        """런타임은 마이그레이션 파일을 읽지 않는다 — 상수 대장이 정본이다."""
        # [2026-09-21 ASM-06] head가 5b3e9c27a1f6(problem_attempt.selected_choice_index)로
        # 전진해 종전 리터럴 핀이 깨졌다. 이 좌석이 정말 재려는 것은 "**EOS-112 리비전이
        # 대장에 등재됐는가**"이므로 그것을 직접 단언하고, head 리터럴은 현행으로 갱신해
        # 기존 계약을 그대로 유지한다(손 유지 사본을 줄일지의 판정은 MISC-31 소관 — 여기서
        # 앞질러 바꾸지 않는다).
        #
        # `KNOWN_REVISIONS[-1] == EXPECTED_ALEMBIC_HEAD` 형태의 단언은 두지 않는다 —
        # `EXPECTED_ALEMBIC_HEAD`가 `KNOWN_REVISIONS[-1]`로 *정의*돼 있어 정상·고장 양쪽에서
        # 같은 값을 내는 동어반복이고, 그런 검사는 보호가 아니라 위장이다.
        assert "d2a9e4b71c35" in KNOWN_REVISIONS, "EOS-112 리비전이 대장에서 사라졌다"
        assert EXPECTED_ALEMBIC_HEAD == "5b3e9c27a1f6"
        assert len(set(KNOWN_REVISIONS)) == len(KNOWN_REVISIONS), "리비전 중복 등재"

    def test_prod_schema_probe_covers_the_revision(self) -> None:
        """`infra-contracts` 잡의 프로브가 꼬리 전수 커버를 요구한다 — 빠뜨리면 그 잡만 red다.

        여기서 함께 보는 이유: 그 잡을 로컬에서 안 돌리면 *다른 잡이 green이라* 빠짐이
        보이지 않는다(CLAUDE.md v0.2.27 — 잡을 통째로 빠뜨리는 축).
        """
        probe = (_REPO_ROOT / "scripts/ops/probe_prod_schema_revision.sql").read_text(
            encoding="utf-8"
        )
        assert "d2a9e4b71c35" in probe, "프로브가 신규 리비전을 덮지 않는다"
        assert re.search(r"'d2a9e4b71c35',\s*'generation_log',\s*'served_model'", probe), (
            "프로브의 판별자가 (generation_log, served_model)이 아니다 — 판별자는 그 "
            "리비전이 실제로 만드는 대상이어야 한다."
        )


class TestNullMeansUnobserved:
    """값 의미 계약 — 기본값이 0이나 ''이 되면 미관측이 실측으로 둔갑한다."""

    def test_defaults_are_none(self) -> None:
        log = GenerationLog()
        assert log.served_model is None
        assert log.retries is None

    def test_retries_rejects_negative(self) -> None:
        with pytest.raises(ValueError):
            GenerationLog(retries=-1)

    def test_retries_zero_is_allowed(self) -> None:
        """0은 '계측했고 재시도 없었다'는 유효한 실측이다."""
        assert GenerationLog(retries=0).retries == 0

    def test_served_model_width_matches_orm(self) -> None:
        """스키마 폭과 DB 폭이 갈라지면 한쪽만 받아 주고 다른 쪽이 터진다."""
        column = sa.inspect(OrmGenerationLog).columns["served_model"]
        assert column.type.length == 128
        with pytest.raises(ValueError):
            GenerationLog(served_model="x" * 129)


# ══════════════════════════════════════════════════════════════════════════
# ④ 선언 vs 관측 대조
# ══════════════════════════════════════════════════════════════════════════
_PINS = ("claude-sonnet-4-6", "claude-opus-4-7")


def _rates(tally: SeatTally) -> dict[str, Any]:
    return seat_operating_rates(tally, selected_seat="anthropic", seat_model_pins=_PINS)


class TestDeclaredVsServed:
    """둘 다 실린 행에서만 비교한다 — 한쪽만 있는 행을 계상하면 미관측이 판정이 된다."""

    def test_difference_is_counted_and_the_pair_is_shown(self) -> None:
        tally = SeatTally().observe(
            model_name="claude-sonnet-4-6",
            success=True,
            cost_usd=None,
            served_model="claude-sonnet-4-6-20260101",
        )
        block = _rates(tally)["observation"]["declared_vs_served"]
        assert block["comparable"] == 1
        assert block["differs"] == 1
        assert block["matched"] == 0
        assert block["differing_pairs"] == [
            {
                "declared": "claude-sonnet-4-6",
                "served": "claude-sonnet-4-6-20260101",
                "count": 1,
            }
        ]

    def test_identical_values_are_matched_not_differing(self) -> None:
        """대조군 — 없으면 '전부 어긋남으로 계상'하는 과잉 구현도 위 테스트를 통과한다."""
        tally = SeatTally().observe(
            model_name="claude-opus-4-7",
            success=True,
            cost_usd=None,
            served_model="claude-opus-4-7",
        )
        block = _rates(tally)["observation"]["declared_vs_served"]
        assert (block["comparable"], block["matched"], block["differs"]) == (1, 1, 0)
        assert block["differing_pairs"] == []

    def test_row_without_served_model_is_not_comparable(self) -> None:
        """관측이 없으면 '일치'도 '어긋남'도 아니다 — 분모에 들어가지 않는다."""
        tally = SeatTally().observe(
            model_name="claude-sonnet-4-6", success=True, cost_usd=None, served_model=None
        )
        obs = _rates(tally)["observation"]
        assert obs["calls_with_served_model"] == 0
        assert obs["declared_vs_served"]["comparable"] == 0
        assert obs["declared_vs_served"]["differs"] == 0

    def test_row_without_declared_name_is_observed_but_not_comparable(self) -> None:
        tally = SeatTally().observe(
            model_name=None, success=True, cost_usd=None, served_model="mystery/model"
        )
        obs = _rates(tally)["observation"]
        assert obs["calls_with_served_model"] == 1
        assert obs["observed_models"] == {"mystery/model": 1}
        assert obs["declared_vs_served"]["comparable"] == 0

    def test_repeated_difference_accumulates_on_one_pair(self) -> None:
        tally = SeatTally()
        for _ in range(3):
            tally = tally.observe(model_name="a", success=True, cost_usd=None, served_model="b")
        block = _rates(tally)["observation"]["declared_vs_served"]
        assert block["differs"] == 3
        assert block["differing_pairs"] == [{"declared": "a", "served": "b", "count": 3}]
        assert block["differing_pairs_truncated"] is False

    def test_many_distinct_pairs_are_truncated_with_disclosure(self) -> None:
        """잘랐으면 잘랐다고 말한다 — 조용히 자르면 '어긋남은 이게 전부'로 읽힌다."""
        tally = SeatTally()
        for index in range(25):
            tally = tally.observe(
                model_name=f"declared-{index:02d}",
                success=True,
                cost_usd=None,
                served_model=f"served-{index:02d}",
            )
        block = _rates(tally)["observation"]["declared_vs_served"]
        assert block["differs"] == 25
        assert len(block["differing_pairs"]) == 20
        assert block["differing_pairs_truncated"] is True

    def test_note_says_difference_is_not_a_verdict(self) -> None:
        """상시 발화하는 경보로 만들면 사람이 꺼 버린다 — 문구가 그것을 막는다."""
        note = _rates(SeatTally())["observation"]["declared_vs_served"]["note"]
        assert "별칭" in note


class TestRetryAggregation:
    """미계측(None)은 분모 밖이다 — 넣으면 계측 없는 경로가 '재시도 0%'로 보인다."""

    def test_none_rows_stay_out_of_the_denominator(self) -> None:
        tally = SeatTally()
        for _ in range(4):
            tally = tally.observe(model_name="m", success=True, cost_usd=None, retries=None)
        block = _rates(tally)["observation"]["retries"]
        assert block["calls_with_retries_measured"] == 0
        assert (
            block["retries_total"] is None
        ), "계측 0건인데 합을 0으로 내면 '재시도 없었다'로 읽힌다"
        assert block["calls_with_any_retry"] is None

    def test_measured_zero_is_reported_as_zero(self) -> None:
        """대조군 — 계측된 0은 실측이므로 None이 아니다."""
        tally = SeatTally().observe(model_name="m", success=True, cost_usd=None, retries=0)
        block = _rates(tally)["observation"]["retries"]
        assert block["calls_with_retries_measured"] == 1
        assert block["retries_total"] == 0
        assert block["calls_with_any_retry"] == 0

    def test_totals_and_affected_rows_are_separate(self) -> None:
        """합 5가 한 행 탓인지 다섯 행 탓인지 구분된다."""
        tally = SeatTally()
        tally = tally.observe(model_name="m", success=True, cost_usd=None, retries=5)
        tally = tally.observe(model_name="m", success=True, cost_usd=None, retries=0)
        block = _rates(tally)["observation"]["retries"]
        assert (block["retries_total"], block["calls_with_any_retry"]) == (5, 1)
        assert block["calls_with_retries_measured"] == 2


class TestObservationDoesNotDisturbTheDeclaredAxis:
    """EOS-111이 세운 선언 축이 그대로다 — 회귀 대조군."""

    def test_state_still_reflects_declared_pins_only(self) -> None:
        """관측값이 핀 밖이어도 `state`는 선언값으로 판정한다(두 축을 섞지 않는다)."""
        tally = SeatTally().observe(
            model_name="claude-sonnet-4-6",
            success=True,
            cost_usd=None,
            served_model="somewhere/else",
        )
        assert _rates(tally)["state"] == "all_on_selected_seat"

    def test_report_still_declares_its_own_limit(self) -> None:
        note = _rates(SeatTally())["declared_not_observed"]
        assert "선언값" in note
        assert "observation" in note


# ══════════════════════════════════════════════════════════════════════════
# 집행 지점 — 만들기만 하고 안 부르면 값은 영영 None이다
# ══════════════════════════════════════════════════════════════════════════
def _generation_log_kwargs(source: str, func_name: str) -> set[str]:
    """지정 함수 안에서 `GenerationLog(...)`에 넘기는 키워드 이름들 (AST — 문자열 검색 아님)."""
    tree = ast.parse(source)
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == func_name
        ),
        None,
    )
    assert target is not None, f"{func_name}이 사라졌다 — 이 가드가 볼 자리가 없어졌다"
    names: set[str] = set()
    for node in ast.walk(target):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "GenerationLog"
        ):
            names.update(kw.arg for kw in node.keywords if kw.arg)
    return names


class TestProducersCarryTheAxes:
    """두 생산 지점이 usage의 두 축을 GenerationLog로 나른다."""

    def test_authoring_generator_passes_both(self) -> None:
        source = (_SRC / "l3/equivalent/llm_generator.py").read_text(encoding="utf-8")
        kwargs = _generation_log_kwargs(source, "_emit_generation_log")
        assert {"served_model", "retries"} <= kwargs, (
            f"저작 경로가 관측 축을 안 싣는다(실린 키워드: {sorted(kwargs)}) — 필드는 "
            "있는데 값이 영영 None이 된다."
        )
        assert "model_name" in kwargs, "대조군(선언 축)이 사라졌다 — 이 가드의 전제가 깨졌다"

    def test_pregenerate_bridge_passes_both(self) -> None:
        source = (_SRC / "l3/pregenerate/provenance_bridge.py").read_text(encoding="utf-8")
        kwargs = _generation_log_kwargs(source, "generation_log_from_result")
        assert {"served_model", "retries"} <= kwargs
        assert "model_name" in kwargs

    def test_batch_sink_feeds_the_observation_axes(self) -> None:
        """싱크가 좌석 원장에 두 축을 실제로 먹인다 — AST로 구성된 호출을 본다."""
        source = (_SRC / "harness/problem_corpus_accumulate.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        sink = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "_genlog_sink"
            ),
            None,
        )
        assert sink is not None, "_genlog_sink가 사라졌다"
        seat_kwargs: set[str] = set()
        for node in ast.walk(sink):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "observe"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "seat_tally"
            ):
                seat_kwargs.update(kw.arg for kw in node.keywords if kw.arg)
        assert {"served_model", "retries"} <= seat_kwargs, (
            f"싱크가 관측 축을 안 먹인다(넘긴 키워드: {sorted(seat_kwargs)}) — 집계기는 "
            "있는데 그 축의 분모가 영영 0이다."
        )
        assert "model_name" in seat_kwargs, "대조군(선언 축 배선)이 사라졌다"


class TestEndToEndThroughTheSeam:
    """추출 → 스키마 → ORM → 집계까지 한 번에 통과시킨다(각 단계 단언의 대조군)."""

    def test_observed_difference_survives_the_whole_chain(self) -> None:
        usage = extract_usage(
            {"model": "deepinfra/qwen-actually", "usage": {"prompt_tokens": 2}},
            1.0,
            retries=1,
        )
        log = GenerationLog(
            log_id=uuid.uuid4(),
            model_name="deepseek/deepseek-v4.1-flash",
            served_model=usage.served_model,
            retries=usage.retries,
        )
        restored = OrmGenerationLog.from_schema(log).to_schema()
        tally = SeatTally().observe(
            model_name=restored.model_name,
            success=True,
            cost_usd=None,
            served_model=restored.served_model,
            retries=restored.retries,
        )
        observation = _rates(tally)["observation"]
        assert observation["declared_vs_served"]["differs"] == 1
        assert observation["retries"]["retries_total"] == 1
