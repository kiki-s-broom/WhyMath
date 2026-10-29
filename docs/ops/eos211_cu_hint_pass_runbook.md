# EOS-211 — CU 사후 LLM 힌트 패스 (EOS-197 A6 회차 30 CU 소급) Kiki 실행 런북

> 코드 정본: 패스 본체 `src/backend/whymath_backend/l4/hint_content/cu_hint_pass.py` · CLI 진입점
> `python -m whymath_backend.harness.cu_hint_pass` · 프롬프트 정본 `docs/prompts/cu_hint_pass.md`.
> 측정기: `python -m whymath_backend.ops.g3_content_measures`(EOS-207). 이 런북은 **EOS-211 PR이 main에
> 머지된 뒤** 실행한다 — [B]가 main 최신인지·코드가 있는지를 스스로 확인해 막는다.

## 6항목 사전 브리핑

1. **과제 명칭** — EOS-197 A6 회차 CU 30건에 3단계 힌트(L1·L2·L3)를 붙이고 G3 힌트 누설을 소급 측정.
2. **목적** — EOS-197 회차 CU에는 힌트가 0건이라 G3 조건 "힌트 의미 누설 0"이 측정 대상 부재였다(EOS-207
   첫 측정). 이 패스가 CU마다 LLM으로 단계 목록과 L1·L2·L3 힌트를 만들고, 기계 게이트 3종(레벨 노출 정합·
   정답 누설·정서 톤)을 통과한 힌트만 `cu.hints.jsonl`에 남긴다. 그 파일을 측정기에 넣어 G3 힌트 항목의
   **기계 축** 값을 처음으로 얻는다. 결과는 세션이 받아 EOS-211 ③ 소급 측정값으로 기록하고, 의미 축(사람 표본
   검수 · EOS-210)의 입력이 된다.
3. **구체적 절차** — [A] 격리 워크트리(1분) → [B] 환경·코드 출처 자가검증(1분) → [C] 좌석·키·모델 자가검증
   (1분 · 호출 0건) → [D] 로컬 좌석 3 CU(2~10분 · 첫 호출은 모델 로드로 1~2분 더) → [E] openrouter 좌석 27 CU
   (8~20분 · 유료 — 추정 약 65원 · 상한 약 200원, 근거는 [E]) → [F] 소급 측정(즉시) → [G] 산출물 브랜치
   push(1~2분). [A-2]는 [B]가 낡은 워크트리를 말할 때만, [R]은 [D]·[E]가 손상으로 `EXIT=2`를 낼 때만, [H]는
   세션이 수신을 확인한 뒤의 선택 정리다.
4. **성공 기준** — [D]·[E]가 끝에 찍는 `SUMMARY_EXIT_LINE=EXIT=…`가 **있고** 그 값이 `0`(전 CU 완료) 또는
   `1`(일부 CU 미완 — 실패도 산출물이다, 그대로 진행)이다. 그 줄이 비어 있으면(요약 자체가 없음) 프로세스가 중간에
   죽은 것이고, `EXIT=3`이면 처리되지 않은 예외(`UNHANDLED_ERROR=<타입명>`)다 — 둘 다 출력 전문을 회신한다.
   [F]의 `HINT_INPUTS=2`·`HINT_TOTAL` 1 이상, [G]의 `PUSH_VERIFIED=True`. 쓰기 블록은 선행 조건을 스스로 다시
   계산해 어긋나면 `WRITE_REFUSED=True — …`를 내고 아무것도 쓰지 않는다. **실패 시 대처**: 같은 블록을 다시
   붙여넣으면 완료 CU는 건너뛰고 미완 CU는 남은 시도 예산 안에서 다시 만든다 — `EXIT=2`면 입력 오류이므로
   출력 전문을 회신한다(파일 손상이면 [R]).
