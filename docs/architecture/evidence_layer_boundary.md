# 학습 증거 4층 경계 — Attempt · Evaluation · Assessment · Mastery (EOS-79)

> **지위**: `EOS-79-evidence-layer-boundary-canon` 산출물. 계획서 200 §24의 "Attempt ≠ Evaluation
> ≠ Assessment ≠ Mastery"를 이 저장소의 실물에 대고 **판정 가능한 규칙**으로 옮긴 것이다.
> 새 증거 모델·새 writer가 어느 층에 속하는지 다툼이 생기면 §1의 판별 질문으로 답한다.
>
> **대조 시점**: 2026-09-05 · main `f90dde83` · 실측 대상 = `db/models/` ORM 55파일 전수 +
> `schema/` 40파일 + 학생 경로 writer(`api/coach.py`·`api/me.py`·`l2/*`).
>
> ## ⚠️ 정본화 ≠ 집행 — 이 문서는 **배정을 강제하지 않는다**
>
> 새 모델을 엉뚱한 층에 넣어도 **CI는 통과한다.** 층 귀속을 판정하는 기계는 이 저장소에 없다
> (§3에서 검색 범위와 함께 밝힌다). 이 문서에 딸린 유일한 기계 장치
> (`tests/infra/test_evidence_layer_boundary_doc.py`)가 검사하는 것은 **표가 가리키는 테이블이
> 실재하는가**뿐이다 — *배정이 옳은가*는 검사하지 않는다. 그러므로 이 문서의 존재를 근거로
> "증거 층이 지켜지고 있다"고 말하면 안 된다. 지금 있는 것은 **층의 정의와, 그 정의가 실물을
> 가리킨다는 보장**뿐이다.

---

## §0. 이 문서가 침범하지 않는 것 — 32번 문서의 3계층과는 **축이 다르다**

`docs/architecture/32_learning_history.md` §2.3은 **이미 ADR로 동결된 3계층**을 갖고 있다:
`Raw Event → Learning History → Learner State`. 그 표도 실물 모델을 배정한다. 두 문서가 같은
것을 두 번 정의하면 이중 진실 원천이 되므로, 관계를 먼저 못박는다.

| | 32번 §2.3 (3계층) | 이 문서 (4층) |
|---|---|---|
| **묻는 것** | 이 데이터는 **얼마나 가공됐는가** | 이 데이터는 **무엇에 대한 증거인가** |
| **축** | 원자 사실 → 의미 부여 이력 → 추론된 상태 | 입력 → 정오 → 귀속 → 누적 상태 |
| **쓰이는 때** | 저장소·보존·삭제권·재계산 설계 | 새 증거 writer의 **소속 판정**, 스코어카드 입력 선택 |
| **지위** | **선행 정본** — 충돌 시 32번이 우선 | 그 위에 얹는 **두 번째 축** |

두 축은 직교하지 않지만 서로를 대체하지 못한다. 예: `concept_mastery_history`는 32번 축에서
**Learning History**(append-only 측정 시계열)이고 이 문서 축에서는 **Mastery**다 — 가공 단계로는
중간이고 증거 종류로는 최종이다. 반대로 `attempt_event`는 32번 축에서 **Raw Event** 하나지만
이 문서 축에서는 **Attempt와 Assessment가 동거**한다(§2). 한 축의 배정으로 다른 축을 추론할 수
없다는 것이 두 문서를 따로 두는 이유다.

### 세 번째 축 — `canonical_entity_model_v1.md`(ARCH-37, 2026-09-05 같은 날 착지)

ARCH-37은 78테이블을 **핵심 엔티티 19종**에 귀속시킨다. 그 축은 "이 테이블은 *무엇의*
테이블인가"(정체성)이고, 이 문서의 축은 "이 데이터는 *무엇에 대한 증거*인가"다. 경쟁하지 않는다 —
오히려 **정확히 맞물린다**: ARCH-37이 이 문서의 표에 있는 **11개 테이블을 `LearningEvent` 한
엔티티로 묶는데**(`:176`), 그 묶음 안을 가르는 것이 이 문서의 4층이다. 엔티티가 같다고 증거 층이
같지 않다(같은 `LearningEvent` 안에 Attempt·Evaluation·Assessment가 다 있다). 셋의 관계:

