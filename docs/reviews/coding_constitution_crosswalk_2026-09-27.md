# 코딩 헌법 × 저장소 대조표 — 규칙 95건·원본 9건·파이프라인·꾸러미 자체 검증·계획 어휘 (CONST-02)

- 판정 기준: 조사 = main `b8af6f26`(2026-09-26 · PR #1321) · 계획 기록 재확인 = main `a0e60965`(2026-09-28) · 작성 2026-09-28
- 조사 방식: 규칙 묶음 11개(G01~G11)를 병렬 조사 → 묶음별 **독립 재검증**(다른 에이전트가 증거를 다시 실측) → 비평가 1회(조사가 놓친 곳 찾기). 증거 등급 E3 = 실행 출력 · E2 = 파일·줄 직접 확인 · E1 = 정황 · E0 = 문서 주장뿐
- 이 문서의 "저장소 현황" 열은 **조사 시점(이 PR 이전)** 상태다. 이 PR이 착지시킨 것은 "배정" 열이 `CONST-02 착지`인 5건이다
- 이식 정본: `docs/standards/coding_constitution_transplant.md` · 런북: `docs/ops/coding_constitution_kiki_runbook.md`

## 1. 요약 수치

| 항목 | 값 |
|---|---|
| 규칙 | 95건 = v1.0 14건(R0~R4) + v1.1 추가 81건(R5~R29) |
| 저장소 현황(조사 시점) | 없음 22 · 부분 68 · 코드 있음 4 · 해당 없음 1 — 재검증 후 최종: 없음 20 · 부분 70 · 코드 있음 4 · 해당 없음 1 |
| 재검증 판정 | 확인 74 · 정정 20 · 반박 1(R18-04) |
| 배정 | CONST-02 착지 5(그중 R1-01~03·R4-01 4건은 3단계 판정을 CONST-03이 이어받음) · CONST-03 9 · CONST-04 15 · CONST-05 8 · CONST-06 9 · CONST-07 15 · CONST-08 33 · CONST-09(+08) 1 |
| 원본 등록부 | 9건 중 제안 경로 부재 6 + 외부 원본 판 표기 자리표시자 1 = 차단 7 → A0003 정정안으로 0(모의 실측) |
| 파이프라인 | 꾸러미 제안 12노드 → 저장소 실측 기반 28노드(`pipeline.yaml`) |

"없음"이라고 적은 규칙도 **기능이 없다는 뜻이 아니라**, 그 규칙이 요구하는 형태의 집행 장치(파일·CI 스텝)가 없다는 뜻이다. 예를 들어 R5-01(코어→과목 의존 금지)은 import-linter 계약이 이미 CI에서 돌지만 등록부의 check 경로(`.importlinter`)와 다르다 — 이런 경우는 "부분"이나 "코드 있음"으로 적었다.

## 2. 원본 등록부 9건

정정 경로·근거·증거 등급은 개정 초안 `docs/constitution_proposals/A0003_sources_registry_draft.md`의 「정정 내역」 표가 정본이다(같은 표를 두 곳에 두면 한쪽이 낡는다 — 헌법 제7조). 요점만 적는다.

- 제안 경로 6건(`content/*.yaml` 3 · `schemas/item.schema.json` · `docs/copyright/…v2.0.md` · `docs/planning/…xlsx`)이 저장소에 없다 — 이 저장소의 정본은 JSON 코퍼스·Pydantic 모델·enum·라이선스 매트릭스·기계 도출 장부다.
- 외부 원본 "성취기준"의 판 표기가 자리표시자("고시 번호·판 확인 후 기입")였다 — 원본 `audit.py`는 이것을 ✅로 통과시켰다(패치 ⓒ로 위반 처리).
- `pipeline.yaml`은 꾸러미에 동봉된 제안본이라 꾸러미 안에서만 ✅였다 — 저장소에는 없었으므로 그대로 이식하면 차단은 7건이다. 이 PR이 저장소 실측 기반 28노드로 새로 썼다.

## 3. 규칙 95건 대조

배정 기준: 장(chapter) 0~4 → CONST-03 · 5~8·28 → CONST-04 · 9~11 → CONST-05 · 12~14 → CONST-06 · 15~19 → CONST-07 · 20~27·29 → CONST-08. 이 PR이 집행 장치를 착지시킨 R0-01(가드)·R1-01/R1-03(파이프라인 검사 CI)·R1-02(`--downstream`)·R4-01(원본 등록부 심사 — 래칫)은 `CONST-02 착지`, R22-03(학생 입력 CAS 파싱)은 학생 안전 우선순위 1이라 `CONST-09`로 앞당겼다.

| ID | 조문 요지 | 단계 | 저장소 현황 | 재검증 | 가장 가까운 저장소 집행 지점 | 배정 |
|---|---|---|---|---|---|---|
| R0-01 | AI는 constitution/ 폴더를 수정·삭제·이동할 수 없다 | 2 | 없음 | 확인 | .claude/settings.json:permissions.deny | CONST-02 착지 |
| R0-02 | constitution/ 이 바뀐 커밋에는 amendments/ 의 새 개정 기록이 함께 있어야 한다 | 3 | 부분 | 확인 | scripts/harness/rules.py:288 (lint) · .github/workflows/ci.yml:1538-1… | CONST-03 |
| R1-01 | 파이프라인 실행 순서는 pipeline.yaml 한 곳에만 선언하며, 누락·순환·섬 노드가 없어야 한다 | 3 | 부분 | 확인 | scripts/harness/store.py:465 (DependencyGraph) · :623 graph_cycles · … | CONST-02 착지 → 3단계 판정 CONST-03 |
| R1-02 | 어떤 노드를 바꿨을 때 다시 실행할 하류 노드를 명령 한 줄로 구할 수 있어야 한다 | 3 | 부분 | 확인 | scripts/harness/ci_job_coverage.py:1-30 · :598-604 (scope 서브커맨드) | CONST-02 착지 → 3단계 판정 CONST-03 |
| R1-03 | 저작권 판정·백업·교육과정 정합성 검토는 pipeline.yaml의 노드이며, 저작권 판정은 게시의 상류에 있어야… | 3 | 부분 | 정정 | src/backend/whymath_backend/ops/provenance_audit.py:1-50 · .github/wo… | CONST-02 착지 → 3단계 판정 CONST-03 |
| R2-01 | 게시 테이블은 중복·품질·저작권 게이트 통과 기록이 없는 문항을 DB 수준에서 거부한다 | 5 | 부분 | 확인 | src/backend/whymath_backend/db/models/problem.py:29 | CONST-03 |
| R2-02 | 중복 게이트 판정과 무관하게 모든 후보 문항은 사람 품질 판정(F1~F8)을 받는다 | 3 | 부분 | 확인 | src/backend/whymath_backend/harness/needs_review_worklist.py:152 | CONST-03 |
| R2-03 | 게이트 기록에는 판정자·일시·근거·우회 여부 필드가 있어야 한다 | 3 | 부분 | 확인 | src/backend/whymath_backend/schema/review_timer.py:143 | CONST-03 |
| R2-04 | 사람 검토 세션의 검토 소요 시간 중앙값이 10초 미만이거나 반려율이 0%이면 경고한다 (도장 찍기 조기 경보) | 3 | 부분 | 확인 | src/backend/whymath_backend/ops/hit_cu_metrics.py:635 | CONST-03 |
| R3-01 | 모든 배치 스크립트는 두 번 실행해도 행 수와 결과가 같아야 한다 ('두 번 실행 테스트' 필수) | 3 | 부분 | 확인 | tests/backend/l1/problem_bank/test_populate_integration.py:282 | CONST-03 |
| R3-02 | AI 문항 생성은 출력이 아니라 생성 자리(slot_key) 기준으로 중복을 막으며, items.slot_key에… | 5 | 부분 | 확인 | src/backend/alembic/versions/20260528_1801_4c6d083dfeef_initial_probl… | CONST-03 |
| R4-01 | 저장소 안의 원본은 모두 아래 sources에 등록되어 있고 실제로 존재한다 (L5 · 원본 stage 1) | 1 | 부분 | 확인 | tests/backend/test_failure_prevention_manifest.py:129 | CONST-02 착지 → 3단계 판정 CONST-03 |
| R4-02 | Python·Dart 데이터 모델은 schemas/ 의 JSON Schema에서 자동 생성되며, 재생성 결과가 커… | 3 | 없음 | 확인 | schemas/v1.1/problem.schema.yaml:4-6 | CONST-03 |
| R4-03 | 문서에 적힌 핵심 숫자(개념 노드 수·오개념 수·시그니처 패턴 수)는 원본에서 센 실제 값과 같아야 한다 (L5 … | 2 | 부분 | 정정 | tests/backend/l1/test_node_granularity_governance.py:51 | CONST-03 |
| R5-01 | 모듈 의존 방향은 api → infra → subject_* → eos_core 이며 역방향 import를 금지한… | 1 | 코드 있음 | 확인 | src/backend/pyproject.toml:221-256 | CONST-04 |
| R5-02 | eos_core는 DB 드라이버·AI SDK를 직접 import하지 않는다 (L5 · 원본 stage 3 · li… | 2 | 부분 | 확인 | scripts/ops/check_provider_seat_contract.py:81-110 | CONST-04 |
| R6-01 | AI 출력과 외부 입력은 경계에서 스키마로 파싱하며, 실패하면 재시도 후 격리한다 | 3 | 부분 | 정정 | src/backend/whymath_backend/l3/equivalent/llm_generator.py:469-495 | CONST-04 |
| R6-02 | 스키마 변경은 과거 실제 데이터 표본으로 호환성 테스트를 통과해야 한다 | 3 | 부분 | 정정 | .github/workflows/ci.yml:591-700 (backend-migrations 잡) | CONST-04 |
| R6-03 | 경계를 넘는 모든 데이터 스키마에는 schema_version 필드가 있다 | 3 | 부분 | 정정 | src/backend/whymath_backend/schema/problem.py:430 + tests/backend/sch… | CONST-04 |
| R7-01 | 문항 상태는 status 한 컬럼으로만 표현하며 상태를 뜻하는 불리언 플래그 컬럼을 두지 않는다 | 4 | 부분 | 확인 | src/backend/whymath_backend/schema/enums.py:703-745 | CONST-04 |
| R7-02 | 상태 전이는 전이표(item_transitions)에 있는 것만 DB가 허용한다 | 4 | 부분 | 확인 | src/backend/alembic/versions/20260914_0000_67cf48ad3bce_concept_versi… | CONST-04 |
| R8-01 | 비밀값(API 키·비밀번호·암호화 키)은 저장소에 커밋될 수 없다 | 3 | 부분 | 확인 | .github/workflows/ci.yml:1444-1458 (policy-guard 잡 'Forbid hardcoded … | CONST-04 |
| R8-02 | 앱 빌드 산출물에 서버용 비밀 키 패턴이 없어야 한다 | 4 | 없음 | 확인 | .github/workflows/ci.yml:828-907 (mobile 잡) | CONST-04 |
| R8-03 | 서버는 필수 설정이 빠지면 시작하지 않고 즉시 종료한다 | 3 | 부분 | 정정 | src/backend/whymath_backend/app.py:671-697 (_lifespan) + db/schema_ve… | CONST-04 |
| R8-04 | 백업 암호화 비밀키는 백업과 다른 곳 2곳 이상에 보관하고 위치를 기록한다 (L2 · 원본 stage 1 · ch… | 1 | 부분 | 확인 | docs/architecture/db_backup_dr_runbook.md:99-105 | CONST-04 |
| R9-01 | 커밋 메시지는 Conventional Commits 형식(content 타입 포함)을 따른다 | 3 | 없음 | 확인 | scripts/harness/backlog.py:321 | CONST-05 |
| R9-02 | 한 커밋의 변경 파일이 25개를 넘으면 경고한다 | 3 | 부분 | 정정 | .github/workflows/ci.yml:80 | CONST-05 |
| R9-03 | 코드 변경과 콘텐츠 변경을 한 커밋에 섞으면 경고한다 | 4 | 없음 | 확인 | .github/workflows/ci.yml:105 | CONST-05 |
| R10-01 | DB 스키마는 migrations/ 파일로만 바꾸며, 적용된 마이그레이션 파일은 수정하지 않는다 | 3 | 부분 | 확인 | .github/workflows/ci.yml:647 | CONST-05 |
| R10-02 | DROP·RENAME이 든 마이그레이션은 contract 표식과 선행 expand 번호가 있어야 한다 | 4 | 없음 | 확인 | docs/architecture/deployment_cd_runbook.md:280 | CONST-05 |
| R10-03 | 마이그레이션은 자동 백업을 만들고 확인한 뒤에만 적용된다 | 4 | 부분 | 확인 | scripts/backup/backup_whymath_pg.ps1:1 | CONST-05 |
| R11-01 | 린트 위반 수는 파일별 기준선보다 늘어날 수 없다 (래칫) | 3 | 부분 | 확인 | .github/workflows/ci.yml:379 | CONST-05 |
| R11-02 | 기준선은 줄어드는 방향으로만 갱신되며, 늘리려면 개정 기록이 필요하다 | 3 | 부분 | 정정 | src/backend/whymath_backend/ops/provenance_audit.py:1 | CONST-05 |
| R12-01 | 단위 테스트는 네트워크에 접속하지 않는다 | 3 | 부분 | 확인 | tests/backend/conftest.py:60 | CONST-06 |
| R12-02 | fix: 커밋에는 재현 테스트 변경이 함께 있어야 한다 | 3 | 없음 | 확인 | .github/pull_request_template.md:12 | CONST-06 |
| R12-03 | 단위 테스트 전체 실행 시간은 60초 이내여야 한다 | 4 | 부분 | 확인 | .github/workflows/ci.yml:348 | CONST-06 |
| R13-01 | 정답 재도출 검증은 생성 단계의 정답을 입력으로 받지 않는다 (블라인드) | 1 | 부분 | 확인 | src/backend/whymath_backend/l3/cross_verify.py:283 | CONST-06 |
| R13-02 | 재도출 검증은 생성과 다른 방법(CAS) 또는 다른 모델 계열을 쓴다 | 3 | 부분 | 확인 | src/backend/whymath_backend/l3/cross_verify.py:796 | CONST-06 |
| R13-03 | 검증 층 간 일치율이 4주 연속 100%이면 경고한다 (복사 의심) | 5 | 없음 | 확인 | src/backend/whymath_backend/ops/qa_confusion_matrix.py:41 | CONST-06 |
| R14-01 | 저장소의 모든 .py 파일은 린트 검사 범위 안에 있어야 한다 | 1 | 부분 | 확인 | tests/infra/test_lint_coverage.py:288 | CONST-06 |
| R14-02 | 검사 도구(ruff·mypy·pytest 등) 버전은 잠금 파일로 고정한다 | 3 | 부분 | 확인 | src/mobile/pubspec.lock:1 | CONST-06 |
| R14-03 | Dart 분석은 info 수준까지 실패로 처리한다 | 2 | 없음 | 확인 | .github/workflows/ci.yml:868 | CONST-06 |
| R15-01 | 백엔드 코드는 print() 대신 구조화 로그를 쓴다 (L5 · 원본 check=pyproject.toml · r… | 3 | 부분 | 확인 | src/backend/pyproject.toml:184 | CONST-07 |
| R15-02 | 모든 배치는 run_id와 created·skip·failed 요약을 구조화 로그로 남긴다 (L4 · 원본 che… | 4 | 부분 | 확인 | src/backend/whymath_backend/harness/problem_corpus_accumulate.py:241-… | CONST-07 |
| R15-03 | 로그에 개인정보가 평문으로 남지 않는다 (L5 · 원본 check=tests/constitution/test_lo… | 3 | 부분 | 확인 | src/backend/whymath_backend/ops/log_scrubber.py:163-231 | CONST-07 |
| R16-01 | 백업 파일은 age 암호화 헤더와 최소 크기 검사를 통과해야 한다 (L5 · 원본 check=scripts/con… | 4 | 부분 | 확인 | scripts/backup/backup_whymath_pg.ps1:174-179 | CONST-07 |
| R16-02 | 마지막 복원 훈련이 35일 이상 지나면 경고한다 (L4 · 원본 run=check_backups.py --dril… | 4 | 부분 | 정정 | backlog/gates.yaml:100-108 | CONST-07 |
| R16-03 | 최근 48시간 백업 사본이 서로 다른 위치 2곳 이상에 있어야 한다 (L4 · 원본 run=check_backup… | 4 | 부분 | 정정 | scripts/backup/backup_whymath_pg.ps1:46-54,308-330 | CONST-07 |
| R17-01 | 모든 판례의 '이제 무엇이 막는가'에는 규칙 ID가 하나 이상 있다 (L5 · 원본 check=scripts/co… | 3 | 부분 | 확인 | scripts/harness/incidents.py:145-197 | CONST-07 |
| R17-02 | 게이트 우회(bypass) 기록마다 판례가 있다 (L4 · 원본 run=check_precedents.py --b… | 4 | 부분 | 확인 | scripts/harness/backlog.py:1515-1517,4654-4658 | CONST-07 |
| R18-01 | task/ 브랜치에는 목표·범위·완료 조건을 적은 TASK.md가 있다 | 3 | 부분 | 확인 | scripts/harness/models.py:133 | CONST-07 |
| R18-02 | AI는 TASK.md의 수정 허용 범위 밖 파일을 편집할 수 없다 | 3 | 부분 | 확인 | scripts/harness/backlog.py:4131 | CONST-07 |
| R18-03 | 테스트 잠금이 선언된 작업에서 AI는 tests/를 수정할 수 없다 | 4 | 없음 | 확인 | scripts/harness/models.py:44 | CONST-07 |
| R18-04 | 작업 1건의 변경이 400줄 또는 파일 10개를 넘으면 경고한다 | 4 | 부분 | 반박 | scripts/harness/backlog.py:4040 | CONST-07 |
| R19-01 | 검토 도구는 사람이 판정을 입력하기 전에 AI 참고 판정을 보여주지 않는다 | 4 | 없음 | 확인 | src/backend/whymath_backend/harness/review_session.py:393 | CONST-07 |
| R19-02 | 검토 세션에는 정답을 아는 보정 문항이 10% 이상 섞인다 | 4 | 부분 | 확인 | src/backend/whymath_backend/harness/defect_detection_eval.py:198 | CONST-07 |
| R19-03 | 보정 문항 정답률 80% 미만인 세션의 판정은 재검토 대상으로 표시된다 | 4 | 부분 | 확인 | src/backend/whymath_backend/harness/defect_detection_eval.py:157 | CONST-07 |
| R20-01 | 개념 그래프에는 선수 관계 순환이 없다 | 1 | 코드 있음 | 확인 | src/data-pipeline/data_pipeline/atom_graph/validate.py:103-167 | CONST-08 |
| R20-02 | 모든 개념 노드는 원본 목록에 실재하는 성취기준 1개 이상에 연결된다 (보조 노드는 표식) | 2 | 부분 | 정정 | src/data-pipeline/data_pipeline/atom_graph/validate.py:14,149-153,232… | CONST-08 |
| R20-03 | 선수 노드의 학년은 대상 노드보다 높을 수 없다 (허용목록 예외) | 3 | 부분 | 정정 | src/data-pipeline/data_pipeline/concept_graph/validate.py:123-128,278… | CONST-08 |
| R20-04 | 추이적으로 중복된 선수 간선은 경고한다 | 3 | 없음 | 확인 | src/data-pipeline/data_pipeline/graph_analytics/analytics.py:1-45,166 | CONST-08 |
| R20-05 | 한 번 발급된 노드 ID는 삭제·재사용하지 않고 deprecated로만 표시한다 | 3 | 부분 | 확인 | data/corpus/concept_graph_v1/ids.yaml:1-22 + src/data-pipeline/data_p… | CONST-08 |
| R21-01 | 콘텐츠 파일은 스키마·필수 필드·LaTeX 괄호 린트를 통과한다 | 2 | 부분 | 정정 | src/backend/whymath_backend/l3/equivalent/latex_gate.py:1-88 | CONST-08 |
| R21-02 | 학습자 응답은 (item_id, revision)을 함께 기록한다 | 5 | 없음 | 확인 | src/backend/whymath_backend/db/models/activity.py:179-196 | CONST-08 |
| R21-03 | 콘텐츠 릴리스는 매니페스트(버전·해시)로 원자적으로 배포·롤백된다 | 5 | 없음 | 확인 | docs/architecture/44_eos_version_management.md:18,243-296,365 | CONST-08 |
| R21-04 | 콘텐츠 문자열(특히 수식)에 제어 문자가 있으면 실패한다 (YAML 이스케이프 손상 탐지) | 2 | 부분 | 확인 | scripts/ops/cp949_guard.py:1-30,114-116 + .github/workflows/ci.yml:14… | CONST-08 |
| R22-01 | CAS로 검증 가능한 문항은 정답 선지가 정확히 1개임을 확인한다 | 3 | 부분 | 확인 | tests/backend/l1/problem_bank/test_corpus_quality.py:249 | CONST-08 |
| R22-02 | 모든 수식은 KaTeX 파싱을 통과한다 | 3 | 부분 | 정정 | src/backend/whymath_backend/l3/equivalent/latex_gate.py:46 | CONST-08 |
| R22-03 | 학생 입력 수식은 허용 문자 검사를 통과한 뒤에만 CAS로 파싱한다 | 3 | 부분 | 확인 | src/backend/whymath_backend/api/verify.py:42 | CONST-09 · CONST-08 |
| R23-01 | 응답 이벤트 테이블은 추가만 가능하다 (UPDATE·DELETE 차단) | 5 | 없음 | 정정 | src/backend/alembic/versions/20260914_0000_67cf48ad3bce_concept_versi… | CONST-08 |
| R23-02 | 모든 숙달 판정 기록에는 model_version이 있다 | 3 | 부분 | 확인 | src/backend/whymath_backend/l2/mastery_contract.py:126 | CONST-08 |
| R23-03 | BKT 파라미터는 퇴화 방지 범위(추측 ≤ 0.3, 실수 ≤ 0.1)를 지킨다 | 3 | 부분 | 확인 | src/backend/whymath_backend/l2/bkt.py:58 | CONST-08 |
| R23-04 | 모델·파라미터 변경은 과거 응답 재생 비교 보고서가 있어야 배포된다 | 6 | 없음 | 확인 | src/backend/whymath_backend/harness/attempt_grading_shadow_report.py:1 | CONST-08 |
| R24-01 | 문항 통계(정답률·변별도·선지 선택률)를 주 1회 계산한다 | 6 | 부분 | 확인 | src/backend/whymath_backend/l1/problem_bank/answer_distribution.py:53 | CONST-08 |
| R24-02 | 응답 30건 이상에서 변별도가 -0.1 미만인 문항은 자동 격리된다 | 6 | 부분 | 정정 | src/backend/whymath_backend/schema/enums.py:725 | CONST-08 |
| R24-03 | 문항 난이도에는 출처(ai_estimate / empirical)가 표기된다 | 3 | 부분 | 확인 | src/backend/whymath_backend/schema/problem.py:637 | CONST-08 |
| R25-01 | 튜터 응답은 출력 가드를 통과해야 학생에게 전달된다 | 3 | 부분 | 확인 | src/backend/whymath_backend/harness/wh1_primary.py:292 | CONST-08 |
| R25-02 | 프롬프트·모델 변경 시 튜터 평가셋 통과율이 기준선 이상이어야 한다 | 4 | 부분 | 확인 | .github/workflows/ci.yml:473 | CONST-08 |
| R25-03 | 위기 신호가 담긴 입력에는 정해진 안전 응답과 도움 경로가 반환된다 | 3 | 없음 | 확인 | docs/strategy/risks.md:98 | CONST-08 |
| R25-04 | 프롬프트는 prompts/ 파일로 버전 관리하며 코드 안 문자열로 두지 않는다 | 3 | 부분 | 확인 | src/backend/whymath_backend/l3/prompt_assets.py:1 | CONST-08 |
| R26-01 | 개인정보 인벤토리에 없는 개인정보 필드는 저장할 수 없다 | 3 | 부분 | 정정 | src/backend/whymath_backend/privacy/erasure.py:106 | CONST-08 |
| R26-02 | 외부 AI API로 가는 요청은 개인정보 차단기를 통과한다 | 3 | 부분 | 확인 | src/backend/whymath_backend/l3/router.py:570 | CONST-08 |
| R26-03 | 앱의 제3자 SDK는 허용목록에 있는 것만 쓴다 | 3 | 부분 | 확인 | src/mobile/test/pubspec_dependency_usage_governance_test.dart:1 | CONST-08 |
| R26-04 | 만 14세 미만 계정은 법정대리인 동의 확인 전까지 개인정보 처리 기능이 잠긴다 | 3 | 부분 | 정정 | src/backend/whymath_backend/api/_auth.py:157 | CONST-08 |
| R27-01 | 모든 문항은 출처 필드(유형·근거·생성 모델·라이선스)를 가진다 | 3 | 부분 | 확인 | src/backend/whymath_backend/ops/provenance_audit.py:12 | CONST-08 |
| R27-02 | 유사도 검사 기록이 없는 문항은 게시할 수 없다 | 4 | 부분 | 정정 | src/backend/whymath_backend/harness/golden_promotion_gate.py:1 | CONST-08 |
| R27-03 | 이미지·폰트 등 에셋은 라이선스 목록에 등록되어야 한다 | 3 | 없음 | 확인 | docs/data/license_snapshot_archive.md:1 | CONST-08 |
| R28-01 | 과목 패키지끼리는 서로 import하지 않는다 (L5 · 원본 stage 3 · lint-imports) | 3 | 해당 없음 | 확인 | src/backend/pyproject.toml:272-316 | CONST-04 |
| R28-02 | 모든 과목 어댑터는 코어가 소유한 계약 테스트를 통과한다 (L5 · 원본 stage 3 · pytest tests… | 1 | 코드 있음 | 확인 | tests/backend/schema/test_subject_adapter.py:90 | CONST-04 |
| R28-03 | 허수아비 과목 어댑터가 계약 테스트를 통과해 코어의 과목 독립성을 증명한다 (L5 · 원본 stage 3 · py… | 1 | 코드 있음 | 확인 | tests/backend/schema/test_subject_adapter_physics_stub.py:119 | CONST-04 |
| R28-04 | 과목 어댑터는 코어 필수 게이트를 제거할 수 없다 (L5 · 원본 stage 3 · pytest -k core_g… | 2 | 부분 | 확인 | src/backend/whymath_backend/l4/subject_adapter_math.py | CONST-04 |
| R29-01 | 기준 기기에서 첫 화면 3초·반응 0.1초 성능 예산을 측정한다 | 5 | 부분 | 확인 | docs/standards/incident_response_slo.md:48 | CONST-08 |
| R29-02 | 네트워크가 끊겨도 작성 중인 답안이 보존된다 | 3 | 없음 | 확인 | src/mobile/lib/core/token_store.dart | CONST-08 |
| R29-03 | 모든 수식 콘텐츠에는 읽기 텍스트가 있다 | 3 | 부분 | 정정 | src/mobile/lib/features/chat/presentation/scene_renderer.dart:186 | CONST-08 |
| R29-04 | 교실 35명 동시 접속 부하 시험을 공개 전과 주요 변경 후 실행한다 | 5 | 없음 | 확인 | docs/standards/testing.md:150 | CONST-08 |

규칙마다의 상세 증거(파일:줄·실행 출력)와 재검증 메모는 조사 원자료에 있고, 각 CONST 태스크가 착수할 때 그 파트의 행을 다시 실측한다(판정 시점이 다르면 증거도 낡는다).

## 4. 꾸러미 자체 검증 — 설치 전에 꾸러미의 주장을 먼저 재현했다

꾸러미 README·도구 docstring의 주장 16건을 모의 저장소에서 재현했다(E3). 주장대로 동작한 것: 첫 심사의 차단(원본 등록부)·`--report`·`--sources-only`·파이프라인 검사 3종·`merge_rules.py` 미리보기/반영/중복 거부·v1.1 심사의 "규칙이 sources로 흡수됨" 차단·단계별 차단 수·`--hook` 모드. 표준북 파트 정리 장 6개와 `rules_additions_v1.1.yaml` 81건은 ID·강도·단계·조문·문구 5열이 전건 일치했다.

재현 중 발견해 **패치로 고친 결함**(`scripts/constitution/UPSTREAM.md` 패치 목록이 정본):

| 결함 | 증상 | 조치 |
|---|---|---|
| L4·L5 규칙의 `run`이 비면 배선 검사가 항상 통과 | `"" in 워크플로텍스트`가 참 → 실행 없이 ✅ (주입 실측) | 패치 ⓑ — "집행 장치 없음" 차단 |
| 외부 원본 판 표기 자리표시자 통과 | `bool(version)`만 봄 | 패치 ⓒ — 자리표시자 목록 위반 |
| 심사 불가와 위반이 같은 종료 코드 | 일반 모드에서 둘 다 1 | 패치 ⓔ — 심사 불가는 항상 2 |
| `--upstream-of`가 추이적 | 우회 간선이 있어도 저작권 게이트 "상류"로 통과 | `--direct-upstream-of` 추가 |
| 노드 0개 파이프라인이 "정상" | 빈 그래프 통과 | exit 2 |
| `merge_rules.py`가 CRLF·뒤 공백에서 IndexError | 줄끝이 다른 파일에서 죽음 | 줄 단위 탐색 |
| 원본 3파일이 저장소 린트(줄 100자) 위반 22건 | CI red | 형식만 정리(동작 불변) |

**설계 수준의 한계(3단계 설계 입력 — CONST-03)**: 배선 판정이 전역 STAGE 기준 · 워크플로 부분 문자열 일치(주석도 "연결") · 파일 단위 pytest run 35건은 이 저장소 CI 구조상 영구 "미연결" · 루트 cwd·180초 타임아웃·`shell=True` · L4 비대칭 · `.pre-commit-config.yaml` 부재. 이식 정본 §4에 정리했다.

**문서 오기 1건**: 표준북 부록 C 본문 "3단계의 44개 규칙" — 같은 파일의 표와 yaml 실측은 45건.

## 5. 계획·결정 기록과의 대조 — 같은 말, 다른 뜻

진단 묶음(계획서 100~600 · 8/27~12/31 일정)의 용어와 이 저장소의 용어는 이름이 같고 뜻이 다른 것이 많다. 이식 정본 §6에 요약 표가 있고, 여기에는 판정에 영향을 주는 차이만 적는다(판정하지 않고 기록만 인용).

**D-10 — "MVP 개발 종료 = 12/31" / "Phase 2 완료"**
- 저장소는 MVP 종료를 **2026-08-30**에 선언했다(태그 `whymath-mvp-final-2026-08-30` · `docs/strategy/eos_transition_declaration_2026-08-30.md` §0). 12/31은 **내부 검증 판정일**(Go / Conditional Go / No-Go)이다. 즉 저장소에서 EOS 전환점은 8/30이고, 12/31은 전환 후 첫 판정이다.
- 계획서 300 Gate 2는 9/19·9/24·9/25 세 번 **FAIL**로 기록됐다(10조건은 충족, 남은 미충족 1축 = 원인 미상 오답 직후 Loop 1 보정 → `EOS-26` todo). Phase 3 진입 게이트 `G-p3-entry-gate2-pass`는 pending, 3차 재판정 `EOS-141`은 todo다(main `a0e60965` 재확인). "Phase 2 완료"라는 문구는 대장·MEMORY에 없다.
- 2026-09-03 Kiki 결정: 계획서 300의 4주 Phase 2는 "참고 문서로 강등, 폐쇄루프는 계측기".

**그 밖의 대조 (D-01~D-09)**

| ID | 대조 결과 | 요지 |
|---|---|---|
| D-01 | 일치 | 12/31 = 내부 검증 판정일 · 목표 2축(EOS 아키텍처 · AI 콘텐츠 생산). 저장소는 실패 정의 F-Ⅰ~Ⅴ(G0 동결)를 추가 조건으로 둔다 — 진단 묶음의 RG1~RG8과 어느 쪽이 판정 기준인지 명시 필요 |
| D-02 | 부분 어긋남 | 콘텐츠 범위는 초등~대학 유지, 검증 구간은 앵커 6개(대학 A7·A8 제외)로 이미 좁혀짐(2026-08-30 Kiki) |
| D-03 | 일치+보강 | 1인 개발 · 주당 25시간 상한(가용 406시간) |
| D-04 | 기록 부재 | "Micro-Application Factory"·"OpenClaw" 낱말과 9/20 채택 결정이 저장소에 없다. 저장소 기록은 9/06 "대체안 A — 마이크로 프로젝트 = 적재 회차 1건(MP)" |
| D-05 | 일치 | 저작권 종합가이드 v2.0 실재 · 라이선스 매트릭스·LIC 게이트로 집행 |
| D-06 | 부분 어긋남 | AIHub 71859 = 영리 허용·국외반출 별도 합의 → 로컬 라우팅 강제. "교과서 2차저작 본문 노출 제약" 문구는 찾은 방법으로 0건. 현재 적재 코퍼스 27개 전부 자체 저작 |
| D-07 | 어긋남 3·일치 3 | 백업: 암호화·드라이브 미러·오프사이트·복구 리허설(RTO 5.8분) 일치 / 스케줄 04:00(진술 03:00)·보존 14일(진술 30개)·git bundle 없음 |
| D-08 | 일치+확장 | 로컬 우선 + Anthropic API 12/31까지 미사용(ARCH-66) · OpenRouter 경유 DeepSeek 저작 한정(ARCH-55) |
| D-09 | 모집단 어긋남 | 382·270·120개 기능 목록은 저장소 밖. 저장소 정본 모집단 = 전환계획 52항목·기능 인벤토리 v2 162행·라우터 23행 |

**구조 가정의 차이**: 진단 도구는 `eos/core`·`eos/adapters/math` 같은 물리 경로를 가정하지만, 이 저장소는 `src/backend/whymath_backend/**` 안에 CORE/ADAPTER가 동거하고 경계는 `BOUNDARY_MAP` + import-linter 계약으로 집행한다(물리 이동은 의도적으로 하지 않음). 그래서 진단 도구의 층 설정을 `scripts/constitution/diag/whymath_layers.json`(저장소 실제 경로)으로 새로 만들었다.

## 6. 비평가 지적 12건과 처분

| # | 지적 | 심각도 | 처분 |
|---|---|---|---|
| 1 | 세 헌법의 서열 모순(제2조 ① vs CLAUDE.md 최우선)에 결정 주체·게이트가 없다 | 높음 | 게이트 `G-const-precedence-declaration`(3택) 등재 · 결정 전 잠정 해석("더 엄격한 쪽, 판단 불가면 멈추고 보고")을 이식 정본 §1-2와 CLAUDE.md에 명시 |
| 2 | R0-01 집행 파일이 꾸러미에 없고, 저작 모델(AI 초안 vs 사람 전용)이 미결 | 높음 | 가드 훅·자가시험·거부 규칙 착지 · 저작 모델 = AI 초안(`docs/constitution_proposals/`) → 사람 채택 도우미(AI 세션 반영 거부) · Claude Code 밖 경로는 CONST-03(룰셋·CODEOWNERS) |
| 3 | STAGE 이름 충돌(백로그 스테이지 S0~E6)과 상향 기준·주체 부재 | 중간 | 용어 고정("이식 단계" vs "스테이지") · 상향은 래칫이 기계 집행(새 차단 있으면 기준선 이동 거부) + 채택 도우미 1칸 제한 · 파트별 부분 활성은 CONST-03 설계 |
| 4 | 위반의 CI 처리·유예 만료 미정 | 높음 | 차단 0 대신 **래칫**(항목 집합 비교·감소만 갱신)으로 CI 배선 · 만료 = 헌법 부칙 ② 경과 조치 2026-12-31 · 기준선 0화는 원본 등록부 게이트 소유 |
| 5 | 규칙 등록부 이중화(rules.yaml vs rules.ndjson)와 CLAUDE.md 동시 편집 | 높음 | 통합하지 않고 교차 참조(이식 정본 §1-3) — 통합 방향은 서열 게이트와 묶음 · CLAUDE.md 편집은 규칙 인덱스 린트(HARN-121) 통과를 조건으로 최소화 |
| 6 | Flutter 앱 축 미조사(모바일 규칙 3건 경로 불일치) | 중간 | CONST-08 acceptance에 모바일 열 재판정 포함 |
| 7 | DB 제약 실물·prod 스키마 미확인 | 중간 | CONST-05(마이그레이션) 범위 · prod 프로브 실측은 Kiki 머신 게이트 |
| 8 | 머신 로컬 규칙(백업)의 판정 장소 | 중간 | CONST-07 — 규칙에 판정 장소 축(ci / kiki-machine) · D-07 수치는 실측 후 정정 |
| 9 | 원격 claim 가독성·병렬 세션 | 중간 | 확인 — 브리핑이 타 세션 원격 claim을 읽는다 · CONST 태스크는 CLI add → start(claim)로 착수 |
| 10 | KR-06(`9^9^9` 서버 정지) 재현·추적 부재 | 높음 | 진단 기준선 BL-004로 실측 · `CONST-09`(우선순위 1) 등재 |
| 11 | pipeline.yaml 범위(콘텐츠만)와 재검증 정정 6건 미반영 | 중간 | 정정 6건 반영(28노드) · 직접 선행 검사 모드 추가 · 범위 확장은 CONST-04/07 결정 |
| 12 | 이식 완성의 정의·측정기 부재 | 높음 | 이식 정본 §5 — 완성 정의 ①~⑧을 종료 코드·게이트로 명세 · 진단 기준선 문서 고정 |
