# MP-02 카나리 검수 런북 — 카나리 구간 절단 → 30건 판정 (Phaiakes9 실행)

> **작성**: claude · **실행 주체**: Kiki · **작성일** 2026-09-21
>
> 대상 태스크 `MP-02-first-llm-authoring-run` **acceptance ②** · 소유 태스크 `MP-07-canary-review-runbook`
>
> 이 런북이 닫는 게이트 = `G-eos-first-run-canary-review` (2026-09-06 요청 · 15일 경과)

---

## ⛔ 선행 조건 — 이것부터 확인하십시오

이 런북은 **MP-02 회차(`docs/reviews/mp02_first_llm_authoring_run_runbook.md` §1~§5)가 먼저 돌아야**
실행됩니다. 회차가 만든 사이드카 3종(`.rounds.jsonl` 대장 · `.genlog.jsonl` 생성 로그 ·
`.review.jsonl` 검수 큐)이 이 런북의 **입력**이기 때문입니다.

> 「실측 2026-09-21」 2026-09-10 회차는 **두 번 돌았고 두 번 다 `accepted=0`** 이었습니다. 그
> 회차로도 §2가 기술적으로는 돌아갈 수 있지만, **승격 원천이 0건인 검수**가 될 수 있습니다 —
> §3의 판정 지점이 그것을 먼저 알려 줍니다. 그러니 §3을 건너뛰지 마십시오.

또한 MP-02 런북 자체에 **사이드카 경로 계산 버그**가 있었습니다(`MP-06`에서 정정 중). 정정본이
main에 착지한 뒤 회차를 다시 돌리시는 것을 권합니다.

---

## 0. 사전 브리핑 (6항목)

### ① 과제 명칭
첫 LLM 저작 회차의 **카나리 30건 100% 검수** — 회차 앞머리 구간을 잘라내 한 건씩 판정합니다.

### ② 목적
이 회차가 만든 문항 중 **앞 30건**(카나리 구간)을 Kiki가 직접 보고 승인/반려합니다. 두 가지가
여기서 나옵니다 — ⓐ **골든셋 승격 원천**(승인된 문항이 이후 벤치마크의 정답지가 됩니다)
ⓑ **HIT 측정치**(문항 1건당 사람이 실제로 쓴 시간 — EOS 검증의 F-Ⅰ 지표). 눈으로만 보고
기록을 남기지 않으면 둘 다 생기지 않습니다.

### ③ 구체적 절차
§1 환경 자가검증(1분) → §2 카나리 구간 절단(즉시) → §3 **검수 가치 판정**(1분·여기서 멈출 수
있습니다) → §4 30건 판정(30~60분 예상) → §5 증적 확인·회신(2분).

### ④ 성공 기준
§2가 `"written": true` · `"emitted": 30` · `"unresolved_count": 0`을 내고, §4가 `승인 + 수정승인 +
반려`의 합이 §2의 `emitted_distinct_slugs`와 같은 상태로 끝나며, §5의 `VERDICT_LINES`가 그 같은
숫자이면 성공입니다. **분모는 30이 아니라 `emitted_distinct_slugs`입니다** — 검수 도구가 같은
문항(같은 slug)을 한 번만 보여 주므로, 회차 안에 중복이 있으면 판정 건수가 30보다 적은 것이
정상입니다(중복이 있는데 30이 나오면 오히려 이중 계측입니다). 실패 신호와 대처는 각 절에
함께 적었습니다.

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`.
별도 접속·WSL 진입 불요. **서버·Docker 가동 불요**(이 런북은 파일만 읽고 씁니다 — DB도 LLM도
쓰지 않습니다).

### ⑥ 창 구분
**창 ① 하나만** 쓰며, 처음부터 끝까지 같은 창에서 진행합니다. 장기 점유 프로세스가 없으므로
중간에 다른 명령을 넣으셔도 안전합니다. 단 §4는 **대화형**이라 그 창이 입력을 기다립니다 —
§4가 끝난 뒤에 다음 명령을 넣으십시오.

---

## 1. 환경 자가검증 — 창 ①

> **브랜치를 옮기지 않습니다.** 이 클론은 여러 세션이 공유하는 단일 작업 사본이라 다른 세션의
> 미커밋 변경이 상시 존재할 수 있습니다. `git checkout`으로 트리를 옮기는 대신, **이 런북이 읽는
> 경로만 main과 같은지** 확인합니다 — 무관한 파일이 더러워도 통과하고 실행 입력이 다르면 막는
> 검사입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git diff --quiet origin/main -- src/backend/whymath_backend/harness/ src/backend/whymath_backend/ops/
"CODE_MATCHES_MAIN=$($LASTEXITCODE -eq 0)"
$Py = ".\.venv\Scripts\python.exe"
& $Py -c "import whymath_backend.harness.canary_slice as m; print('CANARY_SLICE_FILE', m.__file__)"
"IMPORT_EXIT=$LASTEXITCODE"
```

