# Canonical Entity Model v1 — 핵심 엔티티 19종 동결

> **한 줄**: 9월 스키마에 들어갈 **핵심 엔티티를 19종으로 고정**하고, 현행 78테이블을 그 19종
> 또는 "핵심 외"에 **전수 귀속**시킨다. 검토해 온 나머지 노드는 9월에 넣지 않는다.

- **결정일**: 2026-09-05 (Kiki 지시 — "이날은 코드 개발을 멈추고 핵심 엔티티를 고정한다")
- **태스크**: `ARCH-37-canonical-entity-model-freeze`
- **실측 기준**: `Base.metadata` 전수 스캔 **78테이블** (2026-09-05)
- **시점 근거**: W2(9/7~9/13) = "되돌릴 수 없는 스키마 확정" 주간
  (`docs/strategy/eos_transition_declaration_2026-08-30.md` §5). 이 문서는 W2 **직전**에
  대상 목록을 확정해 W2가 무엇을 확정하는지 흔들리지 않게 한다.

※ [갱신 2026-09-11] `SEC-27`이 `job_ownership`(비동기 작업 소유권) 테이블을 추가해 78→79
테이블로 늘었다 — 위 "전수 귀속" 원칙 자체는 그대로다(핵심-외 §2-B에 편입, 신규 좌석 아님).
§2 표·합계·아래 ① 행을 79로 갱신했다.

※ [갱신 2026-09-14] `EOS-49`가 `concept_version` 테이블을 Concept 좌석의 4번째 테이블로
추가해 79→80 테이블로 늘었다(§3-D "판정 2026-09-06"이 이미 이 배정을 예고했다 — 새 엔티티가
아니라 기존 Concept 좌석 편입) — §2 표·합계·아래 ① 행을 80으로 갱신했다.

※ [상호참조 2026-09-16] `EOS-100`이 `docs/architecture/learning_loop_contract_v1.md`에
**루프 호출 어휘**(14객체·18관계)를 고정했다. 그 문서는 이 정본의 **좌석 축을 건드리지 않는다** —
신규 테이블·신규 엔티티 0건이고, 좌석이 없는 루프 객체는 `no_seat`으로 적는다. 여기 §1의 19종과
저기 §3의 귀속표는 1:1로 대조되며(그쪽 검사 ⑤가 이 문서 §2-A 표를 파싱한다), 이 문서가 엔티티를
추가·개명하면 그 검사가 자동으로 따라온다.

---

## ⚖️ 집행 고지 (정본화 ≠ 집행)

CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"에 따라 **이 문서가 강제하는 것과 강제하지
않는 것을 먼저** 적는다.

### 기계가 강제하는 것 — `tests/backend/db/test_canonical_entity_model_freeze.py`

| # | 검사 | 깨지면 |
|---|---|---|
| ① | 80테이블 **전수 귀속** — 좌석 또는 핵심-외 중 정확히 한쪽 | 신규 테이블이 생기면 **RED** |
| ② | 19종 **좌석 실재** + 엔티티 개수 19 고정 | 좌석 삭제·개명, 20번째 엔티티 추가 시 **RED** |
| ③ | **좌석 부재 4종** — 예약 이름 금지 + **좌석 tuple이 비어 있음** (§3) | `hints`는 물론 `hint_content` 같은 우회 이름으로 좌석을 등재해도 **RED** |
| ④ | **문서 ↔ 상수 배정 대조** — §2-A·§2-B 표를 파싱해 1:1 확인 | 배정을 옮기거나(예: `skill_node`를 Skill→Content) 표에서 행이 빠지면 **RED** |

④는 "이름이 문서 어딘가에 있다"가 아니라 **어느 엔티티에 배정됐는지**를 본다. 토큰 존재만 보는
검사는 배정을 바꿔도 같은 초록을 내므로 정본과 집행이 조용히 어긋난다(PR #984 Codex P2 지적 —
실측으로 재현 확인 후 강화).

### 기계가 강제하지 **않는** 것 (있는 척 금지)

- **배정의 *옳음*.** 기계는 문서와 상수가 **서로 일치하는지**만 본다 — 둘이 사이좋게 틀려
  있으면 통과한다. "이 테이블이 *올바른* 엔티티에 갔는가"는 §1 산문이 근거인 사람 판단이다.
- **컬럼 수준 스키마**. 어떤 필드를 갖는지는 각 모델의 기존 ORM 테스트 소관이다.
- **코드 밖 저작 스키마와의 정합**. `schemas/v1.1/*.yaml`·`schemas/v1.0/`과의 대조는
  기계 집행이 **없다** — 알려진 드리프트는 §7에 그대로 적는다.
- **런타임 사용 여부**. 좌석이 있다고 writer가 있다는 뜻이 아니다(§7-C).

---

## §1. 핵심 엔티티 19종 — 위반 판정 가능한 정의

각 항목은 **"이것이다 / 이것이 아니다"** 쌍으로 적는다. "대체로 이런 느낌"은 판정 근거가 되지
못하므로, 새 코드가 어느 엔티티인지 다툴 때 아래의 *아니다* 절이 결론을 낸다.

### 교육과정 축

1. **Subject** — 학습 내용의 최상위 분류 축.
   - *이다*: 한 문항·개념이 어느 과목에 속하는지 말하는 **분류 값**.
   - *아니다*: 자체 생명주기를 갖는 레코드가 아니다. → **좌석 부재**(§3-A), 열(column) 축으로 유지.

2. **Curriculum** — 한 국가·시기의 교육과정 **판(version)** 그 자체.
   - *이다*: "2022 개정 교육과정 수학과"처럼 **개정 단위로 통째 교체되는 것**.
   - *아니다*: 그 안의 단원·성취기준 개별 항목이 아니다(그것은 CurriculumNode).

3. **CurriculumNode** — 교육과정 안의 **한 항목**(영역·단원·성취기준·성취수준·교과서 단원).
   - *이다*: Curriculum 판에 종속돼 **판이 바뀌면 함께 교체되는** 구조 항목.
   - *아니다*: 개념 그 자체가 아니다. 플레이북 "Curriculum은 Overlay" 원칙 — 개념은 영속하고
     교육과정 매핑만 교체된다. 이 축에 개념을 넣으면 개정 때 개념이 함께 죽는다.

