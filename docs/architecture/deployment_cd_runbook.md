# WhyMath 배포·CD 런북 — OPS-03

> 대상: `docker-compose.prod.yml`(app + PostgreSQL 16/pgvector + Redis 7) 스택.
> 시연용 `docker-compose.demo.yml`(trust 인증·볼륨 없음·55432·`whymath-demo-db`)과 **역할이 정반대다** — 혼동 금지.
> 배포 env 파일(`deploy/staging.env`·`deploy/prod.env`)은 **ASCII 전용 템플릿**(`.env.prod.example`)에서 만들고, 실 값은 절대 커밋하지 않는다(`.gitignore`의 `*.env`가 이미 막는다 — 2026-07-26 `git check-ignore` 실측).
> **읽기 전 주의**: 프로덕션 클라우드(GCP/AWS) 호스트는 아직 **미프로비저닝**이다. 이 문서의 §1~§6은 도커가 도는 단일 호스트(현재 Phaiakes9)에서 그대로 실행 가능한 절차이고, GitHub Actions 자동 배포(`.github/workflows/deploy.yml`)는 **대상이 생기기 전까지 preflight에서 명시 실패**한다(§8).

---

## 사전 브리핑 (CLAUDE.md 6항목 템플릿)

1. **과제 명칭** — WhyMath 백엔드 컨테이너 배포(스테이징/프로덕션 스택 기동·갱신·롤백).
2. **목적** — 지금까지 백엔드 실행은 시연 스크립트(`run_demo.ps1`: 일회용 DB + 개발 uvicorn)뿐이라 "운영으로 올린다"는 경로가 없었다. 이 런북은 ①영속 볼륨·비밀번호 인증을 갖춘 스택을 띄우고 ②새 코드로 갱신하고 ③문제가 나면 **되돌리는** 절차를 고정한다. 결과물은 `whymath-<env>-app` / `-db` / `-redis` 컨테이너 3종과 영속 볼륨 2종.
3. **구체적 절차** — §0 브랜치 준비(1분) → §1 배포 env 파일 생성·자가검증(5분) → §2 이미지 빌드(첫 회 5~10분, 이후 캐시로 단축) → §3 최초 배포: 마이그레이션 → 기동(3분) → §4 배포 검증(1분) → §5 갱신 배포(§2~§4 반복) → §6 롤백(5분). §7은 GitHub 시크릿 등록(자동 배포를 켤 때만).
4. **성공 기준** — 각 단계 블록에 자가검증 스텝과 성공/실패 판별, 실패 시 대처 1개를 병기했다. 총괄 기준: §4에서 컨테이너 상태가 `healthy`이고 `/health/live`가 200, `/health/ready`가 200(DB 도달). 실패는 침묵하지 않는다 — 값이 하나라도 비면 compose가 **기동을 거부**하며 어느 변수가 비었는지 출력한다(fail-closed).
5. **실행 환경** — **Windows PowerShell**(= Phaiakes9 이 PC 자체 · SSH 불요), 작업 디렉터리 `C:\Users\kiki\Desktop\__AI\WhyMath`. 선행 조건: Docker Desktop 실행 중. 호스트에 Python은 §1 키 생성에만 쓴다(`run_demo.ps1`이 쓰는 것과 같은 `python`).
6. **창 구분** — **새 PowerShell 창 1개**로 전 절차 수행 가능. 장기 점유 프로세스가 없다(컨테이너는 전부 `-d` 분리 실행이라 창을 잡지 않는다) → 서버 점유 창 분리 규칙 해당 없음. 단, `run_demo.ps1` 시연 서버가 돌고 있는 창은 그대로 두고 **별도 창**을 쓴다.

---

## §0. 사전 준비 — 브랜치 체크아웃 (미머지 브랜치 신규 파일)

`Dockerfile`·`docker-compose.prod.yml`은 미머지 브랜치에 있다. 재시작(force-push) 가능성이 있으므로 `fetch` + `checkout -B` 형식만 쓴다(pull 금지 — diverged 시 add/add 충돌).

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin
git checkout -B claude/whymath-service-review-9r21im origin/claude/whymath-service-review-9r21im

# 자가검증: 배포 산출물 3종이 모두 True 여야 함
Test-Path .\Dockerfile
Test-Path .\docker-compose.prod.yml
Test-Path .\.env.prod.example
```

- **성공**: 세 줄 모두 `True`. (변별력: 이 파일들은 이 브랜치에만 있어 체크아웃 실패 시 실제로 `False`가 나온다.)
- **실패 시 대처**: `git branch --show-current`로 현재 브랜치를 확인하고 위 두 줄을 재실행.

## §1. 배포 env 파일 생성 (환경별 1회) — 시크릿은 여기에만 존재한다

`staging`과 `prod`는 **같은 compose 파일 + 다른 env 파일**로 갈린다(토폴로지 이중화로 인한 드리프트 방지 — 근거는 `docker-compose.prod.yml` 헤더 주석). 컨테이너·볼륨 이름에 `DEPLOY_ENV`가 박혀 한 호스트에 둘이 공존해도 서로의 데이터를 덮지 않는다.

### 1-1. 템플릿 복사 + 값 생성

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
New-Item -ItemType Directory -Force -Path .\deploy | Out-Null
Copy-Item .\.env.prod.example .\deploy\staging.env

# 값 생성 (DB/Redis 비밀번호는 DSN URL에 들어가므로 URL-safe hex, 암호화 키는 base64 32바이트)
python -c "import secrets;print('DB   ', secrets.token_hex(24))"
python -c "import secrets;print('REDIS', secrets.token_hex(24))"
python -c "import secrets;print('JWT  ', secrets.token_hex(32))"
python -c "import base64,os;print('DIALOG', base64.b64encode(os.urandom(32)).decode())"
python -c "import base64,os;print('DEVICE', base64.b64encode(os.urandom(32)).decode())"
python -c "import base64,os;print('STUDENT_WORK', base64.b64encode(os.urandom(32)).decode())"
```

