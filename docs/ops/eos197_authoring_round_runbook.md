# EOS-197 — A6 LLM 저작 회차 1회 (두 좌석 × 15 CU) Kiki 실행 런북

> **판정 기준: EOS-198이 머지된 뒤의 main.** 초안의 판정 기준 main `1c441f59`(그때 읽은 코드:
> `harness/problem_corpus_accumulate.py`·`harness/review_session.py`·`ops/hit_cu_metrics.py`·
> `ops/weekly_metrics_report.py`·`l3/equivalent/llm_generator.py`·`l3/generation_seed.py`·
> `l3/router.py`·`config.py`·`scripts/ops/check_runbook_blocks.py`)에 더해, EOS-198이 바꾼 세
> 모듈을 읽는다 — `ops/weekly_metrics_report.py`(파일 입력 모드·cu_slug 조인)·
> `harness/problem_corpus_accumulate.py`(A6 과목·slug 접두)·`ops/provenance_audit.py`
> (`data/runs/` 검사). [B]가 그 코드가 **실제로 import됐는지** 실측한다(`EOS198_CODE=True`) —
> EOS-198이 main에 없으면 `READY_B=False`이고 [F]·[G]가 스스로 거부한다.
>
> **실행 방식(D10 Kiki 2026-10-23 결정 (다) 보류)**: 무인 실행기를 쓰지 않는다. Kiki가 이 런북의
> 블록을 **손으로** 붙여넣어 한 회차를 돈다.
>
> **역할 분담**: Kiki 머신은 저작·검수·산출물 push([A]~[L])까지만 한다 — DB에도 주간 KPI
> 원장에도 쓰지 않는다. `metrics/weekly.json`의 `measured: true` 기록은 **세션이** [L]로 넘겨받은
> JSONL을 주간 KPI CLI의 **파일 입력 모드**(`--events-jsonl`·`--generation-log-jsonl`)로 집계해
> PR로 남긴다. [K]는 같은 CLI·같은 파일·같은 창을 `--dry-run`으로 돌린 미리보기다.

---

## 공백 — 착수 조사에서 나온 7건과 그 처리 (실행 전에 읽을 것)

G-A·G-B·G-D·G-F·G-G는 **EOS-198이 코드·문서로 해소했다**(이 런북은 그 착지 뒤에 돈다). G-C는 Kiki
결정으로 그대로 두고, G-E는 폴더 구조로 우회한다.

| ID | 공백 | 근거(파일:줄) | 이 런북의 처리 |
|---|---|---|---|
| G-A **해소** | (종전) `ops/weekly_metrics_report`가 **DB만** 읽었다(`review_timer_event`·`generation_log`). 저작·검수 CLI는 JSONL에만 쓰고 JSONL→DB 적재기는 0건이었다. → EOS-198 ①: **파일 입력 모드** — `--events-jsonl`(반복)·`--generation-log-jsonl`(반복)을 주면 DB에 연결하지 않고 그 파일을 같은 `aggregate`·`build_record_from_report`로 집계한다. 창은 `--week-start`/`--week-end`로 지정한다(회차가 실행 시각 기준 직전 7일 밖이어도 된다). 같은 입력이면 DB 경로와 같은 레코드가 나온다(실 PG 대조 테스트 포함). | 종전 `ops/weekly_metrics_report.py:377-417`·`:487-489` · 테스트 `tests/backend/ops/test_weekly_metrics_file_input.py`·`test_weekly_metrics_report_integration.py::TestDbPathEqualsFileInputMode` | [K]가 이 CLI를 `--dry-run`으로 돌려 미리보기를 낸다. 원장 기록은 세션이 [L]로 받은 **같은 파일·같은 창**으로 한다. |
| G-B **해소** | (종전) DB 경로가 생성 로그 행을 `problem_id`·`cost_usd`·토큰 4키로만 옮겨 `cu_slug`를 버렸다 — 배치 저작 행(`problem_id=None`)의 비용이 CU에 조인되지 않아 `unit_cost_krw`가 미측정이었다. → EOS-198 ②: 변환을 `_genlog_row_for_aggregate` 하나로 모으고 `cu_slug`를 싣는다(DB·파일 공통). | 테스트 `test_weekly_metrics_file_input.py::TestCuSlugJoin`(cu_slug 제거 뮤테이션 RED) | [K]의 `PREVIEW_UNIT_COST_KRW_MEASURED=True`가 조인이 일했다는 증거다. |
| G-C 유지 | openrouter 좌석의 GenerationLog는 **`seed`가 항상 `null`**이다(seed는 LOCAL 결정에서만 뽑아 싣는다). **Kiki 결정 2026-10-27: 구조적 미지원으로 기록하고 W-18 충족으로 인정 — 코드 수정 없음.** 산출물에는 정직하게 드러난다: 그 좌석 행은 `seed: null`(0·가짜 값이 아니다)이고, 읽기측 분류 `capability_for_model`은 이 모델명을 "지원"으로 반올림하지 않는다. | `l3/generation_seed.py:94-100`·`:114-115` · `l3/equivalent/llm_generator.py:453-454` | [H]가 좌석별 `CU_MISSING_SEED`를 그대로 보고한다(로컬 0 · openrouter = CU 수가 정상). `provenance_audit`는 seed를 **로컬 좌석만** 검사하고, 검사하지 않은 행 수를 모델별로 적는다(검사 안 함 ≠ 통과). |
| G-D **해소** | (종전) 저작 CLI가 생성기를 `공통`·`wm-gen-quad`로 **고정**해, A6 CU가 과목 `공통`·slug `wm-gen-quad-…`로 기록됐다. → EOS-198 ③: spec의 성취기준 코드 `[12미적Ⅰ-…]`이면 과목 **`미적분`**·slug 접두 **`wm-gen-calc1`**(결정론 미적분Ⅰ 정본 `p3_diff_skeleton_base.py`와 같은 과목 값). 그 밖의 코드(이차방정식 등)는 종전 값 그대로다. | `harness/problem_corpus_accumulate.py`(`authoring_subject_for_codes`) · 테스트 `tests/backend/harness/test_accumulate_authoring_subject.py` | [B]가 이 코드가 import됐는지 보고, [H]가 `CU_SUBJECT_CALC`·`CU_SLUG_CALC1`이 그 좌석 CU 수와 같은지 센다. |
| G-E | 저작 CLI가 `run_id`를 실행 중에 `uuid4`로 **스스로** 만든다(입력 인자 없음). 실행 전에 run_id 이름의 산출 폴더를 정할 수 없고, 목표 15건을 못 채워 회차를 덧붙이면 한 파일에 run_id가 여러 개다. | `harness/problem_corpus_accumulate.py:1347` | 폴더를 **좌석 이름**으로 둔다(`data/runs/eos197-a6-local/` · `…-openrouter/`). run_id는 각 폴더의 `cu.rounds.jsonl`·`cu.genlog.jsonl`이 담는다. |
| G-F **해소** | (종전) `provenance_audit`가 `data/corpus/`만 봐서 이 회차가 무엇을 내든 exit 0이었다(변별력 0). → EOS-198 ④: `data/runs/*/cu.jsonl`의 `license`·`source_type`과 곁의 `cu.genlog.jsonl`(같은 `cu_slug`의 **성공** 호출 조인 · `model_name`·`prompt_version`·`input_sha256` · `seed`는 로컬 좌석만)을 검사한다. `--require-runs`면 회차 0건도 위반이다. CI backend 잡도 `data/runs/` 변경에 깨어난다(`ci.yml` backend 필터). | `ops/provenance_audit.py`(`audit_runs_root`) · 테스트 `tests/backend/ops/test_provenance_audit_runs.py`(실 저작 CLI 산출물 감사 포함) | [H]가 워크트리에서 `--require-runs`로 돌려 `PROVENANCE_EXIT=0`을 본다(완료 검사 ③과 같은 검사). |
| G-G **해소** | (종전) A6 범위가 문서마다 달랐다 — ADR-007은 `12미적Ⅰ` 02-01~02-10, 앵커 레지스트리는 02-05~02-10. → **Kiki 결정 2026-10-27: 정본 = 레지스트리.** EOS-198 ⑤가 ADR-007을 v2.3으로 정정했다(결정 내용 불변 · 정정 이력 절). | `docs/architecture/adr/ADR-007-eos-g2-disposition.md` §정정 이력 · `data/corpus/eos_anchor_set_v1/anchors.yaml:167-187` | spec 4종 = 02-05·02-07·02-09·02-10(02-06·02-08은 정답 단일화 곤란으로 제외 — EOS-197 ⑥). |

**위험(공백은 아니다)**: 저작 CLI가 `[12미적Ⅰ-…]` 코드로 돈 기록이 MEMORY에 없다(지금까지의 LLM 회차는 전부 이차방정식 `[9수02-20]`·`[10공수1-02-02]`). 수용률을 예측할 근거가 없으므로, [F]·[G]가 목표(15건)에 닿을 때까지 회차를 덧붙이되 **시도 상한 45건**에서 멈춘다.

---

## 6항목 사전 브리핑

### ① 과제 명칭
EOS-197 A6(고2 도함수의 활용) LLM 저작 회차 1회 — 로컬 좌석 15 CU + openrouter 좌석 15 CU, 이어서 카나리 검수(타이머 ON).

### ② 목적
12/31 판정 조건 ③(D4 교체)과 G2 재판정(11/8, ADR-007)의 물증을 만든다: A6 저작 산출물 30행 이상 + CU별 생성 로그(모델·프롬프트 버전·시드·입력 해시) + 사람 검수 타이머로 잰 HIT 첫 유효 표본(15건 이상). 두 좌석을 같은 조건으로 돌려 **로컬과 클라우드 저작의 수용률·비용을 비교 기록**한다(D3 Kiki 2026-10-23 결정 (c)). 결과물은 세션이 git 브랜치로 넘겨받아([L]) main에 커밋하고, **같은 JSONL을 주간 KPI CLI의 파일 입력 모드로 집계해** 원장(`metrics/weekly.json`)의 첫 `measured: true` 기록을 만든다.

### ③ 구체적 절차 (예상 소요)

