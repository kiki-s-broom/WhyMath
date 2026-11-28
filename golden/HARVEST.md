| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| problem_bank_middle_function_v0 10건 (LF-01~LF-10) | 나머지 190건(같은 유형 중복) | 유형 다양성 | S3 |
| `whymath_backend.db.session.get_engine` (+ `config.get_settings`의 `db_disable_pool=True` 사본으로 NullPool) | 없음 | 연결 URL을 옛 Settings(`WHYMATH_DATABASE_URL`)에서 그대로 읽기 위해. 기동은 정상이라 지시서 "막히면"(직접 `create_async_engine`) 조건에 해당하지 않음. 단 `db/__init__.py`가 ORM 모델 전체를 import해 옛 모듈 102개가 함께 로드된다(실측). NullPool은 `with` 없는 TestClient가 요청마다 새 이벤트 루프를 만들기 때문 | S4 |
| `whymath_backend.l3.providers.factory.build_cloud_provider` + `l3.router.Router.route`(결정 1개) | 지시서의 대체안 "tutor.py에 직접 HTTP 50줄"은 쓰지 않음 | 팩토리 단독 import가 옛 모듈 40개로 지시서 "하지 말 것"의 20개 기준을 넘지만, 공통 규칙 8(팩토리 경유만·직접 호출 금지)이 작업 지시보다 우선한다. `generate`가 `RoutingDecision`을 요구해 라우터 경유로 받았고, 그래서 데이터 반출 게이트가 적용된다(실측 결정 cloud_mid · EXPORT_ALLOWED) | S4 |
| (S5 채점) `whymath_backend.l3.safe_parse.safe_parse_expr`(학생 입력 파싱 단일 안전 진입점) + SymPy `nsimplify`·`simplify` 직접 사용 | `whymath_backend/l3/equivalent/canonicalize.py`(옛 동치 판정 엔진) | 파싱은 코딩 헌법 R22-03이 진입점 하나로 강제한다(`9^9^9`·eval 우회 차단 — 직접 `parse_expr`는 `tests/infra/test_cas_parse_entrypoint_governance.py`가 막는다). 비교는 계약 규칙 두 줄(number·expression)로 끝나고 정답이 정수·분수·`x`의 일차식뿐이라 옛 엔진의 다종 answer_kind 체계가 필요 없다. import 비용 옛 모듈 28개(실측) | S5 |
| (S6 Flutter) `lib/core/env.dart`의 `Env.apiUrl`(`--dart-define=API_URL=`) | `lib/core/api_client.dart`의 `dioProvider`(인증 인터셉터) · 옛 `app.dart`·`core/router.dart`(go_router) · `lib/shared/widgets/math_text.dart` | 골든 패스는 닉네임만으로 시작해 인증 인터셉터가 필요 없어 `Dio`를 직접 만든다. 진입점은 `lib/main_golden.dart`로 분리하고 화면 전환은 라우터 없이 상태(세션 유무)로 정한다. 수식은 지시서대로 `flutter_math_fork`의 `Math.tex`를 `$...$` 구간에만 직접 쓴다 | S6 |
| (S7 Flutter) 없음 — 옛 코드 import 0건. S6의 `golden_state.dart`·`golden_api.dart`(이미 골든 안) 위에 결과 화면만 더함 | 옛 `core/router.dart`(go_router) 화면 전환 | 결과 화면도 S6과 같이 라우터 없이 상태(판정 결과 유무)로 고른다. 숙련도는 서버 값만 표시하고 바뀐 양은 판정 직전·직후 서버 값의 차이다(클라이언트 재계산 없음) | S7 |
| (S8) 없음 — 코드 변경 0건(골든 코드·옛 코드 모두). 재사용: `docker-compose.demo.yml`(시연 Postgres 55432 · 볼륨 없는 일회용)을 런북 서버 블록에 그대로 씀 | 옛 `scripts/demo/run_demo.ps1`·`run_demo.sh`(alembic 116리비전 + seed + 옛 `create_app` + 데모 JWT 일괄 기동) | 골든 서버는 `golden.api:app` 하나로 뜨고 스키마는 시작 시 `create_all`로 만든다 — 데모 스크립트의 마이그레이션·시드·토큰 단계가 전부 필요 없다. LAN IP 탐지도 지시서의 `Get-NetIPAddress 192.168.*` 한 줄로 대신한다 | S8 |

## 1주차 수확 정리 (S1~S5 · S5 작성 2026-11-09)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 문항 10건 — `data/corpus/problem_bank_middle_function_v0` → LF-01~LF-10(나머지 20건은 직접 작성) | 같은 은행 나머지 190건 · 다른 문제은행 38개 | 200건이 전부 "f(k) 구하기" 한 유형이라 30문항의 유형 다양성을 못 채운다. 골든 패스는 중2 일차함수 한 단원뿐이다 | S1~S5 |
| DB 엔진 — `whymath_backend.db.session.get_engine` + `config.get_settings`(`WHYMATH_DATABASE_URL`) | Alembic 리비전 추가 · 옛 ORM 모델·저장소 계층 | 연결 설정을 옛 것 그대로 재사용한다. 표 3개는 앱 시작 시 `create_all`로 만든다(리비전은 golden/ 밖이고 infra-contracts 등재가 필요) | S1~S5 |
| 프로바이더 팩토리 — `l3.providers.factory.build_cloud_provider` + `l3.router.Router.route` | 직접 HTTP·SDK 호출 | 공통 규칙 8(LLM은 팩토리 경유만). 라우터를 거쳐 데이터 반출 게이트도 그대로 적용된다 | S1~S5 |
| 없음 | `whymath_backend/api/coach.py`(4,570줄 코치 세션 파이프라인) | 코치 세션은 정답을 받아도 문제 완료로 처리하지 않고(S4 실측 `problem_complete=false`), 인증·오개념·힌트 사다리가 얽혀 있다. 골든 패스는 `api.py`의 엔드포인트 3개로 대신한다 | S1~S5 |
| 없음 | 오개념 DB·매칭 — `whymath_backend/l1/misconception/`(10파일) · 응답의 `misconceptions` 필드 | 오류 유형 분류는 3주 범위 밖(§5). 튜터는 문항의 `hint1` 하나만 쓴다 | S1~S5 |
| 없음 | 교수학 루브릭 — `whymath_backend/harness/pedagogical_rubric.py` 등 측정·검수 하네스 | 저작·검수용 도구라 학생 경로에 필요 없다. 튜터 규칙은 `golden/tutor_prompt.md` 191자 한 장 | S1~S5 |
| 없음 | L2 학습자 모델(BKT·IRT·`next-problem` 선택) | 숙련도는 +0.10/−0.05 한 줄, 문항 순서는 고정 30개 순환이다(§5) | S1~S5 |
| 없음 | 데모 OAuth·JWT·회원가입 | 학생 식별자는 닉네임뿐(공통 규칙 9) | S1~S5 |
| 없음 — 튜터(S4)와 같은 프로바이더 팩토리·라우터(`build_cloud_provider` + `Router.route`)를 학생 LLM에도 재사용 | 옛 시뮬레이터·합성 학생 계열은 찾아 쓰지 않음(`golden/sim_student.py` 1파일로 새로 씀) | 학생 LLM도 공통 규칙 8(팩토리 경유)을 따른다. 튜터 코드(`api.py`·`tutor.py`)와는 HTTP로만 만난다 | S11 |
| (S14 튜터 프롬프트 개선) 없음 — 옛 자산 0건. `golden/tutor_prompt.md` 규칙 6에 한 문장(마지막 되묻기에서도 틀린 곳 하나를 짚고 질문 하나로 답을 묻는다)만 더함 | 오개념 카탈로그(`whymath_backend/l1/misconception/` — 부호 오개념 항목) · 교수학 루브릭(`whymath_backend/harness/pedagogical_rubric.py`)의 힌트 규칙 | 튜터가 학생이 쓴 값을 그대로 짚으면 되므로 카탈로그 조회·오개념 매칭이 필요 없다(FINDINGS「S14 제안」 · 오개념 매칭은 §5). 실제 LLM 재생으로 효과 확인: 1위 근거 5사례×5회의 마지막 되묻기가 틀린 곳을 짚은 수 4/25 → 25/25 | S14 |
| (S15 격리·회고) 없음 — 옛 코드 import 0건 추가. 측정 스크립트는 `grimp`(이미 dev 의존성)만 씀 | 옛 모듈 722개·옛 Flutter 74파일의 `/legacy` 물리 이동(이번엔 하지 않음) | Kiki 결정(2026-11-15) "보류 — 목록만 기록". 부분 이동은 패키지 이름이 바뀌어 옛 import 3,409줄 수정(§5)과 옛 테스트 965파일·CI 19잡 수정을 부른다. 목록은 아래 절에 확정 | S15 |
| (S15 결정 집행) 격리: 722모듈·74파일, 이동 없음, 삭제는 S74 — `golden/LEGACY_MANIFEST.txt` + import-linter 계약 `golden-no-legacy` + `tests/golden/test_legacy_manifest.py` | 물리 이동(`/legacy`) · 옛 코드 수정 | Kiki 결정(2026-11-15) "논리 격리". 옛 코드는 한 줄도 고치지 않고, golden에서 새 import만 막는다 | S15 |

## 3주간 미참조 모듈 (S15 · 측정 2026-11-15 · 기준 main `a9cff6ec`)

> **뜻**: golden 코드(`src/backend/golden/`·`src/mobile/lib/golden/`·`lib/main_golden.dart`)가 **직접이든 간접이든 한 번도 import하지 않는** 옛 모듈. "죽은 코드"가 아니다 — 옛 `create_app`·옛 테스트·CLI 스크립트는 여전히 쓴다. **삭제 대상이 아니다**(지시서 "하지 말 것").
> **/legacy 물리 이동: 보류 — Kiki 결정(2026-11-15 · S15 세션 질문 응답 "보류 — 목록만 기록").** **최종 결정(같은 날 Kiki): 물리 이동 없이 논리 격리** — 목록을 `golden/LEGACY_MANIFEST.txt`로 고정하고 import-linter 계약 `golden-no-legacy`로 golden의 새 import를 막는다. 삭제는 3단계 S74(GOLD-17). 근거는 아래 「이동하면 깨지는 것」. 이동은 `golden/NEXT_3WEEKS.md`에 실제 학생 검증 뒤 순서로 올렸다.

### 측정 명령

```bash
cd src/backend && python -m golden.measure_unreferenced
```

- 스크립트: `src/backend/golden/measure_unreferenced.py`(Python 3.12 · `grimp` — CI와 같은 `pip install -e ".[dev]"` 환경 · 학생 경로와 무관한 도구라 `golden.api`는 import하지 않는다 · `golden/` 루트 아래 `.py`는 CI 린트 대상이 아니라 `tests/infra/test_lint_coverage.py`가 막으므로 린트되는 이 자리에 둔다 — S11 `sim_student.py` 선례). 결과 파일은 `golden/reports_no_students/S15/`의 `unreferenced_backend.tsv`(722행 · 경로·줄 수 전수) · `referenced_backend.tsv`(122행) · `unreferenced_flutter.tsv`(74행) · `flutter_golden_imports.tsv`(8행) · `measure_summary.json` · `unreferenced_compact.md`(아래 표의 원본).
- 백엔드 "golden이 쓰는 모듈" = 아래 세 가지의 합집합이다.
  1. `grimp.build_graph("whymath_backend", "golden").find_upstream_modules("golden", as_package=True)` — 정적 import로 닿는 옛 모듈 **16개**.
  2. **보정 ① 조상 패키지**: `a.b.c`를 import하면 `a/__init__.py`·`a/b/__init__.py`도 실행되는데 grimp는 이것을 의존으로 세지 않는다. 조상 패키지와 그 조상이 import하는 모듈을 늘지 않을 때까지 더하면 **120개**(대부분 `db/__init__.py`가 ORM 모델 전체를 import해서 — S4 HARVEST 줄과 같은 현상).
  3. **보정 ② 런타임 실측**: `GOLDEN_FAKE_LLM=1`로 golden 모듈 전부를 import한 뒤 `sys.modules`의 옛 모듈 **122개**. 정적에 없고 런타임에만 있는 것은 2개(`whymath_backend.l1`·`whymath_backend.l1.rights.permission_map`), 정적에만 있는 것은 0개다.
