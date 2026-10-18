# SEC-34 런북 — Phaiakes9 자격증명 전량 폐기·재발급 (Kiki · Phaiakes9)

> **판정 기준**: 작성 시점 `origin/main` `e30984983`. 태스크 `SEC-34-phaiakes9-cryptominer-incident-response`
> acceptance ②(자격증명 전량 로테이션)를 실행하는 런북이다. **이 태스크는 `owner: kiki`라 세션이 착수(claim)하지 못했다**
> (`backlog.py start`가 사람 소유 태스크로 거부 — `--as kiki` 우회는 하지 않았다). 착수 기입은 Kiki 본인 몫이다(§0 명령).
>
> **이 런북의 범위**: acceptance ② 전부. **범위 밖(별도 절차 필요)**: ① 침해 범위 실측 잔여(Run 키·서비스·백업 연속성 전수),
> ③ 학생 데이터 노출 판정(시점 대조 — 법령 유래 통지 판단은 기계 대체 금지), ⑤ 재발 탐지 배선, 백신 **치료**(MSERT `/N`은 탐지 전용).
> §3은 "시크릿을 새로 만들어 이 머신에 둬도 되는가"를 가르는 **지표 점검**이지 머신이 깨끗하다는 증명이 아니다.

## 사전 브리핑 (6항목)

### ① 과제 명칭
**Phaiakes9 자격증명 전량 폐기·재발급** — 감염 기간 중 이 머신에 있었거나 입력된 시크릿을 전부 무효화하고 새로 발급합니다.

### ② 목적
2026-09-10에 채굴 예약 작업(`GoogleUpdateTask` 위장)이 SYSTEM 권한으로 발견됐습니다. 프로세스 종료·자동실행 차단·13개 파일 격리까지는 끝났지만, 감염 기간(최대 2026-08-22 전후부터 3주 이상) 동안 **유출됐을 수 있는 토큰·키는 머신 밖에서 계속 유효**합니다.
채굴 드로퍼는 자격증명 탈취 모듈을 동반하는 경우가 흔하므로 유출 증거가 없어도 노출로 간주합니다. 머신을 정화해도 이미 나간 토큰은 되살아나지 않습니다.
결과는 태스크 증적(done)과 사고 대장(HARN-118)에 쓰이고, 마지막 항목(성능 재측정 `OPS-75`)의 착수 조건 일부가 됩니다.

### ③ 구체적 절차 (전체 약 1~1.5시간 — 추정, 실측 전)
| 절 | 무엇이 일어나는가 | 어디서 | 소요(추정) |
|---|---|---|---|
| §1 | 도구·로그인 상태·시크릿 인벤토리(이름·길이만) | 창 A | 1~2분 |
| §2 | **폐기**: GitHub·Anthropic·OpenRouter 등 웹 콘솔에서 키 삭제 + 완료 기록 | 아무 기기 + 창 A | 20~40분 |
| §3 | 이 머신 신뢰 지표 점검(Defender 예외·IoC 잔존·자동실행) — 통과해야 §4 이후 진행 | **창 B(관리자)** | 3~8분 |
| §3b | (필요할 때만) 악성 패턴에 걸린 Defender 예외 제거 | 창 B | 수 초 |
| §4 | 로컬 시크릿 회전(JWT·암호화 키 4종·HMAC·salt) | 창 A | 1~2분 |
| §5 | gh 재로그인 → GitHub PAT·외부 서비스 키 재발급 | 창 A | 10~15분 |
| §6 | (등록된 경우만) 배포 SSH 키 교체 | 창 A | 5~10분 |
| §7 | 백업 age 키쌍 교체 + 백업 1회 검증 + 개인키를 머신 밖으로 | 창 A | 5~10분 |
| §8 | 최종 점검 요약 | 창 A | 1분 |

**순서의 이유**: 폐기(§2)는 새 비밀을 만들지 않으므로 **오염 가능한 머신에서도, 다른 기기에서도** 안전합니다. 재발급은 새 비밀이 이 머신에 저장되므로, 머신이 지표상 정상일 때만(§3) 합니다. 그래서 §2 → §3 → §4~§7입니다.

### ④ 성공 기준
| 판정 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `INVENTORY_DONE` | `True` | `MISSING_TOOLS`에 나온 도구를 설치(아래 §1 실패 대처) |
| §2b `NO=` | `0` | 미완료 항목을 웹 콘솔에서 마저 하고 §2b 재실행 |
| §3 `TRUST_OK` | `True` | 출력된 항목별 건수를 세션에 전달 — **§4 이후는 실행하지 않습니다** |
| §4 `LOCAL_UNVERIFIED` | `0` | 해당 이름을 세션에 전달 |
| §5c `EXTERNAL_OLD_ACTIVE` | `0` | `ACTIVE`로 나온 서비스 콘솔에서 해당 키를 삭제(폐기가 안 된 상태) |
| §7b `VERIFY_EXIT` | `0` | 구 키쌍으로 복귀하지 말고 세션에 전달 |
| §8 `STALE_ROTATABLE` | 비어 있음 | 나온 이름의 재발급을 §5·§6에서 다시 |

**`REFUSED`로 끝나는 줄은 실패가 아니라 가드가 일부러 멈춘 것입니다.** 이유가 같은 줄에 찍힙니다. 다음 블록으로 넘어가지 말고 그 줄을 세션에 전달하십시오.
`UNKNOWN`·`UNPROBED`는 **통과가 아닙니다**("모른다 ≠ 아니다") — 콘솔에서 사람이 확인해야 하는 항목입니다.

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 결과 폴더는 저장소 밖 `C:\Users\kiki\Desktop\__AI\sec34-out\<시각>` 이며 **시크릿 값은 어떤 파일에도 쓰지 않습니다**(이름·길이·판정만).
선행 조건: ⓐ 인터넷 연결 ⓑ 웹 콘솔에 로그인할 수 있는 기기 1대(휴대폰도 됩니다) ⓒ Docker Desktop 가동(§4 행수 판정·§7b) ⓓ `gh`·`age`·`age-keygen`·`ssh-keygen` 설치(§1이 점검).
이 런북의 블록은 **저장소 코드를 실행하지 않습니다**(§7b만 `scripts/backup/`을 쓰며 스스로 `origin/main`과 동등성을 판정). 블록 첫머리의 `git log -1 --oneline`은 참고 출력이며 어떤 해시여도 §1~§6은 동작합니다.

### ⑥ 창 구분
| 창 | 종류 | 쓰는 절 |
|---|---|---|
| **창 A** | 평소 쓰는 **일반** PowerShell 1개 | §1, §2b, §4~§8 |
| **창 B** | **관리자 권한** PowerShell 1개(시작 메뉴 → PowerShell 우클릭 → 관리자 권한으로 실행) | §3, §3b 전용 |

변수를 창 사이에 넘기지 않습니다. 각 블록이 **디스크의 최신 결과 폴더**에서 상태를 스스로 다시 읽으므로, 창을 닫았다 다시 열어도 이어집니다(단 §1을 건너뛰면 결과 폴더가 없어 `REFUSED`).
`Read-Host`가 입력을 기다리는 동안 그 창은 **입력 전용**입니다. 비밀 입력(`-AsSecureString`)은 **글자가 화면에 보이지 않습니다** — 붙여넣고 Enter를 누르십시오. 길이가 0으로 나오면 붙여넣기가 안 된 것입니다.

---

## 먼저 알아 둘 것 (코드·문서 실측에서 나온 함정)

1. **시크릿 값은 채팅에 붙이지 않습니다.** 세션에는 판정 줄(`EXIT`·건수·길이·접두)만 인용문으로 전달하십시오. 아래 블록은 값을 화면·파일에 출력하지 않도록 설계했습니다. 출력되는 것은 이름·길이·`github_pat_`처럼 **공개된 형식 접두**뿐입니다.
2. **이 머신에서 만든 새 시크릿은 머신이 정상일 때만 안전합니다.** §3이 통과하지 않으면 §4 이후 쓰기 블록은 스스로 거부합니다. §3이 못 잡는 것(예: 지표에 안 걸리는 지속성)은 이 런북이 증명하지 못합니다.
3. **저장 데이터 암호화 키 4종은 교체가 아니라 *회전*입니다.** 구 키를 폴백(`*_DECRYPTION_FALLBACK_KEYS`)에 남기지 않고 새 키만 두면 **기존 암호문은 영구히 복호 불가**(lockout)입니다(`api/_crypto.py` `MultiKeyCipher`). 반대로 남기면 구 키가 유출됐을 때 **기존 행의 기밀성은 회복되지 않습니다**(키 간 재암호화는 후속 — 같은 모듈 docstring의 ③).
   그래서 §4가 암호문 행수를 먼저 세어 판정합니다 — 행수 0이면 폴백 불필요, 1 이상이거나 **셀 수 없으면(-1)** 폴백을 남깁니다(잃는 쪽이 더 나쁘다). 남긴 경우의 잔여 위험은 사고 대장·acceptance ③에 기록해야 합니다.
4. **DB·Redis 비밀번호(`WHYMATH_DB_PASSWORD`·`WHYMATH_REDIS_PASSWORD`)는 자동 교체하지 않습니다.** 서버(컨테이너)에 이미 설정된 비밀번호와 환경변수가 어긋나면 서비스가 끊깁니다. 있으면 §4가 이름만 알려 줍니다. (`whymath-pg`는 trust 인증이라 비밀번호 자체가 없을 수 있습니다 — §1이 포트 노출 여부를 함께 보여 줍니다.)
5. **JWT 시크릿을 바꾸면 발급된 토큰이 전부 무효**가 됩니다. 의도한 효과입니다(2026-09-07 `problem_attempt` 0행 — 실제 학생 세션 없음).
6. **새 값은 환경변수가 *다음 프로세스부터* 적용**됩니다. 가동 중인 서버·Ollama는 옛 값을 메모리에 들고 있으므로 §4~§5 후 **재기동이 필요**합니다(재기동 절차는 이 런북 범위 밖 — 기존 가동 절차를 따르십시오).
7. **폐기 검증의 한계**: GitHub에 저장된 시크릿(`PR_AUTO_RESYNC_TOKEN` 등)은 값을 읽을 수 없어 "옛 값이 죽었는가"를 호출로 확인할 수 없습니다 — 근거는 §2b 콘솔 기록뿐입니다. 이 머신 환경변수에 있는 외부 서비스 키는 **옛 값으로 호출해 거부(401)되는지** §5c가 직접 확인합니다(변별력: 폐기 전 200 → 폐기 후 401).
8. **외부 서비스 응답 코드는 이 런북 작성 환경에서 일부만 실측했습니다.** Anthropic `GET /v1/models`는 잘못된 키에 401을 실측 확인했고, GitHub·OpenRouter·DeepSeek·OpenAI·Langfuse는 **작성 환경의 네트워크 정책으로 실측하지 못했습니다**(문서 기반). 그래서 §5c는 `401`만 "거부", `200`만 "유효"로 보고 그 외(404·5xx·무응답)는 `UNKNOWN`으로 둡니다.
9. **GitHub PAT의 쓰기 권한은 호출로 증명되지 않습니다.** §5b는 새 토큰이 저장소를 읽을 수 있음(HTTP 200)만 확인합니다. `Contents`·`Pull requests` 쓰기 권한의 최종 판정은 `pr-auto-resync` 워크플로가 실제 PR에 돌 때입니다.

---

## 0. 태스크 착수 기입 (Kiki 본인 — 세션이 대신할 수 없습니다)

