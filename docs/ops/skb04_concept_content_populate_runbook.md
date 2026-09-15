# G-skb04-concept-content-populate — `concept_content` 적재 (Kiki 실행 런북)

> 게이트 **`G-skb04-concept-content-populate`**(kiki·2026-09-15 등재)의 실행 절차다.
>
> **선행 조건 없음.** 이 런북이 쓰는 CLI와 코퍼스는 **이미 main에 있다**(SKB-04는 코드를 추가하지
> 않는다 — 착수 검증에서 코드 공백이 아님이 확정됐다). 그래서 [C]의 착지 확인 스텝도 없다.
>
> **`G-skb03-atom-node-populate`와 같은 창에서 연달아 실행할 수 있다** — 두 테이블은 서로를
> 참조하지 않으므로 순서 의존이 없다. SKB-03 런북을 방금 돌렸다면 [A]·[C]는 이미 만족된 상태지만,
> 다시 붙여넣어도 무해하다(Docker 기동은 멱등, 환경 변수는 재주입).
>
> 형식은 `g_skb01_concept_behavior_skills_populate_runbook.md` §9의 교훈을 따른다 — 최상위
> `elseif`/`else` 분기 없음, 건너뛰는 가드 없음, 블록 사이 판정은 사람이 눈으로.

---

## 1. 과제 명칭

`concept_content` 적재 — 콘텐츠 4종 코퍼스(K-12 437 + 대학 409 = 846건)를 `concept_content`
테이블에 멱등 적재한다.

## 2. 목적

이 CLI는 완비돼 있는데 **prod에서 한 번도 실행되지 않았다.** 2026-09-14 크로스워크 이전이
`concept_content K-12 대상 행 부재 437건`을 보고한 것이 그 증상이다.

그 결과 L4 콘텐츠 공급 경로가 조회할 원문이 없다. `content_supply.py`는 행이 없으면 로그 없이
`None`을 반환하고(256행), `age_band_explanation.py`는 경고 로그를 남기고 `None`을 반환한다(79행)
— 후자는 침묵이 아니지만 전자는 조용하다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 기대 출력 | 소요 |
|---|---|---|---|
| A | Docker Desktop 기동 + prod DB 도달 확인 | `DOCKER_OK=True` | ~10초 (꺼져 있으면 최대 3분) |
| B | 실행 입력이 main과 같은지 판정 + BEFORE 카운트 | `PATHS_MATCH_MAIN=True` · `BEFORE_TOTAL` | ~20초 |
| C | 환경 주입 + 도달성 | `REACH_EXIT=0` | ~15초 |
| D | **적재** (여기서만 DB에 쓴다) | `POPULATE_EXIT=0` | ~30초~2분 |
| E | AFTER 카운트 (scope별) | `AFTER_TOTAL=846` | ~5초 |

**부수 효과 없음.** SKB-03의 CLI와 달리 이 CLI는 `concept_content` 한 테이블만 건드린다.
FK가 없고 `code`가 PK라 다른 테이블의 선행 적재도 필요 없다.

## 4. 성공 기준

`POPULATE_EXIT=0` → `AFTER_TOTAL=846`(K-12 437 + 대학 409)이면 성공이다. 두 수치는 코퍼스에서
직접 센 값이다(2026-09-15 실측: `content.json`의 `content` 배열 길이, code 437건 전건 유일).

CLI가 stdout에 찍는 두 줄(`콘텐츠 적재: N건 (scope=K-12·src=…)`·`(scope=대학·…)`)의 N과
`AFTER_K12`·`AFTER_UNIV`가 **각각 같아야 한다** — 적재기 반환값과 DB 카운트는 서로 다른 경로에서
나오므로 한쪽만 맞는 상태를 가른다.

`BEFORE_TOTAL`은 0이든 아니든 그대로 기록해 전달한다 — 이 게이트는 "테이블이 전량 비었는지 K-12
437행만 없는지"를 아직 실측하지 못했고(SKB-04 acceptance ①, 특히 **대학 409행의 존재 여부는
한 번도 확인된 적이 없다**), BEFORE가 그 답이다.

### 실패 대처

