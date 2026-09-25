# MP-03 런북 — 골든 승격 1차 시도 + 골든 벤치 첫 동결 (Kiki · Phaiakes9)

> **전제**: 이 런북이 부르는 `whymath_backend.harness.golden_inputs`는 MP-03 PR이 **main에
> 머지된 뒤에만** 존재합니다. §1의 `CODE_FROM_WORKTREE=True`가 그것을 기계로 확인합니다 —
> False면 아직 머지 전이므로 멈추십시오.
>
> 게이트: `G-mp03-first-promotion-run` · 태스크: `MP-03-first-golden-promotion` ①②④.
> 판정 기준 main 은 §1 출력의 `HEAD`가 말합니다(회신에 포함해 주십시오).

## 사전 브리핑 (6항목)

### ① 과제 명칭
MP-02 1회차 카나리 검수 기록으로 **골든 승격 게이트 1회 시도** + **골든 벤치 셋 첫 동결**.

### ② 목적
2026-09-22에 검수하신 카나리 고유 15건(승인 13 · 반려 2)의 기록으로 두 판정기를 처음 돌립니다.

- **승격 게이트**(`golden_promotion_gate`) — 문항을 학생 노출 가능 상태로 올리는 문입니다. 이번
  시도는 **거부되는 것이 정상**입니다(검수 30건 미만으로는 통계상 통과 불가 — 0결함이어도 최소
  133건 필요). 목적은 "15건이 **어느 단에서 몇 건씩** 막히는가"를 실물로 기록하는 것입니다
  (MP-03 ①②). 세션의 사전 분석은 *승인분이 코퍼스에 있어도 승인 도장(review_status) 단에서
  전부 막힌다*고 예상합니다 — 그 도장을 사람 판정에서 옮겨 주는 도구가 아직 없기 때문입니다.
  이 실행이 그 예상을 실측으로 확인하거나 반증합니다.
- **골든 벤치**(`golden_benchmark`) — QA 엔진(자동 판정기)을 채점할 **정답지**를 처음 동결합니다.
  동결 지문(digest)·시각이 시계열의 첫 점이 됩니다(MP-03 ④).

두 도구 모두 **판정을 만들지 않습니다** — 사람 판정 기록을 읽어 열거·대조만 합니다. 검수 파일
원본은 바꾸지 않고, 새 파일은 전부 `mp02-out\mp03\` 폴더 안에만 만듭니다.

### ③ 구체적 절차 (전체 약 3~5분)
| 절 | 무엇이 일어나는가 | 소요 |
|---|---|---|
| §1 | main 워크트리를 따로 만들고, 그 코드가 실제로 임포트되는지 확인 | 1분 |
| §2 | `Desktop\__AI` 아래에서 검수 기록 폴더를 **스스로 찾음**(경로 입력 없음) | 1~2분 |
| §3 | 검수 기록에서 입력 2종(승격 제안 목록·앵커 매핑) 파생 | 수 초 |
| §4 | 승격 게이트 1회 실행 → 거부 사유 분포 출력 | 수 초 |
| §5 | 골든 벤치 1회 실행 → 동결 지문 출력 | 수 초 |
| §6 | 회신 | — |

### ④ 성공 기준
| 줄 | 성공 | 실패면 |
|---|---|---|
| §1 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` | 둘 다 `True` | PR 머지 전이거나 fetch 실패 — 회신 |
| §2 `DATA_OK` | `True` | 후보 목록을 회신(세션이 경로를 채운 블록을 드립니다) |
| §3 `PROPOSAL_EXIT` · `ANCHOR_EXIT` | 둘 다 `0` | `2`=입력 손상/부재 · `1`=산출 0건 — 요약 JSON 회신 |
| §4 `GATE_EXIT` | **`1`(거부)** — 이번 시도의 정상값 | `0`이면 오히려 이상(보고 필요) · `2`=입력 오류 |
| §5 `GOLDEN_EXIT` · `GOLDEN_JSON` | `0` · `True` | `1`=승격 0건/파싱 실패 — 리포트 회신(측정 불가도 결과입니다) |

