# G-skb01-resolution-remeasure — 해소율 재측정 2회차 (Kiki 실행 런북)

> 게이트 **`G-skb01-resolution-remeasure`**(kiki·2026-09-14 등재)의 실행 절차다.
> 게이트가 풀리면 `SKB-01-skill-concept-bridge-prod-populate` acceptance ④가 닫히고,
> 그 수치가 `EOS-63-attempt-skill-event-consumption` acceptance ②의 전환 판정 재료가 된다.
>
> **판정 기준: main `eb048e20`**(최초 검증 `265a4106` · 2026-09-16 회차 이후 재확인) — 아래 명령·
> 경로·인자·기본값은 전부 그 커밋의 코드에서 실측
> 확인했다(`attempt_skill_reach_probe.main()`·`attempt_skill_event_reach_report.main()`의
> argparse 정의 · `probe_to_json()` 키 · `db_host_reachability` 실재 · `concept`/`problem_concept`/
> `skill_node` 테이블·컬럼명).
>
> **재확인(2026-09-16 → `eb048e20`, 10커밋 진행)**: 그 사이 `EOS-13` 숙달 계약 리팩터가 착지해
> `skill_mastery_tracking.py`(+100줄)·`api/me.py`(+410줄)가 바뀌었으나, **해소 쿼리
> `_assessed_skill_ids`는 실질 무변경**이고(여전히 `Concept.behavior_skills` ∩ `skill_node`
> estimable) writer 배선(`skill_records` → `record_attempt_skill_event(skill_ids=...)`)도 그대로다.
> 프로브·리포트·도달성 CLI 3종은 파일 자체가 무변경. 즉 이 회차의 설계는 그대로 유효하다.

> **1회차(2026-09-10)와의 차이**: 그때는 `RESOLUTION=0.0`이었고 원인이 브리지 데이터 공백이었다.
> 그 공백은 두 게이트가 닫아 해소됐다(`skill_node` 0→27 · `concept.behavior_skills` 0→1,198
> nonempty). 이 회차는 **그 해소가 해소율로 나타나는지**를 잰다.

---

## 1. 과제 명칭

`attempt_event.skill_ids` **해소율 재측정 2회차** — 브리지 데이터를 채운 뒤 concept→skill 해소가
실제로 살아났는지 실측한다.

## 2. 목적

1회차가 답한 것은 "writer 배선은 100% 살아 있고 해소율이 0%"였다. 그 0%의 원인으로 지목된 두
공백은 이후 메워졌다:

| 축 | 1회차(2026-09-10) | 현재 | 닫은 게이트 |
|---|---:|---:|---|
| `skill_node` 행 | 0 | 27 | `G-skb01-bridge-populate`(2026-09-12) |
| `concept.behavior_skills` nonempty | 0 | 1,198 | `G-skb01-concept-behavior-skills-populate`(2026-09-14) |

이 회차는 **그 두 적재가 해소율로 이어지는가**를 잰다. 이어지지 않는다면 사슬의 *다른* 고리가
끊겨 있다는 뜻이고, 이 런북은 그 고리를 같은 회차에서 지목하도록 설계돼 있다(§4-3).

### 세션이 이 회차 전에 실측한 것 (가정 제거)

해소 쿼리는 `l2/skill_mastery_tracking.py`의 `_assessed_skill_ids`이며 실제 조인은
**`Concept.behavior_skills` ∩ `skill_node`(`mastery_estimable=True`)** 다. 그래서 세 가지를 미리
확인했다:

1. **`atom_node`·`concept_content`는 이 경로에 없다.** 게이트 등재 시점 고지("두 테이블이 해소
   경로에 관여하면 이번 재측정도 0%")는 코드 실측 결과 **해당하지 않는다** — 두 테이블은
   `_assessed_skill_ids`에도 그 호출 사슬에도 등장하지 않는다. 따라서 `G-skb03-behavior-skills-repropagate`가
   pending인 것은 이 회차의 선행 조건이 아니다.
2. **키 공간이 완전히 겹친다.** 저장소 코퍼스로 오프라인 대조한 결과, 크로스워크가 유도하는
   distinct skill_id **27종이 `skill_graph_v1`의 27종과 전건 일치**하고 고아 0건이며 전부
   `mastery_estimable=True`다. 즉 "채웠는데 이름이 안 맞아 0%"는 배제된다.
3. **남은 미지수는 문항↔개념 링크 하나다.** 해소 사슬은 `problem → problem_concept(PRIMARY/TESTED)
   → concept.behavior_skills → skill_node`인데, 첫 고리만 prod 사실이라 저장소에서 판정할 수
   없다. §4-3의 진단이 그것을 잰다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | **Docker Desktop 기동 + prod DB 도달 확인** | `DOCKER_OK=True` | ~10초 (꺼져 있으면 최대 3분) |
| B | 임시 worktree를 main에 detach로 만든다(공유 클론 무변경) | `WT_IS_MAIN_TIP=True` · `PROBE_FILE_OK=True` | ~30초 |
| C | 환경 주입 + 도달성 + **사슬 진단**(읽기 전용·쓰기 0) | `REACH_EXIT=0` + 진단 7행 | ~30초 |
| D | 표본 20건 제출 + 사후 측정 + 증적 (**여기서만 DB에 쓴다**) | 증적 8줄 | 1~3분 |
| E | worktree 정리 + 원래 자리 복귀 | `WT_REMOVED=True` | ~10초 |

**[B]가 worktree를 쓰는 이유**: Kiki 클론은 여러 세션이 공유하는 단일 작업 사본이라 타 세션의
브랜치·미커밋 변경이 상시 존재한다. 2026-09-14·09-15 두 회차가 연달아 그것에 걸렸고, 09-15에는
정지 신호가 켜졌는데도 옛 CLI가 돌아 적재가 0건으로 끝났다. worktree는 원 작업 사본의 브랜치도
미커밋 변경도 **건드리지 않으면서** main 코드를 돌린다(CLAUDE.md 2026-09-15 등재 기법 ⓑ).

**쓰기가 남는다(의도)**: [D]는 prod DB에 채점 20건을 남긴다 — 남지 않으면 잴 것이 없다. 전부
프로브 전용 고정 사용자 `c5de83b3-9143-58e8-a7a8-cf378801c065` 소유라 정리가 user_id 하나로
끝난다(§6).

## 4. 성공 기준

### 4-1. 회차 성립

`===== 증적 =====` 아래 8줄이 출력되고 `EVENTS`가 1 이상이면 이 게이트가 요구한 실측은 성립한다.
**해소율이 몇이든 성립이다** — 닫히지 않는 것은 *측정이 안 된 경우*뿐이다.

### 4-2. 해소율 읽기

| 관측 | 뜻 | SKB-01·EOS-63에 주는 판정 |
|---|---|---|
| `RESOLUTION` > 0 | concept→skill 브리지가 산다 | SKB-01 acceptance ④ 충족 · EOS-63 **전환 가능** |
| `RESOLUTION` = 0 | 브리지 적재가 해소로 이어지지 않는다 | §4-3 진단이 원인을 지목한다 — 실패가 아니라 다음 원인의 실측 |

### 4-3. `RESOLUTION=0`일 때 어느 고리가 끊겼는가 (이 회차의 핵심 설계)

1회차는 0%를 얻고도 원인 확인에 **별도 쿼리 왕복**이 필요했다. 이번엔 [C]의 진단과 [D]의
`CONCEPT_UPDATED_ATTEMPTS`가 같은 회차 안에서 고리를 가른다:

| 진단 값 | 뜻 | 다음 행동 |
|---|---|---|
| `B_problem_concept_rows` = 0 | **문항↔개념 링크가 통째로 없다** | `problem_bank.populate` 재실행이 필요(§7 배경) — 새 태스크 |
| `D_candidates_resolvable` = 0 이고 `B` > 0 | 링크는 있는데 **닿는 개념의 skills가 비었다** | 링크가 구 437 행을 가리키는지 확인 — 새 태스크 |
| `D_candidates_resolvable` > 0 인데 `RESOLUTION` = 0 | **병리** — 데이터는 맞는데 런타임 해소가 0 | 조사 태스크(코드 축) |
| `CONCEPT_UPDATED_ATTEMPTS` = 0 | 개념 숙달도 0건 — 첫 고리에서 끊김 | 위 1행과 같은 결론(교차 확인) |

**이 진단은 실행 검증됐다(2026-09-16·세션)**: PostgreSQL 16.13 임시 인스턴스에 같은 컬럼·타입으로
최소 스키마를 세우고 **런북에서 SQL을 그대로 추출해** 돌린 뒤, 상태를 주입해 변별력을 확인했다 —
개념 skills 전건 채움에서 `D`가 1→2, 전건 비움에서 `D`·`E`가 0, 링크 전멸에서 `B`·`C`·`D`가 0이되
`E`는 1로 남았다. 즉 위 표의 2행("링크가 없다")과 3행("링크는 있는데 skills가 비었다")은 **실제로
서로 다른 값 패턴을 낸다**. 범위 고지: 검증한 것은 *쿼리가 도는가와 무엇을 가르는가*이며, prod의
실제 행 수는 [C]가 처음 잰다.

`G_concept_with_source_id`는 위 2행의 가설을 가르는 보조 값이다 — 원자 백본 적재기
(`atom_backend_concept.py`)는 `source_id`를 채우지 않으므로(grep 0건 실측), 이 값이 0이면
구 437 잔재가 `concept` 테이블에 없다는 뜻이다.

### 4-4. 실패 — 프로브 exit code별 대처

| exit | 뜻 | 대처 |
|---:|---|---|
| 2 | DB 미도달 | [C]의 `REACH_EXIT`가 먼저 잡는다 — [D]는 그 상태에서 **스스로 거부**한다 |
| 3 | 스키마 뒤처짐(`attempt_event.skill_ids` 부재) | §7-1 마이그레이션 1회 후 [D] 재실행 |
| 4 | 후보 문제 0건 | 1회차에 1,704건이 적재됐으므로 정상이면 나오지 않는다 — 나오면 세션에 전달 |
| 5 | 제출 전건 실패 | 「실패 사유」 표의 예외 타입명이 가른다. `UndefinedColumnError`면 **스키마 드리프트**이므로 §7-1로 간다(exit 3은 `attempt_event.skill_ids` 한 컬럼만 보므로 다른 컬럼의 드리프트는 여기로 온다 — 2026-09-18 실측). 그 외 타입명은 그대로 세션에 전달 |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath` — [B]가 임시 worktree로 옮긴다
- **선행 조건**: Docker Desktop 실행 중 · `whymath-pg` 컨테이너(호스트 포트 **5433**) 가동 ·
  `src\backend\.venv` 세팅 완료
- **DB**: prod DB = docker `whymath-pg` (5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유 창이 없다.
새 창을 열고 [A]→[B]→[C]→[D]→[E]를 **하나씩** 붙여넣는다.

> **[C]와 [D] 사이에서 한 번 멈춘다.** [C]의 `REACH_EXIT`와 진단 7행을 눈으로 본 뒤 [D]로 간다.
> 보지 않고 넘어가도 [D]가 스스로 거부하므로 DB는 안전하지만, 거부 사유를 읽으려면 [C]의 출력이
> 화면에 있어야 한다.

---

## 실행 블록

> 자리표시자가 하나도 없다. 각 블록을 **통째로** 붙여넣으면 된다.

### [A] Docker Desktop 기동 + prod DB 도달 확인

> **이 블록이 이 런북의 1회차 결함이다.** 2026-09-16 회차가 Docker 미가동으로 공전했다 —
> §5가 "선행 조건: Docker Desktop 실행 중"이라고 *적기만* 하고 블록이 그것을 **확인하지
> 않았다**. 산문에 적힌 선행 조건은 집행이 아니다. 형태는 `skb04_concept_content_populate_runbook.md`
> [A]에서 그대로 가져왔다(그 런북은 이 단계 덕에 1회에 성립했다).

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $Repo
"CWD=" + (Get-Location).Path
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

**자가검증**: `DOCKER_OK=True`. `whymath-pg` 줄에 `0.0.0.0:5433->5432/tcp`가 보여야 한다.
- `DOCKER_EXE_FOUND=False`면 두 후보 경로에 Docker Desktop이 없다 — 설치 위치를 세션에 알린다.
- 180초 안에 안 뜨면 `DOCKER_UP_AFTER_SEC`이 찍히지 않는다. 그 경우 Docker Desktop을 직접 띄우고
  트레이 아이콘이 안정될 때까지 기다린 뒤 이 블록을 다시 붙여넣는다(멱등하다).
- `DOCKER_OK=False`인데 컨테이너 줄은 보이면 컨테이너는 살아 있고 psql이 실패한 것이다 —
  화면의 오류 줄을 세션에 전달한다.

### [B] 임시 worktree — main 코드를 공유 클론과 분리해 확보

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $Repo
"CWD=" + (Get-Location).Path
git fetch origin main
git worktree prune
if (Test-Path $WT) { git worktree remove --force $WT; if (Test-Path $WT) { Remove-Item -Recurse -Force $WT } } else { "WT_PREEXISTING=False — 새로 만든다" }
git worktree add --detach $WT origin/main
cd $WT
New-Item -ItemType Directory -Force -Path $Out | Out-Null
git log --oneline -1
"WT_HEAD=" + (git rev-parse --short HEAD) + "  MAIN_TIP=" + (git rev-parse --short origin/main)
"WT_IS_MAIN_TIP=" + ((git rev-parse HEAD) -eq (git rev-parse origin/main))
"PROBE_FILE_OK=" + (Test-Path "$WT\src\backend\whymath_backend\harness\attempt_skill_reach_probe.py")
"PY_OK=" + (Test-Path $Py)
"CWD=" + (Get-Location).Path
```

**자가검증**: `WT_IS_MAIN_TIP=True` · `PROBE_FILE_OK=True` · `PY_OK=True` · `CWD`가 `whymath-wt-remeasure`로
끝난다. 이 블록은 원 클론의 브랜치·미커밋 변경을 **전혀 건드리지 않는다**.
- `PY_OK=False`면 venv 경로가 다르다 — 세션에 알린다(원 클론의 venv를 쓰는 것이 의도다.
  worktree에는 `.venv`가 없다).
- `WT_IS_MAIN_TIP=False`면 fetch가 실패했거나 엉뚱한 커밋을 잡은 것이다 — `WT_HEAD`·`MAIN_TIP` 두
  값을 세션에 전달한다. **특정 해시를 기대값으로 적지 않는 이유**: main은 이 런북과 무관하게
  계속 움직이므로, 고정 해시 기대값은 정상 상태에서 상시 불일치를 내 사람이 검증 스텝 자체를
  무시하게 만든다(2026-09-16 실측 — 이 런북 1회차가 `WT_HEAD=265a4106`을 기대값으로 적었고
  실제로는 정상적으로 `eb048e20`이 나왔다). 비교 대상은 *그때의 origin/main*이지 과거의 한 점이 아니다.
- 첫 줄의 중첩 가드는 *이전 회차가 중간에 죽어 폴더만 남은* 경우를 처리한다 — `worktree remove`가
  등록되지 않은 폴더를 지우지 못하면 `worktree add`가 "폴더가 비어 있지 않다"로 실패하기 때문이다.
  지우는 대상은 두 줄 위에서 이 블록이 직접 정한 전용 경로뿐이다.

### [C] 환경 + 도달성 + 사슬 진단 (읽기 전용 — DB에 아무것도 쓰지 않는다)

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $WT
"CWD=" + (Get-Location).Path
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "$WT\src\backend").Path
"DB_TARGET=$env:WHYMATH_DATABASE_URL"
& $Py -c "import whymath_backend.harness.attempt_skill_reach_probe as m; print('MODULE_FROM=' + m.__file__)"
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
"===== 사슬 진단 (읽기 전용) ====="
docker exec -i whymath-pg psql -U whymath -d whymath -v ON_ERROR_STOP=1 -c "SELECT 'A_problem_candidates' AS k, count(*) AS n FROM problem WHERE difficulty_overall IS NOT NULL UNION ALL SELECT 'B_problem_concept_rows', count(*) FROM problem_concept UNION ALL SELECT 'C_problems_linked', count(DISTINCT problem_id) FROM problem_concept UNION ALL SELECT 'D_candidates_resolvable', count(DISTINCT pc.problem_id) FROM problem_concept pc JOIN concept c ON c.concept_id = pc.concept_id JOIN problem p ON p.problem_id = pc.problem_id WHERE cardinality(c.behavior_skills) > 0 AND pc.role::text IN ('PRIMARY','TESTED') AND p.difficulty_overall IS NOT NULL UNION ALL SELECT 'E_concept_nonempty_skills', count(*) FROM concept WHERE cardinality(behavior_skills) > 0 UNION ALL SELECT 'F_skill_node_estimable', count(*) FROM skill_node WHERE mastery_estimable UNION ALL SELECT 'G_concept_with_source_id', count(*) FROM concept WHERE source_id IS NOT NULL ORDER BY 1;"
"DIAG_EXIT=$LASTEXITCODE"
```

**자가검증**: `MODULE_FROM`이 `whymath-wt-remeasure` 경로로 시작 · `REACH_EXIT=0` · `DIAG_EXIT=0` ·
진단 7행 출력.
- `MODULE_FROM`이 원 클론(`Desktop\__AI\WhyMath\src`) 경로면 **worktree 코드가 아니라 설치된
  패키지가 돌고 있다** — [D]가 거부한다. 그 줄을 세션에 전달한다.
- `REACH_EXIT=1`이면 DB에 못 붙는다(CLI가 상태와 대책을 함께 출력한다). `REACH_EXIT=2`는 고장이
  아니라 **측정 불가**(docker 미가동 등)다 — 화면의 `측정 사유 기록`을 먼저 해소한다.
- 기대값: `E_concept_nonempty_skills=1198` · `F_skill_node_estimable=27`. 이 둘이 다르면 앞선 두
  게이트의 적재가 이후 뒤집혔다는 뜻이므로 **[D]로 가지 말고** 세션에 알린다.

**여기서 한 번 멈춘다.** 위 값들을 눈으로 확인한 뒤 [D]로 간다.

### [D] 표본 20건 + 사후 측정 + 증적 (**여기서만 DB에 쓴다** · 선행 미충족이면 스스로 거부)

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $WT
"CWD=" + (Get-Location).Path
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "$WT\src\backend").Path
"DB_TARGET=$env:WHYMATH_DATABASE_URL"
& $Py -c "import whymath_backend.harness.attempt_skill_reach_probe as m; print(m.__file__)" > "$Out\module_from.txt" 2>&1
$ModuleFrom = ((Get-Content "$Out\module_from.txt" -Raw) + "").Trim()
$ModuleOk = ($ModuleFrom -like "$WT*")
& $Py -m whymath_backend.ops.db_host_reachability
$ReachOk = ($LASTEXITCODE -eq 0)
"MODULE_OK=$ModuleOk  REACH_OK=$ReachOk"
if ($ModuleOk -and $ReachOk) {
  Remove-Item "$Out\probe.json", "$Out\report.json" -ErrorAction SilentlyContinue
  "===== 표본 생성 20건 ====="
  & $Py -m whymath_backend.harness.attempt_skill_reach_probe --count 20 --json "$Out\probe.json"
  "PROBE_EXIT=$LASTEXITCODE"
  $ProbeOk = Test-Path "$Out\probe.json"
  "PROBE_JSON_OK=$ProbeOk"
  if ($ProbeOk) { $P = Get-Content "$Out\probe.json" -Raw | ConvertFrom-Json; $Since = $P.started_at; "SINCE=$Since"; & $Py -m whymath_backend.harness.attempt_skill_event_reach_report --since $Since --json "$Out\report.json"; "REPORT_EXIT=$LASTEXITCODE" } else { "PROBE_JSON_MISSING=True — 표본 생성 실패. 위 PROBE_EXIT 숫자를 §4-4 표와 대조해 전달한다" }
  $ReportOk = Test-Path "$Out\report.json"
  "REPORT_JSON_OK=$ReportOk"
  if ($ReportOk) { $R = Get-Content "$Out\report.json" -Raw | ConvertFrom-Json; $CU = @($P.outcomes | Where-Object { $_.concept_updates -gt 0 }).Count; "===== 증적 ====="; "WINDOW=$($R.since)"; "ATTEMPTS=$($R.attempts_total)  EVENTS=$($R.events_total)"; "EMPTY=$($R.events_empty_skill_ids)  NONEMPTY=$($R.events_nonempty_skill_ids)  NULL=$($R.events_null_skill_ids)"; "WRITER_REACH=$($R.writer_reach_rate)  RESOLUTION=$($R.resolution_rate)  E2E=$($R.end_to_end_rate)"; "PROBE_ACCEPTED=$($P.accepted)  PROBE_FAILED=$($P.failed)"; "CONCEPT_UPDATED_ATTEMPTS=$CU"; "JUDGED_AGAINST_MAIN=" + (git rev-parse --short HEAD); "MODULE_FROM=$ModuleFrom" } else { "REPORT_JSON_MISSING=True — 사후 측정 실패. 화면의 예외 타입명을 세션에 전달한다" }
  "BLOCK_D_COMPLETE=True"
} else { "WRITE_REFUSED=True — 쓰기를 거부했다. MODULE_OK=$ModuleOk(worktree 코드인가) REACH_OK=$ReachOk(DB 도달하는가). DB는 건드리지 않았다. 두 값과 위 화면을 세션에 전달한다." }
```

