"""`ncic_overlap` — 겹침 실측과 그 실측치로 합성한 라이선스 선언 (hermetic·실 코퍼스 0).

이 모듈이 존재하는 이유는 PR #998 리뷰 지적이다. 처음 정정은 선언 문자열을 `models.py`에 상수로
박고 커밋된 코퍼스 파일도 손으로 고쳤는데, 그러면 두 가지가 깨진다 — ① 다른 xlsx로 재생성하면
`133건`이라는 숫자가 사실과 무관하게 그대로 나가고 ② 빌드 CLI가 사이드카를 통째 덮어써
`ncic_statement_overlap`이 사라져 새 게이트가 정상 상태에서 red를 낸다. 즉 게이트가 **생성 경로에
배선되지 않았다** — 정정이 막으려던 결함과 같은 형태였다.

여기서 보는 축(각각 성공·실패 양쪽에서 다른 값을 내는지):
① 겹침이 있는 데이터 → 선언이 건수와 출처 표시를 담는다.
② 겹침이 **0인** 데이터 → 같은 빌더가 출처 표시를 담지 **않고** "0건"을 말한다(대칭 — 한 방향만
   보면 "항상 같은 문장"인 빌더도 통과한다).
③ 연결하지 않은 성취기준과 우연히 닮은 문장은 세지 않는다(자기 연결분하고만 비교).
④ 표기 흔들림(띄어쓰기·가운뎃점)은 같은 문장으로, 어미 차이는 다른 문장으로 센다.
⑤ 사이드카 병합이 기존의 *모르는* 키(`pool` 등)를 보존한다 — 통째 덮어쓰기 회귀 방어.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.concept_content.__main__ import _merge_sidecar
from data_pipeline.concept_content.ncic_overlap import (
    build_license_notice,
    build_source_citation,
    load_standard_statements,
    measure_overlap,
    normalize,
)

_STATEMENTS = {
    "[12확통03-01]": "확률변수와 확률분포의 뜻을 설명할 수 있다.",
    "[12확통03-02]": "이산확률변수의 기댓값(평균)과 표준편차를 구할 수 있다.",
    "[2수01-01]": "수의 필요성을 인식하면서 0과 100까지의 수 개념을 이해하고, 수를 세고 읽고 쓸 수 있다.",
}


def test_exact_copy_counted_as_overlap_and_exact() -> None:
    """① 글자 그대로 옮긴 문장은 겹침이자 완전 일치."""
    report = measure_overlap(
        [("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[12확통03-01]"])], _STATEMENTS
    )
    assert (report.count, report.exact, report.total_with_explanation) == (1, 1, 1)


def test_notation_drift_is_same_sentence_but_ending_drift_is_not() -> None:
    """④ 표기 흔들림은 같은 문장, 어미 차이는 다른 문장."""
    drifted = measure_overlap(
        [("이산확률 변수의 기댓값(평균)과표준편차를 구할 수 있다.", ["[12확통03-02]"])], _STATEMENTS
    )
    assert (drifted.count, drifted.exact) == (1, 1), "띄어쓰기 차이를 다른 문장으로 셌다"

    own_words = measure_overlap(
        [("수를 세는 이유를 손가락 짝짓기로 느껴 본다.", ["[2수01-01]"])], _STATEMENTS
    )
    assert own_words.count == 0, "자체 서술을 본문 복제로 셌다"


def test_only_linked_standards_are_compared() -> None:
    """③ 연결하지 않은 성취기준과 닮았다고 세지 않는다 — 건수 부풀림 방지."""
    report = measure_overlap(
        [("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[2수01-01]"])], _STATEMENTS
    )
    assert report.count == 0
    assert report.total_with_explanation == 1, "비교는 했으나 겹치지 않은 것으로 세야 한다"


def test_records_without_usable_link_are_not_counted_in_denominator() -> None:
    """빈 explanation·미등재 코드는 분모에서 빠진다 — 모르는 것을 0으로 접지 않는다."""
    report = measure_overlap(
        [("", ["[12확통03-01]"]), ("무언가", ["[없는코드]"]), ("무언가", [])], _STATEMENTS
    )
    assert (report.count, report.total_with_explanation) == (0, 0)


def test_declaration_is_symmetric_on_zero_overlap() -> None:
    """② 대칭 — 겹침 0이면 출처 표시를 담지 않고 0건을 말한다.

    이 축이 없으면 "무슨 데이터를 넣어도 같은 문장"을 내는 빌더도 ①만으로 통과한다.
    """
    some = measure_overlap(
        [("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[12확통03-01]"])], _STATEMENTS
    )
    none = measure_overlap(
        [("수를 세는 이유를 손가락으로 느껴 본다.", ["[2수01-01]"])], _STATEMENTS
    )

    with_overlap, without = build_license_notice(some), build_license_notice(none)
    assert "공공누리" in with_overlap and "1건" in with_overlap
    assert "공공누리" not in without and "0건" in without
    assert with_overlap != without

    assert "교육부 고시 제2022-33호" in build_source_citation(some)
    assert "교육부 고시 제2022-33호" not in build_source_citation(none)


def test_declaration_reports_the_measured_number_not_a_constant() -> None:
    """건수가 바뀌면 문장도 바뀐다 — 하드코딩 회귀(PR #998 지적) 방어."""
    one = measure_overlap(
        [("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[12확통03-01]"])], _STATEMENTS
    )
    two = measure_overlap(
        [
            ("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[12확통03-01]"]),
            ("이산확률변수의 기댓값(평균)과 표준편차를 구할 수 있다.", ["[12확통03-02]"]),
        ],
        _STATEMENTS,
    )
    assert "1건" in build_license_notice(one)
    assert "2건" in build_license_notice(two)
    assert "133건" not in build_license_notice(two), "옛 상수가 되살아났다"


