# ADR 계열 규약 — `docs/architecture/adr/`

> **결정일 2026-09-05 (Kiki) · 게이트 `G-eos-adr-numbering-series`의 판정**

## 규칙 3줄

1. **ADR 번호 계열은 이 디렉터리 하나뿐이다.** 다른 계열(`EOSADR-00n` 등)을 만들지 않는다.
2. **새 ADR은 다음 빈 번호를 받는다** — 고르는 법은 아래 §"번호를 고르는 법"(작업 트리 `ls` 금지).
3. **계획서의 "ADR-001~010"은 번호가 아니라 결정해야 할 *주제 목록*이다.** 그 번호를
   저장소 파일명으로 쓰지 않는다 — 아래 매핑표로만 연결한다. **계획서가 둘(100 §3.16 · 200 §31)이고
   주제 목록이 서로 다르므로 매핑표도 둘이다** — 계획서끼리도 번호로 대조하면 안 된다.

## 왜 이 규칙인가

계획서 100 §3.16은 ADR-001~010을 지정하는데, 저장소는 이미 ADR-001 = 이벤트 저장소,
ADR-002 = 학생 풀이 단계 엔티티로 번호를 썼다. 계획서 번호를 그대로 채택하면 **같은 번호가 두
주제를 가리킨다** — 태스크 번호에서 세 번 겪은 HARN-10/38과 같은 유형의 사고다
(`eos_source_docs_gap_review_2026-08-31.md` §7.3-④).

기존 2건을 개명하는 안은 기각했다: 코드·테스트·alembic·백로그에 걸친 `ADR-002` 참조 12건 이상이
파손된다(`grep -rn "ADR-002"` 실측).

---

## 번호를 고르는 법 — `ls`로 고르지 말 것

**기계가 판정한다** (HARN-66). 다음 빈 번호를 물어보고, 충돌이면 거부당한다:

```bash
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
python3 scripts/harness/adr_number_check.py
```

정상이면 `✔ … 다음 빈 번호: ADR-00N`을 출력하고, 같은 번호가 서로 다른 문서를 가리키면
충돌한 양쪽과 각각이 사는 브랜치를 지목하며 exit 1로 거부한다. 이 검사는 CI
`harness-integrity` 잡에서도 돌므로, 충돌한 번호는 머지되지 않는다.

**스캔이 성립하지 않으면(원격 조회 실패·대상 0건) 통과가 아니라 exit 1이다** — "0건 통과"로
위장되면 그것은 보호가 아니다.

**작업 트리의 `ls docs/architecture/adr/`는 다음 빈 번호를 알려주지 않는다.** 그것은 "trunk에
무엇이 있는가"만 말하며, 장기 미머지 브랜치가 수십 개인 이 저장소에서 trunk는 실제 진척을 점점
덜 대표한다(CLAUDE.md "trunk 부재를 미구현으로 단정 금지").

> **사고 경위 (2026-09-05 — 이 규칙이 생긴 이유)**: 이 README를 만든 그 세션이 `ls`로 "다음 빈
> 번호 = 003"을 골라 `ADR-003-subject-contract-v1-provisional.md`를 만들었다. 실제로는
> `origin/claude/entity-model-freeze-lji37v`가 같은 날 **15:45**에
> `ADR-003-subject-prefix-is-convention-not-entity.md`를 선점했고, 그 세션의 커밋은 **16:58**로
> 나중이었다 — **번호 충돌을 막으려고 만든 문서가 번호 충돌을 하나 더 만들었다.** ADR-004로
> 개명해 상환했다.
>
> **대비가 요점이다**: 같은 세션에서 *태스크* 번호는 `backlog.py add`가 원격 claim까지 검사해
> `EOS-83` 충돌을 잡아 **거부**했다. *ADR* 번호는 그런 CLI가 없어 눈으로 골랐고 뚫렸다. 규칙이
> 아니라 **집행 장치의 유무**가 갈랐다 — 기계 검사는 `HARN-66`으로 등재했다.

---

## 현재 계열 (2026-09-16)

