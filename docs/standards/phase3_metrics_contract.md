# Phase 3 지표 7종 계약 (제품 완성도 평면) — 정본

> **집행 코드**: `src/backend/whymath_backend/ops/phase3_metrics.py`
> **좌석**: `P3-14-phase3-metrics-cli`
> **판정 기준**: origin/main `713512bc` (2026-10-09 실측)
> **명령**: `python -m whymath_backend.ops.phase3_metrics` (자가 점검: `--self-check`)
> **개정**: 2026-10-13 `P3-33` — 게이트 `G-p314-phase3-metric-targets`(2026-10-12 Kiki 결정) 반영: ⑦ 목표 0.95 확정 · ⑥ 을 F-Ⅱ·F-Ⅴ 2종으로 축소

Phase 3 실행 지시문 [19] 가 요구한 "지표 7종을 **한 명령**으로 산출하고, 각각 **위반 주입에 반응**"하는
실행기의 계약이다. 이 문서는 ① 이 저장소에 이미 있는 지표 묶음들과의 **평면 구분** ② 7종의 정의·출처·
흡수 근거 ③ 현재 상태 ④ 목표 확정 결과 ⑤ 지시문과 저장소가 어긋난 곳을 고정한다.

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
(ARCH-18)도 coverage 를 말하지만 분모가 다르다(성취기준 <!-- fact:standards.k12 -->895<!-- /fact -->건·문제은행 전체). 이 7종의 `Curriculum Coverage`
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
| ④ | Solution QA Pass | 적용된 검사(C1~C5)가 모두 결정되어 통과한 문항 | 통과 + 실패 문항(검증 불가 제외) | `harness.solution_qa.run_solution_qa` (P3-07 · 승인 ∧ 대표 과정 PRIMARY 문항 전수) | `1 − ` 스코어카드 `수학적 오류율` ceiling (**흡수**) |
| ⑤ | Learning Loop Success | `loop_kpi_gate` LOOP_COMPLETION 의 분자 | 같은 분모 | `ops.loop_kpi_gate` **그대로 재사용**(새 정의 없음) | `LOOP_KPI_SPECS` 의 임계(Wilson 하한) |
| ⑥ | Critical Defect | 해당(triggered) Hard Gate 수 | Hard Gate **2종**(F-Ⅱ·F-Ⅴ) | `ops.validation_scorecard.evaluate_hard_gates` 의 F-Ⅱ·F-Ⅴ **그대로 흡수**(F-Ⅰ·Ⅲ·Ⅳ 는 범위 밖) | 0건 |
| ⑦ | Graph Connectivity Coverage | Concept → Skill → Problem → Misconception → Pedagogy 가 **한 줄**로 이어지는 핵심 개념 | 핵심 개념(10) | P3-02 **재사용** | 명세 `targets.graph_connectivity_coverage` — **0.95**(2026-10-12 확정) |

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
- **검증 불가는 통과가 아니다.** 적용된 검사 중 하나라도 결정하지 못한 문항(풀이가 답 형태로 끝나지 않음·근 선택 규칙이
  구조에 없음 등)은 분자·분모에 넣지 않고 `검증 불가 비율`로 따로 낸다. 검증 가능한 문항이 0건이면 **측정 실패**다
  (0% 도 100% 도 아니다). 전수 계수(표본 추정 아님)이므로 Wilson 경계를 쓰지 않는다(P3-02 와 같은 입장).
- **엔진 = `harness.solution_qa`(P3-07).** 문항마다 C1 정답↔조건(+`answer` 필드↔`answer_map`) · C2 풀이 최종 답↔정답 ·
  C3 선택지에 정답이 정확히 한 번 · C4 풀이 단계 연쇄 동치 · C5 발문 독립 재유도↔정답(P3-63 · 인식기가 있는 문장 틀만 — 미적용은
  통과로 세지 않고 보고서 `[C5 적용 범위]`에 따로 낸다)을 SymPy 단일 권위(`verify_answer`·`verify_final_answer`·
  `verify_solution`)로 돌린다. 판정: 실패가 하나라도 있으면 FAIL, 없고 검증 불가가 하나라도 있으면 검증 불가, 아니면 통과.
