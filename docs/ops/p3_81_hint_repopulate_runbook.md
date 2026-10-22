# P3-81 — 운영 DB 힌트 카탈로그 재적재 (Kiki 실행 런북)

> 판정 기준: main `117d3f49` (2026-10-22). P3-77(PR #1721)이 이 main에 병합돼 있다.
>
> 태스크 `P3-81`의 acceptance ②·③을 이행하는 **Kiki 머신용 실행 절차**다. 이 런북이 쓰는 읽기 전용
> 프로브 `scripts/ops/p3_81_hint_catalog_probe.py`는 **이 PR이 병합돼야 `origin/main`에 있다.**
> 병합 전에 [B]를 돌리면 `PROBE_IN_WT=False`로 거부된다(미머지 파일을 쓰는 명령이므로 일부러 둔
> 자가검증이다).
>
> **이 문서가 실행으로 검증한 것과 못 한 것은 §9에 따로 적었다.** 못 한 것을 한 것처럼 읽지 않는다.

---

## 1. 과제 명칭

운영 DB `hints` 테이블 재적재 — P3-77의 값 동치 게이트(게이트 B·④)를 기존 힌트 행에 반영하고, 전후를
실측해 서빙 경로가 정답 누설 L3를 내지 않는지 표본으로 확인한다.

## 2. 목적

P3-77이 힌트 게이트 B·④에 값 동치 축을 넣어 `verified`·`gate_report` 판정이 바뀌었다. 그러나 운영 DB의
`hints` 행은 `python -m whymath_backend.l4.hint_content.populate --apply`를 다시 돌리기 전까지 **종전
판정 그대로**다 — 정답과 값이 같은 산술식을 보여 주는 L3(예: 정답 31인 문항의 L3가 `1 + (11 - 1)*3`을
보여 주는 경우)가 `verified=true`로 남아 서빙될 수 있다. 서빙 reader(`store.find_served_hint`)는
`verified=true` 행만 읽고 값 판정은 다시 하지 않으므로, 행이 갱신돼야 누설이 닫힌다.

이 실행의 결과는 세 곳에 쓰인다. ① `hints` 행의 `verified`·`gate_report`가 새 판정으로 바뀐다 ② 전후 수치가
P3-81 acceptance ②의 증거가 된다 ③ 서빙 표본의 누설 0건이 acceptance ③의 증거가 된다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | DB 쓰기 | 기대 출력(판정값) |
|---|---|---|---|
| A | Docker Desktop·`whymath-pg` 기동 확인 | 없음 | `DOCKER_OK=True` |
| B | main 기준 임시 worktree 생성(공유 클론 무변경) | 없음 | `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True` |
| C | 환경 주입 · 코드 출처 · DB 도달 · **적재 전 실측**(BEFORE) | 없음 | `CODE_OK=True` · `REACH_EXIT=0` · `BEFORE_OK=True` |
| D | **시험 실행(dry-run)** — 새 판정으로 생성만 하고 적재하지 않음 | 없음 | `DRY_OK=True` · 검수 수 예측 |
| E | `hints` 표 백업(되돌리기용 사본) | 없음(파일만 생성) | `BACKUP_OK=True` |
| F | 적재 확인 입력(`APPLY` 한 단어) | 없음 | `CONFIRMED=True` |
| G | **적재(`--apply`)** — 여기서만 DB에 쓴다 | **있음** | `APPLY_EXIT=0` |
| H | **적재 후 실측**(AFTER) · 전후 대조 · 예측 대조 | 없음 | `WRITE_OK=True` |
| I | 서빙 경로 표본 · 카탈로그 전수의 정답 누설 판정 | 없음 | `SERVE_EXIT=0` · `SCAN_EXIT=0` |
| J | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

**소요 시간은 실측하지 못했다.** dry-run과 적재는 같은 생성·판정 계산을 하므로 서로 비슷한 시간이 든다.
이 샌드박스에서는 4경로 소표본만 돌려 1초 미만이었고, 운영 규모(수천 경로)의 시간은 미확인이다 — 첫
실행의 [D] 소요 시간을 기록해 전달해 달라.

**쓰기는 [G]에서만 일어난다.** `populate`는 한 트랜잭션으로 적재하고(중간 실패 시 롤백), 같은 입력으로
다시 돌리면 두 번째는 전부 `unchanged`다(멱등 — 샌드박스 PG 16에서 실측). 행을 **삭제하지 않는다**:
이번 실행에서 더는 만들어지지 않는 기존 힌트는 `verified=false`로 내려가고 `gate_report.retired`에 사유가
남는다.

**`updated`가 행 수 전체에 가까운 것은 정상이다.** 새 판정은 모든 행의 `gate_report`에 값 축 표지
(`value_verdict`)를 새로 붙이므로, 검수 상태가 안 바뀌는 행도 내용이 바뀐 것으로 센다. 검수 상태가 바뀐 행은
`updated`가 아니라 **전후 검수 분포의 차**로 읽는다. 부수 효과로 거의 모든 행의 `updated_at`이 오늘 시각이
된다.

## 4. 성공 기준

[H]가 `WRITE_OK=True`를 내고 [I]가 `SERVE_EXIT=0`·`SCAN_EXIT=0`이면 성공이다. `WRITE_OK=True`는 아래를
**전부** 재검사한 결과다.

| 항목 | 뜻 |
|---|---|
| `APPLY_EXIT=0` · 적재 JSON 형식 정상 | 적재 CLI가 끝났고 리포트가 읽힌다 |
| `RUN_CMS_CONFLICTS=0` | CMS로 고친 행이 하나도 건너뛰어지지 않았다 |
| 레벨별 `AFTER 검수 수 == dry-run 검수 수 + 이월 행 수` | 적재 결과가 [D]의 예측과 일치한다 |
| 검수 통과 행의 값 축 표지 없음 ≤ 이월 행 수 | 종전(P3-77 이전) 판정 행이 처리 대상에서 남지 않았다 |

[I]의 `SERVE_LEAK_EXPOSED=0`·`SCAN_LEAK_EXPOSED=0`이 acceptance ③(정답 누설 L3 없음)의 증거다. 두 프로브는
**종전 판정 행이 실제로 남은 상태에서 RED(exit 1)를 내는 것을 확인했다**(§9) — 0건이 "판정을 안 해서"가
아니다. 판정한 건수(`*_JUDGED`)가 0이면 exit 2(측정 실패)이며 통과로 읽지 않는다.

### 추정치와 어떻게 대조하는가

P3-77 판정문(`docs/reviews/p3_77_hint_l3_gap_pedagogy_judgment_2026-10-22.md` §3.1, 판정 기준 main
`5d1ef801`)의 추정은 **승인 1,772문항, L3 슬롯 3,600개** 기준이다.

| 항목 | 재적재 전 | 재적재 후(추정) |
|---|---|---|
| 승인 문항의 검수 L3 | 3,461 | **2,734** |
| 검수 L3가 0건인 승인 문항 | 45 | **396** |

태스크 acceptance ①의 문면에는 **2,845**와 **324**가 적혀 있다. 3,461 − 2,845 = 616 이고 3,461 − 2,734 =
727 인데, 그 차 111건은 판정문 §2.1 이력이 적은 "PR 재리뷰에서 새로 거부된 검수 L3 111건"과 정확히
같다. 그래서 문면의 수는 **그 재리뷰 이전(PR 첫 판) 추정**으로 읽는다. 판정문이 문면 수를 초판이라고 명시한
것은 아니므로 이것은 **추론**이다 — 이 런북은 두 수를 모두 출력해 나란히 보여 준다.

추정은 "모든 단계 검증됨·개념 있음"을 가정한 코퍼스 기준 계산이고, 이 런북이 재는 것은 **운영 DB의 실제
행**이다. 두 수는 같은 모집단이 아닐 수 있으므로 **일치 여부가 합격 기준이 아니다**(합격 기준은 위 표의
구조적 재검사다). 읽는 법은 다음과 같다.

| 관측 | 해석 | 다음 행동 |
|---|---|---|
| `APPROVED_ROWS_L3`가 3,600과 크게 다르다 | 모집단이 다르다(DB에 없는 문항·미실체화 경로·`sympy_verified` 미통과) | 절대 수가 아니라 **변화량**과 비율로 읽는다. 값 전달만 하고 판정은 세션에 넘긴다 |
| 변화량(검수 L3 감소)이 추정(−727)보다 훨씬 작고 `RUN_VALUE_EXPOSED`가 0 | **값 축이 안 돌았을 의심** | 합격 판정하지 않는다. `RUN_VALUE_NOT_RUN`·`RUN_VALUE_ACCOUNTED`와 `CODE_*` 경로를 함께 전달 |
| 변화량이 추정보다 크다 | 그 사이 경로가 늘었거나 판정이 더 엄격한 입력이 있다 | 합격 여부와 무관하게 값만 전달 |
| 재적재 후 L3 0건 문항이 추정(396)과 다르다 | 같은 이유 | 값만 전달 |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (블록이 스스로 `cd`한다)
- **선행 조건**: ① 이 PR이 main에 병합됨 ② Docker Desktop 실행 가능, `whymath-pg`(호스트 포트 **5433**)
  ③ `src\backend\.venv`(Python 가상환경)가 이미 세팅돼 있음 ④ 디스크 여유(임시 worktree + 백업 파일)
- **DB**: prod = docker `whymath-pg`(5433, trust, user/db=`whymath`). 데모용 55432·타 프로젝트 5432와
  혼동 금지.
- **코드 출처**: 공유 작업 사본(`C:\Users\kiki\Desktop\__AI\WhyMath`)의 브랜치·미커밋 변경과 **무관하게**,
  main의 사본(임시 worktree `WhyMath_wt_<main 해시>`)에서 실행한다. 클론의 체크아웃을 옮기지 않는다.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유되는 창이 없다. 블록 사이에
**같은 창을 유지**해야 한다 — 뒤 블록이 앞 블록의 변수(`$Wt`·`$Py`·`$DryOk` 등)를 읽는다. 창을 닫았거나
변수가 없으면 쓰기 블록은 **스스로 거부**한다(`WRITE_REFUSED=True`).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에 넘어간다.
> 단 쓰기 블록 [G]는 눈 확인에 기대지 않고 **선행 판정을 스스로 다시 검사해 거부**한다 — 출력은 흐름을
> 멈추지 못한다(2026-09-15 실측). [F]는 한 줄짜리 블록이며 **혼자** 붙여넣는다.

### [A] Docker 기동 + prod DB 컨테이너 확인

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 · A Docker 기동 (읽기 전용)
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
$Probe1 = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe1)
```

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `Up …` + `0.0.0.0:5433->5432/tcp`. `False`면 멈추고 출력 전체를
전달한다(이후 블록은 전부 거부되거나 실패한다).

### [B] main 기준 임시 worktree (공유 클론을 옮기지 않는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · B 임시 worktree (읽기 전용 · 클론 무변경)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$CloneHead = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath_wt_$MainSha"
if (Test-Path $Wt) { "WT_EXISTS=True · 이미 있는 폴더를 재사용합니다" } else { git worktree add --detach $Wt origin/main }
$WtHead = (git -C $Wt rev-parse --short HEAD)
git -C $Wt diff --quiet origin/main -- "src/backend/whymath_backend" "scripts/ops" "data/corpus"
$WtClean = ($LASTEXITCODE -eq 0)
$HasProbe = (Test-Path "$Wt\scripts\ops\p3_81_hint_catalog_probe.py")
$HasValueAxis = ((Get-Content "$Wt\src\backend\whymath_backend\l4\hint_content\populate.py" -Raw) -match "default_answer_value_exposure")
$WtOk = ($WtHead -eq $MainSha) -and $WtClean -and $HasProbe -and $HasValueAxis
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · PROBE_IN_WT=$HasProbe · VALUE_AXIS_IN_WT=$HasValueAxis · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

**확인**: `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True`.

- `PROBE_IN_WT=False`면 이 PR이 아직 main에 없다 — 병합 후 다시 시작한다.
- `VALUE_AXIS_IN_WT=False`면 main의 `populate.py`에 P3-77 값 축 배선이 없다는 뜻이다(이 경우 재적재가
  오히려 종전 판정을 되풀이한다) — 멈추고 `MAIN_SHA`와 함께 전달한다.
- `WT_EXISTS=True`로 재사용한 폴더는 `WT_CLEAN=True`가 아니면 거부된다(이전 실행의 흔적 방어).

### [C] 환경 · 코드 출처 · DB 도달 · 적재 전 실측 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · C 환경 + BEFORE 실측 (읽기 전용)
cd $Wt
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = "$Wt\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Probe = "$Wt\scripts\ops\p3_81_hint_catalog_probe.py"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\work\p3_81_$MainSha"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
function Get-KvMap([string[]]$Lines) { $Map = @{}; foreach ($L in $Lines) { if ($L -match '^([A-Z0-9_]+)=(.*)$') { $Map[$Matches[1]] = $Matches[2].Trim() } }; return $Map }
function Get-KvInt($Map, [string]$Key) { $V = $Map[$Key]; if ($null -ne $V -and $V -match '^-?\d+$') { return [int]$V } else { return -1 } }
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$BeforeLines = & $Py $Probe stats
$StatsExit = $LASTEXITCODE
$BeforeLines
"STATS_EXIT=$StatsExit"
$BeforeMap = Get-KvMap $BeforeLines
if ($BeforeLines) { [IO.File]::WriteAllLines("$OutDir\before.kv", [string[]]$BeforeLines); "EVIDENCE_SAVED=$OutDir\before.kv" } else { "EVIDENCE_NOT_SAVED=True — 프로브 출력이 비었습니다" }
$CodeOk = ([bool]$BeforeMap["CODE_POPULATE"]) -and ($BeforeMap["CODE_POPULATE"] -like "$Wt\*") -and ($BeforeMap["CODE_STORE"] -like "$Wt\*") -and ($BeforeMap["CODE_PROBE"] -like "$Wt\*")
$BeforeOk = ($StatsExit -eq 0) -and ($BeforeMap["HINTS_TABLE"] -eq "True") -and ($BeforeMap["HINTS_CMS_COLUMN"] -eq "True") -and ($BeforeMap["DB_NAME"] -ceq "whymath") -and ((Get-KvInt $BeforeMap "HINTS_ROWS") -ge 0)
"CODE_OK=$CodeOk · BEFORE_OK=$BeforeOk · REACH_EXIT=$ReachExit"
```

