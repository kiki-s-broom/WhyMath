# EOS-127 처분 판정 — 상태 머신 R4(선수결손)는 배선하지 않고 **삭제**한다

> **판정 기준: main `381ec106`** (2026-10-03 · `SEC-40: 삭제권 이행 시 evidence_event 함께 삭제 (#1439)`)
> **소유 태스크**: `EOS-127-prerequisite-gap-rule-r4-wiring` · 처분 (나) — acceptance ③
> **실행 환경(실측)**: 컨테이너 · PostgreSQL 16.14(로컬 루프백) + pgvector · `alembic upgrade head` EXIT=0 · Python 3.12 venv · 4 vCPU
> **이 문서가 답하는 것**: ①R4가 왜 한 번도 발화하지 않았나 ②"무겁다"는 EOS-105의 추정이 맞았나 ③그래도 왜 (가) 배선을 고르지 않았나 ④무엇을 지웠고 무엇을 남겼나 ⑤어떻게 검증했나 ⑥남은 구멍은 무엇인가

---

## §0. 결론 (먼저)

**(나) R4를 상태 머신에서 제거한다.** 선수 개념으로 내려가는 일은 이미 *다음 문항 선택*이 요청 시점에 하고 있고(R6 경로 · `EOS-26`·`EOS-124`), 실 PG 테스트로 검증돼 있다. 제출 시점에 R4를 또 두면 **같은 판단을 두 곳에서 하게 되고**, 더 나쁘게는 R4가 R6보다 먼저 가로채 그 하강을 막는다.

- **비용 때문에 (가)를 배제한 것이 아니다.** 측정해 보니 비용은 문제가 아니었다(§2). 배제 사유는 *중복과 가로채기*다(§3). 태스크 ④가 "무겁다는 추정으로 (가)를 배제하지 말라"고 못박았고, 이 판정은 그 요구를 지켰다.
- **지운 것**: 규칙 `R4-prerequisite-gap` · 증거 필드 `AttemptEvidence.prerequisite_gap_concept_ids` · 조립기 인자 · 행동 종류 `NextActionKind.GO_TO_PREREQUISITE_CONCEPT` · 전이표 간선 `ASSESSING → LEARNING`.
- **남긴 것**: PG enum 라벨 `POLICY_PREREQUISITE_GAP` 하나. 추가 전용 원장의 라벨은 지우는 비용이 남기는 비용보다 크다(§4). 대신 **은퇴 표기**(`RETIRED_POLICY_TRIGGERS`)와 "발화 규칙 0건" 동결 테스트를 붙였다.
- **R4a(예외 규칙)는 만들지 않는다.** `EOS-138`이 "R4 제거를 고르면 이 예외도 소멸한다"고 미리 적어 두었다.

---

## §1. 실측 사실 — R4는 한 번도 매치되지 않았다 (acceptance ①)

- 증거 조립기 `build_attempt_evidence`는 `prerequisite_gap_concept_ids`를 **인자로만** 받았고, 유일한 서빙 호출부(`api/me.py::submit_attempt` → 공용 진입점 `advance_on_graded_attempt`)가 그 값을 넘기지 않았다. 코치 완료 경로(`api/coach.py`)도 같은 공용 진입점을 쓰며 같은 상태였다.
- 그래서 `R4-prerequisite-gap`의 조건(`not e.is_correct and bool(e.prerequisite_gap_concept_ids)`)은 서빙에서 **항상 거짓**이었다. 실 PG 시나리오 `SCENARIO-003 ③`이 이 공백을 동결하고 있었다(선수 결손이 확정된 상태의 오답 → 규칙 `R6-wrong-undiagnosed` · `target_concept_id=null`).

---

## §2. 비용 실측 — "무겁다"는 추정은 틀렸다 (acceptance ④)

EOS-105가 생산자 미배선의 사유로 든 것은 "`recommend_prerequisite_gaps`가 재귀 CTE라 제출마다 돌리기 무겁다"였다. 이것은 **측정이 아니라 판단**이었다. 실 PG에 개념 600개(선수 엣지 약 1,200건·직접 선수 최대 3개)·문항 1,800건을 심고, 학습자 이력 3단계(시도 50 · 500 · 5,000건)에서 각 단계를 60회씩 쟀다(세션은 회마다 새로 열었다 · 루프백 연결 · 표본 60회라 p95는 근사치다).

