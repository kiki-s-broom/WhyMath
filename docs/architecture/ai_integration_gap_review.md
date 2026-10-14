# AI 기능 통합점검 — 기능×배선×관측 교차 갭 리뷰 (2026-08-10)

> **범위**: 외부 EOS 틀 대조가 **아니다**. AI 축 리뷰 4편(`ai_content_generation_gap_review{,_2}.md`·`ai_tutor_module_gap_review.md`·`ai_recommendation_module_gap_review.md`·`nlp_module_gap_review.md` — 등재 태스크 전건 done)이 기능 축을 각자 전수 대조했으므로, 이번 점검은 그 표면들을 **교차**로 재점검한다: "기능이 있다(선언)" × "호출자가 있다(배선)" × "비용·트레이스가 보인다(관측)"의 3축 곱에서 한 축이 0인 지점 전수. 신규 기능 설계 0.
> **형식**: gap_review 시리즈 고정 구조(§0~§5·§정정·부록) 답습 — 단 §1 판정표의 행은 EOS 기능 번호가 아니라 *AI 표면* × {선언·배선·관측}. 파일명은 같은 날 신설된 `dsl_integration_gap_review.md`(미머지 `claude/whymath-dsl-integration-check-bmjic8`)와 `<주제>_integration_gap_review.md` 시리즈를 이룬다(축 상이 — DSL vs AI 기능·중복 아님).
> **성격**: 재점검 — 4편 리뷰와 `ai_llm_inventory_2026-07.xlsx`(ARCH-15·2026-07-24)를 1차 스냅샷으로 승계하고, 그 이후 3주의 델타(특히 2026-07-20 WH-1 primary GA flip)가 만든 stale·미추적 지점만 다룬다.
> **결론 4줄**:
> 1. **최대 갭 = 학생 대면 LLM 트래픽 100%가 비용 게이트② 표본 밖** — WH-1 primary(기본 ON)가 `l3.pipeline`을 우회해 provider를 직접 호출, Langfuse `l3_routing` 0건·Redis 캐시 0. *선언된 유보였으나 GA flip으로 발화 조건이 이미 충족됐다* → D1(`OPS-26`).
> 2. 두 번째 갭 = **QUALITY 비동기 경로가 컨테이너 배포에서 producer-only** — 202+job_id는 반환되나 워커 서비스가 어떤 compose에도 없어 영구 pending → D2(`OPS-27`).
> 3. 세 번째 갭 = LLM 표면 봉인 잔여 — `GET /v1/jobs` 무인증 축은 점검 중 타 세션 `SEC-15`가 선점(승계), 남은 `POST /v1/generate` 레이트리밋 0만 등재 → D3(`SEC-19`).
> 4. 총계: **등재 5건**(OPS-26·OPS-27·SEC-19·PED-17·OPS-28) · **유보 8건**(§5) · **중복 등재 금지 대장 15항**(§3) · **정본 정정 4파일**(§정정 — 이번 커밋에서 직접 수정).

관련 정본: `docs/architecture/ai_llm_inventory_2026-07.xlsx`(ARCH-15) · `03a_l3_router_design.md` · `04a_wh1_tutoring_harness.md` · `04b_misconception_judge_graduation.md` · AI 리뷰 4편(상기) · `data_platform_module_gap_review.md`(OPS-22 감사기 설계 결정) · `src/backend/whymath_backend/{l3,l4,l5,harness,ops,whs}` 실측 · `MEMORY.md` 결정 로그 2026-07-09·07-14·07-16·07-20·07-24.

---

## §0. 전제 정리 — 재점검 사유 3가지

**사유 ① — 2026-07-20 WH-1 primary GA flip이 "LLM 호출 0" 시대의 서술을 대량 stale로 만들었다.** `wh1_primary_enabled=True`(`config.py:168`)가 기본이 된 뒤 학생 대면 AI 발화의 단일 경로는 WH-1 하네스(`harness/wh1_primary.py`)다. 그런데 `api/coach.py` 모듈·핸들러 docstring 3곳이 여전히 "LLM 호출은 여전히 0"이라 기술했고(§정정), 그 flip이 발화시킨 유보 항목(트레이스 결선)은 아무도 발화를 확인하지 않았다(D1).

