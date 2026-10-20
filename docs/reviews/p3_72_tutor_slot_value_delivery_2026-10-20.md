판정 기준: main 7f091d73

# P3-72 — 튜터 슬롯 값 전달(개념·스킬·문제 구조·팩 요약)과 전달 경로 분리 (2026-10-20)

- 태스크: `P3-72-tutor-slot-value-delivery` · 브랜치 `claude/p3-72-tutor-slot-value-delivery` (claim ad3e761a)
- 커밋: 구현 2c9d43c4 · 주석 정정 ce1ade2a · 보고서 5fbe40fd · PR #1709 독립 검토 반영 522fc404 · 이 개정
- 선행: `P3-08` — 보고서 `docs/reviews/p3_08_tutor_context_builder_2026-10-20.md`
- 근거 결정: Kiki 결정 (가) 2026-10-20 — 튜터 LLM 프롬프트에 싣는 것은 개념·스킬·문제 내용·교수 정책(pack) 요약뿐이다. 학생 개인 학습 데이터(θ·숙달도·mastery 수치와 그 파생 라벨)는 프롬프트에 싣지 않는다(서버 사적 보유는 허용).
- 산출 코드:
  - `src/backend/whymath_backend/harness/wh1_tutor_context.py` — 경로 enum·내용 요약 타입·선택 규칙
  - `src/backend/whymath_backend/harness/wh1_llm_policy.py` — 요약 렌더·실측 prompt 경로 회계·시스템 프롬프트 정정
  - `src/backend/whymath_backend/harness/wh1_primary.py` — 턴 뒤 실측으로 경로 확정
  - `src/backend/whymath_backend/api/coach.py` — 요약 조회(PK 단건·SAVEPOINT·허용 열 SELECT)
- 테스트:
  - `tests/backend/harness/test_wh1_tutor_slot_delivery.py`(신규 62건 — 검토 반영 +24)
  - `tests/backend/api/test_coach_tutor_context.py`(P3-72 신규 18건(파라미터 포함 수집 기준) + 대조군 기대 갱신 — 초판의 '14건'은 오기였다)
  - `tests/backend/api/test_coach_tutor_content_integration.py`(신규·실 PG 통합 3건 — 검토 중2)
  - `tests/backend/harness/test_wh1_tutor_context.py`(경로 API로 갱신)
- 새 Entity·스키마·Alembic 0 · 새 모듈 0(인벤토리 귀속 변화 0) · 응답은 필드 추가만(`delivery_paths` — 하위호환)

## 0. 결론

acceptance ①~⑦ 중 결정 (가)가 대체한 항목(① '숙달 라벨' 문구·② 개인정보 게이트)을 빼고 **전부 충족**했다. PR #1709 독립 검토(상 0·중 2·하 3·추가 1)는 전건 반영했다(§10). 남은 위험은 §9에 적었다. 가장 큰 것은 오개념 가설의 confidence(학생별 진단 추정치)가 P3-08 이전부터 프롬프트에 실려 왔다는 사실이다. 결정 (가)의 열거(θ·숙달도·mastery)에는 들어 있지 않아 이번에 바꾸지 않았고, Kiki 판단 대상으로 올린다(§9-1).

| acceptance | 판정 | 근거 |
|---|---|---|
| ① 개념·스킬·팩 요약 전달 + 매니페스트가 실제 전달로 표기 | **충족** ('숙달 라벨'은 ⑤가 대체) | 문제 구조 요약도 함께 전달한다. 표기는 정책이 좌석에 **실제로 넘긴** 프롬프트의 렌더 키에서 계산한다(§1·§7 M08·M09) |
| ② 개인정보 결정 게이트 | **결정 (가)로 대체** | — |
| ③ 순회 시 ARCH-11 guard · 예산 불변 | **충족** | 새 순회 0 — PK 단건 조회 3종뿐이다(§6). 노드 ≤ 20·토큰 ≤ 3000 불변이며 선택 규칙을 문서화하고 테스트로 동결했다(§3) |
| ④ 게이트 CLI exit 0 · 슬롯 제거 뮤테이션 RED | **충족** | 게이트 20종 + declared_unwired 전건 exit 0(§8). 슬롯 4종 제거 M01~M04 RED |
| ⑤ θ·숙달은 클라우드 LLM 금지 · 주입하면 RED | **충족** | 숙달 경로 = none. θ는 private_tool. 주입 뮤테이션 M05~M07 RED |
| ⑥ 프롬프트·시스템 프롬프트에 θ·숙달 값·파생 라벨 부재 단언 | **충족** | 단위 테스트(정책·러너)와 HTTP(두 핸들러 × 숙달 원천 3종)가 단언한다(§2) |
| ⑦ 경로 분리 · context_not_delivered 설명 정정 · grade 판정 | **충족** | `delivery_paths` 신설(§1), 시스템 프롬프트 정정(§2), grade는 미전달(§4) |

## 1. 슬롯별 전달 경로표 (완비 턴 · 금지모드 가드 OFF 기본)