- **흡수 판정(P3-07 acceptance ④ · 2026-10-18).** 이원화하지 않는다 — 새 지표를 얹지 않고 이 ④ 가 곧 Solution QA Pass
  이며 임계는 스코어카드 흡수값(99.5%)을 그대로 쓴다(지시문 원문 ≥ 99% 보다 엄격). 단독 CLI(`python -m
  whymath_backend.harness.solution_qa`)는 같은 엔진·같은 모집단의 **상세 보기**(검사별 분포·사유별 건수·실패 목록·사람 검수 대기
  목록)이고, ④ 는 그 집계를 7종 보고서에 싣는 어댑터다. **판정 방식은 의도적으로 다르다**: 단독 CLI·CI 게이트는 확정된 불일치
  (FAIL)가 1건이라도 있으면 exit 1(영 허용 — 456건 중 1건은 통과율 99.78% 라 비율 판정이면 삼켜진다)이고, ④ 는 스코어카드 임계
  (99.5%)로 비율 판정한다. `0 < 실패 ≤ 0.5%` 구간에서 두 표면의 판정이 갈리며, 어느 쪽으로 합칠지는 Kiki 결정이다.
- **옛 대리(`corpus_reverify`)를 쓰지 않는 이유.** 그 표준 경로는 `verify.answer_map` 만 검산하고 레코드의 `answer` 필드는
  비교하지 않아 `answer` 만 바뀐 변조를 놓쳤다(대표 과정 40건 변조 → 0/40 검출, 2026-10-18 실측). 풀이 최종 답·선택지 유일성도
  보지 않는다. **[OPS-150 · 2026-10-21]** 야간 S6 은 이제 `answer` ↔ `answer_map` 을 C1 과 같은 공용 함수
  (`l3.verify_solution.answer_map_vars_matching`)로 대조한다(불일치 → fail · 대조 불가 → skip 으로 따로 계상). 그래도 ④ 의
  엔진은 바꾸지 않는다 — C2·C3 은 여전히 `solution_qa` 에만 있다.
- **이 수치가 말하지 않는 것.** 통과율은 *검증 가능한 문항*에 대한 값이다(검증 가능 비율을 반드시 함께 읽는다). C1 은 정답이
  `verify.conditions` 를 만족하는지를 보며, conditions 가 발문을 충실히 옮겼는지는 보지 않는다 — 정답에서 역산한 식을 conditions 로
  쓰는 생성기 계열이 있어 통과율은 실제 정확도의 **상한**이다.

### ⑤ Learning Loop Success — Phase 2 KPI ① 과 같은 개념
`loop_kpi_gate` 의 LOOP_COMPLETION(첫 시도 이후 Recommendation 까지 도달한 세션 비율)을 수집기·판정기째로
재사용한다. 이 CLI 는 수집기 1종만 부르고(`collect_all(collectors={LOOP_COMPLETION: …})`) 판정은
`loop_kpi_gate.evaluate` 가 한다. **DB 가 없으면 `unmeasured` 이지 0 이 아니다.**
`--no-db --input` 은 숫자 **주입**일 뿐 측정이 아니므로 `--sample-basis` 를 **반드시 명시**해야 하고(없으면 exit 3),
출력에 `기준: 주입값(--input) — 측정이 아니다`와 표본 기준이 각인된다.

### ⑥ Critical Defect — Hard Gate F-Ⅱ·F-Ⅴ 흡수 (P3-33 · 분모 5 → 2)
Hard Gate 5종 중 **제품 완성도 의미에 가까운 2종**만 흡수한다(2026-10-12 Kiki 결정).
- **흡수(판정함)**: F-Ⅱ(인간 검수를 통과한 CU 의 수학적 오류율 > 2%) · F-Ⅴ(힌트의 의미적 정답 누설 ≥ 10%).
- **범위 밖(판정하지 않음)**: F-Ⅰ(HIT 중앙값) · F-Ⅲ(실패 유형 분포) · F-Ⅳ(앵커 미달)는 **생산 공정 평면** 소관이다
  (`ops/validation_scorecard.py` 가 소유). 위반이 나도 ⑥ 은 반응하지 않고, 입력이 없어도 ⑥ 을 측정 실패로 만들지
  않는다. 이 사실은 출력의 지표 이름 줄(`[Hard Gate F-Ⅱ·F-Ⅴ 2종 — F-Ⅰ·Ⅲ·Ⅳ 는 생산 공정 평면 소관(이 지표 밖)]`)과
  JSON `scope` 에 박힌다.
