"""대학 과목 간(inter-course) 선수 엣지 *제안* 검증 — S4-01 슬라이스 3 (남은 범위 ⒜).

배경(실측): 원자 백본 v1의 대학 노드 1,069개(세부개념 512) 중 과목 *안* 엣지는 479건이지만
과목 *간* 엣지는 2건뿐이라(수치해석↔미적분학 I) 대학 축이 과목별 고립 사슬 32개였다.
해석학 I → 해석학 II 같은 명백한 계열조차 미연결이다. 이 모듈은 그 사슬을 희소하게 잇는 *제안
파일*(`inter_course_edges_university_v1.json`)을 검증한다.

**정본 무변경 원칙**: 제안은 graph.json과 별개 파일이며, 이 모듈은 어떤 파일도 *쓰지 않는다*.
정본 병합은 검수 승인 후 별도 세션 소관이다(`docs/data/inter_course_edges_university_v1.md`).

슬라이스 1(`cross_band_edges.py`, 고등→대학)과 형태는 같고 방향 규칙이 다르다. 두 검증기는 제안
레코드 스키마·리포트 형태·DAG 탐색기를 공유한다.

검사 항목(성공 기준 = **error 0건**, warning은 통과):

  - **endpoint_exists**(error) — 양끝 code가 graph.json 노드에 실재.
  - **direction_inter_course**(error) — 양끝 모두 대학이고 *서로 다른 과목*이다. 같은 과목 안
    엣지(이미 정본에 481건)나 학교급을 넘는 엣지(슬라이스 1 소관)가 섞이는 것을 막는다.
  - **level_detail_concept**(error) — 양끝 모두 세부개념(단원·소단원 컨테이너 연결 금지).
  - **no_duplicate**(error) — 제안 내부 중복 + 기존 graph.json 엣지와의 중복.
  - **relation_prerequisite_only**(error) — 관계 타입 단일(관계 타입 폭발 금지).
  - **rationale_present**(error) — 교육적 근거가 빈 문자열이 아니다.
  - **pair_density_cap**(error) — 같은 (선수 과목 → 후속 과목) 쌍에 엣지가 상한(4건)을 넘지 않는다.
    32과목은 쌍이 992개라 전수 연결은 N²로 폭발한다(CLAUDE.md "관계 폭발 금지") — 상한은
    희소성을 *데이터 단계에서* 강제한다.
  - **acyclic_when_merged**(error) — 제안을 기존 엣지에 합쳤을 때 prerequisite DAG 유지.
    과목 *내부* 사슬이 이미 촘촘해서 과목 간 엣지가 순환을 만들기 쉽다(실측: 수치해석 앞쪽 개념으로
    미적분학 I 후반 개념에서 들어오는 엣지는 기존 NUMER-P01→CALC1-C16 때문에 순환이 된다).
  - **subject_coherence**(warning) — 허용 과목 쌍 표에 없는 쌍 — 차단이 아니라 검수자 확인 신호.

또한 *작동한 비율*을 말하는 측정 함수 두 개를 제공한다(CLAUDE.md "작동 신호 없는 알고리즘 부착
금지"): `university_reachability`(고등 세부개념에서 선수 방향으로 도달 가능한 대학 세부개념 수)와
`course_components`(과목을 노드로 본 연결 성분 수). "4축 활성"이 노드 존재가 아니라 도달 가능성으로
판정되게 하는 근거다.

구현 메모: 검사는 graph.json의 *원시 dict*를 대상으로 한다(Pydantic 모델 재구성 없음) — 뮤테이션
테스트가 불법 입력을 주입해야 하는데 모델로 올리면 검증기가 아니라 모델 생성에서 먼저 터진다.
"""

from __future__ import annotations

import argparse
import json
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from data_pipeline.atom_graph.cross_band_edges import (
    CrossBandValidationReport,
    _existing_pairs,
    _find_prerequisite_cycle,
    _node_index,
    proposal_edges,
)
from data_pipeline.atom_graph.models import AtomRelation, NodeLevel, SchoolLevel
from data_pipeline.atom_graph.validate import ValidationIssue

_ERROR: Final[str] = "error"
_WARNING: Final[str] = "warning"

DEFAULT_GRAPH_PATH: Final[Path] = Path("data/corpus/atom_graph_v1/graph.json")
DEFAULT_PROPOSAL_PATH: Final[Path] = Path(
    "data/corpus/atom_graph_v1/inter_course_edges_university_v1.json"
)

#: 제안 엣지의 출처 표기 — 기존 원자 백본·슬라이스 1 엣지와 구분되어야 출처 추적이 된다.
PROPOSAL_EVIDENCE: Final[str] = "S4-01 대학 과목간 저작 v1"

