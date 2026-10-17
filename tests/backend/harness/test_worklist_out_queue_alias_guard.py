"""OPS-147 — `--worklist-out`이 검수 큐 정본과 같은 파일이면 호출 0건에서 거부한다(hermetic).

**무엇을 막는가**: 회차 끝의 `worklist_path.write_text(...)`는 파일 *전체*를 덮어쓴다. 뷰 경로를
큐 정본 `<out>.review.jsonl`과 같게 주면 그 쓰기가 JSONL 정본을 마크다운 뷰로 바꾼다. EOS-121
회차(`--out anthropic.jsonl --worklist-out anthropic.review.jsonl`)가 실제로 그랬고, 비수용 후보의
구조화 payload가 소실됐다. 코드에는 두 경로의 동치를 막는 장치가 없었다.

**왜 호출 0건에서 막는가**: 소실은 되돌릴 수 없고 호출은 비싸다(EOS-121 90호출). 돌린 *뒤에야*
정본이 사라진 것을 알면 가드가 아니라 부고다.

**검증 방식 — 두 층**:
  1. 시나리오를 실물 모듈에 돌려 *통과*를 확인한다(거부 5종 + 대조군 3종).
  2. 같은 시나리오를 *소스를 메모리에서 한 절씩 변형한 모듈*에 돌려 **각 변형이 정확히 기대한
     시나리오만 RED로 만드는지** 확인한다. 정상 입력에서 초록인 것은 보호의 증거가 아니다
     (CLAUDE.md 「보호 장치를 실패 주입 없이 "보호 있음"으로 선언 금지」).

하네스의 약속(이 파일이 위장이 되지 않도록 — OPS-139 `test_atom_graph_prod_parity_mutation.py` 동형):
  ① 주입이 실제로 적용됐다 — 치환 대상이 정확히 1건이고 `mutated != original`.
  ② 원복이 바이트 동일하다 — 실파일은 한 번도 쓰지 않는다(메모리 로드). 전후 sha256을 단언한다.
  ③ 각 변형이 *의도한 절*을 밟았다 — RED 여부만이 아니라 *어느 시나리오가* RED인지 기대 집합과
     대조한다. 전건 RED는 커버리지의 증거가 아니다.
"""

from __future__ import annotations

import hashlib
import ntpath
import os
import sys
import types
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from whymath_backend.harness import problem_corpus_accumulate as real_module
from whymath_backend.harness.problem_corpus_accumulate import worklist_aliases_review_queue
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.models import GenerationResult, RoutingDecision, Usage
from whymath_backend.schema.enums import Subject

_SRC = Path(real_module.__file__)

# 큐 정본 모사 — 로더가 읽지 않으므로 형태는 자유지만, *바이트가 보존되는지*만 본다.
_QUEUE_SEED = '{"status": "needs_review", "note": "정본 한 줄 — 덮어쓰이면 안 된다"}\n'
_NON_JSON_RESPONSE = "이번 턴은 유효한 JSON 응답이 아님)))"