| 블록 | 무엇 | 쓰기 | 예상 |
|---|---|---|---|
| [A] | 격리 워크트리 준비 | 워크트리 폴더 | 1분 |
| [B] | 환경·코드 출처 자가검증 | 없음 | 1분 |
| [C] | 클라우드 좌석 설정·OpenRouter 키 자가검증(키 값 미출력) | 없음 | 1분 |
| [C-1]·[C-2] | 키 입력·등록 — **[C]가 키 없음을 말할 때만** | User 환경변수 1개 | 1분 |
| [D] | Ollama 모델 확인(라우터에 묻는다) | 없음 | 1분 (모델이 없으면 [D-1] 내려받기 10~30분) |
| [E] | 산출 폴더 현황(이어하기 판정) | 없음 | 즉시 |
| [F] | **좌석 1 = 로컬 `qwen3:30b-a3b`** 저작 — 15행에 닿을 때까지(상한 45시도) | 산출 파일 | **15~45분** |
| [G] | **좌석 2 = openrouter `deepseek/deepseek-v4.1-flash`** 저작 — 같은 조건 | 산출 파일 · 유료 호출 | **8~25분** |
| [H] | 두 좌석 산출물·GenerationLog 4필드 검사 | 없음 | 즉시 |
| [I] | 검수 큐 조립(두 좌석 번갈아 섞기) | 큐 파일 1개 | 즉시 |
| [J] | **카나리 검수**(대화형 · 타이머 ON) | 이벤트·판정 파일 | **60~120분**(30건 × 2~4분 · 나눠서 가능) |
| [K] | HIT·비용 요약 + 주간 KPI 미리보기 | 없음 | 1분 |
| [L] | 산출물 브랜치 커밋·push + 원격 대조 | git 브랜치 1개 | 1~2분 |
| [M] | (선택) 워크트리 정리 — 세션이 수신을 확인한 뒤에만 | 워크트리 삭제 | 즉시 |
| [N] | 회신 | — | — |

**총 예상: 약 1.5~3.5시간**(검수 [J]가 절반 이상). [J]는 `--resume`으로 나눠 할 수 있다. 주간 KPI 집계 창은 [K]가 **산출물의 시각에서 직접** 정하므로(파일 입력 모드 `--week-start`/`--week-end` — G-A 행) 검수를 며칠에 나눠도 된다.

로컬 시간 근거: `qwen3:30b-a3b` 저작 60시도가 20~60분(MP-02 3회차·`docs/reviews/mp02_rerun_runbook.md` §7-2) → 시도당 20~60초. 첫 호출은 모델 로드에 30초~2분이 더 걸린다. openrouter 시간 근거: EOS-121 90호출 20~40분(`docs/ops/eos121_seat_generation_diversity_runbook.md` §5) → 시도당 약 15~25초.

### ④ 성공 기준
- [B] `READY_B=True` · [C] `READY_C=True` · [D] `READY_D=True`. 하나라도 False면 [F]·[G]가 **스스로 거부**한다(`WRITE_REFUSED=True`와 이유가 출력된다).
- [F] `LOCAL_DONE lines=` 15 이상 · [G] `OPENROUTER_DONE lines=` 15 이상 → 합계 30행 이상.
- [H] 좌석마다 `CU_MISSING_GENLOG=0`·`CU_MISSING_MODEL_NAME=0`·`CU_MISSING_PROMPT_VERSION=0`·`CU_MISSING_INPUT_SHA256=0`. `CU_MISSING_SEED`는 로컬 0 · openrouter = 그 좌석 CU 수(공백 G-C — Kiki 결정으로 이것이 정상값이다). 좌석마다 `CU_SUBJECT_CALC`·`CU_SLUG_CALC1` = 그 좌석 `CU_LINES`(공백 G-D). `PROVENANCE_EXIT=0`(공백 G-F).
- [J] 세션 요약의 `승인 + 수정승인 + 반려` 합 = [I]의 `QUEUE_LINES`.
- [K] `HIT_…_EXIT=0` · `CU_MEASURED` 15 이상 · `IMPLAUSIBLE_MAJORITY=False` · `PREVIEW_HIT_SECONDS_MEASURED=True` · `PREVIEW_UNIT_COST_KRW_MEASURED=True`.
- [L] `PUSH_VERIFIED=True`.
- **한 좌석이 실패해도 다른 좌석 산출물은 지워지지 않는다**(좌석별 폴더 · 덮어쓰기 없음 · append만). 실패한 좌석은 그 출력 전문을 회신하고 나머지 단계는 이어가도 된다.
- **실패 시 대처(공통)**: `WRITE_REFUSED=True`·`READ_REFUSED=True`가 나온 블록은 **아무것도 쓰지 않았다.** 그 줄의 False 항목을 보고 앞 블록을 다시 붙여넣는다. 창을 새로 열었다면 [B]부터 다시(창 변수가 사라졌기 때문이다).

### ⑤ 실행 환경
- **머신**: Phaiakes9 = 평소 쓰시는 이 PC. 별도 접속·SSH·WSL 불요.
- **시스템**: Windows PowerShell.
- **원 작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` (평소 클론 — 브랜치·미커밋 변경을 **하나도 건드리지 않는다**).
- **실행 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath-eos197` ([A]가 main 최신 커밋으로 만드는 격리 워크트리). 산출물도 여기 `data\runs\` 아래에 쌓인다.
- **파이썬**: `C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe` + `PYTHONPATH`로 워크트리 코드를 먼저 읽게 한다(import 후 `__file__`로 확인).
- **선행 조건**: Ollama 가동 · 인터넷(openrouter 좌석 · 모델 내려받기) · OpenRouter 키(User 환경변수 — 2026-09-16 등록 기록이 있다, [C]가 확인).
- **불요**: Docker·`whymath-pg`(5433)·백엔드 서버. **이 회차는 DB에 아무것도 쓰지 않는다** — 주간 KPI는 세션이 파일 입력 모드로 집계한다(공백 G-A).
- **좌석 제약**: Anthropic 좌석은 쓰지 않는다(ARCH-66 · 12/31까지 API 중단 — [C]가 `AN_API_ENABLED=False`를 확인). openrouter 좌석은 **학생 데이터 0** 조건에서만 쓴다 — 이 회차의 모델 입력은 spec 4종·주제 힌트·오개념 카탈로그 라벨·이번 회차 자신의 산출물(회피 목록)뿐이고, `--seed` 코퍼스 3종(전건 `WHYMATH_GENERATED`·자체생성 1,327행)은 **로컬 중복 판정에만** 쓰인다(`harness/problem_corpus_accumulate.py:336-358`). 공급사는 `deepinfra`로 고정 · 관할 표기는 코드상 `US`(`l3/providers/openrouter.py:106`)이며, 모델 자체는 DeepSeek(중국 개발 오픈웨이트)다.

### ⑥ 창 구분
- **창 ①** (새 PowerShell 창) — [A]~[N] 전부. 앞 블록이 만든 변수를 뒤 블록이 쓰므로 **같은 창에서 이어 간다.** [F]·[G]는 수십 분 걸린다 — 도는 동안 그 창을 건드리지 마십시오. `Ctrl+C`는 복사가 아니라 **중단 신호**입니다(중단해도 그때까지의 생성 로그·대장은 호출마다 즉시 기록돼 남는다).
- **창 ②** (새 창 · [D]가 Ollama 미가동을 말할 때만) — `ollama serve` 한 줄. **그 창은 서버가 점유하므로 이후 아무것도 입력하지 마십시오.**
- [J]는 **대화형**이다 — [J] 블록은 그 한 줄만 붙여넣는다(뒤에 붙인 줄이 판정 입력으로 먹힌다 — 2026-09-22 실측·MP-11).

---

## [A] 격리 워크트리 준비 — 창 ① (1분)

이미 워크트리가 있으면(앞 시도) **건드리지 않는다** — 그 안의 `data\runs\` 산출물을 지우지 않기 위해서다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [A] 격리 워크트리 준비
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos197"
$WtExisted = Test-Path $Wt
"WORKTREE_EXISTED=$WtExisted"
if (-not $WtExisted) { git worktree add --detach $Wt origin/main; "WORKTREE_CREATED=$(Test-Path $Wt)" } else { "WORKTREE_KEPT=True — 앞 시도의 워크트리를 그대로 씁니다(산출물 보존). 아래 두 해시가 다르면 회신에 적어 주십시오" }
"MAIN_HEAD=$(git rev-parse --short origin/main)"
"WORKTREE_HEAD=$(git -C $Wt rev-parse --short HEAD)"
```

**판정**: `WORKTREE_CREATED=True` 또는 `WORKTREE_KEPT=True`. 두 해시가 같으면 최신 main이다. 다르더라도 [B]가 이 런북에 필요한 코드·파일이 있는지 실측해 막으므로 계속 진행해도 된다(해시는 회신에 적는다 — 두 좌석이 같은 코드로 돌았는지 세션이 대조한다).

---