### ⑤ 실행 환경
Phaiakes9 = 평소 쓰시는 **Windows PowerShell**. 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`
(§1이 옆에 `WhyMath-mp03` 워크트리를 만들고 그 안으로 들어갑니다). **Docker·서버·LLM 불요** —
파일만 읽고 씁니다. 비용 0원.

### ⑥ 창 구분
**창 ① 하나만** 씁니다. 처음부터 끝까지 같은 창에서 §1→§5 순서로 붙여넣으십시오. 장기 점유
프로세스가 없으므로 중간에 다른 명령을 넣으셔도 안전합니다. 각 블록은 앞 블록이 만든 변수
(`$PyExe`·`$Data`·`$Out` 등)를 씁니다 — **창을 닫았다면 §1부터 다시** 붙여넣으십시오.

---

## 1. 워크트리 + 코드 출처 검증 — 창 ①

클론은 여러 세션이 공유하는 작업 사본이라 브랜치를 옮기지 않고 **별도 워크트리**에서 돕니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 워크트리 생성 + 코드 출처 검증
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
if (Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-mp03) { git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-mp03 } else { "기존 워크트리 없음 — 새로 만듭니다" }
git worktree add --detach C:\Users\kiki\Desktop\__AI\WhyMath-mp03 origin/main
cd C:\Users\kiki\Desktop\__AI\WhyMath-mp03
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "C:\Users\kiki\Desktop\__AI\WhyMath-mp03\src\backend"
$PyExe = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Src = & $PyExe -c "import whymath_backend.harness.golden_inputs as m; print(m.__file__)"
$CodeOk = ($Src -like "*WhyMath-mp03*")
"LOADED_FROM=$Src"
"CODE_FROM_WORKTREE=$CodeOk"
"HEAD_MATCHES_REMOTE=$((git rev-parse HEAD) -eq (git rev-parse origin/main))"
"HEAD=$(git rev-parse --short HEAD)"
```

**판정**: `CODE_FROM_WORKTREE`·`HEAD_MATCHES_REMOTE`가 둘 다 `True`여야 §2로 갑니다.
`ModuleNotFoundError`가 나고 `CODE_FROM_WORKTREE=False`면 MP-03 PR이 아직 머지되지 않은
것입니다 — 멈추고 회신해 주십시오. 편집 설치된 **원 클론의 옛 코드**가 임포트되는 상황도 이
줄이 막습니다(`PYTHONPATH`가 편집 설치를 이기는지 `__file__`로 확인).

---

## 2. 검수 기록 폴더 찾기 — 창 ① (읽기 전용 · 1~2분)