**확인**: `PY_OK=True` · `REACH_EXIT=0` · `STATS_EXIT=0` · `CODE_OK=True` · `BEFORE_OK=True`. 그리고 출력된 `CODE_POPULATE`·
`CODE_STORE`·`CODE_PROBE` 세 경로가 모두 `…\WhyMath_wt_<main 해시>\…`로 시작해야 한다(공유 클론 경로면 틀린
코드가 돈 것이다).

| 값 | 실패 신호 | 대처 |
|---|---|---|
| `REACH_EXIT` | 1(도달 불가) 또는 2(측정 불가) | CLI가 출력하는 상태·대책을 따른다(`FOREIGN_LISTENER`면 5433을 다른 프로세스가 물고 있다 — 적재 금지, 출력 전달) |
| `HINTS_CMS_COLUMN=False` | prod 스키마에 `hints.cms_edited_at`(P3-25)이 없다 | 적재하지 않는다. 출력 전달 — 마이그레이션 선행이 필요하다 |
| `DB_NAME`이 `whymath`가 아님 | 엉뚱한 DB에 붙었다 | 적재하지 않는다 |
| `PROBE_ERROR=` 줄 | 프로브가 DB를 못 읽었다(원인 타입명 포함) | 그 줄을 그대로 전달 |

이 블록의 **BEFORE 수치 전체**(41줄 안팎)가 acceptance ②의 "재적재 전" 실측이다. 화면 전체를 복사해 전달한다.