- 구현은 스코어카드 `evaluate_hard_gates` 를 **그대로 호출**하고 그 결과에서 2종을 고른다(정의를 복제하지 않는다).
  스코어카드가 내는 게이트가 5종(F-Ⅰ~Ⅴ)이 아니면 흡수 계약 파손으로 측정 실패다.
- 해당 게이트가 1건이라도 있으면 나머지가 판정 불가여도 **확정 위반**이다(알 수 없는 것이 확정을 지우지 않는다).
- 해당이 0건이어도 **흡수한 2종 중 판정 불가가 남으면 측정 실패**다. "해당 없음"과 "판정 불가"는 다르다 —
  입력이 없는 게이트를 해당 없음으로 접으면 0건 통과가 된다.
- 입력 payload 는 스코어카드 `--input` 과 같은 모양을 `--hard-gate-input` 으로 받는다(이 CLI 는 payload 수집기를
  갖지 않는다). 읽는 곳은 `content`(F-Ⅱ·F-Ⅴ)뿐이지만 payload 전체를 스코어카드에 넘기므로, 범위 밖 구역의 형식이
  깨져 있으면 스코어카드가 던져 ⑥ 은 측정 실패(예외 타입명 동반)가 된다. payload 가 없으면 ⑥ 은 `unmeasured`.
- 결정 경위는 §6 에 기록한다.

### ⑦ Graph Connectivity Coverage — 목표 0.95 확정 (P3-33)
명세가 목표를 **0.95** 로 갖는다(2026-10-12 Kiki 결정 · `scope_spec.yaml` `completeness.targets.graph_connectivity_coverage`).
확정 전에는 `null`(목표 미정)이라 PASS/FAIL 을 만들지 않았으나(`no_target`), 이제 측정값 기준으로 충족/미달이 나온다.
`no_target` 경로 자체는 계약으로 남는다 — 명세가 어떤 목표를 `null` 로 되돌리면(사유 필수) 값은 내되 판정을 만들지
않고 종합이 충족일 수 없다(§4). 이 경로는 단위 테스트(`TestNoTarget`)와 `--self-check` ⓓ 가 계속 겨냥한다.

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

**힌트 입력 경로 (P3-41)**. 힌트는 DB `hints`(`verified=true`)에만 있다. 이 CLI 는 `phase3_coverage` 와 같은 이름·같은 읽기 함수
(`--hints-from-db` · `read_hint_problem_ids_from_db`)로 그 집합을 코퍼스에 넣는다. 세 경우가 서로 다르다:
플래그 없음 → 힌트 입력 `None` = **측정 불가**(빈 집합으로 채우지 않는다) · 플래그 있고 읽힘 → 집합이 입력이 되어 `hint` 연결은
linked/missing 으로 판정(0건이면 측정 불가가 아니라 **missing**) · 플래그 있는데 못 읽음 → `hint_source` 단계 실패로
대표 과정 세계 전체가 측정 실패(exit 2 · 출력에 `CoverageError` 와 원인 예외 타입명). 측정 불가로 조용히 내려가지 않는다.
이 플래그는 ⑤ 의 `--no-db` 와 독립이다(`--no-db` 는 ⑤ 수집만 끈다). `--self-check` 와는 함께 쓸 수 없다(합성 세계만 본다).
② 의 `힌트 입력` 사실 행이 DB 힌트 문항 수·범위 은행과의 겹침·적격 수를 보여 주며, 겹침이 0건이면 사유에 ID 공간 불일치
가능성을 덧붙인다(연결 0 이 '힌트 없음'이 아닐 수 있다).

**측정 불가 연결의 취급 (이 CLI 가 P3-02 위에 더한 규칙)**. P3-02 는 힌트 입력이 없는 실행에서 `hint` 연결을 "측정 불가"로 두고(힌트는
DB `hints` 에만 있어 `--hints-from-db` 가 읽는다 — P3-22 · 이 CLI 는 P3-41) 측정 불가를 충족으로 세지 않아 Completeness 가 0 이다. 이 CLI 는 "모른다 ≠ 아니다"를
구간으로 적용한다 — 확정 완전 `c` 와 'missing 연결이 없는'(= 최대 가능) `p` 로:
`c/n ≥ 목표` → 충족 확정 · `p/n < 목표` → **미달 확정** · 그 사이 → **측정 불가(unmeasured)**.
오늘의 실 코퍼스는 교수(pedagogy) 연결이 전 개념에서 끊겨 있어 `p = 0` 이므로 hint 가 어떻든 **미달 확정**이다
(P3-02 와 같은 결론). 힌트를 읽어 hint 가 linked 가 돼도 다른 연결이 모두 이어진 상태가 되면 그때 비로소 충족이 된다.

