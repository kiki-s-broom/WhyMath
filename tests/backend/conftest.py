"""tests/backend/conftest.py — 백엔드 테스트 임포트 경로 + 통합 테스트 게이트.

`whymath_backend`는 `pip install -e ".[dev]"`로 editable 설치되므로 보통은
import 경로 조정이 불필요하다. 다만 editable 설치 없이(예: 로컬에서 venv 미설치)
테스트를 돌릴 때도 동작하도록 소스 경로를 sys.path 앞에 둔다.

data-pipeline(tests/data_pipeline/conftest.py)과 달리 *동명 충돌이 없다*:
테스트 디렉토리는 `tests/backend`, 패키지는 `whymath_backend`로 이름이 다르다.
따라서 모듈 purge 로직은 불필요하고, 경로 보장만 한다.

통합 테스트 게이트 (M1.2-live S1 신규):
`@pytest.mark.integration`은 *라이브 서비스*(실제 Ollama 데몬 등)를 요구하므로
CI(라이브 서비스 없음)에서는 기본 *skip*한다. 실행하려면 환경변수
`WHYMATH_RUN_INTEGRATION`을 truthy(1/true/yes/on)로 설정한다 — Phaiakes9에서
Kiki가 켜고 돌린다. 프로젝트에 통합 게이트 선례가 없어 이 패턴을 여기서 확립한다.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

# 이 conftest 디렉터리(tests/backend)를 sys.path에 명시 삽입 — 형제 모듈 `_db_leak_guard`를
# conftest 로드 시점에 import 가능하게. pytest의 암묵적 디렉터리 삽입은 실행 방식에 따라 갈린다:
# 위치 인자로 경로를 주면 삽입되지만, `-m integration`처럼 testpaths만으로 수집하면 conftest
# 로드 시점에 이 디렉터리가 sys.path에 없어 ModuleNotFoundError가 난다(2026-07-26 CI 통합잡
# 실측). 암묵 동작에 기대지 않고 명시 삽입으로 고정한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# db.session 전역 누수 가드(OPS-07)의 탐지·격리 로직 — 가드 자체의 변별력을 별도 테스트
# (test_db_leak_guard.py)에서 오염 주입으로 실측하려고 모듈로 분리했다.
from _db_leak_guard import (  # noqa: E402  (위 sys.path 삽입 후에 import해야 한다)
    contain_db_session_leak,
    db_session_leak_reason,
    format_leak_failure,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_BACKEND = _PROJECT_ROOT / "src" / "backend"

# editable 설치가 없을 때를 대비한 안전장치: 소스 경로를 가장 앞으로
_src_path_str = str(_SRC_BACKEND)
if _src_path_str in sys.path:
    sys.path.remove(_src_path_str)
sys.path.insert(0, _src_path_str)

_RUN_INTEGRATION_ENV = "WHYMATH_RUN_INTEGRATION"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _integration_enabled() -> bool:
    """환경변수로 통합 테스트가 켜져 있는지 판정."""
    return os.environ.get(_RUN_INTEGRATION_ENV, "").strip().lower() in _TRUTHY


def pytest_collection_modifyitems(config: pytest.Config, items: Iterable[pytest.Item]) -> None:
    """`integration` 마크 테스트를 기본 skip (환경변수로만 활성화).

    CI는 `WHYMATH_RUN_INTEGRATION`을 설정하지 않으므로 통합 테스트가 자동으로
    빠진다 → 라이브 Ollama 없이도 CI green. 환경변수가 켜지면 그대로 수집·실행.
    """
    if _integration_enabled():
        return
    skip_integration = pytest.mark.skip(
        reason=f"통합 테스트는 기본 skip — 실행하려면 {_RUN_INTEGRATION_ENV}=1 설정"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# ──────────────────────────────────────────────────────────────────────
# db.session 전역 누수 가드 (OPS-07)
# ──────────────────────────────────────────────────────────────────────
# 2026-07-26 사고: OPS-06의 한 테스트가 pg_cached store 생성으로 `db.session._engine`
# (모듈 전역·지연 캐시)을 채우고 정리하지 않아, 같은 프로세스의 후속 테스트
# `db/test_problem_orm.py::test_session_module_imports_without_connection`(전역이 None임을
# 단언)가 *실행 순서 때문에* 깨졌다 → main CI red(#606 머지 후). 이 오염은 파일 단위 실행에서는
# 재현되지 않고 전체 스위트에서만 터져 로컬 검증을 통과했다.
#
# 근본 원인은 개별 부주의가 아니라 '전역 캐시를 채우는 테스트'를 잡는 장치의 부재. 이 가드는
# 매 테스트 종료 시 db.session 모듈 전역이 남았는지 검사해 ① 그 테스트를 실패시키고(귀책)
# ② 전역을 되돌려 다음 테스트로의 전파를 막는다(격리). 순서-의존·전체-스위트-한정 오염을
# *그 테스트 자체*의 결정론적 실패로 바꾼다. 탐지·격리 로직은 `_db_leak_guard` 모듈에 있다
# (최상단 import — 변별력을 test_db_leak_guard.py에서 별도로 실측하려고 분리).


# ──────────────────────────────────────────────────────────────────────────
# rate limit 전역 격리 (OPS-63 — OPS-06/OPS-07과 같은 유형의 2회차)
# ──────────────────────────────────────────────────────────────────────────
# 2026-09-06 사고 실측: `configure_backend_from_settings` 호출처가 0건이라 FastAPI 앱마다
# 백엔드가 재설치되지 않고, 같은 pytest 프로세스에서 도는 통합 테스트 21파일이 프로세스
# 전역 `whymath_backend.api._rate_limit._BACKEND`(기본 InMemoryBackend)의 IP 쓰기 버킷
# (`ip:testclient`·`coach_rate_limit_ip_write_per_minute`=60/분)을 공유한다 — 같은 커밋의
# 실 PG 통합 잡이 07:29 green → 09:39 red로 갈렸다(pytest-randomly 순서 차이, CI run
# 34024961969). 개별 파일의 `reset_store()` 자체 픽스처(test_coach.py 등 다수)가 이미
# 있었지만, 새 통합 테스트가 그 관용을 안 따르면 재발한다 — OPS-06(db.session._engine
# 전역 오염 → OPS-07 가드)과 같은 유형의 전역 오염이다.
#
# **OPS-07과의 관계(범위 분리)**: OPS-07(`_guard_db_session_global_leak`, 아래)은 테스트
# **종료** 시 전역 누수를 탐지·귀책하고 hermetic에만 적용된다. 이 픽스처는 테스트 **시작**
# 시 카운트를 비우는 *격리*이고 hermetic·integration 양쪽 모두에 적용된다 — 귀책 축은
# 추가하지 않는다(레이트리미터 카운트는 정상 동작의 잔여물이지 누수가 아니다).
#
# **Redis 백엔드는 건드리지 않는다** — `InMemoryBackend`일 때만 리셋한다. 로직을 별도
# 함수로 뺀 이유: `@pytest.fixture`로 감싼 함수는 pytest 내부 메커니즘을 거쳐야만 실행할
# 수 있어 직접 호출하는 단위 테스트로 변별력을 재기 어렵다. 이 헬퍼는 순수 함수라
# `tests/backend/api/test_rate_limit_fixture_isolation.py`가 pytest 스케줄링·실행 순서와
# 무관하게 직접 호출해 전/후 상태를 단언한다(`import conftest` — 위 sys.path 삽입 덕에
# `_db_leak_guard`와 동형으로 sibling import 가능).
def reset_inmemory_rate_limit_store() -> None:
    """InMemoryBackend일 때만 rate limit 카운트를 비운다 — Redis 설정은 손대지 않는다."""
    from whymath_backend.api._rate_limit import InMemoryBackend, get_backend, reset_store

    if isinstance(get_backend(), InMemoryBackend):
        import asyncio

        asyncio.run(reset_store())


@pytest.fixture(autouse=True)
def _reset_rate_limit_store_before_test() -> None:
    """모든 백엔드 테스트 **시작 시** 인메모리 rate limit 카운트를 비운다(OPS-63).

    개별 파일의 기존 `reset_store()` 자체 픽스처(test_coach.py 등)와 중복 실행돼도
    무해하다 — 두 번 비워도 결과는 빈 상태 그대로다. 테스트 *내부*에서 쌓는 카운트는
    건드리지 않는다(시작 시점 1회만).
    """
    reset_inmemory_rate_limit_store()


@pytest.fixture(autouse=True)
def _guard_db_session_global_leak(request: pytest.FixtureRequest) -> Iterator[None]:
    """모든 백엔드 테스트 종료 후 db.session 전역 누수를 탐지·격리·귀책한다(OPS-07).

    테스트 *시작* 시점은 (앞 테스트가 이 가드로 정리됐으므로) 깨끗하다고 본다. *종료* 시
    전역이 남아 있으면 이 테스트가 남긴 것이므로 실패시킨다 — 실패 신호를 내기 전에 전역을
    되돌려 다음 테스트가 연쇄로 깨지지 않게 한다(귀책과 격리를 분리).

    **범위 = hermetic 전용**: `integration` 마크 테스트는 제외한다. ① 사고는 hermetic 스위트
    (`backend — lint·type·test` 잡)에서 났고, 피해 테스트(전역 None 단언)도 hermetic이다.
    ② 통합 테스트는 별도 잡(`-m integration`·실 PG)에서 각자의 엔진 수명주기(대개 TestClient
    lifespan의 dispose)로 돌며, 두 집합은 서로 다른 프로세스라 교차 오염이 불가능하다.
    ③ 함수 단위 '엔진=None' 불변식은 실 PG 통합 테스트에 대해 로컬 검증이 불가하므로, 검증된
    범위(hermetic·7514건 실측 클린)로 가드를 한정한다.
    """
    yield
    if request.node.get_closest_marker("integration") is not None:
        return
    reason = db_session_leak_reason()
    if reason is None:
        return
    contain_db_session_leak()
    pytest.fail(format_leak_failure(request.node.nodeid, reason), pytrace=False)


# ──────────────────────────────────────────────────────────────────────────
# 무작위 순서 seed 노출 (OPS-09) — 레포 루트 conftest와 **의도적 중복**
#
# 왜 여기에도 있어야 하는가: backend 스위트는 CI에서 `cd src/backend && pytest
# -c pyproject.toml ../../tests/backend`로 돈다. 이때 rootdir이 `src/backend`가 되어
# **레포 루트 `conftest.py`가 수집 범위(confcutdir) 밖으로 밀려난다** — 즉 루트에만 두면
# 이 스위트에서는 seed가 찍히지 않는다(2026-07-27 실측: `--collect-only`로 seed 줄 0건).
# 하필 사고가 실제로 난 것이 이 스위트라, 여기서 재현 경로가 없으면 OPS-09 도입 전제가
# 무너진다(재현할 수 없는 빨강은 고칠 수 없는 빨강).
#
# 중복을 감수한 이유: 공유 모듈 import는 rootdir이 다른 두 실행 맥락에서 경로 조작을
# 요구해 오히려 깨지기 쉽다. 대신 두 사본이 어긋나지 않도록
# `tests/infra/test_seed_report_wiring.py`가 동결한다.
# ──────────────────────────────────────────────────────────────────────────
@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """설정 적재를 검증(OPS-61)하고, 무작위 순서 seed를 stdout에 항상 찍는다.

    **이 모듈의 유일한 `pytest_configure`다** — 두 번 정의하면 뒤엣것이 앞엣것을 덮어써
    먼저 정의된 훅이 조용히 사라진다. 새 초기화 로직은 훅을 하나 더 만들지 말고 헬퍼로
    빼서 여기서 부른다.

    `trylast=True` 필수 — pytest-randomly가 자기 `pytest_configure`에서 `"default"`를
    실제 정수로 확정하므로, 먼저 돌면 재현 불가능한 문자열이 로그에 남는다.
    """
    # OPS-61 — 설정이 안 읽힌 상태면 여기서 즉시 멈춘다(seed 출력보다 먼저).
    _assert_backend_ini_loaded(config)

    seed = getattr(getattr(config, "option", None), "randomly_seed", None)
    if seed is not None:
        print(
            f"[order] randomly-seed={seed}  (재현: pytest ... -p randomly --randomly-seed={seed})"
        )


# ──────────────────────────────────────────────────────────────────────────
# OPS-61 — 명시 경로 invocation의 `asyncio_mode` 미적용 함정을 **1건의 즉시 실패**로
#
# 무엇이 문제였나: `src/backend`에서 `pytest ../../tests/backend/...`처럼 **명시 경로**를 주면
# pytest가 인자의 공통조상을 상향 탐색해 **저장소 루트의 `pyproject.toml`을 rootdir 앵커**로
# 잡는다. 루트에는 `[tool.pytest.ini_options]`가 없으므로 `src/backend/pyproject.toml`의
# `asyncio_mode = "auto"`가 읽히지 않고 **strict로 폴백**하며, 그 결과 `async def` 테스트가
# 전부 "async def functions are not natively supported"로 실패한다.
#
# 실측(2026-09-06):
#     bare      → rootdir=src/backend  · inifile=src/backend/pyproject.toml · mode='auto'
#     명시 경로  → rootdir=<저장소 루트> · inifile=<루트>/pyproject.toml      · mode='strict'
# 2026-09-05 전체 스위트 730 실패 중 **718건(98.4%)**이 이 형태였고, 같은 커밋의 CI(bare
# `pytest`)는 11,727 passed·0 failed였다 — 즉 코드가 아니라 **호출 방식**이 만든 빨강이다.
#
# 왜 가드인가(ARCH-22의 2회차): 이 현상은 2026-07-30에도 관측됐으나 원인이 **"무상한 pin"**으로
# 잘못 기록돼(그 정정은 `src/backend/pyproject.toml` 주석에 있다) 재발했다. 723건이 늘 빨간
# 상태면 **새 실패와 소음을 구분할 수 없다** — 실패가 정보가 되지 못한다. 그래서 718건의 혼란
# 대신 **원인을 지목하는 실패 1건**으로 바꾼다.
#
# 이 가드가 하지 않는 것: 모드를 *고쳐 주지* 않는다. 조용히 auto로 되돌리면 "왜 초록인지"가
# 사라지고, 다음 사람이 rootdir이 어디로 잡혔는지 모른 채 다른 ini 설정(테스트 경로·마커·
# 필터)도 함께 누락된 상태로 돌게 된다. 알려 주고 멈추는 편이 옳다.
# ──────────────────────────────────────────────────────────────────────────
def _assert_backend_ini_loaded(config: pytest.Config) -> None:
    """`asyncio_mode`가 auto가 아니면 원인을 지목하고 즉시 멈춘다.

    **훅이 아니라 헬퍼다.** 한 모듈에 `pytest_configure`를 두 번 정의하면 뒤엣것이 앞엣것을
    덮어써 먼저 정의된 훅이 **조용히 사라진다** — 초판이 실제로 그렇게 써서 위쪽 seed 출력
    훅을 죽였고(실측: seed 줄 0건) `ruff` F811이 그것을 경고했는데 `noqa`로 눌러 위장했다.
    아래 하나뿐인 `pytest_configure`가 이 헬퍼를 부른다.

    `getini`가 이 키를 모르는 경우(pytest-asyncio 미설치)는 **가드 대상이 아니다** — 그때는
    async 테스트 자체가 수집되지 않으므로 이 함정과 무관하고, 여기서 막으면 플러그인 부재라는
    다른 문제를 이 메시지로 오진하게 만든다.
    """
    try:
        mode = str(config.getini("asyncio_mode"))
    except (ValueError, KeyError):
        return

    if mode == "auto":
        return

    raise pytest.UsageError(
        "\n"
        "━━━ pytest 설정이 읽히지 않았다 (OPS-61) ━━━\n"
        f"  asyncio_mode = {mode!r}  (기대: 'auto')\n"
        f"  rootdir      = {config.rootpath}\n"
        f"  inifile      = {config.inipath}\n"
        "\n"
        "원인: 명시 테스트 경로를 인자로 주면 pytest가 인자의 공통조상을 상향 탐색해\n"
        "      저장소 루트를 rootdir로 잡는다. 루트 pyproject.toml에는 pytest 설정이 없어\n"
        "      src/backend/pyproject.toml 의 asyncio_mode='auto' 가 읽히지 않는다.\n"
        "      이대로 두면 async def 테스트가 전부 실패한다(2026-09-05 실측 718건).\n"
        "      ※ pytest-asyncio pin 버전과 무관하다 — 상한을 올려도 재현된다.\n"
        "\n"
        "해결(둘 중 하나):\n"
        "  1) CI와 같게 bare 호출     : cd src/backend && python -m pytest -k <필터>\n"
        "  2) 설정을 명시로 고정       : python -m pytest -c src/backend/pyproject.toml \\\n"
        "                                --rootdir=src/backend <경로...>\n"
        "\n"
        "이 가드의 근거·실측은 src/backend/pyproject.toml 의 pytest-asyncio 주석에 있다."
    )
