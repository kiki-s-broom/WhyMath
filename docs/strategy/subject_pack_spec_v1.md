# 과목 팩 명세서 v1 — 새 과목을 "채우는" 실측 스키마

> **작성일**: 2026-07-06 | **상위**: `subject_expansion_e_axis_v1.md`(E축 실행 로드맵) · `business_plan_master_v1.md` 제4부 | **설계 정본**: `subject_expansion_readiness.md`
>
> E축 문서가 "어떤 과목을 어떤 순서로"를 정한다면, 이 문서는 **"과목 팩이 실제 어떤 파일·필드로 이뤄지는가"** — 저장소의 **실존 코퍼스·스키마·로더 포맷** — 를 실측 기록한다. 새 과목(물리 등) 추가는 새 엔진을 짓는 게 아니라 **아래 6개 팩의 빈칸을 채우는 작업**임을 코드 레벨에서 증명한다.
>
> **⚠️ 이 문서는 설계 기록이지 착수 지시가 아니다.** 플레이북 "소비처 없는 추상 미도입" 원칙에 따라, 여기 적힌 팩 중 **새 코드/스키마가 필요한 항목은 전부 `subject_expansion_readiness.md` §8 보류 대장의 트리거 도달 시점까지 구현 금지**다. 본 명세는 "그때 무엇을 채우는가"의 지도일 뿐, 지금 만들 목록이 아니다.
> **불변 전제**: 수학 완성(M6=S5 게이트) 통과 전 어떤 과목 팩도 착수하지 않는다.

---

## 0. 과목 팩 = 6개 데이터 팩 (엔진 0줄 수정 — 성립 범위는 §0-1로 한정)

| # | 팩 | 실존 위치 (수학 기준) | 새 과목이 채우는 것 | 새 코드 필요? |
|---|---|---|---|---|
| 1 | 성취기준 | `data/corpus/standards_<subj>_v1/` | NCIC 해당 교과 크롤 → Collection JSON | ❌ (정규식·로더 재사용) |
| 2 | 원자/개념 | `data/corpus/atom_graph_<subj>_v1/` + AREA 니모닉 | 원자 노드·prerequisite 엣지 | ⚠️ idmap AREA 추가만 |
| 3 | 오개념 | `data/corpus/misconceptions_<subj>_v1/` + L4 kebab | 과목 접두 오개념 | ❌ (스키마 재사용) |
| 4 | 프롬프트 | `docs/prompts/*.md` → 코드 상수 | (교수학 무관 — 대부분 재사용) | ❌ |
| 5 | 검증축 | `l3/symbolic_equivalence.py` 등 | 과목 검증 primitive | ✅ (형제 primitive) |
| 6 | 문제 | `data/corpus/problem_bank_<subj>/` + `Problem.subject_area` | 동등문제 JSONL | ⚠️ subject_area 축 신설 |

> **핵심**: 6개 팩 중 엔진 수정이 필요한 것은 5번(형제 검증 primitive 추가)과 축 신설 2건(idmap AREA·`Problem.subject_area`)뿐. 나머지는 **데이터만 채운다**.

### 0-1. "엔진 0줄 수정"이 성립하는 범위 — 2026-10-23 정정 (`ARCH-104` · 감리 W-08·W-10·W-11·W-12 · 판정 기준 main `0523e19e`)

위 표와 핵심 문장은 2026-07-06 작성 그대로다. 그 뒤 EOS 감리(2026-10-19)가 현재 코드와 대조해 **"엔진 0줄"을
그대로 읽으면 틀린 구간**을 찾았다. 주장을 지우지 않고 **성립하는 범위로 한정**한다.

**성립하는 것 (등록·데이터 적재 층)**: 성취기준·원자/개념·오개념·프롬프트 팩은 파일·스키마·로더 재사용으로
채울 수 있다. 필수층 `SubjectAdapter` 3메서드는 교차 과목 프로브(`EOS-92`)에서 물리 문항으로 필드 15개를
채워 ✗ 0이었다(Frozen · unexercised — Core 호출자 0). 개념 ID 접두는 `ADR-009`로 코드 상수 집합
(`SUBJECT_PREFIXES`)에서 조립되므로 새 접두는 개념 그래프 안에서는 **집합에 토큰 1개를 더하는 것**으로 끝난다(이 정규식 수정은 불필요하나, 같은 모양의 리터럴이 `schemas/v1.1/concept.schema.yaml`·`ai_quality_judges.py`의 `_CONCEPT_CODE_RE`에 더 있다 — ADR-009).

