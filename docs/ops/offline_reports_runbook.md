# 오프라인 리포트 7종 실행 런북 (OPS-34)

> 대상: Kiki (Phaiakes9 = 작업 PC). 이 문서는 선언≠배선 감사기(`ops/declared_unwired_audit.py`)가 "수치를 보려고 **사람이 돌린다**"로 면제한 오프라인 리포트 7종에 대해, **그 "사람"이 누구이고 언제 무엇을 돌리는지**를 적는다.

## 0. 사전 브리핑 (6항목)

1. **과제 명칭**: 오프라인 리포트 7종의 수취인·실행 시점 선언 (그리고 실행 방법)
2. **목적**: 감사기는 이 7종을 "CI에 안 붙여도 되는 리포트"로 면제해 왔지만, 면제의 전제인 "사람이 돌린다"의 그 사람과 시점이 어디에도 적혀 있지 않았다. 적히지 않은 면제는 아무도 돌리지 않아도 영원히 통과한다. 이 문서가 그 빈칸이다. 감사기는 이제 이 문서의 섹션이 실재하고, 그 안에 해당 모듈의 실행 명령과 `수취인`·`시점` 표지가 있는지를 CI에서 검사한다.
3. **구체적 절차**: 아래 §3의 7개 섹션 중 지금 필요한 리포트의 블록 하나를 붙여넣는다. 7종 모두 **저장소와 DB를 바꾸지 않는다**(결과 파일은 임시 폴더에만 쓴다). 소요는 리포트마다 수 초~1분 안쪽이다.
4. **성공 기준**: 블록 마지막 줄의 `EXIT=` 값이 섹션에 적힌 기대값과 같다. 6종은 `EXIT=0`이고, `pedagogy_policy_eval`만 표본이 쌓이기 전까지 `EXIT=1`이 **정상**이다(§3-4). 기대값과 다르면 리포트가 돌지 못한 것이고 원인은 같은 화면 위쪽 오류 문구에 있다.
5. **실행 환경**: Windows PowerShell (Phaiakes9에서 평소 쓰는 창이 곧 이 시스템이다 — SSH 불필요). 선행 조건: 이 저장소의 `.venv`에 백엔드가 설치돼 있을 것(`python -m pip install -e src/backend`). Docker·DB는 필요 없다.
6. **창 구분**: **새 창 하나**를 열어 쓴다. 서버를 점유하는 명령이 없으므로 끝난 뒤에도 그 창을 계속 쓸 수 있다.

## 1. 왜 7종이 이 문서에 있는가

| 모듈 | 입력 | 게이트 여부 |
|---|---|---|
| `harness.problem_bank_coverage` | 문항 코퍼스 + 성취기준 대장 | 아님 (exit 0/2) |
| `harness.problem_duplication_audit` | 문항 코퍼스 | 아님 (exit 0/2) |
| `harness.rephrased_corpus_hygiene` | 재서술 코퍼스 | 아님 — 단, **기본 실행이 파일을 덮어쓴다**(§3-3) |
| `harness.pedagogy_policy_eval` | 교수법 처치 로그 | **게이트** — 표본 부족이면 의도적으로 exit 1 |
| `harness.objective_coverage` | 성취기준 대장 + 소단원 DSL | 아님 (exit 0/2) |
| `harness.concept_assessment_index` | 문항 코퍼스 + 개념 콘텐츠 | 기본 아님 (`--min-problem-based-rate`를 주면 옵트인 게이트) |
| `harness.concept_content_audit` | 개념 콘텐츠 | 기본 아님 (임계 옵션을 주면 옵트인 게이트) |

전부 DB·LLM·HTTP 없이 저장소 파일만 읽는다. 그래서 CI 상시 실행으로 승격하지 않는다 — 승격하면 매 PR마다 수 초~수십 초를 쓰면서 "수치를 보는" 목적에는 쓸모가 없고, 사람이 필요한 시점에 한 번 보면 충분하다.

OPS-19 관측 러너가 자동으로 돌리는 리포트(CI 5종·compose 11종)는 이 문서의 대상이 아니다 — 그쪽은 `docs/ops/ops19_observation_reports_runbook.md`가 정본이다.

## 2. 이 문서의 형식 계약

감사기는 섹션 제목을 GitHub 앵커 규칙(소문자, 공백→하이픈)으로 변환해 `runbook:docs/ops/offline_reports_runbook.md#<앵커>` 선언을 찾고, 그 섹션 안에서 다음 셋을 모두 요구한다.

- 해당 모듈의 실행 명령 (`-m whymath_backend.<모듈>`)
- `수취인` 표지
- `시점` 표지

섹션 제목을 바꾸면 앵커가 깨져 CI가 실패한다. 의도된 동작이다.

## 3. 리포트별 실행

### problem_bank_coverage

