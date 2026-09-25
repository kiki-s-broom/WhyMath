# 게이트 `G-admin06-browser-menu-call` 실행 런북 — 백오피스 셸 실 브라우저 menu 호출 확인

> 작성: 2026-09-25 · 판정 기준: main `63451153`
> 대상 게이트: `G-admin06-browser-menu-call` (ADMIN-06 acceptance ②의 사람 축 · ADMIN-07 착수 선결)
> 이 런북은 **읽기 전용**이다 — DB 쓰기·대장 조작·배포가 없다. 서버 두 개를 잠깐 띄웠다가 끈다.

## 0. 먼저 알아 둘 것 — 이 게이트는 두 단계로 나뉜다

게이트 제목은 두 가지를 확인하라고 요구한다.

| 단계 | 확인 내용 | 지금 실행 가능? |
|---|---|---|
| **A. CORS 축** | 허용 origin에서는 브라우저가 서버 응답을 **받고**, 비허용 origin에서는 브라우저가 **차단한다** | ✅ 가능 (이 런북 §2~§4) |
| **B. 렌더 축** | 허용 origin에서 **200 + 좌측 내비 렌더** | ❌ **불가** — 실행 경로 공백 (§5) |

B가 불가한 이유: `GET /v1/admin/menu`는 **데모 계정이 아닌** 실 신원 토큰을 요구한다(`api/admin_menu.py` — 데모 계정 403). 저장소에서 액세스 토큰을 발급하는 경로는 OAuth 콜백(`api/auth.py`)과 데모 로그인 둘뿐이고, Kiki의 content_admin 계정(`account_bootstrap_cli`로 생성 — 게이트 `G-operator-seat-first-grant` 증적)에는 OAuth 로그인 이력이 없다. 이 공백은 태스크 **`ADMIN-15-operator-access-token-issuance`**로 등재했다. 그 태스크가 착지하면 §5를 채운다.

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

## 5. B 단계 — 200 + 내비 렌더 (현재 실행 불가 · `ADMIN-15` 대기)

필요한 것: Kiki의 content_admin 계정(`G-operator-seat-first-grant` 증적의 user_id)에 대한 **비데모 액세스 토큰**. 이 토큰은 창②의 서버와 **같은 `WHYMATH_JWT_SECRET_KEY`**로 서명돼야 하고, 서버는 `whymath-pg`(5433)에서 그 계정을 조회해야 한다.

`ADMIN-15`가 착지하면 이 절에 다음을 채운다: ①창②에 `WHYMATH_DATABASE_URL`(whymath-pg) 추가 ②토큰 발급 블록(창②와 같은 시크릿 공유 방식 포함) ③브라우저 B-1: 허용 origin에서 실 토큰 → 좌측 내비가 서버 레지스트리 섹션대로 렌더, Network `menu` 200.

OAuth(카카오·네이버) 실 로그인으로 토큰을 얻는 경로가 Phaiakes9에서 동작한다는 것이 실측되면, `ADMIN-15`는 취소하고 이 절을 그 경로로 채운다.

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
