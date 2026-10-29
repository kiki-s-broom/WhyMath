# 저작 회차 한 줄 실행 런북 (EOS-208 — 모든 회차 공통)

> **판정 기준: main `4ec479e6`**(EOS-197 회차 산출물이 들어간 커밋) + 이 런북을 싣는 EOS-208 PR.
> 실행 코드는 `src/backend/whymath_backend/harness/authoring_round.py`(오케스트레이터)·
> `authoring_round_probe.py`(탐침)·`authoring_round_config.py`(설정)·`authoring_round_ports.py`
> (외부 경계)이며, 저작·검수·집계·감사는 기존 CLI를 그대로 부른다(로직 복제 없음).
>
> **이 런북이 대신하는 것**: EOS-197 런북(`docs/ops/eos197_authoring_round_runbook.md`)의 붙여넣기
> 블록 [A]~[L] 15개 이상. 그 블록들은 그 런북에 **수동 대안**으로 남아 있다(이 런북이 막힐 때만).

---

## 이것이 무엇을 하는가 (단계 8개 · 한 줄이 순서대로 돈다)

| 단계 | 런북 블록 | 무엇 | 쓰기 |
|---|---|---|---|
| `preflight` | [B]~[E] | 워크트리·코드 출처·탐침(라우팅·좌석·키 형태·Ollama 타임아웃 주입)·Ollama 모델·산출 폴더 현황 | 없음 |
| `author-local` | [F] | 로컬 좌석 저작 — 목표 CU에 닿거나 시도 예산을 다 쓸 때까지 회차를 덧붙인다 | 산출 파일 |
| `author-cloud` | [G] | 유료 좌석 저작 — 같은 규칙 · **시도 예산 상한 필수** | 산출 파일 · 유료 호출 |
| `check` | [H] | 산출물·GenerationLog 4필드·과목/slug·`provenance_audit --require-runs` | 없음 |
| `queue` | [I] | 좌석 번갈아 섞은 검수 큐(slug 중복 제외 · 이미 있으면 덮어쓰지 않는다) | 큐 파일 |
| `review` | [J-G] | **검수 창**이 뜬다 — 사람이 판정한다. 창을 닫으면 판정 수를 큐 행 수와 대조 | 검수 기록 |
| `summarize` | [K] | HIT·비용·주간 KPI 미리보기(원장에는 쓰지 않는다) | 산출물 없음(상태 파일·설정 스냅샷만 갱신) |
| `deliver` | [L] | 산출물 브랜치 커밋·push·원격 대조 — **판정 수 = 큐 행 수**이고 산출물 밖 변경 0일 때만 | 원격 브랜치 1개 |

**이어하기**: 같은 한 줄을 다시 붙여넣으면 **실물로 끝난 쓰기 단계는 건너뛰고** 남은 단계부터 간다
(판정은 상태 파일이 아니라 산출 파일·행 수·원격 대조로 한다). 검수를 나눠 해도, 창을 닫아도, 저작
도중 `Ctrl+C`로 끊어도 같은 한 줄이면 된다. 끊긴 저작 회차의 시도 수는 **소진으로 센다**(유료 좌석이
같은 예산을 두 번 쓰지 않게).

**거부(자가거부)**: 쓰기 단계는 실행 직전에 선행 조건을 다시 계산하고, 하나라도 False면 아무것도 쓰지
않고 `WRITE_REFUSED=True stage=… FALSE: …` 줄을 낸 뒤 멈춘다. 그 줄의 항목 이름이 곧 원인이다
(아래 「거부·실패 줄 읽는 법」).

**출력**: 단계마다 `▶`로 시작하는 한국어 요약 줄과 `KEY=VALUE` 판정 줄이 함께 나온다. 마지막 줄은
`ROUND_STATUS=complete`(회차 완료) 또는 `ROUND_STATUS=incomplete NEXT_STAGE=…`이고, 바로 아래
`ROUND_EXIT=` 줄이 종료 코드다(0 완료 · 1 거부·실패·미완 · 2 설정 오류).

---

## 회차 설정 파일

