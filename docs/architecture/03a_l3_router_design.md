# L3a. 라우터 설계서 — 입력 분류기 + fast/mid/quality 분기 로직

> `docs/architecture/03_content_generation.md`(L3 캐논)의 **상세 하위 설계서**.
> 03 문서 §1 "모델 라우터"·"모델 풀" 표를 *데이터 기반 분기 로직*으로 구체화한다.
> 근거 데이터: `MEMORY.md` 2026-05-19 결정 로그(qwen2-math:1.5b GPU 측정, fast/mid/quality 3단계 라인업 확정) + 2026-05-16 로그(7b·27b GPU baseline).
>
> **범위**: *설계* 트랙. 입력 분류기·분기 결정 로직·에스컬레이션 체인·스키마 *명세*까지. 실제 구현(`.py`)·테스트는 후속 마일스톤 **M1.2**.

---

## 0. 이 설계서가 해소하는 것 — 라우팅 축의 명칭 충돌 + 태스크 패밀리 축

L3 라우팅에는 **서로 다른 세 축**이 있다. (1·2축은 본래 분리, 3축은 2026-05-20 Phaiakes9 실측이 추가로 요구.) 기존 문서는 1·2축을 한 단어(`mid`)로 겹쳐 써 모순 위험이 있었고, 3축(태스크 패밀리)은 아예 없었다.

| | 축1 — **비용·위치 축** (에스컬레이션) | 축2 — **로컬 모델 크기 축** | 축3 — **로컬 모델 패밀리 축**(신규) |
|---|---|---|---|
| 질문 | "클라우드로 *올라갈* 것인가?" | "로컬에서 *어느 크기* 모델인가?" | "로컬에서 *어느 패밀리*(수학 vs 일반) 모델인가?" |
| 값 | `LOCAL` / `CLOUD_MID` / `CLOUD_HIGH` | `FAST` / `MID` / `QUALITY` | `MATH`(qwen2-math) / `GENERAL`(qwen2.5) |
| 비용 | 0원 / ~$0.003·0.015 / ~$0.015·0.075 | 전부 0원 (Phaiakes9 로컬) | 전부 0원 (Phaiakes9 로컬) |
| 출처 | 03 문서·llm-architect.md 기존 `LLMTier` | 2026-05-19 벤치 라인업 | **2026-05-20 태스크 인지 실측**(아래 §0.2) |
| 목표 분포 | **80 / 18 / 2** (유지) | LOCAL(80%) *내부* 세분 | LOCAL(80%) *내부* — 태스크 유형이 결정(분포 무관) |

**핵심 1 (축1·2 충돌)**: 2026-05-19 확정된 `fast/mid/quality`는 *전부 로컬 Qwen 모델*이다. 이는 기존 `LLMTier.LOCAL/MID/HIGH`(비용·위치 축)와 **다른 축** — `LOCAL` 티어 *내부의* 모델 크기 세부 분기다. 두 축에 `mid`가 동시에 존재하여 충돌한다(클라우드 MID = Claude Sonnet vs 로컬 mid = 7b).

**핵심 2 (축3 신규 — 패밀리)**: 2026-05-20 Phaiakes9 실측(GPU `127.0.0.1`, temperature=0)이 드러낸 바, 로컬 라우팅은 *크기(축2)만*으로 부족하다 — **태스크 유형(수학 계산 vs NLP)에 따라 모델 *패밀리*를 먼저 갈라야 한다.** NLP 호출지점(추출·정규화·매칭)을 수학 특화 모델(`qwen2-math`)로 돌리면 **7b조차 0%**였다. 즉 축2의 `FAST`(1.5b)/`MID`(7b)는 *어느 패밀리 안에서의* 크기인지가 먼저 정해져야 의미가 있다. 따라서 **로컬 모델 ID = (패밀리 축3) × (크기 축2)** 의 조합으로 결정된다. (상세 §0.2·§A.0.)

### 0.1 명칭 충돌 해소 규칙 (이 문서 전체·후속 코드에 적용)

1. **`mid`를 *단독으로* 쓰지 않는다.** 항상 축을 접두사로 한정한다.
   - 축1: `CLOUD_MID` (클라우드 중급, Claude Sonnet 계열)
   - 축2: 로컬 7b는 `LocalModelTier.MID` 또는 산문에서 `로컬 mid(7b)`로 표기
2. **축1 enum을 `CLOUD_` 접두사로 명시한다.** 기존 `LLMTier.MID/HIGH` → `CostTier.CLOUD_MID/CLOUD_HIGH`로 개명. `LOCAL`은 유지.
   - 이유: `MID`라는 맨이름이 두 축 어디에도 단독으로 속하지 않게 만들어, 코드·문서·Langfuse 태그에서 *어느 축인지 항상 자명*하게 한다.
3. **라우팅 결정은 항상 (축1, 축2) 쌍으로 표현한다.** 축2(`local_model`)는 축1이 `LOCAL`일 때만 의미를 가진다. 축1이 `CLOUD_*`이면 `local_model = None`.
   - 표기 관례: `LOCAL/FAST`, `LOCAL/MID`, `LOCAL/QUALITY`, `CLOUD_MID`, `CLOUD_HIGH`.

> **호환성 메모**: 03 문서·llm-architect.md의 기존 `LLMTier`(LOCAL/MID/HIGH)는 *축1만* 표현하던 단일 enum이었다. 본 설계는 이를 (a) 축1 `CostTier`(LOCAL/CLOUD_MID/CLOUD_HIGH)와 (b) 축2 `LocalModelTier`(FAST/MID/QUALITY)로 **분해**한다. 기존 `LLMTier.MID`→`CostTier.CLOUD_MID`, `LLMTier.HIGH`→`CostTier.CLOUD_HIGH`로 1:1 대응되므로 기존 라우팅 규칙은 의미 보존되며, *로컬 내부 세분*만 신규 추가된다. (llm-architect.md 정의 갱신은 별도 검토 — 본 설계서가 근거.)

### 0.2 태스크 패밀리 축(축3) 도입 규칙 — 2026-05-20 실측 근거

로컬 라우팅은 *크기(축2)*에 앞서 **태스크 패밀리(축3)** 를 결정해야 한다. 이는 명칭 충돌이 아니라 *새로운 차원*의 추가다.

1. **로컬 모델 ID = 패밀리(축3) × 크기(축2).** 축2의 `FAST`/`MID`는 *추상 크기 등급*이고, 그것이 가리키는 *실제 모델*은 패밀리가 정한다.
   - `MATH` × `FAST` = `qwen2-math:1.5b` / `MATH` × `MID` = `qwen2-math:7b`
   - `GENERAL` × `FAST` = `qwen2.5:3b` / `GENERAL` × `MID` = `qwen2.5:7b`
   - `QUALITY`는 패밀리 무관 상위 티어 = `qwen3.5:27b`(강한 검증·복잡추론, 비동기). 27b는 일반·수학 양쪽을 포괄하므로 축3을 적용하지 않는다.
2. **패밀리는 태스크 유형이 결정한다(크기·SLA가 아니라).**
   - **수학 계열**(계산·풀이·증명) → `MATH`. `qwen2-math`는 수식 추론·산술에 강하다(실측 산술 7b 100%).
   - **NLP 계열**(추출·정규화·매칭·분류·메타) → `GENERAL`. `qwen2.5`는 정보처리·형식변환에 적합하다(실측 match 3b 100%).
3. **`MATH` enum 명칭은 단독으로 쓰지 않는다.** 항상 "패밀리 `MATH`" / "`ModelFamily.MATH`"로 한정한다 — 축1의 `CLOUD_*`, 축2의 `MID`와 충돌하지 않도록(맨이름 `MATH`가 *난이도*나 *과목명*으로 오독되지 않게).
4. **클라우드(축1=CLOUD_*)에는 축3을 적용하지 않는다.** Claude/GPT 등 클라우드 모델은 범용이라 패밀리 구분이 없다. 축3은 *축1=LOCAL일 때만* 의미를 가진다(축2와 동일 조건).

