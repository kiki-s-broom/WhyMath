"""OPS-139 — 원자 백본 정본↔prod DB 패리티 프로브의 판정 계약 동결.

이 스위트가 존재하는 이유: 정상 상태(MATCH)에서 초록인 것만으로는 보호가 아니다(CLAUDE.md 「보호
장치를 실패 주입 없이 '보호 있음'으로 선언 금지」). 그래서 각 어긋남을 *실제로 주입해* 그 판정이
나오는지, 그리고 서로 **다른** 판정으로 갈리는지 확인한다. 뮤테이션(절 하나 제거)으로 이 스위트가
정말 그 절을 밟는지는 `test_atom_graph_prod_parity_mutation.py`가 판정한다.

prod DB에는 닿지 않는다 — psql 실행기는 주입 seam(`runner`)으로 가짜를 꽂는다. 실측 실행은 Kiki
머신이며 이 한계는 모듈 docstring·리포트에 명시돼 있다.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.ops import atom_graph_prod_parity as mod

_REPO = Path(__file__).resolve().parents[3]
_REAL_GRAPH = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"

# 개념 5개·엣지 5개(subtype 4종) — 모든 축을 한 픽스처에서 흔들 수 있는 최소 정본.
_CONCEPTS = ["C1", "C2", "C3", "C4", "C5"]
_EDGES: list[tuple[str, str, str | None]] = [
    ("C1", "C2", "원본"),
    ("C2", "C3", "소단원내"),
    ("C3", "C4", "소단원내"),
    ("C4", "C5", "학년간"),
    ("C1", "C3", "소단원간"),
]


def _write_graph(
    tmp_path: Path,
    *,
    concepts: Sequence[str] = _CONCEPTS,
    edges: Sequence[tuple[str, str, str | None]] = _EDGES,
) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(
            {
                "concepts": [
                    {"code": c, "name": f"개념{c}", "level": "세부개념"} for c in concepts
                ],
                "edges": [
                    {
                        "from_code": f,
                        "to_code": t,
                        "relation": "prerequisite",
                        "relation_subtype": s,
                        "strength": 0.8,
                    }
                    for f, t, s in edges
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _canonical(tmp_path: Path, **kwargs: Any) -> mod.CanonicalSnapshot:
    return mod.compute_canonical(_write_graph(tmp_path, **kwargs))


def _db_payload(
    edges: Sequence[tuple[str, str, str | None]] = _EDGES,
    *,
    concepts: Sequence[str] = _CONCEPTS,
    atom_nodes: int | None = None,
    edge_type: str = "PREREQUISITE",
    cms_pairs: Sequence[tuple[str, str]] = (),
    extra_rows: Sequence[list[Any]] = (),
) -> dict[str, Any]:
    """`read_db_payload`가 돌려주는 JSON 모양 그대로 — 서버가 만든 행 배열."""
    rows: list[list[Any]] = [[f, t, s, edge_type, (f, t) in cms_pairs] for f, t, s in edges]
    rows.extend(extra_rows)
    return {
        "concepts": list(concepts),
        "atom_nodes": len(concepts) if atom_nodes is None else atom_nodes,
        "edges": rows,
        "_cms_column_present": True,
        "_atom_node_table_present": True,
    }


def _snapshot_pair(
    tmp_path: Path, payload: dict[str, Any], **graph_kwargs: Any
) -> tuple[mod.CanonicalSnapshot, mod.DbSnapshot]:
    canonical = _canonical(tmp_path, **graph_kwargs)
    return canonical, mod.parse_db_payload(payload, canonical)


class _FakeRunner:
    """docker exec psql 대역 — 호출 순서(스키마 사실 → 본 조회)대로 응답을 낸다."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        facts: dict[str, Any] | None = None,
        returncode: int = 0,
        stderr: bytes = b"",
        stdout_override: bytes | None = None,
        raises: BaseException | None = None,
    ) -> None:
        self.payload = payload
        self.facts = facts if facts is not None else {"cms_column": True, "atom_node_table": True}
        self.returncode = returncode
        self.stderr = stderr
        self.stdout_override = stdout_override
        self.raises = raises
        self.calls: list[tuple[list[str], str]] = []

    def __call__(
        self, args: Sequence[str], stdin: bytes, timeout: float
    ) -> subprocess.CompletedProcess[bytes]:
        sql = stdin.decode("ascii")
        self.calls.append((list(args), sql))
        if self.raises is not None:
            raise self.raises
        if self.stdout_override is not None:
            out = self.stdout_override
        elif "'cms_column'" in sql:
            out = json.dumps(self.facts).encode("utf-8")
        else:
            assert self.payload is not None
            body = {k: v for k, v in self.payload.items() if not k.startswith("_")}
            # 서버는 JSON을 UTF-8 한 줄로 돌려준다 — 한글 subtype이 그대로 실려 와야 한다.
            out = json.dumps(body, ensure_ascii=False).encode("utf-8")
        return subprocess.CompletedProcess(list(args), self.returncode, out, self.stderr)