회차 하나 = 설정 파일 하나: `docs/ops/authoring_round_<회차 이름>.yaml`. **세션이 만들어 main에
올린다**(예시·정본 형식: `docs/ops/authoring_round_eos197.yaml`). 담는 값: 회차 이름·작업 ID·
워크트리 경로·Ollama 타임아웃(기본 180초)·좌석별(종류·모델·목표 CU·시도 예산·클라우드 라우팅 신호)·
앵커 spec·시드 코퍼스·저작 인자·검수자·산출물 브랜치.

- **목표·예산만 바꿀 때**(좌석이 목표에 못 미쳤는데 더 돌리고 싶을 때): 워크트리 안의 그 설정 파일에서
  `target_cu`·`attempt_budget`을 고치고 같은 한 줄을 다시 붙여넣는다. 남은 예산만큼 이어서 저작한다.
  **검수 큐를 만든 뒤에는 저작을 덧붙이지 않는다**(검수 분모가 바뀐다 — 저작 단계는 `AUTHOR_FROZEN`으로
  건너뛰고 다음 단계로 간다. 목표·예산 상향은 큐를 만들기 전에만 반영된다).
  설정 파일 수정은 deliver의 "산출물 밖 변경"으로 세지 않으며, 실제로 쓰인 설정은 산출 폴더의
  `round_config.yaml`로 함께 보내진다.
- 유료 좌석 `attempt_budget`은 **필수**이고 300을 넘으면 설정 오류(exit 2)로 거부된다(오타 과금 방지).

---

## 6항목 사전 브리핑

### ① 과제 명칭
저작 회차 한 줄 실행 — 좌석별 LLM 저작 → 검사 → 검수 큐 → 검수(창) → 집계 미리보기 → 산출물 전달.

### ② 목적
한 회차의 산출물(CU·생성 로그·회차 대장·검수 기록)을 만들어 세션에 git 브랜치로 넘긴다. 세션이 그
브랜치로 주간 KPI 원장(`metrics/weekly.json`)을 기록하고 main에 반영한다.

### ③ 구체적 절차 (예상 소요)

| 블록 | 무엇 | 예상 |
|---|---|---|
| [R0] | 회차 이름 입력(한 줄 · 단독) | 즉시 |
| [R1] | 격리 워크트리 준비·실행 변수 설정 | 1분 |
| [R2-D] | (선택) 미리보기 — 무엇을 할지 보고 아무것도 쓰지 않는다 | 1분 |
| [R2] | **한 줄 실행** — 끝까지 간다. 검수 창이 뜨면 거기서 판정 | 저작 15~45분/좌석 + 검수 60~120분 |
| [R3] | (선택) 워크트리 정리 — 세션이 수신을 확인한 뒤에만 | 즉시 |

키가 없다고 나오면 [K-1]·[K-2](키 입력·등록)를 한 번 하고 [R2]를 다시 붙여넣는다. `…_BUDGET_EVIDENCED=False`가
나오면 「예약 풀기」 한 줄을 쓴다.

### ④ 성공 기준
- 마지막에 `PUSH_VERIFIED=True` · `ROUND_STATUS=complete` · `ROUND_EXIT=0`.
- 검수 도중 쉬면 `REVIEW_DONE=False`·`ROUND_EXIT=1`이 정상이다 — 같은 [R2]를 다시 붙여넣으면 남은 것부터.
- **실패 시 대처**: `WRITE_REFUSED=True` 또는 `STAGE_FAILED` 줄이 나오면 그 블록은 아무것도 쓰지 않았거나
  (거부) 그 단계에서 멈췄다(실패). 「거부·실패 줄 읽는 법」 표에서 항목 이름을 찾아 조치하고 [R2]를 다시.
  표에 없으면 출력 전체를 회신한다.

### ⑤ 실행 환경
- **머신**: Phaiakes9 = 평소 쓰시는 이 PC. SSH·WSL 불요.
- **시스템**: Windows PowerShell.
- **원 작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`(평소 클론 — 브랜치·미커밋 변경을 건드리지 않는다).
- **실행 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath-<회차 이름>`([R1]이 main 최신으로 만드는 격리 워크트리).
- **파이썬**: `C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe`(오케스트레이터가 같은
  인터프리터로 자식 CLI를 부른다 — `python -m` 형태).
