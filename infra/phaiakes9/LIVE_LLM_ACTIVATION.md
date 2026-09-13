# 라이브 LLM 활성화 런북 — 새 Phaiakes9 (라이젠 AI Max+ 395 · Windows 11)

> **대상 하드웨어**: GMKtec AMD 라이젠 AI Max+ 395 (Strix Halo) · Radeon 8060S iGPU(RDNA 3.5·40CU)
> · 통합 LPDDR5X(최대 128GB) · Windows 11 Pro.
> **목적**: 이 머신에서 WhyMath의 **라이브 LLM 파이프라인 3종**(발문 다양화 rephrase ·
> LLM 동등문제 생성 · misconception judge shadow)을 실제로 켜는 정확한 절차.
> **근거**: 전부 코드 정본에서 추출(라우터 매트릭스 `l3/router.py` · provider `l3/providers/` ·
> config env var `config.py`). 기존 `SETUP_GUIDE.md`는 Linux(systemd) 전제 — 본 런북은 Windows
> 우선, Linux 이관 시 SETUP_GUIDE로 합류.
>
> **PowerShell 규율**: `&&` 없음 · 한 줄씩 실행 (세션 인계 규약).

---

## 0. 이 하드웨어가 바꾸는 것 (한 줄)

통합 LPDDR5X 덕에 **QUALITY 티어(qwen3.5:27b)까지 GPU 메모리 상주**가 현실적 —
클라우드 승급(CLOUD_MID/HIGH) 의존도를 낮추고 라우터 목표 분포(LOCAL 80%)를 로컬에서 소화한다.

---

## 1. Ollama 설치 (Windows)

1. https://ollama.com/download/windows 에서 Windows 설치본 설치 (AMD GPU는 최신 Ollama가
   ROCm/Vulkan 백엔드로 자동 감지 — 8060S는 gfx1151).
2. GPU 오프로드 확인:
   ```powershell
   ollama run qwen2.5:3b "2+2="
   ```
   응답 후 작업 관리자에서 GPU(8060S) 사용률이 뛰는지 확인. GPU 미사용(CPU 폴백)이면
   Ollama 최신 버전 + AMD Adrenalin 드라이버 갱신 후 재시도.
3. (선택·성능) 시스템 환경 변수 — SETUP_GUIDE의 systemd 값을 Windows로 이식:
   ```powershell
   [Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "2", "User")
   [Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "4", "User")
   [Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "10m", "User")
   ```
   설정 후 Ollama 재시작(트레이 아이콘 Quit → 재실행).

---

## 2. 모델 pull — 코드 정본 6종 (⚠ pull_models.sh 기본값으론 부족)

`/status`의 `ready=true`는 **라우터 매트릭스 전 모델 설치**를 요구한다
(`LOCAL_MODEL_MATRIX` + `QUALITY_MODEL_ID`, `l3/providers/ollama.py::_REQUIRED_MODEL_IDS`):

```powershell
ollama pull qwen2-math:1.5b
ollama pull qwen2-math:7b
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
ollama pull qwen3.5:27b
ollama pull qwen3-vl:8b
```

| 태그 | 라우터 좌석 | 용도 |
|---|---|---|
| `qwen2-math:1.5b` | MATH×FAST | 풀이·즉답(p50≈1s) |
| `qwen2-math:7b` | MATH×MID | 풀이·깊이 |
| `qwen2.5:3b` | GENERAL×FAST | NLP·경량 저작 |
| `qwen2.5:7b` | GENERAL×MID | **동등문제 저작·rephrase·judge(general_mid)** |
| `qwen3.5:27b` | QUALITY(비동기 전용) | 킬러 난이도(동기 호출 금지) |
| `qwen3-vl:8b` | VISION×FAST | OCR·그래프(멀티모달) |

