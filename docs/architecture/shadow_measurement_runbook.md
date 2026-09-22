# Shadow → Canary 측정 런북 (오개념 게이트 · WH-1 verify verdict)

> **목적**: 오개념 진단의 네 게이트를 *노출 없이* shadow 모드로 켜고, 구조화 관측 로그를 모아
> harvest 도구로 집계해 **canary/노출(on) 승격 여부**를 정량 데이터로 결정하는 운영 절차.
> 설계 근거: `math_dsl_remediation_design.md` §1.3(crosswalk)·§2.5(wrong_form),
> `04b_misconception_judge_graduation.md`(judge·semantic). 정본 패턴: `l4/step_shadow_harvest`.

## 원칙 (협상 불가)

- **측정 전 노출 금지**: 모든 게이트는 shadow(비노출·비차단)로 *먼저 측정*한 뒤에만 canary/on을
  검토한다(의사결정 우선순위 #1 학생 안전 · #3 교수학적 정확성 ≫ #6 비용).
- **프라이버시**: 관측 레코드엔 학생 풀이 원문·식별자·judge 근거가 *구조적으로* 없다
  (`extra="forbid"` + 필드 한정 — 추상 오개념 id·개수·유사도·verdict 카운트만). 로그 sink도
  미성년 PII 취급 규약을 따른다.
- **측정 윈도에만 켠다**: shadow 모드는 비용(임베딩 로드·per-write DB 왕복·judge LLM)을 유발하므로
  상시 on이 아니라 *측정 기간 한정*으로 켠다. 기본은 전부 `off`.

## 게이트 요약

| 게이트 | 켜기(env) | record 로거 | harvest 모듈 | 핵심 결정 변수 |
|---|---|---|---|---|
| crosswalk 매핑 | `WHYMATH_MISCONCEPTION_CROSSLINK_MODE=shadow` | `whymath.l4.misconception.crosslink_shadow.record` | `crosslink_shadow_harvest` | `distinct_canonical_ratio`·`unmapped_kebab_ids`·`canonical_ambiguous_kebab_ids` |
| wrong-form(SymPy) | `WHYMATH_MISCONCEPTION_WRONG_FORM_MODE=shadow` | `whymath.l4.misconception.wrong_form_shadow.record` | `wrong_form_shadow_harvest` | `sympy_only_id_freq`(가치)·`substring_only_id_freq`(결합 유지) |
| semantic 매칭 | `WHYMATH_MISCONCEPTION_SEMANTIC_MODE=shadow` | `whymath.l4.misconception.shadow.record` | `semantic_shadow_harvest` | `semantic_only_id_freq`·`sim_ge_*`(feed 임계) |
| judge 필터 | `…SEMANTIC_MODE=shadow` + `WHYMATH_MISCONCEPTION_JUDGE_SHADOW=true` | `whymath.l4.misconception.judge_shadow.record` | `judge_shadow_harvest` | `remove_rate`(가치)·`uncertain_rate`(신뢰) |

> judge shadow는 semantic 매처가 라이브로 도는 경로에 얹히므로 `SEMANTIC_MODE=shadow`가 *전제*다
> (비용 분리: 매처 shadow는 싸고 judge는 LLM 수 초라 별 토글). judge *노출* 게이트
> (`misconception_judge_enabled`)는 이 측정 이후의 별도 결정이다.

## 절차 (게이트 공통 4단계)

### 1. shadow 켜기 (측정 윈도)
해당 env 플래그를 측정 기간에만 설정한다. 노출·verdict·DB 저장은 불변(off와 비트동일 관측)이고,
관측은 record 로거로만 흐른다.

### 2. 관측 JSONL 수집
로그 sink에서 위 표의 *record 로거 이름* 라인만 골라 한 줄당 JSON(관측 1건)인 `obs.jsonl`로 모은다
(평문 로그·다른 로거 노이즈 배제 — 로거 이름 필터). 수집은 관측 인프라(로그 파이프라인) 몫이며
harvest는 모인 파일을 읽는다.

### 3. harvest 집계 (오프라인·순수·비노출)
```bash
python -m whymath_backend.l4.misconception.crosslink_shadow_harvest   obs.jsonl
python -m whymath_backend.l4.misconception.wrong_form_shadow_harvest  obs.jsonl
python -m whymath_backend.l4.misconception.semantic_shadow_harvest    obs.jsonl
python -m whymath_backend.l4.misconception.judge_shadow_harvest       obs.jsonl
```
각 명령은 사람이 읽는 요약 리포트를 출력하고, *마지막 줄은 파싱 가능한 JSON*(요약 모델
`model_dump_json` — 스냅샷·회귀·대시보드 재적재용)이다.

### 4. 판정 (게이트별 결정 변수 → go/no-go)
아래 게이트별 절을 본다. **구체적 임계(cutoff)는 실 트래픽·제품 판단**이며 이 런북은 *어느 변수를
어느 방향으로 읽는지*만 고정한다(임의 숫자 단정 금지 — CLAUDE.md "모르면 모른다고").

---

## crosswalk 매핑 (kebab-id → canonical M-id)

- **가치 변수**: `distinct_canonical_ratio` — 실 런타임에 등장한 *서로 다른* kebab-id 중
  **canonical 선택 정책**(`select_canonical` — confidence NOT NULL 직접매핑의 strict 최대가
  *단독*일 때만 선정)을 통과한 비율. canary(M-id canonical 플립)는 이 커버리지가 *충분히
  차오른 뒤* 검토한다 — 원시 링크 유무(`distinct_coverage_ratio`)는 1:N을 구분 못 해 참고
  지표로 강등(1:N 링크만 세면 ambiguous 집계가 무의미).
- **큐레이션 우선순위**: `unmapped_kebab_ids` — 자주 등장하나 매핑이 없는 kebab-id부터 사람이
  crosswalk를 채운다(coverage를 올리는 최단 경로).
- **정책 필요**: `canonical_ambiguous_kebab_ids` — 직접매핑 최고 confidence *동률(tie)*이라
  canonical이 자동 선정되지 않은 kebab-id. 플립 전 사람이 우선순위를 확정해야 한다(자동 임의
  선택은 오귀속 위험이라 resolver가 정직하게 미선정). `ambiguous_kebab_ids`(1:N 원시 링크)는
  다중 표시 정책 검토용 참고 목록.
- **게이트 우회 감시**: `kebab_invalid` > 0 — 정본 카탈로그 밖 kebab-id가 게이트를 통과했다는 신호
  (조사 대상).

## wrong-form (SymPy 거짓 항등식)

- **가치 변수**: `sympy_only_id_freq` — substring이 놓친(변수명·표기 변이) 오개념을 SymPy가 새로
  잡은 빈도. 노출 통합은 *substring과의 결합*(대체 아님)이므로 이 순기여가 결합의 이득이다.
- **결합 유지**: `substring_only_id_freq` — SymPy가 못 잡고 substring만 잡은 오개념. 결합 후에도
  substring 경로가 계속 커버해야 할 목록(대체 시 회귀 리스크).
- **주의**: shadow는 *비노출 측정*이라 SymPy의 거짓양성/음성은 사람이 표본을 검토해 판단한다
  (거짓 낙인 방지 가드가 있으나 canary 전 표본 검수 권장).

## semantic 매칭

- **가치 변수**: `semantic_only_id_freq` — substring이 놓친(의미 유사) 오개념을 의미 매처가 후보로
  올린 빈도(+recall). 단, +recall과 방향맹 FP가 섞이므로 유사도로 걸러 본다.
- **feed 임계**: `sim_ge_090`·`sim_ge_080`·`sim_ge_070`(누적) — "feed 임계 T를 잡으면 semantic-only
  몇 건이 남나". `on` 승격 시 combine 대상 후보를 거를 코사인 운영점 선정 근거(04b §4).
- **노출 플립**: `SEMANTIC_MODE=on`은 substring 아래에 semantic-only 후보를 *결합 노출*한다
  (substring 우선·재정렬 없음·비블로킹·실패 시 substring 폴백).

## judge 필터

- **가치 변수**: `remove_rate` — judge가 의미 후보 중 FP로 판정해 걸러낼 비율(정밀도 향상). 단
  과도하면 over-removal(recall 손실)이므로 `would_keep`와 함께 본다.
- **신뢰 변수**: `uncertain_rate` — 모호·폴백(형식 위반·seam 예외) 비율. 높으면 judge 라우팅·프롬프트
  재점검 신호(신뢰 리스크). judge는 `아니오`만 거르고 `예`·`불확실`은 유지(recall 보존·보수).
- **FP 원천**: `would_remove_id_freq` — judge가 주로 걸러낸 오개념 = 의미 매처 FP 주 원천 진단.
- **운영점 맥락**: `routings` — 관측에 섞인 judge 라우팅 프로파일(서로 다른 모델의 율 차이 해석용).

---

## 참고: 단계-비보존 shadow (선례·라벨 기반)

`step_shadow`는 coverage/분포가 아니라 *A/B 라벨링 워크시트*를 낸다:
`step_shadow_harvest`(관측→`human_label:null` draft) → 사람이 A/B 채움 → `step_shadow_eval`(precision
측정). 오개념 네 게이트의 harvest는 이 *관측→오프라인 집계* 정본 패턴을 공유하되 산출이 *coverage/
분포 요약*이라는 점만 다르다(라벨 불요 — 카탈로그 id 자체가 관측에 실림).

---

## WH-1 verify verdict 수확 (S1-11 flip 전제 ①)

> **목적**: WH-1 튜터링 하네스 shadow(`harness/wh1_shadow.py`)의 **verify verdict 분포**
> (correct/incorrect/unverifiable/None)를 실측·축적해 S1-11(verify 게이트 primary 승격) flip의
> 전제 ①을 채운다. 오개념 게이트들과 같은 *관측→오프라인 집계* 패턴이되, **누적 원장**(여러
> 측정 세션에 걸친 축적)이 추가된다.

| 항목 | 값 |
|---|---|
| 켜기(env) | `WHYMATH_WH1_HARNESS_SHADOW_ENABLED=true` (**서버 기동 전** 설정 — 프로세스 캐시) |
| record 로거 | `whymath.harness.wh1_shadow.record` |
| harvest 모듈 | `harness/wh1_shadow_harvest` (`--store` 누적 원장·중복 제거·재수확 멱등) |
| 드라이버 | `ops/wh1_shadow_probe` (합성 트래픽 — coach 세션/턴 제출) |
| 핵심 결정 변수 | `verdict_counts`/`verdict_ratios`·`turn_verdicts`(턴별 추이) — **판정선 없음**(분포 제시) |

### 발동 조건 (둘 다 필요)

1. **env**: 서버가 `WHYMATH_WH1_HARNESS_SHADOW_ENABLED=true`로 기동돼야 coach 세션/턴이
   하네스를 비차단 spawn한다(OFF 기본 — 학생 응답 비트동일·04a "측정 없는 도입 없음").
2. **solution_steps**: 요청에 `CoachRequest.solution_steps`(이미 분해된 표현식 리스트)가
   동봉돼야 하네스 verify 의무(§3.1)가 걸려 **verdict가 생성**된다. 미동봉 턴은
   `verify_verdict: null`(verify 미호출)로 관측된다 — 이것도 분포의 일부다(none 라벨).

### 수확 경로: 서버 로그 → harvest CLI → 누적 원장

record 로거의 관측 JSON은 **무영속**(서버 로그로만 흐름)이다. 그리고 **uvicorn 기본 로깅으로는
캡처되지 않는다** — uvicorn 기본 dictConfig는 자기 로거(uvicorn/uvicorn.error/uvicorn.access)만
구성하고 root를 안 건드려, 앱 INFO 라인은 `logging.lastResort`(WARNING 이상)에서 탈락한다
(2026-07-17 실측 — uvicorn 0.51 `LOGGING_CONFIG`·`run_demo.ps1`의 `.demo_uvicorn.err.log`에는
record 라인이 **안 남는다**). 따라서 uvicorn을 `--log-config scripts/demo/wh1_shadow_logconfig.json`
으로 기동한다 — uvicorn 기본 콘솔 로깅을 유지하면서 record 로거만 `FileHandler`로 분리 캡처해,
기동 cwd(`src\backend`) 기준 `wh1_shadow_records.log`에 **순수 JSONL**(포맷 `%(message)s`)이
쌓인다(dictConfig 로드·캡처는 2026-07-17 실측 검증).

```
coach 세션/턴(shadow ON·solution_steps 동봉)
  → record 로거 JSON → (--log-config) src\backend\wh1_shadow_records.log
  → python -m whymath_backend.harness.wh1_shadow_harvest wh1_shadow_records.log --store <원장.ndjson>
  → verdict 분포 리포트(원장 전체 기준·중복 제거 키 = dialogue_id·turn_index·observed_at)
```

harvest는 record 라인 파싱 성공(parsed)·비해당 라인(skipped)·깨진 JSON(broken)을 분리 회계하고,
`--store` 원장에 신규 관측만 append한다(같은 로그 재수확은 멱등 — appended 0). `--json`으로
리포트를 직렬화할 수 있다.

### 트래픽 만들기: 합성 드라이버 (`ops/wh1_shadow_probe`)

실기기 트래픽이 없을 때 대표 3모양을 재현 가능하게 제출한다 — 라운드당(기본 믹스 `eq:expr:bad=2:2:1`)
세션 5개, 세션마다 생성 1 + 멀티턴 2(전 턴 `solution_steps` 동봉·총 15제출/라운드):

- `eq` 방정식 변형 체인(`2x+3=7 → 2x=4 → x=2`) — **S3-02(2026-07-18·main 머지) 이후 해집합 보존
  동치로 판정돼 `correct` 결정 구간**이다(각 단계의 실수 해집합이 보존되므로). ★S3-02 *이전*엔
  등호 파싱 실패로 **unverifiable**-heavy였다(실사용 89% unverifiable의 근본원인) — 이 flip이 아래
  "## S3-02 라이브 재측정"의 핵심 관측 신호다(구판 로그·원장 라인은 옛 판정이라 재수확해도 불변).
- `expr` 표현식 동치(`(x+1)(x+2) → x^2+3x+2`) — SymPy 결정 구간(**correct**).
- `bad` 오전개 주입(`(x+1)(x+2) → x^2+4x+2`) — **incorrect** 검출용(스텝이 실제 틀린 수식임을
  테스트가 `verify_step` 실물로 동결).

`--token` 미지정 시 `POST /v1/auth/demo/callback`으로 JWT를 자동 발급한다(서버
`WHYMATH_DEMO_AUTH_ENABLED=true` 전제 — `run_demo.ps1`이 설정). 드라이버 출력은 **제출 회계뿐**
— verdict는 서버 로그가 진실이라 자체 집계하지 않는다.

★**합성 캐비엇(정직)**: 이 분포는 *합성 트래픽*의 분포다. 실 학생 트래픽 대표성 판정과 S1-11
flip go/no-go는 **Kiki(사람) 몫**이다 — 도구는 3-state가 각각 유도되는 모양만 보장한다.
하네스 정책(`LLMTutorPolicy`)은 Ollama 라이브면 LLM 거동을, 미가동이면 안전 강등 거동을
보이므로 `action_type`/`tool_calls` 분포는 LLM 모드에 따라 달라진다(verdict 유도 자체는
verify 의무가 하네스 강제라 성립).

### Kiki 실행 절차 (Phaiakes9)

창 ① — 데모 스택 기동 후, uvicorn만 record-캡처 구성으로 교체(**같은 창에서** — `run_demo.ps1`이
남긴 env(`WHYMATH_DATABASE_URL`·`WHYMATH_JWT_SECRET_KEY`·`WHYMATH_DEMO_AUTH_ENABLED`)를 수동
uvicorn이 상속해야 한다):

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9 — 이 PC 자체, SSH 불요) — 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
# 미머지 브랜치의 신규 파일(wh1_shadow_probe/harvest·logconfig) 필요.
# ★checkout -B 형태 필수 — 이 브랜치는 재시작(force-push)될 수 있어 pull은 add/add 충돌을 낸다
#   (2026-07-17 실측: HARN-06 yaml 충돌). 로컬 잔여 커밋은 전부 main에 기머지분이라 버려도 안전.
git fetch origin claude/coding-duplication-conflicts-p41iau
git checkout -B claude/coding-duplication-conflicts-p41iau origin/claude/coding-duplication-conflicts-p41iau