> **왜 실측이 이 축을 강제했나**: 2026-05-20 1차 하니스는 *모든* 로컬 호출지점을 `qwen2-math`로 평가했고, NLP 호출지점(extract/translate/match)에서 7b조차 거의 0%가 나왔다. 원인 재해석 결과 "1.5b vs 7b 크기" 문제가 아니라 **모델 패밀리가 태스크와 안 맞은 것**임이 확정됐다(`MEMORY.md` 2026-05-20 "재설계(A)" 로그). 하니스를 태스크 인지로 재설계해 NLP=`qwen2.5`로 바꾸자 match 3b=100%·translate 7b=75%로 정상화됐다. 따라서 *설계*도 패밀리 축을 1급 차원으로 승격한다.

---

## A. 라우팅 축의 통합 — 모델 풀 + 합성 흐름

### A.0 로컬 모델 풀 — 패밀리(축3) × 크기(축2) 매트릭스

로컬(축1=LOCAL)에서 *실제로 호출되는 모델*은 **패밀리 × 크기**의 조합이다. 축2의 `FAST`/`MID`는 추상 크기 등급일 뿐, 그것이 가리키는 실제 모델은 패밀리가 정한다(§0.2).

| 크기(축2) ＼ 패밀리(축3) | **MATH** (수학 계산·풀이·증명) | **GENERAL** (NLP: 추출·정규화·매칭·분류·메타) |
|---|---|---|
| **FAST** | `qwen2-math:1.5b` | `qwen2.5:3b` |
| **MID** | `qwen2-math:7b` | `qwen2.5:7b` |
| **QUALITY** | `qwen3.5:27b` (패밀리 무관 상위 티어 — 강한 검증·복잡추론, **비동기 전용**) | ← 동일(27b가 양 패밀리 포괄) |

- **패밀리 선택 기준**: 태스크 *유형*(수학 vs NLP)이 정한다 — 크기·SLA가 아니라(§0.2 규칙2, §C.0).
- **2026-05-20 태스크 인지 실측이 검증한 적합도**(GPU `127.0.0.1`, temperature=0):
  - `GENERAL` match `qwen2.5:3b` = **100%**, translate `qwen2.5:7b` = **75%**(3b 50%) — NLP에 일반 모델이 적합.
  - `MATH` 산술 `qwen2-math:1.5b` = **87.5%**, `qwen2-math:7b` = **100%** — 수학에 수학 모델이 적합.
  - **반증(패밀리 미스매치)**: NLP 호출지점을 `qwen2-math`로 돌리면 **7b조차 0%**. → 크기를 올려도 패밀리가 틀리면 무의미.
  - extract는 `set_f1`(개념 집합 F1) 지표로 여전히 0% — 그러나 이는 *모델 약점이 아니라 측정 한계*(의미≠문자열, §H 후속8). 보수적으로 GENERAL/MID 기본(§B.2).

### A.1 그라운딩 데이터 — 크기(축2) 지연·SLA (2026-05-19 벤치, Phaiakes9 / Windows Ollama 0.24.0 + DirectML / Radeon 8060S Strix Halo)

> 아래 지연 수치는 *크기 등급별* 대표값이다(2026-05-19 벤치는 `qwen2-math` 라인업으로 측정). 같은 크기 등급의 `GENERAL`(qwen2.5:3b/7b) 지연은 동급으로 가정하되, 실측 보정은 §H 후속(패밀리별 지연 재측정)으로 남긴다.

| 크기 티어(축2) | 대표 모델(MATH) | 디스크 | p50(c=1) | tok/s(c=1) | tok/s(c=4) | SLA 게이트 p50<2s | 동기 가능? |
|---|---|---|---|---|---|---|---|
| **FAST** | qwen2-math:1.5b | 934MB | **1,010ms** | 124.25 | 142.91 (+15%) | ✅ **PASS** | 예 (즉답) |
| **MID** | qwen2-math:7b | 4.4GB | 3,918ms | 32.63 | 33.81 (+4%) | ❌ FAIL (허용범위) | 예 (즉답엔 길다) |
| **QUALITY** | qwen3.5:27b | 17GB | 13,886ms | 9.22 | 9.28 (~0%) | ❌ FAIL (동기 불가) | **아니오 (비동기 전용)** |

핵심 함의 (결정 로그에서):
- **FAST만 SLA 게이트 통과** → *동기 대화 즉답*의 기본 경로. c=4에서 throughput이 +15% 증가(병렬 작동) → *피크 트래픽 흡수*까지 단일 GPU로 가능.
- **MID p50≈4초**: 동기 호출은 가능하나 *즉답엔 길다*. 정밀 풀이·2~3단계 추론·메인 학생 대화용. c=4에서 p50 15초로 폭발 → 동시성 제한 필요.
- **QUALITY(27b) p50≈14초 + 병렬 미작동**(GPU 100% 단일 점유) → **동기 불가. 백그라운드/비동기 큐 전용.**

### A.2 합성 흐름 (한 요청이 세 축을 통과하는 순서)

```
              ┌─────────────────────── 입력 분류기 (B장) ───────────────────────┐
요청(RoutingRequest+) ─▶ │ 신호 수집: task_type·difficulty·requires_reasoning·       │
                         │           sync·conversation_phase·subscription·budget   │
                         └───────────────────────────────┬───────────────────────┘
                                                          ▼
                            ┌──────────── 축1 결정: 클라우드로 올라가나? ────────────┐
                            │ killer/prove ─────────────────────────▶ CLOUD_HIGH (2%)│
                            │ 어려운 추론 & premium↑ ────────────────▶ CLOUD_MID  (18%)│
                            │ 그 외 ─────────────────────────────────▶ LOCAL    (80%)│
                            └───────────────────────────────┬───────────────────────┘
                                              LOCAL일 때만   ▼
                            ┌──────────── 축3 결정: 로컬 어느 패밀리? (C.0) ──────────┐
                            │ NLP(extract/translate/match/classify/meta) ─▶ GENERAL  │
                            │ 수학(계산/풀이/증명·산술) ──────────────────▶ MATH     │
                            └───────────────────────────────┬───────────────────────┘
                                              패밀리 결정 후 ▼
                            ┌──────────── 축2 결정: 로컬 어느 크기? (C장) ───────────┐
                            │ 동기 즉답·분류·1단계 산술 ──────────────▶ FAST          │
                            │ 정밀 풀이·2~3단계 추론·메인 대화 ───────▶ MID           │
                            │ 검증·복잡 추론·PRM·백그라운드(비동기) ──▶ QUALITY (27b) │
                            └───────────────────────────────┬───────────────────────┘
                                            (패밀리×크기 합성) ▼
                                  실제 모델 = A.0 매트릭스 lookup
                                  (예: GENERAL×FAST=qwen2.5:3b, MATH×MID=qwen2-math:7b)
                                                             ▼
                                              RoutingDecision (G장 스키마)
                                  {cost_tier, local_family, local_model, mode, reason,
                                   est_latency_ms, est_cost_krw}
```

- **80%는 LOCAL로 떨어진 뒤, 먼저 패밀리(축3)로, 다시 크기(축2)로 갈라진다.** 축2·축3 모두 축1의 LOCAL 가지 *안에서만* 작동한다.
- **패밀리(축3)를 크기(축2)보다 먼저** 정한다 — 같은 "FAST"라도 패밀리가 다르면 다른 모델(qwen2.5:3b vs qwen2-math:1.5b)이기 때문(§0.2 규칙1).
- `QUALITY`로 결정되면 패밀리는 무시된다(27b가 양 패밀리 포괄, §A.0). 즉 `local_family`는 *FAST/MID일 때만* 모델 선택에 영향.
- **18%는 CLOUD_MID**(Claude Sonnet 4.6), **2%는 CLOUD_HIGH**(Claude Opus 4.7) — 03 문서 모델 풀·목표 분포 그대로.
- CLOUD 경로에서는 `local_model = local_family = None`. 축2·축3은 평가하지 않는다.

---

## B. 입력 분류기 (Input Classifier)

