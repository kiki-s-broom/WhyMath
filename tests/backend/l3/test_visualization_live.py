"""L3 시각화 명세 생성 *라이브* 평가 — 패밀리 비교 (Phaiakes9 전용·작업 I).

기본 SKIP. 실행하려면 `WHYMATH_RUN_INTEGRATION=1`(+ 필요 시 `WHYMATH_OLLAMA_HOST`)을
설정한다. CI 단위 잡은 이 변수를 설정하지 않고(conftest 게이트), 통합잡은 이 파일을 **파일 단위로**
`--ignore`해 *실행하지 않는다*(OPS-137 — 제외 사유 장부 `L3_EXTERNAL_SERVICE_EXCLUSIONS`) — 실
모델·GPU가 필요하기 때문(test_ollama_integration과 동일).

무엇을 검증하나:
    H가 보강한 ① `SimulationSpec.outcomes` 스키마와 ② L3 프롬프트 예시로, 로컬 LLM이 실제로
    유효한 outcomes(임의 분포)·3D surface·2D 함수 명세를 *생성*하는지를 **프로덕션 프롬프트·
    검증 게이트 그대로** 태워 측정한다(`build_visualization_prompt` + `parse_visualization_spec`).
    채점은 결정적(LLM-as-judge 아님)이라 재현 가능하다.

패밀리 비교(이 테스트의 핵심):
    같은 (개념→명세) 작업을 세 패밀리로 강제 라우팅해 유효율을 비교한다 —
      - GENERAL(qwen2.5:7b) / MATH(qwen2-math:7b) / VISION(qwen3-vl:8b).
    각 후보는 라우터 매트릭스의 (패밀리×크기) 셀이므로 `resolve_model`로 실제 모델 ID를
    얻는다(매트릭스: GENERAL/MID·MATH/MID·VISION/FAST — router.LOCAL_MODEL_MATRIX). viz
    `generate`는 *프로덕션에서 MATH로 라우팅*되므로(router NLP 집합에 없음), 단언은 MATH
    패밀리에 건다(타입별 유효율 ≥ VIZ_MIN_VALID). 나머지 패밀리는 비교 측정만 한다 —
    MATH가 미달이면 best 패밀리가 viz 라우팅 보정 후보다(라우터 변경은 별도 결정).

결정성 주의:
    `OllamaProvider`는 temperature 옵션을 노출하지 않아(프로덕션 호출 규약 그대로) 샘플링이
    완전 결정적이지는 않다 — 실행마다 유효율이 다소 출렁일 수 있다. 항목 수(타입별 2~4개)와
    하한(0.6)에 여유를 둬 잡음에 견디게 했다. 엄밀 재현이 필요하면 항목을 늘려 평균을 안정화.
"""

from __future__ import annotations

import json
import platform
from dataclasses import asdict
from pathlib import Path

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.models import (
    CostTier,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
)
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l3.router import resolve_model
from whymath_backend.l3.visualization import build_visualization_prompt
from whymath_backend.l3.viz_eval import (
    EVAL_ITEMS,
    PRODUCTION_FAMILY,
    VIZ_MIN_VALID,
    VizRunRecord,
    aggregate,
    build_verdicts,
    grade_spec,
)

pytestmark = pytest.mark.integration


# 후보 모델 = (패밀리, 크기, 패밀리 라벨). 매트릭스 셀이라 resolve_model로 실 모델 ID를 얻는다.
#   GENERAL/MID=qwen2.5:7b · MATH/MID=qwen2-math:7b · VISION/FAST=qwen3-vl:8b (router 매트릭스).
_CANDIDATES: tuple[tuple[ModelFamily, LocalModelTier, str], ...] = (
    (ModelFamily.GENERAL, LocalModelTier.MID, "general"),
    (ModelFamily.MATH, LocalModelTier.MID, "math"),
    (ModelFamily.VISION, LocalModelTier.FAST, "vision"),
)

# 패밀리 크기별 예상 지연(ms) — RoutingDecision 필수 필드(측정엔 영향 없음, 03a §A.1).
_EST_LATENCY_MS: dict[LocalModelTier, int] = {
    LocalModelTier.FAST: 1010,
    LocalModelTier.MID: 3918,
}


