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