라우팅 *결정*에 앞서, 요청의 신호를 수집·정규화하는 단계. 분류기 자체는 *규칙 기반*(휴리스틱)이며, 일부 신호(특히 `difficulty`·`requires_reasoning`)는 **FAST 티어 LLM 호출지점 ①/②**(개념 추출·깊이 추론)로 추정될 수 있다 — 이 경우 분류기가 라우터를 *재귀적으로* 1회 경유(FAST 고정)한다. (CLAUDE.md "LLM 호출은 항상 라우터 경유" 준수.)

### B.1 입력 신호

| 신호 | 출처 | 라우팅에서의 역할 |
|---|---|---|
| `task_type` | 호출자(L4/L5) | 'explain','diagnose','coach','generate','verify','prove','extract','match','translate','classify','self_verify' — **축3(패밀리) 결정의 1차 신호**(수학 vs NLP, §C.0) + 축2 영향 |
| `difficulty` | 문항 메타 또는 ①/② 추정 | 'easy','medium','hard','killer' — 축1·축2 동시 영향 |
| `requires_reasoning` | 호출자 또는 ② 추정 | 다단계 추론 필요 여부 — MID/QUALITY·CLOUD 승급 신호 |
| `sync`(신규) | 호출자 | True=동기 즉답 요구, False=비동기 허용 — **QUALITY 게이팅의 핵심** |
| `conversation_phase`(신규) | L4 대화 상태 | 'greeting','probing','hint','solution_reveal','followup' — 즉답성 판단 |
| `max_latency_ms` | 호출자 | SLA 한도. <2000이면 사실상 FAST 강제 |
| `student_subscription` | 세션 | 'free','basic','premium','gifted' — CLOUD 승급 가드 |
| `budget_krw`(개명) | 쿼터 매니저 | 이 호출 잔여 예산(원). 0이면 CLOUD 차단 → LOCAL 강등 |
| `call_site`(신규) | 호출자 | 5개 핵심 호출지점 식별자 ①~⑤ (없으면 일반 호출) — **축3 패밀리 결정의 강신호**(①③④=NLP→GENERAL, ②=수학→MATH, §C.0) |
| `data_licenses`(신규·EOS-59) | 호출자 | 이 호출의 프롬프트에 실리는 **자료의 라이선스 목록**. 축1의 *법적* 게이트 입력 — 반출 불가/미확인 자료가 있으면 CLOUD 차단(§D.5). 미지정 기본값 `UNKNOWN` = fail-closed |

> 명명: 기존 `RoutingRequest.budget_cents`는 *원(KRW)* 단위 일일 한도(03 문서·llm-architect.md)와 불일치했다. 본 설계는 `budget_krw`로 통일한다(E장).

### B.2 5개 핵심 호출지점별 기본 로컬 패밀리×티어 매핑 (2026-05-20 실측 반영)

03 문서 "LLM 핵심 호출지점" 5개 각각의 *기본(default) 축3 패밀리 + 축2 티어*. 분기 로직(C장)이 신호에 따라 이 기본값을 승급/강등할 수 있다. **2026-05-20 Phaiakes9 태스크 인지 실측**(GPU `127.0.0.1`, temperature=0)으로 패밀리·티어를 검증·확정했다.

| # | 호출지점 | 기본 축1 | 기본 축3(패밀리) | 기본 축2(크기) | 실제 모델 | 동기성 | 실측 근거(2026-05-20) |
|---|---|---|---|---|---|---|---|
| ① | **개념 추출** | LOCAL | **GENERAL** | **MID** | `qwen2.5:7b` | sync | NLP 작업(수학모델 0%). `set_f1`이 *의미≠문자열*이라 측정상 0% → 보수적 MID 기본; **티어는 지표 보정 후 확정**(§H 후속8) |
| ② | **깊이 추론** | LOCAL | **MATH** | **MID** (hard↑면 QUALITY/CLOUD) | `qwen2-math:7b`(→27b/CLOUD) | sync→async | 위계·선수개념 의존성은 수학 추론. 다단계라 FAST 부족. 03 문서 "난이도 높으면 MID/HIGH" |
| ③ | **번역·정규화** | LOCAL | **GENERAL** | **MID** | `qwen2.5:7b` | sync | NLP 작업. 3b 50%(<하한 60%), **7b 75%** → MID 필요. 반복성 높음(캐싱) |
| ④ | **개념 ID 매칭** | LOCAL | **GENERAL** | **FAST** | `qwen2.5:3b` | sync | NLP 작업. **3b 100%** → FAST로 충분. 반복성 높음. 매칭 실패→사람 검수(C.4) |
| ⑤ | **자기검증** | LOCAL | (무관) | **QUALITY** | `qwen3.5:27b` | **async** | 환각 방어 ③. *생성 모델과 분리된* 더 강한 모델로 교차검증. 27b 비동기. 추가 비용→샘플링(F장) |
| (산술) | **계산·산술** | LOCAL | **MATH** | **MID** | `qwen2-math:7b` | sync | 일반 호출(call_site 없음). **7b 100% vs 1.5b 87.5%** — 정확도 우선 MID 기본(차이 12.5%p > DELTA, §H 후속10) |

핵심 변화 (2026-05-20 실측이 뒤집은 기존 가정):
- **①③④는 이제 `GENERAL`(qwen2.5) 패밀리**다. 기존 설계는 패밀리 구분이 없어 암묵적으로 수학 모델을 가정했으나, 실측에서 NLP를 수학 모델로 돌리면 7b조차 0%였다 → 패밀리를 일반으로 교정.
- **④(개념 ID 매칭)만 FAST(3b=100%)**, **①③은 MID로 상향**. 매칭은 후보 중 코드 선택이라 3b로 충분하나, 추출·정규화는 3b가 하한 미달(translate 3b 50%)이라 7b 필요.
- **②·산술은 `MATH`(qwen2-math) 유지** — 수학 추론·계산에 수학 모델이 적합(산술 7b 100%).
- **①의 MID는 *잠정***: extract 0%는 `set_f1` 측정 한계(의미≠문자열)이지 모델 약점이 아니다. 지표 보정(동의어/임베딩/LLM-judge, §H 후속8) 후 FAST로 낮출 여지가 있다 — 보수적으로 MID에서 출발.
- **⑤(자기검증)는 패밀리 무관 QUALITY**: 27b가 양 패밀리를 포괄하고 동기 불가이므로 비동기 큐. 비용 통제 위해 *샘플링*(F장).
- **①③④는 여전히 캐싱 적중률 기여가 크다**(반복성 높음) — 패밀리가 바뀌어도 캐싱 전략은 동일(F.1).

---

## C. 분기 결정 로직 (Decision Table + 의사코드)

**평가 순서 = 축1(C.1) → [LOCAL이면] 축3(C.0) → 축2(C.2).** 축1이 CLOUD_*면 축3·축2는 건너뛴다(`local_family = local_model = None`). 축1=LOCAL이면 **패밀리(축3)를 크기(축2)보다 먼저** 정한다 — 같은 크기 등급이라도 패밀리가 가리키는 실제 모델이 다르기 때문(§0.2 규칙1, §A.0).

### C.0 축3 결정표 (LOCAL일 때만 — MATH / GENERAL) — 2026-05-20 실측 근거

축1=LOCAL로 확정된 요청만 평가. 태스크 *유형*(수학 vs NLP)으로 패밀리를 가른다(크기·SLA가 아니라). 평가 순서 = 위에서 아래, 첫 매치에서 확정. `QUALITY`로 갈 요청도 패밀리를 정해두지만, 최종적으로 축2가 QUALITY면 패밀리는 무시된다(27b가 양 패밀리 포괄, §A.0).

| 우선 | 조건 | 축3 결정 | 근거(2026-05-20 실측) |
|---|---|---|---|
| 1 | `call_site in {① extract, ③ translate, ④ match}` | **GENERAL** | NLP 호출지점. 일반 모델 적합(match 3b 100%·translate 7b 75%). 수학모델은 7b조차 0% |
| 2 | `call_site == ② depth` | **MATH** | 깊이·선수개념 의존성은 수학 추론 |
| 3 | `task_type in {extract, match, translate, classify}` | **GENERAL** | NLP 계열(추출·매칭·정규화·분류) — 정보처리/형식변환 |
| 4 | `task_type in {generate, explain, coach, diagnose, verify, prove}` | **MATH** | 수학 풀이·설명·코칭·진단·검증·증명은 수학 추론 |
| 5 | 그 외 (일반 산술·미상) | **MATH** | 안전 기본값 — WhyMath 호출 다수가 수학 계산. 산술은 수학 모델이 적합(7b 100%) |

