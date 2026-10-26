판정 기준: main e609c543

# P3-09 — 튜터 구조화 출력 스키마: 검증을 통과한 응답만 학생에게, `mastery_update_allowed`는 항상 false (2026-10-21)

- 태스크: `P3-09-tutor-output-schema` · 브랜치 `claude/p3-09-tutor-output-schema` (claim 1b5c5a26) · PR #1713
- 커밋:
  - 초판 구현 c06b8dcb · 초판 보고서 982fa2f5
  - PR #1713 독립 검토 반영 ad63ca98(코드) · 그다음 커밋(테스트 1건 + 이 개정본)
- 선행: `P3-08`(`docs/reviews/p3_08_tutor_context_builder_2026-10-20.md`) · `P3-72`(`docs/reviews/p3_72_tutor_slot_value_delivery_2026-10-20.md`)
- 정본 지시: `docs/strategy/phase3_math_eos_completion_instruction_set.md` [13] P3-09
- 산출 코드:
  - `src/backend/whymath_backend/harness/wh1_tutor_output.py` (신설 — 스키마·검증기 정본)
  - `src/backend/whymath_backend/harness/wh1_llm_policy.py` (1단계 집행 · 안전 강등 · 정답 억제 불변식 · 시스템 프롬프트)
  - `src/backend/whymath_backend/harness/wh1_loop.py` (1-b단계 — 개념 id 도구 단위 실패)
  - `src/backend/whymath_backend/harness/wh1_primary.py` (2단계 집행)
  - `src/backend/whymath_backend/api/coach.py` (3단계 집행 · 응답 필드 `tutor_output`)
  - `src/backend/whymath_backend/harness/wh1_shadow.py` (관측 필드 3종 · 결말 라벨 1종)
  - `scripts/analysis/eos_feature_inventory_v2.py` (신규 모듈을 WM-E-704에 귀속)
- 테스트:
  - `tests/backend/harness/test_wh1_tutor_output.py` (신설 · 176건)
  - `tests/backend/api/test_coach_tutor_output_schema.py` (신설 · 32건 = 두 핸들러 × 16)
  - `tests/infra/test_tutor_output_schema_gate.py` (신설 · 10건 — AST 집행 동결, stdlib만)
  - `tests/backend/harness/test_wh1_shadow.py` (관측 레코드 비식별 필드 허용 목록에 3종 추가)
- 새 Entity·DB 스키마·Alembic 0건. API 응답 변경은 필드 추가뿐이다(`tutor_output` — nullable, 하위호환).

## 0. 결론

acceptance ①~④를 **전부 충족**했다. PR #1713 독립 검토의 지적(중2·중1·하1~하5)은 전건 반영했다(§9 처리표).

이 회차의 실질은 스키마 신설이 아니라 게이팅이었지만, 실측해 보니 두 가지가 실제로 비어 있었다.
- 학생 대면 출력에 구조(진단·전략·다음 행동)도 `mastery_update_allowed` 개념도 없었다. main 코드에서 `mastery_update_allowed`는 0건이다.
- LLM 원시 출력 파서가 위반을 **조용히** 넘겼다. 실패 로그가 0건이었고, 상태 권위 주장 키는 무시됐고, `"1"`·`true`·`1.9`는 정수로 형변환됐다.

검토 과정에서 main에도 있던 교수학 결함 하나가 함께 드러나 고쳤다. **오답 턴에 LLM이 격려를 고르면 "좋아, 지금까지 잘 하고 있어"가 그대로 나가던 경로**다. 이제는 질문으로 강등된다(§4).

| acceptance | 판정 | 근거 |
|---|---|---|
| ① 구조화 스키마 고정 + 통과해야만 학생에게 | **충족** | 정본화는 `TutorTurnOutput`이다(§2). 집행은 4지점이며 두 핸들러가 모두 경유한다(§3) |
| ② `mastery_update_allowed` 항상 false 기계 동결 | **충족** | 타입 `Literal[False]` + `is False` 검사 · 빌더 미전달 · LLM 원시 출력 거부 · 승격 직전 재검증 · AST 전수 스캔(§4) |
| ③ 변별력 — 스키마 위반·mastery=true 주입 차단 | **충족** | 주입 결과는 §5, 뮤테이션 32종 전건 RED는 §6 |
| ④ 완료 판정 | **충족** | 검증 미통과 응답은 학생 응답 문자열(`decision.prompt`)·`tutor_output` 어디에도 없다. HTTP 테스트가 응답 본문 전체에서 표지 문자열 부재를 단언한다 |

