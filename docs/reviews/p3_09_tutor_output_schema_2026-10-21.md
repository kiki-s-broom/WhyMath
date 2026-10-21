판정 기준: main e609c543

# P3-09 — 튜터 구조화 출력 스키마: 검증을 통과한 응답만 학생에게, `mastery_update_allowed`는 항상 false (2026-10-21)

- 태스크: `P3-09-tutor-output-schema` · 브랜치 `claude/p3-09-tutor-output-schema` (claim 1b5c5a26)
- 커밋: 구현·테스트 c06b8dcb · 보고서는 그다음 커밋
- 선행: `P3-08`(`docs/reviews/p3_08_tutor_context_builder_2026-10-20.md`) · `P3-72`(`docs/reviews/p3_72_tutor_slot_value_delivery_2026-10-20.md`)
- 정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [13] P3-09
- 산출 코드:
  - `src/backend/whymath_backend/harness/wh1_tutor_output.py` (신설 — 스키마·검증기 정본)
  - `src/backend/whymath_backend/harness/wh1_llm_policy.py` (1단계 집행)
  - `src/backend/whymath_backend/harness/wh1_primary.py` (2단계 집행)
  - `src/backend/whymath_backend/api/coach.py` (3단계 집행 · 응답 필드 `tutor_output`)
  - `src/backend/whymath_backend/harness/wh1_shadow.py` (관측 필드 2종 · 결말 라벨 1종)
  - `scripts/analysis/eos_feature_inventory_v2.py` (신규 모듈을 WM-E-704에 귀속)
- 테스트:
  - `tests/backend/harness/test_wh1_tutor_output.py` (신설 · 124건)
  - `tests/backend/api/test_coach_tutor_output_schema.py` (신설 · 26건 = 두 핸들러 × 13)
  - `tests/infra/test_tutor_output_schema_gate.py` (신설 · 8건 — AST 집행 동결, stdlib만)
  - `tests/backend/harness/test_wh1_shadow.py` (관측 레코드 비식별 필드 허용 목록에 2종 추가)
- 새 Entity·DB 스키마·Alembic 0건. API 응답 변경은 필드 추가뿐이다(`tutor_output` — nullable, 하위호환).

## 0. 결론

acceptance ①~④를 **전부 충족**했다. 이 회차의 실질은 등재 메모가 예측한 대로 스키마 신설이 아니라 **게이팅**이었다. 다만 실측해 보니 두 가지가 실제로 비어 있었다.

- 학생 대면 출력에 구조(진단·전략·다음 행동)도 `mastery_update_allowed` 개념도 없었다. main 코드에서 `mastery_update_allowed`는 0건이다.
- LLM 원시 출력 파서가 위반을 **조용히** 넘겼다. 실패 로그가 0건이었고, 상태 권위 주장 키는 무시됐고, `"1"`·`true`·`1.9`는 정수로 형변환됐다.

| acceptance | 판정 | 근거 |
|---|---|---|
| ① 구조화 스키마 고정 + 통과해야만 학생에게 | **충족** | 정본화는 `TutorTurnOutput`이다(§2). 집행은 3지점이며 두 핸들러가 모두 경유한다(§3) |
| ② `mastery_update_allowed` 항상 false 기계 동결 | **충족** | 타입 `Literal[False]` · 빌더 미전달 · LLM 원시 출력 거부 · 승격 직전 재검증 · AST 전수 스캔(§4) |
| ③ 변별력 — 스키마 위반·mastery=true 주입 차단 | **충족** | 주입 결과는 §5, 뮤테이션 20종 전건 RED는 §6 |
| ④ 완료 판정 | **충족** | 검증 미통과 응답은 학생 응답 문자열(`decision.prompt`)·`tutor_output` 어디에도 없다. HTTP 테스트가 응답 본문 전체에서 표지 문자열 부재를 단언한다 |

## 1. 경로 실측 — LLM 출력이 학생에게 가기까지 (main e609c543 vs 이 브랜치)

