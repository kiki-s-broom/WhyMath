# ARCH-52 — 전수 귀속 인벤토리의 패키지 사각 실측·폐쇄 (2026-09-25)

> **판정 기준: main `57d336537ba890e95bd1373aa7398e79808c8fe0`** (+ 이 작업 트리의 미커밋 변경). 아래 "수정 전" 열은 main 그대로의 `scripts/analysis/eos_feature_inventory_v2.py`, "수정 후" 열은 이 변경을 적용한 트리에서 실행한 결과다.

태스크: `ARCH-52-inventory-schema-attribution-blindspot`. 발견 경위는 태스크 notes(EOS-13에서 `schema/`와 `l2/`에 같은 모듈을 신설했는데 l2 쪽만 RED)를 따른다.

## 1. 결론

- 사각은 `schema` 한 곳이 아니었다. **카탈로그가 패키지나 fnmatch 패턴으로 적은 모든 자리**가 사각이었다. 실제 트리에 프로브 모듈 66개를 넣어 본 결과 **50개가 GREEN**이었다(디렉터리 프로브 42개, fnmatch 모양 이름 8개). 카탈로그 쪽에서 보면 원인 항목은 패키지 41개와 fnmatch 8개, 합계 49개다. 새 모듈이 기존 행에 조용히 흡수돼 "미귀속 모듈" 검사에 한 번도 걸리지 않았다.
- 판정: **사각을 닫았다.** 모듈 귀속은 이제 파일 모듈 단위로 명시한 항목만 인정한다. 패키지·fnmatch·`-` 제외 항목은 오류로 거부한다. 기존 모듈은 전부 같은 행에 그대로 귀속된다. 확장 전후의 장부 산출물(YAML 전문과 CSV)이 **바이트 단위로 같다**. 그래서 그랜드파더(예외 목록)가 0건이고, 닫지 않고 남긴 패키지도 0건이다.
- 닫은 뒤 같은 66개 프로브를 다시 넣으면 **66개 전부 RED**다. 주입하지 않은 대조군은 오류 0건(GREEN)이다.

## 2. 원인 (② — main 기준 라인)

`scripts/analysis/eos_feature_inventory_v2.py` @ main:

- L838–839: WM-E-801의 모듈 항목은 `"schema"`와 `"-schema.subject_adapter"`다. 파일 목록이 아니라 **패키지 이름**을 적어 두었다.
- L1041, L1047(`_resolve_modules`): fnmatch 항목은 `fnmatch.fnmatchcase(m, entry)`로, 패키지 항목은 `m.startswith(entry + ".")`로 풀린다. 둘 다 **측정하는 그 순간의** universe(`_backend_modules()`, 즉 `rglob("*.py")`)를 기준으로 펼친다. 따라서 `schema/` 아래에 파일이 새로 생기면 다음 실행에서 자동으로 `"schema"`의 구성원이 된다.
- L1704, L1712(`_measure_modules`): 펼쳐진 모듈이 전부 `module_owner[m] = spec.fid`로 WM-E-801에 등록된다.
- L1882(`_completeness_errors`): `if m not in module_owner and m not in router_modules_seen`만 검사한다. 새 모듈은 이미 `module_owner`에 들어가 있으므로 **이 검사는 그 모듈에 대해 구조적으로 RED를 낼 수 없다.**
- `"-schema.subject_adapter"` 예외는 **이미 있는** `subject_adapter` 하나를 WM-E-419에 돌려주는 장치일 뿐이다. 새 모듈을 막지는 못한다. 제외 항목이 있다고 해서 그 패밀리가 명시적으로 관리되고 있다는 뜻이 아니었다.
- `l2/`가 RED였던 이유는 l2의 행들이 전부 **파일 단위**(`"l2.bkt"` 등)로 적혀 있었기 때문이다. 같은 이유로 `l1/`·`l3/`·`l4/`·`l6/` **바로 아래**는 RED였고, 그 **하위 패키지**(`l1/atom_graph/` 등)는 GREEN이었다.

## 3. 패키지별 프로브 주입 판정표 (① · ④)

실제 저장소 트리에 `"""ARCH-52 probe"""` 한 줄짜리 모듈을 만들고 `measure()`를 실행한 뒤 파일을 지웠다. 이 실행은 `test_real_repo_population_is_complete`의 본문과 같은 호출이다. 각 프로브마다 세 가지를 단언했다: 주입이 실제로 적용됐는지(universe에 그 모듈이 있음), 제거됐는지(universe에서 빠짐), 기준선 오류가 0건인지. 결과는 66/66 적용, 66/66 제거, 기준선 오류 0건이고 끝난 뒤 `git status`에 잔존 파일은 0건이다. 대상은 백엔드의 **모든 디렉터리 58개**(루트 포함)와 fnmatch 모양 이름 8개다. 추가로 `schema/` 프로브 하나는 실제 pytest `test_real_repo_population_is_complete`로도 돌렸다. 수정 후 결과는 `미귀속 모듈: schema.arch52probe`로 RED, exit 1이다.