- **보정 ③ 그래프 밖 파일**: `whymath_backend/l1/rights/`는 `__init__.py`가 없어(네임스페이스 패키지) grimp 그래프에 아예 없다(5파일). 파일 시스템으로 다시 세서 전체를 **844개**로 잡았다(grimp만 보면 839개 — S1 STATE Q7의 839와 같다). 이 5개의 사용 여부는 런타임 실측으로만 판정했다.
- Flutter: `lib/main_golden.dart`와 `lib/golden/*.dart`에서 시작해 `import`·`export`·`part`(같은 패키지 `package:korean_math_app/…`와 상대 경로)를 끝까지 따라갔다.
- 변별력 확인: 쓰는 쪽에 `db.session`·`l3.safe_parse`·`l3.providers.factory`, 안 쓰는 쪽에 `l3.equivalent.canonicalize`(S5가 버림)·`api.coach`(S1~S5가 버림)·`app`·`l1.misconception`(S14가 쓰지 않음)이 들어갔다 — HARVEST의 "가져온 것/버린 것"과 일치한다.
- 해석 범위: `importlib` 문자열 로딩·entry point는 런타임 실측(import 시점)에 잡힌 것만 들어간다. 함수 안에서 요청 처리 중에만 하는 import는 정적 그래프(1)로 잡힌다.

### 요약

| 구분 | 전체 | golden이 씀 | golden이 안 씀 |
| --- | ---: | ---: | ---: |
| 백엔드 모듈(`src/backend/whymath_backend/`) | 844개 · 316,469줄 | 122개 · 30,194줄 | **722개 · 286,275줄** |
| Flutter 소스(`src/mobile/lib/`, 생성 파일 0개) | 82개 | 옛 파일 1개(`lib/core/env.dart`) + 골든 7개 | **74개 · 10,931줄** |

- 골든 Flutter가 쓰는 외부 패키지: `dio`·`flutter`·`flutter_math_fork`·`flutter_riverpod`.

**백엔드 하위 패키지별**

| 하위 패키지 | 전체 | 씀 | 안 씀 | 안 쓰는 줄 수 |
| --- | ---: | ---: | ---: | ---: |
| `whymath_backend` | 1 | 1 | 0 | 0 |
| `whymath_backend._stdio` | 1 | 1 | 0 | 0 |
| `whymath_backend.api` | 56 | 0 | 56 | 26,724 |
| `whymath_backend.app` | 1 | 0 | 1 | 1,668 |
| `whymath_backend.composition` | 1 | 0 | 1 | 148 |
| `whymath_backend.config` | 1 | 1 | 0 | 0 |
| `whymath_backend.consent` | 1 | 0 | 1 | 61 |
| `whymath_backend.consent_grant` | 1 | 0 | 1 | 126 |
| `whymath_backend.db` | 66 | 64 | 2 | 394 |
| `whymath_backend.harness` | 163 | 0 | 163 | 80,582 |
| `whymath_backend.l1` | 98 | 2 | 96 | 21,414 |
| `whymath_backend.l2` | 41 | 0 | 41 | 14,470 |
| `whymath_backend.l3` | 166 | 18 | 148 | 73,550 |
| `whymath_backend.l4` | 100 | 0 | 100 | 23,630 |
| `whymath_backend.l5` | 10 | 0 | 10 | 1,634 |
| `whymath_backend.l6` | 18 | 0 | 18 | 3,019 |
| `whymath_backend.lang` | 2 | 0 | 2 | 275 |
| `whymath_backend.ops` | 38 | 0 | 38 | 27,618 |
| `whymath_backend.privacy` | 9 | 0 | 9 | 2,287 |
| `whymath_backend.schema` | 55 | 35 | 20 | 4,662 |
| `whymath_backend.security` | 1 | 0 | 1 | 159 |
| `whymath_backend.whs` | 14 | 0 | 14 | 3,854 |

### 목록 (경로·줄 수)

통째로 안 쓰는 디렉터리는 한 줄로 접었다. 쓰는 파일이 섞인 디렉터리만 파일 단위로 적었다. 파일 하나하나는 `unreferenced_backend.tsv`·`unreferenced_flutter.tsv`에 있다.

<!-- golden.measure_unreferenced 가 생성 — 손으로 고치지 않는다 -->

##### 백엔드 (`src/backend/whymath_backend/`) — 100줄로 접음

| 경로 | 파일 수 | 줄 수 |
| --- | ---: | ---: |
| `src/backend/whymath_backend/api/` | 56 | 26,724 |
| `src/backend/whymath_backend/app.py` | 1 | 1,668 |
| `src/backend/whymath_backend/composition.py` | 1 | 148 |
| `src/backend/whymath_backend/consent.py` | 1 | 61 |
| `src/backend/whymath_backend/consent_grant.py` | 1 | 126 |
| `src/backend/whymath_backend/db/published_edit_guard.py` | 1 | 93 |
| `src/backend/whymath_backend/db/schema_version.py` | 1 | 301 |
| `src/backend/whymath_backend/harness/` | 163 | 80,582 |
| `src/backend/whymath_backend/l1/atom_graph/` | 10 | 2,778 |
| `src/backend/whymath_backend/l1/atom_probe/` | 3 | 342 |
| `src/backend/whymath_backend/l1/concept_atom_crosswalk/` | 4 | 662 |
| `src/backend/whymath_backend/l1/concept_content/` | 6 | 912 |
| `src/backend/whymath_backend/l1/concept_graph/` | 9 | 2,009 |
| `src/backend/whymath_backend/l1/concept_visual_style/` | 2 | 160 |
| `src/backend/whymath_backend/l1/concept_visualization/` | 2 | 148 |
| `src/backend/whymath_backend/l1/curriculum/` | 4 | 884 |
| `src/backend/whymath_backend/l1/embedding_primitives.py` | 1 | 237 |
| `src/backend/whymath_backend/l1/embedding_provider.py` | 1 | 362 |
| `src/backend/whymath_backend/l1/fk_precheck.py` | 1 | 110 |
| `src/backend/whymath_backend/l1/formula_graph/` | 3 | 324 |
| `src/backend/whymath_backend/l1/misconception/` | 10 | 1,737 |
| `src/backend/whymath_backend/l1/pedagogy/` | 5 | 811 |
| `src/backend/whymath_backend/l1/problem_bank/` | 9 | 2,606 |
| `src/backend/whymath_backend/l1/problem_type_graph/` | 3 | 296 |
| `src/backend/whymath_backend/l1/rights/attribution.py` | 1 | 179 |
| `src/backend/whymath_backend/l1/rights/gateway.py` | 1 | 181 |
| `src/backend/whymath_backend/l1/rights/integration.py` | 1 | 98 |
| `src/backend/whymath_backend/l1/rights/policy_engine.py` | 1 | 265 |
| `src/backend/whymath_backend/l1/skill_graph/` | 4 | 340 |
| `src/backend/whymath_backend/l1/standards/` | 12 | 5,661 |
| `src/backend/whymath_backend/l1/strategy_graph/` | 3 | 312 |
| `src/backend/whymath_backend/l2/` | 41 | 14,470 |
| `src/backend/whymath_backend/l3/cache/` | 2 | 437 |
| `src/backend/whymath_backend/l3/cross_verify.py` | 1 | 1,186 |
| `src/backend/whymath_backend/l3/curriculum_notation_gate.py` | 1 | 682 |
| `src/backend/whymath_backend/l3/data_grade_defaults.py` | 1 | 82 |
| `src/backend/whymath_backend/l3/dsl/` | 8 | 1,302 |
| `src/backend/whymath_backend/l3/equivalent/` | 77 | 46,539 |
| `src/backend/whymath_backend/l3/escalation_defaults.py` | 1 | 43 |
| `src/backend/whymath_backend/l3/exact_value.py` | 1 | 110 |
| `src/backend/whymath_backend/l3/finite_probability.py` | 1 | 590 |
| `src/backend/whymath_backend/l3/generation_seed.py` | 1 | 160 |
| `src/backend/whymath_backend/l3/isolated_call.py` | 1 | 486 |
| `src/backend/whymath_backend/l3/multi_solution.py` | 1 | 1,329 |
| `src/backend/whymath_backend/l3/notation_coverage.py` | 1 | 827 |
| `src/backend/whymath_backend/l3/pedagogy/` | 11 | 2,864 |
| `src/backend/whymath_backend/l3/pipeline.py` | 1 | 432 |
| `src/backend/whymath_backend/l3/pregenerate/` | 6 | 1,927 |
| `src/backend/whymath_backend/l3/problem_metadata_evidence.py` | 1 | 164 |
| `src/backend/whymath_backend/l3/problem_publish_gate.py` | 1 | 935 |
| `src/backend/whymath_backend/l3/prompt_assets.py` | 1 | 236 |
| `src/backend/whymath_backend/l3/publish_gate.py` | 1 | 991 |
| `src/backend/whymath_backend/l3/queue/` | 4 | 594 |
| `src/backend/whymath_backend/l3/render/` | 6 | 1,001 |
| `src/backend/whymath_backend/l3/sequence_induction.py` | 1 | 613 |
| `src/backend/whymath_backend/l3/solution_path.py` | 1 | 267 |
| `src/backend/whymath_backend/l3/solution_path_store.py` | 1 | 121 |
| `src/backend/whymath_backend/l3/solution_set.py` | 1 | 457 |
| `src/backend/whymath_backend/l3/speech.py` | 1 | 490 |
| `src/backend/whymath_backend/l3/speech_parse.py` | 1 | 449 |
| `src/backend/whymath_backend/l3/statistical_claim.py` | 1 | 664 |
| `src/backend/whymath_backend/l3/symbolic_equivalence.py` | 1 | 433 |
| `src/backend/whymath_backend/l3/trace/` | 2 | 319 |
| `src/backend/whymath_backend/l3/verification_tier.py` | 1 | 129 |
| `src/backend/whymath_backend/l3/verifier.py` | 1 | 587 |
| `src/backend/whymath_backend/l3/verify_answer.py` | 1 | 3,471 |
| `src/backend/whymath_backend/l3/verify_answer_form.py` | 1 | 145 |
| `src/backend/whymath_backend/l3/verify_final_answer.py` | 1 | 320 |
| `src/backend/whymath_backend/l3/verify_solution.py` | 1 | 939 |
| `src/backend/whymath_backend/l3/verify_step.py` | 1 | 491 |
| `src/backend/whymath_backend/l3/visualization.py` | 1 | 338 |
| `src/backend/whymath_backend/l3/viz_eval.py` | 1 | 400 |
| `src/backend/whymath_backend/l4/` | 100 | 23,630 |
| `src/backend/whymath_backend/l5/` | 10 | 1,634 |
| `src/backend/whymath_backend/l6/` | 18 | 3,019 |
| `src/backend/whymath_backend/lang/` | 2 | 275 |
| `src/backend/whymath_backend/ops/` | 38 | 27,618 |
| `src/backend/whymath_backend/privacy/` | 9 | 2,287 |
| `src/backend/whymath_backend/schema/analytics_event.py` | 1 | 132 |
| `src/backend/whymath_backend/schema/answer_form.py` | 1 | 128 |
| `src/backend/whymath_backend/schema/assessment_evidence.py` | 1 | 378 |
| `src/backend/whymath_backend/schema/auth.py` | 1 | 81 |
| `src/backend/whymath_backend/schema/cms_access.py` | 1 | 127 |
| `src/backend/whymath_backend/schema/concept_lifecycle.py` | 1 | 101 |
| `src/backend/whymath_backend/schema/corpus_provenance.py` | 1 | 64 |
| `src/backend/whymath_backend/schema/event_data_contract.py` | 1 | 356 |
| `src/backend/whymath_backend/schema/learning_loop_contract.py` | 1 | 383 |
| `src/backend/whymath_backend/schema/mastery_contract.py` | 1 | 350 |
| `src/backend/whymath_backend/schema/pedagogy_pack.py` | 1 | 210 |
| `src/backend/whymath_backend/schema/pedagogy_strategy.py` | 1 | 263 |
| `src/backend/whymath_backend/schema/problem_metadata.py` | 1 | 335 |
| `src/backend/whymath_backend/schema/review_transition.py` | 1 | 303 |
| `src/backend/whymath_backend/schema/speech.py` | 1 | 233 |
| `src/backend/whymath_backend/schema/subject_adapter.py` | 1 | 341 |
| `src/backend/whymath_backend/schema/unit_dsl.py` | 1 | 157 |
| `src/backend/whymath_backend/schema/verification_capabilities.py` | 1 | 417 |
| `src/backend/whymath_backend/schema/version_lifecycle.py` | 1 | 167 |
| `src/backend/whymath_backend/schema/wrong_answer_signature.py` | 1 | 136 |
| `src/backend/whymath_backend/security.py` | 1 | 159 |
| `src/backend/whymath_backend/whs/` | 14 | 3,854 |