## 1. 경로 실측 — LLM 출력이 학생에게 가기까지 (main e609c543 vs 이 브랜치)

학생에게 LLM 문자열이 나가는 서빙 경로는 **세션 핸들러 두 개뿐**이다: `create_session`·`append_turns` → `_wh1_primary_decision_or`. 역할 기반으로 찾았다 — `model_copy(update={"prompt"`, `run_wh1_primary_turn(`·`.coach(`·`rephrase_coach_utterance(` 호출측. 내가 찾은 방법으로는 그 밖의 학생 대면 LLM 발화 경로는 0건이다.

| # | 단계 | 코드 위치 | main e609c543 | 빈틈 | 이 브랜치 |
|---|---|---|---|---|---|
| 1 | LLM 호출 | `LLMTutorPolicy.next_action` → `Wh1LlmSeam`(라우터·캐시·Langfuse) | 있음 | — | 그대로 |
| 2 | JSON 추출 | `_extract_json` | 있음 | 실패 시 **로그 0**(침묵 강등) | 사유 `NOT_JSON_OBJECT` WARNING + 회계 |
| 3 | 스키마 판정 | 없음 | Pydantic 판별 유니온만 있었다. 여분 키는 조용히 버려지고, 극성 `"1"`·`true`는 정수로 형변환되고, 비문자열 발화는 None이 되고, 가중치는 무제한이었다 | 상태 권위 주장 무시 · 관대한 형변환 · 가중치 무제한 · 실패 로그 0 | `classify_action_payload` → `_reject`(사유 WARNING · 회계 · 안전 강등) |
| 3-b | 개념 id 인자 | 하네스 `_exec`(read/query) | 무동작 기록 | 환각 id도 성공(`ok=True`) | **그 도구만** `ok=False`(턴 계속) |
| 4 | 액션 구성 | `_build_action`(Pydantic) | 있음 | 예외 시 로그 0 | 예외 타입명을 사유로 WARNING |
| 5 | 불변식 | `_enforce_invariants` · 하네스 `_exec` | 있음(ARCH-60 C·D 동결) | 오답 턴에 LLM이 고른 **격려**를 유지했다 | 오답 턴 격려는 질문으로 강등 |
| 6 | 프로즈(기본 OFF) | `gate_policy_prose` · `rephrase_coach_utterance` | 있음(ARCH-60 B) | 길이 상한은 프로필 S에만 있다 | 7·8단계가 덮는다 |
| 7 | 금지모드 가드 · 톤필터 | `check_forbidden_modes` · `filter_tone` | 있음(ARCH-60 A) | 정책 자유발화의 길이 상한 0 | 그대로 |
| 8 | 구조화 출력 | 없음 | 러너는 문자열만 반환했다 | 구조 0 · `mastery_update_allowed` 0 | `build_tutor_output` → 검증 → 미통과면 `None` + `fallback_output_schema` |
| 9 | 승격 | `_wh1_primary_decision_or` | 있음(ARCH-59 ①·ARCH-60 G) | 승격 직전 재검증 0 | `check_deliverable` |
| 10 | 응답 조립 | 두 응답 모델 | `decision.prompt` | — | `tutor_output` 추가 |

판정 대상 밖인 비대면 경로:
- **shadow** — 비노출 관측. 1단계 판정은 적용된다. 개념 id 검사는 하지 않는다(허용 집합 없음 · 기존 동작).
- **stateless `POST /v1/coach`** — LLM 0.
- **`PolyaCoach.coach`** — API 호출측 0건(ARCH-60 E).
- **`run_persisted_turn`** — HTTP 미배선(§8).

## 2. 정본화 — 스키마 정의 위치

정의 위치는 `harness/wh1_tutor_output.py`다. `TutorTurnOutput`은 `extra="forbid"`·`frozen`·`strict`이고 판은 `tutor-output-v1`이다.