#: 선수 과목 → 후속 과목 한 쌍에 허용하는 엣지 상한. 희소 설계의 데이터 단계 집행이다.
MAX_EDGES_PER_COURSE_PAIR: Final[int] = 4

#: 허용 과목 쌍 표(subject_coherence·**warning 전용**) — "선수 과목 → 후속 과목"이 교육과정상
#: 자연스러운 계승 쌍인지 보는 *휴리스틱*이지 엣지 채택 기준이 아니다(채택은 사람 저작·검수).
#: 여기 없는 쌍은 "틀렸다"가 아니라 "검수자가 한 번 더 보라"는 신호다.
ALLOWED_COURSE_PAIRS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("미분기하학", "미분다양체리만기하"),
        ("미분방정식", "편미분방정식"),
        ("미적분학 I", "금융수학"),
        ("미적분학 I", "미분방정식"),
        ("미적분학 I", "미적분학 II"),
        ("미적분학 I", "복소해석학"),
        ("미적분학 I", "수치해석"),
        ("미적분학 I", "조합론그래프이론"),
        ("미적분학 I", "해석학 I"),
        ("미적분학 I", "확률론"),
        ("미적분학 II", "미분기하학"),
        ("미적분학 II", "미분다양체리만기하"),
        ("미적분학 II", "미분방정식"),
        ("미적분학 II", "복소해석학"),
        ("미적분학 II", "선형대수학 II"),
        ("미적분학 II", "편미분방정식"),
        ("복소해석학", "정수론(심화)"),
        ("선형대수학 I", "선형대수학 II"),
        ("선형대수학 I", "수치해석"),
        ("선형대수학 I", "암호론코딩이론"),
        ("선형대수학 I", "조합론그래프이론"),
        ("선형대수학 I", "함수해석학"),
        ("선형대수학 I", "현대대수학 II"),
        ("선형대수학 II", "미분기하학"),
        ("선형대수학 II", "미분방정식"),
        ("선형대수학 II", "수치해석"),
        ("선형대수학 II", "함수해석학"),
        ("선형대수학 II", "현대대수학 II"),
        ("실해석학(측도론)", "함수해석학"),
        ("위상수학 I", "대수기하 입문"),
        ("위상수학 I", "대수적 위상수학"),
        ("위상수학 I", "미분다양체리만기하"),
        ("위상수학 I", "위상수학 II"),
        ("위상수학 II", "대수적 위상수학"),
        ("위상수학 II", "미분다양체리만기하"),
        ("위상수학 II", "함수해석학"),
        ("정수론 입문", "암호론코딩이론"),
        ("정수론 입문", "정수론(심화)"),
        ("정수론 입문", "현대대수학 I"),
        ("정수론 입문", "현대대수학 II"),
        ("집합과 논리", "수리논리"),
        ("집합과 논리", "위상수학 I"),
        ("집합과 논리", "정수론 입문"),
        ("집합과 논리", "조합론그래프이론"),
        ("집합과 논리", "집합론"),
        ("집합과 논리", "해석학 I"),
        ("집합과 논리", "현대대수학 I"),
        ("집합과 논리", "확률론"),
        ("편미분방정식", "금융수학"),
        ("해석학 I", "복소해석학"),
        ("해석학 I", "수치해석"),
        ("해석학 I", "실해석학(측도론)"),
        ("해석학 I", "위상수학 I"),
        ("해석학 I", "해석학 II"),
        ("해석학 II", "수치해석"),
        ("해석학 II", "실해석학(측도론)"),
        ("해석학 II", "편미분방정식"),
        ("현대대수학 I", "갈루아 이론"),
        ("현대대수학 I", "암호론코딩이론"),
        ("현대대수학 I", "현대대수학 II"),
        ("현대대수학 II", "갈루아 이론"),
        ("현대대수학 II", "대수기하 입문"),
        ("현대대수학 II", "암호론코딩이론"),
        ("현대대수학 II", "정수론(심화)"),
        ("확률론", "금융수학"),
        ("확률론", "수리통계학"),
    }
)


def _label() -> str:
    return "대학 과목간 엣지 제안 검증"


