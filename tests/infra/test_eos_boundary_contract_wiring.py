"""EOS Core↔Adapter 경계 계약의 **정합성 + 배선 실재** 동결 (EOS-67 acceptance ③).

이 저장소는 "만들었는데 안 도는 것"에 반복해서 뚫렸다(`tests/infra` 199건 미실행·브랜치
보호 required check 미강제·`tests/infra` lint 잡 부재). 그래서 계약을 하나 세울 때마다
**그것이 CI에서 실제로 실행되는지**를 기계가 대조한다(OPS-10 선례).

여기서 막는 것은 두 가지다.

1. **드리프트** — `pyproject.toml`의 forbidden 목록과 배정 정본(`BOUNDARY_MAP`)이 어긋나는 것.
   pyproject를 손으로 고치고 정본을 안 고치면(또는 반대) 이중 진실 원천이 된다.
2. **미배선** — 계약이 파일에는 있는데 CI 잡이 `lint-imports`를 부르지 않는 것.
   "pyproject에 존재함"과 "잡이 돌아감"은 다르다.

`lint-imports`의 *판정 자체*는 여기서 재현하지 않는다(그건 CI lint 스텝이 한다). 이 파일은
계약이 **올바른 대상을 가리키고 실제로 호출되는지**만 본다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO_ROOT / "src" / "backend" / "pyproject.toml"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_SCAN_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "eos_core_adapter_boundary_scan.py"
_BOUNDARY_DOC = _REPO_ROOT / "docs" / "architecture" / "eos_core_adapter_boundary.md"

_ROOT_PACKAGE = "whymath_backend"
_CONTRACT_NAME_PREFIX = "EOS Core → Math Adapter 금지"


def _load_scan_module() -> Any:
    """경계 스캔 스크립트를 모듈로 적재한다 — 배정·리포트 양쪽의 단일 진실 원천."""
    name = "_eos_boundary_scan"
    spec = importlib.util.spec_from_file_location(name, _SCAN_SCRIPT)
    assert spec is not None and spec.loader is not None, f"스캔 스크립트 로드 불가: {_SCAN_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    # `@dataclass`가 어노테이션을 풀 때 sys.modules에서 자기 모듈을 찾는다 — 등록 없이
    # exec_module하면 AttributeError로 죽는다(실측 2026-08-31).
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _load_boundary_map() -> dict[str, tuple[str, str]]:
    """배정 정본을 스크립트에서 직접 읽는다 — 목록을 여기 복사하면 진실이 셋이 된다."""
    boundary_map: dict[str, tuple[str, str]] = _load_scan_module().BOUNDARY_MAP
    return boundary_map


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    all_contracts: list[dict[str, Any]] = data["tool"]["importlinter"]["contracts"]
    return [c for c in all_contracts if str(c.get("name", "")).startswith(_CONTRACT_NAME_PREFIX)]


# ──────────────────────────────────────────────────────────────────────
# ① 드리프트 — 계약 목록 ↔ 배정 정본
# ──────────────────────────────────────────────────────────────────────


def test_eos_boundary_contracts_exist() -> None:
    contracts = _contracts()
    assert (
        len(contracts) == 2
    ), f"EOS 경계 계약이 2건이어야 한다(깨끗한 구역 / baseline 있음). 실측 {len(contracts)}건"
    assert {c["type"] for c in contracts} == {"forbidden"}


def test_forbidden_modules_match_the_adapter_assignment_exactly() -> None:
    """forbidden 목록 == BOUNDARY_MAP의 ADAPTER 키 전체. 어느 쪽이 빠져도 실패한다.

    빠지면 그 어댑터는 아무도 안 막고(위험), 남으면 존재하지 않는 모듈을 가리킨다(거짓 안심).
    """
    expected = {
        f"{_ROOT_PACKAGE}.{key}"
        for key, (verdict, _) in _load_boundary_map().items()
        if verdict == "ADAPTER"
    }
    assert expected, "정본에 ADAPTER 배정이 하나도 없다 — 스캔 스크립트 로드가 잘못됐다"

    for contract in _contracts():
        actual = set(contract["forbidden_modules"])
        missing = expected - actual
        extra = actual - expected
        assert (
            not missing
        ), f"[{contract['name']}] 정본에 있으나 계약에 없는 ADAPTER: {sorted(missing)}"
        assert not extra, f"[{contract['name']}] 계약에 있으나 정본에 없는 모듈: {sorted(extra)}"


def test_source_modules_are_never_adapter_assigned() -> None:
    """source에 ADAPTER 배정 모듈이 들어가면 안 된다 — 어댑터끼리의 의존을 위반으로 오판한다."""
    boundary = _load_boundary_map()
    adapters = {
        f"{_ROOT_PACKAGE}.{key}" for key, (verdict, _) in boundary.items() if verdict == "ADAPTER"
    }
    for contract in _contracts():
        offending = [src for src in contract["source_modules"] if src in adapters]
        assert not offending, f"[{contract['name']}] ADAPTER를 source로 잡았다: {offending}"


def test_clean_region_contract_carries_no_baseline() -> None:
    """'깨끗한 구역' 계약은 유예를 가지면 안 된다 — 유예가 붙는 순간 이름이 거짓이 된다."""
    clean = [c for c in _contracts() if "baseline 0" in c["name"]]
    assert len(clean) == 1, "baseline 0 계약이 정확히 1건이어야 한다"
    assert not clean[0].get(
        "ignore_imports"
    ), "깨끗한 구역 계약에 ignore_imports가 생겼다 — 깨끗하지 않다면 baseline 계약으로 옮겨라"


def test_baseline_entries_are_documented_as_debt_with_an_owner() -> None:
    """baseline 계약의 유예에는 해소 소유자(EOS-69)와 재확인 지점이 주석으로 붙어 있어야 한다.

    "만료 없는 유예 금지" — 만료의 1차 집행은 import-linter의
    `unmatched_ignore_imports_alerting`(기본 ERROR)이지만, *누가 언제* 갚는지는 사람이 읽는다.
    """
    raw = _PYPROJECT.read_text(encoding="utf-8")
    baseline_section = raw.split("그룹 ②", 1)
    assert len(baseline_section) == 2, "baseline 유예 그룹(② 주석)이 없다"
    body = baseline_section[1]
    assert "EOS-69" in body, "baseline 유예에 해소 소유자 태스크가 적혀 있지 않다"
    assert re.search(r"G1|2026-09-27", body), "baseline 유예에 재확인 지점이 적혀 있지 않다"


def test_baseline_ignores_do_not_silently_outlive_the_debt() -> None:
    """유예 만료가 *기계*로 걸려 있는지 — 기본 ERROR 정책을 끄지 않았는지 확인한다.

    `unmatched_ignore_imports_alerting = "none"`(또는 warn)으로 낮추면, 빚을 갚아도 유예 줄이
    조용히 남는다. 그 순간 이 계약의 만료 장치가 사라진다.
    """
    for contract in _contracts():
        level = contract.get("unmatched_ignore_imports_alerting", "error")
        assert str(level).lower() == "error", (
            f"[{contract['name']}] unmatched_ignore_imports_alerting={level!r} — "
            "ERROR가 아니면 갚은 빚의 유예 줄이 조용히 남는다"
        )


# ──────────────────────────────────────────────────────────────────────
# ② 배선 실재 — CI가 실제로 부르는가
# ──────────────────────────────────────────────────────────────────────


def test_ci_actually_runs_lint_imports() -> None:
    """'pyproject에 존재함'과 '잡이 돌아감'은 다르다 — CI가 lint-imports를 부르는지 대조."""
    ci = _CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^\s*run:\s*lint-imports\s*$", ci
    ), "ci.yml에 `run: lint-imports` 스텝이 없다 — 계약이 파일에만 있고 돌지 않는다"


def test_boundary_doc_and_scan_script_exist_as_the_referenced_sources() -> None:
    """계약 주석이 가리키는 정본·해설 파일이 실재하는지 — 링크가 썩으면 계약을 못 고친다."""
    assert _SCAN_SCRIPT.is_file(), f"배정 정본 스크립트 부재: {_SCAN_SCRIPT}"
    assert _BOUNDARY_DOC.is_file(), f"경계 해설 문서 부재: {_BOUNDARY_DOC}"
    pyproject = _PYPROJECT.read_text(encoding="utf-8")
    assert "eos_core_adapter_boundary_scan.py" in pyproject
    assert "eos_core_adapter_boundary.md" in pyproject


# ──────────────────────────────────────────────────────────────────────
# ③ 이 테스트 자체의 변별력 — 검사기가 고장나면 조용히 통과하지 않는가
# ──────────────────────────────────────────────────────────────────────


def test_boundary_map_loader_actually_returns_the_real_assignment() -> None:
    """로더가 빈 dict를 조용히 돌려주면 드리프트 검사는 '비교 대상 0건'으로 항상 통과한다.

    그 위장을 막기 위해, 로더가 실제 정본을 읽었다는 증거(알려진 키·4배정 전부)를 요구한다.
    """
    boundary = _load_boundary_map()
    assert len(boundary) > 30, f"정본 키가 너무 적다({len(boundary)}) — 로더가 실물을 못 읽었다"
    verdicts = {verdict for verdict, _ in boundary.values()}
    assert verdicts == {"CORE", "ADAPTER", "INFRA", "MIXED"}
    # 경계 문서가 근거로 드는 대표 배정 — 바뀌면 문서와 함께 고쳐야 한다
    assert boundary["l2"][0] == "CORE"
    assert boundary["l3.equivalent"][0] == "ADAPTER"
    assert boundary["l5.ocr"][0] == "ADAPTER"


# ──────────────────────────────────────────────────────────────────────
# ④ 집행 사실의 stale 방지 (EOS-03) — "아무도 막고 있지 않다"로 되돌아가지 않는가
# ──────────────────────────────────────────────────────────────────────
#
# 사고 경위: `EOS-67`이 2026-08-31에 집행을 붙였는데, 경계 스캔의 docstring과 위반 0건 출력
# 문안은 그 이전 상태("CI에 붙기 전까지 … 아무도 막고 있지 않다 — 집행은 EOS-67")를 2주 넘게
# 그대로 말했다. 방향은 안전한 쪽(집행을 *과소* 보고)이지만, G1 판정 근거로 인용되면 "집행
# 장치가 없다"는 잘못된 전제를 만든다. 실제로 2026-09-16 재대조에서 두 서브에이전트가 이
# 문안을 근거로 "게이트 아님"을 보고했다.
#
# 이 검사가 막는 것은 **문안이 과거 시제로 되돌아가는 것**이지 문안의 문학적 형태가 아니다.
# 그래서 금지 문자열 열거가 아니라 *구성된 산출물*(실제 렌더된 리포트)을 본다.


def _render_scan_report() -> str:
    """스캔을 실제로 돌려 리포트 문자열을 얻는다 — 소스 grep이 아니라 *구성된 산출물* 검사.

    금지 문자열 열거는 표기 변형에서 뚫린다(CLAUDE.md "금지 패턴 열거 대신 산출물 검사").
    그래서 사람이 실제로 읽게 되는 markdown을 만들어 놓고 본다.
    """
    module = _load_scan_module()
    source = _REPO_ROOT / module.DEFAULT_SOURCE
    facts, errors = module.scan(source, lambda *_: None)
    return str(
        module.render_markdown(facts, module.violations(facts), module.summarize(facts), errors)
    )


def test_scan_report_does_not_claim_the_boundary_is_unenforced() -> None:
    """위반 0건 문안이 "아무도 막고 있지 않다"로 되돌아가면 적색.

    `EOS-67` 계약 2건은 CI `backend` 잡의 `lint-imports`가 매 PR 판정한다(위 §②가 그 배선
    실재를 따로 동결한다). 그 사실이 선 뒤에도 스캔이 "미집행"을 말하면 두 기계가 서로 다른
    현실을 보고하는 것이다.
    """
    report = _render_scan_report()
    assert "아무도 막고 있지 않" not in report, (
        "경계 스캔 리포트가 여전히 '아무도 막고 있지 않다'고 말한다 — "
        "EOS-67(2026-08-31 done)이 import-linter 계약으로 집행을 붙인 뒤로 이 문안은 거짓이다"
    )


def test_scan_report_names_the_enforcing_contract_and_its_blind_spot() -> None:
    """정정된 문안이 갖춰야 할 두 가지 — 집행 주체와 그 집행의 사각.

    "집행이 있다"만 적으면 이번엔 반대 방향으로 틀린다(경유 의존·MIXED는 계약이 보지 않는다).
    과소 보고를 고치면서 과대 보고를 만들지 않도록 둘 다 요구한다.
    """
    report = _render_scan_report()
    assert "EOS-67" in report, "집행 주체를 지목하지 않는다"
    assert "lint-imports" in report, "집행이 실제로 도는 스텝 이름이 없다"
    # `or`로 묶지 않는다 — 한쪽만 남아도 통과하면 나머지 절은 검증된 적이 없는 채로
    # "검증된 가드"에 계상된다(뮤테이션 M3 생존으로 실측: 2026-09-16).
    assert (
        "직접 import" in report
    ), "0건이 무엇을 센 0인지 적지 않는다 — 범위를 안 적은 0은 '전부 막혔다'로 오독된다"
    assert "allow_indirect_imports" in report, (
        "계약의 사각을 그 설정 키 이름으로 지목하지 않는다 — "
        "'경유는 안 센다'는 산문만으로는 어느 계약의 어느 설정이 그렇게 만드는지 추적 불가다"
    )


def test_scan_module_docstring_records_that_enforcement_landed() -> None:
    """모듈 docstring도 같은 사실을 말하는가 — 리포트만 고치고 소스 주석을 두면 다시 갈린다."""
    module = _load_scan_module()
    doc = module.__doc__ or ""
    assert (
        "CI에 붙기 전까지" not in doc
    ), "docstring이 아직 '집행 전' 조건문으로 적혀 있다 — 그 조건은 2026-08-31에 충족됐다"
    assert "EOS-67" in doc and "lint-imports" in doc


# ──────────────────────────────────────────────────────────────────────
# ⑤ 소유 잡의 **도달성** — "막음 ≠ 이번 실행에서 도달함" (EOS-117 · P-12)
# ──────────────────────────────────────────────────────────────────────
#
# 이 저장소는 같은 사슬을 네 단계로 겪었다:
#   ① 존재함 ≠ 돌아감     (OPS-10 — `tests/infra` 199건을 어느 잡도 실행하지 않던 상태)
#   ② 선언함 ≠ 배선됨     (OPS-22 — `declared_unwired_audit`)
#   ③ 돌아감 ≠ 막음       (OPS-29 — `continue-on-error`·`|| true`가 판정을 삼키는 축)
#   ④ 막음   ≠ **도달함** (CLAUDE.md v0.2.27 — 스텝 목록은 맞췄는데 잡을 통째로 빠뜨림)
#
# 위 §②의 `test_ci_actually_runs_lint_imports`는 ①만 잰다 — ci.yml 어딘가에
# `run: lint-imports` 줄이 있는지 정규식으로 볼 뿐이다. 그래서 **그 스텝을 야간 전용 잡
# (`e2e-nightly` · `if: github.event_name == 'schedule'`)으로 옮겨도 초록이다.**
#
# 실측(2026-09-19 · EOS-117): 그 뮤테이션을 넣고 `tests/infra` 전건을 돌렸더니
# `1520 passed, 1 skipped` — 경계 import 계약이 PR에서 **한 번도 판정되지 않는** 상태를
# 어떤 가드도 보지 못했다. 정상 입력에서 초록인 것은 보호의 증거가 아니다.
#
# 그래서 이 절은 스텝이 아니라 **그 스텝을 소유한 잡이, 위반을 실어 오는 PR에서 실제로
# 깨어나는가**를 동결한다. 판정은 잡 `if` 식을 *평가해서* 한다 — 문자열 검사로는
# `needs.changes.outputs.<플래그>`가 어느 경로에 걸리는지 알 수 없기 때문이다.


class CIConditionError(AssertionError):
    """잡 `if` 식을 해석하지 못했다 — **측정 실패이지 통과가 아니다**."""


_TRIGGER_WIRING_TEST = Path(__file__).with_name("test_ci_contract_fixture_trigger_wiring.py")

_COND_TOKEN_RE = re.compile(r"\s*(?P<tok>\(|\)|&&|\|\||==|!=|!|'[^']*'|[A-Za-z_][A-Za-z0-9_.\-]*)")


def _load_trigger_wiring_module() -> Any:
    """CI `changes` 필터 파서를 **재구현하지 않고 기존 정본에서 빌려 쓴다**.

    같은 필터 문법을 두 번 파싱하면 진실이 둘이 된다(COLLAB-04/07 선례). 그래서 이 절은
    파서를 새로 쓰지 않고 `test_ci_contract_fixture_trigger_wiring.py`의 것을 적재한다.
    """
    name = "_eos_ci_trigger_wiring"
    spec = importlib.util.spec_from_file_location(name, _TRIGGER_WIRING_TEST)
    assert (
        spec is not None and spec.loader is not None
    ), f"필터 파서 로드 불가: {_TRIGGER_WIRING_TEST}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


def _tokenize_condition(expr: str) -> list[str]:
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        match = _COND_TOKEN_RE.match(expr, pos)
        if match is None:
            if not expr[pos:].strip():
                break
            raise CIConditionError(f"조건식 해석 실패(위치 {pos}): {expr!r}")
        tokens.append(match.group("tok"))
        pos = match.end()
    if not tokens:
        raise CIConditionError(f"조건식이 비었다: {expr!r}")
    return tokens


class _ConditionEvaluator:
    """GitHub Actions `if` 식 중 **이 저장소가 실제로 쓰는 부분집합**만 평가한다.

    지원: `(` `)` · `&&` · `||` · `!` · `==` · `!=` · 작은따옴표 문자열 · 컨텍스트 참조.
    모르는 참조·문법은 **예외로 터뜨린다** — 해석 실패를 "실행됨"으로 반올림하면 이 절
    전체가 위장이 된다(CLAUDE.md "측정 실패가 통과로 위장되면 안 된다").
    """

    def __init__(self, tokens: list[str], context: Mapping[str, str]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._context = context

    def evaluate(self) -> bool:
        value = self._parse_or()
        if self._pos != len(self._tokens):
            raise CIConditionError(
                f"조건식에 해석되지 않은 토큰이 남았다: {self._tokens[self._pos :]}"
            )
        return self._truthy(value)

    # ── 파서 ──────────────────────────────────────────────────────────
    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise CIConditionError("조건식이 예기치 않게 끝났다")
        self._pos += 1
        return token

    def _parse_or(self) -> str | bool:
        value = self._parse_and()
        while self._peek() == "||":
            self._take()
            right = self._parse_and()
            value = self._truthy(value) or self._truthy(right)
        return value

    def _parse_and(self) -> str | bool:
        value = self._parse_compare()
        while self._peek() == "&&":
            self._take()
            right = self._parse_compare()
            value = self._truthy(value) and self._truthy(right)
        return value

    def _parse_compare(self) -> str | bool:
        left = self._parse_unary()
        operator = self._peek()
        if operator in ("==", "!="):
            self._take()
            right = self._parse_unary()
            return (left == right) if operator == "==" else (left != right)
        return left

    def _parse_unary(self) -> str | bool:
        if self._peek() == "!":
            self._take()
            return not self._truthy(self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self) -> str | bool:
        token = self._take()
        if token == "(":
            value = self._parse_or()
            if self._take() != ")":
                raise CIConditionError("닫는 괄호가 없다")
            return value
        if token.startswith("'"):
            return token[1:-1]
        if token in ("true", "false"):
            return token == "true"
        if token in self._context:
            return self._context[token]
        raise CIConditionError(
            f"모르는 컨텍스트 참조: {token!r} — 해석할 수 없는 식을 '실행됨'으로 "
            "반올림하지 않는다. 이 평가기가 새 문법을 지원해야 한다면 함께 고쳐라."
        )

    @staticmethod
    def _truthy(value: str | bool) -> bool:
        return value if isinstance(value, bool) else value != ""


def evaluate_job_condition(expression: Any, context: Mapping[str, str]) -> bool:
    """잡/스텝의 `if` 값을 주어진 컨텍스트에서 평가한다. `if`가 없으면 항상 실행이다."""
    if expression is None:
        return True
    if not isinstance(expression, str):
        raise CIConditionError(f"`if` 값이 문자열이 아니다: {expression!r}")
    body = expression.strip()
    if body.startswith("${{") and body.endswith("}}"):
        body = body[3:-2]
    return _ConditionEvaluator(_tokenize_condition(body), context).evaluate()


@dataclass(frozen=True)
class GateSeat:
    """경계 게이트 1종과 **그 게이트를 반드시 깨워야 하는 PR 변경 집합**."""

    label: str
    run_needle: str
    # 각 원소가 하나의 PR 변경 집합이다. 전건이 소유 잡을 깨워야 한다.
    # 빈 튜플 = "아무 경로 플래그도 켜지지 않은 PR"(= 무게이트 잡이어야 한다는 뜻).
    waking_changesets: tuple[tuple[str, ...], ...]
    why: str


def _jobs_from_ci_text(ci_text: str) -> dict[str, Any]:
    wiring = _load_trigger_wiring_module()
    try:
        spec = yaml.safe_load(ci_text)
    except yaml.YAMLError as exc:  # 침묵 실패 금지 — 예외 타입명을 남긴다
        raise CIConditionError(f"ci.yml YAML 파싱 실패 {type(exc).__name__}: {exc}") from exc
    jobs: dict[str, Any] = wiring._extract_jobs(spec, "ci.yml")
    return jobs


def _changes_flags_for(jobs: Mapping[str, Any], changed: Sequence[str]) -> dict[str, str]:
    """PR이 `changed` 경로만 바꿨을 때 `changes` 잡이 내보낼 플래그 값."""
    wiring = _load_trigger_wiring_module()
    script = wiring._changes_filter_script(jobs)
    regex_by_output: dict[str, str] = wiring._filter_regex_by_output(script, [])
    if not regex_by_output:
        raise CIConditionError("경로 필터를 하나도 해석하지 못했다 — 도달성 판정이 성립하지 않는다")
    return {
        output: ("true" if any(re.compile(pattern).search(p) for p in changed) else "false")
        for output, pattern in regex_by_output.items()
    }


def _is_non_blocking(node: Mapping[str, Any]) -> bool:
    return bool(node.get("continue-on-error"))


def find_gate_seat_violations(ci_text: str, seats: Sequence[GateSeat]) -> list[str]:
    """게이트 좌석별 도달성 위반 목록. **빈 목록 = 도달 가능**."""
    jobs = _jobs_from_ci_text(ci_text)
    wiring = _load_trigger_wiring_module()
    violations: list[str] = []

    for seat in seats:
        owners = [
            name
            for name, job in jobs.items()
            if isinstance(job, dict)
            and any(seat.run_needle in run for run in wiring._iter_run_steps(job))
        ]
        if len(owners) != 1:
            violations.append(
                f"[{seat.label}] `{seat.run_needle}`를 돌리는 잡이 {len(owners)}개다"
                f"({sorted(owners)}) — 1개가 아니면 어느 잡의 도달성을 재야 하는지 결정 불가다"
            )
            continue

        owner = owners[0]
        job = jobs[owner]

        for changeset in seat.waking_changesets:
            flags = _changes_flags_for(jobs, changeset)
            context: dict[str, str] = {"github.event_name": "pull_request"}
            context.update({f"needs.changes.outputs.{k}": v for k, v in flags.items()})
            if not evaluate_job_condition(job.get("if"), context):
                shown = list(changeset) or ["(경로 변경 없음)"]
                violations.append(
                    f"[{seat.label}] 소유 잡 `{owner}`이 {shown} 만 바꾼 PR에서 실행되지 "
                    f"않는다 — if={job.get('if')!r} · 플래그={flags}. {seat.why}"
                )

        if _is_non_blocking(job):
            violations.append(
                f"[{seat.label}] 소유 잡 `{owner}`이 continue-on-error다 — 막지 못한다"
            )
        for step in wiring._iter_steps(job):
            run = step.get("run")
            if isinstance(run, str) and seat.run_needle in run and _is_non_blocking(step):
                violations.append(
                    f"[{seat.label}] `{seat.run_needle}` 스텝이 continue-on-error다 — 막지 못한다"
                )

    return violations


def _real_core_source_sample() -> str:
    """CORE 배정 모듈의 **실재** 소스 파일 하나(레포 상대 경로).

    가상의 경로로 통과/실패를 만들지 않는다(`test_ci_contract_fixture_trigger_wiring.py`의
    "표본은 실재 파일에서 뽑는다" 규약과 동형). CORE 소스가 곧 위반이 들어올 자리다.
    """
    package_root = _REPO_ROOT / "src" / "backend" / "whymath_backend"
    for key, (verdict, _reason) in sorted(_load_boundary_map().items()):
        if verdict != "CORE" or not key:
            continue
        target = package_root.joinpath(*key.split("."))
        candidates = sorted(target.glob("*.py")) if target.is_dir() else []
        if target.with_suffix(".py").is_file():
            candidates = [target.with_suffix(".py")] + candidates
        for candidate in candidates:
            return str(candidate.relative_to(_REPO_ROOT))
    raise AssertionError("CORE 배정 모듈의 실재 소스 파일을 하나도 찾지 못했다 — 표본 추출 실패")


def _gate_seats() -> tuple[GateSeat, ...]:
    core_sample = _real_core_source_sample()
    return (
        GateSeat(
            label="EOS-67 Core→Adapter import 계약(lint-imports)",
            run_needle="lint-imports",
            # 위반이 들어오는 자리(CORE 소스)와 계약이 약해지는 자리(pyproject) — 둘 다
            # 각각 단독으로 이 잡을 깨워야 한다. `any` 합산이 아니라 **건별** 판정이다.
            waking_changesets=((core_sample,), ("src/backend/pyproject.toml",)),
            why=(
                "Core→Adapter import 위반은 CORE 소스에 들어오고 계약 약화는 pyproject에서 "
                "일어난다 — 그 PR에서 잡이 SKIP되면 계약은 파일에만 있고 판정되지 않는다"
            ),
        ),
        GateSeat(
            label="EOS-84/EOS-04 AST·어휘 게이트(pytest tests/infra)",
            run_needle="pytest tests/infra",
            # 빈 변경 집합 = 어떤 경로 플래그도 켜지지 않는 PR. AST 리터럴 분기·어휘 ratchet·
            # 이 파일 자신이 **경로와 무관하게** 돌아야 하는 이유: 배정 정본
            # (`scripts/analysis/…`)은 어떤 `changes` 필터에도 없다.
            waking_changesets=((),),
            why=(
                "경계 배정 정본은 `scripts/analysis/`에 있어 어떤 경로 필터에도 잡히지 "
                "않는다 — 이 게이트가 경로 게이팅을 타면 그 PR에서 통째로 사라진다"
            ),
        ),
    )


def test_boundary_gate_seats_are_reachable_on_the_prs_that_carry_the_violation() -> None:
    """④ 축 — 게이트를 소유한 잡이 *위반을 실어 오는 PR*에서 실제로 깨어나는가.

    §②는 `run: lint-imports` 줄의 **존재**만 본다. 그 줄을 야간 전용 잡으로 옮겨도 §②는
    초록이고(실측 2026-09-19: `tests/infra` 1520 passed), 그 상태에서 경계 계약은 PR을
    한 번도 막지 못한다. 이 검사가 그 간극을 닫는다.
    """
    violations = find_gate_seat_violations(_CI_WORKFLOW.read_text(encoding="utf-8"), _gate_seats())
    assert not violations, (
        "경계 게이트의 소유 잡이 위반을 실어 오는 PR에서 실행되지 않는다 — "
        "'ci.yml에 스텝이 있다'와 '그 PR에서 그 스텝이 돈다'는 다르다:\n  · "
        + "\n  · ".join(violations)
    )


def test_gate_seat_samples_are_real_files_not_invented_paths() -> None:
    """표본이 실재하지 않으면 위 검사는 '아무 경로에도 안 걸리는 PR'을 재는 셈이 된다."""
    for seat in _gate_seats():
        for changeset in seat.waking_changesets:
            for path in changeset:
                assert (
                    _REPO_ROOT / path
                ).is_file(), f"[{seat.label}] 표본이 실재하지 않는다: {path}"


# ── ④ 축 자신의 변별력 — 결함을 주입하면 실제로 RED인가 ────────────────────────
#
# "정상 입력에서 초록"은 보호의 증거가 아니다(CLAUDE.md 실패 주입 규칙). 아래 뮤테이션은
# 전부 **실제 ci.yml 텍스트**를 대상으로 하고, 주입이 실제로 적용됐는지(`mutated != original`)를
# 먼저 단언한다 — 주입이 조용히 실패하면 "검출 실패"가 "검출"처럼 보인다(2026-09-06 교훈).

_LINT_IMPORTS_STEP = (
    "      - name: Import contracts (import-linter — 7계층 단방향)\n        run: lint-imports\n"
)


def _ci_text() -> str:
    return _CI_WORKFLOW.read_text(encoding="utf-8")


def _insert_into_job_steps(text: str, job: str, block: str) -> str:
    start = text.index(f"\n  {job}:\n")
    anchor = text.index("    steps:\n", start) + len("    steps:\n")
    return text[:anchor] + block + text[anchor:]


def _mutate_move_gate_to_nightly_only_job(text: str) -> str:
    """M1 — 실측된 그 뮤테이션: 게이트 스텝을 야간(schedule) 전용 잡으로 옮긴다."""
    assert text.count(_LINT_IMPORTS_STEP) == 1, "앵커가 1건이 아니다 — 주입 대상을 못 찾았다"
    return _insert_into_job_steps(
        text.replace(_LINT_IMPORTS_STEP, "", 1), "e2e-nightly", _LINT_IMPORTS_STEP
    )


def _mutate_gate_job_watches_the_wrong_flag(text: str) -> str:
    """M2 — 소유 잡의 경로 게이트가 엉뚱한 플래그를 본다(backend → mobile).

    치환 범위를 **소유 잡 블록 안으로 한정**한다. 같은 문자열이 `backend-serial-nightly`
    등 다른 잡의 `if`에도 있어 전역 치환은 앵커 1건 단언에서 터진다(실측 2건).
    """
    start = text.index("\n  backend:\n")
    old = "needs.changes.outputs.backend == 'true'"
    hit = text.index(old, start)
    assert (
        text.count(old, start, text.index("\n  backend-migrations:\n")) == 1
    ), "backend 잡 블록 안의 if 앵커가 1건이 아니다 — 주입 대상을 결정할 수 없다"
    return text[:hit] + "needs.changes.outputs.mobile == 'true'" + text[hit + len(old) :]


def _mutate_ast_gate_becomes_path_gated(text: str) -> str:
    """M3 — 상시 도는 AST·어휘 게이트 잡에 경로 게이트를 붙인다."""
    old = "  infra-contracts:\n    name: infra-contracts"
    assert text.count(old) == 1, "infra-contracts 잡 앵커가 1건이 아니다"
    new = (
        "  infra-contracts:\n"
        "    needs: changes\n"
        "    if: needs.changes.outputs.backend == 'true'\n"
        "    name: infra-contracts"
    )
    return text.replace(old, new, 1)


def _mutate_gate_step_is_non_blocking(text: str) -> str:
    """M4 — 스텝은 돌지만 실패해도 막지 못한다(③ 축과의 접점)."""
    assert text.count(_LINT_IMPORTS_STEP) == 1
    return text.replace(
        _LINT_IMPORTS_STEP,
        _LINT_IMPORTS_STEP.rstrip("\n") + "\n        continue-on-error: true\n",
        1,
    )


def _mutate_gate_has_two_owner_jobs(text: str) -> str:
    """M5 — 같은 게이트가 두 잡에 있어 어느 잡의 도달성을 재야 하는지 결정 불가."""
    assert text.count(_LINT_IMPORTS_STEP) == 1
    return _insert_into_job_steps(text, "e2e-nightly", _LINT_IMPORTS_STEP)


def _mutate_gate_is_deleted(text: str) -> str:
    """M6 — 게이트 스텝이 통째로 사라진다(소유 잡 0개)."""
    assert text.count(_LINT_IMPORTS_STEP) == 1
    return text.replace(_LINT_IMPORTS_STEP, "", 1)


@pytest.mark.parametrize(
    ("mutate", "expect_in_message"),
    [
        (_mutate_move_gate_to_nightly_only_job, "lint-imports"),
        (_mutate_gate_job_watches_the_wrong_flag, "lint-imports"),
        (_mutate_ast_gate_becomes_path_gated, "pytest tests/infra"),
        (_mutate_gate_step_is_non_blocking, "continue-on-error"),
        (_mutate_gate_has_two_owner_jobs, "2개"),
        (_mutate_gate_is_deleted, "0개"),
    ],
    ids=[
        "nightly-only",
        "wrong-flag",
        "ast-gate-path-gated",
        "non-blocking",
        "two-owners",
        "deleted",
    ],
)
def test_reachability_checker_detects_injected_wiring_defects(
    mutate: Any, expect_in_message: str
) -> None:
    original = _ci_text()
    mutated = mutate(original)
    assert mutated != original, "주입이 적용되지 않았다 — 통과가 '검출'로 위장된다"
    violations = find_gate_seat_violations(mutated, _gate_seats())
    assert violations, f"주입 {mutate.__name__}을 검출하지 못했다 — 가드가 변별력이 없다"
    assert any(expect_in_message in v for v in violations), violations


def test_reachability_checker_passes_the_unmutated_workflow() -> None:
    """대조군 — 주입이 없으면 위반 0. 이것이 없으면 '전부 위반'인 과잉 수정이 통과한다."""
    assert find_gate_seat_violations(_ci_text(), _gate_seats()) == []


@pytest.mark.parametrize(
    ("expression", "event", "flags", "expected"),
    [
        ("github.event_name != 'schedule'", "pull_request", {}, True),
        ("github.event_name != 'schedule'", "schedule", {}, False),
        ("github.event_name == 'schedule'", "pull_request", {}, False),
        (
            "(github.event_name != 'pull_request' || needs.changes.outputs.backend == 'true')"
            " && github.event_name != 'schedule'",
            "pull_request",
            {"backend": "true"},
            True,
        ),
        (
            "(github.event_name != 'pull_request' || needs.changes.outputs.backend == 'true')"
            " && github.event_name != 'schedule'",
            "pull_request",
            {"backend": "false"},
            False,
        ),
        ("!(github.event_name == 'schedule')", "pull_request", {}, True),
        ("${{ github.event_name == 'pull_request' }}", "pull_request", {}, True),
    ],
)
def test_condition_evaluator_truth_table(
    expression: str, event: str, flags: dict[str, str], expected: bool
) -> None:
    """평가기가 `&&`·`||`·`!`·괄호·`${{ }}`를 실제로 구별하는가 — 성공/실패 양방향 대조."""
    context = {"github.event_name": event}
    context.update({f"needs.changes.outputs.{k}": v for k, v in flags.items()})
    assert evaluate_job_condition(expression, context) is expected


def test_condition_evaluator_refuses_what_it_cannot_understand() -> None:
    """모르는 식을 '실행됨'으로 반올림하지 않는다 — 그 순간 이 절 전체가 위장이 된다."""
    with pytest.raises(CIConditionError):
        evaluate_job_condition("github.actor == 'nobody'", {"github.event_name": "push"})
    with pytest.raises(CIConditionError):
        evaluate_job_condition("(github.event_name == 'push'", {"github.event_name": "push"})
    with pytest.raises(CIConditionError):
        evaluate_job_condition("github.event_name == 'push' extra", {"github.event_name": "push"})
    with pytest.raises(CIConditionError):
        evaluate_job_condition(["not", "a", "string"], {})


def test_condition_evaluator_absent_gate_means_always_runs() -> None:
    assert evaluate_job_condition(None, {}) is True


# ──────────────────────────────────────────────────────────────────────
# ⑥ 공허한 계약 금지 — "스캔 0건은 실패다" (EOS-117 · P-12 지시 4)
# ──────────────────────────────────────────────────────────────────────
#
# §①은 forbidden 쪽(어댑터 목록)을 정본과 **정확 일치**로 동결하지만, source 쪽은
# "ADAPTER를 source로 잡지 않았는가"만 봤다. 그래서 `source_modules = []`로 비우면
# 계약이 **아무것도 금지하지 않는 상태**가 되는데도 전건 초록이다.
#
# 실측(2026-09-19 · EOS-117): 'baseline 0' 계약의 `source_modules`를 `[]`로 바꾸고
# 이 파일을 돌렸더니 `12 passed` — 대상이 0건인 전수 가드는 공허하게 통과한다.
#
# 여기서 닫는 축 3종:
#   (a) 계약의 source/forbidden 집합이 비어 있지 않다
#   (b) CORE 배정 전건이 어느 계약의 source에 **포괄**된다(빠뜨린 CORE = 무방비 구역)
#   (c) (b)의 예외는 사유와 함께 열거된 것만 — 만료 없는 암묵 면제 금지

# `l3` 패키지 루트는 **통째로 source에 넣을 수 없다** — ADAPTER 모듈이 같은 계층에 살아
# 자기 자신을 금지하는 계약이 된다(pyproject 주석 "l3는 통째로 넣을 수 없다"). 그래서
# CORE 배정 `l3.*` 하위 키를 개별 열거하는 방식이며, 바로 그 이유로 이 키만 면제한다.
_SOURCE_COVERAGE_EXEMPTIONS: dict[str, str] = {
    "l3": "ADAPTER 모듈이 같은 패키지에 동거 — 하위 CORE 키를 개별 열거하는 방식(pyproject 주석)",
    # `l5`도 같은 구조다: 실코드가 전부 ADAPTER(`l5.ocr`)이고 CORE 실체는 `__init__.py`
    # 18줄(import 0건)뿐이다. `whymath_backend.l5`를 source로 넣으면 `l5.ocr`이 source가 돼
    # adapter→adapter를 위반으로 오판한다(§① `test_source_modules_are_never_adapter_assigned`가
    # 막으려는 바로 그 상태). `l3`와 달리 개별 열거할 CORE 하위 키가 없어 면제로 둔다.
    "l5": "실코드가 전부 ADAPTER(l5.ocr)이고 CORE 실체는 빈 __init__.py — 열거할 CORE 하위 키가 없다",
}


def find_vacuous_contract_violations(
    contracts: Sequence[Mapping[str, Any]],
    boundary_map: Mapping[str, tuple[str, str]],
) -> list[str]:
    """계약이 **공허해지는** 자리를 모은다. 빈 목록 = 계약이 실제로 무언가를 금지한다."""
    violations: list[str] = []
    if not contracts:
        return ["경계 계약이 0건이다 — 비교 대상이 없는 검사는 항상 통과한다"]

    covered: set[str] = set()
    for contract in contracts:
        name = contract.get("name", "(이름 없음)")
        sources = list(contract.get("source_modules") or [])
        forbidden = list(contract.get("forbidden_modules") or [])
        if not sources:
            violations.append(f"[{name}] source_modules가 비었다 — 아무것도 금지하지 않는 계약이다")
        if not forbidden:
            violations.append(f"[{name}] forbidden_modules가 비었다 — 금지 대상이 0건이다")
        covered.update(s.removeprefix(f"{_ROOT_PACKAGE}.") for s in sources)

    core_keys = [key for key, (verdict, _) in boundary_map.items() if verdict == "CORE" and key]
    if not core_keys:
        return violations + ["정본에 CORE 배정이 0건이다 — 배정 로드가 잘못됐다"]

    for key in sorted(core_keys):
        parts = key.split(".")
        if any(".".join(parts[:i]) in covered for i in range(1, len(parts) + 1)):
            continue
        if key in _SOURCE_COVERAGE_EXEMPTIONS:
            continue
        violations.append(
            f"CORE 배정 `{key}`가 어느 계약의 source_modules에도 포괄되지 않는다 — "
            "그 구역은 어댑터를 마음대로 import해도 계약이 침묵한다"
        )
    return violations


def test_boundary_contracts_are_not_vacuous() -> None:
    """(a)(b) — 계약이 실제로 무언가를 금지하고, CORE 전건이 그 사정권 안에 있는가."""
    violations = find_vacuous_contract_violations(_contracts(), _load_boundary_map())
    assert (
        not violations
    ), (
        "경계 계약이 공허하다 — 대상이 0건인 전수 가드는 아무것도 막지 않으면서 초록을 낸다:\n  · "
        + "\n  · ".join(violations)
    )


def test_source_coverage_exemptions_are_real_and_still_needed() -> None:
    """(c) — 면제 키가 실재하는 CORE 배정이고, 사유가 비어 있지 않은가.

    쓰이지 않는 면제는 조용히 남아 다음 사람에게 "여긴 원래 면제"라고 거짓말한다.
    """
    boundary = _load_boundary_map()
    for key, reason in _SOURCE_COVERAGE_EXEMPTIONS.items():
        assert key in boundary, f"면제 키 `{key}`가 배정 정본에 없다 — 썩은 면제다"
        assert boundary[key][0] == "CORE", f"면제 키 `{key}`가 CORE 배정이 아니다"
        assert reason.strip(), f"면제 키 `{key}`에 사유가 없다"
        sources = {
            s.removeprefix(f"{_ROOT_PACKAGE}.")
            for contract in _contracts()
            for s in contract.get("source_modules") or []
        }
        assert key not in sources, f"면제 키 `{key}`가 이미 source에 있다 — 면제가 불필요하다"


@pytest.mark.parametrize(
    ("mutate", "expect_in_message"),
    [
        (lambda c, b: ([{**c[0], "source_modules": []}, c[1]], b), "source_modules가 비었다"),
        (lambda c, b: ([{**c[0], "forbidden_modules": []}, c[1]], b), "forbidden_modules가 비었다"),
        (lambda c, b: ([], b), "계약이 0건"),
        (
            lambda c, b: (
                [{**c[0], "source_modules": [f"{_ROOT_PACKAGE}.l1"]}, c[1]],
                b,
            ),
            "l2",
        ),
        (lambda c, b: (c, {k: v for k, v in b.items() if v[0] != "CORE"}), "CORE 배정이 0건"),
    ],
    ids=["empty-source", "empty-forbidden", "no-contracts", "dropped-core-package", "no-core"],
)
def test_vacuity_checker_detects_injected_emptiness(mutate: Any, expect_in_message: str) -> None:
    """공허 검출기가 실제로 RED를 내는가 — 정상 입력 초록은 보호의 증거가 아니다."""
    contracts = _contracts()
    boundary = _load_boundary_map()
    mutated_contracts, mutated_boundary = mutate(contracts, boundary)
    assert (mutated_contracts, mutated_boundary) != (contracts, boundary), "주입이 적용되지 않았다"
    violations = find_vacuous_contract_violations(mutated_contracts, mutated_boundary)
    assert violations, "공허해진 계약을 검출하지 못했다"
    assert any(expect_in_message in v for v in violations), violations


def test_vacuity_checker_passes_the_real_contracts() -> None:
    """대조군 — 주입이 없으면 위반 0. 없으면 '전부 위반'인 과잉 수정이 통과한다."""
    assert find_vacuous_contract_violations(_contracts(), _load_boundary_map()) == []
