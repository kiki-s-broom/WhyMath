# Phase 3 지표 7종 계약 (제품 완성도 평면) — 정본

> **집행 코드**: `src/backend/whymath_backend/ops/phase3_metrics.py`
> **좌석**: `P3-14-phase3-metrics-cli`
> **판정 기준**: origin/main `713512bc` (2026-10-09 실측)
> **명령**: `python -m whymath_backend.ops.phase3_metrics` (자가 점검: `--self-check`)

Phase 3 실행 지시문 [19] 가 요구한 "지표 7종을 **한 명령**으로 산출하고, 각각 **위반 주입에 반응**"하는
실행기의 계약이다. 이 문서는 ① 이 저장소에 이미 있는 지표 묶음들과의 **평면 구분** ② 7종의 정의·출처·
흡수 근거 ③ 현재 상태 ④ 목표가 아직 확정되지 않았다는 사실 ⑤ 지시문과 저장소가 어긋난 곳을 고정한다.

---

## 1. 평면 구분 — 지표 묶음은 이미 다섯이다

분모가 다르면 같은 표에 얹지 않는다. 얹으면 "KPI 17종·22종"이라는 하나의 평균이 생기고, 그 평균은 한 평면이
잘 되는 것으로 다른 평면의 붕괴를 덮는다(붕괴 연쇄 ④ "truth source가 하나가 아님"). 아래는 **현재 저장소의
전 평면**이다. 이 7종은 맨 아래 행이고, 앞의 네 묶음을 대체하지도 편입하지도 않는다.

| 평면 | 묶음 | 집행 | 재는 것 | 분모 | 판정 시점·성격 | 정본 문서 |
|---|---|---|---|---|---|---|
| 생산 공정 | **KPI 12종** (Hard Gate F-Ⅰ~Ⅴ + 기술 6 + 내용 6) | `ops/validation_scorecard.py` | 콘텐츠가 얼마나 싸고 정확하게 만들어지나(CU당 시간·비용·오류율) | 생산된 콘텐츠 단위(CU) | 12/31 최종 G5 · 판정기 | `docs/standards/eos_verification_design_v1.md` §5·§6 |
| 생산 공정(주간) | **기술 KPI 6종** (HIT·자동검증률·재작업률·처리량·단위비용·실패유형) | `ops/weekly_metrics_report.py` | 12종 중 기술 6종의 주간 집계 | 이번 주 생성·검수 로그 | 주간 cron · 관측 | 같은 문서 §6 |
| 학습 루프 | **Phase 2 루프 KPI 5종** (완주·정합·설명가능·수기개입·역추적) | `ops/loop_kpi_gate.py` | 학생 한 명의 루프가 끝까지 흐르나 | 실행된 학습 루프(세션) | 상시(운영 관측창) · 판정기 | `docs/standards/loop_kpi_contract.md` |
| 구조 | **Phase 1 구조 지표 5종** | `ops/phase1_structure_report.py` | 구조 계약이 얼마나 섰나 | 계획서 200 §27·§39 가 고정한 항목 | 관측 · **판정기 아님**(exit 로 합격 선언 안 함) | 모듈 docstring |
| **제품 완성도** | **Phase 3 지표 7종 (이 문서)** | `ops/phase3_metrics.py` | **대표 과정이 얼마나 채워졌나** | 대표 과정 범위 명세(`scope_spec.yaml`)가 동결한 노드·개념·스킬·승인 문항 | Phase 3 Release Gate · 판정기 | 이 문서 |

**이름 충돌 주의 — "coverage"**. `harness/objective_coverage.py`(CUR-02)와 `harness/problem_bank_coverage.py`
(ARCH-18)도 coverage 를 말하지만 분모가 다르다(성취기준 895건·문제은행 전체). 이 7종의 `Curriculum Coverage`
는 **대표 과정 10노드**가 분모이며, 출력 이름에 범위(`[대표 과정 10노드]`)를 박는다.

경계를 코드가 지킨다: 출력 헤더와 JSON 에 평면 이름(`plane`·`other_plane`)이 박히고, 종합 점수를 만들지 않으며
(`종합 점수 없음`), 지표 이름 공간이 다른 평면과 겹치지 않음을 테스트가 확인한다
(`test_metric_names_do_not_collide_with_other_planes`).