.\scripts\demo\run_demo.ps1   # DB·시드·데모 인증 준비(uvicorn도 뜨지만 record 캡처 불가)

# 데모 uvicorn 종료(DB는 유지) — ★pid 파일만 믿지 말 것: 이전 세션의 좀비 uvicorn이 8000을
# 점유하면 run_demo의 새 서버는 바인드 실패로 즉사하고 /health는 좀비가 응답해 성공처럼 보인다
# (2026-07-17 실측 — pid 5792 부재·프로브는 shadow OFF 좀비에 제출돼 기록 0). 포트 기준으로 정리:
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }

# shadow ON + record 캡처 uvicorn 재기동 (logconfig는 ASCII 전용 — uvicorn이 로케일 인코딩
# (한국어 Windows=cp949)으로 읽으므로 비ASCII가 있으면 기동 실패, 2026-07-17 실측·수정)
$env:WHYMATH_WH1_HARNESS_SHADOW_ENABLED = "true"
cd src\backend
.\.venv\Scripts\uvicorn.exe whymath_backend.app:create_app --factory --host 0.0.0.0 --port 8000 --log-config ..\..\scripts\demo\wh1_shadow_logconfig.json
# (이 창은 서버가 점유 — record는 src\backend\wh1_shadow_records.log에 쌓인다)
```

> ★**서버 창(창 ①) 조작 금지** — 측정이 끝날 때까지 이 창에 아무것도 입력하지 않는다.
> 특히 **Ctrl+C는 복사가 아니라 서버 중단 신호**다(2026-07-17 실측: 창 ②용 명령을 창 ①에
> 잘못 붙여넣고 Ctrl+C로 프롬프트를 되찾는 순간 서버가 우아하게 종료 → 프로브 전부
> ConnectError). 출력 복사가 필요하면 마우스 드래그 선택 후 **우클릭**(또는 Enter)으로
> 복사한다. 서버 종료는 측정이 끝난 뒤 의도적으로만(Ctrl+C).

창 ② — 합성 트래픽 제출 + 수확·축적:

```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9 — 이 PC 자체, SSH 불요) — 창 ②
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend

