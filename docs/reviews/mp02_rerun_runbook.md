# MP-02 재회차 런북 — 로컬 모델 비교 파일럿 → 승자 모델로 2회차 (Phaiakes9 실행)

> **판정 기준: 이 런북을 착지시키는 PR의 머지 커밋.** `--authoring-tier` 옵션과
> `mp02_rerun_spec_plan.jsonl`이 그 커밋에서 처음 main에 들어온다. §1의 자가검증
> `HAS_TIER_FLAG=True`·`SPEC_PLAN_OK=3`이 그 두 가지를 기계로 확인한다 — 머지 전에 돌리면
> 둘 다 실패로 나오므로 착지 여부를 사람이 따로 기억할 필요가 없다.
>
> 대상 태스크 `MP-02-first-llm-authoring-run` · 작성 2026-09-24 · 실행 주체 **Kiki**
> 1차 회차 런북: `docs/reviews/mp02_first_llm_authoring_run_runbook.md` (이 문서는 그것을 대체하지
> 않는다 — 1차 회차의 기록으로 남는다)

---

## 0. 사전 브리핑 (6항목)

### ① 과제 명칭
**MP-02 재회차** — 로컬 모델 두 개를 같은 조건에서 30건씩 비교(파일럿)하고, 더 나은 쪽으로
60건 회차를 다시 돌린다.

### ② 목적
1차 회차(2026-09-21 · `run_id c0854e382b50415eb11829d991c93820`)는 카나리에서 차단됐다.
원인을 수치로 규명한 결과 **품질이 아니라 중복이 차단을 만들었다**:

- 카나리 통과 조건은 「Wilson 95% 하한 ≥ 0.90」이고, **중복은 판정 분모에서 빠진다**
  (`harness/batch_safety.py` `evaluate_canary`).
- 하한 0.90을 넘으려면 판정 대상이 **최소 25건이고 그 전부가 합격**해야 한다
  (실측 계산: 25/25 → 0.9023 · 24/25 → 0.8391 · 20/20 → 0.8808 · 10/10 → 0.7871).
- 1차 회차는 30건 중 **20건이 회차 내 중복**이라 판정 대상이 10건뿐이었다. 그 10건이 전부
  합격이었어도 하한 0.7871로 **통과가 수학적으로 불가능**했다.

즉 카나리 30건 중 **중복이 6건 이상이면 품질과 무관하게 차단**된다. 그래서 재회차 전에 중복을
줄이는 두 가지 조치를 한다:

1. **문제 유형 순환** — 한 가지 형태(큰 근)만 반복하던 것을 3종(큰 근·작은 근·중근)으로 번갈아
   만든다. 중복 판정은 방정식 구조와 `answer_selection`으로 나뉘므로 유형이 다르면 겹치지 않는다
   (EOS-121 실측: OpenRouter 좌석에서 3종 순환 시 중복률 25.6%).
2. **모델 비교** — 현재 저작 모델 `qwen2.5:7b`(2024년 세대, 7B)와 이미 설치된 `qwen3:30b-a3b`
   (MoE — 전체 30B 중 한 번에 3B만 계산하는 구조라 7B급 속도로 30B급 품질을 노린다)를 같은
   조건에서 30건씩 돌려 **수용 건수가 많은 쪽**을 고른다. 이 판정 규칙은 **실행 전에 여기
   고정**한다(결과를 보고 규칙을 바꾸지 않기 위해서다).

### ③ 구체적 절차
A. 격리 작업 폴더 준비 + 자가검증 (2분) → B. 모델 2종 확인 (2분, 없으면 다운로드 추가) →
C. 파일럿 ① `qwen2.5:7b` 30건 (**10~25분**) → D. 파일럿 ② `qwen3:30b-a3b` 30건 (**10~40분**) →
E. 파일럿 판정 (1분) → F. MP-02 2회차 60건 (**20~60분**) → G. 산출 자가검증 + 리콜 리허설 (2분) →
H. 회신