**판정**: `CODE_MATCHES_MAIN=True` · `IMPORT_EXIT=0` · `CANARY_SLICE_FILE` 출력, 셋 다 나와야
통과입니다. `CANARY_SLICE_FILE` 경로가 `...\WhyMath\src\backend\...`로 시작하는지 눈으로
확인해 주십시오 — **파일을 검사하는 것만으로는 그 파일이 실제로 임포트됐는지 모르기 때문에**
임포트 후 `__file__`을 직접 출력합니다.

**실패 시**:
- `CODE_MATCHES_MAIN=False` → 다른 세션의 변경이 실행 입력에 섞여 있습니다. 작업 사본을 건드리지
  않는 별도 워크트리에서 돌리십시오:
  `git worktree add --detach C:\Users\kiki\Desktop\__AI\wm-mp07 origin/main`
  (끝나면 `git worktree remove C:\Users\kiki\Desktop\__AI\wm-mp07`)
- `ModuleNotFoundError` → 의존성 미설치입니다. `& $Py -m pip install -e .\src\backend`를 돌린 뒤
  이 블록을 다시 실행하십시오(실행기 단독 `pip` 금지 — `python -m pip`로 같은 인터프리터를 강제).

---

## 2. 카나리 구간 절단 — 창 ①

회차 앞머리 `canary_size`건을 검수 큐 JSONL로 잘라냅니다. **식별 근거는 genlog의 적재 순서**이고,
**크기는 회차 대장의 `canary_size` 필드**입니다(둘 다 도구가 읽습니다 — 30을 손으로 넣지 않습니다).

