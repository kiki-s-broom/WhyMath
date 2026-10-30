"""P3-62 규칙 (가) — 풀이 끝 정답 변수 값 진술의 단위 계약(생성기 전체를 돌리지 않는다 · 빠름).

검증 축
-------
① `final_statement_steps` — 근 목록으로 끝난 연쇄 뒤에 '근 선택 → 정답 변수 값' 두 줄을 붙이고, 붙인 연쇄는
   공용 해석 판정(`verify_solution_interpreted`)에서 전 전이 correct다(GREEN).
② **정답 역산 금지** — 함수에 정답·answer_map을 넘기는 자리가 없고(시그니처 동결), 선택 근거(도메인 부등식)가
   없으면 후보가 둘 다 살아 None이다(정답을 보고 고르지 않는다). 근거가 *다른* 근을 가리키면 그 근의 값을
   진술한다 — 정답 기록과 다르면 `structured_view`가 저작 결함으로 멈춘다(반례).
③ 도메인 근거 도출 — 극소면 f''(x) > 0, 극대면 f''(x) < 0(명시 다항식).
④ `explicit_definitions` — 2계 도함수 정의(`Derivative(f, x, x).doit()`)를 명시 다항식으로 다시 쓰고, 다항식이
   아닌 정의는 그대로 둔다.
⑤ 구조화 모드 — 기본 꺼짐(승인 은행 바이트 불변), 블록 안에서만 켜지고 블록을 나가면 꺼진다.
⑥ 배치의 쓰기 자가거부 — 후보를 승인 은행 영역(`data/corpus` 아래 어디든 — 다른 배치의 은행 포함)에
   쓰려 하면 거부(사유 문자열·CLI exit 2·라이브러리 ValueError), 저장소 밖과 형제 디렉터리는 허용.
⑦ 빌드 시점 검증 — 구조화 조건이 깨진 문항은 *기본 모드* 빌드에서 멈춘다(후보 배치까지 숨지 않는다).
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import pytest

from whymath_backend.harness import p3_calculus1_diff_batch as batch
from whymath_backend.harness import p3_fill_batch as fill_batch
from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    P3DiffGraphShapeGenerator,
    ShapeItem,
    _kind_basis,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    final_step_structuring,
    final_step_structuring_enabled,
    structured_view,
)
from whymath_backend.l3.equivalent.p3_diff_solution_steps import (
    explicit_definitions,
    final_statement_steps,
)
from whymath_backend.l3.verify_solution import verify_solution_interpreted
from whymath_backend.schema.enums import AnswerFormat

# 실 은행 레코드(wm-p3-diff-graphshape-e6551214a538)의 수학 — f(x) = 2x^3 + ax^2 - 72x + 6, x = -3에서 극값,
# 극솟값을 묻는다(a = -3, 극소점 x = 4, 극솟값 -202).
_CHAIN = (
    "Derivative(2*x**3 + (-3)*x**2 - 72*x + 6, x).doit() = 0",
    "6*x**2 - 6*x - 72 = 0",
    "6*(x - 4)*(x + 3) = 0",
    "x = -3, x = 4",
)
_PIN = "Derivative(2*x**3 + a*x**2 - 72*x + 6, x).doit().subs(x, -3) = 0"
_CRIT = "Derivative(2*x**3 - 3*x**2 - 72*x + 6, x).doit() = 0"
_DEF = "y = 2*x**3 - 3*x**2 - 72*x + 6"
_MIN_BASIS = "12*x - 6 > 0"
_MAX_BASIS = "12*x - 6 < 0"


def _all_correct(steps: tuple[str, ...], conditions: tuple[str, ...]) -> bool:
    result = verify_solution_interpreted(list(steps), conditions=conditions).result
    return result.n_transitions >= 1 and result.n_correct == result.n_transitions


# ── ① 진술 GREEN ──────────────────────────────────────────────────────────
def test_statement_is_appended_and_proven_from_conditions() -> None:
    conditions = (_PIN, _CRIT, _MIN_BASIS, _DEF)
    out = final_statement_steps(_CHAIN, conditions=conditions, target="y")
    assert out == (*_CHAIN, "x = 4", "y = -202")
    assert _all_correct(out, conditions)


def test_single_candidate_gets_substitution_only() -> None:
    chain = ("Derivative(x**3 - 3*x, x).doit() = 0", "3*x**2 - 3 = 0", "x = -1, x = 1")
    conditions = ("Derivative(x**3 - 3*x, x).doit() = 0", "x > 0", "y = 6*x")
    out = final_statement_steps(chain, conditions=conditions, target="y")
    assert out == (*chain, "x = 1", "y = 6")
    # 후보가 하나뿐인 연쇄는 근 선택 줄 없이 대입 한 줄만 붙인다.
    one = ("Derivative(x**2 - 2*x, x).doit() = 0", "2*x - 2 = 0", "x = 1")
    assert final_statement_steps(
        one, conditions=("Derivative(x**2 - 2*x, x).doit() = 0", "y = 3*x"), target="y"
    ) == (*one, "y = 3")


# ── ② 정답 역산 금지 ─────────────────────────────────────────────────────
def test_signature_has_no_answer_channel() -> None:
    """선택에 정답을 쓸 통로가 없다 — 인자는 연쇄·조건·정답 *변수 이름*뿐이다."""
    params = set(inspect.signature(final_statement_steps).parameters)
    assert params == {"steps", "conditions", "target"}


def test_without_basis_both_candidates_survive_and_nothing_is_stated() -> None:
    """근거(도메인 부등식) 없이 정답 쪽 근을 '골라' 쓰지 않는다 — 후보 둘이 다 살면 None."""
    assert final_statement_steps(_CHAIN, conditions=(_PIN, _CRIT, _DEF), target="y") is None


def test_basis_picks_the_root_it_states_not_the_recorded_answer() -> None:
    """극대 근거를 주면 극대점(x = -3)의 값을 진술한다 — 정답 기록(x = 4)을 따라가지 않는다."""
    out = final_statement_steps(_CHAIN, conditions=(_PIN, _CRIT, _MAX_BASIS, _DEF), target="y")
    assert out is not None
    assert out[-2:] == ("x = -3", "y = 141")


def _item(structured: tuple[str, ...], answer: str, x: str) -> ShapeItem:
    return ShapeItem(
        slot="representative",
        frame_id="p362-test",
        question_text="(시험용) 함수 f(x) = 2x^3 + ax^2 - 72x + 6이 x = -3에서 극값을 가질 때 극솟값",
        answer_text=answer,
        explanation="(시험용)",
        conditions=(
            "y = 2*x**3 + a*x**2 - 72*x + 6",
            "Derivative(2*x**3 + a*x**2 - 72*x + 6, x).doit() = 0",
        ),
        answer_map=(("x", x), ("a", "-3"), ("y", answer)),
        problem_type_code="ptype.optimize-extremum",
        answer_format=AnswerFormat.실수,
        structured_conditions=structured,
    )


def test_structured_view_matches_recorded_answer() -> None:
    view = structured_view(_item((_PIN, _CRIT, _MIN_BASIS, _DEF), "-202", "4"))
    assert view is not None
    conditions, steps = view
    assert conditions == (_PIN, _CRIT, _MIN_BASIS, _DEF)
    assert steps[-2:] == ("x = 4", "y = -202")


def test_structured_view_refuses_when_stated_value_contradicts_record() -> None:
    """반례 — 근거가 정답 기록과 다른 근을 가리키면 조용히 종전 단계로 돌아가지 않고 멈춘다."""
    with pytest.raises(ValueError, match="저작 결함"):
        structured_view(_item((_PIN, _CRIT, _MAX_BASIS, _DEF), "-202", "4"))


def test_structured_view_refuses_unprovable_structured_conditions() -> None:
    """구조화 조건을 달았는데 근거가 빠져 증명이 안 되면 틀 설계 결함으로 멈춘다."""
    with pytest.raises(ValueError, match="증명하지 못했다"):
        structured_view(_item((_PIN, _CRIT, _DEF), "-202", "4"))


# ── ③ 도메인 근거 도출 ───────────────────────────────────────────────────
def test_kind_basis_is_second_derivative_sign() -> None:
    poly = ((3, 2), (2, -3), (1, -72), (0, 6))
    assert _kind_basis(poly, "min") == _MIN_BASIS
    assert _kind_basis(poly, "max") == _MAX_BASIS


# ── ④ 정의 등식 명시화 ───────────────────────────────────────────────────
def test_explicit_definitions_rewrites_second_derivative() -> None:
    conditions = (
        "y = Derivative(-2*x**3 - 3*x**2 + 12*x, x, x).doit()",
        "Derivative(-2*x**3 - 3*x**2 + 12*x, x).doit() = 0",
        "x > 0",
    )
    out = explicit_definitions(conditions, "y", "x")
    assert out == ("y = -12*x - 6", conditions[1], conditions[2])


def test_explicit_definitions_leaves_non_polynomial_alone() -> None:
    conditions = ("y = 1/(x - 2)", "x > 3")
    assert explicit_definitions(conditions, "y", "x") == conditions
    # 이미 허용 목록 꼴이면 그대로 둔다.
    assert explicit_definitions((_DEF,), "y", "x") == (_DEF,)


# ── ⑤ 모드 ───────────────────────────────────────────────────────────────
def test_mode_is_off_by_default_and_scoped() -> None:
    assert final_step_structuring_enabled() is False
    with final_step_structuring():
        assert final_step_structuring_enabled() is True
        with final_step_structuring(False):
            assert final_step_structuring_enabled() is False
        assert final_step_structuring_enabled() is True
    assert final_step_structuring_enabled() is False


# ── ⑥ 쓰기 자가거부 ──────────────────────────────────────────────────────
def test_structured_write_into_approved_area_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "data" / "corpus"
    own = root / batch.CORPUS_DIR_NAME
    other = root / fill_batch.CORPUS_DIR_NAME
    own.mkdir(parents=True)
    other.mkdir()
    # 자기 은행·다른 배치의 은행·영역 자체·하위 폴더·`..` 경유 — 전부 거부.
    for target in (own, other, root, own / "nested", root / "x" / ".." / batch.CORPUS_DIR_NAME):
        refusal = batch.refuses_structured_write(target, root)
        assert refusal is not None and "승인 은행" in refusal, target
    # 심볼릭 링크로 영역 안을 가리켜도 거부(문자열이 아니라 resolve 뒤 경로로 본다).
    link = tmp_path / "alias"
    link.symlink_to(other, target_is_directory=True)
    assert batch.refuses_structured_write(link, root) is not None
    # 대조군 — 저장소 밖·이름 접두만 같은 형제 디렉터리는 허용(과잉 거부 아님).
    assert batch.refuses_structured_write(tmp_path / "candidate", root) is None
    assert batch.refuses_structured_write(tmp_path / "data" / "corpus_candidate", root) is None


@pytest.fixture
def fake_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """가드가 회귀해도 *실제* 승인 은행을 덮지 않도록 기본 경로를 tmp로 돌린다."""
    root = tmp_path / "data" / "corpus"
    monkeypatch.setattr(batch, "_corpus_root", lambda: root)
    monkeypatch.setattr(batch, "_default_out_dir", lambda: root / batch.CORPUS_DIR_NAME)
    monkeypatch.setattr(fill_batch, "_default_out_dir", lambda: root / fill_batch.CORPUS_DIR_NAME)
    return root


@pytest.mark.parametrize("module", [batch, fill_batch])
def test_cli_refuses_structured_without_out_dir(
    module: object, fake_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--out-dir` 없이 구조화 후보를 쓰려 하면 생성 전에 exit 2(승인 은행 무변경)."""
    main = module.main  # type: ignore[attr-defined]
    assert main(["--structure-final-step"]) == 2
    assert "WRITE_REFUSED" in capsys.readouterr().err
    assert main(["--structure-final-step", "--check"]) == 2
    assert not list(fake_corpus.rglob("problems.jsonl"))