경로를 문서에 박지 않습니다. `Desktop\__AI` 아래 `WhyMath*`·`mp02*`·`wm-*` 폴더를 훑어
`canary_review_events_v3.jsonl`(2026-09-22 검수 기록 — 게이트 `G-eos-first-run-canary-review`
증적의 파일명)이 있는 폴더를 찾고, 그 폴더의 회차 대장에 1회차 `run_id c0854e38…`이 있는지까지
확인합니다. **조건을 만족하는 폴더가 정확히 1개일 때만** `$Data`가 채워집니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 검수 기록 폴더 스캔(읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-mp03
$Scan = "import json,pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent for d in dirs for p in d.rglob('canary_review_events_v3.jsonl')}); rid=lambda h: ','.join(json.loads(l).get('run_id','')[:8] for l in ((h/'problems.rounds.jsonl').read_text(encoding='utf-8').splitlines() if (h/'problems.rounds.jsonl').exists() else []) if l.strip().startswith('{')); [print('%s | queue %s | corpus %s | review %s | run_ids %s' % (h, (h/'canary_review_queue.jsonl').exists(), (h/'problems.jsonl').exists(), (h/'problems.review.jsonl').exists(), rid(h))) for h in hits]; ok=[h for h in hits if 'c0854e38' in rid(h)]; print('CANDIDATES', len(hits), 'ROUND1_MATCHES', len(ok))"
$Pick = "import json,pathlib; root=pathlib.Path(r'C:\Users\kiki\Desktop\__AI'); dirs=[d for d in root.iterdir() if d.is_dir() and (d.name.startswith('WhyMath') or d.name.startswith('mp02') or d.name.startswith('wm-'))]; hits=sorted({p.parent for d in dirs for p in d.rglob('canary_review_events_v3.jsonl')}); ok=[h for h in hits if (h/'problems.rounds.jsonl').exists() and 'c0854e38' in (h/'problems.rounds.jsonl').read_text(encoding='utf-8')]; print(ok[0] if len(ok)==1 else '')"
& $PyExe -c $Scan
$Data = (& $PyExe -c $Pick)
$Ev = "$Data\canary_review_events_v3.jsonl"
$Q = "$Data\canary_review_queue.jsonl"
$Corpus = "$Data\problems.jsonl"
$RQ = "$Data\problems.review.jsonl"
$Out = "$Data\mp03"
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Ev) -and (Test-Path $Q) -and (Test-Path $Corpus) -and (Test-Path $RQ))
"DATA=$Data"
"DATA_OK=$DataOk"
```

**판정**: `DATA_OK=True`면 §3으로 갑니다. 기대 출력은 `mp02-out` 한 줄에 `queue True | corpus
True | review True | run_ids c0854e38`, 마지막 줄 `CANDIDATES 1 ROUND1_MATCHES 1`입니다.
`DATA_OK=False`면 목록 전체를 회신해 주십시오 — 후보가 0개(파일명이 다름)이거나 2개 이상(사본
존재)인 경우이며, 세션이 경로를 채운 블록을 따로 드립니다(자리표시자는 드리지 않습니다).

---

## 3. 입력 2종 파생 — 창 ① (새 파일 4개를 `mp02-out\mp03\`에만 씀)

- **승격 제안 목록**: 검수 기록에서 사람이 종결 판정(승인·반려)을 내린 문항 **전건**을 나열합니다.
  반려분도 넣습니다 — 이번 시도의 목적이 "무엇이 어느 단에서 막히는가"의 전체 분포이기 때문입니다.
- **앵커 매핑**: 검수 큐의 각 문항이 스스로 적은 성취기준 코드를 앵커 레지스트리로 역인덱스합니다.
  코드가 앵커 1개로 정확히 떨어질 때만 매핑하고, 나머지는 사유와 함께 `unmapped`로 보고합니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 입력 파생(선행 조건을 이 블록이 다시 검사해 거부함)
cd C:\Users\kiki\Desktop\__AI\WhyMath-mp03
$CodeOk = ($Src -like "*WhyMath-mp03*")
$DataOk = (($Data.Length -gt 0) -and (Test-Path $Ev) -and (Test-Path $Q))
if ($CodeOk -and $DataOk) { New-Item -ItemType Directory -Force -Path $Out | Out-Null; cmd /c "$PyExe -m whymath_backend.harness.golden_inputs proposal --events $Ev --out $Out\proposal.txt > $Out\proposal_summary.json 2> $Out\proposal.err"; "PROPOSAL_EXIT=$LASTEXITCODE"; cmd /c "$PyExe -m whymath_backend.harness.golden_inputs anchor-map --queue $Q --out $Out\anchor_map.jsonl > $Out\anchor_map_summary.json 2> $Out\anchor_map.err"; "ANCHOR_EXIT=$LASTEXITCODE"; Get-Content "$Out\proposal_summary.json" -Encoding UTF8; Get-Content "$Out\anchor_map_summary.json" -Encoding UTF8; "PROPOSAL_LINES=$(@(Get-Content "$Out\proposal.txt").Count)" } else { "WRITE_REFUSED=True — CODE_FROM_WORKTREE=$CodeOk DATA_OK=$DataOk. False인 항목을 회신해 주십시오. 아무것도 쓰지 않았습니다." }
```

> **왜 `cmd /c`로 감싸는가**: 요약 JSON에 한국어가 들어갑니다. PowerShell 5.1은 네이티브 명령의
> stdout을 cp949로 디코딩했다 재인코딩하며 JSON 구조 문자를 잃습니다(2026-09-14 실측). `cmd /c`의
> `>`는 바이트를 그대로 파일에 씁니다.

**판정**: `PROPOSAL_EXIT=0` · `ANCHOR_EXIT=0`. 기대값은 제안 요약의 `"judged_slugs": 15` ·
`"by_verdict": {"approved": 13, "rejected": 2}`, 앵커 요약의 `"distinct_slugs": 15`이며,
`PROPOSAL_LINES=15`입니다. `unmapped_count`가 0이 아니면 **실패가 아니라 결과**입니다 — 그 목록을
회신에 포함해 주십시오(예: 모델이 스펙과 다른 성취기준 코드를 적은 문항).

