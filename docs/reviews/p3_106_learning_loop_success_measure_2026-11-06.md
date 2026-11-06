# P3-106 — 지표 ⑤ Learning Loop Success 측정 기록 (1차: 수집 경로 실측 · 운영 DB 대기)

판정 기준: main `ce8c2165` (2026-11-06)
태스크: `P3-106-phase3-learning-loop-success-prod-measure` · 작업 M1 · 게이트 입력 `G-p3-w3-release-merged`
목표: Wilson 하한(신뢰도 0.95) ≥ 0.95 (`G-p314-phase3-metric-targets` · 2026-10-12 Kiki 확정)

## 0. 요약

| 항목 | 값 |
|---|---|
| 운영 DB(`whymath-pg` 5433) 기준 ⑤ | **미측정 — Kiki PC 실행 대기** (런북 `docs/ops/p3_106_learning_loop_success_prod_measure_runbook.md`) |
| 수집 경로 생존(클라우드 세션 실 PG) | 살아 있음 — 루프 기록 0건이면 "측정 불가(0/0)", 기록이 있으면 값·Wilson 하한으로 판정 |
| Gate A 관통 1회분 표본(정리 끈 실측) | 1/1 = 100% · Wilson 하한 0.2699 < 0.95 → **FAIL(미달)** |
| PASS에 필요한 최소 표본 | 전건 성공 52세션 · 1건 실패 87 · 2건 118 · 3건 147 |
| 운영 DB에 그 표본을 AI로 만드는 경로 | **없음** → `P3-108` 등재 |

이 문서는 **운영 DB 값을 아직 담지 않는다.** 운영 DB 결과가 오면 §5에 덧붙인다. 그 전까지 ⑤는
"측정되지 않은 지표"이며 PASS로 세지 않는다.

## 1. 수집 경로 (코드 실측)

- 진입: `python -m whymath_backend.ops.phase3_metrics` (`src/backend/whymath_backend/ops/phase3_metrics.py`).
  ⑤는 새 정의 없이 `ops/loop_kpi_gate.py`의 `LOOP_COMPLETION`(`collect_loop_completion`)을 그대로 쓴다.
- DB 접속: 환경 변수 `WHYMATH_DATABASE_URL`(`config.py` `database_url` · `env_prefix="WHYMATH_"`).
  기본값은 `postgresql+asyncpg://whymath@127.0.0.1:5432/whymath`이라 **운영 DB(5433)는 반드시 명시**해야 한다.
  접속 실패는 실행 오류(3)가 아니라 ⑤의 미측정(exit 2 · 예외 타입명 기록)이다.
- `--since-hours`: 관측창(기본 24시간). 창 = [지금 − N시간, 지금).
- `--no-db`: ⑤ 수집을 건너뛴다(P3-17이 쓴 방식 — 이번엔 쓰지 않는다).
- `--input loop.json`: 숫자 주입. 형식 `{"loop_completion_rate": {"numerator": int, "denominator": int}}`
  (그 밖의 키는 거부). 주입할 때는 `--sample-basis`가 **필수**이고 결과에 "주입 — 측정이 아니다"가 찍힌다.
- `--sample-basis {live, synthetic}`: 표본 성격 표지. DB 수집이면 기본 `live`.
- 분모: 관측창에 시작된 `learning_session` 중 `problem_attempt`가 1건 이상 있는 세션 수.
  분자: 그중 첫 시도(서버 수신 시각) 이후·창 끝 이전에 같은 `session_id`의 `recommendation_render`
  증거 이벤트가 1건 이상 있는 세션 수. 시도 없는 세션은 `sessions_without_attempt`로 따로 보고.
- 판정: 분모 0 → 미측정. 그 외 Wilson 하한 ≥ 0.95면 PASS.
- **내부 테스트 계정 필터 없음.** 수집기는 관측창의 모든 세션을 센다. 운영 DB에 실사용자가 없다는
  전제(ARCH-66 ⑥ — 학생 참여는 12/31 이후)에서만 "내부 테스트 계정 표본"과 같다.

## 2. 클라우드 세션 실측 (실 PG 16 + pgvector · `alembic upgrade head`)

