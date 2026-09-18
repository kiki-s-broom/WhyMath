"""OpenRouter 엔드포인트 조회 — 공급사 slug·양자화·단가를 실측으로 확정한다 (ARCH-49 ⑨).

왜 이 도구가 따로 필요한가
------------------------
`l3/providers/openrouter.PROVIDER_JURISDICTIONS`는 **우리가 국적을 아는 공급사만** 담는다.
거기 없는 slug는 `UNKNOWN`이고 전건 차단이므로, 목록이 좁으면 쓸 수 있는 공급사도 좁다.
그 목록을 넓히려면 근거가 필요한데, 근거의 1차 자료는 OpenRouter가 모델별로 내놓는
**엔드포인트 목록**이다(공급사 tag·양자화·컨텍스트·단가).

**모델 slug 자체도 이 도구가 확정한다.** 이 저장소는 같은 자리에서 한 번 틀렸다 —
웹 자료 3곳이 일치해 적은 `deepseek-v4-flash`가 DeepSeek 공식 API에서는 받아들여지지
않는 이름이었다(실제는 `deepseek-flash`, ARCH-49 acceptance ⑦). 제품 표기와 API id는
다를 수 있으므로 **`/models`가 돌려주는 문자열만** 핀한다. `--search`가 그 조회다.

경계 (정직 고지)
--------------
OpenRouter API는 공급사의 **법인 국적을 말해 주지 않는다** — `tag`(예 `deepinfra/fp8`)와
양자화·단가만 준다. 국적은 사람이 1차 자료로 확인해 `PROVIDER_JURISDICTIONS`에 근거와
함께 적는 축이며, 이 도구는 *무엇을 확인해야 하는지의 목록*을 만들어 줄 뿐이다.
그 구분을 흐리면 "API가 말해 줬다"와 "우리가 확인했다"가 같은 칸에 들어간다.

개발 컨테이너에서는 돌지 않는다 — egress 프록시가 `openrouter.ai`를 거부한다
(2026-09-17 실측). 실행처는 키가 있는 Phaiakes9다.

사용:
    python -m whymath_backend.harness.openrouter_endpoints_probe --search deepseek flash
    python -m whymath_backend.harness.openrouter_endpoints_probe --model deepseek/deepseek-v4-flash
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from whymath_backend.config import get_settings
from whymath_backend.l3.providers.openrouter import (
    PROVIDER_JURISDICTIONS,
    provider_slug_from_tag,
)

_BAR = "─" * 78


def _get(url: str, token: str, timeout_s: float) -> Any:
    """GET 1회 — 비-2xx는 **응답 본문을 담아** 실패한다(실패 원인을 남긴다)."""
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover — 환경 의존
        raise RuntimeError("httpx가 설치되지 않았습니다 (`pip install httpx`).") from exc
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=timeout_s) as client:
        response = client.get(url, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"조회 실패 HTTP {response.status_code}: {response.text[:2000]}")
        payload: Any = response.json()
        return payload


def _rows(payload: Any) -> list[dict[str, Any]]:
    """`{"data": [...]}` 형태에서 목록을 방어적으로 꺼낸다(형태가 다르면 빈 목록)."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            endpoints = data.get("endpoints")
            if isinstance(endpoints, list):
                return [r for r in endpoints if isinstance(r, dict)]
    return []


def _search(settings: Any, terms: list[str]) -> int:
    """`/models`에서 검색어를 모두 포함하는 id를 출력한다 — slug 확정용."""
    payload = _get(
        f"{settings.openrouter_base_url.rstrip('/')}/models",
        settings.openrouter_api_key.get_secret_value(),
        settings.openrouter_request_timeout_s,
    )
    rows = _rows(payload)
    if not rows:
        print("측정 실패 — /models 응답에서 목록을 읽지 못했다(형태 변경 의심).", file=sys.stderr)
        return 1
    needles = [t.lower() for t in terms]
    hits = [r for r in rows if all(n in str(r.get("id", "")).lower() for n in needles)]
    print(f"{_BAR}\n/models 전체 {len(rows)}건 중 '{' '.join(terms)}' 일치 {len(hits)}건\n{_BAR}")
    if not hits:
        print("일치 0건 — 검색어를 넓혀 보라(제품 표기와 API id는 다를 수 있다).")
        return 1
    for row in hits:
        raw_pricing = row.get("pricing")
        pricing: dict[str, Any] = raw_pricing if isinstance(raw_pricing, dict) else {}
        print(f"  id   : {row.get('id')}")
        print(f"  name : {row.get('name')}")
        print(f"  단가  : prompt={pricing.get('prompt')} · completion={pricing.get('completion')}")
        print()
    return 0


