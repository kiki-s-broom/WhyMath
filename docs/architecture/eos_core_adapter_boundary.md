# EOS Core ↔ Math Adapter 경계 — 현행 패키지 배정표 v1 (EOS-65)

> **지위**: `EOS-65-core-adapter-boundary-map` 산출물. `EOS-66`(SubjectAdapter 계약)·
> `EOS-67`(import-linter 강제)의 **선결 입력**이며, G1(2026-09-27) 차단 조건
> "Core→Math 정적 의존 0"의 *판정 기준 그 자체*다.
>
> **배정 정본은 이 문서가 아니라 코드다** — `scripts/analysis/eos_core_adapter_boundary_scan.py`
> 의 `BOUNDARY_MAP`이 단일 진실 원천이고, 본 문서는 그 표를 전사·해설한다(선례:
> `eos_anchor_asset_audit.py`의 `ANCHOR_DEFS`가 EOS-51 앵커 동결 정본). 배정을 바꾸려면
> 스크립트를 고친다 — 문서만 고치면 이중 진실 원천이 된다.
>
> ## ⚠️ 정본화 ≠ 집행 — 이 표는 **아무것도 강제하지 않는다**
>
> 이 문서와 스캔 스크립트는 *계측기*다. 배정을 기계가 강제하는 지점은 **`EOS-67`**
> (import-linter forbidden 계약 + CI 배선 동결)이며, 그것이 착지하기 전까지:
>
> - ~~새 코드가 경계를 넘어도 **CI는 통과한다**.~~ → **2026-08-31 `EOS-67` 착지로 해소** —
>   import-linter 계약 2건이 CI lint 스텝에서 판정한다(§5). 아래 두 줄은 여전히 유효하다.
> - 아래 "위반 15건"은 *막고 있는 상태에서 남은 15건*이 아니라 **아무도 막지 않은 상태의 15건**이다.
> - 따라서 이 문서의 존재를 근거로 "경계가 있다"고 말하면 안 된다. 지금 있는 것은 **경계의 정의**뿐이다.
>
> 대조 시점: 2026-08-31 · main `3f512962` 기준 · 스캔 대상 **556 모듈 / 155,435 LOC** · 스캔 오류 0.

---

## §1. 판정 규칙

계획서 100 §3.7의 단일 문장이 규칙이다 — **"Core가 이차방정식을 알게 만들면 안 된다."**
이를 판정 가능한 형태로 옮기면:

| 배정 | 정의 | 판별 질문 |
|---|---|---|
| **CORE** | 과목과 무관한 교육 실행 엔진 | Physics를 붙일 때 **이 모듈을 고쳐야 하는가?** 아니오 → CORE |
| **ADAPTER** | 수학 의미론(기호 조작·수식 표기·수학 엔티티 타입)을 인코딩 | 이 모듈이 아는 것이 *수학*인가? 예 → ADAPTER |
| **INFRA** | 횡단 관심사(설정·DB 세션·보안·관측성·하네스) | 계층 계약의 대상이 아님 |
| **MIXED** | 한 모듈 안에 CORE 기계와 ADAPTER 의미론이 동거 | 파일 단위로 못 가름 → **그대로 MIXED로 적는다** |

**MIXED를 반올림하지 않는 이유**: 애매한 모듈을 CORE로 반올림하면 위반 수가 부풀고, ADAPTER로
반올림하면 위반이 숨는다. 둘 다 EOS-67의 baseline 설계를 잘못 이끈다. 34건은 애매한 채로 남겼다.

**수학 신호는 근거이지 판정이 아니다.** 스캔이 재는 `sympy` import 수와 수학 어휘 밀도는
배정을 *뒷받침*할 뿐 결정하지 않는다. 밀도 0이어도 ADAPTER인 모듈이 있고(수학 엔티티를 실어
나르는 순수 적재기 — `l1.formula_graph`), 밀도가 높아도 CORE인 모듈이 있다(수학 코퍼스를
다루는 범용 하네스). 배정은 사람이 하고 근거만 기계가 잰다.

---

## §2. 계획서 100 §3.7 항목 ↔ 현행 패키지 대응

### EOS Core 14항목

| 계획서 Core 항목 | 현행 좌석 | 상태 |
|---|---|---|
| Identity | `security` · `consent` · `consent_grant` · `db.models.user*` | INFRA로 분류(횡단) |
| Curriculum | `l1.curriculum` · `l1.standards` · `db.models.curriculum_framework` | CORE ✓ |
| Knowledge Graph | `l1.atom_graph` · `l1.concept_graph` · `l1.skill_graph` · `l1.concept_atom_crosswalk` | CORE ✓ |
| Learning Model | `l2` 전체(22모듈) | CORE ✓ — 수학 신호 **0건** |
| Assessment | `l2.ability_estimation` · `l2.irt` · `l2.item_calibration` · `l3.pedagogy`(예심) | CORE ✓ |
| Recommendation | `l2.prerequisite_recommendation` · `l2.weak_concept_recommendation` · `l2.learning_path` | CORE ✓ |
| Content | `l1.concept_content` · `l1.problem_bank` · `l3.render` · `l3.dsl` | CORE(dsl은 MIXED) |
| Pedagogy | `l4`(polya·socratic·lthc·pedagogy) · `l1.pedagogy` | CORE ✓ |
| AI Orchestration | `l3.router` · `l3.providers` · `l3.pipeline` · `l3.cache` · `l3.queue` | CORE ✓ |
| Event | `schema.analytics_event` · `l2.evidence_event_store` · `db.models`(이벤트 테이블) | CORE ✓ |
| Analytics | `l2.learning_metrics_rollup` · `ops` | CORE / INFRA |
| QA | `l3.pedagogy`(예심·검수) · `harness`(게이트) | CORE / INFRA |
| Versioning | `schema`(schema_version) · alembic · `l3.prompt_assets` | 분산 — EOS-44/47/49 소유 |
| Security | `security` · `privacy` | INFRA ✓ |

**판정**: 14항목 중 **좌석이 없는 항목은 0건**이다. Core 기능은 전부 실재하며, 문제는 부재가
아니라 *섞임*(§4)이다.

### Math Adapter 10항목

| 계획서 Adapter 항목 | 현행 좌석 | 배정 |
|---|---|---|
| Math AST | `l3.speech`(AST→낭독) · `l3.equivalent`(정규화) | ADAPTER ✓ |
| LaTeX | `l3.render` 경유 · `schema.problem` 필드 · `l1.formula_graph` | 분산 — MIXED 다수. **S1-16(2026-08-31) 착지로 수학 전용 4필드가 `extensions.math`로 구조화**됐으나, 하위호환용 legacy top-level 필드가 남아 양방향 동기화되므로 `schema.problem`은 여전히 MIXED다(CORE 승격은 legacy 제거가 선결 — breaking이라 미채택) |
| Equation equivalence | `l3.equivalent`(26모듈·12,119loc) | ADAPTER ✓ |
| Symbolic manipulation | `l3.symbolic_equivalence` | ADAPTER ✓ |
| Graph rendering | `l3.visualization`(명세만) + 클라 렌더 | CORE — 명세는 구조라 중립 |
| Geometry representation | **좌석 없음** | 미구현(현행 코퍼스 범위 밖) |
| Proof structure | **좌석 없음** | 미구현(Lean4 보류 상태) |
| Mathematical expression parsing | `l5.ocr` · `l3.speech_parse` | ADAPTER ✓ |
| Math misconception detectors | `l4.misconception.wrong_form_match` (+shadow harvest) | ADAPTER ✓ |
| Math problem validators | `l3.verify_answer` · `verify_step` · `verify_final_answer` · `verify_solution` · `verifier` · `solution_set` · `finite_probability` · `statistical_claim` | ADAPTER ✓ |

