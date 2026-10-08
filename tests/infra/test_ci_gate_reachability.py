"""[OPS-38 · 원 OPS-19 회수] CI 게이트의 **도달 가능성** 계약 — 스텝의 트리거로 부모 잡이 실제로 도는가.

왜 이 테스트가 있는가
--------------------
`qa_pipeline` 스텝(`if: needs.changes.outputs.corpus == 'true'`)은 부모 잡 `data-pipeline`이
`data_pipeline` 플래그만 보던 시절, 코퍼스만 바뀐 PR에서 **잡이 통째로 skip돼 시작조차 못 했다**
(`data_platform_module_gap_review_r2` A1 · 원 태스크 OPS-19 · main 해소 = COLLAB-07).

main에는 이미 같은 계열의 가드가 있다 — `test_ci_contract_fixture_trigger_wiring.py::
test_no_dead_changes_flag`. 그러나 그 가드는 스텝의 플래그가 부모 잡 `if`에 **문자열로 등장하는지**만
본다. 그래서 잡 `if`가 `... data_pipeline == 'true' && corpus == 'true'`처럼 플래그를 **AND로
요구**하게 바뀌면(= 코퍼스 단독 PR에서 잡이 다시 skip되는, 원래 결함 그대로의 상태) 플래그가
문자열로는 등장하므로 **그 가드는 통과한다**(2026-10-08 OR→AND 뮤테이션 실측: 기준선 20 passed,
뮤테이션 후 `test_no_dead_changes_flag` 1 passed). "존재함 ≠ 돌아감"의 한 단계 아래 사각이다.

이 파일은 그 사각만 메운다 — 스텝이 참조하는 플래그가 **참인 변경셋**에서 부모 잡 `if`를 실제로
**평가**해 참이 되는지 판정한다. 문자열 포함이 아니라 의미를 본다.

검증 계약
--------
① 게이트성 스텝(스텝 자신의 `if`가 `needs.changes.outputs.*`를 참조) 전수를 구조 스캔으로 찾는다
   — 레지스트리(하드코딩 표) 없음. 스캔 0건은 공허한 통과이므로 실패한다.
② 각 스텝에 대해 `github.event_name == 'pull_request'` 고정, 그 스텝이 참조하는 플래그**만** 참인
   변경셋에서 부모 잡 `if`가 참인지 평가한다. 거짓이면 스텝은 영영 실행되지 못한다.
③ 평가기는 인식하지 못한 표현식 토큰을 만나면 조용히 통과시키지 않고 실패한다(위장 금지) —
   `eval`을 쓰지 않고 이 저장소가 쓰는 어휘(`&&`·`||`·`!`·괄호·플래그 비교·event_name 비교)만
   재귀하강으로 해석한다.
④ 평가기 자체의 판별력을 합성 픽스처(실제 있었던 버그·수정 문자열 + AND 뮤테이션)로 고정한다.

한계(정직 기술): 스텝 `if`가 플래그를 OR로 여럿 참조해도 "그 플래그 전부 참" 하나의 변경셋으로만
판정한다 — 거짓 양성이 없는 하한 검사이며, OR 가지 하나가 잡에서 빠진 경우는 잡지 못한다.
`github.event_name` 외의 컨텍스트(`github.ref`·`needs.<다른잡>.result` 등)가 부모 잡 `if`에 들어오면
평가기가 모르는 어휘이므로 **실패**한다(그때 평가기를 확장하라는 신호다).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_CI_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

# 스텝/잡 `if`에서 `needs.changes.outputs.<flag>` 참조를 뽑는다.
_FLAG_REF_RE = re.compile(r"needs\.changes\.outputs\.(\w+)")

# 이 저장소의 잡/스텝 `if`가 실제로 쓰는 어휘 전부 — 여기에 안 맞는 잔여 문자열은 평가하지 않는다.
_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<lparen>\()
      | (?P<rparen>\))
      | (?P<and>&&)
      | (?P<or>\|\|)
      | (?P<not>!(?!=))
      | needs\.changes\.outputs\.(?P<flag>\w+)\s*==\s*'true'
      | github\.event_name\s*(?P<op>==|!=)\s*'(?P<event>\w+)'
    )""",
    re.VERBOSE,
)

