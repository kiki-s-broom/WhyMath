# Phase 2 (EOS Closed Learning Loop) 집행 지시문 세트

> **무엇인가**: 「Phase 2 — EOS Closed Learning Loop 실행계획」(2026.09.28~10.25) 문서를 **항목별로 순차 집행**하기 위해, Kiki가 AI 세션에 그대로 붙여넣는 지시문 모음이다.
> **왜 필요한가**: 저 문서는 *설계 산문*이라 그대로 주면 AI가 범위를 자의로 넓히거나(§15 금지 기능까지 손댐) 계약보다 알고리즘을 먼저 만든다. 이 문서는 그 산문을 **착수 단위 16개 + 게이트 5개**로 쪼갠 것이다.
> **어떻게 쓰는가**: ①매 세션 첫 메시지에 **마스터 프리앰블**(§1)을 붙인다 → ②그 아래에 이번 회차 지시문(§3의 P-xx) **하나만** 붙인다 → ③그 항목이 끝나면 다음 회차에서 다음 번호로 넘어간다. **한 세션에 두 항목을 묶지 않는다** (묶는 순간 PR이 Vertical Slice가 아니라 기능 묶음이 되고, 원 문서 §20이 경고하는 상태로 돌아간다).

**원 문서 대조 기준**: 원 문서는 작성 시점을 2026-08-27로 적고 있고, 이 지시문 세트는 2026-09-16에 `main` 기준으로 작성됐다. Phase 2 착수일(9/28)까지 남은 기간에 §2(선행 1회)를 끝내 두는 것을 전제로 한다.

---

## 1. 마스터 프리앰블 — 매 세션 첫 메시지 상단에 항상 붙인다

아래 블록은 **모든 회차에서 글자 그대로 동일**하다. 이 블록이 하는 일은 원 문서의 설계 원칙(§2·§13·§15·§20·§22)과 이 저장소의 CLAUDE.md 규칙을 매 세션에 강제 주입하는 것이다.

```text
[Phase 2 마스터 프리앰블 — 이번 세션 전체에 적용]

너는 WhyMath 저장소에서 「Phase 2 — EOS Closed Learning Loop 실행계획」(2026.09.28~10.25)을
항목 단위로 집행하는 엔지니어다. 이번 세션은 아래에 이어지는 항목 **하나만** 다룬다.

[범위 규율]
- 이번 항목 밖의 코드를 "김에 같이" 고치지 않는다. 발견한 별건은 backlog.py add로 등재만 하고 넘어간다.
- 원 문서 §15가 10월 동결로 지정한 것은 production code로 구현하지 않는다:
  신규 EOS 기능번호 추가 / 새 Agent architecture / Digital Twin / 다과목 Adapter 실제 구현 /
  Physics·Chemistry·Biology 확장 / 고급 Knowledge Graph 분석 / 자동 교수법 개선 / 가상 학습 실험 /
  성장 경로 예측 / 자동 콘텐츠 리팩토링 / 연구자 협업 / 고급 A/B framework / 복잡한 ML 추천.
  설계 문서는 남겨도 되지만 코드는 동결이다. 이번 항목이 저것들을 요구하는 것처럼 읽히면 구현 대신 나에게 되묻는다.

[설계 규율 — 원 문서 §2·§10·§13]
- 알고리즘보다 계약이 먼저다. v1 내부 구현은 if/else 규칙이어도 되지만, **호출 계약(시그니처·입출력 스키마)은
  나중에 BKT/DKT/IRT/LLM으로 교체해도 그대로 유지될 형태**여야 한다. 교체 가능성을 주석이 아니라 타입으로 표현한다.
- LLM은 학습 상태를 직접 결정하지 않는다. LLM의 역할은 설명·힌트·후보 분류·제안까지이고,
  LearnerState의 최종 변경은 Assessment Engine / Mastery Engine / Policy Engine이 한다.
- EOS Core 안에 `if subject == "math"`류 분기를 새로 만들지 않는다. 수학 특화 로직은 Math Adapter로 보낸다.
- 표현이 아니라 구조로 저장한다(화면 문자열 금지 — CLAUDE.md L1-L4 규칙).

[착수 규율 — CLAUDE.md]
- 첫 행위는 `python3 scripts/harness/backlog.py start <태스크ID>`다. 대상 파일을 열어보는 것부터가 착수다.
  claim 없이 코드를 읽거나 쓰지 않는다. 해당 태스크가 없으면 backlog.py add로 먼저 등재하고 claim한다.
- 부재를 단정하기 전에 ①역할 기반으로 재검색 ②소비자(호출측) 역추적 ③그래도 0건이면
  "내가 찾은 방법으로는 0건"이라고 범위를 밝혀 적는다. `git log --all --grep=<ID>`로 미머지 브랜치도 본다.
- 판정 근거는 trunk 실측이다. 보고 상단에 `판정 기준: main <커밋해시>`를 박는다.

[검증 규율 — CLAUDE.md]
- 새로 만든 가드·테스트·게이트는 **막으려는 상태를 실제로 주입해 RED를 확인**한 뒤에만 "보호된다"고 말한다.
  정상 입력에서 초록인 것은 증거가 아니다. 주입이 실제 적용됐는지(mutated != original)도 단언한다.
- 판정은 exit code로 한다. `-q`·`| tail`로 출력을 자르고 눈에 보이는 문자열로 통과를 선언하지 않는다.
- 로컬 검증은 CI 잡의 **스텝 목록 전체**에 맞춘다(pytest만이 아니라 mypy --strict·lint-imports·게이트 CLI 포함).
- 백엔드 소스·테스트를 건드렸으면 전체 스위트를 돌린다. 못 돌렸으면 "전체는 확인하지 못했다"를 명시한다.

[산출 규율 — 원 문서 §20 + CLAUDE.md]
- PR은 기능 단위가 아니라 **Vertical Slice 단위**로 연다. 제목은 흐름으로 쓴다.
  좋은 예: "PR — Wrong Answer → LearnerState Update Slice"
  나쁜 예: "PR — Mastery DB 추가"
- 커밋이 있고 (조사전용/미완/CI red/Kiki 보류) 4종 예외가 아니면 PR 생성이 기본값이다.
- 세션 끝에 다음 4줄을 보고한다: ①이번 항목의 완료 판정 결과(충족/미충족, 근거 커밋) ②연 PR 링크
  ③원 문서 대비 미이행으로 남긴 것과 이유 ④다음 항목에 넘기는 선행 조건.

[이번 세션 항목]
(↓ 아래에 P-xx 지시문 하나를 붙인다)
```

