# EOS-137 런북 — QA 엔진 첫 평가: 골든 v1 대비 혼동행렬 + 평가 원장 첫 행 (Kiki · Phaiakes9)

> **전제**: 이 런북이 부르는 `whymath_backend.harness.qa_item_verdict`는 EOS-137 PR이 **main에
> 머지된 뒤에만** 존재합니다. §1의 `CODE_FROM_WORKTREE=True`가 그것을 기계로 확인합니다 —
> False면 아직 머지 전이므로 멈추십시오.
>
> 게이트: `G-eos137-first-qa-eval-run` · 태스크: `EOS-137-qa-per-item-verdict-adapter` ②.
> 판정 기준 main은 §1 출력의 `HEAD`가 말합니다(회신에 포함해 주십시오). 그 값이 평가 원장의
> `engine_revision`이 됩니다.

## 사전 브리핑 (6항목)

### ① 과제 명칭
골든 벤치 v1(2026-09-26 동결 · 15건)로 **QA 엔진 첫 평가** — 문항별 판정 생산 + 혼동행렬 + 평가 원장 첫 행.

### ② 목적
2026-09-26에 동결한 정답지(골든 v1 — 정상 13 · 결함 2)는 "QA 엔진이 결함을 얼마나 놓치는가(FN율)"를
재려고 만든 것인데, 그동안 QA 엔진이 **문항마다** 내린 판정을 뽑는 도구가 없어 "측정 불가"로 남아
있었습니다. 이번 PR이 그 도구(`qa_item_verdict`)를 만들었고, 이 런북이 그것을 처음 돌립니다.

- **문항별 판정** — 카나리 검수 큐에 들어 있던 문항 본문(검수자가 본 그대로)을 QA 엔진의 문항 판정
  좌석에 태워 문항마다 pass/fail을 냅니다. 판정할 수 없는 문항은 pass로 채우지 않고 따로 셉니다.
- **혼동행렬** — 그 판정을 정답지와 맞대어 재현율(결함을 걸러낸 비율)·FN율 상한·적재율(정답지 중
  판정이 붙은 비율)을 냅니다.
- **평가 원장 첫 행** — 이 평가를 `(정답지 지문, 엔진 리비전, 판정기, 지표)`로 원장에 한 줄 남깁니다.
  이 줄이 "모델 표류 감지" 시계열의 첫 점입니다.

**세션의 사전 예상(틀릴 수 있습니다)**: 표본이 15건뿐이라 수치는 자릿수만 말합니다. 결함 2건 중
1건은 F7(문장 수준) 반려인데, QA 엔진의 문항 좌석은 수학 기계 판정이 중심이라 **그 결함을 놓칠
가능성이 높습니다**(FN) — 그것도 결과입니다. 판정 불가 문항은 0건으로 예상합니다(저장소 문제은행
14,034건에서 0건이었습니다).