## [B] 환경·코드 출처 자가검증 — 창 ① (읽기 전용 · 1분)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [B] 환경·코드 출처 자가검증 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos197"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$env:PYTHONPATH = "$Wt\src\backend"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Plan = "$Wt\docs\ops\eos197_a6_spec_plan.jsonl"
$Runs = "$Wt\data\runs"
$Seeds = @("$Wt\data\corpus\problem_bank_p3_calculus1_diff_v0\problems.jsonl", "$Wt\data\corpus\problem_bank_p3_fill_v0\problems.jsonl", "$Wt\data\corpus\problem_bank_generated_v0\problems.jsonl")
$CountPy = "import sys,pathlib; p=pathlib.Path(sys.argv[1]); print(sum(1 for l in p.read_text(encoding='utf-8').splitlines() if l.strip()) if p.exists() else 0)"
$Probe = "from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator as G; from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec as S; from whymath_backend.l3.router import resolve_model; g=G(None, misconception_catalog={}, topic_hint='x', routing_sync=False); d=g._decide_routing(S(achievement_standard_codes=frozenset({'[12미적Ⅰ-02-07]'}), target_misconception_ids=frozenset(), difficulty_overall=3.0, answer_format=None)); print(resolve_model(d.local_family, d.local_model))"
$SeedsPresent = @($Seeds | Where-Object { Test-Path $_ }).Count
$CodeFile = & $Py -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOk = [bool]($CodeFile -and $CodeFile.StartsWith($Wt))
$HelpText = & $Py -m whymath_backend.harness.problem_corpus_accumulate --help | Out-String
$FlagsOk = ($HelpText -match "--spec-file") -and ($HelpText -match "--authoring-tier") -and ($HelpText -match "--avoid-recent")
$PlanCount = & $Py -c "import sys,pathlib; from whymath_backend.harness.problem_corpus_accumulate import load_spec_plan_file as L; e=L(pathlib.Path(sys.argv[1]), default_standard_code='[12미적Ⅰ-02-05]', default_difficulty=2.5, default_topic_hint='x'); print(len(e)); [print(s, sorted(sp.achievement_standard_codes)[0], sp.difficulty_overall) for s, sp, _ in e]" $Plan
$PlanOk = ($PlanCount -and ($PlanCount[0] -eq "4"))
$G198Py = "from whymath_backend.harness.problem_corpus_accumulate import authoring_subject_for_codes as A; from whymath_backend.ops.weekly_metrics_report import report_from_files; from whymath_backend.ops.provenance_audit import audit_runs_root; print(A(['[12미적Ⅰ-02-05]']) == ('미적분', 'wm-gen-calc1') and A(['[10공수1-02-02]']) == ('공통', 'wm-gen-quad'))"
$G198 = & $Py -c $G198Py
$ReadyB = $CodeOk -and $FlagsOk -and $PlanOk -and ($SeedsPresent -eq 3) -and ($G198 -eq "True")
"IO_ENCODING=$(& $Py -c 'import sys; print(sys.stdout.encoding)')"
"CODE_FILE=$CodeFile"
"CODE_FROM_WORKTREE=$CodeOk"
"CLI_FLAGS_OK=$FlagsOk"
"SPEC_PLAN=$($PlanCount -join ' | ')"
"SEEDS_PRESENT=$SeedsPresent"
"EOS198_CODE=$G198"
"WORKTREE_HEAD=$(git rev-parse --short HEAD)"
"READY_B=$ReadyB"
```

**판정**: `IO_ENCODING=utf-8` · `CODE_FROM_WORKTREE=True` · `CLI_FLAGS_OK=True` · `SPEC_PLAN=4 | a6-tangent [12미적Ⅰ-02-05] 2.5 | a6-extremum … | a6-root-count … | a6-velocity …` · `SEEDS_PRESENT=3` · `EOS198_CODE=True` · `READY_B=True`.

> 변별력: `CODE_FROM_WORKTREE`는 `PYTHONPATH`가 먹지 않으면 평소 클론 경로가 찍혀 False가 된다(파일이 있다는 것과 그 파일이 import됐다는 것은 다르다). `SPEC_PLAN`은 이 런북의 PR이 머지되기 전 main에서 `FileNotFoundError`로 비고 `READY_B=False`가 된다. `SEEDS_PRESENT`는 시드 경로가 틀리면 3보다 작다 — 저작 CLI는 없는 시드를 **조용히 건너뛰므로**(`problem_corpus_accumulate.py:348-349`) 여기서 막아야 한다. `EOS198_CODE`는 EOS-198 이전 코드면 `ImportError`로 비어 False가 되고(파일 입력 모드·회차 감사·과목 선택 함수가 없다), 과목 선택이 옛 고정값으로 되돌아가 있으면 `False`가 찍힌다 — 그 상태로 저작하면 A6 CU가 다시 `공통`·`wm-gen-quad`로 기록된다.

`ModuleNotFoundError`가 나면 `& $Py -m pip install -e C:\Users\kiki\Desktop\__AI\WhyMath\src\backend`를 돌린 뒤 [B]를 다시 붙여넣는다.

---

## [C] 클라우드 좌석 설정·OpenRouter 키 자가검증 — 창 ① (읽기 전용 · 호출 0건 · 키 값 미출력)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [C] 좌석·키 자가검증 (읽기 전용 · 호출 0건 · 키 값 미출력)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$SeatOut = & $Py -c "from whymath_backend.config import Settings; from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name; from whymath_backend.harness.problem_corpus_accumulate import authoring_can_reach_cloud as R; s=Settings(); k=s.openrouter_api_key.get_secret_value(); print('SEAT=%s PIN_MID=%s ALLOWED=%s AN_API_ENABLED=%s AN_CONFIGURED=%s KEY_LEN_OK=%s KEY_HAS_ELLIPSIS=%s KEY_PREFIX_SK_OR=%s CLOUD_REACH_PAID=%s CLOUD_REACH_DEFAULT=%s' % (cloud_provider_name(s), cloud_model_pins(s)[0], ','.join(s.openrouter_allowed_providers), s.anthropic_api_enabled, s.anthropic_configured, len(k) >= 20, chr(8230) in k, k.startswith('sk-or-'), R('premium', 5000.0), R(None, None)))"
$StatusOut = & $Py -c "import asyncio; from whymath_backend.l3.providers.openrouter import OpenRouterProvider; s=asyncio.run(OpenRouterProvider().check_status()); print(f'CONFIGURED={s.configured} PROVIDERS={s.allowed_providers} JURISDICTION={s.jurisdiction} ERROR={s.error}')"
$ReadyC = [bool]($SeatOut -and ($SeatOut -match "SEAT=openrouter ") -and ($SeatOut -match "PIN_MID=deepseek/deepseek-v4\.1-flash ") -and ($SeatOut -match "ALLOWED=deepinfra ") -and ($SeatOut -match "AN_API_ENABLED=False ") -and ($SeatOut -match "AN_CONFIGURED=False ") -and ($SeatOut -match "KEY_LEN_OK=True ") -and ($SeatOut -match "KEY_HAS_ELLIPSIS=False ") -and ($SeatOut -match "KEY_PREFIX_SK_OR=True ") -and ($SeatOut -match "CLOUD_REACH_PAID=True ") -and ($SeatOut -match "CLOUD_REACH_DEFAULT=False"))
"SEAT_CHECK=$SeatOut"
"PROVIDER_STATUS=$StatusOut"
"USER_VAR_OPENROUTER_API_KEY_SET=$([bool][Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY','User'))"
"USER_VAR_WHYMATH_OPENROUTER_API_KEY_SET=$([bool][Environment]::GetEnvironmentVariable('WHYMATH_OPENROUTER_API_KEY','User'))"
"READY_C=$ReadyC"
```

**각 항목이 막는 것**:
- `SEAT=openrouter`·`PIN_MID=deepseek/deepseek-v4.1-flash`·`ALLOWED=deepinfra` — 좌석 셀렉터가 다른 값으로 덮여(환경변수 `WHYMATH_CLOUD_PROVIDER`) 다른 모델로 도는 것.
- `AN_API_ENABLED=False`·`AN_CONFIGURED=False` — Anthropic 좌석 사용(ARCH-66 위반).
- `KEY_*` — 키는 **값이 아니라 길이·형태만** 본다. 자리표시자나 말줄임표(`…`)가 키로 등록된 상태(2026-07-16 사고 유형)를 잡는다.
- `CLOUD_REACH_PAID=True` — [G]가 쓰는 라우팅 신호(`--subscription premium --budget-krw 5000`)가 정말 클라우드에 닿는다. `CLOUD_REACH_DEFAULT=False` — [F]의 신호 없는 기본값이 정말 **로컬에만** 간다(로컬 좌석이 몰래 유료 호출을 하지 않는다).

**판정**:
- `READY_C=True` → [C-1]·[C-2]를 **건너뛰고** [D]로.
- `KEY_LEN_OK=False`인데 `USER_VAR_…_SET=True`가 하나라도 있으면 **키 등록 전에 연 창**이다 — [C-1]로 가지 말고 **새 창을 열어 [B]부터** 다시.
- `KEY_LEN_OK=False`이고 `USER_VAR_…_SET`이 둘 다 False면 [C-1]로.
- `KEY_HAS_ELLIPSIS=True`이거나 `AN_…=True`이거나 `SEAT`/`PIN_MID`가 위와 다르면 **멈추고 이 출력을 회신**한다(이 런북은 기존 키·설정을 덮어쓰지 않는다).

## [C-1] 키 입력 — [C]가 키 없음을 말할 때만 · 이 블록만 단독으로 붙여넣는다

> `Read-Host`는 뒤에 붙여넣은 줄을 입력값으로 삼킨다(2026-09-18 실측). 입력은 화면에 보이지 않는다(별표도 없다). 입력 길이는 같은 줄이 바로 출력한다 — 0이면 붙여넣기가 실패한 것이다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [C-1] 키 입력 · 이 블록만 단독으로 · 입력은 화면에 보이지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$KeySecure = Read-Host "OpenRouter 키(sk-or- 로 시작)를 붙여넣고 Enter" -AsSecureString; "KEY_INPUT_LENGTH=$($KeySecure.Length)"
```

## [C-2] 키 등록 — [C-1] 다음에만

입력 형태를 **스스로 다시 검사해** 어긋나면 쓰지 않는다. 기존 User 키가 있으면 덮어쓰지 않는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [C-2] 키 등록 · User 환경변수 1개 · 키 값은 출력하지 않는다
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$KeyBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($KeySecure)
$KeyPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($KeyBstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($KeyBstr)
$KeyLength = ([string]$KeyPlain).Length
$KeyShapeOk = ($KeyLength -ge 20) -and ([string]$KeyPlain).StartsWith("sk-or-") -and (-not ([string]$KeyPlain).Contains([string][char]0x2026))
$ExistingUserKey = [bool][Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "User")
"KEY_LENGTH=$KeyLength KEY_SHAPE_OK=$KeyShapeOk EXISTING_USER_KEY=$ExistingUserKey"
if ($KeyShapeOk -and (-not $ExistingUserKey)) { [Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", $KeyPlain, "User"); $env:OPENROUTER_API_KEY = $KeyPlain; "WRITTEN_USER_KEY_LENGTH=$(([string][Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY','User')).Length)" } else { "WRITE_REFUSED=True — 키를 쓰지 않았다. KEY_SHAPE_OK=$KeyShapeOk(True여야 함 — 20자 이상·sk-or- 시작·생략 문자 없음) EXISTING_USER_KEY=$ExistingUserKey(False여야 함 — 있으면 덮어쓰지 않는다)" }
Remove-Variable KeyPlain, KeySecure
```