##### Flutter (`src/mobile/lib/`) — 11줄로 접음

| 경로 | 파일 수 | 줄 수 |
| --- | ---: | ---: |
| `src/mobile/lib/app.dart` | 1 | 30 |
| `src/mobile/lib/core/api_client.dart` | 1 | 73 |
| `src/mobile/lib/core/auth_interceptor.dart` | 1 | 192 |
| `src/mobile/lib/core/router.dart` | 1 | 220 |
| `src/mobile/lib/core/shell/` | 1 | 59 |
| `src/mobile/lib/core/token_refresh_api.dart` | 1 | 69 |
| `src/mobile/lib/core/token_store.dart` | 1 | 215 |
| `src/mobile/lib/features/` | 61 | 9,395 |
| `src/mobile/lib/main.dart` | 1 | 33 |
| `src/mobile/lib/shared/` | 2 | 525 |
| `src/mobile/lib/theme/` | 3 | 120 |

### 이동하면 깨지는 것 (Kiki 결정의 근거 · 실측)

| 깨지는 것 | 숫자 | 확인 방법 |
| --- | --- | --- |
| 옛 서버 진입점 | `whymath_backend.app`(`create_app`) 자체가 이동 대상 → 옛 서버가 뜨지 않는다 | 위 목록 |
| 옛 테스트 | `tests/backend` 테스트 파일 1,114개 중 **965개**가 이동 대상을 직접 import(`tests/infra` 1 · `tests/data_pipeline` 1) | 정규식 `^(from|import) whymath_backend…` 대조 |
| CI | 잡 25개 중 **19개**가 `whymath_backend`·`tests/backend`·`src/backend`·`lint-imports`·`alembic`을 참조 | `.github/workflows/ci.yml` 잡별 grep |
| import-linter | 계약 5개 중 **4개**가 옛 계층(L1~L7·EOS·데이터 접근)을 가리킨다. 남는 1개가 `옛 코드는 golden을 모른다` | `src/backend/pyproject.toml` `[tool.importlinter]` |
| 패키지 이름 | `whymath_backend`는 `__init__.py`가 있는 일반 패키지라 일부만 `legacy/`로 옮기면 모듈 이름이 바뀐다. 이동 대상 **648파일 안의 import 3,409줄**을 고쳐야 한다 = 옛 코드 수정(§5) | 정규식 집계 |
| 스크립트 | `scripts/` 아래 20파일이 `whymath_backend`를 import | grep |
| Flutter | 옛 앱 `lib/main.dart`·`lib/app.dart`·`features/`가 이동 대상 → 옛 앱 빌드와 `src/mobile/test/` 70파일 대부분이 깨진다 | 위 목록 |

- 사전 실측(2026-11-08)의 "테스트 파일 1,109개"는 이번 측정에서 `tests/backend`의 `test_*.py` **1,114개**다(3주 사이 다른 태스크가 추가 — S 세션은 `tests/backend`를 바꾸지 않았다).
- 지시서가 제안한 `legacy/README.md`는 `golden/` 바깥 새 파일이라 만들지 않았다(공통 규칙 3). 목록의 정본은 이 절이다.

## 전이 의존 절단 (S20A · 1단계 개정판 S20+1 · 2026-11-16 · 기준 main `cd560e32`)

### 경계 긋기 — 직접 import 7종에서 골든이 실제로 쓰는 이름 (복사 전에 적음)

| 옛 모듈 (쓰는 골든 파일) | 골든이 쓰는 이름 | 이 모듈 하나가 끌고 오는 옛 모듈 수(조상 패키지 포함) | 결정 | 이유 |
| --- | --- | ---: | --- | --- |
| `whymath_backend.db.session` (`store.py`) | 함수 `get_engine` 1개 | 102 | **복사해서 자른다** → `src/backend/golden/db.py` | `db/__init__.py`가 ORM 모델 전체(`db` 64 · `schema` 35)를 import한다. 골든은 엔진 하나만 쓴다 |
| `whymath_backend.config` (`store.py`) | 함수 `get_settings` → 필드 `database_url` 1개(`db_disable_pool`은 골든이 늘 True로 덮어쓴다) | 3 | **복사해서 자른다** → `src/backend/golden/settings.py` | 2,211줄 설정에서 필드 1개만 쓴다. `db.py`가 옛 `Settings`를 받지 않게 하려면 같이 잘라야 한다 |
| `whymath_backend.l3.safe_parse` (`grade.py`) | 함수 `safe_parse_expr` 1개 | 24 (LLM 경로와 겹치지 않는 것은 자기 자신 1개) | **import 유지** | 코딩 헌법 R22-03 — CAS 파싱 진입점은 이 파일 하나다. `tests/infra/test_cas_parse_entrypoint_governance.py`가 `src/backend` 전체에서 진입점 밖의 `parse_expr` 호출·import를 막으므로 복사본은 그 검사에 걸린다(허용목록은 golden 밖 · 헌법이 지시문보다 위). 지시서 제안값 ⓑ(함수 1개 복사)는 채택하지 않는다 |
| `whymath_backend.l3.models` (`tutor.py`·`sim_student.py`) | 클래스 `RoutingRequest` 1개 | 23 | **import 유지** | LLM 호출은 라우터 경유(CLAUDE.md 불변 · 공통 규칙 9) |
| `whymath_backend.l3.router` (같음) | 클래스 `Router`의 `route` 1개 | 23 | **import 유지** | 같음 |
| `whymath_backend.l3.providers.factory` (같음) | 함수 `build_cloud_provider` 1개(돌려받은 프로바이더의 `generate` 호출) | 36 | **import 유지** | 같음 |
| `whymath_backend.schema.enums` (같음) | 열거형 `LicenseType`의 `WHYMATH_GENERATED` 1개 | 18 | **import 유지** | `l3.models`가 어차피 같은 모듈을 import한다 — 골든에서만 떼어도 전이는 줄지 않는다 |

### 복사한 것 (다섯 걸음 ③ · 한 개씩 초록 확인)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| **복사: 의존 과다** — `src/backend/whymath_backend/config.py`의 `Settings.database_url` 필드 1개와 `get_settings`(읽는 규칙: 접두사 `WHYMATH_` · `.env` · 모르는 키 무시 · 한 번만 읽기) → `src/backend/golden/settings.py`(`GoldenSettings`·`get_settings`) | 옛 `Settings`의 나머지 필드 전부(2,211줄) · `db_disable_pool`(골든은 늘 풀을 쓰지 않는다) | 골든이 읽는 값이 DB 주소 하나뿐이다. 특성화 `tests/golden/characterization/test_s20a_settings.py`(환경 10가지에서 옛 설정과 같은 값) | S20A |
| **복사: 의존 과다** — `src/backend/whymath_backend/db/session.py`의 `get_engine`(NullPool 경로)·`dispose_engine` → `src/backend/golden/db.py`(`make_engine`·`get_engine`·`dispose_engine`) | `get_sessionmaker`·`get_session`(FastAPI 의존성)·풀을 쓰는 경로 | 옛 모듈 하나를 import하면 `db/__init__.py`가 ORM 전체를 불러 옛 모듈 102개가 로드된다. 특성화 `tests/golden/characterization/test_s20a_db.py`(연결 주소 10개에서 옛 엔진과 같은 모양 — 주소·드라이버·풀 종류) | S20A |
| 없음(import 유지) — `l3.safe_parse.safe_parse_expr` | 지시서 제안값 ⓑ "함수 1개 복사" | 코딩 헌법 R22-03(CAS 파싱 진입점 1곳) — 복사본은 `tests/infra/test_cas_parse_entrypoint_governance.py`에 걸린다 | S20A |
| 없음(import 유지) — `l3.models.RoutingRequest`·`l3.router.Router`·`l3.providers.factory.build_cloud_provider`·`schema.enums.LicenseType` | 프로바이더·라우터 복사 | LLM 호출은 라우터 경유(불변). 30 초과분의 처리는 Kiki 결정(게이트 `G-s20a-router-path-transitive-budget`) | S20A |

### 결과 (측정기 `python -m golden.measure_unreferenced --budget` · 2026-11-16)

| 구분 | 이전(S15 · 이 세션 재측정 동일) | 이후 | 예산 | 판정 |
| --- | ---: | ---: | ---: | --- |
| 직접 import하는 옛 모듈(서로 다른 것) | 7 | **5** | 10 | 통과 |
| 전이 — 정적 + 조상 패키지 | 120 | **37** | — | — |
| 전이 — 런타임 실측 포함 합집합(예산 판정 기준) | 122 | **40** | 30 | **미달(10 초과)** |
| 골든이 쓰는 옛 코드 줄 수 | 30,194 | 17,587 | — | — |