도구는 **판정만 기록**합니다. 검수 파일·정답지 원본은 바꾸지 않고, 새 파일은 `mp02-out\mp03\qa_eval_v1\`
폴더와 원장 파일 1개(`mp02-out\mp03\golden_benchmark_v1\eval_ledger.jsonl`)에만 씁니다.

### ③ 구체적 절차 (전체 약 3~5분)
| 절 | 무엇이 일어나는가 | 소요 |
|---|---|---|
| §1 | main 워크트리를 따로 만들고, 그 코드가 실제로 임포트되는지 확인 | 1분 |
| §2 | `Desktop\__AI` 아래에서 검수 기록 폴더와 골든 v1을 **스스로 찾음** + 지문 대조 | 1~2분 |
| §3 | 문항별 판정 1회 → 요약 출력 | 수 초 |
| §4 | 혼동행렬 + 평가 원장 1회 → 수치 출력 | 수 초 |
| §5 | 회신 | — |

### ④ 성공 기준
| 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` | 둘 다 `True` | PR 머지 전이거나 fetch 실패 — 회신 |
| §2 `DATA_OK` · `GOLDEN_DIGEST_MATCH` | 둘 다 `True` | 후보 목록·지문을 회신(세션이 경로를 채운 블록을 드립니다) |
| §3 `ADAPTER_EXIT` | `0` | `1`=판정 0건(전부 판정 불가) · `2`=입력 손상/부재 — 요약 JSON 회신 |
| §4 `MATRIX_EXIT` · `LEDGER_LINES` | `0` · `1` | `1`이면 리포트 끝의 `[측정 실패]`·`[재채점 금지 위반]` 줄을 회신 |

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`
(§1이 옆에 `WhyMath-eos137` 워크트리를 만들고 그 안으로 들어갑니다). **Docker·서버·LLM 불요** —
파일만 읽고 씁니다. 비용 0원.

### ⑥ 창 구분
**창 ① 하나만** 씁니다. 처음부터 끝까지 같은 창에서 §1→§4 순서로 붙여넣으십시오. 장기 점유
프로세스가 없으므로 중간에 다른 명령을 넣으셔도 안전합니다. 각 블록은 앞 블록이 만든 변수
(`$PyExe`·`$Data`·`$Golden`·`$Out` 등)를 씁니다 — **창을 닫았다면 §1부터 다시** 붙여넣으십시오.

> **한 번만 돌리십시오(§4).** 평가 원장은 같은 정답지를 *다른* 엔진 리비전으로 다시 재면 거부합니다
> (재채점 금지). 같은 워크트리(같은 `HEAD`)로 다시 돌리는 것은 허용되지만, 며칠 뒤 main이 바뀐 상태로
> §1부터 다시 하면 §4가 `[재채점 금지 위반]`으로 exit 1을 냅니다 — 그것은 고장이 아니라 설계입니다.

---

## 1. 워크트리 + 코드 출처 검증 — 창 ①

클론은 여러 세션이 공유하는 작업 사본이라 브랜치를 옮기지 않고 **별도 워크트리**에서 돕니다.
`PYTHONPATH`에 `src\data-pipeline`도 넣습니다 — QA 엔진 모듈이 원자 그래프 검증기를 그 패키지에서
가져오기 때문입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 워크트리 생성 + 생성 결과 되읽기 + 코드 출처 검증
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
if (Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-eos137) { git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-eos137 } else { "기존 워크트리 없음 — 새로 만듭니다" }
git worktree add --detach C:\Users\kiki\Desktop\__AI\WhyMath-eos137 origin/main
$Expected = (git rev-parse origin/main)
$Head = (git -C C:\Users\kiki\Desktop\__AI\WhyMath-eos137 rev-parse HEAD)
if ($Head -and ($Head -eq $Expected)) {
  cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
  $env:PYTHONUTF8 = "1"
  $env:PYTHONIOENCODING = "utf-8"
  $env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-eos137\src\backend;C:\Users\kiki\Desktop\__AI\WhyMath-eos137\src\data-pipeline"
  $PyExe = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
  $Src = & $PyExe -c "import whymath_backend.harness.qa_item_verdict as m; print(m.__file__)"
  $CodeOk = ($Src -like "*WhyMath-eos137*")
  $Rev = (git -C C:\Users\kiki\Desktop\__AI\WhyMath-eos137 rev-parse --short=12 HEAD)
  "HEAD_MATCHES_REMOTE=True"
  "HEAD=$Rev"
  "LOADED_FROM=$Src"
  "CODE_FROM_WORKTREE=$CodeOk"
} else { $Src = ""; $Rev = ""; "REFUSED — 워크트리 생성 실패 또는 커밋 불일치. HEAD=$Head EXPECTED=$Expected. 이 출력을 회신해 주십시오. 뒤 단계는 실행하지 마십시오." }
```

**판정**: `HEAD_MATCHES_REMOTE=True`와 `CODE_FROM_WORKTREE=True`가 둘 다 보여야 §2로 갑니다.
`REFUSED`가 나오면 `$Src`·`$Rev`를 비워 두므로 실수로 §3 이후를 붙여넣어도 그 블록들이 스스로
거부합니다. `ModuleNotFoundError`가 나고 `CODE_FROM_WORKTREE=False`면 EOS-137 PR이 아직 머지되지
않은 것입니다 — 멈추고 회신해 주십시오. 편집 설치된 **원 클론의 옛 코드**가 임포트되는 상황도 이
줄이 막습니다(`PYTHONPATH`가 편집 설치를 이기는지 `__file__`로 확인).

---

## 2. 검수 기록 폴더 + 골든 v1 찾기 — 창 ① (읽기 전용 · 1~2분)

