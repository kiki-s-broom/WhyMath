# G-eos63 — `attempt_event.skill_ids` 기록률 실측 회차 (Kiki 실행 런북)

> 이 문서는 게이트 **`G-eos63-skill-event-reach-sample`**(kiki·2026-09-01 등재)의 실행 절차다.
> 게이트가 풀리면 `EOS-63-attempt-skill-event-consumption`(P1)의 차단이 해제된다.
>
> **판정 기준: main `4abacdce`(2026-09-08 재확인)** — 아래 명령·플래그·기본값·경로는 전부 그
> 커밋의 코드에서 확인했다(`attempt_skill_event_reach_report.main()` 인자 정의 ·
> `config.Settings.database_url` 기본값과 `WHYMATH_` 접두 · `scripts/demo/run_demo.ps1`의 DB URL
> 규약 · `attempt_skill_reach_probe`의 exit 표).
>
> **갱신(2026-09-08)**: 최초 작성(main `3a30244c`) 시점에는 프로브(`attempt_skill_reach_probe`)가
> main에 없어 [1단계]가 그 사실을 스스로 판정해 폴백 브랜치를 고르게 돼 있었다. 그 프로브는
> **main에 착지했고 폴백 브랜치(`claude/skill-event-reach-sample-ec2w3b`)는 삭제됐다**(실측:
> `git cat-file -e origin/main:src/backend/whymath_backend/harness/attempt_skill_reach_probe.py`
> → 존재 · `git ls-remote --heads origin claude/skill-event-reach-sample-ec2w3b` → 0건). 삭제된
> ref를 fetch하면 Kiki 화면에 해석 불가한 오류가 뜨므로 [1단계]에서 그 분기를 제거했다 —
> 이제 main만 본다. (CLAUDE.md 「검증 없는 실행 안내 금지」: 안내 전 실재를 실측한다)

---

## 1. 과제 명칭

`문제시도` 이벤트 **스킬 배열 기록률 라이브 1회차 실측** — "좌석과 writer를 만들었다"와
"작동한다"를 실측으로 가른다.

## 2. 목적

`EOS-63`은 스킬 축 롤업을 **런타임 재해소** 대신 **기록된 사실**(`attempt_event.skill_ids`)을
읽도록 바꾸는 태스크다. 그 전환에는 딱 한 가지 선결 조건이 있다 —

> 기록이 실제로 쌓이고 있는가? **기록 0건 상태에서 소비를 바꾸면 스킬 숙달 전파가 죽는다.**

그 수치는 **실 PG의 실제 채점 이력**이 분모라서 CI에서는 원리적으로 나오지 않는다(매 잡의 DB가
비어 있다). 그래서 사람이 Phaiakes9에서 1회 돌려야 하고, 그것이 이 게이트다.

산출은 리포트의 **3분류**(미도달 / 해소 0건 / 해소 ≥1)와 **해소율**이며, 그것이 EOS-63
acceptance ②의 유일한 판정 재료다.

### 왜 리포트만 돌리면 안 되는가 (이 런북에 프로브가 있는 이유)

리포트는 **관측만** 한다. Phaiakes9의 prod DB에 EOS-57 writer 착지(2026-08-30) *이후*의 채점이
없으면 전 지표가 `측정 불가(분모 0)`로 나오고, 회차가 통째로 공전한다. 그래서 이 런북은
**표본을 만드는 단계**를 앞에 둔다. 프로브는 `record_attempt_skill_event`를 직접 부르지 않고
**실제 `POST /v1/me/attempts` 라우트**를 in-process로 태운다 — 직접 호출하면 도달률이 구성상
100%가 되어 측정이 아니라 동어반복이 되기 때문이다.

## 3. 구체적 절차

