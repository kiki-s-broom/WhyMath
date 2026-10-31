# EOS-194 — 문항 발행 호출 표면: `l3/problem_publish_gate`의 운영 호출자

> **판정 기준**: `main 093d172b` 위의 작업 브랜치 `claude/jolly-fermi-6km81l`(**미머지**). 아래 "착지"는 이 브랜치 기준이며, 머지 전에는 main에 없다. 2026-10-13.
> **선행**: `EOS-190`(writer — `docs/architecture/eos190_problem_publish_writer.md`). **짝**: 개념 판 P3-12(`api/admin_cms.py`). **후속**: `EOS-195`(발행 이후 편집 드리프트) · `EOS-196`(Rollback·Restore) · `EOS-193`(시도 단위 pinned 비율 리포트).

## 1. 한 줄 결론

`problem_version`의 유일한 writer를 부르는 **운영 표면을 관리자 CMS 라우트 4개로 만들었다.** 실제 JWT·실제 PostgreSQL로 편집자·검수자·배포자 세 역할이 HTTP만으로 초안 → 제출 → 검토 → 승인 → 발행까지 가고, 그 직후 학습자의 `POST /v1/me/attempts`가 `outcome=pinned`를 내며 시도 행에 판 id가 박힘을 확인했다. **그러나 운영 DB에서의 측정은 아직 하지 않았다** — 이 샌드박스는 운영 DB에 닿지 못한다. 측정 방법은 §5에 있고, 그 값이 나오기 전까지 "운영에서 pinned 비율이 0을 벗어났다"고 말할 수 없다.

## 2. 인수 조건 대조 (정직 기술)

| # | 인수 조건 | 상태 | 근거 |
|---|---|---|---|
| ① | 호출 표면 = CMS 라우트 vs 운영 CLI 중 **판정 근거와 함께** 하나. 게이트 공개 함수만 부르고 ORM `ProblemVersion`을 import하지 않는다 | 착지 | §3(판정) · AST 동결(§6) |
| ② | 권한 매핑(`schema/cms_access.py` 정본 재사용) · 전이 1건마다 감사 1행 | 착지 — **단, 문구와 정본이 한 곳 어긋난다**(§4) | 역할×전이 32칸 매트릭스 · 실 PG 감사 5행 |
| ③ | 실제 표면으로 발행 → `outcome=pinned` · `problem_attempt.problem_version_id` 채워짐 · 운영 DB 분자/분모 | **부분** — 실 PG 관통은 했고 **운영 DB 측정은 미실시** | §5 |

## 3. 표면 선택 판정: CMS 라우트 (CLI 아님)

| 판단 축 | CMS 라우트 | 운영 CLI |
|---|---|---|
| 역할 분리(편집·검수·배포) | `RequireContent*` 모듈 가드 + `CmsCapability` 검사를 **DB 접근 전에** 수행. 정본 `cms_access` 재사용 | CLI는 인증된 역할이 없다 — 권한표를 새로 지어야 한다(복제 = 드리프트 자리) |
| 전이마다 감사 1행 | `privacy_audit.user_id` = 인증된 사용자 | 행위자를 CLI 인자로 받으면 위조 가능, 신원 검증 경로를 또 지어야 한다 |
| 기존 자산 | 개념 판 P3-12가 같은 모양(권한 → 게이트 → 감사 → commit 1회)으로 이미 운영 중 | 해당 없음 |
| 웹 UI 없이 쓰기 | 운영자 토큰 CLI(`ops/operator_token_cli`, ADMIN-15)가 `content_*` 4개 역할 계정에 단기 토큰을 발급한다 — **같은 라우트를 HTTP로 직접 부를 수 있다** | — |

판정: CMS 라우트. 운영 CLI를 따로 두면 얻는 것이 없고(위 토큰 경로가 이미 CLI 사용성을 준다) 권한·감사를 두 번 짓게 된다.

## 4. 라우트와 권한

| 메서드 · 경로 | 권한 | 하는 일 |
|---|---|---|
| `POST /v1/admin/cms/problems/{problem_id}/drafts` | `EDIT` | **지금 라이브 문항 행의 스냅숏**으로 새 DRAFT 판(`version_no`=최신+1) |
| `GET /v1/admin/cms/problems/{problem_id}/versions` | `VIEW` | 판 목록(최신부터). 없는 문항은 404, 판이 0건이면 빈 목록 |
| `GET /v1/admin/cms/problem-versions/{version_id}` | `VIEW` | 판 상세 — payload · 거버넌스 · 게이트 통과 기록 |
| `POST /v1/admin/cms/problem-versions/{version_id}/transitions` | 전이별(아래) | 제출·검토·승인·발행·폐기·은퇴 |

