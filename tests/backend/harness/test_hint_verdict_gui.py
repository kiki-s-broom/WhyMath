"""힌트 누설 사람 판정 창 — `harness/hint_verdict_gui` (EOS-219). hermetic · tkinter 불요.

검증 축:
  - 맹검 순서(헌법 R19-01 · Kiki 2026-10-30 선택) — 권고 공개(`reveal_recommendation`)는 이번
    세션에서 **기록에 성공한** 힌트만 된다. 판정 전·건너뛰기·기록 실패·다른 힌트 → 예외.
    판정 화면(`current_view`)에는 `review_view` 다섯 칸 밖의 필드가 없다
  - 기록 — 터미널 도구와 같은 계약 행(목적·지문·bypassed=False · 권고 필드 없음)
  - 실수 방지 — 입력 잠금 · 빈/긴 근거 거부 · 시계 역행 정지 · 공개 단계에서 판정 변경 불가
  - 권고 파일 — 정상 · 형식 오류 · 중복 · 대상 밖 hint_id · 낡은 지문 · 파일 없음
  - 불일치 보고 — 이 판정자·이 표본·지금 지문의 최신 판정만 · stdout 요약 키
  - 창 없는 경로 — 모듈 import가 tkinter를 부르지 않음 · tkinter 부재 → GUI_UNAVAILABLE exit 2
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


def _recs_for_all(world: dict[str, Any], verdict: str) -> dict[str, gui.HintAiRecommendation]:
    return {
        hint_id: gui.HintAiRecommendation.model_validate(_rec_row(hint_id, verdict, fp))
        for hint_id, fp in _fingerprints(world).items()
    }


# ──────────────────────────────────────────────────────────────────────
# 맹검 순서 — 권고는 기록 성공 뒤에만
# ──────────────────────────────────────────────────────────────────────
class TestBlindOrdering:
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

    def test_reveal_raises_before_record(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        with pytest.raises(gui.RecommendationLockedError):
            ctl.reveal_recommendation(view.hint_id)
        # 아직 화면에 오지 않은 힌트도 마찬가지
        for hint_id in _fingerprints(world):
            with pytest.raises(gui.RecommendationLockedError):
                ctl.reveal_recommendation(hint_id)

    def test_reveal_raises_after_skip(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        assert ctl.skip() is True
        with pytest.raises(gui.RecommendationLockedError):
            ctl.reveal_recommendation(view.hint_id)
        assert ctl.outcome.skipped == 1 and _rows(world) == []

    def test_reveal_raises_after_record_failure_and_session_stops(
        self, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*_a: object, **_k: object) -> None:
            raise PermissionError("locked")

        monkeypatch.setattr(gui, "append_verdict", _fail)
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        result = ctl.submit(hv.HintVerdict.NOT_LEAKED, "근거")
        assert result.status == "record_failed" and "PermissionError" in result.message
        assert ctl.halted and ctl.current_view() is None
        with pytest.raises(gui.RecommendationLockedError):
            ctl.reveal_recommendation(view.hint_id)
        assert ctl.submit(hv.HintVerdict.LEAKED, "다시").status == "rejected"

    def test_reveal_after_successful_record_shows_disagreement(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        result = ctl.submit(hv.HintVerdict.NOT_LEAKED, "숫자가 드러나지 않음")
        assert result.status == "recorded" and result.hint_id == view.hint_id
        reveal = ctl.reveal_recommendation(view.hint_id)
        assert reveal.state == "shown" and reveal.ai is hv.HintVerdict.LEAKED
        assert reveal.agrees is False
        assert _AI_SENTINEL in reveal.text() and "누설" in reveal.text()

    def test_reveal_after_record_agreement(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "not_leaked"), clock=clock)
        view = _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.NOT_LEAKED, "근거").status == "recorded"
        assert ctl.reveal_recommendation(view.hint_id).agrees is True

    def test_recording_one_hint_does_not_unlock_the_next(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, recs=_recs_for_all(world, "leaked"), clock=clock)
        _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "recorded"
        assert ctl.advance() is True
        nxt = ctl.current_view()
        assert nxt is not None
        with pytest.raises(gui.RecommendationLockedError):
            ctl.reveal_recommendation(nxt.hint_id)

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

    def test_reveal_states_none_and_stale(self, world: dict[str, Any]) -> None:
        fps = _fingerprints(world)
        first, second = list(_inputs(world).items)[:2]
        stale = gui.HintAiRecommendation.model_validate(
            _rec_row(first.hint.hint_id, "leaked", "sha256:" + "0" * 64)
        )
        clock = _Clock()
        ctl = _controller(world, recs={first.hint.hint_id: stale}, clock=clock)
        assert ctl.stale_count == 1 and ctl.loaded_count == 1
        _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "recorded"
        reveal = ctl.reveal_recommendation(first.hint.hint_id)
        assert reveal.state == "stale" and reveal.agrees is None
        assert "내용이 바뀜" in reveal.text() and _AI_SENTINEL not in reveal.text()
        assert ctl.advance()
        _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "recorded"
        none = ctl.reveal_recommendation(second.hint.hint_id)
        assert none.state == "none" and none.text() == "AI 권고: 권고 없음"
        assert fps[first.hint.hint_id] != stale.content_fingerprint


# ──────────────────────────────────────────────────────────────────────
# 실수 방지
# ──────────────────────────────────────────────────────────────────────
class TestGuards:
    def test_input_lock_rejects_early_submit(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
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

    def test_verdict_cannot_change_while_revealing(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        _show_and_wait(ctl, clock)
        assert ctl.submit(hv.HintVerdict.LEAKED, "근거").status == "recorded"
        assert ctl.revealing
        assert ctl.submit(hv.HintVerdict.NOT_LEAKED, "번복").status == "rejected"
        assert ctl.skip() is False
        assert len(_rows(world)) == 1

    def test_quit_midway_is_aborted_and_finish_is_not(self, world: dict[str, Any]) -> None:
        clock = _Clock()
        ctl = _controller(world, clock=clock)
        _show_and_wait(ctl, clock)
        ctl.quit()
        assert ctl.outcome.aborted
        done = _controller(world, clock=clock)
        for _ in range(4):
            assert done.current_view() is not None
            assert done.skip()
        done.quit()
        assert done.finished and not done.outcome.aborted


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
# 불일치 보고
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
        assert (report.agree, report.disagree, report.no_rec) == (1, 1, 1)
        assert report.disagreements == [
            {"hint_id": ids[1], "human": "not_leaked", "ai": "leaked", "ai_rationale": _AI_SENTINEL}
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
        assert (report.agree, report.disagree, report.no_rec, report.disagreements) == (
            0,
            0,
            0,
            [],
        )


# ──────────────────────────────────────────────────────────────────────
# CLI — 창 없는 경로·가짜 창
# ──────────────────────────────────────────────────────────────────────
def _gui_args(world: dict[str, Any], *extra: str) -> list[str]:
    return [*_common(world), "--reviewer", "kiki", *extra]


def _summary(out: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


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
        report_path = _review_dir(world) / gui.DEFAULT_DISAGREEMENTS_NAME
        assert summary["DISAGREEMENTS_PATH"] == str(report_path)
        assert json.loads(report_path.read_text(encoding="utf-8")) == [
            {"hint_id": ids[1], "human": "not_leaked", "ai": "leaked", "ai_rationale": _AI_SENTINEL}
        ]

    def _fake_tk(self) -> types.ModuleType:
        module = types.ModuleType("tkinter")

        class _Root:
            def mainloop(self) -> None:
                return None

        class _TclError(Exception):
            pass

        module.Tk = _Root  # type: ignore[attr-defined]
        module.TclError = _TclError  # type: ignore[attr-defined]
        return module

    def test_window_session_records_and_writes_report(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """가짜 창이 1건 기록·공개 후 닫는다 — 기록·중단 요약·보고 파일·권고 파일 부재 표기."""
        clock = _Clock()
        seen: dict[str, Any] = {}

        class _Window:
            def __init__(self, root: object, controller: gui.GuiReviewController) -> None:
                self.record_failed = False
                view = controller.current_view()
                assert view is not None
                clock.t += 5.0
                result = controller.submit(hv.HintVerdict.LEAKED, "정답을 직접 적음")
                seen["result"] = result
                seen["reveal"] = controller.reveal_recommendation(view.hint_id)
                controller.quit()

        monkeypatch.setattr(gui, "_import_tk", self._fake_tk)
        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world), clock=clock) == gui.EXIT_OK
        out = capsys.readouterr().out
        summary = _summary(out)
        assert seen["result"].status == "recorded" and seen["reveal"].state == "none"
        assert summary["SESSION_STATE"] == "중단" and summary["SESSION_RECORDED"] == "1"
        assert summary["AI_RECS_FILE"] == "MISSING" and summary["AI_NO_REC"] == "1"
        assert len(_rows(world)) == 1
        assert (_review_dir(world) / gui.DEFAULT_DISAGREEMENTS_NAME).exists()

    def test_window_record_failure_exits_2(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
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
        monkeypatch.setattr(gui, "_import_tk", self._fake_tk)
        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        assert gui.main(_gui_args(world), clock=clock) == gui.EXIT_RECORD
        captured = capsys.readouterr()
        assert _summary(captured.out)["SESSION_STATE"] == "기록 실패로 정지"
        assert "PermissionError" in captured.err

    def test_preflight_failure_does_not_open_window(
        self,
        world: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        blocker = Path(world["root"]) / "blocker"
        blocker.write_text("파일이라 폴더로 쓸 수 없다", encoding="utf-8")

        class _Window:
            def __init__(self, *_a: object) -> None:
                raise AssertionError("쓰기 점검 실패인데 창을 띄웠다")

        monkeypatch.setattr(gui, "_import_tk", self._fake_tk)
        monkeypatch.setattr(gui, "HintVerdictWindow", _Window)
        code = gui.main(_gui_args(world, "--verdicts", str(blocker / "v.jsonl")))
        assert code == gui.EXIT_RECORD and "WRITE_PREFLIGHT_FAILED" in capsys.readouterr().out
