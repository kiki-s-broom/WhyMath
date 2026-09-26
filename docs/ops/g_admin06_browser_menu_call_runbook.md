# 게이트 `G-admin06-browser-menu-call` 실행 런북 — 백오피스 셸 실 브라우저 menu 호출 확인

> 작성: 2026-09-25 · 판정 기준: main `63451153`
> 대상 게이트: `G-admin06-browser-menu-call` (ADMIN-06 acceptance ②의 사람 축 · ADMIN-07 착수 선결)
> A 단계는 **읽기 전용**이다(DB 쓰기·대장 조작·배포 없음). B 단계는 `whymath-pg`에 백업 후 스키마 업그레이드 1회와 토큰 발급 감사 1행을 쓴다(§5 B2·B3 — 둘 다 자가거부 가드 안).
> 개정: 2026-09-25 §5 B 단계 채움(ADMIN-15 착지 · 판정 기준: 브랜치 `claude/optimistic-euler-wckia8`, main `f138f894` 병합본)

## 0. 먼저 알아 둘 것 — 이 게이트는 두 단계로 나뉜다

게이트 제목은 두 가지를 확인하라고 요구한다.

| 단계 | 확인 내용 | 지금 실행 가능? |
|---|---|---|
| **A. CORS 축** | 허용 origin에서는 브라우저가 서버 응답을 **받고**, 비허용 origin에서는 브라우저가 **차단한다** | ✅ 가능 (이 런북 §2~§4) |
| **B. 렌더 축** | 허용 origin에서 **200 + 좌측 내비 렌더** | ✅ `ADMIN-15` 머지 후 가능 (§5) |

B가 불가한 이유: `GET /v1/admin/menu`는 **데모 계정이 아닌** 실 신원 토큰을 요구한다(`api/admin_menu.py` — 데모 계정 403). 저장소에서 액세스 토큰을 발급하는 경로는 OAuth 콜백(`api/auth.py`)과 데모 로그인 둘뿐이고, Kiki의 content_admin 계정(`account_bootstrap_cli`로 생성 — 게이트 `G-operator-seat-first-grant` 증적)에는 OAuth 로그인 이력이 없다. 이 공백은 태스크 **`ADMIN-15-operator-access-token-issuance`**가 운영자 토큰 발급 CLI로 메웠다(§5).

**A 단계만으로 게이트를 닫지 않는다.** A의 결과는 게이트 notes에 부분 증적으로 남기고, B까지 끝난 뒤 clear한다.

### A 단계가 변별력이 있는 이유 (2026-09-25 컨테이너 실측)

토큰 자리에 **일부러 가짜 문자열**(`not-a-real-token`)을 넣는다. 그러면 서버는 401을 낸다. 이때:

- 허용 origin → 브라우저가 401 응답을 자바스크립트에 **넘겨준다** → 셸 화면 제목 「**토큰이 유효하지 않습니다 (401)**」
- 비허용 origin → 브라우저가 응답을 **차단한다**(자바스크립트는 상태 코드조차 못 본다) → 셸 화면 제목 「**백엔드에 닿지 못했습니다**」, 개발자도구 콘솔에 `blocked by CORS policy`

두 화면이 서로 다르므로, 이 확인으로 CORS가 막는 경우와 통과시키는 경우를 가를 수 있다. Chromium(Playwright)으로 이 두 결과가 실제로 갈리는 것을 확인했다.

> 실측(컨테이너, Next 15.5.25 admin 빌드 + uvicorn): 허용 origin `http://127.0.0.1:3001` → 네트워크 `GET 401`, 화면 「토큰이 유효하지 않습니다 (401)」 · 비허용 origin `http://localhost:3001` → 콘솔 `Access to fetch ... has been blocked by CORS policy`, 화면 「백엔드에 닿지 못했습니다 … 실패 종류: TypeError」 · 프리플라이트 직접 호출: 허용 200 / 비허용 400.

**`127.0.0.1`과 `localhost`는 브라우저에게 서로 다른 origin이다.** 그래서 정적 서버 하나만 띄워도 허용·비허용 두 origin을 모두 만들 수 있다 — 허용 목록에는 `http://127.0.0.1:3001`만 넣는다.

## 1. 사전 브리핑 (6항목)

