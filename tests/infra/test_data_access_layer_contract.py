"""데이터 접근 계층 처분 (b)의 **집행** — baseline 동결 + 신규 증가 차단 (ARCH-48).

## 정본화 ≠ 집행

`scripts/analysis/data_access_layer_audit.py`는 계측기다 — 세기만 하고 아무것도 막지 않는다.
**막는 것은 이 파일이다.** 처분과 근거는 `docs/architecture/data_access_layer_disposition.md`.

## 무엇을 막는가 (4축)

1. **신규 증가** — baseline 밖 파일이 세션·연결을 직접 조작하면 RED.
2. **baseline 썩음** — 데이터 접근이 사라진 파일이 baseline에 남아 있으면 RED(ratchet 지시).
   한 방향만 잠그면 리팩터로 비운 자리가 표에 남아 "아직 118건"이라는 거짓 숫자가 굳는다.
3. **이름 바꿔치기 회피** — `session`을 `sesh`로 고쳐 수신자 목록을 빠져나가는 것.
   세션 타입으로 *주석된* 이름이 목록 밖이면 RED.
4. **미배선** — 계약이 파일에만 있고 CI가 부르지 않는 것.
   "저장소에 존재함"과 "돌아감"은 다르다(OPS-03·OPS-08·OPS-11 반복 사고).

## 만료 (만료 없는 유예 금지)

`BASELINE_REVIEW_BY`가 지나면 RED. 기계적 ratchet만으로는 "118이 여전히 118"인 상태가
영원히 green이므로, 처분 자체의 재확인 기한을 별도로 둔다.

## 스캔 0건은 실패

전수 가드가 대상을 하나도 못 찾으면 공허하게 통과한다 — 그래서 하한을 단언한다.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG = _REPO_ROOT / "src" / "backend" / "whymath_backend"
_PYPROJECT = _REPO_ROOT / "src" / "backend" / "pyproject.toml"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "data_access_layer_audit.py"
_DISPOSITION_DOC = _REPO_ROOT / "docs" / "architecture" / "data_access_layer_disposition.md"

_CONTRACT_NAME = "데이터 접근 금지 (baseline 0 — 아직 DB를 모르는 구역)"

# 스캔이 최소한 이만큼은 찾아야 한다 — 못 찾으면 가드가 아니라 위장이다.
# 2026-09-16 실측 118파일의 절반. 절반까지 줄면 그것 자체가 큰 리팩터라 재확인이 옳다.
_MIN_EXPECTED_FILES = 59


def _load_audit_module() -> Any:
    """감사 스크립트를 모듈로 적재한다 — baseline·스캐너의 단일 진실 원천."""
    name = "_data_access_layer_audit"
    spec = importlib.util.spec_from_file_location(name, _AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None, f"감사 스크립트 로드 불가: {_AUDIT_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit() -> Any:
    return _load_audit_module()


@pytest.fixture(scope="module")
def scanned(audit: Any) -> tuple[dict[str, set[str]], dict[str, int], list[Any], list[str]]:
    messages: list[str] = []
    return audit.scan(_PKG, messages.append)


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    return list(data.get("tool", {}).get("importlinter", {}).get("contracts", []))


def _data_access_contract() -> dict[str, Any]:
    for contract in _contracts():
        if contract.get("name") == _CONTRACT_NAME:
            return contract
    pytest.fail(f"import-linter 계약 '{_CONTRACT_NAME}' 가 pyproject.toml에 없다")


# ── 축 0: 스캔 자체가 성립하는가 ────────────────────────────────────────────


def test_scan_finds_data_access_targets(scanned: Any) -> None:
    """스캔 0건은 실패다 — 대상을 못 찾은 전수 가드는 모든 입력에서 초록이다."""
    observed, _calls, _unknown, parse_failures = scanned
    total = sum(len(files) for files in observed.values())
    assert (
        parse_failures == []
    ), f"파싱 실패 {len(parse_failures)}건 — 측정 불완전: {parse_failures}"
    assert total >= _MIN_EXPECTED_FILES, (
        f"데이터 접근 파일 {total}건 — 하한 {_MIN_EXPECTED_FILES} 미만이다. "
        "스캐너가 망가졌거나(수신자·메서드 목록 오타) 대규모 리팩터가 있었다. "
        "후자라면 BASELINE과 이 하한을 함께 내려라 — 조용히 통과시키지 마라."
    )


def test_scanner_actually_discriminates(audit: Any, tmp_path: Path) -> None:
    """스캐너가 세션 호출과 동명이인(`set.add`)을 **가른다**는 것을 주입으로 확인한다.

    하한 단언(위)은 스캐너가 아무거나 세도 통과한다. 여기서 성공/실패 양방향을 본다.
    """
    pkg = tmp_path / "probe"
    (pkg / "api").mkdir(parents=True)
    # 양성: 세션 수신자 위의 세션 메서드.
    (pkg / "api" / "hit.py").write_text(
        "async def f(session):\n    await session.execute('x')\n", encoding="utf-8"
    )
    # 음성 대조군: 같은 메서드 이름이지만 수신자가 세션이 아니다(`set.add`).
    (pkg / "api" / "miss.py").write_text(
        "def g():\n    seen = set()\n    seen.add(1)\n    return seen\n", encoding="utf-8"
    )
    observed, calls, unknown, failures = audit.scan(pkg, lambda _m: None)
    assert failures == []
    assert observed.get("api") == {"api/hit.py"}, f"판별 실패: {observed}"
    assert calls.get("api/hit.py") == 1
    assert unknown == []


# ── 축 1·2: baseline 동결 (늘면 RED · 줄면 ratchet) ─────────────────────────


def test_no_new_data_access_outside_baseline(audit: Any, scanned: Any) -> None:
    """처분 (b)의 본체 — 데이터 접근을 **새 파일로 퍼뜨리지 못한다**."""
    observed, _calls, _unknown, _failures = scanned
    added, _removed = audit.baseline_diff(observed)
    assert not added, (
        "baseline 밖에서 ORM 세션·연결을 직접 잡는 파일이 생겼다 — 처분 (b) 위반:\n"
        + "\n".join(f"  [{layer}] {f}" for layer, files in sorted(added.items()) for f in files)
        + "\n\n해소: ① 기존 baseline 파일의 조회 함수를 재사용하거나 "
        "② 정말 새 접근점이 필요하면 data_access_layer_audit.py의 BASELINE에 "
        "추가하라(그 편집이 리뷰에서 보이는 것이 이 가드의 목적이다)."
    )


def test_baseline_has_no_stale_entries(audit: Any, scanned: Any) -> None:
    """줄었으면 baseline을 줄여라 — 한 방향만 잠그면 표가 썩고 숫자가 거짓이 된다."""
    observed, _calls, _unknown, _failures = scanned
    _added, removed = audit.baseline_diff(observed)
    assert (
        not removed
    ), "baseline에 있으나 더는 데이터 접근이 없는 파일 — BASELINE에서 지워 ratchet하라:\n" + "\n".join(
        f"  [{layer}] {f}" for layer, files in sorted(removed.items()) for f in files
    )


# ── 축 3: 회피 차단 ─────────────────────────────────────────────────────────


def test_no_unknown_session_receiver_names(scanned: Any) -> None:
    """`session` → `sesh` 개명으로 수신자 목록을 빠져나가는 회피를 막는다."""
    _observed, _calls, unknown, _failures = scanned
    assert not unknown, (
        "세션 타입으로 주석됐으나 수신자 이름 목록 밖인 이름 — 스캐너가 이 호출을 놓친다:\n"
        + "\n".join(f"  {path}: {name}" for path, name in unknown)
        + "\n\n해소: 이름을 `session`/`conn` 등으로 맞추거나, 정당한 새 관용어라면 "
        "data_access_layer_audit.py의 SESSION_RECEIVER_NAMES에 추가하고 BASELINE을 다시 재라."
    )


# ── 깨끗한 계층: 호출 축 0 + import 축 계약 정합 ────────────────────────────


def test_clean_layers_have_zero_data_access(audit: Any, scanned: Any) -> None:
    """`CLEAN_LAYERS`는 baseline이 아니라 금지다 — 호출 축에서도 0이어야 한다."""
    observed, _calls, _unknown, _failures = scanned
    dirty = {
        layer: sorted(observed.get(layer, set()))
        for layer in audit.CLEAN_LAYERS
        if observed.get(layer)
    }
    assert not dirty, f"깨끗한 계층에 데이터 접근이 생겼다(유예 없음): {dirty}"


def test_importlinter_contract_matches_clean_layers(audit: Any) -> None:
    """pyproject 계약과 `CLEAN_LAYERS` 정본의 **정확한 일치** — 이중 진실 원천 금지."""
    contract = _data_access_contract()
    declared = sorted(contract.get("source_modules", []))
    expected = sorted(f"whymath_backend.{layer}" for layer in audit.CLEAN_LAYERS)
    assert declared == expected, (
        "import-linter 계약의 source_modules와 CLEAN_LAYERS가 어긋난다 — "
        f"계약={declared} 정본={expected}. 한쪽만 고치면 안 된다."
    )


def test_importlinter_contract_forbids_both_axes() -> None:
    """`sqlalchemy`(직접)와 `whymath_backend.db`(경유) 둘 다 막아야 한다.

    하나만 막으면 나머지로 우회한다 — `from whymath_backend.db.session import get_session`은
    sqlalchemy를 import하지 않고도 세션을 얻는다.
    """
    contract = _data_access_contract()
    forbidden = set(contract.get("forbidden_modules", []))
    assert {
        "sqlalchemy",
        "whymath_backend.db",
    } <= forbidden, f"forbidden_modules가 두 축을 다 막지 않는다: {sorted(forbidden)}"
    assert contract.get("type") == "forbidden"


def test_external_packages_are_in_the_import_graph() -> None:
    """`include_external_packages`가 없으면 `sqlalchemy` 금지는 **설정 오류로 죽는다**.

    import-linter는 이 설정 없이 외부 forbidden 모듈을 만나면 계약을 조용히 넘기는 것이
    아니라 전체 실행을 실패시킨다(실측 2026-09-16). 그래도 여기서 동결하는 이유는,
    누군가 그 실패를 "계약을 지우면 초록이 된다"로 해결할 때 이 테스트가 남기 때문이다.
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    top = data.get("tool", {}).get("importlinter", {})
    assert (
        top.get("include_external_packages") is True
    ), "include_external_packages=true가 없다 — 외부 패키지(sqlalchemy) forbidden 계약이 성립하지 않는다"