> **왜 `cmd /c`로 감싸는가**: 이 요약 JSON에는 한국어 사유 문자열이 들어갑니다. PowerShell 5.1은
> 네이티브 명령의 stdout을 `[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 디코딩한 뒤
> 재인코딩하는데, 그 과정에서 UTF-8 3바이트 문자의 경계가 어긋나 **JSON 구조 문자(`"`)가
> 유실됩니다**. 출력 인코딩을 명시해도 막히지 않으므로(이미 깨진 문자열을 성실히 쓸 뿐) 경유
> 자체를 없앱니다 — 바이트가 셸을 통과하지 않습니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$env:PYTHONIOENCODING = "utf-8"
cmd /c ".venv\Scripts\python.exe -m whymath_backend.harness.canary_slice --out data\corpus\problem_bank_mp02_first_run_v0\problems.jsonl --queue-out data\corpus\problem_bank_mp02_first_run_v0\canary_review_queue.jsonl > mp02_canary_slice.json 2> mp02_canary_slice.err"
"SLICE_EXIT=$LASTEXITCODE"
Get-Content mp02_canary_slice.json -Encoding UTF8
Get-Content mp02_canary_slice.err -Encoding UTF8
```

**판정**: `SLICE_EXIT=0`이고 요약 JSON에 `"written": true`가 있으면 통과입니다.

**요약 JSON에서 반드시 눈으로 보실 여섯 줄**:

| 필드 | 기대값 | 다르면 |
|---|---|---|
| `canary_size` | 30 | 대장 기록값입니다. 다르면 회차가 다른 설정으로 돌았습니다 |
| `emitted` | `canary_size`와 같음 | 적으면 카나리 구간이 덜 채워진 것입니다 — 아래 shortfall 참조 |
| `unresolved_count` | 0 | 0이 아니면 `unresolved` 배열에 건별 사유가 있습니다 |
| `duplicate_slug_rows` | **0이 아닐 수 있습니다** | 산출 행 중 같은 slug가 두 번 이상 실린 수입니다. 2026-09-21 회차는 비-0이 정상입니다(모델이 같은 구조를 반복) |
| `emitted_distinct_slugs` | `emitted` − `duplicate_slug_rows` | **이것이 실제 검수 분모입니다.** §4·§5의 완주 판정은 이 숫자로 합니다 |
| `queue_duplicate_slug_rows` | 0이 아닐 수 있습니다 | 큐 색인에서 제외된 중복 행 수(첫 행 채택). **거부 사유가 아닙니다** — 건별 사유는 `queue_duplicate_slugs`에 줄 번호까지 실립니다 |

> **왜 분모가 `emitted`가 아닌가**: 검수 도구는 같은 slug를 **한 번만** 보여 줍니다
> (`review_session.py:216` — 「같은 CU가 큐에 두 번 오면 한 번만 검수한다 — 중복 계측은 HIT를
> 부풀린다」). 그래서 큐 30행에 고유 19건이 들어 있으면 판정은 19건만 생성되고, 분모를 30으로
> 잡으면 **완주한 검수가 영원히 미완주로 보입니다**. 초판 런북이 그렇게 적혀 있었고 그 상태로는
> 게이트가 증적을 다 갖춘 채로 닫히지 않습니다 — `MP-10`에서 정정했습니다.

**`SLICE_EXIT=1`인 경우 — 전부 설계된 거부입니다**(도구가 stderr에 사유를 냅니다):

- `canary_size가 미기록(None)` → 그 회차가 MP-04 이전 기록입니다. 기본값 30을 가정해 채우지
  않습니다(모른다 ≠ 아니다). → 회차를 다시 돌리셔야 합니다.
- `회차 대장에 손상된 행 N건` → 어느 회차가 최신인지 판정할 수 없습니다. → `--run-id <회차>`를
  붙여 회차를 명시하면 진행합니다.
- `생성 로그에 손상된 행 N건` → 적재 순서가 카나리 구간의 유일한 근거라, 행 하나가 빠지면 뒤
  시도가 앞당겨져 **다른 구간**이 카나리로 보고됩니다. 부분 산출도 내지 않습니다. → 해당 줄을
  고친 뒤 재실행.
- `카나리 N건 중 해결 0건` → 검수 큐를 **만들지 않습니다**(빈 큐를 남기면 0건을 검수하고
  "전건 검수"로 보고하게 되므로). → §3으로 가서 원인을 보십시오.

**`[부분 산출]` 경고가 stderr에 나온 경우**: genlog 행이 `canary_size`보다 적습니다(회차가 중도
중단). 이때 `"shortfall"` 블록에 `expected`·`observed`·`missing`이 실립니다. **검수 분모가 30이
아니게 되므로**, 이 상태로 검수하시면 게이트 증적은 "카나리 30건 검수"가 아니라 "카나리 N건
검수"입니다 — §5 회신에 그 숫자를 그대로 적어 주십시오.

---

## 3. 검수 가치 판정 — 창 ① (1분 · **여기서 멈출 수 있습니다**)

§2 요약 JSON의 `resolved_from` 세 칸을 봅니다. 이 세 숫자가 **검수에 1시간을 쓸 가치가 있는지**를
먼저 말해 줍니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$S = if (Test-Path "mp02_canary_slice.json") { Get-Content "mp02_canary_slice.json" -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
"SUMMARY_READ=$($S -ne $null)"
"EMITTED=$($S.emitted)"
"DISTINCT=$($S.emitted_distinct_slugs)"
"FROM_CORPUS=$($S.resolved_from.corpus)"
"FROM_QUEUE_THIS_RUN=$($S.resolved_from.review_queue_this_run)"
"UNRESOLVED=$($S.unresolved_count)"
if ($S -eq $null) { "판정 불가: §2 요약을 읽지 못했습니다 — §2를 다시 돌린 뒤 이 블록을 다시 실행하십시오." } else { if ($S.resolved_from.corpus -eq 0) { "판정: 승격 원천 0건 — 이 회차는 기계 수용분이 없습니다. §4 검수는 HIT 측정치만 남기고 골든셋 승격 원천은 만들지 못합니다." } else { "판정: 승격 원천 $($S.resolved_from.corpus)건 — §4로 진행하십시오." } }
```

