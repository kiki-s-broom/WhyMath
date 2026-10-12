# G-s464-university-cells-populate — 대학 원자 KR 셀 prod 적재 (Kiki 실행 런북)

> 게이트 **`G-s464-university-cells-populate`**의 실행 절차다.
>
> **선행 조건**: `S4-64` PR이 main에 병합돼야 한다. 이 런북이 쓰는 `--atom-graph` 인자와
> 대학 셀 합류는 그 PR이 신설한 것이라, 병합 전 코드로 실행하면 대학 셀이 한 건도 들어가지
> 않고 조용히 끝난다(종전 CLI는 canonical·원자만 적재한다) — [C]의 `HAS_ATOM_GRAPH_FLAG`와
> [D]의 자가거부 가드가 그것을 잡는다.
>
> **이 런북은 `docs/ops/skb03_atom_node_populate_runbook.md`의 교훈을 처음부터 적용했다** —
> ①최상위 `elseif`/`else` 분기가 없고(단일 `if … { } else { }`는 닫는 중괄호와 같은 줄에서만)
> ②쓰기 블록 [D]가 선행 판정값을 스스로 재검사해 실행을 거부하며 ③실행 코드 출처를 출력으로
> 동결한다. 자리표시자는 하나도 없다.

---

## 1. 과제 명칭

대학 원자 KR 셀 적재 — 원자 백본의 대학 세부개념 512건을 `curriculum_entry`에 멱등 적재한다
(학년 13~16 = 대학 1~4학년 · `required_depth`는 원자별 `cognitive_type`에서 도출).

## 2. 목적

`S4-62`가 대학 셀을 만드는 함수를 추가했지만 어느 CLI도 그것을 부르지 않아, 대학 원자에는
학년·요구 깊이 신호가 `curriculum_entry`에 **한 번도 들어간 적이 없다**. L6 깊이정렬(랭킹 보너스,
상한 1.5·하드 게이트 아님)이 대학 원자에서 신호를 못 받는 상태였다. `S4-64`가 CLI를 배선했고,
이 런북이 그것을 prod에서 1회 실행한다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | Docker Desktop 기동 + prod DB 도달 확인 | `DOCKER_OK=True` | ~10초 (꺼져 있으면 최대 3분) |
| B | 실행 입력이 main과 같은지 판정 + 테이블·프레임워크 행 존재 + BEFORE 카운트(읽기 전용) | `PATHS_MATCH_MAIN=True` · `TABLE_EXISTS=t` · `FRAMEWORK_EXISTS=1` | ~20초 |
| C | 환경 주입 + 이번 PR 착지 확인 + 도달성 | `HAS_ATOM_GRAPH_FLAG=True` · `REACH_EXIT=0` | ~15초 |
| D | **적재** (여기서만 DB에 쓴다) | `POPULATE_EXIT=0` | ~10~60초 |
| E | AFTER 카운트 + 정합성 대조 | `AFTER_UNIV=512` | ~5초 |

**부수 효과 고지(중요)**: 이 CLI의 본업은 canonical·원자 셀 적재이고 대학 셀은 세 번째 입력으로
얹혔다. 따라서 D단계는 **canonical 437건·원자 1,311건도 함께 멱등 재적재한다.** 전부
`ON CONFLICT(entry_id) DO UPDATE`라 신규 행을 만들지 않고 같은 코퍼스로 값을 덮어쓰며
`created_at`은 보존, `updated_at`만 갱신된다. 그래도 "대학 셀만 건드린다"고 오해하지 않도록
명시한다. 기대 총 적재 건수는 437 + 1,311 + 512 = 2,260건이다.

## 4. 성공 기준

`BEFORE_UNIV=0` → `POPULATE_EXIT=0` → `AFTER_UNIV=512`이면 성공이다. 추가로 AFTER의 깊이 분포가
`conceptual` 360 · `procedural` 108 · `NULL` 44이고 `mastery`가 0건이어야 한다(코퍼스에서 직접 센
값 — 2026-10-09 실측: 대학 세부개념 512건 = 개념 360·절차 108·표상 44).

