# ARCH-55 프로바이더 3축 강등전 — 소표본 스모크 런북

> 이 문서는 **Kiki가 Phaiakes9에서 직접 실행**하는 절차다. 본 강등전(40+40) 전에
> **하네스가 라이브에서 실제로 도는지**만 20문항으로 확인한다.

---

> **범위 정정 (2026-09-17 · Kiki)** — 채택 대상 경로는 **OpenRouter**다. DeepSeek 공식 API는
> 우리가 쓰기로 한 경로가 아니다. 그래서 요금 구간(peak/off_peak) 축은 **무의미**하고
> (2배 단가는 공식 API에만 있는 개념이며 OpenRouter는 평평하다), 단일 모델의 결함 검출률로
> 채택을 가르지도 않는다 — 이것은 개발 단계 오케스트레이션이고 오류 검출은 완성 후
> **다축 오케스트레이션**이 담당한다.
>
> 판정 기준은 4개: (a) 도는가 (b) 공급사 고정 (c) 회당 비용 (d) 지연·가용성.
> 아래 [A]~[G]의 공식 API arm 기록은 **배경 대조**로만 남긴다. 실제 판정은 **[H]**다.



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

### 1회차 실측 (2026-09-17 · `de28e842` · 재시도 배선 이전)

`OR_EXIT=0` · 20회 중 **14회 성공 / 6회 429 실패(30%)**.

| 축 | 값 |
|---|---|
| 공급사 고정 | **성립** — 불일치 0건(집계 제외 6건은 전부 호출 실패) |
| 실패 원인 | `429 engine_overloaded` · `limit_source=upstream_provider_shared_pool` · `is_byok=false` |
| 지연 p50 / p95 | 14,044ms / **138,420ms** |
| 토큰 (14회) | 입력 6,330 / 출력 8,873 → 회당 452 / 634 |

관측: 같은 시험지인데 **출력 토큰이 공식 API의 1/3**이다(634 vs 1,985). 입력은 거의 같으므로
(452 vs 465) 같은 문제를 푼 것은 맞고 차이는 추론 쪽이다. 셋 중 하나이며 아직 미확정 —
ⓐ 다른 모델/설정 ⓑ deepinfra가 추론 길이를 제한 ⓒ OpenRouter가 추론 토큰을 usage에 안 실음.
ⓒ면 실제 과금이 더 크므로 **OpenRouter Activity의 실제 청구액과 대조해야 확정된다.**

### 재시도 배선 이후 재측정

429는 "다시 걸라"는 뜻인데 1회차의 전송기에는 재시도가 없었다. 그래서 그 30%는 공급사의
성질이 아니라 **우리 전송기의 성질**을 잰 숫자다. 지수 백오프(429·5xx · `Retry-After` 우선)를
배선했고, 재시도 횟수는 회차마다 기록돼 리포트에 뜬다(가려지지 않는다).

`--concurrency 1`을 쓴다 — 1회차의 `--concurrency 2`는 세마포어만 있고 실행은 직렬이던
결함 때문에 **실제로는 1이었다**(그 결함도 같이 고쳤다). 변수를 하나만 바꾸려면 1이 맞다.

**소표본 10+10**으로 공급사 고정과 실패율을 다시 본다:

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
if ($FromWorktree -and $Ready) { & $Py -m whymath_backend.harness.provider_accuracy_battle --arm openrouter --n-defective 10 --n-clean 10 --seed 20260708 --concurrency 1 --expected-provider deepinfra --audit-out C:\Users\kiki\Desktop\__AI\WhyMath-arch55\data\audit\arch-55-or-retry; "OR_RETRY_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — FromWorktree=$FromWorktree Ready=$Ready · 호출 0건" }
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


### 2회차 실측 — 재시도 배선 이후 (2026-09-18 · `1cac94d2` · `--concurrency 1`)

| 축 | 1회차(재시도 없음) | 2회차(재시도 3회) |
|---|---|---|
| 성공 | 14/20 (70%) | **17/20 (85%)** |
| 실패 | 6건 429 | **3건 429**(재시도 3회 소진) |
| 재시도 | — | **12회 / 회차 8건** |
| 지연 p50 | 14,044ms | **40,275ms** |
| 지연 p95 | 138,420ms | **332,447ms** |
| 토큰(성공 회차) | 452 / 634 | **460 / 1,518** |

`OR_RETRY_EXIT=0` · 공급사 불일치 0건(고정 성립) · 검출 8/10 · 오경보 3/7.

**읽는 법 세 가지.**

① **1발 성공률은 오히려 내려갔다.** 재시도를 겪은 8건 중 3건이 끝내 실패했으므로 재시도
없이 성공한 것은 12/20 = **60%**다(1회차 70%). 이번 상류 상태가 더 나빴고, 그 조건에서
재시도가 70%→85%를 만들었다 — 재시도 자체는 제대로 작동했다.

② **3회를 다 쓰고도 15%가 죽는다.** 일시적 스파이크가 아니라 **지속적 과부하**다. 재시도를
5회로 늘리면? p95가 이미 5분 32초인데 10분을 넘긴다. **재시도로 풀 문제가 아니다.**

③ **p50 40초는 재시도가 숨기고 있던 진짜 비용이다.** 배치 저작이라도 문항 하나에 40초면
100문항에 1시간이 넘는다.

