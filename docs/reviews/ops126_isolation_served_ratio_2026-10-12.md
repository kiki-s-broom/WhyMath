# OPS-126 / OPS-140 — SymPy 격리 "작동한 비율" 관측 · 상한·용량 재판정 · 두 고립 구현 회수

**판정 기준**: `main a4942eac`(측정 시점) 위에서 이 PR의 작업 트리. 이후 main이 `0cf43504`까지 한 커밋(OPS-135, CI 이미지 설정) 늘었고 이 문서의 대상 파일과 겹치지 않는다.
**측정 환경**: Linux · 4코어 · RAM 16GB · Python 3.13.16 · SymPy(백엔드 제약 파일 고정본). 배포 이미지는 `python:3.12-slim`이라 **버전이 다르다**. Windows(Phaiakes9)는 측정하지 않았다.
**성격**: 2026-10-12 같은 날 서로 다른 두 세션(`claude/relaxed-keller-4wk0b2` · `claude/wonderful-allen-vhbdra`)이 OPS-126을 각자 구현하고 둘 다 PR 없이 끝났다. 이 문서는 두 구현을 **main 위에서 직접 돌려** 기준을 정하고, 두 판정 문서를 하나로 합친 정본이다. 두 브랜치의 수치는 인용하지 않고 이 환경에서 다시 쟀다(재현하지 못한 것은 해당 절에 명시).

---

## 0. 한 줄 결론

| 질문 | 판정 |
|---|---|
| 어느 구현이 기준인가 | **keller 구현을 기준**으로 하고 allen 고유분을 이식했다. 두 구현의 테스트는 main 위에서 둘 다 통과해(16건/12건) 테스트로는 갈리지 않았고, **main의 OPS-131 ①이 이미 지목한 이름**(`process_id`·`undecidable_ratio`·`--mode steps`)이 결정 근거다 |
| 두 구현에 공통으로 남아 있던 결함 | **둘 다 main 위에서는 거짓 "접힘 0%"를 낸다.** 분기 이후 풀에 생긴 `deadlines`(총 예산 소진) 사유를 합계에 넣지 않아, 실측에서 4건 중 접힌 2건을 "작동 100%"로 보고했다. 이 PR이 고쳤다(§2.2) |
| ① 소비자 배선 | **이행** — `/health/ready`에 `sympy_isolation` 섹션. 뮤테이션 12종 전건 검출 |
| ② 상한 재판정 | **부분 이행 + 승계** — 합성 대리 분포로 5.0초 유지 판정. 실입력 분포는 파일럿이 필요해 `OPS-131`이 소유 |
| ③ 운영 용량 | **이행(Linux만)** — 워커 RSS 73~78MB, 기본값 2 유지, 증설 신호 = `queue_waits > 0`. Windows·실배포 이미지 미측정 |
| `OPS-126`을 닫을 수 있는가 | **이 PR 착지 후 소유 세션이 닫을 수 있다**(§7). 단 ②는 문면대로 이행이 아니므로 `OPS-131` 승계를 증적에 적는다 |

---

## 1. 고립 실측 고정 (OPS-140 ①)

| 항목 | keller | allen |
|---|---|---|
| 브랜치 head | `bd22bf43`(ahead 2) | `af36c2cf`(ahead 1) |
| 분기점 | `d873d064` | `d873d064` |
| 대장 상태 | OPS-126 `done`·notes에 PR 보류(incomplete) · claim release됨 | OPS-126 `in_progress` 방치 · claim 기록 없음 |
| `/health/ready` 섹션 | 13필드 · 비율 2개(`isolated_ratio`·`undecidable_ratio`) · `process_id` | 12필드 · 비율 3개(합 1) · `scope: per_process` · `process_id` 없음 |
| 고유 산출 | 단계 합성 측정 `--mode steps` 354건 · 후속 `OPS-131` · config 근거 · MEMORY 항목 | 워커 메모리 도구 `measure_sympy_isolation_workers.py` · 단계 측정 `--steps` 194건 · 모름≠0 테스트 |
| 테스트 | 16건 · 뮤테이션 7종 | 12건 · 뮤테이션 8종 |