학생에게 LLM 문자열이 나가는 서빙 경로는 **세션 핸들러 두 개뿐**이다: `create_session`·`append_turns` → `_wh1_primary_decision_or`. 역할 기반으로 찾았다 — `model_copy(update={"prompt"`, `run_wh1_primary_turn(`·`.coach(`·`rephrase_coach_utterance(` 호출측. 내가 찾은 방법으로는 그 밖의 학생 대면 LLM 발화 경로는 0건이다.

| # | 단계 | 코드 위치 | main e609c543에 있던 것 | 빈틈 | 이 브랜치 |
|---|---|---|---|---|---|
| 1 | LLM 호출 | `LLMTutorPolicy.next_action` → `Wh1LlmSeam`(라우터·캐시·Langfuse) | 있음 | — | 그대로 |
| 2 | JSON 추출 | `_extract_json` | 있음(코드펜스·주변 산문 허용) | 실패 시 **로그 0**(침묵 강등) | 사유 `NOT_JSON_OBJECT` WARNING + 회계 |
| 3 | 스키마 판정 | 없음 | Pydantic 판별 유니온만 있었다. 여분 키는 조용히 버려지고, 극성 `"1"`·`true`는 정수로 형변환되고, 비문자열 `utterance`는 조용히 None이 됐다 | 상태 권위 주장(`mastery_update_allowed: true`)을 **무증상으로 무시** · 관대한 형변환 · 환각 개념 id 무검사 · 실패 로그 0 | `classify_action_payload` 신설 → `_reject`(사유 WARNING · `output_rejections` 회계 · 안전 강등) |
| 4 | 액션 구성 | `_build_action`(Pydantic) | 있음 | 예외 시 로그 0 | 예외 타입명을 사유로 WARNING |
| 5 | 불변식 | `_enforce_invariants` · 하네스 `_exec`(verify 의무·정답 억제·`log_evidence` 카탈로그 게이트) | 있음(ARCH-60 C·D 동결) | — | 그대로 |
| 6 | 프로즈(기본 OFF) | 정책 자유발화 → `gate_policy_prose`(외래 등식) · 파생 템플릿 → `rephrase_coach_utterance` → `classify_prose_violation`(fail-closed) | 있음(ARCH-60 B 동결) | 켜면 rephrase 산출물이 학생에게 간다. 길이 상한 120은 프로필 S에만 있다 | 7·8단계가 프로즈 산출물도 덮는다(톤필터 뒤 최종 문자열 기준) |
| 7 | 금지모드 가드(옵트인) · 톤필터 | `check_forbidden_modes` · `filter_tone` | 있음(ARCH-60 A 동결) | 정책 자유발화(프로즈 OFF)의 길이 상한 0 | 그대로 |
| 8 | 학생 대면 구조화 출력 | 없음 | 러너는 **문자열**만 반환했다 | 응답에 진단·전략·다음 행동 구조 0 · `mastery_update_allowed` 0 | `build_tutor_output` → 스키마 검증 → 미통과면 `None` + 관측 `fallback_output_schema` |
| 9 | 승격 | `_wh1_primary_decision_or` → `decision.model_copy(update={"prompt": …})` | 있음(ARCH-59 ①·ARCH-60 G 동결 — `prompt` 한 키·생산자 반환값만) | 승격 직전 구조 재검증 0 | `check_deliverable`(재검증 · 발화 일치 · 코치 자신의 DB 조회 개념과 대조) |
| 10 | 응답 조립 | `SessionCreateResponse`·`TurnAppendResponse` | `decision.prompt`(문자열) | — | `tutor_output` 필드 추가(검증 통과 구조체만) |

