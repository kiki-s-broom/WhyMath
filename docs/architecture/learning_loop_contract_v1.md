# EOS Learning Loop Contract v1 — 14객체·18관계 동결

> **한 줄**: 계획서 300 §1(EOS Kernel)의 **학습 루프 어휘를 14객체·18관계로 닫고**, 그 14객체를
> `ARCH-37` 핵심 엔티티 19종 좌석 정본에 전수 귀속시킨다. 신규 DB 테이블·신규 좌석은 만들지 않는다.

- **판정 기준: main `c4f8c9fb`** (2026-09-16)
- **태스크**: `EOS-100-learning-loop-relation-contract`
- **코드 정본**: `src/backend/whymath_backend/schema/learning_loop_contract.py`
- **기계 집행**: `tests/backend/schema/test_learning_loop_contract.py`
- **선행 정본**: `docs/architecture/canonical_entity_model_v1.md`(`ARCH-37` 19종 좌석) ·
  `docs/architecture/evidence_layer_boundary.md`(`EOS-79` 4층 순서)

---

## ⚖️ 집행 고지 (정본화 ≠ 집행)

CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"에 따라 **강제하는 것과 강제하지 않는 것**을
먼저 적는다.

### 기계가 강제하는 것 — `tests/backend/schema/test_learning_loop_contract.py`

| # | 검사 | 깨지면 |
|---|---|---|
| ① | 루프 객체 **정확히 14종** + 이름 집합 일치 | 15번째 객체를 추가하면 **RED** |
| ② | 관계 삼중항 **정확히 18건** + 집합 일치 | 미선언 관계를 추가하면 **RED** |
| ③ | 모든 관계의 source·target이 14객체 안 | 미정의 객체를 관계에 쓰면 **RED** |
| ④ | 좌석 귀속이 14객체를 **전수** 1:1 커버 | 객체를 추가하고 귀속을 빠뜨리면 **RED** |
| ⑤ | 귀속이 지목한 엔티티 이름이 `ARCH-37` §2-A 표에 **실재** | 유령 엔티티·오탈자면 **RED** |
| ⑥ | 고립 객체 집합이 관계에서 **계산한 값**과 일치 | 관계를 지워 객체가 고립되면 **RED** |
| ⑦ | `prerequisite`가 DAG 제약 대상 + 순환 주입 검출 + 집행 지점 파일 실재 | 순환을 놓치면 **RED** |
| ⑧ | 이 문서 §2·§3 표 ↔ 코드 상수 **1:1 대조** | 한쪽만 고치면 **RED**(드리프트 차단) |
| ⑨ | 파서 자신이 위장하지 않음 — 표를 못 찾으면 "0건 통과"가 아니라 **예외** | 문서 구조가 깨지면 **RED** |

⑤·⑧은 "이름이 문서 어딘가에 있다"가 아니라 **어느 행에 어떻게 배정됐는지**를 본다.

### 기계가 강제하지 **않는** 것 (있는 척 금지)

- **서빙 배선.** 오늘 이 상수를 읽는 API·엔진은 **0건**이다. 이 문서는 "루프가 이 계약대로
  돈다"고 말하지 **않는다** — 말하는 것은 "루프의 어휘가 이것으로 닫혔다"까지다. 배선은
  `EOS-10`(LearnerState 단일 표면) · `EOS-12`(Assessment Evidence) · `EOS-13`(Mastery 호출
  계약) · `EOS-14`(Recommendation 호출 계약)가 각자 소유한다.
- **관계의 *옳음*.** 기계는 코드와 문서가 **서로 일치하는지**만 본다. 둘이 사이좋게 틀려 있으면
  통과한다 — 계획서 §1과의 대조는 사람 판단이다.
- **실데이터의 DAG 무결성.** `find_prerequisite_cycle`은 계약층 primitive다. 실적재 경로의
  차단은 `l1/atom_graph/populate.py`·`data_pipeline/atom_graph/validate.py` 2지점이 소유하며,
  검사 ⑦은 그 **파일이 실재하는지**까지만 본다(적재 실행은 DB가 필요해 이 스위트 밖이다).