1. **과제 명칭**: 백오피스 셸 실 브라우저 CORS 확인 (게이트 A 단계)
2. **목적**: 관리 콘솔 셸이 *실제 브라우저*에서 백엔드 메뉴 API를 부를 때, 허용한 주소에서는 통과하고 허용하지 않은 주소에서는 막히는지 사람 눈으로 확인한다. 서버 쪽은 테스트로 고정돼 있지만 브라우저의 실제 동작은 사람만 볼 수 있다. 결과는 검수 큐 화면(ADMIN-07) 착수의 선결 조건이 된다.
3. **구체적 절차** (총 10~15분, 대부분 `npm ci` 대기):
   - 블록 1 (창①): 작업 사본을 건드리지 않는 임시 폴더(worktree)에 main을 꺼내고 Node 설치를 확인한다 — 30초
   - 블록 2 (창①): 관리 콘솔을 빌드한다 — 3~8분
   - 블록 3 (창②): 백엔드 서버를 띄운다 — 10초, 이후 창 점유
   - 블록 4 (창③): 빌드 결과물을 서빙하는 정적 서버를 띄운다 — 즉시, 이후 창 점유
   - 블록 5 (창①): 세 서버 상태를 기계로 확인한다 — 5초
   - 브라우저 확인 2회 — 2분
   - 블록 6 (창①): 정리 — 10초
4. **성공 기준**: 블록 5가 `PREFLIGHT_ALLOWED=200`·`PREFLIGHT_DENIED=400`·`STATIC_ADMIN=200`을 내고, 브라우저에서 `127.0.0.1` 주소는 「토큰이 유효하지 않습니다 (401)」, `localhost` 주소는 「백엔드에 닿지 못했습니다」가 뜬다. **실패 시 대처 1개**: 두 주소 모두 「백엔드에 닿지 못했습니다」가 뜨면 창②의 서버가 죽었거나 `WHYMATH_CORS_ALLOWED_ORIGINS`가 안 들어간 것이다 — 창② 출력의 `CORS_ORIGINS=` 줄과 `Uvicorn running` 줄을 확인한다.
5. **실행 환경**: Phaiakes9 = Kiki 작업 PC의 **Windows PowerShell**(WSL 아님). 기본 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선결 조건: 백엔드 venv(`src\backend\.venv`) 존재 · Node.js 설치(블록 1이 확인) · 포트 8010·3001 비어 있음(블록 3·4가 확인). **Docker·DB 불필요**(A 단계는 가짜 토큰이라 DB에 닿기 전에 401이 난다).
6. **창 구분**: PowerShell 창 **3개**를 새로 연다 — 창① [준비·검증], 창② [백엔드 — 점유], 창③ [정적 서버 — 점유]. 창②·창③은 서버가 점유하므로 **블록을 붙여넣은 뒤에는 아무것도 입력하지 않는다. 그 창에서 Ctrl+C는 복사가 아니라 서버 중단 신호다**(정리 단계에서만 누른다).

## 2. 준비 · 빌드 (창①)

### 블록 1 — 창① [준비]: worktree 생성 + Node 확인

Kiki 클론은 여러 세션이 함께 쓰는 작업 사본이라, 다른 브랜치가 체크아웃돼 있거나 커밋되지 않은 변경이 있을 수 있다. 체크아웃을 옮기지 않고 임시 폴더에 main을 꺼낸다(원 작업 사본은 하나도 바뀌지 않는다).

```powershell
# [창① 준비] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
if (Test-Path $Wt) { git worktree remove --force $Wt; "OLD_WORKTREE_REMOVED=True" }
git worktree add --detach $Wt origin/main
"WORKTREE_HEAD=" + (git -C $Wt log -1 --oneline)
"NODE_FOUND=" + [bool](Get-Command node -ErrorAction SilentlyContinue)
"NPM_CMD_FOUND=" + [bool](Get-Command npm.cmd -ErrorAction SilentlyContinue)
```

판정: `NODE_FOUND=True`와 `NPM_CMD_FOUND=True`가 둘 다 나와야 블록 2로 간다. `False`면 Node.js 22 LTS를 설치하고 **새 창**에서 블록 1부터 다시 한다. `WORKTREE_HEAD=`의 해시가 이번 실행의 기준 커밋이므로 회신에 포함한다.

### 블록 2 — 창① [빌드]: admin 타깃 빌드

위 블록 1의 `NODE_FOUND=True`를 확인한 다음에만 붙여넣는다. `npm` 대신 `npm.cmd`를 쓰는 이유: PowerShell 실행 정책이 `npm.ps1`을 막는 환경이 흔하다.