| 필드 | 타입 | 값의 출처(전부 서버) |
|---|---|---|
| `diagnosis.concept_id` | `str \| None`(≤ 120자) | 이번 턴 코치가 DB에서 PK로 조회한 PRIMARY 개념 code |
| `diagnosis.misconception_id` | `str \| None` — 카탈로그 정본에 있어야 한다 | **코치가 큐레이션한 초기 활성 가설**(응답 `active_hypotheses`와 같은 원천)의 최상위. 카탈로그 밖 id는 건너뛴다 |
| `diagnosis.confidence` | `float \| None`(0~1, bool 금지, 오개념 id가 없으면 None) | 그 가설의 신뢰도 |
| `response_strategy` | `guided_question`·`guided_hint`·`diagnostic_probe`·`encouragement`·`socratic_requestion` | 하네스 `end_turn` 행위 유형과 1:1(가드 대체는 `socratic_requestion`) |
| `hint_level` | `Literal[1,2,3,4] \| None`(bool·실수 금지) | 결정론 Polya 엔진의 `PedagogyDecision.hint_level` |
| `explanation` | `str`(1~400자, 보이는 문자 1개 이상) | 톤필터 산출물 = `decision.prompt` |
| `explanation_source` | `llm`·`harness_template` | LLM 작성(정책 명시 발화·프로즈 rephrase)인지, 하네스 결정론 템플릿(파생·강등·가드 재질문)인지 |
| `next_action` | `continue_dialogue`·`revise_solution`·`solve_probe` | 출제 → `solve_probe`, 오답·검증 불가 → `revise_solution`, 그 밖 `continue_dialogue` |
| `mastery_update_allowed` | **`Literal[False]`** + `is False` 검사 | 빌더가 넘기지 않는다 |

**모델 수준 검사.**
- **일관성:** `diagnostic_probe` ⇔ `solve_probe`. `revise_solution` 턴에는 `encouragement` 금지.
- **Literal 값 동등 차단:** `strict`도 `Literal`의 값 동등(`True == 1`·`2.0 == 2`·`0 == False`)은 막지 못해 타입 검사를 따로 걸었다.
- **보이지 않는 문자만 있는 발화 거부:** 범주 Cc·Cf·Zs·Zl·Zp와 한글 채움 문자를 지운 뒤 빈 발화면 거부한다.

**게이트 함수 수준 검사.**
- 진단 개념 id의 실재 대조는 `validate_tutor_output`·`check_deliverable`에 둔다. 모델 검증자에 두면 응답 직렬화 자리에서 모델이 깨진다 — 초판 때 HTTP 테스트 14건 RED로 실측했다.

**발화 길이 상한 400의 근거.** 하네스 파생 발화의 최장은 163자다(카탈로그 72종 전수 실측). 400은 그 약 2.5배다.

**LLM 원시 출력 판정(`classify_action_payload`) 사유 코드.**
- `STATE_AUTHORITY_CLAIM` — 키를 NFKC로 정규화하고, camelCase·구분자로 분리하고, 복수형을 단수화한 **단어**가 `mastery`·`proficiency`·`ability`·`competence`이거나, 연쇄 `skill level`이거나, 한글 조각 `숙달`·`능력치`·`숙련도`를 포함하면 주장이다. 중첩 dict·list까지 재귀한다. 예외는 정확히 `mastery_update_allowed: false` 하나다. `probability`·`capability`·`masterpiece`는 통과한다.
- `UNKNOWN_KIND` · `MISSING_FIELD` · `FIELD_TYPE`
- `FIELD_RANGE` — `log_evidence.weight` ∉ [0, 1], NaN, ±inf, 음수 `turns_elapsed`. 상한 1.0은 코치 경로 관례에서 왔다: `weight=match.confidence`(0~1), `_REFUTE_WEIGHT=0.5`, `_REFUTE_STRONG_WEIGHT=1.0`, None은 1.0 취급.
- `UNKNOWN_MISCONCEPTION_ID`(카탈로그 밖) · `NOT_JSON_OBJECT` · 구성 단계 예외 타입명
- 개념 id는 판정기가 보지 않는다 — 하네스가 그 도구만 실패시킨다(§3).
- 무해한 여분 키는 거부하지 않는다(액션에 실릴 자리가 없다 — ARCH-59 ③).

## 3. 집행 지점