5. **실행 환경** — Phaiakes9(이 PC) · Windows PowerShell · 원 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`
   → 격리 워크트리 `C:\Users\kiki\Desktop\__AI\WhyMath-eos211`(원 클론의 브랜치·미커밋 변경을 건드리지 않는다).
   선행 조건: Ollama 가동(로컬 좌석) · 인터넷(openrouter 좌석) · OpenRouter 키(User 환경변수 — EOS-197 회차가 쓴
   그 키, [C]가 확인) · `.venv`(`C:\Users\kiki\Desktop\__AI\WhyMath\.venv`).
6. **창 구분** — **창 ①**(새 PowerShell 창)에서 [A]~[G]를 순서대로. 앞 블록이 만든 변수를 뒤 블록이 쓰므로
   **같은 창에서 이어 간다**. [D]·[E]가 도는 동안 그 창을 건드리지 않는다 — `Ctrl+C`는 복사가 아니라 **중단
   신호**다(중단해도 CU마다 즉시 기록돼 남고, 다시 붙여넣으면 이어 간다). Ollama가 꺼져 있으면 **창 ②**(새 창)에서
   `ollama serve` 한 줄만 실행하고 그 창은 그대로 둔다.

### 이 패스가 하는 것과 하지 않는 것 (판정 읽기 전에)

- **하는 것**: CU 1건당 LLM 호출로 단계 목록·핵심 개념 이름·L1·L2·L3를 받는다. 게이트 3종을 모두 통과한 힌트만
  `verified=true`다(정답 누설 게이트 포함 · 판정 불가는 통과가 아니다). CU당 **총 시도 상한은 3회**(기본
  `--retries 2` — 이전 실행까지 합쳐 센다)이고, provider·파싱·형식 실패뿐 아니라 **게이트 거부도 같은 예산
  안에서 다시 만든다.** 세 레벨이 모두 통과하면 멈추고, 예산이 떨어지면 통과 레벨이 가장 많은 시도를 남긴다.
- **⚠ 선택 편향**: 게이트 거부 재생성은 "검출기를 통과할 때까지 다시 뽑기"다. 그래서 요약은 시도 수·거부율
  (`HINT_ATTEMPTS_TOTAL`·`HINT_GATE_REJECT_RATE`·`CU_REGENERATED`·`CU_ATTEMPTS`)을 늘 싣는다 — **회신에 그대로
  적는다.** 세션은 이 값을 측정 해석에 함께 남기고, 의미 축 표본(EOS-210)에 재생성된 CU를 우선 넣는다.
- **⚠ 순환 측정**: 측정기의 힌트 기계 축은 이 패스가 거른 바로 그 정답 누설 게이트를 다시 돌린다. 그래서
  `cu.hints.jsonl`에 대한 `HINT_LEAKED_L12`는 구조적으로 0이다 — **누설이 없다는 증거가 아니다.** 실질 검증은
  의미 축(사람 표본 검수 · EOS-210)이고, 측정기는 늘 `HINT_SEMANTIC_AXIS=NOT_MEASURED`를 싣는다.
- **하지 않는 것**: LLM이 낸 단계 계산 자체를 SymPy로 검증하지 않는다(후속). DB(`hints` 표)에 적재하지 않는다 —
  CU에는 실제 풀이 경로(`solution_paths`)·DB 문항 행이 없어 외래키를 만족할 수 없다(후속).

### 산출물 (좌석 폴더마다 · 줄마다 즉시 기록)

| 파일 | 내용 |
|---|---|
| `cu.hints.jsonl` | **현재 채택본**의 게이트 3종 통과 `Hint` JSON 1행 1건 — 측정 입력(원자적 교체로만 쓴다) |
| `cu.hints.rejected.jsonl` | 게이트 거부 `Hint` JSON — `gate_report`에 게이트별 사유 · **이력**(재생성해도 지우지 않는다) |
| `cu.hints.genlog.jsonl` | 시도마다 `GenerationLog` 1행(모델·prompt_version·seed·input_sha256·성공 여부·오류 `<타입명>(HTTP nnn)` — 원문 없음) · **이력** |
| `cu.hints.context.jsonl` | CU당 1행(현재 채택본) — 게이트가 본 단계·개념 이름·정답·레벨별 판정·누적 시도 회계 |
| `*.corrupt` | 끊긴 쓰기 등으로 깨진 줄의 보존본(생기면 회신에 적는다 — 정상 실행에서는 없다) |

### 요약 줄 읽는 법 ([D]·[E] 출력 끝 · 마지막 줄은 항상 `EXIT=`)

- 진행 중에는 CU마다 `CU_DONE slug=… verified_levels=[…] attempts_total=…` 또는 `CU_FAILED slug=…`가 찍힌다.
  **5분 넘게 새 줄이 없으면** `Ctrl+C`로 멈추고 그때까지의 출력을 회신한다.
- `CU_BUDGET_EXHAUSTED` — 시도 3회를 다 쓰고도 미완인 CU(다시 붙여넣어도 호출하지 않는다 · 세션이 지시할 때만
  [D-R]로 예산을 새로 준다) · `CU_REGENERATED` — 게이트까지 간 시도가 2회 이상인 CU.
- `HINT_ATTEMPTS_TOTAL`(누적 시도) · `HINT_GATED_ATTEMPTS_TOTAL`(게이트까지 간 시도) ·
  `HINT_GATE_REJECTED_HINTS_TOTAL`(거부 힌트) · `HINT_GATE_REJECT_RATE`(거부 힌트 ÷ 게이트 도달 시도×3).
- `GENLOG_QUARANTINED_LINES`·`REJECTED_QUARANTINED_LINES` — 앞 실행이 쓰는 도중 끊겨 깨진 줄을 `.corrupt`로
  옮긴 수(0이 정상 · 0이 아니면 회신).
- `CU_COMPLETE`(L1·L2·L3 모두 통과) · `CU_MEASURABLE_L12`(측정기가 판정할 수 있는 CU — L1·L2 둘 다 통과) ·
  `CU_INCOMPLETE`(한 레벨 이상 거부) · `CU_GENERATION_FAILED`(재시도 후에도 응답을 계약으로 받지 못함).
- `CALL_FAILURE_KINDS` — `provider`(타임아웃·전송 오류) · `parse`(JSON 아님) · `schema`(형식 위반).
- `ROUTES` — 로컬 좌석은 `local:-:quality`, openrouter 좌석은 `cloud_mid:-:-`만 나와야 한다. 다른 값이 섞이면 회신.
- `MODELS` — 로컬은 `qwen3:30b-a3b`, openrouter는 `deepseek/deepseek-v4.1-flash`.
- `EXIT=0` 전 CU 완료 · `EXIT=1` 일부 미완(그대로 다음 블록) · `EXIT=2` 입력 오류(LLM 호출 0건 — 회신, 파일
  손상이면 [R]) · `EXIT=3` 처리되지 않은 예외(`UNHANDLED_ERROR=<타입명>` — 회신).

---

## [A] 격리 워크트리 준비 — 창 ① (1분)

이미 워크트리가 있으면(앞 시도) **건드리지 않는다** — 그 안의 앞 시도 산출물을 지우지 않기 위해서다(재개 재료).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [A] 격리 워크트리 준비
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos211"
$WtExisted = Test-Path $Wt
"WORKTREE_EXISTED=$WtExisted"
if (-not $WtExisted) { git worktree add --detach $Wt origin/main; "WORKTREE_CREATED=$(Test-Path $Wt)" } else { "WORKTREE_KEPT=True — 앞 시도의 워크트리를 그대로 씁니다(산출물 보존 · 재개). [B]의 HEAD_IS_ORIGIN_MAIN을 보십시오" }
"MAIN_HEAD=$(git rev-parse --short origin/main)"
"WORKTREE_HEAD=$(git -C $Wt rev-parse --short HEAD)"
```

**판정**: `WORKTREE_CREATED=True` 또는 `WORKTREE_KEPT=True`. 두 해시가 같으면 최신 main이다.

---

## [A-2] 낡은 워크트리를 최신 main으로 옮기기 (산출물 보존) — [B]가 `HEAD_IS_ORIGIN_MAIN=False`일 때만 · 창 ①