# 판정 대상 이벤트 — PR 전용 도달 가능성(push·schedule은 changes 플래그와 무관하게 별도 경로).
_EVENT = "pull_request"


def _tokenize(expr: str) -> list[tuple[str, str]]:
    """`if` 표현식을 토큰열로 쪼갠다. 인식 못한 잔여가 있으면 즉시 실패한다."""
    body = expr.strip()
    if body.startswith("${{") and body.endswith("}}"):
        body = body[3:-2]
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(body):
        if not body[pos:].strip():
            break
        match = _TOKEN_RE.match(body, pos)
        if match is None or match.end() == pos:
            raise AssertionError(
                f"`if` 표현식 {expr!r}의 {body[pos:]!r} 부분을 해석하지 못했다 — 이 평가기가 모르는 "
                "새 어휘가 ci.yml에 들어왔다. 평가기를 확장하라(조용히 통과시키지 않는다)."
            )
        kind = str(match.lastgroup)
        if kind == "flag":
            tokens.append(("flag", match.group("flag")))
        elif kind == "event":
            tokens.append(("event", f"{match.group('op')}{match.group('event')}"))
        else:
            tokens.append((kind, match.group(kind)))
        pos = match.end()
    if not tokens:
        raise AssertionError(f"`if` 표현식 {expr!r}에서 토큰을 하나도 얻지 못했다.")
    return tokens


class _Evaluator:
    """`||` < `&&` < `!` 우선순위의 재귀하강 평가기 (괄호 지원)."""

    def __init__(self, expr: str, flags_true: frozenset[str]) -> None:
        self._expr = expr
        self._tokens = _tokenize(expr)
        self._flags_true = flags_true
        self._i = 0

    def evaluate(self) -> bool:
        value = self._or()
        if self._i != len(self._tokens):
            raise AssertionError(
                f"`if` 표현식 {self._expr!r}을 끝까지 해석하지 못했다(잔여 토큰 "
                f"{self._tokens[self._i:]!r}) — 괄호·연산자 짝을 확인하라."
            )
        return value

    def _peek(self) -> str | None:
        return self._tokens[self._i][0] if self._i < len(self._tokens) else None

    def _or(self) -> bool:
        value = self._and()
        while self._peek() == "or":
            self._i += 1
            rhs = self._and()  # 단락 평가 금지 — 항상 끝까지 소비해 문법 오류를 놓치지 않는다.
            value = value or rhs
        return value

    def _and(self) -> bool:
        value = self._not()
        while self._peek() == "and":
            self._i += 1
            rhs = self._not()
            value = value and rhs
        return value

    def _not(self) -> bool:
        if self._peek() == "not":
            self._i += 1
            return not self._not()
        return self._atom()

    def _atom(self) -> bool:
        kind = self._peek()
        if kind is None:
            raise AssertionError(f"`if` 표현식 {self._expr!r}이 피연산자 없이 끝났다.")
        _, text = self._tokens[self._i]
        self._i += 1
        if kind == "lparen":
            value = self._or()
            if self._peek() != "rparen":
                raise AssertionError(f"`if` 표현식 {self._expr!r}의 괄호가 닫히지 않았다.")
            self._i += 1
            return value
        if kind == "flag":
            return text in self._flags_true
        if kind == "event":
            op, event = (text[:2], text[2:])
            return (event == _EVENT) if op == "==" else (event != _EVENT)
        raise AssertionError(f"`if` 표현식 {self._expr!r}: 예상 못한 토큰 {kind!r}({text!r}).")


def job_reachable_under_flags(job_if: str, flags_true: frozenset[str]) -> bool:
    """PR 이벤트에서, `flags_true`만 참인 변경셋에 대해 `job_if`가 참인지 평가한다."""
    return _Evaluator(job_if, flags_true).evaluate()


