# SSM 가동 인수인계 — Kiki 따라하기 가이드

> **작성일**: 2026-07-09 | **버전**: 1.0 | **대상**: Kiki(라이브 머신·키 소관) | **범위**: 실행 가이드(문서)
>
> **한 줄**: SSM 문서·프로세스는 전부 `main`에 있고, 남은 건 **하드웨어·키가 있어야 켤 수 있는 3트랙**뿐이다. 이 문서는 그 3트랙을 *복붙 가능한 명령·기대 출력·검증·막히면 조치*와 함께 순서대로 따라할 수 있게 통합한 가이드다.
>
> **시크릿 규율**: 아래 명령의 키 값(`sk-ant-…`·`pk-lf-…`)은 **실제 발급 키로 치환**해 입력한다. 키는 **환경변수로만** 주입하고 코드·문서·git에 절대 넣지 않는다(CLAUDE.md 하드코딩 금지).
>
> **PowerShell 규율**: `&&` 없이 **한 줄씩** 실행(Windows 세션 인계 규약).

---

## 0. 3트랙 지도 (무엇을·왜·순서)

| 트랙 | 무엇 | 의존 | 왜 Kiki 몫 |
|---|---|---|---|
| **A** 라이브 Routine 생성 | 분기 SSM 스캔 자동 발동 예약 | 독립(언제든) | 스케줄링 도구가 **승인 게이트** 필요 — 대화형 세션에서만 |
| **B** 계측선 S1~S4 가동 | 파일럿 측정용 라이브 계측 켜기 | 순차(S1→S2→S3→S4) | **라이브 키 + Phaiakes9 GPU + β 표본** 필요 |
| **C** 파일럿 측정·재판정 | 6후보 측정 → SSM 게이트 재판정 | **B 완료 후**(#12만 선행 가능) | B의 실측 데이터가 전제 |

```
A ─────────────(독립·병렬)─────────────▶ 완료
B  S1 ─▶ S2 ─▶ S3 ─▶ S4 ───────────────▶ 계측선 가동
C                    └─(B후)─▶ 파일럿 측정 ─▶ SSM §5 재판정
   (#12 교수학 루브릭은 WH-1 자체평가라 B 없이 선행 가능)
```

> **최소 목표**: "로컬 온리"면 B의 S2까지만 해도 로컬 LLM 파이프라인은 돈다. **비용/지연 실측(파일럿 대부분)** 은 클라우드·Langfuse 키가 필요한 "풀 경로"(S1·S4)까지 가야 한다.

---

## 트랙 A — 라이브 Routine 생성 (독립)

분기 스캔이 "잊혀서 안 도는" 것을 막는 예약. 자동 세션 도구가 승인 게이트에 막혀 자동 세션에선 못 만든다 → **대화형 Claude Code 세션이나 앱의 스케줄 UI**에서 아래 스펙대로 생성.

- [ ] **A-1. Routine 생성** (스펙 정본 = `system_superiority_maintenance.md` §8 "분기 리마인더 스케줄")
  - 이름: `SSM 분기 지평 스캔 (자동)`
  - cron: `0 0 1 1,4,7,10 *` (1/4/7/10월 1일 00:00 UTC = 09:00 KST) · **다음 발동 2026-10-01(Q4)**
  - 모드: **새 세션 발동**(fresh-session-per-fire) · 완료 시 **푸시 알림**
  - 정책: 자동 스캔·리포트 산출 후 **draft PR**(auto-merge 금지 — 사람이 검수·머지)
  - 발동 프롬프트: §8의 "발동 프롬프트 요지" 그대로(표준 숙지→4축 조사→§5 게이트→§8 리포트→MEMORY→draft PR)
  - **검증**: 생성 후 스케줄 목록에 `next_run_at = 2026-10-01` 확인.
  - **막히면**: 자동/비대화형 세션에선 "MCP tool call requires approval"로 실패 — 대화형 세션에서 재시도.

---

## 트랙 B — 계측선 S1~S4 가동 (순차)

> 대상 머신: 새 Phaiakes9(라이젠 AI Max+ 395·Radeon 8060S·Windows 11). 깊은 절차·함정은 `infra/phaiakes9/LIVE_LLM_ACTIVATION.md`·`GPU_ACTIVATION_FOLLOWUP.md`가 정본 — 이 가이드는 순서와 핵심 명령을 자기완결로 담는다.

### S0. 준비 (최초 1회)
- [ ] repo·venv:
  ```powershell
  git clone https://github.com/kiki-s-broom/WhyMath.git
  cd WhyMath\src\backend
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  pip install -e ".[dev]"
  ```

### S2. 로컬 LLM 가동 (Ollama·GPU·모델) — *로컬 온리면 여기까지*
> 순서상 로컬을 먼저 세워야 프리플라이트(S1)의 도달성·LOCAL 폴백이 의미 있다.
- [ ] **Ollama 설치**: https://ollama.com/download/windows → 설치.
- [ ] **GPU 오프로드 확인**: `ollama run qwen2.5:3b "2+2="` 실행 후 작업관리자 GPU(8060S) 사용률↑ 확인. CPU 폴백이면 Ollama·AMD Adrenalin 최신화.
- [ ] **모델 6종 pull**(라우터 매트릭스 정본):
  ```powershell
  ollama pull qwen2-math:1.5b
  ollama pull qwen2-math:7b
  ollama pull qwen2.5:3b
  ollama pull qwen2.5:7b
  ollama pull qwen3.5:27b
  ollama pull qwen3-vl:8b
  ```
  - **검증**: `ollama list`에 6종 전부. 또는:
  ```powershell
  cd WhyMath\src\backend
  .venv\Scripts\Activate.ps1
  python -c "import asyncio; from whymath_backend.l3.providers.ollama import OllamaProvider; s=asyncio.run(OllamaProvider().check_status()); print('reachable:',s.reachable,'missing:',list(s.missing),'READY:',s.all_present)"
  ```
  기대: `reachable: True · missing: [] · READY: True`.
- [ ] **백엔드 env**:
  ```powershell
  [Environment]::SetEnvironmentVariable("WHYMATH_OLLAMA_HOST","http://127.0.0.1:11434","User")
  [Environment]::SetEnvironmentVariable("WHYMATH_OLLAMA_REQUEST_TIMEOUT_S","120","User")
  ```
- [ ] **GPU 활성(p50<2s 게이트)** — `total_vram=0`이면 `GPU_ACTIVATION_FOLLOWUP.md`:
  - BIOS → Advanced → Graphics → **UMA Frame Buffer Size: Auto → Fixed**(권장 48GB)
  - Windows AMD Adrenalin 26.x+ · `%UserProfile%\.wslconfig` 메모리 110GB · PowerShell `wsl --shutdown`
  - (Linux 이관 시) 커널 6.17+ · **ROCm 7.2.0+** · Ollama systemd `vulkan.conf` override → `systemctl restart ollama`
  - **검증**: `ollama` 로그 `inference compute id=vulkan · total_vram="48 GiB"` · 재벤치 tok/s 5-12x·**p50<2,000ms**.

### S1. 라이브 키 투입 + 프리플라이트 (풀 경로)
> 클라우드 승급·비용/지연 실측·Langfuse 관측을 켠다. **로컬 온리면 생략 가능**(단 파일럿 비용/지연 측정은 이 단계 필요).
- [ ] **키 주입**(값은 실 발급 키로 치환):
  ```powershell
  [Environment]::SetEnvironmentVariable("WHYMATH_ANTHROPIC_API_KEY","sk-ant-…","User")
  [Environment]::SetEnvironmentVariable("WHYMATH_LANGFUSE_PUBLIC_KEY","pk-lf-…","User")
  [Environment]::SetEnvironmentVariable("WHYMATH_LANGFUSE_SECRET_KEY","sk-lf-…","User")
  ```
  (모델 alias가 `404 model not found`면 `WHYMATH_ANTHROPIC_MODEL_MID`/`_HIGH`로 키에서 실재하는 ID 핀.)
- [ ] **키 투입 직후 1회 검증**:
  ```powershell
  cd WhyMath\src\backend
  .venv\Scripts\Activate.ps1
  python -m whymath_backend.ops.live_preflight --via-pipeline
  ```
  - **기대**: ① `cloud_configured=True` ② `langfuse_configured=True` · Anthropic/Ollama 도달 OK · CLOUD_MID(Sonnet) **실 1콜 → 실측 cost_krw·토큰** 출력 · Langfuse에 `l3_routing` 이벤트 기록·flush.
  - **종료코드**: `0`=정상 · `2`=설정됐는데 도달 불가/스모크 실패.
  - 변형: `--no-smoke`(실 호출 없이 판정·도달성만) · `--json preflight.json`(리포트 저장).

### S3. β 표본 축적 + 베이스라인 캡처
- [ ] β 트래픽/DB 축적(세션·attempt·dialogue). 표본이 쌓여야 지표가 `NO_DATA→MEASURED`로 전환.
- [ ] **코호트 베이스라인**:
  ```powershell
  cd WhyMath\src\backend
  .venv\Scripts\Activate.ps1
  python -m whymath_backend.harness.surrogate_baseline_report
  ```
  (기간 한정 시 `--since 2026-10-01T00:00:00 --until 2026-12-31T23:59:59`, 개인 `--user-id <UUID>`.)
  - **검증**: 11지표 커버리지 **MEASURED n/11** 상승(가짜 0 없음 — 미측정은 사유 표기).

### S4. 비용/지연 실측 보정
- [ ] Langfuse `l3_routing`에서 실측 토큰 p50 확보 → `src/backend/whymath_backend/l3/router.py`의 `_EST_ASSUMED_INPUT_TOKENS`·`_EST_ASSUMED_OUTPUT_TOKENS`에 대입 → `CLOUD_MIN_COST_KRW` **자동 재계산**(단일 공식). `CLOUD_LATENCY_MS` placeholder도 실측 보정·`USD_TO_KRW=1540` 라이브 확인.
  - **검증**: 추정 vs 실측 비용 괴리(스캔 시점 ≈1/69) 해소.

### B 함정표 (막히면)
| 증상 | 원인 | 조치 |
|---|---|---|
| `/status ready=false·missing=[…]` | 모델 일부 미pull | missing 태그 그대로 `ollama pull` |
| GPU 대신 CPU로 느림 | Ollama가 8060S 미감지 | Ollama·Adrenalin 최신화, `ollama ps` 확인 |
| 클라우드 결정인데 `RuntimeError`(키 없음) | `WHYMATH_ANTHROPIC_API_KEY` 미설정 | S1 키 설정(조용한 강등 없음이 *의도*) |
| 클라우드 404 `model not found` | alias가 키에서 미제공 | `WHYMATH_ANTHROPIC_MODEL_MID/_HIGH`로 실 ID 핀 |
| 비용/토큰이 Langfuse에 안 보임 | Langfuse 키 미설정(sink no-op) | `WHYMATH_LANGFUSE_PUBLIC_KEY`/`_SECRET_KEY` 설정 |

---

## 트랙 C — 파일럿 측정·재판정 (B 후)

계측선(B)이 켜지면 SSM 2026-Q3 파일럿을 측정해 **SSM 도입 게이트(§5)에서 재판정**(파일럿→도입/기각). 측정 지표는 `ssm_scan_2026-Q3.md` 게이트 대기 큐가 정본.

- [ ] **#1 DeepSeekMath V2/V3.2** — Phaiakes9 서빙 tok/s·p50 + 수학 정확도 A/B vs qwen2-math. (S2·S1)
- [ ] **#2 PRM 재랭킹** — L3 검증 커버리지·PRM 통과율 델타. (S1·S3)
- [ ] **#8 Qwen3-Embedding** — 한국어 의미검색 품질 A/B vs bge-m3 + 8B 비용/지연. (S1·S3·S4)
- [ ] **#10 PaddleOCR-VL** — 한국어 손글씨 정확도(목표 90%) 실측 vs 현 하이브리드. (S2)
- [ ] **#12 교수학 루브릭** — 프롬프트 템플릿 루브릭 자체 평가·회귀테스트. **B 없이 선행 가능**(WH-1 오프라인·`harness/pedagogical_rubric.py` 이미 존재).
- [ ] **#4 NuminaMath-1.5** — 계측 아님. **법적 게이트**(공공누리/약관, `docs/data/licensing_safety.md` 소관) 별도 처리.
- [ ] **재판정 기록**: 각 측정 결과로 SSM §5 판정 갱신 → `MEMORY.md` 결정 로그 + 필요 시 `ssm_scan_2026-Q4.md`. 도입 판정 시에만 `CLAUDE.md` 기술 스택 표 갱신.

---

## 완료 기준 (전체)

- [ ] 트랙 A: Routine 생성·`next_run_at=2026-10-01` 확인
- [ ] 트랙 B: `live_preflight` green(종료코드 0) · p50<2s · 베이스라인 커버리지 n/11 · 비용 실측 보정
- [ ] 트랙 C: 파일럿 5건(#1·2·8·10·12) 측정 → SSM 게이트 재판정 · #4 법적 처리
- [ ] 이상적 시점: **2026-Q4 분기 스캔(10/1) 전** 재판정 완료 → 다음 스캔이 실측 기반으로 시작

---

**연계 문서**: `system_superiority_maintenance.md`(SSM 표준·§8 Routine 스펙·§5 게이트) · `measurement_line_enablement.md`(계측선 런북 상세) · `ssm_scan_2026-Q3.md`(파일럿·측정 지표) · `../../infra/phaiakes9/LIVE_LLM_ACTIVATION.md`·`GPU_ACTIVATION_FOLLOWUP.md`(하드웨어 정본·함정) · `../data/licensing_safety.md`(#4 법적) · `../../MEMORY.md`(판정 배출구).