| 번호 | 주제 | 상태 | 소재 |
|---|---|---|---|
| [ADR-001](./ADR-001-event-storage-postgresql-first.md) | 이벤트 저장소 PostgreSQL 우선 | 채택 | main |
| [ADR-002](./ADR-002-student-solution-step-entity.md) | 학생 풀이 step = 별도 정규 엔티티 | 채택 | main |
| [ADR-003](./ADR-003-subject-prefix-is-convention-not-entity.md) | 노드 ID의 과목 접두사는 규약이지 Subject 엔티티 참조가 아니다 | 채택 | main |
| [ADR-004](./ADR-004-subject-contract-v1-provisional.md) | Subject Contract v1 잠정 · 교차과목 프로브 후 Freeze | **Provisional** (target 2026-09-27) | main |
| [ADR-005](./ADR-005-ai-gateway-single-router-seam.md) | AI Gateway = L3 라우터 단일 경유 · 3축 라우팅 · 개방 포트폴리오 · 불변 검증 계약 | 채택 (기존 결정의 정본화) | main |
| [ADR-006](./ADR-006-learning-state-machine-without-stored-state.md) | 학습 상태 머신 8상태 채택 · 상태를 저장하지 않고 전이 원장에서 파생 | 채택 (2026-09-03 보류의 번복 · 게이트 판정 ②) | main |

**다음 빈 번호: ADR-007** — 쓰기 전에 위 §"번호를 고르는 법"의 스캔을 돌릴 것.

---

## 계획서 100 §3.16 주제 ↔ 저장소 문서 매핑

**빈 칸은 "확인하지 않았다"는 뜻이다. 추측으로 채우지 않는다.**

| 계획서 주제 | 저장소 문서 | 상태 |
|---|---|---|
| ADR-001 EOS Core Boundary | `docs/architecture/eos_core_adapter_boundary.md` + `scripts/analysis/eos_core_adapter_boundary_scan.py`(`BOUNDARY_MAP`) | 충족 — ADR 형식은 아니나 556모듈 전수 배정으로 결정 내용이 정본화됨(EOS-65 done) |
| ADR-002 Subject Adapter | [ADR-004](./ADR-004-subject-contract-v1-provisional.md) | 오늘 작성 — Provisional |
| ADR-003 Entity ID | [ADR-003](./ADR-003-subject-prefix-is-convention-not-entity.md) | 주제 일치 확인 — 노드 ID 접두사 규약 축 |
| ADR-004 Event Model | | 미확인 |
| ADR-005 LearnerState | [ADR-006](./ADR-006-learning-state-machine-without-stored-state.md) (학습 국면 축) + `l2/learner_state.py`(요약 상태 조립기 축) | **부분** — 학습 *국면*의 상태·전이 계약은 ADR-006이 덮는다. 요약 LearnerState의 단일 조회 표면·영속 좌석은 `EOS-10`·`EOS-103`이 소유하며 아직 ADR 형식의 기록이 없다 |
| ADR-006 Content Version | | 미확인 |
| ADR-007 AI Gateway | [ADR-005](./ADR-005-ai-gateway-single-router-seam.md) | 충족 — 기존 결정의 정본화(ARCH-45). 주제의 실질(`l3/router.py`·`03a_l3_router_design.md`)은 이미 있었고 ADR 형식의 단일 기록만 없었다 |
| ADR-008 Knowledge Graph | | 미확인 |
| ADR-009 Assessment Architecture | | 미확인 |
| ADR-010 Math AST | | 미확인 |

**왼쪽 번호는 계획서의 것이고 오른쪽 파일명의 번호는 저장소의 것이다 — 둘은 무관하다.**

계획서 ADR-002(Subject Adapter)가 저장소 ADR-004에 있고, 계획서 ADR-003(Entity ID)이 저장소
ADR-003에 있는 것은 **우연**이다(후자는 두 계열이 같은 번호에서 우연히 만난 경우다).

**검색 범위 명시(부재 판정 절차)**: "미확인" 6칸은 *조사하지 않았다*는 뜻이지 *대응 문서가
없다*는 뜻이 아니다. 채워진 4칸은 각각 실측(`eos_source_docs_gap_review_2026-08-31.md` §7.3-④·§319
인용, 원격 브랜치 파일 실측)에 근거한다. 계획서 100 원본은 Kiki 보유이며 저장소에 반입돼 있지
않다(`grep -rln "계획서 100"` = 인용 문서 6건, 원본 0건).
---

## 계획서 200 §31 주제 ↔ 저장소 문서 매핑

