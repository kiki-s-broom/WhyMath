# EOS-194 인수 조건 ③ — 운영 DB 실측 기록 (2026-10-31)

> **판정 기준: main `d994dc07`** (EOS-195 머지 이후) · 측정 코드 = 이 문서와 같은 커밋의 `eos194_acceptance3_2026-10-31/eos194_measure.py`(브랜치 `claude/eos-194-acceptance3-measure`)
> **상태: 측정 전** — Kiki 실행 결과가 오면 §3을 채운다.
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

## 3. 결과 (Kiki 실행 후 기입)

_측정 전._
