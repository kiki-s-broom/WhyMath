# 코딩 헌법 서명 검증 Kiki 런북 — 서명 키 만들기 · 무장 PR · 무장 확인 · 이후 개정 절차

- 태스크: `CONST-17` · 게이트: `G-const-signing-key-register`(키 등록 = 무장) · 결정 근거: 게이트 `G-const-protection-outside-claude`(Kiki 승인 2026-10-15, (나)안)
- 검증기: `scripts/constitution/check_signed_changes.py` · CI 스텝: `harness-integrity` 잡의 「헌법 서명 검증」 · 테스트: `tests/constitution/test_check_signed_changes.py`
- 판정 기준: 이 런북의 명령은 **CONST-17 PR이 main에 머지된 뒤**의 `origin/main`을 기준으로 한다. 블록마다 그것을 스스로 확인하고, 안 맞으면 쓰기를 거부한다.

## 0. 왜 이것이 필요한가 (쉬운 설명)

헌법 폴더(`constitution/`)는 사람(Kiki님)만 고칠 수 있어야 합니다. 지금은 Claude Code 안에 **가드 훅**이 있어서 AI가 고치려 하면 막습니다. 하지만 이 훅은 "Claude Code 도구를 쓸 때"만 작동합니다. 웹 편집이나 외부 스크립트로 올리면 훅은 아무것도 못 봅니다. 게다가 GitHub에서는 사람과 AI가 **같은 계정**이라 "누가 고쳤나"를 구별할 수 없습니다.

그래서 **서명**을 씁니다. 서명은 "이 커밋은 이 열쇠를 가진 사람이 만들었다"는 도장입니다. 열쇠(비밀키)는 Kiki님 PC에만 있고, AI 세션은 갖고 있지 않아 도장을 찍을 수 없습니다. CI가 "헌법을 바꾸는 커밋에 Kiki님 도장이 있는가"를 확인합니다.

- **비밀키**(`whymath_constitution_signing`): 도장 그 자체. **절대 공유하거나 저장소에 올리지 않습니다.**
- **공개키**(`...signing.pub`): "이 도장은 이 사람 것"이라는 확인용 정보. 저장소에 올려도 안전합니다.
- **무장(arm)**: 공개키가 저장소(`constitution_signers/allowed_signers`)에 등록되어 검사가 실제로 강제되기 시작하는 순간. 그 전(미무장)에는 검사가 "아직 키가 없다"고 알리고 통과시킵니다.

## 순서 요약

| 과제 | 내용 | 창 | 소요 |
|---|---|---|---|
| S | 서명 키 만들기 + 지문 확인 | 창① | 3분 |
| T | 무장 PR 만들기(공개키 등록) → 웹에서 PR 열고 머지 | 창① 이어서 | 5분 |
| U | 무장 확인(실제로 막는지 음성 시험) | 창② (새 창) | 3분 |
| V | 이후 헌법을 개정할 때의 서명 커밋 방법 | 필요할 때 | — |

---

## 1. 과제 S — 서명 키 만들기

### 사전 브리핑

1. **과제 명칭**: 헌법 서명용 SSH 키 쌍 생성과 지문 확인.
2. **목적**: 헌법 변경 커밋에 찍을 "도장"을 만듭니다. 결과(공개키)는 과제 T에서 저장소에 등록됩니다.
3. **구체적 절차**:
   - [S-1] 키 생성: `ssh-keygen`이 비밀번호(passphrase)를 두 번 물어봅니다. **비밀번호를 정하는 것을 권장**합니다(키 파일이 유출돼도 바로 쓰이지 않음). 헌법 개정은 드물어서 서명할 때마다 비밀번호를 입력해도 부담이 적습니다. 비밀번호는 분실하면 복구할 수 없으니 비밀번호 관리자에 보관하세요.
   - [S-2] 지문 확인: 읽기 전용. 공개키의 지문(fingerprint)을 출력합니다.
