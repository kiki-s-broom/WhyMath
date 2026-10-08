# OPS-19 관측 리포트 실행 런북

> 대상: Kiki (Phaiakes9 = 작업 PC). 이 문서는 **자동 실행이 닿지 못하는 두 부류**를 사람이 돌리는 방법과, 자동 실행 결과를 읽는 방법을 적는다.

## 0. 사전 브리핑 (6항목)

1. **과제 명칭**: 관측 리포트 일괄 실행 (Phaiakes9 개발 DB 대상)
2. **목적**: 관측 리포트 20개 중 17개는 지금까지 돌린 적이 없어 "측정한 적 없음"이 "문제 없음"으로 읽혔다. 이 과제는 실 데이터가 있는 Phaiakes9 DB에 대해 11개 리포트를 한 번에 돌려 **돌았는지 못 돌았는지**를 파일로 남긴다. 결과 수치는 12월 검증의 참고 자료가 된다.
3. **구체적 절차**: 아래 §2의 블록을 붙여넣는다. 블록이 스스로 선행 조건(러너 파일·DB 컨테이너)을 재검사하고, 통과하면 `db` 부류 10개와 `checkout_db` 부류 1개를 차례로 실행한다. 소요 약 1~2분. 읽기 전용이라 DB·저장소를 바꾸지 않고, 결과 파일은 임시 폴더에만 쓴다.
4. **성공 기준**: 마지막 줄 근처에 `DB_CLASS_EXIT=0`과 `CHECKOUT_DB_CLASS_EXIT=0`이 나온다. 하나라도 0이 아니면 일부 리포트가 **돌지 못한 것**이고, 원인은 `manifest.json`의 `stderr_tail`에 있다. `RUN_REFUSED=True`가 나오면 아무것도 실행되지 않은 것이며, 같은 줄에 무엇이 False였는지 적혀 있다.
5. **실행 환경**: Windows PowerShell (Phaiakes9에서 평소 쓰는 창이 곧 이 시스템이다 — SSH 불필요). 선행 조건: Docker Desktop 가동, 컨테이너 `whymath-pg`(호스트 포트 5433) 실행 중, 이 저장소가 `main`의 OPS-19 머지 이후 커밋이어야 한다.
6. **창 구분**: **새 창 하나**를 열어 쓴다. 서버를 점유하는 명령이 없으므로 끝난 뒤에도 그 창을 계속 쓸 수 있다.

## 1. 부류 3종 — 왜 이렇게 나뉘는가

| 부류 | 필요한 것 | 누가 돌리나 |
|---|---|---|
| `ci` (5개) | 저장소 체크아웃만 | CI `harness-integrity` 잡이 매 PR마다 자동 |
| `db` (10개) | 도달 가능한 DB | 배포 환경은 compose `observation-reports` 서비스가 7일마다 자동, Phaiakes9는 이 런북 |
| `checkout_db` (1개) | 저장소 체크아웃과 DB **둘 다** | 이 런북만 (CI에는 DB가 없고, 배포 이미지에는 `tests/`가 없다) |

배포 이미지에서 `checkout_db`를 돌리면 `tests/` 파일이 없어 지표가 낮게 나온다 — 실측으로 Contract coverage가 100%에서 66.7%로, Vertical Slice가 75%에서 0.0%로 떨어졌다. 그래서 자동 경로에 넣지 않았다.

자동 경로 밖에 하나 더 있다: `generation_seed_adoption_report`는 생성 배치의 genlog 파일(JSONL)을 위치 인자로 받아야만 실행되므로 자동 대상이 아니다. genlog 위치가 정해지면 별도로 안내한다.

## 2. 실행

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$Out = Join-Path $env:TEMP ("whymath-observation-" + (Get-Date -Format "yyyyMMdd-HHmmss"))

# 선행 조건 재검사 — 전부 True여야 아래가 실행된다
$RunnerPresent = Test-Path "src\backend\whymath_backend\ops\observation_report_runner.py"
$PyPresent = Test-Path $Py
$ImportOk = $false
if ($PyPresent) { & $Py -c "import whymath_backend.ops.observation_report_runner" 2>$null; $ImportOk = ($LASTEXITCODE -eq 0) }
$DbUp = ((docker ps --filter "name=whymath-pg" --filter "status=running" --format "{{.Names}}") -eq "whymath-pg")

if ($RunnerPresent -and $PyPresent -and $ImportOk -and $DbUp) { & $Py -m whymath_backend.ops.observation_report_runner --class db --out "$Out\db" --cwd . ; "DB_CLASS_EXIT=$LASTEXITCODE" ; & $Py -m whymath_backend.ops.observation_report_runner --class checkout_db --out "$Out\checkout_db" --cwd . ; "CHECKOUT_DB_CLASS_EXIT=$LASTEXITCODE" ; "RESULT_DIR=$Out" } else { "RUN_REFUSED=True — RUNNER_PRESENT=$RunnerPresent PY_PRESENT=$PyPresent IMPORT_OK=$ImportOk DB_UP=$DbUp (False인 항목부터 해결: 러너 파일이 없으면 git pull로 main을 받고, IMPORT_OK가 False면 이 .venv에 백엔드가 설치되지 않은 것이며, DB_UP이 False면 Docker Desktop과 whymath-pg 컨테이너를 켠다)" }
```

실행이 끝나면 결과 폴더가 `RESULT_DIR=` 줄에 출력된다. 폴더 안에는 부류별 `manifest.json`(실행 기록)과 리포트별 `.txt`(본문)가 있다.

## 3. 결과 읽는 법

러너는 리포트마다 상태를 하나씩 기록한다. 이 네 값이 서로 다르다는 것이 핵심이다.

- `ran_ok` — 프로세스가 정상 종료했다. **수치가 0이어도 이 값이다.** 본문에 "0건"이라 적혀 있어도 "리포트가 0을 보고했다"는 뜻이지 "문제 없음"이 아니다. 빈 DB에서 나온 0은 리포트가 본문에 `볼 것이 없었다`처럼 스스로 구분해 적는다.
- `run_failed` — 종료 코드가 0이 아니다. 측정값이 없다. `stderr_tail`이 원인이다 (예: `ConnectionRefusedError`는 DB가 꺼진 것).
- `run_timeout` — 제한 시간(기본 300초) 안에 끝나지 않아 종료시켰다.
- `spawn_error` — 프로세스를 띄우지 못했다 (인터프리터나 모듈 경로 문제).

`manifest.json`에 `running`이 남아 있으면 러너가 중간에 죽었다는 증거다.

## 4. 배포 환경(staging/prod) 자동 실행 확인

`docker-compose.prod.yml`의 `observation-reports` 서비스가 기동 직후 1회, 이후 성공하면 7일마다, 실패하면 1시간 뒤 재시도로 `db` 부류를 돌린다. 요약은 컨테이너 로그의 마지막 JSON 한 줄(`run_id`·`total`·`ran_ok`·`not_ok`)이다. 리포트 본문은 컨테이너의 `/tmp/observation-reports`에 있고 재기동하면 사라진다 (영속 보관이 필요해지면 그때 볼륨을 얹는다).

## 5. 알려진 한계

- `ran_ok`는 "정상 종료"이지 "측정이 완전했다"가 아니다. 리포트가 본문에 `미측정`이라 적고 정상 종료하는 설계(예: `phase1_structure_report`의 DB 지표)는 본문을 읽어야 안다. 러너는 본문을 해석하지 않는다.
- 결과를 Slack·이메일로 전달하는 것은 `OPS-30` 몫이다.
- 리포트 내용의 좋고 나쁨은 판정하지 않는다 (게이트가 아니라 관측).
