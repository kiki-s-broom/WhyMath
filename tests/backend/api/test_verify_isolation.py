"""verify 엔드포인트의 SymPy 격리 — 이벤트 루프 비차단 + 시간 상한 = 판정 불가(OPS-96).

acceptance ④의 변별력 증명:
  ⓐ 상한 초과는 **판정 불가**(`unverifiable`)다 — 통과(`correct`/`pass`)도 오답도 아니다.
  ⓑ 느린 식이 도는 동안 **같은 워커의 가벼운 요청이 막히지 않는다**.
  ⓑ의 *대조군*(`test_control_...`): 격리를 끄면(`sympy_isolation_enabled=false` — 격리를 되돌린
  뮤테이션과 같은 상태) 같은 가벼운 요청이 느린 식이 끝날 때까지 막힌다. 이 대조군이 RED/GREEN을
  가르므로 ⓑ가 "아무 때나 통과하는 검사"가 아님이 기계로 보인다.

느린 입력은 합성 sleep이 아니라 실제 SymPy가 느린 식이다(`x^20+x+1=0` → `x^19+x+2=0`·`safe_parse`
구조 예산 상한 차수의 방정식 단계·이 환경 첫 계산 4.2초 — 같은 프로세스 재호출은 SymPy 캐시로 0.2초,
2026-10-14 실측).
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from whymath_backend.api import _isolated_call
from whymath_backend.api import verify as verify_api
from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.config import get_settings
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3.isolated_call import BudgetExceededError
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_SLOW_A = "x^20+x+1=0"
_SLOW_B = "x^19+x+2=0"
_CAP_S = 0.5
# 실 SymPy 체인의 요청 벽시계 상한 — 예산(상한×4=2.0s) + 마감 직전 kill·스레드 오버헤드. OPS-128로
# 워커 기동·복원 대기가 마감 안에 묶인 뒤 정상 실측은 2.14~2.58초(10회·4코어 단독)였다. OPS-136이
# 앱 첫 요청의 라우트 지연 생성을 창 밖으로 빼(`_prime_routes`) 정상은 2.006~2.024초로 내려갔다
# (단독 5회 2.008~2.012 · 방해 프로세스 4개 + 4병렬 9회 2.006~2.024, 2026-10-14 실측) — 예산이 요청 시간을
# 정확히 묶기 때문이다. 예산 제거 뮤테이션(배수 100)은 단독 28.2초 이상·부하 50.2초 이상(옛 기록 11.27초).
# 정상 최대의 약 2.0배·뮤테이션 최소의 약 1/7 — 라우트 생성 외 부하 여유를 남기려 더 조이지 않는다.
_CHAIN_WALL_BOUND_S = 4.0
# 콜드 워커(기동 4초) 체인의 벽시계 여유 — 예산 2.0초에 더한다. 정상은 예열 후 2.008~2.023초(단독·부하
# 동일)이고 예열 전엔 2.14~2.83초였다(수정 전 여유 0.75초는 부하에서 3.01~3.20초로 5/32 RED). 예산 제거
# 뮤테이션은 기동 4초를 그대로 기다려 단독 7.7초 이상·부하 12.5초 이상이다. 정상의 약 1.7배·뮤테이션
# 최소(7.7초)의 절반 미만.
_COLD_BOOT_WALL_SLACK_S = 1.5


def _unique_slow(degree: int) -> tuple[str, str]:
    """프로세스 안에서 *처음 보는* 느린 방정식 단계 — 계수를 시각 기반으로 고유하게 만든다.

    SymPy는 같은 입력을 내부 캐시에 두어 재호출이 0.05초로 끝난다(실측: 첫 호출 10~17초 → 같은
    입력 재호출 0.05초). 프로세스 안에서 직접 돌리는 대조군이 앞선 테스트의 캐시에 적중하면 느린
    입력이 빠르게 끝나 *대조군이 변별하지 못한다* — 테스트 순서(무작위화)에 따라 깨지는 가짜 통과/
    실패를 막으려고 대조군은 항상 고유 입력을 쓴다. 차수 12≈2.2초·13≈2.9초(이 환경 실측).
    """
    k = time.time_ns() % 1_000_000 + 2
    return f"x^{degree}+{k}*x+1=0", f"x^{degree - 1}+{k}*x+2=0"


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=uuid.uuid4(), persona_primary=Persona.A_일반고고3)
    )


class _FakeSession:
    async def execute(self, stmt: Any) -> None:
        raise AssertionError("verify 라우터(stateless)는 DB 쿼리하지 않아야 한다.")


def _app() -> Any:
    """테스트 앱 — 인증은 고정 사용자, DB는 접근 시 실패하는 가짜 세션."""
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return app


def _configure(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    """env로 격리 설정을 바꾸고 캐시·풀을 비운다(설정은 프로세스 수명 캐시라 반드시 비운다)."""
    monkeypatch.setenv("WHYMATH_JWT_SECRET_KEY", "test-secret-0123456789abcdef")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_TIMEOUT_S", str(_CAP_S))
    monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_MAX_WORKERS", "1")
    get_settings.cache_clear()
    _isolated_call.reset_pool_for_tests()


@pytest.fixture
def isolation_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=True)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def isolation_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    _configure(monkeypatch, enabled=False)
    yield
    _isolated_call.reset_pool_for_tests()
    get_settings.cache_clear()


def _prime_routes(client: TestClient) -> None:
    """앱의 첫 verify 요청이 치르는 라우트 지연 생성을 측정 창 밖에서 먼저 치른다(OPS-136).

    FastAPI는 앱마다 첫 요청에서 라우트 76개의 의존성·응답 모델(`TypeAdapter` 229개)을 지연 생성한다
    — 단독 ≈0.15초지만 부모 프로세스의 CPU 일이라 코어를 초과 구독하면 ≈1초까지 부푼다(실측: 측정 창
    `elapsed`의 `other` 구간). 계산 상한·예산과 무관한 비용이라 벽시계 단언의 창에 섞이면 안 된다.
    입력 검증에서 끝나는 422 요청이라 풀·워커를 건드리지 않는다 — 콜드 풀을 쓰는 테스트에도 안전하다.
    """
    resp = client.post("/v1/verify-solution", json={})
    assert resp.status_code == 422, resp.text


def _warm_worker() -> None:
    """워커 기동(SymPy import ≈1s + 웜업)을 시간 상한 밖에서 미리 치른다.

    식 종류별 첫 사용의 지연 import(`simplify` → `sympy.physics` ≈68ms)는 이 호출의 입력(`2*(x+1)`)이
    아니라 워커의 `warmup`(OPS-142)이 기동 단계에서 치른다 — 웜업이 없던 때는 이 호출이 데운 것은
    덧셈 경로뿐이라, 본문의 첫 `(a+b)^2`가 그 비용을 계산 상한 안에서 치렀다."""
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/verify-step", json={"expr_before": "2*(x+1)", "expr_after": "2*x+2"}
        )
        assert resp.status_code == 200 and resp.json()["state"] == "correct"


# ── ⓐ 상한 초과 = 판정 불가 ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("isolation_on")
class TestBudgetMeansUnverifiable:
    def test_slow_step_is_unverifiable_not_correct_nor_incorrect(self) -> None:
        _warm_worker()
        with TestClient(_app()) as client:
            resp = client.post(
                "/v1/verify-step", json={"expr_before": _SLOW_A, "expr_after": _SLOW_B}
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "unverifiable"  # 통과도 오답도 아니다
        assert body["reason_code"] == "undecidable"  # 기존 폐쇄 7종 재사용 — 스키마 불변
        assert "상한" in body["reason"]
        assert body["evidence_weight"] == 0.5
        # "상한이 계산을 끊었다"는 벽시계가 아니라 풀의 계상으로 증명한다(OPS-136) — 종전 `elapsed < 2.0`은
        # 앱 기동·첫 요청의 라우트 지연 생성·종료까지 재서 코어를 초과 구독한 러너(머지 큐 2.07초)에서 깨졌다.
        # 격리를 끈 뮤테이션은 풀이 없어 계상이 {}고, 상한을 키운 뮤테이션은 `timeouts`가 0이라 둘 다 RED다.
        stats = _isolated_call.isolation_stats()
        assert stats.get("timeouts") == 1, f"상한이 계산을 끊지 않았다 — 풀 계상 {stats}"
        assert stats["calls"] == 2  # 워밍업 + 느린 식, 둘 다 풀 경유(스레드 폴백 아님)
        assert stats["deadlines"] == stats["worker_deaths"] == stats["queue_waits"] == 0
        assert stats["fallbacks"] == 0
        assert _isolated_call._get_pool().timeout_s == _CAP_S  # 끊은 상한이 설정한 0.5초다

    def test_normal_step_is_unaffected_by_isolation(self) -> None:
        """정상 문항은 격리 전후 같은 판정 — 정상 입력이 판정 불가로 새지 않는다."""
        _warm_worker()
        with TestClient(_app()) as client:
            ok = client.post(
                "/v1/verify-step", json={"expr_before": "(a+b)^2", "expr_after": "a^2+2*a*b+b^2"}
            )
            bad = client.post(
                "/v1/verify-step", json={"expr_before": "(a+b)^2", "expr_after": "a^2+b^2"}
            )
        assert ok.json()["state"] == "correct"
        assert bad.json()["state"] == "incorrect"

    def test_each_endpoint_maps_budget_to_unverifiable_never_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """세 엔드포인트 모두 상한 초과를 `unverifiable`로 접는다 — pass·correct·fail·incorrect 아님.

        풀을 항상 초과를 던지는 스텁으로 바꿔 결정론으로 검증한다(타이밍 비의존).
        """

        class _AlwaysExceeded:
            async def run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
                raise BudgetExceededError("timeout", 1.0)

        monkeypatch.setattr(_isolated_call, "_get_pool", lambda: _AlwaysExceeded())
        with TestClient(_app()) as client:
            step = client.post(
                "/v1/verify-step", json={"expr_before": "x", "expr_after": "x"}
            ).json()
            sol = client.post("/v1/verify-solution", json={"steps": ["x", "x", "x"]}).json()
            ans = client.post(
                "/v1/verify-answer", json={"conditions": "x = 3", "answer": {"x": "3"}}
            ).json()
        assert step["state"] == "unverifiable"
        assert sol["n_transitions"] == 2
        assert sol["n_unverifiable"] == 2 and sol["n_correct"] == 0 and sol["n_incorrect"] == 0
        assert sol["has_incorrect"] is False
        assert ans["state"] == "unverifiable"

    def test_solution_keeps_other_transitions_and_caps_total_budget(self) -> None:
        """체인: 느린 전이만 판정 불가로 접히고 정상 전이 판정은 보존된다 + 총 예산으로 요청 시간이 묶인다.

        steps = [정상, 정상, 정상, A, B, A, B, A, B, A, B]: t0·t1 correct, t2는 표현식→등식 혼합(빠른
        unverifiable), t3~t9는 전부 느린 방정식 전이(7개). 전이마다 상한(0.5s)만 있다면 3.5s+가
        걸리지만 총 예산(상한×4=2.0s)이 있어 그 안에서 끝난다.
        """
        _warm_worker()
        steps = ["2*(x+1)", "2*x+2", "2*x+2+0", _SLOW_A, _SLOW_B, _SLOW_A, _SLOW_B]
        steps += [_SLOW_A, _SLOW_B, _SLOW_A, _SLOW_B]
        with TestClient(_app()) as client:
            # 검증 요청 한 건만 잰다 — 앱 기동·종료(실측 0.02초 안팎)와 앱 첫 요청의 라우트 지연 생성
            # (≈0.15초·과부하 ≈1초)은 이 테스트의 대상이 아니라 먼저 치른다(OPS-136).
            _prime_routes(client)
            started = time.perf_counter()
            resp = client.post("/v1/verify-solution", json={"steps": steps})
            elapsed = time.perf_counter() - started
        assert resp.status_code == 200, resp.text
        body = resp.json()
        states = [s["state"] for s in body["steps"]]
        assert states[:2] == ["correct", "correct"]  # 정상 전이 판정 보존
        assert all(s == "unverifiable" for s in states[2:])  # 느린 전이는 전부 판정 불가
        assert body["n_correct"] == 2 and body["n_incorrect"] == 0
        assert body["n_unverifiable"] == len(steps) - 1 - 2
        # 총 예산(2.0s)이 요청 시간을 묶는다 — 예산을 없앤 뮤테이션은 느린 전이를 전부 계산해
        # 11.3~11.6초를 쓴다(OPS-127 실측). 종전엔 정상도 예산을 *재기동 1회만큼* 넘었다(마감이 워커
        # 기동·복원 대기를 못 묶음 — 2.2~3.7초·CI 3.45초) — OPS-128이 그 대기를 마감 안에 가뒀다
        # (정상 2.14~2.58초). 남은 예산 배분의 *정확성*은 벽시계로 구별되지 않으므로(아래 결정론 테스트가
        # 맡는다) 여기서는 "예산이 요청을 묶었다"만 본다.
        assert elapsed < _CHAIN_WALL_BOUND_S, f"체인 총 예산 2.0s 기대 — {elapsed:.2f}s"
        assert _isolated_call.isolation_stats()["timeouts"] < 7, "예산이 전이를 건너뛰지 않았다"

    def test_solution_grants_each_transition_only_the_remaining_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """총 예산 배분을 벽시계 없이 고정한다 — 가짜 시계 + 상한을 끝까지 쓰는 스텁 풀(OPS-127).

        각 호출은 받은 상한만큼 계산하고 워커 재기동(0.3s · 마감 안·계산 상한 밖)을 더 쓴 뒤 초과로 끝난다.
        예산 2.0s에서: 0.5 → 0.5 → 남은 0.4 → 소진(이후 전이는 계산 없이 판정 불가).
        남은 예산 대신 상한 전체를 주는 뮤테이션(0.5·0.5·0.5)과 예산을 없앤 뮤테이션(8회 호출)이 둘 다
        RED다 — 위 실 SymPy 테스트의 벽시계로는 앞의 뮤테이션이 정상과 구별되지 않는다.
        """
        clock = {"now": 1000.0}
        monkeypatch.setattr(verify_api, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        granted: list[float] = []
        budgets: list[float] = []

        class _BurnsItsWholeLimit:
            async def run(
                self, fn: Any, *args: Any, timeout_s: float, budget_s: float | None, **kwargs: Any
            ) -> Any:
                granted.append(timeout_s)
                assert (
                    budget_s is not None
                ), "체인이 총 예산(budget_s)을 풀에 넘기지 않았다(OPS-128)"
                budgets.append(budget_s)
                clock["now"] += timeout_s + 0.3
                raise BudgetExceededError("timeout", timeout_s)

        monkeypatch.setattr(_isolated_call, "_get_pool", lambda: _BurnsItsWholeLimit())
        with TestClient(_app()) as client:
            body = client.post("/v1/verify-solution", json={"steps": ["x"] * 9}).json()
        assert granted == pytest.approx([_CAP_S, _CAP_S, 0.4])  # 마지막은 남은 예산만
        # OPS-128 — 계산 상한과 별개로, 호출 *전체*(기동·복원 대기 포함)의 벽시계 예산도 남은 예산이다.
        assert budgets == pytest.approx([2.0, 1.2, 0.4])
        assert sum(granted) <= _CAP_S * verify_api._CHAIN_BUDGET_FACTOR + 1e-9
        assert body["n_transitions"] == 8
        assert body["n_unverifiable"] == 8 and body["n_correct"] == 0 and body["n_incorrect"] == 0

    def test_solution_cold_worker_boot_cannot_outlive_chain_budget(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """OPS-128 ① — 느리게 뜨는 워커가 체인 총 예산(2.0s)을 넘겨 요청을 붙잡지 못한다.

        워커 기동(`ready`)은 계산 상한 밖이라 종전엔 마감도 묶지 못했다 — 마감 직전에 시작한 전이가
        기동 대기만큼(최악 60초) 요청을 늘렸다. 여기서는 import에 4초 걸리는 모듈을 워커의 사전
        import로 주입해 그 상황을 만든다(콜드 풀 — `_warm_worker()`를 일부러 부르지 않는다).
        예산 안에 `ready`가 오지 않으면 전이는 판정 불가로 접히고 요청은 예산 + 여유 안에 끝나야 한다.
        """
        (tmp_path / "ops128_slow_boot.py").write_text("import time\ntime.sleep(4.0)\n")
        monkeypatch.syspath_prepend(str(tmp_path))  # spawn 자식은 부모의 sys.path를 물려받는다
        monkeypatch.setenv("WHYMATH_SYMPY_ISOLATION_PRELOAD_MODULES", '["ops128_slow_boot"]')
        get_settings.cache_clear()
        _isolated_call.reset_pool_for_tests()
        budget_s = _CAP_S * 4  # verify_api._CHAIN_BUDGET_FACTOR

        with TestClient(_app()) as client:
            # 풀·워커는 콜드 그대로 — 라우트 지연 생성만 창 밖에서 치른다(OPS-136)
            _prime_routes(client)
            started = time.perf_counter()
            resp = client.post("/v1/verify-solution", json={"steps": ["2*x+2", "2*(x+1)", "x+x+2"]})
            elapsed = time.perf_counter() - started
        assert resp.status_code == 200, resp.text
        assert (
            elapsed < budget_s + _COLD_BOOT_WALL_SLACK_S
        ), f"체인 총 예산 {budget_s}s인데 {elapsed:.2f}s — 워커 기동 대기가 마감 밖이다"
        body = resp.json()
        # 기동이 안 끝난 전이는 통과·오답이 아니라 판정 불가다 — 점수가 새지 않는다.
        assert body["n_unverifiable"] == 2 and body["n_correct"] == 0 and body["n_incorrect"] == 0

    def test_step_types_length_error_is_still_422(self) -> None:
        """입력 규약 위반은 격리와 무관하게 422 — 판정 불가로 접히지 않는다."""
        with TestClient(_app()) as client:
            resp = client.post(
                "/v1/verify-solution", json={"steps": ["a", "b", "c"], "step_types": ["계산"]}
            )
        assert resp.status_code == 422


# ── ⓑ 루프 비차단 + 대조군 ───────────────────────────────────────────────────────


async def _light_request_lateness_during_slow_step(
    slow_pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> tuple[float, float]:
    """느린 verify-step이 진행 중일 때 가벼운 `/health` 요청이 *얼마나 늦어졌는가*(초)와 느린 요청 총 시간.

    기준 시각은 **느린 요청이 핸들러에 진입한 시각**이다. 루프가 막히면 가벼운 요청을 *보내기조차*
    못하므로, 막힌 시간은 "목표 시각보다 얼마나 늦게 보낼 수 있었는가"로 잰다(가벼운 요청의 단순
    응답 시간을 재면 막히고 난 뒤 보내서 0.00s로 보인다 — 이 테스트의 첫 판본이 그 함정에 빠졌다).

    **고정 `sleep`을 기준으로 삼지 않는다** — 구 판본은 요청 송신 0.15초 뒤를 목표로 삼았는데, 핸들러가
    SymPy 호출에 진입하는 시각이 첫 요청 준비(미들웨어·의존성·본문 검증)로 0.10~0.33초 사이에서
    흔들려(4코어 샌드박스 실측 2026-10-09) 진입이 0.15초보다 늦으면 *막히기 전에* 가벼운 요청이 먼저
    나가 늦어짐이 0.1초대로 측정됐다(대조군이 "격리 OFF인데 안 막힘"으로 거짓 RED, 격리 ON 쪽은 격리를
    되돌려도 GREEN이 되는 거짓 통과 위험). 그래서 진입 시각을 직접 기록하고 그 시각 + 0.1초를 목표로 삼는다.

    **진입 시각은 의존성 해석이 아니라 핸들러가 `isolated(...)`를 부르는 순간이다(OPS-136)** — 직전 판본은
    의존성 해석 스레드에서 기록했는데, 그 시각과 핸들러 본문이 SymPy를 부르는 시각 사이에 이벤트 루프의
    한 번 이상 돌아감이 끼어 있다. 코어를 초과 구독하면 이 간격이 0.1초를 넘어(수정 전 판본을 방해
    프로세스 4~6개 아래서 32회 돌려 대조군이 6회 RED, 늦어짐 0.01초) 가벼운 요청이 *막히기 전에* 먼저
    나갔다. 핸들러 진입 직후에는 `await` 없이 곧바로 격리 OFF의 동기 계산이 시작되므로 간격이 없다.
    """
    entered: dict[str, float] = {}
    signal = threading.Event()
    real_isolated = verify_api.isolated

    async def _isolated_marking_entry(*args: Any, **kwargs: Any) -> Any:
        entered["t"] = time.perf_counter()
        signal.set()
        return await real_isolated(*args, **kwargs)

    monkeypatch.setattr(verify_api, "isolated", _isolated_marking_entry)
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        slow_started = time.perf_counter()
        slow = asyncio.create_task(
            client.post(
                "/v1/verify-step", json={"expr_before": slow_pair[0], "expr_after": slow_pair[1]}
            )
        )
        # 스레드에서 기다린다 — 루프가 막혀 있어도 이 대기와 기록은 영향받지 않는다.
        assert await asyncio.to_thread(signal.wait, 30.0), "느린 요청이 핸들러에 도달하지 못했다"
        target = entered["t"] + 0.1  # 핸들러 진입 → (ON) 워커 디스패치 완료까지의 여유
        delay = target - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)  # 루프가 막혀 있었다면 이미 지나 있어 건너뛴다
        light = await client.get("/health")
        lateness = time.perf_counter() - target
        assert light.status_code == 200
        resp = await slow
        assert resp.status_code == 200
        return lateness, time.perf_counter() - slow_started


class TestEventLoopNotBlocked:
    async def test_light_request_is_not_blocked_by_slow_sympy(
        self, isolation_on: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """④ⓑ 격리 ON — 느린 식(상한 0.5s) 진행 중에도 가벼운 요청이 거의 늦어지지 않는다(< 0.3s)."""
        await asyncio.to_thread(_warm_worker)
        # 고유 입력(차수 14 ≈ 3.7초 > 상한 0.5초) — 격리를 되돌린 뮤테이션에서 앞선 테스트의 SymPy 캐시에
        # 적중해 빠르게 끝나면 이 테스트가 RED가 되지 못한다(뮤테이션 실측으로 확인한 결함).
        lateness, _ = await _light_request_lateness_during_slow_step(_unique_slow(14), monkeypatch)
        assert lateness < 0.3, f"가벼운 요청이 {lateness:.2f}s 늦어졌다 — 루프 차단"

    async def test_control_without_isolation_blocks_the_loop(
        self, isolation_off: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """대조군 — 격리 OFF(= 격리를 되돌린 뮤테이션)면 같은 가벼운 요청이 느린 식이 끝날 때까지 막힌다.

        이 테스트가 GREEN이라는 것은 위 `test_light_request_is_not_blocked...`가 격리 때문에
        통과했다는 증거다(격리가 없어도 통과하는 무의미한 검사가 아님).
        """
        # 고유 입력(차수 12≈2.2초) — 같은 프로세스 SymPy 캐시에 적중하면 빠르게 끝나 변별하지 못한다.
        lateness, slow_total = await _light_request_lateness_during_slow_step(
            _unique_slow(12), monkeypatch
        )
        assert lateness > 1.0, f"격리 OFF인데 늦어짐 {lateness:.2f}s — 대조군이 변별하지 못한다"
        assert slow_total > 1.5
