"""FastAPI 앱 단위테스트 — TestClient + 가짜 의존성 주입 (라이브 서비스 없음).

/health·/status(도달 가능/불가)·/v1/generate(동기 정상·QUALITY 202 큐잉·큐 미가용
503)·/v1/jobs/{id}(폴링)를 검증한다. 실제 Ollama·Redis·Langfuse·Celery broker에
의존하지 않는다 — 특히 가짜 큐를 주입해 기본 CeleryJobQueue가 broker에 닿는 것을 막는다
(hermeticity: 큐 미주입 시 QUALITY 경로가 라이브 Redis로 ~20초 블록됨).

인가(SEC-07 D1 + SEC-24(원 SEC-15) M6): `/v1/generate`·`/v1/jobs/{id}` 둘 다 `CurrentUser`(인증만)
게이트가 있다(SEC-24(원 SEC-15)가 폴링의 무인증 구멍을 봉인 — POST만 봉인되고 폴링이 열려 있었다).
이 파일의 대부분 테스트는 라우팅/캐시/큐 *결선*이 목적이라 `_client()`가
`get_current_user`를 고정 인증 사용자로 오버라이드한다(test_concepts.py의
`require_content_admin` 오버라이드 패턴과 동형) — 인증 자체(무토큰 401·실토큰 200)는
`TestGenerateAuthGate`·`TestJobsAuthGate`가 오버라이드 없이 검증한다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_current_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.job_ownership import JobOwnership
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l3.interfaces import InMemoryCache, RecordingTraceSink
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l3.providers.anthropic import AnthropicStatus
from whymath_backend.l3.providers.ollama import ModelAvailability, OllamaStatus
from whymath_backend.l3.queue.celery_job_queue import JobStatus
from whymath_backend.security import create_access_token

_FAKE_USER = UserProfile(user_id=uuid.uuid4())


class StubProvider:
    """가짜 LLMProvider + check_status — 앱 결선 검증용."""

    def __init__(
        self,
        *,
        text: str = "원시출력",
        status: OllamaStatus | None = None,
    ) -> None:
        self._text = text
        self._status = status
        self.calls: list[tuple[str, str, RoutingDecision]] = []

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        self.calls.append((prompt, system, decision))
        return GenerationResult(self._text)

    async def check_status(self) -> OllamaStatus:
        if self._status is not None:
            return self._status
        return OllamaStatus(reachable=True, models=())


class StubCompositeProvider:
    """가짜 복합 provider — check_status(로컬) + check_cloud_status(클라우드) 노출.

    /status 클라우드 필드 매핑(S5)을 검증하기 위해 CompositeProvider 표면만 모사한다.
    """

    def __init__(
        self,
        *,
        ollama_status: OllamaStatus,
        cloud_status: AnthropicStatus | None,
    ) -> None:
        self._ollama_status = ollama_status
        self._cloud_status = cloud_status

    async def generate(
        self, prompt: str, system: str, decision: RoutingDecision
    ) -> GenerationResult:
        return GenerationResult("")

    async def check_status(self) -> OllamaStatus:
        return self._ollama_status

    async def check_cloud_status(self) -> AnthropicStatus | None:
        return self._cloud_status


class StubQueue:
    """가짜 AsyncJobQueue + result — 앱 결선 검증용(broker 없음).

    enqueue는 정해진 job_id를 돌려주고(또는 raises로 broker 다운 모사), result는 등록한
    JobStatus를 돌려준다(폴링 모사). result_supported=False면 result 메서드를 제거해
    '폴링 미지원 큐' 분기(/v1/jobs unknown)를 검증할 수 있다.
    """

    def __init__(
        self,
        *,
        job_id: str = "job-1",
        enqueue_raises: Exception | None = None,
        statuses: dict[str, JobStatus] | None = None,
    ) -> None:
        self._job_id = job_id
        self._enqueue_raises = enqueue_raises
        self._statuses = statuses or {}
        self.payloads: list[dict[str, object]] = []

    async def enqueue(self, payload: dict[str, object]) -> str:
        self.payloads.append(payload)
        if self._enqueue_raises is not None:
            raise self._enqueue_raises
        return self._job_id

    def result(self, job_id: str) -> JobStatus:
        return self._statuses.get(job_id, JobStatus(job_id=job_id, state="pending"))


class NoPollQueue:
    """result 메서드가 없는 가짜 큐 — /v1/jobs 폴링 미지원 분기 검증용."""

    async def enqueue(self, payload: dict[str, object]) -> str:
        return "job-x"


class _FakeSession:
    """/v1/generate·/v1/jobs의 session 의존성용 가짜 세션 — 동의 조회 + job_ownership 모사.

    `ownership`는 여러 HTTP 요청(POST 큐잉 → GET 폴링)에 걸쳐 *공유*되는 인메모리 딕셔너리다
    (`_client()`가 하나 만들어 클로저로 매 요청의 새 `_FakeSession` 인스턴스에 주입) — 실
    세션은 매 요청 새로 만들어지지만(FastAPI `Depends`), job_id→user_id 매핑은 요청 경계를
    넘어 살아있어야 실제 `job_ownership` 테이블의 영속성을 흉내낼 수 있다.

    `default_owner`는 `ownership`에 명시 기록이 없는 job_id의 소유자를 무엇으로 볼지
    결정한다 — 기본값(`_FAKE_USER.user_id`)은 SEC-27 이전부터 있던 큐 폴링 메커니즘
    테스트들(TestJobsEndpoint 등)이 소유권 도입으로 회귀하지 않게 하기 위함이다(그
    테스트들은 소유권이 아니라 큐 상태 매핑을 검증한다). 소유권 자체를 검증하는 테스트는
    `default_owner=None`(매핑 부재) 또는 다른 UUID(타 사용자 소유)를 명시한다.
    """

    def __init__(
        self,
        *,
        default_owner: uuid.UUID | None = None,
        ownership: dict[str, uuid.UUID] | None = None,
    ) -> None:
        self._default_owner = default_owner
        self._ownership = ownership if ownership is not None else {}

    async def scalar(self, stmt: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, JobOwnership):
            self._ownership[obj.job_id] = obj.user_id

    async def commit(self) -> None:
        return None

    async def get(self, model: Any, pk: Any) -> Any:
        if model is JobOwnership:
            owner = self._ownership.get(pk, self._default_owner)
            return JobOwnership(job_id=pk, user_id=owner) if owner is not None else None
        return None


def _client(
    provider: StubProvider,
    queue: Any | None = None,
    *,
    job_owner: uuid.UUID | None = _FAKE_USER.user_id,
) -> TestClient:
    """provider/cache/trace/queue를 가짜로, get_current_user/get_session을 오버라이드.

    `job_owner`(SEC-27) — 명시 기록 없는 job_id의 기본 소유자. 기본값은 `_FAKE_USER`라
    기존(소유권 도입 이전) 테스트가 무회귀. 실제 POST(큐잉)→GET(폴링) 왕복은 같은 클라이언트
    안에서 `ownership` 딕셔너리를 공유하므로, POST가 기록한 실 소유자가 `job_owner` 기본값보다
    우선한다(`_FakeSession.get`의 `ownership.get(pk, default_owner)`).
    """
    app = create_app(
        provider=provider,
        cache=InMemoryCache(),
        trace=RecordingTraceSink(),
        # 기본적으로 가짜 큐 주입 — 라이브 broker 차단(hermetic).
        queue=queue if queue is not None else StubQueue(),
    )
    app.dependency_overrides[get_current_user] = lambda: _FAKE_USER
    ownership: dict[str, uuid.UUID] = {}

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession(default_owner=job_owner, ownership=ownership)

    # /v1/generate가 ConsentScope.ai_training 동의 판정 + job_ownership 기록에 session을
    # 쓰므로, /v1/jobs가 소유권 조회에 쓰는 것과 같은 가짜 세션을 주입한다.
    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


class TestHealth:
    def test_health_ok(self) -> None:
        """/health는 의존성 없이 200 ok."""
        client = _client(StubProvider())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestStatus:
    def test_status_reachable_all_present(self) -> None:
        """모든 모델 설치 시 ready=true, reachable=true."""
        status = OllamaStatus(
            reachable=True,
            models=(
                ModelAvailability("qwen2-math:1.5b", True),
                ModelAvailability("qwen3:30b-a3b", True),
            ),
        )
        client = _client(StubProvider(status=status))
        resp = client.get("/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is True
        assert body["reachable"] is True
        assert body["missing"] == []

    def test_status_unreachable_reports_not_ready(self) -> None:
        """Ollama 불가 시에도 500이 아니라 200 + ready=false 보고."""
        status = OllamaStatus(
            reachable=False,
            models=(ModelAvailability("qwen2-math:1.5b", False),),
            error="ConnectionError: refused",
        )
        client = _client(StubProvider(status=status))
        resp = client.get("/status")
        assert resp.status_code == 200  # 비크래시
        body = resp.json()
        assert body["ready"] is False
        assert body["reachable"] is False
        assert body["error"] is not None
        assert "qwen2-math:1.5b" in body["missing"]

    def test_status_provider_without_check_method_reports_unreachable(self) -> None:
        """check_status가 없는 provider(가짜)를 주입하면 도달 불가로 보고(500 아님)."""

        class NoStatusProvider:
            async def generate(
                self, prompt: str, system: str, decision: RoutingDecision
            ) -> GenerationResult:
                return GenerationResult("")

        app = create_app(
            provider=NoStatusProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
        )
        resp = TestClient(app).get("/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ready"] is False
        assert body["reachable"] is False
        assert body["error"] is not None

    def test_status_missing_some_models(self) -> None:
        """일부 모델 누락 시 ready=false + missing 채워짐."""
        status = OllamaStatus(
            reachable=True,
            models=(
                ModelAvailability("qwen2-math:1.5b", True),
                ModelAvailability("qwen3:30b-a3b", False),
            ),
        )
        client = _client(StubProvider(status=status))
        body = client.get("/status").json()
        assert body["ready"] is False
        assert body["reachable"] is True
        assert body["missing"] == ["qwen3:30b-a3b"]

    def test_status_includes_cloud_when_provider_exposes_it(self) -> None:
        """CompositeProvider 표면(check_cloud_status) → /status에 cloud_* 필드가 채워진다(S5)."""
        provider = StubCompositeProvider(
            ollama_status=OllamaStatus(
                reachable=True, models=(ModelAvailability("qwen2-math:1.5b", True),)
            ),
            cloud_status=AnthropicStatus(configured=True, reachable=True),
        )
        app = create_app(
            provider=provider,
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=StubQueue(),
        )
        body = TestClient(app).get("/status").json()
        assert body["cloud_configured"] is True
        assert body["cloud_reachable"] is True
        assert body["cloud_error"] is None
        assert body["reachable"] is True  # 로컬 필드는 그대로 보고

    def test_status_cloud_unconfigured_reports_false(self) -> None:
        """클라우드 키 미설정 → cloud_configured=False, cloud_reachable=False(비크래시)."""
        provider = StubCompositeProvider(
            ollama_status=OllamaStatus(reachable=True, models=()),
            cloud_status=AnthropicStatus(configured=False, reachable=False, error=None),
        )
        app = create_app(
            provider=provider,
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=StubQueue(),
        )
        body = TestClient(app).get("/status").json()
        assert body["cloud_configured"] is False
        assert body["cloud_reachable"] is False

    def test_status_cloud_fields_none_when_provider_lacks_cloud_check(self) -> None:
        """check_cloud_status 미노출 provider(로컬전용·가짜) → cloud_* 필드 None(기존 호환)."""
        client = _client(StubProvider(status=OllamaStatus(reachable=True, models=())))
        body = client.get("/status").json()
        assert body["cloud_configured"] is None
        assert body["cloud_reachable"] is None
        assert body["cloud_error"] is None


class TestGenerateEndpoint:
    def test_generate_happy_path_local(self) -> None:
        """LOCAL 동기 경로 → 200 + 텍스트 + 결정 메타데이터."""
        provider = StubProvider(text="생성결과")
        client = _client(provider)
        payload = {
            "request": {
                "task_type": "explain",
                "difficulty": "easy",
                "requires_reasoning": False,
                "student_subscription": "free",
                "sync": True,
            },
            "prompt": "이차방정식이 뭐야?",
            "system": "너는 수학 코치다",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "생성결과"
        assert body["cache_hit"] is False
        # 결정 메타데이터 노출 (use_enum_values=True → 문자열)
        assert body["decision"]["cost_tier"] == "local"
        assert body["decision"]["mode"] == "sync"
        assert len(provider.calls) == 1
        # 환각 없는 출력 → shadow 검증 신호 None(필드 노출 확인).
        assert body["validation_signal"] is None

    def test_generate_surfaces_shadow_validation_signal(self) -> None:
        """거짓 수치 관계 생성물 → validation_signal에 사유 노출(비차단·텍스트 불변)."""
        provider = StubProvider(text="계산:\n2 + 2 = 5")
        client = _client(provider)
        payload = {
            "request": {
                "task_type": "explain",
                "difficulty": "easy",
                "requires_reasoning": False,
                "student_subscription": "free",
                "sync": True,
            },
            "prompt": "p",
            "system": "s",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        # 비차단: 원시 텍스트 그대로 반환.
        assert body["text"] == "계산:\n2 + 2 = 5"
        # shadow 검증 신호가 응답에 노출(조용히 넘어가지 않음).
        assert body["validation_signal"] is not None
        assert "arithmetic error" in body["validation_signal"]

    def test_generate_shadow_disabled_via_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings 게이트 off → 거짓 산술이어도 validation_signal=None(검증 미실행)."""
        monkeypatch.setenv("WHYMATH_L3_SHADOW_VALIDATION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            provider = StubProvider(text="2 + 2 = 5")
            client = _client(provider)
            payload = {
                "request": {
                    "task_type": "explain",
                    "difficulty": "easy",
                    "requires_reasoning": False,
                    "student_subscription": "free",
                    "sync": True,
                },
                "prompt": "p",
                "system": "s",
            }
            body = client.post("/v1/generate", json=payload).json()
            # 비차단 동일: 텍스트는 원시 그대로. 단, 검증 비활성이라 신호 없음.
            assert body["text"] == "2 + 2 = 5"
            assert body["validation_signal"] is None
        finally:
            get_settings.cache_clear()  # 다음 테스트로 게이트 상태 누수 방지.

    def test_skip_cache_on_signal_via_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """l3_skip_cache_on_signal=on → 거짓 산술은 캐시 미적재(재요청 시 재생성)."""
        monkeypatch.setenv("WHYMATH_L3_SKIP_CACHE_ON_SIGNAL", "true")
        get_settings.cache_clear()
        try:
            provider = StubProvider(text="계산:\n2 + 2 = 5")
            client = _client(provider)
            payload = {
                "request": {
                    "task_type": "explain",
                    "difficulty": "easy",
                    "requires_reasoning": False,
                    "student_subscription": "free",
                    "sync": True,
                },
                "prompt": "p",
                "system": "s",
            }
            first = client.post("/v1/generate", json=payload).json()
            second = client.post("/v1/generate", json=payload).json()
            # 신호 노출은 그대로(비차단). 그러나 거짓이라 캐시에 안 남아 2회차도 미스·재호출.
            assert first["validation_signal"] is not None
            assert second["cache_hit"] is False
            assert len(provider.calls) == 2  # 캐시 위생 → 재생성
        finally:
            get_settings.cache_clear()

    def test_skip_cache_default_off_caches_flagged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """기본(skip off) → 거짓 산술도 캐시 적재(2회차 히트·기존 동작)."""
        get_settings.cache_clear()  # 환경 기본값(off) 확정.
        try:
            provider = StubProvider(text="계산:\n2 + 2 = 5")
            client = _client(provider)
            payload = {
                "request": {
                    "task_type": "explain",
                    "difficulty": "easy",
                    "requires_reasoning": False,
                    "student_subscription": "free",
                    "sync": True,
                },
                "prompt": "p",
                "system": "s",
            }
            client.post("/v1/generate", json=payload)
            second = client.post("/v1/generate", json=payload).json()
            assert second["cache_hit"] is True  # 적재됨(기본 동작)
            assert len(provider.calls) == 1
        finally:
            get_settings.cache_clear()

    def test_generate_cache_hit_on_second_call(self) -> None:
        """동일 요청 2회 → 2회차 cache_hit=true(같은 앱 인스턴스 캐시 공유)."""
        provider = StubProvider(text="동일")
        client = _client(provider)
        payload = {
            "request": {
                "task_type": "explain",
                "difficulty": "easy",
                "requires_reasoning": False,
                "student_subscription": "free",
                "sync": True,
            },
            "prompt": "p",
            "system": "s",
        }
        first = client.post("/v1/generate", json=payload).json()
        second = client.post("/v1/generate", json=payload).json()
        assert first["cache_hit"] is False
        assert second["cache_hit"] is True
        assert len(provider.calls) == 1  # 2회차는 캐시

    def test_generate_quality_returns_202_with_job_id(self) -> None:
        """QUALITY(자기검증, 비동기) → 동기 호출 대신 202 Accepted + job_id(폴링 안내).

        S4 계약 변경: 기존엔 503(큐 미구현)이었으나, 이제 작업 큐에 적재하고 202로
        job_id를 돌려준다(03a §D.3). provider는 동기 호출되지 않는다.
        """
        provider = StubProvider()
        queue = StubQueue(job_id="job-quality-1")
        client = _client(provider, queue=queue)
        payload = {
            "request": {
                "task_type": "self_verify",
                "difficulty": "hard",
                "requires_reasoning": True,
                "student_subscription": "free",
                "sync": False,
                "call_site": "self_verify",
            },
            "prompt": "검증해줘",
            "system": "",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"] == "job-quality-1"
        assert body["status"] == "queued"
        assert body["decision"]["mode"] == "async"
        assert body["decision"]["local_model"] == "quality"
        assert provider.calls == []  # 동기 호출 금지
        assert len(queue.payloads) == 1  # enqueue 1회

    def test_generate_quality_503_when_queue_unavailable(self) -> None:
        """enqueue 실패(broker 다운) → 503 JSON(스택트레이스 X, 가용성 우선)."""
        provider = StubProvider()
        queue = StubQueue(enqueue_raises=ConnectionError("broker refused"))
        client = _client(provider, queue=queue)
        payload = {
            "request": {
                "task_type": "self_verify",
                "difficulty": "hard",
                "requires_reasoning": True,
                "student_subscription": "free",
                "sync": False,
                "call_site": "self_verify",
            },
            "prompt": "검증해줘",
            "system": "",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "quality_queue_unavailable"
        assert provider.calls == []  # provider 미호출

    def test_generate_rejects_unknown_request_field(self) -> None:
        """RoutingRequest는 extra=forbid → 알 수 없는 필드는 422."""
        client = _client(StubProvider())
        payload = {
            "request": {
                "task_type": "explain",
                "difficulty": "easy",
                "requires_reasoning": False,
                "student_subscription": "free",
                "sync": True,
                "bogus_field": 1,
            },
            "prompt": "p",
            "system": "s",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 422


class TestGenerateAuthGate:
    """SEC-07 D1 — `/v1/generate` 인가 회귀(오버라이드 없는 *실제* `get_current_user`).

    이전엔 인증 의존성이 0건이라 무인증 LLM 비용 남용 표면이었다(`docs/architecture/
    account_security_gap_review.md` D1). `CurrentUser`(인증만 — 역할 불문)로 게이팅한다.
    """

    def test_unauthenticated_post_returns_401(self) -> None:
        app = create_app(
            provider=StubProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=StubQueue(),
        )

        # get_session은 get_current_user의 형제 의존성이라 무토큰이어도 FastAPI가 먼저
        # 해석을 시도한다 — 가짜로 오버라이드해 실 DB 엔진 진입을 막는다(전역 누수 가드
        # OPS-07 회피, api/test_ocr_endpoint.py 선례). credentials=None이면 get_current_user가
        # session을 실제로 쓰기 전에 401을 던지므로 더미 객체만 yield하면 충분하다.
        async def _fake_session() -> Any:
            yield object()

        app.dependency_overrides[get_session] = _fake_session
        client = TestClient(app)
        payload = {
            "request": {
                "task_type": "explain",
                "difficulty": "easy",
                "requires_reasoning": False,
                "student_subscription": "free",
                "sync": True,
            },
            "prompt": "p",
            "system": "s",
        }
        resp = client.post("/v1/generate", json=payload)
        assert resp.status_code == 401


class TestJobsEndpoint:
    """GET /v1/jobs/{job_id} — QUALITY 비동기 작업 폴링 (S4)."""

    def test_job_pending_returns_200(self) -> None:
        """진행 중(pending) → 200 + state=pending, text 없음."""
        queue = StubQueue(statuses={"j1": JobStatus(job_id="j1", state="pending")})
        client = _client(StubProvider(), queue=queue)
        resp = client.get("/v1/jobs/j1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == "j1"
        assert body["state"] == "pending"
        assert body["text"] is None

    def test_job_success_returns_text(self) -> None:
        """완료(success) → 200 + text(검증 전 원시 출력). 환각 없으면 신호 None."""
        queue = StubQueue(statuses={"j2": JobStatus(job_id="j2", state="success", text="27b 결과")})
        client = _client(StubProvider(), queue=queue)
        resp = client.get("/v1/jobs/j2")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "success"
        assert body["text"] == "27b 결과"
        assert body["error"] is None
        assert body["validation_signal"] is None

    def test_job_success_surfaces_shadow_signal(self) -> None:
        """완료 텍스트에 거짓 산술 → 폴링 응답이 validation_signal 노출(동기 파리티·재검증)."""
        queue = StubQueue(
            statuses={"j2x": JobStatus(job_id="j2x", state="success", text="결과:\n2 + 2 = 5")}
        )
        client = _client(StubProvider(), queue=queue)
        body = client.get("/v1/jobs/j2x").json()
        assert body["state"] == "success"
        assert body["text"] == "결과:\n2 + 2 = 5"  # 비차단·텍스트 불변
        assert body["validation_signal"] is not None
        assert "arithmetic error" in body["validation_signal"]

    def test_job_pending_has_no_signal(self) -> None:
        """미완료(pending)는 텍스트가 없어 validation_signal None(재검증 안 함)."""
        queue = StubQueue(statuses={"j5": JobStatus(job_id="j5", state="pending")})
        client = _client(StubProvider(), queue=queue)
        body = client.get("/v1/jobs/j5").json()
        assert body["validation_signal"] is None

    def test_job_signal_none_when_shadow_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Settings 게이트 off → 완료 텍스트가 거짓이어도 재검증 안 함(신호 None)."""
        monkeypatch.setenv("WHYMATH_L3_SHADOW_VALIDATION_ENABLED", "false")
        get_settings.cache_clear()
        try:
            queue = StubQueue(
                statuses={"j6": JobStatus(job_id="j6", state="success", text="결과:\n2 + 2 = 5")}
            )
            client = _client(StubProvider(), queue=queue)
            body = client.get("/v1/jobs/j6").json()
            assert body["text"] == "결과:\n2 + 2 = 5"
            assert body["validation_signal"] is None
        finally:
            get_settings.cache_clear()

    def test_job_failure_returns_error_not_500(self) -> None:
        """실패(failure) → 200 + state=failure + error(사유), 500 스택트레이스 아님."""
        queue = StubQueue(
            statuses={"j3": JobStatus(job_id="j3", state="failure", error="모델 오류")}
        )
        client = _client(StubProvider(), queue=queue)
        resp = client.get("/v1/jobs/j3")
        assert resp.status_code == 200  # 비크래시
        body = resp.json()
        assert body["state"] == "failure"
        assert body["error"] == "모델 오류"
        assert body["text"] is None

    def test_job_unknown_state_returns_200(self) -> None:
        """판정 불가(unknown — backend 미도달 흡수) → 200 + state=unknown."""
        queue = StubQueue(
            statuses={"j4": JobStatus(job_id="j4", state="unknown", error="backend down")}
        )
        client = _client(StubProvider(), queue=queue)
        resp = client.get("/v1/jobs/j4")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "unknown"
        assert body["error"] is not None

    def test_job_unknown_id_defaults_pending(self) -> None:
        """등록 안 된 job_id는 가짜 큐 기본(pending)으로 — 200 비크래시."""
        client = _client(StubProvider(), queue=StubQueue())
        resp = client.get("/v1/jobs/never-seen")
        assert resp.status_code == 200
        assert resp.json()["state"] == "pending"

    def test_job_queue_without_result_method_reports_unknown(self) -> None:
        """result()가 없는 큐(폴링 미지원) → unknown 보고(500 아님 — 기능 탐지)."""
        client = _client(StubProvider(), queue=NoPollQueue())
        resp = client.get("/v1/jobs/whatever")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == "unknown"
        assert body["error"] is not None


class TestJobsOwnership:
    """SEC-27(48_보안 §P0) — `GET /v1/jobs/{id}` 소유권(job↔user) 인가 회귀.

    acceptance④: 소유자 ALLOW, 다른 사용자 DENY, 미인증 DENY(+ 매핑 부재도 DENY —
    acceptance③이 명시한 세 번째 상태). 전부 404로 통일(존재 자체 비노출 — `get_job`
    docstring의 근거)한다.
    """

    def test_owner_can_poll_own_job(self) -> None:
        """POST가 큐잉한 job을 같은(소유자) 사용자가 폴링 → 200(왕복 — 실 소유권 기록 경로).

        `job_owner=None`(매핑 없으면 거부)으로 명시해 "POST가 실제로 JobOwnership 행을
        기록했다"는 것 자체를 변별한다 — 기본값(`_FAKE_USER`)을 그대로 뒀다면 POST의
        기록 여부와 무관하게 항상 200이 나와 이 테스트가 아무것도 검증하지 못했을 것이다.
        """
        queue = StubQueue(
            job_id="job-owned-1",
            statuses={"job-owned-1": JobStatus(job_id="job-owned-1", state="pending")},
        )
        client = _client(StubProvider(), queue=queue, job_owner=None)
        payload = {
            "request": {
                "task_type": "self_verify",
                "difficulty": "hard",
                "requires_reasoning": True,
                "student_subscription": "free",
                "sync": False,
                "call_site": "self_verify",
            },
            "prompt": "검증해줘",
            "system": "",
        }
        post_resp = client.post("/v1/generate", json=payload)
        assert post_resp.status_code == 202
        job_id = post_resp.json()["job_id"]
        assert job_id == "job-owned-1"
        get_resp = client.get(f"/v1/jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["state"] == "pending"

    def test_other_user_job_returns_404(self) -> None:
        """소유자가 다른 사용자(job_owner≠현재 인증 사용자) → 404(리소스 존재 비노출)."""
        queue = StubQueue(statuses={"j-other": JobStatus(job_id="j-other", state="pending")})
        client = _client(StubProvider(), queue=queue, job_owner=uuid.uuid4())
        resp = client.get("/v1/jobs/j-other")
        assert resp.status_code == 404

    def test_unmapped_job_returns_404(self) -> None:
        """job_ownership 행 자체가 없음(job_owner=None) → 404(매핑 부재도 동일 거부)."""
        queue = StubQueue(statuses={"j-unmapped": JobStatus(job_id="j-unmapped", state="pending")})
        client = _client(StubProvider(), queue=queue, job_owner=None)
        resp = client.get("/v1/jobs/j-unmapped")
        assert resp.status_code == 404


class TestJobsAuthGate:
    """SEC-24(원 SEC-15) M6 — `GET /v1/jobs/{id}` 인가 회귀(오버라이드 없는 *실제* `get_current_user`).

    SEC-07이 짝인 `POST /v1/generate`만 봉인하고 폴링을 "범위 밖"으로 남겨, 검증 전 원시
    LLM 출력이 무인증으로 반환되고 있었다(`functional_security_audit_2026-08-08.md` M6).
    무토큰 → 401, 유효 토큰(실 JWT mint/decode) → 기존 폴링 동작(200) 유지의 양방향을
    동결한다. 소유권(job↔user) 검사는 job→user 저장이 생길 때 후속(핸들러 docstring).
    """

    _JWT_SETTINGS = Settings(jwt_secret_key=SecretStr("test-secret-key-0123456789abcdef"))

    def _app(self, statuses: dict[str, JobStatus] | None = None) -> Any:
        return create_app(
            provider=StubProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=StubQueue(statuses=statuses or {}),
        )

    def test_unauthenticated_get_returns_401(self) -> None:
        """무토큰 폴링 → 401 (TestGenerateAuthGate와 동일 구성 — 실 DB 진입 차단)."""
        app = self._app()

        # get_session은 get_current_user의 하위 의존성 — 가짜로 오버라이드해 실 DB 엔진
        # 진입을 막는다(OPS-07 전역 누수 가드 회피). credentials=None이면 session을 실제로
        # 쓰기 전에 401이므로 더미 객체만 yield하면 충분하다(TestGenerateAuthGate 선례).
        async def _fake_session() -> Any:
            yield object()

        app.dependency_overrides[get_session] = _fake_session
        resp = TestClient(app).get("/v1/jobs/j1")
        assert resp.status_code == 401

    def test_valid_token_keeps_polling_behavior(self) -> None:
        """유효 토큰(실 mint/decode 왕복) + 소유자 본인 → 기존 폴링 동작(200 + 상태) 유지.

        SEC-27: `get_job`이 이제 `JobOwnership` PK lookup도 하므로(`get_current_user`와 같은
        세션 인스턴스 — FastAPI Depends 캐시) `_UserSession.get`이 모델별로 분기해 job "j1"의
        소유자를 `user`로 응답한다.
        """
        user = UserProfile(user_id=uuid.uuid4())
        app = self._app(statuses={"j1": JobStatus(job_id="j1", state="pending")})

        class _UserSession:
            """get_current_user·get_job이 부르는 get(model, pk) 모사(test_problems 패턴)."""

            async def get(self, model: Any, pk: Any) -> Any:
                if model is UserProfile:
                    return user if pk == user.user_id else None
                if model is JobOwnership:
                    return JobOwnership(job_id="j1", user_id=user.user_id) if pk == "j1" else None
                return None

        async def _fake_session() -> Any:
            yield _UserSession()

        app.dependency_overrides[get_session] = _fake_session
        app.dependency_overrides[get_settings] = lambda: self._JWT_SETTINGS
        token = create_access_token(user.user_id, settings=self._JWT_SETTINGS)
        resp = TestClient(app).get("/v1/jobs/j1", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] == "pending"


class TestDocsProdSurfaceGate:
    """SEC-24(원 SEC-18) 결함A — `/docs`·`/redoc`·`/openapi.json`은 프로덕션 추정에서만 비활성.

    `create_app`이 FastAPI 생성자에 `docs_url`/`redoc_url`/`openapi_url`을 넘기지 않아
    기본값(항상 활성)이 적용돼, 프로덕션에서도 API 스키마가 무인증 노출되고 있었다
    (`docs/reviews/functional_security_audit_2026-08-08.md` L1). `is_production_like`
    (실 OAuth kakao/naver 구성 여부, `config.py`)가 True일 때만 세 경로를 라우트 자체가
    없는 404로 봉인한다 — 개발·CI(이 저장소 CI에 kakao/naver 키 없음)는 항상 dev 분기라
    기존 200 동작이 완전 무회귀여야 한다(`test_reports.py::TestAppendOnly`가 이미
    `/openapi.json` 200을 전제).
    """

    def test_docs_enabled_in_dev(self) -> None:
        """kakao/naver 미설정(개발·CI 기본) → 기존 동작 무회귀: 셋 다 200."""
        get_settings.cache_clear()  # 환경 기본값(off) 확정 — 다른 테스트 env 누수 방지.
        try:
            app = create_app(
                provider=StubProvider(),
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                queue=StubQueue(),
            )
            client = TestClient(app)
            assert client.get("/docs").status_code == 200
            assert client.get("/redoc").status_code == 200
            assert client.get("/openapi.json").status_code == 200
        finally:
            get_settings.cache_clear()

    def test_docs_disabled_when_production_like(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """kakao 구성(프로덕션 추정) → 셋 다 404(라우트 자체가 등록되지 않음).

        env+cache_clear로 프로덕션 유사 `Settings`를 만든다 — `docs_url` 등은 FastAPI
        생성자에 한 번만 넘겨져 앱 구성 *시점*에 확정되므로(런타임 재설정 불가),
        `dependency_overrides`(요청 시점 Depends 대체)로는 이 결정을 되돌릴 수 없다.
        `get_settings()`가 실제로 kakao_configured=True인 인스턴스를 돌려주게 만들어야
        `create_app` 내부의 `production_like` 계산이 그 값을 본다.
        """
        monkeypatch.setenv("WHYMATH_KAKAO_CLIENT_ID", "prod-kakao-id")
        get_settings.cache_clear()
        try:
            app = create_app(
                provider=StubProvider(),
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                queue=StubQueue(),
            )
            client = TestClient(app)
            assert client.get("/docs").status_code == 404
            assert client.get("/redoc").status_code == 404
            assert client.get("/openapi.json").status_code == 404
        finally:
            get_settings.cache_clear()  # 다음 테스트로 kakao 구성 누수 방지.


class TestSecurityHeadersMiddleware:
    """SEC-26(48_보안 §P0 "CORS/보안 헤더 미들웨어" 갭) — 모든 응답에 보안 헤더가 얹힌다.

    HSTS·CSP는 `_prod_like`에서만(도크스 게이팅과 같은 축 재사용 — `TestDocsProdSurfaceGate`와
    동일한 kakao env 트리거 패턴). 나머지 3종은 항상.
    """

    def _client(self) -> TestClient:
        app = create_app(
            provider=StubProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=StubQueue(),
        )
        return TestClient(app)

    def test_always_on_headers_present_in_dev(self) -> None:
        """dev(kakao 미설정) → nosniff·DENY·referrer-policy는 있고 HSTS·CSP는 없다."""
        get_settings.cache_clear()
        try:
            resp = self._client().get("/health")
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["x-frame-options"] == "DENY"
            assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
            assert "strict-transport-security" not in {k.lower() for k in resp.headers}
            assert "content-security-policy" not in {k.lower() for k in resp.headers}
        finally:
            get_settings.cache_clear()

    def test_hsts_and_csp_present_when_production_like(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """kakao 구성(프로덕션 추정) → HSTS·CSP가 추가로 실린다."""
        monkeypatch.setenv("WHYMATH_KAKAO_CLIENT_ID", "prod-kakao-id")
        get_settings.cache_clear()
        try:
            resp = self._client().get("/health")
            assert resp.headers["strict-transport-security"] == (
                "max-age=63072000; includeSubDomains; preload"
            )
            assert resp.headers["content-security-policy"] == (
                "default-src 'none'; frame-ancestors 'none'"
            )
            # 상시 헤더도 여전히 실린다(축소가 아니라 추가).
            assert resp.headers["x-content-type-options"] == "nosniff"
        finally:
            get_settings.cache_clear()


class TestTrustedHostMiddleware:
    """SEC-26 — TrustedHostMiddleware. 미설정(기본) → `*`(무회귀). 설정 시 Host 헤더 검증."""

    def test_default_allows_any_host(self) -> None:
        """미설정 → 어떤 Host 헤더든 통과(현재 동작 무회귀)."""
        get_settings.cache_clear()
        try:
            app = create_app(
                provider=StubProvider(),
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                queue=StubQueue(),
            )
            resp = TestClient(app, base_url="http://anything.example.com").get("/health")
            assert resp.status_code == 200
        finally:
            get_settings.cache_clear()

    def test_configured_allowlist_rejects_mismatched_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WHYMATH_TRUSTED_HOSTS_ALLOWLIST 설정 시, 목록 밖 Host는 400으로 거부된다."""
        monkeypatch.setenv("WHYMATH_TRUSTED_HOSTS_ALLOWLIST", "api.whymath.kr")
        get_settings.cache_clear()
        try:
            app = create_app(
                provider=StubProvider(),
                cache=InMemoryCache(),
                trace=RecordingTraceSink(),
                queue=StubQueue(),
            )
            ok = TestClient(app, base_url="http://api.whymath.kr").get("/health")
            assert ok.status_code == 200
            rejected = TestClient(app, base_url="http://evil.example.com").get("/health")
            assert rejected.status_code == 400
        finally:
            get_settings.cache_clear()


class TestParseAppVersion:
    """`_parse_app_version` 순수 함수 단위테스트(OPS-17) — 외부 semver 라이브러리 없이 정수
    3튜플 비교로 버전을 가른다."""

    def test_parses_well_formed_version(self) -> None:
        from whymath_backend.app import _parse_app_version

        assert _parse_app_version("1.2.3") == (1, 2, 3)
        assert _parse_app_version(" 0.0.0 ") == (0, 0, 0)

    def test_rejects_malformed_versions(self) -> None:
        from whymath_backend.app import _parse_app_version

        assert _parse_app_version("1.2") is None  # 부분 누락
        assert _parse_app_version("1.2.3.4") is None  # 빌드번호 등 초과 부분
        assert _parse_app_version("1.2.x") is None  # 비정수 부분
        assert _parse_app_version("") is None  # 빈 문자열

    def test_tuple_ordering_is_numeric_not_lexicographic(self) -> None:
        """정수 튜플 비교라 "1.10.0"이 "1.2.0"보다 크다(문자열 비교였다면 반대)."""
        from whymath_backend.app import _parse_app_version

        low, high = _parse_app_version("0.9.9"), _parse_app_version("1.0.0")
        assert low is not None and high is not None
        assert low < high

        a, b = _parse_app_version("1.2.0"), _parse_app_version("1.10.0")
        assert a is not None and b is not None
        assert a < b


class TestAppVersionGate:
    """OPS-17 — X-App-Version 헤더 최소버전 게이트(app.py _service_metrics_middleware 좌석).

    GET /v1/jobs/{id}를 표적 엔드포인트로 쓴다 — ops 프로브 경로가 아니어서(게이트 대상)
    미들웨어 동작을 그대로 본다. SEC-24(원 SEC-15)로 이 라우트에 `CurrentUser` 게이트가 붙었으므로
    `_make_app`이 `get_current_user`를 고정 사용자로 오버라이드해 인증을 통과시킨다
    (이 클래스의 관심사는 미들웨어이지 인증이 아니다 — 인증 자체는 `TestJobsAuthGate`).
    """

    def _make_app(self, queue: Any) -> Any:
        app = create_app(
            provider=StubProvider(),
            cache=InMemoryCache(),
            trace=RecordingTraceSink(),
            queue=queue,
        )
        app.dependency_overrides[get_current_user] = lambda: _FAKE_USER

        # SEC-27: get_job이 session.get(JobOwnership, ...)을 부르므로, 이 클래스의 관심사
        # (미들웨어)와 무관한 실 DB 진입을 막기 위해 _FAKE_USER를 기본 소유자로 하는 가짜
        # 세션을 주입한다(_client()의 _FakeSession과 동형 — 여기선 클래스 헬퍼가 별도라 인라인).
        async def _fake_session() -> AsyncIterator[_FakeSession]:
            yield _FakeSession(default_owner=_FAKE_USER.user_id)

        app.dependency_overrides[get_session] = _fake_session
        return app

    def test_missing_header_passes_through_and_counts_unknown(self) -> None:
        """헤더 없음(배포 이전 구버전 클라) → 차단하지 않고(200) '미상' 카운터만 증가."""
        from whymath_backend.app import _VERSION_UNKNOWN_COUNT_KEY

        app = self._make_app(StubQueue(statuses={"j1": JobStatus(job_id="j1", state="pending")}))
        client = TestClient(app)
        before = getattr(app.state, _VERSION_UNKNOWN_COUNT_KEY)
        resp = client.get("/v1/jobs/j1")
        assert resp.status_code == 200
        assert getattr(app.state, _VERSION_UNKNOWN_COUNT_KEY) == before + 1

    def test_malformed_header_treated_as_unknown_not_blocked(self) -> None:
        """파싱 불가한 버전 문자열 → 침묵 실패 없이 '미상' 취급(차단하지 않음)."""
        from whymath_backend.app import _VERSION_UNKNOWN_COUNT_KEY

        app = self._make_app(StubQueue(statuses={"j2": JobStatus(job_id="j2", state="pending")}))
        client = TestClient(app)
        before = getattr(app.state, _VERSION_UNKNOWN_COUNT_KEY)
        resp = client.get("/v1/jobs/j2", headers={"X-App-Version": "not-a-version"})
        assert resp.status_code == 200
        assert getattr(app.state, _VERSION_UNKNOWN_COUNT_KEY) == before + 1

    def test_default_min_version_passes_any_well_formed_version(self) -> None:
        """기본 min_app_version=0.0.0 → 어떤 X.Y.Z 헤더든 통과(게이트 사실상 비활성)."""
        app = self._make_app(StubQueue(statuses={"j3": JobStatus(job_id="j3", state="pending")}))
        client = TestClient(app)
        resp = client.get("/v1/jobs/j3", headers={"X-App-Version": "0.0.1"})
        assert resp.status_code == 200

    def test_below_min_version_blocked_with_426(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """최소버전 상향 → 미달 클라는 426(401/404/422와 다른 전용 사유코드)."""
        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "1.0.0")
        get_settings.cache_clear()
        try:
            app = self._make_app(
                StubQueue(statuses={"j4": JobStatus(job_id="j4", state="pending")})
            )
            client = TestClient(app)
            resp = client.get("/v1/jobs/j4", headers={"X-App-Version": "0.9.9"})
            assert resp.status_code == 426
            assert "업데이트" in resp.json()["detail"]
        finally:
            get_settings.cache_clear()

    def test_at_or_above_min_version_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """최소버전과 같거나 위인 클라는 통과(경계값 정합)."""
        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "1.0.0")
        get_settings.cache_clear()
        try:
            app = self._make_app(
                StubQueue(statuses={"j5": JobStatus(job_id="j5", state="pending")})
            )
            client = TestClient(app)
            resp_eq = client.get("/v1/jobs/j5", headers={"X-App-Version": "1.0.0"})
            assert resp_eq.status_code == 200
            resp_above = client.get("/v1/jobs/j5", headers={"X-App-Version": "1.2.0"})
            assert resp_above.status_code == 200
        finally:
            get_settings.cache_clear()

    def test_bidirectional_threshold_flip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """변별력(acceptance ④) — 최소버전 상향→전용 문구(426), 하향→같은 클라 버전이 다시
        정상 복귀(200). 양방향 모두 실제로 *다른* 응답을 낸다."""
        app = self._make_app(StubQueue(statuses={"j6": JobStatus(job_id="j6", state="pending")}))
        client = TestClient(app)
        headers = {"X-App-Version": "1.0.0"}

        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "2.0.0")
        get_settings.cache_clear()
        blocked = client.get("/v1/jobs/j6", headers=headers)
        assert blocked.status_code == 426

        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "0.5.0")
        get_settings.cache_clear()
        restored = client.get("/v1/jobs/j6", headers=headers)
        assert restored.status_code == 200

        get_settings.cache_clear()

    def test_unparseable_min_app_version_fails_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """min_app_version 자체가 오구성(파싱 불가)이어도 전 클라를 막지 않는다(fail-open —
        서버 설정 오류로 전 클라를 차단하는 것이 더 나쁜 실패 모드)."""
        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "not-a-version")
        get_settings.cache_clear()
        try:
            app = self._make_app(
                StubQueue(statuses={"j7": JobStatus(job_id="j7", state="pending")})
            )
            client = TestClient(app)
            resp = client.get("/v1/jobs/j7", headers={"X-App-Version": "0.0.1"})
            assert resp.status_code == 200
        finally:
            get_settings.cache_clear()

    def test_ops_probe_paths_exempt_from_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """/health 등 ops 프로브 경로는 헤더 유무·최소버전 설정과 무관하게 게이트 대상이 아니다."""
        monkeypatch.setenv("WHYMATH_MIN_APP_VERSION", "99.0.0")
        get_settings.cache_clear()
        try:
            app = self._make_app(StubQueue())
            client = TestClient(app)
            resp = client.get("/health")
            assert resp.status_code == 200
        finally:
            get_settings.cache_clear()


def test_create_app_defaults_are_real_implementations() -> None:
    """기본 팩토리(주입 없음)는 CompositeProvider(Ollama+Anthropic, S5)
    +RedisCache(S2)+LangfuseSink(S3)+CeleryJobQueue(S4)를 단다.

    S2에서 기본 캐시가 InMemoryCache → RedisCache로, S3에서 기본 트레이스가
    RecordingTraceSink → LangfuseSink로, S4에서 기본 큐가 CeleryJobQueue로, S5에서 기본
    provider가 OllamaProvider → CompositeProvider(local=Ollama, cloud=Anthropic)로 바뀌었다.
    모두 *지연*이라 isinstance 확인만으로는 라이브 Redis·Langfuse·Celery broker·Anthropic
    키가 필요 없다(첫 사용 전엔 클라이언트/앱을 만들지 않음) → 이 단정은 hermetic하다.
    동작을 타는 테스트는 위 _client()가 가짜 의존성을 주입해 라이브 의존을 피한다.
    """
    from whymath_backend.app import _CACHE_KEY, _PROVIDER_KEY, _QUEUE_KEY, _TRACE_KEY
    from whymath_backend.l3.cache import RedisCache as _RC  # noqa: N814
    from whymath_backend.l3.providers.anthropic import AnthropicProvider as _AP  # noqa: N814
    from whymath_backend.l3.providers.composite import CompositeProvider as _CP  # noqa: N814
    from whymath_backend.l3.providers.ollama import OllamaProvider as _OP  # noqa: N814
    from whymath_backend.l3.queue import CeleryJobQueue as _CJQ  # noqa: N814
    from whymath_backend.l3.trace import LangfuseSink as _LFS  # noqa: N814

    app = create_app()
    composite = getattr(app.state, _PROVIDER_KEY)
    assert isinstance(composite, _CP)
    # 기본 복합 provider는 로컬=Ollama, 클라우드=Anthropic을 단다(S5 디스패치).
    assert isinstance(composite._local, _OP)
    assert isinstance(composite._cloud, _AP)
    assert isinstance(getattr(app.state, _CACHE_KEY), _RC)
    assert isinstance(getattr(app.state, _TRACE_KEY), _LFS)
    assert isinstance(getattr(app.state, _QUEUE_KEY), _CJQ)
    # CI hermetic 보강: 기본 LangfuseSink는 키 미설정 시 비활성(전송 X)이어야 한다.
    # (단, 환경에 WHYMATH_LANGFUSE_* 키가 실제로 있으면 활성일 수 있어 단정은 조건부.)
    from whymath_backend.config import Settings

    if not Settings().langfuse_configured:
        assert getattr(app.state, _TRACE_KEY).configured is False
