# EOS-118 — 좌석 작동 신호 라이브 재확인 (Kiki 실행)

> `EOS-111`(선언 축)·`EOS-112`(관측 축)가 만든 좌석 신호가 **실제로 도는 회차에서 좌석을
> 말하는지** 확인하는 관측 회차다. 새로 배선할 코드는 없다 — 신호는 이미 `main`에 있고,
> 이 런북은 그 신호를 **잡아서 회신 가능한 형태로 꺼내는** 절차다.
>
> **선행 런북과의 관계**: `docs/ops/arch57_authoring_openrouter_runbook.md`(ARCH-57)와
> [A][B]는 사실상 같다. 다른 것은 [C]다 — ARCH-57판은 종료 코드와 산출 행 수만 회신받게
> 돼 있어 **요약 JSON(stdout)을 아무 데도 담지 않는다**. `cloud_seat` 블록은 바로 그
> stdout에만 실리므로(`problem_corpus_accumulate.py`의 `json.dump(payload, sys.stdout)`),
> ARCH-57판을 그대로 돌리면 이 태스크가 요구하는 회신을 **만들 수 없다**. 이 런북의 [C]가
> 그 stdout을 파일로 받아 필요한 필드를 꺼낸다.

## 1. 과제 명칭

저작 배치를 **두 좌석으로 각 1회**(OpenRouter / Anthropic 대조군) 돌리고, 각 회차 요약의
`cloud_seat` 블록을 꺼내 회신한다.

## 2. 목적

지금까지 확인된 것은 ① 좌석 신호의 **코드 계약**(EOS-111 뮤테이션 5종·EOS-112 14종 동결)
② 컨테이너에서 좌석 객체가 바뀌는 것까지다. **실제 LLM 호출이 나가고 그 회차의 신호가
좌석을 제대로 말하는지는 아무도 본 적이 없다** — 라이브 작동 비율이 0이다. CLAUDE.md
「작동 신호 없는 알고리즘 부착 금지」가 겨냥하는 형태이며, 이 회차가 그것을 닫는다.