`WRITTEN_USER_KEY_LENGTH`가 `KEY_LENGTH`와 같으면 등록된 것이다. **[C]를 다시 붙여넣어 `READY_C=True`를 확인한 뒤** [D]로 간다.

---

## [D] Ollama 모델 확인 — 창 ① (읽기 전용 · 1분)

어느 모델이 쓰이는지 **런북이 단정하지 않고 라우터에 묻는다**(문서에 박은 모델명이 실제 라우팅과 달랐던 사고 — PR #1017).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [D] Ollama 모델 확인 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$ModelQuality = & $Py -c $Probe
$Installed = ollama list | Out-String
$QualityPresent = [bool]($ModelQuality -and $Installed.Contains($ModelQuality))
$ReadyD = ($ModelQuality -eq "qwen3:30b-a3b") -and $QualityPresent
"MODEL_QUALITY=$ModelQuality"
"OLLAMA_LIST_LINES=$(@($Installed -split [Environment]::NewLine | Where-Object { $_.Trim() }).Count)"
"QUALITY_PRESENT=$QualityPresent"
"OLLAMA_CONTEXT_LENGTH=$([Environment]::GetEnvironmentVariable('OLLAMA_CONTEXT_LENGTH','User'))"
"READY_D=$ReadyD"
```

**판정**:
- `MODEL_QUALITY=qwen3:30b-a3b` · `QUALITY_PRESENT=True` · `READY_D=True` → [E]로.
- `OLLAMA_LIST_LINES=0`(또는 `ollama` 명령 오류)이면 Ollama가 꺼져 있다 → **창 ②**에서 아래 한 줄을 실행하고 그 창은 그대로 둔 뒤, 창 ①에서 [D]를 다시.
- `QUALITY_PRESENT=False`인데 목록은 보이면 → [D-1](내려받기).
- `OLLAMA_CONTEXT_LENGTH`가 `8192`가 아니면(비어 있음 포함) 30B 모델 로드가 실패할 수 있다(성능 정본 `docs/ops/amd395_local_llm_performance.md` — 기본 262,144가 로드 실패를 일으켰다). 이 런북은 환경변수를 바꾸지 않는다 — [F]가 전건 `generation_failed`로 끝나면 이것부터 의심하고 값을 회신한다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ② — 서버 점유 창 · 이후 이 창에는 아무것도 입력하지 않는다 · Ctrl+C는 서버 중단 신호
ollama serve
```

## [D-1] 모델 내려받기 — [D]가 `QUALITY_PRESENT=False`일 때만 (약 18GB · 10~30분)

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [D-1] 모델 내려받기 (디스크 약 18GB)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$ModelQuality = & $Py -c $Probe
if ($ModelQuality -eq "qwen3:30b-a3b") { ollama pull $ModelQuality; "QUALITY_PRESENT=$([bool]((ollama list | Out-String).Contains($ModelQuality)))" } else { "WRITE_REFUSED=True — 라우터가 고른 모델이 qwen3:30b-a3b가 아니다(MODEL_QUALITY=$ModelQuality). 내려받지 않았다 — 이 출력을 회신" }
```

---

## [E] 산출 폴더 현황 — 창 ① (읽기 전용 · 즉시)

[F]·[G]는 **append만** 한다. 앞 시도의 산출물이 있으면 그 위에 이어 붙이고(중복은 저작 CLI가 기존 산출물과 대조해 막는다), 이미 15행이면 그 좌석은 호출 없이 끝난다. 그래서 여기서는 **지우지 않고 현황만** 본다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [E] 산출 폴더 현황 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$LocalOut = "$Runs\eos197-a6-local\cu.jsonl"
$OrOut = "$Runs\eos197-a6-openrouter\cu.jsonl"
$ReviewDir = "$Runs\eos197-a6-review"
if ($Py -and $Runs) { "LOCAL_LINES=$(& $Py -c $CountPy $LocalOut) LOCAL_FILES=$(@(Get-ChildItem -Path (Split-Path $LocalOut) -ErrorAction SilentlyContinue).Count)"; "OPENROUTER_LINES=$(& $Py -c $CountPy $OrOut) OPENROUTER_FILES=$(@(Get-ChildItem -Path (Split-Path $OrOut) -ErrorAction SilentlyContinue).Count)"; "REVIEW_FILES=$(@(Get-ChildItem -Path $ReviewDir -ErrorAction SilentlyContinue).Count)" } else { "READ_REFUSED=True — 창 변수 Py·Runs가 비어 있다. 새 창이면 [B]부터 다시 붙여넣으세요" }
```

첫 실행이면 전부 0이다. 0이 아니면 **지우지 말고** 이 출력을 회신에 적는다(앞 시도의 생성 로그가 원인 분석 재료다).

---

## [F] 좌석 1 — 로컬 `qwen3:30b-a3b` 저작 — 창 ① (쓰기 · 로컬 LLM · 15~45분)

**이 블록은 선행 판정을 스스로 다시 계산하고, 통과하지 못하면 실행을 거부한다.**

- **목표 15행**에 닿을 때까지 회차를 덧붙인다. 회차 크기 = `min(20, (15 − 현재 행 수) × 2)`(최소 5) · **시도 상한 45건**(수용률이 낮아도 끝없이 돌지 않는다).
- 인자: `--authoring-tier quality`(라우터 규칙이 로컬 QUALITY = `qwen3:30b-a3b`를 고른다 · MP-02 실측 채택) · `--avoid-recent 10`(회차 내 자기 중복 회피 · MP-02 3회차에서 중복 0) · `--spec-file`(A6 spec 4종 순환) · `--seed` 3종(기존 A6·미적분 자산과의 중복 차단) · `--canary 0 --abort-window 0`(회차가 20건 이하라 두 관문이 판정하지 않는다 — 꺼 둔 사실을 회차 대장에 그대로 남긴다).
- `--subscription`·`--budget-krw`를 **주지 않는다** — 그러면 라우터가 로컬로 강제한다([C]의 `CLOUD_REACH_DEFAULT=False`가 그 증거).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [F] 좌석 1: 로컬 qwen3:30b-a3b 저작 (쓰기 · 로컬 LLM 호출)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$LocalOut = "$Runs\eos197-a6-local\cu.jsonl"
$CodeFileF = & $Py -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOkF = [bool]($CodeFileF -and $CodeFileF.StartsWith($Wt))
$ModelF = & $Py -c $Probe
$PlanOkF = Test-Path $Plan
$SeedsOkF = (@($Seeds | Where-Object { Test-Path $_ }).Count -eq 3)
$G198F = & $Py -c $G198Py
"PRECHECK_F CodeOk=$CodeOkF Model=$ModelF PlanExists=$PlanOkF SeedsOk=$SeedsOkF Eos198Code=$G198F WorktreeHead=$(git rev-parse --short HEAD)"
if ($CodeOkF -and $PlanOkF -and $SeedsOkF -and ($ModelF -eq "qwen3:30b-a3b") -and ($G198F -eq "True")) {
  New-Item -ItemType Directory -Force -Path (Split-Path $LocalOut) | Out-Null
  $TriedF = 0
  $LinesF = [int](& $Py -c $CountPy $LocalOut)
  while (($LinesF -lt 15) -and ($TriedF -lt 45)) {
    $NF = [Math]::Min(45 - $TriedF, [Math]::Max(5, [Math]::Min(20, (15 - $LinesF) * 2)))
    "ROUND_START seat=local n=$NF lines_before=$LinesF tried_before=$TriedF at=$(Get-Date -Format s)"
    & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $LocalOut --seed $Seeds[0] --seed $Seeds[1] --seed $Seeds[2] --spec-file $Plan --n $NF --authoring-tier quality --avoid-recent 10 --canary 0 --abort-window 0
    $RoundExitF = $LASTEXITCODE
    $TriedF = $TriedF + $NF
    $LinesF = [int](& $Py -c $CountPy $LocalOut)
    "ROUND_END seat=local exit=$RoundExitF lines_after=$LinesF tried_after=$TriedF at=$(Get-Date -Format s)"
    if ($RoundExitF -eq 2) { "ROUND_STOP=exit2 — 연속 무진전 알람 또는 설정 오류입니다. 위 stderr 문구를 회신하세요"; break }
  }
  "LOCAL_DONE lines=$LinesF tried=$TriedF target=15 budget=45"
} else { "WRITE_REFUSED=True — 호출하지 않았다. CodeOk=$CodeOkF(True여야) Model=$ModelF(qwen3:30b-a3b여야) PlanExists=$PlanOkF(True여야) SeedsOk=$SeedsOkF(True여야) Eos198Code=$G198F(True여야 — EOS-198 이전 코드면 A6 CU가 공통·wm-gen-quad로 기록된다) · 새 창이면 [B]부터, 아니면 [B]·[D]를 다시 확인하세요" }
```

**예상 출력**: 회차마다 진행 로그 → 리포트 JSON → `ROUND_END … exit=0`(이번 회차에 1건 이상 붙음) 또는 `exit=1`(이번 회차 무진전 — 다음 회차로 넘어간다). 끝에 `LOCAL_DONE lines=15 이상`.

- `LOCAL_DONE lines=`가 15 미만이고 `tried=45`면 상한에 닿은 것이다 — **그대로 [G]로 진행**하고 회신에 적는다(실패도 산출물이다 · 좌석 비교의 데이터가 된다). 리포트 JSON의 `outcome_counts`가 어느 단계에서 막혔는지 말한다.
- 진행 로그가 **5분 이상** 멈추면 `Ctrl+C`로 중단하고 그때까지의 출력을 회신한다(이 창은 서버 창이 아니다).
- 전건 `generation_failed`면 [D]의 `OLLAMA_CONTEXT_LENGTH`부터 의심한다.

---

## [G] 좌석 2 — openrouter `deepseek/deepseek-v4.1-flash` 저작 — 창 ① (쓰기 · **유료 호출** · 8~25분)

[F]와 **글자 그대로 같은 조건**이다(spec·시드·회피 목록·목표·상한). 다른 것은 셋뿐: 출력 폴더 · 라우팅 신호 `--subscription premium --budget-krw 5000`(둘이 함께여야 클라우드로 간다) · `--authoring-tier`를 주지 않음(클라우드 결정에는 로컬 티어가 쓰이지 않는다). `--top-p`는 **주지 않는다**(EOS-121 정정 — 각 공급사 기본값).

**비용(곱셈 추정 · 청구서 대조값 아님)**: deepinfra 실단가 입력 $0.20 · 출력 $0.60 / 1M 토큰(`l3/router.py:143`) × 시도당 입력 약 3,000 · 출력 약 1,500 토큰 가정 → 시도당 약 $0.0015 · 상한 45시도 약 $0.07(**약 100원**, 환율 `USD_TO_KRW=1540` · `l3/router.py:177`). `--budget-krw`는 라우팅 티어 입력이지 **지출 상한이 아니다.**

**좌석별 폴더를 따로 두는 이유**: 회차 대장·생성 로그·검수 큐 사이드카가 `--out` 경로에서 파생되므로(`with_suffix` · `problem_corpus_accumulate.py:738-759`) 좌석마다 분리되고, **두 좌석이 같은 중복 인덱스를 공유하지 않는다** — 같은 파일에 쌓으면 뒤 좌석이 앞 좌석 산출물과도 중복 판정을 받아 비교가 오염된다. 한 좌석이 실패해도 다른 좌석의 파일은 건드리지 않는다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [G] 좌석 2: openrouter 저작 (쓰기 · 유료 클라우드 호출)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$OrOut = "$Runs\eos197-a6-openrouter\cu.jsonl"
$CodeFileG = & $Py -c "import whymath_backend.harness.problem_corpus_accumulate as m; print(m.__file__)"
$CodeOkG = [bool]($CodeFileG -and $CodeFileG.StartsWith($Wt))
$SeatG = & $Py -c "from whymath_backend.config import Settings; from whymath_backend.l3.providers.factory import cloud_model_pins, cloud_provider_name; from whymath_backend.harness.problem_corpus_accumulate import authoring_can_reach_cloud as R; s=Settings(); k=s.openrouter_api_key.get_secret_value(); print('%s|%s|%s|%s|%s' % (cloud_provider_name(s), cloud_model_pins(s)[0], s.anthropic_api_enabled, len(k) >= 20 and k.startswith('sk-or-') and chr(8230) not in k, R('premium', 5000.0)))"
$SeatOkG = ($SeatG -eq "openrouter|deepseek/deepseek-v4.1-flash|False|True|True")
$PlanOkG = Test-Path $Plan
$SeedsOkG = (@($Seeds | Where-Object { Test-Path $_ }).Count -eq 3)
$G198G = & $Py -c $G198Py
"PRECHECK_G CodeOk=$CodeOkG SeatCheck=$SeatG SeatOk=$SeatOkG PlanExists=$PlanOkG SeedsOk=$SeedsOkG Eos198Code=$G198G WorktreeHead=$(git rev-parse --short HEAD)"
if ($CodeOkG -and $SeatOkG -and $PlanOkG -and $SeedsOkG -and ($G198G -eq "True")) {
  New-Item -ItemType Directory -Force -Path (Split-Path $OrOut) | Out-Null
  $TriedG = 0
  $LinesG = [int](& $Py -c $CountPy $OrOut)
  while (($LinesG -lt 15) -and ($TriedG -lt 45)) {
    $NG = [Math]::Min(45 - $TriedG, [Math]::Max(5, [Math]::Min(20, (15 - $LinesG) * 2)))
    "ROUND_START seat=openrouter n=$NG lines_before=$LinesG tried_before=$TriedG at=$(Get-Date -Format s)"
    & $Py -m whymath_backend.harness.problem_corpus_accumulate --out $OrOut --seed $Seeds[0] --seed $Seeds[1] --seed $Seeds[2] --spec-file $Plan --n $NG --subscription premium --budget-krw 5000 --avoid-recent 10 --canary 0 --abort-window 0
    $RoundExitG = $LASTEXITCODE
    $TriedG = $TriedG + $NG
    $LinesG = [int](& $Py -c $CountPy $OrOut)
    "ROUND_END seat=openrouter exit=$RoundExitG lines_after=$LinesG tried_after=$TriedG at=$(Get-Date -Format s)"
    if ($RoundExitG -eq 2) { "ROUND_STOP=exit2 — 연속 무진전 알람 또는 설정 오류입니다. 위 stderr 문구를 회신하세요"; break }
  }
  "OPENROUTER_DONE lines=$LinesG tried=$TriedG target=15 budget=45"
} else { "WRITE_REFUSED=True — 호출하지 않았다(과금 0). CodeOk=$CodeOkG(True여야) SeatCheck=$SeatG(openrouter|deepseek/deepseek-v4.1-flash|False|True|True여야) PlanExists=$PlanOkG SeedsOk=$SeedsOkG Eos198Code=$G198G(True여야) · [B]·[C]부터 다시 확인하세요" }
```

**판정**: `OPENROUTER_DONE lines=15 이상`. 호출이 전건 실패하면(리포트 `outcome_counts`가 전부 `generation_failed`) 키·네트워크 문제다 — 출력 전문을 회신한다. 이 좌석이 실패해도 [F]의 산출물은 그대로이며 [H]~[L]은 이어 갈 수 있다.

---

## [H] 두 좌석 산출물·GenerationLog 4필드 검사 — 창 ① (읽기 전용 · 즉시)

CU 1행마다 그 CU를 만든 성공 생성 호출 1건(`cu_slug`가 같은 genlog 행)을 찾아 4필드(`model_name`·`prompt_version`·`seed`·`input_sha256`)가 채워졌는지 센다. `input_sha256`은 입력 스냅샷에서 스키마가 재계산해 채운다(`schema/provenance.py:559-561`). 이어서 CU의 과목·slug 접두(공백 G-D)를 세고, 완료 검사 ③과 **같은 감사**(`provenance_audit --require-runs` — 공백 G-F)를 이 워크트리의 `data\runs\`에 돌린다.

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [H] 산출물·GenerationLog 4필드 검사 (읽기 전용)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$SeatCheckPy = "import json,sys,pathlib
d=pathlib.Path(sys.argv[1])
def rows(p):
    return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()] if p.exists() else []
c=rows(d/'cu.jsonl'); g=rows(d/'cu.genlog.jsonl'); r=rows(d/'cu.rounds.jsonl')
slugs=[x.get('slug') for x in c]
ok={}
for x in g:
    if x.get('cu_slug') and x.get('success'):
        ok[x['cu_slug']]=x
miss={'genlog':0,'model_name':0,'prompt_version':0,'seed':0,'input_sha256':0}
for s in slugs:
    x=ok.get(s)
    if x is None:
        miss['genlog']+=1
        continue
    for k in ('model_name','prompt_version','seed','input_sha256'):
        if x.get(k) is None:
            miss[k]+=1
costs=[x.get('cost_usd') for x in g]
print('SEAT_DIR=%s' % d.name)
print('CU_LINES=%d DISTINCT_SLUGS=%d' % (len(c), len(set(slugs))))
print('CU_SUBJECT_CALC=%d CU_SLUG_CALC1=%d' % (sum(1 for x in c if x.get('subject') == '미적분'), sum(1 for x in c if str(x.get('slug', '')).startswith('wm-gen-calc1-'))))
print('ROUNDS=%d RUN_IDS=%s' % (len(r), ','.join(str(x.get('run_id')) for x in r)))
print('ATTEMPTED=%d ACCEPTED=%d APPENDED=%d' % (sum(x.get('attempted',0) for x in r), sum(x.get('accepted',0) for x in r), sum(x.get('appended',0) for x in r)))
print('GENLOG_ROWS=%d GENLOG_SUCCESS=%d' % (len(g), sum(1 for x in g if x.get('success'))))
print('MODELS=%s' % ','.join(sorted({str(x.get('model_name')) for x in g})))
print('PROMPT_VERSIONS=%s' % ','.join(sorted({str(x.get('prompt_version')) for x in g})))
for k,v in miss.items():
    print('CU_MISSING_%s=%d' % (k.upper(), v))
print('COST_USD_SUM=%.6f COST_NULL_ROWS=%d' % (sum(v for v in costs if v is not None), sum(1 for v in costs if v is None)))"
$HaveH = [bool]($Py -and $Runs -and ((Test-Path "$Runs\eos197-a6-local\cu.jsonl") -or (Test-Path "$Runs\eos197-a6-openrouter\cu.jsonl")))
if ($HaveH) { & $Py -c $SeatCheckPy "$Runs\eos197-a6-local"; "---"; & $Py -c $SeatCheckPy "$Runs\eos197-a6-openrouter"; "TOTAL_CU_LINES=$([int](& $Py -c $CountPy "$Runs\eos197-a6-local\cu.jsonl") + [int](& $Py -c $CountPy "$Runs\eos197-a6-openrouter\cu.jsonl"))"; "---"; & $Py -m whymath_backend.ops.provenance_audit --require-runs; "PROVENANCE_EXIT=$LASTEXITCODE" } else { "READ_REFUSED=True — 두 좌석 모두 cu.jsonl이 없다(또는 창 변수가 없다 — 새 창이면 [B]부터). [F]·[G] 출력을 회신하세요" }
```

**판정**:
- `TOTAL_CU_LINES` 30 이상(완료 검사 ③의 첫 항).
- 좌석마다 `CU_MISSING_GENLOG=0` · `CU_MISSING_MODEL_NAME=0` · `CU_MISSING_PROMPT_VERSION=0` · `CU_MISSING_INPUT_SHA256=0`.
- `CU_MISSING_SEED`: 로컬 = 0 · openrouter = 그 좌석 `CU_LINES`와 같은 값(공백 G-C — 지금 코드의 정상값). 로컬에서 0이 아니면 이상 신호다 — 회신.
- `MODELS`: 로컬 폴더 = `qwen3:30b-a3b` · openrouter 폴더 = `deepseek/deepseek-v4.1-flash`. 다른 이름이 섞이면 좌석이 갈린 것이다 — 회신.
- `COST_USD_SUM`: 로컬 = 0.000000(로컬 0원 확정 — `l3/pregenerate/provenance_bridge.py:115-116`) · openrouter = 0보다 큰 값.
- `CU_SUBJECT_CALC`·`CU_SLUG_CALC1`: 둘 다 그 좌석 `CU_LINES`와 같은 값(과목 `미적분`·slug `wm-gen-calc1-…` — 공백 G-D). 0이면 EOS-198 이전 코드로 저작된 것이다 — 회신.
- `PROVENANCE_EXIT=0`: 감사 출력의 `회차 루트`가 이 워크트리의 `data\runs`이고 `스캔한 회차    : 2`(좌석 둘 · 검수 폴더는 `cu.jsonl 없는 폴더`로 따로 적힌다)·`위반 : 0건`. `seed 미검사` 줄에 openrouter 모델이 그 좌석 CU 수만큼 적히는 것이 정상이다(공백 G-C). exit 1이면 위반 줄 전체를 회신한다.

> 변별력: 이 검사는 세션 실측에서 genlog 행이 없는 CU를 `CU_MISSING_GENLOG=1`로 잡았다(가짜 산출물 주입 · 2026-10-27). `provenance_audit --require-runs`는 회차 폴더가 없으면 `RUNS_EMPTY`로 exit 1이고, 로컬 좌석 seed 결손·`prompt_version` 결손·조인 불가를 각각 exit 1로 잡는다(`tests/backend/ops/test_provenance_audit_runs.py` — 실 저작 CLI 산출물에 결함을 주입한 경우 포함).

---

## [I] 검수 큐 조립 — 창 ① (쓰기 · 큐 파일 1개 · 즉시)

두 좌석 산출물을 **한 건씩 번갈아** 한 큐로 묶는다 — 한 좌석을 몰아서 보면 피로·익숙함이 한쪽 HIT에만 실린다. 같은 slug는 한 번만 싣는다. 큐 파일이 이미 있으면 **덮어쓰지 않는다**(앞 검수의 분모가 바뀌기 때문이다 — 이어서 검수하려면 [J-2]의 `--resume`을 쓴다).

> 큐는 저작 산출물(`cu.jsonl`, 전건 수용분)이다. 카나리 절단 CLI(`harness/canary_slice`)는 쓰지 않는다 — 그 CLI는 회차 대장의 `canary_size`가 필요한데 이 회차는 `--canary 0`이라 그 값이 없어 exit 1이 난다(MP-07 런북 §7). 검수 CLI는 코퍼스 JSONL을 그대로 큐로 받는다(`review_session --queue` 도움말).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [I] 검수 큐 조립 (쓰기 · 큐 파일 1개)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$ReviewDir = "$Runs\eos197-a6-review"
$Queue = "$ReviewDir\canary_review_queue.jsonl"
$QueuePy = "import json,sys,pathlib,itertools
a=pathlib.Path(sys.argv[1]); b=pathlib.Path(sys.argv[2]); q=pathlib.Path(sys.argv[3])
def rows(p):
    return [l for l in p.read_text(encoding='utf-8').splitlines() if l.strip()] if p.exists() else []
ra=rows(a); rb=rows(b)
if q.exists():
    print('QUEUE_WRITTEN=False REASON=queue_file_already_exists')
    raise SystemExit(1)
out=[]; seen=set(); dup=0
for x in itertools.chain.from_iterable(itertools.zip_longest(ra, rb)):
    if x is None:
        continue
    s=json.loads(x).get('slug')
    if s in seen:
        dup+=1
        continue
    seen.add(s); out.append(x)
q.parent.mkdir(parents=True, exist_ok=True)
q.write_text(''.join(l+chr(10) for l in out), encoding='utf-8')
back=sum(1 for l in q.read_text(encoding='utf-8').splitlines() if l.strip())
print('LOCAL_ROWS=%d OPENROUTER_ROWS=%d CROSS_SEAT_DUP_SLUGS=%d' % (len(ra), len(rb), dup))
print('QUEUE_WRITTEN=True QUEUE_LINES=%d' % back)"
$TotalI = [int](& $Py -c $CountPy "$Runs\eos197-a6-local\cu.jsonl") + [int](& $Py -c $CountPy "$Runs\eos197-a6-openrouter\cu.jsonl")
$QueueExistedI = Test-Path $Queue
"PRECHECK_I TotalCuLines=$TotalI QueueExisted=$QueueExistedI"
if (($TotalI -ge 15) -and (-not $QueueExistedI)) { & $Py -c $QueuePy "$Runs\eos197-a6-local\cu.jsonl" "$Runs\eos197-a6-openrouter\cu.jsonl" $Queue; "QUEUE_EXIT=$LASTEXITCODE"; "QUEUE_FILE_LINES=$(& $Py -c $CountPy $Queue)" } else { "WRITE_REFUSED=True — 큐를 만들지 않았다. TotalCuLines=$TotalI(15 이상이어야 — HIT 유효 표본 하한) QueueExisted=$QueueExistedI(False여야 — 이미 있으면 [J-2]로 이어서 검수)" }
```

**판정**: `QUEUE_WRITTEN=True`와 `QUEUE_LINES=` 뒤의 숫자 · `QUEUE_EXIT=0` · `QUEUE_FILE_LINES`가 같은 숫자. **그 숫자가 검수 완주 분모다** — 적어 두십시오. `CROSS_SEAT_DUP_SLUGS`는 보통 0이다(slug가 발문·정답·성취기준 코드의 해시라 좌석이 달라도 같은 글이면 같아진다 — `l3/equivalent/llm_generator.py:1210-1218` · 0이 아니면 회신에 적는다).

---

## [J] 카나리 검수 — 창 ① (**대화형** · 타이머 ON · 60~120분)

한 건씩 화면에 뜨고, 판정 키를 누르면 다음 건으로 넘어간다. **타이머는 도구가 직접 잰다**(사람이 시간을 적는 방식은 쓰지 않는다).

**HIT 하한 가드(OPS-90)가 있다**: 한 건의 검수 경과가 **30초 미만**이면 "비현실적으로 짧은 검수"로 세고, 그런 건이 절반 이상이면 이번 회차 HIT는 **무효(미측정)**가 된다(`ops/hit_cu_metrics.py` 모듈 설명 "HIT 하한 가드"). 그러니 **다른 창에서 미리 읽어 두지 말고, 이 화면에서 처음 읽고 판정**해 주십시오(2026-09-22 회차는 미리 읽은 뒤 결정만 다시 눌러 중앙값 6초 — 무효였다).

### 판정 키 (폐쇄 집합 · `harness/review_session.py`)

| 키 | 의미 | 반려코드 |
|---|---|---|
| `a` | 승인 — 그대로 쓸 수 있다 | 불요 |
| `e` | 수정승인 — 손질하면 쓸 수 있다 | 선택(Enter로 생략) |
| `r` | 반려 — 못 쓴다 | **필수**(F1~F8 번호) |
| `s` | 보류 — 지금 판단하지 않는다 | 불요(판정으로 세지 않는다) |
| `q` | 세션 종료 — 현재 항목은 중단으로 기록 | 불요 |

반려코드: F1 수식·파싱 실패 · F2 정답 불일치 · F3 풀이 논리 비약 · F4 성취기준 이탈 · F5 난이도 미스 · F6 오개념 오연결 · F7 언어 수준 부적합 · F8 힌트 정답 누설(`docs/standards/eos_verification_design_v1.md` §4).

**A6 검수 관점(참고)**: 접선의 y절편·극댓값·실근 개수(정수 k의 개수)·속도 — 답 하나가 정수로 정해지는가, 성취기준 코드가 문항 내용과 맞는가(F4), 과목은 `미적분`·slug는 `wm-gen-calc1-…`로 찍혀 있어야 한다(공백 G-D 해소 — [H]가 이미 셌다. 다르게 찍혀 있으면 검수를 멈추고 회신한다).

**아래 블록은 대화형 명령 한 줄뿐이다. 다른 줄과 함께 붙여넣지 마십시오.** [I]가 `QUEUE_WRITTEN=True`를 낸 뒤에만 실행한다.

```powershell
& $Py -m whymath_backend.harness.review_session --queue "$Runs\eos197-a6-review\canary_review_queue.jsonl" --events "$Runs\eos197-a6-review\canary_review_events.jsonl" --verdicts "$Runs\eos197-a6-review\canary_review_verdicts.jsonl" --reviewer-id kiki
```

**판정**: 마지막에 `=== 검수 세션 요약 ===`이 뜨고 `승인 + 수정승인 + 반려`의 합이 [I]의 `QUEUE_LINES`와 같으면 완주다. 적으면 보류·중단이 남은 것이다 → [J-2].

**`[입력 실패] 검수 대상 0건`**(exit 1)이면 큐가 비었다는 뜻이다("0건 통과"가 아니라 측정 실패) → [I]로 돌아간다.

## [J-2] 이어서 검수 — 중간에 그만둔 뒤 (대화형 한 줄)

`q`로 끝냈거나 창을 닫았다면, (새 창이면 [B]를 먼저 붙여넣은 뒤) 아래 한 줄만 붙여넣는다. 이미 종결한 건을 건너뛴다(이중 계측 방지). 이벤트·판정은 항목마다 즉시 기록되므로 그때까지의 기록은 남아 있다.

```powershell
& $Py -m whymath_backend.harness.review_session --queue "$Runs\eos197-a6-review\canary_review_queue.jsonl" --events "$Runs\eos197-a6-review\canary_review_events.jsonl" --verdicts "$Runs\eos197-a6-review\canary_review_verdicts.jsonl" --reviewer-id kiki --resume
```

---

## [K] HIT·비용 요약 + 주간 KPI 미리보기 — 창 ① (읽기 전용 · 1분)

`ops/hit_cu_metrics`를 좌석별 생성 로그로 한 번씩 돌려 HIT·비용을 내고, 이어서 **주간 KPI CLI를 파일 입력 모드·`--dry-run`으로** 돌려 원장(`metrics/weekly.json`)에 들어갈 레코드를 미리 낸다(공백 G-A·G-B 해소분). **원장에는 쓰지 않는다** — 원장 기록은 세션이 [L]로 받은 같은 파일로 한다.

집계 창은 **산출물의 시각에서 정한다**: 검수 이벤트의 `recorded_at`과 두 좌석 생성 로그의 `generated_at` 중 가장 이른 시각부터 가장 늦은 시각 + 1초까지(`WINDOW_START`·`WINDOW_END`). 주간 KPI CLI는 창 밖 행을 빼므로(DB 경로의 WHERE와 같은 규칙) 이 창이면 회차의 행이 하나도 빠지지 않는다 — CLI가 stderr로 내는 `[파일 입력] … 창 안 N행` 줄이 그 확인이다. 환율은 라우터 상수 `USD_TO_KRW`(1540)를 그대로 넘긴다(주간 KPI CLI는 기본 환율을 두지 않는다 — 세션도 같은 값으로 기록한다).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [K] HIT·비용 요약 + 주간 KPI 미리보기 (읽기 전용 · 파일 입력 모드 --dry-run · 원장 미기록)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$HitPy = "import io,json,sys,contextlib,pathlib
from datetime import datetime,timedelta
from whymath_backend.ops import hit_cu_metrics as H
from whymath_backend.ops import weekly_metrics_report as W
from whymath_backend.l3.router import USD_TO_KRW
ev,vd,gl,go=(pathlib.Path(a) for a in sys.argv[1:5])
for seat,g in (('local',gl),('openrouter',go)):
    buf=io.StringIO()
    with contextlib.redirect_stdout(buf):
        code=H.main(['--events',str(ev),'--verdicts',str(vd),'--generation-log',str(g),'--json'])
    r=json.loads(buf.getvalue())
    print('HIT_%s_EXIT=%d CU_MEASURED=%s HIT_MEDIAN_S=%s IMPLAUSIBLE_MAJORITY=%s CU_WITH_COST=%s COST_USD_TOTAL=%s COVERAGE=%s' % (seat.upper(), code, r['cu_measured'], r['hit_median_seconds'], r['hit_implausible_majority'], r['cu_with_cost'], r['cost_usd_total'], r['coverage_rate']))
ts=[]
for p,key in ((ev,'recorded_at'),(gl,'generated_at'),(go,'generated_at')):
    for l in p.read_text(encoding='utf-8').splitlines():
        if l.strip():
            v=json.loads(l).get(key)
            if v:
                ts.append(datetime.fromisoformat(v))
if not ts:
    print('WINDOW_UNKNOWN=True — 시각이 찍힌 행이 0건이다(측정 실패 · 회신)')
    raise SystemExit(1)
ws=min(ts).isoformat()
we=(max(ts)+timedelta(seconds=1)).isoformat()
print('WINDOW_START=%s WINDOW_END=%s TIMESTAMPED_ROWS=%d' % (ws, we, len(ts)))
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    code=W.main(['--dry-run','--events-jsonl',str(ev),'--generation-log-jsonl',str(gl),'--generation-log-jsonl',str(go),'--week-start',ws,'--week-end',we,'--krw-per-usd',str(USD_TO_KRW)])
rec=json.loads(buf.getvalue())
print('WEEKLY_CLI_EXIT=%d WEEK_START=%s WEEK_END=%s' % (code, rec['week_start'], rec['week_end']))
for k in ('hit_seconds','unit_cost_krw'):
    v=rec['kpis'][k]
    print('PREVIEW_%s_MEASURED=%s VALUE=%s REASON=%s' % (k.upper(), v['measured'], v['value'], v['reason']))
print('PREVIEW_ONLY=True LEDGER_WRITTEN=False')"
$EvK = "$Runs\eos197-a6-review\canary_review_events.jsonl"
$VdK = "$Runs\eos197-a6-review\canary_review_verdicts.jsonl"
$HaveK = [bool]($Py -and (Test-Path $EvK) -and (Test-Path $VdK) -and (Test-Path "$Runs\eos197-a6-local\cu.genlog.jsonl") -and (Test-Path "$Runs\eos197-a6-openrouter\cu.genlog.jsonl"))
if ($HaveK) { "EVENT_LINES=$(& $Py -c $CountPy $EvK) VERDICT_LINES=$(& $Py -c $CountPy $VdK)"; & $Py -c $HitPy $EvK $VdK "$Runs\eos197-a6-local\cu.genlog.jsonl" "$Runs\eos197-a6-openrouter\cu.genlog.jsonl"; "HIT_SUMMARY_EXIT=$LASTEXITCODE" } else { "READ_REFUSED=True — 검수 이벤트·판정 파일 또는 좌석 생성 로그가 없다. 검수 이벤트=$(Test-Path $EvK) 판정=$(Test-Path $VdK) 로컬로그=$(Test-Path "$Runs\eos197-a6-local\cu.genlog.jsonl") openrouter로그=$(Test-Path "$Runs\eos197-a6-openrouter\cu.genlog.jsonl") · 한 좌석이 실패했다면 그대로 회신하세요(세션이 좌석 하나로 집계한다)" }
```

**판정**:
- `HIT_LOCAL_EXIT=0`·`HIT_OPENROUTER_EXIT=0` · `CU_MEASURED` 15 이상(HIT 유효 표본 목표) · `IMPLAUSIBLE_MAJORITY=False`.
- `CU_WITH_COST`: 로컬 줄 = 로컬 CU 중 검수된 수 · openrouter 줄 = openrouter CU 중 검수된 수(각 좌석 로그는 자기 CU만 조인한다 — 다른 좌석 CU는 미조인으로 분리되는 것이 정상이다).
- `WINDOW_START`·`WINDOW_END`가 찍히고 `WEEKLY_CLI_EXIT=0`. stderr의 `[파일 입력] … 이벤트 N행 중 창 안 N행 … 생성 로그 M행 중 창 안 M행 · 파싱 실패 0행` — **창 안 행 수가 전체 행 수와 같아야** 한다(다르면 회차 행이 창 밖으로 빠진 것이다 — 회신).
- `PREVIEW_HIT_SECONDS_MEASURED=True` · `PREVIEW_UNIT_COST_KRW_MEASURED=True` — 세션이 같은 파일·같은 창으로 원장에 기록할 **바로 그 값**이다. `IMPLAUSIBLE_MAJORITY=True`이면 HIT 미리보기가 False로 나오고 사유에 "HIT 하한 30초 미만(절반 이상)"이 적힌다 — 그 경우 검수가 재입력 세션으로 읽힌 것이니 회신에 그대로 적는다. 사유에 "입력 파싱 실패"가 있으면 파일 하나가 깨진 것이다(부분 입력으로는 판정하지 않는다) — 회신.

> 변별력: 파일 입력 모드는 입력 0건·창 밖·비용 미기록·cu_slug 결손·파싱 실패·파일 없음을 전부 `measured: false`(사유 동반)로 낸다. cu_slug를 지우는 뮤테이션은 `unit_cost_krw`를 `measured False`·"이번 주 비용 계측 완료 CU 0건"으로 떨어뜨려 회귀 테스트가 RED가 된다(`tests/backend/ops/test_weekly_metrics_file_input.py` — 공백 G-B).

---

## [L] 산출물 브랜치 커밋·push + 원격 대조 — 창 ① (쓰기 · git 브랜치 1개 · 1~2분)

세션은 Kiki 머신의 파일을 직접 볼 수 없다 — **git 브랜치로 넘겨받는다.** 워크트리에서 `data/runs/` 아래 새 파일만 커밋해 브랜치 `eos197/a6-authoring-output`로 push한다. main에는 push하지 않는다(main은 머지 큐 전용). 이 블록은 **다른 파일이 바뀌어 있으면 커밋하지 않는다**(산출물 외 변경이 섞이지 않게).

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [L] 산출물 커밋·push (쓰기 · 원격 브랜치 1개)
cd C:\Users\kiki\Desktop\__AI\WhyMath-eos197
$Branch = "eos197/a6-authoring-output"
$EmailSet = [bool](git config user.email)
$NewFiles = @(git status --porcelain --untracked-files=all -- data/runs).Count
$OtherDirty = @(git status --porcelain -- . ':!data/runs').Count
$RemoteExists = [bool](git ls-remote --heads origin $Branch)
$SessionFiles = @("eos197-a6-local\cu.jsonl", "eos197-a6-local\cu.genlog.jsonl", "eos197-a6-local\cu.rounds.jsonl", "eos197-a6-openrouter\cu.jsonl", "eos197-a6-openrouter\cu.genlog.jsonl", "eos197-a6-openrouter\cu.rounds.jsonl", "eos197-a6-review\canary_review_queue.jsonl", "eos197-a6-review\canary_review_events.jsonl", "eos197-a6-review\canary_review_verdicts.jsonl")
$MissingL = @($SessionFiles | Where-Object { -not (Test-Path "$Runs\$_") })
$ReviewOkL = (Test-Path "$Runs\eos197-a6-review\canary_review_events.jsonl") -and (Test-Path "$Runs\eos197-a6-review\canary_review_verdicts.jsonl")
"PRECHECK_L EmailSet=$EmailSet NewFiles=$NewFiles OtherDirty=$OtherDirty RemoteBranchExists=$RemoteExists ReviewFilesPresent=$ReviewOkL"
"SESSION_FILES_MISSING=$($MissingL.Count) $($MissingL -join ' ')"
if ($EmailSet -and ($NewFiles -gt 0) -and ($OtherDirty -eq 0) -and (-not $RemoteExists) -and $ReviewOkL) { git checkout -B $Branch; git add -- data/runs; git commit -m "EOS-197: A6 저작 회차 산출물 — 두 좌석 cu.jsonl·생성 로그·회차 대장·검수 이벤트 (Kiki 머신 실행분)"; git push -u origin $Branch; $LocalSha = git rev-parse HEAD; $RemoteSha = ((git ls-remote origin "refs/heads/$Branch") -split "\s+")[0]; "COMMITTED_FILES=$(@(git show --name-only --format= HEAD).Count)"; "LOCAL_SHA=$LocalSha"; "REMOTE_SHA=$RemoteSha"; "PUSH_VERIFIED=$($LocalSha -eq $RemoteSha)" } else { "WRITE_REFUSED=True — 커밋·push하지 않았다. EmailSet=$EmailSet(True여야 — git 사용자 설정) NewFiles=$NewFiles(1 이상이어야) OtherDirty=$OtherDirty(0이어야 — 산출물 밖 변경이 있으면 목록을 회신) RemoteBranchExists=$RemoteExists(False여야 — 이미 있으면 앞 push가 성공한 것일 수 있다. 회신하세요) ReviewFilesPresent=$ReviewOkL(True여야 — 검수 이벤트·판정 파일이 없는 채로 push하면 이 블록이 다시는 push하지 않으므로 [J]를 먼저 마치세요)" }
```

**판정**: `PUSH_VERIFIED=True`(원격 브랜치 끝이 방금 만든 커밋과 같다 — push 명령의 성공 메시지가 아니라 **원격을 다시 읽어** 대조한다). `SESSION_FILES_MISSING=0`이면 세션이 원장 기록·완료 검사에 쓰는 9개 파일이 모두 실렸다 — 0이 아니면 빠진 파일 이름이 같은 줄에 찍힌다(한 좌석이 실패했다면 그 좌석 파일만 빠지는 것이 정상이며, 세션은 남은 좌석으로 집계한다). `COMMITTED_FILES`는 보통 13개 안팎이다(좌석당 `cu.jsonl`·`cu.genlog.jsonl`·`cu.rounds.jsonl`·`cu.review.jsonl`(비수용이 있을 때)·`cu.worklist.md` + 검수 폴더 3개).

- push가 인증 오류로 실패하면 `PUSH_VERIFIED=False`·`REMOTE_SHA=` 빈칸이 나온다 — 출력 전문을 회신한다(세션이 다른 회수 경로를 정한다). 커밋은 워크트리에 남아 있으므로 다시 저작할 필요는 없다.
- 판정 문구: 이 push는 **산출물 전달**이지 main 반영이 아니다. main 반영·`metrics/weekly.json` 기록은 세션이 PR로 한다 — 세션은 이 브랜치의 파일로 주간 KPI CLI를 파일 입력 모드로 돌리고(`--events-jsonl …\canary_review_events.jsonl --generation-log-jsonl …local\cu.genlog.jsonl --generation-log-jsonl …openrouter\cu.genlog.jsonl --week-start/--week-end`(=[K]의 창) `--krw-per-usd 1540`), 완료 검사 ③(`wc -l`·`provenance_audit --require-runs`·`weekly.json` measured)을 main 기준으로 다시 잰다.

---

## [M] (선택) 워크트리 정리 — 세션이 수신을 확인한 **뒤에만**

```powershell
# Windows PowerShell (= Phaiakes9) · 창 ① — [M] 워크트리 정리 (쓰기 · 세션의 수신 확인 뒤에만)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath-eos197"
$Branch = "eos197/a6-authoring-output"
$WtSha = git -C $Wt rev-parse HEAD
$RemoteShaM = ((git ls-remote origin "refs/heads/$Branch") -split "\s+")[0]
$SafeM = [bool]($WtSha -and ($WtSha -eq $RemoteShaM))
"PRECHECK_M WorktreeSha=$WtSha RemoteSha=$RemoteShaM Safe=$SafeM"
if ($SafeM) { git worktree remove $Wt; "WORKTREE_REMAINS=$(Test-Path $Wt)" } else { "WRITE_REFUSED=True — 지우지 않았다. 워크트리 커밋($WtSha)이 원격 브랜치($RemoteShaM)와 같아야 지운다 — 산출물이 원격에 없으면 지우면 안 된다" }
```

`WORKTREE_REMAINS=False`면 정리됐다. `git worktree remove`가 거부하면(남은 파일) 그대로 두셔도 된다 — 다음 회차에 방해가 되지 않는다.

---

## [N] 회신 — 이것만 주시면 됩니다

1. [A]의 `MAIN_HEAD`·`WORKTREE_HEAD` 두 줄.
2. [B]·[C]·[D]의 `READY_*` 줄(False가 있었다면 그 블록 출력 전체).
3. [F]의 `ROUND_START`/`ROUND_END` 줄 전부와 `LOCAL_DONE` · [G]의 같은 줄들과 `OPENROUTER_DONE`. 각 회차 리포트 JSON의 `outcome_counts` 줄.
4. [H]의 출력 전체.
5. [I]의 `QUEUE_LINES` 줄 · [J]의 `=== 검수 세션 요약 ===` 전체.
6. [K]의 출력 전체(stderr의 `[파일 입력]` 줄 포함 — 창 안 행 수 대조에 쓴다).
7. [L]의 `PRECHECK_L`·`SESSION_FILES_MISSING`·`PUSH_VERIFIED`·`LOCAL_SHA`·`REMOTE_SHA` 줄.

**파일 자체는 회신하지 않아도 된다** — 세션은 [L]이 push한 브랜치 `eos197/a6-authoring-output`에서 다음 9개를 읽는다: 좌석마다(`eos197-a6-local`·`eos197-a6-openrouter`) `cu.jsonl`(CU 산출물 · 완료 검사 `wc -l`)·`cu.genlog.jsonl`(GenerationLog · W-18 감사와 단위비용)·`cu.rounds.jsonl`(회차 대장 · run_id), 검수 폴더(`eos197-a6-review`)의 `canary_review_queue.jsonl`(분모)·`canary_review_events.jsonl`(HIT)·`canary_review_verdicts.jsonl`(판정). 회신의 [K] 창 값은 세션이 같은 창으로 기록했는지 대조하는 데 쓴다.

**출력을 자르지 말고 그대로** 주십시오 — 잘린 출력으로 판정하면 분모가 조용히 줄어든 것을 놓칩니다.

---

## 부록 — 근거 (실측 출처 · 판정 기준 main `1c441f59` + EOS-198 브랜치 `claude/eos-197-authoring-round`)

| 사실 | 출처 |
|---|---|
| A6 = `[12미적Ⅰ-02-05]`~`[12미적Ⅰ-02-10]` 6코드(01~04 제외) | `data/corpus/eos_anchor_set_v1/anchors.yaml:167-187` |
| G2 조건 = "A6 LLM 저작 회차 1회 ≥30 CU 산출물(GenerationLog 포함) 커밋 + OPS-90 착지" | `docs/architecture/adr/ADR-007-eos-g2-disposition.md:30` |
| 저작 CLI 인자(`--seed` 반복·`--out` 필수·`--n`·`--spec-file`·`--authoring-tier`·`--avoid-recent`·`--subscription`·`--budget-krw`·`--canary`·`--abort-window`) | `python -m whymath_backend.harness.problem_corpus_accumulate --help`(2026-10-27 세션 실행 · exit 0) |
| `--out`은 수용분만 append(코퍼스 레코드 1행 = CU 1개) · exit 0=수용≥1·1=무진전·2=알람/설정 오류 | `harness/problem_corpus_accumulate.py:5-14`·`:84-92` |
| 사이드카 = `with_suffix`(`cu.genlog.jsonl`·`cu.review.jsonl`·`cu.worklist.md`·`cu.rounds.jsonl`) | `harness/problem_corpus_accumulate.py:738-759` · `harness/anchor_round_ledger.py:732-740` |
| run_id는 CLI가 `uuid4`로 생성 · 생성 로그·리포트·검수 큐에 같은 값 | `harness/problem_corpus_accumulate.py:1341-1347`·`:1365` |
| 시드 코퍼스는 서명·slug 중복 판정에만 쓰임 · 없는 경로는 조용히 건너뜀 | `harness/problem_corpus_accumulate.py:336-358` |
| 시드 3종 라이선스 전건 `WHYMATH_GENERATED`·자체생성(504·204·619행) | 2026-10-27 세션 집계 |
| GenerationLog 4필드: `model_name`(좌석 핀)·`prompt_version`(자산 해시)·`seed`(LOCAL만)·`input_sha256`(스냅샷 재계산) | `l3/equivalent/llm_generator.py:745-769` · `l3/generation_seed.py:94-124` · `schema/provenance.py:559-561` |
| 비용: LOCAL 0.0 확정 · CLOUD는 좌석별 단가(openrouter CLOUD_MID $0.20/$0.60) | `l3/pregenerate/provenance_bridge.py:114-119` · `l3/router.py:138-143` |
| `quality` 티어 → 라우터가 `qwen3:30b-a3b` · `mid` → `qwen2.5:7b` | [B]·[D]의 `$Probe`를 2026-10-27 세션에서 실행한 결과 |
| 좌석 기본 = openrouter · 핀 `deepseek/deepseek-v4.1-flash` · 허용 공급사 `deepinfra` · `anthropic_api_enabled` 기본 False | `config.py:646`·`:747-760`·`:853-874` · [C] 점검식을 2026-10-27 세션에서 실행(키 없는 환경 — `KEY_LEN_OK=False`가 정상적으로 나옴) |
| `authoring_can_reach_cloud('premium', 5000.0)=True` · `(None, None)=False` | `harness/problem_corpus_accumulate.py:904-940` · 2026-10-27 세션 실행 |
| spec 계획 파일 4종이 `load_spec_plan_file`로 읽힘 | `docs/ops/eos197_a6_spec_plan.jsonl` · 2026-10-27 세션 실행(`SPEC_PLAN_OK 4`) |
| 검수 CLI 인자(`--queue`·`--events`·`--verdicts`·`--reviewer-id`·`--resume`·`--limit`) · 코퍼스 JSONL을 큐로 받음 | `harness/review_session.py:615-626` · `--help` 2026-10-27 실행 |
| HIT 하한 가드 30초 · 절반 이상이면 주간 KPI가 미측정으로 냄 | `ops/hit_cu_metrics.py` 모듈 설명 · `ops/weekly_metrics_report.py`(`build_record_from_report`의 `implausible_reason`) |
| 주간 KPI CLI는 (종전) DB만 읽고 genlog 행에서 `cu_slug`를 버렸다 → EOS-198이 파일 입력 모드·cu_slug 조인 추가 | 종전 `ops/weekly_metrics_report.py:377-417` · 현행 같은 파일 `report_from_files`·`_genlog_row_for_aggregate` |
| A6 산출물 과목·slug 접두 = `미적분`·`wm-gen-calc1`(그 밖의 코드는 종전 `공통`·`wm-gen-quad`) | `harness/problem_corpus_accumulate.py`(`authoring_subject_for_codes`) |
| `provenance_audit`가 `data/runs/*/cu.jsonl`·`cu.genlog.jsonl` 검사 · `--require-runs` | `ops/provenance_audit.py`(`audit_runs_root`) |
| 주간 KPI 원장 `metrics/weekly.json`은 main에 없음 · 자동 cron 산출 브랜치 2개(`ops/weekly-metrics-20261019T000122Z`·`…20261025T235900Z`)는 `measured: false`뿐이고 PR 조회 결과 0건 | `git ls-remote` · `gh api repos/kiki-s-broom/whymath/pulls?head=…`(2026-10-27) |