| 단계 | 무엇이 일어나는가 | 예상 출력 | 소요 |
|---|---|---|---|
| ① 체크아웃 | main으로 detached 이동(지역 브랜치 무변경) | `PROBE_FILE_OK=True` | ~20초 |
| ② 환경 | UTF-8 콘솔 + prod DB URL 주입 + import 확인 + **도달성 CLI**(OPS-72) | `REACH_EXIT=0` | ~15초 |
| ③ 사전 관측 | 지금 DB에 무엇이 있는지 읽는다(**쓰기 0**) | 리포트 마크다운 | ~10초 |
| ④ 표본 생성 | 채점 20건을 실제 라우트로 제출 | 회차 요약 + `work\eos63\probe.json` | 1~3분 |
| ⑤ 사후 측정 | 프로브 회차 창으로 리포트 재실행 | 리포트 + `work\eos63\report.json` | ~10초 |
| ⑥ 자가검증 | 창 안 이벤트 수·해소율을 뽑아 출력 | `EVENTS=..` `E2E_RATE=..` | 즉시 |

**쓰기가 남는다(의도)**: ④는 prod DB에 채점 행을 남긴다 — 남지 않으면 ⑤가 볼 것이 없다.
행은 전부 프로브 전용 고정 사용자
`c5de83b3-9143-58e8-a7a8-cf378801c065` 소유라 사후 식별·정리가 user_id 하나로 끝난다(§7).

## 4. 성공 기준

**판정은 리포트의 수치로 한다.** 프로브의 exit code는 *회차가 성립했는가*만 말한다.

### 성공

⑥의 자가검증이 `EVENTS≥1`을 내면 이 게이트가 요구한 실측은 성립한다. 그 다음 해소율을 읽는다:

| 관측 | 뜻 | EOS-63에 주는 판정 |
|---|---|---|
| 해소 ≥1이 다수 | concept→skill 브리지가 산다 | **전환 가능** — 수치를 EOS-63 notes에 남기고 착수 |
| 전부 `해소 0건`(`[]`) | writer는 돌았고 **매핑 데이터가 비었다** | 전환 보류 — 대책은 코드가 아니라 **브리지 데이터 보강** |
| `이벤트 있으나 skill_ids NULL`이 0이 아님 | **병리** — 이 컬럼을 NULL로 쓰는 다른 경로가 생겼다 | 조사 태스크 등재 |

`coach_completion` 행이 `0`인 것은 **정상**이다 — 프로브가 그 경로를 태우지 않는다(코치 대화
완료 경로). "0으로 보이는 것"과 "죽은 것"을 여기서 혼동하지 않는다.

### 실패 — 프로브 exit code별 대처 (전부 서로 다른 번호다)

| exit | 뜻 | 대처 |
|---:|---|---|
| 2 | DB 미도달 | ②의 도달성 CLI(`REACH_EXIT`)가 먼저 잡는다 — 컨테이너 생존이 아니라 **실제 TCP 연결 성립**을 판정한다(§[2단계] 대처) |
| 3 | **스키마 뒤처짐** — `attempt_event.skill_ids` 부재 | §6의 마이그레이션 블록을 1회 실행 후 ④부터 재개 |
| 4 | 후보 문제 0건 | 코퍼스 미적재 — **시드 대상 DB가 prod임을 알고** 적재할지 정한다(§7-2에 두 갈래의 재료). 적재하지 않으면 이 회차는 여기서 끝나고, 그 사실 자체가 측정 결과다 |
| 5 | 제출 전건 실패 | 화면의 「실패 사유」 표(예외 타입명)를 그대로 세션에 전달 |

`해소율 0%`는 **실패가 아니라 측정값**이다(exit 0). 그 경우도 게이트는 닫힌다 — 닫히지 않는 것은
*측정이 안 된 경우*뿐이다.

> **단, exit 4(후보 문제 0건)는 다르다.** 그것은 해소율이 0인 것이 아니라 **분모를 만들 수조차
> 없는** 상태다 — 측정이 성립하지 않았으므로 게이트를 닫는 근거가 되지 못한다. 문항을 적재해
> 분모를 만들지, 아니면 그 상태를 그대로 보고할지는 **사람의 판단**이며(§7-2에 두 갈래의 재료가
> 있다), 세션이 대신 정하지 않는다.
>
> **실제 진행(2026-09-10)**: 적재 후 회차를 완주해 `RESOLUTION=0.0`을 얻었고, 그 0%는 위 표의
> "전부 해소 0건" 행 — 즉 **브리지 데이터가 비었다**는 판정이다. 게이트는 그 증적으로 clear됐고
> 근본원인은 `SKB-01-skill-concept-bridge-prod-populate`가 소유한다.

