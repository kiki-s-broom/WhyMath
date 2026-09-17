# ARCH-55 프로바이더 3축 강등전 — 소표본 스모크 런북

> 이 문서는 **Kiki가 Phaiakes9에서 직접 실행**하는 절차다. 본 강등전(40+40) 전에
> **하네스가 라이브에서 실제로 도는지**만 20문항으로 확인한다.

---

## 1. 과제 명칭

DeepSeek 경로 강등전 하네스 **라이브 스모크 실행** (ARCH-55 acceptance ① 선행 확인)

## 2. 목적

`provider_accuracy_battle` 하네스가 실제 클라우드 호출에서 **도는지**를 먼저 본다.
본 강등전(arm당 80문항 × 최대 3 arm)을 바로 돌리면, 도구 결함 하나에 회차 전체가
날아간다 — 2026-08-22 Phaiakes9 성능 진단에서 측정 4회가 *측정이 아닌 이유로* 공전한
전례가 있다. 여기서 확인할 것은 정확도 수치가 아니라 **파이프라인의 생존**이다:

- 키가 실제로 읽히는가(특히 `WHYMATH_ANTHROPIC_API_KEY` — DeepSeek 키와 달리 이 머신에
  등록돼 있는지 아직 실측되지 않았다)
- 라우터가 `CLOUD_MID`를 내고 관할 게이트를 통과하는가
- 회차별 증거가 `--audit-out`에 실제로 쌓이는가
- 피크/오프피크 라벨과 토큰 수가 응답에서 나오는가

결과는 ARCH-55 판정문과 MEMORY 결정 로그의 근거가 된다.

## 3. 구체적 절차

블록 [A] → [B] → [C] 순서로 **하나씩** 붙여넣는다. 각 블록은 판정값을 출력하고 끝난다.

| 블록 | 하는 일 | 예상 소요 |
|---|---|---|
| [A] | 별도 워크트리 생성 + 실행할 코드의 커밋 확인 | 10초 이내 |
| [B] | 호출 **없이** arm별 준비 상태(키·허용목록)만 판정 | 5초 이내 |
| [C] | 준비된 arm만 20문항씩 실제 호출 | arm당 1~3분 |

[A]는 Kiki의 평소 작업 사본을 **건드리지 않는다** — `git worktree`로 별도 폴더를 만들어
그 안의 코드를 실행하고, 원래 클론의 브랜치·미커밋 변경은 그대로 둔다(다른 세션이 같은
클론을 쓰고 있다).

## 4. 성공 기준

- **[A]**: 마지막 줄에 커밋 한 줄이 보이고 그 메시지에 `ARCH-55`가 들어 있다.
  안 보이면 fetch가 실패한 것 → [A]를 다시 실행한다.
- **[B]**: `[준비] OK   deepseek` 가 보인다. `CHECK_EXIT=0`이면 요청한 arm이 전부 호출
  가능, `CHECK_EXIT=2`면 하나 이상 미비이며 **어느 것이 왜** 미비인지 같은 화면에 적힌다.
  미비여도 실패가 아니다 — 그것을 알아내는 것이 [B]의 일이다(호출은 0건).
- **[C]**: `SMOKE_EXIT=0` + arm별 표(검출 하한·오경보 상한·지연·토큰)가 출력된다.
  `WRITE_REFUSED=True`가 보이면 **호출을 하나도 하지 않고 거부한 것**이며, 같은 줄에
  어느 조건이 False였는지 적힌다 → 그 줄을 그대로 회신해 주십시오.
  회차가 일부 `unresolved`로 나오는 것은 정상 출력이다(그 숫자 자체가 증거다).

## 5. 실행 환경

- 머신: **Phaiakes9** (= 평소 쓰는 이 PC). 별도 접속 불요.
- 시스템: **Windows PowerShell**
- 작업 디렉터리: `C:\Users\kiki\Desktop\__AI\WhyMath`
- 선행 조건: 인터넷 연결. Docker·DB·서버 **불요**(이 하네스는 DB를 쓰지 않는다).
- 비용: [C]는 arm당 20회 호출한다. 카탈로그 단가 기준 Anthropic arm 약 US$0.13,
  DeepSeek arm 약 US$0.01 수준 — 청구서로 검증한 값이 아니라 단가 곱셈이다.

