"""오개념 품질 게이트 *집행 지점* 동결(MISC-18 ④) — 소스 스캔.

`apply_match_quality_gate`(floor 0.65)가 학생 대면 두 경로(코치 `api/coach.py`·WH-1 하네스
`harness/wh1_loop.py`) 모두에서 불린다는 것을, 그리고 **게이트 없이 원시 매처 출력을 소비하는
경로가 등록되지 않은 채 새로 생기지 않는다**는 것을 소스에서 직접 센다.

배경 — "한 곳에서만 부름"형 부분집행: 게이트 계약(`l4/misconception/match_gate.py`)은 정본화됐지만
호출자가 코치 1곳뿐이라 하네스 주경로는 floor 없이 돌았다. 계약이 있다는 사실은 *부른다*는 증거가
아니므로(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"), 호출 지점을 AST로 센다.

**왜 두 방향 등록부인가**: "호출자가 둘이다"를 숫자로만 고정하면 한 곳이 빠지고 다른 곳이 느는
치환에서 통과한다. 그래서 (a) 게이트 호출자 집합과 (b) 게이트 없는 원시 소비자 집합을 각각 *이름이
달린 닫힌 등록부*로 두고 양방향(신규=red·삭제=red)으로 대조한다. 새 경로를 추가하는 사람은 등록부에
역할과 사유를 적어야 한다 — 그 한 줄이 "이 경로는 학생에게 닿는가, 게이트는?"을 묻는 지점이다.

스캔 방식(문자열이 아니라 *구성된 결과*): 모듈이 `diagnose`/`combine_diagnoses`/
`combined_diagnose`/`apply_match_quality_gate`를 *import해 호출(ast.Call)*하는지를 센다. 주석·
docstring 언급이나 import만 하고 안 부르는 재수출(`l4/misconception/__init__.py`)은 소비자가 아니다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import whymath_backend

_PKG_ROOT = Path(whymath_backend.__file__).resolve().parent

# 원시 매처 심볼이 정의·재수출되는 모듈 — 이 모듈 경로에서 import한 이름만 추적한다.
_MATCHER_MODULES = frozenset(
    {
        "whymath_backend.l4.misconception.diagnose",
        "whymath_backend.l4.misconception.combined",
        "whymath_backend.l4.misconception",
    }
)
_GATE_MODULES = frozenset({"whymath_backend.l4.misconception.match_gate"})
_RAW_SYMBOLS = frozenset({"diagnose", "combine_diagnoses", "combined_diagnose"})
_GATE_SYMBOL = "apply_match_quality_gate"

# ──────────────────────────────────────────────────────────────────────
# 등록부 — 경로(패키지 루트 기준) → 역할·사유. 바꾸려면 그 경로가 학생에게 닿는지 판정해 적는다.
# ──────────────────────────────────────────────────────────────────────

# (a) 게이트 호출자. "serving" = 학생 대면 경로(반드시 둘 다 있어야 한다).
GATE_CALLERS: dict[str, str] = {
    "api/coach.py": "serving — 코치 응답(`_compute_matches`의 세 모드 공통 출구 `_gate`)",
    "harness/wh1_loop.py": "serving — WH-1 하네스 match_misconception 실행부(`_exec`·MISC-18)",
    "l4/misconception/distractor_link.py": "channel — 오답지 채널, 단일 원소 목록에 게이트",
    "l4/misconception/answer_signature.py": "channel — 답 서명 채널, 후보에 게이트",
    "harness/misconception_false_positive_eval.py": "measurement — 정답 해설 FP 측정",
    "harness/anchor_detection_channel_eval.py": "measurement — 앵커 탐지 채널 측정",
    "harness/explicit_correction_gap_eval.py": "measurement — 명시 정정 갭 측정",
}

# 학생 대면 경로가 게이트를 부르는 *함수* — 같은 모듈의 다른 곳에서 부르면서 이 지점은 빠지는
# 부분 이동(`_exec`에서 게이트를 빼고 헬퍼에만 남김)을 잡는다.
SERVING_GATE_FUNCTIONS: dict[str, str] = {
    "api/coach.py": "_gate",
    "harness/wh1_loop.py": "_exec",
}

# (b) 원시 매처 출력을 소비하되 게이트를 부르지 않는 모듈 — 학생에게 노출되지 않는 사유를 적는다.
UNGATED_RAW_CONSUMERS: dict[str, str] = {
    "harness/agreement_gate.py": "measurement — Phase2 진단 일치율 게이트(매처 자체를 잰다·비노출)",
    "l4/misconception/probes.py": "measurement — 진단 recall 프로브 집계(비노출)",
    "l4/misconception/semantic_eval.py": "measurement — substring↔의미 매처 비교 측정(비노출)",
    "l4/misconception/wrong_form_match.py": "shadow — SymPy↔substring 비교 *로깅*만(반환 None)",
    "l4/misconception/combined.py": "definition — `combined_diagnose` 정의(프로덕션 호출자 0 동결)",
    "l4/subject_adapter_math.py": "contract seat — `detect_misconception`(프로덕션 호출자 0 동결)",
}

# 프로덕션 호출자가 0이어야 하는 진입점. 게이트 없는 원시 출력을 돌려주므로, 연결되는 순간 게이트를
# 우회하는 새 경로가 된다 — 연결하려면 게이트 경유를 먼저 설계한 뒤 이 동결을 푼다.
_ZERO_CALLER_FUNCTIONS = ("combined_diagnose",)
_ZERO_CALLER_METHODS = ("detect_misconception",)


@dataclass
class _ModuleScan:
    gate_calls: list[tuple[ast.Call, str]] = field(default_factory=list)  # (호출 노드, 둘러싼 함수)
    raw_calls: list[tuple[str, str]] = field(default_factory=list)  # (심볼, 둘러싼 함수)
    method_calls: list[str] = field(default_factory=list)  # `.속성(` 호출의 속성명


class _Visitor(ast.NodeVisitor):
    def __init__(self, bound: dict[str, str]) -> None:
        self.bound = bound  # 로컬 이름 → 실제 심볼
        self.scan = _ModuleScan()
        self._stack: list[str] = []

    def _enter(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_FunctionDef = _enter  # noqa: N815 — ast.NodeVisitor 규약 이름
    visit_AsyncFunctionDef = _enter  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 — ast.NodeVisitor 규약 이름
        enclosing = self._stack[-1] if self._stack else "<module>"
        func = node.func
        if isinstance(func, ast.Name) and func.id in self.bound:
            symbol = self.bound[func.id]
            if symbol == _GATE_SYMBOL:
                self.scan.gate_calls.append((node, enclosing))
            else:
                self.scan.raw_calls.append((symbol, enclosing))
        elif isinstance(func, ast.Attribute):
            self.scan.method_calls.append(func.attr)
        self.generic_visit(node)


def _bound_names(tree: ast.AST) -> dict[str, str]:
    """추적 대상 심볼을 import한 로컬 이름(별칭 포함) → 실제 심볼."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        for alias in node.names:
            local = alias.asname or alias.name
            if node.module in _MATCHER_MODULES and alias.name in _RAW_SYMBOLS:
                bound[local] = alias.name
            elif node.module in _GATE_MODULES and alias.name == _GATE_SYMBOL:
                bound[local] = _GATE_SYMBOL
    return bound


