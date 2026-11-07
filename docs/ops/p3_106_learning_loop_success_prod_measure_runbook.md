# 런북 — P3-106 지표 ⑤ Learning Loop Success 운영 DB 실측 (Kiki PC · 읽기 전용)

> 태스크 `P3-106-phase3-learning-loop-success-prod-measure` · 작업 M1(P3 Release 재판정 준비).
> 측정 기록은 `docs/reviews/p3_106_learning_loop_success_measure_2026-11-06.md`에 남긴다.

## 0. 6항목 브리핑

1. **과제 명칭** — 지표 ⑤ Learning Loop Success(학습 루프 완주율)를 운영 DB에서 재기.
2. **목적** — Phase 3 Release 재판정(게이트 `G-p3-w3-release-merged`)과 새 Q1의 근거 KPI다.
   P3-17 판정은 이 지표를 DB 없이(`--no-db`) 돌려 "이 회차 미측정"으로 남겼고, 측정되지 않은 지표는
   PASS로 세지 않는다. 이번에 운영 DB `whymath-pg`의 실제 기록으로 값·분모·판정을 낸다.
3. **구체적 절차(약 3~5분)**
   - [A] 창A에서 main 최신본으로 별도 작업 폴더(워크트리 `WhyMath-p3r-m1`)를 만든다. 평소 클론의
     브랜치·미커밋 변경은 건드리지 않는다. 약 30초.
   - [B] 같은 창A에서 측정을 두 번 돈다 — 관측창 24시간(도구 기본값)과 전 기간(10년). DB 접속은
     **읽기 전용 세션**으로 열리고, 측정 전에 실제로 읽기 전용인지 스스로 확인한다(아니면 거부). 약 1~3분.
   - [C] 출력의 `P5_SUMMARY_24H=`·`P5_SUMMARY_ALL=` 두 줄(영문·기호만 있는 한 줄 JSON)과
     `MEASURE_BASE=` 줄을 복사해 이 세션 채팅에 붙여 넣는다. 그것이 결과 회신이다.
4. **성공 기준**
   - [A] 끝에 `READY_A=True`. False면 같은 줄에 무엇이 False인지 나온다.
   - [B] `READ_ONLY_24H=True`·`READ_ONLY_ALL=True`와 `P5_SUMMARY_24H=`·`P5_SUMMARY_ALL=` 두 줄이 나오면
     측정 자체는 성공이다. **⑤의 판정이 FAIL이거나 '측정 불가'여도 측정 성공이다** — 그 값이 이번 결과다.
   - 실패 시 대처: `RUN_REFUSED=True`가 나오면 아무것도 실행하지 않았다. 그 줄의 False 항목을 보고
     [A]를 다시 붙여넣는다. `EXIT_24H=3`이면 실행 오류다 — 로그 파일 경로(`LOG_24H=`)를 회신한다.
5. **실행 환경** — Phaiakes9의 Windows PowerShell. 작업 장소 `C:\Users\kiki\Desktop\__AI\WhyMath`.
   선행 조건: Docker Desktop 가동 + 컨테이너 `whymath-pg`(호스트 포트 5433) 실행 중. 서버(uvicorn)는
   켜져 있어도 꺼져 있어도 된다. 파이썬은 `C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe`.
6. **창 구분** — 새 PowerShell 창 하나(창A)만 쓴다. [A]·[B]는 같은 창A에 순서대로 붙여넣는다
   (창 변수 `$Wt`·`$Py`를 이어 쓴다). 서버를 점유하는 창이 아니므로 이후 조작해도 된다.

