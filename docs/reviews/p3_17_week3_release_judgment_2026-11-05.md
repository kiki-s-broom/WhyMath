# P3-17 — Week 3 + Phase 3 Release 통합 판정 (2026-11-05)

> **판정 기준: main `036286a1`** (`036286a1bf41a4ce674d322a0ba34b8cf0409f09` · "EOS-194 ③ 충족 … (#1842)")
> **대상 게이트**: `G-p3-w3-release-merged` (decision · assignee kiki)
> **성격**: 판정 전용 회차(acceptance ②). production code 변경 0. 발견한 결함은 태스크 등재만 했다(P3-100·P3-101·P3-102).
> **실행 환경**: 클라우드 세션 · Python 3.13(CI는 3.12) · 로컬 PostgreSQL 16 + pgvector(CI와 같은 `alembic upgrade head` 뒤 실행).
> 운영 DB(Kiki 머신 `whymath-pg`) 값은 이 세션이 직접 재지 못했다 — 인용한 운영 값은 전부 출처 판정문·커밋을 함께 적었다.

## 최종 판정

**FAIL**

- (가) Week 3 축: **FAIL** — AI 품질 8종 중 6축의 임계값이 아직 "제안값(Kiki 확인 전)"이고, 판정 대상인 "LLM이 쓴 문장"의 표본이 0건이다.
- (나) Phase 3 Release 축: **FAIL** — Gate A·B·C 미충족(D·E 충족), 성공 기준 Q1·Q2 NO(Q3 YES).

한 축이라도 FAIL이면 최종은 FAIL이다(acceptance ③). 조건부 PASS는 없다.

---

## 1. 이번 회차에 직접 실행한 것

| 명령 | 결과 |
|---|---|
| `python -m whymath_backend.ops.phase3_metrics --no-db` | exit 2 · 충족 3 · 미달 1 · 미측정 3 |
| `python -m whymath_backend.harness.ai_quality_eval --self-test` | exit 0 · 8/8 축 주입 반응 |
| `pytest` 13개 파일(Gate A·C·D·Week 3 근거, 실 PG, `WHYMATH_RUN_INTEGRATION=1`) | exit 0 · **287 passed · skip 0** |
| `pytest` 어댑터·의존 방향 5개 파일(Q3·Gate E 근거) | exit 0 · 115 passed |
| `lint-imports` (src/backend) | exit 0 · Contracts 4 kept, 0 broken |
| `python scripts/constitution/audit_ratchet.py` | exit 0 · 차단 0건 ≤ 기준선 0건 |
| `python -m alembic upgrade head` → `ops.integrity_violations_gate` | 둘 다 exit 0 |

13개 파일: `test_e2e_three_consecutive_loops` · `test_p11_five_stage_loop_chain` · `test_week1_gate_no_learner_writes` · `test_week2_gate_wrong_answer_propagation` · `test_week3_gate_remediation_loop` · `test_e2e_persona_journeys` · `test_admin_cms_problem_versions_integration` · `test_published_problem_edit_guard_integration` · `l3/test_publish_gate_integration` · `scenarios/test_gate_d_event_role_census` · `infra/test_llm_state_authority_boundary` · `infra/test_tutor_output_schema_gate` · `harness/test_wh1_tutor_output`.

## 2. (가) Week 3 축 — FAIL

| 조건 | 판정 | 근거 | 끊긴 지점 · 남은 작업 | 소유 |
|---|---|---|---|---|
| AI 품질 8종 — 합의된 기준 충족 | **FAIL** | `harness/ai_quality_judges.py` AXIS_SPECS: 8축 중 6축(수학적 정확성 0.05 · 정답 누설 0.05 · 힌트 0.90 · 설명 일관성 0.90 · 학생 수준 0.90 · hallucination 0.05)의 `threshold_basis`가 "제안값(Kiki 확인 전)". 재사용 KPI 2축(오개념 판정 0.85 · Curriculum 0.92)만 확정. P3-78 라이브 측정(`docs/reviews/p3_78_ai_quality_live_run_2026-10-31.md`): LLM 저자 발화가 학생 본문으로 나간 경우 **0/244**. D16(2026-10-31·11-01 Kiki): 판정 대상 = 문장 축 6개의 "LLM이 쓴 문장", 임계값은 P3-94 초안 분포를 보고 정한다. | 측정 경로(LLM 초안 저장 + 문장 6축 평가)가 없다 → 표본 0 → 합의된 기준 자체가 아직 없다. 남은 작업: P3-94 구현(중) + 라이브 1회차(Kiki 머신) + 임계값 6개 Kiki 결정 | **P3-94**(todo) |
| 평가 도구 반증력 | 충족 | `ai_quality_eval --self-test` exit 0 · 8/8 축 주입 반응 | — | P3-10(done) |
| LLM이 학습 상태를 못 바꿈(재확인) | **충족** | `test_llm_state_authority_boundary` · `test_tutor_output_schema_gate` · `test_wh1_tutor_output` 통과(위 287건 안). P3-09 `mastery_update_allowed: Literal[False]` | — | P3-09 · ARCH-59(done) |

