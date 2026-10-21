# G-skb03-atom-node-populate — `atom_node` 메타 프로젝션 적재 (Kiki 실행 런북)

> 게이트 **`G-skb03-atom-node-populate`**(kiki·2026-09-14 등재)의 실행 절차다.
>
> **선행 조건**: SKB-03 PR이 main에 병합돼야 한다. 이 런북이 쓰는 `--skip-atom-node` 플래그와
> 여섯 번째 적재 스텝은 그 PR이 신설한 것이라, 병합 전에는 CLI가 `atom_node`를 건드리지 않는다
> (그 상태로 실행하면 조용히 아무 일도 일어나지 않는다 — [2단계] 자가검증이 그것을 잡는다).
>
> **이 런북은 `docs/ops/g_skb01_concept_behavior_skills_populate_runbook.md` §9의 교훈을
> 처음부터 적용했다** — 그 게이트는 4회 왕복을 썼고 그중 3회가 런북 자신의 결함이었다. 그래서
> 여기에는 ①최상위 `elseif`/`else` 분기가 없고 ②건너뛰는 가드가 없으며 ③블록 사이의 판정을
> 사람이 눈으로 한다. 각 블록 끝의 판정값을 확인한 **다음에만** 그 아래 블록을 붙여넣으면 된다.

---

## 1. 과제 명칭

`atom_node` 메타 프로젝션 적재 — 원자 백본 코퍼스의 안전 메타(인지축·노드유형·학교급·전이·
원자성 등)를 `atom_node` 테이블에 2,683행 멱등 적재한다.

## 2. 목적

`atom_node_projection.py`는 멱등 upsert 구현을 갖고도 **어느 CLI에서도 호출되지 않아 prod에
한 번도 적재된 적이 없었다.** 이 저장소의 관례는 `<디렉터리>/populate.py`가 형제
`*_node_projection.py`를 부르는 것인데(`skill_graph`·`problem_type_graph`·`concept_content`
전부 그렇다) `atom_graph`만 그 연결이 빠져 있었다.

그 결과 L2 약개념 추천(`weak_concept_recommendation`)의 메타 enrich가 **조용히 0건**이었다 —
`atom_node`에 없는 code는 "메타 누락"이 아니라 "원자 축 밖"(`off_atom_axis`)으로 계상되므로,
빈 테이블이 정상 동작처럼 보였다. SKB-03이 CLI를 배선했고, 이 런북이 그것을 prod에서 1회 실행한다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | Docker Desktop 기동 + prod DB 도달 확인 | `DOCKER_OK=True` | ~10초 (꺼져 있으면 최대 3분) |
| B | 실행 입력이 main과 같은지 판정 + BEFORE 카운트 | `PATHS_MATCH_MAIN=True` · `BEFORE_TOTAL=0` | ~20초 |
| C | 환경 주입 + 이번 PR 착지 확인 + 도달성 | `HAS_SKIP_FLAG=True` · `REACH_EXIT=0` | ~15초 |
| D | **적재** (여기서만 DB에 쓴다) | `POPULATE_EXIT=0` | ~1~3분 |
| E | AFTER 카운트 + 정합성 대조 | `AFTER_TOTAL=2683` | ~5초 |

**부수 효과 고지(중요)**: 이 CLI의 본업은 `concept`·`concept_edge` 적재이고 `atom_node`는
여섯 번째 스텝으로 얹혔다. 따라서 D단계는 **concept·concept_edge·시각화 Overlay 2종도 함께
멱등 재적재한다.** 전부 upsert라 신규 행을 만들지 않고 기존 값을 같은 코퍼스로 덮어쓸 뿐이지만,
"atom_node만 건드린다"고 오해하지 않도록 명시한다.

## 4. 성공 기준

`BEFORE_TOTAL=0` → `POPULATE_EXIT=0` → `AFTER_TOTAL=2683`이면 성공이다.

2,683은 코퍼스에서 직접 센 값이다(2026-09-14 실측: 세부개념 1,823 + 단원 217 + 소단원 643,
`name`/`level` 결손으로 skip될 노드 0건). CLI가 stdout에 찍는 `atom_nodes=N`의 N과
`AFTER_TOTAL`이 **같아야 한다** — 두 값은 서로 다른 경로(적재기 반환값 vs DB 카운트)에서 나오므로
한쪽만 맞는 상태를 가른다.

