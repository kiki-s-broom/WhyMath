"""교육과정 개정판 crosswalk 리포트 테스트 — 결정론·정직 회계·발산 계산 동결(hermetic).

대상: `whymath_backend.harness.curriculum_revision_crosswalk_report`(CUR-01 관측 리포트).
실 코퍼스·DB·LLM·네트워크 0 — 대부분의 테스트는 `tmp_path`에 만든 소형 픽스처로 검증한다.

예외 하나(`test_real_repo_corpus_*`류): CUR-01 acceptance ①("현행 실측 고정")을 위해 저장소의
*실제* `data/corpus` 코퍼스를 읽어 "3어휘가 실제로 공존한다"는 조사 결과를 코드로 재현·고정한다.
이 테스트만 non-hermetic(실 파일 시스템 상태에 결합)이며, 그 사실을 테스트 docstring에 명기한다.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): 각 테스트는 *그 규약이 깨진 구현에서 실제로
실패하는지*를 기준으로 짰다 —
  - crosswalk 매핑 실패를 조용히 버리면 `unmapped_values`가 비어 실패한다.
  - 필드 누락과 미매핑을 합치면 정직 회계 단언이 실패한다.
  - 3어휘 중 한 값을 바꿔도 발산 건수가 그대로면 발산 계산이 죽은 코드라는 뜻 — 필수 변별 테스트.
  - dict 삽입 순서에 의존해 렌더하면 역순 입력 동일성 테스트가 실패한다.
  - 발산 임계로 exit 1을 내면 고발산 테스트가 실패한다(게이트 아님 동결).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from whymath_backend.harness import curriculum_revision_crosswalk_report as ccr


# ──────────────────────────────────────────────────────────────────────────
# 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def _write_standards(path: Path, revisions: list[str]) -> Path:
    """`standards.json` 픽스처 — 각 원소가 성취기준 1건의 `curriculum_revision` 값."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        {"code": f"[STD-{idx:02d}]", "curriculum_revision": rev}
        for idx, rev in enumerate(revisions)
    ]
    path.write_text(json.dumps({"standards": entries}, ensure_ascii=False), encoding="utf-8")
    return path


def _write_unit_yaml(path: Path, curriculum_rev: str | None, *, unit_id: str = "unit-01") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"unit_id": unit_id}
    if curriculum_rev is not None:
        payload["curriculum_rev"] = curriculum_rev
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def _write_problem_bank(root: Path, name: str, curriculum_versions: list[str | None]) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ccr.CORPUS_FILE_NAME
    lines = []
    for idx, version in enumerate(curriculum_versions):
        payload: dict[str, object] = {"problem_id": f"{name}-{idx}"}
        if version is not None:
            payload["curriculum_version"] = version
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────
# 1. crosswalk 매핑표 — 3어휘 전량 커버·미매핑 판정
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2022 개정", "2022_REVISION"),
        ("2015 개정", "2015_REVISION"),
        ("2009 개정", "2009_REVISION"),
        ("2022", "2022_REVISION"),
        ("2015", "2015_REVISION"),
        ("2009", "2009_REVISION"),
        ("2022_REVISION", "2022_REVISION"),
        ("2015_REVISION", "2015_REVISION"),
        ("2009_REVISION", "2009_REVISION"),
    ],
)
def test_canonicalize_covers_three_vocabularies(raw: str, expected: str) -> None:
    assert ccr.canonicalize(raw) == expected


def test_canonicalize_unmapped_value_returns_none() -> None:
    """crosswalk 표에 없는 값은 조용히 아무거나 반환하지 않고 명시적으로 `None`(미매핑 신호)."""
    assert ccr.canonicalize("1997 개정") is None
    assert ccr.canonicalize("") is None