def _flags_referenced(condition: str) -> frozenset[str]:
    return frozenset(_FLAG_REF_RE.findall(condition))


def _gate_steps(jobs: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any], Mapping[str, Any]]]:
    """스텝 자신의 `if`가 `needs.changes.outputs.*`를 참조하는 (잡 키, 잡, 스텝) 전수."""
    found: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and _flags_referenced(str(step.get("if") or "")):
                found.append((job_key, job, step))
    return found


def reachability_violations(jobs: Mapping[str, Any]) -> list[str]:
    """게이트성 스텝마다, 그 스텝의 플래그가 참일 때 부모 잡이 도는지 판정해 위반을 모은다."""
    violations: list[str] = []
    for job_key, job, step in _gate_steps(jobs):
        job_if = str(job.get("if") or "")
        if not job_if:
            continue  # 부모 잡에 `if`가 없으면 항상 실행 — 도달 불가 문제가 성립하지 않는다.
        step_if = str(step.get("if") or "")
        step_flags = _flags_referenced(step_if)
        if not job_reachable_under_flags(job_if, step_flags):
            name = step.get("name") or "(무명 스텝)"
            violations.append(
                f"[{job_key}] 스텝 '{name}' — 스텝 if={step_if!r}의 플래그 {sorted(step_flags)}만 "
                f"참인 PR에서 부모 잡 if={job_if!r}가 거짓이라 잡이 통째 skip된다 → 스텝 영구 미실행."
            )
    return violations


def _load_jobs() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 게이트 배선을 확인할 수 없다.")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    jobs = (spec or {}).get("jobs") if isinstance(spec, dict) else None
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError("ci.yml에서 jobs를 읽지 못했다 — 워크플로 형태가 바뀌었는가.")
    return dict(jobs)


# ── 실제 ci.yml 판정 ──────────────────────────────────────────────────────────


def test_gate_steps_scan_is_not_vacuous() -> None:
    """스캔 0건은 공허한 통과다 — 게이트성 스텝이 1건 이상 잡혀야 아래 판정이 의미를 갖는다."""
    gates = _gate_steps(_load_jobs())
    assert gates, (
        "`needs.changes.outputs.*`로 게이트되는 스텝이 ci.yml에 하나도 없다 — 스캐너가 형태를 "
        "놓쳤거나 게이트가 사라졌다. 사라진 것이 의도라면 이 파일의 계약을 의식적으로 폐기하라."
    )


def test_gate_steps_reachable_under_own_trigger() -> None:
    """게이트성 스텝마다, 그 스텝의 트리거 플래그만으로 부모 잡도 실행돼야 한다."""
    violations = reachability_violations(_load_jobs())
    assert not violations, "CI 게이트 도달 불가 — 스텝은 있으나 부모 잡이 skip된다:\n" + "\n".join(
        f"  · {v}" for v in violations
    )


# ── 평가기 판별력 고정(합성 픽스처 — 실제 ci.yml을 건드리지 않는다) ───────────────────────────

# 이 세 문자열은 2026-08-04~08 실측에서 실제로 있었던 상태다: (BUGGY) A1 결함 · (FIXED) COLLAB-07
# 해소 후 main · (AND) main의 문자열 포함 가드는 통과하지만 A1과 같은 증상인 뮤테이션.
_BUGGY_JOB_IF = (
    "(github.event_name != 'pull_request' || needs.changes.outputs.data_pipeline == 'true') "
    "&& github.event_name != 'schedule'"
)
_FIXED_JOB_IF = (
    "(github.event_name != 'pull_request' || needs.changes.outputs.data_pipeline == 'true' "
    "|| needs.changes.outputs.corpus == 'true') && github.event_name != 'schedule'"
)
_AND_MUTATION_JOB_IF = (
    "(github.event_name != 'pull_request' || needs.changes.outputs.data_pipeline == 'true' "
    "&& needs.changes.outputs.corpus == 'true') && github.event_name != 'schedule'"
)
_CORPUS = frozenset({"corpus"})