| 학습자 시도 수 | 선수 조회 CTE `max_depth=1` p50 / p95 | `compute_concept_diagnoses` p50 / p95 | 생산자 전체 `recommend_prerequisite_gaps(max_depth=1)` p50 / p95 |
|---|---|---|---|
| 50 | 2.4 / 3.5 ms | 3.6 / 5.2 ms | **5.8 / 7.1 ms** |
| 500 | 2.2 / 3.1 ms | 9.0 / 11.0 ms | **11.1 / 13.7 ms** |
| 5,000 | 2.3 / 3.3 ms | 52.5 / 111.0 ms | **62.7 / 127.8 ms** |

읽는 법(초보자용): 재귀 CTE는 `max_depth=1`이면 "직접 선수만" 찾는 일반 조회라 **약 2ms**로 끝난다. 시간이 늘어나는 곳은 CTE가 아니라 `compute_concept_diagnoses`(학습자의 *전체* 이력을 읽어 개념별 숙달을 계산)이고, 학습자의 시도가 많을수록 비례해 커진다. 시도 5,000건짜리 최악 학습자에서도 p95 약 128ms다.

- 비교 기준: 코드에 박힌 "제출 경로 예산"은 없다. SLO 문서(`incident_response_slo.md` §1-2)의 학생 트래픽 p95 평상 목표는 3,000ms이고 `T2` 경로 설계 목표는 p95 1,000ms다. 128ms는 그 **약 13%**다. 즉 *배선하면 안 될 만큼 무겁지는 않다.*
- 따라서 이 판정은 (가)를 **비용으로 배제하지 않는다.**

---

## §3. 그런데 왜 (가)가 아닌가 — 이미 같은 일을 하는 경로가 있고, R4는 그것을 가로챈다

### 3-1. 선수 하강은 이미 살아 있다 (R6 → 다음 문항 선택)

`l2/learning_state_recommendation.py`(EOS-26 · EOS-124)는 **상태 머신의 R6 결정을 읽고** 다음 문항을 고를 때 선수 쪽으로 내려간다. 요청 시점에 시간·노드·깊이 예산을 걸고(`PrerequisiteReader` 주입), 선수 상태를 셋으로 나눈다.

| 오답 개념 C가 막힘(< 0.4)일 때 | 하는 일 | 결과 이름 |
|---|---|---|
| 직접 선수 중 **이미 측정된 약점(< 0.7)** 이 있다 | 진단하지 않고 그 약점을 연습 | `known_prerequisite_deficit` |
| 약점은 없고 **미측정 선수**가 있다 | 미측정 선수 문항으로 탐침(측정) | `prerequisite_probe` |
| 선수가 전부 숙달 / 엣지 없음 / 문항 없음 / 시간 초과 | 같은 개념 연습 | 각각 별도 이름 |

R4가 하려던 일("오답 + 알려진 선수 결손 → 선수로 간다")은 첫 행(`known_prerequisite_deficit`)과 **같은 판단**이다. 두 번째 행(탐침)은 R4에는 아예 없던 기능이다. 즉 R4는 이 경로의 **열화된 복제**였다.

### 3-2. R4를 배선하면 R6 하강이 막힌다

`route_by_learning_state`는 상태 머신의 **R3와 R6 결정만 읽는다.** R4 결정을 읽는 소비자는 없다. 그러면 R4가 서빙에서 발화하기 시작하는 순간:

1. "오답 + 선수 결손이 알려진 학생"의 결정이 R6에서 R4로 바뀌고,
2. 추천 쪽은 R4를 집행할 줄 모르므로 지시 없음(`None`)으로 처리해 **기본 문항 선택**으로 떨어지며,
3. 지금 동작하는 `known_prerequisite_deficit` · `prerequisite_probe` 하강이 **사라진다.**

(가)를 정직하게 완성하려면 `route_by_learning_state`에 R4 소비자를 새로 붙이고, 연속 오답 판정 집합(`_WRONG_ANSWER_DECISIONS`)에 R4를 넣고, `R4a` 예외 규칙과 신규 임계 k=3(근거 없는 초안 수치)을 실측 보정해야 한다. 그렇게 해서 얻는 것은 **이미 있는 하강과 같은 판단의 두 번째 진실 원천**이다 — CLAUDE.md 8대 구조 원칙의 "단일 진실 원천"과 정면으로 어긋난다. 이것이 (가)를 배제하는 근거이며, 비용이 아니다.