- 이후 직접 5개: `l3.safe_parse`(grade) · `l3.models`·`l3.router`·`l3.providers.factory`·`schema.enums`(tutor·sim_student). 빠진 2개: `config`·`db.session`(store).
- 이후 전이 40개의 패키지별: `l3` 18 · `schema` 17 · `l1` 2 · `whymath_backend`(루트) 1 · `_stdio` 1 · `config` 1. `db`는 64 → 0.
- 남은 40개를 못 끊은 이유: 골든은 `l3`에서 이름 5개만 쓰지만 `l3/__init__.py`가 `models`·`router`를, `l3/providers/__init__.py`가 프로바이더 4종 전부를, `schema/__init__.py`가 스키마 16모듈을 일괄 import한다. 옛 코드를 고치지 않고는 골든 쪽에서 떼어 낼 수 없다.
- 30 안으로 가는 길(Kiki 결정): 프로바이더 팩토리 경로(`providers/` 10모듈 + `interfaces`·`provider_jurisdiction`)를 골든으로 복사하면 정적 37 → 24(런타임 포함 약 27)가 된다(grimp 계산 · 미실행). 라우터(`Router.route`)는 그대로 경유한다. 전체 목록 `golden/reports_phase1/S20A/referenced_backend.tsv`.
- 동결: `tests/golden/test_import_budget.py`(직접 ≤ 10 · 전이는 더 늘지 못함(상한 40) · 목표 30은 strict xfail · 끊은 `config`·`db`가 되돌아오면 RED).

### 2일째 — 프로바이더 경로 복사 (Kiki 결정 2026-11-17: 선택지 B · 게이트 `G-s20a-router-path-transitive-budget`)

**경계 긋기**(복사 전에 적음). 계산 결과 옛 코드를 고치지 않는 한 바닥은 정적 24(런타임 포함 약 27)다 — 헌법이 강제하는 `l3.safe_parse`를 import하는 순간 `l3/__init__`이 라우터·모델·스키마를 함께 부른다. 줄일 수 있는 것은 `l3.providers` 패키지 13모듈뿐이고, 그 패키지의 모듈을 하나라도 import하면 `providers/__init__`이 프로바이더 4종을 전부 부르므로 **패키지 안의 것은 하나도 import하지 않는다**.

| 옛 위치 | 가져올 이름 | 골든 위치 | 이 복사본이 계속 import하는 옛 모듈(전부 바닥 안 또는 +1) |
| --- | --- | --- | --- |
| `l3/providers/_response_fields.py` | `read_response_model_id` | `src/backend/golden/llm/_response_fields.py` | 없음 |
| `l3/providers/seat_failure.py` | `SeatHttpError`·`SeatNotConfiguredError`(+ 같은 파일의 분류 함수) | `golden/llm/seat_failure.py` | `l3.models`(바닥) |
| `l3/providers/_openai_compat.py` | `ChatTransport`·`HttpxChatTransport`·`extract_text`·`extract_usage`·재시도 카운터 | `golden/llm/_openai_compat.py` | `l3.models`(바닥) |
| `l3/providers/openrouter.py` | `OpenRouterProvider`(+ 관할 표·`build_provider_block`) | `golden/llm/openrouter.py` | `config`·`l3.models`·`l3.router._as_cost_tier`(바닥) · `l3.provider_jurisdiction`(+1) |
| `l3/providers/factory.py` | `build_cloud_provider`의 **openrouter 분기 1개** | `golden/llm/factory.py` | `config`(바닥) — 다른 좌석이면 조용히 바꾸지 않고 `ValueError` |

- 계속 옛 것을 쓰는 것: 라우터 판정 `Router.route`(LLM 호출은 라우터 경유 — 불변) · 설정 `config.Settings`(모델 핀·허용 공급사·키 이름이 옛 것과 같이 움직인다). 공통 규칙 9의 "`build_cloud_provider()` 경유" 문구만 Kiki 결정으로 골든 팩토리로 바뀐다.
- 버리는 것: deepseek·anthropic·ollama·composite 프로바이더, 좌석 강등 계수(`LocalDegradeCounter` 등 — 골든은 강등 조립을 쓰지 않는다. 같은 파일이라 함께 복사되지만 쓰지 않는다).

**복사 결과(2일째)**

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| **복사: 의존 과다** — `l3/providers/_response_fields.py`·`seat_failure.py`·`_openai_compat.py`·`openrouter.py` 4파일 통째(본문 무변경 · import 줄만 골든 복사본으로) → `src/backend/golden/llm/` · `factory.py`는 openrouter 분기 1개만 새로 씀 | deepseek·anthropic·ollama·composite 프로바이더 · 옛 팩토리의 다른 두 분기 | 옛 `providers/__init__`이 프로바이더 4종을 한꺼번에 불러 13모듈이 따라온다. 특성화 `tests/golden/characterization/test_s20a_llm_compat.py`(응답 파싱 10 · Retry-After 10 · 전송 재시도 10 · 실패 분류 10)·`test_s20a_llm_openrouter.py`(생성 10 · 상태 점검 4 · 팩토리). 본문은 원본과 대조해 import 순서 외 동일 | S20A |

| 구분 | S15 | 1일째 | **2일째** | 예산 |
| --- | ---: | ---: | ---: | ---: |
| 직접 import 옛 모듈 | 7 | 5 | **6** | 10 |
| 전이(런타임 포함 · 판정 기준) | 122 | 40 | **28** | 30 |
| 골든이 쓰는 옛 코드 줄 | 30,194 | 17,587 | **14,248** | — |

- 2일째 직접 6: `l3.safe_parse`(grade) · `l3.models`·`l3.router`·`schema.enums`(tutor·sim_student) · `config`·`l3.provider_jurisdiction`(golden/llm). `l3.providers` 패키지는 0.
- 남은 28은 바닥(약 27)에서 1 위다 — `l3.provider_jurisdiction` 1개. 여유 2. 다음 옛 자산(T1·T2·T3)은 import하면 거의 확실히 예산을 넘으므로 **복사**가 기본이다.
- 공통 규칙 9의 "튜터 LLM = `build_cloud_provider()` + `Router.route`"는 Kiki 결정(2026-11-17 선택지 B)으로 "`golden.llm.factory.build_cloud_provider()` + `Router.route`"가 된다. 라우터 판정은 그대로 옛 것을 거친다.

### 위험 제거 (GOLD-20 · Kiki 지시 2026-11-17)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 옛 `l3/providers/composite.CompositeProvider._guard_cloud_jurisdiction`의 감싸개 3줄(관할 읽기·opt-in 읽기·차단 오류) → `src/backend/golden/llm/gate.py`. 판정 함수 `l3.provider_jurisdiction.jurisdiction_judgment`는 **import 유지**(이미 전이 안 · 비용 0) | 옛 기본값 "관할 선언 없음 = US"(골든은 차단 · fail-closed) · LOCAL 강등(골든은 대체 문장으로 이어 간다) | 골든 튜터·시뮬레이터가 S4부터 관할 게이트를 건너뛰고 있었다. 특성화 `tests/golden/characterization/test_s20a_llm_gate.py`(옛 메서드와 10가지 판정 동일 · 차단 시 호출 0회) | S20A 후속 |
| 없음 — 동기화 검사 `src/backend/golden/llm/sync.py`(`python -m golden.llm.sync`)·`tests/golden/test_llm_copy_sync.py` 신설 | — | 옛 프로바이더 원본의 **코드**(주석 제외)가 바뀌면 골든 복사본과 구문 트리가 달라져 RED. 주석·import 순서만 바뀐 경우는 통과 | S20A 후속 |

### 학생 답 클라우드 송신 — Kiki 명시 허용 (GOLD-22 · 2026-11-17)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음 — 결정 기록만(`src/backend/golden/tutor.py` `_routing_request` docstring) | 선택지 ①(학생 답을 USER_GENERATED로 선언 → 라우터 LOCAL → 로컬 튜터 전환) | Kiki 결정 2026-11-17 선택지 ②: 골든 튜터가 학생 답을 포함한 프롬프트를 OpenRouter로 보내는 것을 명시 허용. 동작 변경 없음. 전제 4개(닉네임·세션 ID·정답 미포함 · 허용 공급사 기본값 deepinfra = 미국·수집 거부·보존 0 · 관할 게이트 · 실학생 전 보호자 동의서 반영)가 바뀌면 다시 묻는다 | GOLD-22 |

### RS 입고 준비 — 특성화 테스트 (RS-X2 · 2026-11-19)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 가져온 것 = 없음(특성화 테스트만) — `tests/golden/characterization/test_rs_misconception_engine.py`(옛 `l4/misconception` diagnose·hypothesis·intervene 입력 10개 고정) | 버린 것 = 없음 | 이유 = RS 입고 준비(수확 대기열 2순위) | 세션 = RS-X2 |
| 가져온 것 = 없음(특성화 테스트만) — `tests/golden/characterization/test_rs_final_answer.py`(옛 `l3/verify_final_answer`·`l3/symbolic_equivalence` 입력 10개 고정) | 버린 것 = 없음 | 이유 = RS 입고 준비(수확 대기열 1순위) | 세션 = RS-X1 |

### RS 입고 준비 — 수확 대기열 3순위 특성화 테스트 (RS-X3 · 2026-11-19)

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(특성화 테스트만 — `tests/golden/characterization/test_rs_polya_socratic.py`) | 없음 | RS 입고 준비 | RS-X3 |

## 슬롯 T1 경계 (S21 · 1단계 · 2026-11-20 · 기준 main `6ebc76e9` · 인용 F-01)

**T1 경계: 함수 2개** — 옛 `src/backend/whymath_backend/harness/pedagogical_rubric.py`(152줄)에서 아래 둘만 가져올 대상이다. 다섯 걸음 ①(경계 긋기)이며, 특성화 테스트(②)보다 먼저 적었다.

| 옛 함수 (파일 경로 · 이름) | 지금 하는 일 | 함께 따라오는 것(같은 파일 안 · 함수가 직접 씀) | 일차함수에 쓰는 항목(5개 이내) |
| --- | --- | --- | --- |
| `whymath_backend/harness/pedagogical_rubric.py` · `detect_answer_leakage(response, answer) -> LeakageVerdict` | 튜터 문장에 정답 값이 나오는지 3상태(`leaked`·`clean`·`undecidable`)로 판정. NFKC·소문자·LaTeX 명령·구조 문자(`$ \ { } ( ) 공백 ,`) 제거 뒤 비교 | 열거형 `LeakageVerdict` · `_normalize` · 상수 `_MIN_DECIDABLE_LEN`(=2)·`_AMBIGUOUS_TOKENS`·`_LATEX_COMMANDS`·`_STRUCTURAL_CHARS`·`_NUMERIC` | ① 정답 유출 3상태 ② 수치 정답 단어 경계(`-12`가 `-120`에 걸리지 않음) ③ 정규화 뒤 1글자 정답은 판정 유보(`undecidable`) |
| `whymath_backend/harness/pedagogical_rubric.py` · `score_tutoring_response(response, *, answer) -> RubricScore` | ①의 판정 + 발문 신호(물음표·발문어 13개) 유무 → `passed`(= 유출 아님 AND 발문 있음) · 근거 문자열 2개 | pydantic 모델 `RubricScore`(필드 5개) · `_has_socratic_prompt` · 상수 `_SOCRATIC_MARKERS` | ④ 발문 신호(질문으로 끝나는가) ⑤ 통과 = 유출 아님 AND 발문 있음 |

