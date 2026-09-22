# [원본 보존] WhyMath → EOS 1과목 완성: 2026년 12월 말 출시 계획

> **이 문서는 Kiki 제공 원 문서의 전사본(轉寫本)이며, 세션의 해석·판단·추가는 한 줄도 섞여 있지 않다.**
> 존재 이유는 단 하나다 — `EOS-128`(Phase 3 실행계획 → 백로그 변환) 1회차가 **"원 문서가 저장소·원격 브랜치·PR·히스토리 어디에도 없다"**는 이유로 차단됐기 때문이다.
> 입력이 채팅 첨부로만 존재하면 세션이 바뀔 때마다 같은 차단이 재발한다. 그 재발을 끊는 것이 이 파일이다.

| 항목 | 값 |
|---|---|
| 원본 파일 | `400_Phase_3___Math_EOS___________.docx` (Kiki 첨부, 2026-09-22) |
| 원본 sha256 | `b109941c324d1aa5dbdc112e1878309899d75b9d5bc70cd659b2ea65bee7a012` |
| 원본 크기 | 27,032 바이트 · 추출 텍스트 7,108자 |
| 문서 내 작성 시점 | 본문이 "현재 시점인 2026년 8월 27일"이라고 밝힘 |
| 전사 방식 | `word/document.xml` 텍스트 노드 전량 추출 후 목록·표를 마크다운으로 재배치. **어휘·수치·순서 무변경** |
| 저작 주체 | Kiki (WhyMath 기획). 외부 저작물 인용분 없음 |
| 전사 세션 | `claude/compassionate-hypatia-chznsu` (2026-09-22) |

**미첨부분 (이 파일에 없는 것)**: 집행 지시문 세트 `[02/20]~[15/20]`에 해당하는 **기준 분해안 P3-01~P3-14**. `EOS-128` acceptance ①이 원 문서와 **함께** 요구하는 입력이며 현재까지 어디에도 없다. 이 파일은 그 절반만 메운다.

---

## 1. 12월 31일의 목표 상태

현재 시점인 2026년 8월 27일에서 12월 31일까지 약 18주가 남아 있다. 이 기간에 가장 중요한 것은 EOS 전체 기능을 완성하는 것이 아니라, **수학 1과목을 EOS Core 위에서 실제 서비스 가능한 수준으로 완성**하는 것이다.

전체 전략은 다음 한 문장으로 정리된다.

> 9월에는 구조를 고정하고, 10월에는 EOS 학습 폐쇄루프를 완성하고, 11월에는 콘텐츠·품질을 완성하고, 12월에는 기능 개발을 멈추고 출시 안정화에 집중한다.

12월 말에 만들어져 있어야 하는 것은 단순한 WhyMath MVP가 아니라 **Math EOS v1.0**이어야 한다.

**학생 관점** — 다음 흐름이 처음부터 끝까지 끊기지 않아야 한다.

회원/프로필 → 교육과정 선택 → 진단 → 학습자 상태 생성 → 개념 추천 → 이론/콘텐츠 → 문제 추천 → 풀이 → 채점 → 오개념 판정 → 힌트/AI 설명 → 숙련도 갱신 → 다음 학습 추천 → 학습 결과

**관리자 관점** — 다음이 운영되어야 한다.

교육과정 → 개념 → Skill → 문제 → 풀이 → 오개념 → 교수전략 → 콘텐츠 → 검수 → 승인 → 버전 → 배포

**시스템 관점** — 다음 경계가 실제 코드에 존재해야 한다.

EOS Core → Subject Contract → Math Adapter → WhyMath

이 세 가지가 모두 만족돼야 "EOS 1과목 완성"이라고 본다.

## 2. 전체 18주 로드맵

| 단계 | 기간 | 핵심 목적 | 결과물 |
|---|---|---|---|
| Phase 0 | 8/27~9/6 | 방향 전환·범위 동결 | EOS v1 Scope, 기능 재분류 |
| Phase 1 | 9/7~9/27 | EOS Core 구조 확정 | Core Contract v1 |
| Phase 2 | 9/28~10/25 | Math Vertical Slice 완성 | 학생 학습 폐쇄루프 |
| Phase 3 | 10/26~11/22 | 과목 완성도 확보 | 콘텐츠·AI·관리자 기능 |
| Phase 4 | 11/23~12/13 | Beta·QA·성능 안정화 | Release Candidate 후보 |
| Phase 5 | 12/14~12/31 | 출시 | Math EOS v1.0 |

