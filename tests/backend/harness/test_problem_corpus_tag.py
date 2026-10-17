"""시그니처 태깅 후처리 CLI(S2-06) — 멱등·바이트 보존·dry-run 무기록 단위테스트(hermetic).

핵심 봉인: ① 이미 태깅된 코퍼스(배치 산출물)에 적용하면 **바이트 무변경**(멱등) ② 시그니처가
비워진(과거 산출물 가정) 코퍼스를 재태깅하면 배치 산출물과 바이트 동일(태거=배치 정합·단일 권위)
③ 시그니처 필드 외 바이트 무변경 ④ dry-run은 파일 미기록·통계만 ⑤ 2회 실행 바이트 동일.
LLM·DB 0(순수 결정론).
"""

from __future__ import annotations

import json
from pathlib import Path

from whymath_backend.harness.problem_corpus_batch import run_corpus_batch
from whymath_backend.harness.problem_corpus_tag import main, run_corpus_tag


def _make_corpus(out: Path, *, seq_inductive_n: int = 4, short_n: int = 3) -> None:
    """소형 코퍼스 생성 — 기존 문제군(short·태깅 0) + 귀납 밴드(태깅 2종) 혼합."""
    run_corpus_batch(
        out_path=out,
        short_n=short_n,
        mc_n=0,
        sqrt_n=0,
        sqrt_mc_n=0,
        calc_extremum_n=0,
        calc_tangent_n=0,
        calc_value_n=0,
        calc_value_mc_n=0,
        calc_extremum_irr_n=0,
        exp_n=0,
        log_n=0,
        arith_n=0,
        geo_n=0,
        trig_n=0,
        arith_sum_n=0,
        geo_sum_n=0,
        trig_eq_n=0,
        seq_inductive_n=seq_inductive_n,
        write=True,
    )


def _strip_signatures(src: Path, dst: Path) -> None:
    """signature_patterns를 전건 빈 배열로 비운 사본 — 과거(태깅 전) 산출물을 재현."""
    lines = []
    for line in src.read_text(encoding="utf-8").splitlines():
        data = json.loads(line)
        data["signature_patterns"] = []
        lines.append(json.dumps(data, ensure_ascii=False))
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestRunCorpusTag:
    def test_already_tagged_corpus_is_byte_noop(self, tmp_path: Path) -> None:
        # 배치 산출물은 이미 태깅됨 — 재태깅은 무변경(멱등)·바이트 동일.
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        _make_corpus(src)
        report = run_corpus_tag(in_path=src, out_path=out)
        assert report.total == 7 and report.changed == 0 and report.written == 7
        assert report.tagged == 4  # 귀납 밴드 4건만 시그니처 보유
        assert report.pattern_counts == {"CONDITION_LIST": 4, "INDUCTIVE_SEQUENCE": 4}
        assert out.read_bytes() == src.read_bytes()

    def test_corpus_with_recorded_author_is_accepted_and_preserved(self, tmp_path: Path) -> None:
        # PB-15 — 저작 서명(`authored_by`)이 기록된 코퍼스를 이 도구가 거부하지 않는다.
        # `Problem`은 extra="forbid"라 `_AUTHORING_KEYS`에 없는 키는 검증에서 터진다 — 서명을
        # 코퍼스에 싣기 시작하면 이 도구(와 같은 상수를 쓰는 다른 2개 도구)가 깨질 수 있었다.
        # 서명 키는 시그니처 재유도와 무관하므로 원문 줄이 바이트 그대로 보존돼야 한다.
        src = tmp_path / "src.jsonl"
        signed = tmp_path / "signed.jsonl"
        out = tmp_path / "out.jsonl"
        _make_corpus(src)
        lines = []
        for line in src.read_text(encoding="utf-8").splitlines():
            data = json.loads(line)
            data["authored_by"] = "llm:qwen3:30b-a3b"
            lines.append(json.dumps(data, ensure_ascii=False))
        signed.write_text("\n".join(lines) + "\n", encoding="utf-8")

        report = run_corpus_tag(in_path=signed, out_path=out)

        assert report.total == 7 and report.changed == 0
        assert out.read_bytes() == signed.read_bytes()

    def test_retag_stripped_corpus_matches_batch_output(self, tmp_path: Path) -> None:
        # 태깅이 비워진 코퍼스를 재태깅 → 배치 산출물과 바이트 동일(태거=배치 단일 권위 정합).
        src = tmp_path / "src.jsonl"
        stripped = tmp_path / "stripped.jsonl"
        out = tmp_path / "out.jsonl"
        _make_corpus(src)
        _strip_signatures(src, stripped)
        report = run_corpus_tag(in_path=stripped, out_path=out)
        assert report.changed == 4  # 귀납 밴드 4건만 갱신(기존 문제군 3건 무변경)
        assert out.read_bytes() == src.read_bytes()

    def test_only_signature_field_changes(self, tmp_path: Path) -> None:
        # 시그니처 필드 외 바이트/필드 무변경 — 레코드별 dict 비교(한 키 외 전부 동일).
        src = tmp_path / "src.jsonl"
        stripped = tmp_path / "stripped.jsonl"
        out = tmp_path / "out.jsonl"
        _make_corpus(src)
        _strip_signatures(src, stripped)
        run_corpus_tag(in_path=stripped, out_path=out)
        in_lines = stripped.read_text(encoding="utf-8").splitlines()
        out_lines = out.read_text(encoding="utf-8").splitlines()
        assert len(in_lines) == len(out_lines)
        for in_line, out_line in zip(in_lines, out_lines, strict=True):
            before = json.loads(in_line)
            after = json.loads(out_line)
            before.pop("signature_patterns")
            after.pop("signature_patterns")
            assert before == after

    def test_rerun_is_byte_identical(self, tmp_path: Path) -> None:
        # 2회 실행 바이트 동일(멱등) — 1회차 산출물에 재적용해도 그대로.
        src = tmp_path / "src.jsonl"
        stripped = tmp_path / "stripped.jsonl"
        once = tmp_path / "once.jsonl"
        twice = tmp_path / "twice.jsonl"
        _make_corpus(src)
        _strip_signatures(src, stripped)
        run_corpus_tag(in_path=stripped, out_path=once)
        report = run_corpus_tag(in_path=once, out_path=twice)
        assert report.changed == 0
        assert once.read_bytes() == twice.read_bytes()


class TestCliEntry:
    def test_dry_run_writes_nothing(self, tmp_path: Path, capsys: object) -> None:
        # dry-run — 입력 무변경·산출 미기록·통계만 stdout(JSON).
        src = tmp_path / "src.jsonl"
        out = tmp_path / "out.jsonl"
        _make_corpus(src)
        before = src.read_bytes()
        code = main(["--in", str(src), "--out", str(out), "--dry-run"])
        assert code == 0
        assert not out.exists()
        assert src.read_bytes() == before
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["total"] == 7 and report["written"] is None
        assert report["pattern_counts"] == {"CONDITION_LIST": 4, "INDUCTIVE_SEQUENCE": 4}

    def test_in_place_default_out(self, tmp_path: Path, capsys: object) -> None:
        # --out 생략 시 제자리 갱신 — 이미 태깅된 파일이라 바이트 무변경(멱등 제자리).
        src = tmp_path / "src.jsonl"
        _make_corpus(src)
        before = src.read_bytes()
        code = main(["--in", str(src)])
        assert code == 0
        assert src.read_bytes() == before
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["changed"] == 0 and report["written"] == 7
