"""공식 지식 자산 도달 관측 리포트 테스트 — 결정론·정직 표기·변별력 동결(hermetic).

대상: `whymath_backend.harness.formula_reach_report`(KG-03 acceptance①·③~⑤). 실 DB·LLM·
네트워크 0 — `tmp_path`에 가짜 backend/api/mobile 트리·코퍼스를 만들어 검증한다. 실 코퍼스
대상 스모크 테스트 1건만 실제 저장소 경로를 읽는다(회귀 anchor).

**집행 지점(acceptance②)**: 이 파일이 리포트 '미도달' 판정의 정본 소비처다 — CI backend 잡
(`.github/workflows/ci.yml` "Pytest (with coverage)", working-directory src/backend)이
`src/backend/pyproject.toml`의 `testpaths = ["../../tests/backend"]`로 이 디렉터리를 수집한다.

**변별력**(CLAUDE.md "변별력 없는 검증 스텝 금지" — acceptance④ 그대로):
  - 표면별 소비 참조를 주입하면 그 표면만 '도달'로 바뀌고, 제거하면 다시 '미도달'로
    돌아온다(양방향 — 성공/실패가 같은 값을 내면 검증이 아니라 위장이다).
  - 주석·docstring 라인의 참조는 계수되지 않는다(태스크 b — "주석 제외" 자체를 동결).
  - 심볼 스캔 제외 경로(자기 모듈·배럴·관측기 자신)의 참조도 계수되지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import formula_reach_report as frr

# 코퍼스 건수는 손으로 박지 않고 단일 원천의 기계용 사본에서 읽는다(OPS-154).
# 원본이 바뀌면 `python3 scripts/analysis/corpus_facts.py sync`가 이 파일을 갱신한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FACTS = json.loads(
    (_REPO_ROOT / "docs" / "data" / "corpus_facts.json").read_text(encoding="utf-8")
)

# ──────────────────────────────────────────────────────────────────────────
# 가짜 트리 헬퍼 — hermetic 베이스라인(전 표면 미도달·최소 코퍼스)
# ──────────────────────────────────────────────────────────────────────────
_MINIMAL_CORPUS_ROWS = [
    {"formula_id": "formula.t.a", "constraints": ["a>0"], "mnemonic": "암기법"},
    {"formula_id": "formula.t.b", "constraints": [], "mnemonic": None},
]


def _make_roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """가짜 backend 패키지/api/mobile 루트 + 최소 코퍼스(2행) 생성."""
    pkg_root = tmp_path / "whymath_backend"
    api_root = pkg_root / "api"
    mobile_root = tmp_path / "mobile_lib"
    api_root.mkdir(parents=True)
    mobile_root.mkdir()
    corpus_path = tmp_path / "formulas.jsonl"
    _write_corpus(corpus_path, _MINIMAL_CORPUS_ROWS)
    return pkg_root, api_root, mobile_root, corpus_path


def _write_corpus(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def _build(pkg: Path, api: Path, mobile: Path, corpus: Path) -> frr.FormulaReachReport:
    return frr.build_report(
        backend_pkg_root=pkg, backend_api_root=api, mobile_root=mobile, corpus_path=corpus
    )


def _surface(report: frr.FormulaReachReport, key: str) -> frr.SurfaceReach:
    return next(s for s in report.surfaces if s.key == key)


# ──────────────────────────────────────────────────────────────────────────
# 1. 로더 — 정상·정직 실패
# ──────────────────────────────────────────────────────────────────────────
def test_load_scan_root_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        frr.load_scan_root(tmp_path / "없음", label="x")


def test_load_scan_root_rejects_non_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "파일.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        frr.load_scan_root(file_path, label="x")


def test_load_corpus_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        frr.load_corpus(tmp_path / "없음.jsonl")


def test_load_corpus_rejects_broken_json_line(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text('{"formula_id": "a"}\n{깨진 json\n', encoding="utf-8")
    with pytest.raises(ValueError):
        frr.load_corpus(path)


def test_load_corpus_rejects_non_object_row(tmp_path: Path) -> None:
    path = tmp_path / "scalar.jsonl"
    path.write_text('["배열은", "오브젝트가 아님"]\n', encoding="utf-8")
    with pytest.raises(ValueError):
        frr.load_corpus(path)


def test_load_corpus_accepts_rows_and_skips_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "ok.jsonl"
    path.write_text('{"formula_id": "a"}\n\n{"formula_id": "b"}\n', encoding="utf-8")
    rows = frr.load_corpus(path)
    assert len(rows) == 2


# ──────────────────────────────────────────────────────────────────────────
# 2. 집계 — hermetic 0건 베이스라인 + 저작/도달 축 분리(acceptance③)
# ──────────────────────────────────────────────────────────────────────────
def test_build_report_all_unreached_on_empty_roots(tmp_path: Path) -> None:
    report = _build(*_make_roots(tmp_path))

    assert len(report.surfaces) == 3
    assert report.unreached_count == 3
    assert all(s.status == "미도달" for s in report.surfaces)
    assert all(s.reach_count == 0 for s in report.surfaces)
    assert all(s.matched_sites == () for s in report.surfaces)


def test_corpus_fill_is_separate_axis_from_reach(tmp_path: Path) -> None:
    """저작(충전)과 도달(소비)은 별개 필드다 — 충전이 있어도 표면 status에 영향 0."""
    report = _build(*_make_roots(tmp_path))

    fill = report.corpus_fill
    assert fill.total_formulas == 2
    by_field = {f.field: f for f in fill.fields}
    # constraints: 1행 충전([a>0])·1행 빈 리스트 → filled=1, 키는 2행 모두 존재
    assert by_field["constraints"].filled == 1
    assert by_field["constraints"].total == 2
    assert by_field["constraints"].keys_present == 2
    # mnemonic: null은 미충전
    assert by_field["mnemonic"].filled == 1
    # canonical_signature: 키 자체 부재 — '키 없음(0)'과 'null 충전'을 구분해 낸다
    assert by_field["canonical_signature"].filled == 0
    assert by_field["canonical_signature"].keys_present == 0
    # 충전이 존재해도 도달 표면은 전부 미도달 그대로(축 분리)
    assert report.unreached_count == 3


def test_build_report_rejects_missing_root(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    with pytest.raises(ValueError):
        frr.build_report(
            backend_pkg_root=tmp_path / "없음",
            backend_api_root=api,
            mobile_root=mobile,
            corpus_path=corpus,
        )


def test_build_report_rejects_missing_corpus(tmp_path: Path) -> None:
    pkg, api, mobile, _corpus = _make_roots(tmp_path)
    with pytest.raises(ValueError):
        frr.build_report(
            backend_pkg_root=pkg,
            backend_api_root=api,
            mobile_root=mobile,
            corpus_path=tmp_path / "없음.jsonl",
        )


# ──────────────────────────────────────────────────────────────────────────
# 3. 변별력(mutation) — 양방향, acceptance④ 핵심
# ──────────────────────────────────────────────────────────────────────────
def test_mobile_surface_mutation_round_trips(tmp_path: Path) -> None:
    """(d) mobile — formula 경로 리터럴 주입→도달, 제거→미도달(양방향)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    fake_dart = mobile / "fake_caller.dart"

    baseline = _surface(_build(pkg, api, mobile, corpus), "mobile_formula_refs")
    assert baseline.status == "미도달"

    fake_dart.write_text("final res = _dio.get('/v1/formulas/search');", encoding="utf-8")
    mutated = _build(pkg, api, mobile, corpus)
    mutated_mobile = _surface(mutated, "mobile_formula_refs")
    assert mutated_mobile.status == "도달"
    assert mutated_mobile.reach_count == 1
    assert mutated_mobile.matched_sites == ("fake_caller.dart:1",)
    # 다른 표면은 오염되지 않는다(오탐 방지 확인)
    assert _surface(mutated, "api_formula_seat").status == "미도달"
    assert _surface(mutated, "formula_symbol_refs").status == "미도달"

    fake_dart.unlink()
    restored = _surface(_build(pkg, api, mobile, corpus), "mobile_formula_refs")
    assert restored.status == "미도달"
    assert restored.reach_count == baseline.reach_count == 0


