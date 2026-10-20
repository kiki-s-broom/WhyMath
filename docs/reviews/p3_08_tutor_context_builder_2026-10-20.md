판정 기준: main f2a7b2ca

# P3-08 — Tutor Context Builder 9종: 누락이 조용히 지나가지 않게 하기 (2026-10-20)

- 태스크: `P3-08-tutor-context-builder` · 브랜치 `claude/p3-08-tutor-context-builder` (claim 6410c374 · 구현 cfe2233c)
- 지시 원문: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [12] P3-08 (1275–1283행)
- 산출 코드: `src/backend/whymath_backend/harness/wh1_tutor_context.py`(신규) · `api/coach.py` · `harness/wh1_primary.py` · `harness/wh1_llm_policy.py` · `harness/wh1_shadow.py` · `l2/skill_mastery_tracking.py`(공개 래퍼 1개) · `scripts/analysis/eos_feature_inventory_v2.py`(WM-E-704에 모듈 1개 귀속)
- 테스트: `tests/backend/harness/test_wh1_tutor_context.py` · `tests/backend/api/test_coach_tutor_context.py` · `tests/backend/harness/test_wh1_shadow.py`(레코드 허용 목록에 필드 1개 추가)
- 새 Entity·스키마·Alembic 변경 0 · 새 Agent 0 · 응답 스키마는 필드 추가만(하위호환)

## 0. 결론

**완료 판정 충족.** 코치 세션 두 핸들러(`create_session`·`append_turns`)는 튜터를 부를 때마다 9종을 전부 판정한다. 각 슬롯은 `filled`이거나, `filled=False`와 원인 코드를 함께 가진다. 누락은 응답·로그·튜터 프롬프트·관측 레코드 네 곳에 표기된다. 슬롯을 하나씩 비우는 주입 9건을 두 핸들러에서 돌렸다(18건). 18건 모두 네 곳에 표기됐고 요청은 201로 진행됐다. 표기 코드를 지우는 뮤테이션에서는 18건이 모두 RED였다(§4).

"9종이 채워진다"는 9종이 늘 **값**으로 채워진다는 뜻이 **아니다**. 다음 상태는 정당하다: 첫 진입이라 학생 답안이 없음, 텍스트 턴이라 풀이 단계가 없음, 문항 없는 대화라 개념이 없음. 그래서 완료 판정을 이렇게 읽었다. 9종의 **판정**은 늘 채워진다(값 또는 원인). 판정이 빈 채로 튜터가 도는 경로는 0이다. 매니페스트 검증자는 "비었는데 원인 없음"과 "누락을 감춘 complete=True"를 구조적으로 거부한다(§4 `TestManifestInvariants`).

## 1. 9종 실측표 — 변경 전(main f2a7b2ca) 코드 경로별

튜터는 WH-1 primary(`harness/wh1_primary.py::run_wh1_primary_turn`)다. 서빙 경로에서 LLM을 부르는 유일한 튜터 좌석이고, 기본값 ON(`wh1_primary_enabled`)이며, `api/coach.py::_wh1_primary_decision_or`가 부른다. stateless `POST /v1/coach`는 튜터를 부르지 않는다(LLM 0·DB 0). 그래서 이 표의 범위 밖이다.