| 프로브 (whymath_backend 기준) | 수정 전 | 흡수한 행·항목 (수정 전) | 수정 후 |
|---|---|---|---|
| `arch52probe.py` | RED | — | RED |
| `api/arch52probe.py` | RED | — | RED |
| `db/arch52probe.py` | **GREEN** | WM-E-802 `db` | RED |
| `db/models/arch52probe.py` | **GREEN** | WM-E-802 `db` | RED |
| `harness/arch52probe.py` | RED | — | RED |
| `l1/arch52probe.py` | RED | — | RED |
| `l1/atom_graph/arch52probe.py` | **GREEN** | WM-E-101 `l1.atom_graph` | RED |
| `l1/atom_probe/arch52probe.py` | **GREEN** | WM-E-114 `l1.atom_probe` | RED |
| `l1/concept_atom_crosswalk/arch52probe.py` | **GREEN** | WM-E-103 `l1.concept_atom_crosswalk` | RED |
| `l1/concept_content/arch52probe.py` | **GREEN** | WM-E-104 `l1.concept_content` | RED |
| `l1/concept_graph/arch52probe.py` | **GREEN** | WM-E-102 `l1.concept_graph` | RED |
| `l1/concept_visual_style/arch52probe.py` | **GREEN** | WM-E-116 `l1.concept_visual_style` | RED |
| `l1/concept_visualization/arch52probe.py` | **GREEN** | WM-E-116 `l1.concept_visualization` | RED |
| `l1/curriculum/arch52probe.py` | **GREEN** | WM-E-105 `l1.curriculum` | RED |
| `l1/formula_graph/arch52probe.py` | **GREEN** | WM-E-110 `l1.formula_graph` | RED |
| `l1/misconception/arch52probe.py` | **GREEN** | WM-E-107 `l1.misconception` | RED |
| `l1/pedagogy/arch52probe.py` | **GREEN** | WM-E-108 `l1.pedagogy` | RED |
| `l1/problem_bank/arch52probe.py` | **GREEN** | WM-E-109 `l1.problem_bank` | RED |
| `l1/problem_type_graph/arch52probe.py` | **GREEN** | WM-E-113 `l1.problem_type_graph` | RED |
| `l1/rights/arch52probe.py` | **GREEN** | WM-E-115 `l1.rights` | RED |
| `l1/skill_graph/arch52probe.py` | **GREEN** | WM-E-111 `l1.skill_graph` | RED |
| `l1/standards/arch52probe.py` | **GREEN** | WM-E-106 `l1.standards` | RED |
| `l1/strategy_graph/arch52probe.py` | **GREEN** | WM-E-112 `l1.strategy_graph` | RED |
| `l2/arch52probe.py` | RED | — | RED |
| `l3/arch52probe.py` | RED | — | RED |
| `l3/cache/arch52probe.py` | **GREEN** | WM-E-303 `l3.cache` | RED |
| `l3/dsl/arch52probe.py` | **GREEN** | WM-E-307 `l3.dsl` | RED |
| `l3/equivalent/arch52probe.py` | RED | — | RED |
| `l3/pedagogy/arch52probe.py` | RED | — | RED |
| `l3/pregenerate/arch52probe.py` | **GREEN** | WM-E-306 `l3.pregenerate` | RED |
| `l3/providers/arch52probe.py` | **GREEN** | WM-E-302 `l3.providers` | RED |
| `l3/queue/arch52probe.py` | **GREEN** | WM-E-304 `l3.queue` | RED |
| `l3/render/arch52probe.py` | **GREEN** | WM-E-308 `l3.render` | RED |
| `l3/trace/arch52probe.py` | **GREEN** | WM-E-303 `l3.trace` | RED |
| `l4/arch52probe.py` | RED | — | RED |
| `l4/lthc/arch52probe.py` | **GREEN** | WM-E-403 `l4.lthc` | RED |
| `l4/misconception/arch52probe.py` | RED | — | RED |
| `l4/misconception/semantic/arch52probe.py` | **GREEN** | WM-E-413 `l4.misconception.semantic` | RED |
| `l4/pedagogy/arch52probe.py` | RED | — | RED |
| `l4/pedagogy/adaptive/arch52probe.py` | **GREEN** | WM-E-410 `l4.pedagogy.adaptive` | RED |
| `l4/polya/arch52probe.py` | **GREEN** | WM-E-401 `l4.polya` | RED |
| `l4/socratic/arch52probe.py` | **GREEN** | WM-E-402 `l4.socratic` | RED |
| `l4/speech/arch52probe.py` | **GREEN** | WM-E-359 `l4.speech` | RED |
| `l5/arch52probe.py` | RED | — | RED |
| `l5/ocr/arch52probe.py` | **GREEN** | WM-E-501 `l5.ocr` | RED |
| `l6/arch52probe.py` | RED | — | RED |
| `l6/blueprint/arch52probe.py` | **GREEN** | WM-E-603 `l6.blueprint` | RED |
| `l6/gifted/arch52probe.py` | **GREEN** | WM-E-601 `l6.gifted` | RED |
| `l6/metacognition/arch52probe.py` | **GREEN** | WM-E-601 `l6.metacognition` | RED |
| `l6/retake/arch52probe.py` | **GREEN** | WM-E-601 `l6.retake` | RED |
| `l6/school_progress/arch52probe.py` | **GREEN** | WM-E-601 `l6.school_progress` | RED |
| `l6/suneung/arch52probe.py` | **GREEN** | WM-E-602 `l6.suneung` | RED |
| `l6/thinking/arch52probe.py` | **GREEN** | WM-E-601 `l6.thinking` | RED |
| `lang/arch52probe.py` | **GREEN** | WM-E-808 `lang` | RED |
| `ops/arch52probe.py` | RED | — | RED |
| `privacy/arch52probe.py` | RED | — | RED |
| `schema/arch52probe.py` | **GREEN** | WM-E-801 `schema` | RED |
| `whs/arch52probe.py` | RED | — | RED |
| `l3/equivalent/arch52probe_skeleton_generator.py` | **GREEN** | WM-E-352 `l3.equivalent.*_skeleton_generator` | RED |
| `l3/equivalent/arch52probe_mc_generator.py` | **GREEN** | WM-E-352 `l3.equivalent.*_mc_generator` | RED |
| `l4/misconception/crosslink_arch52probe.py` | **GREEN** | WM-E-415 `l4.misconception.crosslink_*` | RED |
| `harness/problem_corpus_arch52probe.py` | **GREEN** | WM-O-909 `harness.problem_corpus_*` | RED |
| `harness/arch52probe_batch.py` | **GREEN** | WM-O-909 `harness.*_batch` | RED |
| `harness/arch52probe_eval.py` | **GREEN** | WM-O-912 `harness.*_eval` | RED |
| `harness/arch52probe_battle.py` | **GREEN** | WM-O-912 `harness.*_battle` | RED |
| `harness/arch52probe_report.py` | **GREEN** | WM-O-913 `harness.*_report` | RED |