```powershell
# [창① 빌드] Windows PowerShell — Phaiakes9
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$HasNode = [bool](Get-Command npm.cmd -ErrorAction SilentlyContinue)
if ($HasNode) { cd (Join-Path $Wt "src\web\webapp"); npm.cmd ci --no-audit --no-fund; $env:NEXT_PUBLIC_WHYMATH_API_BASE_URL = "http://127.0.0.1:8010"; npm.cmd run build:admin; "BUILD_EXIT=$LASTEXITCODE" } else { "BUILD_REFUSED=True — npm.cmd 없음. Node.js 22 LTS 설치 후 새 창에서 블록 1부터" }
"OUT_ADMIN=" + (Test-Path (Join-Path $Wt "src\web\webapp\out\admin\index.html"))
cd C:\Users\kiki\Desktop\__AI\WhyMath
```

판정: `BUILD_EXIT=0`과 `OUT_ADMIN=True`. 빌드 출력의 라우트 표에 `/admin`이 있어야 한다(`/`는 없어야 정상 — admin 타깃은 공개 랜딩을 빼고 빌드한다). worktree는 블록 1에서 매번 새로 만들므로 `OUT_ADMIN=True`가 이전 실행의 잔재일 수 없다.

## 3. 서버 기동 (창② · 창③)

### 블록 3 — 창② [백엔드 — 점유]

**이 창은 블록을 붙여넣은 뒤 서버가 점유한다. 이후 아무것도 입력하지 않는다. Ctrl+C는 서버 중단 신호다.**

이 블록은 서버를 띄우기 전에 두 가지를 스스로 검사하고, 하나라도 어긋나면 서버를 띄우지 않고 이유를 출력한다: ①실행될 백엔드 코드가 worktree(main)의 것인가(`import` 후 `__file__` 출력) ②포트 8010이 비어 있는가(좀비 서버가 대신 응답하는 사고 방지).

```powershell
# [창② 백엔드 — 이 창은 서버가 점유합니다. 붙여넣은 뒤 조작 금지]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$env:WHYMATH_CORS_ALLOWED_ORIGINS = "http://127.0.0.1:3001"
$env:WHYMATH_JWT_SECRET_KEY = (& $Py -c "import secrets;print(secrets.token_urlsafe(48))")
$AppFile = (& $Py -c "import whymath_backend.app as a; print(a.__file__)")
$FromWt = ($AppFile -eq (Join-Path $Wt "src\backend\whymath_backend\app.py"))
$PortBusy = [bool](Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
"APP_FILE=$AppFile"
"FROM_WORKTREE=$FromWt"
"PORT_8010_BUSY=$PortBusy"
"CORS_ORIGINS=$env:WHYMATH_CORS_ALLOWED_ORIGINS"
if ($FromWt -and (-not $PortBusy)) { & $Py -m uvicorn whymath_backend.app:create_app --factory --host 127.0.0.1 --port 8010 } else { "SERVER_REFUSED=True — FROM_WORKTREE=False면 블록 1 재실행, PORT_8010_BUSY=True면 Get-NetTCPConnection -LocalPort 8010 으로 점유 프로세스 확인 후 정리" }
```

판정: `FROM_WORKTREE=True`·`PORT_8010_BUSY=False`가 출력된 뒤 `Uvicorn running on http://127.0.0.1:8010`이 나오면 성공이다.

### 블록 4 — 창③ [정적 서버 — 점유]

**이 창도 블록을 붙여넣은 뒤 서버가 점유한다. 이후 조작 금지.**

```powershell
# [창③ 정적 서버 — 이 창은 서버가 점유합니다. 붙여넣은 뒤 조작 금지]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out = Join-Path $Wt "src\web\webapp\out"
$OutOk = Test-Path (Join-Path $Out "admin\index.html")
$PortBusy = [bool](Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue)
"OUT_ADMIN=$OutOk"
"PORT_3001_BUSY=$PortBusy"
if ($OutOk -and (-not $PortBusy)) { & $Py -m http.server 3001 --bind 127.0.0.1 --directory $Out } else { "SERVER_REFUSED=True — OUT_ADMIN=False면 블록 2 재실행, PORT_3001_BUSY=True면 점유 프로세스 정리" }
```

판정: `Serving HTTP on 127.0.0.1 port 3001`이 나오면 성공이다.