**판정**: 10항목 중 **8건 좌석 실재 · 2건 미구현**(Geometry·Proof). 미구현 2건은 갭이 아니라
현행 범위 밖이다 — 앵커 6개(EOS-51 §2)에 기하 증명 단원이 없다.

---

## §3. 계층별 배정 실측

스캔 출력(`--json`) 집계. 어휘 밀도는 근거 자료다(§1 단서).

> **2026-08-31 갱신**: `EOS-66` 착지로 2모듈이 `BOUNDARY_MAP`에 추가됐다 —
> `schema.subject_adapter`(CORE·계약) · `l4.subject_adapter_math`(ADAPTER·구현). 그만큼
> 합계가 늘었고 **위반 수는 15로 불변**이다(어댑터는 ADAPTER→CORE 방향으로만 의존).

| 계층 | CORE | ADAPTER | MIXED | INFRA |
|---|---|---|---|---|
| `l1` 데이터 기반 | 75모듈 / 13,946 loc | — | 6 / 608 | — |
| `l2` 학습자 모델 | **22 / 5,035** | — | — | — |
| `l3` 생성·검증 | 39 / 8,910 | **39 / 19,938** | 15 / 3,019 | — |
| `l4` 교수학 | **77 / 14,920** | 3 / 485 | 4 / 588 | — |
| `l5` 상호작용 | 1 / 18 | 9 / 1,605 | — | — |
| `l6` 응용 모드 | **17 / 2,837** | — | — | — |
| `api` | 37 / 15,814 | — | 3 / 462 | — |
| `schema` | 33 / 7,194 | — | 6 / 3,549 | — |
| `db`·`ops`·`privacy`·`harness`·`whs` | — | — | — | 166 / 53,871 |
| **합계** | **301 / 68,732** | **51 / 22,028** | **34 / 8,226** | **174 / 58,587** |

> **이 표는 스냅샷이다** — 머지마다 수치가 바뀐다(2026-08-31만 해도 세 번 갱신했다).
> 판정을 다시 뽑으려면 `python3 scripts/analysis/eos_core_adapter_boundary_scan.py`를
> 돌린다. 표를 손으로 맞추기보다 **불변량**을 보는 편이 낫다 — CORE의 `sympy` import 0건,
> `l2`·`l6`의 수학 신호 0건, 위반 15건(EOS-69가 줄인다).

**교차 검증 — CORE의 `sympy` import는 0건이다.** 전체 27건의 sympy import 중 ADAPTER 18 ·
MIXED 7 · INFRA 2(하네스)로 갈렸고 CORE는 정확히 0이다. 배정을 손으로 했는데 독립 신호가
경계와 일치했다는 뜻이라, 배정이 자의적이지 않다는 근거로 삼을 수 있다.

**가장 깨끗한 계층**: `l2`(학습자 모델)와 `l6`(응용 모드)는 수학 어휘·sympy 전부 0이다.
Physics를 붙일 때 **이 두 계층은 손대지 않아도 된다** — 계획서 100 §4-⑥의 합격 기준
("Math가 제대로 동작하고, Physics를 붙일 때 Core를 뜯지 않아도 되는 수준")이 이미 성립한 구역이다.

**가장 섞인 계층**: `l3`. 한 계층에 AI 오케스트레이션(CORE)과 수학 검증(ADAPTER)이 39:39로
동거한다. 경계선은 계층 사이가 아니라 **`l3` 한가운데를 지난다** — 7계층 축(현행 import-linter
계약)이 이 축을 볼 수 없는 이유이자, EOS-67이 별도 계약이어야 하는 이유다.

---

## §4. CORE → ADAPTER import 위반 — 착수 시점 15건 → **현재 0건**

> **갱신 2026-08-31 (EOS-69 완료)**: 아래 15건은 *EOS-65 실측 시점*의 값이다. 상환 결과는
> §4.1에 별도로 적는다 — 원 측정을 덮어쓰지 않는 이유는 "무엇이 있었는지"가 "지금 몇
> 건인지"만큼 중요하기 때문이다(같은 형태의 위반이 다시 생기면 여기가 대조 기준이 된다).

`EOS-67`의 baseline 허용 필요 여부를 판정하는 근거다(EOS-65 acceptance ②).

**결론: baseline 허용이 필요하다.** 위반이 0이 아니므로, EOS-67이 계약을 걸면 **즉시 CI가 적색**이
된다. 15건을 고치고 계약을 거는 것과, 계약을 걸며 15건을 만료 있는 baseline으로 동결하는 것 중
후자를 권고한다(§5).

### 15건 전수 — 성격별 3분류

| 성격 | 건수 | 위반 | 판단 |
|---|---:|---|---|
| **A. 진성 위반** — Core가 수학 검증을 직접 호출 | **11** | `api.coach` → `verify_final_answer`(2)·`verify_solution`(1) · `l6.blueprint.assembly` → `verify_solution`(1)·`verify_step`(2) · `l3.pedagogy.slot_generator` → `symbolic_equivalence`(2) · `l3.render.adapters` → `verify_answer`(1)·`equivalent.rephrase`(2) | EOS-66 SubjectAdapter가 흡수해야 할 정확히 그 지점 |
| **B. 오배치 유틸** — 경계 문제가 아니라 파일 위치 문제 | **3** | `l3.render.adapters` → `l3.equivalent.josa`(`eul_reul`·`eun_neun`·`i_ga`) | `josa.py`는 **한국어 조사 받침 판별**(모듈 docstring 자인)로 과목과 무관하다. 수학 패키지 안에 살 이유가 없다 — 옮기면 위반 3건이 소멸한다 |
| **C. DI 배선** — 어댑터 팩토리 참조 | **1** | `api._ocr_state` → `l5.ocr.factory.OcrComponents` | 구현체 직접 참조. EOS-66 Protocol 경유로 바꾸면 해소되는 부류 |

### A분류가 말하는 것

11건 전부가 **"Core가 정답을 판정하려고 수학 모듈을 부른다"**는 한 가지 형태다. `api.coach`(학생
대화 표면)·`l6.blueprint.assembly`(모드 조립)·`l3.render.adapters`(콘텐츠 렌더)는 셋 다 과목을
몰라야 하는 자리인데, 셋 다 수학 검증 함수를 직접 import한다.

이것이 **EOS-66이 필요한 이유의 실측 증거**다. `SubjectAdapter.evaluate_answer()`가 있었다면
이 11건은 Protocol 호출 1개로 대체됐을 자리다. 반대로 EOS-66 없이 EOS-67 계약만 걸면 이 11건은
고칠 방법이 없어 baseline에 영구 동결된다 — **순서가 EOS-66 → EOS-67이어야 하는 근거**다.

### §4.1 상환 결과 — 15 → **0건** (EOS-69 완료 2026-08-31)

세 축으로 갚았다. **축을 나누어 적는 이유는 셋의 신뢰도가 다르기 때문이다** — ①②는 코드가
바뀌었고 ③은 판정이 바뀌었다.