경로 정의:
- `prompt` — LLM 프롬프트 문자열에 실림. 클라우드 좌석으로 나갈 수 있는 유일한 경로다.
- `private_tool` — 정책·하네스가 사적으로 보유하고 도구 실행에만 쓴다. 프롬프트에는 없다.
- `output_guard` — 출력 후처리 필터가 실제로 소비했다. 교수법 팩 금지모드 가드가 **판정을 낸** 턴만 해당한다.
- 빈 목록 — none(미전달).

`delivered_to_tutor`는 `bool(delivery_paths)`로 파생된다. 기존 필드는 유지했고, 검증자가 둘의 불일치를 거부한다.

| # | 슬롯 | P3-08(main 7f091d73) | P3-72 경로 | 프롬프트에 실리는 내용 |
|---|---|---|---|---|
| 1 | learner_state | delivered (θ 사적) | `private_tool` | 없음. θ는 select_probe 정보량 계산 전용이고, 학년은 어디에도 전달하지 않는다 |
| 2 | concept | not_delivered | `prompt` | 개념 code·한국어 이름 |
| 3 | skill | not_delivered | `prompt` | 스킬 총수 + 이름 ≤ 5 |
| 4 | problem | not_delivered | `prompt` | 문항 구조: question_format·bloom_level·has_visual·condition_count |
| 5 | student_answer | delivered (사적) | `private_tool` | 없음(match_misconception 인자 전용) |
| 6 | solution_record | delivered (사적) | `private_tool` | 없음(verify_step 인자 전용) |
| 7 | misconception | delivered | `prompt` + `private_tool` | 가설 id·한국어 라벨·confidence(기존 S1-a 동작). 하네스도 curate/log 도구용으로 보유한다 |
| 8 | mastery | not_delivered | none | 없음 — 결정 (가). 검증자가 prompt 경로를 거부한다 |
| 9 | pedagogy_policy | 가드 ON일 때만 delivered | `prompt` (+ 가드가 판정한 턴은 `output_guard`) | 지식 유형·스텁 여부·금지 모드(폐쇄 어휘). 발문 템플릿 본문은 싣지 않는다 |

판정 원천(핸들러 추정 0):
- `prompt` — `LLMTutorPolicy.prompt_slots_sent`. 좌석에 넘기기 직전, 실제로 렌더된 요약 dict의 키에서 계산해 턴 내내 합집합으로 모은다.
- `private_tool` — 정책 보유값(`private_context_slots`: 공백이 아닌 답안·단계, 0.0으로 채우지 않은 θ)과 `run_tutoring_turn`에 넘긴 바로 그 초기 가설 목록이다.
- `output_guard` — `check_forbidden_modes`가 예외 없이 반환한 턴만 센다.
- 확정 시점 — **턴이 끝난 뒤**(`wh1_primary._settle`). 모든 결말에서 관측 emit 직전에 확정한다: 정상·예산 소진·프로즈 거부·예외/타임아웃.
- 턴 전 공개 — 같은 렌더러의 계획값으로 프롬프트에 공개한다. 실측이 계획과 다르면 WARNING을 남기고 실측으로 표기한다.
- 턴 도중 match→curate 도구가 만든 가설은 도구 *출력*이지 context 슬롯(초기 가설)이 아니다. 그래서 초기 가설이 0인 턴에서는 misconception의 prompt 경로로 세지 않는다(M20).

응답 `tutor_context.slots[*].delivery_paths`와 로그 1줄(`… · 프롬프트 n: 슬롯명`)이 같은 판정을 싣는다.

prompt 경로는 **토큰 절단 뒤 최종 요약**에서만 계산한다. 가설이 예산으로 전부 잘린 프롬프트는 misconception을 prompt로 세지 않는다(검토 하1 X5). 요약 dict는 리스트 복사본을 싣는다 — 예산 루프가 원본을 pop해도 이미 조립한 요약이 사후에 바뀌지 않는다.

**공지 — 관측 분포 변화**: P3-72부터 `delivered_to_tutor`의 분포가 바뀐다. pedagogy_policy는 가드 OFF여도 true(prompt)이고, concept·skill·problem은 true가 된다. misconception의 의미도 바뀌어 prompt + private_tool 두 경로를 갖는다. P3-08 기준으로 `delivered_to_tutor`·`not_delivered`를 집계하던 관측 대시보드·리포트는 이 날짜를 경계로 분포가 달라진다(완비 턴의 `not_delivered` 5종 → mastery 1종).

## 2. 프롬프트 전후 예시 — 학생 데이터 없음 확인

같은 입력을 썼다:
- θ = 0.4137, 서버 숙달 = 0.5813, 학년 = 11
- 답안 "x+1=3 이니까 x=2", CONCEPT 팩, 가설 1건(distribution-over-power)

스크립트로 첫 프롬프트를 캡처했다. "전"은 main 7f091d73을 `git archive`로 떠서 실행했다. 전후 모두 프롬프트·시스템 프롬프트 전체에서 다음 문자열을 찾았고 0건이었다(exit 0):
- θ·숙달 값: 0.4137·0.41·0.5813·0.58
- 파생 라벨: 숙달·초보·발전 중
- 학년