`BEFORE_TOTAL`이 0이 아니면 그 값을 그대로 전달한다 — 이 게이트는 "테이블이 전량 비었는지
1,311개 code만 없는지"를 아직 실측하지 못했고(SKB-03 acceptance ①), BEFORE가 그 답이다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `HAS_SKIP_FLAG=False` | 체크아웃이 SKB-03 병합 커밋에 닿지 않았다 | 멈추고 [C]의 `git log` 줄과 함께 전달 |
| `PATHS_MATCH_MAIN=False` | 실행 입력이 main과 다르다 | 멈추고 [B]의 `git status` 출력 전달 |
| `REACH_EXIT`가 0이 아님 | DB에 못 붙는다 | CLI가 출력하는 사유를 그대로 전달 |
| `POPULATE_EXIT=1` + 순환 오류 | 코퍼스에 순환 선수관계 | 강제 조치 금지 — 화면 전체 전달 |
| `AFTER_TOTAL`이 2683이 아님 | 부분 적재 | 화면 전체 전달(값 자체가 정보다) |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop · `whymath-pg` 컨테이너(호스트 포트 **5433**) · `src\backend\.venv`
- **DB**: prod = docker `whymath-pg`(5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없다.

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에만
> 아래 블록으로 넘어간다.

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

### [B] 실행 입력 동등성 판정 + BEFORE 카운트

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
git fetch origin main
"MAIN_SHA=" + (git rev-parse --short origin/main)
"HEAD_SHA=" + (git rev-parse --short HEAD)
"----- 미커밋 변경(추적 파일) -----"
git status --porcelain --untracked-files=no
"----- 실행 입력이 main과 동일한가 -----"
git diff --quiet origin/main -- "src/backend/whymath_backend/l1/atom_graph" "data/corpus/atom_graph_v1/graph.json"
$PathsMatchMain = ($LASTEXITCODE -eq 0)
"PATHS_MATCH_MAIN=$PathsMatchMain"
"----- BEFORE (읽기 전용) -----"
$Before = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM atom_node;"
"BEFORE_TOTAL=$Before"
```

**확인**: `PATHS_MATCH_MAIN=True`. `BEFORE_TOTAL` 값은 0이든 아니든 그대로 기록해 전달한다
(이 값이 acceptance ①의 답이다).

판정값을 **화면에 찍기만 하지 않고 변수에 담는 이유**: [D]의 자가거부 가드가 그 변수를
재검사한다. 출력만 하면 가드가 참조할 것이 없어 장식이 된다(HARN-106 — 출력은 흐름을
멈추지 않는다). 같은 창에서 [B]→[C]→[D] 순서로 붙여넣어야 변수가 살아 있다.

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
$PopulateSrc = "src/backend/whymath_backend/l1/atom_graph/populate.py"
$HasSkipFlag = ((Get-Content $PopulateSrc -Raw) -match "skip-atom-node")
"HAS_SKIP_FLAG=$HasSkipFlag"
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**확인**: `PY_OK=True` · **`HAS_SKIP_FLAG=True`** · `REACH_EXIT=0`.

`HAS_SKIP_FLAG=False`면 SKB-03이 이 체크아웃에 아직 없다는 뜻이다. 그 상태로 D를 돌리면
CLI가 `atom_node`를 건드리지 않고 조용히 끝난다 — **여기서 멈추고 알린다.**

### [D] 적재 (여기서만 DB에 쓴다)

> **정본이 엣지를 지우거나 뒤집었다면 이 블록 대신 §9를 쓴다**(KG-14). 이 적재기는 추가·갱신만
> 하므로 옛 엣지가 DB에 남고, 옛 방향과 새 방향이 순환을 이루면 엣지 적재 전체가 거부된다
> (2026-10-21 실측: KG-09·KG-10·KG-12 정본 → prod 잔존 221건 · 순환 위험 5쌍).

이 블록은 **[B]·[C]의 판정값을 스스로 재검사하고, 미충족이면 실행을 거부한다.** 눈으로
확인하라는 안내에 기대지 않는 이유는 2026-09-15에 그 방식이 실패했기 때문이다 — `[B]`가
`PATHS_MATCH_MAIN=False`를, `[C]`가 `HAS_SKIP_FLAG=False`를 **정확히 출력했는데도** 이
블록이 그대로 붙여넣어져 옛 CLI가 돌고 적재가 0건으로 끝났다. **출력은 흐름을 멈추지
않는다**(HARN-106).

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$PathsOk = $PathsMatchMain -eq $true
$FlagOk = $HasSkipFlag -eq $true
"PATHS_OK=$PathsOk · FLAG_OK=$FlagOk"
if ($PathsOk -and $FlagOk) { & $Py -m whymath_backend.l1.atom_graph.populate; "POPULATE_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True — PATHS_OK=$PathsOk FLAG_OK=$FlagOk · 둘 다 True여야 적재합니다. [B]·[C]를 같은 창에서 먼저 돌리고 그 값을 확인하세요." }
```

**확인**: `POPULATE_EXIT=0`, 그리고 stdout `[원자 백본 적재] …` 줄 끝의 `atom_nodes=N(경로)`.
그 줄을 통째로 복사해 전달한다.

`WRITE_REFUSED=True`가 나오면 적재는 **일어나지 않았다** — 무엇이 False였는지 같은 줄에
찍히므로 그 축을 먼저 해소한다. 닫는 중괄호와 **같은 줄**의 `} else {`인 것이 중요하다:
새 줄에서 시작하는 `else`는 대화형 프롬프트에서 별개 명령으로 해석돼 그 가지가 통째로
미실행된다(2026-09-14 실측).

### [E] AFTER 카운트

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$After = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM atom_node;"
"AFTER_TOTAL=$After"
$WithSkills = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM atom_node WHERE behavior_skills <> '{}';"
"AFTER_WITH_SKILLS=$WithSkills"
"----- 정본↔prod 패리티 (읽기 전용 · OPS-139) -----"
& $Py -m whymath_backend.ops.atom_graph_prod_parity
"PARITY_EXIT=$LASTEXITCODE"
"JUDGED_AGAINST_MAIN=" + (git rev-parse --short origin/main)
```

**확인**: `AFTER_TOTAL=2683`, 그리고 `atom_nodes=N`의 N과 일치. **`PARITY_EXIT=0`(`STATUS=MATCH`)**.

`PARITY_EXIT`는 수작업 `count(*)`를 대신하는 판정이다(OPS-139): `atom_node`뿐 아니라 이 적재가 함께
건드린 `concept_edge`·`concept`까지 정본과 같은지 — **총수만이 아니라 `relation_subtype` 분포와
엣지 집합 지문까지** 본다. `1`(DRIFT)·`2`(UNKNOWN)·`3`(정본 입력 오류)이면 적재가 끝났다고 말하지
않는다 — 출력 전체를 전달한다. 종료 코드별 해석과 이 프로브의 한계는
`docs/ops/atom_graph_parity_probe_runbook.md`가 정본이다.

`AFTER_WITH_SKILLS`는 **0이 정상**이다 — `behavior_skills`는 이 CLI가 아니라 크로스워크 이전
(`concept_atom_crosswalk.populate`)이 채운다. 그 이전은 대상 행이 없어 2026-09-14에 0건으로
끝났으므로, 이 적재로 행이 생긴 지금 **한 번 더 돌려야** 채워진다(§8 참조).

---

## 9. 정본이 엣지를 지우거나 뒤집은 뒤의 재적재 — 잔존 엣지 은퇴 (KG-14)

정본 교정(KG-09 순서 역전 교정 · KG-10 경계 반려 · KG-12 체인 수리)은 엣지를 **지우거나 뒤집는다**.
적재기는 추가·갱신만 하므로 옛 행이 prod에 남는다. 옛 방향과 새 방향이 함께 있으면 쓰기 전
순환 검사(`assert_acyclic_with_db`)가 엣지 적재를 거부하고, 정본은 prod에 도달하지 못한다. 이 절은
그 옛 행을 **같은 트랜잭션에서 은퇴시키며** 적재한다. 범위의 정본은
`src/backend/whymath_backend/l1/atom_graph/atom_edge_retire.py` 모듈 설명이다 — 선수 엣지 · 양끝이
원자 정본 코드 · CMS 소유 아님 · 정본에 없는 쌍, 넷을 모두 만족하는 행만 지운다.

**선행 조건**: prod 스키마가 head여야 한다(`concept_edge.cms_edited_at` 열 — 적재기가 쓴다). 2026-10-21에
백업 후 `b4d8e2a6c0f3 → a8c4e1f7b3d9`로 올렸다(덤프 `C:\Users\kiki\whymath_backups\whymath_before_kg14_schema_20261021_224838.dump`).
아래 K2가 head 여부를 다시 확인하고, 아니면 K3가 거부한다.

**공유 작업 사본을 옮기지 않는다**: Kiki 클론은 여러 세션이 쓰는 단일 작업 사본이다. 체크아웃을
바꾸지 않고 main 기준 임시 worktree(`WhyMath_wt_<main 해시>`)에서 돌린다. 끝나면 K5로 지운다.

| 단계 | 무엇 | 쓰기 | 기대 |
|---|---|---|---|
| K1 | main 기준 임시 worktree | 없음 | `WT_OK=True` · `CLONE_HEAD_UNCHANGED=True` |
| K2 | 환경 · 코드 출처 · 스키마 판 · **은퇴 계획(plan)** | 없음 | `CODE_FROM_WORKTREE=True` · `AT_HEAD=True` · `PLAN_EXIT=0` · `RETIRE_PLAN_OK=True` |
| K3 | **은퇴 + 적재(apply)** | 있음 | `APPLY_EXIT=0` · `[원자 백본 적재]` 줄의 `retired=`가 K2의 `RETIRE_STALE_FOUND`와 같다 |
| K4 | 패리티 · atom_node 되읽기 | 없음 | `PARITY_EXIT=0`(`STATUS=MATCH`) |
| K5 | 임시 worktree 정리 | 저장소 밖 폴더만 | `WT_REMOVED=True` |

K2의 `RETIRE_STALE_FOUND`와 지울 목록을 **눈으로 본 다음에만** K3를 붙여넣는다. K3는 K2가 남긴 변수를
스스로 다시 검사해 하나라도 어긋나면 아무것도 쓰지 않는다(HARN-106 — 출력은 흐름을 멈추지 않는다).
`PLAN_EXIT=1`은 "은퇴해도 순환이 남는다"는 뜻이다(대개 CMS 소유 엣지가 원인) — 그때는 K3로 가지 않고
출력 전체를 세션에 전달한다.

### K1 — main 기준 임시 worktree (쓰기 없음)

```powershell
# [Windows PowerShell · Phaiakes9] 새 창 · K1 main 기준 임시 worktree
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
$CloneHead = (git rev-parse --short HEAD)
$MainSha = (git rev-parse --short origin/main)
$Wt = "C:\Users\kiki\Desktop\__AI\WhyMath_wt_$MainSha"
if (Test-Path $Wt) { "WT_EXISTS=True · 이미 있는 폴더를 재사용합니다" } else { git worktree add --detach $Wt origin/main }
$WtHead = (git -C $Wt rev-parse --short HEAD)
git -C $Wt diff --quiet origin/main -- "src/backend/whymath_backend" "data/corpus"
$WtClean = ($LASTEXITCODE -eq 0)
$WtOk = ($WtHead -eq $MainSha) -and $WtClean
"MAIN_SHA=$MainSha · WT_HEAD=$WtHead · WT_CLEAN=$WtClean · WT_OK=$WtOk"
"CLONE_HEAD_UNCHANGED=" + ((git rev-parse --short HEAD) -eq $CloneHead)
```

### K2 — 환경 · 코드 출처 · 스키마 판 · 은퇴 계획 (쓰기 없음)

`plan`은 DB를 읽기 전용 트랜잭션(`SET TRANSACTION READ ONLY`)에서 SELECT 한 번만 읽는다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · K2 은퇴 계획 (읽기 전용)
cd $Wt
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONPATH = "$Wt\src\backend"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$Py = "C:\Users\kiki\Desktop\__AI\WhyMath\src\backend\.venv\Scripts\python.exe"
$CodeFrom = (& $Py -c "import whymath_backend.l1.atom_graph.atom_edge_retire as m; print(m.__file__)")
$CodeOk = [bool]$Wt -and ($CodeFrom -like "$Wt\*")
"CODE_FROM=$CodeFrom"
"CODE_FROM_WORKTREE=$CodeOk"
$DbRev = (docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT version_num FROM alembic_version;")
cd "$Wt\src\backend"
$HeadOut = (& $Py -m alembic heads 2>&1) -join " "
cd $Wt
$AtHead = [bool]$DbRev -and ($HeadOut -match [regex]::Escape($DbRev))
"DB_REVISION=$DbRev · CODE_HEADS=$HeadOut · AT_HEAD=$AtHead"
$PlanExit = -1
$PlanStale = $null
if ($WtOk -and $CodeOk) { $PlanOut = (& $Py -m whymath_backend.l1.atom_graph.populate --retire-stale-edges plan); $PlanExit = $LASTEXITCODE; $PlanOut; $PlanStale = ($PlanOut | Select-String -Pattern '^RETIRE_STALE_FOUND=(\d+)' | ForEach-Object { $_.Matches[0].Groups[1].Value }) } else { "PLAN_REFUSED=True · WT_OK=$WtOk CODE_FROM_WORKTREE=$CodeOk · K1을 같은 창에서 먼저 실행하세요" }
"PLAN_EXIT=$PlanExit · PLAN_STALE=$PlanStale"
```

### K3 — 은퇴 + 적재 (여기서만 DB에 쓴다)

엣지 은퇴와 엣지 upsert는 **한 트랜잭션**이다 — 순환 검사나 삭제 건수 대조가 실패하면 은퇴도 함께
롤백된다. 개념·Overlay·`atom_node` 적재는 종전처럼 각자의 트랜잭션이다(멱등 upsert).

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · K3 은퇴 + 적재 (쓰기 · 조건 미충족이면 스스로 거부)
cd $Wt
$PlanOk = ($PlanExit -eq 0) -and ($null -ne $PlanStale)
"WT_OK=$WtOk · CODE_FROM_WORKTREE=$CodeOk · AT_HEAD=$AtHead · PLAN_OK=$PlanOk · PLAN_STALE=$PlanStale"
if ($WtOk -and $CodeOk -and $AtHead -and $PlanOk) { & $Py -m whymath_backend.l1.atom_graph.populate --retire-stale-edges apply; "APPLY_EXIT=$LASTEXITCODE" } else { "WRITE_REFUSED=True · WT_OK=$WtOk CODE_FROM_WORKTREE=$CodeOk AT_HEAD=$AtHead PLAN_OK=$PlanOk · 넷 다 True여야 적재합니다. K1·K2를 같은 창에서 먼저 실행하세요" }
```

**확인**: `APPLY_EXIT=0`, 그리고 `[원자 백본 적재] …` 줄 끝의 `retire=apply stale=N retired=N cms_kept=M`에서
`retired`가 K2의 `PLAN_STALE`과 같다. `APPLY_EXIT=1`이면 엣지 쓰기는 일어나지 않았다(롤백) — 출력
전체를 전달한다.

### K4 — 패리티 · atom_node 되읽기 (쓰기 없음)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · K4 되읽기 (읽기 전용)
cd $Wt
& $Py -m whymath_backend.ops.atom_graph_prod_parity
"PARITY_EXIT=$LASTEXITCODE"
$AfterNodes = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM atom_node;"
"AFTER_ATOM_NODES=$AfterNodes"
"JUDGED_AGAINST_MAIN=$MainSha"
```

**확인**: `STATUS=MATCH` · `PARITY_EXIT=0` · `AFTER_ATOM_NODES=2683`.

### K5 — 임시 worktree 정리 (저장소 밖 폴더만 지운다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 · K5 임시 worktree 정리
cd C:\Users\kiki\Desktop\__AI\WhyMath
$WtIsTemp = [bool]$Wt -and ($Wt -like "C:\Users\kiki\Desktop\__AI\WhyMath_wt_*")
if ($WtIsTemp) { git worktree remove --force $Wt; "WT_REMOVED=" + (-not (Test-Path $Wt)) } else { "REMOVE_REFUSED=True · WT=$Wt 은 임시 worktree 경로가 아닙니다" }
git worktree prune
"CLONE_HEAD=" + (git rev-parse --short HEAD)
```

## 7. 게이트 clear 방법

Kiki가 할 일은 위 판정값들을 세션에 전달하는 것까지다. 대장 조작(`backlog.py gates clear`)은
세션이 가져간다 — `--evidence`에 판정 기준 커밋 해시가 들어가야 한다(HARN-68).

전달할 값: `DOCKER_OK` · `PATHS_MATCH_MAIN` · `BEFORE_TOTAL` · `HAS_SKIP_FLAG` ·
`REACH_EXIT` · `POPULATE_EXIT` · CLI의 `[원자 백본 적재]` 줄 · `AFTER_TOTAL` ·
`AFTER_WITH_SKILLS` · 패리티 프로브 출력 전체와 `PARITY_EXIT` · `JUDGED_AGAINST_MAIN`.

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **L2 enrich가 실제로 살아나는지는 이 실행으로 증명되지 않는다.** `atom_node`가 채워지면
  `off_atom_axis` 계수가 줄어들 것이 기대되지만, 그것은 학습자 진단 데이터가 있는 요청을 실제로
  호출해 봐야 안다 — 별도 측정이다.
- **`behavior_skills` 재전파가 남는다.** 2026-09-14 크로스워크 이전이 "atom_node 대상 행 부재
  1311건"으로 끝났으므로, 이 적재로 행이 생긴 뒤 `concept_atom_crosswalk.populate`를 한 번 더
  돌려야 `atom_node.behavior_skills`가 채워진다. 그 재실행은 이 게이트 범위 밖이며, 결과에 따라
  후속 게이트로 등재한다.
- **`concept_content` 공백은 별건이다** — `SKB-04`가 소유한다.
- **`review_status`는 전량 `ai_estimated`로 박힌다**(코드 상수). 검수 게이팅
  (`reviewed_only=True`)을 쓰는 경로에서는 적재 후에도 전건 게이팅될 수 있다.
