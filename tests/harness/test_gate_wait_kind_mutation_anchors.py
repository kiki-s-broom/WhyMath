"""HARN-184 — 게이트 대기 분류 뮤테이션 하네스의 주입 대상이 **썩지 않았는지** 동결한다.

`scripts/harness/verify_gate_wait_kind_discrimination.py`는 무거워서(주입마다 테스트 파일 전체
재실행) CI에서 돌리지 않는다. 대신 그 하네스가 의존하는 **치환 대상 문자열**이 하네스 코드에
여전히 정확히 1건씩 있는지를 여기서 매 CI마다 확인한다 — HARN-174·HARN-177의 앵커 동결 테스트와
같은 이유·같은 형태다(주입 자체의 실재 · CLAUDE.md 2026-09-06).
"""

from __future__ import annotations

import pytest
import verify_gate_graph_discrimination as graph_harness
import verify_gate_wait_kind_discrimination as harness


def test_mutation_names_are_unique():
    names = [m.name for m in harness.MUTATIONS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mutation", harness.MUTATIONS, ids=lambda m: m.name)
def test_anchor_exists_exactly_once_and_mutation_differs(mutation):
    # check_anchor가 ①정확히 1건 ②치환 결과 ≠ 원본을 단언한다 — 실패 시 AssertionError
    original = graph_harness.check_anchor(mutation)
    assert original.replace(mutation.original, mutation.replacement) != original


def test_every_surface_of_the_classification_is_covered():
    """절이 사는 파일 전부(판정·그래프·화면·보드·정지 사유·브리핑·등재 검사)에 1건 이상의 주입이 있다."""
    covered = {m.path.name for m in harness.MUTATIONS}
    assert covered == {
        "store.py",
        "work_graph.py",
        "work_graph_page.html",
        "board.py",
        "selector.py",
        "report.py",
        "models.py",
    }


def test_harness_targets_the_wait_kind_test_file():
    assert harness.TEST_FILE == "tests/harness/test_gate_wait_kind.py"
    assert (graph_harness.REPO / harness.TEST_FILE).is_file()