## 6. 창 구분

**새 PowerShell 창 1개**에서 [A]·[B]·[C]를 순서대로 실행한다. 서버를 띄우지 않으므로
이 창은 계속 조작해도 된다. 진행 중 다른 창은 필요 없다.

---

## [A] 워크트리 준비 + 실행할 커밋 확인

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/friendly-wright-x6wp2y
if (Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-arch55) { git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-arch55 } else { "기존 워크트리 없음 — 새로 만듭니다" }
git worktree add --detach C:\Users\kiki\Desktop\__AI\WhyMath-arch55 origin/claude/friendly-wright-x6wp2y
git -C C:\Users\kiki\Desktop\__AI\WhyMath-arch55 log -1 --oneline
```

## [B] 준비 판정 (호출 0건)

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system — .venv가 없어 시스템 python으로 진행합니다" }
& $Py -c "import whymath_backend.harness.provider_accuracy_battle as m; print('SOURCE=' + m.__file__)"
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm anthropic --arm deepseek --check-only
"CHECK_EXIT=$LASTEXITCODE"
```

## [C] 소표본 실측 (준비된 arm만 · 20문항)

이 블록은 [B]의 출력을 **스스로 다시 계산해** 판정한다. [B]를 건너뛰었거나 [B]가 미비를
냈어도 안전하다 — 조건이 맞지 않으면 호출을 하나도 하지 않고 `WRITE_REFUSED`를 낸다.

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$Source = (& $Py -c "import whymath_backend.harness.provider_accuracy_battle as m; print(m.__file__)")
$FromWorktree = ($Source -like "*WhyMath-arch55*")
"FROM_WORKTREE=$FromWorktree ($Source)"
$Arms = @()
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm anthropic --check-only | Out-Null
if ($LASTEXITCODE -eq 0) { $Arms += "--arm"; $Arms += "anthropic" } else { "ARM_SKIP=anthropic (키 미설정 — 이 arm 없이 진행합니다)" }
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm deepseek --check-only | Out-Null
if ($LASTEXITCODE -eq 0) { $Arms += "--arm"; $Arms += "deepseek" } else { "ARM_SKIP=deepseek (키 미설정 — 이 arm 없이 진행합니다)" }
"ARMS=$($Arms -join ' ')"
if ($FromWorktree -and $Arms.Count -gt 0) { & $Py -m whymath_backend.harness.provider_accuracy_battle @Arms --n-defective 10 --n-clean 10 --concurrency 2 --audit-out C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-smoke; "SMOKE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — FromWorktree=$FromWorktree ArmCount=$($Arms.Count) · 호출 0건" }
```

## [D] 회신 요청

[A]~[C]의 출력을 **통째로** 붙여넣어 회신해 주십시오. 특히 다음 줄이 판정에 쓰입니다:

- `SOURCE=` (어느 트리의 코드가 돌았는가)
- `[준비]` 로 시작하는 줄 전부
- `CHECK_EXIT=` · `SMOKE_EXIT=` 또는 `WRITE_REFUSED=`
- arm별 결과 표

## 스모크 실측 결과 (2026-09-17 · `0d0bc934`)

| 축 | anthropic (baseline) | deepseek |
|---|---|---|
| 검출 | 6/10 (Wilson 하한 0.3516) | 8/10 (하한 0.5408) |
| 오경보 | 1/10 (Wilson 상한 0.3477) | 3/10 (상한 0.5583) |
| 지연 p50 | 2,988ms | 6,523ms |
| 지연 p95 | 12,459ms | 39,148ms |
| 입력 토큰(20회) | 11,461 | 9,298 |
| 출력 토큰(20회) | 4,177 | **39,697** |
| 집계 제외 | 0건 | 0건 |

`SMOKE_EXIT=0` · `FROM_WORKTREE=True` · 전 회차 `off_peak`.

**파이프라인은 생존했다** — 40회 호출 전건이 라우팅·관할 게이트를 통과했고 집계 제외 0건이다.
정확도 수치는 n=10이라 Wilson 구간이 0.35~0.56로 벌어져 **판정에 쓸 수 없다**(그래서 본
강등전이 필요하다).

스모크가 잡아낸 것: **DeepSeek의 출력 토큰이 9.5배다.** 추론 토큰이 과금에 포함되므로
"입력·출력 단가가 싸다"만으로 계산한 비용 우위는 이 배율만큼 깎인다. ARCH-49에서 계산한
12.4배 우위는 **양쪽 토큰 수가 비슷하다는 가정** 위에 있었고, 그 가정이 틀렸다.

## [F] 본 강등전 (스모크가 통과한 뒤)

arm당 80문항. `--seed`는 스모크와 다른 값을 써서 시험지를 겹치지 않게 한다.
`--concurrency 2`는 그대로 둔다(높이면 공급사 rate limit이 지연 측정을 오염시킨다).

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$Source = (& $Py -c "import whymath_backend.harness.provider_accuracy_battle as m; print(m.__file__)")
$FromWorktree = ($Source -like "*WhyMath-arch55*")
"FROM_WORKTREE=$FromWorktree ($Source)"
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm anthropic --arm deepseek --check-only | Out-Null
$Ready = ($LASTEXITCODE -eq 0)
"READY=$Ready"
if ($FromWorktree -and $Ready) { & $Py -m whymath_backend.harness.provider_accuracy_battle --arm anthropic --arm deepseek --n-defective 40 --n-clean 40 --seed 20260917 --concurrency 2 --audit-out C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-full; "FULL_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — FromWorktree=$FromWorktree Ready=$Ready · 호출 0건" }
```