def _endpoints(settings: Any, model: str) -> int:
    """`/models/{author}/{slug}/endpoints` — 공급사·양자화·단가 표를 낸다."""
    if "/" not in model:
        print(f"[인자 오류] 모델은 `author/slug` 형태여야 한다(받은 {model!r})", file=sys.stderr)
        return 2
    payload = _get(
        f"{settings.openrouter_base_url.rstrip('/')}/models/{model}/endpoints",
        settings.openrouter_api_key.get_secret_value(),
        settings.openrouter_request_timeout_s,
    )
    rows = _rows(payload)
    if not rows:
        print("측정 실패 — endpoints 응답에서 목록을 읽지 못했다.", file=sys.stderr)
        return 1

    print(f"{_BAR}\n{model} — 엔드포인트 {len(rows)}곳\n{_BAR}")
    print(f"{'slug':<18}{'tag':<24}{'양자화':<10}{'prompt':<14}{'completion':<14}관할(우리 판정)")
    unknown: list[str] = []
    for row in rows:
        tag = str(row.get("tag") or row.get("name") or "")
        slug = provider_slug_from_tag(tag)
        quant = str(row.get("quantization") or "unknown")
        raw_pricing = row.get("pricing")
        pricing: dict[str, Any] = raw_pricing if isinstance(raw_pricing, dict) else {}
        known = PROVIDER_JURISDICTIONS.get(slug)
        verdict = known.value if known is not None else "미확인 → 전건 차단"
        if known is None and slug not in unknown:
            unknown.append(slug)
        print(
            f"{slug:<18}{tag:<24}{quant:<10}"
            f"{str(pricing.get('prompt')):<14}{str(pricing.get('completion')):<14}{verdict}"
        )
    print(_BAR)
    print(f"국적 미확인 {len(unknown)}곳: {', '.join(unknown) if unknown else '(없음)'}")
    print(
        "\n※ OpenRouter API는 **법인 국적을 말해 주지 않는다** — 위 '관할'은 우리 목록\n"
        "   (`l3/providers/openrouter.PROVIDER_JURISDICTIONS`)의 판정이다. 미확인 slug를\n"
        "   넓히려면 각 공급사 상세 페이지·법인 등록 등 1차 자료로 국적을 확인하고 그\n"
        "   근거와 함께 목록에 적는다. 이 도구는 *무엇을 확인해야 하는지*까지만 말한다."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="openrouter_endpoints_probe",
        description="OpenRouter 모델 slug 확정 + 공급사 엔드포인트 표 (ARCH-49 ⑨).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--search", nargs="+", metavar="용어", help="/models에서 id 검색")
    group.add_argument("--model", metavar="author/slug", help="엔드포인트 조회 대상")
    parser.add_argument("--json", action="store_true", help="원본 JSON을 함께 출력")
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.openrouter_configured:
        print(
            "[설정 오류] OpenRouter 키가 미설정이다 "
            "(WHYMATH_OPENROUTER_API_KEY 또는 OPENROUTER_API_KEY).",
            file=sys.stderr,
        )
        return 2
    try:
        if args.search:
            return _search(settings, args.search)
        code = _endpoints(settings, args.model)
    except Exception as exc:  # noqa: BLE001 — 실패 *원인*을 남기는 것이 이 도구의 일이다
        print(f"[조회 실패] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        raw = _get(
            f"{settings.openrouter_base_url.rstrip('/')}/models/{args.model}/endpoints",
            settings.openrouter_api_key.get_secret_value(),
            settings.openrouter_request_timeout_s,
        )
        print("\n----- 원본 JSON -----")
        print(json.dumps(raw, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
