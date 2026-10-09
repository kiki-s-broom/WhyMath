# M0671 라이브 DB 서명 메모 복구 런북 (Kiki 머신 · 1행 쓰기)

> **판정 기준: main `54e0d365`** (코퍼스 `crosslinks.json` 68건 · M0671 note "성취기준 [12미적Ⅰ-02-03] 원문 확인함(…) · 검수:kiki 2026-10-06").
> 라이브 DB 값은 Kiki 머신 출력으로만 봤다(2026-10-07 적재 출력 `BEFORE_TOTAL=34`·`AFTER_TOTAL=34`).

## 1. 과제 명칭

`power-rule-step-omitted ↔ M0671` 라이브 DB 행의 서명 메모(note)를 승인 코퍼스 값으로 되돌린다.

## 2. 목적

2026-10-07 Kiki가 같은 행을 직접 서명해 적재하면서(게이트 `G-misc40-deferred-m0671-redecision`는 이미 clear였다) DB 행의 note가
`검수:kiki 2026-10-07`(단독)이 됐다. 승인 코퍼스의 note는 "원문 확인함 … 검수:kiki 2026-10-06"이다. 신뢰도 0.85·직접매핑은 같다.
Kiki가 코퍼스를 정본으로 정했으므로(선택지 A) DB를 코퍼스에 맞춘다. **다른 행은 건드리지 않는다.**

## 3. 구체적 절차 (약 2~3분)

- [A] 읽기 전용: `origin/main`의 임시 작업 폴더를 만들고, 도우미 스크립트를 쓰고, DB 도달성과 현재 상태를 읽는다.
- [B] 쓰기: 선행 조건 8개를 스스로 재검사하고 **모두 참일 때만** 1행을 적재한다. 적재 뒤 DB를 다시 읽어 note 일치와 전체 행 수 불변을 판정한다.
- [C] 임시 폴더를 정리한다.

계획 건수는 **정확히 1행**이다. 스크립트가 코퍼스에서 같은 키의 행이 1건이 아니거나 DB에 그 행이 1건이 아니면 쓰지 않고 거부한다(INSERT로 새 행을 만들지 않는다).

## 4. 성공 기준

- [A]: `REFUSED`가 나오지 않고, `PLAN_ROWS=1` · `DB_ROWS=1` · `DB_FIELDS_MATCH=True` · `DB_NOTE_MATCH=False`가 보인다
  (`DB_NOTE_MATCH=True`면 이미 복구된 것이므로 [B]를 붙여넣을 필요가 없다).
