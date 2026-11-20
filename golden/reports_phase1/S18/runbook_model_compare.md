# S18 Kiki 머신 런북 — 학생 모델 후보 2개 비교 (로컬 Ollama)

> 기준: 작업 브랜치 `claude/new-session-yzei6i` · 코드 커밋 `0eff924b`(블록 A가 이 커밋을 포함하는지 검사한다).
> 시드 원문은 화면·파일·채팅 어디에도 나오지 않는다 — 블록은 줄 수와 숫자만 찍는다(공통 규칙 7).

## 사전 브리핑 (6항목)

1. **과제 명칭** — S18 학생 모델 후보 비교: `exaone3.5:7.8b` 대 `qwen2.5:7b`.
2. **목적** — 학생 시뮬레이터(P2·P3·P4·P6)가 쓸 로컬 Ollama 모델 1개를 고른다. 고른 모델이 `GOLDEN_SIM_STUDENT_MODEL`의 기본값이 되고, S19 러너·야간 스모크(Kiki 머신 실제 LLM 판)가 그 모델로 돈다. 클라우드 세션에는 Ollama와 시드가 없어 이 단계만 Kiki 머신에서 한다.
3. **구체적 절차**
   - 블록 A(약 30초): 공유 작업 사본은 그대로 두고, 따로 만든 작업 폴더 `WhyMath-s18cmp`를 S18 브랜치에 맞춘다. 파이썬·`ollama` 패키지·시드 줄 수(20)·후보 모델 설치 여부를 점검해 한 줄씩 찍는다.
   - 블록 P(후보가 없을 때만 · 모델 하나에 약 4.7~4.8GB · 회선에 따라 5~20분): 없는 후보만 `ollama pull`.
   - 블록 B(약 3~10분): 비교를 돌린다. 모델마다 페르소나 4개 × 문항 5개 = 발화 20개를 만들고, ⓑ규칙 위반 수와 ⓐ말투 구분 정확도(로컬 계산 — 시드를 밖으로 보내지 않으려고 "세션 AI가 구분"을 바꿨다)를 센다. 결과는 작업 폴더의 `golden\reports_phase1\S18\` 안 파일 2개(`model_compare.json` 숫자만 · `samples.md` 모델 발화만)다. 모델 발화가 시드를 베꼈으면 그 칸만 가리고 진행한다. 가림을 지나 시드가 남으면 파일을 지우고 `COMPARE_EXIT=3`으로 멈춘다. 원인 진단 숫자는 `SEED_SCAN` 한 줄이다(원문 없음).
   - 블록 C(약 10초): 결과 파일 2개를 S18 브랜치에 커밋·푸시한다. 블록 B가 성공하지 않았으면 스스로 거부한다.
4. **성공 기준**
   - 블록 A: `CODE_OK=True` · `WORKTREE_HEAD`와 `EXPECTED`가 같음 · `PY_OK=True` · `OLLAMA_PKG_OK=True` · `SEED_LINES=20` · `HAS_EXAONE`·`HAS_QWEN` 중 하나 이상 True.
   - 블록 B: 마지막 줄이 `COMPARE_EXIT=0`이고 그 위에 `MODEL=… VIOLATIONS=…` 줄이 모델 수만큼, `CHOSEN=… COMPARISON=실시` 한 줄.
   - 블록 C: `PUSH_EXIT=0`과 커밋 한 줄.
   - 실패 시 대처: 블록마다 `RUN_REFUSED`·`WRITE_REFUSED` 줄이 무엇이 False인지 말한다. `OLLAMA_TAGS=0`이면 작업 표시줄에서 Ollama 앱을 켠 뒤 블록 A를 다시 붙여넣는다.
5. **실행 환경** — Phaiakes9(이 PC) · Windows PowerShell · 공유 작업 사본 `C:\Users\kiki\Desktop\__AI\WhyMath`(읽기만 — 시드 폴더와 `.venv`를 빌려 쓴다) · 작업 폴더 `C:\Users\kiki\Desktop\__AI\WhyMath-s18cmp`. 선행 조건: Ollama 앱 가동 · S16 시드 파일(`golden\sim\seed\utterances.txt`)이 공유 작업 사본에 있음(2026-11-17 S16 실행으로 생김). 서버·Docker·DB는 필요 없다.
6. **창 구분** — **새 PowerShell 창 하나(창 A)**에서 블록 A → (필요하면 P) → B → C를 차례로 붙여넣는다. 앞 블록이 만든 변수를 뒤 블록이 쓰므로 같은 창이어야 한다. 서버를 띄우지 않으므로 창을 점유하지 않는다. **각 블록의 판정 줄을 눈으로 본 다음에 다음 블록을 붙여넣는다**(쓰기 블록 B·C는 조건이 틀리면 스스로 거부하지만, 판정을 보는 것이 먼저다).

## 블록 A — 준비·점검 (창 A · 새 창)

```powershell
# [창 A · 블록 A — 준비·점검] Windows PowerShell — 작업 폴더 WhyMath-s18cmp를 S18 브랜치에 맞추고, 실제로 맞춰졌을 때만 파이썬·ollama·시드 줄 수·모델을 점검(공유 작업 사본은 바꾸지 않음)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/new-session-yzei6i
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-s18cmp"
git worktree prune
$WtValid = (Test-Path "$Wt\.git") -and ((git -C $Wt rev-parse --is-inside-work-tree 2>$null) -eq "true")
if ($WtValid) { git -C $Wt checkout -q --detach --force origin/claude/new-session-yzei6i } else { if (-not (Test-Path $Wt)) { git worktree add --detach $Wt origin/claude/new-session-yzei6i } }
$Expected = git rev-parse origin/claude/new-session-yzei6i
$WtHead = git -C $Wt rev-parse HEAD 2>$null
Write-Host "WORKTREE_HEAD=$WtHead  EXPECTED=$Expected  (같아야 함)"
if ($WtHead -and ($WtHead -eq $Expected)) {
  git -C $Wt log -1 --oneline
  git -C $Wt merge-base --is-ancestor 0eff924b HEAD 2>$null; $CodeOk = ($LASTEXITCODE -eq 0)
  $Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
  $PyOk = Test-Path $Py
  $OllamaPkgOk = $false; if ($PyOk) { & $Py -c "import ollama" 2>$null; $OllamaPkgOk = ($LASTEXITCODE -eq 0) }
  $SeedDir = "C:\Users\kiki\Desktop\__AI\WhyMath\golden\sim\seed"
  $SeedLines = 0; if (Test-Path "$SeedDir\utterances.txt") { $SeedLines = @(Get-Content -Encoding UTF8 "$SeedDir\utterances.txt" | Where-Object { $_.Trim() }).Count }
  $Tags = @(ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ })
  $HasExaone = $Tags -contains "exaone3.5:7.8b"
  $HasQwen = $Tags -contains "qwen2.5:7b"
  Write-Host "CODE_OK=$CodeOk  PY_OK=$PyOk  OLLAMA_PKG_OK=$OllamaPkgOk  SEED_LINES=$SeedLines  OLLAMA_TAGS=$($Tags.Count)  HAS_EXAONE=$HasExaone  HAS_QWEN=$HasQwen"
  if ($CodeOk -and $PyOk -and $OllamaPkgOk -and ($SeedLines -eq 20) -and ($HasExaone -or $HasQwen)) { Write-Host "READY=True — 둘 다 True면 블록 B로, 하나만 True면 블록 P 또는 그대로 블록 B(비교 미실시로 기록)" } else { Write-Host "READY=False — CODE_OK=False=브랜치에 S18 코드 없음(세션에 알리기) · PY_OK=False=.venv 없음(세션에 알리기) · OLLAMA_PKG_OK=False=아래 패키지 설치 한 줄 · SEED_LINES가 20이 아님=S16 시드 없음(세션에 알리기) · OLLAMA_TAGS=0=Ollama 앱 켜기 · HAS_* 둘 다 False=블록 P" }
} else { Write-Host "REFUSED — HEAD=$WtHead EXPECTED=$Expected — 작업 폴더가 S18 브랜치로 바뀌지 않았다. 이 폴더를 연 탐색기·VS Code·이전 PowerShell 창을 닫고 블록 A를 다시. 그래도 같으면 세션에 알리기" }
```

`ollama` 파이썬 패키지가 없을 때(`OLLAMA_PKG_OK=False`)만 이 한 줄을 같은 창에 붙여넣고 블록 A를 다시 붙여넣는다.

```powershell
# [창 A · 패키지 설치 — OLLAMA_PKG_OK=False일 때만] Windows PowerShell — 공유 .venv에 ollama 클라이언트(백엔드 의존성 범위 >=0.4,<1) 설치
& "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe" -m pip install "ollama>=0.4.0,<1"
```

## 블록 P — 없는 후보 모델 내려받기 (창 A · HAS_EXAONE 또는 HAS_QWEN이 False일 때만)

```powershell
# [창 A · 블록 P — 없는 후보만 ollama pull] Windows PowerShell — exaone3.5:7.8b 약 4.8GB · qwen2.5:7b 약 4.7GB · 이미 있는 모델은 건너뜀
if (-not $HasExaone) { ollama pull exaone3.5:7.8b } else { Write-Host "SKIP exaone3.5:7.8b — 이미 있음" }
if (-not $HasQwen) { ollama pull qwen2.5:7b } else { Write-Host "SKIP qwen2.5:7b — 이미 있음" }
$Tags = @(ollama list 2>$null | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] } | Where-Object { $_ })
$HasExaone = $Tags -contains "exaone3.5:7.8b"
$HasQwen = $Tags -contains "qwen2.5:7b"
Write-Host "HAS_EXAONE=$HasExaone  HAS_QWEN=$HasQwen  (둘 다 True면 블록 B · 내려받기가 실패해 하나만 True여도 블록 B는 그 하나로 돌고 '비교 미실시'로 기록된다)"
```

## 블록 B — 비교 실행 (창 A · 작업 폴더 안 결과 파일 2개를 쓴다)

```powershell
# [창 A · 블록 B — 모델 비교] Windows PowerShell — 조건을 다시 검사하고, 실행 모듈이 작업 폴더의 것인지 확인한 뒤에만 비교를 돌린다(숫자만 출력)
$Models = @(); if ($HasExaone) { $Models += "exaone3.5:7.8b" }; if ($HasQwen) { $Models += "qwen2.5:7b" }
$ModelsArg = $Models -join ","
cd "$Wt\src\backend"
Remove-Item Env:GOLDEN_FAKE_LLM -ErrorAction SilentlyContinue
$env:GOLDEN_SIM_SEED_DIR = $SeedDir
$ModFile = ""; if ($PyOk) { $ModFile = & $Py -c "import golden.sim.student_compare as m; print(m.__file__)" 2>$null }
$ModOk = [string]$ModFile -like "$Wt\*"
Write-Host "MODULE_FROM_WORKTREE=$ModOk  MODELS=$ModelsArg"
$CompareExit = -1
if ($CodeOk -and ($WtHead -eq $Expected) -and $OllamaPkgOk -and ($SeedLines -eq 20) -and ($Models.Count -ge 1) -and $ModOk) { & $Py -m golden.sim.student_compare --models $ModelsArg; $CompareExit = $LASTEXITCODE } else { Write-Host "RUN_REFUSED=True — 블록 A의 READY가 True였는지, MODULE_FROM_WORKTREE=True인지 확인(False면 작업 폴더가 아닌 곳의 코드가 잡힌 것 — 세션에 알리기)" }
Write-Host "COMPARE_EXIT=$CompareExit  (0=성공 · 2=시드/가짜 모드 문제 · 3=결과에 시드가 섞여 지움 · -1=실행 거부)"
cd C:\Users\kiki\Desktop\__AI\WhyMath
```

## 블록 C — 결과 커밋·푸시 (창 A · 블록 B가 COMPARE_EXIT=0일 때만 실제로 쓴다)

```powershell
# [창 A · 블록 C — 결과 2개 커밋·푸시] Windows PowerShell — COMPARE_EXIT=0이고 결과 파일 2개가 있을 때만 작업 폴더에서 커밋해 S18 브랜치로 푸시(공유 작업 사본은 바꾸지 않음)
$Out = "$Wt\golden\reports_phase1\S18"
$HasFiles = (Test-Path "$Out\model_compare.json") -and (Test-Path "$Out\samples.md")
$PushExit = -1
if (($CompareExit -eq 0) -and $HasFiles) { git -C $Wt add golden/reports_phase1/S18/model_compare.json golden/reports_phase1/S18/samples.md; git -C $Wt commit -q -m "S18: Kiki machine student model comparison result (F-00)"; if ($LASTEXITCODE -eq 0) { git -C $Wt push origin HEAD:claude/new-session-yzei6i; $PushExit = $LASTEXITCODE } else { Write-Host "COMMIT_FAILED=True — git 사용자 이름·메일이 없거나 바뀐 파일이 없다(세션에 알리기)" } } else { Write-Host "WRITE_REFUSED=True — COMPARE_EXIT=$CompareExit  HAS_FILES=$HasFiles (블록 B가 0으로 끝나지 않았다)" }
Write-Host "PUSH_EXIT=$PushExit  (0이면 성공 — 세션에 '푸시했다'고만 알리면 세션이 결과를 읽어 기본 모델을 확정한다)"
git -C $Wt log -1 --oneline
```

## 끝난 뒤

- 세션에는 "블록 C까지 PUSH_EXIT=0"이라고만 알린다. 결과 파일은 세션이 브랜치에서 직접 읽는다(숫자 표와 모델 발화뿐 — 시드 원문 없음).
- 작업 폴더 `WhyMath-s18cmp`는 S19 런북에서 다시 쓸 수 있어 지우지 않는다. 지우려면 `git worktree remove C:\Users\kiki\Desktop\__AI\WhyMath-s18cmp`(공유 작업 사본 창에서).
- 블록 B가 `COMPARE_EXIT=3`이면 가림을 지나 시드가 남았다는 뜻이다(결과 파일은 이미 지워졌다). `SEED_SCAN` 줄의 숫자만 세션에 알린다.
- 2026-11-20 첫 실행 2회의 `COMPARE_EXIT=3`은 도구의 오탐이었다 — 규칙 페르소나 칸과 사람 말이 우연히 같은 것까지 유출로 셌다. 코드 `0eff924b`가 판정 대상을 모델 발화로 좁혔다.
