"""HARN-118 — 사고 대장의 계약 동결.

이 파일이 지키는 것은 "대장이 존재한다"가 아니라 **"위반 상태에서 실제로 거부
신호를 낸다"** 이다(CLAUDE.md: 변별력 없는 검증 스텝 금지). 그래서 핵심 축마다
*위반 주입*과 *정상 대조군*을 쌍으로 둔다 — 대조군이 없으면 "전부 거부"라는 과잉
수정이 그대로 통과한다(2026-09-08 `if ! gh api` 사고의 교훈).

축 4개:
  ① 스키마 — 폐쇄 집합·형식 위반이 잡히는가 (그리고 정상은 통과하는가)
  ② 회차 — `nth`가 날짜 순으로 계산되고, 미배정은 `None`으로 남는가
  ③ 2회차 코드 착지 강제 — rule-only 등재가 exit 1인가, code 참조를 붙이면 0인가
  ④ 재계산 일치 — 시드 676건의 집계가 보고서 §2 표와 한 자리도 다르지 않은가
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import incidents as inc
import pytest

import backlog as cli

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_JSONL = REPO_ROOT / "docs/data/recurring_failure_ledger_2026-09-20/incidents.jsonl"
TAXONOMY_DOC = REPO_ROOT / "docs/reviews/recurring_failure_taxonomy_2026-09-20.md"


def _incident(**overrides: object) -> inc.Incident:
    base: dict[str, object] = {
        "date": "2026-09-01",
        "cat": "B",
        "title": "가드가 정상 입력에서만 초록이었다",
    }
    base.update(overrides)
    return inc.Incident(**base)  # type: ignore[arg-type]


# ── ① 스키마 ────────────────────────────────────────────────────────────────


class TestSchema:
    def test_minimal_record_is_valid(self) -> None:
        """정상 대조군 — 이것이 통과하지 않으면 아래 거부들은 변별력이 없다."""
        assert _incident().validate() == []

    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [
            ("date", "2026-9-1", "date"),
            ("cat", "Z", "cat"),
            ("title", "   ", "title"),
            ("damage_class", "catastrophic", "damage_class"),
            ("fix_form", "prose", "fix_form"),
            ("who_caught", "santa", "who_caught"),
            ("series_id", "Unmerged_Isolation", "series_id"),
            ("line", -3, "line"),
            ("reviewed", "false", "reviewed"),
        ],
    )
    def test_each_field_violation_is_caught(self, field: str, value: object, needle: str) -> None:
        errors = _incident(**{field: value}).validate()
        assert errors, f"{field}={value!r} 가 위반으로 잡히지 않았다"
        assert any(needle in e for e in errors), errors

    def test_unknown_key_is_an_error_not_silently_dropped(self) -> None:
        """오타 난 키가 조용히 사라지면 그 필드는 영원히 비어 있게 된다."""
        record, errors = inc.from_dict(
            {"date": "2026-09-01", "cat": "B", "title": "t", "fix_forms": "code"}, source="x"
        )
        assert record is None
        assert errors and "fix_forms" in errors[0]

    def test_ledger_roundtrip_preserves_every_field(self, tmp_path: Path) -> None:
        original = _incident(
            sub="픽스처 절 미접촉",
            cause="경계 절을 밟는 입력이 픽스처에 없었다",
            damage="왕복 1회",
            damage_class="wasted_round",
            fix_form="rule+code",
            fix_ref="tests/harness/test_incidents.py",
            series_id="fixture-clause-untouched",
            who_caught="bot",
            quote="M1 생존으로 발각",
            src="MEMORY.md",
            line=42,
            series_raw="동일 유형 3회차",
            series_source="manual",
            reviewed=True,
        )
        inc.save_incidents(tmp_path, [original])
        loaded, errors = inc.load_incidents(tmp_path)
        assert errors == []
        assert loaded == [original]

    def test_corrupt_line_names_the_exception_type(self, tmp_path: Path) -> None:
        """침묵 실패 금지 — 무타입 경고는 8일 무증상 전멸의 원인이었다."""
        (tmp_path / "backlog").mkdir()
        (tmp_path / "backlog" / inc.LEDGER_NAME).write_text("{not json\n", encoding="utf-8")
        _, errors = inc.load_incidents(tmp_path)
        assert len(errors) == 1
        assert "JSONDecodeError" in errors[0]

    def test_missing_ledger_is_empty_not_an_error(self, tmp_path: Path) -> None:
        assert inc.load_incidents(tmp_path) == ([], [])


# ── ② 회차 계산 ─────────────────────────────────────────────────────────────


class TestNth:
    def test_nth_follows_date_order_not_file_order(self) -> None:
        """과거 사고를 뒤늦게 append해도 회차가 올바르다 — 파일 위치에 의존하지 않는다."""
        ledger = [
            _incident(date="2026-09-01", series_id="alpha"),
            _incident(date="2026-07-01", series_id="alpha"),
            _incident(date="2026-08-01", series_id="alpha"),
        ]
        assert inc.compute_nth(ledger) == [3, 1, 2]

    def test_unassigned_series_is_none_not_one(self) -> None:
        """모른다 ≠ 1회차. None을 1로 접으면 2회차 강제가 통째로 무력해진다."""
        ledger = [_incident(), _incident(), _incident(series_id="alpha")]
        assert inc.compute_nth(ledger) == [None, None, 1]

    def test_series_are_counted_independently(self) -> None:
        ledger = [
            _incident(date="2026-07-01", series_id="alpha"),
            _incident(date="2026-07-02", series_id="beta"),
            _incident(date="2026-07-03", series_id="alpha"),
        ]
        assert inc.compute_nth(ledger) == [1, 1, 2]

    def test_same_date_ties_break_on_file_position_deterministically(self) -> None:
        ledger = [
            _incident(date="2026-07-01", series_id="alpha", title="먼저"),
            _incident(date="2026-07-01", series_id="alpha", title="나중"),
        ]
        assert inc.compute_nth(ledger) == [1, 2]

    def test_next_nth_does_not_mutate_the_ledger(self) -> None:
        ledger = [_incident(series_id="alpha")]
        assert inc.next_nth(ledger, _incident(date="2026-09-02", series_id="alpha")) == 2
        assert len(ledger) == 1


# ── ③ 2회차 코드 착지 강제 (acceptance ②의 뮤테이션) ───────────────────────


class TestRepeatSettlement:
    """핵심 변별력. 2회차 rule-only 주입 → 거부, code 참조 부착 → 통과."""

    @staticmethod
    def _first() -> inc.Incident:
        return _incident(date="2026-07-01", series_id="alpha", fix_form="rule")

    def test_first_occurrence_may_be_prose_only(self) -> None:
        """1회차는 산문 대책도 허용한다 — 계열인 줄 모르는 시점이기 때문이다."""
        assert inc.repeat_settlement_error([], self._first()) is None

    def test_second_occurrence_with_rule_only_is_rejected(self) -> None:
        error = inc.repeat_settlement_error(
            [self._first()], _incident(date="2026-08-01", series_id="alpha", fix_form="rule")
        )
        assert error is not None
        assert "alpha" in error and "2회차" in error

    @pytest.mark.parametrize("fix_form", ["rule", "none", "unknown"])
    def test_every_unsettled_form_is_rejected_on_repeat(self, fix_form: str) -> None:
        """대책을 안 적은 것과 산문만 적은 것은 집행 지점이 없다는 점에서 같다."""
        error = inc.repeat_settlement_error(
            [self._first()], _incident(date="2026-08-01", series_id="alpha", fix_form=fix_form)
        )
        assert error is not None

    @pytest.mark.parametrize("fix_form", ["rule", "none", "unknown"])
    def test_unsettled_form_is_rejected_even_with_a_reference(self, fix_form: str) -> None:
        """`fix_form` 절의 **반례** — 참조가 있어도 형태가 산문이면 거부여야 한다.

        위 테스트는 `fix_ref`가 비어 있어 *두 번째* 절(참조 요구)이 대신 잡는다. 즉
        `SETTLING_FIX_FORMS`에 'rule'을 몰래 넣어도 통과한다 — 그 절을 한 번도 밟지
        않기 때문이다(뮤테이션 M3 생존으로 발각. CLAUDE.md "픽스처가 그 절을 실제로
        밟는가" 2026-09-07). 참조를 채워 첫 절만 남긴 것이 이 케이스다.
        """
        error = inc.repeat_settlement_error(
            [self._first()],
            _incident(
                date="2026-08-01",
                series_id="alpha",
                fix_form=fix_form,
                fix_ref="tests/harness/test_incidents.py",
            ),
        )
        assert error is not None
        assert "fix_form" in error

    def test_prose_is_not_counted_as_settlement(self) -> None:
        """상환 집합의 내용 자체를 동결한다 — 'rule'이 들어오면 그것이 곧 회귀다."""
        assert "rule" not in inc.SETTLING_FIX_FORMS
        assert inc.SETTLING_FIX_FORMS == frozenset({"code", "task", "rule+code", "rule+task"})

    @pytest.mark.parametrize("fix_form", ["code", "task", "rule+code", "rule+task"])
    def test_settled_forms_pass_on_repeat(self, fix_form: str) -> None:
        """대조군 — 이것이 통과하지 않으면 위 거부는 '전부 거부'라는 과잉 수정이다."""
        assert (
            inc.repeat_settlement_error(
                [self._first()],
                _incident(
                    date="2026-08-01",
                    series_id="alpha",
                    fix_form=fix_form,
                    fix_ref="tests/harness/test_incidents.py",
                ),
            )
            is None
        )

    def test_settled_form_without_a_reference_is_rejected(self) -> None:
        """'code'라고만 적고 어디인지 비면 다음 세션이 그 대책을 찾을 수 없다."""
        error = inc.repeat_settlement_error(
            [self._first()],
            _incident(date="2026-08-01", series_id="alpha", fix_form="code", fix_ref="  "),
        )
        assert error is not None and "fix_ref" in error

    def test_unassigned_repeat_is_not_blocked(self) -> None:
        """계열 미배정은 회차를 모르는 상태다 — 모른다고 거부하면 등재 자체가 막힌다."""
        assert (
            inc.repeat_settlement_error([_incident(fix_form="rule")], _incident(fix_form="rule"))
            is None
        )


# ── ③-b CLI 경로 (거부가 exit code로 나오는가) ──────────────────────────────


@pytest.fixture
def seeded_repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


def _add(*argv: str) -> int:
    return cli.main(["incident", "add", *argv])


class TestIncidentCli:
    def test_repeat_rule_only_exits_1_and_names_series_and_nth(
        self, seeded_repo: Path, capsys
    ) -> None:
        assert (
            _add(
                "--title",
                "1회차",
                "--cat",
                "B",
                "--date",
                "2026-07-01",
                "--series",
                "alpha",
                "--fix-form",
                "rule",
            )
            == 0
        )
        capsys.readouterr()
        assert (
            _add(
                "--title",
                "2회차",
                "--cat",
                "B",
                "--date",
                "2026-08-01",
                "--series",
                "alpha",
                "--fix-form",
                "rule",
            )
            == 1
        )
        err = capsys.readouterr().err
        assert "alpha" in err and "2회차" in err

    def test_same_repeat_with_code_reference_exits_0(self, seeded_repo: Path, capsys) -> None:
        """같은 주입에 참조만 붙이면 GREEN — 이 대비가 게이트의 변별력이다."""
        assert (
            _add(
                "--title",
                "1회차",
                "--cat",
                "B",
                "--date",
                "2026-07-01",
                "--series",
                "alpha",
                "--fix-form",
                "rule",
            )
            == 0
        )
        assert (
            _add(
                "--title",
                "2회차",
                "--cat",
                "B",
                "--date",
                "2026-08-01",
                "--series",
                "alpha",
                "--fix-form",
                "code",
                "--fix-ref",
                "tests/harness/test_incidents.py",
            )
            == 0
        )
        capsys.readouterr()
        ledger, errors = inc.load_incidents(seeded_repo)
        assert errors == []
        assert [i.title for i in ledger] == ["1회차", "2회차"]

    def test_rejected_add_writes_nothing(self, seeded_repo: Path, capsys) -> None:
        """거부는 판정이다 — 거부하면서 절반 쓰면 대장이 오염된다."""
        assert (
            _add(
                "--title",
                "1회차",
                "--cat",
                "B",
                "--date",
                "2026-07-01",
                "--series",
                "alpha",
                "--fix-form",
                "rule",
            )
            == 0
        )
        assert (
            _add(
                "--title",
                "2회차",
                "--cat",
                "B",
                "--date",
                "2026-08-01",
                "--series",
                "alpha",
                "--fix-form",
                "rule",
            )
            == 1
        )
        capsys.readouterr()
        ledger, _ = inc.load_incidents(seeded_repo)
        assert [i.title for i in ledger] == ["1회차"]

    def test_add_records_an_event_with_series_and_nth(self, seeded_repo: Path, capsys) -> None:
        import store

        assert (
            _add(
                "--title",
                "사고",
                "--cat",
                "G",
                "--series",
                "alpha",
                "--fix-form",
                "code",
                "--fix-ref",
                "HARN-118",
            )
            == 0
        )
        capsys.readouterr()
        text = "".join(p.read_text(encoding="utf-8") for p in store.event_paths(seeded_repo))
        events = [json.loads(line) for line in text.splitlines() if '"incident_add"' in line]
        assert len(events) == 1
        assert events[0]["id"] == "alpha" and events[0]["nth"] == 1

    def test_validate_catches_hand_edited_ledger(self, seeded_repo: Path, capsys) -> None:
        """손편집 금지의 집행 지점 — validate가 exit 1을 내는가 (acceptance ①)."""
        assert cli.main(["validate", "--quiet"]) == 0
        path = inc.ledger_path(seeded_repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"date": "2026-09-01", "cat": "Z", "title": "손편집"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        assert cli.main(["validate", "--quiet"]) == 1
        assert "cat 'Z'" in capsys.readouterr().err

    def test_check_edit_hook_sees_the_same_violation(
        self, seeded_repo: Path, capsys, monkeypatch
    ) -> None:
        """훅과 CLI가 같은 함수를 쓰는지 — 한쪽만 보면 배선이 반쪽이다."""
        import io

        path = inc.ledger_path(seeded_repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"date": "2026-09-01", "cat": "Z", "title": "x"}\n', encoding="utf-8")
        payload = json.dumps({"tool_input": {"file_path": str(path)}})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))
        assert cli.main(["check-edit"]) == 2

    def test_seed_refuses_to_overwrite_without_force(self, seeded_repo: Path, capsys) -> None:
        assert cli.main(["incident", "seed", "--source", str(SEED_JSONL)]) == 0
        capsys.readouterr()
        assert cli.main(["incident", "seed", "--source", str(SEED_JSONL)]) == 1
        assert "--force" in capsys.readouterr().err

    def test_report_json_shape(self, seeded_repo: Path, capsys) -> None:
        assert _add("--title", "사고", "--cat", "A", "--fix-form", "code", "--fix-ref", "x") == 0
        capsys.readouterr()
        assert cli.main(["incident", "report", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total"] == 1
        assert set(data) >= {
            "by_cat",
            "by_month",
            "by_damage",
            "by_fix_form",
            "series",
            "unassigned_series",
            "max_series_nth",
            "rule_only_ratio",
        }


# ── ④ 시드 재계산 일치 (acceptance ③) ───────────────────────────────────────


def _doc_table_counts(pattern: str, *, group_label: int, group_count: int) -> dict[str, int]:
    """보고서 마크다운 표에서 (라벨, 건수)를 뽑는다 — 굵게(**) 표기를 벗긴다."""
    text = TAXONOMY_DOC.read_text(encoding="utf-8")
    found: dict[str, int] = {}
    for match in re.finditer(pattern, text, flags=re.MULTILINE):
        label = match.group(group_label).replace("*", "").strip()
        found[label] = int(match.group(group_count).replace("*", "").replace(",", ""))
    return found


class TestSeedRecalculationMatchesReport:
    """시드 676건의 집계가 보고서 §2와 한 자리도 다르지 않아야 한다.

    이 대조가 없으면 대장은 '보고서와 무관한 숫자 676개'가 된다. 대조가 깨지면
    둘 중 하나가 틀린 것이고, 어느 쪽이든 알아야 한다.
    """

    @pytest.fixture
    def report(self) -> inc.Report:
        seeded, errors = inc.seed_from_jsonl(SEED_JSONL)
        assert errors == [], errors[:5]
        return inc.aggregate(seeded)

    def test_total_is_676(self, report: inc.Report) -> None:
        assert report.total == 676

    def test_by_cat_matches_report_section_2_2(self, report: inc.Report) -> None:
        # `| **B** | 보호 장치 자기위장 | ... | **177** | **26%** |`
        doc = _doc_table_counts(
            r"^\| \*{0,2}([A-K])\*{0,2} \| [^|]+ \| [^|]+ \| (\*{0,2}[\d,]+\*{0,2}) \|",
            group_label=1,
            group_count=2,
        )
        assert len(doc) == 11, doc
        assert report.by_cat == doc

    def test_by_month_matches_report_section_2_1(self, report: inc.Report) -> None:
        # `| 2026-07 | 133 | 43 | 3.09 | ... |`
        doc = _doc_table_counts(
            r"^\| (2026-\d{2})[^|]*\| ([\d,]+) \|", group_label=1, group_count=2
        )
        assert len(doc) == 5, doc
        assert report.by_month == doc

    def test_by_damage_matches_report_section_2_4(self, report: inc.Report) -> None:
        doc = _doc_table_counts(
            r"^\| \*{0,2}(none|latent_days|wasted_round|false_pass|discarded_work|ci_red"
            r"|data_loss)\*{0,2} \| [^|]+ \| (\*{0,2}[\d,]+\*{0,2}) \|",
            group_label=1,
            group_count=2,
        )
        assert len(doc) == 7, doc
        assert report.by_damage == doc

    def test_by_fix_form_matches_report_section_2_6(self, report: inc.Report) -> None:
        """§2.6 '사고 676건' 열 — code 297 · task 159 · none/unknown 114 · rule 72 · 혼합 34."""
        assert report.by_fix_form["code"] == 297
        assert report.by_fix_form["task"] == 159
        assert report.by_fix_form["none"] == 114
        assert report.by_fix_form["rule"] == 72
        assert report.by_fix_form["rule+code"] + report.by_fix_form["rule+task"] == 34
        assert sum(report.by_fix_form.values()) == 676

    def test_every_seed_record_keeps_its_original_series_text(self) -> None:
        """파생 series_id가 원문을 덮지 않는다 — 추정 금지의 집행."""
        raw_source = [
            json.loads(line)
            for line in SEED_JSONL.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        seeded, _ = inc.seed_from_jsonl(SEED_JSONL)
        assert sorted(i.series_raw for i in seeded) == sorted(
            str(r.get("series", "") or "") for r in raw_source
        )

    def test_seed_is_unreviewed_and_marks_derived_series(self) -> None:
        seeded, _ = inc.seed_from_jsonl(SEED_JSONL)
        assert all(not i.reviewed for i in seeded)
        assert all((i.series_source == "seed_keyword") == bool(i.series_id) for i in seeded)

    def test_generic_repeat_counters_are_deliberately_unassigned(self) -> None:
        """'반복 실수 9회차'는 유형이 아니라 통산 카운터다 — 계열로 묶으면 회차가 거짓이 된다."""
        assert inc.series_id_from_raw("반복 실수 9회차") == ""
        assert inc.series_id_from_raw("미병합 고립 4회차") == "unmerged-isolation"


class TestCommittedLedgerMatchesSeed:
    """저장소에 커밋된 대장이 시드 원천과 같은지 — 손편집·표류 탐지."""

    def test_committed_ledger_is_schema_clean(self) -> None:
        ledger, errors = inc.load_incidents(REPO_ROOT)
        assert errors == [], errors[:5]
        assert len(ledger) == 676

    def test_committed_ledger_recomputes_to_the_same_tables(self) -> None:
        ledger, _ = inc.load_incidents(REPO_ROOT)
        seeded, _ = inc.seed_from_jsonl(SEED_JSONL)
        assert inc.aggregate(ledger).to_json() == inc.aggregate(seeded).to_json()
