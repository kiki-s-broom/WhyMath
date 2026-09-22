# EOS-02 — 프롬프트 캐시 라이브 계측 회차 (Kiki 실행 런북 v2)

> 이 문서는 `EOS-02-prompt-cache-live-measurement` acceptance ①의 **실행 절차**이며
> 게이트 `G-eos02-prompt-cache-live-run`(`kind: human` · `assignee: kiki`)의 실행 대상이다.
>
> 세션은 도구를 만들지 않는다 — 계측은 `EOS-99`가 이미 배선했고(`prompt_cache` 리포트 블록),
> 여기서 필요한 것은 **실 Anthropic 키로 한 회차를 돌리는 것**뿐이다.
>
> **판정 기준: main `d10ba109`** (2026-09-21 재검증). v1은 main `1abf743b` 기준이었고
> 그 사이 저작 경로에 5개 커밋이 들어왔다(ARCH-57 좌석 셀렉터 · EOS-111/112 관측 · EOS-121 계측).
> 아래 §10에 v1에서 무엇을 고쳤는지 적었다 — **v1 블록을 그대로 쓰면 안 된다.**

---

## 1. 과제 명칭

프롬프트 캐시 **적중률 라이브 1회차 계측** — "켰다"와 "작동했다"를 실측으로 가른다.

## 2. 목적

`WHYMATH_ANTHROPIC_PROMPT_CACHING`은 현재 기본값 **False**다(`config.py`의 `anthropic_prompt_caching`).
켜는 판단을 하려면 적중률이 필요한데, **적중은 실 Anthropic 키로만 관측된다** — hermetic
테스트로는 정의되지 않는다(가짜 클라이언트는 캐시 토큰을 만들어 내지 않는다).

이 회차의 산출은 회차 대장의 `prompt_cache` 블록이며, 그것이 곧 `EOS-02` acceptance ③
(기본값 전환 여부)의 **유일한 판정 재료**다. 계측 없이 켜지 않는다.

## 3. 실행 환경

| | |
|---|---|
| 머신 | **Phaiakes9** = Kiki의 작업 PC 그 자체 (별도 접속·SSH 불요) |
| 시스템 | Windows PowerShell |
| 원 작업 디렉터리 | `C:\Users\kiki\Desktop\__AI\WhyMath` |
| 실행 디렉터리 | `C:\Users\kiki\Desktop\__AI\WhyMath-eos02` (**[A]가 worktree로 새로 만든다**) |
| 선행 조건 | Anthropic API 키가 등록돼 있을 것 ([B]가 값을 출력하지 않고 존재만 검사) |
| 불요 | Docker · DB · 서버 기동 · Ollama (이 회차는 클라우드 경로만 태우고 DB에 쓰지 않는다) |

**왜 worktree인가**: Kiki 클론은 여러 세션이 공유하는 **단일 작업 사본**이다. 다른 세션이
브랜치를 전환해 두거나 미커밋 변경을 남겨 둘 수 있으므로, 체크아웃을 옮기지 않고 별도
worktree에서 돈다. 원 클론의 브랜치·미커밋 변경을 **하나도 건드리지 않는다.**

## 4. 창 구분

**창은 하나면 된다.** 서버를 띄우지 않으므로 점유 창이 없다. 블록 [A]~[D]를 같은 PowerShell
창에서 순서대로 실행한다. 실행 후에도 그 창을 계속 써도 된다.

다만 [C]는 **3~8분** 걸린다. 도는 동안 그 창을 건드리지 말 것 — `Ctrl+C`는 복사가 아니라
**중단 신호**다.

## 5. 절차 개요와 예상 시간

| 블록 | 무엇 | 쓰기 | 예상 |
|---|---|---|---|
| [A] | worktree 생성 + 해시 자가검증 | worktree만 | 1분 |
| [B] | 환경·코드 출처·CLI 인자·**SDK 표면** 검사 | 없음(읽기) | 1분 |
| [C] | **회차 10호출** (쓰기 — 선행 판정을 재검사해 스스로 거부) | 산출 파일 | 3~8분 |
| [D] | 판정 재료 추출 (Python이 쓴 대장을 Python이 읽는다) | 없음(읽기) | 즉시 |

## 6. 성공 기준

