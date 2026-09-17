"""프로바이더 3축 강등전의 *계약* 회귀 — 라이브 없이 (ARCH-55 ①②③).

라이브에서 도는지는 여기서 잴 수 없다(키·egress 부재). 여기서 재는 것은 **라이브에 갔을 때
옳은 것을 재는가**의 전제들이다:

  ① **시험지·채점 기준 공유** — OPS-48 강등전과 같은 프롬프트·파서를 쓴다. 갈라지면 두
     강등전의 수치를 나란히 놓을 수 없다(그래서 복사가 아니라 import이고, 그 사실을 동결한다).
  ② **라우터 경유** — 티어를 손으로 박지 않고 입력 신호로 `CLOUD_MID`를 받는다.
  ③ **집계에서 빼야 할 것을 빼는가** — 호출 실패·공급사 불일치 회차가 정답으로도 오답으로도
     세어지지 않고 `unresolved`로 간다. 이것이 "정확도가 낮다"와 "도구가 고장났다"를 가른다.
  ④ **모르면 지어내지 않는가** — 측정값이 없으면 None이지 0이 아니다.
"""

from __future__ import annotations

import pytest

from whymath_backend import config
from whymath_backend.harness import provider_accuracy_battle as battle
from whymath_backend.harness.quality_tier_moe_accuracy_battle import (
    _SYSTEM_PROMPT,
    _format_item,
    _parse_response,
)
from whymath_backend.l3.equivalent.defect_seeder import DEFECT_CLASSES
from whymath_backend.l3.models import CostTier
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType


def _outcome(**overrides: object) -> battle.RoundOutcome:
    base: dict[str, object] = {
        "arm": "deepseek",
        "slug": "s1",
        "ground_truth": None,
        "detected": False,
        "parsed": True,
        "pricing_window": "peak",
    }
    base.update(overrides)
    return battle.RoundOutcome(**base)  # type: ignore[arg-type]


class TestSharedRubric:
    """OPS-48과 같은 시험지·채점 기준을 쓰는가 — 비교 가능성의 전제."""

    def test_reuses_the_same_system_prompt_and_parser(self) -> None:
        """복사본이 아니라 **같은 객체**여야 한다 — 복사하면 조용히 갈라진다."""
        assert battle._SYSTEM_PROMPT is _SYSTEM_PROMPT
        assert battle._format_item is _format_item
        assert battle._parse_response is _parse_response

    def test_the_shared_prompt_still_demands_json(self) -> None:
        """공유 프롬프트가 JSON 판정을 요구하는가 — 파서의 전제다."""
        assert "JSON" in _SYSTEM_PROMPT
        assert "has_defect" in _SYSTEM_PROMPT


class TestRoutesThroughTheRouter:
    """티어를 손으로 박지 않는다 — 라우터가 스스로 클라우드를 내야 한다."""

    def test_battle_request_yields_a_cloud_decision(self) -> None:
        decision = Router().route(battle._battle_request(LicenseType.WHYMATH_GENERATED))
        assert decision.cost_tier == CostTier.CLOUD_MID
        assert decision.data_export_blocked is False

    def test_declared_grade_is_carried_into_the_decision(self) -> None:
        """등급이 결정에 승계돼야 관할 게이트가 판정할 재료가 생긴다."""
        decision = Router().route(battle._battle_request(LicenseType.WHYMATH_GENERATED))
        assert tuple(decision.data_licenses) == (LicenseType.WHYMATH_GENERATED,)