4. **LearningObjective** — 소단원의 **한 학습목표**(주 지식유형으로 교수법 팩에 바인딩).
   - *이다*: 학생이 무엇을 할 수 있게 되는지의 진술 + 그 진술이 붙는 소단원 컨테이너.
   - *아니다*: 성취기준 원문이 아니다(그것은 CurriculumNode·NCIC 공공누리). 교과서 학습목표
     **본문**은 저작권 게이트 대상이라 여기 복제 금지.

### 지식 축

5. **Concept** — 교육적으로 압축된 인지 그래프의 **노드**(순수 개념).
   - *이다*: `math.<area>.<slug>` canonical ID로 영속하는 개념 원자.
   - *아니다*: renderer·curriculum·prompt·misconception·UI·embedding을 **품지 않는다**
     (Concept Purity — 8대 구조 원칙 ①). 그 6종은 전부 핵심-외 테이블로 외부화돼 있다(§2-B).
   - ⚠ **혼재 3좌석**: `concept`(관계형) · `concept_node`(그래프 프로젝션) · `atom_node`(원자 백본).
     판정 불가라 **그대로 적는다** — 통합 여부는 §5 후속 판단.
   - **버전 축**: `concept_version`(4번째 좌석·`EOS-49`·게이트 `G-eos49-content-version-seat`
     D안 판정 — 새 엔티티가 아니라 이 좌석의 버전 테이블. §3-D 참조).

6. **Skill** — 개념을 **실행**하는 능력 단위(`skill.<slug>`).
   - *이다*: 숙련도 추적의 단위이자 증거가 귀속되는 대상.
   - *아니다*: 개념이 아니다. Concept이 "무엇을 아는가"라면 Skill은 "무엇을 할 수 있는가".

7. **Misconception** — 반복 관측되는 **오개념 카탈로그 항목**(`M0425` + kebab crosswalk).
   - *이다*: 학생 개인과 무관하게 존재하는 **유형 정의**.
   - *아니다*: 특정 학생의 오개념 **추정**이 아니다(그것은 §2-C 판정 보류).
   - 계약: 초기 context에 preload 금지 — reactive retrieval만(붕괴 방어).

### 콘텐츠 축

8. **Problem** — 학생에게 제시되는 **한 문항**과 그 정답 단계.
   - *이다*: 자체 코퍼스의 문항. 구조(스키마) + 렌더러-중립 LaTeX 본문.
   - *아니다*: 검정교과서·평가원 기출 **본문 복제가 아니다** — 구조 메타데이터만 인용하고
     본문은 자체 동등문제로 대체한다(절대 금기).

9. **Solution** — 한 문항에 대한 **풀이 경로**와 그 검증 산출.
   - *이다*: 접근법 1개 = 경로 1개(한 문항에 다중 경로 허용). 다중 풀이의 본질적 동치성이 이 축.
   - *아니다*: 학생이 실제로 쓴 풀이가 아니다(그것은 LearningEvent의 `student_solution_step`).
     **정본 풀이 ↔ 학생 풀이**를 섞으면 채점 대상과 정답지가 같은 테이블에 산다.

10. **Hint** — 등급화된 **힌트**(1=가장 은근 ~ 3=거의 정답).
    - *이다*: "바로 정답 제공 금지 · 가능한 가장 빠른 단계에서 멈춤"의 데이터 표현.
    - *아니다*: 힌트를 **썼다는 기록**이 아니다(그것은 LearningEvent의 `hint_usage`).
    - → **좌석 부재**(§3-B). 설계 정본은 있고 저장 좌석이 없다.

11. **Content** — 개념·소단원에 붙는 **설명 자산**(은유·오개념 설명·정식정의·허용표현·암기카드).
    - *이다*: 학생에게 보여줄 수 있는 서술형 자산과 그 슬롯.
    - *아니다*: 문항이 아니다(Problem). 개념 노드 자체도 아니다(Concept Purity).

### 학습자 축

12. **Learner** — 학생 **본인**(계정·프로필).
    - *이다*: 신원과 프로필. **미성년 민감정보**로 분류돼 암호화 저장 대상.
    - *아니다*: 학습 상태가 아니다(LearnerState). 인증 자격도 아니다(핵심-외).

13. **LearnerState** — 한 시점의 학습 **상태 스냅샷**.
    - *이다*: "지금 이 학생은 어떤 상태인가"의 시점 사진(개념·패턴 숙련 맵, 평균 풀이시간 등).
    - *아니다*: 숙련도의 **시계열 이력**이 아니다(MasteryState). 프로필 변경 이력도 아니다.

14. **MasteryState** — Skill·Concept별 **숙련도**와 그 변화 이력.
    - *이다*: 누적 증거를 반영한 현재 숙련 + append-only 이력.
    - *아니다*: 개별 증거 하나가 아니다(LearningEvent). 시험 결과도 아니다(Assessment).

### 평가 축

15. **Assessment** — 진단 평가 **세션**(초기 진단 + 주기적 재진단).
    - *이다*: "언제 무엇을 진단했는가"의 컨테이너.
    - *아니다*: 매 문항 채점이 아니다(LearningEvent).

16. **AssessmentResult** — 그 진단이 **산출한 판정**(단원별 진단·약점·강점·권장 경로).
    - *이다*: Assessment 1회의 결론.
    - → **좌석 부재**(§3-C) — 현재 `assessment` 행 안의 JSONB 5필드로 **혼입**돼 있고,
      `ARCH-38`이 **혼입 유지로 판정**했다(2026-09-06·main `794c0ea8` 기준). 미결이 아니라
      **판정된 상태**다 — 근거·비용·재판정 트리거 3종은 §3-C.

### 행위·전략 축

17. **LearningEvent** — 학생이 남긴 **원시 학습 행위 기록**.
    - *이다*: 시도·제출·힌트 사용·대화 턴·풀이 단계·막힘 등 **일어난 일 그대로**.
    - *아니다*: 그 기록에서 **파생된 집계·판정이 아니다**. 롤업(일일 지표 등)은 핵심-외로 뺐다.
    - ⚠ 11좌석으로 가장 넓다. 4층 경계(Attempt·Evaluation·Assessment·Mastery)의 정밀 분해는
      **`EOS-79`가 소유**한다 — 이 문서는 그 태스크를 대체하지 않는다(§6).

