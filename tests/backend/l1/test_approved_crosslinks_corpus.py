"""승인 crosswalk 코퍼스 거버넌스 — Kiki 검수 승인분의 무결성·게이트·해석 동결.

`data/corpus/misconception_crosslinks_v1/crosslinks.json`은 검수 큐(전행 pending) 중 **Kiki가
직접 승인한 매핑**을 promote 산출(로더 형식)해 커밋한 것이다(사람 사인오프·AI 자기승인 아님).
2026-07-08 극값 2(M0864·M0865)·2026-07-10 트리아지 A 11 + B 8 + frac 1·2026-07-12 미매핑 Tier C
Tier C 10 + period + root-loss + 843 트랜치1~5 각 6(신규 탐지 kebab·계산형)을 승인해
**총 64건(탐지 카탈로그 64 전수 매핑)**이었고, 2026-10-03 MISC-21·MISC-40 서명 5건이 더해져 **69건**이다. 이 테스트는 hermetic(DB 0)으로 봉인한다:
① 로더 형식·게이트 통과(method=manual·검수 서명) ② kebab∈탐지 카탈로그·M-id∈843 코퍼스(참조 무결성)
③ `select_canonical`이 각 kebab에 canonical M-id를 실제로 돌려줌(단절 해소·843→34 도달).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.l1.misconception.crosslink_gate import (
    LOADABLE_METHOD,
    is_signed,
    load_gate_violations,
)
from whymath_backend.l1.misconception.crosslink_resolve import (
    ResolvedLink,
    select_canonical,
)
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CROSSLINKS = _REPO_ROOT / "data" / "corpus" / "misconception_crosslinks_v1" / "crosslinks.json"
_MISCONCEPTIONS = _REPO_ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"

# Kiki 승인분(MEMORY 정본·극값 2·A/B/frac 20·Tier C 10·period·root-loss·843 트랜치1~5 각 6)
# — 탐지 카탈로그 64 전수 매핑·기대 매핑 동결.
_EXPECTED: dict[str, str] = {
    "extremum-max-min-confused": "M0864",
    "extremum-value-vs-point-confused": "M0865",
    "continuity-implies-differentiability": "M0670",
    "sine-distributes-over-sum": "M0707",
    "composite-function-commutes": "M0643",
    "discriminant-negative-no-real-root": "M0610",
    "limit-equals-function-value": "M0665",
    "term-to-zero-implies-convergence": "M0704",
    "factor-sign-flip": "M0863",
    "distribution-over-power": "M0019",
    "critical-point-implies-extremum": "M0080",
    "product-rule-naive": "M0075",
    "log-distribution": "M0049",
    "area-perimeter-confusion": "M0529",
    "geometric-series-always-converges": "M0209",
    "invertibility-without-1-1": "M0144",
    "opposite-root-selected": "M0862",
    "exponent-zero": "M0105",
    "circle-radius-squared": "M0848",
    "square-root-positivity": "M0550",
    "chain-rule-inner-derivative-omitted": "M0370",
    "fraction-cancellation": "M0118",
    "angle-sum-non-triangle": "M0493",
    "division-by-zero": "M0003",
    "dot-product-is-vector": "M0735",
    "gambler-fallacy": "M0688",
    "mean-vs-median": "M0419",
    "mutually-exclusive-implies-independent": "M0692",
    "prosecutor-fallacy": "M0691",
    "sign-flip-in-inequality": "M0564",
    "similarity-vs-congruence": "M0519",
    "translation-sign-flip": "M0411",
    "period-of-scaled-sine": "M0152",
    "root-loss-by-dividing": "M0573",
    "fraction-addition-naive": "M0004",
    "negative-times-negative": "M0001",
    "subtract-negative-sign": "M0002",
    "absolute-value-keeps-sign": "M0010",
    "sqrt-distributes-over-sum": "M0008",
    "difference-of-squares-confused": "M0121",
    "exponent-product-multiplies": "M0006",
    "power-of-power-adds": "M0135",
    "negative-square-precedence": "M0009",
    "distribute-first-term-only": "M0017",
    "negative-distribute-sign": "M0018",
    "square-of-difference-no-cross": "M0020",
    "midpoint-sum-only": "M0066",
    "scale-area-linear": "M0013",
    "negative-even-power-sign": "M0201",
    "combine-unlike-terms": "M0016",
    "complete-square-naive": "M0119",
    "conjugate-product-sum": "M0206",
    "transpose-no-sign-change": "M0021",
    "gcd-lcm-confused": "M0014",
    "decimal-mult-place": "M0103",
    "mixed-number-mult-whole": "M0102",
    "remainder-theorem-sign": "M0133",
    "vieta-sign-error": "M0123",
    # 843 트랜치5(비대수 도메인·기하4·확통2)
    "trapezoid-area-no-half": "M0161",
    "scale-volume-linear": "M0056",
    "cone-volume-no-third": "M0063",
    "circle-area-circumference": "M0053",
    "combination-no-denominator": "M0087",
    "same-item-permutation-no-divide": "M0190",
}


def _load_rows() -> list[MisconceptionCrosslink]:
    payload = json.loads(_CROSSLINKS.read_text(encoding="utf-8"))
    return [MisconceptionCrosslink.model_validate(r) for r in payload["crosslinks"]]


def _corpus_mis_ids() -> set[str]:
    data = json.loads(_MISCONCEPTIONS.read_text(encoding="utf-8"))
    items = data.get("misconceptions", data)
    return {m["mis_id"] for m in items if isinstance(m, dict) and "mis_id" in m}


# 2026-10-03 게이트 G-misc40-new-crosslink-signature — Kiki가 행별로 승인한 5건(MISC-21 잔여 3 +
# MISC-40 신설 1 + 기존 부분매핑 1을 직접 0.85로 승격). 위 `_EXPECTED`(kebab당 1건)와 달리
# `product-rule-naive`는 M0075(0.97)에 더해 M0672(0.85)가 붙어 kebab당 2건이 되므로 쌍 집합으로 따로 동결한다.
_MISC40_SIGNED: dict[tuple[str, str], float] = {
    ("bigger-denominator-bigger-fraction", "M0462"): 0.9,
    ("ratio-order-swapped", "M0515"): 0.85,
    ("addition-multiplication-rule-confused", "M0599"): 0.9,
    ("power-rule-step-omitted", "M0671"): 0.85,
    ("product-rule-naive", "M0672"): 0.85,
}


def test_exact_approved_pairs() -> None:
    # 승인 69건 = 기존 64건(kebab→M-id 동결) + 2026-10-03 서명 5건 — 드리프트 시 즉시 실패.
    rows = _load_rows()
    pairs = {(r.kebab_id, r.mis_id) for r in rows}
    assert len(rows) == len(pairs), "중복 행 금지"
    assert pairs == set(_EXPECTED.items()) | set(_MISC40_SIGNED)


def test_misc40_signed_rows_carry_kiki_stamp_and_confidence() -> None:
    # 서명 5건의 신뢰도·서명 stamp를 값으로 못 박는다(승격 신뢰도 0.85 등 판정 결과 동결).
    by_pair = {(r.kebab_id, r.mis_id): r for r in _load_rows()}
    for pair, conf in _MISC40_SIGNED.items():
        row = by_pair[pair]
        assert row.confidence == conf, pair
        assert row.link_type == "직접매핑", pair
        assert row.note is not None and row.note.endswith("검수:kiki 2026-10-03"), pair
    # M0671은 성취기준 원문 OCR 정합이 미확인인 채 서명됐다 — 그 사실이 note에서 지워지면 안 된다.
    ocr_note = by_pair[("power-rule-step-omitted", "M0671")].note
    assert ocr_note is not None and "원문 OCR 정합은 미확인" in ocr_note


def test_product_rule_naive_canonical_stays_m0075_after_m0672_promotion() -> None:
    # M0672(0.85)가 직접으로 붙어도 canonical은 strict 최대 신뢰도 M0075(0.97)로 유지된다 —
    # 동률이 아니므로 ambiguous도 아니다(M0672는 보조 직접 링크).
    links = [
        ResolvedLink(mis_id=r.mis_id, link_type=r.link_type, confidence=r.confidence)
        for r in _load_rows()
        if r.kebab_id == "product-rule-naive"
    ]
    assert sorted(link.mis_id for link in links) == ["M0075", "M0672"]
    sel = select_canonical(links)
    assert (sel.canonical_mis_id, sel.ambiguous, sel.reason) == ("M0075", False, "ok")


def test_load_gate_passes() -> None:
    # 로더 게이트 통과 — 전 행 method=manual·검수 서명 stamp(검수 우회·자기승인 차단 통과분).
    rows = _load_rows()
    assert load_gate_violations(rows) == []
    for r in rows:
        assert r.method == LOADABLE_METHOD
        assert is_signed(r.note)
        assert (
            r.confidence is not None and r.confidence >= 0.6
        )  # 직접매핑 승격 게이트 하한(DIRECT_MIN_CONFIDENCE)
        assert r.link_type == "직접매핑"


def test_referential_integrity() -> None:
    # kebab는 탐지 카탈로그(현 64종)·M-id는 843 콘텐츠 코퍼스에 실재(양측 dangling 0).
    rows = _load_rows()
    corpus_ids = _corpus_mis_ids()
    for r in rows:
        assert r.kebab_id in CATALOG_BY_ID
        assert r.mis_id in corpus_ids


def test_canonical_resolution_realized() -> None:
    # 단절 해소 증명 — select_canonical이 두 kebab에 canonical M-id를 실제로 돌려준다
    # (과거엔 링크 0으로 no_links·843 콘텐츠가 34 탐지에 도달 못 함).
    rows = _load_rows()
    for kebab, expected_mis in _EXPECTED.items():
        links = [
            ResolvedLink(mis_id=r.mis_id, link_type=r.link_type, confidence=r.confidence)
            for r in rows
            if r.kebab_id == kebab
        ]
        sel = select_canonical(links)
        assert sel.canonical_mis_id == expected_mis
        assert sel.ambiguous is False
        assert sel.reason == "ok"
