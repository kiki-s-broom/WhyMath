# 작업 그래프 데스크톱 앱 — Windows 설치·실행·확인 런북 (HARN-206 · HARN-208)

> 대상: Kiki · 머신: Phaiakes9(Windows) · 앱 소스: `tools/work-graph-desktop/` · 앱 설명: `tools/work-graph-desktop/README.md`
>
> **HARN-208부터 앱은 보통 Windows 프로그램처럼 켠다** — 설치 파일을 두 번 클릭해 설치하고, 바탕화면 아이콘이나 시작 메뉴로 연다.
> PowerShell·Node·npm은 필요 없다. 아래 PowerShell 블록은 설치가 제대로 됐는지 **스스로 판정하는 선택 검사**다.
> 소스에서 직접 빌드하는 절차는 맨 아래 「부록」에 있다(Node 22 필요).

## 사전 브리핑 (6항목)

1. **과제 명칭** — `WhyMath 작업 지도` 설치 → 첫 실행 → 창 수 확인 → (선택) 제거.
2. **목적** — HARN-208 acceptance ①(두 번 클릭 실행 · 바탕화면·시작 메뉴 바로가기 · 무설치 EXE)·②(저장소 자동 연결)를 실물 Windows에서
   판정한다. 결과(판정 줄 값)는 태스크 증적과 MEMORY 결정 로그에 들어간다.
3. **구체적 절차** — [A] 설치 파일을 받아 두 번 클릭(1~2분) → [B] 앱이 뜨면 왼쪽 레일의 `WhyMath`를 확인하고 「새로고침」(30초~2분) →
   [C] 설치 결과 검사 블록(선택 · 10초) → [D] 창 수 검사 블록(선택 · 10초) → [E] 무설치 EXE(선택) → [F] 제거(선택).
4. **성공 기준** — [B]에서 왼쪽 레일에 `WhyMath`가 **이미 연결돼** 있고, 「새로고침」 뒤 캔버스에 창(카드)이 그려진다. 검사 블록을 돌리면
   `INSTALL_OK=True`·`APP_OK=True`. 실패하면 각 절 아래 「실패하면」의 대처 1개를 따른다.
5. **실행 환경** — Phaiakes9 · 설치·실행은 탐색기(마우스) · 검사 블록은 Windows PowerShell(기본 환경 · 진입 명령 불요) ·
   앱이 찾는 저장소 `C:\Users\kiki\Desktop\__AI\WhyMath` · 선행 조건: Python 3 + PyYAML(앱이 저장소 `.venv` →
   `src\backend\.venv` → `python3` → `python` → `py -3` 순으로 **PyYAML을 임포트할 수 있는** 첫 파이썬을 고른다) · Git.
6. **창 구분** — 앱은 자기 창(GUI)으로 뜬다. 검사 블록은 **새 PowerShell 창(창 A)** 하나에서 차례로 붙여넣는다. 앱은 서버가 아니라서
   창 A를 점유하지 않는다 — 앱을 켜 둔 채로 검사 블록을 붙여넣어도 된다.

## [A] 설치 — 명령 없음

1. **설치 파일 받기** — 둘 중 하나.
   - Claude 앱 대화에 첨부된 `whymath-work-graph-desktop-0.1.0-setup.exe`를 내려받는다.
   - 또는 GitHub 저장소 → Actions → `work-graph-desktop` 워크플로의 최근 성공 실행 → 아래 Artifacts의 `work-graph-desktop-windows`를
     내려받아 압축을 푼다(실물 Windows 러너가 빌드하고 **패키징된 EXE를 직접 띄워 검사한** 산출물이다).
2. **두 번 클릭** — `whymath-work-graph-desktop-0.1.0-setup.exe`.
   - 「Windows의 PC 보호」 파란 창이 뜨면 「추가 정보」 → 「실행」. 코드서명 인증서가 없어서 뜨는 경고다(파일 자체의 문제가 아니다).
