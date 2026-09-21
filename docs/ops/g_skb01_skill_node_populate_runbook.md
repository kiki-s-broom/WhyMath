# G-skb01-bridge-populate — `skill_node` 최초 적재 (Kiki 실행 런북 · 전반부만)

> 이 문서는 게이트 **`G-skb01-bridge-populate`**(kiki·2026-09-10 등재)의 실행 절차 중
> **skill_node populate 부분만** 다룬다.
>
> **판정 기준: main `091dd3c5`** — 아래 명령·플래그·기본값·경로는 전부 그 커밋의 코드에서
> 확인했다(`whymath_backend.l1.skill_graph.populate.main()` 인자 정의 ·
> `config.Settings.database_url` 기본값과 `WHYMATH_` 접두 · alembic
> `20260703_1200_..._skill_node_projection.py`).
>
> **왜 "전반부만"인가(2026-09-11 코드 검증으로 확정)**: SKB-01 acceptance③은 원래 두 populate를
> 요구했다 — ① `skill_node` 최초 적재 ② `concept_graph.populate` 재실행으로
> `concept.behavior_skills` 채우기. 그런데 ②는 **목표를 달성하지 못한다**는 것이 코드로 확인됐다
> — 런타임 정본 `data/corpus/atom_graph_v1/graph.json`(2,683건)에는 `behavior_skills` 필드
> 자체가 없다(구 코퍼스 `concept_graph_v1/graph.json`에만 404/437 존재). `concept.behavior_skills`를
> 채우는 코드 경로가 저장소에 없으므로(SKB-01 acceptance③-보정 참조), ②는 이 런북에서 빼고
> **①만** 안내한다. 반쪽짜리 재실행으로 prod에 의미 없는 쓰기를 넣지 않기 위해서다
> (CLAUDE.md 「검증 없는 실행 안내 금지」).

---

## 1. 과제 명칭

`skill_node` 테이블 **최초 적재** — 스킬 택소노미(27개 스킬)를 운영 DB에 처음으로 채워 넣는다.

## 2. 목적

`EOS-63`(스킬 이벤트 소비 전환)이 2026-09-10 실측에서 막힌 이유는 "기록은 100% 되는데 해소는
0%"였다. 원인 중 하나가 `skill_node` 테이블이 **한 번도 채워진 적이 없다**(0행)는 것이었다.
이 런북은 그 27개 스킬 메타데이터를 `skill_node` 테이블에 upsert 방식으로 적재한다. 저장소에는
이미 스킬 택소노미 코퍼스(`data/corpus/skill_graph_v1/graph.json`, 27건)와 적재 CLI가 존재하므로
**새 코드는 필요 없다** — DB 쓰기 권한이 있는 사람(Kiki)이 한 번 실행하기만 하면 된다.

이 작업만으로 `concept.behavior_skills`(EOS-63이 측정한 해소율의 다른 절반)까지 채워지지는
않는다 — 그 부분은 별도 코드 작업이 선행돼야 하며(SKB-01 소유), 이 런북의 범위 밖이다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 예상 출력 | 소요 |
|---|---|---|---|
| ① 체크아웃 | main으로 detached 이동(지역 브랜치 무변경) | `POPULATE_FILE_OK=True` | ~20초 |
| ② 환경 | UTF-8 콘솔 + prod DB URL 주입 + import 확인 + 도달성 CLI | `REACH_EXIT=0` | ~15초 |
| ③ 사전 확인 | `skill_node` 테이블 존재 여부·현재 행 수(읽기 전용) | `TABLE_EXISTS=True` `BEFORE_COUNT=0` | ~5초 |
| ④ 적재 | `skill_graph.populate` 실행(27건 upsert) | `POPULATE_EXIT=0` | ~10초 |
| ⑤ 사후 확인 | 적재 후 행 수 재확인(읽기 전용) | `AFTER_COUNT=27` | ~5초 |

**쓰기는 ④에서만 일어난다.** upsert이므로 재실행해도 안전하다(멱등) — 실수로 두 번 돌려도
행 수가 27을 넘지 않는다.

## 4. 성공 기준

`AFTER_COUNT=27`이면 성공이다. 화면에 출력되는 `TABLE_EXISTS=` · `BEFORE_COUNT=` ·
`POPULATE_EXIT=` · `AFTER_COUNT=` 네 줄과 마지막 `git log` 줄을 **그대로 복사해 세션에
전달**한다 — 그것이 게이트 증적이다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `REACH_EXIT=1` | DB에 못 붙는다 | CLI가 출력하는 상태·대책을 그대로 따른다(`/demo-doctor` §W1) |
| `TABLE_EXISTS=False` | `skill_node` 테이블이 아직 없음(마이그레이션 미적용) | §6-1의 마이그레이션 블록을 1회 실행 후 ③부터 재개 |
| `POPULATE_EXIT=2` | `graph.json`을 못 찾음(작업 디렉터리 문제) | ①의 체크아웃이 제대로 됐는지 `git log --oneline -1`로 확인 |
| 그 외 예외 | 화면에 찍힌 예외 타입명·메시지를 그대로 세션에 전달 | — |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop 실행 중 · `whymath-pg` 컨테이너(호스트 포트 **5433**) 가동 ·
  `src\backend\.venv` 세팅 완료