---

## 2. 선행 1회 — Phase 2 착수 전에 반드시 끝내는 2건

### P-00a. 문서 → 백로그 변환 (중복 등재 방지 포함)

원 문서 §14(LOOP/SUPPORT/FUTURE 3분류)와 §22(P0~P3 우선순위)를 이 저장소의 대장에 **실제로 집행**시키는 작업이다. 산문에만 있는 우선순위는 `selector.py`가 읽지 않는다.

```text
[항목 P-00a] Phase 2 실행계획을 빌드 하네스 백로그로 변환한다.

1. 첨부한 Phase 2 실행계획 문서를 읽고, §1·§3~§13·§16~§19가 요구하는 산출물을
   착수 단위 태스크로 분해하라. 이 문서의 §3 목록(P-01~P-16)을 기준 분해안으로 삼되, 그대로 믿지 말고 대조하라.
2. **등재 전에 중복을 실측하라.** 이 저장소에는 이미 EOS-01~EOS-77대가 존재하고, 특히
   EOS-65(core-adapter-boundary-map) · EOS-66(subject-adapter-contract) · EOS-67(core-adapter-import-contract)
   · EOS-63(attempt-skill-event-consumption) 등이 Phase 2 항목과 겹칠 수 있다.
   각 분해 단위마다 ①기존 태스크 전수 조회 ②`git log --all --grep` 으로 미머지 구현 여부를 확인하고,
   겹치면 신규 등재 대신 기존 태스크에 `amend`로 acceptance를 덧붙인다.
3. 신규 등재는 반드시 `backlog.py add`로 한다(번호 추론 금지). 선행 관계는 notes 산문이 아니라
   `--depends <full-id>`로 건다. 우선순위는 원 문서 §22를 그대로 옮긴다(P0=1, P1=2, P2=3, P3=보류).
4. 원 문서 §14 분류를 각 태스크 notes에 LOOP / SUPPORT / FUTURE 중 하나로 명시하라.
   FUTURE로 분류된 것은 등재하되 10월 착수 금지임을 notes에 적고 priority를 낮춘다.
5. 산출: ①등재·수정된 태스크 ID 전체 목록(신규/기존 구분) ②원 문서 항목 ↔ 태스크 ID 대조표
   ③겹침으로 등재하지 않은 항목과 그 근거 ④이 변환에서 "원 문서가 요구하지만 등재할 수 없었던 것"과 이유.
6. 대조표는 docs/strategy/ 아래 문서로 남기고 PR을 연다.

주의: backlog CLI 인자에 마크다운 백틱을 직접 넘기지 마라(셸 명령치환으로 내용이 소실된다).
인용 heredoc으로 파일에 쓴 뒤 "$(cat 파일)" 형태로 넘기고, 쓴 뒤 반드시 읽어서 보존을 확인하라.
```

**완료 판정**: 원 문서의 §1~§19 각 항목이 태스크 ID 하나 이상에 대응되고, 그 대응표가 `main`에 있다.

### P-00b. 기존 기능 3분류 감사 (§14)

```text
[항목 P-00b] 기존 WhyMath 기능을 LOOP / SUPPORT / FUTURE로 전수 분류한다.

1. 현재 저장소에서 서빙되는 기능 표면(API 라우트·서비스 모듈·CLI)을 전수 열거하라.
   열거 방법과 그 방법이 놓칠 수 있는 범위를 함께 적어라("내가 찾은 방법으로는 N건").
2. 각각을 원 문서 §14 기준으로 분류하라:
   LOOP = 학습 폐쇄루프에 반드시 연결돼야 하는 것
   SUPPORT = 루프를 지원하지만 없어도 루프가 도는 것
   FUTURE = EOS 확장 기능 — 10월 동결 대상
3. **FUTURE로 분류된 것 중 현재 활발히 개발 중인 것**(열린 PR·in_progress 태스크)을 따로 표로 내라.
   원 문서가 "가장 위험하다"고 지목한 상태가 바로 이것이다.
4. 산출: 분류표 + 동결 권고 목록 + 그 권고를 집행할 방법(태스크 block 처리 여부는 Kiki 판단으로 남긴다).
   코드는 건드리지 않는다. 조사 전용이다.
```

**완료 판정**: 분류표가 `main`에 있고, FUTURE∩진행중 목록이 Kiki에게 보고됐다.

---

## 3. 항목별 순차 지시문 (P-01 ~ P-16)

> 순서는 의존성 순이다. 앞 항목의 완료 판정이 충족되기 전에 다음 항목을 시작하지 않는다.
> 각 블록은 §1 마스터 프리앰블 **아래에** 붙인다.

### Week 1 (9/28~10/4) — Learning Loop Skeleton

가짜 데이터라도 전체 흐름이 한 번 도는 것이 목표다. AI 품질·추천 품질·UI 완성도는 이 주에 신경 쓰지 않는다.