**왜 이 판정이 필요한가**: 게이트 `G-eos-first-run-canary-review`의 선언된 목적은 **골든셋 승격
원천**입니다. 그런데 `FROM_CORPUS=0`이면 30건 전부가 **기계가 이미 반려한 후보**입니다. 그것을
1시간 검수해도 `review_timer` 이벤트 30건은 남아 "카나리 30건을 검수했다"는 증적은 성립하는데,
승격 가능한 문항은 0건입니다 — **증적은 참인데 목적은 달성되지 않는** 상태가 됩니다.

> 「실측 2026-09-21」 2026-09-10 회차는 두 번 다 `accepted=0`이었으므로, 그 회차로 §2를 돌리시면
> `FROM_CORPUS=0`이 나올 가능성이 높습니다. 원인은 저작 프롬프트가 `conditions`·`answer_map`을
> 비우지 말라고 경고하지 않은 것이며, 그 수정은 `MP-06`이 회수 중입니다.

**`FROM_CORPUS=0`일 때 선택지 둘** — Kiki 판단입니다:
- **(권장) 여기서 멈추고 회차를 다시 돌린다** — `MP-06` 정정본 착지 후 MP-02 런북 §1~§5 재실행.
  그 회차로 이 런북을 다시 §2부터 하십시오.
- **그대로 검수한다** — HIT 측정치(F-Ⅰ 지표)만 먼저 확보하고 싶으실 때. 이 경우 §5 회신에
  "승격 원천 0건 회차의 검수"라고 명시해 주십시오. 게이트 clear 증적으로 올릴 때 그 사실이
  함께 기록되어야 합니다.

---

## 4. 30건 판정 — 창 ① (**대화형** · 30~60분)

한 건씩 화면에 뜨고, 판정 키를 누르면 다음 건으로 넘어갑니다. **타이머는 도구가 직접 잽니다** —
사람이 시간을 적어 내는 방식은 기억 왜곡·선의의 반올림으로 지표가 오염되므로 쓰지 않습니다.

### 판정 키 (폐쇄 집합)

| 키 | 의미 | 반려코드 |
|---|---|---|
| `a` | 승인 — 그대로 쓸 수 있다 | 불요 |
| `e` | 수정승인 — 손질하면 쓸 수 있다 | **선택**(손질한 축·Enter로 생략) |
| `r` | 반려 — 못 쓴다 | **필수**(F1~F8 번호만) |
| `s` | 보류 — 지금 판단하지 않는다 | 불요(판정으로 세지 않습니다) |
| `q` | 세션 종료 — 현재 항목은 중단으로 기록 | 불요 |

### 반려코드 F1~F8 (동결 · 자유 텍스트 단독 금지)

| 코드 | 정의 |
|---|---|
| F1 | 수식·파싱 실패 (LaTeX/AST 불가) |
| F2 | 정답 불일치 (SymPy/수치 검증 모순) |
| F3 | 풀이 논리 비약 (인접 단계 비동치·근거 없는 도약) |
| F4 | 성취기준 이탈 |
| F5 | 난이도 미스 |
| F6 | 오개념 오연결 (op-code 매핑 오류) |
| F7 | 언어 수준 부적합 (학교급 어휘·문장) |
| F8 | 힌트 정답 누설 |

`r`은 반려코드가 **없으면 판정 자체가 생성되지 않습니다**(스키마 강제). 애매하면 `s`(보류)로
넘기고 나중에 `--resume`으로 돌아오십시오 — 억지 판정보다 낫습니다.

이 블록은 **스스로 선행 조건을 다시 계산해 거부합니다** — §3의 출력은 흐름을 멈추지 못하므로
사람 판정에만 기대지 않습니다. 두 가지를 재검사합니다: ⓐ §2가 큐를 실제로 썼는가(`written`)
ⓑ 큐 파일의 실제 행 수가 §2가 보고한 `emitted`와 같은가(중간에 다른 회차 큐로 바뀌지 않았는가).

