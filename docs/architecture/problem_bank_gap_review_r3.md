# 문제은행(Problem Bank) 모듈 — 외부 EOS 틀 **3차 대조**(R3) 갭 점검·설계 (2026-08-11)

> **범위**: 외부 참고 문서 『0단계 — 문제은행』(기능 18 문제 DB · 19 난이도 관리 · 20 유형
> 관리 · 21 자동 문제 생성 · 22 변형문제 생성 — **WhyMath 전용이 아닌 일반적 EOS 틀**,
> Kiki 제공)의 **3차 대조**. 1차 `problem_bank_gap_review.md`(2026-07-28 · D1~D9 · 태스크
> 8건) · 2차 `problem_bank_gap_review_r2.md`(2026-08-03 · R1~R7 · `PB-01`~`PB-04`)가 이미
> 존재하므로, 이 문서는 **① R2 판정의 8일 후 재판정 ② R1·R2가 보지 않은 축의 설계**만 담는다.
> 1·2차 문서는 **덮어쓰지 않는다**(이력 보존 — 그 시리즈 자신의 관례).
> **형식**: `gamification_module_gap_review_r2.md`(2026-08-04) 답습 — 같은 모듈의 **첫 3차 대조**.
>
> **결론**: 착수 가설이 또 한 번 뒤집혔다. R2는 "선언과 배선이 벌어져 있다"였다. R3의 실측은
> **① R2가 지적한 축에는 설계로 더 할 일이 없다** — 7건 중 4건 해소, 남은 3건은 전부 *설계
> 갭이 아니라 머지·인플라이트*다(§1). 그리고 **② 훨씬 큰 것이 시야 밖에 있었다** — 문제은행
> 저작이 **main 코퍼스의 4.3배 규모(11,446문·30코퍼스)로 이미 실행됐고 main도 백로그도 그
> 사실을 모른다**(§3 G1). R2가 §3 R7에서 *"소비처가 잠겨 있어 저작 큐는 페이퍼로만"* 이라고
> 판단한 바로 그 저작이다. 미병합 고립 **4회차**이며, 이번 회차의 신규 사실은 "감지 실패"가
> 아니라 **감지된 고립을 회수로 잇는 경로가 없다**는 것이다(`HARN-13` 감지기는 정상 작동한다).
> 진짜 갭 7건(G1~G7)을 설계하고 실행 5건을 신규 등재했다. 정본 stale 5곳을 실측으로 정정한다.

관련 정본: `problem_bank_gap_review.md`(1차 — D1~D9 설계 원문) ·
`problem_bank_gap_review_r2.md`(2차 — 선언≠배선 7건·R1~R7) ·
`03_content_generation.md`(L3 생성) · `docs/standards/superhuman_verification_standard.md`(검증 6축) ·
`docs/data/problem_type_graph_v1.md`(유형 17종) · `docs/data/licensing_safety.md`(저작권) ·
`MEMORY.md` 결정 로그(2026-08-11).

**실측 기준**: HEAD `959ec4ad` · 2026-08-11. 재현 명령은 §부록.

---

## §0. 재점검 사유 — 왜 R2를 덮어쓰지 않고 R3를 새로 쓰는가

### ① 동일 문서 3회차임을 수치로 확정한다 (추론 아님)

첨부 문서의 본문 구조는 1·2차가 대조한 것과 같다 — 기능 18~22, 개발 우선순위 제안
(18 → 20 → 21 → 22 → 19), "WhyMath 전체 흐름" 다이어그램. 1차 문서 서두가 인용한 항목 목록
(문제 ID·본문·정답·해설·풀이 과정·성취기준·난이도 8축·유형 10종·생성 4방식·변형 6방식)과
**항목 단위로 일치**한다. 즉 새 요구가 추가된 재제출이 아니라 **같은 틀의 3회차 대조**다.

따라서 R3는 기능 18~22를 처음부터 다시 판정하지 않는다. **§2에서 바뀐 칸만** 기록한다.

### ② R2를 in-place 수정하지 않는 이유

R2 §0-①이 밝힌 그대로다 — 판정의 *시점*이 정보다. "2026-08-03에는 이렇게 보였고 8일 뒤에는
이렇게 되었다"가 이 프로젝트의 반복 실수(미병합 고립·선언≠배선)를 진단하는 유일한 재료이며,
R2를 고쳐 쓰면 그 재료가 사라진다. R2 본문은 그대로 두고 여기에 Δ만 적는다.

### ③ 승계 선언 — 재판정하지 않는 것

아래는 R1·R2의 판정을 **그대로 승계**하며 이 문서에서 재논증하지 않는다.

- **1차 §2 의도적 미채택 6건**(기출 수집형 출처 관리 · per-문항 버전 필드 · "사람이 봤는가"식
  검수 · 난이도 8축 신규 필드 증설 · 문제↔유형 즉시 연결 · 독립 Problem Template DSL)
  + **R2 §2 신규 미채택 1건**(`review_status`의 수동 운용) — **전부 승계**.
- **1차 §5 유보 ①**(Problem↔Formula) **②**(`achievement_standard_codes` 영속화) — 발화 조건 불변.
  **③**(문제↔유형 연결)은 2026-07-30 부기로 이미 해제(`S3-27`). **④만 재평가**한다(§5).
- **R2 §4 정직한 공백 8건** — killer 표본 min-n 미달, `probability_finite_v0` 노출 잠금,
  실응답 통계, 초·중 커버리지 *실행*, L6 모드별 UX, 정서 표현 검사, `equivalence_canonicalize`
  130건, 다중 풀이 — 승계처가 바뀐 것만 §4에 적는다.

---

## §1. R2 판정의 Δ — "선언≠배선 7건"의 8일 후

R2 §0-②의 7건을 그대로 재측정했다. **4건 해소 · 3건 미해소**이며, **미해소 3건은 전부 설계
갭이 아니다.**

| # | R2 갭 (2026-08-03) | 2026-08-11 | 근거 |
|---|---|---|---|
| **다** | 기본 CAT이 저작권 게이트 우회 — `is_exposable` 호출자에 `api/me.py` 0건 | ✅ **해소** | `api/me.py:2218-2225` — `Problem.source_type.notin_([s.value for s in METADATA_ONLY_SOURCES])`. 수능 분기와 **동일 상수 재사용**(R2 R4-⑴ 설계대로) |
| **라** | "노출 4단"의 3단(검수)이 코드에 없음 · `review_status` 실측 None 2,647/2,647 | ✅ **해소** | `l6/_shared.py:165` `is_review_cleared` **별도 함수로** 신설(법적 축과 미병합 — R2 R4-⑵ 설계대로) · 코퍼스 실측 **approved 2,489 / pending 158** |
| **마** | `_CANDIDATE_FETCH_LIMIT = 1000` < 2,647 → 1,647문 후보 불가 | ✅ **해소** | `api/gating.py:76` **3000** + 절단 발생 시 warning 관측(`:105-112`). 현 코퍼스 2,647 < 3000이라 절단 0 |
| **사** | 문항 본문 금칙어·PII 검사 0 | ✅ **해소** | `ARCH-24` done — `qa_pipeline` 8번째 축 |
| **가** | S6 야간 재검증이 3/7 코퍼스만 배선(1,478문 55.8% 미배선) | 🔴 미해소 — **설계 갭 아님** | main `ci.yml:1186-1189` 하드코딩 3파일 유지. **완료본이 열린 PR #739**에 있고 글롭 전환(`problem_bank_*/problems.jsonl`)이 실물로 확인됨 |
| **바** | `problem_bank_coverage` CI 미배선 · 리포트 stale | 🔴 미해소 — 동상 | 같은 `PB-02`·같은 PR #739 |
| **나** | L6 응용 모드 6종 학생 도달 0회 | 🔴 미해소 — **다른 세션 인플라이트** | `PB-04` done in `claude/whymath-issues-review-k20m0w`(2026-08-11 커밋 · `api/gating.py`+`api/me.py` +147/−46) |

