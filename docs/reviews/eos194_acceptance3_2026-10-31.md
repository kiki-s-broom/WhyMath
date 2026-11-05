# EOS-194 인수 조건 ③ — 운영 DB 실측 기록 (2026-10-31)

> **판정 기준: main `d994dc07`** (EOS-195 머지 이후) · 측정 코드 = 이 문서와 같은 커밋의 `eos194_acceptance3_2026-10-31/eos194_measure.py`(브랜치 `claude/eos-194-acceptance3-measure`)
> **상태: 측정 완료(2026-10-31 · Kiki 실행) — 발행 가능 후보 0건으로 [W] 미실행. 인수 조건 ③ 미충족(차단 = 힌트 미연결 · 소유 P3-32 blocked).**
> 인수 조건 ③(대장 원문): "실제 호출 표면으로 문항 1건을 발행해 submit_attempt가 outcome=pinned를 내고
> problem_attempt.problem_version_id가 채워짐을 확인하고, 운영 DB에서 problem.problem_version_id IS NOT NULL
> 문항 수를 분모(전체 노출 문항 수)와 함께 보고한다. 0건이면 0건이라고 적는다."

## 1. 무엇을 쓰는가 (운영 DB 쓰기 범위)

| 쓰기 | 건수 | 되돌리기 |
|---|---:|---|
| `user_profile` — 측정 전용 계정 2개(`eos194-measure-staff` = content_admin · `eos194-measure-learner` = student, 연령 미상) | 2 | 학습자는 `DELETE /v1/me`로 삭제 · staff는 감사 행이 참조하므로 남긴다 |
| `problem_version` — 발행 대상 문항 1건의 판 1개(DRAFT → … → PUBLISHED) | 1 | `deprecate` 전이(포인터 NULL) |
| `problem.problem_version_id` — 그 문항의 발행 포인터 | 1 | 같은 `deprecate` |
| `privacy_audit` — 전이 5건(create·submit·pass_review·approve·publish) | 5 | 남긴다(감사 기록) |
| `problem_attempt` + 숙달·학습 상태 행 — 측정 학습자의 시도 1건 | 1+ | `DELETE /v1/me`가 학습자 데이터 전부 삭제 |

발행 대상은 스크립트가 스스로 고른다: 서빙 노출 풀(`candidate_pool_conditions`) · 포인터 없음 · 검증된 힌트 ≥1 · 판 이력 없음 ·
7필드(P3-04) 충족 · 라이브 스냅숏 계약 충족 중 `problem_id` 오름차순 첫 1건. 후보가 0이면 **쓰지 않고 거부**한다.

## 2. 측정 방법

- 도구: `docs/reviews/eos194_acceptance3_2026-10-31/eos194_measure.py`(ASCII 전용 — PowerShell 5.1 인코딩 왕복 방지).
  모드 3개: `preflight`(읽기 전용) · `publish`(쓰기 — 내부에서 preflight를 다시 돌려 후보 0·스키마 불일치면 거부) ·
  `deprecate`(되돌리기 — 상태 파일이 없으면 거부).
- 호출 표면은 운영 코드 그대로다: `create_app()`의 라우트를 in-process로 부르고(`/v1/admin/cms/problems/{id}/drafts` →
  `/v1/admin/cms/problem-versions/{id}/transitions` ×4 → `/v1/me/attempts`), 인증은 실제 `get_current_user`(JWT 서명 키는
  이 프로세스 전용 난수). 판정은 응답 코드만이 아니라 **DB를 다시 읽어** 한다(포인터·시도 행·판 상태).
- 분모·분자는 EOS-194 §5.2 런북 SQL 그대로(노출 = 난이도 보유 · 본문 미보유 출처 제외 · approved).
- 샌드박스 사전 검증(로컬 PostgreSQL 16, 운영 아님): 스키마 불일치 거부 · 후보 0 거부 · 발행 성공
  (`EOS194_ACCEPTANCE3_OK=True` · 증분 분모 0 / 분자 +1) · 재발행 거부 · 되돌리기 성공(포인터 NULL) · 재되돌리기 거부 — 전부 통과.

## 3. 결과 (Kiki 실행 · 운영 DB `whymath-pg` 5433 · 측정 코드 커밋 `14557bbe`)

[A] 작업 폴더 HEAD `14557bbe` 일치 · 실행 코드 출처 = 작업 폴더(`WhyMath-01C\src\backend\whymath_backend`) · 컨테이너 가동 · 상태 파일 없음 — 전부 True.

[B] `preflight` (읽기 전용) — `PREFLIGHT_EXIT=3`:

| 항목 | 값 |
|---|---:|
| 스키마 | `a8c4e1f7b3d9` = head (`SCHEMA_AT_HEAD=True`) |
| 전체 문항 | 1,703 |
| **노출 문항(분모)** | **1,699** |
| **포인터 채워진 노출 문항(분자)** | **0** |
| 포인터 채워진 문항(전체) | 0 |
| PUBLISHED 판 | 0 |
| 노출·포인터 없음 중 검증된 힌트 보유 | **0** |
| 발행 가능 후보(7필드 충족) | **0** |
| 표본 50건 미충족 필드 | `hint_strategy` 50 · `misconception_signature` 39 · `skill` 5 |

