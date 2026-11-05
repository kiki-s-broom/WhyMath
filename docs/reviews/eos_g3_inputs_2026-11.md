# EOS G3 입력 현황표 (최종본) — 2026-11-05

> 판정 기준: main `a150cdef` (#1845 머지 직후 · 2026-11-05) · 게이트 `G-eos-g3` · 판정 예정 11/22(Kiki 10/28 보류 결정) · 이 문서는 **판정이 아니라 입력 정리**다. 판정·clear는 Kiki 몫이다.
> 초안(2026-10-31 · main `a91ffcf7` 기준 · 레인 01-A)을 이 세션(폴더 04 · 판정 준비)이 main 기준으로 다시 실측해 최종본으로 갱신했다. 초안과 값이 달라진 항목은 없고, ③의 주간 원장 기록 상태만 바뀌었다(§1 ③).
> **D12 결정문은 받지 못했다**(§4). 이 문서는 D12 없이 측정할 수 있는 것만 담고, D12가 오면 §4의 명령으로 게이트 notes에 붙인다.

## 1. 조건별 현황 (main `a150cdef` 재측정)

| # | G3 조건(ADR-007 개정 §결정 2) | 측정값 | 상태 | 근거(재현 명령 §2 · 값 출처) | 소유 태스크 |
|---|---|---|---|---|---|
| ① | A6 LLM 저작 회차 ≥30 CU 커밋 | 30 CU(local 3 · openrouter 27) | **충족** | `wc -l data/runs/eos197-a6-*/cu.jsonl` = 3+27 · `provenance_audit --require-runs` EXIT=0 위반 0 · #1765 | EOS-197(done) |
| ② | HIT 중앙값 ≤8분 · 유효 표본 ≥15 | 중앙값 53.24초(0.89분) · P90 189.45초 · n=30(cu_measured 30/30 · 30초 하한 미달 과반 아님) | **충족(조건부)** | `hit_cu_metrics --events canary_review_events.jsonl --verdicts canary_review_verdicts.jsonl` EXIT=0 · `metrics/weekly.json` 10/28·11/01 레코드 `hit_seconds` measured true 53.2405 · **AI 보조 검수 조건**(검수자가 AI 권고를 보며 판정) — 사람 단독 HIT는 미측정. 판정문에 이 조건을 명시해야 한다(D12) | OPS-90(done) · EOS-197(done) |
| ③ | 자동검증 1차 통과율 '산출됨' | 0.1171(13/111) · Wilson 단측 95% 하한 0.0758 · 원시 0.3153 · 게이트 도달 기준 0.1461 | **충족(산출됨)** | `g3_content_measures` `AUTO_GATE_PASS_RATE=0.1171` `AUTO_GATE_MEASURED=True` · `docs/reviews/eos207_g3_measures_2026-10-29.md` · **주간 원장 정식 기록 확인**: `metrics/weekly.json` 11/01 레코드(`generated_at` 2026-11-01T14:26:01Z) `auto_gate_pass_rate` measured true 0.11711(EOS-220 #1805 · 초안 시점의 "measured:false"는 해소됨) · `weekly_metrics_report --dry-run` 재계산 EXIT=0 동일값 | EOS-207(done) · EOS-220(done) |
| ④ | 힌트 의미 누설 0 | 표본 30건 누설 0(`HINT_SEMANTIC_N=30` `K=0`) · Wilson 단측 95% 상한 0.0827 · 기계 축 L1·L2 누설 0 / 89힌트 | **충족** | `g3_content_measures` `HINT_SEMANTIC_AXIS=PASS` `HINT_MACHINE_AXIS=PASS` · 사람 판정 45행(`hint_verdicts.jsonl` · #1792) · 표본 `hvs-6bfbb1baa75f6e34` 매니페스트 밖 0 · 판정 누락 0 | EOS-210(done) · EOS-211(done) |
| ⑤ | 메타 누락 0 | CU 30건 누락 0(`META_CU_MISSING=0`) · seed 비대상 27건(openrouter 좌석이 seed를 받지 않음 — EOS-197 ⑥ 인정) | **충족** | `g3_content_measures` `META_AXIS=PASS` · `provenance_audit --require-runs` EXIT=0 | EOS-207(done) |

요약: **충족 5/5**(미충족 0 · 측정 실패 0). 단, ②는 AI 보조 검수 조건의 값이라 판정문에 그 조건을 명시해야 한다(결정 D12 — 미수신). `g3_content_measures` 종합 `MACHINE_VERDICT=PASS` · `EXIT=0`. 전체 리포트 = `data/runs/eos197-a6-review/g3_content_measures_g3prep_2026-11-05.json`(이 세션 커밋 · 10/31 EOS-211 소급 리포트 `g3_content_measures_eos211.json`은 사람 판정 전이라 exit 2였고, 사람 판정 반영 후 exit 0으로 바뀐 것이 유일한 차이).

### 1-1. 초안(10/31 · `a91ffcf7`) 대비 바뀐 것

- ③ 주간 원장: 초안은 "`metrics/weekly.json`에는 아직 measured:false(WP-K 소관)"였다. EOS-220(#1805 · 11/01)이 `generated_at` 2026-11-01 레코드에 measured true 0.1171을 정식 기록했으므로 **원장 값과 측정 CLI 값이 일치**한다(병기 완료).
- 그 밖의 측정값(①②④⑤)은 초안과 동일하다. 입력 파일(`data/runs/eos197-a6-*` · `eos197-a6-review`)은 `a91ffcf7` 이후 main에서 바뀌지 않았다(`git log a91ffcf7..a150cdef -- data/runs` 0건 — 이 세션이 커밋하는 리포트 JSON 1건 제외).

## 2. 재현 명령 (저장소 루트 · main `a150cdef` · 2026-11-05 이 세션 실측)

```bash
cd src/backend && python -m whymath_backend.ops.g3_content_measures --round eos197-a6 --runs-root ../../data/runs \
  --hints-jsonl ../../data/runs/eos197-a6-local/cu.hints.jsonl \
  --hints-jsonl ../../data/runs/eos197-a6-openrouter/cu.hints.jsonl \
  --hint-verdicts ../../data/runs/eos197-a6-review/hint_verdicts.jsonl \
  --hint-sample-manifest ../../data/runs/eos197-a6-review/hint_sample_manifest.json \
  --json ../../data/runs/eos197-a6-review/g3_content_measures_g3prep_2026-11-05.json
```

실측: `EXIT=0` · `AUTO_GATE_PASS_RATE=0.1171` · `AUTO_GATE_PASS_RATE_WILSON_LOWER_95=0.0758` · `HINT_SEMANTIC_AXIS=PASS`(N=30 · K=0 · 상한 0.0827) · `HINT_MACHINE_AXIS=PASS` · `META_AXIS=PASS`(30/0) · `HINT_HUMAN_INPUT_ERRORS=0` · `LABEL_MISMATCH=2` · `MACHINE_VERDICT=PASS`. 10/31 Kiki PC 실측(초안 §2)과 같은 값이다.

```bash
cd src/backend && python -m whymath_backend.ops.hit_cu_metrics --events ../../data/runs/eos197-a6-review/canary_review_events.jsonl --verdicts ../../data/runs/eos197-a6-review/canary_review_verdicts.jsonl --json
```

실측: 종료 코드 0 · `hit_median_seconds` 53.2405 · `hit_p90_seconds` 189.452 · `cu_measured` 30/30 · `coverage_rate` 1.0 · 세션 이상 0 · 중복 이벤트 0.

```bash
cd src/backend && python -m whymath_backend.ops.weekly_metrics_report --events-jsonl ../../data/runs/eos197-a6-review/canary_review_events.jsonl --generation-log-jsonl ../../data/runs/eos197-a6-local/cu.genlog.jsonl --generation-log-jsonl ../../data/runs/eos197-a6-openrouter/cu.genlog.jsonl --authoring-run-dir ../../data/runs/eos197-a6-local --authoring-run-dir ../../data/runs/eos197-a6-openrouter --week-start 2026-10-27T14:06:14.101338+00:00 --week-end 2026-10-28T07:52:53.299873+00:00 --krw-per-usd 1540 --dry-run
```

실측: 종료 코드 0 · `hit_seconds` measured true 53.2405 · `auto_gate_pass_rate` measured true 0.11711 — 원장(`metrics/weekly.json` 11/01 레코드)과 같다.

```bash
cd src/backend && python -m whymath_backend.ops.provenance_audit --require-runs
```

실측: 종료 코드 0 · 위반 0건 · seed 미검사 27건(openrouter 좌석 · 비대상).

실행 환경 단서: 이 세션은 Python 3.13.18(CI는 3.12)에서 돌렸다. 측정기는 순수 파일 입력이라 버전 영향은 없다고 보지만, 10/31 Kiki PC 실측(Windows · 초안 §2)과 값이 전부 일치하는 것이 실질 근거다.

## 3. 판정 증거력의 한계 (감리 X-17 · G5 증거에 이어 적는다)

- ② HIT는 **AI 보조 검수**의 값이다 — 검수자가 AI 권고를 보며 판정했으므로 사람 단독 HIT가 아니다. 사람 단독 표본은 0건. 판정문에 조건을 명시하지 않으면 G4·G5가 이 값을 사람 HIT로 오독한다.
- ④ 사람 판정자 1인(kiki). 판정 45건 20.9분, 건당 간격 중앙값 26.2초(최소 21.4초 · 5초 미만 0건) · 사유 45/45. AI 권고는 판정 완료 후에만 비교 공개(R19-01 블라인드) · 불일치 0건.
- ④ 표본 모집단은 1회차 30 CU의 L1·L2 힌트 60건 중 30건 — 2회차(A4·`EOS-225`) 이후 표본은 별도.
- ③ 통과율 0.1171은 '산출됨'(계측 가능성) 조건만 충족한다. G4 조건 "≥70%"와는 거리가 멀다(Wilson 하한 0.0758) — G3 판정과 무관하나 G4 준비 세션이 알아야 한다.
- `LABEL_MISMATCH=2`(`wm-gen-calc1-c42808b25a8f` · `wm-gen-calc1-9e4ec39eaadd`): 검수 라벨 F8 ↔ 기계 미결 — F8 중복 표기 문제로 EOS-204 소관(10/28 G2 판정 단서와 같은 건). 누설이 아니다.
- 판정 기준 해시 이후 main이 바뀌어도 입력 파일(`data/runs/eos197-a6-*`)이 바뀌지 않는 한 값은 같다. 11/22 판정 직전에 `git log a150cdef..origin/main -- data/runs metrics/weekly.json`이 0건인지 확인하고, 0건이 아니면 §2를 다시 돌린다.

## 4. 남은 결정과 기록 절차

- **D12**(기한 11/20 · Kiki): HIT를 AI 보조 조건으로 판정할지. 추천 (a) 판정문에 조건 명시 + G4 전 사람 단독 표본 ≥15. **이 세션은 D12 결정문을 받지 못했다** — 11/05 현재 저장소(docs·MEMORY·gates notes)에도 D12 기록이 없다. D12가 오면 결정문의 명령 그대로 `G-eos-g3` notes에 남긴다(`backlog.py gates amend G-eos-g3 --note "<D12 결정문>" --reason "D12 Kiki 결정 기록"` — 산문은 인용 heredoc 파일 경유).
- Kiki 판정 뒤 기록 명령(세션 실행 · clear는 Kiki):

```bash
python3 scripts/harness/backlog.py gates amend G-eos-g3 --verdict PASS --evidence "판정 기준: main a150cdef · docs/reviews/eos_g3_inputs_2026-11.md · Kiki 판정 <날짜>" --reason "Kiki G3 판정 기록"
```

FAIL이면 `--verdict FAIL`에 `--owner <미종결 소유 태스크>`를 붙인다(현재 5조건 전부 충족이라 FAIL 사유가 나오면 그 사유의 소유 태스크를 그때 등재한다 — 이 문서 §1의 소유 태스크는 전부 done).