- **가져오지 않는 것**: 이 파일 밖은 아무것도 없다(이 두 함수는 표준 라이브러리 `re`·`unicodedata`·`enum`과 `pydantic`만 쓴다 — 옛 모듈 의존 0개). `_AMBIGUOUS_TOKENS`의 참·거짓·yes·no 같은 낱말은 일차함수 30문항에 쓰이지 않지만 함수 동작의 일부라 떼어 내지 않는다(옛 자산 리팩토링은 §6 금지).
- **되묻기 루브릭 v0(C1~C5)는 코드로 옮기지 않는다** — `golden/reports_no_students/S9/되묻기_루브릭.md`는 S23·S25의 사람 판정 기준으로 남긴다(LLM 판정기는 §6). 위 두 함수가 결정론으로 잴 수 있는 것은 C3(정답 비노출)과 C2(질문 하나)의 일부뿐이고, F-01의 본체인 C5(틀린 곳 겨냥)는 재지 못한다.
- **③(복사/import)에 대한 사실 — S22 판단용**: 이 파일은 `golden/LEGACY_MANIFEST.txt` 158행에 있다 → import-linter 계약 `golden-no-legacy`가 `golden` 패키지의 import를 막는다(CLAUDE.md 골든 규칙 "새 import 금지"). 또 이 모듈을 import하면 `harness/__init__.py`가 평가·DB 모듈을 함께 불러 **옛 모듈 220개**가 로드된다(2026-11-20 이 세션 실측 · `sys.modules` 세기) — 전이 예산 30을 넘는다. 따라서 공통 규칙 8의 "의존 3개 이하면 import"보다 매니페스트·예산이 앞서 **복사**가 된다. 결정은 S22가 적는다.
- **특성화(②)**: `tests/golden/characterization/test_t1_rubric.py` — 골든 패스 로그의 실제 튜터 문장 10개(유출 3 · 판정 불가 2 · 깨끗함 5)에 대한 지금 출력을 고정. 같은 입력 100회 → 같은 출력(결정성 통과 → "버림: 비결정적" 아님).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(경계 긋기와 특성화 테스트만 — 다섯 걸음 ①②) · 경계 = `harness/pedagogical_rubric.py`의 `detect_answer_leakage`·`score_tutoring_response` 함수 2개 | 되묻기 루브릭 v0 C1~C5의 코드화(사람 판정 기준으로 둔다) | T1 설계 · 복사/import·연결은 S22 | S21 |

### 슬롯 T1 import·연결 (S22 · 2026-11-20 · 기준 main `4009dad0` · 인용 F-01)

**T1 import: 함수 2개 · 의존 0개(사본 기준 · 원본 import 시 옛 모듈 219개) · 복사.** 다섯 걸음 ③④.

- 복사 대상: S21 경계 그대로 — `detect_answer_leakage`·`score_tutoring_response`와 같은 파일 안 열거형·모델·도우미 2개·상수 6개 → `src/backend/golden/eval/rubric_copy.py`. 원본의 `from __future__` 아래 본문이 바이트 단위로 같다(원 모듈 설명문만 사본 설명으로 바꿈).
- import 비용(S22 실측 · Python 3.13 · `python -X importtime -c "import whymath_backend.harness.pedagogical_rubric"`): 옛 모듈 줄 233개 · `sys.modules`에 새로 들어온 옛 모듈 219개 · 누적 약 3.9초(콜드) / 1.1초(같은 프로세스 재측정). 사본은 표준 라이브러리 + pydantic만 쓴다(옛 모듈 0개).
- 연결(④): `golden/api.py` `answer()`의 GP-4 되묻기 직후, `GOLDEN_T1_RUBRIC=1`일 때만 `golden.eval.evaluate_tutor_reply`를 불러 `golden.eval_log(turn_id, verdict_json, created_at)`에 기록만 한다. 응답은 바꾸지 않는다. 기본 끔.
- 특성화(②)는 원본·사본 두 대상에 같은 10쌍을 parametrize해 둘 다 초록이다(`tests/golden/characterization/test_t1_rubric.py`).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 복사: 의존 과다 — `harness/pedagogical_rubric.py`의 함수 2개(+같은 파일 안 의존) → `src/backend/golden/eval/rubric_copy.py` · 평가기 `golden/eval/rubric.py`(`evaluate_tutor_reply` · `RubricVerdict` · 유출 출처 `leak_origin` 칸 추가) · 새 표 `golden.eval_log` · 플래그 `GOLDEN_T1_RUBRIC`(기본 0) | 원본 import(매니페스트 계약 `golden-no-legacy` 위반 · 전이 예산 30 초과) · 되묻기 루브릭 v0 C1~C5 코드화 · 응답 차단/수정(S23 몫) | 두 함수의 의존은 3개 이하지만 원본 모듈을 부르는 순간 `harness/__init__`가 옛 모듈 219개를 끌고 온다 — 공통 규칙 8의 "3개 이하면 import"보다 매니페스트·예산이 앞선다(S21 판단 그대로) | S22 |

### 학생 시뮬레이터 — 로컬 Ollama 제공자 (S18 · 2026-11-20)

경계 긋기(복사 전에 적음): `src/backend/whymath_backend/l3/providers/ollama.py`의 `FixedModelOllamaProvider`(`__init__`·`generate`·`_get_client`·`jurisdiction`)와 그 도우미 6개(`_OllamaClient`·`_extract_text`·`_coerce_token_count`·`_read_field`·`_extract_usage`·`_build_default_client`).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 복사: 의존 과다 — `FixedModelOllamaProvider` 생성 경로 + 도우미 6개 → `src/backend/golden/sim/ollama_client.py`(동작 그대로 · import 출처 하나만 `golden.llm._response_fields`로) · 특성화 `tests/golden/characterization/test_s18_ollama_client.py`(입력 10개 + 클라우드 결정 거부 2 + 관할 1) | `OllamaProvider.generate`의 `resolve_model` 경로 · `check_status`·`OllamaStatus`·`ModelAvailability` · 이미지·JSON 스키마 인자 · `_running_loop_or_none`(루프 밖 분기 — RS-G3 조용한 값 게이트에 걸리고, 여기선 비동기 안에서만 부른다) | 지시서는 import를 기본으로 했지만(공통 규칙 9) 옛 모듈은 `l3/providers/__init__.py`를 거쳐 프로바이더 4종을 함께 부른다 — S20A가 끊은 패키지라 import하면 `test_import_budget.py`(전이 28/30 · 끊은 패키지 재유입 금지)가 RED. 모델 ID 지정은 옛 `FixedModelOllamaProvider`가 이미 받으므로 "모델 지정 불가"가 아니라 "의존 과다"다. 라우터 결정(`Router.route` · LOCAL 확인)은 옛 것을 그대로 거친다 | S18 |

### 시뮬레이터 러너 — M1 정답 유출 판정 (S19 · 2026-11-20 · 인용 F-00)

경계 긋기(복사 전에 적음): `src/backend/whymath_backend/harness/pedagogical_rubric.py`의 `detect_answer_leakage` **함수 1개**와 그것이 직접 쓰는 `LeakageVerdict`·`_normalize`·상수 4개(`_MIN_DECIDABLE_LEN`·`_AMBIGUOUS_TOKENS`·`_LATEX_COMMANDS`·`_STRUCTURAL_CHARS`·`_NUMERIC`). `score_tutoring_response`는 가져오지 않는다(T1 S22 몫).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 복사: 새 import 금지 목록 — `detect_answer_leakage` + 직접 쓰는 열거형·정규화·상수 → `src/backend/golden/sim/metrics.py`(동작 그대로 · 측정용) · 옛 함수와 나란히 부르는 대조 `tests/golden/test_sim_metrics.py::test_leak_copy_matches_old_function`(입력 18개 · 세 상태 모두) | `score_tutoring_response`·`RubricScore`·`_SOCRATIC_MARKERS`(발문 신호 — S22가 T1 슬롯으로 가져올 것) | 지시서 S19는 "import해 쓴다"였지만 그 모듈은 `golden/LEGACY_MANIFEST.txt` 158행 → import-linter 계약 `golden-no-legacy`가 막는다(CLAUDE.md 골든 규칙이 지시문보다 우선) · import하면 `harness/__init__.py`가 옛 모듈 220개를 부른다(S21 실측 · 전이 예산 30 초과). **GP-4 연결이 아니다** — 러너가 jsonl을 채점할 때만 쓴다. S22가 같은 함수를 `golden/eval/`로 가져오면 metrics.py가 그쪽을 import하도록 하나로 합친다(LATER) | S19 |

## 슬롯 T2 경계 (S26 · 1단계 · 2026-11-24 · 기준 main `3df80cd1` · 인용 F-05)

**T2 경계: 함수 1개 + 매칭 로직 없음** — 다섯 걸음 ①(경계 긋기)이며, 특성화 테스트(②)보다 먼저 적었다.

| 옛 함수 (파일 경로 · 이름) | 지금 하는 일 | 함께 따라오는 것 | 일차함수에 쓰는 항목 |
| --- | --- | --- | --- |
| `whymath_backend/l1/misconception/catalog_loader.py` · `load_misconceptions(session, collection_json, *, engine, settings, store, overwrite_cms_edits, conflicts) -> int` | 코퍼스 Collection(dict 또는 파일)의 `misconceptions` 행마다 `schema.MisconceptionCatalog`로 검증(`_misconception_from_row` · 칸 이름 바꿈 없음 · `extra=forbid`)한 뒤 저장소 `populate`로 DB에 멱등 upsert, 적재 행 수를 돌려준다 | `_as_collection`·`_misconception_from_row`(같은 파일) · `schema/misconception_catalog.py`의 `MisconceptionCatalog`(pydantic · 칸 18개) · 저장소를 넣지 않으면 `MisconceptionCatalogStore`(sync 엔진 · DB) | ① 행 검증(필수 `mis_id` · 모르는 칸 거부) ② 행 순서 보존 ③ 반환 = 검증된 행 수 |

- **매칭 로직 없음.** 지시서가 든 후보 둘을 읽었다.
  - `wrong_answer_signature_table.py`는 오답 서명 규칙표(`data/corpus/wrong_answer_signatures_v1/rules.yaml`) 로더다. 규칙 10개가 모두 미분 문항용(`ask` = `derivative_at` 2 · `extremum_value` 2 · `extremum_point`·`extremum_any_point`·`extremum_count`·`monomial_params`·`one_sided_difference`·`differentiable_yes_no` 각 1)이고, 일차함수 오개념 ID(M0034~M0037·M0409·M0567~M0569)와 부호 3건(M0001·M0002·M0548)은 하나도 없다.
  - `resolve.py`는 오개념의 성취기준·개념 연결을 푸는 함수라 답을 보지 않는다.
  - 그래서 **T2는 로더만 가져오고, 매칭(틀린 답 → 오개념 ID)은 S27이 주입기 표(`golden/sim/errors.py`의 `MISCONCEPTION_RULES`)를 거꾸로 써서 50줄로 새로 쓴다**(지시서 할 일 2의 "없으면" 문장 그대로).
- **③(복사/import)에 대한 사실 — S27 판단용.**
  - 이 파일은 `golden/LEGACY_MANIFEST.txt` 277행에 있다 → import-linter 계약 `golden-no-legacy`가 `golden` 패키지의 import를 막는다.
  - import하면 `config`·`db.models`·`l1.concept_graph.embedding`을 함께 불러 **옛 모듈 114개**가 로드된다(2026-11-24 이 세션 실측 · `sys.modules` 세기). 전이 예산 30을 넘는다.
  - 골든이 실제로 필요한 것은 DB 적재가 아니라 "행 검증" ①②뿐이다. 따라서 S27은 import가 아니라 **복사**(`_misconception_from_row` + `MisconceptionCatalog` 모델)이거나, 이미 검증된 `golden/data/misconceptions_lf.json`을 그대로 읽는 쪽이 된다. 결정은 S27이 적는다.
- **추출(할 일 3):** `golden/data/misconceptions_lf.json` **11건**이다. 일차함수분 8건과 선행 부호 3건이고, S17 주입기 표와 같은 11건이다.
  - 칸: `mis_id` · `statement`(코퍼스 `canonical_statement`) · `student_wrong_thinking` · `distractor_rule` · `op_code` · `standard_code` · `source`.
  - `op_code`는 주입기 규칙 순서의 목록이고, 빈 목록이 2건이다(M0409·M0567 — 함수 판별 문항이 30문항에 없다).
  - 계획서 15~25건에 못 미치지만 채우지 않았다(LLM 생성 금지).