| 단계 | 집행 지점 | 미통과 시 | 기계 동결(`tests/infra/test_tutor_output_schema_gate.py`) |
|---|---|---|---|
| 1 | `LLMTutorPolicy._parse_action` → `_reject` | 사유 WARNING · `output_rejections` 회계 · `_safe_fallback` | A |
| 1-b | 하네스 `_exec`(read_student_state·query_curriculum) ← 러너가 `known_concept_ids=policy.known_concept_ids`를 전달 | **그 도구만** `ok=False`(`CONCEPT_ID_REJECT_DETAIL`). 정책이 다음 도구를 고른다(턴 계속) | G |
| 2 | `run_wh1_primary_turn` — 톤필터 직후 `build_tutor_output`, 거부면 `return None` | 결정론 Polya 발화 · `fallback_output_schema` · `tutor_output_reason_code` · WARNING | B · H(진단 = `initial_hypotheses`) |
| 3 | `_wh1_primary_decision_or` — `check_deliverable`, 거부면 `return decision` | 결정론 발화 · `tutor_output=null` · WARNING | C |
| 배선 | 두 핸들러가 `output_receipt=`를 넘기고 응답에 `tutor_output=<영수증>.output`을 싣는다 | — | D |

시스템 프롬프트에 개념 id 규칙을 추가했다: 개념 id에는 `concept.code`만 쓸 수 있고, `concept.name`은 id가 아니며, code가 없으면 넣지 않는다.

관측 레코드에 세 필드를 추가했다.
- `llm_output_rejections` — 강등으로 이어진 거부 수
- `concept_id_tool_rejections` — 도구 단위 실패 수. primary만 기록하고, shadow는 검사가 없어 None이다
- `tutor_output_reason_code`

구판은 None이다.

## 4. 미통과 시 학생이 받는 것 — 교수학적 근거

| 상황 | 학생이 받는 발화 | 근거 |
|---|---|---|
| 환각 개념 id(이름 오용 등) | 그 도구만 실패한다. 이후 LLM이 고른 행동이 그대로 이어진다(오답 턴이면 정답 억제 백스톱이 하네스 질문을 낸다) | 무동작 도구의 잘못된 인자 하나로 턴을 닫지 않는다. main과 같은 발화임을 실측했다(§5) |
| 1단계 거부(강등) | 풀이 단계가 있고 미검증이면 `verify_step`. **오답·검증 불가 판정이면 질문**(하네스 소크라테스 개입 또는 중립 유도 "방금 단계에서 무엇을 근거로 그렇게 했는지 말해줄래?"). 정답·판정 없음이면 격려 템플릿 | 틀린 풀이에 "잘 하고 있어"라고 하지 않는다. 그렇다고 "틀렸다"는 부정 강화도 하지 않고 근거를 묻는다. 템플릿은 상수라 정답을 담지 못한다 |
| LLM이 오답 턴에 **격려**를 고름 | 정책 불변식이 질문으로 강등한다(main은 격려 템플릿을 그대로 냈다) | 같은 근거 |
| 2·3단계 거부 | 코치의 결정론 `PolyaCoach.decide` 발화 | 기존 폴백 경로다(신설 0) |

질문 강등을 `PolyaCoach.decide` 경로가 아니라 하네스 질문으로 한 이유: 하네스 질문은 활성 가설의 소크라테스 개입을 쓰고, 검토 재현 입력에서 main이 낸 발화와 **바이트 동일**하다. 강등이 기존 교수 행동을 바꾸지 않는다.

`mastery_update_allowed` 강제는 다섯 층이다.
1. **타입** — `Literal[False]` + `is False` 검사. 0·true는 생성되지 않는다.
2. **빌더 미전달** — 빌더는 이 필드를 넘기지 않는다. AST 전수 스캔(F)이 False 상수가 아닌 대입 0건을 단언한다.
3. **원시 출력 거부** — LLM 원시 출력의 false 아닌 값을 거부한다.
4. **승격 직전 재검증** — `model_construct` 우회도 잡는다.
5. **ARCH-59** — 구조적 집행(튜터 경로 mastery writer 0)을 담당하며, 이번에도 green이다.

## 5. 주입 결과

모두 hermetic이다(LLM 0·DB 0). 표지 문자열을 LLM 발화에 싣고, 학생 응답·로그에 그 표지가 없는지를 본다.

