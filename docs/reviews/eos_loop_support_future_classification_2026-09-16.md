# 기존 기능 LOOP / SUPPORT / FUTURE 3분류 감사 (계획서 300 §14)

> **판정 기준: main `c4f8c9fb`** (2026-09-16) · 태스크 `EOS-16-loop-support-future-classification-audit`
> **성격: 조사 전용.** production code 0줄 변경 · 백로그 block 처리 0건. 동결 권고의 *집행* 여부는 Kiki 판단으로 남긴다(§7).
> **원 지시문**: 「Phase 2 — EOS Closed Learning Loop 실행계획」 항목 `P-00b`
> (`docs/ops/phase2_eos_closed_loop_execution_prompts.md` · PR [#1176](https://github.com/kiki-s-broom/WhyMath/pull/1176) · **미머지** — 지시문 원문은 커밋 `0d8e848c`에서 읽었다)

---

## §0. 한 줄 판정

**FUTURE ∩ 활발히 개발 중 = 0건.** 원 문서 §14가 "가장 위험하다"고 지목한 상태
("FUTURE 기능을 계속 개발하면서 LOOP가 완성되지 않는 상황")는 **이 저장소에서 실현되지 않았다.**
열린 PR 11건 중 FUTURE 분류 행의 파일을 한 줄이라도 건드린 것은 **0건**이고, `in_progress` 태스크
7건 중 FUTURE 행을 실제로 수정 중인 것도 **0건**이다.

대신 **다른 모양의 위험**이 두 건 실측됐다 — ①루프에 연결돼야 할 기능 **10행이 꺼진 채**
(Flag-off 7 · Batch 3) 서 있고 ②진행 중 작업의 무게가 SUPPORT 쪽으로 쏠려 있다(§6).
이것은 §14가 경고한 "FUTURE 때문에 LOOP 미완"이 아니라 **"SUPPORT 때문에 LOOP 미완"**이며,
전자보다 덜 위험하지만 같은 방향이다.

| 분류 | 행 | 비율 | 뜻 |
|---|---:|---:|---|
| **LOOP** | **92** | 55% | 학습 폐쇄루프에 반드시 연결돼야 하는 것 |
| **SUPPORT** | **72** | 43% | 루프를 지원하지만 없어도 루프가 도는 것 |
| **FUTURE** | **2** | 1% | EOS 확장 — 10월 동결 대상 |
| 계 | 166 | 100% | 분류율 166/166 |

---

## §1. 열거 방법 — 그리고 이 방법이 놓치는 범위

### 1-1. 모집단은 새로 만들지 않았다

기능 표면 열거는 **`EOS-83`이 이미 만든 기계 장부**를 재사용했다. 새 장부를 만들면 이중 진실
원천이 되고, 두 장부가 갈라지는 순간 둘 다 못 믿게 된다.

- 생성기(정본): `scripts/analysis/eos_feature_inventory_v2.py`
- 장부(기계 출력·저장소에 커밋되지 않음 — `OPS-76`): `backlog/inventory/feature_inventory_v2.yaml`
- 전수성·결함 주입 동결: `tests/infra/test_eos_feature_inventory_v2.py` (CI `infra-contracts` 잡)

재현:

```bash
git fetch --unshallow origin
git rev-parse origin/main                                   # c4f8c9fb 이어야 한다
python3 scripts/analysis/eos_feature_inventory_v2.py --write
```

**모집단 166행** (2026-09-03 문서 기재 162행에서 4행 증가 — 그 사이 착지분).
네 평면과 각 평면의 전수성 검사는 아래와 같고, 어느 하나라도 빠지면 생성기가 exit 1로 장부를 쓰지 않는다.

| 평면 | 모집단 정의 | 전수성 검사 | 행 |
|---|---|---|---:|
| **S** 서빙 표면 | `app.py`가 `include_router`한 **22 라우터** + app 자체 엔드포인트 | **110 엔드포인트** 전부 정확히 1행 귀속 | 50 |
| **E** 백엔드 엔진 | `whymath_backend` 모듈 가족(l1~l6·whs·harness 런타임·schema·db·infra) | **606 모듈** 전부 정확히 1행 귀속 | 90 |
| **O** 운영자 도구 | `ops`·`privacy` CLI · `harness` 배치/게이트/리포트 가족 | E와 같은 모듈 검사 | 14 |
| **C** 클라이언트 | Flutter `lib/features/*`·`lib/core` · web 그래핑 계산기 | 10 feature 디렉터리 전부 귀속 | 12 |

### 1-2. 이 방법이 놓치는 범위 (부재 판정 절차 — "내가 찾은 방법으로는 N건")

**분류표 166행은 저장소의 실행 가능한 코드 전부가 아니다.** 아래는 모집단 정의상 *의도적으로* 또는
*알려진 결함으로* 빠진 표면이며, 그러므로 "여기에 FUTURE 기능이 없다"는 본 감사의 결론은
**아래 범위에는 미치지 않는다**.

| 빠진 표면 | 규모(실측) | 사유 | 위험 |
|---|---:|---|---|
| 패키지 초기화 모듈 `__init__.py` | **57건** | 생성기 모집단이 제외 — **알려진 결함**, `ARCH-42`가 소유(todo) | 낮음(대부분 re-export) |
| Alembic 마이그레이션 | **100건** | 스키마 이력이지 기능 아님 | 낮음 |
| `scripts/` 운영 스크립트 | **68건**(harness 16 포함) | 저장소 도구지 제품 기능 아님 | **중** — 아래 실증 참조 |
| `src/data-pipeline` 독립 모듈 | 79건 중 일부만 E행에 `pipelines`로 편입 | ETL 절반만 매핑 | 중 |
| `src/web` | `graphing-calculator` 1종만 (C행에 편입) | 그 외 웹 표면 없음 | 낮음 |
| `.github/workflows` | — | CI지 기능 아님 | 낮음 |

**이 사각은 추측이 아니라 실측됐다.** §5의 PR 교차에서 열린 PR이 건드린 소스 파일 중
**8건이 어느 행에도 귀속되지 않았다** — `scripts/ops/activate_rocm72_standalone.{ps1,py}`,
`bench_ollama.ps1`, `install_rocm72_standalone.ps1`, `restore_rocm72_builtin.py`,
`tune_and_bench.ps1`, `run_moe_quality_battle.ps1`, 그리고 LIC-01 마이그레이션 1건.
즉 **운영 스크립트 축은 3분류 자체가 적용되지 않는다.** 그것들이 FUTURE인지 아닌지는 이 감사가
답하지 않았다(모두 로컬 LLM 벤치·환경 설치 스크립트로 보이나, **읽어서 그렇게 보인다**는 범위다).

---

## §2. 분류 규칙 — 산문이 아니라 기계 판정

§14의 세 정의를 저장소에서 **재현 가능한 신호**로 옮겼다. 위에서부터 첫 일치가 판정이며,
**FUTURE가 1순위**다(확장 기능이 루프에 닿아 있어도 동결 대상이라는 §15 취지).

### FUTURE — "EOS 확장 기능, 10월 동결 대상"

| 코드 | 규칙 | 적중 |
|---|---|---:|
| **F1** | 카탈로그 `horizon == "P3"` 선언 (장기 연구/플랫폼 — P3는 *선언*으로만 생긴다) | **2** |
| **F2** | §14 FUTURE 7종 / §15 동결 13종 키워드가 기능명·좌석·경로에 존재<br>(`디지털 트윈`·`가상 학습`·`성장 경로 예측`·`자동 콘텐츠 리팩`·`연구자 협업`·`교사 협업`·`multi_agent`·`pagerank`·`자동 교수법`·`ab_test`·`experiment_arm` 외) | **0** |

### LOOP — "학습 폐쇄루프에 반드시 연결돼야 하는 것"

씨앗은 계획서 300 §12 API 12종에서 온 **`STUDENT_LOOP_ROUTES` 25개 라우트**다(생성기 상수).

| 코드 | 규칙 | 적중 |
|---|---|---:|
| **L1** | (S평면) 자기 라우트가 `STUDENT_LOOP_ROUTES`에 속함 — 루프 씨앗 그 자체 | 17 |
| **L2** | `loop_seed` 선언 — import 그래프에 안 잡히는 진입점(클라 앱 셸 등) | 2 |
| **L3** | (C평면) 클라이언트 소스에 루프 라우트 리터럴 존재 | 7 |
| **L4** | 학생 루프 씨앗에서 **import로 도달** | 62 |
| **L5** | 루프가 읽는 테이블의 (유일) writer — 데이터가 없으면 루프는 빈 화면이다 | 4 |

### SUPPORT — "루프를 지원하지만 없어도 루프가 도는 것"

| 코드 | 규칙 | 적중 |
|---|---|---:|
| **S1** | (S평면) `PRODUCTION_LOOP_ROUTES`(앵커 콘텐츠 **생산** 루프) 씨앗 — 학생 루프 아님 | 2 |
| **S2** | 앵커 생산 루프에만 import 도달 — 학생 루프 아님 | 9 |
| **S3** | 불변 계약(미성년 PII·저작권 레일·Langfuse 추적·동의·인증 배관) — 루프와 직교하나 법적 필수 | 8 |
| **S4** | 루프 미도달 | 53 |

**S1·S2를 SUPPORT로 둔 판단 근거(명시)**: 앵커 콘텐츠 생산 루프(생성→검증→검수큐)는
§14 정의상 *학습* 폐쇄루프가 아니다 — 새 문항이 하나도 안 만들어져도 **기존 콘텐츠 위에서
학생 루프는 돈다**. 다만 이것은 "덜 중요하다"는 뜻이 **아니다**: 11행 전부가 `release_priority=P0`
(선언 부록 E G1~G3·G5 차단 조건)이며, 10월의 공식 목표인 **G2 앵커 콘텐츠 생산**이 바로 이 축이다.
§14 축과 12월 검증 축은 직교하며, 이 표는 §14 축만 말한다.

**S3(불변 계약)를 SUPPORT로 둔 판단 근거**: 인증이 없으면 루프는 401로 멈추므로 기계적으로는
LOOP에 가깝다. 그러나 §14의 LOOP는 *학습 상태가 흐르는 경로*를 말하고, 인증·동의·PII 보호는
그 경로와 **직교하는 상시 계약**이다(생성기도 같은 이유로 `INVARIANT_AUTH_MODULES`를 도달성
판정에서 분리한다 — "넣으면 인증이 걸린 전 표면이 P0가 된다"). **이 8행은 동결 후보가 아니다.**

### 2-1. 이 규칙에 변별력이 있는가 — 주입 시험

정상 입력에서 표가 그럴듯하게 나오는 것은 증거가 아니다. **막으려는 상태를 주입해 판정이
실제로 뒤집히는지** 확인했다(주입 적용 여부·원복도 각각 단언).

| # | 주입 | 대상 | 기대 | 결과 |
|---|---|---|---|---|
| M1 | 루프 도달 신호 6종 전멸 | WM-E-101 | LOOP → SUPPORT | ✅ 검출 |
| M2 | 기능명에 FUTURE 키워드(`디지털 트윈`) 삽입 | WM-S-001 | SUPPORT → FUTURE | ✅ 검출 |
| M3 | `horizon="P3"` 선언 주입 | WM-E-101 | LOOP → **FUTURE** (1순위 증명) | ✅ 검출 |
| M4 | 씨앗 라우트 제거 | WM-S-003 | LOOP → SUPPORT | ✅ 검출 |
| M5 | `data_supplier` 단독 점등 | WM-E-110 | SUPPORT → LOOP | ✅ 검출 |
| M6 | **대조군** — S평면에 `data_supplier` 주입(생성기 정의상 불가능한 상태) | WM-S-001 | SUPPORT 유지 | ✅ 유지 |
| M7 | **대조군** — 무관 필드(`migration_risk`·`loc`) 변경 | WM-S-001 | SUPPORT 유지 | ✅ 유지 |

전건 통과(exit 0). **M5는 처음에 생존했다** — 첫 픽스처로 S평면 행을 골랐는데 L5절은
`plane != "S"`에서만 도달하므로 **그 절을 한 번도 밟지 않았다**. 픽스처를 E평면 행으로 교체한 뒤
RED가 나왔다. 규칙이 관대했던 것이 아니라 픽스처가 그 자리를 지나가지 않은 것이다
(CLAUDE.md "픽스처가 그 절을 실제로 밟는가" 3회차). 대조군 M6·M7은 과잉 판정(모든 입력에서
FUTURE/LOOP를 내는 규칙)을 배제하기 위한 것이다.

---

## §3. 총계와 교차

### 3-1. §14 분류 × 12월 검증 등급 (`release_priority`)

두 축은 **직교하며 서로를 대체하지 않는다**. `release_priority`는 "없으면 12/31 검증이
성립하는가"를, §14 분류는 "학습 폐쇄루프 경로 위에 있는가"를 묻는다.

| | P0 | P1 | P2 | P3 | 계 |
|---|---:|---:|---:|---:|---:|
| **LOOP** | 85 | 7 | 0 | 0 | **92** |
| **SUPPORT** | 18 | 33 | 21 | 0 | **72** |
| **FUTURE** | 0 | 0 | 0 | 2 | **2** |
| 계 | 103 | 40 | 21 | 2 | 166 |

읽는 법: **P0 103건 중 18건이 SUPPORT**다 — 12월 검증에는 필수인데 *학습 루프*에는 안 걸린
것들이며, 대부분 앵커 생산 루프(§2 S1·S2 11행)와 불변 계약이다. 반대로 **LOOP 92건 중 7건이
P1**인데, 이 7건은 전부 아래 3-2의 꺼진 기능이다(도달은 하나 Flag-off라 "우회 가능" 판정).

### 3-2. ⚠ LOOP인데 켜져 있지 않은 10행 — §14 위험의 실제 모양

§14가 경고한 "LOOP가 완성되지 않는 상황"의 **저장소 내 실체**는 FUTURE 개발이 아니라 이것이다.

| ID | 기능 | 상태 | 플래그 |
|---|---|---|---|
| WM-E-306 | 빌드타임 캐시 사전생성(pre-warm)·시드 검증 | Batch | — |
| WM-E-413 | 오개념 의미(임베딩) 매칭 + shadow | Flag-off | `misconception_semantic_mode="off"` |
| WM-E-414 | 오개념 방향 판별 LLM-judge + shadow | Flag-off | `misconception_judge_enabled=False` |
| WM-E-415 | 오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수 | Flag-off | `misconception_crosslink_mode="off"` |
| WM-E-416 | 오답 형태 SymPy 매칭(canonical_wrong_form) | Flag-off | `misconception_wrong_form_mode="off"` |
| WM-E-417 | 중간 단계 등가성 shadow 관측·평가 | Flag-off | `l4_step_shadow_enabled=False` |
| WM-E-703 | bank_solution → SolutionPath 승격 writer | Batch | — |
| WM-E-705 | WH-1 shadow 관측·수확·2단계 종료 게이트 | Flag-off | `wh1_harness_shadow_enabled=False` |
| WM-E-809 | 데모 인증(시연 전용 가짜 OAuth provider) | Flag-off | `demo_auth_enabled=False` |
| WM-O-912 | QA 파이프라인·강등전 게이트(Wilson·결함주입·금칙어) | Batch | — |

**10행 중 5행이 오개념 축**(WM-E-413~416 + 417)이다. 계획서 300 §7이 오개념 탐지를 루프의
한 마디로 두는데, 이 저장소에서 그 마디는 **코드는 있고 스위치가 꺼져 있다**. 이것은 §14의
FUTURE 문제가 아니라 **shadow→production 승격이 안 끝난 상태**이며, 동결이 아니라 *개통*이
필요한 쪽이다. `WM-E-809`(데모 인증)는 Flag-off가 정상이다 — 끄는 것이 설계다.

> 주의: 이 10행에 대한 조치 제안은 **본 감사의 범위 밖**이다(조사 전용). 여기서는 상태만 적는다.

---

## §4. FUTURE 2행 — 전수

| ID | 기능 | 경로 | 상태 | 판정 근거 | 좌석 |
|---|---|---|---|---|---|
| WM-E-701 | WH-S 솔버 하네스(루프·판정·저장소·코퍼스 replay) | `src/backend/whymath_backend/whs` | Production | F1 `horizon=P3` | 03b 설계 — 솔버 자기진화 플랫폼(PRM 라벨 공급) — 12월 폐쇄루프 밖·장기 연구 |
| WM-E-702 | WH-S 자기진화(PRM·SFT 학습셋 export) | `src/backend/whymath_backend/whs` | Batch | F1 `horizon=P3` | 설계 §5 — 2027 학습 파이프라인(PRM·SFT) — 장기 연구 |

**§14 FUTURE 7종 / §15 동결 13종에 대응하는 코드는 여전히 0건이다**(F2 적중 0).
이는 2026-09-03 `plan300_phase2_backlog_crosswalk.md` §2의 재확인이며, 본 감사가 그 시점
이후(main `c4f8c9fb`) 기준으로 **다시 세어도 같은 결과**임을 뜻한다. 다과목 확장은 코드가 아니라
백로그에만 있고 **3중 동결** 상태다(`stage=E1~E6` × `eos_priority=P3` × 사람 게이트
`G-s5-subject-expansion`) — 관련 태스크 15건 전부 `todo`.

---

## §5. FUTURE ∩ 활발히 개발 중 — 핵심 교차표

> **원 문서가 "가장 위험하다"고 지목한 상태.** 판정 방법: 열린 PR 11건 각각에 대해
> `git diff --name-only $(git merge-base <head> origin/main) <head>`의 `src/`·`scripts/` 파일을
> 166행의 소유 경로에 귀속시키고 분류별로 집계했다.

### 5-1. 열린 PR 11건 × 분류 (파일→행 귀속 건수)

| PR | 제목 | LOOP | SUPPORT | **FUTURE** | 미귀속 | 성격 |
|---|---|---:|---:|---:|---:|---|
| [#1176](https://github.com/kiki-s-broom/WhyMath/pull/1176) | Phase 2 집행 지시문 세트 | 0 | 0 | **0** | 0 | 문서 전용 |
| [#1174](https://github.com/kiki-s-broom/WhyMath/pull/1174) | HARN-105 등재 | 0 | 0 | **0** | 0 | 대장 전용 |
| [#1145](https://github.com/kiki-s-broom/WhyMath/pull/1145) | ASM-10 조립 세트 시행 귀속 관측 | 4 | 12 | **0** | 0 | SUPPORT |
| [#1076](https://github.com/kiki-s-broom/WhyMath/pull/1076) | S3-28 canonicalize 적용범위 오탐 | 4 | 5 | **0** | 0 | SUPPORT |
| [#1061](https://github.com/kiki-s-broom/WhyMath/pull/1061) | HARN-82 필수 체크 간접 계측 | 0 | 0 | **0** | 0 | 대장 전용 |
| [#1007](https://github.com/kiki-s-broom/WhyMath/pull/1007) | Gate 0 판정 r6 + 백로그 정정 | 0 | 0 | **0** | 0 | 문서·대장 전용 |
| [#975](https://github.com/kiki-s-broom/WhyMath/pull/975) | PB-13 완료 기록 + HARN-61 | 0 | 0 | **0** | 0 | 대장 전용 |
| [#865](https://github.com/kiki-s-broom/WhyMath/pull/865) | S4-16 OpenRouter + prompt v2 | 49 | 17 | **0** | 7 | LOOP |
| [#858](https://github.com/kiki-s-broom/WhyMath/pull/858) | LIC-01 Rights & Provenance MVP | 41 | 25 | **0** | 2 | LOOP |
| [#856](https://github.com/kiki-s-broom/WhyMath/pull/856) | S4-16/OPS-48 감사 JSONL 스키마 (draft) | 19 | 21 | **0** | 1 | SUPPORT |
| [#844](https://github.com/kiki-s-broom/WhyMath/pull/844) | S4-16 Ollama override + K=3 (draft) | 26 | 13 | **0** | 0 | LOOP |
| | **합계** | | | **0** | 8 | |

**FUTURE 행(= `whs/` 경로)을 건드린 PR은 0건이다.** 11개 head 전부에 대해
`git diff --name-only … | grep -c "whs/"` = **0**으로 직접 확인했다.

### 5-2. `in_progress` 태스크 7건 × 분류

| 태스크 | stage | eos_prio | 선언 경로가 닿는 분류 | 실제 FUTURE 수정 |
|---|---|---|---|---|
| `ARCH-09-concept-version-model-registry-omission` | S3 | P1 | (파일 단위 선언 — LOOP 인접) | 없음 |
| `EOS-16-…-classification-audit` (본 태스크) | S3 | P2 | 문서 전용 | 없음 |
| `HARN-56-merge-queue-adoption` | S3 | P1 | CI·문서 전용 | 없음 |
| `LIC-01` | **E2** | P1 | **LOOP + SUPPORT + FUTURE** | **없음**(아래) |
| `MOB-18-issues-review-nonsecurity-recovery` | S3 | P1 | LOOP + SUPPORT | 없음 |
| `PB-13-authoring-expansion-corpus-recovery` | S3 | P1 | LOOP + SUPPORT | 없음 |
| `SKB-04-concept-content-k12-prod-populate` | S3 | P1 | LOOP | 없음 |

**`LIC-01`의 FUTURE 적중은 실질이 아니라 선언 아티팩트다.** 이 태스크의 `paths`가
`src/backend/whymath_backend/**` — **백엔드 전체**이므로 `whs/`를 포함한 모든 행에 형식적으로
걸린다. 그러나 실제 PR([#858](https://github.com/kiki-s-broom/WhyMath/pull/858)·[#865](https://github.com/kiki-s-broom/WhyMath/pull/865)) 디프는 `whs/` 파일을 **0건** 건드린다. 따라서 FUTURE 개발이 아니다.

다만 이 행은 **별건 두 가지를 드러낸다**(§8에 등재 권고로 분리).

---
## §6. 진행 중 작업의 무게 배분 — §14 위험의 변형

§14의 경고를 "무엇에 힘을 쓰고 있는가"로 바꿔 읽으면, 답은 **FUTURE가 아니라 SUPPORT**다.

- 코드를 건드리는 열린 PR 5건 중 **3건이 S4-16 계열**(로컬 LLM 프로바이더·벤치·감사 JSONL —
  [#865](https://github.com/kiki-s-broom/WhyMath/pull/865)·[#856](https://github.com/kiki-s-broom/WhyMath/pull/856)·[#844](https://github.com/kiki-s-broom/WhyMath/pull/844))이고, 그중 2건은 2026-08 개설 후 **3주 이상 미머지 draft**다.
- 같은 기간 계획서 300이 LOOP 축의 **핵심 갭으로 지목한 5건**(`EOS-10` LearnerState 단일 표면 ·
  `EOS-11` Event Trace 읽기 · `EOS-12` Assessment Evidence 계약 · `EOS-13` Mastery 갱신 계약 ·
  `EOS-14` Recommend 계약)은 **전부 `todo`이며 착수 0건**이다 — `backlog.py next`의 1~4순위가
  그대로 이 넷이다.

즉 §14가 예언한 인과("FUTURE 개발 → LOOP 미완")는 성립하지 않지만, **결과("LOOP 미완")는
성립한다.** 다른 원인으로. 이 관찰은 판정이 아니라 관측이며, 우선순위 재배분은 Kiki 판단이다.

---

## §7. 동결 권고 + 집행 방법

> **권고이며 집행이 아니다.** 본 세션은 태스크 `block` 처리·`priority` 변경·PR close를 **하나도
> 하지 않았다.** 아래는 "집행하려면 이 명령"까지만 적는다.

### 7-1. 신규 동결 권고 — **0건**

FUTURE 2행(WM-E-701·702) 모두 **이미 동결 상태**이며, 추가 조치가 불필요하다:

| 대상 | 현 동결 수단 | 실측 | 추가 권고 |
|---|---|---|---|
| WM-E-701·702 (`whs/`) | `horizon="P3"` 선언 → `release_priority=P3` | 열린 PR 11건 중 `whs/` 접촉 **0건** | **없음** — 건드리는 사람이 없다 |
| 다과목 확장(E1~E6) | `stage=E1~E6` × `eos_priority=P3` × 사람 게이트 `G-s5-subject-expansion` | 관련 태스크 **15건 전부 `todo`** | **없음** — 3중 동결은 notes 산문보다 강하다 |
| §15 동결 13종 | 코드 0건 | F2 키워드 적중 **0** | **없음** |
| 신규 EOS 기능번호 추가 | `backlog.py add`가 `--eos-priority` 미지정 시 **exit 1** (`HARN-55` done) | 본 감사의 `EOS-16` 등재 시 실제로 강제됨 | **없음** — 기계 집행 중 |

원 지시문이 예상한 처방("FUTURE는 등재하되 priority를 낮추고 10월 착수 금지를 notes에 적는다")은
**이미 더 강한 형태로 집행 중**이다 — notes 산문이 아니라 `stage`·게이트·CLI exit 1이다.
notes 산문 동결은 CLAUDE.md가 명시적으로 무효라고 적은 형태다(`selector.py`는 notes를 읽지 않는다).

### 7-2. 만약 Kiki가 동결을 집행하기로 한다면 — 명령 형태

FUTURE 2행을 백로그 축에서도 명시적으로 막고 싶은 경우(현재는 *태스크가 없어서* 막을 것이 없다.
`whs`를 대상으로 하는 미완 태스크가 생길 때 쓸 형태):

```bash
# Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B main origin/main
git log -1 --oneline     # c4f8c9fb 로 시작해야 한다

# ① 현재 whs를 대상으로 하는 미완 태스크가 있는지 전건 조회(절단 금지)
python -m scripts.harness.backlog next --n 500 --json

# ② (있을 때만) 해당 태스크를 사람 게이트 뒤로 보낸다 — 대장 손편집 금지
python scripts\harness\backlog.py amend <TASK-ID> --priority 3 --reason "계획서 300 §15 10월 동결"
```

`block` 상태 전환은 `depends_on`·게이트로 하는 것이 정본이며(`notes`에 "착수 금지"를 적는 것은
집행이 아니다 — CLAUDE.md "선행 조건을 산문에만 적고 대장에 집행하지 않기 금지"),
어느 쪽을 쓸지는 그런 태스크가 생겼을 때 판단하면 된다.

---

## §8. 이번 감사에서 나온 별건 — 등재 권고(본 세션은 등재하지 않았다)

범위 규율상 이번 항목 밖이므로 **고치지 않았다.** 두 건 모두 `LIC-01` 행에서 드러났다.

1. **`LIC-01`의 `stage=E2`** — E2는 **화학 과목 확장** 스테이지다. 그런데 `LIC-01`은
   Rights & Provenance(저작권·출처 레일 = §14 기준 불변 계약)이고 `eos_priority=P1`, 상태는
   `in_progress`다. 스테이지 축과 내용이 어긋나 있어, 스테이지 기반 진입 게이트가 이 태스크를
   잘못 다룰 여지가 있다(`S1-16` 실피해로 기록된 "오분류된 트랙" 형태). 정정 CLI 경로 자체는
   `HARN-49-task-track-amend-path`(**done**)가 이미 열어 뒀으므로, 남은 것은 *이 한 건을
   실제로 정정할지*의 판단뿐이다 — 그 판단은 Kiki 몫이고 본 감사는 하지 않았다.
2. **`paths: src/backend/whymath_backend/**`** — 백엔드 전체를 선언한 태스크가 있으면
   `backlog.py`의 파일 범위 겹침 경고가 **모든 태스크에 대해 켜져** 변별력을 잃는다. 실제로
   본 태스크 등재 시 겹침 경고 11건이 떴고 그중 실질 충돌은 0이었다. 경고가 상시 켜지면
   사람은 그것을 읽지 않게 된다(CLAUDE.md "상시 실패하는 fail-open 보호" 형태).

---

## §9. 완료 판정

| 지시문 요구 | 충족 | 근거 |
|---|---|---|
| ① 기능 표면 전수 열거 + 열거 방법·사각 명시 | ✅ | §1 — 166행 / 4평면 / 놓치는 6표면을 실측 규모와 함께 기재, PR 교차에서 미귀속 8건으로 사각을 실증 |
| ② §14 기준 LOOP/SUPPORT/FUTURE 전수 분류 | ✅ | §2 규칙(재현 가능·주입 7종 검증) + §10 전수 분류표 166/166 |
| ③ FUTURE ∩ 활발히 개발 중 별도 표 | ✅ | §5 — 열린 PR 11건 × 분류, `in_progress` 7건 × 분류. **결과 0건** |
| ④ 동결 권고 + 집행 방법(block은 Kiki 판단) | ✅ | §7 — 신규 권고 0건 + 필요 시의 명령 형태. 본 세션 집행 0건 |
| ⑤ 조사 전용 — 코드 미변경 | ✅ | 변경 파일 = 본 문서 + 백로그 대장(태스크 등재·claim·done) |
| ⑥ 판정 기준 커밋 해시 명기 | ✅ | 문서 상단 `main c4f8c9fb` |

---

## §10. 전수 분류표 (166행)

> 상태 열의 굵은 글씨(**Flag-off**·**Batch**)는 Production이 아닌 것. §14 열의 굵은 글씨는
> LOOP·FUTURE.

### S 서빙 표면 — 50행 (LOOP 17 · SUPPORT 33 · FUTURE 0)

| ID | 기능 | 도메인 | 상태 | §14 | 판정 근거 |
|---|---|---|---|---|---|
| WM-S-001 | 헬스체크·상태 조회 | Operations | Production | SUPPORT | S4 루프 미도달 — Operations / Platform |
| WM-S-002 | LLM 생성 게이트웨이(동기·비동기 잡) | AI Orchestration | Production | SUPPORT | S1 앵커 생산 루프 씨앗 2건 — 학생 루프 아님: GET /v1/jobs/{job_id}, POST /v1/generate |
| WM-S-003 | 소셜 로그인(OAuth 카카오·네이버) | Identity | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: POST /{provider}/callback |
| WM-S-004 | 토큰 회전·로그아웃 | Identity | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: POST /refresh |
| WM-S-005 | 활성 세션 목록·원격 로그아웃 | Security | Production | SUPPORT | S4 루프 미도달 — Security / Student |
| WM-S-006 | 내 프로필 조회·수정(온보딩) | Identity | Production | **LOOP** | L1 학생 루프 씨앗 라우트 2건: GET /me, PATCH /me |
| WM-S-007 | 법정대리인 동의 기록·철회·조회 | Security | **Flag-off** | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-008 | 디바이스 등록·폐기·목록 | Security | Production | SUPPORT | S4 루프 미도달 — Security / Student |
| WM-S-009 | 개인정보 처리 권한 판정(PEP) | Security | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-010 | 내 학습 세션 이력·종료·삭제 | Event | Production | SUPPORT | S4 루프 미도달 — Event / Student |
| WM-S-011 | 내 진단 이력·완료·삭제 | Assessment | Production | SUPPORT | S4 루프 미도달 — Assessment / Student |
| WM-S-012 | 평가 조립(청사진)·측정 캡처 | Assessment | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: POST /assessments/assemble |
| WM-S-013 | 내 코치 대화 이력·종료·삭제 | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Student |
| WM-S-014 | 내 개인정보 감사 이력 조회(삭제·접근) | Security | Production | SUPPORT | S4 루프 미도달 — Security / Student |
| WM-S-015 | 풀이 채점 제출(attempt 적재+숙달 갱신) | Learning Model | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: POST /attempts |
| WM-S-016 | 개념·스킬 숙달 곡선 조회 | Learning Model | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /mastery/current |
| WM-S-017 | IRT 능력(θ) 추정·스냅샷·성장 곡선 | Learning Model | Production | SUPPORT | S4 루프 미도달 — Learning Model / Student |
| WM-S-018 | 개념 진단(BKT↔IRT 교차검증)·요약 | Assessment | Production | **LOOP** | L1 학생 루프 씨앗 라우트 2건: GET /diagnosis/concepts, GET /diagnosis/summary |
| WM-S-019 | 약개념 추천·복습 우선순위 큐 | Recommendation | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /weak-concepts |
| WM-S-020 | 선수개념 갭·학습 경로·개념 코칭 결정 | Recommendation | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /weak-concepts/{concept_id}/learning-path |
| WM-S-021 | 적응형 다음 문항 추천(IRT CAT) | Recommendation | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /next-problem |
| WM-S-022 | 목표 진행 상황(D-day·성취기준 커버리지) | Learning Model | Production | SUPPORT | S4 루프 미도달 — Learning Model / Student |
| WM-S-023 | 계정 삭제권·데이터 이동권(내보내기) | Security | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-024 | 성장 증거 노출(학생 안전)·대리지표 원시값(admin) | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Student |
| WM-S-025 | 학습시간 통계 | Analytics | Production | SUPPORT | S4 루프 미도달 — Analytics / Student |
| WM-S-026 | 학습목표 맞춤 학습 단위 공급·결과 기록 | Pedagogy | Production | **LOOP** | L1 학생 루프 씨앗 라우트 2건: POST /{objective_id}/outcome, POST /{objective_id}/study |
| WM-S-027 | 교수학 통합 결정(stateless 코치) | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Student |
| WM-S-028 | 코치 대화 세션(생성·턴 추가·조회) | Pedagogy | Production | **LOOP** | L1 학생 루프 씨앗 라우트 3건: GET /coach/sessions/{dialogue_id}, POST /coach/sessions, POST /coach/sessions/{dialogue_id}/turns |
| WM-S-029 | 결정론 채점 3종(단계·풀이·답 검산) | Math Engine | Production | **LOOP** | L1 학생 루프 씨앗 라우트 3건: POST /verify-answer, POST /verify-solution, POST /verify-step |
| WM-S-030 | 문제 조회(공개 투영·단계·관계) | Content | Production | **LOOP** | L1 학생 루프 씨앗 라우트 2건: GET /{problem_id}, GET /{problem_id}/steps |
| WM-S-031 | 문제 저작 CRUD | Content | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-032 | 검증 풀이 경로 단계 점층 공개 | Content | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /{solution_path_id}/steps |
| WM-S-033 | 개념 그래프 조회(목록·단건·엣지) | Knowledge Graph | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /{concept_id} |
| WM-S-034 | 개념 의미검색(pgvector) | Knowledge Graph | Production | SUPPORT | S4 루프 미도달 — Knowledge Graph / Student |
| WM-S-035 | 개념 콘텐츠(정의·비유·예시) 조회 | Content | Production | **LOOP** | L1 학생 루프 씨앗 라우트 1건: GET /content |
| WM-S-036 | 개념 노드 저작 CRUD | Knowledge Graph | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-037 | 교육과정 프레임워크·버전·노드 조회 | Curriculum | Production | SUPPORT | S4 루프 미도달 — Curriculum / Admin |
| WM-S-038 | 성취기준(학습 성과) 단건 조회 | Curriculum | Production | SUPPORT | S4 루프 미도달 — Curriculum / Admin |
| WM-S-050 | 성취기준 학습맵 단일 조회(개념·스킬·문제·오개념 4홉) | Curriculum | Production | SUPPORT | S4 루프 미도달 — Curriculum / Admin |
| WM-S-039 | 개념↔성취기준 정렬 통합 조회 | Curriculum | Production | SUPPORT | S4 루프 미도달 — Curriculum / Admin |
| WM-S-040 | 권리(저작권) 판정 게이트웨이 | Content | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-S-041 | L6 응용 모드 게이팅 6종(재수·수능·학교진도·사고력·메타인지·영재) | Application Mode | Production | SUPPORT | S4 루프 미도달 — Application Mode / Student |
| WM-S-042 | 약점 개념 맞춤 시각화 생성 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Student |
| WM-S-043 | 시각화 명세 검증·공유 링크 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Student |
| WM-S-044 | 약점 개념 맞춤 학습 장면 생성 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Student |
| WM-S-045 | 시각화 조작 이벤트 적재 | Event | Production | SUPPORT | S4 루프 미도달 — Event / Student |
| WM-S-046 | 손글씨 풀이 OCR(단일·다중 페이지) | Math Engine | **Flag-off** | SUPPORT | S4 루프 미도달 — Math Engine / Student |
| WM-S-047 | 수식 한국어 낭독 명세 생성 | Math Engine | Production | SUPPORT | S4 루프 미도달 — Math Engine / Student |
| WM-S-048 | DSL 콘텐츠 생성·검증·컴파일 | Content | Production | SUPPORT | S1 앵커 생산 루프 씨앗 3건 — 학생 루프 아님: POST /compile, POST /generate, POST /validate |
| WM-S-049 | 학생 결함 신고 접수 | QA | Production | SUPPORT | S4 루프 미도달 — QA / Student |

### E 백엔드 엔진 — 90행 (LOOP 65 · SUPPORT 23 · FUTURE 2)

| ID | 기능 | 도메인 | 상태 | §14 | 판정 근거 |
|---|---|---|---|---|---|
| WM-E-101 | 원자 백본 그래프 적재·검색·중복 검수 | Knowledge Graph | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-102 | 구 개념그래프 적재·임베딩·검색 | Knowledge Graph | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-103 | 개념↔원자 크로스워크 이전 | Knowledge Graph | Production | **LOOP** | L5 루프가 읽는 테이블의 (유일) writer — 데이터 없으면 루프가 빈 화면 |
| WM-E-104 | 개념 콘텐츠 4종 적재·해석 | Content | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-105 | 교육과정 프레임워크 로더·해석 | Curriculum | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-106 | 성취기준·평가기준 적재·정렬 질의·앵커 레지스트리 | Curriculum | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-107 | 오개념 카탈로그·크로스링크 적재·승인 게이트 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-108 | 교수법 팩·단원 DSL 컴파일·적재 | Pedagogy | Production | **LOOP** | L5 루프가 읽는 테이블의 (유일) writer — 데이터 없으면 루프가 빈 화면 |
| WM-E-109 | 문제은행 적재·임베딩·시그니처·페르소나 적합·정답분포 | Content | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-110 | 공식 그래프 적재 | Knowledge Graph | Production | SUPPORT | S4 루프 미도달 — Knowledge Graph / Platform |
| WM-E-111 | 스킬 그래프 적재·해석 | Knowledge Graph | Production | **LOOP** | L5 루프가 읽는 테이블의 (유일) writer — 데이터 없으면 루프가 빈 화면 |
| WM-E-112 | 풀이 전략 그래프 적재 | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Platform |
| WM-E-113 | 문제 유형 그래프 적재 | Content | Production | SUPPORT | S4 루프 미도달 — Content / Platform |
| WM-E-114 | 진단문항·소크라테스 프로브 적재 | Assessment | Production | SUPPORT | S4 루프 미도달 — Assessment / Platform |
| WM-E-115 | 저작권 게이트웨이·정책 엔진·귀속 | Content | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-116 | 개념 시각화·시각 스타일 오버레이 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Platform |
| WM-E-117 | 임베딩 제공자 셀렉터(bge-m3·OpenAI·fake) | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-118 | 그래프 분석 유틸(ETL 측) | Knowledge Graph | Production | SUPPORT | S4 루프 미도달 — Knowledge Graph / Platform |
| WM-E-201 | BKT 숙달 추정·개념/스킬 숙달 이력 영속 | Learning Model | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-202 | IRT 문항·능력 동시 추정·θ 시계열 | Learning Model | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-203 | 문항 난이도 JMLE 보정 배치 | Assessment | **Batch** | SUPPORT | S4 루프 미도달 — Assessment / Admin |
| WM-E-204 | 개념 진단(BKT↔IRT 교차)·LearnerState 조립 | Assessment | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-205 | 약·강·선수개념 추천·학습 경로·복습 큐 | Recommendation | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-206 | 학습 증거 이벤트 적재(attempt·처치·추천 회계) | Event | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-207 | 목표 진행 조회 좌석 | Learning Model | Production | SUPPORT | S4 루프 미도달 — Learning Model / Student |
| WM-E-208 | 일별 학습 지표 롤업 writer | Analytics | Production | SUPPORT | S4 루프 미도달 — Analytics / Admin |
| WM-E-301 | LLM 라우터(3축 결정·모델 매트릭스·seed 정책) | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-302 | LLM 제공자(Ollama·Anthropic·복합) | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-303 | 생성 파이프라인·Redis 캐시·Langfuse 관측 | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-304 | QUALITY 티어 비동기 큐(Celery) | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-305 | 데이터 등급 → 국외 반출 게이트 | Security | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-306 | 빌드타임 캐시 사전생성(pre-warm)·시드 검증 | AI Orchestration | **Batch** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-307 | DSL 콘텐츠 생성기(컴파일·검증·복구·변수 엔진) | Content | Production | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-E-308 | 교수법 렌더 어댑터 5종·평가 재료 뱅크 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-309 | 교수 콘텐츠 슬롯 파이프라인(생성→예심→검수) | QA | Production | SUPPORT | S4 루프 미도달 — QA / Admin |
| WM-E-310 | 비유·예시 생성기·결함 검출기 | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Platform |
| WM-E-311 | 독립 다관점 LLM 교차검증 | QA | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-312 | 풀이 경로(SolutionPath) 구조·조회 store | Content | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-313 | 시각화 명세 생성기·품질 채점 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Platform |
| WM-E-314 | 프롬프트 자산 레지스트리 | Versioning | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-315 | 연령별 설명 생성기·언어수준(F7) 결함 검출기 | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Platform |
| WM-E-351 | 동등문제 생성 파이프라인(생성·수용 게이트·정규화·rephrase·감사) | Math Engine | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-352 | 단원별 스켈레톤 생성기 41종(초·중·고·대) | Math Engine | Production | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-E-353 | 기호 동치·해집합 보존 판정 primitive | Math Engine | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-354 | 답 검산(Tier1 수치·형태·최종답) | Math Engine | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-355 | 단계·풀이 연쇄 검증·검증 등급 | Math Engine | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-356 | SymPy 불가 영역 검산(유한확률 전수·통계 자료형) | Math Engine | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-357 | 다중 풀이법 생성(접근법 6종) | Math Engine | Production | SUPPORT | S4 루프 미도달 — Math Engine / Platform |
| WM-E-358 | 표기 커버리지 게이트 | Math Engine | **Batch** | SUPPORT | S4 루프 미도달 — Math Engine / Admin |
| WM-E-359 | 수식 낭독(AST→한국어)·역파서·학년별 프로파일 | Math Engine | Production | SUPPORT | S4 루프 미도달 — Math Engine / Student |
| WM-E-401 | Polya 4단계 코칭 엔진·전이 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-402 | 소크라테스 6카테고리 선택 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-403 | LTHC 적응(진입점·확장·비계) | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-404 | 답 미루기 4단계 힌트·정서 안전 톤필터 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-405 | 메타인지·보정·선수복습 코칭 결정 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-406 | 완료 상태머신·턴 메타·세션 회상 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-407 | 풀이 계산오류 → 검산 코칭 오케스트레이터 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-408 | 콘텐츠 공급 경로(DSL 캐시·render-vs-generate) | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-409 | 교수전략 선택기·팩 프롬프트 조립·금지모드 가드 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-410 | 적응 교수법 policy(Thompson sampling·안전제약) | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Student |
| WM-E-411 | 오개념 진단·개입·매칭 게이트·distractor 카탈로그 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-412 | 활성 오개념 가설·프로브 선택·웜스타트·증거 저장 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-413 | 오개념 의미(임베딩) 매칭 + shadow | Pedagogy | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-414 | 오개념 방향 판별 LLM-judge + shadow | Pedagogy | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-415 | 오개념 크로스링크(kebab↔M-id) 후보·트리아지·검수·shadow | Pedagogy | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-416 | 오답 형태 SymPy 매칭(canonical_wrong_form) + shadow | Math Engine | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-417 | 중간 단계 등가성 shadow 관측·평가 | Pedagogy | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-418 | 학습 장면(LearningScene) DSL·생성·시각화 정책 | Interaction | Production | SUPPORT | S4 루프 미도달 — Interaction / Student |
| WM-E-419 | SubjectAdapter 계약 + 수학 구현 | AI Orchestration | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-420 | L4 공용 모델·인터페이스 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-421 | 연령별 설명 공개 진입점(EOS-70 explain 위임 대상) | Pedagogy | Production | SUPPORT | S4 루프 미도달 — Pedagogy / Student |
| WM-E-501 | OCR 파이프라인(검출→라우팅→인식→조립·검증) | Math Engine | **Flag-off** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-E-601 | L6 모드 게이팅 로직 5종(재수·학교진도·사고력·메타인지·영재) | Application Mode | Production | SUPPORT | S4 루프 미도달 — Application Mode / Student |
| WM-E-602 | 수능 모드 게이팅·적응 추천(게이팅×IRT CAT) | Recommendation | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-603 | 평가 청사진 테스트셋 조립 | Assessment | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-701 | WH-S 솔버 하네스(루프·판정·저장소·코퍼스 replay) | Math Engine | Production | **FUTURE** | F1 horizon=P3 선언(장기 연구/플랫폼) — 좌석: 03b 설계 — 솔버 자기진화 플랫폼(PRM 라벨 공급) — 12월 폐쇄 |
| WM-E-702 | WH-S 자기진화(PRM·SFT 학습셋 export) | Math Engine | **Batch** | **FUTURE** | F1 horizon=P3 선언(장기 연구/플랫폼) — 좌석: 설계 §5 — 2027 학습 파이프라인(PRM·SFT) — 장기 연구 |
| WM-E-703 | bank_solution → SolutionPath 승격 writer | Content | **Batch** | **LOOP** | L5 루프가 읽는 테이블의 (유일) writer — 데이터 없으면 루프가 빈 화면 |
| WM-E-704 | WH-1 튜터링 하네스(턴 루프·LLM 정책·프로즈·프로브 공급) | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-705 | WH-1 shadow 관측·수확·2단계 종료 게이트 | QA | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-706 | 성장 증거 대리지표 7종·노출 계약·베이스라인 | Pedagogy | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-801 | Pydantic 계약 스키마(문항·활동·이벤트·권리 등 40종) | Versioning | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-802 | ORM 모델 54종·세션·스키마 버전·alembic | Versioning | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-803 | 인증·인가·암호화·레이트리밋·동시성 배관 | Security | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-804 | OAuth 제공자 구현(카카오·네이버 httpx) | Identity | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-805 | 동의 절차(14세 미만·동의 부여) | Security | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-806 | 디바이스 저장소·서명 실패 metric | Security | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-807 | 앱 조립·합성 루트·설정·app.state 배관 | Operations | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-808 | 한국어 조사 유틸 | Content | Production | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-E-809 | 데모 인증(시연 전용 가짜 OAuth provider) | Identity | **Flag-off** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |

### O 운영자 도구 — 14행 (LOOP 1 · SUPPORT 13 · FUTURE 0)

| ID | 기능 | 도메인 | 상태 | §14 | 판정 근거 |
|---|---|---|---|---|---|
| WM-O-901 | 개인정보 삭제권·이동권·PEP·감사 writer | Security | Production | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-O-902 | PII 보존기한 파기·대화·학생답안 봉투 암호화 백필 | Security | **Batch** | SUPPORT | S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수 |
| WM-O-903 | 서비스 헬스 딥체크·프리플라이트·DB 도달성 진단·로그 스크러버 | Operations | Production | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-904 | LLM 비용 프로브·비용 리포트 | Analytics | **Batch** | SUPPORT | S4 루프 미도달 — Analytics / Admin |
| WM-O-905 | 12월 검증 스코어카드·QA 혼동행렬·HIT/CU 계측 | QA | **Batch** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-906 | 콘텐츠 출처·라이선스 감사 게이트·사이드카 | Content | **Batch** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-907 | 선언≠배선 감사·추천/슬롯 도달 리포트·Phase 1 구조 지표 | QA | **Batch** | SUPPORT | S4 루프 미도달 — QA / Admin |
| WM-O-908 | 운영자 계정 부트스트랩·역할 좌석·shadow 합성 트래픽 | Operations | **Batch** | SUPPORT | S4 루프 미도달 — Operations / Admin |
| WM-O-909 | 동등문제 코퍼스 축적·후처리 배치(36 단원 배치 포함) | Content | **Batch** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-910 | 검수 워크플로(HIT 타이머·검수 세션·워크리스트·표본 패키지) | QA | **Batch** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-911 | 골든 벤치마크 승격·경로 게이트·앵커 회차 대장 | QA | **Batch** | SUPPORT | S2 앵커 생산 루프만 도달 — 학생 루프 아님 |
| WM-O-912 | QA 파이프라인·강등전 게이트(Wilson·결함주입·금칙어) | QA | **Batch** | **LOOP** | L4 학생 루프 씨앗에서 import 도달 |
| WM-O-913 | 커버리지·도달률 관측 리포트 가족 | Analytics | **Batch** | SUPPORT | S4 루프 미도달 — Analytics / Admin |
| WM-O-914 | 데이터 무결성 게이트(orphan·dangling·duplicate 6종) | QA | **Batch** | SUPPORT | S4 루프 미도달 — QA / Admin |

### C 클라이언트 — 12행 (LOOP 9 · SUPPORT 3 · FUTURE 0)

| ID | 기능 | 도메인 | 상태 | §14 | 판정 근거 |
|---|---|---|---|---|---|
| WM-C-001 | 로그인·계정 보안 화면·토큰 배관 | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-002 | 온보딩(학년·학교유형·목표) | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-003 | 홈·탭 셸·라우팅 | Client UX | Production | **LOOP** | L2 loop_seed 선언(import 그래프 밖 진입점) |
| WM-C-004 | 코치 채팅(턴·단계 패널·완료 신호) | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-005 | MathLive 수식 입력(WebView 임베드) | Client UX | Production | **LOOP** | L2 loop_seed 선언(import 그래프 밖 진입점) |
| WM-C-006 | 학습 장면·풀이 경로 렌더러 | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-007 | 그래핑 계산기(React WebView 임베드) | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-008 | 진단·문제 풀기 화면 | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-009 | 손글씨 촬영·OCR 캡처 | Client UX | **Flag-off** | SUPPORT | S4 루프 미도달 — Client UX / Student |
| WM-C-010 | 나(프로필)·성장 증거 탭 | Client UX | Production | **LOOP** | L3 클라이언트 소스에 루프 라우트 리터럴 존재 |
| WM-C-011 | 탐구(Explore) 탭 | Client UX | Production | SUPPORT | S4 루프 미도달 — Client UX / Student |
| WM-C-012 | 결함 신고 버튼 | Client UX | Production | SUPPORT | S4 루프 미도달 — Client UX / Student |

---

## 부록 A. 재현 — 3분류기 전문

본 감사는 **조사 전용**이므로 `scripts/` 아래에 코드를 남기지 않았다(CI 표면 미추가).
아래를 그대로 저장해 실행하면 §3·§10의 표가 재생산된다. 모집단 장부는 `.gitignore` 대상이므로
(`OPS-76`) 먼저 §1-1의 생성 명령을 돌려야 한다.

```bash
git fetch --unshallow origin && git checkout c4f8c9fb
python3 scripts/analysis/eos_feature_inventory_v2.py --write   # 장부 재생성
python3 /경로/classify.py                                       # 아래 전문
```

```python
"""계획서 300 §14 — LOOP / SUPPORT / FUTURE 3분류기 (조사 전용·EOS-16).

모집단: EOS-83 기계 장부 `backlog/inventory/feature_inventory_v2.yaml` (166행).
분류 축은 기존 EOS Ownership·Migration Action·release_priority와 **직교**한다.
"""

import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # 저장소 루트로 조정한다
sys.path.insert(0, str(ROOT / "scripts" / "analysis"))
OUT = "classified.json"   # 재현 시 원하는 출력 경로로 바꾼다
import eos_feature_inventory_v2 as G  # noqa: E402

SPEC = {s.fid: s for s in G.CATALOG}
STU = G.STUDENT_LOOP_ROUTES
PRD = G.PRODUCTION_LOOP_ROUTES

rows = yaml.safe_load((ROOT / "backlog/inventory/feature_inventory_v2.yaml").read_text())["features"]

# §14 FUTURE 7종 / §15 동결 13종 — 키워드로 전수 재확인(존재하면 FUTURE 확정)
FREEZE_PAT = (
    "digital_twin", "디지털 트윈", "virtual_learning", "가상 학습",
    "growth_path_predict", "성장 경로 예측", "auto_refactor", "자동 콘텐츠 리팩",
    "researcher", "연구자 협업", "teacher_collab", "교사 협업",
    "agent_framework", "multi_agent", "graph_centrality", "pagerank",
    "auto_pedagogy", "자동 교수법", "ab_test", "experiment_arm",
)


def classify(r):
    fid = r["feature_id"]
    s = SPEC[fid]
    h = r["loop_hits"]
    blob = (r["name"] + " " + r.get("seat", "") + " " + r["location"]).lower()

    # ── FUTURE (1순위) ────────────────────────────────────────────────
    if s.horizon == "P3":
        return "FUTURE", f"F1 horizon=P3 선언(장기 연구/플랫폼) — 좌석: {r['seat'][:40]}"
    for kw in FREEZE_PAT:
        if kw.lower() in blob:
            return "FUTURE", f"F2 §14 FUTURE/§15 동결 키워드 일치: {kw}"

    # ── LOOP: 학생 폐쇄루프 도달 ─────────────────────────────────────
    if s.plane == "S":
        hit_stu = sorted(rt for rt in s.routes if (s.router, rt) in STU)
        hit_prd = sorted(rt for rt in s.routes if (s.router, rt) in PRD)
        if hit_stu:
            return "LOOP", f"L1 학생 루프 씨앗 라우트 {len(hit_stu)}건: {', '.join(hit_stu[:3])}"
        if hit_prd:
            return "SUPPORT", f"S1 앵커 생산 루프 씨앗 {len(hit_prd)}건 — 학생 루프 아님: {', '.join(hit_prd)}"
    else:
        if h.get("seed_declared"):
            return "LOOP", "L2 loop_seed 선언(import 그래프 밖 진입점)"
        if h.get("seed_route"):
            return "LOOP", "L3 클라이언트 소스에 루프 라우트 리터럴 존재"
        if h.get("student_loop"):
            return "LOOP", "L4 학생 루프 씨앗에서 import 도달"
        if h.get("data_supplier"):
            return "LOOP", "L5 루프가 읽는 테이블의 (유일) writer — 데이터 없으면 루프가 빈 화면"
        if h.get("production_loop"):
            return "SUPPORT", "S2 앵커 생산 루프만 도달 — 학생 루프 아님"

    if h.get("invariant"):
        return "SUPPORT", "S3 불변 계약(PII·저작권·추적·인증) — 루프와 직교하나 법적 필수"
    return "SUPPORT", f"S4 루프 미도달 — {r['domain']} / {r['user']}"


out = []
for r in rows:
    cls, basis = classify(r)
    out.append({**r, "loop_class": cls, "loop_class_basis": basis})

import collections, json
print("총계:", collections.Counter(o["loop_class"] for o in out))
print("평면×분류:", collections.Counter((o["plane"], o["loop_class"]) for o in out))
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
```

§2-1의 주입 시험 하네스는 이 모듈을 import해 `SPEC`(frozen dataclass는 `dataclasses.replace`로)과
행 dict를 변형한 뒤 `classify()`를 다시 부르고, **주입 적용 여부(`mutated != original`)와 원복을
각각 단언**한다. 주입이 조용히 실패하면 정상 파일에 대해 시험이 돌아 "검출"처럼 보이기 때문이다
(CLAUDE.md "주입 자체의 실재").
