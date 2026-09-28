# G-eos129-item-response-census — 운영 DB 문항 응답 축적 실측 (Kiki 실행 런북)

> **읽기 전용이다.** 이 런북은 운영 DB에 아무것도 쓰지 않는다 — 측정 도구가 조회 전에 트랜잭션을
> `READ ONLY`로 선언하므로, 코드에 쓰기가 섞여 들어와도 DB가 거부한다.
>
> **전제**: 측정 도구 `whymath_backend.l2.item_response_census`가 main에 착지해 있어야 한다
> (EOS-129 부분 이행 PR). 블록 [B]가 main 워크트리에서 그 파일의 실재를 확인하고, 없으면 [D]가
> 실행을 거부한다.

---

## 1. 과제 명칭

EOS-129 ⑤ — 운영 DB의 **문항당 응답 축적** 실측(읽기 전용 1회)

## 2. 목적

진단(CAT)은 지금 모든 문항을 변별도 a=1.0으로 다뤄, 측정 정밀도(SE 0.3)에 닿으려면 이론상 최소
45문항이 든다. 문항마다 a를 데이터로 추정하면(2PL 보정) 이 수가 20·12문항까지 내려갈 수 있다.
그런데 a 추정은 **문항마다 여러 학생의 응답이 쌓여야** 가능하다.

이 실측은 "지금 운영 DB에 a를 추정할 만큼 응답이 쌓인 문항이 몇 개인가"를 센다. 결과는 두 곳에
쓰인다.

- 게이트 `G-eos129-item-response-census`의 clear 증적
- EOS-129 ③(2PL 보정 구현)을 **지금 착수할지, 데이터 축적 대기로 둘지**의 판정 근거 — 후보 문항이
  0에 가까우면 대기가 산출물이다(acceptance ⑤)

## 3. 구체적 절차

| 블록 | 하는 일 | 예상 소요 | 예상 출력 |
|---|---|---|---|
| [A] | Docker·운영 DB(`whymath-pg`) 기동과 도달 확인 | 10초~3분(Docker가 꺼져 있으면 기동 대기) | `DOCKER_OK=True` |
| [B] | 최신 main을 임시 워크트리로 꺼내고 측정 도구 실재 확인 | 10~30초 | `MAIN_SHA=…` · `CENSUS_MODULE_PRESENT=True` |
| [C] | 환경 설정 · DB 도달성 · **실행될 코드가 워크트리 것인지** 확인 | 10~20초 | `PY_OK=True` · `REACH_EXIT=0` · `CENSUS_FROM_WORKTREE=True` |
| [D] | 실측(읽기 전용) — [B]·[C] 판정이 모두 참일 때만 실행 | 수 초~1분 | JSON 1줄 · `CENSUS_EXIT=0` |
| [E] | 판정 기준 해시 기록 · 워크트리 정리 | 수 초 | `JUDGED_AGAINST_MAIN=…` · `WORKTREE_REMOVED=True` |

## 4. 성공 기준

**성공**: `DOCKER_OK=True` · `CENSUS_MODULE_PRESENT=True` · `PY_OK=True` · `REACH_EXIT=0` ·
`CENSUS_FROM_WORKTREE=True` · `CENSUS_EXIT=0`, 그리고 [D]가 `{"a_estimable_items_by_min_students": …`로
시작하는 JSON 한 줄을 찍는다.

**실패**: [D]가 `RUN_REFUSED=True — …`를 찍거나 `CENSUS_EXIT`가 0이 아니다.

### 실패 대처

- `RUN_REFUSED=True` — 그 줄을 **그대로** 세션에 전달한다. 줄에 어느 조건이 False였는지 적혀 있다
  (측정 도구 부재 = PR 미머지 · 코드 출처가 워크트리가 아님 · DB 미도달). 억지로 다시 돌리지 않는다.