4. **성공 기준**: S-1 뒤 `KEY_CREATED=True`, S-2에서 `PUB_EXISTS=True`와 `SHA256:`로 시작하는 `KEY_FINGERPRINT` 줄. 실패 신호: `KEY_EXISTS=True`(이미 키가 있어 새로 만들지 않음 — 정상 거부이며, 그 키를 계속 쓰면 됩니다) 또는 `SSH_KEYGEN_OK=False`(OpenSSH 클라이언트 미설치 → 설정 > 앱 > 선택적 기능에서 "OpenSSH 클라이언트" 추가).
5. **실행 환경**: Phaiakes9(이 PC)의 Windows PowerShell. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건 없음(S는 저장소 상태와 무관).
6. **창 구분**: **새 창 하나(창①)**. S-1은 비밀번호 입력을 기다리는 **대화형 블록이라 이 블록으로 끝나야 하며**, 입력을 마친 뒤 S-2를 따로 붙여넣습니다. S-1 실행 중에는 다른 것을 붙여넣지 마세요(붙여넣은 글자가 비밀번호로 입력됩니다).

### [S-1] 키 생성 (대화형 — 이 블록으로 끝)

```powershell
# [창① S-1 키 생성] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Key = Join-Path $HOME ".ssh\whymath_constitution_signing"
$SshOk = [bool](Get-Command ssh-keygen -ErrorAction SilentlyContinue)
$KeyExists = (Test-Path $Key) -or (Test-Path "$Key.pub")
"SSH_KEYGEN_OK=$SshOk KEY_EXISTS=$KeyExists KEY_PATH=$Key"
if ($SshOk -and (-not $KeyExists)) { New-Item -ItemType Directory -Force (Join-Path $HOME ".ssh") | Out-Null; ssh-keygen -t ed25519 -C "kiki-whymath-constitution" -f $Key } else { "KEY_REFUSED=True — ssh-keygen 없음(SSH_KEYGEN_OK) 또는 이미 키가 있음(KEY_EXISTS): 기존 키를 덮어쓰지 않습니다. 위 값을 확인하세요." }
```

### [S-2] 지문 확인 (읽기 전용)

```powershell
# [창① S-2 지문 확인] Windows PowerShell — Phaiakes9 (읽기 전용)
$Key = Join-Path $HOME ".ssh\whymath_constitution_signing"
$PubExists = Test-Path "$Key.pub"
"PUB_EXISTS=$PubExists"
if ($PubExists) { "KEY_FINGERPRINT=" + (ssh-keygen -l -f "$Key.pub") } else { "KEY_FINGERPRINT=없음 — S-1이 성공했는지 확인하세요(KEY_CREATED 대신 KEY_REFUSED가 나왔다면 위 사유)." }
```

---

## 2. 과제 T — 무장 PR 만들기 (공개키 등록)

### 사전 브리핑

1. **과제 명칭**: 서명자 목록(`constitution_signers/allowed_signers`)에 Kiki님 공개키를 등록하는 PR 생성.
2. **목적**: 이 PR이 머지되는 순간 서명 검증이 **무장**됩니다. 이후 `constitution/`·서명자 목록·검증기·검증 스텝을 바꾸는 모든 PR 커밋은 이 키로 서명돼야 합니다.
3. **구체적 절차**:
   - [T-1] 동의 입력: `ARM`을 직접 타이핑합니다(한 줄 블록이라 붙여넣기가 여기서 멈춥니다).
   - [T-2] 준비·반영·푸시: 아래 조건이 **모두 True일 때만** 옆 폴더 `WhyMath-const`에 작업 사본을 만들고, 공개키 한 줄을 `allowed_signers`에 쓴 뒤, **서명된 커밋**을 만들어 `kiki/const-signing-arm` 브랜치로 올립니다(약 20초, 서명 때 비밀번호 입력). 조건: main에 검증기가 머지됨 · 이미 무장되지 않음 · 공개키 존재 · 동의 입력. 하나라도 False면 아무것도 쓰지 않고 이유를 출력합니다.
   - [T-3] 웹에서 PR을 열고 머지합니다(블록이 PR 생성 링크를 출력). 머지 큐가 강제되므로 큐에 넣으면 됩니다.
4. **성공 기준**: `READY=True` → `SIGNED_STATUS=G`(서명이 허용 목록 키로 검증됨) → `PUSH_OK=True`. 실패 신호: `ARM_REFUSED=True`(이유 줄 확인) · `SIGNED_STATUS=N`(서명이 안 붙음 → 비밀번호 입력 취소 또는 키 경로 문제) · `COMMIT_FAILED=True`.
5. **실행 환경**: Phaiakes9의 Windows PowerShell, 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: 과제 S 완료 · **CONST-17 PR이 main에 머지됨**.
6. **창 구분**: 창①에서 이어서. T-1(한 줄)에서 `ARM`을 입력한 다음 T-2를 붙여넣습니다. T-2는 비밀번호를 물을 수 있으니 끝날 때까지 다른 입력을 하지 마세요.