[W] **미실행** — 블록 설계대로 후보 0이면 쓰지 않는다. 운영 DB 쓰기 0건.

## 4. 판정

- **인수 조건 ③ 미충족.** 운영 DB의 발행 포인터 채움은 **0/1,699**(0건이면 0건이라고 적는다). `outcome=pinned`의 운영 확인은 **할 수 없었다** — 발행할 수 있는 문항이 0건이다.
- **끊긴 지점**: 발행 게이트(P3-04 `problem_metadata_complete`)가 7필드를 요구하는데, 운영 DB의 노출 문항에 **검증된 힌트(`hints.verified=true`)가 한 건도 연결돼 있지 않다** → `hint_strategy` 전수 미충족. 표본에서는 오개념 서명(39/50)·스킬(5/50)도 비어 있다.
- **소유 태스크**: `P3-32-core-concept-hint-link`(blocked — Kiki 머신 DB 필요). 대장에 EOS-194 → P3-32 선행을 CLI로 걸었다. 오개념 서명·스킬 결손의 소유 태스크는 찾지 못했다(검색: 대장 미완료 태스크 제목의 `misconception_signature`·`behavior_skills` — 범위를 밝혀 둔다).
- **발행 표면 자체**는 샌드박스 실 PG에서 6시나리오 통과(§2) — 막힌 것은 표면이 아니라 운영 데이터의 7필드다.
- EOS-195 드리프트 리포트의 운영 분모도 0이라 **측정 불성립**(통과 아님).
- EOS-194는 `review`에 둔다(done 아님). P3-32 착지 뒤 같은 블록([A]→[B]→[W])을 다시 실행하면 된다.

## 5. 재측정 — 인수 조건 ③ 충족 (2026-11-05 · Kiki 실행)

> **판정 기준: main `920cc624`**(런북 `docs/ops/eos194_publish_measure_runbook.md` · 측정 코드 같은 커밋) · 운영 DB `whymath-pg`(5433)
> · 선행 착지: P3-32·P3-97(#1834 · 검증 힌트 연결) · P3-99(#1839 · 원자 개념 `code` 상속)

[A]~[F]를 임시 worktree `WhyMath_wt_920cc624`에서 실행했다. 백업 `eos194_before.dump`(2,220,090바이트) 뒤 발행했다.
증거 파일: Kiki 머신 `work\eos194_920cc624\publish.kv`·`eos194_state.json`·`preflight_before.kv`.

**발행 전(`publish.kv` 앞부분)**: 전체 문항 2,567 · 노출 2,563 · 포인터 0 · PUBLISHED 판 0 · 검증 힌트 보유 노출 문항 979 ·
`SCANNED=979` · `SCAN_TRUNCATED=False` · **`PUBLISHABLE=76`** · `NOT_PUBLISHABLE_REASONS={"misconception_signature": 903}` ·
`ATOM_MISCONCEPTION_ROWS=0`.

**발행 측정**: 대상 문항 `03cd2daa-a36c-52c9-bd6b-ddb9caf67a48` · 판 `511a4720-2572-4f39-85b0-7e40bdaef86a`(2026-11-05 01:22:27Z) ·
초안 201 → 제출·검토 통과·승인·발행 각 200 · 측정 학습자 시도 201(`c9a18ae4-5fb3-400f-bb70-9681be901ebf`) ·
`LOG_OUTCOME_PINNED=True` · `VERSION_STATUS=PUBLISHED` · `PROBLEM_POINTER_MATCH=True` · `ATTEMPT_PIN_MATCH=True` ·
`DRIFT={"drifted": 0, "in_sync": 1, …}` · **`EOS194_ACCEPTANCE3_OK=True`**.

**인수 조건 ③ 보고값**: 포인터 채워진 노출 문항 **1 / 2,563**(전체 포인터 1 · PUBLISHED 판 1). 발행 후 [C]를 다시 돌린 결과도
`PUBLISHED_VERSIONS=1`·`EXPOSED_WITH_POINTER=1`로 일치했다(12:04 · 그때 `PUBLISHABLE=75` — 발행된 1건이 후보에서 빠졌다).

**정직한 단서**

- 운영 DB에는 원자 유래 오개념(`ATOM:`)이 **0행**이다. 그래서 운영의 발행 가능 76건은 P3-99의 `code` 상속 경로를 거치지 않고,
  문항 자체 서명이나 구 카탈로그 상속으로 통과한 것으로 본다(문항별 출처는 측정하지 않았다). P3-99 경로는 리허설 DB에서만
  실증됐다(`docs/reviews/p3_99_atom_inheritance_rehearsal_2026-11-04.md` · 0 → 861).
- 나머지 903건은 여전히 오개념 서명 결손이다. 런북 [C2](원자 오개념 적재)는 `PUBLISHABLE=0`일 때만 실행되도록 막혀 있어 이번에는
  스스로 거부했다(쓰기 0). 적재 여부는 Kiki 판단으로 남긴다.
- 발행된 판 1건은 운영 DB에 그대로 있다. 되돌리기 [G]는 실행하지 않았다(선택 · Kiki 판단).
