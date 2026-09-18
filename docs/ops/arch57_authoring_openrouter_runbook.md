# ARCH-57 — 저작 배치를 OpenRouter 좌석으로 1회 돌리기 (Kiki 실행)

> ARCH-55가 채택한 경로(OpenRouter 경유 `deepseek/deepseek-v4.1-flash` · 공급사 `deepinfra`
> 고정)를 **실제 저작 작업**에 처음 태우는 회차다. 셀렉터 배선은 코드로 착지했고, 남은 것은
> 키가 있는 머신에서 한 번 도는지 확인하는 것뿐이다.

## 1. 과제 명칭

저작 배치(문항 생성) 1회를 `WHYMATH_CLOUD_PROVIDER=openrouter`로 실행해 산출물·비용·재시도를
기록한다. 대조군으로 같은 배치를 기본 좌석(anthropic)으로도 돌린다.

## 2. 목적

ARCH-57이 만든 셀렉터가 **저작 경로에서 실제로 작동하는지**를 확인한다. 지금까지 확인된 것은
① 코드 계약(테스트 13,314건 green) ② 컨테이너에서 좌석이 바뀌는 것(`OpenRouterProvider`가
나온다)까지이고, **실제 LLM 호출이 그 좌석으로 나가 문항이 나오는지는 미확인**이다 — 키가
Phaiakes9 User 환경변수에만 있고 컨테이너·CI에는 egress가 없다.

결과는 ARCH-57 완료 증적과 "개발 단계 저작에 이 좌석을 상시로 쓸 것인가"의 1차 재료가 된다.
(상시 배치 전환은 별건이다 — 5절 주의 참조.)

## 3. 구체적 절차

블록 3개다. **[A]는 조회, [B]는 조회, [C]만 호출한다.**

- **[A] 좌석 왕복 확인** (10초) — 환경변수로 좌석이 실제로 바뀌는지, 없으면 기본으로
  돌아오는지 양방향으로 본다. 호출 0건.
- **[B] 사전 점검** (10초) — 키·허용목록·관할이 맞는지 본다. 호출 0건.
- **[C] 저작 1회차** (5~15분) — OpenRouter 좌석으로 `--n 5`를 돌리고, 이어 기본 좌석으로
  같은 수를 돌려 대조군을 만든다. **[A][B]의 판정을 스스로 다시 계산해 조건이 맞지 않으면
  호출을 하나도 하지 않고 거부한다**(HARN-106).

지연은 회차마다 크게 흔들린다 — ARCH-55 4회차 실측 p50 36.9초 / p95 212.6초. 5문항이면
3~20분 사이 어디든 정상이다.

## 4. 성공 기준

- **[A]**: `SEAT_WITH_ENV=OpenRouterProvider` 와 `SEAT_DEFAULT=AnthropicProvider` 두 줄이
  모두 보인다. 한쪽만 보이면 배선이 덜 된 것이다.
- **[B]**: `CHECK_EXIT=0`. 비-0이면 **어느 것이 왜** 미비인지 같은 화면에 적힌다 —
  대개 `OPENROUTER_API_KEY` 미설정이다. 미비는 실패가 아니라 [C]를 하지 말라는 신호다.
- **[C]**: `OPENROUTER_EXIT=0` + `ANTHROPIC_EXIT=0`, 그리고 두 산출 JSONL의 **행 수**가
  출력된다. `WRITE_REFUSED=True`가 보이면 호출을 하나도 하지 않고 거부한 것이며 같은 줄에
  어느 조건이 False였는지 적힌다 → **그 줄을 그대로 회신**해 주십시오.
- 실패 시 대처: `OPENROUTER_EXIT`가 비-0이면 로그 마지막 20줄을 회신한다. 429가 섞여 있어도
  그 자체는 기대 범위다(재시도가 배선돼 있다) — 전건 실패인지 일부인지가 판정 대상이다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: 인터넷 연결. `OPENROUTER_API_KEY`·`ANTHROPIC_API_KEY` User 환경변수.
  Docker·DB·서버 **불요**(이 배치는 DB를 쓰지 않는다).
- 비용: [C]는 좌석당 5회 호출한다. ARCH-55 실측 단가 기준 OpenRouter 약 US$0.006,
  Anthropic 약 US$0.024 — 청구서로 검증한 값이 아니라 회당 비용 곱셈이다.
- **주의 — 상시화는 이 과제가 아니다**: 이 회차는 수동 1회다. 같은 명령을 스케줄에 올리면
  게이트 `G-arch56-availability-trigger`의 발동 조건 ⓐ(상시 배치 트래픽 투입)에 해당하므로
  그때는 ARCH-56이 먼저다.

## 6. 창 구분

**새 PowerShell 창 1개**에서 [A]→[B]→[C]를 순서대로 붙여넣는다. 장기 점유 프로세스가 없으므로
같은 창을 계속 쓴다. [C]는 최대 20분 걸릴 수 있으니 끝날 때까지 그 창을 건드리지 않는다.

---

## [A] 좌석 왕복 확인 (호출 0건)