## 4. 확인 (창① + 브라우저)

### 블록 5 — 창① [자가검증]: 세 서버 상태를 기계로 확인

창②·창③이 아니라 **창①**에 붙여넣는다. `curl.exe`는 Windows 10 이상에 기본 포함돼 있다(PowerShell의 `curl` 별칭과 다르다).

```powershell
# [창① 자가검증] Windows PowerShell — Phaiakes9
$Allowed = curl.exe -s -o NUL -w "%{http_code}" -X OPTIONS http://127.0.0.1:8010/v1/admin/menu -H "Origin: http://127.0.0.1:3001" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization"
$Denied = curl.exe -s -o NUL -w "%{http_code}" -X OPTIONS http://127.0.0.1:8010/v1/admin/menu -H "Origin: http://localhost:3001" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization"
$Static = curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:3001/admin/
"PREFLIGHT_ALLOWED=$Allowed (기대 200)"
"PREFLIGHT_DENIED=$Denied (기대 400)"
"STATIC_ADMIN=$Static (기대 200)"
```

판정: 세 값이 모두 기대값이면 브라우저 확인으로 간다. 어느 값이 `000`이면 해당 서버(8010=창②, 3001=창③)가 떠 있지 않은 것이다. 이 검사는 실패 상태에서 실제로 다른 값을 낸다 — 서버가 없으면 `000`, CORS 허용 목록이 비었으면 허용 쪽도 `400`.

### 브라우저 A-1 — 허용 origin

1. Chrome(또는 Edge)에서 `http://127.0.0.1:3001/admin/` 을 연다.
2. 「운영자 인증」 칸에 `not-a-real-token` 을 넣고 「콘솔 열기」를 누른다.
3. **기대**: 본문 제목 「**토큰이 유효하지 않습니다 (401)**」.
4. F12 → Network 탭에서 `menu` 요청의 Status가 `401`인 것을 확인한다.

### 브라우저 A-2 — 비허용 origin

1. **같은 브라우저의 새 탭**에서 `http://localhost:3001/admin/` 을 연다(주소만 다르고 같은 파일이다).
2. 같은 가짜 토큰을 넣고 「콘솔 열기」.
3. **기대**: 본문 제목 「**백엔드에 닿지 못했습니다**」, 설명에 `실패 종류: TypeError`.
4. F12 → Console 탭에 `has been blocked by CORS policy` 문구가 보인다.

A-2에서 페이지 자체가 안 열리면(연결 거부), `localhost`가 IPv6로만 해석되는 환경이다. 이 경우 A-2 브라우저 확인은 건너뛰고 블록 5의 `PREFLIGHT_DENIED=400`을 비허용 축 증적으로 쓴다 — 회신에 그렇게 적는다.

### 회신할 내용

- 블록 1의 `WORKTREE_HEAD=` 줄
- 블록 2의 `BUILD_EXIT=`·`OUT_ADMIN=` 줄
- 블록 5의 세 줄
- A-1·A-2 각각 화면에 뜬 제목 한 줄(가능하면 스크린샷)

세션이 이 내용을 게이트 notes에 **A 단계 부분 증적**으로 기록한다. 게이트는 §5(B 단계)까지 끝난 뒤 clear한다.

## 5. B 단계 — 200 + 내비 렌더 (`ADMIN-15` 착지 후 실행 가능)

A 단계와 **따로** 실행한다(A의 블록 6이 worktree를 지웠으므로 준비부터 다시 한다). 새로 필요한 것은 세 가지다.

- **운영자 토큰** — `ops/operator_token_cli.py`(ADMIN-15)가 content_admin 계정에 단기 토큰(기본 30분·상한 60분)을 발급하고, 발급마다 `privacy_audit`에 `operator_token_issued` 1행(누가·누구에게·언제·만료)을 남긴다. 데모 계정·content_admin이 아닌 계정·없는 계정은 exit 1로 거부한다.
- **스키마 업그레이드** — 위 감사 행이 쓰는 컬럼 2개(`token_expires_at`·`issued_by`)가 마이그레이션 `8c19e8a611e4`로 추가됐다. `whymath-pg`에 적용돼 있지 않으면 CLI가 빠진 컬럼 이름을 적고 exit 1로 거부한다. 그래서 블록 B2가 **백업 후 `alembic upgrade head`**를 한다(이 런북에서 유일한 DB 쓰기).
- **같은 JWT 시크릿** — 토큰은 창②의 서버와 같은 `WHYMATH_JWT_SECRET_KEY`로 서명돼야 한다. 그래서 토큰 발급을 **창② 안에서** 서버 기동 직전에 하고, 토큰은 화면에 찍지 않고 **클립보드**로만 넘긴다.

