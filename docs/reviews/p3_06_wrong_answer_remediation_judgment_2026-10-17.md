# P3-06 판정 — 오답 → Error Signature → 오개념 후보·confidence → Remediation Strategy

> **판정 기준: main `63fe19ddc0d14edc0a5d4a6b9442fcbbfd3e6dad`** (2026-10-17 · `P3-53: P3-G1 Week 1 Gate 재판정 — main e35692ef 기준 PASS (#1668)`).
> 이 문서가 더하는 코드·데이터·테스트는 작업 브랜치 `claude/p3-06-wrong-answer-remediation-slice`에 있고 **머지 전에는 main에 없다.** 아래 §1의 수치는 그 브랜치에서 CLI를 실행해 얻은 값이다.
> **소유 태스크**: `P3-06-wrong-answer-remediation-pipeline` · 선행 `P3-05-triangle-density`(trunk에서 done).

---

## §0. 한 줄 결론 (초보자용)

학생이 객관식에서 **틀린 보기를 고르면** → 어떤 오개념인지 후보와 신뢰도가 나오고 → 같은 오류가 쌓일수록 교정 강도가 올라가는 전 과정이, 핵심 오개념 12개 중 **7개에서 실제로 돕니다.** 나머지 **5개는 "오개념 이름표(kebab)" 자체가 없어서 막혀 있고**, 그건 제가 임의로 만들 수 없는 Kiki님의 결정 사항입니다. 그래서 완료 판정은 **미충족(7/12)** 입니다.

| 용어 | 뜻 |
|---|---|
| Error Signature(오류 서명) | "학생이 이런 오답을 냈다"는 구조화된 흔적. 여기서는 (어떤 문항, 몇 번 보기) 한 쌍 + 그 보기에 붙은 오개념 이름표 |
| kebab | 런타임 오개념 카탈로그의 이름표(예: `power-rule-step-omitted`). 학생 풀이에서 오개념을 알아채는 쪽 |
| M-id | 오개념 코퍼스의 번호(예: `M0671`). 리포트에 뜨는 쪽. kebab↔M-id 연결은 사람이 서명한 크로스워크만 인정 |
| 사다리(Escalation) | 같은 오개념이 2·3·4번 쌓이면 개입 강도를 교정 설명 → 쉬운 문항 → 선수 개념 순으로 올리는 P-09 정책 |

## §1. 완료 판정 대조

원 문서의 완료 판정: "대표 과정 핵심 오개념 각각에 대해 오답 → 오개념 후보·confidence → 교정 전략이 산출되고, 변별력 주입이 RED".

| 조건 | 결과 | 근거 |
|---|---|---|
| 핵심 오개념 12개 각각에 오답 → 후보·confidence → 교정 전략 산출 | **미충족 (7/12)** | 아래 표. 5개는 좌석 없음(blocked) |
| 변별력 주입이 RED | **충족** | §4 — 주입 테스트 + 코드 뮤테이션 14종 전건 검출, 생존 0 |
| 정답을 오개념으로 잡는 오탐 픽스처 | **충족** | §4 — 정답 픽스처 12건 전부 후보 0 · 오탐 주입이 RED |
| 오개념은 LLM 초기 context에 preload하지 않는다 | **충족** | 새 모듈 3개에 LLM 경로 임포트 0(AST 테스트) · 카탈로그는 역추적된 id 하나를 확인할 때만 조회(폭탄 카탈로그 테스트) |
| ID는 기존 kebab↔M-id 크로스워크 경유 | **충족** | 새 ID 체계 0 · M-id는 승인 크로스워크(`select_canonical`)로만 도출 |

### 커버리지 표 (핵심 오개념 12개 — 분모는 P3-01 명세)

실행: `python -m whymath_backend.ops.phase3_remediation` (종료 코드 **1** — 5개가 막혀 있어서).