앞 시도가 남긴 워크트리가 옛 main에 있고, 그 안에 아직 push하지 않은 산출물(`cu.hints*`·측정 리포트)이 있을 때 쓴다.
[H]는 원격에 산출물이 있어야만 지우므로 이 상태에서 막힌다. 이 블록은 ① 산출물을 별도 폴더로 복사하고 ② 복사본의
해시가 원본과 **모두 같을 때만** 워크트리를 지워 최신 main으로 다시 만들고 ③ 산출물을 제자리로 되돌려 해시를 다시
대조한다. 워크트리에 추적 파일 변경이 있거나, 보존 폴더가 비어 있지 않으면 아무것도 하지 않는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [A-2] 낡은 워크트리 이전 (쓰기 · 산출물 보존 · 워크트리 재생성)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos211"
$Carry = "C:\Users\kiki\Desktop\__AI\WhyMath-eos211-carry"
$WtHeadA2 = if (Test-Path $Wt) { git -C $Wt rev-parse HEAD } else { "" }
$MainHeadA2 = git rev-parse origin/main
$StaleA2 = [bool]($WtHeadA2 -and ($WtHeadA2 -ne $MainHeadA2))
$TrackedDirtyA2 = if (Test-Path $Wt) { @(git -C $Wt status --porcelain --untracked-files=no).Count } else { -1 }
$CarryEmptyA2 = (-not (Test-Path $Carry)) -or (@(Get-ChildItem -Path $Carry -Recurse -File -ErrorAction SilentlyContinue).Count -eq 0)
$OutFilesA2 = @(Get-ChildItem -Path "$Wt\data\runs" -Recurse -File -ErrorAction SilentlyContinue | Where-Object { ($_.Name -like "cu.hints*") -or ($_.Name -eq "g3_content_measures_eos211.json") })
"PRECHECK_A2 Stale=$StaleA2 TrackedDirty=$TrackedDirtyA2 CarryEmpty=$CarryEmptyA2 OutputFiles=$($OutFilesA2.Count) WorktreeHead=$WtHeadA2 MainHead=$MainHeadA2"
if ($StaleA2 -and ($TrackedDirtyA2 -eq 0) -and $CarryEmptyA2) {
  $RelA2 = @($OutFilesA2 | ForEach-Object { $_.FullName.Substring($Wt.Length + 1) })
  foreach ($r in $RelA2) { New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $Carry $r)) | Out-Null; Copy-Item -LiteralPath (Join-Path $Wt $r) -Destination (Join-Path $Carry $r) }
  $CopyMismatchA2 = @($RelA2 | Where-Object { (Get-FileHash -LiteralPath (Join-Path $Wt $_)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Carry $_)).Hash }).Count
  "CARRY_COPIED=$($RelA2.Count) CARRY_HASH_MISMATCH=$CopyMismatchA2"
  if ($CopyMismatchA2 -eq 0) {
    git worktree remove --force $Wt
    git worktree add --detach $Wt origin/main
    foreach ($r in $RelA2) { New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $Wt $r)) | Out-Null; Copy-Item -LiteralPath (Join-Path $Carry $r) -Destination (Join-Path $Wt $r) }
    $RestoreMismatchA2 = @($RelA2 | Where-Object { -not (Test-Path (Join-Path $Wt $_)) -or ((Get-FileHash -LiteralPath (Join-Path $Wt $_)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $Carry $_)).Hash) }).Count
    "WORKTREE_HEAD_NOW=$(git -C $Wt rev-parse HEAD) MAIN_HEAD=$MainHeadA2 RESTORED=$($RelA2.Count) RESTORE_HASH_MISMATCH=$RestoreMismatchA2"
  } else { "WRITE_REFUSED=True — 워크트리를 지우지 않았다. 복사본 해시 불일치 $CopyMismatchA2건(0이어야) — 보존 폴더 $Carry 를 그대로 두고 이 출력을 회신" }
} else { "WRITE_REFUSED=True — 아무것도 하지 않았다. Stale=$StaleA2(True여야 — False면 이미 최신이거나 워크트리가 없다: [A]부터) TrackedDirty=$TrackedDirtyA2(0이어야 — 추적 파일이 바뀌어 있으면 회신) CarryEmpty=$CarryEmptyA2(True여야 — 앞 이전의 보존본이 남아 있으면 회신)" }
```

**판정**: `CARRY_HASH_MISMATCH=0` · `WORKTREE_HEAD_NOW`가 `MAIN_HEAD`와 같다 · `RESTORE_HASH_MISMATCH=0`. 그다음 **[B]부터**
다시 붙여넣는다(재개 — 되돌린 산출물이 그대로 이어진다). 보존 폴더 `C:\Users\kiki\Desktop\__AI\WhyMath-eos211-carry`는
세션이 수신을 확인할 때까지 지우지 않는다.

---

## [B] 환경·코드 출처 자가검증 — 창 ① (읽기 전용 · 1분)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [B] 환경·코드 출처 자가검증 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos211"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$Wt\src\backend"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_OLLAMA_REQUEST_TIMEOUT_S = "180"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Runs = "$Wt\data\runs"
$LocalRun = "$Runs\eos197-a6-local"
$OrRun = "$Runs\eos197-a6-openrouter"
$ReviewDir = "$Runs\eos197-a6-review"
$MeasureJson = "$ReviewDir\g3_content_measures_eos211.json"
$PassArgs = @()
$CountPy = "import sys,pathlib; p=pathlib.Path(sys.argv[1]); print(sum(1 for l in p.read_text(encoding='utf-8').splitlines() if l.strip()) if p.exists() else 0)"
$HeadSha = git rev-parse HEAD
$MainSha = git rev-parse origin/main
$HeadIsMain = [bool]($HeadSha -and ($HeadSha -eq $MainSha))
$CodeFile = & $Py -c "import whymath_backend.harness.cu_hint_pass as m; print(m.__file__)"
$CoreFile = & $Py -c "import whymath_backend.l4.hint_content.cu_hint_pass as m; print(m.__file__)"
$CodeOk = [bool]($CodeFile -and $CoreFile -and $CodeFile.StartsWith($Wt) -and $CoreFile.StartsWith($Wt))
$HelpText = & $Py -m whymath_backend.harness.cu_hint_pass --help | Out-String
$FlagsOk = ($HelpText -match "--run-dir") -and ($HelpText -match "--retries") -and ($HelpText -match "--budget-krw")
$OllamaTimeout = & $Py -c "from whymath_backend.config import Settings; print(Settings().ollama_request_timeout_s)"
$LocalCu = & $Py -c $CountPy "$LocalRun\cu.jsonl"
$OrCu = & $Py -c $CountPy "$OrRun\cu.jsonl"
$ReadyB = $HeadIsMain -and $CodeOk -and $FlagsOk -and ($OllamaTimeout -eq "180.0") -and ($LocalCu -eq "3") -and ($OrCu -eq "27")
"HEAD_LOG=$(git log -1 --oneline)"
"HEAD_IS_ORIGIN_MAIN=$HeadIsMain"
"IO_ENCODING=$(& $Py -c 'import sys; print(sys.stdout.encoding)')"
"CODE_FILE=$CodeFile"
"CORE_FILE=$CoreFile"
"CODE_FROM_WORKTREE=$CodeOk"
"CLI_FLAGS_OK=$FlagsOk"
"OLLAMA_TIMEOUT_S=$OllamaTimeout"
"LOCAL_CU=$LocalCu OPENROUTER_CU=$OrCu"
"LOCAL_DONE_BEFORE=$(& $Py -c $CountPy "$LocalRun\cu.hints.context.jsonl") OPENROUTER_DONE_BEFORE=$(& $Py -c $CountPy "$OrRun\cu.hints.context.jsonl")"
"PASS_ARGS=$($PassArgs -join ' ')"
"READY_B=$ReadyB"
```

