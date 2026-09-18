# Week 1 Gate 판정 — 계획서 300 Phase 2 §4

**판정 기준: main `d99a482807e0bf31d8cc3d43097ac279f95881ac`**
**판정자**: claude (구현 세션과 분리 — 이 세션은 판정 하네스만 만들고 기능을 구현하지 않았다)
**태스크**: `EOS-106` · **PR**: [#1194](https://github.com/kiki-s-broom/WhyMath/pull/1194)
**라이브 증거**: CI run `35313156085` 잡 `105499238372` (`backend — 마이그레이션·통합 (실 PG)` · pgvector/pgvector:pg16 · `WHYMATH_RUN_INTEGRATION=1`)

---

## 1. 판정

> **번호 교차 참조 (2026-09-18 개명)**: 이 문서가 `EOS-109`로 부르는 후속 태스크는 **처음 `EOS-108`로
> 등재**됐다. 다른 세션이 같은 번호를 `EOS-108-mastery-engine-v1-single-write-path`로 쓰고 있어 내 쪽을
> `EOS-109-oauth-created-learner-profile-read`로 옮겼다. 그러므로 **이 PR의 커밋 메시지와 코멘트에 적힌
> `EOS-108`은 전부 지금의 `EOS-109`를 가리킨다**(그것들은 되돌려 쓸 수 없다). 충돌은 누구의 잘못도 아닌
> **24초 경합**이다 — 내 add가 `06:28:11Z`, 상대 claim이 `06:28:35Z`이고, 그 24초 동안 서로의 번호가
> 상대에게 보이지 않았다(내 add는 push 전까지 안 보이고, 상대 claim은 내 add 시점에 아직 없었다).
> 재발방지대책은 별건으로 등재했다.


> **통과 (PASS)** — 단, 인접 결함 1건(`EOS-109`)을 함께 보고한다.

완료 판정 문면은 *"1사이클(사용자 생성→진단→개념 선택→문제 풀이→오답→mastery 변경→다음 문제 추천)이
DB 직접 수정 없이 완주"* 다. **완주했다.**

「실측」 CI run `35315225642` 잡 `105505403023` (`backend — 마이그레이션·통합 (실 PG)`) pytest 스텝:

> `= 322 passed, 13 skipped, 10332 deselected, 1 xfailed, 2 warnings in 293.44s (0:04:53) =` · 스텝 **exit 0**
> `XFAIL api/test_week1_gate_closed_loop.py::test_oauth_created_learner_can_read_own_profile - EOS-109 …`

통과한 322건에 `test_week1_gate_one_cycle_without_direct_db_writes`(7단계 관통)와
`test_mastery_step_assertion_is_discriminating`(음성 대조군)이 포함된다. 판정은 exit code로 냈다.

### 1-1. **정정 — 이 문서의 최초 판정은 "미통과"였고, 그것은 내 범위 오류였다**

지우지 않고 병기한다. 최초 회차(CI run `35313156085` 잡 `105499238372`)에서 판정 하네스는
`1 failed`였고 나는 이 문서에 **미통과**로 적었다. 그 실패는 실재했으나(§3의 결함) **그 단언은
게이트의 7단계에 없는 것이었다** — 나는 1단계 "사용자 생성"의 증거로 `GET /v1/users/me`
읽기까지 요구했고, 그 읽기가 깨져 있어 2~7단계가 아예 실행되지 못했다. 즉 **게이트를 막은 것은
제품이 아니라 내 하네스의 과도한 단언**이었다.

끊긴 지점을 `xfail(strict=True)`로 분리하자 2~7단계가 처음 실행되어 전건 통과했다. 판정을
**통과**로 정정한다. 결함 자체는 그대로 실재하고 `EOS-109`이 소유한다 — 다만 그것은 게이트의
합격 여부가 아니라 온보딩 표면의 문제다(§3).

이 정정이 남기는 교훈: **판정 기준을 원 문서의 문면보다 넓게 잡으면 판정이 제품 대신 판정자를
잰다.** 7단계에 없는 것을 1단계의 증거로 요구한 것이 그것이다.

## 2. 무엇을 판정했는가 — 그리고 이 판정이 기존 관통 증명과 다른 점

7단계를 **공개 HTTP 표면만으로** 관통하는 하네스를 만들었다
(`tests/backend/api/test_week1_gate_closed_loop.py`). 단계마다 status code가 아니라 *산출물*을
단언한다.

기존 관통 테스트(`test_e2e_vertical_slice_integration.py`, `EOS-81`)와의 차이가 이 판정의 핵심이다:
그 테스트는 학습자를 `_add_adult_user()`로 **ORM 직접 insert**해 만든다. 즉 7단계 중 1단계가 API
경로를 지나가지 않으므로, **루프 연결성은 증명하지만 게이트 문면("DB 직접 수정 없이")은 증명하지
않는다.** 이 하네스는 학습자를 `POST /v1/auth/{provider}/callback`(운영 `resolve_user` upsert)이
만들게 하고, 학습자 정리도 운영 삭제권(`DELETE /v1/me`)에 맡겨 **학습자 상태 SQL을 0으로** 만들었다.

그리고 그 한 줄을 바꾸자 **즉시 결함이 드러났다.**

| 단계 | 표면 | 판정 |
|---|---|---|
| ① 사용자 생성 | `GET /v1/auth/demo/state` → `POST /v1/auth/demo/callback` | **통과** — user_profile 0건→1건(호출 전 0건을 선행 삭제권 정리로 확보) |
| ② 진단 | `GET /v1/me/diagnosis/summary` · `GET /v1/me/next-problem?purpose=diagnosis` | **통과** — CAT이 문항을 골랐다(problem_id 비-null) |
| ③ 개념 선택 | `GET /v1/concepts/{id}` · `GET /v1/me/weak-concepts` | **통과** — 대상 개념 반환 · 약점 표면 호출 가능(콜드스타트 0건은 정당) |
| ④ 문제 풀이 | `GET /v1/problems/{id}` | **통과** — 200 + 정답 sentinel 비노출 |
| ⑤ 오답 | `POST /v1/me/attempts` | **통과** — 201 · `is_correct=False` · attempt_id 발급 |
| ⑥ mastery 변경 | 응답 `mastery_updates` + `GET /v1/me/mastery/current` | **통과** — 갱신 목록에 책임귀속 개념 포함 · 스냅샷 0건→N건(값 비-null) |
| ⑦ 다음 문제 추천 | `GET /v1/me/next-problem` | **통과** — 시도 문항 제외 · 표준오차 null→산출 |

**인접 표면(7단계 밖)**: `GET/PATCH /v1/users/me` — **깨져 있다**(§3 · `EOS-109` · `xfail(strict=True)`로 동결).

위 7건은 **한 회차에서 순서대로 실제 실행된 결과**다(간접 추론이 아니다). 각 단계는 status code가
아니라 산출물을 단언한다 — "API 200"을 통과 근거로 쓰는 단계는 없다.

---

## 3. 인접 결함 1건 — 게이트를 막지는 않지만 온보딩을 막는다

> **OAuth 로그인으로 생성된 학습자를 `GET/PATCH /v1/users/me`가 읽지 못한다(500).**

이것은 게이트의 7단계에 없는 표면이다(그러므로 판정은 통과다). 그러나 **신규 가입 계정의 프로필
조회·수정이 둘 다 500**이므로 실제 온보딩은 성립하지 않는다 — 게이트 합격과 별개로 P0로 다룬다.

「실측」 실패 예외:

> `whymath_backend/db/models/user.py:197` → `ValidationError: 4 validation errors for UserProfile`
> `track_type` · `target_universities` · `inkang_provider` · `accessibility_needs`
> 각각 `Input should be a valid list [type=list_type, input_value=None, input_type=NoneType]`

원인 사슬:

1. ORM 컬럼 4종은 **nullable**이다 — `db/models/user.py`의 `Mapped[list[...] | None]`.
2. 스키마 필드 4종은 **비옵셔널**이다 — `schema/user.py`의 `list[...]` (+`default_factory=list`).
3. `to_schema()`는 매핑된 키를 **명시적으로** 넘긴다(`{key: getattr(self, key) ...}`). 키가
   존재하므로 `default_factory`가 적용되지 않고 `None`이 그대로 검증에 들어간다.
4. `resolve_user`(`api/auth.py`)는 `from_schema`를 경유하지 않고 ORM 생성자를 직접 부른다 —
   그래서 그 4컬럼이 **NULL로 남는다**.

즉 **운영 로그인 경로로 만들어진 계정은 자기 프로필을 읽을 수 없다.** 이 결함은 main에 이미
있었고 이 PR이 건드린 코드가 아니다 — 기존 관통 테스트가 `from_schema`로 시딩해 `[]`가 채워졌기
때문에 그 경로를 한 번도 지나가지 않았다.

**후속 태스크**: `EOS-109` (이 지점만 고친다). 고치는 축은 셋(생성측 `from_schema` 경유 / 읽기측
NULL→`[]` 강제 / 컬럼 server_default + 백필)이고 파급이 서로 달라 **판정과 사유 기록을
acceptance가 요구한다**. 기존 NULL 행 축과 인접 표면 전수 확인도 별항으로 분리했다.

저장소에는 `xfail(strict=True)`로 동결했다(`test_oauth_created_learner_can_read_own_profile`).
`skip`이 아닌 이유는 저장소 선례(`test_notation_evidence_integrity.py`)와 같다 — skip은 "검사가
없는 것"과 구별되지 않아 침묵 실패가 되고, strict xfail은 고쳐지는 순간 **XPASS로 빨강**이 되어
표식 제거를 강제한다. `EOS-109` acceptance ④가 그 제거를 함께 요구한다.

---

## 4. 판정 하네스 자신의 변별력

"단언이 실패 상태에서 실제로 실패하는가"를 두 방향으로 확인했다.

**① 규율 가드의 뮤테이션 9종 — 전건 RED.** `test_week1_gate_no_learner_writes.py`는 판정 하네스가
학습자 상태를 DB에 직접 쓰지 않는다는 규율을 AST로 집행한다(금지 문자열 열거가 아니라 *생성되는
노드*를 본다 — 읽기 `select(UserProfile)`은 통과해야 하므로 이름 등장으로는 판정할 수 없다).
`scripts/ops/verify_week1_gate_guard.py`가 순수 Python으로 주입하고, 주입 적용 여부
(`mutated != original`)와 원복의 바이트 동일성을 각각 단언한다.

| 주입 | 대상 검사 | 결과 |
|---|---|---|
| M1 `session.add_all`에 `ProblemAttempt()` 추가 | 학습자 상태 생성 | RED |
| M2 `UserProfile.from_schema()` 직접 시딩 | 같음 | RED |
| M3 `ConceptMasteryHistory()` 기준선 시딩 | 같음 | RED |
| M4 정리 SQL → `INSERT INTO concept_mastery_history` | 원시 SQL 동사 | RED |
| M5 정리 SQL → `UPDATE concept_mastery_history` | 같음 | RED |
| M6 6단계 라벨 제거 | 7단계 전수 | RED |
| M7 1단계 라벨 제거 | 같음 | RED |
| M8 콘텐츠 시딩 호출 제거 (스캔 0건 축) | 학습자 상태 생성 | RED |
| M9 `text()` 호출 전건 제거 (스캔 0건 축) | 원시 SQL 동사 | RED |

대조군(정상 하네스) 3검사 GREEN · 원복 sha256 동일 · `exit 0`.

**만드는 과정에서 가드가 두 번 위장했고 둘 다 실측이 잡았다.** ⓐ첫 판은 리터럴을 전수 훑어
docstring의 "upsert"를 SQL 쓰기 동사로 읽어 **정상 상태에서 RED**였다(오탐을 내는 가드는 사람이
끄게 되므로 이것도 변별력 결함이다) → 검사 대상을 `text()` 호출 인자로 좁혀 해소. ⓑM9가 처음엔
**생존**했다 — 픽스처가 `text("DELETE FROM`만 치환해 `text("SELECT 1")`을 남겨 *스캔 0건 상태에
도달하지 못했다*. 절은 멀쩡했고 픽스처가 그 자리를 지나가지 않은 것이다(CLAUDE.md 2026-09-07
"픽스처가 그 절을 실제로 밟는가") → `text(` 전건 치환으로 고친 뒤 RED.

**② 6단계 단언의 음성 대조군 — CI 안에서 통과.** 판정은 `mastery_updates`가 비어 있지 않음을
6단계의 증거로 쓴다. 그 단언이 어떤 입력에서도 초록이면 증거가 아니라 장식이므로,
**개념 매핑이 없는 문항**으로 같은 오답을 제출하는 대조군을 같은 모듈에 뒀다 — 책임귀속 PRIMARY가
없으니 전파가 0이어야 한다. 파일을 고치지 않고 *입력*으로 실패 상태를 만들므로 판정과 같은 회차에
함께 돌고 원복 실패 위험이 없다. 결과: 통과(321 passed에 포함).

---

## 5. 선행 조건 확인 (P-01~P-04)

게이트의 시작 조건이다. **trunk 실측**으로 확인했다(브랜치 아님).

| 지시문 | 태스크 | main `d99a4828`의 status |
|---|---|---|
| `P-01` Learning Loop Contract v1 | `EOS-100` | `done` |
| `P-02` Learning Event 정본화 | `EOS-11` | `done` |
| `P-03` LearnerState v1 | `EOS-10` | `done` |
| `P-04` 학습 상태 머신 | `EOS-105` | `done` |

전건 충족. 확인 방법: `git show origin/main:backlog/tasks/<파일>` 의 `status` 필드.

---

## 6. 판정 범위 — 무엇을 보지 않았는가

원 문서 지시대로 **연결성만** 봤다. AI 품질·추천 품질·UI는 판정 대상이 아니다.

- **저작 콘텐츠는 ORM으로 시딩했다.** 원 문서 §4가 "가짜 데이터라도 전체 흐름이 한 번 돌아가게"라고
  명시해 콘텐츠는 전제이고, 7단계에 저작 행위가 없다. 이것은 *선언된 경계*이며 게이트 문면의 문자적
  전수 충족은 아니다. 덧붙여 `problem_concept`(문제↔개념 매핑)에는 **HTTP 쓰기 API가 없다**
  (라우트 108종 AST 전수 추출로 확인) — 다만 그것은 갭이 아니라 설계다: 적재 정본은 L1 코퍼스 경로
  (`l1/problem_bank/populate.py`·`scripts/demo/seed_demo.py`)다. (한 번 갭으로 의심했다가 역할 기반
  재검색으로 정정한 판정이다.)
- **외부 IdP는 스텁이다.** `FakeOAuthProvider`(저장소에 실재하는 시연 경로)를 주입해 code 교환 한
  지점만 대체한다. 그 뒤(`resolve_user` upsert·`derive_is_minor` 서버 파생·JWT 발급)는 운영 코드
  그대로다. CI에 카카오/네이버 자격증명을 들이지 않고 사용자 생성 코드 경로를 지나가는 유일한
  방법이며, 실 provider와의 통합은 여전히 미검증이다(기존 `oauth_providers.py` docstring의 자인과
  같은 범위).
- **2단계 CAT 단언을 약하게 뒀다** — "문항을 고를 수 있는가"만 보고 *어느* 문항인지는 보지 않는다.
  이 잡은 통합 테스트 전체가 PG 하나를 공유해 후보 풀에 다른 테스트의 시딩이 섞이며, "내 문항이
  뽑혀야 한다"고 쓰면 판정이 남의 시딩 순서에 의존한다 — 그때의 red는 루프 고장이 아니라 판정
  하네스의 결함이다.

---

## 7. 정직한 공백

1. **②③④⑦은 단 한 회차만 실행됐다.** `xfail` 재구성 이후 회차(`35315225642`)가 그 네 단계를
   처음 실행해 전건 통과했다. 1회 실증은 "그때 됐다"이지 "지금도 된다"가 아니다 — 상시성은 이
   하네스가 `backend-migrations` 잡(PR 상시)에 들어가 있는 것으로 확보된다. 다만 `EOS-81` 관통이
   `e2e-nightly`에서 추가로 도는 것과 달리 이 하네스는 **야간 회차가 없다**(필요 판정은 별건).
2. **이 판정 하네스는 판정 환경에서 한 번도 로컬 실행되지 못했다.** CCR 컨테이너는 pypi가 상시
   503이라 `pip install`이 불가하다(직접·프록시 모두 15초 후 503). 라이브 실행은 전부 CI다.
3. **ruff·pytest를 로컬에서 못 돌렸다.** black은 GitHub 소스 조립으로 확보해 CI 명령을 그대로
   재현했으나(§8), ruff는 Rust 바이너리이고 pytest는 백엔드 런타임 의존성(asyncpg·pydantic-core
   등 컴파일 확장)이 필요해 같은 방법이 통하지 않는다.
4. **`crosswalk` §9-⑤의 "등재 불필요 — 이미 돈다"는 판정은 절반만 옳았다.** 루프는 돈다(그 문서가
   근거로 든 `EOS-81` 관통이 실제로 관통한다). 그러나 게이트 문면의 *"DB 직접 수정 없이"* 축은 그
   관통이 증명하지 않았고, 그 축을 실제로 판정하자 결함 1건이 드러났다. 같은 §10의 "관통 테스트가
   nightly 전용이라 PR에서 돌지 않는다"는 서술은 **실측과 다르다**(그 테스트에는 `integration`
   marker가 있어 PR의 `backend-migrations` 잡이 수집한다) — 정정은 `EOS-107`이 소유한다.