| M-id | 개념 | 상태 | kebab | 리포트 id | 오답/정답 픽스처 | 첫 신뢰도 | 사다리(1→4회) |
|---|---|---|---|---|---|---|---|
| M0075 | 02-01 | served | product-rule-naive | M0075 | 2/2 | 0.80 | none→교정 설명→쉬운 문항→선수 개념 |
| M0080 | 02-01 | served | critical-point-implies-extremum | M0080 | 2/2 | 0.80 | 동일 |
| M0670 | 02-02 | served | continuity-implies-differentiability | M0670 | 2/2 | 0.80 | 동일 |
| M0671 | 02-03 | served | power-rule-step-omitted | M0671 | 4/2 | 0.80 | 동일 |
| M0672 | 02-04 | **shadowed** | product-rule-naive | **M0075** | 2/2 | 0.80 | 동일 |
| M0673 | 02-05 | **blocked** | — | — | — | — | — |
| M0674 | 02-06 | **blocked** | — | — | — | — | — |
| M0864 | 02-07 | served | extremum-max-min-confused | M0864 | 2/2 | 0.80 | 동일 |
| M0865 | 02-07 | served | extremum-value-vs-point-confused | M0865 | 4/2 | 0.80 | 동일 |
| M0676 | 02-08 | **blocked** | — | — | — | — | — |
| M0677 | 02-09 | **blocked** | — | — | — | — | — |
| M0678 | 02-10 | **blocked** | — | — | — | — | — |

- **served 6** = 체인 전 구간 + 리포트 id가 자기 자신.
- **shadowed 1 (M0672)** = 체인은 돌지만 같은 kebab을 쓰는 M0075가 canonical(0.97 vs 0.85, strict 최대 단독)이라 **리포트에는 M0075로 나간다.** 한 kebab으로는 둘을 구별할 수 없다 → `P3-59`.
- **blocked 5** = 승인 크로스워크에 이 M-id로 닿는 kebab이 없다. 2026-10-06 Kiki님이 게이트 `G-misc40-unseated-concepts-disposition`에서 "안 E 보류(P3-02 이후 재판정)"로 결정했고, 2026-10-17 이번 세션에서 "7개만 완성, 5개는 막힘으로 정직 보고"로 결정했다. **서명 없는 kebab·크로스링크를 세션이 만들지 않았다.**

### 오개념별 교정 전략 (실데이터 — 같은 오답 4회 누적)

신뢰도는 0.80 → 0.939 → 0.964 → 0.968로 쌓인다(Phase 2 규칙 그대로). 교정 하한(0.7 초과)은 첫 회부터 넘는다. 추천 행위는 전부 `practice_current`(이유 `misconception_remediation`).

| kebab | 개입 패턴(1회→2회~) | 3회 쉬운 문항(문항 id 앞 8자) | 4회 선수 원자 |
|---|---|---|---|
| power-rule-step-omitted | 거꾸로 사고 → 반례 유도 | 012aef69 · 06d93371 · 0f510e63 | 12미적Ⅰ-02-01-1 · 02-02-3 · 02-04-1 |
| product-rule-naive | 〃 | 0f6bfaab · 127bf12b · 18ea1bad | 12미적Ⅰ-01-02-1 · 01-04-3 · 02-01-1 |
| critical-point-implies-extremum | 〃 | 0f6bfaab · 127bf12b · 18ea1bad | 〃 |
| continuity-implies-differentiability | 〃 | 1d06509c · 41fa50b1 · 55cbac84 | 12미적Ⅰ-01-03-1 · 02-01-1 · 02-01-3 |
| extremum-max-min-confused | 〃 | 199087ff · 2a80aea5 · 37be4bee | 12미적Ⅰ-02-04-1 · 02-06-3 · 02-07-1 |
| extremum-value-vs-point-confused | 〃 | 〃 | 〃 |

- 2회째 "교정 설명"의 근거는 카탈로그의 `counterexample` 문장이다(예: x=2에서 (x³)′ 값 비교).
- 쉬운 문항·선수 원자는 **틀린 문항의 개념**에서 코퍼스를 따라가 해소한다(오개념의 개념이 아니다 — 한 kebab이 여러 개념의 문항에 퍼져 있어서, 예: power-rule은 02-03 외에 02-05·02-10 문항에도 달려 있다).
- **교수 전략은 전부 `ANALOGY`다.** 런타임 선택기(`runtime_selector.select`)의 R2 규칙이 "오개념 가설이 있으면 ANALOGY"이고, 오개념별 정밀화(error_type ↔ suitable_error_types)는 어휘 교집합이 0이라 `P3-23`이 판정하도록 보류돼 있다. 이 슬라이스는 그 선택기를 **그대로 호출**했고 새 간선을 만들지 않았다 — 그래서 "Pedagogy와 연결됐다"는 말은 맞지만 "오개념별로 다르다"는 말은 틀리다.

