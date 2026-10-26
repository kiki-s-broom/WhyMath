# 변형 코퍼스 편입 결정과 계보만 걸기 (PB-20)

> **판정 기준**: main `dc214a2f` (2026-10-13 실측 — 작업 브랜치 HEAD와 `origin/main`이 같은 커밋).
> 미머지 근거는 쓰지 않았다. 아래 수치는 이 커밋 위에서 CLI를 다시 돌려 얻었다.
> 근거 문서: `problem_bank_variants_pb09.md` §4·§5. 선행: `cat_sibling_filter_relation_policy_pb19.md`.

## 0. 결론 한눈에

| 질문 | 결정 |
|---|---|
| PB-09 변형 코퍼스를 커밋하는가 | **커밋한다 — 단 `problem_bank_*` 글롭 밖 스테이징**(`data/corpus/problem_variants_staging_v0/`)에. 313행, 사이드카에 sha256 동결 |
| 언제 노출되는가 | 검수 표본 감사(Wilson 게이트)를 통과해 **글롭 안으로 승격**된 뒤에만. 승격은 §4의 5단을 한 PR로 한다 |
| 왜 글롭 안(30종과 같은 `other` 부류)에 두지 않는가 | CAT·L6는 닫혀 있지만 **공개 카탈로그 GET이 열려 있다**(PB-08 미착수). 글롭 안에 두면 미검수 313건이 그 구멍으로 나간다 (§1.3) |
| 중복으로 탈락한 자식은 | 새로 낳지 않고 **기존 문항 사이에 관계만** 건다 — 전체 시드 실측 **36건 연결 가능 · 35건 CAT 도달** (§3) |
| 이번 PR이 DB에 쓰는가 | 아니다. 연결 후보는 사이드 JSONL까지만 — 적재는 후속 태스크 (§6) |

## 1. 노출 경로 조사 (acceptance ①)

노출은 두 층에서 일어난다. 파일 층(코퍼스 JSONL을 읽는 코드)과 서빙 층(DB의 `problem` 행을 읽는 코드)이다.
학생에게 닿는 것은 서빙 층이고, 파일 층은 그 DB를 채우거나(적재) 재거나(측정) 상속 재료를 만든다(빌드).

### 1.1 `is_published`는 게이트가 아니다

`problem.is_published`는 **읽는 코드가 0건**이다. 나오는 곳은 생성기 docstring, ORM·스키마 정의, 관리자 CMS 편집 허용 필드 목록(`api/admin_cms_resources.py`)뿐이고,
`l3/dsl/models.py:25` 주석이 "별개의 게시 축이며 현재 읽는 코드가 없다(ADMIN-12)"고 자인한다.
코퍼스 14,538행(2026-10-13 판정 기준) 전부 `False`지만 그 값이 노출을 막은 적은 없다. **그래서 `is_published=False`를 노출 방어로
세지 않는다.** 실제로 노출을 막는 축은 `review_status` 하나다.

### 1.2 서빙 층 — 검수 공백 행이 학생에게 닿는가

`Problem`을 SELECT하는 서빙 코드 12곳을 전수 열거(`select(Problem` 계열 grep)해 대조했다.

| 표면 | 코드 | 게이트 | 검수 공백(`review_status` 없음) 행 |
|---|---|---|---|
| 기본 CAT 후보 풀 | `l2/next_problem_selection.py::candidate_pool_conditions` | SQL `review_status == approved` (허용목록) | **차단** |
| 학습상태 추천(R6) | `l2/learning_state_recommendation.py` | 위 풀을 그대로 재사용(조건 재작성 0) | **차단** |
| 수능 정책 | `api/_next_problem_policy.py` → `l6/suneung/recommendation.py::recommend_suneung_index` → `is_suneung_eligible` → `l6/_shared.py::is_review_cleared` | SQL에는 검수 조건이 없고 **후보 선택 단계 Python 게이트**가 `approved`만 통과 | **차단** (후보 풀 크기에는 잡히나 선택되지 않는다) |
| L6 6모드·blueprint | `api/gating.py` · `l6/*/gating.py` · `l6/blueprint/assembly.py` | `is_review_cleared` | **차단** |
| 개념 평가 재료 상속 | `harness/concept_assessment_index.py`(빌드) → `l3/render/assessment_bank.py`(런타임 조회) | `is_review_status_cleared` | **차단** |
| 공개 카탈로그 GET 4종 | `api/problems.py` | `quarantined`만 배제(SEC-07 D1 — `pending`·공백도 나간다) | **열림** |
| 학습 지도 | `l1/standards/learning_map.py` | 없음 | 열림 — 단 id·형식·난이도 메타뿐, 본문 없음 |
| 진단 프로브 후보 | `l1/problem_bank/probe_candidates.py` | 없음 — `distractor_map` 보유 행만 읽음 | **불활성** — 변형 행에는 `distractor_map`이 없다 (테스트로 동결) |
| 이미 정해진 id 조회 | `l3/multi_solution.py` · `api/_attempt_misconception_scan.py` | 후보를 고르지 않음 | 해당 없음 |
| 관리자 표면 | `api/admin_bff.py` · `api/admin_cms.py` | 인가 | 해당 없음 |
| 학생 이력 | `/v1/me/ability/history` | 의도적 미필터(격리 계약 §2-3) | 해당 없음 |