- [B]: `WRITE_ALLOWED=True` · `LOADED=1` · `AFTER_NOTE_MATCH=True` · `RESTORE_OK=True` · `LOAD_EXIT=0`, 그리고 `AFTER_TOTAL`이 `BEFORE_TOTAL`과 같다.
- 실패하면 그 블록의 출력 전체를 세션에 전달한다. `WRITE_REFUSED=True`는 DB를 건드리지 않은 상태다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop 실행 중 · `whymath-pg` 컨테이너(호스트 포트 **5433**) 가동 · `src\backend\.venv` 세팅 완료
- **DB**: prod DB = docker `whymath-pg` (5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

새 PowerShell 창 하나에서 [A] → [B] → [C]를 순서대로 붙여넣는다. 서버를 띄우지 않으므로 점유 창이 없다.

---

## 실행 블록

### [A] 작업 폴더·도우미 스크립트·현재 상태 확인 (읽기 전용)

```powershell
# [Windows PowerShell · Phaiakes9] 새 창
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Repo = (Get-Location).Path
$Wt = Join-Path $env:TEMP "whymath_m0671_wt"
$Work = Join-Path $env:TEMP "whymath_m0671_work"
git fetch origin main
$FetchOk = ($LASTEXITCODE -eq 0)
$Expected = (git rev-parse origin/main)
if (Test-Path $Wt) { git worktree remove --force $Wt }
git worktree add --detach $Wt origin/main
$Head = (git -C $Wt rev-parse HEAD)
"WT_HEAD=$Head"
"FETCH_OK=$FetchOk"
if ($FetchOk -and $Expected -and ($Head -eq $Expected)) {
New-Item -ItemType Directory -Force -Path $Work | Out-Null
@'
import json, sys
from pathlib import Path
from sqlalchemy import text
from whymath_backend.config import get_settings
from whymath_backend.l1.concept_graph.embedding import _build_sync_engine
from whymath_backend.l1.misconception.crosslink_loader import load_crosslinks

KEBAB, MIS = "power-rule-step-omitted", "M0671"
mode, corpus_path = sys.argv[1], Path(sys.argv[2])
rows = [r for r in json.loads(corpus_path.read_text(encoding="utf-8"))["crosslinks"]
        if r["kebab_id"] == KEBAB and r["mis_id"] == MIS]
engine = _build_sync_engine(get_settings())


def read_db():
    with engine.connect() as c:
        total = c.execute(text("SELECT count(*) FROM misconception_crosslink")).scalar_one()
        got = c.execute(text("SELECT link_type, confidence, method, note FROM misconception_crosslink "
                             "WHERE kebab_id=:k AND mis_id=:m"), {"k": KEBAB, "m": MIS}).all()
    return total, got


def report(tag):
    total, got = read_db()
    print("PLAN_ROWS=%d" % len(rows))
    print("%s_TOTAL=%d" % (tag, total))
    print("%s_ROWS=%d" % (tag, len(got)))
    if len(rows) == 1 and len(got) == 1:
        r, (lt, conf, meth, note) = rows[0], got[0]
        print("%s_FIELDS_MATCH=%s" % (tag, (lt, float(conf), meth) == (r["link_type"], r["confidence"], r["method"])))
        print("%s_NOTE_MATCH=%s" % (tag, note == r["note"]))
        print("%s_NOTE=%s" % (tag, note))
        print("CORPUS_NOTE=%s" % r["note"])
    return total, got


if mode == "check":
    report("DB"); sys.exit(0)
if mode != "apply":
    print("BAD_MODE"); sys.exit(2)
before_total, before_rows = report("BEFORE")
if len(rows) != 1 or len(before_rows) != 1:
    print("APPLY_REFUSED=True plan_rows=%d db_rows=%d" % (len(rows), len(before_rows))); sys.exit(2)
n = load_crosslinks(None, {"crosslinks": rows})
print("LOADED=%d" % n)
after_total, after_rows = report("AFTER")
ok = (n == 1 and after_total == before_total and len(after_rows) == 1 and after_rows[0][3] == rows[0]["note"])
print("RESTORE_OK=%s" % ok); sys.exit(0 if ok else 1)
'@ | Set-Content -Encoding UTF8 (Join-Path $Work "m0671_restore.py")
@'
import pathlib, sys, whymath_backend
f = pathlib.Path(whymath_backend.__file__).resolve()
ok = pathlib.Path(sys.argv[1]).resolve() in f.parents
print("CODE_FILE=" + str(f)); print("CODE_FROM_WT=" + str(ok)); sys.exit(0 if ok else 1)
'@ | Set-Content -Encoding UTF8 (Join-Path $Work "check_origin.py")
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = Join-Path $Wt "src\backend"
$Py = Join-Path $Repo "src\backend\.venv\Scripts\python.exe"
$Script = Join-Path $Work "m0671_restore.py"
$Corpus = Join-Path $Wt "data\corpus\misconception_crosslinks_v1\crosslinks.json"
"PY_OK=" + (Test-Path $Py)
& $Py (Join-Path $Work "check_origin.py") $Wt
"CODE_FROM_WT_EXIT=$LASTEXITCODE"
& $Py -m whymath_backend.ops.db_host_reachability | Out-Null
"REACH_EXIT=$LASTEXITCODE"
$ChkA = @(& $Py $Script check $Corpus)
$ChkA
$BeforeTotalLine = ($ChkA | Where-Object { $_ -like "DB_TOTAL=*" })
"BEFORE_TOTAL_LINE=$BeforeTotalLine"
"A_DONE=True"
} else { "REFUSED — HEAD=$Head EXPECTED=$Expected FETCH_OK=$FetchOk (worktree 전환 또는 fetch 실패 — 이후 단계를 실행하지 않았습니다. 이 줄을 세션에 알려 주세요.)" }
```

**눈으로 확인한 다음에만 [B]를 붙여넣는다.** `REFUSED`가 나왔거나 `DB_NOTE_MATCH=True`면 [B]는 필요 없다.

### [B] 1행 적재 (여기서만 DB에 쓴다 · 스스로 재검사)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$HeadOk = ((git -C $Wt rev-parse HEAD) -eq $Expected)
& $Py (Join-Path $Work "check_origin.py") $Wt | Out-Null
$CodeOk = ($LASTEXITCODE -eq 0)
& $Py -m whymath_backend.ops.db_host_reachability | Out-Null
$ReachOk = ($LASTEXITCODE -eq 0)
$Chk = @(& $Py $Script check $Corpus)
$PlanOk = ($Chk -contains "PLAN_ROWS=1")
$DbRowOk = ($Chk -contains "DB_ROWS=1")
$FieldsOk = ($Chk -contains "DB_FIELDS_MATCH=True")
$NeedOk = (-not ($Chk -contains "DB_NOTE_MATCH=True"))
$TotalOk = ($BeforeTotalLine -and ($Chk -contains $BeforeTotalLine))
if ($HeadOk -and $CodeOk -and $ReachOk -and $PlanOk -and $DbRowOk -and $FieldsOk -and $NeedOk -and $TotalOk) {
  "WRITE_ALLOWED=True"
  & $Py $Script apply $Corpus
  "LOAD_EXIT=$LASTEXITCODE"
} else { "WRITE_REFUSED=True HEAD_OK=$HeadOk CODE_OK=$CodeOk REACH_OK=$ReachOk PLAN_OK=$PlanOk DB_ROW_OK=$DbRowOk FIELDS_OK=$FieldsOk NEED_OK=$NeedOk TOTAL_OK=$TotalOk" }
```

### [C] 정리

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$CanClean = ($Wt -and $Work -and ($Wt -like "*whymath_m0671_wt") -and ($Work -like "*whymath_m0671_work") -and (Test-Path $Wt) -and (Test-Path $Work))
if ($CanClean) {
  git worktree remove --force $Wt
  Remove-Item -Recurse -Force $Work
  "CLEANED=True WT_LEFT=" + (Test-Path $Wt) + " WORK_LEFT=" + (Test-Path $Work)
} else { "CLEAN_REFUSED=True WT=$Wt WORK=$Work (변수가 비었거나 예상 폴더가 아닙니다 — 아무것도 지우지 않았습니다)" }
git worktree list
git status --short --branch
```

**성공 판정**: `CLEANED=True WT_LEFT=False WORK_LEFT=False` · `git worktree list`에 `whymath_m0671_wt`가 없음 · `git status`의 브랜치가 실행 전과 같다. `CLEAN_REFUSED=True`면 아무것도 지우지 않은 것이다(이 창이 [A]를 실행한 창이 아니면 변수가 비어 있다).

---

## 이 런북이 답하지 못하는 것 (정직 고지)

- **PowerShell 블록은 이 환경에서 실행하지 못했다**(`pwsh` 부재). 도우미 스크립트(Python)와 SQL은 임시 PostgreSQL 16에서 운영과 같은 제약(유니크 키·`mis_id` 외래키)·같은 초기 상태(34행·note `검수:kiki 2026-10-07`)로 검증했다:
  복구 전 `DB_NOTE_MATCH=False` → 적용 `RESTORE_OK=True`(전체 행 수 34 불변 · 다른 33행의 해시 불변) → 재적용 멱등 → 코퍼스에 행 없음/DB에 행 없음 입력은 `APPLY_REFUSED` 종료 코드 2 → 적재가 아무것도 쓰지 않는 뮤테이션에서 `RESTORE_OK=False` 종료 코드 1.
- 임시 DB에는 pgvector 확장이 없어 테스트 래퍼가 벡터 타입 등록 훅만 무력화했다. 크로스링크 테이블과 무관한 부분이다.
- 라이브 DB의 현재 값은 이 세션이 직접 읽지 못한다. [A]의 출력이 그 증거다.
- 이 블록은 **M0671 1행만** 다룬다. 라이브 DB 34행 대 코퍼스 68행 어긋남, 오귀속 의심 4건, 서명 메모 없는 26건은 게이트 `G-crosslink-live-drift-disposition`(Kiki 결정)이 소유한다.