## 3. (나) Phase 3 Release 축 — FAIL

### Gate A — 학생 폐쇄루프: FAIL

정의(`docs/strategy/phase3_math_eos_completion_plan_source.md` §Gate A · D2로 내부 테스트 계정): 진단 → 추천 → 학습 → 문제 → 답안 → 채점 → 오개념 → Hint/Tutor → Mastery Update → Next Recommendation을 사람의 DB 수정 없이.

- 단계를 덮는 테스트는 모두 통과했지만 **10단계를 한 번에 잇는 실행은 저장소에 없다.** 조각별 커버리지(파일 안 호출 수 실측):
  - `test_e2e_three_consecutive_loops`: 진단·추천·문제·답·채점·오개념·보정·숙달·다음 추천 — 힌트/튜터 0 · 학습(`/study`) 0
  - `test_week3_gate_remediation_loop`: 코치(`/v1/coach/sessions`) 포함
  - `test_e2e_persona_journeys`: 진단 → 학습(`/study`) 화살표
- **끊긴 단계 = 학습.** `test_e2e_persona_journeys`(1174~1181행 docstring + ④-b 단언)가 동결한 현행: `/v1/me/objectives/{id}/study`는 409를 넘지만 `supply()`가 개념 DSL을 못 찾아 **404**. 저장소에서 `/study` 201에 닿는 테스트는 전부 `supply()`를 대역으로 바꾼다. 게다가 개념 콘텐츠 학생 공급은 KG-02 보류(2026-10-15 Kiki)로 reviewed 0건이 의도된 상태다.
- 남은 작업: PED-17(학습 공급 폴백 결정·구현, 중) + 10단계 관통 하네스(P3-101, 소~중). 학습 단계는 KG-02 보류를 그대로 두면 "생성 폴백" 경로로만 열린다 — 그 판단이 PED-17 ①이다.
- 소유: **PED-17**(todo) · **P3-101**(신규 등재).

### Gate B — 콘텐츠: FAIL

`phase3_metrics --no-db`(main `036286a1`) 실측:

| 지표 | 값 | 목표 | 판정 |
|---|---|---|---|
| ① Curriculum Coverage | 10/10 = 100% | ≥98% | 충족 |
| ② Concept Completeness | 저장소 측정 불가(hint 연결만 남음 · 나머지 4연결은 10/10 확정) | ≥95% | 운영 DB 기준 10/10으로 본다 — P3-32 Kiki 머신 실행(main `c4ef20c2` · `HINT_LINKED_CONCEPTS=10/10` · `LEAK_CHECK_OK=True`). 단일 CLI 실행이 아니라 두 측정의 조합이다 |
| ③ Problem Coverage | 8/8 = 100% | ≥95% | 충족 |
| ④ Solution QA Pass | 548/548 = 100% | ≥99.5% | 충족 |
| ④' 검증 가능 비율(D11 하한) | **548/1,121 = 48.9%** (검증 불가 573) | ≥55%(617/1,121) | **미달** |
| ⑤ Learning Loop Success | 측정 불가(`--no-db`) | — | 이 회차 미측정 |
| ⑥ Critical Defect | 측정 불가(payload 없음) | — | 이 회차 미측정 |
| ⑦ Graph Connectivity | **4/10 = 40.0%** | ≥95% | **미달** |

⑦ 끊긴 개념(D13 · acceptance ⑥) — 6개 모두 사유는 "오답 보기가 핵심 오개념에 닿는 문항이 없다":

| 개념 | 소유 태스크 |
|---|---|
| 12미적Ⅰ-02-01 | **P3-50**(todo) |
| 12미적Ⅰ-02-09 | **P3-52**(todo) |
| 12미적Ⅰ-02-05 · 02-06 · 02-08 · 02-10 | **P3-44**(in_progress) |

- 남은 작업: ⑦ — 95%는 10개 중 10개라 6개 전부 닫아야 한다(P3-44·50·52, 각 중). ④' — 69건 더 검증 가능해야 한다(P3-91 승격 + P3-93 잔여 VAR 해소. 허용 경로 안 구조적 상한 0.5575라 여유 0.75%p).
- 소유: **P3-44 · P3-50 · P3-52 · P3-91 · P3-93**.

### Gate C — 운영(수정 → QA → 승인 → Publish): FAIL