- `CENSUS_EXIT=3` — 바로 위에 `CENSUS_FAILED error=<예외 이름>` 한 줄이 있다. 그 줄을 전달한다.
  0건 JSON이 나오지 않은 것은 정상이다 — 이 도구는 측정 실패를 0건으로 위장하지 않는다.

## 5. 실행 환경

- 머신: **Phaiakes9**(Kiki 작업 PC) · **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: Docker Desktop 설치(블록 [A]가 꺼져 있으면 기동한다) · 저장소 `.venv`(`src\backend\.venv`)
- 서버 기동 없음 — 이 런북은 API 서버를 띄우지 않는다

## 6. 창 구분

**새 PowerShell 창 1개**(창 ①)에서 [A]→[E]를 순서대로 붙여넣는다. 오래 점유하는 프로세스가 없어서
창을 나눌 필요가 없다. 블록 사이에 변수가 이어지므로 **같은 창**을 쓴다.

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에만
> 아래 블록으로 넘어간다. [D]는 앞 블록의 판정값을 **스스로 다시 확인**하고, 하나라도 거짓이면
> 실행하지 않는다.

### [A] Docker 기동 + 운영 DB 도달

```powershell
# [Windows PowerShell · Phaiakes9] 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  "DOCKER_DAEMON=down — Docker Desktop 기동을 시도합니다(최대 180초)."
  $DockerExe = @(
    "C:\Program Files\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  "DOCKER_EXE_FOUND=" + [bool]$DockerExe
  if ($DockerExe) { Start-Process $DockerExe }
  for ($i = 1; $i -le 36; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { "DOCKER_UP_AFTER_SEC=" + ($i * 5); break }
  }
}
docker start whymath-pg *> $null
docker ps --filter "name=whymath-pg" --format "{{.Names}} | {{.Status}} | {{.Ports}}"
$Probe = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe)
```

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `Up …` + `0.0.0.0:5433->5432/tcp`.

### [B] 최신 main 워크트리 + 측정 도구 실재

작업 사본(이 클론)은 여러 세션이 같이 쓰므로 지금 어느 브랜치에 있는지 모른다. 그래서 체크아웃을
옮기지 않고 **main을 임시 폴더에 따로 꺼내** 그 코드를 돌린다(원래 작업 사본의 브랜치·미커밋 변경은
건드리지 않는다).

```powershell
# [Windows PowerShell · Phaiakes9] 창 ① (같은 창)
git fetch origin main
$Wt = Join-Path $env:TEMP "whymath-eos129-census"
if (Test-Path $Wt) { git worktree remove --force $Wt }
git worktree prune
git worktree add --detach $Wt origin/main
"MAIN_SHA=" + (git -C $Wt rev-parse --short HEAD)
$ModPath = Join-Path $Wt "src\backend\whymath_backend\l2\item_response_census.py"
$ModPresent = Test-Path $ModPath
"CENSUS_MODULE_PRESENT=$ModPresent"
```

**확인**: `CENSUS_MODULE_PRESENT=True`. False면 측정 도구 PR이 아직 main에 없다는 뜻이다 — [D]가
실행을 거부하므로 계속 붙여넣어도 해는 없지만, 그 줄을 세션에 전달하면 된다.

### [C] 환경 + DB 도달성 + 코드 출처

`.venv`의 파이썬은 이 클론을 가리키도록 설치돼 있을 수 있다. 그래서 `PYTHONPATH`를 워크트리로
돌리고, **실제로 import되는 파일이 워크트리 것인지** 경로를 찍어 확인한다.

```powershell
# [Windows PowerShell · Phaiakes9] 창 ① (같은 창)
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$Py = Join-Path (Resolve-Path "src\backend\.venv\Scripts").Path "python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$ModFile = & $Py -c "import whymath_backend.l2.item_response_census as m; print(m.__file__)"
"CENSUS_IMPORTED_FROM=$ModFile"
$WtFull = (Resolve-Path $Wt).Path
$FromWt = [bool]$ModFile -and $ModFile.StartsWith($WtFull, [StringComparison]::OrdinalIgnoreCase)
"CENSUS_FROM_WORKTREE=$FromWt"
```