경로를 문서에 박지 않습니다. MP-03 런북과 같은 규칙으로 `Desktop\__AI` 아래에서
`canary_review_events_v3.jsonl`이 있고 회차 대장에 1회차 `run_id c0854e38…`이 있는 폴더를 찾습니다
(**정확히 1개일 때만** `$Data`가 채워집니다). 그다음 그 안의 골든 v1 지문(digest)이 2026-09-26 동결값
`55105757…`과 같은지 확인합니다 — 다른 골든을 재면 원장 첫 행이 엉뚱한 정답지를 가리킵니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 검수 기록 폴더 스캔 + 골든 지문 대조(읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$Scan = "import json,pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent for d in dirs for p in d.rglob('canary_review_events_v3.jsonl')}); rid=lambda h: ','.join(json.loads(l).get('run_id','')[:8] for l in ((h/'problems.rounds.jsonl').read_text(encoding='utf-8').splitlines() if (h/'problems.rounds.jsonl').exists() else []) if l.strip().startswith('{')); [print('%s | queue %s | golden %s | run_ids %s' % (h, (h/'canary_review_queue.jsonl').exists(), (h/'mp03'/'golden_benchmark_v1'/'golden.json').exists(), rid(h))) for h in hits]; ok=[h for h in hits if 'c0854e38' in rid(h)]; print('CANDIDATES', len(hits), 'ROUND1_MATCHES', len(ok))"
$Pick = "import json,pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent for d in dirs for p in d.rglob('canary_review_events_v3.jsonl')}); ok=[h for h in hits if (h/'problems.rounds.jsonl').exists() and 'c0854e38' in (h/'problems.rounds.jsonl').read_text(encoding='utf-8')]; print(ok[0] if len(ok)==1 else '')"
$Dig = "import json,sys; g=json.load(open(sys.argv[1],encoding='utf-8')); print(g['digest'])"
& $PyExe -c $Scan
$Data = (& $PyExe -c $Pick)
$Q = "$Data\canary_review_queue.jsonl"
$Golden = "$Data\mp03\golden_benchmark_v1\golden.json"
$Ledger = "$Data\mp03\golden_benchmark_v1\eval_ledger.jsonl"
$Out = "$Data\mp03\qa_eval_v1"
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Q) -and (Test-Path $Golden))
if ($DataOk) { $Digest = (& $PyExe -c $Dig $Golden) } else { $Digest = "" }
$DigestOk = ($Digest -eq "55105757519f790e9ca95100fd5042085ba28b7f37bc4a31812e29c4385e1a1c")
"DATA=$Data"
"DATA_OK=$DataOk"
"GOLDEN_DIGEST=$Digest"
"GOLDEN_DIGEST_MATCH=$DigestOk"
"LEDGER_EXISTS_BEFORE=$(Test-Path $Ledger)"
```

**판정**: `DATA_OK=True` · `GOLDEN_DIGEST_MATCH=True`면 §3으로 갑니다. 기대 출력은 `mp02-out` 한 줄에
`queue True | golden True | run_ids c0854e38`, `CANDIDATES 1 ROUND1_MATCHES 1`,
`LEDGER_EXISTS_BEFORE=False`(첫 평가이므로 원장이 아직 없어야 합니다 — `True`면 누군가 이미 잰
것이므로 그 사실을 회신에 적어 주십시오). `DATA_OK=False`면 목록 전체를 회신해 주십시오 — 세션이 경로를
채운 블록을 따로 드립니다(자리표시자는 드리지 않습니다).

---

## 3. 문항별 판정 — 창 ① (새 폴더 `mp02-out\mp03\qa_eval_v1\`에만 씀)

입력은 **카나리 검수 큐 하나**입니다. 그 큐에는 골든 15건의 본문이 전부 있습니다 — 코퍼스에 수록된
8건은 코퍼스 행 그대로, 회차 내 중복으로 수록되지 않은 7건은 후보 본문으로(MP-03 판정 문서 §8.3).
검수자가 본 본문과 QA 엔진이 판정하는 본문이 같아야 정답지와 맞댈 수 있기 때문입니다. 같은 문항이
큐에 두 번 있으면 **첫 줄**을 판정합니다(검수 도구와 같은 규칙).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 문항별 판정(선행 조건을 이 블록이 다시 검사해 거부함)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$CodeOk = ($Src -like "*WhyMath-eos137*")
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Q) -and (Test-Path $Golden))
$DigestOk = ($Digest -eq "55105757519f790e9ca95100fd5042085ba28b7f37bc4a31812e29c4385e1a1c")
$ASum = "import json,sys; s=json.load(open(sys.argv[1],encoding='utf-8')); print('PREDICTOR',s.get('predictor'),'ROWS',s.get('rows_total'),'DUP_ROWS',s.get('duplicate_rows'),'DIVERGENT',len(s.get('duplicate_divergent',[])),'OUTSIDE_GOLDEN',s.get('outside_golden')); print('BY_VERDICT',s.get('by_verdict'),'UNDETERMINED_BY',s.get('undetermined_by_category'))"
if ($CodeOk -and $DataOk -and $DigestOk) { New-Item -ItemType Directory -Force -Path $Out | Out-Null; cmd /c "$PyExe -m whymath_backend.harness.qa_item_verdict --input $Q --golden $Golden --out $Out\qa_verdicts.jsonl --undetermined $Out\qa_undetermined.jsonl > $Out\adapter_summary.json 2> $Out\adapter.err"; $AdapterExit = $LASTEXITCODE; "ADAPTER_EXIT=$AdapterExit"; & $PyExe -c $ASum "$Out\adapter_summary.json"; "PREDICTION_LINES=$(@(Get-Content "$Out\qa_verdicts.jsonl" -ErrorAction SilentlyContinue).Count)" } else { $AdapterExit = -1; "WRITE_REFUSED=True — CODE_FROM_WORKTREE=$CodeOk DATA_OK=$DataOk GOLDEN_DIGEST_MATCH=$DigestOk. False인 항목을 회신해 주십시오. 아무것도 쓰지 않았습니다." }
```