- **문항**: 표면은 있다. 실 PG 통합 테스트 통과 — CMS로 발행(시도에 판 고정) · 승인 뒤 라이브 변경 시 발행 422 · 재발행 시 포인터 이동 · 발행된 문항의 제자리 편집 409 · 폐기(deprecate) 뒤 편집 허용. 운영 DB 첫 발행 1건 실증(EOS-194 §5 · main `920cc624` · `EOS194_ACCEPTANCE3_OK=True`).
  - 끊긴 지점 ①: 운영 DB 노출 문항 979건 중 **903건이 발행 게이트를 지날 수 없다**(`NOT_PUBLISHABLE_REASONS={"misconception_signature": 903}` · EOS-194 §5). 이 문항들은 오류를 고쳐도 Publish 단계에 들어갈 수 없다. 소유 태스크가 없어 **P3-102** 등재.
  - 단서: "내용을 고친 뒤 새 판 발행"을 한 줄로 잇는 테스트는 없다(위 조각들의 조합으로 성립한다고 읽힌다 — 읽어서 그렇게 보인다). 문항 판 Rollback·Restore 없음(EOS-196 todo).
- **개념**: `l3/publish_gate.py` 모듈 docstring 30행 "이후 판(수정)은 기존대로 개념 행을 바꾸지 않는다(서빙 경로 미연결)". 개념 수정 발행이 학생 화면에 닿지 않는다. 대장 미완료 태스크 검색(서빙 경로 미연결 · 개념 판 서빙 · concept_version 서빙 · 수정판 학생 · 개념 수정 발행) 0건 → **P3-100** 등재.
- 남은 작업: P3-100(중~대 — 서빙 원천 전환) · P3-102(Kiki 결정 + 런북 실행).
- 소유: **P3-100 · P3-102**(신규).

### Gate D — 데이터: 충족(단서)

`scenarios/test_gate_d_event_role_census` 통과 — 8역할 전부 대응 이벤트 1건 이상. 단서: `concept_viewed`는 `concept_selected`로만 대응하고 `content_viewed` 생산자는 0건(P3-29 todo) · 코치 이벤트 session_id 귀속 없음(P3-30 todo). 둘 다 테스트가 현행 동작으로 동결해 고쳐지면 RED가 난다.

### Gate E — EOS Architecture: 충족

`lint-imports` 4 kept / 0 broken · 헌법 래칫 차단 0. "EOS Core → Math Adapter 금지(baseline 있음)" 계약의 `ignore_imports`는 ADAPTER 출발(구조적 제외 — 위반 아님)과 MIXED 출발 8건(`api.verify`·`api.speech`·`api.ocr`·`api._ocr_state`·`l4.speech`)이다. 새 침투는 없다.

### 성공 기준 3문항

| 문항 | 답 | 근거 |
|---|---|---|
| Q1 100명을 넣어도 개발자가 학생별 데이터를 안 만지고 학습이 돈다 | **NO** | Gate A의 학습 단계가 404로 끝난다(PED-17). 튜터는 θ 조회 실패 시 턴 전체가 실패한다(P3-85 todo). 문면의 "실제 중·고등학생 100명"은 D2가 Gate A 줄에만 계정 종류를 바꿨고 이 문항은 바뀌지 않았다 — 학생 참여는 ARCH-66 ⑥으로 12/31 이후라 문면 그대로는 이 회차에 YES가 될 수 없다 |
| Q2 콘텐츠 오류를 배포 없이 운영자가 수정·검수·배포 | **NO** | Gate C — 개념 수정 발행이 서빙에 닿지 않고(P3-100), 운영 문항 903/979가 발행 게이트를 못 지난다(P3-102) |
| Q3 Physics를 붙일 때 Core를 다시 뜯지 않는 구조 | **YES** | Gate E 근거 + `test_subject_adapter_physics_stub`(필수층 3메서드를 물리로 구현해 Protocol 만족) 통과. 단서: 필수층 Core 호출자는 0건이라 "사용으로 시험된" 중립성은 아니다(ARCH-41 기록) · MIXED 표면 8건은 과목별 분할이 남아 있다 |

## 4. 기록

- 게이트: `gates amend G-p3-w3-release-merged --verdict FAIL` — 근거 = 이 판정문 · main `036286a1`. 소유 태스크 연결: 기존 입력 P3-93·P3-94에 더해 P3-44 · P3-50 · P3-52 · P3-91 · PED-17 · P3-100 · P3-101 · P3-102.
- 하류: `G-internal-completion-2026-12-31` 조건 ①(Phase 3 Release Gate A~E PASS)이 이 게이트를 입력으로 건다 — 이 FAIL로 ①은 현재 미충족이다.

## 5. 확인하지 못한 것

- 운영 DB 값(내부 테스트 계정 수 · ⑤ Learning Loop · 힌트 연결 재측정)은 이 세션에서 다시 재지 못했다. ②는 11/03 운영 실측을 인용했다.
- ⑥ Critical Defect는 payload 수집기가 없어 미측정이다(CLI 한계로 명시됨).
- CI 3.12가 아니라 로컬 3.13에서 돌렸다. 판정 근거 테스트는 CI `backend-integration` 잡이 마커로 수집하는 파일이다.