- **좌석 축.** 어떤 테이블이 어느 엔티티에 속하는지는 여전히 `ARCH-37` 정본 하나가 소유한다.

---

## §0. 이 문서가 `ARCH-37`을 뒤집지 않는 이유 (먼저 읽을 것)

`EOS-09` 변환 대조표(`docs/strategy/plan300_phase2_backlog_crosswalk.md` §9-②)는 이 축을
**등재 제외**로 판정했다. 사유는 이렇다:

> `ARCH-37`(done)이 19종 좌석 정본을 세우며 엣지 테이블(`concept_edge`·`evidence_links` 등)을
> **'핵심 외'로 명시 배제**했다. 관계 계약을 지금 등재하면 **이미 내려진 배제 판정을 태스크가
> 조용히 뒤집는다.** 필요한 것은 "관계 계약을 세울 것인가"라는 결정이지 착수 단위가 아니다.

그 판정은 옳고, 이 문서는 그것을 뒤집지 않는다 — **축이 다르기 때문**이다.

| 축 | `ARCH-37`이 배제한 것 | 이 문서가 고정하는 것 |
|---|---|---|
| 대상 | **저장 좌석** — 관계를 담는 *테이블* | **호출 어휘** — 관계의 *이름과 방향* |
| 산출 | 79→80테이블 전수 귀속표 | 14객체·18관계 삼중항 레지스트리 |
| 효과 | 엣지 테이블은 핵심 엔티티가 **아니다** | 선언되지 않은 엣지는 계약 위반이다 |

즉 이 문서는 엣지 테이블에 좌석을 **주지 않는다**. `Recommendation`처럼 좌석이 없는 객체는
`no_seat`으로 적고 끝내며, 20번째 엔티티를 만들지 않는다(만들면 `ARCH-37` 검사 ②가 RED다).

**착수 근거**: 2026-09-16 Kiki 지시(계획서 300 집행 지시문 `P-01`). §9-②가 "결정이 선행"이라고
적은 그 결정에 해당한다.

---

## §1. 14객체 — 루프 어휘의 전부

계획서 300 §1 EOS Kernel 그대로다. **이 목록에 없는 객체는 루프 어휘가 아니다.**

`Learner` · `LearnerState` · `Curriculum` · `Objective` · `Concept` · `Skill` · `Content` ·
`Problem` · `Attempt` · `Assessment` · `Misconception` · `Mastery` · `Recommendation` ·
`LearningSession`

> **실측 정정**: 집행 지시문 `P-01`은 이 목록을 "13개 객체"라고 적었으나 **열거된 이름은 14개**다.
> 목록이 정본이고 개수 표기가 오기다(세어서 확인). 코드·문서·테스트 전부 **14**로 고정한다.

---

## §2. 18관계 — (source) --edge--> (target)

관계 타입은 **16종**이며 `similar_to`·`related_to`는 의도적으로 없다(CLAUDE.md: traversal
사용 금지). 전부 **단방향 canonical edge**로 저장한다.

| # | source | edge | target |
|---|---|---|---|
| 1 | `Learner` | `has` | `LearnerState` |
| 2 | `LearnerState` | `mastery` | `Concept` |
| 3 | `LearnerState` | `mastery` | `Skill` |
| 4 | `LearnerState` | `misconception` | `Misconception` |
| 5 | `LearnerState` | `current_goal` | `Objective` |
| 6 | `Objective` | `requires` | `Concept` |
| 7 | `Concept` | `prerequisite` | `Concept` |
| 8 | `Concept` | `taught_by` | `Content` |
| 9 | `Concept` | `assessed_by` | `Problem` |
| 10 | `Concept` | `associated_with` | `Misconception` |
| 11 | `Problem` | `assesses` | `Concept` |
| 12 | `Problem` | `assesses` | `Skill` |
| 13 | `Problem` | `triggers` | `Misconception` |
| 14 | `Attempt` | `made_by` | `Learner` |
| 15 | `Attempt` | `on` | `Problem` |
| 16 | `Attempt` | `produces` | `Assessment` |
| 17 | `Assessment` | `updates` | `LearnerState` |
| 18 | `LearnerState` | `feeds` | `Recommendation` |