---

**Content Coverage 판정문의 견고성 병기 (P3-64 · 소비 절차)**. P3 게이트 판정문이 Content Coverage Rate 를 근거로 쓸 때는 `phase3_coverage` 보고서의 `link_robustness`(텍스트 「스킬 연결 견고성」 표 · `--json` 의 `link_robustness.concepts`)를 함께 옮겨 적고, `status: thin` 인 개념을 이름으로 적는다 — 연결 10/10 이 같은 사실 하나를 반복해 묻는 한 틀 위에 서 있는지를 판정문이 말하게 하려는 것이다. 이 필드는 **공개 전용**이라 met·exit code 를 바꾸지 않으며, 취약 기준(`LINK_THIN_MIN_DISTINCT_*`)은 잠정값이다(확정은 Kiki 결정 후보).

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
`--hard-gate-input` 이 있을 때만 측정된다. (⑦ 은 목표가 확정돼 `목표미정` 이 아니라 측정값 기준 충족/미달이 나온다 —
P3-33.) 이를 결함으로 오인해 기본값을 채우면 이 CLI 가 막으려는 위장(0건 통과)이 된다.

모든 출력(표·JSON·증거 NDJSON)에 `run_id` 와 관측 시각이 박힌다 — 이전 실행의 결과를 이번 것으로 오독하지 않게.
`--json PATH` 는 `loop_kpi_gate` 와 같은 형태(표는 stdout, JSON 은 파일)다. `--evidence PATH` 는 지표가 끝날 때마다
줄 단위로 즉시 flush 한다(④ 재검증이 십수 초 걸리므로 마지막에 한 번 쓰면 중간에 멈출 때 전부 잃는다).

---

## 5. 위반 주입 반응 검증 (acceptance ②)

전 항목 초록은 증거가 아니다. 세 겹으로 확인한다.

1. **`--self-check`**(CI `backend` 잡 게이트 스텝 · DB 0·LLM 0·약 4초): 7종 전부 충족하는 합성 대조 세계에서
   ⓐ 대조군이 충족인지 ⓑ 지표마다 위반을 주입해 **그 지표만** 미달로 바뀌는지 ⓒ 미측정 주입이 통과로 접히지 않고
   종합이 측정 실패가 되는지 ⓓ 목표 미정이 판정을 만들지 않는지 ⓔ 경계(값 == 목표는 충족) ⓕ 종합 규칙 ⓖ **범위 밖
   게이트(F-Ⅰ·Ⅲ·Ⅳ) 위반을 주입해도 7종 전부가 무반응인지**(⑥ 이 5종 흡수로 되돌아가지 않았다는 증거 — P3-33)와,
   흡수 2종의 입력만 지우면 범위 밖 입력이 멀쩡해도 ⑥ 이 측정 실패인지를 점검한다(22건).
   무반응이 하나라도 있으면 exit 1. 주입은 적용 자체를 단언한다(`InjectionNotAppliedError`).
2. **pytest**(`tests/backend/ops/test_phase3_metrics.py`): 같은 성질을 독립 주입 표로 다시 확인하고, 자가 점검 자신이
   무반응·무변경 주입·미측정→통과 접힘에 exit 1 을 내는지까지 확인한다.
3. **뮤테이션 검증**: 핵심 판정 한 줄씩 일부러 깨뜨려 위 둘이 RED 가 되는지 실측했다 —
   결과표는 `docs/reviews/p3_14_phase3_metrics_2026-10-09.md`.

**CI 배선 판단.** 실 코퍼스 판정(`python -m whymath_backend.ops.phase3_metrics`)은 CI 에 걸지 않는다. 오늘의 실 상태는
기준선 미달·측정 실패(exit 2)라 걸면 상시 red 가 되어 게이트가 꺼지기 때문이다. CI 에는 `--self-check` 만 걸고
(`backend` 잡), 그 스텝의 존재와 "실 코퍼스 판정을 걸지 않는다"는 결정은 `tests/infra/test_phase3_metrics_wiring.py` 가
동결한다. 목표 수치는 2026-10-12 에 확정됐지만(§6) 실 코퍼스는 여전히 미달·측정 실패(exit 2)라 걸지 않는다. 실 코퍼스 판정을
걸고 싶어졌다면 상시 red 가 되지 않는 상태가 된 뒤에 그 테스트를 고치는 것이 올바른 순서다.