- **선행 조건**: Ollama 가동(로컬 좌석) · 인터넷(유료 좌석·push) · OpenRouter 키(User 환경변수 — 한 번 등록).
  Docker·DB·백엔드 서버는 **불요**(회차는 DB에 쓰지 않는다).

### ⑥ 창 구분
- **창 ①**(새 PowerShell 창) — [R0]~[R3] 전부 같은 창. [R2]가 도는 동안 그 창은 건드리지 않는다.
  `Ctrl+C`는 복사가 아니라 **중단 신호**다(중단해도 다시 [R2]로 이어진다).
- **창 ②**(Ollama가 꺼져 있다고 나올 때만 · 새 창) — `ollama serve` 한 줄. 그 창은 서버가 점유하므로
  이후 아무것도 입력하지 않는다.
- **검수 창**(별도 윈도) — [R2]가 검수 단계에서 띄운다. 창을 닫으면 [R2]가 이어서 판정 수를 센다.

---

## [R0] 회차 이름 — 창 ① (이 한 줄만 단독으로 붙여넣는다)

> `Read-Host`는 함께 붙여넣은 다음 줄을 입력으로 삼킨다 — 이 블록은 반드시 단독으로. 세션이 알려 준
> 회차 이름(설정 파일 `authoring_round_<이름>.yaml`의 `<이름>` 부분 — EOS-197이면 `eos197`)을 친다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R0] 회차 이름 입력 (단독 한 줄 · 쓰기 없음)
$Round = Read-Host "회차 이름(세션이 알려 준 영문 이름)"; "ROUND_NAME=[$Round] LENGTH=$($Round.Length)"
```

**판정**: `ROUND_NAME=[…]` 괄호 안이 세션이 알려 준 이름과 같고 `LENGTH`가 0이 아니면 [R1]로.

## [R1] 격리 워크트리 준비 — 창 ① (워크트리 폴더 1개 · 처음 한 번)

이미 워크트리가 있으면 **건드리지 않는다**(앞 시도의 산출물 보존 — 이어하기의 전제).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R1] 격리 워크트리 준비 + 실행 변수 (워크트리 폴더 1개)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Wt = if ($Round) { "C:\Users\kiki\Desktop\__AI\WhyMath-$Round" } else { $null }
$Cfg = if ($Round) { "$Wt\docs\ops\authoring_round_$Round.yaml" } else { $null }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$WtExisted = [bool]($Wt -and (Test-Path $Wt))
$CfgOnMain = [bool]($Round -and (git ls-tree --name-only origin/main "docs/ops/authoring_round_$Round.yaml"))
if ($Round -and $CfgOnMain -and (-not $WtExisted)) { git worktree add --detach $Wt origin/main; "WORKTREE_CREATED=$(Test-Path $Wt)" } else { "WORKTREE_ADD_SKIPPED=True — Round=[$Round](비면 [R0]부터) CfgOnMain=$CfgOnMain(False면 회차 설정이 아직 main에 없다 — 세션에 회신) WtExisted=$WtExisted(True면 앞 시도의 워크트리를 그대로 쓴다 — 정상)" }
"WORKTREE_PRESENT=$([bool]($Wt -and (Test-Path $Wt))) CONFIG_PRESENT=$([bool]($Cfg -and (Test-Path $Cfg))) PY_PRESENT=$(Test-Path $Py)"
"MAIN_HEAD=$(git rev-parse --short origin/main)"
if ($WtExisted -or ($Wt -and (Test-Path $Wt))) { "WORKTREE_HEAD=$(git -C $Wt rev-parse --short HEAD)" } else { "WORKTREE_HEAD=없음 — 위 SKIPPED 줄의 이유를 보세요" }
```

**판정**: `WORKTREE_PRESENT=True CONFIG_PRESENT=True PY_PRESENT=True`면 [R2]로. 두 해시가 다르면(앞 시도의
워크트리) 그대로 진행해도 된다 — [R2]의 준비 점검이 코드 출처를 실측해 막는다. 해시는 회신에 적는다.