### 2-1. DAG 제약

`prerequisite`(7번)만 DAG를 강제한다 — 유일한 자기참조 관계이며, 순환이 생기면 학습 경로가
구성 불가가 된다(CLAUDE.md 7대 붕괴 연쇄 3단계). 계약층 primitive는
`find_prerequisite_cycle`·`reachable_from`이고, **실적재 차단은 기존 2지점이 소유한다**:

- `src/backend/whymath_backend/l1/atom_graph/populate.py` (`AtomBackboneCycleError` — hard fail)
- `src/data-pipeline/data_pipeline/atom_graph/validate.py` (transform 단계 1차 차단)

> **정직한 공백**: 순환 탐지 구현이 이제 저장소에 **3벌**이다(위 2곳 + 계약층 primitive).
> 통합 여부는 이 태스크 범위 밖이며 `EOS-101`이 소유한다. 지금은 검사 ⑦-c가 세 구현이 같은
> 픽스처에서 **같은 판정을 내는지** 대조해 조용한 분기를 막는다.

### 2-2. 관계가 0건인 객체 3종 (고립 — 날조로 채우지 않는다)

`Curriculum` · `Mastery` · `LearningSession` 은 계획서 §1 관계도에서 **한 번도 source·target으로
등장하지 않는다.** 없는 관계를 지어내지 않고 고립 사실 그대로 적는다.

- `Curriculum` — `Objective`가 교육과정에 속하지만 계획서가 그 엣지를 적지 않았다.
- `Mastery` — 엣지 이름 `mastery`(2·3번)와 **다른 것**이다. 객체 `Mastery`는 고립돼 있다.
- `LearningSession` — 루프를 담는 컨테이너인데 계획서 관계도가 컨테이너 엣지를 적지 않았다.

이 3건은 계약의 결함일 수 있으나 **계획서 대비 추가는 임의 확장**이므로 하지 않는다. 확장이
필요하다는 판정이 서면 그때 관계를 추가하고 이 문서·코드·테스트를 함께 고친다.

---

## §3. `ARCH-37` 19종 좌석 정본과의 전수 귀속표

귀속 어휘: `seated`(동명 좌석 있음) · `seated_alias`(좌석 있으나 정본 이름이 다름) ·
`absorbed`(다른 엔티티 좌석에 흡수) · `no_seat`(19종에 대응 없음).

| Loop 객체 | 정본 엔티티 | 귀속 | 이름충돌 | 비고 |
|---|---|---|---|---|
| `Learner` | `Learner` | `seated` | 아니오 | 좌석 `user_profile` |
| `LearnerState` | `LearnerState` | `seated` | 아니오 | 좌석 `user_state_snapshot` — writer 0(`EOS-10`) |
| `Curriculum` | `Curriculum` | `seated` | 아니오 | 좌석 `curriculum_framework`·`curriculum_version` |
| `Objective` | `LearningObjective` | `seated_alias` | 아니오 | 계획서 약칭 — 저장소 정본 이름 유지 |
| `Concept` | `Concept` | `seated` | 아니오 | 혼재 3좌석은 `ARCH-37` §5 소관 |
| `Skill` | `Skill` | `seated` | 아니오 | 좌석 `skill_node` |
| `Content` | `Content` | `seated` | 아니오 | 좌석 `concept_content`·`pedagogy_content_slot` |
| `Problem` | `Problem` | `seated` | 아니오 | 좌석 `problem`·`problem_step` |
| `Attempt` | `LearningEvent` | `absorbed` | 아니오 | `problem_attempt`·`attempt_event`·`answer_submission` |
| `Assessment` | `Assessment` | `seated` | 예 | ⚠ 같은 글자, 다른 것 — §3-1 |
| `Misconception` | `Misconception` | `seated` | 아니오 | 좌석 `misconception_catalog` |
| `Mastery` | `MasteryState` | `seated_alias` | 아니오 | 좌석 `*_mastery_history`·`ability_snapshot` |
| `Recommendation` | — | `no_seat` | 아니오 | 19종에 대응 없음 — 좌석 신설 안 함 |
| `LearningSession` | `LearningEvent` | `absorbed` | 아니오 | 좌석 `learning_session` — writer 0 |

