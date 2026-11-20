"""문제은행 커버리지 리포트 CLI 테스트 — 결정론·정직 회계·집계 정확성 동결(hermetic).

대상: `whymath_backend.harness.problem_bank_coverage`(D4 관측 리포트). 실 코퍼스·DB·LLM·네트워크
0 — 전부 tmp_path에 만든 소형 픽스처로 검증한다.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): 각 테스트는 *그 규약이 깨진 구현에서 실제로
실패하는지*를 기준으로 짰다 —
  - 파싱 실패를 조용히 버리면 `parse_errors`가 비어 실패한다.
  - "데이터없음"과 "비어있음"을 합치면 상태 단언이 실패한다.
  - 커버율 임계로 exit 1을 내면 0% 커버 테스트가 실패한다(게이트 아님 동결).
  - dict 삽입 순서에 의존해 렌더하면 역순 입력 동일성 테스트가 실패한다.
  - 난이도 밴드 경계를 임의로 바꾸면 L6 앵커 거버넌스 테스트가 실패한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import problem_bank_coverage as pbc

# ──────────────────────────────────────────────────────────────────────────
# 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────────────────
_STD_2022 = "2022 개정"
_STD_2015 = "2015 개정"


def _standard(
    code: str,
    revision: str = _STD_2022,
    *,
    school_type: str = "고등학교",
    domain: str = "대수",
) -> dict[str, object]:
    return {
        "norm_id": f"{revision[:4]}_{code}",
        "code": code,
        "curriculum_revision": revision,
        "school_type": school_type,
        "domain": domain,
    }


def _write_standards(path: Path, entries: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"standards": entries}, ensure_ascii=False), encoding="utf-8")
    return path


def _problem(
    *,
    problem_id: str = "p1",
    units: list[str] | None = None,
    standards: list[str] | None = None,
    difficulty: float | None = 2.5,
    question_format: str | None = "단답형",
    problem_types: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "problem_id": problem_id,
        "unit_codes": units if units is not None else ["QUAD-EQ"],
        "achievement_standard_codes": standards if standards is not None else ["[10공수1-02-02]"],
        "difficulty_overall": difficulty,
        "question_format": question_format,
    }
    if problem_types is not None:
        payload["problem_type_codes"] = problem_types
    return payload


def _write_problem_types(path: Path, type_ids: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"problem_type_id": t}, ensure_ascii=False) + "\n" for t in type_ids),
        encoding="utf-8",
    )
    return path


def _write_corpus(root: Path, name: str, problems: list[dict[str, object]]) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / pbc.CORPUS_FILE_NAME
    path.write_text(
        "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in problems), encoding="utf-8"
    )
    return path


# ──────────────────────────────────────────────────────────────────────────
# 1. 난이도 밴드 — 경계·정직 분류·기존 정본 유도 동결
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, pbc.BAND_AWARENESS),
        (1.999, pbc.BAND_AWARENESS),
        (2.0, pbc.BAND_PROCEDURAL),  # 경계는 상위 밴드에 귀속(좌폐우개)
        (2.9, pbc.BAND_PROCEDURAL),
        (3.0, pbc.BAND_CONCEPTUAL),
        (3.99, pbc.BAND_CONCEPTUAL),
        (4.0, pbc.BAND_MASTERY),
        (5.0, pbc.BAND_MASTERY),  # 최상단만 폐구간
        (None, pbc.BAND_UNSCORED),
        (0.9, pbc.BAND_OUT_OF_RANGE),
        (5.1, pbc.BAND_OUT_OF_RANGE),
    ],
)
def test_difficulty_band_boundaries(value: float | None, expected: str) -> None:
    assert pbc.difficulty_band(value) == expected


def test_unscored_and_out_of_range_are_distinct_from_low_band() -> None:
    """'난이도 없음'·'범위 밖'을 최저 밴드로 뭉개지 않는다(데이터 없음 ≠ 낮음)."""
    assert pbc.difficulty_band(None) != pbc.difficulty_band(1.0)
    assert pbc.difficulty_band(0.0) != pbc.difficulty_band(1.0)


def test_difficulty_bands_derive_from_l6_anchors() -> None:
    """거버넌스 — 밴드 경계가 L6 기존 정본에서 유도된 값임을 기계로 동결(자체 기준 신설 금지).

    ① `_DEPTH_TARGET_DIFFICULTY`(RequiredDepth 앵커 1.5/2.5/3.5/4.5)의 인접 중점이 밴드 경계
    ② `GIFTED_MIN_DIFFICULTY`(4.0)가 최상단 경계와 일치.
    L6 상수가 바뀌면 이 테스트가 깨져 리포트 밴드 정의를 함께 갱신하도록 강제한다.
    """
    from whymath_backend.l6.gifted.gating import GIFTED_MIN_DIFFICULTY
    from whymath_backend.l6.school_progress.gating import _DEPTH_TARGET_DIFFICULTY

    anchors = sorted(_DEPTH_TARGET_DIFFICULTY.values())
    assert len(anchors) == 4
    midpoints = tuple(round((lo + hi) / 2, 6) for lo, hi in zip(anchors, anchors[1:], strict=False))
    assert midpoints == pbc._BAND_EDGES
    assert GIFTED_MIN_DIFFICULTY == pbc._BAND_EDGES[-1]

    # "가장 가까운 앵커" 분할과 밴드가 같은 분류를 내는지 그리드 검증.
    anchor_to_band = dict(
        zip(
            anchors,
            (pbc.BAND_AWARENESS, pbc.BAND_PROCEDURAL, pbc.BAND_CONCEPTUAL, pbc.BAND_MASTERY),
            strict=True,
        )
    )
    for step in range(100, 501):
        value = step / 100
        # 동률(정확히 경계값 2.0·3.0·4.0)은 *상위* 앵커에 귀속 — 밴드 구간이 좌폐우개인 것과 동형.
        nearest = min(anchors, key=lambda a: (abs(a - value), -a))
        assert pbc.difficulty_band(value) == anchor_to_band[nearest], value


# ──────────────────────────────────────────────────────────────────────────
# 2. 성취기준 대장 — 레코드 수 ≠ 고유 코드 수
# ──────────────────────────────────────────────────────────────────────────
def test_catalog_distinguishes_records_from_unique_codes() -> None:
    catalog = pbc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-02]", _STD_2022),
                _standard("[10공수1-02-02]", _STD_2015),  # 같은 코드·다른 개정
                _standard("[12대수03-02]", _STD_2022),
            ]
        }
    )
    assert catalog.record_count == 3
    assert len(catalog.unique_codes) == 2
    assert catalog.codes_for(_STD_2022) == {"[10공수1-02-02]", "[12대수03-02]"}
    assert catalog.codes_for(_STD_2015) == {"[10공수1-02-02]"}
    assert catalog.revisions == (_STD_2015, _STD_2022)


def test_load_standards_rejects_malformed_payload() -> None:
    """분모를 모른 채 커버율을 내지 않는다 — 조용한 폴백 없이 즉시 ValueError."""
    with pytest.raises(ValueError):
        pbc.load_standards([])
    with pytest.raises(ValueError):
        pbc.load_standards({"items": []})
    with pytest.raises(ValueError):
        pbc.load_standards({"standards": [{"norm_id": "x"}]})  # code 없음


# ──────────────────────────────────────────────────────────────────────────
# 3. 정직 회계 — 데이터없음/비어있음/파싱 실패/필드 누락
# ──────────────────────────────────────────────────────────────────────────
def test_missing_file_and_empty_file_are_different_states(tmp_path: Path) -> None:
    """'데이터 없음'(파일 부재)과 '0건'(파일 존재·문항 0)을 구분한다."""
    empty = _write_corpus(tmp_path, "problem_bank_empty", [])
    missing = tmp_path / "problem_bank_ghost" / pbc.CORPUS_FILE_NAME

    empty_load = pbc.load_corpus_file(empty, name="problem_bank_empty")
    missing_load = pbc.load_corpus_file(missing, name="problem_bank_ghost")

    assert empty_load.status == "비어있음"
    assert missing_load.status == "데이터없음"
    assert empty_load.status != missing_load.status
    assert len(empty_load.records) == len(missing_load.records) == 0


def test_parse_failures_are_counted_with_exception_type(tmp_path: Path) -> None:
    """파싱 실패 라인을 조용히 버리지 않고 예외 타입명과 함께 보고한다(침묵 실패 금지)."""
    path = tmp_path / "problem_bank_broken" / pbc.CORPUS_FILE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_problem(problem_id="ok"), ensure_ascii=False)
        + "\n"
        + "{ not json\n"  # JSONDecodeError
        + json.dumps({"unit_codes": "QUAD-EQ"}, ensure_ascii=False)  # TypeError(배열 아님)
        + "\n"
        + json.dumps([1, 2], ensure_ascii=False)  # TypeError(object 아님)
        + "\n",
        encoding="utf-8",
    )
    load = pbc.load_corpus_file(path, name="problem_bank_broken")

    assert len(load.records) == 1  # 나머지 라인은 계속 집계
    assert [e.line_no for e in load.parse_errors] == [2, 3, 4]
    assert [e.error_type for e in load.parse_errors] == [
        "JSONDecodeError",
        "TypeError",
        "TypeError",
    ]
    assert all(e.corpus == "problem_bank_broken" for e in load.parse_errors)


def test_field_gaps_counted_separately(tmp_path: Path) -> None:
    """필드 누락을 0으로 위장하지 않고 항목별로 센다."""
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_gaps",
        [
            _problem(problem_id="a", units=[], standards=[], difficulty=None, question_format=None),
            _problem(problem_id="b"),
        ],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_gaps"),), catalog, revision=_STD_2022
    )

    assert report.total_problems == 2
    assert report.problems_without_unit_codes == 1
    assert report.problems_without_standard_codes == 1
    assert report.problems_without_difficulty == 1
    assert report.problems_without_question_format == 1
    # 미태깅 문항도 매트릭스에서 사라지지 않는다.
    assert report.unit_band_matrix[pbc.UNTAGGED_UNIT] == {pbc.BAND_UNSCORED: 1}
    assert report.per_corpus_formats["problem_bank_gaps"][pbc.UNSPECIFIED_FORMAT] == 1


def test_unknown_and_other_revision_codes_are_separated(tmp_path: Path) -> None:
    """대장에 없는 코드 / 다른 개정에만 있는 코드 / 대상 개정 코드를 3분류한다."""
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_codes",
        [
            _problem(problem_id="a", standards=["[10공수1-02-02]"]),  # 대상 개정
            _problem(problem_id="b", standards=["[2수01-01]"]),  # 2015에만 존재
            _problem(problem_id="c", standards=["[99없음-01-01]"]),  # 대장에 없음
        ],
    )
    catalog = pbc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-02]", _STD_2022),
                _standard("[2수01-01]", _STD_2015, school_type="초등학교"),
            ]
        }
    )
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_codes"),), catalog, revision=_STD_2022
    )

    assert report.covered_codes == ("[10공수1-02-02]",)
    assert report.other_revision_only_codes == {"[2수01-01]": 1}
    assert report.unknown_standard_codes == {"[99없음-01-01]": 1}
    assert report.problems_per_covered_code == {"[10공수1-02-02]": 1}


# ──────────────────────────────────────────────────────────────────────────
# 4. 집계 정확성 — 커버율·0커버·매트릭스·분해
# ──────────────────────────────────────────────────────────────────────────
def _sample_report(tmp_path: Path) -> pbc.CoverageReport:
    corpus_a = _write_corpus(
        tmp_path,
        "problem_bank_a",
        [
            _problem(problem_id="a1", units=["QUAD-EQ"], difficulty=2.5),
            _problem(problem_id="a2", units=["QUAD-EQ", "POLY-ROOT"], difficulty=4.5),
        ],
    )
    corpus_b = _write_corpus(
        tmp_path,
        "problem_bank_b",
        [
            _problem(
                problem_id="b1",
                units=["POLY-ROOT"],
                standards=["[12대수03-02]"],
                difficulty=1.2,
                question_format="객관식",
            )
        ],
    )
    catalog = pbc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-02]"),
                _standard("[12대수03-02]"),
                _standard("[12확통02-04]", domain="확률"),
                _standard("[2수01-01]", school_type="초등학교", domain="수와 연산"),
            ]
        }
    )
    loads = (
        pbc.load_corpus_file(corpus_a, name="problem_bank_a"),
        pbc.load_corpus_file(corpus_b, name="problem_bank_b"),
    )
    return pbc.build_report(loads, catalog, revision=_STD_2022)


def test_coverage_counts_and_zero_list(tmp_path: Path) -> None:
    report = _sample_report(tmp_path)
    assert report.total_problems == 3
    assert report.target_codes_total == 4
    assert report.covered_codes == ("[10공수1-02-02]", "[12대수03-02]")
    # 0커버 목록 정렬은 코드 사전순 고정(결정론).
    assert report.zero_coverage_codes == ("[12확통02-04]", "[2수01-01]")
    assert report.coverage_rate == pytest.approx(0.5)
    assert report.coverage_by_school_type == {"고등학교": (2, 3), "초등학교": (0, 1)}
    assert report.coverage_by_domain["확률"] == (0, 1)


def test_multi_unit_problem_counted_in_each_unit(tmp_path: Path) -> None:
    """한 문항이 여러 단원을 가지면 각 단원에 1씩 — 단원 합계는 문항 수와 다를 수 있다."""
    report = _sample_report(tmp_path)
    assert report.unit_band_matrix["QUAD-EQ"] == {
        pbc.BAND_PROCEDURAL: 1,
        pbc.BAND_MASTERY: 1,
    }
    assert report.unit_band_matrix["POLY-ROOT"] == {
        pbc.BAND_MASTERY: 1,
        pbc.BAND_AWARENESS: 1,
    }
    assert sum(report.unit_totals.values()) == 4  # 문항 3 < 단원 귀속 4
    assert sum(report.band_totals.values()) == report.total_problems


def test_per_corpus_decomposition(tmp_path: Path) -> None:
    report = _sample_report(tmp_path)
    assert report.per_corpus_bands["problem_bank_a"] == {
        pbc.BAND_PROCEDURAL: 1,
        pbc.BAND_MASTERY: 1,
    }
    assert report.per_corpus_formats["problem_bank_a"] == {"단답형": 2}
    assert report.per_corpus_formats["problem_bank_b"] == {"객관식": 1}
    assert report.format_totals == {"단답형": 2, "객관식": 1}


def test_coverage_rate_is_none_when_denominator_zero(tmp_path: Path) -> None:
    """분모 0이면 커버율은 None — 가짜 0.0/1.0 금지."""
    corpus = _write_corpus(tmp_path, "problem_bank_x", [_problem()])
    catalog = pbc.load_standards({"standards": [_standard("[2수01-01]", _STD_2015)]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_x"),), catalog, revision=_STD_2015
    )
    # 2015 개정 분모는 1이라 0이 아니다 — 분모 0 상황은 비어 있는 대장으로 만든다.
    assert report.target_codes_total == 1
    empty = pbc.build_report((), pbc.StandardsCatalog(entries=()), revision=_STD_2022)
    assert empty.coverage_rate is None
    assert "데이터없음" in pbc.render_report(empty)


# ──────────────────────────────────────────────────────────────────────────
# 5. 결정론 — 같은 입력 → 같은 바이트, 삽입 순서 무의존
# ──────────────────────────────────────────────────────────────────────────
def test_render_and_json_are_byte_identical_across_runs(tmp_path: Path) -> None:
    first = _sample_report(tmp_path)
    second = _sample_report(tmp_path)
    assert pbc.render_report(first) == pbc.render_report(second)
    assert pbc.dump_json(first) == pbc.dump_json(second)


def test_output_independent_of_corpus_insertion_order(tmp_path: Path) -> None:
    """코퍼스 적재 순서가 매트릭스·집계 렌더를 바꾸지 않는다(정렬 고정)."""
    report = _sample_report(tmp_path)
    reversed_report = pbc.build_report(
        tuple(reversed(report.corpora)),
        pbc.load_standards(
            {
                "standards": [
                    _standard("[10공수1-02-02]"),
                    _standard("[12대수03-02]"),
                    _standard("[12확통02-04]", domain="확률"),
                    _standard("[2수01-01]", school_type="초등학교", domain="수와 연산"),
                ]
            }
        ),
        revision=_STD_2022,
    )
    assert report.sorted_units() == reversed_report.sorted_units()
    assert report.unit_band_matrix == reversed_report.unit_band_matrix
    assert report.covered_codes == reversed_report.covered_codes
    # 단원 정렬은 총량 내림차순 → 코드 오름차순(동률 결정론).
    assert report.sorted_units() == ("POLY-ROOT", "QUAD-EQ")


def test_zero_list_truncation_is_announced(tmp_path: Path) -> None:
    """0커버 목록을 잘랐으면 잘렸다고 쓴다(조용한 절단 금지)."""
    report = _sample_report(tmp_path)
    text = pbc.render_report(report, max_zero_codes=1)
    assert "…외 **1**건" in text
    assert "[12확통02-04]" in text  # 사전순 첫 코드만 실림
    assert "[2수01-01]" not in text
    # 전량은 JSON 산출물에 있다.
    payload = json.loads(pbc.dump_json(report))
    assert payload["zero_coverage_codes"] == ["[12확통02-04]", "[2수01-01]"]


# ──────────────────────────────────────────────────────────────────────────
# 6. 유형(problem_type) × 단원 축 (S3-27)
# ──────────────────────────────────────────────────────────────────────────
def test_type_unit_matrix_and_zero_coverage(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_types",
        [
            _problem(problem_id="t1", units=["QUAD-EQ"], problem_types=["ptype.solve-for-unknown"]),
            _problem(problem_id="t2", units=["QUAD-EQ"], problem_types=["ptype.solve-for-unknown"]),
            _problem(
                problem_id="t3", units=["ARITH-SEQ"], problem_types=["ptype.evaluate-expression"]
            ),
            _problem(problem_id="t4", units=["POLY-ROOT"]),  # 유형 미태깅.
        ],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_types"),),
        catalog,
        revision=_STD_2022,
        problem_types=(
            "ptype.solve-for-unknown",
            "ptype.evaluate-expression",
            "ptype.verify-claim",
        ),
    )

    assert report.type_unit_matrix["ptype.solve-for-unknown"] == {"QUAD-EQ": 2}
    assert report.type_unit_matrix["ptype.evaluate-expression"] == {"ARITH-SEQ": 1}
    assert report.type_totals["ptype.solve-for-unknown"] == 2
    assert report.zero_coverage_types == ("ptype.verify-claim",)
    assert report.problems_without_problem_type == 1


def test_zero_coverage_types_empty_when_catalog_unknown(tmp_path: Path) -> None:
    """카탈로그를 안 주면(기본값) '0커버'를 단정하지 않는다 — 정직 회계."""
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_types2",
        [_problem(problem_id="u1", problem_types=["ptype.solve-for-unknown"])],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_types2"),), catalog, revision=_STD_2022
    )
    assert report.problem_types_catalog == ()
    assert report.zero_coverage_types == ()
    assert report.type_totals["ptype.solve-for-unknown"] == 1


def test_load_problem_types_rejects_malformed_payload() -> None:
    """분모(카탈로그)를 모른 채 0커버를 내지 않는다 — 조용한 폴백 없이 즉시 ValueError."""
    with pytest.raises(ValueError):
        pbc.load_problem_types({"not": "a list"})
    with pytest.raises(ValueError):
        pbc.load_problem_types([{"name_ko": "누락"}])  # problem_type_id 없음
    with pytest.raises(ValueError):
        pbc.load_problem_types(["문자열도 안 됨"])


def test_load_problem_types_dedups_and_sorts() -> None:
    ids = pbc.load_problem_types(
        [
            {"problem_type_id": "ptype.verify-claim"},
            {"problem_type_id": "ptype.solve-for-unknown"},
            {"problem_type_id": "ptype.verify-claim"},  # 중복.
        ]
    )
    assert ids == ("ptype.solve-for-unknown", "ptype.verify-claim")


# ──────────────────────────────────────────────────────────────────────────
# 6.5 대학 축 (W1 — 학년축 최단경로 계획 §3)
# ──────────────────────────────────────────────────────────────────────────
_UNI = pbc.UNIVERSITY_REVISION  # "대학"


def _uni_standard(code: str, *, subject: str = "미적분학 I") -> dict[str, object]:
    return _standard(code, _UNI, school_type="대학교", domain=subject)


def test_university_catalog_none_is_byte_identical_regression(tmp_path: Path) -> None:
    """university_catalog 미제공(기본) — 대학 축 전 필드 빈 값·K-12 §1 헤드라인 완전 무변경."""
    without = _sample_report(tmp_path)
    corpus_a = tmp_path / "problem_bank_a" / pbc.CORPUS_FILE_NAME
    corpus_b = tmp_path / "problem_bank_b" / pbc.CORPUS_FILE_NAME
    catalog = pbc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-02]"),
                _standard("[12대수03-02]"),
                _standard("[12확통02-04]", domain="확률"),
                _standard("[2수01-01]", school_type="초등학교", domain="수와 연산"),
            ]
        }
    )
    with_none = pbc.build_report(
        (
            pbc.load_corpus_file(corpus_a, name="problem_bank_a"),
            pbc.load_corpus_file(corpus_b, name="problem_bank_b"),
        ),
        catalog,
        revision=_STD_2022,
        university_catalog=None,
    )
    assert with_none == without  # 새 파라미터 생략과 명시 None이 바이트 단위 동일(회귀 0).
    assert with_none.university_target_codes_total == 0
    assert with_none.university_covered_codes == ()
    assert with_none.university_zero_coverage_codes == ()
    assert with_none.university_coverage_rate is None
    assert "대학교" not in with_none.coverage_by_school_type


def test_university_coverage_counts_independent_of_k12_denominator(tmp_path: Path) -> None:
    """대학 코드는 K-12 target_codes_total에 합산되지 않는다 — 완전히 별도 분모."""
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_uni",
        [
            _problem(problem_id="k", standards=["[10공수1-02-02]"]),  # K-12 커버
            _problem(problem_id="u", standards=["[CALC1-01-01]"]),  # 대학 커버
        ],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    uni_catalog = pbc.load_standards(
        {
            "standards": [
                _uni_standard("[CALC1-01-01]"),
                _uni_standard("[CALC1-01-02]", subject="선형대수"),
            ]
        }
    )
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_uni"),),
        catalog,
        revision=_STD_2022,
        university_catalog=uni_catalog,
    )
    # K-12 헤드라인은 대학 코드와 무관 — 분모 1(기존과 동일), 대학 코드는 unknown에도 안 실림.
    assert report.target_codes_total == 1
    assert report.covered_codes == ("[10공수1-02-02]",)
    assert report.unknown_standard_codes == {}
    assert report.other_revision_only_codes == {}
    # 대학 축은 독립 분모 2 — 1커버·1미커버.
    assert report.university_target_codes_total == 2
    assert report.university_covered_codes == ("[CALC1-01-01]",)
    assert report.university_zero_coverage_codes == ("[CALC1-01-02]",)
    assert report.university_coverage_rate == pytest.approx(0.5)
    assert report.university_problems_per_covered_code == {"[CALC1-01-01]": 1}


def test_university_school_type_merges_into_existing_table_without_disturbing_k12_rows(
    tmp_path: Path,
) -> None:
    """coverage_by_school_type에 '대학교' 행이 추가되고, 기존 K-12 행은 변경되지 않는다."""
    report = _sample_report(tmp_path)  # 이 픽스처의 school_type 기대값은 위 §4에서 동결.
    baseline_school = dict(report.coverage_by_school_type)

    corpus_a = tmp_path / "problem_bank_a" / pbc.CORPUS_FILE_NAME
    corpus_b = tmp_path / "problem_bank_b" / pbc.CORPUS_FILE_NAME
    catalog = pbc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-02]"),
                _standard("[12대수03-02]"),
                _standard("[12확통02-04]", domain="확률"),
                _standard("[2수01-01]", school_type="초등학교", domain="수와 연산"),
            ]
        }
    )
    uni_catalog = pbc.load_standards(
        {"standards": [_uni_standard("[CALC1-01-01]"), _uni_standard("[LINALG-01-01]")]}
    )
    with_uni = pbc.build_report(
        (
            pbc.load_corpus_file(corpus_a, name="problem_bank_a"),
            pbc.load_corpus_file(corpus_b, name="problem_bank_b"),
        ),
        catalog,
        revision=_STD_2022,
        university_catalog=uni_catalog,
    )
    for key, value in baseline_school.items():
        assert with_uni.coverage_by_school_type[key] == value  # K-12 행 무변경
    assert with_uni.coverage_by_school_type["대학교"] == (0, 2)  # 문항 0건이라 미커버
    # 대학 과목(K-12 영역과 다른 granularity)은 by_domain에 섞이지 않는다.
    assert "미적분학 I" not in with_uni.coverage_by_domain
    assert with_uni.university_coverage_by_domain["미적분학 I"] == (0, 2)


def test_render_report_shows_university_section(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_uni2",
        [_problem(problem_id="u1", standards=["[CALC1-01-01]"])],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    uni_catalog = pbc.load_standards(
        {"standards": [_uni_standard("[CALC1-01-01]"), _uni_standard("[CALC1-01-02]")]}
    )
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_uni2"),),
        catalog,
        revision=_STD_2022,
        university_catalog=uni_catalog,
    )
    text = pbc.render_report(report)
    assert "## 1.6 대학 커버리지" in text
    assert "분모(대학 고유 코드) **2**" in text
    assert "커버된 코드: **1**" in text
    assert "`[CALC1-01-02]`" in text  # 0커버 목록에 등장
    assert "| 미적분학 I | 1 | 2 | 50.0% |" in text

    # university_catalog 미제공 — "미측정"으로 정직하게 표시(0/0으로 위장 금지).
    unmeasured = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_uni2"),), catalog, revision=_STD_2022
    )
    unmeasured_text = pbc.render_report(unmeasured)
    assert "대학 성취기준 대장 미측정" in unmeasured_text


def test_json_includes_university_block(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path, "problem_bank_uni3", [_problem(problem_id="u1", standards=["[CALC1-01-01]"])]
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    uni_catalog = pbc.load_standards({"standards": [_uni_standard("[CALC1-01-01]")]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_uni3"),),
        catalog,
        revision=_STD_2022,
        university_catalog=uni_catalog,
    )
    payload = json.loads(pbc.dump_json(report))
    assert payload["university"]["revision"] == _UNI
    assert payload["university"]["target_codes_total"] == 1
    assert payload["university"]["covered_code_count"] == 1
    assert payload["university"]["coverage_rate"] == pytest.approx(1.0)
    assert payload["university"]["covered_codes"] == ["[CALC1-01-01]"]
    assert payload["coverage_by_school_type"]["대학교"] == {"covered": 1, "total": 1}
    # K-12 헤드라인 키는 무변경(회귀 0).
    assert payload["standards"]["target_revision"] == _STD_2022


def test_render_report_shows_zero_coverage_type_list(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path,
        "problem_bank_types3",
        [_problem(problem_id="v1", problem_types=["ptype.solve-for-unknown"])],
    )
    catalog = pbc.load_standards({"standards": [_standard("[10공수1-02-02]")]})
    report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_types3"),),
        catalog,
        revision=_STD_2022,
        problem_types=("ptype.solve-for-unknown", "ptype.verify-claim"),
    )
    text = pbc.render_report(report)
    assert "## 2.5 유형(problem_type) × 단원 분포" in text
    assert "`ptype.verify-claim`" in text
    assert "1/2종 미커버" in text or "**1**/2종 미커버" in text

    empty_catalog_report = pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_types3"),), catalog, revision=_STD_2022
    )
    empty_text = pbc.render_report(empty_catalog_report)
    assert "카탈로그 미상" in empty_text


# ──────────────────────────────────────────────────────────────────────────
# 7. CLI — exit 0/2만(게이트 아님)
# ──────────────────────────────────────────────────────────────────────────
def _cli_env(
    tmp_path: Path, problems: list[dict[str, object]], *, problem_type_ids: list[str] | None = None
) -> tuple[Path, Path]:
    corpus_root = tmp_path / "corpus"
    _write_corpus(corpus_root, "problem_bank_cli", problems)
    standards = _write_standards(
        corpus_root / "standards_v1" / "standards.json",
        [_standard("[10공수1-02-02]"), _standard("[12확통02-04]")],
    )
    if problem_type_ids is not None:
        _write_problem_types(
            corpus_root / "problem_type_graph_v1" / "problem_types.jsonl", problem_type_ids
        )
    return corpus_root, standards


def test_cli_exit_zero_even_at_zero_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """커버율 0%여도 exit 0 — 관측 리포트이지 게이트가 아니다(corpus_audit_eval과의 차이)."""
    corpus_root, standards = _cli_env(tmp_path, [_problem(standards=["[없음-01]"], problem_id="z")])
    rc = pbc.main(["--corpus-root", str(corpus_root), "--standards", str(standards)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "커버된 코드: **0**" in out
    assert "0커버 코드: **2**" in out


def test_cli_exit_zero_with_parse_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """라인 파싱 실패는 리포트 카운트로 실리고 종료 코드를 바꾸지 않는다."""
    corpus_root, standards = _cli_env(tmp_path, [_problem()])
    broken = corpus_root / "problem_bank_cli" / pbc.CORPUS_FILE_NAME
    broken.write_text(broken.read_text(encoding="utf-8") + "{oops\n", encoding="utf-8")
    rc = pbc.main(["--corpus-root", str(corpus_root), "--standards", str(standards)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "| 파싱 실패 라인 | 1 |" in out
    assert "JSONDecodeError" in out


def test_cli_exit_two_on_missing_standards(tmp_path: Path) -> None:
    corpus_root, _ = _cli_env(tmp_path, [_problem()])
    rc = pbc.main(["--corpus-root", str(corpus_root), "--standards", str(tmp_path / "nope.json")])
    assert rc == pbc._EXIT_INPUT_ERROR


def test_cli_exit_two_on_unknown_revision(tmp_path: Path) -> None:
    corpus_root, standards = _cli_env(tmp_path, [_problem()])
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--revision",
            "2029 개정",
        ]
    )
    assert rc == pbc._EXIT_INPUT_ERROR


def test_cli_exit_two_on_named_corpus_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """명시 지정한 코퍼스가 없으면 0건으로 위장하지 않고 '데이터없음' + exit 2."""
    corpus_root, standards = _cli_env(tmp_path, [_problem()])
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--corpus",
            "problem_bank_ghost",
        ]
    )
    captured = capsys.readouterr()
    assert rc == pbc._EXIT_INPUT_ERROR
    assert "데이터없음" in captured.out
    assert "코퍼스 파일 없음" in captured.err


def test_cli_exit_two_when_corpus_root_empty(tmp_path: Path) -> None:
    standards = _write_standards(tmp_path / "standards.json", [_standard("[10공수1-02-02]")])
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    rc = pbc.main(["--corpus-root", str(empty_root), "--standards", str(standards)])
    assert rc == pbc._EXIT_INPUT_ERROR


def test_cli_json_artifact_is_deterministic(tmp_path: Path) -> None:
    corpus_root, standards = _cli_env(tmp_path, [_problem(), _problem(problem_id="p2")])
    out_a = tmp_path / "out" / "a.json"
    out_b = tmp_path / "out" / "b.json"
    for target in (out_a, out_b):
        rc = pbc.main(
            [
                "--corpus-root",
                str(corpus_root),
                "--standards",
                str(standards),
                "--json",
                str(target),
            ]
        )
        assert rc == 0
    assert out_a.read_bytes() == out_b.read_bytes()
    payload = json.loads(out_a.read_text(encoding="utf-8"))
    assert payload["total_problems"] == 2
    assert payload["standards"]["target_revision"] == _STD_2022
    assert payload["standards"]["coverage_rate"] == pytest.approx(0.5)
    assert payload["band_labels"] == list(pbc.BAND_LABELS)


def test_cli_wires_problem_types_catalog(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--problem-types`로 지정한 카탈로그가 유형×단원 축·0커버 목록에 실제로 반영된다."""
    corpus_root, standards = _cli_env(
        tmp_path,
        [_problem(problem_id="p1", problem_types=["ptype.solve-for-unknown"])],
        problem_type_ids=["ptype.solve-for-unknown", "ptype.verify-claim"],
    )
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--problem-types",
            str(corpus_root / "problem_type_graph_v1" / "problem_types.jsonl"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "`ptype.verify-claim`" in out
    assert "1/2종 미커버" in out or "**1**/2종 미커버" in out


def test_cli_missing_problem_types_warns_but_does_not_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """유형 카탈로그 파일이 없어도 exit 2로 막지 않는다 — 보조 축이라 경고만(침묵 실패 금지)."""
    corpus_root, standards = _cli_env(tmp_path, [_problem()])
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--problem-types",
            str(tmp_path / "no-such-catalog.jsonl"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "경고 — 유형 카탈로그 적재 실패" in captured.err
    assert "카탈로그 미상" in captured.out


# ──────────────────────────────────────────────────────────────────────────
# 8. 과목(subject) 축 (ARCH-28)
# ──────────────────────────────────────────────────────────────────────────
def _subject_report(tmp_path: Path, *, with_geometry_problem: bool) -> pbc.CoverageReport:
    """과목 축 픽스처 — 대수 코드 2종(한 문항이 둘 다 태그)·기하 코드 1종.

    `with_geometry_problem=False`면 기하 성취기준은 대장에만 있고 문항이 없다 —
    `zero_problem_subjects` 변별력(양방향)의 조작 변수다.
    """
    problems = [
        _problem(problem_id="s1", standards=["[12대수01-08]", "[12대수03-02]"]),
    ]
    if with_geometry_problem:
        problems.append(_problem(problem_id="s2", standards=["[12기하01-01]"]))
    corpus = _write_corpus(tmp_path, "problem_bank_subject", problems)
    catalog = pbc.load_standards(
        {
            "standards": [
                {**_standard("[12대수01-08]"), "subject": "12대수"},
                {**_standard("[12대수03-02]"), "subject": "12대수"},
                {**_standard("[12기하01-01]", domain="기하"), "subject": "12기하"},
            ]
        }
    )
    return pbc.build_report(
        (pbc.load_corpus_file(corpus, name="problem_bank_subject"),), catalog, revision=_STD_2022
    )


def test_load_standards_projects_subject_field() -> None:
    """대장의 `subject`를 투영하고, 결측은 빈 문자열로 남긴다(조용한 발명 금지)."""
    catalog = pbc.load_standards(
        {
            "standards": [
                {**_standard("[10공수1-02-02]"), "subject": "10공수1"},
                _standard("[12대수03-02]"),  # subject 키 자체가 없음
            ]
        }
    )
    assert {e.code: e.subject for e in catalog.entries} == {
        "[10공수1-02-02]": "10공수1",
        "[12대수03-02]": "",
    }


def test_coverage_by_subject_counts_and_multi_code_refs(tmp_path: Path) -> None:
    """과목별 커버(코드 기준)와 문항 참조(중복 가산) — 같은 과목 코드 2개 태그면 참조는 2."""
    report = _subject_report(tmp_path, with_geometry_problem=True)
    assert report.coverage_by_subject == {"12대수": (2, 2), "12기하": (1, 1)}
    assert report.problems_per_subject == {"12대수": 2, "12기하": 1}
    assert report.zero_problem_subjects == ()


def test_zero_problem_subject_detection_is_bidirectional(tmp_path: Path) -> None:
    """변별력 실측(ARCH-28 acceptance) — 과목 문항을 빼면 0문 과목으로 *나타나고*,
    다시 넣으면 *사라진다*. 성공/실패 양쪽에서 같은 값을 내면 검증이 아니라 위장이다."""
    present = _subject_report(tmp_path / "with", with_geometry_problem=True)
    assert present.zero_problem_subjects == ()

    absent = _subject_report(tmp_path / "without", with_geometry_problem=False)
    assert absent.zero_problem_subjects == ("12기하",)
    assert absent.coverage_by_subject["12기하"] == (0, 1)
    assert "12기하" not in absent.problems_per_subject


def test_subject_missing_is_reported_as_misang(tmp_path: Path) -> None:
    """대장 subject 결측을 숨기지 않는다 — `(미상)` 버킷으로 드러낸다(정직 회계)."""
    report = _sample_report(tmp_path)  # 픽스처 대장 4건 전부 subject 없음
    assert report.coverage_by_subject == {"(미상)": (2, 4)}
    assert report.problems_per_subject == {"(미상)": 3}
    # 커버가 0이 아니므로 0문 과목은 아니다 — 결측과 0문을 혼동하지 않는다.
    assert report.zero_problem_subjects == ()


def test_render_shows_subject_section_and_zero_subject_list(tmp_path: Path) -> None:
    absent = _subject_report(tmp_path / "without", with_geometry_problem=False)
    text = pbc.render_report(absent)
    assert "### 1.3 과목별 커버리지 (ARCH-28)" in text
    assert "| 12대수 | 2 | 2 | 100.0% | 2 |" in text
    assert "**0문 과목 1종**: `12기하`" in text
    # 기존 소절은 번호만 밀리고 그대로 있다(하위호환 렌더).
    assert "### 1.4 커버된 코드 상위 (문항 수)" in text
    assert "### 1.5 0커버 코드 목록" in text

    present = _subject_report(tmp_path / "with", with_geometry_problem=True)
    assert "- 0문 과목: 없음" in pbc.render_report(present)


def test_json_adds_subject_axis_and_keeps_existing_keys(tmp_path: Path) -> None:
    """JSON 하위호환 — 신규 키 3종이 추가되고 기존 키는 그대로다."""
    absent = _subject_report(tmp_path / "without", with_geometry_problem=False)
    payload = json.loads(pbc.dump_json(absent))
    assert payload["coverage_by_subject"] == {
        "12대수": {"covered": 2, "total": 2},
        "12기하": {"covered": 0, "total": 1},
    }
    assert payload["problems_per_subject"] == {"12대수": 2}
    assert payload["zero_problem_subjects"] == ["12기하"]
    for existing_key in (
        "coverage_by_school_type",
        "coverage_by_domain",
        "unit_band_matrix",
        "standards",
        "problems_per_covered_code",
        "honest_accounting",
    ):
        assert existing_key in payload


def test_cli_wires_university_standards(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--university-standards`로 지정한 대장이 §1.6 대학 커버리지에 실제로 반영된다."""
    corpus_root, standards = _cli_env(tmp_path, [_problem(standards=["[CALC1-01-01]"])])
    uni_standards = _write_standards(
        corpus_root / "standards_university_v1" / "standards.json",
        [_uni_standard("[CALC1-01-01]"), _uni_standard("[CALC1-01-02]", subject="선형대수")],
    )
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--university-standards",
            str(uni_standards),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "## 1.6 대학 커버리지" in out
    assert "분모(대학 고유 코드) **2**" in out
    assert "`[CALC1-01-02]`" in out  # 대학 0커버 코드
    assert "| 대학교 |" in out  # §1.1 학교급별 표에 병합된 행


def test_cli_missing_university_standards_warns_but_does_not_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """대학 대장 파일이 없어도 exit 2로 막지 않는다 — 보조 축이라 경고만(침묵 실패 금지)."""
    corpus_root, standards = _cli_env(tmp_path, [_problem()])
    rc = pbc.main(
        [
            "--corpus-root",
            str(corpus_root),
            "--standards",
            str(standards),
            "--university-standards",
            str(tmp_path / "no-such-university-catalog.json"),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "경고 — 대학 성취기준 대장 적재 실패" in captured.err
    assert "대학 성취기준 대장 미측정" in captured.out