### [D] 시험 실행 — dry-run (DB에 쓰지 않는다)

`populate`는 `--apply` 없이 돌리면 적재 없이 리포트만 낸다. 이 블록은 그 리포트로 **재적재 후의 검수 수를
미리 계산**한다. 리포트 JSON은 변수로 받아 UTF-8 파일에 그대로 저장한다. 이 JSON은 실질적으로 ASCII뿐이고
(키·판정값·`hint_id`), [C]가 콘솔 인코딩을 UTF-8로 맞추므로 PowerShell 5.1의 cp949 디코딩 왕복으로 구조
문자가 손상되지 않는다. 그래도 저장 후 `run-summary`가 JSON을 다시 읽어 **형식을 검사**한다(`RUN_WELLFORMED`) —
손상되면 그 자리에서 드러난다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · D dry-run (쓰기 없음 · 조건 미충족이면 스스로 거부)
cd $Wt
$DryJson = "$OutDir\dry.json"
$DryReady = $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0)
"DRY_READY=$DryReady · WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
if ($DryReady) { $DryOut = & $Py -m whymath_backend.l4.hint_content.populate; $DryExit = $LASTEXITCODE; "DRY_EXIT=$DryExit"; [IO.File]::WriteAllLines($DryJson, [string[]]@($DryOut)); "SAVED=$DryJson" } else { $DryExit = -1; "DRY_REFUSED=True — WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 실행합니다. [B]·[C]를 같은 창에서 먼저 실행하세요" }
$DryLines = & $Py $Probe run-summary --json $DryJson
$SumExit = $LASTEXITCODE
$DryLines
"RUN_SUMMARY_EXIT=$SumExit"
$DryMap = Get-KvMap $DryLines
$KnownAll = $true
foreach ($K in "RUN_VERIFIED_L1", "RUN_VERIFIED_L2", "RUN_VERIFIED_L3", "RUN_GENERATED") { if ((Get-KvInt $DryMap $K) -lt 0) { $KnownAll = $false } }
foreach ($K in "CARRY_VERIFIED_L1", "CARRY_VERIFIED_L2", "CARRY_VERIFIED_L3", "VERIFIED_L1", "VERIFIED_L2", "VERIFIED_L3") { if ((Get-KvInt $BeforeMap $K) -lt 0) { $KnownAll = $false } }
$DryOk = $DryReady -and ($DryExit -eq 0) -and ($SumExit -eq 0) -and $KnownAll -and ($DryMap["RUN_WELLFORMED"] -eq "True") -and ($DryMap["RUN_APPLIED"] -eq "False") -and ($DryMap["RUN_VALUE_ACCOUNTED"] -eq "True") -and ((Get-KvInt $DryMap "RUN_VALUE_NOT_RUN") -eq 0) -and ((Get-KvInt $DryMap "RUN_GENERATED") -gt 0)
"DRY_OK=$DryOk"
$ExpectL1 = (Get-KvInt $DryMap "RUN_VERIFIED_L1") + (Get-KvInt $BeforeMap "CARRY_VERIFIED_L1")
$ExpectL2 = (Get-KvInt $DryMap "RUN_VERIFIED_L2") + (Get-KvInt $BeforeMap "CARRY_VERIFIED_L2")
$ExpectL3 = (Get-KvInt $DryMap "RUN_VERIFIED_L3") + (Get-KvInt $BeforeMap "CARRY_VERIFIED_L3")
"PREDICT_VERIFIED_L1=" + $BeforeMap["VERIFIED_L1"] + " -> " + $ExpectL1
"PREDICT_VERIFIED_L2=" + $BeforeMap["VERIFIED_L2"] + " -> " + $ExpectL2
"PREDICT_VERIFIED_L3=" + $BeforeMap["VERIFIED_L3"] + " -> " + $ExpectL3
```

**확인**: `DRY_EXIT=0` · `RUN_SUMMARY_EXIT=0` · **`DRY_OK=True`**. 그리고 `RUN_VALUE_NOT_RUN=0`(값 축 능력이
주입돼 실제로 돌았다) · `RUN_VALUE_ACCOUNTED=True`(생성된 모든 힌트가 값 축 판정을 받았다).

`PREDICT_VERIFIED_Lk` 줄이 "이 dry-run대로 적재하면 검수 통과가 현재 → 이 수가 된다"는 예측이다. **L3 숫자가
줄어드는 것이 의도된 변화다**(정답 누설 L3가 내려간다). `RUN_VALUE_EXPOSED`는 값 축이 거부한 힌트 수다 —
0이면 §4의 "값 축이 안 돌았을 의심" 행을 본다.

| 증상 | 뜻 | 대처 |
|---|---|---|
| `DRY_REFUSED=True` | 선행 판정 하나가 False | 같은 줄에 찍힌 값을 보고 [B]·[C]를 같은 창에서 다시 |
| `DRY_EXIT=1` | 원천 경로가 0건(`whs.path_promotion --apply` 선행 필요) — 화면에 "원천 경로 0건" 안내가 찍힌다 | 적재하지 않는다. 화면 출력을 전달 |
| `RUN_VALUE_NOT_RUN`이 0이 아님 | 값 축 능력이 주입되지 않았다 — 모든 힌트가 거부되는 상태 | 적재하지 않는다(전량 미검수가 된다). 출력 전달 |
| `RUN_PATHS_SKIPPED_*`가 0이 아님 | 일부 경로가 원천 결함으로 건너뛰어졌다(그 경로의 기존 행은 안 바뀐다) | 값만 전달. [H]의 대조에서 차이로 나타날 수 있다 |
| `RUN_SUMMARY_EXIT=2` | JSON이 없거나 깨졌다 | `dry.json` 존재 여부와 화면 출력을 전달 |

### [E] `hints` 표 백업 (되돌리기용 사본 · DB는 읽기만)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · E hints 표 백업 (DB 읽기 전용 · 파일 생성)
cd $Wt
$BackupFile = "$OutDir\hints_before.dump"
$BackupReady = $DryOk -and ($Wt -notmatch '\s')
"BACKUP_READY=$BackupReady · DRY_OK=$DryOk"
if ($BackupReady) { docker exec whymath-pg pg_dump -U whymath -d whymath -t hints -Fc -f /tmp/p3_81_hints_before.dump; $DumpExit = $LASTEXITCODE; docker cp whymath-pg:/tmp/p3_81_hints_before.dump $BackupFile; $CopyExit = $LASTEXITCODE; "DUMP_EXIT=$DumpExit · COPY_EXIT=$CopyExit" } else { $DumpExit = -1; $CopyExit = -1; "BACKUP_REFUSED=True — DRY_OK=$DryOk · [D]가 DRY_OK=True여야 백업합니다" }
$BackupBytes = 0
if (Test-Path $BackupFile) { $BackupBytes = (Get-Item $BackupFile).Length }
docker exec whymath-pg pg_restore -l /tmp/p3_81_hints_before.dump *> $null
$ListExit = $LASTEXITCODE
$BackupOk = $BackupReady -and ($DumpExit -eq 0) -and ($CopyExit -eq 0) -and ($BackupBytes -gt 0) -and ($ListExit -eq 0)
"BACKUP_BYTES=$BackupBytes · RESTORE_LIST_EXIT=$ListExit · BACKUP_OK=$BackupOk"
```