**전(main 7f091d73)** — 요약 꼬리:

> "context_not_delivered": ["concept", "skill", "problem", "mastery", "pedagogy_policy"]

시스템 프롬프트(전):

> context_not_delivered는 서버에는 있으나 당신에게 주어지지 않은 정보입니다. 그 정보를 아는 것처럼 추측하지 마세요.

**후(이 브랜치)** — 요약 꼬리(앞부분 turn_index … verify_obligation_pending은 전과 같다):

> "context_not_delivered": ["mastery"],
> "context_held_privately": ["learner_state", "student_answer", "solution_record"],
> "concept": {"code": "math.algebra.linear-equation", "name": "일차방정식"},
> "skills": {"count": 1, "names": ["등식의 성질로 이항하기"]},
> "problem": {"question_format": "단답형", "bloom_level": "APPLY", "has_visual": false, "condition_count": 2},
> "pedagogy_policy": {"k_type": "CONCEPT", "is_stub": false, "forbidden_modes": ["WORKED_EXAMPLE_FIRST"]}

시스템 프롬프트(후 — 정정분):

> context_held_privately는 하네스가 사적으로 보유해 도구 실행(verify_step·match_misconception·select_probe 등)에만 쓰는 정보입니다 — 사적 보유분은 존재만 알려 줄 뿐 그 내용은 당신에게 보이지 않습니다. 보이지 않는 정보를 아는 것처럼 추측하지 마세요.
>
> 문항 요약: concept·skills·problem·pedagogy_policy는 이번 문항의 비식별 요약입니다(개념 이름·스킬 이름·문항 구조·교수법 유형). 정답·풀이·지문은 들어 있지 않습니다 — 요약으로 정답을 추측해 말하지 마세요. pedagogy_policy.forbidden_modes는 이 유형에서 쓰지 말아야 할 교수 방식입니다.

**⑥ 동결 집행 지점** — 문자열 단언 3겹과 구조 1겹이다:
1. 정책 단위 테스트 `test_theta_and_mastery_never_reach_prompt_or_system`
2. 러너 테스트 `test_paths_match_what_the_runner_actually_sent_and_held` — 턴의 모든 프롬프트를 본다
3. HTTP 테스트 `test_prompt_carries_content_summary_but_no_student_learning_data` — 두 핸들러 × 숙달 원천 3종(서버·`mastery_level="숙달"`·`bkt_mastery`), 턴의 모든 프롬프트·시스템 프롬프트

세 테스트 모두 같은 것을 단언한다. **1차 축은 검토 중1 반영으로 바뀌었다** — 금지 키·감시 값 열거는 표기 변형(소수 1자리 반올림·다른 키 이름·하위 키·새 필드)에 뚫렸다(검토자 사본에서 X1~X4 생존).
- **키 트리 허용 목록**: 렌더된 요약 dict의 키 트리 전체 경로(`a.b`·`a[]`·`a[].b`)가 허용 목록(`ALLOWED_PROMPT_KEY_PATHS` — 48경로) 안에 있어야 한다. 모든 선택 키가 실리는 최대 픽스처에서는 허용 목록과 **정확히 같아야** 한다(양방향 — 키 하나의 추가·누락 모두 RED). 정본은 하네스 테스트 1곳이고, HTTP 테스트는 같은 정본을 파일 경로로 적재한다(복제 0).
- **수치 잎 감시**: 파싱된 요약의 수치 잎(bool 제외)이 θ·서버 숙달·클라 숙달(`bkt_mastery`)의 ±0.05 근방이 아니고, 학년 값(11)과도 같지 않다. 문자열 형태가 아니라 값으로 보므로 반올림 표기 변형에 뚫리지 않는다.
- 보조 축(기존): 금지 키 이름 7종 부재 · 값 표기 4형 부재 · 숙달 라벨 3종과 "학년" 부재(두 문자열 전체).

구조 축:
- `TutorContentSummary`·`ConceptBrief`·`SkillBrief`·`ProblemBrief`·`PackBrief`의 `model_fields`를 **정확 집합**으로 동결한다(필드 신설·삭제 RED). `extra="forbid"`는 *입력*의 여분 키만 막고, 필드 선언을 늘리면 그대로 통과하기 때문이다(검토 X4).
- `PROMPT_FORBIDDEN_SLOTS` 검증자(학생 상태·숙달은 `prompt` 경로 불가)는 **표기 정직성 장치이지 전송 차단 장치가 아니다**. 정책은 내용 요약 4키와 가설만 슬롯으로 매핑하므로, θ를 다른 키로 프롬프트에 넣어도 이 검증자는 런타임에 발동하지 않는다. 전송 차단을 집행하는 것은 위의 타입 필드 동결과 키 트리·수치 잎 테스트다.

## 3. 예산·선택 규칙 (Minimal Reasoning Subgraph 불변)