판정 대상 밖인 비대면 경로와 그 근거:
- **shadow**(`observe_wh1_harness_shadow`) — 비노출 관측이다. 같은 정책을 쓰므로 1단계 판정은 shadow에도 적용된다.
- **stateless `POST /v1/coach`** — LLM 0(`PolyaCoach.decide` 결정론). 튜터 출력이 아니다.
- **`PolyaCoach.coach`**(`l4/polya/engine.py`, LLM 생성) — API 호출측 0건. 톤필터 반환은 ARCH-60 E가 동결한다.
- **`run_persisted_turn`**(`harness/wh1_session.py`) — HTTP 미배선(호출측 0건). §8 한계 참조.

## 2. 정본화 — 스키마 정의 위치

정의 위치는 `harness/wh1_tutor_output.py`다. `TutorTurnOutput`은 `extra="forbid"`·`frozen`·`strict`이고 판은 `tutor-output-v1`이다.

| 필드 | 타입 | 값의 출처(전부 서버) |
|---|---|---|
| `diagnosis.concept_id` | `str \| None`(≤ 120자) | 이번 턴 코치가 DB에서 PK로 조회한 PRIMARY 개념 code(`_concept_label_for` → `TutorContentSummary.concept.code`) |
| `diagnosis.misconception_id` | `str \| None` — 카탈로그 정본(`CATALOG_BY_ID`)에 있어야 한다 | 하네스 턴 종료 시 활성 가설 최상위(신뢰도 내림차순, 같으면 id 오름차순) |
| `diagnosis.confidence` | `float \| None`(0~1, 오개념 id가 없으면 None) | 그 가설의 신뢰도 |
| `response_strategy` | `guided_question`·`guided_hint`·`diagnostic_probe`·`encouragement`·`socratic_requestion` | 하네스 `end_turn` 행위 유형(질문·힌트·출제·격려)과 1:1. 금지모드 가드가 대체한 턴은 `socratic_requestion` |
| `hint_level` | `Literal[1,2,3,4] \| None` | 결정론 Polya 엔진의 `PedagogyDecision.hint_level`. LLM은 힌트 단계를 정하지 않는다 |
| `explanation` | `str`(1~400자, 공백뿐 금지) | 톤필터 산출물 = 학생 화면의 `decision.prompt` |
| `next_action` | `continue_dialogue`·`revise_solution`·`solve_probe` | 출제 턴이면 `solve_probe`, 이번 턴 verify 판정이 incorrect·unverifiable이면 `revise_solution`, 그 밖은 `continue_dialogue` |
| `mastery_update_allowed` | **`Literal[False]`**(기본 False) | 빌더가 이 필드를 **넘기지 않는다** |

**발화 길이 상한 400의 근거.** 하네스 파생 발화의 최장은 163자다. 카탈로그 72종 × 신뢰도·증거 수 조합의 개입 발문을 전수 실측한 값이고, 400은 그 약 2.5배다. 소크라테스 한 턴은 질문 하나이므로, 그보다 긴 발화는 독백이나 풀이 전개로 보고 거부한다.

**`concept_id` 실재 대조는 게이트 함수에 둔다.** 대조는 `validate_tutor_output`·`check_deliverable`에서 하고 모델 검증자에는 두지 않는다. 처음에는 모델 검증자에 넣었는데, 응답 모델이 구조체를 재검증하는 자리(조회 결과를 모르는 곳)에서 모델 스스로 깨졌다. HTTP 테스트 14건 RED로 발견했다. 그래서 모델은 형식만 보고, 실재 확인은 게이트를 경유한 경로에서만 한다.

LLM 원시 출력 판정(`classify_action_payload`)의 사유 코드는 닫힌 어휘다.
- `STATE_AUTHORITY_CLAIM` — 키 이름에 학습 상태 축(`mastery`·`proficiency`·`ability`·`skill_level`·`competence` — ARCH-59 ③과 같은 어휘)이 있다. 예외는 계약과 같은 값의 echo인 `mastery_update_allowed: false` 하나다.
- `UNKNOWN_KIND` · `MISSING_FIELD` · `FIELD_TYPE` — 관대한 형변환을 금지한다(bool을 정수로, 문자열 극성, 비문자열 발화).
- `UNKNOWN_CONCEPT_ID` — 이번 턴 프롬프트에 실린(DB 조회) 개념 code 밖의 개념 id다(`read_student_state.node_ids`·`query_curriculum.node_id`). LLM이 받은 적 없는 id는 환각이다.
- `UNKNOWN_MISCONCEPTION_ID` — 카탈로그 밖 오개념 id다(`log_evidence`).
- `NOT_JSON_OBJECT`. 액션 구성 단계의 실패는 예외 타입명(`ValidationError` 등)을 사유로 쓴다.
- 무해한 여분 키(`"reason": …`)는 **거부하지 않는다**. 액션 타입에 실릴 자리가 없어 버려지고(필드 집합은 ARCH-59 ③ 동결), 거부하면 라이브 폴백률만 오른다.

