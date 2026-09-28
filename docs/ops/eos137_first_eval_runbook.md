# EOS-137 런북 — QA 엔진 골든 첫 평가(혼동행렬 + 평가 원장 첫 행) (Kiki · Phaiakes9)

> **전제**: 이 런북이 부르는 `whymath_backend.harness.qa_item_verdicts`와 확장된
> `ops.qa_confusion_matrix`는 EOS-137 PR이 **main에 머지된 뒤에만** 존재합니다. §1의
> `CODE_FROM_WORKTREE=True`가 그것을 기계로 확인합니다 — False면 아직 머지 전이므로 멈추십시오.
>
> 태스크: `EOS-137-qa-per-item-verdict-adapter` ②. 판정 기준 main은 §1 출력의 `HEAD`가
> 말합니다(회신에 포함해 주십시오). 결과 수치는 세션이 MEMORY에 기록합니다.

## 사전 브리핑 (6항목)

### ① 과제 명칭
MP-03에서 동결한 **골든 v1(15건)** 로 **QA 엔진의 첫 혼동행렬**을 재고, **평가 원장 첫 행**을 남깁니다.

### ② 목적
MP-03은 정답지(골든 v1 — clean 13 · defective 2)를 동결했지만 "QA 엔진 혼동행렬 = 측정 불가"로
끝났습니다. QA 엔진이 **문항마다** 내린 판정을 만드는 도구가 없었기 때문입니다. EOS-137이 그
도구를 만들었으므로, 이번 실행으로 처음으로 다음을 잽니다.

- **재현율(Recall) 하한** — 사람이 결함이라 판정한 문항을 엔진이 몇 건 걸렀는가
- **FN율 상한** — 결함 문항을 엔진이 정상으로 통과시킨 비율(무관용 축)
- **커버리지** — 골든 15건 중 엔진 판정이 실제로 붙은 비율

결과는 **나쁘게 나오는 것이 정상일 수 있습니다.** 엔진이 문항 단위로 보는 것은 9축 중 3축(조건 식
형식·금칙어/개인정보·출처 필드)뿐이고, 수학 오류(F1·F2)를 보는 축은 아닙니다. 이번 측정의 목적은
"엔진이 무엇을 못 보는가"를 숫자로 처음 확인하는 것입니다. 원장 첫 행은 이후 표류 시계열의
기준점이 됩니다(같은 골든을 다른 엔진 리비전으로 다시 재는 것은 금지 — 계약 §4·§9).

두 도구 모두 **판정을 만들지 않습니다** — 검수자가 본 파일을 읽어 엔진 판정을 적용하고, 골든과
대조만 합니다. 검수 원본·골든 파일은 바꾸지 않습니다. 새로 쓰는 것은 `mp02-out\eos137\` 폴더의
파일들과, 골든 옆의 **평가 원장 1행**(`mp02-out\mp03\golden_benchmark_v1\eval_ledger.jsonl`)입니다.

### ③ 구체적 절차 (전체 약 3~5분)
| 절 | 무엇이 일어나는가 | 소요 |
|---|---|---|
| §1 | main 워크트리를 따로 만들고, 새 코드가 실제로 그 워크트리에서 임포트되는지 확인 | 1분 |
| §2 | `Desktop\__AI` 아래에서 MP-03 데이터 폴더를 **스스로 찾고**, 골든이 MP-03 기록과 같은지 지문 대조 | 1~2분 |
| §3 | 검수 큐의 문항마다 QA 엔진 판정을 내려 predictions 파일 작성 | 수 초 |
| §4 | 골든 대비 혼동행렬 1회 + 평가 원장 첫 행 기록 | 수 초 |
| §5 | 회신 | — |

### ④ 성공 기준
| 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` | 둘 다 `True` | PR 머지 전이거나 fetch 실패 — 회신 |
| §2 `DATA_OK` · `GOLDEN_MATCHES_MP03` | 둘 다 `True` · `GOLDEN_ITEMS 15` | 후보 목록 전체를 회신(세션이 경로를 채운 블록을 드립니다) |
| §2 `LEDGER_ROWS_BEFORE` | `0` | 0이 아니면 첫 평가가 이미 있는 것 — §4가 스스로 거부합니다. 회신 |
| §3 `ADAPTER_EXIT` · `WRITTEN` | `0` · `True` | `1`=판정 0건(측정 실패) · `2`=입력 손상/부재 — 요약 줄 회신 |
| §4 `CM_EXIT` · `LEDGER_ROWS_AFTER` | `0` · `1` | `1`이면 아래 `.err` 내용이 이유를 말합니다 — 그대로 회신(측정 불가도 결과입니다) |