### [T-1] 동의 입력 (한 줄 — 직접 타이핑)

```powershell
$Consent = Read-Host "무장 PR을 만듭니다. 계속하려면 ARM 을 입력하고 Enter"
```

### [T-2] 준비·반영·푸시

```powershell
# [창① T-2 무장 PR] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git cat-file -e origin/main:scripts/constitution/check_signed_changes.py
$MainHasVerifier = ($LASTEXITCODE -eq 0)
git cat-file -e origin/main:constitution_signers/allowed_signers 2>$null
$AlreadyArmed = ($LASTEXITCODE -eq 0)
$Key = Join-Path $HOME ".ssh\whymath_constitution_signing"
$KeyFwd = $Key -replace '\\', '/'
$PubOk = Test-Path "$Key.pub"
$ConsentOk = ($Consent -eq "ARM")
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-const"
$Br = "kiki/const-signing-arm"
$Ready = ($MainHasVerifier -and (-not $AlreadyArmed) -and $PubOk -and $ConsentOk)
"READY=$Ready MAIN_HAS_VERIFIER=$MainHasVerifier ALREADY_ARMED=$AlreadyArmed PUB_OK=$PubOk CONSENT_OK=$ConsentOk"
if ($Ready) { if (Test-Path $Wt) { git worktree remove --force $Wt; git worktree prune }; git worktree add -B $Br $Wt origin/main; New-Item -ItemType Directory -Force (Join-Path $Wt "constitution_signers") | Out-Null; $Parts = (Get-Content "$Key.pub" -Raw).Trim().Split(" "); $Line = "kiki-whymath " + $Parts[0] + " " + $Parts[1]; Set-Content -Path (Join-Path $Wt "constitution_signers\allowed_signers") -Value $Line -Encoding ascii; git -C $Wt add constitution_signers/allowed_signers; git -C $Wt -c gpg.format=ssh -c gpg.ssh.program=ssh-keygen -c "user.signingkey=$KeyFwd.pub" commit -S -m "const-signing: register Kiki signing key (arms CONST-17 check)"; $CommitOk = ($LASTEXITCODE -eq 0); "COMMIT_OK=$CommitOk COMMIT=" + (git -C $Wt rev-parse --short HEAD); "SIGNED_STATUS=" + (git -C $Wt -c gpg.format=ssh -c gpg.ssh.program=ssh-keygen -c "gpg.ssh.allowedSignersFile=$Wt/constitution_signers/allowed_signers" log -1 --format=%G?); if ($CommitOk) { git -C $Wt push -u origin $Br; $PushOk = ($LASTEXITCODE -eq 0); "PUSH_OK=$PushOk REMOTE_HEAD=" + (git ls-remote origin $Br); "PR_LINK=https://github.com/kiki-s-broom/WhyMath/pull/new/$Br" } else { "COMMIT_FAILED=True — 커밋이 만들어지지 않아 푸시하지 않았습니다. 위 git 오류를 확인하세요." } } else { "ARM_REFUSED=True — 위 READY 줄에서 False인 항목을 확인하세요: MAIN_HAS_VERIFIER=False면 CONST-17 PR 머지 전, ALREADY_ARMED=True면 이미 무장됨, PUB_OK=False면 과제 S 먼저, CONSENT_OK=False면 T-1에서 ARM 입력." }
```

머지가 끝나면 작업 사본은 과제 U에서 정리합니다.

---

## 3. 과제 U — 무장 확인 (실제로 막는지 음성 시험)

### 사전 브리핑

1. **과제 명칭**: 서명 검증이 무장됐는지, 그리고 **서명 없는 헌법 변경을 실제로 거부하는지** 시험.
2. **목적**: "통과했다"만 보면 검사가 아무것도 안 보고 있어도 같은 화면이 나옵니다. 그래서 일부러 서명 없는 헌법 변경을 만들어 **거부(exit 1)** 되는지 봅니다. 시험 커밋은 임시 작업 사본에만 있고 푸시하지 않으며 끝나면 지웁니다.
3. **구체적 절차**:
   - [U-1] main 기준 임시 작업 사본을 만들고(약 10초) 무장 상태를 확인합니다(미무장이면 안내 문구가 나옵니다).
   - [U-2] 임시 사본에서 `constitution/STAGE`를 서명 없이 바꿔 커밋하고 검증기를 돌립니다. **종료 코드 1**이 정상입니다. 그리고 작업 사본을 지웁니다.