### 3-3. 태스크 문면 ②의 전제는 낡았다

acceptance ②는 "클라이언트가 조회형 3종 좌석을 부르지 않으면 선수 결손이 학생에게 도달하지 않는다"고 썼다(2026-09-19 작성). 그 뒤 `EOS-26`(2026-09-26)이 R6 경로로 `next-problem`이 스스로 선수로 내려가게 했다. 실 PG 시나리오 `SCENARIO-003 ②`가 그 증거다(선수 문항 오답 1건 → 추천 `action=practice_prerequisite` · `target_concept=선수` · 고른 문항이 선수 개념 문항). 조회형 좌석 없이도 하강이 일어난다.

---

## §4. 무엇을 바꿨나

| 대상 | 변경 | 이유 |
|---|---|---|
| `l2/learning_state_policy.py` | 규칙 `R4-prerequisite-gap` 삭제 · R3/R5/R6 설명문에서 R4 언급 제거 · 모듈 docstring에 "R4는 없다" 절 신설 | 발화하지 않는 규칙을 남기지 않는다 |
| `schema/learning_state.py` | `AttemptEvidence.prerequisite_gap_concept_ids` · `NextActionKind.GO_TO_PREREQUISITE_CONCEPT` 삭제 · 전이표에서 `(ASSESSING, LEARNING)` 삭제 · `RETIRED_POLICY_TRIGGERS` 신설 · `POLICY_PREREQUISITE_GAP` 은퇴 표기 | 아래 "라벨을 남긴 이유" |
| `l2/learning_state_evidence.py` | 조립기 인자 `prerequisite_gap_concept_ids` 삭제 · 생산자 배선 표를 4필드로 정정 | 입구 닫기 |
| `api/me.py` · `l2/learning_state_recommendation.py` · `l2/remediation_policy.py` | "R4 미배선"·"R4가 소유" 문구를 처분 결과로 정정 (코드 동작 변경 0) | 낡은 주석이 가리키는 소유자가 사라졌다 |

**라벨 `POLICY_PREREQUISITE_GAP`을 남긴 이유**: `learning_state_trigger_enum`은 추가 전용 원장(`learning_state_transition`)의 PostgreSQL enum이다. 라벨을 빼려면 타입 재생성 마이그레이션이 필요하고, 그 사이 이 값이 적힌 행이 있다면 읽는 순간 `LookupError`가 난다. R4는 서빙에서 한 번도 발화하지 않았고 클라이언트는 정책 소유 트리거를 적재할 수 없으므로(`_POLICY_OWNED_TRIGGERS`) 그런 행은 없다고 **추론**하지만, 아래 §6-2대로 프로덕션 원장은 이 세션이 **실측하지 못했다.** 지우는 비용(마이그레이션 + 미실측 위험)이 남기는 비용(은퇴 표기 1줄)보다 크다.

**건드리지 않은 것**: `EscalationRung.PREREQUISITE_CONCEPT`(L4 개입 강도 사다리 4칸)는 경로가 아니라 강도 표기라 그대로 둔다(docstring의 소유자 표기만 정정). 조회형 선수 좌석 3종(`/weak-concepts/{id}/prerequisites`·`/coaching`·`/learning-path`)도 그대로다. `constitution/`은 읽기만 했다.

---

## §5. 검증

### 5-1. 테스트

| 구분 | 결과 |
|---|---|
| 상태 머신·증거·추천·보정 정책·`/learning-state` API 단위 테스트(5파일) | **285 passed** · EXIT=0 |
| **실 PG 통합**(`WHYMATH_RUN_INTEGRATION=1`): 시나리오 회귀 스위트 + 페르소나 3종 + `EOS-26` R6 탐침 + `EOS-138` R3 입력 + `EOS-24` 추천 추종 | **38 passed · skip 0** · EXIT=0 |