**출력 토큰 미스터리에 새 데이터**: 1회차 회당 634 → 2회차 **1,518**(2.4배). 같은 시험지·
같은 모델이다. 공식 API의 1,985에 훨씬 가까워졌으므로, 앞서 세운 가설 ⓒ(OpenRouter가 추론
토큰을 usage에 안 실음)는 **약해진다** — 안 싣는다면 회차마다 이렇게 흔들릴 이유가 없다.
**회차별 추론 길이 변동**이 더 그럴듯하고 1회차의 634가 이상값이었을 가능성이 크다. 표본이
14·17로 작아 확정은 아니며, 청구액 대조가 여전히 필요하다.

### 판정 기준 4개 (2026-09-18 시점)

| | 결과 |
|---|---|
| (a) 도는가 | **조건부** — 재시도 포함 85% · 1발 60% |
| (b) 공급사 고정 | **성립** — 불일치 0건 (1·2회차 모두) |
| (c) 회당 비용 | **$0.00098** → Sonnet $0.004767 대비 **4.9배 저렴** |
| (d) 지연·가용성 | **불합격** — p50 40초 · p95 332초 · 15% 실패 |

**(c)는 좋고 (d)는 현 구성으로 못 쓴다.** 원인은 모델이 아니라 **접속 구조**다 — OpenRouter가
오류 본문에서 직접 말한다: `is_byok: false` · `limit_source: upstream_provider_shared_pool`.
공유 풀이라 다른 사용자와 rate limit을 나눈다.

선택지 3개(Kiki 결정):
1. **BYOK** — deepinfra 계정 키를 OpenRouter integrations에 등록해 우리 몫의 rate limit을
   쓴다. 오류 메시지가 1순위로 권하는 방법이고 데이터가 이것을 지목한다.
2. **공급사 교체** — 미확인 9곳 중 하나. 관할·데이터 정책·양자화 3축을 다시 확인해야 한다.
3. **현 구성 유지** — 개발 단계 오케스트레이션에 p50 40초가 감당 가능하다면.


### 3회차 — Baseten 교체 (2026-09-18 · `6d4c9414` · **[peak] 구간**)

| | deepinfra 1회차 | deepinfra 2회차 | **baseten** |
|---|---|---|---|
| 구간 라벨 | off_peak | off_peak | **peak** |
| 실패 | 6/20 | 3/20 | **8/20** |
| 재시도 | — | 12회 / 8건 | **28회 / 17건(85%)** |
| 지연 p50 | 14,044ms | 40,275ms | **5,348ms** |
| 지연 p95 | 138,420ms | 332,447ms | **23,151ms** |

`OR_BASETEN_EXIT=0` · 집계 제외 8건(전부 호출 실패).

#### 결정적 발견 — 429는 공급사의 성질이 아니다

Baseten 오류 본문: `provider_name: "BaseTen"` · **`is_byok: false`** ·
**`limit_source: upstream_provider_shared_pool`**.

deepinfra와 **글자 그대로 같은** `limit_source`·`is_byok`다. 공급사를 바꿔도 같은 공유 풀을
통과해야 하므로 **공급사 교체로는 벗어날 수 없다.** 위 [판정 기준] 절의 선택지 ②(공급사
교체)는 이 실측으로 **기각**된다.

#### 이 세션이 틀린 지점 (기록)

공급사 선택의 근거로 OpenRouter 표의 `Uptime 100.00%`를 썼는데, 그 열은 **"그 공급사
엔드포인트가 살아 있었는가"**를 재지 **"우리가 공유 풀을 뚫고 거기까지 갔는가"**를 재지
않는다. 다른 것을 재는 지표를 우리 문제의 해답으로 읽었다 — 6곳을 비교한 것 자체가 잘못된
축이었다. 오류 본문이 두 번(deepinfra·baseten) 같은 말을 했는데도 공급사 교체를 먼저 권했다.

#### 이 회차를 deepinfra와 나란히 놓을 수 없는 이유

구간 라벨이 **`[peak]`**다(이전 둘은 `off_peak`). 라벨 자체는 DeepSeek 공식 API 시간대라
OpenRouter 과금과 무관하지만, **실행 시각이 달랐다**는 것은 말해 준다 — 이번은 아시아 낮,
이전 둘은 저녁·밤이다. 공유 풀이 훨씬 붐비는 시간대이므로 "baseten이 더 나쁘다"는 이
데이터로 말할 수 없다. 교란을 없애려면 **같은 시간대에 deepinfra를 다시 재야 한다**
(환경변수 `WHYMATH_OPENROUTER_ALLOWED_PROVIDERS`로 한 창에서만 바꿔 20회 · 약 $0.02).

#### 교란을 뚫고 살아남은 신호

**더 붐비는 시간대인데도 지연이 훨씬 낫다** — p50 5.3초(vs 40.3초) · p95 23초(vs 332초).
대기열을 뚫고 나면 Baseten의 서빙 자체는 빠르다. 교란 방향과 **반대**라 실재 신호일
가능성이 높다.

#### 남은 결론

**BYOK이 유일한 구조적 해답이다.** 공급사 둘 다 같은 메시지로 그것을 1순위로 권한다
(`Please retry shortly, or add your own key to accumulate your rate limits`). 어느 쪽 계정을
만들지는 위 동시간대 A/B가 정한다 — 지연 우위가 baseten으로 확정되면 baseten, 비슷하면
2배 싼 deepinfra다. 기본값은 A/B 전까지 그대로 두며, **틀린 근거로 정한 값을 교란된
데이터로 또 뒤집지 않는다.**


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