소요: arm당 약 8~20분(스모크 지연 p50 기준 외삽). 비용은 스모크의 4배 규모.

### 피크 구간을 함께 받으려면

DeepSeek 공식 API의 피크 구간은 UTC 01–04시·06–10시, **한국시간 10–13시·15–19시**(주말은
항상 오프피크)다. 위 [F]를 그 시간대에 **한 번 더** 돌리면 acceptance ②(피크/오프피크 분리
집계)의 양쪽 표본이 모인다. 오프피크만으로도 정확도·지연 판정은 성립하지만, 단가가 정확히
2배 차이라 비용 축은 양쪽이 있어야 말이 된다.

## 본 강등전 실측 결과 (2026-09-17 · `2f9b9457` · off_peak)

| 축 | anthropic (baseline) | deepseek |
|---|---|---|
| 검출 | 23/40 (Wilson 하한 0.4457) | 33/40 (하한 0.7066) |
| 오경보 | 1/40 (Wilson 상한 0.1046) | 8/40 (상한 0.3215) |
| 지연 p50 | 2,804.3ms | 4,243.4ms |
| 지연 p95 | 9,411.4ms | 29,548.6ms |
| 입력 토큰(80회) | 45,963 | 37,335 |
| 출력 토큰(80회) | 16,243 | **149,174** |
| 집계 제외 | 0건 | 0건 |

`FULL_EXIT=0` · 160회 호출 전건 통과 · 전 회차 `off_peak`(피크 표본 미수집).

## [H] OpenRouter arm (acceptance ① 2종 중 나머지 · ③ 공급사 고정 확인)

acceptance ①은 DeepSeek 경로를 **2종** 요구한다 — 공식 API와 OpenRouter 경유. 위 [F]는
공식 API만 돌렸다. ③(공급사·양자화 고정 확인)은 **OpenRouter arm에만 존재하는 축**이라
이 블록 없이는 ①③ 둘 다 미충족이다.

`--seed 20260917`을 [F]와 **같은 값으로** 둔다 — 같은 시험지를 풀어야 나란히 놓을 수 있다.
`--audit-out`도 같은 폴더라 `openrouter.ndjson`이 옆에 쌓이고 [G] 재생이 3개 arm을 함께 읽는다.