> **실측 divergence(수정 전 주의)** ①: `infra/phaiakes9/pull_models.sh` 기본은 `qwen2-math:7b`
> **1종만** 받는다 — Linux에서 쓸 땐 `WHYMATH_MODELS_OVERRIDE="qwen2-math:1.5b,qwen2-math:7b,qwen2.5:3b,qwen2.5:7b,qwen3.5:27b"` 필요.
> ②: CLAUDE.md 기술 스택 표(Qwen3-Math·DeepSeek-Math)는 상위 의도이고 **코드 매트릭스(위 표)가
> 실제 pull 정본**. ③: `healthcheck.sh` 헤더 주석의 `qwen2.5-math:7b-instruct`는 stale.

---

## 3. WhyMath 백엔드 env (PowerShell)

```powershell
[Environment]::SetEnvironmentVariable("WHYMATH_OLLAMA_HOST", "http://127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("WHYMATH_OLLAMA_REQUEST_TIMEOUT_S", "120", "User")
```
- 타임아웃 기본 30s는 FAST 동기 기준 — **라이브 저작·rephrase는 120 권장**(7b 저작 p50≈4s·꼬리 여유).
- `WHYMATH_ANTHROPIC_API_KEY`는 **로컬 전용이면 설정하지 않는다**(라우터가 LOCAL 결정이면
  AnthropicProvider는 지연 연결이라 호출 자체가 없음. 클라우드 결정+키 없음이면 명확히 실패 —
  조용한 강등 없음).

레포 준비(새 PC 최초 1회):
```powershell
git clone https://github.com/kiki-s-broom/WhyMath.git
cd WhyMath\src\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

---

## 4. 스모크 검증 (라이브 게이트)

```powershell
cd WhyMath\src\backend
.venv\Scripts\Activate.ps1
python -c "import asyncio; from whymath_backend.l3.providers.ollama import OllamaProvider; s = asyncio.run(OllamaProvider().check_status()); print('reachable:', s.reachable); print('missing:', list(s.missing)); print('READY:', s.all_present)"
```
기대: `reachable: True` · `missing: []` · `READY: True`. `missing`에 태그가 남으면 §2로.

(API 서버까지 띄우면 `GET /status`가 같은 판정을 JSON으로 준다 — `ready`·`missing` 필드.)

---

## 5. 파이프라인 ① — 발문 다양화 rephrase (가장 먼저·가장 안전)

**왜 먼저**: fail-closed 설계라 실패해도 원문 유지(수치 오염 원천 불가). 결정론 3중 검증
(방정식 substring 봉인·추가 등식 차단·위생)이 LLM 출력을 봉인. 산출물이 코퍼스 v0를 덮지 않고
별 경로에 생김.

```powershell
cd WhyMath\src\backend
.venv\Scripts\Activate.ps1
python -m whymath_backend.harness.problem_corpus_rephrase --in ..\..\data\corpus\problem_bank_generated_v0\problems.jsonl --out ..\..\data\corpus\problem_bank_rephrased_v0\problems.jsonl --temperature 0.9
```

- provider 미주입 → 내부에서 표준 CompositeProvider(Ollama 로컬) 자동 구성. 라우터가
  GENERAL(qwen2.5) 저작 패밀리로 태움.
- stdout JSON 리포트에서 확인: `rephrased`(성공 다양화 수) vs `unchanged`(원문 유지 수) +
  `unchanged_reason_sample`(사유 표본). **비-quad 발문(미적분 삼차 계열)은 방정식 추출 밖이라
  의도적으로 unchanged** — 정상.
- 산출 JSONL은 사람 검수 전 v0 — repo 커밋은 검토 후 결정(rephrase 산출물은 라이브 LLM 결과라
  기본 미커밋 규약).

## 6. 파이프라인 ② — LLM 동등문제 생성 (llm_generator·라이브 배치)

`l3/equivalent/llm_generator.py` docstring L40-92의 핸드오프 절차가 정본. 요약:

```python
# WhyMath\src\backend 에서 python 대화형 또는 스크립트
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.providers.ollama import OllamaProvider
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID  # 배선부는 계약 면제
from whymath_backend.schema.enums import Subject

