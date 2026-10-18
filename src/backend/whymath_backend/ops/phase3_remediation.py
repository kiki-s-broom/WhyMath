"""Phase 3 오답 → 교정 전략 커버리지 CLI (P3-06) — 핵심 오개념 12개에 체인이 실제로 도는가.

판정 대상은 "파일이 있는가"가 아니라 **오답을 넣으면 교정 전략이 나오는가**다. 핵심 오개념(P3-01
명세 12개)마다 아래를 실제로 실행해 확인하고, 사람이 세지 않고 CLI 가 표와 종료 코드를 낸다.

    사용법: python -m whymath_backend.ops.phase3_remediation [--json] [--spec PATH] [--data PATH]

    ① 좌석    — 승인 크로스워크(직접매핑)로 그 M-id 에 닿는 kebab 이 있고 서명 픽스처가 있다
    ② 오답    — 오답 픽스처를 넣으면 그 kebab 단 하나가 후보로 나오고 신뢰도가 게이트를 넘는다
    ③ 정답    — 정답 픽스처를 넣으면 후보가 나오지 않는다(정답을 오개념으로 잡는 오탐 0)
    ④ 사다리  — 같은 오답을 4회 넣으면 P-09 사다리가 none→교정 설명→쉬운 문항→선수 개념으로 오르고,
                 각 등급이 코퍼스에 실재하는 대상(문항 id·원자 코드)으로 해소된다
    ⑤ 보고 id — 그 kebab 의 canonical M-id 가 이 M-id 인가(`select_canonical` — 동률·가림이면 표기)

상태: served(①~⑤ 충족) · shadowed(①~④ 충족, canonical 이 다른 M-id 라 리포트에는 그쪽 id 로 나감) ·
blocked(좌석 없음 — 서명을 만들 kebab 자체가 없다) · failed(좌석은 있는데 ②~④ 중 깨졌다).

종료 코드: 0 = 12개 전부 산출(served·shadowed) · 1 = 하나라도 blocked·failed ·
2 = 명세·코퍼스·데이터 적재 실패(측정 자체를 못 했다 — 통과로 위장하지 않는다).

범위 정직: 이 CLI 는 **객관식 채널**만 잰다. 단답형 문항은 어떤 채널로도 후보가 0건이라(숫자 하나를
답하므로 오류 서명 등식이 안 만들어진다) 범위 밖이며, 그 크기를 "작동한 비율" 절에 숫자로 낸다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final

from whymath_backend.l1.misconception.crosslink_resolve import ResolvedLink, select_canonical
from whymath_backend.l1.standards import phase3_coverage as p3c
from whymath_backend.l1.standards.phase3_remediation_spec import (
    RemediationSpec,
    RemediationSpecError,
    SignatureFixtures,
    default_spec_path,
    load_remediation_spec,
)
from whymath_backend.l1.standards.phase3_scope import (
    ReferenceIndex,
    ScopeSpec,
    ScopeSpecError,
    load_reference_index,
    load_scope_spec,
    verify_spec,
)
from whymath_backend.l2.recommendation_contract import ReasonType, RecommendationAction
from whymath_backend.l2.remediation_policy import EscalationRung
from whymath_backend.l4.misconception.attempt_hypothesis_policy import AttemptHypothesisAction
from whymath_backend.l4.misconception.distractor_link import resolve_misconception_from_choice
from whymath_backend.l4.misconception.remediation_strategy import (
    ChainResult,
    run_choice_chain,
)
from whymath_backend.schema.assessment_evidence import MisconceptionScan

__all__ = [
    "EXPECTED_LADDER",
    "CorpusResolvers",
    "Inputs",
    "MisconceptionRow",
    "RemediationReport",
    "RowStatus",
    "evaluate",
    "load_inputs",
    "main",
]

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROBLEM_GLOB: Final = "data/corpus/problem_bank_*/problems.jsonl"
_CROSSLINKS: Final = "data/corpus/misconception_crosslinks_v1/crosslinks.json"

#: 같은 오답을 1·2·3·4회 넣었을 때 기대하는 사다리 — **계획서 §9 의 사실**(2·3·4회)을 독립적으로
#: 적은 것이다. `l2/remediation_policy` 표를 읽어 만들면 표의 경계가 한 칸 밀려도 기대도 따라 밀려
#: 변별력이 0 이 된다(경계 이동 뮤테이션이 RED 가 되려면 기대가 표 밖에 있어야 한다).
EXPECTED_LADDER: Final[tuple[EscalationRung, ...]] = (
    EscalationRung.NONE,
    EscalationRung.CORRECTIVE_EXPLANATION,
    EscalationRung.EASIER_PROBLEM,
    EscalationRung.PREREQUISITE_CONCEPT,
)

#: 해소기가 돌려주는 대상 수 상한 — 그래프 조회 규율(depth ≤ 2 · max_nodes ≤ 12~20)과 같은 정신이다.
_MAX_EASIER: Final = 3
_MAX_PREREQUISITES: Final = 3


class RowStatus(str, Enum):
    SERVED = "served"
    SHADOWED = "shadowed"
    BLOCKED = "blocked"
    FAILED = "failed"


# ──────────────────────────────────────────────────────────────────────────
# 입력 — 테스트가 값 객체째로 바꿔 끼워 결함을 주입한다
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Inputs:
    scope: ScopeSpec
    index: ReferenceIndex
    remediation: RemediationSpec
    corpus: p3c.CoverageCorpus
    #: 승인된 범위 내 **객관식** 문항 원본 행(problem_id → 행). 보기·정답·distractor_map 을 읽는다.
    rows: Mapping[str, Mapping[str, Any]]
    #: kebab → 승인 크로스워크 링크(직접매핑). canonical 선정의 입력이다.
    crosslinks: Mapping[str, tuple[ResolvedLink, ...]]
    #: 범위 내 승인 단답형 문항 수 — 채널이 없는 크기를 숫자로 내기 위한 분모.
    short_answer_problems: int


class CorpusResolvers:
    """`RungResolvers` 의 코퍼스 구현 — 틀린 문항의 **개념**에서 쉬운 문항·선수 원자를 따라간다.

    오개념의 개념이 아니라 틀린 문항의 개념을 쓰는 이유: 한 kebab 이 여러 개념의 문항에 퍼져 있다
    (예: power-rule-step-omitted 는 02-03 뿐 아니라 02-05·02-10 문항에도 달려 있다). 오개념 쪽
    개념으로 고정하면 학생이 실제로 막힌 문항과 다른 개념으로 내려보낸다.
    """

    def __init__(self, inputs: Inputs) -> None:
        self._inputs = inputs
        self._problems = {p.problem_id: p for p in inputs.corpus.problems}
        self._concepts = {c.source_id: c for c in inputs.scope.concepts}

    def _concepts_of(self, problem_id: str) -> list[Any]:
        problem = self._problems.get(problem_id)
        if problem is None:
            return []
        return [self._concepts[s] for s in sorted(problem.primary_src_ids) if s in self._concepts]

    def easier_problem_ids(self, problem_id: str, misconception_id: str) -> Sequence[str]:
        failing = self._problems.get(problem_id)
        if failing is None or failing.difficulty is None:
            return ()
        concepts = {c.source_id for c in self._concepts_of(problem_id)}
        pool = [
            p
            for p in self._inputs.corpus.problems
            if p.problem_id != problem_id
            and p.review_status == p3c.PROBLEM_ELIGIBLE_STATUS
            and p.difficulty is not None
            and p.difficulty < failing.difficulty
            and p.primary_src_ids & concepts
        ]
        # 같은 오개념을 겨냥한 문항을 먼저(쉽게 다시 확인) · 그다음 쉬운 순 · 동률은 id 로 결정론.
        pool.sort(
            key=lambda p: (
                misconception_id not in p.distractor_ids,
                p.difficulty if p.difficulty is not None else 0.0,
                p.problem_id,
            )
        )
        return tuple(p.problem_id for p in pool[:_MAX_EASIER])

    def prerequisite_atoms(self, problem_id: str) -> Sequence[str]:
        found: set[str] = set()
        for concept in self._concepts_of(problem_id):
            facts = p3c.concept_facts(
                self._inputs.scope, self._inputs.index, self._inputs.corpus, concept
            )
            found.update(facts.prerequisite_sources)
        return tuple(sorted(found)[:_MAX_PREREQUISITES])


# ──────────────────────────────────────────────────────────────────────────
# 결과 모델
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SignatureEvidence:
    """kebab 하나의 서명을 체인에 실제로 넣어 본 결과."""

    kebab_id: str
    failures: tuple[str, ...]
    wrong_checked: int
    correct_checked: int
    op_code_entries: int
    first_confidence: float | None
    ladder: tuple[str, ...]
    ladder_resolved: tuple[bool, ...]
    patterns: tuple[str, ...]
    action: str | None
    reason_type: str | None
    pedagogy: str | None


@dataclass(frozen=True)
class MisconceptionRow:
    mis_id: str
    concept_code: str
    status: RowStatus
    kebab_id: str | None
    reports_as: str | None
    reaching_problems: int
    failures: tuple[str, ...]
    evidence: SignatureEvidence | None
    note: str


@dataclass(frozen=True)
class WorkingRatio:
    """객관식 오답 보기를 실제로 골랐을 때 런타임이 후보를 내는 비율 — 측정과 서빙의 일치 여부."""

    wrong_picks: int
    with_candidate: int
    dropped_unknown: Mapping[str, int]
    dropped_below_floor: int
    short_answer_problems: int


@dataclass(frozen=True)
class RemediationReport:
    rows: tuple[MisconceptionRow, ...]
    working: WorkingRatio

    @property
    def produced(self) -> int:
        return sum(1 for r in self.rows if r.status in (RowStatus.SERVED, RowStatus.SHADOWED))

    @property
    def exit_code(self) -> int:
        return 0 if self.produced == len(self.rows) else 1


# ──────────────────────────────────────────────────────────────────────────
# 서명 검증 — 체인을 실제로 돌린다
# ──────────────────────────────────────────────────────────────────────────
def _pick(inputs: Inputs, problem_id: str, failures: list[str]) -> Mapping[str, Any] | None:
    row = inputs.rows.get(problem_id)
    if row is None:
        failures.append(f"문항 {problem_id[:8]}…: 승인된 범위 내 객관식 문항이 아니거나 없다")
    return row


def _run(
    row: Mapping[str, Any],
    index: int,
    *,
    is_correct: bool,
    resolvers: CorpusResolvers,
    prior: Sequence[Any] = (),
) -> ChainResult:
    return run_choice_chain(
        problem_id=str(row["problem_id"]),
        distractor_map=row.get("distractor_map"),
        selected_choice_index=index,
        is_correct=is_correct,
        prior=prior,
        resolvers=resolvers,
    )


def _verify_signature(
    sig: SignatureFixtures, inputs: Inputs, resolvers: CorpusResolvers
) -> SignatureEvidence:
    failures: list[str] = []
    op_entries = 0
    first_confidence: float | None = None
    patterns: list[str] = []
    action: str | None = None
    reason_type: str | None = None
    pedagogy: str | None = None
    wrong_checked = 0
    correct_checked = 0
    first_wrong: tuple[Mapping[str, Any], int] | None = None

    for fx in sig.wrong:
        row = _pick(inputs, fx.problem_id, failures)
        if row is None:
            continue
        choices = row.get("choices") or []
        label = f"{fx.problem_id[:8]}…#{fx.choice_index}"
        if not 0 <= fx.choice_index < len(choices):
            failures.append(f"오답 픽스처 {label}: 보기 인덱스가 범위 밖이다")
            continue
        if choices[fx.choice_index] == row.get("answer"):
            failures.append(f"오답 픽스처 {label}: 정답 보기를 오답이라 선언했다")
            continue
        dmap = row.get("distractor_map") or []
        if resolve_misconception_from_choice(dmap, fx.choice_index) != sig.kebab_id:
            failures.append(
                f"오답 픽스처 {label}: distractor_map 이 이 보기를 {sig.kebab_id} 로 잇지 않는다"
            )
            continue
        wrong_checked += 1
        if any(
            isinstance(e, Mapping) and e.get("choice_index") == fx.choice_index and e.get("op_code")
            for e in dmap
        ):
            op_entries += 1
        result = _run(row, fx.choice_index, is_correct=False, resolvers=resolvers)
        if result.scan is not MisconceptionScan.RAN_WITH_CANDIDATES or result.candidate_ids != (
            sig.kebab_id,
        ):
            failures.append(
                f"오답 {label}: 후보가 {sig.kebab_id} 단 하나가 아니다 — "
                f"후보 {list(result.candidate_ids)} · dropped={result.dropped_reason}"
            )
            continue
        strategy = result.strategy
        if strategy is None:
            failures.append(f"오답 {label}: 후보는 나왔는데 교정 전략이 없다")
            continue
        if (
            not strategy.remediation_eligible
            or strategy.reason_type is not ReasonType.MISCONCEPTION_REMEDIATION
        ):
            failures.append(
                f"오답 {label}: 신뢰도 {strategy.confidence:.2f} 가 교정 하한을 넘지 못한다"
            )
            continue
        if strategy.action is not RecommendationAction.PRACTICE_CURRENT:
            failures.append(
                f"오답 {label}: 추천 행위가 PRACTICE_CURRENT 가 아니다 ({strategy.action})"
            )
            continue
        if first_wrong is None:
            first_wrong = (row, fx.choice_index)
            first_confidence = result.candidate_confidence
            action = strategy.action.value
            reason_type = strategy.reason_type.value
            pedagogy = strategy.pedagogy_strategy

    for fx in sig.correct:
        row = _pick(inputs, fx.problem_id, failures)
        if row is None:
            continue
        choices = row.get("choices") or []
        label = f"{fx.problem_id[:8]}…#{fx.choice_index}"
        if not 0 <= fx.choice_index < len(choices) or choices[fx.choice_index] != row.get("answer"):
            failures.append(f"정답 픽스처 {label}: 이 보기가 정답이 아니다")
            continue
        correct_checked += 1
        result = _run(row, fx.choice_index, is_correct=True, resolvers=resolvers)
        if result.signature is not None or result.candidate_ids:
            failures.append(
                f"정답 {label}: 정답 보기에서 오개념 후보가 나왔다 — "
                f"{list(result.candidate_ids)} (오탐)"
            )
        elif result.hypothesis_action is not AttemptHypothesisAction.DECAY_ONLY:
            failures.append(
                f"정답 {label}: 정답 회차의 가설 처분이 DECAY_ONLY 가 아니다 "
                f"({result.hypothesis_action.value})"
            )

    ladder: list[str] = []
    resolved: list[bool] = []
    if first_wrong is not None:
        row, index = first_wrong
        prior: Sequence[Any] = ()
        for _ in EXPECTED_LADDER:
            step = _run(row, index, is_correct=False, resolvers=resolvers, prior=prior)
            prior = step.hypotheses
            if step.strategy is None:
                ladder.append("none_strategy")
                resolved.append(False)
                continue
            ladder.append(step.strategy.escalation_rung.value)
            resolved.append(step.strategy.rung_action.resolved)
            if len(patterns) < 2:
                patterns.append(step.strategy.intervention_pattern.value)
        expected = tuple(r.value for r in EXPECTED_LADDER)
        if tuple(ladder) != expected:
            failures.append(f"사다리: 1~4회 관측 {ladder} ≠ 기대 {list(expected)}")
        for n, ok in enumerate(resolved, start=1):
            if not ok:
                failures.append(
                    f"사다리 {n}회차({ladder[n - 1]}): 가리키는 대상이 코퍼스에서 해소되지 않는다"
                )
    elif not failures:
        failures.append("오답 픽스처가 하나도 체인을 통과하지 못해 사다리를 잴 수 없다")

    return SignatureEvidence(
        kebab_id=sig.kebab_id,
        failures=tuple(failures),
        wrong_checked=wrong_checked,
        correct_checked=correct_checked,
        op_code_entries=op_entries,
        first_confidence=first_confidence,
        ladder=tuple(ladder),
        ladder_resolved=tuple(resolved),
        patterns=tuple(patterns),
        action=action,
        reason_type=reason_type,
        pedagogy=pedagogy,
    )


# ──────────────────────────────────────────────────────────────────────────
# 평가
# ──────────────────────────────────────────────────────────────────────────
def _working_ratio(inputs: Inputs) -> WorkingRatio:
    picks = 0
    produced = 0
    unknown: dict[str, int] = {}
    below = 0
    for row in inputs.rows.values():
        dmap = row.get("distractor_map") or []
        for entry in dmap:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("choice_index"), int):
                continue
            picks += 1
            result = run_choice_chain(
                problem_id=str(row["problem_id"]),
                distractor_map=dmap,
                selected_choice_index=entry["choice_index"],
                is_correct=False,
            )
            if result.candidate_ids:
                produced += 1
            elif result.dropped_reason == "unknown_misconception" and result.signature is not None:
                key = result.signature.misconception_id
                unknown[key] = unknown.get(key, 0) + 1
            elif result.dropped_reason == "below_floor":
                below += 1
    return WorkingRatio(
        wrong_picks=picks,
        with_candidate=produced,
        dropped_unknown=dict(sorted(unknown.items())),
        dropped_below_floor=below,
        short_answer_problems=inputs.short_answer_problems,
    )


def _reaching_problems(inputs: Inputs, kebabs: Sequence[str]) -> int:
    targets = set(kebabs)
    return sum(
        1
        for row in inputs.rows.values()
        if any(
            isinstance(e, Mapping) and e.get("misconception_id") in targets
            for e in row.get("distractor_map") or []
        )
    )


def evaluate(inputs: Inputs) -> RemediationReport:
    """핵심 오개념 12개를 분모로 체인을 실제 실행해 표를 만든다."""
    resolvers = CorpusResolvers(inputs)
    signatures = inputs.remediation.by_kebab()
    evidence_cache: dict[str, SignatureEvidence] = {}
    kebabs_of: dict[str, list[str]] = {}
    for linked_kebab, links in inputs.crosslinks.items():
        for link in links:
            if link.link_type == p3c.DIRECT_LINK_TYPE:
                kebabs_of.setdefault(link.mis_id, []).append(linked_kebab)

    rows: list[MisconceptionRow] = []
    for core in inputs.scope.core_misconceptions:
        seated = sorted(kebabs_of.get(core.mis_id, []))
        kebab = next((k for k in seated if k in signatures), None)
        if kebab is None:
            reason = (
                "승인 크로스워크에 이 M-id 로 닿는 kebab 이 없다"
                if not seated
                else f"kebab {seated} 은 있으나 서명 픽스처가 없다"
            )
            rows.append(
                MisconceptionRow(
                    mis_id=core.mis_id,
                    concept_code=core.concept_code,
                    status=RowStatus.BLOCKED,
                    kebab_id=None,
                    reports_as=None,
                    reaching_problems=0,
                    failures=(),
                    evidence=None,
                    note=(
                        f"좌석 없음 — {reason}. 처분은 게이트 "
                        f"{inputs.remediation.unseated_gate} 의 재판정(안 A~D) 몫이라 "
                        "이 항목이 kebab·크로스링크를 만들지 않는다."
                    ),
                )
            )
            continue
        if kebab not in evidence_cache:
            evidence_cache[kebab] = _verify_signature(signatures[kebab], inputs, resolvers)
        evidence = evidence_cache[kebab]
        selection = select_canonical(list(inputs.crosslinks.get(kebab, ())))
        reports_as = selection.canonical_mis_id
        if evidence.failures:
            status = RowStatus.FAILED
            note = "체인 검증 실패 — failures 참조"
        elif reports_as == core.mis_id:
            status = RowStatus.SERVED
            note = ""
        else:
            status = RowStatus.SHADOWED
            canonical_text = reports_as or (
                "없음(동률)" if selection.ambiguous else "없음(no_direct)"
            )
            note = (
                f"{kebab} 의 canonical 이 {canonical_text} — "
                f"리포트에는 그 id 로 나간다(한 kebab 으로는 {core.mis_id} 와 변별 불가)"
            )
        rows.append(
            MisconceptionRow(
                mis_id=core.mis_id,
                concept_code=core.concept_code,
                status=status,
                kebab_id=kebab,
                reports_as=reports_as,
                reaching_problems=_reaching_problems(inputs, [kebab]),
                failures=evidence.failures,
                evidence=evidence,
                note=note,
            )
        )
    return RemediationReport(rows=tuple(rows), working=_working_ratio(inputs))


# ──────────────────────────────────────────────────────────────────────────
# 적재
# ──────────────────────────────────────────────────────────────────────────
class LoadError(RuntimeError):
    """측정 입력 적재 실패 — CLI 는 exit 2 (통과로 위장하지 않는다)."""


def _load_rows(scope: ScopeSpec, root: Path) -> tuple[dict[str, Mapping[str, Any]], int]:
    scope_srcs = frozenset(c.source_id for c in scope.concepts)
    rows: dict[str, Mapping[str, Any]] = {}
    short = 0
    scanned = 0
    for path in sorted(root.glob(_PROBLEM_GLOB)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LoadError(
                f"문항 코퍼스를 읽지 못했다 ({path}): {type(exc).__name__}: {exc}"
            ) from exc
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LoadError(
                    f"문항 코퍼스 {number}행 파싱 실패 ({path}): {type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                continue
            scanned += 1
            ref = p3c.problem_ref_from_row(row)
            if ref is None or ref.review_status != p3c.PROBLEM_ELIGIBLE_STATUS:
                continue
            if not ref.primary_src_ids & scope_srcs:
                continue
            if row.get("distractor_map") and isinstance(row.get("choices"), list):
                rows[ref.problem_id] = row
            else:
                short += 1
    if scanned == 0:
        raise LoadError("문항 코퍼스가 0건이다 — 측정 불가")
    return rows, short


def _load_crosslinks(root: Path) -> dict[str, tuple[ResolvedLink, ...]]:
    target = root / _CROSSLINKS
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LoadError(
            f"오개념 크로스링크를 읽지 못했다 ({target}): {type(exc).__name__}: {exc}"
        ) from exc
    raw = payload.get("crosslinks") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        raise LoadError(f"{target}: 최상위 'crosslinks' 배열이 없거나 비어 있다")
    grouped: dict[str, list[ResolvedLink]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("kebab_id"), str):
            continue
        conf = item.get("confidence")
        grouped.setdefault(item["kebab_id"], []).append(
            ResolvedLink(
                mis_id=str(item.get("mis_id")),
                link_type=str(item.get("link_type")),
                confidence=(
                    float(conf)
                    if isinstance(conf, (int, float)) and not isinstance(conf, bool)
                    else None
                ),
            )
        )
    return {k: tuple(v) for k, v in grouped.items()}


def load_inputs(
    scope_path: Path | None = None, data_path: Path | None = None, root: Path | None = None
) -> Inputs:
    base = root or _REPO_ROOT
    try:
        scope = load_scope_spec(scope_path)
        index = load_reference_index(scope)
        violations = verify_spec(scope, index)
        if violations:
            raise LoadError(
                "범위 명세가 코퍼스와 어긋나 있다 — 분모를 신뢰할 수 없어 측정을 거부한다:\n"
                + "\n".join(f"  - {v}" for v in violations)
            )
        remediation = load_remediation_spec(data_path or default_spec_path())
        if remediation.scope_spec_id != scope.spec_id:
            raise LoadError(
                f"교정 데이터가 가리키는 범위 명세({remediation.scope_spec_id})가 "
                f"현행({scope.spec_id})과 다르다"
            )
        corpus = p3c.load_corpus(scope)
    except (ScopeSpecError, RemediationSpecError, p3c.CoverageError) as exc:
        raise LoadError(f"{type(exc).__name__}: {exc}") from exc
    rows, short = _load_rows(scope, base)
    return Inputs(
        scope=scope,
        index=index,
        remediation=remediation,
        corpus=corpus,
        rows=rows,
        crosslinks=_load_crosslinks(base),
        short_answer_problems=short,
    )


# ──────────────────────────────────────────────────────────────────────────
# 출력
# ──────────────────────────────────────────────────────────────────────────
def to_json(report: RemediationReport) -> dict[str, Any]:
    def ev(e: SignatureEvidence | None) -> dict[str, Any] | None:
        if e is None:
            return None
        return {
            "wrong_checked": e.wrong_checked,
            "correct_checked": e.correct_checked,
            "op_code_entries": e.op_code_entries,
            "first_confidence": e.first_confidence,
            "ladder": list(e.ladder),
            "ladder_resolved": list(e.ladder_resolved),
            "patterns": list(e.patterns),
            "action": e.action,
            "reason_type": e.reason_type,
            "pedagogy": e.pedagogy,
        }

    return {
        "produced": report.produced,
        "total": len(report.rows),
        "exit_code": report.exit_code,
        "rows": [
            {
                "mis_id": r.mis_id,
                "concept_code": r.concept_code,
                "status": r.status.value,
                "kebab_id": r.kebab_id,
                "reports_as": r.reports_as,
                "reaching_problems": r.reaching_problems,
                "failures": list(r.failures),
                "evidence": ev(r.evidence),
                "note": r.note,
            }
            for r in report.rows
        ],
        "working": {
            "wrong_picks": report.working.wrong_picks,
            "with_candidate": report.working.with_candidate,
            "dropped_unknown": dict(report.working.dropped_unknown),
            "dropped_below_floor": report.working.dropped_below_floor,
            "short_answer_problems": report.working.short_answer_problems,
        },
    }


def render(report: RemediationReport) -> str:
    lines = [
        f"P3-06 오답 → 교정 전략 커버리지 — 핵심 오개념 {report.produced}/{len(report.rows)} 산출"
        f" ({'충족' if report.exit_code == 0 else '미충족'})",
        "",
        "M-id    개념            상태      kebab                                  "
        "보고id  오답/정답  신뢰  사다리(1~4회)",
    ]
    for r in report.rows:
        e = r.evidence
        ladder = "→".join(x.replace("_", " ") for x in e.ladder) if e else "-"
        fx = f"{e.wrong_checked}/{e.correct_checked}" if e else "-"
        conf = f"{e.first_confidence:.2f}" if e and e.first_confidence is not None else "-"
        lines.append(
            f"{r.mis_id:<7} {r.concept_code:<14}  {r.status.value:<8}  {(r.kebab_id or '-'):<38} "
            f"{(r.reports_as or '-'):<7} {fx:<9}  {conf:<4}  {ladder}"
        )
        for failure in r.failures:
            lines.append(f"          ✗ {failure}")
        if r.note:
            lines.append(f"          · {r.note}")
    w = report.working
    lines += [
        "",
        "작동한 비율 — 객관식 오답 보기를 실제로 골랐을 때 런타임이 후보를 내는가:",
        f"  오답 보기 선택 {w.wrong_picks}건 중 후보 산출 {w.with_candidate}건",
    ]
    if w.dropped_unknown:
        lines.append(
            f"  카탈로그에 없는 id 라 조용히 버려진 {sum(w.dropped_unknown.values())}건: "
            f"{w.dropped_unknown}"
        )
    if w.dropped_below_floor:
        lines.append(f"  품질 게이트 미달로 버려진 {w.dropped_below_floor}건")
    lines.append(
        f"  단답형 {w.short_answer_problems}문항: 채널 없음"
        "(범위 밖 — 숫자 하나를 답해 오류 서명 등식이 안 만들어진다)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="P3-06 오답 → 교정 전략 커버리지 — 핵심 오개념 12개에 체인을 실제로 돌린다"
    )
    parser.add_argument("--spec", type=Path, default=None, help="범위 명세 YAML 경로")
    parser.add_argument("--data", type=Path, default=None, help="교정 전략 데이터 YAML 경로")
    parser.add_argument("--json", action="store_true", help="기계 판독 JSON 으로 출력")
    args = parser.parse_args(argv)
    try:
        report = evaluate(load_inputs(args.spec, args.data))
    except LoadError as exc:
        print(f"[적재 실패] {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(to_json(report), ensure_ascii=False, indent=2) if args.json else render(report)
    )
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
