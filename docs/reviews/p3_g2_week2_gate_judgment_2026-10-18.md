# P3-G2 Week 2 Gate 판정문

**판정 기준: main `9f4944545ff978c5d8b72448e0ffa4b88815a36f`** (2026-10-18 10:59:58 UTC · PR #1684 머지 커밋 · 측정 시점의 `git rev-parse HEAD`와 동일함을 확인)
**판정일**: 2026-10-18 · **태스크**: `P3-16-week2-gate-judgment` · **게이트**: `G-p3-g2-week2`(`kind=decision` · 담당 kiki · 이 판정 시점에 `pending`)
**판정 세션**: P3-04~P3-07 구현에 관여하지 않은 단독 판정 세션. production code·테스트·명세·코퍼스를 바꾸지 않았다(작업 트리 변경은 이 판정문·증거 폴더·대장뿐). 단, 이 세션은 PR #1684(P3-07, 다른 세션이 만든 PR)에 CI 통과 뒤 자동 머지를 걸었다 — 그 PR 의 내용은 바꾸지 않았다.
**main CI(같은 커밋)**: `CI` merge_group(run 6118) success · `release-freeze` merge_group success · `conflict-guard`·`harness-audit` push success. `CI` push 실행은 `cancelled` — 이후 푸시(`27d3f87f`)에 밀려 취소된 것이고, 같은 커밋을 먼저 검증한 것은 위 merge_group 실행이다.
**기준 이후 main**: `27d3f87f`(OPS-151)가 한 커밋 더 올라왔다. 변경 4파일 중 측정 대상 경로(`data/corpus/`·`src/backend/`·`schemas/`)는 **0건**이라 아래 수치에 영향이 없다.

## 최종 판정

> **PASS** — 세 조건(Problem Coverage ≥ 95% · Solution QA Pass ≥ 99% · 오답 1건이 교정 전략까지 도달) 모두 충족.

조건부 PASS가 아니다. 다만 아래 "읽기 전에 알아야 할 것" 2·3번은 **게이트를 clear 하기 전에 Kiki 가 알고 있어야 하는 해석 지점**이다 — 결과를 바꾸는 결정이 이미 대장에 걸려 있다.

## 읽기 전에 알아야 할 것

1. **CLI 종료 코드가 0이 아닌 것이 여럿이다 — 전부 게이트 조건이 아니다.**

   | 명령 | 종료 코드 | 왜 그 코드인가 |
   |---|---|---|
   | `ops.phase3_metrics --no-db` | 2 | 7지표 중 ② Concept Completeness(힌트 입력 없음) · ⑤ Learning Loop(DB 수집 안 함) · ⑥ Critical Defect(입력 payload 없음)가 **측정 불가**라 종합이 "측정 실패". 세 지표 모두 P3-G2 조건이 아니다. 조건인 ③④는 `measured` · 충족 |
   | `l1.standards.phase3_coverage` | 1 | 목표 미달 둘 — Concept Completeness 0/10 · Graph Connectivity 4/10. 둘 다 P3-G2 조건이 아니다 |
   | `l1.standards.phase3_coverage --gate P3-G2` | **2** | 명세에 P3-G2 의 조건 지표 선언이 없다(선언된 게이트는 P3-G1 뿐). 이 CLI 로는 이 게이트를 판정할 수 없다 → 후속 `P3-70` |
   | `ops.phase3_remediation` | 1 | 핵심 오개념 12개 중 5개가 `blocked`(좌석 없음) — 조건 3 절 참조 |
   | `harness.solution_qa` | 0 | 실패 0건 |

   처음에 `phase3_coverage` 가 exit 1 을 낸 것은 측정 결과가 아니라 **의존 패키지(`pydantic_settings`) 미설치로 CLI 가 시작도 못 한 것**이었다 — 이 CLI 는 "목표 미달"도 exit 1 이라 두 경우가 같은 코드를 낸다. 환경을 갖춘 뒤 다시 돌려 위 표의 값을 얻었다(아래 "측정 환경").

2. **조건 3 의 읽기 — 이 판정은 대장 문면을 따랐다.** 대장·태스크 acceptance 의 조건은 "오답 **1건**이 교정 전략까지 도달"이다. 반면 지시문 세트의 판정 절차는 "핵심 오개념 중 **무작위 3개**를 골라 각각 …"이라고 적는다. 판정 기준 커밋 해시를 시드로 삼아 추첨(결과를 보기 전에 방법을 고정)했더니 **3개 중 1개(`M0673`)가 오답을 낼 좌석 자체가 없었다.** 엄격하게 "뽑은 3개가 모두 도달해야 한다"로 읽으면 이 조건은 미통과다. 이 판정이 대장 문면(1건)을 따른 근거는 ① 게이트 제목·태스크 acceptance 가 모두 "1건" ② Kiki 가 2026-10-17 에 핵심 오개념 7/12 를 인정하고 P3-06 을 done 처리하며 막힌 5개의 재판정을 별도로 두었다는 점이다. 어느 읽기가 정본인지는 clear 하는 사람이 정할 일이라 여기에 숨기지 않고 적는다.

3. **Solution QA 의 100% 는 "검증할 수 있었던 문항"에 대한 값이다.** 통과 456 · 실패 0 · **검증 불가 665**(전체 1,121건 중 59.3%). 검증 불가는 통과로 세지 않고 분모에서도 뺀다(P3-07 이 정한 정의). 이 정의를 확정하는 결정이 게이트 `G-p307-solution-qa-judgement-rules`(Kiki 대기)에 걸려 있다 — 검증 가능 비율의 **하한**을 두기로 하면 이 조건은 뒤집힐 수 있다. 이 판정은 지금 main 에 있는 정의로 쟀다.

4. **환경.** 이 컨테이너에는 DB 가 없어 로컬에 PostgreSQL 16 + pgvector 를 직접 세워 라이브 트레이스를 했다(아래 "측정 환경"). CI 가 아니라 로컬 실행이고, 학생 로그인은 외부 IdP 한 지점만 스텁인 데모 provider 경로다(Week 1·2 하네스와 같은 방식) — 실제 카카오/네이버 계정이 아니다.

## 조건 1 — Problem Coverage ≥ 95%: 충족

| 확인 | 실측 |
|---|---|
| 지표 | `ops.phase3_metrics` ③ — 명세 스킬 8개 중 승인 문항이 문제유형 경유로 그 스킬을 행사하는 스킬의 비율(직접 계수) |
| 값 | **8/8 = 100.0%** (목표 ≥ 95.0%, 명세 `problem_coverage_by_skill` 에서 읽음) · 상태 `measured` · `met: true` |
| 스킬별 승인 문항 수 | graph-sketching 421 · equation-rearrangement 316 · polynomial-arithmetic 312 · case-analysis 72 · graph-reading 72 · deductive-reasoning 48 · pattern-generalization 24 · word-problem-modeling 24 |
| 변별력 | `ops.phase3_metrics --self-check` → 점검 24건 중 실패 0건, exit 0 (「승인 문항이 없는 스킬 추가」 주입 등 7지표 위반 주입에 지표가 반응함) |
| 이력 | 10/14 설계 메모에서는 6/8 (pattern-generalization · word-problem-modeling 이 0건) → P3-05 가 두 스킬을 24건씩 채워 8/8 |

한계: 이 지표는 스킬마다 승인 문항이 **1건이라도** 있으면 덮인 것으로 센다(P3-05 Kiki 결정 ① 의 정의). 마지막 두 스킬은 24건뿐이라 "충분히 연습시킨다"의 증거가 아니라 "비어 있지 않다"의 증거다.

## 조건 2 — Solution QA Pass ≥ 99%: 충족 (정의 단서 있음)

| 확인 | 실측 |
|---|---|
| 명령 | `python -m whymath_backend.harness.solution_qa` → **exit 0** |
| 모집단 | 대표 과정 승인 문항 1,121건 (P3-14 ④와 같은 모집단) |
| 판정 | 통과 **456** · 실패 **0** · 검증 불가 **665** → Solution QA Pass 456/456 = **100.00%** |
| 임계 | P3-14 ④는 스코어카드에서 흡수한 ≥ 99.5% 를 쓴다(지시문의 99% 보다 엄격) — 둘 다 넘는다. CLI 의 합격 기준은 "실패 0건" |
| 검사별 | C1 정답↔조건 pass 1,121 · C2 풀이 최종 답↔정답 pass 456 / 검증 불가 665 · C3 선택지에 정답이 정확히 한 번 pass 236 / 해당 없음 885 · C4 풀이 단계 연쇄 pass 1,049 / 해당 없음 72 |
| 검증 불가 사유 | 풀이가 정답 변수의 값으로 끝나지 않음 361 · 근 선택 규칙이 구조에 없음("양수 a") 155 · 마지막 줄이 중간 변수 77 · 풀이 줄 없음 72 |
| 변별력 | `test_solution_qa.py` · `test_solution_qa_wiring.py` · `test_phase3_remediation.py` · `test_remediation_strategy.py` · `test_phase3_metrics.py` 5파일을 이 세션에서 다시 돌려 **250 passed, exit 0**. 구현 세션이 보고한 검출기 뮤테이션 32종·실 코퍼스 주입 5종은 이 세션에서 다시 돌리지 않았다(테스트 통과까지만 확인) |

한계(구현 세션이 PR #1684 에 적은 것과 같고 이 세션에서 숫자로 확인한 부분만 인용): ① 통과율은 검증 가능한 40.68%(456/1,121)에 대한 값이다. ② C1 은 정답이 `verify.conditions` 를 만족하는지만 보는데 일부 계열은 conditions 를 정답에서 역산해 적으므로 통과율은 실제 정확도의 **상한**이다. ③ 다변수 86건은 소속 대조뿐인 약한 검사다. 소유 태스크: `P3-62`(검증 불가 구조화) · `P3-63`(발문↔conditions 독립 재유도) · 결정 게이트 `G-p307-solution-qa-judgement-rules`.

## 조건 3 — 오답 1건이 교정 전략까지 도달: 충족 (대장 문면 기준 · 읽기 단서 있음)

### 3-1. 측정기(CLI) 결과

`python -m whymath_backend.ops.phase3_remediation` → **exit 1**, "핵심 오개념 **7/12** 산출".

| 상태 | 개수 | M-id |
|---|---|---|
| served (좌석 ~ 보고 id 까지 충족) | 6 | M0075 · M0080 · M0670 · M0671 · M0864 · M0865 |
| shadowed (같은 kebab 의 다른 M-id 에 가려짐) | 1 | M0672 → M0075 로 보고됨 (`P3-59` done) |
| blocked (좌석 없음) | 5 | M0673 · M0674 · M0676 · M0677 · M0678 |

이 CLI 는 오답·정답 픽스처를 순수 함수 체인에 넣어 확인하는 **측정용 조립**이다(`l4/misconception/remediation_strategy.py` 를 부르는 곳은 이 CLI 하나다). 그래서 "서빙 경로가 같은 결과를 내는가"는 아래 라이브 트레이스로 따로 확인했다.

### 3-2. 무작위 3개 추첨 (재현 가능)

방법을 먼저 고정했다: 핵심 오개념 12개를 M-id 오름차순으로 세우고, 시드 = 판정 기준 커밋 해시 앞 8자리(`9f494454` → 2672378964)로 3개를 뽑는다. 결과를 보고 다시 뽑지 않았다.

추출: **M0673 · M0080 · M0670** (`docs/reviews/p3_g2_week2_gate_evidence_2026-10-18/p3g2_draw.py`)

### 3-3. 라이브 트레이스 — 실 PG · 실 앱(HTTP) · 학생 1명

학습자 상태는 한 줄도 직접 쓰지 않았다(전부 HTTP 부수효과). 저작 콘텐츠(문항)는 `l1.problem_bank.populate` 로 적재했다. 오답은 측정 CLI 가 쓴 픽스처(문항 id + 오답 보기 번호)를 그대로 `POST /v1/me/attempts`(`selected_choice_index`)로 냈다. 사람이 값을 넣어야 넘어가는 구간은 **없었다**(학생이 하는 일은 보기 하나 고르기뿐).

| 단계 | M0080 (critical-point-implies-extremum) | M0670 (continuity-implies-differentiability) |
|---|---|---|
| 제출한 오답 | 문항 `135fbda6…` · 보기 1 | 문항 `920d9d5e…` · 보기 1 |
| 응답 | 201 · `is_correct=false` | 201 · `is_correct=false` |
| 오개념 훑기 | `ran_with_candidates` | `ran_with_candidates` |
| 후보 · 신뢰도 | critical-point-implies-extremum · **0.8** · 게이트 통과 | continuity-implies-differentiability · **0.8** · 게이트 통과 |
| 학습 상태 전이 | NEW → **REMEDIATING** · 규칙 `R3-wrong-misconception` · 다음 행동 `REMEDIATE_MISCONCEPTION` | 동일 |
| 교정 코칭 | `misconception_review` · 소크라테스 범주 `assumption` ("수를 직접 넣어 보면…") | 동일 형식 |
| 다음 학습 추천 (`GET /v1/me/next-problem`) | `practice_current` · 이유 `misconception_remediation` · 근거 `learning_state` · `learning_state_directive=applied` · 틀린 문항과 같은 개념(`12미적Ⅰ-02-07-1`)의 다음 문항 `1e924953…` | `practice_current` · 동일 이유 · 같은 개념(`12미적Ⅰ-02-02-1`)의 문항 `0cbf40e1…` |
| 이벤트 trace (`GET /v1/me/learning-trace`) | 8종: concept_selected · problem_attempted · assessment_failed · mastery_updated · misconception_detected · skills_resolved · learner_state_created · recommendation_generated | 동일 8종 |

원 자료: `live_M0080_1.json` · `live_M0670_1.json`(같은 폴더). 측정 CLI 의 해당 행과 라이브 값이 맞물린다 — CLI 의 M0080·M0670 행은 첫 신뢰도 0.80 · `action=practice_current` · `reason_type=misconception_remediation` 을 보고했고, 라이브의 첫 오답이 같은 신뢰도·행동·이유를 냈다.

**M0673 ([12미적Ⅰ-02-05]) — 끊긴 지점: 첫 단계(좌석).** 이 오개념을 가리키는 오답 보기가 **아무 데도 없다**: 적재한 문항 2,984건의 `distractor_map` 에서 0건, 코퍼스 전 문제은행(`data/corpus/*/problems.jsonl`) 0건, 승인 크로스워크 0건. `M0673` 문자열은 오개념 카탈로그·범위 명세·픽스처 문서에만 있다. 학생이 어떤 오답을 내도 이 오개념으로는 닿지 않는다. 소유: `P3-61`(todo · 선지 역추적 전용 kebab 4개 신설 — 안 A) · 게이트 `G-misc40-unseated-concepts-disposition`(안 E 보류로 clear).

**결론.** 대장 문면("오답 1건이 교정 전략까지 도달")은 충족한다 — 추출된 3개 중 좌석이 있는 2개는 서빙 경로에서 오답 1건이 후보 → 상태 전이 → 교정 코칭 → 다음 추천까지 사람 개입 없이 이어졌다. 엄격한 읽기("뽑은 3개 전부")로는 2/3 이고 끊긴 지점은 `M0673` 하나다(위 "읽기 전에 알아야 할 것" 2번).

### 3-4. 반복 오답 관측 (조건 밖 · 후속 등재)

같은 오개념(M0080)의 오답을 4회 연속 제출했다.

| 회차 | 누적 가설 신뢰도(DB) | 증거 횟수 | 상태 규칙 → 다음 행동 | `next-problem` |
|---|---|---|---|---|
| 1 | 0.80 | 1 | R3 → REMEDIATE_MISCONCEPTION | practice_current · misconception_remediation |
| 2 | 0.94 | 2 | R3 → REMEDIATE_MISCONCEPTION | diagnose · unmeasured · `released_after_repeat` |
| 3 | 0.96 | 3 | R5 → OFFER_EXPLANATION_OR_HINT | diagnose · unmeasured |
| 4 | 0.97 | 4 | R5 → OFFER_EXPLANATION_OR_HINT | diagnose · unmeasured |

신뢰도 누적(0.80 → 0.94 → 0.96 → 0.97)은 측정 CLI 의 0.80 → 0.939 → 0.964 → 0.968 과 맞는다. 그러나 **코칭 문구는 4회 모두 글자 그대로 같았고**, CLI 가 보여 준 사다리 3·4단계(쉬운 문항 · 선수 개념)가 서빙에서 같은 대상으로 집행되는지는 확인하지 못했다. 코드가 말하는 것은 두 가지다: `l4/misconception/intervene.py` 는 사다리 등급이 결정에만 실리고 발화(`prompt`)에는 닿지 않는다고 적고(학생에게 "몇 번 틀렸다"를 말하지 않는다는 교수학 금기), `l4/misconception/models.py` 는 등급을 HTTP 응답에 싣지 않기로 한 것이 의도적인 결정(PR #1203 — 응답을 누적 증거의 함수로 만들면 동일 입력의 응답 비트동일성이 깨진다)이며 등급의 관측 좌석은 `harness/wh1_loop` 라고 적는다. 즉 등급이 응답에 보이지 않는 것은 결함이 아니라 설계다. 확인되지 않은 것은 **등급이 서빙의 다른 경로로 행동(쉬운 문항 · 선수 개념)이 되는가**이고, 이 판정은 그것을 조사하지 않고 `P3-69` 로 등재만 했다. 원 자료: `live_M0080_4.json`.

## 조건 밖에서 달라진 것 (참고)

`phase3_coverage` 의 Graph Connectivity 는 10/17 G1 재판정(`e35692ef`)의 5/10 에서 **4/10** 이 됐다. 같은 CLI 를 `6f6684745^1`(P3-49 직전, 5/10)과 `6f6684745`(P3-49 머지, 4/10)에서 돌려 원인이 P3-49(#1678 — 극값의 개수 24건을 02-01 → 02-07 이동)임을 확인했고, P3-49 자신이 "Graph Connectivity 5/10→4/10 (Kiki 게이트 수용)"으로 이미 기록했다. 새 결함이 아니다. 나머지 지표는 G1 재판정 때와 같다: Content Coverage 10/10 · Curriculum Coverage 10/10 · Concept Completeness 0/10(힌트 측정 불가) · 6슬롯 60/60.

## 정직한 공백

| 항목 | 상태 |
|---|---|
| 핵심 오개념 5개 막힘 (M0673·M0674·M0676·M0677·M0678) | `P3-61`(todo) · `P3-44`(in_progress — 오답 보기 재연결) · 게이트 `G-misc40-unseated-concepts-disposition`(안 E 보류) |
| 단답형 885문항(범위 내 승인 문항의 79%)은 오답→오개념 후보 채널이 없다 | `P3-56`. 이 판정의 오답 트레이스는 객관식 채널만 본다 |
| 오답 보기 12건이 raw M-id(`M0674`)를 달아 런타임이 조용히 버림 | `P3-57` |
| Solution QA 검증 불가 665건 · 정의 결정 | `P3-62` · `P3-63` · 게이트 `G-p307-solution-qa-judgement-rules` |
| 반복 오답 사다리 3·4단계의 서빙 집행 여부 | `P3-69` (이 판정이 등재) |
| P3-G2 게이트 단위 종료 코드 부재 | `P3-70` (이 판정이 등재) |
| 라이브 트레이스의 학생 로그인 | 외부 IdP 한 지점만 스텁(데모 provider) — 실제 소셜 로그인 계정이 아니다 |
| 라이브 트레이스의 DB | 로컬 PG 16.15 + pgvector 0.6.0, 문제 2,984건(코퍼스 5종) 적재. 측정 CLI 들은 DB 가 아니라 코퍼스 파일을 직접 읽는다 |
| 실행 환경의 Python | 3.13(CI 는 3.12). 의존성은 CI 제약 파일(`infra/ci/constraints-py312.txt`)로 고정 |
| 구현 세션의 뮤테이션 검증 | 재실행하지 않음(관련 테스트 250건 통과까지만) |

## 측정 환경 (재현용)

- Python venv: `pip install -e "src/backend[dev]"` · `PIP_CONSTRAINT=infra/ci/constraints-py312.txt`
- PostgreSQL 16.15 + `postgresql-16-pgvector` 0.6.0 · 역할 `whymath`(trust) · `alembic upgrade head` → 리비전 `a8c4e1f7b3d9`
- 적재: `l1.standards.populate`(성취기준 895) · `l1.atom_graph.populate`(원자 백본 2,683노드·2,234엣지) · `l1.problem_bank.populate`(픽스처 문항이 든 코퍼스 5종 → `problem` 2,984건 전부 approved)
- pytest 는 설정 가드(OPS-61) 때문에 `-c src/backend/pyproject.toml --rootdir=src/backend` 로 실행

## 증거 폴더

`docs/reviews/p3_g2_week2_gate_evidence_2026-10-18/` — CLI 원출력(`phase3_metrics_output.txt` · `phase3_coverage_output.txt` · `phase3_remediation_output.txt` · `solution_qa_cli_output.txt`) · JSON(`p3_metrics.json` · `remed.json`) · 라이브 트레이스 원 응답(`live_M0080_1.json` · `live_M0670_1.json` · `live_M0080_4.json`) · 스크립트(`p3g2_draw.py` · `p3g2_live_trace.py` · `p3g2_hyp_probe.py`) · 픽스처 문항의 코퍼스 위치(`fixture_corpora.txt`).

## 기록

- **PASS** → 게이트 `G-p3-g2-week2` 의 clear 는 Kiki 몫이다(`kind=decision` · `assignee=kiki`, 에이전트가 `--as kiki` 로 대행하지 않는다). clear 는 판정 기준(커밋 해시·PR 참조)을 증적에 요구한다(HARN-68) — 기준은 위 `9f4944545ff9…`.
- 이 판정이 등재한 후속(판정을 막지 않음): `P3-69` · `P3-70`.
- 핵심 판단이 걸린 두 지점(위 2·3번)은 clear 전에 확인을 권한다: 조건 3 을 "1건"으로 읽을지 "뽑은 3개 전부"로 읽을지, 그리고 `G-p307-solution-qa-judgement-rules` 의 결정 방향.