## 5. 실행 환경

- **머신**: Phaiakes9(= Kiki의 작업 PC 그 자체 · 별도 접속 없음)
- **시스템**: Windows PowerShell (WSL 아님)
- **작업 디렉터리**: `C:\Users\kiki\Desktop\__AI\WhyMath`
- **선행 조건**: Docker Desktop 실행 중 · `whymath-pg` 컨테이너(호스트 포트 **5433**) 가동 ·
  `src\backend\.venv` 세팅 완료
- **DB**: prod DB = docker `whymath-pg` (5433). 데모용 55432·타 프로젝트 5432와 혼동 금지.

## 6. 창 구분

**전 단계가 같은 창 하나에서 끝난다.** 서버(uvicorn)를 띄우지 않으므로 점유 창이 없고, 창을
나눌 이유도 없다. 새 PowerShell 창 하나를 열고 아래 블록을 순서대로 붙여넣는다.

---

## 실행 블록

> 아래 블록은 **자리표시자가 하나도 없다**. 그대로 통째로 붙여넣으면 된다.
> 각 블록 끝의 자가검증 줄이 **실패 상태에서 다른 값을 낸다** — 그 값을 보고 다음 블록으로 간다.

### [1단계] 체크아웃 — main으로 detached 이동(지역 브랜치 무변경)

```powershell
# [Windows PowerShell · Phaiakes9]
cd C:\Users\kiki\Desktop\__AI\WhyMath
# 작업 트리 청결부터 확인한다 — 더러우면 아무것도 하지 않는다.
# (붙여넣기 실행에서는 `throw`가 뒤 줄을 멈추지 못하므로 뒷부분을 통째로 가드로 감싼다.)
# `--untracked-files=no`가 핵심: untracked 파일은 체크아웃을 막지도 덮어쓰지도 않는데,
# 그것까지 세면 위험하지 않은 상태에서 블록이 멈춘다(2026-09-08 실측 — `reports/`와
# `ruleset*.json` 5건 때문에 회차가 한 번 공전했다). 위험한 것은 *추적 중인* 변경뿐이다.
$Dirty = (git status --porcelain --untracked-files=no)
"TRACKED_DIRTY=" + [bool]$Dirty
if (-not $Dirty) {
  # 지역 브랜치는 손대지 않는다 — detached HEAD로만 옮긴다. `checkout -B`는 지역 브랜치
  # 포인터를 원격 tip으로 *강제 이동*시켜 아직 push하지 않은 지역 커밋을 그 브랜치에서
  # 도달 불가로 만든다. 위 청결 검사로는 그 상태가 잡히지 않는다(트리는 깨끗하니까).
  $Branch = (git rev-parse --abbrev-ref HEAD)
  "RETURN_TO=$Branch"
  git fetch origin main
  $ProbeRel = "src/backend/whymath_backend/harness/attempt_skill_reach_probe.py"
  git checkout --detach origin/main
  git log --oneline -1
  "PROBE_FILE_OK=" + (Test-Path (Join-Path (Get-Location) $ProbeRel))
}
```

**자가검증**: `TRACKED_DIRTY=False` **그리고** `PROBE_FILE_OK=True`.
`RETURN_TO=`에 찍힌 이름은 회차가 끝난 뒤 돌아갈 브랜치다(§7-4). 이 블록은 **지역 브랜치를
전혀 바꾸지 않는다** — detached HEAD로만 이동하므로 push하지 않은 지역 커밋이 안전하다.
- `TRACKED_DIRTY=True`면 추적 중인 미커밋 변경이 있어 블록이 **아무것도 하지 않은 것**이다(의도) —
  그 변경을 어떻게 할지 세션에 물은 뒤 다시 온다.
- `PROBE_FILE_OK=False`면 fetch가 실패했거나(네트워크) main에서 프로브가 사라진 것이다 —
  다음 단계로 가지 말고 세션에 알린다. 이 검사는 변별력이 있다: 파일이 없으면 `False`가 뜬다.