**판정**: `HEAD_IS_ORIGIN_MAIN=True` · `IO_ENCODING=utf-8` · `CODE_FROM_WORKTREE=True` · `CLI_FLAGS_OK=True` ·
`OLLAMA_TIMEOUT_S=180.0` · `LOCAL_CU=3 OPENROUTER_CU=27` · `READY_B=True`. `HEAD_LOG`는 회신에 그대로 적는다
(세션이 기대 커밋과 대조한다). `…_DONE_BEFORE`는 첫 실행이면 0이고, 앞 시도가 있었다면 이미 끝난 CU 수다.

> 변별력: `HEAD_IS_ORIGIN_MAIN`은 [A]가 앞 시도의 낡은 워크트리를 그대로 썼으면 False가 된다 — 그때는 [A-2]로
> 산출물을 보존한 채 워크트리를 최신 main으로 옮기고 [B]부터 다시 한다(push가 이미 끝났다면 [H] 뒤 [A]부터). `CODE_FROM_WORKTREE`는 `PYTHONPATH`가
> 먹지 않으면 평소 클론 경로가 찍혀 False가 된다(파일이 있다는 것과 그 파일이 import됐다는 것은 다르다).
> EOS-211이 머지되기 전 main이면 `ModuleNotFoundError`로 `CODE_FILE`이 비어 False가 된다.
> `OLLAMA_TIMEOUT_S`는 이 창에만 건 값이다(영속 환경변수를 바꾸지 않는다) — 기본 30초면 30B 모델의 힌트 생성이
> 타임아웃으로 전건 실패한다(EOS-197 회차 생성 로그의 `ReadTimeout` 실측).

---

## [C] 좌석·키·모델 자가검증 — 창 ① (읽기 전용 · LLM 호출 0건 · 키 값 미출력)

좌석은 런북이 단정하지 않고 **패스가 실제로 쓰는 함수(`routing_request_for`)로 라우터에 묻는다.**

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [C] 좌석·키·모델 자가검증 (읽기 전용 · 호출 0건 · 키 값 미출력)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$RouteOut = & $Py -c "from whymath_backend.l4.hint_content.cu_hint_pass import routing_request_for as R; from whymath_backend.l3.router import Router, resolve_model; a=Router().route(R(subscription=None, budget_krw=None)); b=Router().route(R(subscription='premium', budget_krw=5000.0)); print('LOCAL_TIER=%s LOCAL_MODEL=%s PAID_TIER=%s' % (a.cost_tier, resolve_model(a.local_family, a.local_model), b.cost_tier))"
$SeatOut = & $Py -c "from whymath_backend.config import Settings; from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name; from whymath_backend.l3.providers.openrouter import jurisdiction_of_slugs as J; s=Settings(); k=s.openrouter_api_key.get_secret_value(); print('SEAT=%s PIN_MID=%s ALLOWED=%s JURIS=%s AN_API_ENABLED=%s AN_CONFIGURED=%s KEY_LEN_OK=%s KEY_HAS_ELLIPSIS=%s KEY_PREFIX_SK_OR=%s' % (cloud_provider_name(s), cloud_model_pins(s)[0], ','.join(s.openrouter_allowed_providers), J(s.openrouter_allowed_providers).value, s.anthropic_api_enabled, s.anthropic_configured, len(k) >= 20, chr(8230) in k, k.startswith('sk-or-')))"
$Installed = ollama list | Out-String
$QualityPresent = [bool]($Installed -and $Installed.Contains("qwen3:30b-a3b"))
$ReadyLocal = [bool]($RouteOut -and ($RouteOut -match "LOCAL_TIER=local LOCAL_MODEL=qwen3:30b-a3b ") -and $QualityPresent)
$ReadyCloud = [bool]($RouteOut -and ($RouteOut -match "PAID_TIER=cloud_mid") -and $SeatOut -and ($SeatOut -match "SEAT=openrouter ") -and ($SeatOut -match "PIN_MID=deepseek/deepseek-v4\.1-flash ") -and ($SeatOut -match "ALLOWED=deepinfra ") -and ($SeatOut -match "JURIS=us ") -and ($SeatOut -match "AN_API_ENABLED=False ") -and ($SeatOut -match "AN_CONFIGURED=False ") -and ($SeatOut -match "KEY_LEN_OK=True ") -and ($SeatOut -match "KEY_HAS_ELLIPSIS=False ") -and ($SeatOut -match "KEY_PREFIX_SK_OR=True"))
"ROUTE_CHECK=$RouteOut"
"SEAT_CHECK=$SeatOut"
"OLLAMA_LIST_LINES=$(@($Installed -split [Environment]::NewLine | Where-Object { $_.Trim() }).Count) QUALITY_PRESENT=$QualityPresent"
"READY_LOCAL=$ReadyLocal READY_CLOUD=$ReadyCloud"
```

**판정**: `ROUTE_CHECK=LOCAL_TIER=local LOCAL_MODEL=qwen3:30b-a3b PAID_TIER=cloud_mid` · `QUALITY_PRESENT=True` ·
`READY_LOCAL=True` · `READY_CLOUD=True`.

- `OLLAMA_LIST_LINES=0`(또는 `ollama` 오류)이면 Ollama가 꺼져 있다 → **창 ②**에서 아래 한 줄을 실행하고 그 창은 그대로
  둔 뒤, 창 ①에서 [C]를 다시.
- `KEY_LEN_OK=False`면 이 창이 키 등록 전에 열렸거나 키가 없다 — 새 창을 열어 [B]부터 다시 해도 False면 **멈추고 이
  출력을 회신**한다(이 런북은 키를 쓰지 않는다 · 키 등록 절차는 `docs/ops/eos197_authoring_round_runbook.md` [C-1]·[C-2]).
- `AN_…=True`이거나 `SEAT`/`PIN_MID`/`JURIS`가 위와 다르면 **멈추고 회신**한다(ARCH-66 · 관할 레일).
- `READY_LOCAL=False`만이면 [D]를 건너뛰고 [E]로 가도 된다(반대도 같다) — 건너뛴 좌석은 회신에 적는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서버 점유 창 · 이후 이 창에는 아무것도 입력하지 않는다 · Ctrl+C는 서버 중단 신호
ollama serve
```

