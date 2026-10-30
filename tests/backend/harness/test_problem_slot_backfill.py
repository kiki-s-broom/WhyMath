"""기존 문항 6슬롯 백필 CLI — 바이트 계약·모드·실 코퍼스 정합 (P3-05 3단계).

합성 코퍼스(tmp_path)와 주입한 오개념 판정으로 CLI의 동작을 잠그고, 마지막에 실제 커밋된 코퍼스에
같은 계산을 돌려 "규칙과 코퍼스가 어긋나지 않았다"를 지킨다(드리프트 가드).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from whymath_backend.harness import problem_slot_backfill as cli
from whymath_backend.l1.standards import phase3_coverage as pc
from whymath_backend.l1.standards import phase3_scope as ps
from whymath_backend.l1.standards.phase3_slot_rules import SlotRulesError, load_slot_rules
from whymath_backend.schema.problem_metadata import ProblemSlot, parse_slot_tags

_C1 = "H:test-A"
_BANK = "problem_bank_x"
_BANK2 = "problem_bank_y"


def _rules_file(tmp_path: Path, banks: list[str] | None = None) -> Path:
    doc = {
        "version": 1,
        "banks": banks or [_BANK],
        "scope_concepts": [_C1],
        "rules": [
            {
                "id": "hold-count",
                "when": {"folded_stem_contains": "개수"},
                "slot": None,
                "reason": "다른 개념의 행동",
            },
            {
                "id": "trigger",
                "when": {"has_own_misconception": True},
                "slot": "misconception_trigger",
            },
            {"id": "applied", "when": {"has_own_misconception": False}, "slot": "applied"},
        ],
    }
    path = tmp_path / "rules.yaml"
    if (
        not path.exists()
    ):  # 쓰기 금지 시험(--check)이 규칙 파일 준비에서 스스로 걸리지 않게 한 번만 쓴다
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _row(pid: str, stem: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "problem_id": pid,
        "question_text": stem,
        "answer": "1",
        "answer_explanation": "해설이다",
        "review_status": "approved",
        "tags": [],
        "concepts": [{"concept_src_id": _C1, "role": "PRIMARY", "relevance": 0.9}],
        "problem_type_codes": ["ptype.evaluate-expression"],
        "difficulty_overall": 3.0,
        "distractor_map": [],
    }
    row.update(over)
    return row


def _write(tmp_path: Path, bank: str, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "corpus" / bank / cli.CORPUS_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def _reaches_by_id(ids: set[str]) -> Callable[[pc.ProblemRef], bool]:
    return lambda p: p.problem_id in ids


def _run(
    tmp_path: Path,
    *,
    write: bool = True,
    trig: set[str] | None = None,
    banks: list[str] | None = None,
) -> cli.SlotBackfillReport:
    return cli.run_backfill(
        corpus_root=tmp_path / "corpus",
        rules_path=_rules_file(tmp_path, banks),
        write=write,
        reaches=_reaches_by_id(trig or set()),
        verify_scope=False,
    )


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


class TestApply:
    def test_adds_exactly_one_slot_tag_chosen_by_the_rules(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값을 구하시오"), _row("b", "보기를 고르시오")])
        report = _run(tmp_path, trig={"b"})
        rows = [json.loads(line) for line in _lines(path)]
        assert rows[0]["tags"] == ["p3-slot:applied"]
        assert rows[1]["tags"] == ["p3-slot:misconception_trigger"]
        assert report.changed == 2 and report.written == 2
        assert report.assigned_by_rule == {"applied": 1, "trigger": 1}

    def test_existing_unrelated_tags_are_kept_and_the_slot_is_appended(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값을 구하시오", tags=["calc", "p3-bank"])])
        _run(tmp_path)
        assert json.loads(_lines(path)[0])["tags"] == ["calc", "p3-bank", "p3-slot:applied"]

    def test_a_rewritten_line_keeps_korean_text_literal(self, tmp_path: Path) -> None:
        """코퍼스 기록 규약은 `ensure_ascii=False` 다 — `\\uXXXX` 로 바뀌면 diff 가 줄 전체로 번진다."""
        path = _write(tmp_path, _BANK, [_row("a", "값을 구하시오")])
        _run(tmp_path)
        line = _lines(path)[0]
        assert "값을 구하시오" in line and "\\u" not in line

    def test_only_the_tags_key_changes(self, tmp_path: Path) -> None:
        original = _row("a", "값을 구하시오")
        path = _write(tmp_path, _BANK, [original])
        _run(tmp_path)
        after = json.loads(_lines(path)[0])
        assert {k: v for k, v in after.items() if k != "tags"} == {
            k: v for k, v in original.items() if k != "tags"
        }
        assert list(after) == list(original)  # 키 순서도 그대로다(바이트 계약)

    def test_untouched_rows_keep_their_exact_bytes(self, tmp_path: Path) -> None:
        """재직렬화하면 달라질 줄(공백이 다른 JSON)이 규칙 밖이면 원문 그대로 남는다."""
        path = _write(tmp_path, _BANK, [_row("a", "값을 구하시오")])
        odd = '{"problem_id": "z",  "review_status": "draft", "tags": [], "concepts": []}'
        path.write_text(path.read_text(encoding="utf-8") + odd + "\n", encoding="utf-8")
        _run(tmp_path)
        assert _lines(path)[-1] == odd

    def test_second_run_is_byte_identical(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값을 구하시오"), _row("b", "보기")])
        _run(tmp_path, trig={"b"})
        first = path.read_bytes()
        second_report = _run(tmp_path, trig={"b"})
        assert path.read_bytes() == first
        assert second_report.changed == 0 and second_report.skipped["already-slotted"] == 2

    def test_already_slotted_row_is_not_overwritten(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값", tags=["p3-slot:diagnostic"])])
        before = path.read_bytes()
        report = _run(tmp_path)
        assert path.read_bytes() == before and report.changed == 0

    @pytest.mark.parametrize(
        "over",
        [
            {"review_status": "draft"},
            {"review_status": None},
            {"concepts": [{"concept_src_id": "H:elsewhere", "role": "PRIMARY"}]},
            {"concepts": [{"concept_src_id": _C1, "role": "SECONDARY"}]},
        ],
    )
    def test_rows_outside_the_rules_are_left_alone(
        self, tmp_path: Path, over: dict[str, Any]
    ) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값", **over)])
        before = path.read_bytes()
        report = _run(tmp_path)
        assert path.read_bytes() == before and report.changed == 0

    def test_held_rows_are_counted_and_not_tagged(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "극값의 개수를 구하시오")])
        before = path.read_bytes()
        report = _run(tmp_path, trig={"a"})  # 오개념 연결이 있어도 위의 보류 규칙이 이긴다
        assert path.read_bytes() == before
        assert report.held_by_rule == {"hold-count": 1} and report.changed == 0

    def test_a_row_without_tags_key_gets_one(self, tmp_path: Path) -> None:
        row = _row("a", "값")
        del row["tags"]
        path = _write(tmp_path, _BANK, [row])
        _run(tmp_path)
        assert json.loads(_lines(path)[0])["tags"] == ["p3-slot:applied"]


class TestModes:
    def test_dry_run_reports_but_writes_nothing(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값")])
        before = path.read_bytes()
        report = _run(tmp_path, write=False)
        assert path.read_bytes() == before
        assert report.changed == 1 and report.written is None

    def _cli(self, tmp_path: Path, *flags: str, monkeypatch: pytest.MonkeyPatch) -> int:
        monkeypatch.setattr(cli, "_default_reaches", lambda: _reaches_by_id(set()))
        monkeypatch.setattr(cli, "_check_scope_exists", lambda rules: None)
        return cli.main(
            [
                "--corpus-root",
                str(tmp_path / "corpus"),
                "--rules",
                str(_rules_file(tmp_path)),
                *flags,
            ]
        )

    def test_check_fails_when_a_row_still_needs_a_tag_and_passes_after_backfill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path, _BANK, [_row("a", "값")])
        assert self._cli(tmp_path, "--check", monkeypatch=monkeypatch) == 1
        assert "슬롯 태그를 더할 승인 문항 1건" in capsys.readouterr().err
        assert self._cli(tmp_path, monkeypatch=monkeypatch) == 0  # 기본 모드가 쓴다
        assert self._cli(tmp_path, "--check", monkeypatch=monkeypatch) == 0

    def test_check_does_not_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값")])
        _rules_file(tmp_path)
        before = path.read_bytes()

        def boom(*_: Any, **__: Any) -> None:
            raise AssertionError("--check 가 쓰기 경로에 들어갔다")

        monkeypatch.setattr(Path, "write_text", boom)
        assert self._cli(tmp_path, "--check", monkeypatch=monkeypatch) == 1
        assert path.read_bytes() == before

    def test_dry_run_and_check_are_mutually_exclusive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            self._cli(tmp_path, "--dry-run", "--check", monkeypatch=monkeypatch)
        assert exc.value.code == 2

    def test_dry_run_exits_zero_even_when_work_remains(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--dry-run 은 게이트가 아니다 — 같은 입력에서 --check 만 1 이라는 차이를 대조로 고정한다."""
        _write(tmp_path, _BANK, [_row("a", "값")])
        assert self._cli(tmp_path, "--dry-run", monkeypatch=monkeypatch) == 0
        assert self._cli(tmp_path, "--check", monkeypatch=monkeypatch) == 1


