# OPS-141 런북 — WH-1 primary 시간 초과 소요 분해 실측 (Kiki · Phaiakes9)

> **판정 기준**: 작성 시점 `origin/main` `57330b05`. 이 런북이 실행하는 도구
> `scripts/ops/wh1_primary_timeout_decompose.py`는 **이 런북과 같은 PR로 들어옵니다 — PR이 머지되기 전에는
> 실행하지 마십시오.** §1이 `origin/main`에 도구가 있는지 기계로 확인하고, 없으면 아무것도 실행하지 않고
> 멈춥니다.
>
> 태스크: `OPS-141-wh1-primary-timeout-live-decomposition` · 게이트: `G-ops141-wh1-timeout-live-decompose`.
> 이 런북은 **측정만** 합니다. 기본 타임아웃(15초)은 바꾸지 않습니다 — 값 판정(②③)은 수치를 받은 뒤
> 승계 태스크가 합니다.

## 사전 브리핑 (6항목)

### ① 과제 명칭
**WH-1 primary 시간 초과 소요 분해 실측** — "primary 한 턴의 15초가 어디서 소진되는가"를 구간별로 잽니다.

### ② 목적
2026-10-12 라이브 실측에서 15요청 중 14턴이 15초(`wh1_primary_timeout_seconds`)에 걸려 결정론 템플릿으로
폴백했습니다. 학생이 LLM 코칭 대신 덜 개인화된 템플릿을 받는 상태입니다. 원인 후보는 넷입니다.

| 후보 | 내용 |
|---|---|
| (가) | 모델 콜드 로드 — 첫 턴에 모델이 메모리에 올라오는 시간 |
| (나) | 턴당 LLM 호출 수 × 호출당 지연이 15초를 구조적으로 넘음 |
| (다) | Redis 캐시 대기 — Redis가 꺼져 있으면 캐시 연산(get·set)마다 최대 **2초**(`redis_socket_timeout_s`)를 기다리고 미스로 넘어간다. LLM 호출 1회가 캐시 연산 2회(get 1 + set 1)를 부르므로 호출당 최대 4초 |
| (라) | 후보 조립·도구 실행 등 LLM이 아닌 단계 |

(다)는 코드를 읽고 세운 **가설**이지 측정된 사실이 아닙니다. 2026-10-12 서버 로그의
`Redis 캐시 강등 — TimeoutError` 1건이 단서일 뿐이며, 그 로그는 연속 실패 중 첫 건과 100번째 건만 남기므로 몇
번 일어났는지는 모릅니다. 이번 실측이 그것을 가립니다.

**왜 기존 수치로는 못 가리는가**: OPS-134가 기록하는 `llm_ms_total`("끝난 LLM 호출 소요 합")은 캐시 get/set
대기까지 한 타이머로 감쌉니다. 그래서 (가)(나)와 (다)가 같은 숫자로 보입니다. 이 도구는 프로바이더와 캐시를
**각각** 감싸 구간을 따로 잽니다. 프로덕션 코드는 건드리지 않습니다.

결과는 승계 태스크에서 ②(지배 원인 판정)와 ③(15초 재판정)에 쓰입니다.

### ③ 구체적 절차 (전체 약 15~35분 — 추정, 실측 전)
| 절 | 무엇이 일어나는가 | 소요(추정) |
|---|---|---|
| §1 | 코드 동등성·파이썬·Ollama·모델·Docker 사전 점검 (읽기 전용 + 결과 폴더 생성) | 약 1분 |
| §2 | R1 — 캐시를 메모리로 둔 대조군. **모델을 메모리에서 내린 뒤** 시작(첫 턴이 콜드). 예산 120초(자르지 않음) | 2~6분 |
| §3 | R2 — Redis 없음. 예산 120초(자르지 않음) | 3~8분 |
| §4 | R3 — Redis 없음. **실서비스 예산(15초)** 그대로 | 2~4분 |
| §5 | 측정 전용 Redis 컨테이너 기동(포트 16379) | 약 0.5~1분 |
| §6 | R4 — Redis 정상. 예산 120초 / R5 — Redis 정상. 실서비스 예산 | 3~8분 |
| §7 | 측정 전용 Redis 컨테이너 제거 | 수 초 |
| §8 | 전체 요약 한 화면 → 세션에 전달 | 수 초 |

각 실행은 합성 턴 12개(시나리오 4종 × 3바퀴)입니다. 학생 데이터는 쓰지 않고, 클라우드 호출은 0건이며
(정책이 `classify`/GENERAL/FAST/LOCAL로 라우팅 → 모델 `qwen2.5:3b`), 비용은 0원입니다.

