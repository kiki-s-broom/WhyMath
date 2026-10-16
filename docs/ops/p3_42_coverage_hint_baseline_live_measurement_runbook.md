# P3-42 — `phase3_coverage --hints-from-db` 운영 DB 기준선 실측 (Kiki 실행 런북)

> 태스크 **`P3-42-coverage-hint-baseline-live-measurement`**(P3-22 acceptance ④ 승계)의 실행 절차다.
>
> **선행 조건 없음.** 이 런북이 쓰는 CLI(`--hints-from-db`)는 P3-22(#1632)로 **이미 main에 있다**.
> 미머지 브랜치의 파일을 쓰지 않으므로 브랜치 체크아웃이 필요 없다 — 블록 [B]가 "당신 클론의
> 실행 입력이 main과 같은가"를 판정한다.
>
> **DB에 쓰지 않는다.** 모든 SQL은 `SELECT`이고, CLI는 `hints.verified`만 읽는다
> (`fetch_verified_hint_problem_ids` — 본문 `content`도 읽지 않는다). 쓰는 것은 임시 폴더
> `%TEMP%\p3_42`의 결과 파일뿐이다.
>
> 형식은 `g_skb01_concept_behavior_skills_populate_runbook.md` §9의 교훈을 따른다 — 최상위
> `elseif`/`else` 분기 없음, 건너뛰는 가드는 반드시 이유를 출력, 자리표시자 0개.

---

## 1. 과제 명칭

Phase 3 Coverage 계측기의 **힌트 연결 운영 기준선 실측** — 운영 DB(`whymath-pg`)에 검수 통과 힌트가
몇 문항에 달려 있고, 그것이 Coverage 계측기가 세는 JSONL 문제은행과 얼마나 겹치는지 잰다.

## 2. 목적

P3-22가 계측기에 `--hints-from-db`를 배선했지만, 구현 세션 환경에는 Postgres가 없어 **실제 DB 수치를
한 번도 못 쟀다**(실패 경로 `ConnectionRefusedError` → exit 2만 확인됐다). 그래서 지금
`hint` 연결은 "측정 불가"가 아니라 "측정해 본 적 없음"이다.

이 수치는 두 곳에 쓰인다.
- **P3-32**(핵심 개념 10종 hint 연결): 출발선. 지금 `linked` 몇 개인지를 알아야 "10/10"까지 얼마나
  남았는지 안다.
- **P3-41**(phase3_metrics 힌트 배선): `hint_seat`가 0이면 그쪽 지표도 0이 나온다 — 그 0이
  "힌트 없음"인지 "ID 불일치"인지를 먼저 가려 둔다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | Docker Desktop 기동 + prod DB 컨테이너 도달 | `DOCKER_OK=True` | ~10초 (꺼져 있으면 최대 3분) |
| B | 실행 입력이 main과 같은지 판정 + DB 힌트 건수(읽기 전용 SQL 4건) | `PATHS_MATCH_MAIN=True` · `DB_HINTS_VERIFIED=…` | ~20초 |
| C | 환경 주입 + 호스트→DB 도달성 + 요약/진단 스크립트 생성 | `REACH_EXIT=0` · `PROBE_OK=True` | ~15초 |
| D | **계측기 실행** (`--hints-from-db --json`) → 요약 | `MEASURED=True` · `HINT_SEAT=…` | ~10~60초 |
| E | **ID 공간 진단** — DB 힌트 문항 ↔ JSONL 은행 대조 | `VERDICT=…` | ~10초 |

## 4. 성공 기준

**"성공"은 `CLI_EXIT=0`이 아니다.** 이 계측기는 목표 미달이면 exit 1을 낸다 — 힌트 연결이 아직
채워지지 않은 지금은 **exit 1이 정상**이다. 판정은 이렇게 한다.

- **판정은 `MEASURED=True` 한 줄이다.** `CLI_EXIT`로 판정하지 않는다 — 이 계측기의 exit 1은
  "목표 미달"과 "크래시(예: import 실패의 traceback)"를 **구분하지 못한다**(2026-10-16 실측:
  의존성이 없는 환경에서 import 실패도 exit 1). 그래서 [D]는 exit code가 아니라 **결과 JSON이 비어
  있지 않은지**를 보고, 프로브가 JSON 안의 `hint_seat`가 실재하는 객체인지로 `MEASURED=`를 낸다.
- `CLI_EXIT`가 0 또는 1이고 `MEASURED=True`이며 `HINT_SEAT=`에 숫자 4개가 든 JSON이면 **측정 성공**
  (힌트가 아직 안 채워졌으므로 exit 1이 정상이다).
- `MEASURED=False`(`HINT_SEAT=null`)는 `--hints-from-db`가 읽은 값이 없다는 뜻 — 측정 실패다.
- `CLI_EXIT=2`는 DB를 못 읽은 **측정 실패**다. `[적재 실패]` 줄의 사유를 그대로 전달.
- 블록 [E]의 `VERDICT=` 한 줄이 acceptance ②의 답이다. `NO_VERIFIED_HINTS`·`ID_SPACE_DRIFT`·
  `NOT_IN_BANK`·`OVERLAP_OK` 중 하나가 나온다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `DOCKER_OK=False` | Docker 미기동 | 3분 기다린 뒤 [A]만 다시 — 그래도 False면 화면 전달 |
| `PATHS_MATCH_MAIN=False` | 클론의 실행 입력이 main과 다르다 | 멈추고 [B]의 `git status` 출력 전달 (D가 스스로 거부한다) |
| `REACH_EXIT`가 0이 아님 | 호스트→5433 도달 불가 | CLI가 출력한 사유 그대로 전달 |
| `CLI_EXIT=2` | DB 읽기 실패 | `[적재 실패]` 줄 전달 |
| `PSQL_FAILED` 또는 [B]의 `rc=1` | SQL 실패(`hints` 테이블 부재 가능) | 그 줄 전달 — 0건과 다른 결과다 |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop · `whymath-pg` 컨테이너(호스트 포트 **5433**) · `src\backend\.venv`
- **DB**: prod = docker `whymath-pg`(5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없고, 끝난 뒤에도 그
창을 계속 써도 된다. 블록 [C]에서 만든 변수(`$Py`·`$Probe` 등)를 [D]·[E]가 쓰므로 **[C]~[E]는
같은 창**에서 순서대로 붙여넣는다. [D]·[E]는 변수가 없으면 이유를 출력하고 거부한다(아무것도
읽지 않는다).

---

## 실행 블록

> 자리표시자가 하나도 없다. **블록 하나씩** 붙여넣고, 각 블록 끝의 판정값을 확인한 다음에 아래
> 블록으로 넘어간다. 마지막에 [B]·[D]·[E]의 출력을 **텍스트로 복사해** 회신한다.

### [A] Docker 기동 + prod DB 컨테이너 도달

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
$Probe1 = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT 1;"
"DOCKER_OK=" + ($LASTEXITCODE -eq 0 -and $null -ne $Probe1)
```

**확인**: `DOCKER_OK=True` · `docker ps` 줄에 `Up …` + `0.0.0.0:5433->5432/tcp`.

### [B] 실행 입력 동등성 + DB 힌트 건수 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
"MAIN_SHA=" + (git rev-parse --short origin/main)
"HEAD_SHA=" + (git rev-parse --short HEAD)
"----- 미커밋 변경(추적 파일) -----"
git status --porcelain --untracked-files=no
git diff --quiet origin/main -- "src/backend/whymath_backend" "data/corpus"
$PathsMatch = ($LASTEXITCODE -eq 0)
"PATHS_MATCH_MAIN=$PathsMatch"
"----- DB 힌트 건수 (SELECT 만) -----"
$HintsAll = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM hints;"
"DB_HINTS_ALL=$HintsAll (rc=$LASTEXITCODE)"
$HintsVerified = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM hints WHERE verified IS TRUE;"
"DB_HINTS_VERIFIED=$HintsVerified (rc=$LASTEXITCODE)"
$HintedProblems = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(DISTINCT problem_id) FROM hints WHERE verified IS TRUE;"
"DB_HINTED_PROBLEMS=$HintedProblems (rc=$LASTEXITCODE)"
$ProblemRows = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM problem;"
"DB_PROBLEM_ROWS=$ProblemRows (rc=$LASTEXITCODE)"
```

**확인**: `PATHS_MATCH_MAIN=True` · 네 DB 줄의 `(rc=0)`. 네 DB 값은 **그대로 기록해 회신**한다 —
이 값 자체가 정보다(예: `DB_HINTS_ALL=0 (rc=0)`이면 힌트 생성기가 prod에서 한 번도 안 돈 것이다).
`rc=1`이면서 값이 비어 있으면 SQL이 실패한 것이다 — 특히 `hints` 테이블이 prod 스키마에 아직 없는
경우(마이그레이션 미적용)가 그렇다. 그 경우 [D]도 exit 2로 끝나므로, 이 출력을 그대로 회신하면
"힌트 0건"이 아니라 "좌석 부재"로 보고된다.

> `PATHS_MATCH_MAIN=False`면 멈추고 위 `git status` 출력을 회신한다. 이 클론은 여러 세션이
> 공유하므로 타 세션 브랜치에 있을 수 있다 — 그 상태에서 [D]를 돌려도 [D]가 스스로 거부한다.

### [C] 환경 주입 + 도달성 + 요약·진단 스크립트 생성

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
$ReachExit = $LASTEXITCODE
"REACH_EXIT=$ReachExit"
$Out = Join-Path $env:TEMP "p3_42"
$Probe = Join-Path $Out "p3_42_probe.py"
$ProbePy = @'
import collections, glob, json, os, subprocess, sys

DB = ["docker", "exec", "-i", "whymath-pg", "psql", "-U", "whymath", "-d", "whymath",
      "-t", "-A", "-F", "|"]


def psql(sql):
    try:
        r = subprocess.run(DB + ["-c", sql], capture_output=True, encoding="utf-8",
                           errors="replace", timeout=60)
    except subprocess.TimeoutExpired:
        print("PSQL_FAILED reason=timeout60s")
        sys.exit(2)
    if r.returncode != 0:
        print("PSQL_FAILED rc=%s stderr=%s" % (r.returncode, r.stderr.strip()[:300]))
        sys.exit(2)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def summary(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    print("MEASURED=%s" % isinstance(d.get("hint_seat"), dict))
    print("JSON_EXIT_CODE_FIELD=%s" % d.get("exit_code"))
    print("PROBLEMS_SCANNED=%s" % d.get("problems_scanned"))
    print("HINT_SEAT=" + json.dumps(d.get("hint_seat")))
    comp = next((m for m in d.get("metrics", []) if m.get("key") == "concept_completeness"), None)
    if comp is None:
        print("COMPLETENESS=MISSING_IN_JSON")
    if comp is not None:
        print("COMPLETENESS value=%s met=%s/%s target=%s met_flag=%s" % (
            comp.get("value"), comp.get("met_count"), comp.get("population"),
            comp.get("target"), comp.get("met")))
    print("LINK_COUNTS_HINT=" + json.dumps(d.get("link_counts", {}).get("hint")))
    print("COMPLETENESS_MEASURABLE=" + json.dumps(d.get("completeness_measurable")))
    for w in d.get("warnings", []):
        print("WARNING: " + w)


def idspace(repo):
    n_all = int(psql("SELECT count(*) FROM hints")[0])
    n_hinted = int(psql("SELECT count(DISTINCT problem_id) FROM hints WHERE verified IS TRUE")[0])
    rows = [ln.split("|") for ln in psql(
        "SELECT DISTINCT p.problem_id, p.slug, coalesce(p.review_status::text, 'NULL') FROM hints h "
        "JOIN problem p ON p.problem_id = h.problem_id WHERE h.verified IS TRUE ORDER BY 1")]
    by_id, by_slug, scanned = {}, {}, 0
    pattern = os.path.join(repo, "data", "corpus", "problem_bank_*", "problems.jsonl")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                scanned += 1
                pid, slug = row.get("problem_id"), row.get("slug")
                if isinstance(pid, str):
                    by_id[pid] = row.get("review_status")
                if isinstance(slug, str):
                    by_slug[slug] = pid
    if scanned == 0:
        print("BANK_SCANNED=0 - JSONL bank not found under %s" % repo)
        sys.exit(2)
    match, drift, absent = [], [], []
    for pid, slug, db_status in rows:
        if pid in by_id:
            match.append((pid, slug, db_status))
            continue
        if slug in by_slug:
            drift.append((pid, slug, by_slug[slug]))
            continue
        absent.append((pid, slug))
    print("DB_HINTS_ALL=%d" % n_all)
    print("DB_HINTED_PROBLEMS=%d" % n_hinted)
    print("JOINED_PROBLEM_ROWS=%d" % len(rows))
    print("BANK_ROWS_SCANNED=%d  BANK_IDS=%d" % (scanned, len(by_id)))
    print("ID_MATCH=%d" % len(match))
    print("SLUG_MATCH_BUT_ID_DIFFERS=%d" % len(drift))
    print("NOT_IN_BANK=%d" % len(absent))
    print("ID_MATCH_STATUS_DB_VS_JSONL=" + json.dumps(dict(collections.Counter(
        "%s/%s" % (st, by_id[pid]) for pid, _, st in match))))
    for pid, slug, bank_pid in drift[:5]:
        print("  DRIFT_SAMPLE db=%s bank=%s slug=%s" % (pid, bank_pid, slug))
    for pid, slug in absent[:5]:
        print("  ABSENT_SAMPLE db=%s slug=%s" % (pid, slug))
    print("VERDICT=" + verdict_of(n_hinted, len(rows), match, drift))


def verdict_of(n_hinted, n_rows, match, drift):
    if n_hinted == 0:
        return "NO_VERIFIED_HINTS"
    if n_rows != n_hinted:
        return "HINTS_WITHOUT_PROBLEM_ROW"
    if match:
        return "OVERLAP_OK"
    if drift:
        return "ID_SPACE_DRIFT"
    return "NOT_IN_BANK"


def main(argv):
    if len(argv) == 3 and argv[1] == "summary":
        summary(argv[2])
        return 0
    if len(argv) == 3 and argv[1] == "idspace":
        idspace(argv[2])
        return 0
    print("usage: p3_42_probe.py summary <json> | idspace <repo>")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'@
if ($Py -and (Test-Path $Py)) { New-Item -ItemType Directory -Force -Path $Out | Out-Null; Set-Content -Path $Probe -Value $ProbePy -Encoding UTF8; "PROBE_OK=" + (Test-Path $Probe); "PROBE_LINES=" + @(Get-Content $Probe -Encoding UTF8).Count } else { "WRITE_REFUSED=True — PY=$Py (Test-Path=" + (Test-Path $Py) + "). src\backend\.venv 가 없습니다. 이 출력을 회신해 주십시오. 아무것도 쓰지 않았습니다." }
```

**확인**: `PY_OK=True` · `REACH_EXIT=0` · `PROBE_OK=True` · `PROBE_LINES`가 0이 아님.
`REACH_EXIT`가 0이 아니면 [D]·[E]는 스스로 거부한다.

### [D] 계측기 실행 (`--hints-from-db --json`) + 요약

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 변수 $PathsMatch(B)·$ReachExit(C)·$Py·$Probe·$Out 필요
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Ready = ($PathsMatch -eq $true) -and ($ReachExit -eq 0) -and $Py -and $Probe -and (Test-Path $Probe)
if ($Ready) { Remove-Item "$Out\coverage.json", "$Out\coverage.err" -ErrorAction SilentlyContinue; cmd /c "$Py -m whymath_backend.l1.standards.phase3_coverage --hints-from-db --json > $Out\coverage.json 2> $Out\coverage.err"; $CliExit = $LASTEXITCODE; "CLI_EXIT=$CliExit"; $JsonBytes = (Get-Item "$Out\coverage.json" -ErrorAction SilentlyContinue).Length; "CLI_JSON_BYTES=$JsonBytes"; "----- stderr -----"; Get-Content "$Out\coverage.err" -Encoding UTF8; if (($CliExit -le 1) -and ($JsonBytes -gt 0)) { & $Py -I $Probe summary "$Out\coverage.json" } else { "CLI_FAILED=True — CLI_EXIT=$CliExit JSON_BYTES=$JsonBytes. 결과 JSON 이 없으면 측정 실패입니다. 위 stderr 를 회신해 주십시오." } } else { "RUN_REFUSED=True — PATHS_MATCH_MAIN=$PathsMatch REACH_EXIT=$ReachExit PY=$Py PROBE=$Probe. False/비어 있는 항목을 해소한 뒤 다시 붙여넣어 주십시오. 아무것도 읽지 않았습니다." }
```

> **왜 `cmd /c`로 감싸는가**: 결과 JSON에 한국어가 들어갑니다. PowerShell 5.1은 자식 프로세스
> stdout을 cp949로 디코딩했다 재인코딩하며 JSON 구조 문자를 잃습니다(2026-09-14 실측).
> `cmd /c "… > 파일"`은 그 경유 자체를 없앱니다.

**확인**: `MEASURED=True` · `HINT_SEAT={…}`에 숫자 4개 · `COMPLETENESS value=…` ·
`LINK_COUNTS_HINT={"linked": …, "missing": …, "unmeasured": …}`. `CLI_EXIT`는 0 또는 1이면 된다
(1이 정상). `MEASURED=False`·`CLI_FAILED=True`·`CLI_EXIT=2`면 측정 실패다.

### [E] ID 공간 진단 (acceptance ②)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 변수 $Py·$Probe 필요
cd C:\Users\kiki\Desktop\__AI\WhyMath
$RepoPath = (Get-Location).Path
if ($Py -and $Probe -and (Test-Path $Probe)) { & $Py -I $Probe idspace $RepoPath; "IDSPACE_EXIT=$LASTEXITCODE" } else { "RUN_REFUSED=True — PY=$Py PROBE=$Probe. 블록 [C]를 같은 창에서 먼저 실행해 주십시오. 아무것도 읽지 않았습니다." }
```

**확인**: `IDSPACE_EXIT=0` + `VERDICT=` 한 줄. 이 블록은 DB `problem`의 `(problem_id, slug)`와
JSONL 은행의 `(problem_id, slug)`를 대조하는 **읽기 전용** 진단이다.

---

## 7. 결과 해석 (회신을 받은 뒤 세션이 하는 일)

세션은 아래 표대로 판정하고, 결과 수치를 태스크 notes에 **그대로** 기록한다. 측정을 못 한
것을 통과로 보고하지 않는다.

| `VERDICT` | 뜻 | 기준선 보고 | 후속 |
|---|---|---|---|
| `NO_VERIFIED_HINTS` | prod에 검수 통과 힌트가 0건 — **ID 문제가 아니다** | `hint linked 0 / missing N` (원인 = 힌트 미생성) | P3-32가 채우기부터 시작 |
| `OVERLAP_OK` | 힌트 문항이 은행과 겹친다 | `hint_seat` 4수치 + `linked/missing` + Completeness | 정상 — 수치가 곧 기준선 |
| `ID_SPACE_DRIFT` | 같은 slug인데 PK가 다르다 — 재적재가 slug 충돌 시 기존 PK를 보존한 결과(`problem_bank/populate.py`) | **힌트 0건으로 보고하지 않는다** | ID 공간 정합 태스크 신규 등재 후 정정 |
| `NOT_IN_BANK` | 힌트는 있으나 문항이 JSONL 은행에 없다(시드·타 경로로 만든 문항) | 겹침 0 그대로 + 원인 병기 | 힌트 대상 문항 출처 확인 |
| `HINTS_WITHOUT_PROBLEM_ROW` | 힌트가 가리키는 `problem` 행이 없다 | FK 위반 의심 — 별건 | 스키마 점검 |

**겹침이 있어도 `linked`는 낮을 수 있다.** 계측기의 `hint` 연결은 "힌트가 달린 **승인(approved)**
문항이 개념마다 1건 이상"이다(`_completeness_links`). 승인 여부는 **JSONL 행의 `review_status`**로
판정하는데(`PROBLEM_ELIGIBLE_STATUS`), 힌트는 **DB 행**에 달린다. `ID_MATCH_STATUS_DB_VS_JSONL`이
`DB상태/JSONL상태` 쌍으로 이 둘을 나란히 보여 준다.

- `approved/approved` — 정상 적격.
- `approved/None` — DB에서는 승인됐는데 JSONL에는 상태가 없다. 계측기는 이 문항을 **적격으로 세지
  않는다**(`eligible_hinted`에서 빠진다). 원인은 힌트도 ID도 아닌 **상태 좌석의 불일치**이며
  기준선을 "힌트 없음"으로 보고하지 않는다 — 별도 태스크로 등재한다.

## 8. 오프라인 사전 확인 (2026-10-16 · 판정 기준: `origin/main` `419c4e7c`)

런북 작성 세션이 **DB 없이** 확인한 것 — 라이브 실행이 가를 질문을 줄이기 위한 것이며, **운영 DB
수치가 아니다**.

- JSONL 은행 40개 디렉터리 14,694행. `problem_id`가 있는 행 14,690건은 **전부 유일한 UUIDv5**이고
  `str(uuid.UUID(x)) == x`(소문자·하이픈 정규형)라서, DB가 돌려주는 `str(uuid)`와 **문자열 비교가
  성립**한다. 즉 *형식* 불일치로 겹침이 0이 될 구조적 이유는 없다.
- 계측기가 쓰는 **적격 판정은 JSONL `review_status == "approved"`뿐**이다. 실측 분포는 `None`
  11,552 · `approved` 2,984(5개 디렉터리 — `conceptual_v0`·`generated_v0`·`misconception_mc_v0`·
  `p3_calculus1_diff_v0`·`rephrased_v0`) · `pending` 158이다. 즉 JSONL 기준으로 적격이 될 수 있는
  문항은 **최대 2,984건**이고, 그 밖의 은행 문항에 힌트가 달려 있으면 DB에서 승인된 문항이어도
  `eligible_hinted`에 잡히지 않는다(DB 상태가 JSONL로 역류하지 않는다).
- `problem_id`가 없는 행 4건은 `problem_bank_v1`의 초기 시드(`pending`)다. 계측기는 ID 없는 행을
  건너뛴다(`_problem_from_row`). 적재 시에는 `uuid4` 기본값이 붙어 JSONL과 영영 대응하지 않는다.
- 따라서 [E]가 가를 진짜 질문은 하나다 — **과거 적재의 PK 보존**. `problem_bank/populate.py`는
  slug 충돌 시 기존 `problem_id`를 보존하므로, 어떤 문항이 JSONL의 `problem_id`가 확정되기 전에
  다른 값으로 먼저 적재됐다면 DB와 JSONL의 PK가 갈린다. 이것은 DB를 읽어야만 안다.
- 계측기를 **합성 주입**(DB 없이 `hint_problem_ids`에 적격 문항 ID 5건 + 존재하지 않는 ID 1건)으로
  실행해 이 런북의 요약 프로브가 실제 `to_json` 출력을 읽는 것을 확인했다: 범위 은행은
  **1,073문항 중 적격(approved) 917**이고, 주입 6건은 `hint_seat = {hinted 6 · in_scope_bank 5 ·
  eligible_hinted 5 · outside_scope 1}`로 보고됐다. 이 값들은 **형식 검증용 합성 입력**이며 운영
  DB의 사실이 아니다. DB 없는 환경의 `--hints-from-db`는 문서대로 exit 2 +
  `[적재 실패] CoverageError … ConnectionRefusedError`를 낸다.