> **왜 MATH가 기본값인가**: WhyMath는 수학 학습 앱이라 *대부분의 로컬 호출이 수학 추론·계산*이다. NLP 계열(추출·정규화·매칭·분류)은 명시적 신호(`call_site`·`task_type`)로 식별될 때만 GENERAL로 보낸다. 즉 **"NLP임이 분명할 때 GENERAL, 그 외 MATH"** 가 안전하다(수학 작업을 일반 모델로 보내는 것보다, NLP를 놓쳐 수학 모델로 보내는 위험이 크므로 — 후자는 7b조차 0%였다. 따라서 NLP 식별 규칙을 *넓게* 잡는다).

### C.1 축1 결정표 (LOCAL / CLOUD_MID / CLOUD_HIGH)

평가 순서 = 위에서 아래. 첫 매치에서 확정. (03 문서·llm-architect.md `Router.route()` 규칙을 *비용축으로* 보존·확장.)

| 우선 | 조건 | 축1 결정 | 근거 |
|---|---|---|---|
| 1 | `budget_krw <= 0` (쿼터 소진) | **LOCAL** | 비용 0원 강제. CLOUD 차단(E장) |
| 2 | `student_subscription == 'free'` | **LOCAL** | 무료 사용자 항상 로컬(기존 규칙1) |
| 3 | `difficulty == 'killer'` or `task_type == 'prove'` | **CLOUD_HIGH** | 킬러·증명(기존 규칙2). 단 쿼터·구독 가드 통과 시 |
| 4 | `requires_reasoning` and `subscription in {premium,gifted}` | **CLOUD_MID** | 어려운 진단(기존 규칙3) |
| 5 | (에스컬레이션 트리거 — D장) 로컬 결과 신뢰 미달 | **CLOUD_MID**→**CLOUD_HIGH** | 폴백 체인(D장) |
| 6 | 그 외 | **LOCAL** | 기본(기존 규칙4). 목표 분포 80% |

> **결정표 뒤에 법적 게이트가 한 번 더 걸린다 (EOS-59)** — 위 6규칙은 *비즈니스 축*(구독·예산)이며 그 결과는 **희망 티어**다. 최종 축1은 `guard_data_export(희망, data_licenses)`를 통과한 값이다(§D.5). 두 축을 한 함수에 합치지 않는 이유도 그곳에 적었다.

### C.2 축2 결정표 (LOCAL일 때만 — FAST / MID / QUALITY)

축1=LOCAL로 확정 + 축3(C.0) 패밀리 결정 후 평가. 평가 순서 = 위에서 아래. **축3 결과를 입력으로 받는다** — 일부 규칙은 패밀리별 실측 정확도에 따라 크기를 다르게 정한다(특히 GENERAL 호출지점은 3b/7b 적합도가 호출지점마다 다름, §B.2).

| 우선 | 조건 | 축2 결정 | 모드 | 근거(SLA·실측) |
|---|---|---|---|---|
| 1 | `call_site == ⑤(자기검증)` | **QUALITY** | async | 검증은 강한 모델·비동기(패밀리 무관) |
| 2 | `sync == False` and (`task_type in {verify,generate}` or `difficulty in {hard,killer}`) | **QUALITY** | async | 27b 동기 불가 → 비동기 큐 전용 |
| 3 | `call_site == ④(match)` | **FAST** | sync | GENERAL match는 **3b=100%** → FAST로 충분(2026-05-20) |
| 4 | `call_site in {① extract, ③ translate}` | **MID** | sync | GENERAL이나 **3b 하한 미달**(translate 3b 50%<60%) → 7b 필요. ①은 지표 보정 후 FAST 강등 여지(§H 후속8) |
| 5 | `sync == True` and `max_latency_ms < 2000` | **FAST** | sync | FAST만 SLA 게이트 통과(p50 1초) |
| 6 | `conversation_phase in {greeting,followup}` or `task_type in {match,classify}` or (`difficulty=='easy'` and not `requires_reasoning`) | **FAST** | sync | 즉답·분류·경량 매칭(3b 충분) |
| 7 | `task_type in {explain,coach,diagnose}` and `requires_reasoning` | **MID** | sync | 정밀 풀이·2~3단계 추론·메인 학생 대화(p50 4초 허용) |
| 8 | `difficulty in {medium,hard}` and `sync == True` | **MID** | sync | 동기인데 추론 필요 → 7b(즉답보단 길지만 허용범위) |
| 9 | 그 외 | **FAST** | sync | 안전 기본값(가장 빠르고 SLA 충족) |

> **SLA 근거 요약**: *동기 즉답 = FAST*(유일하게 p50<2s) / *정밀 풀이·메인 대화 = MID*(p50≈4초, 허용) / *검증·복잡추론·백그라운드 = QUALITY*(p50≈14초, 비동기 강제). 이 3분기는 결정 로그가 명시한 "비용·품질·지연의 파레토 최적".
>
> **패밀리×크기 정합 메모**: 규칙 3·4는 *GENERAL 호출지점 안에서도* 크기가 갈림을 명시한다 — `match`는 3b로 충분(FAST), `extract`/`translate`는 7b 필요(MID). 이는 2026-05-20 실측(match 3b 100% vs translate 3b 50%)이 직접 강제한 분기다. 기존 표(구 규칙4)는 `extract/match/translate`를 *한 덩어리로 FAST* 처리했으나, 실측이 이를 갈랐다.

### C.3 핵심 분기 규칙 (산문 요약)

0. **패밀리 먼저(축3): NLP면 GENERAL, 수학이면 MATH.** 크기(축2)는 그 다음. 같은 "FAST"라도 GENERAL은 qwen2.5:3b, MATH는 qwen2-math:1.5b다(§0.2). NLP를 수학 모델로 보내면 7b조차 0%(2026-05-20).
1. **동기 + 빠른 SLA(<2초) → 무조건 FAST.** 27b·7b는 p50가 게이트를 넘으므로 동기 즉답 자리에 올 수 없다.
2. **비동기 + 검증/생성/고난도 → QUALITY.** 27b는 동기 불가이므로 *비동기 큐로만* 호출된다(D.3). QUALITY면 패밀리 무시(27b가 양 패밀리 포괄).
3. **동기인데 추론이 필요 → MID.** 즉답은 아니지만(p50 4초) 정밀 풀이·메인 대화가 허용하는 범위.
4. **GENERAL 호출지점도 크기가 갈린다**: `match`는 FAST(3b 100%), `extract`/`translate`는 MID(3b 하한 미달). 캐싱 적중률은 ①③④ 모두 크다.
5. **자기검증(⑤)은 항상 QUALITY/비동기 + 샘플링.**

### C.4 의사코드

