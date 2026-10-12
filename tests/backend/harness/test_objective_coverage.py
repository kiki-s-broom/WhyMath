"""학습목표(Objective) 커버리지 리포트 CLI 테스트 — 결정론·정직 회계·집계 정확성 동결(hermetic).

대상: `whymath_backend.harness.objective_coverage`(CUR-02 관측 리포트). 실 코퍼스·DB·LLM·네트워크
0 — 합성 fixture(tmp_path)로 검증하되, acceptance ①(현행 실측 고정)만 저장소의 실제 코퍼스
(`data/corpus/standards_v1/standards.json`+`data/corpus/units_v1/`)를 직접 읽는다
(`test_problem_type_mapping.py`의 실코퍼스 대조 패턴 재사용).

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지"): 각 테스트는 *그 규약이 깨진 구현에서 실제로
실패하는지*를 기준으로 짰다 —
  - unit_id 누락으로 파일 전체를 버리면 "적재됨"·objectives_total이 사라져 실패한다.
  - "데이터없음"과 "비어있음"을 합치면 상태 단언이 실패한다.
  - 커버율 임계로 exit 1을 내면 0% 커버 테스트가 실패한다(게이트 아님 동결).
  - 소단원 1건 추가로 커버리지 %가 안 움직이면 acceptance④ 변별력 테스트가 실패한다.
  - dict 삽입 순서에 의존해 렌더하면 역순 입력 동일성 테스트가 실패한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from whymath_backend.harness import objective_coverage as oc

# ──────────────────────────────────────────────────────────────────────────
# 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────────────────
_REV_2022 = "2022 개정"
_REV_2015 = "2015 개정"


def _standard(
    code: str,
    revision: str = _REV_2022,
    *,
    school_type: str = "고등학교",
    subject: str = "10공수1",
    domain: str = "대수",
    sub_domain: str = "이차함수",
) -> dict[str, object]:
    return {
        "norm_id": f"{revision[:4]}_{code}",
        "code": code,
        "curriculum_revision": revision,
        "school_type": school_type,
        "subject": subject,
        "domain": domain,
        "sub_domain": sub_domain,
    }


def _write_standards(path: Path, entries: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"standards": entries}, ensure_ascii=False), encoding="utf-8")
    return path


def _objective(
    *, standard_code: str | None = "[10공수1-02-06]", k_type: str | None = "CONCEPT"
) -> dict[str, object]:
    payload: dict[str, object] = {"suffix": "OBJ-01", "statement": "설명"}
    if standard_code is not None:
        payload["standard_code"] = standard_code
    if k_type is not None:
        payload["k_type"] = k_type
    return payload


def _unit_yaml(
    *,
    unit_id: str | None = "10공수1-이차함수-최대최소",
    curriculum_rev: str | None = "2022",
    standard_codes: list[str] | None = None,
    objectives: list[dict[str, object]] | None = None,
) -> str:
    doc: dict[str, object] = {}
    if unit_id is not None:
        doc["unit_id"] = unit_id
    if curriculum_rev is not None:
        doc["curriculum_rev"] = curriculum_rev
    doc["standard_codes"] = standard_codes if standard_codes is not None else ["[10공수1-02-06]"]
    doc["objectives"] = objectives if objectives is not None else [_objective()]
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _write_unit(root: Path, name: str, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.unit.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ──────────────────────────────────────────────────────────────────────────
# 1. 성취기준 대장 — 레코드 수 ≠ 고유 코드 수
# ──────────────────────────────────────────────────────────────────────────
def test_catalog_distinguishes_records_from_unique_codes() -> None:
    catalog = oc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-06]", _REV_2022),
                _standard("[10공수1-02-06]", _REV_2015),  # 같은 코드·다른 개정
                _standard("[12대수03-02]", _REV_2022),
            ]
        }
    )
    assert catalog.record_count == 3
    assert len(catalog.unique_codes) == 2
    assert catalog.revisions == (_REV_2015, _REV_2022)


def test_load_standards_rejects_malformed_payload() -> None:
    """분모를 모른 채 커버율을 내지 않는다 — 조용한 폴백 없이 즉시 ValueError."""
    with pytest.raises(ValueError):
        oc.load_standards([])
    with pytest.raises(ValueError):
        oc.load_standards({"items": []})
    with pytest.raises(ValueError):
        oc.load_standards({"standards": [{"norm_id": "x"}]})  # code 없음


# ──────────────────────────────────────────────────────────────────────────
# 2. 소단원 YAML 파싱 — 정상·정직 회계·파일 단위 격리
# ──────────────────────────────────────────────────────────────────────────
def test_parse_unit_yaml_normal_case() -> None:
    record = oc.parse_unit_yaml(_unit_yaml(), unit_file="quadratic_maxmin.unit.yaml")
    assert record.unit_id == "10공수1-이차함수-최대최소"
    assert record.curriculum_rev == "2022"
    assert record.standard_codes == ("[10공수1-02-06]",)
    assert len(record.objectives) == 1
    assert record.objectives[0].k_type == "CONCEPT"


def test_parse_unit_yaml_missing_unit_id_is_non_fatal() -> None:
    """unit_id 누락은 파일 전체를 버리지 않는다 — 표시용 라벨일 뿐 조인 키가 아니다."""
    text = _unit_yaml(unit_id=None)
    record = oc.parse_unit_yaml(text, unit_file="no_id.unit.yaml")
    assert record.unit_id is None
    assert record.standard_codes == ("[10공수1-02-06]",)
    assert len(record.objectives) == 1


@pytest.mark.parametrize(
    "raw_text",
    [
        "unit_id: broken\nstandard_codes: [1, 2\n",  # YAML 문법 오류(미종결 flow seq)
        "- 1\n- 2\n",  # 최상위가 object가 아니라 list
        "unit_id: x\nstandard_codes: not-a-list\n",  # standard_codes 타입 위반
        "unit_id: x\nstandard_codes: [1, 2]\n",  # 원소가 문자열 아님
        "unit_id: x\nobjectives: not-a-list\n",  # objectives 타입 위반
        "unit_id: x\nobjectives: [1, 2]\n",  # objectives 원소가 object 아님
        "unit_id: x\nobjectives:\n  - standard_code: 123\n",  # standard_code 타입 위반
    ],
)
def test_parse_unit_yaml_fatal_failures_raise(raw_text: str) -> None:
    """구조적으로 잘못된 필드는 파일 전체 파싱 실패로 처리한다(예외로 상위에 올림)."""
    with pytest.raises(Exception):  # noqa: B017 — 다양한 예외 타입(YAMLError/TypeError) 허용
        oc.parse_unit_yaml(raw_text, unit_file="broken.unit.yaml")


def test_parse_unit_yaml_missing_objective_fields_are_counted_not_dropped() -> None:
    """objective의 standard_code/k_type 누락은 파싱 실패가 아니라 객체별 None으로 남는다."""
    text = _unit_yaml(objectives=[_objective(standard_code=None, k_type=None), _objective()])
    record = oc.parse_unit_yaml(text, unit_file="gaps.unit.yaml")
    assert len(record.objectives) == 2
    assert record.objectives[0].standard_code is None
    assert record.objectives[0].k_type is None
    assert record.objectives[1].standard_code == "[10공수1-02-06]"


# ──────────────────────────────────────────────────────────────────────────
# 3. 유닛 코퍼스 적재 — 데이터없음/비어있음/적재됨 + 파일 단위 격리
# ──────────────────────────────────────────────────────────────────────────
def test_missing_and_empty_units_root_are_different_states(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-dir"
    empty = tmp_path / "empty-dir"
    empty.mkdir()

    missing_load = oc.load_units(missing)
    empty_load = oc.load_units(empty)

    assert missing_load.status == "데이터없음"
    assert empty_load.status == "비어있음"
    assert missing_load.status != empty_load.status
    assert len(missing_load.units) == len(empty_load.units) == 0


def test_load_units_isolates_parse_failures_per_file(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(root, "ok_unit", _unit_yaml())
    _write_unit(root, "broken_unit", "unit_id: x\nstandard_codes: not-a-list\n")

    load = oc.load_units(root)

    assert load.status == "적재됨"
    assert len(load.units) == 1
    assert load.units[0].unit_id == "10공수1-이차함수-최대최소"
    assert len(load.parse_errors) == 1
    assert load.parse_errors[0].unit_file == "broken_unit.unit.yaml"
    assert load.parse_errors[0].error_type == "TypeError"


def test_discover_unit_files_sorted_and_globs_only_unit_yaml(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(root, "b_unit", _unit_yaml())
    _write_unit(root, "a_unit", _unit_yaml())
    (root / "_provenance.json").write_text("{}", encoding="utf-8")  # 매치되면 안 됨

    files = oc.discover_unit_files(root)

    assert [p.name for p in files] == ["a_unit.unit.yaml", "b_unit.unit.yaml"]


# ──────────────────────────────────────────────────────────────────────────
# 4. 집계 정확성 — 커버율·개정/학교급/영역 분포·정직 회계
# ──────────────────────────────────────────────────────────────────────────
def _catalog_5() -> oc.StandardsCatalog:
    return oc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-06]", _REV_2022, domain="방정식과 부등식"),
                _standard("[10공수1-02-06]", _REV_2015, domain="방정식과 부등식"),  # 중복 코드
                _standard("[12대수03-02]", _REV_2022, domain="대수", school_type="고등학교"),
                _standard("[2수01-01]", _REV_2015, domain="수와 연산", school_type="초등학교"),
                _standard("[9수01-01]", _REV_2022, domain="수와 연산", school_type="중학교"),
            ]
        }
    )


def test_coverage_counts_record_based_denominator(tmp_path: Path) -> None:
    """분모는 레코드 전량(5) — `[10공수1-02-06]`은 두 개정에 중복 등재돼 커버 레코드 2건."""
    root = tmp_path / "units_v1"
    _write_unit(root, "u1", _unit_yaml(standard_codes=["[10공수1-02-06]"]))
    catalog = _catalog_5()
    report = oc.build_report(oc.load_units(root), catalog)

    assert report.standards_record_count == 5
    assert report.covered_record_count == 2  # 2022·2015 두 레코드 모두 커버
    assert report.covered_codes == ("[10공수1-02-06]",)
    assert report.coverage_rate == pytest.approx(2 / 5)
    assert len(report.zero_coverage_codes) == 3  # 고유 코드 4개 중 1개만 커버


def test_coverage_by_revision_school_type_and_domain(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(root, "u1", _unit_yaml(standard_codes=["[10공수1-02-06]"]))
    catalog = _catalog_5()
    report = oc.build_report(oc.load_units(root), catalog)

    assert report.coverage_by_revision == {_REV_2022: (1, 3), _REV_2015: (1, 2)}
    # 고등학교 3레코드 중 2개가 `[10공수1-02-06]`(2022·2015 중복 등재 모두 고등학교) — 코드
    # 일치는 개정을 가리지 않으므로 두 레코드 모두 커버로 잡힌다(모듈 docstring "커버리지 정의").
    assert report.coverage_by_school_type["고등학교"] == (2, 3)
    assert report.coverage_by_school_type["초등학교"] == (0, 1)
    assert report.coverage_by_domain["방정식과 부등식"] == (2, 2)
    assert report.coverage_by_domain["수와 연산"] == (0, 2)


def test_unknown_standard_codes_counted_separately(tmp_path: Path) -> None:
    """unit이 인용했으나 대장에 없는 코드(오타·구버전)는 조용히 버리지 않고 별도 카운트."""
    root = tmp_path / "units_v1"
    _write_unit(
        root,
        "u1",
        _unit_yaml(standard_codes=["[10공수1-02-06]", "[99없음-01-01]"]),
    )
    catalog = _catalog_5()
    report = oc.build_report(oc.load_units(root), catalog)

    assert report.unknown_standard_codes == {"[99없음-01-01]": 1}
    assert report.covered_codes == ("[10공수1-02-06]",)  # 미지 코드는 covered에 안 섞임


def test_k_type_totals_and_per_unit_breakdown(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(
        root,
        "u1",
        _unit_yaml(
            objectives=[
                _objective(k_type="CONCEPT"),
                _objective(k_type="PROCEDURE"),
            ]
        ),
    )
    _write_unit(root, "u2", _unit_yaml(objectives=[_objective(k_type="CONCEPT")]))
    catalog = _catalog_5()
    report = oc.build_report(oc.load_units(root), catalog)

    assert report.k_type_totals == {"CONCEPT": 2, "PROCEDURE": 1}
    assert report.objectives_total == 3
    assert report.per_unit_k_type["u1.unit.yaml"] == {"CONCEPT": 1, "PROCEDURE": 1}
    assert report.per_unit_k_type["u2.unit.yaml"] == {"CONCEPT": 1}


def test_honest_accounting_fields(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(
        root,
        "gaps",
        _unit_yaml(
            unit_id=None,
            standard_codes=[],
            objectives=[
                _objective(standard_code=None, k_type=None),
                _objective(standard_code="[안-닮음-코드]", k_type="PROCEDURE"),  # unit 목록 밖 코드
            ],
        ),
    )
    catalog = _catalog_5()
    report = oc.build_report(oc.load_units(root), catalog)

    assert report.units_missing_unit_id == 1
    assert report.units_without_standard_codes == 1
    assert report.objectives_without_standard_code == 1
    assert report.objectives_without_k_type == 1
    assert report.objective_code_outside_unit_list == 1


# ──────────────────────────────────────────────────────────────────────────
# 5. acceptance ④ — 변별력: 소단원 추가 시 커버리지 %가 실제로 움직인다
# ──────────────────────────────────────────────────────────────────────────
def test_acceptance4_coverage_moves_when_unit_added(tmp_path: Path) -> None:
    """0건 → 1건 → 2건 소단원 반입에 커버율이 단조 증가하는지 직접 확인한다.

    **실제 저장소 코퍼스(`data/corpus/units_v1/`)에는 손대지 않는다** — 합성 표준·합성 유닛
    (tmp_path)만 사용한다(커리큘럼 저작은 이 태스크 범위 밖).
    """
    catalog = oc.load_standards(
        {
            "standards": [
                _standard("[A-01]", domain="A영역"),
                _standard("[A-02]", domain="A영역"),
                _standard("[B-01]", domain="B영역"),
                _standard("[B-02]", domain="B영역"),
                _standard("[C-01]", domain="C영역"),
            ]
        }
    )

    zero_units_root = tmp_path / "units_zero"
    zero_units_root.mkdir()
    report_zero = oc.build_report(oc.load_units(zero_units_root), catalog)

    one_unit_root = tmp_path / "units_one"
    _write_unit(one_unit_root, "unit1", _unit_yaml(standard_codes=["[A-01]", "[A-02]"]))
    report_one = oc.build_report(oc.load_units(one_unit_root), catalog)

    two_unit_root = tmp_path / "units_two"
    _write_unit(two_unit_root, "unit1", _unit_yaml(standard_codes=["[A-01]", "[A-02]"]))
    _write_unit(two_unit_root, "unit2", _unit_yaml(standard_codes=["[B-01]"]))
    report_two = oc.build_report(oc.load_units(two_unit_root), catalog)

    assert report_zero.covered_record_count == 0
    assert report_zero.coverage_rate == pytest.approx(0.0)

    assert report_one.covered_record_count == 2
    assert report_one.coverage_rate == pytest.approx(2 / 5)

    assert report_two.covered_record_count == 3
    assert report_two.coverage_rate == pytest.approx(3 / 5)

    # 단조 증가 — 커버리지 %가 실제로 움직인다(변별력).
    assert report_zero.coverage_rate < report_one.coverage_rate < report_two.coverage_rate

    # 렌더된 마크다운 수치도 같이 움직이는지(내부 계산뿐 아니라 표시까지) 확인.
    assert "커버된 레코드: **0** (0.00%)" in oc.render_report(report_zero)
    assert "커버된 레코드: **2** (40.00%)" in oc.render_report(report_one)
    assert "커버된 레코드: **3** (60.00%)" in oc.render_report(report_two)


# ──────────────────────────────────────────────────────────────────────────
# 6. 결정론 — 같은 입력 → 같은 바이트, 삽입 순서 무의존
# ──────────────────────────────────────────────────────────────────────────
def test_render_and_json_are_byte_identical_across_runs(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(root, "u1", _unit_yaml())
    catalog = _catalog_5()
    first = oc.build_report(oc.load_units(root), catalog)
    second = oc.build_report(oc.load_units(root), catalog)
    assert oc.render_report(first) == oc.render_report(second)
    assert oc.dump_json(first) == oc.dump_json(second)


def test_output_independent_of_standards_insertion_order(tmp_path: Path) -> None:
    root = tmp_path / "units_v1"
    _write_unit(root, "u1", _unit_yaml(standard_codes=["[10공수1-02-06]"]))
    units_load = oc.load_units(root)

    forward = oc.load_standards(
        {
            "standards": [
                _standard("[10공수1-02-06]", _REV_2022),
                _standard("[12대수03-02]", _REV_2022),
            ]
        }
    )
    reversed_catalog = oc.load_standards(
        {
            "standards": [
                _standard("[12대수03-02]", _REV_2022),
                _standard("[10공수1-02-06]", _REV_2022),
            ]
        }
    )
    report_forward = oc.build_report(units_load, forward)
    report_reversed = oc.build_report(units_load, reversed_catalog)

    assert report_forward.covered_codes == report_reversed.covered_codes
    assert report_forward.coverage_by_domain == report_reversed.coverage_by_domain
    assert oc.render_report(report_forward) == oc.render_report(report_reversed)


def test_covered_list_truncation_is_announced(tmp_path: Path) -> None:
    """커버된 목록을 잘랐으면 잘렸다고 쓴다(조용한 절단 금지)."""
    root = tmp_path / "units_v1"
    _write_unit(root, "u1", _unit_yaml(standard_codes=["[A-01]", "[A-02]", "[A-03]"]))
    catalog = oc.load_standards(
        {
            "standards": [
                _standard("[A-01]"),
                _standard("[A-02]"),
                _standard("[A-03]"),
            ]
        }
    )
    report = oc.build_report(oc.load_units(root), catalog)
    text = oc.render_report(report, max_covered_display=1)
    assert "…외 **2**건" in text
    assert "`[A-01]`" in text
    assert "`[A-02]`" not in text
    payload = json.loads(oc.dump_json(report))
    assert payload["covered_codes"] == ["[A-01]", "[A-02]", "[A-03]"]


# ──────────────────────────────────────────────────────────────────────────
# 7. CLI — exit 0/2만(게이트 아님)
# ──────────────────────────────────────────────────────────────────────────
def test_cli_exit_zero_when_units_root_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """소단원 코퍼스가 아예 없어도(현재 저장소 상태 포함) exit 0 — 관측 리포트라 게이트가 아니다."""
    standards = _write_standards(tmp_path / "standards.json", [_standard("[10공수1-02-06]")])
    rc = oc.main(
        [
            "--standards",
            str(standards),
            "--units-root",
            str(tmp_path / "no-such-units-dir"),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "상태 **데이터없음**" in out
    assert "커버된 레코드: **0** (0.00%)" in out


def test_cli_exit_zero_with_unit_parse_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """유닛 파일 파싱 실패는 리포트 카운트로 실리고 종료 코드를 바꾸지 않는다."""
    standards = _write_standards(tmp_path / "standards.json", [_standard("[10공수1-02-06]")])
    units_root = tmp_path / "units"
    _write_unit(units_root, "broken", "unit_id: x\nstandard_codes: not-a-list\n")
    rc = oc.main(["--standards", str(standards), "--units-root", str(units_root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "| 유닛 파일 파싱 실패 | 1 |" in out
    assert "TypeError" in out


def test_cli_exit_two_on_missing_standards(tmp_path: Path) -> None:
    rc = oc.main(
        [
            "--standards",
            str(tmp_path / "nope.json"),
            "--units-root",
            str(tmp_path / "units"),
        ]
    )
    assert rc == oc._EXIT_INPUT_ERROR


def test_cli_exit_two_on_malformed_standards(tmp_path: Path) -> None:
    bad = tmp_path / "standards.json"
    bad.write_text(json.dumps({"nope": []}), encoding="utf-8")
    rc = oc.main(["--standards", str(bad), "--units-root", str(tmp_path / "units")])
    assert rc == oc._EXIT_INPUT_ERROR


def test_cli_json_artifact_is_deterministic(tmp_path: Path) -> None:
    standards = _write_standards(
        tmp_path / "standards.json", [_standard("[10공수1-02-06]"), _standard("[12대수03-02]")]
    )
    units_root = tmp_path / "units"
    _write_unit(units_root, "u1", _unit_yaml(standard_codes=["[10공수1-02-06]"]))
    out_a = tmp_path / "out" / "a.json"
    out_b = tmp_path / "out" / "b.json"
    for target in (out_a, out_b):
        rc = oc.main(
            [
                "--standards",
                str(standards),
                "--units-root",
                str(units_root),
                "--json",
                str(target),
            ]
        )
        assert rc == 0
    assert out_a.read_bytes() == out_b.read_bytes()
    payload = json.loads(out_a.read_text(encoding="utf-8"))
    assert payload["standards"]["record_count"] == 2
    assert payload["standards"]["covered_record_count"] == 1
    assert payload["standards"]["coverage_rate"] == pytest.approx(0.5)


# ──────────────────────────────────────────────────────────────────────────
# 8. acceptance ① — 실제 저장소 코퍼스 대상 현행 실측 재현(895건 중 11건·1.23% — 2026-10-07 P3-03)
# ──────────────────────────────────────────────────────────────────────────
# tests/backend/harness/test_x.py → parents[3] = repo 루트(harness→backend→tests→root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REAL_STANDARDS_PATH = _REPO_ROOT / "data" / "corpus" / "standards_v1" / "standards.json"
_REAL_UNITS_ROOT = _REPO_ROOT / "data" / "corpus" / "units_v1"


class TestAcceptance1RealCorpusBaseline:
    """CUR-02 acceptance① — 실제 저장소 코퍼스의 목표 커버리지 실측을 재현·동결한다.

    이 값이 바뀌면(신규 소단원 반입 등) 이 테스트가 깨진다 — 그것은 회귀가 아니라 *의도된
    진전*이므로, 그 경우 이 골든값을 갱신하는 것이 맞다(problem_bank_coverage의 골든 분포
    테스트와 동일 관례).

    골든값 이력:
      - CUR-02 착수 시점: 895건 중 1건(0.11%) — 이차함수 파일럿 1편·4목표.
      - 2026-10-07 P3-03: 미적분Ⅰ '미분' 대단원 초안 10편(`calc1_diff_01…10`)·30목표 반입으로
        895건 중 11건(1.23%)·11편·34목표. 의도된 데이터 진전이다(docs/data/units_v1.md §3).
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def report() -> oc.CoverageReport:
        payload = json.loads(_REAL_STANDARDS_PATH.read_text(encoding="utf-8"))
        catalog = oc.load_standards(payload)
        units_load = oc.load_units(_REAL_UNITS_ROOT)
        return oc.build_report(units_load, catalog)

    def test_standards_record_total_is_895(self, report: oc.CoverageReport) -> None:
        assert report.standards_record_count == 895

    def test_covered_record_count_is_exactly_11(self, report: oc.CoverageReport) -> None:
        # 2026-10-07 P3-03: 파일럿 [10공수1-02-06] + 미적분Ⅰ 미분 10건(1 → 11, 의도된 진전).
        assert report.covered_record_count == 11
        assert report.covered_codes == (
            "[10공수1-02-06]",
            "[12미적Ⅰ-02-01]",
            "[12미적Ⅰ-02-02]",
            "[12미적Ⅰ-02-03]",
            "[12미적Ⅰ-02-04]",
            "[12미적Ⅰ-02-05]",
            "[12미적Ⅰ-02-06]",
            "[12미적Ⅰ-02-07]",
            "[12미적Ⅰ-02-08]",
            "[12미적Ⅰ-02-09]",
            "[12미적Ⅰ-02-10]",
        )

    def test_coverage_rate_is_1_23_percent(self, report: oc.CoverageReport) -> None:
        # 2026-10-07 P3-03: 1/895(0.11%) → 11/895(1.23%).
        assert report.coverage_rate == pytest.approx(11 / 895)
        assert f"{report.coverage_rate * 100:.2f}%" == "1.23%"

    def test_eleven_unit_files_with_thirty_four_objectives(self, report: oc.CoverageReport) -> None:
        # 2026-10-07 P3-03: 파일럿 1편·4목표 + 미적분Ⅰ 미분 10편·30목표(02-08만 2목표, 02-10은 4목표).
        assert len(report.units) == 11
        assert report.objectives_total == 34

    def test_k_type_distribution_pilot_plus_calculus_draft(self, report: oc.CoverageReport) -> None:
        # 2026-10-07 P3-03: 파일럿 1·1·1·1 + 미적분Ⅰ 9·10·10·1(02-08은 CONCEPT 없음 — 원자 02-08-2
        # 제외, MODELING은 02-10의 '유용성 인식' 목표 1개뿐).
        assert report.k_type_totals == {
            "CONCEPT": 10,
            "PROCEDURE": 11,
            "REPRESENT": 11,
            "MODELING": 2,
        }

    def test_no_silent_data_quality_issues(self, report: oc.CoverageReport) -> None:
        """현재 파일럿 데이터는 정직 회계 축에서 전부 깨끗해야 한다(0)."""
        assert len(report.unit_parse_errors) == 0
        assert report.unknown_standard_codes == {}
        assert report.units_missing_unit_id == 0
        assert report.units_without_standard_codes == 0
        assert report.objectives_without_standard_code == 0
        assert report.objectives_without_k_type == 0
        assert report.objective_code_outside_unit_list == 0

    def test_cli_reproduces_the_same_baseline(self, capsys: pytest.CaptureFixture[str]) -> None:
        """CLI(기본 경로 자가탐지)로도 같은 수치가 재현되는지 — 코어 함수 우회 경로도 검증."""
        rc = oc.main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "레코드 **895**" in out
        # 2026-10-07 P3-03: 1건(0.11%) → 11건(1.23%) — 위 골든값 이력과 같은 사유.
        assert "커버된 레코드: **11** (1.23%)" in out