---

## 8. 부수 사고와 대책 (같은 세션)

판정과 무관하지만 같은 세션에서 발생했으므로 기록한다. **추측으로 포맷을 고쳐 CI red를 2회** 냈다.
근본 원인은 포맷 결함이 아니라 **오라클 부재**였다 — pypi 503으로 black을 설치할 수 없어 Black의
동작을 추측했고, "조각이 95자니까 한 줄에 들어간다"는 계산이 틀렸다(**Black은 줄 길이를 문자 수가
아니라 표시 폭으로 잰다 — 한글·CJK는 폭 2**). 해결은 GitHub 소스에서 black 26.5.1과 순수 파이썬
의존성을 조립해 실물을 돌린 것이다. 버전은 추측하지 않고 특정했다(핀 `black>=24.10.0,<27` → 최신
26.5.1). **정합 확인 스텝이 사고를 한 번 더 막았다**: 먼저 조립한 25.9.0은 기존 파일 11건을
재포맷하려 해 CI와 불일치였고, 26.5.1은 CI 로그와 글자까지 일치했다
(`1 file would be reformatted, 1594 files would be left unchanged`).

두 회차 모두 Black이 7번째 스텝이라 **뒤 20스텝이 전부 skipped**였다(mypy·계층 커버리지 게이트·
게이트 CLI 13종) — 화면상 "실패 1건"인데 검증 표면 대부분이 미실행이었다.