---

## 4. 승격 게이트 1회 — 창 ① (읽기 전용 + 리포트 파일만 씀)

백필 감사로그는 저장소의 정본 7종(`docs\data\review_status_backfill_audit\*.jsonl`)을 **그대로**
넘깁니다 — 이번 회차 문항의 각인 기록이 없다는 사실 자체가 판정 입력입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 승격 게이트(거부가 정상 · 선행 조건 재검사)
cd C:\Users\kiki\Desktop\__AI\WhyMath-mp03
$AuditFiles = @(Get-ChildItem "docs\data\review_status_backfill_audit\*.jsonl")
$AuditArgs = ($AuditFiles | ForEach-Object { "--backfill-audit " + $_.FullName }) -join " "
$HasProposal = (Test-Path "$Out\proposal.txt")
$HasInputs = ((Test-Path $Corpus) -and (Test-Path $RQ) -and (Test-Path $Ev))
$HasAudits = ($AuditFiles.Count -gt 0)
$Sum = "import json,collections,sys; g=json.load(open(sys.argv[1],encoding='utf-8')); u=g['defect_rate_upper']; print('PROPOSED',g['proposed'],'ON_PATH',g['on_path'],'OFF_PATH',g['off_path'],'REVIEWED',g['reviewed'],'DEFECTS',g['defects'],'UPPER',(round(u,4) if u is not None else 'NONE'),'MAX',g['max_defect_rate'],'APPROVED',g['approved']); print('REASONS',dict(collections.Counter(v['blocked_reason'] for v in g['verdicts'])))"
if ($HasProposal -and $HasInputs -and $HasAudits) { cmd /c "$PyExe -m whymath_backend.harness.golden_promotion_gate --proposal $Out\proposal.txt --review-queue $RQ --review-events $Ev --corpus $Corpus $AuditArgs --json $Out\promotion_gate.json > $Out\promotion_gate.md 2> $Out\promotion_gate.err"; "GATE_EXIT=$LASTEXITCODE"; "AUDIT_FILES=$($AuditFiles.Count)"; & $PyExe -c $Sum "$Out\promotion_gate.json" } else { "RUN_REFUSED=True — PROPOSAL=$HasProposal INPUTS=$HasInputs AUDITS=$HasAudits. False인 항목을 회신해 주십시오." }
```

**판정**: `GATE_EXIT=1`(거부)이 이번 시도의 정상값입니다. `AUDIT_FILES=7`. 마지막 두 줄
(`PROPOSED … APPROVED False`와 `REASONS {…}`)이 MP-03 ②의 핵심 수치입니다 — 그대로 회신해
주십시오. `GATE_EXIT=2`면 `$Out\promotion_gate.md` 끝부분의 `[입력 오류]` 줄을 회신해 주십시오.

---

## 5. 골든 벤치 첫 동결 — 창 ① (새 폴더 `mp02-out\mp03\golden_benchmark_v1\`에만 씀)

`--edit-aware-since 2026-09-01T04:51:35Z`는 EOS-62(승인/수정승인 구분) 착지 시각입니다. 그 이후
검수의 `approved`는 "손대지 않은 승인"이라 정답지에 `clean`으로 들어갑니다 — 게이트
`G-eos-first-run-canary-review` 증적의 측정(`hit_cu_metrics`)이 쓴 경계와 같은 값입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — 골든 벤치 동결(선행 조건 재검사)
cd C:\Users\kiki\Desktop\__AI\WhyMath-mp03
$GDir = "$Out\golden_benchmark_v1"
$HasMap = (Test-Path "$Out\anchor_map.jsonl")
$HasEv = (Test-Path $Ev)
$GSum = "import json,collections,sys; g=json.load(open(sys.argv[1],encoding='utf-8')); it=g['items']; print('GOLDEN_VERSION',g['golden_version'],'ROTATION',g['rotation'],'FROZEN_AT',g['frozen_at'],'DIGEST',g['digest'],'ITEMS',len(it)); print('LABELS',dict(collections.Counter(i['label'] for i in it)),'ANCHORS',dict(collections.Counter(i['anchor_id'] for i in it)),'BASIS',dict(collections.Counter(i['as_found_basis'] for i in it)))"
if ($HasMap -and $HasEv) { New-Item -ItemType Directory -Force -Path $GDir | Out-Null; cmd /c "$PyExe -m whymath_backend.harness.golden_benchmark --events $Ev --anchor-map $Out\anchor_map.jsonl --edit-aware-since 2026-09-01T04:51:35Z --golden-version v1 --rotation 0 --out $GDir\golden.json --report $GDir\golden_promotion.md > $Out\golden_benchmark.out 2> $Out\golden_benchmark.err"; "GOLDEN_EXIT=$LASTEXITCODE"; "GOLDEN_JSON=$(Test-Path "$GDir\golden.json")"; if (Test-Path "$GDir\golden.json") { & $PyExe -c $GSum "$GDir\golden.json" } else { Get-Content "$GDir\golden_promotion.md" -Encoding UTF8 } } else { "RUN_REFUSED=True — ANCHOR_MAP=$HasMap EVENTS=$HasEv. §3을 먼저 성공시켜 주십시오." }
```