main 기준 소비자 부재 실측: 시작 시점에 `isolation_stats()`의 비테스트 소비자 0건, `src/` 안 `sympy_isolation` 섹션 0건이었다. 두 구현은 `api/_isolated_call.py`·`app.py`·`config.py`·이 문서·`measure_sympy_isolation_budget.py`를 서로 다르게 고쳐 통째 병합이 불가능하다. 둘 다 main보다 낡았으므로(분기 이후 main이 `_isolated_call.py`에 `CHAIN_BUDGET_FACTOR`·`budget_s`를 추가) 통째 머지 없이 파일 단위로 옮겼다.

---

## 2. 기준 구현 판정 (OPS-140 ②) — 증거가 먼저

### 2.1 main 위에서 각각 돌린 결과

두 구현을 각각 격리된 작업 트리(main 위)에 3-way로 적용했고(`_isolated_call.py`의 `__all__` 한 줄만 충돌, `CHAIN_BUDGET_FACTOR` 보존하며 해소), 임포트 출처가 해당 작업 트리임을 `__file__`로 단언한 뒤 실행했다.

| 비교 축 | keller | allen |
|---|---|---|
| 자기 테스트 (main 위) | **16 passed** | **12 passed** |
| main 신규 사유 `deadlines` 반영 | ✗ | ✗ |
| OPS-131 ①이 이름으로 지목한 계약(`process_id`·`undecidable_ratio`·원 카운터) | ○ | △ (`process_id` 없음·필드명 다름) |
| 측정 스크립트 인자 (OPS-131이 `--mode steps` 지목) | `--mode steps` ○ | `--steps` △ |
| 세 비율의 합 = 1 (닫힌 회계) | ✗ (분모가 다른 두 비율) | ○ |
| `enabled=False` + 남은 카운터 → 비율 null | ✗ | ○ |
| 응답이 범위(프로세스별)를 스스로 적음 | `process_id`만 | `scope` 문자열 ○ |

### 2.2 둘을 가르지 못한 결정적 발견 — `deadlines`

시작 시점의 풀 `stats()`에는 두 구현이 쓸 때 없던 키 `deadlines`(총 예산 소진, OPS-125·128)가 있다. 두 구현의 판정 불가 합계는 분기 이전의 세 사유(`timeouts`·`queue_waits`·`worker_deaths`)뿐이다. 실제 풀로 입구 거절 1건과 대기열 중 예산 소진 1건을 일으켜 보았다.

> 실측(두 구현 동일): 풀 `stats()`는 `calls` 4·`deadlines` 2였다. keller 스냅샷은 `undecidable` 0·`undecidable_ratio` 0.0·`isolated_ratio` 1.0, allen 스냅샷은 `served` 4·`folded_ratio` 0.0이었다.

4건 중 2건이 판정 불가로 접혔는데 둘 다 "접힘 0%"를 보고한다. 정상 200과 접힘이 같은 화면이 되는, 이 태스크가 막으려던 바로 그 상태다. 이 결함은 어느 구현을 골라도 같으므로 기준 선택의 근거가 아니라 **둘 다에 필요한 수정**이다.

게다가 `deadlines` 증가 지점 하나(`l3/isolated_call.py`의 입구 거절, `budget_s <= 0`)는 `calls`를 올리기 *전에* 오른다. 접힘 수가 분모를 앞질러 `undecidable_ratio`가 1을 넘을 수 있다(예: 정상 1건 + 입구 거절 1건이면 실제 0.5인데 1.0). 그래서 입구 거절도 `calls`를 올리도록 풀에서 한 줄 고쳤다. 다른 접힘 사유(대기 포화 등)가 이미 `calls`를 올린 뒤 접히는 것과 같은 회계가 되어 호출 하나는 정확히 한 결과로 끝난다. 기존 테스트 중 이 경로의 `calls`를 단언한 것은 없었다.

### 2.3 결정

