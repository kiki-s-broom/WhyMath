"""P3-61 선지 역추적 전용 kebab 4종 — 불변식·채널 격리·반례 정합·반사실 서빙 동결.

이 파일이 지키는 것
-------------------
정상 입력에서 초록인 것은 증거가 아니다. 이 부류(`choice_trace_only`)가 안전하다고 말하려면 막으려는
상태를 **실제로 넣고 RED가 되는지** 보여야 한다. 그래서

  1. 불변식 양방향 — `signals ≥ 1`은 부류 밖 전 항목에 그대로 유효하고, 부류 안은 본문 채널 재료가
     0이다. 어느 쪽을 어기는 항목을 만들면 구성 시점에 거부된다(주입). 구성자를 우회(`model_copy`)한
     객체에는 카탈로그 수준 검사가 대신 RED를 낸다(검사 자체의 변별력).
  2. 본문 채널 격리 — 신호 0건 항목이 `diagnose`·의미 매칭·정정 억제 평가·신호 포화 감사·pgvector 적재
     어디로든 새면 RED. 의미 매칭은 신호와 무관하게 `name_kr + canonical_statement`를 임베딩하므로
     가장 실질적인 누수 경로다. 각 격리는 필터가 없는 짝(대조군)에서 실제로 새는 것을 함께 확인한다.
  3. 반례 정합 — 반례는 가정 진술을 실제로 반증한다(SymPy, 반례 문자열과 독립 계산).
  4. 선지 채널 도달 — 격리가 채널을 죽이지 않았다. 오답 보기를 고르면 후보가 나온다.
  5. 반사실 서빙 — 서명이 났고 오답 보기가 새 kebab을 가리킨다면 P3-06 체인이 도는가(메모리 시뮬레이션,
     저장소 데이터는 불변). 서명이 없으면 보기를 바꿔도 served가 아니고, 정답 보기에 새 kebab을 달면 RED.

주입 표는 모듈이 아니라 이 파일이 **독립적으로** 정의한다.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
import sympy as sp
from pydantic import ValidationError

from whymath_backend.harness import explicit_correction_gap_eval as gap_eval
from whymath_backend.l1.misconception.crosslink_resolve import ResolvedLink
from whymath_backend.l1.standards.phase3_remediation_spec import FixtureRef, SignatureFixtures
from whymath_backend.l4.misconception import (
    BODY_CATALOG,
    CATALOG,
    CATALOG_BY_ID,
    CHOICE_TRACE_ONLY_IDS,
    Misconception,
    MisconceptionMatch,
    body_detectable,
    diagnose,
    distractor_link_candidates,
    select_intervention,
)
from whymath_backend.l4.misconception.audit import audit_catalog_coverage
from whymath_backend.l4.misconception.diagnose import _match_one
from whymath_backend.l4.misconception.distractor_link import DISTRACTOR_LINK_CONFIDENCE
from whymath_backend.l4.misconception.models import BODY_CHANNEL_FIELDS
from whymath_backend.l4.misconception.semantic import (
    FakeEmbeddingProvider,
    InMemoryVectorIndex,
    SemanticMatcher,
    catalog_text,
)
from whymath_backend.l4.misconception.semantic import pgvector_index as pgvector_mod
from whymath_backend.l4.misconception.validate import validate_distractor_map
from whymath_backend.ops import phase3_remediation as pr
from whymath_backend.schema.problem import DistractorEntry

#: 2026-10-17 Kiki 결정이 지정한 4개 개념의 kebab — 이 부류의 **전체 범위**다(독립 정의).
_EXPECTED: dict[str, str] = {
    "tangent-external-point-as-contact": "M0673",
    "mvt-conditions-unchecked": "M0674",
    "graph-sketch-few-points-only": "M0676",
    "velocity-sign-ignored": "M0678",
}
_TRACE_ONLY = sorted(_EXPECTED)


def _violations(m: Misconception) -> list[str]:
    """부류 불변식 위반 목록 — 모듈과 독립적으로 이 파일이 정의한다."""
    if m.choice_trace_only:
        present = [name for name in BODY_CHANNEL_FIELDS if getattr(m, name)]
        if m.ambiguous_regex_signals:
            present.append("ambiguous_regex_signals")
        return present
    return [] if m.signals else ["signals"]


def _base_kwargs(**over: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "id": "injected-item",
        "name_kr": "주입",
        "domain": "미적분",
        "canonical_statement": "주입된 가정",
        "counterexample": "주입된 반례",
        "signals": ("신호",),
    }
    kwargs.update(over)
    return kwargs


# ──────────────────────────────────────────────────────────────────────────
# 1. 불변식 — 양방향 동결
# ──────────────────────────────────────────────────────────────────────────
class TestInvariantBothDirections:
    def test_scope_is_exactly_the_four_decided_concepts(self) -> None:
        """이 부류를 넓히려면 새 결정이 필요하다 — 다섯 번째 항목이 조용히 들어오면 RED."""
        assert CHOICE_TRACE_ONLY_IDS == frozenset(_EXPECTED)
        assert {m.id for m in CATALOG if m.choice_trace_only} == set(_EXPECTED)

    def test_real_catalog_has_no_violation_in_either_direction(self) -> None:
        assert [(m.id, _violations(m)) for m in CATALOG if _violations(m)] == []

    def test_non_class_items_keep_the_signals_ge_one_invariant(self) -> None:
        """완화는 플래그 하나로 닫힌다 — 부류 밖은 68개 전부 신호가 1건 이상이다."""
        outside = [m for m in CATALOG if not m.choice_trace_only]
        assert len(outside) == 68
        assert all(len(m.signals) >= 1 for m in outside)

    def test_body_catalog_is_catalog_minus_class_in_original_order(self) -> None:
        assert BODY_CATALOG == tuple(m for m in CATALOG if m.id not in _EXPECTED)
        assert len(BODY_CATALOG) == len(CATALOG) - 4

    def test_body_detectable_filters_any_catalog_and_preserves_order(self) -> None:
        a = Misconception(**_base_kwargs(id="a-item"))
        t = Misconception(**_base_kwargs(id="t-item", signals=(), choice_trace_only=True))
        b = Misconception(**_base_kwargs(id="b-item"))
        assert body_detectable((a, t, b)) == (a, b)
        assert body_detectable((t,)) == ()

    def test_empty_signals_without_the_flag_is_rejected(self) -> None:
        """부류 밖에서 신호가 비면 구성 시점에 거부된다 — 신호가 우연히 비어 죽은 항목이 못 들어온다."""
        with pytest.raises(ValidationError, match="signals"):
            Misconception(**_base_kwargs(signals=()))

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("signals", ("신호",)),
            ("regex_signals", (r"\d+",)),
            ("refuting_regex", (r"틀리",)),
            ("canonical_wrong_form", ("a", "b")),
            ("correct_form", "정정"),
            ("ambiguous_regex_signals", True),
        ],
    )
    def test_body_channel_material_on_a_class_member_is_rejected(
        self, field: str, value: Any
    ) -> None:
        """부류 안에 본문 채널 재료가 하나라도 있으면 거부된다 — 두 채널이 섞이지 않는다."""
        kwargs = _base_kwargs(signals=(), choice_trace_only=True)
        kwargs[field] = value  # signals 케이스는 비어 있던 자리를 덮어쓴다
        with pytest.raises(ValidationError, match="본문 채널 재료"):
            Misconception(**kwargs)

    def test_valid_members_of_both_classes_construct(self) -> None:
        """성공 방향 대조군 — 과잉 거부(전부 실패로 계상)가 통과하지 못한다."""
        assert Misconception(**_base_kwargs()).signals == ("신호",)
        assert Misconception(**_base_kwargs(signals=(), choice_trace_only=True)).signals == ()

    def test_the_catalog_level_check_discriminates_constructor_bypass(self) -> None:
        """구성자를 우회한 객체(`model_copy`는 검증하지 않는다)는 카탈로그 수준 검사가 RED로 잡는다."""
        regular = CATALOG_BY_ID["power-rule-step-omitted"]
        member = CATALOG_BY_ID["velocity-sign-ignored"]
        bad_regular = regular.model_copy(update={"signals": ()})
        bad_member = member.model_copy(update={"signals": ("접선",)})
        assert bad_regular != regular and bad_member != member  # 주입이 실제로 적용됐다
        assert _violations(bad_regular) == ["signals"]
        assert _violations(bad_member) == ["signals"]
        # 대조군: 원본은 위반이 없다.
        assert _violations(regular) == [] and _violations(member) == []


# ──────────────────────────────────────────────────────────────────────────
# 2. 반례 정합 — 독립 계산
# ──────────────────────────────────────────────────────────────────────────
class TestCounterexamplesAreRealRefutations:
    """반례 문자열은 개입 발화에 그대로 들어가 학생에게 닿는다 — 거짓이면 학생에게 거짓을 말한다."""

    def test_tangent_line_through_external_point_misses_the_curve(self) -> None:
        x = sp.symbols("x", real=True)
        curve = x**2
        assert curve.subs(x, 1) != -3  # (1, -3)은 곡선 위의 점이 아니다
        slope_at_x1 = sp.diff(curve, x).subs(x, 1)
        assert slope_at_x1 == 2
        wrong_line = slope_at_x1 * (x - 1) + (-3)  # 그 점의 기울기로 (1,-3)을 지나는 직선 = 2x - 5
        assert sp.expand(wrong_line) == 2 * x - 5
        disc = sp.discriminant(sp.expand(curve - wrong_line), x)
        assert disc == -16 and disc < 0  # 만나는 점이 없다
        ce = CATALOG_BY_ID["tangent-external-point-as-contact"].counterexample
        assert "(1, −3)" in ce and "y=2x−5" in ce and "−16" in ce

    def test_mean_value_conclusion_fails_without_the_conditions(self) -> None:
        x = sp.symbols("x", real=True)
        f = sp.Abs(x)
        assert (f.subs(x, 1) - f.subs(x, -1)) / 2 == 0  # 평균변화율
        # 열린 구간 (-1, 1)에서 f' 는 x>0 이면 1, x<0 이면 -1 — 0이 되는 점이 없다(x=0 은 미분 불가).
        assert sp.diff(x, x) == 1 and sp.diff(-x, x) == -1
        left_slope = sp.limit(f / x, x, 0, "-")
        right_slope = sp.limit(f / x, x, 0, "+")
        assert left_slope != right_slope  # x=0 에서 미분 불가
        ce = CATALOG_BY_ID["mvt-conditions-unchecked"].counterexample
        assert "|x|" in ce and "[−1, 1]" in ce and "미분 불가" in ce

    def test_three_sample_points_lie_on_a_line_that_the_graph_leaves(self) -> None:
        x = sp.symbols("x", real=True)
        f = x**3 - 3 * x
        assert [(a, f.subs(x, a)) for a in (-2, 0, 2)] == [(-2, -2), (0, 0), (2, 2)]  # 모두 y=x 위
        assert f.subs(x, -1) == 2 and 2 > -1  # x=-1 에서 직선 값(-1)보다 위
        assert sorted(sp.solve(sp.diff(f, x), x)) == [-1, 1]  # 극점
        ce = CATALOG_BY_ID["graph-sketch-few-points-only"].counterexample
        assert "x³−3x" in ce and "y=x" in ce and "f(−1)=2" in ce

    def test_velocity_and_speed_differ_when_the_particle_moves_backward(self) -> None:
        t = sp.symbols("t", real=True)
        velocity = sp.diff(t**2 - 4 * t, t)
        assert velocity.subs(t, 1) == -2 and abs(velocity.subs(t, 1)) == 2
        ce = CATALOG_BY_ID["velocity-sign-ignored"].counterexample
        assert "t²−4t" in ce and "−2" in ce and "속력은 2" in ce

    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_counterexample_does_not_hand_over_the_procedure(self, kebab: str) -> None:
        """개입 발화에 그대로 닿는 문자열이라 정답식·올바른 절차를 적지 않는다(답 미루기)."""
        m = CATALOG_BY_ID[kebab]
        for text in (m.counterexample, m.canonical_statement):
            assert "정답" not in text and "올바른" not in text
        forbidden = {
            "tangent-external-point-as-contact": ("미지수로", "접점을 구"),
            "mvt-conditions-unchecked": ("롤의 정리",),
            "graph-sketch-few-points-only": ("증감표를",),
            "velocity-sign-ignored": ("v=2t", "2t−4"),
        }[kebab]
        for phrase in forbidden:
            assert phrase not in m.counterexample, (kebab, phrase)

    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_intervention_prompt_carries_both_strings(self, kebab: str) -> None:
        m = CATALOG_BY_ID[kebab]
        decision = select_intervention(MisconceptionMatch(misconception=m, confidence=0.9))
        assert decision is not None
        assert m.canonical_statement in decision.prompt
        assert m.counterexample in decision.prompt


# ──────────────────────────────────────────────────────────────────────────
# 3. 본문 채널 격리 — 신호 0건 항목이 새면 RED
# ──────────────────────────────────────────────────────────────────────────
def _texts_resembling(m: Misconception) -> list[str]:
    """학생이 본문에 적을 법한, 이 항목과 가장 닮은 글 — 누수가 있다면 여기서 샌다."""
    return [
        m.canonical_statement,
        m.counterexample,
        m.name_kr,
        f"{m.name_kr}. {m.canonical_statement}",
        f"{m.canonical_statement} {m.counterexample}",
    ]


class TestBodyChannelsNeverEmitTheClass:
    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_substring_regex_channel_never_returns_a_member(self, kebab: str) -> None:
        for text in _texts_resembling(CATALOG_BY_ID[kebab]):
            ids = {x.misconception.id for x in diagnose(text, top_k=100)}
            assert ids.isdisjoint(CHOICE_TRACE_ONLY_IDS), (text, ids)

    def test_the_class_rule_holds_even_if_a_signal_were_present(self) -> None:
        """'신호가 비어서 우연히 안 나온다'에 기대지 않는다 — 신호가 있어도 부류 규칙이 먼저 막는다."""
        base = CATALOG_BY_ID["tangent-external-point-as-contact"]
        text = "접선을 그었다"
        leaky = base.model_copy(update={"signals": ("접선",)})  # 구성자 우회 주입
        assert leaky.signals == ("접선",) and leaky.choice_trace_only
        assert _match_one(leaky, text) is None
        # 대조군: 같은 신호인데 플래그가 꺼져 있으면 실제로 발화한다 — 위 None 은 신호 부재가 아니다.
        control = leaky.model_copy(update={"choice_trace_only": False})
        found = _match_one(control, text)
        assert found is not None and found.confidence == 1.0

    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_semantic_channel_never_returns_a_member(self, kebab: str) -> None:
        """가장 실질적인 누수 경로 — 신호 없이도 name_kr+canonical_statement 가 임베딩된다."""
        provider = FakeEmbeddingProvider()
        matcher = SemanticMatcher(provider=provider)  # 기본 카탈로그 = 전체 CATALOG
        member = CATALOG_BY_ID[kebab]
        hits = matcher.match(catalog_text(member), top_k=100, threshold=-2.0)
        assert hits, "임계값을 -2 로 내려도 후보가 없다 — 이 테스트가 아무것도 시험하지 못한다"
        assert {h.misconception.id for h in hits}.isdisjoint(CHOICE_TRACE_ONLY_IDS)
        # 대조군: 본문 채널 항목은 자기 표현에 대해 자기 자신을 1순위로 돌려준다.
        body = BODY_CATALOG[0]
        top = matcher.match(catalog_text(body), top_k=1, threshold=-2.0)
        assert top and top[0].misconception.id == body.id

    def test_semantic_index_holds_only_body_items(self) -> None:
        index = InMemoryVectorIndex()
        SemanticMatcher(provider=FakeEmbeddingProvider(), index=index).match(
            "분모가 0", top_k=1, threshold=0.0
        )
        assert len(index) == len(BODY_CATALOG)

    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_a_preloaded_index_containing_a_member_still_cannot_emit_it(self, kebab: str) -> None:
        """두 번째 방어선 — 사전 적재 인덱스에 선지 전용 행이 섞여 있어도 후보로 나가지 않는다."""
        provider = FakeEmbeddingProvider()
        index = InMemoryVectorIndex()
        for m in CATALOG:  # 필터 없이 전부 적재 — 오염된 인덱스를 흉내 낸다
            index.add(m.id, provider.embed([catalog_text(m)])[0])
        assert len(index) == len(CATALOG)
        matcher = SemanticMatcher(provider=provider, index=index, prebuilt_index=True)
        member = CATALOG_BY_ID[kebab]
        hits = matcher.match(catalog_text(member), top_k=100, threshold=-2.0)
        assert hits and {h.misconception.id for h in hits}.isdisjoint(CHOICE_TRACE_ONLY_IDS)

    def test_pgvector_population_never_embeds_a_member(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[list[tuple[str, str]]] = []

        def spy(items: Any, **_: Any) -> int:
            captured.append(list(items))
            return len(items)

        monkeypatch.setattr(pgvector_mod, "embed_changed", spy)
        # embed_changed 가 가로채져 인덱스는 실제로 쓰이지 않지만, 인자 평가 시 두 속성은 읽힌다.
        fake_index = SimpleNamespace(
            existing_text_hashes=lambda keys: {}, upsert_entry=lambda *a: None
        )
        count = pgvector_mod.populate_pgvector(
            FakeEmbeddingProvider(),
            index=fake_index,  # type: ignore[arg-type]
            settings=SimpleNamespace(),  # type: ignore[arg-type]
        )
        assert len(captured) == 1 and count == len(BODY_CATALOG)
        keys = [k for k, _ in captured[0]]
        assert set(keys).isdisjoint(CHOICE_TRACE_ONLY_IDS)
        assert keys == [m.id for m in BODY_CATALOG]  # 적재 순서 규약(카탈로그 순서) 불변

    def test_correction_suppression_eval_skips_the_class(self) -> None:
        probes = gap_eval.build_probes()
        assert {p.kebab_id for p in probes}.isdisjoint(CHOICE_TRACE_ONLY_IDS)
        assert len(probes) == len(BODY_CATALOG)

    def test_signal_saturation_audit_skips_the_class(self) -> None:
        report = audit_catalog_coverage()
        assert {it.misconception_id for it in report.items}.isdisjoint(CHOICE_TRACE_ONLY_IDS)
        assert report.total == len(BODY_CATALOG)
        # 분모를 희석하지 않는다 — 신호 0 항목이 들어갔다면 이 비율이 내려갔을 것이다.
        assert report.signals_ge_min_rate == sum(
            1 for m in BODY_CATALOG if len(m.signals) >= 2
        ) / len(BODY_CATALOG)


# ──────────────────────────────────────────────────────────────────────────
# 4. 선지 채널 — 격리가 채널을 죽이지 않았다
# ──────────────────────────────────────────────────────────────────────────
class TestChoiceChannelStillReachesTheClass:
    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_choosing_the_labeled_wrong_option_yields_one_gated_candidate(self, kebab: str) -> None:
        dmap = [{"choice_index": 2, "misconception_id": kebab}]
        candidates = distractor_link_candidates(dmap, 2)
        assert [(c.misconception_id, c.confidence, c.gate_passed) for c in candidates] == [
            (kebab, DISTRACTOR_LINK_CONFIDENCE, True)
        ]
        # 대조군: 다른 보기를 고르거나 보기를 보고하지 않으면 후보가 없다.
        assert distractor_link_candidates(dmap, 1) == ()
        assert distractor_link_candidates(dmap, None) == ()

    @pytest.mark.parametrize("kebab", _TRACE_ONLY)
    def test_distractor_map_referential_integrity_accepts_the_class(self, kebab: str) -> None:
        """격리는 본문 채널 한정이다 — kebab 으로서의 존재(참조 무결성)는 그대로 인정된다."""
        assert (
            validate_distractor_map([DistractorEntry(choice_index=1, misconception_id=kebab)]) == []
        )
        # 대조군: 카탈로그에 없는 id 는 여전히 위반이다.
        assert validate_distractor_map(
            [DistractorEntry(choice_index=1, misconception_id="not-in-catalog")]
        )


# ──────────────────────────────────────────────────────────────────────────
# 5. 반사실 서빙 — 서명이 나고 보기가 새 kebab 을 가리킨다면
# ──────────────────────────────────────────────────────────────────────────
_KEBAB = "mvt-conditions-unchecked"
_MID = "M0674"


@pytest.fixture(scope="module")
def base() -> pr.Inputs:
    return pr.load_inputs()


@pytest.fixture(scope="module")
def base_report(base: pr.Inputs) -> pr.RemediationReport:
    return pr.evaluate(base)


def _row(report: pr.RemediationReport, mis_id: str) -> pr.MisconceptionRow:
    return next(r for r in report.rows if r.mis_id == mis_id)


def _relabel_raw_mid(
    base: pr.Inputs,
) -> tuple[dict[str, Any], list[tuple[str, int]], list[tuple[str, int]]]:
    """승인 문항의 raw `M0674` 보기를 새 kebab 으로 재라벨한 사본과 (오답, 정답) 픽스처 후보."""
    rows = copy.deepcopy(dict(base.rows))
    wrong: list[tuple[str, int]] = []
    correct: list[tuple[str, int]] = []
    for pid, row in sorted(rows.items()):
        hits = [e for e in row["distractor_map"] if e["misconception_id"] == _MID]
        if not hits:
            continue
        for entry in hits:
            entry["misconception_id"] = _KEBAB
        wrong.append((pid, hits[0]["choice_index"]))
        correct.append((pid, row["choices"].index(row["answer"])))
    return rows, wrong, correct


def _counterfactual(base: pr.Inputs, *, signed: bool) -> pr.Inputs:
    rows, wrong, correct = _relabel_raw_mid(base)
    assert len(wrong) >= 2, "재라벨할 승인 문항이 2건 미만이다 — 이 시뮬레이션은 성립하지 않는다"
    sig = SignatureFixtures(
        kebab_id=_KEBAB,
        channel="choice",
        wrong=tuple(FixtureRef(p, i) for p, i in wrong[:2]),
        correct=tuple(FixtureRef(p, i) for p, i in correct[:2]),
    )
    crosslinks = dict(base.crosslinks)
    if signed:
        crosslinks[_KEBAB] = (ResolvedLink(_MID, "직접매핑", 0.9),)
    mutated = replace(
        base,
        rows=rows,
        remediation=replace(base.remediation, signatures=(*base.remediation.signatures, sig)),
        crosslinks=crosslinks,
    )
    assert dict(mutated.rows) != dict(base.rows), "주입이 적용되지 않았다 — RED 를 신뢰할 수 없다"
    return mutated


class TestCounterfactualServing:
    def test_as_committed_nothing_is_served_through_the_class(
        self, base_report: pr.RemediationReport
    ) -> None:
        """서명 전에는 served 가 아니라 blocked 다 — pending 을 served 로 보고하지 않는다."""
        for mis_id in _EXPECTED.values():
            assert _row(base_report, mis_id).status is pr.RowStatus.BLOCKED, mis_id
        served_kebabs = {r.kebab_id for r in base_report.rows if r.status is pr.RowStatus.SERVED}
        assert served_kebabs.isdisjoint(CHOICE_TRACE_ONLY_IDS)

    def test_signed_and_relabeled_m0674_would_be_served_end_to_end(
        self, base: pr.Inputs, base_report: pr.RemediationReport
    ) -> None:
        report = pr.evaluate(_counterfactual(base, signed=True))
        row = _row(report, _MID)
        assert row.status is pr.RowStatus.SERVED and row.kebab_id == _KEBAB
        assert row.failures == ()
        e = row.evidence
        assert e is not None and e.wrong_checked >= 2 and e.correct_checked >= 1
        assert e.ladder == tuple(r.value for r in pr.EXPECTED_LADDER) and all(e.ladder_resolved)
        # 진척은 이 한 행뿐이다 — 다른 행의 상태는 그대로다("전부 좋아졌다"가 아니다).
        for r in report.rows:
            if r.mis_id != _MID:
                assert r.status is _row(base_report, r.mis_id).status, r.mis_id
        assert report.produced == base_report.produced + 1
        # 작동한 비율: 조용히 버려지던 raw M0674 12건이 후보가 된다(P3-57 이 보려던 간극).
        assert base_report.working.dropped_unknown.get(_MID, 0) == 12
        assert report.working.dropped_unknown.get(_MID, 0) == 0
        assert report.working.with_candidate == base_report.working.with_candidate + 12

    def test_relabeled_but_unsigned_is_still_blocked(self, base: pr.Inputs) -> None:
        """보기를 바꿔도 서명이 없으면 served 가 아니다 — 승인은 사람 전용이라 코드가 대신하지 못한다."""
        report = pr.evaluate(_counterfactual(base, signed=False))
        assert _row(report, _MID).status is pr.RowStatus.BLOCKED

    def test_labeling_the_correct_choice_with_the_new_kebab_is_red(self, base: pr.Inputs) -> None:
        """정답 보기를 새 kebab 으로 라벨하는 오탐 — 정답 픽스처가 RED 가 되어야 한다."""
        mutated = _counterfactual(base, signed=True)
        sig = next(s for s in mutated.remediation.signatures if s.kebab_id == _KEBAB)
        pid, correct_idx = sig.correct[0].problem_id, sig.correct[0].choice_index
        rows = copy.deepcopy(dict(mutated.rows))
        before = list(rows[pid]["distractor_map"])
        rows[pid]["distractor_map"] = [
            *before,
            {"choice_index": correct_idx, "misconception_id": _KEBAB},
        ]
        assert rows[pid]["distractor_map"] != before  # 주입이 적용됐다
        row = _row(pr.evaluate(replace(mutated, rows=rows)), _MID)
        assert row.status is pr.RowStatus.FAILED
        assert any("오탐" in f for f in row.failures)