> 이 가드가 `emitted`를 쓰는 것은 맞습니다 — 큐 **파일 행 수**와 대조하는 검사이기 때문입니다.
> 뒤의 **완주 판정**은 그것과 다른 숫자(`emitted_distinct_slugs`)로 합니다. 두 숫자가 다른 것이
> 이 회차의 정상 상태입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 대화형입니다. 끝날 때까지 다른 명령을 넣지 마십시오.
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$QueueOut = "data\corpus\problem_bank_mp02_first_run_v0\canary_review_queue.jsonl"
$Events = "data\corpus\problem_bank_mp02_first_run_v0\canary_review_events.jsonl"
$Verdicts = "data\corpus\problem_bank_mp02_first_run_v0\canary_review_verdicts.jsonl"
$S = Get-Content "mp02_canary_slice.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$QueueLines = if (Test-Path $QueueOut) { (Get-Content $QueueOut | Where-Object { $_.Trim() }).Count } else { -1 }
"SLICE_WRITTEN=$($S.written)"; "EMITTED=$($S.emitted)"; "DISTINCT=$($S.emitted_distinct_slugs)"; "QUEUE_LINES=$QueueLines"
if ($S.written -eq $true -and $QueueLines -eq $S.emitted) { & $Py -m whymath_backend.harness.review_session --queue $QueueOut --events $Events --verdicts $Verdicts --reviewer-id kiki; "REVIEW_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — SLICE_WRITTEN=$($S.written) · QUEUE_LINES=$QueueLines vs EMITTED=$($S.emitted). §2를 다시 돌리십시오." }
```

**`WRITE_REFUSED=True`가 나오면** 검수를 시작하지 않은 것입니다(이벤트·판정 파일에 아무것도
쓰이지 않았습니다). 출력된 두 숫자를 §2 요약과 대조한 뒤 §2부터 다시 하십시오.

**중간에 그만두셔도 됩니다**: `q`로 종료한 뒤, 같은 명령 끝에 `--resume`을 붙여 다시 실행하면
**이미 종결한 건을 건너뜁니다**(이중 계측 방지). 이벤트·판정은 **항목마다 즉시 flush**되므로
중간에 창이 닫혀도 그때까지의 기록은 남습니다.

**판정**: 마지막에 `=== 검수 세션 요약 ===`이 뜨고 `승인 + 수정승인 + 반려`의 합이 §2의
`emitted_distinct_slugs`(= 위 블록의 `DISTINCT`)와 같으면 완주입니다. 합이 적으면 보류·중단이
남은 것이니 `--resume`으로 이어가십시오.

**`emitted`(30)와 비교하지 마십시오.** 중복이 있으면 그 등식은 성립할 수 없고, `--resume`을
반복해도 새로 보여 줄 건이 없습니다(고유 건은 이미 전부 종결). 검수를 시작할 때 도구가 출력하는
대상 건수도 `DISTINCT`와 같아야 합니다 — 그것이 30이면 오히려 이상 신호입니다.

**`REVIEW_EXIT=1`인 경우**: `[입력 실패] 검수 대상 0건`이면 §2의 큐가 비었다는 뜻입니다("0건
통과"가 아니라 측정 실패입니다) → §2·§3으로 돌아가십시오.

---

## 5. 증적 확인 — 창 ①

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$Events = "data\corpus\problem_bank_mp02_first_run_v0\canary_review_events.jsonl"
$Verdicts = "data\corpus\problem_bank_mp02_first_run_v0\canary_review_verdicts.jsonl"
$HaveFiles = (Test-Path $Events) -and (Test-Path $Verdicts)
"FILES_PRESENT=$HaveFiles"
if ($HaveFiles) { "EVENT_LINES=$((Get-Content $Events | Where-Object { $_.Trim() }).Count)"; "VERDICT_LINES=$((Get-Content $Verdicts | Where-Object { $_.Trim() }).Count)"; & $Py -m whymath_backend.ops.hit_cu_metrics --events $Events --verdicts $Verdicts; "HIT_EXIT=$LASTEXITCODE" } else { "READ_REFUSED=True — 검수 산출 파일이 없습니다(§4가 거부됐거나 아직 실행되지 않았습니다). §4부터 다시 하십시오." }
```

**판정**: `VERDICT_LINES`가 §2의 `emitted_distinct_slugs`와 같으면 100% 검수입니다(30이
아닙니다 — §2 표의 분모 설명 참조). `EVENT_LINES`는 타이머
이벤트 수이고, `hit_cu_metrics`가 내는 **적재율**(판정 중 타이머 동반 비율)과 **HIT 중앙값**이
EOS 검증 F-Ⅰ 지표의 입력입니다.

---

## 6. 회신 — 이것만 주시면 됩니다