- **DB**: prod DB = docker `whymath-pg` (5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 같은 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유 창이 없다.
새 PowerShell 창 하나를 열고 아래 블록을 순서대로 붙여넣는다.

---

## 실행 블록

> 아래 블록은 **자리표시자가 하나도 없다**. 그대로 통째로 붙여넣으면 된다.
> 각 블록 끝의 자가검증 줄이 **실패 상태에서 다른 값을 낸다** — 그 값을 보고 다음 블록으로 간다.

### [1단계] 체크아웃 — main으로 detached 이동(지역 브랜치 무변경)

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
# 작업 트리 청결부터 확인한다 — 더러우면 아무것도 하지 않는다.
$Dirty = (git status --porcelain --untracked-files=no)
"TRACKED_DIRTY=" + [bool]$Dirty
if (-not $Dirty) {
  $Branch = (git rev-parse --abbrev-ref HEAD)
  "RETURN_TO=$Branch"
  git fetch origin main
  $PopulateRel = "src/backend/whymath_backend/l1/skill_graph/populate.py"
  git checkout --detach origin/main
  git log --oneline -1
  "POPULATE_FILE_OK=" + (Test-Path (Join-Path (Get-Location) $PopulateRel))
}
```

**자가검증**: `TRACKED_DIRTY=False` **그리고** `POPULATE_FILE_OK=True`.
- `TRACKED_DIRTY=True`면 추적 중인 미커밋 변경이 있어 블록이 **아무것도 하지 않은 것**이다 —
  세션에 물은 뒤 다시 온다.
- `POPULATE_FILE_OK=False`면 fetch 실패 또는 main에서 파일이 사라진 것 — 다음 단계로 가지 않는다.

### [2단계] 환경 — UTF-8 + prod DB + 도달성 판정

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -c "import whymath_backend.l1.skill_graph.populate; print('IMPORT_OK=True')"
"IMPORT_EXIT=$LASTEXITCODE"
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**자가검증**: `PY_OK=True` · `IMPORT_OK=True`(`IMPORT_EXIT=0`) · **`REACH_EXIT=0`**.
- `IMPORT_EXIT=1`이면 의존성 미설치 — 화면에 찍힌 모듈명을 세션에 전달한다.
- `REACH_EXIT=1`이면 DB에 못 붙는다 — CLI가 출력하는 상태·대책을 그대로 따른다.
- `REACH_EXIT=2`는 고장이 아니라 측정 불가(Docker 미가동 등) — 화면의 안내를 먼저 해소한다.

### [3~5단계] 사전 확인 → 적재 → 사후 확인 (한 블록)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
"===== 3. 사전 확인 (읽기 전용) ====="
$TableExists = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT to_regclass('public.skill_node') IS NOT NULL;"
"TABLE_EXISTS=$($TableExists.Trim())"
if ($TableExists.Trim() -eq "t") {
  $Before = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM skill_node;"
  "BEFORE_COUNT=$($Before.Trim())"
  "===== 4. 적재 (여기서만 DB에 쓴다) ====="
  & $Py -m whymath_backend.l1.skill_graph.populate --graph data/corpus/skill_graph_v1/graph.json
  "POPULATE_EXIT=$LASTEXITCODE"
  "===== 5. 사후 확인 (읽기 전용) ====="
  $After = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM skill_node;"
  "AFTER_COUNT=$($After.Trim())"
  git log --oneline -1
} else {
  "TABLE_MISSING=True -- skill_node 테이블이 없다. 아래 [보조] 마이그레이션 블록을 먼저 실행한다."
}
```

**성공 판정**: `TABLE_EXISTS=t` · `BEFORE_COUNT=0`(최초 적재이므로) · `POPULATE_EXIT=0` ·
`AFTER_COUNT=27`. 이 네 줄과 마지막 `git log` 줄을 그대로 복사해 세션에 전달한다.

`BEFORE_COUNT`가 이미 0이 아니면(예: 이전에 부분 적재된 적이 있으면) 그 값도 그대로 전달한다 —
upsert라 안전하지만, 값이 27과 다르게 나오면 그 자체가 정보다.

---

## 6-1. [보조] `TABLE_MISSING=True`가 났을 때 — 마이그레이션 1회

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
& .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
"EXIT=$LASTEXITCODE"
cd C:\Users\kiki\Desktop\__AI\WhyMath
```

`EXIT=0`을 확인한 뒤 [3~5단계] 블록부터 재개한다.

## 6-2. 회차 후 원래 브랜치로 복귀

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
if ($Branch -and $Branch -ne "HEAD") { git checkout $Branch } else { git checkout main }
git status --short --branch
```

---

## 7. 게이트 clear 방법

**Kiki가 할 일은 위 네 줄(`TABLE_EXISTS=` · `BEFORE_COUNT=` · `POPULATE_EXIT=` ·
`AFTER_COUNT=`)과 `git log` 줄을 세션에 전달하는 것까지다.** 대장 조작
(`backlog.py gates clear`)은 세션이 가져간다.

세션 쪽 참고: `gates clear`의 `--evidence`에는 판정 기준(커밋 해시)이 반드시 들어가야 한다
(HARN-68). 이 게이트를 clear해도 `concept.behavior_skills` 부분(SKB-01 acceptance③-보정)은
여전히 코드 작업이 선행돼야 하므로 SKB-01 자체는 이 런북만으로 done 처리하지 않는다.

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **`concept.behavior_skills`는 이 런북으로 채워지지 않는다.** SKB-01 acceptance③-보정
  참조 — 채우려면 atom_node→concept 동기화 코드 신설 또는 graph.json 재생성 파이프라인
  병합이 먼저 필요하다(코드 작업, human gate 아님).
- **해소율(RESOLUTION) 재측정은 이 런북의 범위가 아니다.** `skill_node`가 채워져도
  `concept.behavior_skills`가 비어 있으면 `attempt_skill_event_reach_report`의 해소율은
  여전히 0%로 나올 가능성이 높다 — 그 재측정은 SKB-01 acceptance④(위 코드 작업 완료 후)의 몫이다.