> 실측(2026-09-25 컨테이너, 로컬 PG16): `account_bootstrap_cli create` → `role_grant_cli grant … content_admin` → `operator_token_cli issue … --ttl-minutes 30` exit 0 → 그 토큰으로 `GET /v1/admin/menu` **HTTP 200**, 섹션이 채워진 응답 · `--ttl-minutes 90`은 exit 2로 거부. 통합 테스트 `tests/backend/ops/test_operator_token_cli_integration.py` 5건(메뉴 200 + sections 비어 있지 않음 · 무토큰 401 대조 · 감사 1행 · 거부 3종 감사 0)이 같은 흐름을 동결한다.

### B0 — 창① [준비·빌드]: §2의 블록 1·2를 그대로 다시 실행

블록 1의 `WORKTREE_HEAD`가 **ADMIN-15 머지 커밋 이후**여야 한다(B1의 `HAS_TOKEN_CLI=True`가 그것을 확인한다). `BUILD_EXIT=0`·`OUT_ADMIN=True`까지 확인한 뒤 B1로 간다.

### B1 — 창① [DB 상태 확인 — 읽기 전용]

선행 조건: Docker Desktop 가동, `whymath-pg` 컨테이너 실행 중.

```powershell
# [창① B1 DB 상태 확인 — 읽기 전용] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
"HAS_TOKEN_CLI=" + (Test-Path (Join-Path $Wt "src\backend\whymath_backend\ops\operator_token_cli.py"))
"PG_RUNNING=" + [bool](docker ps --filter "name=^whymath-pg$" --format "{{.Names}}")
cd (Join-Path $Wt "src\backend")
& $Py -m alembic current
"CURRENT_EXIT=$LASTEXITCODE"
& $Py -m alembic heads
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Admins = @(docker exec whymath-pg psql -U whymath -d whymath -tAc "select user_id from user_profile where role::text='content_admin'" | Where-Object { $_ -match '^[0-9a-f-]{36}$' })
"CONTENT_ADMIN_COUNT=" + $Admins.Count
```

판정: `HAS_TOKEN_CLI=True`·`PG_RUNNING=True`·`CURRENT_EXIT=0`·`CONTENT_ADMIN_COUNT=1`. `alembic heads`는 `8c19e8a611e4 (head)`(또는 그 이후)를 낸다. `alembic current`가 이미 같은 값이면 B2를 건너뛰어도 된다. content_admin 계정은 **정확히 1개**여야 한다(B3가 그 1개를 자동으로 고른다 — 0개나 2개 이상이면 B3가 거부한다). 계정 조회는 읽기 전용 `select` 한 줄이다.

### B2 — 창① [백업 + 스키마 업그레이드 — 쓰기]

B1의 판정값을 눈으로 확인한 다음에 붙여넣는다. 이 블록은 조건(worktree 코드·컨테이너 가동·CLI 실재)을 **스스로 다시 검사해** 하나라도 어긋나면 아무것도 쓰지 않는다. 백업이 실패하면 업그레이드도 하지 않는다. 백업 파일은 저장소 밖 `C:\Users\kiki\whymath_backups`에 남는다(PowerShell `>`로 받으면 바이너리 덤프가 깨지므로 컨테이너 안에서 파일로 만든 뒤 `docker cp`로 꺼낸다).