### [2단계] 환경 — UTF-8 + prod DB + **도달성 판정**(OPS-72 CLI)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:WHYMATH_DATABASE_URL = "postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
# 이 창은 저장소 루트에 있는데 `-m whymath_backend...`는 패키지가 venv에 설치돼 있어야 풀린다.
# 설치돼 있으면 이 줄은 무해하고(같은 코드를 가리킨다), 안 돼 있으면 이 줄이 해결한다 —
# "설치돼 있을 것이다"라는 가정 자체를 없앤다.
$env:PYTHONPATH = (Resolve-Path "src\backend").Path
$Py = "src\backend\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path work\eos63 | Out-Null
"PY_OK=" + (Test-Path $Py)
# 여기서 `import whymath_backend`만 하면 **아무것도 검증하지 못한다** — 그 패키지의
# `__init__.py`에는 무거운 import가 하나도 없어(문서 문자열 + `__version__`뿐) SQLAlchemy·
# Pydantic이 없어도 통과한다. 게다가 위 PYTHONPATH가 발견 가능성까지 보장해 준다. 그래서
# **3~6단계가 실제로 부르는 모듈들**을 직접 import한다. 프로브의 ASGI 의존(`TestClient`·
# `create_app`)은 함수 안 지연 import라 모듈 import로도 안 잡히므로 따로 세운다.
& $Py -c "import whymath_backend.harness.attempt_skill_event_reach_report, whymath_backend.harness.attempt_skill_reach_probe, whymath_backend.app; from fastapi.testclient import TestClient; print('IMPORT_OK=True')"
"IMPORT_EXIT=$LASTEXITCODE"
# 도달성 판정은 여기서 손으로 하지 않는다 — 전용 CLI가 정본이다(OPS-72). 컨테이너 생존
# (docker ps)은 *간접* 신호일 뿐이고, 2026-09-08에는 컨테이너가 Up이고 pg_isready도 통과하는데
# 호스트에서만 못 붙는 상태가 실재했다. 이 CLI는 설정(HostConfig.PortBindings)과 실현
# (NetworkSettings.Ports)과 실제 TCP 연결을 각각 읽어 6상태로 가르고 대책까지 출력한다.
& $Py -m whymath_backend.ops.db_host_reachability
"REACH_EXIT=$LASTEXITCODE"
```

**자가검증**: `PY_OK=True` · `IMPORT_OK=True`(그리고 `IMPORT_EXIT=0`) · **`REACH_EXIT=0`**.
- `IMPORT_OK`가 안 찍히고 `IMPORT_EXIT=1`이면 의존성 미설치다(ModuleNotFoundError의 *대상*이
  화면에 찍힌다 — 그 이름을 세션에 전달한다). 3단계로 가면 같은 실패를 DB 오류처럼 보게 되므로
  여기서 멈추는 것이 맞다.
- **`REACH_EXIT=1`이면 DB에 못 붙는다.** CLI가 어떤 상태인지(`NOT_PUBLISHED`·`NO_BINDING`·
  `PUBLISHED_BUT_CLOSED`·`FOREIGN_LISTENER`)와 그에 맞는 대책을 함께 출력하므로 그대로 따른다.
  Windows 포트 예약 축의 영구 조치는 `/demo-doctor` 카탈로그 **§W1**에 있다.
- **`REACH_EXIT=2`는 고장이 아니라 측정 불가**다(docker 미가동 등). 화면의 `측정 사유 기록`을
  먼저 해소한다 — 이것을 도달 불가로 읽으면 엉뚱한 곳을 파게 된다.

> **`$LASTEXITCODE`를 단독 판정으로 쓰지 않는다**: 이 변수는 *외부 실행 파일이 실제로 돌았을 때만*
> 갱신된다. 명령이 파싱 오류 등으로 시작조차 못 하면 **이전 값이 그대로 남아 성공처럼 보인다**
> (2026-09-08 실측 — 실패한 명령 뒤에 `REPORT_EXIT=0`이 찍혔다). 그래서 아래 단계들은 exit code와
> **산출물 파일의 실재**를 함께 본다. CLAUDE.md 「래퍼가 종료 코드를 가림」 축의 PowerShell 변형이다.

### [3단계] 사전 관측 (읽기 전용 — DB에 아무것도 쓰지 않는다)

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
# 이전 회차 잔재를 먼저 지운다 — 안 지우면 옛 파일이 이번 결과인 척한다
# (CLAUDE.md 「지금 보는 것이 이번 실행 것인가」).
Remove-Item work\eos63\probe.json, work\eos63\report.json -ErrorAction SilentlyContinue
"===== 3. 사전 관측 (읽기 전용) ====="
& $Py -m whymath_backend.harness.attempt_skill_event_reach_report --json work\eos63\before.json
"BEFORE_EXIT=$LASTEXITCODE"
"===== 4. 표본 생성 20건 (여기서만 DB에 쓴다) ====="
& $Py -m whymath_backend.harness.attempt_skill_reach_probe --count 20 --json work\eos63\probe.json
"PROBE_EXIT=$LASTEXITCODE"
if (Test-Path work\eos63\probe.json) {
  "===== 5. 사후 측정 ====="
  $Since = (Get-Content work\eos63\probe.json -Raw | ConvertFrom-Json).started_at
  "SINCE=$Since"
  & $Py -m whymath_backend.harness.attempt_skill_event_reach_report --since $Since --json work\eos63\report.json
  "REPORT_EXIT=$LASTEXITCODE"
  if (Test-Path work\eos63\report.json) {
    $R = Get-Content work\eos63\report.json -Raw | ConvertFrom-Json
    $P = Get-Content work\eos63\probe.json  -Raw | ConvertFrom-Json
    "===== 6. 게이트 증적 ====="
    "WINDOW=$($R.since)"
    "ATTEMPTS=$($R.attempts_total)  EVENTS=$($R.events_total)"
    "EMPTY=$($R.events_empty_skill_ids)  NONEMPTY=$($R.events_nonempty_skill_ids)  NULL=$($R.events_null_skill_ids)"
    "WRITER_REACH=$($R.writer_reach_rate)  RESOLUTION=$($R.resolution_rate)  E2E=$($R.end_to_end_rate)"
    "PROBE_ACCEPTED=$($P.accepted)  PROBE_FAILED=$($P.failed)"
    git log --oneline -1
  } else { "REPORT_JSON_MISSING=True -- 사후 측정 실패. 화면의 오류 줄을 세션에 전달한다" }
} else { "PROBE_JSON_MISSING=True -- 표본 생성 실패. 위 PROBE_EXIT 숫자를 세션에 전달한다" }
```