## 3. 집행 지점 — 그 검증을 실제로 경유하는 서빙 코드

| 단계 | 집행 지점 | 미통과 시 | 기계 동결 |
|---|---|---|---|
| 1 | `LLMTutorPolicy._parse_action` → `_reject` | 사유 WARNING + `output_rejections` 회계 + `_safe_fallback` | `test_tutor_output_schema_gate.py` A |
| 2 | `run_wh1_primary_turn` — 톤필터 직후 `build_tutor_output`, 거부면 `return None` | 결정론 Polya 발화 · 관측 `primary_outcome="fallback_output_schema"`·`tutor_output_reason_code` · WARNING | 같은 파일 B — 빌더가 톤필터 산출물을 소비하고, 거부 분기가 모든 발화 반환보다 앞에 있다 |
| 3 | `_wh1_primary_decision_or` — `check_deliverable`, 거부면 `return decision` | 결정론 발화 · `tutor_output=null` · WARNING | 같은 파일 C — 재검증이 `model_copy`보다 앞에 있다 |
| 배선 | `create_session`·`append_turns`가 둘 다 `output_receipt=`를 넘기고 응답에 `tutor_output=<영수증>.output`을 싣는다 | — | 같은 파일 D |

관측 레코드에 두 필드를 추가했다.
- `llm_output_rejections` — 턴당 거부 수. 검증기가 실제로 작동한 횟수의 분자다.
- `tutor_output_reason_code` — 2단계 거부 사유.

구판·shadow는 None이라 "0건"과 구분된다. 결말 어휘에는 `fallback_output_schema`를 추가했고, 수확기 `PRIMARY_OUTCOME_LABELS`는 `get_args`로 자동 반영된다.

## 4. 미통과 시 학생이 받는 것 — 교수학적 근거

| 거부 단계 | 학생이 받는 발화 | 근거 |
|---|---|---|
| 1 (LLM 원시 출력) | 풀이 단계가 있고 미검증이면 먼저 `verify_step`을 돌린다(검증 의무 유지). 그렇지 않으면 하네스 격려 템플릿 "좋아, 지금까지 잘 하고 있어. 다음으로 가보자."로 턴을 닫는다 | 거부가 검증 의무를 건너뛰게 하지 않는다(`test_policy_rejection_respects_verify_obligation`). 격려 템플릿은 상수 문자열이라 정답을 담을 수 없다. 오답 턴에는 하네스 정답 억제가 그대로 돈다 |
| 2·3 (구조화 출력) | 코치의 결정론 `PolyaCoach.decide` 발화(현재 Polya 단계 질문) | P3-09 이전부터 러너 실패·타임아웃의 폴백으로 쓰던 경로다(신설 0). 단계 질문에는 정답 문자열이 없다 |

정답 직접 제공 금지는 그대로 유지된다. 폴백은 둘 다 결정론 템플릿이고 LLM 문자열을 섞지 않으며, 부정적 피드백 표현도 없다(격려·질문형).