#### P-01. Learning Loop Contract v1 고정 (원 문서 §1·§2)

```text
[항목 P-01] EOS Learning Loop v1 Contract를 코드로 고정한다. 기능 구현이 아니라 계약 고정이 목적이다.

1. 아래 13개 객체만으로 최소 계약을 정의하라. 이 목록에 없는 객체를 추가하지 마라.
   Learner / LearnerState / Curriculum / Objective / Concept / Skill / Content / Problem /
   Attempt / Assessment / Misconception / Mastery / Recommendation / LearningSession
2. 객체 간 관계를 아래대로 고정하라(원 문서 §1의 EOS Kernel):
   Learner has→ LearnerState
   LearnerState: mastery→Concept, mastery→Skill, misconception→Misconception, current_goal→Objective
   Objective requires→ Concept
   Concept: prerequisite→Concept, taught_by→Content, assessed_by→Problem, associated_with→Misconception
   Problem: assesses→Concept, assesses→Skill, triggers→Misconception
   Attempt: made_by→Learner, on→Problem, produces→Assessment
   Assessment updates→ LearnerState
   LearnerState feeds→ Recommendation
3. **기존 엔티티와 대조하라.** 이 저장소에는 이미 상당수 엔티티가 있다(ARCH-37 엔티티 동결 참조).
   신규 생성이 아니라 기존 것에 대한 매핑표를 먼저 만들고, 이름이 다르면 어느 쪽을 정본으로 할지 근거와 함께 제안하라.
   충돌이 있으면 임의 개명하지 말고 나에게 물어라.
4. 계약은 타입(스키마/Protocol/DTO)으로 표현하고, prerequisite 관계는 DAG를 깨지 않는지 검사하는
   reachability 테스트를 동봉하라(순환참조는 CLAUDE.md 붕괴 연쇄 3단계다).
5. 검증: 계약 위반 상태를 실제로 주입해(존재하지 않는 관계 추가, 순환 prerequisite 삽입) RED를 확인하라.
6. 산출: 계약 모듈 + 기존 엔티티 매핑표 + 뮤테이션 검증 결과 + PR.
```

**완료 판정**: 13객체·관계 계약이 `main`에 있고, 위반 주입이 RED를 낸다.

#### P-02. Learning Event 정본화 (원 문서 §4-작업2 · §17)

```text
[항목 P-02] 학생 행동을 Learning Event로 남기는 이벤트 계약을 만든다. 단순 로그가 아니라 학습 이벤트다.

1. 최소 이벤트 스키마를 고정하라. 원 문서 §4가 제시한 형태를 출발점으로 하되 필수/선택을 명시하라:
   event_type, learner_id, session_id, problem_id, concept_id, answer, correct, response_time_ms, timestamp
2. 원 문서 §17이 요구하는 **세션 단위 Event Trace**를 만들어라. 한 학생의 한 세션에 대해
   diagnostic_started → diagnostic_completed → learner_state_created → concept_selected →
   content_viewed → problem_attempted → assessment_failed → misconception_detected →
   mastery_updated(0.54→0.43) → recommendation_generated(PREREQUISITE C087) → ...
   를 시간순으로 재구성해 출력할 수 있어야 한다.
3. mastery_updated 이벤트는 **변경 전후 값을 모두** 남긴다(역추적 KPI 5의 전제다).
4. 이 저장소의 기존 이벤트/관측 배선(Langfuse·ops 이벤트·backlog events.ndjson)과의 관계를 먼저 조사하고,
   새 store를 만들지 말지부터 판단하라. 새로 만들어야 한다면 근거를 적어라.
5. 침묵 실패 금지: 이벤트 기록이 실패하면 예외 타입명을 반드시 로그에 남긴다(값·시크릿은 제외).
6. 검증: 이벤트 기록 경로를 고의로 깨뜨렸을 때 **무증상이 아니라 관측 가능한 실패**가 나는지 주입 확인하라.
7. 산출: 이벤트 계약 + trace 조회 경로 + 주입 검증 결과 + PR.
```

**완료 판정**: 한 세션의 이벤트 나열을 시간순으로 뽑을 수 있고, 기록 실패가 무증상이 아니다.

#### P-03. LearnerState v1 (원 문서 §4-작업1)

```text
[항목 P-03] LearnerState v1을 만든다. digital twin을 만들지 마라 — 아래 필드까지만이다.

1. 최소 형태:
   learner_id / curriculum_id / current_objective_id /
   concept_mastery(개념ID→0~1) / skill_mastery(스킬ID→0~1) /
   misconceptions(id + confidence 목록) / updated_at
2. 이 구조가 나중에 BKT·Knowledge Tracing·성장예측으로 확장될 때 **필드 추가만으로** 되도록 설계하라.
   지금 그 확장을 구현하지는 마라(§15 동결).
3. 읽기·쓰기 경로를 각각 하나로 모아라. LearnerState를 여러 모듈이 제각각 수정하면
   원 문서 KPI 2(State Integrity)를 영원히 측정할 수 없다.
4. 생성 시점을 명확히 하라 — 진단 완료 시 자동 생성이며, 운영자가 DB를 직접 만들 필요가 없어야 한다(Gate 2 조건 3).
5. 검증: LearnerState 없이 루프 진입을 시도했을 때 조용히 기본값으로 진행하지 않고 명시적으로 실패하는지 주입 확인.
6. 산출: 엔티티 + 마이그레이션 + 단일 진입 경로 + PR.
```

**완료 판정**: 진단 완료가 LearnerState를 자동 생성하고, 수정 경로가 하나다.

#### P-04. 학습 상태 머신 (원 문서 §3)

