# 작업 그래프 데스크톱 앱 — Windows 빌드·설치·확인 런북 (HARN-206)

> 대상: Kiki · 머신: Phaiakes9(Windows PowerShell) · 앱 소스: `tools/work-graph-desktop/` · 앱 설명: `tools/work-graph-desktop/README.md`
>
> **이 컨테이너(Linux)에서 검증된 것**: 단위 테스트 51건 · 렌더러 화면 계약 10건 · Electron 스모크 1건(xvfb) · `npm run dist:win`
> 산출물 생성(리눅스 크로스 빌드). **Windows에서는 미검증** — NSIS 설치 파일 실행·시작 메뉴 바로가기·앱 실행·제거는 아래
> 절차를 Kiki가 직접 밟아야 판정된다. 각 블록의 마지막 판정 줄이 `True`여야 다음 블록으로 간다.

## 사전 브리핑 (6항목)

1. **과제 명칭** — 작업 그래프 데스크톱 앱(`WhyMath 작업 지도`) Windows 설치형 빌드·설치·실행·제거 확인.
2. **목적** — HARN-206 acceptance ①(NSIS 설치 EXE + 무설치 zip)·⑥(Windows 설치·실행·제거는 런북으로 판정)을 채운다.
   결과(판정 줄 값)는 태스크 done 증적과 MEMORY 결정 로그에 들어간다.
3. **구체적 절차** — [1] 브랜치 체크아웃·자가검증(1분) → [2] 의존성 설치·Windows 빌드(첫 회 5~10분 · Electron 바이너리 내려받음) →
   [3] 산출물 존재 검사 → [4] 설치 파일 실행(설치 마법사 · 사용자별 설치 · 1분) → [5] 시작 메뉴 바로가기·설치 폴더 검사 →
   [6] 앱 실행 → 작업공간 추가 → 새로고침 → 창 수 확인(앱 안 조작 2분 + 검사 블록) → [7] 제거 → 제거 검사.
4. **성공 기준** — 블록 [1]~[7]의 판정 줄이 모두 `True`. `False`가 나오면 그 블록의 앞 출력을 인용문으로 보내 주시면 된다(실패 원인은
   각 블록 아래 「실패하면」에 1개씩 적어 두었다). 시작 메뉴 바로가기와 설치 폴더 이름은 블록이 스스로 찾으므로 손으로 고칠 값이 없다.