- **특성화(②):** `tests/golden/characterization/test_t2_misconception.py`.
  - 옛 로더를 옛 자리에서 가짜 저장소로 부른다. 입력은 ID 10개, 출력은 행 10개(핵심 칸 7개)를 고정한다.
  - 같은 입력 100회 → 같은 출력이다(결정성 통과 → "버림: 비결정적" 아님).
  - 골든 파일 11건의 글이 옛 로더 출력과 같은지도 대조한다.
- **errors.py(할 일 5):** S17이 파일 안 딕셔너리로 두었던 임시 표를 `misconceptions_lf.json`에서 읽게 바꿨다(`load_misconception_table`).
  - OP_01 오개념의 계산 단계 변형(`mul_neg`·`sub_neg`·`sub_neg_neg`)은 틀린 답을 만드는 규칙이라 주입기에 남겼다(`SIGN_VARIANTS`).
  - 옛 표와 새 표는 `LF_MISCONCEPTIONS`·`SIGN_MISCONCEPTIONS`·`ALL_MISCONCEPTIONS`·`MISCONCEPTION_RULES`·`INJECTABLE_OPS`·`OP_RULES`·`ALL_INPUTS` 7개가 모두 같았다(순서 포함). 커밋된 S17 `injection_table.csv`와도 글자 단위로 같다.

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(경계 긋기·추출·특성화 테스트만 — 다섯 걸음 ①②) · 경계 = `l1/misconception/catalog_loader.py`의 `load_misconceptions` 1개 · 자료 = `golden/data/misconceptions_lf.json` 11건 | 매칭 로직(옛 코드에 일차함수용이 없음 — S27이 새로 씀) · 오개념 DB 843건 전체 적재·그래프 탐색·디스트랙터 생성(지시서 "하지 말 것") | T2 설계 · 복사/import·연결은 S27 | S26 |

### 슬롯 T2 import·연결 (S27 · 2026-11-24 · 기준 main `33b0419e` · 인용 F-05)

- **로더:** import도 복사도 하지 않았다(다섯 걸음 ③).
  - S26이 경계로 정한 옛 `catalog_loader.load_misconceptions`는 DB 적재기다. 골든이 필요한 것은 "검증된 행 11건"뿐이고, 그것은 S26이 `golden/data/misconceptions_lf.json`으로 이미 커밋했다(특성화 테스트가 옛 로더 출력과 글을 대조한다).
  - 옛 모듈은 LEGACY_MANIFEST 277행에 있고, import하면 옛 모듈 114개가 딸려 온다. 복사하면 쓰지 않는 적재 코드가 골든에 생긴다. 그래서 둘 다 하지 않았다.
- **매칭:** 옛 코드에 일차함수용 매칭이 없어(S26) 지시서 할 일 1의 ②로 새로 썼다 — `src/backend/golden/eval/misconception.py`의 `match_misconception`(본문 약 50줄).
  - 주입기가 30문항 × 오개념 11건에 대해 만드는 틀린 답 70개를 `golden/data/misconception_answers_lf.json`에 미리 계산해 둔다(`python -m golden.sim.errors --answers-json …` · 커밋본과 지금 주입기가 같은지는 테스트가 대조).
  - 학생 답을 채점기 규칙(`grade.is_correct`)으로 비교한다.
  - 학생 응답 경로가 시뮬레이터 패키지(`golden.sim` · 시드를 읽는 모듈이 있음)를 import하지 않게 표는 파일로만 받는다.
- **연결(④):** `api.py`에 붙였다. 오답일 때 `GOLDEN_T2_MISCONCEPTION=1`이면 기록한다 — 되묻기 턴과 3턴을 다 쓴 마지막 오답 판정이 대상이다.
  - 기록 자리는 `golden.eval_log`의 그 턴 행이다. 칸은 `t2_matcher`·`t2_misconception_id`이고, None도 기록한다.
  - 턴 표에는 열을 더하지 않았다. 응답은 바꾸지 않는다.
  - T1과 같은 턴에 함께 쓰이도록 `store.record_eval`을 "행이 있으면 JSON 합치기"로 바꿨다.
  - 실패 처리는 좁은 `except (SQLAlchemyError, OSError, ValueError, KeyError)`이고, 경고 로그에 예외 타입명을 남긴다. 넓은 `except`는 허용 목록과 Kiki 승인이 필요해 쓰지 않았다.
  - T1의 넓은 `except`(승인분)가 줄 이동으로 `api.py:190 → 200`이 되어 `tests/golden/rescue/silent_failure_allow.txt`의 줄 번호만 고쳤다(문구·승인 그대로).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(옛 코드 import 0 · 복사 0) · 새로 씀: `golden/eval/misconception.py`(`match_misconception`·`misconception_enabled`) + 표 `golden/data/misconception_answers_lf.json`(70행 · 주입기 S17 규칙의 역방향) · 연결 `api.py` · 기록 `golden.eval_log`(`t2_misconception_id`) · 플래그 `GOLDEN_T2_MISCONCEPTION`(기본 0) | 옛 `catalog_loader.load_misconceptions`(DB 적재기 — 필요한 행은 S26 파일에 이미 있음 · LEGACY_MANIFEST · 옛 모듈 114개) · 튜터에 매칭 결과 보내기(S28 몫) · 오개념 DB 843건 적재 | 옛 코드에 일차함수 매칭이 없어 지시서 ②(주입기 규칙 역적용)로 씀 · 답만으로 가를 수 없는 오개념 쌍 3개는 앞 ID가 나온다(S27 보고) | S27 |

### 슬롯 T2 적용 (S28 · 2026-11-24 · 기준 main `ce489827` · 인용 F-05)

- **옛 자산:** 새로 가져온 것이 없다(다섯 걸음 ④ 연결의 연장 — 옛 코드 import 0 · 복사 0).
- **연결(④ GP-4):** `api.py` 되묻기 경로에서 `GOLDEN_T2_MISCONCEPTION=1`이면 튜터를 부르기 **전에** 매칭하고, 매칭이 있으면 그 오개념 한 줄 설명을 `tutor.build_user_prompt`의 학생 입력 바로 뒤에 지시서 문장 그대로 넣는다. 시스템 프롬프트(`golden/tutor_prompt.md`)는 그대로다.
  - 한 줄 설명은 오개념 파일에 새로 둔 `prompt_description`(11행 · 숫자 없음)이다. 코퍼스 서술(`statement`·`student_wrong_thinking`)에는 예시 숫자(`3-(-5)=3-5=-2`·`앞은 4`)가 있어, 같은 숫자가 정답인 문항에서 튜터 문장으로 새지 않게 따로 썼다.
  - eval_log에 `t2_prompt_hint`(그 턴 프롬프트에 한 줄을 넣었는가)를 더했다 — 플래그 1 실행에서 주입이 실제로 몇 번 일어났는지 숫자로 보려고.
  - 매칭 실패(표 파일 오류)면 튜터에 아무것도 넣지 않고 응답은 그대로다(좁은 except · 타입명 로그). 기록 실패(DB·연결)도 응답은 그대로다.
  - 줄 이동으로 승인분 넓은 `except` 두 줄의 번호만 고쳤다: `tutor.py:128 → 153` · `api.py:200 → 206`(문구·승인 그대로).
- **측정:** 오개념 검출률을 `golden/sim/metrics.py`(`misconception_detection`)에 더하고, 집계·전후 표 도구 `golden/sim/t2_summary.py`를 새로 썼다(T1 `t1_summary.py`와 같은 모양 · 진입점 선언 `test_orphan_gate.py`).
  - 주입된 오개념은 실행 기록의 `forced_answer`를 주입기에 다시 물어 찾는다(세션 기록 모양은 S19 계약 그대로 · 새 키 없음).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(옛 코드 import 0 · 복사 0) · 새로 씀: 튜터 프롬프트 한 줄(`tutor.T2_HINT_TEMPLATE`) · 설명·검출 낱말(`misconceptions_lf.json`의 `prompt_description`·`keywords`) · 검출률(`metrics.misconception_detection`) · 집계 `golden/sim/t2_summary.py` | 코퍼스 서술을 그대로 튜터에 넣기(예시 숫자 유출 위험) · 매칭 임계값 완화(지시서 "하지 말 것") · 시스템 프롬프트 수정(개정 1회 한도는 S23이 씀) | T2 다섯 걸음 ④를 GP-4 프롬프트에 붙임 · 검출률은 Kiki 머신 720 전후로 잰다(런북) | S28 |

## 슬롯 T3 경계 (S31 · 1단계 · 2026-11-25 · 기준 main `18413980` · 인용 F-06)

**T3 경계: 클래스 1개 + 함수 1개** — 옛 `src/backend/whymath_backend/l2/bkt.py`(179줄)에서 아래 둘만 가져올 대상이다. 다섯 걸음 ①(경계 긋기)이며, 특성화 테스트(②)보다 먼저 적었다.

| 옛 이름 (파일 경로 · 이름) | 지금 하는 일 | 함께 따라오는 것(같은 파일 안 · 직접 씀) | 일차함수에 쓰는 항목 |
| --- | --- | --- | --- |
| `whymath_backend/l2/bkt.py` · `BktParameters` | BKT 파라미터 묶음(불변 · 전부 0~1). `p_slip + p_guess < 1`(비퇴화)을 어기면 `ValueError` | 기본값 상수 5개(`_DEFAULT_P_INIT` 0.3 · `_DEFAULT_P_TRANSIT` 0.1 · `_DEFAULT_P_SLIP` 0.1 · `_DEFAULT_P_GUESS` 0.2 · `_DEFAULT_P_FORGET` 0.0) · 검증 `_check_non_degenerate` | 파라미터 4개 `p_init`·`p_transit`·`p_slip`·`p_guess` |
| `whymath_backend/l2/bkt.py` · `update_mastery(prior, correct, params) -> float` | 관측 1회(정/오답) → 베이지안 사후 → 학습 전이 → 새 숙련도 | `posterior_mastery`(분모 0이면 prior 그대로) · `apply_learning` | 정답·오답 한 번마다 숙련도 갱신(지금의 +0.10/−0.05 자리) |

- **가져오지 않는 것**: 망각 `apply_forgetting`·`BktModel.apply_forgetting`(지시서 S31 · 계획서 §6) · `BktModel` 클래스 · `probability_correct`(다음 문항 정답 확률 — 적응형 문항 선택에 쓰이므로 §6). `BktParameters`의 `p_forget` 필드는 클래스의 일부라 떼어 내지 않지만 쓰지 않는다(기본 0).
- **파라미터 4개(일차함수용 제안값 · S31은 값만 적는다 · S32가 S24·S29 정답률로 보정 가능):**

| 파일의 필드 | 뜻 | 옛 기본값 | 일차함수 제안값 |
| --- | --- | ---: | ---: |
| `p_init` | 초기 숙련도 P(L0) | 0.3 | 0.2 |
| `p_transit` | 학습률 P(T) — 학습 기회 한 번에 미숙달→숙달 | 0.1 | 0.3 |
| `p_guess` | 추측률 P(G) — 미숙달인데 맞힘 | 0.2 | 0.2 |
| `p_slip` | 실수율 P(S) — 숙달했는데 틀림 | 0.1 | 0.1 |

  제안값은 비퇴화 검증을 통과한다(0.1 + 0.2 < 1 · 특성화 테스트가 이 묶음으로 4쌍을 고정).
