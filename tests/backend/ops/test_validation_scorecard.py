"""12월 검증 결론 판정기 — 동결 기준 준수 + **미측정이 통과로 위장되지 않음** (EOS-61).

이 파일이 지키는 것은 두 가지다.

1. **§5 동결 문언대로 판정하는가** — F-Ⅰ~F-Ⅴ의 임계값과 F-Ⅳ의 "3개 이상 NO_GO /
   2개면 Conditional"은 G0 서명으로 동결됐고 12월 수정 금지다. 코드가 그 문언에서
   미끄러지면 검증이 아니라 확증편향이 된다.
2. **측정하지 않은 것을 통과라 하지 않는가** — 이 저장소가 반복해서 다친 부류다.
   실제로 1차 구현은 **빈 입력에서 GO**를 냈다(Hard Gate가 전부 판정 불가라 triggered가
   없고 KPI가 전부 미측정이라 failed도 없었다). 그 회귀를 여기서 막는다.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from whymath_backend.ops import validation_scorecard as vs
from whymath_backend.ops.validation_scorecard import (
    KPI_SOURCES,
    KpiVerdict,
    Verdict,
    evaluate,
    main,
    render,
)


def _anchors(fail: int, total: int = 6) -> dict[str, bool]:
    return {f"A{i + 1}": i >= fail for i in range(total)}


#: 모든 Hard Gate가 '미해당'이고 모든 KPI가 통과하는 완전 입력.
def _clean_payload() -> dict:
    return {
        "hit": {
            "median_minutes": 3.0,
            "p90_minutes": 7.0,
            "sample_size": 200,
            "baseline_anchor_median_minutes": {"A3": 5.0, "A4": 6.0},
        },
        "auto_gate_pass": {"hits": 900, "trials": 1000},
        "rework": {"hits": 60, "trials": 1000, "repeat_hits": 5, "repeat_trials": 1000},
        "throughput": {"cu_per_hour": 35.0, "sample_size": 200},
        "unit_cost": {"krw_per_cu": 180.0, "sample_size": 200},
        "machine_share": {"hits": 700, "trials": 1000},
        "failure_distribution": {"judgment_hits": 300, "rejected_total": 1000},
        "anchors": _anchors(0),
        "content": {
            "reviewed_math_errors": 0,
            "reviewed_cu_total": 2000,
            "hint_leak_hits": 0,
            "hint_leak_sample": 500,
            # 수학적 오류율은 **상한** 지표(≤0.5%)다 — 분자는 결함 건수이고, 임계는
            # 입력이 아니라 CONTENT_KPI_THRESHOLDS가 갖는다.
            "수학적 오류율 ≤0.5% (독립 모델 심판 전수)": {"hits": 0, "trials": 4000},
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# ① 미측정이 통과가 되지 않는다 — 1차 구현의 실제 결함
# ──────────────────────────────────────────────────────────────────────────
def test_empty_input_never_yields_go() -> None:
    """빈 입력에서 GO가 나오면 '검증했고 통과했다'는 거짓 신호가 된다.

    1차 구현이 실제로 GO를 냈다 — Hard Gate가 전부 판정 불가라 triggered가 없고 KPI가
    전부 미측정이라 failed도 없어서, 두 부정을 통과로 읽었기 때문이다.
    """
    card = evaluate({})
    assert card.verdict is not Verdict.GO
    assert card.measurement_failed is True
    assert card.unmeasured_count > 0 and card.unmeasurable_gate_count == 5


def test_measurement_failure_is_distinct_from_failing_a_gate() -> None:
    """'실패인지 모른다'와 '실패다'는 다른 축 — 같은 필드로 표현하지 않는다."""
    card = evaluate({})
    assert all(not g.triggered for g in card.hard_gates), "판정 불가를 해당으로 접었다"
    assert all(not g.measurable for g in card.hard_gates)


def test_one_missing_kpi_blocks_go() -> None:
    """11종이 통과여도 1종이 미측정이면 GO가 아니다 — 부분 측정은 완결이 아니다."""
    payload = _clean_payload()
    del payload["unit_cost"]
    card = evaluate(payload)
    assert card.verdict is Verdict.CONDITIONAL_GO
    assert card.measurement_failed is True


def test_go_is_currently_unreachable_and_that_is_the_honest_state() -> None:
    """**지금 이 저장소에서는 GO가 나올 수 없다** — 채점기가 아직 없기 때문이다.

    깨끗한 입력을 줘도 내용 KPI 일부는 미측정으로 남는다(`consumer_module=None` +
    골든 축 밖 2종). 그것이 결함이 아니라 **사실**이고, 스코어카드가 그 사실을 GO로
    덮지 않는 것이 이 도구의 존재 이유다.

    이 테스트는 "왜 아직 GO가 안 나오나"를 미래 세션에게 설명하는 자리이기도 하다 —
    답은 '입력이 나빠서'가 아니라 '재는 도구가 아직 없어서'다.
    """
    card = evaluate(_clean_payload())
    assert card.verdict is not Verdict.GO
    assert card.measurement_failed is True
    unmeasured = [k for k in card.kpis if k.verdict is KpiVerdict.unmeasured]
    assert unmeasured, "미측정이 0인데 GO가 아니면 다른 이유가 섞인 것이다"
    for k in unmeasured:
        assert k.note, f"'{k.kpi}'가 왜 미측정인지 말하지 않는다"


def test_go_is_reachable_once_every_scorer_lands(monkeypatch) -> None:
    """변별력 — 전 지표가 측정되면 실제로 GO가 나온다.

    이 케이스가 없으면 위 테스트들이 '항상 GO를 막는' 구현으로도 통과한다. 미착지
    채점기를 착지한 것으로 가정한 입력을 만들어, 막는 것이 *구현*이 아니라 *데이터
    부재*임을 보인다.
    """
    from whymath_backend.ops import validation_scorecard as vs
    from whymath_backend.ops.qa_confusion_matrix import ContentKpiConsumer

    landed = tuple(
        ContentKpiConsumer(
            kpi=c.kpi,
            label_axis=c.label_axis,
            consumer_module=c.consumer_module or "whymath_backend.ops.qa_confusion_matrix",
            seat_task=c.seat_task,
            failure_codes=c.failure_codes,
        )
        for c in vs.CONTENT_KPI_CONSUMERS
    )
    monkeypatch.setattr(vs, "CONTENT_KPI_CONSUMERS", landed)

    payload = _clean_payload()
    for consumer in landed:
        threshold = vs.CONTENT_KPI_THRESHOLDS[consumer.kpi]
        # 방향이 섞여 있으므로 통과 입력도 방향별로 만든다 — 하한 지표는 거의 전부 성공,
        # 상한 지표는 거의 전부 무결함.
        payload["content"][consumer.kpi] = (
            {"hits": 0, "trials": 4000}
            if threshold.direction == "ceiling"
            else {"hits": 9900, "trials": 10000}
        )
    for kpi, _target, _reason in vs.NON_GOLDEN_CONTENT_KPIS:
        payload["content"][kpi] = {"observed": "ρ=0.62", "passed": True, "sample_size": 120}

    card = vs.evaluate(payload)
    assert card.verdict is Verdict.GO
    assert card.measurement_failed is False


def test_scorecard_reports_all_twelve_kpis() -> None:
    """§6이 동결한 12종(기술 6 · 내용 6)이 전부 표에 오른다.

    결선표(`CONTENT_KPI_CONSUMERS`)는 4종만 담는다 — 골든 라벨 축이 없는 2종(난이도
    타당도·힌트 누설률)이 거기 없는 것이 맞기 때문이다. 그 둘을 스코어카드에서도 빼면
    "12종을 봤다"는 착시가 생기므로 별도 상수로 채운다.
    """
    card = evaluate(_clean_payload())
    assert len(card.kpis) == 12, [k.kpi for k in card.kpis]


# ──────────────────────────────────────────────────────────────────────────
# ② Hard Gate가 점수보다 먼저다 (설계 규칙 1)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda p: p["hit"]["baseline_anchor_median_minutes"].update({"A3": 12.5}), "F-Ⅰ"),
        (lambda p: p["content"].update({"reviewed_math_errors": 200}), "F-Ⅱ"),
        (lambda p: p["failure_distribution"].update({"judgment_hits": 700}), "F-Ⅲ"),
        (lambda p: p.update({"anchors": _anchors(3)}), "F-Ⅳ"),
        (lambda p: p["content"].update({"hint_leak_hits": 100}), "F-Ⅴ"),
    ],
)
def test_each_hard_gate_forces_no_go(mutate, code: str) -> None:
    """F-Ⅰ~F-Ⅴ **각각**이 단독으로 NO_GO를 만든다 — 하나라도 놓치면 게이트가 아니다."""
    payload = _clean_payload()
    mutate(payload)
    card = evaluate(payload)
    assert card.verdict is Verdict.NO_GO, f"{code}가 NO_GO를 만들지 못했다"
    triggered = [g.code for g in card.hard_gates if g.triggered]
    assert code in triggered, f"{code}가 아니라 {triggered}가 걸렸다"


def test_anchor_threshold_follows_the_frozen_wording() -> None:
    """F-Ⅳ 동결 문언: 3개 이상 미달 = NO_GO · 2개 = Conditional Go.

    임계값이 한 칸 밀리면(2개에서 NO_GO, 또는 3개에서 Conditional) 12월 판정이
    동결 기준과 달라진다 — 경계 양쪽을 모두 고정한다.
    """
    two = _clean_payload()
    two["anchors"] = _anchors(2)
    assert evaluate(two).verdict is Verdict.CONDITIONAL_GO

    three = _clean_payload()
    three["anchors"] = _anchors(3)
    assert evaluate(three).verdict is Verdict.NO_GO


def test_no_single_composite_score_is_produced() -> None:
    """단일 EOS Score 금지 — 치명 오류가 평균에 묻히는 구조를 만들지 않는다.

    Scorecard에 종합 점수 필드가 **없음**을 동결한다. 누군가 편의로 추가하면 그 순간
    "평균 82점이니 괜찮다"가 가능해지고, F-Ⅰ 해당이 그 82점 안으로 사라진다.
    """
    card = evaluate(_clean_payload())
    forbidden = {"score", "total_score", "composite", "eos_score", "overall"}
    assert not (forbidden & set(vars(card).keys() if hasattr(card, "__dict__") else card.__slots__))


# ──────────────────────────────────────────────────────────────────────────
# ③ 결선표·한계·판정 형식
# ──────────────────────────────────────────────────────────────────────────
def test_technical_kpi_sources_are_six_and_name_their_seat() -> None:
    """기술 KPI 6종이 각각 출처 모듈과 좌석 태스크를 말한다(acceptance ⑤)."""
    assert len(KPI_SOURCES) == 6
    for src in KPI_SOURCES:
        assert src.source_module.startswith("whymath_backend."), src.kpi
        assert src.seat_task, src.kpi


def test_content_kpis_reuse_the_existing_crosswalk() -> None:
    """내용 KPI는 `CONTENT_KPI_CONSUMERS`를 재사용한다 — 결선표를 두 곳에 두지 않는다."""
    from whymath_backend.ops.qa_confusion_matrix import CONTENT_KPI_CONSUMERS

    card = evaluate(_clean_payload())
    for consumer in CONTENT_KPI_CONSUMERS:
        assert any(k.kpi == consumer.kpi for k in card.kpis), consumer.kpi


def test_unlanded_scorer_is_reported_as_unmeasured_not_pass() -> None:
    """채점기가 없는 내용 KPI는 '미측정'이며 좌석 태스크를 함께 말한다(추정 금지)."""
    from whymath_backend.ops.qa_confusion_matrix import CONTENT_KPI_CONSUMERS

    unlanded = [c for c in CONTENT_KPI_CONSUMERS if c.consumer_module is None]
    if not unlanded:
        pytest.skip("모든 내용 채점기가 착지했다 — 이 케이스는 더 이상 재현되지 않는다")
    card = evaluate(_clean_payload())
    for consumer in unlanded:
        result = next(k for k in card.kpis if k.kpi == consumer.kpi)
        assert result.verdict is KpiVerdict.unmeasured
        assert consumer.seat_task in result.note


def test_report_always_carries_the_design_limits() -> None:
    """§7 한계가 리포트에 **항상** 실린다 — 빼면 표본 185건 판정이 정밀 추정으로 읽힌다."""
    text = render(evaluate(_clean_payload()))
    assert "§7-3" in text and "185 CU" in text
    assert "§7-4" in text


def test_cli_exit_codes(tmp_path) -> None:
    """exit 0 = GO뿐. CONDITIONAL_GO·NO_GO·측정 실패는 전부 1(진행 금지 신호 공유)."""
    # 현재 저장소 상태에서는 깨끗한 입력도 exit 1이다 — 채점기 미착지로 미측정이 남는다.
    # 그것이 정직한 결과다: "GO를 선언할 수 없다"와 "기준 미달"은 stdout이 구분해 말한다.
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(_clean_payload()), encoding="utf-8")
    assert main(["--input", str(clean)]) == 1

    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert main(["--input", str(empty)]) == 1

    broken = tmp_path / "broken.json"
    broken.write_text("{ 깨진", encoding="utf-8")
    assert main(["--input", str(broken)]) == 1, "입력을 못 읽은 것도 진행 금지다"

    assert main(["--input", str(tmp_path / "없는파일.json")]) == 1


def test_cli_json_output_exposes_measurement_failure(tmp_path) -> None:
    """JSON 소비자도 '측정 불완전'을 볼 수 있어야 한다 — verdict만 읽고 오독하지 않게."""
    src = tmp_path / "in.json"
    src.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"
    main(["--input", str(src), "--json", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["measurement_failed"] is True
    assert payload["verdict"] != "GO"
    assert payload["unmeasured_kpis"] > 0


# ──────────────────────────────────────────────────────────────────────────
# ⑥ PR #953 리뷰(codex) 지적 6건 — 각각이 재발하면 여기서 깨진다
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("anchors", "why"),
    [
        ({"A1": True}, "부분 지도 — 5개를 재지 않았는데 '0/1 미달'로 통과했다"),
        ({f"A{i}": True for i in range(1, 6)}, "A6 누락"),
        (
            {**{f"A{i}": True for i in range(1, 7)}, "A7": True},
            "정의에 없는 앵커가 분모를 늘린다",
        ),
        ({f"A{i}": "fail" for i in range(1, 7)}, "bool이 아닌 값 — `is False`만 세면 합격이 된다"),
        ({f"A{i}": None for i in range(1, 7)}, "None — 미판정이 합격이 된다"),
    ],
)
def test_partial_or_untyped_anchor_map_is_not_measurable(anchors: dict, why: str) -> None:
    """F-Ⅳ는 **A1~A6 전수 bool**일 때만 판정 가능하다 — 아니면 measurable=False.

    '6개 중 3개'라는 문언은 분모가 6일 때만 셀 수 있다. 부분 지도를 받아 `0/1 미달`을
    내면 그것은 "앵커가 멀쩡하다"가 아니라 "5개를 재지 않았다"인데, 판정문은 전자로
    읽힌다. 값이 bool이 아닌 경우도 같다 — 이전 판은 `ok is False`만 세어서 문자열
    `"fail"`이 조용히 합격이 됐다.
    """
    payload = _clean_payload()
    payload["anchors"] = anchors
    card = evaluate(payload)
    gate = next(g for g in card.hard_gates if g.code == "F-Ⅳ")
    assert gate.measurable is False, why
    assert gate.triggered is False, "판정 불가를 '해당'으로 접으면 안 된다"
    assert gate.observed not in ("", "—"), "왜 판정 불가인지 사유가 없다"
    assert card.measurement_failed is True


def test_defect_rate_content_kpi_uses_an_upper_bound() -> None:
    """결함율 KPI(≤0.5%)는 Wilson **상한**으로 본다 — 하한을 쓰면 1%가 통과한다.

    codex P1이 지적한 그 시나리오를 그대로 재현한다: 오류율 1%(40/4000)는 0.5% 기준을
    넘었으므로 반드시 fail이어야 한다. 이전 판은 모든 내용 KPI에 하한을 썼고 임계도
    입력이 줬기 때문에, 하한(≈0.74%)이 입력이 준 floor(0.5%)보다 커서 **통과**했다.
    """
    from whymath_backend.ops import validation_scorecard as vs

    kpi = "수학적 오류율 ≤0.5% (독립 모델 심판 전수)"
    assert vs.CONTENT_KPI_THRESHOLDS[kpi].direction == "ceiling"

    payload = _clean_payload()
    payload["content"][kpi] = {"hits": 40, "trials": 4000}  # 1.0%
    result = next(k for k in evaluate(payload).kpis if k.kpi == kpi)
    assert result.verdict is KpiVerdict.failed, f"오류율 1%가 0.5% 기준을 통과했다: {result}"
    assert "상한" in result.observed


def test_content_kpi_threshold_is_not_taken_from_the_input() -> None:
    """입력이 자기 합격선을 써 내면 판정이 아니다 — 임계 필드가 있으면 거부한다."""
    kpi = "수학적 오류율 ≤0.5% (독립 모델 심판 전수)"
    payload = _clean_payload()
    payload["content"][kpi] = {"hits": 40, "trials": 4000, "floor": 0.001}
    result = next(k for k in evaluate(payload).kpis if k.kpi == kpi)
    assert result.verdict is KpiVerdict.unmeasured
    assert "임계" in result.note, "왜 거부됐는지 말하지 않는다"


def test_every_content_consumer_has_a_frozen_threshold() -> None:
    """결선표의 KPI 문언이 바뀌면 임계표가 조용히 빗나가는 대신 여기서 깨진다."""
    from whymath_backend.ops import validation_scorecard as vs

    missing = [c.kpi for c in vs.CONTENT_KPI_CONSUMERS if c.kpi not in vs.CONTENT_KPI_THRESHOLDS]
    assert not missing, f"임계 미등록: {missing}"
    for threshold in vs.CONTENT_KPI_THRESHOLDS.values():
        assert threshold.direction in ("floor", "ceiling")


def test_repeated_regeneration_submetric_is_required_and_enforced() -> None:
    """재작업률 목표는 '≤15% **그리고** 2회+ 재생성 ≤3%' — 하나만 재면 미측정이다."""
    from whymath_backend.ops import validation_scorecard as vs

    kpi = next(s.kpi for s in KPI_SOURCES if s.payload_key == "rework")

    payload = _clean_payload()
    payload["rework"] = {"hits": 60, "trials": 1000}  # 하위지표 없음
    result = next(k for k in evaluate(payload).kpis if k.kpi == kpi)
    assert result.verdict is KpiVerdict.unmeasured, "2회+ 재생성을 재지 않고 통과했다"
    assert "repeat" in result.note

    # 변별력 — 하위지표가 있고 그것이 미달이면 fail이 되어야 한다(항상 미측정이 아니다).
    payload["rework"] = {"hits": 60, "trials": 1000, "repeat_hits": 80, "repeat_trials": 1000}
    result = next(k for k in evaluate(payload).kpis if k.kpi == kpi)
    assert result.verdict is KpiVerdict.failed
    assert vs.KpiThreshold("ceiling", 0.03).judge(80, 1000)[0] is False


def test_judgment_share_gate_uses_the_wilson_boundary() -> None:
    """F-Ⅲ도 비율이다 — 점추정 비교는 작은 표본에서 아무 말도 아니다(설계 규칙 4).

    반려 5건 중 3건은 점추정 60.0%라 '초과 아님'이지만 상한은 87%다. 이 게이트가 묻는
    것은 '판단형이 지배적인가'이고, 지배를 낙관적으로 볼 이유가 없다.
    """
    payload = _clean_payload()
    payload["failure_distribution"] = {"judgment_hits": 3, "rejected_total": 5}
    gate = next(g for g in evaluate(payload).hard_gates if g.code == "F-Ⅲ")
    assert gate.measurable is True
    assert gate.triggered is True, "점추정 60.0%를 '미해당'으로 접었다"
    assert "상한" in gate.observed

    # 변별력 — 큰 표본에서 실제로 낮으면 미해당이어야 한다(항상 triggered가 아니다).
    payload["failure_distribution"] = {"judgment_hits": 300, "rejected_total": 1000}
    gate = next(g for g in evaluate(payload).hard_gates if g.code == "F-Ⅲ")
    assert gate.triggered is False


@pytest.mark.parametrize("key", ["hit", "throughput", "unit_cost"])
def test_summary_kpis_without_a_sample_size_are_unmeasured(key: str) -> None:
    """표본수 없는 요약값은 판정하지 않는다 — CU 2건짜리 '통과'는 아무것도 보증하지 않는다."""
    payload = _clean_payload()
    payload[key].pop("sample_size")
    kpi = next(s.kpi for s in KPI_SOURCES if s.payload_key == key)
    result = next(k for k in evaluate(payload).kpis if k.kpi == kpi)
    assert result.verdict is KpiVerdict.unmeasured
    assert "sample_size" in result.note


def test_content_kpi_nodes_are_keyed_by_kpi_not_seat_task() -> None:
    """좌석 하나가 KPI 둘을 가질 수 있다 — 좌석으로 키를 잡으면 한 지표가 사라진다.

    `EOS-61-validation-scorecard-aggregator` 좌석이 교육과정 정합률과 풀이 비약 지적률
    **둘**을 갖는다. 좌석 키였을 때 뒤 입력이 앞을 덮어, 정합률이 비약의 입력으로
    판정됐다(구현 중 실측으로 잡음).
    """
    from whymath_backend.ops import validation_scorecard as vs

    seats = [c.seat_task for c in vs.CONTENT_KPI_CONSUMERS]
    assert len(set(seats)) < len(seats), "좌석이 유일해졌다면 이 테스트의 전제를 다시 본다"
    assert len({c.kpi for c in vs.CONTENT_KPI_CONSUMERS}) == len(seats), "KPI 이름은 유일해야 한다"


# ──────────────────────────────────────────────────────────────────────────
# ⑦ 생산자 배선 — 결선표가 지목한 산출물을 **실제로** 읽는가 (codex P1 ⑤)
# ──────────────────────────────────────────────────────────────────────────
# 결선표에 `source_module`을 적는 것은 배선이 아니다. 1차 구현은 `hit.median_minutes`를
# 기대했는데 생산자는 `hit_median_seconds`를 낸다 — 두 모양이 아무 데서도 만나지 않아
# **실재하는 산출물이 미측정으로 보고되는** 상태였다. 아래 테스트들은 생산자의 *실제*
# 필드명으로 짜여 있어, 생산자가 이름을 바꾸면 여기서 깨진다.
def _hit_report_json(**overrides) -> dict:
    """`hit_cu_metrics --json` 산출과 **같은 키 집합**의 dict — 필드명은 생산자에서 온다."""
    import dataclasses

    from whymath_backend.ops.hit_cu_metrics import HitCuReport

    payload: dict = {}
    for field in dataclasses.fields(HitCuReport):
        payload[field.name] = None
    payload.update(overrides)
    return payload


def test_hit_adapter_reads_only_real_producer_fields() -> None:
    """어댑터가 읽는 키가 전부 `HitCuReport`의 실제 필드인가 — 오타·상상 키 차단."""
    import dataclasses

    from whymath_backend.ops.hit_cu_metrics import HitCuReport

    known = {f.name for f in dataclasses.fields(HitCuReport)}
    read_by_adapter = {
        "hit_median_seconds",
        "cu_measured",
        "hit_total_seconds",
        "failure_code_counts",
        "rejected_count",
        "cost_usd_total",
        "cu_with_cost",
    }
    assert read_by_adapter <= known, f"생산자에 없는 키를 읽는다: {sorted(read_by_adapter - known)}"


def test_hit_adapter_turns_a_real_report_into_measured_kpis() -> None:
    """실제 산출물 모양이 들어오면 HIT·처리량·기계형 분포·F-Ⅲ가 **측정된다**."""
    from whymath_backend.ops import validation_scorecard as vs

    report = _hit_report_json(
        hit_median_seconds=180.0,  # 3분
        cu_measured=200,
        hit_total_seconds=200 * 120.0,  # 평균 2분/CU → 30 CU/h
        rejected_count=100,
        failure_code_counts={f"F{i}": 0 for i in range(1, 9)}
        | {"F1": 40, "F2": 30, "F3": 10, "F6": 5, "F7": 5},
        cost_usd_total=20.0,
        cu_with_cost=200,
    )
    adapted = vs.adapt_hit_cu_metrics(report, krw_per_usd=1400.0)

    assert adapted["hit"] == {"median_minutes": 3.0, "sample_size": 200}
    assert adapted["throughput"]["cu_per_hour"] == pytest.approx(30.0)
    assert adapted["machine_share"] == {"hits": 70, "trials": 100}
    assert adapted["failure_distribution"] == {"judgment_hits": 20, "rejected_total": 100}
    assert adapted["unit_cost"]["krw_per_cu"] == pytest.approx(140.0)

    card = vs.evaluate(adapted)
    measured = {k.kpi for k in card.kpis if k.verdict is not KpiVerdict.unmeasured}
    for src in KPI_SOURCES:
        if src.payload_key in ("machine_share", "throughput", "unit_cost"):
            assert src.kpi in measured, f"'{src.kpi}'가 실제 산출물에서도 미측정이다"
    assert next(g for g in card.hard_gates if g.code == "F-Ⅲ").measurable is True


def test_hit_adapter_does_not_invent_what_the_producer_lacks() -> None:
    """생산자에 없는 것(P90·재작업·자동검증 통과율)은 **만들지 않는다**.

    채워 넣으면 좌석 미착지가 통과로 위장된다. 미측정으로 남는 것이 정직한 상태다.
    """
    from whymath_backend.ops import validation_scorecard as vs

    adapted = vs.adapt_hit_cu_metrics(
        _hit_report_json(hit_median_seconds=180.0, cu_measured=200, hit_total_seconds=24000.0)
    )
    assert "p90_minutes" not in adapted["hit"]
    assert "rework" not in adapted and "auto_gate_pass" not in adapted

    card = vs.evaluate(adapted)
    hit_kpi = next(k for k in card.kpis if k.kpi.startswith("HIT"))
    assert hit_kpi.verdict is KpiVerdict.unmeasured
    assert "p90_minutes" in hit_kpi.note, "무엇이 없어서 못 쟀는지 말하지 않는다"


def test_unit_cost_needs_an_explicit_exchange_rate() -> None:
    """환율 없이 원화 단가를 만들지 않는다 — 임의 환율은 측정이 아니라 가정이다."""
    from whymath_backend.ops import validation_scorecard as vs

    adapted = vs.adapt_hit_cu_metrics(_hit_report_json(cost_usd_total=20.0, cu_with_cost=200))
    assert "unit_cost" not in adapted


def test_failure_code_classification_matches_the_producer() -> None:
    """기계형/판단형 분류의 정본은 `hit_cu_metrics`다 — 두 곳이 갈라지면 여기서 깨진다."""
    from whymath_backend.ops import hit_cu_metrics as hcm
    from whymath_backend.ops import validation_scorecard as vs

    assert set(vs._MACHINE_FAILURE_CODES) == {c.value for c in hcm._MACHINE_CODES}
    assert set(vs._JUDGMENT_FAILURE_CODES) == {c.value for c in hcm._JUDGMENT_CODES}


def test_qa_matrix_adapter_maps_a_real_report_payload() -> None:
    """`qa_confusion_matrix`의 실제 JSON에서 F-Ⅱ·수학적 오류율이 측정된다.

    FN(정답지가 결함이라 한 것을 엔진이 통과시킨 건)은 정의상 **검수를 통과한 결함 CU**다 —
    F-Ⅱ와 수학적 오류율 KPI가 묻는 바로 그 모집단이다.
    """
    from datetime import UTC, datetime

    from whymath_backend.harness.golden_benchmark import (
        AsFoundBasis,
        GoldenItem,
        GoldenLabel,
        freeze_golden_set,
    )
    from whymath_backend.ops import validation_scorecard as vs
    from whymath_backend.ops.qa_confusion_matrix import (
        Prediction,
        _report_payload,
        build_report,
    )
    from whymath_backend.schema.enums import GenerationFailureCode

    def _item(slug: str, label: GoldenLabel, code=None) -> GoldenItem:
        return GoldenItem(
            cu_slug=slug,
            anchor_id="A4",
            label=label,
            failure_code=code if label == GoldenLabel.DEFECTIVE else None,
            as_found_basis=(
                AsFoundBasis.REJECTED_FAILURE_CODE
                if label == GoldenLabel.DEFECTIVE
                else AsFoundBasis.PRE_REVIEW_SNAPSHOT
            ),
        )

    items = [_item(f"clean-{i}", GoldenLabel.CLEAN) for i in range(20)]
    items.append(_item("escaped", GoldenLabel.DEFECTIVE, GenerationFailureCode.F1))
    golden = freeze_golden_set(
        items, golden_version="v1", rotation=0, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    predictions = [Prediction(item.cu_slug, passed=True) for item in items]
    produced = _report_payload(build_report(golden, predictions))

    adapted = vs.adapt_qa_confusion_matrix(produced)
    assert adapted["content"]["reviewed_math_errors"] == 1  # F1 FN 1건
    assert adapted["content"]["reviewed_cu_total"] == 21

    payload = vs.merge_payloads(_clean_payload(), adapted)
    card = vs.evaluate(payload)
    gate = next(g for g in card.hard_gates if g.code == "F-Ⅱ")
    assert gate.measurable is True
    kpi = next(k for k in card.kpis if k.kpi.startswith("수학적 오류율"))
    assert kpi.verdict is not KpiVerdict.unmeasured
    assert kpi.sample_size == 21


def test_qa_matrix_adapter_does_not_borrow_anchor_verdicts() -> None:
    """`by_anchor`는 *QA 엔진의 앵커별 FN율*이지 '그 앵커가 기준을 충족했는가'가 아니다.

    간접 신호를 판정으로 쓰지 않는다 — F-Ⅳ는 명시 입력으로만 판정한다.
    """
    from whymath_backend.ops import validation_scorecard as vs

    adapted = vs.adapt_qa_confusion_matrix(
        {
            "coverage": {"evaluated": 100},
            "fn_by_failure_code": {"F1": 0, "F2": 0},
            "by_anchor": [{"anchor_id": f"A{i}", "fn_rate_upper": 0.0} for i in range(1, 7)],
        }
    )
    assert "anchors" not in adapted


def test_cli_consumes_producer_json_directly(tmp_path) -> None:
    """CLI가 생산자 산출 파일을 그대로 먹는가 — 배선의 집행 지점(수기 변환 불요)."""
    hit_path = tmp_path / "hit.json"
    hit_path.write_text(
        json.dumps(
            _hit_report_json(
                hit_median_seconds=180.0,
                cu_measured=200,
                hit_total_seconds=24000.0,
                rejected_count=100,
                failure_code_counts={f"F{i}": 0 for i in range(1, 9)} | {"F1": 70},
            )
        ),
        encoding="utf-8",
    )
    # 전 지표가 차지는 않으므로 exit 1(측정 불완전)이 정상이다 — 확인하는 것은
    # "생산자 산출을 읽어 실제로 측정된 지표가 생기는가"다.
    assert main(["--hit-cu-json", str(hit_path)]) == 1

    out = tmp_path / "verdict.json"
    main(["--hit-cu-json", str(hit_path), "--json", str(out)])
    written = json.loads(out.read_text(encoding="utf-8"))
    measured = [k for k in written["kpis"] if k["verdict"] != "unmeasured"]
    assert measured, "생산자 산출을 줬는데 측정된 지표가 하나도 없다 — 배선이 없는 것이다"
    assert any(k["kpi"].startswith("실패 유형 분포") for k in measured)


def test_manual_input_overrides_adapter_output(tmp_path) -> None:
    """수동 `--input`이 어댑터 산출보다 뒤에 병합된다(앵커 판정 등 사람 입력 구간)."""
    from whymath_backend.ops import validation_scorecard as vs

    merged = vs.merge_payloads(
        {"hit": {"median_minutes": 3.0, "sample_size": 10}},
        {"hit": {"p90_minutes": 7.0}, "anchors": _anchors(0)},
    )
    assert merged["hit"] == {"median_minutes": 3.0, "sample_size": 10, "p90_minutes": 7.0}
    assert merged["anchors"]["A6"] is True


def test_cli_requires_at_least_one_input() -> None:
    """입력을 하나도 주지 않으면 '빈 판정'이 아니라 사용법 오류다."""
    with pytest.raises(SystemExit):
        main([])


def test_dense_and_sparse_failure_code_maps_are_read_differently() -> None:
    """`hit_cu_metrics`는 전 코드를 0으로 채우고(dense) `qa_confusion_matrix`는 안 채운다.

    이 구분을 뭉개면 한쪽에서 계약 위반이 0으로 위장되고, 다른 쪽에서 정상 산출이
    미측정으로 버려진다.
    """
    from whymath_backend.ops import validation_scorecard as vs

    # dense: F2가 없으면 '그 산출물이 아니다' → 미측정
    partial = _hit_report_json(rejected_count=10, failure_code_counts={"F1": 3})
    assert "machine_share" not in vs.adapt_hit_cu_metrics(partial)

    # sparse: F2가 없으면 실제로 0건
    adapted = vs.adapt_qa_confusion_matrix(
        {"coverage": {"evaluated": 100}, "fn_by_failure_code": {"F1": 3}}
    )
    assert adapted["content"]["reviewed_math_errors"] == 3


def test_producer_enum_repr_keys_are_rejected_as_unmeasured() -> None:
    """repr 키(`GenerationFailureCode.F1`)는 계약 위반 → **미측정**. 조용히 0건으로 읽지 않는다.

    EOS-61 초판은 양쪽 표기를 받았다(`rsplit`). EOS-75가 생산자의 키를 `.value`로 명시·동결한
    뒤로 repr 키는 "우리가 아는 그 산출물이 아니다"다 — sparse 경로에서 무시하면 *수학 오류
    0건*이라는 거짓 통과가 되므로 미측정으로 드러낸다. 정상 표기는 그대로 읽힌다(대조군).
    """
    from whymath_backend.ops import validation_scorecard as vs

    rejected = vs.adapt_qa_confusion_matrix(
        {"coverage": {"evaluated": 50}, "fn_by_failure_code": {"GenerationFailureCode.F1": 2}}
    )
    assert rejected == {}, "repr 키를 읽어 버렸다(계약 위반이 통과로 위장)"

    accepted = vs.adapt_qa_confusion_matrix(
        {"coverage": {"evaluated": 50}, "fn_by_failure_code": {"F1": 2}}
    )
    assert accepted["content"]["reviewed_math_errors"] == 2

    # dense 경로(hit_cu_metrics)도 같은 계약 — 전 코드가 있어도 repr 키가 섞이면 미측정
    from whymath_backend.schema.enums import GenerationFailureCode

    dense_ok = {c.value: 0 for c in GenerationFailureCode} | {"F1": 3}
    assert "machine_share" in vs.adapt_hit_cu_metrics(
        _hit_report_json(rejected_count=10, failure_code_counts=dense_ok)
    )
    dense_polluted = dense_ok | {"GenerationFailureCode.F2": 1}
    assert "machine_share" not in vs.adapt_hit_cu_metrics(
        _hit_report_json(rejected_count=10, failure_code_counts=dense_polluted)
    )


class TestEditAwareVerdictSeam:
    """EOS-62 × EOS-61 이음매 — 손질 승인이 F-Ⅲ 분모를 오염시키지 않는가.

    두 태스크는 서로 다른 브랜치에서 같은 계측 사슬을 건드렸다(EOS-62는 생산자
    `hit_cu_metrics`, EOS-61은 소비자 `adapt_hit_cu_metrics`). **어느 쪽 CI도 상대를 보지
    못했으므로** 이 이음매는 두 PR이 각각 green이어도 깨질 수 있는 자리다 — 그래서 실물
    생산자 산출을 실물 소비자에 태워 고정한다.

    지켜야 하는 것: F-Ⅲ("실패 분포에서 판단형 > 60%")의 '실패 분포'는 EOS-51 §5에서 12월까지
    수정 금지로 동결된 의미이고, 그 모집단은 **반려분**이다. 손질 승인의 부기 결함코드를
    `failure_code_counts`에 합쳤다면 소비자는 아무것도 모른 채 다른 모집단 위에서 임계를
    계산했을 것이다 — 조용한 판정 오염이다.
    """

    @staticmethod
    def _producer_report() -> dict:
        """실물 `hit_cu_metrics.aggregate` 산출(JSON 평면) — 손질 승인 F7이 섞인 구성."""
        from whymath_backend.harness.review_timer import finish_review, start_review
        from whymath_backend.ops.hit_cu_metrics import aggregate
        from whymath_backend.schema.enums import GenerationFailureCode

        events = []
        for slug, verdict, code in (
            ("cu-rejected", "rejected", GenerationFailureCode.F2),  # 기계형 반려
            ("cu-edited", "approved_with_edit", GenerationFailureCode.F7),  # 판단형 손질
            ("cu-clean", "approved", None),
        ):
            started = start_review(cu_slug=slug, reviewer_id="kiki")
            events.append(started)
            events.append(
                finish_review(
                    review_session_id=started.review_session_id,
                    cu_slug=slug,
                    reviewer_id="kiki",
                    verdict=verdict,  # type: ignore[arg-type]
                    failure_code=code,
                    elapsed_ms=60_000,
                )
            )
        return dataclasses.asdict(aggregate(events))

    def test_edit_codes_do_not_enter_the_frozen_failure_distribution(self) -> None:
        """★ 판단형 F7 손질 1건이 있어도 F-Ⅲ 모집단은 반려 1건 그대로다."""
        adapted = vs.adapt_hit_cu_metrics(self._producer_report())

        assert adapted["failure_distribution"]["rejected_total"] == 1
        # 손질분(F7=판단형)이 섞였다면 judgment_hits가 1이 되어 판단형 비중 0%→100%가 된다.
        assert adapted["failure_distribution"]["judgment_hits"] == 0
        assert adapted["machine_share"] == {"hits": 1, "trials": 1}

    def test_producer_still_reports_the_edit_axis_separately(self) -> None:
        """분리는 '버림'이 아니다 — 손질 코드는 별도 축에 살아 있어야 한다."""
        report = self._producer_report()
        assert report["edit_failure_code_counts"]["F7"] == 1
        assert report["failure_code_counts"]["F7"] == 0
        assert report["approved_with_edit_count"] == 1

    def test_adapter_ignores_new_producer_fields_without_error(self) -> None:
        """소비자는 EOS-62가 더한 필드를 모른다 — 모르는 채로 정상 동작해야 한다.

        어댑터가 `.get()` 기반이라 필드 추가는 무해하다는 전제를 실측으로 고정한다(전제가
        깨지면 생산자 확장이 소비자를 조용히 죽인다).
        """
        adapted = vs.adapt_hit_cu_metrics(self._producer_report())
        assert "approval_rate_clean" not in adapted
        assert adapted["hit"]["sample_size"] == 3
