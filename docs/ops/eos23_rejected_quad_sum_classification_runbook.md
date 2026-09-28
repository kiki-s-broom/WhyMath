# EOS-23 거부 30건 전수 분류 런북 (Phaiakes9 · 읽기 전용)

> **태스크**: `EOS-23-authoring-seat-generation-accuracy` acceptance ②·③(오프라인 축)
> **전제**: 이 런북의 CLI(`whymath_backend.harness.tier1_rejection_classifier`)가 **main에 머지된 뒤** 실행한다. 머지 전에는 [B]의 코드 출처 검사가 실행을 거부한다.
> **기대 해시**: [A]의 마지막 줄 `git log -1 --oneline`이 머지 커밋과 같아야 한다 — 머지 후 세션이 이 줄에 해시를 기입한다. 해시를 눈으로 대조하지 못해도 [B]가 `HEAD == origin/main`을 스스로 검사한다.
> **Anthropic API 호출 0 · LLM 호출 0 · DB 0 · 네트워크 0**(ARCH-66 준수). `git fetch`·`git pull`만 GitHub에 닿는다.

---

## 1. 과제 명칭

EOS-121 anthropic 좌석의 `quad-sum` 게이트 거부 30건을 **산술 오류(ⓐ) / 표현 불일치(ⓑ) / 판정불가**로 기계 전수 분류한다.

## 2. 목적

EOS-121 회차에서 anthropic 좌석은 "두 근의 합" spec 30건을 **전부** `정확성 실패 — Tier1 답 검산 fail: 조건 위반 — 잔차 ≠ 0`으로 거부당했다. 이 사유는 두 경우에 똑같이 난다.

- **ⓐ 산술 오류** — 모델이 답을 틀렸다.
- **ⓑ 표현 불일치** — 문항은 옳은데, 검산 조건은 `x`를 **근**으로 묶고 답은 `x`에 **근의 합**을 담았다. 그러면 잔차가 0이 아닌 게 당연하다.

두 경우는 처방이 정반대다(ⓐ면 저작 프롬프트 교정, ⓑ면 검산 계약 쪽). 그래서 **고치기 전에 먼저 가른다**(acceptance ⑤ "미분류 상태에서 코드부터 고치지 않는다").

거부된 30건의 본문(문항·정답·검산 조건)은 Kiki 머신의 `.eos121-out\anthropic.review.jsonl`에만 있다(gitignore 폴더). 파일을 옮기지 않고 **그 자리에서 분류기를 돌려 요약 JSON만 회신**받는 것이 이 과제다. 유료 회차를 다시 돌리지 않는다(acceptance ② "회수 전에 유료 회차를 계획하면 180호출을 또 태운다").

결과는 EOS-23 ③의 ⓐ/ⓑ/판정불가 건수가 되고, EOS-121 판정문의 "수학적으로 틀린 문제를 만들었다"를 확정하거나 정정하는 근거가 된다.

## 3. 구체적 절차와 예상 출력

| 블록 | 무엇을 하나 | 쓰기 | 예상 시간 |
|---|---|---|---|
| [A] | main 최신화 + 커밋 확인 | 작업 사본의 브랜치 전환 | 1분 |
| [B] | 코드 출처·버전·입력 파일 검사 후 분류 실행 | `.eos121-out\eos23_classification.json` 1개 | 10~30초 |

분류기는 행마다 다음을 한다(코드 경로는 §8).

1. 대상 확인 — `status == rejected_gate`이고 후보 본문이 있는 행, 그리고 `spec_id == quad-sum`
2. 재현 — 게이트와 같은 함수(`verify_answer`)로 다시 검산해 정말 fail인지 본다. 재현이 안 되면 그 행은 판정불가다.
3. 해집합 — 조건을 게이트와 같은 파서로 읽고 SymPy로 근을 구한다.
4. 대조 — 답이 근이면 모순(판정불가). 답이 근의 합·곱·차의 절댓값·제곱의 합·역수의 합 중 하나와 같으면 ⓑ. 아무것과도 안 맞고 모든 비교가 확정되면 ⓐ. 확정 못 한 비교가 있으면 판정불가.

**[B]의 예상 출력** (머지 후 실측 전이므로 형식만):

> 앞쪽에 `LOADED_FROM=`·`CODE_FROM_MAIN_CLONE=True`·`HEAD_IS_ORIGIN_MAIN=True`·`TREE_MATCHES_MAIN=True`·`FOUND=… SHA256=…`·`REVIEW_FILE=…`·`READY=True` 줄이 나온다.
> 이어서 `{`로 시작하는 JSON이 나온다. 그 안에 `"target_rows": 30`, `"verdict_counts": {"arithmetic_error": …, "representation_mismatch": …, "undecidable": …}`, `"by_spec"`, `"undecidable_reason_codes"`, `"matched_derived_counts"`가 있고, 끝에 `"rows": [` 아래로 **행이 한 줄에 하나씩** 30줄 나온다.
> 마지막 줄은 `CLASSIFY_EXIT=0`이다.