18. **PedagogyStrategy** — 교수 **전략**과 그 팩(Polya·소크라테스 등 인지행동 기준 전략).
    - *이다*: "어떻게 가르칠 것인가"의 재사용 단위.
    - *아니다*: 개념도 콘텐츠도 아니다. 노드에 prompt를 넣지 않는다는 원칙의 반대편 좌석.

19. **ContentVersion** — 콘텐츠·엔티티의 **판 관리** 공통 축.
    - *이다*: "이 학생이 푼 그 문항의 그 시점 판은 무엇이었나"를 복원하는 축.
    - *아니다*: 엔티티마다 각자 만드는 버전 필드가 아니다 — **공통 거버넌스**가 원칙.
    - → **좌석 부재**(§3-D). 현재 각 테이블에 버전 컬럼이 **분산**돼 있다.

---

## §2. 현행 79테이블 전수 귀속표

> 이 표는 `tests/backend/db/test_canonical_entity_model_freeze.py`의 상수와 **1:1**이며,
> 검사 ①·④가 둘의 어긋남을 RED로 낸다.

### §2-A. 좌석 배정 — 42테이블

| # | 핵심 엔티티 | 좌석 테이블 | 좌석 수 |
|---|---|---|---|
| 1 | **Subject** | — **좌석 부재**(§3) | 0 |
| 2 | **Curriculum** | `curriculum_framework` · `curriculum_version` | 2 |
| 3 | **CurriculumNode** | `curriculum_entry` · `achievement_standard` · `achievement_level_unit` · `textbook_unit` · `textbook_mapping` | 5 |
| 4 | **LearningObjective** | `learning_objective` · `unit_spec` | 2 |
| 5 | **Concept** | `concept` · `concept_node` · `atom_node` · `concept_version` | 4 |
| 6 | **Skill** | `skill_node` | 1 |
| 7 | **Misconception** | `misconception_catalog` | 1 |
| 8 | **Problem** | `problem` · `problem_step` | 2 |
| 9 | **Solution** | `solution_paths` · `solution_nodes` · `verified_solutions` · `verified_lemmas` | 4 |
| 10 | **Hint** | — **좌석 부재**(§3) | 0 |
| 11 | **Content** | `concept_content` · `pedagogy_content_slot` | 2 |
| 12 | **Learner** | `user_profile` | 1 |
| 13 | **LearnerState** | `user_state_snapshot` | 1 |
| 14 | **MasteryState** | `concept_mastery_history` · `skill_mastery_history` · `ability_snapshot` | 3 |
| 15 | **Assessment** | `assessment` | 1 |
| 16 | **AssessmentResult** | — **좌석 부재**(§3) | 0 |
| 17 | **LearningEvent** | `attempt_event` · `evidence_event` · `review_timer_event` · `hint_usage` · `answer_submission` · `problem_attempt` · `learning_session` · `student_solution_step` · `dead_end_log` · `dialogue` · `dialogue_turn` | 11 |
| 18 | **PedagogyStrategy** | `strategy_node` · `pedagogy_pack` | 2 |
| 19 | **ContentVersion** | — **좌석 부재**(§3) | 0 |

**좌석 합계 = 42**

### §2-B. 핵심 외 — 37테이블

핵심 19종에 **배정하지 않는다**. 사유를 값으로 강제해(테스트 상수) "일단 여기 던져 넣기"를
비싸게 만든다. 이 목록 자체가 **8대 구조 원칙의 외부화 증거**다 — 임베딩·렌더러·관계·오개념이
개념 노드에서 이미 분리돼 있다.

| 테이블 | 배정 제외 사유 |
|---|---|
| `atom_embedding` | 임베딩(벡터) — 개념 노드에 혼입 금지 |
| `atom_probe` | 부속 노드(원자 프로브) — 원자 백본 진단 보조 |
| `concept_edge` | 관계(엣지) — 개념↔개념 |
| `concept_embedding` | 임베딩(벡터) — 개념 노드에 혼입 금지 |
| `concept_fusion` | 관계(엣지) — 개념 융합 |
| `concept_standard_link` | 관계(엣지) — 개념↔성취기준 |
| `concept_visual_style` | 렌더러(시각 스타일) — 개념 노드에 혼입 금지 |
| `concept_visualization` | 렌더러(시각화 인텐트) — 개념 노드에 혼입 금지 |
| `content_provenance` | 권리·출처(생성 계보) |
| `content_rights` | 권리·출처(저작권 레일) |
| `content_source` | 권리·출처(저작권 레일) |
| `daily_learning_metrics` | 집계(롤업) — LearningEvent 파생물 |
| `defect_report` | 운영(결함 신고) |
| `deletion_audit` | 감사(파기 이력) |
| `derivation_edge` | 관계(엣지) — 콘텐츠 파생 계보(권리 축) |
| `device_credential` | 인증(기기 자격) |
| `evidence_links` | 관계(엣지) — 증거↔대상 |
| `formula_node` | 부속 노드(공식 택소노미) — Concept 승격은 정본 갱신 경유 |
| `generation_log` | 권리·출처(LLM 생성 로그) |
| `job_ownership` | 인증(작업 소유권) — 학습 도메인 엔티티 아님 |
| `misconception_crosslink` | 관계(엣지) — 오개념 kebab↔M-id 크로스워크 |
| `misconception_embedding` | 임베딩(벡터) — 오개념 노드에 혼입 금지 |
| `misconception_hypothesis` | 판정 보류 — L2 오개념 추론 산출물. 카탈로그도 원시 이벤트도 아니다 |
| `misconception_relation` | 관계(엣지) — 오개념↔오개념 |
| `parental_consent` | 법령(법정대리인 동의) — 기계 대체 금지 축 |
| `privacy_audit` | 감사(개인정보 접근) |
| `problem_concept` | 관계(엣지) — 문항↔개념 |
| `problem_embedding` | 임베딩(벡터) — 문항에 혼입 금지 |
| `problem_relation` | 관계(엣지) — 문항↔문항 |
| `problem_solve_time_distribution` | 집계(롤업) — LearningEvent 파생물 |
| `problem_type_node` | 부속 노드(문항유형 택소노미) — Problem 승격은 정본 갱신 경유 |
| `refresh_token_session` | 인증(세션 토큰) |
| `rights_entity` | 권리·출처(저작권 레일) |
| `rights_holder` | 권리·출처(저작권 레일) |
| `source_entity` | 권리·출처(저작권 레일) |
| `user_behavior_metrics` | 집계(롤업) — LearningEvent 파생물 |
| `user_persona_history` | 사용자 이력(페르소나 변경) — LearnerState 아님 |
| `user_track_history` | 사용자 이력(트랙 변경) — LearnerState 아님 |

