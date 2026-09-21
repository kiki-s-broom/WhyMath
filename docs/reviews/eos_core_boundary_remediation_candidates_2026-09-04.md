# EOS Core 경계 상환 후보 3건 검토 (2026-09-04 · EOS-84 후속 · Kiki 판정용)

> EOS-84 계측(`docs/architecture/eos_core_adapter_boundary.md` §8)이 남긴 Kiki 판정 후보 3건을
> 코드 실측으로 검토했다. **결정은 하지 않았다** — 각 건에 대해 사실·선택지·권고·판정 질문을 적는다.
> 등재는 Kiki 판정 후 `backlog.py add`로만 한다(태스크 번호 추론 배정 금지).

| # | 후보 | 실측 규모 | 권고 방향 | 난이도 | 결정 질문 |
|---|---|---|---|---|---|
| 1 | `populate` answer_kind 열거(리터럴 비교 위반 1건) | 튜플 17종 = 코퍼스 분포 17종(차집합 0) · 어휘 사본 4곳 · 직접 테스트 1건 | **화이트리스트 삭제 + 미지 값 정책 명시** | 낮음 | 미지 answer_kind를 *거부*할지 *통과*시킬지 |
| 2 | `solution_coaching` MIXED 분해(잔여 누수 2건) | 실행 코드 ~40줄 · 수학 접근 2필드 · 대응 프로토콜 `StepChainVerifier` 선재(구현체 없음) | **선택층 주입(후보 A)** | 중간 | 부분 상환(sympy 잔존)을 수용할지 |
| 3 | `l4.misconception` 카탈로그 코드 상수(어휘 43건) | 실제 64종(문서 34종 stale) · 소비자 28모듈 · 테스트 40파일 · 843 M-id 데이터 정본 별도 실재 | **신설 금지 — 기존 "canonical 수렴" 부채에 편입** | 중간 | 별도 태스크 vs 기존 부채 트랙 스코프 편입 |

---

## 1. `l1.problem_bank.populate._verify_meta_from_raw` — answer_kind 튜플 열거

### 사실
- 위치 `src/backend/whymath_backend/l1/problem_bank/populate.py:360-384`. 원소 **17종**(EOS-84 첫 메모 "16종"은 오기 — 정정 완료). 미지 값은 **거부가 아니라 조용한 `None` 강등**(`else None`). 같은 함수의 형제 필드 `verification_tier`는 반대로 `ProblemCorpusError`로 **적재 거부**한다 — 한 함수 안에 두 정책이 공존한다.
- 이 조용한 강등은 **이미 데이터를 잃게 한 전례가 있다**: `finite_probability`·`finite_count`가 화이트리스트에 없어 None으로 떨어지던 결함(S4-17 부수 발견 · `tests/backend/l1/problem_bank/test_populate.py:515-528` 주석).
- 어휘의 **단일 진실 원천은 없다** — 4곳 사본: `l3/equivalent/acceptance.py:121` `_CONCEPTUAL_VERIFIERS`(17·검산 함수 매핑), `harness/corpus_reverify.py:51`(15 — **이미 드리프트**), `l3/verifier.py:236-278`(파생), populate 튜플(17·이름만). `schema/subject_adapter.py:96-99`는 `answer_kind: str`이고 docstring이 "Core가 이 값으로 분기하면 경계 위반"이라고 못 박는다. `l4/subject_adapter_math.py:134`는 통과만 시킨다(어휘 없음).
- 코퍼스 실분포(`data/corpus/problem_bank_*/problems.jsonl`) distinct 17종 = 튜플 17종. **화이트리스트가 지금 거르는 값은 0건**이다.
- 하류 소비: `ProblemVerifyMeta.answer_kind`는 DB 적재에 미사용(authoring 메타), `harness/problem_corpus_batch.py:298`·`residue_cross_verify_eval.py:122`·`test_corpus_quality.py`가 읽는다.
- 제약: import-linter 계약(`pyproject.toml:252-287`)이 `l1`→`l3.equivalent`·`l3.verifier`·`l4.subject_adapter_math`를 금지(baseline 0). **acceptance 테이블 재사용은 불가**.
- `SubjectAdapter` 필수층은 3메서드(`evaluate_answer`·`detect_misconception`·`validate_problem`)로 `test_subject_adapter_two_tier_contract.py`가 집합을 동결하며 "Physics·History에도 반드시 존재하는가"가 추가 게이트다. `MathSubjectAdapter` default 팩토리는 `composition.py`에 없다(선택층 5종만 배선).