| # | 슬롯 | 핸들러가 이미 조회하던 원천 (create / append) | 튜터 러너에 전달 | 비었을 때(변경 전) |
|---|---|---|---|---|
| 1 | 학생 상태 | `_server_theta_for`(θ) · `_grade_for`(학년) | θ만 `theta=` | `theta if theta is not None else 0.0` — **콜드스타트 0.0으로 표기 없이 진행** |
| 2 | 현재 Concept | `get_primary_concept_id` — 숙달·팩·θ·성취기준·선수 조회 안에서 최대 5회 재해석 | ✗ | 미매핑이면 `_standard_code_for` DEBUG 로그뿐 — **표기 없음** |
| 3 | 현재 Skill | 코치 경로 조회 **0**(스킬 해소는 채점 적재 경로 `_assessed_skill_ids`에만 있음) | ✗ | **조회 자체가 없음** |
| 4 | 문제 | `body.problem_id` / `dialogue.problem_id` | `problem_id=` | None — 표기 없음 |
| 5 | 학생 답안 | `body.student_solution or body.student_input` | `student_solution=` | 빈 문자열 — 표기 없음 |
| 6 | 풀이 기록 | `body.solution_steps or []` | `solution_steps=` | 빈 목록 — 표기 없음 |
| 7 | 추정 Misconception | `_apply_hypotheses` 반환 가설(이번 턴 매칭 큐레이션) | `active_hypotheses=` | 빈 배열이 프롬프트에 그대로 보임(부분 표기) |
| 8 | Mastery | `_server_mastery_for` · `body.bkt_mastery` · `body.mastery_level` | ✗ (결정론 `decide`만 소비) | 라벨 None — 힌트 이벤트 `label_source`에만 흔적 |
| 9 | Pedagogy Policy | `_pack_for`(교수법 팩) | `pack=` (금지모드 가드·옵트인) | None이면 base Polya 발문 — 표기 없음 |

태스크 notes의 "CoachRequest가 9종을 이미 받는다"는 절반만 맞다. 요청 본문이 직접 받는 것은 4(세션 생성 시)·5·6·8(클라 숙달)뿐이다. 1·2·7·9와 서버 숙달은 서버가 조회하고, 3은 코치 경로에서 조회되지 않았다. 실질 공백은 두 가지였다. ⓐ 3(스킬) 조회 부재. ⓑ 9종 **전부**에 대한 누락 표기 부재.

### 변경 후 판정 규칙 (`api/coach.py::_tutor_context_for` → `harness/wh1_tutor_context.py::build_tutor_context_manifest`)

| # | 판정 | 원인 코드 |
|---|---|---|
| 1 | θ가 있으면 filled. 크기는 θ·학년 중 있는 축 수. 학년만 있으면 **비었음**(콜드스타트를 '있음'으로 위장하지 않는다) | `source_disabled`(플래그 OFF) · `unresolved` |
| 2 | `get_primary_concept_id` 1회. 기존 좌석을 재사용하고 never-break로 감싼다 | `no_problem_context` · `unresolved` · `lookup_failed·<예외타입>` |
| 3 | `get_concept_skill_ids`(신규 **공개 래퍼**). 채점 적재와 같은 `_assessed_skill_ids` 1홉 규칙이다 | 개념 원인 승계 · `unresolved` · `lookup_failed·<예외타입>` |
| 4 | 문항 id 유무 | `not_supplied` |
| 5 | 튜터가 받는 값과 같은 식(`student_solution or student_input`)을 strip해서 판정 | `not_supplied` |
| 6 | 공백이 아닌 단계 수 | `not_supplied` |
| 7 | post-apply 가설 수(reactive) | `none_detected` |
| 8 | 서버 숙달 또는 클라 숙달 신호 | `source_disabled` · `no_problem_context` · `unresolved` |
| 9 | 교수법 팩 유무. 없으면 base Polya 정책만으로 진행한다는 뜻이다 | `source_disabled` · `no_problem_context` · `unresolved` |

새 조회는 개념 1건과 스킬 1건뿐이다(인덱스 단건·1홉). 나머지는 핸들러가 이미 조회한 값을 넘겨받는다(재조회 0). 판정기는 순수 함수이고 값을 채우지 않는다.

## 2. 표기 지점 (집행 — 정본화와 별항)

같은 매니페스트 객체 하나가 네 곳으로 간다. 판정 원천은 하나다. HTTP 대조군 테스트가 `응답 == 튜터가 받은 것`을 단언한다.

1. **응답** — `SessionCreateResponse.tutor_context`와 `TurnAppendResponse.tutor_context`.
   - 필드 추가만 했다(기본값 None, 두 핸들러는 늘 채운다).
   - 값은 담지 않는다. 슬롯·`filled`·크기·원인·예외 타입명만 있다. 숙달·θ 수치 비노출(slice 69/70)은 유지된다(`test_manifest_carries_no_values`).
   - stateless `CoachResponse`에는 싣지 않는다. 튜터가 없는 경로라 늘 '누락'인 가짜 계기판이 되기 때문이다(선례: `client_state_mismatch`·`served_hint`).
