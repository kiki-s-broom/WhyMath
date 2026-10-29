"""힌트 누설 사람 판정 도구 — `harness/hint_verdict_session` (EOS-210). hermetic.

검증 축:
  - 맹검(헌법 R19-01) — 판정 입력 전 출력에 기계 판정·게이트 기록·목적·다른 판정자의 판정이
    없다(출력 캡처로 단언) · review 경로는 기계 판정 함수를 부르지도 않는다
  - 기록 — 계약대로 1건씩 append · 목적(표본/기계 판정 불가) 기입 · 겹치는 대상은 한 번만 묻는다
  - 실수 방지 — 입력 잠금(띄운 직후 입력 폐기) · 빈 근거 재질문 · 확인(y) 없이 기록 안 함
  - 정지·재개 — 쓰기 사전 점검 실패면 아무것도 묻지 않음 · 기록 실패면 즉시 정지(exit 2) ·
    재실행은 이미 판정한 항목을 건너뜀 · --rejudge는 append(이력 보존) · 손상된 기존 파일에 이어
    쓰지 않음 · 이름형 판정자 ID 거부
  - sample — 결정론 매니페스트 · 같은 내용이면 그대로 · 다른 내용이면 덮어쓰지 않음
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import hint_verdict_session as hvs
from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef
from whymath_backend.ops import hint_human_verdicts as hv

_GATE_SENTINEL = "GATE_REPORT_SENTINEL_7f3a"
_OTHER_SENTINEL = "OTHER_REVIEWER_RATIONALE_SENTINEL_91c2"


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
        # 기계(게이트) 판정 흔적 — 판정 화면에 새면 안 된다
        gate_report={"answer_leakage": {"verdict": "clean", "note": _GATE_SENTINEL}},
    )


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    """CU 2개(정답 `25`·한 자리 `3`) × L1·L2 = 힌트 4건. `3`의 힌트는 기계 판정 불가(None)다."""
    cus = [_cu("long", "25"), _cu("short", "3")]
    hints = [
        _hint(cus[0], "기울기부터 구해 볼까요?", 1, "h-long-l1"),
        _hint(cus[0], "접점을 먼저 정해 봐요", 2, "h-long-l2"),
        _hint(cus[1], "세 단계로 나눠 생각해 봐요", 1, "h-short-l1"),
        _hint(cus[1], "접점을 먼저 정해 봐요", 2, "h-short-l2"),
    ]
    _write(tmp_path / "r1-a" / "cu.jsonl", cus)
    _write(tmp_path / "r1-a" / "cu.genlog.jsonl", [])  # 회차 폴더 필수 파일(측정기와 같은 로더)
    hints_path = tmp_path / "r1-a" / "cu.hints.jsonl"
    _write(hints_path, [h.model_dump(mode="json") for h in hints])
    return {"root": tmp_path, "cus": cus, "hints": hints, "hints_path": hints_path}


def _common(world: dict[str, Any]) -> list[str]:
    return [
        "--round",
        "r1",
        "--runs-root",
        str(world["root"]),
        "--hints-jsonl",
        str(world["hints_path"]),
    ]


def _sample(world: dict[str, Any]) -> tuple[int, str]:
    out = io.StringIO()
    code = hvs.main(["sample", *_common(world)], out=out)
    return code, out.getvalue()


def _ticking(step: float = 10.0) -> Callable[[], float]:
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += step
        return state["t"]

    return clock


def _review(
    world: dict[str, Any],
    answers: list[str],
    *extra: str,
    clock: Callable[[], float] | None = None,
    reviewer: str = "kiki",
) -> tuple[int, str]:
    out = io.StringIO()
    code = hvs.main(
        ["review", *_common(world), "--reviewer", reviewer, *extra],
        stream=io.StringIO("".join(a + "\n" for a in answers)),
        out=out,
        clock=clock or _ticking(),
    )
    return code, out.getvalue()


def _verdicts_path(world: dict[str, Any]) -> Path:
    return Path(world["root"]) / "r1-review" / hvs.DEFAULT_VERDICTS_NAME


def _manifest(world: dict[str, Any]) -> hv.SampleManifest:
    manifest, errors = hv.load_manifest(
        Path(world["root"]) / "r1-review" / hvs.DEFAULT_MANIFEST_NAME
    )
    assert errors == [] and manifest is not None
    return manifest


def _rows(world: dict[str, Any]) -> list[dict[str, Any]]:
    text = _verdicts_path(world).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ──────────────────────────────────────────────────────────────────────
# sample
# ──────────────────────────────────────────────────────────────────────
class TestSample:
    def test_writes_deterministic_manifest_with_both_purposes(self, world: dict[str, Any]) -> None:
        code, out = _sample(world)
        assert code == 0 and "MANIFEST_WRITTEN=True" in out
        manifest = _manifest(world)
        assert sorted(manifest.population) == sorted(h.hint_id for h in world["hints"])
        assert set(manifest.machine_undecided_hint_ids) >= {"h-short-l1"}
        assert "h-long-l1" not in manifest.machine_undecided_hint_ids  # 대조군 — 기계 clean
        # 겹치는 대상은 판정 대상에서 한 번만
        assert len(manifest.work_hint_ids) == len(set(manifest.work_hint_ids)) == 4

    def test_identical_rerun_keeps_file_and_different_content_is_refused(
        self, world: dict[str, Any]
    ) -> None:
        assert _sample(world)[0] == 0
        path = Path(world["root"]) / "r1-review" / hvs.DEFAULT_MANIFEST_NAME
        before = path.read_bytes()
        code, out = _sample(world)
        assert (code, path.read_bytes()) == (0, before)
        assert "MANIFEST_WRITTEN=EXISTS_IDENTICAL" in out
        changed = [h.model_dump(mode="json") for h in world["hints"]]
        changed[0]["content"] = "다른 본문으로 바꿨어요"
        _write(world["hints_path"], changed)
        code, out = _sample(world)
        assert code == 2 and "MANIFEST_WRITTEN=False" in out
        assert path.read_bytes() == before  # 덮어쓰지 않았다

    def test_sample_output_names_no_individual_machine_verdict(self, world: dict[str, Any]) -> None:
        _, out = _sample(world)
        assert "h-short-l1" not in out and _GATE_SENTINEL not in out


# ──────────────────────────────────────────────────────────────────────
# review — 맹검(R19-01)
# ──────────────────────────────────────────────────────────────────────
_FORBIDDEN_IN_REVIEW = (
    _GATE_SENTINEL,
    _OTHER_SENTINEL,
    "gate_report",
    "answer_leakage",
    "value_verdict",
    "exposed",
    "machine",
    "semantic_sample",
    "machine_undecided",
    "not_leaked",
    "reveals",
    "기계",
    "표본",
)


class TestBlind:
    def test_review_output_never_shows_machine_or_other_verdicts(
        self, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _sample(world)[0] == 0
        manifest = _manifest(world)
        # 다른 판정자의 기존 판정(근거에 표지) — 화면에 나오면 안 된다
        other_hint = world["hints"][0]
        hv.append_verdict(
            _verdicts_path(world),
            hv.HintHumanVerdict(
                schema_version="hint-human-verdict/v1",
                hint_id=other_hint.hint_id,
                problem_id=other_hint.solution_step_ref.problem_id,
                reviewer="other",
                judged_at="2026-10-29T00:00:00Z",  # type: ignore[arg-type]
                verdict=hv.HintVerdict.LEAKED,
                rationale=_OTHER_SENTINEL,
                purpose=manifest.purpose_of(other_hint.hint_id),
                sample_id=manifest.sample_id,
                content_fingerprint=hv.hint_review_fingerprint(world["cus"][0], other_hint),
                review_session_id=uuid.uuid4(),
                bypassed=False,
            ),
        )

        # review 경로는 기계 판정을 계산조차 하지 않는다 — 부르면 터진다
        def _boom(*_a: object, **_k: object) -> None:
            raise AssertionError("review가 기계 판정을 불렀다")

        monkeypatch.setattr(hvs, "hint_machine_verdict", _boom)
        answers = []
        for _ in range(4):
            answers += ["2", "숫자와 식이 드러나지 않음", "y"]
        code, out = _review(world, answers)
        assert code == 0
        for token in _FORBIDDEN_IN_REVIEW:
            assert token not in out, token
        # 정답은 보여 준다(누설 판정에 필요) — 대조군
        assert "정답: 25" in out and "정답: 3" in out
        assert "힌트 본문: 기울기부터 구해 볼까요?" in out

    def test_render_item_lines_are_exactly_the_review_view(self, world: dict[str, Any]) -> None:
        out = io.StringIO()
        hint = world["hints"][0]
        hvs.render_item(out, 1, 4, hvs.WorkItem(hint=hint, cu_row=world["cus"][0]))
        body = [line for line in out.getvalue().splitlines() if line and not line.startswith("─")]
        assert body == [
            f"[1/4] 힌트 {hint.hint_id}",
            f"문항: {world['cus'][0]['question_text']}",
            "정답: 25",
            "힌트 단계: L1",
            "힌트 본문: 기울기부터 구해 볼까요?",
        ]


# ──────────────────────────────────────────────────────────────────────
# review — 기록·실수 방지
# ──────────────────────────────────────────────────────────────────────
class TestRecord:
    def test_records_contract_rows_with_purpose_and_fingerprint(
        self, world: dict[str, Any]
    ) -> None:
        assert _sample(world)[0] == 0
        manifest = _manifest(world)
        code, out = _review(world, ["1", "정답 3을 세 단계로 암시", "y", "q"])
        assert code == 0 and "SESSION_RECORDED=1" in out
        rows = _rows(world)
        assert len(rows) == 1
        verdict = hv.HintHumanVerdict.model_validate(rows[0])
        assert verdict.reviewer == "kiki" and verdict.bypassed is False
        assert verdict.sample_id == manifest.sample_id
        assert verdict.purpose is manifest.purpose_of(verdict.hint_id)
        hint = next(h for h in world["hints"] if h.hint_id == verdict.hint_id)
        cu = next(
            c for c in world["cus"] if c["problem_id"] == str(hint.solution_step_ref.problem_id)
        )
        assert verdict.content_fingerprint == hv.hint_review_fingerprint(cu, hint)

    def test_input_lock_discards_instant_answer(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        times = iter([0.0, 0.5, 9.0])  # 띄움 · 0.5초 뒤 입력(폐기) · 9초 뒤 입력

        def clock() -> float:
            return next(times, 100.0)

        code, out = _review(world, ["1", "1", "근거", "y", "q"], clock=clock)
        assert code == 0
        assert "화면을 읽기 전에 입력됐습니다" in out
        assert len(_rows(world)) == 1  # 폐기된 첫 입력은 판정이 아니다

    def test_blank_rationale_is_asked_again_and_n_redoes(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        code, out = _review(world, ["1", "", "   ", "첫 근거", "n", "2", "다시 본 근거", "y", "q"])
        assert code == 0 and "근거가 비었습니다" in out
        rows = _rows(world)
        assert [(r["verdict"], r["rationale"]) for r in rows] == [("not_leaked", "다시 본 근거")]

    def test_skip_records_nothing(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        code, out = _review(world, ["s", "s", "s", "s"])
        assert code == 0 and "SESSION_SKIPPED=4" in out
        assert _rows(world) == []

    def test_eof_mid_item_is_a_clean_stop(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        code, out = _review(world, ["1", "근거"])  # 확인 전에 입력이 끝남
        assert code == 0 and "SESSION_STATE=중단" in out and _rows(world) == []


# ──────────────────────────────────────────────────────────────────────
# review — 정지·재개·재판정
# ──────────────────────────────────────────────────────────────────────
class TestStopResume:
    def test_resume_skips_already_judged(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        assert _review(world, ["2", "근거 하나", "y", "q"])[0] == 0
        code, out = _review(world, ["q"])
        assert code == 0 and "이미 판정 1건(건너뜀)" in out and "[2/4]" in out

    def test_other_reviewer_does_not_count_as_done(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        assert _review(world, ["2", "근거 하나", "y", "q"])[0] == 0
        code, out = _review(world, ["q"], reviewer="second")
        assert code == 0 and "이미 판정 0건" in out

    def test_rejudge_appends_and_keeps_history(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        answers = []
        for _ in range(4):
            answers += ["2", "첫 판정", "y"]
        assert _review(world, answers)[0] == 0
        first = _rows(world)
        target = first[0]["hint_id"]
        code, out = _review(world, ["1", "다시 보니 누설", "y"], "--rejudge", target)
        assert code == 0
        rows = _rows(world)
        assert len(rows) == 5 and rows[:4] == first  # 앞선 판정은 그대로
        assert (rows[4]["hint_id"], rows[4]["verdict"]) == (target, "leaked")

    def test_rejudge_unknown_hint_is_input_failure(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        code, out = _review(world, [], "--rejudge", "no-such-hint")
        assert code == hvs.EXIT_INPUT and "--rejudge" in out

    def test_preflight_failure_shows_nothing(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        blocker = Path(world["root"]) / "blocker"
        blocker.write_text("파일이라 폴더로 쓸 수 없다", encoding="utf-8")
        target = blocker / "hint_verdicts.jsonl"  # 부모가 파일 — 쓸 수 없다
        code, out = _review(world, ["1", "근거", "y"], "--verdicts", str(target))
        assert code == hvs.EXIT_RECORD and "WRITE_PREFLIGHT_FAILED" in out
        assert "[1/" not in out and "힌트 본문" not in out

    def test_record_failure_stops_the_session(
        self, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _sample(world)[0] == 0

        def _fail(*_a: object, **_k: object) -> None:
            raise PermissionError("locked")

        monkeypatch.setattr(hvs, "append_verdict", _fail)
        code, out = _review(world, ["1", "근거", "y", "2", "근거2", "y"])
        assert code == hvs.EXIT_RECORD
        assert "기록 실패 — PermissionError" in out and "[2/4]" not in out
        assert "SESSION_STATE=기록 실패로 정지" in out

    def test_corrupt_existing_file_is_not_appended_to(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        path = _verdicts_path(world)
        path.write_text('{"hint_id": "x"\n', encoding="utf-8")
        code, out = _review(world, ["1", "근거", "y"])
        assert code == hvs.EXIT_INPUT and "손상" in out
        assert path.read_text(encoding="utf-8") == '{"hint_id": "x"\n'

    def test_existing_file_with_time_going_backwards_is_not_appended_to(
        self, world: dict[str, Any]
    ) -> None:
        """확인 리뷰 P2-1 — 순서가 깨진 파일에 이어 쓰면 측정기가 파일 전체를 거부한다."""
        assert _sample(world)[0] == 0
        manifest = _manifest(world)
        path = _verdicts_path(world)
        for stamp in ("2026-10-02T00:00:00Z", "2026-10-01T00:00:00Z"):  # 두 번째가 더 이르다
            hint = world["hints"][0]
            hv.append_verdict(
                path,
                hv.HintHumanVerdict(
                    schema_version="hint-human-verdict/v1",
                    hint_id=hint.hint_id,
                    problem_id=hint.solution_step_ref.problem_id,
                    reviewer="kiki",
                    judged_at=stamp,  # type: ignore[arg-type]
                    verdict=hv.HintVerdict.NOT_LEAKED,
                    rationale="근거",
                    purpose=manifest.purpose_of(hint.hint_id),
                    sample_id=manifest.sample_id,
                    content_fingerprint=hv.hint_review_fingerprint(world["cus"][0], hint),
                    review_session_id=uuid.uuid4(),
                    bypassed=False,
                ),
            )
        before = path.read_bytes()
        code, out = _review(world, ["1", "근거", "y"])
        assert code == hvs.EXIT_INPUT and "순서 손상" in out
        assert path.read_bytes() == before

    def test_clock_running_backwards_stops_before_writing(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        manifest = _manifest(world)
        items, errors = hvs.prepare_work(manifest, world["cus"], world["hints"])
        assert errors == []
        path = _verdicts_path(world)
        out = io.StringIO()
        outcome = hvs.run_review_session(
            items,
            manifest=manifest,
            verdicts_path=path,
            reviewer="kiki",
            done=set(),
            stream=io.StringIO("1\n근거\ny\n"),
            out=out,
            clock=_ticking(),
            now=lambda: datetime(2026, 10, 1, tzinfo=UTC),
            not_before=datetime(2026, 10, 2, tzinfo=UTC),
        )
        assert outcome.record_failed and outcome.recorded == 0
        assert "시계 역행" in out.getvalue() and not path.exists()

    @pytest.mark.parametrize("reviewer", ["김철수", "kim cheolsu", "", "a" * 33])
    def test_name_like_reviewer_id_is_refused(self, world: dict[str, Any], reviewer: str) -> None:
        assert _sample(world)[0] == 0
        code, out = _review(world, [], reviewer=reviewer)
        assert code == hvs.EXIT_INPUT and "판정자 ID" in out

    def test_changed_hint_after_sampling_is_refused(self, world: dict[str, Any]) -> None:
        assert _sample(world)[0] == 0
        changed = [h.model_dump(mode="json") for h in world["hints"]]
        changed[0]["content"] = "바뀐 본문"
        _write(world["hints_path"], changed)
        code, out = _review(world, ["1", "근거", "y"])
        assert code == hvs.EXIT_INPUT and "모집단" in out