**성공 판정**: `===== 증적 =====` 아래 **8줄**이 출력되고 `EVENTS`가 1 이상. 그 8줄을 **그대로
복사해 세션에 전달**한다 — 그것이 게이트 증적이다.

**이 블록이 스스로 거부하는 이유**: 2026-09-15 `G-skb03` 회차에서 정지 신호 2개가 정확히 켜졌는데도
적재 블록이 붙여넣어져 옛 CLI가 돌고 적재가 0건으로 끝났다. 출력은 흐름을 멈추지 못하므로, 쓰기
블록이 선행 판정을 **다시 계산해** 거부한다(CLAUDE.md 2026-09-15 등재). `WRITE_REFUSED=True`가
뜨면 DB는 안전하다 — 아무것도 쓰지 않았다.

### [E] 정리 — worktree 제거 + 원래 자리 복귀

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $Repo
"CWD=" + (Get-Location).Path
if (Test-Path $WT) { git worktree remove --force $WT } else { "WT_ALREADY_GONE=True — 제거할 worktree가 없다" }
git worktree prune
"WT_REMOVED=" + (-not (Test-Path $WT))
git status --short --branch
```

**자가검증**: `WT_REMOVED=True`. 산출물(`probe.json`·`report.json`)은 원 클론의
`work\skb01-remeasure\`에 남아 worktree 제거와 무관하게 보존된다(`/work/`는 gitignore 대상).
`git status`가 [B] 이전과 같아야 한다 — 이 회차는 원 클론의 브랜치·미커밋 변경을 건드리지 않았다.

---

## 7. 보조 블록 (필요할 때만)

### 7-1. 프로브가 스키마 뒤처짐으로 실패했을 때 — 현재 리비전 확인 후 마이그레이션

> **2026-09-18 실측으로 드러난 경로다.** 프로브가 `PROBE_EXIT=5`(제출 전건 실패)로 끝나고 실패
> 사유가 `UndefinedColumnError: column "..." of relation "problem_attempt" does not exist`면,
> 라우트·인증 문제가 아니라 **prod DB 스키마가 main보다 뒤처진 것**이다. 프로브의 exit 3 검사는
> `attempt_event.skill_ids` 한 컬럼만 보므로 **다른 컬럼의 드리프트는 exit 5로 나타난다**(§4-4).

**[7-1a] 현재 리비전 조회 (읽기 전용 — DB를 바꾸지 않는다)**

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd "$WT\src\backend"
"CWD=" + (Get-Location).Path
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "$WT\src\backend").Path
"DB_TARGET=$env:WHYMATH_DATABASE_URL"
docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT version_num FROM alembic_version;"
"PROD_REVISION_EXIT=$LASTEXITCODE"
& $Py -m alembic -c alembic.ini current
"ALEMBIC_CURRENT_EXIT=$LASTEXITCODE"
& $Py -m alembic -c alembic.ini heads
"ALEMBIC_HEADS_EXIT=$LASTEXITCODE"
cd $WT
```