```python
# 의사코드 — 실제 구현은 M1.2. 세 축을 순차 평가한다: 축1 → [LOCAL이면] 축3 → 축2.
def route(req: RoutingRequest) -> RoutingDecision:
    # ── 축1: 비용·위치 (LOCAL / CLOUD_MID / CLOUD_HIGH) ──
    if req.budget_krw <= 0:                      # 쿼터 소진 → 비용 0원 강제
        cost = CostTier.LOCAL
    elif req.student_subscription == "free":     # 무료는 항상 로컬
        cost = CostTier.LOCAL
    elif req.difficulty == "killer" or req.task_type == "prove":
        cost = guard_cloud(req, CostTier.CLOUD_HIGH)   # 가드 미통과 시 LOCAL 강등
    elif req.requires_reasoning and req.student_subscription in ("premium", "gifted"):
        cost = guard_cloud(req, CostTier.CLOUD_MID)
    else:
        cost = CostTier.LOCAL

    # CLOUD 경로면 축2·축3 없음
    if cost != CostTier.LOCAL:
        return RoutingDecision(cost_tier=cost, local_family=None, local_model=None,
                               mode="sync", reason="cloud escalation",
                               est_latency_ms=cloud_latency(cost),
                               est_cost_krw=cloud_cost(req, cost))

    # ── 축3: 로컬 패밀리 (MATH / GENERAL) — 크기보다 먼저 (C.0) ──
    # NLP임이 분명할 때 GENERAL, 그 외 MATH (수학 앱이라 MATH가 안전 기본값, C.0).
    NLP_CALL_SITES = (CallSite.CONCEPT_EXTRACT, CallSite.TRANSLATE, CallSite.CONCEPT_MATCH)
    NLP_TASK_TYPES = ("extract", "match", "translate", "classify")
    if req.call_site in NLP_CALL_SITES or req.task_type in NLP_TASK_TYPES:
        family = ModelFamily.GENERAL          # 추출·정규화·매칭·분류 = NLP → qwen2.5
    else:
        family = ModelFamily.MATH             # 계산·풀이·증명·산술·미상 = 수학 → qwen2-math

    # ── 축2: 로컬 모델 크기 (FAST / MID / QUALITY) — 축3 결과를 입력으로 ──
    if req.call_site == CallSite.SELF_VERIFY:                # ⑤ 자기검증
        local, mode = LocalModelTier.QUALITY, "async"
    elif (not req.sync) and (req.task_type in ("verify", "generate")
                             or req.difficulty in ("hard", "killer")):
        local, mode = LocalModelTier.QUALITY, "async"        # 27b 비동기 전용
    elif req.call_site == CallSite.CONCEPT_MATCH:
        local, mode = LocalModelTier.FAST, "sync"            # ④ GENERAL match: 3b=100%
    elif req.call_site in (CallSite.CONCEPT_EXTRACT, CallSite.TRANSLATE):
        local, mode = LocalModelTier.MID, "sync"             # ①③ GENERAL: 3b 하한 미달 → 7b
    elif req.sync and req.max_latency_ms < 2000:
        local, mode = LocalModelTier.FAST, "sync"            # FAST만 SLA 통과
    elif (req.conversation_phase in ("greeting", "followup")
          or req.task_type in ("match", "classify")
          or (req.difficulty == "easy" and not req.requires_reasoning)):
        local, mode = LocalModelTier.FAST, "sync"            # 즉답·경량 매칭(3b 충분)
    elif req.task_type in ("explain", "coach", "diagnose") and req.requires_reasoning:
        local, mode = LocalModelTier.MID, "sync"             # 정밀 풀이·메인 대화
    elif req.difficulty in ("medium", "hard") and req.sync:
        local, mode = LocalModelTier.MID, "sync"
    else:
        local, mode = LocalModelTier.FAST, "sync"            # 안전 기본값

    # QUALITY면 패밀리 무시 (27b가 양 패밀리 포괄, A.0) — 기록상 family는 그대로 둔다.
    return RoutingDecision(cost_tier=CostTier.LOCAL, local_family=family,
                           local_model=local, mode=mode,
                           reason=f"local/{family.value}/{local.value}",
                           est_latency_ms=local_latency(local),  # FAST≈1010, MID≈3918, QUALITY≈13886
                           est_cost_krw=0.0)

# 실제 모델 ID 해석(A.0 매트릭스 lookup) — 호출 직전 LLMClient가 수행.
LOCAL_MODEL_MATRIX = {
    (ModelFamily.MATH,    LocalModelTier.FAST): "qwen2-math:1.5b",
    (ModelFamily.MATH,    LocalModelTier.MID):  "qwen2-math:7b",
    (ModelFamily.GENERAL, LocalModelTier.FAST): "qwen2.5:3b",
    (ModelFamily.GENERAL, LocalModelTier.MID):  "qwen2.5:7b",
    # QUALITY는 패밀리 무관 — (any, QUALITY) → "qwen3.5:27b"
}
```

> 환각 방어와의 관계: `route()`는 *어디서 생성할지*만 정한다. 생성된 응답은 03 문서 "환각 방어 통합 파이프라인"(스키마→SymPy/Lean→PRM→자기검증→사람검수)을 *반드시* 통과해야 학생에게 노출된다. 라우팅은 그 파이프라인을 *대체하지 않는다*. (CLAUDE.md 절대 금기 "LLM 응답을 검증 없이 학생에게 제공 금지".)

---

## D. 에스컬레이션·폴백 체인

### D.1 단방향 승급 사슬 (패밀리 안에서 크기를 올린다)

```
패밀리 내 크기 승급:
  [MATH]    qwen2-math:1.5b ─▶ qwen2-math:7b ─┐
  [GENERAL] qwen2.5:3b      ─▶ qwen2.5:7b     ─┼─▶ QUALITY qwen3.5:27b ─▶ CLOUD_MID ─▶ CLOUD_HIGH
                          (FAST)        (MID)  │     (패밀리 합류)         (Sonnet)      (Opus)
   로컬 (비용 0원) ─────────────────────────────┘     로컬 천장 ────────┘  클라우드(구독·예산 가드 필수)
```

- **승급은 *같은 패밀리 안에서* FAST→MID 먼저.** GENERAL 호출의 FAST(3b)가 미달이면 GENERAL MID(7b)로 올리지, 갑자기 MATH로 패밀리를 바꾸지 않는다(태스크 유형은 불변).
- **QUALITY(27b)는 두 패밀리의 합류점.** 패밀리 MID(7b)에서도 미달이면 패밀리 무관하게 27b로 올린다(27b가 양쪽 포괄, §A.0).
- QUALITY(로컬 천장)에서도 미달일 때만 CLOUD로 넘어간다(비용 0원 우선). CLOUD 승급은 항상 구독·예산 가드(D.4) 통과 필수.

- 로컬 3단계 안에서 먼저 올린다(비용 0원). 로컬 천장(QUALITY)에서도 미달일 때만 CLOUD로 넘어간다.
- CLOUD로의 승급은 **항상 구독·예산 가드**(`guard_cloud`)를 통과해야 한다. 미통과 시 *승급하지 않고* LOCAL 최선(QUALITY) 결과 + 신뢰도 경고로 마감하거나, 신뢰 미달이 심하면 **안전 응답 패턴**(03 문서 `SAFE_FALLBACK`)으로 답을 *미룬다*(CLAUDE.md 답 미루기 원칙과 정합).

### D.2 에스컬레이션 트리거

| 트리거 | 발동 시 승급 | 비고 |
|---|---|---|
| 자기 일관성 불일치(N회 다수결 미수렴) | 다음 티어 1단계 | 환각 방어 4번 |
| 신뢰도 낮음(PRM·verdict confidence < 임계) | 다음 티어 1단계 | 환각 방어 2번 |
| 타임아웃(티어 p50·p99 초과) | 동일 티어 재시도 1회 → 실패 시 *강등 후 비동기*(FAST 동기 실패 시 MID 비동기) | SLA 보호 |
| `difficulty=='killer'` / `task_type=='prove'` | 즉시 CLOUD_HIGH(축1 규칙3) | 로컬 단계 건너뜀 |
| 도구 검증 실패(SymPy/Lean 불일치) | 재생성(동일 티어·동일 패밀리) → 반복 실패 시 사람 검수 큐 | 환각 방어 ②/3번 |
| 개념 ID 매칭 실패(④) | **GENERAL 안에서** FAST(3b)→MID(7b) 1회 → 실패 시 사람 검수 큐 | 03 문서 "매칭 실패 시 사람 검수". 패밀리는 GENERAL 유지(NLP 작업) |

### D.3 QUALITY 비동기 큐 경로 (명시)

QUALITY(27b)는 **동기 호출 불가**(p50≈14초, 병렬 미작동). 따라서:

- QUALITY로 라우팅된 모든 요청은 **작업 큐**(비동기 워커)로 들어간다. 호출자에게는 즉시 `job_id` 반환 → 완료 시 콜백/폴링.
- **동기 맥락에서 QUALITY가 필요해진 경우**(예: 동기 대화 중 자기 일관성 붕괴 → 검증 필요): 학생에게는 FAST/MID로 *잠정 응답 + "정밀 검증 중"* 표시를 주고, QUALITY 검증은 백그라운드에서 수행 → 결과가 잠정 응답과 다르면 정정 푸시.
- QUALITY 워커 동시성은 **1**로 제한한다(GPU 100% 단일 점유, 병렬 시 throughput 무이득·p50 폭발). 큐 깊이가 임계 초과 시 ⑤ 자기검증 *샘플링 비율을 낮춰* 부하 조절(F장).