```text
[항목 P-04] 학습을 페이지 이동이 아니라 상태 전이로 구현한다.

1. 상태: NEW → DIAGNOSING → READY → LEARNING → PRACTICING → ASSESSING → REMEDIATING → ADVANCING → LEARNING
2. 전이 규칙(v1):
   정답 + 높은 confidence → ADVANCING
   정답 + 낮은 confidence → PRACTICING
   오답 + misconception 확인 → REMEDIATING
   오답 + prerequisite gap → prerequisite Concept
   반복 실패 → explanation/hint/tutor
3. 구조는 `UI → API → DB`가 아니라 `Event → LearnerState → Policy → Next Action`이어야 한다.
   Policy는 교체 가능한 인터페이스로 분리하라(v1 내부는 if/else로 충분하다).
4. **정의되지 않은 전이는 조용히 통과시키지 말고 거부하라.** 허용 전이표를 데이터로 두고 위반을 예외로 만든다.
5. 검증: 허용되지 않은 전이(예: NEW → ADVANCING)를 주입해 RED를 확인하라.
   또한 각 전이 규칙마다 "이 규칙이 없으면 통과해 버리는 입력"을 픽스처에 넣어라(규칙 하나당 반례 하나).
6. 산출: 상태 머신 + 전이표 + 뮤테이션 전건 결과 + PR.
```

**완료 판정**: 전이가 데이터로 선언돼 있고, 미정의 전이가 RED다.

#### ✅ Week 1 Gate 지시문 (10/4)

```text
[Week 1 Gate 판정] 원 문서 §4 Week 1 Gate를 판정하라. 구현이 아니라 판정이다.

CLI든 개발용 UI든 무방하다. 아래 한 사이클이 **사람의 DB 직접 수정 없이** 도는지 실제로 실행해 보여라:
사용자 생성 → 진단 → 개념 선택 → 문제 풀이 → 오답 → mastery 변경 → 다음 문제 추천

- 통과/미통과를 exit code 또는 명시적 판정 줄로 내라. 인상 판정 금지.
- 판정 기준 커밋 해시를 보고 상단에 박아라(main 기준).
- 미통과면 무엇이 끊겼는지 **끊긴 지점 하나**를 지목하고, 그 지점만 고치는 후속 태스크를 등재하라.
- 이 단계에서 AI 품질·추천 품질·UI는 판정 대상이 아니다. 연결성만 본다.
```

### Week 2 (10/5~10/11) — Assessment + Mastery + Misconception

학생의 행동이 실제로 LearnerState를 바꾸게 만드는 주다.

#### P-05. Assessment Engine v1 (원 문서 §5)

```text
[항목 P-05] Assessment Engine v1을 만든다. 정답/오답에서 끝나면 실패다.

1. 반환 형태(최소):
   correct / score / concept_evidence(개념ID→증거값, 음수 가능) /
   skill_evidence(스킬ID→증거값) / possible_misconceptions(id + confidence 목록)
2. 핵심 요구: Answer → Evidence → LearnerState 로 변환돼야 한다. Evidence 단계를 건너뛰고
   정답 여부로 바로 mastery를 만지는 경로를 만들지 마라.
3. 채점의 수학적 동치 판정은 이 저장소의 기존 SymPy 단일 권위 경로를 경유한다. 새 판정기를 만들지 마라.
4. Assessment는 LearnerState를 **직접 쓰지 않는다** — evidence를 반환할 뿐이고 반영은 P-06이 한다.
   이 경계를 테스트로 동결하라.
5. 검증: Assessment가 LearnerState를 직접 쓰는 코드를 주입했을 때 가드가 RED를 내는지 확인하라.
6. 산출: 엔진 + evidence 스키마 + 경계 가드 + PR(슬라이스 제목: "Attempt → Assessment Evidence Slice").
```

**완료 판정**: 오답 1건이 evidence(개념·스킬·오개념 후보)를 산출하고, LearnerState는 손대지 않는다.

#### P-06. Mastery Engine v1 (원 문서 §6)

```text
[항목 P-06] Mastery Engine v1을 만든다. 매우 단순하게 시작하되 인터페이스는 반드시 분리한다.

1. 인터페이스: update_mastery(learner_state, assessment_evidence) -> mastery_update
   이 시그니처는 나중에 BKT·DKT로 교체될 자리다. 내부 구현만 교체 가능해야 한다.
2. v1 내부 규칙:
   정답 → +0.10 / 오답 → -0.08 / 힌트 사용 → gain × 0.7 / 연속 정답 → confidence 증가
3. 값의 경계(0~1 클램프)·동시 갱신·재시도 시 중복 반영 방지를 명시적으로 처리하라.
   같은 Attempt가 두 번 반영되면 KPI 2(State Integrity <1%)가 즉시 깨진다.
4. mastery 변경은 **항상 이벤트로 남긴다**(변경 전후 값 포함 — P-02와 연결).
5. 이 엔진이 LearnerState를 바꾸는 유일한 경로임을 가드로 동결하라.
6. 검증: ①같은 Attempt 이중 반영 주입 ②클램프 우회 주입 ③우회 경로(다른 모듈이 mastery 직접 수정) 주입
   — 3종 전부 RED를 확인하라.
7. 산출: 엔진 + 단일 경로 가드 + 뮤테이션 결과 + PR.
```

**완료 판정**: mastery 변경 경로가 하나이고, 이중 반영·직접 수정이 RED다.

#### P-07. Misconception 연결 (원 문서 §7)

