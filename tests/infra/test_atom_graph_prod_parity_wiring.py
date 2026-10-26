"""OPS-139 ⑥ — 패리티 프로브의 *집행 지점* 배선 동결.

프로브를 만드는 것과 **누가 언제 부르는가**는 다른 문제다(CLAUDE.md 「정본화를 집행으로 착각한 완료
선언 금지」). 판정 함수가 아무리 정확해도 어떤 런북·체크리스트도 그것을 부르지 않으면, 정본과 prod가
어긋나도 아무도 모른다 — S4-60 병합 뒤 prod가 2,210건에 머문 사고가 정확히 그 형태였다.

CI는 prod DB에 닿지 못하므로 여기서 동결하는 것은 *호출이 존재하는가*까지다:
  ① 적재 런북(`skb03_atom_node_populate_runbook.md`)의 AFTER 블록 [E]가 프로브를 부르고 종료 코드를 되읽는다
  ② 프로브 전용 런북이 읽기 전용이고(쓰기 명령 0건)·자리표시자가 없고·6항목 브리핑을 갖는다
  ③ 정본 `graph.json`을 바꾸는 PR 템플릿이 적재 후 MATCH를 증적으로 요구한다
  ④ 런북이 부르는 모듈이 실제로 존재한다(존재하지 않는 곳을 부르는 배선은 배선이 아니다)

각 검사는 **실패할 수 있는지**를 함께 확인한다 — 실제 텍스트에서 호출 줄을 지운 변형이 위반으로
잡혀야 한다(모든 입력에서 초록인 검사는 위장이다).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SKB03 = _REPO / "docs" / "ops" / "skb03_atom_node_populate_runbook.md"
_PROBE_RUNBOOK = _REPO / "docs" / "ops" / "atom_graph_parity_probe_runbook.md"
_PR_TEMPLATE = _REPO / ".github" / "pull_request_template.md"
_MODULE = "whymath_backend.ops.atom_graph_prod_parity"
_CALL = f"& $Py -m {_MODULE}"
_FENCE = re.compile(r"```powershell\n(.*?)```", re.DOTALL)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _blocks(text: str) -> list[str]:
    return _FENCE.findall(text)


def _runbook_wiring_violations(text: str) -> list[str]:
    """런북이 프로브를 *실제로* 부르는지 — 호출 줄·종료 코드 되읽기·`$Py` 정의 순서를 본다."""
    problems: list[str] = []
    blocks = _blocks(text)
    callers = [i for i, b in enumerate(blocks) if _CALL in b]
    if not callers:
        return [f"어떤 powershell 블록도 `{_CALL}`을 부르지 않는다"]
    for index in callers:
        block = blocks[index]
        if "PARITY_EXIT=$LASTEXITCODE" not in block:
            problems.append(f"블록 {index}: 호출은 있으나 종료 코드를 되읽지 않는다(PARITY_EXIT)")
        defined_before = any("$Py = " in earlier for earlier in blocks[:index])
        if "$Py = " not in block and not defined_before:
            problems.append(f"블록 {index}: `$Py`가 호출보다 앞 블록에 정의돼 있지 않다")
        # 호출이 *주석 처리된 줄*이면 부르는 것이 아니다
        lines = [ln for ln in block.splitlines() if _CALL in ln]
        if all(ln.lstrip().startswith("#") for ln in lines):
            problems.append(f"블록 {index}: 호출 줄이 전부 주석이다")
    return problems


def _pr_template_violations(text: str) -> list[str]:
    needed = ("graph.json", _MODULE.split(".")[-1], "STATUS=MATCH")
    return [f"PR 템플릿에 `{n}`이 없다" for n in needed if n not in text]


# ──────────────────────────────────────────────────────────────────────────
# ① 적재 런북 [E]가 프로브를 부른다
# ──────────────────────────────────────────────────────────────────────────
class TestAfterBlockCallsTheProbe:
    def test_skb03_runbook_after_block_calls_probe_and_reads_exit_code(self) -> None:
        assert _runbook_wiring_violations(_read(_SKB03)) == []

    def test_the_call_lives_in_the_after_block_not_an_earlier_one(self) -> None:
        """수작업 count를 *대체*하는 자리는 AFTER 판정 블록이다 — BEFORE 블록에 있으면 의미가 다르다."""
        text = _read(_SKB03)
        after = text[text.index("### [E]") :]
        # 마크다운 구분선은 줄 단위로 자른다 — 블록 안의 `-----` 출력 줄을 구분선으로 오인하지 않는다
        assert _CALL in after.split("\n---\n")[0]
        before = text[: text.index("### [E]")]
        assert _CALL not in before

    def test_runbook_tells_kiki_to_hand_back_the_parity_output(self) -> None:
        """전달값 목록에 프로브 출력이 없으면 세션이 판정을 받지 못한다 — 호출만 있고 회수가 없는 배선."""
        text = _read(_SKB03)
        section = text[text.index("## 7. 게이트 clear 방법") :]
        assert "PARITY_EXIT" in section

    def test_wiring_check_fails_when_the_call_line_is_removed(self) -> None:
        """대조군 — 호출 줄을 지운 변형이 위반으로 잡혀야 이 검사가 실패할 수 있다."""
        mutated = "\n".join(ln for ln in _read(_SKB03).splitlines() if _CALL not in ln)
        assert mutated != _read(_SKB03)
        assert _runbook_wiring_violations(mutated)

    def test_wiring_check_fails_when_exit_code_is_not_read_back(self) -> None:
        text = _read(_SKB03)
        mutated = text.replace('"PARITY_EXIT=$LASTEXITCODE"', '"done"')
        assert mutated != text
        assert any("PARITY_EXIT" in p for p in _runbook_wiring_violations(mutated))

    def test_wiring_check_fails_when_the_call_is_commented_out(self) -> None:
        text = _read(_SKB03)
        mutated = text.replace(_CALL, f"# {_CALL}")
        assert mutated != text
        assert any("주석" in p for p in _runbook_wiring_violations(mutated))


# ──────────────────────────────────────────────────────────────────────────
# ② 프로브 전용 런북 — 읽기 전용·자리표시자 0·6항목 브리핑
# ──────────────────────────────────────────────────────────────────────────
class TestProbeRunbook:
    def test_runbook_exists_and_calls_the_probe(self) -> None:
        assert _PROBE_RUNBOOK.is_file()
        assert _runbook_wiring_violations(_read(_PROBE_RUNBOOK)) == []

    def test_runbook_has_the_six_item_briefing(self) -> None:
        """CLAUDE.md — Kiki 직접 수행 과제는 6항목 브리핑을 명령 블록에 앞서 제공한다."""
        text = _read(_PROBE_RUNBOOK)
        for heading in (
            "## 1. 과제 명칭",
            "## 2. 목적",
            "## 3. 구체적 절차",
            "## 4. 성공 기준",
            "## 5. 실행 환경",
            "## 6. 창 구분",
        ):
            assert heading in text, heading
        assert text.index("## 6. 창 구분") < text.index("## 실행 블록")

    def test_runbook_is_read_only_no_write_command_in_any_block(self) -> None:
        """이 런북에는 쓰기 블록이 없다 — 적재는 skb03 [D]가 맡는다. 쓰기가 섞이면 자가거부 가드가 필요해진다."""
        forbidden = re.compile(
            r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b|l1\.atom_graph\.populate|--load\b",
            re.IGNORECASE,
        )
        for index, block in enumerate(_blocks(_read(_PROBE_RUNBOOK))):
            assert not forbidden.search(block), f"블록 {index}에 쓰기 명령이 있다"

    def test_runbook_has_no_placeholders_in_paste_blocks(self) -> None:
        """붙여넣기 블록에 자리표시자 금지(CLAUDE.md) — 전체 붙여넣기에서는 치환이 일어나지 않는다."""
        for index, block in enumerate(_blocks(_read(_PROBE_RUNBOOK))):
            assert "여기에_" not in block, f"블록 {index}"
            assert not re.search(r"<[^<>\s]+>", block), f"블록 {index}: <…> 자리표시자"

    def test_runbook_uses_container_exec_not_host_port(self) -> None:
        """호스트 TCP 5433에 의존하는 안내는 OPS-72 고장 때 침묵한다 — 컨테이너 안으로 들어간다."""
        for block in _blocks(_read(_PROBE_RUNBOOK)):
            assert "docker exec" in block or "git " in block or _CALL in block or "$env:" in block
            assert "5433" not in re.sub(r"\{\{.*?\}\}", "", block).replace("Ports", "")

    def test_runbook_states_the_ci_limit_and_that_unknown_is_not_match(self) -> None:
        text = _read(_PROBE_RUNBOOK)
        assert "CI는 prod DB에 닿지 못한다" in text
        assert "`UNKNOWN`을 `MATCH`로 읽지 않는다" in text

    def test_every_dotted_module_the_runbooks_call_exists_on_disk(self) -> None:
        """존재하지 않는 곳을 부르는 배선은 배선이 아니다 — 모듈 경로를 파일로 환원해 확인한다."""
        for path in (_SKB03, _PROBE_RUNBOOK):
            for block in _blocks(_read(path)):
                for dotted in re.findall(r"-m (whymath_backend[\w.]+)", block):
                    target = _REPO / "src" / "backend" / Path(*dotted.split("."))
                    assert (
                        target.with_suffix(".py").is_file() or (target / "__init__.py").is_file()
                    ), dotted


# ──────────────────────────────────────────────────────────────────────────
# ③ 정본을 바꾸는 PR의 체크리스트
# ──────────────────────────────────────────────────────────────────────────
class TestPrTemplateRequiresTheEvidence:
    def test_template_requires_match_evidence_for_graph_json_changes(self) -> None:
        assert _pr_template_violations(_read(_PR_TEMPLATE)) == []

    def test_template_check_fails_when_the_item_is_removed(self) -> None:
        text = _read(_PR_TEMPLATE)
        kept = [
            ln
            for ln in text.splitlines()
            if "atom_graph_prod_parity" not in ln and "STATUS=MATCH" not in ln
        ]
        mutated = "\n".join(kept)
        assert mutated != text
        assert _pr_template_violations(mutated)

    def test_template_item_is_a_checkbox_so_the_reviewer_sees_it_unchecked(self) -> None:
        text = _read(_PR_TEMPLATE)
        line = next(
            ln for ln in text.splitlines() if "atom_graph_prod_parity" in ln or "graph.json" in ln
        )
        assert line.lstrip().startswith("- [ ]")


# ──────────────────────────────────────────────────────────────────────────
# ④ 등록 — 인벤토리 귀속·미배선 감사 사유(새 모듈이 대장에 귀속됐는가)
# ──────────────────────────────────────────────────────────────────────────
class TestRegistration:
    def test_module_is_attributed_in_the_feature_inventory(self) -> None:
        text = _read(_REPO / "scripts" / "analysis" / "eos_feature_inventory_v2.py")
        assert (
            text.count('"ops.atom_graph_prod_parity"') == 1
        )  # 정확히 한 좌석(중복 귀속은 인벤토리가 거부)

    def test_module_has_a_named_declared_unwired_reason(self) -> None:
        text = _read(
            _REPO / "src" / "backend" / "whymath_backend" / "ops" / "declared_unwired_audit.py"
        )
        assert '"ops.atom_graph_prod_parity": _LIVE_DEPENDENT' in text
