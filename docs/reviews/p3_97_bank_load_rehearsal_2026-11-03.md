# P3-97 — 운영 DB 미적분 은행 적재 리허설 (2026-11-03)

> **판정 기준: main `37e32712`** + 이 PR · 측정 환경 = 클라우드 세션의 로컬 PostgreSQL 16 + pgvector(운영 아님) ·
> 스키마 `a8c4e1f7b3d9`
> 태스크: `P3-97` · 런북 `docs/ops/p3_97_bank_load_runbook.md`

## 1. 왜 리허설인가

운영 DB에서 P3-32 힌트 연결이 2/10에서 멈췄다(`docs/ops/p3_32_hint_link_runbook.md` §10). 남은 8개 개념의 문항이 운영
DB에 없기 때문이다. Kiki가 2026-11-03에 적재를 결정했고 범위를 두 은행(`p3_calculus1_diff_v0` 504행 ·
`conceptual_v0` 360행)으로 정했다. `p3_fill_v0`는 현재 승인본에 문장 결함이 남아 있어 제외했다(코퍼스 실측:
"(a는 상수)가" 24 · "...로" 12 · "차분몫" 10 · "구하는 극한값" 8 · "cm/초^2였다고" 3 — 두 적재 대상 은행은 같은 검색이
전부 0건). 적재 CLI에는 시험 실행이 없어서, 운영과 비슷한 DB를 만들어 적재와 그 뒤의 P3-32 전 과정을 끝까지 돌렸다.

## 2. 운영 모사

빈 DB에 마이그레이션 → 성취기준 → 원자 백본 → `generated_v0`·`misconception_mc_v0`만 적재 = **문항 1,699행**
(운영 1,703행 · P3-32 운영 실측에서 운영의 핵심 개념 적격 문항이 정확히 이 두 은행 소속으로 나왔다).

## 3. 결과

| 단계 | 결과 |
|---|---|
| 미리보기(적재 전) | `TOTAL_NEW=864` · `TOTAL_NEW_APPROVED=864` · `TOTAL_SLUG_CONFLICT=0` · `TOTAL_PROTECTED=0` · `CONCEPTS_GAINING=9` · `LOAD_VERDICT=OK` |
| 개념별 새 적격 문항 | 02-02 24 · 02-03~02-06 각 72 · 02-07 24 · 02-08~02-10 각 72 · 02-01 0(이미 있음) |
| 적재 | calc 504건 · conceptual 360건 · 개념 orphan 0 · 두 CLI exit 0 |
| P3-32 프로브(적재 후) | `DB_PROBLEM_ROWS=2563` · `ELIGIBLE_IN_DB=780` · `REPLAYABLE_IN_DB=540` · `CONCEPTS_REPLAYABLE=10` · `VERDICT=READY` · `REPLAY_BANK_COUNT=3` |
| 재생(3개 은행 · 존재 필터) | 979/979 verified · 실패 0 · `skipped_problem_missing=0` |
| 승격 | 979 승격 · 대기열 0 · 형식 거부 0 |
| 힌트 | 생성 4,421 · 검수 통과 4,147 |
| 계측기 `--hints-from-db` | **hint linked 10 · missing 0 · Concept Completeness 10/10** |

## 4. 함께 고친 것

- 런북 가드 검사기(`scripts/ops/check_runbook_blocks.py`)가 적재 블록을 **쓰기 0개**로 판정했다 — 적재 모듈 호출이
  `cmd /c "…"` 문자열 안에 있어서 토큰 검사가 못 봤다(P3-32 PR에서 재생·승격에 대해 고친 것과 같은 사각). 문자열 속
  `-m whymath_backend.….populate`를 적재로 본다. 픽스처 `wrapped_populate`(그 가지를 지우면 RED 확인).

## 5. 운영에서 다를 수 있는 것

- 운영 DB 행이 4건 더 많다(1,703). 그 4건이 두 은행과 slug가 겹치면 `LOAD_VERDICT=SLUG_CONFLICT`로 [F]가 거부된다.
- 운영 `hints`에는 P3-32 운영 적재분(1,324)이 이미 있다 — P3-32 재실행 시 그 행은 `unchanged`로 남는다.