gen = LLMEquivalentProblemGenerator(
    OllamaProvider(),  # 실 Ollama(지연 연결). None이면 Composite 자동 구성
    misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
    topic_hint="이차방정식 — 두 근 중 큰 근을 구하는 형태(답 하나)",
    subject=Subject.공통,
    slug_prefix="wm-gen-quad",
)
# 이후 orchestrator.run_batch(spec, gen, n=…, store=…)로 게이트+dedup 경유 저장
```

- 온도 0.9·authoring_family=GENERAL 기본(qwen2-math는 저작 mode collapse — S2-h 실측).
- **LLM 출력은 S2-a 게이트 통과 전 학생 노출 자격 없음** — 게이트가 최종 봉인.
- 참고: 스켈레톤 결정론 배치(`problem_corpus_batch`)는 **LLM 0**이라 이 머신 GPU와 무관 —
  코퍼스 materialization은 어디서든 동일 산출.

## 7. 파이프라인 ③ — misconception judge (shadow부터)

그래듀에이션 규약(`docs/architecture/04b_misconception_judge_graduation.md`·shadow 런북) 준수 —
**바로 gate on 금지, shadow 측정 먼저**:

```powershell
[Environment]::SetEnvironmentVariable("WHYMATH_MISCONCEPTION_JUDGE_ROUTING", "general_mid", "User")
```
- `general_mid`(qwen2.5:7b) 권장 — 기본 `fast_math`(qwen2-math:1.5b)는 2026-06-15 라이브 측정에서
  한국어 판정 형식 미준수(FP 감소 0) 실측.
- shadow 측정: `WHYMATH_MISCONCEPTION_JUDGE_SHADOW=true` (+ semantic_mode=shadow 전제·비차단).
- **라이브 게이트(`WHYMATH_MISCONCEPTION_JUDGE_ENABLED=true`)는 shadow 지표 검토 후에만** —
  coach `_gate`(api/coach.py L574)가 이 플래그를 읽는다.

---

## 8. 순서 요약 (체크리스트)

- [ ] §1 Ollama 설치 + GPU 오프로드 확인
- [ ] §2 모델 6종 pull (`ollama list`로 확인)
- [ ] §3 env 2종 설정 + 레포/venv 준비
- [ ] §4 스모크: `check_status()` READY=True
- [ ] §5 rephrase 1회 실행 → 리포트에서 rephrased>0 확인 (**첫 라이브 이정표**)
- [ ] §6 llm_generator 소량(n=5) 배치 → accepted_stored 확인
- [ ] §7 judge shadow 측정 → 지표 검토 → (별도 결정) gate on
- [ ] (풀 경로) §10 클라우드·관측성 키 설정 → `/status`가 `cloud_configured`·Langfuse 활성 보고
- [ ] (풀 경로) §11 라이브 계측 판독 → Langfuse `l3_routing`에서 `cost_tier` 분포·실측 `cost_krw` 확인
- [ ] 결과·수율을 MEMORY.md 결정 로그에 기록

> **로컬 온리 vs 풀 경로**: §1~§7은 **로컬(Ollama)** 활성화 — rephrase·동등문제 생성·judge는
> 전부 로컬 결정이라 클라우드 키 없이 돈다. §10·§11은 **풀 경로**(클라우드 승급 + 관측성) — 라우터가
> CLOUD_MID/HIGH를 내리는 호출(킬러·자기검증 QUALITY→클라우드)과 **비용/로컬 비율 실측**(S1 게이트②)을
> 실제로 켜고 읽는 단계다. 로컬만 검증할 거면 §7에서 멈춰도 된다.

## 9. 알려진 함정

| 증상 | 원인 | 조치 |
|---|---|---|
| `RuntimeError: ollama … 설치되지 않았습니다` | venv에 ollama 클라이언트 없음 | `pip install ollama` |
| `/status ready=false·missing=[…]` | §2 divergence ① — 모델 일부 미pull | missing 태그 그대로 pull |
| rephrase 전건 unchanged·"provider 예외" | Ollama 데몬 미기동/호스트 불일치 | `WHYMATH_OLLAMA_HOST` 확인·데몬 기동 |
| 저작이 같은 문제 반복(mode collapse) | MATH 패밀리로 저작 | authoring_family=GENERAL 기본 유지(S2-h) |
| QUALITY 27b 동기 호출 503 | 설계 의도(비동기 전용) | Celery 워커(concurrency 1) 경유·Linux 이관 시 |
| GPU 대신 CPU로 느림 | Ollama가 8060S 미감지 | Ollama·Adrenalin 최신화, `ollama ps`로 확인 |
| 클라우드 결정인데 `RuntimeError`(키 없음) | `WHYMATH_ANTHROPIC_API_KEY` 미설정 | §10 키 설정(조용한 강등 없음이 *의도* — CLAUDE.md) |
| 클라우드 호출 404 `model not found` | 모델 alias가 키에서 미제공 | §10 `WHYMATH_ANTHROPIC_MODEL_MID/HIGH`로 실 ID 핀 |
| 비용/토큰이 Langfuse에 안 보임 | Langfuse 키 미설정(sink 영구 no-op) | §10 `WHYMATH_LANGFUSE_PUBLIC_KEY`/`_SECRET_KEY` 설정 |

---

## 10. 클라우드·관측성 활성화 (풀 경로 — 라이브 키)

> **로컬 온리면 생략.** 이 단계는 라우터가 CLOUD_MID/HIGH를 내리는 호출(킬러·자기검증 QUALITY 승급)과
> **비용 실측 관측**(S1 게이트②·PR #465/#467)을 켠다. 시크릿은 **env로만** 주입(CLAUDE.md 하드코딩 금지).

```powershell
# 클라우드 LLM (Anthropic) — CLOUD_MID(Sonnet)·CLOUD_HIGH(Opus) 경로
[Environment]::SetEnvironmentVariable("WHYMATH_ANTHROPIC_API_KEY", "sk-ant-…", "User")
# 관측성 (Langfuse) — 없으면 계측이 계산만 되고 버려진다(sink 영구 no-op)
[Environment]::SetEnvironmentVariable("WHYMATH_LANGFUSE_PUBLIC_KEY", "pk-lf-…", "User")
[Environment]::SetEnvironmentVariable("WHYMATH_LANGFUSE_SECRET_KEY", "sk-lf-…", "User")
```

| env | 역할 | 미설정 시 |
|---|---|---|
| `WHYMATH_ANTHROPIC_API_KEY` | CLOUD_MID/HIGH 생성 활성 | 클라우드 결정 시 **명확한 오류**(조용한 강등 없음) |
| `WHYMATH_ANTHROPIC_MODEL_MID`/`_HIGH` | 클라우드 모델 ID 핀 | 기본 alias(`claude-sonnet-4-6`/`claude-opus-4-7`, config.py:260-273) 사용 |
| `WHYMATH_LANGFUSE_PUBLIC_KEY`/`_SECRET_KEY` | 관측성(Langfuse) 활성 | `langfuse_configured=False` → **LangfuseSink 영구 no-op**(비용 계산은 되나 관측에 안 흐름) |
| `WHYMATH_LANGFUSE_HOST` | 셀프호스트 Langfuse | 기본 `https://cloud.langfuse.com` |