| 상한 | 값 | 넘칠 때 규칙 |
|---|---|---|
| 노드 총합 | ≤ 20 (`_MAX_CONTEXT_NODES`) | 내용 요약 노드(개념 1 + 실린 스킬 이름 수, 최대 6)가 **먼저** 차지한다. 가설+match는 남은 자리(≥ 14)를 confidence 내림차순으로 나눈다(결정론 tiebreak 기존과 같음). 절단 수는 `omitted_count`에 남긴다 |
| 토큰 | ≤ 3000 (문자/4 근사) | 기존 순서 그대로: 세션 회상 → history → 저confidence 가설 → match id. **내용 요약은 자르지 않는다** — 누락 표기 키와 같은 지위의 고정 필드다 |
| 개념 code | ≤ 120자 | 넘으면 code를 **싣지 않는다**(잘린 id는 다른 id라 도구 인자로 쓰이면 오류) |
| 개념·스킬 이름 | ≤ 60자 | 자르고 '…' |
| 스킬 이름 | ≤ 5 | skill_id 오름차순 앞 5개. 총수는 `count`. 조회도 그 5개만 한다 |
| 금지 모드 | ≤ 8 | 팩 순서 앞 8개 |
| 조건 수 | 0..20 | 20에서 자름 |

요약을 자르지 않아도 되는 근거는 상한이 타입에 박혀 있다는 것이다. 최악 입력(모든 문자열 상한 초과·스킬 30·금지 모드 30)의 렌더 크기를 테스트가 **1,600자(≈ 400토큰) 이하**로 단언한다. 최대 압력(가설 30·history 30·회상·표기 키 9종 × 3)에서는 다음을 단언한다:
- 토큰 ≤ 3000
- 노드 총합 ≤ 20
- 요약 4키 생존
- `context_truncated=true`

뮤테이션 M14(선점 제거)·M15(정렬 제거)·M19(요약 우선 절단)가 각각 RED다.

## 4. 학년(grade) 전달 판정 — **보내지 않는다**

- **식별성**: CLAUDE.md 금기 "학교·학년 정보로 개인 식별 가능한 분석 결과 외부 노출 금지"에 닿는다. 학년은 `user_profile`의 학생 속성이다. 클라우드 좌석(openrouter·US)으로 나가는 문자열에 실으면 문항 요약·가설과 결합해 준식별자가 된다.
- **필요성**: 정책의 유일한 일은 8개 도구 중 하나를 고르는 것이다. 학년이 그 선택을 바꿀 근거가 없다.
  - 학년별 표현 조정은 결정론 `decide`(PED-05 개인화 슬롯·비노출)와 L4 톤필터·F7 검출기가 맡는다.
  - 문항 수준은 이미 개념 code와 구조(bloom_level)에 반영돼 있다.
- **결정 (가)와의 관계**: 학년은 학습 데이터가 아니라 프로필이다. 그러나 "기본은 보내지 않는 쪽이 안전"이라는 지시에 따라 미전달로 둔다. 필요성이 실측으로 생기면 학년 숫자만 싣는 변경을 별건으로 올린다.
- **집행**:
  - `learner_state` 슬롯의 경로는 `private_tool`(θ)뿐이고 prompt는 검증자가 거부한다.
  - 요약 타입에 grade 필드가 없다.
  - ⑥ 동결 테스트가 키 `grade`와 문자열 "학년"의 부재를 단언한다.
  - `_tutor_content_for`는 grade를 인자로 받지도 않는다.
  - 성취기준 고시코드(`_standard_code_for`)도 싣지 않는다.

## 5. 교수학 안전 — 정답 억제 계약 유지

- **조회 헬퍼는 실제로 실행해서 검증한다**(검토 중2). 종전 HTTP 테스트는 헬퍼 3종을 전부 monkeypatch로 대체해, 헬퍼 본문이 한 번도 실행되지 않았다. 이제 두 층으로 본다:
  - hermetic — 기록 세션이 헬퍼가 실제로 던진 문을 PG 방언으로 컴파일해 캡처한다. 엔티티 전체 로드(`session.get`)는 즉시 실패한다. 단언: 정답 열 미조회·스킬 id 오름차순 앞 5개만 `IN`·조건 수 20 절단·(code, 이름) 순서(X7~X10 RED).
  - 실 PG 통합(`test_coach_tutor_content_integration.py`) — 개념·스킬 7개·문항(정답·해설·지문에 표지 문자열)을 적재하고 헬퍼를 그대로 돌린다. 로컬 검증: PG 16 임시 인스턴스에 해당 6테이블을 ORM 메타데이터로 만든 뒤 `WHYMATH_RUN_INTEGRATION=1`로 3 passed(enum 열이 문자열 값으로 돌아옴 확인). CI에서는 `backend-migrations` 잡(마이그레이션 head)이 돈다.