# ──────────────────────────────────────────────────────────────────────────
# 대역 — 유일한 가짜는 LLM 호출부 하나
# ──────────────────────────────────────────────────────────────────────────
class _ScriptedProvider:
    """대본 provider. 소진 시 IndexError(대본 밖 호출을 숨기지 않는다)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        out = self._responses[self._index]
        self._index += 1
        return GenerationResult(
            out, usage=Usage(input_tokens=50, output_tokens=120, latency_ms=42.0)
        )


def _forbid_generator(monkeypatch: pytest.MonkeyPatch, module: types.ModuleType) -> list[int]:
    """생성기 조립 도달 = 가드가 호출 전에 못 막았다는 뜻 — 조립 시도 횟수를 센다."""
    reached: list[int] = []

    def _build(*_args: object, **_kwargs: object) -> object:
        reached.append(1)
        raise AssertionError("생성기 조립에 도달했다 — 가드가 호출 0건에서 막지 못했다")

    monkeypatch.setattr(module, "_build_live_generator", _build)
    return reached


def _scripted_generator(monkeypatch: pytest.MonkeyPatch, module: types.ModuleType) -> None:
    """대조군용 — 실물 생성기 조립에 provider만 대본(비JSON 1건 → generation_failed 1행)."""
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID

    def _build(
        topic_hint: str, *, generation_log_sink: object = None, **_routing: object
    ) -> LLMEquivalentProblemGenerator:
        return LLMEquivalentProblemGenerator(
            _ScriptedProvider([_NON_JSON_RESPONSE]),  # type: ignore[arg-type]
            misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
            topic_hint=topic_hint,
            subject=Subject.공통,
            slug_prefix="wm-gen-ops147",
            generation_log_sink=generation_log_sink,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(module, "_build_live_generator", _build)


def _snapshot(root: Path) -> dict[str, bytes]:
    """디렉터리 전체의 (상대경로 → 바이트) — 거부 시 *어떤 파일도* 안 바뀌었음을 대조한다."""
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def _first_non_space(path: Path) -> str:
    """정본이 JSONL로 남았는지 보는 자가검증 — 첫 비공백 문자가 `{`면 JSONL이다."""
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    return stripped[:1]


# ──────────────────────────────────────────────────────────────────────────
# 시나리오 — 모듈 `m`을 받아 기대 거동을 단언한다(통과 = 정상 return)
# ──────────────────────────────────────────────────────────────────────────
Scenario = Callable[[types.ModuleType, Path, pytest.MonkeyPatch, pytest.CaptureFixture[str]], None]


def _expect_refused(
    m: types.ModuleType,
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv_tail: list[str],
    *,
    seed_queue: bool,
) -> None:
    """공통 거부 단언 — exit 2 · 두 경로가 사유에 · 어떤 파일도 안 바뀜 · 생성기 미도달."""
    out = base / "acc.jsonl"
    queue = base / "acc.review.jsonl"
    if seed_queue:
        queue.write_text(_QUEUE_SEED, encoding="utf-8")
    before = _snapshot(base)
    reached = _forbid_generator(monkeypatch, m)
    capsys.readouterr()
    code = m.main(["--out", str(out), "--n", "1", *argv_tail])
    err = capsys.readouterr().err
    assert code == 2, f"exit 2여야 한다(받은 값 {code})"
    assert not reached, "거부 회차가 생성기 조립에 도달했다"
    assert str(queue.resolve()) in err, "사유에 큐 정본 경로가 없다"
    assert "--worklist-out" in err and "검수 큐 정본" in err
    assert _snapshot(base) == before, "거부 회차가 파일을 쓰거나 바꿨다"
    assert not out.exists(), "거부 회차가 코퍼스 산출물을 만들었다"


def _scn_same_path(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """EOS-121 사고 그대로 — 정본이 *아직 없는* 첫 회차에서 뷰=정본 경로."""
    base = tmp_path / "same_path"
    base.mkdir()
    _expect_refused(
        m, base, monkeypatch, capsys,
        ["--worklist-out", str(base / "acc.review.jsonl")],
        seed_queue=False,
    )  # fmt: skip


def _scn_relative_vs_absolute(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """상대 경로 ↔ 절대 경로 동치 — 정본이 없을 때도 *문자열 해석*만으로 잡혀야 한다."""
    base = tmp_path / "relative"
    base.mkdir()
    monkeypatch.chdir(base)
    _expect_refused(
        m, base, monkeypatch, capsys,
        ["--worklist-out", "acc.review.jsonl"],
        seed_queue=False,
    )  # fmt: skip


def _scn_dotdot(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """`..` 우회 — `sub/../acc.review.jsonl`. 정본이 없어야 resolve 절만 밟는다."""
    base = tmp_path / "dotdot"
    base.mkdir()
    _expect_refused(
        m, base, monkeypatch, capsys,
        ["--worklist-out", str(base / "sub" / ".." / "acc.review.jsonl")],
        seed_queue=False,
    )  # fmt: skip


def _scn_case_variant(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """Windows 대소문자 무시 — `ACC.Review.JSONL`. Windows 규칙(ntpath.normcase)을 주입한다."""
    base = tmp_path / "case_variant"
    base.mkdir()
    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    _expect_refused(
        m, base, monkeypatch, capsys,
        ["--worklist-out", str(base / "ACC.Review.JSONL")],
        seed_queue=False,
    )  # fmt: skip


def _scn_hardlink(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """이름이 전혀 다른 하드 링크 — 문자열로는 못 잡고 `samefile`만 잡는다(정본이 있어야 성립)."""
    base = tmp_path / "hardlink"
    base.mkdir()
    queue = base / "acc.review.jsonl"
    queue.write_text(_QUEUE_SEED, encoding="utf-8")
    alias = base / "totally_different_name.md"
    try:
        os.link(queue, alias)
    except (OSError, NotImplementedError, AttributeError) as exc:  # pragma: no cover
        pytest.skip(f"하드 링크 미지원 파일시스템: {type(exc).__name__}")
    _expect_refused(
        m, base, monkeypatch, capsys,
        ["--worklist-out", str(alias)],
        seed_queue=False,
    )  # fmt: skip


def _expect_passes_and_queue_stays_jsonl(
    m: types.ModuleType,
    base: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv_tail: list[str],
    view: Path,
) -> None:
    """대조군 공통 — 거부되지 않고 끝까지 돌며, 정본은 JSONL로 남고 뷰는 마크다운으로 쓰인다."""
    base.mkdir(parents=True, exist_ok=True)
    out = base / "acc.jsonl"
    queue = base / "acc.review.jsonl"
    _scripted_generator(monkeypatch, m)
    capsys.readouterr()
    code = m.main(["--out", str(out), "--n", "1", *argv_tail])
    err = capsys.readouterr().err
    assert "--worklist-out 거부" not in err, "과잉 차단: 정상 뷰 경로가 거부됐다"
    assert code == 1, f"비JSON 1건 → 무진전 exit 1이어야 한다(받은 값 {code})"
    assert _first_non_space(queue) == "{", "정본이 JSONL로 남지 않았다"
    assert view.read_text(encoding="utf-8").startswith("#"), "뷰가 마크다운으로 쓰이지 않았다"
    assert view.resolve() != queue.resolve()


def _scn_control_default(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """대조군 ① — 플래그 생략(기본 `<out>.worklist.md`)."""
    base = tmp_path / "control_default"
    _expect_passes_and_queue_stays_jsonl(m, base, monkeypatch, capsys, [], base / "acc.worklist.md")


def _scn_control_md_name(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """대조군 ② — 런북이 안내하는 정정형 `.review.md`(정본과 *이름만 비슷한* 다른 파일)."""
    base = tmp_path / "control_md"
    view = base / "acc.review.md"
    _expect_passes_and_queue_stays_jsonl(
        m, base, monkeypatch, capsys, ["--worklist-out", str(view)], view
    )


def _scn_control_other_dir_same_name(m, tmp_path, monkeypatch, capsys):  # type: ignore[no-untyped-def]
    """대조군 ③ — *다른 디렉터리의* 같은 파일명은 다른 파일이다(이름만 보는 과잉 구현 차단)."""
    base = tmp_path / "control_other_dir"
    view = base / "elsewhere" / "acc.review.jsonl"
    _expect_passes_and_queue_stays_jsonl(
        m, base, monkeypatch, capsys, ["--worklist-out", str(view)], view
    )


_REFUSE_SCENARIOS: dict[str, Scenario] = {
    "same_path": _scn_same_path,
    "relative_vs_absolute": _scn_relative_vs_absolute,
    "dotdot": _scn_dotdot,
    "case_variant": _scn_case_variant,
    "hardlink": _scn_hardlink,
}
_CONTROL_SCENARIOS: dict[str, Scenario] = {
    "control_default": _scn_control_default,
    "control_md_name": _scn_control_md_name,
    "control_other_dir_same_name": _scn_control_other_dir_same_name,
}
_ALL_SCENARIOS: dict[str, Scenario] = {**_REFUSE_SCENARIOS, **_CONTROL_SCENARIOS}


@pytest.mark.parametrize("name", list(_ALL_SCENARIOS))
def test_scenario_passes_on_real_module(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """실물 모듈에서 거부 5종·대조군 3종이 모두 기대대로 거동한다."""
    _ALL_SCENARIOS[name](real_module, tmp_path, monkeypatch, capsys)


def test_refusal_keeps_preexisting_queue_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """정본이 이미 쌓여 있어도(2회차 이후) 거부 시 한 바이트도 안 바뀐다 — ① 마지막 문장."""
    base = tmp_path / "preexisting"
    base.mkdir()
    queue = base / "acc.review.jsonl"
    queue.write_text(_QUEUE_SEED, encoding="utf-8")
    _expect_refused(
        real_module, base, monkeypatch, capsys,
        ["--worklist-out", str(queue)],
        seed_queue=False,
    )  # fmt: skip
    assert queue.read_text(encoding="utf-8") == _QUEUE_SEED


# ──────────────────────────────────────────────────────────────────────────
# 판정 함수 단독 — 표기 변형 표
# ──────────────────────────────────────────────────────────────────────────
class TestWorklistAliasesReviewQueue:
    def test_identical(self, tmp_path: Path) -> None:
        q = tmp_path / "a.review.jsonl"
        assert worklist_aliases_review_queue(q, q) is True

    def test_different_names_both_missing_is_not_alias(self, tmp_path: Path) -> None:
        """없는 두 파일 → samefile이 FileNotFoundError → False(대조군)."""
        assert (
            worklist_aliases_review_queue(tmp_path / "a.review.md", tmp_path / "a.review.jsonl")
            is False
        )

    def test_missing_view_with_existing_queue_is_not_alias(self, tmp_path: Path) -> None:
        q = tmp_path / "a.review.jsonl"
        q.write_text(_QUEUE_SEED, encoding="utf-8")
        assert worklist_aliases_review_queue(tmp_path / "a.worklist.md", q) is False

    def test_symlink_to_queue(self, tmp_path: Path) -> None:
        q = tmp_path / "a.review.jsonl"
        q.write_text(_QUEUE_SEED, encoding="utf-8")
        link = tmp_path / "view.md"
        try:
            link.symlink_to(q)
        except OSError as exc:  # pragma: no cover
            pytest.skip(f"심볼릭 링크 미지원: {type(exc).__name__}")
        assert worklist_aliases_review_queue(link, q) is True

    def test_case_variant_needs_windows_rules(self, tmp_path: Path) -> None:
        """대소문자 변형은 *규칙에 따라* 다르다 — Windows 규칙에서만 같은 파일이다.

        이 칸이 두 방향을 모두 동결한다: Windows 규칙 → 동치, 대소문자 구분 규칙(항등) → 별개.
        항등 쪽이 빠지면 "대소문자만 다르면 무조건 막는" 과잉 구현이 초록이다(리눅스에서
        `A.md`와 `a.md`는 정말 다른 파일).
        """
        q = tmp_path / "acc.review.jsonl"
        variant = tmp_path / "ACC.REVIEW.JSONL"
        assert worklist_aliases_review_queue(variant, q, normcase=ntpath.normcase) is True
        assert worklist_aliases_review_queue(variant, q, normcase=lambda s: s) is False

    @pytest.mark.skipif(os.name != "nt", reason="실제 Windows 파일시스템에서만 의미 있음")
    def test_real_windows_case_insensitivity(self, tmp_path: Path) -> None:  # pragma: no cover
        q = tmp_path / "acc.review.jsonl"
        assert worklist_aliases_review_queue(tmp_path / "ACC.REVIEW.JSONL", q) is True


# ──────────────────────────────────────────────────────────────────────────
# 실패 주입 — 절 하나를 지우면 정확히 기대한 시나리오가 RED가 되는가
# ──────────────────────────────────────────────────────────────────────────
_GUARD_OFF = (
    "    if args.worklist_out is not None:\n        queue_path_for_guard",
    "    if False:\n        queue_path_for_guard",
)
_HELPER_FIRST_LINE = "    fold = normcase if normcase is not None else os.path.normcase\n"

# 이름 → (치환 목록, 기대 RED 시나리오 집합). 치환 대상은 각각 정확히 1건이어야 한다.
_MUTATIONS: dict[str, tuple[list[tuple[str, str]], set[str]]] = {
    "M1_guard_call_site_disabled": (
        [_GUARD_OFF],
        set(_REFUSE_SCENARIOS),
    ),
    "M2_helper_always_false": (
        [(_HELPER_FIRST_LINE, "    return False\n" + _HELPER_FIRST_LINE)],
        set(_REFUSE_SCENARIOS),
    ),
    "M3_drop_resolve": (
        [
            ("Path(worklist_path).resolve()", "Path(worklist_path)"),
            ("Path(queue_path).resolve()", "Path(queue_path)"),
        ],
        {"relative_vs_absolute", "dotdot"},
    ),
    "M4_drop_samefile": (
        [
            (
                "        return os.path.samefile(worklist_resolved, queue_resolved)",
                "        return False",
            )
        ],
        {"hardlink"},
    ),
    "M5_drop_normcase": (
        [
            (
                "fold(str(worklist_resolved)) == fold(str(queue_resolved))",
                "str(worklist_resolved) == str(queue_resolved)",
            )
        ],
        {"case_variant"},
    ),
    # 과잉 차단 방향 — 대조군 없이 거부 방향만 재면 이 변형이 초록이다.
    "M6_helper_always_true": (
        [(_HELPER_FIRST_LINE, "    return True\n" + _HELPER_FIRST_LINE)],
        {"control_md_name", "control_other_dir_same_name"},
    ),
}


def _load_mutated(source: str, name: str) -> types.ModuleType:
    """소스 문자열을 별도 모듈로 메모리 로드 — 실파일은 건드리지 않는다."""
    module = types.ModuleType(name)
    module.__file__ = str(_SRC)
    module.__package__ = "whymath_backend.harness"
    sys.modules[name] = module  # dataclass의 문자열 주석 해석이 sys.modules를 본다
    try:
        exec(compile(source, str(_SRC), "exec"), module.__dict__)  # noqa: S102 — 자기 소스 변형
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mutations_flip_exactly_the_expected_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = _SRC.read_text(encoding="utf-8")
    sha_before = _sha(_SRC)
    unexpected: list[str] = []

    for mut_name, (edits, expected_red) in _MUTATIONS.items():
        mutated = original
        for old, new in edits:
            # ① 주입이 실제로 적용됐는가 — 치환 대상이 정확히 1건(0건이면 조용히 무변형).
            assert mutated.count(old) == 1, f"{mut_name}: 치환 대상 {mutated.count(old)}건: {old!r}"
            mutated = mutated.replace(old, new)
        assert mutated != original, f"{mut_name}: 주입이 적용되지 않았다"

        module_name = f"_ops147_mutant_{mut_name}"
        module = _load_mutated(mutated, module_name)
        try:
            red: set[str] = set()
            for scn_name, scenario in _ALL_SCENARIOS.items():
                case_dir = tmp_path / mut_name
                case_dir.mkdir(exist_ok=True)
                with monkeypatch.context() as mp:
                    try:
                        scenario(module, case_dir, mp, capsys)
                    except (AssertionError, IndexError):
                        red.add(scn_name)
                    except pytest.skip.Exception:  # pragma: no cover
                        pass
        finally:
            sys.modules.pop(module_name, None)

        if red != expected_red:
            unexpected.append(f"{mut_name}: RED={sorted(red)} 기대={sorted(expected_red)}")

    # ② 원복 — 실파일은 메모리 변형만 했으므로 바이트 동일해야 한다.
    assert _sha(_SRC) == sha_before
    assert _SRC.read_text(encoding="utf-8") == original
    assert not unexpected, "변형 → RED 집합 불일치:\n" + "\n".join(unexpected)
