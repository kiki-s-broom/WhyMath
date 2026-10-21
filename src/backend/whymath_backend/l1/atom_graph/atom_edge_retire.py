"""원자 백본 적재의 잔존 엣지 은퇴 — 정본에서 지운·뒤집은 선수 엣지를 DB에서 정리한다 (KG-14).

## 왜 필요한가

원자 백본 엣지 적재기(`AtomBackendEdgeStore.populate`)는 `INSERT … ON CONFLICT DO UPDATE`만 한다.
정본이 엣지를 지우거나 방향을 뒤집으면(KG-09 순서 역전 교정 · KG-10 경계 반려 · KG-12 체인 수리) 옛
행이 DB에 그대로 남는다. 남은 옛 방향과 새 방향이 합쳐지면 순환이므로, 쓰기 전 DB 인지 순환 검사
(`prerequisite_guard.assert_acyclic_with_db`)가 엣지 적재 전체를 거부한다 — 새 정본이 prod에 영영
도달하지 못한다. 2026-10-21 Kiki 머신 읽기 전용 실측(main `9ca012c1`): prod `concept_edge` 2,234건 ·
정본에만 265 · DB에만 221 · 순환 위험 5쌍.

## 무엇을 지우는가 (범위를 넓히지 않는다)

DB `concept_edge` 행 가운데 다음 넷을 **모두** 만족하는 것만:

1. `edge_type = PREREQUISITE`
2. 양끝 개념 코드가 모두 원자 백본 정본의 개념 코드(`graph.json` `concepts`)다
3. CMS 소유가 아니다(`cms_edited_at IS NULL`) — 사람이 CMS로 만든 관계는 보존하고 건수만 보고한다
4. (선수, 후행) 쌍이 정본 적재 예정 쌍에 없다 — 같은 쌍이 `relation_subtype`만 다르면 upsert가
   고치므로 지우지 않는다

범위 밖(구 개념그래프 엣지 · 다른 엣지 유형 · CMS 소유)은 읽기만 하고 건드리지 않는다.

## 모드

- `report`(기본) — 계산해 리포트에만 싣고 지우지 않는다(종전 동작과 같다).
- `plan` — DB에 아무것도 쓰지 않는다. 지울 목록과 "은퇴 뒤 합집합이 비순환인가"만 판정한다.
- `apply` — 엣지 적재와 **같은 트랜잭션**에서 지운 뒤 DB 인지 순환 검사와 upsert를 한다. 검사나
  삭제 건수 대조가 실패하면 삭제까지 함께 롤백된다(부분 은퇴 없음).

이 모듈은 **DB를 모른다**(순수 판정·렌더). DB 읽기·삭제는 적재기(`atom_backend_edge.py`)가 한다 —
데이터 접근 지점을 늘리지 않는다(`scripts/analysis/data_access_layer_audit.py` 처분 (b)).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from whymath_backend.schema.enums import EdgeType
from whymath_backend.schema.learning_loop_contract import find_prerequisite_cycle

RETIRE_REPORT: Final[str] = "report"
RETIRE_PLAN: Final[str] = "plan"
RETIRE_APPLY: Final[str] = "apply"
RETIRE_MODES: Final[tuple[str, ...]] = (RETIRE_REPORT, RETIRE_PLAN, RETIRE_APPLY)

# DB `edge_type_enum` 문자열 — 적재기가 `EdgeType.PREREQUISITE.value`로 바인딩한다
_PREREQUISITE_DB_VALUE: Final[str] = EdgeType.PREREQUISITE.value


class StaleEdgeRetireError(RuntimeError):
    """은퇴 삭제가 계획과 어긋났다 — 트랜잭션을 롤백시키기 위해 올린다(조용히 넘기지 않는다)."""


@dataclass(frozen=True, slots=True)
class DbEdgeRow:
    """DB `concept_edge` 한 행의 비교용 값(코드로 해석된 양끝)."""

    edge_id: str
    from_code: str
    to_code: str
    relation_subtype: str | None
    edge_type: str
    cms_owned: bool

    @property
    def pair(self) -> tuple[str, str]:
        return (self.from_code, self.to_code)

    def label(self) -> str:
        return f"{self.from_code} → {self.to_code} [{self.relation_subtype or '-'}]"


@dataclass(frozen=True, slots=True)
class RetirePlan:
    """은퇴 계획 — 무엇을 지우고(stale) 무엇을 지켰는지(cms_kept) 건수와 함께 남긴다."""

    stale: tuple[DbEdgeRow, ...]
    cms_kept: tuple[DbEdgeRow, ...]
    in_scope_prerequisite: int  # 범위 안 선수 엣지 수(판정 모집단)
    out_of_scope: int  # 범위 밖이라 읽기만 한 행 수(다른 엣지 유형 포함)


@dataclass(frozen=True, slots=True)
class RetireOutcome:
    """적재 1회의 은퇴 결과 — "작동한 비율" 원칙: 찾은 수·지운 수·지킨 수를 함께 말한다."""

    mode: str
    stale_found: int
    retired: int
    cms_kept: int
    sample: tuple[str, ...] = ()


def validate_mode(mode: str) -> str:
    """모드 문자열 검증 — 오탈자를 기본 동작으로 접지 않는다."""
    if mode not in RETIRE_MODES:
        raise ValueError(f"은퇴 모드는 {RETIRE_MODES} 중 하나여야 한다: {mode!r}")
    return mode


def plan_retirement(
    db_rows: Iterable[DbEdgeRow],
    canon_pairs: Iterable[tuple[str, str]],
    scope_codes: Iterable[str],
) -> RetirePlan:
    """DB 행·정본 쌍·범위 코드 → 은퇴 계획(순수 함수 · DB를 모른다)."""
    canon = frozenset(canon_pairs)
    scope = frozenset(scope_codes)
    stale: list[DbEdgeRow] = []
    kept: list[DbEdgeRow] = []
    in_scope = 0
    out_of_scope = 0
    for row in db_rows:
        if row.edge_type != _PREREQUISITE_DB_VALUE:
            out_of_scope += 1
            continue
        if row.from_code not in scope or row.to_code not in scope:
            out_of_scope += 1
            continue
        in_scope += 1
        if row.pair in canon:
            continue
        if row.cms_owned:
            kept.append(row)
            continue
        stale.append(row)
    order = sorted(stale, key=lambda r: (r.from_code, r.to_code, r.edge_id))
    return RetirePlan(
        stale=tuple(order),
        cms_kept=tuple(sorted(kept, key=lambda r: (r.from_code, r.to_code, r.edge_id))),
        in_scope_prerequisite=in_scope,
        out_of_scope=out_of_scope,
    )


def cycle_after_retirement(
    db_rows: Iterable[DbEdgeRow],
    plan: RetirePlan,
    canon_pairs: Iterable[tuple[str, str]],
) -> list[str] | None:
    """은퇴 뒤 DB 선수 엣지 ∪ 정본 쌍에 순환이 남는가 — `assert_acyclic_with_db`와 같은 합집합."""
    retired = {row.edge_id for row in plan.stale}
    pairs = {
        row.pair
        for row in db_rows
        if row.edge_type == _PREREQUISITE_DB_VALUE and row.edge_id not in retired
    }
    pairs.update(canon_pairs)
    return find_prerequisite_cycle(sorted(pairs))


def summarize(
    plan: RetirePlan, mode: str, retired: int, *, sample_limit: int = 20
) -> RetireOutcome:
    """계획 → 리포트용 결과(목록은 상위 N건만 · 건수는 전량)."""
    return RetireOutcome(
        mode=mode,
        stale_found=len(plan.stale),
        retired=retired,
        cms_kept=len(plan.cms_kept),
        sample=tuple(row.label() for row in plan.stale[:sample_limit]),
    )


def render_plan(
    plan: RetirePlan,
    cycle: Sequence[str] | None,
    *,
    cycle_without_retire: Sequence[str] | None,
    limit: int = 50,
) -> str:
    """plan 모드 출력 — 판정 줄(키=값)과 목록. 목록이 잘리면 잘렸다고 쓴다."""
    lines = [
        "[잔존 엣지 은퇴 계획] (KG-14 · DB에 쓰지 않음)",
        f"RETIRE_STALE_FOUND={len(plan.stale)}",
        f"RETIRE_CMS_KEPT={len(plan.cms_kept)}",
        f"RETIRE_IN_SCOPE={plan.in_scope_prerequisite} · RETIRE_OUT_OF_SCOPE={plan.out_of_scope}",
        "CYCLE_WITHOUT_RETIRE="
        + ("없음" if cycle_without_retire is None else " → ".join(cycle_without_retire)),
        "CYCLE_AFTER_RETIRE=" + ("없음" if cycle is None else " → ".join(cycle)),
        f"RETIRE_PLAN_OK={cycle is None}",
    ]
    shown = plan.stale[:limit]
    lines.append(f"지울 엣지 {len(plan.stale)}건(상위 {len(shown)}건):")
    lines.extend(f"  - {row.label()}" for row in shown)
    if plan.cms_kept:
        lines.append(f"CMS 소유라 지키는 엣지 {len(plan.cms_kept)}건:")
        lines.extend(f"  - {row.label()}" for row in plan.cms_kept[:limit])
    return "\n".join(lines)


__all__ = [
    "RETIRE_APPLY",
    "RETIRE_MODES",
    "RETIRE_PLAN",
    "RETIRE_REPORT",
    "DbEdgeRow",
    "RetireOutcome",
    "RetirePlan",
    "StaleEdgeRetireError",
    "cycle_after_retirement",
    "plan_retirement",
    "render_plan",
    "summarize",
    "validate_mode",
]
