"""`scripts/ops/misc61_source_key_probe.py` — 원천 JSON 키 진단(MISC-61 ①).

이 스크립트는 Kiki 머신의 원천 파일에 한 번 돌아 가설 ①(원천 공란)/②(추출 누락)을 가른다. 실행 기회가
한 번이므로 **실패 상태에서 실제로 실패 신호를 내는지**를 합성 원천 세 종류로 확인한다 — 세 판정이 서로
다른 값을 내지 못하면 그 출력은 판정이 아니라 위장이다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from data_pipeline.misconception import extract as extractor

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "misc61_source_key_probe.py"
_spec = importlib.util.spec_from_file_location("misc61_source_key_probe", _SCRIPT)
assert _spec is not None and _spec.loader is not None
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

SECRET_TEXT = "이 문장은_보고서에_나오면_안된다"  # 행 본문이 보고서에 새는지 검사하는 표지


def _row(mis_id: str, note: str = probe.LINKED_NOTE, **extra: object) -> dict:
    row: dict = {"mis_id": mis_id, "오개념": SECRET_TEXT, "생성·검수": note}
    row.update(extra)
    return row


def _write(tmp_path: Path, rows: list[dict], corpus_ids: list[str], sha_of_source: bool = True):
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps([{"개념ID": "C1", "L5_META": {"오개념": rows}}], ensure_ascii=False),
        encoding="utf-8",
    )
    corpus = tmp_path / "misconceptions.json"
    corpus.write_text(
        json.dumps(
            {
                "misconceptions": [
                    {
                        "mis_id": mid,
                        "provenance_note": probe.LINKED_NOTE,
                        "student_wrong_thinking": None,
                        "distractor_rule": None,
                        "error_type": None,
                    }
                    for mid in corpus_ids
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    provenance = tmp_path / "_provenance.json"
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if sha_of_source else "0" * 64
    provenance.write_text(json.dumps({"source_sha256": digest}), encoding="utf-8")
    return source, corpus, provenance


def _run(tmp_path: Path, rows: list[dict], corpus_ids: list[str], capsys, **kw):
    source, corpus, provenance = _write(tmp_path, rows, corpus_ids, **kw)
    code = probe.main(
        ["--source", str(source), "--corpus", str(corpus), "--provenance", str(provenance)]
    )
    out = capsys.readouterr()
    return code, out.out, out.err


# ── 세 판정이 서로 다른 값을 낸다 ────────────────────────────────────────
def test_h1_when_source_is_empty_everywhere(tmp_path, capsys):
    rows = [_row("M0001", 학생의_잘못된_사고="", distractor_규칙=None, error_type="")]
    code, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    assert code == 0
    assert json.loads(out)["all_targets"]["verdict"] == "H1_source_empty"


def test_h2_known_key_when_source_has_value_under_extractor_key(tmp_path, capsys):
    rows = [_row("M0001", distractor_규칙="규칙 본문")]
    code, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    report = json.loads(out)
    assert code == 0
    assert report["all_targets"]["verdict"] == "H2_known_key"
    assert report["all_targets"]["known_key_nonempty_counts"] == {"distractor_규칙": 1}


def test_h2_unknown_key_when_value_hides_under_a_key_the_extractor_never_reads(tmp_path, capsys):
    rows = [_row("M0001", 오답선택지=["①", "②"])]
    code, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    report = json.loads(out)
    assert report["all_targets"]["verdict"] == "H2_unknown_key"
    assert report["all_targets"]["unknown_key_nonempty_counts"] == {"오답선택지": 1}


def test_a3_rows_are_reported_individually(tmp_path, capsys):
    rows = [
        _row("M0599", 학생의_잘못된_사고=""),
        _row("M0600", distractor_규칙="있다"),
        _row("M0417", note="원본"),
    ]
    _, out, _ = _run(tmp_path, rows, [], capsys)
    a3 = json.loads(out)["a3"]
    assert a3["M0599"]["verdict"] == "H1_source_empty"
    assert a3["M0600"]["verdict"] == "H2_known_key"
    assert a3["M0417"]["verdict"] == "H1_source_empty"
    assert a3["M0418"]["verdict"] == "NO_TARGETS"  # 원천에 없는 A3 행은 '없음'으로 말한다


# ── 대조군: 대상 밖 행은 판정을 흔들지 않는다 ─────────────────────────────
def test_values_on_non_target_rows_do_not_change_the_verdict(tmp_path, capsys):
    rows = [
        _row("M0001", 학생의_잘못된_사고=""),
        _row("M9999", note="원본", distractor_규칙="대상 밖", 오답선택지=["x"]),
    ]
    _, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    report = json.loads(out)
    assert report["all_targets"]["verdict"] == "H1_source_empty"
    # 다만 원천 전체의 비표준 키는 대상 밖이라도 보인다(매핑 누락이 더 넓은지 보려고)
    assert report["source_wide_unknown_key_nonempty_counts"] == {"오답선택지": 1}


# ── 파일 신원·출력 안전·입력 오류 ─────────────────────────────────────────
def test_sha_match_is_true_for_the_provenance_file_and_false_otherwise(tmp_path, capsys):
    rows = [_row("M0001")]
    _, ok, _ = _run(tmp_path, rows, ["M0001"], capsys)
    assert json.loads(ok)["sha256_matches_provenance"] is True
    other = tmp_path / "other"
    other.mkdir()
    _, bad, _ = _run(other, rows, ["M0001"], capsys, sha_of_source=False)
    assert json.loads(bad)["sha256_matches_provenance"] is False


def test_report_never_contains_row_text(tmp_path, capsys):
    rows = [_row("M0001", 학생의_잘못된_사고="비밀 서술", 오답선택지=["비밀 선택지"])]
    _, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    for leaked in (SECRET_TEXT, "비밀 서술", "비밀 선택지"):
        assert leaked not in out


def test_no_target_rows_in_source_exits_2_and_says_so(tmp_path, capsys):
    rows = [_row("M0001")]
    code, _, err = _run(tmp_path, rows, ["M7777"], capsys)  # 코퍼스의 대상이 원천에 없다
    assert code == 2 and "다른 파일" in err


def test_malformed_source_exits_2(tmp_path, capsys):
    source = tmp_path / "s.json"
    source.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    corpus = tmp_path / "c.json"
    corpus.write_text(json.dumps({"misconceptions": []}), encoding="utf-8")
    code = probe.main(["--source", str(source), "--corpus", str(corpus)])
    assert code == 2
    assert "ValueError" in capsys.readouterr().err  # 예외 타입명을 남긴다


def test_missing_file_exits_2(tmp_path, capsys):
    code = probe.main(["--source", str(tmp_path / "nope.json"), "--corpus", str(tmp_path / "c")])
    assert code == 2


# ── 복제본이 추출기와 어긋나지 않는다 ─────────────────────────────────────
def test_extractor_keys_copy_matches_the_real_extractor():
    real = set(extractor._STR_FIELDS) | {"mis_id", "매핑점수"}
    assert set(probe.EXTRACTOR_KEYS) == real, "추출기 키 매핑이 바뀌었다 — 진단 스크립트도 갱신"


def test_empty_field_source_keys_are_the_three_the_corpus_leaves_empty():
    mapped = {extractor._STR_FIELDS[k] for k in probe.EMPTY_FIELD_SOURCE_KEYS}
    assert mapped == {"student_wrong_thinking", "distractor_rule", "error_type"}


@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_empty_like_values_are_not_values(value):
    assert probe._nonempty(value) is False


def test_zero_and_false_are_values():
    # 0·False는 '값이 있다' — 빈 값으로 접으면 숫자 필드를 놓친다
    assert probe._nonempty(0) is True and probe._nonempty(False) is True


# ── 출력 형태: 표준 출력은 ASCII, --out은 UTF-8 ─────────────────────────
def test_stdout_is_ascii_only_so_console_encoding_cannot_corrupt_it(tmp_path, capsys):
    rows = [_row("M0001", 오답선택지=["x"])]
    _, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    assert out.isascii(), "표준 출력에 비-ASCII가 섞이면 cp949 중계에서 JSON 구조가 손상된다"
    assert json.loads(out)["all_targets"]["verdict"] == "H2_unknown_key"  # 이스케이프 후에도 파싱됨


def test_out_file_is_readable_utf8_and_matches_stdout(tmp_path, capsys):
    rows = [_row("M0001", 오답선택지=["x"])]
    source, corpus, provenance = _write(tmp_path, rows, ["M0001"])
    out_path = tmp_path / "report.json"
    code = probe.main(
        [
            "--source",
            str(source),
            "--corpus",
            str(corpus),
            "--provenance",
            str(provenance),
            "--out",
            str(out_path),
        ]
    )
    stdout = capsys.readouterr().out
    assert code == 0
    text = out_path.read_text(encoding="utf-8")
    assert "오답선택지" in text, "UTF-8 본에는 한글 키가 그대로 읽혀야 한다"
    assert json.loads(text) == json.loads(stdout)


def test_no_targets_still_prints_the_report_before_exiting_2(tmp_path, capsys):
    code, out, err = _run(tmp_path, [_row("M0001")], ["M7777"], capsys)
    assert code == 2 and "다른 파일" in err
    assert json.loads(out)["source_rows_total"] == 1  # 왜 0건인지 보이는 보고서는 남는다


def test_corpus_rows_that_already_have_a_value_are_not_targets(tmp_path):
    """코퍼스에서 이미 값이 있는 `distractor 연결됨` 행은 대상이 아니다 — 비어 있는 행만 진단한다."""
    corpus = tmp_path / "c.json"
    corpus.write_text(
        json.dumps(
            {
                "misconceptions": [
                    {"mis_id": "M1", "provenance_note": probe.LINKED_NOTE, "error_type": None},
                    {
                        "mis_id": "M2",
                        "provenance_note": probe.LINKED_NOTE,
                        "error_type": "부호오류",
                    },
                    {"mis_id": "M3", "provenance_note": "원본", "error_type": None},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # M2는 값이 있고 M3은 `distractor 연결됨`이 아니다 — 둘 다 대상이 아니다
    assert probe.corpus_empty_ids(corpus) == {"M1"}


def test_known_key_value_wins_when_the_same_row_also_has_an_unknown_key(tmp_path, capsys):
    """같은 행에 두 곳 모두 값이 있으면 H2_known_key다 — 추출기 키에 값이 있다는 것이 더 강한 증거다.

    (우선순위 절의 반례: 이 행이 없으면 순서를 뒤집어도 모든 테스트가 통과한다.)
    """
    rows = [_row("M0001", distractor_규칙="있다", 오답선택지=["x"])]
    _, out, _ = _run(tmp_path, rows, ["M0001"], capsys)
    assert json.loads(out)["all_targets"]["verdict"] == "H2_known_key"


def test_a3_rows_are_targets_even_when_the_corpus_does_not_list_them(tmp_path, capsys):
    """A3 4건은 코퍼스의 `distractor 연결됨` 목록과 무관하게 전체 판정의 대상이다.

    M0418·M0417은 `원본` 표기라 코퍼스 대상 목록에 없다 — A3를 합치는 절이 빠지면 이 행의 값이
    전체 판정에서 사라진다.
    """
    rows = [_row("M0418", note="원본", distractor_규칙="있다")]
    _, out, _ = _run(tmp_path, rows, [], capsys)  # 코퍼스 대상 0건
    report = json.loads(out)
    assert report["corpus_distractor_linked_empty_rows"] == 0
    assert report["all_targets"]["target_rows_found_in_source"] == 1
    assert report["all_targets"]["verdict"] == "H2_known_key"