| # | 상태 | ⑤ 결과 | exit |
|---|---|---|---|
| 1 | 빈 DB(루프 기록 0건) | 미측정 — 분모 0/0 · `sessions_started=0` | 2 |
| 2 | `test_release_gate_a_chain.py` 정상 실행 후(9/10 도달 · 학습 단계 PED-17 끊김) | 미측정 — 0/0 | 2 |
| 3 | 같은 관통을 **정리(teardown)만 끄고** 1회 실행 후 | 측정 — 1/1 = 100% · Wilson 하한 0.2699 → 미달 | 2(②⑥ 미측정 때문) |
| 4 | 3과 같은 DB를 읽기 전용 실행기로 측정 | 3과 동일 · `READ_ONLY=True` | 2 |

- 2의 원인: 관통 하네스는 끝에 `_Content.teardown()` → `DELETE /v1/me`(삭제권 경로)로 학습자를 지운다.
  그래서 테스트가 남기는 루프 기록은 0건이다 — "테스트를 돌리면 표본이 생긴다"는 성립하지 않는다.
- 3의 기록: 세션 1 · 시도 21(전부 그 세션) · `recommendation_render` 22. 첫 시도 이후 추천 21건.
  정리를 끈 것은 일회용 pytest 플러그인(커밋하지 않음)이며 관통 코드 자체는 바꾸지 않았다.
- 종합 exit 2는 ⑤가 아니라 ②(힌트 입력 없음)·⑥(payload 없음) 미측정 때문이다. ⑤ 판정은 행 단위로 읽는다.

## 3. 읽기 전용 실행기 (`scripts/ops/phase3_metrics_readonly.py`)

운영 DB에 쓰지 않음을 코드 주장이 아니라 DB가 강제하게 했다. 접속을 asyncpg `server_settings`의
`default_transaction_read_only=on`으로 열고, 측정 전에 `SHOW transaction_read_only`가 `on`인지 스스로
확인한다(아니면 exit 3 거부). ⑤만 뽑은 ASCII 한 줄(`P5_SUMMARY=`)을 회신용으로 낸다.

| 방법 | UPDATE 주입 결과 | 채택 |
|---|---|---|
| `PGOPTIONS` 환경 변수 | 성공(asyncpg가 읽지 않음) | 기각 |
| SQLAlchemy `connect` 이벤트 `SET SESSION … READ ONLY` | 성공(접속 직후 롤백으로 되돌려짐) | 기각 |
| asyncpg `server_settings` | `ReadOnlySQLTransactionError`로 차단 | 채택 |

동결: `tests/backend/ops/test_phase3_metrics_readonly.py`(실 PG · `integration`) 4건 — 주입 차단 · 대조군
성공 · 자가확인 거부 · 정상 실행. 뮤테이션 2종(엔진 보호 제거 · 자가확인 제거)이 각각 해당 테스트만 RED,
원복 바이트 동일.

## 4. 끊긴 지점 — 누가 루프를 돌려야 표본이 생기는가

- 운영 DB의 ⑤ 표본은 **누군가 앱(또는 공개 HTTP 표면)으로 진단 → 문제 시도 → 추천까지 도는 학습 세션**을
  만들어야 생긴다. 지금 그 주체는 Kiki의 수동 시연뿐이고, PASS에 필요한 52세션을 한 관측창에 쌓는
  경로가 없다.
- Gate A 관통 하네스(P3-101)는 실 PG에서 돌지만 학습자 1명이고 스스로 지운다.
- 결정론 합성 부하(EOS-38 `loop_kpi_sample_load`)는 표본을 충분히 만들지만 전용 DB(`_kpi_sample`)만
  허용하고 `synthetic`으로 표지된다 — 운영 live로 계상되지 않는다.
- 따라서 운영 DB 결과가 0/0이면 그 판정은 **"측정 실패 — 루프 표본 부재"**다. 해소 경로와 표본 기준
  결정은 `P3-108`이 소유한다.

## 5. 운영 DB 결과 (Kiki PC)

아직 없음 — 런북 실행 대기. 결과가 오면 이 절에 `MEASURE_BASE`(측정 기준 해시) · 24시간 창과 전 기간의
값·분모·목표·판정을 적는다.
