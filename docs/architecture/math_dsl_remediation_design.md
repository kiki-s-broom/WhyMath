# Math DSL 부채 교정 — 설계(고위험 항목)

> **상태**: 설계(design) · **계층**: 횡단(L1·L3·L4) · **작성일**: 2026-06-30
> **정본 상위**: `math_dsl_risk_register.md`(부채 분석). 본 문서는 그 부채 중 *고위험·선행조건
> 미정* 항목의 **설계만** 담는다(구현은 별 슬라이스·별 `/plan`).
> **동반 구현(이미 반영)**: cycle 방어선(populate/load)·교육과정 grade/semester 노드 제거는
> 같은 변경분에서 *구현 완료*. 본 문서는 *남은* 고위험 항목의 청사진이다.

> ✅ **2026-08-10 개정 배너(DSL 통합 점검 — `dsl_integration_gap_review.md` §5)**: 실측 대조로
> 두 서술이 코드에 추월·역전됐다. ① §1.3-2 "*(잔여)* 매핑 채택·적재" → **완료됨** —
> `data/corpus/misconception_crosslinks_v1/crosslinks.json`에 64건 채택·적재(검수:Kiki
> 2026-07-12). ② §1.3-3 "`learning_scene.py`·`wh1_loop.py` shadow 배선 **불필요로 종결**" →
> **코드는 반대다** — 두 곳 모두 배선 실재(`l4/learning_scene.py:369`·`harness/wh1_loop.py:498`
> `observe_crosslink_shadow`). 종결 근거였던 in-memory 제약이 이후 구현에서 해소된 것으로,
> 현행 정본은 "배선됨"이다. §1.3-3의 *(잔여)* canary/full 플립만 미착수 상태로 유효.

## 0. 이번에 구현된 것(맥락) vs 설계로 남긴 것