| 축 | 건수 | 무엇을 했나 | 무엇이 증거인가 |
|---|---:|---|---|
| **① 타입** | 6 | Core가 어댑터를 부른 이유가 *상태 enum 하나*뿐이던 간선. `VerifyStepState`·`FinalAnswerState`·`IdentityVerdict`를 과목 중립 계약(`schema/verification_capabilities.py`)의 `VerificationOutcome`·`EquivalenceOutcome`으로 올리고 어댑터는 **별칭**으로 공유 | `VerifyStepState is VerificationOutcome`(동일 객체·값 보존). 변환 객체를 만들지 않았으므로 상태 재해석 지점 자체가 없다 |
| **② 배선** | 8 | Core가 기본 구현을 스스로 골라 오던 간선(`slot_generator`·`coach`·`render.adapters`). 능력별 좁은 Protocol을 **주입**받게 하고, 기본 구현 선택은 합성 루트 `whymath_backend.composition`(INFRA) 한 곳으로 | `mypy --strict` 565파일 통과 + 어댑터 쪽 `_*_CONFORMANCE` 대입 4건이 시그니처까지 검사 |
| **③ 분류** | 1 | `api._ocr_state → l5.ocr.factory`. `OcrComponents`를 **타입 주석으로만** 쓰고 필드를 한 번도 읽지 않는 app.state 배관(`_l3_state`와 동형)이라 INFRA로 재배정 | **코드 변경 0** — 이 1건은 위반이 사라진 게 아니라 위반이 아니었다고 판정한 것이다 |

**왜 함수 안 지연 import로 숨기지 않았나.** `slot_generator`의 1차 시도가 정확히 그것이었고,
경계 스캔·import-linter는 **지연 import도 그대로 본다**. 숨기면 위반이 사라지는 게 아니라
보이지 않게 될 뿐이다. 합성 루트는 그 반대다 — 어댑터를 아는 지점을 *한 곳으로 모으고* 그
사실을 계약에 명시적으로 적는다(7계층 계약의 좁은 예외 2줄).

**합성 루트가 세탁 통로가 되지 않게 하는 장치.** `-> whymath_backend.composition` 전체를
열지 않고 **간선 단위로** 예외했다(현재 2줄: `slot_generator`·`render.adapters`). 새 Core→
composition 간선이 생기면 그 즉시 `lint-imports`가 적색이 되어 *그때마다 판단*을 강요한다.

**남은 정직한 잔여.** 능력을 주입받는 세 호출부는 아직 **기본 구현 선택 편의**를 쓴다
(`equivalence=None`이면 합성 루트에 묻는다). 호출부가 능력을 상류에서 받아 내리면 그 2줄도
사라진다. 위반이 없어진 게 아니라 **작아졌고**, 남은 크기를 계약에 적어 두었다.

### 이 숫자의 한계 (정직한 공백)

- **MIXED 34모듈은 위반 계산에서 빠진다.** CORE로 배정된 것만 출발점으로 센다. MIXED를 CORE로
  간주하면 위반은 늘어난다 — 즉 **15는 하한이다.**
- **정적 import만 잡는다.** 동적 import·문자열 경유 참조·DI 컨테이너 등록은 안 보인다.
- **재수출(re-export) 경유는 원 소유 패키지로 귀속되지 않는다.** `__init__`이 다시 내보낸 심볼을
  통해 들어가는 간접 경로는 이 스캔의 사각이다.

---

## §5. 집행 — `EOS-67` 착지 (2026-08-31)

**정적 강제가 착지했다.** 이 문서 머리의 "⚠️ 정본화 ≠ 집행" 경고는 §5 범위에서는 **해소됐다** —
`src/backend/pyproject.toml`에 import-linter `forbidden` 계약 2건이 서고, CI lint 스텝
(`run: lint-imports`)이 매 PR에서 이를 판정한다. 남은 미집행은 §4 A분류의 *경유 배선*(EOS-69)이다.

| 계약 | source | 유예 | 상태 |
|---|---|---|---|
| **baseline 0 — 이미 깨끗한 구역** | `l1` · `l2` · `schema` | **없음** | KEPT. 이 구역이 수학을 새로 끌어오면 즉시 적색 |
| **baseline 있음 — EOS-69가 해소** | `api` · `l4` · `l6` · `l3` CORE 키 20 | 20 | KEPT (20 ignored) |

**유예 20건의 성격은 둘로 갈린다** (pyproject 주석에 그룹 ①②로 분리 표기):

- **그룹 ① 구조적 제외 11건 — 빚이 아니다.** 출발점이 ADAPTER(3) 또는 MIXED(8)인 간선이다.
  계약은 "CORE로 지정한 모듈"만 구속하므로 애초에 위반이 아니고, 부모 패키지를 source로 잡은
  탓에 걸릴 뿐이다. MIXED를 지금 강제하면 §1이 유보한 판정을 조기에 강요하게 된다.
- **그룹 ② baseline 9건 — 이것이 빚이었다.** §4 A·B·C분류의 심볼 15건을 모듈 단위로 축약한
  수였다(`api.coach` 3심볼→2간선 · `l6.blueprint.assembly` 3→2 · `l3.render.adapters` 6→3 ·
  `l3.pedagogy.slot_generator` 2→1 · `api._ocr_state` 1→1). 소유자는 **`EOS-69`**였다.

  **2026-08-31 현재 이 그룹은 0줄이다**(§4.1). 구역 자체는 비운 채 남겼다 — 다음 빚이 생겼을
  때 "여기가 적는 자리"임을 알리는 표지가 필요하기 때문이다. 대신 7계층 계약 쪽에 합성 루트
  경유 예외 **2줄**이 새로 생겼다: 빚의 총량이 9 → 2로 줄었고, 성격도 "Core가 어댑터를 직접
  부른다"에서 "Core가 배선 지점을 부른다"로 바뀌었다. 후자가 왜 더 나은지는 §4.1 마지막 문단.

**만료는 날짜가 아니라 기계다.** `unmatched_ignore_imports_alerting`이 기본 `ERROR`이므로,
EOS-69가 어떤 간선을 없애면 대응하는 유예 줄이 매치되지 않아 `lint-imports`가 실패한다 —
CI가 "이 줄을 지워라"라고 말한다. 실측 확인(뮤테이션 C): `l6.blueprint.assembly`의
`verify_step` import를 제거하니 `No matches for ignored import ...`로 exit 1. 유예가 조용히
눌러앉을 수 없다("만료 없는 유예 금지"의 코드 집행). **이 장치는 실제로 작동했다** — EOS-69의
두 차례 상환에서 매번 `No matches for ignored import ...`가 먼저 CI를 적색으로 만들었고,
그 다음에 목록이 줄었다(총 3라운드: 9→8→4→0). 사람이 읽을 재확인 지점은 **G1(9/27)** —
그때 이 목록이 여전히 0줄인지 확인한다(0도 재확인 대상이다).

**드리프트 방지**: `tests/infra/test_eos_boundary_contract_wiring.py`가 pyproject의 forbidden
목록을 `BOUNDARY_MAP`(정본)과 대조하고, CI가 `lint-imports`를 실제로 부르는지, 만료 정책이
꺼지지 않았는지를 함께 동결한다. pyproject만 고치고 정본을 안 고치면 CI가 적색이 된다.