## [R2-D] (선택) 미리보기 — 창 ① (쓰기 없음 · 한 줄)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R2-D] 미리보기 (쓰기 없음 · 다음에 할 일과 명령만 보인다)
if ($Py -and $Wt -and $Cfg -and (Test-Path $Cfg)) { cd $Wt; $env:PYTHONPATH = "$Wt\src\backend"; & $Py -m whymath_backend.harness.authoring_round --config $Cfg --worktree $Wt --dry-run; "ROUND_EXIT=$LASTEXITCODE" } else { "RUN_REFUSED=True — Py=[$Py] Wt=[$Wt] Cfg=[$Cfg] — 새 창이면 [R0]·[R1]부터" }
```

**판정**: `READY_PREFLIGHT=True`와 `DRY_RUN_PLAN stage=…` 줄이 보이면 준비가 된 것이다. `READY_PREFLIGHT=False`면
그 위 `PREFLIGHT …` 줄의 False 항목을 「거부·실패 줄 읽는 법」에서 찾는다.

## [R2] 한 줄 실행 — 창 ① (이 한 줄만 붙여넣는다 · 다시 붙여넣으면 이어서 간다)

> 이 한 줄은 검수 단계에서 **검수 창**을 띄운다. 터미널 키 입력 검수(`review.ui: terminal`)로 설정된
> 회차라면 판정 키를 이 창에서 받으므로 **다른 줄과 함께 붙여넣지 않는다**(함께 붙여넣은 줄이 판정
> 입력으로 먹힌다 — 2026-09-22 실측).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R2] 저작 회차 한 줄 실행 (쓰기·유료 호출·push는 오케스트레이터가 단계마다 스스로 재검사 후 실행)
if ($Py -and $Wt -and $Cfg -and (Test-Path $Cfg)) { cd $Wt; $env:PYTHONPATH = "$Wt\src\backend"; & $Py -m whymath_backend.harness.authoring_round --config $Cfg --worktree $Wt; "ROUND_EXIT=$LASTEXITCODE" } else { "RUN_REFUSED=True — Py=[$Py] Wt=[$Wt] Cfg=[$Cfg] — 새 창이면 [R0]·[R1]부터" }
```

**예상 출력**: `STAGE_START stage=preflight` → `READY_PREFLIGHT=True` → 좌석마다 `ROUND_START`/`ROUND_END`
(저작 CLI의 진행 로그가 그 사이에 흐른다) → `AUTHOR_DONE … outcome=target_met|budget_exhausted` →
`CHECK_OK=True` → `QUEUE_WRITTEN=True QUEUE_LINES=N` → 검수 창 → `REVIEW_DONE=True` → `PREVIEW_…` →
`PUSH_VERIFIED=True` → `ROUND_STATUS=complete` → `ROUND_EXIT=0`.

- `outcome=budget_exhausted`(목표 미달)는 실패가 아니다 — 회차는 다음 단계로 간다(실패도 산출물이다).
  더 돌리려면 큐가 만들어지기 **전에** 설정의 목표·예산을 바꾸고 [R2]를 다시.
- 진행 로그가 **5분 이상** 멈추면 `Ctrl+C`로 끊고 [R2]를 다시 붙여넣는다(끊긴 회차는 소진으로 센다).

## 단계 하나만 다시 — 창 ① (한 줄)