- 통합 테스트는 기본 skip이다. 첫 실행을 플래그 없이 돌려 "5 passed, 69 skipped"가 나왔고, 그것은 **통과 근거가 아니라** 미실행이라 플래그를 켜고 다시 돌렸다.
- 플래그를 켠 두 번째 실행에서 5건이 실패했는데, 원인은 변경이 아니라 **§2 벤치가 같은 DB에 심은 문항 1,800건이 `next-problem`의 전역 후보 풀을 오염**시킨 것이었다(시나리오가 심은 문항이 아닌 벤치 문항이 추천됨). DB를 새로 만들어(`drop` → `create` → `alembic upgrade head`) 같은 명령을 다시 돌려 38건 통과를 확인했다 — 가설을 추론으로 두지 않고 **제거 실험으로 확인**했다.
- 일부 테스트를 새 동작으로 승격했다: `SCENARIO-003 ③`은 "R4 미발화(정직한 공백 동결)"에서 "선수 결손 상태의 오답은 R6이고 선수 하강은 추천(②)이 한다"로 바뀌었다(단언 값은 같고 소유자가 바뀌었다).

### 5-2. 새 동결 테스트와 뮤테이션 (실패 주입 · 주입 적용·원복 바이트 동일 단언)

새 테스트 4건: ①`POLICY_*` 트리거 전수 = 규칙이 내는 트리거 ∪ 은퇴 라벨 · 규칙은 은퇴 라벨을 내지 않는다 ②`ASSESSING`에서 나가는 전이표 간선은 전부 어떤 규칙의 도착지(죽은 간선 0) ③`GO_TO_PREREQUISITE_CONCEPT`·`R4-prerequisite-gap` 부재 ④`prerequisite_gap_concept_ids`의 필드·조립기 인자 부재.

| # | 주입 | 결과 | 잡은 테스트 |
|---|---|---|---|
| M1 | 전이표에 `ASSESSING → LEARNING` 복원 | RED (1건) | `test_no_declared_assessing_edge_is_dead` |
| M2 | `RETIRED_POLICY_TRIGGERS` 비움 | RED (1건) | `test_policy_triggers_are_exactly_rule_triggers_plus_retired` |
| M3 | `NextActionKind.GO_TO_PREREQUISITE_CONCEPT` 복원 | RED (1건) | `test_removed_prerequisite_action_kind_is_gone` |
| M4 | 조립기 인자 복원 | RED (1건) | `test_prerequisite_gap_is_not_an_evidence_field_anymore` |

기준선은 129 passed였고, 주입마다 정확히 의도한 테스트 **하나만** 실패했다. 원복 후 sha256이 주입 전과 같음을 단언했다.

### 5-3. CI 동등 검증 (잡 목록을 먼저 열거한 뒤 맞춤)

CI 잡: `changes · data-pipeline · backend · backend-migrations · data-pipeline-integration · data-pipeline-neo4j · mobile · concept-reach-guard · web · webapp · infra-contracts · docker-build · infra-shell · policy-guard · harness-integrity · declared-unwired-audit · corpus-authoring · e2e-nightly · backend-serial-nightly`. 이번 변경이 닿는 잡과 판정 근거:

- **닿음** `backend`(소스·테스트 변경) · `declared-unwired-audit`(상태 머신 어휘 삭제) · `harness-integrity`(대장·문서 변경) · `policy-guard`(문서 추가).
- **안 닿음(근거)** `backend-migrations`/`docker-build`: 마이그레이션·Dockerfile 변경 0 · `mobile`/`web`/`webapp`: 클라이언트 코드에 삭제 심벌 참조 0건(`src/mobile`·`src/web` grep 0건) · `infra-contracts`: 신규 모듈·엔드포인트·alembic 리비전 0건(인벤토리 귀속 대상 없음) · 나머지 잡은 데이터·코퍼스 축.

실행 결과(종료 코드로 판정): `ruff check` EXIT=0 · `black --check` EXIT=0 · `mypy --strict whymath_backend` EXIT=0(732 파일) · `lint-imports` EXIT=0(4 kept, 0 broken) · `declared_unwired_audit` EXIT=0(위반 0) · `cp949_guard` EXIT=0 · `check_conflict_markers` EXIT=0 · `backlog.py validate` EXIT=0.