## §2. 무엇을 어떻게 연결했나 (새 탐지기 0)

기존 Phase 2 부품을 채점 경로와 같은 순서·규칙으로 조립했다. 새 탐지 알고리즘·새 Entity·스키마 변경·LLM 호출이 없다.

- 서명·후보: `distractor_link`(품질 게이트 floor 0.65 통과분만) — 학생이 고른 보기 → 그 문항 `distractor_map` 항목.
- 가설: `attempt_hypothesis_policy` 6칸 표 + `hypothesis.update_hypotheses` — 오답 강화 · 정답은 1턴 감쇠 · 충돌(정답으로 보고했는데 오답 보기)은 무변화.
- 개입: `intervene.select_intervention_from_hypotheses` — 신뢰도 >0.8 반례 유도, 0.5~0.8 거꾸로 사고.
- P-09: `MISCONCEPTION_REMEDIATION_FLOOR`(0.7 초과)와 반복 오류 사다리(2/3/4회).
- 교수 전략: `runtime_selector.select`.

새 코드: 로더 `l1/standards/phase3_remediation_spec.py` · 체인 `l4/misconception/remediation_strategy.py`(순수·수학 어휘 없음) · CLI `ops/phase3_remediation.py` · 데이터 `data/corpus/phase3_remediation_v1/`. 기존 파일은 `phase3_coverage.py`에 공개 창구 `concept_facts` 1개만 추가했다.

## §3. 단답형은 범위 밖 (Kiki님 결정 2026-10-17)

대표 과정 승인 문항 중 **단답형 885건은 지금 어떤 채널로도 후보가 0건**이다. 오답 2,534회를 넣었을 때 후보 0건(훑기 `ran_no_candidate` 2,508 · `not_run` 26). 숫자 하나를 답하는 문항이라 "문항 식 = 학생 답" 등식이 만들어지지 않는다. "예측 오답값 매처"는 새 탐지기라 금지 사항에 걸려 구현하지 않고 `P3-56`으로 등재했다.

## §4. 변별력·오탐 — 막으려는 상태를 실제로 넣고 RED를 확인

정상 입력에서 초록인 것은 증거가 아니라서 두 층으로 확인했다.

**(1) 상태 주입 테스트** (`tests/backend/ops/test_phase3_remediation.py` 등, 모든 주입은 `mutated != original` 선단언):

| 주입한 상태 | 결과 |
|---|---|
| 서명(픽스처) 제거 | 그 오개념만 blocked — 다른 행은 영향 없음 |
| 오답 보기 항목 삭제 / 엉뚱한 오개념으로 재라벨 / 카탈로그에 없는 raw id | 해당 행 failed, raw id는 `dropped_reason=unknown_misconception`으로 사유 표기 |
| **정답 보기를 오개념으로 라벨** (오탐) | 정답 픽스처가 RED ("정답 보기에서 오개념 후보가 나왔다") |
| 탐지기가 엉뚱한 오개념을 0.79로 같이 냄 | RED ("후보가 단 하나가 아니다") |
| 크로스링크 제거 / canonical 뒤집기 / 동률 | blocked / served↔shadowed 반전 / 동률은 추측 없이 shadowed |
| P-09 사다리 경계를 한 칸 밀기 | RED (기대 사다리가 정책 표 밖에 독립 정의되어 있어서) |
| 선지 신뢰도 0.6 (<0.65) | 후보 0건 + `below_floor` — **신호가 약하면 단정하지 않는다** |
| 신뢰도 0.70 / 0.71 | 0.70은 교정 하한 미달(RED), 0.71은 통과 — **경계 양쪽을 밟음** |
| 쉬운 문항만 / 선수 간선만 제거 | 그 등급만 RED, 다른 등급은 영향 없음 |