**확인**: `DUMP_EXIT=0` · `COPY_EXIT=0` · `BACKUP_BYTES`가 0보다 큼 · `RESTORE_LIST_EXIT=0` · `BACKUP_OK=True`.
`BACKUP_OK`는 [G]의 가드가 다시 읽는다 — `False`면 적재가 거부된다.

이 백업은 **복원 명령을 이 문서가 검증하지 않았다**(§9). 파일이 생겼고 `pg_restore -l`이 목차를 읽는다는
것까지만 확인한다. 백업은 안전망일 뿐 재적재 자체는 멱등이며, 새 판정은 코드로 언제든 다시 만든다.

### [F] 적재 확인 입력 (한 줄 블록 — 이 줄만 붙여넣는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · F 적재 확인 입력 (이 블록만 혼자 붙여넣는다)
$Confirm = Read-Host "dry-run 예측(PREDICT_VERIFIED_L3 등)을 확인했다면 대문자 APPLY 를 입력하고 Enter"
```

**이 블록은 위아래 어떤 줄과도 같이 붙여넣지 않는다.** 입력 대기 중에 뒤따라 붙여넣은 줄이 입력으로 먹히는
것을 막기 위해서다. `APPLY` 외의 입력이면 [G]가 거부한다.

### [G] 적재 (여기서만 DB에 쓴다)

이 블록은 **[D]·[E]·[F]의 판정값을 스스로 다시 검사하고, 하나라도 미충족이면 실행을 거부한다.** 눈 확인
안내에 기대지 않는다 — 변수가 없거나(창을 바꿈) `False`면 `null`/`False`로 평가돼 거부 가지로 간다.
`--overwrite-cms-edits`는 **쓰지 않는다**: CMS로 고친 행은 건너뛰고 충돌로 보고만 한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · G 적재 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$ApplyJson = "$OutDir\apply.json"
$ConfirmOk = ($Confirm -ceq "APPLY")
$ApplyReady = $DryOk -and $BackupOk -and $ConfirmOk -and $WtOk -and $CodeOk -and $BeforeOk -and ($ReachExit -eq 0)
"APPLY_READY=$ApplyReady · DRY_OK=$DryOk BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit"
if ($ApplyReady) { $ApplyOut = & $Py -m whymath_backend.l4.hint_content.populate --apply; $ApplyExit = $LASTEXITCODE; "APPLY_EXIT=$ApplyExit"; [IO.File]::WriteAllLines($ApplyJson, [string[]]@($ApplyOut)); "SAVED=$ApplyJson" } else { $ApplyExit = -1; "WRITE_REFUSED=True — DRY_OK=$DryOk BACKUP_OK=$BackupOk CONFIRMED=$ConfirmOk WT_OK=$WtOk CODE_OK=$CodeOk BEFORE_OK=$BeforeOk REACH_EXIT=$ReachExit · 전부 True/0이어야 적재합니다. [B]~[F]를 같은 창에서 순서대로 실행하세요" }
```