**전체 스위트(별도 워크트리 · 실행 중 트리 무변경 · 새 DB · CI와 같게 `data-pipeline` 설치)**:
- 일반 `pytest`: 16,523 passed · 511 skipped · 1 xfailed · **1 failed** — 실패 1건은 `db/test_session.py::test_default_settings_use_connection_pool`이고 **내 실행 스크립트가 켠 `WHYMATH_DB_DISABLE_POOL=1`이 원인**이다(CI의 일반 pytest 스텝에는 없는 변수). 변수 없이 그 테스트만 돌리면 passed, 있으면 failed로 대조 확인했다. 코드 변경과 무관.
- 통합 `pytest -m integration --ignore=l3`(`WHYMATH_RUN_INTEGRATION=1`): **473 passed · 13 skipped** · EXIT=0.
- `tests/harness`: **1588 passed · 3 skipped** · EXIT=0. `backlog validate`·`audit-deps`·`rules lint`·`rules render --check`·`jit check`·헌법 래칫(차단 7건 ≤ 기준선 7건)·가드 자가시험 전부 EXIT=0.
- 첫 두 번의 전체 실행은 환경 문제로 테스트 전에 끝났다(PG 서버 다운 · `data_pipeline` 미설치로 수집 ImportError) — 결과로 세지 않고 원인을 고쳐 다시 돌렸다.

---

## §6. 남은 구멍 — 숨기지 않고 적는다

1. **응답 문면 ↔ 추천 불일치(기존 설계 · 이번 변경이 만든 것이 아님).** 선수 결손 상태의 오답 제출 응답은 `learning_state.next_action=PRACTICE_SAME_CONCEPT`(R6)인데 이어지는 `next-problem`은 선수 문항(`practice_prerequisite`)을 낸다. R6의 문면은 "같은 개념 연습"이고 선수 탐침은 EOS-26이 R6 위에 얹은 집행이다. 학생에게 보이는 이름표가 둘로 갈리는 것은 `EOS-124`류의 *정책 축 ↔ 선택 축* 불일치 후보이지만 이번 태스크의 범위(R4 처분)가 아니다. 후속 판정이 필요하면 별도 태스크로 올린다.
2. **프로덕션 원장은 실측하지 못했다.** `POLICY_PREREQUISITE_GAP` 행이 0건이라는 확인은 추론(발화 경로 없음 · 클라이언트 적재 차단)이지 DB 실측이 아니다. 읽기 전용 확인 한 줄을 Kiki가 prod DB(docker `whymath-pg` · 호스트 포트 5433)에서 돌릴 수 있다(PR 본문 참조). 0이 아니면 라벨 보존 결정이 옳았음이 확인되고, 0이면 향후 enum 정리 마이그레이션의 전제가 선다.
3. **R4a가 다루던 구간은 답을 못 준다.** "측정된 선수 결손 ∧ 교정 저항" 학생은 지금도 R3→R5→(R6/설명) 경로를 탄다. `EOS-138` §7 반례 S-A가 이미 "P를 한 번도 풀지 않은 학생에게는 판정이 답을 주지 못한다"고 인정한 구간이며, 교정 저항 신호는 R5가 받는다. 새로 생긴 구멍이 아니다.
4. **실제 모바일 앱은 R6에 도달하지 않는다**(`EOS-146` — 앱은 오답을 제출하지 않고 코치 정답 완료만 기록). 따라서 이 처분의 "선수 하강이 일어난다"는 **API 계약 수준**의 사실이다. 앱 학생에게 일어나는 개선이 아니다.
5. **벤치 한계**: 개념 600개·표본 60회·루프백 연결·4 vCPU 컨테이너다. Phaiakes9 실측이 아니고 p95는 근사치다. 이 판정은 비용으로 결론을 내리지 않았으므로(§3) 한계가 결론을 흔들지 않지만, 훗날 (가)류 배선을 재논의하면 이 표를 근거로 쓰기 전에 재측정해야 한다.

---

## 부록 A. 비용 벤치마크 재현

`/tmp` 스크래치에서 쓴 스크립트의 방법(재현용 요약): 로컬 PG16에 `alembic upgrade head` → `Concept`·`AtomNode`(600) · `ConceptEdge`(앞 번호 40개 중 1~3개를 선수로 · DAG) · `Problem`·`ProblemConcept`(개념당 3개, PRIMARY) 시딩 → 학습자 1명에 `ProblemAttempt`·`ConceptMasteryHistory`를 N건(앞쪽 150개 개념에 무작위 분산) 적재 → `analyze` → 대상 개념(직접 선수 3개)에 대해 `fetch_prerequisites(max_depth=1)` · `compute_concept_diagnoses` · `recommend_prerequisite_gaps(max_depth=1)`를 각 60회, 호출마다 새 세션으로 시간 측정. **벤치 후에는 DB를 반드시 새로 만든다**(§5-1의 오염 사례).