def test_mobile_surface_ignores_ocr_domain_formula_terms(tmp_path: Path) -> None:
    """OCR '수식(formula)' 도메인 용어는 공식 그래프 소비가 아니다 — 오탐 6건 실측(2026-08-11)
    재발 방지: bare 토큰이 아니라 /v1/ 경로·formula_id 심볼만 잡는다."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    (mobile / "ocr_models.dart").write_text(
        "bool get isFormula => contentType == ocrContentTypeFormula;\n"
        "const String ocrContentTypeFormula = '수식';\n"
        "enum DefectType { formulaError }\n",
        encoding="utf-8",
    )
    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "mobile_formula_refs").status == "미도달"


def test_api_seat_surface_mutation_round_trips(tmp_path: Path) -> None:
    """(a) api 좌석 — api/ 내 formula 참조 주입→도달, 제거→미도달(양방향)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    fake_py = api / "formulas.py"

    assert _surface(_build(pkg, api, mobile, corpus), "api_formula_seat").status == "미도달"

    fake_py.write_text("def list_formulas():\n    return store.load_formula_nodes()\n", "utf-8")
    mutated = _build(pkg, api, mobile, corpus)
    mutated_api = _surface(mutated, "api_formula_seat")
    assert mutated_api.status == "도달"
    assert mutated_api.reach_count == 2  # 함수명·호출 각 1라인 매치

    fake_py.unlink()
    assert _surface(_build(pkg, api, mobile, corpus), "api_formula_seat").status == "미도달"