| 문서 | 축 | 단위 |
|---|---|---|
| `32_learning_history.md` §2.3 | 얼마나 가공됐는가 | 3계층 |
| `canonical_entity_model_v1.md` (ARCH-37) | 무엇의 테이블인가 | 19 엔티티 |
| **이 문서** | 무엇에 대한 증거인가 | **4층** |

ARCH-37이 독립적으로 같은 규율에 도달한 항목도 있다 — "좌석이 있다고 writer가 있다는 뜻이
아니다"(그 문서 §7-C). 이 문서의 귀속표가 **writer 열**을 따로 둔 이유와 같다.

> **32번 문서 내부 불일치 1건 (이 작업의 실측 부산물)**: §2.3 표는 `concept_mastery_history`를
> **Learning History**로 배정하는데, 같은 문서 §3 데이터 흐름(`:56-68`)은 5단계
> `Raw Event → Learning History → Evidence → Learner State → 소비자`를 그리며 같은 테이블을
> **Evidence**에 넣는다. 이 문서는 그 불일치를 해소할 권한이 없다(32번이 선행 정본이다) —
> **발견 사실로만 적고** 32번 소유자에게 남긴다.

> **부재 판정 기록** (CLAUDE.md "식별자 부재를 기능 부재로 단정 금지"): `EOS-79` 등재 시의
> 실측은 "네 개념의 경계를 규정한 정본 문서 **0건**"이었고 검색 범위를 `docs/architecture/0*.md`
> 21건 + `docs/standards/`로 밝혔다. 이 작업에서 **역할 기반으로 다시 검색**하자
> (`증거 층`·`계층 분리`·`evidence layer`·`Learner State`, 한/영 양쪽 · `docs/` 전체) 32번
> §2.3·§8과 `adr/ADR-002`(이벤트냐 엔티티냐 판정 기준)가 나왔다. 등재 시 판정이 틀린 것이
> 아니라 **찾던 축이 아니었던 것**이다 — "Evaluation"을 *층 이름*으로 쓰는 문서는 재검색에서도
> 0건이고, 4개를 나란히 세운 문서도 0건이었다. 이 항목은 부재 주장이 검색 방법에 의존한다는
> 규칙의 실사례로 남긴다.

---

## §1. 판정 규칙 — 4층 정의

정의는 "대체로 이런 느낌"이면 판정 근거가 되지 못한다. 각 층은 **한 문장의 판별 질문**과
**그 층이 아님을 보이는 반증**을 함께 갖는다.

| 층 | 정의 | 판별 질문 (예 → 그 층) | 이 층이 **아닌** 신호 |
|---|---|---|---|
| **Attempt** | 학생이 무엇을 입력했는가 | 채점기를 **통째로 바꿔도** 이 값이 그대로인가? 그리고 학생이 그 행동을 안 했으면 이 행이 아예 없는가? | 값이 정오 규칙에 의존한다 → Evaluation |
| **Evaluation** | 그 답이 맞았는가 | 이 값은 **채점 규칙의 함수**인가? 규칙이 바뀌면 같은 입력에서 값이 바뀌는가? | 어느 스킬·오개념인지를 말한다 → Assessment |
| **Assessment** | 그 결과가 **어느 Skill·오개념의 어떤 증거인가** | 이 행을 지우면 *학생이 무엇을 아는지*의 근거가 사라지는가? (그 문항을 풀었다는 사실·정오는 남고) | 귀속 없이 정오만 있다 → Evaluation |
| **Mastery** | 누적 증거를 반영한 **현재 상태** | 원본 증거를 재생하면 이 값을 **다시 만들 수 있는가**? | 재계산 불가능하다 → 그건 상태가 아니라 원본 증거다 |