CLI가 stdout에 찍는 `대학 N건`의 N과 `AFTER_UNIV`가 **같아야 한다** — 두 값은 서로 다른 경로
(적재기가 만든 목록 vs DB 카운트)에서 나오므로 한쪽만 맞는 상태를 가른다.

`BEFORE_UNIV`가 0이 아니면 그 값을 그대로 전달한다 — 이미 누군가 적재한 흔적이라는 뜻이며,
멱등 upsert라 해롭지 않지만 이 게이트의 "처음 적재" 전제가 틀렸다는 정보다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `TABLE_EXISTS`가 `t`가 아님 | 마이그레이션 미적용 | 멈추고 [B] 화면 전달 |
| `FRAMEWORK_EXISTS`가 `1`이 아님 | `curriculum_framework`에 `KR_NC_2022` 행이 없다 — 이 상태로 적재하면 모든 셀이 외래키 위반으로 실패한다(로컬 재현 확인) | 멈추고 [B] 화면 전달 |
| `PATHS_MATCH_MAIN=False` | 실행 입력이 main과 다르다 | 멈추고 [B]의 `git status` 출력 전달 |
| `HAS_ATOM_GRAPH_FLAG=False` | 체크아웃이 S4-64 병합 커밋에 닿지 않았다 | 멈추고 [C]의 `git log` 줄과 함께 전달 |
| `REACH_EXIT`가 0이 아님 | DB에 못 붙는다 | CLI가 출력하는 사유를 그대로 전달 |
| `WRITE_REFUSED=True` | [D] 가드가 적재를 거부했다(적재 0건) | 같은 줄에 찍힌 False 항목을 먼저 해소 |
| `AFTER_UNIV`가 512가 아님 | 부분 적재 | 화면 전체 전달(값 자체가 정보다) |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop · `whymath-pg` 컨테이너(호스트 포트 **5433**) · `src\backend\.venv`
- **DB**: prod = docker `whymath-pg`(5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없다.
[B]→[C]→[D]→[E]는 **같은 창**에서 순서대로 붙여넣는다(판정 변수가 창 안에서만 산다).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에
> 아래 블록으로 넘어간다. 단 쓰기 블록 [D]는 눈 확인에 기대지 않고 스스로 거부한다.

### [A] Docker 기동 + prod DB 도달

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  "DOCKER_DAEMON=down — Docker Desktop 기동을 시도합니다(최대 180초)."
  $DockerExe = @(
    "C:\Program Files\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
  ) | Where-Object { Test-Path $_ } | Select-Object -First 1
  "DOCKER_EXE_FOUND=" + [bool]$DockerExe
  if ($DockerExe) { Start-Process $DockerExe }
  for ($i = 1; $i -le 36; $i++) {
    Start-Sleep -Seconds 5
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { "DOCKER_UP_AFTER_SEC=" + ($i * 5); break }
  }
}
docker start whymath-pg *> $null
docker ps --filter "name=whymath-pg" --format "{{.Names}} | {{.Status}} | {{.Ports}}"
$Probe = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe)
```

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `Up …` + `0.0.0.0:5433->5432/tcp`.

### [B] 실행 입력 동등성 판정 + 테이블·프레임워크 존재 + BEFORE 카운트

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
git fetch origin main
"MAIN_SHA=" + (git rev-parse --short origin/main)
"HEAD_SHA=" + (git rev-parse --short HEAD)
"----- 미커밋 변경(추적 파일) -----"
git status --porcelain --untracked-files=no
"----- 실행 입력이 main과 동일한가 -----"
git diff --quiet origin/main -- "src/backend/whymath_backend/l1/curriculum" "data/corpus/atom_graph_v1/graph.json" "data/corpus/concept_graph_v1/graph.json" "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl"
$PathsMatchMain = ($LASTEXITCODE -eq 0)
"PATHS_MATCH_MAIN=$PathsMatchMain"
"----- 테이블 존재 + BEFORE (읽기 전용) -----"
$TableExists = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT to_regclass('public.curriculum_entry') IS NOT NULL;"
"TABLE_EXISTS=$TableExists"
$FrameworkExists = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM curriculum_framework WHERE framework_id = 'KR_NC_2022';"
"FRAMEWORK_EXISTS=$FrameworkExists"
$BeforeUniv = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM curriculum_entry WHERE introduced_grade BETWEEN 13 AND 16;"
"BEFORE_UNIV=$BeforeUniv"
$BeforeTotal = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM curriculum_entry;"
"BEFORE_TOTAL=$BeforeTotal"
```