- **③(복사/import)에 대한 사실 — S32 판단용**: 이 파일은 `golden/LEGACY_MANIFEST.txt` 333행에 있다 → import-linter 계약 `golden-no-legacy`가 `golden` 패키지의 import를 막는다. 또 `whymath_backend.l2.bkt`를 import하면 `l2/__init__.py`를 거쳐 **옛 모듈 141개**가 로드된다(2026-11-25 이 세션 실측 · `sys.modules` 세기 · `config`·`db.models` 등) — 전이 예산 30을 넘는다. 두 대상의 실제 의존은 표준 라이브러리 `math` + `pydantic`뿐이다. 따라서 T1(S22)과 같은 이유로 **복사**가 된다. 결정은 S32가 적는다.
- **특성화(②)**: `tests/golden/characterization/test_t3_bkt.py` — (prior, correct, params) 10쌍(옛 기본값 4 · 제안값 4 · 분모 0 분기 2)의 지금 출력 고정 · 같은 입력 100회 → 같은 출력(결정성 통과 → "버림: 비결정적" 아님) · `p_slip=0.5, p_guess=0.5`는 `ValueError`(비퇴화 거부).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(경계 긋기와 특성화 테스트만 — 다섯 걸음 ①②) · 경계 = `l2/bkt.py`의 `BktParameters` + `update_mastery`(+ 같은 파일 안 `posterior_mastery`·`apply_learning`) | 망각(`apply_forgetting`·`BktModel.apply_forgetting`) · `BktModel` · `probability_correct` | T3 설계 · 망각·적응형 문항 선택은 §6 금지 · 복사/import·연결은 S32 | S31 |

## 슬롯 T3 복사·연결 (S32 · 1단계 · 2026-11-25 · 기준 main `5ca51174` · 인용 F-06)

- **③ 복사**: S31 경계 그대로 `BktParameters` + `update_mastery`(+ `posterior_mastery`·`apply_learning`)를 `src/backend/golden/mastery/bkt.py`로 옮겼다. 계산식·기본값·오류 문구는 원본과 같다. 골든 파라미터(S31 제안값 0.2·0.3·0.1·0.2)는 `GOLDEN_BKT_PARAMETERS`이고, 지시서 모양의 `update(prior, correct) -> float`가 이 값을 쓴다.
  - 사본은 `pydantic`·표준 라이브러리만 쓴다. `import golden.mastery`가 새로 부르는 옛 모듈은 **0개**다(이 세션 실측 · `sys.modules` 세기 · 원본은 141개).
  - S31 경계와 다른 점 하나: 원본의 `p_forget` 필드는 "떼어 내지 않지만 쓰지 않는다"였다. 사본은 복사라 남길 이유가 없어 **뺐다**(망각 §6 금지). 특성화 테스트가 사본의 필드를 정확히 4개로 고정한다.
- **② 원본·사본 대조**: `tests/golden/characterization/test_t3_bkt.py`가 S31의 10쌍을 원본·사본 두 대상에 parametrize한다(S22 선례). 두 대상이 같은 값을 낸다.
- **④ 연결(GP-6)**: `golden/api.py`의 `_graded` → `_shadow_mastery`. 판정 1건마다 새 표 `golden.mastery_shadow`에 simple·bkt 2행을 쌓는다(`students`에는 열을 더하지 않는다). 플래그 `GOLDEN_MASTERY_ENGINE`(기본 simple · 정확히 `bkt`일 때만 bkt)은 응답 `mastery`에 어느 값을 실을지만 정한다. `students.mastery`는 늘 simple(+0.10/−0.05)이다.

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 복사: 의존 과다 — `l2/bkt.py`의 `BktParameters`(`p_forget` 뺌) + `update_mastery`·`posterior_mastery`·`apply_learning` → `src/backend/golden/mastery/bkt.py` · 플래그 `src/backend/golden/mastery/__init__.py`(`GOLDEN_MASTERY_ENGINE`) · 새 표 `golden.mastery_shadow` | 원본 import(매니페스트 333행 · 계약 `golden-no-legacy` · 전이 141개로 예산 30 초과) · 망각(`apply_forgetting`·`p_forget`) · `BktModel` · `probability_correct` · 화면에 bkt 값 표시 | 두 대상의 의존은 `math`·`pydantic`뿐이지만 원본 모듈을 부르면 `l2/__init__`가 옛 모듈 141개를 끌고 온다(S31 실측) — T1(S22)과 같은 판단 | S32 |

## 미참조 옛 모듈 재측정 (S35 · 1단계 · 2026-11-26 · 기준 main `bb456fdf` · 인용 F-00)

- **방법:** 골든 패스 S15와 같은 측정기 `python -m golden.measure_unreferenced`(grimp로 `golden` 상류 ∖ 전체 + 런타임 `sys.modules`)를 다시 돌렸다. 결과 파일은 `golden/reports_phase1/S35/measure/`(`measure_summary.json` · `referenced_backend.tsv` · `unreferenced_backend.tsv` · `unreferenced_flutter.tsv`)이고, S15 결과는 `golden/reports_no_students/S15/`다.
- **숫자:** 백엔드 전체 844모듈은 S15와 같다. golden이 쓰는 옛 모듈은 122 → **28**, 미참조는 722 → **816**(302,221줄)이다. Flutter 미도달 74파일은 S15와 같은 목록이다.
- **S15 목록과의 차이(세 칸):**
  - 새로 import된 옛 모듈(T1·T2·T3 자산): **0개**. 세 슬롯 모두 import가 아니라 `src/backend/golden/` 아래로 복사했다(T1 `eval/rubric_copy.py` · T2 오개념 카탈로그 로더(`_misconception_from_row` 등 · S27) · T3 `mastery/bkt.py`). 그래서 슬롯 자산의 원본 모듈은 S15에서 이미 미참조였고 지금도 미참조다.
  - S20A 복사로 **빠진** 모듈: **94개**(15,946줄) — `whymath_backend.db` 64 · `schema` 18 · `l3` 12. golden이 `golden/db.py` 등 복사본을 쓰게 되면서 상류에서 떨어져 나갔다(「전이 의존 절단 (S20A)」).
  - 여전히 미참조인 모듈: S15의 722개 전부. 지금 쓰는 28개는 `config` · `l1`(권한 지도 런타임) · `l3`의 라우터·모델·`safe_parse` · `schema` 일부다.
- **LEGACY_MANIFEST 갱신:** `golden/LEGACY_MANIFEST.txt`에 추가분 94모듈을 따로 묶어 더했다(머리에 측정 기준 `bb456fdf` · 2026-11-26 · 백엔드 816모듈). import-linter 계약 `golden-no-legacy`(`src/backend/pyproject.toml`)에도 같은 94모듈을 더했고(그래프 밖 모듈 0개), `tests/golden/test_legacy_manifest.py`의 개수를 816으로 바꿨다. `lint-imports` 7계약 KEPT · 그 테스트 7개 통과.
- 옛 모듈은 지우지 않았다. `/legacy` 물리 이동은 Kiki 결정(S15와 같다).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음(측정만) | 없음 — 미참조 816모듈은 격리 목록에 올렸을 뿐 지우지 않았다(삭제는 3단계 S74) | 지시서 S35 할 일 4 | S35 |

## 반복 슬롯 T2R 경계 (S26R · 1단계 반복 회차 · 2026-11-26 · 기준 main `a07a018d` · 인용 F-02)

- **무엇을 다루나:** 채점 입력에 앞말(`f(0)은 …`)·꼬리(`…이에요?`·`…같은식으로 바뀌겠죠?`)가 붙어 맞는 식·값이 오답 처리되는 것(`F-02` · FINDINGS_v2 2위). 고정 입력 표 `golden/data/grade_prefix_tail_lf.json`(43행 = 맞는 입력 11문장(반복 포함 13) · 오답 20 · 지금도 정답 대조군 11 · 모호 1).
- **옛 자산 후보와 판정(다섯 걸음 ①):**
  - `whymath_backend/l3/verify_final_answer.py`의 `verify_final_answer`(+ `_strip_answer_noise`·`_last_rhs`) — **버림: 쓸모 없음(측정)**. 고정 입력 표에서 맞는 입력 11문장을 하나도 `correct`로 받지 않는다(11개 모두 `unverifiable`). 대조군 11개 중에서도 `correct`는 1개이고 `incorrect`가 2개다(`f(5)=-3(5)+3=-15+3=-12`·`f(-3) = -3 + 4` · 원인은 확인하지 않았다). 지금 골든 채점기보다 거짓 오답이 많다. 또 `LEGACY_MANIFEST.txt`에 있어 새 import가 금지다. 근거는 `tests/golden/characterization/test_t2r_grade.py`가 고정한다.
  - `whymath_backend/l3/safe_parse.py`의 `safe_parse_expr` — 이미 `golden/grade.py`가 쓰는 파서다. 앞말·꼬리를 떼는 함수가 아니라 이 슬롯의 자산이 아니다.
  - `whymath_backend/schema/answer_form.py`(`expected_form_of`·`strict_expected_form_of`) — 기대 답 **형식** 분류뿐이다. 입력에서 답 조각을 고르지 않는다.
  - `whymath_backend/l3/notation_coverage.py`의 `extract_math_glyphs` — 수식 기호 **개수**를 센다. 답 조각을 돌려주지 않는다.
- **결론: 옛 자산 없음 — golden 안에 새로 쓴다**(1회차 S27 매칭 함수 선례). S27R은 `src/backend/golden/` 안에서 "숫자가 든 마지막 수식 조각" 규칙(FINDINGS 「판정 오류」의 다시 채점 방법)을 플래그 `GOLDEN_T2R_GRADE` 뒤에 쓴다.
- **특성화(다섯 걸음 ②):** 옛 자산이 없어 지금 `golden.grade.is_correct`의 출력을 고정 입력 43행 전부에 대해 고정했다(대조군 11개만 True · 나머지 32개 False). 플래그 0에서 S27R 뒤에도 이 테스트가 그대로 초록이어야 한다.
- **S27R이 알아야 할 어려운 칸:** `6(2)-8=-4요?`(LF-03)는 대입식 `6(2)-8`이 정답 4와 같지만 학생이 쓴 끝값은 `-4`다 — 마지막 조각 규칙이면 오답(옳다). `f(3)=-8 같은식으로 계산되면 8이 아니겠죠?`는 맞는 값과 부정된 틀린 값이 함께 있어 모호로 뒀다. 질문 꼴 4문장(`…넣어요?`·`…하면 뭔가요?`)은 제출로 볼지 판정자마다 다르다(S29 4절).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음 — golden 안에 새로 쓴다(S27R) | `whymath_backend/l3/verify_final_answer.py::verify_final_answer` | 버림: 쓸모 없음(측정) — 맞는 입력 0/11 correct · 대조군 거짓 오답 2 · LEGACY_MANIFEST(새 import 금지) | S26R |

## 반복 슬롯 T2R 연결 (S27R · 1단계 반복 회차 · 2026-11-26 · 인용 F-02)