```text
[항목 P-07] 오답을 오개념으로 연결한다. WhyMath의 차별화 지점이다.

1. 흐름: Problem → Wrong Answer → Error Signature → Misconception Candidate → Confidence → LearnerState
2. 예시 기준: (x+2)^2 에 대해 학생 답이 x²+4 이면 cross_term_omission 계열 오개념에 연결되고,
   {misconception_id, confidence} 형태로 산출돼야 한다.
3. **이 저장소의 기존 오개념 자산과 먼저 대조하라** — 오개념 kebab↔M-id 크로스워크 게이트 계약
   (docs/standards/crosswalk_gate_contract.md)이 이미 존재한다. 새 ID 체계를 만들지 말고 그것을 경유하라.
4. CLAUDE.md 금지: 오개념을 LLM 초기 context에 preload하지 않는다. reactive retrieval만 쓴다.
   이 금지를 위반하는 경로를 만들지 말고, 가드가 있다면 이번 코드가 그 가드를 통과하는지 확인하라.
5. confidence는 누적·감쇠 규칙이 있어야 한다(Persona C 시나리오에서 confidence가 *감소*해야 하므로).
6. 검증: 알려진 오답 패턴 N종을 픽스처로 넣고, 각 패턴이 없으면 잡히지 않는지(=변별력) 주입 확인하라.
7. 산출: 탐지기 + LearnerState 반영 경로 + PR(슬라이스 제목: "Wrong Answer → LearnerState Update Slice").
```

**완료 판정**: 특정 오답 패턴이 오개념 confidence로 LearnerState에 남고, 감쇠 규칙이 있다.

#### ✅ Week 2 Gate 지시문 (10/11)

```text
[Week 2 Gate 판정] 원 문서 §7 Week 2 Gate를 판정하라.

오답 **한 건**이 실제로 아래 전 구간에 영향을 주는지 실행으로 보여라:
Attempt → Assessment → Misconception → Mastery → LearnerState

- 오답 1건 투입 전후의 LearnerState 스냅샷 2개를 비교해 제시하라(값 변화가 증거다).
- 그 변화가 P-02 이벤트에도 남아 있는지 함께 확인하라(두 곳이 어긋나면 KPI 2 위반이다).
- 판정 기준 커밋 해시를 박고, 미통과면 끊긴 지점 하나를 지목하라.
```

### Week 3 (10/12~10/18) — Recommendation + Remediation + AI Tutor

#### P-08. Recommendation Engine v1 — Reason과 함께 (원 문서 §8)

```text
[항목 P-08] 추천 엔진 v1을 만든다. Recommendation이 아니라 Recommendation + Reason을 설계한다.

1. 입력: LearnerState / Current Objective / Concept Graph / Misconception / Recent Attempts
2. 출력(최소):
   action(예: PRACTICE_PREREQUISITE) / target_concept / content_id / problem_ids[] /
   reason { type(예: PREREQUISITE_GAP), confidence }
3. **reason 없는 recommendation을 구조적으로 만들 수 없게 하라.** KPI 3이 "reason 없이 생성된 추천 = 0"이다.
   선택 필드로 두면 반드시 비어서 나온다 — 필수 필드로 두고, 비어 있으면 생성 자체가 실패해야 한다.
4. 인터페이스: recommend(learner_state, learning_context) — 내부는 나중에
   Rule → BKT → IRT → Knowledge Tracing → Graph → LLM → Hybrid 로 교체된다. 계약만 유지되면 된다.
5. Concept Graph 조회는 CLAUDE.md 제약을 지킨다: depth ≤ 2, max_nodes ≤ 12~20, visited set·timeout·token budget guard.
   전체 그래프를 통째로 읽지 마라.
6. 검증: reason을 비우는 주입 / depth 제한을 푸는 주입 — 둘 다 RED를 확인하라.
7. 산출: 엔진 + reason 필수 계약 + PR(슬라이스 제목: "Mastery Threshold → Next Learning Slice").
```

**완료 판정**: 모든 추천에 reason이 붙고, reason 제거 주입이 RED다.

#### P-09. Remediation 정책 (원 문서 §9)

```text
[항목 P-09] 보정 정책을 정책 데이터로 분리해 구현한다. v1 규칙은 단순해도 된다.

1. 기본 정책:
   mastery < 0.4 → prerequisite
   misconception confidence > 0.7 → misconception remediation
   mastery 0.4~0.7 → same concept practice
   mastery > 0.7 → next concept
2. 반복 실패 정책:
   same error >= 2 → corrective explanation
   same error >= 3 → easier problem
   same error >= 4 → prerequisite concept
3. 임계값을 코드에 흩뿌리지 말고 **한 곳의 정책 테이블**로 모아라. 나중에 실측으로 조정될 값이다.
4. "same error"의 정의를 명확히 하라(같은 문제? 같은 오개념? 같은 error signature?).
   정의를 고르고 그 근거를 적어라 — 고르지 않으면 구현마다 달라진다.
5. 검증: 각 임계 경계값(0.4, 0.7, 2·3·4회)마다 **경계 바로 아래/위** 픽스처를 넣어라.
   경계를 한 칸 옮기는 뮤테이션이 RED를 내야 한다(안 나오면 픽스처가 그 경계를 안 밟은 것이다).
6. 산출: 정책 테이블 + 경계 테스트 + PR.
```

**완료 판정**: 정책이 한 곳에 있고, 경계 이동 뮤테이션이 RED다.

#### P-10. AI Tutor v1 (원 문서 §10)

