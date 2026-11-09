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
