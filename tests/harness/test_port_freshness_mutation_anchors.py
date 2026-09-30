"""HARN-205 — 뮤테이션 하네스의 주입 대상이 **썩지 않았는지** 동결한다.

`scripts/harness/verify_port_freshness_discrimination.py`는 주입마다 테스트 파일 전체를 다시 돌려
무거우므로 CI에서 돌리지 않는다. 대신 그 하네스가 의존하는 **치환 대상 문자열**이 도구·집행 문서에
여전히 정확히 1건씩 있는지를 매 CI마다 확인한다. 리팩터링으로 대상이 사라지면 하네스는 "치환 대상
0건"으로 실패하는데, 아무도 하네스를 돌리지 않으면 그 실패는 영원히 보이지 않는다(주입 자체의 실재 ·
CLAUDE.md 2026-09-06 · HARN-174 `test_gate_graph_mutation_anchors.py`와 같은 방식).

이 파일은 `test_port_freshness.py`와 **분리돼 있어야 한다** — 같은 파일에 두면 뮤테이션 실행 중 이
앵커 검사가 "치환 대상 0건"으로 먼저 RED를 내, 동작 테스트가 뮤테이션을 잡았는지와 구분되지 않는다
(RED의 출처 · HARN-120 ⑥).
"""

from __future__ import annotations

import pytest
import verify_port_freshness_discrimination as harness
from verify_gate_graph_discrimination import check_anchor

#: acceptance ⑤가 이름으로 요구하는 4종 — 목록에서 빠지면 그 절은 변별력 검증 없이 '검증됨'이 된다.
_REQUIRED = {
    "P01-intersection-disabled",
    "P02-zero-guard-removed",
    "P03-basename-match-removed",
    "P04-default-target-is-base",
}


def test_mutation_names_are_unique():
    names = [m.name for m in harness.MUTATIONS]
    assert len(names) == len(set(names))


def test_required_mutations_present():
    assert _REQUIRED <= {m.name for m in harness.MUTATIONS}


def test_runner_targets_the_behaviour_tests():
    """러너가 도는 파일은 동작 테스트다 — 이 앵커 파일을 돌리면 RED의 출처가 흐려진다."""
    assert harness.TEST_FILE == "tests/harness/test_port_freshness.py"


@pytest.mark.parametrize("mutation", harness.MUTATIONS, ids=lambda m: m.name)
def test_anchor_exists_exactly_once_and_mutation_differs(mutation):
    # check_anchor가 ①정확히 1건 ②치환 결과 ≠ 원본을 단언한다 — 실패 시 AssertionError
    original = check_anchor(mutation)
    assert original.replace(mutation.original, mutation.replacement) != original