# ── 축 4: 배선 실재 ─────────────────────────────────────────────────────────


def test_ci_actually_runs_lint_imports() -> None:
    """import 축 집행이 CI에서 실제로 돌아가는지 — 'pyproject에 존재함'과 다르다."""
    ci = _CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^\s*run:\s*lint-imports\s*$", ci
    ), "ci.yml에 `run: lint-imports` 스텝이 없다 — import 축 계약이 돌지 않는다"


def test_ci_actually_runs_infra_tests() -> None:
    """호출 축 집행(이 파일 자신)이 CI에서 실제로 돌아가는지."""
    ci = _CI_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^\s*run:\s*python3 -m pytest tests/infra\b", ci
    ), "ci.yml에 tests/infra 실행 스텝이 없다 — 이 가드 자신이 돌지 않는다"


# ── 만료·출처 ───────────────────────────────────────────────────────────────


def test_baseline_review_point_not_expired(audit: Any) -> None:
    """만료 없는 유예 금지 — 처분 (b) 자체의 재확인 기한.

    기계적 ratchet은 "118이 여전히 118"인 상태를 영원히 green으로 둔다. 이 날짜가 지나면
    사람이 ①처분 승격 ②기한 이동(그 커밋이 재확인 증적) ③baseline 축소 중 하나를 해야 한다.
    """
    review_by = datetime.date.fromisoformat(audit.BASELINE_REVIEW_BY)
    today = datetime.date.today()
    assert today <= review_by, (
        f"데이터 접근 baseline 재확인 기한({review_by})이 지났다(오늘 {today}). "
        "docs/architecture/data_access_layer_disposition.md §재확인을 읽고 "
        "처분을 갱신하거나 BASELINE_REVIEW_BY를 옮겨라 — 유예는 자동 연장되지 않는다."
    )


def test_disposition_doc_records_source_and_owner() -> None:
    """acceptance ⑤ — 이 갭의 출처와 소유자가 산출 문서에 적혀 있는지."""
    assert _DISPOSITION_DOC.is_file(), f"처분 문서 없음: {_DISPOSITION_DOC}"
    text = _DISPOSITION_DOC.read_text(encoding="utf-8")
    for token in (
        "ARCH-48",
        "eos_source_docs_gap_review_2026-08-31.md",
        "판정 기준: main ",
    ):
        assert token in text, f"처분 문서에 '{token}' 이 없다 — 출처·소유·판정 시점 미기록"