def test_canonical_revisions_match_curriculum_enum() -> None:
    """`CANONICAL_REVISIONS`가 `schema.enums.Curriculum` 전 멤버와 정확히 일치(거버넌스)."""
    from whymath_backend.schema.enums import Curriculum

    assert set(ccr.CANONICAL_REVISIONS) == {member.value for member in Curriculum}
    assert ccr.CANONICAL_REVISIONS == tuple(sorted(ccr.CANONICAL_REVISIONS))  # 사전순 결정론


# ──────────────────────────────────────────────────────────────────────────
# 2. 로더 ① — standards_v1/standards.json
# ──────────────────────────────────────────────────────────────────────────
def test_parse_standards_payload_basic() -> None:
    payload = {
        "standards": [
            {"code": "[A]", "curriculum_revision": "2022 개정"},
            {"code": "[B]", "curriculum_revision": "2015 개정"},
        ]
    }
    observations, errors = ccr.parse_standards_payload(payload, source="standards.json")
    assert errors == ()
    assert [o.raw_value for o in observations] == ["2022 개정", "2015 개정"]
    assert all(o.axis == ccr.AXIS_STANDARDS for o in observations)


def test_parse_standards_payload_missing_field_is_none_not_error() -> None:
    """필드 누락(`curriculum_revision` 부재)은 파싱 실패가 아니라 `raw_value=None`(정직 회계)."""
    payload = {"standards": [{"code": "[A]"}]}
    observations, errors = ccr.parse_standards_payload(payload, source="s.json")
    assert errors == ()
    assert observations[0].raw_value is None


def test_parse_standards_payload_isolates_type_errors() -> None:
    """레코드 1건의 타입 오류는 그 레코드만 `ParseError`로 격리하고 나머지는 계속 집계한다."""
    payload = {
        "standards": [
            {"code": "[A]", "curriculum_revision": "2022 개정"},
            {"code": "[B]", "curriculum_revision": 2022},  # 문자열이 아님
            "이것도 object가 아님",
        ]
    }
    observations, errors = ccr.parse_standards_payload(payload, source="s.json")
    assert len(observations) == 1
    assert len(errors) == 2
    assert all(e.error_type == "TypeError" for e in errors)
    assert all(e.axis == ccr.AXIS_STANDARDS for e in errors)


@pytest.mark.parametrize(
    "payload",
    [
        "문자열",
        {"no_standards_key": []},
        {"standards": "배열이 아님"},
    ],
)
def test_parse_standards_payload_rejects_bad_structure(payload: object) -> None:
    """구조가 깨지면(최상위 dict 아님/standards 배열 없음) 즉시 ValueError(조용한 폴백 없음)."""
    with pytest.raises(ValueError):
        ccr.parse_standards_payload(payload, source="s.json")


def test_load_standards_axis_missing_file_is_no_data_not_error(tmp_path: Path) -> None:
    load = ccr.load_standards_axis(tmp_path / "nope.json")
    assert load.status == "데이터없음"
    assert load.observations == ()
    assert load.parse_errors == ()


def test_load_standards_axis_reads_real_file(tmp_path: Path) -> None:
    path = _write_standards(
        tmp_path / "standards_v1" / "standards.json",
        ["2022 개정", "2022 개정", "2015 개정"],
    )
    load = ccr.load_standards_axis(path)
    assert load.status == "적재됨"
    assert len(load.observations) == 3
    assert load.sources == ("standards.json",)


# ──────────────────────────────────────────────────────────────────────────
# 3. 로더 ② — units_v1/*.unit.yaml
# ──────────────────────────────────────────────────────────────────────────
def test_parse_unit_yaml_basic() -> None:
    text = yaml.safe_dump({"unit_id": "u1", "curriculum_rev": "2022"}, allow_unicode=True)
    obs = ccr.parse_unit_yaml(text, source="u1.unit.yaml")
    assert obs.raw_value == "2022"
    assert obs.axis == ccr.AXIS_UNIT_SPEC
    assert obs.line_no is None  # 단원 파일 1개 = 관측 1건(라인 개념 없음)