class TestUnusableRoundsAreExcluded:
    """③ — 집계에서 빼야 할 회차가 실제로 빠지는가."""

    def test_fixture_defect_class_is_a_real_one(self) -> None:
        """픽스처가 쓰는 결함 유형이 실물 목록에 있는가 — 없으면 아래 단언들이 공허하다."""
        assert "answer_error" in DEFECT_CLASSES

    def test_call_failure_counts_as_unresolved_not_a_miss(self) -> None:
        """호출 실패를 '못 잡았다'로 세면 도구 고장이 정확도 저하로 위장된다."""
        outcomes = [
            _outcome(ground_truth="answer_error", call_error="TimeoutError: x"),
        ]
        metrics = battle.summarize(outcomes)
        assert metrics.unresolved == 1
        assert metrics.true_positives == 0
        assert metrics.false_negatives == 0  # ← 오답으로 세지 않는다
        assert metrics.defective_total == 0

    def test_provider_mismatch_counts_as_unresolved(self) -> None:
        """다른 공급사가 응답한 회차는 양자화가 다를 수 있어 비교 대상이 아니다."""
        outcomes = [
            _outcome(
                ground_truth="answer_error",
                detected=True,
                served_provider="novitaai",
                provider_mismatch=True,
            ),
        ]
        metrics = battle.summarize(outcomes)
        assert metrics.unresolved == 1
        assert metrics.true_positives == 0  # 맞혔어도 세지 않는다

    def test_clean_rounds_are_counted_normally(self) -> None:
        """green 축 — 정상 회차는 세어져야 한다(전부 제외하면 게이트가 아니다)."""
        outcomes = [
            _outcome(ground_truth="answer_error", detected=True),
            _outcome(ground_truth=None, detected=False),
            _outcome(ground_truth=None, detected=True),
        ]
        metrics = battle.summarize(outcomes)
        assert (metrics.true_positives, metrics.true_negatives, metrics.false_positives) == (
            1,
            1,
            1,
        )
        assert metrics.unresolved == 0

    def test_usable_property_distinguishes_the_two_exclusion_reasons(self) -> None:
        assert _outcome().usable is True
        assert _outcome(call_error="X: y").usable is False
        assert _outcome(provider_mismatch=True).usable is False


class TestWilsonBounds:
    """점추정 금지 — 경계로 판정한다."""

    def test_bounds_are_conservative_not_point_estimates(self) -> None:
        metrics = battle.DetectionMetrics(
            true_positives=9, false_negatives=1, false_positives=0, true_negatives=10, unresolved=0
        )
        lower = metrics.detection_lower_bound(0.95)
        assert lower is not None
        assert lower < 0.9, "Wilson 하한이 점추정(0.9) 이상이면 경계가 아니다"
        upper = metrics.false_alarm_upper_bound(0.95)
        assert upper is not None
        assert upper > 0.0, "오경보 0건이어도 상한은 0보다 커야 한다(작은 표본의 정직)"

    def test_empty_strata_return_none_not_zero(self) -> None:
        """모수가 0이면 None — 0.0으로 접으면 '완벽했다'로 읽힌다."""
        empty = battle.DetectionMetrics(0, 0, 0, 0, 0)
        assert empty.detection_lower_bound() is None
        assert empty.false_alarm_upper_bound() is None


class TestMeasurementHonesty:
    """④ — 측정값이 없으면 지어내지 않는다."""

    def test_latency_summary_is_none_when_nothing_measured(self) -> None:
        summary = battle.latency_summary([_outcome(latency_ms=None)])
        assert summary["n"] == 0
        assert summary["p50_ms"] is None

    def test_latency_summary_ignores_unusable_rounds(self) -> None:
        """실패 회차의 지연은 지연이 아니다 — 섞으면 빠른 실패가 빠른 응답으로 보인다."""
        summary = battle.latency_summary(
            [_outcome(latency_ms=5.0, call_error="X: y"), _outcome(latency_ms=100.0)]
        )
        assert summary["n"] == 1
        assert summary["p50_ms"] == 100.0

    def test_token_summary_reports_measured_count_separately(self) -> None:
        summary = battle.token_summary([_outcome(input_tokens=10, output_tokens=20), _outcome()])
        assert summary["n_measured"] == 1
        assert summary["input_total"] == 10

    def test_report_states_that_cost_is_not_converted(self) -> None:
        """비용을 환산하지 않는다는 사실이 출력에 남아야 한다(침묵하면 '비용 없음'으로 읽힌다)."""
        assert "단가" in battle.main.__doc__ if battle.main.__doc__ else True
        assert "비용을 계산하지 않는 이유" in (battle.__doc__ or "")


class TestArmConstruction:
    """arm마다 다른 프로바이더가 클라우드 슬롯에 앉는가."""

    @pytest.mark.parametrize("arm", battle.ARMS)
    def test_each_arm_builds(self, arm: str) -> None:
        provider, label = battle.build_arm(arm, battle._ProviderTap())
        assert label
        # 디스패처는 항상 CompositeProvider — 관할 게이트를 경유시키기 위함이다.
        assert type(provider).__name__ == "CompositeProvider"

    def test_unknown_arm_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="알 수 없는 arm"):
            battle.build_arm("gpt5", None)

    @pytest.mark.parametrize(
        ("arm", "expected_jurisdiction"),
        [("anthropic", "us"), ("deepseek", "cn")],
    )
    def test_arm_jurisdiction_is_what_we_think(self, arm: str, expected_jurisdiction: str) -> None:
        """arm이 실제로 그 관할로 나가는가 — 라벨이 아니라 프로바이더 선언을 본다."""
        from whymath_backend.l3.providers.composite import CompositeProvider

        provider, _ = battle.build_arm(arm, None)
        assert isinstance(provider, CompositeProvider)
        cloud = provider._cloud  # noqa: SLF001 — 관할 선언 확인이 이 테스트의 목적
        assert CompositeProvider.cloud_jurisdiction(cloud).value == expected_jurisdiction