def validate_inter_course_edges(
    edges: Sequence[Mapping[str, Any]],
    graph: Mapping[str, Any],
) -> CrossBandValidationReport:
    """대학 과목 간 엣지 제안 검증. `edges`는 제안 레코드(dict) 목록, `graph`는 정본 graph.json.

    어떤 파일도 쓰지 않는다(판정 전용). 성공 기준은 error 0건.
    """
    nodes = _node_index(graph)
    existing = _existing_pairs(graph)
    existing_set = set(existing)
    report = CrossBandValidationReport(
        proposal_count=len(edges),
        existing_edge_count=len(existing),
        label=_label(),
    )

    seen_in_proposal: set[tuple[str, str]] = set()
    mergeable_pairs: list[tuple[str, str]] = []
    per_course_pair: dict[tuple[str, str], int] = {}

    for record in edges:
        from_code = str(record.get("from_code", ""))
        to_code = str(record.get("to_code", ""))
        ref = f"{from_code}→{to_code}"

        # 1. endpoint_exists (error)
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

        # 2. direction_inter_course (error) — 양끝 대학 + 서로 다른 과목.
        #    끝점이 없으면 학교급·과목을 알 수 없으므로 1번 보고로 갈음한다(중복 보고 억제).
        if from_node is not None and to_node is not None:
            from_level = str(from_node.get("school_level", ""))
            to_level = str(to_node.get("school_level", ""))
            from_subject = str(from_node.get("subject_area", ""))
            to_subject = str(to_node.get("subject_area", ""))
            univ = SchoolLevel.UNIVERSITY.value
            if from_level != univ or to_level != univ:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=ref,
                        rule="direction_inter_course",
                        detail=(
                            f"양끝이 모두 대학이 아님: from={from_level or '미상'}, "
                            f"to={to_level or '미상'} — 학교급 경계 엣지는 슬라이스 1 소관"
                        ),
                    )
                )
            elif from_subject == to_subject:
                report.issues.append(
                    ValidationIssue(
                        severity=_ERROR,
                        ref=ref,
                        rule="direction_inter_course",
                        detail=(
                            f"같은 과목 안 엣지: {from_subject or '미상'} — "
                            "과목 내부 엣지는 정본에 이미 있다"
                        ),
                    )
                )
            else:
                course_pair = (from_subject, to_subject)
                per_course_pair[course_pair] = per_course_pair.get(course_pair, 0) + 1
                # 7. subject_coherence (warning) — 허용 과목 쌍 표.
                if course_pair not in ALLOWED_COURSE_PAIRS:
                    report.issues.append(
                        ValidationIssue(
                            severity=_WARNING,
                            ref=ref,
                            rule="subject_coherence",
                            detail=(
                                f"허용 과목 쌍 표에 없는 쌍: {from_subject} → {to_subject} "
                                "— 검수자 확인 필요"
                            ),
                        )
                    )

        # 3. level_detail_concept (error)
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

        # 4. no_duplicate (error)
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

        # 5. relation_prerequisite_only (error)
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

        # 6. rationale_present (error)
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

    # 8. pair_density_cap (error) — 과목 쌍별 상한(희소 설계 집행).
    for (from_subject, to_subject), count in sorted(per_course_pair.items()):
        if count > MAX_EDGES_PER_COURSE_PAIR:
            report.issues.append(
                ValidationIssue(
                    severity=_ERROR,
                    ref=f"{from_subject} → {to_subject}",
                    rule="pair_density_cap",
                    detail=(
                        f"과목 쌍 엣지 {count}건 > 상한 {MAX_EDGES_PER_COURSE_PAIR}건 "
                        "— 관계 폭발 방어"
                    ),
                )
            )

    # 9. acyclic_when_merged (error)
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


# ─────────────────────────────── 도달성 측정 ───────────────────────────────


@dataclass(frozen=True, slots=True)
class ReachabilityReport:
    """대학 축이 *실제로* K-12에서 도달 가능한 비율.

    "초·중·고+대학 4축 활성"을 노드 존재가 아니라 도달 가능성으로 말하기 위한 측정값이다.
    """

    university_atoms: int
    reached_atoms: int
    university_courses: int
    reached_courses: int
    course_components: int

    @property
    def atom_ratio(self) -> float:
        """도달한 대학 세부개념 / 전체 대학 세부개념."""
        return self.reached_atoms / self.university_atoms if self.university_atoms else 0.0

    def summary(self) -> str:
        return (
            f"대학 세부개념 도달 {self.reached_atoms}/{self.university_atoms} "
            f"({self.atom_ratio:.1%}) · 도달 과목 {self.reached_courses}/{self.university_courses} "
            f"· 과목 연결 성분 {self.course_components}개"
        )