**keller를 기준**으로 한다. 근거는 §2.1의 마지막 세 행이다 — main에 이미 있는 후속 태스크 `OPS-131`이 `process_id`·`undecidable_ratio`·`--mode steps`를 이름으로 지목하므로(복원본), 소비자 계약에 맞는 쪽을 기준으로 삼으면 후속 문면을 고치지 않아도 된다. allen의 닫힌 회계(합 1)는 설계로는 더 단단하지만 **스키마를 갈아엎는 근거**는 못 된다고 보고, 그 의도는 아래 이식으로 살렸다.

**allen에서 이식한 것**
- 모름≠0: 격리가 꺼졌으면 남은 카운터가 있어도 두 비율은 `null`(`IsolationSnapshot`)
- 응답의 `scope: "per_process"`(acceptance ④가 요구한 "응답이 스스로 적는다")
- 워커 메모리 실측 도구 `measure_sympy_isolation_workers.py`(파일 그대로, sha256 일치)
- 오답·무관 쌍 측정 코드 → `measure_sympy_isolation_budget.py --mode slips`(allen의 `--steps`를 모드로 이식. 동일 시드 7에서 판정 분포가 정확히 재현됨)
- 닫힌 회계의 *의도*: 풀이 판정 불가 사유를 새로 세면 깨지는 **키 동결 테스트**(§6)

**이 PR이 새로 한 것**: `deadlines` 사유 반영, 풀 입구 거절 회계 수정, 키 동결 테스트, 실제 풀 회계 테스트, 응답 변환 필드 매핑 테스트.

**버린 것**: 두 브랜치의 OPS-126 태스크 YAML(복사 안 함 — OPS-126은 소유 세션이 닫는다), 두 MEMORY 항목(하나로 새로 씀), allen의 12필드 스키마와 `IsolationServedSnapshot`(이름·구조), allen의 `--steps` 인자(`--mode slips`로 대체).

---

## 3. ① 소비자 배선 — `GET /health/ready`의 `sympy_isolation`

### 비어 있던 것
`api/_isolated_call.isolation_stats()`는 호출 수·상한 초과·대기열 포화·총 예산 소진·워커 사망·폴백을 세지만 **읽는 비테스트 코드가 0건**이었다. 정상 응답 200은 격리가 일했다는 증거가 아니다 — 격리를 끄거나 전부 스레드 폴백으로 새도 200은 같다(CLAUDE.md "작동한 비율" 원칙).

### 만든 것 (신규 엔드포인트·모듈 0 — 기존 좌석 재사용)
- `api/_isolated_call.py` — 불변 `IsolationSnapshot`과 `isolation_snapshot()`(읽기 전용·풀을 만들지 않음)
- `app.py` — `/health/ready` 응답에 `sympy_isolation` 섹션

응답 필드: `scope`·`enabled`·`pool_started`·`process_id`·`max_workers`·`timeout_s`·원 카운터 6종(`calls`·`timeouts`·`queue_waits`·`deadlines`·`worker_deaths`·`fallbacks`)·`undecidable`·`undecidable_ratio`·`isolated_ratio`.

| 비율 | 정의 | 읽는 법 |
|---|---|---|
| `isolated_ratio` | `calls / (calls + fallbacks)` | 1.0이 아니면 일부 호출이 pickle 불가로 스레드 폴백(**시간 상한 없음**)했다 |
| `undecidable_ratio` | `(timeouts + queue_waits + deadlines + worker_deaths) / calls` | 0이 아니면 그만큼이 "모른다"로 접혔다 — 상한 재판정의 입력 |

**None-vs-0**: 분모가 0이거나 `enabled=false`이면 비율은 `null`("0건 중 0건"이 아니라 측정 대상 없음).

### 한계 (응답에 `scope`·`process_id`로도 적힘)
- 카운터는 **프로세스별**이다. 서버 워커(uvicorn `--workers`)가 여럿이면(Phaiakes9 네이티브 유닛은 `--workers 2`, §5) 응답한 워커 1개의 값이고 합산은 수집 측이 `process_id`로 구분해 한다. 재시작하면 0부터다.
- 취소된 요청(클라이언트 끊김)은 `calls`에는 들어가지만 접힘으로 세지 않아 `undecidable_ratio`는 하한 쪽으로 기운다.
- 풀 카운터는 I/O 스레드에서 오르므로 극단적 경합에서 근사값이다(회계가 아니라 비율 관측이 목적).
- **이 지표가 못 보는 것**: 검증기가 구조 예산·보수적 판정으로 직접 `unverifiable`을 내는 경우(§4.3)는 풀 접힘이 아니므로 `undecidable_ratio`에 잡히지 않는다.

