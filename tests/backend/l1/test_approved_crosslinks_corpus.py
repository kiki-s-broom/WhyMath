"""승인 crosswalk 코퍼스 거버넌스 — Kiki 검수 승인분의 무결성·게이트·해석 동결.

`data/corpus/misconception_crosslinks_v1/crosslinks.json`은 검수 큐(전행 pending) 중 **Kiki가
직접 승인한 매핑**을 promote 산출(로더 형식)해 커밋한 것이다(사람 사인오프·AI 자기승인 아님).
2026-07-08 극값 2(M0864·M0865)·2026-07-10 트리아지 A 11 + B 8 + frac 1·2026-07-12 미매핑 Tier C
Tier C 10 + period + root-loss + 843 트랜치1~5 각 6(신규 탐지 kebab·계산형)을 승인해
**총 64건(탐지 카탈로그 64 전수 매핑)**이었고, 2026-10-06 게이트 `G-misc40-new-crosslink-signature` 재판정으로 승인 4건(M0462·M0515·M0671·M0672)이 더해져 **68건**이다(보류 1건 M0599는 미적재). 이 테스트는 hermetic(DB 0)으로 봉인한다:
① 로더 형식·게이트 통과(method=manual·검수 서명) ② kebab∈탐지 카탈로그·M-id∈843 코퍼스(참조 무결성)
③ `select_canonical`이 각 kebab에 canonical M-id를 실제로 돌려줌(단절 해소·843→34 도달).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.l1.misconception.crosslink_gate import (
    DIRECT_LINK_TYPE,
    DIRECT_MIN_CONFIDENCE,
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


# 2026-10-06 게이트 G-misc40-new-crosslink-signature — Kiki가 5행을 재판정했다: 승인 4(M0462·M0515·M0671 직접매핑 +
# M0672 직접매핑 0.85 상향) + 보류 1(M0599). 2026-10-05 판정(M0599 승인·M0671 보류·M0672 부분매핑)을 대체한다. 위 `_EXPECTED`(kebab당 1건)와 달리 `product-rule-naive`는
# M0075(0.97)에 더해 M0672가 붙어 kebab당 2건이 되므로 쌍 집합으로 따로 동결한다. 값 = (link_type, confidence).
_MISC40_SIGNED: dict[tuple[str, str], tuple[str, float | None]] = {
    ("bigger-denominator-bigger-fraction", "M0462"): ("직접매핑", 0.9),
    ("ratio-order-swapped", "M0515"): ("직접매핑", 0.85),
    ("power-rule-step-omitted", "M0671"): ("직접매핑", 0.85),
    ("product-rule-naive", "M0672"): ("직접매핑", 0.85),
}
# 서명일 — M0462·M0515는 2026-10-05 서명 유지, 재판정으로 바뀐 M0671·M0672는 2026-10-06 재서명.
_MISC40_SIGN_DATE: dict[str, str] = {
    "M0462": "2026-10-05",
    "M0515": "2026-10-05",
    "M0671": "2026-10-06",
    "M0672": "2026-10-06",
}
# 보류(deferred)라 코퍼스에 있으면 안 되는 쌍 — 서명 없이 적재된 흔적을 막는다.
_MISC40_DEFERRED: frozenset[tuple[str, str]] = frozenset(
    {("addition-multiplication-rule-confused", "M0599")}
)


def test_exact_approved_pairs() -> None:
    # 승인 68건 = 기존 64건(kebab→M-id 동결) + 2026-10-05·06 서명 승인 4건 — 드리프트 시 즉시 실패.
    rows = _load_rows()
    pairs = {(r.kebab_id, r.mis_id) for r in rows}
    assert len(rows) == len(pairs), "중복 행 금지"
    assert pairs == set(_EXPECTED.items()) | set(_MISC40_SIGNED)


def test_misc40_signed_rows_carry_kiki_stamp_and_confidence() -> None:
    # 서명 4건의 유형·신뢰도·서명 stamp를 값으로 못 박는다(M0672는 직접매핑 0.85로 상향).
    by_pair = {(r.kebab_id, r.mis_id): r for r in _load_rows()}
    for pair, (link_type, conf) in _MISC40_SIGNED.items():
        row = by_pair[pair]
        assert row.confidence == conf, pair
        assert row.link_type == link_type, pair
        stamp = "검수:kiki " + _MISC40_SIGN_DATE[pair[1]]
        assert row.note is not None and row.note.endswith(stamp), pair
    # M0671은 성취기준 원문을 확인하고 승인했다 — 그 사실이 note에서 지워지거나 미확인으로 되돌아가면 안 된다.
    m0671_note = by_pair[("power-rule-step-omitted", "M0671")].note
    assert m0671_note is not None and "원문 확인함" in m0671_note and "미확인" not in m0671_note


def test_misc40_deferred_rows_are_not_in_the_approved_corpus() -> None:
    # M0599는 보류 판정이다 — 승인 코퍼스에 있으면 서명 없는 적재이므로 즉시 실패해야 한다.
    pairs = {(r.kebab_id, r.mis_id) for r in _load_rows()}
    assert pairs.isdisjoint(_MISC40_DEFERRED)


def test_product_rule_naive_canonical_stays_m0075_after_m0672_direct_signature() -> None:
    # M0672가 직접매핑 0.85로 붙어도 canonical은 strict 최대 신뢰도 M0075(0.97)로 유지된다 —
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
        # MISC-63 적재 자격 — 승인 코퍼스는 전 행이 직접매핑이다(부분매핑·개념겹침은 기본 적재 금지).
        assert r.link_type == DIRECT_LINK_TYPE, (r.kebab_id, r.mis_id, r.link_type)
        assert (
            r.confidence is not None and r.confidence >= DIRECT_MIN_CONFIDENCE
        )  # 직접매핑 승격 게이트 하한


def test_every_corpus_row_is_direct_mapping() -> None:
    # MISC-63 — 비직접 행이 하나라도 섞이면 전건 열거로 실패한다(스캔 0건 공허 통과 방지: 행 수도 단언).
    rows = _load_rows()
    assert len(rows) == 68
    non_direct = [
        (r.kebab_id, r.mis_id, r.link_type) for r in rows if r.link_type != DIRECT_LINK_TYPE
    ]
    assert non_direct == []


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