집계: 수정 전 RED 16 · **GREEN 50**(디렉터리 프로브 42 + fnmatch 모양 8) → 수정 후 RED 66 · GREEN 0.

## 4. 판정과 폐쇄 방법 (③)

- **닫는다.** 모든 패키지·fnmatch 항목 49개를 그 시점의 구성 모듈 목록(파일 단위)으로 풀어 적었다. `-` 제외 항목 3개(`-schema.subject_adapter`·`-harness.concept_content_review_batch`·`-harness.surrogate_baseline_report`)는 풀어 쓴 목록에서 해당 모듈을 뺀 것으로 대체했다. 풀어 쓴 결과가 원래와 같다는 근거는 두 가지다. 행별 소유 모듈 집합을 JSON으로 덤프해 비교했을 때 동일했다. `to_yaml`과 `to_csv` 전문도 코드 변경 전후로 `cmp` 결과가 동일했다.
- `_entry_error`(현 L1195)는 패키지·fnmatch·제외 형태를 오류로 거부한다. `_attribute_modules`(현 L1853)는 항목이 universe에 있는 파일 모듈인지까지 확인한다. 귀속 로직을 `_measure_modules`에서 `_attribute_modules`로, 미귀속 검사를 `_completeness_errors`에서 `_unowned_modules`(현 L2049)로, 라우터 소유자 계산을 `_router_module`(현 L2044)로 분리했다. 이렇게 해 두면 파일 I/O 없이 같은 코드로 프로브를 판정할 수 있다.
- 예외 상수(닫지 않는 패키지 목록)는 **두지 않았다.** 남길 패키지가 없었기 때문이다. 예외가 필요해지면 코드를 바꿔야 하고, 그 순간 `test_family_entries_are_rejected_not_expanded`와 `test_new_module_in_any_backend_package_is_unowned`가 RED가 된다.
- 대가: WM-E-801(schema 45종)과 WM-E-802(db 59종) 같은 큰 행은 카탈로그에 모듈을 전부 나열한다. 새 모듈을 추가하는 PR은 이제 **어느 패키지에서든** 카탈로그 1줄을 함께 바꿔야 한다. 이것은 원래 l2·api 등에서 이미 요구되던 절차이며, 이번 변경으로 그 요구가 저장소 전체에 균일해졌다.

## 5. 영구 테스트와 뮤테이션 (④)