- **③ 복사/import:** 옛 자산 없음(S26R 경계) — golden 안에 새로 썼다. `src/backend/golden/grade_tail.py`(`last_math_fragment` · `t2r_grade_enabled` · 플래그 `GOLDEN_T2R_GRADE`). 표준 라이브러리만 쓴다. 옛 모듈 import 0개.
- **④ 연결(GP-5):** `src/backend/golden/grade.py`의 `is_correct`. 원래 입력이 **파싱에 실패했을 때만**, 플래그가 `1`이면 마지막 수식 조각으로 한 번 더 채점한다. 원래 입력이 읽히면 정답이든 오답이든 그 판정을 그대로 쓴다. 넓은 `except`는 새로 만들지 않았다 — 원래 있던 한 줄(허용 목록 · Kiki 승인 2026-11-18) 안에서 시도를 차례로 돈다. 허용 목록은 옮겨진 줄 번호(148 → 167)만 고쳤다.
- **실측:** 고정 입력 43행 — 플래그 1에서 맞는 입력 11/11(반복 포함 13/13) 정답 · 오답 20행 뒤집힘 0 · 대조군 11 그대로. 가짜 720 기록의 서로 다른 학생 입력 661개 — 플래그 0↔1 판정 차이 0. 처음 판은 P7 붙여넣기(500자) 속 `x=0`이 LF-06 정답 0과 맞아 1건이 뒤집혔다 → 공백을 지우고 100자를 넘는 입력은 조각을 고르지 않게 했다(지금 채점기의 `MAX_INPUT_LEN`과 같은 값).

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음 — golden 안에 새로 씀(`grade_tail.py` 61줄) | — | S26R 경계 "옛 자산 없음" 그대로 | S27R |

## 반복 슬롯 T2R 판정·되돌림 (S30R · 1단계 반복 회차 · 2026-11-27 · 기준 main `578a47a9` · 인용 F-02)

- **판정:** 효과 없음(잠정 · AI 대체 · S28R 조건 M3 미달 · FINDINGS 「T2R 판정 (S30R)」).
- **되돌림(1회차 S30 선례):**
  - `src/backend/golden/grade.py`를 S27R 이전 판(`2bdf049e^`)으로 되돌렸다(바이트 동일).
  - `src/backend/golden/grade_tail.py`·`tests/golden/test_t2r_grade.py`를 지웠다. 연결이 없으면 쓰는 곳이 없다.
  - 허용 목록 줄 번호를 167 → 148로 되돌렸다. 같은 줄(Kiki 승인 2026-11-18)의 위치다.
- **남긴 것:** 고정 입력 표 `golden/data/grade_prefix_tail_lf.json` · 특성화 테스트 `tests/golden/characterization/test_t2r_grade.py`(S26R 판 + "플래그 1이어도 출력이 같다" 43칸).
- 보고 폴더의 S28R·S29R 추출기(`.txt`)는 `golden.grade_tail`을 불러 S28R 실행 당시 코드에서만 돈다. 두 런북 모두 실행 코드를 먼저 검사하므로(S29R `SAME_CODE_AS_S28R_RUN` · S28R `HAS_T2R`), 이제 main에서 다시 돌리면 실행 전에 거부된다. 다시 재려면 커밋 `71297e2c`를 고정해서 돌린다.

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| 없음 | `grade_tail.py`(S27R이 새로 씀 · 옛 자산 아님) | 효과 없음 — 연결 되돌림 | S30R |

## 반복 슬롯 T3R 경계 (S31R · 1단계 반복 회차 · 2026-11-27 · 기준 main `b77b9837` · 판정 확정 2026-11-28 · 기준 main `bc69b117` · 인용 F-07)

GP-4 튜터 응답에서 정답 노출을 잡는 옛 함수 — 함수 이름 단위다(지시서 S31R 할 일 3). 1회차 T1이 복사한 `detect_answer_leakage`(`src/backend/golden/eval/rubric_copy.py`)와 M1 규칙(`golden.sim.metrics.detect_answer_leakage` — 같은 규칙)은 측정 도구라 이 슬롯의 옛 자산으로 세지 않는다.

| 후보 | 하는 일 | 지금 M1 규칙과 다른 점 | 의존 | 판정(S31R 시점) |
| --- | --- | --- | --- | --- |
| `whymath_backend/l4/hint_content/gates.py::check_answer_leakage` | 두 축. 글자 축은 `harness/pedagogical_rubric.detect_answer_leakage`(= M1 규칙)이고, 값 축은 본문의 닫힌 산술식 중 계산하면 정답이 되는 것을 찾는다 | 값 축이 새로 더하는 부분이다. M1이 유보(undecidable)하는 1글자 정답에서도 `6*2-8`(정답 4) 같은 식을 잡는다 | `Hint`·`GateContext`(힌트 콘텐츠 모델)를 받는다. 값 축 능력은 `l4/subject_adapter_math.py::MathAnswerValueExposure`가 주입한다 | **버림(함수 자체)** — 힌트 모델용이라 GP-4에 바로 맞지 않는다. 글자 축은 M1 규칙과 같아 ⓒ(부호 반대 오답 되짚기)를 그대로 유출로 센다. 가져올 것은 아래 값 축 함수들이다 |
| `whymath_backend/l3/verify_solution.py::scan_value_exposure` (+ 같은 파일 `arithmetic_fragments` · `same_value` · `_value_targets` · `ValueExposureResult`) | 값 축 본체. 3상태(exposed · clean · undecidable)를 낸다 | 맨 숫자(`-12`)는 식이 아니라 보지 않는다. 그 부분은 글자 축 몫이다 | `verify_solution`을 import하면 whymath 모듈 56개가 따라온다(클라우드 실측). 직접 ≤10 · 전이 ≤30 예산(S20A)을 넘으므로 **import 불가 → 복사**(다섯 걸음 ③) | **가져옴(복사 · S32R)** — 특성화 테스트 고정(입력 10). ⓐ 합성 2줄을 모두 잡고(M1이 유보한 1글자 정답 `6*2-8` 포함) ⓒ 실제 3줄은 하나도 잡지 않는다. 단 ⓑ 실제 4줄 중 학생 식을 되짚은 1줄(`5*3`)도 잡으므로 **값 축만으로 막지 않는다** — 아래 둘째 점 |
| `whymath_backend/l3/pedagogy/analogy_checker.py::_detect_answer_leak` | 정답 문자열이 본문에 그대로 들어 있는가(부분 문자열) | 단어 경계가 없다. 정답 `1`이 `15`에 걸린다(클라우드 실측). 짧은 정답의 유보도 없다 | 표준 라이브러리만 | **버림 — 오탐(측정 확정)** — ⓒ 실제 3줄 모두 True(`11`이 `-11`에 걸린다) · ⓑ도 전부 True라 ⓐ와 가르지 못한다 |

- 세 후보 모두 `golden/LEGACY_MANIFEST.txt`에 있다(`l4/hint_content/gates.py` · `l3/verify_solution.py` · `l3/pedagogy/analogy_checker.py`). 골든 코드는 새로 import하지 않는다. 테스트만 옛 자리에서 부른다.
- 특성화 테스트 `tests/golden/characterization/test_t3r_leak.py`(입력 10 · 출력 30 + 경계 사실 1 · 2026-11-28). 입력은 S31R 출처 표의 실제 튜터 문장(ⓑ 4 · ⓒ 3)과 합성(ⓐ 2 · 대조군 1)이다. **실제 ⓐ는 0건**이라 ⓐ는 합성이다(`golden/DECISIONS_AUTO.md` 2026-11-28 S31R).
- S32R에 넘기는 경계: "ⓐ인가"는 옛 함수가 아니라 **학생 이력**으로 가른다 — 튜터 문장의 정답 값(M1 규칙 또는 값 축)이 그 턴까지 학생 입력에 이미 있었으면 ⓑ·ⓒ(되짚기)라 막지 않는다. S31R 실제 29턴은 전부 이 조건이 참이었다(추출기 `이 턴까지 학생이 정답 값을 낸 적=True`).
| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| `l3/verify_solution.py::scan_value_exposure` (+ 같은 파일 4개 · 복사는 S32R) | `l4/hint_content/gates.py::check_answer_leakage` · `l3/pedagogy/analogy_checker.py::_detect_answer_leak` | 가져옴: ⓐ 합성 2/2 · ⓒ 실제 0/3(측정). 버림: 힌트 모델용·글자 축이 M1과 같음(코드 읽기) · 부분 문자열 오탐 ⓒ 3/3(측정) · 모두 LEGACY_MANIFEST(새 import 금지) | S31R |

- 찾은 방법(범위): `leak`·`leakage`·`reveal`이 이름에 든 함수를 `whymath_backend/l3`·`l4`·`harness`에서 grep으로 찾았고, 지시서가 이름을 댄 두 후보와 값 축 함수를 직접 읽었다. 이 범위 밖에 쓸 만한 함수가 있는지는 모른다.

## 반복 슬롯 T3R 연결 (S32R · 1단계 반복 회차 · 2026-11-28 · 기준 main `a86ab459` · 인용 F-07)

- **다섯 걸음 ③ 복사: 의존 과다** — `whymath_backend/l3/verify_solution.py`의 값 축 함수를 `src/backend/golden/eval/value_exposure.py`로 복사했다. 옛 모듈을 import하면 whymath 모듈 56개가 따라오고, 그 모듈은 `golden/LEGACY_MANIFEST.txt`에 있다(새 import 금지).
  - 가져온 함수: `scan_value_exposure` · `arithmetic_fragments` · `_value_targets` · `split_top_level` · `_closed_value`, 그리고 이 함수들이 쓰는 `_name_kind` · `_balanced` · `_is_single_variable`.
  - 자른 의존 2개:
    - `same_value`: 옛 판은 정본 채점기 `verify_final_answer`(옛 모듈 다수)에 맡겼다. 사본은 같은 안전 파서 `l3.safe_parse.safe_sympify`로 수를 비교한다. 이 파서는 골든 채점기가 이미 쓰므로 직접 import 예산은 그대로다.
    - `_value_targets`의 LaTeX 평문화: 골든 30문항의 정답은 모두 평문이다. 정답에 역슬래시(`\`)가 있으면 판정 불가로 둔다.
  - 출력이 같은지 확인했다: 30문항 정답 × 본문·힌트·S31R 튜터 문장 등 2,040쌍 이상에서 옛 판과 결과 4칸이 모두 같다. 고정 테스트는 `tests/golden/test_t3r_guard.py::test_value_copy_matches_legacy_on_problem_texts`이고, 클라우드 사전 점검에서는 630쌍 모두 같았다.
- **다섯 걸음 ④ 연결**: `src/backend/golden/tutor.py`의 튜터 응답 직후다. `GOLDEN_T3R_LEAK_GUARD=1`일 때만 켜진다. 유출 판정은 `src/backend/golden/eval/leak_guard.py`가 한다.
  - 정답이 드러났는지는 두 축으로 본다: 글자 축(M1 규칙 + 부호 경계)과 값 축(위 사본).
  - 학생이 이미 낸 값을 되짚은 것인지는 이번 문제의 학생 입력(앞 턴 포함)으로 가른다.
  - 학생이 낸 적 없는 정답이 드러났을 때(ⓐ)만 막는다. 같은 입력으로 1회 다시 만들고, 그래도 걸리면 고정 문장으로 바꾼다.
  - 기록은 `golden.eval_log`의 `t3r_*` 칸에 남긴다.

| 가져온 것 | 버린 것 | 이유 | 세션 |
| --- | --- | --- | --- |
| `l3/verify_solution.py::scan_value_exposure` 외 7함수 → `golden/eval/value_exposure.py` | `same_value`의 `verify_final_answer` 위임 · LaTeX 평문화(`latex_to_plain`) | 복사: 의존 과다(옛 모듈 56개 · LEGACY_MANIFEST). 대신 `safe_sympify` 수 비교를 넣었다. 골든 정답은 평문이다. 옛 판과 같은 출력을 테스트로 고정했다 | S32R |