**확인**: `APPLY_READY=True` → `APPLY_EXIT=0`.

`WRITE_REFUSED=True`가 나오면 적재는 **일어나지 않았다.** 같은 줄에 무엇이 `False`였는지 찍힌다. 닫는 중괄호와
**같은 줄**의 `} else {`가 중요하다 — 새 줄에서 시작하는 `else`는 대화형 프롬프트에서 별개 명령으로 해석돼
그 가지가 통째로 미실행된다(2026-09-14 실측).

`APPLY_EXIT=1`이면 적재 CLI가 원천 0건으로 끝난 것이다(dry-run과 같은 증상). 쓰기는 일어나지 않았다.
`APPLY_EXIT`가 그 밖의 값이면 예외로 중단된 것이며, **한 트랜잭션이라 부분 적재는 없다**(commit 전 예외는
롤백). 화면에 찍힌 예외 줄을 그대로 전달한다.

### [H] 적재 후 실측 · 전후 대조 · 예측 대조 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · H AFTER 실측 + 전후 대조 (읽기 전용)
cd $Wt
$ApplyLines = & $Py $Probe run-summary --json $ApplyJson
$ApplySumExit = $LASTEXITCODE
$ApplyLines
"APPLY_SUMMARY_EXIT=$ApplySumExit"
$ApplyMap = Get-KvMap $ApplyLines
$AfterLines = & $Py $Probe stats
$AfterStatsExit = $LASTEXITCODE
$AfterLines
"AFTER_STATS_EXIT=$AfterStatsExit"
$AfterMap = Get-KvMap $AfterLines
if ($AfterLines) { [IO.File]::WriteAllLines("$OutDir\after.kv", [string[]]$AfterLines); "EVIDENCE_SAVED=$OutDir\after.kv" } else { "EVIDENCE_NOT_SAVED=True — 프로브 출력이 비었습니다" }
$CarryTotal = (Get-KvInt $BeforeMap "CARRY_VERIFIED_L1") + (Get-KvInt $BeforeMap "CARRY_VERIFIED_L2") + (Get-KvInt $BeforeMap "CARRY_VERIFIED_L3")
$StaleLeft = (Get-KvInt $AfterMap "VALUE_VERDICT_VERIFIED_NONE")
$MatchL1 = ((Get-KvInt $AfterMap "VERIFIED_L1") -eq $ExpectL1) -and ($ExpectL1 -ge 0)
$MatchL2 = ((Get-KvInt $AfterMap "VERIFIED_L2") -eq $ExpectL2) -and ($ExpectL2 -ge 0)
$MatchL3 = ((Get-KvInt $AfterMap "VERIFIED_L3") -eq $ExpectL3) -and ($ExpectL3 -ge 0)
$StaleOk = ($StaleLeft -ge 0) -and ($StaleLeft -le $CarryTotal)
$WriteOk = ($ApplyExit -eq 0) -and ($ApplySumExit -eq 0) -and ($AfterStatsExit -eq 0) -and ($ApplyMap["RUN_WELLFORMED"] -eq "True") -and ($ApplyMap["RUN_APPLIED"] -eq "True") -and ((Get-KvInt $ApplyMap "RUN_CMS_CONFLICTS") -eq 0) -and $MatchL1 -and $MatchL2 -and $MatchL3 -and $StaleOk
"MATCH_PREDICT_L1=$MatchL1 · MATCH_PREDICT_L2=$MatchL2 · MATCH_PREDICT_L3=$MatchL3 · STALE_MARKER_OK=$StaleOk (검수 통과 행 중 값 축 표지 없음=$StaleLeft, 이월 행=$CarryTotal)"
"WRITE_OK=$WriteOk"
"BEFORE_AFTER hints 행 수: " + $BeforeMap["HINTS_ROWS"] + " -> " + $AfterMap["HINTS_ROWS"]
"BEFORE_AFTER 검수 통과 L1/L2/L3: " + $BeforeMap["VERIFIED_L1"] + "/" + $BeforeMap["VERIFIED_L2"] + "/" + $BeforeMap["VERIFIED_L3"] + " -> " + $AfterMap["VERIFIED_L1"] + "/" + $AfterMap["VERIFIED_L2"] + "/" + $AfterMap["VERIFIED_L3"]
"BEFORE_AFTER 승인 문항 검수 L3: " + $BeforeMap["APPROVED_VERIFIED_L3"] + " -> " + $AfterMap["APPROVED_VERIFIED_L3"] + " (승인 문항 L3 슬롯 " + $AfterMap["APPROVED_ROWS_L3"] + ")"
"BEFORE_AFTER 승인 문항 중 검수 L3 0건: " + $BeforeMap["APPROVED_PROBLEMS_NO_VERIFIED_L3"] + " -> " + $AfterMap["APPROVED_PROBLEMS_NO_VERIFIED_L3"] + " (승인 문항 " + $AfterMap["APPROVED_PROBLEMS_WITH_HINTS"] + ")"
"ESTIMATE P3-77 판정문 3.1 최종판(승인 1772문항): 검수 L3 3461 -> 2734 · L3 0건 문항 45 -> 396"
"ESTIMATE 태스크 acceptance 1 문면(초판 추정으로 읽음): 검수 L3 3461 -> 2845 · L3 0건 문항 45 -> 324"
"JUDGED_AGAINST_MAIN=$MainSha"
```

**확인**: **`WRITE_OK=True`**. 이 값은 §4 표의 네 항목을 전부 재검사한 결과다. `False`면 같은 화면의
`MATCH_PREDICT_Lk`·`STALE_MARKER_OK`·`RUN_CMS_CONFLICTS`가 무엇이 어긋났는지 말한다.

| 증상 | 뜻 | 대처 |
|---|---|---|
| `RUN_CMS_CONFLICTS`가 0이 아님 | CMS로 고친 힌트가 덮어쓰기에서 건너뛰어졌다 — **그 행이 종전 판정(누설 L3 포함)으로 남았을 수 있다** | `--overwrite-cms-edits`로 덮어쓰면 사람의 편집이 사라진다. Kiki가 정할 일이다 — 충돌 `hint_id` 목록(`apply.json`)을 세션에 전달하고, [I]의 `SCAN_LEAK_EXPOSED`가 그 행을 잡는지 본다 |
| `MATCH_PREDICT_Lk=False` | 적재 결과가 dry-run 예측과 다르다 | 값 그대로 전달(원인 후보: 건너뛴 경로·CMS 충돌·dry-run과 적재 사이 DB 변경) |
| `STALE_MARKER_OK=False` | 값 축 표지 없는 검수 통과 행이 이월 행보다 많다 — 종전 판정 행이 처리되지 않았다 | 적재 완료로 말하지 않는다. 출력 전체 전달 |
| `WRITE_OK=True`인데 변화량이 추정과 매우 다름 | §4 "추정치와 어떻게 대조하는가" 표 | 값 전달만 |

이 블록의 **전후 수치 전체**가 acceptance ②의 증거다. 화면 전체를 복사해 전달한다.

### [I] 서빙 경로 표본 · 카탈로그 정답 누설 판정 (읽기 전용)

두 프로브는 P3-10 `ai_quality_eval`의 정답 누설 축(`judge_case("answer_leak")` — 정답 문자열·선언 어구·값 동치
산술식·최종 풀이 단계)을 **같은 판정기로** 힌트 본문에 부른다. `serve-sample`은 서빙 reader
(`store.find_served_hint`)를 실제로 불러 문항 표본 × 단계 × 레벨(1~3)의 결과를 판정하고, 앞 단계 L3 대체·
L2 하향이 몇 번 일어났는지도 센다. `catalog-scan`은 검수 통과 L3 행 **전수**를 판정한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · I 서빙 표본 + 카탈로그 전수 (읽기 전용)
cd $Wt
$ServeLines = & $Py $Probe serve-sample --problems 300
$ServeExit = $LASTEXITCODE
$ServeLines
"SERVE_EXIT=$ServeExit"
$ScanLines = & $Py $Probe catalog-scan --levels 3
$ScanExit = $LASTEXITCODE
$ScanLines
"SCAN_EXIT=$ScanExit"
if ($ServeLines) { [IO.File]::WriteAllLines("$OutDir\serve.kv", [string[]]$ServeLines) }
if ($ScanLines) { [IO.File]::WriteAllLines("$OutDir\scan.kv", [string[]]$ScanLines) }
"LEAK_CHECK_OK=" + (($ServeExit -eq 0) -and ($ScanExit -eq 0))
```