**판정은 exit code가 아니라 `prompt_cache` 블록으로 한다.** 이 CLI의 exit code는 *코퍼스 수용
여부*를 말하지 캐시 계측 성패를 말하지 않는다(코드 실측 main `d10ba109`: 리포트 JSON은 exit
분기 **이전**에 stdout으로 나간다 — `problem_corpus_accumulate.py` L1445, exit 분기는 L1454 이후).

- `exit 0` = 신규 수용 ≥1 · `exit 1` = 이번 회차 수용 0 또는 배치 중단 · `exit 2` = 연속 무진전 알람
- **셋 중 무엇이든 `prompt_cache` 블록은 남는다.** 캐시 계측 관점에서 exit 1·2는 실패가 아니다.

### 1차 관문 — 측정이 됐는가

`calls_with_cache_telemetry > 0` 이어야 ①이 성립한다. **0이면 적중 0%가 아니라 미측정**이다
(클라우드로 안 나갔다는 뜻). 그때는 적중률을 읽지 말고 [B]의 `READY` 줄로 돌아간다.

### 2차 — `state` 어휘 6종 (코드 실측 `anchor_round_ledger.prompt_cache_rates`)

| `state` | 의미 | 다음 |
|---|---|---|
| `enabled_working` | 켰고 적중 있음 | `hit_rate`가 (n-1)/n에 근접하면 정상 → acceptance ③ 판단으로 |
| `enabled_not_working` | **켰는데 적중 0%** | 이 태스크가 존재하는 이유 — 아래 §7 원인 후보 2종 |
| `not_applicable` | 캐시 텔레메트리 0건 | **미측정.** 클라우드 미도달 — 회차를 다시 돌린다 |
| `unmeasured` | 텔레메트리는 있는데 프롬프트 토큰 합이 0 | 분모 없음 — 비율 None. 원인 규명 |
| `disabled` / `disabled_but_hit` | 리포트가 플래그를 꺼진 것으로 읽었다 | 플래그 주입 실패 — [B]의 `CACHE_FLAG_ON` 확인 |
| `unknown_flag` | 측정은 됐으나 플래그 상태 미상 | 설정 읽기 경로 점검 |

## 7. `enabled_not_working`이 나오면 — 원인 후보 2종

미리 판정하지 않는다. 다만 회신이 오면 세션이 이 두 축을 먼저 본다.

1. **최소 캐시 토큰 미달** — Anthropic은 캐시 가능한 최소 프리픽스 길이가 모델별로 다르고
   (512~4096 토큰) 그 미만이면 **조용히 캐시되지 않는다**(`config.py`의 플래그 설명이 이미
   자인한다). 저작 경로의 system 프롬프트는 `docs/prompts/l3_equivalent_gen.md`의
   `l3.equivalent.system` 블록이며 2026-09-21 실측 **2,834자**다. 한국어 혼합이라 거친 환산으로
   1,400~1,900 토큰이고, Sonnet 계열 최소치와 **같은 자릿수**다 — 즉 아슬아슬하다.
2. **브레이크포인트가 가변 구간 뒤에 놓임** — 우리는 최상위 `cache_control`(자동 캐싱)을 쓴다
   (`l3/providers/anthropic.py` L443). 자동 캐싱은 *마지막 캐시 가능 블록*에 지점을 잡는데,
   우리 호출의 마지막 블록은 **시도마다 달라지는 user 프롬프트**다. system 프롬프트는
   `_system_prompt()`가 상수를 돌려주므로 회차 내내 **동일**하지만(그래서 구조적으로 적중이
   가능하다), 지점이 뒤에 잡히면 공통 프리픽스가 별도로 기록되지 않을 수 있다.

호출은 **순차**다(`problem_corpus_accumulate.py` L532 `for index in range(n)`) — 1회차가 쓰고
2~10회차가 읽는 구조라 적중이 시간적으로 가능하다. 동시 호출로 인한 경합은 배제된다.

## 8. 비용

Sonnet(CLOUD_MID) **10호출**이며 전액 실제 과금된다. `--budget-krw`는 라우팅 티어를 정하는
입력이지 **지출 상한이 아니다.** 거친 추정으로 **수백 원** 수준이고, 정확한 값은 리포트의
비용 필드로 확인한다.

## 9. 왜 `--subscription premium --budget-krw 5000`을 둘 다 주는가

