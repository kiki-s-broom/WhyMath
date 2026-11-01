# EOS-220 — 자동검증 1차 통과율·재작업률 주간 원장 기록 (1회차 소급)

판정 기준: main `15364290` · 기록 레코드 `generated_at` = `2026-11-01T14:18:33.989109+00:00`
(`metrics/weekly.json`)

## 1. 결과 (EOS-197 A6 1회차 · CU 30건)

| KPI | 값 | 분자/분모 | Wilson 단측 95% | 동결 목표(§6) |
|---|---|---|---|---|
| 자동검증 1차 통과율 | 0.1171 | 13 / 111 (모델 응답 수) | 하한 0.0758 | ≥85% · G4 ≥70% |
| 재작업률 | 0.6333 | 19 / 30 (CU 수) | 상한 0.7613 | ≤15% |
| 2회+ 재생성률 | 0.3333 | 10 / 30 | 상한 0.4834 | ≤3% |

- 1차 통과율은 EOS-207 문서(`docs/reviews/eos207_g3_measures_2026-10-29.md`)와 같은 값·같은 분모다(같은
  측정기 `ops/g3_content_measures.measure_auto_gate`를 쓴다).
- CU를 내지 못하고 끝난 시도 49건은 재작업률 분모 밖이다(어느 CU에도 귀속되지 않는다). 레코드
  `detail.abandoned_attempts`에 따로 남겼다.
- 판정은 하지 않는다. G4가 이 레코드를 `generated_at`으로 지목해 판정한다.

## 2. 재작업률 정의 (정본 = `ops/weekly_metrics_report.measure_rework` docstring)

§6의 동결 측정법은 "Run 로그 재생성 카운트"다. 저작 CLI는 시도마다 "몇 번째 CU를 위한 시도인가"를
기록하지 않는다. 그래서 다음 규칙으로 센다.

- **CU 슬롯** = 좌석(회차 폴더) × 생성 주제(`input_snapshot.topic_hint`, 저작 계획 spec 1건).
  같은 좌석·같은 주제의 시도를 생성 시각 순서로 줄 세운다. 보충 라운드도 같은 줄에 이어진다.
- **재생성** = 직전 CU 이후 다음 CU가 나오기 전까지의 CU가 아닌 시도 수. 생성 실패(미생성 포함)·게이트
  거부·검수 대기·중복 거부가 모두 들어간다. 1차 통과율 분모에서 빠지는 미생성도 여기서는 센다.
  재작업은 다시 돌린 횟수이기 때문이다.
- **재작업률** = 재생성 ≥1 CU ÷ CU 수. **2회+ 재생성률** = 재생성 ≥2 CU ÷ CU 수.
- 미측정 조건: 입력·회계 오류(1차 통과율 측정기와 같은 대조) · 생성 시각 없음 · 주제 없음 · 같은
  slug의 결과 순서 판정 불가 · 창 안 CU 0건. 0으로 떨어뜨리지 않는다.
- **범위 밖**: "검수 반려 후 재저작"은 §6 동결 측정법이 아니다. 회차 산출물에는 반려된 CU와 다시
  만든 CU를 잇는 기록도 없다. 그래서 이 값에 들지 않고, 레코드 `detail.review_reauthoring`에 그 사실을
  적었다.

genlog만으로 셀 수 있으므로 새 로그 좌석(`gate_outcomes.jsonl` 등)은 만들지 않았다. 슬롯 번호를
생성기가 직접 남기면 귀속 규칙(시간순)이 필요 없어진다. 그 변경은 생성기 쪽(02-B 레인)에 넘긴다.

## 3. cron 판정 (EOS-220 ⑥)

`weekly-metrics.yml` cron은 **DB 모드 그대로 둔다**. 근거:

1. cron 창은 실행 시각 기준 직전 7일이다. 저작 회차 폴더는 회차가 끝난 뒤 PR로 커밋된다. 그래서 대부분의
   주에 "창 안 응답 0건"인 미측정 행만 늘어난다.
2. 파일 입력 모드는 검수 이벤트 파일(`--events-jsonl`)을 함께 요구한다. cron에는 그 파일을 고를 기준이 없다.
3. 회차 측정은 회차의 창(산출물 시각의 최소~최대)으로 재야 한다.

그래서 회차마다 파일 입력 모드로 한 번 기록하고, 그 레코드를 `generated_at`으로 지목한다(EOS-197 ⑦(d)
선례). cron 레코드에서 두 KPI가 미측정이어도 정상이다.

## 4. 변별력

`tests/backend/ops/test_weekly_metrics_rework.py`:

- 실데이터 사본 주입: 실패 시도 제거 → 재작업률 하락 · CU 1건 제거 → 1차 통과율 분모 −1 · 주제 없음/시각
  없음/회계 불일치/파일 없음/깨진 줄 → 미측정 + 사유. 주입마다 파일이 실제로 바뀌었는지 단언한다.
- 코드 뮤테이션 5종(순서 판정 제거 · 재생성 미초기화 · 슬롯을 좌석 전체로 · 회계 대조 제거 · CU 0건도
  측정) 전건 RED. 원복은 백업 `cp`, 바이트 동일 확인.

## 5. 재현 명령 (저장소 루트)

```bash
python -m whymath_backend.ops.weekly_metrics_report --events-jsonl data/runs/eos197-a6-review/canary_review_events.jsonl --generation-log-jsonl data/runs/eos197-a6-local/cu.genlog.jsonl --generation-log-jsonl data/runs/eos197-a6-openrouter/cu.genlog.jsonl --authoring-run-dir data/runs/eos197-a6-local --authoring-run-dir data/runs/eos197-a6-openrouter --week-start 2026-10-27T14:06:14.101338+00:00 --week-end 2026-10-28T07:52:53.299873+00:00 --krw-per-usd 1540 --dry-run
```

창·입력·환율은 2026-10-28T07:57:24Z 레코드와 같다. 다른 4종 값도 그 레코드와 같게 나온다.

## 6. 다른 레인에 넘길 것

- **02-C(`harness/authoring_round`)**: 회차 진행기의 주간 KPI 미리보기 호출(`authoring_round.py` 약 1185행)은
  `--authoring-run-dir`를 넘기지 않는다. 그래서 미리보기에서 두 KPI가 미측정으로 나온다. 좌석 폴더를
  `--authoring-run-dir`로 함께 넘기면 된다.
- **02-B(`l3/equivalent/**`)**: 생성 로그에 슬롯 번호(spec_id·슬롯 순번)를 남기면 시간순 귀속 규칙이 필요
  없어진다. 이번 측정에는 필요하지 않다.