### D.4 구독·예산 가드 (`guard_cloud`)

```python
def guard_cloud(req, desired: CostTier) -> CostTier:
    # 클라우드 승급 전 가드. 미통과 시 LOCAL로 강등.
    if req.student_subscription == "free":
        return CostTier.LOCAL                       # 무료는 클라우드 금지
    if req.budget_krw < cloud_min_cost(desired):    # 잔여 예산 부족
        return CostTier.LOCAL                       # 강등(+ 신뢰도 경고)
    if desired == CostTier.CLOUD_HIGH and req.student_subscription == "basic":
        return CostTier.CLOUD_MID                   # basic은 HIGH 불가 → MID로 제한
    return desired
```

### D.5 데이터 등급 가드 (`guard_data_export`) — 법적 축, EOS-59

`guard_cloud`(§D.4)와 **합치지 않는다**. §D.4는 구독·예산 = *비즈니스 규칙*(프로모션·요금제
개편으로 언제든 완화 가능)이고, 여기는 데이터 제공자 이용조건 = *법적 규칙*(완화하려면
권리자와의 **별도합의**가 필요)이다. 한 함수에 합치면 "무료 사용자에게도 클라우드를 열자"는
비즈니스 결정이 법적 게이트까지 조용히 여는 경로가 생긴다. 저장소 선례: `l6/_shared.py`의
`is_exposable`(저작권 축)과 `is_review_cleared`(검수 축)도 같은 이유로 분리돼 있다.

**무엇이 국외 반출인가**: `CLOUD_MID`/`CLOUD_HIGH`가 가리키는 프로바이더(Anthropic 등)는
**국외 법인**이므로, 클라우드 티어로 프롬프트를 보내는 것은 그 프롬프트에 실린 자료의
*국외 이전*이다. `docs/data/licensing_safety.md` §133 AIHub 4조건 ②(국외반출·국외법인
별도합의)에 따라 AIHub 유래 자료를 별도합의 없이 클라우드로 보내면 라이선스 위반이며,
이는 CLAUDE.md 의사결정 우선순위 **#2(법적)** 사안으로 **#6(비용·효율)을 이긴다**.

**권리 판정의 정본은 라우터가 아니다**: "AIHub는 반출 불가"는 이미
`l1/rights/permission_map.py`의 `_AIHUB_OPEN`에 `export=False`로 선언돼 있다. 라우터는 그
선언을 *읽기만* 한다 — 등급 어휘를 새로 만들면 권리 기준이 두 벌이 되기 때문에
`LicenseType` × `PermissionAction.EXPORT`를 그대로 쓴다.

```python
def guard_data_export(desired: CostTier, licenses) -> CostTier:
    # 법적 가드. **강등만** 한다 — 어떤 입력으로도 티어가 올라가지 않는다(단방향성).
    if desired not in {CostTier.CLOUD_MID, CostTier.CLOUD_HIGH}:
        return desired                  # 국내(로컬) — 판정할 반출이 없다
    if export_judgment(licenses).blocks_offshore:   # export=False 또는 None(미확인)
        return CostTier.LOCAL           # 반출 불가/미확인 → 국내 강등
    return desired
```

병합은 보수적이다(§policy_engine 동형): 하나라도 `export=False`면 금지, 그 외에 `None`이
있으면 미확인 → **fail-closed로 차단**. 미지정(`UNKNOWN`)이 곧 차단이므로, 그 보수 기본값이
*일상 동작*이 되지 않도록 **소스 스캔 게이트**(`scripts/ops/check_routing_data_grade.py`,
CI `backend` 잡)가 프로덕션 호출부의 등급 명시를 강제한다. 호출부가 쓰는 등급 프로파일의
단일 좌석은 `l3/data_grade_defaults.py`다(코퍼스 구성이 바뀌면 그 한 곳만 고친다).

그 게이트는 **입력**만 본다. 집행 지점은 `Router.route` 하나이므로 `RoutingDecision`을 손으로
조립해 provider에 넘기면 판정을 지나지 않는다 — 그 우회는 **결정 스캔 게이트**
(`scripts/ops/check_routing_decision_bypass.py`, 같은 CI 잡 · EOS-77)가 막는다: 클라우드 티어
리터럴 직접 생성은 위반, 비리터럴 티어는 라우터 결정의 `data_export_reason` *승계*(표현식)가
있어야 통과, 유예는 `경로::함수=만료일`로만 허용하고 만료·unmatched를 exit 1로 강제한다.
2026-09-05 기준 프로덕션 유예 0건(유일한 우회였던 `ops/live_preflight`를 라우터 경유로 전환).

**불변식 5**(`RoutingDecision`): `data_export_blocked=True ⟹ cost_tier == LOCAL`.
막힌 결정이 클라우드로 나가 있으면 모순이므로 스키마가 구성 자체를 거부한다.

---

## E. 비용·예산·SLA 연동

### E.1 로컬의 "한도"는 *비용*이 아니라 *리소스*

로컬(FAST/MID/QUALITY)은 토큰당 0원이다(Phaiakes9). 따라서 일일 한도(원)는 **로컬 호출에는 직접 적용되지 않는다.** 로컬의 진짜 제약은:

- **GPU 리소스**: 특히 QUALITY(27b)는 단일 GPU 100% 점유 → *동시성 1*. MID(7b)는 c=4에서 p50 폭발 → 동시성 제한.
- **호출 횟수·큐 깊이**: 남용 방지·피크 흡수는 *rate limit*과 *큐 깊이*로 관리(예산이 아님).

### E.2 일일 한도(원)와 LOCAL/CLOUD 분기 관계

| 구독 | 일일 한도(원) | 의미 |
|---|---|---|
| free | 100 | 사실상 LOCAL 전용(축1 규칙2가 항상 LOCAL). 한도는 *클라우드 우발 호출 차단선* |
| basic | 500 | CLOUD_MID 소량 가능, CLOUD_HIGH 불가(D.4) |
| premium | 2,000 | CLOUD_MID 일상 + CLOUD_HIGH 제한적 |
| gifted | 5,000 | CLOUD_HIGH 포함 폭넓게 |

- **한도는 *클라우드 호출에만* 차감된다.** 로컬 호출은 0원이므로 한도를 소모하지 않는다 → `budget_krw`는 *클라우드 잔여 예산*으로 해석.
- `budget_krw <= 0`이면 축1 규칙1이 **LOCAL 강제**. 즉 예산 소진 = "오늘은 로컬만". 학생 경험은 *느려질 수 있어도 끊기지 않는다*(웰빙 우선, CLAUDE.md 의사결정 우선순위 1 > 6).

### E.3 목표 분포 80/18/2 모니터링 + SLA 게이트

- **목표 분포(축1)**: LOCAL 80% / CLOUD_MID 18% / CLOUD_HIGH 2%. Langfuse `cost_tier` 태그 집계로 *실측 분포*를 추적(F장). 80% 미달 시 라우팅 규칙·임계값 재조정 신호.
- **로컬 내부 분포(축2 크기·축3 패밀리)**는 별도 관찰. 크기는 FAST가 다수여야 SLA·throughput 유리. 패밀리는 *NLP=GENERAL 라우팅이 실제로 작동하는지*(GENERAL 비율이 NLP 호출 비율과 정합하는지) 감시 — `local_family` 태그 집계. 명시적 목표치는 *미설정*(라우터 가동 후 실측으로 정함, H장).
- **SLA 게이트 p50 < 2초는 FAST만 충족.** 따라서 *동기 즉답 경로의 SLA*는 "FAST로 라우팅된 비율 × FAST p50"로 평가한다. MID/QUALITY는 SLA 게이트 대상이 아니라 *각자의 허용 지연*(MID≈4초 동기, QUALITY 비동기)으로 평가.