- **문제 요약은 구조만 싣는다.** `api/coach._problem_brief_query`는 허용 열 4개만 SELECT한다(question_format·bloom_level·has_visual·condition_count). 다음 열은 **조회 자체를 하지 않는다**: 지문(question_text·_md)·보기(choices)·정답(answer)·해설·multiple_answers·오답 선지→오개념 매핑(distractor_map — 이것은 오개념 preload이기도 하다)·answer_constraint/transform·answer_format·conditions_parsed. 테스트는 문자열 금지 목록이 아니라 **구성된 SELECT의 실제 열 집합**을 대조한다. 정답 열을 더하는 M16이 RED다.
- **지문을 싣지 않는 이유 둘**:
  1. 지문·보기·정답 형식은 정답 경로를 좁힌다.
  2. 튜터 호출은 `data_licenses=SELF_AUTHORED_CORPUS`로 라우팅된다. 문항 본문은 출처별 라이선스가 따로 있어, 실으면 그 선언이 거짓이 된다. 개념·스킬 이름은 자체 저작 그래프, 팩은 자체 저작, 문항 구조는 우리가 붙인 분류라 등급 선언이 참으로 남는다(`check_routing_data_grade` exit 0).
- **정답 억제 코드 경로는 그대로다**(정책 `_enforce_invariants` + 하네스 `_end_turn_utterance` 백스톱). 요약이 실린 상태에서도 오답 판정 뒤 LLM 발화를 걷어 내는지 `test_answer_suppression_still_holds_with_content`로 재확인했다. 시스템 프롬프트에 "요약으로 정답을 추측해 말하지 마세요"를 추가했다.

## 6. 그래프 순회 · ARCH-11 판정

새 그래프 순회는 **없다**. 추가 조회는 P3-08이 이미 해소한 id에 이름표를 붙이는 PK 조회 3종뿐이다:
- 개념 1행
- 스킬 ≤ 5행(`IN`)
- 문항 1행

세 조회 모두:
- SAVEPOINT 안에서 돈다.
- 실패하면 해당 슬롯을 프롬프트 미전달로 남기고 예외 타입명을 WARNING으로 남긴다(M21·M23 RED).
- **튜터 호출이 확정된 턴(`tutor_invoked`)에만** 돈다(검토 하3). 완료 상태머신이 가로챈 턴과 primary OFF 턴은 조회 0이다(X13 RED). `_tutor_context_for`는 P3-08의 개념·스킬 조회 결과를 함께 돌려주고, 핸들러는 그것을 재사용해 요약을 만든다(개념·스킬 재조회 0).
- 개념 code는 `_pack_for`의 조회를 재사용하지 않았다. 이름(`name_ko`)이 어차피 조회 1건을 요구하고, code는 같은 SELECT에 함께 실린다 — 재사용해도 쿼리 수가 줄지 않는다. 반면 `_pack_for`의 반환형을 바꾸면 PED-01 호출부 전부가 닿는다.

`query_curriculum`은 여전히 실제 순회를 하지 않는다. 그래서 ARCH-11 traversal guard(visited·timeout·token budget)는 이번에도 동반 대상이 아니다. 기존 서빙 경로 가드도 P3-08 동결 테스트가 그대로 초록이다: 선수 traversal depth ≤ 2, 웜스타트 상한 12 ≤ 20, 오개념 preload 0.

## 7. 뮤테이션 (cp 백업 → 적용 단언(count==1·sha 변화) → pytest → cp 원복 → sha256 동일 단언)

하네스: 세션 스크래치 `run_mutations.py`. 대상 테스트 4파일, `-x`. 셸 이스케이프를 배제한 순수 Python이다.

| # | 뮤테이션 | 결과 |
|---|---|---|
| M01~M04 | 전달 슬롯 제거(concept·skills·problem·pedagogy_policy) | RED×4 |
| M05 | θ 프롬프트 주입(키 `theta`) | RED |
| M06 | 숙달 파생 라벨 주입(`"숙달"`) | RED |
| M07 | θ 값 위장 키 주입(`ability_hint: round(θ,2)`) | RED |
| M08 | 경로 판정 상수화(렌더 무관 전부 prompt) | RED |
| M09 | 실측 대신 계획값으로 prompt 경로 | RED |
| M10 | 가드 예정을 실행으로 셈(발화 없음 턴) | RED |
| M11 | 가드 예외도 실행으로 셈 | RED |
| M12 | 시스템 프롬프트 정정 되돌림 | RED |
| M13 | 사적 보유 공개 제거 | RED |
| M14 | 노드 예산 선점 제거 | RED |
| M15 | 스킬 선택 정렬 제거 | RED |
| M16 | 문제 요약 SELECT에 정답 열 추가 | RED |
| M17 | 결정 (가) 검증자 제거 | RED |
| M18 | 전달 비트 파생 검사 제거 | RED |
| M19 | 토큰 루프가 요약을 먼저 절단 | RED |
| M20 | 턴 중 도구 가설 필터 제거 | RED |
| M21 | 내용 조회 SAVEPOINT 제거 | RED |
| M22 | 내용 조회 게이트 상수화 | RED |
| M23 | 이름 조회 실패에도 스킬 수 전달 | RED |
| M24 | `with_delivery` 슬롯 재검증 생략(model_copy) | **생존 — 등가 뮤턴트** |
| M25 | 핸들러가 요약을 러너에 안 넘김 | RED |
| M26 | 러너가 정책에 요약을 안 넘김 | RED |