**먼저 slug 확인**(모델 이름이 틀리면 전 회차가 호출 실패로 끝난다 — ARCH-49에서 실제로
틀렸던 축이다):

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
& $Py -m whymath_backend.harness.openrouter_endpoints_probe --search deepseek
"SEARCH_EXIT=$LASTEXITCODE"
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm openrouter --check-only
"CHECK_EXIT=$LASTEXITCODE"
```

**그다음 소표본 10+10**으로 공급사 고정이 실제로 되는지부터 본다(`집계 제외`가 0이어야
한다 — 0이 아니면 허용목록 1곳이 응답하지 않은 것이고, 그 상태로 80회를 돌리면 잡음을 잰다):

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$Source = (& $Py -c "import whymath_backend.harness.provider_accuracy_battle as m; print(m.__file__)")
$FromWorktree = ($Source -like "*WhyMath-arch55*")
"FROM_WORKTREE=$FromWorktree ($Source)"
& $Py -m whymath_backend.harness.provider_accuracy_battle --arm openrouter --check-only | Out-Null
$Ready = ($LASTEXITCODE -eq 0)
"READY=$Ready"
if ($FromWorktree -and $Ready) { & $Py -m whymath_backend.harness.provider_accuracy_battle --arm openrouter --n-defective 10 --n-clean 10 --seed 20260708 --concurrency 2 --expected-provider deepinfra --audit-out C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-or-smoke; "OR_SMOKE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — FromWorktree=$FromWorktree Ready=$Ready · 호출 0건" }
```

**소표본에서 `집계 제외 0건`을 확인한 뒤** 본 회차:

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
$Source = (& $Py -c "import whymath_backend.harness.provider_accuracy_battle as m; print(m.__file__)")
$FromWorktree = ($Source -like "*WhyMath-arch55*")
$SmokeClean = (Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-or-smoke\openrouter.ndjson)
"FROM_WORKTREE=$FromWorktree SMOKE_EVIDENCE=$SmokeClean"
if ($FromWorktree -and $SmokeClean) { & $Py -m whymath_backend.harness.provider_accuracy_battle --arm openrouter --n-defective 40 --n-clean 40 --seed 20260917 --concurrency 2 --expected-provider deepinfra --audit-out C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-full; "OR_FULL_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — FromWorktree=$FromWorktree SmokeEvidence=$SmokeClean · 호출 0건" }
```


## [G] 단가 재환산 (호출 0건 · 비용 축)

단가를 확인한 뒤 **같은 회차 증거를 다시 읽어** USD로 환산한다. 라이브를 다시 돌리면 그건
새 측정이라(시험지·시각·모델이 다르다) 위 표와 나란히 놓을 수 없다.

아래 블록의 단가는 **주입값**이며 출처 문자열이 리포트에 그대로 찍힌다. 두 단가 모두
1차 자료로 확인됐다:

- **Anthropic `claude-sonnet-4-6`** = $3 / $15 per 1M (입력 / 출력)
- **DeepSeek Flash 계열** = 오프피크 $0.15(입력 캐시 미스) / $0.60(출력) · 캐시 히트 입력
  $0.003 · **피크는 정확히 2배**($0.30 / $1.20). 출처 = DeepSeek 플랫폼 Usage 페이지의
  공급사 공지 배너(2026-09-10 12:00 베이징 시각 발효 · 2026-09-17 확인)

**청구서 교차검증(2026-09-17)**: 이 계정의 `deepseek-flash` 30일 사용량이
**101 requests · 236,012 tokens · $0.11 USD**로 찍혔고, 이는 우리가 부른 라이브 프로브 1회
+ 스모크 20회 + 본 강등전 80회 = **101회**와 토큰 합계(508 + 48,995 + 186,509 =
**236,012**)에 **정확히 일치**한다. 즉 아래 환산은 단가 곱셈이면서 동시에 **청구 총액으로
검산된** 값이다(역산: 입력 46,721 x $0.15 + 출력 189,291 x $0.60 = $0.121 → 청구 $0.11,
차액은 입력 캐시 히트분).

```powershell
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-arch55\src\backend"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
if (Test-Path $Py) { "PY=venv" } else { $Py = "python"; "PY=system" }
& $Py -m whymath_backend.harness.provider_accuracy_battle --replay C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-full --arm anthropic --arm deepseek --price anthropic=3/15 --price deepseek:off_peak=0.15/0.60 --price deepseek:peak=0.30/1.20 --price-source "Anthropic 공식 단가표 / DeepSeek 플랫폼 Usage 공지 배너 2026-09-17 - 청구서 101req 236012tok 0.11USD 교차검증"
"REPLAY_EXIT=$LASTEXITCODE"
```


## [E] 정리 (스모크가 끝난 뒤에만)

본 강등전까지 마친 다음 실행한다. 워크트리만 지우며 커밋·브랜치는 건드리지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-arch55
git worktree list
```