### 선택지
| | 방안 | 변경 | 위험 |
|---|---|---|---|
| (c) **권고** | 화이트리스트 **삭제** — `answer_kind`를 불투명 `str`로 통과. 미지 값 정책은 별도 결정(아래 질문) | populate 1함수 · 테스트 1건 · probe 기준선 `{}`로 ratchet · 문서 §8.2 | EOS-66 계약과 가장 정합. 오타 방어는 L3 검산 단계(`acceptance`)가 어차피 `_SUPPORTED_KINDS` 밖으로 판정한다 |
| (a) | `schema/` 중립 데이터 + `composition` 주입으로 어휘 공급 | 4~5파일 | 필수 아닌 배선 추가 — 어휘 사본이 5번째가 될 위험 |
| (b) | `SubjectAdapter.answer_kinds()` 추가 | 프로토콜·동결 테스트·구현체·합성 팩토리 신설 | **가장 비쌈** — two-tier 계약 위반에 가깝고 필수층 주입 배선이 없다 |

### 판정 질문
미지 answer_kind를 만나면 ①`verification_tier`처럼 **거부**(`ProblemCorpusError`)할지 ②**통과**(str 그대로, 검산 단계가 판정)시킬지. 권고는 ② — Core가 어휘를 모르는 것이 계약이고, 거부는 어휘를 알아야 한다. 단 ②를 택하면 "조용한 None"은 없어지고 값이 그대로 남으므로 S4-17형 손실도 사라진다.

---

## 2. `l4.solution_coaching` — MIXED 분해 (잔여 누수 2건의 유일한 원인)

### 사실
- 281줄 중 docstring ~150줄, **실행 코드 ~40줄**(L214-274). 공개 API 3개(`SlipKind`·`SolutionCoaching`·`recommend_coaching_for_solution`). 모듈 docstring이 스스로를 "L3→L4 오케스트레이터 · 본 모듈만 양쪽 계층을 안다"로 선언 — **의도된 단일 결선 지점**이다.
- ADAPTER 접촉 2건: `verify_solution(...)` **직접 실행**(L222) — 결과 소비는 `has_incorrect`(L228)·`first_incorrect_index`(L242) **2필드**, 나머지는 `solution_verification` 필드로 통과 노출(L264). `observe_wrong_form_shadow(...)`(L273) — 반환 None·기본 off·순수 부작용.
- 시그니처는 이미 과목 중립(`str`·`float|None`·`Sequence[str]`·`HintLevel`). 수학 타입은 반환 모델의 필드 하나(`SolutionVerificationResult`, L115)뿐.
- `api/ocr_handoff.py`는 `solution_coaching`을 import하지 않는다 — `api.coach` 경유 2-hop 파생. **누수 지점은 정확히 하나**.
- **대응 프로토콜이 선재한다**: `schema/verification_capabilities.py:167` `StepChainVerifier.verify_chain(steps) -> ChainVerification`. 그리고 `l3/verify_solution.py:224` `_counts_conformance`가 `SolutionVerificationResult`의 구조적 적합성을 **mypy로 이미 증명**해 두었다 — 변환 객체가 필요 없다. 단 구현체(`MathStepChainVerifier`)와 `composition.default_step_chain_verifier()`는 **없다**(다른 5종 능력은 있음).
- 주입 관례 선재: `api/coach.py:71-74` composition 팩토리 import(EOS-69), `_get_judge_seam_deps`(L738-753) app.state `Depends` 묶음.
- 테스트: 10파일, 전용 `test_solution_coaching.py` 625줄이 **실제 SymPy를 돌린다**(mock 아님). `validator=` 주입 슬롯은 이미 있다.
- **정직한 잔여**: `validate_response`·`arithmetic_validator`(`l3.pregenerate.validator`, **MIXED**, 내부 sympy)는 두 방안 모두 남는다. probe 잔여 집합은 0이 되지만 "수학을 지우면 깨지는가"의 실질은 **부분 상환**이다. 완전 상환은 `l3.pregenerate.validator` 배정 재검토가 선행돼야 한다. `api/coach.py:109-112`도 같은 것을 직접 import한다.