하나만 주거나 안 주면 라우터가 LOCAL로 강제해 클라우드 호출이 0건이 되고 계측이 공전한다.
2026-09-07 실측: free/0=local · free/5000=local · premium/0=local · **premium/5000=cloud_mid**.
구독과 예산이 **각각 독립적으로** LOCAL을 강제한다.

---

## [A] worktree 생성 + 해시 자가검증

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git worktree add --detach C:\Users\kiki\Desktop\__AI\WhyMath-eos02 origin/main
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos02
git log -1 --oneline
```

worktree가 이미 있다는 오류가 나면 이전 회차의 잔재다.
`git worktree remove C:\Users\kiki\Desktop\__AI\WhyMath-eos02 --force` 후 위를 다시 실행한다.

해시를 눈으로 대조하지 못해도 **[B]가 다시 잡는다**(아래 `HEAD_MATCHES_REMOTE`).

## [B] 환경·코드 출처·CLI 인자·SDK 표면 검사 (읽기 전용)

이 블록은 **아무것도 쓰지 않는다.** 마지막 줄의 `READY`가 [C]의 통과 조건이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos02
$Py = Get-ChildItem C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe -ErrorAction SilentlyContinue
if (-not $Py) { $Py = @(Get-Command python -ErrorAction SilentlyContinue)[0] }
$PyExe = $Py.FullName
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-eos02\src\backend"
$env:WHYMATH_ANTHROPIC_PROMPT_CACHING = "true"
$Src = & $PyExe -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk = $Src -like "*WhyMath-eos02*"
$HeadSha = (git rev-parse HEAD)
$RemoteSha = (git rev-parse origin/main)
$HeadOk = $HeadSha -eq $RemoteSha
$ArgsOut = & $PyExe -m whymath_backend.harness.problem_corpus_accumulate --help 2>&1 | Out-String
$HasSub = $ArgsOut -match "--subscription"
$HasBudget = $ArgsOut -match "--budget-krw"
$Sdk = & $PyExe -c "import inspect, anthropic; ps=list(inspect.signature(anthropic.resources.messages.Messages.create).parameters); print('VER=%s;CC=%s' % (anthropic.__version__, 'cache_control' in ps))"
$SdkHasCacheControl = $Sdk -match "CC=True"
$Cfg = & $PyExe -c "from whymath_backend.config import Settings; s=Settings(); print('KEY=%s;CACHE=%s;SEAT=%s' % (s.anthropic_configured, s.anthropic_prompt_caching, s.cloud_provider))"
$HasKey = $Cfg -match "KEY=True"
$CacheFlagOn = $Cfg -match "CACHE=True"
$SeatAnthropic = $Cfg -match "SEAT=anthropic"
$Ready = $CodeOk -and $HeadOk -and $HasSub -and $HasBudget -and $SdkHasCacheControl -and $HasKey -and $CacheFlagOn -and $SeatAnthropic
Write-Output "PYTHON=$PyExe"
Write-Output "LOADED_FROM=$Src"
Write-Output "CODE_FROM_WORKTREE=$CodeOk"
Write-Output "HEAD_MATCHES_REMOTE=$HeadOk  (HEAD=$HeadSha)"
Write-Output "HAS_SUBSCRIPTION=$HasSub  HAS_BUDGET=$HasBudget"
Write-Output "SDK=$Sdk"
Write-Output "SDK_HAS_CACHE_CONTROL=$SdkHasCacheControl"
Write-Output "SETTINGS=$Cfg"
Write-Output "HAS_ANTHROPIC_KEY=$HasKey  CACHE_FLAG_ON=$CacheFlagOn  SEAT_IS_ANTHROPIC=$SeatAnthropic"
Write-Output "READY=$Ready"
```

**각 검사가 무엇을 막는가** (변별력):

- `CODE_FROM_WORKTREE` — 원 클론에 editable 설치된 **옛 코드가 임포트되는** 상황을 막는다.
  파일을 눈으로 보는 것만으로는 *그 파일이 실제로 임포트됐는지* 모르므로 `__file__`을 찍는다.
- `HEAD_MATCHES_REMOTE` — **경로가 아니라 버전을 본다.** 위 검사는 *어느 트리인가*만 보므로
  옛 커밋의 worktree에서도 True가 난다.
- `HAS_SUBSCRIPTION` / `HAS_BUDGET` — worktree가 옛 커밋이면 두 인자가 없다. §9의 두 플래그가
  실재하지 않으면 회차가 LOCAL로 공전한다.
