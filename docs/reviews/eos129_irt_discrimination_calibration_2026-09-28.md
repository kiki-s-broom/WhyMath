# EOS-129 — IRT 변별도 a 보정 배선 판정 (2026-09-28)

> **판정 기준: main `919865d4`** (브랜치 `claude/gallant-euler-blngpj`에서 구현 · 이 문서의 코드
> 참조는 그 브랜치 기준이며, 머지 전까지 main에는 없다)
>
> 대상 태스크: `EOS-129-irt-discrimination-calibration` · 선행 맥락: `EOS-126`(CAT 2차 중단 규칙)

## 요약

| 축 | 판정 | 근거 |
|---|---|---|
| ① 근본 원인 실측 고정 | **충족** | a=1.0 하한 45문항, 프로브 실측 46문항을 회귀로 동결 |
| ② 쓰기 경로 부재 확정(착수 시점) | **충족** | 착수 시점 `irt_a` 쓰기 경로 0건 |
| ③ 2PL 보정 배선 + 폴백 비율 리포트 | **충족** | 보정기 → `Problem.irt_a` → CAT 진단 경로 소비, 리포트가 폴백 비율·사유를 말한다 |
| ④ 도달 비용 재측정 | **충족** | a=1.5 → 적응 22문항, a=2.0 → 적응 13문항 |
| ⑤ 운영 코퍼스 응답 분포 실측 | **미측정 — 게이트 이관** | 컨테이너에 운영 DB 부재. 읽기 전용 측정 모드(`--dry-run`)를 만들어 둠 |

## ① 근본 원인 — a=1.0이면 45문항이 하한이다

문항 하나의 최대 정보량은 a²·0.25(P=0.5일 때)다. SE ≤ 0.3이려면 총정보량이 1/0.3² = 11.11
이상이어야 하므로, 필요한 최소 문항 수는 ceil(1/(0.09·0.25·a²))다.

- a=1.0 → 45 · a=1.5 → 20 · a=2.0 → 12

프로브: 난이도 1.0~5.0 균등 201문항 코퍼스(`difficulty_to_logit`로 b ∈ [−2, 2]), 참 θ=0.
두 방식으로 쟀다.

- **고정 θ**: θ를 참값에 고정하고 `select_next_item`이 고른 문항의 정보만 누적 — 순수 정보 축
- **적응 루프**: θ̂로 다음 문항 선택 → 결정론 응답(참 θ 기대 정답 누적을 반올림해 따라감) →
  `estimate_ability`로 θ̂ 재추정 → θ̂에서 SE — 실제 CAT와 같은 순서

a=1.0 실측: 고정 θ 46문항(SE 0.2975), 적응 루프 46문항(SE 0.2998). EOS-126 주석의
"46문항(SE 0.2973)"과 같은 축이다. 동결 위치는
`tests/backend/l2/test_irt_discrimination_calibration.py::TestReachLowerBound`이다.

## ② 쓰기 경로 부재 — 착수 시점 실측

착수 시점(main `919865d4`)에 `src`·`scripts`·`src/data-pipeline` 전체를 `irt_a` 식별자와
`irt_a=` 대입 형태로 검색했다. 결과는 다음과 같다.

- 소비처: `l1/problem_bank/probe_candidates.py`(오개념 프로브 경로) 1곳
- 선언: ORM 컬럼(`db/models/problem.py`), 스키마 필드(`schema/problem.py`), 마이그레이션
  `20260616_1300_c8d9e0f1a2b3`의 ADD COLUMN
- 쓰기 경로: **0건**. 보정기 `l2/item_calibration.py`는 `fit_jmle`(1PL, a 고정)로 b만 적합했다.
  `Problem.from_schema`는 스키마 필드를 그대로 옮기는 통로라 원리상 쓸 수 있지만, 저장소의
  적재 데이터(JSON·YAML·JSONL)에 `irt_a`를 담은 파일은 0건이었다(백로그 태스크 문서 제외).

즉 착수 시점 `irt_a`는 항상 NULL이었고, CAT 진단 경로는 모든 응답을 Rasch(a=1.0)로 다뤘다.

## ③ 배선 지점

