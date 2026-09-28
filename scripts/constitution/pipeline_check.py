#!/usr/bin/env python3
"""scripts/constitution/pipeline_check.py — 파이프라인 그래프 검사기 (코딩 헌법 제4조, R1-01~03).

원본: Kiki 헌법 v1.0 꾸러미(2026-09-26). 로컬 패치는 `# whymath 패치(CONST-02):` 주석과
UPSTREAM.md에 기록했다.

사용법
  python scripts/constitution/pipeline_check.py
      → 누락 참조·순환·섬 노드 검사
  python scripts/constitution/pipeline_check.py --downstream concept_graph
      → concept_graph를 바꾸면 다시 실행해야 할 하류 노드 출력 (R1-02)
  python scripts/constitution/pipeline_check.py --require copyright,backup \\
      --upstream-of publish:copyright
      → 필수 노드 존재 + 'publish의 상류에 copyright가 있는가' 검사 (R1-03)
  python scripts/constitution/pipeline_check.py --direct-upstream-of publish:copyright
      → copyright가 publish의 needs에 '직접' 있는가 (whymath 패치)

필요 패키지: pyyaml   (graphlib는 파이썬 3.9+ 표준 라이브러리)
"""

from __future__ import annotations

import argparse
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("⛔ pyyaml이 없습니다. 설치: python -m pip install pyyaml")

# 윈도우 콘솔(cp949)에서 한글 출력이 깨지지 않도록 UTF-8로 맞춘다
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[2]


def load(path: Path) -> dict:
    """pipeline.yaml의 nodes를 읽는다. 파일이 없거나 형식이 틀리면 즉시 실패(종료 코드 2)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        nodes = data["nodes"]
        if not isinstance(nodes, dict):
            raise TypeError("nodes는 '이름: 설정' 형태여야 함")
        if not nodes:
            # whymath 패치(CONST-02): 노드 0개는 '정상'이 아니라 측정 실패다(0건 통과 위장 금지).
            raise ValueError("nodes가 비어 있음")
        return {k: (v or {}) for k, v in nodes.items()}  # 값이 비어 있는 노드도 허용
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as e:
        print(f"⛔ [설정 오류] {path}: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)


def needs(spec: dict) -> list[str]:
    return list(spec.get("needs", []) or [])


def check(nodes: dict) -> list[str]:
    errors = []
    # 1) 존재하지 않는 선행 노드 참조 (오타·삭제된 노드)
    for name, spec in nodes.items():
        for dep in needs(spec):
            if dep not in nodes:
                errors.append(f"[누락] '{name}' 이(가) 없는 노드 '{dep}' 를 참조")
    # 2) 순환 (A→B→A 같은 고리) — 존재하는 노드끼리만 검사
    graph = {n: {d for d in needs(s) if d in nodes} for n, s in nodes.items()}
    try:
        list(TopologicalSorter(graph).static_order())
    except CycleError as e:
        errors.append(f"[순환] {' → '.join(e.args[1])}")
    # 3) 섬 노드: 원천(source)도 아니고, 입력도 없고, 아무도 쓰지 않는 노드
    used = {d for s in nodes.values() for d in needs(s)}
    for name, spec in nodes.items():
        if not spec.get("source") and not needs(spec) and name not in used:
            errors.append(f"[섬] '{name}' 은(는) 그래프와 연결되지 않음")
    return errors


def downstream(nodes: dict, changed: str) -> set[str]:
    """changed가 바뀌면 다시 실행해야 할 모든 하류 노드."""
    children: dict[str, list[str]] = {n: [] for n in nodes}
    for n, s in nodes.items():
        for d in needs(s):
            children.setdefault(d, []).append(n)
    result, stack = set(), [changed]
    while stack:  # 깊이 우선 탐색
        for c in children.get(stack.pop(), []):
            if c not in result:
                result.add(c)
                stack.append(c)
    return result


def upstream(nodes: dict, target: str) -> set[str]:
    """target을 실행하기 전에 반드시 끝나야 하는 모든 상류 노드."""
    result, stack = set(), [target]
    while stack:
        for d in needs(nodes.get(stack.pop(), {})):
            if d not in result:
                result.add(d)
                stack.append(d)
    return result


def split_pair(pair: str, errors: list[str], flag: str) -> tuple[str, str] | None:
    """'TARGET:NODE' 인자를 나눈다. 형식이 틀리면 오류 목록에 적고 None."""
    try:
        target, node = pair.split(":")
    except ValueError:
        errors.append(f"[인자 오류] {flag} 형식은 TARGET:NODE : '{pair}'")
        return None
    return target, node


def main() -> int:
    ap = argparse.ArgumentParser(description="파이프라인 그래프 검사기")
    ap.add_argument("--file", default=str(ROOT / "pipeline.yaml"))
    ap.add_argument("--downstream", metavar="NODE", help="하류 노드 출력")
    ap.add_argument("--require", metavar="A,B", help="반드시 존재해야 하는 노드 목록")
    ap.add_argument(
        "--upstream-of",
        metavar="TARGET:NODE",
        action="append",
        default=[],
        help="NODE가 TARGET의 상류(추이적)에 있어야 함 (여러 번 지정 가능)",
    )
    # whymath 패치(CONST-02): 원본 --upstream-of는 추이적이라, 게이트를 거치지 않는 우회 간선이
    # 있어도 다른 경로로 닿기만 하면 통과한다(주입 실측: publish→copyright 직접 간선을 지워도
    # qa_pipeline 경유로 통과). '게이트가 직접 선행인가'를 따로 묻는 옵션을 둔다.
    ap.add_argument(
        "--direct-upstream-of",
        metavar="TARGET:NODE",
        action="append",
        default=[],
        help="NODE가 TARGET의 needs에 직접 있어야 함 (whymath 패치)",
    )
    args = ap.parse_args()

    nodes = load(Path(args.file))
    errors = check(nodes)

    for name in filter(None, (args.require or "").split(",")):
        if name.strip() not in nodes:
            errors.append(
                f"[필수 노드 없음] '{name.strip()}' — "
                "헌법 제4조 ②: 그래프 밖의 작업은 존재할 수 없음"
            )

    for pair in args.upstream_of:
        parsed = split_pair(pair, errors, "--upstream-of")
        if parsed and parsed[1] not in upstream(nodes, parsed[0]):
            errors.append(
                f"[상류 누락] '{parsed[1]}' 이(가) '{parsed[0]}' 의 상류에 없음 — "
                "건너뛸 수 있는 게이트"
            )

    for pair in args.direct_upstream_of:
        parsed = split_pair(pair, errors, "--direct-upstream-of")
        if parsed and parsed[1] not in needs(nodes.get(parsed[0], {})):
            errors.append(
                f"[직접 선행 누락] '{parsed[1]}' 이(가) '{parsed[0]}' 의 needs에 직접 없음 — "
                "다른 경로로만 닿으면 그 경로가 바뀔 때 게이트가 조용히 빠진다"
            )

    for e in errors:
        print(e)

    if args.downstream:
        if args.downstream not in nodes:
            print(f"[누락] 노드 '{args.downstream}' 없음")
            return 1
        ds = sorted(downstream(nodes, args.downstream))
        print(f"'{args.downstream}' 변경 시 재실행 대상 {len(ds)}개: {', '.join(ds) or '(없음)'}")

    if not errors:
        print(f"✅ 파이프라인 그래프 정상 (노드 {len(nodes)}개)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