def test_symbol_surface_mutation_round_trips(tmp_path: Path) -> None:
    """(b) 심볼 — 자기 모듈 밖 FormulaNode/formula_id 사용 주입→도달, 제거→미도달(양방향)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    fake_py = pkg / "l4" / "uses_formula.py"
    fake_py.parent.mkdir(parents=True)

    assert _surface(_build(pkg, api, mobile, corpus), "formula_symbol_refs").status == "미도달"

    fake_py.write_text(
        "node = FormulaNode(formula_id='formula.t.a')\n",
        encoding="utf-8",
    )
    mutated = _surface(_build(pkg, api, mobile, corpus), "formula_symbol_refs")
    assert mutated.status == "도달"
    assert mutated.reach_count == 2  # 같은 라인의 FormulaNode·formula_id 각 1매치
    assert mutated.matched_sites == ("l4/uses_formula.py:1", "l4/uses_formula.py:1")

    fake_py.unlink()
    assert _surface(_build(pkg, api, mobile, corpus), "formula_symbol_refs").status == "미도달"


def test_symbol_surface_excludes_comment_and_docstring_lines(tmp_path: Path) -> None:
    """(b) 주석·docstring 라인의 formula_id·FormulaNode는 계수되지 않는다(태스크 b 명시).

    현행 실트리의 유일 참조가 `db/models/__init__.py` 주석이었던 상태를 그대로 동결한다."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    (pkg / "commented.py").write_text(
        '"""모듈 docstring — FormulaNode 프로젝션을 설명만 한다."""\n'
        "# formula_id 키 주석 — 사용 아님\n"
        "x = 1  # 코드 라인(참조 없음)\n"
        "'''\nformula_id 블록 문자열 내부\nFormulaNode\n'''\n",
        encoding="utf-8",
    )
    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "formula_symbol_refs").status == "미도달"
    assert _surface(report, "formula_symbol_refs").reach_count == 0


