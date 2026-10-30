"""문제 유형(problem_type_codes) 백필 CLI(S3-27·PB-07) — 바이트 계약·멱등·계보 분류 단위테스트.

핵심 봉인(`problem_corpus_tag` 패턴 동형): ① 미태깅 레코드에 적용하면 `problem_type_codes` 키만
추가되고 나머지 바이트는 그대로 ② 이미 태깅된 레코드는 재적용해도 바이트 무변경(멱등) ③ dry-run은
파일 미기록·통계만 ④ `problem_bank_rephrased_v0`는 계보(부모 "변형" relations) 승계로 태깅하고,
계보로도 추적 불가한 레코드는 미태깅으로 남겨 리포트가 정직하게 센다(침묵 누락 금지 — PB-07이
구 명시 제외를 해제·`EXCLUDED_CORPORA` 좌석은 현재 빈 상태). LLM·DB 0(순수 결정론).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness.problem_type_backfill import main, run_backfill
from whymath_backend.harness.problem_type_mapping import (
    CORPUS_GENERATED_V0,
    CORPUS_P3_CALCULUS1_DIFF_V0,
    CORPUS_P3_DIFFERENTIABILITY_REACH_V0,
    CORPUS_P3_FILL_V0,
    CORPUS_REPHRASED_V0,
    CORPUS_V1,
    PTYPE_CONDITION_SATISFACTION,
    PTYPE_EVALUATE_EXPRESSION,
    TARGET_CORPORA,
)


def _variant_relation(parent_slug: str) -> dict[str, object]:
    """계보(변형) relations 픽스처 — S4-18 영속 형태와 동일 구조."""
    return {"parent_slug": parent_slug, "relation_type": "변형", "similarity_score": 1.0}


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def _generated_v0_record(unit_code: str, *, problem_id: str) -> dict[str, object]:
    return {"problem_id": problem_id, "unit_codes": [unit_code], "slug": f"wm-skel-{problem_id}"}


class TestRunBackfill:
    def test_tags_generated_v0_by_unit_codes(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_GENERATED_V0 / "problems.jsonl",
            [
                _generated_v0_record("QUAD-EQ", problem_id="a"),
                _generated_v0_record("IND-SEQ", problem_id="b"),
            ],
        )
        report = run_backfill(corpus_root=root, write=True)

        by_name = {c.name: c for c in report.corpora}
        gen = by_name[CORPUS_GENERATED_V0]
        assert gen.total == 2
        assert gen.tagged == 2
        assert gen.changed == 2  # 신규 키 추가 — 첫 실행은 전건 변경.

        lines = (
            (root / CORPUS_GENERATED_V0 / "problems.jsonl").read_text(encoding="utf-8").splitlines()
        )
        tagged = [json.loads(line) for line in lines]
        assert tagged[0]["problem_type_codes"] == ["ptype.solve-for-unknown"]
        assert tagged[1]["problem_type_codes"] == ["ptype.generalize-pattern"]

    def test_second_run_is_byte_identical(self, tmp_path: Path) -> None:
        # 2회 실행 바이트 동일(멱등) — 문제_corpus_tag와 동일 계약.
        root = tmp_path / "corpus"
        path = root / CORPUS_GENERATED_V0 / "problems.jsonl"
        _write_jsonl(path, [_generated_v0_record("QUAD-EQ", problem_id="a")])

        run_backfill(corpus_root=root, write=True)
        first_bytes = path.read_bytes()
        second_report = run_backfill(corpus_root=root, write=True)
        second_bytes = path.read_bytes()

        assert first_bytes == second_bytes
        by_name = {c.name: c for c in second_report.corpora}
        assert by_name[CORPUS_GENERATED_V0].changed == 0  # 무변경(이미 일치).

    def test_only_problem_type_codes_key_changes(self, tmp_path: Path) -> None:
        """바이트 계약 — 다른 필드는 절대 건드리지 않는다."""
        root = tmp_path / "corpus"
        record = {
            "problem_id": "a",
            "unit_codes": ["QUAD-EQ"],
            "question_text": "이차방정식 문제",
            "answer": "3",
        }
        _write_jsonl(root / CORPUS_GENERATED_V0 / "problems.jsonl", [record])
        run_backfill(corpus_root=root, write=True)
        result = json.loads(
            (root / CORPUS_GENERATED_V0 / "problems.jsonl").read_text(encoding="utf-8")
        )
        expected = dict(record)
        expected["problem_type_codes"] = ["ptype.solve-for-unknown"]
        assert result == expected

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"
        path = root / CORPUS_GENERATED_V0 / "problems.jsonl"
        _write_jsonl(path, [_generated_v0_record("QUAD-EQ", problem_id="a")])
        original = path.read_bytes()

        report = run_backfill(corpus_root=root, write=False)

        assert path.read_bytes() == original  # 파일 미기록.
        by_name = {c.name: c for c in report.corpora}
        assert by_name[CORPUS_GENERATED_V0].tagged == 1
        assert by_name[CORPUS_GENERATED_V0].written is None

    def test_v1_slug_based_classification(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_V1 / "problems.jsonl",
            [
                {"slug": "wm-quad-eq-larger-root", "unit_codes": ["QUAD-EQ"]},
                {"slug": "wm-quad-fn-axis", "unit_codes": ["QUAD-FN"]},
                {"slug": "wm-unknown-slug", "unit_codes": ["QUAD-EQ"]},  # 매핑표 밖 — 미태깅.
            ],
        )
        report = run_backfill(corpus_root=root, write=True)
        by_name = {c.name: c for c in report.corpora}
        v1 = by_name[CORPUS_V1]
        assert v1.total == 3
        assert v1.tagged == 2
        assert v1.untagged == 1

    def test_rephrased_v0_tagged_via_lineage(self, tmp_path: Path) -> None:
        """PB-07 계보 분류 — rephrased 레코드는 "변형" 계보의 부모(직접 분류 코퍼스) 유형을
        승계하고, 부모를 색인에서 못 찾는 레코드는 미태깅으로 남아 리포트가 정직하게 센다."""
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_GENERATED_V0 / "problems.jsonl",
            [_generated_v0_record("QUAD-EQ", problem_id="p1")],
        )
        _write_jsonl(
            root / CORPUS_REPHRASED_V0 / "problems.jsonl",
            [
                {
                    "problem_id": "r1",
                    "slug": "wm-skel-p1-rephrased",
                    "relations": [_variant_relation("wm-skel-p1")],
                },
                {
                    "problem_id": "r2",
                    "slug": "wm-orphan-rephrased",
                    "relations": [_variant_relation("wm-missing-parent")],  # 색인 부재 부모.
                },
            ],
        )

        report = run_backfill(corpus_root=root, write=True)

        by_name = {c.name: c for c in report.corpora}
        reph = by_name[CORPUS_REPHRASED_V0]
        assert reph.total == 2
        assert reph.tagged == 1
        assert reph.untagged == 1  # 침묵 누락 금지 — 추적 불가 건수가 리포트에 드러난다.

        lines = (
            (root / CORPUS_REPHRASED_V0 / "problems.jsonl").read_text(encoding="utf-8").splitlines()
        )
        tagged = [json.loads(line) for line in lines]
        assert tagged[0]["problem_type_codes"] == ["ptype.solve-for-unknown"]  # 부모 유형 승계.
        assert "problem_type_codes" not in tagged[1]  # 미태깅 레코드는 원문 바이트 그대로.

    def test_rephrased_only_gains_problem_type_codes_key(self, tmp_path: Path) -> None:
        """계보 백필도 바이트 계약 준수 — `problem_type_codes` 키 추가 외 타 필드 불변."""
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_GENERATED_V0 / "problems.jsonl",
            [_generated_v0_record("IND-SEQ", problem_id="p1")],
        )
        record = {
            "problem_id": "r1",
            "slug": "wm-skel-p1-rephrased",
            "question_text": "재서술된 발문",
            "answer": "3",
            "relations": [_variant_relation("wm-skel-p1")],
        }
        _write_jsonl(root / CORPUS_REPHRASED_V0 / "problems.jsonl", [record])

        run_backfill(corpus_root=root, write=True)

        result = json.loads(
            (root / CORPUS_REPHRASED_V0 / "problems.jsonl").read_text(encoding="utf-8")
        )
        expected = dict(record)
        expected["problem_type_codes"] = ["ptype.generalize-pattern"]
        assert result == expected

    def test_rephrased_second_run_is_byte_identical(self, tmp_path: Path) -> None:
        """계보 백필 멱등 — 2회 실행 바이트 동일(직접 분류 코퍼스와 동일 계약)."""
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_GENERATED_V0 / "problems.jsonl",
            [_generated_v0_record("QUAD-EQ", problem_id="p1")],
        )
        path = root / CORPUS_REPHRASED_V0 / "problems.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "problem_id": "r1",
                    "slug": "wm-skel-p1-rephrased",
                    "relations": [_variant_relation("wm-skel-p1")],
                }
            ],
        )

        run_backfill(corpus_root=root, write=True)
        first_bytes = path.read_bytes()
        second_report = run_backfill(corpus_root=root, write=True)
        second_bytes = path.read_bytes()

        assert first_bytes == second_bytes
        by_name = {c.name: c for c in second_report.corpora}
        assert by_name[CORPUS_REPHRASED_V0].changed == 0  # 무변경(이미 일치).

    def test_excluded_seat_is_empty_after_pb07(self, tmp_path: Path) -> None:
        """PB-07 해제 후 제외 좌석 회계 — `excluded` 절은 유지되되 현재 빈 상태다(항목이
        재등재되면 만료 계약(`ExclusionEntry`·task_id 필수)과 함께만 가능 — mapping 모듈 동결)."""
        root = tmp_path / "corpus"
        _write_jsonl(root / CORPUS_GENERATED_V0 / "problems.jsonl", [])
        report = run_backfill(corpus_root=root, write=True)
        assert report.excluded_corpora == ()
        assert report.excluded_total == 0

    def test_missing_corpus_file_is_zero_not_error(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"  # 아무 파일도 안 만듦.
        report = run_backfill(corpus_root=root, write=True)
        assert all(c.total == 0 for c in report.corpora)
        assert CORPUS_REPHRASED_V0 in {c.name for c in report.corpora}  # 계보 코퍼스도 회계 대상.
        assert report.excluded_total == 0
        assert report.grand_total == 0


class TestUnitTableCorporaBackfill:
    """CONT-09 — `unit_codes` 표 코퍼스 태깅과 자가 태깅 코퍼스의 읽기 전용 회계."""

    _POLY = "problem_bank_polynomial_arithmetic_v0"
    _INEQ = "problem_bank_quad_ineq_v0"

    def test_unit_table_corpora_are_backfilled_and_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"
        _write_jsonl(
            root / self._POLY / "problems.jsonl",
            [{"problem_id": "a", "slug": "s-a", "unit_codes": ["POLYNOMIAL-ARITHMETIC"]}],
        )
        _write_jsonl(
            root / self._INEQ / "problems.jsonl",
            [
                {"problem_id": "b", "slug": "s-b", "unit_codes": ["QUAD-INEQ-BOUNDARY"]},
                # 표에 없는 unit_codes — 침묵 오분류가 아니라 미태깅으로 리포트에 잡혀야 한다.
                {"problem_id": "c", "slug": "s-c", "unit_codes": ["NOT-IN-TABLE"]},
            ],
        )
        report = run_backfill(corpus_root=root, write=True)

        by_name = {c.name: c for c in report.corpora}
        assert by_name[self._POLY].tagged == 1 and by_name[self._POLY].untagged == 0
        assert by_name[self._INEQ].total == 2
        assert by_name[self._INEQ].tagged == 1
        assert by_name[self._INEQ].untagged == 1  # NOT-IN-TABLE.

        poly = json.loads((root / self._POLY / "problems.jsonl").read_text("utf-8").splitlines()[0])
        assert poly["problem_type_codes"] == [PTYPE_EVALUATE_EXPRESSION]
        ineq_lines = (root / self._INEQ / "problems.jsonl").read_text("utf-8").splitlines()
        assert json.loads(ineq_lines[0])["problem_type_codes"] == [PTYPE_CONDITION_SATISFACTION]
        # 미태깅 행은 원문 바이트 그대로(키를 새로 만들지 않는다 — 기존 바이트 계약).
        assert "problem_type_codes" not in json.loads(ineq_lines[1])

    def test_unit_table_corpora_are_in_the_default_target_run(self) -> None:
        # 기본 실행(`run_backfill`)이 새 코퍼스를 실제로 순회하는지 — TARGET_CORPORA 편입이 배선이다.
        assert self._POLY in TARGET_CORPORA and self._INEQ in TARGET_CORPORA

    def test_second_run_is_byte_identical_for_unit_table_corpus(self, tmp_path: Path) -> None:
        root = tmp_path / "corpus"
        path = root / self._POLY / "problems.jsonl"
        _write_jsonl(
            path,
            [{"problem_id": "a", "slug": "s-a", "unit_codes": ["POLYNOMIAL-ARITHMETIC"]}],
        )
        run_backfill(corpus_root=root, write=True)
        first = path.read_bytes()
        second_report = run_backfill(corpus_root=root, write=True)
        assert path.read_bytes() == first
        assert {c.name: c for c in second_report.corpora}[self._POLY].changed == 0

    def test_nonempty_stored_tag_is_preserved_when_table_does_not_know_the_row(
        self, tmp_path: Path
    ) -> None:
        # 표에 없는 unit_codes 행에 누군가 올바른 태그를 달아 둔 경우 — 백필이 []로 덮어쓰면 안 된다.
        root = tmp_path / "corpus"
        path = root / self._POLY / "problems.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "problem_id": "a",
                    "slug": "s-a",
                    "unit_codes": ["NEW-BAND-NOT-IN-TABLE"],
                    "problem_type_codes": ["ptype.count-solutions"],
                },
                {"problem_id": "b", "slug": "s-b", "unit_codes": ["POLYNOMIAL-ARITHMETIC"]},
            ],
        )
        before_first_line = path.read_text("utf-8").splitlines()[0]
        report = run_backfill(corpus_root=root, write=True)

        lines = path.read_text("utf-8").splitlines()
        assert lines[0] == before_first_line  # 보존 행은 원문 바이트 그대로.
        assert json.loads(lines[1])["problem_type_codes"] == [PTYPE_EVALUATE_EXPRESSION]
        poly = {c.name: c for c in report.corpora}[self._POLY]
        assert poly.preserved == 1  # 침묵 보존이 아니라 건수로 드러난다.
        assert poly.tagged == 2 and poly.changed == 1
        assert (
            report.to_json()["corpora"][[c.name for c in report.corpora].index(self._POLY)][
                "preserved"
            ]
            == 1
        )

    def test_self_tagged_corpus_is_never_rewritten_and_is_accounted(self, tmp_path: Path) -> None:
        # p3는 레코드별 유형을 생성 시점에 직접 기록한다. 백필이 쓰면(`classify_record`는 빈 리스트)
        # 저장된 유형이 지워진다 — 쓰기 모드에서도 바이트 무변경이어야 한다.
        root = tmp_path / "corpus"
        path = root / CORPUS_P3_CALCULUS1_DIFF_V0 / "problems.jsonl"
        _write_jsonl(
            path,
            [
                {
                    "problem_id": "a",
                    "unit_codes": ["P3-X"],
                    "problem_type_codes": ["ptype.count-solutions"],
                },
                {"problem_id": "b", "unit_codes": ["P3-X"], "problem_type_codes": []},
            ],
        )
        before = path.read_bytes()
        report = run_backfill(corpus_root=root, write=True)

        assert path.read_bytes() == before  # 쓰지 않았다.
        # 자가 태깅 좌석이 셋이다(P3-03 은행·P3-05 빈 칸 채우기 은행·P3-65 스킬 도달 은행) — 시험
        # 코퍼스에는 앞의 것만 있다.
        p3, fill, reach = report.self_tagged
        assert fill.name == CORPUS_P3_FILL_V0 and fill.total == 0
        assert reach.name == CORPUS_P3_DIFFERENTIABILITY_REACH_V0 and reach.total == 0
        assert p3.name == CORPUS_P3_CALCULUS1_DIFF_V0
        assert (p3.total, p3.tagged, p3.untagged) == (2, 1, 1)
        assert p3.changed == 0 and p3.written is None
        # 정직 회계: 미태깅 1건이 리포트에 드러나고, 전체 합계에도 포함된다.
        assert report.untagged_self_tagged == 1
        assert report.grand_total == 2
        payload = report.to_json()
        assert payload["untagged_self_tagged"] == 1
        assert payload["self_tagged"][0]["name"] == CORPUS_P3_CALCULUS1_DIFF_V0


class TestMainCli:
    def test_cli_reports_json_and_exit_zero(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        root = tmp_path / "corpus"
        _write_jsonl(
            root / CORPUS_GENERATED_V0 / "problems.jsonl",
            [_generated_v0_record("QUAD-EQ", problem_id="a")],
        )
        rc = main(["--corpus-root", str(root)])
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert rc == 0
        assert payload["total_tagged"] == 1

    def test_cli_dry_run_flag(self, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
        root = tmp_path / "corpus"
        path = root / CORPUS_GENERATED_V0 / "problems.jsonl"
        _write_jsonl(path, [_generated_v0_record("QUAD-EQ", problem_id="a")])
        original = path.read_bytes()

        rc = main(["--corpus-root", str(root), "--dry-run"])

        assert rc == 0
        assert path.read_bytes() == original