`SEC-34`는 사람 소유 태스크라 세션의 `start`가 거부됐습니다. 착수 대장 기입은 아래로 합니다(읽기 전용 확인 후 기입).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A] §0 태스크 착수 — 대장 기입은 Kiki 본인 몫
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Branch = (git branch --show-current)
$TaskFile = Test-Path "backlog\tasks\SEC-34-phaiakes9-cryptominer-incident-response.yaml"
$Ready = ($Branch -eq "main") -and $TaskFile
if ($Ready) { python scripts\harness\backlog.py start SEC-34-phaiakes9-cryptominer-incident-response --as kiki; "START_EXIT=$LASTEXITCODE" } else { "START_REFUSED  Branch=$Branch  TaskFilePresent=$TaskFile  (Branch가 main이 아니면 다른 세션이 쓰던 브랜치입니다 - 전환하지 마십시오. TaskFilePresent=False면 이 체크아웃이 낡았습니다)" }
```
- **성공**: `START_EXIT=0`. **`START_REFUSED`**면 이유 변수를 세션에 전달하십시오(이 절을 건너뛰어도 §1 이후는 진행 가능합니다 — 착수 기입은 대장 정합용이고 로테이션 자체와 독립입니다).

---

## 1. 사전 점검 + 시크릿 인벤토리 — 읽기 전용 (결과 폴더만 만듦)

**왜 인벤토리를 먼저 하는가**: 위 acceptance의 "최소 목록"은 바닥이지 전부가 아닙니다. 이 머신에 **실제로 있는** 시크릿 이름을 먼저 읽어야 빠뜨리지 않습니다. 또 §2에서 GitHub OAuth를 철회하면 `gh` 로그인이 끊기므로 **GitHub 저장소 시크릿 목록은 그 전에** 읽어 둡니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §1 사전 점검 + 시크릿 인벤토리 — 읽기 전용(값은 출력하지 않는다. 이름·길이만)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$BackupDir = "C:\Users\kiki\Desktop\__AI\WhyMath-backups"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out = "C:\Users\kiki\Desktop\__AI\sec34-out\$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$Missing = @(@("git","gh","ssh-keygen","age","age-keygen","docker") | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
gh auth status 2>$null | Out-Null
$GhLoggedIn = ($LASTEXITCODE -eq 0)
$Rx = "KEY|SECRET|TOKEN|PASSWORD|PASSWD|SALT|CREDENTIAL"
$EnvRows = @()
foreach ($Scope in @("User","Machine")) { $Vars = [Environment]::GetEnvironmentVariables($Scope); foreach ($K in $Vars.Keys) { if ($K -match $Rx) { $EnvRows += [pscustomobject]@{ Scope = $Scope; Name = $K; Length = ("" + $Vars[$K]).Length } } } }
"--- 환경변수(이름·길이만) ---"
$EnvRows | Sort-Object Scope, Name | Format-Table -AutoSize
$Files = @(Get-ChildItem "$Repo\.env","$Repo\src\backend\.env","$Repo\deploy\*.env" -Force -ErrorAction SilentlyContinue)
$FileRows = @()
foreach ($F in $Files) { foreach ($Line in (Get-Content $F.FullName -ErrorAction SilentlyContinue)) { if ($Line -match "^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$") { if ($Matches[1] -match $Rx) { $FileRows += [pscustomobject]@{ File = $F.Name; Name = $Matches[1]; Length = $Matches[2].Trim().Length } } } } }
"--- env 파일 속 시크릿성 키(이름·길이만) ---"
$FileRows | Format-Table -AutoSize
"--- ~\.ssh 파일(이름·크기만) ---"
Get-ChildItem "$env:USERPROFILE\.ssh" -File -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
$DockerAuths = @((Get-Content "$env:USERPROFILE\.docker\config.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json).auths.PSObject.Properties.Name | Where-Object { $_ })
"--- docker 로그인 호스트 ---"
$DockerAuths
$GhSecrets = @(gh secret list --repo kiki-s-broom/WhyMath 2>$null)
"--- GitHub 저장소 시크릿(이름·갱신 시각) ---"
$GhSecrets
$HasDeployKey = @($GhSecrets | Where-Object { $_ -match "^DEPLOY_SSH_KEY\b" }).Count
$AgeFiles = @(Get-ChildItem "$BackupDir\*.dump.age" -ErrorAction SilentlyContinue)
$PlainDumps = @(Get-ChildItem "$BackupDir\*.dump" -ErrorAction SilentlyContinue)
$IdentityOnDisk = Test-Path "$env:USERPROFILE\whymath-backup-identity.key"
$RecipientsFile = Test-Path "$BackupDir\recipients.txt"
$Ports = @(docker ps --filter "name=whymath" --format "{{.Names}}  {{.Ports}}" 2>$null)
"--- whymath 컨테이너 포트 ---"
$Ports
$PublicBind = @($Ports | Where-Object { $_ -match "0\.0\.0\.0:|\[::\]:" }).Count
"IS_ADMIN=$IsAdmin"
"MISSING_TOOLS=$($Missing -join ',')"
"GH_LOGGED_IN=$GhLoggedIn  HAS_DEPLOY_SSH_KEY=$HasDeployKey"
"ENV_SECRET_LIKE=$($EnvRows.Count)  FILE_SECRET_LIKE=$($FileRows.Count)  GH_SECRETS=$($GhSecrets.Count)  DOCKER_AUTH_HOSTS=$($DockerAuths.Count)"
"AGE_BACKUPS=$($AgeFiles.Count)  PLAIN_DUMPS=$($PlainDumps.Count)  IDENTITY_ON_DISK=$IdentityOnDisk  RECIPIENTS_FILE=$RecipientsFile"
"DB_PORTS_PUBLIC_BIND=$PublicBind"
"OUT_DIR=$Out  OUT_EXISTS=$(Test-Path $Out)"
"INVENTORY_DONE=$(($Missing.Count -eq 0) -and $GhLoggedIn)"
```
- **성공**: `INVENTORY_DONE=True` · `OUT_EXISTS=True`.
- **판독**: ⓐ `DB_PORTS_PUBLIC_BIND`가 1 이상이면 컨테이너 포트가 **모든 인터페이스에 열려** 있다는 뜻이고 `whymath-pg`가 trust 인증이면 같은 네트워크의 누구나 DB를 읽습니다 — 이 런북의 범위는 아니지만 **반드시 세션에 알려 주십시오**. ⓑ `PLAIN_DUMPS`가 1 이상이면 평문 덤프가 디스크에 있습니다(§7에서 처분 결정). ⓒ 인벤토리에 위 §2 표에 없는 서비스 이름이 보이면 세션에 전달하십시오(체크리스트에 추가해야 합니다).
- **실패 시 대처**: `MISSING_TOOLS`에 `age`·`age-keygen`이 있으면 `winget install FiloSottile.age`, `gh`가 있으면 `winget install GitHub.cli`를 한 뒤 **새 PowerShell 창**에서 §1을 다시 실행하십시오(PATH 갱신). `GH_LOGGED_IN=False`면 지금은 §2를 먼저 진행해도 되지만 **GitHub 저장소 시크릿 목록(§6 판단 근거)이 비므로** 가능하면 `gh auth login`으로 로그인한 뒤 §1을 다시 하십시오.

---

## 2. 폐기 — 웹 콘솔에서 (아무 기기에서나 · 새 비밀을 만들지 않으므로 안전)

**먼저 폐기하고 나중에 만듭니다.** 아래 12개를 웹 콘솔에서 하나씩 처리하고, 끝나면 §2b로 기록합니다. 메뉴 이름은 서비스 개편으로 바뀔 수 있어 **경로는 방향 표시**입니다(없으면 설정 검색창에 항목명을 넣으십시오).
**해당 없음(`na`)도 답입니다** — 그 서비스를 이 머신에서 쓴 적이 없으면 `na`로 기록합니다. 판단이 안 서면 `n`으로 두고 세션에 물으십시오(`n`이 남아 있으면 §4 이후가 거부됩니다 — 의도입니다).

| # | 대상 | 무엇을 | 확인 방법 |
|---|---|---|---|
| R1 | GitHub **개인 액세스 토큰(PAT)** — `PR_AUTO_RESYNC_TOKEN` 포함 | 계정 Settings → Developer settings → Personal access tokens → **Fine-grained tokens와 Tokens (classic) 양쪽** 모두에서, 이 머신에서 만든 것을 전부 삭제 | 두 목록에 이 머신용 토큰이 남지 않음 |
| R2 | GitHub **OAuth 앱 권한**(GitHub CLI·Git Credential Manager 등) | Settings → Applications → Authorized OAuth Apps → 해당 항목 Revoke. `gh`·`git` 로그인이 이 머신에 저장한 토큰이 여기 속합니다 | 목록에서 사라짐(이후 `gh`는 로그아웃 상태가 됩니다 — 정상) |
| R3 | GitHub **SSH 키·배포 키** | Settings → SSH and GPG keys에서 이 머신 유래 키 삭제. 저장소 `kiki-s-broom/WhyMath` → Settings → Deploy keys도 확인 | 목록에 이 머신 유래 키 없음 |
| R4 | GitHub **로그인 세션** + 보안 로그 | Settings → Sessions에서 모든 세션 종료. Settings → Security log에서 **2026-08-22 ~ 2026-09-10** 구간의 낯선 IP·`personal_access_token.*`·`oauth_authorization.*`·`public_key.create` 이벤트를 눈으로 확인 | 낯선 이벤트 건수를 세션에 전달(0이어도 전달) |
| R5 | GitHub **조직 감사 로그** | 조직 `kiki-s-broom` → Settings → Audit log(소유자 권한)에서 같은 구간 점검 | 낯선 이벤트 건수 전달 |
| R6 | **Anthropic** | Console → API keys에서 키 **전부 폐기(revoke)** — 재발급하지 않습니다(`ARCH-66`: 2026-12-31까지 API 미사용, 쓰지 않는 유효 키는 유출 시 과금 위험만 남김). claude.ai는 계정 설정의 **모든 기기 로그아웃** 항목(없으면 비밀번호 변경으로 대체) | Console 키 목록이 비어 있음 |
| R7 | **OpenRouter**(현재 기본 클라우드 좌석) | Keys 페이지에서 키 삭제 + Activity에서 감염 구간의 **낯선 사용량** 점검(과금 탈취 지표) | 키 삭제 + 사용량 이상 여부 전달 |
| R8 | **DeepSeek · OpenAI** | 각 플랫폼 API keys에서 이 머신에서 쓴 키 삭제(쓴 적 없으면 `na`) | 목록 정리 |
| R9 | **Langfuse** | 쓰는 곳(클라우드 또는 자체 호스팅)의 프로젝트 Settings → API Keys에서 **키 쌍 삭제** | 목록 정리 |
| R10 | **Kakao · Naver 개발자 콘솔** | 클라이언트 시크릿 재발급(실제 OAuth를 등록한 경우만. 등록 전이면 `na`) | 재발급 완료 또는 `na` |
| R11 | **Google 계정**(Chrome 로그인·Drive 오프사이트 폴더) | 보안 점검에서 알 수 없는 기기 로그아웃 + 비밀번호 변경. Drive 폴더의 "최근 활동"에서 낯선 접근 확인 | 낯선 활동 건수 전달 |
| R12 | **레지스트리 토큰 · 브라우저 저장 계정** | Docker Hub·GHCR 등에 로그인한 토큰 삭제(§1이 `DOCKER_AUTH_HOSTS`로 보여 줍니다). 브라우저에 저장된 비밀번호·세션 중 고가치 계정(금융·클라우드·이메일)은 비밀번호 재설정 여부를 **본인이 판단**(런북이 대신 정하지 않습니다) | 처리 여부 |

> **R4·R5·R7·R11은 "낯선 이벤트 건수"가 중요합니다.** 그 숫자가 0이 아니면 acceptance ①(침해 범위)·③(노출 판정)이 달라지므로 세션이 이어서 판단합니다 — 이 런북은 건수를 **전달받는 것**까지입니다.

### 2b. 폐기 완료 기록 (창 A)