**성립하지 않는 것 (학생이 풀고 채점받는 동작 층)** — 새 과목의 동작 경로를 열려면 아래 CORE/MIXED 지점을 *고쳐야 한다*:

| 지점 | 현재 코드 | 왜 "0줄"이 아닌가 |
|---|---|---|
| 선택층 능력 계약 (감리 W-08) | `schema/verification_capabilities.py` 능력 Protocol 8종 중 `ExpressionEquivalence`·`ExpressionSeal`·`AnswerFormVerifier`·`AssessmentAnswerVerifier`·`AnswerValueExposure` 5종이 수식·값 계산을 전제한다(파일 스스로 "역사·국어엔 없다"). 필수층만 구현하면 등록은 되나 채점 경로가 열리지 않는다 | 미제공 능력의 폴백이 지점마다 다르다. 최소집합·폴백 단일화는 `ADR-008`(Proposed · 12월은 문서만) |
| 문항 적재 (W-10) | `db/models/problem.py` `Problem.subject`는 NOT NULL PG enum(`Subject` 5값 = 수능 선택과목 축). 위 §6이 선언한 `Problem.subject_area` 컬럼은 **아직 없다**(선언 ≠ 착지) | 타 과목 문항은 INSERT 자체가 불가 — 컬럼·Alembic·`schema/problem.py` 변경이 필요 |
| CORE 안의 수학 데이터 상수 (W-11) | `l4/misconception/catalog.py`(오개념 72종 코드 상수) · `l3/pedagogy/slot_generator.py`(이차함수 프롬프트 예시) · `l6/suneung/scope.py`(성취기준 코드 파싱) · `schema/enums.py`(`SourceType`·`ExamType`) | CORE로 배정됐지만 수학 데이터를 품고 있다 — 데이터 이전이 필요(2027 이월 후보, 12/31 내부 검증 기간 방침 3항) |
| 능력 계약 우회 (W-12) | `api/verify.py`가 `/v1/verify`에서 `l3.verify_answer`·`verify_solution`·`verify_step`을 직접 호출한다. import-linter `ignore_imports`에 MIXED·INFRA 출발 8간선(+ 합성 루트 경유 2간선)이 면제로 적혀 있다 | 능력 계약을 거치지 않는 경로는 과목을 갈아 끼울 수 없다 |
| 합성 루트·등록 | `composition.py` 팩토리 9개와 `app.py` 능력 7종 등록은 수학 단일 과목 고정 — 과목 셀렉터는 두 번째 과목이 실재할 때 도입한다고 파일 스스로 적었다 | 두 번째 과목을 붙이면 이 파일은 고쳐야 한다(INFRA의 정의) |

따라서 이 문서의 "엔진 0줄 수정"은 **"등록·데이터 적재 층에서"** 로 읽는다. 동작 층은 위 5지점이
2027-01 이후 이월 게이트(감리 R-11)의 몫이며, 12/31까지는 건드리지 않는다. 능력 수 정의(8종·등록 7종·팩토리 9개)는
`docs/architecture/eos_core_adapter_boundary.md` 상단 「능력 수는 이렇게 센다」가 정본이다.

---

## 1. 성취기준 팩 (Standards) — 새 코드 0

**실존 포맷** (`data/corpus/standards_v1/standards.json` — 단일 Collection 객체):

```json
{
  "source_citation": "출처: …(build_ncic_citation_core)",
  "curriculum_revision": "2022 개정",
  "standards": [{
    "norm_id": "2022_2수_01_01",        // PK, 교육과정 간 유일
    "code": "[2수01-01]",                // 고시 원문코드
    "grade_band": "초등학교 1~2학년군", "school_type": "초등학교",
    "subject": "2수", "domain": "수와 연산", "sub_domain": "100까지의 수",
    "statement": "…", "curriculum_revision": "2022 개정",
    "parent_codes": [], "source_url": "https://www.ncic.go.kr"
  }],
  "links": [{"concept_src_id": "N1", "norm_id": "2022_2수_01_01", "link_type": "직접"}]
}
```