결과는 `EOS-111`(PR #1208)·`EOS-112`(PR #1211) 본문의 '정직한 공백'(라이브 미확인)을
닫는 증적이 된다.

**이 회차는 상시 채택 결정이 아니다.** 수동 1회 관측이며, 게이트
`G-arch56-availability-trigger`의 발동 조건 ⓐ(학생 대면 또는 **상시 배치** 트래픽 투입)를
건드리지 않는다. 같은 명령을 스케줄에 올리는 순간 그쪽이 먼저다.

## 3. 구체적 절차

블록 3개. **[A]는 조회, [B]는 조회, [C]만 호출한다.**

- **[A] 좌석 왕복 + 신호 실재 확인** (약 20초) — 환경변수로 좌석이 바뀌는지, 없으면 기본으로
  돌아오는지 양방향으로 본다. 더해 이 트리의 요약 코드가 **관측 축(EOS-112)을 실제로 내는지**
  (`observation` 블록 유무)까지 본다. 호출 0건.
- **[B] 사전 점검** (약 10초) — 키·허용목록·관할이 맞는지 본다. 호출 0건.
- **[C] 두 좌석 회차 + 신호 추출** (5~25분) — OpenRouter 좌석으로 `--n 5`, 이어 Anthropic
  좌석으로 `--n 5`를 돌리고, **각 회차의 요약 stdout을 파일로 받아** `cloud_seat`에서 판정
  필드를 꺼내 화면에 낸다. [A][B]의 판정을 **스스로 다시 계산해** 조건이 어긋나면 호출을
  하나도 하지 않고 거부한다(HARN-106).

지연은 회차마다 크게 흔들린다 — ARCH-55 4회차 실측 p50 36.9초 / p95 212.6초. 좌석당
5문항이면 양쪽 합쳐 5~25분 사이 어디든 정상이다.

## 4. 성공 기준

**[A]**: `SEAT_OK=True`. 실패하면 같은 줄에 어느 항이 False였는지 적힌다. 특히
`HAS_OBSERVATION=False`면 트리의 코드가 EOS-112 이전 리비전이라는 뜻이니 그 줄을 회신한다.

**[B]**: `CHECK_EXIT=0` 그리고 `CONFIGURED=True`. 비-0이면 **어느 것이 왜** 미비인지 같은
화면에 적힌다 — 대개 `OPENROUTER_API_KEY` 미설정이다. 미비는 실패가 아니라 [C]를 하지 말라는
신호다.

**[C]**: 아래 네 축이 **함께** 성립해야 통과다. 하나라도 어긋나면 그것은 통과 실패가 아니라
**원인 규명 대상**이며, 그 회차도 그대로 회신한다(실패 회차 폐기 금지).

| 축 | 통과 조건 | 어긋나면 |
|---|---|---|
| ⓐ 선언 축 | `state`가 `not_measured`가 **아닐** 것 | 좌석 판정 자체가 정의되지 않은 회차 |
| ⓑ 관측 축 | `comparable`가 **0보다 클** 것 | 선언 축만 살고 관측 축이 죽은 상태 — EOS-111을 등재하게 만든 바로 그 형태 |
| ⓒ 변별력 | 두 회차의 `served_models`가 **서로 다를** 것 | 신호가 좌석을 구분 못 하는 것이며 ⓐ의 통과는 위장 |
| ⓓ 재시도 | **OpenRouter 회차**의 `retries_measured`가 0보다 클 것 | 계측 배선이 라이브에서 죽은 것 |

**ⓓ는 OpenRouter 회차에만 적용된다.** Anthropic 회차는 SDK가 자체 재시도하고 우리 전송기를
타지 않아 `retries_measured=0`·`retries_total=null`이 **정상**이다(`anthropic.py:216`이 그렇게
적고 있다). 두 회차에 같은 잣대를 대면 정상을 결함으로 읽는다.

**종료 코드가 비-0이어도 데이터는 있다.** 이 배치는 요약 JSON을 stdout에 쓴 **뒤에** 판정
코드를 돌려준다 — `1`=축적 0건 또는 카나리 차단, `2`=연속 무진전 알람. 즉 `EXIT=1`이
"측정 실패"를 뜻하지 않는다. 추출이 값을 내면 그 값이 실측이다.

실패 시 대처: 추출이 `EXTRACT_SKIPPED`를 내면 같은 줄의 사유와 `*.err.log`의 마지막 20줄을
회신한다. 429가 섞여 있어도 그 자체는 기대 범위다(재시도가 배선돼 있다) — 전건 실패인지
일부인지가 판정 대상이다.

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: 인터넷 연결. `OPENROUTER_API_KEY`·`ANTHROPIC_API_KEY` User 환경변수.
  Docker·DB·서버 **불요** — 이 배치는 DB를 쓰지 않는다(모듈에 DB import 0건).
- 비용: [C]는 좌석당 5회, 합 10회 호출한다. ARCH-55 실측 단가 기준 OpenRouter 약 US$0.006,
  Anthropic 약 US$0.024 — 청구서로 검증한 값이 아니라 회당 비용 곱셈이다.
- 전용 worktree를 쓴다: Kiki 클론은 여러 세션이 공유하는 단일 작업 사본이라 브랜치를 옮기면
  다른 세션의 실행이 깨진다. worktree는 원 작업 사본의 브랜치·미커밋 변경을 **하나도**
  건드리지 않는다.

## 6. 창 구분

**새 PowerShell 창 1개**에서 [A]→[B]→[C]를 순서대로 붙여넣는다. 장기 점유 프로세스가 없으므로
같은 창을 계속 쓴다. `$Py`·`$env:PYTHONPATH`를 [A]가 그 창에 설정하고 [C]가 물려받으므로
**창을 바꾸지 않는다**. [C]는 최대 25분 걸릴 수 있으니 끝날 때까지 그 창을 건드리지 않는다.

---

## [A] 좌석 왕복 + 신호 실재 확인 (호출 0건)

> **왜 기본값을 잴 때 자식 프로세스에서 변수를 제거하는가**: PowerShell 창은 앞서 붙여넣은
> 블록이 설정한 `$env:` 값을 계속 들고 있다. 그 상태에서 "설정 전에 재면 기본값"이라고
> 가정하면 재실행·부분 실행한 창에서는 **남아 있는 값을 기본값으로 오독한다**(2026-09-18
> 실측 — `SEAT_DEFAULT=OpenRouterProvider`가 나왔고 그것은 코드가 아니라 창의 상태였다).
> 그래서 부재를 *가정*하지 않고 자식 프로세스에서 `os.environ.pop`으로 **만들어** 잰다.
> `PRE_SHELL_VAR`·`PRE_USER_VAR`를 함께 찍는 것은 오염이 창 한정인지 User 환경변수에 영구
> 등록된 것인지 구분하기 위해서다.
>
> **`HAS_OBSERVATION`은 무엇을 가르는가**: 요약의 `cloud_seat.observation` 블록은 EOS-112가
> 신설했다. 그것이 없는 리비전에서 돌면 [C]의 추출이 `KeyError`로 죽는데, 그 실패는 원인이
> 멀리 있어 읽기 어렵다. 여기서 **빈 집계로 요약 함수를 한 번 불러** 키 유무를 직접 본다 —
> 호출 0건·네트워크 0건이면서 리비전을 변별한다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Ref = "origin/main"
$Tree = "C:\Users\kiki\Desktop\__AI\WhyMath-eos118"
git fetch origin
if (-not (Test-Path $Tree)) { git worktree add --detach $Tree $Ref } else { git -C $Tree fetch origin; git -C $Tree checkout --detach $Ref }
git -C $Tree log -1 --oneline
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$env:PYTHONPATH = "$Tree\src\backend"
$Source = (& $Py -c "import whymath_backend.l3.providers.factory as m; print(m.__file__)")
"SOURCE=$Source"
$FromTree = ($Source -like "*WhyMath-eos118*")
"FROM_TREE=$FromTree"
"PRE_SHELL_VAR=$($env:WHYMATH_CLOUD_PROVIDER)"
"PRE_USER_VAR=$([Environment]::GetEnvironmentVariable('WHYMATH_CLOUD_PROVIDER','User'))"
$Default = (& $Py -c "import os; os.environ.pop('WHYMATH_CLOUD_PROVIDER', None); from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_DEFAULT=$Default"
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
$WithEnv = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
"SEAT_WITH_ENV=$WithEnv"
$HasObs = (& $Py -c "from whymath_backend.harness.anchor_round_ledger import SeatTally, seat_operating_rates; b=seat_operating_rates(SeatTally(), selected_seat='anthropic', seat_model_pins=()); print('observation' in b and 'declared_vs_served' in b['observation'])")
"HAS_OBSERVATION=$HasObs"
$SeatOk = $FromTree -and ($WithEnv -eq "OpenRouterProvider") -and ($Default -eq "AnthropicProvider") -and ($HasObs -eq "True")
if ($SeatOk) { "SEAT_OK=True" } else { "SEAT_OK=False — FROM_TREE=$FromTree SEAT_DEFAULT=$Default SEAT_WITH_ENV=$WithEnv HAS_OBSERVATION=$HasObs. 넷 다 채워져야 합니다. 비어 있는 항이 있으면 위 worktree 생성 줄의 출력을 회신해 주십시오." }
```

**`SEAT_OK=True`를 눈으로 확인한 다음에만 [B]를 붙여넣으십시오.**

## [B] 사전 점검 (호출 0건)

```powershell
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
& $Py -c "from whymath_backend.l3.providers.openrouter import OpenRouterProvider; import asyncio; s=asyncio.run(OpenRouterProvider().check_status()); print(f'CONFIGURED={s.configured} PROVIDERS={s.allowed_providers} JURISDICTION={s.jurisdiction} ERROR={s.error}')"
"CHECK_EXIT=$LASTEXITCODE"
```

**`CHECK_EXIT=0`이고 `CONFIGURED=True`인 것을 눈으로 확인한 다음에만 [C]를 붙여넣으십시오.**

## [C] 두 좌석 회차 + 신호 추출 (호출 10건 — 좌석당 5)

이 블록은 [A][B]의 판정을 **스스로 다시 계산해** 실행을 거부한다. 앞을 건너뛰었거나 앞이
미비를 냈어도 안전하다 — 조건이 맞지 않으면 호출을 하나도 하지 않고 `WRITE_REFUSED` 한 줄을
낸다. 그 줄에 어느 조건이 False였는지 적힌다.

> **요약 stdout을 `cmd /c`로 받는 이유**: PowerShell 5.1은 자식 프로세스의 stdout을
> `[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 **디코딩한 뒤 재인코딩**한다.
> 이 요약 JSON에는 한국어 주석 문자열과 `—`·`·`가 들어 있어 그 왕복에서 바이트 경계가
> 어긋나고, 선행바이트가 뒤따르는 `"`를 삼켜 **JSON 구조 문자가 유실된다**(2026-09-14 실측 —
> `Out-File -Encoding utf8`로도 막히지 않는다. 이미 깨진 문자열을 성실히 UTF-8로 쓸 뿐이다).
> `cmd /c "... > 파일"`은 그 경유 자체를 없앤다.
>
> **`--subscription premium --budget-krw 5000`은 장식이 아니다**: 이 둘을 **함께** 주지
> 않으면 라우터가 LOCAL로 강제해(`problem_corpus_accumulate.py:583`) 클라우드 호출이 0건이
> 되고, 좌석 신호는 `not_measured`나 로컬 모델만 내놓는다. 하나만 줘도 같다.
>
> **대조군에서 좌석을 지우지 않고 `anthropic`으로 명시하는 이유**: 부재를 기본값으로
> 가정하는 것이 [A] 주석이 적은 오독 경로다. 명시하면 `selected_seat`가 회신에 그대로 찍혀
> 그 회차가 어느 좌석이었는지 나중에도 결정 가능하다.

```powershell
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutDir = "C:\Users\kiki\Desktop\__AI\WhyMath\.eos118-out"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Extract = "import json,sys;d=json.load(open(sys.argv[1],encoding='utf-8'))['cloud_seat'];o=d['observation'];v=o['declared_vs_served'];print(json.dumps({'selected_seat':d['selected_seat'],'state':d['state'],'seat_model_pins':d['seat_model_pins'],'calls_total':d['calls_total'],'calls_with_model_name':d['calls_with_model_name'],'declared_models':d['observed_models'],'served_models':o['observed_models'],'calls_with_served_model':o['calls_with_served_model'],'comparable':v['comparable'],'matched':v['matched'],'differs':v['differs'],'differing_pairs':v['differing_pairs'],'retries_measured':o['retries']['calls_with_retries_measured'],'retries_total':o['retries']['retries_total']},indent=2))"
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
$Seat = (& $Py -c "from whymath_backend.l3.providers.factory import build_cloud_provider; print(type(build_cloud_provider()).__name__)")
$Configured = (& $Py -c "from whymath_backend.l3.providers.openrouter import OpenRouterProvider; import asyncio; print(asyncio.run(OpenRouterProvider().check_status()).configured)")
"RECHECK_SEAT=$Seat RECHECK_CONFIGURED=$Configured"
if (($Seat -eq "OpenRouterProvider") -and ($Configured -eq "True")) {
  $OrOut = Join-Path $OutDir "openrouter-$Stamp.jsonl"
  $OrJson = Join-Path $OutDir "openrouter-$Stamp.summary.json"
  $OrLog = Join-Path $OutDir "openrouter-$Stamp.err.log"
  cmd /c "$Py -m whymath_backend.harness.problem_corpus_accumulate --out $OrOut --n 5 --subscription premium --budget-krw 5000 > $OrJson 2> $OrLog"
  "OPENROUTER_EXIT=$LASTEXITCODE"
  $env:WHYMATH_CLOUD_PROVIDER = "anthropic"
  $AnOut = Join-Path $OutDir "anthropic-$Stamp.jsonl"
  $AnJson = Join-Path $OutDir "anthropic-$Stamp.summary.json"
  $AnLog = Join-Path $OutDir "anthropic-$Stamp.err.log"
  cmd /c "$Py -m whymath_backend.harness.problem_corpus_accumulate --out $AnOut --n 5 --subscription premium --budget-krw 5000 > $AnJson 2> $AnLog"
  "ANTHROPIC_EXIT=$LASTEXITCODE"
  "===== CLOUD_SEAT / openrouter ====="
  if ((Test-Path $OrJson) -and ((Get-Item $OrJson).Length -gt 0)) { & $Py -c $Extract $OrJson } else { "EXTRACT_SKIPPED=openrouter — 요약 JSON이 없거나 비었습니다. $OrLog 마지막 20줄을 회신해 주십시오." }
  "===== CLOUD_SEAT / anthropic ====="
  if ((Test-Path $AnJson) -and ((Get-Item $AnJson).Length -gt 0)) { & $Py -c $Extract $AnJson } else { "EXTRACT_SKIPPED=anthropic — 요약 JSON이 없거나 비었습니다. $AnLog 마지막 20줄을 회신해 주십시오." }
  "OUT_DIR=$OutDir"
} else {
  "WRITE_REFUSED=True — 호출 0건. 좌석=$Seat (OpenRouterProvider여야 함) / 키구성=$Configured (True여야 함). [A][B]를 먼저 실행하고 그 출력을 회신해 주십시오."
}
```

## 회신해 주실 것

1. [A]의 `SEAT_OK` 줄 (False면 그 줄 전체)
2. [B]의 `CHECK_EXIT`·`CONFIGURED` 줄
3. [C]의 `OPENROUTER_EXIT`·`ANTHROPIC_EXIT` 줄
4. [C]의 **`===== CLOUD_SEAT / ... =====` 두 블록 전문** — 이것이 이 과제의 산출물이다

`WRITE_REFUSED`가 나왔다면 그 한 줄만 회신하면 된다.

산출물은 `.eos118-out\`에 남는다(gitignore 대상 폴더 — 커밋되지 않는다): 회차 JSONL,
요약 JSON 전문(`*.summary.json`), stderr 로그(`*.err.log`). 어긋남 쌍이나 로그 대조가
필요하면 그때 따로 요청드린다.

## 판정 후 처리 (세션 몫)

- `differs > 0`이면 `differing_pairs`를 보고 **별칭→버전 해소인지 진짜 폴백인지 사람이 판정**해
  그 판정을 `EOS-118` notes에 남긴다. 기계가 가르지 않기로 한 축이다(EOS-112 PR #1211).
- `differs == 0`이면 "이 공급사는 선언값과 같은 문자열을 돌려준다"는 **실측**이며 그것도
  기록한다. `comparable > 0`이 요구되므로 실측 0과 미관측은 구분된다.
- 네 축 중 어긋난 것이 있으면 그 실패가 이 태스크의 산출물이다. 원인을 실측 규명해 수정
  태스크로 분리 등재하고, 실패 회차를 폐기하지 않는다.

## 부록 — 이 런북의 사전 검증 (2026-09-19 · 판정 기준: main `ed298920`)

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
  정상이며, 4절 표의 ⓓ를 OpenRouter 회차에만 건다.
- **DB 불요** — 모듈에 DB·세션 import 0건.

### 이 런북에 대한 CI 가드의 실제 적용 범위 (정직한 공백)

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