### 1.3 발견 — 닫히지 않은 곳은 공개 카탈로그 하나다

판정 기준 시점(2026-10-13) 코퍼스는 14,538행 중 `approved` 2,984 · `pending` 158 · **공백 11,396**이다. 공백 11,396행은 승인된 적이
없는데 이미 `problem_bank_*` 글롭 안(30종)에 있다. CAT·L6는 허용목록이라 이를 막지만, 공개 카탈로그는
`quarantined`만 빼므로 이 행들이 나간다. 이 구멍은 `PB-08`(`todo`, 의존 없음)이 소유한다.

이것이 편입 결정의 핵심 전제다. **글롭 안 `other` 부류는 "서빙의 허용목록이 막아 준다"는 가정으로만
안전한데, 공개 카탈로그가 그 가정 밖이다.** 313건을 거기에 더하면 미검수 문항이 나가는 표면이 313건 늘어난다.

### 1.4 파일 층 — `problem_bank*` 글롭을 쓰는 소스 24개

소스·스크립트의 경로형 문자열 상수 전수(AST) 스캔 결과다. 모두 디렉터리명 글롭(`problem_bank_*` 또는
`problem_bank*`)이라 **디렉터리 이름이 일치하지 않으면 읽지 않는다.** `tests/.../test_variant_intake_pb20.py`가
이 표가 낡지 않게 지킨다 — 글롭을 쓰는 새 파일이 생기면 이 표에 올리기 전까지 RED다.

