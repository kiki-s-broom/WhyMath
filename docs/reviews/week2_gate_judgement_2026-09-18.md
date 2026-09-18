# Week 2 Gate 판정 — 계획서 300 Phase 2 §7

**판정 기준: main `54f9af588fc28ec10bcaf1e4189a8ac2a4fd5133`**
**판정자**: claude (구현 세션과 분리 — 이 세션은 판정 하네스만 만들고 P-05~P-07 기능을 구현하지 않았다)
**태스크**: `EOS-110`
**선행**: P-05 = `EOS-12`(Evidence 3종 계약) · P-06 = `EOS-13`(update_mastery 호출 계약) + `EOS-18`(임시 어댑터 폐기) · P-07 = `EOS-104`(오개념 후보 생산자 배선) — 전건 `done`·main 머지 확인

---

## 1. 판정

> **통과 (PASS)**

완료 판정 문면은 *"오답 1건이 Attempt→Assessment→Misconception→Mastery→LearnerState 전 구간에
전파되고 이벤트와 일치"* 다. **전파했고, 이벤트와 일치했다.**

판정은 exit code로 냈다(인상 판정·점추정 없음).

## 2. 오답 1건 투입 전후 LearnerState 스냅샷

같은 학습자·같은 호출(`GET /v1/me/learner-state`)을 투입 전후로 한 번씩 찍었다. **값 변화가 증거다.**

| LearnerState 축 | 투입 **전** | 투입 **후** |
|---|---|---|
| `mastery`(개념코드→BKT) | `{}` (0건) | `{"UC.w2gate.<sfx>": 0.15}` (1건) |
| `active_misconceptions` | `[]` | `["distribution-over-power"]` |
| `skill_mastery`(skill_id→BKT) | `{}` (0건) | `{"skill.w2gate.<sfx>": …}` (1건) |

투입한 것은 **오답 한 건**이다 — `POST /v1/me/attempts`,
`{problem_id, is_correct: false, student_answer: "x^2+4"}`. 문항 발문은 `(x+2)^2`(원 문서 §7 예시).

세 축이 모두 *키 자체가 없던 상태*에서 *값이 있는 상태*로 바뀌었다. `mastery`·`skill_mastery`는
미측정이면 키가 없는 규약(None≠0)이라, 0건→1건이 곧 "이 오답이 처음으로 이 축을 만들었다"는 뜻이다.

## 3. 구간별로 무엇을 단언했는가

`tests/backend/api/test_week2_gate_wrong_answer_propagation.py` — 공개 HTTP 표면만 쓰고, 구간마다
status code가 아니라 **산출물**을 단언한다. 학습자 상태 테이블은 한 줄도 직접 쓰지 않는다(Week 1
게이트의 시딩 경계를 그대로 승계 — 그 모듈의 헬퍼를 재사용한다).

| # | 구간 | 무엇으로 통과를 판정했나 | 실측 |
|---|---|---|---|
| 1 | **Attempt** | `POST /v1/me/attempts` 201 + `attempt_id` 발급 + 학생 대면 문항 조회에 정답 비노출 | 201 |
| 2 | **Assessment** | 응답 `evidence`가 존재하고 3종이 다 채워짐. 개념 증거가 PRIMARY·`refuting`, 스킬 증거가 개념의 행동 스킬로 해소됨 | `filled=3/3` (concept 1·skill 1·misconception 1) |
| 3 | **Misconception** | `coverage.misconception_scan == ran_with_candidates` + 기대 오개념이 `gate_passed=True`로 후보에 실림 | `distribution-over-power` conf `0.9` |
| 4 | **Mastery** | 그 증거가 개념·스킬 숙달 갱신으로 이어짐(`mastery_updates`·`skill_mastery_updates`) | concept `0.15` (sample_size 1) · skill 갱신 |
| 5 | **LearnerState** | §2의 전후 스냅샷 3축이 전부 변함 + 응답만이 아니라 **조회 표면**에도 도달 | 0건→1건 · 오개념 활성화 |
| 6 | **이벤트 일치** | `GET /v1/me/learning-trace`의 값이 상태의 값과 **같음** | `mastery_before=None → after=0.15` = state `0.15` |

