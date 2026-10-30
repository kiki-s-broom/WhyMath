"""힌트 누설 사람 판정 창 — `harness/hint_verdict_gui` (EOS-219). hermetic · tkinter 불요.

검증 축:
  - 맹검(헌법 R19-01 · 독립 검토 H1) — 판정하는 동안 AI 권고는 한 건도 나가지 않는다. 기록 결과는
    확인 문구뿐이고 곧바로 다음 항목으로 넘어간다. 사람-AI 비교(`final_comparison`)는 남은 항목
    0건·정지 아님일 때만 열리며, 그 전(판정 전·일부 기록·건너뛰기 중·정지)에는 예외다
  - 창 소스 동결(M1 · AST) — 창 클래스는 `_recommendations`를 읽지 않고, `final_comparison`은
    끝 화면 메서드에서만 부르며 그 메서드는 `finished` 게이트 뒤·`view is None` 분기에서만 닿는다
  - 콜백 예외 처리기(M1) — 세션 정지·예외 타입명 오류 창·창 닫기(fail-closed)
  - 기록 — 터미널 도구와 같은 계약 행(목적·지문·bypassed=False · 권고 필드 없음)
  - 실수 방지 — 입력 잠금(항목마다 다시) · 빈/긴 근거 거부 · 시계 역행 정지 · 남은 0건 종료는 완료
  - 권고 파일 — 정상 · 형식 오류 · 중복 · 대상 밖 hint_id · 낡은 지문 · 파일 없음
  - 요약·불일치 보고 — 끝났을 때만 AI 수·판정자별 파일 · 중간 종료면 `AI_COMPARE=WITHHELD`·파일 없음
  - 창 없는 경로 — 모듈 import가 tkinter를 부르지 않음 · tkinter 부재 → GUI_UNAVAILABLE exit 2 ·
    창 오류 → GUI_ERROR exit 2
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import types
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import hint_verdict_gui as gui
from whymath_backend.harness import hint_verdict_session as hvs
from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef
from whymath_backend.ops import hint_human_verdicts as hv

_GATE_SENTINEL = "GATE_REPORT_SENTINEL_5b1d"
_AI_SENTINEL = "AI_RATIONALE_SENTINEL_c03e"


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def _cu(slug: str, answer: str) -> dict[str, Any]:
    return {
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, slug)),
        "slug": slug,
        "question_text": f"문항 {slug}: 접선의 y절편을 구하시오.",
        "answer": answer,
    }


def _hint(cu: dict[str, Any], content: str, level: int, hint_id: str) -> Hint:
    return Hint(
        hint_id=hint_id,
        solution_step_ref=SolutionStepRef(
            solution_path_id="p1", step_order=1, problem_id=uuid.UUID(cu["problem_id"])
        ),
        level=level,  # type: ignore[arg-type]
        reveals=HintReveals.from_flags(
            concept_names=level == 1, step_flow=level >= 2, partial_computation=level == 3
        ),
        content=content,
        verified=True,
        gate_report={"answer_leakage": {"verdict": "clean", "note": _GATE_SENTINEL}},
    )


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    """CU 2개 × L1·L2 = 힌트 4건 + 표본 매니페스트(터미널 도구 sample로 만든다)."""
    cus = [_cu("long", "25"), _cu("short", "3")]
    hints = [
        _hint(cus[0], "기울기부터 구해 볼까요?", 1, "h-long-l1"),
        _hint(cus[0], "접점을 먼저 정해 봐요", 2, "h-long-l2"),
        _hint(cus[1], "세 단계로 나눠 생각해 봐요", 1, "h-short-l1"),
        _hint(cus[1], "접점을 먼저 정해 봐요", 2, "h-short-l2"),
    ]
    _write(tmp_path / "r1-a" / "cu.jsonl", cus)
    _write(tmp_path / "r1-a" / "cu.genlog.jsonl", [])
    hints_path = tmp_path / "r1-a" / "cu.hints.jsonl"
    _write(hints_path, [h.model_dump(mode="json") for h in hints])
    w: dict[str, Any] = {"root": tmp_path, "cus": cus, "hints": hints, "hints_path": hints_path}
    assert hvs.main(["sample", *_common(w)], out=io.StringIO()) == 0
    return w


def _common(world: dict[str, Any]) -> list[str]:
    return [
        "--round",
        "r1",
        "--runs-root",
        str(world["root"]),
        "--hints-jsonl",
        str(world["hints_path"]),
    ]


def _review_dir(world: dict[str, Any]) -> Path:
    return Path(world["root"]) / "r1-review"


def _verdicts_path(world: dict[str, Any]) -> Path:
    return _review_dir(world) / hvs.DEFAULT_VERDICTS_NAME


def _recs_path(world: dict[str, Any]) -> Path:
    return _review_dir(world) / gui.DEFAULT_RECOMMENDATIONS_NAME


def _inputs(world: dict[str, Any]) -> hvs.ReviewInputs:
    inputs = hvs.load_review_inputs(
        runs_root=Path(world["root"]),
        round_id="r1",
        hint_paths=[world["hints_path"]],
        manifest_path=_review_dir(world) / hvs.DEFAULT_MANIFEST_NAME,
        verdicts_path=_verdicts_path(world),
    )
    assert inputs.errors == [] and inputs.manifest is not None
    return inputs


def _fingerprints(world: dict[str, Any]) -> dict[str, str]:
    return {
        item.hint.hint_id: hv.hint_review_fingerprint(item.cu_row, item.hint)
        for item in _inputs(world).items
    }


def _rec_row(
    hint_id: str, recommendation: str, fingerprint: str, rationale: str = _AI_SENTINEL
) -> dict[str, Any]:
    return {
        "schema_version": "hint-ai-recommendation/v1",
        "hint_id": hint_id,
        "recommendation": recommendation,
        "rationale": rationale,
        "author": "claude",
        "created_at": "2026-10-30T01:00:00+09:00",
        "content_fingerprint": fingerprint,
    }


class _Clock:
    """수동 시계 — 테스트가 `t`를 직접 옮긴다."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def _controller(
    world: dict[str, Any],
    *,
    recs: dict[str, gui.HintAiRecommendation] | None = None,
    clock: _Clock | None = None,
    not_before: datetime | None = None,
    now: datetime | None = None,
) -> gui.GuiReviewController:
    inputs = _inputs(world)
    assert inputs.manifest is not None
    return gui.GuiReviewController(
        inputs.items,
        manifest=inputs.manifest,
        verdicts_path=_verdicts_path(world),
        reviewer="kiki",
        done=set(),
        recommendations=recs or {},
        clock=clock or _Clock(),
        now=(lambda: now) if now is not None else (lambda: datetime.now(UTC)),
        not_before=not_before,
    )