2. **로그** — `whymath.harness.wh1_tutor_context`에 1줄을 남긴다. 형식은 `슬롯(원인[·예외타입명])`다.
   - 등급: 시스템 측 공백(`source_disabled`·`unresolved`·`lookup_failed`)이 하나라도 있으면 WARNING, 학생 측 정상 부재뿐이면 INFO, 완비면 0줄이다. 운영 루트 로거는 WARNING이라 시스템 공백은 반드시 남는다.
   - 새 조회가 실패하면 `api.coach` 로거에도 타입명이 든 WARNING이 남는다. 예외 메시지(값)는 남기지 않는다.
   - **실측 결함 1건을 피해 갔다.** 처음 형식 `student_answer=not_supplied`는 루트 PII 스크러버(`ops/log_scrubber.py`의 `student_answer[:=]값` 마스킹)에 걸려 `student_answer=***MASKED***`로 지워졌다. 누락 표기가 로그에서 사라진 것이다. HTTP 테스트가 RED로 잡았고, 괄호 형식으로 바꿨다. 9종을 전부 비운 최악의 경우에도 스크러버를 통과하는지 테스트로 동결했다(뮤테이션 M8 RED).
3. **튜터 프롬프트** — `LLMTutorPolicy` 상태 요약에 `context_missing: [슬롯명…]`을 싣는다.
   - 비었을 때만 키가 생긴다. 완비면 프롬프트는 바이트 단위로 기존과 같다.
   - 토큰 예산 절단 대상이 아니다. 누락 표기가 예산 때문에 지워지면 그 자체가 무증상 누락이다.
4. **관측 레코드** — `Wh1HarnessShadowObservation.context_missing`.
   - None은 구판·shadow 레코드, `[]`는 누락 0이다.
   - 정상 종료·예산 소진·프로즈 거부·타임아웃 중단 레코드 모두에 실린다.

## 3. 누락 처리 정책 — "진행하되 표기"(거부·LLM 생략이 아니다)

**선택: 누락이 있어도 튜터 호출·코칭을 그대로 진행한다. 대신 누락을 §2의 네 곳에 반드시 표기한다.** 4xx 거부도, "필수 누락 시 LLM 생략·결정론 폴백 강제"도 택하지 않았다. 학생에게 정답을 바로 주지 않는 동작은 바뀌지 않는다.

근거:

1. **누락의 대부분이 정당한 학생 상태다.** 첫 진입(답안 없음), 텍스트 턴(풀이 단계 없음), 의심 없음(가설 0), 문항 없는 대화가 그렇다. 거부하면 정상 학습 흐름이 깨진다. 폴백을 강제하면 대부분의 턴에서 하네스 발화가 꺼진다. 이 하네스 발화에는 verify 의무·정답 억제 게이트가 포함돼 있다. 결국 폴백 강제는 이 회차가 금지한 "튜터 기능 변경"이다.
2. **학생 안전 게이트는 슬롯 값에 기대지 않는다.** verify 의무(§3.1)·정답 억제 백스톱(§3.4)·톤필터·금지모드 가드는 슬롯이 비어도 똑같이 강제된다.
3. **"빈 값을 넣어 LLM을 부르는" 경로가 구조적으로 없다.** LLM 프롬프트에는 슬롯 *값*이 들어가지 않는다. 학생 원문·단계는 정책이 사적으로 보유하고(S1-a), 프롬프트는 비민감 상태 요약뿐이다. 그래서 지시문 3항이 걱정한 상황은 "LLM이 그 context 없이 고른다는 사실을 모른다"로 바뀐다. `context_missing`이 바로 그 공백을 메운다.
4. **원 지시문 3항("명시적으로 fallback 경로로 보낸다")과의 차이.** 명시적 폴백 경로는 이미 있다. 결정론 Polya 템플릿이고, 튜터 실패·타임아웃·예산 소진 때 그리로 간다. 누락만으로 이 경로를 강제하지 않은 이유는 위 1·2다. 이 선택은 되돌리기 쉽다. 특정 슬롯(예: 학생 상태)을 필수로 올리려면 `_wh1_primary_decision_or` 호출 앞에 `manifest.status_of(...)` 분기 한 줄을 넣으면 된다. 판정이 이미 한 곳에 모여 있기 때문이다.