### ④ 성공 기준
- **파일럿 성공**: §5에서 `PILOT_VERDICT_OK=True`와 `CHOSEN_TIER=mid` 또는 `quality`가 보인다.
- **2회차 성공**: §7에서 `LEDGER_ROWS 1` · `canary_passed`가 `true` 또는 `false`(null이 아님) ·
  `RECALL_EXIT=0` 그리고 리콜 열거 건수 = `GENLOG_SAME_RUN`.
- **차단도 결과다**: 2회차가 또 카나리에서 막힐 수 있다. 그래도 이번엔 *유형 순환 + 모델 교체가
  중복을 얼마나 줄였는가*가 수치로 남고, 그것이 임계 0.90의 현실 적합성 판정(`MP-03`)의 입력이
  된다. §5가 파일럿 결과로 **차단 가능성을 미리 알려 준다**(`CANARY_FEASIBLE`).
- **실패 시 대처**: 어느 블록이든 `REFUSED` 줄이 나오면 **그 블록은 아무것도 쓰지 않은 것**이다.
  그 줄을 포함해 출력 전문을 회신해 주시고 다음 블록으로 넘어가지 마십시오.

### ⑤ 실행 환경
- **머신**: Phaiakes9 (= 평소 쓰시는 이 PC). 별도 접속 없음.
- **시스템**: Windows PowerShell
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (평소 클론) — 단 코드는 거기서
  돌리지 않고, §1이 만드는 **격리 작업 폴더** `C:\Users\kiki\Desktop\__AI\WhyMath-mp02-rerun`
  (main 최신 커밋 고정)에서 돌린다. 평소 클론의 브랜치·미커밋 변경은 하나도 건드리지 않는다.
- **산출물 위치**: `C:\Users\kiki\Desktop\__AI\mp02-rerun\` (저장소 밖 — 코퍼스를 오염시키지 않는다)
- **선행 조건**: Ollama 가동 중 · 인터넷은 모델 다운로드가 필요할 때만

### ⑥ 창 구분
- **창 ①** (새 창) — §1~§8 전부. **모든 블록이 같은 창에서 이어진다**(앞 블록이 만든 변수를
  뒤 블록이 쓴다). 창을 닫았다면 §1부터 다시 붙여넣으면 된다 — §1은 여러 번 실행해도 안전하다.
- **창 ②** (새 창) — §2에서 Ollama가 꺼져 있을 때만. **그 창은 서버가 점유하므로 이후 아무것도
  입력하지 마십시오.** `Ctrl+C`는 복사가 아니라 **서버 중단 신호**입니다.

---

## 1. 격리 작업 폴더 + 자가검증 — 창 ①

평소 클론은 여러 세션이 함께 쓰는 작업 사본이라 다른 브랜치에 있거나 미커밋 변경이 있을 수
있다. 그래서 체크아웃을 옮기지 않고 **main 최신 커밋을 별도 폴더에 펼쳐** 그 코드를 돌린다.
파이썬은 평소 `.venv`를 쓰되, `PYTHONPATH`로 격리 폴더의 코드를 먼저 읽게 한다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-mp02-rerun"
if (Test-Path $Wt) { git -C $Wt checkout --detach origin/main } else { git worktree add --detach $Wt origin/main }
git -C $Wt log -1 --oneline
"MAIN_HEAD=$(git rev-parse --short origin/main)"
"WORKTREE_HEAD=$(git -C $Wt rev-parse --short HEAD)"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$Wt\src\backend;$Wt\src\data-pipeline"
$env:PYTHONIOENCODING = "utf-8"
& $Py -c "import sys; print('IO_ENCODING', sys.stdout.encoding)"
$CodeFile = & $Py -c "import whymath_backend; print(whymath_backend.__file__)"
"CODE_FILE=$CodeFile"
$CodeOk = [bool]($CodeFile -and $CodeFile.StartsWith($Wt))
"CODE_FROM_WORKTREE=$CodeOk"
$TierProbe = & $Py -c "import inspect, whymath_backend.harness.problem_corpus_accumulate as m; print('authoring_tier' in inspect.signature(m._build_live_generator).parameters)"
$HasTier = ($TierProbe -eq "True")
"HAS_TIER_FLAG=$HasTier"
$Plan = "$Wt\docs\reviews\mp02_rerun_spec_plan.jsonl"
& $Py -c "import sys; from whymath_backend.harness.problem_corpus_accumulate import load_spec_plan_file as L; e=L(__import__('pathlib').Path(sys.argv[1]), default_standard_code='[9수02-20]', default_difficulty=2.5, default_topic_hint='x'); print('SPEC_PLAN_OK', len(e)); [print(' ', s, sorted(sp.achievement_standard_codes), sp.difficulty_overall) for s, sp, _ in e]" $Plan
```