---

## F. 캐싱·Langfuse 연동

### F.1 캐시 키에 축1·축3·축2 포함

기존 `ResponseCache._cache_key(prompt, system, model)`(llm-architect.md)의 `model`을 **`{cost_tier}:{local_family}:{local_model}`** 합성 식별자로 확장한다. 같은 프롬프트라도 *어느 티어·패밀리가 생성했는지*가 캐시 정체성의 일부다 — FAST 응답과 QUALITY 응답을, 그리고 **MATH(qwen2-math) 응답과 GENERAL(qwen2.5) 응답을** 섞지 않는다(패밀리가 다르면 출력 특성·신뢰도가 다르므로).

```python
# 예시 — 캐시 키에 세 축을 포함
def _cache_key(prompt, system, cost_tier, local_family, local_model):
    model_id = f"{cost_tier}:{local_family or '-'}:{local_model or '-'}"
    # 예: "LOCAL:GENERAL:FAST"(qwen2.5:3b), "LOCAL:MATH:MID"(qwen2-math:7b), "CLOUD_MID:-:-"
    content = f"{system}|||{prompt}|||{model_id}"
    return f"llm:cache:{sha256(content)}"
```

- **①③④(개념 추출·번역정규화·개념 ID 매칭)는 캐시 적중률 기여가 가장 크다**(반복성 높음). 동일 교과서 텍스트·동일 개념 표현은 재호출 없이 캐시 반환. 캐싱 KPI(30%→50%)의 주력.
- **⑤(자기검증)는 *샘플링*** — 신뢰도 높은 LOCAL 생성물은 일부만 자기검증(추가 비용·QUALITY 큐 부하 절감). 샘플링 비율은 D.3 큐 깊이에 따라 동적 조절.
- 캐시 적중 시에도 Langfuse에 *cache_hit=true*로 기록(분포·KPI 왜곡 방지).

### F.2 Langfuse 기록 필드 확장

기존 추적(llm-architect.md)에 다음을 추가한다.

| 필드 | 값 | 용도 |
|---|---|---|
| `cost_tier` | LOCAL/CLOUD_MID/CLOUD_HIGH | 80/18/2 분포 모니터링 |
| `local_family`(신규) | MATH/GENERAL 또는 null | 패밀리별 분포·품질 추적(NLP=GENERAL 라우팅이 실제로 작동하는지) |
| `local_model` | FAST/MID/QUALITY 또는 null | 로컬 내부 크기 분포·티어별 품질 추적 |
| `mode` | sync/async | SLA 평가 분리(동기만 게이트 대상) |
| `latency_ms` | 실측 | 티어별 p50/p90/p99 — 벤치 회귀 감시 |
| `cost_krw` | 실측(로컬=0) | 학생당 월 비용 KPI |
| `call_site` | ①~⑤ 또는 null | 호출지점별 분포·캐싱 효과 |
| `cache_hit` | bool | 캐싱 적중률 KPI |
| `escalated_from` | 직전 티어(폴백 시) | 에스컬레이션 빈도 분석 |
| `student_id_hash` | 해시 | 직접 ID 금지(기존 규칙 유지) |
| `data_export_blocked`(신규·EOS-59) | bool | 데이터 등급 게이트가 *실제로* 클라우드를 막은 건수 — "작동한 비율"의 분자 |
| `data_export_reason`(신규·EOS-59) | EXPORT_ALLOWED/PROHIBITED/UNVERIFIED 또는 null | 등급 판정 분포·발동률 분모. null=미판정(라우터 미경유)이며 '허용'이 아니다 |

---

## G. 스키마 확장 (예시 — 실제 코드는 M1.2)

> 아래는 *설계 예시*다. 실제 `.py` 파일은 후속 구현에서 작성한다. 기존 `RoutingRequest`(llm-architect.md §라우팅 규칙)를 확장하고, 축을 분리한 신규 enum·결정 객체를 추가한다.

```python
from enum import Enum
from pydantic import BaseModel, Field

# ── 축1: 비용·위치 (기존 LLMTier.MID/HIGH → CLOUD_ 접두사로 개명) ──
class CostTier(str, Enum):
    LOCAL = "local"            # Phaiakes9 로컬 (0원) — 축3·축2로 세분
    CLOUD_MID = "cloud_mid"    # Claude Sonnet 4.6 등 (구 LLMTier.MID)
    CLOUD_HIGH = "cloud_high"  # Claude Opus 4.7 / GPT-5 등 (구 LLMTier.HIGH)

# ── 축3: 로컬 모델 패밀리 (2026-05-20 태스크 인지 실측 라인업) ──
class ModelFamily(str, Enum):
    MATH = "math"        # qwen2-math — 수학 계산·풀이·증명 (산술 7b 100%)
    GENERAL = "general"  # qwen2.5    — NLP: 추출·정규화·매칭·분류 (match 3b 100%)

# ── 축2: 로컬 모델 크기 (2026-05-19 벤치 라인업, 패밀리 무관 추상 등급) ──
# 실제 모델은 (패밀리 축3 × 크기 축2)로 결정 — A.0 매트릭스 lookup.
class LocalModelTier(str, Enum):
    FAST = "fast"        # MATH=qwen2-math:1.5b / GENERAL=qwen2.5:3b — p50≈1.0s, SLA PASS, 동기 즉답
    MID = "mid"          # MATH=qwen2-math:7b  / GENERAL=qwen2.5:7b — p50≈3.9s, 동기 가능(즉답엔 길다)
    QUALITY = "quality"  # qwen3.5:27b (패밀리 무관)                 — p50≈13.9s, 비동기 전용

class CallSite(str, Enum):       # 5개 핵심 호출지점
    CONCEPT_EXTRACT = "extract"  # ① (GENERAL)
    DEPTH_REASON = "depth"       # ② (MATH)
    TRANSLATE = "translate"      # ③ (GENERAL)
    CONCEPT_MATCH = "match"      # ④ (GENERAL)
    SELF_VERIFY = "self_verify"  # ⑤ (QUALITY, 패밀리 무관)

# ── 입력: 기존 RoutingRequest 확장 ──
class RoutingRequest(BaseModel):
    task_type: str                       # explain/diagnose/coach/generate/verify/prove/extract/match/translate/classify/self_verify
    difficulty: str                      # easy/medium/hard/killer
    requires_reasoning: bool
    student_subscription: str            # free/basic/premium/gifted
    max_latency_ms: int = 30000
    budget_krw: float = 0.0              # (개명) 클라우드 잔여 예산(원). 0이면 LOCAL 강제
    # ── 신규 신호 ──
    sync: bool = True                    # True=동기 즉답 요구, False=비동기 허용
    conversation_phase: str | None = None  # greeting/probing/hint/solution_reveal/followup
    call_site: CallSite | None = None    # 5개 핵심 호출지점 식별(없으면 일반 호출). 축3 패밀리 강신호

# ── 출력: 세 축을 합성한 결정 객체 (신규) ──
class RoutingDecision(BaseModel):
    cost_tier: CostTier                  # 축1
    local_family: ModelFamily | None     # 축3 (cost_tier=LOCAL일 때만, 아니면 None)
    local_model: LocalModelTier | None   # 축2 (cost_tier=LOCAL일 때만, 아니면 None)
    mode: str = "sync"                   # sync/async (QUALITY는 async 강제)
    reason: str                          # 결정 근거(디버깅·Langfuse) 예: "local/general/fast"
    est_latency_ms: int                  # 예상 지연(FAST≈1010/MID≈3918/QUALITY≈13886/CLOUD≈가변)
    est_cost_krw: float = 0.0           # 예상 비용(로컬=0)
```

> **불변식(invariant)**:
> - `cost_tier == LOCAL ⟺ local_model is not None` (그리고 `⟺ local_family is not None`).
> - `cost_tier in {CLOUD_MID, CLOUD_HIGH} ⟺ local_model is None == local_family is None` (클라우드엔 축2·축3 없음).
> - `local_model == QUALITY ⟹ mode == "async"`.
> - `local_family`는 *FAST/MID일 때 모델 선택에 영향*하고, `QUALITY`면 기록상 보존되나 모델 lookup에는 쓰이지 않는다(27b가 양 패밀리 포괄, §A.0).
> - 구현 시 검증(validator)으로 강제한다.