- **`SDK_HAS_CACHE_CONTROL` — 이 회차의 핵심 사전검증이다.** 우리는 캐시를 최상위
  `cache_control` 인자로 싣는데, `anthropic` SDK의 `messages.create`에는 `**kwargs`가 **없다**.
  즉 그 인자가 없는 버전이 깔려 있으면 **매 호출이 `TypeError`로 즉사**한다. 그런데 저작
  배치는 호출 실패를 `generation_failed`로 집계하므로 회차는 정상 종료하고, 사람에게는
  `calls_with_cache_telemetry=0`(=미측정)으로만 보인다 — **원인이 보이지 않는 실패**다.

  2026-09-21 실측(PyPI 실물 설치 후 `inspect.signature`): `0.81.0`·`0.82.0` 부재 →
  **`0.83.0`부터 존재**(0.84·0.85·0.90·0.95·0.100·0.117 확인). `output_config`(effort)는
  `0.80.0`부터. 저장소 pin은 `anthropic>=0.40.0,<1`이라 **없는 구간을 허용한다** —
  pin 하한 정정은 `OPS-87-anthropic-sdk-pin-floor-surface`가 소유하며, 그때까지 이 검사가
  Kiki 머신 1대에 대한 방어선이다.
- `HAS_ANTHROPIC_KEY` — **환경변수 이름을 보지 않고 `Settings`에 묻는다.** `anthropic_api_key`
  에는 alias가 없어 `WHYMATH_ANTHROPIC_API_KEY`로만 읽히는데(`config.py`), 이름을 추측해
  직접 보면 `.env` 경유 주입을 놓친다. 값은 출력되지 않는다(`SecretStr` + bool 프로퍼티).
- `CACHE_FLAG_ON` — 위에서 설정한 환경변수를 **`Settings`가 실제로 읽었는지** 확인한다.
  변수 이름이 틀리면 여기서 False가 난다(이 회차 전체가 `disabled`로 나오는 것을 사전 차단).
- `SEAT_IS_ANTHROPIC` — ARCH-57 좌석 셀렉터가 `openrouter`로 잡혀 있으면(`WHYMATH_CLOUD_PROVIDER`
  가 창에 남아 있는 등) 이 회차는 Anthropic을 안 태운다. 그러면 캐시 계측이 성립하지 않는다.

`READY=False`면 위 줄들에서 어느 항목이 False인지 보인다. 고친 뒤 [B]를 다시 돌린다.

## [C] 회차 실행 — 10호출 (쓰기)

