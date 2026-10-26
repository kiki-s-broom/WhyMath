"""튜터 구조화 출력 스키마 게이트의 **집행 지점** 동결 (P3-09).

무엇을 지키는가
--------------
설계 규율: **튜터 응답은 스키마 검증을 통과해야만 학생에게 나가고, `mastery_update_allowed`는 언제나
false다.** 정본(스키마·검증기)은 `harness/wh1_tutor_output.py`에 있고, 행동은
`tests/backend/harness/test_wh1_tutor_output.py`·`tests/backend/api/test_coach_tutor_output_schema.py`가
주입으로 본다. 이 파일은 그 검증기를 **서빙 코드가 실제로 경유하는 자리**를 정적으로 동결한다 —
검증기를 지우거나, 결과를 버리거나, 승격 뒤로 밀거나, 응답에서 빼면 여기가 먼저 빨개진다.

동결하는 6절
-----------
  A. **정책 1단계** — `LLMTutorPolicy._parse_action`이 `classify_action_payload` 결과를 분기 조건으로
     써서 `_reject`로 보낸다(호출만 하고 버리기 금지).
  B. **러너 2단계** — `run_wh1_primary_turn`이 톤필터 산출물로 `build_tutor_output`을 부르고, 그
     결과가 거부(str)면 `return None`으로 빠지는 분기가 **모든 비-None 반환보다 앞**에 있다.
  C. **승격 3단계** — `_wh1_primary_decision_or`가 `check_deliverable` 결과로 결정론 `decision`을
     돌려주는 분기를 두고, 그 분기가 발화 승격(`model_copy`)보다 앞에 있다.
  D. **두 핸들러 배선** — `create_session`·`append_turns`가 모두 `output_receipt=`를 넘기고 응답에
     `tutor_output=<영수증>.output`을 싣는다(한쪽만 배선된 상태를 막는다).
  E. **mastery 강제 false** — `TutorTurnOutput.mastery_update_allowed`의 주석 타입이 `Literal[False]`다.
  F. **true 대입 0건** — 백엔드 프로덕션 코드 어디에도 `mastery_update_allowed`에 `False` 상수가 아닌
     값을 넣는 키워드 인자·속성 대입·dict 리터럴이 없다(빌더는 아예 넘기지 않는다).

**의존성 제약**: `infra-contracts` 잡은 백엔드 패키지를 설치하지 않는다 — `ast` + 표준 라이브러리만
쓴다(ARCH-59·ARCH-60 선례). **스캔 0건은 실패다** — 각 절은 대상 실재를 먼저 단언한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "src" / "backend" / "whymath_backend"

_POLICY_FILE = _BACKEND / "harness" / "wh1_llm_policy.py"
_PRIMARY_FILE = _BACKEND / "harness" / "wh1_primary.py"
_OUTPUT_FILE = _BACKEND / "harness" / "wh1_tutor_output.py"
_COACH_FILE = _BACKEND / "api" / "coach.py"

_CONTRACT_FIELD = "mastery_update_allowed"
_HANDLERS = ("create_session", "append_turns")


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _find_func(tree: ast.Module, name: str, *, where: Path) -> ast.AST:
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    assert found, f"{name!r}를 {where.name}에서 못 찾았다 — 스캔이 깨졌다(좌석을 함께 옮겨라)"
    return found[0]


def _own_nodes(func: ast.AST) -> list[ast.AST]:
    """함수 자신의 노드 — 중첩 정의 본문은 제외(내부 헬퍼의 return이 섞이지 않게)."""
    collected: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(func))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        collected.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return collected


def _callee(node: ast.AST) -> str | None:
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _bindings(func: ast.AST, callee: str) -> list[ast.Assign]:
    return [
        node
        for node in _own_nodes(func)
        if isinstance(node, ast.Assign) and _callee(node.value) == callee
    ]


def _bound_names(func: ast.AST, callee: str) -> set[str]:
    names: set[str] = set()
    for node in _bindings(func, callee):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Tuple):
                names.update(e.id for e in target.elts if isinstance(e, ast.Name))
    return names


def _refers_to(expr: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(expr))


def _is_none(value: ast.expr | None) -> bool:
    return value is None or (isinstance(value, ast.Constant) and value.value is None)


def _returns_in(body: list[ast.stmt]) -> list[ast.Return]:
    out: list[ast.Return] = []
    for stmt in body:
        for node in [stmt, *_own_nodes(stmt)]:
            if isinstance(node, ast.Return):
                out.append(node)
    return out


# ──────────────────────────────────────────────────────────────────────
# A. 정책 1단계
# ──────────────────────────────────────────────────────────────────────
class TestPolicyParseRoutesViolationsToReject:
    def test_classifier_result_drives_reject(self) -> None:
        func = _find_func(_parse(_POLICY_FILE), "_parse_action", where=_POLICY_FILE)
        verdicts = _bound_names(func, "classify_action_payload")
        assert verdicts, "`_parse_action`에서 `classify_action_payload` 결과 대입을 못 찾았다"
        enforced = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _refers_to(node.test, verdicts)
            and any(_callee(r.value) == "_reject" for r in _returns_in(node.body) if r.value)
        ]
        assert (
            enforced
        ), "스키마 판정 결과가 `_reject` 분기를 구동하지 않는다 — 판정을 버리면 위반 JSON이 액션이 된다"

    def test_reject_logs_and_degrades(self) -> None:
        func = _find_func(_parse(_POLICY_FILE), "_reject", where=_POLICY_FILE)
        callees = {_callee(n) for n in _own_nodes(func)}
        assert "warning" in callees, "거부가 WARNING을 남기지 않는다(침묵 실패 금지)"
        body = list(getattr(func, "body", []))
        assert any(
            _callee(r.value) == "_safe_fallback" for r in _returns_in(body) if r.value
        ), "거부가 안전 강등으로 가지 않는다"


# ──────────────────────────────────────────────────────────────────────
# B. 러너 2단계
# ──────────────────────────────────────────────────────────────────────
class TestRunnerGatesOnBuiltOutput:
    @staticmethod
    def _func() -> ast.AST:
        return _find_func(_parse(_PRIMARY_FILE), "run_wh1_primary_turn", where=_PRIMARY_FILE)

    def test_builder_consumes_tone_filtered_text(self) -> None:
        func = self._func()
        filtered = set()
        for node in _bindings(func, "filter_tone"):
            target = node.targets[0]
            if isinstance(target, ast.Tuple) and isinstance(target.elts[0], ast.Name):
                filtered.add(target.elts[0].id)
        assert filtered, "톤필터 산출 이름을 못 찾았다 — 스캔이 깨졌다"
        builds = _bindings(func, "build_tutor_output")
        assert builds, "러너에서 `build_tutor_output` 호출을 못 찾았다 — 2단계 게이트가 사라졌다"
        call = builds[0].value
        assert isinstance(call, ast.Call)
        explanation = next((kw.value for kw in call.keywords if kw.arg == "explanation"), None)
        assert explanation is not None and _refers_to(
            explanation, filtered
        ), "구조화 출력의 발화가 톤필터 산출물이 아니다 — 검증한 문자열과 나가는 문자열이 갈라진다"

    def test_rejection_branch_precedes_every_delivery(self) -> None:
        func = self._func()
        built = _bound_names(func, "build_tutor_output")
        guards = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _refers_to(node.test, built)
            and any(_is_none(r.value) for r in _returns_in(node.body))
        ]
        assert guards, "구조화 출력 거부가 `return None`(결정론 폴백)으로 빠지지 않는다"
        guard_line = min(g.lineno for g in guards)
        build_line = min(b.lineno for b in _bindings(func, "build_tutor_output"))
        deliveries = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.Return) and not _is_none(node.value)
        ]
        assert deliveries, "러너의 발화 반환을 못 찾았다 — 스캔이 깨졌다"
        for node in deliveries:
            assert (
                build_line < guard_line < node.lineno
            ), f"{_PRIMARY_FILE.name}:{node.lineno} — 발화가 스키마 게이트보다 먼저 반환된다"


# ──────────────────────────────────────────────────────────────────────
# C. 승격 3단계
# ──────────────────────────────────────────────────────────────────────
class TestPromotionRevalidatesBeforeCopy:
    def test_deliverable_check_returns_decision_before_promotion(self) -> None:
        func = _find_func(_parse(_COACH_FILE), "_wh1_primary_decision_or", where=_COACH_FILE)
        verdicts = _bound_names(func, "check_deliverable")
        assert verdicts, "승격 좌석에서 `check_deliverable` 결과 대입을 못 찾았다"
        guards = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.If)
            and _refers_to(node.test, verdicts)
            and any(
                isinstance(r.value, ast.Name) and r.value.id == "decision"
                for r in _returns_in(node.body)
            )
        ]
        assert guards, "재검증 거부가 결정론 `decision` 반환으로 이어지지 않는다"
        copies = [
            node
            for node in _own_nodes(func)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "model_copy"
        ]
        assert copies, "발화 승격(`model_copy`)을 못 찾았다 — 스캔이 깨졌다"
        assert max(g.lineno for g in guards) < min(
            c.lineno for c in copies
        ), "재검증이 승격보다 뒤에 있다 — 검증 전 문자열이 이미 학생 응답에 실린다"


# ──────────────────────────────────────────────────────────────────────
# D. 두 핸들러 배선
# ──────────────────────────────────────────────────────────────────────
class TestBothHandlersWireTheReceipt:
    def test_each_handler_passes_receipt_and_serves_its_output(self) -> None:
        tree = _parse(_COACH_FILE)
        for handler in _HANDLERS:
            func = _find_func(tree, handler, where=_COACH_FILE)
            promotions = [
                node
                for node in _own_nodes(func)
                if isinstance(node, ast.Call) and _callee(node) == "_wh1_primary_decision_or"
            ]
            assert promotions, f"{handler}에서 발화 승격 호출을 못 찾았다 — 스캔이 깨졌다"
            receipts: set[str] = set()
            for call in promotions:
                kw = next((k.value for k in call.keywords if k.arg == "output_receipt"), None)
                assert isinstance(kw, ast.Name), f"{handler}가 `output_receipt=`를 넘기지 않는다"
                receipts.add(kw.id)
            served = [
                k.value
                for node in _own_nodes(func)
                if isinstance(node, ast.Call)
                for k in node.keywords
                if k.arg == "tutor_output"
            ]
            assert served, f"{handler} 응답에 `tutor_output`이 없다"
            for value in served:
                assert (
                    isinstance(value, ast.Attribute)
                    and value.attr == "output"
                    and isinstance(value.value, ast.Name)
                    and value.value.id in receipts
                ), f"{handler} 응답의 `tutor_output`이 검증 영수증의 `.output`이 아니다"


# ──────────────────────────────────────────────────────────────────────
# E·F. mastery_update_allowed 강제 false
# ──────────────────────────────────────────────────────────────────────
class TestMasteryUpdateAllowedIsAlwaysFalse:
    def test_field_annotation_is_literal_false(self) -> None:
        tree = _parse(_OUTPUT_FILE)
        cls = next(
            (
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "TutorTurnOutput"
            ),
            None,
        )
        assert cls is not None, "`TutorTurnOutput`을 못 찾았다 — 스캔이 깨졌다"
        fields = [
            s
            for s in cls.body
            if isinstance(s, ast.AnnAssign)
            and isinstance(s.target, ast.Name)
            and s.target.id == _CONTRACT_FIELD
        ]
        assert len(fields) == 1, f"`{_CONTRACT_FIELD}` 필드가 정확히 하나가 아니다"
        ann = fields[0].annotation
        assert (
            isinstance(ann, ast.Subscript)
            and isinstance(ann.value, ast.Name)
            and ann.value.id == "Literal"
            and isinstance(ann.slice, ast.Constant)
            and ann.slice.value is False
        ), f"`{_CONTRACT_FIELD}`의 타입이 `Literal[False]`가 아니다 — true를 담을 자리가 생겼다"

    def test_no_production_code_sets_it_to_anything_but_false(self) -> None:
        modules = sorted(_BACKEND.rglob("*.py"))
        assert modules, "백엔드 모듈을 못 찾았다 — 스캔이 깨졌다"
        hits: list[str] = []
        for path in modules:
            tree = _parse(path)
            rel = path.relative_to(_BACKEND).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == _CONTRACT_FIELD:
                    if not (isinstance(node.value, ast.Constant) and node.value.value is False):
                        hits.append(f"{rel}:{node.value.lineno} 키워드 인자")
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Attribute) and target.attr == _CONTRACT_FIELD:
                            hits.append(f"{rel}:{node.lineno} 속성 대입")
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values, strict=True):
                        if isinstance(key, ast.Constant) and key.value == _CONTRACT_FIELD:
                            if not (isinstance(value, ast.Constant) and value.value is False):
                                hits.append(f"{rel}:{key.lineno} dict 리터럴")
        assert not hits, (
            f"`{_CONTRACT_FIELD}`에 False가 아닌 값을 넣는 코드: {hits} — LLM은 학습 상태를 결정하지 "
            "않는다(Phase 2 동결 계약). 빌더는 이 필드를 넘기지 않는다(기본값 false만)"
        )


# ──────────────────────────────────────────────────────────────────────
# G·H. PR #1713 검토 반영 — 개념 id는 도구 단위 실패, 진단은 코치 큐레이션 세트
# ──────────────────────────────────────────────────────────────────────
class TestReviewFixesStayWired:
    @staticmethod
    def _func() -> ast.AST:
        return _find_func(_parse(_PRIMARY_FILE), "run_wh1_primary_turn", where=_PRIMARY_FILE)

    def test_runner_hands_the_allowed_concept_set_to_the_harness(self) -> None:
        calls = [
            node
            for node in _own_nodes(self._func())
            if isinstance(node, ast.Call) and _callee(node) == "run_tutoring_turn"
        ]
        assert calls, "러너에서 `run_tutoring_turn` 호출을 못 찾았다 — 스캔이 깨졌다"
        for call in calls:
            kw = next((k.value for k in call.keywords if k.arg == "known_concept_ids"), None)
            assert (
                isinstance(kw, ast.Attribute) and kw.attr == "known_concept_ids"
            ), "러너가 허용 개념 집합을 하네스에 넘기지 않는다 — 환각 id가 그대로 성공 처리된다"

    def test_diagnosis_comes_from_the_coach_curated_hypotheses(self) -> None:
        builds = _bindings(self._func(), "build_tutor_output")
        assert builds, "`build_tutor_output` 호출을 못 찾았다 — 스캔이 깨졌다"
        call = builds[0].value
        assert isinstance(call, ast.Call)
        hyp = next((k.value for k in call.keywords if k.arg == "hypotheses"), None)
        assert (
            isinstance(hyp, ast.Name) and hyp.id == "initial_hypotheses"
        ), "진단이 코치 큐레이션 초기 가설이 아니다 — 턴 안 LLM 증거가 진단을 바꿀 수 있다"