```powershell
# [창① B2 백업 + alembic upgrade head — 쓰기] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$CliFile = (& $Py -c "import whymath_backend.ops.operator_token_cli as m; print(m.__file__)")
$FromWt = ($CliFile -eq (Join-Path $Wt "src\backend\whymath_backend\ops\operator_token_cli.py"))
$PgUp = [bool](docker ps --filter "name=^whymath-pg$" --format "{{.Names}}")
$BackupDir = Join-Path $env:USERPROFILE "whymath_backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$Dump = "whymath_before_admin15_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".dump"
"FROM_WORKTREE=$FromWt"
"PG_RUNNING=$PgUp"
if ($FromWt -and $PgUp) { docker exec whymath-pg pg_dump -U whymath -Fc -f "/tmp/$Dump" whymath; $DumpExit = $LASTEXITCODE; docker cp "whymath-pg:/tmp/$Dump" (Join-Path $BackupDir $Dump); $CpExit = $LASTEXITCODE; $DumpSize = if (Test-Path (Join-Path $BackupDir $Dump)) { (Get-Item (Join-Path $BackupDir $Dump)).Length } else { 0 }; "DUMP_EXIT=$DumpExit"; "CP_EXIT=$CpExit"; "DUMP_BYTES=$DumpSize"; if (($DumpExit -eq 0) -and ($CpExit -eq 0) -and ($DumpSize -gt 0)) { cd (Join-Path $Wt "src\backend"); & $Py -m alembic upgrade head; "UPGRADE_EXIT=$LASTEXITCODE"; & $Py -m alembic current; cd C:\Users\kiki\Desktop\__AI\WhyMath } else { "UPGRADE_REFUSED=True — 백업 실패(DUMP_EXIT·CP_EXIT·DUMP_BYTES 확인). DB는 바뀌지 않았다" } } else { "WRITE_REFUSED=True — FROM_WORKTREE=$FromWt PG_RUNNING=$PgUp. False인 쪽을 해결한 뒤 B1부터 다시" }
```

판정: `DUMP_EXIT=0`·`CP_EXIT=0`·`DUMP_BYTES`가 0보다 큼 → `UPGRADE_EXIT=0` → 마지막 `alembic current`가 `8c19e8a611e4 (head)`(또는 그 이후). 거부 줄(`WRITE_REFUSED`·`UPGRADE_REFUSED`)이 보이면 DB는 바뀌지 않은 것이다.

### B3 — 창② [토큰 발급 + 백엔드 — 점유]

**이 창은 블록을 붙여넣은 뒤 서버가 점유한다. 이후 조작 금지. Ctrl+C는 서버 중단 신호다.**

A 단계 블록 3과 다른 점: ①서버가 `whymath-pg`를 본다(계정 조회) ②서버를 띄우기 직전에 **같은 셸·같은 시크릿**으로 토큰을 발급해 클립보드에 넣는다 ③content_admin 계정을 DB 읽기 조회로 스스로 찾는다(정확히 1개가 아니면 거부). 토큰 발급은 감사 1행을 쓰므로 가드 안에서만 한다.

```powershell
# [창② B3 토큰 발급 + 백엔드 — 이 창은 서버가 점유합니다. 붙여넣은 뒤 조작 금지]
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:WHYMATH_CORS_ALLOWED_ORIGINS = "http://127.0.0.1:3001"
$env:WHYMATH_JWT_SECRET_KEY = (& $Py -c "import secrets;print(secrets.token_urlsafe(48))")
$AppFile = (& $Py -c "import whymath_backend.app as a; print(a.__file__)")
$FromWt = ($AppFile -eq (Join-Path $Wt "src\backend\whymath_backend\app.py"))
$PortBusy = [bool](Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
$Admins = @(docker exec whymath-pg psql -U whymath -d whymath -tAc "select user_id from user_profile where role::text='content_admin'" | Where-Object { $_ -match '^[0-9a-f-]{36}$' })
"FROM_WORKTREE=$FromWt"
"PORT_8010_BUSY=$PortBusy"
"CONTENT_ADMIN_COUNT=" + $Admins.Count
if ($FromWt -and (-not $PortBusy) -and ($Admins.Count -eq 1)) { $Issued = (& $Py -m whymath_backend.ops.operator_token_cli issue $Admins[0] --ttl-minutes 30 | ConvertFrom-Json); "ISSUE_EXIT=$LASTEXITCODE"; "TOKEN_LENGTH=" + "$($Issued.access_token)".Length; "EXPIRES_AT=$($Issued.expires_at)"; if ("$($Issued.access_token)".Length -gt 0) { Set-Clipboard -Value $Issued.access_token; "TOKEN_IN_CLIPBOARD=True"; & $Py -m uvicorn whymath_backend.app:create_app --factory --host 127.0.0.1 --port 8010 } else { "SERVER_REFUSED=True — 토큰 발급 실패. 위 stderr의 error 사유 확인(스키마 미적용이면 B2)" } } else { "WRITE_REFUSED=True — FROM_WORKTREE=$FromWt PORT_8010_BUSY=$PortBusy CONTENT_ADMIN_COUNT=$($Admins.Count). CONTENT_ADMIN_COUNT가 1이 아니면 B1의 계정 조회 결과 확인" }
```