---

## 6. Phase 3 — Math EOS 과목 완성 (10월 26일 ~ 11월 22일)

10월까지 엔진을 완성했다면 11월부터는 **수학이라는 과목의 완성도**가 중요해진다. 여기서 개발팀이 흔히 하는 실수가 **다시 새로운 EOS 기능을 만드는 것**이며, 하지 않는 것이 좋다.

11월의 중심은 **콘텐츠 + UX + 품질 + 관리자 운영**이다.

- **학생 측** — 이론 설명 / 문제 / 풀이 / 힌트 / 오개념 / 추천 / AI Tutor / 진도 / 숙련도 / 복습 / 학습 기록
- **관리자 측** — Curriculum CMS / Concept CMS / Problem CMS / Solution CMS / Misconception CMS / Content Version / QA / Approval / Publish / Rollback

이 관리 루프가 있어야 출시 후 콘텐츠 운영이 가능하다.

**콘텐츠 전략** — 모든 수학 영역을 얕게 만드는 것보다 **대표 과정 하나를 완전히 만드는 것**을 추천한다. 특정 중학교 과정 또는 특정 고등학교 과정에서 `교육과정 → Concept → Skill → Problem → Solution → Misconception → Pedagogy` 연결 밀도를 매우 높게 만들고, 나머지 영역은 점차 확장한다.

### Phase 3 방향에 대한 보정

이 Phase 3 방향은 맞다. 다만 "콘텐츠 + UX + 품질 + 관리자 운영"이라는 표현만으로는 **4주 동안 다시 범위가 퍼질 위험**이 크다. Phase 3는 신규 EOS 기능 개발 단계가 아니라, **Phase 2에서 만든 폐쇄루프를 실제 한 과목에서 촘촘하게 채우고 운영 가능하게 만드는 단계**로 더 강하게 정의하는 것이 좋다.

특히 10월 26일~11월 22일의 종료 조건을 "기능이 있다"가 아니라 **"대표 과정 하나가 실제 학생에게 판매 가능한 수준으로 끝까지 작동한다"**로 잡아야 한다.

### Phase 3의 핵심 목표

> Math EOS의 대표 교육과정 1개를 대상으로 학습 데이터, 콘텐츠, AI, 운영도구를 모두 연결하여 실제 서비스 가능한 **Subject Package v1**을 완성한다.

이 단계에서 중요한 것은 기능 개수가 아니라 **Coverage × 연결밀도 × 품질 × 운영가능성**이다.

예를 들어 Concept가 1,000개 있는데 서로 느슨하게 연결되어 있는 것보다, 대표 과정에 필요한 **Concept 150~300개**가 아래처럼 완전히 연결되어 있는 편이 훨씬 가치가 높다.

Curriculum Standard → Unit → Concept → Skill → Prerequisite → Problem → Solution → Misconception → Hint → Pedagogy → Mastery Evidence → Recommendation

---

## Phase 3 실행계획 (2026년 10월 26일 ~ 11월 22일, 4주)

### Week 1 — 10/26~11/1 · 대표 과정 동결 + Coverage 완성

이 주에는 새 기능을 만들기보다 먼저 **"무엇을 완성할 것인가"를 고정**한다.

**반드시 결정해야 하는 것**

1. 출시 대표 과정 1개
2. 대상 학년/과목/단원 범위
3. Curriculum Node 목록
4. Concept 목록
5. Skill 목록
6. 핵심 오개념 목록
7. 필수 Problem Type 목록
8. 문제 수량 목표
9. 콘텐츠 completeness 기준

**이 시점부터 원칙적으로 금지되는 변경** (예외는 Release Blocker뿐)

1. EOS Core 신규 Entity 추가
2. 대규모 DB Schema 변경
3. 새로운 AI Agent 추가
4. 새로운 Subject Adapter 추가
5. 대규모 UI 구조 변경

**Week 1 완료 기준**