### 층을 가르는 세 불변식

1. **Mastery는 파생이다.** 증거에서 재계산할 수 없는 값을 Mastery 층에 두면 안 된다 —
   32번 §8 원칙 8("모델 교체 시 history로부터 재계산 가능")의 이 축 표현이다. 재계산이
   불가능하다면 그 값은 원본 증거이므로 Attempt·Evaluation·Assessment 중 하나로 내려간다.
2. **하위 층은 상위 층을 읽지 않는다.** Attempt·Evaluation 적재 코드가 Mastery를 읽어 분기하면
   증거가 자기 파생물에 의존하는 순환이 된다(BKT 입력이 BKT 출력에 의존). 읽어야 한다면 그것은
   적재가 아니라 *교수학 결정*이며 L4로 올라간다.
3. **학생이 없으면 층도 없다.** 4층은 **학생 증거의 축**이다. 데이터 주체가 학생이 아닌 행
   (시스템 산출물의 채점·검수자의 판정·콘텐츠 자산)은 층 밖이다(§4).

### 층 ≠ 테이블 ≠ 이름

- **한 테이블이 한 층이라는 보장은 없다.** 이 저장소의 실물이 그렇지 않다(§2에 혼재 5건).
  판정 단위는 테이블이 아니라 **컬럼 묶음 또는 이벤트 타입**이다. 새 writer를 붙일 때
  "이 테이블은 Attempt 테이블이니까"는 근거가 되지 못한다 — 쓰려는 **값**에 §1의 질문을 건다.
- **이름이 층을 정하지 않는다.** `assessment` 테이블은 Assessment 층이 *아니고*,
  `evidence_event` 테이블의 실제 내용은 대부분 학습 증거가 *아니다*(§2). 이름은 단서일 뿐이다.

---

## §2. 현행 코드 귀속표

배정 불가는 **혼재로 그대로 적는다**(EOS-65 경계표 선례 — 애매한 것을 한쪽으로 반올림하면
어느 쪽으로 반올림하든 판정을 왜곡한다). 좌표는 `src/backend/whymath_backend/` 기준.

**`writer` 열을 함께 둔 이유**: 이 저장소는 "좌석이 있다"와 "채워진다"를 반복해서 혼동해 왔다.
층 배정만 적고 writer를 안 적으면, **아무도 안 쓰는 빈 테이블이 스코어카드 입력 후보로 보인다.**

<!-- EVIDENCE_LAYER_MAP_BEGIN — 이 블록은 tests/infra/test_evidence_layer_boundary_doc.py가 파싱한다.
     형식: | `테이블명` | 좌표 | **배정** | writer | 근거
     배정 허용값: Attempt / Evaluation / Assessment / Mastery / 혼재 / 반례 -->

