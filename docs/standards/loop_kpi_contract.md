# 학습 루프 KPI 계약 (Phase 2 §19 · 5종) — 정본

> **집행 코드**: `src/backend/whymath_backend/ops/loop_kpi_gate.py`
> **좌석**: `EOS-15-loop-completion-and-manual-intervention-kpi`
> **판정 기준**: main `a58a8473` (2026-09-19 실측)

계획서 300 §19가 Phase 2의 성공을 기능 개수가 아니라 **학습 루프의 런타임 무결성 5축**으로
정의했다. 이 문서는 그 5축의 분자·분모·출처·판정 방식과, **기존 KPI 12종과의 경계**를 고정한다.

---

## 1. 정본 경계 — 왜 12종에 편입하지 않았는가

이 저장소에는 이미 KPI 정본이 있다.

| | 콘텐츠 생산 KPI **12종** | 학습 루프 KPI **5종** |
|---|---|---|
| 집행 | `ops/validation_scorecard.py` | `ops/loop_kpi_gate.py` |
| 재는 것 | 콘텐츠가 **얼마나 싸고 정확하게 만들어지는가** | 학생 한 명의 루프가 **끝까지 흐르는가** |
| 분모 | 생산된 콘텐츠 단위(CU) | 실행된 학습 루프 |
| 판정 시점 | 12/31 최종 G5 | 상시(운영 관측창) |
| 정본 문서 | `docs/standards/eos_verification_design_v1.md` §6 | 이 문서 |