**왜 한 블록인가**: 3~6단계를 따로 두었더니 회차 하나가 **4단계를 통째로 건너뛴 채 5단계로
넘어가** 공전했다(2026-09-08 실측). 붙여넣기 실행에서는 순서를 사람이 지켜 주지 않으므로,
순서를 **가드가 강제**하게 한다 — 앞 단계 산출물이 없으면 뒷 단계가 아예 돌지 않는다.

**판정은 exit code가 아니라 산출물 파일의 실재로 한다** — 위 §[2단계] 말미의 `$LASTEXITCODE`
경고 참조. `Test-Path`는 실패 상태에서 실제로 `False`를 내므로 변별력이 있다.

**성공 판정**: `===== 6. 게이트 증적 =====` 아래 6줄이 출력되고 `EVENTS`가 1 이상.
그 6줄과 마지막 커밋 줄을 **그대로 복사해 세션에 전달**한다 — 그것이 게이트 증적이다.

**멈춘 지점별 대처**:
- `PROBE_JSON_MISSING=True` → `PROBE_EXIT` 숫자가 원인을 가른다(§4의 exit 표).
  **`4`(후보 문제 0건)는 §7-2로 간다 — 시드 대상이 prod임을 알고 적재 여부를 정한다.**
- `REPORT_JSON_MISSING=True` → 사후 측정이 실패했다. 화면의 예외 타입명을 전달한다.

---

## 7. 보조 블록 (필요할 때만)