def _university_concepts(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    univ = SchoolLevel.UNIVERSITY.value
    return [c for c in graph.get("concepts", []) if str(c.get("school_level")) == univ]


def university_reachability(
    graph: Mapping[str, Any],
    extra_pairs: Iterable[tuple[str, str]] = (),
) -> ReachabilityReport:
    """고등 세부개념에서 선수 방향(from→to)으로 도달 가능한 대학 세부개념을 센다.

    `extra_pairs`는 정본에 아직 없는 제안 엣지(병합 가정). 결정론·읽기 전용.
    """
    nodes = _node_index(graph)
    adj: dict[str, list[str]] = {}
    for from_code, to_code in _existing_pairs(graph) + list(extra_pairs):
        adj.setdefault(from_code, []).append(to_code)

    sources = [
        code
        for code, c in nodes.items()
        if str(c.get("school_level")) == SchoolLevel.HIGH.value
        and str(c.get("level")) == NodeLevel.ATOM.value
    ]
    seen: set[str] = set(sources)
    queue: deque[str] = deque(sources)
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, []):
            if nxt not in seen and nxt in nodes:
                seen.add(nxt)
                queue.append(nxt)

    univ_atoms = [
        c for c in _university_concepts(graph) if str(c.get("level")) == NodeLevel.ATOM.value
    ]
    reached_atoms = [c for c in univ_atoms if str(c["code"]) in seen]
    courses = {str(c.get("subject_area")) for c in univ_atoms}
    reached_courses = {str(c.get("subject_area")) for c in reached_atoms}
    return ReachabilityReport(
        university_atoms=len(univ_atoms),
        reached_atoms=len(reached_atoms),
        university_courses=len(courses),
        reached_courses=len(reached_courses),
        course_components=course_components(graph, extra_pairs),
    )


def course_components(
    graph: Mapping[str, Any],
    extra_pairs: Iterable[tuple[str, str]] = (),
) -> int:
    """대학 과목을 노드로 보고 과목 간 엣지(정본+제안)로 이은 연결 성분 수(약연결).

    과목 안 엣지는 같은 과목을 합치지 않는다 — 과목 노드 하나로 취급하므로 영향이 없다.
    """
    nodes = _node_index(graph)
    subjects = sorted(
        {
            str(c.get("subject_area"))
            for c in _university_concepts(graph)
            if str(c.get("level")) == NodeLevel.ATOM.value
        }
    )
    parent = {s: s for s in subjects}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for from_code, to_code in _existing_pairs(graph) + list(extra_pairs):
        a, b = nodes.get(from_code), nodes.get(to_code)
        if a is None or b is None:
            continue
        sa, sb = str(a.get("subject_area")), str(b.get("subject_area"))
        if (
            str(a.get("school_level")) == SchoolLevel.UNIVERSITY.value
            and str(b.get("school_level")) == SchoolLevel.UNIVERSITY.value
            and sa in parent
            and sb in parent
        ):
            parent[find(sa)] = find(sb)
    return len({find(s) for s in subjects})


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _pairs_of(edges: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    return [(str(e.get("from_code", "")), str(e.get("to_code", ""))) for e in edges]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 진입점 — 제안을 정본 graph.json에 대해 검증하고 도달성을 병기한다(exit 0/1)."""
    parser = argparse.ArgumentParser(
        description=(
            "대학 과목간 선수 엣지 제안 검증(S4-01 슬라이스 3). 읽기 전용 — 어떤 파일도 쓰지 "
            "않는다. error 0건이면 exit 0, 1건 이상이면 exit 1."
        )
    )
    parser.add_argument("--proposal", type=Path, default=DEFAULT_PROPOSAL_PATH)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument(
        "--also-proposal",
        type=Path,
        action="append",
        default=[],
        help="도달성 측정에만 함께 병합 가정할 다른 제안(예: 슬라이스 1 경계 엣지). 반복 가능.",
    )
    parser.add_argument("--max-examples", type=int, default=10)
    args = parser.parse_args(argv)

    for label, path in (
        ("제안", args.proposal),
        ("정본 그래프", args.graph),
        *[("추가 제안", p) for p in args.also_proposal],
    ):
        if not path.exists():
            print(f"[!] {label} 파일 없음: {path}")
            return 1

    proposal = _load_json(args.proposal)
    graph = _load_json(args.graph)
    edges = proposal_edges(proposal)
    report = validate_inter_course_edges(edges, graph)
    print(report.report_text(max_examples=args.max_examples))

    also: list[tuple[str, str]] = []
    for extra in args.also_proposal:
        also.extend(_pairs_of(proposal_edges(_load_json(extra))))
    print(f"  [도달성 · 정본만]          {university_reachability(graph).summary()}")
    if also:
        print(f"  [도달성 · +추가 제안]       {university_reachability(graph, also).summary()}")
    print(
        f"  [도달성 · +추가 +본 제안]   "
        f"{university_reachability(graph, also + _pairs_of(edges)).summary()}"
    )
    return 0 if report.success else 1


__all__ = [
    "ALLOWED_COURSE_PAIRS",
    "DEFAULT_GRAPH_PATH",
    "DEFAULT_PROPOSAL_PATH",
    "MAX_EDGES_PER_COURSE_PAIR",
    "PROPOSAL_EVIDENCE",
    "ReachabilityReport",
    "course_components",
    "university_reachability",
    "validate_inter_course_edges",
]


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
