판정 기준: main f2a7b2ca

# P3-08 — 튜터 context 9종의 정직한 매니페스트 (2026-10-20 · PR #1705 검토 반영 개정)

- 태스크: `P3-08-tutor-context-builder` · 브랜치 `claude/p3-08-tutor-context-builder` (claim 6410c374)
- 커밋: 1차 cfe2233c · 247d26a4 → 검토 반영 2425f7d9 · d83f56f7 · 이 보고서 개정
- 지시 원문: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [12] P3-08 (1275–1283행)
- 산출 코드:
  - `src/backend/whymath_backend/harness/wh1_tutor_context.py`(신규 — 판정기·영수증)
  - `api/coach.py` · `harness/wh1_primary.py` · `harness/wh1_llm_policy.py` · `harness/wh1_shadow.py`
  - `l2/skill_mastery_tracking.py`(공개 래퍼 1개)
  - `scripts/analysis/eos_feature_inventory_v2.py`(WM-E-704에 모듈 귀속)
- 테스트: `tests/backend/harness/test_wh1_tutor_context.py`(55) · `tests/backend/api/test_coach_tutor_context.py`(53) · `tests/backend/harness/test_wh1_shadow.py`(레코드 허용 목록 +3)
- 승계 태스크: `P3-72`(슬롯 값 전달) · `P3-73`(Langfuse 기록) · `P3-74`(필수 누락 fallback)
- 새 Entity·스키마·Alembic 변경 0 · 새 Agent 0 · 응답은 필드 추가만(하위호환)

## 0. 결론 — 부분 충족

**부분 충족이다.** acceptance ②④는 충족했다. ①⑤는 "조회·표기"까지만 했고, 튜터에 실제로 실어 보내는 일은 승계 태스크 `P3-72`로 넘겼다.

| acceptance | 판정 | 근거 |
|---|---|---|
| ① 9종 context가 채워진다 | **조회·표기까지** | 9종 모두 슬롯마다 `resolved`(값을 얻었는가)와 `delivered_to_tutor`(튜터 정책 입력에 실제로 실렸는가)를 따로 판정한다. 튜터에 실제로 실리는 것은 학생 답안·풀이 기록·활성 가설·θ 4종뿐이다. 금지모드 가드가 켜지면 교수법 팩이 더해진다. 개념·스킬·숙달·문제 내용은 얻어도 `not_delivered`로 표기한다. 값 전달은 학생 데이터를 클라우드 LLM에 보내는 문제라 개인정보 판단(Kiki)이 필요하다 → `P3-72` |
| ② 누락 시 조용히 진행하지 않는다 | **충족** | 응답·로그·튜터 프롬프트 요약·관측 레코드 네 곳에 누락과 미전달이 표기된다. 완비 턴에서도 미전달 5종이 드러난다 |
| ③ depth ≤ 2·max_nodes·preload 금지 | **충족(기존 가드 동결)** | §5 |
| ④ 하나씩 비우는 주입 변별력 | **충족** | 주입 9건 × 두 핸들러와 대조군을 테스트했다. 표기를 지우는 뮤테이션 29종은 전부 RED였다(§4) |
| ⑤ 9종이 채워지고 누락이 무증상으로 지나가지 않음 | **후반만 충족** | 누락·미전달이 무증상으로 지나가는 경로는 0이다. "튜터에 채워짐"은 `P3-72` |

1차 보고(247d26a4)는 "완료 판정 충족"이라고 적었다. 그 근거였던 `filled=True` 표기는 **거짓**이었다. 개념·스킬·숙달·문제 내용·팩(가드는 기본 OFF)은 튜터 정책에 전달되지 않는데도 채워졌다고 표기했다(검토 상1). 이번 개정에서 `resolved`와 `delivered_to_tutor` 두 축으로 나눠 바로잡았다.

## 1. 9종 실측표 — 변경 전(main f2a7b2ca) 코드 경로별

튜터 = WH-1 primary(`harness/wh1_primary.py::run_wh1_primary_turn`, 기본 ON). 서빙 경로에서 LLM을 부르는 유일한 튜터 좌석이며, `api/coach.py::_wh1_primary_decision_or`가 호출한다. stateless `POST /v1/coach`는 튜터를 부르지 않으므로(LLM 0·DB 0) 범위 밖이다.