# ★캡처 사전 검증 — 창 ①의 서버가 진짜 캡처 uvicorn인지(좀비 아님) 확인.
#   logconfig가 delay 없이 파일을 *기동 즉시* 생성하므로 True여야 정상(2026-07-17 수정 —
#   구판 delay:true는 첫 기록 전까지 False라 사전 검증으로 무효였음).
#   False면 진행 중단하고 창 ① 절차(포트 정리 포함)를 다시 밟는다.
Test-Path wh1_shadow_records.log
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -TimeoutSec 3   # 서버 생존 확인

# 페이싱 기본 2.5초/쓰기(coach 쓰기 rate limit 30/분 대응 — 무간격 제출은 429, 2026-07-17 실측).
# 라운드 3 = 45쓰기 ≈ 2분 소요가 정상이다.
.\.venv\Scripts\python.exe -m whymath_backend.ops.wh1_shadow_probe --base-url http://127.0.0.1:8000 --rounds 3

# 하네스 shadow는 비차단(fire-and-forget) — 마지막 제출 후 잠시 대기 뒤 수확
Start-Sleep -Seconds 15
.\.venv\Scripts\python.exe -m whymath_backend.harness.wh1_shadow_harvest wh1_shadow_records.log --store ..\..\wh1_shadow_ledger.ndjson --json ..\..\wh1_shadow_report.json
```

측정 세션을 거듭할수록 `wh1_shadow_ledger.ndjson`(리포 루트)에 관측이 축적되고, harvest
리포트는 항상 **원장 전체** 기준 분포를 낸다(재수확 멱등 — 같은 로그를 두 번 넣어도 안 불어남).
정리: 창 ①에서 `Ctrl+C`로 uvicorn 종료 후 `cd C:\Users\kiki\Desktop\__AI\WhyMath` →
`.\scripts\demo\stop_demo.ps1`(throwaway DB까지 볼륨째 제거 — 시연 DB 데이터는 소멸하지만
**원장은 파일이라 남는다**).

### 판정 (분포 → go/no-go)

- **결정 변수**: `verdict_counts`/`verdict_ratios`(4-라벨·none=verify 미호출)·
  `turn_verdicts`(턴별 추이)·`status_counts`(budget_exhausted 비율 = 루프 예산 건강도).
- **판정선 없음**: harvest는 cutoff를 내지 않는다 — S1-11 flip은 이 분포를 근거로 사람/별도
  게이트가 결정한다(임의 숫자 단정 금지 — CLAUDE.md "모르면 모른다고"). 합성 분포만으로
  flip하지 말 것(위 합성 캐비엇).

## S3-02 라이브 재측정 (트리거 ③ = S1-11 전제①)

> **목적**: S3-02(입력-검증 계약 확장 — 등호 방정식 *해집합 보존* 판정, main 머지)가 실제로
> unverifiable을 줄이는지 라이브로 확인한다. **2026-07-17 실사용 shadow(n=9)의 unverifiable
> 89% 베이스라인** 대비 하락을 관측 → 그대로 **S1-11 flip 전제①(verdict 분포)**을 채우고 전제ⓑ
> (verify 게이트 승격 재판정)의 before/after 근거가 된다. **모집·동의(S3-01)와 무관 — 지금 실행
> 가능한 Kiki 행동**이다.

**⚠️ 브랜치는 main**: 위 창① 절차의 `claude/coding-duplication-conflicts-p41iau` checkout은 **머지
전 잔재**다. shadow 도구(probe·harvest·logconfig)와 **S3-02 verify가 전부 main에 머지**됐으니
재측정은 **main**에서 한다 — 옛 피처 브랜치는 S3-02 이전일 수 있어 eq가 여전히 unverifiable로
나오는 *거짓 음성* 위험. 창①의 브랜치 checkout을 아래로 대체하고, 이후(run_demo·포트정리·shadow
ON uvicorn 재기동·창②)는 위 절차 그대로:
```powershell
# 실행 시스템: Windows PowerShell (Phaiakes9 — 이 PC 자체) — 창① 첫 부분 (main 사용)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B main origin/main
```

**핵심 관측 신호 (S3-02 delta)**: harvest `verdict_ratios`에서
- `eq`(등호 방정식 체인) verdict가 **unverifiable → correct**로 뒤집히면 S3-02가 shadow 경로에서
  작동함이 실증된다.
- 종합: **unverifiable 비율이 2026-07-17 실사용 89% 대비 하락**.

**두 트래픽 모드**:
1. **합성 sanity(빠름·수분)** — 창②의 `wh1_shadow_probe`를 그대로. 기대: `eq` 세션이 이제
   correct로 수확(예전 unverifiable 아님). S3-02가 shadow에 반영됨을 즉시 확인.
2. **실사용 재측정(정본·실기기)** — 89%는 *실사용* 수치였으니 정본 확인은 실기기에서 **등호 방정식
   풀이를 한 줄 한 단계로 입력**. ★단계 분해 전제: 입력이 줄 단위로 분해돼 인접 등식쌍이 돼야
   S3-02가 판정한다(한 덩어리 자유텍스트면 여전히 미결) — 실기기 입력이 단계로 분해되는지 함께
   관찰(안 되면 입력 UX가 다음 과제).

**비교·판정**:
- 재수확 후 `wh1_shadow_report.json`의 `verdict_ratios`(특히 unverifiable)를 2026-07-17
  n=9(unverifiable 8/9=89%)와 비교.
- **판정선은 사람** — harvest는 cutoff를 안 낸다. 하락 폭·실트래픽 대표성으로 Kiki가 S1-11 flip
  ⓑ 재판정(임의 숫자 단정 금지).
- 원장은 축적되므로 S3-02 전/후 라인이 섞이면 구간을 분리해 before/after 비교(구판 라인은 옛
  판정). **2026-09-22부터 손으로 나누지 않는다** — 수확기에 `--since`/`--until`(ISO 8601·양끝
  포함)이 있고, 구간을 주면 리포트가 "구간 밖 제외 N건"을 함께 찍는다(원장 파일은 무필터로
  전부 축적된다·S3-51). 구간을 안 주면 리포트가 "[집계 구간] 미지정"이라고 말한다.
- 같은 리포트의 **[판정 모집단]** 절은 `none`(verify 미호출 대화 턴)을 뺀 분모 기준 3-state
  비율이다 — 사전등록 판정문의 분모가 그쪽이므로, 위 4-라벨 비율을 그대로 읽으면 오판한다.
- **[전이 형태]** 절은 S3-02 해집합 경로가 실제로 작동한 횟수(Σ등호 방정식 전이)와 혼합 형태
  잔여를 낸다 — "알고리즘을 붙였으면 작동한 비율을 말한다"(CLAUDE.md)의 이 경로 이행분이다.

**6항목 요약**: ①과제=S3-02 라이브 재측정 ②목적=89% 하락 실증 → S1-11 전제①/ⓑ ③절차=위 창①(main)
/창② + 실기기 단계입력 ④성공=eq가 correct·unverifiable 비율 하락 / 실패=eq 여전히 unverifiable
(→브랜치가 S3-02 이전인지·단계 분해 여부 확인) ⑤환경=Phaiakes9 PowerShell·서버+DB ⑥창=창①서버
(조작 금지·Ctrl+C=중단) / 창②명령(별도).

> **자유사용 대표측정(트리거 ③ 잔여분)은 별도 런북이다** — 위 절차는 *대본·합성* 확인이고,
> 2026-07-28 사전등록된 대표측정(대본 금지·15~30분)은
> `docs/ops/s3_02_free_use_remeasurement_runbook.md`가 소유한다(게이트
> `G-s302-free-use-remeasure`).

### 실측 결과 (2026-07-19 — 완료) + 절차 함정 3종

**결과(MEMORY 2026-07-19 이정표 정본)**: 합성 60제출 — eq 24/24 **correct**(S3-02 전엔 전량
unverifiable)·expr 24/24 correct·bad 12/12 incorrect·오검출 0. 실기기(M2007J20CG·원장
`wh1_shadow_ledger_realdevice.ndjson`) — 묶음 3줄 정답 체인 **correct**(실기기 최초 결정 판정)·
묶음 오답 체인 **incorrect**·한줄씩 채팅 입력 unverifiable(89% 현상 재현)·외톨이 한 줄
unverifiable(전이 0·정직 정상). **3-state 실기기 종단 실증 — 잔여 변수는 백엔드가 아니라 입력
UX(묶음 제출 유도·S3-05).**

**절차 함정(실측 등재 — 재발 방지)**:
1. **한줄씩 제출 ≠ 검증 가능** — 검증은 *인접 두 단계의 전이*를 본다. 채팅 습관대로 한 메시지에
   한 줄씩 보내면 매 턴이 외톨이 단계(전이 0)라 전부 unverifiable이 *정상*이다. 실기기 측정은
   반드시 **여러 단계를 한 메시지에 줄바꿈으로 묶어**(풀이 모드·Enter=줄바꿈·전송은 버튼) 제출한다.
2. **`Rename-Item` 새 이름은 이름만** — 경로를 포함하면 "지정된 대상이 경로…" 오류(2026-07-19
   실측·지시문 실수). 옛 캡처 로그 보관은 `Rename-Item src\backend\wh1_shadow_records.log
   wh1_shadow_records_archive_<날짜>.log` 형태로. 보관 실패 시 Test-Path 사전검증이 무변별이 되고
   신규 원장이 옛 라인으로 오염된다(오염 시 원장 삭제 후 재수확).
3. **다중행 블록 붙여넣기의 마지막 줄은 Enter 미실행일 수 있다** — 창①의 uvicorn 명령이 프롬프트에
   입력만 된 채 대기하면 서버가 안 떠 있다(2026-07-19 실측 — 창② /health 연결 거부가 검출).
   블록 실행 후 `INFO: Uvicorn running`이 *보이는지* 눈으로 확인한다.