3. **설치 마법사** — 「현재 사용자만」(기본값) → 설치 폴더 기본값 그대로 「설치」 → 마지막 화면의 「WhyMath 작업 지도 실행」 체크를
   그대로 두고 「마침」. 앱이 바로 뜬다. 바탕화면과 시작 메뉴에 `WhyMath 작업 지도` 아이콘(짙은 사각형 위 청록·호박색 점 그래프)이 생긴다.

- 실패하면: 「추가 정보」 링크가 안 보이면 파일 속성 → 일반 탭 아래 「차단 해제」를 체크하고 다시 두 번 클릭한다.

## [B] 첫 실행 — 앱 안에서

1. 왼쪽 레일 「작업공간」에 `WhyMath`가 **이미 있으면 성공**이다 — 앱이 바탕화면의 `__AI\WhyMath`를 스스로 찾아 연결했다.
2. 오른쪽 위 「새로고침」을 누른다. 버튼이 「수집 중…」이 됐다가 돌아오면 캔버스에 창(카드)이 그려지고, 상태 줄 맨 앞에 `기준: 최신 main <해시 8자리> · 원격에서 받음 <시각>`, 뒤에 `work_graph.py ok · git ok`가 보인다(HARN-306). 새로고침은 매번 `git fetch origin`으로 원격의 최신 main을 받아 앱 전용 폴더(`%APPDATA%\whymath-work-graph-desktop\trunk\`)에서 그린다 — 이 PC 저장소 폴더의 브랜치·미커밋 변경은 건드리지 않고, 그 폴더가 다른 세션의 낡은 브랜치에 있어도 그래프는 최신 main이다. 첫 새로고침은 거울 폴더를 만드느라 30초~2분, 이후는 수 초~수십 초. 원격을 못 받으면 「확인 필요」에 `[fetch]` 사유가 뜨고 마지막으로 받은 main으로 그린다. 원격 조회(다른 세션의 claim·미머지 완료분·고립 브랜치)도 기본으로 켜져 있다. 저장소 폴더의 지금 상태를 보고 싶으면 「연결 및 설정」의 「그릴 대상」을 「작업 트리」로 바꾼다.
3. 다음부터는 바탕화면 아이콘이나 시작 메뉴로 켠다. 이미 켜져 있을 때 아이콘을 또 누르면 새 창 대신 **켜져 있던 창이 앞으로** 나온다.
   창 크기·위치는 닫을 때 기억했다가 다음에 그대로 연다.

- 실패하면(①): 가운데에 「WhyMath 저장소를 연결하세요」 안내가 뜨면 자동 찾기가 실패한 것이다. 「WhyMath 폴더 선택…」을 눌러
  `C:\Users\kiki\Desktop\__AI\WhyMath`를 고른다(한 번만 하면 된다). 「찾아본 자리」를 펼치면 앱이 어디를 봤고 왜 아니었는지 나온다 —
  그 목록을 인용해 보내 주시면 원인을 고친다. 저장소가 아닌 폴더를 고르면 거부 사유가 빨간 글씨로 나오고 아무것도 저장되지 않는다.
- 실패하면(②): 상태 줄이 `work_graph.py missing_tool`이면 PyYAML이 있는 파이썬을 못 찾은 것이다 — 「연결 및 설정」의 python 칸에
  `C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe`를 넣고 「저장」 뒤 다시 「새로고침」.

## [C] 설치 결과 검사 (선택)

바로가기 2곳·설치된 실행 파일·자동 연결된 작업공간을 한 번에 본다.

```powershell
# Windows PowerShell — 창 A (새 창)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Desk = [Environment]::GetFolderPath("Desktop")
$DeskLnk = Test-Path (Join-Path $Desk "WhyMath 작업 지도.lnk")
$MenuLnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter "WhyMath 작업 지도.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMathWorkGraph.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$SettingsFile = Join-Path $env:APPDATA "whymath-work-graph-desktop\settings.json"
$Roots = if (Test-Path $SettingsFile) { @((Get-Content -Raw -Encoding utf8 $SettingsFile | ConvertFrom-Json).workspaces | ForEach-Object { $_.root }) } else { @() }
$Connected = @($Roots | Where-Object { $_ -ieq "C:\Users\kiki\Desktop\__AI\WhyMath" }).Count -gt 0
"DESKTOP_SHORTCUT=$DeskLnk"
"START_MENU_SHORTCUT=$($null -ne $MenuLnk)"
"EXE=$($Exe.FullName)"
"WORKSPACES=$($Roots -join '; ')"
"INSTALL_OK=$($DeskLnk -and ($null -ne $MenuLnk) -and ($null -ne $Exe) -and $Connected)"
```

- 실패하면: `WORKSPACES`가 비어 있으면 앱을 아직 한 번도 켜지 않았거나 [B]의 첫 화면에서 폴더를 고르지 않은 것이다 — 앱을 켜고 [B]를
  마친 뒤 블록을 다시 붙여넣는다. `EXE`만 비어 있으면 설치 폴더를 바꾼 경우라 그 경로를 알려 주시면 된다.

## [D] 창 수 검사 (선택)

[B]에서 「새로고침」을 한 번 누른 뒤 붙여넣는다(앱은 켜 둬도 된다). 화면 도구 줄의 「창 N」과 `WINDOW_COUNT`가 같아야 한다.

```powershell
# Windows PowerShell — 창 A
cd C:\Users\kiki\Desktop\__AI\WhyMath
$SnapDir = Join-Path $env:APPDATA "whymath-work-graph-desktop\snapshots"
$Snap = Get-ChildItem $SnapDir -Filter "ws_*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -ne $Snap) {
  $Data = Get-Content -Raw -Encoding utf8 $Snap.FullName | ConvertFrom-Json
  $Nodes = @($Data.payload.nodes.PSObject.Properties).Count
  "SNAPSHOT=$($Snap.FullName) COLLECTED_AT=$($Data.collectedAt) HARNESS=$($Data.sources.harness.status) GIT=$($Data.sources.git.status)"
  "WINDOW_COUNT=$Nodes"
  "APP_OK=$(($Data.sources.harness.status -eq 'ok') -and ($Nodes -gt 0))"
} else { "APP_OK=False — $SnapDir 에 스냅샷이 없다(새로고침을 누르지 않았거나 수집이 실패했다 · 앱의 '확인 필요' 카드 사유를 인용)" }
```

- 실패하면: `HARNESS=missing_tool`이면 [B]의 「실패하면(②)」, `HARNESS=error`면 「확인 필요」 카드의 사유(예외 타입명과 stderr 첫 줄)를 인용.

## [E] 무설치 EXE (선택)

`whymath-work-graph-desktop-0.1.0-portable.exe`는 설치 없이 두 번 클릭으로 뜬다. 켤 때마다 임시 폴더에 풀기 때문에 설치본보다
3~5초 늦게 뜬다. 설정·스냅샷은 설치본과 같은 `%APPDATA%\whymath-work-graph-desktop`을 쓰므로 둘을 번갈아 써도 작업공간이 이어진다.
이 파일을 `C:\Users\kiki\Desktop\__AI\WhyMath` 안 어디에 두어도(네 단계 이내) 그 저장소를 스스로 찾는다.

## [F] 제거 (선택)

「설정 → 앱 → 설치된 앱」에서 `WhyMath 작업 지도` → 「제거」. 제거 뒤 확인:

```powershell
# Windows PowerShell — 창 A
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Desk = [Environment]::GetFolderPath("Desktop")
$DeskLnk = Test-Path (Join-Path $Desk "WhyMath 작업 지도.lnk")
$MenuLnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter "WhyMath 작업 지도.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMathWorkGraph.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
"REMOVE_OK=$((-not $DeskLnk) -and ($null -eq $MenuLnk) -and ($null -eq $Exe))"
```

- 참고: 앱 데이터(`%APPDATA%\whymath-work-graph-desktop\` — 작업공간 목록·스냅샷·창 자리·메모)는 제거해도 남는다(다음 설치에서
  그대로 쓴다). 완전히 지우려면 그 폴더를 손으로 지운다.

## 결과 보고 형식

[B]에서 왼쪽 레일에 `WhyMath`가 저절로 있었는지(예/아니오 — 아니오면 「찾아본 자리」 목록), 화면의 「창 N · 연결선 M」, 그리고 검사 블록을
돌렸다면 판정 줄(`INSTALL_OK`·`APP_OK`·`WINDOW_COUNT`)을 인용문으로 보내 주시면 세션이 증적에 옮긴다.

## 부록 — 소스에서 직접 빌드 (Node 22 필요)

설치 파일을 받을 수 없을 때만 쓴다. 여러 세션이 함께 쓰는 작업 사본(`C:\Users\kiki\Desktop\__AI\WhyMath`)의 브랜치·미커밋 변경을
건드리지 않도록 **임시 worktree**(`%TEMP%\whymath-wg-build`)에 main을 꺼내 그 안에서 빌드한다.

```powershell
# Windows PowerShell — 창 A
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = Join-Path $env:TEMP "whymath-wg-build"
if (Test-Path $Wt) { git worktree remove --force $Wt }
git worktree add --detach $Wt origin/main
$Head = (git -C $Wt rev-parse HEAD).Trim()
$Main = (git rev-parse origin/main).Trim()
"WORKTREE=$Wt HEAD=$Head"
"WORKTREE_OK=$(($Head -eq $Main) -and (Test-Path (Join-Path $Wt "tools\work-graph-desktop\package.json")))"
```

위 블록의 `WORKTREE_OK=True`를 눈으로 확인한 다음에만 아래 빌드 블록을 붙여넣는다(첫 회 5~10분 · Electron 바이너리를 내려받는다).

```powershell
# Windows PowerShell — 창 A
cd C:\Users\kiki\Desktop\__AI\WhyMath
$App = Join-Path $env:TEMP "whymath-wg-build\tools\work-graph-desktop"
if (Test-Path (Join-Path $App "package.json")) {
  Push-Location $App
  node --version
  npm.cmd ci --no-audit --no-fund
  $CiExit = $LASTEXITCODE
  npm.cmd run dist:win
  $DistExit = $LASTEXITCODE
  Get-ChildItem .\release -File | Select-Object Name, Length
  $SetupOk = Test-Path .\release\whymath-work-graph-desktop-0.1.0-setup.exe
  Pop-Location
  "CI_EXIT=$CiExit DIST_EXIT=$DistExit RELEASE=$App\release"
  "BUILD_OK=$(($CiExit -eq 0) -and ($DistExit -eq 0) -and $SetupOk)"
} else { "BUILD_OK=False — $App 가 없다(위 worktree 블록의 WORKTREE_OK부터 확인)" }
```

- 성공하면 `RELEASE` 폴더의 `whymath-work-graph-desktop-0.1.0-setup.exe`를 두 번 클릭해 [A]의 3단계부터 이어 간다.
- 실패하면: `CI_EXIT`가 0이 아니면 Node 22가 아닌 경우가 대부분이다(`node --version` 출력을 인용). `DIST_EXIT`가 0이 아니면 마지막
  20줄을 인용 — 흔한 원인은 Electron 바이너리 내려받기 실패(프록시)·`release\` 폴더의 열린 파일 잠금(앱이 켜져 있음).
- 정리: 다 쓴 뒤 `git worktree remove --force $env:TEMP\whymath-wg-build`(원 작업 사본에는 영향 없음).

## 검증 (컨테이너 실측 · 2026-09-30 · HARN-208)

판정 기준: 브랜치 `claude/focused-ramanujan-2p5q8w` 작업 트리(main `270968a2` 위) · 컨테이너 Linux · Node v22.22.2 · Electron 38.2.1 ·
electron-builder 26.15.3 · @playwright/test 1.56.1 · vitest 3.2.7 · wine 9.0(교차 빌드의 아이콘 편집용).

| 검사 | exit | 결과 |
|---|---|---|
| 타입 검사(main·preload·tests / renderer) | 0 | 오류 0 |
| 단위 테스트 `npx vitest run` | 0 | 6 파일 · **70 passed** |
| 렌더러 화면 계약 `npx playwright test --project renderer` | 0 | **11 passed**(첫 실행 화면 1건 추가) |
| Electron 앱 흐름 `xvfb-run -a npx playwright test --project electron` | 0 | **6 passed · 1 skipped**(패키징 EXE 기동 — Windows CI 전용) |
| 패키징 EXE 기동 테스트를 리눅스 패키징본으로 | 0 | **1 passed**(asar 묶음 · `isPackaged=true` · 수집 ok) — 테스트 논리 확인용 |
| `npm run dist:win`(리눅스 교차 빌드) | 0 | 아래 표 |

| 파일 | 크기(바이트) | 비고 |
|---|---|---|
| `whymath-work-graph-desktop-0.1.0-setup.exe` | 87,014,607 | NSIS 설치 · 바탕화면·시작 메뉴 바로가기 · 설치 끝에 실행 |
| `whymath-work-graph-desktop-0.1.0-portable.exe` | 86,794,883 | 무설치 단일 EXE |
| `whymath-work-graph-desktop-0.1.0-win-x64.zip` | 121,871,862 | `win-unpacked/` 통째(실행 파일 `WhyMathWorkGraph.exe`) |

세 EXE 모두 아이콘 7개 크기(16~256)와 제품명(UTF-16)이 리소스에 들어간 것을 바이트로 확인했고, Authenticode 인증서 테이블 크기는 0(서명 없음 —
인증서 미제공)이다.

뮤테이션 11종 **전건 RED · 생존 0**(주입 1건 실재·`mutated != original` 단언 · 백업 복사 원복 sha256 동일 · 세션 스크래치 `t207/mut.py`):
앱 위치 조상 탐색 제거 · `requireHarness` 검사 제거 · 단일 인스턴스 잠금 무시 · 닫을 때 창 자리 저장 제거 · 파이썬 탐침을 `--version`으로 ·
첫 화면이 `requireHarness`를 안 보냄 · `fitBounds` 화면 검사 제거 · git 전용 폴더 자동 연결 · 연결 직후 자동 수집 제거 · 첫 실행 찾기 결과 무시 ·
데이터 폴더 영문 고정 제거.

**HARN-206 런북 정정**: 종전 [6] 창 수 검사 블록은 `%APPDATA%\whymath-work-graph-desktop\snapshots`를 봤는데, HARN-206 앱은 데이터 폴더를
지정하지 않아 Electron 기본값(`appData\<제품명>` — 한글이라 로캘에 따라 `WhyMath 작업 지도` 폴더 또는 appData 루트)을 썼다. 즉 그 블록은
수집이 성공해도 「스냅샷 없음」으로 판정했을 것이다. HARN-208이 데이터 폴더를 `whymath-work-graph-desktop`으로 고정해 코드와 런북을 일치시켰다
(회귀 테스트 「앱 데이터는 appData\whymath-work-graph-desktop에 모인다」).

**미검증(명시)**: 이 컨테이너에서 Windows EXE를 실행할 수 없다. 실물 Windows 판정은 두 곳에서 한다 — ① CI `work-graph-desktop` 워크플로의
windows 잡(같은 테스트 + 패키징된 EXE 기동 → 저장소 수집) ② 이 런북의 [A]~[D](설치 마법사·바로가기·SmartScreen·실제 바탕화면 자동 찾기).