`ADAPTER_EXIT=0`이어도 `UNJUDGEABLE`이 0이 아닐 수 있습니다 — **실패가 아니라 결과**입니다(판정
불가 문항은 통과로 채우지 않고 혼동행렬에서 "미평가"로 분리됩니다). 그 목록을 회신해 주십시오.

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`
(§1이 옆에 `WhyMath-eos137` 워크트리를 만들고 그 안으로 들어갑니다). **Docker·서버·LLM 불요** —
파일만 읽고 씁니다. 비용 0원. 선행 조건: MP-03 런북을 실행했던 `mp02-out` 폴더가 그대로 있을 것.

### ⑥ 창 구분
**창 ① 하나만** 씁니다. 처음부터 끝까지 같은 창에서 §1→§4 순서로 붙여넣으십시오. 장기 점유
프로세스가 없으므로 중간에 다른 명령을 넣으셔도 안전합니다. 각 블록은 앞 블록이 만든 변수
(`$PyExe`·`$Data`·`$GoldenOk` 등)를 씁니다 — **창을 닫았다면 §1부터 다시** 붙여넣으십시오.
각 블록은 선행 조건을 **스스로 다시 검사해** 맞지 않으면 아무것도 쓰지 않고 거부합니다.

---

## 1. 워크트리 + 코드 출처 검증 — 창 ①

클론은 여러 세션이 공유하는 작업 사본이라 브랜치를 옮기지 않고 **별도 워크트리**에서 돕니다.
QA 엔진은 원자 그래프 검증 모듈(`data_pipeline`)도 임포트하므로 두 패키지 경로를 모두 워크트리로
지정합니다.

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
  $Src = & $PyExe -c "import whymath_backend.harness.qa_item_verdicts as m; print(m.__file__)"
  $CodeOk = ($Src -like "*WhyMath-eos137*")
  "HEAD_MATCHES_REMOTE=True"
  "HEAD=$($Head.Substring(0,8))"
  "LOADED_FROM=$Src"
  "CODE_FROM_WORKTREE=$CodeOk"
} else { $Src = ""; "REFUSED — 워크트리 생성 실패 또는 커밋 불일치. HEAD=$Head EXPECTED=$Expected. 이 출력을 회신해 주십시오. 뒤 단계는 실행하지 마십시오." }
```

**판정**: `HEAD_MATCHES_REMOTE=True`와 `CODE_FROM_WORKTREE=True`가 둘 다 보여야 §2로 갑니다.
`REFUSED`가 나오면 `$Src`가 비워지므로 실수로 뒤 블록을 붙여넣어도 그 블록들이 스스로 거부합니다.
`ModuleNotFoundError`가 나고 `CODE_FROM_WORKTREE=False`면 EOS-137 PR이 아직 머지되지 않은
것입니다 — 멈추고 회신해 주십시오. 편집 설치된 **원 클론의 옛 코드**가 임포트되는 상황도 이 줄이
막습니다(`PYTHONPATH`가 편집 설치를 이기는지 `__file__`로 확인).

---

## 2. 데이터 폴더 찾기 + 골든 지문 대조 — 창 ① (읽기 전용 · 1~2분)

