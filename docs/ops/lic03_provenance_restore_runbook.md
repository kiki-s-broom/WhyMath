# LIC-03 — 기존 코퍼스 provenance 원장 복원 런북 (Phaiakes9)

> 판정 정본: `docs/standards/provenance_enforcement_layer_decision.md` §9
> 실행 주체: **Kiki** · 실행 환경: **Phaiakes9(= 평소 쓰는 Windows PowerShell)**

---

## §0. 사전 브리핑 (6항목)

1. **과제 명칭** — 문제은행 코퍼스 14,034건의 출처 원장(`content_provenance`) 복원.

2. **목적** — LIC-03 이전에 적재된 문항은 DB에 출처 기록이 **하나도 없다**(원장 테이블은
   있었고 쓰는 코드가 없었다). A4 저작권 레일은 "AI 생성물은 출처 원장을 반드시 동반한다"를
   요구하므로, 12월 검증(G1) 전에 기존 적재분을 채워야 한다. 결과는 저작권 판정·노출 계약·
   F-Ⅱ 오류율 산정의 전제가 된다.

3. **구체적 절차** — 블록 4개를 **순서대로** 붙여넣는다. [1] 전제 확인(읽기) → [2] 복원 전
   계수(읽기) → [3] 복원 실행(**쓰기**) → [4] 복원 후 검증(읽기). [3]만 DB에 쓴다.
   예상 소요: [1][2][4]는 각 5초 이내, [3]은 **약 1분 30초**(37개 코퍼스 순차 적재).

4. **성공 기준** — [4]가 `RESTORED=14034` 같은 형태로 **문항 수와 원장 수가 같음**을
   출력한다. [3]의 마지막 줄 `전 코퍼스 37개 합계`의 원장 신규 건수가 [2]와 [4]의 차이와
   일치해야 한다. 실패 신호: [3]이 `WRITE_REFUSED=True`를 출력하면 아무것도 쓰지 않은
   것이다 — 함께 출력된 False 항목을 그대로 회신하면 된다(재실행해도 안전).

5. **실행 환경** — Windows PowerShell(= Phaiakes9). 작업 디렉터리
   `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건 2건: **Docker Desktop 가동**(prod DB
   컨테이너 `whymath-pg`) · **PR #1268이 main에 머지돼 있을 것**(`--all` 플래그가 그 PR에
   들어 있다 — 블록 [1]이 그 존재를 실측해 확인하고, 없으면 [3]이 거부한다).

6. **창 구분** — **새 PowerShell 창 1개**에서 블록 4개를 모두 실행한다. 장기 점유
   프로세스(서버 등)가 없으므로 창을 나눌 필요가 없고, 블록 [1]이 설정한 변수를 [3]이
   다시 계산해 쓰므로 **같은 창**이어야 한다.

---

## §1. 블록 [1] — 전제 확인 (읽기 전용)

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout main
git pull --ff-only origin main
git log -1 --oneline
$Py = ".\.venv\Scripts\python.exe"
$Probe = & $Py -c "from whymath_backend.l1.problem_bank import populate as m; print(m.__file__); print('ALL=' + str(hasattr(m, 'discover_problem_corpora')))" 2>&1 | Out-String
$HasAll = $Probe -match 'ALL=True'
$PgUp = (& docker ps --filter "name=whymath-pg" --format "{{.Names}}" | Out-String).Trim() -eq "whymath-pg"
"HAS_ALL_FLAG=$HasAll"
"LOADED_MODULE=$($Probe.Split([char]10)[0].Trim())"
"PG_CONTAINER_UP=$PgUp"
```

세 줄이 전부 참(`HAS_ALL_FLAG=True` · `LOADED_MODULE`이 이 클론 경로 ·
`PG_CONTAINER_UP=True`)이어야 다음으로 갑니다. `HAS_ALL_FLAG=False`면 PR #1268이 아직
머지되지 않았거나 다른 트리의 코드가 로드된 것입니다 — `LOADED_MODULE` 경로가 답을 줍니다
(파일을 읽어 보는 것만으로는 *그 파일이 실제로 임포트됐는지* 알 수 없으므로 import로 확인합니다).

## §2. 블록 [2] — 복원 전 계수 (읽기 전용)

```powershell
$Before = (& docker exec whymath-pg psql -U whymath -d whymath -tAc "select (select count(*) from problem)||'/'||(select count(*) from content_provenance)" | Out-String).Trim()
"BEFORE problem/provenance = $Before"
```

## §3. 블록 [3] — 복원 실행 (**쓰기** · 자가거부 가드)

