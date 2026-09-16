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
from pathlib import Path
from typing import Any

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