**분모가 다르므로 같은 표에 얹지 않는다.** 얹으면 "KPI 17종"이라는 하나의 평균이 생기고,
그 평균은 콘텐츠 생산이 잘 되는 것으로 루프 붕괴를 덮는다(붕괴 연쇄 ④ "truth source가
하나가 아님"). 대신 **별도 축**으로 선언하고 경계를 코드가 지킨다:

- `loop_kpi_gate`는 `validation_scorecard`를 import하지 않고, 그 반대도 아니다.
- 두 KPI 이름 공간이 겹치지 않음을 거버넌스 테스트가 상시 확인한다
  (`test_loop_kpi_gate.py::test_axis_is_disjoint_from_validation_scorecard`).
- 5종은 **종합 점수를 만들지 않는다**(12종과 동일 규율 — 평균이 앵커를 덮지 않게).

---

## 2. 5종 정의표 — ①분자 ②분모 ③출처 ④산출 명령

임계는 **전부 코드가 갖는다**(`LOOP_KPI_SPECS`). 입력(`--input`)은 관측치만 내며, 임계·방향
키가 섞이면 CLI가 거부한다 — 입력이 자기 합격선을 써 내면 그것은 판정이 아니라 자기 신고다.

| KPI | 분자 | 분모 | 출처 | 판정 |
|---|---|---|---|---|
| ① Loop Completion Rate | 관측창에 시작된 세션 중 **그 세션의 첫 시도 이후**(서버 수신 시각)·관측창 끝 이전에 같은 `session_id`의 `recommendation_render`가 1건 이상 있는 세션 수 | 관측창에 시작된 세션 중 **시도(`problem_attempt`)가 1건 이상** 있는 세션 수 — 시도 없는 세션 수는 `detail.sessions_without_attempt`로 따로 보고(조용히 빼지 않는다) | `learning_session` × `problem_attempt` × `evidence_event` | Wilson **하한** ≥ 0.95 |
| ② State Integrity | 무결성 위반 행 수(7종 합) | 스캔 대상 행 수(7종 합) | `ops/integrity_violations_gate.scan_integrity` | Wilson **상한** ≤ 0.01 |
| ③ Explainability | `meta.reason`이 없는 `recommendation_render` 건수 | 그 전체 건수 | `evidence_event`(REC-11) | **무관용** — 분자 > 0이면 미달 |
| ④ Manual Intervention | 운영자 계열 감사 3종(`admin_access`·`role_change`·`content_mutation`) 행 수 | 관측창에 적재된 `problem_attempt` 행 수 | `privacy_audit` × `problem_attempt` | **무관용** |
| ⑤ Traceability | 체인이 끊기는 recommendation 건수(첫 끊긴 홉 1개로 계상 — `detail.break_*`) | 근거 기록 개시 이후의 recommendation 건수 — 그 전의 소급 불가 기록은 `detail.excluded_pre_basis`로 따로 보고 | `evidence_event`(`meta.learner_state_basis`) × `learning_session` × `concept_mastery_history` × `problem_attempt` × `problem` | **무관용** |

⑤의 체인: `Recommendation → LearnerState → Assessment → Attempt → Problem`. 홉 정의·조인 키는 §2-1.

**①의 재정의(EOS-131 ⑨ · 2026-09-25)**: 종전 분자는 "추천 기록이 **하나라도** 있는 세션"이었다.
서버 유휴 규칙 세션 writer는 `/me/next-problem`도 세션을 여는 활동으로 치고, 앱은 첫 문제를
추천으로 받으므로 옛 정의로는 거의 모든 세션이 **시작 순간** '도달'이 된다 — 동어반복이다. 재려는
것은 Attempt → Assessment → Mastery → Recommendation 흐름이므로, **첫 시도 뒤의 추천**만 도달로
센다. 시도가 없는 세션은 루프가 시작되지 않은 것이라 분모에서 뺀다. 대안("next-problem을 세션 개시
활동에서 제외")은 첫 추천이 세션 없이 기록돼 추천↔학습자 결합이 다시 끊기므로 채택하지 않았다.
실패 주입 3종(시도 전 추천만 → 미도달 · 시도 후 추천 → 도달 · 시도 뒤 추천 없음 → 미도달)은
`tests/backend/ops/test_loop_kpi_gate_integration.py`가 실 PG로 동결하며, 옛 정의로 되돌리면
첫 번째가 RED다.

### 2-1. ⑤ 역추적 — 홉 정의·조인 키·경계 (EOS-132 · 판정 기준 main `a0e60965`)

**LearnerState 홉은 추천 기록에 남긴 근거로만 되짚는다.** `LearnerState`는 매 호출 조립되고
영속하지 않는다(EOS-10). 종전 원천 대장은 이 홉을 `user_state_snapshot`에 매달아 두었는데 그 좌석은
writer 0건 빈 좌석이라 ⑤가 구조적 미측정이었다. 이제 `/v1/me/next-problem`이 추천을 기록할 때 그
추천이 본 상태의 근거 식별자(`l2.learner_state.LearnerStateBasis`)를 `meta.learner_state_basis`에
싣는다 — 최신 숙달 행 키 `(concept_id, measured_at)` · 전과목 θ 스냅샷 id · 활성 오개념 가설 행 id ·
조립 시각. 식별자와 시각만 싣는다(B1). 이 좌석은 `user_state_snapshot`을 쓰지 않으므로 ARCH-51의
그 좌석 처분이 ⑤를 막지 않는다.

| 홉 | 조인 키 | 끊김 코드(`detail.break_*`) |
|---|---|---|
| ① 추천 → 학습자 | `evidence_event.session_id → learning_session.user_id` | `learner_unjoined` — 세션 기록 실패 placeholder·SEC-40 착지 이전에 삭제돼 남은 잔여. 삭제권 이행은 이제 그 세션의 추천 기록을 함께 지우므로(처분 (나)·EOS-37) 삭제 자체는 이 끊김을 만들지 않는다 |
| ② → LearnerState | `meta.learner_state_basis`(키 부재 · 형식 불량 · 가리키는 θ 스냅샷/가설 행이 없거나 다른 학생 것) | `basis_missing` · `basis_malformed` · `basis_row_missing` |
| ③ → Assessment | 근거 숙달 행 `(학습자, concept_id, measured_at)` — µs까지 정확히 일치 | `assessment_missing` |
| ④ → Attempt | 그 행의 `concept_mastery_history.attempt_id → problem_attempt`(같은 학생) | `attempt_missing` |
| ⑤ → Problem | `problem_attempt.problem_id → problem` | `problem_missing` |

홉 판정의 정본은 `ops/loop_kpi_gate.classify_trace`(순수 함수)이고, 수집기는 근거가 가리키는 행을
**추천마다가 아니라 한 번씩 모아** 읽는다(`_trace_lookups` — IN 목록 500건 단위).

**Assessment 홉은 `assessment` 테이블이 아니다 (⑦ 실측 판정).** ⓐ `problem_attempt`에 assessment
참조 컬럼이 없어 진단 세션(`assessment` 행)은 시도에 닿지 않는다 ⓑ EOS-79 4층 경계
(`docs/architecture/evidence_layer_boundary.md`)가 "`assessment` 테이블은 Assessment 층이 아니다"를
이미 정본화했다 — 그 테이블은 진단 1회의 결과 묶음이다 ⓒ Assessment 층의 정의("그 결과가 어느
개념의 어떤 증거인가")를 체인에서 실현하는 것은 **근거 숙달 행의 귀속(개념 × 시도)**이다. 그래서
`_REQUIRED_SOURCES`의 ⑤ 항목도 `DIAGNOSTIC_COMPLETED`(assessment 테이블)에서 `MASTERY_UPDATED`
(숙달 행)로 바로잡았다. 진단 시도만 Assessment에 속하는 것이 아니다 — 채점되는 모든 시도
(`/v1/me/attempts`·코치 완료)가 평가 개념마다 `attempt_id`를 채운 숙달 행을 남긴다(EOS-108 이후).

**이어지지 않는 추천 유형과 그 판정**:
- 숙달 측정 이력이 없는 학생의 추천(사전값) — 근거가 `{"absent": "no_mastery_history"}`로 적힌다.
  ③~⑤는 **해당 없음**이며 끊김이 아니다(`detail.traced_prior_only`).
- θ 스냅샷이 아직 없는 학생 — `{"absent": "no_ability_snapshot"}`. 스냅샷은 시도마다 찍히지 않으므로
  (루프 writer = EOS-125) 정상 상태다. 끊김이 아니다.
- EOS-108 이전에 `attempt_id` 없이 적재된 숙달 행을 근거로 삼은 추천 — **끊김**(`attempt_missing`).
  그 행에서 시도로 가는 길이 실제로 없다.
- 세션 기록 실패·삭제권 이행 — **끊김**(`learner_unjoined`). 관측창 안에서 삭제권이 이행되면 그 창의
  ⑤가 미달로 나온다 — 알려진 사각이며 `coverage_note`가 항상 함께 말한다.

**"근거 없음"과 "근거 모름"을 같은 글자로 세지 않는다 (⑧).** 근거가 비어 있는 것은 키 안의
`absent` 사유로 말하고(정상), 근거 키 자체가 없는 기록은 끊김(`basis_missing`)이다. 기록 경로는
근거를 넘겨받지 못하면 키를 **넣지 않는다**(null로 쓰지 않는다).

**소급 불가 기록 (⑥).** 근거 기록 개시 = 근거가 실린 **첫** 추천의 시각(관측창과 무관한 전역
최솟값). 그 이전의 근거 없는 추천은 분모에서 빼고 `detail.excluded_pre_basis`로 센다 — 조용히
실패로 계상하지도, 조용히 빼지도 않는다. 개시 이후의 근거 부재는 끊김이다. 관측창 전부가 개시
이전이면 분모 0 → 미측정(exit 2). 개시를 코드 상수로 두지 않은 이유: 배포 시각을 코드가 모르므로
상수는 배포 전후 하루를 미달로 만들거나(너무 이르면) 진짜 회귀를 제외로 삼킨다(너무 늦으면). 대신
치르는 비용 — 기록 경로가 처음부터 근거를 안 쓰면 ⑤는 미달이 아니라 미측정으로 머문다. 이 축은
서빙 경로 통합테스트(`tests/backend/api/test_eos132_learner_state_basis_integration.py` — 실 HTTP로
추천을 불러 근거가 DB의 최신 숙달 행과 같은지 확인)가 CI `backend-migrations` 잡에서 막는다.

**사후 재구성을 채택하지 않은 근거 (③).** 추천 시각 T의 상태를 나중에 재구성하는 방식은 숙달
시계열(append-only)과 θ 스냅샷(append-only)에는 되지만, 오개념 가설 레코드는 `updated_at`으로
덮어써져 T 시점의 활성 집합을 복원할 수 없다. 한 축이라도 복원이 안 되면 그 홉은 "되짚었다"가
아니라 "추정했다"가 된다. 그래서 조립 시점에 쓴 근거를 기록한다.

**알려진 한계**: 근거는 `get_state`와 같은 요청·같은 트랜잭션의 **별도 문장**으로 읽는다(세 근거는
한 문장이라 서로 일관). 두 문장 사이에 같은 학생의 채점이 커밋되면 근거가 측정 한 번 앞선 행을
가리킬 수 있다 — 가리키는 행은 실재하므로 역추적은 성립한다. 앱은 다음 문항을 받은 뒤 답을 내므로
정상 흐름에서는 생기지 않는다. 근거는 **추천이 소비한 상태만** 남긴다 — 학습·코치·상태 조회가
조립한 상태는 기록되지 않는다.

### 산출 명령

```bash
# 운영 DB 대상 판정(exit 0/1/2)
python -m whymath_backend.ops.loop_kpi_gate --since-hours 24 \
    --json out/loop_kpi.json --evidence out/loop_kpi_evidence.ndjson

# CI(빈 DB)용 — 수집 완주만 본다(exit 0/1)
python -m whymath_backend.ops.loop_kpi_gate --schema-smoke

# 위반 주입 드릴 — DB 없이 관측치만으로 판정
python -m whymath_backend.ops.loop_kpi_gate --no-db --input observations.json
```

### 종료 코드

| code | 뜻 |
|---|---|
| 0 | 5종 전부 측정됐고 전부 충족 |
| 1 | 1종 이상 **위반**(측정됐고 미달). 미측정이 함께 있어도 위반이 우선 |
| 2 | 위반 없음, 1종 이상 **미측정** — "0건 통과" 위장을 막는 자리 |
| 3 | 실행 오류(인자·파일 I/O). **DB 접속 실패는 3이 아니라 2**다 |

---

## 3. 분모 판정 — ①은 EOS-131 전까지 측정 불가였다 (이력)

**해소(2026-09-25 EOS-131)**: 아래 두 사실이 모두 사라졌다 — `l2/learning_session_writer`가 서버
30분 유휴 규칙으로 세션 행을 만들고, 추천 기록이 실 `session_id`로 결합된다. 원천 대장이
`PRODUCED`로 바뀌어 ①은 설계대로 **스스로 미측정을 벗었다**(세션이 0건인 관측창은 여전히 분모 0 →
미측정 exit 2). ⑤는 LearnerState 시각 원천(`user_state_snapshot` DORMANT)이 남아 여전히 미측정이었다
— **2026-09-28 EOS-132가 해소했다**(§2-1: 원천을 추천 기록의 근거로 옮기고 분자 쿼리를 채웠다).
아래는 2026-09-19 판정 기록이다.

**세션의 의미(재방문율 KPI2와 공유)**: 서버 추론 세션은 "앱 진입~종료"가 아니라 **학습 활동 묶음**
(마지막 학습 활동으로부터 30분 이내의 활동들)이다. 앱을 열기만 하고 학습 활동이 없으면 세션이
생기지 않는다.

계획서는 ①의 분모를 "시작한 학습 세션"이라고 적었는데, 당시 이 저장소에서 그 단위는 아무도 쓰지
않았다. 두 사실이 겹쳤다(2026-09-16 `l2/learning_event_trace` 실측·2026-09-19 재확인):

1. `learning_session`에 **writer가 0건**이다(조회·종료·삭제 표면만 있다).
2. `evidence_event`에 `user_id` 컬럼이 없고 `session_id`는 호출마다 `uuid.uuid4()`
   placeholder다 — **분자를 분모에 붙일 조인 키가 없다**.

선택지 세 개 중 **"측정 불가를 명시한다"**를 택했다. 다만 그것을 *정지*가 아니라 *자동 해제*로
만들었다: 구조적 선결을 `l2/learning_event_trace`의 원천 대장(`_SOURCE_REGISTRY`)에서 읽으므로,
누군가 세션 writer를 배선해 그 대장이 `PRODUCED`로 바뀌면 ①·⑤가 **스스로 미측정을 벗는다**.
사실을 이 문서나 게이트에 다시 적지 않는 이유가 그것이다 — 적으면 두 곳이 어긋난다.

> 실 DB 검증(2026-09-19): 원천 대장만 `PRODUCED`로 바꾸고 세션 20건(추천 도달 18건)을 심자
> ①이 `18/20`을 세고 `Wilson 하한 0.7383 < 0.95`로 미달 판정했다. 조인이 실제로 돈다.

**다른 분모로 갈아타지 않은 이유**: `problem_attempt` 건수를 분모로 쓰면 "시도마다 추천이
하나씩 나와야 한다"는, 계획서가 말한 적 없는 계약이 새로 생긴다. 그건 지표가 아니라 설계 변경이다.

⑤도 같은 이유로 미측정이었다(EOS-131이 추천 결합 홉을, EOS-132가 LearnerState 홉을 풀었다 — §2-1).
끊긴 홉을 빼고 남은 홉만 재서 "100% 역추적"이라고 적는 것이 정확히 이 게이트가 막으려는 거짓말이며,
그래서 EOS-132 전까지 ⑤는 조회 없이 미측정을 냈다.

---

## 4. ④의 사각 — 볼 수 있는 개입과 볼 수 없는 개입

"운영자 DB 개입"의 관측 가능한 표면은 `privacy_audit`뿐이며, 거기에는 감사 행을 *남기는*
경로만 나타난다(`ops/role_grant_cli`·콘텐츠 CUD 라우터). **`psql` 직접 UPDATE, 시드 스크립트,
마이그레이션 데이터 수정은 이 표면을 지나지 않는다.**

그러므로 ④가 0이라는 것은 "개입이 없었다"가 아니라 "**감사되는 표면에서는** 개입이 없었다"이다.
리포트는 이 한계를 `coverage_note`로 항상 함께 낸다. 가리면 없는 보호를 있다고 말하는 것이 된다.

학생 본인 행위(`export_data`·`consent_change`)는 개입으로 세지 않는다 — 세면 정상 학습
시나리오가 위반으로 계상된다.

---

## 5. 설계 규칙 6 (어기면 계측기가 계측기가 아니게 된다)

1. **미측정은 통과가 아니다** — 분모 0에서 "위반 0건 → 100%"를 만들지 않는다. 독립 exit code(2).
2. **무관용 축에는 Wilson을 쓰지 않는다** — ③④⑤는 1건이면 미달이다. 대신 분자 0으로 통과할 때
   Wilson **상한**을 `residual_upper_bound`로 함께 내어 관측 0을 확정 0으로 과신하지 않는다.
3. **비율 축은 방향까지 지표가 갖는다** — ①은 하한, ②는 상한. 결함율에 하한을 쓰면 1%가
   0.5% 기준을 통과한다.
4. **임계는 코드가, 관측치는 입력이** — `--input`은 `numerator`·`denominator`·
   `unmeasured_reason`·`source`만 받고 그 밖의 키는 **거부**한다(오타 포함 — 조용히 버리면
   제출자는 자기 값이 쓰였다고 믿는다).
5. **인프로세스 이중 회계** — 5종 전부 우리 PostgreSQL에서 직접 센다. 판정 경로에 외부 관측
   SaaS(Langfuse·OTel)를 두지 않는다. 그 인프라가 죽으면 "측정 실패"가 보여야지 "0건 통과"로
   위장되면 안 된다. 거버넌스 테스트가 이 불변식을 동결한다.
6. **실패해도 증거가 남는다** — `--evidence`의 NDJSON은 단계마다 **즉시 flush**되고, 수집
   실패는 **예외 타입명 + 모듈**과 함께 기록된다. 모든 줄에 `run_id`와 관측창이 박혀 있어
   이전 실행의 증거를 이번 것으로 오독할 수 없다. 수집기마다 타임아웃을 건다.

부수 규칙: 한 수집기가 실패하면 **세션을 rollback**한 뒤 다음 수집기로 간다. 안 하면 중단된
트랜잭션 때문에 멀쩡한 수집기가 거짓 실패하고, 고장 1건이 N건으로 보고된다
(2026-09-19 실측: `evidence_event.meta` 하나를 개명했더니 수집기 2종이 실패로 찍혔다).

---

## 6. 검증 — 주입 없이는 "계측된다"고 말하지 않는다

| 축 | 방법 | 결과(2026-09-19) |
|---|---|---|
| 판정기 | hermetic 스위트 68건(정상 ↔ 위반 쌍) | 전건 통과 |
| 판정기 가드 | 뮤테이션 17종 주입 | **17/17 RED**(검출) |
| 수집기 | 실 PG 통합테스트 8건(주입 전/후/정리 3단) | 전건 통과 |
| 실 DB 드릴 | ②고아 15건 ③reason 누락 1건 ④역할변경 1건 주입 | 각각 해당 KPI만 FAIL·exit 1 |
| 스키마 스모크 | `evidence_event.meta` 개명 주입 | exit 1, 되돌리면 exit 0 |
| ⑤ 판정기(EOS-132 · 2026-09-28) | hermetic — 홉마다 **그 홉만 끊긴** 반례 + ⑧ 1쌍 + 개시 경계 | 전건 통과 |
| ⑤ 수집기(EOS-132) | 실 PG — 전용 과거 관측창에 7건(제외 1·이어짐 1·사전값 1·끊김 4종) | 홉별 1건씩 정확히 계수·분자 4/분모 6·미달 판정 |
| ⑤ 서빙 경로(EOS-132) | 실 HTTP — 추천→오답→추천 | 근거 = DB 최신 숙달 행 · 사전값 1·이어짐 1·끊김 0 |

**"뮤테이션 전건 RED"를 커버리지로 읽지 않는다**(CLAUDE.md 2026-09-08) — 주입 목록에 없는 절은
애초에 검사되지 않는다. 그래서 픽스처가 없던 분기(DB 접속 실패 폴백·입력 타입 검사·리포트
저장 실패)를 따로 찾아 테스트를 추가하고 그 위에 뮤테이션 5종(M13~M17)을 더 얹었다.
M17은 실 PG에서만 변별력이 있다 — `meta -> 'reason'`(JSON null이 새는 형태)로 되돌리면
JSON-null 통합테스트가 RED가 된다.

### CI 배선 (선언 ≠ 배선)

- **hermetic 스위트** → `backend` 잡의 Pytest 스텝(기존 배선 그대로).
- **스키마 스모크 + 통합테스트** → `backend-migrations` 잡(실 PG). 스모크는 전용 스텝이고,
  통합테스트는 그 잡의 `pytest -m integration`이 집는다.
- **KPI 판정 자체는 CI에 걸지 않는다** — CI DB는 마이그레이션만 적용한 빈 DB라 5종이 전부
  미측정이고, 그 상태로 판정을 걸면 상시 red가 되어 사람이 게이트를 끈다. 판정은 운영
  DB(파일럿·prod)에서 `--since-hours`로 돌린다. 이 결정을 여기 적어 두는 이유는, 적지 않으면
  다음 사람이 "만들어 놓고 CI에 안 걸었다"로 읽기 때문이다.
