"""8-gram 일치율 기록기 hermetic 테스트 — EOS-222.

검증 축:
① 변별력 — 비교 원본을 그대로 복사한 CU는 일치율 1.0·기준 이상으로 기록되고, 새로 쓴 CU는
   기준 미만이다(같은 픽스처 안에서 양방향을 함께 단언 — 모든 입력에 같은 값을 내는 위장 방지).
② 측정 불가는 0%가 아니다 — 필드 없음·토큰 8개 미만은 overlap 값 없이 이유만 남는다.
③ 차단하지 않는다 — 기준을 넘는 건이 있어도 종료 코드 0, 사이드카에 flagged로만 남는다.
④ 비교 원본 집합 — 회차가 기록한 입력 코퍼스만 쓰고 회차 자기 산출물(cu.jsonl)은 뺀다.
   저장소에 없는 원본(평가원·EBS·교과서)은 not_compared에 적힌다.
⑤ 해시 대조 3상태 — 정확 일치 / 줄바꿈만 다름(Windows 체크아웃) / 불일치를 구분한다.
⑥ 입력 오류는 종료 코드 2(예외 타입명 포함).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from whymath_backend.ops import ngram_overlap_report as m

_ORIGINAL_Q = "다항함수 y = x^3 - 3x 의 그래프 위의 점 (2, 2) 에서 그은 접선의 y절편을 구하시오."
_ORIGINAL_E = "도함수는 y' = 3x^2 - 3 이므로 x = 2 에서 기울기는 9 이다. 접선은 y = 9x - 16 이므로 y절편은 -16 이다."
_FRESH_Q = (
    "곡선 f(x) = 2x^2 + x 위의 x 좌표가 1 인 점에서 접하는 직선이 y축과 만나는 점의 y좌표를 구하라."
)


def _write_jsonl(path: Path, rows: list[dict[str, object]], newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = newline.join(json.dumps(r, ensure_ascii=False) for r in rows) + newline
    path.write_bytes(text.encode("utf-8"))


def _repo(tmp_path: Path, *, crlf_digest: bool = False) -> tuple[Path, Path]:
    """원본 코퍼스 1개 + 회차 1개짜리 임시 저장소."""
    root = tmp_path / "repo"
    corpus = root / "data" / "corpus" / "bank_a" / "problems.jsonl"
    _write_jsonl(
        corpus,
        [{"slug": "orig-1", "question_text": _ORIGINAL_Q, "answer_explanation": _ORIGINAL_E}],
    )
    raw = corpus.read_bytes()
    digest_src = raw.replace(b"\n", b"\r\n") if crlf_digest else raw
    run = root / "data" / "runs" / "r1"
    _write_jsonl(
        run / "cu.rounds.jsonl",
        [
            {
                "dedup_input_digests": {
                    "C:\\Users\\kiki\\WhyMath\\data\\corpus\\bank_a\\problems.jsonl": hashlib.sha256(
                        digest_src
                    ).hexdigest(),
                    "C:\\Users\\kiki\\WhyMath\\data\\runs\\r1\\cu.jsonl": "f" * 64,
                }
            }
        ],
    )
    _write_jsonl(
        run / "cu.jsonl",
        [
            # 원본 통째 복사 — 기준을 넘어야 한다
            {"slug": "cu-copy", "question_text": _ORIGINAL_Q, "answer_explanation": _ORIGINAL_E},
            # 새로 쓴 문항 — 기준 미만이어야 한다 · 해설 없음 → 측정 불가
            {"slug": "cu-fresh", "question_text": _FRESH_Q},
            # 토큰 8개 미만 → 측정 불가
            {"slug": "cu-short", "question_text": "x 의 값을 구하시오.", "answer_explanation": ""},
        ],
    )
    return root, run


def _by_slug(report: dict[str, object]) -> dict[str, dict[str, dict[str, object]]]:
    return {r["slug"]: r["fields"] for r in report["results"]}  # type: ignore[index,union-attr]


def test_copy_is_flagged_and_fresh_is_not(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    rows = _by_slug(m.build_run_report(run, root))
    copy_q = rows["cu-copy"]["question_text"]
    assert copy_q["overlap"] == 1.0 and copy_q["at_or_above_threshold"] is True
    assert copy_q["best_match"] == {"corpus": "bank_a", "slug": "orig-1", "field": "question_text"}
    fresh_q = rows["cu-fresh"]["question_text"]
    assert fresh_q["status"] == "measured"
    assert float(fresh_q["overlap"]) < m.THRESHOLD  # type: ignore[arg-type]
    assert fresh_q["at_or_above_threshold"] is False


def test_partial_copy_crosses_threshold_boundary(tmp_path: Path) -> None:
    """원본 발문 앞에 토큰 몇 개만 붙인 '살짝 바꾼 복사'도 70% 이상으로 잡힌다."""
    root, run = _repo(tmp_path)
    _write_jsonl(
        run / "cu.jsonl",
        [{"slug": "cu-near", "question_text": "다음 물음에 답하시오. " + _ORIGINAL_Q}],
    )
    rec = _by_slug(m.build_run_report(run, root))["cu-near"]["question_text"]
    assert m.THRESHOLD <= float(rec["overlap"]) < 1.0  # type: ignore[arg-type]


def test_unmeasurable_is_not_zero(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    rows = _by_slug(m.build_run_report(run, root))
    for rec in (
        rows["cu-fresh"]["answer_explanation"],
        rows["cu-short"]["question_text"],
        rows["cu-short"]["answer_explanation"],
    ):
        assert rec["status"] == "unmeasurable"
        assert "overlap" not in rec and rec["reason"]


def test_summary_and_not_compared(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    report = m.build_run_report(run, root)
    s = report["summary"]
    assert s["flagged_count"] == 2  # cu-copy 발문·해설
    assert {f["slug"] for f in s["flagged"]} == {"cu-copy"}  # type: ignore[union-attr]
    assert s["by_field"]["answer_explanation"]["unmeasurable"] == 2  # type: ignore[index]
    # 비교 원본은 입력 코퍼스만 — 회차 자기 산출물은 빠진다
    assert [c["corpus"] for c in report["comparison_set"]] == ["bank_a"]  # type: ignore[union-attr]
    assert report["not_compared"] and any("평가원" in x for x in report["not_compared"])  # type: ignore[union-attr]


@pytest.mark.parametrize(("crlf", "expected"), [(False, "exact"), (True, "crlf_equivalent")])
def test_digest_match_states(tmp_path: Path, crlf: bool, expected: str) -> None:
    root, run = _repo(tmp_path, crlf_digest=crlf)
    assert m.build_run_report(run, root)["comparison_set"][0]["digest_match"] == expected  # type: ignore[index]


def test_digest_mismatch_when_content_changed(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    corpus = root / "data" / "corpus" / "bank_a" / "problems.jsonl"
    corpus.write_bytes(corpus.read_bytes() + b'{"slug": "orig-2"}\n')
    assert m.build_run_report(run, root)["comparison_set"][0]["digest_match"] == "mismatch"  # type: ignore[index]


def test_cli_records_without_blocking(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    assert m.main(["run", str(run), "--root", str(root)]) == 0  # 기준을 넘어도 0 — 기록만
    payload = json.loads((run / m.SIDECAR_NAME).read_text(encoding="utf-8"))
    assert payload["summary"]["flagged_count"] == 2
    assert payload["method"]["n"] == 8 and payload["method"]["threshold"] == 0.7


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    root, run = _repo(tmp_path)
    assert m.main(["run", str(run), "--root", str(root), "--dry-run"]) == 0
    assert not (run / m.SIDECAR_NAME).exists()


def test_corpus_summary_keeps_only_question_text_slugs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, run = _repo(tmp_path)
    target = root / "data" / "corpus" / "bank_b"
    _write_jsonl(
        target / "problems.jsonl",
        [{"slug": "b-1", "question_text": _ORIGINAL_Q, "answer_explanation": _ORIGINAL_E}],
    )
    code = m.main(
        [
            "corpus",
            str(target),
            "--against",
            str(root / "data" / "corpus" / "bank_a"),
            "--root",
            str(root),
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["flagged_question_text_slugs"] == ["b-1"]
    assert "flagged" not in out["summary"]


def test_input_errors_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root, run = _repo(tmp_path)
    (run / "cu.rounds.jsonl").unlink()
    assert m.main(["run", str(run), "--root", str(root)]) == 2
    (run / "cu.rounds.jsonl").write_text("{깨진 json\n", encoding="utf-8")
    assert m.main(["run", str(run), "--root", str(root)]) == 2
    assert "JSONDecodeError" in capsys.readouterr().err