**확인**: `SERVE_EXIT=0` · `SCAN_EXIT=0` · `LEAK_CHECK_OK=True`.

- exit `1` = 정답 누설 판정 행이 있다. `*_LEAK_HINT=` 줄(최대 10개)의 `hint_id`와 사유를 전달한다. 가능한 원인:
  CMS 충돌로 건너뛴 행([H] 표), 또는 판정기가 개념 이름 속 식을 정답으로 본 오탐 — 게이트는 원천 개념 이름을
  지우고 판정하지만 P3-10 판정기는 지우지 않는다. 어느 쪽인지는 `hint_id`를 보고 세션이 가린다.
- exit `2` = 측정 실패(`PROBE_ERROR=` 줄). `*_JUDGED=0`이면 스캔 0건이므로 통과가 아니다.
- `SERVE_L3_DOWNGRADED_TO_L2`·`SERVE_L3_FROM_EARLIER_STEP`는 L3 공백 사다리(P3-77 판정문 §3)가 서빙에서
  실제로 작동한 횟수다. 둘 다 0이면 L3 공백이 이 DB에는 없다는 뜻일 수 있다(오류가 아니다).
- `SERVE_VALUE_UNDECIDABLE`·`SCAN_VALUE_UNDECIDABLE`은 판정기가 값 동치를 판정하지 못한 건수다(측정기라
  실패로 세지 않고 회계에만 남긴다). 게이트는 판정 불가를 거부하므로 검수 통과 행에서는 0이 정상이다.