---

## 6. 목표 확정 결과와 지시문↔저장소 불일치

### 목표 수치 확정 (게이트 `G-p314-phase3-metric-targets` · 2026-10-12 Kiki · 반영 `P3-33`)
- 지표 ①~⑤ 목표는 원 문서의 예시값(95%·98%·99.5% 등) **그대로 확정**했다(값 변경 없음).
- **⑦ Graph Connectivity Coverage 목표 = 0.95** — 명세 `null` 에서 확정(위 ⑦ 절).
- **⑥ Critical Defect 는 F-Ⅱ·F-Ⅴ 2종만**(위 ⑥ 절).
- **단서(정직)**: AI 품질 평가 기준선(`P3-10`)이 아직 없는 상태로 확정했다. 그러므로 ④·⑤·⑥ 목표는 그 결과를 본 뒤
  **재조정될 수 있다** — 재조정은 별도 결정이며 이 확정의 선행이 아니다.
- 이 CLI 는 목표를 명세·각 정본에서 읽을 뿐 정하지 않는다. 명세의 목표를 바꾸면 판정이 따라 움직임을 테스트가
  확인한다(`test_target_is_read_from_the_spec_not_hardcoded`). 자가 점검의 합성 세계도 ⑦ 목표를 따로 두지 않고 실제
  명세에서 읽는다(종전의 '합성 세계 안 가설 목표'는 폐지).

### 불일치 기록
① **Critical Defect 의 출처.** 지시문 [19] 항목 2 는 "백로그·이슈의 P0/P1 분류를 출처로" 하라고 했다. 저장소에는 결함
   심각도 필드가 **없다**(내가 찾은 방법으로는 0건: 백로그 태스크 스키마 `scripts/harness/models.py` 의 `eos_priority`
   P0~P3 는 *태스크의 12월 검증 등급*이지 결함 표지가 아니고, 결함과 기능을 구분하는 필드도 없다). 그래서 채택하지 않고 acceptance ④ 의 지시("Hard Gate F-Ⅰ~F-Ⅴ 와 같은 뜻")를 따랐다. 그러나 F-Ⅰ(HIT 중앙값)·
   F-Ⅲ(실패 유형 분포)·F-Ⅳ(앵커 미달)는 **생산 공정 평면**의 신호이고, 제품 완성도 의미에 가까운 것은 F-Ⅱ(검수 통과 CU 수학
   오류율)·F-Ⅴ(힌트 정답 누설)뿐이다. 즉 ⑥ 은 이름은 "제품 결함 0"이지만 실체는 생산 공정 게이트의 흡수였다.
   **해소(2026-10-12 Kiki 결정 · P3-33)**: F-Ⅱ·Ⅴ 만 남겼다(결함 심각도 필드를 새로 두는 안은 채택하지 않음).
② **Solution QA 임계.** 지시문 원문 ≥ 99%(P3-07) vs 이 CLI 0.995(스코어카드 흡수, acceptance ④). 더 엄격한 쪽을 따랐다.
③ **P3-07 착지(2026-10-18).** ④ 의 출처를 `corpus_reverify` 대리에서 `harness.solution_qa` 로 갈아끼웠다(`_solution_qa` 의 판정 함수
   주입 지점 하나). 값은 1121/1121(100%) → 456/456(100%) 이지만 분모의 뜻이 다르다: 종전엔 `answer_map` 만 검산한 문항 전부였고, 지금은
   4검사가 모두 결정된 문항이며 나머지 665건(59.3%)은 검증 불가로 따로 나온다.
④ **종합 우선순위.** 위 §4 — 미측정이 위반보다 먼저(`loop_kpi_gate` 와 반대).
⑤ **`EOS-38`.** 그 태스크 notes 는 "P3-14 의 Learning Loop Success 가 KPI ① 을 재사용하면 거기에도 건다(재사용 여부 미확인)"고
   적었다. 재사용이 **확인**됐으므로 `EOS-38 → P3-14` 선행 부착 여부는 Kiki 판단이다(대장 조작은 사람 소유).