4. **성공 기준**: `ARMED=True`(미무장 안내가 없음) · `NEG_EXIT=1`. 실패 신호: `ARMED=False`(무장 PR이 아직 머지되지 않음) · `NEG_EXIT=0`(서명 없는 변경이 통과 — **심각, 즉시 세션에 알리세요**) · `NEG_EXIT=2`(측정 불가 — 출력된 사유 확인, 대개 `ssh-keygen` 없음).
5. **실행 환경**: Phaiakes9의 Windows PowerShell. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: 과제 T의 PR이 **main에 머지됨**.
6. **창 구분**: **새 창(창②)**. 창①의 변수에 의존하지 않습니다.

### [U-1] main 기준 임시 사본 + 무장 상태 확인

```powershell
# [창② U-1 확인 준비] Windows PowerShell — Phaiakes9
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$PyOk = Test-Path $Py
git cat-file -e origin/main:constitution_signers/allowed_signers 2>$null
$SignersOnMain = ($LASTEXITCODE -eq 0)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-const"
"PY_OK=$PyOk SIGNERS_ON_MAIN=$SignersOnMain"
if ($PyOk -and $SignersOnMain) { if (Test-Path $Wt) { git worktree remove --force $Wt; git worktree prune }; git worktree add --detach $Wt origin/main; $Out = (& $Py "$Wt\scripts\constitution\check_signed_changes.py" --base origin/main --head HEAD --repo $Wt 2>&1) | Out-String; "ARMED=" + (-not ($Out -match "미무장")); "CHECK_OUTPUT=" + $Out.Trim() } else { "U1_REFUSED=True — PY_OK=False면 백엔드 venv 경로 확인, SIGNERS_ON_MAIN=False면 무장 PR이 아직 머지되지 않았습니다(과제 T). 아무것도 만들지 않았습니다." }
```

### [U-2] 음성 시험 — 서명 없는 헌법 변경은 거부돼야 한다

```powershell
# [창② U-2 음성 시험] Windows PowerShell — Phaiakes9 (임시 사본에서만 커밋 — 푸시하지 않음)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-const"
$WtOk = Test-Path "$Wt\constitution\STAGE"
"WT_OK=$WtOk"
if ($WtOk) { Set-Content -Path "$Wt\constitution\STAGE" -Value "99" -Encoding ascii; git -C $Wt add constitution/STAGE; git -C $Wt -c commit.gpgsign=false -c user.name=negtest -c user.email=negtest@example.com commit -m "negative test: unsigned constitution change (local only)"; & $Py "$Wt\scripts\constitution\check_signed_changes.py" --base origin/main --head HEAD --repo $Wt --event pull_request; $NegExit = $LASTEXITCODE; "NEG_EXIT=$NegExit (1이 정상)"; git worktree remove --force $Wt; git worktree prune; "WORKTREE_REMOVED=" + (-not (Test-Path $Wt)) } else { "U2_REFUSED=True — 임시 사본이 없습니다. U-1을 먼저 실행하세요(ARMED=True가 나와야 합니다)." }
```

---

## 4. 과제 V — 이후 헌법을 개정할 때 (서명 커밋)

무장된 뒤에는 `constitution/` 등 보호 경로를 바꾸는 **모든 커밋**이 이 키로 서명돼야 합니다. 요약:

- 평소 작업(서명 불필요한 경로)은 지금과 똑같이 합니다. 서명이 필요한 것은 보호 경로를 바꾸는 커밋뿐입니다.
- 보호 경로를 바꿀 때는 커밋에 `-S`를 붙이고 키를 지정합니다. 이 클론은 여러 세션이 공유하므로 **전역/로컬 설정을 바꾸지 않고** 명령마다 `-c`로 넘깁니다(`commit.gpgsign=true`를 켜 두면 다른 세션의 커밋도 비밀번호를 묻습니다).
- 서명한 커밋은 **그대로 푸시**해야 합니다. 리베이스·스쿼시·메시지 수정(amend 이후 다른 사람이 만든 것 포함)을 하면 서명이 사라집니다. PR의 "Update branch" 버튼(main 병합)은 서명된 커밋을 건드리지 않으므로 괜찮습니다.
- **GitHub 웹 편집은 쓸 수 없습니다.** 웹 커밋은 GitHub의 서명이라 Kiki님 키가 아닙니다. 보호 경로 변경은 로컬에서 서명해 올립니다.
- 머지 큐의 스쿼시 커밋은 GitHub 서명이지만 문제없습니다. 검증은 PR 시점에 하고, 큐 단계(`merge_group`)는 판정하지 않습니다.
- 로컬 사전 확인: 서명한 커밋을 올리기 전에 `python scripts/constitution/check_signed_changes.py --base origin/main`을 돌리면 CI와 같은 판정을 미리 봅니다.