def _show_and_wait(ctl: gui.GuiReviewController, clock: _Clock) -> gui.ItemView:
    view = ctl.current_view()
    assert view is not None
    clock.t += 5.0  # 잠금(2초)이 지난 뒤
    return view


def _rows(world: dict[str, Any]) -> list[dict[str, Any]]:
    path = _verdicts_path(world)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _content(world: dict[str, Any], hint_id: str) -> str:
    return next(h.content for h in world["hints"] if h.hint_id == hint_id)


def _recs_for_all(world: dict[str, Any], verdict: str) -> dict[str, gui.HintAiRecommendation]:
    return {
        hint_id: gui.HintAiRecommendation.model_validate(_rec_row(hint_id, verdict, fp))
        for hint_id, fp in _fingerprints(world).items()
    }


def _record_all(
    ctl: gui.GuiReviewController, clock: _Clock, verdicts: list[str]
) -> list[gui.RecordResult]:
    """남은 항목을 차례로 기록한다(verdict 하나당 1건)."""
    results = []
    for verdict in verdicts:
        _show_and_wait(ctl, clock)
        results.append(ctl.submit(hv.HintVerdict(verdict), "근거"))
    return results


# ──────────────────────────────────────────────────────────────────────
# 맹검 — 판정 중 권고 비노출 · 세션 끝에만 비교
# ──────────────────────────────────────────────────────────────────────
class TestBlindUntilSessionEnd:
    def test_current_view_carries_only_the_five_review_fields(self, world: dict[str, Any]) -> None:
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"))
        view = ctl.current_view()
        assert view is not None
        fields = {f.name for f in gui.ItemView.__dataclass_fields__.values()}
        assert fields == {
            "index",
            "total",
            "hint_id",
            "question_text",
            "choices",
            "answer",
            "hint_level",
            "hint_content",
        }
        rendered = repr(view)
        for token in (_AI_SENTINEL, _GATE_SENTINEL, "leaked", "machine", "semantic_sample"):
            assert token not in rendered, token

    def test_per_item_reveal_api_is_gone(self) -> None:
        # 항목별 공개(H1 결함)로 돌아가는 경로 자체가 없어야 한다
        for name in ("reveal_recommendation", "revealing", "advance"):
            assert not hasattr(gui.GuiReviewController, name), name
        assert not hasattr(gui, "RecommendationReveal")
        assert {f.name for f in gui.RecordResult.__dataclass_fields__.values()} == {
            "status",
            "message",
            "hint_id",
        }

    def test_record_returns_only_a_confirmation_and_moves_on(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        first = _show_and_wait(ctl, clock)
        result = ctl.submit(hv.HintVerdict.NOT_LEAKED, "숫자가 드러나지 않음")
        assert result.status == "recorded" and result.hint_id == first.hint_id
        assert result.message == "기록했습니다 (1/4)"
        for token in (_AI_SENTINEL, "AI", "일치", "leaked", "누설"):
            assert token not in repr(result), token
        nxt = ctl.current_view()
        assert nxt is not None and nxt.hint_id != first.hint_id and nxt.index == 2
        # 다음 항목은 잠금을 새로 건다 — 기록 직후 곧바로 낸 판정은 거부
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "rejected"

    def test_comparison_locked_before_any_record(self, world: dict[str, Any]) -> None:
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"))
        assert ctl.current_view() is not None
        assert not ctl.comparison_unlocked
        with pytest.raises(gui.RecommendationLockedError):
            ctl.final_comparison()

    def test_comparison_locked_while_items_remain(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _record_all(ctl, clock, ["leaked", "not_leaked", "leaked"])  # 4건 중 3건
        assert not ctl.finished
        with pytest.raises(gui.RecommendationLockedError):
            ctl.final_comparison()
        _show_and_wait(ctl, clock)
        assert ctl.skip() is True  # 마지막을 건너뛰면 남은 0건 — 그때 열린다
        assert ctl.finished and ctl.comparison_unlocked
        report = ctl.final_comparison()
        assert report.unjudged == 1 and report.agree + report.disagree + report.no_rec == 3

    def test_comparison_locked_after_record_failure(
        self, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*_a: object, **_k: object) -> None:
            raise PermissionError("locked")

        monkeypatch.setattr(gui, "append_verdict", _fail)
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _show_and_wait(ctl, clock)
        result = ctl.submit(hv.HintVerdict.NOT_LEAKED, "근거")
        assert result.status == "record_failed" and "PermissionError" in result.message
        assert ctl.halted and ctl.current_view() is None
        with pytest.raises(gui.RecommendationLockedError):
            ctl.final_comparison()
        assert ctl.submit(hv.HintVerdict.LEAKED, "다시").status == "rejected"

    def test_comparison_locked_when_finished_but_halted(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _record_all(ctl, clock, ["leaked"] * 4)
        assert ctl.finished
        ctl.fail("창 오류 — RuntimeError")
        with pytest.raises(gui.RecommendationLockedError):
            ctl.final_comparison()

    def test_comparison_after_all_recorded_lists_disagreements_with_content(
        self, world: dict[str, Any]
    ) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        results = _record_all(ctl, clock, ["leaked", "not_leaked", "leaked", "leaked"])
        assert [r.message for r in results] == [f"기록했습니다 ({i}/4)" for i in range(1, 5)]
        assert ctl.finished and ctl.current_view() is None
        report = ctl.final_comparison()
        assert (report.agree, report.disagree, report.no_rec, report.unjudged) == (3, 1, 0, 0)
        ids = list(_fingerprints(world))
        assert report.disagreements == [
            {
                "hint_id": ids[1],
                "hint_content": _content(world, ids[1]),
                "human": "not_leaked",
                "ai": "leaked",
                "ai_rationale": _AI_SENTINEL,
            }
        ]

    def test_skipped_items_are_unjudged_and_never_compared(self, world: dict[str, Any]) -> None:
        ids = list(_fingerprints(world))
        recs = _recs_for_all(world, "leaked")
        clock = _Clock()
        ctl = _controller(world, recs=recs, clock=clock)
        _record_all(ctl, clock, ["not_leaked", "not_leaked"])
        for _ in range(2):
            _show_and_wait(ctl, clock)
            assert ctl.skip()
        report = ctl.final_comparison()
        assert ctl.outcome.skipped == 2 and report.unjudged == 2
        assert {d["hint_id"] for d in report.disagreements} == {ids[0], ids[1]}

    def test_stale_and_missing_recommendations_count_as_no_rec(self, world: dict[str, Any]) -> None:
        first, second = list(_inputs(world).items)[:2]
        stale = gui.HintAiRecommendation.model_validate(
            _rec_row(first.hint.hint_id, "not_leaked", "sha256:" + "0" * 64)
        )
        clock = _Clock()
        ctl = _controller(world, recs={first.hint.hint_id: stale}, clock=clock)
        assert ctl.stale_count == 1 and ctl.loaded_count == 1
        _record_all(ctl, clock, ["leaked"] * 4)
        report = ctl.final_comparison()
        assert (report.agree, report.disagree, report.no_rec) == (0, 0, 4)
        assert report.disagreements == [] and second.hint.hint_id

    def test_recorded_row_is_the_blind_contract_without_recommendation(
        self, world: dict[str, Any]
    ) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.NOT_LEAKED, "  앞뒤 공백  ").status == "recorded"
        rows = _rows(world)
        assert len(rows) == 1
        verdict = hv.HintHumanVerdict.model_validate(rows[0])  # extra 금지 계약 — 권고 필드 없음
        manifest = _inputs(world).manifest
        assert manifest is not None
        assert verdict.hint_id == view.hint_id and verdict.bypassed is False
        assert verdict.rationale == "앞뒤 공백"
        assert verdict.purpose is manifest.purpose_of(view.hint_id)
        assert verdict.content_fingerprint == _fingerprints(world)[view.hint_id]
        assert _AI_SENTINEL not in json.dumps(rows[0], ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────
# 창 소스 동결 (AST · M1) — 창은 권고에 직접 닿지 않고 끝 화면에서만 비교를 연다
# ──────────────────────────────────────────────────────────────────────
def _class_node(tree: ast.Module, name: str) -> ast.ClassDef:
    found = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name]
    assert len(found) == 1, name
    return found[0]


def _methods(cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _calls_to(node: ast.AST, attr: str) -> list[ast.Call]:
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    ]


def _window_source_violations(source: str) -> list[str]:
    """창 클래스의 맹검 구조 위반 목록(빈 목록 = 통과). 테스트가 뮤테이션 소스로도 부른다."""
    violations: list[str] = []
    tree = ast.parse(source)
    window = _class_node(tree, "HintVerdictWindow")
    methods = _methods(window)
    for n in ast.walk(window):
        if isinstance(n, ast.Attribute) and n.attr == "_recommendations":
            violations.append("창이 _recommendations를 읽는다")
        if isinstance(n, ast.Attribute | ast.Name) and (
            getattr(n, "attr", None) or getattr(n, "id", None)
        ) in {"build_disagreement_report", "load_recommendations"}:
            violations.append("창이 게이트 없는 권고 함수를 부른다")
    holders = [name for name, fn in methods.items() for _ in _calls_to(fn, "final_comparison")]
    if holders != ["_show_end_screen"]:
        violations.append(f"final_comparison 호출 위치가 끝 화면 1곳이 아니다: {holders}")
    end = methods.get("_show_end_screen")
    if end is None:
        return [*violations, "_show_end_screen 없음"]
    stmts = [
        s
        for s in end.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))  # docstring
    ]
    gate = stmts[0] if stmts else None
    gate_ok = (
        isinstance(gate, ast.If)
        and any(isinstance(n, ast.Attribute) and n.attr == "finished" for n in ast.walk(gate.test))
        and len(gate.body) == 1
        and isinstance(gate.body[0], ast.Return)
        and not gate.orelse
    )
    if not gate_ok:
        violations.append("_show_end_screen 첫 문장이 finished 게이트(if … : return)가 아니다")
    else:
        assert gate is not None
        calls = _calls_to(end, "final_comparison")
        if any(c.lineno <= gate.end_lineno for c in calls if gate.end_lineno is not None):
            violations.append("final_comparison이 finished 게이트보다 앞에 있다")
    callers = [name for name, fn in methods.items() for _ in _calls_to(fn, "_show_end_screen")]
    if callers != ["_show_current"]:
        violations.append(f"_show_end_screen 호출자가 _show_current 하나가 아니다: {callers}")
    else:
        current = methods["_show_current"]
        guarded = [
            n
            for n in ast.walk(current)
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.ops[0], ast.Is)
            and isinstance(n.test.comparators[0], ast.Constant)
            and n.test.comparators[0].value is None
            and any(c in ast.walk(n) for c in _calls_to(current, "_show_end_screen"))
        ]
        if not guarded:
            violations.append("_show_end_screen 호출이 'view is None' 분기 안에 있지 않다")
    return violations


