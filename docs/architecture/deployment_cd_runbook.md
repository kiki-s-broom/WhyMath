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
```

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
            'WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY','WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY'
foreach ($k in $required) {
  $v = $map[$k]
  $len = if ($null -eq $v) { -1 } else { $v.Length }
  $bad = ($len -le 0) -or ($v -match '…') -or ($v -match '\.\.\.') -or ($v -match 'PUT_REAL_VALUE_HERE')
  "{0,-42} len={1,-4} {2}" -f $k, $len, $(if ($bad) { 'FAIL' } else { 'OK' })
}
# 암호화 키 분리 확인 (한 키 유출이 다른 자산으로 번지지 않게) - True 여야 함
$map['WHYMATH_DIALOGUE_CONTENT_ENCRYPTION_KEY'] -ne $map['WHYMATH_DEVICE_SECRET_ENCRYPTION_KEY']
```

- **성공**: 9줄 전부 `OK`(비밀번호 48자, JWT 64자, base64 키 44자 근처) + 마지막 줄 `True`. 값은 화면에 나오지 않는다.
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

# 자가검증: 컨테이너 3종이 Up 상태여야 함
docker compose --env-file deploy\staging.env -f docker-compose.prod.yml ps
```

- **성공**: `alembic current` 출력에 `(head)`, `ps`에 `whymath-staging-app`·`-db`·`-redis` 세 줄이 `Up`(app은 잠시 `starting`일 수 있다 — §4에서 확정).
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
| 스택 | `whymath-<env>-app`(uvicorn) + `-db`(pgvector/pg16) + `-redis`(redis:7-alpine) + `-retention-purge`(보존 파기 스케줄·SEC-12) |
| 보존 파기 | `retention-purge`가 app 이미지를 재사용해 24h마다 `retention_purge_cli` 호출(§5b) |
| 영속 볼륨 | `whymath-<env>-db-data`, `whymath-<env>-redis-data` |
| 공개 포트 | app만 `${APP_PORT}`(기본 127.0.0.1 바인딩). db·redis는 **미공개**(compose 네트워크 내부) |
| 환경 분리 | 단일 compose + `deploy/<env>.env` + `DEPLOY_ENV` 이름 격리 |
| 이미지 태그 | git short SHA(불변). `latest` 금지 |
| 마이그레이션 | 기동과 분리된 명시 스텝(`run --rm app alembic upgrade head`) |
| 롤백 1순위 | 이미지 태그 되돌리기(스키마 유지) — §6-1 |
| 배포 전 백업 | 스키마 변경 시 의무 — `backup_whymath_pg.ps1 -ContainerName whymath-<env>-db` |

---

*작성: 2026-07-26 (OPS-03-deploy-cd-iac) · 이 문서의 명령은 Phaiakes9(Windows PowerShell) 기준이며, compose·python 호출 형식은 `scripts/demo/run_demo.ps1`에서 이미 동작이 확인된 형식을 따랐다. 이미지 빌드·기동은 이 개발 샌드박스에 도커 데몬이 없어 **실행 검증되지 않았다**(CI `docker-build` 잡이 첫 실행 시 판정한다).*