출력 3종(prod 리비전 · `current` · `heads`)을 **세션에 전달하고 멈춘다.** 세션이 그 리비전과 head
사이의 마이그레이션을 열거해 파괴적 연산 유무를 판정한 뒤 [7-1b] 실행 여부를 답한다 —
`upgrade head`는 스키마를 바꾸므로 "몇 칸 뒤처졌는지 모르는 채" 돌리지 않는다.

**[7-1b] 마이그레이션 (세션이 [7-1a] 판정을 회신한 뒤에만)**

> **`Read-Host`를 쓰지 않는다(2026-09-18 실측 교훈).** 초판은 사람 승인을 `Read-Host`로 받았는데,
> 두 블록을 연달아 붙여넣으면 **`Read-Host`가 다음 블록의 첫 줄을 입력값으로 삼킨다** — 승인이
> 자동으로 실패하고(`WRITE_REFUSED`), 삼켜진 줄을 잃은 다음 블록이 그대로 이어 실행된다. 즉
> 붙여넣기 흐름에서 `Read-Host`는 사람을 멈추는 대신 **자기 블록을 무력화하고 다음 블록을 손상**시킨다.
> 그래서 이 블록의 가드는 전부 기계가 계산한다 — 도달성·ini 실재·목적지 URL·`BEHIND`(현재 리비전이
> head와 다른가). 멱등하므로 이미 head면 스스로 거부한다.
>
> (CLAUDE.md 「붙여넣기 블록의 자리표시자 전면 금지」가 `Read-Host`를 정지 수단으로 권하지만,
> 그것은 **블록이 하나일 때** 성립한다. 뒤에 다른 블록이 붙는 순간 성질이 바뀐다.)