| 주입 | 층 | 결과 |
|---|---|---|
| `mastery_update_allowed: true`/`"false"`/`0`/`null`/`1` · 상태 축 키(중첩·전각·camelCase·복수형·`skill_level`·`숙달도`) | 판정·정책·러너·HTTP | `STATE_AUTHORITY_CLAIM` → 강등, 표지 0. 대조군 `probability`·`capability`·중첩 `mastery_update_allowed: false`는 통과 |
| 깨진 JSON · 필드 누락 · 타입 오류 | 판정·정책·HTTP | `NOT_JSON_OBJECT`·`MISSING_FIELD`·`FIELD_TYPE`, 표지 0 |
| `weight` 1e9·1.0000001·-0.1·NaN·±inf | 판정·정책 | `FIELD_RANGE`. 대조군 0·0.5·1은 통과 |
| **검토 재현** — 오답(x=3) · verify → `query_curriculum{"node_id":"일차방정식"}` → end_turn 질문 | 러너·HTTP 두 핸들러 | 도구만 실패(`concept_id_tool_rejections=1`·`llm_output_rejections=0`·`adopted`). 학생 발화 = "방금 단계에서 무엇을 근거로 그렇게 했는지 말해줄래?"(가설 있는 HTTP에서는 소크라테스 개입) — **main e609c543에서 같은 입력의 발화와 일치(실측)**, 격려 아님. `tutor_output` = (guided_question, revise_solution, harness_template) |
| 변형 — `read_student_state` 잘못된 id · 미매핑 턴(내용 요약 없음 + 실재 code) | 러너·HTTP | 같은 결과 |
| 오답 턴 강등 — 깨진 JSON · provider 장애 · LLM 격려 선택 | 러너·HTTP | 전부 질문(중립 유도). 대조군: 정답 턴 강등은 격려 |
| 진단 공격(`diag_attack.py`) — `log_evidence{-1, weight 1e9}` + curate | 러너 | 1e9는 `FIELD_RANGE`로 거부. 허용 범위 1.0으로 같은 공격을 해도 진단은 코치 큐레이션 최상위 그대로(0.9 A) |
| 존재하지 않는 concept_id(진단 변조) · 오개념 id | 2·3단계·HTTP | `UNKNOWN_CONCEPT_ID`·카탈로그 거부 |
| 카탈로그 밖 가설이 최상위 | 빌더 | 건너뛰고 다음 가설로 진단. WARNING(건수만). 출력 거부 0 |
| `hint_level` 0·5·`"2"`·`True`·`2.0` · `confidence: true` | 스키마 | 거부 |
| ZWSP·한글 채움·BOM+WJ+NBSP만 있는 발화 | 스키마 | 거부. 대조군 "ZWSP+글자"는 통과 |
| 과길이 발화(401자+) | 러너·HTTP | `None` → Polya 발화, `SCHEMA_STRING_TOO_LONG` |
| 영수증 변조(mastery True · 미조회 개념 · 발화 불일치 · 구조체 제거 · hint 9) | 3단계·HTTP | 거부 → 결정론 발화 · `tutor_output=null` |

## 6. 뮤테이션

절차: cp 백업 → 적용 단언(치환 대상 1건·sha 변화) → pytest → cp 원복 → sha256 단언. 하네스는 세션 스크래치 `mutate.py`다. 대상은 신설 3파일 + `test_wh1_loop.py` + ARCH-59·ARCH-60이다.

결과: **32종 전건 RED**. 초판 19종 — 초판 M12는 개념 id 검사가 하네스로 옮겨져 M21로 대체됐다 — 에 검토 반영 13종을 더했다.

| # | 뮤테이션 | 결과 |
|---|---|---|
| M01~M11·M13~M20 | 초판(판정 호출 제거·상태 주장 검사 제거·WARNING 제거·러너/코치 게이트 무력화·Literal 해제·재검증 생략·발화 일치 제거·개념 실재 제거·길이 상한 해제·응답 누락·hint 미전달·mastery True 주입·카탈로그 검사 제거·bool 극성 허용·영수증 초기화 제거·재검증 동어반복) | RED×19 |
| M21 | 하네스: query_curriculum 개념 id 검사 제거 | RED |
| M22 | 러너: 허용 개념 집합 미전달 | RED |
| M23 | 정책: 오답 턴 강등의 질문 분기 제거 | RED(**1차 실행에서 생존** — §6-1) |
| M24 | 스키마: 다시 살펴볼 턴 격려 금지 검사 제거 | RED |
| M25 | 판정: 증거 가중치 범위 검사 제거 | RED |
| M26 | 스키마: 보이지 않는 문자 검사 → strip() | RED |
| M27 | 스키마: hint_level 정수 타입 검사 제거 | RED |
| M28 | 판정: 상태 키 단어 비교 → 부분 문자열 | RED |
| M29 | 판정: 중첩 재귀 제거 | RED |
| M30 | 러너: 진단을 턴 안 LLM 큐레이션 세트로 | RED |
| M31 | 빌더: 카탈로그 밖 가설 건너뛰기 제거 | RED |
| M32 | 러너: 발화 저자 항상 llm | RED |
| M33 | 스키마: mastery `is False` 검사 제거 | RED |