5. **실행 환경** — Phaiakes9 · Windows PowerShell(기본 환경 · 진입 명령 불요) · 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath` ·
   선행 조건: Node 22 + npm(`node --version`이 v22.x) · Git · Python 3(앱이 `python3`→`python`→`py -3` 순으로 찾는다) ·
   인터넷(첫 빌드가 Electron 38 Windows 바이너리와 NSIS를 내려받는다).
6. **창 구분** — 블록 [1]~[5]·[7]은 **같은 PowerShell 창(창 A)** 에서 차례로 붙여넣는다. 블록 [6]은 앱 창(GUI)을 띄우므로 앱 안 조작이
   끝난 뒤 **창 A로 돌아와** 검사 블록을 붙여넣는다. 앱은 서버가 아니라서 창 A를 점유하지 않는다.

## [1] 브랜치 체크아웃 + 자가검증

```powershell
# Windows PowerShell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/focused-ramanujan-2p5q8w
git checkout -B claude/focused-ramanujan-2p5q8w origin/claude/focused-ramanujan-2p5q8w
git log -1 --oneline
$Head = (git rev-parse HEAD).Trim()
$Remote = (git rev-parse origin/claude/focused-ramanujan-2p5q8w).Trim()
$HasApp = Test-Path .\tools\work-graph-desktop\package.json
"HEAD=$Head"
"BRANCH_OK=$(($Head -eq $Remote) -and $HasApp)"
```

- 실패하면: `BRANCH_OK=False`이면 `git status`를 인용해 보내 주시면 된다 — 타 세션의 미커밋 변경이 체크아웃을 막았거나(그 경우
  블록을 다시 붙여넣지 말고 알려 주시면 세션이 worktree 우회 명령을 드린다), 브랜치에 아직 앱 폴더가 없다(푸시 전).

## [2] 의존성 설치 + Windows 빌드

```powershell
# Windows PowerShell
cd C:\Users\kiki\Desktop\__AI\WhyMath\tools\work-graph-desktop
node --version
npm.cmd ci --no-audit --no-fund
$CiExit = $LASTEXITCODE
npm.cmd run dist:win
$DistExit = $LASTEXITCODE
"CI_EXIT=$CiExit DIST_EXIT=$DistExit"
"BUILD_OK=$(($CiExit -eq 0) -and ($DistExit -eq 0))"
```

- 실패하면: `CI_EXIT`가 0이 아니면 Node 22가 아닌 경우가 대부분이다(`node --version` 출력을 인용). `DIST_EXIT`가 0이 아니면 마지막
  20줄을 인용해 주시면 된다 — 흔한 원인은 Electron 바이너리 내려받기 실패(프록시)·`release\` 폴더의 열린 파일 잠금(이전 앱이 켜져 있음).
- 주의: 이 블록은 첫 회 5~10분 걸린다. 출력이 멈춘 것처럼 보여도 `building target=nsis` 줄 뒤에는 2~3분 조용하다.

## [3] 산출물 존재 검사

```powershell
# Windows PowerShell
cd C:\Users\kiki\Desktop\__AI\WhyMath\tools\work-graph-desktop
$Setup = ".\release\whymath-work-graph-desktop-0.1.0-setup.exe"
$Zip = ".\release\whymath-work-graph-desktop-0.1.0-win-x64.zip"
Get-ChildItem .\release -File | Select-Object Name, Length
$SetupOk = Test-Path $Setup
$ZipOk = Test-Path $Zip
"ARTIFACTS_OK=$($SetupOk -and $ZipOk)"
```

- 실패하면: 파일 이름이 다르면(버전을 올렸을 때) `Get-ChildItem` 출력의 이름을 인용해 주시면 된다. 리눅스 실측 이름은 아래 「검증」 절 참조.

## [4] 설치 파일 실행

```powershell
# Windows PowerShell
cd C:\Users\kiki\Desktop\__AI\WhyMath\tools\work-graph-desktop
Start-Process -FilePath (Resolve-Path ".\release\whymath-work-graph-desktop-0.1.0-setup.exe") -Wait
"INSTALLER_EXITED=True"
```

- 설치 마법사에서: SmartScreen 경고가 뜨면 「추가 정보 → 실행」(코드서명이 없다). 설치 유형은 **현재 사용자만**(기본값), 설치 폴더는 기본값
  그대로 「설치」. 마법사가 닫히면 이 블록이 끝난다(`INSTALLER_EXITED=True`는 마법사가 종료됐다는 뜻이고 설치 성공 판정은 [5]가 한다).

## [5] 설치 결과 검사 — 시작 메뉴 바로가기·설치 폴더

```powershell
# Windows PowerShell
$Lnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter "WhyMath 작업 지도.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMath 작업 지도.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
"SHORTCUT=$($Lnk.FullName)"
"EXE=$($Exe.FullName)"
"INSTALL_OK=$(($null -ne $Lnk) -and ($null -ne $Exe))"
```

- 실패하면: `EXE`만 비어 있으면 설치 폴더를 바꾼 경우다 — 바꾼 폴더 경로를 알려 주시면 된다. `SHORTCUT`만 비어 있으면 마법사에서 바로가기
  생성을 껐거나 시작 메뉴 갱신이 늦은 것이니 10초 뒤 블록을 다시 붙여넣는다.

## [6] 앱 실행 → 작업공간 추가 → 새로고침 → 창 수 확인

먼저 앱을 띄운다(환경변수로 저장소를 자동 등록하므로 「작업공간 추가」 대화상자는 생략된다 — 대화상자 경로도 함께 확인하려면
아래 「앱 안 조작」 2번을 따른다).

```powershell
# Windows PowerShell
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMath 작업 지도.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$env:WORK_GRAPH_WORKSPACE = "C:\Users\kiki\Desktop\__AI\WhyMath"
if ($null -ne $Exe) { Start-Process -FilePath $Exe.FullName; "APP_STARTED=True" } else { "APP_STARTED=False — 설치 폴더에서 실행 파일을 찾지 못했다(블록 [5] 확인)" }
```

앱 안 조작(GUI · 창 A는 그대로 둔다):
1. 왼쪽 레일 「작업공간」에 `WhyMath`가 보이는지 확인한다(환경변수 자동 등록). 상태 줄에는 「저장된 스냅샷 없음」이 보인다.
2. (선택) 레일의 「＋ 작업공간 추가」 → 「폴더 선택…」으로 같은 폴더를 골라 「추가」를 눌러 본다 — 같은 폴더는 중복 등록되지 않고
   기존 항목이 선택된다. `scripts/harness/work_graph.py`도 `.git`도 없는 폴더를 고르면 거부 사유가 대화상자에 나온다.
3. 오른쪽 위 「새로고침」을 누른다. 버튼이 「수집 중…」이 됐다가 돌아오면 상태 줄이 `저장된 스냅샷 · 수집 시각 · 원격 조회: 완료분 skipped ·
   claim skipped · 고립 skipped · work_graph.py ok · git ok · gh skipped`로 바뀐다(기본 설정은 `--no-remote`라 원격 조회 3종은 skipped이고,
   그 사실이 「확인 필요」 카드에 3건으로 잡힌다 — 은폐가 아니라 이 앱의 원칙이다).
4. 캔버스에 창(카드)이 그려지고, 도구 줄 오른쪽에 「창 N · 연결선 M」이 나온다. 창 하나를 눌러 오른쪽 상세가 열리는지, 「목록 보기」에서
   표가 나오는지 본다.
5. 앱을 닫는다.

앱을 닫은 뒤 창 A에서 스냅샷 파일로 창 수를 검사한다(화면의 N과 같아야 한다):

```powershell
# Windows PowerShell
$Snap = Get-ChildItem "$env:APPDATA\whymath-work-graph-desktop\snapshots" -Filter "ws_*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -ne $Snap) {
  $Data = Get-Content -Raw -Encoding utf8 $Snap.FullName | ConvertFrom-Json
  $Nodes = @($Data.payload.nodes.PSObject.Properties).Count
  "SNAPSHOT=$($Snap.FullName) COLLECTED_AT=$($Data.collectedAt) HARNESS=$($Data.sources.harness.status) GIT=$($Data.sources.git.status)"
  "WINDOW_COUNT=$Nodes"
  "APP_OK=$(($Data.sources.harness.status -eq 'ok') -and ($Nodes -gt 0))"
} else { "APP_OK=False — 스냅샷 파일이 없다(새로고침을 누르지 않았거나 수집이 실패했다 · 앱의 '확인 필요' 카드를 열어 사유를 인용)" }
```

- 실패하면: `HARNESS=missing_tool`이면 Python을 못 찾은 것 — 앱의 「연결 및 설정」에서 python 실행 파일 경로를 채우고 다시 새로고침한다.
  `HARNESS=error`면 「확인 필요」 카드의 사유(예외 타입명과 stderr 첫 줄)를 인용해 주시면 된다.

## [7] 제거 + 제거 검사

```powershell
# Windows PowerShell
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMath 작업 지도.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$Un = if ($null -ne $Exe) { Get-ChildItem $Exe.DirectoryName -Filter "Uninstall*.exe" | Select-Object -First 1 } else { $null }
if ($null -ne $Un) { Start-Process -FilePath $Un.FullName -Wait; "UNINSTALLER_EXITED=True" } else { "UNINSTALLER_EXITED=False — 제거 프로그램을 찾지 못했다(설정 > 앱에서 'WhyMath 작업 지도' 제거)" }
```

제거 마법사가 닫힌 뒤:

```powershell
# Windows PowerShell
$Lnk = Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" -Recurse -Filter "WhyMath 작업 지도.lnk" -ErrorAction SilentlyContinue | Select-Object -First 1
$Exe = Get-ChildItem "$env:LOCALAPPDATA\Programs" -Recurse -Filter "WhyMath 작업 지도.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
"REMOVE_OK=$(($null -eq $Lnk) -and ($null -eq $Exe))"
```

- 참고: 앱 데이터(`%APPDATA%\whymath-work-graph-desktop\` — 작업공간 목록·스냅샷·창 좌표·메모)는 제거해도 남는다(NSIS 기본 동작·
  다음 설치에서 그대로 쓴다). 완전히 지우려면 제거 마법사에서 「앱 데이터도 삭제」를 고르거나 그 폴더를 손으로 지운다.

## 결과 보고 형식

블록별 판정 줄 7개(`BRANCH_OK`·`BUILD_OK`·`ARTIFACTS_OK`·`INSTALLER_EXITED`·`INSTALL_OK`·`APP_OK`·`REMOVE_OK`)와 `WINDOW_COUNT`, 그리고 앱 화면에서 본
「창 N · 연결선 M」을 인용문으로 보내 주시면 세션이 `backlog.py done` 증적에 옮긴다.

## 검증 (컨테이너 실측 · 2026-09-29)

판정 기준: 브랜치 `claude/focused-ramanujan-2p5q8w` 작업 트리(main `a28a8d08` 위) · 컨테이너 Linux · Node v22.22.2 · npm 10.9.7 ·
Electron 38.2.1 · electron-builder 26.15.3 · @playwright/test 1.56.1(Chromium 1194 기설치본) · vitest 3.2.7 · Python 3.11.15.

| 검사 | 명령 | exit | 결과 |
|---|---|---|---|
| 타입 검사(main/preload/tests) | `npx tsc -p tsconfig.json --noEmit` | 0 | 오류 0 |
| 타입 검사(renderer) | `npx tsc -p tsconfig.renderer.json --noEmit` | 0 | 오류 0 |
| 번들 | `npm run build` | 0 | main 27.1kb · preload 1.3kb · renderer 742.0kb(픽스처 2개 포함) |
| 단위 테스트 | `npx vitest run` | 0 | 5 파일 · **51 passed / 0 failed** |
| 렌더러 화면 계약 | `npx playwright test --project renderer` | 0 | **10 passed / 0 failed** |
| Electron 스모크 | `xvfb-run -a npx playwright test --project electron` | 0 | **1 passed** — 창 제목 `WhyMath 작업 지도` · webPreferences {contextIsolation true, sandbox true, nodeIntegration false} · `WORK_GRAPH_WORKSPACE=/home/user/WhyMath` 자동 등록 · 새로고침(--no-remote) → work_graph.py ok · git ok · 창 수 > 0 · 확인 필요 3(원격 조회 skipped 3종) · userData에 settings.json + snapshots/ws_*.json 저장(저장된 페이로드 창 수 = 화면 창 수) |
| Windows 산출물 | `npm run dist:win` | 0 | 아래 표 |

`npm run dist:win` 산출물(리눅스 크로스 빌드 · `release/`):

| 파일 | 크기(바이트) | 비고 |
|---|---|---|
| `whymath-work-graph-desktop-0.1.0-setup.exe` | 87,006,597 | NSIS 설치 파일 · oneClick=false · perMachine=false · 설치 폴더 변경 허용 · 코드서명 없음 |
| `whymath-work-graph-desktop-0.1.0-setup.exe.blockmap` | 90,446 | electron-builder 차등 갱신 맵(사용 안 함) |
| `whymath-work-graph-desktop-0.1.0-win-x64.zip` | 121,862,966 | 무설치 zip(`win-unpacked/` 통째 · 실행 파일 `WhyMath 작업 지도.exe`) |
| `win-unpacked/resources/app.asar` | 2,006,082 | dist/ + fixtures/sample.json + package.json |

리눅스에서 NSIS 빌드가 된 이유: electron-builder 26이 내장 makensis(리눅스 바이너리)·7zip을 내려받아 쓴다. wine이 필요한 것은
실행 파일의 아이콘·메타데이터 편집과 서명뿐이라 `win.signAndEditExecutable: false` + `icon` 미지정으로 그 단계를 건너뛰었다(기본 Electron
아이콘 · exe 속성에 제품명 없음). Windows에서 빌드하면 같은 명령으로 아이콘·메타데이터가 들어간다.

뮤테이션 3종(별도 사본 `cp` 백업 → 주입이 실제로 적용됐는지 `mutated != original` 단언 → 검사 → `cp` 원복 → 바이트 동일 단언 · 하네스 =
세션 스크래치 `t203/mutate.py`):

| 뮤테이션 | 주입 위치 | 검사 | exit | RED 항목 |
|---|---|---|---|---|
| ⓐ 렌더러가 `state`를 자체 규칙으로 덮어씀(모든 창을 `ready`/「시작 가능」으로) | `src/renderer/canvas.ts` `winHtml` | `npm run build && playwright test --project renderer` | 1 | `창의 상태 라벨은 페이로드의 state/label 그대로다(앱 판정 없음)` |
| ⓑ 어댑터가 실패를 `ok` + 빈 페이로드로 접음 | `src/main/adapters/harness.ts` 비-ok 분기 | `vitest run` | 1 | `harnessAdapter > 타임아웃·오류·깨진 JSON은 각각 status로 남는다` |
| ⓒ main이 `backlog/tasks/<id>.yaml`을 직접 씀 | `src/main/actions.ts` `runAction` | `vitest run` | 1 | `파일 쓰기 식별자는 store/atomic.ts에만 있다` + `runAction > 인자를 배열 그대로 spawn에 넘기고…` |

세 건 모두 원복 뒤 바이트 동일(sha256 일치) · 원복 후 재실행: tsc 0 · vitest 51 passed · renderer e2e 10 passed.

**미검증(명시)**: Windows에서의 NSIS 설치 파일 실행·시작 메뉴 바로가기·앱 실행·`shell.openPath`(태스크 YAML 열기)·`dialog.showOpenDialog`
폴더 선택·제거 — 위 [1]~[7] 블록이 판정한다. gh 어댑터의 라이브 경로(gh 설치·인증 상태)는 가짜 exec로만 검증했다(컨테이너에 gh 없음 →
missing_tool 경로만 실물). 원격 조회 포함(`remote: true`) 수집은 컨테이너에서 돌리지 않았다(네트워크·시간).