## 4. 주입·뮤테이션 결과 (exit code 판정)

### 4.1 주입 9건 × 2핸들러 — HTTP `test_each_single_slot_injection_is_disclosed_and_proceeds`

주입마다 네 가지를 단언했다.

1. 요청이 201로 진행된다.
2. 응답 `missing`에 그 슬롯(연쇄 포함)이 뜬다.
3. 로그 1줄에 `슬롯(원인)`이 남는다.
4. 튜터 러너가 받은 매니페스트에도 같은 누락이 있다.

주입이 실제로 적용됐는지(mutated ≠ original)도 단언했다.

| 주입 | 기대 누락 | create | append | 표기 제거 뮤테이션 시 (create / append) |
|---|---|---|---|---|
| 학생 상태(θ None) | learner_state | GREEN | GREEN | RED / RED |
| 개념(None) | concept·skill | GREEN | GREEN | RED / RED |
| 스킬([]) | skill | GREEN | GREEN | RED / RED |
| 문제(problem_id 없음) | problem·concept·skill·mastery·pedagogy_policy | GREEN | GREEN | RED / RED |
| 학생 답안("") | student_answer | GREEN | GREEN | RED / RED |
| 풀이 기록(없음) | solution_record | GREEN | GREEN | RED / RED |
| 오개념(가설 0) | misconception | GREEN | GREEN | RED / RED |
| 숙달(None) | mastery | GREEN | GREEN | RED / RED |
| 교수법 정책(팩 None) | pedagogy_policy | GREEN | GREEN | RED / RED |

- 정상: 18 passed, exit 0.
- 뮤테이션(로그 호출 삭제 + 매니페스트를 '완비'로 위장해 응답·튜터에 전달): 18 failed, exit 1. 원복 후 sha256 일치를 확인했다.
- 대조군(9종 완비): 두 핸들러 모두 `complete=True`, 누락 로그 0줄, 튜터가 받은 매니페스트도 완비였다.

판정기 단위 테스트(`TestManifestDiscrimination`)에도 같은 9건이 있다. 각 주입은 해당 슬롯만 비우고, 주입하지 않은 8종은 채워진 채로 남는지 확인한다. 판정이 '전부 누락'으로 뭉개지지 않는다는 뜻이다.

### 4.2 표기 코드·가드 뮤테이션 13종 (백업 → 적용 단언 → 실행 → 바이트 원복 단언)

| # | 뮤테이션 | 결과 |
|---|---|---|
| M1 | 핸들러의 누락 로그 호출 삭제 | RED |
| M2 | 응답 `tutor_context` 제거(create) | RED |
| M3 | 튜터 러너로 매니페스트 미전달 | RED |
| M4 | 기본값 채우기 — θ 없음을 '학생 상태 있음'으로 판정 | RED |
| M5 | 공백 답안을 '답안 있음'으로 판정(strip 제거) | RED |
| M6 | 프롬프트 `context_missing` 제거 | RED |
| M7 | 관측 레코드 `context_missing` 미전달 | RED |
| M8 | 로그 형식을 `key=value`로(스크러버가 지움) | RED |
| M9 | 새 스킬 조회의 never-break 제거 | RED |
| M10 | 오개념 preload — 웜스타트 표적을 프롬프트 가설로 넣음 | RED |
| M11 | 선수 traversal depth 1→3 | RED |
| M12 | 웜스타트 상한 해제(`limit=50`) | RED |
| M13 | 튜터에 매니페스트 대신 None 전달(응답만 표기) | RED |

결과: 13/13 RED. 적용 단언 13/13, 원복 단언 13/13, 하네스 exit 0.

지시문 5항의 3종 RED와의 대응:

- ① 필수 context 누락 → §4.1, M1~M5.
- ② token budget 초과 → `test_budget_guards_still_hold_with_context_missing`. 가설 30·history 30·누락 9종을 넣어도 ≤3000토큰·≤20노드가 지켜지고 `context_missing`이 살아남는다. 상한 자체는 기존 가드이고, 그 뮤테이션은 `tests/backend/harness/test_wh1_llm_policy.py` Subgraph 예산 테스트군이 소유한다.
- ③ 오개념 preload → M10.

