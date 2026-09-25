"""HARN-174 — 뮤테이션 하네스의 주입 대상이 **썩지 않았는지** 동결한다.

`scripts/harness/verify_gate_graph_discrimination.py`는 무거워서(주입마다 테스트 파일 전체
재실행) CI에서 돌리지 않는다. 대신 그 하네스가 의존하는 **치환 대상 문자열**이 하네스 코드에
여전히 정확히 1건씩 있는지를 여기서 매 CI마다 확인한다. 리팩터링으로 대상이 사라지면 하네스는
"치환 대상 0건"으로 실패하는데, 아무도 하네스를 돌리지 않으면 그 실패는 영원히 보이지 않는다 —
이 테스트가 그것을 즉시 RED로 만든다(주입 자체의 실재 · CLAUDE.md 2026-09-06).
"""

from __future__ import annotations

import pytest
import verify_gate_graph_discrimination as harness


def test_mutation_names_are_unique():
    names = [m.name for m in harness.MUTATIONS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("mutation", harness.MUTATIONS, ids=lambda m: m.name)
def test_anchor_exists_exactly_once_and_mutation_differs(mutation):
    # check_anchor가 ①정확히 1건 ②치환 결과 ≠ 원본을 단언한다 — 실패 시 AssertionError
    original = harness.check_anchor(mutation)
    assert original.replace(mutation.original, mutation.replacement) != original


def test_every_source_file_under_test_is_covered():
    """절이 사는 5개 파일에 각각 1건 이상의 주입이 있다 — 한 파일이 통째로 빠지면 그 파일의
    절은 변별력 검증을 한 번도 받지 않은 채 '검증됨'으로 계상된다."""
    covered = {m.path.name for m in harness.MUTATIONS}
    assert covered == {"models.py", "store.py", "selector.py", "board.py", "backlog.py"}