---

## [D] 좌석 1 — 로컬 `qwen3:30b-a3b` · CU 3건 — 창 ① (쓰기 · 로컬 LLM · 2~10분)

**이 블록은 선행 판정을 스스로 다시 계산하고, 통과하지 못하면 실행을 거부한다.** 라우팅 신호를 주지 않으므로
(구독·예산 미지정 = free·0) 라우터가 LOCAL로 강제한다 — 이 블록은 유료 호출을 할 수 없다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [D] 로컬 좌석 힌트 패스 (쓰기 · 로컬 LLM · 과금 0)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$CodeFileD = & $Py -c "import whymath_backend.l4.hint_content.cu_hint_pass as m; print(m.__file__)"
$CodeOkD = [bool]($CodeFileD -and $CodeFileD.StartsWith($Wt))
$RouteD = & $Py -c "from whymath_backend.l4.hint_content.cu_hint_pass import routing_request_for as R; from whymath_backend.l3.router import Router, resolve_model; a=Router().route(R(subscription=None, budget_krw=None)); print('%s|%s' % (a.cost_tier, resolve_model(a.local_family, a.local_model)))"
$TimeoutD = & $Py -c "from whymath_backend.config import Settings; print(Settings().ollama_request_timeout_s)"
"PRECHECK_D CodeOk=$CodeOkD Route=$RouteD OllamaTimeout=$TimeoutD CuFile=$(Test-Path "$LocalRun\cu.jsonl") WorktreeHead=$(git rev-parse --short HEAD)"
if ($CodeOkD -and ($RouteD -eq "local|qwen3:30b-a3b") -and ($TimeoutD -eq "180.0") -and (Test-Path "$LocalRun\cu.jsonl")) {
  & $Py -m whymath_backend.harness.cu_hint_pass --run-dir $LocalRun @PassArgs | Tee-Object -Variable OutD
  $LocalExit = $LASTEXITCODE
  $ExitLineD = @($OutD | Where-Object { $_ -match '^EXIT=' }) | Select-Object -Last 1
  "SUMMARY_EXIT_LINE=$ExitLineD LOCAL_PASS_EXIT=$LocalExit PASS_ARGS=$($PassArgs -join ' ')"
  "HINTS=$(& $Py -c $CountPy "$LocalRun\cu.hints.jsonl") REJECTED=$(& $Py -c $CountPy "$LocalRun\cu.hints.rejected.jsonl") CALLS_LOGGED=$(& $Py -c $CountPy "$LocalRun\cu.hints.genlog.jsonl") CU_WITH_STATE=$(& $Py -c $CountPy "$LocalRun\cu.hints.context.jsonl")"
} else { "WRITE_REFUSED=True — 호출하지 않았다. CodeOk=$CodeOkD(True여야) Route=$RouteD(local|qwen3:30b-a3b여야 — 다르면 좌석이 바뀌었다) OllamaTimeout=$TimeoutD(180.0이어야 — 새 창이면 [B]부터) CuFile=$(Test-Path "$LocalRun\cu.jsonl")(True여야)" }
```

**판정**: `SUMMARY_EXIT_LINE=EXIT=0` 또는 `EXIT=1`이고 그 값이 `LOCAL_PASS_EXIT`와 같다. `SUMMARY_EXIT_LINE=`이
비어 있으면 요약이 나오기 전에 죽은 것이고, `EXIT=3`이면 처리되지 않은 예외다 — 둘 다 출력 전문을 회신한다.
`EXIT=2`이고 `INPUT_ERROR=` 줄이 `JSON 파싱 실패`를 말하면 [R]로 간다. `EXIT=1`이면 요약의 `FAILED_CUS`·
`INCOMPLETE_CUS`·`BUDGET_EXHAUSTED_CUS`를 본다 — 예산이 남은 CU가 있으면 **[D]를 한 번 더** 붙여넣는다(완료 CU는
건너뛰고 미완 CU만 남은 예산 안에서 다시 만든다). `BUDGET_EXHAUSTED_CUS`만 남았으면 그대로 [E]로 가고 회신에 적는다.
전건 `CALL_FAILURE_KINDS={"provider": …}`면 Ollama 상태([C])부터 본다.

---

## [E] 좌석 2 — openrouter `deepseek/deepseek-v4.1-flash` · CU 27건 — 창 ① (쓰기 · **유료 호출** · 8~20분)

[D]와 같은 패스이고, 다른 것은 라우팅 신호 `--subscription premium --budget-krw 5000`뿐이다(둘이 함께여야 클라우드로
간다 — EOS-197 회차 [G]와 같은 신호). `--budget-krw`는 라우팅 티어 입력이지 지출 상한이 아니다.

**비용(곱셈 추정 · 청구서 대조값 아님 · 토큰 수는 미측정)**: 단가 입력 $0.20 · 출력 $0.60 / 1M 토큰(`l3/router.py`
openrouter CLOUD_MID 단가표) · 환율 1,540원(`USD_TO_KRW`). 토큰은 **한글 1자 = 1토큰** 보수 가정이다 — 입력 =
시스템 프롬프트 1,318자 + 사용자 프롬프트 최대 421자(이 회차 27 CU 실측 · 평균 337자) ≈ 1,800토큰, 출력 = 계약
상한(단계 8개 × 300자 + 힌트 3개 × 600자 = 4,200자)이 아니라 실제 힌트 분량 기준 약 2,000토큰으로 잡는다. 시도
1회 ≈ 1,800 × $0.20/1M + 2,000 × $0.60/1M ≈ $0.0016. **CU당 1회씩 27회 ≈ $0.042(약 65원)**, 예산 상한(CU당 3회 ×
27 = 81회) ≈ $0.13(**약 200원**). 모델이 추론 토큰을 출력에 더 붙이면 이보다 커질 수 있다 — 실제 값은 생성 로그의
`input_tokens`·`output_tokens`·`cost_usd`로 사후 확인한다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [E] openrouter 좌석 힌트 패스 (쓰기 · 유료 클라우드 호출)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$CodeFileE = & $Py -c "import whymath_backend.l4.hint_content.cu_hint_pass as m; print(m.__file__)"
$CodeOkE = [bool]($CodeFileE -and $CodeFileE.StartsWith($Wt))
$RouteE = & $Py -c "from whymath_backend.l4.hint_content.cu_hint_pass import routing_request_for as R; from whymath_backend.l3.router import Router; b=Router().route(R(subscription='premium', budget_krw=5000.0)); print(b.cost_tier)"
$SeatE = & $Py -c "from whymath_backend.config import Settings; from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name; s=Settings(); k=s.openrouter_api_key.get_secret_value(); print('%s|%s|%s|%s' % (cloud_provider_name(s), cloud_model_pins(s)[0], s.anthropic_api_enabled, len(k) >= 20 and k.startswith('sk-or-') and chr(8230) not in k))"
"PRECHECK_E CodeOk=$CodeOkE Route=$RouteE SeatCheck=$SeatE CuFile=$(Test-Path "$OrRun\cu.jsonl") WorktreeHead=$(git rev-parse --short HEAD)"
if ($CodeOkE -and ($RouteE -eq "cloud_mid") -and ($SeatE -eq "openrouter|deepseek/deepseek-v4.1-flash|False|True") -and (Test-Path "$OrRun\cu.jsonl")) {
  & $Py -m whymath_backend.harness.cu_hint_pass --run-dir $OrRun --subscription premium --budget-krw 5000 @PassArgs | Tee-Object -Variable OutE
  $OrExit = $LASTEXITCODE
  $ExitLineE = @($OutE | Where-Object { $_ -match '^EXIT=' }) | Select-Object -Last 1
  "SUMMARY_EXIT_LINE=$ExitLineE OPENROUTER_PASS_EXIT=$OrExit PASS_ARGS=$($PassArgs -join ' ')"
  "HINTS=$(& $Py -c $CountPy "$OrRun\cu.hints.jsonl") REJECTED=$(& $Py -c $CountPy "$OrRun\cu.hints.rejected.jsonl") CALLS_LOGGED=$(& $Py -c $CountPy "$OrRun\cu.hints.genlog.jsonl") CU_WITH_STATE=$(& $Py -c $CountPy "$OrRun\cu.hints.context.jsonl")"
} else { "WRITE_REFUSED=True — 호출하지 않았다(과금 0). CodeOk=$CodeOkE(True여야) Route=$RouteE(cloud_mid여야) SeatCheck=$SeatE(openrouter|deepseek/deepseek-v4.1-flash|False|True여야) CuFile=$(Test-Path "$OrRun\cu.jsonl")(True여야) · [C]부터 다시 확인하세요" }
```

