# ADR-005 — AI Gateway = L3 라우터 단일 경유 · 3축 라우팅 · 개방 포트폴리오 · 불변 검증 계약

- **상태:** 채택 (기존 결정의 *정본화* — 새 결정을 만들지 않는다)
- **결정일:** 2026-09-15
- **대상:** 계획서 100 §3.16 주제 **`ADR-007 AI Gateway`** 대응 문서. `docs/architecture/adr/README.md` 매핑표의 해당 칸이 "미확인"으로 비어 있던 것을 채운다(`ARCH-45`)
- **관련:** `docs/architecture/03a_l3_router_design.md`(라우터 설계서 정본), `src/backend/whymath_backend/l3/router.py`, `src/backend/whymath_backend/l3/providers/`, `CLAUDE.md` §"✅ 절대 원칙 → LLM 사용", `MEMORY.md` 2026-05-19·2026-05-20·2026-08-16 결정 로그
- **판정 기준:** main `4b33d243` (아래 모든 실측은 이 커밋 기준)

---

## 맥락

`docs/reviews/eos_source_docs_gap_review_2026-08-31.md` §7.3-④가 계획서 100 §3.16의 ADR 10주제
중 **`ADR-007 AI Gateway`에 대응 문서가 없다**고 적었고, `adr/README.md` 매핑표는 그 칸을
"미확인"으로 비워 두었다.

**부재 판정 절차**(CLAUDE.md "식별자 부재를 기능 부재로 단정 금지")대로 역할 기준으로 다시 찾으면
결과가 다르다 — 이 저장소에 "AI Gateway"라는 *이름*은 0건이지만, 그 **역할**은 실재한다:

| 역할 | 저장소의 실체 | 실측 |
|---|---|---|
| 모델 선택·분기 | `l3/router.py` (709줄) | `LOCAL_MODEL_MATRIX`·`business_cost_tier()`·`ESCALATION_CHAIN` |
| 프로바이더 추상화 | `l3/providers/{anthropic,ollama,composite}.py` | 3파일 |
| 비용 회계 | `router.py` `CLOUD_TOKEN_PRICE_USD_PER_1M`·`actual_cost_krw()` | — |
| 관측 태깅 | `router.py` `langfuse_fields()` | — |
| 설계 정본 | `docs/architecture/03a_l3_router_design.md` | 569줄+ |

즉 **미구현이 아니라 미정본화**였다. 결정들은 CLAUDE.md의 절대 원칙, MEMORY.md 결정 로그 3건,
03a 설계서, `config.py` 핀에 흩어져 있었고, 그 결과 "게이트웨이 계약이 무엇인가"를 한 곳에서
읽을 수 없었다. 이 ADR은 **이미 내려진 결정을 옮겨 적는다** — 새 결정을 도입하지 않는다.

---

## 결정

### D1. 모든 LLM 호출은 L3 라우터를 경유한다 — 프로바이더 직접 호출 금지

출처: `CLAUDE.md` §"✅ 절대 원칙 → LLM 사용" 1항 ("LLM 호출은 항상 라우터 경유 — 직접 호출 금지").

라우터는 *어디서 생성할지*만 정한다. 라우터가 환각 방어를 대체하지 않는다(03a §요약).

### D2. 라우팅은 3축의 합성이다 — `mid`를 단독으로 쓰지 않는다

출처: `03a_l3_router_design.md` §0 (2026-05-19·2026-05-20 Phaiakes9 실측 근거).

| 축 | enum | 값 |
|---|---|---|
| 축1 비용·위치 | `CostTier` | `LOCAL` / `CLOUD_MID` / `CLOUD_HIGH` |
| 축2 로컬 크기 | `LocalModelTier` | `FAST` / `MID` / `QUALITY` |
| 축3 모델 패밀리 | `ModelFamily` | `MATH` / `GENERAL` / `VISION` |

