# WhyMath 24/7 운영 설계 (Phaiakes9 상시 가동)

> 범위: WhyMath **독립 수학 코어(L1~L4) + L5 서버**를 Phaiakes9에서 *상시 가동*하기 위한 서비스
> 토폴로지·감독(supervision)·헬스/레디니스·모니터링·백업·배포·클라우드 비용 보정 설계.
> 기존 [`README.md`](./README.md)는 **Ollama 단독(M1.1)** 운영만 다룬다 — 이 문서는 그 위에 *풀 스택*을 올린다.
>
> ⚠️ 라이브 적용(서비스 등록·실측)은 Phaiakes9 콘솔에서 실행한다. 이 문서는 *설계·런북*이며, 실 수치(비용·지연)는 §8에서 측정해 코드 상수를 보정한다.

---

## 0. 결정 우선순위 (CLAUDE.md §의사결정)

운영 충돌 시: **① 학생 안전·웰빙 → ② 법적·미성년자 → ③ 교수학 정확성 → … → ⑥ 비용 → ⑦ 속도.**
가용성(서비스 재시작·폴백)이 *정확성*을 위협하면(예: 검증 없는 응답 노출) **가용성을 양보한다** — L3/L4 검증 게이트를 우회하는 폴백은 금지.

---

## 1. 서비스 토폴로지

Phaiakes9(Ryzen AI Max+ 395·128GB) 단일 노드에 전 스택을 systemd/컨테이너로 상시 가동한다. **수학 로직은 L1~L4 독립 코어**(클라이언트는 API 소비·CLAUDE.md 슬라이스89).

| 서비스 | 역할 | 포트(기본) | 상태점검 | 데이터 |
|---|---|---|---|---|
| `ollama` | 로컬 LLM(Qwen2-Math·DeepSeek-Math·**Qwen3-VL** OCR) | 11434 | `/api/tags` + warm generate | 모델 캐시 |
| `whymath-api` (uvicorn) | L5 FastAPI — L1~L4 오케스트레이션·`/v1/*` | 8000 | **`GET /status`**(아래 §3) | 무상태(컨테이너) |
| `whymath-worker` (celery) | **QUALITY(27b) 비동기 큐 전용**(03a §D.3·동시성 1·GPU 단일 점유). **정본 = compose `quality-worker` 컨테이너**(§2 정본 지정) | — | `celery inspect ping -d <자기 노드>` | 무상태 |
| `postgres` (+TimescaleDB·pgvector) | RDB·시계열·임베딩 벡터(단일 store 동거·슬98) | 5432 | `pg_isready` | **영속(백업 필수)** |
| `redis` | 세션·핫데이터·**L3 응답 캐시**·Celery broker/backend | 6379 | `PING` | 반영속(AOF 권장) |
| `minio` (S3 호환) | 영상·이미지·**학생 손글씨 원본**(미성년 PII·암호화) | 9000c | `/minio/health/live` | **영속·암호화** |

> **정정(2026-10-07 · OPS-37)**: 종전 이 표는 `neo4j`(2026-08-03 미도입 확정)·`clickhouse`(2026-08-11 실측 미도입)를 가동 서비스로 적었다. 개념 그래프와 행동 로그의 정본은 둘 다 PostgreSQL 16(+TimescaleDB·pgvector) 단일 평면이다 — 존재하지 않는 서비스의 헬스체크·부팅 순서·백업을 지시하던 상태를 해소했다. 도입이 판정되면 그때 이 표에 다시 올린다.

의존 순서(부팅): `postgres·redis·minio·ollama` → `whymath-api`·`whymath-worker`.
이 순서를 systemd `After=`/`Wants=`로 강제한다(§2). 컨테이너 스택이면 docker-compose `depends_on`+healthcheck.

---

## 2. 감독(Supervision) — systemd

### 2-0. 정본 지정 — 컨테이너(compose)가 정본, systemd는 네이티브 토폴로지 대안 (OPS-27, 2026-10-08)

이 문서는 두 가지 가동 방식을 함께 기술해 왔고, 그 결과 "워커는 누가 띄우는가"에 답이 둘이었다(이중 진실). 하나로 정한다.

