"""오개념 방향 판별 judge *라이브* 통합 — slice 108 (WHYMATH_RUN_INTEGRATION 게이트).

라이브 L3(로컬 Ollama·라우터 경유)로 방향 판별 judge를 *실제로* 돌려, substring·임베딩 방향맹의
거짓양성을 judge가 얼마나 거르는지(judge_fp_reduction)와 recall을 얼마나 보존하는지
(judge_recall_loss)를 측정한다. 이 테스트의 목적은 **측정**이다 — 품질을 hard-fail하지 않는다
(Kiki가 출력 수치를 보고 coach 배선 여부를 후속 슬라이스에서 결정한다). loose smoke만 단언하고
(`total==98`·비율 ∈ [0,1] 등), judge 전후 수치는 print로 흘려 `-s`로 Kiki가 확인한다.

CI는 `WHYMATH_RUN_INTEGRATION`을 설정하지 않으므로 자동 skip(conftest.py 게이트). 켜져 돌더라도
로컬 Ollama 미도달(모델 미설치·서버 다운)이면 *fail이 아니라 skip*한다(슬106/107 try/except skip
패턴 답습 — 라이브 자원 부재는 환경 이슈이지 코드 결함이 아님). Phaiakes9처럼 Ollama가 떠 있고
로컬 모델이 받아진 환경에서만 실제로 돈다.

비용 메모: judge는 *고비용*이다(후보당 LLM 1회 왕복). 측정은 *프로브 일부*(FP·recall 대표 표본)
로 제한하지 않고 전체 98줄을 돌리되, 로컬 FAST(L3JudgeSeam이 max_latency<2000으로 FAST 강제)라
클라우드 비용 0이다(CLAUDE.md 로컬 우선).
"""

from __future__ import annotations

import pytest

from whymath_backend.l4.misconception.judge import LLMJudge
from whymath_backend.l4.misconception.judge_seam import L3JudgeSeam
from whymath_backend.l4.misconception.probes import probes_path
from whymath_backend.l4.misconception.semantic.matcher import SemanticMatcher
from whymath_backend.l4.misconception.semantic.provider import LocalEmbeddingProvider
from whymath_backend.l4.misconception.semantic_eval import (
    evaluate,
    format_report,
    load_probes,
    run_probes_with_judge,
)

from ._live_resources import (
    require_local_embedding,
    require_ollama_reachable,
)

pytestmark = pytest.mark.integration


class TestJudgeLive:
    """라이브 L3(로컬 Ollama) judge로 전체 프로브셋 측정 — 출력은 측정용, 단언은 loose smoke."""

    @pytest.mark.asyncio
    async def test_full_probeset_judge_fp_reduction_measurement(self) -> None:
        # 프로브셋은 프로덕션 패키지 데이터(`probes_v1.jsonl`)로 단일화됐다 — `probes_path()`로
        # 실파일을 빌려 `load_probes`에 넘긴다(설치 트리·개발 트리 공통).
        with probes_path() as path:
            probes = load_probes(path)
        # 98 + 극값 MC 4 + 843 트랜치1~5 각 12 + #1068 P1 회귀 1건
        assert len(probes) == 169

        # 슬110(#5): bge-m3·Ollama 자원 미도달은 사전체크로 skip(judge=UNCERTAIN 무의미 측정
        # 회피)·측정 경로 코드 버그는 fail로 전파.
        # judge 측정은 임베딩(후보)+Ollama(판정) 둘 다 필요.
        require_local_embedding()
        await require_ollama_reachable()
        provider = LocalEmbeddingProvider()
        matcher = SemanticMatcher(provider=provider)
        judge = LLMJudge(seam=L3JudgeSeam())
        outcomes = await run_probes_with_judge(
            probes,
            provider=provider,
            judge=judge,
            matcher=matcher,
            threshold=0.55,
            top_k=5,
        )

        report = evaluate(outcomes)
        # Kiki 확인용 출력(-s) — judge 후속 coach 배선 결정 근거.
        print("\n" + "=" * 70)
        print("slice 108 방향 판별 judge 측정 (로컬 L3·bge-m3 임베딩·threshold=0.55)")
        print("=" * 70)
        print(format_report(report))

        # loose smoke(측정이 목적·품질 hard-fail 아님): 구조 무결성만 단언.
        assert report.total == 169
        assert report.total_recall == 98
        assert report.total_fp == 71
        # judge 후 지표는 None이거나 [0,1](Ollama 미도달이면 전부 UNCERTAIN→의미와 동일).
        for value in (
            report.judge_fp_rate,
            report.judge_recall,
            report.judge_fp_reduction,
            report.judge_recall_loss,
        ):
            assert value is None or 0.0 <= value <= 1.0
        # judge는 *제거만* 하므로 judge 후 FP ≤ 의미 FP·judge 후 recall ≤ 의미 recall(단조).
        assert report.judge_false_positives <= report.semantic_false_positives
        assert report.judge_caught_recall <= report.caught_recall
        # 각 outcome 분할 불변(kept ⊕ removed = semantic_ids).
        for o in outcomes:
            assert set(o.judge_kept_ids) | set(o.judge_removed_ids) == set(o.semantic_ids)