실제 로컬 모델 = **(축3 패밀리 × 축2 크기)** 매트릭스 해석(`LOCAL_MODEL_MATRIX`). 축3이 필요한
이유는 취향이 아니라 실측이다 — NLP 호출지점을 수학 특화 모델로 돌리면 **7b조차 정확도 0%**였고,
일반 모델로 바꾸자 match 3b=100%·translate 7b=75%였다(2026-05-20).

`CLOUD_MID`(축1)와 `LOCAL/MID`(축2)가 같은 단어를 쓰므로, **축 접두사 없는 맨 `mid` 표기를
금지**한다(03a §0.1).

### D3. 로컬 우선 — 목표 분포 80 / 18 / 2, 승급은 단방향

출처: `03a` §0 표·§E.3, `router.py` `ESCALATION_CHAIN`.

`LOCAL/FAST → LOCAL/MID → LOCAL/QUALITY → CLOUD_MID → CLOUD_HIGH`. 로컬 3단계를 먼저 올리고
로컬 천장에서도 미달일 때만 클라우드로 넘어가며, 클라우드 승급은 항상 `guard_cloud()`를 통과한다
(무료 요금제는 클라우드 금지, 잔여 예산 부족 시 `LOCAL` 강등, `basic`은 `CLOUD_HIGH` 불가 →
`CLOUD_MID` 제한).

### D4. 프로바이더 포트폴리오는 고정 집합이 아니라 *측정 기반 개방 목록*이다

출처: `MEMORY.md` 2026-08-16 결정 로그(Kiki 지시), `CLAUDE.md` §"✅ 절대 원칙 → LLM 사용" 5항.

신규 프로바이더(OpenRouter 등)·신규 모델을 전제로 배제하지 않는다. **채택 조건 3건**:

1. 라우터(`l3/router.py`) 경유 배선 — D1은 프로바이더가 바뀌어도 불변
2. 실측 근거 (2026-05-20 태스크 인지 실측 선례 형식)
3. MEMORY 결정 로그 기재

현행 핀(실측): 클라우드는 `config.py`의 `anthropic_model_mid`·`anthropic_model_high` **2건뿐**이며
GPT-5·Gemini 2.5는 스택 표에 적혀 있으나 **라우터 미배선**이다(CLAUDE.md 스택 표 단서와 일치).

### D5. 프로바이더가 바뀌어도 불변인 계약 4종

출처: `CLAUDE.md` 2026-08-16 결정 로그 단서 문장 ("모델이 바뀌어도 검증 계약은 불변").

1. **검증 권위** — SymPy 단일 권위, 학생 제공 전 PRM/도구 검증 통과
2. **관측** — 모든 LLM 호출은 Langfuse 추적
3. **미성년자 데이터 정책**
4. **저작권 레일**

게이트웨이는 *어느 모델이 답했는가*를 바꿀 수 있어도 *무엇이 학생에게 나가는가*의 조건은 바꾸지
못한다.

---

## 집행 지점 (정본화와 **별항** — CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지")

**빈 칸을 추측으로 채우지 않는다.** 아래는 main `4b33d243` 기준 실측이다.

| 결정 | 기계 집행 장치 | 판정 |
|---|---|---|
| D2 3축 합성 | `router.py`의 `CostTier`/`LocalModelTier`/`ModelFamily` 타입 분리 + `resolve_model()`, `mypy --strict` | **집행됨** (타입 수준) |
| D3 승급 사슬·클라우드 가드 | `ESCALATION_CHAIN`·`guard_cloud()` + `tests/backend/l3/` 라우터 테스트 | **집행됨** |
| D3 목표 분포 80/18/2 | 분포는 *모니터링* 지표이며 CI 게이트가 아니다(03a §E.3) | **미집행 — 관측만** |
| D5 관측(Langfuse) | `langfuse_fields()`는 **태그 dict만 만들고 실제 전송은 하지 않는다**(`router.py` 상단 주석) — 전송은 호출측 책임 | **부분 — 경계가 의도적으로 분리됨** |
| **D1 라우터 단일 경유** | **확인되지 않음** | **미집행 — 사람 규율** |

