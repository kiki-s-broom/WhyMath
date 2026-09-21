# MP-02 런북 — 첫 LLM 저작 회차 완주 (Phaiakes9 실행)

> **판정 기준: main `66515c81`** (MP-04 착지 커밋). 이 문서의 모든 명령·필드는 그 시점
> trunk에서 실측 확인했다 — 미머지 브랜치의 파일을 쓰는 명령은 없다.
>
> 대상 태스크 `MP-02-first-llm-authoring-run` · 작성 2026-09-06 · 실행 주체 **Kiki**

---

## 0. 사전 브리핑 (6항목)

### ① 과제 명칭
**첫 LLM 저작 회차 완주** — 실제 LLM으로 동등문제 60건을 만들어 보고, 배치 안전장치가
무슨 판정을 내는지 처음으로 실측한다.

### ② 목적
지금까지 저작 파이프라인은 **가짜 provider(대본)로만** 돌았다. 게이트·카나리·회차 대장은
전부 hermetic 테스트에서 초록이지만, **실제 모델이 만든 문제로는 한 번도 돌지 않았다.**

이 회차가 만드는 것 세 가지:
1. **골든셋의 원천** — 검수를 통과한 문제가 이후 품질 벤치마크의 기준이 된다.
2. **임계의 현실 근거** — 카나리 임계 0.90이 현실에 맞는 숫자인지 판정할 첫 데이터
   (판정 자체는 `MP-03`에서 한다. 이 회차는 **측정만** 한다).
3. **재현 계약의 첫 실물** — 방금 착지한 `MP-04` 회차 매니페스트가 실제 회차에서
   채워지는지 확인한다.

### ③ 구체적 절차 (아래 §2~§5)
A. main 동기화 + 환경 자가검증 (2분) → B. Ollama 준비 확인 (2분) →
C. 회차 실행 (**20~60분**, 모델 속도에 따라) → D. 산출 3종 자가검증 (1분) →
E. 리콜 리허설 (1분) → F. 결과 회신 (붙여넣기)

### ④ 성공 기준
- **성공**: `rounds.jsonl` 1행 + `genlog.jsonl` 60행 + `review.jsonl` 실재, 리콜 열거 60건
- **성공(다른 모습)**: 카나리 미달로 차단 — **이것도 결과다.** 차단 사유와 Wilson 하한
  수치가 대장에 실리면 성공이다(태스크 acceptance ① 명문). 원인 규명은 회신 후 세션이 한다.
- **실패**: 산출 파일이 없거나, 대장 행의 `canary_passed`·`canary_lower_bound`가 `null`
  → 그 자체가 버그 신고다. §6 그대로 회신.
- **실패 시 대처**: 어떤 단계든 멈추면 **그 단계의 출력 전문**을 그대로 붙여넣어 주십시오.
  추측해서 다음 단계로 넘어가지 마십시오.

### ⑤ 실행 환경
- **머신**: Phaiakes9 (= 평소 쓰시는 이 PC). 별도 접속 없음.
- **시스템**: Windows PowerShell
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Ollama 가동 중 (§2에서 확인) · 인터넷 불필요(로컬 모델 경로)

### ⑥ 창 구분
- **창 ①** (새 창) — §1~§5 전부. 장기 프로세스를 점유하지 않으므로 한 창에서 순서대로 진행.
- **창 ②** (새 창) — §2에서 Ollama가 꺼져 있을 때만 사용. **그 창은 서버가 점유하므로
  이후 아무것도 입력하지 마십시오.** `Ctrl+C`는 복사가 아니라 **서버 중단 신호**입니다.

---

## 1. main 동기화 + 환경 자가검증 — 창 ①

`MP-04`(회차 매니페스트)가 방금 main에 들어갔습니다. 그 필드 없이 돌리면 acceptance ④가
구조적으로 성립하지 않으므로, **동기화가 선행 조건**입니다.

```powershell
# Windows PowerShell (= Phaiakes9)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout main
git pull origin main
$Py = ".\.venv\Scripts\python.exe"
& $Py -c "import whymath_backend, sys; print('PY_OK', sys.executable)"
& $Py -c "from whymath_backend.harness.anchor_round_ledger import RoundRecord; f=RoundRecord.model_fields; need=['canary_passed','canary_lower_bound','dedup_input_digests','cli_argv']; missing=[k for k in need if k not in f]; print('MANIFEST_MISSING', missing)"
```

