"""오개념 crosswalk 검수 큐 승격(`crosslink_review`) 단위테스트 + 실 큐 파일 회귀.

합성 큐로 승격 규칙(승인만 추출·서명 필수·직접매핑 conf<0.6 금지·kebab 실재·top key 오투입
거부·전건 열거·exit 2)을 검증하고, 실 큐 파일(`docs/data/misconception_crosslink_review_queue.json`)
은 초안(`misconception_crosslink_candidates.md` §2) 전사 충실성을 회귀 가드한다 — kebab 32 전원·
M-id 실재(843 코퍼스·극값 MC 신규 저작 M0864·M0865 포함)·전행 pending·직접매핑 conf 초안 명시값
일치(전사 왜곡 방지 스팟).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_review import (
    CrosslinkReviewError,
    CrosslinkReviewItem,
    main,
    promote_approved,
)
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink

# 레포 루트 앵커 — CWD 상대 금지(테스트 실행 위치 무관·step_shadow_eval 테스트 규약).
_ROOT = Path(__file__).resolve().parents[3]
_QUEUE_PATH = _ROOT / "docs" / "data" / "misconception_crosslink_review_queue.json"
_CORPUS_PATH = _ROOT / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"


def _row(**over: Any) -> dict[str, Any]:
    """합성 큐 1행 — 기본은 실재 kebab·직접매핑·pending. over로 필드 덮어쓰기."""
    base: dict[str, Any] = {
        "kebab_id": "log-distribution",
        "mis_id": "M0049",
        "link_type": "직접매핑",
        "confidence": 0.97,
        "rationale": "테스트 근거",
        "status": "pending",
        "reviewer": None,
        "reviewed_on": None,
        "note": None,
    }
    base.update(over)
    return base


def _approved(**over: Any) -> dict[str, Any]:
    """승인 행 — 서명(reviewer·reviewed_on) 포함."""
    base = _row(status="approved", reviewer="kiki", reviewed_on="2026-07-02")
    base.update(over)
    return base


def _queue(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"review_queue": list(rows)}


# ── 승격 규칙 ──────────────────────────────────────────────────────────


def test_promote_extracts_only_approved() -> None:
    out = promote_approved(
        _queue(
            _approved(),
            _row(mis_id="M0650", link_type="부분매핑", confidence=None),  # pending
            _approved(mis_id="M0075", kebab_id="product-rule-naive", status="rejected"),
            _approved(
                mis_id="M0665",
                kebab_id="limit-equals-function-value",
                status="deferred",
            ),
        )
    )
    assert list(out) == ["crosslinks"]  # 출력 top key = 로더 입력 형식
    assert len(out["crosslinks"]) == 1
    row = out["crosslinks"][0]
    assert row["kebab_id"] == "log-distribution"
    assert row["mis_id"] == "M0049"
    assert row["method"] == "manual"  # 채택 주체 = 사람(초안 §4)
    assert "검수:kiki 2026-07-02" in row["note"]


def test_note_merges_reviewer_stamp_with_existing_note() -> None:
    out = promote_approved(_queue(_approved(note="원문 재확인 완료")))
    note = out["crosslinks"][0]["note"]
    assert "원문 재확인 완료" in note
    assert "검수:kiki 2026-07-02" in note


def test_approved_without_signature_errors() -> None:
    with pytest.raises(CrosslinkReviewError, match="검수 서명"):
        promote_approved(_queue(_approved(reviewer=None)))
    with pytest.raises(CrosslinkReviewError, match="검수 서명"):
        promote_approved(_queue(_approved(reviewed_on=None)))


def test_direct_low_confidence_approval_errors() -> None:
    # 직접매핑 & conf<0.6 승인 금지(초안 §0.2) — None도 금지.
    with pytest.raises(CrosslinkReviewError, match="0.6"):
        promote_approved(_queue(_approved(confidence=0.55)))
    with pytest.raises(CrosslinkReviewError, match="0.6"):
        promote_approved(_queue(_approved(confidence=None)))


def test_non_direct_low_confidence_approval_allowed() -> None:
    # 부분매핑/개념겹침은 conf 하한 규칙 대상이 아니다(직접 승격만 금지).
    out = promote_approved(_queue(_approved(link_type="개념겹침", confidence=0.45)))
    assert len(out["crosslinks"]) == 1


def test_unknown_kebab_errors() -> None:
    with pytest.raises(CrosslinkReviewError, match="kebab_id"):
        promote_approved(_queue(_row(kebab_id="no-such-kebab")))


def test_errors_enumerate_all_violations() -> None:
    # 위반 행 전건 열거(조용한 누락 금지) — 서명 누락 + conf 위반 + kebab 미등록 동시 보고.
    with pytest.raises(CrosslinkReviewError) as exc:
        promote_approved(
            _queue(
                _approved(reviewer=None),
                _approved(mis_id="M0075", kebab_id="product-rule-naive", confidence=0.5),
                _row(mis_id="M0650", kebab_id="no-such-kebab"),
            )
        )
    message = str(exc.value)
    assert "[행 0]" in message and "검수 서명" in message
    assert "[행 1]" in message and "0.6" in message
    assert "[행 2]" in message and "kebab_id" in message


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"candidates": []}, "candidates"),  # 후보 도구 출력 오투입
        ({"crosslinks": []}, "crosslinks"),  # 로더 입력(승격 산출물) 재투입
        ({"rows": []}, "review_queue"),  # top key 자체 부재
    ],
)
def test_wrong_top_key_rejected(payload: dict[str, Any], match: str) -> None:
    with pytest.raises(CrosslinkReviewError, match=match):
        promote_approved(payload)


def test_malformed_row_errors_with_row_index() -> None:
    with pytest.raises(CrosslinkReviewError, match=r"\[행 0\]"):
        promote_approved(_queue({"kebab_id": "log-distribution"}))  # 필수 필드 누락


def test_output_rows_satisfy_crosslink_contract() -> None:
    out = promote_approved(
        _queue(
            _approved(),
            _approved(mis_id="M0075", kebab_id="product-rule-naive", confidence=0.97),
            _approved(
                mis_id="M0152",
                kebab_id="period-of-scaled-sine",
                link_type="개념겹침",
                confidence=0.45,
            ),
        )
    )
    for row in out["crosslinks"]:
        validated = MisconceptionCrosslink.model_validate(row)  # extra=forbid 계약 통과
        assert validated.method == "manual"


# ── CLI ───────────────────────────────────────────────────────────────


def test_cli_promote_writes_out_file(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    out_path = tmp_path / "approved.json"
    queue_path.write_text(json.dumps(_queue(_approved()), ensure_ascii=False), encoding="utf-8")
    assert main(["promote", "--queue", str(queue_path), "--out", str(out_path)]) == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(written["crosslinks"]) == 1
    assert written["crosslinks"][0]["method"] == "manual"


def test_cli_zero_approved_exits_2(tmp_path: Path) -> None:
    # 승인 0건 = 조용한 무동작 금지 → exit 2, 출력 파일 미생성.
    queue_path = tmp_path / "queue.json"
    out_path = tmp_path / "approved.json"
    queue_path.write_text(json.dumps(_queue(_row()), ensure_ascii=False), encoding="utf-8")
    assert main(["promote", "--queue", str(queue_path), "--out", str(out_path)]) == 2
    assert not out_path.exists()


def test_cli_missing_queue_exits_2(tmp_path: Path) -> None:
    args = [
        "promote",
        "--queue",
        str(tmp_path / "없음.json"),
        "--out",
        str(tmp_path / "o"),
    ]
    assert main(args) == 2


def test_cli_violation_exits_1(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(_queue(_approved(reviewer=None)), ensure_ascii=False),
        encoding="utf-8",
    )
    assert main(["promote", "--queue", str(queue_path), "--out", str(tmp_path / "o.json")]) == 1


# ── 실 큐 파일 회귀 — 초안 §2 전사 충실성 가드 ─────────────────────────

# 초안 §2 직접매핑 *최상위* 명시 conf — 전사 왜곡 방지 스팟(circle-radius-squared는 병기 2건).
_DRAFT_DIRECT_TOPS: dict[str, set[tuple[str, float]]] = {
    "distribution-over-power": {("M0019", 0.95)},
    "sign-flip-in-inequality": {("M0564", 0.95)},
    "division-by-zero": {("M0003", 0.85)},
    "square-root-positivity": {("M0550", 0.95)},
    "exponent-zero": {("M0105", 0.92)},
    "fraction-cancellation": {("M0118", 0.80)},
    "log-distribution": {("M0049", 0.97)},
    "discriminant-negative-no-real-root": {("M0610", 0.95)},
    "root-loss-by-dividing": {("M0573", 0.95)},
    "angle-sum-non-triangle": {("M0493", 0.85)},
    "similarity-vs-congruence": {("M0519", 0.90)},
    "area-perimeter-confusion": {("M0529", 0.95)},
    "circle-radius-squared": {("M0630", 0.93), ("M0848", 0.93)},
    "gambler-fallacy": {("M0688", 0.98)},
    "prosecutor-fallacy": {("M0691", 0.95)},
    "mean-vs-median": {("M0419", 0.90)},
    "mutually-exclusive-implies-independent": {("M0692", 0.95)},
    "invertibility-without-1-1": {("M0144", 0.92)},
    "composite-function-commutes": {("M0643", 0.95)},
    "translation-sign-flip": {("M0411", 0.90)},
    "chain-rule-inner-derivative-omitted": {("M0370", 0.90)},
    "product-rule-naive": {("M0075", 0.97)},
    "limit-equals-function-value": {("M0665", 0.95)},
    "continuity-implies-differentiability": {("M0670", 0.97)},
    "critical-point-implies-extremum": {("M0080", 0.95)},
    "geometric-series-always-converges": {("M0209", 0.92)},
    "term-to-zero-implies-convergence": {("M0704", 0.95)},
    "sine-distributes-over-sum": {("M0707", 0.97)},
    "dot-product-is-vector": {("M0735", 0.95)},
}


@pytest.fixture(scope="module")
def real_queue() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_QUEUE_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def real_rows(real_queue: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = real_queue["review_queue"]
    return rows


def test_real_queue_format_and_schema(
    real_queue: dict[str, Any], real_rows: list[dict[str, Any]]
) -> None:
    assert real_queue["format"] == "misconception_crosslink_review_queue_v1"
    assert "misconception_crosslink_candidates.md" in real_queue["source_draft"]
    for row in real_rows:
        CrosslinkReviewItem.model_validate(row)  # 전행 스키마 통과(extra=forbid)


def test_real_queue_covers_all_30_kebabs(real_rows: list[dict[str, Any]]) -> None:
    # ① kebab 30종 전원 존재 — 초안 §0.3 "30종 전부 후보 매칭(후보 없음 0)".
    assert {r["kebab_id"] for r in real_rows} == set(CATALOG_BY_ID)


def test_real_queue_mis_ids_exist_in_corpus(real_rows: list[dict[str, Any]]) -> None:
    # ② 모든 mis_id가 실 코퍼스(843종)에 실재 — 존재하지 않는 M-id 전사 방지.
    corpus = json.loads(_CORPUS_PATH.read_text(encoding="utf-8"))
    corpus_ids = {r["mis_id"] for r in corpus["misconceptions"]}
    assert corpus_ids  # 코퍼스 자체가 비면 가드 무의미
    missing = sorted({r["mis_id"] for r in real_rows} - corpus_ids)
    assert missing == [], f"코퍼스에 없는 M-id 전사: {missing}"


def test_real_queue_all_pending_unsigned(real_rows: list[dict[str, Any]]) -> None:
    # ③ 전행 pending·서명 없음 — 사람 검수 전 상태(AI 자기승인 금지).
    for row in real_rows:
        assert row["status"] == "pending"
        assert row["reviewer"] is None
        assert row["reviewed_on"] is None


# 검수 반영(#392) 직접 대안 conf — Kiki 검수로 confidence 필드에 이전된 값(초안 전사 아님).
# 이 집합만큼만 초안 최상위(_DRAFT_DIRECT_TOPS) *외에* non-null 직접매핑이 허용된다 — 그 밖의
# 새 non-null 직접매핑은 여전히 전사 왜곡·미검수 유입으로 차단(가드 유지). M0556은 부분매핑
# 강등되어 여기 없다(직접 아님).
_REVIEWED_DIRECT_ALTS: dict[str, set[tuple[str, float]]] = {
    "distribution-over-power": {("M0572", 0.80)},
    "sign-flip-in-inequality": {("M0028", 0.90), ("M0778", 0.75)},
    "square-root-positivity": {("M0647", 0.85)},
}

# S2-p 후속 — kebab 2종의 직접 대응 M-id를 신규 저작(misconceptions_v1 M0862·M0863)해 초안 v0.3에
# 직접매핑 행으로 추가. 초안 최상위·검수 대안과 같은 화이트리스트라 그 밖의 새 직접매핑은 계속
# 차단된다. 기존 최근접 개념겹침 행(M0831/M0848)은 non-null 직접매핑이 아니라 이 집합 대상 아님.
_S2P_DIRECT: dict[str, set[tuple[str, float]]] = {
    "opposite-root-selected": {("M0862", 0.9)},
    "factor-sign-flip": {("M0863", 0.9)},
}

# 극값 MC 후속 — kebab 2종(극대극소 혼동·값↔x좌표 혼동)의 직접 대응 M-id를 신규 저작
# (misconceptions_v1 M0864·M0865)해 직접매핑 pending 행으로 추가. S2-p와 같은 화이트리스트라
# 그 밖의 새 직접매핑은 계속 차단된다. **pending 계약**: 전행 status=pending·미서명이라 이 화이트
# 리스트 등재가 승인을 의미하지 않는다(Kiki 교수학 검수 전 미승인 — test_real_queue_all_pending).
_EXTREMUM_MC_DIRECT: dict[str, set[tuple[str, float]]] = {
    "extremum-max-min-confused": {("M0864", 0.9)},
    "extremum-value-vs-point-confused": {("M0865", 0.9)},
}

# 843 확장 트랜치1 — 신규 탐지 kebab 6종(기초 계산형)의 직접 대응 M-id를 pending 후보로 추가.
# 같은 화이트리스트 계약(전행 pending·미서명·test_real_queue_all_pending). 그 밖의 새 직접매핑 차단.
_TRANCHE1_DIRECT: dict[str, set[tuple[str, float]]] = {
    "fraction-addition-naive": {("M0004", 0.95)},
    "negative-times-negative": {("M0001", 0.95)},
    "subtract-negative-sign": {("M0002", 0.95)},
    "absolute-value-keeps-sign": {("M0010", 0.95)},
    "sqrt-distributes-over-sum": {("M0008", 0.95)},
    "difference-of-squares-confused": {("M0121", 0.9)},
}

# 843 확장 트랜치2 — 거듭제곱·분배·부호 계산형 6종(같은 화이트리스트 계약·전행 pending).
_TRANCHE2_DIRECT: dict[str, set[tuple[str, float]]] = {
    "exponent-product-multiplies": {("M0006", 0.95)},
    "power-of-power-adds": {("M0135", 0.95)},
    "negative-square-precedence": {("M0009", 0.95)},
    "distribute-first-term-only": {("M0017", 0.95)},
    "negative-distribute-sign": {("M0018", 0.95)},
    "square-of-difference-no-cross": {("M0020", 0.95)},
}

# 843 확장 트랜치3 — 중점·비례·부호·동류항·완전제곱·켤레 계산형 6종(같은 화이트리스트 계약).
_TRANCHE3_DIRECT: dict[str, set[tuple[str, float]]] = {
    "midpoint-sum-only": {("M0066", 0.95)},
    "scale-area-linear": {("M0013", 0.95)},
    "negative-even-power-sign": {("M0201", 0.95)},
    "combine-unlike-terms": {("M0016", 0.95)},
    "complete-square-naive": {("M0119", 0.95)},
    "conjugate-product-sum": {("M0206", 0.95)},
}

# 843 확장 트랜치4 — 이항·GCD/LCM·소수·대분수·나머지정리·근과계수 계산형 6종(같은 화이트리스트).
_TRANCHE4_DIRECT: dict[str, set[tuple[str, float]]] = {
    "transpose-no-sign-change": {("M0021", 0.95)},
    "gcd-lcm-confused": {("M0014", 0.95)},
    "decimal-mult-place": {("M0103", 0.95)},
    "mixed-number-mult-whole": {("M0102", 0.95)},
    "remainder-theorem-sign": {("M0133", 0.95)},
    "vieta-sign-error": {("M0123", 0.95)},
}
_TRANCHE5_DIRECT: dict[str, set[tuple[str, float]]] = {
    "trapezoid-area-no-half": {("M0161", 0.95)},
    "scale-volume-linear": {("M0056", 0.95)},
    "cone-volume-no-third": {("M0063", 0.95)},
    "circle-area-circumference": {("M0053", 0.95)},
    "combination-no-denominator": {("M0087", 0.95)},
    "same-item-permutation-no-divide": {("M0190", 0.95)},
}

# MISC-21 — EOS G0 앵커 A1·A2·A3 좌석 보강 3종(같은 화이트리스트 계약·전행 pending·미서명).
# A5는 의도적 미승격(카탈로그 docstring·misconception_diagnosis.md #65-67 판정 근거 참조)이라
# 여기 없다.
_MISC21_DIRECT: dict[str, set[tuple[str, float]]] = {
    "bigger-denominator-bigger-fraction": {("M0462", 0.9)},
    "ratio-order-swapped": {("M0515", 0.85)},
    "addition-multiplication-rule-confused": {("M0599", 0.9)},
}


def test_real_queue_direct_top_confidences_match_draft(
    real_rows: list[dict[str, Any]],
) -> None:
    # ④ non-null 직접매핑 = 초안 ∪ 검수 ∪ S2-p ∪ 극값 MC ∪ 843 트랜치1~5 ∪ MISC-21 — 그 외 차단.
    expected: dict[str, set[tuple[str, float]]] = {
        k: set(_DRAFT_DIRECT_TOPS.get(k, set()))
        | set(_REVIEWED_DIRECT_ALTS.get(k, set()))
        | set(_S2P_DIRECT.get(k, set()))
        | set(_EXTREMUM_MC_DIRECT.get(k, set()))
        | set(_TRANCHE1_DIRECT.get(k, set()))
        | set(_TRANCHE2_DIRECT.get(k, set()))
        | set(_TRANCHE3_DIRECT.get(k, set()))
        | set(_TRANCHE4_DIRECT.get(k, set()))
        | set(_TRANCHE5_DIRECT.get(k, set()))
        | set(_MISC21_DIRECT.get(k, set()))
        for k in set(_DRAFT_DIRECT_TOPS)
        | set(_REVIEWED_DIRECT_ALTS)
        | set(_S2P_DIRECT)
        | set(_EXTREMUM_MC_DIRECT)
        | set(_TRANCHE1_DIRECT)
        | set(_TRANCHE2_DIRECT)
        | set(_TRANCHE3_DIRECT)
        | set(_TRANCHE4_DIRECT)
        | set(_TRANCHE5_DIRECT)
        | set(_MISC21_DIRECT)
    }
    actual: dict[str, set[tuple[str, float]]] = {}
    for row in real_rows:
        if row["link_type"] == "직접매핑" and row["confidence"] is not None:
            actual.setdefault(row["kebab_id"], set()).add((row["mis_id"], row["confidence"]))
    assert actual == expected


def test_real_queue_no_direct_candidate_case_transcribed(
    real_rows: list[dict[str, Any]],
) -> None:
    # period-of-scaled-sine — 직접 후보 부재: 최근접 후보를 낮은 link/conf 그대로 담고
    # rationale에 신규 M-id 저작 후보를 명기(초안 §2 마지막에서 둘째 행).
    rows = [r for r in real_rows if r["kebab_id"] == "period-of-scaled-sine"]
    assert len(rows) == 1
    row = rows[0]
    assert row["mis_id"] == "M0152"
    assert row["link_type"] == "개념겹침"
    assert row["confidence"] == 0.45
    assert "신규 M-id" in row["rationale"]
    assert not any(
        r["link_type"] == "직접매핑" for r in real_rows if r["kebab_id"] == "period-of-scaled-sine"
    )


def test_real_queue_explicit_alt_confidences_match_draft(
    real_rows: list[dict[str, Any]],
) -> None:
    # 초안이 conf를 명시한 대안 2건 — M0071(P 0.55)·M0503(약함 0.45) 스팟.
    by_pair = {(r["kebab_id"], r["mis_id"]): r for r in real_rows}
    m0071 = by_pair[("limit-equals-function-value", "M0071")]
    assert m0071["link_type"] == "부분매핑" and m0071["confidence"] == 0.55
    m0503 = by_pair[("fraction-cancellation", "M0503")]
    assert m0503["link_type"] == "개념겹침" and m0503["confidence"] == 0.45


def test_real_queue_promotes_nothing_as_is(real_queue: dict[str, Any]) -> None:
    # 전행 pending인 실 큐는 승격 0건 — 검수 없이 어떤 행도 로더 형식으로 새지 않는다.
    assert promote_approved(real_queue) == {"crosslinks": []}
