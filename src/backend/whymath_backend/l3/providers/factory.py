"""클라우드 슬롯 팩토리 — `settings.cloud_provider` 하나가 좌석을 정한다 (ARCH-57).

**왜 이 모듈이 있는가**: `CompositeProvider(local=..., cloud=...)`의 cloud 슬롯은 호출자가
주입하는 구조인데, 종전에는 저작 경로 8곳이 각자 `AnthropicProvider()`를 하드코딩했다. 그래서
`ARCH-55`가 라이브 4회차 실측 끝에 OpenRouter 경로(`deepseek/deepseek-v4.1-flash`·공급사
`deepinfra` 고정)를 **채택하고도** 그것을 쓰는 코드가 프로브(`harness/deepseek_live_probe.py`)
뿐이었다 — 판정은 났는데 집행 지점이 없는 상태이며, CLAUDE.md 「정본화를 집행으로 착각한 완료
선언 금지」가 겨냥하는 바로 그 형태다. 이 팩토리가 그 간극을 닫는다.

**기본값은 `openrouter`다 (ARCH-64 · ARCH-55 "기본 핀 불변" 조항 번복).** ARCH-57 도입 당시에는
ARCH-55 채택 판정문("이 판정은 선택지를 넓힌 것이지 기본값을 옮긴 것이 아니며…")에 따라
`anthropic`에 고정했다. 2026-09-21 Kiki가 "학생 대면까지 한 번에" → "학생대면도 오픈라우터로
전환"으로 목적지를 확정했고 게이트 `G-cloud-mid-seat-cutover`가 판정 ①(저작+학생 대면 동시
컷오버)로 clear돼, 그 조항이 번복됐다. 판정문 원문은 남기고 번복 표기를 덧붙였다
(`docs/ops/arch55_provider_battle_smoke_runbook.md` 「채택 판정」 절). 이 모듈은 여전히 셀렉터를
**읽기만** 한다 — 기본값은 `config.py`에 있고 `test_cloud_provider_selector.py`가 동결한다.

**적용 범위 = 저작 경로 + 학생 대면 서빙(`app.py`)**. ARCH-57 시절에는 학생 대면을 이 팩토리에서
제외해 두었다(`G-arch56-availability-trigger` 발동 조건 ⓐ를 코드가 실현하지 않도록). 그 제외는
게이트 clear 뒤 ARCH-64가 풀었고, 이제는 **반대 방향**이 계약이다 — 학생 대면 앱은 반드시 이
팩토리로 좌석을 조립한다(`test_cloud_provider_selector.py`가 AST로 동결). 한 셀렉터가 두 경로를
함께 움직이므로 저작과 학생 대면이 다른 좌석을 쓰는 불일치가 생기지 않는다.

**2차 좌석은 없다** (2026-09-28 Kiki 결정 · ARCH-66 기간). 이 팩토리는 좌석 **하나**를 만든다.
Anthropic 2차 좌석 failover는 `ARCH-63`이 `G-arch66-anthropic-api-pause-review` 재개 판정 뒤
추가한다 — 그 전까지 1차 좌석 실패는 다른 클라우드 좌석으로 넘어가지 않는다. 학생 대면 조립은
429·5xx·타임아웃·미설정 실패를 LOCAL로 1회 강등하고(ARCH-69 — `CompositeProvider`
`runtime_local_degrade`), 그 밖의 실패는 "2차 좌석 없음" note를 붙여 올린다.

**관할 게이트는 이 모듈이 아니라 `CompositeProvider`가 세운다**(기존 설계 유지). 팩토리가
자기 자신을 검열하면 팩토리를 우회해 provider를 직접 쥐는 경로가 게이트까지 함께 우회한다 —
같은 이유로 `composite.py`가 디스패치 직전에 관할을 묻고, 직접 호출은
`scripts/ops/check_provider_seat_contract.py`(ARCH-46)가 따로 막는다.

**지연 구성**: 반환되는 provider는 생성 시점에 네트워크를 타지 않는다(키 조회·클라이언트
생성은 각 provider가 첫 호출까지 미룬다). 따라서 이 팩토리를 import하거나 호출하는 것만으로
CI hermetic이 깨지지 않는다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from whymath_backend.config import CloudSeat, Settings, get_settings

if TYPE_CHECKING:  # pragma: no cover - 타입 전용(런타임 import 비용·순환 회피)
    from whymath_backend.l3.interfaces import LLMProvider

__all__ = ["build_cloud_provider", "cloud_model_pins", "cloud_provider_name"]


def build_cloud_provider(settings: Settings | None = None) -> LLMProvider:
    """`settings.cloud_provider`가 지목한 클라우드 제공자를 만든다(저작 경로 + 학생 대면 공통).

    `settings`를 주지 않으면 프로세스 설정(`get_settings()`)을 읽는다 — 호출부가 설정을 들고
    다니지 않아도 되게 하되, 테스트는 명시 주입으로 프로세스 상태와 무관하게 판정한다.

    import를 함수 안에서 하는 것은 **선택되지 않은 제공자의 모듈을 끌어오지 않기** 위해서다
    (각 provider가 자기 SDK를 상단에서 import한다 — anthropic 경로만 쓰는 배포에서
    openrouter/deepseek 쪽 의존까지 로드할 이유가 없다).
    """
    resolved = settings if settings is not None else get_settings()
    name = resolved.cloud_provider

    if name == "openrouter":
        from whymath_backend.l3.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider(settings=resolved)
    if name == "deepseek":
        from whymath_backend.l3.providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(settings=resolved)

    if name == "anthropic":
        from whymath_backend.l3.providers.anthropic import AnthropicProvider

        return AnthropicProvider(settings=resolved)

    # 여기 오는 것은 Literal에 값이 늘었는데 이 함수에 분기를 안 붙인 경우다. **else로 받아
    # anthropic을 돌려주지 않는다** — 그러면 새 좌석을 고른 사람이 기본 좌석을 받고도 그 사실을
    # 모른다(CLAUDE.md 「침묵 실패 금지」). `assert`도 쓰지 않는다: `python -O`가 단언을
    # 제거하면 그 침묵이 배포에서만 되살아난다.
    raise ValueError(
        f"알 수 없는 cloud_provider: {name!r} — build_cloud_provider에 분기를 추가하라 "
        "(Literal에 값만 늘리고 팩토리를 안 고치면 여기서 멈춘다)."
    )


def cloud_model_pins(settings: Settings | None = None) -> tuple[str, str]:
    """선택된 클라우드 좌석의 (CLOUD_MID, CLOUD_HIGH) 모델 핀 — 좌석→핀 매핑의 **단일 근거**.

    두 곳이 이 매핑을 각자 들고 있으면 반드시 갈라진다(`ARCH-58`이 정확히 그 형태였다 —
    좌석은 셀렉터로 바뀌는데 기록은 anthropic 핀을 적었다). 그래서 여기 한 번만 적고
    `l3/pregenerate/provenance_bridge.model_name_for_decision()`과 좌석 집계
    (`EOS-111`)가 **같은 함수를 부른다**.

    알 수 없는 좌석은 기본 좌석으로 접지 않고 raise한다 — 접으면 "새 좌석을 골랐는데
    기본 좌석 핀이 기록되는" 침묵 실패가 되고, 그것이 ARCH-58이 상환한 사고다.
    """
    resolved = settings if settings is not None else get_settings()
    seat = resolved.cloud_provider
    if seat == "openrouter":
        return resolved.openrouter_model_mid, resolved.openrouter_model_high
    if seat == "deepseek":
        return resolved.deepseek_model_mid, resolved.deepseek_model_high
    if seat == "anthropic":
        return resolved.anthropic_model_mid, resolved.anthropic_model_high
    raise ValueError(
        f"알 수 없는 cloud_provider: {seat!r} — cloud_model_pins에 분기를 추가하라 "
        "(build_cloud_provider와 같은 셀렉터를 읽는다)."
    )


def cloud_provider_name(settings: Settings | None = None) -> CloudSeat:
    """지금 선택된 클라우드 좌석의 이름 — 리포트·로그의 *작동 신호*용.

    CLAUDE.md 「작동 신호 없는 알고리즘 부착 금지」: 저작 산출물이 "어느 제공자가 처리했는가"를
    말하지 않으면, 셀렉터를 openrouter로 두고도 anthropic이 도는 상태를 정상 응답과 구별할 수
    없다. 호출부가 이 값을 리포트에 싣는다.
    """
    resolved = settings if settings is not None else get_settings()
    return resolved.cloud_provider
