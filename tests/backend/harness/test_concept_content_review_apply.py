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
from whymath_backend.harness.concept_content_link_context import ContentLink
from whymath_backend.harness.concept_content_review_apply import (
    ApplyReport,
    LabelRow,
    apply_labels,
    load_labels,
    main,
)


class _FakeStore:
    """ConceptContentStore 표면 모사 — mark_review_status 호출 기록."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def mark_review_status(
        self, codes: tuple[str, ...], status: str, *, conflicts: list[str] | None = None
    ) -> int:
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
            LabelRow("N1", "reviewed", "kiki", "2026-08-16T00:00:00Z", True),
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

        labels = [LabelRow("N1", "reviewed", "kiki", "2026-08-16T00:00:00Z", True)]
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
            '{"code":"N1","review_status":"reviewed","link_approved":true,'
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
            LabelRow("N1", "reviewed", None, None, True),  # 무서명
            LabelRow("N2", "reviewed", "claude", "2026-09-21T00:00:00Z", True),  # AI 자기승인
            LabelRow("N3", "reviewed", "", "2026-09-21T00:00:00Z", True),  # 빈 서명
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
            LabelRow("N1", "reviewed", "kiki", "2026-09-21T00:00:00Z", True),
            LabelRow("N2", "reviewed", "kiki", "2026-09-21T00:00:00Z", True),
            LabelRow("N3", "reviewed", None, None, True),  # 1건만 미서명
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
            LabelRow("N1", "reviewed", "kiki", "2026-09-21T00:00:00Z", True),
            LabelRow("G1", "reviewed", "kiki", "2026-09-21T00:00:00Z"),  # 대학 — 연결 없음
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


# ──────────────────────────────────────────────────────────────────────────
# CONT-08 — 연결 승인 게이트: reviewed는 "이 원자에 대한 콘텐츠로 맞다"를 보증하지 않는다
#  (크로스워크 연결은 전건 기계 추정이라, 연결 원자가 있는 K-12 행은 link_approved=true 명시가 필요)
# ──────────────────────────────────────────────────────────────────────────
_SIGNED = ("kiki", "2026-10-03T00:00:00Z")


def _link(*codes: str) -> ContentLink:
    return ContentLink(
        atom_codes=tuple(codes),
        atom_names={c: f"원자-{c}" for c in codes},
        primary_atom_code=codes[0],
        confidence=0.58,
        match_method="standard_code+name",
        mapping_review_status="ai_estimated",
    )


class TestLinkApprovalGate:
    def _run(
        self,
        tmp_path: Path,
        labels: list[LabelRow],
        *,
        links: dict[str, ContentLink],
        univ_codes: list[str] | None = None,
    ) -> tuple[ApplyReport, _FakeStore]:
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1", "N2"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=univ_codes or [])
        store = _FakeStore()
        report = apply_labels(
            labels, k12_path=k12, university_path=univ, store=store, dry_run=False, links=links
        )
        return report, store

    def test_reviewed_without_link_approval_is_refused(self, tmp_path: Path) -> None:
        # 연결이 틀린 콘텐츠 행(주입)은 reviewed 라벨만으로 승격되지 못한다.
        report, store = self._run(
            tmp_path, [LabelRow("N1", "reviewed", *_SIGNED)], links={"N1": _link("A-1", "A-2")}
        )
        assert [v for v in report.gate_violations if "link_approved" in v]
        assert "N1" in report.gate_violations[0]
        assert "2개" in report.gate_violations[0]
        assert report.k12_updated == 0
        assert store.calls == []

    def test_explicit_false_is_refused_too(self, tmp_path: Path) -> None:
        report, store = self._run(
            tmp_path,
            [LabelRow("N1", "reviewed", *_SIGNED, link_approved=False)],
            links={"N1": _link("A-1")},
        )
        assert report.gate_violations
        assert store.calls == []

    def test_link_approved_true_promotes(self, tmp_path: Path) -> None:
        # 성공 방향 대조군 — 없으면 "연결 있으면 전부 거부"라는 과잉 수정이 통과한다.
        report, store = self._run(
            tmp_path,
            [LabelRow("N1", "reviewed", *_SIGNED, link_approved=True)],
            links={"N1": _link("A-1")},
        )
        assert report.gate_violations == []
        assert store.calls == [(("N1",), "reviewed")]

    def test_row_without_links_needs_no_link_approval(self, tmp_path: Path) -> None:
        # 연결이 없는 행(대학·unmapped)은 해당 없음 — 대조군(게이트가 연결 있는 행에만 반응한다).
        report, store = self._run(
            tmp_path,
            [LabelRow("G1", "reviewed", *_SIGNED)],
            links={"N1": _link("A-1")},
            univ_codes=["G1"],
        )
        assert report.gate_violations == []
        assert store.calls == [(("G1",), "reviewed")]

    def test_one_unapproved_link_refuses_the_whole_batch(self, tmp_path: Path) -> None:
        # fail-closed — 연결 승인 누락 1건이 나머지 정상 행까지 막는다(부분 적용 금지).
        report, store = self._run(
            tmp_path,
            [
                LabelRow("N1", "reviewed", *_SIGNED, link_approved=True),
                LabelRow("N2", "reviewed", *_SIGNED),
            ],
            links={"N1": _link("A-1"), "N2": _link("B-1")},
        )
        assert len(report.gate_violations) == 1
        assert "N2" in report.gate_violations[0]
        assert report.k12_updated == 0
        assert store.calls == []

    def test_non_review_rows_are_not_checked(self, tmp_path: Path) -> None:
        # rejected 등은 승격이 아니므로 연결 승인을 요구하지 않는다.
        report, store = self._run(
            tmp_path, [LabelRow("N1", "rejected", *_SIGNED)], links={"N1": _link("A-1")}
        )
        assert report.gate_violations == []
        assert store.calls == []

    def test_label_file_accepts_only_a_real_boolean(self, tmp_path: Path) -> None:
        # 문자열 "true"·숫자 1은 승인이 아니다(모른다 ≠ 맞다) — 불리언만 받는다.
        path = tmp_path / "labels.jsonl"
        path.write_text(
            '{"code":"A","review_status":"reviewed","link_approved":true}\n'
            '{"code":"B","review_status":"reviewed","link_approved":"true"}\n'
            '{"code":"C","review_status":"reviewed","link_approved":1}\n'
            '{"code":"D","review_status":"reviewed"}\n'
            '{"code":"E","review_status":"reviewed","link_approved":false}\n',
            encoding="utf-8",
        )
        assert [r.link_approved for r in load_labels(path)] == [True, None, None, None, False]

    def test_unreadable_links_fail_loudly_instead_of_opening_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 연결 파일을 못 읽었을 때 빈 연결로 대체하면 "연결 없음"으로 읽혀 게이트가 통째로 풀린다.
        import whymath_backend.harness.concept_content_review_apply as apply_mod

        def _boom() -> dict[str, ContentLink]:
            raise FileNotFoundError("crosswalk 부재")

        monkeypatch.setattr(apply_mod, "load_content_links", _boom)
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        store = _FakeStore()
        with pytest.raises(FileNotFoundError):
            apply_labels(
                [LabelRow("N1", "reviewed", *_SIGNED, link_approved=True)],
                k12_path=k12,
                university_path=univ,
                store=store,
            )
        assert store.calls == []

    def test_no_approved_rows_never_reads_links(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import whymath_backend.harness.concept_content_review_apply as apply_mod

        def _boom() -> dict[str, ContentLink]:
            raise AssertionError("승인 행이 없는데 연결을 읽었다")

        monkeypatch.setattr(apply_mod, "load_content_links", _boom)
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        report = apply_labels(
            [LabelRow("N1", "rejected", *_SIGNED)],
            k12_path=k12,
            university_path=univ,
            store=_FakeStore(),
        )
        assert report.gate_violations == []

    def test_real_corpus_every_k12_code_requires_link_approval(self, tmp_path: Path) -> None:
        # 실 코퍼스 전수 — 437행 전부 연결이 있어, link_approved 없는 reviewed 라벨은 전부 거부된다.
        from whymath_backend.harness.concept_content_link_context import load_content_links

        links = load_content_links()
        codes = sorted(links)
        assert len(codes) == 437
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=codes)
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        store = _FakeStore()
        report = apply_labels(
            [LabelRow(c, "reviewed", *_SIGNED) for c in codes],
            k12_path=k12,
            university_path=univ,
            store=store,
            links=links,
        )
        assert len(report.gate_violations) == 437
        assert store.calls == []

    def test_main_returns_gate_exit_code_for_missing_link_approval(self, tmp_path: Path) -> None:
        # CLI 종단 — 실 코퍼스 연결을 읽어 N1 승격을 link_approved 없이 시도하면 exit 1.
        labels = tmp_path / "labels.jsonl"
        labels.write_text(
            '{"code":"N1","review_status":"reviewed",'
            '"reviewed_by":"kiki","reviewed_at":"2026-10-03T00:00:00Z"}\n',
            encoding="utf-8",
        )
        k12 = _write_corpus(tmp_path, scope=CONTENT_SCOPE_K12, codes=["N1"])
        univ = _write_corpus(tmp_path, scope=CONTENT_SCOPE_UNIVERSITY, codes=[])
        rc = main(
            ["--labels", str(labels), "--k12", str(k12), "--university", str(univ), "--dry-run"]
        )
        assert rc == 1