항목마다 `y`(완료) · `n`(미완료) · `na`(해당 없음)를 입력합니다. **시크릿 값은 묻지 않습니다.**

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §2b 폐기 완료 기록 — 항목마다 y/n/na 입력(비밀 값은 묻지 않는다)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$Items = @("R1 GitHub PAT 전부 삭제","R2 GitHub OAuth 앱 권한 철회","R3 GitHub SSH 키 배포 키 삭제","R4 GitHub 세션 종료 보안 로그 점검","R5 GitHub 조직 감사 로그 점검","R6 Anthropic 키 폐기 및 claude.ai 로그아웃","R7 OpenRouter 키 삭제 및 사용량 점검","R8 DeepSeek OpenAI 키 삭제","R9 Langfuse 키 삭제","R10 Kakao Naver 클라이언트 시크릿 재발급","R11 Google 계정 점검","R12 레지스트리 토큰 및 브라우저 저장 계정")
if ($OutOk) {
  $Rows = @()
  foreach ($Item in $Items) {
    $Ans = ""
    while (@("y","n","na") -notcontains $Ans) { $Ans = (Read-Host "$Item  [y/n/na]").Trim().ToLower() }
    $Rows += [pscustomobject]@{ Item = $Item; Answer = $Ans; At = (Get-Date -Format "s") }
  }
  $Rows | ConvertTo-Json | Set-Content -Path "$Out\revoke_checklist.json" -Encoding UTF8
  $Back = @(Get-Content "$Out\revoke_checklist.json" -Raw | ConvertFrom-Json)
  "REVOKE_RECORDED=$($Back.Count)  YES=$(@($Back | Where-Object { $_.Answer -eq 'y' }).Count)  NO=$(@($Back | Where-Object { $_.Answer -eq 'n' }).Count)  NA=$(@($Back | Where-Object { $_.Answer -eq 'na' }).Count)"
} else {
  "REVOKE_RECORD_REFUSED  OutOk=$OutOk  Out='$Out'  (결과 폴더가 없습니다 - §1을 먼저 실행하십시오)"
}
```
- **성공**: `REVOKE_RECORDED=12` 그리고 `NO=0`. `NA`가 몇 건이든 괜찮지만 **`na`로 답한 항목의 이유를 세션에 한 줄씩 전달**하십시오(예: "R10 — OAuth 미등록").
- **실패 시 대처**: `NO`가 1 이상이면 그 항목을 콘솔에서 끝낸 뒤 **이 블록을 처음부터 다시** 붙여넣으십시오(새 기록이 이전 기록을 덮어씁니다).

---

## 3. 이 머신 신뢰 지표 점검 (창 B · 관리자)

**왜 필요한가**: §4~§7은 새 비밀을 이 머신에 저장합니다. 채굴이 추가한 **보안 검사 예외**가 남아 있거나, 격리 대상 파일이 되살아났거나, 예약 작업·자동실행이 되살아났다면 새 비밀도 같은 경로로 다시 나갑니다.
`acceptance ⑦`이 "여전히 미완"으로 남긴 것이 정확히 이 셋입니다(보안 예외 원복·백신 전체 검사·자동실행 전수).

**이 점검이 증명하지 못하는 것**: 알려진 지표(이미 확인된 13개 파일 경로·`\Microsoft\Windows\Google\` 작업·Run 키·WMI·시작 폴더)만 봅니다. **지표에 안 걸리는 지속성은 못 봅니다.** `TRUST_OK=True`는 "지표상 이상 없음"이지 "깨끗함"이 아닙니다. 또 Defender 예외 목록은 **관리자 권한이 아니면 보이지 않으므로**(보이지 않는 상태를 "없음"으로 읽지 않도록) 일반 창에서는 `TRUST_OK`가 거부됩니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 B · 관리자] §3 머신 신뢰 지표 점검 — 읽기 전용 점검 + 판정 파일 1개 기록
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$IocRx = "ProgramData\\Google|C:\\Windows\\svchost\.exe|KB5019959|\.png\.00\d"
$Mp = Get-MpPreference -ErrorAction SilentlyContinue
$MpOk = ($null -ne $Mp)
$Excl = @((@($Mp.ExclusionPath) + @($Mp.ExclusionProcess) + @($Mp.ExclusionExtension)) | Where-Object { $_ })
$ExclVisible = $IsAdmin -and $MpOk -and (@($Excl | Where-Object { $_ -match "N/A" }).Count -eq 0)
$ExclIoc = @($Excl | Where-Object { $_ -match $IocRx })
"--- Defender 예외 전체(사람이 눈으로 확인) ---"
$Excl
$St = Get-MpComputerStatus -ErrorAction SilentlyContinue
$Rtp = ($St.RealTimeProtectionEnabled -eq $true)
"--- Defender 상태 ---"
"RealTimeProtection=$($St.RealTimeProtectionEnabled)  AMService=$($St.AMServiceEnabled)  SignatureUpdated=$($St.AntivirusSignatureLastUpdated)  FullScanEnd=$($St.FullScanEndTime)"
$IocPaths = @("C:\Windows\svchost.exe","C:\ProgramData\KB5019959.exe","C:\ProgramData\Google\7z.exe")
$IocFound = @($IocPaths | Where-Object { Test-Path $_ })
$IocFound += @(Get-ChildItem "C:\ProgramData\Google" -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { $_.FullName -match "\\Locales\\(MA|RO|UN|WI|XM)\.pak$|\.png\.00\d$" } | ForEach-Object { $_.FullName })
$Tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.State -ne "Disabled" })
$TaskHits = @($Tasks | Where-Object { (($_.Actions | ForEach-Object { "$($_.Execute) $($_.Arguments)" }) -join " ") -match "ProgramData\\Google|C:\\Windows\\svchost\.exe|KB5019959" })
$GoogleTasks = @($Tasks | Where-Object { $_.TaskPath -like "\Microsoft\Windows\Google\*" })
$RunRows = @()
foreach ($Key in @("HKLM:\Software\Microsoft\Windows\CurrentVersion\Run","HKCU:\Software\Microsoft\Windows\CurrentVersion\Run","HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run")) { $Prop = Get-ItemProperty $Key -ErrorAction SilentlyContinue; if ($Prop) { foreach ($Entry in $Prop.PSObject.Properties) { if ($Entry.Name -notmatch "^PS") { $RunRows += [pscustomobject]@{ Key = $Key; Name = $Entry.Name; Data = [string]$Entry.Value } } } } }
$RunSusp = @($RunRows | Where-Object { $_.Data -match "ProgramData|\\Temp\\|powershell|cmd /c|mshta|rundll32|http" })
$Wmi = @(Get-CimInstance -Namespace "root\subscription" -ClassName "__EventConsumer" -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "SCM Event Log Consumer" })
$Startup = @(Get-ChildItem "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp","$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne "desktop.ini" })
"--- 지표별 적중(0이어야 정상) ---"
"IOC_FILES_REMAINING=$($IocFound.Count)  ENABLED_TASKS_WITH_IOC=$($TaskHits.Count)  ENABLED_GOOGLE_PATH_TASKS=$($GoogleTasks.Count)  RUN_KEY_SUSPECT=$($RunSusp.Count)  WMI_CONSUMERS=$($Wmi.Count)  STARTUP_ITEMS=$($Startup.Count)"
$IocFound
$RunSusp | Select-Object Key, Name | Format-Table -AutoSize
$Startup | Select-Object Name | Format-Table -AutoSize
$AvAns = (Read-Host "백신 전체 검사를 끝냈고 탐지가 0건이거나 조치까지 끝냈습니까? [y/n]").Trim().ToLower()
$ExclAns = (Read-Host "위에 출력된 Defender 예외 전부를 직접 추가했거나 용도를 압니까? [y/n]").Trim().ToLower()
$Trust = $OutOk -and $ExclVisible -and $Rtp -and ($ExclIoc.Count -eq 0) -and ($IocFound.Count -eq 0) -and ($TaskHits.Count -eq 0) -and ($GoogleTasks.Count -eq 0) -and ($RunSusp.Count -eq 0) -and ($Wmi.Count -eq 0) -and ($Startup.Count -eq 0) -and ($AvAns -eq "y") -and ($ExclAns -eq "y")
if ($OutOk) {
  [pscustomobject]@{ TrustOk = $Trust; At = (Get-Date -Format "s"); IsAdmin = $IsAdmin; ExclVisible = $ExclVisible; Rtp = $Rtp; ExclIoc = $ExclIoc.Count; IocFiles = $IocFound.Count; TaskHits = $TaskHits.Count; GoogleTasks = $GoogleTasks.Count; RunSuspect = $RunSusp.Count; Wmi = $Wmi.Count; Startup = $Startup.Count; AvConfirmed = $AvAns; ExclConfirmed = $ExclAns } | ConvertTo-Json | Set-Content -Path "$Out\trust.json" -Encoding UTF8
  $Back = Get-Content "$Out\trust.json" -Raw | ConvertFrom-Json
  "TRUST_RECORDED=$($Back.TrustOk)  At=$($Back.At)"
} else {
  "TRUST_RECORD_REFUSED  OutOk=$OutOk  Out='$Out'  (결과 폴더가 없습니다 - §1을 먼저 실행하십시오)"
}
"TRUST_OK=$Trust  IsAdmin=$IsAdmin  ExclVisible=$ExclVisible  ExclTotal=$($Excl.Count)  Rtp=$Rtp  ExclIoc=$($ExclIoc.Count)  AvAns=$AvAns  ExclAns=$ExclAns"
```
- **성공**: `TRUST_OK=True`. 그러면 §4로 갑니다.
- **`TRUST_OK=False`면 §4 이후를 실행하지 않습니다**(쓰기 블록이 `trust.json`을 다시 읽어 스스로 거부합니다). 어느 항목이 False·0이 아닌지 줄을 세션에 전달하십시오. 흔한 원인:
  - `IsAdmin=False` / `ExclVisible=False` → **일반 창에서 실행했습니다.** 창 B(관리자)에서 다시.
  - `Rtp=False` → 실시간 보호가 꺼져 있습니다. 채굴이 껐을 수 있으므로 Windows 보안에서 켠 뒤 다시(꺼진 이유 자체를 세션에 전달).
  - `ExclIoc` 1 이상 → **§3b**로 악성 패턴 예외를 제거한 뒤 이 블록을 다시.
  - `IOC_FILES_REMAINING`·`ENABLED_*` 1 이상 → **격리·비활성화가 풀렸거나 재감염**입니다. 세션에 즉시 전달하고 멈추십시오(§3b로 해결되지 않습니다).
  - `AvAns`·`ExclAns`가 `y`가 아님 → 백신 전체 검사(Windows 보안 → 바이러스 및 위협 방지 → 검사 옵션 → 전체 검사)를 끝낸 뒤, 예외 목록의 모든 항목을 확인한 뒤 다시. 용도를 모르는 예외가 있으면 `n`으로 답하고 세션에 목록을 전달.

### 3b. 악성 패턴에 걸린 Defender 예외 제거 (창 B · 필요할 때만)