| # | 슬롯 | 핸들러가 이미 조회하던 원천 | 튜터 정책 입력 | 비었을 때(변경 전) |
|---|---|---|---|---|
| 1 | 학생 상태 | `_server_theta_for`(θ) · `_grade_for`(학년) | θ만 | `theta=0.0` 콜드스타트로 표기 없이 진행 |
| 2 | 현재 Concept | `get_primary_concept_id`(숙달·팩·θ·성취기준·선수 조회 안에서 재해석) | ✗ | DEBUG 로그뿐 |
| 3 | 현재 Skill | 코치 경로 조회 0 | ✗ | 조회 자체가 없음 |
| 4 | 문제 | `body.problem_id` / `dialogue.problem_id` | id만 관측 레코드에(내용 ✗) | 표기 없음 |
| 5 | 학생 답안 | `student_solution or student_input` | ✓ (정책 사적 보유) | 표기 없음 |
| 6 | 풀이 기록 | `solution_steps` | ✓ (정책 사적 보유) | 표기 없음 |
| 7 | 추정 Misconception | `_apply_hypotheses` 반환 가설 | ✓ (초기 가설·프롬프트 요약) | 빈 배열만 보임 |
| 8 | Mastery | `_server_mastery_for` · 클라 `bkt_mastery`·`mastery_level` | ✗ (결정론 `decide`만 소비) | 표기 없음 |
| 9 | Pedagogy Policy | `_pack_for`(교수법 팩) | 금지모드 가드에만(기본 OFF) | 표기 없음 |

## 2. 변경 후 — 판정과 집행 지점

### 2.1 두 축

- **`resolved`** — `api/coach.py::_tutor_context_for` → `build_tutor_context_manifest`가 판정한다(순수 함수, DB 0). 값을 채우지 않는다. 못 얻었으면 원인 코드를 하나 붙인다:
  - `not_supplied` — 학생이 아직 내지 않음
  - `no_problem_context` — 문항 없는 대화
  - `none_detected` — 조회했지만 오개념 의심 없음
  - `no_history` — 콜드스타트
  - `coverage_gap` — 미매핑·팩 미보유 단원
  - `source_disabled` — 플래그 OFF
  - `lookup_failed` — 조회 예외
- **`delivered_to_tutor`** — 핸들러가 추정하지 않는다. 러너가 **정책을 만든 뒤** 다음 세 가지에서 계산해 `TutorDeliveryReceipt`로 돌려준다(`wh1_primary._delivered_slots`):
  - 정책 객체가 실제로 보유한 값(`LLMTutorPolicy.delivered_context_slots` — 사적 `student_text`·단계·θ를 0.0으로 채우지 않고 받았는지)
  - `run_tutoring_turn`에 넘긴 바로 그 초기 가설 목록
  - 금지모드 가드에 넘길 팩
- 정책은 이제 `theta=None`을 받는다. 콜드스타트 0.0은 그대로 쓰되(동작 불변) '모름'을 기록한다.

### 2.2 표기 네 곳 — 같은 판정에서 나온다

1. **응답** `tutor_context`:
   - 필드: `tutor_invoked` · 슬롯별 `resolved`/`delivered_to_tutor`/`size`/`cause` · `missing` · `not_delivered` · `complete`
   - **값은 없다.** 숙달·θ 수치(slice 69/70 비노출), 개념/스킬 id, 답안 길이(`student_answer.size=null`), 예외 타입명(`cause_detail` 좌석 자체를 제거)이 모두 빠진다. 예외 타입명은 조회 좌석의 서버 로그에만 남는다.
2. **로그** 1줄(`whymath.harness.wh1_tutor_context`):
   - 형식: `슬롯(원인)` + 미전달 슬롯명
   - `슬롯=원인` 형식은 루트 PII 스크러버가 `student_answer=…`를 마스킹해 표기가 지워진다(실측). 그래서 괄호 형식으로 쓰고 스크러버 통과를 테스트로 동결했다.
3. **튜터 프롬프트 요약** — `context_missing`·`context_not_delivered`(슬롯 이름만, 예산 절단 대상 아님). 시스템 프롬프트에 두 키를 설명하는 1줄을 추가했다("아는 것처럼 추측하지 마세요"). 이 때문에 누락 없는 턴의 바이트 동일 원칙은 깨졌다(허용됨). 대신 `coach_prose_leak_eval`·`pedagogy_pack_fidelity_eval` 게이트를 다시 돌려 exit 0을 확인했다(§6).
4. **관측 레코드** — `context_missing`·`context_not_delivered`·`context_coverage_gap`. None은 구판, `[]`는 0건이다. 정상·예산 소진·프로즈 거부·타임아웃 중단 레코드 모두에 실린다.