판 경로가 `/versions/{id}`가 아니라 `/problem-versions/{id}`인 이유: 앞의 것은 개념 판이 이미 쓴다.

**전이 → 권한(글자로 동결, `schema/cms_access.TRANSITION_CAPABILITY`)**: `submit`=편집 · `request_changes`·`pass_review`·`fail_qa`·`approve`=검수 · `publish`·`deprecate`·`retire`=배포. 복합 전용(`supersede`·`rollback`·`restore`)과 어휘에 없는 이름은 422(`unknown_action`)다.

**⚠ 인수 조건 문구와 정본의 불일치 — 판단이 필요하면 알려 달라.** 인수 조건 ②는 "승인·발행·내리기는 content_publisher"라고 적었다. 그러나 같은 문장이 "(`schema/cms_access.py` 정본 재사용)"이라고 명시하고, 그 정본은 **`approve`를 검수 권한(content_reviewer)** 으로 둔다(개념 판과 동일). 둘이 어긋나 **정본을 따랐다** — 문항 판만 다른 권한표를 쓰면 한 CMS 안에서 같은 전이 이름이 판 종류에 따라 다른 사람에게 열리고, `cms_access`는 개념 판 테스트(`test_cms_access`)가 동결하고 있어 건드리면 개념 판 동작이 바뀐다. 승인을 배포자에게 넘기고 싶다면 그것은 두 판 모두에 영향을 주는 별도 결정이며, `CONTENT_ADMIN`은 어느 쪽이든 전부 가진다.

**초안에 `changes`(payload)가 없다.** 문항은 판과 별개로 라이브 `problem` 행이 서빙된다. 발행은 "승인 이후 라이브 문항이 바뀌지 않았다"(`live_content_current`)를 요구하므로 초안은 항상 지금 라이브 행의 스냅숏이어야 한다. 내용을 고치려면 라이브 행을 먼저 고친(`PATCH /problem/items/{pk}`) 뒤 새 초안을 만든다(발행된 판이 있는 문항은 그 PATCH가 409로 막히므로 먼저 판을 폐기한다 — EOS-195). payload를 받으면 발행될 수 없는 초안을 만드는 입구가 된다.

## 5. 인수 조건 ③ — 운영 DB 측정 (**미실시 — Kiki 실행 과제**)

### 5.1 샌드박스에서 실제로 측정한 것

운영이 아닌 로컬 PostgreSQL 16(+pgvector, alembic head)에서 `tests/backend/api/test_admin_cms_problem_versions_integration.py`가 다음을 확인했다.

- 발행 전 시도는 `outcome=no_version`, 시도 행 `problem_version_id` = NULL.
- 세 역할이 HTTP로 발행한 뒤 시도는 `outcome=pinned`, 시도 행에 그 판 id.
- 발행하지 않은 형제 문항은 계속 NULL, 발행 이전 시도는 소급되지 않음.
- 이 월드에서 **포인터가 채워진 노출 문항 / 노출 문항 = 1/2**(출력 `EOS194_POINTER_COVERAGE=1/2`).
- 운영 런북 SQL(아래)을 글자 그대로 실행한 발행 전후 증분: 분모·전체 문항 수 0 변화, 분자·발행 판 수 +1.

### 5.2 운영 DB에서 재는 법 (Kiki)

**① 과제 명칭** — 운영 DB 문항 발행 포인터 채움 비율 조회 (읽기 전용 1회).

**② 목적** — EOS-194 인수 조건 ③의 숫자를 얻는다. "노출 문항 N개 중 발행 표면으로 포인터가 채워진 문항 M개"를 보고하고, 0이면 0이라고 적는다. 분모의 "노출"은 서빙 후보 풀의 조건(`candidate_pool_conditions`: 난이도 라벨 보유 · 본문 미보유 출처(평가원·EBS·교과서) 제외 · `review_status=approved`)과 같다.

**③ 절차** — 새 PowerShell 창에서 아래 블록을 통째로 붙여넣는다. 컨테이너가 떠 있는지 확인한 뒤 SQL 1개를 읽기 전용으로 실행한다. 쓰기 0 · 소요 10초 미만. 코드 브랜치를 바꿀 필요가 없다(SQL이 이 문서에 들어 있다).
머지·배포 **전**에 재면 발행 표면이 운영에 없으므로 `exposed_with_pointer=0`이 기대값(베이스라인)이고, 운영자가 실제로 문항을 발행한 **뒤**에 다시 재야 의미 있는 값이 나온다.