**사유 ② — OPS-22 선언≠배선 감사기가 가동됐으나 감사기 자체에 사각이 있다.** `ops/declared_unwired_audit.py`(#754)는 HTTP·이벤트·시계열·CLI 4축을 정적 감사하지만, CLI 축이 `("harness", "ops")` 비재귀 glob(`declared_unwired_audit.py:560,568`)이라 l4/l3/l2/whs/l1의 AI CLI ~30종이 감사 밖이고, HTTP "reached" 판정이 dart|테스트 합집합(`:998`)이라 클라이언트 축 미도달이 가려진다(D5).

**사유 ③ — 횡단 정본 xlsx가 3주 미갱신이다.** `ai_llm_inventory_2026-07.xlsx`는 2026-07-24 스냅샷 이후 갱신이 없다. 이번 실측에서 모델 핀은 전건 문자 일치(부록 A-3 — ARCH-15 acceptance 유지)했으나 상태 칸 3곳이 stale이다. xlsx는 바이너리라 diff 불가이므로 갱신하지 않고 **본 문서 부록 A-3이 2026-08-10 델타의 텍스트 정본**이다(§4-①).

### 총론 전제표 (판정의 배경 사실 — 전부 실측)

| # | 전제 | 근거 |
|---|---|---|
| P1 | **검증 권위는 100% SymPy 결정론.** Tier1 답 검산(`l3/verify_answer.py`·고정 시드 샘플링) · Tier2 단계 동치(`l3/verify_step.py`) · 전수 열거(`l3/finite_probability.py`). LLM이 개입하는 검증은 `l3/cross_verify.py`(K=3 다관점) 1건뿐이고 스스로 "게이트가 아니라 검출기"라 선언 — 판정은 Wilson 게이트(`harness/residue_cross_verify_eval.py`) 소유 | 각 모듈 docstring |
| P2 | **학생 대면 LLM 발화의 단일 경로 = WH-1 primary.** `/v1/coach`(stateless)는 LLM 0 유지, `/v1/coach/sessions`(+turns)만 `_wh1_primary_decision_or`(`api/coach.py:1534`) 경유. 폴백은 결정론 `decision.prompt` | `api/coach.py:1816,2138` |
| P3 | **structured output(json_schema)은 LOCAL 전용.** Ollama `format=`만 지원, `AnthropicProvider`는 `json_schema`·`images`에 명확한 RuntimeError(조용한 무시 금지) — 클라우드 경로에는 문법 제약 디코딩 보장이 없다 | `l3/providers/anthropic.py` |
| P4 | **오개념 AI 계층 5플래그 전부 기본 OFF.** `misconception_semantic_mode="off"`(`config.py:945`) · `judge_enabled=False`(`:961`) · `judge_shadow=False`(`:976`) · `crosslink_mode="off"`(`:994`) · `wrong_form_mode="off"`(`:1011`). prod compose에 이 키들이 없어 전부 기본값 → 프로덕션 코치의 오개념 진단은 substring `diagnose()`만. 또한 `Dockerfile:43`이 `[embedding]` extra를 미설치하므로 semantic 모드를 켜도 graceful except로 substring 폴백(경고 로그만) | `config.py`·`Dockerfile:43`·`api/coach.py` |
| P5 | **임베딩 3테이블 중 런타임 정본은 1개.** `atom_embedding`(원자 1,837)만 `GET /v1/concepts/search`로 도달, `concept_embedding`은 `LEGACY_SNAPSHOT` 격하(S0-4b·런타임 호출자 0), `misconception_embedding`은 P4로 노출 차단 | `api/concepts.py`·`l1/atom_graph/retrieval.py` |
| P6 | **CI에서 라이브 AI 경로 실행 0회는 선언된 공백.** 통합 잡이 `pytest -m integration --ignore=../../tests/backend/l3`(`ci.yml:396`)로 l3 통합테스트(Ollama·Anthropic·Langfuse·Celery·Redis) 전체 제외 + `[embedding]` 의도적 미설치 — `_LIVE_DEPENDENT` 사유로 자기 선언돼 있어 숨은 갭이 아니다 | `ci.yml`·`tests/backend/conftest.py:55-61` |
| P7 | **모델 핀(코드 실측)**: LOCAL `qwen2-math:1.5b/7b`·`qwen2.5:3b/7b`·`qwen3-vl:8b`·`qwen3.5:27b`(`l3/router.py:53-68`) / CLOUD `claude-sonnet-4-6`·`claude-opus-4-7`(`config.py:351,358`) / 임베딩 `BAAI/bge-m3`(1024)·`text-embedding-3-large`(3072)(`config.py:900,907`) — xlsx 시트2와 전건 문자 일치(부록 A-3) | 실측 2026-08-10 |

---

## §1. 전수 판정표 — AI 표면 × {선언·배선·관측}

표기: ✅ 충족 · ⚠️ 부분 · 🚫 없음 · ⏸ 기존 태스크/정본 승계. "관측"은 그 표면의 호출이 비용·트레이스 회계(Langfuse `l3_routing` + `ops/cost_report` 게이트② 표본 또는 동등한 인프로세스 이중 회계)에 잡히는가.

| # | AI 표면 | 선언 | 배선(호출자) | 관측 | 판정·처분 |
|---|---|---|---|---|---|
| 1 | 텍스트 생성 `POST /v1/generate` → `l3/pipeline.generate` | ✅ | ✅ 서빙(인증 `CurrentUser`·SEC-07) | ✅ 라우터+캐시+Langfuse 완비 | 레이트리밋 0 — 유일한 무제한 LLM 비용 표면 → **D3(`SEC-19`)** |
| 2 | **코치 세션 LLM 발화 (WH-1 primary·기본 ON)** | ✅ GA(07-20) | ✅ `api/coach.py:1816,2138` → `run_wh1_primary_turn` | 🚫 **`l3_routing` 0건·Redis 캐시 0** — `LLMTutorPolicy`가 `Router().route()` 후 provider 직접 호출(`wh1_llm_policy.py:193`), `wh1_primary.py` docstring이 "범위 밖(후속): Langfuse trace 결선" 자기 선언. verdict 원장(`emit_wh1_observation`)은 있으나 비용·지연 회계 축이 없다 | **D1(`OPS-26`)** — 유보 발화 조건 기충족 |
| 3 | 코치 프로즈 rephrase (`harness/wh1_prose.py`) | ✅ 구현 | ⚠️ 기본 OFF(`config.py:199`) | 🚫 동일 우회 | D1에 포함(같은 결선) |
| 4 | **QUALITY 비동기 (큐→워커→`GET /v1/jobs`)** | ✅ `app.py:678` 상시 결선·202+job_id | ⚠️ **producer-only** — prod compose 서비스는 app·db·redis·retention-purge뿐, 워커 0(systemd 문서 `infra/phaiakes9/OPERATIONS_24_7.md`만 존재) | ✅ 큐 태스크는 Langfuse 배선(단 워커가 없으면 실행 자체가 0) | **D2(`OPS-27`)**. `/v1/jobs` 무인증·소유권은 ⏸ **SEC-15**(타 세션 in_progress) 승계 |
| 5 | 결정론 검증 3종 `POST /v1/verify-{step,solution,answer}` | ✅ | ✅ 서빙(LLM 0·SymPy) | n/a(LLM 무관) | ✅ 정본 사실(P1). 클라 소비 0은 ⏸ S3-32 종속(§5-⑧) |
| 6 | 교차검증 `l3/cross_verify.py` (K=3 LLM 검출기) | ✅ | CLI-only(`harness/residue_*` — by-design) | ✅ 자체 `_record_trace` | ✅ 게이트 강등전은 ⏸ S4-16(in_progress) |
| 7 | 동등문제 LLM 생성·rephrase (`l3/equivalent/`) | ✅ | CLI-only(코퍼스 공장 — by-design) | ⚠️ `llm_generator.py` 자체 기록 ✅ / **`rephrase.py` Langfuse 0**(grep 실측 0건) | rephrase 결선은 D1 acceptance ①에 포함 |
| 8 | OCR 5단계 파이프라인 (`l5/ocr/` 9모듈) | ✅ 전 부품 실구현(§정정 — "스텁" 표기가 stale이었다) | ⚠️ 서빙 배선(`POST /v1/ocr`)·클라 완주(Flutter `ocr_controller`)이나 **배포 3중 잠금**: `ocr_enabled=False` 기본(`config.py:1057`) + prod compose·`.env.prod.example`에 `WHYMATH_OCR_ENABLED` 키 부재 + `Dockerfile:43` `[ocr]` extra 미설치 → 컨테이너에서 상시 503 | ✅ 도달 관측·사유 분리는 NLP-01 착지(`api/_ocr_state.py`) | ⏸ NLP-01(done — 활성화는 명시적 범위 밖) · 활성화는 §5-① 유보 |
| 9 | 오개념 AI 계층 (judge·semantic·crosslink·wrong_form·shadow) | ✅ 코어 구현 | ⚠️ coach 배선은 있으나 5플래그 전부 기본 OFF(P4) — 프로덕션은 substring만 | 🚫 실행 자체 0 | ⏸ `04b_misconception_judge_graduation.md` 졸업 조건 소유(§5-②) — 2026-06-15 실측(1.5b 전건 UNCERTAIN) 후 `general_mid` 좌석 재측정 미실시 |
| 10 | 임베딩 의미검색 `GET /v1/concepts/search` | ✅ | ✅ 서빙(bge-m3·atom 축) — GET 무인증은 SEC-07 동결 결정 | ✅ 도달 관측 KG-01 착지 | ✅ (P5) |
| 11 | 시각화 spec 생성 (`l3/visualization.py`) | ✅ | ✅ `/v1/scenes/weak-concept`(클라 소비 O) · `/v1/visualizations/*` 3라우트는 클라 소비 0 | ✅ pipeline 경유 | ⏸ `/v1/visualizations/*` 거취는 **PED-16 ④**(미머지 dsl 리뷰)가 "별건 등재 금지"로 소유 |
| 12 | 학습 공급 LLM 폴백 (`api/study.py` → `l4/content_supply.supply`) | ⚠️ **선언된 유보** — "생성 폴백은 이 좌석에서 켜지 않는다(후속 결정)"(`study.py:29-30`) | 🚫 `generate_request`·`provider`·`trace` 미전달 → 가드 단락(`content_supply.py:326-334`)·404 | ⚠️ **tally 무변별** — 가드 단락(학생 404)과 실제 생성(학생 수신·`:345-356`)이 동일 `(content_source="generate", strategy, fallback_reason)` 튜플로 합산 — 학생 수신 여부가 회계에서 소실 | **D4(`PED-17`)** — "후속 결정"의 추적 태스크 부재를 해소(소유 태스크화) |
| 13 | 클라우드 승급 (Sonnet 4.6 / Opus 4.7) | ✅ 프로바이더 완비 | 🚫 학생 도달 0 — `l3/escalation_defaults.py`가 전 학생 호출부에 `free`/`0원` 공급 → 라우터 규칙상 CLOUD 도달 불가 | ✅ 도달 관측은 OPS-18 착지 | ⏸ OPS-18(done) · 결제 배선은 §5-④ 유보 |
| 14 | WH-S 솔버 하네스 (`whs/` — verdict·PRM 빌더·self-evolution) | ✅ by-design 오프라인 | ⚠️ 패키지 외부 호출자 0 + **CLI 3종(corpus_replay·prm_builder_export·self_evolution_export)의 실행 배선도 0**(CI·compose·스크립트 어디에도) | n/a | §4-② 정직한 공백. PRM 추론기는 ⏸ 의도적 미등재 승계(§5-⑤) |
| 15 | CI 라이브 AI 경로 (provider·Langfuse·Celery·Redis·임베딩) | ✅ 테스트 존재 | ⏸ 실행 0회 — `_LIVE_DEPENDENT` 선언된 공백(P6) | — | 숨은 갭 아님 — 현행 유지 |
| 16 | 선언≠배선 감사기 (`ops/declared_unwired_audit.py`) | ✅ 가동(CI 잡) | ⚠️ **사각 3종**: CLI 축 비재귀·2패키지 한정 / HTTP reached=dart\|테스트 합집합(클라 축 미분리 — `/v1/generate`·`/v1/jobs`가 서버 테스트만으로 reached) / dart 리터럴 매칭(lib/ 소비 화면 0인 `verify_api.dart`를 reached 판정) | — | **D5(`OPS-28`)** — ✅ 2026-10-12 해소(CLI 축 전 패키지·import≠도달·서버/클라 분리 컬럼·한계 자기 선언) |

---

## §2. 의도적 미채택 — 채워야 할 공백이 아니라 지켜진 경계 (재판정 없음)

| # | 항목 | 근거 정본 |
|---|---|---|
| 1 | **클라우드 비전 경로 부재** — `requires_vision=True`는 무조건 LOCAL/VISION 단축(`l3/router.py:485-494`), 클라우드 승급 경로가 구조적으로 없다 | 미성년 프라이버시·로컬 우선(Phaiakes9) — 2026-05-28 결정 |
| 2 | **stateless `/v1/coach`의 LLM 0 유지** — WH-1 승격은 세션 경로에만 | 세션 상태 없는 단발 호출에 LLM 발화를 열지 않는 경계 |
| 3 | **클라우드 structured output 미지원의 명시적 에러** — `json_schema`를 조용히 무시하지 않고 RuntimeError | `l3/providers/anthropic.py`(침묵 실패 금지) |
| 4 | **Anthropic effort·thinking·prompt caching 기본 OFF** — 배선만 하고 라이브 측정 후 튜닝 | `config.py`·MEMORY 2026-07-14 "프롬프트 캐싱 적용 보류" |
| 5 | **임베딩 provider 최종 결정의 미결 유지** — bge-m3(로컬 기본) vs te-3-large vs Qwen3-Embedding | MEMORY 2026-07-09 "결정은 미결 유지"·SSM 2026-Q3 스캔 ③ |
| 6 | **whs/의 학생 세션 비개입** — 오프라인 전용 선언 | `whs/__init__.py` (단 CLI 실행 배선 0은 §4-②) |

---

## §3. 진짜 갭 설계 D1~D5

### D1 — WH-1 학생 대면 LLM 관측·캐시 결선 (최우선·`OPS-26`)

**사실**: `LLMTutorPolicy`(`harness/wh1_llm_policy.py:193`)와 `wh1_prose.py`는 `Router().route()`로 결정만 받고 `l3.pipeline`을 우회해 provider를 직접 호출한다. 따라서 ① Langfuse `l3_routing` 이벤트 0 — `ops/cost_report`가 계산하는 게이트②(로컬:클라우드 비율·p50/p90·suggested_est) 표본에서 **학생 대면 LLM 트래픽 100%가 구조적으로 빠진다**. ② Redis 응답 캐시 미적용 — 동일 턴 상황 재호출이 전액 재비용. `l3/equivalent/rephrase.py`도 동일 계열(Langfuse 0·grep 실측).

**왜 지금인가**: 이 공백은 침묵 드리프트가 아니라 `wh1_primary.py` docstring의 **선언된 유보**("범위 밖(후속): Langfuse trace 결선 — 정책 호출은 shadow와 동일하게 provider 직접 소비")다. 그 선언이 쓰일 때 primary는 canary였다. 2026-07-20 GA flip(`wh1_primary_enabled=True` 기본)으로 **유보의 발화 조건이 이미 충족**됐는데 발화를 확인한 주체가 없었다 — `ai_tutor_module_gap_review.md` §5-④(스트리밍·fast path)의 트리거("primary 발화 ON 승격")와 같은 방아쇠다. 부수: `wh1_llm_policy.py:18`의 "트레이스는 라우터가 붙이며"는 사실과 달랐다(라우터는 순수 결정 로직·트레이스는 pipeline 소유) — §정정에서 문구를 선정정했고 코드 정합은 본 태스크 acceptance ④가 소유한다.

**경계**: S1-a 프라이버시 설계(학생 원문·정답은 정책 사적 필드·프롬프트 미포함)는 그대로 두고 관측·캐시만 결선한다. 결선돼도 트레이스에 원문이 실릴 수 없다(프롬프트에 없으므로).

### D2 — QUALITY 워커 컨테이너 배포 (`OPS-27`)

`app.py:678`이 `CeleryJobQueue`를 상시 결선하고 QUALITY(`qwen3.5:27b`) 라우팅 시 202+job_id를 반환하지만, `docker-compose.prod.yml`의 서비스는 app·db·redis·retention-purge뿐이다 — **워커가 없어 컨테이너 배포에서 QUALITY 작업은 영구 pending**이고, 폴링 상대(`GET /v1/jobs/{job_id}`·`app.py:1031`)는 끝나지 않는 작업을 바라본다. 워커 정의는 `infra/phaiakes9/OPERATIONS_24_7.md`의 systemd 문서에만 있어 컨테이너/네이티브 이중 진실 상태다. `deployment_cd_runbook.md`에 celery 언급 0 — 미등재였다. "완비된 소비 경로 + 미도달 공급원" 계열(VIZ-01·NLP-01·REC-01·S4-22·OPS-24)의 **배포 축 변형**이다.

### D3 — `POST /v1/generate` 레이트리밋 (축소판·`SEC-19`)

착수 시점의 원안은 "jobs 무인증 + generate 레이트리밋" 2축이었다. 점검 중 타 세션(`claude/whymath-issues-review-k20m0w`)이 **`SEC-15-unauth-answer-jobs-exposure`를 등재·in_progress**로 선점했고, 그 결함B가 jobs 인증+소유권을 정확히 커버함을 원격 실측으로 확인했다(`app.py` 자신도 ":28 — `/v1/jobs`는 SEC-07 범위 밖"이라 자백하던 표면). **jobs 축은 SEC-15 승계**로 전환하고, 그 감사(`functional_security_audit_2026-08-08.md`·미머지)가 다루지 않은 잔여 축만 등재한다: `POST /v1/generate`(`app.py:962`)는 `CurrentUser` 봉인(SEC-07) 후에도 `RateLimited*` 의존성이 0건인 **유일한 무제한 LLM 비용 표면**이다(visualization·scene·coach는 리미터 보유). SEC-08의 `/v1/auth/*` 리미터 이식으로 봉인한다.

### D4 — 학습 공급 생성 폴백 후속 결정 소유 (`PED-17`)

`api/study.py:29-30`은 "생성 폴백(LLM)은 이 좌석에서 **켜지 않는다**(`generate_request` 미주입). — 학습 공급 첫 배선에서 LLM 비용·환각 표면을 열지 않는다(**후속 결정**)"이라고 정직하게 유보를 선언했다. 문제는 두 가지다. ① 그 "후속 결정"을 추적하는 태스크가 없었다 — SEC-15가 잡은 "docstring 자백·추적 태스크 부재" 패턴과 동형이라 같은 처방(소유 태스크화)을 적용한다. ② 판정과 무관하게 **회계 무변별**이 실재한다: 가드 단락(`content_supply.py:326-334` — 학생은 404)과 실제 생성(`:345-356` — 학생 수신)이 tally에 동일 `(content_source="generate", strategy, fallback_reason)` 튜플로 합산돼, `content_supply.py` 모듈 docstring이 스스로 경고한 "generate로 집계되나 학생은 아무것도 못 본" 왜곡을 기계로 판별할 수 없다. 현재 라이브 피해 0인 이유는 이 엔드포인트를 부르는 클라이언트가 아직 없기 때문(MOB-13·타 세션 대기)이며, MOB-13이 착지하는 순간 DSL 미보유 개념의 404가 실학생에게 닿는다.

### D5 — 선언≠배선 감사기 사각 3종 (`OPS-28`)

OPS-22 감사기는 이 계열 사고("최소 6회 반복" — 모듈 자기 집계)의 방어 장치인데 세 사각이 실측됐다. ① **CLI 축**: `_CLI_PACKAGES=("harness","ops")` + 비재귀 `.glob("*.py")`(`declared_unwired_audit.py:560,568`) — l4/misconception 11종(judge_shadow_harvest·crosslink 계열 6종 등)·`l3/pregenerate/__main__.py`·`l2/calibrate_items.py`·whs 3종·l1 populate 계열 등 **AI CLI ~30종이 감사 대상 밖**이고, 이 중 `judge_shadow_harvest.py`·`crosslink_triage.py`는 테스트 외 호출자 0을 이번에 실측했다. ② **HTTP reached 정의**: dart|테스트 합집합(`:998`)은 `data_platform_module_gap_review.md` §2가 기록한 **의도적 설계 결정**이므로 뒤집지 않는다 — 다만 서버 도달과 클라 도달을 분리 컬럼으로 확장해야 `POST /v1/generate`·`GET /v1/jobs`처럼 "서버 테스트만으로 reached"인 표면이 보인다. ③ **dart 리터럴 매칭 한계**: `verify_api.dart`에 경로 리터럴이 있으면 reached인데, `verifyApiProvider`를 watch/read하는 화면·컨트롤러가 lib/ 안에 0건 — **클라이언트 측 선언≠배선**은 구조적으로 못 잡는다(`CoachApi.coach()`·`getSession()` 동일 패턴). 한계 자기 선언까지가 이번 범위, AST 수준 해소는 동결.

### 등재 요약

| 태스크 | 설계 | stage | priority | 근거 |
|---|---|---|---|---|
| `OPS-26-wh1-llm-observability-cache-wiring` | D1 | S4 | 2 | 학생 LLM 트래픽 게이트② 표본 0 — 유보 발화 기충족 |
| `OPS-27-quality-worker-container-deploy` | D2 | S4 | 2 | producer-only 배포 축 — 202 영구 pending |
| `SEC-19-generate-rate-limit` | D3 | S4 | 3 | 유일한 무제한 LLM 비용 표면(jobs 축은 SEC-15 승계) |
| `PED-17-study-generate-fallback-decision` | D4 | S4 | 3 | 선언된 유보의 추적 태스크 부재 + tally 무변별 |
| `OPS-28-declared-unwired-audit-blindspots` | D5 | S4 | 3 | 방어 장치 자체의 사각 3종 |

태스크는 전건 `backlog.py add` CLI 경유로 등재했다(ID 손편집 0 · 번호 충돌은 CLI가 로컬+원격 양쪽 검사 — HARN-10). `--path` 선언으로 겹침 검사를 켰다. `validate` green 234건. **ID 사전 청소**: 번호는 트렁크뿐 아니라 미머지 브랜치 7종의 태스크 파일 천장(OPS-25·SEC-18·PED-16 — 원격 ls-tree 실측)을 넘겨 골랐다 — 2026-07-29 OPS-15 이중 배정(슬러그가 달라 validate가 못 잡는 유형) 재발 방지.

### 중복 등재 금지 대장

| # | 주제 | 기존 추적 (이번 처리) |
|---|---|---|
| 1 | `GET /v1/jobs` 무인증·소유권 | ⏸ `SEC-15`(타 세션 in_progress·미머지) — D3에서 승계·범위 밖 동결 |
| 2 | 클라우드 승급 학생 도달 0 (free/0원 3중 차단) | ⏸ `OPS-18`(done — 관측 좌석) · 결제 배선은 §5-④ |
| 3 | OCR 도달 관측·사유 분리 | ⏸ `NLP-01`(done — 활성화는 그 태스크의 명시적 범위 밖) |
| 4 | OCR 업로드 한도 | ⏸ `SEC-17`(미머지 브랜치 등재 확인) — 인접 축·본 점검 미개입 |
| 5 | `/docs`·`/openapi.json` 노출·CORS | ⏸ `SEC-18`(미머지) — generate 레이트리밋은 미커버 확인 후 D3 분리 |
| 6 | `/v1/visualizations/*` 3라우트 거취 | ⏸ `PED-16` ④(미머지 dsl 리뷰 — "별건 등재 금지" 명시) |
| 7 | 감사기 dead-write 테이블 축 | ⏸ `PED-16` notes 관찰 — D5 범위 밖(§4-③) |
| 8 | LLM 결함 주입 검출률 게이트 강등전 | ⏸ `S4-16`(**in_progress** — 유일한 진행 중 AI 태스크) |
| 9 | attempt_event producer-only 3종 / 백필 CLI CI 미배선 | ⏸ `S4-22`·`OPS-24`(todo — OPS-22 감사기가 이미 등재) |
| 10 | 학습 공급 클라이언트 호출 0 | ⏸ `MOB-13`(todo·타 세션 claim) — D4는 서버 좌석 축만·paths 겹침은 의도(대기 신호) |
| 11 | verify 표면의 학습 루프 재편 | ⏸ `S3-32`(todo) — 클라 verify 소비는 §5-⑧ 종속 유보 |
| 12 | 오개념 judge 졸업(7b 재측정·플래그 ON) | ⏸ `04b_misconception_judge_graduation.md` 졸업 조건 소유 — MISC-01~06과 무관 확인 |
| 13 | PRM 스코어러(추론기) | ⏸ `ai_content_generation_gap_review.md` §4-③ 의도적 미등재(dead task 방지) 승계 |
| 14 | 임베딩 provider 최종 결정 | ⏸ MEMORY 2026-07-09 "미결 유지가 결정" — 재결정 안 함 |
| 15 | 프롬프트 캐싱·effort·thinking | ⏸ MEMORY 2026-07-14 보류 결정 — 라이브 측정 후(§5-⑦) |

---

## §4. 정직한 공백 — 지금 하지 않는 것 (4종)

1. **xlsx 8월판 미갱신.** `ai_llm_inventory_2026-07.xlsx`는 바이너리라 diff·리뷰 불가 — 이번에 갱신하지 않고 부록 A-3(상태 stale 3곳 + 핀 전건 일치)이 2026-08-10 델타의 텍스트 정본이다. 8월판 재발행은 핀 불일치가 실재할 때만(현재 0건 — ARCH- 후속 불요 판정).
2. **whs/ CLI 실행 배선.** 오프라인 by-design은 존중하되, `corpus_replay`·`prm_builder_export_cli`·`self_evolution_export_cli`가 CI·compose·스크립트 어디서도 실행되지 않는 상태는 그대로 둔다 — 소비자(PRM 학습·SFT)가 §5-⑤ 트리거 대기이므로 실행 배선만 먼저 만들면 dead wiring이 된다.
3. **감사기 dead-write 테이블 축.** dsl 리뷰(PED-16 notes)가 관찰한 4축째 사각 — PED-16의 두 테이블 판정 결과를 보고 일반화 여부를 정하는 편이 정직하다(D5에 선편입하면 PED-16과 이중 소유).
4. **클라이언트 dead code 소거**(`CoachApi.coach()`·`getSession()`·`verify_api.dart` 미소비 코드) — S3-32가 검증 표면을 코치 경유로 재편하므로 그 착지 전 소거는 재작업이다(§5-⑧).

---

## §5. 유보 항목의 발화 조건

| # | 유보 항목 | 발화 트리거 | 소유 정본 |
|---|---|---|---|
| ① | OCR 프로덕션 활성화(3중 잠금 해제 — env 키 + `[ocr]` extra + 플래그) | 파일럿(S3-01)에서 손글씨/이미지 입력 수요 실측 + Qwen3-VL 라이브 인식 정확도 측정(목표 90%·PRD §12.3) | `NLP-01` 관측 좌석 + 본 문서 |
| ② | 오개념 judge 플래그 ON(coach 배선) | `general_mid`(qwen2.5:7b) 재측정에서 한국어 3값 판정 형식 준수 + FP 감소 실증(1.5b는 2026-06-15 전건 UNCERTAIN 실측) | `04b_misconception_judge_graduation.md` 졸업 조건 |
| ③ | `CLOUD_LATENCY_MS`(3000/8000 placeholder)·`USD_TO_KRW`(1540 고정) 실측 보정 | `OPS-26` 착지로 학생 트래픽 표본이 게이트②에 잡힌 뒤 — 표본 없는 보정은 07-14 "비대표 1건" 재판 | `03a_l3_router_design.md` §H 후속 4(비용 계측 포괄) |
| ④ | 클라우드 승급 실개통(구독·예산 실값) | 결제(토스페이먼츠) 배선 — `escalation_defaults.py` 단일 좌석 교체 | `OPS-18` 동결 승계 |
| ⑤ | PRM 스코어러 추론기 | `prm_dataset` 소비처(학습 파이프라인) 확정 시 — 그 전 등재는 dead task | `ai_content_generation_gap_review.md` §4-③ |
| ⑥ | 임베딩 provider 최종 결정 | SSM 2026-Q3 스캔 ③ + 파일럿 후보(Qwen3-Embedding) 비교 측정 | MEMORY 2026-07-09 |
| ⑦ | Anthropic prompt caching·effort·thinking ON | 라이브 비용·지연 실측에서 효과 입증(현재 "효과 잠정" 자인) | MEMORY 2026-07-14 |
| ⑧ | `verify_api.dart` 클라 소비(또는 소거) | `S3-32`(학습 루프 닫힘 — 검증을 코치 경유로 재편) 착지 후 소비/폐기 판정 | `S3-32` acceptance(클라 배선 미포함 실측 확인) |

---

## §6. 반복 실수 — 계열 회차 기록

이번 세션의 신규 실수 등재는 0건이다. 다만 두 기존 계열에 회차를 기록한다:

1. **"완비된 소비 경로 + 미도달 공급원" 계열** — D2(폴링 라우트는 있는데 워커가 배포에 없음)가 배포 축 신규 사례다. 기존 회차(VIZ-01·NLP-01·REC-01·MOB-13·S4-22·OPS-24)는 전부 "코드 경로 미호출" 축이었고, 이번 것은 **런타임 프로세스 자체가 배포에 없는** 변형 — OPS-22 정적 감사기가 구조적으로 못 보는 축이라(감사기는 코드만 읽는다) `OPS-27` acceptance ②가 compose 정적 파싱 테스트로 동결한다.
2. **역방향(실제보다 못하다고 기술) 계열** — `l5/ocr/__init__.py`·`factory.py`의 "스텁"·"NotImplementedError" 표기가 신규 사례다(실제는 전 부품 동작). 주목할 점은 **정정의 미전파 메커니즘**: `recognize.py:216`이 2026-07-31에 같은 stale을 정정하며 "그 stale이 갭 대조의 착수 가설을 한 번 틀리게 했다"고 기록까지 했는데, 그 정정이 요약 docstring 2곳(`__init__.py`·`factory.py`)에 전파되지 않았다. 방어: 이번 §정정에서 요약 쪽에 "각 부품의 현재 상태는 해당 모듈 docstring이 정본 — 여기 요약이 뒤처지면 그쪽이 이긴다"를 각인해 요약을 정본 경쟁에서 명시적으로 강등했다.

---

## §정정 — stale 정본 4파일 (이번 커밋에서 직접 수정)

| 파일 | stale 서술 | 정정 |
|---|---|---|
| `api/coach.py` (모듈 docstring + `create_session` + `append_turns`) | "LLM 호출은 여전히 0 / LLM 호출 0 — AI 턴은 `decision.prompt`" ×3곳 | WH-1 primary(기본 ON·2026-07-20 GA)가 LLM 발화 승격, 실패·OFF 시 `decision.prompt` 폴백 — 현행 배선(`:1816,2138`)과 일치시킴 |
| `harness/wh1_llm_policy.py` | "트레이스는 라우터가 붙이며 프롬프트 문자열만 관측" — 라우터는 순수 결정 로직이라 트레이스를 붙이지 않는다 | "L3 트레이스는 현재 미결선 — Langfuse·캐시 결선은 `OPS-26` 소유"로 사실화(프라이버시 논거는 유지 — 프롬프트에 원문이 없으므로 결선 후에도 원문 미노출). 코드 정합은 OPS-26 acceptance ④ 소유 |
| `l5/ocr/__init__.py` | MfdDetector·MfdRouter "스텁"·TexTeller "B 스텁"·QwenVL "C 스텁" | 실상(B·동작 / C·동작 / 비동기 경로 실배선)으로 정정 + "모듈 docstring이 정본" 각인 |
| `l5/ocr/factory.py` | "mfd(YOLO···B 스텁)"·"texteller(B 스텁)"·"qwen_vl(C 스텁)"·"실제 호출 시 NotImplementedError" (저장소에 해당 raise 실재 0건) | rapid-layout PP 계열(YOLO 아님·AGPL 거부)·Phase 현행화·실제 에러 계약(RuntimeError — 의존 미설치·동기 진입)으로 정정 |

xlsx 시트2·시트3의 대응 stale(TexTeller "B 스텁/계획(미배선)"·QwenVL "보류(NotImplementedError)"·WH-1 판단 루프 "현재 Claude Haiku")은 §4-① 방침대로 파일을 고치지 않고 부록 A-3이 델타 정본을 보유한다.

---

## 부록 A — 실측 근거 (2026-08-10 실측 · 브랜치 `claude/whymath-ai-integration-check-5qqcp4` · 베이스 HEAD `5f60f37e`)

### A-1. 핵심 실측 지점 (파일:행)

- WH-1 우회: `harness/wh1_llm_policy.py:193`(`Router().route()` 후 provider 직접)·`:149`(`subscription="free"` 기본 → LOCAL 라우팅)·`harness/wh1_primary.py` docstring "범위 밖(후속): Langfuse trace 결선" / Langfuse·trace 참조 grep: `wh1_llm_policy.py`·`wh1_prose.py`·`l3/equivalent/rephrase.py` 각 0건
- QUALITY: `app.py:678`(CeleryJobQueue 상시 결선)·`app.py:962`(`POST /v1/generate`·`CurrentUser`·RateLimited 0)·`app.py:1031`(`GET /v1/jobs/{job_id}`)·`docker-compose.prod.yml` 서비스 목록(app·db·redis·retention-purge — worker 0)
- 학습 공급: `api/study.py:29-30`(유보 선언)·`l4/content_supply.py:326-334`(가드 단락 tally)·`:345-356`(실생성 tally — 동일 튜플)
- 감사기: `ops/declared_unwired_audit.py:560`(`_CLI_PACKAGES`)·`:568`(비재귀 glob)·`:998`(dart|테스트 합집합)
- 플래그·배포: `config.py:168,199,945,961,976,994,1011,1057`·`Dockerfile:43`·`ci.yml:396`·`tests/backend/conftest.py:55-61`
- 원격 대조: `origin/claude/whymath-issues-review-k20m0w`의 `SEC-15`(결함B=jobs 인증+소유권·in_progress)·`SEC-17`·`SEC-18`·`OPS-25` / `origin/claude/whymath-dsl-integration-check-bmjic8`의 `PED-16`

### A-2. 재현 명령

```bash
# WH-1 경로의 관측 부재 (0이어야 재현)
grep -c "langfuse\|_record_trace\|TraceSink" \
  src/backend/whymath_backend/harness/wh1_llm_policy.py \
  src/backend/whymath_backend/harness/wh1_prose.py \
  src/backend/whymath_backend/l3/equivalent/rephrase.py
# prod compose 워커 부재
grep -n "^  [a-z-]*:" docker-compose.prod.yml
# generate 레이트리밋 부재 (RateLimited 미출현 확인)
sed -n '962,1030p' src/backend/whymath_backend/app.py | grep -c RateLimited
# 감사기 CLI 축 범위
grep -n "_CLI_PACKAGES\|glob(\"\*.py\")" src/backend/whymath_backend/ops/declared_unwired_audit.py
# 선언≠배선 감사기 현행 판정 (본 점검 변경이 무영향인지)
python3 -m whymath_backend.ops.declared_unwired_audit; echo "EXIT=$?"
```

### A-3. `ai_llm_inventory_2026-07.xlsx` 델타 대조 (2026-08-10 — 본 절이 델타의 텍스트 정본)

**모델 핀(시트2) — 전건 문자 일치, ARCH-15 acceptance 유지 → 8월판 재발행 불요**: `qwen2-math:1.5b`·`qwen2-math:7b`·`qwen2.5:3b`·`qwen2.5:7b`·`qwen3.5:27b`·`qwen3-vl:8b` = `l3/router.py:53-68` / `claude-sonnet-4-6`·`claude-opus-4-7` = `config.py:351,358` / `BAAI/bge-m3`(1024)·`text-embedding-3-large`(3072) = `config.py:900,907` — openpyxl 재로드 대조.

**상태 칸 stale 3곳**:

| 시트·행 | xlsx 표기(07-24) | 08-10 실측 |
|---|---|---|
| 시트2 OCR TexTeller | "Phase B 스텁 / 계획(미배선)" | **Phase C·동작**(`recognize.py:144`) — `[ocr-heavy]` extra·Phaiakes9 검증 |
| 시트2·시트3 Qwen3-VL 인식기 | "보류(NotImplementedError)" | **비동기 경로 실배선**(`recognize.py:207` — 2026-07-31 정정·동기 진입만 의도적 RuntimeError). 라이브 인식 정확도는 여전히 미검증(§5-①) |
| 시트3 WH-1 판단 루프 로컬화 | "현재 Claude Haiku(A) → 로컬 전환은 측정 조건" | 코드 실측은 처음부터 **LOCAL 라우팅**(`wh1_llm_policy.py:149` `subscription="free"` → 라우터 규칙상 LOCAL) — "Claude Haiku(A)"는 `04a` §6의 설계 옵션 표기이지 현행 코드가 아님 |

부수 오기: 시트2 "rapid-layout (MfdatDetector)" → 클래스명은 `MfdDetector`.