def test_parse_unit_yaml_missing_field_is_none() -> None:
    text = yaml.safe_dump({"unit_id": "u1"}, allow_unicode=True)
    obs = ccr.parse_unit_yaml(text, source="u1.unit.yaml")
    assert obs.raw_value is None


def test_parse_unit_yaml_rejects_non_object_root() -> None:
    with pytest.raises(TypeError):
        ccr.parse_unit_yaml("- 리스트\n- 임", source="bad.unit.yaml")


def test_discover_unit_files_sorted_and_excludes_provenance(tmp_path: Path) -> None:
    units_root = tmp_path / "units_v1"
    units_root.mkdir()
    (units_root / "_provenance.json").write_text("{}", encoding="utf-8")
    _write_unit_yaml(units_root / "b.unit.yaml", "2022")
    _write_unit_yaml(units_root / "a.unit.yaml", "2015")
    paths = ccr.discover_unit_files(units_root)
    assert [p.name for p in paths] == ["a.unit.yaml", "b.unit.yaml"]


def test_load_unit_spec_axis_missing_dir_is_no_data(tmp_path: Path) -> None:
    load = ccr.load_unit_spec_axis(tmp_path / "no-such-units")
    assert load.status == "데이터없음"


def test_load_unit_spec_axis_isolates_broken_file(tmp_path: Path) -> None:
    """단원 파일 하나가 깨져도 나머지 단원은 계속 집계한다(파일 단위 격리)."""
    units_root = tmp_path / "units_v1"
    _write_unit_yaml(units_root / "good.unit.yaml", "2022")
    (units_root / "broken.unit.yaml").write_text("{oops", encoding="utf-8")
    load = ccr.load_unit_spec_axis(units_root)
    assert len(load.observations) == 1
    assert len(load.parse_errors) == 1
    assert load.parse_errors[0].axis == ccr.AXIS_UNIT_SPEC


# ──────────────────────────────────────────────────────────────────────────
# 4. 로더 ③ — problem_bank*/problems.jsonl
# ──────────────────────────────────────────────────────────────────────────
def test_parse_problem_bank_line_basic() -> None:
    obs = ccr.parse_problem_bank_line(
        json.dumps({"curriculum_version": "2022_REVISION"}), source="pb", line_no=1
    )
    assert obs.raw_value == "2022_REVISION"
    assert obs.line_no == 1


def test_parse_problem_bank_line_missing_field_is_none() -> None:
    obs = ccr.parse_problem_bank_line(json.dumps({"problem_id": "p1"}), source="pb", line_no=1)
    assert obs.raw_value is None