> **⚠ 모델 ID 실재성**: 기본값 `claude-sonnet-4-6`/`claude-opus-4-7`는 프로젝트 alias다. 발급 키에서
> 그 ID가 `404 model not found`면 `WHYMATH_ANTHROPIC_MODEL_MID`/`_HIGH`로 **키에서 실제 사용 가능한
> ID**를 핀한다(코드 변경 0 — env 오버라이드가 정본, config.py 주석).

**활성 확인 — 단일 명령(키 투입 직후 1회)**:
```powershell
cd WhyMath\src\backend; .venv\Scripts\Activate.ps1
python -m whymath_backend.ops.live_preflight            # 스모크 on(기본) — 실 CLOUD_MID 1콜
# python -m whymath_backend.ops.live_preflight --no-smoke        # 판정·도달성만(실 호출 없음)
# python -m whymath_backend.ops.live_preflight --json preflight.json   # JSON 리포트도 저장
# python -m whymath_backend.ops.live_preflight --via-pipeline    # Redis·서버 없이 §11 Langfuse 기록까지 확인
```
> **Redis·서버 없이 §11 Langfuse 기록까지 확인**: `python -m whymath_backend.ops.live_preflight --via-pipeline`.
> 스모크를 `l3.pipeline.generate`(라우터→캐시→provider→LangfuseSink)로 태워 **`l3_routing` 이벤트를
> 실제 기록·flush** 한다 — 전체 앱이 요구하는 PII 암호화(cryptography)·pgvector·Redis·uvicorn을 전부
> 우회한다(conda/venv 뒤엉킴 회피). anthropic 설정 시 CLOUD_MID(sync) 실 1콜, 미설정 시 LOCAL 폴백
> (0원이라도 기록 증명 성립), Langfuse 미설정이면 graceful skip. 실행 후 §11 대시보드에서 레코드 확인.
이 한 명령이 서버 기동 없이 방금 넣은 키의 계측 흐름을 즉석 검증한다(내부적으로 /status가 하는
`check_status()`를 provider 직접 호출로 대체):
- **① cloud_configured** = `Settings().anthropic_configured`(config.py:965) — Anthropic 키 감지.
- **② langfuse_configured** = `Settings().langfuse_configured`(config.py:956) — 공개키+시크릿키 둘 다.
- **도달성** — Anthropic `check_status()`(anthropic.py:362)·Ollama `check_status()`(ollama.py:317).
- **③ 클라우드 스모크** — 스모크 on·키 설정 시 실 **CLOUD_MID(Sonnet)** 1콜 → 실측 `cost_krw`·토큰
  출력(`actual_cost_krw`, router.py:154). 키 없으면 "스모크 skip(키 없음)"으로 graceful skip.