경로를 문서에 박지 않습니다. `Desktop\__AI` 아래 `WhyMath*`·`mp02*`·`wm-*` 폴더를 훑어
`mp03\golden_benchmark_v1\golden.json`(MP-03 §5가 만든 골든)이 있는 폴더를 찾습니다. **정확히
1개일 때만** `$Data`가 채워집니다. 이어서 그 골든을 저장소 로더로 읽어(내용 변조 시 로드가
실패합니다) 지문이 MP-03 기록(MEMORY 2026-09-26 · digest `55105757…`)과 같은지 확인합니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 데이터 폴더 스캔 + 골든 지문 대조(읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$Scan = "import pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent.parent.parent for d in dirs for p in d.rglob('golden.json') if p.parent.name=='golden_benchmark_v1' and p.parent.parent.name=='mp03'}); [print('%s | queue %s | golden %s | ledger %s' % (h, (h/'canary_review_queue.jsonl').exists(), (h/'mp03'/'golden_benchmark_v1'/'golden.json').exists(), (h/'mp03'/'golden_benchmark_v1'/'eval_ledger.jsonl').exists())) for h in hits]; print('CANDIDATES', len(hits))"
$Pick = "import pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent.parent.parent for d in dirs for p in d.rglob('golden.json') if p.parent.name=='golden_benchmark_v1' and p.parent.parent.name=='mp03'}); print(hits[0] if len(hits)==1 else '')"
$GCheck = "import sys; from pathlib import Path; from whymath_backend.harness.golden_benchmark import load_golden_set; g=load_golden_set(Path(sys.argv[1])); print('GOLDEN_DIGEST', g.digest); print('GOLDEN_ITEMS', len(g.items)); print('GOLDEN_VERSION', g.golden_version, 'ROTATION', g.rotation); print('GOLDEN_MATCHES_MP03', g.digest=='55105757519f790e9ca95100fd5042085ba28b7f37bc4a31812e29c4385e1a1c')"
& $PyExe -c $Scan
$Data = (& $PyExe -c $Pick)
$Q = "$Data\canary_review_queue.jsonl"
$Golden = "$Data\mp03\golden_benchmark_v1\golden.json"
$Ledger = "$Data\mp03\golden_benchmark_v1\eval_ledger.jsonl"
$Out = "$Data\eos137"
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Q) -and (Test-Path $Golden))
$GOut = @()
if ($DataOk) { $GOut = @(& $PyExe -c $GCheck $Golden); $GOut } else { "골든 대조 건너뜀 — DATA_OK=False(후보가 0개이거나 2개 이상)" }
$GoldenOk = ($GOut -contains "GOLDEN_MATCHES_MP03 True")
$LedgerBefore = @(Get-Content $Ledger -ErrorAction SilentlyContinue).Count
"DATA=$Data"
"DATA_OK=$DataOk"
"GOLDEN_MATCHES_MP03=$GoldenOk"
"LEDGER_ROWS_BEFORE=$LedgerBefore"
```

**판정**: `DATA_OK=True` · `GOLDEN_MATCHES_MP03=True` · `GOLDEN_ITEMS 15` · `LEDGER_ROWS_BEFORE=0`이면
§3으로 갑니다. 기대 출력은 `mp02-out` 한 줄에 `queue True | golden True | ledger False`, 이어서
`CANDIDATES 1`입니다. `DATA_OK=False`면 목록 전체를 회신해 주십시오 — 세션이 경로를 채운 블록을 따로
드립니다(자리표시자는 드리지 않습니다). `GOLDEN_MATCHES_MP03=False`면 MP-03 이후 골든이 다시
동결된 것입니다 — 이 런북은 v1 첫 평가 전용이므로 회신해 주십시오.

---

## 3. QA 엔진 문항별 판정 — 창 ① (새 파일 3개를 `mp02-out\eos137\`에만 씀)

검수 세션이 검수자에게 보여 준 **그 큐 파일**(`canary_review_queue.jsonl`)을 그대로 넘깁니다 — 골든
라벨은 검수자가 본 문항의 라벨이므로 엔진도 같은 문항을 판정해야 두 축이 같은 대상을 말합니다(큐
28행 중 같은 문항의 2번째 이후 행은 검수 세션과 같이 버립니다).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 문항별 판정(선행 조건을 이 블록이 다시 검사해 거부함)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$CodeOk = ($Src -like "*WhyMath-eos137*")
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Q) -and (Test-Path $Golden))
$ASum = "import json,sys; s=json.load(open(sys.argv[1],encoding='utf-8')); print('WRITTEN',s.get('written'),'ERROR',s.get('error')); print('INPUT_ITEMS',s.get('input_items'),'JUDGED',s.get('judged'),'PASS',s.get('pass'),'FAIL',s.get('fail'),'OPERATING_RATE',s.get('operating_rate')); print('UNJUDGEABLE',s.get('unjudgeable_counts'),'DUP_WITHIN',s.get('duplicate_rows_within_input')); print('AXES',s.get('axis_status_counts')); [print('  -',u.get('cu_slug'),u.get('reason'),u.get('detail')) for u in s.get('unjudgeable',[])]"
if ($CodeOk -and $DataOk -and $GoldenOk) { New-Item -ItemType Directory -Force -Path $Out | Out-Null; cmd /c "$PyExe -m whymath_backend.harness.qa_item_verdicts --input $Q --out $Out\qa_verdicts.jsonl > $Out\qa_verdicts_summary.json 2> $Out\qa_verdicts.err"; "ADAPTER_EXIT=$LASTEXITCODE"; & $PyExe -c $ASum "$Out\qa_verdicts_summary.json"; "PREDICTION_LINES=$(@(Get-Content "$Out\qa_verdicts.jsonl" -ErrorAction SilentlyContinue).Count)" } else { "WRITE_REFUSED=True — CODE_FROM_WORKTREE=$CodeOk DATA_OK=$DataOk GOLDEN_MATCHES_MP03=$GoldenOk. False인 항목을 회신해 주십시오. 아무것도 쓰지 않았습니다." }
```

