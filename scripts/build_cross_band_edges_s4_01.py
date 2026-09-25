#!/usr/bin/env python3
"""S4-01 첫 슬라이스 — 고등→대학 경계 엣지 제안 파일 생성(결정론·멱등).

무엇을 만드나: `data/corpus/atom_graph_v1/cross_band_edges_university_v1.json`.
원자 백본 v1의 정본 `graph.json`은 **읽기만** 한다 — 이 스크립트는 정본을 수정하지 않는다.

왜 별도 파일인가: 고→대 엣지 24건은 *교육적 저작물*이라 사람 검수(게이트
`G-s401-uni-boundary-edge-review`) 전에는 정본에 들어가면 안 된다. 제안 파일로 착지시키고
`data_pipeline.atom_graph.cross_band_edges` 검증기가 기계 검사(양끝 실재·방향·수준·중복·DAG·
과목 계열·근거)를 건다. 정본 병합은 승인 후 별도 세션 소관이다.

결정론: 저작 목록(`AUTHORED_EDGES`)은 이 파일에 상수로 박혀 있고, 노드명(`from_name`/`to_name`)은
graph.json에서 *조회해* 채운다(손 타이핑 금지 — 정본과의 불일치를 구조적으로 차단). 같은 입력이면
같은 바이트가 나온다(테스트 `test_regeneration_is_byte_identical`가 동결).

사용:
    python3 scripts/build_cross_band_edges_s4_01.py            # 생성·기록
    python3 scripts/build_cross_band_edges_s4_01.py --check    # 드라이런(기록 없이 차이만 판정)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

_REPO: Final[Path] = Path(__file__).resolve().parents[1]
GRAPH_PATH: Final[Path] = _REPO / "data" / "corpus" / "atom_graph_v1" / "graph.json"
OUTPUT_PATH: Final[Path] = (
    _REPO / "data" / "corpus" / "atom_graph_v1" / "cross_band_edges_university_v1.json"
)

TASK_ID: Final[str] = "S4-01-math-k12-complete"
#: 기존 원자 백본 엣지("원자 백본 v1")와 구분되는 출처 표기 — 출처 추적이 가능해야 한다.
EVIDENCE: Final[str] = "S4-01 고→대 경계 저작 v1"
#: 기존 경계 엣지 레코드 형태를 그대로 따른다(`graph.json` 엣지 스키마 미러).
RELATION: Final[str] = "prerequisite"
RELATION_SUBTYPE: Final[str] = "학교급간(추정)"
STRENGTH: Final[float] = 0.8

#: 저작 확정 목록 — (from_code=고등 원자, to_code=대학 원자, rationale=교육적 근거).
#: **교육적 판단은 확정됐다. 이 목록의 추가·삭제·코드 변경·근거 문구 수정은 금지**이며,
#: 변경은 게이트 검수 결과로만 이뤄진다(사람 저작물).
AUTHORED_EDGES: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "12미적Ⅰ-01-01-1",
        "CALC1-C03",
        '극한 개념의 직접 계승 — 고등 "극한값≠함숫값"이 대학 ε-δ 정의의 "극한값은 함숫값과 독립"으로 정밀화된다',  # noqa: E501 — 저작 원문(줄바꿈 금지)
    ),
    (
        "12미적Ⅰ-01-02-1",
        "CALC1-P01",
        "0/0 부정형 처리 절차의 계승 — 인수분해·약분 기법이 그대로 쓰인다",
    ),
    (
        "12미적Ⅰ-01-03-1",
        "CALC1-C05",
        '연속의 세 조건이 대학 "연속은 극한값=함숫값"의 선행 정의다',
    ),
    (
        "12미적Ⅰ-02-01-1",
        "CALC1-P05",
        "미분계수(순간변화율)의 차분몫 극한이 대학 도함수 정의 절차의 선행이다",
    ),
    (
        "12미적Ⅰ-02-02-1",
        "CALC1-C09",
        '고등 "미분가능성과 연속성"이 대학 "미분가능이 도함수 연속을 보장하지 않는다"의 선행이다',
    ),
    (
        "12미적Ⅰ-02-03-2",
        "CALC1-C08",
        '"도함수는 함수다"가 dy/dx를 분수로 오해하지 않는 표기 이해의 선행이다',
    ),
    (
        "12미적Ⅰ-02-04-2",
        "CALC1-P06",
        "곱의 미분 오개념(곱의 미분≠미분의 곱)이 동일 축으로 계승된다",
    ),
    (
        "12미적Ⅰ-03-01-1",
        "CALC1-P14",
        "부정적분의 +C 개념이 대학 적분상수 누락 방지의 선행이다",
    ),
    (
        "12미적Ⅰ-03-03-3",
        "CALC1-C18",
        '정적분의 부호 있는 넓이 개념이 대학 "넓이가 아니라 부호 있는 합"의 선행이다',
    ),
    (
        "12미적Ⅰ-03-04-1",
        "CALC1-C19",
        "미적분 기본정리(부정적분-정적분 관계)가 대학 FTC 연속 전제 논의의 선행이다",
    ),
    (
        "12미적Ⅱ-01-04-1",
        "CALC1-C24",
        '급수 일반항 판정의 한계 인식이 대학 "일반항→0은 필요조건일 뿐"으로 계승된다',
    ),
    (
        "12미적Ⅱ-01-01-1",
        "ANAL1-C04",
        "수열의 수렴·발산 개념이 해석학 ε-N 수렴 정의의 선행이다",
    ),
    (
        "12기하03-03-1",
        "CALC2-C04",
        "내적이 스칼라라는 사실과 수직 판정이 대학 다변수 내적의 선행이다",
    ),
    (
        "12기하03-05-2",
        "CALC2-C07",
        "평면=점+법선벡터 표현이 대학 평면 방정식 계수의 법선 해석으로 계승된다",
    ),
    (
        "12기하03-04-2",
        "CALC2-C06",
        "직선=점+방향벡터 표현이 공간 직선의 꼬인 위치 판정의 선행이다",
    ),
    (
        "10공수1-04-02-1",
        "LINA1-P02",
        "행렬 연산의 AB≠BA가 대학 행렬곱 비가환성으로 직접 계승된다",
    ),
    (
        "10공수1-02-08-2",
        "LINA1-C04",
        "연립해가 동시에 참이라는 이해가 해집합 구조(0·1·무한)의 선행이다",
    ),
    (
        "10공수1-04-01-1",
        "LINA1-R02",
        "행렬의 행×열 구조가 행렬을 기하변환으로 읽는 표상의 선행이다",
    ),
    (
        "10공수2-02-02-1",
        "SETLOG-C08",
        "부분집합·포함관계가 공집합·자기자신 부분집합 판정의 선행이다",
    ),
    (
        "10공수2-02-03-1",
        "SETLOG-P07",
        "집합 연산이 드모르간 법칙 적용의 선행이다",
    ),
    (
        "10공수2-02-04-1",
        "SETLOG-P02",
        '"모든"/"어떤" 한정 명제가 대학 한정기호 순서 구분의 선행이다',
    ),
    (
        "10공수2-02-07-1",
        "SETLOG-C07",
        "고등 귀류법이 대학 모순증명(결론 부정)의 선행이다",
    ),
    (
        "12대수03-07-1",
        "SETLOG-P04",
        "수학적 귀납법 두 단계가 대학 귀납법 기저단계 필수성의 선행이다",
    ),
    (
        "12확통02-01-1",
        "PROB-C03",
        "확률의 기본 성질이 콜모고로프 공리(비음·정규·가산가법)의 선행이다",
    ),
)


def _sha256(path: Path) -> str:
    """파일 sha256(제안이 어느 정본 스냅샷을 전제로 하는지 고정 — 정본이 바뀌면 재검수 신호)."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_payload(graph: dict[str, Any], graph_sha256: str) -> dict[str, Any]:
    """저작 목록 + 정본 노드명 조회 → 제안 payload(순수 함수·결정론).

    노드명은 graph.json에서 조회한다. 코드가 정본에 없으면 즉시 실패한다 — 이름을 비워 두고
    넘어가면 "조회해 채운다"는 규율이 조용히 무너지기 때문이다.
    """
    nodes = {str(c["code"]): c for c in graph.get("concepts", [])}
    edges: list[dict[str, Any]] = []
    for from_code, to_code, rationale in AUTHORED_EDGES:
        missing = [c for c in (from_code, to_code) if c not in nodes]
        if missing:
            raise KeyError(f"정본 graph.json에 없는 code: {missing!r} — 저작 목록 점검 필요")
        edges.append(
            {
                "from_code": from_code,
                "from_name": str(nodes[from_code]["name"]),
                "to_code": to_code,
                "to_name": str(nodes[to_code]["name"]),
                "relation": RELATION,
                "relation_subtype": RELATION_SUBTYPE,
                "school_link": True,
                "strength": STRENGTH,
                "evidence": EVIDENCE,
                "rationale": rationale,
            }
        )
    return {
        "_meta": {
            "generated_by": "scripts/build_cross_band_edges_s4_01.py",
            "task": TASK_ID,
            "status": "proposal — 검수 전 정본 미병합",
            "edge_count": len(edges),
            "source_graph_sha256": graph_sha256,
        },
        "edges": edges,
    }