> **SEC-36 (2026-09-27)**: `WHYMATH_STUDENT_WORK_ENCRYPTION_KEY`(학생 답안·풀이 본문 키)가 필수다 — 비어 있으면 compose가 기동을 거부한다. 실 운영 스택에는 카카오·네이버 OAuth 변수(`WHYMATH_KAKAO_CLIENT_ID` 등)도 채운다. 앱은 이 client_id로 '운영'을 판정하므로 둘 다 비면 운영 전용 안전장치가 꺼진다(템플릿 주석 참조).

출력된 값을 `notepad .\deploy\staging.env`로 열어 해당 키에 붙여넣는다. 함께 채울 값:

| 키 | staging 예 | prod 예 | 비고 |
|---|---|---|---|
| `DEPLOY_ENV` | `staging` | `prod` | 컨테이너·볼륨 이름을 가른다 |
| `COMPOSE_PROJECT_NAME` | `whymath-staging` | `whymath-prod` | 프로젝트 격리 |
| `WHYMATH_IMAGE_TAG` | §2에서 얻는 git short SHA | 동일 | **`latest` 금지** |
| `APP_PORT` | `18080` | `18081` | 서로 달라야 한 호스트 공존 가능. 5432/5433/55432/55433은 이미 사용 중이라 회피 |
| `APP_BIND_ADDR` | 비움(=127.0.0.1) | 비움 | LAN 노출이 필요할 때만 `0.0.0.0`(§8 트레이드오프) |

> **붙여넣기 사고 방지**: 생략 문자(`…`)나 잘린 값을 넣지 않는다. 아래 자가검증이 길이와 `…` 포함 여부를 검사한다(값은 출력하지 않는다).

### 1-2. 자가검증 — 값 채움 상태 (값 미출력)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$envFile = ".\deploy\staging.env"
$map = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
  $k, $v = $_ -split '=', 2
  $map[$k.Trim()] = $v
}
$required = 'DEPLOY_ENV','COMPOSE_PROJECT_NAME','WHYMATH_IMAGE_TAG','APP_PORT',
            'WHYMATH_DB_PASSWORD','WHYMATH_REDIS_PASSWORD','WHYMATH_JWT_SECRET_KEY',
            'WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY','WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY',
            'WHYMATH_STUDENT_WORK_ENCRYPTION_KEY'
foreach ($k in $required) {
  $v = $map[$k]
  $len = if ($null -eq $v) { -1 } else { $v.Length }
  $bad = ($len -le 0) -or ($v -match '…') -or ($v -match '\.\.\.') -or ($v -match 'PUT_REAL_VALUE_HERE')
  "{0,-42} len={1,-4} {2}" -f $k, $len, $(if ($bad) { 'FAIL' } else { 'OK' })
}
# 암호화 키 분리 확인 (한 키 유출이 다른 자산으로 번지지 않게) - 세 쌍 모두 달라야 True
$kd = $map['WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY']; $ks = $map['WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY']; $kw = $map['WHYMATH_STUDENT_WORK_ENCRYPTION_KEY']
($kd -ne $ks) -and ($kd -ne $kw) -and ($ks -ne $kw)
```

- **성공**: 10줄 전부 `OK`(비밀번호 48자, JWT 64자, base64 키 44자 근처) + 마지막 줄 `True`. 값은 화면에 나오지 않는다.
- **실패 시 대처**: `FAIL`이 난 키를 다시 붙여넣는다. `len`이 기대보다 짧으면 붙여넣기 절단이다 — 생성 명령을 다시 돌려 **전체**를 복사한다.
- **변별력 근거**: 이 검사는 형식만 본다. 최종 판정은 compose 자신이 한다 — 값이 비면 §3에서 **기동을 거부**한다. 그 fail-closed 동작은 CI(`docker-build` 잡의 "compose.prod fail-closed" 스텝)가 매 PR에서 실제로 검사한다(빈 env로 통과하면 CI가 실패).

## §2. 이미지 빌드 — 불변 태그

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
$tag = (git rev-parse --short HEAD)
"빌드 태그: $tag"
docker build -f Dockerfile -t whymath-backend:$tag .

# 자가검증 1: 종료코드 - True 여야 함
$LASTEXITCODE -eq 0
# 자가검증 2: 비루트 실행 계약 - "appuser" 여야 함
docker image inspect whymath-backend:$tag --format '{{.Config.User}}'
```

빌드가 끝나면 `deploy\staging.env`의 `WHYMATH_IMAGE_TAG=`에 그 태그 값을 적는다(불변 태그가 롤백의 유일한 좌표다).

- **성공**: 자가검증 1이 `True`, 2가 `appuser`.
- **실패 시 대처**: 빌드 로그 마지막 `ERROR` 줄을 본다. 흔한 원인 — Docker Desktop 미기동(`error during connect`) → Docker Desktop 실행 후 재시도.
- **주의**: 빌드 컨텍스트는 레포 루트다. 런타임 코드가 레포 상대 경로로 `data/corpus/**`를 읽기 때문에 `src\backend`만으로는 이미지가 성립하지 않는다(Dockerfile 헤더 주석에 근거 실측 위치 기재).

## §3. 최초 배포 — 마이그레이션 → 기동

마이그레이션은 **기동과 분리된 별도 스텝**이다(컨테이너 자동 마이그레이션 없음). 롤백 판단을 사람이 해야 하기 때문이다(§6).

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 3-1. 스키마 적용 (db·redis가 healthy가 될 때까지 compose가 먼저 기다린다)
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic upgrade head

# 자가검증: 현재 리비전 - "(head)" 표시가 있어야 함
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic current

# 3-2. 스택 기동
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml up -d