대책 = `HARN-110` 등재 + MEMORY 결정 로그 기재(CLAUDE.md 「실수 관리」 — 시스템 실수·동일 유형 2회
이상은 등재 의무).

---

## 9. Kiki가 할 판정

이 문서는 **게이트가 통과라는 사실**과 **인접 결함 1건**을 확정한다. 남은 결정은 Kiki 몫이다:

1. **게이트 통과를 인정할 것인가** — 통과 근거는 7단계 전건이고, 판정 범위 밖으로 선언한 것은
   §6의 두 축(저작 콘텐츠 ORM 시딩 · 외부 IdP 스텁)이다. 그 두 선언을 받아들이지 않으면 판정은
   달라진다 — 그 판단은 이 문서가 대신하지 않는다.
2. **`EOS-109`을 지금 착수시킬 것인가.** 게이트를 막지는 않지만 신규 가입 계정의 프로필 조회·수정이
   둘 다 500이므로 폐쇄루프 시연이 성립하지 않는다. acceptance ②의 세 축(생성측 `from_schema`
   경유 / 읽기측 NULL→`[]` / 컬럼 server_default + 백필) 중 무엇을 고를지는 그 태스크 세션이
   판정해 사유를 남기게 해 뒀다 — 미리 지정하고 싶으면 그 태스크 notes에 지시를 남기면 된다.
3. **이 PR을 머지할 것인가.** 머지하지 않았다 — CI green이고 충돌 없으나 머지는 Kiki 몫이다.

**작성**: 2026-09-18 · `EOS-106` · 판정 기준 main `d99a482807e0bf31d8cc3d43097ac279f95881ac`