§3이 `ExclIoc` 1 이상을 보고했을 때만 실행합니다. **알려진 악성 패턴**(`C:\ProgramData\Google` 하위·`C:\Windows\svchost.exe`·`KB5019959`·`.png.00N`)에 걸린 예외만 지우고, 그 외 예외는 건드리지 않습니다(직접 추가한 개발 예외를 지우지 않으려는 것). 제거 전 목록은 결과 폴더에 보존됩니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 B · 관리자] §3b 악성 패턴 Defender 예외 제거 — 패턴에 걸린 것만
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$IocRx = "ProgramData\\Google|C:\\Windows\\svchost\.exe|KB5019959|\.png\.00\d"
$Mp = Get-MpPreference -ErrorAction SilentlyContinue
$Paths = @($Mp.ExclusionPath | Where-Object { $_ -and ($_ -match $IocRx) })
$Procs = @($Mp.ExclusionProcess | Where-Object { $_ -and ($_ -match $IocRx) })
$Exts = @($Mp.ExclusionExtension | Where-Object { $_ -and ($_ -match $IocRx) })
$Total = $Paths.Count + $Procs.Count + $Exts.Count
$Ready = $OutOk -and $IsAdmin -and ($Total -gt 0)
if ($Ready) {
  @{ ExclusionPath = $Paths; ExclusionProcess = $Procs; ExclusionExtension = $Exts } | ConvertTo-Json | Set-Content -Path "$Out\defender_exclusions_removed.json" -Encoding UTF8
  foreach ($Item in $Paths) { Remove-MpPreference -ExclusionPath $Item }
  foreach ($Item in $Procs) { Remove-MpPreference -ExclusionProcess $Item }
  foreach ($Item in $Exts) { Remove-MpPreference -ExclusionExtension $Item }
  $After = Get-MpPreference
  $Left = @((@($After.ExclusionPath) + @($After.ExclusionProcess) + @($After.ExclusionExtension)) | Where-Object { $_ -and ($_ -match $IocRx) }).Count
  "EXCLUSIONS_REMOVED=$Total  IOC_EXCLUSIONS_LEFT=$Left  SAVED=$(Test-Path "$Out\defender_exclusions_removed.json")"
} else {
  "REMOVE_REFUSED  OutOk=$OutOk  IsAdmin=$IsAdmin  IocExclusions=$Total  (0이면 제거할 것이 없습니다)"
}
```
- **성공**: `IOC_EXCLUSIONS_LEFT=0` + `SAVED=True`. 끝나면 **§3 블록을 다시** 실행해 `TRUST_OK`를 갱신합니다.
- **되돌리기**: 오탐이어서 다시 넣어야 하면 보존 파일(`defender_exclusions_removed.json`)의 경로를 `Add-MpPreference -ExclusionPath`로 복원합니다.

---

## 4. 로컬 시크릿 회전 (창 A) — JWT · 암호화 키 4종 · HMAC · 감사 salt

**선행 조건(블록이 스스로 재검사)**: §2b 기록에 `n`이 0건 + §3의 `TRUST_OK=True`. 둘 중 하나라도 아니면 **아무것도 바꾸지 않고 거부**합니다.

**무엇을 바꾸는가**: 사용자 환경변수와 `.env`·`src\backend\.env`·`deploy\*.env` 파일에 **이미 값이 있는 이름만** 교체합니다(없는 이름은 새로 만들지 않습니다 — 켜져 있지 않던 기능을 켜 버리지 않으려는 것).
암호화 키 4종은 DB의 **암호문 행수를 먼저 세어**(read-only `select count(*)`), 0이 아니거나 셀 수 없으면 구 키를 `*_DECRYPTION_FALLBACK_KEYS`로 옮겨 남깁니다(위 "먼저 알아 둘 것" 3). `.env` 파일에 한국어 등 **비ASCII 문자가 있으면 그 파일은 건드리지 않고** 미검증으로 보고합니다(인코딩을 깨뜨리지 않으려는 것 — 수동 편집 대상).
**DB·Redis 비밀번호는 바꾸지 않습니다**(이름이 있으면 알려만 줍니다).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §4 로컬 시크릿 회전 — 이미 있는 이름만 교체(값은 출력·저장하지 않는다)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
function New-RandomBytes([int]$Count) { $B = New-Object byte[] $Count; $R = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $R.GetBytes($B); $R.Dispose(); return ,$B }
function New-B64([int]$Count) { return [Convert]::ToBase64String((New-RandomBytes $Count)) }
function New-UrlSafe([int]$Count) { return ([Convert]::ToBase64String((New-RandomBytes $Count))).TrimEnd("=").Replace("+","-").Replace("/","_") }
function New-Hex([int]$Count) { $H = New-RandomBytes $Count; return (($H | ForEach-Object { $_.ToString("x2") }) -join "") }
function Get-CipherCount([string]$Sql) { $R = docker exec whymath-pg psql -U whymath -d whymath -tA -c $Sql 2>$null; if ($LASTEXITCODE -ne 0) { return -1 }; $T = ("$R").Trim(); if ($T -match "^\d+$") { return [int]$T } else { return -1 } }
function Get-EnvFileValue([string]$Path, [string]$Name) { foreach ($L in (Get-Content $Path -ErrorAction SilentlyContinue)) { if ($L -match ("^\s*" + [regex]::Escape($Name) + "\s*=\s*(.*)$")) { return $Matches[1].Trim() } }; return "" }
$Counts = @{}
$Counts["WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY"] = Get-CipherCount "select count(*) from dialogue_turn where content_encrypted is not null or image_uri_encrypted is not null or image_analysis_encrypted is not null"
$Counts["WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY"] = Get-CipherCount "select count(*) from device_credential where secret_encrypted is not null"
$Counts["WHYMATH_STUDENT_WORK_ENCRYPTION_KEY"] = Get-CipherCount "select (select count(*) from answer_submission where raw_response_encrypted is not null or latex_encrypted is not null or canonical_ast_encrypted is not null) + (select count(*) from student_solution_step where expression_encrypted is not null or canonical_ast_encrypted is not null) + (select count(*) from problem_attempt where student_answer_encrypted is not null or handwriting_uri_encrypted is not null or ocr_result_encrypted is not null)"
$Counts["WHYMATH_EVIDENCE_PAYLOAD_ENCRYPTION_KEY"] = Get-CipherCount "select count(*) from evidence_event where payload_encrypted is not null"
"--- 암호문 행수(-1 = 셀 수 없음 → 구 키를 폴백으로 남김) ---"
$Counts.GetEnumerator() | Sort-Object Name | Format-Table -AutoSize
$Plan = @(
  @{ Name = "WHYMATH_JWT_SECRET_KEY"; Kind = "urlsafe48"; Fallback = "" },
  @{ Name = "WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY"; Kind = "b64_32"; Fallback = "WHYMATH_DIALOGUE_CONTENT_DECRYPTION_FALLBACK_KEYS" },
  @{ Name = "WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY"; Kind = "b64_32"; Fallback = "WHYMATH_DEVICE_SECRET_DECRYPTION_FALLBACK_KEYS" },
  @{ Name = "WHYMATH_STUDENT_WORK_ENCRYPTION_KEY"; Kind = "b64_32"; Fallback = "WHYMATH_STUDENT_WORK_DECRYPTION_FALLBACK_KEYS" },
  @{ Name = "WHYMATH_EVIDENCE_PAYLOAD_ENCRYPTION_KEY"; Kind = "b64_32"; Fallback = "WHYMATH_EVIDENCE_PAYLOAD_DECRYPTION_FALLBACK_KEYS" },
  @{ Name = "WHYMATH_COACH_DEVICE_HMAC_SECRET"; Kind = "hex32"; Fallback = "" },
  @{ Name = "WHYMATH_PII_AUDIT_IP_SALT"; Kind = "hex32"; Fallback = "" }
)
$EnvFiles = @(Get-ChildItem "$Repo\.env","$Repo\src\backend\.env","$Repo\deploy\*.env" -Force -ErrorAction SilentlyContinue)
$ManualPresent = @()
foreach ($N in @("WHYMATH_DB_PASSWORD","WHYMATH_REDIS_PASSWORD")) { $InFile = @($EnvFiles | Where-Object { (Get-EnvFileValue $_.FullName $N) -ne "" }).Count; if ([Environment]::GetEnvironmentVariable($N, "User") -or [Environment]::GetEnvironmentVariable($N, "Machine") -or ($InFile -gt 0)) { $ManualPresent += $N } }
$MachineScope = @($Plan | Where-Object { [Environment]::GetEnvironmentVariable($_.Name, "Machine") } | ForEach-Object { $_.Name })
$EvFile = "$Out\rotation_local_$(Get-Date -Format HHmmss).json"
$Ready = $OutOk -and $RevokeOk -and $TrustOk
if ($Ready) {
  function Set-EnvFileValue([string]$Path, [string]$Name, [string]$Value, [bool]$AddIfMissing) {
    $Bytes = [System.IO.File]::ReadAllBytes($Path)
    if (@($Bytes | Where-Object { $_ -gt 127 }).Count -gt 0) { return $false }
    $Lines = @(Get-Content $Path)
    $Hit = $false
    for ($I = 0; $I -lt $Lines.Count; $I++) { if ($Lines[$I] -match ("^\s*" + [regex]::Escape($Name) + "\s*=")) { $Lines[$I] = $Name + "=" + $Value; $Hit = $true } }
    if ((-not $Hit) -and $AddIfMissing) { $Lines += ($Name + "=" + $Value); $Hit = $true }
    if ($Hit) { $Lines | Set-Content -Path $Path -Encoding ASCII }
    return $Hit
  }
  $Done = @()
  $Absent = @()
  foreach ($P in $Plan) {
    $Old = [Environment]::GetEnvironmentVariable($P.Name, "User")
    $InFiles = @($EnvFiles | Where-Object { (Get-EnvFileValue $_.FullName $P.Name) -ne "" })
    if (($Old) -or ($InFiles.Count -gt 0)) {
      $New = switch ($P.Kind) { "urlsafe48" { New-UrlSafe 48 } "b64_32" { New-B64 32 } "hex32" { New-Hex 32 } }
      $Cnt = -2
      if ($Counts.ContainsKey($P.Name)) { $Cnt = $Counts[$P.Name] }
      $KeepOld = ($P.Fallback -ne "") -and ($Cnt -ne 0)
      $OldValue = $Old
      if ((-not $OldValue) -and ($InFiles.Count -gt 0)) { $OldValue = Get-EnvFileValue $InFiles[0].FullName $P.Name }
      $FilesOk = $true
      if ($Old) {
        [Environment]::SetEnvironmentVariable($P.Name, $New, "User")
        if ($KeepOld) { $FbOld = [Environment]::GetEnvironmentVariable($P.Fallback, "User"); $FbNew = ((@($FbOld, $OldValue) | Where-Object { $_ }) -join ","); [Environment]::SetEnvironmentVariable($P.Fallback, $FbNew, "User") }
      }
      foreach ($F in $InFiles) {
        $Wrote = Set-EnvFileValue $F.FullName $P.Name $New $false
        if ($KeepOld) { $FbFile = Get-EnvFileValue $F.FullName $P.Fallback; $Ignore = Set-EnvFileValue $F.FullName $P.Fallback ((@($FbFile, $OldValue) | Where-Object { $_ }) -join ",") $true }
        if ((-not $Wrote) -or ((Get-EnvFileValue $F.FullName $P.Name) -ne $New)) { $FilesOk = $false }
      }
      $UserBack = [Environment]::GetEnvironmentVariable($P.Name, "User")
      $UserOk = (-not $Old) -or ($UserBack -eq $New)
      $Done += [pscustomobject]@{ Name = $P.Name; UserEnv = [bool]$Old; Files = $InFiles.Count; OldLen = ("" + $OldValue).Length; NewLen = $New.Length; KeepOldAsFallback = $KeepOld; CipherRows = $Cnt; Verified = ($UserOk -and $FilesOk) }
    } else {
      $Absent += $P.Name
    }
  }
  $Done | ConvertTo-Json | Set-Content -Path $EvFile -Encoding UTF8
  $Back = @(Get-Content $EvFile -Raw | ConvertFrom-Json)
  $Back | Format-Table Name, UserEnv, Files, OldLen, NewLen, KeepOldAsFallback, CipherRows, Verified -AutoSize
  "LOCAL_ROTATED=$($Back.Count)  LOCAL_UNVERIFIED=$(@($Back | Where-Object { -not $_.Verified }).Count)  LOCAL_ABSENT=$($Absent.Count)  FALLBACK_KEPT=$(@($Back | Where-Object { $_.KeepOldAsFallback } | ForEach-Object { $_.Name }) -join ',')"
  "ABSENT_NAMES=$($Absent -join ',')"
  "MANUAL_PASSWORDS_PRESENT=$($ManualPresent -join ',')  MACHINE_SCOPE_PRESENT=$($MachineScope -join ',')  RESTART_REQUIRED=True"
} else {
  "LOCAL_ROTATION_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  (§2b 기록에 n이 있거나 §3이 통과하지 않았습니다)"
}
```
- **성공**: `LOCAL_UNVERIFIED=0`. `LOCAL_ABSENT`는 "그 이름이 이 머신에 없다"는 뜻이라 정상입니다(어떤 이름이 없는지 `ABSENT_NAMES`로 세션에 전달).
- **판독**:
  - `FALLBACK_KEPT`에 이름이 있으면 그 키는 **구 키를 폴백으로 남겼다**는 뜻이므로 기존 암호문 행의 기밀성은 구 키 수준입니다 — `CipherRows`가 **0보다 크면 잔여 위험으로 기록 대상**(재암호화는 후속), `-1`이면 DB를 못 읽어 보수적으로 남긴 것이니 Docker·`whymath-pg`를 켠 뒤 다시 실행하면 됩니다(이미 바뀐 키로 두 번째 회전이 일어나 폴백 체인이 길어질 뿐 안전합니다 — 단 폴백 변수에 **구 키가 누적**되므로 세션에 알려 주십시오).
  - `MANUAL_PASSWORDS_PRESENT`에 이름이 있으면 **서버 쪽 비밀번호와 함께** 바꿔야 하는 항목입니다. 이 런북이 대신하지 않으므로 세션에 전달하십시오.
  - `MACHINE_SCOPE_PRESENT`는 **시스템 환경변수**(관리자 권한 필요)에 있는 이름입니다 — 이 블록이 바꾸지 못했으므로 수동 처리 대상입니다.
- **증거 파일**: 실행할 때마다 `rotation_local_<시각>.json`이 새로 생깁니다(재실행해도 이전 기록이 덮이지 않고 §8이 전부 집계합니다).
- **서비스 재기동**: 위 변경은 **다음에 뜨는 프로세스부터** 적용됩니다. 이 머신에서 백엔드가 돌고 있다면 재기동 전까지 옛 키가 메모리에 남습니다.
- **실패 시 대처**: `LOCAL_ROTATION_REFUSED`면 같은 줄의 `False`인 항목을 먼저 해결하십시오(§2b·§3 재실행). `LOCAL_UNVERIFIED`가 1 이상이면 해당 행의 `Files`가 1 이상인지 보십시오 — 파일에 비ASCII 문자가 있어 건드리지 않은 경우이며, 그 파일을 수동 편집해야 합니다(새 값은 파일에 기록돼 있지 않으므로 **환경변수 쪽만 바뀌었는지** 세션과 확인).

---

## 5. 재발급 — GitHub 로그인·PAT·외부 서비스 키 (창 A)

**선행 조건(각 블록이 스스로 재검사)**: §2b에 `n` 0건 + §3 `TRUST_OK=True`. 아니면 거부합니다. §5의 세 블록은 **순서대로**(5a → 5b → 5c) 하되, 블록 하나씩 붙여넣으십시오.

### 5a. gh 재로그인 (대화형 — 이 블록만 붙여넣고 끝까지 진행)

§2의 R2에서 이 머신의 OAuth 토큰이 폐기돼 `gh`가 로그아웃 상태입니다. 브라우저 인증(device flow)으로 **새 토큰**을 받습니다. 화면에 나오는 일회용 코드를 브라우저에 입력하고, 질문이 나오면 답하십시오. **이 블록 뒤에 다른 줄을 붙여넣지 마십시오**(대화형이라 입력으로 소비됩니다).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §5a gh 재로그인 — 대화형(이 블록만 붙여넣는다)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
$GhFound = [bool](Get-Command gh -ErrorAction SilentlyContinue)
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and $GhFound
if ($Ready) { gh auth login --hostname github.com --web --git-protocol https; "GH_LOGIN_EXIT=$LASTEXITCODE" } else { "GH_LOGIN_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  GhFound=$GhFound" }
```
확인은 별도 블록으로 합니다(로그인 후 붙여넣으십시오).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §5a-2 gh 로그인 확인 — 읽기 전용
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
gh auth status 2>$null | Out-Null
$StatusExit = $LASTEXITCODE
$Account = (gh api user --jq .login 2>$null)
$RepoVisible = (gh api repos/kiki-s-broom/WhyMath --jq .full_name 2>$null)
"GH_STATUS_EXIT=$StatusExit  ACCOUNT=$Account  REPO_VISIBLE=$RepoVisible"
```
- **성공**: `GH_STATUS_EXIT=0` + `ACCOUNT`가 본인 계정 + `REPO_VISIBLE=kiki-s-broom/WhyMath`.
- **실패 시 대처**: `GH_LOGIN_REFUSED`면 같은 줄의 `False`를 해결(§2b·§3 재실행). `ACCOUNT`가 **본인이 아닌 계정**이면 즉시 멈추고 세션에 전달하십시오.