@lru_cache(maxsize=1)
def _scan_package() -> dict[str, _ModuleScan]:
    scans: dict[str, _ModuleScan] = {}
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor(_bound_names(tree))
        visitor.visit(tree)
        scans[path.relative_to(_PKG_ROOT).as_posix()] = visitor.scan
    return scans


def _gate_callers() -> set[str]:
    return {rel for rel, scan in _scan_package().items() if scan.gate_calls}


def _ungated_raw_consumers() -> set[str]:
    return {rel for rel, scan in _scan_package().items() if scan.raw_calls and not scan.gate_calls}


class TestScanIsNotVacuous:
    """스캔 0건은 실패다 — 등록부가 비었거나 스캐너가 아무것도 못 보면 아래가 공허하게 통과한다."""

    def test_scanner_sees_the_package(self) -> None:
        scans = _scan_package()
        assert len(scans) > 100, "패키지 파일을 거의 못 읽었다 — 스캔 루트가 틀렸다"
        assert _gate_callers(), "게이트 호출자를 하나도 못 찾았다 — 스캐너가 호출을 못 본다"

    def test_every_registered_path_exists(self) -> None:
        """등록부의 죽은 경로(파일 이동·삭제)는 조용히 낡는다 — 존재를 단언한다."""
        registered = set(GATE_CALLERS) | set(UNGATED_RAW_CONSUMERS) | set(SERVING_GATE_FUNCTIONS)
        missing = sorted(rel for rel in registered if not (_PKG_ROOT / rel).is_file())
        assert missing == [], f"등록부에 있으나 파일이 없다: {missing}"


