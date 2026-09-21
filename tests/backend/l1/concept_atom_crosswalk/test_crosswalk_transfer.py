"""437-키 자산 원자 축 이전 *단위테스트* — S0-2 (hermetic·PG 불요).

PG 없이 검증 가능한 것만 못 박는다(`test_concept_content_projection.py` 가짜 엔진 패턴 미러):

  ① 로더 — crosswalk.jsonl/graph.json 다리/concepts.jsonl 파싱·유일성·조인 실패 오류
  ② **전파 규칙 동결** — atom_codes *전체* 전파(primary만 아님)·복수 concept union+dedup·사전순·
     unmapped skip·빈 스킬 concept의 원자도 빈 튜플로 유지(멱등 청소)
  ③ K-12 콘텐츠 원자 연결 유도 — dedup·사전순·unmapped skip·중복 src 오류
  ④ 갱신 SQL 구성 — UPDATE(INSERT 아님)·WHERE code·scope='K-12' 필터(대학 구조 차단)·
     rowcount 0 → missing 보고(조용히 넘기지 않음)
  ⑤ CLI — 파일 부재 종료코드 2·성공 시 두 이전 실행(transfer monkeypatch로 DB 우회)

가짜 엔진(`_FakeEngine`)은 begin() 컨텍스트 + execute()를 흉내내 실행 statement와 rowcount를
기록·주입한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType

import pytest

from whymath_backend.config import Settings
from whymath_backend.l1.concept_atom_crosswalk import populate as populate_cli
from whymath_backend.l1.concept_atom_crosswalk.transfer import (
    CrosswalkRecord,
    CrosswalkTransferReport,
    CrosswalkTransferStore,
    derive_atom_behavior_skills,
    derive_k12_content_atom_codes,
    load_behavior_skills_by_src,
    load_concept_src_bridge,
    load_crosswalk_records,
    transfer_atom_behavior_skills,
    transfer_concept_behavior_skills,
    transfer_k12_content_atom_codes,
)


# ──────────────────────────────────────────────────────────────────────────
# 가짜 sync 엔진 — begin() 컨텍스트 + execute()·rowcount 주입 (PG 없이 배선 관찰)
# ──────────────────────────────────────────────────────────────────────────
class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> _FakeResult:
        self._engine.executed.append(statement)
        # 행 부재 시뮬레이션 — missing_codes에 든 code의 UPDATE는 rowcount 0.
        params = statement.compile().params  # type: ignore[attr-defined]
        code = params.get("code_1")
        if code in self._engine.missing_codes:
            return _FakeResult(0)
        return _FakeResult(1)


class _FakeEngine:
    """SQLAlchemy sync Engine 최소 흉내 — begin() + 실행 statement·rowcount 기록."""

    def __init__(self, *, missing_codes: frozenset[str] = frozenset()) -> None:
        self.executed: list[object] = []
        self.missing_codes = missing_codes

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)


def _fake_store(
    *, missing_codes: frozenset[str] = frozenset()
) -> tuple[CrosswalkTransferStore, _FakeEngine]:
    engine = _FakeEngine(missing_codes=missing_codes)
    store = CrosswalkTransferStore(engine=engine)  # type: ignore[arg-type]  # 가짜 엔진(구조만 충족)
    return store, engine


def _compile(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────
# 코퍼스 픽스처 빌더
# ──────────────────────────────────────────────────────────────────────────
def _write_jsonl(tmp_path: Path, rows: list[dict[str, object]], *, name: str) -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


def _write_graph(tmp_path: Path, concepts: list[dict[str, object]]) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"concepts": concepts}, ensure_ascii=False), encoding="utf-8")
    return path


def _cw(concept_id: str, atom_codes: list[str], primary: str | None = None) -> dict[str, object]:
    return {
        "concept_id": concept_id,
        "atom_codes": atom_codes,
        "primary_atom_code": (
            primary if primary is not None else (atom_codes[0] if atom_codes else None)
        ),
        "match_method": "standard_code+name" if atom_codes else "unmapped",
        "review_status": "ai_estimated",
    }


# ──────────────────────────────────────────────────────────────────────────
# ① 로더
# ──────────────────────────────────────────────────────────────────────────
class TestLoadCrosswalk:
    def test_parses_records(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path, [_cw("math.a.x", ["a1", "a2"], "a2"), _cw("math.a.y", [])], name="cw.jsonl"
        )
        loaded = load_crosswalk_records(path)
        assert loaded == [
            CrosswalkRecord(concept_id="math.a.x", atom_codes=("a1", "a2"), primary_atom_code="a2"),
            CrosswalkRecord(concept_id="math.a.y", atom_codes=(), primary_atom_code=None),
        ]

    def test_missing_concept_id_raises(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"atom_codes": ["a1"]}], name="cw.jsonl")
        with pytest.raises(ValueError, match="concept_id"):
            load_crosswalk_records(path)

    def test_duplicate_concept_id_raises(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path, [_cw("math.a.x", ["a1"]), _cw("math.a.x", ["a2"])], name="cw.jsonl"
        )
        with pytest.raises(ValueError, match="중복"):
            load_crosswalk_records(path)

    def test_non_list_atom_codes_becomes_empty(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [{"concept_id": "math.a.x", "atom_codes": "a1", "primary_atom_code": None}],
            name="cw.jsonl",
        )
        assert load_crosswalk_records(path)[0].atom_codes == ()


class TestLoadConceptSrcBridge:
    def test_builds_bridge(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [
                {"concept_id": "math.a.x", "source_id": "N1"},
                {"concept_id": "math.a.y", "source_id": "N2"},
            ],
        )
        assert load_concept_src_bridge(path) == {"math.a.x": "N1", "math.a.y": "N2"}

    def test_missing_source_id_raises(self, tmp_path: Path) -> None:
        path = _write_graph(tmp_path, [{"concept_id": "math.a.x"}])
        with pytest.raises(ValueError, match="source_id"):
            load_concept_src_bridge(path)

    def test_duplicate_concept_id_raises(self, tmp_path: Path) -> None:
        path = _write_graph(
            tmp_path,
            [
                {"concept_id": "math.a.x", "source_id": "N1"},
                {"concept_id": "math.a.x", "source_id": "N2"},
            ],
        )
        with pytest.raises(ValueError, match="중복"):
            load_concept_src_bridge(path)


class TestLoadBehaviorSkills:
    def test_dedup_and_sorted(self, tmp_path: Path) -> None:
        path = _write_jsonl(
            tmp_path,
            [{"src_id": "N1", "behavior_skills": ["skill.b", "skill.a", "skill.b"]}],
            name="concepts.jsonl",
        )
        assert load_behavior_skills_by_src(path) == {"N1": ("skill.a", "skill.b")}

    def test_missing_field_becomes_empty(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"src_id": "N1"}], name="concepts.jsonl")
        assert load_behavior_skills_by_src(path) == {"N1": ()}

    def test_missing_src_id_raises(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"behavior_skills": []}], name="concepts.jsonl")
        with pytest.raises(ValueError, match="src_id"):
            load_behavior_skills_by_src(path)

    def test_duplicate_src_id_raises(self, tmp_path: Path) -> None:
        path = _write_jsonl(tmp_path, [{"src_id": "N1"}, {"src_id": "N1"}], name="concepts.jsonl")
        with pytest.raises(ValueError, match="중복"):
            load_behavior_skills_by_src(path)


# ──────────────────────────────────────────────────────────────────────────
# ② 전파 규칙 동결 — atom_codes 전체·union+dedup·사전순·unmapped skip
# ──────────────────────────────────────────────────────────────────────────
class TestDeriveAtomBehaviorSkills:
    _BRIDGE = {"math.a.x": "N1", "math.a.y": "N2", "math.a.z": "N3", "math.a.w": "N4"}

    def test_propagates_to_all_atom_codes_not_only_primary(self) -> None:
        """전파는 atom_codes *전체* — primary 귀속 규칙(mastery/오개념용)과 역할이 다르다."""
        crosswalk = [CrosswalkRecord("math.a.x", ("a1", "a2", "a3"), "a2")]
        skills = {"N1": ("skill.s1",)}
        derived = derive_atom_behavior_skills(crosswalk, self._BRIDGE, skills)
        assert derived == {"a1": ("skill.s1",), "a2": ("skill.s1",), "a3": ("skill.s1",)}

    def test_multi_concept_union_dedup_sorted(self) -> None:
        """복수 concept이 한 원자에 닿으면 union+dedup·사전순(전파 규칙 동결 핵심)."""
        crosswalk = [
            CrosswalkRecord("math.a.x", ("a1", "a2"), "a1"),
            CrosswalkRecord("math.a.y", ("a2", "a3"), "a2"),
        ]
        skills = {"N1": ("skill.s2", "skill.s1"), "N2": ("skill.s3", "skill.s1")}
        derived = derive_atom_behavior_skills(crosswalk, self._BRIDGE, skills)
        assert derived == {
            "a1": ("skill.s1", "skill.s2"),
            "a2": ("skill.s1", "skill.s2", "skill.s3"),  # union+dedup+사전순
            "a3": ("skill.s1", "skill.s3"),
        }

    def test_unmapped_row_is_skipped(self) -> None:
        crosswalk = [
            CrosswalkRecord("math.a.x", (), None),  # unmapped — 강제 귀속 금지
            CrosswalkRecord("math.a.y", ("a1",), "a1"),
        ]
        skills = {"N1": ("skill.s1",), "N2": ("skill.s2",)}
        derived = derive_atom_behavior_skills(crosswalk, self._BRIDGE, skills)
        assert derived == {"a1": ("skill.s2",)}

    def test_empty_skill_concept_atoms_kept_with_empty_tuple(self) -> None:
        """스킬 없는 concept(미매핑 33 선례)의 원자도 키로 남는다 — 재실행 시 stale 청소·멱등."""
        crosswalk = [CrosswalkRecord("math.a.z", ("a9",), "a9")]
        derived = derive_atom_behavior_skills(crosswalk, self._BRIDGE, {"N3": ()})
        assert derived == {"a9": ()}

    def test_bridge_join_failure_raises(self) -> None:
        crosswalk = [CrosswalkRecord("math.unknown", ("a1",), "a1")]
        with pytest.raises(ValueError, match="graph.json에 없음"):
            derive_atom_behavior_skills(crosswalk, self._BRIDGE, {"N1": ()})

    def test_skills_join_failure_raises(self) -> None:
        crosswalk = [CrosswalkRecord("math.a.x", ("a1",), "a1")]
        with pytest.raises(ValueError, match="조인 실패"):
            derive_atom_behavior_skills(crosswalk, self._BRIDGE, {"N9": ()})


# ──────────────────────────────────────────────────────────────────────────
# ③ K-12 콘텐츠 원자 연결 유도
# ──────────────────────────────────────────────────────────────────────────
class TestDeriveK12ContentAtomCodes:
    _BRIDGE = {"math.a.x": "N1", "math.a.y": "N2"}

    def test_maps_src_id_to_sorted_dedup_atoms(self) -> None:
        crosswalk = [CrosswalkRecord("math.a.x", ("b2", "a1", "b2"), "a1")]
        derived = derive_k12_content_atom_codes(crosswalk, self._BRIDGE)
        assert derived == {"N1": ("a1", "b2")}

    def test_unmapped_row_is_skipped(self) -> None:
        crosswalk = [
            CrosswalkRecord("math.a.x", (), None),
            CrosswalkRecord("math.a.y", ("a1",), "a1"),
        ]
        assert derive_k12_content_atom_codes(crosswalk, self._BRIDGE) == {"N2": ("a1",)}

    def test_duplicate_src_raises(self) -> None:
        crosswalk = [
            CrosswalkRecord("math.a.x", ("a1",), "a1"),
            CrosswalkRecord("math.a.y", ("a2",), "a2"),
        ]
        with pytest.raises(ValueError, match="중복"):
            derive_k12_content_atom_codes(crosswalk, {"math.a.x": "N1", "math.a.y": "N1"})

    def test_bridge_join_failure_raises(self) -> None:
        crosswalk = [CrosswalkRecord("math.unknown", ("a1",), "a1")]
        with pytest.raises(ValueError, match="graph.json에 없음"):
            derive_k12_content_atom_codes(crosswalk, self._BRIDGE)


# ──────────────────────────────────────────────────────────────────────────
# ④ 갱신 SQL 구성 — UPDATE·WHERE code·scope 필터·missing 보고
# ──────────────────────────────────────────────────────────────────────────
class TestAtomSkillUpdate:
    def test_executes_update_not_insert(self) -> None:
        store, engine = _fake_store()
        report = store.update_atom_behavior_skills({"a1": ("skill.s1",)})
        assert report == CrosswalkTransferReport(updated=1, missing=())
        assert len(engine.executed) == 1
        compiled = _compile(engine.executed[0])
        assert "UPDATE atom_node" in compiled
        assert "INSERT" not in compiled
        assert "behavior_skills" in compiled
        assert "updated_at" in compiled
        assert "atom_node.code =" in compiled

    def test_touches_only_transfer_columns(self) -> None:
        """이전 컬럼 외(name_ko·level·review_status 등) 무접촉 — 정본 projection 소관."""
        store, engine = _fake_store()
        store.update_atom_behavior_skills({"a1": ("skill.s1",)})
        compiled = _compile(engine.executed[0])
        for col in ("name_ko", "level", "review_status", "standard_codes", "atomicity"):
            assert f"{col}=" not in compiled.replace(" ", ""), f"이전 외 컬럼 접촉: {col}"

    def test_missing_row_reported(self) -> None:
        store, _engine = _fake_store(missing_codes=frozenset({"a9"}))
        report = store.update_atom_behavior_skills({"a1": ("skill.s1",), "a9": ()})
        assert report.updated == 1
        assert report.missing == ("a9",)

    def test_codes_processed_in_sorted_order(self) -> None:
        store, engine = _fake_store()
        store.update_atom_behavior_skills({"b2": (), "a1": ()})
        codes = [
            stmt.compile().params["code_1"]  # type: ignore[attr-defined]
            for stmt in engine.executed
        ]
        assert codes == ["a1", "b2"]  # 사전순(결정론)

    def test_wrapper_uses_injected_store(self) -> None:
        store, engine = _fake_store()
        report = transfer_atom_behavior_skills({"a1": ("skill.s1",)}, store=store)
        assert report.updated == 1
        assert len(engine.executed) == 1


class TestConceptSkillUpdate:
    """런타임 concept.behavior_skills 갱신(SKB-01) — atom_node 짝(같은 mapping·다른 테이블)."""

    def test_executes_update_not_insert(self) -> None:
        store, engine = _fake_store()
        report = store.update_concept_behavior_skills({"a1": ("skill.s1",)})
        assert report == CrosswalkTransferReport(updated=1, missing=())
        assert len(engine.executed) == 1
        compiled = _compile(engine.executed[0])
        assert "UPDATE concept" in compiled
        assert "INSERT" not in compiled
        assert "behavior_skills" in compiled
        assert "concept.code =" in compiled

    def test_does_not_touch_updated_at(self) -> None:
        """`Concept`에는 `updated_at` 컬럼이 없다(atom_node와 달리) — SET에 등장하면 안 된다."""
        store, engine = _fake_store()
        store.update_concept_behavior_skills({"a1": ("skill.s1",)})
        compiled = _compile(engine.executed[0])
        assert "updated_at" not in compiled

    def test_missing_row_reported(self) -> None:
        store, _engine = _fake_store(missing_codes=frozenset({"a9"}))
        report = store.update_concept_behavior_skills({"a1": ("skill.s1",), "a9": ()})
        assert report.updated == 1
        assert report.missing == ("a9",)

    def test_codes_processed_in_sorted_order(self) -> None:
        store, engine = _fake_store()
        store.update_concept_behavior_skills({"b2": (), "a1": ()})
        codes = [
            stmt.compile().params["code_1"]  # type: ignore[attr-defined]
            for stmt in engine.executed
        ]
        assert codes == ["a1", "b2"]  # 사전순(결정론)

    def test_wrapper_uses_injected_store(self) -> None:
        store, engine = _fake_store()
        report = transfer_concept_behavior_skills({"a1": ("skill.s1",)}, store=store)
        assert report.updated == 1
        assert len(engine.executed) == 1


class TestContentAtomCodesUpdate:
    def test_update_filters_k12_scope(self) -> None:
        """scope='K-12' 필터 — 대학 행은 WHERE가 구조적으로 차단(무변경 보장)."""
        from sqlalchemy.dialects import postgresql

        store, engine = _fake_store()
        report = store.update_k12_content_atom_codes({"N1": ("a1", "a2")})
        assert report == CrosswalkTransferReport(updated=1, missing=())
        compiled = _compile(engine.executed[0])
        assert "UPDATE concept_content" in compiled
        assert "atom_codes" in compiled
        assert "concept_content.scope =" in compiled
        params = (
            engine.executed[0]
            .compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
            .params
        )
        assert "K-12" in params.values()

    def test_missing_row_reported(self) -> None:
        store, _engine = _fake_store(missing_codes=frozenset({"CALC1-U1-S1"}))
        report = store.update_k12_content_atom_codes({"N1": ("a1",), "CALC1-U1-S1": ("a2",)})
        assert report.updated == 1
        assert report.missing == ("CALC1-U1-S1",)

    def test_wrapper_uses_injected_store(self) -> None:
        store, engine = _fake_store()
        report = transfer_k12_content_atom_codes({"N1": ("a1",)}, store=store)
        assert report.updated == 1
        assert len(engine.executed) == 1


def test_store_uses_default_settings_when_unset() -> None:
    store = CrosswalkTransferStore()
    assert isinstance(store._resolved_settings, Settings)


# ──────────────────────────────────────────────────────────────────────────
# ⑤ CLI — 파일 부재 종료코드 2·성공 시 두 이전 실행(DB 우회)
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def _write_corpora(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        cw = _write_jsonl(
            tmp_path, [_cw("math.a.x", ["a1", "a2"], "a1"), _cw("math.a.y", [])], name="cw.jsonl"
        )
        graph = _write_graph(
            tmp_path,
            [
                {"concept_id": "math.a.x", "source_id": "N1"},
                {"concept_id": "math.a.y", "source_id": "N2"},
            ],
        )
        concepts = _write_jsonl(
            tmp_path,
            [
                {"src_id": "N1", "behavior_skills": ["skill.s1"]},
                {"src_id": "N2", "behavior_skills": []},
            ],
            name="concepts.jsonl",
        )
        return cw, graph, concepts

    def test_missing_file_returns_2(self, tmp_path: Path) -> None:
        rc = populate_cli.main(
            [
                "--crosswalk",
                str(tmp_path / "nope.jsonl"),
                "--concept-graph",
                str(tmp_path / "g.json"),
                "--concepts",
                str(tmp_path / "c.jsonl"),
            ]
        )
        assert rc == 2

    def test_success_runs_both_transfers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cw, graph, concepts = self._write_corpora(tmp_path)
        seen: dict[str, dict[str, tuple[str, ...]]] = {}

        def _fake_atoms(mapping: dict[str, tuple[str, ...]]) -> CrosswalkTransferReport:
            seen["atoms"] = dict(mapping)
            return CrosswalkTransferReport(updated=len(mapping), missing=())

        def _fake_concepts(mapping: dict[str, tuple[str, ...]]) -> CrosswalkTransferReport:
            seen["concepts"] = dict(mapping)
            return CrosswalkTransferReport(updated=len(mapping), missing=())

        def _fake_content(mapping: dict[str, tuple[str, ...]]) -> CrosswalkTransferReport:
            seen["content"] = dict(mapping)
            return CrosswalkTransferReport(updated=len(mapping), missing=())

        # DB 우회 — transfer를 가짜로 교체(load·derive는 실 tmp 파일로 동작).
        monkeypatch.setattr(populate_cli, "transfer_atom_behavior_skills", _fake_atoms)
        monkeypatch.setattr(populate_cli, "transfer_concept_behavior_skills", _fake_concepts)
        monkeypatch.setattr(populate_cli, "transfer_k12_content_atom_codes", _fake_content)
        rc = populate_cli.main(
            ["--crosswalk", str(cw), "--concept-graph", str(graph), "--concepts", str(concepts)]
        )
        assert rc == 0
        # 전파 결과 — atom_codes 전체에 전파·concept은 atom과 같은 mapping·K-12 연결은 src_id 키.
        assert seen["atoms"] == {"a1": ("skill.s1",), "a2": ("skill.s1",)}
        assert seen["concepts"] == seen["atoms"]  # SKB-01: 같은 매핑 재사용(다리 불요)
        assert seen["content"] == {"N1": ("a1", "a2")}
        out = capsys.readouterr().out
        assert "unmapped 크로스워크 행 skip: 1건" in out  # math.a.y — 조용히 넘기지 않음
        assert "concept.behavior_skills 갱신" in out
        assert "이전 완료" in out

    def test_missing_rows_are_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cw, graph, concepts = self._write_corpora(tmp_path)

        def _fake_report(mapping: dict[str, tuple[str, ...]]) -> CrosswalkTransferReport:
            return CrosswalkTransferReport(updated=0, missing=tuple(sorted(mapping)))

        monkeypatch.setattr(populate_cli, "transfer_atom_behavior_skills", _fake_report)
        monkeypatch.setattr(populate_cli, "transfer_concept_behavior_skills", _fake_report)
        monkeypatch.setattr(populate_cli, "transfer_k12_content_atom_codes", _fake_report)
        rc = populate_cli.main(
            ["--crosswalk", str(cw), "--concept-graph", str(graph), "--concepts", str(concepts)]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "atom_node 대상 행 부재 2건" in out
        assert "concept 대상 행 부재 2건" in out
        assert "concept_content K-12 대상 행 부재 1건" in out