**새 과목이 채우는 것 / 재사용하는 것**:
- `STANDARD_CODE_PATTERN`(`ncic/models.py` L84) — **과학과 코드 이미 수용**(`[12물리01-01]`·`[10통과1-01-01]` 매치 실측). 정규식 무변경, 회귀 테스트로만 동결(E축 6단계 ①).
- `NORM_ID_PATTERN` `^(2022|2015)_[가-힣A-Za-z0-9]{1,8}_\d{2}_\d{2}$` — `2022_12물리_01_01` 그대로 수용.
- **유일 신규 작업**: `SOURCE_CITATION`의 과목 종속부 — `data_pipeline/citation.py`의 `build_ncic_citation_core()`에 과목 라벨(별책 9 과학 등) 파라미터 추가(`readiness.md` §9 invariant). 이건 새 추상이 아니라 기존 단일 원천에 인자 추가.
- 로더(`standard_loader.py`) rename seam(`code`→`official_code`, `concept_src_id`→`concept_code`)·멱등 upsert 그대로.

---

## 2. 원자/개념 팩 (Atoms) — idmap AREA 추가만

**실존 포맷** (`data/corpus/atom_graph_v1/graph.json` — `concepts[]`·`edges[]`):

```json
// 노드
{ "code": "2수01-01-2", "name": "기수 원리", "level": "세부개념",
  "parent_code": "초수연-U1-S1", "school_level": "초등",
  "subject_area": "수와 연산", "cognitive_type": "개념", "node_type": "구성",
  "intrinsic_difficulty": 1, "standard_codes": ["[2수01-01]"],
  "core_proposition": null,          // 대학 원자만 채움 (K-12 본문 redact)
  "redacted_fields": ["핵심명제/성취기준내용"] }
// 엣지
{ "from_code": "2수01-01-1", "to_code": "2수01-01-2",
  "relation": "prerequisite", "relation_subtype": "원본",
  "strength": 0.8, "evidence": "원자 백본 v1" }
```

**새 과목이 채우는 것**:
- 원자 노드: `school_level`에 과목 학교급, `subject_area`에 과목 영역(역학 등). `AtomConcept`(`atom_graph/models.py`)는 **본문 슬롯 부재**(핵심명제 재유입 구조 차단) — 물리 원자도 동일하게 본문 없이 구조만.
- 엣지: `AtomRelation`은 `prerequisite` 단일. **cross-subject 연결(물리 순간속도 ← 수학 미분계수)도 같은 prerequisite** — 관계 타입 신설 없음(`readiness.md` §7).
- **AREA 니모닉 (⚠️ 새 코드)**: `concept_graph/idmap.py`의 `_TOPIC_AREA_MAP`(41종 dict)에 물리 어간 추가. 예약 완료: `MECH`·`ELEC`·`WAVE`·`THERMO`·`MODPHY`(`readiness.md` §4.1). `_AREA_SLUG_MAP`에 슬러그 1:1 추가. **침묵 폴백 금지 — 미수록 어간은 KeyError로 누수 즉시 발견**(전수 커버리지 단언). 실등록 트리거 = 물리 원천 코퍼스 category 확정(§8 보류 대장).
- 개념 그래프 스키마(`concept.schema.yaml`): `concept_id` = `math.<area>.<slug>` 형식. 물리는 subject를 ID에 넣지 않고(노드에서 제거한 축) `_AREA_SLUG_MAP`이 area→과목을 유도. 엣지 `evidence_source`는 `physics_education_literature` 패턴으로 **값 추가**(rename 금지).

---

## 3. 오개념 팩 (Misconceptions) — 스키마 재사용

**두 체계 공존** (FK 없음 — canonical 수렴은 별도 선행 부채):
- **M-id 콘텐츠 카탈로그** (`data/corpus/misconceptions_v1/misconceptions.json`): `mis_id`(PK)·`canonical_statement`·`error_type`(8종)·`difficulty`·`concept_src_id`·`standard_code` 등 16필드. `MisconceptionRecord` TypedDict, 첫 등장 우선 dedup.
- **kebab-id 탐지 엔진** (`l4/misconception/catalog.py`): 32종 하드코딩. `Misconception` 모델 — `id`(`"distribution-over-power"`)·`canonical_wrong_form`·`correct_form`·`signals`·`regex_signals`. 정본 `docs/prompts/misconception_diagnosis.md`.