class TestWindowSourceGovernance:
    def test_window_class_passes_blind_structure(self) -> None:
        assert _window_source_violations(inspect.getsource(gui)) == []

    def test_final_comparison_called_only_in_window_end_screen_and_summary(self) -> None:
        tree = ast.parse(inspect.getsource(gui))
        holders = sorted(
            f"{cls.name}.{fn.name}"
            for cls in tree.body
            if isinstance(cls, ast.ClassDef)
            for fn in _methods(cls).values()
            for _ in _calls_to(fn, "final_comparison")
        )
        top = [
            fn.name
            for fn in tree.body
            if isinstance(fn, ast.FunctionDef) and _calls_to(fn, "final_comparison")
        ]
        assert holders == [
            "GuiReviewController.summary_text",
            "HintVerdictWindow._show_end_screen",
        ]
        assert top == []

    @pytest.mark.parametrize(
        ("old", "new", "expected"),
        [
            # 창이 권고 사전을 직접 읽는다
            (
                "        report = self._ctl.final_comparison()\n",
                "        report = self._ctl.final_comparison()\n"
                "        _leak = self._ctl._recommendations\n",
                "_recommendations",
            ),
            # 끝 화면 게이트 제거
            (
                "        if not self._ctl.finished or self._ctl.halted:  # 이중 게이트",
                "        if False:  # 이중 게이트",
                "finished 게이트",
            ),
            # 기록 직후 비교를 부른다(항목별 공개로 회귀)
            (
                "        # 기록 성공 — 확인 문구만 내고",
                "        self._ctl.final_comparison()\n        # 기록 성공 — 확인 문구만 내고",
                "호출 위치",
            ),
            # 끝 화면을 view None 분기 밖에서 부른다
            (
                "    def _skip(self) -> None:\n        if self._ctl.skip():",
                "    def _skip(self) -> None:\n        self._show_end_screen()\n"
                "        if self._ctl.skip():",
                "호출자",
            ),
        ],
    )
    def test_checker_detects_injected_violation(self, old: str, new: str, expected: str) -> None:
        source = inspect.getsource(gui)
        assert source.count(old) == 1, "주입 대상이 1건이 아니다 — 뮤테이션이 적용되지 않았다"
        mutated = source.replace(old, new)
        assert mutated != source
        violations = _window_source_violations(mutated)
        assert any(expected in v for v in violations), violations