**측정 축의 한계(명시)**: 계약은 `allow_indirect_imports = true`로 **직접 import만** 판정한다.
경계 스캔이 AST 직접 import를 세므로 축을 맞춘 것이다 — 간접까지 세면 계약과 이 문서가 서로
다른 숫자를 말하게 된다. 따라서 `api.coach → l4 → l4.solution_coaching → wrong_form_match`
같은 *경유* 의존은 이 계약이 잡지 않는다. 그 축은 MIXED 모듈 해소와 함께 다룰 별개 문제다.

**재측정**: `python3 scripts/analysis/eos_core_adapter_boundary_scan.py` — 위반 수 변화가 진척
지표이고, `lint-imports`가 그 진척을 강제한다.

---

## §6. 재현

```bash
# [실행 시스템: 저장소 루트 — Linux/WSL 또는 Windows PowerShell]
cd C:\Users\kiki\Desktop\__AI\WhyMath   # PowerShell인 경우
python3 scripts/analysis/eos_core_adapter_boundary_scan.py
# 배정표·위반표·오류 수를 stdout으로, 진행 로그를 stderr로 낸다
python3 scripts/analysis/eos_core_adapter_boundary_scan.py --json out.json --markdown out.md
```

종료코드는 **스캔 성공 여부**만 뜻한다(0=측정됨·1=측정 실패). **위반 수로 exit 1을 내지 않는다** —
이 스크립트는 게이트가 아니라 계측기이며, 게이트는 EOS-67이 세운다. 측정 자체가 실패하면
"위반 0"이 아니라 exit 1이 나오게 설계했다(측정 실패가 통과로 위장되면 안 된다).

**변별력 확인 기록** (2026-08-31): `l2.bkt`(CORE)에 `l3.symbolic_equivalence`(ADAPTER) import를
주입 → 위반 **15 → 16**, 표에 `l2.bkt` 행 출현. cp 백업으로 원복 → **15**, `git diff` 공집합
확인. (원복을 `git checkout --`로 하지 않은 이유 = 2026-08-10 미커밋 구현분 소실 사고 규칙.)

---

## §7. 다음 검토일

`EOS-67` 착지 시 — baseline에 실제로 들어간 항목과 이 문서 §4의 15건을 대조하고, 해제된 건수를
§4 표에 갱신한다. 배정 자체의 변경은 `BOUNDARY_MAP`을 고치고 본 문서를 재전사한다.
**추가(2026-09-04)**: `l4.solution_coaching` 분리 또는 오개념 카탈로그 데이터 이전이 착지하면 §8을
재측정한다(`eos_core_boundary_probe.py`) — 잔여 누수 2·어휘 상수 77이 첫 실측 기준값이다.

---

## §8. "수학을 제거했을 때 무엇이 남는가" — 전이 도달·금지 규칙 실측 (EOS-84 · 2026-09-04)

> 계획서 100 §3.7의 두 문장을 계측으로 옮겼다. 계측기 = `scripts/analysis/eos_core_boundary_probe.py`,
> 게이트 = `tests/infra/test_eos_core_boundary_probe.py`(리터럴 비교 기준선 **0건**(EOS-85로 해소)·과목명 비교 0 · 잔여 누수 집합 동결).
> **정본화 ≠ 집행**: 이 절의 숫자는 스냅샷이고, 강제는 그 테스트와 EOS-67 계약이 한다.

### 8.1 전이 도달 — EOS-67이 못 보는 축

> ⚠️ **이 절의 수치는 2026-09-04 시점(EOS-84)이다.** EOS-89가 등록(push) 형태로 바꾸면서 전이
> 도달 14 → 2, 합성 루트 경유 14 → 0으로 재실측됐다 — 최신 값은 **§9.2-b**를 보라. 이 절을
> 덮어쓰지 않는 이유는 §8이 *그때의 측정 기록*이기 때문이다(판정에는 시점이 붙는다).

import-linter 계약은 **직접 import**만 판정한다(§4 "정직한 공백"). "수학을 제거하면 함께 깨지는
Core"는 *경유* 의존까지 따라가야 보인다. CORE 266모듈 각각에서 import 간선을 BFS로 따라 처음 만나는
ADAPTER까지의 경로를 전수 산출했다.

| 측정 | 값 | 뜻 |
|---|---:|---|
| CORE → … → ADAPTER 직접 import | **0** | EOS-69 상환 결과 그대로(§4.1) |
| 전이 도달 | **14 / 266** | 수학을 지우면 함께 import에 실패하는 CORE |
| 최단 경로가 합성 루트 `composition` 경유 | 2026-08-31 스냅샷 14/14 (아래 갱신 참조) | **설계된 유일 교체점** 경유 — Physics를 붙일 때 이 파일만 바꾸면 살아난다(EOS-69) |
| **잔여 누수**(교체점을 막아도 닿음) | **2**(2026-09-06 EOS-86 재실측 — 누수 지점 교체) | `api.coach` · `api.ocr_handoff` → `harness.wh1_primary` → `harness.wh1_loop`(**INFRA**) → `l3.verify_solution`(ADAPTER 직접 import) |
| 수학 제거 후 온전히 남는 CORE | 2026-08-31 스냅샷 252/266 (아래 갱신 참조) | `l1` 62 · `l2` 21 · `l3` 27 · `l4` 66 · `l6` 9 · `api` 32 · `schema` 34 · `lang` 1 |

**[EOS-86·2026-09-06 갱신] `l4.solution_coaching` 축은 상환됐다 — 그런데 잔여 누수는 0이 되지
않고 자리를 옮겼다.** `l4.solution_coaching`을 CORE로 재배정하고 `l3.verify_solution`·
`l4.misconception.wrong_form_match` 직접 import를 `StepChainVerifier` 선택층 주입(기본
구현은 합성 루트 `composition.default_step_chain_verifier`·`default_wrong_form_shadow_
observer` 경유)으로 교체했다 — BFS로 실측하면 `solution_coaching` 경유 경로는 실제로 0이다.
그런데 그 경로가 *최단*이어서 이전 스캔은 더 긴 경로를 보지 못했을 뿐이었다: `api.coach`/
`api.ocr_handoff`는 `harness.wh1_loop`(INFRA — WH-1 튜터링 루프)를 통해서도 `l3.verify_
solution`에 닿는다. `harness`는 `composition`과 달리 DESIGNED_SEAMS(설계된 유일 교체점)가
아니라서(`BOUNDARY_MAP`의 `harness` 배정 사유 "상위 계층 호출이 정상이라 계층 계약 밖"은
*허용*이지 *교체점*이라는 뜻이 아니다) 이 경로를 막지 못한다. **정직한 결론**: 잔여 누수 건수는 여전히 2건이고, 원인은
`l4.solution_coaching`에서 `harness.wh1_loop`로 옮겨갔다 — EOS-86은 그 축을 온전히 상환했지만
*전체 잔여 누수를 0으로 만들지는 못했다*(이 발견은 EOS-86 범위 밖 후속 태스크 `ARCH-99`로
분리 등재했다). 위 표의 다른 스냅샷 수치(14/14·252/266 등)는 이번 세션에서 재검증하지 않았다
— 모듈 수 자체가 556→583으로 늘어 있어 그대로 인용하면 오도할 수 있다(다음 정기 재측정 몫).