R1 D1~D9의 잔여도 정리됐다: `PB-01`(D1·D3·D5 회수) done → **`persona_fit` 0 → 2,647/2,647**,
`S4-14`+`S4-18`(D8 계보) done → **계보 실적재 1,024건**(generated 595 · rephrased 429), 그리고
그 계보를 소비하는 CAT 형제 필터가 `api/me.py:1807`에 착지했다.

> **R3의 첫 결론**: R2가 연 축은 **전부 닫혔거나 닫히는 중**이다. 남은 3건에 대해 R3가 할 일은
> 재설계가 아니라 **중복 착수를 금지하는 것**이다(§4 대장). 진짜 갭은 다른 곳에 있었다.

---

## §2. 기능 18~22 재대조 — R2 대비 Δ만

전면 재작성하지 않는다. 1차 §1의 판정표가 여전히 골격이고, R2가 갱신한 칸 위에 **다시 바뀐 칸만** 적는다.

### 기능 18. 문제 DB — 검수 축 집행 완료 · **영속 비대칭**이 새로 드러남

| 항목 | R2 판정 | R3 Δ |
|---|---|---|
| 검수 상태 | ⚠️ 집행이 새 갭(R4) | ✅ **집행 착지** — 단 **노출 경로 하나가 계약 밖**(`GET /v1/problems`) → **G3** |
| 추천 대상(`persona_fit`) | ⚠️ 0/2,647 | ✅ **해소** — 2,647/2,647 |
| 출처·저작권 | ⚠️ 주 노출 경로 미배선 | ✅ **해소**(주 경로 배선) — 단 `license`는 **DB에 영속되지 않는다**(provenance 미적재) → **G6**(재논쟁 없음·기록만) |
| 풀이 과정(단계별) | (1차 ✅ — `problem_step` 좌석 실재) | ⚠️ **판정 정정** — `problem_step` 테이블·조회 API(`api/problems.py:127`)는 있으나 **writer 0건**. 코퍼스 `verify.solution_steps` 1,049건이 DB에 안 들어간다 → **G7**(`S4-09`/`S4-10` 승계) |

### 기능 19. 문제 난이도 관리 — 잠금의 성격이 바뀌었다

R1·R2는 "실학생 응답 0이라 `S4-15` 정상 잠금"으로 판정했다. R3 실측이 한 겹 더 드러낸다 —
**응답이 생겨도 루프는 자동으로 돌지 않는다.** `l2/calibrate_items.py`의 호출자가 저장소 어디에도
없다(§3 G4). 즉 이것은 *데이터 잠금*이 아니라 *배선 공백*이며, 성격이 다르므로 별도로 다룬다.

### 기능 20. 문제 유형 관리 — 429건 구멍의 **사유가 소멸했다**

R2는 429건 미태깅의 사유를 *"S4-14 미착지"* 로 기록했다. `S4-14`는 2026-08-05 done이고
rephrased 429건은 **전건 계보를 갖는다**. 그런데 제외는 코드에 그대로 남아 유형 태깅은
여전히 **2,218/2,647(83.8%)** 이다 → **G2**.

### 기능 21. 자동 문제 생성 — 커버리지 판정이 **통째로 무효**가 됐다

R2 §0-③의 수치(성취기준 72/435 · 초등 5/121 · 0커버 25영역)는 **main 기준으로는 여전히 정확**
하지만, 그 수치를 근거로 한 *"저작 큐를 만들면 입력 없는 파이프라인"* 이라는 R7 판단은
**사실과 다르다** — 저작은 이미 대량 실행됐다(§3 G1). 방식 축(①템플릿 ②개념 ③LLM ④DSL=①에 흡수
⑤확률 유한 전수형)은 불변.

### 기능 22. 변형문제 생성 — **유보 ④의 발화 조건이 충족됐다**

R2 §5가 *"절반 성립 — 미성립은 D8뿐"* 으로 판정한 그 D8이 착지했고, 판정 잠금이던 사람 게이트도
철회됐다. 즉 **6일째 발화 상태로 방치**돼 있다 → **G5**. 현행 6종 실측: 숫자변형 ⚠️(독립 생성이라
계보 없음) · 문맥변형 ✅(rephrase 429) · 오답유도형 ✅(misconception_mc 1,080) ·
**조건변형 ❌ · 난이도 계열변형 ❌ · 역문제 ❌**.

---

## §3. 진짜 갭 G1~G7 — 설계

우선순위 논리: **회수 조건(G1) → 제외 만료(G2) → 노출 계약(G3) → 변형 발화(G5) → 난이도 배선(G4)**,
그리고 **설계는 하되 태스크는 만들지 않는 것(G6·G7)**.

### G1. 저작 확장 11,446문이 main에 0건 — 미병합 고립 **4회차** · 규모 **4.3배** 🔴 최우선

`origin/claude/whymath-mvp-plan-architecture-trjg5x` — 2026-08-09 마지막 커밋 · trunk 대비
**111커밋** · **열린 PR 없음**(2026-08-11 GitHub API 실측).

| 축 | 브랜치 | main | 차이 |
|---|---:|---:|---|
| 문제은행 코퍼스 | **37종 14,093문** | 7종 2,647문 | **+30종 11,446문** |
| 결정론 생성기 파일 | 35개 신규 | 0 | +35 |
| 저작 태스크 `S4-30`~`S4-51` | 22건 | **0건** | 백로그에 **등재조차 안 됨** |
| 고유 성취기준 코드 | (신규분) **55개** | 78개 | **교집합 0** — 합집합 133 |

신규 30종은 R2 §0-③이 실측한 공백을 정확히 겨눈다:

- **초등**(R2 실측 5/121 = 4.1%): `elementary_gcd_lcm` 600 · `elementary_rounding` 600 ·
  `elementary_division_remainder` 400 · `elementary_area_measure` 270 ·
  `elementary_volume_measure` 300 · `elementary_v0` 400 · `measurement_unit_conversion` 180