- 종료 코드: **0**=정상(미설정은 정보) · **2**=설정됐는데 도달 불가/스모크 실패. 시크릿 값은 절대
  출력하지 않는다(설정 여부 bool·비용·토큰만). 출력의 **③ 실측 비용·토큰**을 아래 §11 판독과 대조한다.

---

## 11. 라이브 계측 판독 (S1 게이트② — 투입 즉시 나오는 것)

> §10 키가 들어가면 **코드 변경 0으로** 루프당 실측 비용·로컬:클라우드 비율이 관측에 흐른다
> (PR #465 계측 배선 + #467 judge seam→Langfuse). 판독 경로:

1. **Langfuse `l3_routing` 이벤트** (이벤트명 `l3_routing`, langfuse_sink.py:47) — 모든 L3 생성 1건당 1레코드:
   - `cost_tier`(LOCAL/CLOUD_MID/CLOUD_HIGH) 분포 → **로컬:클라우드 비율**(라우터 목표 로컬 80%).
   - `local_family`·`local_model`·`cache_hit`(캐싱 적중률 KPI).
   - **실측**(#465): `cost_krw`·`input_tokens`·`output_tokens`·`latency_ms` — 추정 `est_cost_krw`/
     `est_latency_ms`와 **별개 키**(추정 vs 실측 구분). **`cost_krw=None`(클라우드 토큰 미상)과
     `0.0`(로컬)은 다르다** — 미상은 지어내지 않고 None.
   - judge 게이트/shadow LLM 호출 비용도 이제 여기로 흐른다(#467 — `_judge_for_gate`가 공유 sink 주입).
2. **`GET /v1/me/harness-metrics`** (api/me.py:1853, 대리 지표 7종) — 지표 ④ `tokens_per_turn`이
   Dialogue 토큰 적재 시 `NO_DATA`→`MEASURED` 전환(본 계측은 trace/GenerationLog 경로; pipeline→
   Dialogue 토큰 영속은 대화 서비스 소관·별도 후속).
3. **`GenerationLog` 테이블** — 호출별 토큰·지연 실측 적재(provenance_bridge). 배치 회계·집계용.

**첫 라이브 비용 이정표**: §10 키 투입 후 클라우드를 타는 호출(예: 킬러 문항·자기검증 QUALITY 승급)을
1회 유발 → Langfuse에서 그 `l3_routing` 레코드의 `cost_tier=CLOUD_*`·`cost_krw>0`·토큰 실측 확인.
로컬 호출은 같은 레코드가 `cost_tier=LOCAL`·`cost_krw=0.0`. 두 분포 비율이 **S1 게이트② "루프당 비용
실측·로컬 80%"** 판정의 근거다.

### 11.1 판독 자동화 — `cost_report` 집계기 (개별 레코드 대신 분포로)

Langfuse UI에서 레코드를 눈으로 세는 대신, **누적 `l3_routing`을 한 번에 집계**해 p50/p90·
로컬비율·튜닝 제안을 뽑는다. 프리플라이트(§10)가 1콜(비대표)만 낸다면, 이 판독기는 라이브
트래픽 몇 분치를 대표 분포로 요약한다(코드: `src/backend/whymath_backend/ops/cost_report.py`).

```powershell
# 라이브 세션 직후 — 오늘치(--days 1) 집계. Langfuse 키(§10)가 설정돼 있어야 실조회한다.
python -m whymath_backend.ops.cost_report --days 1
python -m whymath_backend.ops.cost_report --days 1 --json report.json   # 기계 판독도 저장
```

출력 판독:
- **분포**: `input_tokens`/`output_tokens`/`cost_krw`/`latency_ms`의 p50·p90·평균·합(실측 None은
  표본 제외 — 캐시 히트·비동기는 미상이지 0이 아님).
- **로컬:클라우드 비율**: 목표 80% 로컬 대비 실측 비중.
- **튜닝 제안**: `_EST_ASSUMED_INPUT_TOKENS`/`_EST_ASSUMED_OUTPUT_TOKENS` ← 실측 토큰 p50.

### 11.2 S1 게이트② 판정 체크리스트 (이 순서로)

1. `python -m whymath_backend.ops.live_preflight --via-pipeline` — Langfuse 기록 흐름 1콜 확인(§10).
2. 대표 트래픽 유발 — 킬러 문항 등으로 클라우드 승급 호출 + 로컬 호출을 섞어 수십 건 흘린다.
3. `python -m whymath_backend.ops.cost_report --days 1` — 분포·비율·튜닝 제안 확인.
4. 제안 p50를 `src/backend/whymath_backend/l3/router.py`의 `_EST_ASSUMED_INPUT_TOKENS`/
   `_EST_ASSUMED_OUTPUT_TOKENS`(현재 보수적 기본 1000)에 대입 → `CLOUD_MIN_COST_KRW`·`est_cost_krw`·
   `guard_cloud` 임계값이 단일 공식으로 자동 재계산(router.py §H 후속 4). est/actual 분리는 유지.
5. `cost_krw` p50/합 + 로컬비율로 **"루프당 비용 실측·로컬 80%"** 를 판정 → S1 게이트② 종료.

> 이 두 단계(11.1·11.2)는 AI가 라이브 키 *전*에 선제 준비한 측정 하네스다(`status_roadmap_2026-07`
> §4 병목 #2). Kiki 수동 시간은 "키 투입 → 트래픽 → 스크립트 1회 실행"으로 최소화된다.
