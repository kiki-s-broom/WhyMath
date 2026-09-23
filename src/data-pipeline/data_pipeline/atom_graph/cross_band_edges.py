"""고등→대학 학교급 경계 엣지 *제안* 검증 — S4-01 첫 슬라이스.

배경(실측): 원자 백본 v1(`data/corpus/atom_graph_v1/graph.json`)은 개념 2,683·엣지 2,210이고
학교급 경계를 넘는 엣지는 20건(0.90%)뿐이다. 그중 **고등→대학은 0건**이라 대학 원자 1,069개가
K-12 쪽에서 도달 불가능한 섬으로 남아 있다. 이 모듈은 그 섬을 잇는 *제안 파일*
(`cross_band_edges_university_v1.json`)을 검증한다.

**정본 무변경 원칙**: 제안은 graph.json과 별개 파일이며, 이 모듈은 어떤 파일도 *쓰지 않는다*
(읽기·판정 전용). 정본 병합은 검수 승인 후 별도 세션 소관이다
(`docs/data/cross_band_edges_university_v1.md`).

검사 항목(성공 기준 = **error 0건**, warning은 통과 — atom_graph/validate.py §3 미러):

  - **endpoint_exists**(error) — 양끝 code가 graph.json 노드에 실재.
  - **direction_high_to_university**(error) — from=고등, to=대학. 역방향·동급은 error.
  - **level_detail_concept**(error) — 양끝 모두 level=세부개념(단원·소단원 컨테이너 연결 금지).
  - **no_duplicate**(error) — 제안 내부 중복 + *기존 graph.json 엣지와의* 중복.
  - **acyclic_when_merged**(error) — 제안을 기존 엣지에 합쳤을 때 prerequisite DAG 유지.
  - **subject_coherence**(warning) — from/to의 subject_area 쌍이 허용 계열표에 있는지.
  - **rationale_present**(error) — 교육적 근거가 빈 문자열이 아니다.
  - **relation_prerequisite_only**(error) — 관계 타입은 `prerequisite` 단일(CLAUDE.md "관계 타입
    폭발 금지"의 기계 집행. 위 7종 명세에 더한 항목 — 신규 relation 타입 유입을 데이터
    단계에서 막는다).

구현 메모: 검사는 graph.json의 *원시 dict*를 대상으로 한다(`AtomConcept`/`AtomEdge` 재구성 없음).
뮤테이션 테스트가 "존재하지 않는 code"·"컨테이너 code" 같은 **불법 입력을 주입**해야 하는데,
Pydantic 모델로 올리면 그 주입이 검증기가 아니라 모델 생성에서 먼저 터져 *검증기의 변별력을 측정할
수 없기* 때문이다. 제안 레코드는 `AtomEdge` 필드 + `rationale` 1개를 더 갖는다(`AtomEdge`는
extra="forbid"라 그대로 모델에 넣을 수 없다 — 병합 시 처리 방식은 위 문서 §병합 조건 참조).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from data_pipeline.atom_graph.models import AtomRelation, NodeLevel, SchoolLevel
from data_pipeline.atom_graph.validate import ValidationIssue

_ERROR: Final[str] = "error"
_WARNING: Final[str] = "warning"

DEFAULT_GRAPH_PATH: Final[Path] = Path("data/corpus/atom_graph_v1/graph.json")
DEFAULT_PROPOSAL_PATH: Final[Path] = Path(
    "data/corpus/atom_graph_v1/cross_band_edges_university_v1.json"
)

#: 제안 엣지의 출처 표기 — 기존 원자 백본 엣지("원자 백본 v1")와 구분되어야 출처 추적이 된다.
PROPOSAL_EVIDENCE: Final[str] = "S4-01 고→대 경계 저작 v1"

#: 허용 과목 계열표(subject_coherence·**warning 전용**). "고등 과목 → 대학 과목"이 교육적으로
#: 자연스러운 계승 쌍인지 보는 *휴리스틱*이지 엣지 채택 기준이 아니다(채택은 사람 저작·검수).
#: 여기 없는 쌍은 "틀렸다"가 아니라 "검수자가 한 번 더 보라"는 신호다.
ALLOWED_SUBJECT_PAIRS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # 미적분 계열 — 고등 극한·미분·적분이 대학 미적분학/해석학으로 정밀화된다.
        ("미적분Ⅰ", "미적분학 I"),
        ("미적분Ⅰ", "해석학 I"),
        ("미적분Ⅱ", "미적분학 I"),
        ("미적분Ⅱ", "미적분학 II"),
        ("미적분Ⅱ", "해석학 I"),
        # 기하·벡터 계열 — 공간벡터·평면 방정식이 다변수 미적분/선형대수로 이어진다.
        ("기하", "미적분학 II"),
        ("기하", "선형대수학 I"),
        # 대수·행렬 계열.
        ("공통수학1", "선형대수학 I"),
        ("대수", "선형대수학 I"),
        ("대수", "현대대수학 I"),
        # 집합·논리·증명 계열.
        ("공통수학2", "집합과 논리"),
        ("공통수학2", "집합론"),
        ("대수", "집합과 논리"),
        # 확률·통계 계열.
        ("확률과 통계", "확률론"),
        ("확률과 통계", "수리통계학"),
    }
)


@dataclass(slots=True)
class CrossBandValidationReport:
    """경계 엣지 제안 검증 결과(atom_graph/validate.py의 리포트 형태 미러)."""

    proposal_count: int = 0
    existing_edge_count: int = 0
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
        """rule별 이슈 건수(결정론 — rule 이름 정렬)."""
        tally: dict[str, int] = {}
        for issue in self.issues:
            tally[issue.rule] = tally.get(issue.rule, 0) + 1
        return dict(sorted(tally.items()))

    def rules_hit(self) -> set[str]:
        """이슈가 1건이라도 난 rule 집합(뮤테이션 테스트 단언용)."""
        return {i.rule for i in self.issues}

    def summary(self) -> str:
        """사람 가독 요약(PASS/FAIL = error 없음/있음)."""
        verdict = "PASS" if self.success else "FAIL"
        return (
            f"경계 엣지 제안 검증[{verdict}]: 제안 {self.proposal_count}건, "
            f"기존 엣지 {self.existing_edge_count}건, "
            f"error {len(self.errors)}개, warning {len(self.warnings)}개"
        )

    def report_text(self, *, max_examples: int = 10) -> str:
        """rule별 집계 + 구체 위반 예시. warning은 통과 처리, error만 실패."""
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


def _find_prerequisite_cycle(pairs: Sequence[tuple[str, str]]) -> list[str] | None:
    """(from→to) 쌍 목록에서 사이클 1건 탐지(DFS·명시 스택).

    atom_graph/validate.py의 `_find_prerequisite_cycle`과 같은 알고리즘이되 입력이 모델이 아니라
    *원시 쌍*이다(제안은 아직 `AtomEdge`가 아니다 — 모듈 docstring의 구현 메모 참조).
    재귀 대신 명시 스택: 원자 백본은 2,683 노드라 깊은 체인에서 재귀 한계를 피한다.

    Returns: 사이클을 이루는 노드 경로(닫힘 노드 반복 포함) 또는 None.
    """
    adj: dict[str, list[str]] = {}
    for from_code, to_code in pairs:
        adj.setdefault(from_code, []).append(to_code)

    white, gray, black = 0, 1, 2
    color: dict[str, int] = {}

    for start in list(adj):
        if color.get(start, white) != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        color[start] = gray
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


def _node_index(graph: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """graph.json concepts → code 인덱스."""
    return {str(c["code"]): c for c in graph.get("concepts", [])}


def _existing_pairs(graph: Mapping[str, Any]) -> list[tuple[str, str]]:
    """graph.json의 prerequisite 엣지 (from, to) 쌍 목록(원본 순서 보존)."""
    return [
        (str(e["from_code"]), str(e["to_code"]))
        for e in graph.get("edges", [])
        if str(e.get("relation", AtomRelation.PREREQUISITE.value))
        == AtomRelation.PREREQUISITE.value
    ]


def proposal_edges(proposal: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """제안 파일 payload → 엣지 레코드 목록(`edges` 키·`_meta` 제외)."""
    edges = proposal.get("edges", [])
    if not isinstance(edges, list):
        raise TypeError("제안 파일의 'edges'는 리스트여야 합니다.")
    return list(edges)


def validate_cross_band_edges(
    edges: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
) -> CrossBandValidationReport:
    """고→대 경계 엣지 제안 검증. `edges`는 제안 레코드(dict) 목록, `graph`는 정본 graph.json.

    어떤 파일도 쓰지 않는다(판정 전용). 성공 기준은 error 0건.
    """
    nodes = _node_index(graph)
    existing = _existing_pairs(graph)
    existing_set = set(existing)
    report = CrossBandValidationReport(
        proposal_count=len(edges),
        existing_edge_count=len(existing),
    )

    seen_in_proposal: set[tuple[str, str]] = set()
    mergeable_pairs: list[tuple[str, str]] = []

    for record in edges:
        from_code = str(record.get("from_code", ""))
        to_code = str(record.get("to_code", ""))
        ref = f"{from_code}→{to_code}"

        # 1. endpoint_exists (error) — 양끝이 정본 노드에 실재.
        from_node = nodes.get(from_code)
        to_node = nodes.get(to_code)
        for label, code, node in (("from", from_code, from_node), ("to", to_code, to_node)):
            if node is None:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=ref,
                        rule="endpoint_exists",
                        detail=f"{label} code가 graph.json 노드에 없음: {code!r}",
                    )
                )

        # 2. direction_high_to_university (error) — from=고등, to=대학.
        #    끝점이 없으면 학교급을 알 수 없으므로 1번 보고로 갈음한다(중복 보고 억제).
        if from_node is not None and to_node is not None:
            from_level = str(from_node.get("school_level", ""))
            to_level = str(to_node.get("school_level", ""))
            if from_level != SchoolLevel.HIGH.value or to_level != SchoolLevel.UNIVERSITY.value:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=ref,
                        rule="direction_high_to_university",
                        detail=(
                            f"고등→대학이 아님: from={from_level or '미상'}, "
                            f"to={to_level or '미상'}"
                        ),
                    )
                )

        # 3. level_detail_concept (error) — 양끝 모두 세부개념(컨테이너 연결 금지).
        for label, code, node in (("from", from_code, from_node), ("to", to_code, to_node)):
            if node is None:
                continue
            level = str(node.get("level", ""))
            if level != NodeLevel.ATOM.value:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=ref,
                        rule="level_detail_concept",
                        detail=(
                            f"{label} 노드가 세부개념이 아님: {code}={level or '미상'} "
                            "— 컨테이너(단원·소단원) 연결 금지"
                        ),
                    )
                )

        # 4. no_duplicate (error) — 제안 내부 중복 + 기존 정본 엣지와의 중복.
        pair = (from_code, to_code)
        if pair in seen_in_proposal:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=ref,
                    rule="no_duplicate",
                    detail="제안 내부 중복 — 같은 (from, to) 쌍이 2회 이상",
                )
            )
        seen_in_proposal.add(pair)
        if pair in existing_set:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=ref,
                    rule="no_duplicate",
                    detail="기존 graph.json 엣지와 중복 — 정본에 이미 존재",
                )
            )
        mergeable_pairs.append(pair)

        # 5. relation_prerequisite_only (error) — 관계 타입 단일(폭발 금지).
        relation = str(record.get("relation", ""))
        if relation != AtomRelation.PREREQUISITE.value:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=ref,
                    rule="relation_prerequisite_only",
                    detail=(
                        f"허용되지 않은 relation: {relation or '미지정'!r} "
                        f"— {AtomRelation.PREREQUISITE.value}만 허용"
                    ),
                )
            )

        # 6. rationale_present (error) — 교육적 근거 필수.
        rationale = str(record.get("rationale", "") or "").strip()
        if not rationale:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=ref,
                    rule="rationale_present",
                    detail="rationale이 비어 있음 — 교육적 근거 없는 엣지는 채택 불가",
                )
            )

        # 7. subject_coherence (warning) — 과목 계열 휴리스틱.
        if from_node is not None and to_node is not None:
            subject_pair = (
                str(from_node.get("subject_area", "")),
                str(to_node.get("subject_area", "")),
            )
            if subject_pair not in ALLOWED_SUBJECT_PAIRS:
                report.issues.append(
                    ValidationIssue(
                        severity=_WARNING,
                        ref=ref,
                        rule="subject_coherence",
                        detail=(
                            f"허용 계열표에 없는 과목 쌍: {subject_pair[0] or '미상'} → "
                            f"{subject_pair[1] or '미상'} — 검수자 확인 필요"
                        ),
                    )
                )

    # 8. acyclic_when_merged (error) — 제안 + 기존 엣지 병합 시 DAG 유지.
    cycle = _find_prerequisite_cycle(existing + mergeable_pairs)
    if cycle is not None:
        report.issues.append(
            ValidationIssue(
                severity=_ERROR,
                ref=" → ".join(cycle),
                rule="acyclic_when_merged",
                detail="제안을 병합하면 순환 선수관계 발생 — 학습 경로 구성 불가",
            )
        )

    return report


def _load_json(path: Path) -> dict[str, Any]:
    """UTF-8 JSON 로드(경로 부재는 호출측에서 판정)."""
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — 제안 파일을 정본 graph.json에 대해 검증하고 exit 0/1로 판정."""
    parser = argparse.ArgumentParser(
        description=(
            "고등→대학 경계 엣지 제안 검증(S4-01). 읽기 전용 — 어떤 파일도 쓰지 않는다. "
            "error 0건이면 exit 0, 1건 이상이면 exit 1."
        )
    )
    parser.add_argument(
        "--proposal",
        type=Path,
        default=DEFAULT_PROPOSAL_PATH,
        help=f"제안 JSON 경로(기본: {DEFAULT_PROPOSAL_PATH})",
    )
    parser.add_argument(
        "--graph",
        type=Path,
        default=DEFAULT_GRAPH_PATH,
        help=f"정본 graph.json 경로(기본: {DEFAULT_GRAPH_PATH})",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=10,
        help="리포트에 출력할 위반 예시 최대 건수(기본: 10)",
    )
    args = parser.parse_args(argv)

    for label, path in (("제안", args.proposal), ("정본 그래프", args.graph)):
        if not path.exists():
            print(f"[!] {label} 파일 없음: {path}")
            return 1

    proposal = _load_json(args.proposal)
    graph = _load_json(args.graph)
    report = validate_cross_band_edges(proposal_edges(proposal), graph)
    print(report.report_text(max_examples=args.max_examples))
    return 0 if report.success else 1


__all__ = [
    "ALLOWED_SUBJECT_PAIRS",
    "DEFAULT_GRAPH_PATH",
    "DEFAULT_PROPOSAL_PATH",
    "PROPOSAL_EVIDENCE",
    "CrossBandValidationReport",
    "proposal_edges",
    "validate_cross_band_edges",
]


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
