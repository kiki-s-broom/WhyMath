"""OPS-83 ⑥ 변별력 주입 — 샤드 2/3에만 배정되는 고의 실패. 이 초안 PR은 머지하지 않는다."""


def test_ops83_injected() -> None:
    # 고의 실패: 집계 잡(backend — lint·type·test)이 이 샤드 실패를 red로 판정하는지 확인
    assert False