def test_symbol_surface_word_boundary_excludes_formula_node_store(tmp_path: Path) -> None:
    """(b) `FormulaNodeStore` 같은 파생 식별자는 단어 경계로 배제된다(strategy_graph 실사례)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    (pkg / "store_pair.py").write_text(
        "class StrategyNodeStore(FormulaNodeStore):\n    pass\n", encoding="utf-8"
    )
    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "formula_symbol_refs").reach_count == 0


def test_symbol_surface_excludes_self_module_barrel_and_observer(tmp_path: Path) -> None:
    """(b) 제외 경로 4종(자기 모듈 2·배럴·관측기 자신)의 참조는 계수되지 않고, 제외 목록은
    리포트 필드로 그대로 노출된다(숨기지 않는다)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    fg = pkg / "l1" / "formula_graph"
    fg.mkdir(parents=True)
    (fg / "populate.py").write_text("row['formula_id'] = fid\n", encoding="utf-8")
    models = pkg / "db" / "models"
    models.mkdir(parents=True)
    (models / "formula_node.py").write_text("class FormulaNode:\n    pass\n", encoding="utf-8")
    (models / "__init__.py").write_text(
        "from .formula_node import FormulaNode\n__all__ = ['FormulaNode']\n", encoding="utf-8"
    )
    harness_dir = pkg / "harness"
    harness_dir.mkdir()
    (harness_dir / "formula_reach_report.py").write_text(
        "PATTERN = r'formula_id|FormulaNode'\n", encoding="utf-8"
    )

    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "formula_symbol_refs").status == "미도달"
    assert report.symbol_scan_exclusions == frr.SYMBOL_SCAN_EXCLUSIONS
    excluded_paths = {path for path, _reason in report.symbol_scan_exclusions}
    assert "db/models/__init__.py" in excluded_paths
    assert "harness/formula_reach_report.py" in excluded_paths


def test_test_directory_excluded_from_scan(tmp_path: Path) -> None:
    """`test`/`tests` 이름의 하위 디렉터리는 스캔에서 제외된다(KG-01 '20 vs 13' 가드 답습)."""
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    test_dir = mobile / "test"
    test_dir.mkdir()
    (test_dir / "mock.dart").write_text("_dio.get('/v1/formulas');", encoding="utf-8")

    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "mobile_formula_refs").status == "미도달"