# 자가검증: 컨테이너 5종이 Up 상태여야 함
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml ps
```

- **성공**: `alembic current` 출력에 `(head)`, `ps`에 `whymath-staging-app`·`-db`·`-redis`·`-retention-purge`·`-quality-worker` 다섯 줄이 `Up`(app·quality-worker는 잠시 `starting`일 수 있다 — app은 §4, quality-worker는 §5c에서 확정).
- **실패 시 대처**:
  - `required variable ... is missing a value` → §1로 돌아가 그 변수를 채운다(이게 fail-closed 동작이다 — 정상 반응).
  - `password authentication failed` → 기존 볼륨이 다른 비밀번호로 초기화돼 있다. 볼륨을 그대로 쓰려면 §1의 `WHYMATH_DB_PASSWORD`를 그 볼륨의 값으로 맞추거나, 데이터를 버려도 되는 스테이징이면 `docker volume rm whymath-staging-db-data` 후 재실행(**prod에서는 절대 금지**).
  - `CREATE EXTENSION vector` 실패 → db 이미지가 `pgvector/pgvector:pg16`인지 확인(순정 postgres:16은 실패한다).

## §4. 배포 검증 — 라이브니스·레디니스

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 자가검증 1: 도커 헬스체크(이미지 내장 /health/live) - "healthy" 여야 함 (최대 1분 대기)
docker inspect -f '{{.State.Health.Status}}' whymath-staging-app

# 자가검증 2: 라이브니스 - 200 이어야 함 (APP_PORT를 staging.env 값으로)
(Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:18080/health/live").StatusCode

# 자가검증 3: 레디니스(DB 도달 포함) - 200 이어야 함. 503이면 DB 미도달
try {
  $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:18080/health/ready"
  "ready HTTP $($r.StatusCode)"
} catch {
  if ($_.Exception.Response) {
    "ready HTTP $($_.Exception.Response.StatusCode.value__) - 실패(503 = DB 미도달)"
  } else {
    "ready 연결 실패(DNS·TLS·연결거부 등 전송 계층) - $($_.Exception.Message)"
  }
}
```

- **성공**: `healthy` + 라이브니스 `200` + 레디니스 `200`.
- **실패 시 대처**:
  - 자가검증 1이 `starting`에서 안 변하면 1분 더 기다린 뒤 `docker logs whymath-staging-app --tail 100`.
  - 1이 `unhealthy`면 앱이 뜨지 못한 것 — 로그의 traceback을 본다(설정 오류가 대부분).
  - 1·2는 통과인데 3이 503이면 앱은 살아 있고 DB만 못 붙는 것 — `docker compose ... ps`로 db 상태, 이어서 `docker logs whymath-staging-db --tail 50`.
- **변별력 근거**: 세 검사는 서로 다른 것을 본다(프로세스 생존 / HTTP 표면 / 의존성 도달). DB가 죽어도 1·2는 통과하고 3만 실패한다 — 그래서 셋을 다 본다.

## §5. 갱신 배포 (새 코드 반영)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 5-1. 배포 전 백업 (스키마 변경이 있으면 **의무** - OPS-02)
.\scripts\backup\backup_whymath_pg.ps1 -ContainerName whymath-staging-db
$LASTEXITCODE -eq 0     # True 여야 다음 단계 진행

# 5-2. 새 코드 가져오기 + 태그 산출
git fetch origin
git checkout -B claude/whymath-service-review-9r21im origin/claude/whymath-service-review-9r21im
$tag = (git rev-parse --short HEAD)
"새 태그: $tag  (deploy\staging.env의 WHYMATH_IMAGE_TAG를 이 값으로 수정)"

# 5-3. 빌드 -> 마이그레이션 -> 재기동 (§2~§3과 동일 순서)
docker build -f Dockerfile -t whymath-backend:$tag .
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic upgrade head
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml up -d

# 5-4. 검증: §4를 그대로 재실행
```

- **성공**: §4의 세 자가검증 통과 + `docker inspect -f '{{.Config.Image}}' whymath-staging-app`이 새 태그.
- **실패 시 대처**: §6 롤백.
- **다운타임(정직 기술)**: `up -d`가 컨테이너를 교체하는 수 초 동안 API가 끊긴다. 무중단 배포(블루/그린·롤링)는 미도입이다(§8).
- **직전 태그 기록**: 갱신 전에 `docker inspect -f '{{.Config.Image}}' whymath-staging-app`을 실행해 **현재 태그를 메모**해 둔다 — 롤백 좌표다.

## §5b. 보존 파기 스케줄(retention-purge) 확인 — SEC-12

`privacy/retention_purge_cli.py`(증거+PII 시계열 보존기한 경과분을 단일 TX로 파기)는 §3의
최초 배포·§5의 갱신 배포에서 **자동으로 같이 뜬다** — `docker-compose.prod.yml`의
`retention-purge` 서비스가 `app`과 동일 이미지를 재사용해 24시간마다 CLI를 1회 호출한다(신규
이미지·신규 로직 0). 별도 기동 스텝은 없다. 이 절은 **그 서비스가 실제로 파기를 집행하고
있는지 확인**하는 방법이다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 자가검증 1: 컨테이너가 떠 있다 - "Up" 상태여야 함
docker ps --filter "name=whymath-staging-retention-purge" --format "{{.Status}}"

# 자가검증 2: 최근 실행 로그 - 성공은 {"as_of":...,"purged":{...},"total":N} JSON 한 줄.
#   크래시면 이 JSON이 아니라 Python 트레이스백이 보인다(형태로 구분 — 이중 회계 금기).
docker logs --tail 20 whymath-staging-retention-purge

# 자가검증 3(선택 — 스케줄과 무관하게 즉시 1회 확인하고 싶을 때만): 컨테이너 안에서 CLI를
#   1회 직접 실행(스케줄 루프는 건드리지 않음 - exec는 별도 프로세스).
docker exec whymath-staging-retention-purge python -m whymath_backend.privacy.retention_purge_cli
```

- **성공**: 자가검증 1이 "Up"(재시작 반복 중이 아님) + 자가검증 2에서 `{"as_of": ...}` JSON
  형태(0건 파기도 정상 — `"total": 0`은 "파기 대상이 없었다"이지 "실행이 안 됐다"가 아니다).
- **실패 시 신호**: 컨테이너 상태가 "Restarting"을 반복하면 CLI가 매 실행마다 크래시하고
  있다는 뜻(`WHYMATH_DATABASE_URL` 도달성부터 확인). 로그에 JSON 대신 트레이스백만 쌓이면
  같은 신호다.
