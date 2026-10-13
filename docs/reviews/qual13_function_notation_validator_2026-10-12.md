# QUAL-13 — 위생 검증기 함수 표기 오탐 수정: 결정·검증·경위

> **판정 기준**: 브랜치 `claude/wonderful-planck-48b5ya`(PR kiki-s-broom/WhyMath#1598, 미머지) · 코드 변경 `src/backend/whymath_backend/l3/pregenerate/validator.py` · 동결 테스트 `tests/backend/l3/test_pregenerate_function_notation.py`.
> **이 문서가 `MEMORY.md`가 아닌 이유**: `MEMORY.md` 끝부분 동시 추가는 GitHub 서버 병합에서 충돌로 판정돼 이 PR이 머지 큐에서 두 번(`MERGE_CONFLICT`) 빠졌다. 결정 로그 분리(`HARN-210`)가 착지하기 전까지 이 PR은 `MEMORY.md`를 건드리지 않는다. `HARN-210` 착지 뒤 같은 내용을 결정 로그 항목으로 옮긴다.

## 결정

위생 검증기가 함수 표기 `f(1)`·`f'(2)`를 거짓 산술로 오판정해 P3-03 미분 문항 은행 재생성에서 73건이 거부됐다. 원인은 두 갈래였고 한 모듈에서 함께 고쳤다.

- **원인 ① — 산술·부등식·부등 검증기**: `f'(2) = 5`의 `'`를 "더 큰 식의 일부" 신호로 보지 않아 `(2) = 5`만 떼어 거짓 등식으로 판정했다(`_is_standalone`).
- **원인 ② — 해 주장 검증기·단계 진단**: 암묵 곱셈 파서가 `f(2)`를 `2·f`로 읽어 `f(1) = 3, f(2) = 5`를 "f=3 vs f=5/2"로 판정했다.
- **같은 뿌리의 거짓 음성**: `2x + 1 = 7 이므로 x = 5이고 f'(x) = 2x`에서 `(x) = 2x`가 만든 가짜 방정식(x=0)이 공통 해집합을 비워 진짜 슬립(x=5)의 검출을 가렸다.
- **수정**: `_follows_function_symbol`(프라임 `' ′ ’ ``을 걷어 낸 앞 글자가 영숫자(한글 제외)이거나 직전이 `}`면 함수 인수 괄호) · `_has_function_application`(한 글자 함수 기호+`(`, **인수 안에 그 글자가 있으면 곱셈**이라 `x(x+1)`·`2x(…)`는 곱셈 해석 유지) · `_is_function_notation_relation`(해 주장 검증기·`detect_step_breaks` 공용 skip). 틀리면 통과하는 보수 방향이다.

## 검증

- 수정 전 RED 26건(신규 41건 중) → 수정 후 신규 45건·기존 `test_pregenerate.py` 209건 통과. 대조군(`2 + 3 = 6`·단독 `(2) = 5`·인용 `'(2) = 5'`·`x(x+1) = 6`·`2(x+1) = 6`·`2x(1+1) = 8`·중첩 괄호 `x((2+1)x) = 9`)은 수정 뒤에도 거부된다.
- 뮤테이션 14종 전건 RED(컴파일 검사·pytest 종료 코드 1만 검출로 계상·원복 sha256 동일).
- ④ 은행: `p3_calculus1_diff_batch --check` 504건 드리프트 없음(생성기·은행 바이트 불변 — 5회차 감사 동결본이라 회피 문면을 되돌리지 않았다). 회피 표기를 원본으로 되돌린 96개 문면: **구 검증기 49건 거부 → 수정 후 0건**, 현 은행 기준선은 구·신 모두 0건.
- 로컬 CI 재현: 전체 pytest 19313 passed·커버리지 86.40% · `backend` 후속 게이트 20스텝 · `tests/infra` 3035 · `tests/harness` 2256 · `corpus_authoring` 814 passed · 위헌 심사 래칫 차단 0건(기준선 0). `ci_mirror.py run` 6잡 `not_executed: 0`·`tainted: false`.
- 미재현: `backend-migrations`(postgres 서비스 컨테이너 필요)·`docker-build`(도커 필요)는 경로 필터상 닿지만 로컬 재현 불가 — PR CI가 통과로 판정했다. `concept-reach-guard`·`data-pipeline` 계열·`mobile`·`web`은 `pregenerate` 참조 grep 0건을 근거로 재현하지 않았다("내가 찾은 방법으로 0건").

## 알려진 한계

한 글자 함수 `x(2)`처럼 인수에 그 글자가 없는 식은 곱(2x)이 아니라 함수로 보아 해 주장 검증을 건너뛴다(학생이 `x(2+1)`로 3x를 쓰는 일은 드물어 수용). `}` 꼬리는 `\frac{1}{2}(3)` 같은 곱셈도 건너뛴다(보수 방향).

## 경위 — 세션 실수와 머지 큐 이탈

- **뮤테이션 하네스 결함(자기 발견)**: 치환 문자열이 들여쓰기를 반쯤 남겨 구문 오류가 났는데 `1 error`가 "검출(RED)"처럼 보였다 — `compile()` 단언과 pytest 종료 코드 1만 검출로 계상하도록 고쳤다. 같은 하네스가 우변 함수 적용(M11)·중첩 괄호(M14) 생존 2건을 냈고 반례를 테스트에 추가해 14/14가 됐다.
- **백필 드리프트 체크 실행 위치**: `src/backend`에서 돌려 `FileNotFoundError`(CI는 그 두 스텝만 저장소 루트로 되돌린다) — 루트에서 재실행해 exit 0.
- **미러 결과 경로**: `ci_mirror.py`를 `--result`로 다른 경로에 저장해 `backlog.py done`의 미러 게이트가 결과를 못 찾고 거부 — 결과 파일을 손으로 옮기지 않고 기본 경로로 정식 재실행해 통과.
- **머지 큐 `MERGE_CONFLICT` 2회(2026-10-13 05:04Z·06:36Z)**: 로컬 `git merge`는 `.gitattributes`의 `MEMORY.md merge=union`으로 두 번 모두 "충돌 없음"으로 보였지만 GitHub 서버 병합(머지 큐)은 그 드라이버를 쓰지 않아 큐 안에서 앞선 PR의 `MEMORY.md` 추가와 부딪혔다. 사고 계열 `nondiscriminating-check` 12회차(`HARN-211` 서버 병합 모사 프로브 미착지)와 같은 형태이며, 근본 대책은 `HARN-210`(결정 로그 항목당 파일)이다. 이 PR의 대응은 `MEMORY.md` 수정을 빼고 이 문서로 옮긴 것이다.
