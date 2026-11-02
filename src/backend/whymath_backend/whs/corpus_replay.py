"""WH-S 코퍼스 replay 배치 — 동등문제 검증 풀이·PRM 라벨 공급(S2-02 실가동).

배경(S2-02 "WH-S 배치가 동등문제에 검증 풀이·PRM 라벨 공급")
------------------------------------------------------------
생성 코퍼스(problem_bank_generated_v0)는 S2-02에서 생성기가 방출한 **검증 가능 단계 체인**
(`verify.solution_steps` — 수용 게이트가 Tier2 전 전이 correct를 봉인)을 갖는다. 본 모듈은
그 체인을 **실제 WH-S 하네스 루프(`run_solver`)로 replay**해 4종 상태 저장소를 실적재한다:

  1. 체인의 각 단계 → `solution_nodes` 트리(루트=전개형·자식=변형 단계).
  2. 각 전이를 Tier2(`verify_step` 연쇄)로 재검증 → 노드 `verify_status`(VERIFIED) 라벨.
  3. **결함 주입 오분기**(기본 ON): 마지막 단계의 부호 반전(sign-flip — 오개념 카탈로그의
     factor-sign-flip류 실오류 미러)을 형제 노드로 심고, `verify_step`이 **incorrect(확정
     비동치)로 증명한 경우에만** FAILED 라벨 + Dead-End Log 기록. 증명 불가면 심지 않는다
     (날조 금지 — 강등전 결함 주입 방법론 §3 미러·ground truth 기지).
  4. `finalize` → 검증기 스택 재실행 후 Verified Solution Bank 적재(dedup 멱등).

이렇게 `solution_nodes`에 **good(VERIFIED)·bad(FAILED) 두 라벨**이 실리면 기존
`prm_builder`/`prm_builder_export_cli`(VERIFIED→good·FAILED→bad·그 외 구조 배제)가
PRM 학습쌍 JSONL을 그대로 산출한다 — 본 모듈은 라벨 소스만 공급한다(빌더 재구현 0).

정직성(측정 없는 판정 금지·CLAUDE.md)
------------------------------------
- replay는 **탐색이 아니다**: 정책이 생성기의 construction trace를 재생하므로 finalize
  통과율은 *파이프라인 무결성* 지표이지 솔버의 풀이 능력이 아니다(리포트에 명기).
  LLM 정책(Ollama·MCTS-lite) 탐색은 후속 — 그때 이 replay가 적재한 bank가 웜스타트가 된다.
- 라벨은 전부 SymPy 증명 기반: VERIFIED=전이 동치 증명·FAILED=비동치 증명(incorrect).
  unverifiable 전이는 UNVERIFIED로 격리(PRM 빌더가 구조 배제·학습 누수 0).
- 오분기 시드가 incorrect로 증명되지 않으면 **심지 않고 정직 집계**(`bad_skipped`).

7계층: WH-S 오프라인(§7.5) — 학생 세션 미개입·API 노출 0. 실행은 ops 배치(로컬/CI PG).

사용:
    WHYMATH_DATABASE_URL=postgresql+asyncpg://… python -m whymath_backend.whs.corpus_replay \\
        data/corpus/problem_bank_generated_v0/problems.jsonl \\
        [--limit N] [--no-bad-branch] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from whymath_backend.config import get_settings
from whymath_backend.db.models.solution_node import NodeVerifyStatus
from whymath_backend.l3.verify_step import verify_step
from whymath_backend.whs import node_store
from whymath_backend.whs.harness import (
    Action,
    ApplyStrategyAction,
    EndSearchAction,
    FinalizeAction,
    LogDeadEndAction,
    ParseProblemAction,
    RetrieveSimilarAction,
    SolverOutcome,
    SolverState,
    run_solver,
)

__all__ = [
    "ChainReplayPolicy",
    "ReplayItem",
    "ReplayReport",
    "build_replay_actions",
    "corrupt_final_step",
    "load_replay_items",
    "main",
    "replay_one",
]


@dataclass(frozen=True, slots=True)
class ReplayItem:
    """replay 대상 1건 — 코퍼스 레코드의 검증 재료 투영(순수 데이터)."""

    problem_id: uuid.UUID
    slug: str
    conditions: str
    answer_map: dict[str, str]
    steps: tuple[str, ...]  # 길이 ≥ 2(전이 ≥ 1) — 로더가 필터
    # P3-95: 개념형 답(예 real_root_count — 답이 근이 아니라 개수)은 answer_map이 비어 있다.
    # 그때 finalize는 `answer_kind` 검증기로 레코드의 `answer`(주장 답)를 검산한다.
    answer_kind: str | None = None
    claimed_answer: str | None = None


def load_replay_items(jsonl_text: str) -> list[ReplayItem]:
    """코퍼스 JSONL → replay 대상 목록. `verify.solution_steps`(길이≥2) 보유 레코드만.

    steps 없는 레코드는 replay 불가(전이 0)라 정직히 제외한다 — 카운트는 호출자가
    (전체 대비 대상 수로) 보고한다.
    """
    items: list[ReplayItem] = []
    for line in jsonl_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        record = json.loads(stripped)
        verify = record.get("verify") or {}
        steps = verify.get("solution_steps")
        conditions = verify.get("conditions")
        answer_map = verify.get("answer_map")
        if (
            not isinstance(steps, list)
            or len(steps) < 2
            or not isinstance(conditions, str)
            or not isinstance(answer_map, dict)
        ):
            continue
        items.append(
            ReplayItem(
                problem_id=uuid.UUID(str(record["problem_id"])),
                slug=str(record.get("slug") or record["problem_id"]),
                conditions=conditions,
                answer_map={str(k): str(v) for k, v in answer_map.items()},
                steps=tuple(str(s) for s in steps),
                answer_kind=_answer_kind(verify),
                claimed_answer=_claimed_answer(record, verify),
            )
        )
    return items


def _answer_kind(verify: dict[str, Any]) -> str | None:
    """`verify.answer_kind`(개념형 검증기 키) — 문자열이 아니거나 비면 None(값형)."""
    kind = verify.get("answer_kind")
    return kind if isinstance(kind, str) and kind.strip() else None


def _claimed_answer(record: dict[str, Any], verify: dict[str, Any]) -> str | None:
    """개념형 문항의 주장 답 = 레코드 최상위 `answer` 원문. 값형이면 None(answer_map이 맡는다)."""
    if _answer_kind(verify) is None:
        return None
    answer = record.get("answer")
    if isinstance(answer, bool) or not isinstance(answer, (str, int)):
        return None
    return str(answer)


def corrupt_final_step(steps: tuple[str, ...] | list[str]) -> str | None:
    """마지막 단계의 결정론 오변형(부호 반전) — verify_step이 incorrect로 **증명한 경우에만** 반환.

    부호 반전은 오개념 카탈로그의 sign-flip류(factor-sign-flip 등) 실오류 패턴을 미러한다.
    비동치 증명이 안 되면 None(오분기 미주입·날조 금지) — 호출자가 `bad_skipped`로 정직 집계.
    """
    prev, last = steps[-2], steps[-1]
    corrupted = f"-({last})"
    verdict = verify_step(prev, corrupted)
    if verdict.state.value != "incorrect":
        return None
    return corrupted


def _state_hash(expr: str) -> str:
    """단계 표현식의 결정론 상태 해시 — dead-end 키·노드 상태 식별."""
    return hashlib.sha256(expr.encode("utf-8")).hexdigest()[:16]


def build_replay_actions(item: ReplayItem, *, bad_step: str | None) -> list[dict[str, Any]]:
    """replay 액션 *명세* 목록(순수) — 정책이 런타임에 parent_id를 채워 Action으로 실체화.

    parent_id는 하네스가 노드를 만들어야 알 수 있는 런타임 UUID라 여기서는 자리(`parent`:
    'prev'|'branch'|None)만 표시한다. 순서: parse → retrieve → 체인 apply(steps 전부) →
    (오분기 apply + dead-end) → finalize.
    """
    specs: list[dict[str, Any]] = [
        {"kind": "parse_problem", "structured": {"slug": item.slug, "steps": len(item.steps)}},
        {"kind": "retrieve_similar"},
    ]
    for index, expr in enumerate(item.steps):
        specs.append(
            {
                "kind": "apply_strategy",
                "label": f"전이 {index}: 체인 재생" if index else "문제 제시(체인 시작 상태)",
                "expr": expr,
                "parent": "prev" if index else None,
            }
        )
    if bad_step is not None:
        specs.append(
            {
                "kind": "apply_strategy",
                "label": "결함 주입: 마지막 전이 부호 반전(sign-flip 오개념 미러)",
                "expr": bad_step,
                "parent": "branch",  # 마지막 정상 단계의 *부모*에서 분기(형제 오단계)
            }
        )
        specs.append(
            {
                "kind": "log_deadend",
                "expr": bad_step,
                "label": "결함 주입: 마지막 전이 부호 반전(sign-flip 오개념 미러)",
            }
        )
    specs.append({"kind": "finalize"})
    return specs


class ChainReplayPolicy:
    """`SolverPolicy` 구현 — 액션 명세를 순서 재생하며 parent_id를 런타임 노드 id로 결선.

    ScriptedPolicy는 정적 시퀀스라 apply_strategy의 parent_id(런타임 UUID)를 체이닝할 수
    없다 — 본 정책은 `state.history`의 ToolResult.node_id를 읽어 직전/분기 부모를 잇는다
    (정책은 도구 결과를 관찰할 수 있다는 계약 그대로·하네스 무변경).
    """

    def __init__(self, item: ReplayItem, *, bad_step: str | None) -> None:
        self._item = item
        self._specs = build_replay_actions(item, bad_step=bad_step)
        self._index = 0

    @staticmethod
    def _apply_node_ids(state: SolverState) -> list[uuid.UUID]:
        """지금까지 생성된 apply_strategy 노드 id(순서 보존)."""
        return [
            result.node_id
            for result in state.history
            if result.kind == "apply_strategy" and result.node_id is not None
        ]

    async def next_action(self, state: SolverState) -> Action:
        if self._index >= len(self._specs):
            return EndSearchAction(reason="replay 명세 소진")
        spec = self._specs[self._index]
        self._index += 1
        kind = spec["kind"]
        if kind == "parse_problem":
            return ParseProblemAction(structured=dict(spec["structured"]))
        if kind == "retrieve_similar":
            return RetrieveSimilarAction()
        if kind == "apply_strategy":
            nodes = self._apply_node_ids(state)
            parent: uuid.UUID | None = None
            if spec["parent"] == "prev" and nodes:
                parent = nodes[-1]
            elif spec["parent"] == "branch" and len(nodes) >= 2:
                # 오분기는 마지막 정상 단계의 *부모*(끝에서 두 번째 노드)에서 갈라진다 —
                # (부모 상태 → 오단계) 전이가 PRM bad step이 된다.
                parent = nodes[-2]
            return ApplyStrategyAction(
                action_label=str(spec["label"]),
                state_repr={"expr": spec["expr"]},
                state_hash=_state_hash(str(spec["expr"])),
                parent_id=parent,
            )
        if kind == "log_deadend":
            return LogDeadEndAction(
                state_hash=_state_hash(str(spec["expr"])),
                action_label=str(spec["label"]),
                reason="결정론 결함 주입 — verify_step 비동치 증명(incorrect)",
            )
        if kind == "finalize":
            return FinalizeAction(
                conditions=[self._item.conditions],
                answer=dict(self._item.answer_map),
                steps=list(self._item.steps),
                strategy_tag="corpus-replay",
                answer_kind=self._item.answer_kind,
                claimed_answer=self._item.claimed_answer,
            )
        raise AssertionError(f"미지 명세: {spec!r}")  # pragma: no cover - 빌더와 짝


# 전이 판정 → 노드 라벨 매핑(§3) — correct=VERIFIED·incorrect=FAILED·unverifiable=UNVERIFIED 격리.
_STATE_TO_STATUS: dict[str, NodeVerifyStatus] = {
    "correct": NodeVerifyStatus.VERIFIED,
    "incorrect": NodeVerifyStatus.FAILED,
    "unverifiable": NodeVerifyStatus.UNVERIFIED,
}


@dataclass(slots=True)
class ReplayReport:
    """replay 배치 집계 — 정직 회계(수치는 전부 실측·조용한 생략 0)."""

    total_records: int = 0
    replayed: int = 0
    finalized_verified: int = 0
    finalized_other: int = 0
    nodes_created: int = 0
    labeled_good: int = 0
    labeled_bad: int = 0
    labeled_unverified: int = 0
    bad_skipped: int = 0  # 오분기 비동치 증명 실패로 미주입(날조 금지)
    failures: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "replayed": self.replayed,
            "finalized_verified": self.finalized_verified,
            "finalized_other": self.finalized_other,
            "nodes_created": self.nodes_created,
            "labeled_good": self.labeled_good,
            "labeled_bad": self.labeled_bad,
            "labeled_unverified": self.labeled_unverified,
            "bad_skipped": self.bad_skipped,
            "failures": self.failures,
            "note": (
                "finalize 통과율은 파이프라인 무결성 지표다(생성기 construction trace의 "
                "replay — 솔버 풀이 능력 측정 아님·LLM 정책 탐색은 후속)."
            ),
        }


async def replay_one(
    session: AsyncSession,
    item: ReplayItem,
    *,
    bad_branch: bool = True,
) -> tuple[SolverOutcome, dict[str, int]]:
    """1건 replay — run_solver 실행 후 전이별 Tier2 판정을 노드 verify_status로 라벨링.

    반환 카운트: nodes/good/bad/unverified/bad_skipped. 트랜잭션 commit은 호출자 관리.
    """
    bad_step = corrupt_final_step(item.steps) if bad_branch else None
    policy = ChainReplayPolicy(item, bad_step=bad_step)
    outcome = await run_solver(session, problem_id=item.problem_id, policy=policy)

    node_ids = [
        result.node_id
        for result in outcome.trace
        if result.kind == "apply_strategy" and result.node_id is not None
    ]
    counts = {"nodes": len(node_ids), "good": 0, "bad": 0, "unverified": 0, "bad_skipped": 0}
    if bad_branch and bad_step is None:
        counts["bad_skipped"] = 1

    # 정상 체인 노드 = 앞의 len(steps)개(루트 포함). 루트는 들어온 전이가 없어 PRM 밖(라벨
    # 불필요·pending 유지). 전이 i(steps[i-1]→steps[i])의 판정이 노드 i의 라벨이다.
    chain_nodes = node_ids[: len(item.steps)]
    for index in range(1, len(chain_nodes)):
        verdict = verify_step(item.steps[index - 1], item.steps[index])
        status = _STATE_TO_STATUS[verdict.state.value]
        await node_store.update_evaluation(session, chain_nodes[index], verify_status=status)
        if status is NodeVerifyStatus.VERIFIED:
            counts["good"] += 1
        elif status is NodeVerifyStatus.FAILED:
            counts["bad"] += 1
        else:
            counts["unverified"] += 1

    # 오분기 노드(있으면 마지막 1개) — corrupt_final_step이 이미 incorrect를 증명했다.
    if bad_step is not None and len(node_ids) > len(item.steps):
        await node_store.update_evaluation(
            session, node_ids[len(item.steps)], verify_status=NodeVerifyStatus.FAILED
        )
        counts["bad"] += 1
    return outcome, counts


async def run_replay_batch(
    sessionmaker: async_sessionmaker[AsyncSession],
    items: list[ReplayItem],
    *,
    bad_branch: bool = True,
) -> ReplayReport:
    """배치 replay — 문제별 독립 트랜잭션(1건 실패가 배치를 오염시키지 않게)."""
    report = ReplayReport(total_records=len(items))
    for item in items:
        try:
            async with sessionmaker() as session:
                outcome, counts = await replay_one(session, item, bad_branch=bad_branch)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 — 배치 회계(정직 기록 후 계속)
            report.failures.append(f"{item.slug}: {type(exc).__name__}: {exc}")
            continue
        report.replayed += 1
        report.nodes_created += counts["nodes"]
        report.labeled_good += counts["good"]
        report.labeled_bad += counts["bad"]
        report.labeled_unverified += counts["unverified"]
        report.bad_skipped += counts["bad_skipped"]
        if outcome.status == "finalized" and outcome.final_grade == "verified":
            report.finalized_verified += 1
        else:
            report.finalized_other += 1
            report.failures.append(f"{item.slug}: finalize={outcome.status}/{outcome.final_grade}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.whs.corpus_replay",
        description="코퍼스 단계 체인을 WH-S 하네스로 replay — 검증 풀이·PRM 라벨 실적재.",
    )
    parser.add_argument("corpus", nargs="+", help="코퍼스 JSONL 경로(들).")
    parser.add_argument("--limit", type=int, default=None, help="대상 상한(스모크용).")
    parser.add_argument(
        "--no-bad-branch",
        action="store_true",
        help="결함 주입 오분기 끄기(기본 ON — PRM bad 라벨 공급).",
    )
    parser.add_argument("--json", dest="json_path", default=None, help="JSON 리포트 저장 경로.")
    args = parser.parse_args(argv)

    items: list[ReplayItem] = []
    for path in args.corpus:
        items.extend(load_replay_items(Path(path).read_text(encoding="utf-8")))
    if args.limit is not None:
        items = items[: args.limit]
    if not items:
        print("replay 대상 0건 — verify.solution_steps 보유 레코드가 없습니다.")
        return 1

    engine = create_async_engine(get_settings().database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async def _run() -> ReplayReport:
        try:
            return await run_replay_batch(sessionmaker, items, bad_branch=not args.no_bad_branch)
        finally:
            await engine.dispose()

    report = asyncio.run(_run())
    payload = report.to_json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_path:
        Path(args.json_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # 정직 게이트: 전건 finalize=verified가 아니면 실패(파이프라인 무결성 회귀 신호).
    return 0 if report.finalized_other == 0 and not report.failures else 1


if __name__ == "__main__":  # pragma: no cover - CLI 진입
    sys.exit(main())