---

## 2. 7종 정의 — 분자 · 분모 · 출처 · 목표

임계는 **각 정본이 갖는다**. 이 CLI 는 수치를 복제하지 않고 읽거나 import 한다(`test_absorbed_numbers_are_not_duplicated_in_source`).

| # | 지표 | 분자 | 분모 | 출처 | 목표(읽는 곳) |
|---|---|---|---|---|---|
| ① | Curriculum Coverage | Curriculum → Concept → Skill → Problem 경로가 있는 노드 | 대표 과정 교육과정 노드(10) | `l1.standards.phase3_coverage` (P3-02) **재사용** | 명세 `targets.curriculum_coverage` |
| ② | Concept Completeness | 연결 5종(Prerequisite·Misconception·Solution·Hint·Pedagogy)이 **전부 linked** 인 핵심 개념 | 핵심 개념(10) | 같은 모듈 **재사용** — §3 재설계본 | 명세 `targets.concept_completeness` |
| ③ | Problem Coverage | 승인 문항이 1건 이상 행사하는 스킬 | 명세 `skills`(8) | **신규 계산**(아래) | 명세 `targets.problem_coverage_by_skill` |
| ④ | Solution QA Pass | 재검증 통과 문항 | 재검증 통과 + 실패 문항 | `harness.corpus_reverify.reverify_corpus` (승인 ∧ 대표 과정 PRIMARY 문항 전수) | `1 − ` 스코어카드 `수학적 오류율` ceiling (**흡수**) |
| ⑤ | Learning Loop Success | `loop_kpi_gate` LOOP_COMPLETION 의 분자 | 같은 분모 | `ops.loop_kpi_gate` **그대로 재사용**(새 정의 없음) | `LOOP_KPI_SPECS` 의 임계(Wilson 하한) |
| ⑥ | Critical Defect | 해당(triggered) Hard Gate 수 | Hard Gate 5종 | `ops.validation_scorecard.evaluate_hard_gates` F-Ⅰ~Ⅴ **그대로 흡수** | 0건 |
| ⑦ | Graph Connectivity Coverage | Concept → Skill → Problem → Misconception → Pedagogy 가 **한 줄**로 이어지는 핵심 개념 | 핵심 개념(10) | P3-02 **재사용** | 명세 `targets.graph_connectivity_coverage` — **null(목표 미정)** |

### ③ Problem Coverage — 신규 계산 (직접 계수)
대표 과정 `skills` 각각에 대해, 검수 상태가 `approved` 이고 범위 개념에 PRIMARY 로 달린 문항 중 그 스킬을
**문제유형 경유로 행사하는** 문항이 1건 이상이면 "덮인 스킬"이다. 문항의 스킬은 문제유형 코드가 가리키는
행동 스킬의 합집합이다(P3-02 와 같은 간선). 덮인 스킬 / 전체 스킬. 미검수(`pending`)·범위 밖 개념의 문항은
세지 않는다. 덮이지 않은 스킬은 이름으로 나열한다.

### ④ Solution QA Pass — 임계 흡수와 모집단 차이
- 임계는 스코어카드의 `KpiThreshold("ceiling", 0.005)`(수학적 오류율 ≤ 0.5%)를 import 해 `1 − ceiling = 0.995` 로
  **흡수**한다. 지시문 원문의 "≥ 99%"(P3-07)보다 이쪽이 더 엄격하다(acceptance ④). 스코어카드 항목이
  정확히 1개가 아니거나 방향이 ceiling 이 아니면 던진다(흡수 계약 파손을 조용히 넘기지 않는다).
- **모집단이 다르다.** 스코어카드의 오류율은 *골든 항목의 FN*(독립 모델 심판 전수)이고, ④ 는 *대표 과정 승인 문항의
  SymPy 재검증 통과율*이다. 같은 숫자가 아니며 출력의 `모집단 주의` 줄이 이를 매번 적는다.
- **skip 은 통과가 아니다.** 재검증 불가(verify 재료 없음·unverifiable)는 분자·분모에 넣지 않고 `검증 불가 비율`로
  따로 낸다. 검증 가능한 문항이 0건이면 **측정 실패**다(0% 도 100% 도 아니다). 전수 계수(표본 추정 아님)이므로
  Wilson 경계를 쓰지 않는다(P3-02 와 같은 입장).
