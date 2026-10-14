"""PED-26 — `docs/architecture/`의 문서번호 접두는 한 문서가 하나씩 갖는다.

`04e` 접두를 오개념 교정 설계(`04e_misconception_remediation_design.md`)와 교수전략 카탈로그가
2026-08-15부터 2026-10-08까지 나눠 썼다 — 두 문서 모두 코드·테스트가 "04e §N"으로 약칭해 인용해서
**어느 문서의 몇 절인지 문서번호만으로는 결정할 수 없는** 상태였다(약칭 118곳). 중복은 파일명이
서로 달라 어떤 검사에도 걸리지 않았다 — 이 테스트가 그 사각을 닫는다.

판정 규칙: 파일명이 `<숫자+소문자1자>_`로 시작하는 문서(`04e_…`, `03c_…`, `44_…`)의 접두는 유일해야
한다. 예외는 `_KNOWN_DUPLICATES`에 **사유·소유 태스크·만료일**과 함께 등재된 것뿐이다
(CLAUDE.md "만료 없는 유예·제외 금지"):
- 만료일이 지나면 예외 자체가 실패한다 — 영구 면제가 되지 못한다.
- 등재된 예외가 더는 중복이 아니면(해소됐으면) 예외가 낡았다고 실패한다 — 면제표가 실재해야 한다.
- 스캔 0건은 실패다 — 정규식이 낡아 아무것도 안 보는 위장 통과 방지.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "docs" / "architecture"

_PREFIX = re.compile(r"^(\d+[a-z]?)_")

# 접두 → (소유 태스크, 만료일, 사유). 해소하면 이 항목을 지운다 — 지우지 않으면 아래 테스트가 실패한다.
_KNOWN_DUPLICATES: dict[str, tuple[str, date, str]] = {
    "03c": (
        "ARCH-72-architecture-doc-prefix-03c-dedup",
        date(2026, 12, 31),
        "03c_cloud_tier_transition_v2.md ↔ 03c_content_strategy_cache.md — PED-26 범위 밖(클라우드 티어 "
        "문서는 ARCH-66 일시중단 부기로 활발히 개정 중이라 병렬 충돌을 피해 별건으로 분리)",
    ),
}


def _by_prefix() -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in sorted(ARCH.glob("*.md")):
        m = _PREFIX.match(path.name)
        if m:
            groups[m.group(1)].append(path.name)
    return groups


def test_scan_finds_numbered_docs() -> None:
    """스캔 0건은 통과가 아니라 실패 — 경로·정규식이 낡으면 아무것도 안 보는데 초록이 된다."""
    groups = _by_prefix()
    assert len(groups) >= 20, f"번호 접두 문서를 {len(groups)}종밖에 못 찾음 — 경로/정규식 점검"


def test_no_unlisted_duplicate_prefix() -> None:
    dups = {p: names for p, names in _by_prefix().items() if len(names) > 1}
    unlisted = {p: names for p, names in dups.items() if p not in _KNOWN_DUPLICATES}
    assert not unlisted, (
        "문서번호 접두 중복(등재되지 않음) — 한 접두는 한 문서만 갖는다. "
        "코드·테스트가 '04e §4'처럼 접두로 약칭 인용하므로 중복은 인용 대상을 결정 불가로 만든다: "
        f"{unlisted}"
    )


def test_known_duplicates_are_real_and_not_expired() -> None:
    groups = _by_prefix()
    today = date.today()
    for prefix, (task, expires, reason) in _KNOWN_DUPLICATES.items():
        assert (
            len(groups.get(prefix, [])) > 1
        ), f"예외 {prefix}가 낡았다(더는 중복이 아님) — _KNOWN_DUPLICATES에서 지운다: {reason}"
        assert (
            today <= expires
        ), f"예외 {prefix}가 만료됐다({expires}) — 해소({task})하거나 재확인 사유와 함께 연장한다"
        assert task and reason, f"예외 {prefix}에 소유 태스크·사유가 없다"


def test_strategy_catalog_is_not_squatting_on_04e() -> None:
    """회귀 동결: 04e는 오개념 교정 설계의 번호이고 교수전략 카탈로그는 04g다(PED-26)."""
    assert _by_prefix().get("04e") == ["04e_misconception_remediation_design.md"]
    assert (ARCH / "04g_pedagogy_strategy_catalog.md").is_file()
