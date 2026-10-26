"""SKB-03 런북 §9(KG-14 잔존 엣지 은퇴)의 DB 도달 가드 동결.

2026-10-21 Kiki 실행에서 Docker Desktop이 꺼진 채 K2가 돌아, 은퇴 계획(plan)이 접속 타임아웃
traceback으로 끝났다. 쓰기는 없었지만(K3는 `AT_HEAD`가 빈 리비전으로 False라 거부됐을 것) 왕복이
한 번 늘었다. 같은 런북 앞부분에는 Docker 기동 블록 [A]가 이미 있는데 §9가 그것을 건너뛰었다 —
2026-09-14 G-skb01(Docker 미가동 · REACH_EXIT=2인데 적재 블록 진행)에 이은 같은 형태의 2회차다.

이 테스트는 ①§9 단계표에 K0(=[A] 블록)이 있고 ②K2가 DB 도달을 스스로 재검사해 변수에 담고
③plan 실행 조건이 그 변수를 포함하며 ④거부 가지가 그 변수를 출력하는지를 고정한다.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "docs" / "ops" / "skb03_atom_node_populate_runbook.md"


def _section9() -> str:
    """§9 본문만 잘라 낸다(다음 `## ` 제목 전까지)."""
    text = _RUNBOOK.read_text(encoding="utf-8")
    start = text.index("## 9. ")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def _k2_block() -> str:
    """§9의 K2 powershell 블록 본문."""
    sec = _section9()
    k2 = sec[sec.index("### K2") :]
    m = re.search(r"```powershell\n(.*?)```", k2, re.S)
    assert m, "K2 powershell 블록을 찾지 못했다"
    return m.group(1)


def _plan_line(block: str) -> str:
    """plan을 실행하는 줄(가드 if 포함)."""
    lines = [ln for ln in block.splitlines() if "--retire-stale-edges plan" in ln]
    assert len(lines) == 1, f"plan 실행 줄은 정확히 1줄이어야 한다: {len(lines)}"
    return lines[0]


def test_section9_table_starts_with_docker_step() -> None:
    sec = _section9()
    assert re.search(
        r"^\| K0 \|.*\[A\].*`DOCKER_OK=True`", sec, re.M
    ), "단계표에 K0([A] 블록) 행이 없다"
    assert "### K0" in sec, "K0 절이 없다"
    # K0는 K1보다 앞에 있어야 한다
    assert sec.index("### K0") < sec.index("### K1")


def test_k2_probes_db_reachability_before_plan() -> None:
    block = _k2_block()
    probe = re.search(r"^\$DbReach\s*=.*\$LASTEXITCODE", block, re.M)
    assert probe, "K2가 DB 도달을 `$DbReach`로 재검사하지 않는다"
    assert '"DB_REACHABLE=$DbReach"' in block, "K2가 DB 도달 판정값을 출력하지 않는다"
    # 도달 검사는 plan 실행보다 앞에 있어야 한다
    assert block.index("$DbReach =") < block.index(_plan_line(block))


def test_plan_is_gated_on_db_reachability_and_refusal_names_it() -> None:
    line = _plan_line(_k2_block())
    cond = re.match(r"\s*if \((.*?)\) \{", line)
    assert cond, "plan 실행 줄이 단일 최상위 if 가드로 시작하지 않는다"
    assert "$DbReach" in cond.group(1), "plan 실행 조건에 `$DbReach`가 없다"
    refusal = line[line.index("} else {") :]
    assert "PLAN_REFUSED=True" in refusal and "DB_REACHABLE=$DbReach" in refusal
