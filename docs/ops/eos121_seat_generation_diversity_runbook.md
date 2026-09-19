# EOS-121 좌석별 생성 다양성 실측 회차 런북 (Phaiakes9)

> **게이트**: `G-eos121-seat-generation-diversity-run` (`kind: human` · `assignee: kiki`)
> **선행 착지**: 선결조건 A(`top_p` 양 좌석 전송) · B(중복 출처 구분) · C(spec 순환 + `--top-p` CLI)
> **판정 기준**: 브랜치 `claude/ecstatic-fermi-uvyp2w`
>
> ⚠️ **이 런북이 쓰는 코드는 아직 main에 없다.** `--top-p`·`--spec-file` 인자와 `duplicate_sources` 집계는 위 브랜치에만 있다. [A]가 worktree를 그 브랜치로 만들고, [B]가 **그 인자들이 실재하는지 실측해 없으면 멈춘다**.

---

## 1. 과제 명칭

저작 좌석(anthropic / openrouter)별 **생성 다양성 실측 회차** — 좌석당 90호출(30회 × spec 3종), 합계 180호출.

## 2. 목적

EOS-118 라이브 2회차에서 부수로 관측된 것이 있다. 같은 인자·같은 spec·같은 topic_hint인데 **openrouter는 5건 전건 수용**이었고 **anthropic은 5건 중 4건이 중복으로 폐기**됐다. 두 회차 다 LLM 호출은 전건 성공했으므로 중복은 호출 실패가 아니라 생성 내용의 문제다.

표본이 n=5 단일 주제라 **좌석 특성인지 우연인지 가를 수 없다.** 이 회차가 그것을 가른다.

결과가 쓰이는 곳:
- **재현되면** 저작 배치의 *실효 단가*가 좌석마다 달라진다(수용 1건당 비용 5배). `ARCH-55` 4회차 비용 비교에 이 축을 병기해야 하고, 상시 채택 판정(`ARCH-56`)의 재료가 된다.
- **재현되지 않으면** "표본 5의 우연"으로 기록하고 닫는다. 실패 회차도 산출물이며 폐기하지 않는다.

**이 회차는 채택 결정이 아니다.** 수동 측정 1회이므로 `G-arch56-availability-trigger`의 발동 조건(상시 배치 트래픽 투입)을 건드리지 않는다.

## 3. 실행 환경

| | |
|---|---|
| 머신 | **Phaiakes9** = Kiki의 작업 PC 그 자체 (별도 접속·SSH 불요) |
| 시스템 | Windows PowerShell |
| 원 작업 디렉터리 | `C:\Users\kiki\Desktop\__AI\WhyMath` |
| 실행 디렉터리 | `C:\Users\kiki\Desktop\__AI\WhyMath-eos121` (**[A]가 worktree로 새로 만든다**) |
| 선행 조건 | OpenRouter·Anthropic API 키가 환경변수로 등록돼 있을 것 ([B]가 값을 출력하지 않고 존재만 검사) |
| 불요 | Docker · DB · 서버 기동 (이 회차는 DB에 쓰지 않는다) |

**왜 worktree인가**: Kiki 클론은 여러 세션이 공유하는 **단일 작업 사본**이다. 다른 세션이 브랜치를 전환해 두거나 미커밋 변경을 남겨 둘 수 있으므로, 체크아웃을 옮기지 않고 별도 worktree에서 돈다. 원 클론의 브랜치·미커밋 변경을 **하나도 건드리지 않는다.**

## 4. 창 구분

**창은 하나면 된다.** 서버를 띄우지 않으므로 점유 창이 없다. 블록 [A]~[F]를 같은 PowerShell 창에서 순서대로 실행한다.

다만 [D]와 [E]는 각각 **수십 분**이 걸릴 수 있다(좌석당 90회 LLM 호출). 도는 동안 그 창을 건드리지 말 것 — `Ctrl+C`는 복사가 아니라 **중단 신호**다.

## 5. 절차 개요와 예상 시간

| 블록 | 무엇 | 쓰기 | 예상 |
|---|---|---|---|
| [A] | worktree 생성 + 브랜치 자가검증 | worktree만 | 1분 |
| [B] | 환경·코드 출처·CLI 인자 실재 검사 | 없음(읽기) | 1분 |
| [C] | spec 계획 파일 3종 작성 | 로컬 파일 | 즉시 |
| [D] | **좌석 1 = openrouter** 90호출 | 산출 파일 | 20~40분 |
| [E] | **좌석 2 = anthropic** 90호출 | 산출 파일 | 20~40분 |
| [F] | 회신 추출 | 없음(읽기) | 즉시 |