- 재검증 도구는 `corpus_reverify`(Tier1 답 검산 + Tier2 단계 연쇄, `--fuzz` 미사용)이다. P3-07(Solution QA
  기계 검증)은 아직 `todo` 이므로 ④ 는 P3-07 착지 전까지 이 도구를 **대리**로 쓴다. P3-07 이 정의를 바꾸면
  `_solution_qa` 한 지점만 갈아끼운다.

### ⑤ Learning Loop Success — Phase 2 KPI ① 과 같은 개념
`loop_kpi_gate` 의 LOOP_COMPLETION(첫 시도 이후 Recommendation 까지 도달한 세션 비율)을 수집기·판정기째로
재사용한다. 이 CLI 는 수집기 1종만 부르고(`collect_all(collectors={LOOP_COMPLETION: …})`) 판정은
`loop_kpi_gate.evaluate` 가 한다. **DB 가 없으면 `unmeasured` 이지 0 이 아니다.**
`--no-db --input` 은 숫자 **주입**일 뿐 측정이 아니므로 `--sample-basis` 를 **반드시 명시**해야 하고(없으면 exit 3),
출력에 `기준: 주입값(--input) — 측정이 아니다`와 표본 기준이 각인된다.

### ⑥ Critical Defect — Hard Gate 흡수와 불일치
acceptance ④ 의 문면대로 "Critical Defect 0" 을 Hard Gate F-Ⅰ~F-Ⅴ 와 같은 뜻으로 보고 흡수한다.
- 해당 게이트가 1건이라도 있으면 나머지가 판정 불가여도 **확정 위반**이다(알 수 없는 것이 확정을 지우지 않는다).
- 해당이 0건이어도 **판정 불가 게이트가 남으면 측정 실패**다. "해당 없음"과 "판정 불가"는 다르다 —
  입력이 없는 게이트를 해당 없음으로 접으면 0건 통과가 된다.
- 입력 payload 는 스코어카드 `--input` 과 같은 모양을 `--hard-gate-input` 으로 받는다(이 CLI 는 payload 수집기를
  갖지 않는다). payload 가 없으면 5게이트 전부 판정 불가 → ⑥ 은 `unmeasured`.
- **불일치는 §6-① 에 기록한다.**

### ⑦ Graph Connectivity Coverage — 목표 미정
명세가 목표를 `null` 로 둔다("지시문 원문에 목표 수치가 없다 — P3-02 가 기준선을 실측한 뒤 제안한다").
값은 내되 **PASS/FAIL 을 만들지 않는다**(`no_target`). 목표가 확정되기 전에는 종합이 충족일 수 없다(§4).

---

## 3. Concept Completeness 를 필드 채움으로 만들지 않은 이유 (acceptance ⑤)

원 문서의 정의("Prerequisite·Misconception·Solution·Hint·Pedagogy 가 모두 연결된 비율")를 필드가 비어 있지
않은지로 구현하면 반증력이 0 이다 — 임의 문자열을 받는 필드는 어떤 개념이든 채워지므로 성공과 실패 양쪽에서
같은 값을 낸다. 재설계 근거와 연결 5종의 정의(각 연결을 **다른 코퍼스에 실재하는 개체로 해석되는 관계**로 정의)는
**P3-02 가 기록했다** — `l1/standards/phase3_coverage.py` 모듈 docstring
「Concept Completeness 를 '필드 채움 검사'로 만들지 않은 이유」. 여기서는 다시 정의하지 않고 그 계산을 그대로 쓴다.

**정직 단서**: 필드 채움 검사를 기각한 선례 `ARCH-43` 의 대상은 Subject Contract 15필드의 **과목 중립성 검사**
이지 Concept Completeness 가 아니다. 이 인용은 같은 결함 구조에 대한 **유추 적용**이며 ARCH-43 이 이 지표를
직접 기각한 것은 아니다.