> **선행 조건 — 이 런북이 읽는 코드는 어디 있는가**
> `l3/providers/factory.py`는 ARCH-57이 **신설한 파일**이다. PR #1202가 머지되기 전에는
> `origin/main`에 없으므로, main 체크아웃에서 [A]를 돌리면 `ModuleNotFoundError`가 난다
> (2026-09-18 실측 — 이 런북의 초판이 그 상태로 안내해 1회 공전시켰다).
> 아래 블록은 **전용 worktree**를 만들어 그 안에서 실행한다: Kiki 클론은 여러 세션이
> 공유하는 단일 작업 사본이라 브랜치를 옮기면 다른 세션의 실행이 깨진다. worktree는
> 원 작업 사본의 브랜치·미커밋 변경을 하나도 건드리지 않는다.
> 머지 이후라면 `$Ref`를 `origin/main`으로 바꾸면 된다 — 블록은 그대로 동작한다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Ref = "origin/claude/exciting-allen-5dkjb0"
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-arch57"
git fetch origin
if (-not (Test-Path $Tree)) { git worktree add --detach $Tree $Ref } else { git -C $Tree fetch origin; git -C $Tree checkout --detach $Ref }
git -C $Tree log -1 --oneline
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$env:PYTHONPATH = "$Tree\src\backend"
$Source = (& $Py -c "import whymath_backend.l3.providers.factory as m; print(m.__file__)")
"SOURCE=$Source"
$FromTree = ($Source -like "*WhyMath-arch57*")
"FROM_TREE=$FromTree"
$Default = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_DEFAULT=$Default"
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
$WithEnv = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_WITH_ENV=$WithEnv"
$SeatOk = $FromTree -and ($WithEnv -eq "OpenRouterProvider") -and ($Default -eq "AnthropicProvider")
if ($SeatOk) { "SEAT_OK=True" } else { "SEAT_OK=False — FROM_TREE=$FromTree SEAT_DEFAULT=$Default SEAT_WITH_ENV=$WithEnv. 셋 다 채워져야 합니다. SEAT_DEFAULT/SEAT_WITH_ENV가 비어 있으면 factory 모듈을 못 찾은 것이니 위 worktree 생성 줄의 출력을 회신해 주십시오." }
```

**`SEAT_OK=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.**

## [B] 사전 점검 (호출 0건)

```powershell
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
& $Py -c "from whymath_backend.config import get_settings; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; import asyncio; s=asyncio.run(OpenRouterProvider().check_status()); print(f'CONFIGURED={s.configured} PROVIDERS={s.allowed_providers} JURISDICTION={s.jurisdiction} ERROR={s.error}')"
"CHECK_EXIT=$LASTEXITCODE"
```

**`CHECK_EXIT=0`이고 `CONFIGURED=True`인 것을 눈으로 확인한 다음에만 [C]를 붙여넣으십시오.**

## [C] 저작 1회차 + 대조군 (호출 10건 — 좌석당 5)

이 블록은 [A][B]의 판정을 **스스로 다시 계산해** 실행을 거부한다. 앞을 건너뛰었거나 앞이
미비를 냈어도 안전하다 — 조건이 맞지 않으면 호출을 하나도 하지 않는다.
`$Py`·`$env:PYTHONPATH`는 [A]가 같은 창에 설정한 값을 물려받는다(창을 바꾸지 마십시오).

```powershell
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\.arch57-out"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
$Seat = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
$Configured = (& $Py -c "from whymath_backend.l3.providers.openrouter import OpenRouterProvider; import asyncio; print(asyncio.run(OpenRouterProvider().check_status()).configured)")
"RECHECK_SEAT=$Seat RECHECK_CONFIGURED=$Configured"
if (($Seat -eq "OpenRouterProvider") -and ($Configured -eq "True")) {
  $OrOut = Join-Path $OutDir "openrouter-$Stamp.jsonl"
  & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $OrOut --n 5 --subscription premium --budget-krw 5000
  "OPENROUTER_EXIT=$LASTEXITCODE"
  "OPENROUTER_ROWS=$((Get-Content $OrOut -ErrorAction SilentlyContinue | Measure-Object -Line).Lines)"
  Remove-Item Env:\WHYMATH_CLOUD_PROVIDER
  $AnOut = Join-Path $OutDir "anthropic-$Stamp.jsonl"
  & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $AnOut --n 5 --subscription premium --budget-krw 5000
  "ANTHROPIC_EXIT=$LASTEXITCODE"
  "ANTHROPIC_ROWS=$((Get-Content $AnOut -ErrorAction SilentlyContinue | Measure-Object -Line).Lines)"
  "OUT_DIR=$OutDir"
} else {
  "WRITE_REFUSED=True — 호출 0건. 좌석=$Seat (OpenRouterProvider여야 함) / 키구성=$Configured (True여야 함). [A][B]를 먼저 실행하고 그 출력을 회신해 주십시오."
}
```

## 회신해 주실 것

[A]의 `SEAT_OK` 줄, [B]의 `CHECK_EXIT`·`CONFIGURED` 줄, [C]의 `OPENROUTER_EXIT`·
`OPENROUTER_ROWS`·`ANTHROPIC_EXIT`·`ANTHROPIC_ROWS` 줄. `WRITE_REFUSED`가 나왔다면 그 한 줄만.

산출 JSONL은 `.arch57-out\`에 남습니다(gitignore 대상 폴더 — 커밋되지 않습니다). 내용 대조가
필요하면 그때 따로 요청드리겠습니다.