| 증상 | 뜻 | 대처 |
|---|---|---|
| `PATHS_MATCH_MAIN=False` | 실행 입력이 main과 다르다 | 멈추고 [B]의 `git status` 출력 전달 |
| `REACH_EXIT`가 0이 아님 | DB에 못 붙는다 | CLI가 출력하는 사유를 그대로 전달 |
| `POPULATE_EXIT=2` | 코퍼스 파일을 못 찾음 | 작업 디렉터리 확인 — 화면의 `콘텐츠 코퍼스 없음:` 경로 전달 |
| `AFTER_TOTAL`이 846이 아님 | 부분 적재 | 화면 전체 전달(값 자체가 정보다) |

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop · `whymath-pg` 컨테이너(호스트 포트 **5433**) · `src\backend\.venv`
- **DB**: prod = docker `whymath-pg`(5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**새 PowerShell 창 하나에서 끝난다.** 서버를 띄우지 않으므로 점유되는 창이 없다.
SKB-03 게이트를 같은 창에서 이어서 실행해도 된다.

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
git diff --quiet origin/main -- "src/backend/whymath_backend/l1/concept_content" "data/corpus/concept_content_v1/content.json" "data/corpus/concept_content_university_v1/content.json"
"PATHS_MATCH_MAIN=" + ($LASTEXITCODE -eq 0)
"----- BEFORE (읽기 전용) -----"
$BeforeTotal = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content;"
"BEFORE_TOTAL=$BeforeTotal"
$BeforeK12 = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content WHERE scope = 'K-12';"
"BEFORE_K12=$BeforeK12"
$BeforeUniv = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content WHERE scope = '대학';"
"BEFORE_UNIV=$BeforeUniv"
```

**확인**: `PATHS_MATCH_MAIN=True`. 세 BEFORE 값은 그대로 기록해 전달한다(대학 행의 존재 여부가
여기서 처음 실측된다).

### [C] 환경 + 도달성

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
"PY_OK=" + (Test-Path $Py)
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**확인**: `PY_OK=True` · `REACH_EXIT=0`.

### [D] 적재 (여기서만 DB에 쓴다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
& $Py -m whymath_backend.l1.concept_content.populate
"POPULATE_EXIT=$LASTEXITCODE"
```

**확인**: `POPULATE_EXIT=0`, 그리고 stdout 세 줄(`콘텐츠 적재: …` 2줄 + `콘텐츠 적재 완료: 총 …`).
그 줄들을 통째로 복사해 전달한다.

### [E] AFTER 카운트

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$AfterTotal = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content;"
"AFTER_TOTAL=$AfterTotal"
$AfterK12 = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content WHERE scope = 'K-12';"
"AFTER_K12=$AfterK12"
$AfterUniv = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content WHERE scope = '대학';"
"AFTER_UNIV=$AfterUniv"
$WithAtoms = docker exec -i whymath-pg psql -U whymath -d whymath -t -A -c "SELECT count(*) FROM concept_content WHERE atom_codes <> '{}';"
"AFTER_WITH_ATOMS=$WithAtoms"
"JUDGED_AGAINST_MAIN=" + (git rev-parse --short origin/main)
```

**확인**: `AFTER_TOTAL=846` · `AFTER_K12=437` · `AFTER_UNIV=409`, 그리고 CLI가 찍은 두 건수와 일치.

`AFTER_WITH_ATOMS`는 **0이 정상**이다 — `atom_codes`는 이 CLI가 아니라 크로스워크 이전
(`concept_atom_crosswalk.populate`)이 채운다. 그 이전은 대상 행이 없어 2026-09-14에 0건으로
끝났으므로, 행이 생긴 지금 **한 번 더 돌려야** 채워진다(§8 참조).

---

## 7. 게이트 clear 방법

Kiki가 할 일은 위 판정값들을 세션에 전달하는 것까지다. 대장 조작(`backlog.py gates clear`)은
세션이 가져간다 — `--evidence`에 판정 기준 커밋 해시가 들어가야 한다(HARN-68).

전달할 값: `DOCKER_OK` · `PATHS_MATCH_MAIN` · `BEFORE_TOTAL`/`BEFORE_K12`/`BEFORE_UNIV` ·
`REACH_EXIT` · `POPULATE_EXIT` · CLI의 `콘텐츠 적재` 3줄 · `AFTER_TOTAL`/`AFTER_K12`/`AFTER_UNIV` ·
`AFTER_WITH_ATOMS` · `JUDGED_AGAINST_MAIN`.

## 8. 이 런북이 답하지 못하는 것 (정직 고지)

- **L4 공급이 실제로 살아나는지는 이 실행으로 증명되지 않는다.** `content_supply`의
  `dsl_render_rate`(Wilson 하한 포함)가 올라갈 것이 기대되지만, 실제 학생 요청을 흘려야 안다 —
  별도 측정이다.
- **`atom_codes` 재전파가 남는다.** 행이 생긴 뒤 `concept_atom_crosswalk.populate`를 한 번 더
  돌려야 K-12 437행의 `atom_codes`가 채워진다. SKB-03 런북 §8이 같은 형태의 후속을 예고하므로,
  두 게이트를 모두 실행한 뒤 **크로스워크를 한 번만 재실행하면 두 축이 함께 해소된다.**
- **콘텐츠 품질·검수 상태는 이 실행의 범위가 아니다** — 코퍼스의 `review_status`를 그대로 적재할
  뿐이며, 검수 게이팅을 쓰는 경로에서 무엇이 노출 가능한지는 별건이다.
- **대학 409행의 소비처는 확인하지 않았다** — K-12 437행의 소비처 3곳(`content_supply`·
  `age_band_explanation`·`api/concepts`)만 실측했다.