**측정 불가 연결의 취급 (이 CLI 가 P3-02 위에 더한 규칙)**. P3-02 는 `hint` 연결을 "측정 불가"로 두고(힌트 저장
좌석 부재 — ARCH-39·P3-22) 측정 불가를 충족으로 세지 않아 Completeness 가 0 이다. 이 CLI 는 "모른다 ≠ 아니다"를
구간으로 적용한다 — 확정 완전 `c` 와 'missing 연결이 없는'(= 최대 가능) `p` 로:
`c/n ≥ 목표` → 충족 확정 · `p/n < 목표` → **미달 확정** · 그 사이 → **측정 불가(unmeasured)**.
오늘의 실 코퍼스는 교수(pedagogy) 연결이 전 개념에서 끊겨 있어 `p = 0` 이므로 hint 가 어떻든 **미달 확정**이다
(P3-02 와 같은 결론). 힌트 좌석이 생겨도 다른 연결이 모두 이어진 상태가 되면 그때 비로소 충족이 된다.

---

## 4. 상태·종합·종료 코드

지표 1종의 상태는 셋이다: `measured`(값·목표·충족 여부) · `unmeasured`(사유·예외 타입명, **0 도 100% 도 아님**) ·
`no_target`(값은 있으나 목표가 없어 판정 없음). 상태별 불변식은 생성 시점에 강제된다.

| 종료 코드 | 의미 |
|---|---|
| 0 | 7종 **전부 측정**되고 전부 충족 |
| 1 | 7종 전부 측정됐으나 1종 이상 미달 |
| 2 | 1종 이상 **측정 실패**(미측정) — 또는 미측정은 없으나 **목표 미정** 지표가 있어 종합을 못 낸다 |
| 3 | 실행 오류(인자·파일 I/O·계약 위반 입력·예기치 못한 예외). argparse 오류도 3 이다(기본 2 와 겹치지 않게) |

**미측정이 위반보다 먼저다**(지시문 규칙 "하나라도 측정 실패면 전체는 측정 실패"). 구멍 난 7종은 '미달'이기 전에
'아직 말할 수 없음'이다. 위반이 함께 있어도 지표별로 전부 출력·JSON 에 남는다. 이 점은 `loop_kpi_gate`(위반 우선)와
**다르다** — 거기는 독립된 5종이고 여기는 한 묶음의 완결성이 전제다. 7종이 정확히 한 번씩 오지 않으면 그 자체가
측정 실패다(빈 입력은 통과가 아니다).

**오늘의 실 상태에서 종합이 "측정 실패"(exit 2)인 것은 정상 동작이다.** ⑤ 는 DB 가 닿는 환경에서만, ⑥ 은
`--hard-gate-input` 이 있을 때만 측정되고, ⑦ 은 목표가 정해지기 전까지 판정이 없다. 이를 결함으로 오인해 기본값을
채우면 이 CLI 가 막으려는 위장(0건 통과)이 된다.

모든 출력(표·JSON·증거 NDJSON)에 `run_id` 와 관측 시각이 박힌다 — 이전 실행의 결과를 이번 것으로 오독하지 않게.
`--json PATH` 는 `loop_kpi_gate` 와 같은 형태(표는 stdout, JSON 은 파일)다. `--evidence PATH` 는 지표가 끝날 때마다
줄 단위로 즉시 flush 한다(④ 재검증이 십수 초 걸리므로 마지막에 한 번 쓰면 중간에 멈출 때 전부 잃는다).

---

## 5. 위반 주입 반응 검증 (acceptance ②)

전 항목 초록은 증거가 아니다. 세 겹으로 확인한다.

1. **`--self-check`**(CI `backend` 잡 게이트 스텝 · DB 0·LLM 0·약 4초): 7종 전부 충족하는 합성 대조 세계에서
   ⓐ 대조군이 충족인지 ⓑ 지표마다 위반을 주입해 **그 지표만** 미달로 바뀌는지 ⓒ 미측정 주입이 통과로 접히지 않고
   종합이 측정 실패가 되는지 ⓓ 목표 미정이 판정을 만들지 않는지 ⓔ 경계(값 == 목표는 충족) ⓕ 종합 규칙을 점검한다.
   무반응이 하나라도 있으면 exit 1. 주입은 적용 자체를 단언한다(`InjectionNotAppliedError`).
2. **pytest**(`tests/backend/ops/test_phase3_metrics.py`): 같은 성질을 독립 주입 표로 다시 확인하고, 자가 점검 자신이
   무반응·무변경 주입·미측정→통과 접힘에 exit 1 을 내는지까지 확인한다.