- **수취인**: Kiki — 문항 저작 우선순위를 정하는 사람. 그가 저작 세션(content-curator)에게 지시할 때 이 수치를 입력으로 준다.
- **시점**: 새 문항 코퍼스를 저작·적재하기 **직전**(0커버 성취기준 목록이 저작 우선순위가 된다)과 **직후**(커버율이 실제로 올랐는지 확인). 지난 실행 기록은 `docs/data/problem_bank_coverage_2026-07.md`, `docs/data/problem_bank_coverage_2026-08.md`.
- **성공 기준**: `EXIT=0`. 본문 첫머리에 `문항 총계`와 `코퍼스` 수가 찍힌다 (2026-10-09 실측: 14,034문 · 코퍼스 37종).
- **읽는 법**: 종료 코드는 커버율과 무관하다. 커버율이 낮아도 0이다. `데이터없음`(파일이 없다)과 `비어있음`(파일은 있으나 0문항)은 다른 뜻이다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Out = Join-Path $env:TEMP ("whymath-offline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Py -m whymath_backend.harness.problem_bank_coverage --json "$Out\problem_bank_coverage.json"
"EXIT=$LASTEXITCODE  JSON=$Out\problem_bank_coverage.json"
```

### problem_duplication_audit

- **수취인**: Kiki — 코퍼스 중복 처분(제거·유지)을 결정하는 사람.
- **시점**: 새 `problem_bank*` 코퍼스를 적재하거나 재서술 배치를 반영하는 PR을 **머지하기 전**. 지난 처분 기록은 `docs/data/problem_duplicate_disposition_2026-08.md`, `docs/data/problem_duplicate_disposition_2026-09.md`.
- **성공 기준**: `EXIT=0`. 실중복이 나와도 종료 코드는 0이다 — 중복 건수는 본문 T2 절에서 읽는다.
- **읽는 법**: "0건"과 "검사 안 함"을 구분하려고 스캔한 코퍼스 쌍 수가 본문에 항상 적힌다. 쌍 수가 0이면 0건이 아니라 검사를 못 한 것이다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Out = Join-Path $env:TEMP ("whymath-offline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Py -m whymath_backend.harness.problem_duplication_audit --json "$Out\problem_duplication_audit.json"
"EXIT=$LASTEXITCODE  JSON=$Out\problem_duplication_audit.json"
```

### rephrased_corpus_hygiene

- **수취인**: Kiki — 재서술(rephrase) 배치를 코퍼스에 반영할지 결정하는 사람.
- **시점**: 새 재서술 배치를 `data/corpus/problem_bank_rephrased_v0/problems.jsonl`에 반영하기 **전**, 위반 문항이 몇 건인지 보려고 돌린다.
- **주의 — 이 도구는 관측 리포트가 아니라 쓰기 도구다**: 플래그 없이 실행하면 위반 문항을 **그 파일에서 제자리 삭제**한다(`--dry-run`이 없으면 `write=True`가 기본값). 아래 블록은 `--dry-run`을 고정해 두었다. 이 블록에서 `--dry-run`을 지우지 않는다. 실제 제거는 별도 PR로 하고, 그때는 이 문서가 아니라 변경 PR의 검토를 거친다.
- **성공 기준**: `EXIT=0`이고 출력 JSON에 `total`·`kept`·`dropped`가 있다 (2026-10-09 실측: total 421 · kept 421 · dropped 0). 실행 전후로 `git status`에 `problems.jsonl`이 나타나지 않아야 한다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창 — 파일을 바꾸지 않는 --dry-run 고정
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
& $Py -m whymath_backend.harness.rephrased_corpus_hygiene --dry-run
"EXIT=$LASTEXITCODE"
git status --short data/corpus/problem_bank_rephrased_v0
```

### pedagogy_policy_eval

- **수취인**: Kiki — 교수법 정책(어떤 막힘 상황에 어떤 코칭 전략을 쓸지)을 규칙표에서 학습 정책으로 승격할지 결정하는 사람. 판단 근거는 pedagogy-designer 세션이 준비한다.
- **시점**: 교수법 처치 로그(`evidence_event`)에 표본이 최소 100건(`--min-samples` 기본값) 쌓인 **뒤**. 그 전에는 돌려도 같은 답이 나온다.
- **이 게이트는 지금 의도적으로 실패한다**: 표본이 0이라 `FAIL(측정 미달)`과 `EXIT=1`이 정상이다. 0건을 "통과"로도 "성과 미달"로도 바꾸지 않는 것이 이 도구의 설계다. 그래서 CI에 걸지 않았다(항상 red로 고정되면 신호가 죽는다).
- **성공 기준(현재 상태)**: `EXIT=1`이고 마지막 줄이 `FAIL(측정 미달)`, 안전제약 줄이 `"passed": true`다 (2026-10-09 실측: 안전제약 1,000회 시도·위반 0 / 표본 0 < 최소 100). `"passed": false`가 나오면 안전제약 위반이므로 즉시 보고한다.
- **승격 시**: 표본이 쌓여 `EXIT=0`이 나오면 이 도구는 더 이상 "사람이 돌리는 리포트"가 아니라 CI 게이트 후보다. 그때 감사기의 면제와 이 섹션을 함께 걷고 `ci.yml`에 등재한다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
& $Py -m whymath_backend.harness.pedagogy_policy_eval
"EXIT=$LASTEXITCODE  (표본이 쌓이기 전에는 1이 정상)"
```

### objective_coverage

- **수취인**: Kiki — 소단원(unit) 학습목표 분해 저작을 지시하는 사람.
- **시점**: 소단원 DSL(`data/corpus/units_v1`)에 새 단원을 추가한 **직후**(커버율이 올랐는지 확인), 그리고 교육과정 저작 라운드를 계획할 때(0커버 목록이 입력).
- **성공 기준**: `EXIT=0`. 본문 §1에 `커버된 레코드`와 비율이 찍힌다 (2026-10-09 실측: 895건 중 1건, 0.11%).
- **읽는 법**: 커버율이 0.11%라도 종료 코드는 0이다. 이 수치는 "고쳐야 할 결함"이 아니라 저작 우선순위 입력이다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Out = Join-Path $env:TEMP ("whymath-offline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Py -m whymath_backend.harness.objective_coverage --json "$Out\objective_coverage.json"
"EXIT=$LASTEXITCODE  JSON=$Out\objective_coverage.json"
```

### concept_assessment_index

- **수취인**: Kiki — 개념 평가 재료(문항을 개념에 이어 주는 참조 인덱스)의 갱신을 결정하는 사람.
- **시점**: 개념 콘텐츠나 문항 코퍼스의 검수 상태가 바뀐 **뒤**, 인덱스를 다시 만들기(`--write`) 전에 현재 커버율을 확인할 때.
- **주의**: 이 블록은 `--write`를 **쓰지 않는다**. `--write`를 붙이면 `data/corpus/concept_assessment_v1/index.json`이 갱신되어 코퍼스 변경이 되므로, 그 실행은 이 문서가 아니라 변경 PR에서 한다.
- **성공 기준**: `EXIT=0`. 첫 줄 근처에 `개념 437  커버 57  미커버 380  커버율 13.0%`처럼 찍힌다 (2026-10-09 실측). `PROBLEM_BASED` 어댑터가 주입 전 0.0%에서 주입 후로 올라가는 줄이 `← 변화`로 표시되어야 측정이 유효하다 — 전후 값이 같으면 측정 자체가 무효다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창 — --write 없음(인덱스 파일을 바꾸지 않는다)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Out = Join-Path $env:TEMP ("whymath-offline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Py -m whymath_backend.harness.concept_assessment_index --json "$Out\concept_assessment_index.json"
"EXIT=$LASTEXITCODE  JSON=$Out\concept_assessment_index.json"
```

### concept_content_audit

- **수취인**: Kiki — 개념 콘텐츠 437행의 검수 승격(`ai_estimated` → 검수 완료)을 진행하는 사람.
- **시점**: 개념 콘텐츠 검수 라운드의 **시작과 끝**(검수 상태 분포가 실제로 바뀌었는지 확인).
- **성공 기준**: `EXIT=0`. `[검수 상태 분포]`와 `[결함]` 두 절이 찍힌다 (2026-10-09 실측: 437행 전량 `ai_estimated` · 결함율 0.0% · Wilson 상한 0.6%).
- **읽는 법**: "미검수 437행 (100.0%) — 이 상태로 학생 렌더 경로에 노출 중"이라는 줄은 오류가 아니라 이 감사가 드러내려는 사실이다. 종료 코드가 0이어도 이 줄이 사라질 때까지는 해결된 것이 아니다.

```powershell
# [시스템: Windows PowerShell = Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\.venv\Scripts\python.exe"
$Out = Join-Path $env:TEMP ("whymath-offline-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Py -m whymath_backend.harness.concept_content_audit --json "$Out\concept_content_audit.json"
"EXIT=$LASTEXITCODE  JSON=$Out\concept_content_audit.json"
```

## 4. 알려진 한계

- **런북 형태의 선언은 기한이 없다.** `pending-task:`는 태스크가 사라지거나 done이 되면 CI가 실패하지만, 런북 섹션은 내용이 낡아도 계속 유효로 판정된다. 날짜 기반 만료는 코드 변경 없이 모든 PR을 빨갛게 만들 수 있어 넣지 않았다. 이 문서의 수취인·시점이 현실과 어긋나면 사람이 고친다.
- **감사기는 수취인이 실제로 돌렸는지는 보지 않는다.** 섹션과 명령과 표지가 실재함까지만 판정한다 — 막는 것은 "수취인 없는 면제"이지 "수취인의 태만"이 아니다.
- 이 문서의 수취인은 모두 Kiki다. 지난 실행 기록(`docs/data/` 아래 날짜 파일들)에서 이 리포트들을 실제로 돌려 온 주체를 근거로 적었으며, 다른 담당을 두려면 이 문서의 해당 섹션과 `declared_unwired_audit.py`의 `_OFFLINE_REPORT_RECIPIENTS`를 함께 바꾼다.