**이 블록은 선행 판정을 스스로 재검사하고, 통과하지 못하면 실행을 거부한다.** [B]의 출력을
눈으로 본 것만으로는 흐름이 멈추지 않기 때문이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos02
New-Item -ItemType Directory -Force -Path .eos02-out | Out-Null
$Src2 = & $PyExe -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk2 = $Src2 -like "*WhyMath-eos02*"
$Cfg2 = & $PyExe -c "from whymath_backend.config import Settings; s=Settings(); print('KEY=%s;CACHE=%s;SEAT=%s' % (s.anthropic_configured, s.anthropic_prompt_caching, s.cloud_provider))"
$Go = $CodeOk2 -and ($Cfg2 -match "KEY=True") -and ($Cfg2 -match "CACHE=True") -and ($Cfg2 -match "SEAT=anthropic")
Write-Output "PRECHECK CodeOk=$CodeOk2 Settings=$Cfg2 Go=$Go"
if ($Go) { & $PyExe -m whymath_backend.harness.problem_corpus_accumulate --seed data\corpus\problem_bank_generated_v0\problems.jsonl --out .eos02-out\eos02_cache_probe.jsonl --n 10 --subscription premium --budget-krw 5000 --standard-code "[9수02-20]" --difficulty 2.5 --topic-hint "중3 이차방정식 — 두 근 중 더 큰 근을 구하는 형태(답 하나)" | Tee-Object -FilePath .eos02-out\round_report.json; Write-Output "EXIT=$LASTEXITCODE  (0=수용>=1 · 1=수용0 · 2=무진전알람 — 셋 다 계측은 유효)" } else { Write-Output "WRITE_REFUSED=True — CodeOk=$CodeOk2 Settings=$Cfg2 · [B]를 다시 통과시킨 뒤 이 블록을 붙여넣으세요" }
```

`--canary`·`--abort-window`는 **주지 않는다**. 기본값(30·50)이 `--n 10`보다 크므로 둘 다
판정 자체를 하지 않는다(코드 실측: `--n이 카나리 값 이하면 막을 본배치가 없으므로 판정하지
않는다`). 0으로 끄는 인자를 굳이 붙이면 "안전장치를 껐다"는 오해만 남는다.

## [D] 판정 재료 추출 (읽기 전용)

회차 대장(`<out>.rounds.jsonl`)은 **Python이 쓴다.** 그것을 Python이 읽으므로 PowerShell의
인코딩·JSON 파싱을 경유하지 않는다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos02
$LedgerOk = Test-Path .eos02-out\eos02_cache_probe.rounds.jsonl
Write-Output "LEDGER_EXISTS=$LedgerOk"
if ($LedgerOk) { & $PyExe -c "import json,pathlib; rows=[json.loads(l) for l in pathlib.Path('.eos02-out/eos02_cache_probe.rounds.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]; r=rows[-1]; pc=r.get('prompt_cache') or {}; print('attempted =', r.get('attempted')); print('accepted =', r.get('accepted')); print('outcome_counts =', r.get('outcome_counts')); print('model_name =', r.get('model_name')); [print(k, '=', pc.get(k)) for k in ('state','hit_rate','calls_with_cache_telemetry','calls_total','caching_enabled','cache_read_tokens','cache_creation_tokens','prompt_tokens_total','unmeasured_reason')]" } else { Write-Output "READ_REFUSED=True — 회차 대장이 없습니다. [C]가 실행되지 않았거나 WRITE_REFUSED로 끝났습니다" }
```

## 회신해 주실 것

[B]의 `READY=` 줄, [C]의 `EXIT=` 줄, 그리고 [D]의 출력 전체.

`outcome_counts`를 함께 보내 주시는 이유가 있다 — `generation_failed`가 10이면 호출이 전건
실패한 것이고, 그때 `calls_with_cache_telemetry=0`은 "클라우드 미도달"이 아니라 "호출이 죽었다"
는 뜻이라 대처가 정반대다. **두 실패를 가르는 것이 이 필드다.**

원문 리포트 전문은 `.eos02-out\round_report.json`에 남아 있다(`.eos02-out/`는 gitignore 대상).

---

## 10. v1에서 고친 것 (2026-09-21)

| 축 | v1 | v2 | 근거 |
|---|---|---|---|
| 판정 기준 | main `1abf743b` | main `d10ba109` · 코드 행 번호 재실측(L887 → L1445) | 그 사이 저작 경로 5커밋 |
| 실행 트리 | 원 클론에서 `git checkout main; git pull` | **worktree `--detach`** | 공유 작업 사본 — 타 세션 브랜치·미커밋 변경 |
| 인터프리터 | 맨 `python` | `.venv` 우선 해소 후 `$PyExe` 고정 | conda base + `.venv` 동시 활성 |
| 코드 출처 | 검사 없음 | `__file__` + `HEAD` 대조 | 파일을 봐도 임포트 여부는 모른다 |
| **SDK 표면** | **검사 없음** | `cache_control` 인자 실재 검사 | pin 하한이 없는 구간을 허용 — `OPS-87` |
| 플래그 주입 | `$env:` 설정 후 그 변수를 되읽음 | **`Settings`가 읽었는지** 확인 | 변수만 보면 이름 오류를 못 잡는다 |
| 좌석 | 검사 없음 | `cloud_provider=anthropic` 확인 | ARCH-57 셀렉터가 v1 이후 들어왔다 |
| 산출 경로 | `data\corpus\problem_bank_llm_live\` (**추적 대상**) | `.eos02-out\` (gitignore) | 공유 클론을 더럽히지 않는다 |
| 쓰기 가드 | 키 존재만 | 선행 판정 4항 **재검사 후 거부** | 출력은 흐름을 멈추지 못한다 |
| 추출 | PowerShell `ConvertFrom-Json` | Python이 쓴 대장을 Python이 읽음 | cp949 경유 제거 |
| `state` 표 | 3종만 기재 | **6종 전건** | 나머지 3종이 나오면 판정 불가였다 |