## 6. 성공 기준

- **[B]에서 `READY=True`가 나와야 한다.** 하나라도 False면 [D]·[E]가 **스스로 거부**한다(출력만 보고 지나칠 수 없게 설계돼 있다).
- **[D]·[E]에서 `EXIT=0`** 이고 `attempted`가 90에 가까울 것. 중간 중단이 나면 그 사실이 회차 대장에 남는다.
- **[F]의 회신에 `duplicate_sources`가 `measured: true`로 나올 것.** `measured: false`는 "중복이 0건이라 비율을 낼 수 없다"는 뜻이고, 그 자체가 유효한 결과다(= 재현 실패 방향).
- **실패 시 대처**: [B]가 False를 내면 그 항목 이름이 함께 출력된다. 대개는 worktree가 옛 커밋이거나(→ [A] 재실행) 키 미등록이다.

## 7. 비용

**180호출이며 전액 실제 과금된다.** 상한 장치가 없다 — `--budget-krw`는 라우팅 티어를 정하는 입력이지 지출 상한이 아니다.

거친 추정으로 **5,000~9,000원** 범위다(Sonnet 90호출이 대부분을 차지하고 deepseek-flash 쪽은 훨씬 싸다). **이것은 곱셈 추정이지 청구서 대조값이 아니다.** 금액이 부담되면 게이트를 waive하거나 좌석당 회수를 줄여 돌려도 된다 — 다만 30회 미만이면 acceptance ②의 "좌석당 최소 30회"를 벗어나므로 게이트 문면 수정이 따라와야 한다.

---

## [A] worktree 생성 + 브랜치 자가검증

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin claude/ecstatic-fermi-uvyp2w
git worktree add --detach C:\Users\kiki\Desktop\__AI\WhyMath-eos121 origin/claude/ecstatic-fermi-uvyp2w
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
git log -1 --oneline
```

마지막 줄의 해시가 이 런북을 만든 시점의 브랜치 끝과 같아야 한다. **다르면 [B]가 CLI 인자 실재 검사로 다시 잡는다** — 해시를 눈으로 대조하지 못해도 [B]가 막는다.

worktree가 이미 있다는 오류가 나면 이전 회차의 잔재다. `git worktree remove C:\Users\kiki\Desktop\__AI\WhyMath-eos121 --force` 후 위를 다시 실행한다.

## [B] 환경·코드 출처·CLI 인자 실재 검사 (읽기 전용)

이 블록은 **아무것도 쓰지 않는다.** 마지막 줄의 `READY`가 [D]·[E]의 통과 조건이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
$Py = Get-ChildItem C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe -ErrorAction SilentlyContinue
if (-not $Py) { $Py = @(Get-Command python -ErrorAction SilentlyContinue)[0] }
$PyExe = $Py.FullName
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-eos121\src\backend"
$Src = & $PyExe -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk = $Src -like "*WhyMath-eos121*"
$ArgsOut = & $PyExe -m whymath_backend.harness.problem_corpus_accumulate --help 2>&1 | Out-String
$HasTopP = $ArgsOut -match "--top-p"
$HasSpecFile = $ArgsOut -match "--spec-file"
$HasOrKey = [bool]$env:OPENROUTER_API_KEY
$HasAnKey = [bool]$env:ANTHROPIC_API_KEY
$Ready = $CodeOk -and $HasTopP -and $HasSpecFile -and $HasOrKey -and $HasAnKey
Write-Output "PYTHON=$PyExe"
Write-Output "LOADED_FROM=$Src"
Write-Output "CODE_FROM_WORKTREE=$CodeOk"
Write-Output "HAS_TOP_P=$HasTopP  HAS_SPEC_FILE=$HasSpecFile"
Write-Output "HAS_OPENROUTER_KEY=$HasOrKey  HAS_ANTHROPIC_KEY=$HasAnKey"
Write-Output "READY=$Ready"
```

**각 검사가 무엇을 막는가** (변별력):

- `CODE_FROM_WORKTREE` — 원 클론에 editable 설치된 **옛 코드가 임포트되는** 상황을 막는다. 파일을 눈으로 확인하는 것만으로는 *그 파일이 실제로 임포트됐는지* 모르므로 `__file__`을 찍는다.
- `HAS_TOP_P` / `HAS_SPEC_FILE` — worktree가 옛 커밋이면 두 인자가 없다. **[A]의 해시 대조를 사람이 건너뛰어도 여기서 걸린다.**
- `HAS_*_KEY` — 값을 출력하지 않고 **존재 여부만** 낸다.

`READY=False`면 위 줄들에서 어느 항목이 False인지 보인다. 고친 뒤 [B]를 다시 돌린다.

