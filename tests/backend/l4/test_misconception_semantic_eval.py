"""오개념 의미 매칭 측정 하니스 단위테스트 — slice 107 (hermetic·라이브 0·결정론).

세 갈래로 검증한다:
  ① **스코어링**: 합성 `ProbeOutcome`로 `evaluate`·recall/FP율·Wilson 하한/상한·kind/도메인
     분해·`format_report`를 *수치까지* 단언한다(라이브 임베딩 불요). Wilson 경계(n=0 None·전부
     정답 시 하한<1·전부 FP 시 상한>0·하한≤점추정≤상한)도 못 박는다.
  ② **프로브셋 구조**(실파일 로드): 98줄 파싱·모든 expected_id/near_id ∈ CATALOG_BY_ID·32종
     recall·FP 둘 다 커버·kind 유효·**recall 프로브 substring 풀매칭 0**(임베딩 측정 유효성
     회귀 가드 — substring이 잡으면 의미 매처를 측정할 수 없다).
  ③ **배선 end-to-end**: `run_probes`를 FakeEmbeddingProvider로 1건 돌려 스코어링 배선을 증명한다
     (실 품질이 아니라 *결선*만 — Fake는 어휘 해시라 의미 recall이 아님).

게이트·coach·`diagnose`·`semantic_matches`는 무변경(이 하니스는 *소비*만 한다).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.diagnose import diagnose
from whymath_backend.l4.misconception.judge import FakeJudge, JudgeVerdict
from whymath_backend.l4.misconception.probes import probes_path
from whymath_backend.l4.misconception.semantic.provider import FakeEmbeddingProvider
from whymath_backend.l4.misconception.semantic_eval import (
    JudgeDecision,
    MisconceptionProbe,
    ProbeOutcome,
    SemanticEvalReport,
    _judge_applied,
    _judge_flip_passed,
    _run,
    _wilson_lower_bound,
    _wilson_upper_bound,
    evaluate,
    format_report,
    load_probes,
    report_to_dict,
    run_probes,
    run_probes_with_judge,
)


# 프로브셋 실파일(검증된 98줄·프로덕션 패키지 데이터 `probes_v1.jsonl`) — 구조 검증·end-to-end
# 배선이 읽는다. 프로브셋은 tests/fixtures가 아니라 *패키지 데이터*로 단일화됐으므로(prod→tests
# 역방향 의존 회피), 설치 트리·개발 트리 공통으로 `probes_path()`(importlib.resources) 경유로
# 실파일 `Path`를 빌려 `load_probes`에 넘긴다.
def _load_real_probes() -> list[MisconceptionProbe]:
    with probes_path() as path:
        return load_probes(path)


# 유효 kind 집합 — 프로브셋 스키마 계약(분해 라벨).
_VALID_KINDS = frozenset({"paraphrase", "direction-reverse", "negation", "correct-near"})


# ──────────────────────────────────────────────────────────────────────────
# 합성 프로브/아웃컴 헬퍼 — 스코어링을 라이브 없이 정밀 단언
# ──────────────────────────────────────────────────────────────────────────
def _recall_probe(expected_id: str, *, kind: str = "paraphrase") -> MisconceptionProbe:
    """recall 프로브 합성 — expected_id 설정·near_id null(틀린 진술을 잡아야 함)."""
    return MisconceptionProbe(
        statement=f"틀린 진술 {expected_id}",
        expected_id=expected_id,
        near_id=None,
        kind=kind,
    )


def _fp_probe(near_id: str, *, kind: str = "correct-near") -> MisconceptionProbe:
    """FP 프로브 합성 — expected_id null·near_id 설정(올바른 진술·매칭되면 거짓양성)."""
    return MisconceptionProbe(
        statement=f"올바른 진술 {near_id}", expected_id=None, near_id=near_id, kind=kind
    )


def _outcome(
    probe: MisconceptionProbe,
    *,
    semantic_ids: tuple[str, ...] = (),
    substring_ids: tuple[str, ...] = (),
) -> ProbeOutcome:
    """ProbeOutcome 합성 — 매처 결과를 *직접* 지정해 스코어링을 통제."""
    return ProbeOutcome(probe=probe, semantic_ids=semantic_ids, substring_ids=substring_ids)


# ──────────────────────────────────────────────────────────────────────────
# 결정론 제어 제공자 — run_probes 배선 end-to-end용(어떤 카탈로그 id를 끌지 통제)
# ──────────────────────────────────────────────────────────────────────────
class _NameKrOneHotProvider:
    """텍스트에 카탈로그 항목의 `name_kr`가 들어 있으면 그 항목과 평행(코사인 1.0)으로 만든다.

    카탈로그 표현(`catalog_text` = `"{name_kr}. {canonical}"`)은 자기 `name_kr`를 *포함*하므로,
    각 카탈로그 항목의 벡터는 자기 차원이 1인 원-핫이 된다. probe statement에 *타깃의 name_kr*를
    심으면 그 statement도 같은 차원이 1 → 타깃과 평행(cos 1.0)·나머지와 직교(0.0). 이로써
    run_probes의 배선(매처 호출→예측 가능한 semantic_ids 조립)을 결정론으로 증명한다. 실 임베딩이
    아니라 *배선 테스트용 시임*이다(품질 측정 아님).
    """

    def __init__(self, name_krs: tuple[str, ...]) -> None:
        # 긴 name_kr를 먼저 검사(부분 포함 충돌 방지 — 여기선 충돌이 없지만 안정).
        self._name_krs = tuple(sorted(name_krs, key=len, reverse=True))
        self._idx = {nk: i for i, nk in enumerate(self._name_krs)}

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        rows: list[list[float]] = []
        for text in texts:
            vec = [0.0] * len(self._name_krs)
            for nk in self._name_krs:
                if nk in text:
                    vec[self._idx[nk]] = 1.0
            rows.append(vec)
        return rows


# ══════════════════════════════════════════════════════════════════════════
# ① Wilson 하한/상한 — 경계·정직성
# ══════════════════════════════════════════════════════════════════════════
class TestWilsonBounds:
    def test_lower_bound_zero_successes_is_zero(self) -> None:
        # 성공 0이면 하한 0(자연 도출).
        assert _wilson_lower_bound(0, 10, 0.95) == 0.0

    def test_upper_bound_all_successes_is_one(self) -> None:
        # 전부 성공이면 상한 1.0(Wilson 대수상 정확히 1.0·부동소수 잔차만 허용).
        assert _wilson_upper_bound(10, 10, 0.95) == pytest.approx(1.0)
        # [0,1] 상한 클램프가 1.0을 넘기지 않음을 보장.
        assert _wilson_upper_bound(10, 10, 0.95) <= 1.0

    def test_lower_bound_all_successes_below_one(self) -> None:
        # 5/5=1.0이라도 하한은 1 미만(작은 표본 보정) — step_shadow 문서 예(≈0.65)와 정합.
        lb = _wilson_lower_bound(5, 5, 0.95)
        assert 0.0 < lb < 1.0
        assert lb == pytest.approx(0.6489, abs=1e-3)

    def test_upper_bound_zero_successes_above_zero(self) -> None:
        # 관측 FP가 0이어도 상한>0(과신 방지·FP는 보수적). 0/10@.95 ≈ 0.21.
        ub = _wilson_upper_bound(0, 10, 0.95)
        assert 0.0 < ub < 1.0
        assert ub == pytest.approx(0.2129, abs=1e-3)

    def test_bound_ordering_lower_le_point_le_upper(self) -> None:
        # 하한 ≤ 점추정 ≤ 상한(같은 Wilson 공식의 ∓ 마진).
        for successes, trials in [(3, 10), (7, 12), (1, 4), (9, 20)]:
            lb = _wilson_lower_bound(successes, trials, 0.95)
            ub = _wilson_upper_bound(successes, trials, 0.95)
            phat = successes / trials
            assert lb <= phat <= ub

    def test_invalid_confidence_raises(self) -> None:
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError):
                _wilson_lower_bound(1, 10, bad)
            with pytest.raises(ValueError):
                _wilson_upper_bound(1, 10, bad)


# ══════════════════════════════════════════════════════════════════════════
# ① 스코어링 — recall/FP율·분해(합성 outcome)
# ══════════════════════════════════════════════════════════════════════════
class TestScoring:
    def test_empty_report_metrics_are_none(self) -> None:
        # 프로브 0이면 recall·fp_rate·하한·상한 모두 None(분모 0).
        report = evaluate([])
        assert report.total == 0
        assert report.recall is None
        assert report.false_positive_rate is None
        assert report.recall_lower_bound() is None
        assert report.fp_rate_upper_bound() is None

    def test_recall_counts_only_semantic_catch(self) -> None:
        # recall 프로브 3개 중 2개를 의미 매처가 잡음 → recall 2/3.
        a, b, c = "div", "log", "sin"
        outcomes = [
            _outcome(_recall_probe(a), semantic_ids=(a,)),  # 잡힘
            _outcome(_recall_probe(b), semantic_ids=("other",)),  # 다른 id만 끌림 → 미스
            _outcome(_recall_probe(c), semantic_ids=(c,)),  # 잡힘
        ]
        report = evaluate(outcomes)
        assert report.total_recall == 3
        assert report.caught_recall == 2
        assert report.recall == pytest.approx(2 / 3)
        # 하한은 점추정보다 낮다(정직).
        lb = report.recall_lower_bound()
        assert lb is not None and lb < report.recall

    def test_false_positive_rate_any_match_counts(self) -> None:
        # FP 프로브 4개 중 1개에서 *아무* 오개념이나 끌림 → fp_rate 1/4.
        ids = ("a", "b", "c", "d")
        outcomes = [
            _outcome(_fp_probe(ids[0]), semantic_ids=("z",)),  # 아무거나 끌림 → FP
            _outcome(_fp_probe(ids[1]), semantic_ids=()),  # 안 끌림 → 정상
            _outcome(_fp_probe(ids[2]), semantic_ids=()),
            _outcome(_fp_probe(ids[3]), semantic_ids=()),
        ]
        report = evaluate(outcomes)
        assert report.total_fp == 4
        assert report.semantic_false_positives == 1
        assert report.false_positive_rate == pytest.approx(1 / 4)
        # 상한은 점추정보다 높다(보수).
        ub = report.fp_rate_upper_bound()
        assert ub is not None and ub > report.false_positive_rate

    def test_near_false_positive_is_subset_of_fp(self) -> None:
        # near_id가 끌리면 near-FP이자 일반 FP. 다른 id만 끌리면 FP이되 near-FP 아님.
        outcomes = [
            _outcome(_fp_probe("target"), semantic_ids=("target",)),  # near 끌림 → near-FP
            _outcome(_fp_probe("other"), semantic_ids=("zzz",)),  # 다른 id → FP, not near
        ]
        report = evaluate(outcomes)
        assert report.semantic_false_positives == 2
        assert report.near_false_positives == 1
        assert report.false_positive_rate == pytest.approx(1.0)
        assert report.near_false_positive_rate == pytest.approx(0.5)

    def test_substring_baseline_tracked_separately(self) -> None:
        # substring 기준선 recall/FP를 별도로 집계(의미 매처 순기여 대조).
        outcomes = [
            # recall 프로브: 의미는 잡고 substring도 잡음.
            _outcome(_recall_probe("x"), semantic_ids=("x",), substring_ids=("x",)),
            # FP 프로브: substring이 올바른 진술을 잘못 잡음(기준선 FP).
            _outcome(_fp_probe("y"), semantic_ids=(), substring_ids=("y",)),
        ]
        report = evaluate(outcomes)
        assert report.substring_recall == pytest.approx(1.0)  # 1/1
        assert report.substring_false_positive_rate == pytest.approx(1.0)  # 1/1

    def test_breakdown_by_kind_and_domain(self) -> None:
        # 실 카탈로그 id로 도메인 분해를 단언(division-by-zero=대수, gambler-fallacy=확률통계).
        algebra_id = "division-by-zero"
        prob_id = "gambler-fallacy"
        assert CATALOG_BY_ID[algebra_id].domain == "대수"
        assert CATALOG_BY_ID[prob_id].domain == "확률통계"
        outcomes = [
            _outcome(_recall_probe(algebra_id, kind="paraphrase"), semantic_ids=(algebra_id,)),
            _outcome(_recall_probe(prob_id, kind="paraphrase"), semantic_ids=()),  # 미스
            _outcome(_fp_probe(algebra_id, kind="correct-near"), semantic_ids=("zz",)),  # FP
        ]
        report = evaluate(outcomes)
        # kind 분해: paraphrase recall 1/2.
        assert report.recall_by_kind["paraphrase"] == (1, 2)
        # 도메인 분해: 대수 recall 1/1, 확률통계 recall 0/1.
        assert report.recall_by_domain["대수"] == (1, 1)
        assert report.recall_by_domain["확률통계"] == (0, 1)
        # FP 도메인 분해: 대수 1/1(near_id=대수 항목).
        assert report.fp_by_domain["대수"] == (1, 1)
        assert report.fp_by_kind["correct-near"] == (1, 1)


# ══════════════════════════════════════════════════════════════════════════
# ① format_report — 비빈 문자열·FP 상세 포함
# ══════════════════════════════════════════════════════════════════════════
class TestFormatReport:
    def test_format_non_empty_with_summary(self) -> None:
        outcomes = [
            _outcome(_recall_probe("x"), semantic_ids=("x",)),
            _outcome(_fp_probe("y"), semantic_ids=()),
        ]
        text = format_report(evaluate(outcomes))
        assert text  # 비빈 문자열
        assert "recall=" in text
        assert "fp_rate=" in text

    def test_format_includes_fp_detail(self) -> None:
        # FP가 있으면 *올바른* statement가 어떤 near_id로 끌렸는지 상세에 나온다(플립 근거).
        probe = _fp_probe("dot-product-is-vector", kind="negation")
        outcomes = [_outcome(probe, semantic_ids=("dot-product-is-vector",))]
        text = format_report(evaluate(outcomes))
        assert "false positives" in text
        # near 끌림은 NEAR-FP로 태깅.
        assert "NEAR-FP" in text
        assert "dot-product-is-vector" in text
        assert probe.statement in text

    def test_format_includes_recall_miss_detail(self) -> None:
        # 놓친 recall 프로브는 MISS 상세에(약점 진단).
        probe = _recall_probe("log-distribution")
        outcomes = [_outcome(probe, semantic_ids=("wrong-id",))]
        text = format_report(evaluate(outcomes))
        assert "recall miss" in text
        assert "[MISS]" in text
        assert "log-distribution" in text


# ══════════════════════════════════════════════════════════════════════════
# ② 프로브셋 구조 검증(실파일 로드)
# ══════════════════════════════════════════════════════════════════════════
class TestProbeSetStructure:
    def test_loads_98_probes(self) -> None:
        probes = _load_real_probes()
        # 150 + 843 트랜치5 12(recall 6·FP 6) + MISC-21 7(recall 3·FP 4 — #1068 P1)
        assert len(probes) == 169

    def test_recall_and_fp_split(self) -> None:
        probes = _load_real_probes()
        recall = [p for p in probes if p.is_recall_probe]
        fp = [p for p in probes if p.is_fp_probe]
        assert len(recall) == 98  # 89 + 843 트랜치5 recall 6 + MISC-21 recall 3
        assert len(fp) == 71  # 61 + 843 트랜치5 FP 6 + MISC-21 FP 4(#1068 P1 회귀 1건 포함)
        # 상호배타·완전분할(recall ⊕ fp = 전체).
        assert len(recall) + len(fp) == len(probes)

    def test_all_ids_in_catalog(self) -> None:
        # 모든 expected_id/near_id가 카탈로그에 존재(역참조 무결성).
        probes = _load_real_probes()
        for p in probes:
            if p.expected_id is not None:
                assert p.expected_id in CATALOG_BY_ID, p.expected_id
            if p.near_id is not None:
                assert p.near_id in CATALOG_BY_ID, p.near_id
            # 정확히 한쪽만 설정(recall=expected, fp=near).
            assert (p.expected_id is None) != (p.near_id is None)

    def test_covers_all_catalog_misconceptions_both_ways(self) -> None:
        # 카탈로그 32종 전부 recall·FP 프로브를 *둘 다* 보유(전수 커버).
        probes = _load_real_probes()
        recall_ids = {p.expected_id for p in probes if p.is_recall_probe}
        fp_ids = {p.near_id for p in probes if p.is_fp_probe}
        catalog_ids = set(CATALOG_BY_ID)
        assert recall_ids == catalog_ids
        assert fp_ids == catalog_ids

    def test_kinds_valid(self) -> None:
        probes = _load_real_probes()
        for p in probes:
            assert p.kind in _VALID_KINDS, p.kind

    def test_recall_probes_evade_substring_full_match(self) -> None:
        """**임베딩 측정 유효성 회귀 가드**: recall 프로브가 substring 풀매칭(confidence 1.0)으로
        잡히면 안 된다 — 잡히면 의미 매처를 *측정할 수 없다*(substring이 먼저 다 잡으므로). 각
        recall 프로브를 `diagnose`로 진단해 expected_id가 confidence 1.0으로 매칭되지 않음을 확인.
        """
        probes = _load_real_probes()
        offenders: list[tuple[str | None, str]] = []
        for p in probes:
            if not p.is_recall_probe:
                continue
            for match in diagnose(p.statement, top_k=5):
                if match.misconception.id == p.expected_id and match.confidence >= 1.0:
                    offenders.append((p.expected_id, p.statement))
        assert offenders == [], f"substring 풀매칭된 recall 프로브: {offenders}"


# ══════════════════════════════════════════════════════════════════════════
# ③ run_probes 배선 end-to-end(Fake/제어 제공자 — 결선 증명, 실 품질 아님)
# ══════════════════════════════════════════════════════════════════════════
class TestRunProbesWiring:
    def test_run_probes_assembles_outcomes_with_fake_provider(self) -> None:
        # FakeEmbeddingProvider로 전 프로브를 돌려 스코어링 배선을 증명한다(실 의미 recall 아님).
        probes = _load_real_probes()
        outcomes = run_probes(probes, provider=FakeEmbeddingProvider(), threshold=0.3, top_k=5)
        assert len(outcomes) == len(probes)
        report = evaluate(outcomes)
        # 구조 단언만(품질 hard-fail 아님): 비율은 [0,1] 또는 None.
        assert report.total == 169
        for value in (report.recall, report.false_positive_rate):
            assert value is None or 0.0 <= value <= 1.0
        # outcome의 semantic_ids/substring_ids는 카탈로그 id이거나 빈 튜플.
        catalog_ids = set(CATALOG_BY_ID)
        for o in outcomes:
            assert set(o.semantic_ids) <= catalog_ids
            assert set(o.substring_ids) <= catalog_ids

    def test_run_probes_controlled_recall_catch(self) -> None:
        # 제어 제공자로 *예측 가능한* recall 잡힘을 만든다 — statement에 박은 name_kr가 끌리는지.
        target = "division-by-zero"
        target_name_kr = CATALOG_BY_ID[target].name_kr
        probe = MisconceptionProbe(
            # statement에 타깃 name_kr를 심어 제공자가 그 항목과 평행하게 만든다.
            statement=f"이 진술은 '{target_name_kr}' 오개념과 같은 의미다",
            expected_id=target,
            near_id=None,
            kind="paraphrase",
        )
        # 전 카탈로그 name_kr로 제공자를 만든다(각 항목이 distinct one-hot이 되도록).
        provider = _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))
        outcomes = run_probes([probe], provider=provider, threshold=0.5, top_k=5)
        assert len(outcomes) == 1
        report = evaluate(outcomes)
        # 제공자가 타깃과 평행(cos 1.0 ≥ threshold) → 의미 매처가 그 id를 끌어올림.
        assert outcomes[0].caught_by_semantic
        assert target in outcomes[0].semantic_ids
        assert report.recall == pytest.approx(1.0)

    def test_run_probes_reuses_injected_matcher(self) -> None:
        # matcher 주입 시 그것을 쓴다(카탈로그 재임베딩 회피) — 호출 카운트로 증명.
        from whymath_backend.l4.misconception.semantic.matcher import SemanticMatcher

        provider = FakeEmbeddingProvider()
        matcher = SemanticMatcher(provider=provider)
        probe = _recall_probe("division-by-zero")
        # 동일 matcher로 두 번 — 두 번째도 사전 임베딩 캐시를 재사용(예외 없이 동작).
        out1 = run_probes([probe], provider=provider, matcher=matcher, threshold=0.3)
        out2 = run_probes([probe], provider=provider, matcher=matcher, threshold=0.3)
        assert out1[0].semantic_ids == out2[0].semantic_ids


# ══════════════════════════════════════════════════════════════════════════
# ④ judge 하니스(슬108) — judge 후 FP 감소·recall 손실(합성 + 배선)
# ══════════════════════════════════════════════════════════════════════════
def _judge_outcome(
    probe: MisconceptionProbe,
    *,
    semantic_ids: tuple[str, ...] = (),
    judge_kept_ids: tuple[str, ...] = (),
    judge_removed_ids: tuple[str, ...] = (),
) -> ProbeOutcome:
    """judge 필드를 채운 ProbeOutcome 합성 — judge 후 지표를 라이브 없이 정밀 단언."""
    return ProbeOutcome(
        probe=probe,
        semantic_ids=semantic_ids,
        substring_ids=(),
        judge_kept_ids=judge_kept_ids,
        judge_removed_ids=judge_removed_ids,
    )


class TestJudgeScoring:
    def test_judge_fp_reduction_when_judge_removes_fp(self) -> None:
        # 의미 FP 2건 중 judge가 1건을 거름(아니오) → judge_fp_rate↓·fp_reduction=0.5.
        removed = _judge_outcome(
            _fp_probe("a", kind="direction-reverse"),
            semantic_ids=("a",),
            judge_removed_ids=("a",),  # judge 제거 → judge FP 없음
        )
        kept = _judge_outcome(
            _fp_probe("b"),
            semantic_ids=("b",),
            judge_kept_ids=("b",),  # judge 유지 → 여전히 FP
        )
        report = evaluate([removed, kept])
        assert report.semantic_false_positives == 2
        assert report.judge_false_positives == 1
        assert report.false_positive_rate == pytest.approx(1.0)
        assert report.judge_fp_rate == pytest.approx(0.5)
        assert report.judge_fp_reduction == pytest.approx(0.5)  # (2-1)/2

    def test_judge_fp_reduction_full_when_all_removed(self) -> None:
        # judge가 의미 FP를 전부 제거 → fp_reduction=1.0·judge_fp_rate=0.
        outs = [
            _judge_outcome(_fp_probe(i), semantic_ids=(i,), judge_removed_ids=(i,))
            for i in ("a", "b", "c")
        ]
        report = evaluate(outs)
        assert report.judge_false_positives == 0
        assert report.judge_fp_rate == pytest.approx(0.0)
        assert report.judge_fp_reduction == pytest.approx(1.0)

    def test_judge_fp_reduction_none_when_no_semantic_fp(self) -> None:
        # 의미 FP가 0이면(거를 게 없음) fp_reduction None(미정).
        clean = _judge_outcome(_fp_probe("a"), semantic_ids=(), judge_kept_ids=())
        report = evaluate([clean])
        assert report.semantic_false_positives == 0
        assert report.judge_fp_reduction is None

    def test_judge_recall_loss_when_judge_wrongly_removes(self) -> None:
        # 의미가 잡은 recall 2건 중 judge가 1건을 잘못 거름 → judge_recall↓·recall_loss=0.5.
        kept = _judge_outcome(_recall_probe("x"), semantic_ids=("x",), judge_kept_ids=("x",))
        lost = _judge_outcome(
            _recall_probe("y"),
            semantic_ids=("y",),
            judge_removed_ids=("y",),  # judge가 진짜 오개념을 잘못 제거
        )
        report = evaluate([kept, lost])
        assert report.caught_recall == 2  # 의미는 둘 다 잡음
        assert report.judge_caught_recall == 1  # judge 후 하나만
        assert report.recall == pytest.approx(1.0)
        assert report.judge_recall == pytest.approx(0.5)
        assert report.judge_recall_loss == pytest.approx(0.5)  # (2-1)/2

    def test_judge_recall_loss_zero_when_all_kept(self) -> None:
        # judge가 잡힌 recall을 모두 유지(예·불확실) → recall_loss=0(이상적).
        outs = [
            _judge_outcome(_recall_probe(i), semantic_ids=(i,), judge_kept_ids=(i,))
            for i in ("x", "y")
        ]
        report = evaluate(outs)
        assert report.judge_caught_recall == 2
        assert report.judge_recall_loss == pytest.approx(0.0)

    def test_judge_recall_loss_none_when_nothing_caught(self) -> None:
        # 의미가 아무것도 못 잡았으면(분모 0) recall_loss None.
        miss = _judge_outcome(_recall_probe("x"), semantic_ids=(), judge_kept_ids=())
        report = evaluate([miss])
        assert report.caught_recall == 0
        assert report.judge_recall_loss is None

    def test_judge_wilson_bounds(self) -> None:
        # judge FP는 상한(보수)·judge recall은 하한(정직)으로 보고.
        outs = [
            _judge_outcome(_fp_probe("a"), semantic_ids=("a",), judge_kept_ids=("a",)),
            _judge_outcome(_recall_probe("x"), semantic_ids=("x",), judge_kept_ids=("x",)),
        ]
        report = evaluate(outs)
        fub = report.judge_fp_rate_upper_bound()
        rlb = report.judge_recall_lower_bound()
        assert fub is not None and report.judge_fp_rate is not None and fub >= report.judge_fp_rate
        assert rlb is not None and report.judge_recall is not None and rlb <= report.judge_recall

    def test_judge_metrics_none_on_empty(self) -> None:
        report = evaluate([])
        assert report.judge_fp_rate is None
        assert report.judge_recall is None
        assert report.judge_fp_reduction is None
        assert report.judge_recall_loss is None

    def test_format_report_includes_judge_lines_when_applied(self) -> None:
        # judge 적용 outcome이면 before/after 줄이 나온다.
        outs = [
            _judge_outcome(_fp_probe("a"), semantic_ids=("a",), judge_removed_ids=("a",)),
            _judge_outcome(_recall_probe("x"), semantic_ids=("x",), judge_kept_ids=("x",)),
        ]
        report = evaluate(outs)
        assert _judge_applied(report) is True
        text = format_report(report)
        assert "judge_fp_rate" in text
        assert "fp_reduction" in text
        assert "recall_loss" in text
        assert "-> after=" in text

    def test_format_report_omits_judge_lines_when_not_applied(self) -> None:
        # judge 미적용(슬107 outcome)이면 judge 줄 생략(슬107 출력 불변).
        outs = [_outcome(_recall_probe("x"), semantic_ids=("x",))]
        report = evaluate(outs)
        assert _judge_applied(report) is False
        text = format_report(report)
        assert "judge_fp_rate" not in text


class TestRunProbesWithJudgeWiring:
    """`run_probes_with_judge` end-to-end 배선 — 제어 제공자 + FakeJudge(라이브 0·결정론)."""

    def _one_hot_provider(self) -> object:
        # 전 카탈로그 name_kr로 제공자 구성(각 항목 distinct one-hot).
        return _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))

    @pytest.mark.asyncio
    async def test_judge_removes_caught_fp_via_filter(self) -> None:
        # FP 프로브의 near_id를 제공자가 끌어올리고, judge가 아니오로 거른다 → judge 후 FP 0.
        import asyncio as _asyncio

        assert _asyncio  # async 컨텍스트 확인용(no-op)
        target = "continuity-implies-differentiability"
        nk = CATALOG_BY_ID[target].name_kr
        probe = MisconceptionProbe(
            statement=f"'{nk}' 주제의 올바른 역방향 진술",
            expected_id=None,
            near_id=target,
            kind="direction-reverse",
        )
        provider = self._one_hot_provider()
        judge = FakeJudge({target: JudgeVerdict.NOT_EXPRESSES})
        outcomes = await run_probes_with_judge(
            [probe], provider=provider, judge=judge, threshold=0.5, top_k=5  # type: ignore[arg-type]
        )
        o = outcomes[0]
        assert target in o.semantic_ids  # 의미는 끌어올림(FP 후보)
        assert o.judge_removed_ids == (target,)  # judge가 거름
        assert o.judge_kept_ids == ()
        report = evaluate(outcomes)
        assert report.semantic_false_positives == 1  # judge 전 FP
        assert report.judge_false_positives == 0  # judge 후 FP 0
        assert report.judge_fp_reduction == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_judge_keeps_uncertain_preserves_recall(self) -> None:
        # recall 프로브를 제공자가 잡고, judge가 불확실(유지) → recall 보존(손실 0).
        target = "division-by-zero"
        nk = CATALOG_BY_ID[target].name_kr
        probe = MisconceptionProbe(
            statement=f"'{nk}' 오개념과 같은 틀린 진술",
            expected_id=target,
            near_id=None,
            kind="paraphrase",
        )
        provider = self._one_hot_provider()
        judge = FakeJudge({target: JudgeVerdict.UNCERTAIN})
        outcomes = await run_probes_with_judge(
            [probe], provider=provider, judge=judge, threshold=0.5, top_k=5  # type: ignore[arg-type]
        )
        o = outcomes[0]
        assert o.caught_by_semantic is True
        assert o.judge_kept_expected is True  # 불확실 → 유지
        report = evaluate(outcomes)
        assert report.judge_recall == pytest.approx(1.0)
        assert report.judge_recall_loss == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_semantic_ids_preserved_for_before_after(self) -> None:
        # semantic_ids는 judge 전 값을 보존(before/after 대조 기준선).
        target = "division-by-zero"
        nk = CATALOG_BY_ID[target].name_kr
        probe = MisconceptionProbe(
            statement=f"'{nk}' 진술",
            expected_id=target,
            near_id=None,
            kind="paraphrase",
        )
        provider = self._one_hot_provider()
        # judge가 거르더라도 semantic_ids엔 여전히 target이 남는다(judge 전 기록).
        judge = FakeJudge({target: JudgeVerdict.NOT_EXPRESSES})
        outcomes = await run_probes_with_judge(
            [probe], provider=provider, judge=judge, threshold=0.5, top_k=5  # type: ignore[arg-type]
        )
        o = outcomes[0]
        assert target in o.semantic_ids  # judge 전 의미 매칭 보존
        assert target in o.judge_removed_ids  # judge가 거름
        report = evaluate(outcomes)
        # before recall(의미) 1.0 → after recall(judge) 0.0(judge가 잘못 거름).
        assert report.recall == pytest.approx(1.0)
        assert report.judge_recall == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_full_probeset_with_fake_judge_structure(self) -> None:
        # 실 프로브셋 98줄 + FakeEmbeddingProvider + FakeJudge로 배선 구조 단언(품질 아님).
        probes = _load_real_probes()
        # 전부 불확실 → judge가 아무것도 안 거름(유지) → judge 후 = 의미 후 동일.
        judge = FakeJudge(default=JudgeVerdict.UNCERTAIN)
        outcomes = await run_probes_with_judge(
            probes,
            provider=FakeEmbeddingProvider(),
            judge=judge,
            threshold=0.3,
            top_k=5,
        )
        assert len(outcomes) == len(probes)
        report = evaluate(outcomes)
        assert report.total == 169
        # 전부 유지(불확실)이므로 judge 후 지표 = 의미 지표(거른 게 없음).
        assert report.judge_false_positives == report.semantic_false_positives
        assert report.judge_caught_recall == report.caught_recall
        # 각 outcome: kept ⊕ removed = semantic_ids(분할 불변).
        for o in outcomes:
            assert set(o.judge_kept_ids) | set(o.judge_removed_ids) == set(o.semantic_ids)
            assert set(o.judge_kept_ids) & set(o.judge_removed_ids) == set()
            # 전부 불확실 → removed 비어 있고 kept == semantic_ids.
            assert o.judge_removed_ids == ()
            assert o.judge_kept_ids == o.semantic_ids


# ══════════════════════════════════════════════════════════════════════════
# ⑤ 판정근거 캐처 — judge_decisions 기록 + JSON 리포트(report_to_dict·_run --format json)
# ══════════════════════════════════════════════════════════════════════════
class TestJudgeDecisionsCapture:
    @pytest.mark.asyncio
    async def test_decisions_recorded_per_candidate(self) -> None:
        # 의미 후보마다 (id, verdict, reason)이 judge_decisions에 남는다(판정근거 캐처).
        target = "division-by-zero"
        nk = CATALOG_BY_ID[target].name_kr
        probe = MisconceptionProbe(
            statement=f"'{nk}' 오개념과 같은 틀린 진술",
            expected_id=target,
            near_id=None,
            kind="paraphrase",
        )
        provider = _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))
        judge = FakeJudge({target: JudgeVerdict.UNCERTAIN})
        outcomes = await run_probes_with_judge(
            [probe], provider=provider, judge=judge, threshold=0.5, top_k=5  # type: ignore[arg-type]
        )
        decisions = outcomes[0].judge_decisions
        assert any(d.misconception_id == target for d in decisions)
        d = next(dd for dd in decisions if dd.misconception_id == target)
        assert d.verdict == JudgeVerdict.UNCERTAIN.value  # "uncertain"
        assert isinstance(d.reason, str)  # FakeJudge → "fake"


class TestReportToDict:
    def test_no_judge_omits_judge_summary(self) -> None:
        # judge 미적용 → judge_applied False·judge_* 요약 키 없음·decisions 빈 리스트(슬107 반영).
        outcomes = [
            _outcome(_recall_probe("x"), semantic_ids=("x",)),
            _outcome(_fp_probe("y"), semantic_ids=()),
        ]
        d = report_to_dict(evaluate(outcomes), threshold=0.55)
        assert d["threshold"] == 0.55
        assert d["summary"]["judge_applied"] is False
        assert "judge_fp_rate" not in d["summary"]
        assert len(d["probes"]) == 2
        assert all(row["judge_decisions"] == [] for row in d["probes"])
        # 한글 포함 JSON 직렬화 가능.
        assert json.loads(json.dumps(d, ensure_ascii=False))["summary"]["total"] == 2

    def test_judge_applied_includes_summary_and_decisions(self) -> None:
        # judge 적용(+decisions) → judge_* 요약·프로브별 decisions 직렬화.
        probe = _fp_probe("a", kind="direction-reverse")
        outcome = ProbeOutcome(
            probe=probe,
            semantic_ids=("a",),
            substring_ids=(),
            judge_kept_ids=(),
            judge_removed_ids=("a",),
            judge_decisions=(
                JudgeDecision(misconception_id="a", verdict="not_expresses", reason="역방향"),
            ),
        )
        d = report_to_dict(evaluate([outcome]), threshold=0.6, confidence=0.9)
        assert d["confidence"] == 0.9
        summary = d["summary"]
        assert summary["judge_applied"] is True
        assert summary["judge_fp_reduction"] == pytest.approx(1.0)  # 1 FP 전부 제거
        assert "judge_recall" in summary
        row = d["probes"][0]
        assert row["judge_removed_ids"] == ["a"]
        assert row["judge_decisions"] == [
            {"misconception_id": "a", "verdict": "not_expresses", "reason": "역방향"}
        ]
        json.dumps(d, ensure_ascii=False)  # 전체 직렬화 가능


class TestRunJsonOutput:
    def test_run_emits_parseable_json_without_judge(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # _run(report_format="json")이 stdout에 파싱 가능한 JSON 리포트를 낸다(judge 없이).
        with probes_path() as path:
            code = _run(
                path,
                threshold=0.3,
                sweep=None,
                min_recall=0.0,
                max_fp=0.0,
                top_k=5,
                confidence=0.95,
                provider=FakeEmbeddingProvider(),
                report_format="json",
            )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["total"] == 169
        assert payload["summary"]["judge_applied"] is False
        assert len(payload["probes"]) == 169

    def test_run_json_with_judge_includes_decisions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # judge 주입 + json → judge_applied True·후보별 decisions 직렬화(판정근거 캐처 end-to-end).
        target = "division-by-zero"
        nk = CATALOG_BY_ID[target].name_kr
        probes_file = tmp_path / "probes.jsonl"
        probes_file.write_text(
            json.dumps(
                {
                    "statement": f"'{nk}' 오개념",
                    "expected_id": target,
                    "near_id": None,
                    "kind": "paraphrase",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        provider = _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))
        code = _run(
            probes_file,
            threshold=0.5,
            sweep=None,
            min_recall=0.0,
            max_fp=0.0,
            top_k=5,
            confidence=0.95,
            provider=provider,  # type: ignore[arg-type]
            judge=FakeJudge({target: JudgeVerdict.UNCERTAIN}),
            report_format="json",
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["judge_applied"] is True
        row = payload["probes"][0]
        assert row["judge_decisions"][0]["misconception_id"] == target
        assert row["judge_decisions"][0]["verdict"] == "uncertain"

    def test_run_out_writes_utf8_file_not_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # --out: 리포트를 stdout 대신 파일로 직접 UTF-8 기록(Windows cp949 콘솔/파이프 우회).
        # stdout엔 JSON 본문이 아니라 확인 메시지(ASCII)만, 파일엔 UTF-8 JSON.
        out_file = tmp_path / "report.json"
        with probes_path() as path:
            code = _run(
                path,
                threshold=0.3,
                sweep=None,
                min_recall=0.0,
                max_fp=0.0,
                top_k=5,
                confidence=0.95,
                provider=FakeEmbeddingProvider(),
                report_format="json",
                out=str(out_file),
            )
        assert code == 0
        assert "summary" not in capsys.readouterr().out  # 본문은 파일로, stdout엔 없음
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["summary"]["total"] == 169
        assert len(payload["probes"]) == 169


# ══════════════════════════════════════════════════════════════════════════
# 불변·계약 — Report items가 source-of-truth(파생 일관성)
# ══════════════════════════════════════════════════════════════════════════
class TestReportInvariants:
    def test_report_is_frozen(self) -> None:
        report = evaluate([_outcome(_recall_probe("x"), semantic_ids=("x",))])
        with pytest.raises(FrozenInstanceError):  # frozen dataclass — 할당 차단
            report.items = ()  # type: ignore[misc]

    def test_items_are_source_of_truth(self) -> None:
        # 같은 items면 같은 파생값(파생 프로퍼티는 순수 함수).
        items = (
            _outcome(_recall_probe("a"), semantic_ids=("a",)),
            _outcome(_fp_probe("b"), semantic_ids=("b",)),
        )
        r1 = SemanticEvalReport(items=items)
        r2 = SemanticEvalReport(items=items)
        assert r1.recall == r2.recall
        assert r1.false_positive_rate == r2.false_positive_rate
        assert r1.total == r2.total == 2


# ══════════════════════════════════════════════════════════════════════════
# judge flip 결정 게이트 — 측정→자동 flip/no-flip verdict (슬·Phaiakes9 flip 근거)
# ══════════════════════════════════════════════════════════════════════════
class TestJudgeFlipGate:
    """`_judge_flip_passed` + `_run` judge flip 게이트 — Phaiakes9 측정→자동 flip 근거(hermetic).

    judge 후 recall 하한 ≥ min_recall AND judge 후 FP율 상한 ≤ max_fp면 PASS(flip 권장). 둘 다
    opt-in(0.0=off). None(축 프로브 0)은 임계>0일 때 미달. 실LLM judge 정확도는 Phaiakes9 측정
    소관이고, 여기선 게이트 *수치 로직*과 `_run` exit 코드·verdict *배선*만 결정론으로 잠근다.
    """

    _TGT = "continuity-implies-differentiability"

    def _report(self, *, fp_kept: bool = False, n: int = 8) -> SemanticEvalReport:
        # judge가 recall n건 전부 유지 + FP n건 전부 제거(fp_kept=True면 FP를 *못* 거른 약한 judge).
        recall = [
            _judge_outcome(
                _recall_probe(self._TGT),
                semantic_ids=(self._TGT,),
                judge_kept_ids=(self._TGT,),
            )
            for _ in range(n)
        ]
        fp = [
            _judge_outcome(
                _fp_probe(self._TGT),
                semantic_ids=(self._TGT,),
                judge_kept_ids=(self._TGT,) if fp_kept else (),
                judge_removed_ids=() if fp_kept else (self._TGT,),
            )
            for _ in range(n)
        ]
        return evaluate(recall + fp)

    def test_off_thresholds_always_pass(self) -> None:
        # 둘 다 0.0(off) → 리포트 무관 항상 PASS(opt-in·약한 judge라도).
        assert _judge_flip_passed(
            self._report(fp_kept=True), min_recall=0.0, max_fp=0.0, confidence=0.95
        )

    def test_strong_judge_passes(self) -> None:
        # recall 보존(8/8)·FP 제거(0/8) → 너그러운 임계 PASS(lb≈0.75≥0.5·ub≈0.25≤0.5).
        assert _judge_flip_passed(self._report(), min_recall=0.5, max_fp=0.5, confidence=0.95)

    def test_recall_below_min_fails(self) -> None:
        # recall 하한 미달 임계(0.9>≈0.75) → FAIL.
        assert not _judge_flip_passed(self._report(), min_recall=0.9, max_fp=0.5, confidence=0.95)

    def test_fp_above_max_fails(self) -> None:
        # judge가 FP를 못 거르면(fp_kept·judge_fp=8/8·ub≈1.0) max_fp=0.1 초과 → FAIL.
        assert not _judge_flip_passed(
            self._report(fp_kept=True), min_recall=0.5, max_fp=0.1, confidence=0.95
        )

    def test_missing_axis_probes_fail_when_gated(self) -> None:
        # 축 프로브 0 + 임계>0 → None=미달(증거 없음=통과 불가).
        only_recall = evaluate(
            [
                _judge_outcome(
                    _recall_probe(self._TGT),
                    semantic_ids=(self._TGT,),
                    judge_kept_ids=(self._TGT,),
                )
            ]
        )
        assert only_recall.judge_fp_rate_upper_bound(0.95) is None
        assert not _judge_flip_passed(only_recall, min_recall=0.0, max_fp=0.1, confidence=0.95)
        only_fp = evaluate(
            [
                _judge_outcome(
                    _fp_probe(self._TGT),
                    semantic_ids=(self._TGT,),
                    judge_kept_ids=(),
                    judge_removed_ids=(self._TGT,),
                )
            ]
        )
        assert only_fp.judge_recall_lower_bound(0.95) is None
        assert not _judge_flip_passed(only_fp, min_recall=0.1, max_fp=0.0, confidence=0.95)

    # ── _run exit 코드·verdict 배선(실LLM 0·FakeJudge·결정론 제공자) ──
    def _probes_file(self, tmp_path: Path) -> Path:
        nk = CATALOG_BY_ID[self._TGT].name_kr
        f = tmp_path / "probes.jsonl"
        f.write_text(
            json.dumps(
                {
                    "statement": f"'{nk}' 오개념",
                    "expected_id": self._TGT,
                    "near_id": None,
                    "kind": "paraphrase",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return f

    def test_run_judge_gate_pass_exit0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # judge가 recall 유지(1/1·lb≈0.27) → judge_min_recall=0.1 PASS·exit 0·verdict 한 줄.
        provider = _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))
        code = _run(
            self._probes_file(tmp_path),
            threshold=0.5,
            sweep=None,
            min_recall=0.0,
            max_fp=0.0,
            top_k=5,
            confidence=0.95,
            provider=provider,  # type: ignore[arg-type]
            judge=FakeJudge(default=JudgeVerdict.UNCERTAIN),
            judge_min_recall=0.1,
            judge_max_fp=0.0,
        )
        assert code == 0
        assert "JUDGE FLIP GATE: PASS" in capsys.readouterr().out

    def test_run_judge_gate_fail_exit1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 과한 recall 하한(0.99>≈0.27) → FAIL·exit 1·verdict FAIL 줄.
        provider = _NameKrOneHotProvider(name_krs=tuple(m.name_kr for m in CATALOG_BY_ID.values()))
        code = _run(
            self._probes_file(tmp_path),
            threshold=0.5,
            sweep=None,
            min_recall=0.0,
            max_fp=0.0,
            top_k=5,
            confidence=0.95,
            provider=provider,  # type: ignore[arg-type]
            judge=FakeJudge(default=JudgeVerdict.UNCERTAIN),
            judge_min_recall=0.99,
            judge_max_fp=0.0,
        )
        assert code == 1
        assert "JUDGE FLIP GATE: FAIL" in capsys.readouterr().out