**쓰지 않는 것** — 운영 DB에 쓰지 않는다(접속 단계에서 `default_transaction_read_only=on`으로 연다 —
`scripts/ops/phase3_metrics_readonly.py`). 디스크에 쓰는 것은 워크트리 폴더와 그 안의 `out\` 결과
파일뿐이다. 백업 불필요.

## 1. 실행 블록

### [A] 준비 — 창A(새 창)

```powershell
# [Windows PowerShell · Phaiakes9 · 창A(새 창)] P3-106 [A] 워크트리 준비 — DB는 읽지도 쓰지도 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-p3r-m1"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
git cat-file -e origin/main:scripts/ops/phase3_metrics_readonly.py 2>$null
$RunnerOnMain = ($LASTEXITCODE -eq 0)
$WtExisted = Test-Path $Wt
if ($RunnerOnMain) { if ($WtExisted) { git -C $Wt checkout --detach origin/main } else { git worktree add --detach $Wt origin/main }; "WT_HEAD=$(git -C $Wt rev-parse --short HEAD) MAIN=$(git rev-parse --short origin/main)" } else { "WORKTREE_REFUSED=True — RunnerOnMain=$RunnerOnMain(False면 실행기가 아직 main에 없다 — 세션에 회신)" }
$PgPorts = docker ps --filter "name=^whymath-pg$" --format "{{.Ports}}"
$PgUp = [bool]("$PgPorts" -match "5433")
$HeadIsMain = ((git -C $Wt rev-parse HEAD) -eq (git rev-parse origin/main))
"PY_PRESENT=$(Test-Path $Py) WT_PRESENT=$(Test-Path $Wt) HEAD_IS_MAIN=$HeadIsMain PG_UP=$PgUp PG_PORTS=$PgPorts"
"READY_A=$((Test-Path $Py) -and (Test-Path $Wt) -and $HeadIsMain -and $PgUp)"
```

> 변별력: `PG_UP`은 Docker가 꺼져 있거나 컨테이너 이름이 다르면 False다. `HEAD_IS_MAIN`은 워크트리가
> 옛 커밋에 머물면 False다. `READY_A=False`면 [B]가 스스로 거부한다(아래 가드가 같은 값을 다시 계산한다).

### [B] 측정 — 같은 창A

`READY_A=True`를 눈으로 확인한 다음 붙여넣는다(확인하지 않아도 [B]가 스스로 다시 검사해 거부한다).

```powershell
# [Windows PowerShell · Phaiakes9 · 창A] P3-106 [B] ⑤ 측정 — 운영 DB 읽기 전용 접속 · 결과는 워크트리 out\ 에만 쓴다
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"
$env:PYTHONPATH = "$Wt\src\backend"
$CodeFile = & $Py -c "import whymath_backend.ops.phase3_metrics as m; print(m.__file__)"
$CodeFromWt = [bool]("$CodeFile" -like "$Wt\*")
$PgUpB = [bool]("$(docker ps --filter "name=^whymath-pg$" --format "{{.Ports}}")" -match "5433")
$HeadIsMainB = ((git -C $Wt rev-parse HEAD) -eq (git rev-parse origin/main))
$Out = "$Wt\out"
if ($CodeFromWt -and $PgUpB -and $HeadIsMainB) { New-Item -ItemType Directory -Force -Path $Out | Out-Null; cmd /c "$Py $Wt\scripts\ops\phase3_metrics_readonly.py --json $Out\p3_106_24h.json > $Out\p3_106_24h.log 2>&1"; "EXIT_24H=$LASTEXITCODE LOG_24H=$Out\p3_106_24h.log"; cmd /c "$Py $Wt\scripts\ops\phase3_metrics_readonly.py --since-hours 87600 --json $Out\p3_106_all.json > $Out\p3_106_all.log 2>&1"; "EXIT_ALL=$LASTEXITCODE LOG_ALL=$Out\p3_106_all.log" } else { "RUN_REFUSED=True — 측정하지 않았다. CODE_FROM_WT=$CodeFromWt(False면 워크트리 코드가 import되지 않았다: $CodeFile) PG_UP=$PgUpB(False면 Docker·whymath-pg 확인) HEAD_IS_MAIN=$HeadIsMainB(False면 [A]부터)" }
"READ_ONLY_24H=$([bool](Select-String -Path $Out\p3_106_24h.log -Pattern '^READ_ONLY=True' -Quiet)) READ_ONLY_ALL=$([bool](Select-String -Path $Out\p3_106_all.log -Pattern '^READ_ONLY=True' -Quiet))"
"MEASURE_BASE=$(git -C $Wt rev-parse --short HEAD) CODE_FILE=$CodeFile"
"P5_SUMMARY_24H=$((Select-String -Path $Out\p3_106_24h.log -Pattern '^P5_SUMMARY=').Line)"
"P5_SUMMARY_ALL=$((Select-String -Path $Out\p3_106_all.log -Pattern '^P5_SUMMARY=').Line)"
```

> 왜 `cmd /c … > 파일`인가: PowerShell 5.1이 파이썬 출력을 cp949로 디코딩·재인코딩하면 한국어 표가
> 깨진다(CLAUDE.md 인코딩 규칙 — 셸 중계 축). 바이트를 파일로 바로 보내고, 회신 줄(`P5_SUMMARY=`)은
> 실행기가 **ASCII 한 줄**로 내므로 콘솔을 거쳐도 손상되지 않는다.
>
> 변별력: `CODE_FROM_WT`는 `PYTHONPATH`가 먹지 않으면 평소 클론 경로가 찍혀 False가 된다.
> `READ_ONLY_*`는 실행기가 접속을 읽기 전용으로 열지 못하면 `READ_ONLY=False`를 내고 exit 3으로 거부하므로
> False가 된다(주입 실측: `tests/backend/ops/test_phase3_metrics_readonly.py`).

### [C] 회신

[B] 출력의 마지막 네 줄(`MEASURE_BASE=`·`P5_SUMMARY_24H=`·`P5_SUMMARY_ALL=`·`READ_ONLY_…`)과
`EXIT_24H=`·`EXIT_ALL=` 줄을 복사해 이 세션 채팅에 붙여 넣는다. 결과 JSON 원본은
`C:\Users\kiki\Desktop\__AI\WhyMath-p3r-m1\out\`에 남는다(세션이 더 필요하면 그때 요청한다).

## 2. 결과 읽는 법

- `state`가 `unmeasured`이고 `denominator`가 0 → **측정 실패 — 루프 표본 부재.** 관측창 안에 "시도가 1건
  이상 있는 학습 세션"이 하나도 없다. 0을 통과로 접지 않는다.
- `state`가 `measured`이고 `met`가 false → FAIL. 판정은 점추정이 아니라 Wilson 하한(신뢰도 0.95) ≥ 0.95다.
  그래서 **전부 성공해도 세션이 52개 미만이면 FAIL**이다(1건 실패 허용 시 87개 · 2건 118개).
- `state`가 `measured`이고 `met`가 true → PASS.
- 24시간 창과 전 기간이 다르면 둘 다 기록한다. 재판정 공식값은 판정 회차가 정한 관측창이다
  (이 런북은 둘 다 잰다 — 0건이 "창 밖"인지 "아예 없음"인지 가르기 위해).
