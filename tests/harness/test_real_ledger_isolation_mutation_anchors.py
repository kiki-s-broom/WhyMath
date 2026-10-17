"""HARN-170 — 격리·누출 판별 뮤테이션 하네스의 주입 대상이 **썩지 않았는지** 동결한다.

`scripts/harness/verify_real_ledger_isolation_discrimination.py`는 무거워서(주입마다 테스트 파일
전체 재실행) CI에서 돌리지 않는다. 대신 그 하네스가 의존하는 치환 대상 문자열이 여전히 정확히
1건씩 있는지를 여기서 매 CI마다 확인한다 — HARN-174·177·184·130의 앵커 동결과 같은 형태다
(주입 자체의 실재 · CLAUDE.md 2026-09-06).
"""

from __future__ import annotations

import pytest
import verify_gate_graph_discrimination as graph_harness
import verify_real_ledger_isolation_discrimination as harness


def test_mutation_names_are_unique():
    names = [m.name for m in harness.MUTATIONS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mutation", harness.MUTATIONS, ids=lambda m: m.name)
def test_anchor_exists_exactly_once_and_mutation_differs(mutation):
    original = graph_harness.check_anchor(mutation)
    assert original.replace(mutation.original, mutation.replacement) != original


def test_every_surface_is_covered():
    """절이 사는 파일 전부(격리 픽스처·격리 판정·누출 판별·policy report)에 1건 이상의 주입이 있다."""
    covered = {m.path.name for m in harness.MUTATIONS}
    assert covered == {"conftest.py", "_ledger_guard.py", "event_leaks.py", "backlog.py"}


def test_each_group_targets_its_own_test_file():
    assert harness.ISOLATION_TEST_FILE == "tests/harness/test_real_ledger_isolation.py"
    assert harness.LEAK_TEST_FILE == "tests/harness/test_event_leaks.py"
    for rel in (harness.ISOLATION_TEST_FILE, harness.LEAK_TEST_FILE):
        assert (graph_harness.REPO / rel).is_file()
    assert set(harness.MUTATIONS) == {*harness.ISOLATION_MUTATIONS, *harness.LEAK_MUTATIONS}
