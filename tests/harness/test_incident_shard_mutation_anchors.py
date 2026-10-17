"""HARN-130 — 사고 대장 샤딩 뮤테이션 하네스의 주입 대상이 **썩지 않았는지** 동결한다.

`scripts/harness/verify_incident_shard_discrimination.py`는 무거워서(주입마다 테스트 파일 전체
재실행 · 두 브랜치 git 머지 포함) CI에서 돌리지 않는다. 대신 그 하네스가 의존하는 **치환 대상
문자열**이 코드에 여전히 정확히 1건씩 있는지를 여기서 매 CI마다 확인한다 — HARN-174·177·184의
앵커 동결 테스트와 같은 이유·같은 형태다(주입 자체의 실재 · CLAUDE.md 2026-09-06).
"""

from __future__ import annotations

import pytest
import verify_gate_graph_discrimination as graph_harness
import verify_incident_shard_discrimination as harness


def test_mutation_names_are_unique():
    names = [m.name for m in harness.MUTATIONS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mutation", harness.MUTATIONS, ids=lambda m: m.name)
def test_anchor_exists_exactly_once_and_mutation_differs(mutation):
    # check_anchor가 ①정확히 1건 ②치환 결과 ≠ 원본을 단언한다 — 실패 시 AssertionError
    original = graph_harness.check_anchor(mutation)
    assert original.replace(mutation.original, mutation.replacement) != original


def test_every_surface_of_the_change_is_covered():
    """절이 사는 파일 전부(대장 I/O·등재 CLI·union 배선·gitignore·CI 스텝)에 1건 이상의 주입이 있다."""
    covered = {m.path.name for m in harness.MUTATIONS}
    assert covered == {"incidents.py", "backlog.py", ".gitattributes", ".gitignore", "ci.yml"}


def test_each_group_targets_its_own_test_file():
    assert harness.LEDGER_TEST_FILE == "tests/harness/test_incident_ledger_sharding.py"
    assert harness.INDEX_TEST_FILE == "tests/harness/test_jit_rules.py"
    for rel in (harness.LEDGER_TEST_FILE, harness.INDEX_TEST_FILE):
        assert (graph_harness.REPO / rel).is_file()
    assert set(harness.MUTATIONS) == {*harness.LEDGER_MUTATIONS, *harness.INDEX_MUTATIONS}