## 5. depth / max_nodes / preload — 튜터 context 경로의 가드와 동결

| 경로 | 가드(기존) | 이번 동결 |
|---|---|---|
| 선수 traversal: `_prerequisite_coaching_for` → `recommend_prerequisite_gaps` → `fetch_prerequisites` 재귀 CTE | `max_depth=1`(재귀 bound) | 서빙 경로가 이 좌석을 실제로 1회 타고, `1 ≤ max_depth ≤ 2`임을 HTTP 테스트로 동결(M11 RED) |
| 웜스타트 탐색 표적: `assemble_warmstart_probe_hints` | `_DEFAULT_LIMIT=12` | 호출부가 상한을 풀지 않고, `12 ≤ 상한 ≤ 20`임을 동결(M12 RED) |
| LLM 프롬프트 요약: `LLMTutorPolicy._build_prompt` | `_MAX_CONTEXT_NODES=20`·`_MAX_HISTORY=8`·`_MAX_PROMPT_TOKENS=3000` | `context_missing`이 실려도 세 상한 유지, 누락 표기는 절단하지 않음 |
| 오개념 preload | 웜스타트 표적·`unresolved_hypothesis_ids`는 사적 probe 좌석 전용 | ⓐ 프롬프트에 웜스타트 표적이 실리지 않음(M10 RED) ⓑ HTTP: 실제 `_apply_hypotheses`를 태워 매칭 0인 턴이면 튜터가 받는 `active_hypotheses == []`, 표적은 `warmstart_outside_mids`로만 감 |
| 새 개념→스킬 조회 | — | 그래프 순회가 아니라 1홉이다. 값은 프롬프트에 실리지 않고 크기만 매니페스트에 남는다 |

ARCH-11(blocked·subgraph depth guard)의 소유 범위는 건드리지 않았다. 지금 하네스의 `query_curriculum`은 실제로 순회하지 않는다(`wh1_loop.py`가 "노드 조회(기록·내부)"만 반환한다). 그래서 traversal guard는 여전히 "없는 순회에 가짜 가드를 만들지 않는다"(`wh1_llm_policy.py` docstring) 상태다.

## 6. 검증 (전부 exit code로 판정, HEAD cfe2233c 기준)

CI 잡 대조: 이 변경이 닿는 잡은 `backend`(lint·type·test + 게이트 CLI 20종 + 헌법 테스트), `infra-contracts`(인벤토리 v2 전수 귀속 포함), `declared-unwired-audit`, `harness-integrity`(백로그·래칫)다. `backend-migrations`(실 PG)는 로컬에서 돌리지 못했다.

| 검사 | 명령 | exit |
|---|---|---|
| Ruff | `python -m ruff check . ../../tests/backend ../../tests/constitution` | 0 |
| Black | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| Mypy | `python -m mypy --strict whymath_backend` (806 files) | 0 |
| Import contracts | `lint-imports` (4 kept · 0 broken) | 0 |
| 백엔드 전체 스위트 | `python -m pytest -m "not corpus_authoring" -n auto --dist loadfile --cov=whymath_backend --cov-fail-under=70` → 21357 passed · 710 skipped · 1 xfailed · 총 커버리지 87.56% | 0 |
| 계층별 커버리지 | `check_layer_coverage.py coverage.xml` (api 96.9 · l1 90.8 · l2 96.4 · l3 81.6 · l4 95.8) | 0 |
| backend 게이트 CLI 20종 | defect_detection · selective_grading · explicit_correction_gap · misconception_false_positive · generator_space_overlap · residue_cross_verify_v2 · coach_prose_leak · anchor_detection_channel · pedagogy_pack_fidelity · analogy_fidelity · explanation_f7 · notation_coverage · curriculum_notation_gate · provenance_audit · routing_data_grade · routing_decision_bypass · provider_seat_contract · prompt_asset_audit l3 · phase3_metrics self-check · solution_qa | 전건 0 |
| declared-unwired-audit | `python -m whymath_backend.ops.declared_unwired_audit` | 0 |
| infra-contracts | ruff · black · runbook_blocks · mastery_write_path_scan · dependency_upper_bounds · ci_constraints check · `pytest tests/infra`(3221 passed · 27 skipped) · `pytest tests/test_idempotency.py` | 전건 0 |
| 헌법 테스트 | `pytest -q tests/constitution` | **1** — `test_check_signed_changes.py` 33건이 `ssh-keygen` 부재로 실패(로컬 환경 결함). 그 파일을 제외하면 39 passed, exit 0. 이번 변경은 그 파일·대상(`constitution/`·서명자 목록)을 건드리지 않았다 |
| 백로그 | `backlog.py validate` · `backlog.py audit-deps` | 0 · 0 |
| 위헌 심사 래칫 | `scripts/constitution/audit_ratchet.py` (단계 2 · 차단 0건 ≤ 기준선 0건) | 0 |
| 주입 매트릭스 | §4.1 정상 18 GREEN(exit 0) / 뮤테이션 18 RED(exit 1) | — |
| 뮤테이션 하네스 | §4.2 13/13 RED·적용·원복 | 0 |