한국어는 JSON 안에서 `\uXXXX` 형태로 나온다. **정상이다** — 콘솔을 거쳐도 글자가 깨지지 않도록 일부러 ASCII로만 출력한다(PowerShell 5.1이 네이티브 출력을 cp949로 디코딩·재인코딩하는 문제, CLAUDE.md 인코딩 규칙).

**회신 방법**: [B]가 출력한 `{`부터 `}`까지의 JSON과 `CLASSIFY_EXIT=` 줄을 채팅에 붙여 주시면 된다. 문항 본문 전문은 `.eos121-out\eos23_classification.json`에 저장되며, 세션이 요청할 때만 보내 주시면 된다.

## 4. 성공 기준과 실패 시 대처

**성공**: `READY=True`이고 `CLASSIFY_EXIT=0`이고, JSON에서 `"measured": true`, `"target_rows": 30`, 세 판정 건수의 합이 30이다.

**실패 신호와 대처**:

- **`RUN_REFUSED=True`** — [B]가 스스로 실행을 거부했다. 같은 줄에 False인 항목이 찍힌다.
  - `CodeOk=False` — 분류기 모듈을 이 클론에서 임포트하지 못했다. 대개 머지 전이거나 [A]를 건너뛴 것이다. [A]를 다시 실행한다.
  - `HeadOk=False` 또는 `TreeOk=False` — 작업 사본이 main 끝이 아니다. [A]의 `git checkout main`이 오류를 냈는지 본다(아래).
  - `FileOk=False` — 두 후보 위치 어디에도 `anthropic.review.jsonl`이 없다. `FOUND=` 줄이 하나도 없을 것이다. 그 사실 자체를 회신해 주시면 된다(파일을 다른 곳에 옮기셨다면 그 위치를 알려 주시면 된다).
- **`CLASSIFY_EXIT=2`** — 파일은 열었지만 분류 대상이 **0건**이다. JSON의 `skipped`에 어떤 상태·spec의 행이 몇 건 있었는지 나온다. 공허한 통과를 막으려고 일부러 실패로 처리한다. JSON을 그대로 회신해 주시면 된다.
- **`CLASSIFY_EXIT=1`** — 대상은 분류했지만 **읽지 못한 줄**이 있다. `load_errors`에 줄 번호와 예외 타입명이 나온다. 결과는 그래도 유효한 부분 측정이므로 JSON을 그대로 회신해 주시면 된다.
- **[A]에서 `git checkout main`이 오류를 낸다** (`Your local changes … would be overwritten` 등) — 다른 세션의 미커밋 변경이 걸려 있는 것이다. **`git stash`·`git checkout --`로 지우지 말고** 오류 출력을 그대로 회신해 주시면 된다. 세션이 작업 사본을 건드리지 않는 대체 블록을 드린다.

## 5. 실행 환경

| 항목 | 값 |
|---|---|
| 머신 | **Phaiakes9** = Kiki의 작업 PC 그 자체(별도 접속·SSH 불요) |
| 시스템 | Windows PowerShell |
| 작업 디렉터리 | `C:\Users\kiki\Desktop\__AI\WhyMath` |
| 선행 조건 | 이 런북의 분류기가 main에 머지돼 있을 것 |
| 불요 | Docker · DB · 서버 · API 키 (전부 쓰지 않는다) |
| 입력 파일 후보 | `C:\Users\kiki\Desktop\__AI\WhyMath-eos121\.eos121-out\anthropic.review.jsonl`(EOS-121 회차가 돈 worktree) → 없으면 `C:\Users\kiki\Desktop\__AI\WhyMath\.eos121-out\anthropic.review.jsonl` |

**입력 파일 위치를 두 곳 보는 이유**: EOS-121 회차 런북은 `WhyMath-eos121` worktree에서 돌았으므로 원본은 그쪽 `.eos121-out`에 생겼다. worktree를 지우면서 원 클론으로 옮겨 두셨을 수도 있어 둘 다 본다. 둘 다 있으면 worktree 쪽을 쓰고, 두 파일의 SHA256을 모두 출력하므로 같은 파일인지 회신에서 보인다.

## 6. 창 구분

**창은 하나면 된다.** 서버를 띄우지 않으므로 점유 창이 없다. 새 PowerShell 창을 하나 열어 [A]와 [B]를 순서대로 붙여넣는다. [B]가 끝나면 그 창은 자유롭게 써도 된다.

---

## [A] main 최신화 + 커밋 확인

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin
git checkout main
git pull --ff-only origin main
git status --short --branch
git log -1 --oneline
```

마지막 줄이 머지 커밋이어야 한다(맨 위 "기대 해시" 참조). `git status`의 첫 줄은 `## main...origin/main`이어야 한다. 오류가 나면 §4의 마지막 항목을 따른다.