| 토폴로지 | 구성 | 지위 | 근거 |
|---|---|---|---|
| **compose 스택** | `docker-compose.prod.yml`의 `app`·`db`·`redis`·`retention-purge`·**`quality-worker`** | **정본** | 배포 런북(`docs/architecture/deployment_cd_runbook.md`)·CI(`docker-build`)·계약 테스트(`tests/infra`)가 이쪽만 집행한다. Ollama만 호스트에서 돈다(컨테이너 밖). |
| 네이티브 | `whymath-api.service`·`whymath-worker.service`·호스트 `redis-server` | 비정본(대안) | CI는 이 유닛이 *기동하는지*를 검증하지 않는다(명령 형식 회귀만 `tests/infra`가 본다). 레포에 실가동 기록이 없고 §10이 라이브 적용을 잔여로 남겨 두었다. compose 없이 호스트에 직접 설치하는 경우에만 쓴다. |

- **섞지 않는다.** compose의 Redis는 호스트 포트를 공개하지 않는다(`test_db_and_redis_ports_not_published`) → 호스트 systemd 워커는 compose 앱이 enqueue한 큐를 **구조적으로 소비할 수 없다**. 반대로 같은 브로커에 워커를 둘(컨테이너 + systemd) 띄우면 동시성이 2가 되어 GPU 단일 점유(03a §D.3)를 어긴다.
- compose 스택의 워커 운영(확인·재시작·로그)은 런북 §5c가 정본이다.

상시 가동·자동 재시작은 compose 토폴로지에서는 `restart: unless-stopped`가, 네이티브에서는 systemd가 맡는다. 기존 `systemd/ollama.service` 패턴을 확장한 **네이티브용 유닛 파일**: [`systemd/whymath-api.service`](./systemd/whymath-api.service)·[`systemd/whymath-worker.service`](./systemd/whymath-worker.service)·[`systemd/whymath.env.example`](./systemd/whymath.env.example), 설치 헬퍼 [`systemd/install_whymath_units.sh`](./systemd/install_whymath_units.sh)(아래 요지는 발췌).

**공통 정책**: `Restart=on-failure`·`RestartSec=5`·`StartLimitIntervalSec`로 크래시 루프 차단·`After=`로 의존 정렬. 시크릿은 `EnvironmentFile=/etc/whymath/whymath.env`(0600·env만·하드코딩 금지·CLAUDE.md 보안).