**새 과목이 채우는 것**:
- 과목 접두 kebab-id 필수: `phys-`·`chem-`·`bio-`·`hist-`·`kor-`·`eng-`(수학 32종은 무접두 그대로·재명명 금지). 연구 문헌은 **분류 체계만** 참조(FCI 등 원문항 저작권 미사용).
- M-id 코퍼스의 `error_type` 8종(공식혼동/부호오류/차원혼동 등)은 과목 공통 — 물리 오개념도 이 축 재사용, 필요 시 로드맵 제안 5분류(절차/개념/표상/오독/사실혼동)로 canonical 수렴 시 통합(§4 보류).
- **reactive retrieval 유지** — 오개념을 초기 context에 preload 금지(과목 무관 불변식).

---

## 4. 프롬프트 팩 (Prompts) — 대부분 재사용

**실존 구조**: `docs/prompts/*.md`(6개) 정본 → 코드 상수로 복제(런타임에 md read 안 함, 라인 참조 주석으로 동기화).
- Polya: `l4/polya/prompts.py` — `_STAGE_1~4_PROMPT` 상수 + 전이 휴리스틱 `transitions.py`.
- Socratic: `l4/socratic/categories.py` — 6종(clarification/assumption/evidence/perspective/implication/meta).

**새 과목이 채우는 것**:
- **교수학은 과목 무관** — Polya 4단계·소크라테스 6범주·답 미루기(LTHC)는 물리·화학에 그대로 작동. 재사용률 최대 팩.
- 예외 = 교수학 변형이 필요한 언어/역사 과목: 역사는 Polya의 역사 탐구 대응(사료→가설→검증→성찰)을 `docs/prompts/`에 과목 변형으로 **추가**(기존 수학 상수 무변경). E4~E6 소관.

---

## 5. 검증축 팩 (Verification) — 형제 primitive 추가 (✅ 유일한 실질 신규)

**실존 구조** (`l3/`, 3-tier):
- **동치 권위 단일 진실** (`symbolic_equivalence.py`): `identity_status(lhs, rhs) → IdentityVerdict{identity/not_identity/undecidable/parse_error}`. 정직성 규약 — 판정 불가는 보수(undecidable).
- Tier1 답 검산 `verify_answer(...)`·Tier2 단계 `verify_step(...)`·동등문제 게이트 `evaluate_equivalent_candidate(...)`(4종: 저작권·정확성·위생·동등성).

**새 과목이 채우는 것**:
- **SymPy 커널은 교체하지 않는다** — 물리·화학 수식 동치도 `identity_status` 그대로.
- 과목 검증 축은 **형제 primitive 추가**(같은 L3·같은 정직성 규약):
  - 물리: `dimensional_consistency(expr, expected_dim) → {consistent/inconsistent/undecidable/parse_error}` · `sympy.physics.units` 기반. 트리거 = 물리 문항 검증 소비처 첫 등장(§8).
  - 생물: 수식 동치 부재 → **성취기준 근거 인용 사실 검증**(자체 코퍼스 RAG, 환각 시 undecidable 보수). 신규 검증 계열.
  - 영어: 루브릭 LLM 평가(평가 근거 강제 인용) — 가장 먼 검증축, E6 소관.
- 게이트 인터페이스(`evaluate_equivalent_candidate`)는 과목 중립 — SymPy는 "수학 커널 plugin"이지 파이프라인 본체 아님(§4.1 불변식).

---

## 6. 문제 팩 (Problems) — subject_area 축 신설

**실존 포맷** (`data/corpus/problem_bank_v1/problems.jsonl` — JSONL, 저작 메타 포함):

```json
{ "slug": "wm-quad-eq-larger-root", "source_type": "자체생성",
  "license": "WHYMATH_GENERATED", "subject": "공통",
  "question_text": "이차방정식 …의 큰 근을 구하시오.", "answer": "3",
  "achievement_standard_codes": ["[10공수1-02-02]"],
  "concepts": [{"concept_src_id":"HK06","role":"PRIMARY","relevance":0.95}],
  "verify": {"conditions":"x**2 - 5*x + 6 = 0","answer_map":{"x":"3"},"answer_selection":"largest"} }
```
`concepts`/`verify`/`license`는 Problem 스키마 밖 저작 메타 — `populate.py`가 본문과 분리. `verify`는 §5 게이트 재료.