### D1이 미집행인 근거 (검색 범위 명시)

- `src/backend/pyproject.toml`의 import-linter 계약은 **3건**이고(7계층 단방향 1건 + EOS Core →
  Math Adapter 금지 2건), 그중 **프로바이더 모듈의 소비자를 제한하는 계약은 없다**.
- `l3/providers/*`를 직접 임포트하는 모듈이 `l3/providers/` 밖에 **13개 이상** 실재한다
  (`ops/cost_probe.py`·`ops/live_preflight.py`·`harness/*` 6건·`l4/misconception/judge_seam.py`·
  `l3/cross_verify.py`·`l3/multi_solution.py` 등).
- 이들 대부분은 라우터도 함께 임포트하므로 **위반이라고 단정할 수 없다** — 라우터가 결정한 모델을
  프로바이더로 실행하는 정상 형태일 수 있다. 확인한 것은 하나뿐이다: **어느 쪽인지 기계가
  판정하지 않는다.**
- 따라서 이 표의 판정은 "D1이 깨져 있다"가 아니라 **"D1을 지키는지 여부를 아무도 측정하지
  않는다"**이다. `l4/misconception/judge_seam.py`는 라우터를 임포트하지 않고 `OllamaProvider()`를
  기본값으로 직접 생성하지만 `RoutingRequest`는 구성한다 — **읽어서 그렇게 보인다**는 범위를
  넘지 않으며, 위반 여부 판정은 아래 열린 질문 ①에 넘긴다.

> 이 칸이 비어 있다는 사실 자체가 이 ADR의 산출물이다. CLAUDE.md의 절대 원칙 중 **기계가 지키지
> 않는 항목**을 드러내는 것이, 지켜지는 척 적어 두는 것보다 낫다("측정 없는 기계 게이트를 인간
> 검수 대체로 선언 금지").

---

## 결과·트레이드오프

- **얻는 것**: 게이트웨이 계약이 한 문서에서 읽힌다. 프로바이더 교체 시 무엇이 협상 가능하고
  (모델·가격·지연) 무엇이 불변인지(D5) 구분된다.
- **치르는 것**: 라우터가 단일 병목이다. 라우터 변경은 전 호출지점에 영향을 준다 — 그래서 3축을
  타입으로 분리해 두었다(D2).
- **의도적 미채택**: 별도 게이트웨이 *서비스*(프록시 프로세스)를 만들지 않는다. 현행 경계는
  **인프로세스 모듈 경계**이며, 이는 CLAUDE.md의 "6번째 store 회피"와 같은 결에서 과공학을
  피한 것이다.

## 열린 질문

1. **D1의 기계 집행** — import-linter `forbidden` 계약으로 `l3/providers/*`의 직접 임포트를
   라우터·ops 진단 경로로 한정할 것인가? baseline 위반이 13건 이상이므로 도입하려면
   `EOS Core → Math Adapter 금지 (baseline 있음)` 계약과 같은 **baseline 동결 + 해소 태스크**
   형태가 필요하다. 이 ADR은 이를 **제안하지 않고 질문으로 남긴다** — 위반 13건의 정오 판정이
   선행이며, 그 판정 없이 계약을 걸면 상시 실패하는 fail-open 보호가 하나 더 생긴다.
2. **GPT-5·Gemini 2.5의 처분** — 스택 표에는 있고 라우터에는 없다. D4의 채택 조건 3건을 밟아
   배선할 것인가, 스택 표에서 내릴 것인가.
3. **분포 80/18/2의 게이트화** — 현재 관측 전용. 게이트로 승격하려면 측정 통과 기계 게이트 6축
   (`docs/standards/superhuman_verification_standard.md`)을 밟아야 한다.

---

## 계획서 번호와의 관계

이 문서의 파일명 번호 **005**는 저장소 계열의 다음 빈 번호이고(`adr_number_check.py` 판정),
계획서 100 §3.16의 **007**은 주제 목록의 번호다. **둘은 무관하다** — `adr/README.md`의 매핑표로만
연결한다.