판정: `ISSUE_EXIT=0`·`TOKEN_LENGTH`가 0보다 큼·`TOKEN_IN_CLIPBOARD=True` → `Uvicorn running on http://127.0.0.1:8010`. 토큰 값 자체는 화면에 찍지 않는다. **만료(`EXPIRES_AT`, 30분) 전에** 브라우저 확인을 끝낸다 — 지나면 이 블록을 새 창에서 다시 실행한다(서버를 다시 띄우면 시크릿이 바뀌어 이전 토큰은 무효다).

### B4 — 창③ [정적 서버]: §3의 블록 4를 그대로 실행

### 브라우저 B-1 — 허용 origin + 실 토큰

1. Chrome에서 `http://127.0.0.1:3001/admin/` 을 연다(A 단계에서 연 탭이면 로그아웃 후 새로고침).
2. 「운영자 인증」 칸에 **Ctrl+V**(클립보드의 토큰)를 붙이고 「콘솔 열기」.
3. **기대**: 왼쪽에 서버가 준 메뉴 섹션이 그려진다(예: 「시스템 설정·권한(기능 플래그·RBAC)」 · 「앱·다과목 관리」 — `planned` 항목은 회색 「준비 중」으로 보이고 눌리지 않는다).
4. F12 → Network 탭에서 `menu` 요청의 Status가 **`200`**.

실패 시 대처: 「이 계정으로는 콘솔을 열 수 없습니다 (403)」이면 토큰 대상이 데모 계정이다(발급 CLI가 먼저 거부했어야 하므로 B3 출력 전문을 회신) · 「토큰이 유효하지 않습니다 (401)」이면 토큰과 서버의 시크릿이 다르거나 만료다(B3를 새 창에서 다시).

### B 단계 회신할 내용

- B1의 `HAS_TOKEN_CLI`·`PG_RUNNING`·`CURRENT_EXIT`·`CONTENT_ADMIN_COUNT` 줄과 `alembic current` 출력
- B2의 `DUMP_EXIT`·`CP_EXIT`·`DUMP_BYTES`·`UPGRADE_EXIT` 줄과 마지막 `alembic current` 출력(건너뛰었으면 그 사실)
- B3의 `CONTENT_ADMIN_COUNT`·`ISSUE_EXIT`·`TOKEN_LENGTH`·`EXPIRES_AT` 줄(**토큰 값은 보내지 않는다**)
- B-1 화면의 왼쪽 메뉴 섹션 이름들과 Network `menu` 상태 코드(가능하면 스크린샷)

세션이 A·B 결과를 증적으로 게이트를 clear한다. 정리는 §6과 같다(백업 파일은 남겨 둔다).

## 6. 정리

창②와 창③에서 **이제** Ctrl+C로 서버를 끈다. 그다음 창①에 붙여넣는다.

```powershell
# [창① 정리] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = Join-Path $env:TEMP "whymath-g-admin06"
if (Test-Path $Wt) { git worktree remove --force $Wt }
git worktree prune
"WORKTREE_LEFT=" + (Test-Path $Wt)
"PORT_8010_BUSY=" + [bool](Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue)
"PORT_3001_BUSY=" + [bool](Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue)
```

판정: 세 값이 모두 `False`면 정리 완료. 원 작업 사본(`C:\Users\kiki\Desktop\__AI\WhyMath`)의 브랜치·미커밋 변경은 이 런북 전체에서 한 번도 바뀌지 않았다.

## 7. 한계 (명시)

- 이 런북의 PowerShell 블록은 **Windows에서 실행 검증되지 않았다.** 같은 절차의 Linux 등가물(admin 빌드 → uvicorn → 정적 서버 → Chromium 두 origin)을 컨테이너에서 실측했고, worktree 코드가 PYTHONPATH로 editable 설치를 이기는 것도 컨테이너에서 확인했다. PowerShell 고유 부분(`npm.cmd`·`Get-NetTCPConnection`·`curl.exe`)은 표준 동작 기준이며, 각 블록에 판정 줄을 넣어 어긋나면 그 자리에서 보이게 했다.
- A 단계는 **CORS 축만** 증명한다. 셸이 실 토큰으로 내비를 그리는지는 B 단계가 증명한다.