| 부채 | 처리 | 근거 |
|---|---|---|
| cycle 검출(populate/load 방어선) | **구현 완료** | 저위험·기존 탐지기 미러 |
| 교육과정 `grade_introduced`·`semester_introduced` 제거 | **구현 완료** | NULL·중복·소비처 0 |
| 교육과정 `curriculum_version`·`subject` 완전 Overlay 이관 | **구현 완료**(§3) — 두 필드 제거(PR #350) + `curriculum_entry` KR 적재기 완료 | 런타임 소비처 0 확인·Overlay 단일 진실 |
| 오개념 ID 통합(2026-06-30 작성 당시 kebab 30 ↔ M-id 839) | **골격 구현**(§1) — M-id 로더·crosswalk 테이블·read-time resolver 완료. 잔여 = 매핑 큐레이션·게이트 배선 | rekey는 resolver로 불필요화(채택) |
| 파서(동치 권위) 일원화 | **구현 완료**(§2) — 경계 명문화 + golden test | `notation_contract.md`·`data/notation_contract.json` |
| invariant 회귀 동결 게이트(노드 의미·약한 relation·shadow·traversal 예산) | **구현 완료**(PR #357) — risk_register §4 매핑 5종(Q10-③·Q1/Q8·Q2·Q10-⑥·Q10-⑧) | `test_concept.py`·`test_concept_misconception_runtime.py`·`test_edge_relation_governance.py`·`hypothesis_store.py`·`prerequisite_recommendation.py` |

> **정정(2026-06-30)**: 초안(v0.1)은 M-id 로더를 "없음(스키마만)"이라 했으나 *오보*다 —
> `l1/misconception/catalog_loader.py`(+`populate` CLI·`atom_catalog`·단위/통합 테스트·alembic
> `c4d5e6f7a8b9`)로 **이미 구현·적재 가능**하다. 따라서 오개념 ID 통합의 "1단계 로더"는 완료 상태이며
> 잔여는 §1.3의 ②crosswalk·④학생데이터 rekey다. 파서 항목(§2)은 본 슬라이스로 *경계 명문화 +
> golden test*까지 구현 완료(`notation_contract.md`).

---

## 1. 오개념 ID 통합 (최고위험)

### 1.1 현재(부채) — 2026-06-30 작성 당시
- **kebab 30종**(`l4/misconception/catalog.py` 하드코딩) = *런타임 탐지·개입 정본*. 44+ 파일이
  `CATALOG_BY_ID`에 강결합(진단·judge·distractor·probe·learning_scene·wh1_loop 게이트).
- **M-id 839종**(2026-06-30 당시)(`schema/misconception_catalog.py`·`data/corpus/misconceptions_v1/`) = *콘텐츠
  카탈로그*. **로더 구현 완료**(`l1/misconception/catalog_loader.py`·`populate` CLI·alembic
  `c4d5e6f7a8b9`·단위/통합 테스트) — `misconception_catalog` 테이블에 멱등 적재 가능. (API 노출은 후속.)
- 둘 사이 **crosswalk 부재·FK 없음**. 런타임 테이블(`misconception_hypothesis`·`evidence_link`·
  `misconception_embedding`)은 kebab `misconception_id`를 **TEXT 느슨참조**로 보유.
- 개념노드 `common_misconceptions`(JSONB 자유서술)는 또 다른 표현(런타임 경로 미사용·`05a` RS2).

### 1.2 목표 불변식 (math_dsl_risk_register.md Q10-⑥)
오개념 = **단일 canonical 정체성**·독립 그래프·reactive 로드. 표현 1개당 진실 id 1개.

### 1.3 단계 슬라이스 (제안)
1. ✅ **M-id 로더 + ORM 적재**(완료·저위험·런타임 무영향) — `misconceptions_v1` 839 →
   `misconception_catalog` 테이블(`l1/misconception/catalog_loader.py`). kebab 경로 불변.
2. 🟡 **crosswalk 골격**(완료) — kebab ↔ M-id 매핑 테이블 `misconception_crosslink`
   (`db/models/misconception_crosslink.py`·`concept_standard_link` 패턴·`link_id` UUID PK·`mis_id`
   실 FK·의미 유일키 `(kebab_id, mis_id, link_type)`)·로더(`l1/misconception/crosslink_loader.py`)·
   **read-time resolver**(`crosslink_resolve.py`·kebab→M-id 조회)·alembic `e2f3a4b5c6d7`. **실제 매핑
   데이터·게이트 배선은 잔여**(아래). `confidence`·`method`로 근거를 남기되 채택은 사람 검수.
   *(완료)* **검수 초안** `docs/data/misconception_crosslink_candidates.md`(30종 후보·근거·신뢰도).
   *(완료)* **후보 자동생성 도구** `l4/misconception/crosslink_candidates.py`
   (`propose_crosslink_candidates`·kebab×M-id 임베딩 코사인·검수 artifact 출력·자동 적재 차단.
   감사 I4로 L1→L4 역의존 제거 위해 L1에서 L4로 이동 — 두 오개념 카탈로그 비교는 L4 성격).
   신호 정정: kebab엔 standard_code·error_type 부재 → 주신호 = 임베딩 코사인(domain은 메모만).
   *(잔여)* **매핑 채택·적재** — 검수자가 승인분만 `"crosslinks"` JSON으로 옮겨 `crosslink_loader`
   적재(자동 커밋 금지·오도 코칭 차단).
3. 🟡 **canonical id 선정 + 게이트 공존**(진행) — 신규 노출은 M-id canonical·kebab은 런타임 탐지
   키로 잔존(crosswalk로 항상 매핑). 게이트(`learning_scene.py`·`wh1_loop.py`·`evidence_store.py`)는
   **두 체계 공존 분기**로 확장 — *노출 전 측정*(`04b` shadow→canary).
   *(완료·shadow 1차)* **증거 저장소 게이트 shadow 배선** — `evidence_store.log_evidence`가
   `misconception_crosslink_mode=="shadow"`일 때 kebab→M-id 매핑 coverage를 *비차단·비노출*로
   해석·로깅(`l4/misconception/crosslink_shadow.py`·shadow.py 미러·resolve 실패도 적재 불변).
   노출·DB 저장은 kebab-id 그대로. 기본 `off`(빈 테이블 per-write DB 왕복 회피·측정 윈도만 on).
   *(완료·측정 도구)* **coverage harvest** — `crosslink_shadow_harvest`가 관측 JSONL을 읽어
   kebab→M-id 매핑 coverage(관측/distinct 커버리지·1:N 모호·미매핑 kebab-id 목록)를 집계한다
   (`step_shadow_harvest` 동형·오프라인·순수·비노출). canary 플립 go/no-go와 크로스워크 큐레이션
   우선순위(미매핑·1:N)의 정량 근거 — "노출 전 측정"을 산출하는 도구.
   *(완료·M2)* **canonical 선택 정책 + canonical 기준 shadow 측정** — canonical M-id는
   *confidence NOT NULL 직접매핑의 strict 최대가 단독*일 때만 선정(`select_canonical`·
   `crosslink_resolve.py`). 동률(tie)·직접 부재·링크 부재는 사유와 함께 미선정(자동 임의 선택 =
   오귀속 위험이라 정직 미선정 — 우선순위 #1·#3). confidence 임계(0.6) 강제는 매핑 승격(promote)
   슬라이스 몫(정책 중복 금지). shadow 관측이 canonical 결과(`canonical_mis_id`·
   `canonical_ambiguous`·`direct_count`)를 additive 기본값 필드로 충전하고(구 JSONL 하위호환·
   실패 시 기본값·never-break), harvest가 `distinct_canonical_ratio`를 canary go/no-go 핵심
   변수로 집계한다(1:N 원시 링크 수만 세면 ambiguous 집계가 무의미 —
   `shadow_measurement_runbook.md` crosswalk 절). 런타임 노출 소비(리포트·canary 플립 배선)는
   premature라 미배선.
   *(종결·불필요 — 재개 트리거 명기)* "나머지 두 게이트(`learning_scene.py`·`wh1_loop.py`) shadow
   배선" 항목은 **불필요로 종결**한다. 근거: ① `wh1_loop`의 `LogEvidenceAction`은 *in-memory
   하네스*다 — 증거를 `state.evidence`(프로세스 내 리스트)에만 적재하고 DB에 접근하지 않는다
   (`harness/wh1_loop.py:424-445`). ② `learning_scene`은 *생성물 검증 게이트*다 —
   `parse_learning_scene`이 `misconception_id ∈ CATALOG_BY_ID` 무결성을 검사할 뿐 kebab-id를
   영속하지 않는다(영속 좌석 아님). 학생 데이터에 kebab-id가 *영속되는* 좌석은
   `evidence_store`·`hypothesis_store` 2곳뿐이고 둘 다 shadow 배선 완료 — 측정 목적(영속 kebab의
   canonical coverage 관측)에 두 게이트 배선은 기여가 없다. **재개 트리거**: 두 경로 중 하나라도
   영속을 얻으면(예: wh1_loop 증거의 DB 적재 배선, learning_scene 저장) 그 시점에 shadow 배선을
   재개한다.
   *(잔여)* shadow 측정 후 canary/full 노출(M-id canonical 플립) — 매핑 채택(2-잔여) 선행 필요.
4. **학생 데이터 마이그레이션** *(불필요화·결정)* — 런타임 테이블은 kebab `misconception_id`를
   TEXT(FK 아님)로 보존하므로 **read-time resolver로 rekey 없이** M-id 해석 가능(채택). 물리 일괄
   재키잉(option b)은 미성년 PII·되돌리기 위험으로 **비채택**(우선순위 #1·#2). 1:N 매핑 시 confidence
   상위 우선·다중 표시(리포트 계층 결정).

### 1.4 리스크
- 강결합 44+ 파일 → 점진·공존 전제(빅뱅 금지). 각 슬라이스는 *측정 후 노출*(`04b` shadow→canary 패턴 재사용).
- crosswalk 거짓매핑 = 오도된 코칭(우선순위 #1·#3) → 사람 승인·confidence 게이트 필수.

---

## 2. 파서(동치 권위) 일원화

### 2.1 현재(부채)
- **SymPy**(`l3/verify_step.py`·`l3/verify_answer.py`) = *동치·검산 판정 권위*(단계 동치·수치 검산).
- **mathjs**(`src/web/graphing-calculator/src/lib/graph2dSpec.js`) = 그래프 렌더용 표기 변환
  (`**`→`^`·`toTex`). **동치 판정은 하지 않음**(렌더 전용).
- 부채는 "엔진 중복"이 아니라 **표기 계약 부재** — 두 파서가 implicit multiplication·`^`/`**`·
  유니코드 기호를 다르게 해석하면 *같은 식이 다르게 보이는* drift가 가능.

### 2.2 목표 불변식 (Q10-⑦)
**동치 권위는 SymPy 단일**. mathjs는 *렌더 전용*이며 정오·동치 판정에 절대 관여하지 않는다.

### 2.3 설계
1. **경계 명문화**(문서·코드 주석) — `graph2dSpec.js`에 "동치/정오 판정 금지·표기 변환만" 불변
   주석. 동치가 필요한 어떤 흐름도 SymPy(L3)를 거친다.
2. **표기 계약(golden test)** — py(SymPy 정규화)↔js(mathjs 파싱) 동일 입력 집합(implicit mult,
   `^`/`**`, 음의 부호, 유니코드 `²`·`π`)에 대해 *동일 정규 표기*를 산출하는지 교차검증하는
   golden fixture. CI 양쪽 잡에서 같은 fixture를 읽어 drift를 잡는다.
3. **비목표** — 브라우저에서 SymPy 실행(불가·과설계)·mathjs를 SymPy로 대체(렌더 성능 손실).

### 2.4 런타임 권위 일원화 + 오개념 거짓 항등식 grounding (구현 완료)
파이썬 *런타임* 내부에서도 SymPy 동치 관용구가 `verify_step`에 인라인돼 있었고(오개념 카탈로그는
거짓 항등식을 *문자열*로만 다룸) "권위 둘"이 잠재했다(math_dsl 감사 §7). 교정:
- **단일 primitive** `l3/symbolic_equivalence.py` `identity_status(lhs, rhs) -> IdentityVerdict`
  (identity/not_identity/undecidable/parse_error). SymPy `sympify(convert_xor)`+`expand`+
  `simplify().is_zero`+다항/변수집합 관용구를 *한 곳*에 둔다. `verify_step`은 이 primitive에
  *위임*하도록 리팩터(3상태·reason 동작 불변·기존 테스트 그대로 green).
- **오개념 `canonical_wrong_form`**(`Misconception` 선택 필드·(lhs, rhs) SymPy syntax) — 카탈로그
  무결성 테스트가 `identity_status`로 **not_identity**(거짓임을 SymPy가 증명)임을 강제한다. 정직
  스코프: 다항 거짓 항등식만 부여(`distribution-over-power`·`exponent-zero`). 정의역 의존(`√(x²)`)·
  초월(`log`)·유리식은 SymPy 미결정이라 *미부여*(거짓 머신검증 주장 금지). 런타임 탐지 경로는
  불변(regex/substring) — 본 슬라이스는 *카탈로그를 기호 권위로 grounding*하고 차후 탐지 통합의
  canonical 표현을 깐다.
- **파싱 소스 정규화 일원화**(위첨자·후속): 유니코드 위첨자(`x²`) 치환이 `wrong_form_match`에만
  있어 `identity_status`는 위첨자를 parse_error로 떨구고 L4가 *미리* 변환해 넘겨야 하는 divergence가
  있었다(감사 §7 파싱 관례 갈림·실제 위첨자 버그로 표면화). `to_sympy_source`(strip + 위첨자 0~9→
  거듭제곱)를 `l3/symbolic_equivalence`로 올려 **단일 소스**로 두고 `identity_status`가 내부 적용
  (위첨자 입력을 정상 판정·strict 개선·기존 판정 불변)·`wrong_form`은 사설 복제를 제거하고 재사용
  한다. *잔여*: `validate_response`(`l3/pregenerate/validator.py`)의 `implicit_multiplication` 변환은
  별개 파싱 관례라 후속 통일(관계식 검증 특화·회귀 리스크 분리).

### 2.5 오개념 탐지 SymPy 통합 (shadow 1차·구현 완료)
`canonical_wrong_form`을 *런타임 탐지*에 결선한다 — `l4/misconception/wrong_form_match.py`:
- **`matches_wrong_form`/`detect_wrong_forms`**: 학생 등식을 추출(`extract_equations`)해
  `canonical_wrong_form`을 **SymPy Wild 정합**으로 푼다 — 학생이 *거짓 규칙을 적용*했는지 표기·
  변수명 무관 판정(lhs는 Wild 바인딩·rhs는 `identity_status`로 동치 확인). 기호(`(x+y)²=x²+y²`·
  `(p+q)²=p²+q²`)·수치(`(3+4)²=3²+4²`·학생 lhs `evaluate=False` 구조보존) 인스턴스 둘 다 잡아
  손으로 쓴 `regex_signals`를 일반화한다. **거짓-등식 가드**: 우연히 참(`(3+0)²=3²+0²`)·올바른
  형태는 제외(오개념 인스턴스는 실제 거짓 등식이어야 함·RS2 낙인 차단). 상수 평가 템플릿
  (`a⁰`→1)은 구조 정합 불가로 제외(정직).
- **shadow 전용**: `observe_wrong_form_shadow`(coach `solution_coaching` 결선)는
  `misconception_wrong_form_mode=="shadow"`일 때 SymPy 탐지와 기존 substring/regex(`diagnose`)를
  비교해 SymPy-only 순기여를 *로그로만* 남긴다 — 노출(diagnose 반환)·verdict 불변·비차단·학생
  원문 미기록(미성년 PII). 기본 `off`. 노출 전 분포 측정으로 canary/full 통합 근거를 모은다.
- *(완료·측정 도구)* **분포 harvest** — `wrong_form_shadow_harvest`가 관측 JSONL을 읽어 SymPy vs
  substring 탐지 분포(일치·SymPy 순기여 id별 빈도·substring 단독 id별 빈도)를 집계한다
  (`crosslink_shadow_harvest` 동형·오프라인·순수·비노출). SymPy 순기여=통합 가치, substring 단독=
  결합 후 substring이 계속 커버할 오개념 — canary 통합·결합 정책의 정량 근거.
- *(잔여)* shadow 측정 후 노출 통합(substring과 결합·canary)·수치 인스턴스 구조보존 파서.

---

## 3. 교육과정 `curriculum_version`·`subject` 완전 Overlay 이관 (구현 완료)

> **범위 명확화 (2026-07-02)**: "완전 Overlay 이관"의 대상은 ***개념 노드***(영속 자산)의
> curriculum·subject 필드다. **`Problem`의 `curriculum_version`은 이관 대상이 아니다** — 문항은
> 특정 개정판을 위해 저작된 *콘텐츠*라 curriculum_version이 이중 진실이 아니라 문항 본질 속성이며,
> L6 학교진도 게이트 ③(2015/2022 혼입 방지)의 살아있는 소비처다(§3.1이 "게이팅은
> `Problem.curriculum_version` 사용·Concept과 독립"으로 이미 명시). failure_mode_qa가 이를 "잔여
> 부채·상환 필요"로 등록한 것은 **오등록**이며 2026-07-02 유지 확정으로 상환 목록에서 제외됐다
> (동 문서 "정정 추가 2026-07-02"·`Curriculum` enum docstring 정본).

### 3.1 결과
`grade_introduced`·`semester_introduced`(rev d1e2f3a4b5c6)에 이어 `curriculum_version`·`subject`도
**제거 완료(PR #350·rev f3a4b5c6d7e8)**. 조사 결과 두 필드의 *런타임 READ/필터 소비처가 0*이었고
(교육과정 정합 게이팅은 전부 `Problem.curriculum_version` 사용·Concept과 독립), `idx_concept_level
(level, subject)`도 활용 쿼리가 없어 `(level)`로 축소했다. 즉 "소비 경로 재설계 동반"이라던 초안
가정은 *과대평가*였고 단순 제거가 안전했다(enum `subject_enum`·`curriculum_enum`은 Problem이 계속
사용하므로 타입만 보존·컬럼만 drop).

### 3.2 Overlay 적재기 (이번 슬라이스)
교육과정 분류의 단일 진실은 `curriculum_entry` Overlay다. 그 **KR 적재기를 구현**했다
(`l1/curriculum/curriculum_loader.py`·`populate.py` CLI):
- **소스**: `graph.json` 개념 중심 직접 매핑(개념당 1 KR 셀·concept_id 정합). `domain`→`domain_label`·
  `grade_band_hint`→`grade_band`/`introduced_grade`(밴드 하한)·`standard_codes`→
  `national_standard_codes`·`review_status`→`confidence`. KR 상수(country=KR·license=KR-NCIC·
  revision="2022 개정"·source_url=NCIC)는 graph.json `source_citation`에서 정직 도출(공공누리 1유형).
- **멱등**: `entry_id`(=`{concept_id}:KR`) PK 충돌 ON CONFLICT DO UPDATE — `created_at` 보존·
  `updated_at` 갱신. concept_id는 FK 아닌 느슨참조라 개념 선적재 비의존(독립 적재).
- **범위**: Phase 1 KR만(US는 ccss_code뿐 표준 코퍼스 없음·IMO 코퍼스 없음).
- **`required_depth` 휴리스틱**(사용자 결정 2026-07·"grade_band 학년진행"): 인지 깊이 원문 주석이
  없어(cognitive_level 부재) `grade_band`를 깊이 프록시로 파생(`_GRADE_BAND_TO_REQUIRED_DEPTH` —
  초1-2 awareness·초3-6 procedural·중 conceptual·고 mastery). 나선형 교육과정 통설 기반 coarse
  휴리스틱(개념별 진리 아님)이며 L6 깊이정렬 *랭킹 보너스*(하드 게이트 아님·상한 1.5)에만 쓰인다 —
  cognitive_level 원문 확보 시 대체. 미지 밴드는 None(정직 폴백). 이로써 L6 깊이보너스가 활성화됨
  (기존 항상 0 → grade_band 있는 KR 개념에 목표난이도 정합 보너스).
- **잔여(후속)**: US/IMO 열·cognitive_level 원문 주석(휴리스틱 대체)·`required_depth`의 L5 api
  resolver 주입 배선(Problem.curriculum_required_depth 비영속 채움).

---

## 참고
- 정본 상위: `math_dsl_risk_register.md`·`math_dsl_principles_review.md`
- 구현 좌석: `l4/misconception/`(kebab)·`schema/misconception_catalog.py`(M-id)·`l3/verify_step.py`·
  `l3/verify_answer.py`·`src/web/graphing-calculator/src/lib/graph2dSpec.js`·`schema/curriculum_entry.py`·
  `l1/curriculum/curriculum_loader.py`(KR Overlay 적재기)
- 패턴: `04b_misconception_judge_graduation.md`(shadow→canary→full 점진 노출)
- 운영: `shadow_measurement_runbook.md`(네 오개념 게이트 shadow 켜기→관측 수집→harvest 집계→
  canary 판정 절차·crosslink/wrong_form/semantic/judge harvest 도구 사용법)
- 원칙: `CLAUDE.md`(의사결정 우선순위 1·2·3·미성년 PII)
- 변경 이력: v0.1 (2026-06-30 초안 — 설계만) · v0.2 (2026-06-30 — §3 구현 완료: 필드 제거 PR #350 +
  curriculum_entry KR 적재기) · v0.3 (2026-06-30 — §0 invariant 회귀 동결 게이트 5종 구현 완료·PR #357)