`mastery_update_allowed` 강제는 다섯 층이다.
1. **타입 `Literal[False]`** — true를 담은 구조체는 생성되지 않는다(`test_mastery_update_allowed_true_cannot_be_constructed`).
2. **빌더 미전달** — 빌더는 이 필드를 넘기지 않는다(기본값만). AST 전수 스캔(F)이 백엔드 프로덕션 코드에 False 상수가 아닌 키워드 인자·속성 대입·dict 리터럴이 0건임을 단언한다.
3. **원시 출력 거부** — LLM 원시 출력에 false가 아닌 값(`true`·`"false"`·`0`·`null`·`1`)이 있으면 1단계에서 거부한다.
4. **승격 직전 재검증** — `model_construct`로 우회 생성된 `True` 구조체도 거부한다.
5. **구조적 집행은 ARCH-59** — 이 필드는 *선언*이다. 실제로 숙달을 못 바꾸게 하는 구조적 집행은 ARCH-59가 이미 소유한다(튜터 경로 mastery writer 0, 승격 키는 `prompt` 하나). 이번에도 초록이다. 숙달 갱신은 완료 판정 증거(`completion_evidence`)를 거친 평가·숙달 엔진만 한다.

## 5. 주입 결과

모두 hermetic이다(LLM 0·DB 0). 표지 문자열 `ZZP309MARKZZ`(HTTP)·`ZZTUTORMARKERZZ`(러너)를 LLM 발화에 싣고, 그 표지가 학생 응답·로그에 없는지를 본다.

| 주입 | 층 | 결과 |
|---|---|---|
| `mastery_update_allowed: true` / `"false"` / `0` · `mastery_level` 키 · `student_ability` 키 · `proficiency` 키 | 1단계 판정·정책·러너·HTTP 두 핸들러 | 거부 `STATE_AUTHORITY_CLAIM` → 결정론 격려 발화. 표지 0. `tutor_output.mastery_update_allowed=false` |
| 깨진 JSON(닫는 중괄호 없음) · 배열 · 산문 | 정책·러너·HTTP | `NOT_JSON_OBJECT` → 결정론 발화, 표지 0 |
| `action_type` 누락 · `node_id` 누락 · `misconception_id`/`polarity` 누락 | 판정·정책·HTTP | `MISSING_FIELD` |
| 타입 오류 — 발화 배열, 극성 `"1"`·`true`, `turns_elapsed` `true`·`"1"`·`-1`, `node_ids` 문자열·정수·공백, `weight` 문자열·bool, 관계 정수 | 판정·정책·HTTP | `FIELD_TYPE` |
| 존재하지 않는 concept_id — `query_curriculum`·`read_student_state`(LLM 원시) | 판정·정책 | `UNKNOWN_CONCEPT_ID`. 실린 개념이 없는 턴에서는 모든 개념 id가 환각으로 거부된다 |
| 존재하지 않는 concept_id — 진단 개념(구조체 변조) | 2·3단계·HTTP | `UNKNOWN_CONCEPT_ID` → 승격 거부, `tutor_output=null`, 표지 0 |
| 존재하지 않는 misconception_id — `log_evidence`·진단 | 판정·스키마 | `UNKNOWN_MISCONCEPTION_ID` / `SCHEMA_VALUE_ERROR` |
| 범위 밖 `hint_level`(0·5·7·9·문자열 "2") | 스키마·빌더·3단계 변조 | `SCHEMA_LITERAL_ERROR` |
| 과길이 발화(401자+) | 러너·HTTP | 러너 `None` → 결정론 Polya 발화. 관측 `fallback_output_schema`·`SCHEMA_STRING_TOO_LONG`. 표지 0 |
| 영수증 변조 — `mastery_update_allowed=True`(`model_construct`) · 발화 불일치 · 구조체 제거 | 3단계·HTTP 두 핸들러 | `STATE_AUTHORITY_CLAIM` / `EXPLANATION_MISMATCH` / `MISSING_OUTPUT` → 결정론 발화, `tutor_output=null`, 표지 0 |
| 대조군 — 정상 출력 16형(무해한 여분 키 `reason`·`mastery_update_allowed: false` echo 포함) | 판정·정책·HTTP | 거부 0·강등 0. HTTP 대조군에서 `decision.prompt == tutor_output.explanation == 표지 발화`, 진단 = DB 조회 개념 + 활성 가설 |