6구간의 `mastery_before=None`은 결함이 아니라 계약이다 — 첫 측정이라 직전 값이 없고, 0.0으로
채우면 "없는 상승"이 만들어진다(None≠0 규약).

## 4. 이벤트 일치 — 그리고 그 일치가 **얼마나 독립적인가**(정직 표기)

게이트 문면은 "두 곳이 어긋나면 KPI 2 위반"이다. 어긋나지 않았다. 다만 **"두 곳"이 실제로 얼마나
독립적인지**를 분명히 적어 둔다 — 이것을 적지 않으면 이 판정이 실제보다 강해 보인다.

- `mastery_updated`(트레이스)와 `LearnerState.mastery`는 **둘 다 `concept_mastery_history`를 읽는다**
  (트레이스는 SQL `lag`로 전후를 계산한 투영, LearnerState는 최신값 조립). 즉 이 축의 일치는
  *두 기록자가 같은 말을 한다*가 아니라 *한 원천의 두 투영이 어긋나지 않는다*이다.
- `misconception_detected`와 `LearnerState.active_misconceptions`도 같은 관계다(둘 다
  `misconception_hypothesis`).
- **독립 기록자는 `attempt_event` 하나다** — `record_attempt_skill_event`가 숙달 적재와 *별도
  트랜잭션*으로 쓰고, 트레이스에서 `skills_resolved`로 실린다. 그래서 하네스는 이 축을
  `source == "attempt_event"`까지 못박아 단언한다.

그러므로 이 게이트가 실측으로 배제한 것은 **"상태는 바뀌었는데 행동 이벤트가 없다"**는 형태의
KPI 2 위반이고(§5 M6가 그것을 증명한다), 배제하지 *못한* 것은 같은 테이블의 두 투영이 함께
틀리는 형태다.

## 5. 하네스 변별력 — 뮤테이션 7종 전건 RED

정상 입력에서 초록인 것은 보호의 증거가 아니므로, **서빙 코드에서 구간을 하나씩 끊어** 판정이
실제로 미통과를 내는지 확인했다 (`scripts/ops/verify_week2_gate_discrimination.py`).
주입마다 ①치환 대상이 정확히 1건인지 ②주입 후 해시가 원본과 다른지 ③원복이 바이트 동일한지를
단언한다(원복은 `git checkout`이 아니라 바이트 백업 복원 — 미커밋 작업분 보호).

| 뮤테이션 | 끊은 구간 | 결과 |
|---|---|---|
| M1 | Assessment — 증거 조립 결과를 응답에서 지움 | RED |
| M2 | Misconception — 훑기를 `not_run`으로 고정 | RED |
| M3 | Misconception→LearnerState — 후보를 영속하지 않음 | RED |
| M4 | Mastery(개념) — 증거를 숙달로 옮기지 않음 | RED |
| M5 | Mastery(스킬) — 스킬 증거를 숙달로 옮기지 않음 | RED |
| M6 | 이벤트 — `attempt_event`를 남기지 않음 | RED |
| M7 | 대조군 — 탐지기가 아무 오답이나 잡게 만듦 | RED |

기준선(뮤테이션 전 정상 상태) `exit=0`을 먼저 확인한 뒤 돌렸다 — 그게 없으면 뒤의 RED가
뮤테이션 때문인지 환경 때문인지 구별할 수 없다.

### 5-1. M6는 처음에 **생존했다** — 그리고 그것이 하네스의 결함이었다

지우지 않고 병기한다. 1회차에서 M6(이벤트 적재 생략)가 `exit=0`으로 살아남았다. 원인은 제품이
아니라 내 단언이었다: 나는 이벤트 축을 `problem_attempted` 엔트리로 확인했는데, 그 엔트리는
`attempt_event`가 아니라 **`problem_attempt` 테이블**이 낸다. `attempt_event`의 물리 타입 `문제시도`는
트레이스에서 `skills_resolved`로 실린다(`_ATTEMPT_EVENT_TYPE_MAP`). 즉 이벤트 테이블이 통째로
죽어도 내 판정은 통과했다 — **이벤트 축을 재고 있다고 믿으면서 재지 않았다.**

