"""OPS-139 — 패리티 프로브의 *보호 실재* 검증: 절 하나를 지우면 이 스위트가 RED가 되는가.

정상 입력에서 초록인 것은 보호의 증거가 아니다 — *모든* 입력에서 초록인 가드도 같은 화면을 낸다
(CLAUDE.md 「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」). 그래서 판정 모듈의 소스를 메모리에서
한 절씩 변형(뮤테이션)해 로드하고, 같은 시나리오 묶음(battery)을 돌려 **그 변형이 RED가 되는지** 본다.

하네스의 약속 세 가지(이 파일이 위장이 되지 않도록):
  ① **주입이 실제로 적용됐다** — 치환 대상이 정확히 1건이고 `mutated != original`임을 단언한다.
     주입이 조용히 실패하면 정상 모듈에 대해 시나리오가 돌아 "N passed"가 검출처럼 보인다
     (2026-09-06 사고). 같은 종류 뮤테이션 중 *일부만* RED면 가드가 아니라 하네스를 의심한다.
  ② **원복이 바이트 동일하다** — 파일은 한 번도 쓰지 않는다(메모리 로드). 그래도 전후 sha256을 단언한다.
  ③ **각 뮤테이션이 의도한 절을 밟았다** — RED 여부만이 아니라 *어느 시나리오가* RED인지 기대 집합과
     대조한다. 엉뚱한 시나리오가 RED가 되는 것은 의도한 절이 검증되지 않았다는 뜻이다(전건 RED는
     커버리지의 증거가 아니다).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_SRC = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "backend"
    / "whymath_backend"
    / "ops"
    / "atom_graph_prod_parity.py"
)

_CONCEPTS = ["C1", "C2", "C3", "C4", "C5"]
_EDGES: list[tuple[str, str, str | None]] = [
    ("C1", "C2", "원본"),
    ("C2", "C3", "소단원내"),
    ("C3", "C4", "소단원내"),
    ("C4", "C5", "학년간"),
    ("C1", "C3", "소단원간"),
]

Scenario = Callable[[Any, Path], None]


# ──────────────────────────────────────────────────────────────────────────
# 시나리오 묶음 — 모듈 `m`을 인자로 받아 판정이 기대와 같은지 단언한다
# ──────────────────────────────────────────────────────────────────────────
def _write_graph(
    tmp_path: Path,
    edges: list[tuple[str, str, str | None]] = _EDGES,
    concepts: list[str] = _CONCEPTS,
) -> Path:
    path = tmp_path / "graph.json"
    path.write_text(
        json.dumps(
            {
                "concepts": [{"code": c, "name": f"n{c}", "level": "세부개념"} for c in concepts],
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


def _payload(
    edges: list[tuple[str, str, str | None]] = _EDGES,
    *,
    concepts: list[str] = _CONCEPTS,
    atom_nodes: int = 5,
    cms: list[tuple[str, str]] | None = None,
    extra: list[list[Any]] | None = None,
) -> dict[str, Any]:
    cms = cms or []
    rows: list[list[Any]] = [[f, t, s, "PREREQUISITE", (f, t) in cms] for f, t, s in edges]
    rows.extend(extra or [])
    return {"concepts": concepts, "atom_nodes": atom_nodes, "edges": rows}


def _pair(m: Any, tmp_path: Path, payload: dict[str, Any]) -> tuple[Any, Any]:
    canonical = m.compute_canonical(_write_graph(tmp_path))
    return canonical, m.parse_db_payload(payload, canonical)


def _counts_only(m: Any, *, db_total: int, db_dist: dict[str, int]) -> tuple[Any, Any]:
    """수-전용 입력(집합 None) — 집합 지문이 가려 주는 절을 고립해서 밟는다."""
    canonical = m.CanonicalSnapshot(
        edge_total=5,
        edge_by_subtype={"원본": 1, "소단원내": 2, "학년간": 1, "소단원간": 1},
        concept_total=5,
        atom_node_total=5,
        edges=None,
        concept_codes=frozenset(_CONCEPTS),
    )
    db = m.DbSnapshot(
        edge_total=db_total,
        edge_by_subtype=db_dist,
        concept_total=5,
        concept_missing=0,
        atom_node_total=5,
        edges=None,
    )
    return canonical, db


def sc_match(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload())
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.MATCH and verdict.exit_code == 0


def sc_db_less_with_sets(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload(_EDGES[:3]))
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.DRIFT and verdict.exit_code == 1
    assert verdict.direction == m.DIR_DB_LESS
    assert any(f.axis == "edge_total" for f in verdict.findings)


def sc_db_more_with_sets(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload([*_EDGES, ("C2", "C5", "소단원간")]))
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.DRIFT
    assert verdict.direction == m.DIR_DB_MORE


def sc_counts_only_total(m: Any, tmp_path: Path) -> None:
    canonical, db = _counts_only(
        m, db_total=3, db_dist={"원본": 1, "소단원내": 1, "학년간": 1, "소단원간": 0}
    )
    verdict = m.judge(canonical, db)
    assert verdict.status == m.DRIFT
    assert verdict.direction == m.DIR_DB_LESS


def sc_counts_only_distribution(m: Any, tmp_path: Path) -> None:
    canonical, db = _counts_only(
        m, db_total=5, db_dist={"원본": 0, "소단원내": 3, "학년간": 1, "소단원간": 1}
    )
    verdict = m.judge(canonical, db)
    assert verdict.status == m.DRIFT
    assert verdict.direction == m.DIR_SAME_TOTAL


def sc_same_counts_different_edge(m: Any, tmp_path: Path) -> None:
    swapped = [*_EDGES[1:], ("C1", "C5", "원본")]
    canonical, db = _pair(m, tmp_path, _payload(swapped))
    assert canonical.edge_total == db.edge_total
    assert canonical.edge_by_subtype == db.edge_by_subtype
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.DRIFT
    assert verdict.direction == m.DIR_MIXED


def sc_unknown(m: Any, tmp_path: Path) -> None:
    canonical = m.compute_canonical(_write_graph(tmp_path))
    verdict = m.evaluate(canonical, None, unknown_reason="docker 없음")
    assert verdict.status == m.UNKNOWN and verdict.exit_code == 2
    assert verdict.reason == "docker 없음"


def sc_exit_codes_distinct(m: Any, tmp_path: Path) -> None:
    codes = {m.Verdict(status=s).exit_code for s in (m.MATCH, m.DRIFT, m.UNKNOWN)}
    assert codes == {0, 1, 2}
    assert (
        m.Verdict(status="SOMETHING_ELSE").exit_code == 2
    )  # 모르는 상태는 MATCH·DRIFT로 접히지 않는다


def sc_zero_edges(m: Any, tmp_path: Path) -> None:
    with pytest.raises(m.CanonicalError):
        m.compute_canonical(_write_graph(tmp_path, edges=[]))


def sc_orphan_skip(m: Any, tmp_path: Path) -> None:
    canonical = m.compute_canonical(
        _write_graph(tmp_path, edges=[*_EDGES, ("C1", "GHOST", "원본")])
    )
    assert canonical.edge_total == 5 and canonical.orphan_skipped == 1


def sc_cms_both_sides(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload(cms=[("C2", "C3")]))
    assert m.evaluate(canonical, db).status == m.MATCH


def sc_non_prerequisite(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload(extra=[["C1", "C5", None, "COMPOSED_OF", False]]))
    assert m.evaluate(canonical, db).status == m.MATCH


def sc_atom_node(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload(atom_nodes=0))
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.DRIFT
    assert [f.axis for f in verdict.findings] == ["atom_node_total"]


def sc_concept_missing(m: Any, tmp_path: Path) -> None:
    canonical, db = _pair(m, tmp_path, _payload(concepts=["C1", "C2", "C3", "C4"]))
    verdict = m.evaluate(canonical, db)
    assert verdict.status == m.DRIFT
    assert [f.axis for f in verdict.findings] == ["concept_missing"]


def sc_guard_rejects_second_statement(m: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        m.assert_read_only_sql("SELECT 1; DELETE FROM concept_edge")


def sc_guard_rejects_write_keyword(m: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        m.assert_read_only_sql("SELECT (DELETE FROM concept_edge)")


def sc_server_side_read_only(m: Any, tmp_path: Path) -> None:
    args = m._psql_args("c", "u", "d")
    assert "PGOPTIONS=-c default_transaction_read_only=on" in args
    assert args[-2:] == ["-f", "-"]


def sc_psql_nonzero_is_unknown_even_with_parseable_stdout(m: Any, tmp_path: Path) -> None:
    """psql이 비-0으로 끝났다면 stdout이 멀쩡히 파싱돼도 *신뢰하지 않는다* — 부분 성공 ≠ 정상."""

    def runner(args: Any, stdin: bytes, timeout: float) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 3, b'{"cms_column": true}', b"FATAL: boom")

    with pytest.raises(m.DbReadError):
        m.read_db_payload(runner=runner)


def sc_malformed_payload_is_unknown(m: Any, tmp_path: Path) -> None:
    canonical = m.compute_canonical(_write_graph(tmp_path))
    with pytest.raises(m.DbReadError):
        m.parse_db_payload({"concepts": [], "atom_nodes": 0}, canonical)


_BATTERY: dict[str, Scenario] = {
    fn.__name__: fn
    for fn in (
        sc_match,
        sc_db_less_with_sets,
        sc_db_more_with_sets,
        sc_counts_only_total,
        sc_counts_only_distribution,
        sc_same_counts_different_edge,
        sc_unknown,
        sc_exit_codes_distinct,
        sc_zero_edges,
        sc_orphan_skip,
        sc_cms_both_sides,
        sc_non_prerequisite,
        sc_atom_node,
        sc_concept_missing,
        sc_guard_rejects_second_statement,
        sc_guard_rejects_write_keyword,
        sc_server_side_read_only,
        sc_psql_nonzero_is_unknown_even_with_parseable_stdout,
        sc_malformed_payload_is_unknown,
    )
}


def _run_battery(m: Any, tmp_root: Path) -> set[str]:
    """모든 시나리오를 돌려 *실패한 시나리오 이름*을 돌려준다(예외 전부 = 그 시나리오 RED)."""
    failed: set[str] = set()
    for name, scenario in _BATTERY.items():
        scenario_dir = tmp_root / name
        scenario_dir.mkdir()
        try:
            scenario(m, scenario_dir)
        except BaseException:  # noqa: BLE001 — 어떤 실패든 그 시나리오의 RED 신호다
            failed.add(name)
    return failed


# ──────────────────────────────────────────────────────────────────────────
# 뮤테이션 하네스 — 메모리 로드·적용 단언
# ──────────────────────────────────────────────────────────────────────────
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_source(source: str, name: str) -> types.ModuleType:
    """소스 문자열을 모듈로 로드한다 — 파일을 쓰지 않으므로 원복이 구조적으로 필요 없다."""
    module = types.ModuleType(name)
    module.__file__ = str(_SRC)
    sys.modules[name] = module  # dataclass가 문자열 어노테이션을 해석할 때 모듈을 찾는다
    try:
        exec(compile(source, str(_SRC), "exec"), module.__dict__)  # noqa: S102 — 테스트 하네스
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _mutate(original: str, old: str, new: str) -> str:
    """치환 대상이 정확히 1건임을 단언하고 적용한다 — 안 들어간 주입이 '검출'로 읽히지 않게."""
    assert (
        original.count(old) == 1
    ), f"치환 대상이 정확히 1건이 아니다({original.count(old)}건): {old!r}"
    mutated = original.replace(old, new)
    assert mutated != original, "뮤테이션이 적용되지 않았다"
    return mutated


# (id, 치환 전, 치환 후, 이 뮤테이션이 RED로 만들어야 하는 시나리오 집합)
_MUTATIONS: list[tuple[str, str, str, set[str]]] = [
    (
        "M1-edge-total-axis-removed",
        "edge_dir = _direction_of(canonical.edge_total, db.edge_total)",
        'edge_dir = ""',
        {"sc_counts_only_total", "sc_db_less_with_sets"},
    ),
    (
        "M2-subtype-axis-removed",
        "        if exp != act:",
        "        if False:",
        {"sc_counts_only_distribution"},
    ),
    (
        "M3-direction-judgement-removed",
        'return DIR_DB_LESS if actual < expected else DIR_DB_MORE if actual > expected else ""',
        'return ""',
        # 개념 부재 축의 방향은 `_direction_of`가 아니라 DIR_DB_LESS 상수를 직접 쓴다 — 이 뮤테이션이
        # 닿는 축은 엣지 총수·atom_node뿐이다(기대를 넓히면 밟지 않는 절을 밟았다고 주장하게 된다).
        {"sc_counts_only_total", "sc_db_less_with_sets", "sc_atom_node"},
    ),
    (
        "M4-unknown-folded-into-match",
        "return Verdict(status=UNKNOWN, reason=unknown_reason",
        "return Verdict(status=MATCH, reason=unknown_reason",
        {"sc_unknown"},
    ),
    (
        "M5-unknown-folded-into-drift",
        "return Verdict(status=UNKNOWN, reason=unknown_reason",
        "return Verdict(status=DRIFT, reason=unknown_reason",
        {"sc_unknown"},
    ),
    (
        "M6-edge-set-fingerprint-removed",
        "        if only_canon or only_db:",
        "        if False:",
        {"sc_same_counts_different_edge"},
    ),
    (
        "M7-unknown-exit-code-folded-to-drift",
        "{MATCH: _EXIT_MATCH, DRIFT: _EXIT_DRIFT}.get(self.status, _EXIT_UNKNOWN)",
        "{MATCH: _EXIT_MATCH, DRIFT: _EXIT_DRIFT}.get(self.status, _EXIT_DRIFT)",
        {"sc_unknown", "sc_exit_codes_distinct"},
    ),
    (
        "M8-zero-edge-error-removed",
        "    if not by_pair:",
        "    if False:",
        {"sc_zero_edges"},
    ),
    (
        "M9-cms-exclusion-one-sided",
        "return judge(adjust_canonical_for_cms(canonical, db), db, diff_limit=diff_limit)",
        "return judge(canonical, db, diff_limit=diff_limit)",
        {"sc_cms_both_sides"},
    ),
    (
        "M10-atom-node-axis-removed",
        "node_dir = _direction_of(canonical.atom_node_total, db.atom_node_total)",
        'node_dir = ""',
        {"sc_atom_node"},
    ),
    (
        "M11-concept-missing-axis-removed",
        "    if db.concept_missing > 0:",
        "    if False:",
        {"sc_concept_missing"},
    ),
    (
        "M12-set-direction-removed",
        'DIR_DB_LESS if only_canon else ""',
        '""',
        {"sc_db_less_with_sets"},
    ),
    (
        "M13-non-prerequisite-filter-removed",
        "            if str(edge_type) != _PREREQUISITE_DB_VALUE:",
        "            if False:",
        {"sc_non_prerequisite"},
    ),
    (
        "M14-orphan-skip-removed",
        "        if rec.from_code not in concept_codes or rec.to_code not in concept_codes:",
        "        if False:",
        {"sc_orphan_skip"},
    ),
    (
        "M15-multi-statement-guard-removed",
        "    if len(statements) != 1:",
        "    if False:",
        {"sc_guard_rejects_second_statement"},
    ),
    (
        "M16-forbidden-keyword-guard-removed",
        "    if hit:",
        "    if False:",
        {"sc_guard_rejects_write_keyword"},
    ),
    (
        "M17-server-side-read-only-removed",
        '        "PGOPTIONS=-c default_transaction_read_only=on",  # 서버 쪽 쓰기 거부(이중 방어)',
        '        "PGOPTIONS=-c statement_timeout=0",',
        {"sc_server_side_read_only"},
    ),
    (
        "M18-psql-nonzero-trusted",
        "    if done.returncode != 0:",
        "    if False:",
        {"sc_psql_nonzero_is_unknown_even_with_parseable_stdout"},
    ),
    (
        "M19-payload-shape-error-swallowed",
        "        raise DbReadError(\n"
        '            f"DB 응답의 모양이 기대와 다르다({type(exc).__name__}: {str(exc)[:120]})"\n'
        "        ) from exc",
        "        raise KeyboardInterrupt from exc",
        {"sc_malformed_payload_is_unknown"},
    ),
]


class TestBaseline:
    def test_real_module_passes_the_whole_battery(self, tmp_path: Path) -> None:
        """뮤테이션이 RED를 내려면 먼저 *변형 전*이 GREEN이어야 한다 — 대조군."""
        from whymath_backend.ops import atom_graph_prod_parity as real

        assert _run_battery(real, tmp_path) == set()

    def test_unmutated_source_loaded_by_the_harness_also_passes(self, tmp_path: Path) -> None:
        """하네스의 로드 경로 자체가 모듈을 망가뜨리지 않는다 — 안 그러면 모든 뮤테이션이 거짓 RED다."""
        module = _load_source(_SRC.read_text(encoding="utf-8"), "_atom_parity_baseline")
        try:
            assert _run_battery(module, tmp_path) == set()
        finally:
            sys.modules.pop("_atom_parity_baseline", None)

    def test_battery_has_a_scenario_for_every_mutation_expectation(self) -> None:
        """기대 집합이 존재하지 않는 시나리오 이름을 가리키면 그 뮤테이션은 검증되지 않는다."""
        for mutation_id, _old, _new, expected in _MUTATIONS:
            assert expected <= set(_BATTERY), mutation_id
            assert expected, f"{mutation_id}: 기대 RED 시나리오가 비어 있다"


@pytest.mark.parametrize(
    ("mutation_id", "old", "new", "expected_red"),
    _MUTATIONS,
    ids=[m[0] for m in _MUTATIONS],
)
def test_each_mutation_turns_the_intended_scenarios_red(
    mutation_id: str, old: str, new: str, expected_red: set[str], tmp_path: Path
) -> None:
    before = _sha(_SRC)
    original = _SRC.read_text(encoding="utf-8")
    mutated = _mutate(original, old, new)  # ① 주입이 실제로 적용됐다

    name = f"_atom_parity_mutant_{mutation_id.split('-')[0].lower()}"
    module = _load_source(mutated, name)
    try:
        failed = _run_battery(module, tmp_path)
    finally:
        sys.modules.pop(name, None)

    assert failed, f"{mutation_id}: 어느 시나리오도 RED가 아니다 — 이 절은 보호되지 않는다"
    assert expected_red <= failed, (
        f"{mutation_id}: 의도한 시나리오가 RED가 아니다 — 기대 {sorted(expected_red)} · "
        f"실제 RED {sorted(failed)}. 이 절은 픽스처가 밟지 않는다(픽스처를 고칠 일이지 절을 지울 일이 아니다)"
    )
    assert _sha(_SRC) == before, "② 원본 파일이 변했다 — 하네스는 파일을 쓰지 않아야 한다"


def test_mutation_harness_refuses_a_noop_or_ambiguous_injection() -> None:
    """주입이 안 들어가는 경우(0건)·모호한 경우(2건 이상)를 하네스가 스스로 거부하는지 — 하네스의 대조군."""
    with pytest.raises(AssertionError, match="정확히 1건"):
        _mutate("abc", "zzz", "y")
    with pytest.raises(AssertionError, match="정확히 1건"):
        _mutate("aa", "a", "b")