**판정**: `GOLDEN_EXIT=0` · `GOLDEN_JSON=True`. 기대값은 `ITEMS 15` · `LABELS {'clean': 13,
'defective': 2}` · `ANCHORS {'A4': 15}` · `BASIS`에 `edit_aware_verdict` 13과
`rejected_failure_code` 2입니다. `GOLDEN_EXIT=1`이면 리포트가 대신 출력됩니다 — "측정 실패"
문구가 보이면 그것도 결과이므로 그대로 회신해 주십시오(0점으로 적지 않습니다).

---

## 6. 회신 목록

1. §1의 `CODE_FROM_WORKTREE` · `HEAD_MATCHES_REMOTE` · `HEAD`
2. §2의 목록 전체 + `DATA_OK`
3. §3의 `PROPOSAL_EXIT` · `ANCHOR_EXIT` · 두 요약 JSON 전문 · `PROPOSAL_LINES`
4. §4의 `GATE_EXIT` · `AUDIT_FILES` · `PROPOSED …` 줄 · `REASONS …` 줄
5. §5의 `GOLDEN_EXIT` · `GOLDEN_JSON` · `GOLDEN_VERSION …` 줄 · `LABELS …` 줄

회신을 받으면 세션이 MP-03 ②(탈락 사유 분포)·④(시계열 첫 점)를 기록하고 게이트를 닫습니다.
만든 파일은 전부 `mp02-out\mp03\` 아래에 있고 코퍼스 데이터라 저장소에 커밋하지 않습니다.
워크트리는 끝난 뒤 지우셔도 됩니다 — 이 블록은 선택입니다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — (선택) 워크트리 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
git worktree remove --force C:\Users\kiki\Desktop\__AI\WhyMath-mp03
"WORKTREE_LEFT=$(Test-Path C:\Users\kiki\Desktop\__AI\WhyMath-mp03)"
```

---

## 근거 대장 (세션이 저장소에서 확인한 것)

| 주장 | 근거 |
|---|---|
| 검수 기록 파일명 `canary_review_events_v3.jsonl` · 30이벤트 · 판정 15 | `backlog/gates.yaml` `G-eos-first-run-canary-review` evidence |
| 1회차 `run_id c0854e382b50415eb11829d991c93820` · 출력 폴더 `Desktop\__AI\mp02-out` | `MEMORY.md` 2026-09-21 MP-02 항 |
| 게이트 인자·exit 규칙(0 허용·1 거부·2 입력 오류) | `harness/golden_promotion_gate.py` `main` |
| 골든 벤치 인자·exit 규칙(승격 0건 = exit 1) | `harness/golden_benchmark.py` `main` |
| 입력 파생 CLI의 exit 규칙·비날조 | `harness/golden_inputs.py` · `tests/backend/harness/test_golden_inputs.py` |
| `edit-aware-since` 경계값 | `G-eos-first-run-canary-review` evidence(`hit_cu_metrics` 측정 경계) |
| 명령 흐름 전체의 모의 실행(가짜 `mp02-out` · 28행 큐 · 30이벤트) | 세션 실측 2026-09-25: 제안 15 · 앵커 A4 15 · `GATE_EXIT=1` · `GOLDEN_EXIT=0` |