def test_sidecar_payload_carries_threshold_and_counts() -> None:
    report = measure_overlap(
        [("확률변수와 확률분포의 뜻을 설명할 수 있다.", ["[12확통03-01]"])], _STATEMENTS
    )
    payload = report.as_sidecar(measured_at="2026-09-06")
    assert payload["count"] == 1
    assert payload["exact_after_normalization"] == 1
    assert payload["similarity_threshold"] == report.threshold
    assert payload["field"] == "explanation"


def test_load_standard_statements_reads_corpus_shape(tmp_path: Path) -> None:
    path = tmp_path / "standards.json"
    path.write_text(
        json.dumps(
            {
                "standards": [
                    {"code": "[X-01]", "statement": "본문"},
                    {"code": "", "statement": "무시"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_standard_statements(path) == {"[X-01]": "본문"}


def test_merge_sidecar_preserves_unknown_keys(tmp_path: Path) -> None:
    """⑤ 재생성이 다른 도구의 키를 지우지 않는다 — 통째 덮어쓰기 회귀 방어."""
    path = tmp_path / "_provenance.json"
    path.write_text(
        json.dumps({"pool": "whymath-original", "source_citation": "옛 선언"}, ensure_ascii=False),
        encoding="utf-8",
    )
    merged = _merge_sidecar(
        path, {"source_citation": "새 선언", "ncic_statement_overlap": {"count": 3}}
    )
    assert merged["pool"] == "whymath-original", "재생성이 pool을 지웠다(provenance_audit red)"
    assert merged["source_citation"] == "새 선언"
    assert merged["ncic_statement_overlap"] == {"count": 3}


def test_merge_sidecar_on_missing_or_broken_file(tmp_path: Path, capsys) -> None:
    """없으면 그냥 신규, 깨졌으면 **예외 타입명을 남기고** 신규 — 침묵 실패 금지."""
    missing = tmp_path / "none.json"
    assert _merge_sidecar(missing, {"a": 1}) == {"a": 1}

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert _merge_sidecar(broken, {"a": 1}) == {"a": 1}
    assert "JSONDecodeError" in capsys.readouterr().out


def test_normalize_strips_only_notation() -> None:
    assert normalize("이산확률 변수의 (평균)") == normalize("이산확률변수의 평균")
    assert normalize("구할 수 있다") != normalize("구한다")