### 6-1. M23 생존과 처리

1차 실행에서 M23이 살아남았다. 원인은 픽스처가 그 절을 밟지 않은 것이다.
- 깨진 JSON 강등은 `next_action`이 `_enforce_invariants`를 거치므로, 이번에 고친 불변식(오답 턴 격려 → 질문)이 대신 막는다.
- 불변식을 **거치지 않는** 강등 경로는 provider 장애 하나다(`return self._safe_fallback(state)`).

그 경로를 밟는 픽스처(`test_provider_failure_on_wrong_answer_asks_instead_of_encouraging` — verify 뒤 provider 장애)를 추가했고, 재실행에서 RED가 됐다.

## 7. 검증 (exit code · 검토 반영 커밋 ad63ca98 기준)

CI 잡을 전수 열거한 뒤 닿는 잡을 골라 재현했다: backend·infra-contracts·harness-integrity·declared-unwired-audit·policy-guard 일부. 닿지 않는 잡의 판정:
- data-pipeline·mobile·web·webapp·docker-build·infra-shell·concept-reach-guard·corpus-authoring — 변경 경로 밖이다.
- backend-migrations — DB 변경이 0이다.

| 검사 | exit |
|---|---|
| ruff · black --check(line 100) · mypy --strict(807) · lint-imports(4 kept) | 0 · 0 · 0 · 0 |
| backend 전체 pytest(CI 명령 그대로 · 실행 중 트리 무변경): 21,879 passed · 713 skipped · 1 xfailed · 커버리지 87.73% | 0 |
| 계층별 커버리지 게이트 | 0 |
| 게이트 CLI 20종(coach_prose_leak · pedagogy_pack_fidelity 포함) + declared_unwired_audit | 전건 0 |
| infra-contracts: ruff · black · runbook · mastery_write_path_scan · upper bounds · ci_constraints · pytest tests/infra(3,231 passed) · test_idempotency | 전건 0 |
| harness-integrity: backlog validate · audit-deps · rules lint/render · jit check · audit_ratchet(차단 0) | 전건 0 |
| policy-guard: cp949_guard · conflict markers | 0 · 0 |
| 뮤테이션 32종 | 전건 RED |

`coach_prose_leak` 처리 경위: 검토 반영 중간 상태(스키마 일관성 검사만 추가)에서 이 게이트가 exit 1이었다(clean 셀 오차단 4/16). 원인은 이 게이트의 rephrase 셀이 **오답 턴에 LLM이 격려를 고르는** 시나리오를 쓰기 때문이다. 일관성 검사가 그 격려를 출력 단계에서 거부하자 프로즈 오차단으로 집계됐다.

게이트 픽스처를 고치지 않고, **원천인 정책 불변식**에서 오답 턴 격려를 질문으로 강등했다. 질문은 파생 템플릿이 중립 유도(`REPHRASABLE_TEMPLATES` 구성원)라 rephrase 경로가 그대로 돈다. 재실행 결과 exit 0, 오차단 0이다.

**검토 반영 뒤 추가된 것은 테스트 1건(M23 픽스처)이다.** 전체 스위트 이후에 추가했으며, 해당 파일 실행(176 passed)과 M23 재실행으로 확인했다.

못 돌린 검사:
- `tests/constitution/test_check_signed_changes.py` — 이 환경에 ssh-keygen이 없다. 34건이 환경 원인으로 실패했고, 나머지 39건은 exit 0이다.
- harness-integrity의 원격 의존 스텝 — ADR fetch·claims reap·branches·헌법 서명 검증.
- 실 PG 통합 테스트(기본 skip · 이번 변경은 DB 접근 0).

위 항목들은 CI가 최종 판정한다.

## 8. 한계·남은 위험

