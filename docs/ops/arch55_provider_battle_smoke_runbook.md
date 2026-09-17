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

## [E] 정리 (스모크가 끝난 뒤에만)

본 강등전까지 마친 다음 실행한다. 워크트리만 지우며 커밋·브랜치는 건드리지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-arch55
git worktree list
```