**합계**: `seated` 9 · `seated_alias` 2 · `absorbed` 2 · `no_seat` 1 = **14**.
이 중 **이름충돌 1건**(`Assessment`)은 귀속 축과 독립된 별개 축이다 — 좌석은 있는데 *뜻*이 다르다.

### 3-1. 미해결 — `Assessment` 이름 충돌 (Kiki 판정 대기)

**같은 이름이 두 가지 다른 것을 가리킨다.** 이것은 약칭 문제(`Objective`·`Mastery`)가 아니라
**의미 충돌**이라 자동 정정이 불가능하다.

| | 계획서 300 §5.1의 `Assessment` | `ARCH-37` #15의 `Assessment` |
|---|---|---|
| 뜻 | **한 답안의 채점 산출** — `concept_evidence{}`·`skill_evidence{}`·`possible_misconceptions[]` 묶음 | **진단 평가 세션 컨테이너** — "언제 무엇을 진단했는가" |
| 단위 | per-answer (제출 1건마다) | per-session (CAT 진단 1회) |
| 좌석 | 없음 | `assessment` 테이블 |
| 루프 위치 | `Attempt --produces--> Assessment --updates--> LearnerState` | 루프 밖(진단 세션) |

**임의 개명하지 않았다.** 현재 코드·문서는 두 뜻을 같은 이름으로 적되 `semantic_collision=True`로
**충돌을 데이터로 기록**한다. 판정 3택은 §5에 있다.

### 3-2. 루프 어휘 밖의 핵심 엔티티 8종

`ARCH-37` 19종 중 계획서 §1 루프 어휘에 **대응이 없는** 것들이다. 갭이 아니라 **범위 차이**다 —
루프 어휘는 학습 루프가 도는 데 필요한 최소 집합이고, 19종은 저장 좌석의 전수 집합이다.

`Subject` · `CurriculumNode` · `Solution` · `Hint` · `AssessmentResult` · `LearningEvent` ·
`PedagogyStrategy` · `ContentVersion`

> 이 목록은 **하드코딩이 아니다** — 검사 ⑤가 `ARCH-37` §2-A 표를 파싱해 19종을 읽고, 귀속표가
> 지목한 엔티티를 뺀 나머지로 계산한다. `ARCH-37`이 엔티티를 추가·개명하면 자동으로 따라온다.

---

## §4. 뮤테이션 검증 결과 — 25종 전건 RED · 생존 0