- **한계(정직 기술)**: 스케줄은 *24시간 고정 간격*이며 특정 시각(예: 매일 새벽 3시) 실행을
  보장하지 않는다 — 컨테이너 기동 시각을 기준으로 24시간마다 돈다. 특정 시각 실행이 필요해지면
  compose 셸 루프를 host cron/Celery beat로 교체(§8 미프로비저닝 목록에 없음 — 현재는 불요
  판단, 필요해지면 재검토).

## §5c. QUALITY 비동기 워커(quality-worker) 확인 — OPS-27

`app`은 QUALITY(로컬 27B급) 요청을 동기로 처리하지 않고 큐에 넣은 뒤 `202`와 `job_id`를 돌려주며, 호출자는 `GET /v1/jobs/{job_id}`로 결과를 폴링한다. 그 큐를 **꺼내서 처리하는 프로세스**가 `quality-worker` 서비스다. 이 서비스가 없던 시기(OPS-27 이전)에는 `202`로 접수된 작업이 영구히 `pending`이었다 — 브로커(Redis)는 멀쩡하므로 `503`도 나지 않아 겉보기엔 정상이었다. §3의 최초 배포·§5의 갱신 배포에서 `app`과 함께 **자동으로 뜬다**(`app`과 동일 이미지·신규 이미지 0). 이 절은 그 워커가 **실제로 큐를 소비할 상태인지** 확인하는 방법이다.

**정본은 이 컨테이너다.** `infra/phaiakes9/systemd/whymath-worker.service`는 compose 없는 네이티브 토폴로지 전용 대안이며(`infra/phaiakes9/OPERATIONS_24_7.md` §2-0), compose 스택이 도는 호스트에는 **설치하지 않는다** — 같은 브로커에 워커를 둘 띄우면 동시성이 2가 되어 GPU 단일 점유(03a §D.3)를 어기고, 애초에 호스트 워커는 호스트 포트가 닫힌 compose Redis에 닿지 못한다. 워커 수는 1이어야 하므로 `--scale quality-worker=N`도 쓰지 않는다(Compose 스펙상 `container_name`이 있는 서비스는 scale이 거부된다 — 이 거부 동작 자체는 데몬이 없어 이 레포에서 실행해 보지 못했다).

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 자가검증 1: 컨테이너 상태 - "Up ... (healthy)" 여야 함 (기동 직후 40초는 "(health: starting)")
docker ps --filter "name=whymath-staging-quality-worker" --format "{{.Status}}"

# 자가검증 2: 워커가 QUALITY 태스크를 등록하고 동시성 1로 떴다 - 3가지가 모두 보여야 함:
#   "concurrency: 1"  /  "whymath.l3.quality.generate"  /  "ready."
docker logs whymath-staging-quality-worker 2>&1 | Select-String -Pattern "concurrency:|whymath.l3.quality.generate|ready\."

# 자가검증 3: 이 워커 노드가 브로커를 통해 응답한다 - "pong" 이 보이고 종료 코드 0 이어야 함
docker exec whymath-staging-quality-worker sh -c 'celery -A whymath_backend.l3.queue.tasks:quality_celery_app inspect ping -d celery@$HOSTNAME --timeout 10'
"PING_EXIT=$LASTEXITCODE"

# 자가검증 4: 컨테이너 안에서 호스트의 Ollama에 닿는다 - 200 이어야 함
docker exec whymath-staging-quality-worker python -c "import os,urllib.request; print(urllib.request.urlopen(os.environ['WHYMATH_OLLAMA_HOST'] + '/api/tags', timeout=5).status)"
```

- **성공**: 1이 `healthy`, 2에서 세 문구가 모두 보임, 3이 `pong` + `PING_EXIT=0`, 4가 `200`.
- **실패 시 신호와 대처**:
  - 1이 `Restarting`을 반복 → `docker logs --tail 50 whymath-staging-quality-worker`. `AttributeError: 'function' object has no attribute 'user_options'`면 `-A` 대상이 팩토리 함수로 돌아간 것이다(compose의 `command`를 `tasks:quality_celery_app`으로 되돌린다 — 계약 테스트 `tests/infra/test_quality_worker_compose.py`가 이 회귀를 막는다).
  - 1이 `unhealthy` → 3을 직접 실행. `No nodes replied`면 워커가 브로커에서 떨어진 것, `Could not connect to the message broker`면 Redis가 죽은 것이다(`docker ps`로 `-redis` 확인). 도커는 unhealthy를 자동 재시작하지 않으므로 사람이 `docker compose ... up -d`(§5-3)로 컨테이너를 교체한다.
  - 4가 `URLError`/`Connection refused` → 워커가 Ollama에 못 닿는다. 이 경우 QUALITY 작업은 `pending`이 아니라 `failure`로 끝난다. 호스트에서 `ollama`가 떠 있는지, 그리고 `deploy\staging.env`의 `WHYMATH_OLLAMA_HOST`(기본 `http://host.docker.internal:11434`)가 맞는지 본다 — `app`의 로컬 LLM 경로와 같은 설정이다.