로그 프라이버시: 거부 WARNING에는 사유 코드만 있다. 표지 문자열과 학생 풀이(`x+1=3`)가 로그에 0건임을 테스트가 단언한다.

## 6. 뮤테이션

절차: cp 백업 → 적용 단언(치환 대상 1건·sha 변화) → pytest → cp 원복 → sha256 동일 단언. 하네스는 세션 스크래치의 `mutate.py`(순수 Python·셸 이스케이프 배제)다. 대상 테스트는 신설 3파일과 ARCH-59·ARCH-60 두 파일이고 `-x`로 돌렸다. **20종 전건 RED, 생존 0**이다. 원복 뒤 `git status` clean을 확인했다.

| # | 뮤테이션 | 결과 |
|---|---|---|
| M01 | 정책: 스키마 판정 호출 제거 | RED |
| M02 | 판정: 상태 권위 주장 검사 제거 | RED |
| M03 | 정책: 거부 WARNING 제거(침묵 실패) | RED |
| M04 | 러너: 스키마 거부 분기 무력화(미통과도 통과) | RED |
| M05 | 러너: 영수증 기록 제거 | RED |
| M06 | 코치: 승격 직전 재검증 무력화 | RED |
| M07 | 스키마: `Literal[False]` → `bool` | RED |
| M08 | 검증기: 계약 필드 선검사 제거 | RED |
| M09 | 재검증: dump 재검증 생략(구조체 그대로 신뢰) | RED |
| M10 | 재검증: 발화 불일치 검사 제거 | RED |
| M11 | 검증기: 진단 개념 id 실재 대조 제거 | RED |
| M12 | 판정: `query_curriculum` 환각 개념 id 검사 제거 | RED |
| M13 | 스키마: 발화 길이 상한 해제 | RED |
| M14 | 코치: append 응답에서 `tutor_output` 누락 | RED |
| M15 | 코치: `hint_level` 미전달 | RED |
| M16 | 빌더: `mastery_update_allowed=True` 주입 | RED |
| M17 | 판정: 오개념 카탈로그 실재 검사 제거 | RED |
| M18 | 판정: bool 극성 허용(관대한 형변환) | RED |
| M19 | 러너: 이전 영수증 초기화 제거 | RED |
| M20 | 코치: 재검증 기준을 러너 자신의 진단 개념으로 바꿈(동어반복) | RED |

## 7. 검증 (exit code)

CI 잡을 전수 열거한 뒤, 이 변경이 닿는 잡을 골라 재현했다: backend·infra-contracts·harness-integrity·declared-unwired-audit. 닿지 않는 잡의 판정은 다음과 같다.
- data-pipeline·mobile·web·webapp·docker-build·infra-shell·concept-reach-guard·corpus-authoring — 변경 경로 밖이다.
- backend-migrations — DB 스키마·Alembic 변경이 0이다.

| 검사 | exit |
|---|---|
| backend: ruff(src + tests/backend + tests/constitution) | 0 |
| backend: black --check --line-length 100 | 0 |
| backend: mypy --strict whymath_backend(807 파일) | 0 |
| backend: lint-imports(4 kept · 0 broken) | 0 |
| backend: pytest 전체 `-m "not corpus_authoring" -n auto --dist loadfile --cov`(21,822 passed · 713 skipped · 1 xfailed · 커버리지 87.71%) | 0 |
| backend: 계층별 커버리지 게이트(l4 95.8% · l3 81.7% · api 97.0% 등) | 0 |
| backend 게이트 CLI 20종 — coach_prose_leak · pedagogy_pack_fidelity · defect_detection · selective_grading · explicit_correction_gap · misconception_false_positive · generator_space_overlap · residue_cross_verify_v2(--dry-run) · anchor_detection · analogy_fidelity · explanation_f7 · notation_coverage · curriculum_notation · provenance_audit · routing_data_grade · routing_decision_bypass · provider_seat_contract · prompt_asset_audit · phase3_metrics --self-check · solution_qa | 전건 0 |
| backend: tests/constitution | 1 — 환경 원인. `ssh-keygen` 부재로 `test_check_signed_changes.py` 34건이 실패했다(`which ssh-keygen` exit 1). 그 파일을 뺀 39건은 exit 0 |
| infra-contracts: ruff · black · check_runbook_blocks · mastery_write_path_scan · check_dependency_upper_bounds · ci_constraints check · pytest tests/infra · tests/test_idempotency.py | 전건 0 |
| harness-integrity: backlog validate · audit-deps · rules lint · rules render --check · jit check · audit_ratchet(차단 0 ≤ 기준선 0) · pipeline_check · check_amendment · pipeline_check --downstream | 전건 0 |
| declared-unwired-audit: declared_unwired_audit · review_status 백필 --check · persona_fit 백필 --check | 전건 0 |