**핵심-외 합계 = 38** · 42 + 38 = **80** ✓(EOS-49 `concept_version` 추가 — 2026-09-14,
이전 41 + 38 = 79는 SEC-27 `job_ownership` 추가 — 2026-09-11)

### §2-C. 판정 보류 1건 — 날조 금지

`misconception_hypothesis` 는 **특정 학생의 오개념 추정 레코드**다.

- Misconception(카탈로그)이 **아니다** — 학생에 종속된다.
- LearningEvent(원시 기록)도 **아니다** — 일어난 일이 아니라 L2가 *추론한 결론*이다.
- MasteryState도 **아니다** — 숙련도 축이 아니다.

**층을 늘리지 않는다**(관계 타입 폭발 금지의 동형). 20번째 엔티티를 만들지 않고 "핵심 외 ·
판정 보류"로 그대로 둔다. 이 결정을 뒤집으려면 §5 절차를 경유한다.

---

## §3. 좌석 부재 4종 — 부재를 동결한다

**부재는 실수가 아니라 결정이다.** 아래 4종은 "아직 안 만들었다"가 아니라 "9월에 만들지
않는다"이며, 검사 ③이 예약 이름(`subject`·`hints`·`assessment_result`·`content_version` 등)의
등장을 RED로 막는다.

### §3-A. Subject — 테이블로 만들지 않는다

- **현행 실체**: `Subject` enum 5값(공통·미적분·확통·기하·인공지능수학 — **수능 선택과목 축이며
  수학 교과 한정**) + 자유 텍스트 `subject` 컬럼 8테이블(`concept_content`·`curriculum_entry`·
  `achievement_standard` 등, 기본값 `"수학"`).
- **동결 사유**: 교과 확장(물리 등)의 트리거는 "물리 문항 첫 적재"로 이미 보류 대장에 있다
  (`docs/architecture/subject_expansion_readiness.md`). 그 전에 테이블을 만들면 **수능 선택과목
  축과 교과 축이 한 축으로 영구 혼동**된다.
- **9월 조치**: 없음. 열 축 유지.

### §3-B. Hint — 설계 정본은 있고 저장 좌석이 없다 → **좌석 미실체화 · 신설은 `S4-11` 소유**(2026-09-06)