---

## 4. ② 상한 재판정 — `sympy_isolation_timeout_s = 5.0` 유지

종전 근거는 **최종답 경로** 정상 문항 14,034건(p50 1.2ms·p99 11ms·최대 107.5ms)뿐이다. 학생 풀이 **단계**(`verify-step`·`verify-solution`) 입력의 정상 분포는 코퍼스에 없고 저장소에 파일럿 `isolation_budget_exceeded` 로그도 없다(내가 찾은 방법으로는 0건). 그래서 합성 대리 분포를 두 가지로 쟀다. **둘 다 실제 학생 입력이 아니다.**

### 4.1 교육과정 형태 합성 단계 354건 (`--mode steps`·시드 20261012) — 이 환경 재측정

| 범주 | n | p50 | 최대 |
|---|---:|---:|---:|
| 전개 올바름 / 오류(분배 누락) | 60 / 60 | 25 / 22 ms | 182 / 40 ms |
| 인수분해 이차 / 삼차 | 40 / 40 | 18 / 24 ms | 56 / 38 ms |
| 일차방정식 / 이차방정식(인수·근) | 40 / 40+40 | 10 / 19·3 ms | 17 / 27·5 ms |
| 유리식 · 지수 · 삼각 · 고차 전개 | 8·6·11·9 | 31·15·42·33 ms | 35·16·132·38 ms |
| **전체** | **354** | **19.4 ms** | **182 ms (p99 56 ms)** |

판정 분포: `correct` 294 · `incorrect` 60. 후보 상한 0.25초·0.5초·1초·2초·3초·5초·10초 어디서도 판정 불가로 떨어지는 건 **0건**이다. 5초 상한은 최대치의 약 27배 여유다. (keller 문서의 최대 157ms와 다른 것은 머신 차이이며 결론은 같다.)

### 4.2 구조 예산을 통과하는 가장 느린 부류 — 고차 방정식 단계

`x^d + k·x + 1 = 0 → x^(d-1) + k·x + 2 = 0`, 상한 없이 끝까지 돌린 소요(초):

| 차수 d | k=1 | k=7919 |
|---:|---:|---:|
| 6 | 0.28 | 0.78 |
| 8 | 0.22 | 1.33 |
| 10 | 0.51 | 1.30 |
| 12 | 0.72 | 2.35 |
| 14 | 1.13 | 3.99 |
| 16 | 1.52 | **5.54** |
| 18 | 2.84 | **6.39** |
| 20 | 2.90 | **10.37** |

5초를 넘기는 건 이 환경에서 3건(keller 문서는 2건 — 머신 차이)이고, 중요한 것은 16건 **전부 상한 없이 끝까지 돌려도 `unverifiable`**이라는 점이다. 5초 상한이 끊는 입력은 어차피 "판정 불가"가 났을 입력이므로 상한은 **지연만 줄이고 판정 정보를 잃지 않는다**.

### 4.3 시간과 무관한 `unverifiable` — 별건으로 분리 (`--mode slips`)

같은 시드(7)로 올바른 단계·전형적 오답·무관 쌍 194건을 쟀다. 올바른 단계(전개식↔인수분해식, 차수 2~8) **70건은 70건 전부 `correct`**이고 5초 초과는 0건이다. 그런데 전개식의 상수항을 1 틀린 전형적 오답 70건 중 `incorrect`는 37건뿐이고 **33건(47%)이 `unverifiable`**이며 그중 25건은 0.5초 안에 즉시 나온다(차수 3은 10건 전부). 시간 상한이 아니라 검증기의 구조 예산·보수적 판정으로 보인다(소스를 읽고 추정한 것이며 `verify_step` 내부의 어느 분기가 그 판정을 내는지는 확인하지 않았다). 학생의 단순 계산 실수가 "판정 불가"로 보일 수 있고 §3 지표에 잡히지 않는다. 합성 프록시이므로 실제 비율은 파일럿에서 다시 봐야 하며, 이 범위 밖이라 **`MATH-08`로 등재**했다.