- **0커버 영역 25개 중 확률·통계 계열**: `probability_law` 724 · `binomial_distribution` 300 ·
  `sample_mean_distribution` 400 · `discrete_ev` 200 · `permutation_combination` 160 ·
  `combination_binomial` 121
- **0커버 적분 계열**: `calculus1_integral` 400 · `calculus2_trig_integral` 130 ·
  `highschool_quotient_rule` 200
- 기타: `polynomial_arithmetic` 1,500 · `complex_number_arithmetic` 900 ·
  `linear_inequality_system` 600 · `polynomial_factoring` 600 · `coordinate_geometry` 400 ·
  `vector_operations` 400 · `matrix_ops` 320 · 대학 미적분 2종 600 등

**즉 R2 §3 R7이 "소비처(`S4-01`)가 `S3-01` 잠금이라 지금 저작 큐를 만들면 입력 없는 파이프라인"
이라고 판단한 그 저작이, 판단과 같은 주에 이미 대량 실행되고 있었다.** 브랜치에서도 `S4-01`은
`todo`다 — 저작은 `S4-30`~`S4-51`이라는 **다른 좌석**으로 진행됐고, 그 좌석 자체가 main 백로그에
없어 R2의 시야에 잡히지 않았다.

**이것은 미병합 고립 4회차다.** 3회차(R2 §6-ⓐ) 대책으로 `HARN-13`(코드 감지)이 등재·착지했고,
**감지기는 정상 작동한다** — `backlog.py next`가 이 브랜치를 경고로 뱉는다. 4회차의 신규 사실은
따라서 "감지 실패"가 아니다:

> **감지된 고립을 회수로 잇는 경로가 없다.** 경고는 매 세션 출력되지만, 그 경고를 받은 세션이
> 할 수 있는 행동이 정의돼 있지 않다. 그래서 경고는 습관화되고 — CLAUDE.md가 금지한
> *"상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰"* 의 관측 축 변형이 된다.

#### 회수 전 충족해야 할 차단 조건 2건 (실측)

**⑴ `_provenance.json` 사이드카가 신규 30종 전부 부재.** 브랜치 전체에서 사이드카는 7개
(기존 코퍼스분)뿐이다. `ARCH-25`가 `ops/provenance_audit.py`의 `_KNOWN_GAPS`를 **빈 dict로
비워** 그랜드파더 면제를 0으로 만들었으므로 — 사이드카 없이 회수하면 **상시 CI**
(`ci.yml:301-302`)가 즉시 red다. 이것은 결함이 아니라 **계약이 설계대로 작동하는 것**이며,
회수의 선결 조건이 무엇인지를 정확히 말해준다.

**⑵ 커버리지 효과가 어디에도 측정돼 있지 않다.** `docs/data/problem_bank_coverage_2026-07.json`은
**브랜치·main 양쪽 모두** `total_problems: 2667 · 코퍼스 6 · 커버 코드 72`로 동일하게 stale이다.
즉 11,446문을 저작한 브랜치조차 자기 저작의 커버리지 효과를 모른다. 위 표의 "고유 코드 +55·
교집합 0"은 R3가 이번에 직접 센 값이며(§부록), **대장(2022 개정 435) 대조는 하지 않았다** —
그것은 회수 태스크의 산출물이다.

#### 설계 (신규 태스크 `PB-06`)

- **회수 자체는 이 태스크가 하지 않는다.** 병합 판단은 Kiki 소유다(장기 미머지 브랜치 결정 관례).
  이 태스크가 확정하는 것은 *회수하려면 무엇이 충족돼야 하는가*이며, 산출물은 **결정 입력**이다.
- ⑴ 실측 대장 고정 — 30종 11,446문 · 생성기 35 · 태스크 22건을 코퍼스별 건수·성취기준 코드까지
  표로. 추론 0 · `git show` 재현 명령 병기.
- ⑵ **차단 조건 변별력 실측** — 사이드카 없는 코퍼스를 넣었을 때 `ops/provenance_audit`가 실제로
  red를 내는지, 사이드카를 붙이면 green이 되는지 **양쪽 다** 확인한다. 성공·실패 양쪽에서 같은
  값을 내는 검사는 검증이 아니라 위장이다(CLAUDE.md 금기).
- ⑶ 사이드카 생성 경로 조사 — 기존 CLI가 있으면 그것을 지목하고, 없으면 **부재를 별도 태스크로
  분리 등재**한다(여기서 만들지 않는다 — 범위 폭발 방지).
- ⑷ **커버리지 델타 산정** — 브랜치 코퍼스에 `harness/problem_bank_coverage.py`를 돌려 회수 시
  성취기준 커버(72/435 → ?)·학교급별·0커버 영역 감소를 수치로 낸다. 이것이 Kiki 결정의 유일한
  정량 입력이다.