**판정**: [D]와 같다(`SUMMARY_EXIT_LINE=EXIT=0` 또는 `EXIT=1` · `CU_WITH_STATE`가 27이면 전 CU가 게이트까지 갔다).
`CU_WITH_STATE`가 27보다 작으면 **[E]를 한 번 더** 붙여넣는다(끝난 CU는 다시 부르지 않아 추가 과금은 남은 CU분뿐이다).

---

## [D-R] (세션 지시가 있을 때만) 시도 예산이 떨어진 미완 CU 다시 만들기 — 창 ①

[D]·[E]가 `BUDGET_EXHAUSTED_CUS`를 남겼고 **세션이 다시 만들라고 회신했을 때만** 쓴다. 다음 [D]·[E] 실행에
`--redo-incomplete`를 붙인다(그 실행에서 미완 CU에 시도 3회를 새로 준다 · 거부 이력·생성 로그는 그대로 남는다).
이 블록은 변수만 바꾸고 아무것도 실행하지 않는다 — 이어서 해당 좌석의 [D] 또는 [E]를 붙여넣는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [D-R] 다음 [D]/[E] 실행에 재생성 스위치 싣기 (변수만 설정)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$PassArgs = @("--redo-incomplete")
"PASS_ARGS=$($PassArgs -join ' ')"
```

## [R] (손상 복구) 상태 파일의 깨진 줄 격리 후 다시 돌리기 — [D]·[E]가 `EXIT=2`와 `JSON 파싱 실패`를 말할 때만 · 창 ①

`cu.hints.jsonl`·`cu.hints.context.jsonl`은 원자적 교체로만 쓰므로 정상 실행에서는 깨지지 않는다 — 깨졌다면 외부
손상(디스크·동기화 도구·수동 편집)이다. 그래서 기본 실행은 입력 오류(2)로 멈춘다. 복구는 **파일을 지우지 않는다**:
다음 [D]·[E] 실행에 `--quarantine-damaged-state`를 붙이면, 깨진 줄을 같은 폴더의 `cu.hints.jsonl.corrupt`·
`cu.hints.context.jsonl.corrupt`로 옮겨 보존하고, 짝을 잃은 CU만 미완으로 다뤄 남은 시도 예산 안에서 다시 만든다
(생성 로그·거부 기록의 깨진 줄은 스위치 없이도 늘 같은 방식으로 격리된다). 예산이 이미 떨어진 CU까지 다시 만들려면
세션 지시에 따라 `--redo-incomplete`도 함께 싣는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [R] 다음 [D]/[E] 실행에 손상 격리 스위치 싣기 (변수만 설정)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$PassArgs = @("--quarantine-damaged-state")
"PASS_ARGS=$($PassArgs -join ' ')"
```