### 4.4 판정과 한계

값을 **유지**한다(조정 근거 없음). 한계를 숨기지 않는다.
- 합성 대리 분포다. 학생은 생성기가 만들지 않는 식(오타·비표준 표기·긴 연쇄 등식)을 쓴다.
- 한 머신의 값이다. 느린 CI 러너·저사양 서버에서는 소요가 커질 수 있다(4.2의 큰 계수 부류가 5초에 가장 가깝다).
- 남은 판정은 `OPS-131`이 소유한다 — 파일럿이 격리 호출을 1,000건 이상 쌓은 뒤 `sympy_isolation`을 읽어 `timeouts`가 0이 아니면 그 입력이 상한 없이 돌렸을 때 `correct`/`incorrect`로 끝났을지 판정한다. 임계값 제안(`timeouts / calls ≤ 0.5%`)은 측정으로 정한 값이 아니라 allen 문서의 제안이다.

---

## 5. ③ 운영 용량 — `sympy_isolation_max_workers = 2` 유지

### 배포 형상 (저장소 사실) — 두 가지이며 두 브랜치 문서는 하나만 봤다
| 형상 | 근거 | 서버 프로세스 | SymPy 워커 |
|---|---|---:|---:|
| Docker 이미지 | `Dockerfile` `CMD`가 단일 `uvicorn … --factory`(`--workers` 없음) · `docker-compose.prod.yml`의 `app`에 `command`·`mem_limit`·`cpus`·`deploy` 없음 | 1 | 1 × 2 = **2** |
| **Phaiakes9 네이티브(24/7 운영)** | `infra/phaiakes9/systemd/whymath-api.service`의 `ExecStart`가 `--workers 2`(운영 문서 `OPERATIONS_24_7.md` §2도 같음) | 2 | 2 × 2 = **4** |

두 브랜치 문서는 "저장소에서 `--workers`를 찾지 못했다"고 적었다. **내가 찾은 이름(`WEB_CONCURRENCY` 등)으로는 0건이었지만 기능은 있었다** — systemd 유닛이 직접 옵션으로 쥐고 있었다. 파일럿이 Phaiakes9 네이티브로 돌면 이쪽이 실제 형상이다(어느 쪽이 파일럿 형상인지는 이 PR이 확인하지 못했다). `isolated()`를 쓰는 곳은 `api/verify.py`·`api/coach.py`·`api/_attempt_misconception_scan.py`(API 프로세스)뿐이다(main에서 직접 grep).

**네이티브 형상이 §3의 한계를 현실로 만든다**: 서버 프로세스가 2개이므로 `/health/ready` 응답은 요청을 받은 프로세스 1개의 카운터다. 연속 호출이 서로 다른 `process_id`를 돌려줄 수 있어, 수집 측은 같은 `process_id` 값끼리 묶어 추이를 보고 두 프로세스의 값을 합산해야 한다(`OPS-131`이 이미 "프로세스별 수집"으로 적었다). 한 프로세스만 계속 읽으면 다른 프로세스의 접힘을 놓친다.

### 워커 메모리 실측 (`measure_sympy_isolation_workers.py` · Python 3.13)

| 시점 | 워커 수 | 개당 RSS | 합계 RSS | 합계 PSS |
|---|---:|---:|---:|---:|
| 기동 직후 | 2 | 75.8 MB | 151.6 MB | 127.4 MB |
| 무거운 방정식 12회 뒤 | 2 | 78.3 MB | 156.5 MB | 132.3 MB |

워커 4개(= Phaiakes9 네이티브 형상): 기동 직후 합계 RSS 303.4MB·PSS 252.3MB, 무거운 계산 뒤 307.2MB·256.1MB — 개당 76~77MB로 워커 수에 선형이다.

종전 `config.py` 주석 "개당 약 100~150MB"는 실측(73~78MB)보다 과대여서 정정했다. 서버 프로세스를 N개로 늘리면 `N × 2 × 약 76MB`가 더해진다. keller는 Python 3.12에서 73~76MB를 보고했다 — 두 버전이 비슷하다.

