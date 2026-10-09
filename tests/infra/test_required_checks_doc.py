"""`.github/branch-protection-setup.md`의 required check 목록 ↔ `ci.yml` 잡 이름 동결.

왜 이 테스트가 있는가 (2026-07-26 사고)
--------------------------------------
브랜치 보호 문서가 required status check를 **3종만** 나열하고 `backend — lint·type·test`가
빠져 있었다. CI 잡이 3개에서 14개로 늘어나는 동안 목록이 따라가지 못한 것이다. 그 결과 전체
테스트·mypy·커버리지를 보는 가장 중요한 잡이 머지를 막지 못했고, PR #606이 `1 failed` 상태로
머지돼 main이 red가 됐다.

**드리프트가 조용히 새는 경로**: 문서의 체크 이름은 Kiki가 GitHub UI 검색창에 그대로 입력하는
문자열이다. 이름에 오타가 있거나 잡이 개명되면 검색 결과가 비고, 그 체크는 **설정되지 않은 채
남는다** — UI는 "그런 체크 없음"을 조용히 알릴 뿐 실패를 만들지 않는다. 사람이 목록을 눈으로
대조하는 데 의존하면 언젠가 또 새므로, 기계가 대조한다.

검증 계약 (각 항목은 변별력이 확인된 것만)
----------------------------------------
① 문서가 안내하는 모든 체크 이름이 `ci.yml`에 **실재**한다 (오타·개명 드리프트 차단)
② `ci.yml`의 잡 중 문서에 없는 것이 있으면 실패하되, **의도적 제외는 허용 목록으로 명시**한다
   (잡 신설 시 "required로 걸 것인가"를 강제로 판단하게 만든다 — 침묵 누락 금지)
③ 파서 자체가 위장하지 않는다 — 마커 블록이 없거나 목록이 비면 "위반 0 통과"가 아니라 **실패**
   (OPS-04 `test_slo_contract` 선례: 파서 무력화가 곧 통과가 되면 안 된다)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATH = _REPO_ROOT / ".github" / "branch-protection-setup.md"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_BEGIN = "<!-- REQUIRED_CHECKS_BEGIN"
_END = "<!-- REQUIRED_CHECKS_END -->"

# required에서 의도적으로 제외한 잡 → 그 사유. 새 잡을 여기 넣으려면 사유를 함께 쓴다.
# (제외를 '빈 문자열 사유'로 통과시키지 않는다 — 아래 테스트가 사유 존재를 강제한다.)
_INTENTIONAL_EXCLUSIONS: dict[str, str] = {
    "e2e-nightly — 관통 슬라이스 (실 PG·야간)": (
        "if: github.event_name == 'schedule' — PR에서 항상 skip. 야간 잡을 머지 게이트로 "
        "선언하는 것은 의미가 어긋난다."
    ),
    "backend — 전체 스위트 직렬 (교차 파일 오염 탐지·야간)": (
        "if: github.event_name == 'schedule' — PR에서 항상 skip(위와 같은 사유). 이 잡을 "
        "required로 걸면 PR 머지 게이트에 직렬 26분이 되돌아와 OPS-58 병렬화가 무의미해진다. "
        "배선 실재성은 tests/infra/test_backend_serial_nightly_wiring.py가 동결한다."
    ),
    "constraints-freshness — 제약 파일 연령 센서 (야간)": (
        "if: github.event_name == 'schedule' — PR에서 항상 skip(위와 같은 사유). 연령은 시계에 "
        "따라 결과가 바뀌는 입력이라 머지 게이트(PR·머지 큐)에 넣으면 같은 코드가 날짜에 따라 "
        "초록·빨강이 된다 — 일부러 PR 경로 밖에 둔다(OPS-121). 정적 검사 본체는 required인 "
        "infra-contracts 잡이 돌고, 야간 배선은 tests/infra/test_ci_constraints.py가 동결한다."
    ),
}


def _documented_checks() -> list[str]:
    """문서의 마커 블록에서 백틱으로 감싼 체크 이름을 순서대로 추출.

    마커 부재·블록 공백은 **예외로 실패**시킨다 — 파서가 조용히 빈 목록을 돌려주면 이 테스트
    전체가 "위반 0"으로 통과해버려 검증이 위장이 된다(검증 계약 ③).
    """
    text = _DOC_PATH.read_text(encoding="utf-8")
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1 or end <= start:
        raise AssertionError(
            f"{_DOC_PATH.name}: REQUIRED_CHECKS 마커 블록을 찾지 못했다 "
            f"(begin={start}, end={end}). 목록을 옮겼다면 마커도 함께 옮겨라."
        )
    block = text[start:end]
    names = re.findall(r"^-\s+`([^`]+)`\s*$", block, flags=re.MULTILINE)
    if not names:
        raise AssertionError(f"{_DOC_PATH.name}: 마커 블록 안에 체크 이름이 하나도 없다.")
    return names


def _ci_job_names() -> list[str]:
    """`ci.yml`의 모든 잡 `name:` 값. 이름 없는 잡은 잡 키를 그대로 쓴다(GitHub 동작)."""
    spec = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    jobs = spec.get("jobs") or {}
    return [str(body.get("name") or key) for key, body in jobs.items()]


def test_documented_checks_all_exist_in_ci() -> None:
    """계약 ① — 문서가 안내하는 이름이 전부 ci.yml에 실재해야 한다.

    실패 = UI 검색이 빌 이름을 안내하고 있다는 뜻이며, 그 체크는 미설정으로 남는다.
    """
    documented = _documented_checks()
    actual = set(_ci_job_names())
    missing = [name for name in documented if name not in actual]
    assert not missing, (
        "문서가 존재하지 않는 CI 잡 이름을 안내한다(UI 검색이 비어 미설정으로 샌다): "
        f"{missing}\n실재 잡: {sorted(actual)}"
    )


def test_every_ci_job_is_required_or_explicitly_excluded() -> None:
    """계약 ② — 새 잡을 만들면 required 여부를 *판단하도록* 강제한다.

    문서에도 없고 제외 목록에도 없는 잡은 실패. 침묵 누락(잡은 늘었는데 목록은 그대로)이
    2026-07-26 사고의 구조적 원인이었다.
    """
    documented = set(_documented_checks())
    unaccounted = [
        name
        for name in _ci_job_names()
        if name not in documented and name not in _INTENTIONAL_EXCLUSIONS
    ]
    assert not unaccounted, (
        "required 목록에도 제외 목록에도 없는 CI 잡이 있다 — required로 걸지 여부를 판단해 "
        f"둘 중 하나에 등재하라: {unaccounted}"
    )


def test_backend_test_job_is_required() -> None:
    """계약 ①의 특칭 — 사고의 직접 원인이던 잡이 목록에 있는지 별도 동결.

    일반 계약이 리팩터로 느슨해져도 이 한 줄은 남도록 이름을 박아 둔다.
    """
    assert "backend — lint·type·test" in _documented_checks(), (
        "backend 전체 테스트·mypy·커버리지 잡이 required 목록에서 빠졌다 — "
        "2026-07-26 main red 사고의 직접 원인이다."
    )


def test_exclusions_carry_a_reason() -> None:
    """계약 ② 보강 — 제외는 사유와 함께여야 한다(빈 사유로 조용히 빠져나가지 못하게)."""
    empty = [name for name, reason in _INTENTIONAL_EXCLUSIONS.items() if not reason.strip()]
    assert not empty, f"제외 사유가 비어 있다: {empty}"


def test_parser_fails_loudly_without_markers(tmp_path: Path) -> None:
    """계약 ③ — 마커가 사라지면 '위반 0 통과'가 아니라 예외로 실패해야 한다.

    파서 무력화가 곧 통과가 되면 이 테스트 묶음 전체가 위장이 된다. 실제로 마커 없는 문서를
    만들어 그 경로를 실행한다(문서를 훼손하지 않고 tmp 파일로).
    """
    broken = tmp_path / "broken.md"
    broken.write_text("- `backend — lint·type·test`\n", encoding="utf-8")
    original = globals()["_DOC_PATH"]
    globals()["_DOC_PATH"] = broken
    try:
        with pytest.raises(AssertionError, match="마커 블록을 찾지 못했다"):
            _documented_checks()
    finally:
        globals()["_DOC_PATH"] = original