@pytest.mark.parametrize(
    ("module", "other_bank"),
    [(batch, fill_batch.CORPUS_DIR_NAME), (fill_batch, batch.CORPUS_DIR_NAME)],
)
def test_cli_refuses_structured_into_the_other_batchs_bank(
    module: object, other_bank: str, fake_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """교차 은행 — 한 배치가 *다른* 배치의 승인 은행 경로로 후보를 쓰려 해도 exit 2."""
    main = module.main  # type: ignore[attr-defined]
    target = fake_corpus / other_bank
    assert main(["--structure-final-step", "--out-dir", str(target)]) == 2
    assert "WRITE_REFUSED" in capsys.readouterr().err
    assert not (target / "problems.jsonl").exists()


def test_library_refuses_structured_write_into_approved_bank(fake_corpus: Path) -> None:
    """CLI 밖 라이브러리 호출(`out_path=None` → 기본 승인 은행)도 쓰기 전에 멈춘다."""
    with pytest.raises(ValueError, match="승인 은행"):
        batch.run_p3_calculus1_diff_batch(structure_final_step=True)
    with pytest.raises(ValueError, match="승인 은행"):
        fill_batch.run_p3_fill_batch(structure_final_step=True)
    with pytest.raises(ValueError, match="승인 은행"):
        batch.run_p3_calculus1_diff_batch(
            structure_final_step=True,
            out_path=fake_corpus / fill_batch.CORPUS_DIR_NAME / "problems.jsonl",
        )
    assert not list(fake_corpus.rglob("problems.jsonl"))


# ── ⑦ 빌드 시점 검증 ─────────────────────────────────────────────────────
def test_broken_structured_conditions_fail_the_default_mode_build() -> None:
    """구조화 조건이 깨진 문항은 모드를 켜지 않아도 슬롯 검증에서 멈춘다(결함이 숨지 않는다)."""
    assert final_step_structuring_enabled() is False
    for slot in P3DiffGraphShapeGenerator.slots:
        items = list(P3DiffGraphShapeGenerator.items(slot))
        index = next(
            (i for i, it in enumerate(items) if it.structured_conditions is not None), None
        )
        if index is None:
            continue
        good = items[index]
        assert good.structured_conditions is not None
        # 선택 근거(f'' 부호 부등식)를 빼면 두 후보가 다 살아 증명이 안 된다.
        broken = dataclasses.replace(
            good,
            structured_conditions=tuple(
                c for c in good.structured_conditions if ">" not in c and "<" not in c
            ),
        )
        assert broken.structured_conditions != good.structured_conditions  # 주입 실재
        P3DiffGraphShapeGenerator._validate_slot(slot, items)  # 대조군 — 원본은 통과
        items[index] = broken
        with pytest.raises(ValueError, match="규칙 \\(가\\) 구조화 실패"):
            P3DiffGraphShapeGenerator._validate_slot(slot, items)
        return
    pytest.fail("구조화 문항이 있는 슬롯 0건 — 이 검사가 공허하다")