> **왜 `cmd /c`로 감싸는가**: 요약 JSON에 한국어가 들어갑니다. PowerShell 5.1은 네이티브 명령의
> stdout을 cp949로 디코딩했다 재인코딩하며 JSON 구조 문자를 잃습니다(2026-09-14 실측). `cmd /c`의
> `>`는 바이트를 그대로 파일에 씁니다.

**판정**: `ADAPTER_EXIT=0` · `WRITTEN True`. 기대값은 `INPUT_ITEMS 15` · `DUP_WITHIN 13`이고
`JUDGED`+(판정 불가 건수)=15입니다. `PREDICTION_LINES`는 `JUDGED`와 같아야 합니다. `PASS`/`FAIL`
분포는 세션도 모릅니다 — **이번에 처음 재는 값**입니다. `UNJUDGEABLE`이 비어 있지 않으면 그 아래
`-` 줄들(문항·사유)을 그대로 회신해 주십시오.

---

## 4. 골든 대비 혼동행렬 + 평가 원장 첫 행 — 창 ① (원장 1행 + `mp02-out\eos137\` 파일 4개)

엔진 리비전은 이 워크트리의 커밋(`git rev-parse --short HEAD`)입니다. 원장에 이미 행이 있으면 첫
평가가 아니므로 이 블록이 스스로 거부합니다(같은 골든을 다른 리비전으로 다시 재는 것은 재채점이라
금지 — 계약 §4).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 혼동행렬 + 원장 첫 행(선행 조건 재검사 · 원장 0행일 때만)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos137
$Rev = (git rev-parse --short HEAD)
$PredOk = (Test-Path "$Out\qa_verdicts.jsonl")
$LedgerBefore = @(Get-Content $Ledger -ErrorAction SilentlyContinue).Count
$CSum = "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); m=d['matrix']; c=d['coverage']; x=d['metrics']; g=d['golden']; print('VERDICT_SOURCE',d['verdict_source'],'GOLDEN',g['version'],'ROTATION',g['rotation'],'DIGEST',g['digest'][:12]); print('MATRIX TP',m['tp'],'FN',m['fn'],'FP',m['fp'],'TN',m['tn']); print('COVERAGE',c['evaluated'],'OF',g['total'],'RATE',c['rate'],'WILSON_LOWER',c['wilson_lower'],'UNEVALUATED',c['unevaluated']); print('RECALL_LOWER',x['recall_lower'],'FN_RATE_UPPER',x['fn_rate_upper']); print('PRECISION_LOWER',x['precision_lower'],'FALSE_ALARM_UPPER',x['false_alarm_upper']); print('FN_BY_CODE',d['fn_by_failure_code'],'LEDGER_ENFORCED',d['ledger_enforced'],'REPRO',d['reproducibility'])"
if ($PredOk -and $GoldenOk -and ($LedgerBefore -eq 0) -and $Rev) { cmd /c "$PyExe -m whymath_backend.ops.qa_confusion_matrix --golden $Golden --predictions $Out\qa_verdicts.jsonl --engine-revision $Rev --ledger $Ledger --json $Out\qa_confusion.json --report $Out\qa_confusion.md > $Out\qa_confusion.out 2> $Out\qa_confusion.err"; "CM_EXIT=$LASTEXITCODE"; "ENGINE_REVISION=$Rev"; "LEDGER_ROWS_AFTER=$(@(Get-Content $Ledger -ErrorAction SilentlyContinue).Count)"; if (Test-Path "$Out\qa_confusion.json") { & $PyExe -c $CSum "$Out\qa_confusion.json" } else { "CM_JSON=False — 판정 전에 멈췄습니다. 아래 .err 내용이 이유입니다." }; Get-Content "$Out\qa_confusion.err" -Encoding UTF8 } else { "RUN_REFUSED=True — PREDICTIONS=$PredOk GOLDEN_MATCHES_MP03=$GoldenOk LEDGER_ROWS_BEFORE=$LedgerBefore REV=$Rev. 원장이 0행이 아니면 첫 평가가 이미 있는 것입니다 — 이 출력을 회신해 주십시오. 아무것도 쓰지 않았습니다." }
```

**판정**: `CM_EXIT=0` · `LEDGER_ROWS_AFTER=1` · `VERDICT_SOURCE qa_engine` · `LEDGER_ENFORCED True`.
게이트 임계를 주지 않았으므로 수치가 나빠도 `CM_EXIT`은 0입니다(이번은 **측정**이지 합격 판정이
아닙니다). 마지막 `.err` 줄들에 `[원장] 평가 기록 append`가 보여야 합니다. `CM_EXIT=1`이면 `.err`의
`[측정 실패]`·`[재채점 금지 위반]`·`[재현성 위반]` 줄이 이유입니다 — 그대로 회신해 주십시오.

---

## 5. 회신 목록

1. §1의 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` · `HEAD`
2. §2의 목록 전체 · `GOLDEN_ITEMS` · `DATA_OK` · `GOLDEN_MATCHES_MP03` · `LEDGER_ROWS_BEFORE`
3. §3의 `ADAPTER_EXIT` · `WRITTEN` 줄 · `INPUT_ITEMS …` 줄 · `UNJUDGEABLE …` 줄과 그 아래 `-` 줄 전부 ·
   `AXES …` 줄 · `PREDICTION_LINES`