서명 커밋 만들기 (스테이징한 변경에 대해):

```powershell
# [서명 커밋] Windows PowerShell — Phaiakes9 (필요할 때만 · 비밀번호 입력 있음)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Key = Join-Path $HOME ".ssh\whymath_constitution_signing"
$KeyFwd = $Key -replace '\\', '/'
$Staged = (git diff --cached --name-only) -join " "
$HasStaged = [bool]$Staged
$PubOk = Test-Path "$Key.pub"
$Msg = Read-Host "커밋 메시지(영문/ASCII 권장 — PowerShell이 한글 인자를 깨뜨릴 수 있음)"
$MsgOk = [bool]$Msg
"HAS_STAGED=$HasStaged PUB_OK=$PubOk MSG_OK=$MsgOk STAGED=$Staged"
if ($HasStaged -and $PubOk -and $MsgOk) { git -c gpg.format=ssh -c gpg.ssh.program=ssh-keygen -c "user.signingkey=$KeyFwd.pub" commit -S -m $Msg; $Ok = ($LASTEXITCODE -eq 0); "SIGNED_COMMIT_OK=$Ok HEAD=" + (git rev-parse --short HEAD) } else { "SIGN_REFUSED=True — 스테이징된 변경이 없거나(HAS_STAGED) 공개키가 없거나(PUB_OK) 메시지가 비었습니다(MSG_OK)." }
```

## 5. 알려진 한계 · 키 분실 · 교체

- **미무장 동안은 아무것도 강제되지 않습니다.** 무장 PR(과제 T)은 **Kiki님이 직접 만드세요.** AI가 올린 "키 등록 PR"을 내용 확인 없이 승인하면 AI의 키가 등록됩니다. 등록되는 줄의 공개키 지문이 과제 S-2의 `KEY_FINGERPRINT`와 같은지 PR 파일 보기에서 확인하세요(지문은 `ssh-keygen -l -f <공개키 파일>`로 계산 가능).
- **`ci.yml`의 다른 스텝 조작은 막지 못합니다.** 서명이 필요한 것은 검증 스텝 자신과 잡 게이팅 사실(트리거·`if`·`needs`·`env` 등)뿐입니다. 앞 스텝이 환경변수로 이벤트를 위장하는 식의 우회는 이 검사의 범위 밖이며, 그런 변경은 리뷰에서 막아야 합니다.
- **필수 체크 설정은 저장소 설정(룰셋)에 있습니다.** `harness-integrity` 잡이 필수 체크가 아니면 이 검사가 빨강이어도 머지가 막히지 않습니다. 룰셋 편집은 Kiki님만 할 수 있습니다.
- **키 분실·유출**: 비밀키를 잃으면 서명할 수 없어 보호 경로를 못 바꿉니다. 새 키로 교체하려면 *기존* 키의 서명이 필요하므로(PR이 자기 키를 등록해 통과하는 길을 막기 위함) 분실 시에는 Kiki님이 저장소 관리자 권한으로 룰셋에서 일시 우회하거나 `constitution_signers/allowed_signers`를 직접 정정해야 합니다. 비밀번호 있는 키와 오프라인 백업(예: 암호화된 USB)을 권장합니다.
- **키 교체**(분실 아님): 새 키를 만들고, *기존* 키로 서명한 커밋으로 `allowed_signers`에 새 줄을 추가한 뒤, 이후 새 키로 서명합니다. 옛 줄 삭제도 서명이 필요합니다.
- 이 런북의 PowerShell 블록은 이 세션에서 **직접 실행해 보지 못했습니다**(세션에 PowerShell 없음). 대신 같은 패턴의 기존 런북 구조를 따랐고 쓰기 블록 스캐너(`check_runbook_blocks.py`)를 통과시켰습니다. 실행 중 오류가 나면 출력 전체를 세션에 전달하세요.