## [C] spec 계획 파일 작성

spec을 3종으로 가르는 것이 이 측정의 핵심이다 — **단일 spec에서만 나는 현상인지 가르기 위해서**다. 중복 signature가 발문을 보지 않고 계수 스케일·부호를 흡수하므로, 같은 spec을 반복하면 충돌이 구조적으로 잘 난다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
$Plan = @(
  '{"spec_id": "quad-largest", "topic_hint": "이차방정식 — 두 근 중 큰 근을 구하는 형태(답 하나)", "difficulty": 2.5}',
  '{"spec_id": "quad-smallest", "topic_hint": "이차방정식 — 두 근 중 작은 근을 구하는 형태(답 하나)", "difficulty": 3.0}',
  '{"spec_id": "quad-sum", "topic_hint": "이차방정식 — 두 근의 합을 구하는 형태(답 하나)", "difficulty": 3.5}'
)
Write-Output "PRECHECK Ready=$Ready"
if ($Ready) { New-Item -ItemType Directory -Force -Path .eos121-out | Out-Null; Set-Content -Path .eos121-out\spec_plan.jsonl -Value $Plan -Encoding utf8; Get-Content .eos121-out\spec_plan.jsonl | Measure-Object -Line } else { Write-Output "WRITE_REFUSED=True — [B]의 READY가 True가 아닙니다. [B]를 먼저 통과시키세요" }
```

`Lines: 3`이 나와야 한다.

## [D] 좌석 1 — openrouter 90호출 (쓰기)

**이 블록은 선행 판정을 스스로 재검사하고, 통과하지 못하면 실행을 거부한다.** [B]의 출력을 눈으로 본 것만으로는 흐름이 멈추지 않기 때문이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
$env:WHYMATH_CLOUD_PROVIDER = "openrouter"
$SpecOk = Test-Path .eos121-out\spec_plan.jsonl
$Src2 = & $PyExe -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk2 = $Src2 -like "*WhyMath-eos121*"
Write-Output "PRECHECK SpecOk=$SpecOk CodeOk=$CodeOk2 Seat=$env:WHYMATH_CLOUD_PROVIDER"
if ($SpecOk -and $CodeOk2) { & $PyExe -m whymath_backend.harness.problem_corpus_accumulate --out .eos121-out\openrouter.jsonl --n 90 --spec-file .eos121-out\spec_plan.jsonl --top-p 0.95 --subscription premium --budget-krw 5000 --canary 0 --abort-window 0 --worklist-out .eos121-out\openrouter.review.jsonl 2>&1 | Tee-Object -FilePath .eos121-out\openrouter.stdout.txt; Write-Output "OPENROUTER_EXIT=$LASTEXITCODE" } else { Write-Output "WRITE_REFUSED=True — SpecOk=$SpecOk CodeOk=$CodeOk2 · [C]와 [B]를 다시 확인하세요" }
```

**인자 선택의 근거**:
- `--top-p 0.95`를 **반드시 지정**한다. 지정해야 양 좌석에 같은 값이 나간다 — 미지정이면 각 공급사 기본값에 맡겨져 교란 변수가 열린 채로 재게 된다. 값 자체(0.95)는 측정자 선택이고, **두 좌석이 같기만 하면 된다.**
- `--subscription premium --budget-krw 5000`은 둘 다 있어야 클라우드 티어로 간다(EOS-118과 같은 인자).
- `--canary 0 --abort-window 0`으로 중단 장치를 끈다. 켜 두면 중복률이 높은 좌석에서 **우리가 재려는 현상 때문에** 회차가 조기 종료돼 표본이 안 찬다. 이 선택은 회차 대장에 값 그대로 기록된다.

## [E] 좌석 2 — anthropic 90호출 (쓰기)