신설 테스트(`tests/infra/test_eos_feature_inventory_v2.py` §⑤): 실제 저장소에 파일을 쓰지 않는다. universe에 가짜 모듈 이름을 넣고 `measure()`와 **같은 함수**(`_attribute_modules`·`_router_module`·`_unowned_modules`)를 부른다.

- `test_new_module_in_any_backend_package_is_unowned`: 모든 디렉터리와 fnmatch 모양 8종에 프로브를 넣었을 때 전부 "미귀속 모듈"이어야 한다. 프로브 디렉터리 수 하한 40, 실재 모듈과의 이름 충돌 0, 주입 실재를 단언한다.
- `test_attribution_mirror_is_green_on_the_real_tree`: 주입 없는 GREEN 대조군이다.
- `test_probe_mirror_calls_the_same_functions_as_measure`: 위 재현 경로가 `measure()`가 실제로 부르는 함수와 같다는 전제를 AST로 동결한다.
- `test_family_entries_are_rejected_not_expanded`(5종) · `test_catalog_family_entry_turns_the_real_measure_red`: 패밀리 항목 거부를 단위 수준과 실제 `measure()` 수준에서 각각 확인한다.

뮤테이션은 순수 Python 하네스로 돌렸다. 각 치환은 대상이 1건인지 확인했고, 주입 후 파일이 원본과 다른지 단언했다. 원복은 바이트 백업으로 했고 원복 후 원본과 같은지 단언했다. 실행 대상은 위 7개 테스트와 기존 `test_real_repo_population_is_complete`·`test_unowned_module_is_detected`다.

| 뮤테이션 | 결과 | RED를 낸 테스트 |
|---|---|---|
| CONTROL(무변경) | 전건 PASS | — |
| M1 패키지 흡수 의미 부활 + WM-E-801에 `"schema"` 부활 | RED | probe·family(schema·l3.providers)·catalog_family·mirror_green·real_population(subject_adapter 중복) |
| M2 카탈로그만 `"schema"` 부활(코드는 신규) | RED | real_population·mirror_green |
| M3 미귀속 검사 무력화 | RED | probe·unowned_module_is_detected |
| M4 프로브 디렉터리 스캔 붕괴 | RED | probe(하한 단언) |
| M5 `measure`가 `_attribute_modules` 우회 | RED | mirror_calls·catalog_family |
| M7 fnmatch 흡수 부활 + WM-O-909에 `harness.problem_corpus_*` 부활 | RED | probe·family(harness.*_batch) — **real_population은 GREEN**(사각이 그대로 재현됨) |
| M7b = M7 + fnmatch 모양 프로브 8종 제거 | probe **GREEN** | family(harness.*_batch)만 RED |
| M6 fnmatch 모양 프로브 8종만 제거(코드는 신규) | **생존(전건 PASS)** | — |

M6이 생존한 것은 예상한 결과다. 현재 코드는 fnmatch 항목을 아예 거부하므로, 이름 모양 프로브가 더 잡을 대상이 없다. 이 프로브들이 필요한 경우는 M7과 M7b를 대조하면 드러난다. fnmatch 흡수가 되살아났을 때 프로브 테스트에서 그것을 잡는 것은 **이 8종뿐이다**. 기존 `test_real_repo_population_is_complete`는 M7에서 GREEN이었다.

## 6. 안 본 분기

- **클라이언트 축**: C 행은 디렉터리 단위(`mobile/lib/features/<x>`)로 귀속한다. 그 디렉터리 안에 새 파일이 생기면 같은 방식으로 흡수된다. 이 태스크의 범위는 `src/backend/whymath_backend`이므로 주입하지도 판정하지도 않았다. feature **디렉터리**가 새로 생기는 경우는 기존 검사(`미귀속 Flutter feature`)가 잡는다.
- **data_pipeline**: `pipelines=` 필드는 전수 귀속 검사 대상이 아니다(모집단 정의상 L1 행에 병기). 주입하지 않았다.
- **S 평면 라우터 모듈**: 새 엔드포인트는 엔드포인트 단위 검사가 잡고, 새 라우터 파일은 `api/` 프로브에서 RED였다(수정 전후 동일). `app.py`의 `include_router` 경로에 새 라우터를 붙이는 조합은 주입하지 않았다.
- **`__init__.py` 안의 로직**: universe가 `__init__.py`를 제외하므로 패키지 초기화 모듈에 코드가 늘어나도 귀속 검사는 반응하지 않는다(수정 전후 동일, 주입하지 않음).
- WM-E-801의 행 이름 "40종"과 실제 45종이 다르다. 기존 텍스트라서 고치지 않았다.
- 전체 백엔드 스위트는 돌리지 않았다. 백엔드 소스를 건드리지 않았고, 이 변경이 닿는 CI 잡은 infra-contracts·harness-integrity·policy-guard다.