### 점유 시나리오 (이 환경 재측정)
느린 입력 2건(`x^20+7919x+1=0` 부류, 상한 5초 초과)이 워커 2개를 잡은 동안 정상 요청 20건을 보냈다.

> 실측: 정상 20건은 전부 `correct`였고 대기는 p50 7.04초·최대 7.05초였다. 풀 통계는 `calls` 24·`timeouts` 2·`queue_waits` 0이었고 `undecidable_ratio`는 0.083이었다.

접힌 것은 느린 입력 2건뿐이고 정상 요청은 접히지 않았지만 **학생 체감 지연은 7초**다. 상한까지 점유한 워커를 끊은 뒤 교체 워커가 콜드 기동하는 비용이 대기에 포함된다. keller 문서의 5.77초와 다른 것은 머신·기동 비용 차이로 본다. 대기 상한(시간 상한 × 2 = 10초) 안이라 접히지 않지만, 느린 입력이 동시에 3건 이상 오면 큐 상한을 넘겨 `queue_waits`가 오른다.

### 판정
기본값 2를 **유지**한다. 메모리 비용이 작고(워커당 약 76MB — Docker 형상 약 152MB·Phaiakes9 형상 약 305MB, 둘 다 앱 프로세스 본체와 별도), 현 형상에서 느린 입력의 동시 도착률은 파일럿 없이는 알 수 없다. 서버 프로세스가 2개인 형상은 같은 시각의 동시 SymPy 계산 한도가 프로세스당 2개이므로(프로세스끼리 워커를 나누지 않는다) 한 프로세스에 느린 입력이 몰리면 다른 프로세스가 비어 있어도 그 프로세스의 대기열은 찬다. 증설 신호는 `sympy_isolation.queue_waits > 0`이며 사후 판정은 `OPS-131` ②가 소유한다.

---

## 6. 집행 지점과 검증 (OPS-140 ④)

### 소비자 (정본화와 별항)
- `health_ready` 핸들러가 `isolation_snapshot()`을 호출한다 — 비테스트 소비자 1건(`app.py`). AST 테스트가 핸들러 본문의 호출을 단언한다(스캔 0건은 실패).
- 분모 0·풀 미기동·격리 꺼짐은 0.0이 아니라 `null`이다. 대조군: 같은 요청이 격리 켬이면 `calls=1`, 끔이면 `calls=0`·`null`.
- 프로세스가 여럿이면 카운터가 프로세스별이라는 한계는 응답의 `scope`·`process_id`에 스스로 적힌다.

### 테스트
`tests/backend/api/test_sympy_isolation_observability.py`(관측) + `tests/backend/l3/test_isolated_call.py`(풀 입구 거절 회계 1건 추가). 이 PR의 새 계약 두 가지:
- **사유 키 동결**: 풀 `stats()`의 키가 `{calls, fallbacks, timeouts, queue_waits, deadlines, worker_deaths}`와 정확히 같다. 풀이 판정 불가 사유를 더 세면 깨져 스냅샷 쪽 처리를 결정하게 만든다. 사유 키마다 서로 다른 2의 거듭제곱을 주고 합계를 대조한다.
- **실제 풀 회계**: 정상 1·상한 초과 1·입구 거절 1·폴백 1을 한 풀에 섞어 `calls=3`·접힘 2·`undecidable_ratio=2/3`·`isolated_ratio=3/4`를 단언(비율이 서로 다른 값이라 바꿔치기가 잡힌다).

### 뮤테이션 (주입 적용·원복 바이트 동일을 하네스가 단언)
12종 중 **12종 전건 검출, 생존 0**. 무주입 기준선은 39건 통과.