§1의 `CANARY_SLICE_FILE` 한 줄 · §2의 `SLICE_EXIT`와 요약 JSON 전체 · §3의 다섯 줄 · §4의 세션
요약 전체 · §5의 세 줄과 `hit_cu_metrics` 출력. **출력을 자르지 말고 그대로** 주십시오 — 값이
잘린 채 판단하면 분모가 조용히 줄어든 것을 놓칩니다.

게이트 증적은 **「카나리 `canary_size`건 중 고유 `emitted_distinct_slugs`건 전건 검수」**로
구성됩니다. 게이트 문면은 「카나리 30건 100% 검수」이지만, 기계가 제시할 수 있는 고유 문항이
그보다 적으면 그 숫자를 그대로 적습니다 — 분모를 30으로 위장하지도, 검수할 수 없었던 건을
검수한 것으로 세지도 않습니다.

회신을 받으면 제가 게이트 `G-eos-first-run-canary-review`의 clear 증적을 구성해 드립니다
(clear 명령은 대장 조작이라 증적 확인 후에 안내드립니다).

---

## 7. 근거 (실측 출처 · 판정 기준 main `a71356cd`)

| 사실 | 출처 |
|---|---|
| 카나리 절단 CLI 인자(`--out` 필수·`--queue-out` 필수·`--run-id` 선택) | `harness/canary_slice.py:387-412` |
| 산출 경로가 입력 4종과 겹치면 exit 2 | `harness/canary_slice.py` `parser.error("--queue-out이 …")` |
| `canary_size` 미기록(None) → exit 1 (기본값 30 미가정) | `harness/canary_slice.py:460-466` |
| genlog 손상 1행 → 부분 산출 없이 exit 1 | `harness/canary_slice.py:480-497` |
| 해결 0건 → 파일 미생성 + exit 1 | `harness/canary_slice.py` `summary["written"] = False` 분기 |
| 불변식 `len(rows) + len(unresolved) == canary_size` | `harness/canary_slice.py:270-272` docstring |
| 미해결 3종(`MissingCuSlug`·`SlugNotFound`·`GenlogShortfall`) | `harness/canary_slice.py:38`·`97-100` |
| 해결 우선순위 ①이번 회차 큐 ②코퍼스 ③임의 회차 큐 | `harness/canary_slice.py:295-333` |
| 검수 CLI 인자(`--queue`·`--events`·`--verdicts`·`--reviewer-id`·`--resume`·`--limit`) | `harness/review_session.py:503-514` |
| 판정 키 a/e/r/s/q 폐쇄 집합 | `harness/review_session.py:138-146` |
| 반려코드 F1~F8 필수(`r`)·선택(`e`) | `harness/review_session.py:147-148`·`326-341` |
| F1~F8 정의 | `docs/standards/eos_verification_design_v1.md` §4 |
| 검수 대상 0건 → exit 1("0건 통과가 아니라 측정 실패") | `harness/review_session.py` `if not items:` 분기 |
| `load_review_items`가 status로 거르지 않음(반려분도 검수 대상) | `harness/review_session.py` `load_review_items` |
| **같은 slug는 한 번만 검수**(`DuplicateSlug(skipped)`) → 판정 건수 = 고유 slug 수 | `harness/review_session.py:216` |
| 큐 파일에는 카나리 슬롯 **전건**이 실린다(중복 포함) → 큐 행 수 = `emitted` | `harness/canary_slice.py:618` |
| `emitted_distinct_slugs` = `emitted` − `duplicate_slug_rows` | `harness/canary_slice.py` `distinct = len(set(slugs))` |
| 큐 중복은 fail-close가 아니라 계수·보고(`queue_duplicate_slug_rows`) | `harness/canary_slice.py` (MP-09 · PR #1260) |
| 항목마다 즉시 flush(중단해도 기록 보존) | `harness/review_session.py:69` |
| 사이드카 3종 경로 = `Path.with_suffix()` | `anchor_round_ledger.py:717`·`problem_corpus_accumulate.py:704,714` |
| 게이트 정의·목적("골든셋 승격 원천") | `backlog/gates.yaml` `G-eos-first-run-canary-review` |
| 2026-09-10 회차 2회·둘 다 `accepted=0` | `backlog/tasks/MP-06-…yaml` acceptance ⑤ (Kiki 실행 로그) |
