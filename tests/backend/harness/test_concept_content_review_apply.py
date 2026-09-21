"""concept_content_review_apply 단위테스트 — 코퍼스 JSON + DB 갱신(실 DB 없이)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.db.models.concept_content import (
    CONTENT_REVIEW_STATUS_AI_ESTIMATED,
    CONTENT_SCOPE_K12,
    CONTENT_SCOPE_UNIVERSITY,
)
from whymath_backend.harness.concept_content_review_apply import (
    LabelRow,
    apply_labels,
    load_labels,
    main,
)


class _FakeStore:
    """ConceptContentStore 표면 모사 — mark_review_status 호출 기록."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def mark_review_status(self, codes: tuple[str, ...], status: str) -> int:
        self.calls.append((codes, status))
        return len(codes)


def _write_corpus(tmp_path: Path, *, scope: str, codes: list[str]) -> Path:
    path = tmp_path / f"{scope}.json"
    path.write_text(
        json.dumps(
            {
                "scope": scope,
                "content": [
                    {
                        "code": code,
                        "name": f"name-{code}",
                        "subject": "s",
                        "review_status": CONTENT_REVIEW_STATUS_AI_ESTIMATED,
                    }
                    for code in codes
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class TestLoadLabels:
    def test_loads_reviewed_and_others(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text(
            '{"code":"N1","review_status":"reviewed"}\n'
            '{"code":"N2","review_status":"rejected"}\n',
            encoding="utf-8",
        )
        rows = load_labels(path)
        assert [row.review_status for row in rows] == ["reviewed", "rejected"]

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text('\n{"code":"N1","review_status":"reviewed"}\n\n', encoding="utf-8")
        assert len(load_labels(path)) == 1

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "labels.jsonl"
        path.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(ValueError):
            load_labels(path)


class TestApplyLabels:
    def test_reviewed_updates_corpus_and_db(self, tmp_path: Path) -> None:
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1", "N2"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=["G1"])
        fake_store = _FakeStore()

        labels = [
            LabelRow("N1", "reviewed", "kiki", "2026-08-16T00:00:00Z"),
            LabelRow("N2", "ai_estimated", "kiki", "2026-08-16T00:00:00Z"),
        ]
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=fake_store, dry_run=False
        )

        assert report.k12_updated == 1
        assert report.university_updated == 0
        assert report.db_updated == 1
        assert fake_store.calls == [(("N1",), "reviewed")]

        # K-12 JSON에만 반영되었는지 확인
        k12_data = json.loads(k12.read_text(encoding="utf-8"))
        statuses = {r["code"]: r["review_status"] for r in k12_data["content"]}
        assert statuses["N1"] == "reviewed"
        assert statuses["N2"] == CONTENT_REVIEW_STATUS_AI_ESTIMATED

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=["G1"])
        fake_store = _FakeStore()

        labels = [LabelRow("N1", "reviewed", "kiki", "2026-08-16T00:00:00Z")]
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=fake_store, dry_run=True
        )

        # 게이트는 통과해야 한다 — 통과하지 않으면 이 테스트는 dry-run이 아니라 게이트를 본다.
        assert report.gate_violations == []
        assert report.approved_codes == ["N1"]
        assert report.k12_updated == 0
        assert report.university_updated == 0
        assert report.db_updated == 0
        assert fake_store.calls == []

        k12_data = json.loads(k12.read_text(encoding="utf-8"))
        assert k12_data["content"][0]["review_status"] == CONTENT_REVIEW_STATUS_AI_ESTIMATED

    def test_missing_code_in_corpus_is_reported(self, tmp_path: Path) -> None:
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        labels = [LabelRow("MISSING", "reviewed", "kiki", "2026-08-16T00:00:00Z")]
        report = apply_labels(labels, k12_path=k12, university_path=univ, dry_run=True)
        assert report.gate_violations == []
        assert report.missing_in_corpus == ["MISSING"]


class TestApplyCLI:
    def test_main_dry_run(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels.jsonl"
        labels.write_text(
            '{"code":"N1","review_status":"reviewed",'
            '"reviewed_by":"kiki","reviewed_at":"2026-08-16T00:00:00Z"}\n',
            encoding="utf-8",
        )
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        out = tmp_path / "report.json"

        rc = main(
            [
                "--labels",
                str(labels),
                "--k12",
                str(k12),
                "--university",
                str(univ),
                "--dry-run",
                "--json",
                str(out),
            ]
        )
        assert rc == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["approved_count"] == 1
        assert report["k12_updated"] == 0

    def test_main_missing_labels_returns_2(self, tmp_path: Path) -> None:
        rc = main(["--labels", str(tmp_path / "nope.jsonl")])
        assert rc == 2

    def test_main_missing_corpus_code_returns_1(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels.jsonl"
        labels.write_text(
            '{"code":"MISSING","review_status":"reviewed",'
            '"reviewed_by":"kiki","reviewed_at":"2026-08-16T00:00:00Z"}\n',
            encoding="utf-8",
        )
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])

        rc = main(
            [
                "--labels",
                str(labels),
                "--k12",
                str(k12),
                "--university",
                str(univ),
            ]
        )
        assert rc == 1


class TestReviewGateBlocksSelfApproval:
    """검수 게이트 통합 — AI 자기승인·미서명 라벨이 코퍼스·DB에 닿지 않는다.

    2026-09-21 실측: 이 게이트 도입 전에는 아래 3종이 **전건 승격**됐다(코퍼스 3건 + DB 1콜).
    그 상태를 그대로 주입해 차단을 확인한다(CLAUDE.md 실패 주입 규칙).
    """

    def test_unsigned_and_ai_signed_labels_are_all_refused(self, tmp_path: Path) -> None:
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1", "N2", "N3"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        fake_store = _FakeStore()

        labels = [
            LabelRow("N1", "reviewed", None, None),  # 무서명
            LabelRow("N2", "reviewed", "claude", "2026-09-21T00:00:00Z"),  # AI 자기승인
            LabelRow("N3", "reviewed", "", "2026-09-21T00:00:00Z"),  # 빈 서명
        ]
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=fake_store, dry_run=False
        )

        assert report.gate_violations != []
        assert report.k12_updated == 0
        assert report.db_updated == 0
        assert fake_store.calls == []

        # 코퍼스 파일 자체가 안 바뀌었는지 — 리포트 수치만 보면 쓰기를 놓칠 수 있다.
        statuses = {
            r["code"]: r["review_status"]
            for r in json.loads(k12.read_text(encoding="utf-8"))["content"]
        }
        assert set(statuses.values()) == {CONTENT_REVIEW_STATUS_AI_ESTIMATED}

    def test_one_bad_row_refuses_the_whole_batch(self, tmp_path: Path) -> None:
        """fail-closed — 부분 적용을 허용하면 '일부는 서명 없이 들어간다'가 된다."""
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1", "N2", "N3"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        fake_store = _FakeStore()

        labels = [
            LabelRow("N1", "reviewed", "kiki", "2026-09-21T00:00:00Z"),
            LabelRow("N2", "reviewed", "kiki", "2026-09-21T00:00:00Z"),
            LabelRow("N3", "reviewed", None, None),  # 1건만 미서명
        ]
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=fake_store, dry_run=False
        )

        assert report.k12_updated == 0
        assert fake_store.calls == []

    def test_signed_labels_still_promote(self, tmp_path: Path) -> None:
        """성공 방향 대조군 — 없으면 '전부 거부'라는 과잉 수정이 통과한다."""
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=["G1"])
        fake_store = _FakeStore()

        labels = [
            LabelRow("N1", "reviewed", "kiki", "2026-09-21T00:00:00Z"),
            LabelRow("G1", "reviewed", "kiki", "2026-09-21T00:00:00Z"),
        ]
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=fake_store, dry_run=False
        )

        assert report.gate_violations == []
        assert report.k12_updated == 1
        assert report.university_updated == 1  # 대학 축도 같은 게이트를 지난다(acceptance ⑤)
        assert fake_store.calls == [(("N1", "G1"), "reviewed")]

    def test_rejected_rows_need_no_signature(self, tmp_path: Path) -> None:
        """거부 라벨은 코퍼스를 안 건드리므로 서명을 강요하지 않는다(게이트 과잉 방지)."""
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        report = apply_labels(
            [LabelRow("N1", "rejected", None, None)],
            k12_path=k12,
            university_path=univ,
            dry_run=True,
        )
        assert report.gate_violations == []
        assert report.rejected_or_other == ["N1"]

    def test_cli_refuses_unsigned_labels_with_exit_1(self, tmp_path: Path) -> None:
        labels = tmp_path / "labels.jsonl"
        labels.write_text('{"code":"N1","review_status":"reviewed"}\n', encoding="utf-8")
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        out = tmp_path / "report.json"

        rc = main(
            [
                "--labels",
                str(labels),
                "--k12",
                str(k12),
                "--university",
                str(univ),
                "--json",
                str(out),
            ]
        )
        assert rc == 1
        # 침묵 실패 금지 — 리포트에 위반 사유가 남아야 한다.
        assert json.loads(out.read_text(encoding="utf-8"))["gate_violations"] != []