정상 입력에서 초록인 것은 보호의 증거가 아니므로(CLAUDE.md "보호 장치를 실패 주입 없이 '보호
있음'으로 선언 금지"), **막으려는 상태를 실제로 주입해** 각 검사가 RED를 내는지 확인했다.
하네스는 셸을 배제한 **순수 Python**이며(2026-09-06 "주입 자체의 실재" 규칙) 회차마다
`mutated != original`·sha256 변화·**바이트 동일 원복**을 단언한다.

| # | 주입 | 노린 검사 | exit | 판정 |
|---|---|---|---|---|
| M01 | 15번째 루프 객체 추가 | ① | 1 | RED |
| M02 | 루프 객체 삭제(`Recommendation`) | ①④ | 2 | RED |
| M03 | 선언되지 않은 관계 추가(`Problem --has--> Learner`) | ② | 1 | RED |
| M04 | 관계 삭제(`Assessment --updates--> LearnerState`) | ② | 1 | RED |
| M05 | 관계 방향 뒤집기(`Attempt --on--> Problem`) | ② | 1 | RED |
| M06 | 쓰이지 않는 엣지 타입 추가 | ③ | 1 | RED |
| M07 | traversal 금지 엣지 `similar_to` 도입 | ③ | 1 | RED |
| M08 | 귀속이 유령 엔티티를 지목 | ⑤ | 1 | RED |
| M09 | 좌석 귀속 1건 삭제(`Mastery`) | ④ | 2 | RED |
| M10 | 이름충돌 표기 은폐(`semantic_collision=False`) | ⑤ | 1 | RED |
| M11 | 고립 객체 상수를 관계와 어긋나게 | ⑥ | 1 | RED |
| M12 | 순환 탐지 무력화(항상 `None` — **위음성**) | ⑦ | 1 | RED |
| M13 | 순환 탐지 과잉(항상 순환 — **위양성**) | ⑦ | 1 | RED |
| M14 | DAG 집행 지점을 존재하지 않는 경로로 교체 | ⑦ | 1 | RED |
| M15 | DAG 제약 선언 제거 | ⑦ | 1 | RED |
| M16 | `prerequisite` 아닌 자기참조 관계 삽입 | ②⑦ | 1 | RED |
| M17 | `reachable_from` 무력화 | ⑦ | 1 | RED |
| M18 | 이 문서 §2 관계표 행을 조용히 변경 | ⑧ | 1 | RED |
| M19 | 이 문서 §3 귀속표 `status`를 조용히 변경 | ⑧ | 1 | RED |
| M20 | 이 문서 §2 표 형식 파괴(파서 0건) | ⑨ | 1 | RED |
| M21 | 이 문서 §1 산문에서 객체 1종 누락 | ⑧ | 1 | RED |
| M22 | CI 경로 필터에서 동결 입력 제거 | CI 배선 | 1 | RED |

**M12·M13 쌍이 이 스위트의 핵심**이다. 위음성만 주입하면 "전부 순환"이라고 답하는 과잉 수정이
통과하므로, **성공 방향 대조군**(깨끗한 DAG 4종·깊은 체인 5,000노드)을 함께 둬 양방향을 막았다
(2026-09-08 "전건 RED는 커버리지의 증거가 아니다" 규칙의 대조군 요구).

**M02·M09는 exit 2**(수집 단계 실패)다 — 단언이 아니라 import 오류로 잡혔다. 검출은 검출이나
"어느 검사가 잡았는지"는 M02·M09에 한해 특정되지 않는다. 정직하게 적는다.

**M22는 별도 스위트**(`tests/infra/test_ci_contract_fixture_trigger_wiring.py`)가 잡았다 —
"검증 장치를 만들고 배선 확인 없이 완료 선언 금지"의 이 문서 몫이다. 이 문서만 고치는 PR에서
backend 잡이 깨어나는지를 그 가드가 기계로 강제한다.

### 4-1. 부수 수정 — `EOS-84` 경계 프로브의 `trig` 거짓 양성 (뮤테이션 3종 추가)

이 계약의 `LoopEdge.TRIGGERS`(계획서 §1 `Problem triggers→ Misconception`)가
`tests/infra/test_eos_core_boundary_probe.py`의 ratchet을 깨뜨렸다. 원인은 계약이 아니라
**탐지기**다 — `scripts/analysis/eos_core_boundary_probe.py`의 `trig\w*`가 `trigger`를
부분매치했다(삼각함수를 노린 패턴이 `\w*`로 일반어를 삼켰다).

**이 오탐은 2026-09-06(`EOS-86`)에 이미 관측됐고, 그때의 대책은 오탐을 baseline에
등재하는 것이었다** — 즉 데이터로 덮었고, 그래서 이번 2회차를 못 막았다. CLAUDE.md
「실수 관리」의 반복 실수 규칙과 "동일 유형 텍스트 규칙 2회 실패 후 코드 착지" 선례에 따라
대책을 **코드**에 뒀다: `trig(?!ger)\w*`(2곳) + 회귀 테스트 2종 + 은퇴한 baseline 엔트리 제거.

관계명을 바꾸는 선택지는 없었다 — `triggers`는 계획서 §1의 어휘이고, 개명하면 이 태스크가
고정하려던 충실성 자체가 깨진다. **탐지기가 틀렸을 때 피검체를 고치지 않는다.**

| # | 주입 | exit | 판정 |
|---|---|---|---|
| M23 | 부정 전방탐색 제거(1회차 상태로 회귀) | 1 | RED |
| M24 | 과잉 수정(`trigonometr\w*`만 — `trig`·`TRIG`·`trig_identity`까지 끔) | 1 | RED |
| M25 | 은퇴시킨 거짓양성 baseline 엔트리 복원 | 1 | RED |

M24가 **성공 방향 대조군**이다 — 부정 전방탐색이 진짜 삼각함수 어휘까지 끄면 과잉 수정이고,
그 상태도 RED여야 한다.

재현: `python3 scripts/harness/mutate_eos100.py` 는 **없다** — 하네스는 세션 스크래치패드에서
1회성으로 돌렸고 저장소에 커밋하지 않았다. 재현이 필요하면 위 표의 주입 문자열을 그대로 쓰면 된다.

---

## §5. Kiki 판정 대기 1건

| # | 판정 | 3택 |
|---|---|---|
| ① | `Assessment` 이름 충돌(§3-1) | **(A)** 계획서 쪽을 `AssessmentEvidence`로 부른다(정본 이름 보존·`EOS-12`가 그 이름으로 계약을 만든다) / **(B)** 정본 `Assessment`를 `DiagnosticSession`으로 개명한다(좌석·ORM·문서 3곳 동시 변경·비용 큼) / **(C)** 충돌을 기록만 하고 유지한다(현 상태 — 두 뜻이 계속 같은 글자를 쓴다) |

판정 전까지 코드는 **(C)** 상태이며, 그 사실이 `semantic_collision=True`로 기계에 남아 있다.

**만료 없는 유예가 아니다** — 판정 소유자는 `EOS-12-assessment-evidence-contract`이며, 그 태스크
acceptance ⑤가 이 3택을 **대장에 집행**한다(2026-09-16 `amend`). 산문 유예가 아니라 착수 조건이다:
`EOS-12`가 Evidence 계약의 이름을 정하는 순간이 곧 이 충돌의 판정 시점이고, `(C)`를 고르더라도
**다음 재확인 지점을 명시**해야 한다.

> **세션 기록(2026-09-16)**: 이 3택을 Kiki에게 직접 물었으나 응답 없이 진행하기로 했다. 따라서
> 위 `(C)`는 *선택된 판정*이 아니라 **미판정 상태의 정직한 표기**다 — 둘을 섞어 적지 않는다.

---

## §6. 후속

| 태스크 | 몫 |
|---|---|
| `EOS-10` | `LearnerState` 단일 조회 표면 — 이 계약의 첫 배선 지점 |
| `EOS-12` | `Assessment` Evidence 3종 묶음 계약 — §3-1 판정의 소비자 |
| `EOS-13` | `update_mastery(state, evidence)` 호출 계약 |
| `EOS-14` | `recommend(state, context)` 호출 계약 — `Recommendation`의 `no_seat` 상태를 전제로 설계 |
| `EOS-101` | 순환 탐지 3벌 통합 판정(§2-1 정직한 공백) |

---

**작성**: 2026-09-16 · `EOS-100-learning-loop-relation-contract` · 판정 기준 main `c4f8c9fb`
