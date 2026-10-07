"""P3-03 미분 은행 감사자 자격 측정 — 은행 전용 결함 주입기 회귀 테스트(hermetic·LLM 0).

주입기(`l3/equivalent/p3_diff_defect_seeder`)가 지켜야 할 것:
  · 결정론 — 같은 seed·같은 은행이면 같은 시험지(초인간 검증 S4).
  · 구성 — 결함 120(7종·종류 할당량·종류마다 15건 이상) + 정상 120, 원본·정상이 서로 다른 은행 문항.
  · GT — 모든 결함이 실제로 적용됐고(변조본 ≠ 원본) GT가 성립하며, 의도하지 않은 기계 소견을
    만들지 않는다. 그리고 그 단언 장치 자체가 **실패를 주입하면 RED**다(보호 장치를 실패 주입 없이
    믿지 않는다 — CLAUDE.md).
  · 블라인드 — 정상 쪽이 결함 쪽의 (개념 × 객관식 여부) 분포를 그대로 따른다.
"""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l3.equivalent import p3_diff_defect_seeder as seeder
from whymath_backend.l3.equivalent.p3_diff_defect_seeder import (
    BANK_DEFECT_CLASSES,
    CLASS_QUOTAS,
    VARIANTS,
    GroundTruthError,
    SeededBankItem,
    build_qualification_set,
)

_BANK = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "corpus"
    / "problem_bank_p3_calculus1_diff_v0"
    / "problems.jsonl"
)
_VARIANT = {v.name: v for v in VARIANTS}


def _fingerprint(rows: Any) -> str:
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