집계 미리보기만 다시 보고 싶을 때(산출물 쓰기 없음 — 상태 파일·설정 스냅샷만 갱신). 다른 단계 이름도 같은 형태로 쓸 수 있다
(`preflight`·`author-local`·`author-cloud`·`check`·`queue`·`review`·`summarize`·`deliver` — 선행 조건 재검사는 그대로).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 집계 미리보기만 다시 (산출물 쓰기 없음 · 상태 파일만 갱신)
if ($Py -and $Wt -and $Cfg -and (Test-Path $Cfg)) { cd $Wt; $env:PYTHONPATH = "$Wt\src\backend"; & $Py -m whymath_backend.harness.authoring_round --config $Cfg --worktree $Wt --stage summarize; "ROUND_EXIT=$LASTEXITCODE" } else { "RUN_REFUSED=True — Py=[$Py] Wt=[$Wt] Cfg=[$Cfg] — 새 창이면 [R0]·[R1]부터" }
```

## 예약 풀기 — `…_BUDGET_EVIDENCED=False`가 나올 때만 (한 줄)

저작 회차는 호출 **전에** 시도 수를 예약하고 그 예약을 줄이지 않는다(끊긴 회차가 같은 유료 예산을 두 번 쓰지
않게). 그런데 호출 기록 없이 예약만 남는 경우가 세 가지 있다 — ① 시작 직후 실패한 실행(임포트·설정 오류 · 호출 0건)
② Ctrl+C·시간 상한으로 회차 중간에 끊겨 나머지 예약분을 호출하지 못한 경우 ③ 요청보다 적게 시도하고 끝난 회차.
그 예약만으로 예산이 차면 오케스트레이터는 '예산 소진 완료'라고 하지 않고 거부한다. **끊긴 원인(`STAGE_FAILED`·
`STAGE_INTERRUPTED` 줄)을 확인한 뒤에만** 아래 한 줄로 예약을
실물 근거(대장·genlog)로 되돌린다 — 되돌린 수는 상태 파일 이력에 남는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 근거 없는 예약 풀기 + 이어서 실행 (상태 파일 이력에 기록)
if ($Py -and $Wt -and $Cfg -and (Test-Path $Cfg)) { cd $Wt; $env:PYTHONPATH = "$Wt\src\backend"; & $Py -m whymath_backend.harness.authoring_round --config $Cfg --worktree $Wt --release-unevidenced; "ROUND_EXIT=$LASTEXITCODE" } else { "RUN_REFUSED=True — Py=[$Py] Wt=[$Wt] Cfg=[$Cfg] — 새 창이면 [R0]·[R1]부터" }
```

`RESERVATION_RELEASED seat=… from=… to=…` 줄이 풀어 준 수다.

## [K-1] 키 입력 — `OPENROUTER_KEY_SHAPE_OK=False`가 나올 때만 · 이 블록만 단독으로

> 입력은 화면에 보이지 않는다(별표도 없다). 입력 길이는 같은 줄이 바로 출력한다 — 0이면 붙여넣기 실패.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [K-1] 키 입력 · 이 블록만 단독으로 · 입력은 화면에 보이지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$KeySecure = Read-Host "OpenRouter 키(sk-or- 로 시작)를 붙여넣고 Enter" -AsSecureString; "KEY_INPUT_LENGTH=$($KeySecure.Length)"
```

## [K-2] 키 등록 — [K-1] 다음에만

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [K-2] 키 등록 · User 환경변수 1개 · 키 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$KeyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($KeySecure)
$KeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyBstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyBstr)
$KeyLength = ([string]$KeyPlain).Length
$KeyShapeOk = ($KeyLength -ge 20) -and ([string]$KeyPlain).StartsWith("sk-or-") -and (-not ([string]$KeyPlain).Contains([string][char]0x2026))
$ExistingUserKey = [bool][Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "User")
"KEY_LENGTH=$KeyLength KEY_SHAPE_OK=$KeyShapeOk EXISTING_USER_KEY=$ExistingUserKey"
if ($KeyShapeOk -and (-not $ExistingUserKey)) { [Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $KeyPlain, "User"); $env:OPENROUTER_API_KEY = $KeyPlain; "WRITTEN_USER_KEY_LENGTH=$(([string][Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY','User')).Length)" } else { "WRITE_REFUSED=True — 키를 쓰지 않았다. KEY_SHAPE_OK=$KeyShapeOk(True여야 — 20자 이상·sk-or- 시작·생략 문자 없음) EXISTING_USER_KEY=$ExistingUserKey(False여야 — 있으면 덮어쓰지 않는다. 키 등록 뒤에 연 창이 아니면 새 창을 열어 [R0]부터)" }
Remove-Variable KeyPlain, KeySecure
```

`WRITTEN_USER_KEY_LENGTH`가 `KEY_LENGTH`와 같으면 등록됐다. [R2]를 다시 붙여넣는다(이 창은 `$env:`로 이미 키를 안다).