### 7-1. exit 3(스키마 뒤처짐)이 났을 때 — 마이그레이션 1회

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
cd C:\Users\kiki\Desktop\__AI\WhyMath\src\backend
& .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
"EXIT=$LASTEXITCODE"
cd C:\Users\kiki\Desktop\__AI\WhyMath
```

`EXIT=0`을 확인한 뒤 [4단계]부터 재개한다.

### 7-2. exit 4(후보 문제 0건)가 났을 때 — 시드 대상 DB를 먼저 확인한다

> **먼저 알아야 할 사실(실측)**: `scripts/demo/seed_demo.py`는 `WHYMATH_DATABASE_URL`을 그대로
> 쓴다. 이 런북의 [2단계]가 그 변수를 **prod(5433)** 로 설정하므로, 같은 창에서 그대로 돌리면
> 문항 코퍼스 3종(손저작 4 + 단답 620 + 객관식 1,080)이 **prod에 적재된다**. 이름이 `demo`라
> 데모 DB로 갈 것 같지만 아니다 — 이 한 줄을 모르고 돌리는 것과 알고 돌리는 것은 다르다.

**그래서 무엇을 할 것인가는 사람의 판단이다.** 이 런북은 그 판단을 대신하지 않고 재료만 준다:

- **적재해도 되는가** — 문항 코퍼스는 우리 자체 생성물이고 prod가 원래 갖고 있어야 할 콘텐츠다.
  `scripts/demo/PILOT_RUNBOOK.md`의 DB 선택 표에 *"B. prod 오버라이드 — 데모 시드가 prod에
  섞임 — 미채택"*(2026-07-26)이 있지만, **그 결정은 파일럿 KPI용 영속 DB를 어디에 둘지**를
  정한 것이지 코퍼스 적재 일반을 금지한 것이 아니다. 범위를 넓게 읽지 않는다.
  *(2026-09-09 이 문서가 그 결정을 '전면 금지'로 읽어 회차를 중단시킨 적이 있다 — 그 판단은
  과했고 다음 날 회차가 그대로 진행돼 유효한 실측을 냈다.)*
- **무엇이 남는가** — 프로브가 만드는 채점 행은 고정 사용자
  `c5de83b3-9143-58e8-a7a8-cf378801c065` 소유라 §7-3으로 정리된다. 문항 코퍼스는 남는다.

적재를 택했다면:

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 이 명령은 위 $env:WHYMATH_DATABASE_URL이 가리키는
# DB(=이 런북 기준 prod 5433)에 문항을 적재한다. 대상이 맞는지 확인한 뒤 실행한다.
$env:WHYMATH_DATABASE_URL
& $Py scripts\demo\seed_demo.py
"EXIT=$LASTEXITCODE"
```

`EXIT=0`을 확인한 뒤 위 통합 실행 블록을 처음부터 다시 돌린다(가드가 순서를 강제하므로 중간
재개는 없다).