def test_evaluator_flags_known_bug() -> None:
    assert not job_reachable_under_flags(
        _BUGGY_JOB_IF, _CORPUS
    ), "버그 상태(수정 전 job if)에서 도달 가능하다고 판정했다 — 변별력이 없다."


def test_evaluator_clears_fixed_state() -> None:
    assert job_reachable_under_flags(
        _FIXED_JOB_IF, _CORPUS
    ), "수정된 job if에서 도달 불가라고 판정했다 — 변별력이 없다."


def test_evaluator_catches_and_mutation_that_string_containment_misses() -> None:
    """플래그가 문자열로 등장해도 AND로 묶이면 단독 트리거로는 잡이 안 돈다 — 포함 검사의 사각."""
    assert "needs.changes.outputs.corpus" in _AND_MUTATION_JOB_IF  # 포함 검사는 통과하는 형태
    assert not job_reachable_under_flags(_AND_MUTATION_JOB_IF, _CORPUS)
    # 대조군: 두 플래그가 모두 참이면 AND여도 도달한다 — 평가기가 무조건 False를 내는 것이 아니다.
    assert job_reachable_under_flags(_AND_MUTATION_JOB_IF, frozenset({"corpus", "data_pipeline"}))


def test_evaluator_event_name_and_negation() -> None:
    assert not job_reachable_under_flags("github.event_name == 'schedule'", _CORPUS)
    assert job_reachable_under_flags("github.event_name != 'schedule'", _CORPUS)
    assert job_reachable_under_flags("!(github.event_name == 'schedule')", frozenset())
    assert job_reachable_under_flags("${{ needs.changes.outputs.corpus == 'true' }}", _CORPUS)


def test_evaluator_precedence_and_over_or() -> None:
    """`a || b && c`는 `a || (b && c)` — 우선순위를 잘못 구현하면 AND 뮤테이션 판정이 뒤집힌다."""
    expr = (
        "needs.changes.outputs.a == 'true' || needs.changes.outputs.b == 'true' "
        "&& needs.changes.outputs.c == 'true'"
    )
    assert job_reachable_under_flags(expr, frozenset({"a"}))
    assert not job_reachable_under_flags(expr, frozenset({"b"}))
    assert job_reachable_under_flags(expr, frozenset({"b", "c"}))


@pytest.mark.parametrize(
    "unknown_expr",
    [
        "contains(github.event.pull_request.labels.*.name, 'run-corpus')",
        "needs.changes.outputs.corpus == 'true' && github.ref == 'refs/heads/main'",
        "needs.build.result == 'success'",
        "needs.changes.outputs.corpus == 'true' &&",
        "(needs.changes.outputs.corpus == 'true'",
        "",
    ],
)
def test_evaluator_fails_loudly_on_unrecognized_or_malformed_input(unknown_expr: str) -> None:
    """모르는 어휘·깨진 문법을 조용히 True/False로 접으면 검증이 아니라 위장이다."""
    with pytest.raises(AssertionError):
        job_reachable_under_flags(unknown_expr, _CORPUS)


def test_violations_function_on_synthetic_workflow() -> None:
    """워크플로 단위 판정 — 버그 잡은 위반, 수정 잡·무조건 잡은 무위반, 스텝 없는 잡은 무시."""
    gate_step = {"name": "게이트", "if": "needs.changes.outputs.corpus == 'true'"}

    def jobs_with(job_if: str | None) -> dict[str, Any]:
        job: dict[str, Any] = {"steps": [gate_step]}
        if job_if is not None:
            job["if"] = job_if
        return {"j": job, "plain": {"steps": [{"name": "상시", "run": "true"}]}}

    assert len(reachability_violations(jobs_with(_BUGGY_JOB_IF))) == 1
    assert len(reachability_violations(jobs_with(_AND_MUTATION_JOB_IF))) == 1
    assert reachability_violations(jobs_with(_FIXED_JOB_IF)) == []
    assert reachability_violations(jobs_with(None)) == []