**④ 성공 기준**
- `CONTAINER_UP=True` · `PSQL_EXIT=0` · `HAS_TOTAL_ROW=True`. 그리고 `total_problems`가 0보다 크다(0이면 빈 DB이거나 엉뚱한 DB다).
- 해석: `exposed_with_pointer=0` → 발행된 노출 문항이 없다(그대로 "0건"으로 보고). `any_with_pointer`가 `exposed_with_pointer`보다 크면 포인터는 있으나 노출 풀 밖인 문항이 있다(발행됐지만 서빙은 안 됨 — 검수 상태 확인).
- 실패 신호: `CONTAINER_UP=False`(→ Docker Desktop·컨테이너 가동 후 재시도) 또는 `HAS_TOTAL_ROW=False`(→ 출력된 오류 문구를 세션에 전달).

**⑤ 실행 환경** — Phaiakes9(Kiki 작업 PC 그 자체) · Windows PowerShell · 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath` · 선행 조건: Docker Desktop 실행 중, 운영 DB 컨테이너 `whymath-pg`(호스트 포트 5433) 가동.

**⑥ 창 구분** — 새 창 1개. 서버를 점유하지 않으므로 창 제약이 없다.

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 하나 — 읽기 전용 조회 (쓰기 없음)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Names = docker ps --filter "name=whymath-pg" --format "{{.Names}}"
"CONTAINER_UP=" + [bool]$Names
if ($Names) {
  # SQL은 ASCII만 쓴다 — 한글 출처명은 U&'\XXXX' 이스케이프(PowerShell 5.1의 인자 인코딩 왕복 방지).
  $Sql = "SELECT count(*) AS total_problems, count(*) FILTER (WHERE problem.difficulty_overall IS NOT NULL AND (problem.source_type NOT IN ('EBS', U&'\D3C9\AC00\C6D0', U&'\AD50\ACFC\C11C')) AND problem.review_status = 'approved') AS exposed, count(*) FILTER (WHERE problem.difficulty_overall IS NOT NULL AND (problem.source_type NOT IN ('EBS', U&'\D3C9\AC00\C6D0', U&'\AD50\ACFC\C11C')) AND problem.review_status = 'approved' AND problem.problem_version_id IS NOT NULL) AS exposed_with_pointer, count(*) FILTER (WHERE problem.problem_version_id IS NOT NULL) AS any_with_pointer, (SELECT count(*) FROM problem_version WHERE status = 'PUBLISHED') AS published_versions FROM problem"
  $Out = $Sql | docker exec -i whymath-pg psql -U whymath -d whymath -X -x -v ON_ERROR_STOP=1 2>&1
  "PSQL_EXIT=$LASTEXITCODE"
  "HAS_TOTAL_ROW=" + [bool]($Out -match "total_problems")
  $Out
} else { "SKIPPED — whymath-pg 컨테이너가 떠 있지 않다. Docker Desktop을 켜고 컨테이너를 가동한 뒤 다시 붙여넣는다." }
```

**자가검증의 변별력**: 컨테이너가 없으면 `CONTAINER_UP=False`와 SKIPPED 문구가 뜬다. psql이 실패하면(접속 불가·SQL 오류) `PSQL_EXIT`가 0이 아니거나 `HAS_TOTAL_ROW=False`가 뜬다 — `$LASTEXITCODE`만 믿지 않고 **결과 행의 실재**를 함께 본다.

> 이 SQL이 서빙 노출 게이트와 갈라지면 `tests/backend/api/test_admin_cms_problem_versions.py`의 드리프트 가드가 RED가 된다(노출 조건 2곳을 코드에서 컴파일한 것과 비교). 런북 문서의 SQL이 그 테스트 상수와 글자 단위로 같음은 별도 테스트가 확인한다.

## 6. 검증 (CI가 실제로 도는 것과 개발 중 실 PG)

