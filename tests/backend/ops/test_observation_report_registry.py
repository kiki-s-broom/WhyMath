"""[OPS-19] 관측 리포트 레지스트리 — 21번째 리포트가 조용히 미배선으로 태어나지 못하게 막는다.

러너를 만든 것만으로는 부족하다. 2026-10-08 실측에서 `*_report.py`는 20개였고 그중 17개가 러너
0건이었다 — 리포트를 만들 때 "누가 이것을 돌리는가"를 묻는 지점이 없었기 때문이다. 이 테스트가
그 지점이다: 새 `*_report.py`는 **러너 목록 · 이미 다른 경로로 배선됨 · 입력 의존** 셋 중 한 곳에
반드시 귀속해야 하고, 어디에도 없으면 이 테스트가 실패한다.

검증 계약 (각 항목은 결함을 주입해 RED가 되는 것만)
---------------------------------------------------
① 전수 귀속 — 소스 트리의 모든 `*_report.py`가 정확히 한 곳에 귀속된다(중복·누락 모두 실패).
② 귀속 목록에 죽은 항목이 없다 — 파일이 사라졌는데 목록에 남은 이름은 실패한다.
③ `ELSEWHERE` 주장은 근거 파일을 열어 확인한다 — "다른 곳에서 돈다"는 말만으로는 귀속이 아니다.
④ 스캔 0건은 실패다 — 소스 경로가 틀려 파일을 하나도 못 찾으면 위반 0으로 통과하지 않는다.
⑤ 감사기 면제 문구와 러너 목록이 양방향으로 일치한다 — "러너가 돌린다"는 면제 문구는 실제로
   러너 목록(ci·db 부류)에 있는 모듈에만 붙고, 러너가 도는 모듈에 "사람이 돌린다"가 남지 않는다.
⑥ 읽기 전용 — 러너가 운영 DB에 주기 실행하는 리포트에 쓰기 구문이 없다. 있으면 주간 배치가
   운영 데이터를 바꾸게 된다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from whymath_backend.ops import observation_report_runner as runner
from whymath_backend.ops.declared_unwired_audit import (
    _MANIFEST,
    _OBSERVED_BY_RUNNER,
    _OFFLINE_REPORT,
    AXIS_CLI,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE = _REPO_ROOT / "src" / "backend" / "whymath_backend"


def _discover(package_root: Path) -> set[str]:
    """`*_report.py` 전수를 접두 없는 dotted name(`harness.xxx_report`)으로 낸다."""
    found = {
        ".".join(path.relative_to(package_root).with_suffix("").parts)
        for path in package_root.rglob("*_report.py")
    }
    if not found:
        raise AssertionError(f"{package_root}에서 *_report.py를 하나도 못 찾았다 — 경로가 틀렸다")
    return found


def _accounting_violations(
    discovered: Iterable[str],
    runner_modules: Iterable[str],
    elsewhere: Iterable[str],
    input_dependent: Iterable[str],
) -> list[str]:
    discovered_set = set(discovered)
    groups = {
        "러너 목록": list(runner_modules),
        "ELSEWHERE": list(elsewhere),
        "INPUT_DEPENDENT": list(input_dependent),
    }
    problems: list[str] = []
    seen: dict[str, str] = {}
    for label, names in groups.items():
        for name in names:
            if name in seen:
                problems.append(f"중복 귀속: {name} ({seen[name]} · {label})")
            seen[name] = label
            if name not in discovered_set:
                problems.append(f"죽은 항목: {name} ({label}) — 해당 파일이 없다")
    for name in sorted(discovered_set - set(seen)):
        problems.append(f"미귀속: {name} — 러너 목록·ELSEWHERE·INPUT_DEPENDENT 어디에도 없다")
    return problems


def test_every_report_cli_is_accounted_for_exactly_once() -> None:
    """① ② ④ 실제 소스 트리 전수."""
    discovered = _discover(_PACKAGE)
    problems = _accounting_violations(
        discovered,
        [spec.module for spec in runner.REPORTS],
        runner.ELSEWHERE,
        runner.INPUT_DEPENDENT,
    )
    assert not problems, (
        "관측 리포트 귀속 위반 — 새 리포트는 누가 돌리는지 선언해야 한다:\n"
        + "\n".join(f"  · {p}" for p in problems)
        + "\n\n해결: ops/observation_report_runner.py의 REPORTS(자동 실행) · ELSEWHERE(다른 "
        "경로로 배선) · INPUT_DEPENDENT(입력 파일 필수) 중 하나에 귀속하라."
    )


def test_registry_scan_is_not_vacuous() -> None:
    """④ 전수 가드가 공허하게 통과하지 않는다 — 실제로 리포트를 충분히 찾고 있다."""
    assert len(_discover(_PACKAGE)) >= 20


def test_discover_fails_loudly_on_empty_tree(tmp_path: Path) -> None:
    """④ 파일을 못 찾으면 위반 0이 아니라 예외다."""
    with pytest.raises(AssertionError, match="하나도 못 찾았다"):
        _discover(tmp_path)


def test_accounting_detects_each_defect_kind() -> None:
    """① ② 판정 함수의 변별력 — 대조군은 통과, 결함 3종은 각각 검출."""
    base = {"a.x_report", "b.y_report", "c.z_report"}
    assert _accounting_violations(base, ["a.x_report"], ["b.y_report"], ["c.z_report"]) == []
    # 미귀속(21번째 리포트)
    missing = _accounting_violations(
        base | {"d.new_report"}, ["a.x_report"], ["b.y_report"], ["c.z_report"]
    )
    assert any("미귀속: d.new_report" in p for p in missing)
    # 죽은 항목
    dead = _accounting_violations(
        base, ["a.x_report", "gone_report"], ["b.y_report"], ["c.z_report"]
    )
    assert any("죽은 항목: gone_report" in p for p in dead)
    # 중복 귀속
    dup = _accounting_violations(base, ["a.x_report", "b.y_report"], ["b.y_report"], ["c.z_report"])
    assert any("중복 귀속: b.y_report" in p for p in dup)


@pytest.mark.parametrize("module", sorted(runner.ELSEWHERE))
def test_elsewhere_claims_are_backed_by_the_cited_file(module: str) -> None:
    """③ '다른 곳에서 돈다'는 주장은 근거 파일에 그 흔적이 실제로 있을 때만 유효하다."""
    rel, needle = runner.ELSEWHERE[module]
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{module}: 근거 파일 {rel}이 없다"
    assert needle in path.read_text(encoding="utf-8"), f"{module}: {rel}에 {needle!r}이 없다"


def test_runner_classes_partition_the_registry() -> None:
    """한 리포트가 두 부류에 들어가거나, 알 수 없는 부류에 들어가지 않는다."""
    modules = [spec.module for spec in runner.REPORTS]
    assert len(modules) == len(set(modules))
    assert {spec.klass for spec in runner.REPORTS} <= set(runner.CLASSES)


def _waiver_reasons() -> Mapping[str, str]:
    return _MANIFEST[AXIS_CLI]


def test_observed_by_runner_waivers_match_the_runner_list_both_ways() -> None:
    """⑤ 면제 문구 '러너가 돌린다' ↔ 러너 목록(ci·db 부류)이 양방향으로 같다."""
    automated = {s.module for s in runner.REPORTS if s.klass in (runner.CLASS_CI, runner.CLASS_DB)}
    claimed = {k for k, v in _waiver_reasons().items() if v == _OBSERVED_BY_RUNNER}
    assert (
        claimed <= automated
    ), f"러너가 안 도는데 '러너가 돈다'로 면제된 모듈: {claimed - automated}"
    stale = {s.module for s in runner.REPORTS if _waiver_reasons().get(s.module) == _OFFLINE_REPORT}
    assert not stale, f"러너가 도는데 '사람이 돌린다'가 남은 모듈: {stale}"


def test_checkout_db_reports_are_not_claimed_as_automated() -> None:
    """checkout_db 부류는 자동 경로가 없다 — '러너가 돈다'로 면제하면 거짓 문장이 된다."""
    manual = {s.module for s in runner.REPORTS if s.klass == runner.CLASS_CHECKOUT_DB}
    claimed = {k for k, v in _waiver_reasons().items() if v == _OBSERVED_BY_RUNNER}
    assert not (manual & claimed)


# ── ⑥ 읽기 전용 동결 ─────────────────────────────────────────────────────────
_WRITE_PATTERNS = (
    r"\.commit\(",
    r"session\.add\(",
    r"\.add_all\(",
    r"\.flush\(",
    r"INSERT\s+INTO",
    r"DELETE\s+FROM",
    r"UPDATE\s+[a-z_\"]+\s+SET",
    r"\bDROP\s+TABLE",
    r"\bTRUNCATE\b",
)


def _write_hits(source: str) -> list[str]:
    return [p for p in _WRITE_PATTERNS if re.search(p, source, flags=re.IGNORECASE)]


@pytest.mark.parametrize("spec", runner.REPORTS, ids=lambda s: s.module)
def test_scheduled_reports_contain_no_write_statements(spec: runner.ReportSpec) -> None:
    """⑥ 주기 실행되는 리포트는 읽기 전용이다."""
    path = _PACKAGE / Path(*spec.module.split(".")).with_suffix(".py")
    assert path.is_file(), path
    assert _write_hits(path.read_text(encoding="utf-8")) == []


def test_write_detector_actually_detects() -> None:
    """⑥ 탐지기 변별력 — 쓰기 구문을 주입하면 잡고, 흔한 오탐 형태(Counter.update)는 안 잡는다."""
    assert _write_hits("await session.commit()")
    assert _write_hits("session.add(row)")
    assert _write_hits('text("INSERT INTO t VALUES (1)")')
    assert _write_hits("update workers SET x = 1")
    assert _write_hits("counter.update(codes)\nsys.path.insert(0, d)") == []
