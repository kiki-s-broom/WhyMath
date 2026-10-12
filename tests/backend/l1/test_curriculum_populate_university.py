"""대학 원자 KR 셀 적재 배선 *단위테스트* — `curriculum.populate` CLI (S4-64 · hermetic·PG 불요).

S4-62가 `load_kr_curriculum_entries_for_university_atoms`를 추가했지만 호출처가 0건이라 대학 셀이
`curriculum_entry`에 영원히 들어가지 않는 상태였다(함수만 있고 배선이 없었다). 이 파일은 그 배선과
대학 `required_depth` 정책(Kiki 결정 2026-10-09: 고정 mastery 폐기 → 원자별 `cognitive_type` 도출)을
못 박는다:

  ① 배선 — src에 로더 호출처가 1건 이상 있고 그것이 `populate.py`다(소스 AST 스캔·스캔 0건은 실패)
  ② CLI 실행 — 실 코퍼스로 `main()`을 돌려 대학 셀이 upsert 입력에 실제로 실리는지(PG는 가짜로
     대체해 *넘겨진 목록*을 관찰한다) · 보고 줄에 대학 건수가 canonical·원자와 별도로 찍히는지
  ③ 부분 적재 방지 — 입력 파일이 하나라도 없으면 return 2이고 upsert는 0회 호출된다
  ④ 정책 — cognitive_type 절차→procedural·개념→conceptual·표상/미지/결손→None, mastery 0건, 실
     코퍼스 분포(512건 = 개념 360·절차 108·표상 44) 동결
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pytest

from whymath_backend.l1.curriculum import populate as populate_cli
from whymath_backend.l1.curriculum.curriculum_loader import (
    load_kr_curriculum_entries_for_university_atoms,
)
from whymath_backend.schema.curriculum_entry import CurriculumEntry

_ROOT = Path(__file__).resolve().parents[3]
_SRC = _ROOT / "src" / "backend" / "whymath_backend"
_LOADER_FN = "load_kr_curriculum_entries_for_university_atoms"
_REAL_GRAPH = _ROOT / "data" / "corpus" / "concept_graph_v1" / "graph.json"
_REAL_CROSSWALK = _ROOT / "data" / "corpus" / "concept_atom_crosswalk_v1" / "crosswalk.jsonl"
_REAL_ATOM_GRAPH = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_NOW = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)

# 2026-10-09 실측(atom_graph_v1): 대학 원자 1,069건 중 grade_band가 채워진 세부개념 512건의
# cognitive_type 분포. 코퍼스가 재생성돼 이 수치가 바뀌면 여기서 잡는다(날조 아닌 실측 동결).
_EXPECT_UNIVERSITY = 512
_EXPECT_BY_COGNITIVE = {"개념": 360, "절차": 108, "표상": 44}
_EXPECT_BY_DEPTH = {"conceptual": 360, "procedural": 108, None: 44}


def _write_atom_graph(tmp_path: Path, atoms: list[dict[str, object]]) -> Path:
    path = tmp_path / "atom_graph.json"
    path.write_text(json.dumps({"concepts": atoms}, ensure_ascii=False), encoding="utf-8")
    return path


def _univ_atom(code: str, cognitive_type: object, band: str = "1학년") -> dict[str, object]:
    return {
        "code": code,
        "school_level": "대학",
        "grade_band": band,
        "subject_area": "d",
        "cognitive_type": cognitive_type,
    }


# ──────────────────────────────────────────────────────────────────────────
# ① 배선 — 호출처가 src에 실재한다 (S4-62가 남긴 "호출처 0건" 공백의 동결)
# ──────────────────────────────────────────────────────────────────────────
def _call_sites(fn_name: str) -> list[Path]:
    """src 전체에서 `fn_name`을 *호출*하는 파일(정의 파일 자체의 내부 호출은 제외)."""
    sites: list[Path] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.name == "curriculum_loader.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == fn_name:
                sites.append(path)
                break
    return sites


class TestUniversityLoaderIsWired:
    def test_scan_actually_sees_source_files(self) -> None:
        """스캔 0건은 공허 통과다 — 대상 트리를 실제로 읽었는지부터 단언한다."""
        assert len(list(_SRC.rglob("*.py"))) > 500

    def test_loader_has_caller_in_populate_cli(self) -> None:
        sites = _call_sites(_LOADER_FN)
        assert (
            sites
        ), f"{_LOADER_FN} 호출처가 src에 0건 — 대학 셀이 적재되지 않는다(S4-62 공백 재발)"
        assert _SRC / "l1" / "curriculum" / "populate.py" in sites

    def test_scan_discriminates_an_uncalled_function(self) -> None:
        """스캔이 변별력을 가진다 — 존재하지 않는 호출 이름은 0건으로 나와야 한다."""
        assert _call_sites("load_kr_curriculum_entries_for_university_atoms_NOT_CALLED") == []


# ──────────────────────────────────────────────────────────────────────────
# ② CLI 실행 — 실 코퍼스로 main()을 돌려 upsert에 넘겨진 목록을 관찰한다
# ──────────────────────────────────────────────────────────────────────────
class _Spy:
    """`populate_kr_curriculum_entries` 대역 — 넘겨진 목록을 저장하고 dedup 후 건수를 반환."""

    def __init__(self) -> None:
        self.calls: list[list[CurriculumEntry]] = []

    def __call__(self, entries: Sequence[CurriculumEntry]) -> int:
        self.calls.append(list(entries))
        return len({e.entry_id for e in entries})


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    s = _Spy()
    monkeypatch.setattr(populate_cli, "populate_kr_curriculum_entries", s)
    return s


def _real_args() -> list[str]:
    return [
        "--graph",
        str(_REAL_GRAPH),
        "--crosswalk",
        str(_REAL_CROSSWALK),
        "--atom-graph",
        str(_REAL_ATOM_GRAPH),
    ]


class TestPopulateCliRealCorpus:
    def test_university_cells_reach_the_upsert_input(
        self, spy: _Spy, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = populate_cli.main(_real_args())
        assert rc == 0
        assert len(spy.calls) == 1
        loaded = spy.calls[0]
        univ = [e for e in loaded if e.introduced_grade is not None and e.introduced_grade >= 13]
        assert len(univ) == _EXPECT_UNIVERSITY
        assert {e.introduced_grade for e in univ} == {13, 14, 15, 16}
        # canonical(437) + 원자(1,311) + 대학(512) = 2,260, entry_id 충돌 0 — 덮어쓰기 오염 없음.
        entry_ids = [e.entry_id for e in loaded]
        assert len(entry_ids) == len(set(entry_ids)) == 437 + 1311 + _EXPECT_UNIVERSITY
        out = capsys.readouterr().out
        assert f"{len(entry_ids)}건" in out

    def test_report_line_counts_university_separately(
        self, spy: _Spy, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """조용한 무동작 금지 — 대학 건수가 canonical·원자와 *별도로* 보고된다."""
        assert populate_cli.main(_real_args()) == 0
        out = capsys.readouterr().out
        assert "canonical 437건" in out
        assert "원자 1311건" in out
        assert f"대학 {_EXPECT_UNIVERSITY}건" in out

    def test_default_atom_graph_path_is_the_repo_corpus(self) -> None:
        """`--atom-graph` 기본값이 실 코퍼스를 가리킨다(인자 없이 돌려도 대학 축이 선다)."""
        assert populate_cli._DEFAULT_ATOM_GRAPH == Path("data/corpus/atom_graph_v1/graph.json")
        assert (_ROOT / populate_cli._DEFAULT_ATOM_GRAPH).exists()

    def test_real_corpus_required_depth_distribution_frozen(self) -> None:
        """실 코퍼스 대학 셀의 required_depth 분포 동결 — mastery 0건·표상 건수 = None 건수."""
        entries = load_kr_curriculum_entries_for_university_atoms(_REAL_ATOM_GRAPH, now=_NOW)
        assert len(entries) == _EXPECT_UNIVERSITY
        assert dict(Counter(e.required_depth for e in entries)) == _EXPECT_BY_DEPTH
        assert not any(e.required_depth == "mastery" for e in entries)

    def test_real_corpus_cognitive_types_match_expectation(self) -> None:
        """도출 입력(cognitive_type) 자체의 분포 — 위 depth 분포가 입력에서 유도됨을 이중 확인."""
        payload = json.loads(_REAL_ATOM_GRAPH.read_text(encoding="utf-8"))
        banded = [
            a
            for a in payload["concepts"]
            if a.get("school_level") == "대학"
            and a.get("grade_band") in {"1학년", "2학년", "3학년", "4학년"}
        ]
        assert dict(Counter(a.get("cognitive_type") for a in banded)) == _EXPECT_BY_COGNITIVE


# ──────────────────────────────────────────────────────────────────────────
# ③ 부분 적재 방지 — 입력이 하나라도 없으면 return 2 · upsert 0회
# ──────────────────────────────────────────────────────────────────────────
class TestPopulateCliMissingInputs:
    def test_missing_atom_graph_returns_2_without_writing(
        self, spy: _Spy, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "no_such_atom_graph.json"
        args = ["--graph", str(_REAL_GRAPH), "--crosswalk", str(_REAL_CROSSWALK)]
        rc = populate_cli.main([*args, "--atom-graph", str(missing)])
        assert rc == 2
        assert spy.calls == []  # canonical·원자만 먼저 적재하고 끝나는 부분 적재 금지
        assert str(missing) in capsys.readouterr().out

    def test_missing_graph_still_returns_2(self, spy: _Spy, tmp_path: Path) -> None:
        rc = populate_cli.main(
            [
                "--graph",
                str(tmp_path / "x.json"),
                "--crosswalk",
                str(_REAL_CROSSWALK),
                "--atom-graph",
                str(_REAL_ATOM_GRAPH),
            ]
        )
        assert rc == 2
        assert spy.calls == []

    def test_missing_crosswalk_still_returns_2(self, spy: _Spy, tmp_path: Path) -> None:
        rc = populate_cli.main(
            [
                "--graph",
                str(_REAL_GRAPH),
                "--crosswalk",
                str(tmp_path / "x.jsonl"),
                "--atom-graph",
                str(_REAL_ATOM_GRAPH),
            ]
        )
        assert rc == 2
        assert spy.calls == []


# ──────────────────────────────────────────────────────────────────────────
# ④ 정책 — cognitive_type → required_depth (Kiki 결정 2026-10-09)
# ──────────────────────────────────────────────────────────────────────────
class TestUniversityRequiredDepthPolicy:
    @pytest.mark.parametrize(
        ("cognitive_type", "expected"),
        [
            ("절차", "procedural"),
            ("개념", "conceptual"),
            ("표상", None),  # RequiredDepth에 표상 칸이 없다 — 값을 지어내지 않는다
        ],
    )
    def test_known_cognitive_types(
        self, tmp_path: Path, cognitive_type: str, expected: str | None
    ) -> None:
        path = _write_atom_graph(tmp_path, [_univ_atom("U-1", cognitive_type)])
        (entry,) = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        assert entry.required_depth == expected

    @pytest.mark.parametrize("cognitive_type", [None, "", "암기", "mastery", 7])
    def test_unknown_or_missing_cognitive_type_falls_back_to_none(
        self, tmp_path: Path, cognitive_type: object
    ) -> None:
        """모른다 ≠ 개념 — 미지 라벨·결손은 어느 깊이로도 접지 않고 None 정직 폴백."""
        path = _write_atom_graph(tmp_path, [_univ_atom("U-1", cognitive_type)])
        (entry,) = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        assert entry.required_depth is None

    def test_procedural_atom_is_not_derived_as_conceptual(self, tmp_path: Path) -> None:
        """변별 — 절차 원자가 conceptual로, 개념 원자가 procedural로 뒤바뀌지 않는다."""
        path = _write_atom_graph(tmp_path, [_univ_atom("U-P", "절차"), _univ_atom("U-C", "개념")])
        by_code = {
            e.concept_id: e.required_depth
            for e in load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        }
        assert by_code == {"U-P": "procedural", "U-C": "conceptual"}

    def test_grade_band_does_not_change_depth(self, tmp_path: Path) -> None:
        """학년이 올랐다고 깊이를 승격하지 않는다 — 4학년 개념 원자도 mastery가 아니다."""
        path = _write_atom_graph(
            tmp_path,
            [
                _univ_atom(f"U-{band}", "개념", band)
                for band in ("1학년", "2학년", "3학년", "4학년")
            ],
        )
        entries = load_kr_curriculum_entries_for_university_atoms(path, now=_NOW)
        assert {e.required_depth for e in entries} == {"conceptual"}
