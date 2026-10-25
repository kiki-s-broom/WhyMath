"""원자 백본 그래프 검증 — concept_graph/validate.py 규칙 재사용 + 원자 백본 신규 invariant.

정본: `docs/data/atom_graph_v1.md` + 마이그레이션 플랜 Phase 1.

구조 invariant(빈 코드·난이도 범위·강도 범위)는 `AtomConcept`/`AtomEdge` 생성 시점(Pydantic)에서
강제되므로, 여기서는 단일 모델로 알 수 없는 *그래프 레벨* invariant을 검증한다(concept_graph와
같은 분담):

  - **prerequisite_cycle**(error) — 순환 선수관계 = 학습 경로 불능(DAG 보장·concept_graph와 동일).
  - **atom_id_unique**(error) — 원자 노드 code 유일(충돌 0 — 매 실행 판정).
  - **dangling_edge_endpoint**(error) — 원자ID 엣지 양끝이 원자 노드 집합에 존재.
  - **parent_exists**(error) — 모든 parent_code가 노드 집합에 존재(계층 무결성).
  - **subunit_name_consistency**(error) — 같은 소단원코드 = 같은 소단원명.
  - **standard_exists**(warning·신규) — 원자 standard_codes(정규화 후)가 standards.json code
    집합에 존재(대학 [] 제외). 미매칭은 리포트(에러 아님 — 외부 코퍼스 의존).

성공 기준은 **error 0건**(warning은 그래프 구축을 막지 않음 — concept_graph §3 미러).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from data_pipeline.atom_graph.models import (
    AtomConcept,
    AtomEdge,
    AtomRelation,
    NodeLevel,
)
from data_pipeline.atom_graph.transform import TransformResult

_ERROR = "error"
_WARNING = "warning"


@dataclass(slots=True)
class ValidationIssue:
    """검증 항목 1건."""

    severity: str  # "error" | "warning"
    ref: str  # code 또는 "from→to" 등 대상 식별
    rule: str
    detail: str


@dataclass(slots=True)
class GraphValidationReport:
    """그래프 검증 결과(concept_graph 리포트 형태 미러)."""

    node_count: int = 0
    edge_count: int = 0
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        """error 심각도 이슈."""
        return [i for i in self.issues if i.severity == _ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """warning 심각도 이슈."""
        return [i for i in self.issues if i.severity == _WARNING]

    @property
    def success(self) -> bool:
        """error가 없으면 성공(warning 허용)."""
        return len(self.errors) == 0

    def counts_by_rule(self) -> dict[str, int]:
        """rule별 이슈 건수(결정론적 — rule 이름 정렬)."""
        tally: dict[str, int] = {}
        for issue in self.issues:
            tally[issue.rule] = tally.get(issue.rule, 0) + 1
        return dict(sorted(tally.items()))

    def summary(self) -> str:
        """사람 가독 요약(PASS/FAIL = error 없음/있음)."""
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"그래프 검증[{verdict}]: 노드 {self.node_count}개, 엣지 {self.edge_count}개, "
            f"error {len(self.errors)}개, warning {len(self.warnings)}개"
        )

    def report_text(self, *, max_examples: int = 10) -> str:
        """rule별 집계 + 구체 위반 예시(실데이터 리포트). warning은 통과 처리, error만 실패."""
        lines = [self.summary()]
        tally = self.counts_by_rule()
        if tally:
            lines.append("  [rule별 집계]")
            for rule, count in tally.items():
                lines.append(f"    - {rule}: {count}건")
        for severity, label in ((_ERROR, "error"), (_WARNING, "warning")):
            picked = [i for i in self.issues if i.severity == severity]
            if not picked:
                continue
            lines.append(f"  [{label} 예시 (최대 {max_examples})]")
            for issue in picked[:max_examples]:
                lines.append(f"    [{label}] {issue.rule} | {issue.ref} | {issue.detail}")
        return "\n".join(lines)


def _find_prerequisite_cycle(edges: Sequence[AtomEdge]) -> list[str] | None:
    """선수 엣지 그래프(from=선수→to=후행)에서 사이클 1건 탐지(DFS·반복 스택).

    재귀 대신 명시 스택을 쓴다 — 원자 백본은 수천 노드라(`docs/data/corpus_facts.md`의
    `atom_graph.nodes`) 깊은 체인에서 재귀 한계를 피한다.
    Returns: 사이클을 이루는 노드 경로(닫힘 노드 반복 포함) 또는 None.
    """
    adj: dict[str, list[str]] = {}
    for edge in edges:
        if edge.relation == AtomRelation.PREREQUISITE.value:
            adj.setdefault(edge.from_code, []).append(edge.to_code)

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {}

    for start in list(adj):
        if color.get(start, white) != white:
            continue
        # 명시 스택 DFS. 각 프레임: (노드, 자식 iterator).
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        color[start] = gray
        path.append(start)
        while stack:
            node, child_idx = stack[-1]
            children = adj.get(node, [])
            if child_idx < len(children):
                stack[-1] = (node, child_idx + 1)
                nxt = children[child_idx]
                state = color.get(nxt, white)
                if state == gray:  # back-edge → 사이클
                    return path[path.index(nxt) :] + [nxt]
                if state == white:
                    color[nxt] = gray
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = black
                path.pop()
                stack.pop()
    return None


def validate_graph(
    concepts: Sequence[AtomConcept],
    edges: Sequence[AtomEdge],
    *,
    known_standard_codes: Iterable[str] | None = None,
) -> GraphValidationReport:
    """원자 백본 그래프의 그래프 레벨 invariant 검증.

    `known_standard_codes`(standards.json code 집합)를 주면 standard_exists(warning)를 검사한다
    (미지정 시 외부 코퍼스 없어 건너뜀). 구조 invariant은 모델 생성 시 이미 강제됨.
    """
    report = GraphValidationReport(node_count=len(concepts), edge_count=len(edges))
    node_ids = {c.code for c in concepts}
    atom_ids = {c.code for c in concepts if c.level == NodeLevel.ATOM.value}

    # 1. prerequisite 사이클 (error)
    cycle = _find_prerequisite_cycle(edges)
    if cycle is not None:
        report.issues.append(
            ValidationIssue(
                severity=_ERROR,
                ref=" → ".join(cycle),
                rule="prerequisite_cycle",
                detail="순환 선수관계 — 학습 경로 구성 불가",
            )
        )

    # 2. atom_id_unique (error) — 원자 노드 code 충돌 0.
    atom_counts: dict[str, int] = {}
    for concept in concepts:
        if concept.level == NodeLevel.ATOM.value:
            atom_counts[concept.code] = atom_counts.get(concept.code, 0) + 1
    for code, count in sorted(atom_counts.items()):
        if count > 1:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=code,
                    rule="atom_id_unique",
                    detail=f"원자ID 중복 {count}건 — join 붕괴",
                )
            )

    # 3. dangling_edge_endpoint (error) — 원자ID 엣지 양끝이 원자 노드에 존재.
    for edge in edges:
        for endpoint in (edge.from_code, edge.to_code):
            if endpoint not in atom_ids:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=f"{edge.from_code}→{edge.to_code}",
                        rule="dangling_edge_endpoint",
                        detail=f"엣지 끝점이 원자 노드에 없음: {endpoint}",
                    )
                )

    # 4. parent_exists (error) — 모든 parent_code가 노드 집합에 존재.
    for concept in concepts:
        if concept.parent_code is not None and concept.parent_code not in node_ids:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=concept.code,
                    rule="parent_exists",
                    detail=f"parent_code가 노드에 없음: {concept.parent_code}",
                )
            )

    # 5. subunit_name_consistency (error) — 같은 소단원코드 = 같은 소단원명.
    #    원자의 (subunit_code, subunit)을 모아 코드당 명칭이 1종인지 본다.
    names_by_subcode: dict[str, set[str]] = {}
    for concept in concepts:
        if concept.level != NodeLevel.ATOM.value:
            continue
        if concept.subunit_code is not None and concept.subunit is not None:
            names_by_subcode.setdefault(concept.subunit_code, set()).add(concept.subunit)
    for subcode, names in sorted(names_by_subcode.items()):
        if len(names) > 1:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=subcode,
                    rule="subunit_name_consistency",
                    detail=f"같은 소단원코드에 다른 소단원명: {sorted(names)!r}",
                )
            )

    # 6. standard_exists (warning·신규) — standard_codes가 standards.json에 존재(대학 [] 제외).
    if known_standard_codes is not None:
        known = set(known_standard_codes)
        for concept in concepts:
            if concept.level != NodeLevel.ATOM.value:
                continue
            for code in concept.standard_codes:
                if code not in known:
                    report.issues.append(
                        ValidationIssue(
                            severity=_WARNING,
                            ref=concept.code,
                            rule="standard_exists",
                            detail=f"연결성취기준이 standards에 없음: {code}",
                        )
                    )

    return report


def validate_dataset(
    result: TransformResult,
    *,
    known_standard_codes: Iterable[str] | None = None,
) -> GraphValidationReport:
    """`TransformResult` → 그래프 검증(transform→validate 얇은 어댑터)."""
    return validate_graph(
        result.concepts,
        result.edges,
        known_standard_codes=known_standard_codes,
    )


__all__ = [
    "GraphValidationReport",
    "ValidationIssue",
    "validate_dataset",
    "validate_graph",
]