```text
[항목 P-10] AI Tutor v1을 연결한다. **Agent 플랫폼을 만들지 마라** — §15 동결 대상이다.

1. 허용 범위는 정확히 이것뿐이다:
   Student Question → Tutor Context Builder(Curriculum·Concept·Problem·Attempt·Misconception·LearnerState)
   → RAG → LLM → Math Validator → Student Response
2. 절대 규칙: LLM이 학습 상태를 결정하지 않는다. "LLM → Mastery = 0.83" 형태의 경로를 만들지 마라.
   LLM 역할은 Explain / Generate Hint / Classify candidate / Suggest 까지다.
   이 경계를 **가드로 동결**하고, LLM 출력이 mastery에 닿는 경로를 주입해 RED를 확인하라.
3. 모든 LLM 호출은 라우터(l3/router.py) 경유다. 직접 호출 금지. Langfuse 추적 필수.
   클라우드 호출 전 로컬 모델 가능성을 먼저 검토하라.
4. 학생에게 나가는 응답은 PRM 또는 도구 검증(Math Validator)을 통과한 것만이다. 미검증 응답 노출 금지.
5. 막혔을 때 바로 정답을 주지 않는다 — Polya 4단계 우선(CLAUDE.md 교수학 금기).
6. Context는 최소 subgraph만 넣는다(depth ≤ 2, max_nodes ≤ 12~20, max_tokens ≤ 3000).
   오개념은 preload하지 말고 reactive로 가져온다.
7. 검증: ①LLM→mastery 경로 주입 ②라우터 우회 직접 호출 주입 ③미검증 응답 노출 주입 — 3종 RED 확인.
8. 산출: Tutor v1 + 경계 가드 + PR.
```

**완료 판정**: 튜터가 답하고, LLM이 상태를 못 바꾸는 것이 주입으로 증명됐다.

#### ✅ Week 3 Gate 지시문 (10/18)

```text
[Week 3 Gate 판정] 원 문서 §10 Week 3 Gate(= Remediation Loop)를 판정하라.

학생이 문제를 틀렸을 때 아래가 **사람 개입 없이 자동으로** 이어지는지 실행으로 보여라:
오답 → Misconception → 교정 콘텐츠 → AI Hint → 새 문제 → 재시도

- 각 화살표마다 "무엇이 그 다음을 촉발했는가"를 이벤트 trace로 제시하라(P-02 산출물 활용).
- 중간에 사람이 값을 넣어야 넘어가는 구간이 하나라도 있으면 미통과다.
- 판정 기준 커밋 해시를 박아라.
```

### Week 4 (10/19~10/25) — Vertical Slice 완성

**이 주에는 새 엔진을 추가하지 않는다.** 안정화만 한다.

#### P-11. 필수 API 표면 정리 (원 문서 §12)

```text
[항목 P-11] Phase 2 필수 API 표면을 정리한다. API 개수가 목적이 아니라 내부 흐름 연결이 목적이다.

1. 아래 12개에 대해 "있음 / 다른 이름으로 있음 / 없음"을 실측 표로 내라.
   POST /diagnostics · GET /learner-state · GET /learning/next · GET /concepts/{id} ·
   GET /contents/{id} · GET /problems/{id} · POST /attempts · POST /assessments ·
   GET /recommendations/next · POST /tutor/query · GET /sessions/{id} · GET /learning/result
2. 이름이 다르면 **개명하지 말고 매핑표**로 처리하라(기존 클라이언트를 깨지 않는다).
   개명이 필요하다고 판단되면 근거를 적고 나에게 물어라.
3. 핵심 판정: Attempt → Event → Assessment → LearnerState → Recommendation 이 내부에서 실제로 이어지는가.
   각 API가 아니라 **이 연결**을 통합 테스트로 동결하라.
4. 빠진 API는 최소 형태로만 채운다. 응답 스키마를 풍부하게 만들려 하지 마라.
5. 산출: 실측 표 + 연결 통합 테스트 + PR.
```

**완료 판정**: 12개 표면의 실측 표가 있고, 5단계 내부 연결이 테스트로 동결됐다.

#### P-12. EOS Core / Subject Contract / Math Adapter 경계 기계 집행 (원 문서 §13)

```text
[항목 P-12] EOS 내부 경계를 코드에서 기계로 집행한다. 문서 선언이 아니라 CI 차단이다.

1. 목표 경계:
   WhyMath(Product/UI) → Math Adapter → Subject Contract(Concept·Skill·Problem·Assessment·Misconception·Pedagogy)
   → EOS Core(Learner·LearnerState·LearningSession·Mastery·Recommendation·Event·Version·Identity)
2. 위험 신호를 기계로 잡아라: EOS Core 내부의 `if subject == "math"`류 분기, Core → Adapter 역방향 import.
   문자열 금지 목록이 아니라 **AST 기반 전수 검사**로 만들어라(표기 변형에서 뚫린다).
3. 기존 자산과 먼저 대조하라 — EOS-65(boundary-map)·EOS-66(subject-adapter-contract)·
   EOS-67(core-adapter-import-contract), 그리고 lint-imports 배선이 이미 있을 수 있다.
   있으면 새로 만들지 말고 확장하라.
4. **스캔 0건은 실패로 처리하라** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.
5. 검증: 위반 코드(Core 안에 math 분기, 역방향 import)를 실제로 주입해 CI가 RED를 내는지 확인하라.
   그리고 그 가드가 **이번 CI 실행에서 skipped가 아니라 실제로 실행됐는지** 확인하라.
6. 산출: 가드 + CI 배선 + 주입 결과 + 현재 위반 목록(있으면 정오 판정과 함께) + PR.
```

**완료 판정**: 경계 위반 주입이 CI에서 RED이고, 그 스텝이 실제 실행됐음이 확인됐다.

#### P-13. SCENARIO-001~010 + CI 배선 (원 문서 §16)