# ──────────────────────────────────────────────────────────────────────────
# 판정 — 3상태·방향·상쇄 방지
# ──────────────────────────────────────────────────────────────────────────
class TestJudgeStates:
    def test_identical_state_is_match_exit_0(self, tmp_path: Path) -> None:
        """(a) 정본 = DB → MATCH·exit 0·방향 없음."""
        canonical, db = _snapshot_pair(tmp_path, _db_payload())
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.MATCH
        assert verdict.exit_code == 0
        assert verdict.direction == ""
        assert verdict.findings == ()

    def test_db_less_is_drift_with_db_less_direction(self, tmp_path: Path) -> None:
        """(b) DB가 정본보다 적다(S4-60 직전 실제 상태 형태) → DRIFT·DB<정본(미적재)."""
        canonical, db = _snapshot_pair(tmp_path, _db_payload(_EDGES[:3]))
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.exit_code == 1
        assert verdict.direction == mod.DIR_DB_LESS
        assert verdict.only_canonical_total == 2
        assert verdict.only_db_total == 0
        edge_total = next(f for f in verdict.findings if f.axis == "edge_total")
        assert (edge_total.expected, edge_total.actual) == ("5", "3")

    def test_db_more_is_drift_with_db_more_direction(self, tmp_path: Path) -> None:
        """(c) DB가 정본보다 많다(코퍼스에 없는 잔존 행) → DRIFT·DB>정본."""
        extra: tuple[str, str, str | None] = ("C2", "C5", "소단원간")
        canonical, db = _snapshot_pair(tmp_path, _db_payload([*_EDGES, extra]))
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_DB_MORE
        assert verdict.only_db == (("C2", "C5", "소단원간"),)

    def test_same_total_different_subtype_distribution_is_drift(self, tmp_path: Path) -> None:
        """(d) 총합이 같아도 subtype 분포가 다르면 DRIFT — 상쇄 방지(수-전용 입력으로 고립 검증)."""
        canonical = mod.CanonicalSnapshot(
            edge_total=5,
            edge_by_subtype={"원본": 1, "소단원내": 2, "학년간": 1, "소단원간": 1},
            concept_total=5,
            atom_node_total=5,
            edges=None,
            concept_codes=frozenset(_CONCEPTS),
        )
        db = mod.DbSnapshot(
            edge_total=5,  # 총합 동일
            edge_by_subtype={"원본": 0, "소단원내": 3, "학년간": 1, "소단원간": 1},
            concept_total=5,
            concept_missing=0,
            atom_node_total=5,
            edges=None,
        )
        verdict = mod.judge(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_SAME_TOTAL
        assert {f.axis for f in verdict.findings} == {"subtype[원본]", "subtype[소단원내]"}
        assert not any(f.axis == "edge_total" for f in verdict.findings)

    def test_same_total_and_distribution_but_different_edge_is_drift(self, tmp_path: Path) -> None:
        """수·분포가 모두 같아도 *다른 엣지*면 DRIFT — 지문이 수 비교의 한계를 메운다(④)."""
        swapped: list[tuple[str, str, str | None]] = [*_EDGES[1:], ("C1", "C5", "원본")]
        canonical, db = _snapshot_pair(tmp_path, _db_payload(swapped))
        assert canonical.edge_total == db.edge_total
        assert canonical.edge_by_subtype == db.edge_by_subtype  # 수·분포는 동일
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_MIXED  # 양쪽이 서로에게 없는 것을 갖는다
        assert [f.axis for f in verdict.findings] == ["edge_set_fingerprint"]
        assert verdict.only_canonical == (("C1", "C2", "원본"),)
        assert verdict.only_db == (("C1", "C5", "원본"),)

    def test_unreadable_db_is_unknown_exit_2_not_match(self, tmp_path: Path) -> None:
        """(e) DB 값을 못 읽으면 UNKNOWN(exit 2)이지 MATCH가 아니다 — 모른다는 아니다가 아니다."""
        verdict = mod.evaluate(_canonical(tmp_path), None, unknown_reason="docker 없음")
        assert verdict.status == mod.UNKNOWN
        assert verdict.exit_code == 2
        assert verdict.reason == "docker 없음"
        assert verdict.findings == ()

    def test_three_statuses_map_to_three_distinct_exit_codes(self) -> None:
        """종료 코드가 접히면(같은 값) 3상태가 2상태로 위장된다."""
        codes = {
            mod.Verdict(status=mod.MATCH).exit_code,
            mod.Verdict(status=mod.DRIFT).exit_code,
            mod.Verdict(status=mod.UNKNOWN).exit_code,
        }
        assert codes == {0, 1, 2}

    def test_atom_node_shortfall_is_drift(self, tmp_path: Path) -> None:
        """atom_node 총수가 정본보다 적으면(SKB-03 형태: 미적재) DRIFT·DB<정본."""
        canonical, db = _snapshot_pair(tmp_path, _db_payload(atom_nodes=0))
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_DB_LESS
        assert [f.axis for f in verdict.findings] == ["atom_node_total"]

    def test_missing_canonical_concept_in_db_is_drift(self, tmp_path: Path) -> None:
        """정본 개념이 DB에 없으면 DRIFT — 개념 *총수*가 아니라 포함관계로 본다."""
        payload = _db_payload(concepts=["C1", "C2", "C3", "C4"], atom_nodes=5)
        canonical, db = _snapshot_pair(tmp_path, payload)
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert [f.axis for f in verdict.findings] == ["concept_missing"]
        assert verdict.direction == mod.DIR_DB_LESS

    def test_db_only_concepts_are_informational_not_drift(self, tmp_path: Path) -> None:
        """DB에만 있는 개념(구 개념그래프·CMS 신규 개념)은 판정에 쓰지 않고 정보로만 싣는다."""
        # atom_node는 graph.json에서만 적재되므로 정본 개념 수(5)에 머문다 — 개념만 늘어난 상태.
        payload = _db_payload(concepts=[*_CONCEPTS, "LEGACY1", "LEGACY2"], atom_nodes=5)
        canonical, db = _snapshot_pair(tmp_path, payload)
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.MATCH
        assert any("DB에만 있는 개념 2건" in n for n in verdict.notes)


class TestCmsAndNonPrerequisite:
    def test_cms_owned_extra_edge_is_excluded_not_residue(self, tmp_path: Path) -> None:
        """CMS가 만든 정본 밖 엣지는 '잔존 행'이 아니다 — 적재기가 건너뛰는 쌍이다(P3-26)."""
        payload = _db_payload([*_EDGES, ("C2", "C5", "소단원간")], cms_pairs=[("C2", "C5")])
        canonical, db = _snapshot_pair(tmp_path, payload)
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.MATCH
        assert any("CMS 소유 엣지 1건" in n for n in verdict.notes)

    def test_cms_owned_canonical_pair_is_excluded_from_both_sides(self, tmp_path: Path) -> None:
        """CMS가 소유한 쌍이 정본에도 있으면 *양쪽에서* 뺀다 — 한쪽만 빼면 미적재로 오판된다."""
        payload = _db_payload(_EDGES, cms_pairs=[("C2", "C3")])
        canonical, db = _snapshot_pair(tmp_path, payload)
        assert mod.judge(canonical, db).status == mod.DRIFT  # 정본 쪽을 안 빼면 어긋난다
        assert mod.evaluate(canonical, db).status == mod.MATCH  # 양쪽에서 빼면 일치

    def test_non_prerequisite_edges_are_ignored_and_counted(self, tmp_path: Path) -> None:
        """PREREQUISITE가 아닌 엣지는 적재기가 만들지 않은 행이라 비교에서 빼되 건수를 남긴다."""
        payload = _db_payload(extra_rows=[["C1", "C5", None, "COMPOSED_OF", False]])
        canonical, db = _snapshot_pair(tmp_path, payload)
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.MATCH
        assert db.non_prerequisite_edges == 1
        assert any("비-선수" in n for n in verdict.notes)


# ──────────────────────────────────────────────────────────────────────────
# 정본 쪽 기대값 — 적재기와 같은 규칙·스캔 0건은 오류
# ──────────────────────────────────────────────────────────────────────────
class TestCanonical:
    def test_expected_values_come_from_loader_rules(self, tmp_path: Path) -> None:
        canonical = _canonical(tmp_path)
        assert canonical.edge_total == 5
        assert dict(canonical.edge_by_subtype) == {
            "원본": 1,
            "소단원내": 2,
            "학년간": 1,
            "소단원간": 1,
        }
        assert canonical.concept_total == 5
        assert canonical.atom_node_total == 5

    def test_orphan_edges_are_skipped_like_the_loader(self, tmp_path: Path) -> None:
        """양끝 개념이 없는 엣지는 적재기가 orphan skip한다 — 정본 수와 적재 수가 다를 수 있다."""
        edges = [*_EDGES, ("C1", "GHOST", "원본")]
        canonical = _canonical(tmp_path, edges=edges)
        assert canonical.edge_total == 5
        assert canonical.orphan_skipped == 1

    def test_duplicate_pair_collapses_to_one_row_last_wins(self, tmp_path: Path) -> None:
        """같은 (from,to)는 UNIQUE upsert라 DB에서 한 행이다 — 나중 레코드의 subtype이 이긴다."""
        edges = [("C1", "C2", "원본"), ("C1", "C2", "소단원내")]
        canonical = _canonical(tmp_path, edges=edges)
        assert canonical.edge_total == 1
        assert dict(canonical.edge_by_subtype) == {"소단원내": 1}

    def test_null_subtype_is_a_named_bucket_and_matches_db_null(self, tmp_path: Path) -> None:
        edges: list[tuple[str, str, str | None]] = [("C1", "C2", None), ("C2", "C3", "원본")]
        canonical = _canonical(tmp_path, edges=edges)
        assert canonical.edge_by_subtype[mod.NULL_SUBTYPE] == 1
        db = mod.parse_db_payload(_db_payload(edges), canonical)
        assert mod.evaluate(canonical, db).status == mod.MATCH

    def test_zero_edges_is_an_error_not_a_vacuous_match(self, tmp_path: Path) -> None:
        """(f) 엣지 0건이면 MATCH가 아니라 오류 — 공허한 통과 금지."""
        with pytest.raises(mod.CanonicalError, match="0건"):
            _canonical(tmp_path, edges=[])

    def test_all_edges_orphan_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(mod.CanonicalError, match="0건"):
            _canonical(tmp_path, edges=[("X", "Y", "원본")])

    def test_zero_concepts_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(mod.CanonicalError, match="개념이 0건"):
            _canonical(tmp_path, concepts=[], edges=[])

    def test_missing_file_is_an_error_naming_the_type(self, tmp_path: Path) -> None:
        with pytest.raises(mod.CanonicalError, match="FileNotFoundError"):
            mod.compute_canonical(tmp_path / "nope.json")

    def test_broken_json_is_an_error_naming_the_type(self, tmp_path: Path) -> None:
        path = tmp_path / "graph.json"
        path.write_text("{ not json", encoding="utf-8")
        with pytest.raises(mod.CanonicalError, match="JSONDecodeError"):
            mod.compute_canonical(path)

    def test_source_is_recorded_with_path_and_sha(self, tmp_path: Path) -> None:
        path = _write_graph(tmp_path)
        canonical = mod.compute_canonical(path)
        assert canonical.source_path == str(path)
        assert len(canonical.source_sha12) == 12
        assert (
            canonical.source_sha12
            == __import__("hashlib").sha256(path.read_bytes()).hexdigest()[:12]
        )


class TestRealCorpus:
    """실제 정본으로 (a)·(b)를 재현한다 — 수치를 상수로 박지 않고 정본에서 계산한다."""

    def test_real_graph_parity_and_s4_60_shaped_shortfall(self) -> None:
        canonical = mod.compute_canonical(_REAL_GRAPH)
        assert canonical.edge_total >= 24
        assert canonical.edges is not None
        concepts = sorted(canonical.concept_codes)
        full = [(f, t, s or None) for f, t, s in sorted(canonical.edges)]

        match_db = mod.parse_db_payload(
            _db_payload(full, concepts=concepts, atom_nodes=canonical.atom_node_total), canonical
        )
        assert mod.evaluate(canonical, match_db).status == mod.MATCH  # (a) 정상

        # (b) S4-60 직전의 형태 — 정본보다 24건 적은 DB(2,234 vs 2,210과 같은 모양)
        short_db = mod.parse_db_payload(
            _db_payload(full[:-24], concepts=concepts, atom_nodes=canonical.atom_node_total),
            canonical,
        )
        verdict = mod.evaluate(canonical, short_db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_DB_LESS
        assert verdict.only_canonical_total == 24
        edge_total = next(f for f in verdict.findings if f.axis == "edge_total")
        assert int(edge_total.expected) - int(edge_total.actual) == 24


# ──────────────────────────────────────────────────────────────────────────
# 지문 — 결정론·경계 모호성
# ──────────────────────────────────────────────────────────────────────────
class TestFingerprint:
    def test_order_independent(self) -> None:
        a = [("A", "B", "x"), ("B", "C", "y")]
        assert mod.edge_fingerprint(a) == mod.edge_fingerprint(reversed(a))

    def test_distinguishes_boundary_ambiguity(self) -> None:
        """`a,b`+`c`와 `a`+`b,c`가 같은 문자열이 되면 안 된다 — 구분자가 code에 못 나오는 문자다."""
        assert mod.edge_fingerprint([("a,b", "c", "")]) != mod.edge_fingerprint([("a", "b,c", "")])

    def test_subtype_participates(self) -> None:
        assert mod.edge_fingerprint([("A", "B", "x")]) != mod.edge_fingerprint([("A", "B", "y")])


# ──────────────────────────────────────────────────────────────────────────
# DB 읽기 — 읽기 전용 SQL·인자 안전·실패 사유
# ──────────────────────────────────────────────────────────────────────────
class TestReadOnlySql:
    @pytest.mark.parametrize("cms", [True, False])
    @pytest.mark.parametrize("node", [True, False])
    def test_generated_sql_passes_the_read_only_guard_and_is_ascii(
        self, cms: bool, node: bool
    ) -> None:
        sql = mod.build_snapshot_sql(cms_column=cms, atom_node_table=node)
        mod.assert_read_only_sql(sql)
        assert sql.isascii(), "한국어 리터럴은 psql로 보내지 않는다(Windows cp949 셸이 깨뜨린다)"
        assert ("cms_edited_at" in sql) is cms
        assert ("FROM atom_node" in sql) is node

    def test_schema_facts_sql_is_read_only_and_ascii(self) -> None:
        mod.assert_read_only_sql(mod._SCHEMA_FACTS_SQL)
        assert mod._SCHEMA_FACTS_SQL.isascii()

    @pytest.mark.parametrize(
        "bad",
        [
            "INSERT INTO concept_edge VALUES (1)",
            "UPDATE concept SET code = 'x'",
            "DELETE FROM concept_edge",
            "DROP TABLE concept_edge",
            "SELECT 1; DELETE FROM concept_edge",
            "SELECT 1; SELECT 2",
            "SET default_transaction_read_only = off",
            "SELECT 1 FROM concept; TRUNCATE concept_edge",
            "WITH x AS (DELETE FROM concept_edge RETURNING 1) SELECT * FROM x",
        ],
    )
    def test_guard_rejects_anything_but_one_select(self, bad: str) -> None:
        with pytest.raises(ValueError):
            mod.assert_read_only_sql(bad)

    def test_keywords_inside_string_literals_do_not_trip_the_guard(self) -> None:
        """JSON 키 같은 문자열 리터럴 안의 단어는 쓰기 시도가 아니다 — 오탐하면 정상 SQL이 막힌다."""
        mod.assert_read_only_sql("SELECT json_build_object('update', 1, 'set', 2);")


class TestRunner:
    def test_psql_args_are_ascii_read_only_and_never_pass_sql_as_argument(self) -> None:
        args = mod._psql_args("whymath-pg", "whymath", "whymath")
        assert all(a.isascii() for a in args)
        assert "PGOPTIONS=-c default_transaction_read_only=on" in args  # 서버 쪽 쓰기 거부
        assert "PGCLIENTENCODING=UTF8" in args
        assert args[-2:] == ["-f", "-"]  # SQL은 인자가 아니라 stdin
        assert "-c" not in args[args.index("psql") :]

    def test_two_step_read_uses_schema_facts_to_shape_the_main_query(self) -> None:
        """prod가 마이그레이션에 뒤처져 `cms_edited_at`이 없어도 쿼리 전체가 죽지 않는다."""
        runner = _FakeRunner(_db_payload(), facts={"cms_column": False, "atom_node_table": False})
        payload = mod.read_db_payload(runner=runner)
        assert len(runner.calls) == 2
        assert "'cms_column'" in runner.calls[0][1]
        assert "cms_edited_at IS NOT NULL" not in runner.calls[1][1]
        assert "FROM atom_node" not in runner.calls[1][1]
        assert payload["_cms_column_present"] is False
        assert payload["_atom_node_table_present"] is False

    def test_missing_atom_node_table_surfaces_as_drift_with_reason(self, tmp_path: Path) -> None:
        canonical = _canonical(tmp_path)
        payload = _db_payload(atom_nodes=0)
        payload["_atom_node_table_present"] = False
        verdict = mod.evaluate(canonical, mod.parse_db_payload(payload, canonical))
        assert verdict.status == mod.DRIFT
        finding = next(f for f in verdict.findings if f.axis == "atom_node_total")
        assert "테이블 자체가 DB에 없다" in finding.detail

    def test_korean_subtype_round_trips_through_utf8_bytes(self) -> None:
        runner = _FakeRunner(_db_payload())
        payload = mod.read_db_payload(runner=runner)
        subtypes = {row[2] for row in payload["edges"]}
        assert {"원본", "소단원내", "학년간", "소단원간"} == subtypes

    @pytest.mark.parametrize(
        ("runner", "needle"),
        [
            (_FakeRunner(raises=FileNotFoundError("docker")), "FileNotFoundError"),
            (
                _FakeRunner(raises=subprocess.TimeoutExpired(cmd="docker", timeout=3)),
                "타임아웃",
            ),
            (_FakeRunner(raises=PermissionError("denied")), "PermissionError"),
            (
                _FakeRunner(returncode=1, stderr=b'FATAL: database "whymath" does not exist'),
                'database "whymath" does not exist',
            ),
            (_FakeRunner(stdout_override=b""), "비었다"),
            (_FakeRunner(stdout_override=b"not json at all"), "JSONDecodeError"),
            (_FakeRunner(stdout_override=b"[1, 2, 3]"), "JSON 객체가 아니다"),
        ],
        ids=[
            "no-docker",
            "timeout",
            "oserror",
            "psql-nonzero-stderr",
            "empty-stdout",
            "bad-json",
            "not-object",
        ],
    )
    def test_every_read_failure_becomes_a_reasoned_db_read_error(
        self, runner: _FakeRunner, needle: str
    ) -> None:
        """실패는 사유를 남긴다 — 예외 타입명만으로는 서로 다른 실패가 같은 글자로 보인다."""
        with pytest.raises(mod.DbReadError, match=needle):
            mod.read_db_payload(runner=runner)


class TestParseShape:
    @pytest.mark.parametrize(
        "payload",
        [
            {},  # 키 전부 없음
            {"concepts": [], "atom_nodes": 0},  # edges 없음
            {"concepts": "x", "atom_nodes": 0, "edges": []},  # 배열 아님
            {"concepts": [], "atom_nodes": "many", "edges": []},  # 정수 아님
            {"concepts": [], "atom_nodes": 0, "edges": [["only", "two"]]},  # 행 모양 틀림
        ],
    )
    def test_malformed_payload_is_unknown_not_a_silent_empty_db(
        self, tmp_path: Path, payload: dict[str, Any]
    ) -> None:
        """모양이 틀린 응답을 '빈 DB'로 읽으면 DRIFT로 위장된다 — 읽기 실패(UNKNOWN)다."""
        with pytest.raises(mod.DbReadError):
            mod.parse_db_payload(payload, _canonical(tmp_path))

    def test_genuinely_empty_db_is_drift_not_unknown(self, tmp_path: Path) -> None:
        """진짜로 빈 DB는 *읽었다* — 미적재(DRIFT)다. SKB-03에서 빈 테이블이 정상처럼 보였던 형태."""
        canonical = _canonical(tmp_path)
        db = mod.parse_db_payload(_db_payload([], concepts=[], atom_nodes=0), canonical)
        verdict = mod.evaluate(canonical, db)
        assert verdict.status == mod.DRIFT
        assert verdict.direction == mod.DIR_DB_LESS


# ──────────────────────────────────────────────────────────────────────────
# CLI — 종료 코드·리포트 내용
# ──────────────────────────────────────────────────────────────────────────
class TestCli:
    def _run(
        self, tmp_path: Path, runner: _FakeRunner, capsys: pytest.CaptureFixture[str], *extra: str
    ) -> tuple[int, str]:
        graph = _write_graph(tmp_path)
        code = mod.main(["--graph", str(graph), *extra], runner=runner)
        return code, capsys.readouterr().out

    def test_match_exit_0_and_report_names_source_and_weak_signal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = self._run(tmp_path, _FakeRunner(_db_payload()), capsys)
        assert code == 0
        assert "STATUS=MATCH" in out
        assert "sha256=" in out  # 정본 출처가 찍힌다
        assert str(tmp_path / "graph.json") in out
        assert "총합 일치는 약한 신호" in out  # 한계 명시

    def test_drift_exit_1_prints_direction_and_diff_sample(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = self._run(tmp_path, _FakeRunner(_db_payload(_EDGES[:3])), capsys)
        assert code == 1
        assert "STATUS=DRIFT · DIRECTION=DB<정본" in out
        assert "정본에만 있는 엣지 2건" in out
        assert "C4 → C5 [학년간]" in out

    def test_unknown_exit_2_prints_reason_and_not_a_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        runner = _FakeRunner(returncode=1, stderr=b"Error response from daemon: No such container")
        code, out = self._run(tmp_path, runner, capsys)
        assert code == 2
        assert "STATUS=UNKNOWN" in out
        assert "No such container" in out  # 사유(stderr)가 남는다
        assert "STATUS=MATCH" not in out
        assert "STATUS=DRIFT" not in out

    def test_canonical_error_exit_3_is_distinct_from_unknown(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        runner = _FakeRunner(_db_payload())
        code = mod.main(["--graph", str(tmp_path / "missing.json")], runner=runner)
        out = capsys.readouterr().out
        assert code == 3
        assert "INPUT_ERROR" in out
        assert runner.calls == []  # 정본을 못 읽으면 DB에 말을 걸지도 않는다

    def test_zero_edge_graph_exit_3_never_match(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        graph = _write_graph(tmp_path, edges=[])
        code = mod.main(["--graph", str(graph)], runner=_FakeRunner(_db_payload([])))
        assert code == 3
        assert "STATUS=MATCH" not in capsys.readouterr().out

    def test_json_artifact_mirrors_the_verdict(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "out" / "parity.json"
        code, _out = self._run(
            tmp_path, _FakeRunner(_db_payload(_EDGES[:3])), capsys, "--json", str(target)
        )
        data = json.loads(target.read_text(encoding="utf-8"))
        assert code == data["exit_code"] == 1
        assert data["status"] == "DRIFT"
        assert data["direction"] == mod.DIR_DB_LESS
        assert data["canonical"]["edge_total"] == 5
        assert data["db"]["edge_total"] == 3
        assert len(data["canonical"]["source_sha12"]) == 12

    def test_diff_limit_truncates_the_sample_but_not_the_total(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = self._run(tmp_path, _FakeRunner(_db_payload([])), capsys, "--diff-limit", "2")
        assert code == 1
        assert "정본에만 있는 엣지 5건(상위 2)" in out