- ⑸ **스코프 밖 명시** — 병합·충돌 해소·품질 재감사·문항 내용 검수. `PB-02`의 커버리지 CI 축과
  파일이 겹치지 않게 분리한다(PR #739 대기 중).

### G2. 유형 태깅 429건 제외 — 사유가 소멸했는데 제외가 코드에 남아 있다

`harness/problem_type_backfill.py:12-13` 원문:

> `problem_bank_rephrased_v0`(429건)는 여기 없다 — **`S4-14`(변형 계보 영속) 미착지**로 원
> 생성기를 추적할 수 없어 **명시 제외**한다.

- `S4-14` = **done**(2026-08-05 · artifact `be8953c4`) · `S4-18`도 done.
- rephrased 429건은 **전건 `relations` 보유**(§부록 실측) — 원 생성기 추적이 가능해졌다.
- 그런데 `harness/problem_type_mapping.py:141`
  `EXCLUDED_CORPORA: frozenset[str] = frozenset({CORPUS_REPHRASED_V0})` 는 그대로다.
  유형 태깅 **2,218/2,647(83.8%)** · rephrased **0/429**.

**이는 CLAUDE.md 금기 "만료 없는 유예·제외 금지"(2026-08-03 등재)의 2회차다.** 1회차 대책인
`ARCH-25`는 만료 계약을 *코드로* 착지시켰다 — 그러나 그 계약은 `provenance_audit._KNOWN_GAPS`
**한 좌석에만** 걸려 있고, 같은 성격의 다른 좌석(`EXCLUDED_CORPORA`)은 계약 밖이다.
CLAUDE.md가 *"1차 집행은 규칙 산문이 아니라 코드다"* 라고 적은 그 코드가 **좌석 단위로만**
존재하는 상태다.

#### 설계 (신규 태스크 `PB-07`)

- ⑴ 제외 사유 소멸을 실측 확정하고 rephrased 429건 백필 → 유형 태깅 **2,647/2,647**.
  백필은 기존 계약 준수(생성기 identity 매핑표·LLM 0·바이트 결정론·2회 실행 동일).
  계보를 통한 원 생성기 추적이 실제로 되는지 먼저 확인하고, 안 되는 잔여가 있으면 **건수를
  리포트에 남긴다**(침묵 누락 금지 — 그 CLI의 기존 관례).
- ⑵ **일반화가 본체다** — `ARCH-25`의 만료 계약(항목 값이 추적 태스크 ID를 필수 포함 + 그
  태스크가 done인데 항목이 남아 있으면 테스트 red)을 `EXCLUDED_CORPORA` 좌석에도 적용한다.
  자동 해제는 아니다(면제 해제는 사람 판단) — **방치만 구조적으로 막는다**.
- ⑶ 변별력 의무 — 존재하지 않는 태스크 ID · done 태스크 잔존, **두 경우 모두** red 실측.

### G3. 공개 카탈로그가 노출 계약을 경유하지 않는다 — "정본화≠집행" 재발

`PB-03`이 노출 계약을 신설했고 L6 6모드·기본 CAT은 전부 경유한다. 그런데
`api/problems.py:107-124`:

```python
@router.get("", response_model=list[ProblemSchema], summary="문제 목록")
async def list_problems(...):
    stmt = select(Problem)
    if subject is not None:
        stmt = stmt.where(Problem.subject == subject)
```

`review_status` · `source_type` · `is_published` — **어느 조건도 없다.** 단건
`GET /v1/problems/{id}`(`:81`)도 같다. 결과:

- `review_status=pending` **158건**이 이 경로로는 열람된다. 그중 `probability_finite_v0` 34문은
  `S4-16` 강등전 통과 전까지 **노출 부적격**으로 R2 §4가 명시한 문항이고, `killer_v0` 120문은
  표본 크기 구조적 미달(120 < min-n 200)로 검수 판정이 유예된 문항이다.
- `answer` · `answer_explanation`이 그대로 반환된다. 방어는 **서버가 아니라 클라**에 있다 —
  Flutter `problem_models.dart:11-16`이 정답 필드를 *아예 선언하지 않는* 방식으로 구조적 차단을
  하고 있고, 그 주석 자신이 *"학생 대면 answer 비노출은 코치/verify 계층의 불변식이지 이
  CRUD-read에서 강제되지 않는다"* 고 정직하게 적어 두었다.

> **무인증 자체는 재논쟁하지 않는다.** `account_security_gap_review.md:222`가 GET 무인증을
> "공개 카탈로그"로 의도 결정했고 `tests/backend/api/test_problems.py:480-490`이 회귀 3건으로
> 동결했다. R3가 여는 것은 **검수 축과 정답 축**이다 — *누가 보는가*가 아니라 *무엇이 보이는가*.
>
> 그 결정이 내려진 시점에 `review_status`는 전건 `None`이었다. 검수 축이라는 개념이 런타임에
> 존재하지 않았으므로, 그 결정은 검수 축을 판단한 적이 없다. 계약이 생긴 지금, 노출 경로 하나가
> 계약 밖에 남아 있는 것이다 — CLAUDE.md 금기 *"정본화를 집행으로 착각한 완료 선언 금지"*
> (`PED-06` 선례)의 동일 형태. 그리고 정답 축은 **의사결정 우선순위 #1(학생 안전)**과 절대금기
> *"막혔을 때 바로 정답 제공 금지"* 에 걸리는데, 그 방어가 **클라이언트 단독**이면 클라가 하나
> 늘 때마다(웹·PDF·AI 소비자) 재발한다.

#### 설계 (신규 태스크 `PB-08`)

- ⑴ `list_problems`·`get_problem`에 **기본 CAT과 동일 상수 재사용**으로
  `review_status == approved` + `source_type.notin_(METADATA_ONLY_SOURCES)` 부착
  (`api/me.py:2218-2225`와 같은 상수). 판정 기준이 둘로 갈리지 않게 하는 것이 요건이다.
- ⑵ **무인증은 건드리지 않는다** — `test_problems.py:480-490` 회귀 3건은 그대로 green이어야 한다
  (봉인 범위 과확대 방지 — 그 테스트가 명시한 의도).
- ⑶ **정답 축은 결정을 별항으로 적는다** — 이 CRUD-read 응답에서 `answer`·`answer_explanation`을
  서버가 제외할지, 아니면 인증 축으로 분리할지를 **결정하고 그 결정을 테스트로 동결**한다.
  acceptance에 ①계약 ②집행 지점(어느 서빙 경로가 그 계약을 부르는가)을 **분리해** 적는다
  (CLAUDE.md 금기 — 정본화≠집행).
- ⑷ 변별력 실측 — pending 문항 1건·메타전용 출처 행 1건을 주입해 목록·단건 **양쪽에서** 실제로
  빠지는지 확인.

### G4. 난이도 갱신 루프 — 데이터 잠금이 아니라 **호출자 부재**

R1·R2는 기능 19를 "실학생 응답 0이라 `S4-15` 정상 잠금"으로 판정했다. 실측이 한 겹 더 드러낸다.

`l2/calibrate_items.py` 헤더가 스스로 적는다:

> 이 명령이 없으면 `irt_difficulty_b`는 전량 NULL로 남아 보정이 **휴면**한다(θ 추정이 휴리스틱
> 폴백). **ops가 cron·k8s CronJob으로 주기 실행한다**(예: 매일 02:00). … 스케줄은 *외부*
> (cron/CronJob) 책임 — 이 명령은 1회 실행한다.

그런데 실측:

- **호출자 0건** — `.github/workflows/` · `docker-compose*.yml` · `infra/` 전수 grep 무일치.
  `infra/phaiakes9/systemd/`에는 `whymath-api.service`·`whymath-worker.service`만 있고
  보정 배치 유닛은 없다.
- **정답률·CTT 축은 코드 자체가 없다** — `historical_correct_rate` · `rate_top/mid/low_grade` ·
  `discrimination_D` · `irt_a`는 쓰기 코드 0건(스키마·ORM·마이그레이션·테스트 fixture에만 등장).

즉 스케줄 좌석이 **저장소 밖(ops)으로 위임**됐는데, **그 좌석의 실재를 확인하는 관측이 없다.**
`S3-01` 파일럿이 응답을 만들어도 아무도 그 사실을 모른다. 이것은 잠금이 아니라 미배선이며,
CLAUDE.md **"작동 신호 없는 알고리즘 부착 금지 — 작동한 비율 원칙"** 에 해당한다.

#### 설계 (신규 태스크 `PB-10`)

- ⑴ **관측 먼저**(선례 `VIZ-01`·`NLP-01`·`PB-04` 동형) — `irt_difficulty_b` 채움률 · 마지막 보정
  시각 · 보정 제외 사유(응답 < 5회, `item_calibration.py:27`)를 리포트로. **"휴면 중"이 숫자로
  보이게** 만드는 것이 1단계다.
- ⑵ 스케줄 좌석 결정 — 저장소 안에 배선할지(야간 잡 등), 밖(ops)에 남길지를 **결정하고 기록**한다.
  배선한다면 `tests/infra` 배선 실재성 테스트를 동반한다("저장소에 존재함"과 "돌아감"은 다르다 —
  `OPS-10` 선례). 응답 0행인 현재는 **no-op으로 도는 것이 정상**이며, 그 사실을 로그가 말해야 한다.
- ⑶ 정답률·CTT 변별도 산출은 **`S4-15` 승계**(중복 등재 금지) — 이 태스크는 IRT 축과 관측만.
- ⑷ 스코프 밖 — 5축 세분 난이도 채움(`difficulty.py`가 *"추정 근거 없는 축을 날조하지 않는다"* 고
  명시한 판정 존중) · 난이도 8축 신규 필드 증설(1차 §2-④ 승계).

### G5. 변형 3종 — 유보 ④의 발화 조건이 충족됐다 (조건변형 · 난이도 계열변형 · 역문제)

1차 §5-④ 발화 조건: *"D4 리포트가 특정 밴드 재고 부족을 실측하고, D8 계보 축이 착지해 변형을
**기록할 자리**가 생긴 뒤 — 계보 없는 변형 확대는 G18 재생산"*.

- **D4** — `ARCH-18` done. 재고 부족 실측됨(난이도 사다리 부재 · 유형 9종 0커버 · R2 §0-③).
- **D8** — `S4-14`·`S4-18` done(2026-08-05). 계보 **1,024건 실적재** · 소비처(`api/me.py:1807`
  CAT 형제 필터)까지 착지.
- **판정 잠금이던 사람 게이트** `G-s4-14-variant-identity`는 **등재되지 않았다** — `S4-21`
  (2026-07-29 Kiki 결정)이 선행 해소했음이 병합 시점에 확인돼 철회됐다
  (`backlog/events.ndjson:2111` · `backlog/gates.yaml` 7건에 부재).

**세 조건이 모두 성립했고, 6일째 아무도 발화시키지 않았다.**

현행 6종 실측(코퍼스 전량 `generation_type=FULLY_GENERATED` · `VARIANT_NUMBER`/`VARIANT_STRUCTURE`/
`VARIANT_CONTEXT` 3종 enum 좌석 **실사용 0건**):

| 틀 변형 방식 | 현행 | R3 판정 |
|---|---|---|
| 숫자 변형 | 스켈레톤이 계수 공간을 순회 | ⚠️ 결과적 동등 — **파생이 아니라 독립 생성**이라 계보가 없다 |
| 문맥 변형 | `rephrase.py` 429문 | ✅ |
| 오답 유도형 | `misconception_mc_v0` 1,080 | ✅ (틀보다 앞섬) |
| **조건 변형** | 부재 | 🔴 **발화** |
| **난이도 계열 변형** | 부재 | 🔴 **발화** |
| **역문제 생성** | 부재 | 🔴 **발화** |

#### 설계 (신규 태스크 `PB-09`) — WhyMath 방향 정렬

틀은 변형을 *"반복 학습과 평가를 위한 대량 확장"* 으로 규정한다. WhyMath에서는 다르다 —
제품 정체성이 **"문제은행이 아니라 사고 추적기"**(플레이북 Part 0)이므로, 변형의 목적은
**같은 사고를 다른 각도에서 보게 하는 것**이고 그 각도 차이가 **기록으로 남아야** 한다.
따라서 3종 전부 **계보 필수**(`problem_relation` + `generation_type=VARIANT_*`)로 낳는다.
계보 없는 변형 확대는 금지한다(1차 §5-④ 조건 그대로).

- ⑴ **난이도 계열변형 우선** — R2 §0-③이 실측한 *"한 단원을 인지~숙달로 관통하는 계열이 없다"*
  를 직접 겨냥한다. 기존 스켈레톤 생성기의 파라미터 공간을 밴드 상하로 계열화하고, 같은 뿌리
  문항을 `problem_relation(relation_type=심화/기초)`으로 잇는다. **신규 생성기 신설이 아니라
  기존 생성기의 계열 축 추가** — anti-explosion(붕괴 연쇄 ①·② 방어).
  교수학적 근거: LTHC·Polya의 "더 쉬운 관련 문제를 먼저 풀어라"가 **재고로 존재해야** 성립한다.
- ⑵ **조건 변형은 `verify` 검산 계약이 유지되는 범위에서만** — SymPy 조건식이 변형 후에도
  성립해야 한다. 검증 불가 변형은 만들지 않는다(검증 권위 서열 ①기계 증명). 성립하지 않는
  영역은 정직하게 범위 밖으로 적는다.
- ⑶ **역문제는 v1에서 좁게** — "답 → 문제"의 전면 생성이 아니라, 스켈레톤이 **이미 근을 먼저
  고르고 방정식을 역산하는 구조**(`skeleton_generator.py` 원형)를 **명시적 역문제 좌석으로
  승격**하는 데 그친다. 새 추상 도입 0 — 1차 §2-⑥(독립 Problem Template DSL 미채택)과 정합.
- ⑷ 3종 전부 기존 수용 게이트 5종 · canonical signature dedup · 임베딩 dedup을 그대로 통과해야
  하며, **통과율(=변형이 실제로 작동한 비율)을 리포트에 남긴다** — CLAUDE.md "작동한 비율" 원칙.
  정상 응답 200은 알고리즘이 일했다는 증거가 아니다.
- ⑸ `GenerationType.VARIANT_*` 3종 enum 좌석을 실사용으로 전환 — **신규 필드 0**.
- ⑹ 스코프 밖 — 학생 UX · 변형 노출 정책(형제 문항을 언제 보여줄지는 L6/CAT 축) · 역문제 채점 루브릭.

### G6. 문항 메타 4필드가 DB에 영속되지 않는다 — **기록만 · 태스크 없음**

`db/models/problem.py:295-297`의 `from_schema`가 `mapper.column_attrs`로 매핑 컬럼만 추려
넘긴다. 그 결과 코퍼스가 100% 보유한 4필드가 **적재 시 조용히 드롭**된다:

| 필드 | 코퍼스 | DB | 판정 |
|---|---|---|---|
| `achievement_standard_codes` | 2,647/2,647 | ✗ | **1차 §5-② 의도적 판정** — 런타임 소비는 4단 조인(`api/gating.py:175-186`). 발화 조건 불변 |
| `problem_type_codes` | 2,218/2,647 | ✗ | **`S3-27` acceptance ②가 "관측 축 한정"으로 명시 스코프 밖에 뒀다** — 재논쟁 없음 |
| `license` · `generation_type` | 2,647/2,647 | ✗ | provenance 미적재(`populate.py:215` 자인). **법적 게이트는 `source_type`(영속)으로 작동**하므로 실손실 0 |

**재논쟁하지 않는다.** 다만 정정 1건을 기록한다 — `schema/problem.py:340-341`이
`problem_type_codes`를 *"`signature_patterns` 동형"* 이라 적었으나, **영속 축에서는 동형이 아니다**
(`signature_patterns`는 ORM 컬럼 `db/models/problem.py:157`, `problem_type_codes`는 아님).
소비처가 생길 때 이 비대칭이 "동형이니 당연히 DB에 있겠지"라는 가정을 낳을 수 있다.
§5에 발화 조건으로 남긴다.

### G7. `problem_step` writer 0 — **`S4-09`/`S4-10` 승계 · 태스크 없음**

틀 기능 18의 "풀이 과정"에 대응하는 `problem_step` 테이블(`db/models/problem.py:317-342`)과
조회 API(`api/problems.py:127`)는 실재하나 **생성자 호출이 프로덕션 코드에 0건**이다. 코퍼스의
`verify.solution_steps` 1,049건은 Tier2 검증 재료로만 쓰이고 DB에 들어가지 않는다 —
**상시 빈 응답 API**다(D8 착지 전 `problem_relation`과 같은 형태).

다중 풀이(`S4-09` SolutionPath 물질화 → `S4-10` 다중 풀이 생성)가 이 좌석의 정본 소비처이므로
**승계한다** — 중복 등재 금지. 단 `S4-09`는 다른 브랜치에 완료본이 있다는 감지 경고가 있어
(`claude/whymath-solution-review-40xspg`), **G1의 회수 대장에 함께 올린다**.

---

## §4. 정직한 공백 — 지금 하지 않는 것 (재설계 금지 대장)

| 축 | 사유 | 해소 시점 |
|---|---|---|
| `PB-02` (S6 글롭 · 커버리지 CI 재생성) | **열린 PR #739**에 완료본 — 글롭 전환 실물 확인. 재설계하면 이중 구현 | PR #739 병합 |
| `PB-04` (L6 6모드 도달 관측) | **다른 세션 인플라이트**(`claude/whymath-issues-review-k20m0w` · 오늘 커밋) | 그 세션 |
| `QUAL-02`(실중복 9쌍 판정) · `QUAL-04`(rephrase fail-closed) | 원격 claim 존재 — 세션 브리핑 확인 | 각 세션 |
| `S4-16` (잔여 게이트 강등전) | in_progress · **Kiki 머신 의존**(실 LLM provider). `probability_finite_v0` 34문 노출 승격의 유일 조건 | `S4-16` |
| `S4-01` (K-12 확장 *실행*) | G1의 저작분이 회수되면 이 태스크의 전제 자체가 바뀐다 — **회수 판정 전에 손대지 않는다** | `PB-06` 후 |
| `S4-15` (응답 기반 난이도 루프) | `S3-01` 파일럿 잠금 · 정답률·CTT 축 승계 | `S3-01` 후 |
| `S3-28` (canonicalize 130건) · `ARCH-24` · `ARCH-25` | 기존 추적 / done | — |
| `SEC-18` (prod 표면 하드닝) | `/docs`·CORS 축 — G3(콘텐츠 게이트)와 무관 | 그 세션 |
| killer 표본 min-n 미달 · 정서 표현 검사 · L6 모드별 UX | R2 §4 승계 | 각 조건 |

---

## §5. 유보 항목의 발화 조건 — R1 §5 재평가

| # | 항목 | 이전 조건 | R3 판정 |
|---|---|---|---|
| ① | Problem↔Formula 연결 | Phase 5b · 공식 검색·추천 소비처 실재 시 | **불변**. 단 `NS-04`(formula latex↔dsl 정합 게이트, done)가 선결 품질을 확보했으므로 Phase 5b 착수 시 재료는 준비됨 |
| ② | `achievement_standard_codes` 영속화 | 빌드타임 4단 조인으로 부족한 **런타임** 소비가 실측될 때 | **불변**. 단 4단 조인은 `/v1/gating/school-progress` 전용이고 `next-problem`·`assemble`엔 주입되지 않음을 기록 — 그 경로에서 성취기준 단위 필터 수요가 생기면 그때가 발화 시점 |
| ③ | Problem↔ProblemType 연결 | — | **2026-07-30 해제 완료**(`S3-27`) |
| ④ | 조건 변형 · 난이도 계열 변형 · 역문제 | D4 실측 + D8 계보 착지 | 🔴 **발화** — 세 조건 모두 성립(§3 G5). **`PB-09`로 착수** |
| ⑤ *(신설)* | `problem_type_codes` DB 영속 | 유형 기반 **추천·출제 소비처**가 실재할 때(관측 축을 넘어설 때). 그 전 영속화는 이중 진실 원천 | 신설 — G6의 영속 비대칭 기록과 짝 |

---

## §6. 반복 실수 — 재발방지 등재 (CLAUDE.md 의무)

### ⓐ 미병합 브랜치 고립 — **4회차** (규모 최대)

| 회차 | 사건 | 규모 | 대책 |
|---|---|---|---|
| 1회 | 2026-07-23 규명 | — | MEMORY **텍스트 규칙** |
| 2회 | 2026-07-30 `shadow-data-s3-pilot-nh5kbz` | 70커밋·128파일·9일 | `HARN-13` 등재(코드 감지) |
| 3회 | 2026-08-03 문제은행 R2 — 고립 4건·실피해 4건 | 브랜치 3개 | `PB-01` 회수 + `ARCH-25` 만료 계약 |
| **4회** | **2026-08-11 (본 문서)** — `whymath-mvp-plan-architecture-trjg5x` | **111커밋 · 코퍼스 30종 11,446문 · 생성기 35 · 태스크 22건 미등재 · PR 없음** | **`PB-06`**(회수 조건) |

**4회차가 보여준 새 사실**: `HARN-13` 감지기는 **정상 작동한다** — `backlog.py next`가 이
브랜치를 경고로 출력한다. 실패한 것은 감지가 아니라 **감지 이후**다. 경고를 받은 세션이
취할 행동이 정의돼 있지 않아, 경고는 매 세션 출력되며 습관화된다. 3회차 때 R2가 *"고립은 조용히
썩는 게 아니라 주변 설계에 가정으로 흡수돼 굳는다"* 고 적었는데, 4회차는 한 걸음 더 갔다 —
**고립된 저작이 R2 자신의 판단(R7 "입력 없는 파이프라인")을 사실과 반대로 만들었다.**

→ 대책은 `PB-06`(회수 조건을 코드·측정으로 확정)이며, 그것으로 부족하면 "감지→회수 경로"의 부재를
별도 하네스 태스크로 분리한다. **텍스트 규칙은 이미 2회 실패했으므로 4회차도 텍스트로 끝내지 않는다.**

### ⓑ 만료 없는 유예·제외 — **2회차**

| 회차 | 좌석 | 대책 |
|---|---|---|
| 1회 | `ops/provenance_audit._KNOWN_GAPS`(2,643/2,647 영구 면제) | `ARCH-25` — 태스크 ID 필수 + done 잔존 시 red |
| **2회** | **`harness/problem_type_mapping.EXCLUDED_CORPORA`**(rephrased 429 · 사유 소멸 6일 방치) | **`PB-07`** — 같은 계약을 이 좌석에도 적용 |

**교훈**: 1회차 대책이 *코드로* 착지한 것은 옳았으나 **좌석 단위**였다. 같은 성격의 좌석이
저장소에 몇 개 더 있는지는 아무도 세지 않았다. `PB-07`은 이 좌석을 덮고, 세 번째 좌석이 나오면
그때는 좌석 열거 자체를 기계화한다(지금은 하지 않는다 — 2회차에 일반화 도구를 만들면 과공학).

### ⓒ "정본화 ≠ 집행" — 계열 재발

`PED-06`(노출 계약을 만들고 서빙 경로가 안 부름)과 **동일 형태**가 문제은행에서 재현됐다(G3).
`PB-03`은 계약을 만들고 6모드+CAT에 배선했으나, **경로 열거가 완전하지 않았다** —
`GET /v1/problems`가 빠졌다. `PB-08`의 acceptance는 CLAUDE.md 요구대로 ①계약과 ②**집행 지점 열거**를
별항으로 분리해 적는다.

---

## §정정 — stale 정본 5곳 (이번 대조에서 실측으로 발견)

원문은 이력 보존을 위해 삭제하지 않고 여기에 모은다.

| # | 위치 | 기록된 값 | 실측(2026-08-11) |
|---|---|---|---|
| 1 | `docs/data/problem_bank_corpus_v1.md:3` | "6종 · 전 2,613건" | **7종 2,647건**(`probability_finite_v0` 34 누락) |
| 2 | `docs/data/problem_bank_coverage_2026-07.{md,json}` | "6종 2,667문 · 커버 코드 72" | 7종 2,647. **문서 정정이 아니라 재생성 대상**(`PB-02` 소관 · PR #739) — 여기서는 배너만 |
| 3 | `harness/problem_type_backfill.py:12-13` | "`S4-14` **미착지**로 명시 제외" | `S4-14` done(2026-08-05) · 계보 429/429 보유 — **사유 소멸**. `PB-07`이 상환 |
| 4 | `schema/problem.py:340-341` | `problem_type_codes`는 "`signature_patterns` **동형**" | **영속 축에서 비동형** — `signature_patterns`만 ORM 컬럼(`db/models/problem.py:157`) |
| 5 | `MEMORY.md:1813-1821` | R2 등재 "태스크 **6건** + 게이트 1건"(`PB-05`·`HARN-14` 포함) | 실제 병합분은 `PB-01`~`PB-04` + `HARN-18`. `PB-05`는 `ARCH-24`와 동축이라 의도적 제외(`unmerged_branch_verdict_2026-08-04.md:56`) · **게이트는 철회**(`events.ndjson:2111`). MEMORY만 읽으면 유령 태스크 2건이 생긴다 |

---

## §부록 — 실측 근거·재현 명령 (2026-08-11 · HEAD `959ec4ad`)

```bash
cd /home/user/WhyMath

# ① 코퍼스 채움률 — 2647 / persona_fit 2647 / type 2218 / lineage 1024 / approved 2489·pending 158
python3 -c "
import json,glob,collections
tot=pf=pt=rel=0; rs=collections.Counter()
for f in glob.glob('data/corpus/problem_bank_*/problems.jsonl'):
    for l in open(f,encoding='utf-8'):
        if not l.strip(): continue
        d=json.loads(l); tot+=1
        pf+=bool(d.get('persona_fit')); pt+=bool(d.get('problem_type_codes')); rel+=bool(d.get('relations'))
        rs[d.get('review_status')]+=1
print(tot,'persona_fit',pf,'type',pt,'lineage',rel,dict(rs))"

# ② 미머지 저작 확장 — 브랜치 37코퍼스 / 신규 30종 11,446문 / 고유 성취기준 55(main과 교집합 0)
B=origin/claude/whymath-mvp-plan-architecture-trjg5x
git log -1 --format='%ci' $B; git rev-list --count origin/main..$B          # 2026-08-09 / 111
git ls-tree -r --name-only $B -- data/corpus/ | grep -c 'problem_bank_.*problems.jsonl'   # 37
git ls-tree --name-only $B backlog/tasks/ | grep -cE 'S4-(3[0-9]|4[0-9]|5[0-9])'          # 22
ls backlog/tasks/ | grep -cE 'S4-(3[0-9]|4[0-9]|5[0-9])'                                  # 0
git ls-tree -r --name-only $B -- data/corpus/ | grep -c '_provenance.json'                # 7 (신규 30종 부재)

# ③ 갭 실재 확인
grep -n 'stmt = select(Problem)' -A 3 src/backend/whymath_backend/api/problems.py   # G3
sed -n '141p' src/backend/whymath_backend/harness/problem_type_mapping.py           # G2
grep -rn 'calibrate_items' .github/ docker-compose*.yml infra/ ; echo "EXIT=$?"     # G4 (1=무일치)
# G7 — 히트는 class 정의 2건뿐(생성자 호출 0). class 줄을 빼면 무일치여야 한다
grep -rn 'ProblemStep(' src/backend/whymath_backend/ --include=*.py | grep -v '^.*:class '

# ④ R2 해소분 재확인
grep -n 'METADATA_ONLY_SOURCES\|ReviewStatus.approved' src/backend/whymath_backend/api/me.py | tail -3
grep -n '_CANDIDATE_FETCH_LIMIT = ' src/backend/whymath_backend/api/gating.py       # 3000
grep -c 'variant-identity' backlog/gates.yaml ; echo "EXIT=$?"                      # 0 (철회 확인)
```

**파일:행 대장**

- 미머지 저작 브랜치: `origin/claude/whymath-mvp-plan-architecture-trjg5x`(111커밋 · PR 없음)
- 유형 제외 좌석: `harness/problem_type_mapping.py:141` · 사유 `harness/problem_type_backfill.py:12-13`
- 공개 카탈로그 무게이트: `api/problems.py:81`(단건) · `:107-124`(목록) —
  대조군 `api/me.py:2218-2225`(2축 게이트) · `l6/_shared.py:141,165`
- 정답 축 클라 단독 방어: `src/mobile/lib/features/problems/data/problem_models.dart:11-16`
- 무인증 의도 결정·동결: `account_security_gap_review.md:222` · `tests/backend/api/test_problems.py:480-490`
- 난이도 보정 CLI: `l2/calibrate_items.py:1-13`(스케줄 외부 위임 선언) · `l2/item_calibration.py:27`(min 응답 5)
- 영속 드롭 지점: `db/models/problem.py:295-297`(`mapper.column_attrs` 필터)
- 그랜드파더 만료 계약(1회차 대책): `ops/provenance_audit.py`(`_KNOWN_GAPS` 현재 빈 dict) · `ARCH-25`
- S6 야간 재검증(main): `.github/workflows/ci.yml:1186-1189` — 완료본은 PR #739
- 게이트 철회 근거: `backlog/events.ndjson:2111` · `backlog/gates.yaml`(7건 · `G-s4-14-*` 부재)

**기존 추적 승계(중복 등재 금지 대장)**: `PB-02` · `PB-04` · `QUAL-02` · `QUAL-04` · `S4-16` ·
`S4-01` · `S4-15` · `S4-09`/`S4-10` · `S3-28` · `SEC-18` · `HARN-13` · `ARCH-24` · `ARCH-25`.

---

## §재점검 — 30커밋 후 판정 유효성 재확인 (2026-08-11 · HEAD `6fe30526`)

> **성격**: 새 대조(R4)가 **아니다**. 본문은 이력 보존을 위해 개정하지 않고, 위 판정이 아직
> 유효한지만 재확인한다. 본 문서는 HEAD `959ec4ad` 스냅샷으로 작성됐고 그 후 main이 **30커밋**
> 진행했으며 그중 여럿이 문제은행 축을 직접 건드렸다(`#777` QUAL-02 · `#797` PB-07 ·
> `#801` SOL-01 · `#796` 커버리지 재생성 · `#798` 하네스).

### ① G1~G7 재판정 — 1건 해소 · 1건 성격 변화 · 5건 유효

| 갭 | 재판정 | 근거 |
|---|---|---|
| **G1** 저작 11,446문 고립 | 🔴 **유효** | `trjg5x` 원격 존재 · `S4-30`~`S4-51` main **0건** · main 코퍼스 여전히 **7종** · `PB-06` todo |
| **G2** 유형 태깅 제외 | ✅ **해소** | `PB-07` done(#797)이 `EXCLUDED_CORPORA`를 **빈 dict + `ExclusionEntry` 만료 계약**으로 교체하고 계보 분류 축(`LINEAGE_CORPORA`)을 신설 → 유형 태깅 **2,638/2,638(100%)** |
| **G3** 공개 카탈로그 무게이트 | 🔴 **유효** | `api/problems.py:119` `select(Problem)` 그대로 · `PB-08` todo |
| **G4** 난이도 루프 호출자 0 | 🟡 **구현됨·미머지(PB-10 PR 진행 중, 2026-10-08)** | 판정 시점 main에서는 `calibrate_items` 호출자 `.github/`·`infra/`·compose **0건**으로 여전히 유효. PB-10 브랜치가 `docker-compose.prod.yml`의 `item-calibration` 서비스 + `harness/item_calibration_reach_report.py`를 추가 — **머지 전에는 해소로 세지 않는다** |
| **G5** 변형 3종 부재 | 🔴 **유효** | 조건·난이도계열·역문제 코드 0 · `PB-09` todo |
| **G6** 메타 4필드 미영속 | 🔴 유효(의도) | ORM 매핑 여전히 0 — 재논쟁 없음 |
| **G7** `problem_step` writer 0 | ⚠️ **성격 변화** | `S4-09` done(`SOL-01` #801)로 **`SolutionPath`/`SolutionStep` 좌석은 살아났으나** `problem_step`은 writer 0 유지 → **두 좌석 병존**. `SOL-03`이 이 축을 더 정밀하게 추적한다(problem_step 행수 + *"생성 경로 자체가 없음"* vs *"경로는 있으나 미호출"* 구분 · `ReasoningType` 소비 0) → **`SOL-03` 승계, 중복 등재 금지** |

### ② §부록 수치 stale — `QUAL-02`(#777) 실중복 9레코드 은퇴

| 축 | 본문 기록 | 재점검 실측 |
|---|---:|---:|
| 문항 총계 | 2,647 | **2,638** (`generated_v0` 620→619 · `rephrased_v0` 429→421) |
| 유형 태깅 | 2,218 | **2,638 (100%)** |
| 계보 | 1,024 | **1,015** |
| `review_status` | approved 2,489 / pending 158 | **approved 2,480** / pending 158 |

본문 §부록의 기대값 주석은 **작성 시점 기준**이며, 현행 정본 수치는 이 표다.

### ③ 신규 발견 — 커버리지 리포트가 착지 **1커밋 만에** stale

`docs/data/problem_bank_coverage_2026-08.md`는 §정정-2가 요구한 재생성의 이행본으로
**#796(`74314e64`)**에 착지했다. 그런데 **바로 다음 PR #797(`3b85de7e`)**이 `PB-07`을 착지시켜
유형 태깅을 100%로 만들었다.

| 리포트 §정직 회계 주장 | 실측 |
|---|---|
| "유형(problem_type) 없는 문항 **421**"(`rephrased_v0` 전량) | `rephrased_v0` 421/421 **전건 태깅 · 미태깅 0** |

값 하나가 틀린 것이 문제가 아니다 — **그 값이 실린 절이 "정직 회계"**, 곧 *"전 항목 0이므로
액면 그대로 읽어도 된다"* 는 신뢰 근거를 제공하는 절이다. **신뢰를 보증하는 자리에 틀린 값이 있다.**

이는 R2 §0-②-바("관측 자산이 부패 중")의 **재발이자 형태 변화**다 — 이번엔 리포트가 오래돼서가
아니라 **재생성 CI 배선(`PB-02`)이 아직 열린 PR #739에 있어** 코퍼스가 바뀌어도 자동 갱신되지
않기 때문이다. §1이 `PB-02`를 *"설계 갭이 아니라 머지 대기"* 로 판정한 것은 여전히 옳다(답은
재설계가 아니라 머지다). 다만 **그 머지 대기가 실피해를 냈다**는 사실이 이번에 추가됐다.
정정은 그 리포트에 배너로 달았다 — **수치를 손으로 고치지 않는다**(결정론 CLI 산출물).

### ④ 외부 반증 승계 — `#798` (재논쟁 없음)

`#798`이 다른 세션의 동형 가설(*"MCP로 연 PR은 CI 미발화 → 만성 미머지의 근본 원인"*)을 미머지
18건 전수 판정으로 **반증**했다(실제 사유: PR 미개설 8 · PR 닫힘 8 · CI green인데 사람 결정 3 ·
**CI 미발화 1**). 또 **`pull_request_read method=get_status`가 이 저장소에서 전 PR
`total_count: 0`을 낸다**(commit status API vs check runs)는 도구 함정을 명문화하고 `HARN-30`을
등재했다. 이 문서를 낸 세션도 PR #776 진단에서 그 함정에 걸렸다(초기 근거 1건 무효) — 다만
결론 자체는 권위 있는 `actions_list list_workflow_runs`의 **0 → 1 전이 실측**으로 유지된다.
`HARN-30` 승계, 중복 등재 없음.

### ⑤ 신규 태스크 0건

재점검이 찾은 축은 전부 기존 태스크에 있다 — `PB-02`(리포트 재생성 CI) · `PB-06`·`PB-08`~`PB-10`
(G1·G3~G5) · `SOL-03`(G7) · `HARN-30`(도구 함정). 중복 등재 금지 원칙에 따라 신설하지 않는다.