이 블록은 [1]의 판정을 **스스로 다시 계산**해 확인합니다. 하나라도 어긋나면 아무것도 쓰지
않고 무엇이 False였는지 출력합니다 — 출력은 흐름을 멈추지 못하므로 블록 자신이 멈춥니다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
$Py = ".\.venv\Scripts\python.exe"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath"
$ReProbe = & $Py -c "from whymath_backend.l1.problem_bank import populate as m; print('ALL=' + str(hasattr(m, 'discover_problem_corpora')))" 2>&1 | Out-String
$OkAll = $ReProbe -match 'ALL=True'
$OkPg = (& docker ps --filter "name=whymath-pg" --format "{{.Names}}" | Out-String).Trim() -eq "whymath-pg"
$OkCorpus = @(Get-ChildItem -Path "data\corpus" -Filter "problems.jsonl" -Recurse | Where-Object { $_.Directory.Name -like "problem_bank_*" }).Count
if ($OkAll -and $OkPg -and ($OkCorpus -ge 30)) { & $Py -m whymath_backend.l1.problem_bank.populate --all; "POPULATE_EXIT=$LASTEXITCODE"; $After = (& docker exec whymath-pg psql -U whymath -d whymath -tAc "select (select count(*) from problem)||'/'||(select count(*) from content_provenance)" | Out-String).Trim(); "AFTER problem/provenance = $After" } else { "WRITE_REFUSED=True — 쓰지 않았습니다. HAS_ALL_FLAG=$OkAll PG_CONTAINER_UP=$OkPg CORPUS_COUNT=$OkCorpus (각각 True/True/30이상이어야 실행됩니다)" }
```

## §4. 블록 [4] — 복원 후 검증 (읽기 전용)

```powershell
$Rows = (& docker exec whymath-pg psql -U whymath -d whymath -tAc "select (select count(*) from problem)||' '||(select count(*) from content_provenance)||' '||(select count(*) from problem p where p.source_type='자체생성' and not exists (select 1 from content_provenance v where v.problem_id=p.problem_id))" | Out-String).Trim()
$Parts = $Rows -split '\s+'
"PROBLEMS=$($Parts[0]) PROVENANCE=$($Parts[1]) GENERATED_WITHOUT_PROVENANCE=$($Parts[2])"
```

**성공 판정**: `GENERATED_WITHOUT_PROVENANCE=0`. 이 값이 "출처 없는 AI 생성물"의 잔량이며
0이 곧 A4 DoD 충족입니다. 이 세 숫자를 그대로 회신해 주시면 됩니다.

---

## §5. 안전성 메모

- **멱등** — 두 번 돌려도 문항·원장 행이 늘지 않습니다(실측: 재실행 시 신규 0건, 행 수 불변).
  중간에 끊겨도 다시 돌리면 됩니다.
- **비파괴** — 원장 행이 이미 있으면 건너뜁니다. 사람이 채운 검수·승인 필드를 적재기가
  덮어쓰지 않습니다.
- **되돌리기** — `delete from content_provenance` 한 줄로 복원 전 상태가 됩니다(원장은
  코퍼스에서 언제든 다시 만들어집니다). 문항 행은 이 작업이 건드리지 않습니다.
- **주의** — 원장 행이 생기면 그 문항의 `delete from problem`이 FK로 막힙니다(감사 추적을
  조용히 지우지 않으려는 의도적 설계). 문항을 지워야 하면 원장을 먼저 지웁니다.

## §6. 이 런북의 검증 범위 (정직)

**검증된 것**: ① 구조 — `scripts/ops/check_runbook_blocks.py`(HARN-106) 통과, 그리고 그
가드가 실제로 막는지 주입 3종(가드 제거·침묵 `else`·새 줄 `else`)으로 전건 차단 확인
② 동작 — `--all` 경로를 리눅스 + 실 PostgreSQL 16/pgvector에서 종단 실행(원장 0 → 14,034
복원 1분 31초 → 재실행 신규 0건).

**검증되지 않은 것**: 위 PowerShell 블록의 **구문 파싱**은 이 개발 환경에 PowerShell이 없어
실행해 보지 못했다. 즉 cmdlet 오타·인용 부호 같은 축은 Kiki 머신에서 처음 실행된다.
그래서 블록 순서를 읽기 → 읽기 → 쓰기 → 읽기로 두어 **오타가 있어도 [1][2]에서 먼저
드러나게** 했고, 쓰기 블록 [3]은 선행 판정을 스스로 재검사해 거부한다. [1]이나 [2]에서
오류가 나면 그 메시지를 회신해 주시면 됩니다 — [3]으로 넘어가지 마십시오.