대표 과정의 모든 Curriculum 항목이 최소 `Curriculum → Concept → Skill → Problem` 구조를 가져야 하고, 핵심 개념은 추가로 `Prerequisite` / `Misconception` / `Solution` / `Hint` / `Pedagogy`까지 연결되어야 한다.

**지표 — Content Coverage Rate**

`Coverage = 완전 연결 Concept / 출시 대상 Concept` · 출시 후보라면 핵심 Concept 기준 **95% 이상** 목표.

### Week 2 — 11/2~11/8 · Problem / Solution / Misconception 밀도 확보

이 주가 사실상 **WhyMath의 차별화가 만들어지는 시기**다. 단순히 문제은행을 많이 넣는 것이 아니라 `Concept ↔ Problem ↔ Misconception` **삼각관계**를 구축해야 한다.

**각 핵심 Concept마다 최소 확보할 문제 6종**

1. 대표 문제
2. 기본 문제
3. 응용 문제
4. 오개념 유발 문제
5. 진단 문제
6. 숙련도 확인 문제

**각 Problem이 가져야 할 필드 7종**

`difficulty` · `skill` · `concept` · `solution` · `answer` · `misconception signature` · `hint strategy`

**Wrong Answer 처리** — 단순히 incorrect로 처리하면 EOS의 가치가 크게 떨어진다. 가능하면 다음 구조까지 만들어야 한다.

학생 답안 → Error Signature → Misconception Candidate → Confidence → Remediation Strategy

### Week 3 — 11/9~11/15 · AI Tutor + Personalization 품질 완성

이 주에는 AI Tutor의 **기능을 늘리는 것이 아니라 정확성과 교육적 일관성을 높인다**.

**AI Tutor가 최소한 받아야 할 context 9종**

학생 상태 · 현재 Concept · 현재 Skill · 문제 · 학생 답안 · 풀이 기록 · 추정 Misconception · Mastery · Pedagogy Policy

**Tutor output 구조화** — 자유 텍스트 하나가 아니라 가능하면 구조화한다. 예시 스키마의 필드는 다음과 같다.

- `diagnosis.concept_id` — 예: CONCEPT_QUADRATIC_AXIS
- `diagnosis.misconception_id` — 예: MIS_SIGN_AXIS_01
- `diagnosis.confidence` — 예: 0.87
- `response_strategy` — 예: guided_hint
- `hint_level` — 예: 2
- `explanation` — 설명 본문
- `next_action` — 예: retry_problem
- `mastery_update_allowed` — 예: false

이 방식은 이후 Physics, Chemistry 등으로 확장할 때도 큰 자산이 된다.

**AI 품질 Gate — 최소 별도 평가 8축**

1. 수학적 정확성
2. 정답 누설
3. 오개념 판정 정확도
4. Hint 적절성
5. 설명 일관성
6. 학생 수준 적합성
7. hallucination
8. Curriculum 범위 이탈

이 시점부터는 **모델 성능보다 EOS의 검증 레이어가 더 중요**하다.

### Week 4 — 11/16~11/22 · CMS + QA + Publish 운영루프 완성

마지막 주에는 **개발자 없이 콘텐츠팀이 어느 정도 운영할 수 있어야** 한다.

**최소 운영 흐름**

Draft → Review → QA → Approved → Published → Deprecated / Rollback

**관리자가 최소한 볼 수 있어야 하는 것 (CMS 12종)**

| CMS | 필수 작업 |
|---|---|
| Curriculum | 조회·수정·버전 |
| Concept | CRUD·관계 |
| Skill | Concept 연결 |
| Problem | 문제·정답·난이도 |
| Solution | 풀이 관리 |
| Misconception | Signature·교정 |
| Pedagogy | 교수전략 |
| Content | 설명/힌트 |
| QA | 검수상태 |
| Version | 변경이력 |
| Publish | 배포 |
| Rollback | 이전 버전 복구 |

CMS를 지나치게 예쁘게 만들 필요는 없다. **운영 가능성 > UI 완성도**.

---

## Phase 3에서 반드시 측정해야 할 지표

이 단계부터는 "몇 개 기능이 완성됐는가"를 주요 지표로 사용하지 않는 것이 좋다. 대신 다음 6개가 훨씬 중요하다.