`whymath-api.service` (요지):
```ini
[Unit]
Description=WhyMath L5 API (uvicorn)
After=network-online.target postgresql.service redis-server.service ollama.service
Wants=postgresql.service redis-server.service ollama.service

[Service]
User=whymath
WorkingDirectory=/srv/whymath/src/backend
EnvironmentFile=/etc/whymath/whymath.env
ExecStart=/srv/whymath/src/backend/.venv/bin/uvicorn whymath_backend.app:create_app \
  --factory --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`whymath-worker.service`(네이티브 대안): 동일 패턴, `ExecStart=… celery -A whymath_backend.l3.queue.tasks:quality_celery_app worker -c 1`(QUALITY 27b는 GPU 단일 점유 → **concurrency 1 고정**·03a §D.3). `-A`에는 팩토리 함수가 아니라 **모듈 수준 인스턴스**를 준다 — 팩토리를 주면 celery CLI가 기동 즉시 죽는다(2026-10-08 실측, 이전 판의 이 줄이 그 형식이었다). 큐 **브로커 자체**가 미도달이면 `/v1/generate` QUALITY는 503(파이프라인 `QualityQueueUnavailableError`·동기 호출 절대 금지). 단 브로커는 살아 있는데 **소비자(워커)가 없으면 503이 아니라 202 접수 후 영구 `pending`**이다 — 이것이 OPS-27 이전 compose 스택의 상태였다.

> **다중 워커 주의**: api `--workers N`이면 인메모리 상태(세션·OCR 부품·L3 provider)가 워커별로 복제된다. 세션은 **Redis 영속**(`WHYMATH_REDIS_URL`)으로 공유하고, OCR/L3 부품은 워커별 startup 1회 로드(읽기전용이라 안전). DB 엔진은 lazy·워커별.

---

## 3. 헬스 / 레디니스

- **`GET /status`**(이미 구현) — Ollama 도달성·라우팅 모델 매트릭스 설치 여부·(선택)클라우드 구성. 죽은 의존이 있어도 **500을 던지지 않고 보고**(`reachable=false`·503/ready=false). 로드밸런서·systemd watchdog·외부 모니터의 레디니스 소스.
- 서비스별 저수준 점검: `pg_isready`·`redis-cli PING`·`cypher-shell "RETURN 1"`·`/minio/health/live`·`ollama` warm generate(`healthcheck.sh`).
- **콜드로드 방지**: Ollama `OLLAMA_KEEP_ALIVE`(예: `-1` 또는 충분히 길게)로 핫모델 상주 → 첫 요청 SLA(p50<2s·FAST) 보호. 부팅 후 `healthcheck.sh` generate 2~3회로 워밍업.
- **OCR 부품**: `WHYMATH_OCR_ENABLED=true`면 startup 1회 로드(app.py lifespan)·실패해도 부팅 fail-fast 안 함(/v1/ocr만 503). 라이브 검증은 [`OCR_LIVE_VERIFICATION.md`](./OCR_LIVE_VERIFICATION.md).

---

## 4. 모니터링·관측성

- **LLM 추적**: 모든 LLM/VLM 호출 → **Langfuse**(라우팅 결정·캐시 적중·shadow 검증 신호·비용/지연 추정 vs 실측). L3 `TraceSink`(LangfuseSink)가 이미 결선.
- **분산 추적/메트릭**: OpenTelemetry(api·worker) → 수집기. 핵심 SLI: `/v1/coach`·`/v1/ocr` p50/p95·에러율·캐시 적중률·큐 대기시간·GPU 메모리.
- **로그**: compose 정본은 `docker logs whymath-<env>-quality-worker`, 네이티브는 `journalctl -u whymath-api -u whymath-worker -u ollama`. 학생 채팅·손글씨는 **평문 로그 금지**(미성년 PII·CLAUDE.md) — Langfuse 기록도 학생 ID는 *해시*만(03a §F.2).
- **알림 신호(권장 임계)**: `/status` ready=false 1분↑ · api 5xx율 >2% · 큐 대기 p95 > SLA · 디스크 <15% · GPU OOM(`ollama ps`).

---

## 5. 백업·복구 (영속 데이터)

| 데이터 | 백업 | 주기 | 복구 검증 |
|---|---|---|---|
| PostgreSQL(학생·숙달 시계열·문항·임베딩) | `pg_dump`/물리(pgBackRest)·TimescaleDB 청크 포함 | 일 1회 + WAL 연속 | 분기별 복원 리허설 |
| MinIO(손글씨·이미지) | 버킷 복제/스냅샷 | 일 1회 | 객체 무결성 |
| Redis(세션) | AOF(`appendonly yes`) | 연속 | 재시작 후 세션 잔존(OCR §9·TTL 24h) |

**미성년 PII**: 손글씨 원본·채팅은 **암호화 저장**(MinIO SSE·DB 컬럼 암호화), 백업도 암호화. 보존기간·삭제(GDPR/개인정보)는 `privacy/` 모듈·동의 절차 준수.

---

## 6. 배포·업데이트 (무중단 지향)

1. `git pull` → venv 동기화(`pip install -e ".[dev,...]"`·필요 extra).
2. **DB 마이그레이션**: `alembic upgrade head`(전방호환 우선 — 컬럼 추가형). 파괴적 변경은 2단계(추가→백필→제거).
3. **api 롤링 재시작**: `systemctl reload-or-restart whymath-api`(워커 2+면 순차). lifespan이 `dispose_engine`로 커넥션 정리.
4. worker 재시작은 in-flight 작업 드레인 후. compose 정본: `docker compose ... stop quality-worker`가 SIGTERM을 보내 Celery가 warm shutdown(진행 작업 완료 후 종료)하며 `stop_grace_period: 120s`가 그 시간을 보장한다(도커 기본 10초면 진행 중 생성이 끊겨 그 작업이 영구 pending). 네이티브: `celery ... control shutdown` graceful.
5. 롤백: 직전 태그로 `git checkout` + (마이그레이션 가역성 확보된 경우) `alembic downgrade`.
6. **CI 게이트 통과분만 배포**(ruff·black·mypy-strict·pytest 70%+·policy-guard). `main` 머지 = 배포 후보.

---

## 7. 보안·네트워크

- Phaiakes9는 **폐쇄망** 가정. `ollama`·DB의 `0.0.0.0` 바인딩은 방화벽(ufw) 뒤에서만. 외부 노출 필요 시 **reverse proxy(TLS)+인증** 추가.
- 시크릿은 전부 `EnvironmentFile`(env)·`SecretStr`(코드)·repr/로그 노출 금지(CLAUDE.md). API 키 하드코딩 0.
- 인증·결제(카카오/네이버/토스)는 라이브 키 보유 후 결선(샌드박스 범위 밖).

---

## 8. 클라우드 티어 비용/지연 실측 보정 (03a §H#4)

현재 `l3/router.py`의 클라우드 추정 상수는 **명시적 placeholder**다(fabricate 아님):
- `CLOUD_MIN_COST_KRW` = {CLOUD_MID: 10.0, CLOUD_HIGH: 50.0} — `guard_cloud` 잔여예산 판정용 1회 최소비용.
- `CLOUD_LATENCY_MS` = {CLOUD_MID: 3000, CLOUD_HIGH: 8000} — 예상 지연(03a §A.1 "가변").

**보정 절차**(Phaiakes9·라이브 Anthropic 키):
1. 대표 호출지점(explain/diagnose/coach/verify)별 실 프롬프트로 CLOUD_MID(Sonnet)·CLOUD_HIGH(Opus) 호출 N회.
2. **Langfuse 실측 필드**(토큰 in/out·지연)에서 p50/p95 지연·호출당 원가(토큰×단가·환율) 산출.
3. 1회 최소비용 = 최소 프롬프트 관측 원가의 보수적 하한 → `CLOUD_MIN_COST_KRW` 갱신.
4. 예상 지연 = p50(또는 SLA 보수적으로 p95) → `CLOUD_LATENCY_MS` 갱신.
5. 상수 변경 + 근거(측정 N·기간·환율)를 **MEMORY.md 결정 로그**에 기록(코드 주석의 "placeholder" 표식 제거).

> 측정 자체는 라이브 키·트래픽이 필요해 샌드박스 불가 — 이 절차를 Phaiakes9에서 실행해 상수만 교체한다(라우팅 *로직*은 불변·상수만 데이터 보정).

---

## 9. 용량·확장 메모

- 단일 노드(Phaiakes9) 기준 설계. GPU는 **단일 점유**라 QUALITY(27b) 동시성 1·OCR(Qwen3-VL)·FAST/MID가 GPU를 공유 → 큐로 직렬화(03a §D.3). 동시 부하↑ 시 FAST 우선·QUALITY 비동기 분리가 이미 라우터에 반영.
- 수평 확장은 *프로덕션(GCP/AWS)* 단계(CLAUDE.md 인프라): api 무상태라 N복제 가능(세션 Redis·DB 공유), GPU 워커만 노드 추가. Phaiakes9는 개발·시범 상시가동 노드.

---

## 10. 후속 (이 문서 범위 밖·라이브 필요)

- ✅ **systemd unit 파일 작성 완료** — `systemd/whymath-api.service`·`whymath-worker.service`·
  `whymath.env.example`·`install_whymath_units.sh`(§2). 라이브 잔여: Phaiakes9에서 복사·enable +
  `/etc/whymath/whymath.env` 값 채우기(`sudo bash systemd/install_whymath_units.sh --now`).
- §8 클라우드 상수 실측 보정(라이브 키).
- ✅ 컨테이너화(docker-compose) 결정·이미지 빌드 — OPS-03이 `docker-compose.prod.yml`·`Dockerfile`로 완료, OPS-27이 `quality-worker`를 편입해 compose가 정본이 됐다(§2-0). 라이브 잔여: Docker가 도는 호스트에서 첫 `up -d`와 런북 §5c 자가검증(이 레포의 어떤 세션도 아직 이 스택을 실호스트에 올린 기록이 없다).
- 백업 자동화 스크립트·복원 리허설 cron.
- 인증·결제 라이브 결선.
