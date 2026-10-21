"""KG-14 — 원자 백본 적재의 잔존 엣지 은퇴 계약(hermetic · PG 불요).

주장마다 *깨지면 RED인 입력*으로 확인한다.

1. 범위 — 선수·원자 코드 양끝·비-CMS·정본에 없는 쌍만 은퇴한다(넷 중 하나라도 빠지면 대상 아님).
2. 패리티 프로브와 같은 집합 — prod 실측(2026-10-21)의 "적재 후 잔존"(DB에만 − 정본에만 같은 쌍)과
   은퇴 계획이 같아야 한다.
3. 실제 정본 재현 — KG-12 정본 위에 옛 방향 5쌍(prod 실측 순환 위험 쌍)이 남은 DB는 은퇴 없이는
   순환이고, 은퇴하면 비순환이다.
4. 트랜잭션 순서 — 잠금 → 읽기 → 삭제 → 순환 검사 → upsert. 삭제 건수가 계획과 다르면 롤백(예외).
5. 배선 — 적재 함수·CLI가 모드를 실제로 넘기고, plan은 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from whymath_backend.l1.atom_graph.atom_backend_edge import (
    AtomBackendEdgeRecord,
    AtomBackendEdgeStore,
)
from whymath_backend.l1.atom_graph.atom_edge_retire import (
    RETIRE_APPLY,
    RETIRE_PLAN,
    RETIRE_REPORT,
    DbEdgeRow,
    RetirePlan,
    StaleEdgeRetireError,
    cycle_after_retirement,
    plan_retirement,
    render_plan,
    validate_mode,
)
from whymath_backend.schema.enums import EdgeType

_ROOT = Path(__file__).resolve().parents[4]
_CORPUS = _ROOT / "data" / "corpus" / "atom_graph_v1" / "graph.json"
_PRE = EdgeType.PREREQUISITE.value

# prod 실측(2026-10-21 · main 9ca012c1) 순환 위험 5쌍 — DB에 남은 *옛* 방향
_PROD_CYCLE_RISK_OLD = (
    ("4수01-02-2", "4수01-01-1"),
    ("AALG1-P03", "AALG1-C14"),
    ("CALC2-C08", "CALC2-R04"),
    ("LINA1-P07", "LINA1-P08"),
    ("MFLD-C06", "MFLD-C07"),
)


def _row(
    a: str,
    b: str,
    *,
    subtype: str | None = "원본",
    edge_type: str = _PRE,
    cms: bool = False,
    edge_id: str | None = None,
) -> DbEdgeRow:
    # 결정적 식별자 — parametrize 인자에 무작위 값이 들어가면 병렬 수집이 어긋난다(OPS-144)
    return DbEdgeRow(
        edge_id=edge_id or f"{a}>{b}:{edge_type}:{int(cms)}:{subtype}",
        from_code=a,
        to_code=b,
        relation_subtype=subtype,
        edge_type=edge_type,
        cms_owned=cms,
    )


# ──────────────────────────────────────────────────────────────────────────
# 1. 범위
# ──────────────────────────────────────────────────────────────────────────
class TestScope:
    SCOPE = frozenset({"A", "B", "C", "D"})
    CANON = {("A", "B"), ("B", "C")}

    def test_only_in_scope_prerequisite_non_cms_absent_pairs_are_stale(self) -> None:
        rows = [
            _row("A", "B"),  # 정본에 있음 → 유지
            _row("B", "C", subtype="다른 유형"),  # 같은 쌍·subtype만 다름 → upsert가 고침 → 유지
            _row("C", "D"),  # 정본에 없음 → 은퇴
            _row("D", "A", cms=True),  # CMS 소유 → 지킴
            _row("A", "X"),  # 한쪽이 범위 밖 → 건드리지 않음
            _row("A", "D", edge_type="RELATED"),  # 선수가 아님 → 건드리지 않음
        ]
        plan = plan_retirement(rows, self.CANON, self.SCOPE)
        assert [r.pair for r in plan.stale] == [("C", "D")]
        assert [r.pair for r in plan.cms_kept] == [("D", "A")]
        assert plan.in_scope_prerequisite == 4
        assert plan.out_of_scope == 2

    @pytest.mark.parametrize(
        ("row", "why"),
        [
            (_row("C", "D", cms=True), "CMS 소유"),
            (_row("C", "X"), "범위 밖"),
            (_row("C", "D", edge_type="RELATED"), "비-선수"),
            (_row("A", "B", subtype="딴 것"), "정본 쌍"),
        ],
    )
    def test_each_exclusion_clause_keeps_the_row(self, row: DbEdgeRow, why: str) -> None:
        assert plan_retirement([row], self.CANON, self.SCOPE).stale == (), why

    def test_order_is_deterministic(self) -> None:
        rows = [_row("D", "A"), _row("C", "A"), _row("C", "D")]
        first = plan_retirement(rows, set(), self.SCOPE)
        second = plan_retirement(list(reversed(rows)), set(), self.SCOPE)
        assert [r.pair for r in first.stale] == [r.pair for r in second.stale]
        assert [r.pair for r in first.stale] == sorted(r.pair for r in rows)

    def test_mode_validation(self) -> None:
        assert validate_mode(RETIRE_APPLY) == RETIRE_APPLY
        with pytest.raises(ValueError):
            validate_mode("delete")


# ──────────────────────────────────────────────────────────────────────────
# 2. 패리티 프로브와 같은 집합
# ──────────────────────────────────────────────────────────────────────────
def _write_graph(path: Path, codes: list[str], edges: list[tuple[str, str, str]]) -> Path:
    payload = {
        "concepts": [
            {"code": c, "name": f"개념 {c}", "level": "세부개념", "parent_code": None}
            for c in codes
        ],
        "edges": [
            {"from_code": a, "to_code": b, "relation": "prerequisite", "relation_subtype": s}
            for a, b, s in edges
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestProbeEquivalence:
    def test_plan_equals_probe_db_only_minus_same_pair_canonical(self, tmp_path: Path) -> None:
        from whymath_backend.ops.atom_graph_prod_parity import (
            compute_canonical,
            evaluate,
            parse_db_payload,
        )

        codes = ["A", "B", "C", "D", "E"]
        graph = _write_graph(
            tmp_path / "graph.json",
            codes,
            [("A", "B", "원본"), ("C", "B", "원본"), ("C", "D", "소단원내"), ("D", "E", "원본")],
        )
        db_rows = [
            _row("A", "B", subtype="원본"),  # 같음
            _row("B", "C", subtype="원본"),  # 뒤집기 전 옛 방향 → 은퇴
            _row("C", "D", subtype="원본"),  # subtype만 다름 → 유지(upsert가 고침)
            _row("A", "E", subtype="원본"),  # 정본에서 지워짐 → 은퇴
            _row("E", "A", subtype="원본", cms=True),  # CMS → 양쪽 다 제외
        ]
        canonical = compute_canonical(graph)
        db = parse_db_payload(
            {
                "concepts": codes,
                "edges": [
                    [r.from_code, r.to_code, r.relation_subtype, r.edge_type, r.cms_owned]
                    for r in db_rows
                ],
                "atom_nodes": 0,
            },
            canonical,
        )
        verdict = evaluate(canonical, db, diff_limit=1000)
        canon_only_pairs = {(a, b) for a, b, _s in verdict.only_canonical}
        probe_stale = {(a, b) for a, b, _s in verdict.only_db} - canon_only_pairs

        canon_pairs = {(e[0], e[1]) for e in canonical.edges or ()}
        plan = plan_retirement(db_rows, canon_pairs, canonical.concept_codes)
        assert {r.pair for r in plan.stale} == probe_stale == {("B", "C"), ("A", "E")}

    def test_out_of_scope_is_reported_by_probe_but_never_retired(self, tmp_path: Path) -> None:
        """의도한 차이 — 프로브는 범위 밖 DB 엣지도 '잔존'으로 보고하지만 은퇴는 원자 코드 범위만."""
        rows = [_row("A", "OLD-CONCEPT")]
        plan = plan_retirement(rows, set(), frozenset({"A"}))
        assert plan.stale == () and plan.out_of_scope == 1


# ──────────────────────────────────────────────────────────────────────────
# 3. 실제 정본 재현(prod 실측 순환 위험 5쌍)
# ──────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _CORPUS.exists(), reason="원자 코퍼스 미존재")
class TestRealCanon:
    def _canon(self) -> tuple[set[tuple[str, str]], frozenset[str]]:
        payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
        pairs = {
            (e["from_code"], e["to_code"])
            for e in payload["edges"]
            if e["relation"] == "prerequisite"
        }
        return pairs, frozenset(c["code"] for c in payload["concepts"])

    def test_prod_cycle_risk_pairs_are_reversed_canon_edges(self) -> None:
        pairs, _scope = self._canon()
        for a, b in _PROD_CYCLE_RISK_OLD:
            assert (b, a) in pairs and (a, b) not in pairs, (a, b)

    def test_old_directions_block_the_load_and_retirement_unblocks_it(self) -> None:
        pairs, scope = self._canon()
        db = [_row(a, b) for a, b in sorted(pairs)] + [_row(a, b) for a, b in _PROD_CYCLE_RISK_OLD]
        plan = plan_retirement(db, pairs, scope)
        assert sorted(r.pair for r in plan.stale) == sorted(_PROD_CYCLE_RISK_OLD)
        empty = RetirePlan(stale=(), cms_kept=(), in_scope_prerequisite=0, out_of_scope=0)
        assert cycle_after_retirement(db, empty, pairs) is not None  # 지금 적재가 막히는 이유
        assert cycle_after_retirement(db, plan, pairs) is None  # 은퇴하면 통과

    def test_a_cms_owned_old_direction_still_blocks(self) -> None:
        """CMS 소유는 지키므로 순환이 남는다 — plan이 그것을 보고해야 한다(조용히 통과 금지)."""
        pairs, scope = self._canon()
        a, b = _PROD_CYCLE_RISK_OLD[0]
        db = [_row(x, y) for x, y in sorted(pairs)] + [_row(a, b, cms=True)]
        plan = plan_retirement(db, pairs, scope)
        assert plan.stale == () and [r.pair for r in plan.cms_kept] == [(a, b)]
        assert cycle_after_retirement(db, plan, pairs) is not None
        assert "RETIRE_PLAN_OK=False" in render_plan(
            plan, cycle_after_retirement(db, plan, pairs), cycle_without_retire=None
        )


# ──────────────────────────────────────────────────────────────────────────
# 4. 트랜잭션 순서 — 가짜 엔진
# ──────────────────────────────────────────────────────────────────────────
def _compile(statement: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


class _Res:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _CodeRow:
    def __init__(self, code: str, concept_id: uuid.UUID) -> None:
        self.code = code
        self.concept_id = concept_id


class _ReadRow:
    def __init__(self, e: dict[str, Any]) -> None:
        self.edge_id = e["edge_id"]
        self.from_code = e["from_code"]
        self.to_code = e["to_code"]
        self.relation_subtype = e["subtype"]
        self.edge_type = e["edge_type"]
        self.cms_owned = e["cms"]


class _Conn:
    def __init__(self, eng: _Eng) -> None:
        self.eng = eng

    def __enter__(self) -> _Conn:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.eng.exited_with = exc_type

    def rollback(self) -> None:
        self.eng.rolled_back = True

    def execute(self, statement: Any, parameters: Any = None) -> _Res:
        sql = _compile(statement)
        self.eng.log.append(sql)
        if sql.startswith("SET TRANSACTION"):
            return _Res([])
        if "pg_advisory_xact_lock" in sql:
            return _Res([])
        if sql.startswith("DELETE"):
            ids = set()
            for value in statement.compile().params.values():
                if isinstance(value, (list, tuple)):
                    ids.update(value)
            gone = [e for e in self.eng.edges if e["edge_id"] in ids and not e["cms"]]
            gone = gone[: self.eng.delete_limit] if self.eng.delete_limit is not None else gone
            for e in gone:
                self.eng.edges.remove(e)
            return _Res([(e["edge_id"],) for e in gone])
        if sql.startswith("INSERT"):
            return _Res([("written",)])
        if "AS from_code" in sql:
            return _Res([_ReadRow(e) for e in self.eng.edges])
        if "concept_edge" in sql:  # assert_acyclic_with_db — 지금 DB의 선수 엣지 UUID 쌍
            return _Res(
                [(self.eng.ids[e["from_code"]], self.eng.ids[e["to_code"]]) for e in self.eng.edges]
            )
        if "concept.code" in sql:
            return _Res([_CodeRow(c, u) for c, u in self.eng.ids.items()])
        return _Res([])


class _Eng:
    def __init__(self, codes: list[str], edges: list[tuple[str, str, bool]]) -> None:
        self.ids = {c: uuid.uuid4() for c in codes}
        self.edges = [
            {
                "edge_id": uuid.uuid4(),
                "from_code": a,
                "to_code": b,
                "subtype": "원본",
                "edge_type": EdgeType.PREREQUISITE,
                "cms": cms,
            }
            for a, b, cms in edges
        ]
        self.log: list[str] = []
        self.delete_limit: int | None = None
        self.rolled_back = False
        self.exited_with: type[BaseException] | None = None

    def begin(self) -> _Conn:
        return _Conn(self)

    def connect(self) -> _Conn:
        return _Conn(self)


def _rec(a: str, b: str) -> AtomBackendEdgeRecord:
    return AtomBackendEdgeRecord(
        from_code=a,
        to_code=b,
        edge_type=EdgeType.PREREQUISITE,
        edge_strength=0.8,
        relation_subtype="원본",
    )


_SCOPE = frozenset({"A", "B", "C"})


def _first(log: list[str], needle: str) -> int:
    return next(i for i, s in enumerate(log) if needle in s)


class TestStoreTransaction:
    def test_apply_deletes_after_lock_and_before_cycle_check_and_insert(self) -> None:
        eng = _Eng(["A", "B", "C"], [("A", "B", False), ("C", "B", False)])  # 정본은 B→C
        store = AtomBackendEdgeStore(engine=eng)  # type: ignore[arg-type]
        loaded, _ = store.populate(
            [_rec("A", "B"), _rec("B", "C")], retire_mode=RETIRE_APPLY, retire_scope=_SCOPE
        )
        assert loaded == 2
        log = eng.log
        assert _first(log, "pg_advisory_xact_lock") < _first(log, "AS from_code")
        assert _first(log, "AS from_code") < _first(log, "DELETE") < _first(log, "INSERT")
        assert store.last_retire is not None
        assert (store.last_retire.stale_found, store.last_retire.retired) == (1, 1)
        assert [(e["from_code"], e["to_code"]) for e in eng.edges] == [("A", "B")]

    def test_report_mode_counts_but_does_not_delete_and_the_cycle_guard_still_refuses(self) -> None:
        from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError

        eng = _Eng(["A", "B", "C"], [("A", "B", False), ("C", "B", False)])
        store = AtomBackendEdgeStore(engine=eng)  # type: ignore[arg-type]
        with pytest.raises(PrerequisiteCycleError):
            store.populate(
                [_rec("A", "B"), _rec("B", "C")], retire_mode=RETIRE_REPORT, retire_scope=_SCOPE
            )
        assert not any(s.startswith("DELETE") for s in eng.log)
        assert not any(s.startswith("INSERT") for s in eng.log)
        assert store.last_retire is not None
        assert (store.last_retire.stale_found, store.last_retire.retired) == (1, 0)

    def test_delete_count_mismatch_raises_before_any_insert(self) -> None:
        eng = _Eng(["A", "B", "C"], [("A", "C", False), ("C", "A", False)])
        eng.delete_limit = 1  # 계획 2건 중 1건만 지워졌다(동시 편집 흉내)
        store = AtomBackendEdgeStore(engine=eng)  # type: ignore[arg-type]
        with pytest.raises(StaleEdgeRetireError):
            store.populate([_rec("A", "B")], retire_mode=RETIRE_APPLY, retire_scope=_SCOPE)
        assert not any(s.startswith("INSERT") for s in eng.log)
        assert eng.exited_with is StaleEdgeRetireError  # 트랜잭션 블록이 예외로 끝났다 → 롤백

    def test_cms_owned_stale_row_is_never_in_the_delete(self) -> None:
        eng = _Eng(["A", "B", "C"], [("C", "A", True), ("C", "B", False)])
        store = AtomBackendEdgeStore(engine=eng)  # type: ignore[arg-type]
        store.populate([_rec("A", "B")], retire_mode=RETIRE_APPLY, retire_scope=_SCOPE)
        assert store.last_retire is not None
        assert (store.last_retire.retired, store.last_retire.cms_kept) == (1, 1)
        assert [(e["from_code"], e["to_code"]) for e in eng.edges] == [("C", "A")]
        delete_sql = next(s for s in eng.log if s.startswith("DELETE"))
        assert "cms_edited_at IS NULL" in delete_sql and "edge_type" in delete_sql

    def test_no_scope_means_no_read_and_no_delete(self) -> None:
        eng = _Eng(["A", "B", "C"], [("C", "B", False)])
        store = AtomBackendEdgeStore(engine=eng)  # type: ignore[arg-type]
        store.populate([_rec("A", "B")], retire_mode=RETIRE_APPLY)
        assert not any("AS from_code" in s or s.startswith("DELETE") for s in eng.log)
        assert store.last_retire is None

    def test_plan_mode_is_not_a_write_path(self) -> None:
        store = AtomBackendEdgeStore(engine=_Eng(["A"], []))  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            store.populate([_rec("A", "B")], retire_mode=RETIRE_PLAN, retire_scope=_SCOPE)


# ──────────────────────────────────────────────────────────────────────────
# 5. 배선 — 적재 함수·plan 함수·CLI
# ──────────────────────────────────────────────────────────────────────────
class TestWiring:
    def test_backbone_passes_mode_and_scope_and_reports_counts(self, tmp_path: Path) -> None:
        from whymath_backend.l1.atom_graph.populate import populate_atom_backbone

        graph = _write_graph(tmp_path / "g.json", ["A", "B", "C"], [("A", "B", "원본")])
        seen: dict[str, Any] = {}

        class _Edge(AtomBackendEdgeStore):
            def populate(self, records: Any, **kwargs: Any) -> tuple[int, list[str]]:
                seen.update(kwargs)
                self.last_retire = None
                from whymath_backend.l1.atom_graph.atom_edge_retire import RetireOutcome

                self.last_retire = RetireOutcome(mode="apply", stale_found=3, retired=3, cms_kept=1)
                return len(records), []

        class _Concepts:
            def upsert(self, _record: Any, **_kwargs: Any) -> bool:
                return True

            def resolve_parents(self, records: Any) -> tuple[int, list[str]]:
                return len(records), []

        report = populate_atom_backbone(
            graph,
            concept_store=_Concepts(),  # type: ignore[arg-type]
            edge_store=_Edge(engine=object()),  # type: ignore[arg-type]
            retire_mode=RETIRE_APPLY,
        )
        assert seen["retire_mode"] == RETIRE_APPLY
        assert seen["retire_scope"] == frozenset({"A", "B", "C"})
        assert (report.stale_edges_found, report.edges_retired, report.stale_cms_kept) == (3, 3, 1)

    def test_backbone_rejects_plan_mode(self, tmp_path: Path) -> None:
        from whymath_backend.l1.atom_graph.populate import populate_atom_backbone

        graph = _write_graph(tmp_path / "g.json", ["A"], [])
        with pytest.raises(ValueError):
            populate_atom_backbone(graph, retire_mode=RETIRE_PLAN)

    def test_plan_function_writes_nothing_and_reads_inside_a_read_only_transaction(
        self, tmp_path: Path
    ) -> None:
        from whymath_backend.l1.atom_graph.populate import plan_atom_edge_retirement

        graph = _write_graph(
            tmp_path / "g.json", ["A", "B", "C"], [("A", "B", "원본"), ("B", "C", "원본")]
        )
        eng = _Eng(["A", "B", "C"], [("A", "B", False), ("C", "B", False)])
        result = plan_atom_edge_retirement(graph, engine=eng)
        assert eng.log[0].startswith("SET TRANSACTION READ ONLY")
        assert not any(s.startswith(("DELETE", "INSERT", "UPDATE")) for s in eng.log)
        assert eng.rolled_back
        assert [r.pair for r in result.plan.stale] == [("C", "B")]
        assert result.cycle_without_retire is not None and result.cycle_after_retire is None

    def _cli(self, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
        import sys

        from whymath_backend.l1.atom_graph import populate as populate_module

        monkeypatch.setattr(sys, "argv", ["populate", *argv])
        populate_module._main()

    def test_cli_plan_exits_by_cycle_verdict_and_never_loads(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from whymath_backend.l1.atom_graph import populate as populate_module

        def _no_load(*_a: Any, **_k: Any) -> Any:
            raise AssertionError("plan 모드가 적재를 불렀다")

        for cycle, code in ((None, 0), (["A", "B", "A"], 1)):
            empty = RetirePlan(stale=(), cms_kept=(), in_scope_prerequisite=0, out_of_scope=0)
            monkeypatch.setattr(populate_module, "populate_atom_backbone", _no_load)
            monkeypatch.setattr(
                populate_module,
                "plan_atom_edge_retirement",
                lambda _g, _c=cycle, _e=empty: populate_module.AtomEdgeRetirementPlan(
                    plan=_e, cycle_after_retire=_c, cycle_without_retire=None
                ),
            )
            with pytest.raises(SystemExit) as exc:
                self._cli(monkeypatch, ["--retire-stale-edges", "plan"])
            assert exc.value.code == code
            assert f"RETIRE_PLAN_OK={cycle is None}" in capsys.readouterr().out

    def test_cli_turns_a_cycle_refusal_into_exit_1_with_a_hint(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from whymath_backend.l1.atom_graph import populate as populate_module
        from whymath_backend.l1.concept_graph.prerequisite_guard import PrerequisiteCycleError

        def _refuse(*_a: Any, **_k: Any) -> Any:
            raise PrerequisiteCycleError(["A", "B", "A"])

        monkeypatch.setattr(populate_module, "populate_atom_backbone", _refuse)
        with pytest.raises(SystemExit) as exc:
            self._cli(monkeypatch, [])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "--retire-stale-edges plan" in out and "A → B → A" in out

    def test_cli_default_mode_is_report_and_apply_is_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from whymath_backend.l1.atom_graph import populate as populate_module

        captured: list[str] = []

        def _fake(_g: Path, **kwargs: Any) -> Any:
            captured.append(kwargs["retire_mode"])
            return populate_module.AtomBackbonePopulateReport(
                concepts_loaded=0,
                parents_skipped=0,
                edges_loaded=0,
                edges_skipped=0,
                visual_styles_loaded=0,
                visualization_loaded=0,
                atom_nodes_loaded=0,
            )

        monkeypatch.setattr(populate_module, "populate_atom_backbone", _fake)
        self._cli(monkeypatch, [])
        self._cli(monkeypatch, ["--retire-stale-edges", "apply"])
        assert captured == [RETIRE_REPORT, RETIRE_APPLY]