| 지표 | 의미 | 목표 예시 |
|---|---|---|
| Curriculum Coverage | 출시 범위 연결 정도 | ≥ 98% |
| Concept Completeness | Concept 데이터 완전성 | ≥ 95% |
| Problem Coverage | Skill별 문제 확보 | ≥ 95% |
| Solution QA Pass | 풀이 정확성 | ≥ 99% |
| Learning Loop Success | E2E 학습 완료율 | ≥ 95% |
| Critical Defect | 출시 차단 결함 | 0 |

여기에 EOS 특성을 보여주는 지표를 하나 더 넣는다면 **Graph Connectivity Coverage**를 추천한다. 예를 들어 핵심 Concept 중 `Concept → Skill → Problem → Misconception → Pedagogy` 경로가 완전히 존재하는 비율이다. 이 값이 높아야 "문제은행 앱"이 아니라 **Education OS 기반 학습 시스템**이라고 말할 수 있다.

## Phase 3의 매우 중요한 금지 목록 (Not Now List)

11월에 가장 위험한 것은 **기능 욕심**이다. 따라서 별도로 Not Now List를 운영하는 것을 권한다. EOS 270개 후보 기능 가운데 다음과 같은 것들은 **12월 출시 이후로** 보내는 것이 좋다.

1. Digital Twin 고도화
2. 가상 학습 실험
3. 성장 경로 장기 예측
4. 교수법 자동 개선
5. 콘텐츠 자동 리팩토링
6. 다과목 Adapter
7. 연구자 협업
8. 복잡한 Agent 협업
9. Graph 자동 군집화
10. 자동 교육과정 생성
11. 국제 Curriculum 확장
12. 고급 추론 엔진

기술적으로 좋은 기능이더라도 **Math EOS v1 출시를 늦추면 현재는 부채**다.

## Phase 3 Release Gate

11월 22일에는 회의를 통해 "대충 됐다"고 판단하면 안 된다. 명확한 Gate를 통과해야 한다.

### Gate A — 학생 폐쇄루프

실제 학생 계정에서 다음 전체 과정이 **사람이 DB를 직접 수정하지 않고** 동작해야 한다.

진단 → 추천 → 학습 → 문제 → 답안 → 채점 → 오개념 → Hint/Tutor → Mastery Update → Next Recommendation

### Gate B — 콘텐츠

대표 과정의 주요 Curriculum/Concept/Skill이 출시 기준 이상 채워져 있어야 한다.

### Gate C — 운영

콘텐츠 오류 발견 시 `수정 → QA → 승인 → Publish` 할 수 있어야 한다.

### Gate D — 데이터

학생의 주요 행동이 Event로 남아야 한다. 예시 이벤트 8종:

`learning_started` · `concept_viewed` · `problem_attempted` · `answer_submitted` · `misconception_detected` · `hint_requested` · `mastery_updated` · `recommendation_generated`

### Gate E — EOS Architecture

Math 전용 로직이 EOS Core에 다시 침투하지 않았는지 확인한다. 구조가 계속 `EOS Core → Subject Contract → Math Adapter → WhyMath UI`를 유지해야 한다.

## Phase 3의 진짜 성공 기준

11월 22일에 팀이 다음 세 질문에 **모두 YES**라고 답할 수 있어야 Phase 3 완료다.

1. "내일부터 실제 중·고등학생 100명을 넣어도 개발자가 학생별 데이터를 직접 만지지 않고 학습이 돌아가는가?"
2. "수학 콘텐츠에 오류가 생겼을 때 개발자 배포 없이 콘텐츠 운영자가 수정·검수·배포할 수 있는가?"
3. "Physics를 붙일 때 EOS Core를 다시 뜯지 않고 Physics Adapter를 만들 수 있는 구조인가?"

반대로 Concept Graph, AI Tutor, 문제은행 같은 개별 기능이 아무리 많아도 이 세 질문 중 **하나라도 NO라면 아직 EOS 1과목 완성이 아니다**.

현재 WhyMath 상황에서는 특히 11월을 '기능 170→220개 만드는 달'로 운영하면 안 되고, **'현재 기능들을 하나의 완전한 수학 제품으로 압축하는 달'**로 운영하는 것이 12월 말 출시 가능성을 크게 높일 것이다.