### 5b. GitHub PAT 재발급 → 저장소 시크릿 `PR_AUTO_RESYNC_TOKEN`

**먼저 브라우저에서 새 PAT를 만듭니다**(값은 생성 직후 한 번만 보입니다):
1. GitHub → 계정 Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. 이름: 알아볼 수 있게(예: `whymath-pr-auto-resync`). **만료: 90일 이하**로 하고 만료일을 달력에 적어 두십시오 — 만료되면 `pr-auto-resync`가 쓰기 전에 멈춥니다(fail-closed).
3. Resource owner: `kiki-s-broom` · Repository access: **Only select repositories → `WhyMath` 하나만**.
4. Permissions: **Contents = Read and write** · **Pull requests = Read and write** (Metadata는 자동). 그 외는 부여하지 않습니다(`.github/branch-protection-setup.md`가 정한 최소 권한).
5. 조직이 fine-grained PAT 승인을 요구하면 조직 소유자 승인이 필요합니다(승인 전에는 아래 `API_REPO_HTTP`가 200이 아니라 403·404로 나옵니다).

그 다음 아래 블록을 붙여넣고, 입력 창이 뜨면 **방금 만든 PAT를 붙여넣고 Enter**(화면에 아무것도 보이지 않는 것이 정상입니다).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §5b PAT 검증 후 저장소 시크릿 등록 — 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
function Get-HttpCode([string]$Url, [hashtable]$Headers, [bool]$Enabled) {
  if (-not $Enabled) { return -2 }
  try { $R = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $Headers -TimeoutSec 20 -Method Get; return [int]$R.StatusCode } catch { $Resp = $_.Exception.Response; if ($Resp) { return [int]$Resp.StatusCode } else { return -1 } }
}
$Sec = Read-Host "새 PAT를 붙여넣고 Enter(화면에 보이지 않습니다)" -AsSecureString
$Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Sec)
$Plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
$Len = $Plain.Length
$PrefixOk = ($Plain.PadRight(11).Substring(0, 11) -eq "github_pat_")
$Shape = ($Len -ge 40) -and $PrefixOk -and ($Plain -notmatch "[^\x21-\x7E]")
$Code = Get-HttpCode "https://api.github.com/repos/kiki-s-broom/WhyMath" @{ Authorization = "Bearer $Plain"; Accept = "application/vnd.github+json" } $Shape
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and $Shape -and ($Code -eq 200)
if ($Ready) {
  gh secret set PR_AUTO_RESYNC_TOKEN --repo kiki-s-broom/WhyMath --body $Plain
  $SetExit = $LASTEXITCODE
  $Listed = @(gh secret list --repo kiki-s-broom/WhyMath 2>$null | Where-Object { $_ -match "^PR_AUTO_RESYNC_TOKEN\b" }).Count
  [pscustomobject]@{ Name = "PR_AUTO_RESYNC_TOKEN"; Length = $Len; ApiRepoHttp = $Code; SetExit = $SetExit; Listed = $Listed; At = (Get-Date -Format "s") } | ConvertTo-Json | Set-Content -Path "$Out\rotation_pat.json" -Encoding UTF8
  "PAT_SET_EXIT=$SetExit  PAT_LISTED=$Listed  PAT_LEN=$Len  API_REPO_HTTP=$Code  SAVED=$(Test-Path "$Out\rotation_pat.json")"
} else {
  "PAT_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  Len=$Len  PrefixOk=$PrefixOk  Shape=$Shape  ApiRepoHttp=$Code  (-2=형식이 달라 호출하지 않음 / -1=무응답)"
}
Remove-Variable Plain, Sec -ErrorAction SilentlyContinue
```
- **성공**: `PAT_SET_EXIT=0` · `PAT_LISTED=1` · `API_REPO_HTTP=200` · `SAVED=True`.
- **증명되는 것 / 안 되는 것**: 새 토큰이 **저장소를 읽을 수 있고**(200) 시크릿에 **등록됐다**(목록에 보임)는 것까지입니다. `Contents`·`Pull requests` **쓰기 권한**은 호출로 증명되지 않습니다 — `pr-auto-resync`가 auto-merge 대기 PR에 실제로 돌 때 최종 판정됩니다(Actions 탭의 `Run workflow` → `dry_run=1`은 읽기 전용이라 이 판정에 쓸 수 없습니다).
- **실패 시 대처**: `Len=0`이면 붙여넣기가 안 된 것 — 블록을 다시 붙여넣고 입력 창에서 우클릭으로 붙여넣으십시오. `PrefixOk=False`면 **fine-grained PAT가 아닌 다른 것**(classic은 `ghp_`로 시작)을 붙인 것입니다. `API_REPO_HTTP=403/404`면 저장소 선택·조직 승인 문제입니다 — 값을 채팅에 붙이지 말고 그 줄만 전달하십시오.

### 5c. 외부 서비스 키 — 옛 키 거부 확인 → 새 키 교체 (창 A)

이 머신의 **사용자 환경변수에 있는** 외부 서비스 키만 대상입니다(§1이 이름을 보여 줬습니다). 키마다 이 순서로 처리합니다:
1. **옛 키로 호출해 거부(401)되는지** 확인 — §2에서 콘솔 폐기가 실제로 먹혔는지의 직접 증거입니다(`ACTIVE`면 폐기가 안 된 것).
2. 새 키를 입력받아(화면에 안 보임) **새 키로 호출해 200**인지 확인한 뒤에만 환경변수를 바꿉니다.
3. **Anthropic은 재발급하지 않습니다**(`ARCH-66`). 옛 키가 거부되면 이 머신의 환경변수에서 **제거**합니다.

**새 키를 콘솔에서 먼저 발급해 두십시오**(서비스별, §2의 R7~R10 화면). 건너뛰려면 입력 창에서 아무것도 넣지 않고 Enter(그 키는 교체하지 않고 `skipped`로 기록됩니다).
호출 엔드포인트는 서비스별 공개 문서 기준이며 **Anthropic만 실측**했습니다. 나머지에서 `UNKNOWN(코드)`가 나오면 엔드포인트가 다르거나 막힌 것이므로 **그 키의 폐기 여부는 콘솔에서 사람이 확인**한 것으로 §2b를 근거 삼습니다(통과로 읽지 않습니다).

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §5c 외부 서비스 키 교체 — 값은 출력·저장하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
function Get-HttpCode([string]$Url, [hashtable]$Headers, [bool]$Enabled) {
  if (-not $Enabled) { return -2 }
  try { $R = Invoke-WebRequest -UseBasicParsing -Uri $Url -Headers $Headers -TimeoutSec 20 -Method Get; return [int]$R.StatusCode } catch { $Resp = $_.Exception.Response; if ($Resp) { return [int]$Resp.StatusCode } else { return -1 } }
}
function Get-KeyState([string]$Url, [string]$Style, [string]$Key, [bool]$Enabled) {
  if (-not $Enabled) { return "SKIPPED" }
  if ($Url -eq "") { return "UNPROBED" }
  $H = @{}
  if ($Style -eq "x-api-key") { $H["x-api-key"] = $Key; $H["anthropic-version"] = "2023-06-01" } else { $H["Authorization"] = "Bearer $Key" }
  $C = Get-HttpCode $Url $H $true
  if ($C -eq 200) { return "ACTIVE" }
  if ($C -eq 401) { return "REJECTED" }
  return "UNKNOWN($C)"
}
$Targets = @(
  @{ Svc = "OpenRouter"; Env = "WHYMATH_OPENROUTER_API_KEY"; Url = "https://openrouter.ai/api/v1/key"; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "OpenRouter"; Env = "OPENROUTER_API_KEY"; Url = "https://openrouter.ai/api/v1/key"; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "DeepSeek"; Env = "WHYMATH_DEEPSEEK_API_KEY"; Url = "https://api.deepseek.com/models"; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "DeepSeek"; Env = "DEEPSEEK_API_KEY"; Url = "https://api.deepseek.com/models"; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "OpenAI"; Env = "WHYMATH_OPENAI_API_KEY"; Url = "https://api.openai.com/v1/models"; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "Anthropic"; Env = "WHYMATH_ANTHROPIC_API_KEY"; Url = "https://api.anthropic.com/v1/models"; Style = "x-api-key"; Min = 20; Retire = $true },
  @{ Svc = "Anthropic"; Env = "ANTHROPIC_API_KEY"; Url = "https://api.anthropic.com/v1/models"; Style = "x-api-key"; Min = 20; Retire = $true },
  @{ Svc = "Langfuse"; Env = "WHYMATH_LANGFUSE_SECRET_KEY"; Url = ""; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "Langfuse"; Env = "WHYMATH_LANGFUSE_PUBLIC_KEY"; Url = ""; Style = "bearer"; Min = 20; Retire = $false },
  @{ Svc = "Kakao"; Env = "WHYMATH_KAKAO_CLIENT_SECRET"; Url = ""; Style = "bearer"; Min = 16; Retire = $false },
  @{ Svc = "Naver"; Env = "WHYMATH_NAVER_CLIENT_SECRET"; Url = ""; Style = "bearer"; Min = 16; Retire = $false }
)
$Present = @($Targets | Where-Object { [Environment]::GetEnvironmentVariable($_.Env, "User") })
"--- 이 머신 사용자 환경변수에 있는 외부 서비스 키(이름만) ---"
$Present | ForEach-Object { $_.Env }
$EvFile = "$Out\rotation_external_$(Get-Date -Format HHmmss).json"
$Ready = $OutOk -and $RevokeOk -and $TrustOk
if ($Ready) {
  $Rows = @()
  foreach ($T in $Present) {
    $Old = [Environment]::GetEnvironmentVariable($T.Env, "User")
    $OldState = Get-KeyState $T.Url $T.Style $Old $true
    $NewState = "-"
    $Action = "none"
    $NewLen = 0
    if ($T.Retire) {
      if ($OldState -eq "REJECTED") { [Environment]::SetEnvironmentVariable($T.Env, $null, "User"); $Action = "removed" } else { $Action = "kept(OldState=$OldState)" }
    } else {
      $Sec = Read-Host "[$($T.Svc)] $($T.Env) 새 키(화면에 안 보임 / 건너뛰려면 그냥 Enter)" -AsSecureString
      $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Sec)
      $Plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
      $NewLen = $Plain.Length
      $Shape = ($NewLen -ge $T.Min) -and ($Plain -notmatch "[^\x21-\x7E]") -and ($Plain -ne $Old)
      $NewState = Get-KeyState $T.Url $T.Style $Plain $Shape
      $Accept = $Shape -and (($NewState -eq "ACTIVE") -or ($NewState -eq "UNPROBED"))
      if ($Accept) { [Environment]::SetEnvironmentVariable($T.Env, $Plain, "User"); $Action = "replaced" } else { $Action = "skipped(Shape=$Shape NewState=$NewState Len=$NewLen)" }
    }
    $Rows += [pscustomobject]@{ Service = $T.Svc; Env = $T.Env; OldState = $OldState; NewState = $NewState; NewLen = $NewLen; Action = $Action; EnvNowLen = (("" + [Environment]::GetEnvironmentVariable($T.Env, "User")).Length) }
  }
  $Rows | ConvertTo-Json | Set-Content -Path $EvFile -Encoding UTF8
  $Back = @(Get-Content $EvFile -Raw | ConvertFrom-Json)
  $Back | Format-Table -AutoSize
  "EXTERNAL_TARGETS=$($Back.Count)  EXTERNAL_OLD_ACTIVE=$(@($Back | Where-Object { $_.OldState -eq 'ACTIVE' }).Count)  EXTERNAL_OLD_UNKNOWN=$(@($Back | Where-Object { $_.OldState -like 'UNKNOWN*' }).Count)  EXTERNAL_OLD_UNPROBED=$(@($Back | Where-Object { $_.OldState -eq 'UNPROBED' }).Count)"
  "REPLACED=$(@($Back | Where-Object { $_.Action -eq 'replaced' }).Count)  REMOVED=$(@($Back | Where-Object { $_.Action -eq 'removed' }).Count)  SKIPPED=$(@($Back | Where-Object { $_.Action -like 'skipped*' }).Count)  NEW_UNPROBED=$(@($Back | Where-Object { $_.Action -eq 'replaced' -and $_.NewState -eq 'UNPROBED' }).Count)"
} else {
  "EXTERNAL_ROTATION_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk"
}
Remove-Variable Plain, Sec -ErrorAction SilentlyContinue
```
- **성공**: `EXTERNAL_OLD_ACTIVE=0` 이고 `SKIPPED=0`(건너뛴 키가 있으면 그 이유를 세션에 전달).
- **판독**:
  - **재실행 주의**: 같은 키를 두 번째로 돌리면 이미 교체한 값(새 키)이 `OldState=ACTIVE`로 나옵니다 — 그것은 새 키이므로 정상입니다. 옛 키의 진짜 상태는 **그 키의 첫 실행 행**이며 §8이 첫 실행 기준으로 집계합니다.
  - `EXTERNAL_OLD_ACTIVE`가 1 이상 → **옛 키가 아직 살아 있습니다.** 해당 서비스 콘솔에서 그 키를 삭제하고(R6~R9) 블록을 다시 실행하십시오. 이 경우 `OldState=ACTIVE`인 행의 키는 이미 새 키로 바뀌었어도 옛 키는 계속 유효하니 **콘솔 삭제가 우선**입니다.
  - `EXTERNAL_OLD_UNKNOWN`·`EXTERNAL_OLD_UNPROBED`는 **호출로 폐기를 확인하지 못한 키**입니다(통과가 아닙니다). 그 서비스의 R 항목을 콘솔에서 다시 확인했는지 세션과 점검합니다.
  - `NEW_UNPROBED`는 새 키가 호출 검증 없이 등록됐다는 뜻입니다(Langfuse·Kakao·Naver). 실제 사용 시 첫 호출에서 확인됩니다.
  - 같은 서비스가 `WHYMATH_…`와 벤더 표준 이름(`OPENROUTER_API_KEY` 등)으로 **두 번** 나오면 입력 창도 두 번 뜹니다. 같은 새 키를 두 번 넣으면 됩니다(하나만 설정돼 있으면 한 번만 뜹니다).
  - 새 환경변수는 **다음에 뜨는 프로세스부터** 적용됩니다(위 "먼저 알아 둘 것" 6).