4. §4의 `CM_EXIT` · `ENGINE_REVISION` · `LEDGER_ROWS_AFTER` · `VERDICT_SOURCE`부터 `FN_BY_CODE`까지 6줄 ·
   `.err` 마지막 줄들

회신을 받으면 세션이 재현율·FN 상한·커버리지를 MEMORY에 기록하고 EOS-137 ②를 닫습니다. 만든
파일은 전부 `mp02-out\` 아래에 있고 코퍼스 데이터라 저장소에 커밋하지 않습니다. 워크트리는 끝난 뒤
지우셔도 됩니다 — 이 블록은 선택입니다.

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
| 데이터 폴더 `Desktop\__AI\mp02-out` · 골든 `mp03\golden_benchmark_v1\golden.json` | `docs/ops/mp03_first_golden_promotion_runbook.md` §5 · `MEMORY.md` 2026-09-26 MP-03 항 |
| 골든 v1 digest `55105757519f…` · 15건(clean 13 · defective 2 · A4 15) | `MEMORY.md` 2026-09-26 MP-03 ④ · `docs/reviews/mp03_canary_threshold_and_promotion_path_2026-09-25.md` §8 |
| 카나리 검수 큐 28행 = 수용 8 + 중복 20 · 고유 판정 15 | `MEMORY.md` 2026-09-26 MP-03 "①단 7건의 정체" |
| 어댑터 입력 규칙이 검수 세션과 같다(`candidate_payload` 판정·파일 안 중복 첫 행) | `harness/qa_item_verdicts.py`(`review_session.load_review_items` 재사용) · `tests/backend/harness/test_qa_item_verdicts.py` |
| 어댑터 exit 규칙(0 산출 · 1 입력/판정 0건 · 2 입력 오류, 1·2는 무산출) | `harness/qa_item_verdicts.py` `main` · 같은 테스트 |
| 혼동행렬 exit 규칙·원장 스냅샷·재현성 대조 | `ops/qa_confusion_matrix.py` `main` · `docs/standards/golden_benchmark_contract.md` §6·§9 |
| QA 엔진이 `data_pipeline`을 임포트한다(→ §1 `PYTHONPATH`에 `src\data-pipeline` 포함) | `harness/qa_pipeline.py` 머리 import(`data_pipeline.atom_graph.validate`) · 그 모듈의 외부 의존은 pydantic뿐 |