> **왜 `cmd /c`로 감싸는가**: 요약 JSON에 한국어가 들어갑니다. PowerShell 5.1은 네이티브 명령의
> stdout을 cp949로 디코딩했다 재인코딩하며 JSON 구조 문자를 잃습니다(2026-09-14 실측). `cmd /c`의
> `>`는 바이트를 그대로 파일에 씁니다.

**판정**: `ADAPTER_EXIT=0`. 기대값은 `PREDICTOR qa_pipeline.item_verdict/v1` · `ROWS 28` ·
`DUP_ROWS 13` · `OUTSIDE_GOLDEN 0`이며, `BY_VERDICT`의 pass + fail + undetermined 합이 **15**입니다.
`DIVERGENT`가 0이 아니면(같은 문항의 큐 행끼리 본문이 다름) **실패가 아니라 결과**입니다 — 그 수를
회신에 포함해 주십시오. `ADAPTER_EXIT=2`면 `$Out\adapter_summary.json`의 `input_errors`를 회신해
주십시오(이때 판정 파일은 쓰이지 않습니다).

---

## 4. 혼동행렬 + 평가 원장 첫 행 — 창 ① (리포트 3개 + 원장 1줄을 씀)

엔진 리비전은 §1의 `HEAD`(12자리)를 그대로 씁니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 혼동행렬 + 원장 append(선행 조건 재검사)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$HasPred = (Test-Path "$Out\qa_verdicts.jsonl")
$RevOk = ($Rev.Length -ge 7)
$MSum = "import json,sys; r=json.load(open(sys.argv[1],encoding='utf-8')); m=r['metrics']; c=r['coverage']; print('MATRIX',r['matrix'],'PREDICTOR',r['predictor']['id'],r['predictor']['kind'],'ENGINE_REVISION',r['engine_revision']); print('COVERAGE',c['evaluated'],'/',r['golden']['total'],'LOWER',c['wilson_lower'],'UNEVALUATED',c['unevaluated']); print('RECALL_LOWER',m['recall_lower'],'FN_UPPER',m['fn_rate_upper'],'PRECISION_LOWER',m['precision_lower'],'FALSE_ALARM_UPPER',m['false_alarm_upper']); print('FN_BY_CODE',r['fn_by_failure_code'],'GOLDEN_BY_CODE',r['golden_by_failure_code'])"
if ($HasPred -and $RevOk -and ($AdapterExit -eq 0)) { cmd /c "$PyExe -m whymath_backend.ops.qa_confusion_matrix --golden $Golden --predictions $Out\qa_verdicts.jsonl --engine-revision $Rev --ledger $Ledger --json $Out\qa_confusion.json --report $Out\qa_confusion.md > $Out\qa_confusion.out 2> $Out\qa_confusion.err"; "MATRIX_EXIT=$LASTEXITCODE"; "LEDGER_LINES=$(@(Get-Content $Ledger -ErrorAction SilentlyContinue).Count)"; if (Test-Path "$Out\qa_confusion.json") { & $PyExe -c $MSum "$Out\qa_confusion.json" } else { Get-Content "$Out\qa_confusion.err" -Encoding UTF8 } } else { "RUN_REFUSED=True — PREDICTIONS=$HasPred REVISION_OK=$RevOk ADAPTER_EXIT=$AdapterExit. §3을 먼저 성공시켜 주십시오." }
```

**판정**: `MATRIX_EXIT=0` · `LEDGER_LINES=1`. 뒤따르는 네 줄(`MATRIX …`·`COVERAGE …`·`RECALL_LOWER …`·
`FN_BY_CODE …`)이 EOS-137 ②의 핵심 수치입니다 — 그대로 회신해 주십시오. `PREDICTOR`는
`qa_pipeline.item_verdict/v1 qa_engine`이어야 합니다. 값이 `None`인 지표는 **미산출**(분모 0)이며
0%가 아닙니다. `MATRIX_EXIT=1`이면 `qa_confusion.err`의 마지막 줄들이 출력됩니다 — 그대로 회신해
주십시오(측정 불가도 결과입니다).

---

## 5. 회신 목록

1. §1의 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` · `HEAD`
2. §2의 목록 전체 + `DATA_OK` · `GOLDEN_DIGEST_MATCH` · `LEDGER_EXISTS_BEFORE`
3. §3의 `ADAPTER_EXIT` · `PREDICTOR …` 줄 · `BY_VERDICT …` 줄 · `PREDICTION_LINES`
4. §4의 `MATRIX_EXIT` · `LEDGER_LINES` · `MATRIX …`부터 `FN_BY_CODE …`까지 네 줄

