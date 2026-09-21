# 오개념 crosswalk 검수 결정 패키지 (dossier) — G-crosswalk-approval

> **상태: 사람(Kiki) 검수 대기 · read-only 준비물 · 라이브 테이블 미적재.**
> 이 문서는 게이트 `G-crosswalk-approval`(`backlog/gates.yaml`, status=pending)의 **검수를 한
> 화면에서 끝낼 수 있게** AI 허용 도구(coverage·review-aid)의 출력과 결정 체크리스트를 하나로 묶은
> 준비물이다. **판정하지 않는다** — 어떤 행도 승인/반려로 표시하지 않으며, 검수 큐·라이브 테이블·
> 게이트 상태를 바꾸지 않는다(AI 자기승인 금지·정본 계약 `docs/standards/crosswalk_gate_contract.md`).
>
> **생성**: 2026-07-09 · **계층**: L1/L4(준비) · **원천**:
> `docs/data/misconception_crosslink_review_queue.json`(81행·34 kebab·전행 pending) ·
> 초안 `docs/data/misconception_crosslink_candidates.md`(v0.3) ·
> 코퍼스 `data/corpus/misconceptions_v1/misconceptions.json`(839→…행).

## 왜 이 게이트가 사람 몫인가 (요약)

crosswalk 매핑(런타임 탐지 kebab-id → 리포트 노출 canonical M-id)이 틀리면 **오귀속 진단 = 오도된
학부모/학생 코칭**이 된다(CLAUDE.md 의사결정 우선순위 #1 학생 웰빙·#3 교수학 정확성). 따라서
**AI 자기승인·검수 없는 적재를 금지**하고, 승인·적재·노출 플립은 사람이 한다. AI는 제안(후보)·
측정(shadow)·리포트(커버리지·근거 조인)·가드 강화만 한다. 이 dossier가 바로 그 "리포트" 몫이다.

## §1. Kiki 결정 기록 절차 (이 dossier 이후 단계)

이번 세션은 **준비까지만**이다. 실제 승인은 아래 순서로 Kiki가 진행한다(정본 계약 준수):

1. **행별 판정** — 아래 §5 결정 체크리스트 표(또는 §4 근거)를 보고 각 행을 approve/reject/defer.
   - 직접매핑 승격은 사람 판단으로만. `직접매핑`인데 `confidence < 0.6`이면 **인접 오개념**으로만
     두고 직접매핑 승격 금지(초안 §0.2·승격 규칙 3).
   - 코퍼스 M-id 원문 정합도 병행 확인(코퍼스 자체가 `AI생성-검수필요` — 이중 검수).
2. **검수 큐 *복사본*에 서명 기입** — 승인 행에 `status=approved` + `reviewer` + `reviewed_on`(ISO
   `YYYY-MM-DD`). 서명 stamp 정본 형식 `검수:{reviewer} {reviewed_on}`(`sign()`이 찍고
   `is_signed()`가 검증). 반려는 `rejected`, 보류는 `deferred`.
3. **승격·적재** — 승인분만 로더 형식으로 승격·적재:
   ```bash
   cd src/backend
   python -m whymath_backend.l4.misconception.crosslink_review promote \
       --queue <서명한_큐.json> --load
   ```
   승격 규칙(전건 열거 실패): status=approved ∧ 서명 ∧ (직접매핑 ⇒ conf≥0.6) ∧ kebab∈카탈로그.
   적재 규칙: `method=manual` ∧ note에 서명 stamp. (AI 자기승인·미서명 JSON 구조적 차단.)
4. **게이트 clear** — 적재·검수 증적과 함께:
   ```bash
   python3 scripts/harness/backlog.py gates clear G-crosswalk-approval --as kiki --evidence "<커밋/문서/기록>"
   ```
   → `S2-01`(저작권 안전 동등문제 코퍼스) 해금. 이후 shadow→canary 노출 플립은 별 슬라이스(사람).

## §2. 검수 우선순위 (얇거나 약한 행 먼저)

coverage 갭 분류(§3) + 초안 §3 "우선 검수"를 교차하면 시간을 먼저 쓸 곳은:

| 우선순위 | kebab | 사유 | flag |
|---|---|---|---|
| 1 | `circle-radius-squared` | 직접매핑 최고 **동률**(M0630·M0848 둘 다 conf 0.93) — 어느 것을 canonical로 둘지 **사람 정책 확정 필요** | ⚠동률 |
| 2 | `period-of-scaled-sine` | 직접매핑 후보 **부재**(M0152 개념겹침 0.45만) — "y=sin(2x) 주기" 직접 진술 코퍼스에 없음 → **신규 M-id 저작 여부** 결정 | △직접부재 |
| 3 | `exponent-zero`(M0105) · `sine-distributes-over-sum`(M0707) · `root-loss-by-dividing`(M0573) | 직접 후보 **유일·얇음**(대안 없음) — 그 하나가 틀리면 대체 없음, 원문 정합 집중 확인 | ★얇음 |
| 4 | `opposite-root-selected`(M0862) · `factor-sign-flip`(M0863) · `extremum-max-min-confused`(M0864) · `extremum-value-vs-point-confused`(M0865) | **신규 저작 M-id**(S2-p) 직접매핑 0.90 — 원문 정합·저작 품질 검수 대상 | 신규저작 |
| 5 | `fraction-cancellation`(M0118) | 덧셈식 약분 — (a+b)/a 의도 원문 확인 권장(초안 §3) | — |

나머지 coverable 26종은 conf·근거가 뚜렷(직접매핑 conf≥0.6·최상위 명확)해 확인 부담이 낮다.

## §3. 커버리지·갭 리포트 (`crosslink_coverage.py` 출력)

> 재생성: `cd src/backend && python -m whymath_backend.l4.misconception.crosslink_coverage --queue ../../docs/data/misconception_crosslink_review_queue.json`
> (판정·status 변경 없음·`select_canonical` 시뮬. `coverable`=승격 시 canonical 잡힘·conf≥0.6.)

```text
# crosswalk 커버리지·갭 리포트 (read-only·판정 없음·select_canonical 시뮬)
대상 상태: pending · 전 kebab 34종 · 분류 {'coverable': 32, 'below_threshold': 0, 'ambiguous_tie': 1, 'no_direct': 1, 'no_candidate': 0}
검수 우선순위: no_candidate(후보 저작) → ambiguous_tie(정책) → below_threshold/no_direct.
승인·적재·노출 플립은 사람(4b-2) — 이 리포트는 어디를 볼지만 가리킨다.

## ambiguous_tie — ⚠ 직접매핑 최고 동률(사람 정책 확정 필요) (1종)
  circle-radius-squared: ⚠ 직접매핑 최고 동률(사람 정책 확정 필요) (후보 3·직접 2·conf≥임계 2·reason=tie)

## no_direct — △ 직접매핑 후보 부재(부분/개념겹침만) (1종)
  period-of-scaled-sine: △ 직접매핑 후보 부재(부분/개념겹침만) (후보 1·직접 0·conf≥임계 0·reason=no_direct)

## coverable — ✅ 승격 시 canonical 잡힘 (32종)
  angle-sum-non-triangle: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0493)
  area-perimeter-confusion: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0529)
  chain-rule-inner-derivative-omitted: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0370)
  composite-function-commutes: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0643)
  continuity-implies-differentiability: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0670)
  critical-point-implies-extremum: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0080)
  discriminant-negative-no-real-root: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0610)
  distribution-over-power: ✅ 승격 시 canonical 잡힘 (후보 3·직접 2·conf≥임계 2·reason=ok → M0019)
  division-by-zero: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0003)
  dot-product-is-vector: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0735)
  exponent-zero: ✅ 승격 시 canonical 잡힘 (후보 1·직접 1·conf≥임계 1·reason=ok → M0105)
  extremum-max-min-confused: ✅ 승격 시 canonical 잡힘 (후보 1·직접 1·conf≥임계 1·reason=ok → M0864)
  extremum-value-vs-point-confused: ✅ 승격 시 canonical 잡힘 (후보 1·직접 1·conf≥임계 1·reason=ok → M0865)
  factor-sign-flip: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0863)
  fraction-cancellation: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0118)
  gambler-fallacy: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0688)
  geometric-series-always-converges: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0209)
  invertibility-without-1-1: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0144)
  limit-equals-function-value: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0665)
  log-distribution: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0049)
  mean-vs-median: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0419)
  mutually-exclusive-implies-independent: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0692)
  opposite-root-selected: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0862)
  product-rule-naive: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0075)
  prosecutor-fallacy: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0691)
  root-loss-by-dividing: ✅ 승격 시 canonical 잡힘 (후보 1·직접 1·conf≥임계 1·reason=ok → M0573)
  sign-flip-in-inequality: ✅ 승격 시 canonical 잡힘 (후보 3·직접 3·conf≥임계 3·reason=ok → M0564)
  similarity-vs-congruence: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0519)
  sine-distributes-over-sum: ✅ 승격 시 canonical 잡힘 (후보 1·직접 1·conf≥임계 1·reason=ok → M0707)
  square-root-positivity: ✅ 승격 시 canonical 잡힘 (후보 3·직접 2·conf≥임계 2·reason=ok → M0550)
  term-to-zero-implies-convergence: ✅ 승격 시 canonical 잡힘 (후보 2·직접 1·conf≥임계 1·reason=ok → M0704)
  translation-sign-flip: ✅ 승격 시 canonical 잡힘 (후보 3·직접 1·conf≥임계 1·reason=ok → M0411)

{"statuses":["pending"],"catalog_total":34,"counts":{"coverable":32,"below_threshold":0,"ambiguous_tie":1,"no_direct":1,"no_candidate":0},"no_candidate":[],"ambiguous_tie":["circle-radius-squared"],"below_threshold":[],"not_in_catalog":[]}
```

## §4. kebab별 후보 근거 + 검수 체크리스트 (`crosslink_review_aid.py` 출력)

> 재생성: `cd src/backend && python -m whymath_backend.l4.misconception.crosslink_review_aid --queue ../../docs/data/misconception_crosslink_review_queue.json --corpus ../../data/corpus/misconceptions_v1/misconceptions.json`
> kebab 오개념(정의·반례) × 후보 M-id 근거(학생 오사고·distractor 규칙·오류유형·성취기준)를 조인.
> "기계 전제(promote)"는 자동 계산이고 "교수학 판단(Kiki)"이 사람 몫(도구는 status 미변경).

```text
# crosswalk 검수 보조 — 근거 조인 + 체크리스트(read-only·판정 없음)
대상 상태: pending · kebab 34종 · 후보 81건
검수자는 kebab 오개념과 후보 M-id 근거를 대조해 체크리스트로 approve/reject를 판단하고,
검수 큐 *복사본*에 status/reviewer/reviewed_on을 손기입한 뒤 promote로 적재한다
(이 도구는 status를 안 바꾼다·기계 전제만 계산·판정은 사람 몫).

## angle-sum-non-triangle  (비삼각형 각 합 혼동 · 기하)
   틀린 믿음: 모든 다각형의 내각의 합은 180°
   반례: 사각형의 내각의 합은 360° (n각형은 (n-2)×180°)
   → M0493  [직접매핑 conf=0.85 status=pending]
     개념: 도형이 크거나 모양이 다르면 내각의 합도 달라진다고 생각한다(모양과 무관  · 성취기준 [4수03-25]
     학생 오사고: 도형이 크거나 모양이 다르면 내각의 합도 달라진다고 생각한다(모양과 무관하게 일정).
     distractor 규칙: 정답 대신, 학생이 '도형이 크거나 모양이 다르면 내각의 합도 달라진다고 생각한다(모양과 무관하게 일정)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 최상위 — 모양 다르면 내각합 달라짐
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0580  [부분매핑 conf=null status=pending]
     개념: 외각의 합도 변의 수에 따라 달라진다고 본다(항상 360°). 내각·외각을 헷갈린다.  · 성취기준 [9수03-05]
     초안근거: 초안 대안(무표기·'외각') — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0051  [개념겹침 conf=null status=pending]
     개념: 삼각형 내각합  · 성취기준 [9수03-03]
     학생 오사고: 180°가 아닌 다른 값
     distractor 규칙: 360° 배치
     오류유형: 공식혼동
     초안근거: 초안 대안 '약' 표기 — 인접 오개념. 직접매핑 승격 금지(초안 §0.2)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## area-perimeter-confusion  (둘레 늘면 넓이 늘 가정 · 기하)
   틀린 믿음: 둘레가 크면 넓이도 크다
   반례: 가늘고 긴 직사각형은 둘레 大, 넓이 小 가능
   → M0529  [직접매핑 conf=0.95 status=pending]
     개념: 둘레와 넓이를 혼동한다(둘레는 cm, 넓이는 ㎠)  · 성취기준 [6수03-11]
     학생 오사고: 둘레와 넓이를 혼동한다(둘레는 cm, 넓이는 ㎠). 둘레가 같으면 넓이도 같다고 오해한다.
     distractor 규칙: 정답 대신, 학생이 '둘레와 넓이를 혼동한다(둘레는 cm, 넓이는 ㎠)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 공식혼동
     초안근거: 초안 최상위 — 둘레·넓이 비례 오해
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0782  [부분매핑 conf=null status=pending]
     개념: 둘레와 넓이를 혼동한다(둘레는 길이, 넓이는 ㎡)  · 성취기준 [12직수03-04]
     학생 오사고: 둘레와 넓이를 혼동한다(둘레는 길이, 넓이는 ㎡).
     distractor 규칙: 정답 대신, 학생이 '둘레와 넓이를 혼동한다(둘레는 길이, 넓이는 ㎡)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 공식혼동
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0052  [부분매핑 conf=null status=pending]
     개념: 넓이 vs 둘레  · 성취기준 [9수03-12]
     학생 오사고: 둘 혼동
     distractor 규칙: 공식 바꿔 배치
     오류유형: 공식혼동
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## chain-rule-inner-derivative-omitted  (연쇄법칙 내부도함수 누락 · 미적분)
   틀린 믿음: d/dx[sin(2x)] = cos(2x)
   반례: 정답은 2cos(2x) — 내부함수 2x의 도함수 2가 곱해져야 함
   정정형: d/dx[sin(2x)] = 2cos(2x)
   → M0370  [직접매핑 conf=0.9 status=pending]
     개념: 삼각함수 합성 미분  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: 연쇄법칙 안쪽 계수 누락
     distractor 규칙: 계수 함정
     오류유형: 공식혼동
     초안근거: 초안 최상위 — sin(2x) 연쇄법칙 내부도함수 누락
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0710  [부분매핑 conf=null status=pending]
     개념: 속함수의 미분(곱하기)을 빠뜨린다  · 성취기준 [12미적Ⅱ-02-05]
     학생 오사고: 속함수의 미분(곱하기)을 빠뜨린다. 어디까지가 겉·속함수인지 잘못 나눈다.
     distractor 규칙: 정답 대신, 학생이 '속함수의 미분(곱하기)을 빠뜨린다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 분배누락
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0077  [부분매핑 conf=null status=pending]
     개념: 합성함수 미분  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: 연쇄법칙 누락
     distractor 규칙: 안쪽 미분 빠뜨림
     오류유형: 공식혼동
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## circle-radius-squared  (원 반지름 제곱 혼동 · 기하)
   틀린 믿음: x²+y²=r²의 반지름은 r²
   반례: x²+y²=9는 반지름 3 (=√9), 9가 아님
   → M0630  [직접매핑 conf=0.93 status=pending]
     개념: 반지름 r과 r²(우변)을 혼동한다. 중심 (a,b)의 부호를 반대로 읽는다.  · 성취기준 [10공수2-01-04]
     초안근거: 초안 최상위 병기 1/2(M0630/M0848) — x²+y²=r² 반지름 r vs r²
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0848  [직접매핑 conf=0.93 status=pending]
     개념: 반지름 r과 r²(우변)을 혼동한다. 중심 (a,b)의 부호를 (−a,−b)로 읽는다.  · 성취기준 [10기수2-01-04]
     초안근거: 초안 최상위 병기 2/2(M0630/M0848) — x²+y²=r² 반지름 r vs r²
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0732  [부분매핑 conf=null status=pending]
     개념: 반지름 r과 r²(우변)을 혼동한다. 중심 좌표의 부호를 반대로 읽는다.  · 성취기준 [12기하02-05]
     초안근거: 초안 대안(무표기·'구') — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## composite-function-commutes  (합성함수 교환 가정 · 함수)
   틀린 믿음: f∘g = g∘f (합성은 교환법칙 성립)
   반례: f=x+1, g=x²: f∘g=x²+1 ≠ (x+1)²=g∘f
   → M0643  [직접매핑 conf=0.95 status=pending]
     개념: f∘g와 g∘f를 같다고 본다(순서가 중요). 어느 것을 먼저 적용하는지 헷갈린다.  · 성취기준 [10공수2-03-02]
     초안근거: 초안 최상위 — f∘g=g∘f 같다고 봄
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0858  [부분매핑 conf=null status=pending]
     개념: 합성 순서를 반대로 한다(g∘f를 f(g(x))로)  · 성취기준 [10기수2-03-02]
     학생 오사고: 합성 순서를 반대로 한다(g∘f를 f(g(x))로). 합성에 교환법칙이 성립한다고 오인한다.
     distractor 규칙: 정답 대신, 학생이 '합성 순서를 반대로 한다(g∘f를 f(g(x))로)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 순서오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0038  [부분매핑 conf=null status=pending]
     개념: 합성함수  · 성취기준 [10공수2-03-02]
     학생 오사고: f(g(x)) 순서 반대
     distractor 규칙: g(f(x)) 답 배치
     오류유형: 순서오류
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## continuity-implies-differentiability  (연속·미분가능 함의 혼동 · 미적분)
   틀린 믿음: 연속이면 미분가능하다
   반례: f(x)=|x|는 x=0에서 연속이나 미분불가 (뾰족점)
   → M0670  [직접매핑 conf=0.97 status=pending]
     개념: 연속이면 미분 가능으로 단정한다(뾰족점·꺾인 점이 반례)  · 성취기준 [12미적Ⅰ-02-02]
     학생 오사고: 연속이면 미분 가능으로 단정한다(뾰족점·꺾인 점이 반례). 역방향 함의를 헷갈린다.
     distractor 규칙: 정답 대신, 학생이 '연속이면 미분 가능으로 단정한다(뾰족점·꺾인 점이 반례)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 조건무시
     초안근거: 초안 최상위 — 연속이면 미분가능 단정
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0176  [부분매핑 conf=null status=pending]
     개념: 미분가능·연속  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: 연속이면 미분가능으로
     distractor 규칙: 첨점 무시
     오류유형: 조건무시
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0345  [부분매핑 conf=null status=pending]
     개념: 절댓값 함수 미분가능  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: 꺾인 점 미분 가능으로
     distractor 규칙: 미분 함정
     오류유형: 조건무시
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## critical-point-implies-extremum  (임계점 극값 단정 · 미적분)
   틀린 믿음: f′(a)=0이면 그 점에서 극값을 갖는다
   반례: f(x)=x³는 f′(0)=0이나 극값 아님 (변곡점)
   → M0080  [직접매핑 conf=0.95 status=pending]
     개념: 극값 판정  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: f'=0이면 무조건 극값
     distractor 규칙: 변곡점 함정
     오류유형: 극값변곡혼동
     초안근거: 초안 최상위 — f′=0이면 무조건 극값
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0675  [부분매핑 conf=null status=pending]
     개념: f′=0이면 무조건 극값으로 본다(부호가 안 바뀌는 변곡점은 극값 아님)  · 성취기준 [12미적Ⅰ-02-07]
     학생 오사고: f′=0이면 무조건 극값으로 본다(부호가 안 바뀌는 변곡점은 극값 아님).
     distractor 규칙: 정답 대신, 학생이 'f′=0이면 무조건 극값으로 본다(부호가 안 바뀌는 변곡점은 극값 아님)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 극값변곡혼동
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0349  [부분매핑 conf=null status=pending]
     개념: 극값과 최댓값  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: 정의역 끝점 비교 누락
     distractor 규칙: 최대·극대 함정
     오류유형: 조건무시
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## discriminant-negative-no-real-root  (판별식 음수 해 부재 단정 · 대수)
   틀린 믿음: 판별식 D<0이면 해가 없다
   반례: x²+1=0은 실근은 없으나 x=±i (복소근 2개)
   → M0610  [직접매핑 conf=0.95 status=pending]
     개념: D<0을 '해가 없다'로 단정한다(실근이 없을 뿐 허근은 존재)  · 성취기준 [10공수1-02-02]
     학생 오사고: D<0을 '해가 없다'로 단정한다(실근이 없을 뿐 허근은 존재). D=0의 중근을 근이 없다고 본다.
     distractor 규칙: 정답 대신, 학생이 'D<0을 '해가 없다'로 단정한다(실근이 없을 뿐 허근은 존재)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 최상위 — D<0 해없음 단정(허근)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0832  [부분매핑 conf=null status=pending]
     개념: D=0을 '근 없음'으로 단정한다(중근 하나 존재)  · 성취기준 [10기수1-02-02]
     학생 오사고: D=0을 '근 없음'으로 단정한다(중근 하나 존재). D<0인데 실근이 있다고 본다. 부호와 개수 매칭을 혼동한다.
     distractor 규칙: 정답 대신, 학생이 'D=0을 '근 없음'으로 단정한다(중근 하나 존재)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 부호오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0124  [부분매핑 conf=null status=pending]
     개념: 판별식 해석  · 성취기준 [9수02-20]
     학생 오사고: D=0을 해 없음으로
     distractor 규칙: 중근 무시
     오류유형: 해석오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## distribution-over-power  (제곱 분배 오류 · 대수)
   틀린 믿음: (a+b)² = a² + b²
   반례: a=1, b=1
   정정형: (a+b)² = a² + 2ab + b²
   → M0019  [직접매핑 conf=0.95 status=pending]
     개념: 곱셈공식  · 성취기준 [9수02-19]
     학생 오사고: (a+b)²=a²+b² (중간항 누락)
     distractor 규칙: 정답에 2ab 빠진 식
     오류유형: 분배누락
     초안근거: 초안 최상위 — (a+b)²=a²+b² 중간항 누락 일치
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0572  [직접매핑 conf=0.8 status=pending]
     개념: (a+b)²을 a²+b²으로(가운데 2ab 누락). 부호를 틀린다. 공통인수를 빠뜨리고 묶는다.  · 성취기준 [9수02-19]
     초안근거: 초안 대안(D) — 검수 반영 conf 0.80(#392). 핵심 (a+b)²→a²+b² 일치·복합 레코드라 최상위 M0019(0.95) 미만
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0649  [부분매핑 conf=null status=pending]
     개념: aᵐ·aⁿ을 a^(mn)으로 한다(실제 a^{m+n}). (a+b)ⁿ을 aⁿ+bⁿ으로 분배한다.  · 성취기준 [12대수01-03]
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## division-by-zero  (0 나눗셈 가능성 놓침 · 대수)
   틀린 믿음: 분모에 변수가 와도 항상 정의됨
   반례: 분모 = 0이 되는 값에서 식이 무정의
   → M0003  [직접매핑 conf=0.85 status=pending]
     개념: 0으로 나누기  · 성취기준 [9수01-03]
     학생 오사고: 5÷0=0 또는 =5
     distractor 규칙: '정의되지 않음' 대신 0 배치
     오류유형: 해석오류
     초안근거: 초안 최상위 — 0 나눗셈 가능성 오해
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0556  [부분매핑 conf=0.5 status=pending]
     개념: 한쪽 변에만 연산을 적용한다  · 성취기준 [9수02-03]
     학생 오사고: 한쪽 변에만 연산을 적용한다. 양변을 0으로 나눌 수 있다고 본다(0으로 나누기는 불가).
     distractor 규칙: 정답 대신, 학생이 '한쪽 변에만 연산을 적용한다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 대안(D·'양변0') → 부분매핑 강등(#392 후속). 주진술은 '한쪽 변 연산'(다른 오개념)·0나누기는 부차절 — 직접 부적합(인접 오개념)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0146  [부분매핑 conf=null status=pending]
     개념: 유리함수 정의역  · 성취기준 [10공수2-03-04]
     학생 오사고: 분모 0 값 누락
     distractor 규칙: 정의역 함정
     오류유형: 조건무시
     초안근거: 초안 대안(P 표기·'유리함수') — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## dot-product-is-vector  (내적 결과를 벡터로 · 벡터)
   틀린 믿음: 두 벡터의 내적 a·b는 벡터이다
   반례: 내적은 스칼라(실수): a·b = |a||b|cosθ
   → M0735  [직접매핑 conf=0.95 status=pending]
     개념: 내적의 결과를 벡터로 본다(실제 스칼라). 두 벡터가 수직이면 내적이 0임을 놓친다.  · 성취기준 [12기하03-03]
     초안근거: 초안 최상위 — 내적 결과를 벡터로(실제 스칼라)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0262  [부분매핑 conf=null status=pending]
     개념: 벡터 내적  · 성취기준 [12기하03-03]
     학생 오사고: a·b=|a||b| (cos 누락)
     distractor 규칙: cosθ 빠뜨림
     오류유형: 공식혼동
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## exponent-zero  (0 지수 0 가정 · 대수)
   틀린 믿음: a⁰ = 0
   반례: 2⁰ = 1 (a≠0인 모든 a에 대해 a⁰ = 1)
   정정형: a⁰ = 1
   → M0105  [직접매핑 conf=0.92 status=pending]
     개념: 지수 0·음수  · 성취기준 [9수02-08]
     학생 오사고: 2^0=0, 2^-1=-2
     distractor 규칙: 정답 1, 1/2에 0, -2
     오류유형: 공식혼동
     초안근거: 초안 최상위 — a⁰=0 정확 일치. 직접 후보 유일·얇음(초안 §3 우선 검수)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## extremum-max-min-confused  (극대·극소 혼동 · 미적분)
   틀린 믿음: 극댓값과 극솟값 중 어느 것이 어느 임계점에서 나오는지 상관없다
   반례: 이 예에서는 f(x)=x^3-3x가 x=-1(작은 임계점)에서 극대(2)·x=1에서 극소(-2) — 계수 양수라 순서 고정
   → M0864  [직접매핑 conf=0.9 status=pending]
     개념: 삼차함수에서 극댓값과 극솟값 중 어느 것이 어느 임계점에서 나오는지 구별하지 않고 서로 바꿔 답한다. 삼차항 계수가 양수면 작은 임계점에서 극대, 큰 임계점에서 극소이다  · 성취기준 [12미적Ⅰ-02-07]
     학생 오사고: 극대와 극소의 위치(작은/큰 임계점)를 구별하지 못해, 극댓값을 물으면 극솟값을·극솟값을 물으면 극댓값을 답한다.
     distractor 규칙: 요구된 극값의 반대 극값(극댓값↔극솟값)을 오답 보기로 배치
     오류유형: 극대극소혼동
     초안근거: 극값 MC 신규 저작(misconceptions_v1 M0864) — 극댓값↔극솟값 혼동을 직접 서술. kebab 1:1 대응([12미적Ⅰ-02-07]·H:12미적Ⅰ02-07). status=pending — Kiki 교수학 검수 후 승인·적재(AI 자기승인 금지).
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## extremum-value-vs-point-confused  (극값·극점 혼동 · 미적분)
   틀린 믿음: 극댓값은 극대가 되는 점의 x좌표이다
   반례: f(x)=x^3-3x의 극대는 x=-1에서지만 극댓값은 f(-1)=2 — x좌표 -1이 아님. 극대점(극대가 되는 점)·그 x좌표(-1)·극댓값(함숫값 2)은 각각 다른 대상이다
   → M0865  [직접매핑 conf=0.9 status=pending]
     개념: 극값의 값(극댓값·극솟값)과 극점의 x좌표를 혼동해, 극댓값을 극대가 되는 점의 x좌표로 답한다. 극댓값은 그 점에서의 함숫값 f(x)이다  · 성취기준 [12미적Ⅰ-02-07]
     학생 오사고: 극댓값을 구할 때 극대가 되는 점의 x좌표를 그대로 답으로 적는다(함수 f에 대입한 함숫값을 구하지 않음).
     distractor 규칙: 극점의 x좌표(임계점)를 극값의 값 대신 오답 보기로 배치
     오류유형: 값좌표혼동
     초안근거: 극값 MC 신규 저작(misconceptions_v1 M0865) — 극값의 값↔극점 x좌표 혼동을 직접 서술. kebab 1:1 대응([12미적Ⅰ-02-07]). status=pending — Kiki 교수학 검수 후 승인·적재(AI 자기승인 금지).
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## factor-sign-flip  (인수 근 부호 반전 · 대수)
   틀린 믿음: (x-a)=0이면 x=-a이다
   반례: (x-2)=0의 근은 x=2 — x=-2를 대입하면 -2-2=-4≠0
   → M0848  [개념겹침 conf=0.45 status=pending]
     개념: 반지름 r과 r²(우변)을 혼동한다. 중심 (a,b)의 부호를 (−a,−b)로 읽는다.  · 성취기준 [10기수2-01-04]
     초안근거: 초안 v0.2(S2-p) 최근접 대안 — 원 중심 부호 반전(동일 인지 행동·주제 상이). 직접 대응은 S2-p 신규 저작 M0863(아래 직접매핑 행).
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0863  [직접매핑 conf=0.9 status=pending]
     개념: 인수 (x-a)=0에서 근을 x=-a로 읽는다(부호 반전). 올바른 근은 x=a이다  · 성취기준 [10공수1-02-02]
     학생 오사고: 괄호 안 식이 0이 되려면 x가 빼는 수와 반대 부호여야 한다고 생각해 근을 부호 반전한 값으로 적는다.
     distractor 규칙: 각 인수의 근을 부호 반전한 값을 오답 보기로 배치
     오류유형: 부호오류
     초안근거: S2-p 신규 저작(misconceptions_v1 M0863) — 인수 (x-a)=0을 x=-a로 읽는 부호 반전을 직접 서술. kebab 1:1 대응(HK06·[10공수1-02-02]). 검수 후 승인·적재.
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## fraction-cancellation  (분자 합 약분 오류 · 대수)
   틀린 믿음: (a+b)/a = b
   반례: a=2, b=4: (2+4)/2 = 3 ≠ 4
   정정형: (a+b)/a = 1 + b/a
   → M0118  [직접매핑 conf=0.8 status=pending]
     개념: 약분 시점  · 성취기준 [9수01-04]
     학생 오사고: 덧셈식에서 약분
     distractor 규칙: (a+b)/a=b로
     오류유형: 공식혼동
     초안근거: 초안 최상위 — 덧셈식 약분. (a+b)/a 의도 원문 확인 권장(초안 §3 우선 검수)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0503  [개념겹침 conf=0.45 status=pending]
     개념: 분자·분모를 서로 다른 수로 나눈다  · 성취기준 [6수01-06]
     학생 오사고: 분자·분모를 서로 다른 수로 나눈다. 공약수가 아닌 수로 나눠 값이 바뀐다.
     distractor 규칙: 정답 대신, 학생이 '분자·분모를 서로 다른 수로 나눈다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 대안 '약함 0.45' — 인접 오개념. 직접매핑 승격 금지(초안 §0.2)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## gambler-fallacy  (도박사의 오류 · 확률통계)
   틀린 믿음: 앞면 5번 연속이면 다음은 뒷면이 더 잘 나온다
   반례: 독립시행은 과거 결과와 무관 (P=1/2 유지)
   → M0688  [직접매핑 conf=0.98 status=pending]
     개념: 도박사의 오류: 앞면이 5번 나왔으니 다음엔 뒷면 차례라고 본다(독립이라  · 성취기준 [12확통02-01]
     학생 오사고: 도박사의 오류: 앞면이 5번 나왔으니 다음엔 뒷면 차례라고 본다(독립이라 영향 없음).
     distractor 규칙: 정답 대신, 학생이 '도박사의 오류: 앞면이 5번 나왔으니 다음엔 뒷면 차례라고 본다(독립이라 영향 없음)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 순서오류
     초안근거: 초안 최상위 — 앞면 5번→다음 뒷면 차례 완전 일치
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0093  [부분매핑 conf=null status=pending]
     개념: 도박사 오류  · 성취기준 [12인수04-01]
     학생 오사고: 앞 결과가 다음에 영향
     distractor 규칙: 누적 영향 함정
     오류유형: 해석오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0794  [부분매핑 conf=null status=pending]
     개념: 도박사의 오류(독립 시행을 종속으로 봄)  · 성취기준 [12수문02-02]
     학생 오사고: 도박사의 오류(독립 시행을 종속으로 봄). 기댓값을 한 판에서 실제로 나오는 값으로 본다.
     distractor 규칙: 정답 대신, 학생이 '도박사의 오류(독립 시행을 종속으로 봄)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## geometric-series-always-converges  (등비급수 무조건 수렴 · 수열)
   틀린 믿음: 무한등비급수는 항상 수렴한다
   반례: 공비 r=2면 1+2+4+⋯ 발산 — |r|<1일 때만 수렴
   → M0209  [직접매핑 conf=0.92 status=pending]
     개념: 무한등비급수 수렴조건  · 성취기준 [12대수03-01]
     학생 오사고: |r|≥1인데 합 존재로
     distractor 규칙: 발산 무시
     오류유형: 조건무시
     초안근거: 초안 최상위 — |r|≥1인데 합 존재
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0705  [부분매핑 conf=null status=pending]
     개념: |공비|≥1인데 합 공식을 적용한다(수렴 조건 |r|<1을 무시)  · 성취기준 [12미적Ⅱ-01-05]
     학생 오사고: |공비|≥1인데 합 공식을 적용한다(수렴 조건 |r|<1을 무시).
     distractor 규칙: 정답 대신, 학생이 '|공비|≥1인데 합 공식을 적용한다(수렴 조건 |r|<1을 무시)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 조건무시
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0703  [부분매핑 conf=null status=pending]
     개념: r=1(상수)·r=−1(진동) 같은 경곗값을 구분하지 않는다. |r|<1 조건을 놓친다.  · 성취기준 [12미적Ⅱ-01-03]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## invertibility-without-1-1  (역함수 무조건 존재 · 함수)
   틀린 믿음: 모든 함수는 역함수를 갖는다
   반례: f(x) = x²는 일대일 아님(전 정의역에서) → 역함수 없음
   → M0144  [직접매핑 conf=0.92 status=pending]
     개념: 역함수 존재 조건  · 성취기준 [10기수2-03-03]
     학생 오사고: 일대일 아닌데 역함수 존재로
     distractor 규칙: 존재 판별 함정
     오류유형: 조건무시
     초안근거: 초안 최상위 — 일대일 아닌데 역함수 존재
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0644  [부분매핑 conf=null status=pending]
     개념: 역함수 f⁻¹과 1/f(분수)를 혼동한다. 일대일대응이 아닌데 역함수가 있다고 본다.  · 성취기준 [10공수2-03-03]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0859  [부분매핑 conf=null status=pending]
     개념: 역함수와 역수(1/f)를 혼동한다. 일대일대응이 아닌데 역함수가 있다고 본다. 정의역·치역 교환을 빠뜨린다.  · 성취기준 [10기수2-03-03]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## limit-equals-function-value  (극한=함숫값 가정 · 미적분)
   틀린 믿음: lim_{x→a} f(x) = f(a) (항상)
   반례: f(x)=(x²-1)/(x-1)는 x→1 극한 2지만 f(1) 무정의 (불연속점)
   → M0665  [직접매핑 conf=0.95 status=pending]
     개념: 극한값=함숫값으로 단정한다(연속이 아니어도 극한은 존재 가능). 좌극한·우극한이 다를 때 극한이 있다고 본다.  · 성취기준 [12미적Ⅰ-01-01]
     초안근거: 초안 최상위 — 극한=함숫값 단정
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0071  [부분매핑 conf=0.55 status=pending]
     개념: 극한 대입  · 성취기준 [12미적Ⅰ-01-01]
     학생 오사고: 0/0을 0으로
     distractor 규칙: 부정형을 0 처리
     오류유형: 해석오류
     초안근거: 초안 대안(P 0.55) — 인접 오개념. 직접매핑 승격 금지(초안 §0.2)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## log-distribution  (로그 합 분배 · 대수)
   틀린 믿음: log(a+b) = log a + log b
   반례: a=b=1: log 2 ≠ log 1 + log 1 = 0
   정정형: log(ab) = log a + log b
   → M0049  [직접매핑 conf=0.97 status=pending]
     개념: 로그 법칙  · 성취기준 [12대수01-05]
     학생 오사고: log(a+b)=log a+log b
     distractor 규칙: 곱셈 법칙과 혼동
     오류유형: 공식혼동
     초안근거: 초안 최상위 — log(a+b)=log a+log b 완전 일치
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0650  [부분매핑 conf=null status=pending]
     개념: log(a+b)를 log a+log b로 한다(실제 log(ab)=log a+log b). 진수·밑의 조건(>0)을 놓친다.  · 성취기준 [12대수01-04]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## mean-vs-median  (평균·중앙값 혼동 · 확률통계)
   틀린 믿음: 평균과 중앙값은 항상 같다
   반례: 치우친 분포(소득)에서 평균 ≠ 중앙값
   → M0419  [직접매핑 conf=0.9 status=pending]
     개념: 중앙값=평균  · 성취기준 [6수04-01]
     초안근거: 초안 최상위 — 중앙값=평균
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0095  [부분매핑 conf=null status=pending]
     개념: 평균·중앙값  · 성취기준 [9수04-04]
     학생 오사고: 둘 혼동, 이상치 영향 무시
     distractor 규칙: 값 바꿔 배치
     오류유형: 해석오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0595  [부분매핑 conf=null status=pending]
     개념: 평균만 대푯값으로 쓴다  · 성취기준 [9수04-01]
     학생 오사고: 평균만 대푯값으로 쓴다. 극단값이 있으면 평균이 휘둘려, 중앙값이 더 대표적임을 놓친다.
     distractor 규칙: 정답 대신, 학생이 '평균만 대푯값으로 쓴다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## mutually-exclusive-implies-independent  (배반·독립 혼동 · 확률통계)
   틀린 믿음: 배반사건이면 독립이다
   반례: 주사위 A={1}, B={2}: P(A∩B)=0 ≠ P(A)P(B)=1/36 (배반은 오히려 종속)
   → M0692  [직접매핑 conf=0.95 status=pending]
     개념: 배반(동시에 안 일어남)과 독립(서로 영향 없음)을 혼동한다(배반이면 오히려 종속).  · 성취기준 [12확통02-05]
     초안근거: 초안 최상위 — 배반이면 독립 오해
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0391  [부분매핑 conf=null status=pending]
     개념: 배반·독립 동시  · 성취기준 [12확통02-04]
     학생 오사고: 둘 동시 성립 가능으로 오판
     distractor 규칙: 관계 함정
     오류유형: 해석오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0090  [부분매핑 conf=null status=pending]
     개념: 독립·배반  · 성취기준 [12확통02-04]
     학생 오사고: 둘 혼동
     distractor 규칙: 곱셈 vs 덧셈
     오류유형: 공식혼동
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## opposite-root-selected  (반대 근 선택 · 대수)
   틀린 믿음: 두 근 중 어느 근을 답해도 상관없다
   반례: x²-5x+6=0의 두 근 2, 3 중 '큰 근'은 3 — 2를 답하면 요구와 불일치
   → M0831  [개념겹침 conf=0.4 status=pending]
     개념: x²=4에서 x=2만 답한다(x=±2, −2 누락)  · 성취기준 [10기수1-02-01]
     학생 오사고: x²=4에서 x=2만 답한다(x=±2, −2 누락). 인수분해 후 한쪽 해만 적는다.
     distractor 규칙: 정답 대신, 학생이 'x²=4에서 x=2만 답한다(x=±2, −2 누락)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 분배누락
     초안근거: 초안 v0.2(S2-p) 최근접 대안 — 'x²=4에서 x=2만' 근 일부 누락(인접 행동). 직접 대응은 S2-p 신규 저작 M0862(아래 직접매핑 행).
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0862  [직접매핑 conf=0.9 status=pending]
     개념: 이차방정식의 두 근 중 발문이 요구한 근(큰/작은)이 아닌 반대쪽 근을 답한다  · 성취기준 [10공수1-02-02]
     학생 오사고: 두 근을 모두 구하면 어느 근을 답해도 된다고 생각한다(발문의 '큰 근'/'작은 근' 선택 지시를 무시).
     distractor 규칙: 정답 근의 반대쪽(요구되지 않은) 근 값을 오답 보기로 배치
     오류유형: 조건무시
     초안근거: S2-p 신규 저작(misconceptions_v1 M0862) — 발문의 큰/작은 근 지시 무시를 직접 서술. kebab 1:1 대응(HK06·[10공수1-02-02]). 검수 후 승인·적재.
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## period-of-scaled-sine  (주기 변환 무시 · 삼각함수)
   틀린 믿음: y=sin(2x)의 주기는 2π
   반례: 주기는 π — 계수 2가 주기를 2π/2로 줄임
   → M0152  [개념겹침 conf=0.45 status=pending]
     개념: 삼각함수 진폭·주기  · 성취기준 [12미적Ⅱ-02-02]
     학생 오사고: 계수 위치 혼동
     distractor 규칙: sin2x 주기 4π로
     오류유형: 공식혼동
     초안근거: 직접 후보 부재 — 'y=sin(2x) 주기=2π' 직접 진술 없음. 초안 최근접 후보(O 0.45)·신규 M-id 저작 후보(검수 시 결정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## product-rule-naive  (곱의 미분 오류 · 미적분)
   틀린 믿음: (f·g)′ = f′·g′
   반례: f=g=x: (x²)′ = 2x ≠ 1·1 = 1
   정정형: (f·g)′ = f′·g + f·g′
   → M0075  [직접매핑 conf=0.97 status=pending]
     개념: 곱의 미분  · 성취기준 [12미적Ⅰ-02-01]
     학생 오사고: (fg)'=f'g'로
     distractor 규칙: 곱의 법칙 누락
     오류유형: 공식혼동
     초안근거: 초안 최상위 — (fg)′=f′g′ 완전 일치
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0672  [부분매핑 conf=null status=pending]
     개념: 곱의 미분을 '각각 미분한 곱'으로 한다(곱의 미분법은 따로)  · 성취기준 [12미적Ⅰ-02-04]
     학생 오사고: 곱의 미분을 '각각 미분한 곱'으로 한다(곱의 미분법은 따로). 상수배 처리를 빠뜨린다.
     distractor 규칙: 정답 대신, 학생이 '곱의 미분을 '각각 미분한 곱'으로 한다(곱의 미분법은 따로)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 분배누락
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0424  [부분매핑 conf=null status=pending]
     개념: (f+g)'=f'g'  · 성취기준 [10공수2-03-02]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## prosecutor-fallacy  (검사의 오류 · 확률통계)
   틀린 믿음: P(A|B) = P(B|A)
   반례: P(증거|무죄) ≠ P(무죄|증거) (베이즈 정리)
   → M0691  [직접매핑 conf=0.95 status=pending]
     개념: P(A|B)와 P(B|A)를 같다고 본다(검사의 역설). 분모를 전체로 둔다(조건인 A로 줄여야 함).  · 성취기준 [12확통02-04]
     초안근거: 초안 최상위 — P(A|B)=P(B|A) 완전 일치
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0091  [부분매핑 conf=null status=pending]
     개념: 조건부확률  · 성취기준 [12확통02-04]
     학생 오사고: P(A|B)와 P(B|A) 혼동
     distractor 규칙: 분모 바꿈
     오류유형: 순서오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## root-loss-by-dividing  (양변 나눗셈 근 손실 · 대수)
   틀린 믿음: ax²=bx의 양변을 x로 나누면 x=b/a (x=0 근 손실)
   반례: x²=2x를 x로 나누면 x=2만 — 실제 x(x-2)=0이라 x=0도 근
   → M0573  [직접매핑 conf=0.95 status=pending]
     개념: ax²=bx에서 양변을 x로 나눠 근(x=0)을 하나 잃는다(이항해 인수분해해야 함).  · 성취기준 [9수02-20]
     초안근거: 초안 최상위 — ax²=bx 양변 x 나눠 x=0 근 손실 일치(대안 없음)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## sign-flip-in-inequality  (부등식 부호 미반전 · 대수)
   틀린 믿음: 음수를 곱해도 부등식 부호가 그대로
   반례: -2 < 1에 -1을 곱하면 2 > -1 (부호 반전)
   → M0564  [직접매핑 conf=0.95 status=pending]
     개념: 음수를 곱하거나 나눌 때 부등호 방향을 그대로 둔다(반드시 뒤집어야 함)  · 성취기준 [9수02-11]
     학생 오사고: 음수를 곱하거나 나눌 때 부등호 방향을 그대로 둔다(반드시 뒤집어야 함).
     distractor 규칙: 정답 대신, 학생이 '음수를 곱하거나 나눌 때 부등호 방향을 그대로 둔다(반드시 뒤집어야 함)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 부호오류
     초안근거: 초안 최상위 — 음수 곱/나눗 부등호 그대로
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0028  [직접매핑 conf=0.9 status=pending]
     개념: 부등식 음수 곱  · 성취기준 [9수02-12]
     학생 오사고: 부등호 방향 안 바꿈
     distractor 규칙: -2x>4 → x>-2
     오류유형: 부호오류
     초안근거: 초안 대안(D) — 검수 반영 conf 0.90(#392). 부등호 방향 안 바꿈 정확 일치·prov=원본
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0778  [직접매핑 conf=0.75 status=pending]
     개념: 부등식에서 음수를 곱할 때 방향을 안 바꾼다  · 성취기준 [12직수02-05]
     학생 오사고: 부등식에서 음수를 곱할 때 방향을 안 바꾼다. 조건을 식으로 옮길 때 부호를 틀린다.
     distractor 규칙: 정답 대신, 학생이 '부등식에서 음수를 곱할 때 방향을 안 바꾼다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 부호오류
     초안근거: 초안 대안(D) — 검수 반영 conf 0.75(#392). 첫 절 일치·복합(조건→식)·AI생성 미검수
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## similarity-vs-congruence  (닮음·합동 혼동 · 기하)
   틀린 믿음: 닮은 두 도형은 합동이다
   반례: 배율 2인 닮음 삼각형은 합동 아님
   → M0519  [직접매핑 conf=0.9 status=pending]
     개념: 겉모습만 비슷하면(크기가 다른 닮은꼴) 합동이라 여긴다  · 성취기준 [6수03-01]
     학생 오사고: 겉모습만 비슷하면(크기가 다른 닮은꼴) 합동이라 여긴다. 뒤집힌 합동을 다른 도형으로 본다.
     distractor 규칙: 정답 대신, 학생이 '겉모습만 비슷하면(크기가 다른 닮은꼴) 합동이라 여긴다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 최상위 — 닮음을 합동으로
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0588  [부분매핑 conf=null status=pending]
     개념: 합동 조건과 닮음 조건을 혼동한다  · 성취기준 [9수03-13]
     학생 오사고: 합동 조건과 닮음 조건을 혼동한다. AA에서 각 하나만 같아도 닮음이라 본다(두 각 필요).
     distractor 규칙: 정답 대신, 학생이 '합동 조건과 닮음 조건을 혼동한다'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 조건무시
     초안근거: 초안 대안(무표기·'조건 혼동') — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## sine-distributes-over-sum  (사인 합 분배 · 삼각함수)
   틀린 믿음: sin(a+b) = sin a + sin b
   반례: a=b=90°: sin180° = 0 ≠ sin90° + sin90° = 2
   정정형: sin(a+b) = sin a cos b + cos a sin b
   → M0707  [직접매핑 conf=0.97 status=pending]
     개념: sin(a+b)=sin a+sin b로 분배한다(성립하지 않음). 코사인 덧셈정리의 부호(−)를 틀린다.  · 성취기준 [12미적Ⅱ-02-02]
     초안근거: 초안 최상위 — sin(a+b)=sin a+sin b. 직접 후보 유일·얇음(초안 §3 우선 검수)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## square-root-positivity  (제곱근 양수 가정 · 대수)
   틀린 믿음: √(x²) = x
   반례: x=-3이면 √(x²) = 3 = |x|, x가 아님
   정정형: √(x²) = |x|
   → M0550  [직접매핑 conf=0.95 status=pending]
     개념: √(a²)=a로 단정한다(실제 |a|, a가 음수면 부호 주의). √a+√b를 √(a+b)로 합친다.  · 성취기준 [9수01-07]
     초안근거: 초안 최상위 — √(a²)=a 단정(실제 |a|)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0647  [직접매핑 conf=0.85 status=pending]
     개념: √(a²)=a로 단정한다(실제 |a|). 음수의 짝수 거듭제곱근을 실수에서 구하려 한다.  · 성취기준 [12대수01-01]
     초안근거: 초안 대안(D) — 검수 반영 conf 0.85(#392). √(a²)=a 정확 일치(거듭제곱근판)·최상위 M0550(0.95) 미만
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0109  [부분매핑 conf=null status=pending]
     개념: 음수의 거듭제곱근  · 성취기준 [9수01-07]
     학생 오사고: √((-3)²)=-3
     distractor 규칙: 정답 3에 -3
     오류유형: 부호오류
     초안근거: 초안 대안(P 표기) — conf 미명시
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## term-to-zero-implies-convergence  (항→0이면 수렴 가정 · 수열)
   틀린 믿음: 일반항이 0에 수렴하면 급수도 수렴한다
   반례: 조화급수 Σ1/n은 일반항→0이지만 발산
   → M0704  [직접매핑 conf=0.95 status=pending]
     개념: 일반항이 0으로 가면 급수가 수렴한다고 단정한다(조화급수 Σ1/n은 0으  · 성취기준 [12미적Ⅱ-01-04]
     학생 오사고: 일반항이 0으로 가면 급수가 수렴한다고 단정한다(조화급수 Σ1/n은 0으로 가도 발산).
     distractor 규칙: 정답 대신, 학생이 '일반항이 0으로 가면 급수가 수렴한다고 단정한다(조화급수 Σ1/n은 0으로 가도 발산)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 해석오류
     초안근거: 초안 최상위 — 항→0이면 수렴 단정(조화급수 반례)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0331  [부분매핑 conf=null status=pending]
     개념: 급수 수렴·발산 판정  · 성취기준 [12대수03-01]
     학생 오사고: 항이 0이면 수렴으로
     distractor 규칙: 필요조건 함정
     오류유형: 조건무시
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

## translation-sign-flip  (평행이동 부호 혼동 · 함수)
   틀린 믿음: y=f(x−a)는 왼쪽으로 a만큼 평행이동
   반례: y=(x−2)²의 꼭짓점은 x=2 (오른쪽으로 +2 이동)
   → M0411  [직접매핑 conf=0.9 status=pending]
     개념: y=f(x+1)은 오른쪽 이동  · 성취기준 [10기수2-01-06]
     초안근거: 초안 최상위 — 평행이동 부호 반전
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 ✓
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0850  [부분매핑 conf=null status=pending]
     개념: 이동 방향과 부호를 반대로 한다(오른쪽 a 이동인데 x+a 대입).  · 성취기준 [10기수2-01-06]
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject
   → M0632  [부분매핑 conf=null status=pending]
     개념: +a 평행이동인데 식을 x+a로 바꾼다(실제 x−a, 방향과 부호가 반대  · 성취기준 [10공수2-01-06]
     학생 오사고: +a 평행이동인데 식을 x+a로 바꾼다(실제 x−a, 방향과 부호가 반대).
     distractor 규칙: 정답 대신, 학생이 '+a 평행이동인데 식을 x+a로 바꾼다(실제 x−a, 방향과 부호가 반대)'처럼 잘못 처리한 결과를 오답 보기로 배치
     오류유형: 부호오류
     초안근거: 초안 대안(무표기) — link/conf 미명시·부분매핑 보수 전사(검수 시 확정)
     ── 검수 체크리스트 ──
     기계 전제(promote): kebab∈카탈로그 ✓ · M-id∈코퍼스 ✓ · 직접매핑 conf≥0.6 해당없음
     교수학 판단(Kiki): [ ] canonical·반례 타당  [ ] 4지선다 귀속 타당  [ ] approve  [ ] reject

{"statuses":["pending"],"kebab_groups":34,"candidates":81,"kebab_not_in_catalog":[],"dangling_mis_ids":[],"gate_blocked_mis_ids":[]}
```

## §5. 결정 체크리스트 표 (81행 · 검수 큐 1:1)

각 행에 승인/반려/보류를 표기하고 메모를 남긴다(단일 진실 원천 = 검수 큐 JSON; 이 표는 파생).
`link_type` + `conf`는 큐 값 그대로. flag: ⚠동률 · △직접부재 · ★얇음(후보1) · 신규저작 ·
‼직접conf<0.6(직접매핑인데 임계 미달 — 승격 금지 대상).

| # | kebab_id | mis_id | link_type | conf | flag | 승인/반려/보류 | 검수 메모 |
|---|---|---|---|---|---|---|---|
| 1 | distribution-over-power | M0019 | 직접매핑 | 0.95 |  |  |  |
| 2 | distribution-over-power | M0572 | 직접매핑 | 0.8 |  |  |  |
| 3 | distribution-over-power | M0649 | 부분매핑 | — |  |  |  |
| 4 | sign-flip-in-inequality | M0564 | 직접매핑 | 0.95 |  |  |  |
| 5 | sign-flip-in-inequality | M0028 | 직접매핑 | 0.9 |  |  |  |
| 6 | sign-flip-in-inequality | M0778 | 직접매핑 | 0.75 |  |  |  |
| 7 | division-by-zero | M0003 | 직접매핑 | 0.85 |  |  |  |
| 8 | division-by-zero | M0556 | 부분매핑 | 0.5 |  |  |  |
| 9 | division-by-zero | M0146 | 부분매핑 | — |  |  |  |
| 10 | square-root-positivity | M0550 | 직접매핑 | 0.95 |  |  |  |
| 11 | square-root-positivity | M0647 | 직접매핑 | 0.85 |  |  |  |
| 12 | square-root-positivity | M0109 | 부분매핑 | — |  |  |  |
| 13 | exponent-zero | M0105 | 직접매핑 | 0.92 | ★얇음(후보1) |  |  |
| 14 | fraction-cancellation | M0118 | 직접매핑 | 0.8 |  |  |  |
| 15 | fraction-cancellation | M0503 | 개념겹침 | 0.45 |  |  |  |
| 16 | log-distribution | M0049 | 직접매핑 | 0.97 |  |  |  |
| 17 | log-distribution | M0650 | 부분매핑 | — |  |  |  |
| 18 | discriminant-negative-no-real-root | M0610 | 직접매핑 | 0.95 |  |  |  |
| 19 | discriminant-negative-no-real-root | M0832 | 부분매핑 | — |  |  |  |
| 20 | discriminant-negative-no-real-root | M0124 | 부분매핑 | — |  |  |  |
| 21 | root-loss-by-dividing | M0573 | 직접매핑 | 0.95 | ★얇음(후보1) |  |  |
| 22 | angle-sum-non-triangle | M0493 | 직접매핑 | 0.85 |  |  |  |
| 23 | angle-sum-non-triangle | M0580 | 부분매핑 | — |  |  |  |
| 24 | angle-sum-non-triangle | M0051 | 개념겹침 | — |  |  |  |
| 25 | similarity-vs-congruence | M0519 | 직접매핑 | 0.9 |  |  |  |
| 26 | similarity-vs-congruence | M0588 | 부분매핑 | — |  |  |  |
| 27 | area-perimeter-confusion | M0529 | 직접매핑 | 0.95 |  |  |  |
| 28 | area-perimeter-confusion | M0782 | 부분매핑 | — |  |  |  |
| 29 | area-perimeter-confusion | M0052 | 부분매핑 | — |  |  |  |
| 30 | circle-radius-squared | M0630 | 직접매핑 | 0.93 | ⚠동률 |  |  |
| 31 | circle-radius-squared | M0848 | 직접매핑 | 0.93 | ⚠동률 |  |  |
| 32 | circle-radius-squared | M0732 | 부분매핑 | — | ⚠동률 |  |  |
| 33 | gambler-fallacy | M0688 | 직접매핑 | 0.98 |  |  |  |
| 34 | gambler-fallacy | M0093 | 부분매핑 | — |  |  |  |
| 35 | gambler-fallacy | M0794 | 부분매핑 | — |  |  |  |
| 36 | prosecutor-fallacy | M0691 | 직접매핑 | 0.95 |  |  |  |
| 37 | prosecutor-fallacy | M0091 | 부분매핑 | — |  |  |  |
| 38 | mean-vs-median | M0419 | 직접매핑 | 0.9 |  |  |  |
| 39 | mean-vs-median | M0095 | 부분매핑 | — |  |  |  |
| 40 | mean-vs-median | M0595 | 부분매핑 | — |  |  |  |
| 41 | mutually-exclusive-implies-independent | M0692 | 직접매핑 | 0.95 |  |  |  |
| 42 | mutually-exclusive-implies-independent | M0391 | 부분매핑 | — |  |  |  |
| 43 | mutually-exclusive-implies-independent | M0090 | 부분매핑 | — |  |  |  |
| 44 | invertibility-without-1-1 | M0144 | 직접매핑 | 0.92 |  |  |  |
| 45 | invertibility-without-1-1 | M0644 | 부분매핑 | — |  |  |  |
| 46 | invertibility-without-1-1 | M0859 | 부분매핑 | — |  |  |  |
| 47 | composite-function-commutes | M0643 | 직접매핑 | 0.95 |  |  |  |
| 48 | composite-function-commutes | M0858 | 부분매핑 | — |  |  |  |
| 49 | composite-function-commutes | M0038 | 부분매핑 | — |  |  |  |
| 50 | translation-sign-flip | M0411 | 직접매핑 | 0.9 |  |  |  |
| 51 | translation-sign-flip | M0850 | 부분매핑 | — |  |  |  |
| 52 | translation-sign-flip | M0632 | 부분매핑 | — |  |  |  |
| 53 | chain-rule-inner-derivative-omitted | M0370 | 직접매핑 | 0.9 |  |  |  |
| 54 | chain-rule-inner-derivative-omitted | M0710 | 부분매핑 | — |  |  |  |
| 55 | chain-rule-inner-derivative-omitted | M0077 | 부분매핑 | — |  |  |  |
| 56 | product-rule-naive | M0075 | 직접매핑 | 0.97 |  |  |  |
| 57 | product-rule-naive | M0672 | 부분매핑 | — |  |  |  |
| 58 | product-rule-naive | M0424 | 부분매핑 | — |  |  |  |
| 59 | limit-equals-function-value | M0665 | 직접매핑 | 0.95 |  |  |  |
| 60 | limit-equals-function-value | M0071 | 부분매핑 | 0.55 |  |  |  |
| 61 | continuity-implies-differentiability | M0670 | 직접매핑 | 0.97 |  |  |  |
| 62 | continuity-implies-differentiability | M0176 | 부분매핑 | — |  |  |  |
| 63 | continuity-implies-differentiability | M0345 | 부분매핑 | — |  |  |  |
| 64 | critical-point-implies-extremum | M0080 | 직접매핑 | 0.95 |  |  |  |
| 65 | critical-point-implies-extremum | M0675 | 부분매핑 | — |  |  |  |
| 66 | critical-point-implies-extremum | M0349 | 부분매핑 | — |  |  |  |
| 67 | geometric-series-always-converges | M0209 | 직접매핑 | 0.92 |  |  |  |
| 68 | geometric-series-always-converges | M0705 | 부분매핑 | — |  |  |  |
| 69 | geometric-series-always-converges | M0703 | 부분매핑 | — |  |  |  |
| 70 | term-to-zero-implies-convergence | M0704 | 직접매핑 | 0.95 |  |  |  |
| 71 | term-to-zero-implies-convergence | M0331 | 부분매핑 | — |  |  |  |
| 72 | sine-distributes-over-sum | M0707 | 직접매핑 | 0.97 | ★얇음(후보1) |  |  |
| 73 | period-of-scaled-sine | M0152 | 개념겹침 | 0.45 | △직접부재 ★얇음(후보1) |  |  |
| 74 | dot-product-is-vector | M0735 | 직접매핑 | 0.95 |  |  |  |
| 75 | dot-product-is-vector | M0262 | 부분매핑 | — |  |  |  |
| 76 | opposite-root-selected | M0831 | 개념겹침 | 0.4 |  |  |  |
| 77 | factor-sign-flip | M0848 | 개념겹침 | 0.45 |  |  |  |
| 78 | opposite-root-selected | M0862 | 직접매핑 | 0.9 | 신규저작 |  |  |
| 79 | factor-sign-flip | M0863 | 직접매핑 | 0.9 | 신규저작 |  |  |
| 80 | extremum-max-min-confused | M0864 | 직접매핑 | 0.9 | ★얇음(후보1) 신규저작 |  |  |
| 81 | extremum-value-vs-point-confused | M0865 | 직접매핑 | 0.9 | ★얇음(후보1) 신규저작 |  |  |

<!-- 재생성: 아래 §재생성 명령 참조 · 원천 검수 큐 81행 · kebab 34종 -->

### §재생성 명령 (이 표)

```bash
cd src/backend && python - <<'EOF'
import json
from collections import Counter
q=json.load(open("../../docs/data/misconception_crosslink_review_queue.json"))
rows=q["review_queue"]
ambiguous_tie={"circle-radius-squared"}; no_direct={"period-of-scaled-sine"}
new_authored={"M0862","M0863","M0864","M0865"}
per=Counter(r["kebab_id"] for r in rows)
def fl(r):
    f=[]; k=r["kebab_id"]; m=r["mis_id"]; lt=r["link_type"]; c=r["confidence"]
    if k in ambiguous_tie: f.append("⚠동률")
    if k in no_direct: f.append("△직접부재")
    if per[k]==1: f.append("★얇음(후보1)")
    if m in new_authored: f.append("신규저작")
    if lt=="직접매핑" and (c is None or c<0.6): f.append("‼직접conf<0.6")
    return " ".join(f)
print("| # | kebab_id | mis_id | link_type | conf | flag | 승인/반려/보류 | 검수 메모 |")
print("|---|---|---|---|---|---|---|---|")
for i,r in enumerate(rows,1):
    c=r["confidence"]; cs="—" if c is None else f"{c:g}"
    print(f"| {i} | {r['kebab_id']} | {r['mis_id']} | {r['link_type']} | {cs} | {fl(r)} |  |  |")
EOF
```

---

## 참고

- 정본 계약: `docs/standards/crosswalk_gate_contract.md` · 코드 정본
  `src/backend/whymath_backend/l1/misconception/crosslink_gate.py` · 동결
  `tests/backend/l1/test_crosslink_gate_contract.py`.
- 초안(매핑 근거·변경이력): `docs/data/misconception_crosslink_candidates.md`.
- 승격·적재 도구: `.../l4/misconception/crosslink_review.py`(`promote --load`) ·
  적재기 `.../l1/misconception/crosslink_loader.py` · 해석 `crosslink_resolve.py`.
- 게이트가 막는 태스크: `backlog/tasks/S2-01-equiv-problems-100.yaml`(requires_gates).
- 원칙: CLAUDE.md 의사결정 우선순위 #1 학생 안전·#3 교수학 정확성.
