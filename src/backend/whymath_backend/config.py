"""백엔드 환경설정 — pydantic-settings 기반 (CLAUDE.md 보안 금기: 시크릿 하드코딩 금지).

모든 설정은 *환경변수*로 주입한다. 이 파일에는 호스트·시크릿을 하드코딩하지 않으며
기본값은 *로컬 개발용 무해 디폴트*(예: Ollama 로컬 데몬 주소)만 둔다.

범위 메모 (M1.2-live): S1은 L3 라우터 ↔ 실제 Ollama 결선 + FastAPI 앱을 다뤘고,
S2가 Redis 캐시 설정(redis_url)을 추가했으며, S3가 Langfuse 관측성 설정(공개키·
시크릿키·호스트)을 추가했고, S4가 QUALITY(27b) 비동기 큐(Celery, broker=Redis)
설정을 추가했으며, S5가 클라우드 LLM(Anthropic Claude — API 키·모델 ID·타임아웃)
설정을 추가한다(03a §H 후속 4 클라우드 연동). DB 설정은 후속 슬라이스에서 추가한다 —
여기서는 가동 중인 슬라이스에 필요한 최소 설정만 노출한다.

시크릿 처리 (CLAUDE.md 보안 금기 "API 키·시크릿 코드 하드코딩 금지"): Langfuse
시크릿 키는 `SecretStr`로 받아 *로그·repr에 평문 노출을 차단*한다. 공개키·시크릿키는
*기본값을 두지 않는다*(빈 문자열 = "미설정") — 키가 없으면 관측성은 영구 no-op으로
스스로 비활성된다(LangfuseSink). 호스트는 무해한 공개 디폴트(cloud.langfuse.com)를
둘 수 있다(시크릿 아님).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ──────────────────────────────────────────────────────────────────────────
# 클라우드 좌석(cloud seat) 리터럴 — **좌석 어휘의 단일 진실 원천**.
#
# `Settings.cloud_provider`가 이 별칭을 쓰고, 단가표(`l3.router`)·좌석→핀 매핑
# (`l3.providers.factory.cloud_model_pins`)이 같은 별칭을 읽는다. 새 enum을 세우지
# 않는 이유는 그 순간 좌석 어휘가 둘이 되기 때문이다 — `ARCH-58`이 상환한 사고가
# 정확히 "좌석은 셀렉터로 바뀌는데 기록은 다른 곳의 사본을 봤다"는 형태였다.
#
# 좌석을 추가하려면 여기 한 곳만 고치면 되고, 그 순간 단가표의 (티어, 좌석) 조합이
# 비어서 비용이 None(미측정)으로 떨어진다 — 표를 채우라는 신호가 자동으로 뜬다.
# ──────────────────────────────────────────────────────────────────────────
CloudSeat = Literal["anthropic", "openrouter", "deepseek"]
"""클라우드 좌석 이름 — `cloud_provider` 셀렉터가 고르는 제공자 3종."""


class Settings(BaseSettings):
    """환경변수 기반 설정 — `WHYMATH_` 접두사 (예: `WHYMATH_OLLAMA_HOST`).

    pydantic-settings가 환경변수·`.env`에서 값을 읽는다. 시크릿은 코드가 아니라
    배포 환경의 환경변수/시크릿 매니저로 주입한다 (CLAUDE.md 보안 금기).
    """

    model_config = SettingsConfigDict(
        env_prefix="WHYMATH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 다른 슬라이스(DB·결제 등) 환경변수와 공존 — 모르는 키 무시
        # ARCH-49: 일부 키는 `WHYMATH_` 접두 이름과 **벤더 표준 이름**을 둘 다 읽어야 해서
        # `validation_alias=AliasChoices(...)`를 쓴다(예 `DEEPSEEK_API_KEY` — Phaiakes9
        # User 환경변수에 그 이름으로 이미 등록돼 있다). alias가 붙은 필드는 기본적으로
        # **필드 이름으로 생성할 수 없게** 되는데, 이 클래스는 테스트·DI가
        # `Settings(deepseek_api_key=...)` 형태로 생성하므로 필드 이름 경로를 함께 연다.
        # (mypy `pydantic.mypy` 플러그인의 `warn_required_dynamic_aliases`도 이것을 요구한다.)
        # alias가 없는 기존 필드의 동작은 바뀌지 않는다 — 원래 필드 이름으로만 생성한다.
        populate_by_name=True,
    )

    # ── Ollama (로컬 LLM, Phaiakes9) ──
    ollama_host: str = Field(
        default="http://127.0.0.1:11434",
        description=(
            "Ollama 데몬 주소. 로컬 개발 기본값은 무해한 로컬 루프백. "
            "프로덕션(Phaiakes9)은 환경변수 WHYMATH_OLLAMA_HOST로 주입 (시크릿 아님)"
        ),
    )
    ollama_request_timeout_s: float = Field(
        default=30.0,
        ge=0.0,
        description=(
            "Ollama 단일 호출 타임아웃(초). QUALITY(27b, p50≈14s)는 동기 호출하지 "
            "않으므로(03a §D.3) 이 타임아웃은 FAST/MID 동기 경로 기준 (S1 범위)"
        ),
    )

    # ── 영속 DB (PostgreSQL 16 + asyncpg, 영속 슬라이스) ──
    # 영속 레이어(SQLAlchemy 2.0 async + alembic)가 읽는 연결 URL. redis_url과 동일한
    # plain-str + WHYMATH_ env 오버라이드 패턴 — 로컬 기본값은 자격증명 없는 무해 디폴트라
    # 시크릿이 아니다(CLAUDE.md 보안 금기 비저촉). 프로덕션 자격증명은 코드 밖 환경변수로만.
    database_url: str = Field(
        default="postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",
        description=(
            "PostgreSQL 연결 URL(asyncpg 드라이버, async). 로컬 개발 기본값은 자격증명 없는 "
            "무해한 로컬 루프백(시크릿 아님). 프로덕션(Phaiakes9)은 WHYMATH_DATABASE_URL로 "
            "주입하며 자격증명을 포함할 수 있다(→ 코드 밖). 풀 설정(pool_size 등)은 PoC 범위 밖."
        ),
    )
    # 연결 풀 비활성(NullPool). 기본 False(프로덕션은 풀 사용). True면 매 체크아웃마다 새
    # asyncpg 연결을 만들고 닫는다 — *테스트(통합) 환경*에서 모듈 전역 엔진이 여러 asyncio
    # 이벤트 루프에 걸쳐 재사용될 때 발생하는 "another operation is in progress"(죽은 루프에
    # 바인딩된 풀 연결 재사용)를 회피. CI 통합테스트가 WHYMATH_DB_DISABLE_POOL=1로 켠다.
    db_disable_pool: bool = Field(
        default=False,
        description=(
            "True면 NullPool(연결 풀 비활성·매 체크아웃 새 연결). 통합테스트가 다중 이벤트 "
            "루프에서 전역 엔진을 재사용할 때의 asyncpg 루프 바인딩 충돌 회피용. 기본 False."
        ),
    )

    # ── 응답 캐시 (Redis, S2부터 실제 만료 적용) ──
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        description=(
            "Redis 연결 URL. 로컬 개발 기본값은 무해한 로컬 루프백 DB 0. "
            "프로덕션(Phaiakes9)은 환경변수 WHYMATH_REDIS_URL로 주입. 시크릿 아님 — "
            "인증이 필요하면 URL에 환경변수로 자격증명을 담는다(코드 하드코딩 금지)"
        ),
    )
    redis_socket_timeout_s: float = Field(
        default=2.0,
        gt=0,
        description=(
            "Redis 소켓 타임아웃(초) — 응답 대기(socket_timeout)·연결 수립"
            "(socket_connect_timeout)에 같은 값을 건다(OPS-05). 무응답 Redis(패킷 블랙홀·"
            "방화벽 drop)에서 캐시 호출이 장시간 매달려 asyncio 워커가 고갈되는 것을 막는다 "
            "— 연결 거부(즉시 예외)보다 나쁜 실패 양상이다. 기본 2.0초 근거: ①정상 Redis"
            "(동일 호스트·LAN) 응답은 보통 <5ms라 400배 여유 — 건강한 Redis를 오탐 차단하지 "
            "않는다 ②학생 대면 경로 p50 목표가 2초라 캐시 한 번의 정체가 요청 예산 전체를 "
            "먹지 않는다 ③타임아웃은 예외로 드러나 RedisCache가 캐시 미스로 강등하므로 "
            "요청은 재생성으로 완주한다(장애 전파 아님). 명시 지정 이유: redis-py는 값을 "
            "주지 않으면 라이브러리 버전 기본값에 종속된다(설치본 8.0.1 실측 5초)"
        ),
    )
    cache_ttl_s: int = Field(
        default=3600,
        ge=0,
        description=(
            "응답 캐시 TTL(초). S2 RedisCache가 SET ... EX로 실제 만료 적용(03a §F.1). "
            "0이면 RedisCache는 만료 없이 저장(무기한 폴백 — redis가 EX 0를 거부하므로)"
        ),
    )

    l3_shadow_validation_enabled: bool = Field(
        default=True,
        description=(
            "L3 런타임 shadow 검증(결정론 관계 검증·slice 40~47) 활성 여부. True(기본)면 "
            "/v1/generate 동기 경로와 QUALITY 워커가 생성물의 거짓 수치 관계를 비차단으로 "
            "관측(신호 기록·로그). False면 끈다(SymPy 검증 비용 제거·디버깅). 비차단이라 "
            "반환 텍스트·캐시 동작은 어느 쪽이든 불변 — 관측 신호 유무만 달라진다."
        ),
    )

    l3_skip_cache_on_signal: bool = Field(
        default=False,
        description=(
            "shadow 검증이 환각 신호를 낸 /v1/generate 미스 생성물을 캐시에 적재하지 않을지 "
            "(slice 42 캐시 위생). True면 증명된 거짓 수치 관계 출력을 *영속화하지 않는다* "
            "(다음 동일 요청은 재생성). False(기본)면 기존 동작(항상 적재). `l3_shadow_"
            "validation_enabled`가 False면 신호 자체가 없어 무효과. 반환 텍스트는 불변 "
            "(캐시만 건너뜀)·정확성 무해(false positive 시 재생성 비용만)."
        ),
    )

    l4_step_shadow_enabled: bool = Field(
        default=False,
        description=(
            "L4 중간 step 등가성 shadow 관측(slice 62~63) 활성 여부. True면 /v1/coach 경로가 학생 "
            "풀이의 *단계-비보존*(인접 변환이 해집합을 안 지킴)을 `detect_step_breaks`로 검출해 "
            "logger.info로 관측한다. **student-facing 미노출**(SolutionCoaching·HTTP 응답 불변) — "
            "순차유도 오류(A)와 변수재사용(B)을 구문 분리 못 해 노이즈가 섞이므로 학생엔 안 보이고 "
            "진단 데이터(향후 L7·교사 대시보드)로만 쓴다. **False(기본·opt-in)**: (A)/(B) 노이즈가 "
            "구조적·sink 미구현이라 보수적 off. WHYMATH_L4_STEP_SHADOW_ENABLED=true로 켠다."
        ),
    )

    wh1_harness_shadow_enabled: bool = Field(
        default=False,
        description=(
            "WH-1 튜터링 하네스(`LLMTutorPolicy`·S1-a) *shadow 관측*(비노출·비블로킹)을 켤지"
            "(S1-b·04a '측정 없는 도입 없음'). **False(기본·opt-in)·학생 응답 불변**: 노출은 "
            "*절대* 기존 결정론 경로(`_build_response_payload`) 그대로이고, True일 때만 coach "
            "세션 엔드포인트가 하네스를 *비차단*(_spawn=create_task)으로 *병렬* 실행해 '하네스가 "
            "어떤 도구를 골랐는지·verify 판정이 무엇인지'만 서버 로그로 관측한다. 목적은 실 "
            "트래픽에서 하네스 거동을 *측정*한 뒤(후속) verify 게이트를 primary로 승격하기 위함 — "
            "지금은 학생-대면 동작 변화 0·완전 되돌리기 가능(플래그 OFF면 spawn 0·비트동일). "
            "하네스는 응답 경로를 *지연시키지 않는다*(fire-and-forget·coach는 await 안 함)·**DB "
            "영속 0**(shadow는 로그만·순수 한 턴 `run_tutoring_turn`). 레코드엔 *학생 원문·풀이 "
            "단계·발화·정답 미저장*(미성년 PII — status·action_type·verify verdict·도구 수·가설 수·"
            "식별자 id만). `l4_step_shadow_enabled`·`misconception_judge_shadow` 미러. "
            "WHYMATH_WH1_HARNESS_SHADOW_ENABLED=true로 켠다(측정용·후속)."
        ),
    )

    wh1_primary_enabled: bool = Field(
        default=True,
        description=(
            "WH-1 튜터링 하네스를 학생-대면 *primary*로 승격(flip·S1-11·2026-07-20 사인오프)할지. "
            "**True(기본·2026-07-20 GA)** — 실기기 확인(코치 발화 라이브)+in-process 측정"
            "(`scripts/demo/wh1_primary_probe.py` 3케이스 LLM 개입 실패 0·verdict 정상)으로 canary "
            "졸업. 명시적으로 False면 기존 결정론 Polya 템플릿 경로와 비트동일"
            "(회귀 0·비상 킬스위치). True면 coach *세션/턴*(`/v1/coach/sessions`(+"
            "`/turns`))의 학생-대면 발화(`decision.prompt`·AI 턴 content)가 WH-1 하네스"
            "(`LLMTutorPolicy`→`run_tutoring_turn`) 발화로 대체된다 — 발화는 하네스 verify 의무"
            "(§3.1)·정답 억제 백스톱(§3.4)을 통과하고 L4 톤필터(`filter_tone`)를 거친 것만 "
            "노출된다(검증 게이트 유지). LLM 실패·타임아웃·예산 소진 시 결정론 템플릿으로 안전 "
            "폴백(가용성 — 앱은 죽지 않는다·폴백은 예외 타입명 로그·침묵 실패 금지). shadow 관측 "
            "레코드는 primary 경로에서도 계속 emit(원장 축적 연속·`primary=True` 표식)되며, "
            "primary on이면 별도 shadow spawn은 하지 않는다(이중 LLM 호출 회피). stateless "
            "`/v1/coach`는 불변(결정론 유지·DB 무접근이라 가설·웜스타트 없음). "
            "WHYMATH_WH1_PRIMARY_ENABLED=false로 비상 시 되돌린다(킬스위치)."
        ),
    )

    wh1_primary_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        description=(
            "WH-1 primary(flip) 하네스 한 턴의 총 시간 예산(초). 초과 시 `asyncio.wait_for`가 "
            "끊고 결정론 템플릿으로 폴백한다(TimeoutError 타입명 로그·앱은 죽지 않는다). 04a "
            "§8.3 '풀 루프 턴 2~5초+' 추정 위에 안전 여유를 둔 기본값 — 실측 후 튜닝(fast path "
            "§5.3 결선은 후속). WHYMATH_WH1_PRIMARY_TIMEOUT_SECONDS로 조정."
        ),
    )

    wh1_prose_rephrase_enabled: bool = Field(
        default=False,
        description=(
            "WH-1 파생 템플릿 발화를 정답-안전 rephrase로 LLM 문맥 프로즈화할지(S4-04). "
            "**False(기본·canary)** — OFF면 프로즈 계층 미호출로 기존 경로와 비트동일(회귀 0). "
            "True면 primary 러너가 파생 템플릿(중립 유도·격려 폴백 — 정확 일치 화이트리스트)"
            "만 LLM으로 문맥화하되 결정론 게이트(등호·숫자·학생 풀이 유입·'정답' 키워드·길이) "
            "통과분만 노출하고(실패=원 템플릿 fail-closed), correct 턴 정책 자유발화에는 외래 "
            "등식·위생 게이트를 건다(실패=결정론 폴백). verify 의무·정답 억제 백스톱·톤필터는 "
            "무변경 — 프로즈는 그 *뒤*에 얹힌 계층(harness/wh1_prose.py). GA flip(기본 True)은 "
            "결함주입 측정(coach_prose_leak_eval exit 0)+실기기 확인 후 별도 커밋(S1-11 선례). "
            "WHYMATH_WH1_PROSE_REPHRASE_ENABLED=false 킬스위치."
        ),
    )

    wh1_prose_timeout_seconds: float = Field(
        default=3.0,
        gt=0.0,
        description=(
            "코치 프로즈 rephrase LLM 호출 1건의 시간 예산(초). 초과 시 원 템플릿으로 즉시 "
            "폴백한다(TimeoutError 타입명 로그·fail-closed — 발화는 이미 안전한 템플릿이라 "
            "품질만 잃고 안전은 불변). primary 15s 예산 *바깥*의 추가 예산이므로 워스트 케이스 "
            "턴 지연은 합산 ~18s(파생 템플릿 턴만·correct 턴은 rephrase 호출 0). "
            "WHYMATH_WH1_PROSE_TIMEOUT_SECONDS로 조정."
        ),
    )

    pedagogy_pack_prompt_enabled: bool = Field(
        default=True,
        description=(
            "교수법 팩(PedagogyPack) 4계층 발문 조립기를 stateless "
            "`/v1/coach`(`PolyaCoach.decide`) 경로에 얹을지(PED-01 슬라이스 ③). "
            "**True(기본·2026-07-27 GA)** — 호출자가 `decide(pack=...)`로 팩을 명시 주입한 "
            "경우에만 base_system 위에 팩 socratic_prompt(`{domain_example}` 치환)·오개념·학습자 "
            "상태를 4계층으로 조립해 `PedagogyDecision.system`을 대체한다. 팩 미주입(pack=None) "
            "시에는 플래그와 무관하게 base_system 무변경(옵트인·역호환) — 현재 팩 주입은 "
            "`_pack_for`가 파일럿 목표 개념에 매핑된 문항에서만 팩을 해석하므로 blast radius가 "
            "파일럿 단원으로 한정된다. OFF(킬스위치)면 팩 조립기 미호출로 기존 발문 경로와 "
            "비트동일(`decision.system`은 `_BASE_SYSTEM` 그대로). WH-1 라이브 측정 경로(`wh1_*`)· "
            "톤필터는 무변경. GA 전환 근거: 결함주입 측정(pedagogy_pack_fidelity_eval exit 0·CI "
            "상시) 통과 + Kiki 사인오프(2026-07-27·blast radius 파일럿 1단원 한정 간이 갈음). "
            "주의: forbidden_modes *문면* 가드(`mode_guard`)는 이 플래그와 무관하다 — "
            'PED-16(2026-08-10)이 "WH-1 루프가 PedagogyPack을 참조하지 않는다"를 근거로 '
            "by-design 미배선을 확정했으나, PED-23(회수)이 coach→WH-1 러너 팩 thread로 그 선결 "
            "조건을 충족시켜 톤필터 직전 런타임 배선을 복원했다(`mode_guard_runtime_enabled` "
            "옵트인·기본 OFF — 그 플래그의 description 참조). 오프라인 결함주입 측정"
            "(`pedagogy_pack_fidelity_eval`)은 그대로 CI 상시다. 사전 가드(`runtime_selector`의 "
            "`forbids_worked_first` 선택 시점 강등)도 불변으로 유지된다. "
            "WHYMATH_PEDAGOGY_PACK_PROMPT_ENABLED=false 킬스위치."
        ),
    )

    mode_guard_runtime_enabled: bool = Field(
        default=False,
        description=(
            "교수법 팩 forbidden_modes 런타임 가드(`mode_guard.check_forbidden_modes`)를 WH-1 "
            "primary 학생-대면 발화 경로의 톤필터 *앞*에 걸지(PED-23 회수 — 정본 "
            "docs/architecture/04e_pedagogy_strategy_catalog.md §9). **False(기본·옵트인)** — "
            "OFF면 가드 블록 미실행으로 기존 서빙 경로와 비트동일(회귀 0·킬스위치). ON이면 팩이 "
            "해석된 턴에서 발화가 팩 금지 모드를 위반할 때 그 발화를 학생에게 보내지 않고 "
            "안전한 소크라테스식 재질문(결정론 템플릿·`fallback_reply_for`)으로 대체하며 "
            "reason_code(위반 모드 토큰)를 구조화 WARNING 로그로 남긴다(fail-closed·04d §2.2 "
            "SOCRATIC 강등 선례 미러). 팩 부재(None)면 가드는 통과(팩 없으면 forbidden_modes도 "
            "없음). 결정론 폴백·검증 게이트·톤필터는 무변경 — 가드는 그 사슬 *안*(프로즈 뒤· "
            '톤필터 앞)에 얹힌 계층이다. 경위: PED-16(2026-08-10)이 "WH-1 루프가 PedagogyPack을 '
            '참조하지 않는다"를 근거로 by-design 미배선을 확정했으나, 격리 브랜치의 원 구현'
            "(PED-07)이 이미 coach→러너 팩 thread로 그 선결 조건을 충족해 둔 상태였다 — PED-23이 "
            "그 capability를 현행 위에 재적용했다(옵트인 캔어리). GA flip(기본 True)은 결함주입 "
            "측정(pedagogy_pack_fidelity_eval exit 0 상시)+사인오프 후 별도 커밋(팩 GA 선례). "
            "WHYMATH_MODE_GUARD_RUNTIME_ENABLED=false 킬스위치."
        ),
    )

    pedagogy_catalog_filter_enabled: bool = Field(
        default=False,
        description=(
            "교수전략 카탈로그(PED-05·PED-22 회수)의 적합성 필드(target_grade_bands·"
            "difficulty_range·target_k_types)를 `runtime_selector.select()`의 **후보 필터**로 "
            "소비할지(PED-23 회수 — 정본 docs/architecture/04e_pedagogy_strategy_catalog.md §4). "
            "**False(기본·옵트인)** — OFF면 카탈로그 미조회·규칙표 v1(R1~R5) 원판정 그대로(기존 "
            "선택 경로와 비트동일·킬스위치). ON이면 규칙표 적용 전에 후보 집합을 카탈로그 적합성"
            "으로 **좁히기만** 한다: 좁힌 결과가 공집합이거나 규칙표가 후보를 소진하면 필터를 "
            "무시하고 원판정으로 폴백하며 reason_code(CATALOG_FILTER_EMPTY/EXHAUSTED)를 구조화 "
            "로그로 남긴다(조용한 실패 금지). 카탈로그는 select 전용 — `gate()`는 플래그와 "
            "무관하게 카탈로그를 읽지 않는다(효과≤허용 우회 차단·04e §4 불변식 ②·테스트 동결). "
            "GA flip(기본 True)은 측정+사인오프 후 별도 커밋(mode_guard 캔어리 선례). "
            "WHYMATH_PEDAGOGY_CATALOG_FILTER_ENABLED=false 킬스위치."
        ),
    )

    pedagogy_strategy_card_enabled: bool = Field(
        default=False,
        description=(
            "`supply()` 생성 폴백의 system 프롬프트에 선택된 교수전략의 카탈로그 카드"
            "(name_ko·description·research_basis 요약 1줄 — attention 절약)를 얹을지(PED-23 "
            "회수 — 정본 04e §3.2 소비처 지정표). **False(기본·옵트인)** — OFF면 카탈로그 "
            "미조회·system 무변경으로 기존 생성 경로와 비트동일(프롬프트-해시 캐시 키도 불변·"
            "킬스위치). ON이면 `decide()`가 고른(게이트 통과 후) 전략의 카드를 조회해 "
            "`attach_strategy_card`로 system 뒤에 1블록을 덧붙인다 — 카드 조회 실패는 예외 "
            "타입명을 WARNING 로그로 남기고 무카드로 진행한다(best-effort 계층·생성 자체를 "
            "막지 않음·침묵 실패 금지). 렌더 경로(dsl_render)는 프롬프트가 없어 무관. "
            "GA flip(기본 True)은 측정+사인오프 후 별도 커밋(팩 GA 선례). "
            "WHYMATH_PEDAGOGY_STRATEGY_CARD_ENABLED=false 킬스위치."
        ),
    )

    l4_server_mastery_enabled: bool = Field(
        default=True,
        description=(
            "L4 코칭(세션/턴)이 서버 L2 저장소(ConceptMasteryHistory)의 *실제* 숙달도를 "
            "클라이언트 전송 bkt_mastery보다 우선해 쓸지(slice 70·진짜 L2↔L4 루프). "
            "True(기본·정식기능)면 /v1/coach/sessions·turns가 문항 PRIMARY 개념의 현재 "
            "숙달도를 조회해 hint level 보수화·LTHC 조정에 반영한다(클라 전송값 변조·단절 제거). "
            "명시 mastery_level(라벨)은 여전히 최우선. **student-facing 미노출**(결정에만 쓰고 "
            "decision/CoachResponse 불변). stateless /v1/coach는 DB가 없어 무관(클라값). "
            "False면 기존 동작(클라 bkt만). WHYMATH_L4_SERVER_MASTERY_ENABLED=false로 끈다."
        ),
    )

    l4_attempt_misconception_scan_enabled: bool = Field(
        default=True,
        description=(
            "채점된 **오답 1건**에서 오개념 후보를 훑을지(EOS-104·정식기능). True(기본)면 "
            "POST /v1/me/attempts가 is_correct=false일 때 과목 어댑터의 오답 서명 검출기"
            "(`AttemptMisconceptionDetector`)에 문항 지문·제출 답안을 넘겨, 품질 게이트를 "
            "통과한 후보만 채점 증거(`possible_misconceptions`)에 싣고 활성 가설을 갱신한다. "
            "정답 시도·답안 미제출은 애초에 훑지 않는다(scan=not_run). False면 이 경로가 통째로 "
            "not_run이 되어 **'훑지 않았다'로 정직하게 표기된다** — 0건을 '오개념 없음'으로 "
            "위장하지 않는다. 킬 스위치 용도이며 끄면 감쇠도 함께 멈춘다(관측이 없으면 감쇠할 "
            "근거도 없다). WHYMATH_L4_ATTEMPT_MISCONCEPTION_SCAN_ENABLED=false로 끈다."
        ),
    )

    l4_distractor_link_enabled: bool = Field(
        default=True,
        description=(
            "학생이 고른 **오답 선지**를 문항의 오답 선지→오개념 매핑(`distractor_map`)에 "
            "대조해 오개념을 역추적할지(ASM-06·정식기능). True(기본)면 학생 표면 두 곳"
            "(POST /v1/me/attempts의 `selected_choice_index` · POST /v1/coach/sessions"
            "[/turns]의 같은 이름 슬롯)이 보고한 인덱스를 `l4.misconception.distractor_link`"
            "가 오개념 **후보**로 바꿔 기존 좌석(채점=possible_misconceptions·가설 갱신 / "
            "코치=curate_hypothesis)에 합류시킨다 — 별도 판정 경로·응답 필드를 만들지 않는다. "
            "인덱스 미보고·문항에 매핑 없음·정답 회차는 애초에 돌지 않는다. "
            "**채점 경로에서는 `l4_attempt_misconception_scan_enabled`가 상위 킬 스위치다** — "
            "그것이 False면 이 플래그와 무관하게 통째로 not_run이다(같은 좌석에 쓰는 채널이라 "
            "상위 스위치가 거짓말하면 안 된다). 이 플래그는 *선지 채널만* 끄는 좁은 스위치이며, "
            "끄면 텍스트 채널은 그대로 돈다. WHYMATH_L4_DISTRACTOR_LINK_ENABLED=false로 끈다."
        ),
    )

    l4_server_theta_enabled: bool = Field(
        default=True,
        description=(
            "L4 코칭(세션/턴)이 서버 L2 저장소(AbilitySnapshot)의 *실제* IRT 능력 θ를 조회해 "
            "BKT↔θ 교차검증 코칭(slice 73)에 쓸지. True(기본·정식기능)면 /v1/coach/sessions·"
            "turns가 학생의 최신 전과목 θ를 조회해, BKT 숙달과 *불일치*할 때(θ↑·BKT↓=추측 의심 "
            "→ consolidate·BKT↑·θ↓=망각 의심 → retrieval) `solution_coaching`으로 메타인지 "
            "코칭을 노출한다. **θ 수치는 student-facing 미노출**(결정에만 쓰고 노출되는 건 정성 "
            "코칭 발화뿐). θ 스냅샷이 없거나(희소) False면 교차검증 불가 → diagnose → 비노출"
            "(기존 동작). WHYMATH_L4_SERVER_THETA_ENABLED=false로 끈다."
        ),
    )

    l4_solution_completion_enabled: bool = Field(
        default=True,
        description=(
            "S3-32 — 완료를 *풀이 제출을 통해서만* 일으킬지(별도 '정답 제출' 버튼 대체·정식기능). "
            "True(기본)면 /v1/coach/sessions·turns가 body.solution_steps의 *마지막 단계*를 L3 "
            "verify_final_answer로 판정해, correct면 *바로 넘기지 않고* Polya 돌아보기 1턴을 "
            "유도한 뒤(review_turns_remaining) 다음 턴에 완료를 확정한다(ProblemAttempt "
            "is_correct=True 적재·숙달 전파). incorrect면 정답 비노출 재고 유도(REDIRECT)·"
            "unverifiable은 완료/재고 없음(코칭 그대로). "
            "**기대정답은 결코 응답에 노출하지 않는다**(verify_final_answer 계약). False면 동작 "
            "완전 불변(정답 감지·돌아보기·완료 적재 전부 inert·완전 되돌리기). "
            "WHYMATH_L4_SOLUTION_COMPLETION_ENABLED=false로 끈다."
        ),
    )

    l4_theta_min_responses: int = Field(
        default=3,
        ge=0,
        description=(
            "개념별 θ를 코칭 BKT↔θ 교차검증에 *쓰기 위한* 최소 응답수(slice 76 노이즈 가드). "
            "개념 θ 스냅샷의 response_count가 이 미만이면(응답 1~2개의 극단 θ=±4 등) 신뢰하지 "
            "않고 전과목 θ로 폴백한다. 0이면 응답수 게이트 사실상 해제. "
            "WHYMATH_L4_THETA_MIN_RESPONSES로 조정."
        ),
    )
    l4_theta_max_se: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "개념별 θ를 신뢰할 표준오차(SE) 상한(slice 76 노이즈 가드). 개념 θ의 SE가 이 초과거나 "
            "측정 불가(SE 없음·정보 0의 극단 θ)면 전과목 θ로 폴백한다. 크게 두면 SE 게이트 완화. "
            "WHYMATH_L4_THETA_MAX_SE로 조정."
        ),
    )

    # ── QUALITY(27b) 비동기 큐 (Celery, broker=result backend=Redis, S4) ──
    # QUALITY는 동기 호출 불가(p50≈14초·GPU 단일 점유, 03a §D.3) → 작업 큐 전용이다.
    # broker·result-backend는 *기본값을 두지 않고*(빈 = "redis_url에서 파생") 명시
    # 오버라이드가 없으면 redis_url을 그대로 재사용한다(아래 celery_* property).
    # 별도 환경변수로 분리 인프라(전용 broker DB 등)를 가리키게 할 수 있다.
    celery_broker_url: str = Field(
        default="",
        description=(
            "Celery broker URL. 빈 값(기본)이면 redis_url을 재사용한다(단일 Redis로 "
            "캐시+큐 운영). 전용 broker로 분리하려면 WHYMATH_CELERY_BROKER_URL로 주입. "
            "시크릿 아님 — 인증이 필요하면 URL에 환경변수로 자격증명을 담는다(하드코딩 금지)."
        ),
    )
    celery_result_backend: str = Field(
        default="",
        description=(
            "Celery result backend URL. 빈 값(기본)이면 redis_url을 재사용한다. "
            "job_id로 QUALITY 결과를 폴링하려면 result backend가 필요하다(03a §D.3 폴링). "
            "분리하려면 WHYMATH_CELERY_RESULT_BACKEND로 주입."
        ),
    )

    # ── 관측성 (Langfuse, S3부터 실제 전송) ──
    # 시크릿: 공개키·시크릿키는 *기본값 없음*(빈 = 미설정). 둘 다 채워져야 LangfuseSink가
    # 활성화되고, 하나라도 비면 영구 no-op(03a §F.2 관측성은 best-effort). 시크릿 키는
    # SecretStr로 평문 repr/로그 노출을 차단한다(CLAUDE.md 보안 금기).
    langfuse_public_key: str = Field(
        default="",
        description=(
            "Langfuse 공개키(pk-...). 기본값 없음(빈 = 미설정). 환경변수 "
            "WHYMATH_LANGFUSE_PUBLIC_KEY로 주입. 비면 관측성은 영구 no-op으로 비활성."
        ),
    )
    langfuse_secret_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Langfuse 시크릿키(sk-...). SecretStr — repr/로그에 평문 노출 안 됨. "
            "기본값 없음(빈 = 미설정). 환경변수 WHYMATH_LANGFUSE_SECRET_KEY로만 주입 "
            "(CLAUDE.md 보안 금기: 코드 하드코딩 금지). 비면 관측성 no-op."
        ),
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        description=(
            "Langfuse 호스트 URL. 무해한 공개 디폴트(클라우드). 셀프호스트는 환경변수 "
            "WHYMATH_LANGFUSE_HOST로 주입. 시크릿 아님 — 호스트만으로는 전송 불가(키 필요)."
        ),
    )

    # ── 클라우드 LLM (Anthropic Claude, S5 — 03a §C.1·§A.0 CLOUD_MID/HIGH 경로) ──
    # 라우터가 내리는 CLOUD_MID(Sonnet)·CLOUD_HIGH(Opus) 결정을 실제 생성으로 잇는다.
    # API 키는 *기본값 없음*(빈 = 미설정) — 키가 없으면 AnthropicProvider는 클라우드
    # 결정에 대해 명확한 오류를 던지고(조용한 강등 금지), /status는 cloud_configured=
    # False로 보고한다. 모델 ID는 alias 기본값(env 오버라이드 가능, 03a §H 후속 4).
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Anthropic API 키(sk-ant-...). SecretStr — repr/로그에 평문 노출 안 됨. "
            "기본값 없음(빈 = 미설정). 환경변수 WHYMATH_ANTHROPIC_API_KEY로만 주입 "
            "(CLAUDE.md 보안 금기: 코드 하드코딩 금지). 비면 클라우드 생성 불가."
        ),
    )
    # ARCH-66 — 2026-09-24 Kiki 결정: 2026-12-31(내부 프로젝트 완성 시점)까지 Anthropic API를
    # 쓰지 않는다. 개발은 Claude Max 구독(Claude Code)으로 하되, 구독은 개인 개발 도구이지
    # 서비스 런타임의 API 호출을 대신하지 못한다. 그래서 키가 남아 있어도 이 스위치가 꺼져
    # 있으면 `anthropic_configured`가 False — 키 미설정과 **같은 기존 경로**(클라우드 불가
    # 보고·AnthropicProvider 명확한 오류)로 흐른다. 재개는 이 값을 켜는 것이 아니라
    # 게이트 `G-arch66-anthropic-api-pause-review`(2026-12-31 재판정)를 거친다.
    anthropic_api_enabled: bool = Field(
        default=False,
        description=(
            "Anthropic API 사용 허가 스위치(ARCH-66 · 기본 False). 2026-09-24 Kiki 결정으로 "
            "2026-12-31까지 Anthropic API 미사용 — 꺼져 있으면 키가 있어도 미설정으로 본다. "
            "환경변수 WHYMATH_ANTHROPIC_API_ENABLED. 재개 판정 = G-arch66-anthropic-api-pause-review."
        ),
    )
    anthropic_model_mid: str = Field(
        default="claude-sonnet-4-6",
        description=(
            "CLOUD_MID 티어 모델 ID(축1, 03a §A.0). 기본 Claude Sonnet 4.6 alias. "
            "환경변수 WHYMATH_ANTHROPIC_MODEL_MID로 핀/오버라이드. 시크릿 아님."
        ),
    )
    anthropic_model_high: str = Field(
        default="claude-opus-4-7",
        description=(
            "CLOUD_HIGH 티어 모델 ID(축1, 03a §A.0). 기본 Claude Opus 4.7 alias. "
            "환경변수 WHYMATH_ANTHROPIC_MODEL_HIGH로 핀/오버라이드. 시크릿 아님."
        ),
    )
    anthropic_max_tokens: int = Field(
        default=16000,
        ge=1,
        description=(
            "Anthropic messages.create의 max_tokens(필수 인자). 비스트리밍 동기 호출 "
            "기준 안전 기본값(SDK ~10분 타임아웃 가드 미만). WHYMATH_ANTHROPIC_MAX_TOKENS로 조정."
        ),
    )
    anthropic_request_timeout_s: float = Field(
        default=60.0,
        ge=0.0,
        description=(
            "Anthropic 단일 호출 타임아웃(초). 클라우드는 동기 경로(03a §C.4 mode=sync). "
            "ollama_request_timeout_s 미러. WHYMATH_ANTHROPIC_REQUEST_TIMEOUT_S로 조정."
        ),
    )
    # ── 클라우드 품질·비용 튜닝 노브 (전부 기본 OFF = 현 동작 유지, 03a §H 후속 4) ──
    # 최적값은 *라이브 측정* 후에야 정할 수 있어(키 필요·Kiki) 기본은 '생략/끔'이다 —
    # 코드 변경 없이 env로 켜고 튜닝할 수 있게 *배선만* 해 둔다.
    anthropic_effort: str = Field(
        default="",
        description=(
            "클라우드 호출 effort(output_config.effort) — low/medium/high/xhigh/max. "
            "빈 값(기본)이면 *생략*(현 동작 유지). Sonnet 4.6·Opus 4.7만 지원(구형 모델 핀 시 "
            "400 주의). xhigh/max는 max_tokens 상향 권장. 최적값은 라이브 측정 후 "
            "WHYMATH_ANTHROPIC_EFFORT로 설정(03a §H 후속 4)."
        ),
    )
    anthropic_thinking: bool = Field(
        default=False,
        description=(
            "True면 클라우드 호출에 adaptive thinking(thinking={'type':'adaptive'}) 적용. "
            "기본 False(생략, 현 동작 유지) — thinking은 동기 지연·비용을 늘리므로 라이브 측정 "
            "후 WHYMATH_ANTHROPIC_THINKING로 켠다(생성 텍스트는 type=='text' 블록만 사용)."
        ),
    )
    anthropic_prompt_caching: bool = Field(
        default=False,
        description=(
            "True면 messages.create에 top-level cache_control(ephemeral) 적용(prefix 캐시). "
            "기본 False(현 동작 유지) — 적중은 라이브 키로만 검증 가능하고 system 프롬프트가 "
            "L4/L5 미확정이라 효과 잠정. 짧은 프리픽스는 최소 토큰 미만이라 무효(silent no-op)."
        ),
    )

    # ── 클라우드 슬롯 셀렉터 (ARCH-57 — ARCH-55 채택 판정의 집행 지점) ──
    # `CompositeProvider`의 cloud 슬롯에 어떤 프로바이더가 앉는가. 종전에는 호출자가
    # `AnthropicProvider()`를 **하드코딩**해 8곳에 흩어져 있었고, 그래서 ARCH-55가 채택한
    # OpenRouter 경로를 프로브만 쓰고 실제 저작 작업은 쓸 수 없었다(채택은 났는데 집행이
    # 없는 상태 — CLAUDE.md 「정본화를 집행으로 착각한 완료 선언 금지」).
    #
    # **기본값 `anthropic`은 불변이다.** ARCH-55 채택 판정문이 "선택지를 넓힌 것이지 기본값을
    # 옮긴 것이 아니다"라고 명시했고, 판정 기준 (d) 지연·가용성이 `ARCH-56`으로 보류 중이라
    # 미판정 구성이 기본값이 되면 안 된다. 이 기본값을 바꾸는 것은 코드 변경이 아니라 판정이다
    # (`tests/backend/l3/test_cloud_provider_selector.py`가 계약으로 동결한다).
    #
    # 적용 범위는 **저작 경로 한정**이다 — 학생 대면 서빙(`app.py`)은 이 셀렉터를 타지 않는다.
    # 그쪽을 옮기는 것은 `G-arch56-availability-trigger`의 발동 조건 ⓐ(학생 대면 트래픽 투입
    # 결정)를 실현시키는 행위라 Kiki 판정 사안이다.
    cloud_provider: CloudSeat = Field(
        default="anthropic",
        description=(
            "저작 경로의 클라우드 슬롯 제공자. `anthropic`(기본·불변 핀 claude-sonnet-4-6) / "
            "`openrouter`(ARCH-55 채택 — deepseek/deepseek-v4.1-flash·공급사 deepinfra 고정) / "
            "`deepseek`(공식 API·CN 관할). 좌석 선택만이고 클라이언트 생성은 지연된다. "
            "학생 대면 서빙은 이 값과 무관하게 항상 anthropic이다(ARCH-56 게이트)."
        ),
    )

    # ── DeepSeek 공식 API (CN 관할, ARCH-49 — 03a 클라우드 선택지 확장) ──
    # 모델 ID는 **실측값만** 쓴다. 2026-09-16 Kiki 머신에서 유효 키로 `GET
    # https://api.deepseek.com/models`를 조회한 결과 반환된 id는 정확히 두 개다:
    # `deepseek-flash`·`deepseek-v4-pro`. 웹 자료 3곳이 일치해 적고 있는
    # `deepseek-v4-flash`는 **API가 받지 않는 이름**이다(제품 표기 ≠ API id).
    # 새 ID를 핀할 때도 같은 방식으로 실 API 조회를 먼저 한다
    # (CLAUDE.md 「환경 사실의 추론 등재 금지」).
    #
    # 관할: 공식 API는 중국 본토 서버 전용이고 데이터 레지던시 선택지가 없다(2026-09 실측).
    # 따라서 `Jurisdiction.CN`이며, 기본 허용 등급은 합성 프로브(`WHYMATH_GENERATED`)뿐이다
    # (`l3.provider_jurisdiction`). 자체 저작 코퍼스를 태우려면 아래 opt-in이 필요하다.
    deepseek_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("WHYMATH_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        description=(
            "DeepSeek 공식 API 키(sk-...). SecretStr — repr/로그에 평문 노출 안 됨. "
            "기본값 없음(빈 = 미설정). `WHYMATH_DEEPSEEK_API_KEY` 또는 벤더 표준 이름 "
            "`DEEPSEEK_API_KEY` 둘 다 읽는다 — 후자가 Phaiakes9 User 환경변수에 이미 "
            "등록돼 있어(2026-09-16 라이브 확인) 재등록을 요구하지 않기 위함이다. "
            "하드코딩 금지(CLAUDE.md 보안 금기)."
        ),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        description=(
            "DeepSeek 공식 API 베이스 URL(OpenAI 호환 `/chat/completions`). 시크릿 아님. "
            "WHYMATH_DEEPSEEK_BASE_URL로 오버라이드."
        ),
    )
    deepseek_model_mid: str = Field(
        default="deepseek-flash",
        description=(
            "CLOUD_MID 티어에 대응하는 DeepSeek 모델 ID. **실측 핀**(2026-09-16 /models 조회) — "
            "`deepseek-v4-flash`가 아니다. WHYMATH_DEEPSEEK_MODEL_MID로 오버라이드."
        ),
    )
    deepseek_model_high: str = Field(
        default="deepseek-v4-pro",
        description=(
            "CLOUD_HIGH 티어에 대응하는 DeepSeek 모델 ID. **실측 핀**(2026-09-16 /models 조회). "
            "WHYMATH_DEEPSEEK_MODEL_HIGH로 오버라이드."
        ),
    )
    deepseek_max_tokens: int = Field(
        default=16000,
        ge=1,
        description="DeepSeek chat/completions의 max_tokens. anthropic_max_tokens 미러.",
    )
    deepseek_request_timeout_s: float = Field(
        default=60.0,
        ge=0.0,
        description="DeepSeek 단일 호출 타임아웃(초). anthropic_request_timeout_s 미러.",
    )
    deepseek_allow_internal_corpus: bool = Field(
        default=False,
        description=(
            "True면 CN 관할 프로바이더에 자체 저작 코퍼스(`INTERNAL_OWNED`) 등급을 실은 요청도 "
            "허용한다. **기본 False** — 라이선스상 `INTERNAL_OWNED.export=True`라 *법적으로는* "
            "반출 가능하지만, 개념 그래프·오개념 카탈로그·교수학 프롬프트는 영업자산이고 "
            "DeepSeek이 유료 API 입력을 학습에 쓰는지가 **미확정**이다(2차 자료가 서로 반대로 "
            "적고 1차 약관은 조사 세션의 egress 프록시가 차단). 확정되면 그 근거와 함께 "
            "기본값을 재평가한다. 학생 저작(`USER_GENERATED`)은 이 플래그와 무관하게 "
            "**어떤 값으로도 열리지 않는다**(export=False라 허용 집합에 들어올 수 없다)."
        ),
    )

    # ── OpenRouter 경유 (서방 공급사가 서빙하는 오픈웨이트, ARCH-49 acceptance ⑨⑩) ──
    # DeepSeek V4는 MIT 오픈웨이트라 서방 공급사도 서빙한다 — 즉 "DeepSeek = CN 관할"은
    # *경로에 따라* 다르다. OpenRouter의 `deepseek/deepseek-v4-flash` 엔드포인트는 16곳이고
    # 공급사마다 국적·양자화·데이터 정책이 다르다(2026-09-16 Kiki 머신 실측).
    #
    # 채택 계약(코드에 박는다 — `l3/providers/openrouter.py`): 모든 호출이
    # `provider.only`·`provider.allow_fallbacks=false`·`provider.data_collection="deny"`
    # 세 파라미터를 **항상** 동반한다. 옵션이 아니라 계약이며, 누락 시 테스트가 RED다.
    # 셋이 각각 막는 것: only=국적 미상 공급사, allow_fallbacks=조용한 우회,
    # data_collection=학습 수집. `only` 없이 fallback이 열리면 매 호출마다 다른 정밀도
    # (fp8/fp4/unknown)가 응답해 품질 비교 자체가 성립하지 않는다.
    #
    # Preset 기능은 쓰지 않는다 — 설정이 웹 UI에 있으면 저장소 게이트가 검사할 수 없어
    # 이중 진실 원천이 된다(요청의 명시 파라미터가 Preset을 덮어쓰므로 코드가 항상 이긴다).
    openrouter_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("WHYMATH_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        description=(
            "OpenRouter API 키(sk-or-...). SecretStr — repr/로그에 평문 노출 안 됨. "
            "`WHYMATH_OPENROUTER_API_KEY` 또는 벤더 표준 `OPENROUTER_API_KEY` 둘 다 읽는다 "
            "(후자가 Phaiakes9에 이미 등록·2026-09-16 라이브 확인). 하드코딩 금지."
        ),
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter API 베이스 URL(OpenAI 호환). 시크릿 아님.",
    )
    openrouter_model_mid: str = Field(
        default="deepseek/deepseek-v4.1-flash",
        description=(
            "CLOUD_MID 티어에 대응하는 OpenRouter 모델 slug. **정정 2026-09-17** — "
            "`deepseek-v4-flash`(점 없음)가 아니라 `deepseek-v4.1-flash`다. Kiki가 "
            "openrouter.ai 모델 페이지를 열어 확인했다(URL·복사 버튼의 정본 id). "
            "list price $0.15/$0.60 per 1M · 컨텍스트 1.0M · 출시 2026-09-10. "
            "공식 API의 `deepseek-flash`와 이름이 다르다 — OpenRouter는 제품명을, "
            "공식 API는 자기 id를 쓴다. 최종 확정은 `/models` 조회다"
            "(`harness.openrouter_endpoints_probe --search`)."
        ),
    )
    openrouter_model_high: str = Field(
        default="deepseek/deepseek-v4-pro",
        description=(
            "CLOUD_HIGH 티어에 대응하는 OpenRouter 모델 slug. **미확인 핀** — "
            "MID가 `v4.1`로 정정된 만큼 이 slug도 같은 오류일 수 있다"
            "(`v4.1-pro`일 가능성). 쓰기 전에 `--search`로 확정한다."
        ),
    )
    openrouter_allowed_providers: tuple[str, ...] = Field(
        default=("deepinfra",),
        description=(
            "OpenRouter `provider.only`에 실을 공급사 slug 허용목록 — **우리가 국적을 알고 "
            "데이터 정책이 깨끗한 곳만**. slug는 endpoints 응답 `tag`의 `/` 앞부분이다 "
            "(`deepinfra/fp8`→`deepinfra`). 이 목록이 `data_collection=deny`와 **독립된 두 "
            "번째 방어층**이다(CLAUDE.md 이중 회계 — 외부 분류에만 의존 금지). 빈 목록은 "
            "허용이 아니라 **차단**이다.\n"
            "기본값이 **`deepinfra` 1곳인 이유**: 검증 가능한 세 축을 *함께* 아는 곳이고 "
            "가장 싸다(2026-09-17~18 공급사 패널·엔드포인트 응답 실측).\n"
            "  · 관할 — `Headquarters: US`\n"
            "  · 데이터 정책 — `Prompt training: No` + `Retention: Zero retention`\n"
            "  · 양자화 — `Precision: FP8`\n"
            "`baseten`도 같은 세 축을 만족하며(패널 실측 · `Region: US` 추가) `PROVIDER_*` "
            "표에 등재돼 있다 — 갈아 끼울 때 근거를 다시 모을 필요가 없다. 그럼에도 기본값이 "
            "deepinfra인 것은 **회당 비용이 약 절반**이기 때문이다(실측 토큰 기준 $0.00125 vs "
            "$0.00228 · `claude-sonnet-4-6` $0.004767 대비 3.8배 vs 2.1배).\n"
            "**가용성은 의도적으로 판정 축에서 뺐다.** 2026-09-17~18에 네 회차를 쟀는데 같은 "
            "공급사·같은 시험지로 `429 engine_overloaded` 실패율이 **30% → 15% → 0%**로 "
            "흔들렸다(마지막이 가장 붐빌 것이라던 peak 구간이다 — 시간대로 설명되지 않는다). "
            "20회 표본으로는 공급사를 가를 수 없고, 실제로 이 분산을 근거로 기본값을 두 번 "
            "뒤집었다가 되돌렸다. 더 큰 표본을 태우기 전에 짚을 것이 있다 — 실패 원인이 "
            "`limit_source=upstream_provider_shared_pool` · `is_byok=false`, 즉 **공유 풀**이라 "
            "BYOK(공급사 자체 키를 OpenRouter integrations에 등록)을 붙이면 이 축 자체가 "
            "사라진다. 그때까지 이 표의 가용성 숫자는 *우리가 쓰지 않을 구성*을 재는 값이다.\n"
            "참고: Baseten 엔드포인트는 2곳이지만 **둘 다 tag가 `baseten/fp8`**이라(엔드포인트 "
            "응답 실측) `only`가 둘을 모두 허용해도 정밀도가 섞이지 않는다 — 두 행은 리전/배포 "
            "차이다. 그래서 양자화 강제 파라미터를 따로 두지 않는다.\n"
            "`gmicloud`는 FP8이지만 `Retention: Unknown`이고, `fireworks`·`together`는 보존 "
            "정책이 깨끗하지만 `Precision: --`(미표기)다. 즉 **어느 한 축씩만 아는 곳을 섞으면 "
            "다른 축에서 샌다** — 정밀도가 섞인 목록은 `allow_fallbacks=false`라도 매 호출마다 "
            "다른 모델을 부르는 것과 같고(어느 곳이 응답할지는 OpenRouter가 정한다), 그 "
            "상태에서 잰 정확도 차이는 모델의 것이 아니라 잡음이다(acceptance ⑨(d)).\n"
            "`digitalocean`은 뺐다 — 이전 세션이 US로 적었으나 이번 실측으로 재확인되지 "
            "않았고 그 세션의 OpenRouter 기록 4건이 전부 틀렸다(모델 slug·엔드포인트 수·"
            "최저가 공급사·단가). 근거를 다시 확보하면 되돌린다.\n"
            "**가용성 비용을 명시한다**: 1곳 + `allow_fallbacks=false`면 그곳이 죽을 때 호출이 "
            "실패한다. 지금은 채택 미판정이라 조용한 품질 변동보다 명확한 실패가 낫다는 "
            "판단이며, 운영 도입 시 **정밀도가 같은** 곳을 추가해 이중화한다(정밀도가 다른 "
            "곳으로 늘리는 것은 이중화가 아니라 오염이다).\n"
            "**baseten으로 바꿀 때의 비용 영향**: $0.20/$0.60 → $0.30/$1.20이라 회당 "
            "약 2배다. `Cache read`도 $0.006 → $0.03으로 5배이므로, 프롬프트 캐시 재사용이 큰 "
            "워크로드에서는 그 축을 따로 재야 한다. 대신 대기열을 뚫고 난 뒤의 지연은 baseten이 "
            "낫게 관측됐다(p50 5.3초 vs 36.9초 — 같은 창 A/B 1회)."
        ),
    )
    openrouter_max_tokens: int = Field(
        default=16000,
        ge=1,
        description="OpenRouter chat/completions의 max_tokens. anthropic_max_tokens 미러.",
    )
    openrouter_request_timeout_s: float = Field(
        default=60.0,
        ge=0.0,
        description="OpenRouter 단일 호출 타임아웃(초). anthropic_request_timeout_s 미러.",
    )

    # ── 인증(JWT 집행 계층, L5) ──
    # UserProfile엔 credential 필드가 없다 — JWT는 sub=user_id만 담는 *집행 토큰*이고, 실제
    # 로그인(카카오/네이버 OAuth, 후속)이 create_access_token을 호출해 발급한다. 시크릿은 코드
    # 하드코딩 금지(anthropic_api_key 패턴) — 비면 토큰 발급/검증이 명확한 오류를 던진다.
    jwt_secret_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "JWT 서명 시크릿(HS256). SecretStr — repr/로그 평문 노출 안 됨. 기본값 없음(빈 = "
            "미설정). 환경변수 WHYMATH_JWT_SECRET_KEY로만 주입(하드코딩 금지). 비면 인증 불가."
        ),
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description=(
            "JWT 서명 알고리즘(기본 HS256 대칭). WHYMATH_JWT_ALGORITHM로 오버라이드. 시크릿 아님."
        ),
    )
    jwt_expire_minutes: int = Field(
        default=60 * 24,
        ge=1,
        description="액세스 토큰 만료(분). 기본 24시간. WHYMATH_JWT_EXPIRE_MINUTES로 조정.",
    )
    jwt_refresh_expire_minutes: int = Field(
        default=60 * 24 * 30,  # 30일(security_privacy.md REFRESH_TOKEN_TTL)
        ge=1,
        description="리프레시 토큰 만료(분). 기본 30일. WHYMATH_JWT_REFRESH_EXPIRE_MINUTES로 조정.",
    )

    # ── 미성년 동의 게이트(PIPA 만14세 미만, L5) ──
    # 서버측 `is_minor` 파생의 연령 임계(법정 기준). PIPA는 *만 14세 미만*의 개인정보 처리에
    # 법정대리인 동의를 요구하므로(docs/legal/pipa_data_matrix.md §3) 기본 14다. 이 값은
    # `consent.derive_is_minor`가 birth_year로 `is_minor`를 파생할 때 쓰는 *유일한* 연령 기준
    # 으로, 콜백(가입)·PATCH 양쪽 쓰기 경로가 공유한다(법정 기준 변경 시 한 곳만 바꾼다).
    # birth_year만 수집(월일 미수집)하므로 파생은 *보수적 연나이*다 — 정확한 만나이 게이팅·
    # 동의 GRANT 플로우·동의 재확인 주기는 변호사 자문 후속(pipa_data_matrix.md §3 체크리스트).
    minor_consent_age: int = Field(
        default=14,
        ge=0,
        description=(
            "미성년 동의 게이트 연령 임계(만 나이·법정 기준). PIPA 만14세 미만 법정대리인 동의 "
            "(docs/legal/pipa_data_matrix.md §3) → 기본 14. `consent.derive_is_minor`가 "
            "birth_year로 `is_minor`를 파생할 때의 유일한 기준(가입 콜백·PATCH 공유). 정확한 "
            "만나이엔 생일(월일)이 필요하나 birth_year만 수집해 *보수적 연나이*로 파생한다 — "
            "법정 기준 자체는 변호사 자문으로 확정. WHYMATH_MINOR_CONSENT_AGE로 조정."
        ),
    )
    parental_consent_grant_enabled: bool = Field(
        default=False,
        description=(
            "법정대리인 동의 *기록(GRANT)* 엔드포인트(POST /v1/users/me/parental-consent·PIPA "
            "만14세 미만 §3) 활성 여부. **기본 False(prod 안전)**: 신원 확인이 아직 "
            "StubGuardianVerifier(실 본인확인 미구현·변호사 자문 후속)라, 켜면 미성년이 임의 "
            "이메일로 *스스로 동의를 부여*해 게이트를 우회할 수 있다(self-consent). 실 "
            "GuardianVerifier(휴대폰 본인인증 등) 결선 전까지 off로 둬 동의 경로를 막는다(off면 "
            "404). consent_grant.py·pipa_data_matrix.md §3.5. "
            "WHYMATH_PARENTAL_CONSENT_GRANT_ENABLED로 조정."
        ),
    )

    # ── 개인정보 감사 IP 해싱 시크릿(SEC-09, L5) ──
    # `privacy.audit.hash_client_ip`가 `sha256(salt+ip)`로 감사 행의 IP를 해싱할 때 쓰는 salt.
    # `email_hash`(api/auth.py)는 *의도적으로 무염* — upsert 조회 키라 같은 이메일=같은 해시가
    # 필요하다. 감사 IP 해시는 반대 요구(레인보우테이블 불가·조회 키 아님)라 새 salt를 둔다
    # (jwt_secret_key 패턴 답습 — SecretStr·코드 하드코딩 기본값 없음·env 전용).
    pii_audit_ip_salt: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "개인정보 감사(SEC-09) IP 해싱 salt — sha256(salt+ip). SecretStr — repr/로그 평문 "
            "노출 안 됨. 기본값 없음(빈 = 미설정). 환경변수 WHYMATH_PII_AUDIT_IP_SALT로만 주입 "
            "(하드코딩 금지). 미설정 시 프로덕션 추정 환경은 RuntimeError(fail-closed·SEC-01 "
            "`require_dialogue_content_cipher` 패턴 답습), 개발·CI는 경고 후 ip_hash=None으로 "
            "감사 행 자체는 계속 적재한다(IP 해시 미비로 반출·동의변경 감사 자체를 놓치는 것이 "
            "더 나쁜 실패 모드이므로 주행위를 막지 않는다)."
        ),
    )

    # ── 시연(데모) 전용 가짜 OAuth provider(S1 게이트 ① 실기기 시연) ──
    # 실기기 학습 루프 녹화를 turnkey로 만들기 위한 하드 블로커 ①(인증) 해소 수단이다.
    # 실 로그인 webview(OAuth-c3)가 미배선이라 보호 엔드포인트가 401로 막히는데, 이 플래그를
    # 켜면 create_app이 FakeOAuthProvider를 레지스트리에 등록해 기존 콜백 경로 그대로 고정
    # 데모 계정의 실 JWT를 발급한다(security.py/_auth.py 무변경). 신원 검증이 전혀 없으므로
    # prod에서 켜면 누구나 데모 계정 토큰을 얻는다 — 로컬 시연 호스트 밖에서 절대 금지.
    demo_auth_enabled: bool = Field(
        default=False,
        description=(
            "시연 전용 가짜 OAuth provider 활성 여부. **기본 False(prod 절대 안전)**: True면 "
            "create_app이 FakeOAuthProvider(api/demo_auth.py)를 등록해 POST /v1/auth/demo/callback "
            "이 고정 데모 사용자의 실 JWT를 발급한다(신원 검증 0). S1 탈출 게이트 ①(실기기 15분 "
            "루프 녹화)의 인증 블로커 해소용. **이중 방어**: 실 provider(kakao/naver) 구성 시엔 "
            "이 플래그가 True여도 등록을 거부한다(prod 추정). prod에서 켜면 임의 데모 계정 토큰 "
            "발급이 가능하므로 로컬 시연 호스트 밖에서 절대 금지. WHYMATH_DEMO_AUTH_ENABLED로 조정."
        ),
    )

    # ── OAuth 로그인(카카오·네이버 SSO, OAuth-a2) ──
    # client_id는 공개 식별자(일반 str)·client_secret은 SecretStr·env-only(하드코딩 금지).
    # 비면 해당 provider 미등록(create_app이 레지스트리에서 제외 → 콜백 404).
    kakao_client_id: str = Field(
        default="",
        description=(
            "카카오 REST API 키(client_id·공개 식별자). 환경변수 WHYMATH_KAKAO_CLIENT_ID. "
            "비면 카카오 로그인 미등록(콜백 404)."
        ),
    )
    kakao_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "카카오 client_secret(선택·관리자 설정 시). SecretStr·env-only "
            "(WHYMATH_KAKAO_CLIENT_SECRET·하드코딩 금지)."
        ),
    )
    naver_client_id: str = Field(
        default="",
        description=(
            "네이버 client_id(공개 식별자). 환경변수 WHYMATH_NAVER_CLIENT_ID. "
            "비면 네이버 로그인 미등록(콜백 404)."
        ),
    )
    naver_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "네이버 client_secret. SecretStr·env-only(WHYMATH_NAVER_CLIENT_SECRET·하드코딩 금지)."
        ),
    )

    # ── SEC-08: OAuth state(CSRF) + redirect_uri allowlist(open redirect 방지) ──
    # 이 백엔드는 `/authorize` 리다이렉트를 자체 발급하지 않는다(모바일 클라가 OAuth provider와
    # 직접 리다이렉트를 주고받고 code만 서버에 POST) — 그래서 state는 서버가 *사전 발급*
    # (GET /v1/auth/{provider}/state)하고 콜백 제출 시 그대로 동봉받아 검증하는 stateless HMAC
    # 서명 방식이다(DB/Redis 저장 불필요·api/auth.py issue_oauth_state/verify_oauth_state).
    oauth_redirect_uri_allowlist: str = Field(
        default="",
        description=(
            "OAuth 콜백이 허용하는 redirect_uri 화이트리스트(콤마 구분). 비면 *전부 거부*"
            "(deny-by-default·open redirect 방지). 배포·데모 환경은 반드시 설정. "
            "환경변수 WHYMATH_OAUTH_REDIRECT_URI_ALLOWLIST. 시크릿 아님(공개 URI). "
            "파싱된 리스트는 `oauth_redirect_uris` 프로퍼티 참조."
        ),
    )
    oauth_state_ttl_seconds: int = Field(
        default=300,
        ge=1,
        description=(
            "OAuth CSRF state(`issue_oauth_state`) 유효 기간(초). 기본 5분 — provider 동의 "
            "화면 체류 시간 여유. WHYMATH_OAUTH_STATE_TTL_SECONDS로 조정."
        ),
    )

    # ── L4 코치 엔드포인트 rate limit ──
    coach_rate_limit_read_per_minute: int = Field(
        default=60,
        ge=0,
        description=(
            "L4 코치 *읽기* 엔드포인트(GET /v1/coach/sessions/{id})의 사용자당 분당 요청 "
            "상한. 0=비활성. 읽기는 ETag/304 캐싱으로 경량 — 쓰기보다 높게 둔다."
        ),
    )
    evidence_retention_years: int = Field(
        default=3,
        ge=1,
        description=(
            "학습 증거(evidence_links — 미성년 오개념 진단 증거)의 *기본 보존기한*(년). 적재 시점 "
            "기준 retention_until을 채워 `purge_expired`가 경과분 파기(GDPR 데이터 최소화·무기한 "
            "보존 금지). 기본 3년(2026-06-18 합의)·미성년 보존은 규제 대상이라 법무 확정 시 조정. "
            "log_evidence가 retention_until 미제공 시 today+이 값으로 채운다."
        ),
    )
    pii_retention_years: int = Field(
        default=3,
        ge=1,
        description=(
            "학습 활동 PII 시계열(dialogue·learning_session·problem_attempt·attempt_event·"
            "assessment·concept_mastery_history·ability_snapshot·daily/behavior metrics)의 *기본 "
            "보존기한*(년). `privacy.retention.purge_expired_records`가 타임스탬프(started_at/"
            "measured_at 등) < (오늘−이 값)인 행을 파기(GDPR 데이터 최소화·무기한 보존 금지). 기본 "
            "3년(evidence와 동일·2026-06-18 합의)·법무 확정 시 테이블별 차등은 후속."
        ),
    )
    coach_rate_limit_write_per_minute: int = Field(
        default=30,
        ge=0,
        description=(
            "L4 코치 *쓰기* 엔드포인트(POST /v1/coach·POST /v1/coach/sessions·POST "
            "/v1/coach/sessions/{id}/turns)의 사용자당 분당 요청 상한. 0=비활성. DB 쓰기·"
            "후속 LLM 호출 비용을 고려해 읽기보다 낮게 둔다."
        ),
    )
    coach_rate_limit_ip_read_per_minute: int = Field(
        default=120,
        ge=0,
        description=(
            "L4 코치 *읽기* 엔드포인트의 *IP 단위* 분당 요청 상한(미인증 표면 노출 시). "
            "0=비활성. 인증 사용자보다 *느슨하게* 둔다(공유 NAT·캠퍼스 IP 보호) — 인증된 "
            "사용자 한도(`coach_rate_limit_read_per_minute`)는 별도 적용."
        ),
    )
    coach_rate_limit_ip_write_per_minute: int = Field(
        default=60,
        ge=0,
        description=(
            "L4 코치 *쓰기* 엔드포인트의 *IP 단위* 분당 요청 상한. 0=비활성. "
            "쓰기는 IP 단위에서도 상대적으로 엄격(공격·자동화 봇 방어). 인증 사용자 한도는 별도."
        ),
    )
    # ── SEC-08: 인증 표면(/v1/auth/*) IP 단위 rate limit ──
    auth_rate_limit_ip_per_minute: int = Field(
        default=20,
        ge=0,
        description=(
            "OAuth 콜백(`POST /v1/auth/{provider}/callback`)의 *IP 단위* 분당 요청 상한. "
            "0=비활성. 로그인 시도는 드문 작업이라 20이면 정상 사용자는 무영향이고 자동화 "
            "남용(크리덴셜 스터핑·계정 생성 폭주)만 차단한다."
        ),
    )
    auth_rate_limit_ip_refresh_per_minute: int = Field(
        default=30,
        ge=0,
        description=(
            "리프레시(`POST /v1/auth/refresh`)의 *IP 단위* 분당 요청 상한. 0=비활성. "
            "액세스 토큰 TTL이 24시간이라 정상 리프레시는 드물게 일어나므로 30이면 여유롭다."
        ),
    )
    # ── SEC-24(원 SEC-14): 신뢰 리버스 프록시 allowlist(X-Forwarded-For 위조 방지) ──
    # `_client_ip`(api/_rate_limit.py)가 X-Forwarded-For를 신뢰할지 판단하는 근거. 여기 넣는
    # IP는 *프록시 체인 중간의 아무 IP*가 아니라 "이 앱 서버에 직접 TCP 연결하는 리버스
    # 프록시/로드밸런서의 IP" — 즉 `request.client.host`가 그 값과 일치해야 신뢰 체인이
    # 시작된다(그래야 그 프록시가 실제로 설정한 XFF만 우측-신뢰 방식으로 읽는다). oauth_redirect_
    # uri_allowlist(위)와 동일 패턴: 콤마 구분 원시값 필드 + 파싱 프로퍼티(`trusted_proxy_ips`).
    trusted_proxy_ip_allowlist: str = Field(
        default="",
        description=(
            "`X-Forwarded-For` 헤더를 신뢰할 리버스 프록시/로드밸런서 IP 화이트리스트(콤마 "
            "구분). **이 앱 서버에 직접 TCP 연결하는 프록시의 IP**만 넣는다(`request.client.host` "
            "가 이 값과 일치해야 함) — 체인 중간의 IP가 아니다. 비면 *전부 거부*(deny-by-default): "
            "`_client_ip`가 X-Forwarded-For 헤더를 완전히 무시하고 `request.client.host`만 "
            "쓴다(신뢰 프록시 미구성 상태의 안전한 기본 자세 — 위조된 XFF로 rate limit·감사 IP를 "
            "속일 수 없다). 리버스 프록시 뒤에 배포할 때만 설정. 환경변수 "
            "WHYMATH_TRUSTED_PROXY_IP_ALLOWLIST. 시크릿 아님(공개 IP). "
            "파싱된 집합은 `trusted_proxy_ips` 프로퍼티 참조."
        ),
    )
    # ── SEC-26: CORS + TrustedHost 미들웨어 allowlist(48_보안 §P0 갭) ──
    # 이 백엔드의 학생 클라는 Flutter 네이티브 앱이라 브라우저 CORS 적용 대상이 아니다
    # (`tests/backend/test_cors_policy_freeze.py`의 원 결정 — 근거는 그대로 유효). 웹 클라
    # (`src/web/` 백오피스·교사 대시보드, ADMIN-06)가 실제로 브라우저에서 이 API를 호출하게
    # 되면 이 값을 명시 설정한다. oauth_redirect_uri_allowlist·trusted_proxy_ip_allowlist와
    # 동일 패턴: 콤마 구분 원시값 + 파싱 프로퍼티. 비면 *전부 거부*(deny-by-default) —
    # CORSMiddleware는 항상 등록되지만 allow_origins=[]이면 모든 브라우저 cross-origin
    # 요청을 거부한다(네이티브 앱은 영향 없음 — CORS는 브라우저가 강제하는 정책이다).
    cors_allowed_origins: str = Field(
        default="",
        description=(
            "브라우저 cross-origin 요청을 허용할 origin 화이트리스트(콤마 구분, 예: "
            "https://admin.whymath.kr). 비면 *전부 거부*(deny-by-default) — 네이티브 앱은 "
            "미영향. `*`는 `cors_allow_credentials=True`와 동시 사용 금지(부팅 시 예외로 "
            "거부 — CORS 자격증명 노출 취약점 방지). 환경변수 WHYMATH_CORS_ALLOWED_ORIGINS. "
            "시크릿 아님(공개 URL). 파싱된 리스트는 `cors_allowed_origins_list` 프로퍼티 참조."
        ),
    )
    cors_allow_credentials: bool = Field(
        default=False,
        description=(
            "CORS 응답에 자격증명(쿠키·Authorization 헤더 반영)을 허용할지. 기본 False — "
            "이 백엔드는 Bearer 토큰을 요청 헤더로 직접 보내므로(쿠키 미사용) 기본값을 켤 "
            "이유가 없다. True로 켤 때 `cors_allowed_origins`에 `*`가 있으면 부팅이 실패한다."
        ),
    )
    trusted_hosts_allowlist: str = Field(
        default="",
        description=(
            "TrustedHostMiddleware가 허용할 Host 헤더 화이트리스트(콤마 구분, 예: "
            "api.whymath.kr). 비면 `*`(전부 허용 — 현재 동작 무회귀·로컬 개발 편의 유지). "
            "배포 환경은 설정을 권장(Host 헤더 위조·캐시 포이즈닝 방지). 환경변수 "
            "WHYMATH_TRUSTED_HOSTS_ALLOWLIST. 시크릿 아님. 파싱된 리스트는 "
            "`trusted_hosts_list` 프로퍼티 참조."
        ),
    )

    @model_validator(mode="after")
    def _forbid_cors_wildcard_with_credentials(self) -> "Settings":
        """`*` + `allow_credentials=True` 조합을 부팅 시점에 거부(fail-closed).

        브라우저 CORS 스펙 자체가 이 조합을 금지하지만(Fetch 표준 — 자격증명 포함 요청엔
        와일드카드 origin이 허용되지 않아 브라우저가 응답을 버린다), 그 실패는 *브라우저에서*
        조용히 일어나 서버 쪽에서는 "동작하는 것처럼" 보인다. 여기서 즉시 예외를 내는 이유는
        와일드카드가 실수로 credentials와 함께 배포되는 순간을 부팅 실패로 만들어, 조용한
        보안 구멍이 되는 것을 막기 위함이다(CLAUDE.md "확실하지 않을 때 침묵 금지"와 동형).
        """
        if self.cors_allow_credentials and "*" in self.cors_allowed_origins_list:
            raise ValueError(
                "WHYMATH_CORS_ALLOWED_ORIGINS에 '*'와 WHYMATH_CORS_ALLOW_CREDENTIALS=true를 "
                "동시에 설정할 수 없습니다 — 자격증명 포함 CORS 응답에 와일드카드 origin은 "
                "허용되지 않습니다(SEC-26)."
            )
        return self

    # ── RPT-01: 학생 결함 신고(무인증 표면) IP 단위 rate limit ──
    defect_report_rate_limit_ip_per_minute: int = Field(
        default=20,
        ge=0,
        description=(
            "결함 신고(`POST /v1/reports/defects`)의 *IP 단위* 분당 요청 상한. 0=비활성. "
            "`user_id`를 저장하지 않는 무인증 표면이라 IP만 검사한다(user·device 차원 N/A). "
            "정상 사용자는 같은 세션에서 신고를 자주 반복하지 않으므로 20이면 여유롭고, "
            "coach `write`(60)와 별도 카테고리라 상호 영향 0."
        ),
    )
    coach_rate_limit_device_read_per_minute: int = Field(
        default=90,
        ge=0,
        description=(
            "L4 코치 *읽기* 엔드포인트의 *디바이스(X-Device-Id) 단위* 분당 요청 상한. "
            "0=비활성. 사용자(60)와 IP(120) 사이 중간 — 한 사용자가 다중 디바이스 가능하나 "
            "한 디바이스가 폭주하면 그 디바이스만 제한."
        ),
    )
    coach_rate_limit_device_write_per_minute: int = Field(
        default=45,
        ge=0,
        description=(
            "L4 코치 *쓰기* 엔드포인트의 *디바이스 단위* 분당 요청 상한. 0=비활성. "
            "사용자(30)와 IP(60) 사이 중간."
        ),
    )
    # ── 슬라이스 97: 시각화 LLM 엔드포인트 전용 rate limit (LLM 비용 보호) ──
    visualization_rate_limit_per_minute: int = Field(
        default=15,
        ge=0,
        description=(
            "시각화 생성(`POST /v1/visualizations/weak-concept`)의 *사용자 단위* 분당 상한. "
            "0=비활성. coach write(30)보다 낮음 — LLM 호출(생성·검증)이라 비용↑(coach는 "
            "프롬프트 결정만·LLM 미호출). 별 category로 coach write와 버킷 분리."
        ),
    )
    visualization_rate_limit_ip_per_minute: int = Field(
        default=30,
        ge=0,
        description=(
            "시각화 생성의 *IP 단위* 분당 상한. 0=비활성. 공유 NAT 방어(사용자 한도의 2배)."
        ),
    )
    visualization_rate_limit_device_per_minute: int = Field(
        default=22,
        ge=0,
        description="시각화 생성의 *디바이스 단위* 분당 상한. 0=비활성. 사용자(15)와 IP(30) 사이.",
    )
    # ── 슬라이스 27: 디바이스 store 운영 모드(lifespan 결선) ──
    device_store_mode: Literal["none", "pg", "pg_cached"] = Field(
        default="none",
        description=(
            "디바이스 자격증명 store 활성 모드. `none`(기본)=비활성·slice 21 공유 secret 폴백. "
            "`pg`=`PgDeviceStore` 단독(영속·HA, slice 23). "
            "`pg_cached`=`CachedDeviceStore(PgDeviceStore, Redis)`(verify 캐시·고QPS 최적화, "
            "slice 26). 운영 lifespan이 본 설정 읽어 store 자동 활성·종료 시 정리."
        ),
    )

    # ── 슬라이스 33: 디바이스 자동 폐기 idle 임계 ──
    device_credential_max_idle_days: int = Field(
        default=30,
        ge=1,
        description=(
            "`cleanup_stale_devices` 호출 시 *N일 이상 미사용*(last_used_at < now - N일·"
            "한 번도 사용 안 했으면 created_at 기준)인 활성 device를 자동 폐기. 30일 기본 — "
            "정상 사용자는 매월 1회 이상 verify(앱 사용)이라 무영향·잊혀진/분실 device만 폐기. "
            "운영은 Celery beat·cron으로 일일 호출 권장. 0 미만은 비활성 의도라 ge=1로 금지."
        ),
    )

    # ── 슬라이스 31: startup health check 타임아웃 ──
    device_store_health_check_timeout_seconds: float = Field(
        default=5.0,
        gt=0.0,
        description=(
            "부팅 시 `ping_device_store_health`가 각 의존성(PG·Redis) ping에 허용하는 최대 "
            "응답 시간(초). 초과 시 RuntimeError로 fail-fast — slice 30의 *무한 대기* 한계 "
            "해소. 기본 5s — 정상 인프라엔 충분(>1s면 인프라 점검 필요)·네트워크 깜빡임은 "
            "쿠버네티스 readiness probe로 외부 재시도."
        ),
    )

    # ── 슬라이스 35: startup health check 재시도(exponential backoff) ──
    device_store_health_check_max_retries: int = Field(
        default=3,
        ge=1,
        description=(
            "부팅 시 각 ping을 최대 N회 시도(첫 시도 포함). 일시적 인프라 깜빡임 흡수 — "
            "slice 30 한계 ③(재시도 없음) + slice 31 한계 ①(쿠버네티스 외부 재시도만) 해소. "
            "기본 3 — 정상 인프라엔 1회 통과·일시 실패 시 backoff 후 재시도. 1=재시도 비활성."
        ),
    )
    device_store_health_check_retry_backoff_seconds: float = Field(
        default=2.0,
        gt=0.0,
        description=(
            "재시도 사이 exponential backoff 기본 간격(초). 실제 대기는 `backoff * 2^attempt` "
            "(attempt=0,1,...): 2s·4s·8s. max_retries=3 시 총 대기 ~6s(timeout 별도 합산)."
        ),
    )
    device_store_health_check_retry_jitter: bool = Field(
        default=False,
        description=(
            "slice 36: 재시도 backoff에 AWS-style *full jitter* 적용"
            "(`uniform(0, base*2^attempt)`). k8s 다수 pod 동시 재시작 시 thundering herd"
            "(인프라 회복 직후 동시 재폭주) 차단. 기본 False — 단일 노드/예측 가능 backoff "
            "우선. 다중 pod 운영은 True 권장."
        ),
    )

    # ── 슬라이스 26: verify 결과 Redis 캐시 TTL ──
    device_verify_cache_ttl_seconds: int = Field(
        default=60,
        ge=0,
        description=(
            "디바이스 verify 결과 캐시 TTL(초). `CachedDeviceStore` 사용 시만 의미. "
            "낮을수록 revoke 후 stale 기간 짧음(권장 60s — DB 부담 절감과 invalidation "
            "신선도 절충). 0=캐시 비활성. 운영 lifespan에서 `CachedDeviceStore(inner, cache, "
            "ttl_seconds=settings.device_verify_cache_ttl_seconds)`로 주입."
        ),
    )
    # ── 슬라이스 48: count 캐시 TTL(verify와 별 — count는 register/revoke만 영향) ──
    device_count_cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        description=(
            "디바이스 count 캐시 TTL(초). count는 verify보다 갱신 빈도 *낮음*"
            "(register/revoke만 영향·verify는 영향 0) → 더 긴 TTL로 cache hit rate 향상. "
            "기본 300s(5분). register/revoke 시 즉시 invalidate되므로 stale 위험 ≈ 0. "
            "0=count 캐시 비활성(verify_ttl로 폴백)."
        ),
    )
    # ── 슬라이스 49: include_revoked=True count 전용 TTL ──
    device_count_all_cache_ttl_seconds: int | None = Field(
        default=None,
        ge=0,
        description=(
            "`include_revoked=True` count 전용 TTL(초). 폐기 이력 포함 count는 *훨씬 드물게* "
            "조회됨(주로 보안 감사·관리자 화면) → 더 긴 TTL로 hit rate 향상 가능. None(기본)이면 "
            "`device_count_cache_ttl_seconds` 그대로 사용(slice 48 backward compat). "
            "운영 보고로 active와 all 사용 빈도 차이 확인 후 조정."
        ),
    )

    # ── 슬라이스 25: 디바이스 등록 전용 rate limit (`/v1/devices/register`) ──
    device_register_rate_limit_per_minute: int = Field(
        default=5,
        ge=0,
        description=(
            "디바이스 등록(`POST /v1/devices/register`)의 *사용자 단위* 분당 상한. 0=비활성. "
            "등록은 드문 작업(첫 실행 1회·기기 변경)이라 매우 낮게 — sock-puppet 디바이스 "
            "양산·DB 자격증명 폭증 차단. coach `write`와 *별 키 공간*"
            "(category=device_register)."
        ),
    )
    device_register_rate_limit_ip_per_minute: int = Field(
        default=10,
        ge=0,
        description=(
            "디바이스 등록의 *IP 단위* 분당 상한. 0=비활성. 공유 NAT/학교/공공 와이파이에서 "
            "여러 사용자가 등록 가능하도록 사용자 한도(5)의 2배."
        ),
    )
    device_secret_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "slice 72: 디바이스 secret at-rest 봉투 암호화 마스터 키(base64 인코딩 32바이트="
            "AES-256). DB 밖(env/Settings)에 두어 DB dump만으로는 secret 복호 불가하게 한다. "
            "**SEC-28**: 빈 값은 개발/CI에서만 평문 폴백을 허용하고, prod-like 환경(실 OAuth "
            "provider 구성)에서는 `require_device_secret_cipher`가 RuntimeError로 부팅을 "
            "거부한다. `WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY` env로만 주입(SecretStr — repr/"
            "로그 평문 차단·하드코딩 금지). "
            '키 생성: `python -c "import base64,os; '
            'print(base64.b64encode(os.urandom(32)).decode())"`. 진짜 KMS(HSM)는 후속.'
        ),
    )
    device_secret_decryption_fallback_keys: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "slice 75: 키 회전용 *복호 전용* fallback 키 목록(쉼표 구분 base64 32바이트). "
            "primary 키 회전 시 구 키를 여기 두면 구 키로 암호화된 행이 lockout 없이 복호된다 "
            "(encrypt는 항상 primary). 전 행 재암호화 후 제거. 빈 값=fallback 없음. "
            "`WHYMATH_DEVICE_SECRET_DECRYPTION_FALLBACK_KEYS` env(SecretStr·하드코딩 금지)."
        ),
    )

    dialogue_content_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "감사상환 #2: 미성년 대화 본문(`dialogue_turn.content`) at-rest 봉투 암호화 마스터 "
            "키(base64 인코딩 32바이트=AES-256). 빈 값=암호화 비활성(평문 저장·기존 동작 폴백·"
            "점진 도입). **device secret 키와 분리**(폭발 반경 축소 — 한 키 유출이 다른 자산으로 "
            "번지지 않음). DB 밖(env/Settings)에 두어 DB dump만으로는 채팅 본문 복호 불가하게 "
            "한다(CLAUDE.md 절대 금기 '미성년 채팅 평문 저장 금지'의 기계적 시행). "
            "`WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY` env로만 주입(SecretStr — repr/로그 평문 "
            '차단·하드코딩 금지). 키 생성: `python -c "import base64,os; '
            'print(base64.b64encode(os.urandom(32)).decode())"`.'
        ),
    )
    dialogue_content_decryption_fallback_keys: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "대화 본문 키 회전용 *복호 전용* fallback 키 목록(쉼표 구분 base64 32바이트). "
            "primary 키 회전 시 구 키를 여기 두면 구 키로 암호화된 행이 lockout 없이 복호된다 "
            "(encrypt는 항상 primary). 전 행 재암호화(백필) 후 제거. 빈 값=fallback 없음. "
            "`WHYMATH_DIALOGUE_CONTENT_DECRYPTION_FALLBACK_KEYS` env(SecretStr·하드코딩 금지)."
        ),
    )

    evidence_payload_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "PED-01: 미성년 학습 증거 payload(`evidence_event.payload_encrypted`) at-rest 봉투 "
            "암호화 마스터 키(base64 32바이트=AES-256). 빈 값=암호화 비활성 → 증거는 *메타 전용*"
            "으로만 적재(evidence_event엔 평문 컬럼이 없어 원문 payload는 저장하지 않음·B1). "
            "**dialogue·device secret 키와 분리**(폭발 반경 축소). DB 밖(env/Settings)에 두어 DB "
            "dump 단독 복호 불가. `WHYMATH_EVIDENCE_PAYLOAD_ENCRYPTION_KEY` env로만 주입(SecretStr "
            '— repr/로그 평문 차단·하드코딩 금지). 키 생성: `python -c "import base64,os; '
            'print(base64.b64encode(os.urandom(32)).decode())"`.'
        ),
    )
    evidence_payload_decryption_fallback_keys: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "증거 payload 키 회전용 *복호 전용* fallback 키 목록(쉼표 구분 base64 32바이트). "
            "primary 회전 시 구 키를 여기 두면 구 키 암호화 행이 lockout 없이 복호된다(encrypt는 "
            "항상 primary). 빈 값=fallback 없음. "
            "`WHYMATH_EVIDENCE_PAYLOAD_DECRYPTION_FALLBACK_KEYS` env(SecretStr·하드코딩 금지)."
        ),
    )

    student_work_encryption_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "SEC-31: 학생 답안·풀이 본문(`problem_attempt`·`answer_submission`·"
            "`student_solution_step` 3테이블) at-rest 봉투 암호화 마스터 키(base64 인코딩 "
            "32바이트=AES-256). 빈 값=암호화 비활성(평문 저장·기존 동작 폴백·점진 도입). "
            "**dialogue·evidence payload·device secret 키와 분리**(폭발 반경 축소 — 한 키 유출이 "
            "다른 자산으로 번지지 않음). 3테이블은 *같은* 키를 공유한다 — 한 답안 제출 흐름 안에서 "
            "함께 쓰이는 같은 데이터 주체의 같은 논리적 사건이라(dialogue_turn 내부 3축 공유 "
            "논리의 확장), 테이블별로 쪼개도 폭발 반경이 줄지 않는 반면 '미설정→평문 폴백' 함정만 "
            "늘어난다. DB 밖(env/Settings)에 두어 DB dump만으로는 답안·풀이 본문 복호 불가하게 "
            "한다(CLAUDE.md 절대 금기 '학생 데이터=민감 정보 암호화 저장'의 기계적 시행). "
            "`WHYMATH_STUDENT_WORK_ENCRYPTION_KEY` env로만 주입(SecretStr — repr/로그 평문 차단·"
            '하드코딩 금지). 키 생성: `python -c "import base64,os; '
            'print(base64.b64encode(os.urandom(32)).decode())"`.'
        ),
    )
    student_work_decryption_fallback_keys: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "학생 답안·풀이 키 회전용 *복호 전용* fallback 키 목록(쉼표 구분 base64 32바이트). "
            "primary 키 회전 시 구 키를 여기 두면 구 키로 암호화된 행이 lockout 없이 복호된다 "
            "(encrypt는 항상 primary). 전 행 재암호화(백필) 후 제거. 빈 값=fallback 없음. "
            "`WHYMATH_STUDENT_WORK_DECRYPTION_FALLBACK_KEYS` env(SecretStr·하드코딩 금지)."
        ),
    )

    coach_device_hmac_secret: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "디바이스 서명 검증용 HMAC 비밀키. 빈 기본=비활성(슬라이스 20 동작 그대로). "
            "설정 시 클라이언트는 `X-Device-Sig: HMAC-SHA256(secret, device_id) hex`를 동봉 — "
            "유효하지 않으면 device 차원 검사 비활성(fail-safe·user+IP만 적용). "
            "**위협 모델**: 앱 바이너리에서 secret 추출 가능 — *trivial spoofing*(랜덤 ID "
            "반복) 방어용. 정식 디바이스 인증은 OAuth-style 등록 후속. WHYMATH_COACH_DEVICE_"
            "HMAC_SECRET env로만 주입(SecretStr — repr/로그 평문 차단·하드코딩 금지)."
        ),
    )
    coach_rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "rate limit 백엔드 — `memory`=프로세스-로컬 deque(기본·테스트·로컬), "
            "`redis`=Redis ZSET sliding window(분산/HA 정합·다중 워커/인스턴스 시 필수). "
            "`redis` 선택 시 `redis_url`로 연결, 라이브 도달성은 lazy."
        ),
    )

    # ── 슬라이스 104: L4 오개념 *의미(임베딩) 매칭* 좌석 (substring 거짓음성 보완) ──
    # L4 SemanticMatcher가 카탈로그 표현·학생 텍스트를 임베딩해 코사인 유사도로 패러프레이즈·
    # 동의어를 잡는다(substring AND가 못 잡던 *의미 recall*). **정직 스코프**: 임베딩은 의미
    # recall만 개선하고 *방향·부정·등치*("연속⇒미분" vs 역)는 substring과 똑같이 못 가린다
    # (방향 판별은 LLM-judged/NLI 후속 — docs/prompts/misconception_diagnosis.md §의미 매칭 층).
    # 기본은 `local`(bge-m3·로컬 우선·CLAUDE.md 비용·Phaiakes9). 라이브 로드는 *지연 import*라
    # 이 설정만으로는 모델 다운로드·네트워크가 일어나지 않는다(CI hermetic).
    embedding_provider: Literal["local", "openai", "fake"] = Field(
        default="local",
        description=(
            "오개념 의미 매칭 임베딩 제공자. `local`(기본)=sentence-transformers bge-m3(로컬 "
            "우선·Phaiakes9). `openai`=text-embedding-3-large(클라우드·키 필요). `fake`=결정론 "
            "해시 벡터(테스트·CI hermetic 전용·라이브 의존 0). 좌석 선택만이고 실제 모델 로드는 "
            "지연(import 시점이 아니라 첫 embed 호출 시)."
        ),
    )
    embedding_model_local: str = Field(
        default="BAAI/bge-m3",
        description=(
            "로컬(sentence-transformers) 임베딩 모델 ID. 기본 bge-m3(다국어·한국어 강건). "
            "WHYMATH_EMBEDDING_MODEL_LOCAL로 오버라이드. 시크릿 아님."
        ),
    )
    embedding_model_openai: str = Field(
        default="text-embedding-3-large",
        description=(
            "OpenAI 임베딩 모델 ID(embedding_provider=openai일 때). 기본 text-embedding-3-large "
            "(CLAUDE.md 임베딩 표준). WHYMATH_EMBEDDING_MODEL_OPENAI로 오버라이드. 시크릿 아님."
        ),
    )
    openai_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "OpenAI API 키(sk-...). SecretStr — repr/로그 평문 노출 안 됨. 기본값 없음(빈 = "
            "미설정). 환경변수 WHYMATH_OPENAI_API_KEY로만 주입(CLAUDE.md 보안 금기: 하드코딩 "
            "금지). 비면 OpenAIEmbeddingProvider는 명확한 오류(조용한 폴백 금지)."
        ),
    )
    misconception_semantic_threshold: float = Field(
        default=0.55,
        ge=-1.0,
        le=1.0,
        description=(
            "오개념 의미 매칭 코사인 임계값(이 *미만*은 미매칭). 보수적 기본 0.55 — 거짓양성 "
            "억제(짧은 공통 토큰의 의미 근접 오탐 방지). semantic_matches(threshold=)로 호출별 "
            "오버라이드 가능. WHYMATH_MISCONCEPTION_SEMANTIC_THRESHOLD로 전역 조정."
        ),
    )
    misconception_judge_routing: Literal["fast_math", "general_mid"] = Field(
        default="fast_math",
        description=(
            "오개념 방향 판별 judge 라우팅 프로파일(슬108 후속·측정 실험용). **`fast_math`"
            "(기본·현행)** = 로컬 FAST MATH(qwen2-math:1.5b). 단 2026-06-15 라이브 측정에서 "
            "한국어 판정 형식(`판정: 예/아니오/불확실`) 미준수로 전부 UNCERTAIN→FP 감소 0(작은 "
            "수학 모델이 NLP 분류·형식 준수에 부적합). **`general_mid`** = GENERAL MID"
            "(qwen2.5:7b)로 라우팅해 형식 준수·방향 판별 재측정(판단은 NLP 분류라 일반 instruct "
            "모델 적합). judge는 coach 미배선이라 이 값은 *측정 경로*(CLI `--judge`·통합 "
            "테스트)에만 영향. WHYMATH_MISCONCEPTION_JUDGE_ROUTING로 전환."
        ),
    )

    misconception_semantic_mode: Literal["off", "shadow", "on"] = Field(
        default="off",
        description=(
            "L4 coach 오개념 진단의 *의미(임베딩) 매칭 결합* 모드(slice 106·111). 3값: "
            "**`off`(기본·opt-in)** = coach는 substring `diagnose()`만(현행 비트동일·의미 매처 "
            "미호출·임베딩 로드 0). **`shadow`** = 의미 매처를 *라이브로 돌리되* 노출은 substring "
            "그대로(off와 동일)이고 substring↔semantic *불일치만 로깅*한다(slice 111·step_shadow "
            "미러·비노출·학생 원문 미포함) — 합성 프로브가 아닌 *실 분포*에서 플립 근거 수집. "
            "**`on`** = substring 아래에 semantic-only 후보를 결합해 *노출*(combine_diagnoses·"
            "substring 우선·재정렬 없음). shadow·on의 의미 매칭은 *비블로킹*(asyncio.to_thread)·"
            "실패 시 substring graceful 폴백(200 유지)·matches[0]은 substr면 항상 substr. 기본 "
            "off는 ① bge-m3 로드 비용 ② 방향맹 FP를 보수적으로 막기 위함. `l4_step_shadow_enabled` "
            "미러. WHYMATH_MISCONCEPTION_SEMANTIC_MODE=shadow|on으로 켠다."
        ),
    )

    misconception_judge_enabled: bool = Field(
        default=False,
        description=(
            "L4 coach 오개념 진단에 *방향 판별 LLM-judge 필터*(slice 108)를 켤지. **False(기본·"
            "opt-in)·이번 슬라이스 미사용**: 슬108은 judge 코어 + 측정 하니스만 만들고 coach에 "
            "*배선하지 않는다*(라이브 judge 효과를 Kiki Phaiakes9 측정 후 후속 슬라이스에서 결정). "
            "이 플래그는 그 후속 coach 배선용 *예약*이다 — 현재 어떤 런타임 경로도 읽지 않는다"
            "(`_compute_matches` 무변경). True여도 이번 슬라이스엔 동작 변화 0. judge는 substring·"
            "임베딩이 못 가리는 방향(⇒ 역)·부정(≠)·등치(=)를 언어 추론으로 판별해 `아니오`(올바름/"
            "다른 말) 후보만 거른다(예·불확실 유지·recall 보존). 라우팅/모델은 L3 재사용(로컬 "
            "FAST·라우터 경유). `l4_step_shadow_enabled`·`misconception_semantic_mode` 미러. "
            "WHYMATH_MISCONCEPTION_JUDGE_ENABLED=true로 켠다(후속)."
        ),
    )

    misconception_judge_shadow: bool = Field(
        default=False,
        description=(
            "L4 coach 오개념 진단에서 *judge would-be shadow 로깅*(G1·04b Phase 1)을 켤지. "
            "**False(기본·opt-in)·현행 비트동일**: 노출(student-facing)은 *절대 불변*이고, "
            '`misconception_semantic_mode=="shadow"`일 때만 효력이 있다(매처가 라이브로 도는 '
            "그 경로에서, 의미 후보에 judge를 *비차단*으로 돌려 *걸러질 결과*(would-be removed/"
            "kept)를 무노출로 로깅). 노출 전 실데이터로 judge 효과를 검증하기 위함(합성↔실 갭). "
            "**매처 shadow(`misconception_semantic_mode`·싸다)와 비용 분리**: judge는 LLM(수 초)"
            "이라 매처 shadow와 on/off가 *독립*이어야 한다(이 플래그가 별 토글). judge는 응답 "
            "경로를 *지연시키지 않는다* — fire-and-forget(asyncio.create_task)으로 띄우고 즉시 "
            "반환한다(coach는 judge를 await하지 않음). 레코드엔 *학생 원문·judge reason 미저장* "
            "(미성년 PII — verdict 카운트·id·임계만). `misconception_judge_enabled`(노출 게이트)와 "
            "별개다(이쪽은 노출 필터·저쪽은 비노출 측정). "
            "WHYMATH_MISCONCEPTION_JUDGE_SHADOW=true로 켠다."
        ),
    )

    misconception_crosslink_mode: Literal["off", "shadow"] = Field(
        default="off",
        description=(
            "L4 오개념 게이트의 *kebab-id → M-id crosswalk 해석 shadow 측정* 모드(게이트 공존 배선·"
            "math_dsl_remediation_design.md §1.3 step3). 2값: **`off`(기본·opt-in)** = 게이트는 "
            "kebab-id만 쓰고(현행 비트동일) crosswalk 조회 0. **`shadow`** = 게이트(증거 저장소 "
            "`log_evidence`)가 kebab-id를 *그대로* 런타임 키로 쓰되(노출·DB 저장 불변), crosswalk "
            "resolver로 그 kebab-id의 canonical M-id 매핑을 *비차단·비노출*로 해석해 coverage(매핑 "
            "유무·1:N)를 *로그로만* 남긴다(`crosslink_shadow`·shadow.py 미러). crosswalk 테이블은 "
            "사람 검수 전까지 비어 있어 보통 미매핑([]) — 매핑이 차오르는 분포를 노출 전 수집해 "
            "canonical id 플립(canary→full) 근거를 모은다. shadow의 resolve는 비블로킹"
            "(asyncio.to_thread)·실패 시 적재 graceful 진행(증거 무결성 우선). 기본 off는 빈 "
            "테이블에 per-write DB 왕복을 피하기 위함 — 측정 윈도에만 켠다(semantic_mode 미러). "
            "WHYMATH_MISCONCEPTION_CROSSLINK_MODE=shadow로 켠다."
        ),
    )

    misconception_wrong_form_mode: Literal["off", "shadow"] = Field(
        default="off",
        description=(
            "오개념 *거짓 항등식 SymPy 탐지* shadow 측정 모드(감사 §7·동치 권위 일원화). 2값: "
            "**`off`(기본·opt-in)** = 기존 substring/regex 탐지만(현행 비트동일·SymPy 미호출). "
            "**`shadow`** = coach가 학생 풀이의 등식을 추출해 `canonical_wrong_form`을 SymPy Wild "
            "정합(`wrong_form_match`)으로 *비차단·비노출* 탐지하고, 기존 결과와 비교(SymPy-only·"
            "일치)를 *로그로만* 남긴다 — 노출(diagnose 반환)·verdict 불변. 기호(`(x+y)²=x²+y²`·"
            "변수명 무관)·수치(`(3+4)²=3²+4²`·구조보존 파싱) 인스턴스를 잡고, 우연히 참인 등식은 "
            "거짓-등식 가드로 제외한다(substring이 놓치는 표기 변이 일반화). 노출 전 분포 측정. "
            "WHYMATH_MISCONCEPTION_WRONG_FORM_MODE=shadow로 켠다."
        ),
    )

    # ── 슬라이스 105: 오개념 임베딩 *영속(pgvector) 백엔드* 좌석 선택 ──
    # 슬104 VectorIndex 좌석에 PgVectorIndex(pgvector 백엔드)를 추가한다. **기본은 `memory`**
    # (InMemoryVectorIndex·기본 동작 무변경) — pgvector는 *opt-in*이다. 카탈로그 30종엔
    # in-memory 선형 스캔이 최적이고(슬104 docstring), pgvector는 *영속화 + 스케일 코퍼스
    # groundwork*다(과장 금지 — 30종에 pgvector가 더 빠르다고 주장하지 않는다). 슬98 결정
    # (벡터 DB=pgvector·Postgres 16 통합)의 첫 실 결선 자리.
    vector_store: Literal["memory", "pgvector"] = Field(
        default="memory",
        description=(
            "오개념 의미 매칭 벡터 인덱스 백엔드. `memory`(기본)=InMemoryVectorIndex(코사인 "
            "선형 스캔·카탈로그 30종 최적·라이브 의존 0). `pgvector`=PgVectorIndex(PostgreSQL "
            "pgvector 영속화·스케일 groundwork·sync psycopg 격리 엔진). `pgvector` 선택 시에만 "
            "psycopg/pgvector를 *지연 import*하므로 기본(memory) 경로는 sync 드라이버 불요. "
            "WHYMATH_VECTOR_STORE로 조정."
        ),
    )
    embedding_dim: int = Field(
        default=1024,
        ge=1,
        description=(
            "PgVectorIndex `misconception_embedding.embedding` 컬럼 차원(pgvector `vector(N)`). "
            "기본 1024(bge-m3). 임베딩 *모델*과 일치해야 한다(Fake 64·OpenAI te-3-large 3072). "
            "30종 코퍼스는 seq-scan이라 고정 차원이 검색 성능엔 무관하나, SQLAlchemy `Vector` "
            "타입·마이그레이션이 차원을 박으므로 모델 교체 시 이 값과 마이그레이션을 함께 "
            "맞춘다(in-memory 경로는 무관 — 차원 무지정 동작). WHYMATH_EMBEDDING_DIM로 조정."
        ),
    )

    # ── L5 OCR 서브시스템 (손글씨 풀이 인식·기본 OFF·opt-in) ──
    # OCR는 무거운 모델(rapidocr·rapid_latex_ocr 등)을 쓰므로 기본 비활성이다(extra [ocr]
    # 미설치 환경·CI hermetic 보호). True여야 lifespan이 부품을 적재해 /v1/ocr가 활성화된다.
    # 부품은 *지연 import*라 이 설정·구성만으로는 모델 다운로드·네트워크가 일어나지 않는다.
    ocr_enabled: bool = Field(
        default=False,
        description=(
            "L5 OCR 서브시스템(손글씨 풀이 인식·POST /v1/ocr) 활성 여부. **기본 False(opt-in·"
            "prod 안전)**: rapidocr·rapid_latex_ocr 등 무거운 의존이 extra [ocr]라 미설치 "
            "환경·CI에서 끈다. True면 lifespan이 `build_ocr_components`로 부품을 적재해 "
            "app.state에 올린다(실패해도 fail-fast 아님·경고 로그). WHYMATH_OCR_ENABLED로 켠다."
        ),
    )
    ocr_language: Literal["ko", "en", "korean"] = Field(
        default="korean",
        description=(
            "OCR 텍스트 인식 언어(rapidocr 한글 모델). 기본 korean(한국 학생 손글씨 산문). "
            "ko/en은 별칭·축약. WHYMATH_OCR_LANGUAGE로 조정. 시크릿 아님."
        ),
    )
    ocr_recognizer_backend: Literal["rapid_latex", "texteller", "qwen_vl"] = Field(
        default="rapid_latex",
        description=(
            "수식 인식 백엔드 좌석. `rapid_latex`(기본·Phase A)=rapid_latex_ocr(경량 ONNX). "
            "`texteller`(Phase C·실배선)=transformers TexTeller(손글씨 강건·extra [ocr-heavy]). "
            "`qwen_vl`(Phase C·실배선·비동기 전용)=Qwen3-VL 멀티모달(*반드시 L3 라우터 경유*· "
            "Ollama 직접 호출 금지 — factory가 provider/cache/trace를 주입하며 미주입이면 "
            "RuntimeError). 셋 다 배선돼 있고 미검증인 것은 *구현*이 아니라 *라이브 정확도*다 "
            "(2026-08-04 nlp_module_gap_review_r2.md §1-② 정정 — 이 설명이 texteller·qwen_vl을 "
            "'스텁·미배선'이라 기술해 실제보다 못하다고 말하던 stale을 바로잡았다. 근거: "
            "l5/ocr/factory.py `_build_recognizer` · l5/ocr/recognize.py `TexTellerRecognizer`/ "
            "`QwenVlRecognizer`). WHYMATH_OCR_RECOGNIZER_BACKEND로 조정."
        ),
    )
    ocr_detector: Literal["paddle", "mfd"] = Field(
        default="paddle",
        description=(
            "영역 검출기 좌석. `paddle`(기본·Phase A)=rapidocr 텍스트 라인 검출(휴리스틱 라우터가 "
            "수식을 가름). `mfd`(Phase B)=rapid-layout PP 계열(Apache-2.0)로 수식 영역을 별도 "
            "검출(2D 수식을 한 덩어리로). WHYMATH_OCR_DETECTOR로 조정. 시크릿 아님."
        ),
    )
    ocr_mfd_model_type: Literal[
        "pp_layout_cdla", "pp_layout_publaynet", "pp_doc_layoutv2", "pp_doc_layoutv3"
    ] = Field(
        default="pp_layout_cdla",
        description=(
            "MFD(Phase B) 레이아웃 모델 — rapid-layout PP 계열(**Apache-2.0**)만 허용한다. "
            "`pp_layout_cdla`(기본)는 '공식(Equation)' 클래스를, PP-DocLayout는 'formula'를 준다. "
            "ultralytics 기반(yolov8*/doclayout*)은 AGPL-3.0이라 *허용하지 않는다*(우선순위 #2). "
            "WHYMATH_OCR_MFD_MODEL_TYPE로 조정. 시크릿 아님."
        ),
    )
    ocr_mfd_weights_path: str = Field(
        default="",
        description=(
            "MFD 수식 영역 검출 커스텀 가중치 경로 좌석(rapid-layout 기본 모델 외 핀 모델용). "
            "빈 값(기본)=rapid-layout 기본 PP 모델 사용. WHYMATH_OCR_MFD_WEIGHTS_PATH로 주입."
        ),
    )
    ocr_model_dir: str = Field(
        default="",
        description=(
            "OCR 검출/인식 커스텀 모델 디렉토리 좌석. 빈 값(기본)=rapidocr 기본 모델 사용. "
            "오프라인/핀 모델은 WHYMATH_OCR_MODEL_DIR로 주입. 시크릿 아님."
        ),
    )
    ocr_min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "OCR 영역 인식 신뢰도 하한 좌석(0~1). 기본 0.0=필터 비활성(모든 영역 통과·현 동작). "
            "향후 이 미만 영역을 거르거나 재확인 유도에 쓴다(coach <0.8 게이트와 별). "
            "WHYMATH_OCR_MIN_CONFIDENCE로 조정."
        ),
    )

    # ── OPS-01: 프로덕션 관측·알림 (인프로세스 이중 회계 축) ──
    # 에러율·지연 판정치는 SaaS(Langfuse)가 아니라 *프로세스 안*에서도 산출한다
    # (ops/cost_probe 선례 — 관측 인프라가 죽으면 '측정 실패'가 보여야지 0/정상으로
    # 위장되면 안 된다). 아래 임계는 /health/ready body.alerts + 상태 전이 warning
    # 로그(ops/service_health.py)가 공유한다.
    ops_error_rate_alert_threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "최근 창(고정 크기 deque) 5xx 에러율 알림 임계. *초과 시* breach — "
            "/health/ready body.alerts 상시 노출 + 상태 전이 시 warning 로그"
            "(ops/service_health.py). 기본 0.05(5%). 경계 동률(==)은 비위반. "
            "WHYMATH_OPS_ERROR_RATE_ALERT_THRESHOLD로 조정."
        ),
    )
    ops_latency_p95_alert_ms: float = Field(
        default=5000.0,
        gt=0.0,
        description=(
            "최근 창 p95 지연(ms) 알림 임계. *초과 시* breach(경로는 에러율과 동일). "
            "기본 5000ms — 학생 대면 p50<2s 목표의 보수적 상위 가드(p95는 QUALITY 큐잉·"
            "클라우드 동기 경로가 섞여 p50보다 느슨하게 둔다). "
            "WHYMATH_OPS_LATENCY_P95_ALERT_MS로 조정."
        ),
    )
    ops_metrics_window_size: int = Field(
        default=500,
        ge=1,
        description=(
            "인프로세스 요청 계측의 최근 창 크기(요청 수·고정 deque maxlen). 에러율·p95는 "
            "이 창에서 계산한다 — 전 기간 평균은 최근 악화를 희석하므로 최근 창이 알림 "
            "판정선이다. 기본 500. WHYMATH_OPS_METRICS_WINDOW_SIZE로 조정."
        ),
    )

    # ── OPS-17: 클라 버전 계약 게이트 ──
    # 클라(`X-App-Version` 헤더)가 서버 계약과 어긋나는 구버전으로 고착되는 것을 막는 최소
    # 허용 버전 임계(app.py `_service_metrics_middleware` 좌석 — 신규 미들웨어 아님). 형식은
    # `X.Y.Z`(빌드번호 없음·클라가 그대로 보냄), 비교는 정수 3튜플(외부 semver 라이브러리 불요).
    min_app_version: str = Field(
        default="0.0.0",
        description=(
            "클라이언트 최소 허용 버전(`X.Y.Z`, 빌드번호 없음). 기본 0.0.0 — 사실상 게이트 "
            "비활성(모든 버전이 통과, 기존 클라이언트 무영향). 올리면(예: 0.2.0) 그 미만 "
            "`X-App-Version`은 426 Upgrade Required로 차단된다(app.py "
            "_service_metrics_middleware 좌석 — 401/404/422와 구분되는 전용 사유코드). 헤더 "
            "부재(이 기능 배포 이전의 구버전 클라)나 파싱 불가한 버전 문자열은 '미달'과 다른 "
            "'미상'으로만 관측하고 차단하지 않는다(app.py 경량 카운터·기존 클라 보호). "
            "WHYMATH_MIN_APP_VERSION으로 조정."
        ),
    )

    @property
    def sync_database_url(self) -> str:
        """`database_url`(async asyncpg)에서 *sync psycopg* 드라이버 URL을 파생(슬105).

        PgVectorIndex는 슬104 `VectorIndex` Protocol이 *동기*라 sync SQLAlchemy 엔진을
        쓴다(03a 로컬-우선처럼 *벡터 store 좌석에 한정*해 sync 드라이버 도입 — async 앱
        엔진은 무변경). 자격증명·호스트·DB명은 그대로 보존하고 *드라이버만* `+psycopg`로
        바꾼다. 문자열 치환이 아니라 `make_url(...).set(drivername=...)`로 파싱·재조립해
        패스워드 인코딩·포트 등 엣지를 안전 처리한다(시크릿은 코드에 0 — `database_url`이
        env에서 오고 이 프로퍼티는 변환만). asyncpg가 아닌 다른 드라이버(예: 이미 psycopg)면
        그대로 psycopg로 정규화한다(드라이버 토큰만 교체).

        **`ssl` → `sslmode` 파라미터명 이식**: asyncpg는 SSL 모드를 쿼리파라미터 `ssl=`
        (예: `ssl=disable`, asyncpg `SSLMode.parse` 지원값)로 받지만, psycopg/libpq는
        같은 개념을 `sslmode=`로 받는다(`ssl=`은 psycopg에서 `invalid connection option
        "ssl"`로 즉시 실패 — 실측 확인). 드라이버만 바꾸는 이 프로퍼티의 취지상 값도 드라이버
        관례에 맞게 이식해야 두 드라이버 모두에서 유효한 URL이 된다. 값 자체는 두 드라이버가
        같은 enum 이름(disable/allow/prefer/require/verify-ca/verify-full)을 쓰므로 키만
        바꾸면 된다.
        """
        from sqlalchemy.engine import make_url

        url = make_url(self.database_url).set(drivername="postgresql+psycopg")
        if "ssl" in url.query:
            query = dict(url.query)
            query["sslmode"] = query.pop("ssl")
            url = url.set(query=query)
        return url.render_as_string(hide_password=False)

    @property
    def openai_configured(self) -> bool:
        """OpenAI API 키가 채워졌는가(임베딩 클라우드 호출 가능 여부, 슬104).

        비어 있으면 미설정 — OpenAIEmbeddingProvider는 첫 embed에서 명확한 오류를 던진다
        (조용한 폴백 금지·CLAUDE.md "모르면 모른다고"). 값은 로그에 남기지 않는다.
        """
        return bool(self.openai_api_key.get_secret_value())

    @property
    def langfuse_configured(self) -> bool:
        """Langfuse 공개키·시크릿키가 *둘 다* 채워졌는가(전송 가능 여부).

        하나라도 비어 있으면 미설정으로 보고 LangfuseSink는 no-op이 된다. SecretStr는
        `get_secret_value()`로만 평문을 꺼내며, 여기서는 *비어 있는지*만 본다(값 로그 X).
        """
        return bool(self.langfuse_public_key) and bool(self.langfuse_secret_key.get_secret_value())

    @property
    def anthropic_configured(self) -> bool:
        """Anthropic API 키가 채워졌는가(클라우드 생성 가능 여부, S5).

        비어 있으면 미설정으로 보고 AnthropicProvider는 클라우드 결정에 명확한 오류를
        던진다(조용한 LOCAL 강등 금지 — 라우터가 정당한 이유로 클라우드를 택했으므로).
        SecretStr는 `get_secret_value()`로만 평문을 꺼내며, 여기서는 *비어 있는지*만 본다.

        ARCH-66: `anthropic_api_enabled`가 꺼져 있으면 키가 있어도 False다(사용 중단 방침).
        원인 구분은 `anthropic_policy_blocked`로 한다 — 오류·리포트가 "키 없음"과
        "정책 차단"을 섞어 보고하지 않게.
        """
        return self.anthropic_api_enabled and bool(self.anthropic_api_key.get_secret_value())

    @property
    def anthropic_policy_blocked(self) -> bool:
        """키는 있으나 ARCH-66 사용 중단 방침으로 막힌 상태인가."""
        return (not self.anthropic_api_enabled) and bool(self.anthropic_api_key.get_secret_value())

    @property
    def deepseek_configured(self) -> bool:
        """DeepSeek 공식 API 키가 채워졌는가(CN 관할 직행 경로 가능 여부, ARCH-49).

        `anthropic_configured`와 같은 형태 — 비어 있으면 DeepSeekProvider가 명확한 오류를
        던진다(조용한 강등 금지). 값은 로그에 남기지 않는다.
        """
        return bool(self.deepseek_api_key.get_secret_value())

    @property
    def openrouter_configured(self) -> bool:
        """OpenRouter 키가 채워졌는가(서방 공급사 경유 가능 여부, ARCH-49).

        키만으로는 부족하다 — 호출은 `openrouter_allowed_providers`가 **비어 있지 않을**
        때만 성립한다(빈 허용목록은 '아무나 허용'이 아니라 '차단'이다). 그 검사는
        provider 쪽 계약이고, 여기서는 전송 가능 여부(키 존재)만 본다.
        """
        return bool(self.openrouter_api_key.get_secret_value())

    @property
    def jwt_configured(self) -> bool:
        """JWT 시크릿이 채워졌는가(토큰 발급/검증 가능 여부).

        비어 있으면 미설정 — `create_access_token`/`decode_access_token`이 명확한 오류를
        던진다(빈 시크릿으로 토큰을 발급/검증하는 사고 방지). 값은 로그에 남기지 않는다.
        """
        return bool(self.jwt_secret_key.get_secret_value())

    @property
    def pii_audit_ip_salt_configured(self) -> bool:
        """개인정보 감사(SEC-09) IP 해싱 salt가 채워졌는가.

        비어 있으면 미설정 — `privacy.audit.hash_client_ip`가 프로덕션 추정 환경에서는
        RuntimeError, 개발·CI에서는 경고 후 ip_hash=None으로 감사 행을 계속 적재한다. 값은
        로그에 남기지 않는다.
        """
        return bool(self.pii_audit_ip_salt.get_secret_value())

    @property
    def kakao_configured(self) -> bool:
        """카카오 로그인이 구성됐는가(client_id 존재). 비면 콜백 레지스트리에서 제외(404)."""
        return bool(self.kakao_client_id)

    @property
    def naver_configured(self) -> bool:
        """네이버 로그인이 구성됐는가(client_id 존재). 비면 콜백 레지스트리에서 제외(404)."""
        return bool(self.naver_client_id)

    @property
    def oauth_redirect_uris(self) -> list[str]:
        """`oauth_redirect_uri_allowlist`(콤마 구분 원시값)를 파싱한 리스트(공백 제거·빈 항목 제외).

        빈 리스트면 deny-by-default(모든 redirect_uri 거부) — `api/auth.py::oauth_callback`이
        이 리스트에 없는 redirect_uri를 400으로 거절한다.
        """
        return [u.strip() for u in self.oauth_redirect_uri_allowlist.split(",") if u.strip()]

    @property
    def trusted_proxy_ips(self) -> frozenset[str]:
        """`trusted_proxy_ip_allowlist`(콤마 구분 원시값)를 파싱한 집합(공백 제거·빈 항목 제외).

        빈 집합이면 deny-by-default(신뢰 프록시 없음) — `_client_ip`(api/_rate_limit.py)가
        `X-Forwarded-For`를 완전히 무시하고 `request.client.host`만 쓴다. 순서 무관이라
        리스트가 아닌 `frozenset`(정확한 문자열 일치만 지원 — CIDR·IPv6 정규화는 후속).
        """
        return frozenset(u.strip() for u in self.trusted_proxy_ip_allowlist.split(",") if u.strip())

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """`cors_allowed_origins`(콤마 구분 원시값)를 파싱한 리스트(공백 제거·빈 항목 제외).

        빈 리스트면 deny-by-default — CORSMiddleware가 어떤 브라우저 cross-origin 요청도
        허용하지 않는다(네이티브 앱은 미영향).
        """
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def trusted_hosts_list(self) -> list[str]:
        """`trusted_hosts_allowlist`(콤마 구분 원시값)를 파싱한 리스트.

        비면 `["*"]`(전부 허용) — Host 헤더 검증 미구성 상태의 현재 동작을 무회귀로 보존한다.
        """
        parsed = [h.strip() for h in self.trusted_hosts_allowlist.split(",") if h.strip()]
        return parsed if parsed else ["*"]

    @property
    def production_like(self) -> bool:
        """프로덕션 추정 — `is_production_like`의 Settings 표면(판정 로직은 그 함수가 단일 좌석)."""
        return is_production_like(self)

    @property
    def effective_celery_broker_url(self) -> str:
        """실제 Celery broker URL — celery_broker_url이 비어 있으면 redis_url로 폴백.

        단일 Redis로 캐시(S2)와 큐(S4)를 함께 운영하는 것이 기본이다(03a §D.3). 전용
        broker가 필요하면 WHYMATH_CELERY_BROKER_URL로 분리 인프라를 가리킨다.
        """
        return self.celery_broker_url or self.redis_url

    @property
    def effective_celery_result_backend(self) -> str:
        """실제 Celery result backend URL — 비어 있으면 redis_url로 폴백.

        job_id로 QUALITY 결과를 조회하려면(폴링, 03a §D.3) result backend가 필요하다.
        기본은 broker와 같은 redis_url을 재사용한다.
        """
        return self.celery_result_backend or self.redis_url


def is_production_like(settings: Any) -> bool:
    """프로덕션 추정 — **실 OAuth provider(kakao/naver) 구성 여부** 단일 판정 좌석.

    프로덕션 전용 안전장치(대화 암호화 키 fail-closed·스키마 버전 가드)가 "지금이 프로덕션인가"를
    각자 판단하면 서로 표류한다. 판정은 여기 하나뿐이고 소비처는 전부 이 함수를 부른다.

    **새 env 축을 만들지 않은 이유**: 프로덕션엔 항상 실 provider가 있고 개발·CI엔 없다. 전용
    `environment` 축을 새로 두면 그 축 자체가 *설정하는 걸 잊는* 표면을 하나 더 만든다 —
    잊으면 안전장치가 조용히 꺼진다(SEC-01 결정·`api/demo_auth.py::register_demo_provider` 선례).

    `Any`를 받는 이유: 실 `Settings` 구성 없이 분기를 시험하는 테스트 대역을 허용한다. 다만
    속성 부재를 조용히 False로 흘리지 않도록 **두 속성이 모두 없으면 예외**를 낸다 — 조용한
    False는 "프로덕션이 아니다"라는 *잘못된 판정*이 되어 안전장치를 통째로 무력화한다.
    """
    has_kakao = hasattr(settings, "kakao_configured")
    has_naver = hasattr(settings, "naver_configured")
    if not has_kakao and not has_naver:
        raise TypeError(
            "프로덕션 추정 판별에 필요한 속성(kakao_configured·naver_configured)이 "
            f"모두 없습니다(받음: {type(settings).__name__}) — 조용히 '개발'로 판정하지 않습니다."
        )
    return bool(getattr(settings, "kakao_configured", False)) or bool(
        getattr(settings, "naver_configured", False)
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """프로세스 단위로 캐시된 Settings 접근자.

    `lru_cache`로 단일 인스턴스를 재사용한다(환경변수는 프로세스 수명 동안 고정 가정).
    테스트에서 환경을 바꿔 재로딩하려면 `get_settings.cache_clear()`를 호출한다.
    """
    return Settings()