- 결과: **25/26 RED**. 적용·원복 단언은 26/26 통과했다.
- 하네스 결함 1건: M24의 첫 실행은 black 재포맷 때문에 앵커가 0건이 되어 **미적용**이었다. 하네스가 이를 APPLY-FAIL로 셌고, 앵커를 고쳐 재실행했다.
- M24 생존의 실측 원인: 매니페스트 생성자(`TutorContextManifest(slots=…)`)가 슬롯 인스턴스를 다시 검증한다. 그래서 명시적 재검증을 빼도 결정 (가) 거부가 같은 `ValueError`로 선다(실측: model_copy로 만든 MASTERY·prompt 슬롯을 매니페스트에 넣으면 `ValidationError`). 보호가 빠진 것이 아니라 **이중**이다. 코드 주석이 "model_copy는 검증자를 돌리지 않는다"라고 단정하고 있어 사실대로 정정했다(ce1ade2a).
- 픽스처 접촉 1건 보정: `test_turn_started_misconception_from_tools_is_not_a_context_slot`의 첫 판은 match 도구만 돌려 가설이 0건이었다. 그래서 M20이 지우는 절을 밟지 않았다. match→curate와 실제로 매칭되는 입력으로 바꾸고, 정책의 `prompt_slots_sent`에 misconception이 들어갔음을 단언해 접촉을 증명했다.

**검토 반영 후 재실행(522fc404)** — 위 26종(24 RED · M22 앵커 소멸 · M24 등가 생존 유지) + 검토자 뮤테이션:
- M22는 하3 반영으로 `with_content` 인자 자체가 없어져 적용 대상이 사라졌다(APPLY-FAIL). 같은 축은 X13이 대신 본다.
- 검토자 하네스(`muttools/mut.py`)를 이 사본으로 돌렸다. 적용 단언·sha256 원복 단언은 전건 통과했다.

| # | 뮤테이션(검토자 정의 · X4·X12·X13은 이 사본에 맞춰 위치 조정·추가) | 결과 |
|---|---|---|
| X1 | 정책 요약 최상위 `pace: round(θ,1)` | RED |
| X2 | θ 파생 라벨 `student_band: "상위권"` | RED |
| X3 | `pedagogy_policy.tier = round(θ,1)` | RED |
| X4 | `PackBrief.audience` 신설 + 핸들러가 학년 주입 | RED |
| X4b | `PackBrief.audience` 필드 신설만 | RED |
| X5 | 절단 *전* 요약으로 prompt 경로 계산 | RED (첫 재실행은 **생존** — 아래) |
| X5b | 절단 전 슬롯을 즉시 계산해 반환 | RED |
| X6 | 프로즈 거부 분기 `_settle` 제거 | RED |
| X7 | 문제 요약이 `session.get`으로 엔티티 전체 로드 | RED |
| X8 | 스킬 이름 조회 상한 제거 | RED |
| X9 | 조건 수 상한 제거 | RED |
| X10 | 개념 (code, 이름) 뒤바꿈 | RED |
| X12 | 튜터 라우팅 요청에 `budget_krw=10000` 배선 | RED |
| X13 | 가로챈 턴에도 요약 조회(create) | RED |

X5 첫 재실행의 생존 원인은 실측으로 확인했다. `_compose_summary`가 예산 루프의 `hyp_summaries` 리스트를 **같은 객체로** 요약에 담고 있었다. 그래서 "절단 전 요약"을 붙잡아 둬도 루프의 pop이 그 안의 리스트까지 비웠다 — 뮤테이션의 의미("절단 전 상태로 판정")가 별칭 때문에 표현되지 않은 것이다. 판정이 우연한 별칭에 기대지 않도록 요약이 리스트 복사본을 싣게 고쳤고, 그 뒤 X5·X5b(절단 전 슬롯을 즉시 계산) 모두 RED다.

## 8. 검증 (exit code — 출력은 로그 파일 전체로 판정)

CI 잡 전수 열거(`.github/workflows/ci.yml`)에서 이 변경이 닿는 잡을 골랐다:
- **backend** — 백엔드 소스·테스트 변경
- **infra-contracts** — EOS 인벤토리 귀속. 새 모듈 0이지만 전수 실행
- **declared-unwired-audit**
- **harness-integrity**·**policy-guard** — 문서 신설

닿지 않는 잡과 근거:
- data-pipeline·mobile·web·webapp·concept-reach·docker-build·infra-shell — 경로 변경 0
- backend-migrations — Alembic·스키마 변경 0. 다만 실 PG 통합 테스트도 이 잡에 있다(§9-4)