| # | 주입 | 검출한 테스트 |
|---|---|---|
| M1 | `deadlines`를 판정 불가 합계에서 뺌 | 응답 필드 매핑 |
| M2 | 입구 거절이 `calls`를 안 올림(원 결함) | 실제 풀 회계 |
| M3 | `health_ready`가 스냅샷 대신 0 객체를 박음 | 소비자 AST |
| M4 | `isolated_ratio`가 `enabled`를 무시 | 격리 꺼짐+잔존 카운터 |
| M5 | `undecidable_ratio`가 `enabled`를 무시 | 격리 꺼짐+잔존 카운터 |
| M6 | 분모 0을 `null`이 아니라 0.0으로 접음 | 격리 끔 라이브 |
| M7 | `deadlines`를 잘못된 키로 읽음 | 실제 풀 회계 |
| M8 | 응답 변환이 `queue_waits`↔`deadlines`를 바꿔 꽂음 | 응답 필드 매핑 |
| M9 | `scope` 문구 변경 | 응답 필드 매핑 |
| M10 | 풀이 `stats()`에 새 키를 세기 시작함 | 사유 키 동결 |
| M11 | `isolated_ratio` 분자·분모 뒤바꿈 | 비율 값 단언(첫 실패: 비교 불일치) |
| M12 | `process_id` 하드코딩 | 라이브 결선 |

한계: 뮤테이션은 `-x`(첫 실패에서 중단)로 돌려 표의 "검출한 테스트"는 첫 실패이며, 같은 주입을 잡는 다른 테스트가 더 있을 수 있다.

---

## 7. OPS-126 acceptance 재대조 (OPS-140 ⑤)

| acceptance | 이 PR 착지 후 main 기준 | 비고 |
|---|---|---|
| ① 소비자 배선 | **이행** | §3. 프로세스별 카운터 한계 명시 포함 |
| ② 상한 재판정 | **부분 이행 — 문면대로는 미이행** | 합성 프록시까지만. 문면의 "파일럿 로그의 `isolation_budget_exceeded` 비율"은 로그가 없어 못 한다. 값은 유지. **`OPS-131`이 승계** |
| ③ 운영 용량 판정 | **이행(Linux)** | §5. 실배포 이미지·Windows 미측정은 §8 |

**닫을 수 있는가**: `OPS-131`이 `depends_on: OPS-126`이므로 OPS-126이 닫혀야 OPS-131이 착수 후보가 된다. ②를 문면대로 이행했다고 쓰면 위증이므로, OPS-126을 `done`으로 닫는 세션은 증적에 "② 합성 프록시까지만·실입력은 OPS-131 승계"를 적는다. `amend --acceptance`가 append 전용이라 문면은 줄이지 않았고 이 PR이 OPS-126 대장 항목을 건드리지도 않았다 — **닫는 시점은 소유 세션이 판단한다.**

`OPS-131`의 ①이 열거한 수집 필드(`calls`·`timeouts`·`queue_waits`·`worker_deaths`·`fallbacks`·`undecidable_ratio`)에는 `deadlines`가 빠져 있다. 단건 엔드포인트는 총 예산(`budget_s`)을 쓰지 않아 `deadlines`가 0이지만, 체인 호출(`verify-solution`·코치 연쇄 검증)은 쓰므로 수집 시 함께 보면 된다.

---

## 8. 이 PR이 하지 않은 것

- 실제 학생 입력·파일럿 로그 기반 실측 — 데이터가 없다(`OPS-131`).
- Windows(Phaiakes9)·실 배포 이미지(Python 3.12-slim)의 메모리·소요 실측 — 이 환경에 해당 머신이 없다.
- 상한·워커 수 기본값 변경 — 근거가 변경을 지지하지 않았다.
- 파일럿이 어느 배포 형상(Docker 단일 프로세스 / Phaiakes9 `--workers 2`)으로 도는지 확인 — 두 형상을 모두 적었고 어느 쪽인지는 모른다.
- 알림 임계 신설 — 관측만 배선했다(게이트·알림은 별건).
- keller 문서의 점유 시나리오 수치 재현(5.77초) — 같은 방법을 쓰지 못했고 이 환경 값(7.04초)을 썼다.
- 장기 가동 시 워커 메모리 성장 — 12회 계산에 +2.5MB만 봤다(SymPy 내부 캐시 상한 도달은 미확인).
- 두 브랜치(`claude/relaxed-keller-4wk0b2`·`claude/wonderful-allen-vhbdra`)의 삭제 — 이 PR이 머지된 뒤 정리한다(이식 완료 확인 전 삭제 금지).
