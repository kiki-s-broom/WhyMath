"""`anthropic_configured` 소비자 전수 동결 — 정책 차단 원인을 잃는 표면이 새로 생기지 않게 (ARCH-68).

왜 이 테스트가 있는가
--------------------
ARCH-66(2026-09-24)은 `anthropic_api_enabled` 스위치를 신설해, 키가 남아 있어도 스위치가 꺼져
있으면 `anthropic_configured=False`가 되게 했다. 그런데 `anthropic_configured`를 읽어 사람에게
원인을 말하던 운영 표면은 그 False를 여전히 "키 없음"으로 번역했다 — 2026-09-28 실측으로
`live_preflight`가 "anthropic 미설정(키 없음)"을, `provider_accuracy_battle`이 "키 미설정"을
출력했고, `/status`는 원인 칸을 비웠다. 사용 중단 기간의 **기본 상황**(키는 있고 스위치만 꺼짐)
에서 틀린 원인을 말한 것이다.

각 표면의 동작은 그 모듈의 테스트가 검사한다. 이 파일은 그 목록이 **닫혀 있는지**를 검사한다:
`anthropic_configured`를 새로 읽는 코드가 생기면, 그것이 원인을 말하는 표면인지 분기 조건일
뿐인지 분류하기 전에는 통과하지 못한다. 표면 목록을 사람이 기억하는 대신 AST가 센다.

판정 방식
---------
문자열 검색이 아니라 AST의 속성 접근(`x.anthropic_configured`)을 센다 — docstring·주석 속
언급은 소비가 아니다. 스캔 대상이 0건이면 실패한다(대상을 못 찾은 전수 가드는 공허하게 통과한다).
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import whymath_backend

_PKG_ROOT = Path(whymath_backend.__file__).resolve().parent

_REPORTS = "reports"
"""원인을 사람에게 말하는 표면 — 같은 파일에서 `anthropic_policy_block_reason`도 읽어야 한다."""

_BRANCH_ONLY = "branch_only"
"""분기 조건으로만 쓰고 원인을 말하지 않는 소비자 — 등재 시 사유를 함께 적는다."""

# 패키지 루트 기준 상대 경로 → (분류, 사유). 2026-09-28 착수 시점 전수 4곳.
_CONSUMERS: dict[str, tuple[str, str]] = {
    "l3/providers/anthropic.py": (
        _REPORTS,
        "check_status가 /status의 cloud_error를, _get_client가 생성 오류 문구를 낸다",
    ),
    "ops/live_preflight.py": (
        _REPORTS,
        "판정 줄·스모크 skip 사유·pipeline 폴백 메모·JSON 리포트",
    ),
    "ops/cost_probe.py": (
        _REPORTS,
        "클라우드 archetype 자동 제외 사유(cloud_excluded_reason)",
    ),
    "harness/provider_accuracy_battle.py": (
        _REPORTS,
        "arm_readiness의 미비 사유(detail) — --check-only가 사람에게 출력한다",
    ),
}


def _attribute_reads(tree: ast.AST, name: str) -> int:
    """`<식>.<name>` 형태의 속성 접근 수 — 정의(def name)·문자열 언급은 세지 않는다."""
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == name
    )


@functools.lru_cache(maxsize=1)
def _scan() -> tuple[int, dict[str, ast.AST]]:
    """패키지 전 .py를 파싱해 (스캔 파일 수, anthropic_configured를 읽는 파일 → AST)를 낸다.

    한 프로세스 안에서 1회만 파싱한다(세 테스트가 같은 결과를 읽는다 — 소스는 실행 중 불변).
    """
    scanned = 0
    consumers: dict[str, ast.AST] = {}
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if _attribute_reads(tree, "anthropic_configured"):
            consumers[path.relative_to(_PKG_ROOT).as_posix()] = tree
    return scanned, consumers


def test_scan_is_not_vacuous() -> None:
    """스캔이 실제로 패키지를 봤는가 — 0건 스캔은 통과가 아니라 경로 오류다."""
    scanned, consumers = _scan()
    assert scanned > 100, f"스캔 파일 {scanned}건 — 패키지 루트({_PKG_ROOT}) 해석이 틀렸다"
    assert consumers, "anthropic_configured 소비자가 0건 — 스캔 방식이 깨졌다(속성명 변경?)"


def test_consumer_set_is_frozen() -> None:
    """소비자 집합 = 등재 집합. 새 소비자는 분류 없이 추가되지 않고, 사라진 소비자는 목록에서 뺀다."""
    _, consumers = _scan()
    found = set(consumers)
    pinned = set(_CONSUMERS)
    new = sorted(found - pinned)
    gone = sorted(pinned - found)
    assert not new, (
        f"anthropic_configured의 새 소비자 {new} — 원인을 사람에게 말하는 표면이면 "
        "anthropic_policy_block_reason을 함께 읽게 하고 _CONSUMERS에 'reports'로, 분기 조건으로만 "
        "쓰면 'branch_only'와 사유를 등재하라. 등재 없이 False를 '키 없음'으로 번역하면 ARCH-66 "
        "사용 중단 기간에 틀린 원인을 말한다(ARCH-68)."
    )
    stale = f"등재됐으나 더 이상 anthropic_configured를 읽지 않는 파일 {gone} — 목록에서 뺀다."
    assert not gone, stale


def test_reporting_consumers_read_policy_reason() -> None:
    """'reports' 분류 소비자는 같은 파일에서 정책 차단 사유(단일 좌석)를 읽는다."""
    _, consumers = _scan()
    missing = [
        rel
        for rel, (kind, _why) in _CONSUMERS.items()
        if kind == _REPORTS
        and rel in consumers
        and _attribute_reads(consumers[rel], "anthropic_policy_block_reason") == 0
    ]
    assert not missing, (
        f"{missing}는 원인을 말하는 표면인데 anthropic_policy_block_reason을 읽지 않는다 — "
        "키가 있는데 '키 없음'이라고 말하게 된다(ARCH-68)."
    )


def test_every_entry_has_known_kind_and_reason() -> None:
    """등재 항목은 분류가 둘 중 하나이고 사유가 비어 있지 않다(사유 없는 면제 금지)."""
    for rel, (kind, why) in _CONSUMERS.items():
        assert kind in (_REPORTS, _BRANCH_ONLY), f"{rel}: 알 수 없는 분류 {kind!r}"
        assert why.strip(), f"{rel}: 분류 사유가 비어 있다"