## [B] 검사 + 분류 실행 (쓰기는 결과 파일 하나)

**이 블록은 선행 조건을 스스로 다시 검사하고, 하나라도 False면 분류기를 실행하지 않는다.** [A]의 출력을 눈으로 본 것만으로는 흐름이 멈추지 않기 때문이다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend"
$VenvPy = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$SysPy = (Get-Command python -ErrorAction SilentlyContinue).Source
$PyExe = @(@($VenvPy, $SysPy) | Where-Object { $_ -and (Test-Path $_) })[0]
$Src = & $PyExe -c "import whymath_backend.harness.tier1_rejection_classifier as m; print(m.__file__)"
$CodeOk = [bool]($Src -like "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\*")
$HeadOk = (git rev-parse HEAD) -eq (git rev-parse origin/main)
git diff --quiet origin/main -- src/backend/whymath_backend
$TreeOk = ($LASTEXITCODE -eq 0)
$Cands = @("C:\Users\kiki\Desktop\__AI\WhyMath-eos121\.eos121-out\anthropic.review.jsonl", "C:\Users\kiki\Desktop\__AI\WhyMath\.eos121-out\anthropic.review.jsonl")
$Found = @($Cands | Where-Object { Test-Path $_ })
$Found | ForEach-Object { Write-Output ("FOUND=" + $_ + " SHA256=" + (Get-FileHash $_ -Algorithm SHA256).Hash) }
$Review = @($Found)[0]
$FileOk = [bool]$Review
$OutFile = "C:\Users\kiki\Desktop\__AI\WhyMath\.eos121-out\eos23_classification.json"
$Ready = $CodeOk -and $HeadOk -and $TreeOk -and $FileOk
Write-Output "PYTHON=$PyExe"
Write-Output "LOADED_FROM=$Src"
Write-Output "CODE_FROM_MAIN_CLONE=$CodeOk  HEAD_IS_ORIGIN_MAIN=$HeadOk  TREE_MATCHES_MAIN=$TreeOk"
Write-Output "REVIEW_FILE=$Review  FILE_FOUND=$FileOk"
Write-Output "READY=$Ready"
if ($Ready) { New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null; & $PyExe -m whymath_backend.harness.tier1_rejection_classifier $Review --spec quad-sum --json --out $OutFile; Write-Output "CLASSIFY_EXIT=$LASTEXITCODE" } else { Write-Output "RUN_REFUSED=True — CodeOk=$CodeOk HeadOk=$HeadOk TreeOk=$TreeOk FileOk=$FileOk · 4절의 대처를 보세요" }
```

**각 검사가 무엇을 막는가** (변별력):

- `CODE_FROM_MAIN_CLONE` — 임포트된 분류기 파일의 실제 경로(`__file__`)를 본다. 머지 전이면 모듈이 없어 임포트가 실패하고 빈 값이 되어 False다. 다른 클론(예: `WhyMath-eos121` worktree)에 editable 설치된 코드가 임포트되는 경우도 경로가 달라 False다.
- `HEAD_IS_ORIGIN_MAIN` — 경로가 아니라 **버전**을 본다. [A]를 건너뛰어 옛 main이면 False다. 기대 해시를 하드코딩하지 않고 `origin/main`과 비교하므로 런북이 낡지 않는다.
- `TREE_MATCHES_MAIN` — 백엔드 소스에 **미커밋 변경**이 있으면 False다. 공유 작업 사본이라 다른 세션의 변경이 남아 있을 수 있기 때문이다(백엔드 밖의 미커밋 파일은 막지 않는다).
- `FILE_FOUND` — 두 후보 위치 중 하나라도 있으면 True. 없으면 분류기를 돌리지 않는다.

**쓰기 범위**: `.eos121-out\eos23_classification.json` 한 파일(gitignore 폴더)뿐이다. 입력 파일은 읽기만 한다.

---

## 7. 회신에서 무엇을 읽는가

- **`verdict_counts`** — 핵심 결과. ⓐ(`arithmetic_error`)와 ⓑ(`representation_mismatch`)의 비율이 EOS-23 ⑤ 처방 방향을 정한다.
- **`matched_derived_counts`** — ⓑ로 판정된 행이 어떤 파생량을 담았는지. `sum`이 대부분이면 "발문은 합을 묻고 답도 합인데 조건만 근을 묶었다"는 형태다.
- **`aggregate_gate_would_pass`** — 게이트의 기존 근 집계 검증기(`verify_root_aggregate`)가 이 행을 통과시켰을 건수. 이 값이 크면 **검산 계약은 이미 파생량 답을 표현할 수 있는데 저작 경로가 그 선언(`answer_aggregate`)을 쓰지 않는다**는 뜻이다(아래 §9 관찰 참조).
- **`stem_consistent_counts`** — 보조 신호. ⓑ 행에서 일치한 파생량을 발문 문구도 묻는지. 판정의 근거가 아니라 교차 확인용이다.
- **`undecidable_reason_codes`** — 판정불가 사유 분포. `not_reproduced`가 많으면 게이트와 분류기의 재검산이 어긋난 것이고, 그 자체가 조사 대상이다.
- **`reproduced_direct_branch_rows`** — 재현된 fail이 EOS-121 사유와 같은 분기(`잔차 ≠ 0`)에서 났는지.
- **`run_ids`·`distinct_payloads`** — 파일에 다른 회차 행이 섞였는지, 같은 후보가 중복 기록됐는지.

## 8. 이 런북의 명령이 기대 산출물을 내는지 — 저장소 코드 경로로 확인한 것

PowerShell 블록은 컨테이너에서 실행할 수 없다. 그래서 **Python CLI 부분만** 실제로 돌려 확인했다.

- 진입점: `python -m whymath_backend.harness.tier1_rejection_classifier <review.jsonl> --spec quad-sum --json --out <파일>` — 모듈의 `main()`이 `if __name__ == "__main__"`으로 연결돼 있다.
- 입력 매체: `.eos121-out\anthropic.review.jsonl`은 EOS-121 런북 [E]의 `problem_corpus_accumulate --worklist-out`이 쓴다. 그 행은 `problem_corpus_accumulate._queue_entry` → `_to_record` → `_record_to_json`으로 조립되고 `append_review_queue_jsonl`로 기록된다. 분류기는 같은 모듈의 `load_review_queue_jsonl`로 읽는다.
- 테스트 픽스처도 **같은 조립·기록 경로**로 만든다. `ScriptedGenerator` 후보를 실제 오케스트레이터(`run_equivalent_generation`)에 흘려 게이트가 실제로 낸 거부 사유를 얻는다(`tests/backend/harness/test_tier1_rejection_classifier.py`의 `TestFixtureFidelity`가 사유 문자열 `Tier1 답 검산 fail: 조건 위반 — 잔차 ≠ 0`을 단언한다).
- 컨테이너 실측: 위와 같은 방식으로 만든 `.eos121-out/anthropic.review.jsonl` 픽스처(ⓑ·ⓐ·대조군·비대상 행 혼합)에 런북과 같은 인자로 모듈을 실행했다. 결과: 종료 코드 0, stdout은 전부 ASCII이고 `json.loads`로 읽혔으며 행 수는 대상 수와 같았고, `--out` 파일이 생성됐다. 입력 파일을 없는 경로로 주면 종료 코드 2와 `"measured": false`가 나온다.

## 9. 관찰 — 분류와 별개로 코드에서 확인된 사실 (판정 아님)

저작 LLM 경로(`l3/equivalent/llm_generator.py`)의 출력 스키마(`_OUTPUT_JSON_SCHEMA`)와 조립 함수(`_assemble`)에는 **`answer_aggregate` 필드가 없다**. 게이트에는 근의 합·곱 답을 검증하는 경로(`answer_aggregate in ("sum", "product")` → `verify_root_aggregate`)가 이미 있지만, LLM이 만든 후보는 그 선언을 할 방법이 없어 항상 Tier1(답이 근인가) 경로로 간다. 또 `answer_selection`이 스키마 필수라 "두 근의 합" 문항도 `largest`/`smallest`/`unique` 중 하나를 선언해야 한다.

이것은 ⓑ 가설과 **정합하는 구조적 사실**일 뿐 분류 결과가 아니다. 판정은 회신된 전수 분류로만 한다(acceptance ③). 처방이 이 축으로 가더라도 acceptance ⑤에 따라 실패 주입으로 변별력을 증명한 뒤에만 보호로 친다.

## 10. 한계

- **판정의 주 근거는 수식 일관성이다.** 답이 파생량과 "우연히" 같을 가능성은 남는다(예: 산술 오류의 결과가 마침 제곱의 합과 같음). `matched_derived`와 `stem_consistent`를 함께 보면 이 경우가 드러난다 — 발문이 합을 묻는데 일치한 것이 제곱의 합이면 우연을 의심한다.
- **라이브 축은 수행하지 않았다.** ARCH-66에 따라 Anthropic 재측정·대조 회차(acceptance ④의 좌석당 15회)는 `G-arch66-anthropic-api-pause-review` 전까지 돌리지 않는다. 이 런북은 이미 영속된 30건만 본다 — 미측정을 통과로 계상하지 않는다.
- EOS-121 판정문의 「정직한 한계」(각 좌석 1회차·단일 성취기준·이차방정식 한정·`top_p` 미통제)가 그대로 승계된다.