**R1~R5를 나눈 이유**: 예산 120초 실행은 턴을 자르지 않아 "원래 얼마나 걸리는가"가 보이고, 실서비스 예산(15초)
실행은 "실제로 몇 %가 폴백하는가"를 재현합니다. Redis 없음/정상/메모리(캐시 비용 0)를 같은 합성 턴으로 대조해야
(다)가 원인인지 가려집니다.

### ④ 성공 기준
| 판정 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `PRE_OK` | `True` | `False`인 항목 이름을 회신 |
| 각 실행 `R?_EXIT` | `0` | `1`=측정 실패(증거는 파일에 남음) · `2`=조건 불성립으로 **거부**(아무것도 측정 안 함) → §9 표 |
| §8 각 실행의 `계측 대조` | `{'OK': 12}` | `MISMATCH`가 있으면 측정 도구 결함 — 수치를 쓰지 말고 회신 |
| §8 `⚠ 프로바이더 호출 실패` 줄 | **없음** | 있으면 그 실행의 프로바이더 시간은 LLM 소요가 아님(Ollama 문제) |

**성공이 아닌 값도 결과입니다.** 폴백이 많이 나오거나 15초를 넘는 턴이 많은 것은 실패가 아니라 이번 실측이
찾는 대상입니다. 도구가 "조건이 선언과 다르다"며 거부하는 것도 정상 동작입니다(거부 사유를 회신해 주십시오).

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`.
**선행 조건**: ⓐ Docker Desktop 가동(§5·§7만 사용) ⓑ Ollama 가동 + 모델 `qwen2.5:3b` 설치 ⓒ **다른 Ollama
사용 작업이 없을 것** — R1이 시작 전에 메모리에 올라온 모델을 전부 내립니다(콜드 측정). 결과 파일은 저장소
밖 `C:\Users\kiki\Desktop\__AI\ops141-out\<시각>` 에만 씁니다.

### ⑥ 창 구분
**창 하나**만 씁니다. 서버를 띄우지 않으므로 점유 창이 없습니다. 평소 쓰시는 **새 PowerShell 창 1개**에서 §1부터
순서대로 붙여넣으십시오. §1이 만든 변수를 뒤 블록이 씁니다 — **창을 닫았다면 §1부터 다시** 하십시오(폴더도
새로 만들어집니다). 각 블록은 선행 조건을 스스로 다시 검사하고, 맞지 않으면 아무것도 실행하지 않고 이유를
출력합니다.

---

## 먼저 알아 둘 것 (코드 실측에서 나온 함정)

1. **`scripts/demo/wh1_primary_probe.py`는 이 측정에 쓸 수 없습니다.** 그 도구는 `run_tutoring_turn`을 직접
   불러 `asyncio.wait_for` 예산·OPS-134 계측·캐시 주입을 모두 우회하고, 결과를 화면에 출력만 합니다(기록
   없음). 새 도구는 그 3케이스를 시나리오로 가져오고, 실서비스와 같은 `run_wh1_primary_turn` 경로를 탑니다.
2. **캐시 적중을 일부러 막습니다.** 적중하면 LLM 호출이 생략돼 소요가 위장으로 낮아집니다. 캐시 키에 실행·턴
   식별자를 붙여, Redis 왕복 비용(get 미스 + set 쓰기)은 그대로 재고 적중만 없앱니다.
3. **후보 조립은 재지 않습니다.** 그 호출은 15초 예산(`asyncio.wait_for`) **바깥**이라 시간 초과의 원인일 수
   없습니다. DB도 쓰지 않습니다.
4. **Ollama 단일 호출 상한은 30초입니다**(`ollama_request_timeout_s`). 예산 120초 실행에서 한 호출이 30초를
   넘으면 프로바이더 실패로 기록되고, 그 사실이 요약에 경고로 나옵니다.
5. **도구는 조건을 스스로 확인합니다.** `redis-down`을 선언했는데 Redis가 응답하거나, `redis-up`을 선언했는데
   응답하지 않으면 측정하지 않고 거부합니다(기록 파일도 만들지 않습니다).

---

## 1. 사전 점검 — 읽기 전용 (결과 폴더만 만듦)

```powershell
# Windows PowerShell (= Phaiakes9) · 사전 점검 (읽기 전용 · 결과 폴더 스캐폴딩만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Tool = "$Repo\scripts\ops\wh1_primary_timeout_decompose.py"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out = "C:\Users\kiki\Desktop\__AI\ops141-out\$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
git fetch origin main
$FetchOk = ($LASTEXITCODE -eq 0)
git cat-file -e origin/main:scripts/ops/wh1_primary_timeout_decompose.py
$ToolOnMain = ($LASTEXITCODE -eq 0)
git diff --quiet origin/main -- src/backend scripts/ops
$PathsMatch = ($LASTEXITCODE -eq 0)
$HeadNow = (git rev-parse --short HEAD)
$MainNow = (git rev-parse --short origin/main)
$Py = ""
foreach ($c in @("$Repo\src\backend\.venv\Scripts\python.exe", "$Repo\.venv\Scripts\python.exe")) { if (($Py -eq "") -and (Test-Path $c)) { $Imp = & $c -c "import whymath_backend, redis; print('IMPORT_OK')" 2>$null; if ($Imp -eq "IMPORT_OK") { $Py = $c } } }
$OllamaHost = ""
$SrcOk = $false
if ($Py -ne "") { cd "$Repo\src\backend"; $OllamaHost = (& $Py -c "from whymath_backend.config import get_settings; print(get_settings().ollama_host)"); $Src = (& $Py -c "import whymath_backend; print(whymath_backend.__file__)"); $SrcOk = ($Src -like "$Repo\src\backend*"); cd $Repo }
$OllamaOk = $false
$ModelOk = $false
if ($OllamaHost -ne "") { try { $Tags = Invoke-RestMethod -Uri "$OllamaHost/api/tags" -TimeoutSec 5; $OllamaOk = $true; $ModelOk = (@($Tags.models | ForEach-Object { $_.name }) -contains "qwen2.5:3b") } catch { "OLLAMA_CHECK_ERROR=$($_.Exception.GetType().Name)" } }
$PreOk = ($FetchOk -and $ToolOnMain -and $PathsMatch -and ($Py -ne "") -and $SrcOk -and $OllamaOk -and $ModelOk)
$Listen6379 = @(Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue).Count
$Listen16379 = @(Get-NetTCPConnection -State Listen -LocalPort 16379 -ErrorAction SilentlyContinue).Count
$DockerVer = "$(docker version --format '{{.Server.Version}}' 2>$null)".Trim()
$OldBox = "$(docker ps -a --filter 'name=^whymath-ops141-redis$' --format '{{.Names}}' 2>$null)".Trim()
$DockerReady = (($DockerVer -ne "") -and ($Listen16379 -eq 0) -and ($OldBox -eq ""))
"FETCH_OK=$FetchOk"
"TOOL_ON_ORIGIN_MAIN=$ToolOnMain"
"CODE_MATCHES_ORIGIN_MAIN=$PathsMatch  (HEAD=$HeadNow  origin/main=$MainNow)"
"PYTHON=$Py"
"LOADED_FROM_CLONE=$SrcOk"
"OLLAMA_HOST=$OllamaHost  OLLAMA_REACHABLE=$OllamaOk  MODEL_qwen2.5:3b_INSTALLED=$ModelOk"
"REDIS_6379_LISTENERS=$Listen6379  (0이어야 R2·R3의 'Redis 없음' 조건이 성립)"
"DOCKER_SERVER=$DockerVer  PORT_16379_LISTENERS=$Listen16379  OLD_CONTAINER='$OldBox'"
"DOCKER_READY=$DockerReady  (False여도 R1~R3은 진행 가능 — R4·R5만 건너뜀)"
"OUT_DIR=$Out"
"PRE_OK=$PreOk"
```

`PRE_OK=True`면 §2로. `False`면 아래 §9 표로 항목을 고치거나 이름을 회신하십시오.

## 2. R1 — 메모리 캐시 대조군 · 콜드 시작 · 예산 120초

선행: §1 `PRE_OK=True`. R1이 **Ollama에서 모델을 내린 뒤** 시작합니다(내려갔는지 도구가 확인하고, 확인 못 하면
측정하지 않고 거부합니다).

```powershell
# Windows PowerShell · §1과 같은 창 · R1 — memory · --cold · 예산 120초 (약 2~6분)
if ($PreOk) { cd "$Repo\src\backend"; & $Py $Tool measure --condition memory --cold --timeout-seconds 120 --reps 3 --out $Out; $R1Exit = $LASTEXITCODE; cd $Repo; "R1_EXIT=$R1Exit  (0=정상 1=측정 실패 2=거부)" } else { "R1_REFUSED — §1 PRE_OK가 True가 아니라 아무것도 실행하지 않았습니다. §1 출력에서 False인 항목을 확인하십시오." }
```

## 3. R2 — Redis 없음 · 예산 120초 (자르지 않음)

선행: §1 `PRE_OK=True`, **`REDIS_6379_LISTENERS=0`**. 6379에 무언가 있으면 도구가 "Redis가 응답한다"며 거부합니다.

```powershell
# Windows PowerShell · 같은 창 · R2 — redis-down · 예산 120초 (약 3~8분)
if ($PreOk) { cd "$Repo\src\backend"; & $Py $Tool measure --condition redis-down --timeout-seconds 120 --reps 3 --out $Out; $R2Exit = $LASTEXITCODE; cd $Repo; "R2_EXIT=$R2Exit  (0=정상 1=측정 실패 2=거부)" } else { "R2_REFUSED — §1 PRE_OK가 True가 아니라 아무것도 실행하지 않았습니다." }
```

## 4. R3 — Redis 없음 · 실서비스 예산 그대로 (15초)

`--timeout-seconds`를 주지 않으므로 서버와 같은 설정값(기본 15초)을 씁니다. 몇 %의 턴이 실제로 폴백하는지
재현합니다.

```powershell
# Windows PowerShell · 같은 창 · R3 — redis-down · 실서비스 예산 (약 2~4분)
if ($PreOk) { cd "$Repo\src\backend"; & $Py $Tool measure --condition redis-down --reps 3 --out $Out; $R3Exit = $LASTEXITCODE; cd $Repo; "R3_EXIT=$R3Exit  (0=정상 1=측정 실패 2=거부)" } else { "R3_REFUSED — §1 PRE_OK가 True가 아니라 아무것도 실행하지 않았습니다." }
```

## 5. 측정 전용 Redis 컨테이너 기동 (포트 16379)

실서비스 Redis(6379)와 겹치지 않도록 **16379**를 씁니다. 컨테이너 이름은 `whymath-ops141-redis`이며 §7에서
지웁니다. `redis:7-alpine`은 운영 구성(`docker-compose.prod.yml`)과 같은 이미지입니다(첫 실행은 이미지를 받느라
시간이 걸릴 수 있습니다).

```powershell
# Windows PowerShell · 같은 창 · Redis 컨테이너 기동 + 응답 확인
$RedisUp = $false
if ($PreOk -and $DockerReady) { docker run -d --name whymath-ops141-redis -p 16379:6379 redis:7-alpine; $RunExit = $LASTEXITCODE; $Pong = ""; for ($i = 0; ($i -lt 20) -and ($Pong -ne "PONG"); $i++) { Start-Sleep -Seconds 1; $Pong = "$(docker exec whymath-ops141-redis redis-cli ping 2>$null)".Trim() }; $RedisUp = (($RunExit -eq 0) -and ($Pong -eq "PONG")); "REDIS_CONTAINER_RUN_EXIT=$RunExit  PING='$Pong'  REDIS_UP=$RedisUp" } else { "REDIS_START_REFUSED — PRE_OK=$PreOk  DOCKER_READY=$DockerReady : Docker 가동·포트 16379 비어 있음·옛 컨테이너 없음이 모두 필요합니다(§1 출력 확인). R4·R5는 건너뛰고 §8로 가도 됩니다." }
```

`REDIS_UP=True`를 눈으로 확인한 뒤 §6으로 가십시오. (§6 블록도 `REDIS_UP`을 스스로 다시 검사합니다.)

## 6. R4·R5 — Redis 정상

```powershell
# Windows PowerShell · 같은 창 · R4 — redis-up · 예산 120초 (약 3~8분)
if ($PreOk -and $RedisUp) { cd "$Repo\src\backend"; & $Py $Tool measure --condition redis-up --redis-url redis://127.0.0.1:16379/0 --timeout-seconds 120 --reps 3 --out $Out; $R4Exit = $LASTEXITCODE; cd $Repo; "R4_EXIT=$R4Exit  (0=정상 1=측정 실패 2=거부)" } else { "R4_REFUSED — PRE_OK=$PreOk  REDIS_UP=$RedisUp : §5가 REDIS_UP=True를 내지 않았습니다." }
```

```powershell
# Windows PowerShell · 같은 창 · R5 — redis-up · 실서비스 예산 (약 2~4분)
if ($PreOk -and $RedisUp) { cd "$Repo\src\backend"; & $Py $Tool measure --condition redis-up --redis-url redis://127.0.0.1:16379/0 --reps 3 --out $Out; $R5Exit = $LASTEXITCODE; cd $Repo; "R5_EXIT=$R5Exit  (0=정상 1=측정 실패 2=거부)" } else { "R5_REFUSED — PRE_OK=$PreOk  REDIS_UP=$RedisUp : §5가 REDIS_UP=True를 내지 않았습니다." }
```

## 7. 측정 전용 Redis 컨테이너 제거

```powershell
# Windows PowerShell · 같은 창 · 컨테이너 제거 + 제거 확인
$Box = "$(docker ps -a --filter 'name=^whymath-ops141-redis$' --format '{{.Names}}' 2>$null)".Trim()
if ($Box -eq "whymath-ops141-redis") { docker rm -f whymath-ops141-redis | Out-Null; $After = "$(docker ps -a --filter 'name=^whymath-ops141-redis$' --format '{{.Names}}' 2>$null)".Trim(); "CONTAINER_REMOVED=$($After -eq '')  (남은 이름: '$After')" } else { "NO_CONTAINER_TO_REMOVE — whymath-ops141-redis 컨테이너가 없습니다(§5를 건너뛰었다면 정상)." }
```

## 8. 전체 요약 — 이 출력을 세션에 전달

새로 만든 결과 폴더의 모든 실행을 순서대로 집계합니다. 요약은 파일로도 남깁니다(`cmd /c` 경유 — PowerShell
파이프를 거치면 한글 출력이 깨질 수 있습니다).

```powershell
# Windows PowerShell · 같은 창 · 요약 (읽기 전용 집계 · summary.txt 생성)
cd "$Repo\src\backend"
cmd /c "$Py $Tool summarize --out $Out --all-in-file > $Out\summary.txt 2>&1"
$SumExit = $LASTEXITCODE
cd $Repo
Get-Content -Encoding UTF8 "$Out\summary.txt"
"SUMMARIZE_EXIT=$SumExit  EXITS: R1=$R1Exit R2=$R2Exit R3=$R3Exit R4=$R4Exit R5=$R5Exit"
"OUT_DIR=$Out"
```

**전달할 것**: 이 블록이 화면에 낸 전체(요약 본문 + `SUMMARIZE_EXIT` 줄). 건너뛴 실행이 있으면 `R?Exit`가
비어 있는 것이 정상입니다. 원시 기록(`decompose.jsonl`)은 `OUT_DIR`에 남아 있으니 지우지 마십시오.

## 9. 막혔을 때

| 증상 | 의미 | 대처 |
|---|---|---|
| `TOOL_ON_ORIGIN_MAIN=False` | 도구 PR이 아직 머지 안 됨 | 머지 후 §1부터 |
| `CODE_MATCHES_ORIGIN_MAIN=False` | 클론이 `origin/main`보다 뒤처졌거나 `src/backend`·`scripts/ops`에 로컬 변경 | 회신. (뒤처진 것뿐이면 세션이 `git merge --ff-only origin/main`을 안내 — 미커밋 변경은 보존됨) |
| `PYTHON=` 빈 값 | `whymath_backend`·`redis`를 임포트할 파이썬 없음 | 회신 |
| `OLLAMA_REACHABLE=False` / `MODEL_..._INSTALLED=False` | Ollama 미가동 / 모델 미설치 | Ollama 기동 · `ollama pull qwen2.5:3b` 후 §1부터 |
| `R?_EXIT=2` + `redis-down을 선언했지만 Redis가 응답한다` | 6379에 다른 프로세스가 있음 | 그 프로세스를 회신 — 세션이 다른 닫힌 포트로 재설계 |
| `R?_EXIT=2` + `Ollama가 응답하지 않는다` | 측정 직전 Ollama가 죽음 | Ollama 재기동 후 해당 블록만 재실행(결과 폴더 유지) |
| `R1_EXIT=2` + `--cold를 요청했지만` | 모델을 내렸는지 확인 못 함 | 다른 Ollama 사용 작업 종료 후 R1 재실행 |
| `R?_EXIT=1` + 요약의 `⚠ 프로바이더 호출 실패` | 호출 중 Ollama 오류(30초 상한 초과 포함) | 요약 전체를 회신 — 시간 상한도 결과입니다 |
| 요약의 `계측 대조`에 `MISMATCH` | 도구 계측 결함 | 수치를 쓰지 말고 회신 |
| `DOCKER_READY=False` | Docker 미가동 / 16379 사용 중 / 옛 컨테이너 | R1~R3만 진행 후 §8. R4·R5는 회신 후 재실행 |