이어서 `EXIT=2`를 냈던 좌석의 [D] 또는 [E]를 다시 붙여넣는다. **판정**: 요약의 `STATE_QUARANTINED_LINES`가 1 이상이고
`SUMMARY_EXIT_LINE=EXIT=0` 또는 `EXIT=1`. 끝나면 `.corrupt` 파일 이름을 회신에 적는다([G]가 함께 올린다).

**스위치를 다음 좌석에 끌고 가지 않는다**: [D-R]·[R]이 설정한 `$PassArgs`는 이 창에 남는다. 한 좌석을 다시 돌린 뒤
다른 좌석의 [D]/[E]로 가기 전에는 **[B]를 다시 붙여넣어** `PASS_ARGS=`가 빈 값인지 확인한다(`--redo-incomplete`가
남아 있으면 다른 좌석의 미완 CU에도 예산이 새로 주어져 추가 호출·과금이 생긴다).

---

## [F] 소급 측정 — EOS-207 측정기 — 창 ① (측정 · LLM 호출 0건 · 즉시)

두 좌석의 `cu.hints.jsonl`을 측정기에 그대로 넣는다(EOS-207 입력 계약). 전체 리포트는 검수 폴더에 JSON으로 남겨
[G]가 함께 올린다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [F] G3 소급 측정 (LLM 호출 0건 · 리포트 JSON 1개 생성)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$H1 = "$LocalRun\cu.hints.jsonl"
$H2 = "$OrRun\cu.hints.jsonl"
$MeasureFile = & $Py -c "import whymath_backend.ops.g3_content_measures as m; print(m.__file__)"
$MeasureOk = [bool]($MeasureFile -and $MeasureFile.StartsWith($Wt))
"PRECHECK_F MeasureCodeOk=$MeasureOk LocalHints=$(Test-Path $H1) OpenrouterHints=$(Test-Path $H2)"
if ($MeasureOk -and (Test-Path $H1) -and (Test-Path $H2)) {
  & $Py -m whymath_backend.ops.g3_content_measures --round eos197-a6 --hints-jsonl $H1 --hints-jsonl $H2 --json $MeasureJson
  $G3Exit = $LASTEXITCODE
  "G3_MEASURE_EXIT=$G3Exit REPORT_JSON_EXISTS=$(Test-Path $MeasureJson)"
} else { "WRITE_REFUSED=True — 측정하지 않았다. MeasureCodeOk=$MeasureOk(True여야) LocalHints=$(Test-Path $H1) OpenrouterHints=$(Test-Path $H2)(둘 다 True여야 — 한 좌석이 [D]/[E]에서 전건 실패했다면 그 출력을 회신)" }
```

**판정**: `REPORT_JSON_EXISTS=True` · 출력의 `HINT_INPUTS=2` · `HINT_TOTAL` 1 이상. `G3_MEASURE_EXIT`는 0·1·2 어느
것이든 **그대로 회신**한다 — 이 값은 힌트 축만이 아니라 자동검증 통과율·메타 누락 축의 판정도 합친 것이다.
힌트 축은 `HINT_MACHINE_AXIS`(`PASS`·`UNDECIDED`·`FAIL`) 한 줄이다. `UNDECIDED`는 정상적으로 나올 수 있다 —
L1·L2 중 하나가 게이트에 거부된 CU(`HINT_CU_WITHOUT_L12`)와 짧은 정답(1자)의 글자 축 유보(`HINT_UNDECIDED_L12`)가
그 원인이다. 위 "순환 측정" 경고대로 `HINT_LEAKED_L12`는 0이 구조적 기대값이다.

---

## [G] 산출물 브랜치 커밋·push + 원격 대조 — 창 ① (쓰기 · git 브랜치 1개 · 1~2분)

세션은 이 PC의 파일을 직접 볼 수 없다 — **git 브랜치로 넘겨받는다.** `data/runs/` 아래 새 파일만 커밋해 브랜치
`eos211/cu-hint-output`으로 push한다. main에는 push하지 않는다(main은 머지 큐 전용). **다른 파일이 바뀌어 있으면
커밋하지 않는다.**

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [G] 산출물 커밋·push (쓰기 · 원격 브랜치 1개)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos211
$Branch = "eos211/cu-hint-output"
$EmailSet = [bool](git config user.email)
$NewFiles = @(git status --porcelain --untracked-files=all -- data/runs).Count
$OtherDirty = @(git status --porcelain -- . ':!data/runs').Count
$RemoteExists = [bool](git ls-remote --heads origin $Branch)
$Expected = @("eos197-a6-local\cu.hints.genlog.jsonl", "eos197-a6-local\cu.hints.context.jsonl", "eos197-a6-openrouter\cu.hints.genlog.jsonl", "eos197-a6-openrouter\cu.hints.context.jsonl", "eos197-a6-review\g3_content_measures_eos211.json")
$MissingG = @($Expected | Where-Object { -not (Test-Path "$Runs\$_") })
"PRECHECK_G EmailSet=$EmailSet NewFiles=$NewFiles OtherDirty=$OtherDirty RemoteBranchExists=$RemoteExists MeasureJson=$(Test-Path $MeasureJson)"
"EXPECTED_FILES_MISSING=$($MissingG.Count) $($MissingG -join ' ')"
if ($EmailSet -and ($NewFiles -gt 0) -and ($OtherDirty -eq 0) -and (-not $RemoteExists) -and (Test-Path $MeasureJson)) {
  git checkout -B $Branch
  git add -- data/runs
  git commit -m "EOS-211: CU 사후 힌트 패스 산출물 — EOS-197 A6 두 좌석 cu.hints 4종 + G3 소급 측정 리포트 (Kiki 머신 실행분)"
  $LocalSha = git rev-parse HEAD
  $MainShaG = git rev-parse origin/main
  $HeadNotMain = [bool]($LocalSha -and $MainShaG -and ($LocalSha -ne $MainShaG))
  $CommittedRuns = @(git show --name-only --format= HEAD -- data/runs | Where-Object { $_ }).Count
  "LOCAL_SHA=$LocalSha MAIN_SHA=$MainShaG HEAD_NOT_MAIN=$HeadNotMain COMMITTED_RUNS_FILES=$CommittedRuns COMMITTED_FILES=$(@(git show --name-only --format= HEAD | Where-Object { $_ }).Count)"
  if ($HeadNotMain -and ($CommittedRuns -gt 0)) {
    git push -u origin $Branch
    $RemoteSha = ((git ls-remote origin "refs/heads/$Branch") -split "\s+")[0]
    $RemoteIsCommit = [bool]($RemoteSha -and ($RemoteSha -eq $LocalSha))
    "REMOTE_SHA=$RemoteSha REMOTE_IS_COMMIT=$RemoteIsCommit"
    "PUSH_VERIFIED=$($HeadNotMain -and ($CommittedRuns -gt 0) -and $RemoteIsCommit) — HEAD_NOT_MAIN=$HeadNotMain COMMITTED_RUNS_FILES=$CommittedRuns REMOTE_IS_COMMIT=$RemoteIsCommit(셋 다 True·1 이상이어야)"
  } else { "PUSH_REFUSED=True PUSH_VERIFIED=False — push하지 않았다. HEAD_NOT_MAIN=$HeadNotMain(True여야 — False면 커밋이 실패했다: 위 git commit 출력을 회신) COMMITTED_RUNS_FILES=$CommittedRuns(1 이상이어야)" }
} else { "WRITE_REFUSED=True — 커밋·push하지 않았다. EmailSet=$EmailSet(True여야) NewFiles=$NewFiles(1 이상이어야) OtherDirty=$OtherDirty(0이어야 — 산출물 밖 변경이 있으면 목록을 회신) RemoteBranchExists=$RemoteExists(False여야 — 이미 있으면 앞 push가 성공한 것일 수 있다. 회신하세요) MeasureJson=$(Test-Path $MeasureJson)(True여야 — [F]를 먼저)" }
```