- **hermetic(CI 상시)** — `tests/backend/api/test_admin_cms_problem_versions.py`: 역할×전이 32칸 리터럴 매트릭스 · 복합/미정의 전이 422 · 초안 요청이 내용을 받지 않음 · 오류 매핑(404·409·422·예상 밖) · commit 실패 시 rollback · 트랜잭션 경계 뒤 사용자 접근 금지 · AST(ORM import·포인터 쓰기·쓰기 SQL 주입 시 RED / 게이트 공개 함수 5개만 호출 / 권한표 재진술 금지 / DB 직접 접근 금지).
- **실 PG(`backend-migrations` 잡이 수집)** — `tests/backend/api/test_admin_cms_problem_versions_integration.py` 5건: 발행 관통(위 §5.1) · 권한 거부 시 DB 불변 · 승인 뒤 라이브 변경 → 422 · 재발행/낡은 상태 409/내리기 · 없는 ID 404. `--collect-only`로 CI와 같은 명령에서 5건 수집을 확인했다(`tests/backend/l3` 아래였다면 수집되지 않는다 — EOS-190 §4).
- **뮤테이션** — 라우트 모듈 28종(권한 제거·약화·감사 제거·리소스 타입 오기·rollback 제거·commit 순서·사용자 접근·extra 허용·payload 입구·존재 확인 제거 등) 전건 검출·생존 0. 처음 한 번 생존한 1종(초안 경로의 예상 밖 오류 rollback)은 테스트를 보강해 잡았다. 통합 테스트의 변별력은 전이 라우트의 `commit` 제거 주입(4건 RED)으로 확인했다. 동등 뮤턴트 1종 — 읽기 라우트의 `VIEW` 검사 제거는 모든 CMS 역할이 `VIEW`를 가져 관찰할 수 없다.
- **이 작업이 닿은 기존 동결** — `test_admin_cms.py`(CMS 라우트 +4·쓰기 +2 — main의 P3-26 병합 뒤 합계 44건·19건) · `test_admin_bff.py`(쓰기 허용 목록 닫힌 목록에 2종 등재) · `eos_feature_inventory_v2.py`(`WM-S-058` 신설, `WM-E-316` 낡은 문구 정정) · `data_access_layer_audit.py`(baseline에 경계 소유로 +1, §8).

## 7. 알려진 한계

1. **운영 DB 측정 미실시**(§5.2) — 이것이 끝나기 전에는 인수 조건 ③을 완료로 말할 수 없다.
2. **웹 관리 화면이 없다.** 이 변경은 서버 라우트까지다. 운영자는 운영자 토큰(ADMIN-15)으로 HTTP를 직접 부르거나, 화면은 별도 태스크로 만든다.
3. **발행 이후 제자리 편집은 새 판이 되지 않는다**(`EOS-195`). [정정 2026-10-31 · EOS-195 회수] 발행된 판이 있는 문항은 CMS 편집·`PATCH /v1/problems`·코퍼스 재적재가 판 payload 원천 필드를 바꾸지 못한다(409·건너뜀). 고치려면 판 폐기 → 수정 → 새 판 발행이다. payload 밖 필드(개념 연결·`distractor_map`·슬롯 태그 등)는 여전히 바뀔 수 있다.
4. **롤백·복원 없음**(`EOS-196`). 발행본 내리기(`deprecate`)와 새 판 재발행만 가능하다.
5. **접수 시점 ≠ 출제 시점**(`EOS-191`)은 그대로다.

## 8. 작업 중 발견한 것

- **`HTTP_422_UNPROCESSABLE_ENTITY` 폐기 경고**: 설치된 starlette에서 deprecated 경고가 난다. 기존 `admin_cms.py`가 같은 상수를 쓰므로 일관성을 위해 따랐고, 경고는 pytest에서 에러가 아니다(별도 정리 대상).
- **드리프트 가드 flake**: `METADATA_ONLY_SOURCES`가 `frozenset`이라 SQL `NOT IN (...)` 나열 순서가 프로세스마다 달라진다(문자열 해시 무작위화). 첫 구현의 문자열 직접 비교가 `pytest-randomly`로 우연히 실패해 발견했고, 목록을 집합으로 비교하도록 고쳤다(해시 시드 6종에서 확인).
- **한글 리터럴과 PowerShell**: 첫 SQL 초안의 `'평가원'`·`'교과서'`는 Windows PowerShell 5.1이 네이티브 명령 인자를 cp949로 왕복시켜 조용히 바뀔 수 있어 `U&'\XXXX'` 이스케이프로 바꿨다. 이스케이프 값을 암산으로 쓴 것이 틀렸고(`교`는 `AD50`, 내가 쓴 `ACE0`이 아님) PG에서 `= '교과서'`를 직접 확인해 잡았다.
- **`data_access_layer_audit`**: API 모듈에 직접 `select`를 두었더니 `infra-contracts` 잡의 데이터 접근 baseline이 새 접근점으로 막았다. 존재 확인 쿼리는 게이트 모듈의 읽기 전용 공개 함수(`problem_exists`)로 옮겨 **API 모듈에서 쿼리를 없앴다.** 그래도 이 감사는 `session.commit()`·`rollback()`(트랜잭션 경계)도 데이터 접근으로 세므로 — 경계는 전이 + 감사 1행 + commit 1회를 한 트랜잭션으로 묶기 위해 라우트 핸들러가 소유한다(개념 CMS `api/admin_cms.py`와 같은 이유) — 감사가 안내한 정식 경로(baseline 등재, 사유 명시)로 `api/admin_cms_problem_versions.py`를 등재했다. 등재는 '쿼리 접근점'이 아니라 '경계 소유'로 한정된다(쿼리 직접 접근 금지는 AST로 동결).