def test_load_problem_bank_axis_merges_multiple_corpora(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    _write_problem_bank(root, "problem_bank_a", ["2022_REVISION", "2022_REVISION"])
    _write_problem_bank(root, "problem_bank_b", ["2015_REVISION"])
    load, problems = ccr.load_problem_bank_axis(root)
    assert problems == []
    assert len(load.observations) == 3
    assert set(load.sources) == {"problem_bank_a", "problem_bank_b"}
    assert load.status == "적재됨"


def test_load_problem_bank_axis_auto_discovery_empty_is_not_fatal(
    tmp_path: Path,
) -> None:
    """자동 탐색으로 0건이면(명시 지정 아님) fatal 메시지를 내지 않는다 — 축이 비어도 관측 유효."""
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    load, problems = ccr.load_problem_bank_axis(empty_root)
    assert problems == []
    assert load.status == "데이터없음"


def test_load_problem_bank_axis_named_corpus_missing_reports_problem(
    tmp_path: Path,
) -> None:
    """명시 지정한 코퍼스가 없으면(사용자 실수) 0건으로 위장하지 않고 problems 메시지를 낸다."""
    root = tmp_path / "corpus"
    root.mkdir()
    load, problems = ccr.load_problem_bank_axis(root, ["problem_bank_ghost"])
    assert load.status == "데이터없음"
    assert len(problems) == 1
    assert "problem_bank_ghost" in problems[0]


def test_load_problem_bank_axis_isolates_parse_errors(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    path = _write_problem_bank(root, "problem_bank_c", ["2022_REVISION"])
    path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
    load, _ = ccr.load_problem_bank_axis(root)
    assert len(load.observations) == 1
    assert len(load.parse_errors) == 1
    assert load.parse_errors[0].error_type == "JSONDecodeError"


# ──────────────────────────────────────────────────────────────────────────
# 5. 로더 ④ — curriculum_entry(대응 코퍼스 없음)
# ──────────────────────────────────────────────────────────────────────────
def test_curriculum_entry_axis_always_unavailable() -> None:
    """대응 코퍼스가 없다고 조사로 확인된 축 — 항상 '대응코퍼스없음', 관측 0건."""
    load = ccr.curriculum_entry_axis_unavailable()
    assert load.status == "대응코퍼스없음"
    assert load.observations == ()
    assert load.sources == ()
    assert load.axis == ccr.AXIS_CURRICULUM_ENTRY


# ──────────────────────────────────────────────────────────────────────────
# 6. build_report — 축별 분포·미매핑·필드 누락 정직 회계
# ──────────────────────────────────────────────────────────────────────────
def _loads(
    *,
    standards_revisions: list[str] | None = None,
    unit_revs: list[str | None] | None = None,
    problem_versions: list[str | None] | None = None,
    tmp_path: Path,
) -> tuple[ccr.AxisLoad, ...]:
    """네 축의 `AxisLoad`를 픽스처로 조립(build_report 입력 — 순수 함수 테스트용)."""
    standards_path = _write_standards(
        tmp_path / "standards_v1" / "standards.json", standards_revisions or []
    )
    standards_load = ccr.load_standards_axis(standards_path)

    units_root = tmp_path / "units_v1"
    for idx, rev in enumerate(unit_revs or []):
        _write_unit_yaml(units_root / f"u{idx}.unit.yaml", rev, unit_id=f"u{idx}")
    unit_load = ccr.load_unit_spec_axis(units_root)

    corpus_root = tmp_path / "corpus"
    _write_problem_bank(corpus_root, "problem_bank_x", problem_versions or [])
    problem_load, _ = ccr.load_problem_bank_axis(corpus_root)

    curriculum_entry_load = ccr.curriculum_entry_axis_unavailable()
    return (standards_load, unit_load, problem_load, curriculum_entry_load)


def test_build_report_axis_distributions(tmp_path: Path) -> None:
    loads = _loads(
        standards_revisions=["2022 개정", "2022 개정", "2015 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION", "2022_REVISION"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    assert report.axis_raw_distribution[ccr.AXIS_STANDARDS] == {
        "2022 개정": 2,
        "2015 개정": 1,
    }
    assert report.axis_canonical_distribution[ccr.AXIS_STANDARDS] == {
        "2022_REVISION": 2,
        "2015_REVISION": 1,
    }
    assert report.axis_canonical_distribution[ccr.AXIS_UNIT_SPEC] == {"2022_REVISION": 1}
    assert report.axis_canonical_distribution[ccr.AXIS_PROBLEM_BANK] == {"2022_REVISION": 2}


def test_build_report_unmapped_values_counted_separately(tmp_path: Path) -> None:
    """crosswalk 표에 없는 값은 조용히 버리지 않고 '미매핑'으로 별도 카운트한다."""
    loads = _loads(
        standards_revisions=["2022 개정", "1997 개정"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    assert report.unmapped_values[ccr.AXIS_STANDARDS] == {"1997 개정": 1}
    assert report.unmapped_total == 1
    # 미매핑 값은 전역 발산 계산에서 제외된다(모르는 값과 다수결이 다르다고 단정 금지).
    assert report.global_canonical_totals == {"2022_REVISION": 1}


def test_build_report_missing_field_counted_separately_from_unmapped(
    tmp_path: Path,
) -> None:
    """필드 누락(`None`)과 미매핑(값은 있으나 표에 없음)은 서로 다른 사유로 분리 집계된다."""
    standards_path = tmp_path / "standards_v1" / "standards.json"
    standards_path.parent.mkdir(parents=True, exist_ok=True)
    standards_path.write_text(
        json.dumps(
            {
                "standards": [
                    {"code": "[A]"},
                    {"code": "[B]", "curriculum_revision": "1997 개정"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    standards_load = ccr.load_standards_axis(standards_path)
    loads = (
        standards_load,
        ccr.load_unit_spec_axis(tmp_path / "no-units"),
        ccr.load_problem_bank_axis(tmp_path / "no-corpus")[0],
        ccr.curriculum_entry_axis_unavailable(),
    )
    report = ccr.build_report(loads)
    assert report.missing_field_counts[ccr.AXIS_STANDARDS] == 1
    assert report.unmapped_values[ccr.AXIS_STANDARDS] == {"1997 개정": 1}
    assert report.unmapped_total == 1


def test_build_report_zero_data_canonical_revisions(tmp_path: Path) -> None:
    """enum엔 있으나 실측 0건인 정규 개정판(2009_REVISION 등)을 명시한다."""
    loads = _loads(
        standards_revisions=["2022 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    assert "2009_REVISION" in report.zero_data_canonical_revisions
    assert "2015_REVISION" in report.zero_data_canonical_revisions
    assert "2022_REVISION" not in report.zero_data_canonical_revisions


def test_build_report_no_observations_has_no_majority() -> None:
    """관측이 전무하면 다수결·발산 모두 정의 불가(가짜 0 금지)."""
    loads = (
        ccr.AxisLoad(
            axis=ccr.AXIS_STANDARDS,
            status="비어있음",
            sources=(),
            observations=(),
            parse_errors=(),
        ),
        ccr.AxisLoad(
            axis=ccr.AXIS_UNIT_SPEC,
            status="데이터없음",
            sources=(),
            observations=(),
            parse_errors=(),
        ),
        ccr.AxisLoad(
            axis=ccr.AXIS_PROBLEM_BANK,
            status="데이터없음",
            sources=(),
            observations=(),
            parse_errors=(),
        ),
        ccr.curriculum_entry_axis_unavailable(),
    )
    report = ccr.build_report(loads)
    assert report.majority_canonical is None
    assert report.divergence_total == 0


# ──────────────────────────────────────────────────────────────────────────
# 7. 발산(divergence) 계산 — 다수결·변별력 필수 테스트(acceptance ④)
# ──────────────────────────────────────────────────────────────────────────
def test_divergence_computed_against_global_majority(tmp_path: Path) -> None:
    """단원·문제은행이 전부 2022_REVISION, 성취기준만 일부 2015 개정 → 발산은 그 소수분과 일치."""
    loads = _loads(
        standards_revisions=["2022 개정", "2022 개정", "2022 개정", "2015 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION", "2022_REVISION"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    assert report.majority_canonical == "2022_REVISION"
    assert report.divergence_total == 1
    assert report.divergence_by_axis == {ccr.AXIS_STANDARDS: 1}


def test_divergence_total_changes_when_one_vocabulary_value_flipped(
    tmp_path: Path,
) -> None:
    """**변별력 필수 테스트**(acceptance ④) — 3어휘 중 하나(성취기준 한 건)의 원시값을 바꾸면
    발산 건수가 실제로 달라진다. 성공/실패 양쪽에서 같은 값을 내면 발산 계산이 죽은 코드라는
    뜻이므로, 이 테스트가 실패하면 `build_report`의 발산 로직이 회귀한 것이다.
    """
    baseline_loads = _loads(
        standards_revisions=["2022 개정", "2022 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION", "2022_REVISION"],
        tmp_path=tmp_path / "baseline",
    )
    baseline_report = ccr.build_report(baseline_loads)
    assert baseline_report.divergence_total == 0  # 전부 2022_REVISION → 발산 없음

    # 성취기준 축의 값 하나만 "2022 개정" → "2015 개정"으로 뒤집는다(다른 두 축은 불변).
    flipped_loads = _loads(
        standards_revisions=["2022 개정", "2015 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION", "2022_REVISION"],
        tmp_path=tmp_path / "flipped",
    )
    flipped_report = ccr.build_report(flipped_loads)

    assert flipped_report.divergence_total != baseline_report.divergence_total
    assert flipped_report.divergence_total == 1
    assert flipped_report.divergence_by_axis[ccr.AXIS_STANDARDS] == 1


def test_divergence_majority_tie_break_is_deterministic() -> None:
    """다수결이 동률이면 정규 키 사전순 최솟값으로 결정론 타이브레이크(난수·삽입순 의존 금지)."""
    loads = (
        ccr.AxisLoad(
            axis=ccr.AXIS_STANDARDS,
            status="적재됨",
            sources=("s.json",),
            observations=(
                ccr.AxisObservation(ccr.AXIS_STANDARDS, "s.json", 1, "2022 개정"),
                ccr.AxisObservation(ccr.AXIS_STANDARDS, "s.json", 2, "2015 개정"),
            ),
            parse_errors=(),
        ),
        ccr.AxisLoad(
            axis=ccr.AXIS_UNIT_SPEC,
            status="데이터없음",
            sources=(),
            observations=(),
            parse_errors=(),
        ),
        ccr.AxisLoad(
            axis=ccr.AXIS_PROBLEM_BANK,
            status="데이터없음",
            sources=(),
            observations=(),
            parse_errors=(),
        ),
        ccr.curriculum_entry_axis_unavailable(),
    )
    report = ccr.build_report(loads)
    # 2015_REVISION < 2022_REVISION(사전순) — 1건씩 동률이면 더 작은 키가 다수결로 뽑힌다.
    assert report.majority_canonical == "2015_REVISION"
    assert report.divergence_total == 1  # 2022 개정 1건만 다수결과 다름


# ──────────────────────────────────────────────────────────────────────────
# 8. 렌더·JSON — 결정론·정직 회계 표면화
# ──────────────────────────────────────────────────────────────────────────
def test_render_report_shows_all_sections(tmp_path: Path) -> None:
    loads = _loads(
        standards_revisions=["2022 개정", "2015 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    text = ccr.render_report(report)
    assert "# 교육과정 개정판 어휘 crosswalk 관측 리포트 (CUR-01)" in text
    assert "## 1. crosswalk 매핑표" in text
    assert "## 5. 발산(divergence) 리포트" in text
    assert "발산 총건수: 1" in text
    assert "대응코퍼스없음" in text  # curriculum_entry 축


def test_render_report_deterministic_regardless_of_dict_order(tmp_path: Path) -> None:
    """dict 삽입 순서에 의존해 렌더하면 이 테스트가 실패한다(정렬 고정 회귀 감지)."""
    loads_a = _loads(
        standards_revisions=["2022 개정", "2015 개정", "2015 개정"],
        tmp_path=tmp_path / "a",
    )
    loads_b = _loads(
        standards_revisions=["2015 개정", "2015 개정", "2022 개정"],  # 역순 입력
        tmp_path=tmp_path / "b",
    )
    text_a = ccr.render_report(ccr.build_report(loads_a))
    text_b = ccr.render_report(ccr.build_report(loads_b))
    assert text_a == text_b


def test_report_to_json_roundtrip_and_deterministic(tmp_path: Path) -> None:
    loads = _loads(
        standards_revisions=["2022 개정", "2015 개정"],
        unit_revs=["2022"],
        problem_versions=["2022_REVISION"],
        tmp_path=tmp_path,
    )
    report = ccr.build_report(loads)
    dump_a = ccr.dump_json(report)
    dump_b = ccr.dump_json(report)
    assert dump_a == dump_b
    payload = json.loads(dump_a)
    assert payload["divergence_total"] == 1
    assert payload["majority_canonical"] == "2022_REVISION"
    assert "2009_REVISION" in payload["zero_data_canonical_revisions"]


# ──────────────────────────────────────────────────────────────────────────
# 9. CLI — exit 0/2만(게이트 아님)
# ──────────────────────────────────────────────────────────────────────────
def _cli_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    corpus_root = tmp_path / "corpus"
    standards = _write_standards(
        corpus_root / "standards_v1" / "standards.json", ["2022 개정", "2015 개정"]
    )
    units_root = corpus_root / "units_v1"
    _write_unit_yaml(units_root / "u0.unit.yaml", "2022")
    _write_problem_bank(corpus_root, "problem_bank_cli", ["2022_REVISION"])
    return corpus_root, standards, units_root


def test_cli_exit_zero_even_at_high_divergence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """발산이 커도 exit 0 — 관측 리포트이지 게이트가 아니다."""
    corpus_root, standards, units_root = _cli_env(tmp_path)
    rc = ccr.main(
        [
            "--standards",
            str(standards),
            "--units-root",
            str(units_root),
            "--corpus-root",
            str(corpus_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "발산 총건수: 1" in out


def test_cli_exit_two_on_missing_standards(tmp_path: Path) -> None:
    rc = ccr.main(["--standards", str(tmp_path / "nope.json")])
    assert rc == ccr._EXIT_INPUT_ERROR


def test_cli_exit_two_on_malformed_standards(tmp_path: Path) -> None:
    bad = tmp_path / "standards.json"
    bad.write_text(json.dumps({"no_standards_key": True}), encoding="utf-8")
    rc = ccr.main(["--standards", str(bad)])
    assert rc == ccr._EXIT_INPUT_ERROR


def test_cli_missing_units_root_is_non_fatal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """단원 축 디렉터리 부재는 fatal이 아니다 — '데이터없음'으로 표시되고 exit 0."""
    corpus_root, standards, _ = _cli_env(tmp_path)
    rc = ccr.main(
        [
            "--standards",
            str(standards),
            "--units-root",
            str(tmp_path / "no-such-units"),
            "--corpus-root",
            str(corpus_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "`units_v1.curriculum_rev` | 데이터없음" in out


def test_cli_exit_two_on_named_corpus_absent(tmp_path: Path) -> None:
    """명시 지정한 문제은행 코퍼스가 없으면 exit 2(사용자 실수)."""
    corpus_root, standards, units_root = _cli_env(tmp_path)
    rc = ccr.main(
        [
            "--standards",
            str(standards),
            "--units-root",
            str(units_root),
            "--corpus-root",
            str(corpus_root),
            "--corpus",
            "problem_bank_ghost",
        ]
    )
    assert rc == ccr._EXIT_INPUT_ERROR


def test_cli_json_artifact_is_deterministic(tmp_path: Path) -> None:
    corpus_root, standards, units_root = _cli_env(tmp_path)
    out_a = tmp_path / "out" / "a.json"
    out_b = tmp_path / "out" / "b.json"
    for target in (out_a, out_b):
        rc = ccr.main(
            [
                "--standards",
                str(standards),
                "--units-root",
                str(units_root),
                "--corpus-root",
                str(corpus_root),
                "--json",
                str(target),
            ]
        )
        assert rc == 0
    assert out_a.read_bytes() == out_b.read_bytes()


# ──────────────────────────────────────────────────────────────────────────
# 10. 실측 고정 — acceptance ①(non-hermetic, 실 저장소 코퍼스 읽기)
# ──────────────────────────────────────────────────────────────────────────
def test_real_repo_corpus_confirms_three_vocabulary_coexistence() -> None:
    """CUR-01 acceptance ① — 조사로 확인된 "3어휘 공존"을 실제 저장소 코퍼스로 재현·고정한다.

    **이 테스트만 hermetic이 아니다** — `tmp_path` 픽스처가 아니라 저장소의 실제
    `data/corpus/standards_v1`·`units_v1`·`problem_bank*`를 직접 읽는다(DB·LLM·HTTP는 여전히
    0 — 로컬 파일만). 코퍼스가 바뀌면 이 테스트가 깨져 "현행 실측"이 문서(조사 결과)와
    어긋났음을 드러낸다 — 그것이 이 테스트의 목적이다(가정이 아니라 실측 고정).

    조사로 확인된 현재 사실(2026-08-03 실측):
      - standards_v1: 895건 중 "2022 개정" 435건·"2015 개정" 460건(2어휘 중 하나).
      - units_v1: 파일 1개(`quadratic_maxmin.unit.yaml`), `curriculum_rev="2022"`(연도만 표기).
        → 2026-10-07 P3-03: 미적분Ⅰ '미분' 초안 10편 반입으로 파일 11개 — 전부 `"2022"`(어휘 ② 유지).
      - problem_bank*: 전량(2638건 — 2026-08-03 실측 2647건에서 QUAL-02 실중복 은퇴 9건 반영)
        `curriculum_version="2022_REVISION"`(enum 값 표기).
      - curriculum_entry: 대응 코퍼스 없음(관측 불가).
    """
    standards_load = ccr.load_standards_axis(ccr.DEFAULT_STANDARDS_PATH)
    unit_load = ccr.load_unit_spec_axis(ccr.DEFAULT_UNITS_ROOT)
    problem_load, problems = ccr.load_problem_bank_axis(ccr.DEFAULT_CORPUS_ROOT)
    curriculum_entry_load = ccr.curriculum_entry_axis_unavailable()

    assert problems == []  # 자동 탐색으로 problem_bank* 코퍼스를 찾지 못하면 이 단언이 깨진다.

    # ① standards_v1 — 두 개정판이 실제로 공존(어휘 ①: 한글 "OO 개정").
    standards_raw = {obs.raw_value for obs in standards_load.observations}
    assert standards_raw == {"2022 개정", "2015 개정"}

    # ② units_v1 — 연도만 표기(어휘 ②). 2026-10-07 P3-03: 파일 1개 → 11개(미적분Ⅰ 미분 초안 10편
    # 반입·의도된 진전). 첫 파일만 보던 단언을 *전 파일*이 연도 표기인지로 넓혔다(약화 아님).
    assert len(unit_load.observations) == 11
    assert {obs.raw_value for obs in unit_load.observations} == {"2022"}

    # ③ problem_bank* — enum 값 표기(어휘 ③), 2015/2009_REVISION은 실 데이터 0건.
    problem_raw = {obs.raw_value for obs in problem_load.observations}
    assert problem_raw == {"2022_REVISION"}

    # ④ curriculum_entry — 대응 코퍼스 없음(관측 불가, 조사 결과 그대로).
    assert curriculum_entry_load.status == "대응코퍼스없음"

    report = ccr.build_report((standards_load, unit_load, problem_load, curriculum_entry_load))
    # 다수결은 2022_REVISION(단원·문제은행 전량 + 성취기준 다수), 발산은 2015 개정 성취기준 수.
    assert report.majority_canonical == "2022_REVISION"
    assert report.divergence_total == report.global_canonical_totals.get("2015_REVISION", 0)
    assert report.divergence_total > 0  # 실제로 발산이 관측된다(3어휘가 겉으로만 다른 게 아님).
    assert "2009_REVISION" in report.zero_data_canonical_revisions