`source`까지 못박은 단언으로 교체하자 M6가 RED가 됐다. 뮤테이션이 없었으면 이 판정은 "이벤트
일치 확인"이라고 적힌 채로 틀렸을 것이다.

## 6. 이 판정이 보지 **않은** 것 (전건 RED는 커버리지의 증거가 아니다)

뮤테이션은 *내가 주입 목록에 올린* 절만 검사한다. 아래는 이번 판정의 사정거리 밖이며, 통과를
이 범위 너머로 읽으면 안 된다.

1. **채점 권위** — 이 경로(`POST /v1/me/attempts`)의 `is_correct`는 **클라이언트 자가보고**이고
   서버가 채점하지 않는다(v1 설계·`api/me.py` docstring 명시). 원 문서 P-05 ③의 "SymPy 단일 권위
   경유"는 서버 권위 채점 경로(`coach.py::_complete_problem`)의 이야기다. 이 축은 이미
   `REC-07`(채점 권위 이관 결정·사람 결정)이 소유하므로 **새 태스크를 등재하지 않는다**.
2. **이중 반영 방지** — 같은 attempt를 두 번 제출했을 때의 멱등성은 재지 않았다. attempt commit →
   숙달 → 이벤트가 각각 별도 트랜잭션이고 멱등키가 없다는 한계가 코드에 명시돼 있다
   (`l2/attempt_skill_event.py`). 이 축은 P-06 ③의 요구이며 **`EOS-108`**(Mastery Engine v1 — 클램프·
   Attempt 멱등·mastery 단일 쓰기 경로 AST 가드)이 소유한다. 그 태스크는 다른 세션 브랜치에서
   `status: done`이지만 **판정 시점 main에는 없다**(미머지) — 그래서 이 판정은 그것을 전제하지
   않았고, 중복 등재도 하지 않는다.
3. **오개념 탐지의 사정거리** — 카탈로그 **67종 중 `canonical_wrong_form`을 가진 것은 2종**
   (`distribution-over-power`·`exponent-zero`·실측)이다.
   이 픽스처는 그 사정거리 *안*의 오답이고, 밖의 오답에서는 `ran_no_candidate`가 정상이다
   (대조군 테스트가 그것을 고정한다). 게이트는 연결성만 보므로 탐지 재현율은 판정 대상이 아니다.
4. **confidence 감쇠** — P-07 ⑤가 요구하는 누적·감쇠 규칙은 오답 *1건*으로는 관측되지 않는다
   (감쇠는 재관측되지 않은 회차에 일어난다). 이 게이트 문면이 "오답 한 건"이므로 범위 밖으로 둔다.

## 7. 판정이 바꾼 것 — 대장 1줄 (제품 코드 0)

판정 하네스가 `GET /v1/me/learner-state`를 호출하면서, 그 라우트를 "아직 아무도 안 부른다"로
선언하던 유예가 **stale-waiver**가 됐다(`declared_unwired_audit` exit 1 — 추론이 아니라 도구 출력).
저장소 규약대로 유예를 걷었다: 도달했는데 유예를 남기면 게이트가 red다.

정직한 잔여를 함께 적는다 — 이 축의 `reached`는 "dart 클라 호출 ∪ 백엔드 테스트 호출"이므로,
reached는 *판정 하네스가 관통한다*는 뜻이지 *학생 앱이 쓴다*는 뜻이 아니다. **모바일 소비는 여전히
0건**이고 `MOB-22`가 계속 소유한다. 다만 MOB-22의 acceptance ②("완료 시 이 선언을 걷는다")는 이
해제로 이미 충족됐으므로, 그 태스크 완료 시 다시 걷을 항목은 없다 — 주석에 그 사실을 남겼다.

이것이 이 PR이 `src/` 아래에서 바꾼 **유일한** 것이고, 서빙 동작은 건드리지 않는다(분류 대장 주석·
엔트리 1줄).

## 8. 후속 태스크

**0건.** 게이트의 5구간 어디에도 끊긴 지점이 없었다. §6의 인접 축 2건은 이미 소유자가 있다
(`REC-07`·`EOS-108`) — 중복 등재는 하지 않는다.