class TestGateCallersAreFrozen:
    def test_both_serving_paths_call_the_gate(self) -> None:
        """학생 대면 두 경로 모두 게이트를 부른다 — 한 곳에서만 부르던 상태의 회귀 차단."""
        callers = _gate_callers()
        for rel in SERVING_GATE_FUNCTIONS:
            assert rel in callers, f"{rel}이 apply_match_quality_gate를 부르지 않는다"

    def test_serving_gate_call_lives_in_the_named_function(self) -> None:
        """호출이 *지정 함수 안*에 있다 — 부분 이동(헬퍼에만 남기고 주경로에서 뺌) 차단."""
        for rel, function in SERVING_GATE_FUNCTIONS.items():
            enclosing = {fn for _, fn in _scan_package()[rel].gate_calls}
            assert (
                function in enclosing
            ), f"{rel}: 게이트 호출이 {function}() 안에 없다(현재 위치: {sorted(enclosing)})"

    def test_gate_caller_registry_is_closed(self) -> None:
        """게이트 호출자 집합 == 등록부. 신규 호출 경로도 삭제된 경로도 red다."""
        found = _gate_callers()
        registered = set(GATE_CALLERS)
        assert found - registered == set(), (
            f"등록 안 된 게이트 호출자: {sorted(found - registered)} — 역할(serving/channel/"
            "measurement)을 판정해 GATE_CALLERS에 적는다"
        )
        assert (
            registered - found == set()
        ), f"등록부에는 있으나 더는 게이트를 안 부르는 모듈: {sorted(registered - found)}"


class TestUngatedRawConsumersAreFrozen:
    def test_ungated_raw_consumer_registry_is_closed(self) -> None:
        """게이트 없이 원시 매처 출력을 소비하는 모듈 집합 == 등록부.

        새 모듈이 `diagnose()`를 부르면서 게이트를 안 부르면 red — 그 경로가 학생에게 닿는다면
        게이트를 거치게 하고, 닿지 않는다면 *왜 안 닿는지*를 UNGATED_RAW_CONSUMERS에 적는다.
        """
        found = _ungated_raw_consumers()
        registered = set(UNGATED_RAW_CONSUMERS)
        assert (
            found - registered == set()
        ), f"게이트 없는 새 원시 매처 소비자: {sorted(found - registered)}"
        assert registered - found == set(), (
            f"등록부에는 있으나 더는 게이트 없는 원시 소비자가 아닌 모듈: "
            f"{sorted(registered - found)}"
        )

    def test_serving_paths_are_not_registered_as_ungated(self) -> None:
        """학생 대면 경로는 면제 등록부에 들어갈 수 없다 — 면제로 게이트를 끄는 우회 차단."""
        assert set(UNGATED_RAW_CONSUMERS).isdisjoint(SERVING_GATE_FUNCTIONS)

    def test_zero_caller_entry_points_stay_unwired(self) -> None:
        """게이트 없는 진입점은 프로덕션 호출자 0 — 연결되는 순간 우회 경로가 된다."""
        scans = _scan_package()
        defining = {"l4/misconception/combined.py", "l4/misconception/__init__.py"}
        offenders = sorted(
            rel
            for rel, scan in scans.items()
            if rel not in defining
            for symbol, _ in scan.raw_calls
            if symbol in _ZERO_CALLER_FUNCTIONS
        )
        method_offenders = sorted(
            rel
            for rel, scan in scans.items()
            if any(name in _ZERO_CALLER_METHODS for name in scan.method_calls)
        )
        assert offenders == [], f"combined_diagnose 호출자가 생겼다: {offenders}"
        assert method_offenders == [], f".detect_misconception( 호출자가 생겼다: {method_offenders}"


class TestHarnessCallPassesNoOverrides:
    """하네스 호출은 floor·threshold·ocr 인자를 넘기지 않는다 — 단일 원천 + 게이트② dormant."""

    def _loop_gate_calls(self) -> list[ast.Call]:
        return [call for call, _ in _scan_package()["harness/wh1_loop.py"].gate_calls]

    def test_exactly_one_gate_call_with_only_the_matches_argument(self) -> None:
        calls = self._loop_gate_calls()
        assert len(calls) == 1, f"wh1_loop의 게이트 호출은 정확히 1곳이어야 한다: {len(calls)}"
        call = calls[0]
        assert len(call.args) == 1 and call.keywords == [], (
            "wh1_loop이 floor/threshold/ocr_confidence를 넘기면 floor를 복제하거나 없는 OCR 신뢰도를 "
            f"날조하는 것이다(키워드: {[k.arg for k in call.keywords]})"
        )

    def test_loop_module_holds_no_floor_literal(self) -> None:
        """floor 값(0.65)을 하네스가 리터럴로 들고 있지 않다(이중 진실원천 금지)."""
        tree = ast.parse((_PKG_ROOT / "harness/wh1_loop.py").read_text(encoding="utf-8"))
        floats = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, float)
        }
        assert 0.65 not in floats, "wh1_loop에 floor 리터럴 0.65가 있다 — match_gate.py가 정본이다"
