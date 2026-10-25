"""rephrased 발문 위생 일괄 적용 CLI(S3-12) — 탈락·바이트 보존·커밋 코퍼스 청정 동결(hermetic).

핵심 봉인: ① 위반 레코드만 탈락(사유 병기) ② 생존 라인은 **원 바이트 그대로**(재직렬화 0)
③ 형식 파손 라인은 fail-loud(침묵 실패 금지) ④ 커밋 코퍼스는 위생 위반 0(청정 상태 동결 —
재오염이 생기면 여기서 red).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.rephrased_corpus_hygiene import (
    _KNOWN_DEFECTIVE_SLUGS,
    _REASON_MANUAL_AUDIT,
    _default_corpus_path,
    main,
    run_corpus_hygiene_sweep,
)

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# 감사 확정 결함 문면(한자 주입·메타 라벨·조사 오류)과 정상 문면이 섞인 미니 코퍼스.
_CLEAN = {
    "slug": "wm-skel-clean-000000000001",
    "question_text": "이차방정식 3x^2 - 7x + 4 = 0 의 두 근 중 큰 근을 구하시오.",
}
_HANJA = {
    "slug": "wm-skel-hanja-000000000002",
    "question_text": "이차방정식 x^2 - 9x + 20 = 0 의 두解 중 더 큰 解의 값을 구하시오.",
}
_META = {
    "slug": "wm-skel-meta-000000000003",
    "question_text": "원 발문: 이차방정식 x^2 - 3x + 2 = 0 의 큰 근을 구하시오.",
}
_JOSA = {
    "slug": "wm-skel-josa-000000000004",
    "question_text": "이차방정식 x^2 - 7x + 10 = 0 을 풀어 10 를 넘는 근을 구하시오.",
}


def _write_corpus(path: Path, records: list[dict[str, str]]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )


class TestSweep:
    def test_drops_violators_keeps_clean(self, tmp_path: Path) -> None:
        src = tmp_path / "problems.jsonl"
        _write_corpus(src, [_CLEAN, _HANJA, _META, _JOSA])
        report = run_corpus_hygiene_sweep(src, None, write=True)
        assert (report.total, report.kept, report.dropped) == (4, 1, 3)
        dropped_slugs = {slug for slug, _ in report.dropped_items}
        assert dropped_slugs == {_HANJA["slug"], _META["slug"], _JOSA["slug"]}
        # 사유 코드가 축별로 집계된다(재검수 근거).
        assert set(report.reason_counts) == {
            "FOREIGN_SCRIPT",
            "META_LABEL_LEAK",
            "JOSA_ERROR",
        }
        # 생존 레코드만 남고 원 라인 바이트가 보존된다(재직렬화 0).
        assert src.read_text(encoding="utf-8") == (json.dumps(_CLEAN, ensure_ascii=False) + "\n")

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        src = tmp_path / "problems.jsonl"
        _write_corpus(src, [_CLEAN, _HANJA])
        before = src.read_bytes()
        report = run_corpus_hygiene_sweep(src, None, write=False)
        assert report.dropped == 1
        assert src.read_bytes() == before  # 미기록

    def test_out_path_leaves_input_intact(self, tmp_path: Path) -> None:
        src, dst = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
        _write_corpus(src, [_CLEAN, _JOSA])
        before = src.read_bytes()
        run_corpus_hygiene_sweep(src, dst, write=True)
        assert src.read_bytes() == before
        assert dst.read_text(encoding="utf-8") == json.dumps(_CLEAN, ensure_ascii=False) + "\n"

    def test_malformed_line_fails_loud(self, tmp_path: Path) -> None:
        src = tmp_path / "problems.jsonl"
        src.write_text('{"slug": "ok"\n', encoding="utf-8")  # 파싱 불가
        with pytest.raises(ValueError, match="JSONDecodeError"):
            run_corpus_hygiene_sweep(src, None, write=False)


class TestManualAuditDenylist:
    """개별 감사 확정 제거(GRAMMAR_BREAK) — 패턴 무관 명시 slug 소급 탈락(소급 청소 전용)."""

    def test_known_defective_slug_dropped_even_if_pattern_clean(self, tmp_path: Path) -> None:
        # 어형 붕괴 문면(예: "크다음 근")은 결정론 패턴이 못 잡으므로(정직 한계) slug 자체로
        # 강제 탈락한다 — 아래 발문 자체는 6개 패턴 축 전부 통과하는 청정 문면이다.
        manual = {
            "slug": next(iter(_KNOWN_DEFECTIVE_SLUGS)),
            "question_text": "이차방정식 x^2 - 7x + 10 = 0 의 두 근 중 큰 근을 구하시오.",
        }
        src = tmp_path / "problems.jsonl"
        _write_corpus(src, [_CLEAN, manual])
        report = run_corpus_hygiene_sweep(src, None, write=True)
        assert (report.total, report.kept, report.dropped) == (2, 1, 1)
        dropped_slug, reasons = report.dropped_items[0]
        assert dropped_slug == manual["slug"]
        assert _REASON_MANUAL_AUDIT in reasons
        assert report.reason_counts[_REASON_MANUAL_AUDIT] == 1

    def test_non_denylisted_clean_record_survives(self, tmp_path: Path) -> None:
        # denylist는 명시된 slug만 겨냥한다 — 다른 청정 레코드는 다치지 않는다(과잉 탈락 방지).
        src = tmp_path / "problems.jsonl"
        _write_corpus(src, [_CLEAN])
        report = run_corpus_hygiene_sweep(src, None, write=False)
        assert report.dropped == 0


class TestCliEntry:
    def test_main_dry_run_report_json(self, tmp_path: Path, capsys: object) -> None:
        src = tmp_path / "problems.jsonl"
        _write_corpus(src, [_CLEAN, _HANJA])
        code = main(["--in", str(src), "--dry-run"])
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["total"] == 2 and report["dropped"] == 1
        assert report["dropped_items"][0]["slug"] == _HANJA["slug"]


class TestCommittedCorpusClean:
    def test_committed_rephrased_corpus_has_zero_violations(self) -> None:
        # 커밋 코퍼스 청정 동결 — S3-12 일괄 적용(483→446→429, 1차 37건+rotation-1 재검수
        # 발견 신규 3축 14건 추가 탈락) 후 위반 0. 재오염 시 red.
        # (하한 429→421: 2026-08-11 QUAL-02가 실중복 무변화 사본 8건 은퇴 —
        #  docs/data/problem_duplicate_disposition_2026-08.md. 위생 위반 제거가 아니라 중복 은퇴.)
        corpus = _default_corpus_path()
        assert corpus.exists()
        report = run_corpus_hygiene_sweep(corpus, None, write=False)
        assert report.dropped == 0, report.dropped_items[:10]
        assert report.kept == report.total >= _FACTS["problem_bank.rephrased_v0"]