### 2.3 튜터 미호출 턴(검토 중2)

완료 상태머신이 가로챈 턴(`completion.handled`)과 primary OFF 턴은 `tutor_invoked=false`로 표기하고 전달은 0으로 둔다. 판정은 "튜터가 받을 수 있었던 것"의 기록으로 남기고, **WARNING은 내지 않는다**(INFO 표기만).

### 2.4 로그 등급(검토 중4)

**WARNING은 시스템 결함(`source_disabled`·`lookup_failed`)이 있고 튜터를 실제로 부른 턴에만** 낸다. 콜드스타트(`no_history`)와 커버리지 공백(`coverage_gap`)은 INFO다. 이 둘은 운영 턴 대부분에 해당하는 정상 상태이므로 WARNING으로 올리면 상시 경보가 되어 진짜 결함이 묻힌다. 커버리지 공백은 관측 레코드의 `context_coverage_gap`으로 집계한다.

### 2.5 새 조회의 트랜잭션 안전(검토 하7)

개념·스킬 조회 2건은 **SAVEPOINT**(`session.begin_nested()`) 안에서 돈다. 선례는 `l2/learning_session_writer.py`다. DB 예외가 나도 바깥 PG 트랜잭션이 aborted 상태가 되지 않고, never-break로 흡수한 뒤 타입명만 로그에 남긴다. 새로 추가한 경고에는 `exc_info`를 붙이지 않는다(하8).

## 3. 누락 처리 정책 — "진행하되 표기"

**선택: 누락·미전달이 있어도 튜터 호출과 코칭을 그대로 진행하고, §2.2의 네 곳에 반드시 표기한다.** 4xx 거부도, 필수 누락 시 LLM 생략도 택하지 않았다. 학생에게 정답을 바로 주지 않는 동작은 바뀌지 않는다.

근거:

1. **누락의 대부분이 정당한 학생 상태다.** 첫 진입·텍스트 턴·의심 없음·문항 없는 대화가 그렇다. 거부하면 정상 학습 흐름이 깨진다.
2. **안전 게이트는 슬롯 값에 기대지 않는다.** verify 의무·정답 억제 백스톱·톤필터·금지모드 가드는 슬롯이 비어도 그대로 강제된다.
3. **LLM 프롬프트에는 슬롯 값이 들어가지 않는다.** 그래서 "빈 값을 넣어 LLM을 부르는" 경로가 구조적으로 없다. 남는 문제는 LLM이 무엇이 없는지 모르는 것이고, `context_missing`·`context_not_delivered`가 그 공백을 메운다.

지시문 3항("필수 누락 시 명시 fallback")은 어떤 슬롯을 필수로 볼지라는 정책 선택이 남아 있어 `P3-74`로 넘겼다. 판정 좌석(`manifest.status_of`)은 이미 한 곳에 있다.

## 4. 주입·뮤테이션 결과 (exit code 판정)

### 4.1 주입 9건 × 2핸들러 (HTTP — 실제 튜터 러너 + 스텁 provider)

주입마다 네 가지를 단언했다. 주입이 실제로 적용됐는지(mutated ≠ original)도 단언했다.

1. 201로 진행한다.
2. 응답 `missing`에 해당 슬롯(연쇄 포함)이 있고, 그 슬롯은 `resolved=false`·`delivered=false`·원인 코드를 가진다.
3. 로그 1줄에 `슬롯(원인)`이 INFO로 남는다.
4. 튜터 러너가 받은 매니페스트에도 같은 누락이 있다.

| 주입 | 기대 누락 · 원인 | create | append |
|---|---|---|---|
| 학생 상태(θ 없음) | learner_state · no_history | GREEN | GREEN |
| 개념 미매핑 | concept·skill · coverage_gap | GREEN | GREEN |
| 스킬 미매핑 | skill · coverage_gap | GREEN | GREEN |
| 문제 없음 | problem(not_supplied)·concept·skill·mastery·pedagogy_policy | GREEN | GREEN |
| 학생 답안 없음 | student_answer · not_supplied | GREEN | GREEN |
| 풀이 기록 없음 | solution_record · not_supplied | GREEN | GREEN |
| 가설 0 | misconception · none_detected | GREEN | GREEN |
| 숙달 없음 | mastery · no_history | GREEN | GREEN |
| 팩 없음 | pedagogy_policy · coverage_gap | GREEN | GREEN |