## [R3] (선택) 워크트리 정리 — 세션이 수신을 확인한 **뒤에만**

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R3] 워크트리 정리 (쓰기 · 세션의 수신 확인 뒤에만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Branch = if ($Wt -and $Cfg -and (Test-Path $Cfg)) { & $Py -c "import sys,yaml; print(yaml.safe_load(open(sys.argv[1], encoding='utf-8-sig'))['deliver']['branch'])" $Cfg } else { $null }
$WtSha = if ($Wt -and (Test-Path $Wt)) { git -C $Wt rev-parse HEAD } else { $null }
$RemoteSha = if ($Branch) { ((git ls-remote origin "refs/heads/$Branch") -split "\s+")[0] } else { $null }
$Safe = [bool]($WtSha -and $RemoteSha -and ($WtSha -eq $RemoteSha))
"PRECHECK_R3 Branch=[$Branch] WorktreeSha=$WtSha RemoteSha=$RemoteSha Safe=$Safe"
if ($Safe) { git worktree remove $Wt; "WORKTREE_REMAINS=$(Test-Path $Wt)" } else { "WRITE_REFUSED=True — 지우지 않았다. 워크트리 커밋이 원격 산출물 브랜치와 같아야 지운다(Safe=$Safe) — 산출물이 원격에 없으면 지우면 안 된다" }
```

`git worktree remove`가 남은 파일(상태 파일 갱신분 등) 때문에 거부하면 그대로 두셔도 된다 — 다음 회차에 방해가 되지 않는다.

---

## 거부·실패 줄 읽는 법

| 줄에 보이는 항목(False·실패) | 뜻 | 조치 |
|---|---|---|
| `CODE_FROM_WORKTREE` · `CHILD_CODE_FROM_WORKTREE` | 실행된 코드가 워크트리 것이 아니다(PYTHONPATH가 안 먹음) | 새 창에서 [R0]·[R1]·[R2] |
| `WORKTREE_ISOLATED` | 평소 클론에서 돌았다 | [R1]이 만든 워크트리 경로인지 확인 |
| `CLI_FLAGS_OK` · `SPEC_PLAN_OK` · `SUBJECT_OK` · `SLUG_PREFIX_OK` | 워크트리 코드가 이 회차가 요구하는 코드보다 옛것이다 | 세션에 회신(워크트리를 새로 만들어야 할 수 있다) |
| `…_TIMEOUT_INJECTED` | Ollama 타임아웃 주입이 저작 CLI에 닿지 않았다(EOS-197 30초 공전 유형) | 출력 회신 |
| `…_OLLAMA_MODEL_PRESENT` · `OLLAMA_REACHABLE=False` | Ollama가 꺼졌거나 모델이 없다 | 창 ②에서 `ollama serve`, 모델이 없으면 `ollama pull qwen3:30b-a3b` 후 [R2] |
| `…_MODEL_ROUTED` · `…_LOCAL_ONLY` | 라우터가 설정과 다른 모델로 보내거나 로컬 좌석이 클라우드에 닿을 수 있다(유료 위험) | 멈추고 회신 |
| `…_KEY_SHAPE_OK` | OpenRouter 키가 없거나 형태가 이상하다 | [K-1]·[K-2] 후 [R2] |
| `…_SEAT` · `…_PIN` · `…_JURISDICTION` · `…_ANTHROPIC_OFF` | 클라우드 좌석 설정이 회차 설정과 다르다 | 멈추고 회신 |
| `AUTHOR_FROZEN`(거부 아님) | 검수 큐가 이미 있어 저작을 덧붙이지 않고 건너뛰었다 | 정상 — 더 저작하려면 세션에 새 회차를 요청 |
| `…_BUDGET_EVIDENCED` · `AUTHOR_UNEVIDENCED` | 시도 예산이 **호출 기록 없는 예약**으로 찼다(시작 직후 실패 · 중간에 끊긴 회차의 나머지 · 요청보다 적게 시도한 회차) | 끊긴 원인(`STAGE_FAILED`·`STAGE_INTERRUPTED` 줄)을 확인한 뒤 「예약 풀기」 한 줄 |
| `…_ALLOWED_PROVIDERS` | OpenRouter 허용 공급사 목록이 설정(`expected_allowed_providers`)과 다르다 | 멈추고 회신 |
| `LOCK_HELD=True` | 같은 회차가 다른 창에서 이미 돌고 있다(또는 앞 실행이 강제 종료돼 잠금이 남았다) | 다른 창 확인 → 정말 없으면 같은 줄의 `Remove-Item` 경로를 지운 뒤 [R2] |
| `BRANCH_NAME_VALID` | 설정의 산출물 브랜치 이름이 git 규칙에 어긋난다 | 회신 |
| `SPEC_PLAN_UNCHANGED` | 회차 도중 spec이 바뀌었다 | 회신 |
| `REVIEW_COMPLETE` · `JUDGED<QUEUE_LINES` | 검수가 남았다 — 업로드하지 않는다 | [R2]를 다시(검수 창이 남은 것부터) |
| `OTHER_DIRTY_ZERO` | 산출물 밖 파일이 바뀌었다(`OTHER_DIRTY_PATHS` 줄에 경로) | 경로를 회신 |
| `REMOTE_BRANCH_ABSENT` | 산출물 브랜치가 원격에 이미 있다(앞 push 성공 가능) 또는 원격 조회 실패 | 회신 |
| `STAGE_FAILED … error=RoundStopped` | 저작 회차가 멈췄다 — CAUSE 줄 앞의 `[RoundExit2]`(연속 무진전 알람·설정 오류)·`[RoundTimeout]`(회차 시간 상한)·`[LedgerNotWritten]`(대장 없이 종료 — 시작 직후 실패)·`[LaunchError]` | `STAGE_FAILED_CAUSE` 줄과 위 진행 로그를 회신 |
| `STAGE_FAILED … error=ReviewToolFailed` | 검수 창이 비정상 종료했다(파일을 다른 프로그램이 잡음·tkinter 없음 등) | 그 프로그램을 닫고 [R2] — 판정은 건마다 즉시 기록돼 남아 있다 |
| `STAGE_FAILED … error=CommitVerificationFailed` · `RemoteMismatch` | 커밋에 산출물 밖 파일이 섞였거나 push 뒤 원격 끝이 그 커밋이 아니다 | 회신(push하지 않았거나 대조 실패) |
| `STAGE_FAILED … error=ProbeFailed` | 탐침이 import부터 실패했다(원인 예외 타입이 CAUSE 줄에) | 회신 |
| `STAGE_FAILED … error=ArtifactCheckFailed` | GenerationLog 4필드 결손·감사 실패·합계 미달 | `SEAT_CHECK`·`PROVENANCE_…` 줄을 회신 |
| `STAGE_FAILED … error=GitPushFailed` | push 인증·네트워크 실패(커밋은 워크트리에 남는다) | [R2]를 다시 — 커밋을 그대로 보낸다 |
| `CONFIG_ERROR=` | 설정 파일 형식 오류(exit 2) | 그 줄을 회신 |

**회신**: [R2] 출력 전체를 **자르지 말고** 준다(잘린 출력으로는 분모가 조용히 줄어든 것을 놓친다).
파일은 회신하지 않아도 된다 — 세션은 `deliver`가 push한 브랜치에서 읽는다.

---

## 알려진 한계 (정직한 공백)

- **실행 검증 불가 구간**: 이 저장소의 CI·개발 세션에는 Windows·PowerShell·Ollama·검수 창이 없다.
  오케스트레이터의 단계 흐름·거부 가드·이어하기는 테스트(`tests/backend/harness/test_authoring_round*.py`
  — 자식 프로세스는 가짜, git은 실물 임시 저장소)로 고정했지만, Windows 콘솔에서의 표시·`Ctrl+C` 전파·
  검수 창 종료 코드는 **첫 실회차에서 확인**해야 한다.
- 탐침은 런북 [B]~[D]가 쓰던 것과 같은 함수를 자식 프로세스에서 부른다 — 탐침이 통과한 환경과 저작 CLI가
  도는 환경은 같은 인터프리터·같은 환경변수지만, Ollama 데몬 상태는 탐침 뒤에 바뀔 수 있다(그때는 저작
  회차가 `generation_failed`로 끝나고 `outcome_counts`에 남는다).
- 끊긴 저작 회차의 시도 수는 대장 기록이 없어도 **예약분 전체를 소진으로** 센다(보수적 — 실제 호출은 더
  적었을 수 있다). `STATE_MISMATCH seat=…` 줄이 그 차이를 보여 준다. 그 예약만으로 예산이 차서 거부되면
  「예약 풀기」 한 줄로 실물 근거까지만 되돌린다(끊긴 순간 진행 중이던 호출 1건은 근거에 안 잡혀 풀릴 수 있다).
  예산 자체를 늘리려면 설정에서 올린다.