## 7. 한계·남은 위험

1. **Langfuse에는 기록하지 않았다(지시문 4항 미이행).** 앱 공유 `TraceSink`(`LangfuseSink`) 스트림은 이벤트명이 `l3_routing` 하나뿐이고, `ops/cost_report` 게이트②가 그 스트림을 라우팅 표본으로 센다. 라우팅이 아닌 이벤트를 섞으면 비용 표본이 오염된다. 그래서 같은 요약(누락 슬롯 이름)을 WH-1 관측 레코드(`context_missing`)에 실었다. Langfuse 축이 필요하면 별도 이벤트명과 cost_report 제외 규칙을 함께 만드는 후속 작업이 필요하다.
2. **슬롯 *값*은 LLM 프롬프트에 넣지 않았다.** 튜터가 받는 것은 판정 결과와 누락 이름이다. 개념 코드·스킬·숙달 값은 프롬프트에 없다. 이유는 프라이버시, "LLM은 학습 상태를 결정하지 않는다" 경계, 튜터 기능 불변이다. 값까지 넣으려면 `query_curriculum`이 실제로 순회해야 하므로 ARCH-11 traversal guard와 함께 다룰 사안이다. P3-09(출력 스키마)와도 맞물린다.
3. **probe 후보 풀 상한은 200이다**(`wh1_probe_supply._DEFAULT_LIMIT`). 이 풀은 LLM context가 아니라 `plan_probe`의 사적 입력이다. 그래서 max_nodes 예산 대상으로 보지 않았고, 이번에 바꾸지 않았다.
4. **교수법 정책 슬롯은 교수법 팩을 본다.** base Polya 정책(`PolyaCoach.decide`)은 늘 돌기 때문에 슬롯 판정 대상이 아니다. 팩은 파일럿 단원 문항에서만 해석된다. 따라서 운영 턴 대부분이 `pedagogy_policy(unresolved)` WARNING을 낸다. 스킬·숙달 미매핑도 마찬가지다. 실제 커버리지 공백이므로 표기는 정직하지만 WARNING 로그량은 늘어난다.
5. **조회가 2건 늘었다**(개념·스킬). 개념 해석은 같은 요청에서 이미 최대 5회 반복되던 seam이다. 반복을 하나로 모으는 리팩터는 범위 밖이라 하지 않았다.
6. **stateless `/v1/coach`**는 튜터 호출이 없어 범위 밖이다(응답 필드도 없다).
7. **실 PG 통합 테스트**(`WHYMATH_RUN_INTEGRATION=1` — `test_coach_wh1_primary_flip.py` 등)와 CI `backend-migrations` 잡은 로컬에서 돌리지 못했다. CI가 최종 판정한다. 그 경로에서 `get_concept_skill_ids`가 실 스키마(`Concept.behavior_skills` ∩ `skill_node`)로 도는지도 거기서 처음 확인된다. 다만 SQL은 기존 `_assessed_skill_ids`와 같다.