[D]와 같은 구조다. 좌석과 출력 파일만 다르다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
$env:WHYMATH_CLOUD_PROVIDER = "anthropic"
$SpecOk = Test-Path .eos121-out\spec_plan.jsonl
$PrevOk = Test-Path .eos121-out\openrouter.jsonl
$Src3 = & $PyExe -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk3 = $Src3 -like "*WhyMath-eos121*"
Write-Output "PRECHECK SpecOk=$SpecOk PrevOk=$PrevOk CodeOk=$CodeOk3 Seat=$env:WHYMATH_CLOUD_PROVIDER"
if ($SpecOk -and $CodeOk3) { & $PyExe -m whymath_backend.harness.problem_corpus_accumulate --out .eos121-out\anthropic.jsonl --n 90 --spec-file .eos121-out\spec_plan.jsonl --top-p 0.95 --subscription premium --budget-krw 5000 --canary 0 --abort-window 0 --worklist-out .eos121-out\anthropic.review.jsonl 2>&1 | Tee-Object -FilePath .eos121-out\anthropic.stdout.txt; Write-Output "ANTHROPIC_EXIT=$LASTEXITCODE" } else { Write-Output "WRITE_REFUSED=True — SpecOk=$SpecOk CodeOk=$CodeOk3 · [C]와 [B]를 다시 확인하세요" }
```

**좌석별로 `--out`을 가르는 이유**: 회차 대장(`<out>.rounds.jsonl`)이 좌석별로 분리돼 읽기 쉽고, **두 좌석이 같은 dedup 인덱스를 공유하지 않는다.** 같은 파일에 쌓으면 뒤에 도는 좌석이 앞 좌석의 산출물과도 중복 판정을 받아 비교가 오염된다.

## [F] 회신 추출

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos121
$OrOk = Test-Path .eos121-out\openrouter.jsonl.rounds.jsonl
$AnOk = Test-Path .eos121-out\anthropic.jsonl.rounds.jsonl
Write-Output "PRECHECK OrRounds=$OrOk AnRounds=$AnOk"
if ($OrOk -and $AnOk) { Get-Content .eos121-out\openrouter.jsonl.rounds.jsonl -Tail 1 | Out-File -FilePath .eos121-out\reply_openrouter.json -Encoding utf8; Get-Content .eos121-out\anthropic.jsonl.rounds.jsonl -Tail 1 | Out-File -FilePath .eos121-out\reply_anthropic.json -Encoding utf8; Get-Content .eos121-out\reply_openrouter.json; Write-Output "----- 위가 openrouter · 아래가 anthropic -----"; Get-Content .eos121-out\reply_anthropic.json } else { Write-Output "WRITE_REFUSED=True — 회차 대장이 없습니다(OrRounds=$OrOk AnRounds=$AnOk). 해당 좌석의 .eos121-out\<좌석>.stdout.txt를 확인하세요" }
```

두 출력을 그대로 회신하면 된다. 파일이 없다는 오류가 나면 해당 좌석 회차가 대장을 쓰지 못한 것이므로 `.eos121-out\<좌석>.stdout.txt`를 함께 보내 주시면 원인을 읽을 수 있다.

---

## 8. 판정 — 회신에서 무엇을 읽는가

핵심은 `duplicate_sources.counts`의 두 칸 비교다.

- **`structural_signature` × `round`** — 이번 회차가 방금 만든 것끼리 겹쳤다 = **생성 다양성**
- **`structural_signature` × `corpus`** — 기존 코퍼스와 겹쳤다 = dedup의 **정상 동작**

**전자가 좌석 간에 갈리면** EOS-118의 관측이 재현된 것이고, 저작 단가에 좌석 차이가 있다는 뜻이다. **후자만 갈리면** 좌석 특성이 아니라 각 좌석이 마주친 기존 자산의 차이다. 둘을 구분하지 못하면 원인도 처방도 지목할 수 없어서, 이번 회차 전에 그 계측을 먼저 넣었다.

함께 읽을 것:
- **`spec_outcome_counts`** — spec 3종 중 어디서 났는지. **한 spec에만 쏠려 있으면 좌석 특성이 아니라 그 주제의 특성**이다.
- **`operating_rates`·`cloud_seat`** — 좌석 신호가 실제로 그 좌석을 말하는지(EOS-118이 동결한 축).
- **`duplicate_sources.measured`** — `false`면 중복이 0건이라 비율을 낼 수 없다는 뜻이다. **미측정이지 0%가 아니다.**

### 미리 밝혀 두는 해석 한계

**`embedding_near` 칸은 0으로 나올 것이고, 그 0은 "안 걸렸다"가 아니라 "그 경로가 안 돌았다"이다.** 이 CLI는 `dedup_index`·`embed_provider`를 주입하지 않아 임베딩 과유사 dedup 자체가 실행되지 않는다. 구조는 갖춰 뒀으나 이번 회차에서는 `structural_signature`만 나온다.

그리고 **중복 판정이 과잉일 여지가 구조적으로 있다.** signature가 발문을 전혀 보지 않고 계수 스케일·부호를 흡수하므로, 서사가 완전히 다른 두 문항도 조건식이 같으면 중복이 된다. 그래서 이 회차의 `rejected_duplicate`는 "같은 문제를 또 만들었다"가 아니라 **"같은 방정식 구조를 또 골랐다"** 로 읽어야 한다. spec 3종이 이 축을 가른다.

근거 문서: `docs/ops/eos121_seat_generation_diversity_precheck.md`