### 선택지
| | 방안 | 변경 파일 | 위험 |
|---|---|---|---|
| A **권고** | `verifier: StepChainVerifier | None = None` 파라미터, 기본값 `composition.default_step_chain_verifier()` 지연 import(기존 5팩토리와 동형). `MathStepChainVerifier` 래퍼 ~15줄. `solution_verification` 필드 타입을 `ChainVerificationCounts`로. `observe_wrong_form_shadow`는 함수 내 지연 import 또는 coach로 이관 | 6~9 (`solution_coaching`·`composition`·`subject_adapter_math`·BOUNDARY_MAP MIXED→CORE·probe baseline→`frozenset()`·two-tier 테스트·pyproject forbidden·coach 선택) | 낮음~중. **pydantic 필드를 Protocol 타입으로** 바꿀 때 `arbitrary_types_allowed`/직렬화·OpenAPI 스키마 변화(Flutter 계약 영향 점검) |
| B | 검증 실행을 `api.coach`로 올리고 결과 객체만 받는 순수 함수로 | 5~6 + 테스트 ~25건 재작성 | **높음 — 권하지 않음**. 누수를 CORE(`api.coach`)로 승격시켜 import-linter 직접 위반이 된다. A를 coach 층에서 다시 해야 완결 |

### 판정 질문
①A로 착수해 잔여 누수 2→0(부분 상환·sympy는 `l3.pregenerate` 경유로 잔존)을 수용할지 ②`l3.pregenerate.validator` 배정 재검토를 선행 depends_on으로 묶어 완전 상환을 한 트랙으로 갈지. 권고는 ① 후 ②를 별건 등재(①은 하루 규모, ②는 MIXED 29모듈 해소의 일부).

---

## 3. `l4.misconception` 카탈로그 — 코드 상수의 데이터 이전

