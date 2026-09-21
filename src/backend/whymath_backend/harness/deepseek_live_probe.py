"""DeepSeek 경로 라이브 프로브 — 실제로 부르고, 무엇이 돌아왔는지 보여준다 (ARCH-49 ①).

왜 필요한가
----------
`ARCH-49`가 착지시킨 것은 *배선*이고, 그 배선이 라이브에서 실제로 도는지는 키가 있는
머신(Phaiakes9)에서만 확인할 수 있다 — 개발 컨테이너는 키가 없고 egress가
`api.deepseek.com`·`openrouter.ai`를 거부한다(2026-09-17 실측: CONNECT 403). 이 프로브가
그 간극을 메운다: **한 번 돌리면 라이브 응답·실측 usage·요금 구간이 한 화면에 나온다.**

라우터를 경유한다
----------------
`Router().route()`로 결정을 받아 `CompositeProvider`에 넘긴다 — 프로바이더를 직접 쥐고
부르지 않는다(D1 · `check_provider_seat_contract.py`). 그래서 이 프로브가 통과한다는 것은
**라우팅·법적 게이트·관할 게이트를 전부 통과했다**는 뜻이기도 하다.

기본 등급은 합성 프로브(`WHYMATH_GENERATED`)다 — CN 관할이 기본 설정에서 허용하는 유일한
등급이며, 그래서 opt-in 없이 측정이 성립한다. `--grade`로 바꾸면 관할 게이트가 어떻게
판정하는지도 같은 도구로 볼 수 있다(차단도 결과다).

실패해도 증거가 남는다 (CLAUDE.md 「측정·수집 도구를 성공 경로만 보고 설계 금지」)
------------------------------------------------------------------------------
- 비-2xx는 **응답 본문을 담아** 실패한다(`_openai_compat.HttpxChatTransport`) — 공급사 필터
  거부·모델 ID 오타·쿼터 소진·키 만료가 같은 글자로 보이지 않게.
- 판정값(관할·등급·요금 구간·모델 ID)은 **호출 전에** 출력한다. 호출이 죽어도 "무엇을 하려
  했는지"가 남는다.
- 종료 코드가 판정이다: 0 성공 / 1 호출 실패 / 2 인자·설정 오류.

사용:
    python -m whymath_backend.harness.deepseek_live_probe [--route deepseek|openrouter]
                                                          [--tier mid|high] [--prompt ...]
                                                          [--grade WHYMATH_GENERATED]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from whymath_backend.config import get_settings
from whymath_backend.l3.interfaces import LLMProvider
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.provider_jurisdiction import Jurisdiction
from whymath_backend.l3.providers.composite import CompositeProvider
from whymath_backend.l3.providers.deepseek import DeepSeekProvider, pricing_window
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l3.providers.openrouter import OpenRouterProvider
from whymath_backend.l3.router import Router
from whymath_backend.schema.enums import LicenseType

_DEFAULT_PROMPT = (
    "1부터 100까지 자연수의 합을 구하고, 그 방법이 왜 성립하는지 한 문단으로 설명하라."
)
_DEFAULT_SYSTEM = "너는 한국 중고등학생을 가르치는 수학 코치다. 답보다 이유를 먼저 말한다."

_BAR = "─" * 72


def _build_request(tier: str, grade: LicenseType) -> RoutingRequest:
    """라우터가 원하는 티어를 내도록 입력 신호를 고른다(03a §C.1 규칙 3·4).

    티어를 손으로 박지 않는 이유: 그러면 `RoutingDecision`을 직접 조립하게 되고, 결정 우회
    스캐너(`check_routing_decision_bypass.py`)가 막는 형태가 된다. 입력을 골라 라우터가
    스스로 그 티어를 내게 하는 것이 계약이다.
    """
    if tier == "high":
        # 규칙 3 — killer/prove → CLOUD_HIGH
        return RoutingRequest(
            task_type="prove",
            difficulty="killer",
            requires_reasoning=True,
            student_subscription="premium",
            budget_krw=1000.0,
            data_licenses=(grade,),
        )
    # 규칙 4 — 추론 필요 + premium → CLOUD_MID
    return RoutingRequest(
        task_type="explain",
        difficulty="medium",
        requires_reasoning=True,
        student_subscription="premium",
        budget_krw=1000.0,
        data_licenses=(grade,),
    )


def _cloud_provider(route: str) -> LLMProvider:
    if route == "openrouter":
        return OpenRouterProvider()
    return DeepSeekProvider()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        grade = LicenseType(args.grade)
    except ValueError:
        print(f"[인자 오류] 알 수 없는 라이선스 등급: {args.grade!r}", file=sys.stderr)
        return 2

    cloud = _cloud_provider(args.route)
    jurisdiction = CompositeProvider.cloud_jurisdiction(cloud)
    now = datetime.now(UTC)

    # ── 호출 *전에* 판정값을 낸다 — 호출이 죽어도 무엇을 하려 했는지가 남는다 ──
    decision = Router().route(_build_request(args.tier, grade))
    print(_BAR)
    print(f"경로            : {args.route}")
    print(f"관할            : {jurisdiction.value}")
    if args.route == "openrouter":
        print(f"허용 공급사     : {list(settings.openrouter_allowed_providers)}")
    else:
        print(f"코퍼스 opt-in   : {settings.deepseek_allow_internal_corpus}")
    print(f"선언 등급       : {grade.value}")
    print(f"라우터 결정     : cost_tier={decision.cost_tier} · reason={decision.reason!r}")
    print(
        f"반출 판정       : {decision.data_export_reason} "
        f"(게이트 발동={decision.data_export_blocked})"
    )
    print(f"요금 구간       : {pricing_window(now)}  [{now.isoformat(timespec='seconds')}]")
    print(
        f"키 설정         : deepseek={settings.deepseek_configured} · "
        f"openrouter={settings.openrouter_configured}"
    )
    if jurisdiction is Jurisdiction.UNKNOWN:
        print("⚠ 관할 미확정 — 허용목록에 국적 미확인 slug가 있거나 관할이 혼재한다(전건 차단).")
    print(_BAR)

    provider = CompositeProvider(local=OllamaProvider(), cloud=cloud)
    print(f"\n프롬프트: {args.prompt}\n")
    print("호출 중 …\n")
    try:
        result = await provider.generate(args.prompt, args.system, decision)
    except Exception as exc:  # noqa: BLE001 — 실패 *원인*을 남기는 것이 이 도구의 일이다
        print(f"[호출 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(_BAR)
    print("응답 본문")
    print(_BAR)
    print(result.text or "(빈 응답 — 모델이 텍스트 블록을 내지 않았다)")
    print(_BAR)
    usage = result.usage
    if usage is None:
        print("usage          : 미측정(provider가 노출하지 않음)")
    else:
        print(f"입력 토큰      : {usage.input_tokens}")
        print(f"출력 토큰      : {usage.output_tokens}")
        print(f"캐시 적중 토큰 : {usage.cache_read_input_tokens}  (None=미측정 · 0=적중 없음)")
        latency = usage.latency_ms
        print(
            f"실측 지연      : {latency:.0f} ms"
            if latency is not None
            else "실측 지연      : 미측정"
        )
    print(_BAR)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deepseek_live_probe",
        description="DeepSeek 경로를 라우터 경유로 실제 호출하고 응답·usage·요금 구간을 낸다.",
    )
    parser.add_argument("--route", choices=("deepseek", "openrouter"), default="deepseek")
    parser.add_argument("--tier", choices=("mid", "high"), default="mid")
    parser.add_argument("--prompt", default=_DEFAULT_PROMPT)
    parser.add_argument("--system", default=_DEFAULT_SYSTEM)
    parser.add_argument(
        "--grade",
        default=LicenseType.WHYMATH_GENERATED.value,
        help="선언 라이선스 등급(기본 WHYMATH_GENERATED — CN 관할이 기본 허용하는 유일한 등급)",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