| 지점 | 변경 |
|---|---|
| `l2/irt.py::estimate_item_parameters` | θ 고정 조건부 MLE로 (a, b) 동시 추정. Fisher scoring, 스텝 상한, 우도 감소 시 절반 줄이기, 경계 clamp. `ItemFit`이 추정값과 신뢰 판정 재료(수렴·경계·a의 SE)를 함께 싣는다. 독립 구현(로지스틱 회귀 IRLS)과 수치 일치를 테스트로 확인 |
| `l2/item_calibration.py` | 1PL 단계(`fit_jmle`, 응답 5건 이상에서 b 채택)는 동작 그대로. 그 θ를 고정하고 b 보정 대상 문항마다 2PL 적합. 경계 θ(만점·영점 학생) 응답은 a 입력에서 제외 |
| 채택 게이트 | 응답 50건 이상(경계 θ 제외 후) · 정답과 오답이 모두 있음 · 수렴 · a와 b 모두 경계 아님 · a의 SE 0.3 이하. 전부 충족할 때만 채택하고, 이때 b도 같은 2PL 적합의 b로 영속한다(a와 짝이 맞아야 곡선이 적합과 일치) |
| 탈락 문항 | 1PL b만 UPDATE하고 `irt_a`를 NULL로 되돌린다. 이전 실행에서 채택됐다가 이번에 탈락한 문항의 낡은 a가 "현재 보정값"으로 읽히는 것을 막는다 |
| `CalibrationReport` | b 보정 수, a 채택 수, 폴백 수, 폴백 사유별 건수(0건 사유 포함), 문항당 응답 분포(1-4 / 5-49 / 50-99 / 100+), 경계 θ 제외 응답 수. 폴백 비율은 분모 0이면 None(0으로 접지 않음) |
| `l2/calibrate_items.py` | `--dry-run`(UPDATE·commit 0건), `--json`. 텍스트 출력 첫 줄 `calibrated_items=N`은 하위호환으로 유지 |
| `l2/ability_estimation.py::resolve_item_discrimination_a` | 양수·유한이면 그 값, 아니면 1.0. `resolve_item_difficulty_b`의 대칭축 |
| `l2/next_problem_selection.py::load_attempt_history_state` | SELECT에 `Problem.irt_a` 추가, `IrtItem(difficulty=b, discrimination=a)`. a가 전부 NULL이면 종전과 같은 θ·SE(테스트로 동결). `AttemptHistoryState.discrimination_applied_count`가 a가 실제로 적용된 응답 수를 말한다 |

게이트 채택 설계에서 원 설계에 하나를 더했다. b가 경계에 닿은 적합(`b_at_bound`)도 탈락시킨다.
a는 멀쩡해 보여도 짝인 b가 발산 표시라면 그 곡선을 믿을 수 없기 때문이다.

### 범위 밖(의도적)

- 후보 선택(`candidate_items`·`CandidateRow`)은 여전히 a=1.0으로 정보량을 비교한다. 선택
  순서가 바뀌면 추천 문항 자체가 바뀌므로 별건으로 남긴다.
- `estimate_global_ability`·`compute_concept_abilities`(능력 조회·스냅샷 경로)도 Rasch
  그대로다. 이 경로들은 보정 b를 소비하므로, 채택 문항의 b는 이제 2PL 적합의 b가 들어간다.
  두 b의 차이는 작지만 0은 아니다.
- L1 `probe_candidates.py`는 원래 `irt_a`를 읽고 있었으므로 보정이 채워지면 자동으로 소비한다.

### 척도 주의

2PL a는 1PL JMLE θ 척도 위에서 추정된다. 합성 실험(학생 400명 × 문항 10개)에서 참 a
0.8~2.2가 0.73~1.55로 적합됐다. 순위는 보존되지만 절대값은 JMLE θ 척도가 넓게 퍼지는
만큼 줄어든다. CAT의 θ·SE도 같은 척도에서 계산되므로 서로 일관되지만, ④의 "a=2.0이면
13문항"을 운영 수치로 옮길 때는 **운영 코퍼스에서 실제로 적합된 a 분포**로 다시 읽어야 한다.

## ④ 도달 비용 재측정

같은 프로브를 문항 풀의 a만 바꿔 돌렸다.

| a | 해석적 하한 | 고정 θ | 적응 루프 | 상한(20) 대비 |
|---|---|---|---|---|
| 1.0 | 45 | 46 (SE 0.2975) | 46 (SE 0.2998) | 상한이 먼저 발화 |
| 1.5 | 20 | 20 (SE 0.2993) | 22 (SE 0.2942) | **상한이 여전히 먼저 발화** |
| 2.0 | 12 | 12 (SE 0.2894) | 13 (SE 0.2986) | 정밀도 축이 먼저 발화 |

읽는 법: 순수 정보 축에서는 a=1.5가 정확히 20문항에 닿지만, θ̂를 재추정하는 실제 적응
루프는 초반 θ̂ 오차 때문에 2문항을 더 쓴다. 따라서 EOS-126의 상한(20)이 비상구로만 남으려면
운영 문항의 a가 대략 2 근처까지 채워져야 한다. 위 척도 주의대로, 이 조건이 운영에서 성립하는지는
⑤의 실측 없이는 말할 수 없다.

## ⑤ 운영 코퍼스 응답 분포 — 미측정, 게이트로 이관

이 컨테이너에는 운영 DB가 없어 측정하지 않았다. 측정 수단은 만들어 두었다.

- 명령: `python -m whymath_backend.l2.calibrate_items --dry-run` (JSON이 필요하면 `--json` 추가)
- 동작: UPDATE·commit이 0건이다(테스트 `test_dry_run_writes_nothing`이 동결). 리포트는
  문항당 응답 분포, b 보정 대상 수, a 채택 가능 수, 폴백 사유별 건수를 낸다.
- 전제: 대상 DB는 prod `whymath-pg`(호스트 포트 5433)다. CLI 기본 URL은 5432(타 프로젝트
  점유)이므로 `WHYMATH_DATABASE_URL`을 5433으로 지정해야 한다.

판정 규칙(이관 후): `discrimination_calibrated`가 0에 가깝고 분포가 `1-4`·`5-49`에 몰려
있으면 이 태스크의 ③은 "배선 완료·데이터 축적 대기" 상태이며, 그 사실 자체가 산출물이다.