- **실패 시 대처**: `EXTERNAL_ROTATION_REFUSED`면 같은 줄의 `False`부터 해결. 입력 창에서 붙여넣기가 안 돼 `skipped(... Len=0)`이 나왔다면 블록을 다시 붙여넣고 그 키만 다시 입력(이미 바꾼 키는 `Plain -ne Old` 검사 때문에 같은 값을 다시 넣으면 `skipped`로 정직하게 거부됩니다).

---

## 6. 배포 SSH 키 교체 (창 A · `DEPLOY_SSH_KEY`가 등록된 경우만)

§1의 `HAS_DEPLOY_SSH_KEY`가 `0`이면 **이 절은 건너뜁니다**(교체 대상이 없다는 사실을 §8 요약에 `n/a`로 남깁니다). 1이면 GitHub Actions의 배포 잡(`deploy.yml`)이 쓰는 개인키가 이 머신에서 만들어졌거나 지나갔을 수 있으므로 교체합니다.
`DEPLOY_SSH_HOST`·`DEPLOY_SSH_USER`·`DEPLOY_PATH`·`DEPLOY_SSH_KNOWN_HOSTS`는 **비밀이 아니므로 바꾸지 않습니다**(호스트 신원 정보).

순서가 중요합니다: **새 키 생성 → 서버에 새 공개키 등록(+옛 공개키 삭제) → 새 키로 접속 성공·옛 키 접속 실패를 확인 → 그때서야 GitHub 시크릿 교체**. 서버에 새 공개키를 넣기 전에 시크릿부터 바꾸면 배포가 인증 실패로 멈춥니다.

### 6a. 새 키쌍 생성

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §6a 새 배포 키쌍 생성 — 개인키는 결과 폴더에 잠시만 둔다
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
$KeyPath = "$Out\deploy_ed25519_new"
$Tool = [bool](Get-Command ssh-keygen -ErrorAction SilentlyContinue)
$GhSecrets = @(gh secret list --repo kiki-s-broom/WhyMath 2>$null)
$HasDeployKey = @($GhSecrets | Where-Object { $_ -match "^DEPLOY_SSH_KEY\b" }).Count
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and $Tool -and ($HasDeployKey -ge 1) -and (-not (Test-Path $KeyPath))
if ($Ready) {
  ssh-keygen -t ed25519 -f $KeyPath -N '""' -C "whymath-deploy-rotated" -q
  "KEYGEN_EXIT=$LASTEXITCODE  PRIVATE_EXISTS=$(Test-Path $KeyPath)  PUBLIC_EXISTS=$(Test-Path "$KeyPath.pub")"
  "--- 새 공개키 1줄(공개키이므로 화면 출력 가능 - 서버 authorized_keys에 넣을 것) ---"
  Get-Content "$KeyPath.pub"
} else {
  "DEPLOY_KEYGEN_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  ToolFound=$Tool  HasDeployKey=$HasDeployKey  KeyAlreadyThere=$(Test-Path $KeyPath)  (HasDeployKey=0이면 교체 대상 없음)"
}
```
- **성공**: `KEYGEN_EXIT=0` · `PRIVATE_EXISTS=True` · `PUBLIC_EXISTS=True` + 공개키 1줄(`ssh-ed25519 …`).
- **다음(수동 · 서버에서)**: 배포 서버에 **평소 접속하는 방법**으로 들어가 `~/.ssh/authorized_keys`에서 **옛 배포 공개키 줄을 삭제**하고 위 공개키 1줄을 **추가**하십시오. 서버가 이 PC 자신(Windows OpenSSH)이면 해당 사용자의 `authorized_keys`(관리자 계정이면 `C:\ProgramData\ssh\administrators_authorized_keys`)를 수정합니다. 이 두 동작(추가·삭제)이 끝난 뒤에만 6b로 갑니다.
- **실패 시 대처**: `KEYGEN_EXIT`이 0이 아니면 세션에 전달. `KeyAlreadyThere=True`면 이전 시도의 키가 남아 있으니 **지우지 말고** 세션에 알려 주십시오(서버에 이미 등록했을 수 있습니다).

### 6b. 접속 검증 → GitHub 시크릿 교체 → 로컬 개인키 삭제

입력 창이 두 번 뜹니다: ① 배포 서버 접속 대상(`사용자@호스트` 형식, 비밀 아님) ② 옛 배포 개인키 파일 이름(`~\.ssh` 아래 · 없거나 모르면 `none`).
**변별력**: 새 키 접속 성공(종료 코드 0)이 **같은 실행에서** 확인돼야 옛 키 실패를 "거부됨"으로 읽습니다(네트워크 장애로 둘 다 실패한 것을 거부로 오인하지 않으려는 것). 옛 키 파일을 `none`으로 답하면 옛 키 거부는 **미검증**으로 남습니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §6b 배포 키 접속 검증 + GitHub 시크릿 교체 — 서버 등록 후에만
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
$KeyPath = "$Out\deploy_ed25519_new"
$Target = (Read-Host "배포 서버 접속 대상을 사용자@호스트 형식으로 입력(비밀 아님)").Trim()
$OldName = (Read-Host "옛 배포 개인키 파일 이름(~\.ssh 아래 / 없거나 모르면 none)").Trim()
$OldPath = Join-Path "$env:USERPROFILE\.ssh" $OldName
$TargetOk = ($Target -match "^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]+$")
function Test-SshKey([string]$Key, [string]$Dest, [bool]$Enabled) {
  if (-not $Enabled) { return -2 }
  ssh -i $Key -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 $Dest exit 2>$null
  return $LASTEXITCODE
}
$NewExit = Test-SshKey $KeyPath $Target ($TargetOk -and (Test-Path $KeyPath))
$OldTestable = ($OldName -ne "none") -and (Test-Path $OldPath) -and ($NewExit -eq 0)
$OldExit = Test-SshKey $OldPath $Target $OldTestable
$OldRejected = $OldTestable -and ($OldExit -ne 0)
$OldOk = $OldRejected -or ($OldName -eq "none")
$EvFile = "$Out\rotation_ssh.json"
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and ($NewExit -eq 0) -and $OldOk
if ($Ready) {
  cmd /c "gh secret set DEPLOY_SSH_KEY --repo kiki-s-broom/WhyMath < `"$KeyPath`""
  $SetExit = $LASTEXITCODE
  if ($SetExit -eq 0) { Remove-Item -Path $KeyPath, "$KeyPath.pub" -Force }
  [pscustomobject]@{ NewKeyLoginExit = $NewExit; OldKeyLoginExit = $OldExit; OldRejected = $OldRejected; OldKeyChecked = ($OldName -ne "none"); SetExit = $SetExit; At = (Get-Date -Format "s") } | ConvertTo-Json | Set-Content -Path $EvFile -Encoding UTF8
  "DEPLOY_KEY_SET_EXIT=$SetExit  NEW_KEY_LOGIN_EXIT=$NewExit  OLD_KEY_LOGIN_EXIT=$OldExit  OLD_REJECTED=$OldRejected  OLD_KEY_CHECKED=$($OldName -ne 'none')  LOCAL_KEY_REMOVED=$(-not (Test-Path $KeyPath))  SAVED=$(Test-Path $EvFile)"
} else {
  "DEPLOY_KEY_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  TargetOk=$TargetOk  NewKeyLoginExit=$NewExit  OldTestable=$OldTestable  OldKeyLoginExit=$OldExit  (NewKeyLoginExit: -2=입력 형식/키 파일 문제로 시도 안 함, 255=접속 거부, 0=성공)"
}
```
- **성공**: `DEPLOY_KEY_SET_EXIT=0` · `NEW_KEY_LOGIN_EXIT=0` · `OLD_REJECTED=True`(또는 `OLD_KEY_CHECKED=False` — 그 경우 옛 키 거부는 **미검증**이니 세션에 알려 주십시오) · `LOCAL_KEY_REMOVED=True`.
- **판독**: `OLD_REJECTED=False`인데 `OLD_KEY_LOGIN_EXIT=0`이면 **옛 공개키가 서버에 아직 남아 있습니다** — 6a의 수동 단계에서 삭제가 안 된 것이니 서버에서 지우고 이 블록을 다시 실행하십시오(블록이 거부했으므로 GitHub 시크릿은 아직 바뀌지 않았습니다).
- **실패 시 대처**: `NEW_KEY_LOGIN_EXIT=255`면 서버에 새 공개키가 안 들어갔거나(6a 수동 단계) 호스트 키가 `known_hosts`에 없는 것입니다(한 번 `ssh 대상`으로 수동 접속해 지문을 승인한 뒤 재실행). **절대 값을 채팅에 붙이지 마십시오.**
- **한계**: GitHub에 저장된 옛 `DEPLOY_SSH_KEY` 값은 읽을 수 없어 "옛 시크릿 값이 죽었는가"를 직접 호출로 확인하지 못합니다. 증거는 **서버에서 옛 공개키가 지워졌고(위 `OLD_REJECTED`) 시크릿이 새 키로 덮였다(§8의 갱신 시각)**는 두 가지입니다.

---

## 7. 백업 암호화 키쌍(age) 교체 (창 A)

**왜**: 백업 개인키(`%USERPROFILE%\whymath-backup-identity.key`)는 **이 머신 디스크에 있었으므로 노출로 간주**합니다. 그 키로 잠긴 기존 `.dump.age`(로컬·Drive 오프사이트 동기 폴더)는 개인키와 암호문을 **둘 다** 가진 쪽이 열 수 있습니다.
**이 절이 하는 것(앞으로의 백업)**: 새 키쌍을 만들어 수신자 파일을 **새 공개키로 교체**(추가가 아니라 교체)하고, 백업 1회 + 복원 검증까지 통과한 뒤, **개인키를 이 머신 밖으로** 옮깁니다(백업 머신에는 공개키만 두는 §1b의 원래 설계).
**이 절이 하지 않는 것(과거 백업)**: 기존 `.dump.age`를 새 키로 다시 잠그지 않습니다 — 복호하는 순간 **미성년 PII가 포함될 수 있는 평문이 디스크에 생기기 때문**입니다. 기존 백업의 처분(보관·삭제·재암호화)은 acceptance ③(학생 PII 노출 판정)의 결과로 Kiki가 결정합니다. 구 개인키는 구 백업 복구용으로 **머신 밖에만** 보관합니다.

### 7a. 새 키쌍 생성 + 수신자 파일 교체

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §7a 새 age 키쌍 생성 + 수신자 파일 교체
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
$BackupDir = "C:\Users\kiki\Desktop\__AI\WhyMath-backups"
$Recipients = "$BackupDir\recipients.txt"
$StampName = Split-Path $Out -Leaf
$NewId = "$env:USERPROFILE\whymath-backup-identity-$StampName.key"
$AgeTool = [bool](Get-Command age-keygen -ErrorAction SilentlyContinue)
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and $AgeTool -and (Test-Path $BackupDir) -and (-not (Test-Path $NewId))
if ($Ready) {
  $Log = (& age-keygen -o $NewId 2>&1 | Out-String)
  $Pub = [regex]::Match($Log, "age1[0-9a-z]{50,}").Value
  $PubOk = ($Pub -match "^age1[0-9a-z]{50,}$")
  if ($PubOk) { Copy-Item $Recipients "$Out\recipients.txt.before" -ErrorAction SilentlyContinue; Set-Content -Path $Recipients -Value $Pub -Encoding ascii }
  $Now = @(Get-Content $Recipients -ErrorAction SilentlyContinue)
  "AGE_PUBKEY_FOUND=$PubOk  NEW_IDENTITY_EXISTS=$(Test-Path $NewId)  RECIPIENTS_LINES=$($Now.Count)  RECIPIENTS_IS_NEW=$($Now[0] -eq $Pub)  RECIPIENT_LEN=$($Pub.Length)  OLD_RECIPIENTS_SAVED=$(Test-Path "$Out\recipients.txt.before")"
} else {
  "AGE_ROTATION_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  AgeKeygenFound=$AgeTool  BackupDirExists=$(Test-Path $BackupDir)  NewIdentityAlreadyThere=$(Test-Path $NewId)"
}
```
- **성공**: `AGE_PUBKEY_FOUND=True` · `NEW_IDENTITY_EXISTS=True` · `RECIPIENTS_LINES=1` · `RECIPIENTS_IS_NEW=True` · `OLD_RECIPIENTS_SAVED=True`.
- **실패 시 대처**: `AGE_PUBKEY_FOUND=False`면 수신자 파일은 **바뀌지 않았습니다**(옛 상태 유지) — `age-keygen` 출력 형식이 달라졌을 수 있으니 세션에 전달. 수신자 파일이 바뀐 상태로 7b를 하지 않으면 **다음 예약 백업부터 새 키로만 잠깁니다** — 7b를 이어서 하십시오.