@pytest.fixture(scope="module")
def bank() -> list[dict[str, Any]]:
    return [json.loads(line) for line in _BANK.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(scope="module")
def seeded(bank: list[dict[str, Any]]) -> list[SeededBankItem]:
    return build_qualification_set(bank)


@pytest.fixture(scope="module")
def by_id(bank: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(r["problem_id"]): r for r in bank}


# ── 구성 ────────────────────────────────────────────────────────────────
def test_quotas_are_kiki_design() -> None:
    assert sum(CLASS_QUOTAS.values()) == 120
    assert set(CLASS_QUOTAS) == set(BANK_DEFECT_CLASSES) and len(BANK_DEFECT_CLASSES) == 7
    assert min(CLASS_QUOTAS.values()) >= 15
    for cls in BANK_DEFECT_CLASSES:
        assert sum(v.quota for v in VARIANTS if v.defect_class == cls) == CLASS_QUOTAS[cls]


def test_set_composition(seeded: list[SeededBankItem]) -> None:
    defects = [i for i in seeded if i.is_defective]
    clean = [i for i in seeded if not i.is_defective]
    assert len(seeded) == 240 and len(defects) == 120 and len(clean) == 120
    assert Counter(str(i.defect_class) for i in defects) == Counter(CLASS_QUOTAS)
    assert Counter(str(i.variant) for i in defects) == Counter({v.name: v.quota for v in VARIANTS})


def test_sources_are_distinct_bank_items(seeded: list[SeededBankItem]) -> None:
    sources = [i.source_problem_id for i in seeded]
    assert len(set(sources)) == 240  # 결함 원본·정상 문항이 같은 은행 문항을 쓰지 않는다


def test_clean_items_are_unmodified_bank_records(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    for item in seeded:
        if not item.is_defective:
            assert _fingerprint(item.record) == _fingerprint(by_id[item.source_problem_id])


def test_clean_side_mirrors_defect_side_concept_and_format(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    def key(item: SeededBankItem) -> tuple[str, bool]:
        rec = by_id[item.source_problem_id]
        return rec["achievement_standard_codes"][0], rec["question_format"] == "객관식"

    defects = Counter(key(i) for i in seeded if i.is_defective)
    clean = Counter(key(i) for i in seeded if not i.is_defective)
    assert defects == clean
    concepts = Counter(c for (c, _), n in defects.items() for _ in range(n))
    assert max(concepts.values()) - min(concepts.values()) <= 1  # 개념별 결함 수가 고르다


def test_input_bank_is_not_mutated(bank: list[dict[str, Any]]) -> None:
    before = _fingerprint(bank)
    build_qualification_set(bank)
    assert _fingerprint(bank) == before


# ── 결정론 ──────────────────────────────────────────────────────────────
def test_same_seed_same_set(bank: list[dict[str, Any]], seeded: list[SeededBankItem]) -> None:
    again = build_qualification_set(bank)
    assert [(i.source_problem_id, i.variant, _fingerprint(i.record)) for i in again] == [
        (i.source_problem_id, i.variant, _fingerprint(i.record)) for i in seeded
    ]


def test_other_seed_other_set(bank: list[dict[str, Any]], seeded: list[SeededBankItem]) -> None:
    other = build_qualification_set(bank, seed=seeder.QUALIFICATION_SEED + 1)
    assert {i.source_problem_id for i in other} != {i.source_problem_id for i in seeded}


# ── GT·적용·부수 결함 ────────────────────────────────────────────────────
def test_every_defect_is_applied_true_and_side_effect_free(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    for item in seeded:
        if not item.is_defective:
            continue
        variant = _VARIANT[str(item.variant)]
        original = by_id[item.source_problem_id]
        assert _fingerprint(item.record) != _fingerprint(original), item.variant
        assert variant.check_gt(original, item.record), item.variant
        assert seeder._side_effects(variant, original, item.record) == [], item.variant
        assert item.gt_basis == variant.gt_basis and item.gate_overlap == variant.gate_overlap


def test_assertion_rejects_an_unapplied_injection(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    item = next(i for i in seeded if i.variant == "answer_and_map")
    original = by_id[item.source_problem_id]
    with pytest.raises(GroundTruthError, match="적용되지 않았다"):
        seeder._assert_applied_and_true(
            _VARIANT["answer_and_map"], original, copy.deepcopy(original)
        )


def test_assertion_rejects_a_mutation_whose_ground_truth_fails(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    """정답을 바꿨다고 기록했지만 실제로는 *참인 값*이면 GT 불성립 — 단언이 막는다."""
    item = next(i for i in seeded if i.variant == "answer_and_map")
    original = by_id[item.source_problem_id]
    forged = copy.deepcopy(item.record)
    key = next(k for k, v in original["verify"]["answer_map"].items() if v == original["answer"])
    forged["verify"]["answer_map"][key] = original["answer"]  # 검산 맵은 다시 참으로
    forged["tags"] = [*forged["tags"], "forged"]  # 적용 단언은 통과하게(바이트는 다르다)
    with pytest.raises(GroundTruthError, match="GT 불성립"):
        seeder._assert_applied_and_true(_VARIANT["answer_and_map"], original, forged)


def test_ambiguity_ground_truth_requires_the_phrase_to_be_gone(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    item = next(i for i in seeded if i.defect_class == "ambiguous_solution")
    original = by_id[item.source_problem_id]
    assert seeder._gt_ambiguous(original, item.record)
    assert not seeder._gt_ambiguous(original, original)  # 유일성 조건이 남아 있으면 GT 아님


def test_unrelated_choice_ground_truth_rejects_a_misconception_value(
    bank: list[dict[str, Any]],
) -> None:
    """오개념 절차 값과 같은 선지로 옮긴 것은 '그 오개념에서 나오지 않는 선지'가 아니다.

    시험지 픽스처를 거치지 않고 은행 레코드로 직접 본다 — GT 함수가 뒤집히면 시험지 빌드가 먼저
    멈춰(후보 0건) 이 단언까지 오지 못하는데, 그러면 *무엇이* 틀렸는지가 가려진다.
    """
    record = next(
        r
        for r in bank
        if r.get("distractor_map")
        and r["distractor_map"][0]["misconception_id"] == "power-rule-step-omitted"
        and seeder._unrelated_choice(r) is not None
    )
    index, values = seeder._unrelated_choice(record)  # type: ignore[misc]
    moved = copy.deepcopy(record)
    moved["distractor_map"][0]["choice_index"] = index
    assert seeder._gt_to_unrelated(record, moved)
    entries = record["distractor_map"]
    same = [e for e in entries if e["misconception_id"] == entries[0]["misconception_id"]]
    assert len(same) >= 2  # 거듭제곱 단계 누락은 두 절차 → 두 선지
    wrong = copy.deepcopy(record)
    wrong["distractor_map"][0]["choice_index"] = same[1]["choice_index"]  # 절차 값이 있는 선지
    assert record["choices"][same[1]["choice_index"]] in {str(v) for v in values}
    assert not seeder._gt_to_unrelated(record, wrong)


def test_misconception_model_matches_every_bank_power_rule_item(
    bank: list[dict[str, Any]],
) -> None:
    """⑥의 SymPy 오개념 절차 모형이 은행의 원 연결과 맞는다(모형이 틀리면 GT가 무너진다)."""
    checked = 0
    for rec in bank:
        entries = rec.get("distractor_map") or []
        if not entries or entries[0]["misconception_id"] != "power-rule-step-omitted":
            continue
        values = seeder._misconception_values(rec, "power-rule-step-omitted")
        if values is None:
            continue  # 단일 등식 미분계수 조건이 아닌 문항(모형 범위 밖 — 변이 후보에서도 빠진다)
        for entry in entries:
            text = rec["choices"][entry["choice_index"]]
            assert seeder._rational(text) is not None
            assert any(str(v) == text for v in values), (rec["problem_id"], text, values)
            checked += 1
    assert checked >= 30


def test_point_change_ground_truth_requires_verify_untouched(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    item = next(i for i in seeded if i.variant == "point_changed")
    original = by_id[item.source_problem_id]
    assert seeder._gt_point_changed(original, item.record)
    tampered = copy.deepcopy(item.record)
    tampered["verify"]["answer_map"] = {k: "0" for k in tampered["verify"]["answer_map"]}
    assert not seeder._gt_point_changed(original, tampered)


def test_side_effect_guard_flags_an_unintended_josa_error(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    """점만 바꿀 생각이었는데 조사가 틀리게 되면('f'(-2)를' → 'f'(-1)를') 부수 결함으로 잡는다."""
    item = next(i for i in seeded if i.variant == "point_changed")
    original = by_id[item.source_problem_id]
    broken = copy.deepcopy(item.record)
    broken["question_text"] += " 3를 보라."  # '3'(삼)은 받침이 있어 '을'이 맞다
    assert "josa_token" in seeder._side_effects(_VARIANT["point_changed"], original, broken)


def test_paraphrase_shortcut_evades_the_guard_but_its_twin_does_not(
    seeded: list[SeededBankItem], by_id: dict[str, dict[str, Any]]
) -> None:
    """판정기 밖 어휘 변형은 판정기를 통과하고(과적합 측정의 재료), 판정기 어휘 쌍둥이는 걸린다."""
    for name, canonical, rule in (
        ("avg_rate_paraphrase", "avg_rate_given", "T06-given-rate"),
        ("critical_points_paraphrase", "critical_points_given", "T08-given-critical-points"),
        ("minimizer_paraphrase", "minimizer_given", "T09-pinned-minimizer"),
        ("zero_monomial_paraphrase", "zero_monomial", "T-zero-monomial"),
    ):
        item = next(i for i in seeded if i.variant == name)
        original = by_id[item.source_problem_id]
        assert rule not in seeder._guard_rules(item.record), name
        twin = _VARIANT[canonical].mutate(original)
        assert twin is not None and rule in seeder._guard_rules(twin[0]), name


def test_hints_use_the_banks_own_condition_style(seeded: list[SeededBankItem]) -> None:
    """단서는 은행 관례 꼴 '(단, …)'로만 붙는다 — 은행에 없는 꼴('(참고:')은 결함 표지가 된다."""
    assert not any("참고" in str(i.record["question_text"]) for i in seeded)
    hinted = [
        i
        for i in seeded
        if i.defect_class == "derivative_shortcut" and "(단," in i.record["question_text"]
    ]
    assert len(hinted) == 14  # ③ 17건 중 단항식 x = 0 계열 3건만 발문을 바꿔 쓴다
    assert all(i.record["question_text"].count("(단") == 1 for i in hinted)


def test_pool_exhaustion_raises_instead_of_a_partial_set(bank: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="부족"):
        build_qualification_set(bank[:60])