**(2) 코드 뮤테이션 14종** (CLI·체인 소스를 직접 깨뜨림 — 치환 대상 1건·`mutated != original`·백업 바이트 복원·복원 바이트 동일 단언): **14/14 검출, 생존 0.** 1차 실행에서 4종이 살아남았다 — 원인은 ① 동치 뮤턴트 2종(`x or []`, 정답 회차에서 비어 있는 `matches` 적용), ② 다른 검사가 같은 실패를 가리던 1종, ③ 현 파이프라인에서 도달 불가였던 방어선 1종이었다. 절을 지우지 않고 뮤턴트를 교체하고 테스트를 보강(충돌 회차·정답 픽스처가 사실은 오답인 경우·탐지기 레벨 오염 주입)해 14/14로 만들었다.

## §5. 작동한 비율 — 측정과 서빙이 어긋나는 구간 (신규 발견)

객관식 오답 보기를 실제로 골랐을 때(범위 내 승인 문항 전체): **378건 중 후보 산출 366건. 12건은 조용히 버려진다** — 오답 보기가 kebab이 아니라 M-id `M0674`를 그대로 가리키는데, 런타임(`distractor_link_matches`)은 카탈로그에 없는 id를 버린다. 반면 P3-02 계측기(`_reached_misconceptions`)는 M-id 형태를 "닿음"으로 센다. **계측은 연결됐다고 말하고 서빙은 아무것도 안 한다.** `P3-44`가 "02-06은 M0674를 직접 기입했는데도 미충족 — 원인 미규명"이라고 적은 현상의 한 원인일 수 있다 → `P3-57`.

## §6. 정직한 공백과 별건

| 항목 | 상태 |
|---|---|
| 핵심 오개념 5개(M0673·M0674·M0676·M0677·M0678) | 막힘 — kebab·크로스링크 신설은 Kiki 서명 필요. 재판정은 게이트 `G-misc40-unseated-concepts-disposition`(보류 clear)의 후속. P3-02는 착지했으므로 재판정 시점이 도래했다 |
| 단답형 885문항 | `P3-56` |
| raw M-id 12건 계측/서빙 불일치 | `P3-57` |
| 핵심 kebab 4개 op-code 공백(power-rule · product-rule · critical-point · continuity) | `P3-58` — 카탈로그에 더하면 `misconception_mc_batch`의 op-code 역유도가 바뀌어 승인 코퍼스 재생성과 어긋날 수 있어 이번엔 더하지 않았다 |
| M0672가 M0075에 가려짐 | `P3-59` |
| 선지 신뢰도 0.8이 반례 임계(>0.8)에 걸려 첫 오답은 항상 "거꾸로 사고" | `P3-60` — confidence 규칙은 Phase 2 것을 그대로 썼고 바꾸지 않았다 |
| 판정자가 같은 모델 계열 | 해당 없음(이 항목은 LLM 판정을 쓰지 않았다) |
| 오답 보기 라벨의 수학적 정당성 | 픽스처 6쌍(12문항 선택)을 **`distractor_map` 라벨과 독립인 SymPy 계산**으로 검산했다(`TestFixtureSoundness`): 정답 보기 = 실제 미분·극값 계산값, 오답 보기 = 그 오개념이 만드는 값(예: x⁸의 f′(2)=1024, 오답 128=2⁷은 계수 누락 · 2048=8·2⁸은 지수 미감소). 잘못된 오답 픽스처를 넣으면 RED임을 확인했다. **픽스처 밖의 오답 보기 378건 전수 검산은 하지 않았다** — 오답 보기 라벨은 ASM-06 승계 제약대로 "가설의 근거이지 판정이 아니다" |

## §7. 검증 범위 (CI 잡 대조)

변경이 닿는 잡 판정(`ci_job_coverage scope`): 닿음 4 · 상시 6 · 안 닿음 7 · 야간 3. 재현 불가 2잡은 근거를 적는다.

- `backend-migrations`(Postgres 서비스 필요): 이 PR은 alembic 리비전·ORM 모델·스키마 변경이 **0건**이라 닿지만 영향이 없다고 판단 — 단, 로컬 재현은 하지 않았다.
- `docker-build`: Dockerfile·빌드 입력 변경 0건 — 로컬 재현 불가.

그 외 잡의 로컬 미러 결과는 PR 본문에 적는다.