# ──────────────────────────────────────────────────────────────────────
# 콜백 예외 처리기 (M1 — fail-closed)
# ──────────────────────────────────────────────────────────────────────
class TestCallbackErrorHandler:
    def test_handler_halts_shows_type_name_and_closes(self, world: dict[str, Any]) -> None:
        ctl = _controller(world)
        shown: list[tuple[str, str]] = []
        closed: list[bool] = []
        handler = gui.make_callback_error_handler(
            ctl,
            show_error=lambda t, m: shown.append((t, m)),
            close=lambda: closed.append(True),
        )
        handler(ValueError, ValueError("SECRET_VALUE_9f"), None)
        assert ctl.halted and ctl.halted_reason is not None
        assert "ValueError" in ctl.halted_reason
        assert len(shown) == 1 and "ValueError" in shown[0][1]
        assert "SECRET_VALUE_9f" not in shown[0][1] + ctl.halted_reason
        assert closed == [True]
        with pytest.raises(gui.RecommendationLockedError):
            ctl.final_comparison()

    def test_handler_still_closes_when_dialog_fails(
        self, world: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        ctl = _controller(world)
        closed: list[bool] = []

        def _broken(_t: str, _m: str) -> None:
            raise RuntimeError("no display")

        def _close() -> None:
            closed.append(True)
            raise OSError("already gone")

        handler = gui.make_callback_error_handler(ctl, show_error=_broken, close=_close)
        handler(KeyError, KeyError("k"), None)  # 처리기 자신은 예외를 내지 않는다
        assert ctl.halted and closed == [True]
        assert "RuntimeError" in caplog.text and "OSError" in caplog.text


# ──────────────────────────────────────────────────────────────────────
# 실수 방지
# ──────────────────────────────────────────────────────────────────────
class TestGuards:
    def test_input_lock_rejects_early_submit(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        assert ctl.lock_remaining() == hvs.INPUT_LOCK_SECONDS  # 띄우기 전 — 잠금 전체
        assert ctl.current_view() is not None
        clock.t += 1.0
        result = ctl.submit(hv.HintVerdict.LEAKED, "근거")
        assert result.status == "rejected" and "잠금" in result.message
        assert _rows(world) == []
        clock.t += 1.5
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "recorded"

    def test_submit_before_showing_is_rejected(self, world: dict[str, Any]) -> None:
        ctl = _controller(world)
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "rejected"

    @pytest.mark.parametrize("rationale", ["", "   ", "x" * (hv.RATIONALE_MAX_LENGTH + 1)])
    def test_bad_rationale_is_rejected(self, world: dict[str, Any], rationale: str) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.LEAKED, rationale).status == "rejected"
        assert _rows(world) == [] and not ctl.halted

    def test_clock_regression_stops_before_writing(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(
            world,
            clock=clock,
            now=datetime(2026, 10, 1, tzinfo=UTC),
            not_before=datetime(2026, 10, 2, tzinfo=UTC),
        )
        _show_and_wait(ctl, clock)
        result = ctl.submit(hv.HintVerdict.LEAKED, "근거")
        assert result.status == "record_failed" and "시계 역행" in result.message
        assert ctl.halted and not _verdicts_path(world).exists()

    def test_nothing_left_after_last_item(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        _record_all(ctl, clock, ["leaked"] * 4)
        assert ctl.submit(hv.HintVerdict.NOT_LEAKED, "번복").status == "rejected"
        assert ctl.skip() is False
        assert len(_rows(world)) == 4

    def test_quit_midway_is_aborted(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        _show_and_wait(ctl, clock)
        ctl.quit()
        assert ctl.outcome.aborted
        assert hvs.render_summary(ctl.outcome).startswith("SESSION_STATE=중단")

    def test_quit_after_finishing_is_complete(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        done = _controller(world, clock=clock)
        for _ in range(4):
            assert done.current_view() is not None
            assert done.skip()
        done.quit()
        assert done.finished and not done.outcome.aborted
        assert hvs.render_summary(done.outcome).startswith("SESSION_STATE=완료")

    def test_quit_with_nothing_pending_from_start_is_complete(self, world: dict[str, Any]) -> None:
        inputs = _inputs(world)
        assert inputs.manifest is not None
        ctl = gui.GuiReviewController(
            inputs.items,
            manifest=inputs.manifest,
            verdicts_path=_verdicts_path(world),
            reviewer="kiki",
            done={i.hint.hint_id for i in inputs.items},
            recommendations={},
        )
        assert ctl.finished and ctl.current_view() is None
        ctl.quit()
        assert not ctl.outcome.aborted
        assert hvs.render_summary(ctl.outcome).startswith("SESSION_STATE=완료")


# ──────────────────────────────────────────────────────────────────────
# 권고 파일 로더
# ──────────────────────────────────────────────────────────────────────
class TestRecommendationLoader:
    def test_valid_file_loads_every_row(self, world: dict[str, Any]) -> None:
        fps = _fingerprints(world)
        _write(_recs_path(world), [_rec_row(h, "leaked", fp) for h, fp in fps.items()])
        recs, errors = gui.load_recommendations(_recs_path(world), fps)
        assert errors == [] and set(recs) == set(fps)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda r: r.update(recommendation="leak"),
            lambda r: r.update(rationale="   "),
            lambda r: r.update(created_at="2026-10-30T01:00:00"),  # 시간대 없음
            lambda r: r.update(content_fingerprint="abc"),
            lambda r: r.update(author="김철수"),
            lambda r: r.update(extra_field=1),
            lambda r: r.pop("rationale"),
        ],
    )
    def test_contract_violation_is_an_error_without_values(
        self, world: dict[str, Any], mutate: Any
    ) -> None:
        fps = _fingerprints(world)
        hint_id, fp = next(iter(fps.items()))
        row = _rec_row(hint_id, "leaked", fp)
        mutate(row)
        _write(_recs_path(world), [row])
        recs, errors = gui.load_recommendations(_recs_path(world), fps)
        assert recs == {} and len(errors) == 1 and "권고 계약 위반" in errors[0]
        assert _AI_SENTINEL not in errors[0]

    def test_malformed_json_and_non_object(self, world: dict[str, Any]) -> None:
        path = _recs_path(world)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"hint_id": \n[1, 2]\n', encoding="utf-8")
        _, errors = gui.load_recommendations(path, _fingerprints(world))
        assert len(errors) == 2
        assert "JSON 파싱 실패" in errors[0] and "객체가 아님" in errors[1]

    def test_duplicate_hint_id_is_an_error(self, world: dict[str, Any]) -> None:
        fps = _fingerprints(world)
        hint_id, fp = next(iter(fps.items()))
        _write(_recs_path(world), [_rec_row(hint_id, "leaked", fp)] * 2)
        recs, errors = gui.load_recommendations(_recs_path(world), fps)
        assert len(errors) == 1 and "두 번" in errors[0] and set(recs) == {hint_id}

    def test_unknown_hint_id_is_an_error(self, world: dict[str, Any]) -> None:
        _write(_recs_path(world), [_rec_row("no-such-hint", "leaked", "sha256:" + "a" * 64)])
        recs, errors = gui.load_recommendations(_recs_path(world), _fingerprints(world))
        assert recs == {} and len(errors) == 1 and "판정 대상 목록에 없다" in errors[0]

    def test_stale_fingerprint_is_loaded_but_counted_stale(self, world: dict[str, Any]) -> None:
        fps = _fingerprints(world)
        hint_id = next(iter(fps))
        _write(_recs_path(world), [_rec_row(hint_id, "leaked", "sha256:" + "f" * 64)])
        recs, errors = gui.load_recommendations(_recs_path(world), fps)
        assert errors == [] and set(recs) == {hint_id}
        assert _controller(world, recs=recs).stale_count == 1

    def test_missing_file_is_a_read_error_when_called_directly(self, tmp_path: Path) -> None:
        recs, errors = gui.load_recommendations(tmp_path / "none.jsonl", [])
        assert recs == {} and len(errors) == 1 and "FileNotFoundError" in errors[0]


# ──────────────────────────────────────────────────────────────────────
# 불일치 보고 · 요약
# ──────────────────────────────────────────────────────────────────────
def _append_manual(
    world: dict[str, Any], hint_id: str, verdict: str, *, reviewer: str = "kiki", fp: str = ""
) -> None:
    inputs = _inputs(world)
    assert inputs.manifest is not None
    item = next(i for i in inputs.items if i.hint.hint_id == hint_id)
    hv.append_verdict(
        _verdicts_path(world),
        hv.HintHumanVerdict(
            schema_version="hint-human-verdict/v1",
            hint_id=hint_id,
            problem_id=item.hint.solution_step_ref.problem_id,
            reviewer=reviewer,
            judged_at=datetime.now(UTC),
            verdict=hv.HintVerdict(verdict),
            rationale="근거",
            purpose=inputs.manifest.purpose_of(hint_id),
            sample_id=inputs.manifest.sample_id,
            content_fingerprint=fp or hv.hint_review_fingerprint(item.cu_row, item.hint),
            review_session_id=uuid.uuid4(),
            bypassed=False,
        ),
    )


def _summary(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _report_path(world: dict[str, Any], reviewer: str = "kiki") -> Path:
    return _review_dir(world) / gui.disagreements_filename(reviewer)


class TestDisagreementReport:
    def test_counts_only_this_reviewer_current_content_latest_row(
        self, world: dict[str, Any]
    ) -> None:
        ids = list(_fingerprints(world))
        recs = _recs_for_all(world, "leaked")
        recs.pop(ids[3])  # 권고 없는 힌트
        _append_manual(world, ids[0], "not_leaked")
        _append_manual(world, ids[0], "leaked")  # 같은 판정자 재판정 — 최신(일치)
        _append_manual(world, ids[1], "not_leaked")  # 불일치
        _append_manual(world, ids[2], "not_leaked", reviewer="other")  # 다른 판정자 — 제외
        _append_manual(world, ids[2], "not_leaked", fp="sha256:" + "1" * 64)  # 낡은 판정 — 제외
        _append_manual(world, ids[3], "leaked")  # 권고 없음
        inputs = _inputs(world)
        assert inputs.manifest is not None
        report = gui.build_disagreement_report(
            _verdicts_path(world),
            inputs.items,
            recs,
            reviewer="kiki",
            sample_id=inputs.manifest.sample_id,
        )
        assert (report.agree, report.disagree, report.no_rec, report.unjudged) == (1, 1, 1, 1)
        assert report.disagreements == [
            {
                "hint_id": ids[1],
                "hint_content": _content(world, ids[1]),
                "human": "not_leaked",
                "ai": "leaked",
                "ai_rationale": _AI_SENTINEL,
            }
        ]

    def test_unjudged_hints_never_appear(self, world: dict[str, Any]) -> None:
        inputs = _inputs(world)
        assert inputs.manifest is not None
        report = gui.build_disagreement_report(
            _verdicts_path(world),
            inputs.items,
            _recs_for_all(world, "leaked"),
            reviewer="kiki",
            sample_id=inputs.manifest.sample_id,
        )
        assert (report.agree, report.disagree, report.no_rec, report.unjudged) == (0, 0, 0, 4)
        assert report.disagreements == []

    def test_disagreements_filename_is_per_reviewer(self) -> None:
        assert gui.disagreements_filename("kiki") == "hint_ai_disagreements.kiki.json"
        assert gui.disagreements_filename("rev-2") != gui.disagreements_filename("kiki")
        for bad in ("../x", "김철수", "", "a/b"):
            with pytest.raises(ValueError):
                gui.disagreements_filename(bad)

    def test_summary_withholds_comparison_when_quit_midway(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _record_all(ctl, clock, ["not_leaked"])
        ctl.quit()
        text = ctl.summary_text(_report_path(world))
        summary = _summary(text)
        assert summary["SESSION_STATE"] == "중단" and summary["AI_COMPARE"] == "WITHHELD"
        assert (summary["AI_RECS_FILE"], summary["AI_RECS_LOADED"]) == ("PRESENT", "4")
        for key in ("AI_AGREE", "AI_DISAGREE", "AI_NO_REC", "AI_UNJUDGED", "DISAGREEMENTS_PATH"):
            assert key not in summary, key
        assert _AI_SENTINEL not in text and not _report_path(world).exists()

    def test_summary_withholds_comparison_when_halted(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _record_all(ctl, clock, ["not_leaked"] * 4)
        ctl.fail("창 오류 — RuntimeError")
        summary = _summary(ctl.summary_text(_report_path(world)))
        assert summary["SESSION_STATE"] == "기록 실패로 정지"
        assert summary["AI_COMPARE"] == "WITHHELD" and "AI_AGREE" not in summary
        assert not _report_path(world).exists()

    def test_summary_reveals_and_writes_report_when_finished(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _record_all(ctl, clock, ["leaked", "not_leaked", "leaked"])
        _show_and_wait(ctl, clock)
        assert ctl.skip()
        ctl.quit()
        summary = _summary(ctl.summary_text(_report_path(world)))
        assert summary["SESSION_STATE"] == "완료" and "AI_COMPARE" not in summary
        assert (
            summary["AI_AGREE"],
            summary["AI_DISAGREE"],
            summary["AI_NO_REC"],
            summary["AI_UNJUDGED"],
        ) == ("2", "1", "0", "1")
        assert summary["DISAGREEMENTS_PATH"] == str(_report_path(world))
        written = json.loads(_report_path(world).read_text(encoding="utf-8"))
        assert [d["human"] for d in written] == ["not_leaked"]


# ──────────────────────────────────────────────────────────────────────
# CLI — 창 없는 경로·가짜 창
# ──────────────────────────────────────────────────────────────────────
def _gui_args(world: dict[str, Any], *extra: str) -> list[str]:
    return [*_common(world), "--reviewer", "kiki", *extra]


class _FakeRoot:
    """가짜 Tk 루트 — mainloop은 바로 끝나고 destroy 호출을 센다."""

    instances: list[_FakeRoot] = []

    def __init__(self) -> None:
        self.destroyed = 0
        self.report_callback_exception: Any = None
        self.mainloop_error: BaseException | None = None
        _FakeRoot.instances.append(self)

    def mainloop(self) -> None:
        if self.mainloop_error is not None:
            raise self.mainloop_error

    def destroy(self) -> None:
        self.destroyed += 1


def _fake_tk() -> types.ModuleType:
    module = types.ModuleType("tkinter")

    class _TclError(Exception):
        pass

    module.Tk = _FakeRoot  # type: ignore[attr-defined]
    module.TclError = _TclError  # type: ignore[attr-defined]
    return module


@pytest.fixture
def fake_tk(monkeypatch: pytest.MonkeyPatch) -> list[_FakeRoot]:
    _FakeRoot.instances = []
    monkeypatch.setattr(gui, "_import_tk", _fake_tk)
    return _FakeRoot.instances


class TestMain:
    def test_module_import_does_not_load_tkinter(self) -> None:
        assert "tkinter" not in vars(gui) and "tk" not in vars(gui)
        tree = ast.parse(inspect.getsource(gui))
        for node in tree.body:  # 최상위 문장 — TYPE_CHECKING 블록은 if 문이라 여기 안 걸린다
            if isinstance(node, ast.Import):
                assert all(not a.name.startswith("tkinter") for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("tkinter")

    def test_reviewer_format_is_input_error(
        self, world: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = gui.main([*_common(world), "--reviewer", "김철수"])
        assert code == gui.EXIT_INPUT and "판정자 ID" in capsys.readouterr().out

    def test_malformed_recommendation_file_refuses_to_start(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _never() -> types.ModuleType:
            raise AssertionError("입력 오류인데 창을 띄우려 했다")

        monkeypatch.setattr(gui, "_import_tk", _never)
        path = _recs_path(world)
        path.write_text("not json\n", encoding="utf-8")
        assert gui.main(_gui_args(world)) == gui.EXIT_INPUT
        out = capsys.readouterr().out
        assert "INPUT_ERROR=권고 파일" in out and "판정 창" not in out

    def test_gui_unavailable_exits_2(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _no_tk() -> types.ModuleType:
            raise ImportError("No module named 'tkinter'")

        monkeypatch.setattr(gui, "_import_tk", _no_tk)
        assert gui.main(_gui_args(world)) == gui.EXIT_RECORD
        assert "GUI_UNAVAILABLE=ImportError" in capsys.readouterr().out
        assert _rows(world) == []

    def test_nothing_pending_prints_summary_and_report_without_window(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = list(_fingerprints(world))
        for hint_id, verdict in zip(ids, ["leaked", "not_leaked", "leaked", "leaked"], strict=True):
            _append_manual(world, hint_id, verdict)
        fps = _fingerprints(world)
        _write(
            _recs_path(world),
            [
                _rec_row(ids[0], "leaked", fps[ids[0]]),
                _rec_row(ids[1], "leaked", fps[ids[1]]),
                _rec_row(ids[2], "leaked", "sha256:" + "e" * 64),  # 낡음
            ],
        )

        def _never() -> types.ModuleType:
            raise AssertionError("남은 대상이 없는데 창을 띄우려 했다")

        monkeypatch.setattr(gui, "_import_tk", _never)
        assert gui.main(_gui_args(world)) == gui.EXIT_OK
        summary = _summary(capsys.readouterr().out)
        assert summary["SESSION_STATE"] == "완료" and summary["SESSION_ALREADY_DONE"] == "4"
        assert summary["AI_RECS_FILE"] == "PRESENT"
        assert (summary["AI_RECS_LOADED"], summary["AI_RECS_STALE"]) == ("3", "1")
        assert (summary["AI_AGREE"], summary["AI_DISAGREE"], summary["AI_NO_REC"]) == (
            "1",
            "1",
            "2",
        )
        assert summary["DISAGREEMENTS_PATH"] == str(_report_path(world))
        assert json.loads(_report_path(world).read_text(encoding="utf-8")) == [
            {
                "hint_id": ids[1],
                "hint_content": _content(world, ids[1]),
                "human": "not_leaked",
                "ai": "leaked",
                "ai_rationale": _AI_SENTINEL,
            }
        ]

    def test_window_quit_early_withholds_comparison(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        """가짜 창이 1건 기록 후 닫는다 — 기록·중단 요약·비교 보류·보고 파일 없음."""
        clock = _Clock()
        _write(
            _recs_path(world),
            [_rec_row(h, "leaked", fp) for h, fp in _fingerprints(world).items()],
        )

        class _Window:
            def __init__(self, root: object, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                assert controller.current_view() is not None
                clock.t += 5.0
                assert controller.submit(hv.HintVerdict.LEAKED, "정답을 직접 적음").status == (
                    "recorded"
                )
                controller.quit()

        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world), clock=clock) == gui.EXIT_OK
        out = capsys.readouterr().out
        summary = _summary(out)
        assert summary["SESSION_STATE"] == "중단" and summary["SESSION_RECORDED"] == "1"
        assert summary["AI_RECS_FILE"] == "PRESENT" and summary["AI_COMPARE"] == "WITHHELD"
        assert "AI_AGREE" not in summary and _AI_SENTINEL not in out
        assert len(_rows(world)) == 1 and not _report_path(world).exists()
        assert callable(fake_tk[0].report_callback_exception)

    def test_window_finishing_all_reveals_and_writes_per_reviewer_report(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        clock = _Clock()

        class _Window:
            def __init__(self, root: object, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                _record_all(controller, clock, ["leaked"] * 4)
                controller.quit()

        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world), clock=clock) == gui.EXIT_OK
        summary = _summary(capsys.readouterr().out)
        assert summary["SESSION_STATE"] == "완료" and summary["SESSION_RECORDED"] == "4"
        assert summary["AI_RECS_FILE"] == "MISSING" and summary["AI_NO_REC"] == "4"
        assert summary["DISAGREEMENTS_PATH"] == str(_report_path(world))
        assert json.loads(_report_path(world).read_text(encoding="utf-8")) == []

    def test_window_record_failure_exits_2(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        clock = _Clock()

        def _fail(*_a: object, **_k: object) -> None:
            raise PermissionError("locked")

        class _Window:
            def __init__(self, root: object, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                assert controller.current_view() is not None
                clock.t += 5.0
                assert controller.submit(hv.HintVerdict.LEAKED, "근거").status == "record_failed"

        monkeypatch.setattr(gui, "append_verdict", _fail)
        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world), clock=clock) == gui.EXIT_RECORD
        captured = capsys.readouterr()
        summary = _summary(captured.out)
        assert summary["SESSION_STATE"] == "기록 실패로 정지"
        assert summary["AI_COMPARE"] == "WITHHELD"
        assert "PermissionError" in captured.err

    @pytest.mark.parametrize("where", ["constructor", "mainloop"])
    def test_unexpected_window_error_is_gui_error_exit_2(
        self,
        where: str,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        class _Window:
            def __init__(self, root: _FakeRoot, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                if where == "constructor":
                    raise TypeError("SECRET_FIELD_77")
                root.mainloop_error = TypeError("SECRET_FIELD_77")

        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world)) == gui.EXIT_RECORD
        captured = capsys.readouterr()
        summary = _summary(captured.out)
        assert summary["GUI_ERROR"] == "TypeError"
        assert summary["SESSION_STATE"] == "기록 실패로 정지"
        assert summary["AI_COMPARE"] == "WITHHELD"
        assert "SECRET_FIELD_77" not in captured.out + captured.err
        assert fake_tk[0].destroyed == 1

    def test_callback_exception_in_window_exits_2(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        shown: list[str] = []

        def _box(_root: object, _title: str, message: str) -> None:
            shown.append(message)

        class _Window:
            def __init__(self, root: _FakeRoot, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                # tkinter가 콜백 예외를 넘기는 경로를 그대로 흉내 낸다
                root.report_callback_exception(AttributeError, AttributeError("x"), None)

        monkeypatch.setattr(gui, "_show_error_box", _box)
        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world)) == gui.EXIT_RECORD
        captured = capsys.readouterr()
        assert _summary(captured.out)["SESSION_STATE"] == "기록 실패로 정지"
        assert len(shown) == 1 and "AttributeError" in shown[0]
        assert fake_tk[0].destroyed == 1 and "AttributeError" in captured.err

    def test_preflight_failure_does_not_open_window(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        fake_tk: list[_FakeRoot],
    ) -> None:
        blocker = Path(world["root"]) / "blocker"
        blocker.write_text("파일이라 폴더로 쓸 수 없다", encoding="utf-8")

        class _Window:
            def __init__(self, *_a: object) -> None:
                raise AssertionError("쓰기 점검 실패인데 창을 띄웠다")

        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        code = gui.main(_gui_args(world, "--verdicts", str(blocker / "v.jsonl")))
        assert code == gui.EXIT_RECORD and "WRITE_PREFLIGHT_FAILED" in capsys.readouterr().out
        assert fake_tk == []