### [J] 임시 worktree 정리 (저장소 밖 폴더만 지운다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · J 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
$WtIsTemp = [bool]$Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*")
if ($WtIsTemp) { git worktree remove --force $Wt; "WT_REMOVED=" + (-not (Test-Path $Wt)) } else { "REMOVE_REFUSED=True · WT=$Wt 은 임시 worktree 경로가 아닙니다" }
git worktree prune
"CLONE_HEAD=" + (git rev-parse --short HEAD)
"EVIDENCE_DIR=$OutDir · 파일: " + ((Get-ChildItem $OutDir | ForEach-Object { $_.Name }) -join ", ")
```

**확인**: `WT_REMOVED=True`. 증거 파일(`before.kv`·`dry.json`·`hints_before.dump`·`apply.json`·`after.kv`·
`serve.kv`·`scan.kv`)은 `work\p3_81_<main 해시>\`에 남는다(gitignore 대상 — 저장소에 들어가지 않는다).

---

## 7. 전달할 값

Kiki가 할 일은 아래 값을 세션에 전달하는 것까지다. 태스크 닫기(`backlog.py done`)는 세션이 가져간다 —
증적에는 판정 기준 커밋 해시(`MAIN_SHA`)가 들어가야 한다.

| 단계 | 전달할 줄 |
|---|---|
| B | `MAIN_SHA=…` 줄 전체 |
| C | `CODE_POPULATE=`·`CODE_STORE=`·`CODE_PROBE=` · `REACH_EXIT` · BEFORE 수치 전체 · `CODE_OK`·`BEFORE_OK` |
| D | `DRY_EXIT`·`DRY_OK`·`RUN_*` 전체 · `PREDICT_VERIFIED_L1~L3` · 소요 시간 |
| E | `BACKUP_BYTES`·`BACKUP_OK` |
| G | `APPLY_READY`·`APPLY_EXIT` (거부되면 `WRITE_REFUSED` 줄 전체) |
| H | 적재 JSON 요약(`RUN_*`) · AFTER 수치 전체 · `MATCH_PREDICT_*`·`STALE_MARKER_OK`·`WRITE_OK` · `BEFORE_AFTER`·`ESTIMATE` 줄 |
| I | `SERVE_*`·`SCAN_*` 전체 · `SERVE_EXIT`·`SCAN_EXIT`·`LEAK_CHECK_OK` |
| J | `WT_REMOVED` · `CLONE_HEAD` |

## 8. 이 런북이 닫는 것과 닫지 못하는 것

| P3-81 acceptance | 이 런북이 하는 일 | 닫히는 시점 |
|---|---|---|
| ① 종전 판정 L3가 서빙될 수 있다는 현상 | 재적재 절차(G)와 그 전제 검사 | **Kiki가 [G]를 실행하고 `WRITE_OK=True`가 나온 뒤** |
| ② 재적재 전후 실측 + 추정 대조 + 런북 안전장치 | 전후 실측 도구(프로브)와 대조 절차(C·H). 안전장치 3종: 쓰기 블록 자가거부 가드(D·E·G), 실행 코드 출처 확인(C — `import` 후 `__file__`), 공유 작업 사본 우회(B — `worktree --detach`) | 안전장치는 **이 PR로 이행**. 실측 수치는 **Kiki 실행 후** |
| ③ 서빙 경로가 정답 누설 L3를 내지 않는지 표본 확인 | 프로브 `serve-sample`·`catalog-scan`(I) | **Kiki 실행 후** |

즉 이 PR은 "실행할 수 있는 안전한 절차와 측정 도구"를 낸다. **acceptance ①·②의 실측 수치와 ③의 표본 결과는
Kiki 실행 결과가 있어야 닫힌다** — 태스크를 `done`으로 처리하지 않는다.

이 런북이 **답하지 못하는 것**:

- 재적재 후 실제 학생 세션에서 L3 공백 문항이 어떻게 느껴지는지(라이브 세션 지표 — P3-77 판정문 §5).
- `hints`가 아닌 다른 좌석(힌트 본문을 담은 다른 표)은 없다는 것을 전제한다(`hints` 단일 좌석 동결 테스트가
  지키는 사실이며 이 런북이 다시 재지 않는다).
- 승인 은행 코퍼스(`data/corpus/problem_bank_*`)와 운영 DB의 정합 — 이 절차의 입력은 DB의
  `problem_step`(단계가 실체화된 풀이 경로)이지 코퍼스 파일이 아니다. DB에 경로가 승격되지 않은 문항은 힌트가
  만들어지지 않는다(`whs.path_promotion` 소관).
- `--overwrite-cms-edits` 결정 — Kiki 판단 사항이다.

## 9. 실행 검증 범위 (정직 고지)

판정 기준: 샌드박스(리눅스) · PostgreSQL 16 · Python 3.12 · PowerShell 7.4.6(Windows PowerShell 5.1이 아님).

**실제로 돌려 본 것**

- `populate` 기본(dry-run)·`--apply`·`--help`: 합성 4경로(승인 문항 4개)를 PG 16에 넣고 실행했다. dry-run은 행을
  바꾸지 않았고(전후 `hints` 동일), `--apply`는 `updated=26`이었으며(합성 데이터에서 값 축 표지 없는 종전 판정
  흉내 행), 두 번째 `--apply`는 `unchanged=26`(멱등)이었다. CMS 편집 표지가 있는 행 1개를 만들자 `cms_edit_conflicts`에
  보고되고 건너뛰어졌다. `PYTHONPATH`는 `src/backend` 하나로 충분했다.
- 프로브 4개 서브커맨드: 같은 PG에서 실행. **종전 판정 상태에서 `catalog-scan`·`serve-sample`이 exit 1(RED)** 을
  냈고(합성 L3 `1 + (11 - 1)*3`이 정답 31과 같은 값), 재적재 후 exit 0(GREEN)이 됐다 — 판정기가 실패 상태에서
  실제로 실패 신호를 낸다. DB에 못 붙으면 exit 2, 힌트가 0건인 빈 DB는 `catalog-scan`·`serve-sample` 모두 exit 2다.
- 프로브가 쓰기를 못 하는 것: 모든 접속이 `SET TRANSACTION READ ONLY`라 DB가 거부한다(코드 규약이 아니라 DB가 막는다).
- 이 런북 PowerShell 블록 10개의 **문법 파싱**(오류 0)과 블록 [C]~[I]의 **실행**을 PowerShell 7.4.6(리눅스)에서
  샌드박스 PG 16 대상으로 확인했다. 임시 하네스(저장소에 넣지 않음)가 Windows 전용 부분만 **대역으로 바꿨다**:
  `$Py`를 리눅스 python으로, `docker`(`pg_dump`·`cp`·`pg_restore -l`)를 호스트 PG 16 바이너리로, `db_host_reachability`와
  `Read-Host`를 고정값으로, 경로 구분자를 `/`로. 그 결과 ① 정상 경로에서 C → D → E → F → G → H → I가 끝까지 돌았고
  (`DRY_OK=True` → `APPLY_EXIT=0` → `MATCH_PREDICT_L1~L3=True` → `WRITE_OK=True` → `LEAK_CHECK_OK=True`),
  종전 판정 상태에서는 dry-run이 예측한 검수 L3 감소(6 → 5)와 적재 결과가 일치했다 ② 쓰기 블록 [G]가 여섯 경우에
  `WRITE_REFUSED=True`로 **거부하고 DB를 바꾸지 않았다**: 확인 입력이 `apply`(소문자) · 앞 블록을 하나도 돌리지 않음(변수
  미정의) · `$DryOk=False` · 백업 블록 생략 · `$ReachExit=2` · `$CodeOk=False` ③ CMS 편집 행이 있으면 `RUN_CMS_CONFLICTS=1`이 되어
  `WRITE_OK=False`가 났다. [B]는 이 브랜치가 아직 main이 아니라서 실제로 `PROBE_IN_WT=False` · `WT_OK=False`로 거부됐다.
  계약 테스트 `tests/infra/test_p3_81_hint_repopulate_runbook.py`가 런북 구조를 동결한다.
- `git worktree add --detach` → `git worktree remove --force`의 왕복(임시 경로, 원 저장소 무변경).

**돌리지 못한 것 — 이 샌드박스에서는 실행 검증하지 못함**

- **Windows PowerShell 5.1 실행 전체.** 5.1에서의 `$LASTEXITCODE` 전파, 네이티브 명령 출력의 콘솔 인코딩 디코딩,
  `[IO.File]::WriteAllLines`의 기본 인코딩, `Start-Process`로 Docker Desktop을 띄우는 경로, Windows 경로 구분자.
  5.1과 7.x의 동작 차이는 검증하지 않았다. 하네스가 대역으로 바꾼 부분(위)은 대역이 맞았다는 가정에 기댄다.
- **Docker 기동(A)과 실제 `docker exec pg_dump`·`docker cp`·`pg_restore -l`(E).** 샌드박스에는 Docker 데몬이 없다.
  같은 `pg_dump -Fc -t hints`·`pg_restore -l` 플래그와 종료 코드·파일 크기 판정은 호스트 PG 16 바이너리로 확인했다
  (`BACKUP_BYTES=5.9KB` 규모의 합성 표). 컨테이너 안 `/tmp` 쓰기 권한은 가정이다. **백업 복원(`pg_restore`)은 돌려 보지
  않았다.**
- **`db_host_reachability`**: `--help`만 확인했다(Docker가 필요하다).
- **운영 DB.** 운영 규모의 소요 시간, 실제 행 수, 추정(3,461 → 2,734 등)과의 일치 여부는 미확인이다. 위 합성 수치는
  운영 수치가 아니다.
- **CI에서 도는 범위**: 프로브의 DB 경로(`stats`·`serve-sample`·`catalog-scan`)는 DB가 필요해 CI 계약 테스트가 돌리지
  못한다 — 위 PG 16 실측은 이 샌드박스 1회 증거일 뿐 회귀 방어가 아니다. CI는 런북 구조·프로브 키 계약·읽기 전용 소스
  계약·`run-summary` 순수 로직을 지킨다. PowerShell 문법 파싱 테스트는 `pwsh`가 있을 때만 돈다(CI 러너에는 없으면
  건너뜀).
- **HARN-106 스캐너의 인식 범위**: 스캐너는 이 런북의 쓰기 블록 2개([D]·[G])를 인식하고 통과시킨다. 다만 스캐너는
  문자열 안에 감싸인 실행(`cmd /c "…"`)을 못 보므로, 이 런북은 `populate`를 문자열 밖에서 부른다. 누가 그것을 문자열 안으로
  옮기면 스캐너는 조용해지고 계약 테스트의 `write_guards`가 대신 잡는다.

## 10. 실패 시 되돌리기

- **적재 전 중단**: 아무것도 쓰이지 않았다. [J]로 정리하고 처음부터 다시 한다.
- **적재 후 이상**: `hints`는 코드로 다시 만들 수 있는 파생물이다(같은 입력 → 같은 출력, 멱등). 이전 판정 행 자체가
  필요하면 [E]의 `hints_before.dump`가 있다. **복원 명령은 이 문서가 검증하지 않았다** — 복원이 필요하면 세션에
  알린다(`pg_restore --data-only` 계열이 될 것이며, 실행 전 세션이 명령을 검증해 다시 안내한다).
- 이 런북은 `hints` 외의 표를 쓰지 않는다. 로컬 파일 쓰기는 `work\p3_81_<main 해시>\`와 임시 worktree뿐이다.