class TestFailureModes:
    def test_missing_bank_is_an_error_not_a_zero_pass(self, tmp_path: Path) -> None:
        _write(tmp_path, _BANK, [_row("a", "값")])
        with pytest.raises(SlotRulesError, match="코퍼스가 없다"):
            _run(tmp_path, banks=[_BANK, "problem_bank_gone"])

    def test_a_failure_in_a_later_bank_leaves_earlier_banks_unwritten(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값")])
        before = path.read_bytes()
        with pytest.raises(SlotRulesError):
            _run(tmp_path, banks=[_BANK, "problem_bank_gone"])
        assert path.read_bytes() == before

    def test_unparsable_line_fails_instead_of_passing_silently(self, tmp_path: Path) -> None:
        path = _write(tmp_path, _BANK, [_row("a", "값")])
        path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            _run(tmp_path)

    def test_scope_concept_missing_from_the_scope_spec_fails(self, tmp_path: Path) -> None:
        """오타 난 개념은 아무 문항에도 안 맞아 0건 통과가 된다 — 범위 명세 실재를 확인한다."""
        _write(tmp_path, _BANK, [_row("a", "값")])
        with pytest.raises(SlotRulesError, match="범위 명세에 없다"):
            cli.run_backfill(
                corpus_root=tmp_path / "corpus",
                rules_path=_rules_file(tmp_path),
                write=False,
                reaches=_reaches_by_id(set()),
                verify_scope=True,
            )

    def test_cli_reports_rule_errors_with_exit_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = cli.main(["--corpus-root", str(tmp_path), "--rules", str(tmp_path / "none.yaml")])
        assert code == 2
        assert "SlotRulesError" in capsys.readouterr().err


# ── 실 코퍼스 ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def spec() -> ps.ScopeSpec:
    return ps.load_scope_spec()


@pytest.fixture(scope="module")
def corpus(spec: ps.ScopeSpec) -> pc.CoverageCorpus:
    return pc.load_corpus(spec)


class TestRealCorpus:
    def test_no_pending_assignment_remains(self) -> None:
        """커밋된 코퍼스에 규칙이 더할 태그가 남아 있지 않다(= `--check` 와 같은 계산).

        스캔 0건은 실패다 — 코퍼스를 못 읽어 아무것도 안 보고 통과하는 길을 막는다.
        """
        report = cli.run_backfill(write=False)
        assert report.scanned > 2000, f"읽은 행이 너무 적다({report.scanned}건)"
        assert report.changed == 0, report.to_json()
        assert report.unmatched == 0

    def test_every_in_scope_problem_has_at_most_one_slot(self, corpus: pc.CoverageCorpus) -> None:
        rules = load_slot_rules()
        in_scope = [
            p
            for p in corpus.problems
            if p.review_status == pc.PROBLEM_ELIGIBLE_STATUS
            and p.primary_src_ids & rules.scope_concepts
        ]
        assert in_scope
        multi = [p.problem_id for p in in_scope if len(parse_slot_tags(p.tags).slots) > 1]
        assert multi == [], multi[:5]

    def test_a_folded_stem_never_fills_two_cells_of_one_concept_among_legacy_rows(
        self, corpus: pc.CoverageCorpus
    ) -> None:
        """같은 문면이 두 칸을 채우면 수치가 부풀려진다. 단, 객관식(오개념 유발)과 단답(대표)이 같은 식을
        묻는 02-07 의 6문면은 형식·오개념 연결이 달라 다른 칸에 들어간다 — 알려진 한계(초안 7절)로 상한을 박는다.
        """
        from whymath_backend.l1.standards.phase3_stem_fold import fold_stem

        rules = load_slot_rules()
        cells: dict[tuple[str, str], set[ProblemSlot]] = {}
        for p in corpus.problems:
            if p.review_status != pc.PROBLEM_ELIGIBLE_STATUS:
                continue
            for concept in p.primary_src_ids & rules.scope_concepts:
                folded = fold_stem(p.question_text)
                if folded is None:
                    continue
                cells.setdefault((concept, folded), set()).update(parse_slot_tags(p.tags).slots)
        overlapping = [k for k, v in cells.items() if len(v) > 1]
        assert len(overlapping) <= 6, overlapping[:3]