# ──────────────────────────────────────────────────────────────────────────
# 4. 렌더/JSON — 결정론·정직 표기
# ──────────────────────────────────────────────────────────────────────────
def test_render_report_is_deterministic(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    r1 = frr.render_report(_build(pkg, api, mobile, corpus))
    r2 = frr.render_report(_build(pkg, api, mobile, corpus))
    assert r1 == r2
    assert "미도달 표면: **3/3**" in r1
    assert "저작(충전) 축 — 도달과 별개" in r1
    assert "심볼 스캔 제외 목록" in r1


def test_render_report_truncates_sites_and_notes_remainder(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    for i in range(5):
        (mobile / f"f{i}.dart").write_text(f"_dio.get('/v1/formulas/{i}');", encoding="utf-8")
    report = _build(pkg, api, mobile, corpus)
    assert _surface(report, "mobile_formula_refs").reach_count == 5
    rendered = frr.render_report(report, max_listed=2)
    assert "…외 **3**건" in rendered


def test_report_to_json_round_trips(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    (mobile / "f.dart").write_text("_dio.get('/v1/formulas');", encoding="utf-8")
    report = _build(pkg, api, mobile, corpus)

    payload = frr.report_to_json(report)
    assert payload["unreached_count"] == 2
    assert payload["corpus_fill"]["total_formulas"] == 2
    assert {f["field"] for f in payload["corpus_fill"]["fields"]} == set(frr.FILL_FIELDS)
    assert payload["symbol_scan_exclusions"][0]["path"] == "l1/formula_graph"

    dumped = frr.dump_json(report)
    assert json.loads(dumped) == payload


# ──────────────────────────────────────────────────────────────────────────
# 5. CLI — exit 코드 규율(게이트 아님·입력 오류만 2, acceptance⑥)
# ──────────────────────────────────────────────────────────────────────────
def _cli_args(pkg: Path, api: Path, mobile: Path, corpus: Path) -> list[str]:
    return [
        "--backend-pkg-root",
        str(pkg),
        "--backend-api-root",
        str(api),
        "--mobile-root",
        str(mobile),
        "--corpus",
        str(corpus),
    ]


def test_main_exit_0_even_when_all_surfaces_unreached(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    assert frr.main(_cli_args(pkg, api, mobile, corpus)) == 0


def test_main_exit_2_on_missing_mobile_root(tmp_path: Path) -> None:
    pkg, api, _mobile, corpus = _make_roots(tmp_path)
    assert frr.main(_cli_args(pkg, api, tmp_path / "없음", corpus)) == 2


def test_main_exit_2_on_missing_corpus(tmp_path: Path) -> None:
    pkg, api, mobile, _corpus = _make_roots(tmp_path)
    assert frr.main(_cli_args(pkg, api, mobile, tmp_path / "없음.jsonl")) == 2


def test_main_writes_json_artifact(tmp_path: Path) -> None:
    pkg, api, mobile, corpus = _make_roots(tmp_path)
    out_path = tmp_path / "out" / "report.json"

    exit_code = frr.main([*_cli_args(pkg, api, mobile, corpus), "--json", str(out_path)])
    assert exit_code == 0
    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["unreached_count"] == 3
    assert len(payload["surfaces"]) == 3


# ──────────────────────────────────────────────────────────────────────────
# 6. 실 코퍼스 스모크(회귀 anchor — acceptance⑤)
# ──────────────────────────────────────────────────────────────────────────
def test_real_corpus_smoke_all_surfaces_unreached_and_fill_counts() -> None:
    """실제 저장소(src/backend/whymath_backend·src/mobile/lib·data/corpus)를 읽어 확인한다.

    현행 기대값(2026-08-11 실측): 공식 25·constraints 15/25·mnemonic 14/25·
    canonical_signature 0/25(키 자체 부재)·도달 표면 3종 전부 미도달. 값은 매 실행 코퍼스와
    소스 트리에서 재실측되며(하드코딩 아님), 값이 바뀌면 — 공식 API가 신설되거나 클라가
    소비를 시작하거나 코퍼스가 자라면 — 이 테스트가 깨져 "가시화 리포트가 낡았다"를 자동으로
    신호한다(회귀 anchor이지 임의 임계값이 아니다 — KG-01 스모크와 동형)."""
    if not (
        frr.DEFAULT_BACKEND_PKG_ROOT.is_dir()
        and frr.DEFAULT_MOBILE_LIB_ROOT.is_dir()
        and frr.DEFAULT_CORPUS_PATH.is_file()
    ):
        pytest.skip("실 backend/mobile/코퍼스 경로 미존재")

    report = frr.build_report()
    assert len(report.surfaces) == 3
    assert report.unreached_count == 3
    assert all(s.status == "미도달" for s in report.surfaces)
    assert all(s.reach_count == 0 for s in report.surfaces)

    fill = report.corpus_fill
    assert fill.total_formulas == _FACTS["formula_graph.formulas"]
    by_field = {f.field: f for f in fill.fields}
    assert by_field["constraints"].filled == 15
    assert by_field["mnemonic"].filled == 14
    assert by_field["canonical_signature"].filled == 0
    assert by_field["canonical_signature"].keys_present == 0

    assert isinstance(frr.render_report(report), str)
    assert isinstance(frr.dump_json(report), str)