```text
[항목 P-13] Unit Test가 아니라 Scenario Test를 만든다. Phase 2의 실질 회귀 방어선이다.

1. 아래 10개를 각각 하나의 시나리오 테스트로 만들어라:
   001 신규 학생 정상 학습 / 002 낮은 진단점수 / 003 선수개념 결손 / 004 동일 오개념 반복 /
   005 힌트 후 정답 / 006 AI Tutor 질문 / 007 mastery threshold 통과 / 008 다음 concept 이동 /
   009 세션 종료 후 재접속 / 010 학습 상태 복구
2. 각 시나리오는 **상태 변화**를 단언하라(화면 문자열이 아니라 LearnerState·이벤트).
3. CI에서 항상 돌게 배선하라. 배선했다고 선언하기 전에 **이번 CI 실행에서 실제로 실행됐는지**
   확인하라("저장소에 존재함"과 "돌아감"은 다르다 — 이 저장소에서 반복 발생한 사고 유형이다).
4. 실행 시간이 길면 nightly와 PR용을 나누되, 나눈 기준과 PR용에 남긴 것을 명시하라.
5. 검증: 각 시나리오마다 "이 시나리오가 없으면 통과해 버리는 회귀"를 하나씩 주입해 RED를 확인하라.
   전건 RED가 나와도 그것은 가드의 세기일 뿐 커버리지의 증거가 아니다 — 안 본 분기를 따로 적어라.
6. 산출: 시나리오 10종 + CI 실행 증거(잡 이름·스텝 결과) + PR.
```

**완료 판정**: 10종이 CI에서 실행되고(skipped 아님), 각각의 회귀 주입이 RED다.

#### P-14. KPI 5종 계측 (원 문서 §19)

```text
[항목 P-14] Phase 2 KPI를 기능 개수가 아니라 아래 5종으로 계측한다. 측정 없는 KPI는 KPI가 아니다.

KPI 1 Loop Completion Rate — 시작한 학습 세션 중 Recommendation까지 도달한 비율 (Alpha 목표 > 95%)
KPI 2 State Integrity — Attempt·Assessment·Mastery·Recommendation 간 불일치 < 1%
KPI 3 Explainability — reason 없이 생성된 recommendation = 0
KPI 4 Manual Intervention — 정상 시나리오에서 운영자 DB 개입 = 0
KPI 5 Traceability — Recommendation → LearnerState → Assessment → Attempt → Problem 역추적 100%

1. 각 KPI에 대해 ①분자·분모의 정의 ②데이터 출처 ③산출 명령(CLI) 을 명시하라.
2. 판정은 CLI exit code로 낸다. 점추정·인상 판정 금지.
3. **인프로세스 이중 회계**로 만들어라 — 외부 관측 SaaS가 죽었을 때 "측정 실패"가 보여야지
   "0건 통과"로 위장되면 안 된다(CLAUDE.md 금기).
4. 실패해도 증거가 남게 설계하라: 단계마다 즉시 flush, 실패 원인(예외 타입·응답 본문·stderr) 기록,
   조회에 시간 필터를 걸어 이전 실행 증거를 이번 것으로 오독하지 않게 하라.
5. 검증: 각 KPI에 대해 **일부러 위반 상태를 주입**해 그 KPI가 실제로 떨어지는지 확인하라.
   정상 상태에서만 초록인 계측기는 계측기가 아니다.
6. 산출: KPI CLI + 현재 실측값 + 주입 검증 결과 + PR.
```

**완료 판정**: 5종이 CLI로 산출되고, 각각 위반 주입에 반응한다.

#### P-15. 페르소나 3종 안정화 (원 문서 §11)

```text
[항목 P-15] 새 엔진을 추가하지 마라. 대표 사용자 3명으로 전체 흐름을 반복 테스트해 안정화만 한다.

Persona A 정상 학습자: 진단 → 학습 → 문제 → 대부분 정답 → mastery 상승 → 다음 concept
Persona B 선수학습 결손: 진단 → 문제 → 반복 오답 → prerequisite gap → 하위 concept → 보정 → 원래 concept 복귀
Persona C 특정 오개념: 진단 → 문제 → 특정 오답 패턴 → misconception detection → corrective explanation
             → targeted problem → misconception confidence **감소**

1. 세 경로를 각각 끝까지 실행하고, 각 단계의 LearnerState 변화를 표로 제시하라.
2. Persona C는 confidence가 실제로 *내려가는지*가 판정 포인트다(올라가기만 하면 보정이 작동 안 한 것이다).
3. Persona B는 "원래 concept 복귀"까지 가야 통과다. 하위 concept에서 멈추면 미통과다.
4. 이번 주에 발견한 결함은 **고치되 범위를 넓히지 마라**. 새 기능이 필요하다고 판단되면 태스크로 등재만 하고 보고하라.
5. 산출: 3경로 실행 기록 + 발견 결함 목록(고친 것/등재한 것 구분) + PR.
```

**완료 판정**: 3경로가 끝까지 돌고, Persona C의 confidence 감소가 수치로 보인다.

#### P-16. ✅ Gate 2 최종 판정 (10/25 · 원 문서 §18)

```text
[Gate 2 판정] 2026-10-25 Gate 2를 판정하라. "Alpha 완성" 같은 모호한 판정 금지.

아래 10개 조건을 **각각 실행 증거와 함께** 충족/미충족으로 판정하라:
 1 신규 학생 생성 가능      2 진단 완료 가능        3 LearnerState 자동 생성
 4 Concept 자동 선택        5 Content → Problem 연결  6 Attempt → Assessment 동작
 7 Misconception 기록       8 Mastery 자동 갱신      9 다음 학습 자동 추천
10 전체 과정 반복 가능

추가 최종 조건(가장 중요):
  운영자가 DB를 직접 수정하지 않고 **3회 이상 연속 Learning Loop**가 가능해야 한다.
  Loop 1: 진단 → 문제 → 오답 → 보정
  Loop 2: 보정 → 문제 → 정답 → mastery 상승
  Loop 3: 다음 concept → 문제 → 평가 → 추천

판정 규칙:
- 실제 학생 계정을 만들어 실행한 **이벤트 trace 전문**을 증거로 제시하라(P-02 산출물).
- 중간에 한 번이라도 사람이 DB·관리자 화면으로 값을 넣었다면 그 조건은 미충족이다.
- KPI 5종(P-14) 실측값을 함께 제시하라.
- 판정 기준 커밋 해시를 보고 상단에 박아라(main 기준). 미머지 브랜치를 근거로 조건을 닫지 마라.
- 미충족 조건마다 ①끊긴 지점 ②남은 작업량 추정 ③11월 일정에 미치는 영향을 적어라.
- 최종 한 줄: PASS / FAIL. 조건부 PASS는 없다.
```