**확인**: `PATHS_MATCH_MAIN=True` · `TABLE_EXISTS=t` · `FRAMEWORK_EXISTS=1`. `BEFORE_UNIV`·`BEFORE_TOTAL`은 값 그대로 기록해 전달한다.

판정값을 **화면에 찍기만 하지 않고 변수에 담는 이유**: [D]의 자가거부 가드가 그 변수를
재검사한다. 출력만 하면 가드가 참조할 것이 없어 장식이 된다(출력은 흐름을 멈추지 않는다).

체크아웃을 옮기지 않는 이유: Kiki 클론은 여러 세션이 공유하는 단일 작업 사본이라 미커밋 변경이
상시 있을 수 있다. 필요한 것은 "HEAD가 main인가"가 아니라 "이 CLI가 읽는 코드·코퍼스가 main과
같은가"뿐이고, `git diff`가 작업 트리까지 포함해 그것을 직접 판정한다.

### [C] 환경 + 이번 PR 착지 확인 + 도달성

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
git log --oneline -1
$PopulateSrc = "src/backend/whymath_backend/l1/curriculum/populate.py"
$HasAtomGraphFlag = ((Get-Content $PopulateSrc -Raw -Encoding UTF8) -match "--atom-graph")
"HAS_ATOM_GRAPH_FLAG=$HasAtomGraphFlag"
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**확인**: `PY_OK=True` · **`HAS_ATOM_GRAPH_FLAG=True`** · `REACH_EXIT=0`.

`HAS_ATOM_GRAPH_FLAG=False`면 S4-64가 이 체크아웃에 아직 없다는 뜻이다. 그 상태로 D를 돌리면
CLI가 대학 셀을 건드리지 않고 조용히 끝난다 — **여기서 멈추고 알린다.**

### [D] 적재 (여기서만 DB에 쓴다)

