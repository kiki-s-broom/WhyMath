# EOS G3 입력 현황표 (초안) — 2026-10-31

> 판정 기준: main `a91ffcf7` (#1792 머지 직후) · 게이트 `G-eos-g3` · 판정 예정 11/22(Kiki 10/28 보류 결정) · 이 문서는 **판정이 아니라 입력 정리**다. 판정·clear는 Kiki 몫이다.

## 1. 조건별 현황

| # | G3 조건(ADR-007 개정) | 현재 값 | 상태 | 근거(재현 명령·문서) |
|---|---|---|---|---|
| ① | A6 LLM 저작 회차 ≥30 CU 커밋 | 30 CU(local 3 · openrouter 27) | 충족 | `data/runs/eos197-a6-*/cu.jsonl` · #1765 |
| ② | HIT ≤8분 · 유효 표본 ≥15 | 중앙값 53.24초(0.89분) · n=30 | 충족(**조건부**) | `metrics/weekly.json` 2026-10-28 레코드 `hit_seconds` · **AI 보조 검수 조건** — 사람 단독 HIT는 미측정(D12에서 처리) |
| ③ | 자동검증 1차 통과율 '산출됨' | 0.1171(13/111) · Wilson 단측 95% 하한 0.0758 | 충족(산출됨) | `docs/reviews/eos207_g3_measures_2026-10-29.md` · 아래 §2 명령 `AUTO_GATE_PASS_RATE` · 단 `metrics/weekly.json`에는 아직 measured:false(WP-K 소관) |
| ④ | 힌트 의미 누설 0 | 표본 30건 누설 0 · Wilson 단측 95% 상한 0.0827 | 충족 | #1792 사람 판정 45건 · `HINT_SEMANTIC_AXIS=PASS` |
| ⑤ | 메타 누락 0 | CU 30건 누락 0 | 충족 | `META_AXIS=PASS` · `META_CU_MISSING=0` |

요약: 5개 조건 모두 값이 있고 기준을 넘는다. 단, ②는 AI 보조 검수 조건의 값이라 판정문에 그 조건을 명시해야 한다(결정 D12).

## 2. 재현 명령

```bash
cd src/backend && python -m whymath_backend.ops.g3_content_measures --round eos197-a6 \
  --hints-jsonl ../../data/runs/eos197-a6-local/cu.hints.jsonl \
  --hints-jsonl ../../data/runs/eos197-a6-openrouter/cu.hints.jsonl \
  --hint-verdicts ../../data/runs/eos197-a6-review/hint_verdicts.jsonl \
  --hint-sample-manifest ../../data/runs/eos197-a6-review/hint_sample_manifest.json
```

2026-10-31 Kiki PC 실측(main 96fc929c + 판정 3파일 = 이 문서의 기준 a91ffcf7과 같은 입력): `EXIT=0` · `HINT_SEMANTIC_AXIS=PASS` · `HINT_MACHINE_AXIS=PASS` · `META_AXIS=PASS` · `AUTO_GATE_PASS_RATE=0.1171` · `HINT_HUMAN_INPUT_ERRORS=0` · `MACHINE_VERDICT=PASS`.

## 3. 판정 증거력의 한계 (감리 X-17 · G5 증거에 이어 적는다)

- 사람 판정자 1인(kiki). 판정 45건 20.9분, 건당 간격 중앙값 26.2초(최소 21.4초 · 5초 미만 0건) · 사유 45/45.
- AI 권고는 판정 완료 후에만 비교 공개(R19-01 블라인드) · 불일치 0건.
- 표본 모집단은 1회차 30 CU의 L1·L2 힌트 60건 — 2회차(A4) 이후 표본은 별도.
- `LABEL_MISMATCH=2`(`wm-gen-calc1-c42808b25a8f` · `wm-gen-calc1-9e4ec39eaadd`): 검수 라벨 F8 ↔ 기계 미결 — F8 중복 표기 문제로 EOS-204 소관(10/28 G2 판정 단서와 같은 건).

## 4. 남은 결정

- **D12**(11/20): HIT를 AI 보조 조건으로 판정할지(추천 (a) 조건 명시 + G4 전 사람 단독 표본 ≥15).
- 11/22 Kiki 판정 전에 이 표를 main 기준으로 다시 실측해 최종본으로 갱신한다(폴더 04 판정 준비 세션).
