"""원자 백본 정본(graph.json) ↔ prod DB 패리티 프로브 — OPS-139.

**존재 이유**: 정본(`data/corpus/atom_graph_v1/graph.json`)과 prod DB는 *서로 다른 시점에 바뀌는 두
진실*이라 어긋남이 구조적으로 재발한다. S4-60(PR #1558)이 정본 엣지를 2,210→2,234로 늘렸지만 prod는
별도 적재 동작이 있을 때까지 2,210에 머물렀고, 그 어긋남은 감시가 아니라 PR 본문의 정직한 공백
항목과 사람의 수작업 `count(*)`로만 드러났다. 같은 계열 선례가 SKB-03이다(`atom_node` 적재 구현이
어느 CLI에서도 호출되지 않아 prod에 한 번도 적재된 적이 없었고, 빈 테이블이 정상 동작처럼 보였다).

**판정은 3상태이며 접지 않는다**(`ops/db_host_reachability`와 같은 계약):
  - `MATCH`(exit 0)   — 전 축 일치
  - `DRIFT`(exit 1)   — 하나라도 다름. 방향을 표기한다(DB<정본=미적재 · DB>정본=코퍼스에
      없는 잔존 행)
  - `UNKNOWN`(exit 2) — DB 값을 못 읽었다. 모른다는 아니다가 아니다 — MATCH도 DRIFT도 아니다
  - 입력 오류(exit 3) — 정본을 못 읽었거나 적재 예정 엣지가 0건이다. **스캔 0건은 MATCH가 아니라
    오류다**(공허한 통과 금지)

**총합만 비교하지 않는다**: 총합이 같아도 `relation_subtype` 분포가 다르면 DRIFT이고,
분포까지 같아도
엣지 *집합*(정렬한 `(from_code,to_code,relation_subtype)` 3-튜플의 sha256)이 다르면 DRIFT다. 같은
수의 다른 엣지는 수 비교가 못 잡는다 — 총합 일치는 약한 신호이며 리포트가 그 사실을 명시한다.

**정본 쪽 기대값은 손으로 쓴 상수가 아니다**: 적재기가 쓰는 `load_atom_*_from_graph_json`을 그대로
재사용하고, 적재기와 같은 규칙(양끝 개념이 없는 엣지는 orphan skip·같은 쌍은 UNIQUE upsert로 한 행·
CMS 소유 쌍은 적재가 건너뜀)을 적용해 *적재 예정* 집합을 계산한다. 정본 파일 경로와 sha256 앞 12자를
리포트에 찍어 어느 정본을 기준으로 판정했는지 남긴다.

**CMS 소유 엣지(P3-26)**: CMS가 만든 관계(`cms_edited_at` 있음)는 적재기가 건너뛰는 쌍이다
(`db/cms_edit_marker.upsert_guard`). 그 쌍은 정본 기대값에서도 DB 실측에서도 *양쪽 모두*
뺀다 — 한쪽만
빼면 정당한 CMS 엣지가 "잔존 행"으로, 또는 정본 엣지가 "미적재"로 오판된다. 제외 건수는
리포트에 찍는다
(침묵 제외 금지).

**읽기 전용**: DB는 SELECT만 읽는다. 접속은 호스트 TCP 5433이 아니라 `docker exec psql`을 쓴다 —
OPS-72 실측에서 호스트 5433이 WinNAT 포트 제외로 닫혀도 컨테이너는 정상이었고, 호스트
도달성에 의존하는
도구는 그 고장 때 UNKNOWN이어야 할 자리에서 침묵한다. 세션 수준에서도
`default_transaction_read_only`를
켜 서버가 쓰기를 거부하게 한다(코드가 SELECT만 보낸다는 주장에 더해, 보내도 막히는 이중 방어).
한국어 리터럴은 psql 인자로 넘기지 않는다(Windows cp949 셸이 인자를 깨뜨린다 — SQL은 ASCII 전용이고
`relation_subtype` 한글은 서버가 JSON으로 돌려주는 것을 UTF-8로 디코딩한다).

**한계(명시)**: CI는 prod DB에 닿지 못한다. CI가 하는 일은 판정 함수 단위 테스트와 배선 동결 테스트
(런북이 이 프로브를 실제로 부른다)까지이고, **prod 실행은 Kiki 머신**이다. 이 프로브의 MATCH는 "이
실행 시점의 DB가 이 정본과 같다"는 증거이지 "앞으로도 같다"는 보증이 아니다. 또 엣지 `strength`는
비교하지 않는다(의도적 제외 — 적재기가 재적재 때 강도를 갱신하므로 "적재 누락" 판정과 축이 다르다):
강도만 다른 어긋남은 이 프로브가 못 잡는다.

사용:
    python -m whymath_backend.ops.atom_graph_prod_parity
    python -m whymath_backend.ops.atom_graph_prod_parity --graph
    data/corpus/atom_graph_v1/graph.json
    python -m whymath_backend.ops.atom_graph_prod_parity --json out/atom_parity.json

exit: **0 = MATCH / 1 = DRIFT / 2 = UNKNOWN(DB 못 읽음) / 3 = 정본 입력 오류**
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l1.atom_graph.atom_backend_concept import load_atom_concepts_from_graph_json
from whymath_backend.l1.atom_graph.atom_backend_edge import load_atom_edges_from_graph_json
from whymath_backend.l1.atom_graph.atom_node_projection import load_atom_nodes_from_graph_json

__all__ = [
    "DRIFT",
    "MATCH",
    "UNKNOWN",
    "CanonicalError",
    "CanonicalSnapshot",
    "DbReadError",
    "DbSnapshot",
    "Finding",
    "Verdict",
    "assert_read_only_sql",
    "build_snapshot_sql",
    "compute_canonical",
    "edge_fingerprint",
    "evaluate",
    "judge",
    "main",
    "parse_db_payload",
    "read_db_payload",
    "render_report",
]

_EXIT_MATCH = 0
_EXIT_DRIFT = 1
_EXIT_UNKNOWN = 2
_EXIT_INPUT_ERROR = 3

# ── 상태 어휘 ─────────────────────────────────────────────────────────────
MATCH = "MATCH"
"""전 축 일치 — 이 실행 시점의 DB가 이 정본과 같다."""

DRIFT = "DRIFT"
"""하나라도 다르다 — 방향(DB<정본·DB>정본·혼합)을 함께 표기한다."""

UNKNOWN = "UNKNOWN"
"""DB 값을 못 읽었다 — 모른다. MATCH도 DRIFT도 아니다(3상태를 2상태로 접지 않는다)."""

DIR_DB_LESS = "DB<정본"
"""정본에는 있는데 DB에 없다 — 미적재."""

DIR_DB_MORE = "DB>정본"
"""DB에는 있는데 정본에 없다 — 코퍼스에 없는 잔존 행."""

DIR_MIXED = "혼합"
"""양쪽이 서로에게 없는 것을 갖고 있다 — 미적재와 잔존이 동시에 있다."""

DIR_SAME_TOTAL = "총합 동일·분포/집합 불일치"
"""총합은 같은데 안쪽이 다르다 — 총합만 보는 검사가 놓치는 상쇄 형태."""

# `relation_subtype`이 NULL인 엣지를 분포 표에서 부르는 이름(분포 키는 항상 str이어야
# 정렬·직렬화가 된다).
NULL_SUBTYPE = "(NULL)"

# 엣지 한 개의 정체 — (선수 code, 후행 code, relation_subtype 또는 ""). NULL subtype은 ""로 접는다
# (정본 None과 DB NULL이 같은 값이어야 지문이 같다 — 양쪽이 같은 함수를 거친다).
EdgeKey = tuple[str, str, str]

_PREREQUISITE_DB_VALUE = "PREREQUISITE"  # DB `edge_type_enum` 문자열(적재기가 `.value`로 바인딩)
_DEFAULT_GRAPH = Path("data/corpus/atom_graph_v1/graph.json")
_DEFAULT_DIFF_LIMIT = 20


class CanonicalError(Exception):
    """정본 입력 오류 — 파일 부재·파싱 실패·적재 예정 0건. **MATCH로 접히면 안 되는** 상태다."""


class DbReadError(Exception):
    """DB 값을 못 읽음 — UNKNOWN의 원인. 메시지는 사유(예외 타입명·stderr)를 담는다."""


# ──────────────────────────────────────────────────────────────────────────
# 스냅샷 — 양쪽을 같은 모양으로 맞춘 값(판정 함수는 이것만 본다)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class CanonicalSnapshot:
    """정본 graph.json에서 *적재기와 같은 규칙*으로 계산한 적재 예정 값."""

    edge_total: int
    edge_by_subtype: Mapping[str, int]
    concept_total: int
    atom_node_total: int
    edges: frozenset[EdgeKey] | None  # None = 집합 비교 생략(단위 테스트의 수-전용 입력)
    concept_codes: frozenset[str]
    source_path: str = ""
    source_sha12: str = ""
    orphan_skipped: int = 0  # 양끝 개념 부재로 적재 예정에서 빠진 엣지 수(정본 수 ≠ 적재 수의 이유)


@dataclass(frozen=True, slots=True)
class DbSnapshot:
    """prod DB에서 읽은 값 — `PREREQUISITE`·비-CMS 엣지만 비교 대상이다."""

    edge_total: int
    edge_by_subtype: Mapping[str, int]
    concept_total: int
    concept_missing: int  # 정본 개념 중 DB에 없는 수(0이어야 정상)
    atom_node_total: int
    edges: frozenset[EdgeKey] | None
    cms_owned_pairs: frozenset[tuple[str, str]] = frozenset()  # 양쪽에서 제외하는 CMS 소유 쌍
    db_only_concepts: int = 0  # DB에만 있는 개념 수 — 정보(구 개념그래프·CMS 신규 개념일 수 있다)
    atom_node_table_present: bool = True
    cms_column_present: bool = True
    non_prerequisite_edges: int = 0  # 비교에서 뺀 비-선수 엣지 수 — 정보


@dataclass(frozen=True, slots=True)
class Finding:
    """판정에서 어긋난 한 축 — `direction`이 빈 문자열이면 방향 없는 불일치다."""

    axis: str
    expected: str
    actual: str
    direction: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    """3상태 판정 결과 — 리포트·JSON·종료 코드가 모두 이 값에서 나온다."""

    status: str
    direction: str = ""
    findings: tuple[Finding, ...] = ()
    only_canonical: tuple[EdgeKey, ...] = ()  # 정본에만 있는 엣지 상위 N건(미적재 후보)
    only_db: tuple[EdgeKey, ...] = ()  # DB에만 있는 엣지 상위 N건(잔존 후보)
    only_canonical_total: int = 0
    only_db_total: int = 0
    reason: str = ""  # UNKNOWN의 사유
    notes: tuple[str, ...] = field(default=())

    @property
    def exit_code(self) -> int:
        """MATCH=0 · DRIFT=1 · UNKNOWN=2 — 서로 다른 값이어야 3상태가 접히지 않는다."""
        return {MATCH: _EXIT_MATCH, DRIFT: _EXIT_DRIFT}.get(self.status, _EXIT_UNKNOWN)


# ──────────────────────────────────────────────────────────────────────────
# 순수 코어 — DB·파일·docker를 모르는 판정 로직(테스트가 전 상태를 주입하는 지점)
# ──────────────────────────────────────────────────────────────────────────
def _subtype_key(subtype: str | None) -> str:
    """분포 키 — None·빈 문자열은 `NULL_SUBTYPE`로 접는다(양쪽이 같은 함수를 거친다)."""
    return subtype if subtype else NULL_SUBTYPE


def _edge_key(from_code: str, to_code: str, subtype: str | None) -> EdgeKey:
    return (from_code, to_code, subtype or "")


def distribution(edges: Iterable[EdgeKey]) -> dict[str, int]:
    """엣지 집합 → `relation_subtype`별 수. 정본·DB가 같은 함수를 거쳐 표기를 맞춘다."""
    out: dict[str, int] = {}
    for _from, _to, subtype in edges:
        key = _subtype_key(subtype)
        out[key] = out.get(key, 0) + 1
    return out


def edge_fingerprint(edges: Iterable[EdgeKey]) -> str:
    """정렬한 `(from,to,subtype)` 목록의 sha256 — 정본·DB가 *같은 함수*로 지문을 낸다.

    구분자에 탭·개행을 쓴다(code·subtype에 나올 수 없는 문자) — `a,b`+`c`와 `a`+`b,c`가 같은
    문자열이
    되는 경계 모호성을 막는다.
    """
    body = "\n".join(f"{f}\t{t}\t{s}" for f, t, s in sorted(edges))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compute_canonical(graph_path: Path) -> CanonicalSnapshot:
    """정본 graph.json → *적재 예정* 스냅샷. 적재기 로더를 그대로 재사용한다.

    적재기와 같은 규칙: ①양끝 개념이 정본 개념 집합에 없으면 orphan skip(populate는 DB `concept`
    맵으로 해석하는데, 개념 적재가 먼저 돌므로 정본 개념 집합이 그 맵의 기대값이다) ②같은
    `(from,to)`
    쌍은 UNIQUE upsert라 DB에서 한 행이 된다(나중 레코드가 이긴다) — 그래서 dict로 접는다.

    Raises:
        CanonicalError: 파일 부재·파싱 실패·개념 0건·적재 예정 엣지 0건(스캔 0건은 실패다).
    """
    try:
        raw = graph_path.read_bytes()
        concepts = load_atom_concepts_from_graph_json(graph_path)
        edge_records, _skip_msgs = load_atom_edges_from_graph_json(graph_path)
        nodes = load_atom_nodes_from_graph_json(graph_path)
    except FileNotFoundError as exc:
        raise CanonicalError(
            f"정본 graph.json을 찾을 수 없다: {graph_path} (FileNotFoundError)"
        ) from exc
    except (OSError, ValueError) as exc:  # JSONDecodeError는 ValueError 하위
        raise CanonicalError(
            f"정본 graph.json을 읽지 못했다: {graph_path} ({type(exc).__name__}: {str(exc)[:120]})"
        ) from exc

    concept_codes = frozenset(rec.code for rec in concepts)
    if not concept_codes:
        raise CanonicalError(
            f"정본 개념이 0건이다: {graph_path} — 공허한 통과를 막기 위해 오류로 판정"
        )

    by_pair: dict[tuple[str, str], str | None] = {}
    orphan = 0
    for rec in edge_records:
        if rec.from_code not in concept_codes or rec.to_code not in concept_codes:
            orphan += 1
            continue
        by_pair[(rec.from_code, rec.to_code)] = rec.relation_subtype
    if not by_pair:
        raise CanonicalError(
            f"정본에서 적재 예정 엣지가 0건이다: {graph_path} (적재기 로더 "
            f"{len(edge_records)}건 중 "
            f"orphan {orphan}건) — 공허한 통과를 막기 위해 오류로 판정"
        )

    edges = frozenset(_edge_key(f, t, s) for (f, t), s in by_pair.items())
    return CanonicalSnapshot(
        edge_total=len(edges),
        edge_by_subtype=distribution(edges),
        concept_total=len(concept_codes),
        atom_node_total=len(nodes),
        edges=edges,
        concept_codes=concept_codes,
        source_path=str(graph_path),
        source_sha12=hashlib.sha256(raw).hexdigest()[:12],
        orphan_skipped=orphan,
    )


def _direction_of(expected: int, actual: int) -> str:
    return DIR_DB_LESS if actual < expected else DIR_DB_MORE if actual > expected else ""


def _merge_directions(directions: Iterable[str]) -> str:
    present = {d for d in directions if d}
    if not present:
        return ""
    if len(present) == 1:
        return next(iter(present))
    return DIR_MIXED


def _sample(edges: Iterable[EdgeKey], limit: int) -> tuple[EdgeKey, ...]:
    return tuple(sorted(edges)[:limit])


def judge(
    canonical: CanonicalSnapshot,
    db: DbSnapshot | None,
    *,
    unknown_reason: str = "",
    diff_limit: int = _DEFAULT_DIFF_LIMIT,
) -> Verdict:
    """정본 스냅샷과 DB 스냅샷을 비교해 MATCH/DRIFT/UNKNOWN을 낸다 — 순수 함수.

    `db`가 None이면 **UNKNOWN**이다(MATCH로도 DRIFT로도 접지 않는다). 비교 축: ①엣지 총수 ②
    `relation_subtype`별 수 ③정본 개념의 DB 부재 수 ④`atom_node` 총수 ⑤엣지 집합 지문(양쪽이 집합을
    줄 때). 어느 하나라도 다르면 DRIFT이고, 방향은 집합 차(있으면)·총수 부호에서 정한다.
    """
    if db is None:
        return Verdict(status=UNKNOWN, reason=unknown_reason or "DB 값을 읽지 못했다(사유 미상)")

    findings: list[Finding] = []
    directions: list[str] = []

    # ① 엣지 총수
    edge_dir = _direction_of(canonical.edge_total, db.edge_total)
    if edge_dir:
        findings.append(
            Finding("edge_total", str(canonical.edge_total), str(db.edge_total), edge_dir)
        )

    # ② relation_subtype별 수 — 총합이 같아도 분포가 다르면 DRIFT(상쇄 방지)
    for subtype in sorted(set(canonical.edge_by_subtype) | set(db.edge_by_subtype)):
        exp = canonical.edge_by_subtype.get(subtype, 0)
        act = db.edge_by_subtype.get(subtype, 0)
        if exp != act:
            findings.append(
                Finding(f"subtype[{subtype}]", str(exp), str(act), _direction_of(exp, act))
            )

    # ③ 정본 개념이 DB에 없다 — 개념 총수 차이가 아니라 *포함관계*로 본다
    # (DB에만 있는 개념은 구 개념그래프·CMS 신규 개념일 수 있어 정보로만 싣는다)
    if db.concept_missing > 0:
        findings.append(
            Finding(
                "concept_missing",
                "0",
                str(db.concept_missing),
                DIR_DB_LESS,
                f"정본 개념 {canonical.concept_total}건 중 DB에 없는 수(DB 개념 총 "
                f"{db.concept_total})",
            )
        )
        directions.append(DIR_DB_LESS)

    # ④ atom_node 총수
    node_dir = _direction_of(canonical.atom_node_total, db.atom_node_total)
    if node_dir:
        detail = "" if db.atom_node_table_present else "atom_node 테이블 자체가 DB에 없다"
        findings.append(
            Finding(
                "atom_node_total",
                str(canonical.atom_node_total),
                str(db.atom_node_total),
                node_dir,
                detail,
            )
        )
        directions.append(node_dir)

    # ⑤ 엣지 집합 지문 — 같은 수의 다른 엣지는 수 비교가 못 잡는다
    only_canon: frozenset[EdgeKey] = frozenset()
    only_db: frozenset[EdgeKey] = frozenset()
    set_compared = canonical.edges is not None and db.edges is not None
    if canonical.edges is not None and db.edges is not None:
        only_canon = canonical.edges - db.edges
        only_db = db.edges - canonical.edges
        if only_canon or only_db:
            findings.append(
                Finding(
                    "edge_set_fingerprint",
                    edge_fingerprint(canonical.edges)[:12],
                    edge_fingerprint(db.edges)[:12],
                    "",
                    f"정본에만 {len(only_canon)}건 · DB에만 {len(only_db)}건",
                )
            )
        directions.append(
            _merge_directions([DIR_DB_LESS if only_canon else "", DIR_DB_MORE if only_db else ""])
        )
    else:
        directions.append(edge_dir)

    if not findings:
        return Verdict(status=MATCH, notes=_notes(canonical, db, set_compared))

    direction = _merge_directions(directions) or DIR_SAME_TOTAL
    return Verdict(
        status=DRIFT,
        direction=direction,
        findings=tuple(findings),
        only_canonical=_sample(only_canon, diff_limit),
        only_db=_sample(only_db, diff_limit),
        only_canonical_total=len(only_canon),
        only_db_total=len(only_db),
        notes=_notes(canonical, db, set_compared),
    )


def _notes(canonical: CanonicalSnapshot, db: DbSnapshot, set_compared: bool) -> tuple[str, ...]:
    """판정에 영향을 주진 않았지만 읽는 사람이 알아야 하는 사실 — 침묵 제외 금지."""
    notes: list[str] = []
    if not set_compared:
        notes.append(
            "엣지 집합 지문은 비교하지 않았다(수 비교만) — 같은 수의 다른 엣지는 못 잡는다"
        )
    if canonical.orphan_skipped:
        notes.append(
            f"정본 엣지 중 {canonical.orphan_skipped}건은 양끝 개념 부재로 적재 예정에서 제외됐다"
        )
    if db.cms_owned_pairs:
        notes.append(
            f"CMS 소유 엣지 {len(db.cms_owned_pairs)}건은 정본 기대값·DB 실측 양쪽에서 "
            "제외했다(P3-26)"
        )
    if db.non_prerequisite_edges:
        notes.append(
            f"비-선수(PREREQUISITE 아님) 엣지 {db.non_prerequisite_edges}건은 비교에서 제외했다"
        )
    if db.db_only_concepts:
        notes.append(
            f"DB에만 있는 개념 {db.db_only_concepts}건 — 정본 밖 개념(구 개념그래프·CMS "
            "신규 개념일 수 "
            "있다). 판정에는 쓰지 않았다"
        )
    if not db.cms_column_present:
        notes.append(
            "DB `concept_edge.cms_edited_at` 컬럼이 없다 — CMS 소유 제외를 적용하지 못했다"
        )
    return tuple(notes)


def adjust_canonical_for_cms(canonical: CanonicalSnapshot, db: DbSnapshot) -> CanonicalSnapshot:
    """CMS 소유 쌍을 정본 기대값에서도 뺀다 — 적재기가 그 쌍을 건너뛰는 규칙의 미러.

    DB 쪽에서만 빼면 정당한 CMS 엣지는 "잔존 행"으로, 정본 엣지는 "미적재"로 오판된다.
    """
    if not db.cms_owned_pairs or canonical.edges is None:
        return canonical
    kept = frozenset(e for e in canonical.edges if (e[0], e[1]) not in db.cms_owned_pairs)
    return CanonicalSnapshot(
        edge_total=len(kept),
        edge_by_subtype=distribution(kept),
        concept_total=canonical.concept_total,
        atom_node_total=canonical.atom_node_total,
        edges=kept,
        concept_codes=canonical.concept_codes,
        source_path=canonical.source_path,
        source_sha12=canonical.source_sha12,
        orphan_skipped=canonical.orphan_skipped,
    )


def evaluate(
    canonical: CanonicalSnapshot,
    db: DbSnapshot | None,
    *,
    unknown_reason: str = "",
    diff_limit: int = _DEFAULT_DIFF_LIMIT,
) -> Verdict:
    """CMS 제외를 적용한 뒤 판정한다 — CLI가 부르는 진입점(`judge`는 그 안쪽 순수 비교)."""
    if db is None:
        return judge(canonical, None, unknown_reason=unknown_reason, diff_limit=diff_limit)
    return judge(adjust_canonical_for_cms(canonical, db), db, diff_limit=diff_limit)


# ──────────────────────────────────────────────────────────────────────────
# DB 읽기 — SQL 조립·정적 읽기 전용 검증·psql 호출·응답 파싱
# ──────────────────────────────────────────────────────────────────────────
# 1단계 — 스키마 사실 두 가지(CMS 컬럼·atom_node 테이블)가 있는가. 없는 컬럼을 SELECT하면
# 쿼리 전체가
# 죽어 UNKNOWN이 되므로, 있는지 먼저 물어 본 뒤 있는 것만 읽는다(prod가 마이그레이션에 뒤처진 상태도
# 정직하게 읽는다).
_SCHEMA_FACTS_SQL = (
    "SELECT json_build_object("
    "'cms_column', EXISTS(SELECT 1 FROM information_schema.columns "
    "WHERE table_name = 'concept_edge' AND column_name = 'cms_edited_at'), "
    "'atom_node_table', to_regclass('public.atom_node') IS NOT NULL);"
)

_FORBIDDEN_SQL_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|call|do|set|"
    r"lock|comment|merge|reindex|cluster|refresh)\b",
    re.IGNORECASE,
)


def build_snapshot_sql(*, cms_column: bool, atom_node_table: bool) -> str:
    """2단계 — 개념 코드·엣지(코드 3-튜플)·atom_node 총수를 **한 SELECT·JSON 한 줄**로 읽는다.

    한 문장이라 한 스냅샷이다(여러 쿼리로 나누면 그 사이 적재가 끼어들 수 있다). 엣지는 `concept`와
    조인해 UUID가 아니라 *code*로 환원한다 — 정본의 `(from_code,to_code,relation_subtype)`와 같은
    3-튜플이어야 지문이 같다. ASCII 전용(한글은 서버가 돌려주는 값을 UTF-8로 디코딩한다).
    """
    cms_expr = "(e.cms_edited_at IS NOT NULL)" if cms_column else "false"
    node_expr = "(SELECT count(*) FROM atom_node)" if atom_node_table else "0"
    return (
        "SELECT json_build_object("
        "'concepts', (SELECT coalesce(json_agg(c.code ORDER BY c.code), '[]'::json) FROM "
        "concept c), "
        f"'atom_nodes', {node_expr}, "
        "'edges', (SELECT coalesce(json_agg(json_build_array("
        f"cf.code, ct.code, e.relation_subtype, e.edge_type::text, {cms_expr})), '[]'::json) "
        "FROM concept_edge e "
        "JOIN concept cf ON cf.concept_id = e.from_concept_id "
        "JOIN concept ct ON ct.concept_id = e.to_concept_id));"
    )


def assert_read_only_sql(sql: str) -> None:
    """보내기 전 정적 검사 — SELECT 한 문장 외에는 거부한다(DDL·DML·`SET` 금지).

    서버 쪽 `default_transaction_read_only`가 이중 방어지만, 코드가 *애초에 쓰기 문장을 조립하지
    못한다*는 것을 테스트가 동결할 수 있게 한 곳에 모은다. 문자열 리터럴 안의 단어는 금지어로
    세지 않는다(`'cms_column'` 같은 JSON 키 때문에 오탐하지 않도록 리터럴을 비운 뒤 검사한다).
    """
    stripped = re.sub(r"'(?:[^']|'')*'", "''", sql)
    statements = [s.strip() for s in stripped.split(";") if s.strip()]
    if len(statements) != 1:
        raise ValueError(
            f"SQL은 정확히 한 문장이어야 한다(읽기 전용 스냅샷) — {len(statements)}문장"
        )
    if not statements[0].lower().startswith("select"):
        raise ValueError("SQL은 SELECT로 시작해야 한다(읽기 전용)")
    hit = _FORBIDDEN_SQL_WORDS.search(statements[0])
    if hit:
        raise ValueError(f"읽기 전용 위반 키워드 '{hit.group(0)}' — SELECT 외 문장은 보내지 않는다")


# psql 실행기 — 테스트가 docker 없이 응답을 주입하는 seam. (인자 목록, stdin 바이트,
# 타임아웃) → 결과.
Runner = Callable[[Sequence[str], bytes, float], "subprocess.CompletedProcess[bytes]"]


def _default_runner(
    args: Sequence[str], stdin: bytes, timeout: float
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 — 고정 실행파일·인자는 리스트(셸 미경유)
        list(args), input=stdin, capture_output=True, timeout=timeout, check=False
    )


def _psql_args(container: str, user: str, database: str) -> list[str]:
    return [
        "docker",
        "exec",
        "-i",
        "-e",
        "PGCLIENTENCODING=UTF8",  # 한글 subtype을 클라이언트 로케일(cp949)이 아니라 UTF-8로 받는다
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on",  # 서버 쪽 쓰기 거부(이중 방어)
        container,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-X",
        "-t",
        "-A",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        "-",
    ]


def _run_json_query(
    sql: str,
    *,
    container: str,
    user: str,
    database: str,
    timeout: float,
    runner: Runner,
) -> dict[str, Any]:
    """SELECT 한 문장을 psql로 보내 JSON 한 줄을 받는다. 실패는 사유를 담아 `DbReadError`.

    사유는 서브프로세스 stderr·예외 타입명을 싣는다 — 예외 타입명만으로는 서로 다른 실패가 같은
    글자로 보인다. 타임아웃은 반드시 건다(무한 대기는 측정 회차를 통째로 태운다).
    """
    assert_read_only_sql(sql)
    try:
        done = runner(_psql_args(container, user, database), sql.encode("ascii"), timeout)
    except FileNotFoundError as exc:
        raise DbReadError("docker 실행 파일을 찾을 수 없다(FileNotFoundError)") from exc
    except subprocess.TimeoutExpired as exc:
        raise DbReadError(f"docker exec psql 타임아웃({timeout}s) — 데몬·DB 응답 없음") from exc
    except OSError as exc:
        raise DbReadError(f"docker exec psql 실행 실패({type(exc).__name__})") from exc

    # 로케일 기본 디코드는 한국어 Windows(cp949)에서 붕괴한다 — UTF-8 고정(HARN-19 선례)
    stdout = (done.stdout or b"").decode("utf-8", errors="replace").strip()
    stderr = (done.stderr or b"").decode("utf-8", errors="replace").strip()
    if done.returncode != 0:
        raise DbReadError(f"psql exit {done.returncode}: {stderr[:200]}")
    if not stdout:
        raise DbReadError(f"psql 출력이 비었다(exit 0) — 대상 DB·컨테이너를 확인: {stderr[:120]}")
    last_line = [ln for ln in stdout.splitlines() if ln.strip()][-1]
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError as exc:
        raise DbReadError(f"psql 출력 파싱 실패({type(exc).__name__}): {last_line[:120]}") from exc
    if not isinstance(payload, dict):
        raise DbReadError(f"psql 출력이 JSON 객체가 아니다({type(payload).__name__})")
    return payload


def read_db_payload(
    *,
    container: str = "whymath-pg",
    user: str = "whymath",
    database: str = "whymath",
    timeout: float = 60.0,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """DB에서 스냅샷 원자료(JSON)를 읽는다 — 1단계 스키마 사실 → 2단계 본 조회.

    Raises:
        DbReadError: 어느 단계든 못 읽었다(UNKNOWN의 원인).
    """
    run = runner if runner is not None else _default_runner
    facts = _run_json_query(
        _SCHEMA_FACTS_SQL,
        container=container,
        user=user,
        database=database,
        timeout=timeout,
        runner=run,
    )
    cms_column = bool(facts.get("cms_column"))
    atom_node_table = bool(facts.get("atom_node_table"))
    payload = _run_json_query(
        build_snapshot_sql(cms_column=cms_column, atom_node_table=atom_node_table),
        container=container,
        user=user,
        database=database,
        timeout=timeout,
        runner=run,
    )
    payload["_cms_column_present"] = cms_column
    payload["_atom_node_table_present"] = atom_node_table
    return payload


def parse_db_payload(payload: Mapping[str, Any], canonical: CanonicalSnapshot) -> DbSnapshot:
    """DB 응답 JSON → 비교용 스냅샷(순수). 모양이 틀리면 `DbReadError`(UNKNOWN)다.

    `PREREQUISITE`가 아닌 엣지와 CMS 소유 엣지는 비교 집합에서 빼되 *건수를 남긴다*. 개념은 총수가
    아니라 정본 코드의 DB 부재 수로 본다.
    """
    try:
        concepts = payload["concepts"]
        raw_edges = payload["edges"]
        atom_nodes = int(payload["atom_nodes"])
        if not isinstance(concepts, list) or not isinstance(raw_edges, list):
            raise TypeError("concepts·edges는 배열이어야 한다")

        db_codes = frozenset(str(c) for c in concepts)
        edges: set[EdgeKey] = set()
        cms_pairs: set[tuple[str, str]] = set()
        non_prereq = 0
        for row in raw_edges:
            from_code, to_code, subtype, edge_type, cms_owned = row
            if str(edge_type) != _PREREQUISITE_DB_VALUE:
                non_prereq += 1
                continue
            if bool(cms_owned):
                cms_pairs.add((str(from_code), str(to_code)))
                continue
            edges.add(
                _edge_key(str(from_code), str(to_code), None if subtype is None else str(subtype))
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise DbReadError(
            f"DB 응답의 모양이 기대와 다르다({type(exc).__name__}: {str(exc)[:120]})"
        ) from exc

    frozen = frozenset(edges)
    return DbSnapshot(
        edge_total=len(frozen),
        edge_by_subtype=distribution(frozen),
        concept_total=len(db_codes),
        concept_missing=len(canonical.concept_codes - db_codes),
        atom_node_total=atom_nodes,
        edges=frozen,
        cms_owned_pairs=frozenset(cms_pairs),
        db_only_concepts=len(db_codes - canonical.concept_codes),
        atom_node_table_present=bool(payload.get("_atom_node_table_present", True)),
        cms_column_present=bool(payload.get("_cms_column_present", True)),
        non_prerequisite_edges=non_prereq,
    )


# ──────────────────────────────────────────────────────────────────────────
# 리포트·CLI
# ──────────────────────────────────────────────────────────────────────────
def _fmt_edge(edge: EdgeKey) -> str:
    return f"{edge[0]} → {edge[1]} [{edge[2] or NULL_SUBTYPE}]"


def render_report(
    verdict: Verdict,
    canonical: CanonicalSnapshot | None,
    db: DbSnapshot | None,
) -> str:
    """사람이 읽는 리포트. 정본 출처(경로·sha256 앞 12자)와 판정 한계를 항상 찍는다."""
    lines = ["[원자 백본 패리티] 정본 graph.json ↔ prod DB (OPS-139)"]
    if canonical is not None:
        lines.append(
            f"정본 출처: {canonical.source_path or '(경로 미상)'} · "
            f"sha256={canonical.source_sha12 or '?'}"
        )
        lines.append(
            f"정본 적재 예정: 엣지 {canonical.edge_total} · 개념 {canonical.concept_total} · "
            f"atom_node {canonical.atom_node_total}"
        )
    if db is not None:
        lines.append(
            f"DB 실측: 엣지 {db.edge_total} · 개념 {db.concept_total}"
            f"(정본 개념 부재 {db.concept_missing}) · atom_node {db.atom_node_total}"
        )
    lines.append(
        f"STATUS={verdict.status}"
        + (f" · DIRECTION={verdict.direction}" if verdict.direction else "")
    )
    if verdict.status == UNKNOWN:
        lines.append(f"사유: {verdict.reason}")
        lines.append(
            "→ 측정 자체가 실패했다 — 일치도 불일치도 아니다. 사유를 먼저 해소한 뒤 다시 돌린다."
        )
    for finding in verdict.findings:
        suffix = f" · {finding.direction}" if finding.direction else ""
        extra = f" — {finding.detail}" if finding.detail else ""
        lines.append(
            f"  ✗ {finding.axis}: 정본 {finding.expected} / DB {finding.actual}{suffix}{extra}"
        )
    if verdict.only_canonical:
        lines.append(
            f"  정본에만 있는 엣지 {verdict.only_canonical_total}건(상위 "
            f"{len(verdict.only_canonical)}):"
        )
        lines.extend(f"    - {_fmt_edge(e)}" for e in verdict.only_canonical)
    if verdict.only_db:
        lines.append(f"  DB에만 있는 엣지 {verdict.only_db_total}건(상위 {len(verdict.only_db)}):")
        lines.extend(f"    - {_fmt_edge(e)}" for e in verdict.only_db)
    lines.extend(f"참고: {note}" for note in verdict.notes)
    lines.append(
        "※ 총합 일치는 약한 신호다 — 이 프로브는 subtype 분포와 엣지 집합 지문까지 비교한다. "
        "MATCH는 '이 실행 시점의 DB가 이 정본과 같다'는 증거이지 앞으로도 같다는 보증이 아니다."
    )
    return "\n".join(lines)


def verdict_to_json(
    verdict: Verdict, canonical: CanonicalSnapshot | None, db: DbSnapshot | None
) -> dict[str, Any]:
    """`--json` 산출물 — 리포트와 같은 사실을 기계가 읽는 모양으로."""
    return {
        "status": verdict.status,
        "direction": verdict.direction,
        "exit_code": verdict.exit_code,
        "reason": verdict.reason,
        "findings": [
            {
                "axis": f.axis,
                "expected": f.expected,
                "actual": f.actual,
                "direction": f.direction,
                "detail": f.detail,
            }
            for f in verdict.findings
        ],
        "only_canonical_total": verdict.only_canonical_total,
        "only_db_total": verdict.only_db_total,
        "only_canonical_sample": [list(e) for e in verdict.only_canonical],
        "only_db_sample": [list(e) for e in verdict.only_db],
        "notes": list(verdict.notes),
        "canonical": (
            None
            if canonical is None
            else {
                "source_path": canonical.source_path,
                "source_sha12": canonical.source_sha12,
                "edge_total": canonical.edge_total,
                "concept_total": canonical.concept_total,
                "atom_node_total": canonical.atom_node_total,
                "orphan_skipped": canonical.orphan_skipped,
            }
        ),
        "db": (
            None
            if db is None
            else {
                "edge_total": db.edge_total,
                "concept_total": db.concept_total,
                "concept_missing": db.concept_missing,
                "atom_node_total": db.atom_node_total,
                "cms_owned_pairs": len(db.cms_owned_pairs),
                "non_prerequisite_edges": db.non_prerequisite_edges,
            }
        ),
    }


def main(argv: list[str] | None = None, *, runner: Runner | None = None) -> int:
    """CLI 엔트리. **0 = MATCH / 1 = DRIFT / 2 = UNKNOWN / 3 = 정본 입력 오류.**"""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.atom_graph_prod_parity",
        description=(
            "원자 백본 정본(graph.json)과 prod DB(concept_edge·concept·atom_node)의 패리티를 "
            "읽기 전용으로 판정한다(OPS-139). 엣지 수·subtype 분포·엣지 집합 지문을 비교하며 "
            "exit 0/1/2/3."
        ),
    )
    parser.add_argument("--graph", type=Path, default=_DEFAULT_GRAPH, help="정본 graph.json 경로")
    parser.add_argument(
        "--container",
        default="whymath-pg",
        help="prod DB 컨테이너(데모 whymath-demo-db와 혼동 금지)",
    )
    parser.add_argument("--user", default="whymath", help="DB 사용자")
    parser.add_argument("--database", default="whymath", help="DB 이름")
    parser.add_argument("--timeout", type=float, default=60.0, help="psql 1회 타임아웃(초·기본 60)")
    parser.add_argument(
        "--diff-limit", type=int, default=_DEFAULT_DIFF_LIMIT, help="차집합 출력 상위 N건"
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로"
    )
    args = parser.parse_args(argv)

    try:
        canonical = compute_canonical(args.graph)
    except CanonicalError as exc:
        print(f"[원자 백본 패리티] 정본 입력 오류: {exc}")
        print(
            "STATUS=INPUT_ERROR — 정본을 못 읽었으므로 일치·불일치를 판정하지 않는다(MATCH 아님)."
        )
        return _EXIT_INPUT_ERROR

    db: DbSnapshot | None = None
    reason = ""
    try:
        payload = read_db_payload(
            container=args.container,
            user=args.user,
            database=args.database,
            timeout=args.timeout,
            runner=runner,
        )
        db = parse_db_payload(payload, canonical)
    except DbReadError as exc:
        reason = str(exc)

    verdict = evaluate(canonical, db, unknown_reason=reason, diff_limit=args.diff_limit)
    print(render_report(verdict, canonical, db))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(
                verdict_to_json(verdict, canonical, db),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"JSON 산출물: {args.json_path}")
    return verdict.exit_code


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