못 돌린 검사:
- `tests/constitution/test_check_signed_changes.py` — 이 환경에 ssh-keygen이 없다. CI가 최종 판정한다.
- harness-integrity의 원격 의존 스텝 — ADR 번호 충돌(원격 fetch)·claims reap·branches·헌법 서명 검증(`check_signed_changes.py`). 원격·서명 인프라가 필요하다.
- 실 PG 통합 테스트(`WHYMATH_RUN_INTEGRATION=1`) — 기본 skip이다. 이번 변경은 DB 접근 0이다.

## 8. 한계·남은 위험

- **라이브 폴백률 변화 미측정.** 1단계 판정이 엄격해졌다 — 문자열 극성·bool·비문자열 발화·환각 개념 id·상태 축 키는 이제 거부·강등된다. 로컬 소형 모델이 이런 형태를 실제로 얼마나 내는지는 hermetic 환경에서 알 수 없다. 다음 라이브 측정에서 관측 `llm_output_rejections`와 결말 분포(`fallback_llm_degraded`)로 확인해야 한다. 거부가 늘면 채택률이 떨어진다 — 안전은 불변이고 품질만 손실된다.
- **오개념 id 거부 위치가 둘이다.** 카탈로그 밖 오개념 id는 이제 1단계에서 거부·강등된다. 하네스 `log_evidence` 게이트(ok=False·루프 지속)는 다른 정책(Scripted 등)용 2차 방어로 남는다. LLM 정책에서는 하네스 게이트까지 가지 않는다.
- **2단계 개념 id 대조는 러너 안에서 동어반복이다.** 진단 개념과 알려진 집합이 같은 원천(DB 조회 개념)이기 때문이다. 실질 변별은 두 곳에 있다: 3단계(코치가 자기 DB 조회 결과로 대조 — M20이 동어반복화를 RED로 잡는다)와, 진단 개념의 출처가 바뀌는 미래 리팩터다.
- **`run_persisted_turn`(`harness/wh1_session.py`)은 HTTP 미배선이지만 LLM이 고른 `log_evidence`를 DB(`evidence_links`)에 영속하는 좌석이다.** 배선되면 같은 정책을 거치므로 1단계 판정은 적용된다. 그러나 증거 영속 자체가 "LLM은 학습 상태를 결정하지 않는다"와 충돌하는지(숙달이 아니라 증거 원장이다)는 이 태스크 범위 밖이다. 배선 태스크가 판정해야 한다.
- **`tutor_output`을 소비하는 클라이언트가 아직 0이다.** 응답에 실렸을 뿐 Flutter 앱은 읽지 않는다. 필드 추가뿐이라 기존 클라이언트는 영향이 없다.
- **뮤테이션 전건 RED는 커버리지의 증거가 아니다.** 주입 목록에 오르지 않은 절은 검사되지 않았다(CLAUDE.md 2026-09-08 확장).
- **PR 미생성.** 지시에 따라 push·gh를 하지 않았다. PR 생성·CI 최종 판정은 호출자 몫이다.