---

## 4. 상시 지시문 (필요할 때 단독으로 붙인다)

### S-01. 범위 이탈 차단 (§15 위반이 의심될 때)

```text
[상시 점검] 지금 진행 중인 작업이 원 문서 §15 10월 동결 목록에 닿았는지 판정하라.
동결 목록: 신규 EOS 기능번호 / 새 Agent architecture / Digital Twin / 다과목 Adapter 실제 구현 /
Physics·Chemistry·Biology 확장 / 고급 Knowledge Graph 분석 / 자동 교수법 개선 / 가상 학습 실험 /
성장 경로 예측 / 자동 콘텐츠 리팩토링 / 연구자 협업 / 고급 A/B framework / 복잡한 ML 추천.
닿았으면 즉시 멈추고, 이미 쓴 코드 중 동결 대상 부분을 분리해 태스크로 등재한 뒤 보고하라.
설계 문서는 남겨도 된다.
```

### S-02. PR 형태 교정 (§20)

```text
[상시 점검] 지금 열려 있는 이번 작업 PR이 기능 단위인지 Vertical Slice 단위인지 판정하라.
기능 단위(예: "Mastery DB 추가", "Recommendation DTO 추가")면 흐름 단위로 재구성하라
(예: "Wrong Answer → LearnerState Update Slice", "Mastery Threshold → Next Learning Slice").
재구성이 불가능하면 왜 불가능한지 적고, 그 PR이 단독으로 루프를 깨지 않는지 확인하라.
```

### S-03. 주간 마감 보고

```text
[주간 마감] 이번 주 Phase 2 진척을 아래 형식으로 보고하라. 판정 기준: main <해시>
1) 이번 주 완료 항목(P-xx)과 근거 PR
2) 해당 주 Gate 판정 결과(PASS/FAIL)와 근거
3) KPI 5종 현재 실측값(측정 불가면 "측정 실패"로 명시 — 0으로 적지 마라)
4) 원 문서 대비 미이행으로 남긴 것과 이유
5) 다음 주 첫 항목과 그 선행 조건 충족 여부
```

---

## 5. 진행 체크리스트

| # | 항목 | 원 문서 | 주차 | 완료 판정 |
|---|---|---|---|---|
| P-00a | 문서 → 백로그 변환 | §14·§22 | 착수 전 | 항목↔태스크 대조표가 main에 |
| P-00b | 기존 기능 3분류 감사 | §14 | 착수 전 | 분류표 + FUTURE∩진행중 보고 |
| P-01 | Learning Loop Contract v1 | §1·§2 | W1 | 위반 주입 RED |
| P-02 | Learning Event 정본화 | §4·§17 | W1 | 세션 trace 조회 가능 |
| P-03 | LearnerState v1 | §4 | W1 | 진단 완료 시 자동 생성 |
| P-04 | 학습 상태 머신 | §3 | W1 | 미정의 전이 RED |
| — | **Week 1 Gate** | §4 | 10/4 | 1사이클 무개입 완주 |
| P-05 | Assessment Engine v1 | §5 | W2 | evidence 산출·상태 미변경 |
| P-06 | Mastery Engine v1 | §6 | W2 | 단일 경로·이중반영 RED |
| P-07 | Misconception 연결 | §7 | W2 | 오답 패턴 → confidence |
| — | **Week 2 Gate** | §7 | 10/11 | 오답 1건이 전 구간 전파 |
| P-08 | Recommendation + Reason | §8 | W3 | reason 제거 주입 RED |
| P-09 | Remediation 정책 | §9 | W3 | 경계 이동 뮤테이션 RED |
| P-10 | AI Tutor v1 | §10 | W3 | LLM→mastery 주입 RED |
| — | **Week 3 Gate** | §10 | 10/18 | Remediation Loop 자동 연결 |
| P-11 | 필수 API 표면 | §12 | W4 | 5단계 연결 테스트 동결 |
| P-12 | Core/Adapter 경계 집행 | §13 | W4 | 위반 주입 CI RED(실행됨) |
| P-13 | SCENARIO-001~010 | §16 | W4 | CI 실행(skipped 아님) |
| P-14 | KPI 5종 계측 | §19 | W4 | 위반 주입에 반응 |
| P-15 | 페르소나 3종 안정화 | §11 | W4 | 3경로 완주·C confidence 감소 |
| P-16 | **Gate 2 최종 판정** | §18 | 10/25 | 10조건 + 연속 3루프 |

---

## 6. 이 지시문 세트를 쓸 때의 주의 3가지

1. **한 세션 = 한 항목.** 묶으면 PR이 기능 묶음이 되고, 원 문서 §20이 경고한 "Closed Loop가 다시 분해되는" 상태로 돌아간다.
2. **"~해줘"로 바꾸지 마라.** 각 지시문의 마지막 검증 항목(주입·RED 확인)이 이 세트의 핵심이다. 그것을 빼면 "만들었다"는 보고만 남고 "작동한다"는 증거가 남지 않는다.
3. **Gate 판정은 구현 세션과 분리하라.** 만든 사람이 같은 세션에서 판정하면 통과 쪽으로 기운다. Gate 지시문은 새 세션에서 단독으로 붙인다.