def test_cli_rejects_bad_sample_size() -> None:
    """인자 오류(2)와 게이트 미달(1)을 구분한다 — 섞으면 실패 원인이 사라진다."""
    assert battle.main(["--n-defective", "0"]) == 2


class TestArmReadinessPreflight:
    """호출 전 준비 판정 — 키가 없으면 회차를 태우지 않고 멈추는가.

    각 절이 *실제로 밟히는* 픽스처를 둔다(CLAUDE.md "픽스처가 그 절을 실제로 밟는가"):
    anthropic은 키 부재, openrouter는 키는 있는데 **허용목록이 빈** 상태를 따로 만든다 —
    후자가 없으면 `and bool(allowed)` 절이 뮤테이션에서 살아남는다.
    """

    @staticmethod
    def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
        """이 테스트가 보는 Settings를 환경변수로 구성하고 캐시를 비운다."""
        for name in (
            "WHYMATH_ANTHROPIC_API_KEY",
            "WHYMATH_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
            "WHYMATH_OPENROUTER_API_KEY",
            "OPENROUTER_API_KEY",
            "WHYMATH_OPENROUTER_ALLOWED_PROVIDERS",
        ):
            monkeypatch.delenv(name, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        config.get_settings.cache_clear()

    def test_missing_anthropic_key_is_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._settings(monkeypatch)
        ready, detail = battle.arm_readiness("anthropic")
        assert ready is False
        assert "WHYMATH_ANTHROPIC_API_KEY" in detail
        config.get_settings.cache_clear()

    def test_present_deepseek_key_is_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._settings(monkeypatch, DEEPSEEK_API_KEY="sk-test-not-a-real-key")
        ready, _ = battle.arm_readiness("deepseek")
        assert ready is True
        config.get_settings.cache_clear()

    def test_openrouter_key_without_allowlist_is_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """키는 있는데 허용목록이 빈 상태 — 빈 허용목록은 '아무나 허용'이 아니라 '차단'이다."""
        self._settings(
            monkeypatch,
            OPENROUTER_API_KEY="sk-or-test-not-a-real-key",
            WHYMATH_OPENROUTER_ALLOWED_PROVIDERS="[]",
        )
        ready, detail = battle.arm_readiness("openrouter")
        assert ready is False
        assert "허용 공급사" in detail
        config.get_settings.cache_clear()

    def test_openrouter_with_key_and_allowlist_is_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._settings(
            monkeypatch,
            OPENROUTER_API_KEY="sk-or-test-not-a-real-key",
            WHYMATH_OPENROUTER_ALLOWED_PROVIDERS='["deepinfra"]',
        )
        ready, detail = battle.arm_readiness("openrouter")
        assert ready is True
        assert "deepinfra" in detail
        config.get_settings.cache_clear()

    def test_unknown_arm_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._settings(monkeypatch)
        with pytest.raises(ValueError, match="알 수 없는 arm"):
            battle.arm_readiness("gemini")
        config.get_settings.cache_clear()

    def test_check_only_refuses_when_key_absent(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """미비 arm이 있으면 시험지 생성도 호출도 하지 않고 exit 2."""
        self._settings(monkeypatch)
        called: list[str] = []

        def _never_built(**_kwargs: object) -> list[object]:
            called.append("built")
            return []

        monkeypatch.setattr(battle, "build_defect_seeded_set", _never_built)
        code = battle.main(["--arm", "anthropic", "--check-only"])
        assert code == 2
        assert called == []
        assert "미비" in capsys.readouterr().out
        config.get_settings.cache_clear()

    def test_check_only_passes_and_makes_no_call(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """준비된 arm만 있으면 exit 0 — 그러나 평가는 한 회차도 돌지 않는다."""
        self._settings(monkeypatch, DEEPSEEK_API_KEY="sk-test-not-a-real-key")
        evaluated: list[str] = []

        def _never_evaluated(*_a: object, **_k: object) -> list[object]:
            evaluated.append("ran")
            return []

        monkeypatch.setattr(battle, "evaluate_arm", _never_evaluated)
        code = battle.main(["--arm", "deepseek", "--check-only"])
        assert code == 0
        assert evaluated == []
        assert "호출 가능" in capsys.readouterr().out
        config.get_settings.cache_clear()
