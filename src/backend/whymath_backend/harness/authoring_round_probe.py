"""저작 회차 탐침 (EOS-208) — 저작 CLI가 *실제로 받을 환경*에서 코드 출처·라우팅·좌석을 묻는다.

왜 별도 프로세스로 묻는가
------------------------
오케스트레이터는 저작 CLI를 자식 프로세스로 부르며 환경변수(`PYTHONPATH`·
`WHYMATH_OLLAMA_REQUEST_TIMEOUT_S`)를 주입한다. 자기 프로세스 안에서 `Settings()`를 읽으면 *내가
주입하려는 값*이 아니라 *나에게 주어진 값*을 보게 된다 — 검사 대상과 실행 대상이 갈린다. 그래서
런북 [B]·[C]·[D]가 `& $Py -c ...`로 했던 것처럼 **같은 인터프리터·같은 환경의 자식**에서 묻는다.

각 탐침은 런북 [B]~[D]의 PowerShell 한 줄짜리 파이썬을 그대로 옮긴 것이다(검사 대상 함수 동일:
`_build_live_generator(authoring_tier=...)._decide_routing` · `authoring_can_reach_cloud` ·
`load_spec_plan_file` · `authoring_subject_for_codes` · 좌석 팩토리). 런북이 지적한 변별력(생성기를
손으로 만들면 [F]와 다른 경로를 검사하게 된다)을 그대로 유지한다.

출력: stdout에 JSON 한 줄. 탐침 하나가 실패해도 나머지는 계속하고, 실패한 항목은
`errors[항목] = 예외 타입명`으로 남긴다(침묵 실패 금지 — 값·시크릿은 싣지 않는다). **키 값은 절대
싣지 않는다** — 길이와 형태 불리언만.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from pathlib import Path
from typing import Any, cast

_REQUIRED_FLAGS = ("--spec-file", "--authoring-tier", "--avoid-recent", "--subscription")


def _probe_code(result: dict[str, Any], errors: dict[str, str]) -> None:
    try:
        import whymath_backend.harness.problem_corpus_accumulate as accumulate

        result["accumulate_file"] = str(Path(accumulate.__file__).resolve())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                accumulate.main(["--help"])
            except SystemExit:
                pass  # argparse --help는 SystemExit(0)로 끝난다 — 정상 경로
        help_text = buf.getvalue()
        result["cli_flags_missing"] = [f for f in _REQUIRED_FLAGS if f not in help_text]
    except Exception as exc:  # noqa: BLE001 — 탐침은 실패를 타입명으로 보고하고 계속한다
        errors["code"] = type(exc).__name__


def _probe_settings(result: dict[str, Any], errors: dict[str, str]) -> None:
    try:
        from whymath_backend.config import Settings

        settings = Settings()
        result["ollama_request_timeout_s"] = settings.ollama_request_timeout_s
        result["ollama_host"] = settings.ollama_host
    except Exception as exc:  # noqa: BLE001
        errors["settings"] = type(exc).__name__


def _probe_spec_plan(path: Path, result: dict[str, Any], errors: dict[str, str]) -> None:
    try:
        from whymath_backend.harness.problem_corpus_accumulate import (
            authoring_subject_for_codes,
            load_spec_plan_file,
        )

        entries = load_spec_plan_file(
            path, default_standard_code="", default_difficulty=2.5, default_topic_hint="x"
        )
        result["spec_ids"] = [spec_id for spec_id, _, _ in entries]
        codes = sorted({c for _, spec, _ in entries for c in spec.achievement_standard_codes})
        subject, prefix = authoring_subject_for_codes(codes)
        result["subject"] = subject
        result["slug_prefix"] = prefix
    except Exception as exc:  # noqa: BLE001
        errors["spec_plan"] = type(exc).__name__


def _probe_local(
    tier: str, standard_code: str, result: dict[str, Any], errors: dict[str, str]
) -> None:
    try:
        from whymath_backend.harness.problem_corpus_accumulate import (
            _build_live_generator,
            authoring_can_reach_cloud,
        )
        from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
        from whymath_backend.l3.router import resolve_model

        generator = _build_live_generator("x", authoring_tier=tier)
        # 런북 [B]의 $Probe와 같은 경로 — 구체 생성기의 라우팅 결정 메서드를 그대로 부른다.
        decision = cast(Any, generator)._decide_routing(
            EquivalenceSpec(
                achievement_standard_codes=frozenset({standard_code}),
                target_misconception_ids=frozenset(),
                difficulty_overall=3.0,
                answer_format=None,
            )
        )
        tier_value = str(getattr(decision.cost_tier, "value", decision.cost_tier))
        result["local_cost_tier"] = tier_value
        result["local_model"] = (
            resolve_model(decision.local_family, decision.local_model)
            if tier_value == "local"
            else None
        )
        # 신호 없는 저작이 클라우드에 닿지 않는다 — 로컬 좌석이 몰래 유료 호출을 하지 않는다.
        result["local_only"] = (not authoring_can_reach_cloud(None, None)) and tier_value == "local"
    except Exception as exc:  # noqa: BLE001
        errors["local"] = type(exc).__name__


def _probe_cloud(
    subscription: str, budget_krw: float, result: dict[str, Any], errors: dict[str, str]
) -> None:
    try:
        from whymath_backend.config import Settings
        from whymath_backend.harness.problem_corpus_accumulate import authoring_can_reach_cloud
        from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name
        from whymath_backend.l3.providers.openrouter import jurisdiction_of_slugs

        settings = Settings()
        key = settings.openrouter_api_key.get_secret_value()
        result["cloud_seat"] = str(cloud_provider_name(settings))
        result["cloud_pin_mid"] = cloud_model_pins(settings)[0]
        result["cloud_allowed_providers"] = list(settings.openrouter_allowed_providers)
        result["cloud_jurisdiction"] = jurisdiction_of_slugs(
            settings.openrouter_allowed_providers
        ).value
        result["anthropic_api_enabled"] = bool(settings.anthropic_api_enabled)
        result["anthropic_configured"] = bool(settings.anthropic_configured)
        # 키는 길이·형태만 — 값은 어디에도 싣지 않는다.
        result["key_length"] = len(key)
        result["key_shape_ok"] = (
            len(key) >= 20 and key.startswith("sk-or-") and chr(0x2026) not in key
        )
        result["cloud_reach_paid"] = authoring_can_reach_cloud(subscription, budget_krw)
    except Exception as exc:  # noqa: BLE001
        errors["cloud"] = type(exc).__name__


def _probe_tk(result: dict[str, Any], errors: dict[str, str]) -> None:
    try:
        import tkinter  # noqa: F401

        result["tk_ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["tk_ok"] = False
        errors["tk"] = type(exc).__name__


def run_probe(
    *,
    spec_plan: Path | None,
    local_tier: str | None,
    cloud_subscription: str | None,
    cloud_budget_krw: float | None,
    check_tk: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"probe_file": str(Path(__file__).resolve())}
    errors: dict[str, str] = {}
    _probe_code(result, errors)
    _probe_settings(result, errors)
    first_code = "[12미적Ⅰ-02-07]"
    if spec_plan is not None:
        _probe_spec_plan(spec_plan, result, errors)
        try:
            for line in spec_plan.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    first_code = str(json.loads(line).get("standard_code") or first_code)
                    break
        except (OSError, ValueError) as exc:
            errors.setdefault("spec_plan", type(exc).__name__)
    if local_tier is not None:
        _probe_local(local_tier, first_code, result, errors)
    if cloud_subscription is not None and cloud_budget_krw is not None:
        _probe_cloud(cloud_subscription, cloud_budget_krw, result, errors)
    if check_tk:
        _probe_tk(result, errors)
    result["errors"] = errors
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.authoring_round_probe",
        description="저작 회차 탐침 — 자식 환경의 코드 출처·라우팅·좌석·타임아웃(JSON 한 줄)",
    )
    parser.add_argument("--spec-plan", type=Path, default=None)
    parser.add_argument("--local-tier", choices=("mid", "quality"), default=None)
    parser.add_argument("--cloud-subscription", default=None)
    parser.add_argument("--cloud-budget-krw", type=float, default=None)
    parser.add_argument("--check-tk", action="store_true")
    args = parser.parse_args(argv)
    result = run_probe(
        spec_plan=args.spec_plan,
        local_tier=args.local_tier,
        cloud_subscription=args.cloud_subscription,
        cloud_budget_krw=args.cloud_budget_krw,
        check_tk=args.check_tk,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