대조군(9종 완비)은 두 핸들러 모두 다음과 같았다:

- `complete=true`, `tutor_invoked=true`
- 전달 = {학생 상태, 학생 답안, 풀이 기록, 오개념}
- `not_delivered` = [concept, skill, problem, mastery, pedagogy_policy]
- INFO 로그 1줄
- 응답 매니페스트가 러너 영수증과 바이트 단위로 같다

### 4.2 뮤테이션 29종 (백업 → 적용 단언 → 실행 → sha256 원복 단언)

| 축 | 뮤테이션 | 결과 |
|---|---|---|
| 배선 A | 답안을 `student_input`만으로 읽음 | RED |
| 배선 B | 답안을 `student_solution`만으로 읽음 | RED |
| 배선 C | 개념 조회 예외를 '매핑 없음'으로 뭉갬 | RED |
| 배선 D·E·F | `theta_enabled`·`mastery_enabled`·`pack_enabled`를 True 상수로 | RED·RED·RED |
| 배선 G | `mastery_level` 경로 제거 | RED |
| 전달 H | 정책에 학생 답안을 넘기지 않음(**전달 경로** 뮤테이션) | RED |
| 전달 I | 전달 판정 위조(개념을 전달됨으로) | RED |
| 전달 J | θ 콜드스타트를 전달됨으로 셈 | RED |
| 전달 K | 전달 판정에 다른 가설 객체를 씀 | RED |
| 전달 L | 가드 OFF인데 팩을 전달됨으로 셈 | RED |
| 전달 M·N | 미호출 턴에도 영수증 사용 · 응답에 영수증 대신 사전 매니페스트 | RED·RED |
| 표기 O·P·Q | 프롬프트 `context_not_delivered` 제거 · 프롬프트 공개 호출 제거 · 레코드 미기록 | RED·RED·RED |
| 등급 R·S·T | 커버리지 공백도 WARNING · 미호출 턴도 WARNING · 콜드스타트를 커버리지 공백으로 | RED·RED·RED |
| 1차 승계 U·V·W·X | 로그 호출 삭제 · 응답 필드 제거 · θ 없음을 있음으로 · 로그 `key=value` 형식 | RED×4 |
| 안전 Y·Z | SAVEPOINT 제거 · 새 조회 never-break 제거 | RED·RED |
| 가드 AA·AB·AC | 오개념 preload · 선수 traversal depth 3 · 웜스타트 상한 해제 | RED×3 |

- 결과: 29/29 RED. 적용·원복 단언도 29/29 통과했다.
- 하네스 결함 1건: 첫 실행에서 S의 치환 앵커가 black 재포맷 때문에 0건이 되어 주입이 **미적용**이었다. 하네스가 이를 실패로 셌다. 앵커를 고친 뒤 재실행해 RED를 확인했다.
- 지시문 5항 3종 RED와의 대응:
  - ① 필수 context 누락 → §4.1, A~G, U~W
  - ② token budget 초과 → `test_budget_guards_still_hold_with_disclosure`. 상한 자체의 뮤테이션은 기존 `test_wh1_llm_policy.py` 예산 테스트군이 소유한다.
  - ③ 오개념 preload → AA

## 5. depth / max_nodes / preload — 튜터 context 경로의 가드와 동결

| 경로 | 가드(기존) | 이번 동결 |
|---|---|---|
| 선수 traversal `_prerequisite_coaching_for` → `recommend_prerequisite_gaps` → `fetch_prerequisites` | `max_depth=1` | 서빙 경로가 이 좌석을 1회 타고 `1 ≤ max_depth ≤ 2`인지 확인(AB RED) |
| 웜스타트 탐색 표적 `assemble_warmstart_probe_hints` | `_DEFAULT_LIMIT=12` | 호출부가 상한을 풀지 않고 `12 ≤ 상한 ≤ 20`인지 확인(AC RED) |
| LLM 프롬프트 요약 `LLMTutorPolicy._build_prompt` | 노드 ≤ 20 · history ≤ 8 · 토큰 ≤ 3000 | 표기 키가 실려도 상한이 유지되고, 표기 키는 절단되지 않음 |
| 오개념 preload | 웜스타트 표적은 사적 probe 좌석 전용 | 프롬프트에 실리지 않음(AA RED). HTTP 경로에서 매칭 0이면 튜터가 받는 가설도 0 |
| 새 개념→스킬 조회 | — | 1홉이며 순회가 아니다. 값은 프롬프트에 실리지 않는다 |

