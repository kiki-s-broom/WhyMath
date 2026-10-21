"""P3-10 평가셋 — 커밋본이 결정론 생성 규칙의 산출과 바이트 동일한가 · 적재가 위반을 통과로 접지 않는가.

평가셋은 데이터 파일로 버전 관리하되 진실 원천은 *규칙*이다. 손 편집이나 코퍼스 표류(문항 삭제·승인
취소·distractor_map 변경)가 생기면 이 파일의 첫 테스트가 RED가 되고, 적재는 참조 위반을 모아 실패한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.ai_quality_eval_set import (
    DEFAULT_EVAL_SET,
    HINT_LEVEL_SIGNALS,
    KIND_CHOICE,
    KIND_HINT,
    EvalSetError,
    build_cases,
    dump_cases,
    load_eval_set,
    parse_cases,
)
from whymath_backend.harness.ai_quality_registry import (
    Registry,
    RegistryError,
    default_repo_root,
    load_registry,
)
from whymath_backend.l4.hint_deferral import decide_hint_level
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / DEFAULT_EVAL_SET


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry()


def test_repo_root_resolves_to_this_checkout() -> None:
    assert default_repo_root() == REPO


def test_committed_eval_set_equals_rule_output(registry: Registry) -> None:
    """커밋본 = 규칙 산출(바이트 동일). 다르면 `--build-eval-set`으로 다시 만들고 차이를 검토한다."""
    built = dump_cases(build_cases(registry))
    committed = COMMITTED.read_text(encoding="utf-8")
    assert committed == built


def test_counts_cover_every_axis_minimum(registry: Registry) -> None:
    es = load_eval_set(registry)
    hint = [c for c in es.cases if c.kind == KIND_HINT]
    choice = [c for c in es.cases if c.kind == KIND_CHOICE]
    assert len(hint) == 180  # 10개념 × 6문항 × 3턴
    assert {c.concept_id for c in hint} == registry.scope_concepts
    assert len({c.ladder_id for c in hint}) == 60
    assert len(choice) >= 60
    assert sum(c.verdict == "incorrect" for c in choice) >= 30
    assert sum(c.verdict == "correct" for c in choice) >= 20
    assert all(
        c.expected_misconception_id in CATALOG_BY_ID for c in choice if c.verdict == "incorrect"
    )
    assert all(c.expected_misconception_id is None for c in choice if c.verdict == "correct")


def test_ladder_signals_match_engine() -> None:
    for level, signals in HINT_LEVEL_SIGNALS.items():
        got = decide_hint_level(
            student_input=signals.student_input,
            turn_count=signals.turn_count,
            prev_hint_level=signals.prev_hint_level,
        )
        assert got == level


def test_cases_carry_no_problem_text(registry: Registry) -> None:
    """평가셋은 id·라벨만 담는다 — 문항 본문·정답·풀이가 들어가면 진실 원천이 둘이 된다."""
    for line in COMMITTED.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        assert not {"question_text", "answer", "solution_steps", "choices"} & set(row)


def test_materials_resolve_from_corpus(registry: Registry) -> None:
    es = load_eval_set(registry)
    for case in es.cases:
        m = es.materials[case.problem_id]
        assert m.answer
        if case.kind == KIND_HINT:
            assert case.target_step is not None and case.target_step < len(m.solution_steps)
            assert m.conditions
        else:
            assert case.selected_choice_index is not None
            assert 0 <= case.selected_choice_index < len(m.choices)


# ──────────────────────────────────────────────────────────────────────────
# 엄격 적재 — 위반 주입
# ──────────────────────────────────────────────────────────────────────────
def _first_rows() -> list[dict[str, object]]:
    return [json.loads(line) for line in COMMITTED.read_text(encoding="utf-8").splitlines()[:6]]


def _text(rows: list[dict[str, object]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def test_parse_roundtrip() -> None:
    rows = _first_rows()
    cases = parse_cases(_text(rows))
    assert dump_cases(cases) == "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows[0].update(schema="other/v1"),
        lambda rows: rows[0].update(kind="essay"),
        lambda rows: rows[1].update(case_id=rows[0]["case_id"]),
        lambda rows: rows[0].update(verdict="maybe"),
        lambda rows: rows[0].update(student_band="유치원"),
        lambda rows: rows[0].update(answer_known_to_student=1),
        lambda rows: rows[0].update(target_step=True),
        lambda rows: rows.pop(1),  # 사다리 위치 결손(1, 3)
        lambda rows: rows.clear(),
    ],
    ids=[
        "schema",
        "kind",
        "dup-id",
        "verdict",
        "band",
        "bool-type",
        "bool-int",
        "ladder-gap",
        "empty",
    ],
)
def test_parse_rejects_violations(mutate) -> None:
    rows = _first_rows()
    before = _text(rows)
    mutate(rows)
    assert _text(rows) != before  # 주입이 실제로 적용됐다
    with pytest.raises(EvalSetError):
        parse_cases(_text(rows))


def test_choice_case_without_label_is_rejected() -> None:
    rows = [
        json.loads(line)
        for line in COMMITTED.read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == KIND_CHOICE
    ][:1]
    del rows[0]["expected_misconception_id"]
    with pytest.raises(EvalSetError, match="라벨"):
        parse_cases(_text(rows))


def test_load_rejects_unknown_problem(registry: Registry, tmp_path: Path) -> None:
    rows = _first_rows()[:3]
    for r in rows:
        r["problem_id"] = "00000000-0000-0000-0000-000000000000"
    path = tmp_path / "eval.jsonl"
    path.write_text(_text(rows), encoding="utf-8")
    with pytest.raises(EvalSetError, match="코퍼스에 없다"):
        load_eval_set(registry, path)


def test_load_rejects_concept_outside_scope(registry: Registry, tmp_path: Path) -> None:
    rows = _first_rows()[:3]
    for r in rows:
        r["concept_id"] = "math.calculus.bujeongjeokbunui-tteut"
    path = tmp_path / "eval.jsonl"
    path.write_text(_text(rows), encoding="utf-8")
    with pytest.raises(EvalSetError, match="대표 과정 밖"):
        load_eval_set(registry, path)


def test_missing_file_is_measurement_failure(registry: Registry, tmp_path: Path) -> None:
    with pytest.raises(EvalSetError):
        load_eval_set(registry, tmp_path / "nope.jsonl")


def test_registry_missing_corpus_is_measurement_failure(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(tmp_path)