| 잡 · 검사 | 명령 | exit |
|---|---|---|
| backend · Ruff | `python -m ruff check . ../../tests/backend ../../tests/constitution` | 0 |
| backend · Black | `python -m black --check --line-length 100 . ../../tests/backend ../../tests/constitution` | 0 |
| backend · Mypy | `python -m mypy --strict whymath_backend` (806 files) | 0 |
| backend · Import contracts | `lint-imports` (4 kept · 0 broken) | 0 |
| backend · Pytest 전체(5fbe40fd) | `-m "not corpus_authoring" -n auto --dist loadfile --cov … --cov-fail-under=70` → 21,445 passed · 710 skipped · 1 xfailed · 커버리지 87.60% | 0 |
| backend · Pytest 전체(522fc404 · 검토 반영) | 같은 명령 → 1 failed · 21,475 passed · 713 skipped · 1 xfailed · 커버리지 87.62%. 실패 1건은 `l3/test_isolated_call.py::TestThreadIsNotEnough::test_thread_cannot_stop_the_computation`(CPU 시간 하한 1.5s 단언 — 4코어 병렬 경합). 이 PR은 `l3/`를 건드리지 않았다(`git diff 7f091d73 -- l3` 0). 단독 재실행 3/3 통과. P3-08 보고 §6에 기록된 것과 같은 경합 플레이크다 | 1 → 단독 0 |
| backend · 계층 커버리지 | `check_layer_coverage.py coverage.xml` (522fc404: api 97.0 · l1 90.8 · l2 96.8 · l3 81.6 · l4 95.8) | 0 |
| backend · 관련 파일 + 실 PG 통합 | 관련 4파일 + 통합 파일 → 214 passed · 3 skipped(기본 skip), 로컬 PG16에서 `WHYMATH_RUN_INTEGRATION=1` → 통합 3 passed | 0 |
| backend · 게이트 CLI 20종 | 아래 목록 | 전건 0 |
| backend · 헌법 테스트 | `python -m pytest -q tests/constitution` | 1 (§9-8) |
| declared-unwired-audit | `python -m whymath_backend.ops.declared_unwired_audit` | 0 |
| infra-contracts · Pytest | `python3 -m pytest tests/infra -q` → 3,221 passed · 27 skipped | 0 |
| harness-integrity | `backlog.py validate` · `audit-deps` · `rules lint` · `rules render --check` · `jit check` · `check_amendment.py` | 전건 0 |
| harness-integrity · 위헌 심사 래칫 | `scripts/constitution/audit_ratchet.py` → 단계 2 · 차단 0건 ≤ 기준선 0건 | 0 |
| policy-guard | `cp949_guard.py` · `check_conflict_markers.py` · `check_source_document_binaries.py` · 교과서·EBS·평가원 본문 패턴 grep(변경 파일 대상 0건) | 전건 0 |

게이트 CLI 20종(ci.yml backend 잡 순서, 전건 exit 0):
- defect_detection · selective_grading · explicit_correction_gap · misconception_false_positive
- generator_space_overlap · residue_cross_verify_v2 --dry-run(DRY_RUN_OK)
- **coach_prose_leak**(노출 상한 0.0093 · 오차단 상한 0.0274 · PASS)
- anchor_detection_channel
- **pedagogy_pack_fidelity**(미검출 상한 0.0362 · 오검출 상한 0.0362 · PASS)
- analogy_fidelity · explanation_f7 · notation_coverage · curriculum_notation_gate_cli · provenance_audit
- check_routing_data_grade · check_routing_decision_bypass · check_provider_seat_contract
- prompt_asset_audit --axis l3 · phase3_metrics --self-check · solution_qa

뮤테이션 하네스: §7(25/26 RED, 1 등가).

## 9. 한계·남은 위험

