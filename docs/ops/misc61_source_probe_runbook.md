# MISC-61 ① 원천 대조 런북 — Kiki 머신에서 원천 JSON 키 진단 1회

> 대상 태스크: `MISC-61-a3-thin-misid-source-enrichment` acceptance ①
> 후속 게이트: `G-misc40-deferred-m0599-redecision` (이 런북은 판정을 내리지 않는다 — 재판정 재료만 만든다)
> 판정 기준: 이 런북이 가리키는 스크립트(`scripts/ops/misc61_source_key_probe.py`)는 **이 PR이 main에 머지된 뒤에만** Kiki 클론에서 받을 수 있다.

## 사전 브리핑 (6항목)

1. **과제 명칭** — 원천 7계층 JSON에서 `distractor 연결됨` 88행과 A3 4건의 키 구성 진단.
2. **목적** — 이 88행이 세 필드(`학생의_잘못된_사고`·`distractor_규칙`·`error_type`)가 비어 있는 이유가 ①원천부터 비어 있어서인지 ②추출기가 값을 놓쳐서인지 가른다. 결과에 따라 M0599 보류 해소 경로가 갈린다(①이면 새로 저작, ②이면 추출기 수정 후 재추출).
3. **구체적 절차** — (1) main을 받아 **임시 작업 폴더**(`git worktree`)에 펼친다 — 공유 클론의 브랜치·미커밋 변경은 건드리지 않는다. (2) 원천 파일을 이름·sha256으로 찾는다. (3) 진단 스크립트를 1회 실행한다(읽기 전용, 약 1초). (4) 결과(ASCII JSON)를 세션에 붙여넣는다. (5) 임시 폴더를 지운다.
4. **성공 기준** — `sha256_matches_provenance`가 **True**이고 `all_targets` 안에 `verdict`가 있다. `False`면 다른 파일을 읽은 것이므로 판정을 쓰지 않는다. 대상 행을 하나도 못 찾으면 스크립트가 exit 2로 멈춘다(실패 시 대처: 원천 파일 이름이 `fac16e6f-WhyMath_______.json`인지 확인).
5. **실행 환경** — Windows PowerShell(= Phaiakes9, 별도 접속 불요). 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: 원천 파일이 이 PC에 있을 것. Docker·서버 불요.
6. **창 구분** — **새 PowerShell 창 하나**에서 아래 블록을 순서대로 붙여넣는다. 서버를 점유하지 않으므로 이후 조작 가능.

## 블록 1 — main을 임시 폴더에 펼치고 스크립트 존재를 확인한다 (읽기 전용 · 이 블록은 공유 클론을 바꾸지 않는다)

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 / 작업 디렉터리 = 공유 클론
Set-Location C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = Join-Path $env:TEMP "whymath-misc61-probe"
$Stale = Test-Path $Wt
if ($Stale) { git worktree remove --force $Wt; "STALE_WORKTREE_REMOVED=$Wt" } else { "NO_STALE_WORKTREE=$Wt" }
git worktree add --detach $Wt origin/main
$Probe = Join-Path $Wt "scripts\ops\misc61_source_key_probe.py"
$ProbeExists = Test-Path $Probe
"WORKTREE_HEAD=" + (git -C $Wt log -1 --oneline)
"PROBE_SCRIPT_EXISTS=$ProbeExists"
if ($ProbeExists) { "다음 단계(블록 2)로 진행" } else { "PROBE_MISSING — 이 PR이 아직 main에 머지되지 않았다. 블록 2를 붙여넣지 말고 세션에 알려라" }
```

**자가검증**: `PROBE_SCRIPT_EXISTS=True`가 아니면 블록 2 이후를 붙여넣지 않는다.

## 블록 2 — 원천 파일을 찾는다 (이름 + sha256 일치로만 인정한다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 블록 1의 변수($Wt·$Probe)를 그대로 쓴다
$WantSha = "fcf6d333a419a222fd15d3140ef3c767d246e6f8a7bafe2756326c6b080b187e"
$Roots = @("$env:USERPROFILE\Desktop", "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Documents")
$Found = Get-ChildItem -Path $Roots -Recurse -Filter "fac16e6f*" -File -ErrorAction SilentlyContinue
$Src = $null
foreach ($f in $Found) { if ((Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower() -eq $WantSha) { $Src = $f.FullName } }
"CANDIDATES_BY_NAME=" + @($Found).Count
"SOURCE_SHA_MATCHED_PATH=$Src"
if ($Src) { "원천 확인 — 블록 3으로 진행" } else { "SOURCE_NOT_FOUND — 위 세 폴더에서 이름·sha256이 일치하는 파일이 없다. 파일 위치를 세션에 알려라(블록 3 금지)" }
```

**자가검증**: `SOURCE_SHA_MATCHED_PATH=` 뒤에 경로가 있어야 한다. 이름만 같고 해시가 다른 파일은 **의도적으로 인정하지 않는다**(다른 판의 파일로 판정하면 H1/H2가 무의미해진다).

## 블록 3 — 진단 실행 (읽기 전용 · 결과를 클립보드에 복사한다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 작업 디렉터리를 임시 폴더로 옮긴다(스크립트가 상대 경로로 코퍼스를 읽는다)
Set-Location $Wt
$env:PYTHONUTF8="1"
$CanRun = [bool]$Src -and $ProbeExists
if ($CanRun) { $Report = python $Probe --source $Src --out (Join-Path $Wt "probe_report.json"); $Code = $LASTEXITCODE; $Report | Set-Clipboard; "PROBE_EXIT=$Code"; "REPORT_LINES=" + @($Report).Count; "CLIPBOARD_COPIED=True" } else { "PROBE_REFUSED — 블록 1·2의 판정값이 비었다: Src=$Src ProbeExists=$ProbeExists" }
```

**성공 기준**: `PROBE_EXIT=0`, `REPORT_LINES=`가 0보다 크다. `PROBE_EXIT=2`면 결과는 여전히 클립보드에 있으니(대상 행 0건 보고서 포함) 그대로 세션에 붙여넣는다.

## 블록 4 — 결과를 세션에 전달하고 임시 폴더를 지운다

세션 입력창에 **붙여넣기(Ctrl+V)** 한다. 출력은 ASCII 이스케이프 JSON이라 한글이 `\uXXXX`로 보이는 것이 정상이다. 행 본문(오개념 서술)은 담기지 않아 그대로 붙여도 안전하다.

붙여넣은 뒤 정리한다:

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 정리(임시 폴더만 지운다)
Set-Location C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force $Wt
git worktree prune
"WORKTREE_LEFT=" + (@(git worktree list) -match "whymath-misc61-probe").Count
```

**자가검증**: `WORKTREE_LEFT=0`.

## 세션이 결과를 받으면

1. `sha256_matches_provenance`가 True인지 먼저 본다. False면 판정하지 않는다.
2. `all_targets.verdict`와 A3 4건의 개별 `verdict`를 `MISC-61` 태스크 notes와 `docs/reviews/m0599_hold_and_provenance_mismatch_2026-10-07.md` §2에 기록한다.
3. `H1_source_empty` → acceptance ③(새로 저작 — 카탈로그 kebab 서술 복사 금지·`AI생성-검수필요(MISC-61)` 표시). `H2_known_key`·`H2_unknown_key` → acceptance ②(추출기 키 매핑 수정·재추출·경고 주입 테스트).
4. 게이트 `G-misc40-deferred-m0599-redecision`의 승인·반려는 세션이 하지 않는다.