- **변별력 근거**: 3의 `-d celery@$HOSTNAME`가 핵심이다. `-d` 없는 ping은 같은 브로커의 **어느 노드가 답해도** exit 0이라, 이 컨테이너의 워커가 죽었는데 이웃 워커(예: 호스트 systemd 워커)가 답하면 정상으로 보인다. 그래서 자기 노드만 부르며, compose의 헬스체크도 같은 형태다. 워커 없음·엉뚱한 노드·브로커 단절은 모두 종료 코드 69로, 정상만 0으로 갈린다(2026-10-08 로컬 실측).
- **재시작·종료**: 워커를 내릴 때는 `docker compose ... stop quality-worker`를 쓴다. Celery가 SIGTERM에 warm shutdown(진행 중인 작업을 끝내고 종료)하며 `stop_grace_period: 120s`가 그 시간을 보장한다. 이 유예가 없으면(도커 기본 10초) 진행 중인 생성이 SIGKILL로 끊기고, 이미 수신 확인(ack)된 메시지는 재전달되지 않아 **그 작업이 영구 `pending`**이 된다. 이미지 갱신(§5-3의 `up -d`)도 같은 경로로 워커를 교체한다. (2026-10-08 로컬 실측: 진행 중 SIGTERM → 생성을 마치고 종료, 작업 `success` / 진행 중 SIGKILL → 새 워커를 띄워도 큐·미확인(unacked) 건수가 모두 0이고 새 워커는 그 작업을 한 번도 받지 않아 `pending` 유지.)
- **한계(정직 기술)**: ① 이 스택의 이미지 빌드·`compose up`은 이 문서를 작성한 세션(Docker 데몬 없음)에서 **실행하지 못했다** — 위 4개 자가검증은 첫 실호스트 기동에서 처음 돌아간다. 레포에서 실측된 것은 로컬 `redis-server`(비밀번호 인증) + 실제 `celery` CLI + 가짜 Ollama로 **enqueue → 워커 소비 → `success` 폴링**과 헬스체크 신호의 변별(2026-10-08)이며, 컨테이너 안에서의 동작(비루트 `appuser`·네트워크 이름 해석)은 그 범위 밖이다. ② 작업 유실 방어는 **정상 종료 경로**에만 있다 — 워커 프로세스가 비정상 종료(OOM·강제 kill)하면 진행 중이던 작업은 재시도되지 않는다(`acks_late` 미사용). 이를 바꾸려면 재전달된 작업의 중복 실행(27B 재생성·Langfuse 중복 기록)을 감수해야 하므로 별도 결정이 필요하다. ③ 큐 대기 시간·적체를 보는 지표는 아직 없다(OPS-04 소관).

## §5d. 문항 난이도 보정 스케줄(item-calibration) 확인 — PB-10

`l2/calibrate_items.py`(채점 응답 전수로 문항 IRT 난이도 b·변별도 a를 보정해 `Problem`에 영속)는
§3·§5 배포에서 **자동으로 같이 뜬다** — `docker-compose.prod.yml`의 `item-calibration`
서비스가 `app`과 동일 이미지를 재사용해 24시간마다 CLI를 1회 호출한다(신규 이미지 0). 이 서비스가
생기기 전에는 저장소 안에 그 CLI를 부르는 곳이 0건이라 응답이 쌓여도 `irt_difficulty_b`가 자동으로
채워지지 않았다. GitHub Actions cron은 prod DB에 닿을 수 없어 스케줄 좌석으로 쓰지 않았다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 자가검증 1: 컨테이너가 떠 있다 - "Up" 상태여야 함
docker ps --filter "name=whymath-staging-item-calibration" --format "{{.Status}}"

# 자가검증 2: 최근 실행 로그 - 성공은 calibration_run 한 줄(status=... finished_at=...).
docker logs --tail 20 whymath-staging-item-calibration

# 자가검증 3(읽기 전용 · 쓰기 0건): 보정 루프가 실제로 도는지 숫자로 본다.
docker exec whymath-staging-app python -m whymath_backend.harness.item_calibration_reach_report

# 자가검증 4(EOS-154): 변별도 a 채택 신호 줄 - 실행마다 한 줄이 반드시 있어야 한다.
docker logs --tail 200 whymath-staging-item-calibration 2>&1 | Select-String "irt_a_signal"
```

- **로그 읽는 법**: `status=noop_no_responses`는 채점 응답이 0행이라는 뜻이다 — 지금처럼 학생 응답이
  없을 때의 **정상 상태**다(실패도 성공 위장도 아님). `noop_no_eligible_items`는 응답은 있으나 문항당
  5회 미만이라는 뜻(정상 no-op), `calibrated`는 실제로 b를 보정했다는 뜻이다. 실패는
  `status=failed error_type=<예외 타입명>`이며 컨테이너가 내려가 재시작을 반복한다.
- **a 채택 신호 읽는 법**(자가검증 4 · EOS-154): 보정이 돌 때마다 `irt_a_signal` 한 줄이 남는다
  (채택이 0건이어도 남는다 — 줄이 없는 것과 "아직 대기 중"을 구별하기 위해서다).
  `state=no_denominator`는 b 보정 대상(응답 5건 이상 문항)이 0건이라 a를 판정할 분모가 없다는 뜻,
  `state=waiting`은 대상은 있으나 a 채택이 0건이라는 뜻(**2PL a 보정은 아직 작동하지 않는다**),
  `state=adopted`는 a가 채택된 문항이 1건 이상이라는 뜻이다. `candidates_ge50`은 응답 50건 이상
  문항 수로 채택의 사전 지표(상한)다. **`transition=first_adoption`이 처음 보이면 그날이 EOS-129
  재측정 시점이다**(WARNING 수준으로 남고 `next=`에 다음 행동이 적힌다). `transition=adoption_lost`는
  이전에 채택됐던 a가 이번에 전부 탈락했다는 경고다. 5건은 b(1PL)의 바닥이지 a의 조건이 아니다 —
  a는 응답 50건 이상 + 표준오차 0.3 이하여야 채택된다.
- **판정 읽는 법**(자가검증 3): `NO_RESPONSES`·`NO_ELIGIBLE_ITEMS`는 입력 부재(정상 no-op),
  `LOOP_DORMANT`는 보정 자격 문항이 있는데 b가 전부 비어 있다는 뜻(배치가 한 번도 안 돌았다는
  증거 — 이 서비스가 안 떠 있거나 실패 중인지부터 본다), `LOOP_STALE`은 일부만 채워짐(다음 실행 대기 또는
  정지 — 단독으로 단정하지 않는다), `LOOP_CAUGHT_UP`은 자격 문항 전부 채워짐.
- **한계(정직 기술)**: ①마지막 보정 시각은 DB에 저장되지 않는다(`Problem.calibrated_at` 부재) —
  로그 한 줄이 유일한 기록이고 컨테이너 로그는 3×10MB 회전이다. ②스케줄은 *24시간 고정 간격*이다.
  ③보정 계산은 순수 파이썬 전수 적합이라 문항·응답이 수만 단위가 되면 실행 시간이 길어진다 —
  `--dry-run`으로 먼저 재고 증분 적합을 검토한다. ④`item-calibration` 서비스에 `--dry-run`을 붙이면
  UPDATE가 영원히 0건이 되므로 `tests/infra/test_item_calibration_wiring.py`가 이를 거부한다.
  ⑤a 채택 신호(`irt_a_signal`)도 마지막 보정 시각과 같은 로그 좌석이라 컨테이너를 재생성하면
  사라진다 — 영속 교차 확인은 자가검증 3의 `irt_a` 채움 건수(1 이상이면 a가 채택돼 있다)다.
  ⑥신호는 로그를 읽는 사람에게만 닿는다. 실제 채널(Slack·이메일)로 푸시하는 것은 OPS-30 소관이다.
  ⑦`--dry-run`은 DB를 갱신하지 않으므로 채택 문항이 생기기 전에는 매번 `first_adoption`으로 보일 수
  있다(미리보기). 실제 전이는 `dry_run=false`인 줄에서만 판정한다.

## §6. 롤백

### 6-1. 1순위 — 이미지만 되돌린다 (스키마는 그대로)

대부분의 배포 사고는 코드 문제다. 스키마가 **추가 전용(additive)**이면 옛 코드는 새 컬럼을 몰라도 동작하므로, 이미지만 되돌리는 것이 가장 빠르고 안전하다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# 되돌릴 태그 후보 확인 (로컬에 남아 있는 이미지들)
docker images whymath-backend --format "{{.Tag}}`t{{.CreatedAt}}"