---

## H. 미해결·후속

> 항목 8~11은 **2026-05-20 Phaiakes9 태스크 인지 실측**(GPU `127.0.0.1`, temperature=0)이 새로 식별한 후속이다 — 패밀리 축(축3) 도입의 잔여 과제.

| # | 항목 | 내용 | 시점 |
|---|---|---|---|
| 1 | **FAST tier 품질 검증 (패밀리 인지)** | 패밀리별로 FAST가 MID 대비 *품질 차이*가 충분히 작은지 측정. **2026-05-20 1차 실측 완료**: GENERAL match 3b=100%(FAST 확정)·translate 3b 50%/7b 75%(MID 확정)·MATH 산술 1.5b 87.5%/7b 100%(경계, 항목10). extract는 측정 한계(항목8). 잔여: 지표 보정 후 ①의 FAST 강등 재검토. MEMORY.md 2026-05-20 로그. | M1.2 (라우터 구현 시) |
| 2 | **로컬 내부 분포 목표치 (크기·패밀리)** | 축2(크기) + 축3(패밀리) 목표 비율 *미설정*. 라우터 가동 후 실측으로 정함(크기는 FAST 다수 유리, 패밀리는 NLP=GENERAL 라우팅 정합 감시). | 라우터 가동 후 |
| 3 | **mid/quality 지연 개선** | ROCm 7.2+ Linux native(옵션 F)로 7b·27b 2-5x 개선 시 *축2 결정표 임계값 재조정* 여지(MID 동기 즉답 편입 가능성, QUALITY 동기화 가능성). MEMORY.md 2026-05-19 후속 3번. | 옵션 F 완료 후 |
| 4 | **클라우드 티어 실제 연동** | CLOUD_MID(Sonnet)·CLOUD_HIGH(Opus) 실제 API 연동·비용 계측·`guard_cloud` 실측 임계값 보정. 현재는 *경로·가드 설계*만. **구조 개선(코드)**: est(사전 추정) 비용 `CLOUD_MIN_COST_KRW`가 더는 하드코딩 매직넘버가 아니라 *실측 단가표*(`CLOUD_TOKEN_PRICE_USD_PER_1M`, actual과 동일 근거)와 가정 토큰 상수(`_EST_ASSUMED_INPUT/OUTPUT_TOKENS`=1K+1K 보수적 기본)의 *단일 공식*으로 유도된다(≈27.72/46.2, est/actual 분리 유지 #465). **수치 튜닝은 라이브 대기**: 라이브 트래픽 축적 후 Langfuse `l3_routing` 실측 `input/output_tokens` p50를 가정 토큰 상수에 대입하면 `CLOUD_MIN_COST_KRW`가 자동 재계산된다 — 아직 실측 데이터가 비대표 1건뿐이라 *수치는 미보정*(구조만 개선). | Phase 1 후반 |
| 5 | **`difficulty`·`requires_reasoning` 추정 경로** | 분류기가 ①/②로 이 신호를 추정할 때의 *재귀 라우팅* 비용·정확도. 호출자가 직접 제공 vs LLM 추정의 트레이드오프. (추정 호출 자체도 패밀리 분기: 개념 추출=GENERAL, 깊이 추론=MATH.) | M1.2 |
| 6 | **QUALITY 큐 SLA** | 비동기 큐의 *완료 시간 SLA*(동시성 1 가정 시 큐 대기 포함)·우선순위(자기검증 vs 백그라운드 생성) 정책 미정. | M1.2~Phase 2 |
| 7 | **llm-architect.md `LLMTier` 정의 갱신 + 패밀리 축 반영** | 본 설계의 `CostTier`/`LocalModelTier` 분해는 반영 완료(2026-05-20). **신규**: 축3 `ModelFamily`(MATH/GENERAL) 추가·`RoutingDecision.local_family` 필드를 llm-architect.md·03 문서에 *최소* 반영(GENERAL 패밀리 모델 풀 추가 + 본 설계서 cross-ref). 본 설계서가 근거. | 본 갱신과 함께(03·llm-architect 모델 풀) / 코드는 항목11 |
| 8 | **extract `set_f1` 측정 한계 — gold 동의어/임베딩/LLM-judge 필요** | extract가 GENERAL에서도 0%인 것은 *의미≠문자열* 때문이다 — 모델이 합리적 개념을 대도(예: '곱셈공식' vs '곱셈 공식', '근의 공식' vs '근과 계수의 관계') gold와 문자열이 어긋나 `set_f1`이 0이 된다. 채점기를 (a)gold 동의어 집합, (b)개념 임베딩 코사인 매칭, (c)LLM-as-judge 중 하나로 보강해야 ①의 *진짜* 품질을 측정·티어 확정 가능. 현재 ①은 보수적 MID 잠정(§B.2). | M1.2~Phase 2 |
| 9 | **match 파서 — 장황한 모델의 주제명 echo 처리** | GENERAL match에서 *장황한 모델(7b)*이 후보의 *주제명*(예: '10수학01 (다항식)'의 '다항식')을 답에 그대로 echo해, 코드만 비교하는 채점·운영 파서가 오판할 수 있다. match 파서가 `<ANSWER>`에서 *코드(10수학NN)만* 견고히 추출하도록 강화해야(주제명·괄호 strip). 3b가 100%인 것은 답이 짧아서이기도 하므로, 7b 폴백 시 특히 중요. | M1.2 |
| 10 | **MATH 산술 — MID 확정(정확도 우선)** | ✅**결정(2026-05-20)**: 산술 FAST(1.5b)=87.5% vs MID(7b)=100%. 차이 12.5%p > DELTA(7%p). 87.5%는 ABS_MIN(60%) 위라 속도(p50 1초)만 보면 FAST도 후보였으나, *수학 앱은 정확도 우선*(CLAUDE.md 의사결정 #4 학습효과 > #5 UX·속도)이라 ~8문제 중 1개 오답인 FAST는 부적합 → **MID 확정**(DELTA=0.07 유지 = 정확도 우선 정책). 속도 손실은 *캐싱*으로 흡수. *향후 최적화 여지(보류)*: 난이도별 분기(쉬운 산술=FAST, 복합=MID) — 추가 실측 후. 운영은 temperature=0(변동 제거). | 결정 완료 |
| 11 | **`src/backend/whymath_backend/l3` 라우터 코드가 패밀리 축 반영** | M1.2에서 구현된 라우터(`RoutingDecision`·결정 로직)는 *2축*만 안다. 본 설계의 **축3 `ModelFamily` + C.0 패밀리 결정 + A.0 매트릭스 lookup + `local_family` 필드/캐시 키/Langfuse 태그**를 코드·테스트에 반영해야 한다(별도 구현 과제 — 본 설계가 근거). 불변식(§G)·결정표(C.0/C.2) 단위 테스트 추가. | 별도 구현(M1.2 후속) |

---

> **요약**: 세 라우팅 축(비용·위치 `CostTier` × 로컬 패밀리 `ModelFamily` × 로컬 크기 `LocalModelTier`)을 분리·합성한다. `mid` 명칭 충돌은 `CLOUD_MID`(축1) vs `LOCAL/MID`(축2) 한정 표기로, 패밀리는 `ModelFamily.MATH/GENERAL`로 1급화했다. 입력 분류기가 신호를 모아 축1(80/18/2)→축3(MATH/GENERAL)→축2(FAST/MID/QUALITY)를 순차 결정하고, 실제 모델은 (패밀리×크기) 매트릭스(§A.0)로 해석한다. **2026-05-20 Phaiakes9 태스크 인지 실측이 축3을 강제했다** — NLP를 수학 모델로 돌리면 7b조차 0%, 일반 모델로 바꾸니 match 3b=100%·translate 7b=75%. SLA 데이터(FAST만 p50<2s, QUALITY 비동기 전용)는 여전히 크기 분기의 근거다. 라우팅은 *어디서 생성할지*만 정하고, 환각 방어 파이프라인을 대체하지 않는다.
