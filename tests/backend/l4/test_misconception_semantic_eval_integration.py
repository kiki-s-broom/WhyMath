"""오개념 의미 매칭 측정 하니스 *라이브* 통합 — slice 107 (WHYMATH_RUN_INTEGRATION 게이트).

라이브 bge-m3(`LocalEmbeddingProvider`)로 전체 프로브셋(98줄)을 측정해 *실제* 결합 recall·방향맹
false-positive를 낸다. 이 테스트의 목적은 **측정**이다 — 품질을 hard-fail하지 않는다(Kiki가 출력
수치를 보고 플립 임계 R·F를 확정한다). loose smoke만 단언하고(`total==98`·비율 ∈ [0,1] 등),
recall/FP 숫자는 print로 흘려 `-s`로 Kiki가 확인한다.

CI는 `WHYMATH_RUN_INTEGRATION`을 설정하지 않으므로 자동 skip(conftest.py 게이트). 켜져 돌더라도
bge-m3 가중치 미도달(오프라인·HF 429 rate-limit)이면 *fail이 아니라 skip*한다(slice 106
`test_misconception_semantic_integration.py`의 try/except skip 패턴 답습 — 라이브 자원 부재는
환경 이슈이지 코드 결함이 아님). Phaiakes9처럼 가중치가 캐시된 환경에서만 실제로 돈다.
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.misconception.probes import probes_path
from whymath_backend.l4.misconception.semantic.matcher import SemanticMatcher
from whymath_backend.l4.misconception.semantic.provider import LocalEmbeddingProvider
from whymath_backend.l4.misconception.semantic_eval import (
    MisconceptionProbe,
    evaluate,
    format_report,
    load_probes,
    run_probes,
)

from ._live_resources import require_local_embedding

pytestmark = pytest.mark.integration


# 프로브셋은 프로덕션 패키지 데이터(`probes_v1.jsonl`)로 단일화됐다(prod→tests 역방향 의존
# 회피) — `probes_path()`로 실파일을 빌려 `load_probes`에 넘긴다(설치 트리·개발 트리 공통).
def _load_real_probes() -> list[MisconceptionProbe]:
    with probes_path() as path:
        return load_probes(path)


class TestSemanticEvalLive:
    """bge-m3 라이브로 전체 프로브셋 측정 — 출력은 측정용, 단언은 loose smoke."""

    def test_full_probeset_recall_and_fp_measurement(self) -> None:
        probes = _load_real_probes()
        # 98 + 극값 MC 4 + 843 트랜치1~5 각 12 + #1068 P1 회귀 1건
        assert len(probes) == 169

        # 슬110(#5): bge-m3 자원 미도달은 사전체크로 skip·측정 코드 버그는 fail로 전파.
        require_local_embedding()
        provider = LocalEmbeddingProvider()
        matcher = SemanticMatcher(provider=provider)
        outcomes = run_probes(probes, provider=provider, matcher=matcher, threshold=0.55, top_k=5)

        report = evaluate(outcomes)
        # Kiki 확인용 출력(-s) — 플립 임계 R·F 결정 근거.
        print("\n" + "=" * 70)
        print("slice 107 의미 매칭 측정 (bge-m3 라이브·threshold=0.55)")
        print("=" * 70)
        print(format_report(report))

        # loose smoke(측정이 목적·품질 hard-fail 아님): 구조 무결성만 단언.
        assert report.total == 169
        assert report.total_recall == 98
        assert report.total_fp == 71
        rlb = report.recall_lower_bound()
        fub = report.fp_rate_upper_bound()
        assert rlb is not None and 0.0 <= rlb <= 1.0
        assert fub is not None and 0.0 <= fub <= 1.0
        # recall/FP 점추정도 [0,1](측정값 자체는 자유·구조만 단언).
        assert report.recall is not None and 0.0 <= report.recall <= 1.0
        assert report.false_positive_rate is not None
        assert 0.0 <= report.false_positive_rate <= 1.0

    def test_threshold_sweep_operating_curve(self) -> None:
        """임계값 스윕 — 운영점 곡선(recall↓·FP↓ as threshold↑)을 Kiki가 눈으로 본다."""
        probes = _load_real_probes()
        require_local_embedding()
        provider = LocalEmbeddingProvider()
        matcher = SemanticMatcher(provider=provider)

        print("\n" + "=" * 70)
        print("slice 107 임계값 스윕 (운영점 곡선)")
        print("=" * 70)
        for threshold in (0.40, 0.50, 0.55, 0.60, 0.70):
            outcomes = run_probes(
                probes, provider=provider, matcher=matcher, threshold=threshold, top_k=5
            )
            report = evaluate(outcomes)
            recall = report.recall
            fp = report.false_positive_rate
            near = report.near_false_positive_rate
            print(
                f"  threshold={threshold:.2f} "
                f"recall={recall if recall is None else round(recall, 3)} "
                f"fp_rate={fp if fp is None else round(fp, 3)} "
                f"near_fp={near if near is None else round(near, 3)}"
            )
            # smoke: 비율은 [0,1] 또는 None.
            for value in (recall, fp, near):
                assert value is None or 0.0 <= value <= 1.0