- **라이브 폴백률 미측정.** 1단계 판정이 엄격해졌다(형변환·범위·상태 키). 다음 라이브 측정에서 `llm_output_rejections`·`concept_id_tool_rejections`·결말 분포로 확인해야 한다. 안전은 불변이고 품질만 손실될 수 있다.
- **오답 턴 격려 → 질문 강등은 main 대비 행동 변경이다**(의도된 교수학 정정). LLM이 오답 턴에 격려를 고르던 빈도는 미측정이다.
- **카탈로그 밖 가설 id(검토 하5) 실측 불가.** DB 적재 상태를 이 환경에서 조회할 수 없다. `get_active_hypotheses`는 카탈로그 필터 없이 DB를 그대로 로드한다(코드 확인) — 카탈로그에서 id가 빠지면 생길 수 있는 상태다. 대책으로 빌더가 진단 후보에서 건너뛰므로(WARNING 건수) 출력 거부는 지속되지 않는다. 발생 빈도는 그 WARNING으로 관측해야 한다.
- **in-memory 가설 세트는 여전히 LLM 증거의 영향을 받는다.** 진단에는 쓰지 않지만, 프로즈 rephrase의 가설 라벨(`outcome.hypotheses[0]`, 기본 OFF)과 shadow 관측에는 쓰인다. 가중치는 [0, 1]로 제한했다.
- **2단계 개념 대조는 러너 안에서 동어반복이다.** 실질 변별은 3단계에 있다(M20).
- **`run_persisted_turn`(HTTP 미배선)은 LLM이 고른 `log_evidence`를 DB에 영속하는 좌석이다.** 배선되면 1단계 판정(가중치 범위 포함)은 적용된다. 증거 영속 자체의 권위 판정은 배선 태스크가 해야 한다.
- **`tutor_output`을 소비하는 클라이언트는 아직 0이다**(필드 추가뿐이라 하위호환).
- **뮤테이션 전건 RED는 커버리지의 증거가 아니다.** M23 1차 생존이 그 사례다.

## 9. PR #1713 독립 검토 처리표

| # | 지적 | 처리 | 근거·검증 |
|---|---|---|---|
| 중2 | `UNKNOWN_CONCEPT_ID`가 오답 턴을 격려로 닫음(main 대비 회귀) | **수용·전부 반영** (a) 개념 id 거부를 정책 강등에서 하네스 도구 단위 실패로 이동 (b) `_safe_fallback`이 오답·검증 불가면 질문, 정책 불변식도 오답 턴 격려를 질문으로 강등 (c) 시스템 프롬프트에 허용 id 규칙, shadow는 허용 집합 없음 = 검사 없음(기존 동작), 전략·다음 행동 일관성 검증 추가 | 재현 입력과 변형 2종이 러너·HTTP 두 핸들러에서 RED→GREEN, main 발화와 일치(실측). M21~M24 RED |
| 중1 | LLM 증거로 진단이 뒤집힘 · weight 무제한 | **수용 + 강화**: weight [0, 1]·NaN·inf 거부(관례 근거 §2). 문구 정정 대신 **진단 원천을 코치 큐레이션 초기 활성 가설로 바꿔** LLM 영향 자체를 제거하고 문구를 그에 맞게 고쳤다(`wh1_tutor_output` docstring·`_TUTOR_OUTPUT_DESC`) | `diag_attack.py` 재실행: 1e9 거부, 1.0으로도 진단 불변. M25·M30 RED |
| 하1 | Literal이 strict 아님 | **수용**: `hint_level`·`confidence`·`mastery_update_allowed`에 타입 검사 | M27·M33 RED |
| 하2 | 보이지 않는 문자 발화 통과 | **수용**: Cc·Cf·Z*·한글 채움 제거 후 빈 발화 거부 | M26 RED, 대조군 통과 |
| 하3 | 부분 문자열 거짓 양성 | **수용**: 단어 단위·NFKC·camelCase·복수형·한글 조각·중첩 재귀 | probability·capability 통과. M28·M29 RED |
| 하4 | LLM 발화 vs 하네스 강등 발화 구분 | **수용**: `explanation_source: llm \| harness_template` | M32 RED |
| 하5 | 카탈로그 밖 가설 id 재로드 | **실측 불가 → 완화 + 한계 기재**: 진단 후보에서 건너뜀(WARNING) | M31 RED · §8 |
