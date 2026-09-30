#!/usr/bin/env python3
"""P3-01 실측 교차검증 — 적재된 DB에서 후보 범위의 런타임 수치를 읽어 파일 기준 실측과 대조한다.

지위
----
`p3_01_scope_inventory.py`(파일 기준 실측)의 짝이다. 일회성 분석 스크립트(테스트 불요). 결과 문서:
`docs/reviews/p3_01_scope_candidates_2026-09-30.md` §부록.

**읽기 전용** — SELECT만 실행한다(쓰기·DDL 0). 그래서 운영 DB(whymath-pg)에 대고 돌려도 안전하며,
그 경우 이 스크립트의 출력이 곧 "파일 실측 ↔ 운영 적재 상태" 드리프트 판정이다.

무엇을 대조하나
---------------
전역: atom_node·concept(원자 code 행)·achievement_standard·misconception_catalog(M/ATOM 분리)·
skill_node·problem_type_node·problem·problem_concept·problem_concept가 닿는 개념 수.
후보별(런타임 관점 — 런타임은 문항의 성취기준을 problem_concept → atom_node.standard_codes로 얻는다,
`api/gating.py::_fetch_achievement_codes`):
  리프 원자 수 · 스킬 보유 원자 · 문항 연결 원자 · 런타임 문항 수 · M-id 수.

입력
----
DB URL = `--dsn` 또는 env `WHYMATH_DATABASE_URL`(asyncpg URL이면 psycopg로 바꿔 쓴다).
파일 실측 JSON = `--inventory`(기본 data/audit/p3_01_scope_inventory.json — 먼저 inventory 실행).

종료 코드: 0=전 항목 일치 · 3=불일치(드리프트 — 표에 표시) · 1=측정 실패(접속·쿼리 오류 —
예외 타입명 출력) · 2=입력 부재.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_INV = REPO / "data" / "audit" / "p3_01_scope_inventory.json"


def _dsn(raw: str) -> str:
    # asyncpg/psycopg 접두를 psycopg(libpq) DSN으로 정규화 — 시크릿은 출력하지 않는다.
    for pre in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if raw.startswith(pre):
            return "postgresql://" + raw[len(pre) :]
    return raw


GLOBAL_SQL: dict[str, str] = {
    "atom_node": "select count(*) from atom_node",
    "atom_node_leaf": "select count(*) from atom_node where level='세부개념'",
    "atom_leaf_with_skill": (
        "select count(*) from atom_node where level='세부개념' "
        "and cardinality(behavior_skills)>0"
    ),
    "concept_atom_rows": "select count(*) from concept c join atom_node a on a.code=c.code",
    "achievement_standard": "select count(*) from achievement_standard",
    "achievement_standard_2022": (
        "select count(*) from achievement_standard where curriculum_revision='2022 개정'"
    ),
    "misconception_mid": (
        "select count(*) from misconception_catalog where mis_id not like 'ATOM:%'"
    ),
    "misconception_atom_stub": (
        "select count(*) from misconception_catalog where mis_id like 'ATOM:%'"
    ),
    "skill_node": "select count(*) from skill_node",
    "problem_type_node": "select count(*) from problem_type_node",
    "problem": "select count(*) from problem",
    "problem_concept": "select count(*) from problem_concept",
    "problems_with_concept": "select count(distinct problem_id) from problem_concept",
    "concepts_hit_by_problems": "select count(distinct concept_id) from problem_concept",
    "problems_with_distractor": (
        "select count(*) from problem where distractor_map is not null "
        "and jsonb_typeof(distractor_map)='array' and jsonb_array_length(distractor_map)>0"
    ),
}

# 파일 실측 JSON global 키와의 대응(파일 쪽에 같은 의미의 값이 있는 것만 대조)
GLOBAL_FILE_KEY: dict[str, str] = {
    "atom_node": "atoms_total_nodes",
    "atom_node_leaf": "atoms_leaf",
    "atom_leaf_with_skill": "atoms_with_skill",
    "achievement_standard": "standards_rows_total",
    "achievement_standard_2022": "standards_2022",
    "misconception_mid": "misconceptions_mid",
    "misconception_atom_stub": "misconceptions_atom_stub_equiv",
    "skill_node": "skills",
    "problem_type_node": "problem_types",
    "problem": "problems_total",
    "problems_with_concept": "problems_concept_resolved",
    "concepts_hit_by_problems": "distinct_primary_atoms_hit_by_problems",
    "problems_with_distractor": "problems_with_mid",
}

CAND_SQL: dict[str, str] = {
    "concepts_atom": (
        "select count(*) from atom_node where level='세부개념' and standard_codes && %(codes)s"
    ),
    "atoms_with_skill": (
        "select count(*) from atom_node where level='세부개념' and standard_codes && %(codes)s "
        "and cardinality(behavior_skills)>0"
    ),
    "atoms_with_problem": (
        "select count(distinct a.code) from atom_node a join concept c on c.code=a.code "
        "join problem_concept pc on pc.concept_id=c.concept_id "
        "where a.level='세부개념' and a.standard_codes && %(codes)s"
    ),
    "problems_runtime": (
        "select count(distinct pc.problem_id) from atom_node a join concept c on c.code=a.code "
        "join problem_concept pc on pc.concept_id=c.concept_id "
        "where a.level='세부개념' and a.standard_codes && %(codes)s"
    ),
    "misconceptions_mid": (
        "select count(*) from misconception_catalog where mis_id not like 'ATOM:%%' "
        "and standard_code = any(%(codes)s)"
    ),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P3-01 DB 교차검증(읽기 전용)")
    ap.add_argument("--dsn", default=os.environ.get("WHYMATH_DATABASE_URL"))
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INV)
    args = ap.parse_args(argv)
    if not args.dsn:
        print("DB URL 없음 — --dsn 또는 WHYMATH_DATABASE_URL", file=sys.stderr)
        return 2
    if not args.inventory.exists():
        print(
            f"파일 실측 JSON 없음: {args.inventory} — p3_01_scope_inventory.py 먼저 실행",
            file=sys.stderr,
        )
        return 2
    inv = json.loads(args.inventory.read_text(encoding="utf-8"))
    cands: dict[str, Any] = inv.get("candidates") or {}
    if not cands:
        print("파일 실측 JSON에 candidates 0건 — 스캔 0건은 실패", file=sys.stderr)
        return 1

    try:
        import psycopg
    except Exception as exc:  # noqa: BLE001
        print(f"측정 실패: psycopg import {type(exc).__name__}", file=sys.stderr)
        return 1

    drift = False
    try:
        with psycopg.connect(_dsn(args.dsn), connect_timeout=15) as conn, conn.cursor() as cur:
            cur.execute("set statement_timeout = '60s'")
            cur.execute("set default_transaction_read_only = on")
            print("## 전역 — DB vs 파일\n")
            print("| 항목 | DB | 파일 | 일치 |")
            print("|---|---|---|---|")
            for key, sql in GLOBAL_SQL.items():
                cur.execute(sql)
                db_v = cur.fetchone()[0]
                fk = GLOBAL_FILE_KEY.get(key)
                f_v = inv["global"].get(fk) if fk else None
                ok = "-" if f_v is None else ("O" if db_v == f_v else "X")
                if ok == "X":
                    drift = True
                print(f"| {key} | {db_v} | {f_v if f_v is not None else '-'} | {ok} |")

            print("\n## 후보별 — DB(런타임) vs 파일\n")
            print("| 후보 | 항목 | DB | 파일 | 일치 |")
            print("|---|---|---|---|---|")
            for ck, cm in cands.items():
                codes = cm["codes"]
                for key, sql in CAND_SQL.items():
                    cur.execute(sql, {"codes": codes})
                    db_v = cur.fetchone()[0]
                    f_v = cm.get(key)
                    ok = "O" if db_v == f_v else "X"
                    if ok == "X":
                        drift = True
                    print(f"| {ck} | {key} | {db_v} | {f_v} | {ok} |")
    except Exception as exc:  # noqa: BLE001 — 측정 실패는 타입명과 함께 exit 1(0건 통과 위장 금지)
        print(f"측정 실패: {type(exc).__name__}: {str(exc)[:300]}", file=sys.stderr)
        return 1
    verdict = "드리프트 있음(exit 3)" if drift else "전 항목 일치(exit 0)"
    print(f"\n[p3_01_db_crosscheck] 판정: {verdict}")
    return 3 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