| 테이블 | 좌표 | 배정 | writer | 근거 |
|---|---|---|---|---|
| `attempt_event` | `db/models/activity.py:263` | **혼재** (Attempt + Assessment) | 실재 (`api/coach.py` 5개소 · `l2/attempt_skill_event.py:110` · `api/interactions.py:75`) | 검산결과·힌트제공·힌트요청·막힘은 원자 행동(Attempt). 그러나 `record_attempt_skill_event`가 **같은 테이블**에 `문제시도` 이벤트로 `skill_ids`를 실어 스킬 귀속(Assessment)을 쓴다. **`event_type`이 층을 가른다 — 테이블이 아니라** |
| `problem_attempt` | `db/models/activity.py:145` | **혼재** (Attempt + Evaluation) | 실재 (`api/me.py:745` · `api/coach.py:1012`) | `student_answer`·`handwriting_uri`·`ocr_result`·`attempt_mode`·`duration_seconds`는 Attempt, `is_correct`는 Evaluation. 한 행에 동거. §5의 비대칭이 여기서 난다 |
| `answer_submission` | `db/models/answer_submission.py:74` | **혼재** (Attempt + Evaluation + Assessment) | **없음 — 빈 좌석** (32번 문서 `:99` "writer 배선은 EOS-32 범위 밖 … 그 전까지 이 테이블은 빈 좌석이다") | 세 층이 한 행에 있는 유일한 모델. `raw_response`·`latex`·`canonical_ast`=Attempt · `grading_result`=Evaluation · `error_analysis.suspected_misconception_ids`=Assessment 입력 |
| `student_solution_step` | `db/models/student_solution_step.py:64` | **혼재** (Attempt + Evaluation) | **없음 — 빈 좌석** (ORM docstring `:70` 자인) | `expression`·`canonical_ast`=Attempt, `validation`(SymPy 단계 판정)=Evaluation. `evidence_links`가 "N번째 step의 오류"로 참조하는 안정 참조 대상이지만, 참조된다고 층이 올라가지 않는다 |
| `hint_usage` | `db/models/hint_usage.py:57` | **Attempt** | **없음 — 빈 좌석** (ORM docstring `:61` 자인 · 테스트만 가용성 증명) | 학생이 힌트를 연 사건. `problem_attempt.used_hint` 불리언과 이중 기록 관계이며, Mastery *해석*의 조건 변수이지 그 자체가 상태는 아니다 |
| `evidence_links` | `db/models/evidence_link.py:53` | **Assessment** (오개념 축) | 실재 (`l4/misconception/evidence_store.py:127`) | 한 행 = 한 학습 이벤트가 한 오개념 가설을 `polarity`(+1 지지/−1 반박)로 지지·반박. 정의 그대로 "어떤 증거인가" |
| `evidence_event` | `db/models/evidence_event.py:54` | **혼재** (Assessment + 층 밖) | 실재 (`l2/pedagogy_evidence.py:149,237` · `l2/recommendation_evidence.py:107`) | 이름과 달리 **대부분 학습 증거가 아니다**. writer 3개 중 2개가 담는 것은 교수법 *처치*·추천 *노출*이고, 학습목표 달성 증거(Assessment)와 한 테이블에 산다. 분리 수단은 `event_type` 문자열 필터뿐이고(open TEXT set) **`user_id` 컬럼 자체가 없다**(가명화) |
| `concept_mastery_history` | `db/models/assessment.py:157` | **Mastery** | 실재 (`l2/mastery_tracking.py:134`) | append-only 측정 시계열(BKT). 증거에서 재계산 가능(불변식 1 충족) |
| `skill_mastery_history` | `db/models/assessment.py:196` | **Mastery** | 실재 (`l2/skill_mastery_tracking.py:136`) | 위와 같음(스킬 축) |
| `ability_snapshot` | `db/models/assessment.py:236` | **Mastery** | 실재 (`api/me.py:1085,1156`) | IRT θ(logit) 시계열. BKT 숙달(확률 0–1)과 **척도가 다른 채로 같은 층**에 있다 — §6 미결 |
| `user_state_snapshot` | `db/models/user.py:282` | **Mastery** | **없음 — 빈 좌석** (전수 grep: 프로덕션에 ORM 생성·`session.add` 0건. `l2/learner_state.py`는 **메모리 조립기**이고 이 ORM을 import하지 않는다) | 32번 축에서는 Learner State. 이 축에서는 재계산 가능한 파생 상태라 Mastery. **32번 `:48`이 이 테이블을 Learner State 구현으로 든 것은 좌석 지목이며 writer 실재를 뜻하지 않는다**(PR #985 Codex 지적으로 재실측·정정) |
| `misconception_hypothesis` | `db/models/misconception_hypothesis.py:55` | **Mastery** (오개념 축) | 실재 (`l4/misconception/evidence_store.py`) | `confidence`·`evidence_count`를 갖는 누적 상태. `evidence_links`(Assessment)가 갱신하는 파생물이라 Mastery의 오개념 축 짝 |
| `assessment` | `db/models/assessment.py:66` | **혼재** (Assessment + Mastery + 층 밖) | 실재 (`api/me.py:2811,3024`) | **이름이 층과 같지만 층이 아니다.** 진단 평가 1회의 *결과 묶음*이다: `concept_diagnosis`·`weak_points`=Assessment · `estimated_grade/score/percentile`=Mastery · `recommended_path`=추천(층 밖). 새 필드를 여기 넣을 때 어느 층인지 따로 판정해야 한다 |
| `daily_learning_metrics` | `db/models/timeseries.py:64` | **Mastery** (집계) | 실재 (`l2/learning_metrics_rollup.py`) | 증거에서 재계산 가능한 일별 롤업. 학생 축 유지 |
| `user_behavior_metrics` | `db/models/timeseries.py:161` | **반례** (운영 텔레메트리) | 실재 | §4 — `metric_name` open set(이탈 위험 등). 학습 증거인지 운영 지표인지 경계가 열려 있어 축 밖으로 둔다 |
| `learning_session` | `db/models/activity.py:67` | **반례** (맥락) | **없음 — 빈 좌석** (`l2/recommendation_evidence.py:29` "writer 0 — REC-01 실측") | §4 — 증거가 아니라 증거가 붙는 좌표계 |
| `dialogue_turn` | `db/models/dialogue.py:143` | **반례** (대화 본문) | 실재 | §4 — 32번 `:188`이 "AI Tutor 대화 전문은 Learning History에 넣지 않는다"로 이미 층 밖에 뒀다 |
| `verified_solutions` | `db/models/verified_solution.py:71` | **반례** (증거 아님) | 실재 (`whs/solution_bank.py:96`) | §4 — 학생이 없다 |
| `solution_nodes` | `db/models/solution_node.py:82` | **반례** (증거 아님) | 실재 (WH-S) | §4 — MCTS 탐색 노드(시스템 데이터) |
| `dead_end_log` | `db/models/dead_end_log.py:45` | **반례** (증거 아님) | 실재 (WH-S) | §4 — 솔버의 막다른 길. `UNIQUE`로 중복을 접는 멱등 캐시라 append-only 증거와 성질이 다르다 |
| `atom_probe` | `db/models/atom_probe.py:55` | **반례** (콘텐츠 자산) | 실재 (코퍼스 적재) | §4 — `diagnostic_*` 이름 때문에 Assessment로 오분류되기 쉬우나 **문항 원본**이다 |
| `review_timer_event` | `db/models/review_timer_event.py:54` | **반례** (검수 대장) | 실재 (`harness/review_timer.py`) | §4 — 데이터 주체가 학생이 아니라 검수자 |

<!-- EVIDENCE_LAYER_MAP_END -->

### 이 표가 드러낸 것 두 가지

1. **Evaluation 층에 단독 좌석이 없다.** Evaluation은 `problem_attempt.is_correct`,
   `answer_submission.grading_result`, `student_solution_step.validation` **세 컬럼으로만**
   존재하며 그것만 담는 테이블은 없다. 그중 뒤 둘은 **빈 좌석**이다. 즉 오늘 살아 있는
   Evaluation 증거는 사실상 `is_correct` 한 컬럼이고, §5의 비대칭이 그 위에서 난다.
2. **빈 좌석 5건** — `answer_submission`·`student_solution_step`·`hint_usage`·`learning_session`
   (Attempt·Evaluation 쪽) + `user_state_snapshot`(Mastery 쪽). 하위 층에 4건이 몰려 있고
   Mastery는 5좌석 중 4개가 살아 있다. 증거 파이프라인이 **아래가 비고 위가 찬** 모양이며,
   위가 찬 이유는 `attempt_event`·`problem_attempt` 두 좌석이 아래 몫까지 감당하기 때문이다
   (그래서 그 둘이 혼재다). Mastery의 빈 좌석 1건은 성격이 다르다 — 조립기는 있는데
   **영속 경로가 없다**(메모리에서 만들고 버린다).

---

## §3. 집행 — 무엇이 기계로 강제되고 무엇이 안 되는가

| 축 | 기계 강제 | 지점 |
|---|---|---|
| 표가 가리키는 **테이블이 실재하는가** | **예** | `tests/infra/test_evidence_layer_boundary_doc.py` — 마커 블록을 파싱해 각 테이블명이 `db/models/`의 `__tablename__`으로 실재하는지, 배정 라벨이 허용 6종인지 대조. 마커 부재·빈 목록은 "위반 0 통과"가 아니라 **실패**(`test_required_checks_doc.py` 선례) |
| **배정이 옳은가** | **아니오** | 없음. 새 모델을 엉뚱한 층에 넣어도 CI는 통과한다 |
| 새 증거 모델이 **표에 등재됐는가** | **부분** | 같은 테스트의 `test_every_evidence_table_is_mapped`. **12개 모듈 한정**(`activity`·`answer_submission`·`student_solution_step`·`hint_usage`·`evidence_link`·`evidence_event`·`assessment`·`misconception_hypothesis`·`verified_solution`·`dead_end_log`·`atom_probe`·`review_timer_event`) — 그 안에 모델을 추가하고 표를 안 고치면 red다. **밖은 강제되지 않는다**: `user.py`·`timeseries.py`·`dialogue.py`처럼 비증거 테이블이 섞인 모듈은 등재를 강요하면 사용자·결제 테이블까지 끌어와 무차별 red가 되므로 제외했다 |
| 불변식 2(하위→상위 참조 금지) | **아니오** | 없음 |
| 불변식 3(학생 없는 행 배제) | **아니오** | 없음 |

**"없음"의 검색 범위**(부재 판정 절차): `tests/infra/` 전건에서 `attempt_event`·`evidence_event`
검색 0건. `ls tests/infra | grep -i "governance\|boundary\|contract"` 3건은 모두 다른 축
(CI 계약·EOS Core/Adapter 경계). `scripts/ops/`의 스캐너 2종도 라우팅 축이다. **내가 찾은
방법으로는 층 귀속을 판정하는 기계 0건**이다.

**왜 배정 강제를 만들지 않았는가**: 층 귀속은 컬럼 묶음의 *의미* 판정이라 정적으로 재려면
컬럼명 화이트리스트가 필요하고, 그것은 표기 변형에서 뚫리는 "금지 패턴 열거" 형태가 된다
(CLAUDE.md 2026-09-01 ①). 변별력 없는 가드는 보호가 아니라 위장이므로, **있는 척하지 않고
없다고 적는다.** 실효 있는 강제는 새 증거 writer가 층을 *선언*하게 만드는 설계 변경이며
그것은 이 문서의 범위 밖이다(§6).

---

## §4. 반례 — 4층에 안 들어가는 실재 모델 (층을 늘리지 않는다)

불변식 3이 판정한다. 층 밖 모델이 나오면 층을 늘리는 것이 아니라 **축 밖이라고 적는다** —
관계 타입 폭발 금지의 동형이다. 층을 하나 늘리면 그 층에 들어갈 것을 찾게 되고, 다음 애매한
모델마다 층이 하나씩 는다.

| 모델 | 왜 축 밖인가 |
|---|---|
| `verified_solutions` | **학생이 없다**(`user_id` 컬럼 부재). `grade`(verified/unverified)는 *풀이의 품질*이지 *학생의 정오*가 아니다. 콘텐츠 자산(L1/L3) |
| `solution_nodes` · `dead_end_log` | WH-S MCTS 탐색 노드·막다른 길 — 시스템이 만든 데이터. `student_solution_step`과의 혼동을 ADR-002가 명시적으로 부인한다 |
| `atom_probe` | 진단 **문항 원본**(발문·정답·오답신호). 학생 응답이 아니다 |
| `review_timer_event` | 데이터 주체가 **검수자**(`reviewer_id`). `verdict`·`failure_code`가 Evaluation처럼 보이나 평가 대상이 학생 답이 아니라 **콘텐츠(CU)**다 |
| `learning_session` | 증거가 아니라 **증거가 붙는 좌표계**. 세션 자체는 무엇을 입력했는지도 맞았는지도 말하지 않는다. 4층 대부분이 참조하지만 참조된다고 증거가 되지 않는다 |
| `dialogue_turn` | 대화 본문(봉투 암호화). `student_understanding_signal`이 판정처럼 보이나 문항 채점이 아니라 턴 단위 추정이며, 32번 `:188`이 이미 층 밖으로 뒀다 |
| `user_behavior_metrics` · `problem_solve_time_distribution` | 운영 텔레메트리·문항×페르소나 집계. 앞은 `metric_name`이 open set이라 학습/운영 경계가 열려 있고, 뒤는 **학생 축이 아예 없다**(문항 축 분포) |
| 정서·감정 신호 (L2 계획) | CLAUDE.md L2가 "정서신호"를 계층 요소로 든다. 행동이라는 점에서 Attempt에 가깝지만 *무엇을 아는지*의 증거가 아니라 *어떤 상태인지*의 신호다. **현재 실물 테이블 부재**(검색: `emotion`·`affect`·`정서` — `db/models/` 0건)라 배정을 미룬다. 생기면 그때 4층으로 충분한지 재검토한다 |

**층을 늘려야 한다는 판단은 하지 않았다.** 실측한 22개 모델 중 4층으로 **배정 불가는 0건**이다
(혼재 5건은 *배정 불가*가 아니라 *복수 배정*이다). 축 밖 8건은 층이 부족해서가 아니라 애초에
학생 증거가 아니라서 밖이다 — 즉 이 저장소의 실물은 4층으로 **충분히 덮인다**.

---

## §5. 이 문서가 드러낸 것 — **오답이 Evaluation 층에 남지 않는다**

`docs/reviews/eos_phase2_plan_300_gap_review_2026-09-03.md`가 판정을 보류하고 이 태스크로
넘긴 열린 질문("오답이 `ProblemAttempt` 행을 남기지 않는 것이 설계 의도인지 갭인지")에
대한 실측 회신이다.

**실측**: `problem_attempt`에 행을 만드는 writer는 저장소 전체에 **2개뿐**이다.

| writer | `is_correct` | 학생 앱이 부르는가 |
|---|---|---|
| `api/coach.py:1016` `_complete_problem` | **`True` 고정** (서버 권위 판정) | **예** — 학생 경로 |
| `api/me.py:750` `submit_attempt` | `body.is_correct` (클라 자가보고 — False 가능) | **아니오** |

두 번째 경로를 앱이 부르지 않는 것은 우연이 아니라 **계약**이며(`api/coach.py:445`
"클라는 별도로 `POST /v1/me/attempts`를 부르지 않는다 — 중복 적재 금지"),
`src/mobile/test/e2e_loop_flow_test.dart:254`가 그 엔드포인트가 호출되지 **않음**을 동결한다.

**따라서 1급 학생 앱(Flutter)이 실제로 타는 경로에서는 `problem_attempt.is_correct = False` 행이
생기지 않는다.** 오답의 흔적은 Attempt 층(`attempt_event`의 검산결과 `passed=False`·힌트요청·막힘)
에만 남는다. Evaluation의 나머지 두 좌석(`answer_submission.grading_result`·
`student_solution_step.validation`)은 빈 좌석이라 대신 받아 주지도 않는다(§2).

> **범위 정정 (PR #985 Codex 지적 수용)**: 이것은 *구조적 불가능*이 아니라 **1급 클라이언트의
> 계약**이다. `POST /v1/me/attempts`는 살아 있는 **인증 엔드포인트**이고(`user: ConsentedUser`),
> 인증된 학생·다른 클라이언트(별도 웹·외부 소비자 — 코어를 API로 소비하는 구조)가 부르면
> `is_correct=False` 행이 **실제로 만들어지고 숙달까지 전파된다**(`api/me.py:750`). Flutter
> E2E 테스트가 동결하는 것은 *그 앱의 코치 흐름이 그 요청을 하지 않는다*는 사실 하나뿐이다.
> 그러므로 아래 결론은 "오늘 우리 앱이 만드는 데이터"에 대한 진술이지 스키마 수준의 보장이
> 아니다 — 오답 행의 부재를 **불변식으로 가정하는 코드를 쓰면 안 된다.**

**판정**: 갭인지 의도인지 이 문서는 단정하지 않는다 — 그것은 교수학·측정 설계의 결정이고
근거가 코드에 없다. 이 문서가 확정하는 것은 **경계 사실** 하나다:

> 오늘 1급 학생 앱이 만드는 데이터에서 Evaluation 층의 음(−) 증거는 영속되지 않으며, 그
> 자리를 Attempt 층 신호가 대신하고 있다. (엔드포인트 수준에서는 가능하다 — 위 범위 정정.)

이것이 중요한 이유는 세 소비자가 서로 다른 층을 읽기 때문이다: 숙달 전파
(`record_problem_attempt_mastery`)는 Evaluation을 읽고, 오개념 루프(`evidence_links`)는
Assessment를 읽으며, WH-1 지표는 Attempt를 읽는다. 오답이 Evaluation에 없다는 사실은
**숙달 추정의 분모에만 영향을 주고** 나머지 둘에는 주지 않는다 — 세 소비자를 한 덩어리로
"증거"라고 부르면 보이지 않는 비대칭이다.

---

## §6. 미결·후속 후보 (이 문서에서 등재하지 않음 — 판단 필요)

- **오답 영속 여부의 교수학 판정** — §5의 비대칭이 의도인지. BKT/DKT가 음 증거를 필요로 하는지가
  판정 기준이며, 필요하다면 `_complete_problem` 외에 오답 적재 좌석이 필요하다.
- **Mastery 층의 이질 척도** — `concept_mastery_history`(BKT 확률 0–1)와 `ability_snapshot`
  (IRT θ logit)이 같은 층에 다른 척도로 공존한다. 층을 쪼갤 일인지 척도 변환을 정본화할
  일인지 미결.
- **`evidence_event`의 두 도메인 분리** — 학습목표 달성 증거와 교수법 처치·추천 노출이
  `event_type` 문자열 필터로만 갈린다. 테이블 분리 또는 enum 도입 후보.
- **32번 문서 §2.3 ↔ §3 불일치** — `concept_mastery_history`의 3계층 배정. 32번 소유자 몫.
- **새 증거 writer의 층 선언 강제** — §3의 미강제 축을 실효화하려면 writer가 층을 선언하고
  기계가 그 선언과 쓰는 컬럼을 대조해야 한다. 설계가 필요한 규모다.

## §7. 참고 문서

- `docs/architecture/32_learning_history.md` §2.3·§3·§8 — **선행 정본**(3계층 축·충돌 시 우선)
- `docs/architecture/canonical_entity_model_v1.md` (ARCH-37) — 엔티티 정체성 축(19종). 이 문서 표의 11테이블이 그쪽 `LearningEvent` 하나에 묶인다
- `docs/architecture/adr/ADR-002-student-solution-step-entity.md` — "이벤트냐 엔티티냐" 판정 기준
- `docs/architecture/eos_core_adapter_boundary.md` — 경계표 서술 형식의 선례(EOS-65)
- `docs/reviews/eos_phase1_plan_200_gap_review_2026-09-01.md` §8.1 D3 — 이 태스크의 출처
- `docs/reviews/eos_phase2_plan_300_gap_review_2026-09-03.md` — §5가 회신하는 열린 질문의 출처
