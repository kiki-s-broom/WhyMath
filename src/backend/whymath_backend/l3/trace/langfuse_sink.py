"""Langfuse 관측성 싱크 — interfaces.TraceSink 구현 (M1.2-live S3).

라우터의 `langfuse_fields()`가 만든 결정 태그 dict(03a §F.2)를 받아 Langfuse로
*기록*한다. 라우터는 dict만 만들고(전송 X), 실제 전송은 이 싱크의 책임이다 —
S1/S2가 세운 경계 분리(결정 로직 ↔ 영속/전송 계층)를 그대로 따른다.

설계 정본: `docs/architecture/03a_l3_router_design.md` §F.2(Langfuse 필드 표). 테스트
주입·지연 import 패턴은 providers/ollama.py(`_OllamaClient` 시임 + `_build_default_client`)·
cache/redis_cache.py(`_RedisClient` 시임)를 미러링한다.

────────────────────────────────────────────────────────────────────────────
관측성은 학생 생성을 *절대로* 깨뜨리지 않는다 (CLAUDE.md 의사결정 우선순위 #1 ≫ #6)
────────────────────────────────────────────────────────────────────────────
`record()`는 best-effort 부수효과다. 두 가지 안전장치를 둔다:
  1. *미설정이면 영구 no-op*: 공개키·시크릿키가 없으면(Settings.langfuse_configured=False)
     클라이언트를 만들지도, 네트워크를 타지도 않는다. CI·로컬은 키 없이 hermetic.
  2. *오류는 삼킨다*: Langfuse 호출이 예외를 던져도 `record()`는 전파하지 않는다.
     트레이싱 장애(네트워크·인증·라이브러리)가 학생의 한 번의 생성을 실패시키면 안
     된다 — 가용성(우선순위 #1)이 관측성(우선순위 #6)을 항상 이긴다.

시크릿 처리 (CLAUDE.md 보안 금기 "API 키·시크릿 코드 하드코딩 금지"): 시크릿 키는
Settings에서 `SecretStr`로 받아 *전송 클라이언트를 만드는 그 순간에만* 평문을 꺼내
쓴다. 이 모듈은 키를 로그·repr로 내보내지 않는다.

PII 경계 (03a §F.2·CLAUDE.md "미성년자 개인정보 외부 공유 금지"): 기록 필드의
`student_id_hash`는 *이미 해시된 값*이다(라우터가 직접 ID를 넣지 않음). 이 싱크는
받은 dict를 *그대로* 메타데이터로 전송할 뿐, 원시 학생 식별자를 만들거나 보내지
않는다.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast, runtime_checkable

from whymath_backend.config import Settings, get_settings
from whymath_backend.l3.interfaces import TrafficSurface, with_traffic_surface

logger = logging.getLogger("whymath.l3.trace")

# 결정 dict에서 *필터링 태그*로도 노출할 키 — 분포·KPI를 Langfuse UI에서 빠르게
# 추리기 위함(03a §F.2: cost_tier 80/18/2 분포·패밀리별·캐시 적중률). langfuse 3.x의
# create_event에는 v2식 `tags` 인자가 없어, 태그를 메타데이터 안에 'tags' 리스트로
# 함께 실어 보낸다(UI/스코어 필터에서 활용 가능). 값이 None인 필드는 태그에서 제외.
_TAG_FIELDS: tuple[str, ...] = (
    "cost_tier",
    "local_family",
    "local_model",
    "cache_hit",
    "content_source",  # 공급 경로(dsl_render/prompt_cache/generate·03c §4) — 비용 축 필터.
    # 런타임 LOCAL 강등 사유(ARCH-69) — 강등된 호출만 태그가 붙는다(값이 없으면 태그도 없어 정상
    # 호출은 노이즈가 되지 않는다). `local_degraded`는 True/False가 항상 실려 태그로 쓰면 전
    # 호출에 붙으므로 태그에서 뺐다(메타데이터에는 그대로 있다).
    "degrade_reason",
    # 표면 표지(OPS-105) — 서빙/저작/프로브를 Langfuse UI에서 바로 거른다. 표지가 없는 이벤트는
    # 태그도 없어(None 제외 규칙) '미표기'가 별도 집합으로 남는다.
    "traffic_surface",
)

# Langfuse 이벤트 이름 — L3 라우팅 결정 1건 = 이벤트 1건.
_EVENT_NAME = "l3_routing"


# ──────────────────────────────────────────────────────────────────────────
# Langfuse 클라이언트 추상화 (테스트 주입용) — ollama.py·redis_cache.py 시임 패턴.
# 실제 `langfuse.Langfuse`와 동형이지만 우리가 *실제로 쓰는* 메서드만 좁게 선언한다.
# 단위테스트는 가짜 클라이언트를 주입해 라이브러리·네트워크 없이 검증한다.
# ──────────────────────────────────────────────────────────────────────────
@runtime_checkable
class _LangfuseClient(Protocol):
    """langfuse.Langfuse의 최소 인터페이스 (구조적 타이핑).

    `langfuse.Langfuse`의 부분집합 — 우리는 단발 이벤트 기록만 한다. 반환값(이벤트
    핸들)은 라이브러리 버전별로 형태가 달라 `Any`로 두고 사용하지 않는다(기록 후
    버림 — 전송은 langfuse의 백그라운드 배치 익스포터가 best-effort로 처리).

    ⚠️ SDK 버전별 표면 차이(2026-07-16 실측): `create_event`는 **v3/v4에만** 존재하고
    v2(예: 2.60.10)는 `event(name=, metadata=, ...)`가 쓰기 API다 — v2에서 create_event
    호출은 매번 AttributeError였고 sink가 삼켜 *기록이 조용히 전멸*했다(Phaiakes9 실측).
    따라서 record()는 이 Protocol 표면을 직접 부르지 않고 getattr로 버전 적응한다.
    Protocol 자체는 v3식 create_event를 유지한다(테스트 가짜 클라이언트의 기준 표면).
    """

    def create_event(
        self,
        *,
        name: str,
        metadata: dict[str, object] | None = None,
        level: str | None = None,
    ) -> Any:
        """단발 관측 이벤트 생성 (langfuse create_event API의 부분집합)."""
        ...


def _build_default_client(settings: Settings) -> _LangfuseClient:
    """기본 langfuse.Langfuse 클라이언트 생성 (지연 import).

    `langfuse` 라이브러리가 없는 환경(또는 키 미설정 CI)에서도 모듈 import가 깨지지
    않도록 *호출 시점에만* import한다 (ollama.py·redis_cache.py `_build_default_client`
    패턴). 이 함수는 *설정이 완비됐을 때만* 호출된다(LangfuseSink._get_client가 보장).

    시크릿(SecretStr)은 *여기서, 클라이언트 생성 인자로 전달할 때만* 평문을 꺼낸다
    (`get_secret_value()`). 키를 로그로 남기지 않는다(CLAUDE.md 보안 금기). 생성자
    자체는 네트워크를 타지 않으며(전송은 백그라운드 배치), 도달 실패는 익스포터가
    내부적으로 흡수한다 — 그래도 우리는 record()를 try/except로 한 번 더 감싼다.
    """
    try:
        from langfuse import Langfuse
    except ImportError as exc:  # pragma: no cover — 환경 의존(라이브러리 미설치)
        raise RuntimeError(
            "langfuse Python 클라이언트가 설치되지 않았습니다. "
            "`pip install langfuse` 후 다시 시도하세요."
        ) from exc
    # cast 사유: langfuse가 제공하는 정밀 스텁(create_event의 풍부한 overload·반환
    # 타입 LangfuseEvent)은 우리의 좁은 구조적 시임 `_LangfuseClient`와 형태가 어긋난다.
    # 우리가 실제로 쓰는 호출 규약(create_event(name=,metadata=,level=))은 Langfuse가
    # 런타임에 충족하므로 스텁 정밀도 차이만 cast로 좁힌다(타입 무시 X — ollama.py가
    # AsyncClient를, redis_cache.py가 Redis를 다룬 방식과 동일).
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
    )
    return cast(_LangfuseClient, client)


def _to_metadata(fields: dict[str, object]) -> dict[str, object]:
    """결정 필드 dict → Langfuse 이벤트 메타데이터로 변환.

    필드를 *그대로* 메타데이터로 싣고(전 필드 보존 — 03a §F.2 표 전체), 추가로
    `_TAG_FIELDS` 중 값이 있는 것만 'tags' 리스트(`"key:value"` 문자열)로 합성해
    UI 필터링을 돕는다. 원본 필드는 손대지 않는다(얕은 복사).

    `student_id_hash`는 *이미 해시*이므로 그대로 통과시킨다(원시 ID 생성·전송 안 함).
    """
    metadata: dict[str, object] = dict(fields)  # 얕은 복사 — 호출자 dict 불변
    tags: list[str] = []
    for key in _TAG_FIELDS:
        value = fields.get(key)
        if value is None:
            continue  # 미적용 축(클라우드의 local_family 등)은 태그에서 제외
        tags.append(f"{key}:{value}")
    if tags:
        metadata["tags"] = tags
    return metadata


class LangfuseSink:
    """Langfuse 기반 관측성 싱크 — interfaces.TraceSink 충족.

    파이프라인은 `record(fields)`만 호출하고(03a §F.2), 이 싱크는 그 dict를 Langfuse
    이벤트로 전송한다. 두 가지 불변식(모듈 docstring 참조)을 지킨다:
      - 미설정(키 없음) → 영구 no-op(클라이언트 생성·네트워크 없음).
      - 호출 오류 → 삼킴(학생 생성 절대 미차단).

    클라이언트는 지연 생성(lazy)·주입 가능(injectable)하다 — 테스트는 가짜 클라이언트를
    `client=`로 넣고, 프로덕션은 키가 설정돼 있을 때 첫 record()에서 기본 Langfuse
    클라이언트를 생성한다(생성자/`create_app()`만으로는 키·네트워크가 필요 없도록).
    """

    def __init__(
        self,
        *,
        client: _LangfuseClient | None = None,
        settings: Settings | None = None,
        traffic_surface: TrafficSurface | None = None,
    ) -> None:
        # 주입된 클라이언트가 있으면 그것을 쓰고, 없으면 설정 완비 시 첫 사용에 지연 생성.
        self._client = client
        self._settings = settings
        # 이 싱크가 낳는 기록의 기본 표면(OPS-105). None(기본)이면 표지를 싣지 않는다 — 기존
        # 호출부는 비트동일. 기록 dict에 이미 표지가 있으면 그것이 이긴다(`with_traffic_surface`).
        self._traffic_surface = traffic_surface

    @property
    def traffic_surface(self) -> TrafficSurface | None:
        """이 싱크가 기록에 기본으로 싣는 표면(없으면 None)."""
        return self._traffic_surface

    @property
    def _resolved_settings(self) -> Settings:
        """설정 지연 해석 — 주입 우선, 없으면 캐시된 전역 Settings."""
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def configured(self) -> bool:
        """전송 가능 여부 — 키가 완비됐거나(설정) 클라이언트가 주입됐는가.

        주입된 클라이언트가 있으면(테스트·DI) 키 설정과 무관하게 활성으로 본다.
        그 외에는 Settings.langfuse_configured(공개키·시크릿키 둘 다 존재)를 따른다.
        네트워크를 타지 않고 *내성(introspection)만* 한다 — 기본 구현 단정 테스트·
        향후 레디니스가 연결 없이 활성 여부를 물을 수 있게 한다.
        """
        if self._client is not None:
            return True
        return self._resolved_settings.langfuse_configured

    # `enabled`는 `configured`의 별칭 — 호출처 가독성용(둘 다 "전송될 것인가"를 뜻함).
    enabled = configured

    def _get_client(self) -> _LangfuseClient | None:
        """클라이언트 지연 해석 — 주입 우선, 미설정이면 None(no-op 신호).

        주입 클라이언트 > (설정 완비 시) 기본 Langfuse 생성 > (미설정) None.
        None을 돌려주면 record()는 아무것도 하지 않는다(영구 no-op).
        """
        if self._client is not None:
            return self._client
        if not self._resolved_settings.langfuse_configured:
            return None  # 키 미설정 → 영구 no-op
        self._client = _build_default_client(self._resolved_settings)
        return self._client

    def record(self, fields: dict[str, object]) -> None:
        """라우팅 결정 태그 dict를 Langfuse 이벤트로 기록 (TraceSink 구현).

        best-effort: 미설정이면 조용히 no-op, 호출 오류는 삼킨다(전파 금지). 어떤
        경우에도 예외를 던지지 않아 상위 생성 파이프라인을 깨지 않는다(모듈 docstring
        의 never-break 보장 — CLAUDE.md 우선순위 #1 ≫ #6).
        """
        client = self._get_client()
        if client is None:
            return  # 미설정 → no-op (네트워크·클라이언트 없음)
        if self._traffic_surface is not None:
            fields = with_traffic_surface(fields, self._traffic_surface)
        try:
            # SDK 버전 적응 쓰기(2026-07-16 실측): v3/v4=create_event, v2=event.
            # v2(2.60.10)에는 create_event가 없어 종전 고정 호출은 매 record가
            # AttributeError로 전멸했다 — getattr로 있는 표면을 쓴다.
            create_event = getattr(client, "create_event", None)
            if callable(create_event):
                create_event(
                    name=_EVENT_NAME,
                    metadata=_to_metadata(fields),
                    level="DEFAULT",
                )
            else:
                # langfuse v2 폴백 — event(name=, metadata=). level은 v2 기본값 사용.
                cast(Any, client).event(name=_EVENT_NAME, metadata=_to_metadata(fields))
        except Exception as exc:  # noqa: BLE001 — 관측성 장애가 학생 생성을 깨면 안 됨
            # 시크릿·PII 없이 *예외 타입명만* 경고 로그(필드·키 값은 남기지 않는다).
            # 타입명이 없던 종전엔 v2 AttributeError 전멸이 무증상이었다(침묵 실패 방지).
            logger.warning(
                "Langfuse 기록 실패(%s) — 무시하고 계속(생성 비차단)",
                type(exc).__name__,
                exc_info=False,
            )

    def flush(self) -> None:
        """버퍼된 Langfuse 이벤트를 *즉시* 강제 전송한다 (짧게 끝나는 프로세스용).

        langfuse SDK는 create_event를 백그라운드 배치로 전송하므로, 프로세스가 곧바로
        종료하는 실행(예: CLI 프리플라이트 1콜)에서는 배치가 나가기 전에 죽어 이벤트가
        유실될 수 있다. `flush()`는 그 배치를 지금 밀어내 전송을 확정한다. *서버 상시
        실행 경로는 이 메서드를 호출하지 않으므로 기존 동작은 완전히 무변경*이다.

        record()와 *같은 안전 방침*을 그대로 따른다(모듈 docstring never-break 보장):
          - 미설정(키 없음) → no-op(_get_client가 None). 네트워크·클라이언트 없음.
          - 클라이언트가 flush를 노출하지 않으면(테스트 가짜·구버전) → no-op.
          - 호출 오류 → 삼킨다(전파 금지). 관측성 장애가 흐름을 깨면 안 된다(#1 ≫ #6).

        `_LangfuseClient` 시임에 flush를 넣지 않는 이유: 그 Protocol은 runtime_checkable로
        가짜 클라이언트 위생 테스트(`isinstance(fake, _LangfuseClient)`)에 쓰인다 —
        flush를 요구하면 flush 없는 가짜가 시임을 깨므로, 여기서 `getattr`로 *있으면
        호출*하는 선택적 능력으로 다룬다(mypy strict 안전: Any 콜러블 가드).
        """
        client = self._get_client()
        if client is None:
            return  # 미설정 → no-op
        flush = getattr(client, "flush", None)
        if not callable(flush):
            return  # flush 미노출(가짜·구버전) → no-op
        try:
            flush()
        except (
            Exception
        ) as exc:  # noqa: BLE001 — flush 실패도 흐름을 깨면 안 됨(record와 동일 방침)
            logger.warning(
                "Langfuse flush 실패(%s) — 무시하고 계속(비차단)",
                type(exc).__name__,
                exc_info=False,
            )