적재하지 않기로 했다면 **이 회차는 여기서 끝난다** — 후보 문제 0건은 고쳐야 할 오류가 아니라
*측정 결과*이기도 하다. 아래 읽기 전용 전수 카운트를 증적으로 남기고 세션에 전달한다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창 — 읽기 전용 전수 카운트
docker exec -i whymath-pg psql -U whymath -d whymath -v ON_ERROR_STOP=1 -c "SELECT 'problem' AS t, count(*) AS n FROM problem UNION ALL SELECT 'problem_with_difficulty', count(*) FROM problem WHERE difficulty_overall IS NOT NULL UNION ALL SELECT 'problem_attempt', count(*) FROM problem_attempt UNION ALL SELECT 'attempt_event', count(*) FROM attempt_event UNION ALL SELECT 'user_profile', count(*) FROM user_profile UNION ALL SELECT 'concept', count(*) FROM concept ORDER BY 1;"
"EXIT=$LASTEXITCODE"
```

**회차 이력(다시 돌리는 세션이 먼저 읽을 것)**

| 날짜 | 결과 |
|---|---|
| 2026-09-09 (main `94d1f28a`) | `problem` 0 · `problem_attempt` 0 · `attempt_event` 0 · `concept` 2,683 · `user_profile` 2 — 문항이 없어 프로브가 exit 4로 멈췄다 |
| 2026-09-10 (PR #1079) | 회차 완주 — `ATTEMPTS=20 EVENTS=20 WRITER_REACH=1.0 RESOLUTION=0.0 E2E=0.0`. **기록 배선은 완벽하고 해소율이 0%**였다. 원인은 `skill_node` 0행 · `concept.behavior_skills` 전량 빈 배열(2,683/2,683) — 코드가 아니라 **브리지 데이터 미적재**다. 게이트는 이 증적으로 clear됐고 근본원인은 `SKB-01-skill-concept-bridge-prod-populate`가 소유한다 |

즉 **이 게이트는 이미 닫혔다.** 이 런북을 다시 쓰는 경우는 SKB-01 적재 후 재검증(그 태스크
acceptance ④)이며, 그때 기대값은 "해소율이 0%를 벗어나는가"다.

### 7-3. 표본 정리 (선택 — **게이트를 닫은 뒤에만**)

> ⚠ 이 블록은 **측정한 표본을 지운다**. 게이트 증적(§6의 6줄)을 세션에 전달하기 *전에*
> 돌리면 재측정해야 한다. 지우지 않아도 무해하다 — 프로브 사용자 한 명의 행일 뿐이다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
$U = "c5de83b3-9143-58e8-a7a8-cf378801c065"
docker exec -i whymath-pg psql -U whymath -d whymath -v ON_ERROR_STOP=1 -c "DELETE FROM attempt_event WHERE user_id='$U'; DELETE FROM skill_mastery_history WHERE user_id='$U'; DELETE FROM concept_mastery_history WHERE user_id='$U'; DELETE FROM problem_attempt WHERE user_id='$U'; DELETE FROM user_profile WHERE user_id='$U';"
"EXIT=$LASTEXITCODE"
```

---

### 7-4. 회차 후 원래 브랜치로 복귀

[1단계]가 detached HEAD로 옮겨 두었으므로, 끝나면 원래 자리로 돌아온다.

```powershell
# [Windows PowerShell · Phaiakes9] 같은 창
if ($Branch -and $Branch -ne "HEAD") { git checkout $Branch } else { git checkout main }
git status --short --branch
```

`$Branch`는 [1단계]가 같은 창에 남긴 값이다. 창을 새로 열었다면 `git checkout main`으로
돌아오면 된다(지역 커밋은 손대지 않았으므로 그대로 있다).

---

## 8. 게이트 clear 방법

**Kiki가 할 일은 §6의 6줄을 세션에 전달하는 것까지다.** 대장 조작(`backlog.py gates clear`)은
세션이 가져간다 — 이 문서에 그 명령을 붙여넣기 블록으로 두지 않는 이유는, 증적 문자열이
자리표시자를 포함할 수밖에 없어 그대로 실행되면 잘못된 증적이 대장에 박히기 때문이다.

세션 쪽 참고: `gates clear`의 `--evidence`에는 **판정 기준(커밋 해시 또는 PR 참조)**이 반드시
들어가야 한다(HARN-68 — 없으면 CLI가 exit 1로 거부한다). 증적 본문은 §6의 6줄 + 프로브가
돌아간 커밋 해시 + `WINDOW` 값으로 구성한다.

## 9. 이 회차가 답하지 못하는 것 (정직 고지)

- **유기적 트래픽의 writer 도달률이 아니다.** 표본을 프로브가 만들었으므로 배선이 살아 있으면
  도달률은 100%다. 그 100%가 증명하는 것은 "`attempt_submit` 경로의 writer 배선이 이 DB에서
  실제로 작동한다"까지이고, "학생들이 쓰고 있다"가 아니다.
- **`coach_completion` 경로는 미측정이다.** 리포트의 그 행이 0인 것은 죽었다는 뜻이 아니라
  이 회차가 태우지 않았다는 뜻이다. 그 경로의 실측은 실기기·코치 대화 회차가 필요하다.
- **해소율은 이 DB의 브리지 데이터에 대한 값이다.** 코퍼스가 바뀌면 값도 바뀐다 — 그래서
  증적에 판정 기준 커밋과 창(`WINDOW`)을 함께 남긴다.
