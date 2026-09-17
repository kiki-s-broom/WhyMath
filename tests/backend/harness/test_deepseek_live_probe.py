"""DeepSeek 라이브 프로브의 *계약* 회귀 — 라이브 없이 (ARCH-49 ① 도구).

이 프로브의 값어치는 "라이브에서 돈다"는 것인데, 그 축은 여기서 잴 수 없다(키·egress).
여기서 재는 것은 **라이브에 갔을 때 옳은 것을 보내는가**의 전제 셋이다:

  ① 티어를 손으로 박지 않고 *라우터가 그 티어를 내게* 입력을 고른다
     — 박으면 결정 우회 스캐너가 막는 형태가 되고, 라우팅 규칙이 바뀌어도 프로브가 그걸 모른다.
  ② 기본 등급이 합성 프로브(`WHYMATH_GENERATED`)다 — CN 관할이 기본 허용하는 유일한 등급이라
     그래야 opt-in 없이 측정이 성립한다.
  ③ 실패가 *원인을 남기고* 종료 코드로 판정된다(성공 0 / 호출 실패 1 / 인자 오류 2).
"""

from __future__ import annotations

import pytest

from whymath_backend.harness.deepseek_live_probe import _build_request, main
from whymath_backend.l3.models import CostTier
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType


@pytest.mark.parametrize(
    ("tier", "expected"),
    [("mid", CostTier.CLOUD_MID), ("high", CostTier.CLOUD_HIGH)],
)
def test_router_actually_yields_the_requested_tier(tier: str, expected: CostTier) -> None:
    """입력 신호만 골라 라우터가 *스스로* 그 티어를 내야 한다(결정 손조립 금지).

    라우팅 규칙(03a §C.1)이 바뀌어 이 입력이 다른 티어를 내게 되면 여기서 RED가 난다 —
    프로브가 "CLOUD_MID를 쟀다"고 말하면서 실제로는 다른 모델을 부르는 상태를 막는다.
    """
    decision = Router().route(_build_request(tier, LicenseType.WHYMATH_GENERATED))
    assert decision.cost_tier == expected
    # 라우터 경유의 증거 — 등급이 결정에 승계돼야 관할 게이트가 판정할 재료가 생긴다.
    assert tuple(decision.data_licenses) == (LicenseType.WHYMATH_GENERATED,)


def test_default_grade_is_the_one_cn_allows_without_opt_in() -> None:
    """기본 등급이 바뀌면 기본 설정에서 측정이 막힌다 — 그 사실을 동결한다."""
    decision = Router().route(_build_request("mid", LicenseType.WHYMATH_GENERATED))
    assert decision.data_export_blocked is False
    assert decision.data_export_reason == "EXPORT_ALLOWED"


def test_unknown_grade_exits_2_not_1(capsys: pytest.CaptureFixture[str]) -> None:
    """인자 오류(2)와 호출 실패(1)를 구분한다 — 둘을 섞으면 실패 원인이 사라진다."""
    assert main(["--grade", "NOT_A_REAL_GRADE"]) == 2
    assert "등급" in capsys.readouterr().err


def test_missing_key_exits_1_with_the_reason(capsys: pytest.CaptureFixture[str]) -> None:
    """키가 없으면 조용히 0으로 끝나지 않고 *이유를 적어* 1로 끝난다.

    이 픽스처가 그 절을 실제로 밟는다: 키 미설정은 `DeepSeekProvider.generate`가 던지는
    `RuntimeError`이며, 프로브가 그것을 삼키면 "돌렸는데 아무 일도 없었다"가 된다.
    """
    exit_code = main(["--prompt", "1+1은?"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "호출 실패" in captured.err
    assert "키가 미설정" in captured.err
    # 호출 *전* 판정값은 실패해도 남아야 한다 — 무엇을 하려 했는지가 증거다.
    assert "라우터 결정" in captured.out
    assert "요금 구간" in captured.out