ARCH-11(blocked)의 소유 범위는 건드리지 않았다. `query_curriculum`은 여전히 실제로 순회하지 않는다. 값 전달(`P3-72`)이 실제 순회를 만들면 그때 ARCH-11 가드가 동반돼야 하며, `P3-72` acceptance ③에 명시했다.

## 6. 검증 (exit code)

| 검사 | 명령 | exit |
|---|---|---|
| Ruff | `python -m ruff check . ../../tests/backend ../../tests/constitution` | 0 |
| Black | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| Mypy | `python -m mypy --strict whymath_backend` | 0 |
| Import contracts | `lint-imports` | 0 |
| 관련 디렉터리 | `pytest tests/backend/harness tests/backend/api tests/backend/l4` (8859 passed · 372 skipped) | 0 |
| 백엔드 전체 · 계층 커버리지 | 최종 HEAD 재실행 결과는 최종 보고에 기재 | — |
| backend 게이트 CLI 20종 | coach_prose_leak · pedagogy_pack_fidelity 포함 전건 | 전건 0 |
| declared-unwired-audit | `python -m whymath_backend.ops.declared_unwired_audit` | 0 |
| 백로그 | `backlog.py validate` · `audit-deps` | 0 · 0 |
| 뮤테이션 하네스 | §4.2 29종 | 0(재실행 포함) |

## 7. 한계·남은 위험

1. **튜터 슬롯 값 전달은 미이행이다(`P3-72`).** 개념·스킬·숙달·팩 요약을 프롬프트에 싣는 일이다. 학생 숙달·θ에서 파생된 정보를 클라우드 LLM(openrouter 좌석)에 보낼지는 개인정보 판단이므로 Kiki 결정이 선행 조건이다.
2. **Langfuse 기록은 미이행이다(`P3-73`).** 보류 사유는 표본 오염 우려가 **아니다**. `cost_report`는 `name="l3_routing"`으로 필터링하므로(`ops/cost_report.py:63·628`) 별도 이벤트명이면 오염되지 않는다. 진짜 사유는 `LangfuseSink`가 이벤트명을 `l3_routing`으로 하드코딩하고 있다는 점이다(`l3/trace/langfuse_sink.py:61`). sink 확장(또는 l3_routing 메타데이터 결선)이 필요하다. 1차 보고의 "오염 우려로 불가"는 잘못된 근거였으므로 정정한다. 같은 요약은 관측 레코드에 이미 있다.
3. **필수 누락 시 명시 fallback은 미이행이다(`P3-74`).**
4. **매니페스트 범위 밖 호출자**(`tutor_context` 미전달 — 관측 레코드의 context 필드는 None, 프롬프트 표기 키 없음):
   - `harness/wh1_shadow.py::observe_wh1_harness_shadow` — 비노출 shadow
   - `harness/coach_prose_leak_eval.py` — 게이트 측정 하네스
   - `scripts/demo/wh1_primary_probe.py`·`scripts/ops/wh1_primary_timeout_decompose.py` — 데모·진단 스크립트

   학생에게 서빙되는 경로는 코치 세션 두 핸들러뿐이며, 둘 다 매니페스트를 전달한다.
5. **WARNING 로그량 위험은 낮췄다.** 콜드스타트와 커버리지 공백은 INFO로 내렸다. 운영에서 WARNING은 플래그 OFF와 조회 실패에만 남는다.
6. **조회가 2건 늘었다**(개념·스킬, SAVEPOINT 1개). 개념 해석은 같은 요청에서 이미 반복되던 seam이다. 반복을 모으는 리팩터는 범위 밖이다.
7. **실 PG 경로 미확인.** 실 PG 통합 테스트와 CI `backend-migrations` 잡은 로컬에서 돌리지 못했다. 실 PG에서 SAVEPOINT와 `get_concept_skill_ids`(SQL은 기존 `_assessed_skill_ids`와 동일)가 도는지는 CI가 판정한다.
8. **헌법 테스트 일부 미판정.** `tests/constitution/test_check_signed_changes.py`는 로컬에 `ssh-keygen`이 없어 판정하지 못했다. 이번 변경과는 무관하다.