# deploy\staging.env의 WHYMATH_IMAGE_TAG를 직전 태그로 수정한 뒤:
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml up -d

# 자가검증: 실행 중 이미지가 직전 태그여야 함
docker inspect -f '{{.Config.Image}}' whymath-staging-app
```

- **성공**: 위 자가검증이 직전 태그를 출력 + §4 세 검사 통과.
- **실패 시 대처**: 되돌릴 태그의 이미지가 로컬에 없으면(정리됨) `git checkout --detach <직전 SHA>` 후 §2로 재빌드한다.
- **GitHub Actions로 하는 경우**: `Deploy (수동 승인)` 워크플로를 **직전 image_tag + `skip_migration=true`**로 재실행하는 것이 같은 동작이다.

### 6-2. 마이그레이션 되돌림 판단 기준 (스키마까지 되돌려야 하는가)

먼저 **이번 배포가 무엇을 적용했는지** 확인한다.

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic current
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic history -r-5:current
```

판단표 — **위에서부터** 해당하는 첫 줄을 따른다:

| 이번에 적용된 마이그레이션의 성격 | 조치 | 근거 |
|---|---|---|
| 컬럼·테이블 **추가만**(기존 것 미변경, 새 컬럼이 nullable/default 有) | **되돌리지 않는다.** 6-1(이미지만 롤백)로 끝낸다 | 옛 코드는 새 컬럼을 무시한다 — 되돌림은 이득 없이 위험만 추가 |
| 컬럼 rename·타입 변경·NOT NULL 추가 등 **기존 스키마 변형** | `alembic downgrade <직전 리비전>` 후 6-1 | 옛 코드가 변형된 스키마를 못 읽는다. downgrade가 그 변형의 역이면 데이터 손실 없음 |
| **데이터 이동·삭제**(백필 후 원본 DROP, 테이블 DROP 등) | **downgrade 금지 → 6-3 백업 복구** | downgrade는 구조만 되돌릴 뿐 사라진 데이터를 만들어내지 못한다 |
| 판단이 서지 않음 | **6-3 백업 복구**(보수적 선택) | 학생 데이터 손실 > 다운타임 (의사결정 우선순위 #1·#2 ≫ #7) |

```powershell
# (2행에 해당할 때만) 스키마 되돌리기 - 직전 리비전 ID를 넣는다
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic downgrade <직전_리비전_ID>

# 자가검증: current가 그 리비전이어야 함
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml run --rm app alembic current
```

- **실패 시 대처**: downgrade가 `NotImplementedError`·에러로 멈추면 그 마이그레이션은 되돌릴 수 없게 작성된 것이다 → 즉시 6-3.

### 6-3. 최후 수단 — 백업 복구 (OPS-02 연계)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath

# ① 앱만 내린다(DB는 살려둔다 - 복구 대상이다). 쓰기를 멈춰 복구 중 오염을 막는다.
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml stop app

# ② 복구는 OPS-02 런북 절차를 그대로 따른다(컨테이너 이름만 이 스택 것으로):
#    docs/architecture/db_backup_dr_runbook.md  §3-2(반입+복원) -> §3-3(행수 대조)
#    대상 컨테이너: whymath-staging-db  (prod면 whymath-prod-db)

# ③ 복구 확인 후 옛 이미지로 재기동 (deploy\staging.env의 태그를 직전 값으로)
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml up -d

# 자가검증: §4 세 검사 + OPS-02 §3-3 행수 대조
```

- **성공**: OPS-02 §3-3 행수 대조 통과 + §4 세 검사 통과.
- **손실 범위(정직 기술)**: 마지막 백업 이후의 학생 활동은 복구되지 않는다(RPO — OPS-02 §5 기준 최대 3~4일). 그래서 **스키마 변경이 있는 배포는 §5-1 백업이 의무**다.

## §7. 시크릿 등록 (GitHub Actions 자동 배포를 켤 때만)

> 현재는 대상 호스트가 없어 **등록하지 않는다**. 아래는 대상이 생겼을 때의 절차다.

### 7-1. 등록

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
# gh CLI 로그인 상태 확인 (Logged in 표시가 나와야 함)
gh auth status

# 값은 프롬프트로 입력한다 - 명령행에 값을 쓰면 PowerShell 히스토리에 남는다.
gh secret set DEPLOY_SSH_HOST
gh secret set DEPLOY_SSH_USER
gh secret set DEPLOY_PATH
gh secret set DEPLOY_SSH_KNOWN_HOSTS
# 개인키는 파일에서 읽어 넣는다(줄바꿈 보존)
gh secret set DEPLOY_SSH_KEY < C:\경로\배포용_개인키
```

### 7-2. 등록 직후 자가검증 (값 미출력 — CLAUDE.md 시크릿 규칙)

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
# ① 이름 존재 확인 (값은 GitHub도 다시 보여주지 않는다)
gh secret list

# ② 등록 *전에* 값 형식을 검사한다 - 붙여넣기 절단·생략문자 사고 방지
#    (아래는 개인키 파일 검사 예: 헤더/푸터 존재 + 줄 수)
$key = Get-Content C:\경로\배포용_개인키 -Raw
"header: " + ($key -match 'BEGIN .*PRIVATE KEY')
"footer: " + ($key -match 'END .*PRIVATE KEY')
"lines : " + ($key -split "`n").Count
"ellipsis(있으면 FAIL): " + ($key -match '…')
```

- **성공**: `gh secret list`에 5개 이름 모두 표시, header/footer `True`, ellipsis `False`.
- **실패 시 대처**: header/footer가 `False`면 키 파일이 잘렸다 — 원본에서 다시 내보낸다. 등록 후 실제 도달성은 워크플로 preflight가 판정한다(미설정이면 이름을 찍고 실패).
- **변별력 근거**: `gh secret list`는 이름만 보여준다 — "등록됐다"는 확인이지 "올바른 값이다"의 확인이 아니다. 값의 정합은 ②의 형식 검사 + 첫 배포 실행이 판정한다.

### 7-3. environment 승인 규칙 등록 (필수 — 안 하면 승인 게이트가 무효)

GitHub 웹 UI: `Settings → Environments → New environment`에서 `staging`·`prod`를 만들고, **prod에는 `Required reviewers`로 Kiki를 등록**한다.

**성공 판정 — `gh api`로 설정 실물을 읽는다** (아래 "왜 워크플로 실행으로 판정하지 않는가" 참조):

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
gh auth status
gh api repos/kiki-s-broom/WhyMath/environments --jq '.environments[] | {name, rules: [.protection_rules[]?.type]}'
```

- **성공**: `staging`·`prod` 두 줄이 나오고, **`prod`의 `rules`에 `required_reviewers`가 포함**된다.
- **실패**: `prod`가 없거나 `rules`가 `[]` — 등록이 안 됐다. 웹 UI에서 재등록 후 재실행한다.
- **변별력 근거**: 이 명령은 GitHub이 실제로 보관 중인 보호 규칙을 그대로 읽는다. 미등록 상태에서는 `[]`, 등록 상태에서는 `["required_reviewers"]`로 **서로 다른 값**이 나온다.

> **왜 워크플로 실행으로 판정하지 않는가 (2026-09-01 정정)**: 종전 이 자리의 성공 판정은 "`Deploy (수동 승인)`를 prod로 실행했을 때 `deploy` 잡이 *Waiting for review*로 멈추면 성공"이었다. **현 상태에서는 관측 불가능하다** — `deploy` 잡은 `needs: preflight`(deploy.yml:122)이고, preflight는 배포 시크릿 5종(§7-1)이 전부 미설정이라 반드시 실패한다(§8 표 1행). 따라서 `deploy`는 등록 여부와 **무관하게 항상 skipped**로 남는다. 성공/실패 양쪽에서 같은 화면을 내므로 검증이 아니라 위장이다 — CLAUDE.md「변별력 없는 검증 스텝 금지」. 시크릿 5종이 실제로 등록된 뒤에는 그 실행 판정도 유효해진다(그때는 두 판정이 서로를 보강한다).

- **미등록 시 위험(정직 기술)**: environment를 만들지 않으면 GitHub이 자동 생성하며 **승인 없이 통과**한다 — 워크플로에 `environment:`가 적혀 있다는 사실만으로는 승인이 강제되지 않는다.

### 7-4. 등록 후 잔여 한계 — 조일 수 있는 것과 없는 것 (2026-09-01 실측)

등록 직후 GitHub이 준 기본값 2건은 승인 게이트의 강도를 낮춘다. 정직하게 적는다.

| 설정 | 기본값 | 의미 | 처분 |
|---|---|---|---|
| `can_admins_bypass` | ~~`true`~~ → **`false`**(2026-09-01 조임 완료) | 관리자도 승인 절차를 거친다 | 완료 — 실측 `{"can_admins_bypass":false,"rules":["required_reviewers"]}` |
| `prevent_self_review` | `false` | 배포를 **트리거한 본인이 스스로 승인**할 수 있다 | **유지** — 현재 1인 팀이라 `true`로 두면 prod 배포가 영구 불가능해진다. 두 번째 승인자가 생기는 시점에 재검토 |

`can_admins_bypass`는 **2026-09-01에 껐다**. 관리자도 승인 절차를 거치되 자기 승인은 여전히 가능하므로 배포는 막히지 않는다 — "우회"가 아니라 "멈춰서 확인"이 됐다. 아래는 재적용·검증용 명령이다(멱등).

```powershell
# [실행 시스템] Windows PowerShell (= Phaiakes9 이 PC, 진입 명령 불요)
cd C:\Users\kiki\Desktop\__AI\WhyMath
'{"can_admins_bypass":false,"reviewers":[{"type":"User","id":178589964}]}' | gh api -X PUT repos/kiki-s-broom/WhyMath/environments/prod --input -

# 자가검증: false 여야 함
gh api repos/kiki-s-broom/WhyMath/environments/prod --jq '{can_admins_bypass, rules: [.protection_rules[]?.type]}'
```

- **성공**: `{"can_admins_bypass":false,"rules":["required_reviewers"]}`.
- **변별력 근거**: 현재 값이 `true`이므로 명령이 무효면 `true`가 그대로 나온다 — 성공/실패가 다른 값을 낸다.
- **주의**: `reviewers`를 함께 보내지 않으면 기존 승인자 규칙이 지워진다(PUT은 전체 치환) — 위 블록은 그래서 두 필드를 같이 보낸다.

## §8. 정직한 공백 — 이 CI가 검증하는 것과 검증하지 않는 것

### 기계가 실제로 검증하는 것 (진짜 게이트 — PR마다 실행, 실패 시 CI 실패)

`.github/workflows/ci.yml`의 `docker-build` 잡:

1. **이미지가 빌드된다** (의존성 해석·설치 포함)
2. **그 이미지가 실제로 기동한다** — 컨테이너를 띄우고 `/health/live`가 200 + `{"status":"ok"}`. 실패 시 컨테이너 로그를 덤프하고 잡 실패
3. **비루트 실행** — `docker exec ... id -u`가 0이 아님
4. **이미지에 시크릿 미포함** — `Config.Env`에 `WHYMATH_*`·SECRET/PASSWORD/TOKEN/API_KEY류 키 부재
5. **compose fail-closed 변별력** — 빈 env로는 compose가 *거부*해야 통과(거부하지 않으면 CI 실패), 값이 채워지면 렌더 성공 + `trust` 흔적 0건 + 영속 볼륨·pgvector 이미지 존재

`tests/infra/test_deploy_artifacts.py`(hermetic·docker 불요)는 위 계약의 **텍스트 수준 동결**이다.

### 검증하지 않는 것 (사람·런북의 몫)

- **실제 배포 실행** — 아무도 아직 이 스택을 실 호스트에 올린 적이 없다. `.github/workflows/deploy.yml`의 ssh 스텝은 **미검증 골격**이며, 첫 성공 실행 기록이 남기 전까지 검증된 경로가 아니다.
- **마이그레이션이 실 데이터에서 도는지** — CI는 빈 DB 왕복(`backend-migrations` 잡)만 본다.
- **성능·부하·동시성** — 측정 없음.
- **`/health/ready` 200(DB 도달)** — CI 스모크는 의존성 없이 라이브니스만 본다(그게 변별력의 조건). 레디니스는 §4가 사람 손으로 확인한다.

### 미프로비저닝·미도입 목록

| 항목 | 상태 | 영향 |
|---|---|---|
| GCP/AWS 프로덕션 호스트 | **없음** | 자동 배포 워크플로는 preflight에서 명시 실패한다 |
| 컨테이너 레지스트리(GHCR 등) | 없음 | 이미지는 배포 호스트에서 직접 빌드한다(빌드 실패 = 배포 실패) |
| TLS 종단·리버스 프록시 | 없음 | 기본 바인딩이 127.0.0.1인 이유. `APP_BIND_ADDR=0.0.0.0`은 평문 HTTP를 LAN에 여는 것이며 학생 데이터 경로에는 부적합(시연 한정) |
| 무중단 배포(블루/그린·롤링) | 없음 | `up -d` 교체 시 수 초 다운타임 |
| staging 전용 호스트 | 없음 | staging/prod가 같은 호스트에 공존한다(이름·볼륨·포트로만 격리) — 진짜 격리는 호스트 분리 후 |
| environment 승인 규칙 | **등록·강화됨**(2026-09-01) | `staging`(규칙 없음)·`prod`(`required_reviewers`=doldori7, `can_admins_bypass=false`) — `gh api .../environments` 실측 `total:2`. **잔여 한계**: `prevent_self_review=false`(트리거한 본인이 승인) — 1인 팀이라 불가피, 두 번째 승인자가 생기면 재검토(§7-4) |
| 기존 `whymath-pg`(5433) 이관 | 미실시 | 현 데이터는 compose 밖 컨테이너에 있다. 이 스택으로 옮기려면 OPS-02 백업 → 새 볼륨 복원 절차가 필요하다(별도 과제) |
| 로그 수집·알림 | 부분 | 컨테이너 로그 로테이션(10MB×3)만 설정. 중앙 수집·알림은 OPS-04 |

## §9. 운영 요약

| 항목 | 값 |
|---|---|
| 스택 | `whymath-<env>-app`(uvicorn) + `-db`(pgvector/pg16) + `-redis`(redis:7-alpine) + `-retention-purge`(보존 파기 스케줄·SEC-12) + `-quality-worker`(QUALITY 비동기 큐 소비자·OPS-27) + `-item-calibration`(문항 난이도 보정 스케줄·PB-10) |
| 보존 파기 | `retention-purge`가 app 이미지를 재사용해 24h마다 `retention_purge_cli` 호출(§5b) |
| QUALITY 워커 | `quality-worker`가 app 이미지를 재사용해 `celery ... worker -c 1`로 큐를 소비(동시성 1 고정·GPU 단일 점유). 정본은 이 컨테이너, systemd 유닛은 비정본 대안(§5c) |
| 난이도 보정 | `item-calibration`이 app 이미지를 재사용해 24h마다 `calibrate_items` 호출(§5d) |
| 영속 볼륨 | `whymath-<env>-db-data`, `whymath-<env>-redis-data` |
| 공개 포트 | app만 `${APP_PORT}`(기본 127.0.0.1 바인딩). db·redis는 **미공개**(compose 네트워크 내부) |
| 환경 분리 | 단일 compose + `deploy/<env>.env` + `DEPLOY_ENV` 이름 격리 |
| 이미지 태그 | git short SHA(불변). `latest` 금지 |
| 마이그레이션 | 기동과 분리된 명시 스텝(`run --rm app alembic upgrade head`) |
| 롤백 1순위 | 이미지 태그 되돌리기(스키마 유지) — §6-1 |
| 배포 전 백업 | 스키마 변경 시 의무 — `backup_whymath_pg.ps1 -ContainerName whymath-<env>-db` |

---

*작성: 2026-07-26 (OPS-03-deploy-cd-iac) · 이 문서의 명령은 Phaiakes9(Windows PowerShell) 기준이며, compose·python 호출 형식은 `scripts/demo/run_demo.ps1`에서 이미 동작이 확인된 형식을 따랐다. 이미지 빌드·기동은 이 개발 샌드박스에 도커 데몬이 없어 **실행 검증되지 않았다**(CI `docker-build` 잡이 첫 실행 시 판정한다).*