**확인**: `PY_OK=True` · `REACH_EXIT=0` · `CENSUS_FROM_WORKTREE=True`(`CENSUS_IMPORTED_FROM`이
`…\Temp\whymath-eos129-census\src\backend\…`로 시작).

### [D] 실측 (읽기 전용 — 앞 판정이 모두 참일 때만 실행)

```powershell
# [Windows PowerShell · Phaiakes9] 창 ① (같은 창)
$OutFile = Join-Path $env:TEMP "eos129_item_response_census.json"
if ($ModPresent -and $FromWt -and $ReachExit -eq 0) {
  & $Py -m whymath_backend.l2.item_response_census --out $OutFile
  "CENSUS_EXIT=$LASTEXITCODE"
} else {
  "RUN_REFUSED=True — MODULE_PRESENT=$ModPresent FROM_WORKTREE=$FromWt REACH_EXIT=$ReachExit"
}
```

**확인**: JSON 한 줄 + `CENSUS_EXIT=0`. 그 JSON 줄을 **통째로** 복사해 세션에 전달한다. 학생·문항
식별자는 들어 있지 않다(집계치만).

### [E] 판정 기준 기록 + 워크트리 정리

```powershell
# [Windows PowerShell · Phaiakes9] 창 ① (같은 창)
"JUDGED_AGAINST_MAIN=" + (git -C $Wt rev-parse --short HEAD)
$env:PYTHONPATH = $null
git worktree remove --force $Wt
"WORKTREE_REMOVED=" + (-not (Test-Path $Wt))
```

**확인**: `WORKTREE_REMOVED=True`.

---

## 7. 게이트 clear 방법

Kiki가 할 일은 아래 값들을 세션에 전달하는 것까지다. 대장 조작(`backlog.py gates clear`)과
EOS-129 판정 기록은 세션이 가져간다 — `--evidence`에 판정 기준 커밋 해시(`JUDGED_AGAINST_MAIN`)가
들어가야 한다(HARN-68).

전달할 값: `DOCKER_OK` · `MAIN_SHA` · `CENSUS_MODULE_PRESENT` · `PY_OK` · `REACH_EXIT` ·
`CENSUS_FROM_WORKTREE` · [D]의 JSON 한 줄 · `CENSUS_EXIT` · `JUDGED_AGAINST_MAIN`.

세션이 JSON에서 읽는 것:

- `a_estimable_items_by_min_students` — 학생 30·100·200·500명 이상 **그리고** 정답·오답이 둘 다
  있는 문항 수. 전부 0이거나 0에 가까우면 EOS-129는 **데이터 축적 대기**다.
- `b_calibratable_items` — 지금의 b 보정기(응답 5건 이상)가 보정할 수 있는 문항 수. a보다 먼저
  찰 수밖에 없는 하한이라, 이것조차 0이면 a는 볼 것도 없다.
- `distinct_students` · `graded_responses` · `problems_total` — 규모 확인용.

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **a 추정에 몇 명이 필요한지는 정하지 않는다.** 도구는 여러 임계에서 셀 뿐이고, 문헌마다 요구치가
  다르다(수백 명 단위가 흔히 인용된다). 판정 임계는 결과를 본 뒤 사람이 정한다.
- **내부 테스트 계정과 실학생을 구분하지 않는다.** 운영 DB에 시연·측정용 응답이 섞여 있으면 그 응답도
  센다. 실학생 표본은 2026-12-31 이후 계획이라(EOS-135), 지금 나오는 수는 "실학생 분포"가 아니라
  "현재 DB에 쌓인 응답"이다.
- **학생의 능력 분포는 보지 않는다.** a 추정은 능력이 고르게 퍼진 응답자에서 안정되는데, 이 도구는
  학생 수만 센다. 추정 가능 문항이 충분히 나오면 그때 능력 분산을 따로 확인한다.