def serialize(payload: dict[str, Any]) -> str:
    """제안 파일 직렬화(atom_graph 코퍼스 관례 미러 — ensure_ascii=False·indent=2·끝 개행)."""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def run(*, check: bool) -> int:
    """생성(또는 드라이런). 반환값이 그대로 종료 코드."""
    graph: dict[str, Any] = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    text = serialize(build_payload(graph, _sha256(GRAPH_PATH)))

    if check:
        if not OUTPUT_PATH.exists():
            print(f"[--check] 산출물 없음: {OUTPUT_PATH}")
            return 1
        current = OUTPUT_PATH.read_text(encoding="utf-8")
        if current != text:
            print(f"[--check] 산출물이 재생성 결과와 다릅니다: {OUTPUT_PATH}")
            return 1
        print(f"[--check] 재생성 결과와 바이트 동일: {OUTPUT_PATH}({len(AUTHORED_EDGES)}건)")
        return 0

    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"기록: {OUTPUT_PATH}(엣지 {len(AUTHORED_EDGES)}건 · 정본 무변경)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S4-01 고→대 경계 엣지 제안 파일 생성(결정론·정본 graph.json 무변경)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="기록하지 않고 기존 산출물이 재생성 결과와 같은지만 판정(다르면 exit 1).",
    )
    args = parser.parse_args(argv)
    return run(check=args.check)


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    raise SystemExit(main())