**새 과목이 채우는 것 (⚠️ 축 신설 2건)**:
- **`Subject` enum(공통/미적분/확통/기하/인공지능수학)에 물리 값 ADD VALUE 금지** — 이건 "수학 교과 내 수능 선택과목" 축이다. 타 과목은 **`Problem.subject_area` 컬럼 신설**(server_default '수학', 트리거 = 물리 문항 첫 적재, §8). 축 혼동 방지.
- **`VisualizationStyle`(16종 한글)**: 물리 양식(벡터도는 이미 존재·파동그래프·자유물체도)은 PG enum **ADD VALUE**로 확장(자체 docstring 설계). 제거는 어려우나 추가는 쉬움.
- 동등문제 생성: 수능 시그니처 방법론(S2 파이프라인·PRM·검수 큐) 재사용, 패턴 데이터만 과목 팩. 코퍼스는 저작 시점에 §5 게이트 통과 계약으로 적재(`test_corpus_quality.py` 봉인).

---

## 7. 과목 팩 착수 체크리스트 (팩별 트리거 — §8 보류 대장 매핑)

새 과목 착수 시 이 순서로 6단계 플레이북(E축 문서 §1)을 실행하되, **각 팩의 새 코드는 트리거 도달 전 금지**:

| 팩 | 새 코드 트리거 | 착수 전 확인 |
|---|---|---|
| ① 성취기준 | (없음) 크롤 즉시 가능 | citation 과목 라벨 인자만 |
| ② 원자 idmap AREA | 물리 원천 코퍼스 category 확정 | `_TOPIC_AREA_MAP` 예약 니모닉 소비·KeyError 게이트 |
| ③ 오개념 | canonical 수렴 완료 + 콘텐츠 착수 | `phys-` 접두·reactive 유지 |
| ④ 프롬프트 | (없음) 교수학 재사용 | 언어/역사만 변형 추가 |
| ⑤ 검증축 primitive | 과목 문항 검증 소비처 첫 등장 | 형제 primitive·정직성 규약 |
| ⑥ subject_area 컬럼 | 과목 문항 첫 적재 | `Subject` enum 오염 금지·server_default |

**공통 선행 게이트** (콘텐츠 1건 전): 저작권 매트릭스 `licensing_safety.md` 등록 · 도메인 검수자 1인 · 임베딩 namespace subject 축 스키마 변경 0 수용(거버넌스 테스트).

---

## 8. 참조

| 항목 | 위치 |
|---|---|
| E축 실행 로드맵 | `docs/strategy/subject_expansion_e_axis_v1.md` |
| 확장 준비 정본(보류 대장 §8) | `docs/architecture/subject_expansion_readiness.md` |
| 상위 사업계획 | `docs/strategy/business_plan_master_v1.md` 제4부 |
| 성취기준 모델 | `src/data-pipeline/data_pipeline/ncic/models.py` · `citation.py` · `l1/standards/standard_loader.py` |
| 원자·AREA | `data_pipeline/atom_graph/models.py` · `concept_graph/idmap.py` · `schemas/v1.1/{concept,edge}.schema.yaml` |
| 오개념 | `data_pipeline/misconception/extract.py` · `l4/misconception/catalog.py` · `docs/prompts/misconception_diagnosis.md` |
| 검증축 | `l3/symbolic_equivalence.py` · `verify_answer.py` · `verify_step.py` · `equivalent/acceptance.py` |
| 문제·enum | 구현 정본 `src/backend/whymath_backend/schema/problem.py` · `schema/enums.py` · `l1/problem_bank/populate.py` (구본 명세 `schemas/v1.1/problem.schema.yaml`은 미구현·비정본 — 판정: `docs/architecture/problem_bank_gap_review.md` §3 D1) |

---

**버전**: 1.0 | **작성**: 2026-07-06 | **다음 갱신**: E1 물리 착수·첫 팩 실제 적재 시 (실측 포맷 diff 반영)
