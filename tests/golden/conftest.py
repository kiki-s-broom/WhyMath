"""골든 패스 테스트 공통 설정.

테스트 세션이 시작될 때 두 환경변수를 켠다.
- GOLDEN_TEST_MODE=1 : GET /golden/next 응답에 `_test_answer`(정답)를 넣는다. 테스트에서만 켠다.
- GOLDEN_FAKE_LLM=1  : 튜터가 실제 LLM 대신 고정 문장을 돌려준다. 테스트·CI는 실제 LLM을 부르지 않는다.

주의: 이 픽스처는 테스트 *수집이 끝난 뒤* 첫 테스트 직전에 실행된다. 그래서 golden 패키지는
이 두 값을 import 시점이 아니라 요청을 처리하는 시점에 읽어야 한다.
"""

from collections.abc import Iterator

import pytest

# 골든 패스 테스트가 켜는 환경변수(이름 → 값)
_GOLDEN_TEST_ENV = {
    "GOLDEN_TEST_MODE": "1",
    "GOLDEN_FAKE_LLM": "1",
}


@pytest.fixture(scope="session", autouse=True)
def golden_test_env() -> Iterator[None]:
    """세션 시작 시 테스트용 환경변수를 넣고, 세션이 끝나면 원래 값으로 되돌린다."""
    with pytest.MonkeyPatch.context() as mp:
        for name, value in _GOLDEN_TEST_ENV.items():
            mp.setenv(name, value)
        yield