**판정**: `PUSH_VERIFIED=True`(커밋이 실제로 만들어졌고 · 마지막 커밋에 `data/runs/` 파일이 있고 · 원격 브랜치 끝이 그
커밋이다 — push 성공 메시지가 아니라 원격을 다시 읽어 대조한다). `EXPECTED_FILES_MISSING=0`이면 두 좌석의 생성 로그·
문맥 파일과 측정 리포트가 모두 실렸다(한 좌석이 실패했다면 그 좌석 파일만 빠지는 것이 정상이다). `cu.hints.jsonl`·
`cu.hints.rejected.jsonl`은 통과·거부가 0건이면 만들어지지 않으므로 기대 목록에 넣지 않았다.

**회신할 것**: [B]의 `HEAD_LOG`·`READY_B` · [C]의 `ROUTE_CHECK`·`READY_LOCAL`·`READY_CLOUD` · [D]·[E]의 요약 줄 전부
(`RUN_DIR=`부터 `EXIT=`까지)와 마지막 `…_PASS_EXIT=` 줄 · [F]의 출력 전부 · [G]의 `PUSH_VERIFIED` 줄.

---

## [H] (선택) 워크트리 정리 — 세션이 수신을 확인한 **뒤에만**

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [H] 워크트리 정리 (쓰기 · 세션의 수신 확인 뒤에만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos211"
$Branch = "eos211/cu-hint-output"
$WtSha = git -C $Wt rev-parse HEAD
$RemoteShaH = ((git ls-remote origin "refs/heads/$Branch") -split "\s+")[0]
$SafeH = [bool]($WtSha -and ($WtSha -eq $RemoteShaH))
"PRECHECK_H WorktreeSha=$WtSha RemoteSha=$RemoteShaH Safe=$SafeH"
if ($SafeH) { git worktree remove $Wt; "WORKTREE_REMAINS=$(Test-Path $Wt)" } else { "WRITE_REFUSED=True — 지우지 않았다. 워크트리 커밋($WtSha)이 원격 브랜치($RemoteShaH)와 같아야 지운다 — 산출물이 원격에 없으면 지우면 안 된다" }
```

---

## 근거 (이 런북의 주장이 기대는 코드)

| 주장 | 근거 |
|---|---|
| 로컬 좌석 = 기본 신호 → LOCAL·QUALITY, openrouter = premium+5000 → CLOUD_MID | `cu_hint_pass.routing_request_for`(sync=False·task_type=generate) · `l3/router.py` `business_cost_tier` 규칙 1·2·4·축2 규칙 2 · 회귀 `test_cu_hint_pass.py::TestRouting` |
| 입력 오류면 LLM 0건 · exit 2 | `run_cu_hint_pass`(로드·재개 검사 후에만 호출) · `TestInputErrors` |
| 재실행은 완료 CU를 다시 부르지 않고, 미완 CU는 총 시도 예산 안에서(게이트 거부 포함) 다시 만든다 | `cu_hint_pass._run_cu`·`_load_resume_state` · `TestResume`·`TestRegeneration` |
| 손상 줄은 지우지 않고 `.corrupt`로 격리한다 · 미처리 예외는 `EXIT=3` | `_quarantine_damaged_lines`·`run_cli` · `TestP3Hardening` |
| 측정기가 `cu.hints.jsonl`을 그대로 읽는다 | `ops/g3_content_measures.load_hints` · `TestNormalPathWithMeasurer`(실데이터 CU로 PASS 판정 동결) |
| Ollama 기본 타임아웃 30초 | `config.py` `ollama_request_timeout_s` 기본값 · EOS-197 `cu.genlog.jsonl`의 `ReadTimeout` 행 |