**읽는 법(2026-08-31 원문 — solution_coaching 축만 위 갱신으로 대체)**: 최단 경로 다수는
*설계*다 — `l3.pedagogy.slot_generator`·`l3.render.adapters`·`api.coach`·(EOS-86부터)
`l4.solution_coaching`이 `composition`에서 능력 구현을 받아 오는 배선(EOS-69 ② "기본 구현
선택 편의")이고, 그 줄들은 계약에 좁은 예외로 적혀 있다. 동결 열쇠는 (출발점, 누수 지점)이다
— 끝 ADAPTER는 동률이 있어 열쇠로 쓰면 탐색 순서에 따라 흔들린다(첫 구현이 `set`을 그대로
순회해 해시 시드마다 다른 끝점을 냈고, 정렬 순회로 고정한 뒤 열쇠도 바꿨다).

### 8.2 금지 규칙 — `if subject == "math"` · `if problem.type == "quadratic"`

CORE 266모듈의 AST에서 **비교문(`Compare`)·`match` 패턴의 문자열 리터럴**이 과목명(`math`·`수학`…)
또는 수학 유형(`quadratic`·`trig*`·`polynomial`…)인 곳을 찾았다.

**히트 0건 — `EOS-85`로 해소**(2026-09-06 · 판정 기준 main `dc2e6583`).

종전에 남아 있던 1건은 아래 자리였다:

| CORE 모듈 | 위치 | 종류 | 내용 |
|---|---|---|---|
| ~~`l1.problem_bank.populate`~~ | ~~`_verify_meta_from_raw` L363~~ | ~~math_type~~ | ~~`kind_raw in ("real_root_count", …, "inequality_direction", …)` — answer_kind **17종 튜플 열거**~~ → **제거됨** |

진단은 옳았다 — 적재기(CORE)가 answer_kind **허용 어휘**를 갖고 있으면 Physics 어댑터가
`"unit_consistency"`를 들고 와도 적재 단계에서 걸러지고, 이는 EOS-66의 "answer_kind는 Core가
해석하지 않는 불투명 문자열" 계약과 정면 충돌한다. 다만 상환은 예상했던
`SubjectAdapter.answer_kinds()`로의 **이관**이 아니라 **열거 자체의 제거**였다: 어휘를 어댑터로
옮기면 Core는 여전히 "허용 목록을 조회해 거른다"는 동작을 갖는데, 애초에 **적재기가 거를 일이
아니다**. 검증 가능 여부의 판정 권위는 L3 검산(`l3.equivalent.acceptance._CONCEPTUAL_VERIFIERS`)
이고, 적재기는 값을 **형식만 보고 그대로 통과**시킨다.

부수 효과로 **조용한 손실**도 사라졌다 — 종전에는 목록에 없는 값이 예외도 경고도 없이 `None`이
되어 "answer_kind 없는 문항"으로 보였다(`S4-17` `finite_probability` 손실이 그 전례).

> ⚠ **이 0이 보장하는 범위**(과대주장 방지 · EOS-85 결함 주입 실측). 스캐너는 리터럴을
> `MATH_TYPE_RX`(접두 목록)로 판정하는데, 위 17종 중 그 정규식에 걸리는 것은
> **`inequality_direction` 하나뿐**이었다. 즉 히트 1건은 사실상 그 한 값이 만들었고,
> 화이트리스트를 3종·7종으로 되살려도(그 값 제외) **히트는 0으로 유지된다**. 그러므로
> "리터럴 비교 0"은 *접두 목록에 걸리는 어휘가 없다*는 뜻이지 과목 어휘 열거가 전부 사라졌다는
> 뜻이 아니다. 같은 파일의 `answer_selection`(largest/smallest/unique)·`answer_aggregate`
> (sum/product)가 **지금도 같은 형태로 남아 있으면서 스캔에 안 잡히는** 실례다.
> 매처 확장과 그 두 필드의 처분은 `EOS-01`이 소유한다. 그때까지 `answer_kind` 축의 실질
> 보호는 행동 축 회귀 테스트가 맡는다(`test_load_passes_unknown_answer_kind_through_verbatim`
> — 같은 뮤테이션에서 실제로 RED).

테스트는 이제 **빈 기준선**을 동결한다 — 새 자리가 생기면 RED, 실측이 더 줄면 기준선을 다시
내리라고 실패시킨다(ratchet). 과목명 비교는 기준선 없이 0을 강제한다. 결함 주입
(`if subject == "math":`·`if problem.type == "quadratic":`·튜플 멤버십·`case "trig_identity":`·
역순 비교)이 각각 1건으로 검출됨을 확인했다(변수 대 변수 비교·대입·docstring·`"pending"`은 비검출).

### 8.3 그러나 Core는 *데이터로* 수학을 안다 — 어휘 상수 77건 / 18모듈

비교문은 깨끗한데, **문자열 상수**(docstring 제외)에 수학 어휘가 박힌 자리가 있다. 이것은 §3.7의
금지 규칙 위반은 아니지만 "Core가 이차방정식을 안다"의 다른 형태다.

| CORE 모듈 | 건수 | 성격 | 처방 방향 |
|---|---:|---|---|
| `l4.misconception.catalog` | 31 | 수학 오개념 64종 카탈로그가(착수 메모 "34종"은 stale — `test_misconception_catalog.py`가 64로 동결) **코드 상수**(예 `'제곱근 양수 가정'`) | 카탈로그 *기계*는 중립, *내용*은 과목 데이터 — `data/corpus`(L1) 이전 후보 |
| `schema.pedagogy_pack` | 8 | 예시 문자열 `'이차함수'·'일차함수'·'삼각함수'` | 스키마 설명의 예시 — 과목 중립 예시로 교체 가능 |
| `l4.misconception.distractor` | 7 | op-code 카탈로그 시드(`'연쇄법칙 내부 도함수 누락'`) | catalog와 동형 — 데이터 이전 후보 |
| `l4.misconception.models` | 5 | 영역 enum 설명(`미적분·삼각함수·벡터`) | 영역 분류를 과목 데이터로 |
| `l3.pedagogy.slot_generator` | 4 | **LLM 프롬프트 예시**에 `이차함수 $f(x)=x^2-4x+…` | 프롬프트 예시는 교수법 팩(과목별)으로 |
| `l3.solution_path` | 3 | `ApproachType` 한글 라벨 `'조합적'`(수학 접근법 분류) | 접근법 어휘의 과목 소유 판정 필요 |
| `schema.visualization` · `l3.viz_eval` · `l3.visualization` | 6 | `graph-quadratic`·정적분 영역·`a*x**2+…` 예시 | 명세 자체는 중립, 예시가 수학 |
| 그 외 9모듈 | 13 | `schema.concept/standard/textbook_mapping` 필드 설명의 예시(`'미적분학의 기본정리'`), `schema.user` "벡터 저장소"(거짓 양성) | 대부분 설명 예시 — 위해 낮음 |

**판정**: 어휘 상수의 무게 중심은 `l4.misconception`(43/77)이다 — EOS-65가 "카탈로그·crosslink·판정
큐·probe 36모듈 중 sympy 접촉 2건뿐 — 기계는 중립"으로 CORE에 둔 배정은 *로직*으로는 맞고 *데이터*로는
새는 자리다. Physics 오개념을 붙일 때 `catalog.py`를 고쳐야 하면 그것은 Core가 아니다. 등재는
Kiki 판정(후보: 카탈로그 내용을 `data/corpus/misconceptions_v*`로 이전하고 코드는 로더만 남기기).

### 8.4 재현·정직한 공백

```bash
# [실행 시스템: 저장소 루트 — Linux/WSL 또는 Windows PowerShell]
cd C:\Users\kiki\Desktop\__AI\WhyMath   # PowerShell인 경우
python3 scripts/analysis/eos_core_boundary_probe.py                 # 마크다운 리포트
python3 scripts/analysis/eos_core_boundary_probe.py --json probe.json
```

- 전이 도달은 **정적 import**다. `app.state` DI·`Depends`·문자열 경유 참조는 안 보인다(인벤토리 v2의
  DI 다리는 엔드포인트 도달성용이라 여기엔 적용하지 않았다 — 적용하면 `composition` 외 교체점이 더
  드러날 수 있다).
- 어휘 스캔은 낱말 목록이다. 일반어와 겹치는 낱말(함수·로그·실수·소수·분수·확률)은 의도적으로 뺐다 —
  거짓 양성이 신호를 덮기 때문이며, 그만큼 **놓치는 것도 있다**(`schema.user`의 "벡터 저장소"는
  반대로 거짓 양성이다).
- MIXED 29모듈은 두 계측 모두에서 *출발점*이 아니다(§1 반올림 금지와 같은 이유). 잔여 누수 2건이
  전부 MIXED를 경유한다는 사실이 그 사각의 크기를 말한다.

---

## §9. 허용 의존 방향 — Application → Core → Subject Interface ← Math Adapter (EOS-88 · 계획서 100 §3.8 · 2026-09-04)

> §3.8은 두 그림을 준다. **권장**: `Application → EOS Core → Subject Contract → Math Adapter`.
> **실행 시 어댑터가 Core에 등록되는 형태라면** 실제 의존 역전은 `EOS Core → Subject Interface ← Math Adapter`가
> 더 정확하다 — *Core는 Math Adapter 구현체를 몰라야 한다*. 이 절은 그 문장을 네 화살표와 "등록 vs 풀"로
> 나눠 잰 결과다. 게이트 = `tests/infra/test_eos_dependency_direction.py`(22건). **정본화 ≠ 집행**: 직접
> import 축은 EOS-67 계약이 이미 강제하고(schema가 source), 지연 import·이름·문자열·pull 지점은 이 테스트가 본다.
>
> **2026-09-07 갱신(EOS-89)**: 9.2를 등록(push) 전환 **이후** 수치로 재실측했다. 9.1은 그대로다.

### 9.1 네 화살표 실측

| 화살표 | §3.8 요구 | 실측 | 집행 |
|---|---|---|---|
| Application → Core | 허용 | `api`가 `l*`를 import(layers 최상단) | 7계층 layers 계약 |
| Core → Subject Interface | 허용·권장 | CORE 소비자 4(`api.coach`·`l3.pedagogy.slot_generator`·`l3.render.adapters`·`l6.blueprint.assembly`)가 `schema.subject_adapter`/`verification_capabilities` 프로토콜을 import | — |
| Math Adapter → Subject Interface | **필수**(화살표가 위로) | `l4.subject_adapter_math`가 두 인터페이스 모듈을 import하고 적합성 증명 `_CONFORMANCE_PROOF: SubjectAdapter = MathSubjectAdapter()`(L151) 보유. 선택층 5종도 동형 증명 | `test_math_adapter_points_up_at_the_interface` |
| Subject Interface → Adapter | **금지** | 코드 import **0**(두 파일이 import하는 것은 `schema.answer_form`뿐). docstring이 구현체 이름을 2곳(`schema/subject_adapter.py` L12·L85) 언급 — 의존은 아니나 인터페이스 산문이 구현체를 안다 | EOS-67 계약 1 + 지연 import 검사 |
| Core → Adapter 구현체(이름·문자열) | **금지** | CORE 코드 **0**(docstring 제외·`composition`은 정의상 제외) | `test_core_code_never_names_an_adapter_implementation` |
| Core → Application | 금지 | CORE **0**. INFRA 운영 도구 8모듈(`ops.*` 4·`privacy.*` 3·`harness.*` 1)은 `api._crypto`·`api._auth`·`api.me` 등 헬퍼를 import — Application 쪽에 선 도구라 §3.8 대상 아님(9.2) | `test_core_never_imports_the_application` |

### 9.2 등록(push) vs 풀(pull) — **EOS-89로 등록 형태가 됐다** (2026-09-07 재실측)

| 측정 | EOS-88(전) | EOS-89(후) |
|---|---:|---:|
| `app.py`가 `app.state`에 등록하는 키 | 13 | **18** |
| 그중 **과목 능력**(`ExpressionEquivalence`·`FinalAnswerVerifier`·`AssessmentAnswerVerifier`·`ExpressionSeal`·`AnswerFormVerifier`) | **0** | **5** |
| 합성 루트에서 기본 구현을 **끌어오는(pull) CORE** 모듈 | **3** | **0** |
| 합성 루트를 소비하는 **비-CORE** 모듈(엔트리포인트) | 0 | **2** — `app` · `harness.concept_assessment_index` |
| layers 계약의 `-> composition` 면제 줄 | 2 | **0** |
| 필수층 `MathSubjectAdapter`의 프로덕션 인스턴스화 | 0 | **0** (변화 없음 — 선택층 5종만 등록했다) |

**pull 3지점이 각각 어떻게 사라졌나**

| 자리 | 전(pull) | 후(push) |
|---|---|---|
| `api.coach` | `default_final_answer_verifier()`·`default_answer_form_verifier()` 직접 호출 | `SubjectCapabilityDeps`(`Depends(_get_subject_capabilities)`) → `_resolve_completion` → `_final_answer_state`. `_get_judge_seam_deps` 선례와 동형이되 **폴백 없음**(미등록은 `AttributeError`) |
| `l3.render.adapters` | `default_expression_seal()`·`default_assessment_answer_verifier()` 폴백 | 어댑터 **생성자 주입**(`_CapabilityBackedAdapter`). 상류 = `registry.get_adapter(strategy, seal=…, assessment_verifier=…)` ← `l4.content_supply.supply(...)` ← `api.study`(app.state) |
| `l3.pedagogy.slot_generator` | `default_expression_equivalence()` 폴백 | 호출부 파라미터(`equivalence=`). 폴백 대신 **fail-loud**: `verification` 주장이 있는데 미주입이면 `LookupError` |

**호출부 4곳의 상류 실측** — acceptance ③이 물은 "상류를 갖지 못하는 곳"의 답이다.

| 호출부 | 능력이 실제로 필요한가 | 상류 |
|---|---|---|
| `l4.content_supply` (렌더 경로) | 필요 | **있다** — `api.study` → `app.state` 등록분 |
| `l3.pedagogy.review` | payload에 `verification` 주장이 있을 때만 | **프로덕션 상류 없음**(`test_zero_production_callers_governance`가 `l3/pedagogy/` 밖 소비자 0을 동결). 현 상류는 테스트뿐이며, 그래서 파라미터를 **선택**으로 두고 필요할 때 터지게 했다 |
| `l3.pedagogy.example_generator` | **불필요** — 생성 payload에 `verification` 키가 구조적으로 없다 | 없어도 된다(능력을 안 부른다) |
| `l3.pedagogy.diag_item_projector` | **불필요** — atom_probe payload도 마찬가지 | 없어도 된다 |

임시 처방의 근거: 뒤 세 곳에 능력을 **필수**로 요구하면, 쓰지도 않을 능력을 구하려고 그들이
합성 루트를 import하게 되고 pull 지점이 자리만 옮겨 되살아난다. 그렇다고 기본값 폴백을 두면
미주입이 조용히 통과한다. 그래서 **선택 인자 + 필요한 순간 `LookupError`**로 갈랐다
(`slot_generator._require_equivalence` docstring이 그 판단을 담고 있다). 이 세 모듈이 프로덕션
상류를 갖게 되는 날, 그 상류는 `api.study`처럼 `app.state` 등록분을 내려보내야 한다.

**엔트리포인트 2곳은 왜 남았나**: 합성 루트는 정의상 *프로세스가 시작되는 자리*가 소비한다.
`app`(ASGI 팩토리)과 `harness.concept_assessment_index`(렌더 성공률 측정 CLI·`main()` 보유)가
그 자리다 — CLI는 어댑터를 자기가 조립하므로 능력이 필요한데 그것을 줄 상류가 없다(자기 자신이
시작점이다). 이 2건은 "면제"가 아니라 **회계**다: `NON_CORE_COMPOSITION_CONSUMERS`가 정확한
집합 일치를 요구하므로 어느 모듈이든 조용히 늘어나면 RED이고, 열거된 모듈이 실제로
엔트리포인트인지(`main()` 보유 여부)까지 소스로 검사한다.

**⚠️ EOS-86 주의(변함없음)**: `StepChainVerifier` 팩토리도 이 등록 경로를 타야 한다. Core가
`composition.default_step_chain_verifier()`를 직접 부르면 pull 4번째 지점이 부활한다. 강제 장치는
두 개다 — `api/_subject_capability_state.SUBJECT_CAPABILITY_KEYS`(등록 키 목록)와
`test_registered_capability_keys_match_the_composition_factories`(팩토리 수 = 등록 키 수). 팩토리를
추가하고 등록을 안 하면 후자가 먼저 RED가 된다.

### 9.2-b 전이 도달 재실측 — 합성 루트 경유가 사라졌다

`scripts/analysis/eos_core_boundary_probe.py` 재실행(2026-09-07):

| 측정 | §8.1(EOS-84) | EOS-89 후 |
|---|---:|---:|
| CORE 모집단 | 266 | **267** (`api._subject_capability_state` 신설) |
| 전이 도달(CORE →…→ ADAPTER) | 14 | **2** |
| 그중 합성 루트(`composition`) 경유 | 14 / 14 | **0** |
| 잔여 누수(교체점을 막아도 닿음) | 2 | **2** (변화 없음 — `api.coach`·`api.ocr_handoff` → `l4.solution_coaching`) |
| 수학 제거 후 온전히 남는 CORE | 252 / 266 (95%) | **265 / 267 (99%)** |

**읽는 법**: §8.1의 14건은 "설계된 교체점을 지나는 정상 도달"이었다. 등록 형태에서는 그 정적
간선 자체가 없어져 도달이 **아예 계측되지 않는다** — 능력이 `app.state`를 통해 런타임에 흐르기
때문이다. 그래서 14 → 0이 됐고, 남은 2는 EOS-84가 이미 지목한 *진짜* 잔여(`l4.solution_coaching`
MIXED)로 이 태스크 범위 밖이다. 다만 **이 감소는 결합이 사라진 것이 아니라 정적 계측의 시야
밖으로 옮겨간 축을 포함한다** — 프로브 자신의 공백(§9.3 "정적 import다·`app.state` DI는 안
보인다")이 여기서 그대로 작동한다. 그 축을 보는 도구는 인벤토리 v2의 DI 다리이며, 실제로
`di_keys_bridged`가 20 → 30으로 늘어 같은 배선을 반대편에서 계측한다.

### 9.3 재현·공백

```
/root/.local/bin/pytest tests/infra/test_eos_dependency_direction.py
```

- 정적 AST 계측이다 — `getattr`·문자열 조립으로 구현체를 찾는 코드는 못 본다(현행 0건은 "내가 찾은
  방법으로 0건"이다).
- INFRA 8모듈의 `api` 헬퍼 import(`privacy.* → api._crypto/_auth`)는 §3.8 대상이 아니지만, 암호·인증
  헬퍼가 `api` 패키지에 사는 것 자체는 배치 냄새다 — 별도 판정 후보(등재 안 함).

---

## §10. Core의 과목 전용 누수 2종 — enum 멤버·필드명 (EOS-90 · 2026-09-04)

> Subject Contract v1 후보 판정(`docs/reviews/subject_contract_v1_candidate_verdicts_2026-09-04.md`)
> 중에 CORE 배정 모듈이 수학을 아는 자리 2종이 드러났고, **둘 다 §8의 프로브 v1이 놓쳤다**.
> 이 절은 그 사각과 계측 확장을 기록한다.

### 10.1 무엇을 못 봤나

| 자리 | 형태 | v1 검출 | 왜 못 봤나 |
|---|---|---|---|
| `l4.visualization_policy:47-57` `_SEATED_STYLES` | 수학 전용 표상 7종을 **enum 멤버로 열거**(`VisualizationStyle.단위원` 등) | **0** | 리터럴 스캔은 `Compare`의 *문자열*만 본다. 여기엔 문자열이 하나도 없다(`Attribute` 노드) |
| `schema.visualization:147-179` `Graph2dSpec` | `tangent_point`·`integral_region`·`show_extrema`·`number_line`을 **typed 필드로 검증** | **0** | 어휘 스캔은 문자열 *상수*만 본다. 이건 값이 아니라 **이름**이다 |

두 번째가 더 무겁다. Core의 최하위 계층 `schema`가 미적분 어휘를 필드명으로 갖고 그 필드를
**검증까지 한다**(`_validate_typed_spec`). EOS-66의 불투명 페이로드 원칙 — "Core는 `answer_kind`를
해석하지 않는다" — 과 정면으로 충돌한다. `if problem.type == "quadratic"`을 금지하면서 `tangent_point`를
필드로 검증하는 것은 같은 지식을 다른 문법으로 갖는 것이다.

### 10.2 계측 확장 — 실측·동결

프로브에 스캐너 2종을 추가했다(`scan_subject_enum_members`·`scan_math_field_names`).

| 축 | 실측 | 동결 위치 |
|---|---:|---|
| CORE의 과목 전용 enum 멤버 | **2** | `SUBJECT_ENUM_MEMBER_BASELINE` |
| CORE의 수학 필드명 | **6** | `MATH_FIELD_NAME_BASELINE` |

필드명 6건 = 위 4개 + `l3.solution_path.sympy_verified`(CORE가 sympy 검증 여부를 필드로 안다) +
`l4.misconception.catalog._TRIG`(§8.3 데이터 누수 43건의 일부). 결함 주입 8종으로 변별력을
확인했고(enum 3·필드 5), 비위반 8종은 비검출이다 — 특히 소문자 수신자(`self.tangent`)는 인스턴스
속성이지 enum 열거가 아니므로 세지 않고, `AnnAssign`이 아닌 대입은 중복 계상을 피해 제외한다.

### 10.3 정직한 공백 — 스캐너가 못 보는 것을 테스트가 고정한다

어휘 목록 기반이라 목록에 없는 과목 어휘는 **놓친다**. `_SEATED_STYLES`의 7종 중 잡는 것은 2종뿐이고
(`단위원`·`함수그래프`·`부등식영역`·`분포곡선`·`확률시뮬레이션`은 목록에 없다), 그 한계를
`test_enum_scanner_admits_what_it_cannot_see`가 명시적으로 고정한다 — 놓치는 것을 모르는 채 "0건"이라
말하지 않기 위해서다. 목록을 넓히면 그 테스트가 실패하고, 그때 기준선도 함께 넓힌다.

상환(어휘를 어댑터·데이터로 이전)은 이 태스크 범위 밖이다 — 등재는 Kiki 판정.


## §11. Core가 불투명 페이로드를 **해석**하는가 — 반증 가능한 검사 (ARCH-43 · 2026-09-06)

> **판정 기준: 작업 트리(main `a7d25f90` 위)** — 아래 수치는 이 커밋의 코드에서 실측했다.

EOS-92 교차 과목 프로브(`subject_contract_cross_probe.md` §3)가 실증한 것: Subject Contract v1의
15필드 중 13개가 임의 문자열을 받아 **필드 채움 검사는 실패 사례를 구성할 수 없다**(반증력 0).
계약 파일이 스스로 지목한 진짜 축은 *"Core 코드가 `answer_kind` 값을 읽어 분기하기 시작하는 것"*
이고, §8의 프로브도 §4의 스캔도 그것을 못 본다 — §8.2는 *리터럴이 수학 어휘인지*를, §4는 *import*를
본다. `if p.answer_kind == "physics.quantity_with_unit"`는 둘 다 통과한다.

### 11.1 위반 정의 → 주입 RED → 검사

`scripts/analysis/eos_opaque_payload_gate.py`(게이트 · exit 0/1/2)가 **CORE 배정 모듈**(§1의
`BOUNDARY_MAP` 그대로 — 새 목록 없음)에서 계약 docstring "불투명 페이로드 원칙" 절이 이름 붙인
필드(`answer`·`answer_kind`·`conditions` — 기계 파생)의 **값**을 다음 자리에 놓으면 위반으로 센다:

| 종류 | 형태 |
|---|---|
| `eq_literal` | 리터럴·명명 상수와 `==`/`!=` |
| `membership` | 어휘 집합에 `in`/`not in` |
| `substring_probe` | 값 *안*을 `in`으로 더듬기(`"=" in p.conditions`) |
| `dict_key` | 조회 키(`H[p.answer_kind]`·`H.get(p.answer_kind)`) |
| `match` | `match p.answer_kind:` |
| `str_parse` | `p.conditions.split(";")`·`.startswith(...)` |

읽기 형태 4종(속성·첨자·`.get("…")`·같은 스코프 별칭)과 값 보존 str 메서드 경유를 한 값으로 본다 —
표기를 바꿔 빠져나가지 못하게(문자열 열거가 아니라 **AST로 구성된 결과** 검사).

| 실측 | 값 |
|---|---:|
| 분모 (CORE 스캔 모듈) | **309** / 639 파일 (제외: ADAPTER 81 · INFRA 215 · MIXED 34) |
| 위반 | **1** — `l1.problem_bank.populate:363` `membership` (`kind_raw = raw.get("answer_kind")` → `kind_raw in (17종)`) |
| 기준선 | 그 1건 · 지문 `d93b2c7770a0` · 소유 `EOS-85` · 재확인 G1 2026-09-27 (`KNOWN_VIOLATIONS`) |

기준선의 정체성은 **(모듈, 종류)별 개수가 아니라 위반 하나하나의 지문**(`sha256(모듈|종류|해석 식의
ast.unparse)[:12]`)이다 — 개수 대조는 "알려진 위반을 갚으면서 같은 모듈에 새 위반을 하나 넣는" 변경이
1→1로 상쇄돼 통과한다(PR #1014 Codex P1 · 테스트 §②′가 그 시나리오를 RED로 동결). 줄 번호는 정체성이
아니다(위 코드가 밀려도 같은 지문) · 식이 바뀌면(어휘 추가 등) 지문이 바뀌어 재승인이 필요하다.

§8.2의 리터럴 비교 1건과 **같은 자리**를 다른 축으로 잡았다 — 그쪽은 어휘가 수학이라서, 이쪽은
Core가 불투명 값을 읽어서. 별칭을 추적하지 않았다면 이 스캐너는 0을 냈을 것이고, 그 0은 맹점이다.

> **상환 완료 — `EOS-85`**(2026-09-06 · 판정 기준 main `dc2e6583`). 그 한 자리가 사라져
> `KNOWN_VIOLATIONS`는 **비었다**(지문 `d93b2c7770a0` 상환). 기준선 항목의 `recheck`가
> "EOS-85 착지 시 이 항목을 비운다"였고 그대로 집행했다 — *만료 지점을 동반한 유예*가
> 실제로 회수된 사례다. 두 축이 같은 자리를 잡고 있었으므로 §8.2와 이 절이 **동시에** 0이
> 됐다. 별칭 탐지력은 실 저장소 위반이 아니라 **합성 주입**이 계속 동결한다 — 위반을 갚으면
> 탐지력이 사라지는 테스트는 상환을 벌주는 구조라, 그 의존을 끊었다.

### 11.2 집행 — `tests/infra/test_eos_opaque_payload_gate.py` (CI `infra-contracts` 잡)

실 저장소 스캔을 기준선과 지문 단위로 정확히 대조(늘면 RED · 줄면 ratchet RED)하고, 위반 6종 21개 형태를
합성 소스로 **주입해 RED**를 확인하며, 같은 패턴이 ADAPTER 배정(`l4.subject_adapter_math`·
`l3.verify_answer`)에 있으면 초록임을, CORE 0건·파싱 실패는 **exit 2**(측정 실패)임을 고정한다.
실 저장소와 합성 주입은 **같은 판정 함수**(`scan_source`·`run_gate`·`evaluate`)를 쓴다.

### 11.3 축 (b)·(c)의 처분

- **(b) Physics 스텁 실구현** — `tests/backend/schema/test_subject_adapter_physics_stub.py`. 필수 3종을
  물리 의미로 채운 hermetic 어댑터가 Protocol을 만족한다(NotImplementedError 강요 0). 드러내는 것:
  필수층은 물리로 *구현 가능*하다 · 필수층에 수학 전용 메서드가 추가되면 이 스텁이 Protocol을 **못
  만족해 RED**(REQUIRED_METHODS 상수 동결과 별개의 살아 있는 반증기). 드러내지 **못하는** 것: 의미
  왜곡 — Core 호출자가 0(`ARCH-41`)이라 왜곡이 일어날 호출 지점 자체가 없다. **부분 채택.**
- **(c) 계약 시그니처의 수학 은유 식별자** — `contract_identifiers()` + 프로브의 `_identifier_is_math`
  (어휘 단일 원천)로 클래스·메서드·인자·필드 전수 0건 동결 + `parse_latex`·`sympy_expr` 주입 RED.
  docstring 산문(EOS-92 §2-1 "치환맵")은 못 본다 — 테스트가 그 공백을 명시 고정. **부분 채택.**

### 11.4 정직한 공백

이름 기반(타입 미해결) · 별칭 한 단계·같은 스코프 · 소문자 이름과의 `==` 미계상 · `getattr`·포맷 후
파싱·런타임 프롬프트 조립 미검출 · 그리고 **필수층 호출자 0**이라 이 게이트가 잡을 위반은 아직
생길 자리가 없다(`ARCH-41`이 첫 호출자 등장을 추적). 게이트는 그 시점에 대비한 장치이지 현재
위반의 발견기가 아니다 — 그 사실을 §11.1의 1건(선택층 밖 적재기)이 예외적으로 보여 준다.

재현: `python3 scripts/analysis/eos_opaque_payload_gate.py; echo EXIT=$?` (저장소 루트 · 기대 EXIT=0).