def _forced_decision(family: ModelFamily, tier: LocalModelTier) -> RoutingDecision:
    """라우터를 우회해 후보 (패밀리×크기)를 *직접 지정*하는 LOCAL 결정 — 패밀리 비교용."""
    return RoutingDecision(
        cost_tier=CostTier.LOCAL,
        local_family=family,
        local_model=tier,
        mode="sync",
        reason="viz-eval-family-comparison",
        est_latency_ms=_EST_LATENCY_MS[tier],
        est_cost_krw=0.0,
    )


async def test_visualization_generation_family_comparison() -> None:
    """세 패밀리 × 평가셋으로 시각화 명세를 생성·채점하고 패밀리 비교 리포트를 남긴다.

    단언: 프로덕션 패밀리(MATH)가 *각 시각화 타입*에서 유효율 ≥ VIZ_MIN_VALID. 미달이면
    실패로 신호(viz 라우팅 보정 필요 근거). 나머지 패밀리는 비교 측정만 한다.
    """
    provider = OllamaProvider(settings=Settings())
    status = await provider.check_status()
    if not status.reachable:
        pytest.skip(f"Ollama 미도달: {status.error}")

    # 후보별 실 모델 ID 해석 + 설치 여부 확인. 미설치 후보는 비교에서 제외(측정 불가).
    available: list[tuple[ModelFamily, LocalModelTier, str, str]] = []
    for family, tier, label in _CANDIDATES:
        model_id = resolve_model(family, tier)
        if model_id in status.missing:
            if label == PRODUCTION_FAMILY:
                pytest.skip(f"프로덕션 패밀리 모델 미설치: {model_id} (`ollama pull {model_id}`)")
            continue  # 비교 대상 후보 누락 — 측정만 빠짐(프로덕션 단언은 유지)
        available.append((family, tier, label, model_id))

    # 후보 × 항목 순차 생성·채점(품질 측정은 throughput이 아니라 정확성이 목적 — quality_eval).
    records: list[VizRunRecord] = []
    for family, tier, label, model_id in available:
        decision = _forced_decision(family, tier)
        for item in EVAL_ITEMS:
            system_prompt, user_prompt = build_visualization_prompt(item.concept, item.level)
            try:
                raw = await provider.generate(user_prompt, system_prompt, decision)
            except Exception as exc:  # noqa: BLE001 — 호출 실패도 0점(미파싱)으로 흡수
                raw = f"ERROR: {type(exc).__name__}: {exc}"
            score = grade_spec(raw, item.expected_type, item_id=item.id)
            records.append(VizRunRecord(model_id=model_id, family=label, item=item, score=score))

    cells = aggregate(records)
    verdicts = build_verdicts(cells)

    # ── 리포트: results/viz_eval_<host>.json + 콘솔 비교표(Kiki가 패밀리 적합 판단) ──
    host = platform.node() or "unknown"
    report = {
        "host": host,
        "threshold": VIZ_MIN_VALID,
        "production_family": PRODUCTION_FAMILY,
        "n_items": len(EVAL_ITEMS),
        "candidates": [
            {"family": label, "model_id": model_id} for _, _, label, model_id in available
        ],
        "cells": [asdict(c) for c in cells],
        "verdicts": [asdict(v) for v in verdicts],
    }
    out_dir = Path("results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"viz_eval_{host}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== L3 시각화 생성 패밀리 비교 (결과: {out_path}) ===")
    print(f"{'타입':<28}{'패밀리':<10}{'유효율':>8}{'  (유효/전체)'}")
    for cell in cells:
        print(
            f"{cell.viz_type:<28}{cell.family:<10}"
            f"{cell.valid_rate:>7.0%}  ({cell.n_valid}/{cell.n_items})"
        )
    print("--- 타입별 판정 ---")
    for v in verdicts:
        print(f"  {v.verdict}")

    # ── 단언: 프로덕션 패밀리(MATH)가 각 타입에서 하한 충족 ──
    failures = [v for v in verdicts if not v.meets_threshold]
    assert not failures, (
        "프로덕션 패밀리("
        + PRODUCTION_FAMILY
        + ")가 다음 타입에서 유효율 하한 미달 — viz 라우팅 보정 필요:\n"
        + "\n".join(f"  - {v.verdict}" for v in failures)
    )
