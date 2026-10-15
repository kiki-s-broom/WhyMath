"""대표 과정 실 코퍼스의 문제 메타데이터 7필드·슬롯 래칫 — P3-04 (CI 쪽 집행).

이 파일이 하는 일은 **올라가기만 하는 하한**을 거는 것이다. 정확한 수치(예: 슬롯 47/60)는 고정하지
않는다 — P3-05 가 채울 때마다 바뀌는 값이라 고정하면 정당한 진척이 테스트 실패가 된다
(`test_phase3_coverage.py` 모듈 docstring 의 원칙). 대신 "이미 확보한 것이 줄어들면 RED" 를 건다.

왜 CLI 가 아니라 테스트인가: `phase3_coverage` CLI 는 Concept Completeness 목표 미달로 지금도 exit 1
이라 CI 게이트로 쓸 수 없다. 이 파일은 그 CLI 가 내는 새 두 축(7필드·슬롯)만 따로 잠근다.

무엇을 잠그는가 (기준 시점 main: 적격 문항 917건 · 슬롯 47/60 — P3-05 3단계 기존 문항 재배정 · 결손 0건)
  ① 적격 문항 수 하한 — 문항이 범위 밖으로 빠지면(개념 태그가 사라지면) 조용히 분모가 줄어든다.
  ② 파일로 측정 가능한 6필드의 결손 0 — 하나라도 비우면 발행 게이트가 거부할 문항이 생긴 것이다.
  ③ 측정 불가 필드는 `hint_strategy` 하나뿐 — 다른 필드가 몰래 측정 불가로 바뀌면 RED.
  ④ 알 수 없는 슬롯 태그 0 — 오타 난 태그는 그 문항을 슬롯 없는 문항으로 보이게 한다.
  ⑤ 슬롯 충족 칸 수 하한(47) · 오개념 유발 태그 문항은 전부 문항 자체 오개념 연결을 가진다.

각 잠금은 실 코퍼스 문항 하나를 실제로 깨뜨리는 주입으로 변별력을 확인한다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.schema.problem_metadata import (
    EMPTY_DIFFICULTY,
    ProblemMetadataField,
    ProblemSlot,
    parse_slot_tags,
    slot_tag,
)

#: 기준 시점(P3-04) 하한. 올리는 것은 정당한 진척이고 내리는 것은 퇴보다 — 내릴 때는 사유를 PR 에 적는다.
ELIGIBLE_PROBLEMS_FLOOR = 917
FILLED_SLOT_CELLS_FLOOR = 47

_F = ProblemMetadataField


@pytest.fixture(scope="module")
def spec() -> ps.ScopeSpec:
    return ps.load_scope_spec()


@pytest.fixture(scope="module")
def index(spec: ps.ScopeSpec) -> ps.ReferenceIndex:
    return ps.load_reference_index(spec)


@pytest.fixture(scope="module")
def corpus(spec: ps.ScopeSpec) -> pc.CoverageCorpus:
    return pc.load_corpus(spec)


@pytest.fixture(scope="module")
def report(spec: ps.ScopeSpec, index: ps.ReferenceIndex, corpus: pc.CoverageCorpus) -> Any:
    return pc.evaluate(spec, index, corpus)


def _eligible(corpus: pc.CoverageCorpus) -> list[pc.ProblemRef]:
    """적격(approved) 문항 — 범위 안 문항은 `load_corpus` 가 이미 걸렀다."""
    return [p for p in corpus.problems if p.review_status == pc.PROBLEM_ELIGIBLE_STATUS]


# ── ① 분모 ───────────────────────────────────────────────────────────────────
def test_eligible_population_does_not_shrink(report: Any) -> None:
    stats = report.problem_metadata
    assert stats is not None
    assert stats.population >= ELIGIBLE_PROBLEMS_FLOOR, (
        f"적격 문항이 {stats.population}건으로 줄었다(하한 {ELIGIBLE_PROBLEMS_FLOOR}) — "
        "개념 태그가 사라졌거나 검수 상태가 내려간 문항이 있다"
    )


# ── ② 파일로 측정 가능한 6필드: 결손 0 ─────────────────────────────────────────────
def test_no_eligible_problem_has_a_blank_measurable_field(report: Any) -> None:
    stats = report.problem_metadata
    assert stats is not None
    assert stats.unmet == (), [(u.subject, u.missing) for u in stats.unmet[:5]]
    for name, count in stats.field_counts.items():
        assert count["missing"] == 0, name


# ── ③ 측정 불가 필드는 hint_strategy 뿐 ────────────────────────────────────────────
def test_only_the_hint_field_may_be_unmeasured(report: Any) -> None:
    stats = report.problem_metadata
    assert stats is not None
    assert set(stats.unmeasured_fields) <= {_F.HINT_STRATEGY.value}, stats.unmeasured_fields
    for name, count in stats.field_counts.items():
        if name != _F.HINT_STRATEGY.value:
            assert count["unknown"] == 0, f"{name} 이(가) 몰래 측정 불가가 됐다"


# ── ④ 슬롯 태그 정합 ─────────────────────────────────────────────────────────────
def test_every_slot_tag_in_scope_is_a_known_slot(corpus: pc.CoverageCorpus) -> None:
    unknown = sorted({t for p in corpus.problems for t in parse_slot_tags(p.tags).unknown})
    assert unknown == [], unknown


# ── ⑤ 슬롯 충족 ──────────────────────────────────────────────────────────────────
def test_filled_slot_cells_do_not_regress(report: Any) -> None:
    assert report.slots is not None
    assert report.slots.population == 60
    assert (
        report.slots.met_count >= FILLED_SLOT_CELLS_FLOOR
    ), f"채워진 슬롯 칸이 {report.slots.met_count}로 줄었다(하한 {FILLED_SLOT_CELLS_FLOOR})"


def test_every_trigger_tagged_problem_has_its_own_signature(
    spec: ps.ScopeSpec, corpus: pc.CoverageCorpus
) -> None:
    """오개념 유발 슬롯 태그가 달린 적격 문항은 문항 자체의 오개념 연결이 있어야 한다."""
    del spec
    trigger = [
        p
        for p in _eligible(corpus)
        if ProblemSlot.MISCONCEPTION_TRIGGER in parse_slot_tags(p.tags).slots
    ]
    assert trigger, "오개념 유발 슬롯 문항이 0건이다 — 이 검사가 공허하게 통과한다"
    without = [p.problem_id for p in trigger if not pc._reached_misconceptions(p, corpus)]
    assert without == [], without[:5]


# ── 변별력: 실 코퍼스 문항 하나를 실제로 깨뜨리면 위 잠금이 RED 가 된다 ────────────────
def _break_one(corpus: pc.CoverageCorpus, field: ProblemMetadataField) -> pc.CoverageCorpus:
    """적격 문항 하나의 한 필드를 비운다. 오개념은 오개념 유발 슬롯 문항에서 지운다."""
    pool = _eligible(corpus)
    if field is _F.MISCONCEPTION_SIGNATURE:
        target = next(
            p
            for p in pool
            if ProblemSlot.MISCONCEPTION_TRIGGER in parse_slot_tags(p.tags).slots
            and pc._reached_misconceptions(p, corpus)
        )
        changes: dict[str, Any] = {"distractor_ids": ()}
    else:
        target = pool[0]
        changes = {
            _F.DIFFICULTY: {"difficulty": EMPTY_DIFFICULTY},
            _F.SKILL: {"problem_type_codes": ()},
            _F.SOLUTION: {"solution_text": ""},
            _F.ANSWER: {"answer": ""},
        }[field]
    new = replace(target, **changes)
    assert new != target, "주입이 적용되지 않았다 — 실 코퍼스 문항이 이미 그 상태였다"
    broken = replace(corpus, problems=tuple(new if p is target else p for p in corpus.problems))
    assert broken != corpus
    return broken


@pytest.mark.parametrize(
    "field",
    [f for f in ProblemMetadataField if f not in (_F.CONCEPT, _F.HINT_STRATEGY)],
    ids=lambda f: f.value,
)
def test_breaking_one_real_problem_trips_the_ratchet(
    spec: ps.ScopeSpec, index: ps.ReferenceIndex, corpus: pc.CoverageCorpus, field: Any
) -> None:
    broken = _break_one(corpus, field)
    stats = pc.evaluate(spec, index, broken).problem_metadata
    assert stats is not None
    assert len(stats.unmet) == 1, "결손 문항 하나가 목록에 나타나야 한다"
    assert stats.field_counts[field.value]["missing"] == 1
    assert stats.unmet[0].missing == (f"{field.value}: 비어 있다",)


def test_removing_a_real_problems_concept_tag_shrinks_the_population(
    spec: ps.ScopeSpec, index: ps.ReferenceIndex, corpus: pc.CoverageCorpus
) -> None:
    """concept 필드의 코퍼스 쪽 결손은 분모 감소로 나타난다 — ①의 하한이 그것을 잡는다."""
    target = _eligible(corpus)[0]
    new = replace(target, primary_src_ids=frozenset())
    assert new != target
    broken = replace(corpus, problems=tuple(new if p is target else p for p in corpus.problems))
    before = pc.evaluate(spec, index, corpus).problem_metadata
    after = pc.evaluate(spec, index, broken).problem_metadata
    assert before is not None and after is not None
    assert after.population == before.population - 1


def test_untagging_every_trigger_problem_of_one_concept_drops_a_cell(
    spec: ps.ScopeSpec, index: ps.ReferenceIndex, corpus: pc.CoverageCorpus
) -> None:
    """슬롯 칸이 실제로 채워진 개념에서 그 슬롯 문항의 태그를 전부 걷으면 지표가 떨어진다."""
    base = pc.evaluate(spec, index, corpus)
    assert base.slots is not None
    # 채워진 (개념, 슬롯) 칸 하나를 골라 그 슬롯 태그를 가진 그 개념의 적격 문항 태그를 지운다.
    unmet = {u.subject: u.missing for u in base.slots.unmet}
    target_concept = next(c for c in spec.core_concepts if c.code not in unmet)
    tagged = [
        p
        for p in _eligible(corpus)
        if target_concept.source_id in p.primary_src_ids
        and ProblemSlot.BASIC in parse_slot_tags(p.tags).slots
    ]
    assert tagged, "고른 개념에 기본 슬롯 문항이 없다 — 이 검사가 공허하다"
    rewritten = {
        id(p): replace(p, tags=tuple(t for t in p.tags if t != slot_tag(ProblemSlot.BASIC)))
        for p in tagged
    }
    broken = replace(corpus, problems=tuple(rewritten.get(id(p), p) for p in corpus.problems))
    assert broken != corpus
    after = pc.evaluate(spec, index, broken)
    assert after.slots is not None
    assert after.slots.met_count == base.slots.met_count - 1