> **판정 기준: main `3f2b39c1`** — 실측은 전부 이 커밋의 trunk 코드에서 확인했다.
>
> ⚠ **판정 정정(2026-09-07 · PR #1015 Codex P2 수용).** 이 절은 처음에 **"영구 부재"**로 적혔다.
> **그 판정은 틀렸다.** 좌석 신설을 이미 소유한 태스크가 대장에 있다 —
> `S4-11-hint-content-generation`(`status: todo` · `eos_priority: **P0**`)의 acceptance가
> "**hints 테이블 실체화**(생성 writer·검증·coach 서빙 reader)"와 `reveal_score` 로깅을
> 명시하고, notes는 이를 "HintNode Persistence **연기** 해제 조건 충족 슬라이스"로 규정한다.
> 즉 좌석은 *포기된 것*이 아니라 *연기된 것*이었고, 종전 §3-B의 "언젠가 필요하다"는 근거 없는
> 가정이 아니라 **다른 태스크의 약속**이었다. 아래 실측은 그대로 유효하지만, 그것으로 P0 태스크를
> 무효화할 수는 없다 — 백로그가 일정의 정본이다(CLAUDE.md 워크플로우 표준).

- **현행 실체**: `schemas/v1.1/hint.schema.yaml`이 entity `Hint`·L4·`storage: "PostgreSQL 16
  (hints)"`·`primary_key: hint_id`로 선언한다. **그러나 `hints` 테이블은 존재하지 않는다**
  (ORM `__tablename__` 0건 · alembic 언급 파일 0건).

- **판정(`ARCH-39`)**: **좌석 신설·불요를 판정하지 않는다 — 그 결정은 `S4-11`이 소유한다.**
  ARCH-39가 실제로 해소하는 것은 **선언↔실측 드리프트**(§7-B)뿐이다: yaml이 *지금 있는* 저장소를
  선언하는 것처럼 읽히던 것을 *계획된* 좌석으로 고쳐 적는다. 아래 실측은 **`S4-11`의 입력**이다.

#### 실측 — S4-11이 착수할 때 알아야 할 것

1. **런타임 힌트에는 영속 정체성이 없다.** 서빙 경로는 `l4/hint_deferral.decide_hint_level`
   (단계 결정) → `api/coach.py`(LLM 발화 조립) → `l4/tone_filter.filter_tone`(정서 안전)이며,
   본문은 그 턴의 대화 맥락에서 만들어지고 재사용되지 않는다. → S4-11의 "생성 writer"는
   *이 경로를 저장하는 것*이 아니라 **오프라인 생성**을 새로 세우는 일이다(acceptance가 이미
   "SolutionStep 원천 **오프라인 생성**"으로 그렇게 적고 있다).

2. **힌트 본문 생산 경로는 있고, 소비 경로가 없다.** `l3/dsl/models.py`의 `HintSpec.text`가
   `l3/dsl/compiler.py`에서 `CompiledContent.hint_texts`로 실린다(레벨 정렬 포함).
   그러나 **`l3/dsl` 밖 소비자는 0건**이고 DB 좌석도 없다 — 즉 만들어지지만 아무도 읽지 않는다.
   → S4-11의 "coach 서빙 reader"가 정확히 이 끊긴 지점이다.
   ※ 반면 `l3/solution_path.py`의 `SolutionStep.hint`는 **생산자·소비자가 모두 0건**이고
   실코퍼스 200행에도 `"hint"` 키가 0건이다(적재기 `populate.py` 언급 0건). 두 경로를 구분해야
   한다 — S4-11 acceptance가 원천으로 지목한 것은 후자(`SolutionStep`)인데, 실제로 텍스트가
   흐르는 것은 전자(`HintSpec`)다. **착수 시 이 불일치를 먼저 정리해야 한다.**

3. **Phase 1 KPI는 좌석 없이 이미 측정된다.** "세션당 평균 도달 깊이 2.5+"의 측정 정본은
   `harness/wh1_evaluation.py` ⑧ `hint_depth_reached` =
   `attempt_event`(`힌트제공`)의 **`hint_level` 평균·최대**다(`_hint_depth_from_levels`).
   yaml의 `reveals.reveal_score`는 **미구현**이며 KPI 경로가 읽지 않는다.
   → S4-11의 `reveal_score` 로깅은 **KPI 성립의 전제가 아니라 정밀화**다. 그 순서를 뒤집어
   "reveal_score가 없어서 KPI를 못 잰다"고 적으면 사실이 아니다.

4. **`hint_usage.hint_id`는 현재 writer 0건**이다(서빙 코드 전수 — 정의·주석 외 대입 0).
   S4-11이 좌석을 세우면 이 느슨참조를 FK로 조일지가 함께 걸린다(그 판단도 S4-11 소유).

#### `hints` 예약은 유지한다 — 금지가 아니라 **명시적 결정 요구**

`ABSENT_ENTITIES`·`RESERVED_ABSENT_TABLE_NAMES`의 `hint`/`hints` 예약과, 이번에 추가한
**컬럼 축 가드**(`test_no_table_gains_a_hint_body_column`)는 좌석을 *영구히 막는 장치가 아니다*.
둘 다 **좌석이 조용히 생기는 것**을 막는 속도 방지턱이며, S4-11은 그 항목들을 **의도적으로
걷어내면서** 착수한다(다른 부재 4종과 같은 규약). 컬럼 축을 더한 이유는 기존 두 검사가 모두
*테이블* 축이라, 새 테이블 없이 **기존 테이블에 컬럼 하나**를 더하는 경로가 무방비였기 때문이다
(실측: `problem_step`에 `hint_text` 주입 시 신규 가드만 RED, 기존 ③·③-b는 통과).

- **9월 조치**: `hint.schema.yaml`의 `storage` 선언을 실측에 맞게 정정(드리프트 §7-B 해소) ·
  좌석 신설 여부는 **판정하지 않고** `S4-11`에 넘긴다 · 예약 3종(테이블명·좌석 tuple·컬럼)은 유지.

### §3-C. AssessmentResult — `assessment` 안에 혼입돼 있다 → **혼입 유지로 판정**(2026-09-06)

> **판정 기준: main `794c0ea8`** — 아래 실측은 전부 이 커밋의 trunk 코드에서 확인했다
> (CLAUDE.md "미머지 존재를 '충족'으로 단정 금지" — 판정에는 시점이 붙어야 한다).
>
> **재확인: main `400a8e76`**(2026-09-06, PR #997 머지 정렬 시점) — 판정 기준 이후 trunk에
> 들어온 3커밋(`749ccb16`·`59503f7f`·`400a8e76`)이 판정 근거 경로
> (`assessment`·`api/coach.py`·`l2/`·privacy 3종·이 문서)를 **하나도 건드리지 않았음**을
> `git diff --name-only`로 확인했다. 근거가 살아 있으므로 판정을 갱신하지 않는다.
> 판정 *기준* 해시는 실측 시점 그대로 둔다 — 뒤늦게 바꾸면 재현 불가가 된다.

- **현행 실체**: `assessment` 테이블의 JSONB 5필드
  (`concept_diagnosis`·`pattern_diagnosis`·`weak_points`·`strong_points`·`recommended_path`).
  세션(언제 진단했나)과 결과(무엇이 나왔나)가 **한 행에 산다**.

- **판정(`ARCH-38`)**: **분리하지 않는다.** ARCH-37 당시 "이번 주 근거로는 이득이 실측되지
  않았다"였던 것을 `ARCH-38`이 W8 축으로 전수 재측정했고, 결과는 **이득 0**이다. 아래는
  "아직 안 봤다"가 아니라 **보고 나서 안 한다**는 판정이다.

#### 판정 근거 — 분리가 무엇을 얻는가: 셋 다 0

1. **W8 경로가 `assessment`를 읽지도 쓰지도 않는다.** 채점→오개념→Mastery 런타임 전 구간
   (`api/coach.py` `_complete_problem`:983-1030 → `curate_hypothesis`:1692 →
   `l2/mastery_tracking.py` → `l2/skill_mastery_tracking.py` → `l2/attempt_skill_event.py`,
   그리고 v1 잔존 경로 `api/me.py:721 submit_attempt`)에서 ORM `Assessment` 참조는 **0건**이다.
   그 경로가 만지는 것은 `ProblemAttempt`·`misconception_hypothesis`·`ConceptMasteryHistory`·
   `SkillMasteryHistory`·`attempt_event`이며, `assessment`는 **평행한 별도 좌석**이다.
   → **분리해도 W8 경로의 코드·쿼리·트랜잭션은 한 줄도 바뀌지 않는다.**
   ※ `api/coach.py`·`l2/*`의 `assessment` grep 히트 2건은 *모듈 파일명*이 같을 뿐
   `ConceptMasteryHistory`/`SkillMasteryHistory` 임포트다 — 테이블이 다르다.

2. **Assessment : Result는 1:1·write-once다** — 분리가 푸는 카디널리티 문제가 없다.
   writer 2곳(`api/me.py:2811` capture·`:3024` assemble)은 행 전체를 조립해 **한 번 commit**
   하고 끝이며, 5필드를 **갱신하는 경로가 없다**(`PATCH .../complete`는 `completed_at`만
   채운다·`api/me.py:2547-2570`). capture는 하루 1행 idempotency(`_find_existing_capture`
   :2655)라 한 세션이 결과를 여러 벌 낳지도 않는다. 별도 엔티티가 정당화되려면 결과가
   **N개이거나 append-only 이력**이어야 하는데 둘 다 아니다.

3. **reader가 0이라 "죽은 소비 경로 소생"이라는 선례 조건을 충족하지 못한다.**
   이 저장소의 JSONB→엔티티 분리 선례 `S4-09`(`solution_paths` 실체화)가 스스로 밝힌 정당화는
   *"reader 2종 소생 — `GET /v1/problems/{id}/steps` 실데이터·`learning_scene`
   `solution_path_id` 댕글링 해소"*였다. 즉 **이미 있는데 죽어 있던 소비처가 살아난다**는 것이
   근거였다. AssessmentResult에는 그 소비처가 없다 — 5필드를 *값으로 읽어 판단에 쓰는* 코드는
   서빙 경로에 0건이고(응답에 실어 보내는 직렬화는 소비가 아니다), 학생 화면 부재는
   **`ASM-11`이 소유**한다. 분리는 그 화면을 앞당기지 못한다.

#### 분리했을 때의 실비용 (측정된 반대편)

- **프라이버시 3계획의 순서 목록에 삽입**해야 한다 — `privacy/erasure.py:107`(`_ERASURE_PLAN`,
  "자식 우선" 순서 강제)·`privacy/retention.py:83`·`privacy/export.py:164`
  (`_STUDENT_FACING_SERIALIZERS`). 셋 다 순서·완전성 거버넌스 테스트가 붙어 있다.
- **GDPR 삭제 경로에 cascade 관심사가 새로 생긴다.** 현행 `delete_my_assessment`는
  *"Assessment는 자식 테이블이 없어 FK 위반 우려 없음"*(`api/me.py:2585`)을 전제로 서 있다.
  자식이 생기면 그 전제가 깨진다.
- ⚠ **완전성 가드의 사각**: `tests/backend/privacy/test_erasure_plan_completeness.py`는
  `user_id`·`student_id`·`target_user_id` **소유 컬럼이 있는 테이블만** 스캔한다
  (`OWNER_COLUMN_NAMES`). `assessment_result`를 `assessment_id` FK만으로 만들면 **미성년
  진단 데이터를 담은 테이블이 이 가드에 안 보인다** — 등재를 깜빡해도 RED가 안 난다.
  분리는 이 사각을 새로 만든다.
- 서빙 표면 5개(`GET /assessments`·`PATCH .../complete`·`DELETE`·`POST .../capture`·
  `POST .../assemble`)의 조회·조립 경로 전부 변경 + 소급 불가 마이그레이션 왕복.

**요약**: 얻는 것 0 · 치르는 것 위 5종. 지금 분리하면 순수 손실이다.

#### 9월 조치와 기계 집행

- **9월 조치**: 없음(분리하지 않는다). §1-16·§2-A의 `AssessmentResult` 좌석 수는 **0을 유지**한다.
- **집행**: 이 판정은 이미 기계가 지킨다 — `test_canonical_entity_model_freeze.py`의
  `ABSENT_ENTITIES`(좌석 tuple 비어 있음) + `RESERVED_ABSENT_TABLE_NAMES`
  (`assessment_result`·`assessment_results`)가 좌석 신설 시 **RED**를 낸다. 판정을 뒤집으려면
  §5 절차를 밟아 문서와 상수를 **함께** 고쳐야 한다(둘 중 하나만 고치면 검사 ④가 RED).

#### 재확인 지점 (만료 없는 유예 금지 — CLAUDE.md 2026-08-03)

이 판정은 **영구 결론이 아니라 현재 근거에 대한 판정**이다. 아래 셋 중 **하나라도 성립하면
재판정**한다 — 셋 다 위 "근거 3"의 부정이다.

| # | 재판정 트리거 | 관측 지점 |
|---|---|---|
| 1 | W8 경로(채점→오개념→Mastery)가 `assessment`를 읽거나 쓰기 시작 | `api/coach.py`·`l2/*`에 ORM `Assessment` 참조가 생김 |
| 2 | 한 Assessment가 결과를 **2개 이상** 낳거나 결과가 append-only 이력이 됨 | 5필드에 *갱신* writer가 생김 |
| 3 | 5필드를 **값으로 읽어 판단에 쓰는** 서빙 reader가 착지(`ASM-11` 등) | 직렬화가 아닌 소비 코드 |

**집행 — 트리거마다 장치가 다르다** (초판 정정 · Codex P2 · PR #997):

| 트리거 | 누가 알리는가 | 형태 |
|---|---|---|
| 1 (W8 경로가 Assessment를 만짐) | `tests/backend/db/test_assessment_result_verdict_premise.py` | **자동 RED** — 허용목록 밖에서 ORM `Assessment`를 임포트하면 즉시 실패 |
| 2 (갱신 writer 등장) · 3 (값을 읽는 서빙 reader) | 게이트 `G-arch38-verdict-recheck`[kiki] | **날짜 리마인더** — 2026-10-26(W8 종료 직후)부터 SessionStart 브리핑 |

재판정 착수는 **`ARCH-40-assessment-result-verdict-recheck`**가 지고, 그 태스크는 위 게이트로
`requires_gates` **차단**돼 있다.

> **초판이 틀렸던 지점**: 재확인을 태스크로 등재하는 것만으로 집행이라 적었으나, 그 태스크는
> `depends_on: []`·`requires_gates: []`라 selector가 **즉시 착수 후보로 계산했다**(실측:
> 후보 124건에 포함). "트리거가 성립하면 재판정한다"고 적어 놓고 트리거를 기다리는 장치가
> 없었던 것이다 — 지금 실행하면 전부 False로 확인하고 또 하나의 즉시-후보를 재생성할 뿐이고,
> 방치하면 재확인은 집행되지 않는다. **이 문서가 인용한 "정본화를 집행으로 착각한 완료 선언
> 금지"를 그 재확인 축에서 그대로 되풀이한 셈**이며, Codex 리뷰가 잡았다. 게이트 부착 후
> 후보 124 → 123건으로 줄고 ARCH-40이 빠지는 것을 실측 확인했다(대조군 `OPS-62`는 잔류).

#### 함께 실측된 드리프트 (고치지 않고 적는다)

- **`strong_points`는 writer가 0이다.** 5필드 중 유일하게 *쓰는 코드가 아예 없는* 컬럼인데
  `StudentAssessment` 응답에는 실려 나간다(항상 `[]`). "좌석이 있다고 writer가 있다는 뜻이
  아니다"(§7-C)의 컬럼 축 사례다. 소유자 = **`ASM-13-strong-points-writer-absence`**.
- **주차 표기 어긋남**: `ARCH-38` notes는 W8을 `10/12~10/18`로 적지만, 선언의 주간 리듬
  (W1=`8/31~9/6`, `eos_transition_declaration_2026-08-30.md`)에서 그 구간은 **W7**이고
  W8은 `10/19~10/25`다. 어느 쪽이든 `ARCH-38` 기한(`2026-10-05`)보다 뒤라 **이 판정의
  결론은 바뀌지 않는다**. 계획서 300 원문이 저장소 밖이라 라벨·날짜 중 무엇이 정본인지는
  여기서 판정하지 않는다(날조 금지).

### §3-D. ContentVersion — 전용 좌석 없이 분산돼 있다

- **현행 실체**: `curriculum_version`(교육과정 판만 담당) + 각 테이블의 버전 컬럼
  (`unit_spec.unit_version`·`pedagogy_pack.pack_version`·`api_version`·`problem.curriculum_version`·
  `generation_log.prompt_version`) + `content_provenance`.
- **알려진 갭**: `concept_node`에 `version` 컬럼이 **없다**. 계획서가 경고한
  "엔티티마다 별도 버전 시스템을 만들지 말라"는 **유효한 경고**이며, 이 축은
  **`EOS-49`(ConceptVersion 계약)·`EOS-47`(attempt version pinning)이 소유**한다.
- **9월 조치**: 이 문서는 좌석을 만들지 않는다. 공통 버전 축 설계는 위 두 태스크로 넘긴다 —
  **여기서 20번째 엔티티를 급조하면 두 태스크와 충돌한다.**

#### 판정 2026-09-06 — 부재는 *범용* ContentVersion에만 걸린다 (게이트 `G-eos49-content-version-seat`)

`EOS-49`의 `concept_version` 착수 가부를 두고 이 절과 `44_eos_version_management.md`가
충돌하는지 판정했다. **결론: 충돌하지 않는다.** 이 절이 막는 것은 위 문장 그대로
**"20번째 엔티티 급조"**, 즉 모든 도메인을 한 테이블에 담는 *범용* ContentVersion이다.
44 §6.1은 Unified Entity 슈퍼테이블을 **보류**하고 Hybrid(공통 헤더 Pydantic + 도메인별
버전 테이블)를 채택했고 §14-8은 슈퍼테이블 즉시 도입을 **금기**로 명시한다 — 즉 두 정본은
같은 것을 금지하고 있었다.

**도메인별 버전 테이블은 그 엔티티 좌석에 편입한다.** 선례가 이미 있다:
`curriculum_version`은 Curriculum 좌석의 2번 테이블이다(§2-A) — 새 엔티티가 아니다.
같은 규칙으로 `concept_version`은 **Concept 좌석**, `problem_version`(ARCH-31)은
**Problem 좌석**에 앉는다. `ContentVersion` 좌석은 **비운 채로 유지**한다(검사 ③·③-b 무손상).

**차단 주체 정정** — 이 게이트의 원 문면은 검사 ③/③-b가 `concept_version`을 막는다고 적었으나
실패 주입으로 확인한 결과는 다르다(main `9d5f81b2` 실측):

| 검사 | `concept_version` 주입 시 | 정상 시 |
|---|---|---|
| ① 전수 귀속 | **RED** — `귀속 없는 신규 테이블 1건` | GREEN |
| ③ 예약 이름 | GREEN — 예약 목록에 `concept_version`이 없다 | GREEN |
| ③-b 좌석 tuple | GREEN — `ContentVersion` 좌석이 비어 있는 한 무관 | GREEN |
| ④ 문서↔상수 | GREEN | GREEN |

막는 것은 **검사 ①**이며, 그것은 "이 좌석 배정을 정본에 적었는가"를 묻는 검사다 — 부재 동결을
푸는 것이 아니라 **§5 절차를 밟았는가**를 묻는다.

---

## §4. 9월 스키마에 넣지 않는 것

Kiki 지시: *"기존에 검토해 온 훨씬 많은 Node를 모두 9월 schema에 넣는 것은 피한다."*
그 지시를 **판정 가능한 규칙**으로 옮기면 아래다.

1. **19종 밖의 새 1급 엔티티를 9월에 만들지 않는다.** 20번째가 필요해 보이면 먼저 §2-C처럼
   "핵심 외 · 판정 보류"로 적어 둔다 — 층을 늘리는 것이 마지막 수단이다.
2. **부속 노드는 부속으로 둔다.** `formula_node`·`problem_type_node`·`atom_probe`는 승격 후보이나
   9월 승격 금지. 승격은 §5 절차.
3. **관계 타입을 늘리지 않는다.** 현행 엣지 9종으로 충분한지 먼저 묻는다 —
   "이 관계가 없으면 AI 튜터링에서 실제 어떤 오류가 나는가"에 답하지 못하면 weak → 제거.
4. **개념 노드에 아무것도 더 붙이지 않는다.** renderer·curriculum·prompt·misconception·UI·
   embedding은 이미 전부 외부화돼 있다(§2-B가 그 증거) — 되돌리지 않는다.
5. **W2가 확정하는 소급 불가 스키마**(`REC-11`·`EOS-47`·`EOS-49`)는 이 동결의 **예외가 아니라
   대상**이다. 셋 다 새 엔티티가 아니다 — 이 동결과 충돌하지 않는다.
   **정정 2026-09-06**: 원 문장은 셋을 모두 "기존 좌석의 **컬럼 추가**"로 적었으나 `EOS-49`
   acceptance ①은 `concept_version` **테이블 신설**이다(사실 오류). 판정 결과는 §3-D 하단 —
   *도메인별 버전 테이블은 소속 엔티티 좌석에 편입한다*(엔티티 19종 불변). `REC-11`·`EOS-47`은
   원 서술대로 컬럼 추가가 맞다.

---

## §5. 동결을 푸는 절차

동결은 영구 금지가 아니라 **비용을 명시한 문턱**이다. 새 엔티티·새 좌석이 필요하면:

1. **어느 기존 엔티티로도 안 되는 이유**를 §1의 *아니다* 절과 대조해 적는다.
2. **backlog 태스크로 등재**한다(`backlog.py add` — 번호 눈으로 고르기 금지).
3. 이 문서의 §1·§2 표와 `test_canonical_entity_model_freeze.py`의 **상수를 함께** 고친다.
   둘 중 하나만 고치면 검사 ④가 RED를 낸다(그것이 이 검사의 목적이다).
4. MEMORY.md에 결정 로그를 남긴다.

**이 절차 자체에는 기계 집행이 없다** — 3번만 기계가 본다. 1·2·4는 사람 규율이다.

### §5-1. 좌석 등재는 테이블 신설과 **원자적**이어야 한다 (2026-09-06 실측)

3번을 "문서·상수를 먼저 고치고 구현을 나중에"로 나누면 **CI가 즉시 RED**가 된다. `concept_version`을
좌석에만 선등재한 상태를 주입해 실측한 결과(main `9d5f81b2`):

| 검사 | 좌석만 선등재 시 |
|---|---|
| ① 전수 귀속 | **RED** — `정본이 선언한 테이블이 코드에 없다` |
| ② 좌석 실재 | **RED** — `좌석 테이블이 사라졌다(삭제·개명 추정)` |
| ④ 문서↔상수 | **RED** — 문서와 상수가 어긋난 중간 상태 |

그러므로 **§2-A 표 + 좌석 상수 + ORM/alembic을 같은 PR에 담는다.** 게이트 판정 세션이 좌석 표를
미리 고쳐 두는 것은 금지다 — 판정 결과는 산문(§3-D)에 적고, 표와 상수는 구현 PR이 함께 옮긴다.

---

## §6. 인접 정본과의 경계 (중복 방지)

| 문서·태스크 | 소유 범위 | 이 문서와의 관계 |
|---|---|---|
| `EOS-79-evidence-layer-boundary-canon` | Attempt·Evaluation·Assessment·Mastery **4층 경계** | 이 문서 §1-17(LearningEvent)의 **내부 분해**를 소유. 대체하지 않음 — EOS-79는 그대로 진행 |
| `docs/standards/part9_id_policy_review.md` | 엔티티 **ID 형식**(`math.<area>.<slug>`·`skill.<slug>`·`M0425`) | ID는 이미 동결·CI 집행 완료. 이 문서는 ID를 **재정의하지 않는다** |
| `EOS-49` / `EOS-47` | **버전 축** 공통 계약 | §3-D의 미해결분을 소유 |
| `docs/architecture/32_learning_history.md` §4 | 학습이력 9엔티티 판정표 | 도메인 한정 부분 정본. 충돌 시 **이 문서가 상위** |
| `docs/reviews/eos_phase2_plan_300_gap_review_2026-09-03.md` §4.1 | 14객체 실측 대조표 | 리뷰 문서(정본 아님). 이 문서가 그 인벤토리를 19종으로 승격·확장 |
| `docs/architecture/eos_core_adapter_boundary.md` | 모듈 Core/Adapter 배정 | 축이 다름(모듈 vs 엔티티) |

---

## §7. 알려진 드리프트 — 그대로 적는다

기계 집행이 **없는** 축이라 사람이 읽어야 한다. 고치지 않고 적는 이유는, 지금 고치면
9월 동결의 범위가 아니라 리팩터가 되기 때문이다.

- **A. `schemas/v1.1` 저장소 선언이 낡았다.** `concept.schema.yaml`·`edge.schema.yaml`이
  `storage: Neo4j 5.x`라고 적지만, Neo4j는 **런타임 미도입**이고 정본은 PG 단일 평면이다
  (CLAUDE.md 2026-08-03 확정). 이 정본은 PG 실측을 따른다.
- **B. ~~`schemas/v1.1/hint.schema.yaml`이 없는 테이블을 선언한다.~~ → 해소**(`ARCH-39` ·
  2026-09-06). 선언을 실측에 맞춰 정정했다: `storage`가 *이미 있는* 저장소를 가리키는 것처럼
  읽히던 것을 **"계획 — `hints` 미실체화 · 신설은 `S4-11`(P0) 소유"**로 고쳐 적었다.
  좌석을 만들어서도, 만들지 않기로 해서도 아니라 **선언을 사실에 맞춰** 해소했다.
  드리프트 A(Neo4j 선언)와 형태는 같지만 처분이 다르다: A는 "정본이 PG"라는 *대체 좌석*이
  이미 있어 선언만 낡은 것이고, B는 좌석이 **아직 없고 소유자가 있는** 상태다.
  ※ [정정 2026-09-07] 이 항목은 한때 "만들지 않기로 판정해 해소"라고 적혔다 — 틀렸다(§3-B 상단).
- **C. 좌석이 있다고 writer가 있다는 뜻이 아니다.** `learning_session`은 스키마가 실재하나
  **writer 0**으로 실측됐다(계획서 300 검토 §4.1). 이 문서는 좌석의 *존재*만 동결하며
  **배선 여부는 판정하지 않는다** — 배선·폐기 판정은 별도 소유자가 필요하다.
- **D. `ROADMAP.md` 미반영 잔여 "스키마 v1.0↔v1.1 통합"이 여전히 열려 있다.**
  이 문서는 그 통합을 수행하지 않는다.

---

## 부록. 재현 명령

> ⚠ **명령 정정(`OPS-61` · 2026-09-06)** — 종전 블록은 저장소 루트에서 테스트 경로를
> *위치 인자로* 주는 형태였고, 그렇게 부르면 pytest가 rootdir을 저장소 루트로 잡아
> `src/backend/pyproject.toml`의 설정이 통째로 안 읽힌다. 지금은 conftest 가드가 이를
> **EXIT 4 UsageError로 즉시 정지**시킨다(실측 확인 — 종전 명령은 테스트를 한 건도 돌리지
> 못한다). 아래는 `-c`로 설정 파일을 못 박은 형태다.

```bash
# WSL / Linux — 저장소 루트에서
cd /mnt/c/Users/kiki/Desktop/__AI/WhyMath
python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend \
  tests/backend/db/test_canonical_entity_model_freeze.py -v; echo "EXIT=$?"
```

```powershell
# Windows PowerShell (Phaiakes9) — 저장소 루트
cd C:\Users\kiki\Desktop\__AI\WhyMath
python -m pytest -c src\backend\pyproject.toml --rootdir=src\backend `
  tests\backend\db\test_canonical_entity_model_freeze.py -v; echo "EXIT=$LASTEXITCODE"
```

판정은 **exit code**로 한다(출력 문자열 아님 — CLAUDE.md "검사 명령의 출력을 억제하거나 잘라서
판정 금지").