이 블록은 **[B]·[C]의 판정값을 스스로 재검사하고, 미충족이면 실행을 거부한다.** 눈으로 확인하라는
안내에 기대지 않는다 — 출력은 흐름을 멈추지 못하기 때문이다(`HARN-106`).

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$PathsOk = $PathsMatchMain -eq $true
$FlagOk = $HasAtomGraphFlag -eq $true
$TableOk = ($TableExists -eq "t")
$FrameworkOk = ($FrameworkExists -eq "1")
"PATHS_OK=$PathsOk · FLAG_OK=$FlagOk · TABLE_OK=$TableOk · FRAMEWORK_OK=$FrameworkOk"
if ($PathsOk -and $FlagOk -and $TableOk -and $FrameworkOk) { & $Py -m whymath_backend.l1.curriculum.populate; "POPULATE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — PATHS_OK=$PathsOk FLAG_OK=$FlagOk TABLE_OK=$TableOk FRAMEWORK_OK=$FrameworkOk · 넷 다 True여야 적재합니다. [B]·[C]를 같은 창에서 먼저 돌리고 그 값을 확인하세요." }
```

**확인**: `POPULATE_EXIT=0`, 그리고 stdout `교육과정 Overlay(KR) 적재 완료: N건 (canonical … + 원자 … + 대학 512건 …)`
줄. 그 줄을 통째로 복사해 전달한다. 기대 `N=2260`.

실행 중 `RuntimeWarning: 'whymath_backend.l1.curriculum.populate' found in sys.modules …` 경고가 한 줄 뜨는 것은
**정상**이다(패키지 `__init__`이 모듈을 먼저 임포트해서 나는 기존 경고이며 적재와 무관 — 로컬 실행에서 확인).

`WRITE_REFUSED=True`가 나오면 적재는 **일어나지 않았다** — 무엇이 False였는지 같은 줄에
찍히므로 그 축을 먼저 해소한다. 닫는 중괄호와 **같은 줄**의 `} else {`인 것이 중요하다:
새 줄에서 시작하는 `else`는 대화형 프롬프트에서 별개 명령으로 해석돼 그 가지가 통째로
미실행된다.

### [E] AFTER 카운트

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$AfterUniv = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM curriculum_entry WHERE introduced_grade BETWEEN 13 AND 16;"
"AFTER_UNIV=$AfterUniv"
$AfterTotal = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM curriculum_entry;"
"AFTER_TOTAL=$AfterTotal"
"AFTER_UNIV_DEPTH_DISTRIBUTION (depth|count):"
docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT coalesce(required_depth::text,'NULL'), count(*) FROM curriculum_entry WHERE introduced_grade BETWEEN 13 AND 16 GROUP BY 1 ORDER BY 1;"
"JUDGED_AGAINST_MAIN=" + (git rev-parse --short origin/main)
```

**확인**: `AFTER_UNIV=512` · 분포가 `NULL|44` · `conceptual|360` · `procedural|108` 세 줄이고
`mastery`가 없음. `AFTER_TOTAL`은 `BEFORE_TOTAL`에 신규 행만큼 더한 값이다(BEFORE_UNIV=0이면
`BEFORE_TOTAL + 512`와 같아야 한다 — canonical·원자 행은 이미 있으므로 늘지 않는다).

---

## 7. 게이트 clear 방법

Kiki가 할 일은 위 판정값들을 세션에 전달하는 것까지다. 대장 조작(`backlog.py gates clear`)은
세션이 가져간다 — `--evidence`에 판정 기준 커밋 해시가 들어가야 한다(`HARN-68`).

전달할 값: `DOCKER_OK` · `PATHS_MATCH_MAIN` · `TABLE_EXISTS` · `FRAMEWORK_EXISTS` · `BEFORE_UNIV` · `BEFORE_TOTAL` ·
`HAS_ATOM_GRAPH_FLAG` · `REACH_EXIT` · `POPULATE_EXIT` · CLI의 `교육과정 Overlay(KR) 적재 완료` 줄 ·
`AFTER_UNIV` · `AFTER_TOTAL` · 깊이 분포 3줄 · `JUDGED_AGAINST_MAIN`.

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **이 런북 자체는 prod에서 실행된 적이 없다.** 같은 CLI를 스크래치 PostgreSQL 16(+pgvector)에서 두 번
  실행해 확인한 결과: 적재 전 `BEFORE_UNIV=0`·`BEFORE_TOTAL=0` → 후 `AFTER_UNIV=512`·`AFTER_TOTAL=2260`
  (학년 13/14/15/16 = 175/93/118/126 · 깊이 `conceptual` 360·`procedural` 108·`NULL` 44) → 2회차도
  2,260 그대로(멱등). 단 그 DB는 마이그레이션이 아니라 ORM 메타데이터로 만든 `curriculum_entry`
  한 테이블이었고 `KR_NC_2022` 행은 수동 시드했다 — prod 스키마와의 동치는 CI `backend-migrations`
  잡이 마이그레이션 경로로 도는 통합 테스트가 따로 본다. prod 수치는 Kiki 실행 전까지 **미측정**이다.

- **L6 깊이정렬이 대학 원자에서 실제로 좋아지는지는 이 실행으로 증명되지 않는다.** 셀이 들어가면
  신호가 *도달*할 뿐이다. 랭킹 보너스가 대학 문항 선택에 미치는 효과는 별도 측정이다.
- **`required_depth`는 임시 휴리스틱이다.** `cognitive_type`(개념/절차/표상)에서 도출한 값이며
  인지 수준 원문 주석이 아니다. 라벨 출처는 원자 백본 provenance상 "와이매스 자체작성"이고 라벨
  단위 검수 기록은 확인되지 않았다(미확인). 표상 44건은 깊이 칸이 없어 `NULL`로 들어간다.
- **canonical·원자 셀도 같은 CLI가 재적재한다**(위 부수 효과 고지). 코퍼스가 마지막 적재 이후
  바뀌었다면 그 변화도 함께 반영된다.