**자가검증 판정** — 아래가 전부 보여야 §2로 갑니다:

| 보이는 것 | 뜻 |
|---|---|
| `MAIN_HEAD`와 `WORKTREE_HEAD`가 **같은 해시** | 격리 폴더가 main 최신이다 |
| `IO_ENCODING utf-8` | 리포트가 cp949에서 잘리지 않는다 |
| `CODE_FROM_WORKTREE=True` | 실제로 격리 폴더의 코드가 import된다 |
| `HAS_TIER_FLAG=True` | 모델 선택 옵션이 있는 코드다(이 런북의 PR이 머지됨) |
| `SPEC_PLAN_OK 3` + 아래 3줄(`quad-larger`·`quad-smaller`·`quad-double`) | 유형 순환 계획 파일이 읽힌다 |

> 변별력: `CODE_FROM_WORKTREE`는 `PYTHONPATH`가 안 먹으면 `C:\...\WhyMath\src\backend\...`가
> 찍혀 `False`가 나온다. `HAS_TIER_FLAG`·`SPEC_PLAN_OK`는 이 런북의 PR 머지 전 main에서
> 각각 `False`·`FileNotFoundError`가 나온다. 성공·실패가 서로 다른 화면을 낸다.

---

## 2. 모델 2종 확인 — 창 ①