`alembic.ini`와 `versions/`를 **worktree**(main tip)에서 읽는다 — 공유 클론은 타 세션 브랜치에
있을 수 있어 그쪽 `versions/`를 쓰면 *어느 트리의 마이그레이션인지 모르는 채* 스키마가 바뀐다.

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$WT   = "C:\Users\kiki\Desktop\__AI\whymath-wt-remeasure"
$Py   = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd "$WT\src\backend"
"CWD=" + (Get-Location).Path
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "$WT\src\backend").Path
"DB_TARGET=$env:WHYMATH_DATABASE_URL"
& $Py -m whymath_backend.ops.db_host_reachability
$ReachOk = ($LASTEXITCODE -eq 0)
$IniOk = Test-Path "$WT\src\backend\alembic.ini"
$UrlOk = ($env:WHYMATH_DATABASE_URL -like "*:5433/whymath*")
$Before = ((docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT version_num FROM alembic_version;") + "").Trim()
$HeadLine = (& $Py -m alembic -c alembic.ini heads | Where-Object { $_ -match '^[0-9a-f]{8,}' } | Select-Object -First 1)
$Head = (($HeadLine + "") -split '\s+')[0]
$Behind = ($Before -ne $Head)
"BEFORE_REVISION=$Before  HEAD=$Head  BEHIND=$Behind"
"REACH_OK=$ReachOk  INI_OK=$IniOk  URL_OK=$UrlOk"
if ($ReachOk -and $IniOk -and $UrlOk -and $Behind) { & $Py -m alembic -c alembic.ini upgrade head; "ALEMBIC_EXIT=$LASTEXITCODE"; $After = ((docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT version_num FROM alembic_version;") + "").Trim(); "AFTER_REVISION=$After"; "AT_HEAD=" + ($After -eq $Head) } else { "WRITE_REFUSED=True — 마이그레이션을 돌리지 않았다. REACH_OK=$ReachOk INI_OK=$IniOk URL_OK=$UrlOk(5433 prod를 겨냥하는가) BEHIND=$Behind(뒤처져 있는가 — False면 이미 head이므로 할 일이 없다). 스키마는 그대로다." }
cd $WT
```

`ALEMBIC_EXIT=0`과 `current`가 head로 바뀐 것을 확인한 뒤 **[D]를 다시 붙여넣는다**(프로브는
이미 시도한 문항을 제외하므로 새 표본 20건이 뽑힌다).

### 7-2. 표본 정리 (선택 — **증적을 세션에 전달한 뒤에만**)

> ⚠ 이 블록은 측정한 표본을 지운다. 증적 8줄을 전달하기 *전에* 돌리면 재측정해야 한다.
> ⚠ **이 블록만 단독으로 붙여넣는다** — `Read-Host`가 있어서, 뒤에 다른 블록을 이어 붙이면
>    그 블록의 첫 줄이 입력값으로 삼켜진다(2026-09-18 실측).
> 지우지 않아도 무해하다 — 프로브 사용자 한 명의 행일 뿐이다.

```powershell
# [Windows PowerShell · Phaiakes9] — 이 블록은 자기완결형이다(앞 블록의 변수·현재 위치에 의존하지 않는다)
$Repo = "C:\Users\kiki\Desktop\__AI\WhyMath"
$Out  = "C:\Users\kiki\Desktop\__AI\WhyMath\work\skb01-remeasure"
cd $Repo
"CWD=" + (Get-Location).Path
$ReportExists = Test-Path "$Out\report.json"
"REPORT_EXISTS=$ReportExists"
$Confirm = Read-Host "증적 8줄을 이미 세션에 전달했습니까? 표본을 지우려면 DELETE 를 입력하세요"
$EvidenceSent = ($Confirm -ceq "DELETE")
"EVIDENCE_SENT=$EvidenceSent"
if ($EvidenceSent -and $ReportExists) { docker exec -i whymath-pg psql -U whymath -d whymath -v ON_ERROR_STOP=1 -c "DELETE FROM attempt_event WHERE user_id='c5de83b3-9143-58e8-a7a8-cf378801c065'; DELETE FROM skill_mastery_history WHERE user_id='c5de83b3-9143-58e8-a7a8-cf378801c065'; DELETE FROM concept_mastery_history WHERE user_id='c5de83b3-9143-58e8-a7a8-cf378801c065'; DELETE FROM problem_attempt WHERE user_id='c5de83b3-9143-58e8-a7a8-cf378801c065'; DELETE FROM user_profile WHERE user_id='c5de83b3-9143-58e8-a7a8-cf378801c065';"; "CLEANUP_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — 표본을 지우지 않았다. EVIDENCE_SENT=$EvidenceSent REPORT_EXISTS=$ReportExists. 증적을 먼저 전달하고, 지울 때 DELETE 를 정확히 입력한다." }
```

---

## 8. 배경 — `problem_concept` 링크가 왜 미지수인가

`problem_bank.populate`의 **§원자 재연결**(코퍼스 `concept_src_id` → `primary_atom_code` → 원자 행
`concept_id`)은 **2026-09-11**에 착지했다(`2d1f76c8`). prod의 문항은 그보다 **하루 전
2026-09-10**에 시드됐으므로, 현재 `problem_concept` 행은 구 체인
(`{concept.source_id: concept_id}` 맵)으로 쓰였다.

구 체인은 `source_id`를 가진 행에만 닿는데, 런타임 `concept` 테이블(2,683행)은 원자 백본이고
그 적재기 `atom_backend_concept.py`는 `source_id`를 **채우지 않는다**(grep 0건 실측). 그래서
"구 체인이 아무것도 해소하지 못해 `problem_concept`이 비어 있을" 가능성이 있다 — 다만 그 테이블의
실제 행 수는 **prod 사실이라 저장소에서 판정할 수 없다**. 소스를 읽어 그렇게 보인다는 범위까지가
세션이 말할 수 있는 전부이며, [C]의 진단이 그것을 잰다.

해소 경로(`problem_bank.populate` 재실행 + reconcile로 구 437 잔재 자동 청소)는 코드에 이미
있으나(populate.py §76), 그 실행은 이 게이트의 범위가 아니다 — [C]가 `B_problem_concept_rows=0`을
내면 별도 태스크로 등재한다.

## 9. 이 회차가 답하지 못하는 것 (정직 고지)

- **유기적 트래픽의 도달률이 아니다.** 표본을 프로브가 만들었으므로 배선이 살아 있으면
  `WRITER_REACH`는 100%다. 그것이 증명하는 것은 "`attempt_submit` 경로의 writer가 이 DB에서
  작동한다"까지이고 "학생들이 쓰고 있다"가 아니다.
- **`coach_completion` 경로는 미측정이다.** 리포트의 그 행이 0인 것은 죽었다는 뜻이 아니라 이
  회차가 태우지 않았다는 뜻이다.
- **해소율은 이 DB의 브리지 데이터에 대한 값이다.** 코퍼스가 바뀌면 값도 바뀐다 — 그래서 증적에
  판정 기준 커밋(`JUDGED_AGAINST_MAIN`)과 창(`WINDOW`)을 함께 남긴다.
- **`RESOLUTION` > 0이어도 그 값이 "충분한가"는 이 회차가 답하지 않는다.** EOS-63 전환의 판정
  기준선은 그 태스크가 소유한다.

## 10. 게이트 clear 방법

**Kiki가 할 일은 §[D]의 증적 8줄(+ [C]의 진단 7행)을 세션에 전달하는 것까지다.** 대장 조작
(`backlog.py gates clear`)은 세션이 가져간다 — 증적 문자열이 자리표시자를 포함할 수밖에 없어
그대로 실행되면 잘못된 증적이 대장에 박히기 때문이다.

세션 쪽 참고: `--evidence`에는 판정 기준(커밋 해시 또는 PR 참조)이 반드시 들어가야 한다
(HARN-68 — 없으면 CLI가 exit 1로 거부한다). 증적 본문은 [C] 진단 7행 + [D] 증적 8줄로 구성한다.