### 사실
- `catalog.py` 788줄, `CATALOG` = frozen Pydantic 인스턴스 **64종**(8영역 튜플 합성 · `test_misconception_catalog.py:27`이 `== 64` 동결). EOS-84 문서·MEMORY의 "34종"은 stale — 정정 완료. `distractor.py` `DISTRACTOR_CATALOG` **10건**(첫 메모 7건도 stale).
- **100% 순수 데이터** — 람다·함수 참조 0건. `regex_signals`·`canonical_wrong_form`은 문자열이고 컴파일·검증은 소비자(`diagnose.py:68` `lru_cache _compile`, `l3.symbolic_equivalence`)가 한다. JSON 직렬화에 원리적 장벽 없음.
- 소비자 **28모듈**: 검출 루프(`diagnose`·`wrong_form_match`) · import-time 검증(`distractor.py:57` validator가 `CATALOG_BY_ID` 조회) · crosswalk 게이트 6모듈 · 씬 DSL 참조 무결성(`scene_generation`·`learning_scene`) · **`api/coach.py:202` `_FANOUT = len(CATALOG)` import-time 상수** · harness 7모듈 프롬프트 삽입.
- **데이터 정본은 이미 있다**: `data/corpus/misconceptions_v1/misconceptions.json` **843건**(M-id, `misconception_catalog` 테이블·`l1/misconception/catalog_loader.py` 적재) + `misconception_crosslinks_v1/crosslinks.json` **64건**(kebab↔M-id 1:1, "검수:Kiki 2026-07-12"). 두 체계는 FK 없는 N:M(`schema/misconception_crosslink.py:4-5`). 64종은 *탐지* 정본(signals/regex/wrong-form), 843은 *콘텐츠* 정본(distractor_rule/교정포인트).
- **이미 등재된 상위 부채**: "오개념 3중 표현 부채(kebab 코드 / M-id 843 / JSONB) canonical 수렴 최우선" — `subject_expansion_readiness.md:88,121`, `math_dsl_evolution.md:53,290`, `current_phase_checklist.md:43`. 물리 오개념 시드는 **"canonical 수렴 선행"으로 명시 차단**돼 있다(`phys-` 접두 확정).
- **진짜 하드 블로커 1개**: `models.py:17` `MisconceptionDomain = Literal[8 수학 영역]` — 타입 레벨 폐쇄. 물리 영역 추가 = Core 타입 수정. 데이터 쪽 `misconception_catalog.domain`은 `String(64)` 개방형 — **데이터는 이미 중립, 코드만 닫혀 있다**.
- 로딩은 전부 import-time. 데이터 파일로 바꾸면 lazy+캐시 필수 — 같은 디렉터리 `probes.py`가 `probes_v1.jsonl`을 `importlib.resources`로 읽는 선례. `CATALOG` 심볼을 PEP 562 `__getattr__`로 보존하면 **소비자 28·테스트 40 무수정**.
- doc-first 불변식: `docs/prompts/misconception_diagnosis.md`가 정본이고 `catalog.py`는 그 인코딩 — 데이터 파일을 더하면 **3중 부채가 4중**이 된다. 이 계약 재정의가 선결.
- CLAUDE.md "오개념은 독립 DB · Reactive Retrieval"과의 관계: reactive 축은 이미 준수(학생 발화 후 스캔). "독립 DB" 축은 64종 kebab만 미이행 — 이전은 원칙에 **역행이 아니라 정렬**.

### 선택지
| | 방안 | 변경 | 위험 |
|---|---|---|---|
| A **권고(단, 신설 아님)** | 패키지 내 `detectors.json` + `importlib.resources` 로더 + `lru_cache` + PEP 562 심볼 보존. `models.py` Literal→개방 str + 과목 팩 어휘 검증. `distractor.py` 10건 동봉 | src 3~4 + 데이터 2 + 테스트 2~3 | import-time validator 순환 · 타입 검증이 CI→부팅 시점으로 이동(스키마 동결 테스트로 보상) · 정규식 백슬래시 JSON escape · doc-first 계약 충돌 |
| B | `misconception_detector` DB 테이블(843과 대칭) | src 8~12 + 테스트 6~10 + DB fixture | **높음** — `audit.py:23` "DB 0·순수·결정론" 계약 위반, hermetic 테스트 다수 DB 의존화, 843 수렴 부채와 스코프 폭발 |

### 판정 질문
별도 태스크를 **신설하지 않고** 기존 "canonical 수렴" 부채 트랙에 ①`catalog.py` 64종 데이터화 ②`distractor.py` 10건 ③`MisconceptionDomain` Literal 개방 3건을 명시 스코프로 편입하는 데 동의하는지. 그리고 doc-first 정본(`misconception_diagnosis.md`)을 유지할지 데이터 파일을 정본으로 바꿀지.

---

## 정직한 공백
- 세 조사는 정적 코드 읽기다 — 런타임(DI·플래그) 경로는 EOS-84 프로브와 같은 사각을 공유한다.
- 후보 2의 pydantic Protocol 타입 직렬화 영향은 **실측하지 않았다**(착수 시 첫 검증 항목).
- 후보 3의 소비자 28·테스트 40 "무수정" 주장은 심볼 보존을 전제한 추정이며, `_FANOUT` import-time 상수 같은 굳힘 지점이 더 있을 수 있다.
- 부수 stale 표기(수정 안 함·보고만): `catalog.py:772` docstring "34종", `models.py`·`audit.py`·`api/coach.py:199`·`misconception_embedding.py` 주석 "30종", `docs/architecture/eos_core_adapter_boundary.md` §8.3 외 다른 절의 오개념 건수.
