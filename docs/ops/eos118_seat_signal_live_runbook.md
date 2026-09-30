# EOS-118 · ARCH-71 — 저작 경로 좌석 신호·기록 원가 라이브 회차 (Kiki 실행)

> **정정(2026-09-29 · ARCH-71) — 이 런북의 전제가 둘 바뀌었다. 초판(2026-09-19)을 그대로 붙여넣지 말 것.**
>
> ① **기본 좌석이 `anthropic` → `openrouter`로 옮겨졌다**(ARCH-64 · PR #1370 · 커밋 `16e9bf89`).
> 초판 [A]가 기대하던 "환경변수가 없으면 `AnthropicProvider`"는 이제 거짓이다.
>
> ② **Anthropic API가 2026-12-31까지 중단됐다**(ARCH-66 · `anthropic_api_enabled=False`가 기본).
> 초판 [C]의 "대조군 = 기본 좌석(anthropic)"은 두 번 틀린다. anthropic은 더 이상 기본 좌석이
> 아니고, 좌석을 anthropic으로 명시해도 정책 차단 오류로 5건 전부 실패한다(호출이 나가지 않으므로
> 대조군이 되지 못한다). 스위치가 켜진 창이라면 중단 방침 위반이 된다.
>
> 그래서 이 판은 세 가지를 바꿨다.
> - [A]의 왕복 방향을 뒤집었다. 기본은 `OpenRouterProvider`이고, anthropic 명시는 **객체
>   생성만** 한다(호출 0건).
> - [C]를 **기본 좌석 1회차**로 바꿨다. 좌석 환경변수를 지운 창에서 돌리므로 "기본값이 실제로
>   openrouter인가"를 라이브로 잰다.
> - 두 좌석 대조로 얻던 변별력(초판 4절 ⓒ)은 **단가 산식 대조**로 대신한다. 두 좌석의 CLOUD_MID
>   단가는 24.4배 다르므로(`l3/router.py` `CLOUD_TOKEN_PRICE_USD_PER_1M`), genlog에 기록된 원가가
>   어느 좌석의 산식과 맞는지로 좌석이 갈린다.
>
> 초판의 사전 검증과 2026-09-19 실행 결과는 **그 시점의 사실로 유효**하므로 지우지 않고 아래에
> 남긴다. 초판 코드 블록은 git 이력에 있다(커밋 `4cdc27ca`).
>
> 학생 대면 경로의 같은 회차는 `docs/ops/arch71_student_facing_cloud_mid_live_runbook.md`가 맡는다.
>
> **ARCH-69(런타임 LOCAL 강등 · 커밋 `eb633ee1`)는 이 회차의 동작을 바꾸지 않는다.** 강등은 학생
> 대면 서빙 조립(`app.py`의 `runtime_local_degrade=True`)에만 장착되고 저작 조립에는 없다. 그래서
> 저작 회차의 1차 좌석 실패는 지금도 LOCAL 응답으로 바뀌지 않고 genlog의 실패 행으로 남는다.
> 바뀐 것은 요약에 `cloud_seat.failover.local_degrade` 블록(이 회차에서는 "미측정")이 더해진 것뿐이며,
> [A]·[C]가 그 블록의 존재를 리비전 표지로 함께 확인한다.

> `EOS-111`(선언 축)·`EOS-112`(관측 축)가 만든 좌석 신호가 **실제로 도는 회차에서 좌석을
> 말하는지** 확인하는 관측 회차다. 새로 배선할 코드는 없다 — 신호는 이미 `main`에 있고,
> 이 런북은 그 신호를 **잡아서 회신 가능한 형태로 꺼내는** 절차다.
>
> **선행 런북과의 관계**: `docs/ops/arch57_authoring_openrouter_runbook.md`(ARCH-57)의 [C]는
> 종료 코드와 산출 행 수만 회신받게 돼 있어 **요약 JSON(stdout)을 아무 데도 담지 않는다**.
> `cloud_seat` 블록은 바로 그 stdout에 실린다(`problem_corpus_accumulate.main` 끝의
> `json.dump(payload, sys.stdout, …)`). 이 런북의 [C]가 그 stdout을 파일로 받아 필요한 필드를
> 꺼낸다. ARCH-57판도 초판 전제(기본=anthropic)로 쓰였으니 지금은 이 런북을 쓴다.

## 1. 과제 명칭

저작 배치를 **기본 좌석(openrouter)으로 1회**(5문항) 돌리고, 회차 요약의 `cloud_seat` 블록과
genlog의 기록 원가를 꺼내 회신한다.

## 2. 목적

**ARCH-71(2026-09-29 추가)**: `ARCH-64`는 acceptance ⑤(라이브 대조 1회)를 컨테이너에 키가 없어
수행하지 못했다. 이 회차가 그중 **저작 1회차**다. 확인할 것은 셋이다.

- 기본 좌석 컷오버 뒤에도 좌석 신호가 `openrouter`를 말하는가(`cloud_seat.selected_seat`·`state`)
- 관측 모델이 무엇인가(`observation.observed_models`)
- 기록 원가가 좌석 단가로 찍히는가 — CLOUD_MID 1회 추정 **약 0.354원**(가정 토큰 입력 74·출력
  358 기준)이며, 실제 기록은 실측 토큰 × openrouter 단가다

`seat_primary_success_rate`는 ARCH-63 전까지 코드가 계산하지 않으므로 이 회차에서는
**`null`(미산출)이 정상**이다. 0으로 접어 적지 않는다.

**EOS-118(초판 목적 · 2026-09-19에 닫힘)**: 좌석 신호의 코드 계약(EOS-111·112)은 있었으나 실제
LLM 호출이 나간 회차에서 좌석을 말하는지는 아무도 본 적이 없었다(라이브 작동 비율 0). 초판
회차가 그것을 닫았다 — 아래 "실행 결과 — 2026-09-19".

**이 회차는 상시 채택 결정이 아니다.** 수동 1회 관측이며, 게이트 `G-arch56-availability-trigger`의
발동 조건 ⓐ(학생 대면 또는 **상시 배치** 트래픽 투입)를 건드리지 않는다. 같은 명령을 스케줄에
올리는 순간 그쪽이 먼저다.

## 3. 구체적 절차

블록 3개. **[A]는 조회, [B]는 조회, [C]만 호출한다.**

- **[A] 좌석 왕복 + 신호 실재 확인** (약 20초 · 호출 0건) — 기본 좌석이 `OpenRouterProvider`이고
  anthropic 명시가 여전히 `AnthropicProvider`를 만드는지(셀렉터가 살아 있는지) 양방향으로 본다.
  Anthropic API가 꺼져 있는지, 이 트리의 요약 코드가 관측 축(EOS-112)과 2차 좌석 블록(ARCH-64)을
  실제로 내는지도 본다.
- **[B] 사전 점검** (약 10초 · 호출 0건) — 키·허용목록·관할과 키 형태(길이·생략 문자·접두)를 본다.
  키 값은 출력하지 않는다.
- **[C] 기본 좌석 회차 + 신호·원가 추출** (3~15분 · 호출 5건) — 창의 좌석 환경변수를 지우고
  `--n 5`를 돌린다. **요약 stdout을 파일로 받아** `cloud_seat`에서 판정 필드를 꺼내고, genlog에서
  행마다 기록 원가를 좌석 단가 산식과 대조한다. [A][B]의 판정을 **스스로 다시 계산해** 어긋나면
  호출을 하나도 하지 않고 거부한다(HARN-106).

지연은 회차마다 크게 흔들린다 — ARCH-55 4회차 실측 p50 36.9초 / p95 212.6초. 5문항이면 3~15분
사이 어디든 정상이다.

## 4. 성공 기준

**[A]**: `SEAT_OK=True`. 실패하면 같은 줄에 어느 항이 False였는지 적힌다. `HAS_SEAT_BLOCKS=False`면
트리의 코드가 EOS-112 또는 ARCH-64 이전 리비전이라는 뜻이니 그 줄을 회신한다.

**[B]**: `CHECK_EXIT=0` · `CONFIGURED=True` · `KEY_HAS_ELLIPSIS=False` · `KEY_LENGTH`가 20 이상.
`CONFIGURED=False`면 실패가 아니라 [C]를 하지 말라는 신호다 — 키 등록은
`docs/ops/arch71_student_facing_cloud_mid_live_runbook.md`의 [K-1]·[K-2]를 쓴다.

**[C]**: 아래 다섯 축이 **함께** 성립해야 통과다. 하나라도 어긋나면 그것은 통과 실패가 아니라
**원인 규명 대상**이며, 그 회차도 그대로 회신한다(실패 회차 폐기 금지).

| 축 | 통과 조건 | 어긋나면 |
|---|---|---|
| ⓐ 선언 축 | `selected_seat`가 `openrouter`이고 `state`가 `not_measured`가 **아닐** 것 | 기본 좌석 컷오버가 이 머신에서 성립하지 않았거나 좌석 판정 자체가 없다 |
| ⓑ 관측 축 | `comparable`가 **0보다 클** 것 | 선언 축만 살고 관측 축이 죽은 상태 — EOS-111을 등재하게 만든 바로 그 형태 |
| ⓒ 변별력(갱신) | `COST_CHECK`의 `price_seat_counts`에서 `openrouter`가 **1 이상**이고 `anthropic`·`neither`가 **0**일 것 | `anthropic`이 있으면 기록 원가가 좌석 단가를 따르지 않는다(ARCH-62·64 회귀). `neither`면 단가표가 바뀌었는지부터 본다. `openrouter=0`(전 행 `unmeasured`)이면 원가가 한 건도 기록되지 않은 것이다 — "어긋난 행 0건"만으로 통과로 읽지 않는다 |
| ⓓ 재시도 | `retries_measured`가 0보다 클 것 | 계측 배선이 라이브에서 죽은 것 |
| ⓔ 2차 좌석(신설) | `secondary_seat`·`seat_primary_success_rate`·`seat_failover_rate`가 **셋 다 `null`**일 것 | 값이 있으면 2차 좌석이 없는데 있는 것처럼 보이는 위장이다(ARCH-64) |

**ⓐ만으로는 통과가 아니다.** `state`는 선언값(설정 유래 모델명) 기반이라 호출이 전부 실패해도
`all_on_selected_seat`로 나온다(부록 실측). 실제로 호출이 나갔는지는 ⓑ·ⓒ가 말한다.

**ⓔ의 `null`은 "모른다"이지 "0%"가 아니다.** 판정 칸에 `seat_primary_success_rate=None(미산출 ·
ARCH-63 전 정상)`으로 적고 0으로 접지 않는다.

**`local_degrade_measured=false`·`seat_local_degrade_rate=null`도 정상이다(ARCH-69).** 런타임 LOCAL
강등은 학생 대면 서빙 조립(`app.py`)에만 장착된다 — 저작·측정 조립의 `CompositeProvider`에는
`runtime_local_degrade` 인자가 없다(AST로 동결 — `tests/backend/l3/test_cloud_runtime_local_degrade.py`의
`test_only_the_student_facing_app_arms_runtime_local_degrade`). 그래서 이 배치는 강등 계수를 요약에 넘기지 않고,
요약은 그것을 "미측정"으로 적는다(`anchor_round_ledger._failover_block` · 판정 기준 `a28a8d08`).
0으로 접지 않는다. 같은 이유로 이 회차의 결과는 **이 머신의 Ollama 상태와 무관하다** — 학생 대면
회차(ARCH-71 런북 0-4)와 다른 점이다.

**함께 읽을 값**: `price_seat`가 `unmeasured`인 행은 원가·토큰 중 하나가 없는 행이다(호출 실패 행,
또는 CLOUD_HIGH 핀 `deepseek/deepseek-v4-pro` — 그 조합은 단가 미등재라 원가가 `null`이 정상이다).
`recorded_krw`가 0.354와 정확히 같지 않은 것은 정상이다 — 0.354원은 가정 토큰에서의 추정이고
기록은 실측 토큰으로 계산된다.

**종료 코드가 비-0이어도 데이터는 있다.** 이 배치는 요약 JSON을 stdout에 쓴 **뒤에** 판정 코드를
돌려준다 — `1`=축적 0건 또는 카나리 차단, `2`=연속 무진전 알람. 즉 `EXIT=1`이 "측정 실패"를
뜻하지 않는다. 추출이 값을 내면 그 값이 실측이다. genlog의 `genlog_success`도 같다 — 호출 성공이
아니라 **문항 후보 조립 성공**이므로, `false`여도 원가·관측 모델은 실측이다.

실패 시 대처: 추출이 `EXTRACT_SKIPPED`를 내면 같은 줄의 사유와 `*.err.log`의 마지막 20줄을
회신한다. 429가 섞여 있어도 그 자체는 기대 범위다(재시도가 배선돼 있다) — 전건 실패인지
일부인지가 판정 대상이다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath` (코드는 전용 worktree
  `C:\Users\kiki\Desktop\__AI\WhyMath-eos118`에서 읽는다)
- 선행 조건: 인터넷 연결 · OpenRouter 키(User 환경변수 `OPENROUTER_API_KEY` 또는
  `WHYMATH_OPENROUTER_API_KEY`). **Anthropic 키는 불요하다**(있어도 쓰지 않는다 — ARCH-66).
  Docker·DB·서버 **불요** — 이 배치는 DB를 쓰지 않는다(모듈에 DB import 0건).
- 좌석 판정은 작업 디렉터리의 `.env`까지 포함한 실효값이다(`Settings`가 `.env`도 읽는다).
- 비용: [C]는 5회 호출한다. ARCH-55 실측 단가 기준 약 US$0.006 — 청구서로 검증한 값이 아니라
  회당 비용 곱셈이다.
- 전용 worktree를 쓴다: Kiki 클론은 여러 세션이 공유하는 단일 작업 사본이라 브랜치를 옮기면
  다른 세션의 실행이 깨진다. worktree는 원 작업 사본의 브랜치·미커밋 변경을 **하나도**
  건드리지 않는다.

## 6. 창 구분

**새 PowerShell 창 1개**에서 [A]→[B]→[C]를 순서대로 붙여넣는다. 장기 점유 프로세스가 없으므로
같은 창을 계속 쓴다. `$Py`·`$env:PYTHONPATH`를 [A]가 그 창에 설정하고 [C]가 물려받으므로
**창을 바꾸지 않는다**. [C]는 최대 15분 걸릴 수 있으니 끝날 때까지 그 창을 건드리지 않는다.
[C]는 이 창의 `WHYMATH_CLOUD_PROVIDER`를 지운다 — 이 창을 다른 런북에 재사용하려면 새 창을 연다.

---

## [A] 좌석 왕복 + 신호 실재 확인 (호출 0건)

> **왜 기본값을 잴 때 자식 프로세스에서 변수를 제거하는가**: PowerShell 창은 앞서 붙여넣은
> 블록이 설정한 `$env:` 값을 계속 들고 있다. 그 상태에서 "설정 전에 재면 기본값"이라고
> 가정하면 재실행·부분 실행한 창에서는 **남아 있는 값을 기본값으로 오독한다**(2026-09-18
> 실측 — 초판 전제에서 `SEAT_DEFAULT=OpenRouterProvider`가 나왔고 그것은 코드가 아니라 창의
> 상태였다). 그래서 부재를 *가정*하지 않고 자식 프로세스에서 `os.environ.pop`으로 **만들어**
> 잰다. anthropic 명시도 자식 프로세스 안에서만 설정한다 — 이 창의 환경변수는 건드리지 않는다.
> `PRE_SHELL_VAR`·`PRE_USER_VAR`를 함께 찍는 것은 오염이 창 한정인지 User 환경변수에 영구
> 등록된 것인지 구분하기 위해서다.
>
> **`HAS_SEAT_BLOCKS`는 무엇을 가르는가**: 요약의 `cloud_seat.observation` 블록은 EOS-112가,
> `cloud_seat.failover` 블록은 ARCH-64가, 그 안의 `local_degrade` 블록은 ARCH-69가 신설했다.
> 셋 중 하나라도 없는 리비전에서 돌면 [C]의 추출이 `KeyError`로 죽는데, 그 실패는 원인이 멀리
> 있어 읽기 어렵다. 여기서 **빈 집계로 요약 함수를 한 번 불러** 키 유무를 직접 본다 — 호출 0건·
> 네트워크 0건이면서 리비전을 변별한다. [C]도 같은 판정을 다시 계산한다.

```powershell
# [창① A 좌석 왕복] Windows PowerShell (Phaiakes9) — 새 창 · 호출 0건
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Ref = "origin/main"
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-eos118"
git fetch origin
if (-not (Test-Path $Tree)) { git worktree add --detach $Tree $Ref } else { git -C $Tree fetch origin; git -C $Tree checkout --detach $Ref }
git -C $Tree log -1 --oneline
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe" }
if (Test-Path $Py) { "PY=$Py" } else { $Py = "python"; "PY=system — venv를 찾지 못해 PATH의 python을 씁니다" }
$env:PYTHONPATH = "$Tree\src\backend"
$Source = (& $Py -c "import whymath_backend.l3.providers.factory as m; print(m.__file__)")
"SOURCE=$Source"
$FromTree = ($Source -like "*WhyMath-eos118*")
"FROM_TREE=$FromTree"
"PRE_SHELL_VAR=$($env:WHYMATH_CLOUD_PROVIDER)"
"PRE_USER_VAR=$([Environment]::GetEnvironmentVariable('WHYMATH_CLOUD_PROVIDER','User'))"
$Default = (& $Py -c "import os; os.environ.pop('WHYMATH_CLOUD_PROVIDER', None); from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_DEFAULT=$Default"
$Explicit = (& $Py -c "import os; os.environ['WHYMATH_CLOUD_PROVIDER'] = 'anthropic'; from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_EXPLICIT_ANTHROPIC=$Explicit"
$AnthropicOff = (& $Py -c "from whymath_backend.config import get_settings; print(get_settings().anthropic_api_enabled is False)")
"ANTHROPIC_OFF=$AnthropicOff"
$HasBlocks = (& $Py -c "from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates; b=seat_operating_rates(SeatTally(), selected_seat='openrouter', seat_model_pins=()); print('declared_vs_served' in b.get('observation', {}) and b.get('failover', {}).get('seat_primary_success_rate', 'absent') is None and 'local_degrade' in b.get('failover', {}))")
"HAS_SEAT_BLOCKS=$HasBlocks"
$SeatOk = $FromTree -and ($Default -eq "OpenRouterProvider") -and ($Explicit -eq "AnthropicProvider") -and ($AnthropicOff -eq "True") -and ($HasBlocks -eq "True")
if ($SeatOk) { "SEAT_OK=True" } else { "SEAT_OK=False — FROM_TREE=$FromTree SEAT_DEFAULT=$Default(OpenRouterProvider여야 함) SEAT_EXPLICIT_ANTHROPIC=$Explicit(AnthropicProvider여야 함 — 객체 생성만) ANTHROPIC_OFF=$AnthropicOff(True여야 함 — ARCH-66) HAS_SEAT_BLOCKS=$HasBlocks. 비어 있는 항이 있으면 위 worktree 생성 줄의 출력을 회신해 주십시오." }
```

**`SEAT_OK=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.** (건너뛰어도 [C]가 같은 판정을
다시 계산해 스스로 거부한다.)

## [B] 사전 점검 (호출 0건 · 키 값 미출력)

```powershell
# [창① B 사전 점검] Windows PowerShell — 같은 창 · 호출 0건 · 키 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath
& $Py -c "import asyncio; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; s=asyncio.run(OpenRouterProvider().check_status()); print(f'CONFIGURED={s.configured} PROVIDERS={s.allowed_providers} JURISDICTION={s.jurisdiction} ERROR={s.error}')"
"CHECK_EXIT=$LASTEXITCODE"
& $Py -c "from whymath_backend.config import get_settings; k=get_settings().openrouter_api_key.get_secret_value(); print('KEY_LENGTH=%d KEY_HAS_ELLIPSIS=%s KEY_PREFIX_SK_OR=%s' % (len(k), chr(8230) in k, k.startswith('sk-or-')))"
```

**`CHECK_EXIT=0`이고 `CONFIGURED=True`인 것을 눈으로 확인한 다음에만 [C]를 붙여넣으십시오.**
`CONFIGURED=True`인데 `KEY_HAS_ELLIPSIS=True`거나 `KEY_LENGTH`가 20 미만이면 멈추고 두 줄을
회신한다(자리표시자 문자열이 키로 등록된 상태일 수 있다 — 2026-07-16 사고 유형).

## [C] 기본 좌석 회차 + 신호·원가 추출 (호출 5건)

이 블록은 [A][B]의 판정을 **스스로 다시 계산해** 실행을 거부한다. 앞을 건너뛰었거나 앞이
미비를 냈어도 안전하다 — 조건이 맞지 않으면 호출을 하나도 하지 않고 `WRITE_REFUSED` 한 줄을
낸다. 그 줄에 어느 조건이 False였는지 적힌다.

> **창의 좌석 변수를 지우고 도는 이유**: 이 회차가 재는 것은 "기본값이 openrouter인가"다. 창에
> `WHYMATH_CLOUD_PROVIDER`가 남아 있으면(초판 [A]가 `openrouter`를 설정했었다) 기본값이 아니라 그
> 값을 잰다. 그래서 첫 줄에서 지우고, 재검사도 **지운 뒤의 같은 창 상태**로 한다. 요약의
> `selected_seat`가 회신에 그대로 찍히므로 그 회차가 어느 좌석이었는지는 나중에도 결정 가능하다.
>
> **요약 stdout을 `cmd /c`로 받는 이유**: PowerShell 5.1은 자식 프로세스의 stdout을
> `[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 **디코딩한 뒤 재인코딩**한다.
> 이 요약 JSON에는 한국어 주석 문자열과 `—`·`·`가 들어 있어 그 왕복에서 바이트 경계가
> 어긋나고, 선행바이트가 뒤따르는 `"`를 삼켜 **JSON 구조 문자가 유실된다**(2026-09-14 실측 —
> `Out-File -Encoding utf8`로도 막히지 않는다). `cmd /c "... > 파일"`은 그 경유 자체를 없앤다.
> `$env:PYTHONUTF8 = "1"`(2026-09-29 추가)은 파이썬이 그 파일을 로케일(cp949)이 아니라 UTF-8로
> 쓰게 한다 — 추출기가 UTF-8로 읽기 때문이다.
>
> **`--subscription premium --budget-krw 5000`은 장식이 아니다**: 이 둘을 **함께** 주지 않으면
> 라우터가 LOCAL로 강제해(`problem_corpus_accumulate.authoring_can_reach_cloud`가 같은 판정을
> 미리 한다) 클라우드 호출이 0건이 되고, 좌석 신호는 `not_measured`나 로컬 모델만 내놓는다.
> 예산은 8.612원 이상이어야 한다 — 라우터의 사전 판정은 좌석을 모르고 anthropic 단가로 임계를
> 잡는다(`router.SERVING_CLOUD_SEAT` docstring ② · ARCH-64가 남긴 간극 · 상환 = `ARCH-70`).
>
> **원가 대조(`COST_CHECK`)가 무엇을 하는가**: genlog(`<out>.genlog.jsonl` — 호출마다 즉시 UTF-8로
> 적재)의 행마다 `cost_usd`를 **같은 행의 실측 토큰 × 좌석 단가**로 다시 계산해 openrouter
> 산식과 맞는지, anthropic 산식과 맞는지 가른다. 단가는 런북에 적지 않고 코드
> (`CLOUD_TOKEN_PRICE_USD_PER_1M`)에서 읽는다 — 단가표가 바뀌면 이 대조가 그 값을 따라간다.

```powershell
# [창① C 기본 좌석 회차] Windows PowerShell — 같은 창 · OpenRouter 유료 호출 5건 · 약 US$0.006
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:WHYMATH_CLOUD_PROVIDER = $null
"SHELL_VAR_AFTER_CLEAR=[$($env:WHYMATH_CLOUD_PROVIDER)]"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\.eos118-out"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Extract = "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'))['cloud_seat'];o=d['observation'];v=o['declared_vs_served'];f=d['failover'];print(json.dumps({'selected_seat':d['selected_seat'],'state':d['state'],'seat_model_pins':d['seat_model_pins'],'calls_total':d['calls_total'],'calls_with_model_name':d['calls_with_model_name'],'declared_models':d['observed_models'],'served_models':o['observed_models'],'calls_with_served_model':o['calls_with_served_model'],'comparable':v['comparable'],'matched':v['matched'],'differs':v['differs'],'differing_pairs':v['differing_pairs'],'retries_measured':o['retries']['calls_with_retries_measured'],'retries_total':o['retries']['retries_total'],'cost_usd_total':d['cost_usd_total'],'calls_with_cost':d['calls_with_cost'],'secondary_seat':f['secondary_seat'],'seat_primary_success_rate':f['seat_primary_success_rate'],'seat_failover_rate':f['seat_failover_rate'],'seat_local_degrade_rate':f['seat_local_degrade_rate'],'local_degrade_measured':f['local_degrade']['measured']},indent=2))"
$CostCheck = "import json,math,sys;from whymath_backend.l3.models import CostTier as T;from whymath_backend.l3.router import CLOUD_TOKEN_PRICE_USD_PER_1M as P,CLOUD_MIN_COST_KRW as E,USD_TO_KRW as FX;rows=[json.loads(x) for x in open(sys.argv[1],encoding='utf-8') if x.strip()];k=lambda r:None not in (r.get('cost_usd'),r.get('input_tokens'),r.get('output_tokens'));u=lambda r,s:(r['input_tokens']*P[(T.CLOUD_MID,s)][0]+r['output_tokens']*P[(T.CLOUD_MID,s)][1])/1000000;m=lambda r:'unmeasured' if not k(r) else ('openrouter' if math.isclose(r['cost_usd'],u(r,'openrouter'),rel_tol=1e-9) else ('anthropic' if math.isclose(r['cost_usd'],u(r,'anthropic'),rel_tol=1e-9) else 'neither'));per=[{'model_name':r.get('model_name'),'served_model':r.get('served_model'),'genlog_success':r.get('success'),'input_tokens':r.get('input_tokens'),'output_tokens':r.get('output_tokens'),'recorded_krw':None if r.get('cost_usd') is None else round(r['cost_usd']*FX,4),'price_seat':m(r),'error_detail':(r.get('error_detail') or '')[:120]} for r in rows];print(json.dumps({'genlog_rows':len(rows),'est_krw_per_call_at_assumed_tokens':{'openrouter':round(E[(T.CLOUD_MID,'openrouter')],4),'anthropic':round(E[(T.CLOUD_MID,'anthropic')],4)},'price_seat_counts':{s:sum(1 for x in per if x['price_seat']==s) for s in ('openrouter','anthropic','neither','unmeasured')},'rows':per},indent=2))"
$Seat = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
$Configured = (& $Py -c "import asyncio; from whymath_backend.config import get_settings; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; k=get_settings().openrouter_api_key.get_secret_value(); print(asyncio.run(OpenRouterProvider().check_status()).configured and len(k) >= 20 and chr(8230) not in k)")
$AnthropicOff = (& $Py -c "from whymath_backend.config import get_settings; print(get_settings().anthropic_api_enabled is False)")
$Source = (& $Py -c "import whymath_backend.l3.providers.factory as m; print(m.__file__)")
$FromTree = ($Source -like "*WhyMath-eos118*")
$HasBlocks = (& $Py -c "from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates; b=seat_operating_rates(SeatTally(), selected_seat='openrouter', seat_model_pins=()); print('declared_vs_served' in b.get('observation', {}) and b.get('failover', {}).get('seat_primary_success_rate', 'absent') is None and 'local_degrade' in b.get('failover', {}))")
"RECHECK_FROM_TREE=$FromTree RECHECK_HAS_SEAT_BLOCKS=$HasBlocks RECHECK_SEAT=$Seat RECHECK_KEY_READY=$Configured RECHECK_ANTHROPIC_OFF=$AnthropicOff"
if ($FromTree -and ($HasBlocks -eq "True") -and ($Seat -eq "OpenRouterProvider") -and ($Configured -eq "True") -and ($AnthropicOff -eq "True")) {
  $PrevPythonUtf8 = $env:PYTHONUTF8
  $env:PYTHONUTF8 = "1"
  $OrOut = Join-Path $OutDir "default-seat-$Stamp.jsonl"
  $OrJson = Join-Path $OutDir "default-seat-$Stamp.summary.json"
  $OrLog = Join-Path $OutDir "default-seat-$Stamp.err.log"
  $OrGenlog = Join-Path $OutDir "default-seat-$Stamp.genlog.jsonl"
  cmd /c "$Py -m whymath_backend.harness.problem_corpus_accumulate --out $OrOut --n 5 --subscription premium --budget-krw 5000 > $OrJson 2> $OrLog"
  "BATCH_EXIT=$LASTEXITCODE"
  "===== CLOUD_SEAT / default seat ====="
  if ((Test-Path $OrJson) -and ((Get-Item $OrJson).Length -gt 0)) { & $Py -c $Extract $OrJson } else { "EXTRACT_SKIPPED=summary — 요약 JSON이 없거나 비었습니다. $OrLog 마지막 20줄을 회신해 주십시오." }
  "===== COST_CHECK / genlog ====="
  if ((Test-Path $OrGenlog) -and ((Get-Item $OrGenlog).Length -gt 0)) { & $Py -c $CostCheck $OrGenlog } else { "EXTRACT_SKIPPED=genlog — genlog가 없거나 비었습니다(호출이 한 건도 기록되지 않았다). $OrLog 마지막 20줄을 회신해 주십시오." }
  "OUT_DIR=$OutDir"
  $env:PYTHONUTF8 = $PrevPythonUtf8
  "PYTHONUTF8_RESTORED=[$($env:PYTHONUTF8)]"
} else {
  "WRITE_REFUSED=True — 호출 0건. 트리 출처=$FromTree (True여야 함 — WhyMath-eos118 worktree의 코드) / 요약 블록=$HasBlocks (True여야 함 — EOS-112·ARCH-64·ARCH-69 리비전) / 좌석=$Seat (OpenRouterProvider여야 함 — 창 변수를 지운 뒤의 기본값) / 키준비=$Configured (True여야 함) / Anthropic 꺼짐=$AnthropicOff (True여야 함 — ARCH-66). [A][B]를 먼저 실행하고 그 출력을 회신해 주십시오."
}
```

## 회신해 주실 것

1. [A]: `git -C $Tree log -1 --oneline`이 찍은 한 줄과 `SEAT_OK` 줄 (False면 그 줄 전체)
2. [B]: `CHECK_EXIT`·`CONFIGURED`·`KEY_LENGTH` 줄
3. [C]: `SHELL_VAR_AFTER_CLEAR`·`RECHECK_FROM_TREE`로 시작하는 줄·`BATCH_EXIT`·`PYTHONUTF8_RESTORED` 줄
4. [C]의 **`===== CLOUD_SEAT / default seat =====` 블록과 `===== COST_CHECK / genlog =====` 블록 전문**
   — 이것이 이 과제의 산출물이다

`WRITE_REFUSED`가 나왔다면 그 한 줄만 회신하면 된다.

산출물은 `.eos118-out\`에 남는다(`.gitignore` 등재 폴더 — 커밋되지 않는다): 회차 JSONL,
요약 JSON 전문(`*.summary.json`), genlog(`*.genlog.jsonl`), 회차 대장(`*.rounds.jsonl`),
stderr 로그(`*.err.log`). 재실행하면 새 시각의 파일이 생기고 앞 파일은 그대로 남는다.

## 판정 후 처리 (세션 몫)

- 다섯 축이 전건 성립하면 ARCH-71 acceptance ①의 저작 1회차 증적으로 적는다. 판정 칸에
  `seat_primary_success_rate=None(미산출 · ARCH-63 전 정상)`을 **그대로** 적고 0으로 쓰지 않는다.
- `differs > 0`이면 `differing_pairs`를 보고 **별칭→버전 해소인지 진짜 폴백인지 사람이 판정**해
  그 판정을 기록한다. 기계가 가르지 않기로 한 축이다(EOS-112 PR #1211).
- `differs == 0`이면 "이 공급사는 선언값과 같은 문자열을 돌려준다"는 **실측**이며 그것도
  기록한다. `comparable > 0`이 요구되므로 실측 0과 미관측은 구분된다.
- 다섯 축 중 어긋난 것이 있으면 그 실패가 이 회차의 산출물이다. 원인을 실측 규명해 수정
  태스크로 분리 등재하고, 실패 회차를 폐기하지 않는다.

## 부록 — 갱신판 사전 검증 (2026-09-29 · 판정 기준: main `a28a8d08`)

「검증 없는 실행 안내 금지」에 따라, 갱신한 블록이 기대 산출물을 실제로 내는 코드 경로인지
확인했다. **라이브 호출은 이 컨테이너에서 불가하므로**(키 없음) 확인 범위는 가짜 OpenRouter
전송층까지다. 실제 호출이 나가는 축은 이 회차가 처음 본다.

기준 커밋: 갱신판의 첫 검증은 ARCH-69 착지 이전 main `ab9f29f2`에서 했다. ARCH-69(`eb633ee1`)가
요약에 `failover.local_degrade` 블록을 더했으므로, 아래는 **전부 main `a28a8d08`에서 다시 돌린
결과**다. 재현은 `git archive origin/main`의 `src/backend`·`docs` 사본에서 했고, 배치는 실제
`problem_corpus_accumulate`를 실제 `HttpxChatTransport`(재시도 포함)로 돌리되
`httpx.AsyncClient.post` 하나만 대역으로 바꿨다.

- **[A]·[B]·[C]의 `-c` 한 줄 코드**를 이 파일에서 그대로 떼어 돌렸다 — 기본
  `OpenRouterProvider` · anthropic 명시 `AnthropicProvider`(객체만) · `ANTHROPIC_OFF=True` ·
  `HAS_SEAT_BLOCKS=True`. 스위치를 켜거나(`WHYMATH_ANTHROPIC_API_ENABLED=true`) 키를 비우면
  해당 항이 False로 바뀌어 변별한다. `HAS_SEAT_BLOCKS`는 ARCH-69 이전 트리(`ab9f29f2`)에서
  `False`다 — 갱신한 판정이 리비전을 가른다.
- **`$Extract`·`$CostCheck`** 를 그대로 떼어, 배치를 3문항 돌린 **실제 산출물**(요약 JSON·genlog)에
  적용했다(배치 종료 코드 1 = 축적 0건 — 대역 응답이 문항 후보로 조립되지 않았다. 데이터는 있다).
  정상 회차는 `selected_seat=openrouter` · `state=all_on_selected_seat` · `comparable=3` ·
  `retries_measured=3` · 2차 좌석 셋 다 `null` · `seat_local_degrade_rate=null` ·
  `local_degrade_measured=false` · `price_seat_counts.openrouter=3`.
- **실패 주입 2종** — ⓐ 정상 회차 genlog의 `cost_usd`를 anthropic 단가 산식으로 바꿔 넣은 입력
  → `price_seat_counts`가 `anthropic=3`·`openrouter=0`으로 **ⓒ가 거짓**이 된다(초판 검증은 코드
  회귀 모사였고, 이번 재검증은 입력 주입이다 — 대조기가 가르는 대상은 같다) ⓑ 전 호출 429 → 요약은
  여전히 나오고(`EXIT=1`이어도 데이터가 있다) `comparable=0`이라 **ⓑ가 거짓**이 되며, genlog 행의
  `price_seat`는 전부 `unmeasured`다(원가를 0으로 지어내지 않는다). 이때 `state`는
  `all_on_selected_seat`로 나온다 — 선언값(설정 유래 모델명) 기반이라 호출이 전부 실패해도
  성립하므로, ⓐ만 보고 통과로 읽으면 안 된다. 같은 429 회차에서 `local_degrade_measured=false`였고
  stderr에 LOCAL 강등 경고가 0건이었다 — 저작 경로는 1차 좌석 실패를 LOCAL로 넘기지 않는다.
- 배치는 모든 genlog 행을 호출 직후 UTF-8로 적재하므로(`provenance_bridge.append_generation_log_jsonl`)
  배치가 도중에 죽어도 그때까지의 원가 대조는 가능하다.

### 갱신판에 대한 CI 가드의 실제 적용 범위 (정직한 공백 · 초판과 같다)

`check_runbook_blocks.py`·`check_ps_scripts.py`가 이 파일을 통과시키지만, [C]의 자가거부 가드는
**사람이 쓴 것이고 기계가 지키지 않는다** — 가드 스캐너의 쓰기 어휘에 유료 외부 호출·출력
리다이렉션 축이 없다(아래 초판 부록과 같은 공백 · 상환 = `HARN-116`).

## 부록 — 초판 사전 검증 (2026-09-19 · 판정 기준: main `ed298920` · 초판 전제)

「검증 없는 실행 안내 금지」에 따라, 안내 전에 각 명령이 기대 산출물을 실제로 내는 코드
경로인지 확인했다. **라이브 호출은 이 컨테이너에서 불가하므로**(egress·키 없음) 확인 범위는
*신호를 꺼내는 경로*까지이며, 호출이 실제로 나가는 축은 이 회차가 처음 본다.

- **`cloud_seat` 실재** — `problem_corpus_accumulate.py:860`이 `seat_operating_rates(...)`를
  `payload["cloud_seat"]`에 싣고, `payload`는 `json.dump(payload, sys.stdout)`으로만 나간다.
  ARCH-57판 [C]가 stdout을 담지 않아 이 런북이 필요해진 근거다.
- **[A]의 `HAS_OBSERVATION` 프로브** — main 코드에서 빈 `SeatTally()`로 실행해 `True` 실측.
- **[C]의 추출기** — 런북 본문의 `$Extract` 문자열을 **그대로 떼어내** 두 좌석 픽스처에
  돌렸고, EOS-118이 요구하는 필드 전건이 나왔다(exit 0).
- **실패 주입 2종** — ⓐ `observation` 블록을 제거한 옛 리비전 모사 → `KeyError` + exit 1로
  **크게 터진다**([A]의 가드가 장식이 아니라는 뜻이다) ⓑ 클라우드 호출 0건 회차 모사 →
  `state: not_measured`·`comparable: 0`을 **데이터로 낸다**(실패를 감추지도, 죽지도 않는다).
- **재시도 축의 비대칭** — `openrouter.py:390`은 `retries=retries_since(...)`를 싣고
  `anthropic.py:216`은 `retries`를 `None`으로 둔다. 그래서 대조군의 `retries_measured=0`은
  정상이며, 4절 표의 ⓓ를 OpenRouter 회차에만 건다.(초판 4절 기준 — 갱신판은 대조군이 없어 ⓓ를 기본 좌석 회차에 건다.)
- **DB 불요** — 모듈에 DB·세션 import 0건.

### 초판에 대한 CI 가드의 실제 적용 범위 (정직한 공백)

CI 잡 3종을 로컬에서 그대로 재현해 전건 `exit 0`을 받았다 — `infra-contracts`의
`check_runbook_blocks.py`, `infra-shell`의 `check_ps_scripts.py`, `policy-guard`의
`cp949_guard.py`. **다만 그 통과를 자가거부 가드의 증거로 읽으면 안 된다.**

주입으로 확인한 사실: 이 런북 [C]의 자가거부 가드 `if (...) { }`를 통째로 제거해도
`check_runbook_blocks.py`는 `위반 0건 / 판정: 통과`를 냈고 집계(`쓰기 블록 18개`)도 변하지
않았다. 원인은 가드의 고장이 아니라 **쓰기 어휘의 범위**다 — `_WRITE_COMMAND_TOKENS`에
유료 외부 호출·출력 리다이렉션 축이 없어 이 블록이 쓰기로 분류되지 않는다. 같은 세션에서
`skb03_atom_node_populate_runbook.md`의 실제 쓰기 가드를 제거하자 `exit 1`로 정확히 잡혔으므로
검출기 자체는 변별력이 있다.

즉 **이 런북의 [C] 가드는 사람이 쓴 것이고 기계가 지키지 않는다.** 이 런북을 고치는 사람은
그 가드를 CI가 지켜 준다고 가정하지 말 것. 어휘 공백의 상환은 `HARN-116`이 소유한다.

---

## 실행 결과 — 2026-09-19 (판정 기준: `origin/main` `412ccb71`)

> **이 회차는 2026-09-29 정정 *이전* 전제로 돌았다**(기본 좌석 anthropic · 두 좌석 대조 ·
> Anthropic API 사용 가능). 그 판정은 그 시점의 사실로 유효하며 고치지 않는다 — 특히
> `SEAT_DEFAULT=AnthropicProvider`는 당시의 정답이었다. 컷오버 뒤의 회차는 위 갱신판 [A]~[C]로 돈다.

Kiki가 Phaiakes9에서 `[A]`→`[B]`→`[C]`를 실행했다. worktree 자가검증 출력이
`412ccb71 (HEAD, origin/main, origin/HEAD)`으로 찍혀 실행 코드의 출처가 main임이 고정됐다.

- `[A]` `SEAT_OK=True` — `FROM_TREE=True` · `SEAT_DEFAULT=AnthropicProvider` ·
  `SEAT_WITH_ENV=OpenRouterProvider` · `HAS_OBSERVATION=True`.
- `[B]` `CHECK_EXIT=0` · `CONFIGURED=True` · `PROVIDERS=('deepinfra',)` ·
  `JURISDICTION=Jurisdiction.US` · `ERROR=None`.
- `[C]` `OPENROUTER_EXIT=0` · `ANTHROPIC_EXIT=0` · 좌석당 5호출.

### 판정 4축 — 전건 성립

| 축 | openrouter | anthropic | 판정 |
|---|---|---|---|
| ⓐ `state` | `all_on_selected_seat` | `all_on_selected_seat` | 통과 (`not_measured` 아님) |
| ⓑ `comparable` | 5 | 5 | 통과 (> 0) |
| ⓒ `served_models` | `deepseek/deepseek-v4.1-flash`: 5 | `claude-sonnet-4-6`: 5 | 통과 (서로 다름) |
| ⓓ `retries_measured` | 5 (`retries_total` 0) | 0 (`retries_total` `null`) | 통과 (ⓓ는 openrouter 축) |

### 읽을 자리 — `differs=0`이 말하는 것

두 회차 모두 `differs: 0` · `differing_pairs: []`이고 `comparable: 5`다. 4절이 미리 갈라 둔
대로 이것은 **미관측이 아니라 실측 0**이며, 두 공급사 다 선언값과 **글자 그대로 같은 문자열**을
돌려준다는 뜻이다. 별칭→버전 해소가 일어나지 않았다.

이것은 사전 가정의 반증이기도 하다 — 이 런북의 추출기를 검증할 때 쓴 픽스처는 Anthropic이
날짜 붙은 ID(`claude-sonnet-4-6-20260219` 형태)를 돌려줄 것으로 가정했는데 실측은 핀 문자열
그대로였다. 그러므로 **지금 이 두 좌석에서는 선언 축과 관측 축이 같은 값을 낸다.** EOS-112가
두 축을 분리해 둔 가치는 *지금 차이가 있어서*가 아니라 **차이가 생겼을 때 보이게 하려고**다 —
두 값을 한 필드로 합쳤다면 provider가 조용히 다른 모델로 바꾼 날 그 사실이 '일치'로 위장된다.

### 부수 관측 — 창 오염이 실제로 막혔다

`[A]`의 `PRE_SHELL_VAR=openrouter`가 찍혔다. 즉 실행 창에 이전 값이 남아 있었다. 그럼에도
`SEAT_DEFAULT=AnthropicProvider`가 정확히 나온 것은 이 블록이 부재를 *가정*하지 않고 자식
프로세스에서 `os.environ.pop`으로 **만들어** 재기 때문이다 — 2026-09-18에 실제로 한 번 겪은
오독 경로가 설계대로 차단됐다. `PRE_USER_VAR`는 비어 있어 User 환경변수 영구 오염은 없다.

### 닫힌 것

`EOS-111`(PR #1208)·`EOS-112`(PR #1211) 본문의 '정직한 공백'(라이브 미확인)이 이 회차로
닫힌다. 좌석 신호의 라이브 작동 비율은 더 이상 0이 아니다.