### 7b. 백업 1회 실행 + 암호화·복원 검증

이 블록은 `scripts/backup/`의 **`origin/main` 판**을 쓰므로 먼저 동등성을 판정합니다(`git diff --quiet origin/main -- scripts/backup`). 다르면(로컬 변경·옛 체크아웃) **실행하지 않고** 거부합니다(체크아웃을 옮기지 않습니다 — 다른 세션이 쓰는 작업 사본일 수 있습니다). Docker Desktop과 `whymath-pg` 컨테이너가 떠 있어야 합니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §7b 새 키로 백업 1회 + 양방향 검증(잠김·복원 가능)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$BackupDir = "C:\Users\kiki\Desktop\__AI\WhyMath-backups"
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$RevokeRows = @(Get-Content "$Out\revoke_checklist.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json)
$RevokeOk = $OutOk -and ($RevokeRows.Count -ge 12) -and (@($RevokeRows | Where-Object { $_.Answer -eq "n" }).Count -eq 0)
$TrustRow = Get-Content "$Out\trust.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
$TrustOk = $OutOk -and ($TrustRow.TrustOk -eq $true)
$NewIdFile = Get-ChildItem "$env:USERPROFILE\whymath-backup-identity-*.key" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$NewId = [string]$NewIdFile.FullName
git fetch origin main 2>$null | Out-Null
git diff --quiet origin/main -- scripts/backup
$PathsMatch = ($LASTEXITCODE -eq 0)
$Py = ""
foreach ($C in @("$Repo\.venv\Scripts\python.exe", "$Repo\src\backend\.venv\Scripts\python.exe")) { if (($Py -eq "") -and (Test-Path $C)) { $Py = $C } }
$DockerUp = ("$(docker version --format '{{.Server.Version}}' 2>$null)".Trim() -ne "")
$PgUp = (@(docker ps --filter "name=^whymath-pg$" --format "{{.Names}}" 2>$null).Count -ge 1)
$RecipientsNew = ((Get-Content "$BackupDir\recipients.txt" -ErrorAction SilentlyContinue | Select-Object -First 1) -match "^age1[0-9a-z]{50,}$")
$EvFile = "$Out\rotation_age.json"
$Ready = $OutOk -and $RevokeOk -and $TrustOk -and ($NewId -ne "") -and $PathsMatch -and ($Py -ne "") -and $DockerUp -and $PgUp -and $RecipientsNew
if ($Ready) {
  $T0 = Get-Date
  & "$Repo\scripts\backup\backup_whymath_pg.ps1" -RequireEncryption
  $BackupOk = $?
  $BackupExit = $LASTEXITCODE
  $Art = Get-ChildItem "$BackupDir\*.dump.age" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  $Fresh = ($Art.LastWriteTime -gt $T0)
  & $Py "$Repo\scripts\backup\verify_encrypted_backup.py" $Art.FullName --identity $NewId --pg-restore-docker-image pgvector/pgvector:pg16
  $VerifyExit = $LASTEXITCODE
  [pscustomobject]@{ BackupOk = $BackupOk; BackupExit = $BackupExit; ArtifactFresh = $Fresh; Artifact = $Art.Name; VerifyExit = $VerifyExit; NewIdentity = (Split-Path $NewId -Leaf); At = (Get-Date -Format "s") } | ConvertTo-Json | Set-Content -Path $EvFile -Encoding UTF8
  "BACKUP_OK=$BackupOk  BACKUP_EXIT=$BackupExit  ARTIFACT_FRESH=$Fresh  ARTIFACT=$($Art.Name)  VERIFY_EXIT=$VerifyExit  SAVED=$(Test-Path $EvFile)"
} else {
  "BACKUP_VERIFY_REFUSED  OutOk=$OutOk  RevokeOk=$RevokeOk  TrustOk=$TrustOk  NewIdentityFound=$($NewId -ne '')  BackupScriptsMatchMain=$PathsMatch  PythonFound=$($Py -ne '')  DockerUp=$DockerUp  PgContainerUp=$PgUp  RecipientsIsAgeKey=$RecipientsNew"
}
```
- **성공**: `BACKUP_OK=True` · `BACKUP_EXIT=0` · `ARTIFACT_FRESH=True` · `VERIFY_EXIT=0`(출력에 `① 잠김 … OK` / `② 열림 … OK`).
- **판독**: `VERIFY_EXIT=1`은 "잠김" 또는 "복원 가능" 중 하나가 미달(**이 새 키쌍으로 복귀하지 말고** 세션에 전달), `2`는 **판정 불가**(도구 부재 — 통과가 아닙니다. `pg_restore` 컨테이너 이미지가 없으면 Docker가 내려받느라 처음엔 시간이 걸립니다).
- **실패 시 대처**: `BACKUP_VERIFY_REFUSED`면 같은 줄의 `False`부터. `BackupScriptsMatchMain=False`면 이 체크아웃의 `scripts/backup/`이 `origin/main`과 다릅니다 — **체크아웃을 옮기지 말고** 세션에 전달하십시오.

### 7c. 개인키를 머신 밖으로 (구·신 둘 다)

**수동 선행**: 이 머신의 age 개인키 파일(`whymath-backup-identity*.key` — 구 1개 + 새 1개)을 **별도 매체**(오프라인 USB·암호 관리자 첨부 등 — 이 PC 디스크가 아닌 곳)에 **각각 복사**하십시오. 이 키를 잃으면 해당 `.dump.age`는 **영구히 열리지 않습니다**.
블록이 키마다 복사본의 **전체 경로를 묻고**, 로컬 파일과 **SHA-256이 같은지** 확인한 뒤에만 로컬 파일을 삭제합니다(같지 않거나 이 PC의 사용자 폴더 안이면 **아무것도 지우지 않습니다**). 삭제 후에도 예약 백업은 **공개키만**으로 계속 동작합니다.
복원 리허설이나 검증이 필요할 때는 별도 매체에서 개인키를 **잠깐 가져왔다가** 끝나면 다시 지우십시오.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §7c age 개인키를 별도 매체로 옮긴 뒤 로컬 사본 삭제 — 복사본 해시 일치 시에만
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
$Ids = @(Get-ChildItem "$env:USERPROFILE\whymath-backup-identity*.key" -ErrorAction SilentlyContinue | Sort-Object Name)
"--- 이 머신의 age 개인키 파일 ---"
$Ids | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
$Pairs = @()
foreach ($Id in $Ids) {
  $CopyPath = (Read-Host "$($Id.Name) 의 별도 매체 사본 전체 경로를 입력(따옴표 없이)").Trim().Trim('"')
  $LocalHash = (Get-FileHash -LiteralPath $Id.FullName -Algorithm SHA256).Hash
  $CopyHash = ""
  if ($CopyPath -ne "") { $CopyHash = [string](Get-FileHash -LiteralPath $CopyPath -Algorithm SHA256 -ErrorAction SilentlyContinue).Hash }
  $Separate = ($CopyPath -ne "") -and (-not ($CopyPath -like "$env:USERPROFILE\*"))
  $Pairs += [pscustomobject]@{ Local = $Id.FullName; Name = $Id.Name; CopyDrive = $CopyPath.PadRight(2).Substring(0, 2).Trim(); HashMatch = (($CopyHash -ne "") -and ($CopyHash -eq $LocalHash)); Separate = $Separate }
}
$Pairs | Select-Object Name, CopyDrive, HashMatch, Separate | Format-Table -AutoSize
$Ready = $OutOk -and ($Ids.Count -gt 0) -and ($Pairs.Count -eq $Ids.Count) -and (@($Pairs | Where-Object { (-not $_.HashMatch) -or (-not $_.Separate) }).Count -eq 0)
if ($Ready) {
  foreach ($Pair in $Pairs) { Remove-Item -LiteralPath $Pair.Local -Force }
  $Left = @(Get-ChildItem "$env:USERPROFILE\whymath-backup-identity*.key" -ErrorAction SilentlyContinue).Count
  [pscustomobject]@{ MovedOff = $Pairs.Count; LocalIdentitiesLeft = $Left; At = (Get-Date -Format "s") } | ConvertTo-Json | Set-Content -Path "$Out\age_identity_moved.json" -Encoding UTF8
  "IDENTITIES_MOVED_OFF=$($Pairs.Count)  LOCAL_IDENTITIES_LEFT=$Left  SAVED=$(Test-Path "$Out\age_identity_moved.json")"
} else {
  "IDENTITY_MOVE_REFUSED  OutOk=$OutOk  KeyFiles=$($Ids.Count)  PairsChecked=$($Pairs.Count)  HashMismatchOrNotSeparate=$(@($Pairs | Where-Object { (-not $_.HashMatch) -or (-not $_.Separate) }).Count)  (로컬 키는 하나도 지우지 않았습니다)"
}
```
- **성공**: `IDENTITIES_MOVED_OFF=2` · `LOCAL_IDENTITIES_LEFT=0`(키가 1개였다면 1·0).
- **`IDENTITY_MOVE_REFUSED`면 로컬 키를 하나도 지우지 않은 상태**입니다. `HashMatch=False`는 복사본이 없거나 내용이 다른 것(복사를 다시), `Separate=False`는 입력 경로가 이 PC 사용자 폴더 안이라는 뜻입니다.
- **판독 주의**: `CopyDrive`가 이 PC의 내장 디스크(`C:`)면 **별도 매체가 아닙니다** — 런북이 드라이브 종류까지는 판정하지 못하므로 그 값을 눈으로 보고 판단하십시오(USB·암호 관리자 동기화 폴더가 아닌 곳에 두면 키 분리가 성립하지 않습니다).
- **평문 `.dump` 처분**: §1의 `PLAIN_DUMPS`가 1 이상이었다면(평문 덤프가 디스크에 남은 상태) 오프사이트 폴더로 나간 적이 있는지 확인하고 처분 방법을 세션과 정하십시오 — 이 런북은 자동 삭제하지 않습니다.

---

## 8. 최종 점검 요약 — 읽기 전용 (창 A)

지금까지의 결과 파일을 모아 **한 화면**으로 요약하고, GitHub 저장소 시크릿이 이번 회전 이후에 **실제로 갱신됐는지**를 시각으로 대조합니다(`PR_AUTO_RESYNC_TOKEN`·`DEPLOY_SSH_KEY`가 이번 시작 시각보다 오래됐으면 `STALE_ROTATABLE`).
외부 키의 `FIRST_OLD_*`는 **키마다 첫 실행 행**을 씁니다(재실행에서는 새 키가 `ACTIVE`로 나오므로 마지막 행을 쓰면 오탐합니다). 실행하지 않은 절은 `n/a`로 나옵니다 — `n/a`는 통과가 아니라 **그 절을 하지 않았다**는 뜻입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · [창 A · 일반] §8 최종 점검 요약 — 읽기 전용(값은 출력하지 않는다)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
cd C:\Users\kiki\Desktop\__AI\WhyMath
git log -1 --oneline
$Latest = Get-ChildItem "C:\Users\kiki\Desktop\__AI\sec34-out" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
$Out = [string]$Latest.FullName
$OutOk = ($Out -ne "") -and (Test-Path $Out)
function Read-Ev([string]$Path) { return (Get-Content $Path -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json) }
function Pick($Obj, [string]$Field) { if ($null -eq $Obj) { return "n/a" }; $V = $Obj.$Field; if ($null -eq $V) { return "n/a" }; return [string]$V }
$Revoke = @(Read-Ev "$Out\revoke_checklist.json")
$Trust = Read-Ev "$Out\trust.json"
$LocalRows = @()
foreach ($F in @(Get-ChildItem "$Out\rotation_local_*.json" -ErrorAction SilentlyContinue | Sort-Object Name)) { $LocalRows += @(Read-Ev $F.FullName) }
$LocalLast = @($LocalRows | Group-Object Name | ForEach-Object { $_.Group | Select-Object -Last 1 })
$ExtRuns = @()
foreach ($F in @(Get-ChildItem "$Out\rotation_external_*.json" -ErrorAction SilentlyContinue | Sort-Object Name)) { $ExtRuns += @(Read-Ev $F.FullName) }
$ExtFirst = @($ExtRuns | Group-Object Env | ForEach-Object { $_.Group | Select-Object -First 1 })
$ExtLast = @($ExtRuns | Group-Object Env | ForEach-Object { $_.Group | Select-Object -Last 1 })
$Pat = Read-Ev "$Out\rotation_pat.json"
$Ssh = Read-Ev "$Out\rotation_ssh.json"
$Age = Read-Ev "$Out\rotation_age.json"
$Moved = Read-Ev "$Out\age_identity_moved.json"
$StampName = Split-Path $Out -Leaf
$StartLocal = [datetime]::ParseExact($StampName, "yyyyMMdd-HHmmss", [Globalization.CultureInfo]::InvariantCulture)
$Api = @(gh api repos/kiki-s-broom/WhyMath/actions/secrets --jq '.secrets[] | [.name, .updated_at] | @tsv' 2>$null)
$Stale = @()
$Seen = @()
foreach ($Row in $Api) { $Parts = "$Row" -split "`t"; $Seen += $Parts[0]; if (@("PR_AUTO_RESYNC_TOKEN","DEPLOY_SSH_KEY") -contains $Parts[0]) { $Upd = [datetime]::Parse($Parts[1], [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal); if ($Upd -lt $StartLocal.ToUniversalTime()) { $Stale += $Parts[0] } } }
$MissingRot = @(@("PR_AUTO_RESYNC_TOKEN") | Where-Object { $Seen -notcontains $_ })
$IdsLeft = @(Get-ChildItem "$env:USERPROFILE\whymath-backup-identity*.key" -ErrorAction SilentlyContinue).Count
"OUT_DIR=$Out  OUT_EXISTS=$OutOk  RUN_START=$StampName  GH_SECRETS_READ=$($Api.Count)"
"SEC34_SUMMARY_1  REVOKE_ROWS=$($Revoke.Count)  REVOKE_NO=$(@($Revoke | Where-Object { $_.Answer -eq 'n' }).Count)  REVOKE_NA=$(@($Revoke | Where-Object { $_.Answer -eq 'na' }).Count)  TRUST_OK=$(Pick $Trust 'TrustOk')  TRUST_AT=$(Pick $Trust 'At')"
"SEC34_SUMMARY_2  LOCAL_ROTATED=$($LocalLast.Count)  LOCAL_UNVERIFIED=$(@($LocalLast | Where-Object { -not $_.Verified }).Count)  FALLBACK_KEPT=$(@($LocalLast | Where-Object { $_.KeepOldAsFallback } | ForEach-Object { $_.Name }) -join ',')  CIPHER_ROWS_POSITIVE=$(@($LocalLast | Where-Object { $_.CipherRows -ne 0 } | ForEach-Object { $_.Name }) -join ',')"
"SEC34_SUMMARY_3  PAT_SET_EXIT=$(Pick $Pat 'SetExit')  PAT_LISTED=$(Pick $Pat 'Listed')  PAT_API_HTTP=$(Pick $Pat 'ApiRepoHttp')  EXTERNAL_FIRST_OLD_ACTIVE=$(@($ExtFirst | Where-Object { $_.OldState -eq 'ACTIVE' }).Count)  EXTERNAL_FIRST_OLD_UNKNOWN=$(@($ExtFirst | Where-Object { $_.OldState -like 'UNKNOWN*' -or $_.OldState -eq 'UNPROBED' }).Count)  EXTERNAL_SKIPPED_LAST=$(@($ExtLast | Where-Object { $_.Action -like 'skipped*' }).Count)  EXTERNAL_KEYS=$($ExtLast.Count)"
"SEC34_SUMMARY_4  DEPLOY_SET_EXIT=$(Pick $Ssh 'SetExit')  DEPLOY_OLD_REJECTED=$(Pick $Ssh 'OldRejected')  DEPLOY_OLD_CHECKED=$(Pick $Ssh 'OldKeyChecked')  AGE_BACKUP_OK=$(Pick $Age 'BackupOk')  AGE_VERIFY_EXIT=$(Pick $Age 'VerifyExit')  AGE_MOVED_OFF=$(Pick $Moved 'MovedOff')  LOCAL_IDENTITIES_LEFT=$IdsLeft"
"SEC34_SUMMARY_5  STALE_ROTATABLE=$($Stale -join ',')  MISSING_ROTATABLE=$($MissingRot -join ',')"
```
- **성공(모두 충족)**: `REVOKE_NO=0` · `TRUST_OK=True` · `LOCAL_UNVERIFIED=0` · `PAT_SET_EXIT=0`·`PAT_LISTED=1` · `EXTERNAL_FIRST_OLD_ACTIVE=0` · `AGE_VERIFY_EXIT=0` · `LOCAL_IDENTITIES_LEFT=0` · `STALE_ROTATABLE`·`MISSING_ROTATABLE`가 **비어 있음**.
- **`n/a`가 나온 줄**은 그 절을 하지 않은 것입니다 — `DEPLOY_*`가 `n/a`인데 §1의 `HAS_DEPLOY_SSH_KEY`가 1이었다면 §6을 빠뜨린 것입니다.
- 이 요약 8줄을 인용문으로 세션에 전달하십시오. 시크릿 값은 어디에도 없습니다.

---

## 9. 막혔을 때 (증상 → 원인 → 대처)

| 증상(판정 줄) | 원인 | 대처 |
|---|---|---|
| `…_REFUSED` / `…_REFUSED  OutOk=False` | 결과 폴더가 없음(§1 미실행) 또는 다른 폴더가 최신 | §1을 먼저. 폴더가 여러 개면 **가장 최근 것**을 쓰므로 §1을 한 번 더 한 경우 §2b·§3부터 다시 |
| `…_REFUSED  RevokeOk=False` | §2b 기록이 없거나 `n`이 있음 | 콘솔에서 마저 폐기 → §2b 재실행 |
| `…_REFUSED  TrustOk=False` | §3 미통과 또는 미실행 | §3 항목별 줄 확인 → §3b → §3 재실행 |
| `TRUST_OK=False` + `IOC_FILES_REMAINING`≥1 | 격리 파일 재출현(재감염 가능성) | **즉시 멈추고** 세션에 전달. §3b로 해결되지 않습니다 |
| `GH_STATUS_EXIT≠0` | 로그인이 안 끝남 | §5a를 다시(브라우저 코드 입력까지) |
| `PAT_REFUSED … Len=0` | 입력 창에 붙여넣기 실패 | 블록 재붙여넣기 → 입력 창에서 우클릭 붙여넣기 |
| `PAT_REFUSED … ApiRepoHttp=403/404` | 저장소 선택·조직 승인 | 토큰 설정(저장소 `WhyMath`만·조직 승인) 확인 후 재발급 |
| `EXTERNAL_FIRST_OLD_ACTIVE`≥1 | 콘솔 폐기가 안 먹음 | 해당 서비스 콘솔에서 키 삭제 → §5c 재실행 |
| `DEPLOY_KEY_REFUSED … NewKeyLoginExit=255` | 서버에 새 공개키 미등록 또는 호스트 키 미승인 | 6a 수동 단계 확인 → 수동 접속으로 지문 승인 → 6b 재실행 |
| `BACKUP_VERIFY_REFUSED … BackupScriptsMatchMain=False` | 체크아웃의 `scripts/backup/`이 `origin/main`과 다름 | 체크아웃을 옮기지 말고 세션에 전달 |
| `VERIFY_EXIT=1` | 잠김 또는 복원 가능 미달 | 구 키쌍으로 복귀하지 말고 세션에 전달 |
| `IDENTITY_MOVE_REFUSED` | 복사본 해시 불일치 또는 같은 PC 안 경로 | 별도 매체에 다시 복사 후 재실행(로컬 키는 안 지워졌음) |

**언제든 멈추고 세션에 알려야 하는 신호**: 낯선 GitHub·Google·클라우드 활동(R4·R5·R7·R11의 건수 ≥1) · `IOC_FILES_REMAINING`≥1 · 실시간 보호가 꺼져 있었음(`Rtp=False`) · `DB_PORTS_PUBLIC_BIND`≥1 · `ACCOUNT`가 본인이 아닌 계정 · 어떤 블록이든 **값처럼 보이는 문자열**이 화면에 출력됨(출력은 이름·길이·판정뿐이어야 합니다).

---

## 10. 세션 몫 — 증적 수령 후 마감 (Kiki가 실행하지 않습니다)

Kiki가 §8의 요약 5줄과 §2의 R4·R5·R7·R11 낯선 이벤트 건수를 전달하면 세션이 다음을 합니다:

1. **acceptance ② 대조** — 요약 줄을 체크리스트(최소 목록 6종 + 인벤토리에서 새로 발견된 이름)와 항목별로 대조해 이행·미이행·`n/a`를 표로 남깁니다. 미이행분은 승계 태스크로 분리 등재합니다(회수 시 "acceptance 전수 재대조" 규칙).
2. **태스크 증적** — `SEC-34`는 사람 소유 태스크라 세션의 `backlog.py done`이 §0의 `start`와 같이 거부될 수 있습니다. 거부되면 우회하지 않고 Kiki 실행용 명령(PR 증적 포함)을 새 런북 블록으로 드립니다. 증적에는 `--artifact`로 PR 참조를 포함합니다.
3. **사고 대장(HARN-118)** — `backlog.py incident add`로 경위를 기록합니다. 제안 필드: 제목 "Phaiakes9 채굴 침해 — 자격증명 전량 로테이션"(80자 이내) · `--cat K`(기존 A~J 분류에 보안 침해가 없음) · `--damage-class latent_days`(08-22 오진 → 09-10 규명까지 약 3주 방치) · `--who-caught kiki` · `--fix-form rule+task`와 `--fix-ref`는 `SEC-34`·`OPS-75`. 같은 사고의 오진 기록 정정(acceptance ④)은 `OPS-74`(PR #1137)가 이미 소유합니다.
4. **MEMORY 결정 로그** — 경위·판정 기준 커밋·남은 위험(폴백으로 남긴 구 키의 기존 암호문, 과거 `.dump.age`의 처분)을 한 단락으로 남깁니다.

## 11. 이 런북이 닫지 않는 것 (정직한 공백)

| 항목 | 상태 | 소유 |
|---|---|---|
| **머신 청결의 증명** | §3은 알려진 지표 점검일 뿐. 백신 **치료**는 별도(MSERT `/N`은 탐지 전용) · 지표에 안 걸리는 지속성은 못 봄 | acceptance ① 잔여 |
| **학생 데이터 노출 판정** | 시점 대조(감염 기간 ↔ `problem_attempt`·`attempt_event` 행) 미수행. §4의 암호문 행수는 그 대체가 아님. 법령 유래 통지 판단은 기계 대체 금지 | acceptance ③ (Kiki + 필요 시 변호사) |
| **기존 암호문의 기밀성** | 폴백으로 남긴 구 키는 기존 행을 지키지 못함 — 키 간 재암호화는 미구현(후속) | 승계 태스크 필요 |
| **과거 `.dump.age`** | 구 개인키가 노출됐으므로 PII가 있었다면 기밀성 상실 가능 — 처분은 ③ 결과에 따라 Kiki | acceptance ③ |
| **`DB_PORTS_PUBLIC_BIND`** | §1이 관측만 함 — 포트 노출·trust 인증 조합은 별도 점검 | 별도 태스크 필요 |
| **서비스 재기동** | 새 환경변수는 다음 프로세스부터 적용 | 기존 가동 절차 |
| **재발 탐지 배선** | 커밋 여유 임계 경고 미착지 | acceptance ⑤ |
| **성능 재측정** | 감염 기간과 겹치는 수치의 재측정은 이 태스크의 나머지 acceptance 완결 후 | `OPS-75` |

*작성: 2026-10-18 · 근거: `SEC-34` acceptance ②⑥⑦⑧⑨⑩, `docs/standards/security_privacy.md` 사고 대응·절대 금지, `docs/standards/incident_response_slo.md` §4-7·§5, `api/_crypto.py` 키 회전 계약, `docs/architecture/db_backup_dr_runbook.md` §1b·§4-1a·§4-5, `.github/branch-protection-setup.md` PAT 최소 권한. 형식 검사: `check_runbook_blocks.py` · `check_ps_scripts.py` 통과. **PowerShell 블록은 작성 환경(Linux·pwsh 없음)에서 실행해 보지 못했고 정적 검사와 정독만 거쳤다 — 첫 실행(§1)은 읽기 전용이라 안전하며, 구문 오류가 있으면 쓰기 블록 앞에서 드러난다.***