3. **뮤테이션 검증**: 핵심 판정 한 줄씩 일부러 깨뜨려 위 둘이 RED 가 되는지 실측했다 —
   결과표는 `docs/reviews/p3_14_phase3_metrics_2026-10-09.md`.

**CI 배선 판단.** 실 코퍼스 판정(`python -m whymath_backend.ops.phase3_metrics`)은 CI 에 걸지 않는다. 오늘의 실 상태는
기준선 미달·측정 실패(exit 2)라 걸면 상시 red 가 되어 게이트가 꺼지기 때문이다. CI 에는 `--self-check` 만 걸고
(`backend` 잡), 그 스텝의 존재와 "실 코퍼스 판정을 걸지 않는다"는 결정은 `tests/infra/test_phase3_metrics_wiring.py` 가
동결한다. 실 코퍼스 판정을 걸고 싶어졌다면 §6 의 목표 수치(acceptance ⑥)와 ⑦ 의 목표가 확정된 뒤에 그 테스트를
고치는 것이 올바른 순서다.

---

## 6. 목표 미확정과 지시문↔저장소 불일치 (Kiki 확인 사항)

### 목표 수치는 '목표 예시'다 (acceptance ⑥)
95%·98%·99% 는 원 문서의 **목표 예시**다. P3-02·P3-10 실측 기준선을 본 뒤 **Kiki 가 확정**한다. 이 CLI 는 목표를
명세·각 정본에서 읽을 뿐 정하지 않는다. 명세의 목표를 바꾸면 판정이 따라 움직임을 테스트가 확인한다
(`test_target_is_read_from_the_spec_not_hardcoded`). ⑦ 의 목표는 명세가 null 이며, 자가 점검의 합성 세계 안에서만
가설 목표를 둔다(권고값 아님).

### 불일치 기록
① **Critical Defect 의 출처.** 지시문 [19] 항목 2 는 "백로그·이슈의 P0/P1 분류를 출처로" 하라고 했다. 저장소에는 결함
   심각도 필드가 **없다**(내가 찾은 방법으로는 0건: 백로그 태스크 스키마 `scripts/harness/models.py` 의 `eos_priority`
   P0~P3 는 *태스크의 12월 검증 등급*이지 결함 표지가 아니고, 결함과 기능을 구분하는 필드도 없다). 그래서 채택하지 않고 acceptance ④ 의 지시("Hard Gate F-Ⅰ~F-Ⅴ 와 같은 뜻")를 따랐다. 그러나 F-Ⅰ(HIT 중앙값)·
   F-Ⅲ(실패 유형 분포)·F-Ⅳ(앵커 미달)는 **생산 공정 평면**의 신호이고, 제품 완성도 의미에 가까운 것은 F-Ⅱ(검수 통과 CU 수학
   오류율)·F-Ⅴ(힌트 정답 누설)뿐이다. 즉 ⑥ 은 이름은 "제품 결함 0"이지만 실체는 생산 공정 게이트의 흡수다.
   **Kiki 확인 사항**: ⑥ 을 이대로 둘지, F-Ⅱ·Ⅴ 만 남길지, 결함 심각도 필드를 새로 둘지.
② **Solution QA 임계.** 지시문 원문 ≥ 99%(P3-07) vs 이 CLI 0.995(스코어카드 흡수, acceptance ④). 더 엄격한 쪽을 따랐다.
③ **P3-07 미착지.** 지시문은 "P3-02·P3-07·Phase 2 KPI 1 을 재사용"하라고 하나 P3-07 은 `todo` 다. ④ 는 `corpus_reverify` 를
   대리로 쓰며 P3-07 착지 시 출처를 갈아끼운다.
④ **종합 우선순위.** 위 §4 — 미측정이 위반보다 먼저(`loop_kpi_gate` 와 반대).
⑤ **`EOS-38`.** 그 태스크 notes 는 "P3-14 의 Learning Loop Success 가 KPI ① 을 재사용하면 거기에도 건다(재사용 여부 미확인)"고
   적었다. 재사용이 **확인**됐으므로 `EOS-38 → P3-14` 선행 부착 여부는 Kiki 판단이다(대장 조작은 사람 소유).