0. **현재 튜터 정책 호출은 전부 LOCAL로 라우팅된다** — 그래서 지금은 내용 요약과 오개념 confidence가 클라우드로 나가지 않는다. `_routing_request`가 `budget_krw`를 넘기지 않아(기본 0) 라우터가 LOCAL을 강제하기 때문이다(검토자 실측·이 사본에서 구독 4 × 난이도 4 전수 재확인). 이 사실을 테스트로 동결했다(`test_tutor_policy_routes_local_so_prompt_never_reaches_cloud` — provider가 받은 실제 결정의 `cost_tier`를 단언한다). 예산이 배선되는 순간(X12) RED가 된다 — 실측상 basic·killer는 CLOUD_MID, premium·gifted·killer는 CLOUD_HIGH가 된다. **클라우드 좌석으로 바뀌면 내용 요약(개념·스킬 이름·문제 구조·팩)과 가설 confidence가 openrouter(US)로 나간다.** 그 RED는 결정 (가)와 아래 1번 confidence 판단을 사람이 다시 보라는 신호이며, 테스트를 지우거나 기대값만 바꾸는 것으로 해소하면 안 된다.
1. **오개념 가설 confidence가 프롬프트에 실린다**(S1-a 이래 기존 동작·이번 변경 없음). 가설 id·라벨은 카탈로그 상수지만, confidence는 이 학생의 답안에서 파생한 학생별 진단 추정치다. 결정 (가)의 열거(θ·숙달도·mastery와 그 파생 라벨)에 없어 범위를 넓히지 않았다. 다만 "학생 개인 학습 데이터"의 취지에는 닿을 수 있다. **Kiki 판단을 요청한다**: 유지 / 라벨만 싣고 confidence 제거 / 클라우드 좌석 한정 제거.
2. **프로즈 계층(S4-04·기본 OFF canary)은 경로표에 들어 있지 않다.** ON이면 학생 답안·단계가 `gate_policy_prose`·`rephrase_coach_utterance`의 금지 조각(출력 가드)으로 쓰이고, 가설 라벨 1건이 rephrase LLM 프롬프트에 실린다. 이 태스크의 `output_guard`는 지시대로 팩 금지모드 가드만 센다. 프로즈 경로까지 경로표에 넣는 것은 후속 대상이다.
3. **게이트 CLI는 내용 요약이 실린 프롬프트로 LLM 품질을 측정하지 않는다.** `coach_prose_leak_eval`·`pedagogy_pack_fidelity_eval`은 hermetic·결정론이고 `tutor_content`를 넘기지 않는다. exit 0은 "기존 안전 게이트를 깨지 않았다"이지 "요약이 도구 선택을 개선했다"가 아니다. 라이브 효과 측정은 하지 않았다.
4. **실 PG 확인 범위.** 조회 헬퍼 3종은 실 PG 통합 테스트로 확인했다(§5). 다만 로컬 확인은 마이그레이션 head가 아니라 **ORM 메타데이터로 만든 6테이블**에서 했다(로컬에 pgvector가 없어 `alembic upgrade head`를 돌릴 수 없다). 마이그레이션된 스키마와의 일치는 CI `backend-migrations` 잡이 판정한다.
5. **토큰 근사(문자/4)는 한글에서 과소 추정일 수 있다**(기존 한계 승계). 요약은 최악 1,600자로 상한이 고정이다.
6. **관측 레코드(`Wh1HarnessShadowObservation`)에는 prompt 경로 목록 필드를 더하지 않았다**(레코드 허용 목록 계약). 응답과 로그 1줄에는 있다. Langfuse 기록은 `P3-73`이다.
7. **shadow·게이트 하네스·데모 스크립트는 `tutor_content`를 넘기지 않는다**(P3-08 범위 밖 호출자 그대로). 학생 대면 서빙 두 핸들러만 요약을 싣는다.
8. **헌법 테스트 `tests/constitution/test_check_signed_changes.py` 33건은 로컬에서 판정하지 못했다.** 실패 원인이 전부 `ssh-keygen` 부재 단언이다(P3-08 보고 §7-8과 같은 환경 한계). 이 파일을 뺀 39건은 exit 0이다. CI가 최종 판정한다.

## 10. PR #1709 독립 검토 처리표

| 등급 | 지적 | 처리 | 근거 |
|---|---|---|---|
| 중1 | ⑥ 동결이 표기 변형에 뚫림(X1~X4 생존) · `PROMPT_FORBIDDEN_SLOTS`는 런타임 미발동 | **반영** | 키 트리 허용 목록(최대 픽스처는 정확 일치) · 수치 잎 θ/숙달 ±0.05·학년 값 감시 · Brief 5종 `model_fields` 정확 집합 동결. 검증자는 '표기 정직성 장치'로 서술을 정정했다(모듈 docstring·§2). X1·X2·X3·X4·X4b RED |
| 중2 | 조회 헬퍼 3종이 테스트에서 미실행(X7~X10 생존) | **반영** | 기록 세션으로 헬퍼를 실제 실행(실행 SQL 캡처·엔티티 로드 금지) + 실 PG 통합 테스트(로컬 3 passed). X7~X10 RED |
| 하1 | X5(절단 전 요약으로 경로 계산)·X6(프로즈 거부 분기 확정 제거) 생존 | **반영** | 가설 전부 절단 픽스처 · 프로즈 거부 픽스처. X5 첫 재실행 생존의 원인(리스트 별칭)은 코드에서 제거했다. X5·X5b·X6 RED |
| 하2 | OpenAPI 설명·모듈 docstring의 낡은 문구 | **반영** | `_TUTOR_CONTEXT_DESC`에 `delivery_paths`·숙달 미전달·학년 미전달 서술, 'not_delivered에 남는다' 정정. docstring에서 없어진 `delivered_context_slots` 참조와 '값은 어디에도 싣지 않는다' 문구 정정 |
| 하3 | 가로챈 턴에도 요약 조회 | **반영** | 조회를 `tutor_invoked` 확정 뒤로 옮겼다(X13 RED). 개념 code의 `_pack_for` 재사용은 하지 않았다 — 쿼리 수 이득 0, 근거는 §6 |
| 추가 | 튜터 라우팅 LOCAL 동결 부재 | **반영** | provider가 받은 실제 결정의 `cost_tier == LOCAL`을 구독 4 × 난이도 4로 단언. 예산 배선 X12 RED. 사실과 함의는 §9-0 |
| 추가 | 검토 처리표·관측 분포 변화 공지 | **반영** | 이 표 · §1 공지 |

검토 반영 검증(522fc404 기준):
- ruff 0 · black(100) 0 · mypy --strict 0 · lint-imports 0
- 관련 테스트 0
- 백엔드 전체: 플레이크 1건(단독 3/3 통과) 외 전건 통과
- 게이트 CLI 20종 + declared_unwired 전건 0 — coach_prose_leak(노출 상한 0.0093·PASS)·pedagogy_pack_fidelity(미검출 상한 0.0362·PASS)
- 뮤테이션 X1~X13 + X4b·X5b 전건 RED