| 부류 | 파일 | 하는 일 | 학생에게 닿는가 |
|---|---|---|---|
| 적재 | `src/backend/whymath_backend/l1/problem_bank/populate.py` | 코퍼스 → DB 멱등 upsert. `review_status`를 코퍼스 값 그대로 쓴다 | 직접은 아님. 적재된 행은 §1.2 표의 게이트가 결정 |
| 빌드→런타임 | `src/backend/whymath_backend/harness/concept_assessment_index.py` | 개념 평가 재료 상속 후보 선별 | 닿을 수 있음 — **`approved`만**(L303) |
| 코퍼스 변이 | `src/backend/whymath_backend/harness/problem_corpus_author_backfill.py` | `authored_by` 서명을 코퍼스에 제자리 기입 | 아님 (승격 후 대상이 됨 — §4) |
| 측정(분자=승인) | `src/backend/whymath_backend/l1/standards/phase3_coverage.py` | Phase 3 커버리지 — `approved` 문항만 센다 | 아님 |
| 측정(분자=승인) | `src/backend/whymath_backend/harness/ai_quality_eval_set.py` | P3-10 AI 품질 평가셋 — `approved` 이고 PRIMARY 개념이 대표 과정인 문항의 `verify`·보기·`distractor_map` 을 id로 해석하는 오프라인 평가기(학생 응답 경로가 아니다) | 아님 |
| 측정(분자=승인) | `src/backend/whymath_backend/ops/phase3_remediation.py` | P3-06 오답→교정 전략 커버리지 — `approved` 객관식 문항의 보기·정답·distractor_map 만 읽는 오프라인 측정기(학생 응답 경로가 아니다) | 아님 |
| 측정(분자=승인) | `src/backend/whymath_backend/ops/phase3_metrics.py` | Phase 3 지표 — `approved` 문항만 센다 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/qa_pipeline.py` | CI QA 축(조건식 DSL 위반 순회) | 아님 — 단 분모에 들어가면 CI 판정이 바뀐다 |
| 측정(CI 게이트) | `src/backend/whymath_backend/l3/notation_coverage.py` | 표기 커버리지 | 아님 — 단 게이트라 미검수 행의 표기 결손이 CI를 깬다 |
| 측정(CI 게이트) | `src/backend/whymath_backend/l3/curriculum_notation_gate.py` | 교육과정 표기 게이트 | 아님 — 위와 같다 |
| 측정 | `src/backend/whymath_backend/harness/attempt_grading_shadow_report.py` | 서버 채점 섀도 리포트 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/selective_grading_demotion_eval.py` | 채점 결함 주입 강등전 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/crosslink_demotion_eval.py` | 오개념 크로스링크 강등전 | 아님 |
| 측정 | `src/backend/whymath_backend/l4/misconception/crosslink_machine_reject.py` | 크로스링크 기계 거부 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/misconception_false_positive_eval.py` | 오개념 오탐 평가 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/banned_words_pii_eval.py` | 금칙어·PII 평가 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/answer_distribution_battle.py` | 정답 위치 분포 편향 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/problem_bank_coverage.py` | 커버리지 리포트 | 아님 |
| 측정 | `src/backend/whymath_backend/harness/curriculum_revision_crosswalk_report.py` | 개정판 어휘 crosswalk 관측 | 아님 |
| 측정 | `src/backend/whymath_backend/ops/repeat_recommendation_report.py` | 반복 추천 리포트 | 아님 |
| PB-09/PB-20 | `src/backend/whymath_backend/harness/problem_corpus_variants.py` | 변형 파생 — 시드 signature로 코퍼스를 읽는다 | 아님 |
| PB-09/PB-20 | `src/backend/whymath_backend/harness/problem_corpus_lineage_links.py` | 계보만 걸기 — 시드 역인덱스로 코퍼스를 읽는다 | 아님 |
| 분석 스크립트 | `scripts/analysis/corpus_facts.py` | 코퍼스 사실 단일 원천 — 은행별·전체 건수 계산(OPS-154) | 아님 |
| 분석 스크립트 | `scripts/analysis/answer_form_requirement_scan.py` | 정답 형식 요건 스캔 | 아님 |
| 분석 스크립트 | `scripts/analysis/eos_anchor_asset_audit.py` | EOS 앵커 자산 감사 | 아님 |
| 분석 스크립트 | `scripts/analysis/measure_sympy_isolation_budget.py` | SymPy 격리 예산 실측 | 아님 |
| 분석 스크립트 | `scripts/analysis/p3_01_scope_inventory.py` | Phase 3 범위 인벤토리 | 아님 |

파일 층의 두 가지 위험은 **노출이 아니다.** ① 측정 도구의 **분모**에 검수 안 된 313건이 섞여 수치를 바꾼다
(승인만 세는 두 곳은 영향 없음) ② CI 게이트(`notation_coverage`·`curriculum_notation_gate`·`qa_pipeline`)가
새 행의 결손으로 깨질 수 있다. 스테이징은 둘 다 막는다.

이 스캔이 못 잡는 부류도 있다 — 디렉터리 이름을 상수로 직접 가리키는 코드(예: `harness/problem_type_mapping.py`의
코퍼스명 상수, `scripts/demo/seed_demo.py`). 이들은 특정 코퍼스를 이름으로 고르므로 스테이징을 이름으로
고르지 않는 한 읽지 않는다. 디렉터리명에 묶이지 않는 열거(`rglob("problems.jsonl")` 등)가 소스에 **0건**임은
테스트가 동결한다 — 하나라도 생기면 이름 기반 격리가 그 소비처에 대해 무의미하다.

### 1.5 이 조사에서 함께 나온 결함

`harness/review_status_domains.py`의 `_REPO_CORPUS_DIR = Path("data/corpus")`는 **상대경로**다.
`corpus_backfill_refusal`(다른 코퍼스의 감사 근거로 각인하려는 시도를 거부하는 가드)이 이 값으로 "레포 코퍼스
아래인가"를 판정하므로, 작업 디렉터리가 저장소 루트가 아니면 같은 입력에 거부 대신 `None`을 돌려준다.
실측: 루트에서 `거부됨`, `src/backend`(CI 백엔드 잡의 cwd)에서 `None`. 운영 호출(루트)에서는 동작하고
이 PR의 승격 보호(§4)도 루트 기준으로 동결했지만, **가드가 cwd에 따라 침묵으로 꺼진다**는 사실은 별도 태스크로
등재한다(§6).

**해소 (OPS-138)**: 원인은 `_REPO_CORPUS_DIR` 하나가 아니라 세 지점이었다 — 레포 코퍼스 디렉터리 판정·고정
코퍼스 식별(`_is_known_fixed`)·제 짝 경로 비교가 모두 cwd에 붙어 있었다(`src/backend`에서 `classify_corpus`가
고정 코퍼스를 `other`로 분류하는 것까지 실측). 세 지점을 모듈 파일 위치 기준 `_REPO_ROOT`로 앵커했다.
같은 모양(상대 Path 상수를 cwd 의존 연산에 거는 코드)을 AST로 전수 스캔한 결과는 `src/backend/whymath_backend`·
`scripts` 907파일에서 **침묵 오작동 0건**이며, 후보 11파일 중 대부분은 이미 `__file__` 기준 앵커이고
`ci_job_coverage`·`ci_mirror`의 cwd 상대 `--workflow` 기본값은 파일이 없으면 `ScanEmptyError`로 소리 내어
실패한다. 이 스캔은 별칭·함수 인자로 우회하는 모양은 보지 못하므로 회귀 가드로만 읽는다
(`tests/backend/harness/test_relative_path_const_cwd_scan.py`).

## 2. 편입 결정 (acceptance ②)

### 2.1 결정

PB-09 산출물을 `data/corpus/problem_variants_staging_v0/{problems.jsonl,_provenance.json}`에 커밋한다.

- **디렉터리명이 `problem_bank*`로 시작하지 않는다.** 파일 층의 모든 노출 경로가 `problem_bank*` 글롭이므로
  (§1.4) 어느 것도 이 로트를 읽지 않는다. `problems.jsonl`이라는 파일명은 **일부러 유지**했다 —
  `ops/provenance_audit.py`가 그 파일명을 보고 라이선스·출처 필드 결손을 검사하므로, 이름을 바꾸면
  스테이징이 위생 감사 밖으로 빠진다.
- **메타는 비워 둔다.** `review_status` 키 없음 · `is_published=False` · `problem_type_codes=[]` ·
  `persona_fit={}` · `authored_by` 없음. 공백은 정상이다 — `review_status_stamping_contract.md` §2가 `other`
  부류의 공백을 "노출 차단이며 결함이 아니다"라고 정의한다. `pending`을 **미리 찍지 않는 이유**: 백필 CLI는
  이미 채워진 값을 불가침으로 두므로(§3 충돌 규칙) `pending`을 박아 두면 코퍼스 단위 감사가 영영 `approved`를
  각인하지 못한다.
- **로트를 동결한다.** 사이드카의 `sha256`·`record_count`가 이 로트의 정체다.

### 2.2 왜 재생성하지 않고 커밋하는가

변형 산출물은 **저장소 전체 상태의 함수**다. 구조 중복 판정의 시드가 `problem_bank_*` 전 코퍼스라서,
무관한 코퍼스 하나가 추가돼도 결과가 바뀐다. 실측: PB-09 문서(2026-10-08)는 저장소 316건이라 적었으나
같은 CLI를 오늘(`dc214a2f`) 다시 돌리면 **313건**이다 — 그 사이 늘어난 코퍼스가 자식 3건을 구조 중복으로 만들었다.
감사 표본추출은 모집단이 고정돼야 성립하므로, 감사 대상 로트는 재생성이 아니라 **커밋된 바이트**여야 한다.

CLI는 두 번 실행해 바이트 동일(sha256 `be102af9…`)임을 확인했다 — 같은 저장소 상태에서는 재현된다.

### 2.3 로트는 하나다 — 모드별로 쪼개지 않는다

코퍼스 단위 백필의 승인 조건은 감사 표본 **n ≥ 200** · 결함율 Wilson 95% 단측 상한 ≤ 0.02다
(`problem_corpus_review_status_backfill._MIN_N`·`_MAX_DEFECT_UPPER`). 로트 구성은 다음과 같다.

| 모드 | 행 | 이동 |
|---|---|---|
| 난이도 계열 (`wm-var-lad`) | 85 | `ladder_harder` 75 · `ladder_easier` 10 |
| 조건변형 (`wm-var-cnd`) | 158 | `condition_flip` 92 · `condition_sign` 66 |
| 역문제 (`wm-var-inv`) | 70 | `inverse` 70 |
| **합계** | **313** | |

**어느 모드도 단독으로 200에 못 미친다.** 모드별 코퍼스로 쪼개면 감사 자체가 불가능하다. 313건 전체로
감사해야 하며 그러면 **로트의 64%(200/313) 이상을 표본으로 봐야 한다** — 사실상 전수에 가깝다. 이 비용이
승격의 실제 문턱이다. (결함 0건이면 n=200에서 상한 약 0.0133으로 통과, 결함 1건이면 n=222 필요.)
`test_only_the_whole_lot_can_reach_the_audit_minimum`이 이 사실을 동결해, 누군가 로트를 쪼개 감사 경로를
여는 시도를 RED로 만든다.

### 2.4 근거 차용 금지

부모 `generated_v0`는 승인됐지만(감사 240건) **변형은 부모의 승인을 물려받지 않는다.** 변형은 부모가
아닌 새 문항이고, 승인된 부모에서 파생됐다는 사실은 변형이 옳다는 증거가 아니다. 스테이징 경로를 다른 코퍼스의
감사 키로 각인하려 하면 `corpus_backfill_refusal`이 거부한다(루트 실행 기준 — §1.5).

## 3. 계보만 걸기 (acceptance ③)

### 3.1 문제

PB-09가 파생한 자식 630시도 중 47건이 `rejected_duplicate/structural_signature`로 저장이 막혔다
(`ladder_harder` 2 · `ladder_easier` 11 · `condition_flip` 34). 같은 방정식·같은 근 선택이 이미 있다는 뜻이니
**새 문항은 필요 없다.** 대신 부모와 그 기존 문항 사이에 `problem_relation`만 걸면 신규 콘텐츠 0으로
계열이 는다.

### 3.2 설계 — `harness/problem_corpus_lineage_links.py`

1. PB-09와 같은 파생기(`derive_variants`)로 자식 후보를 낸다 — 파생 로직을 복제하지 않는다.
2. **시그니처 → 소유 문항 역인덱스**를 만든다. PB-09의 `load_corpus_index`는 signature **집합**만 돌려줘
   "어느 문항이 그 구조인가"를 모른다 — 이 역인덱스가 새로 필요한 유일한 부품이다. 키 산식은 같고, 두 인덱스의
   키 집합이 같음은 테스트가 동결한다.
3. 소유 문항이 있으면 (부모 → 소유 문항) 관계 후보를 낸다. 유형은 PB-09 이동 표 그대로다
   (`ladder_harder`→심화 · `ladder_easier`→선수 · `condition_*`→변형 · `inverse`→대조). 소유 문항이 여럿이면
   검수 통과 → 코퍼스명 → slug 순으로 결정론으로 하나를 고르고 남은 대안 수를 후보에 싣는다.
4. 산출은 `--out` 사이드 JSONL뿐이다. **봉인된 코퍼스의 `relations`를 제자리에서 늘리지 않는다**
   (`problem_corpus_batch`의 바이트 동일 재생성 계약). DB에도 쓰지 않는다.

### 3.3 방향·상한 규약

- 방향은 항상 **부모(코퍼스 문항) → 기존 문항**이다 (PB-09 §2와 같다).
- **한 쌍(순서 무관)은 한 번만** 이어진다. 코퍼스에 이미 어느 방향·유형으로든 관계가 있으면 건너뛴다 —
  같은 쌍에 유형을 덧얹으면 PB-19 분류기가 읽는 역할이 모순될 수 있다(모순은 중립 처리되어 정책 효과가 사라진다).
- **상한: 문항당 관계 ≤ 10**(`MAX_RELATIONS_PER_RECORD`). 새 수치를 만들지 않고
  `test_relation_governance.py`의 `_MAX_RELATIONS_PER_RECORD`를 승계하며 값 일치를 테스트가 동결한다.
  이동은 5종이고 부모·이동당 자식이 최대 1이므로 부모 하나가 낳는 후보는 구조적으로 5 이하다.
  현행 코퍼스의 문항당 관계 최대는 3, 부모 출차수 최대는 4다.

### 3.4 실측 — 작동한 비율 (전체 시드, `dc214a2f`)

`python -m whymath_backend.harness.problem_corpus_lineage_links --dry-run` (약 1분, LLM 0 · DB 0).
부모 619행 중 자격 126행, 시도 630.

| 이동 | 시도 | 파생 | 연결 | 새 구조(연결 아님) | 이미 이어진 쌍 | 이번 실행 중복 쌍 |
|---|---|---|---|---|---|---|
| `ladder_harder` | 126 | 77 | 1 | 76 | 0 | 0 |
| `ladder_easier` | 126 | 23 | 9 | 13 | 0 | 1 |
| `condition_flip` | 126 | 126 | 26 | 94 | 4 | 2 |
| `condition_sign` | 126 | 68 | 0 | 68 | 0 | 0 |
| `inverse` | 126 | 77 | 0 | 77 | 0 | 0 |
| **합계** | 630 | 371 | **36** | | 4 | 3 |

- **연결 36건 · 그중 CAT 도달 35건**(부모·상대가 모두 `approved`여야 CAT 후보 풀에서 쓰인다). 유형은
  변형 26 · 선수 9 · 심화 1. 연결 후 문항당 관계 최대 4 — 상한 10에 한참 못 미친다.
- PB-09의 구조 중복 47건은 **36(연결) + 7(이미/이번 실행 중 이어진 쌍) + 4(이번 실행 안에서 먼저 저장된
  자식과 겹친 것 — 연결 대상 문항이 코퍼스에 아직 없다)**로 정확히 나뉜다. 마지막 4건을 연결하지 않는 것이
  맞다: 상대가 될 기존 문항이 없다.
- `condition_sign`·`inverse`는 연결 0이다. 연립 조건이라 signature가 없어(None) 코퍼스 구조 중복 자체가 성립하지
  않는다 — 구조적 한계이며 숨기지 않고 0으로 드러낸다.

### 3.5 정직한 한계

- 연결 후보는 **구조 일치**를 근거로 한다. 두 문항의 발문·난이도 라벨이 같다는 뜻은 아니다. 선수(쉬운 쪽)
  관계의 "더 쉬움"은 PB-09의 이동 정의(정답 근을 고정하고 다른 근을 정수화)에서 오며, 기존 문항의 실측 난이도로
  재확인하지 않았다. 난이도 보정은 `PB-10` 소관이다.
- 이 경로는 **측정과 후보까지**다. 후보를 `problem_relation`에 적재하는 단계가 없으므로 지금은 CAT·공개
  카탈로그 어디에도 닿지 않는다 (§6).

## 4. 승격 절차 — 스테이징 → `problem_bank_*` (한 PR)

노출되기 전에 모든 보호를 통과해야 하므로 순서가 중요하다. 아래 5단을 **한 PR에서** 수행한다 — 이동과 각인
사이에 머지가 끼면 공백 상태의 로트가 글롭 안에 노출 경로에 놓인 시간이 생긴다(공개 카탈로그가 열려 있는 한).

1. **결정론 백필을 스테이징 파일에 명시 경로로 적용한다** — 유형 태깅(`problem_type_backfill`) ·
   `persona_fit` · `authored_by`(`deterministic:` 서명). 감사자가 최종 콘텐츠를 보게 하기 위함이며, 감사 이벤트는
   내용 지문을 싣기 때문에(EOS-27) 감사 뒤의 편집은 라벨을 무효화한다.
2. **로트 sha256을 갱신해 다시 동결한다.**
3. **감사 라벨 표본을 만든다 — n ≥ 200(로트의 64% 이상)**. 결함율 Wilson 상한 ≤ 0.02가 아니면 승격하지 않는다.
   이 단계는 사람 또는 측정 통과 기계 게이트(검증 권위 서열 ②)가 한다 — 이 PR이 대체하지 않는다.
4. **`KNOWN_CORPORA`·`AUDIT_LABEL_MAP`에 새 코퍼스 키를 등록**한다 (코퍼스 단위 백필의 고정 목록).
5. **디렉터리를 `problem_bank_variants_v0`로 옮기고 백필을 돌린다.** 공백이 `approved`/`rejected`로 각인된다.
   관계 거버넌스(`test_relation_governance.py`)의 코퍼스 목록과 `_WIRED_CORPORA`도 같이 갱신한다.

이 절차 어디에도 `generated_v0`의 승인을 쓰지 않는다(§2.4).

## 5. 집행 지점 (acceptance ④ — 정본화와 별항)

결정이 문서에만 있지 않도록, 각 보호가 **실제 서빙·적재 경로의 코드와 맞물림**을 테스트로 동결했다.

| 무엇 | 테스트 (`tests/backend/harness/`) | 동결하는 것 |
|---|---|---|
| 로트 동결 | `test_variant_intake_pb20.py::test_staged_lot_matches_its_sidecar` | 행 수·sha256이 사이드카와 같다 |
| 글롭 밖 | `::test_no_exposure_glob_matches_the_staging_directory` | 소스·스크립트 전수 글롭 상수가 스테이징 디렉터리와 일치하지 않는다 (양성 대조군 + 스캔 0건 실패) |
| 이름에 안 묶인 열거 없음 | `::test_no_source_enumerates_every_corpus_directory_for_problem_rows` | `rglob("problems.jsonl")` 류 0건 |
| 적재 발견 | `::test_populate_discovery_does_not_return_the_staging_file` | `discover_problem_corpora`가 스테이징을 반환하지 않는다 |
| slug 충돌 | `::test_staged_slugs_are_disjoint_from_every_exposed_corpus` | 승격 시 upsert 덮어쓰기 없음 |
| 서빙 술어 | `::test_serving_review_predicate_rejects_every_staged_row` | `is_review_cleared`가 스테이징 313행을 전부 거부 (`approved` 통과 대조군) |
| CAT 풀 | `::test_cat_candidate_pool_requires_approved` | 실제 후보 풀 WHERE에 `approved` 항이 있다 |
| 근거 차용 | `::test_staging_is_not_a_known_corpus_and_cannot_borrow_another_audit` | 다른 코퍼스 감사 키로 각인 거부 (루트 실행 조건) |
| 로트 크기 | `::test_only_the_whole_lot_can_reach_the_audit_minimum` | 모드별로 쪼개면 n≥200 불가 |
| 위생 감사 | `::test_provenance_audit_covers_the_staging_directory` | 사이드카·행 필드 감사가 스테이징을 본다 |
| 조사 문서 | `::test_investigation_doc_names_every_glob_consumer` | §1.4 표가 글롭 소비처를 전부 담는다 |
| 신규 모듈 귀속 | `tests/infra/test_eos_feature_inventory_v2.py` · `ops/declared_unwired_audit.py` | 계보 링크 모듈이 인벤토리 행(WM-O-909)에 귀속되고, 미배선(적재 단계 부재)이 `pending-task:PB-23-…`로 선언된다 — PB-23이 닫히면 선언이 만료되어 감사가 다시 빨개진다 |
| 계보 링크 | `test_problem_corpus_lineage_links.py` | 방향·유형·이미 이어진 쌍·상한·깔때기 항등식·PB-09 오케스트레이터와의 차분·PB-19 분류 |

결함 주입 검증 결과는 PR 본문에 둔다.

## 6. 선행(⑤)과 분리한 것

**⑤ 선행**: PB-19(머지 커밋 `dc214a2f`, #1590 — 이 문서의 판정 기준 커밋이다)가 관계 유형별 소비 정책을 이미 정했다 — 변형·유사=대칭 형제,
선수=쉬운 계열(오답 직후 우대), 심화=어려운 계열(중립), 대조=형제 아님. 계보가 CAT에 닿기 전에 정책이 있어야
한다는 순서는 지켜졌다. `test_link_relation_types_are_classified_by_the_pb19_policy`가 연결 후보가 쓰는
세 유형(변형·선수·심화)을 PB-19 분류기가 역할로 읽음을 동결한다.

**이번 범위 밖(후속 태스크로 등재 — 대장에 실재)**:

1. **연결 후보 적재** — `PB-23-variant-lineage-links-populate-apply`. 사이드 JSONL을 `problem_relation`으로
   올리는 `populate` 확장. 이 단계가 있어야 계보가 CAT에 닿는다. 닿기 전에 `sibling_filter` 기본 OFF가
   유지되는지 확인한다.
2. **스테이징 로트 감사·승격** — `PB-24-variant-staging-lot-audit-and-promotion`. §4의 5단. 감사 라벨 ≥ 200건이 필요하다.
3. **`corpus_backfill_refusal` cwd 의존 결함** — `OPS-138-backfill-refusal-cwd-relative-guard` (§1.5).
4. `PB-08` — 공개 카탈로그가 `approved`를 요구하게 하는 일. 이것이 닫히면 §1.3의 위험 전제가 사라져 글롭 안
   `other` 부류도 안전해지고 스테이징의 필요가 줄어든다. 그때까지 이 PR의 스테이징이 313건을 그 구멍에서 지킨다.
