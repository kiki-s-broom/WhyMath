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

---

# 2차 실행 — `오개념_원인` 값 덤프 (M0418·M0417 채움 재료)

> 대상 태스크: `MISC-61-a3-thin-misid-source-enrichment` acceptance ② (M0418·M0417 경로)
> **실행 여부는 Kiki가 정한다.** 이 실행 없이도 M0599·M0600은 이미 저작돼 있다 — 이 실행은 A3의 나머지 2건(M0418·M0417)을 채우기 위한 것이다.
> 선행 조건: 1차 실행으로 원천 파일이 이 PC에 있음이 확인돼 있다(`통합데이터셋\WhyMath_통합데이터셋.json`, sha256 `fcf6d333…187e` 일치 확인됨).
> **[정정 2026-10-16]** 이 옵션(`--dump-key`)은 1차 이행 PR(#1643)과 함께 **main에 들어갔다.** 종전 판은 "main에 없다, 브랜치 `claude/peaceful-bell-s7mlg8`에서 펼친다"고 적었으나 그 브랜치는 머지 뒤 원격에서 삭제돼(`git ls-remote` 0건) 블록 A의 `git fetch`가 첫 줄에서 실패했다. 지금은 `origin/main`에서 펼치고, 블록 A가 그 트리에 옵션이 실제로 있는지 자가검증한다.

## 사전 브리핑 (6항목)

1. **과제 명칭** — 원천 7계층 JSON에서 `오개념_원인` 키의 값 전체를 읽어, 코퍼스의 `원본`+세 필드 공란 행과 행 단위로 대조.
2. **목적** — 1차 실행으로 "원천에 `오개념_원인` 값이 21행 있고, 코퍼스의 `원본` 공란도 21행"까지만 알았다. 그 21행이 **같은 행인지**와 M0418·M0417의 **실제 내용**을 보아야 값을 어느 필드(`student_wrong_thinking`인지 다른 칸인지)로 보낼지 정할 수 있다. 내용을 보지 않고는 정하지 않는다.
3. **구체적 절차** — (A) `origin/main`을 임시 폴더(`git worktree`)에 펼치고 `--dump-key` 옵션이 실제로 있는지 확인 → (B) 원천 파일을 이름·sha256으로 찾음 → (C) 진단을 1회 실행(읽기 전용, 약 1초)하고 결과를 클립보드에 복사하며 점검 줄을 출력 → (E) 필요한 두 행(`M0418`·`M0417`)의 값을 화면에 출력해 세션에 전달 → (D) 임시 폴더 삭제. 공유 클론의 브랜치·미커밋 변경은 건드리지 않는다.
4. **성공 기준** — 블록 A에서 `FETCH_OK=True`·`DUMP_KEY_OPTION_PRESENT=True`·`CONTAINS_PR1643=True`, 블록 B에서 `SOURCE_SHA_MATCHED_PATH=` 뒤에 경로, 블록 C에서 `PROBE_EXIT=0`·`SHA_MATCHES=True`·`DUMP_ROWS=21`·`A3_IN_BOTH=True`. **`DUMP_ROWS`가 "숫자로 나온다"는 기준으로 쓰지 않는다** — `--dump-key`의 키 이름이 깨져도 `0`이 나오는데 `0`도 숫자라 실패 상태에서 통과해 버린다(2026-10-17 합성 원천으로 확인). 하나라도 어긋나면 다음 블록을 붙여넣지 않는다(실패 시 대처: 어긋난 줄의 출력을 그대로 세션에 알린다).
5. **실행 환경** — Windows PowerShell(= Phaiakes9, 별도 접속 불요). 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. Docker·서버 불요.
6. **창 구분** — **새 PowerShell 창 하나**에서 블록 A→B→C→D를 **한 블록씩** 붙여넣는다. 서버를 점유하지 않으므로 이후 조작 가능. 앞 블록의 출력 판정값을 눈으로 확인한 뒤 다음 블록을 붙여넣는다.

**출력 안전**: 이 덤프는 `오개념_원인` 한 키의 값만 낸다. 와이매스 자체 저작 오개념 서술이며 학생 데이터·개인정보가 아니다. 그래도 그 키 하나 외의 본문(오개념 서술 등)은 나오지 않는다.

## 블록 A — `origin/main`을 임시 폴더에 펼치고 `--dump-key` 옵션 존재를 확인한다 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 / 작업 디렉터리 = 공유 클론
Set-Location C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$FetchOk = ($LASTEXITCODE -eq 0)
"FETCH_OK=$FetchOk"
git worktree prune
$Wt = Join-Path $env:TEMP "whymath-misc61-probe2"
if (Test-Path $Wt) { git worktree remove --force $Wt; "STALE_WORKTREE_REMOVED=$Wt" }
$Expected = (git rev-parse --short origin/main)
git worktree add --detach $Wt origin/main
$Head = (git -C $Wt rev-parse --short HEAD)
$Probe = Join-Path $Wt "scripts\ops\misc61_source_key_probe.py"
$HasOption = $false
$HasPr1643 = $false
if ($FetchOk -and $Head -and ($Head -eq $Expected)) {
  if (Test-Path $Probe) { $HasOption = [bool](Select-String -Path $Probe -Pattern "--dump-key" -SimpleMatch -Quiet) }
  git -C $Wt merge-base --is-ancestor 8d21c4cc HEAD
  $HasPr1643 = ($LASTEXITCODE -eq 0)
  "WORKTREE_HEAD=" + (git -C $Wt log -1 --oneline)
  "DUMP_KEY_OPTION_PRESENT=$HasOption"
  "CONTAINS_PR1643=$HasPr1643"
  if ($HasOption -and $HasPr1643) { "블록 B로 진행" } else { "BLOCK_A_FAILED — 블록 B 이후를 붙여넣지 말고 위 줄들을 채팅에 알려 주세요" }
} else { "REFUSED — FETCH_OK=$FetchOk HEAD=$Head EXPECTED=$Expected — 전환이 안 됐으니 블록 B 이후를 붙여넣지 마세요" }
```

**자가검증**: `FETCH_OK=True`·`DUMP_KEY_OPTION_PRESENT=True`·`CONTAINS_PR1643=True`가 아니면 블록 B 이후를 붙여넣지 않는다. 이 줄들은 옵션이 없는 상태(1차 이행 PR #1643 이전의 main 스크립트)에서 `False`를 내므로 변별력이 있다 — 그 이전 커밋의 스크립트에서 `--dump-key` 0건, 이후에서 3건임을 실측했다. `git worktree add` 뒤의 모든 단계는 **HEAD 되읽기 가드 안**에 있다(전환이 실패하면 `REFUSED` 한 줄만 나오고 아무것도 실행되지 않는다). `WORKTREE_HEAD` 줄의 한글이 깨져 보이는 것은 콘솔이 커밋 제목을 cp949로 표시한 탓이며 실행에는 영향이 없다.

## 블록 B — 원천 파일을 찾는다 (이름 + sha256 일치로만 인정한다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 블록 A의 변수($Wt·$Probe·$HasOption)를 그대로 쓴다
$WantSha = "fcf6d333a419a222fd15d3140ef3c767d246e6f8a7bafe2756326c6b080b187e"
$Roots = @("$env:USERPROFILE\Desktop", "$env:USERPROFILE\Downloads", "$env:USERPROFILE\Documents")
$Found = @()
if ($HasOption) { $Found = Get-ChildItem -Path $Roots -Recurse -Filter "*WhyMath_*.json" -File -ErrorAction SilentlyContinue }
$Src = $null
foreach ($f in $Found) { if ((Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower() -eq $WantSha) { $Src = $f.FullName } }
"CANDIDATES_BY_NAME=" + @($Found).Count
"SOURCE_SHA_MATCHED_PATH=$Src"
if ($Src) { "원천 확인 — 블록 C로 진행" } else { "SOURCE_NOT_FOUND — 블록 C 금지. 위 두 줄을 세션에 알려라" }
```

**자가검증**: `SOURCE_SHA_MATCHED_PATH=` 뒤에 경로가 있어야 한다. 이름 필터가 `*WhyMath_*.json`인 이유: 1차 실행에서 로컬 사본의 이름이 `fac16e6f-…`가 아니었기 때문이다. 해시가 맞는 파일만 인정한다.

## 블록 C — 덤프 실행 (읽기 전용 · 결과를 클립보드에 복사하고 점검 줄을 출력한다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 블록 A·B의 변수($Wt, $Probe, $Src, $HasOption)를 그대로 쓴다
$CanRun = [bool]$Src -and $HasOption
if ($CanRun) {
  Set-Location $Wt
  $env:PYTHONUTF8 = "1"
  $Lines = python $Probe --source $Src --dump-key "오개념_원인" --out (Join-Path $Wt "probe_dump.json")
  $Code = $LASTEXITCODE
  "PROBE_EXIT=$Code"
  $Lines | Set-Clipboard
  "CLIPBOARD_COPIED=True"
  $J = ($Lines -join "`n") | ConvertFrom-Json
  "SHA_MATCHES=" + $J.sha256_matches_provenance
  "DUMP_ROWS=" + $J.dump.rows_with_value
  "CORPUS_ORIGINAL_EMPTY=" + $J.dump.corpus_original_empty_rows
  "A3_IN_BOTH=" + (($J.dump.in_both -contains "M0418") -and ($J.dump.in_both -contains "M0417"))
  "ONLY_IN_SOURCE=" + @($J.dump.only_in_source).Count
  "ONLY_IN_CORPUS=" + @($J.dump.only_in_corpus).Count
}
if (-not $CanRun) { "PROBE_REFUSED — 블록 A·B의 판정값이 비었습니다: Src=$Src HasOption=$HasOption" }
```

**성공 기준**: `PROBE_EXIT=0`, `SHA_MATCHES=True`, `DUMP_ROWS=21`, `CORPUS_ORIGINAL_EMPTY=21`, `A3_IN_BOTH=True`. `ONLY_IN_SOURCE`·`ONLY_IN_CORPUS`는 0이 이상적이지만 0이 아니어도 실패가 아니라 정보다. **이 상태는 M0418·M0417이 아직 `원본`+공란일 때의 기대값이다** — 2026-10-17 반영 뒤에 다시 돌리면 두 행이 그 집합에서 빠져 `CORPUS_ORIGINAL_EMPTY=19`·`A3_IN_BOTH=False`·`ONLY_IN_SOURCE=2`가 정상이다.

**실패 신호**: `DUMP_ROWS=0`이면 키 이름이 PowerShell을 거치며 깨진 것이다. `SHA_MATCHES=False`이면 다른 판의 파일이다. 둘 다 블록 D로 가지 말고 출력을 세션에 알린다. 점검 줄은 값 본문을 담지 않는다 — 값은 클립보드에만 있다.

## 블록 E — 필요한 두 행(`M0418`·`M0417`)의 값만 화면에 출력한다 (읽기 전용)

점검 줄만 세션에 전달하면 값 본문은 전달되지 않는다(2026-10-17 실제로 두 번 점검 줄만 전달됐다). 클립보드를 붙여넣기 어려우면 블록 C와 **같은 창**에서 이 블록을 실행해 화면에서 복사한다. 블록 D(정리) 전에 실행한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 블록 C가 만든 $J를 그대로 쓴다 (읽기 전용, 파일 변경 없음)
if ($J -and $J.dump) {
  $Two = @($J.dump.values | Where-Object { $_.mis_id -eq "M0418" -or $_.mis_id -eq "M0417" })
  "TWO_ROWS_FOUND=" + $Two.Count
  $Two | ConvertTo-Json -Depth 5
} else { "NO_DUMP_IN_MEMORY — 이 창에 블록 C의 결과가 없습니다. 블록 A→B→C를 다시 실행해 주세요" }
```

**성공**: `TWO_ROWS_FOUND=2`와 그 아래에 `mis_id`·`value`가 있는 항목 두 개(한글 문장으로 읽힘). 이 출력을 복사해 세션에 붙여넣는다. 창을 닫았거나 정리(블록 D)를 마쳤으면 `NO_DUMP_IN_MEMORY`가 나온다 — A→B→C를 다시 돌린다.

## 블록 D — 결과를 세션에 전달하고 임시 폴더를 지운다

세션 입력창에 **붙여넣기(Ctrl+V)** 한다. 출력은 ASCII 이스케이프 JSON이라 한글이 `\uXXXX`로 보이는 것이 정상이다.

붙여넣은 뒤 정리한다:

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 정리(임시 폴더만 지운다)
Set-Location C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force $Wt
git worktree prune
"WORKTREE_LEFT=" + (@(git worktree list) -match "whymath-misc61-probe2").Count
```

**자가검증**: `WORKTREE_LEFT=0`.

## 세션이 결과를 받으면

1. `sha256_matches_provenance`가 True인지 먼저 본다. False면 판정하지 않는다.
2. `dump.in_both`에 `M0418`·`M0417`이 있는지, `only_in_source`·`only_in_corpus`가 비었는지(= 21행 = 21행이 **같은 행**인지) 확인한다.
3. 값의 **내용**을 보고 `오개념_원인`을 어느 필드로 보낼지 정한다. 값이 `student_wrong_thinking`에 해당하면 그 칸만 채우고, 나머지 두 칸(`distractor_rule`·`error_type`)이 여전히 비면 그 칸은 원천에 근거가 없으므로 acceptance ③(AI 저작 표시)로 채울지 Kiki에게 묻는다.
4. 반영은 **표적 패치**다 — 전체 재추출은 하지 않는다(재추출하면 `severity`·`behavior_skills`와 손으로 더한 행 6건이 지워진다. 판정 문서 §2-c).
5. 게이트 `G-misc40-deferred-m0599-redecision`의 승인·반려는 세션이 하지 않는다.

## 실행 기록

- **2026-10-17**: Kiki 머신에서 블록 A→B→C→E→D를 실행했다(원천 `C:\Users\kiki\Desktop\__AI\mathmatic\통합데이터셋\WhyMath_통합데이터셋.json`, 후보 이름 42개 중 sha256 일치 1개). `PROBE_EXIT=0` · `SHA_MATCHES=True` · `DUMP_ROWS=21` · `CORPUS_ORIGINAL_EMPTY=21` · `A3_IN_BOTH=True` · `ONLY_IN_SOURCE=0` · `ONLY_IN_CORPUS=0`. M0417 = `확률 범위 미이해` · M0418 = `배반사건 혼동`. 반영과 근거 = `docs/reviews/m0599_hold_and_provenance_mismatch_2026-10-07.md` §2-d.