**위 표(계획서 100 §3.16)와 주제 목록이 다르다 — 덧쓰지 않고 별도로 둔다.** 200은 Entity
Versioning·Curriculum Mapping·Concept/Skill separation·Problem/Answer·Misconception Model을
갖고, 100은 AI Gateway·Math AST·Knowledge Graph·Content Version·Assessment Architecture를
갖는다. 두 계획서의 `ADR-00n`은 **서로 다른 주제**를 가리키므로 번호로 대조하면 안 된다.

**작성 근거**: 2026-09-16 Kiki가 계획서 200 원본(docx)을 세션에 반입해 항목별 대조를 지시했고,
그 재대조(`docs/reviews/eos_phase1_plan_200_reverify_2026-09-16.md` §5 · 판정 기준 main
`2520a27c`)가 10주제 전건의 저장소 정본을 실측했다. 위 100 §3.16 표의 7칸이 비어 있는 사유
("계획서 100 원본 미반입")는 **여전히 유효하다** — 반입된 것은 200이지 100이 아니다.

| 계획서 200 §31 주제 | 저장소 정본 | 상태 |
|---|---|---|
| ADR-001 EOS Core Boundary | `docs/architecture/eos_core_adapter_boundary.md` + `scripts/analysis/eos_core_adapter_boundary_scan.py`(`BOUNDARY_MAP` 64항목) | 충족 — ADR 형식은 아니나 전수 배정으로 정본화(`EOS-65`) |
| ADR-002 Entity ID Strategy | `docs/standards/eos_identity_layer_011_1_decision.md` + [ADR-003](./ADR-003-subject-prefix-is-convention-not-entity.md) | 충족 — 2026-08-17 판정(부분 수용·부분 거부) + 접두사 규약 |
| ADR-003 Entity Versioning | `docs/architecture/44_eos_version_management.md` + `schema/version_header.py`(`VersionStatus` 6종) | 충족 — `EOS-44`(설계)·`EOS-49`(`concept_version` 착지) |
| ADR-004 Subject Contract | [ADR-004](./ADR-004-subject-contract-v1-provisional.md) | **Provisional** — 9/27 Freeze 판정 대기 |
| ADR-005 Curriculum Mapping | `docs/architecture/eos_curriculum_semantic_backbone_adr.md` | 충족 — Overlay 방식(개념 백본 위에 Framework/Version/Alignment 레이어) |
| ADR-006 Concept/Skill separation | `docs/architecture/canonical_entity_model_v1.md` §1-5·§1-6 | 충족 — 이다/아니다 쌍으로 판정 가능하게 정의 |
| ADR-007 Problem/Answer Contract | `docs/architecture/adr_answer_form_contract.md` + `schema/answer_form.py` | 충족 — `EOS-28` |
| ADR-008 Misconception Model | `docs/standards/crosswalk_gate_contract.md` + `04b`/`04c`/`04e` | 충족 — kebab↔M-id 승인·적재 게이트가 코드 동결 |
| ADR-009 Event Architecture | [ADR-001](./ADR-001-event-storage-postgresql-first.md) + `schema/event_data_contract.py` | 충족 — 저장소 선택 + payload 계약 단일 진실원 |
| ADR-010 Learner State | `docs/architecture/evidence_layer_boundary.md`(`EOS-79`) + `docs/architecture/02_learner_model.md` | 충족(정본) · **집행 없음**(문서 §3이 스스로 명시) |

**10주제 전부 저장소 정본이 실재하므로 새로 쓸 ADR은 없다.** 계획서가 "작성할 가치가 크다"고
한 10건은 ADR 파일이 아닌 형태(경계 문서·표준 문서·계약 모듈·동결 테스트)로 이미 결정돼 있다.
이 표는 **그 대응을 기록하는 것이지 새 ADR을 예약하는 것이 아니다** — 위 §"번호를 고르는 법"의
다음 빈 번호는 이 표와 무관하다.



---

## 새 ADR 쓸 때

```bash
# 1. 위 §"번호를 고르는 법"의 원격 스캔으로 다음 빈 번호 확인
# 2. docs/architecture/adr/ADR-00N-<주제-슬러그>.md 작성
# 3. 이 README의 "현재 계열" 표에 1행 추가 + "다음 빈 번호" 갱신
# 4. 계획서 주제에 대응하면 매핑표 오른쪽 칸도 채운다 (대응이 불확실하면 비워 둔다)
```

문서 상단에 `상태`(초안/Provisional/채택/폐기)·`결정일`·`대상`·`관련`을 적는다 —
ADR-001·002·004가 그 형식이다.