**자가검증 판정** — 이 두 줄이 보여야 다음으로 갑니다:
- `PY_OK C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe`
- `MANIFEST_MISSING []`  ← **빈 대괄호**여야 합니다

`MANIFEST_MISSING`에 이름이 하나라도 있으면 pull이 안 된 것입니다. 그 출력을 회신해 주십시오.

> 이 검사에 변별력이 있는 이유: MP-04 이전 코드에서는 네 필드가 전부 없어
> `MANIFEST_MISSING ['canary_passed', 'canary_lower_bound', 'dedup_input_digests', 'cli_argv']`가
> 나옵니다. 성공·실패에서 서로 다른 값을 내므로 위장이 아닙니다.

---

## 2. Ollama 준비 확인 — 창 ①

이 회차는 라우터가 고르는 **로컬 모델**로 돌아갑니다. 어떤 모델인지는 **런북이 단정하지 않고
코드에 묻습니다** — 라우팅은 난이도·저작 패밀리 override를 거쳐 정해지므로, 문서에 모델
이름을 박아 두면 라우팅이 바뀌는 순간 이 런북이 조용히 거짓이 됩니다.

> **왜 이렇게 하는가**: 이 런북 초판은 `LOCAL_MODEL_MATRIX`만 읽고 `qwen2-math:7b`라고
> 적었습니다. 실측해 보니 생성기가 로컬 FAST/MID 결정의 **패밀리를 GENERAL로 갈아타서**
> 실제 모델은 `qwen2.5:7b`였습니다(`local/math/mid → 저작:general`). 그 모델만 없는
> 상태로 돌리면 60번의 호출이 전부 실패하고 카나리가 차단되는데, 그건 *저작 품질이 나쁜 것*이
> 아니라 *모델이 없는 것*입니다 — 측정 회차 하나를 통째로 태우는 실패입니다.
> (PR #1017 Codex P1 지적·수용)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$Model = & $Py -c "from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator as G; from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec as S; from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID as C; from whymath_backend.schema.enums import Subject; from whymath_backend.l3.router import resolve_model; g=G(None, misconception_catalog={k: v.name_kr for k, v in C.items()}, topic_hint='x', subject=Subject.공통, slug_prefix='probe'); d=g._decide_routing(S(achievement_standard_codes=frozenset({'[9수02-20]'}), target_misconception_ids=frozenset(), difficulty_overall='2.5', answer_format=None)); print(resolve_model(d.local_family, d.local_model))"
"SELECTED_MODEL=$Model"
if ($Model) { $Present = (ollama list | Select-String -SimpleMatch $Model) -ne $null; "MODEL_PRESENT=$Present" }
```

**판정**:
- `SELECTED_MODEL=` 뒤에 모델 이름이 찍히고 `MODEL_PRESENT=True`면 → §3으로.
- `MODEL_PRESENT=False`면 그 모델이 없는 것입니다. **같은 창 ①**에서 아래를 실행하십시오
  (앞에서 구한 이름을 그대로 씁니다 · 4~5GB · 5~15분):

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
if ($Model) { ollama pull $Model; ollama list | Select-String -SimpleMatch $Model }
```

- `SELECTED_MODEL=`이 **비어 있으면** 앞 명령이 실패한 것입니다(§1이 통과했는지 먼저 확인).
  그 출력을 회신해 주십시오.
- **`ollama` 명령 자체가 실패**하면(`CommandNotFoundException` 또는 연결 거부) Ollama 서버가
  꺼진 것입니다. **창 ②(새 창)** 를 열어 아래 한 줄만 실행하고, **그 창은 그대로 두십시오**:

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서버 점유 창 · 이후 조작 금지
ollama serve
```

그 다음 **창 ①로 돌아와** `ollama list`를 다시 실행합니다.

---

## 3. 회차 실행 — 창 ① (20~60분)

**설계 판단 2건을 먼저 밝힙니다** (이 태스크가 지정하지 않아 세션이 정한 값입니다):

1. **새 출력 파일에 씁니다** — `problem_bank_mp02_first_run_v0`. 기존 코퍼스에 섞지 않는
   이유: 기존 `problem_bank_generated_v0`에는 `[9수02-20]`으로만 184문이 이미 있어,
   거기에 이어 쓰면 **중복 제거(dedup)에 걸려 떨어지는 비율**이 카나리 성공률을 지배합니다.
   그러면 이 회차가 재는 것이 *모델 품질*이 아니라 *코퍼스 포화도*가 됩니다. 첫 회차는
   생성기 자체를 재는 것이 목적이므로 빈 파일에서 시작합니다.
2. **성취기준은 `[9수02-20]`(중3 이차방정식)** — 생성기가 가장 많이 검증된 축입니다
   (기존 코퍼스 619문 중 184문이 이 코드). 프롬프트가 통하는 축에서 먼저 완주합니다.

카나리 30 · 임계 0.90 · 신뢰수준 0.95 · 롤링 창 50 · 롤링 임계 0.30은 **전부 기본값**이라
인자로 주지 않습니다(기본값을 명시적으로 적으면 나중에 기본값이 바뀌어도 이 회차만 옛 값으로
남습니다 — 대장에는 실제 적용값이 그대로 기록됩니다).

**재실행 안전장치가 왜 필요한가**: 축적기는 **append-only**이고, `--out` 파일이 이미 있으면
그 내용을 dedup 인덱스에 넣습니다. 그래서 한 번 중단됐다 다시 돌리면 "빈 상태에서 시작한다"는
이 회차의 전제가 조용히 깨집니다 — 앞 시도의 잔여물이 뒤 시도의 수용률을 깎는데, §4 검사는
*가장 최근 회차*만 보므로 **정상처럼 보입니다**. 그래서 아래 블록은 대상이 깨끗하지 않으면
**아예 실행되지 않습니다**(PR #1017 Codex P1 지적·수용).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$Out = "data\corpus\problem_bank_mp02_first_run_v0\problems.jsonl"
$Stale = @($Out, "$Out.rounds.jsonl", "$Out.genlog.jsonl", "$Out.review.jsonl") | Where-Object { Test-Path $_ }
"STALE_FILES=$($Stale.Count)"
if ($Stale.Count -gt 0) { "중단: 앞 시도의 산출물이 남아 있습니다 → $($Stale -join ', ')" }
if ($Stale.Count -eq 0) { New-Item -ItemType Directory -Force -Path (Split-Path $Out) | Out-Null }
if ($Stale.Count -eq 0) { & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $Out --n 60 --standard-code "[9수02-20]" --difficulty 2.5 --topic-hint "중3 이차방정식 — 두 근 중 더 큰 근을 구하는 형태(답 하나)" | Tee-Object -FilePath "mp02_report.json"; "ACCUMULATE_EXIT=$LASTEXITCODE" }
```

**`STALE_FILES=0`이어야 회차가 돕니다.** 0이 아니면 위 "중단:" 줄이 어느 파일이 남았는지
알려 줍니다 — 그 목록을 회신해 주시면 처분(재시도용 새 폴더 vs 이전 시도 폐기)을 함께
정하겠습니다. **세션이 지우라고 말하기 전에 지우지 마십시오**: 앞 시도의 genlog에 실패 원인이
남아 있을 수 있고, 그게 다음 회차 설계의 재료입니다.

> 각 줄을 `if`로 감싼 이유: 붙여넣기 실행에서는 줄마다 독립적으로 돌아가 `throw`가 뒤 줄을
> 멈추지 못합니다. 가드를 조건문으로 걸어야 실제로 막힙니다.

**예상 출력**: 진행 로그가 흐르다가 마지막에 리포트 JSON이 출력되고, `ACCUMULATE_EXIT=0`
(신규 수용 0건이면 `1`) 이 찍힙니다. 리포트는 `mp02_report.json`에도 저장됩니다.

**중간에 멈춰도 됩니다** — genlog와 검수 큐는 호출마다 즉시 기록되므로 그때까지의 증거가
파일에 남습니다. 다만 회차 대장 1행은 **완주해야** 기록됩니다(완료되지 않은 회차를 대장에
남기지 않는 설계입니다).

---

## 4. 산출 3종 자가검증 — 창 ①

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$Out = "data\corpus\problem_bank_mp02_first_run_v0\problems.jsonl"
& $Py -c "import json,sys,pathlib
out=pathlib.Path(sys.argv[1])
def rows(p):
    q=pathlib.Path(p)
    if not q.exists(): return None
    return [json.loads(l) for l in q.read_text(encoding='utf-8').splitlines() if l.strip()]
led=rows(str(out)+'.rounds.jsonl'); gen=rows(str(out)+'.genlog.jsonl'); rev=rows(str(out)+'.review.jsonl')
print('LEDGER_ROWS', 'FILE_MISSING' if led is None else len(led))
print('GENLOG_ROWS', 'FILE_MISSING' if gen is None else len(gen))
print('REVIEW_ROWS', 'FILE_MISSING' if rev is None else len(rev))
if led:
    r=led[-1]
    print('RUN_ID', r.get('run_id'))
    for k in ('canary_size','canary_threshold','canary_passed','canary_rate','canary_lower_bound','canary_blocked','canary_advisory','aborted','abort_reason','model_name','prompt_version','attempted','accepted','appended'):
        print(' ', k, '=', json.dumps(r.get(k), ensure_ascii=False))
    if gen: print('GENLOG_SAME_RUN', sum(1 for g in gen if g.get('run_id')==r.get('run_id')))
" $Out
```

**판정 기준**:

| 보이는 것 | 뜻 |
|---|---|
| `LEDGER_ROWS 1` | ✅ 회차가 완주해 대장에 기록됨 |
| `LEDGER_ROWS FILE_MISSING` | ❌ 회차가 중간에 죽었다 — §6으로 회신 |
| `canary_passed = true` / `false` | ✅ 어느 쪽이든 **게이트가 판정을 냈다** |
| `canary_passed = null` | ❌ 판정 자체가 없었다 — 버그 신고 대상 |
| `canary_lower_bound` 에 숫자 | ✅ Wilson 하한 실측값 (임계 0.9와 비교할 값) |
| `model_name` 에 `qwen2-math:7b` 같은 값 | ✅ 재현 계약 성립 |
| `model_name = null` | ❌ genlog 연결이 끊겼다 — 회신 |
| `GENLOG_SAME_RUN 60` | ✅ 60회 호출 전건이 같은 회차로 묶임 |

> `canary_blocked = true`면 본배치가 시작되지 않았으므로 `GENLOG_SAME_RUN`은 60이 아니라
> **30 부근**입니다. 그건 오류가 아니라 **차단이 작동했다는 증거**입니다.

---

## 5. 리콜 리허설 (acceptance ③) — 창 ①

이 회차 산출물을 나중에 회수해야 할 때 **정확히 이 회차 것만** 골라낼 수 있는지 확인합니다.
**`--apply`는 쓰지 않습니다** — 실제 격리는 결함이 발견됐을 때만 합니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$Out = "data\corpus\problem_bank_mp02_first_run_v0\problems.jsonl"
$RunId = (Get-Content "$Out.rounds.jsonl" | Select-Object -Last 1 | ConvertFrom-Json).run_id
"RUN_ID_FOR_RECALL=$RunId"
$CorpusArgs = @(); if (Test-Path $Out) { $CorpusArgs = @("--corpus", $Out) }
"CORPUS_ARGS=$($CorpusArgs -join ' ')"
if ($RunId) { & $Py -m whymath_backend.ops.generation_recall --genlog "$Out.genlog.jsonl" @CorpusArgs --run-id $RunId; "RECALL_EXIT=$LASTEXITCODE" }
```

**판정**: 열거 건수가 §4의 `GENLOG_SAME_RUN`과 **같아야** 합니다(과다·과소 0). 다르면 그
차이 자체가 결함이므로 두 숫자를 함께 회신해 주십시오.

> `--corpus`를 **조건부로** 붙이는 이유: 카나리가 수용 0건으로 차단되면 코퍼스 파일 자체가
> 생기지 않습니다(§0 ④가 정상 결과로 인정하는 경우입니다). 그 상태에서 없는 경로를
> `--corpus`로 넘기면 리콜이 `[측정 실패] 코퍼스 파일 없음`과 함께 **exit 2**로 거부합니다
> — 정상 결과인데 리허설만 실패하는 셈입니다(실측 확인 · PR #1017 Codex P2 지적·수용).
> `--corpus` 없이도 이 리허설이 재는 것(회차 열거 건수)은 그대로 나옵니다.
>
> `$RunId`를 앞 명령의 출력에서 셸 변수로 받는 이유: 이 블록을 통째로 붙여넣어도 값이
> 자동으로 이어집니다. `if ($RunId)` 가드는 앞 줄이 실패했을 때 뒤 명령이 빈 인자로
> 실행되는 것을 막습니다.

---

## 6. 회신 — 이것만 붙여넣어 주시면 됩니다

§1의 두 줄, §3의 `ACCUMULATE_EXIT=`, §4의 표 전체, §5의 두 숫자.
값이 잘린 채 판단하지 않도록 **출력을 자르지 말고 그대로** 주십시오.

---

## 7. ⛔ acceptance ②(카나리 30건 검수)는 아직 실행하지 마십시오

**실측된 설계 공백입니다.** acceptance ②는 "카나리 30건을 100% 검수"를 요구하는데,
**그 30건을 지목할 수단이 저장소에 없습니다.**

> 「실측」 `problem_corpus_accumulate.py:305-306`
> *"카나리는 버리는 표본이 아니라 이 회차의 앞부분이므로, 통과분은 그대로 코퍼스에 append된다."*

즉 카나리 통과분은 **아무 표식 없이** 나머지 30건과 같은 파일에 섞입니다. 코퍼스 행에도
검수 큐 행에도 "이건 카나리였다"는 필드가 0건입니다. 유일한 근거는 genlog의 **적재 순서**
(같은 `run_id`의 앞 30행)인데, 그걸 검수 큐로 잘라 주는 CLI가 없습니다.

지금 검수하면 60건 전부를 보시거나 임의로 30건을 고르시게 되고, 어느 쪽이든 게이트
`G-eos-first-run-canary-review`의 증적이 "카나리 30건을 검수했다"는 주장을 뒷받침하지
못합니다.

**처분**: `MP-05`로 등재했습니다(카나리 구간 식별 CLI). §1~§6을 먼저 완주하고 회신해
주시면, 그 회차의 genlog로 `MP-05`를 구현·검증한 뒤 **검수용 30건 큐를 만들어** ② 런북을
따로 드리겠습니다. 순서가 이렇게 되는 이유는 `MP-05`가 **이 회차의 산출물을 입력으로 받는**
도구라서입니다 — 회차가 먼저 돌아야 만들 수 있습니다.

---

## 8. 근거 (실측 출처)

| 사실 | 출처 (main `66515c81`) |
|---|---|
| 카나리 기본 30 · 임계 0.90 · 신뢰 0.95 | `harness/batch_safety.py:124-126` |
| 롤링 창 50 · 임계 0.30 | `harness/batch_safety.py:129-130` |
| 모듈 실행 진입점(콘솔 스크립트 없음) | `harness/problem_corpus_accumulate.py` 말미 `if __name__ == "__main__"` |
| 저작 실제 모델 = **GENERAL/MID** → `qwen2.5:7b`(난이도 2.5 실측) | `l3/equivalent/llm_generator.py:665-690` 저작 패밀리 override + `l3/router.py` `LOCAL_MODEL_MATRIX` · **런북은 이 값을 하드코딩하지 않고 §2가 코드에 묻는다** |
| 사이드카 3종 경로 규칙 | `default_round_ledger_path` / `default_generation_log_path` / `default_review_queue_path` |
| 리콜 CLI 인자(`--genlog`·`--corpus`·`--run-id`·dry-run 기본) | `ops/generation_recall.py:385-441` |
| 검수 CLI 인자(`--queue`·`--events`·`--verdicts`·`--reviewer-id`) | `harness/review_session.py:503-514` |
| 카나리 통과분에 표식 없음 | `harness/problem_corpus_accumulate.py:305-306` |
| 매니페스트 16필드 | `harness/anchor_round_ledger.py` `RoundRecord` (MP-04 · PR #1013) |