어떤 모델이 쓰이는지 **런북이 단정하지 않고 라우터에 묻는다** — 1차 런북의 교훈이다(문서에 박은
모델명이 실제 라우팅과 달랐던 사고, PR #1017).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
$Probe = "from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator as G; from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec as S; from whymath_backend.l3.router import resolve_model; import sys; g=G(None, misconception_catalog={}, topic_hint='x', routing_sync=(sys.argv[1]=='mid')); d=g._decide_routing(S(achievement_standard_codes=frozenset({'[9수02-20]'}), target_misconception_ids=frozenset(), difficulty_overall=2.5, answer_format=None)); print(resolve_model(d.local_family, d.local_model))"
$ModelMid = & $Py -c $Probe mid
$ModelQuality = & $Py -c $Probe quality
"MODEL_MID=$ModelMid"
"MODEL_QUALITY=$ModelQuality"
$Installed = ollama list
"MID_PRESENT=$([bool]($Installed | Select-String -SimpleMatch $ModelMid))"
"QUALITY_PRESENT=$([bool]($Installed | Select-String -SimpleMatch $ModelQuality))"
"OLLAMA_CONTEXT_LENGTH=$([Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','User'))"
```

**판정**:
- `MODEL_MID=qwen2.5:7b` · `MODEL_QUALITY=qwen3:30b-a3b`처럼 **서로 다른 두 이름**이 찍혀야 한다.
  같거나 비어 있으면 §1이 통과하지 않은 것이다 — 출력을 회신.
- `MID_PRESENT=True` · `QUALITY_PRESENT=True`면 §3으로.
- `QUALITY_PRESENT=False`면 같은 창에서 아래를 실행한다(약 18GB · 10~30분):

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
if ($ModelQuality) { ollama pull $ModelQuality; "QUALITY_PRESENT=$([bool](ollama list | Select-String -SimpleMatch $ModelQuality))" } else { "REFUSED: MODEL_QUALITY가 비어 있다 — §2 출력을 회신" }
```

- `OLLAMA_CONTEXT_LENGTH=8192`가 아니면(비어 있음 포함) **30B 모델 로드가 실패할 수 있다**
  (성능 정본 `docs/ops/amd395_local_llm_performance.md` ★확정 결론 5 — 기본 262,144가 로드
  실패를 일으켰다). 이 런북은 환경변수를 바꾸지 않는다 — 값을 회신해 주시면 세션이 판단한다.
  파일럿 ②가 전건 `generation_failed`로 끝나면 이것부터 의심한다.
- `ollama` 명령이 실패하면 **창 ②(새 창)**에서 아래 한 줄만 실행하고 그 창은 그대로 둔다:

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서버 점유 창 · 이후 조작 금지
ollama serve
```

---

## 3. 파일럿 ① — `mid` 티어 30건 — 창 ①

**조건 고정**: 두 파일럿은 티어 하나만 다르다. 같은 유형 순환 계획 · 같은 30건 · 빈 출력 파일에서
시작 · 카나리 끔(`--canary 0`) · 롤링 중단 끔(`--abort-window 0`). 안전장치를 끄는 이유: 파일럿은
**비교 측정**이라 중간에 멈추면 두 모델의 표본 크기가 달라져 비교가 무효가 된다. 파일럿 산출물은
저장소 밖 폴더에만 쓰이고 코퍼스에 섞이지 않는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
$Root = "C:\Users\kiki\Desktop\__AI\mp02-rerun"
$OutMid = "$Root\pilot-mid\problems.jsonl"
$StaleMid = @(Get-ChildItem -Path (Split-Path $OutMid) -Filter "problems*" -ErrorAction SilentlyContinue).Count
"STALE_MID=$StaleMid"
if ($CodeOk -and $HasTier -and $StaleMid -eq 0) { New-Item -ItemType Directory -Force -Path (Split-Path $OutMid) | Out-Null; & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $OutMid --n 30 --spec-file $Plan --authoring-tier mid --canary 0 --abort-window 0 | Tee-Object -FilePath "$Root\pilot-mid\report.json"; "PILOT_MID_EXIT=$LASTEXITCODE"; "PILOT_MID_FILES=$(@(Get-ChildItem -Path (Split-Path $OutMid) -Filter 'problems*').Count)" } else { "REFUSED: 파일럿 ① 미실행 — CODE_FROM_WORKTREE=$CodeOk HAS_TIER_FLAG=$HasTier STALE_MID=$StaleMid (앞 둘은 True, 마지막은 0이어야 한다)" }
```

**예상 출력**: 진행 로그 → 리포트 JSON → `PILOT_MID_EXIT=0`(수용 1건 이상) 또는 `1`(수용 0건) →
`PILOT_MID_FILES=` 4 안팎(코퍼스·genlog·review·rounds 사이드카). 수용 0건이면 코퍼스 파일이
없어 3이 나올 수 있다 — 그것도 결과다.

`STALE_MID`가 0이 아니면 앞 시도의 잔여물이 있는 것이다. **지우지 말고** 목록을 회신해 주십시오
(앞 시도의 genlog가 원인 분석 재료다).

---

## 4. 파일럿 ② — `quality` 티어 30건 — 창 ①

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
$OutQuality = "$Root\pilot-quality\problems.jsonl"
$StaleQuality = @(Get-ChildItem -Path (Split-Path $OutQuality) -Filter "problems*" -ErrorAction SilentlyContinue).Count
"STALE_QUALITY=$StaleQuality"
if ($CodeOk -and $HasTier -and $StaleQuality -eq 0) { New-Item -ItemType Directory -Force -Path (Split-Path $OutQuality) | Out-Null; & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $OutQuality --n 30 --spec-file $Plan --authoring-tier quality --canary 0 --abort-window 0 | Tee-Object -FilePath "$Root\pilot-quality\report.json"; "PILOT_QUALITY_EXIT=$LASTEXITCODE"; "PILOT_QUALITY_FILES=$(@(Get-ChildItem -Path (Split-Path $OutQuality) -Filter 'problems*').Count)" } else { "REFUSED: 파일럿 ② 미실행 — CODE_FROM_WORKTREE=$CodeOk HAS_TIER_FLAG=$HasTier STALE_QUALITY=$StaleQuality" }
```

30B 모델은 첫 호출에서 로드에 30초~2분이 걸린다. 그 뒤로는 파일럿 ①과 비슷하거나 약간 느리다.
**40분을 넘겨도 진행 로그가 흐르고 있으면 기다린다.** 로그가 5분 이상 멈추면 `Ctrl+C`로 중단하고
(이 창은 서버 창이 아니다) 그때까지의 출력을 회신한다 — genlog는 호출마다 즉시 기록되므로 증거가
남는다.

---

## 5. 파일럿 판정 — 창 ①

**판정 규칙(실행 전 고정)**:
1. 두 파일럿 모두 대장 1행 · `attempted=30` · `model_name`이 채워져 있고 **서로 달라야** 비교가
   성립한다. 하나라도 어긋나면 `PILOT_VERDICT_OK=False` — 판정하지 않는다.
2. **`accepted_stored`(코퍼스에 실제로 들어간 건수)가 더 많은 티어**를 고른다. 동률이면 `mid`
   (바꿀 근거가 없으면 현행 유지).
3. 그 밖의 수치(중복·게이트 거부·생성 실패·유형별 성적)는 **판정에 쓰지 않고 기록만** 한다 — 결과를
   본 뒤 기준을 고르는 것을 막기 위해서다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
& $Py -c "import json,sys,pathlib
def last(p):
    q=pathlib.Path(p).with_suffix('.rounds.jsonl')
    if not q.exists(): return None
    rows=[json.loads(l) for l in q.read_text(encoding='utf-8').splitlines() if l.strip()]
    return rows[-1] if rows else None
r={'mid':last(sys.argv[1]),'quality':last(sys.argv[2])}
for t,x in r.items():
    if x is None: print('PILOT', t, 'LEDGER_MISSING'); continue
    oc=x.get('outcome_counts') or {}
    print('PILOT', t, 'model=', x.get('model_name'), 'attempted=', x.get('attempted'), 'accepted_stored=', oc.get('accepted_stored',0), 'dup=', oc.get('rejected_duplicate',0), 'gate=', oc.get('rejected_gate',0), 'gen_failed=', oc.get('generation_failed',0))
    print('  spec_outcome_counts', json.dumps(x.get('spec_outcome_counts'), ensure_ascii=False))
ok=all(x is not None and x.get('attempted')==30 and x.get('model_name') for x in r.values()) and r['mid']['model_name']!=r['quality']['model_name']
print('PILOT_VERDICT_OK', ok)
if ok:
    a={t:(x.get('outcome_counts') or {}).get('accepted_stored',0) for t,x in r.items()}
    tier='quality' if a['quality']>a['mid'] else 'mid'
    oc=r[tier].get('outcome_counts') or {}
    judged=30-oc.get('rejected_duplicate',0)
    fails=judged-oc.get('accepted_stored',0)
    print('CHOSEN_TIER', tier)
    print('CHOSEN_MODEL', r[tier].get('model_name'))
    print('CANARY_FEASIBLE', judged>=25 and fails==0, '(judged', judged, 'fails', fails, '- 25건 이상 전건 합격이어야 하한 0.90 통과)')
" $OutMid $OutQuality
```

**판정 읽는 법**:
- `PILOT_VERDICT_OK True` + `CHOSEN_TIER mid|quality` → §6으로.
- `CANARY_FEASIBLE False`면 2회차도 카나리에서 막힐 가능성이 높다는 **예보**다. 그래도 §6을
  진행한다 — 막히면 그것이 `MP-03`(임계 현실 판정)의 두 번째 데이터가 된다. 다만 여기서 멈추고
  회신만 해 주셔도 된다(세션이 판단). 어느 쪽을 택했는지 회신에 한 줄 적어 주십시오.
- `PILOT_VERDICT_OK False` → §6으로 가지 말고 이 출력 전문을 회신.

---

## 6. MP-02 2회차 60건 — 창 ①

이 블록은 §5의 판정을 **다시 계산해서** 쓴다 — 앞 출력을 눈으로 옮겨 적지 않는다. 판정이 서지
않거나 출력 폴더가 깨끗하지 않으면 **실행을 거부**한다. 카나리 30 · 임계 0.90 · 롤링 창 50 등
안전장치는 **전부 기본값**이다(1차 회차와 같은 조건 — 바뀐 것은 유형 순환과 모델뿐).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
$Out2 = "$Root\round2\problems.jsonl"
$Tier = & $Py -c "import json,sys,pathlib
def last(p):
    q=pathlib.Path(p).with_suffix('.rounds.jsonl')
    rows=[json.loads(l) for l in q.read_text(encoding='utf-8').splitlines() if l.strip()] if q.exists() else []
    return rows[-1] if rows else None
m,q=last(sys.argv[1]),last(sys.argv[2])
ok=m and q and m.get('attempted')==30 and q.get('attempted')==30 and m.get('model_name') and q.get('model_name') and m['model_name']!=q['model_name']
a=lambda x:(x.get('outcome_counts') or {}).get('accepted_stored',0)
print(('quality' if a(q)>a(m) else 'mid') if ok else '')
" $OutMid $OutQuality
"ROUND2_TIER=$Tier"
$Stale2 = @(Get-ChildItem -Path (Split-Path $Out2) -Filter "problems*" -ErrorAction SilentlyContinue).Count
"STALE_ROUND2=$Stale2"
if ($CodeOk -and $HasTier -and ($Tier -eq "mid" -or $Tier -eq "quality") -and $Stale2 -eq 0) { New-Item -ItemType Directory -Force -Path (Split-Path $Out2) | Out-Null; & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $Out2 --n 60 --spec-file $Plan --authoring-tier $Tier | Tee-Object -FilePath "$Root\round2\report.json"; "ACCUMULATE_EXIT=$LASTEXITCODE"; "ROUND2_FILES=$(@(Get-ChildItem -Path (Split-Path $Out2) -Filter 'problems*').Count)" } else { "REFUSED: 2회차 미실행 — CODE_FROM_WORKTREE=$CodeOk HAS_TIER_FLAG=$HasTier ROUND2_TIER='$Tier'(mid 또는 quality여야 한다) STALE_ROUND2=$Stale2(0이어야 한다)" }
```

**예상 출력**: `ACCUMULATE_EXIT=0`(수용 1건 이상) · `1`(카나리 차단 또는 수용 0) · `2`(연속 무진전
알람 — 이 출력 폴더는 새로 만들었으므로 나오면 이상 신호). 어느 값이든 §7로 간다.

---

## 7. 산출 자가검증 + 리콜 리허설 (acceptance ①③④) — 창 ①

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ①
& $Py -c "import json,sys,pathlib
out=pathlib.Path(sys.argv[1])
def rows(p):
    q=pathlib.Path(p)
    if not q.exists(): return None
    return [json.loads(l) for l in q.read_text(encoding='utf-8').splitlines() if l.strip()]
led=rows(out.with_suffix('.rounds.jsonl')); gen=rows(out.with_suffix('.genlog.jsonl')); rev=rows(out.with_suffix('.review.jsonl'))
print('LEDGER_ROWS', 'FILE_MISSING' if led is None else len(led))
print('GENLOG_ROWS', 'FILE_MISSING' if gen is None else len(gen))
print('REVIEW_ROWS', 'FILE_MISSING' if rev is None else len(rev))
if led:
    r=led[-1]
    print('RUN_ID', r.get('run_id'))
    for k in ('model_name','prompt_version','attempted','accepted','appended','outcome_counts','spec_outcome_counts','duplicate_sources','canary_size','canary_threshold','canary_passed','canary_rate','canary_lower_bound','canary_blocked','aborted','abort_reason'):
        print(' ', k, '=', json.dumps(r.get(k), ensure_ascii=False))
    if gen: print('GENLOG_SAME_RUN', sum(1 for g in gen if g.get('run_id')==r.get('run_id')))
" $Out2
$RunId2 = & $Py -c "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]).with_suffix('.rounds.jsonl'); rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()] if p.exists() else []; print(rows[-1]['run_id'] if rows else '')" $Out2
"RUN_ID_FOR_RECALL=$RunId2"
$CorpusArgs = @(); if (Test-Path $Out2) { $CorpusArgs = @("--corpus", $Out2) }
$Genlog2 = & $Py -c "import pathlib,sys; print(pathlib.Path(sys.argv[1]).with_suffix('.genlog.jsonl'))" $Out2
if ($RunId2) { & $Py -m whymath_backend.ops.generation_recall --genlog $Genlog2 @CorpusArgs --run-id $RunId2; "RECALL_EXIT=$LASTEXITCODE" } else { "REFUSED: 리콜 미실행 — 회차 대장에 run_id가 없다(LEDGER_ROWS를 확인)" }
```

**판정**:

| 보이는 것 | 뜻 |
|---|---|
| `LEDGER_ROWS 1` | ✅ 회차 완주 · 대장 기록 |
| `canary_passed = true` | ✅ 본배치까지 진행 — `GENLOG_SAME_RUN 60`이면 acceptance ① 충족 |
| `canary_passed = false` + `canary_blocked = true` | ✅ 차단도 결과다 — `GENLOG_SAME_RUN 30` 부근 |
| `canary_passed = null` | ❌ 판정 부재 — 버그 신고 |
| `model_name`이 §5의 `CHOSEN_MODEL`과 같음 | ✅ 고른 모델로 실제로 돌았다 |
| `RECALL_EXIT=0` + 리콜 열거 건수 = `GENLOG_SAME_RUN` | ✅ acceptance ③ 충족(과다·과소 0) |

---

## 8. 회신 — 이것만 붙여넣어 주십시오

§1의 판정 표 5줄 · §2의 `MODEL_*`·`*_PRESENT`·`OLLAMA_CONTEXT_LENGTH` · §3·§4의 `*_EXIT`·`*_FILES`
· **§5 출력 전문** · §6의 `ROUND2_TIER`·`ACCUMULATE_EXIT` · **§7 출력 전문**.
출력을 자르지 말고 그대로 주십시오.

회신을 받으면 세션이 하는 일: ①모델 판정을 MEMORY 결정 로그에 기록(모델 채택 조건 ②③ —
실측 근거·결정 로그) ②acceptance 전수 재대조 ③카나리 30건 검수가 필요하면 검수 런북
(`docs/reviews/mp02_canary_review_runbook.md`)을 이 회차 경로로 안내.

> 격리 폴더 정리는 회신 후 세션이 안내한다 — 산출물 판정 전에 지우지 마십시오.

---

## 9. 근거 (실측 출처)

| 사실 | 출처 |
|---|---|
| 1차 회차 결과(수용 8 · 중복 20 · 생성 실패 2 · 하한 0.5408) | `MEMORY.md` 2026-09-21 MP-02 항 |
| 카나리 분모에서 중복 제외 | `harness/batch_safety.py` `evaluate_canary` |
| Wilson 하한 표(25/25 → 0.9023 등) | `harness/wilson.py` `wilson_lower_bound(k, n, 0.95)` 세션 실측 |
| 저작 기본 = 동기 → 라우터 규칙 8 → 로컬 MID(GENERAL) = `qwen2.5:7b` | `l3/router.py` `_decide_local_tier` · `l3/equivalent/llm_generator.py` `_decide_routing` |
| `--authoring-tier quality` = 비동기 → 규칙 2 → 로컬 QUALITY = `QUALITY_MODEL_ID` | 같은 두 파일 + `harness/problem_corpus_accumulate.py` `_build_live_generator` |
| QUALITY 모델 `qwen3:30b-a3b` 채택 근거(정확도 비열등·생성 6배) · 파싱 실패율 16% 노출 | `MEMORY.md` 2026-08-22 OPS-48/OPS-49 항 |
| 성능 수치는 감염 기간 측정이라 잠정치 | `docs/ops/amd395_local_llm_performance.md` 상단 정정 박스(SEC-34 · 재측정 `OPS-75`) |
| 유형 순환이 중복을 가른다(3종 순환 시 OpenRouter 중복률 25.6%) | `docs/ops/eos121_seat_generation_diversity_verdict.md` |
| 사이드카 경로 = `with_suffix()` 교체 | 1차 런북 정정 박스 · `tests/infra/test_mp02_runbook_sidecar_paths.py` |