회신을 받으면 세션이 EOS-137 ②(재현율·FN 상한·적재율)를 MEMORY에 기록하고 게이트를 닫습니다.
만든 파일은 전부 `mp02-out\mp03\` 아래에 있고 코퍼스 데이터라 저장소에 커밋하지 않습니다. 원장 파일
(`eval_ledger.jsonl`)은 **지우지 마십시오** — 다음 회전(골든 v2)의 표류 시계열과 재채점 금지 판정이
이 파일을 읽습니다. 워크트리는 끝난 뒤 지우셔도 됩니다 — 이 블록은 선택입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — (선택) 워크트리 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-eos137
"WORKTREE_LEFT=$(Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-eos137)"
```

---

## 근거 대장 (세션이 저장소에서 확인한 것)

| 주장 | 근거 |
|---|---|
| 골든 v1 지문 `55105757…` · 15건(정상 13 · 결함 2) · 경로 `mp02-out\mp03\golden_benchmark_v1\golden.json` | `backlog/gates.yaml` `G-mp03-first-promotion-run` evidence · MP-03 런북 §5 |
| 카나리 검수 큐 28행 = 수용 8(코퍼스 행) + 중복 20 중 slug 보유분 · 고유 15 | MP-03 판정 문서 §8.1·§8.3 · `harness/canary_slice.py`(수용분도 `candidate_payload`에 코퍼스 행을 싣는다) |
| 큐 행 본문 해석 규칙(첫 등장 · `candidate_payload`) | `harness/review_session._resolve_payload`(어댑터가 그대로 재사용) |
| 어댑터 exit 규칙(0 · 1=판정 0건 · 2=입력 손상, 손상 시 무산출) | `harness/qa_item_verdict.py` · `tests/backend/harness/test_qa_item_verdict.py::TestCli` |
| 혼동행렬·원장 규칙(판정기 필수 · 재채점 금지 · 원장 행 지표) | `ops/qa_confusion_matrix.py` · `docs/standards/golden_benchmark_contract.md` §9 |
| `src\data-pipeline`을 `PYTHONPATH`에 넣는 이유 | `harness/qa_pipeline.py`가 `data_pipeline.atom_graph.validate`를 가져온다(모듈 docstring "cross-package import 경계") |
| 명령 흐름 전체의 모의 실행(가짜 `mp02-out` · 큐 28행 · 골든 15건) | 세션 실측 2026-09-28 — PR 본문 참조 |
