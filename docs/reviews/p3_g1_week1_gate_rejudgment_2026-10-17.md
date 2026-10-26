# P3-G1 Week 1 Gate 재판정문

**판정 기준: main `e35692ef39e766bf12c23137cce432137271c56f`** (2026-10-16 22:49 UTC · PR #1665 머지 시점 · `git rev-parse HEAD`와 `git fetch origin main`의 FETCH_HEAD가 동일함을 확인)
**판정일**: 2026-10-17 · **태스크**: `P3-53-week1-gate-rejudgment-2026-10-17` · **게이트**: `G-p3-g1-week1`(이미 `cleared`)
**직전 판정**: 2026-10-12 · main `f34d7b76` · PASS · PR #1584. 이후 main에 first-parent 커밋 90건이 쌓였고 전부 PR 번호를 가진다.
**판정 세션**: 구현 세션과 분리된 단독 판정 세션. production code·테스트·명세·코퍼스를 바꾸지 않았다(작업 트리 변경은 이 판정문과 대장뿐). 게이트는 이미 clear돼 있어 `gates clear`/`amend`를 다시 시도하지 않는다.
**main CI(같은 커밋)**: `CI` push 실행 success · `CI` merge_group success · `conflict-guard`·`harness-audit` success. 체크 46건 중 success 38 · skipped 7(야간 전용 잡) · failure 1(`pr-auto-resync` 스케줄 워크플로의 `resync` — 코드 검증 잡이 아니며 원인은 조사하지 않았다).

## 최종 판정

> **PASS** — 세 조건(명세 동결 · 핵심 Concept Content Coverage ≥ 95% · 금지 변경 0건) 모두 충족.

조건부 PASS가 아니다. 아래 "읽기 전에 알아야 할 것"과 "정직한 공백"은 게이트 조건이 아닌 한계·잔여이며, 한계 가운데 소유자가 필요한 두 건은 태스크로 등재했다.

## 읽기 전에 알아야 할 것

1. **CLI 종료 코드는 1이다.** `python -m whymath_backend.l1.standards.phase3_coverage`는 이번에도 exit 1이다. 원인은 Content Coverage가 아니라 목표가 있는 다른 두 지표다 — Concept Completeness 0/10(< 95%)과 Graph Connectivity 5/10(< 95%). 이 PASS는 "종료 코드가 0"이 아니라 "게이트 문면이 지목한 Content Coverage가 10/10"에 기댄다. 게이트 문면은 `backlog/gates.yaml`의 `G-p3-g1-week1`: "핵심 Concept Content Coverage 95%+". 종료 코드가 이 지표를 가르지 못한다는 사실은 계측기 변별력 주입으로 직접 확인했다(아래 조건 2) → 별건 `P3-54`.
2. **10/12 이후 종료 코드의 원인이 하나 늘었다.** 10/12에는 Graph Connectivity에 목표가 없어 exit 1의 원인이 Completeness 하나였다. P3-33(PR #1608, 10/13)이 목표를 0.95로 확정해 지금은 둘이다. 게이트 조건은 아니다.
3. **금지 변경 조사 창의 날짜.** 지시문은 "10/26 이후"를 말하지만 판정일(10/17)은 그 전이다. 기간은 도달 시한이지 착수 하한이 아니라는 기본방침(2026-09-24)에 따라 앞당겨 판정했다. **10/26 이후의 변경은 이 판정이 덮지 못한다**(아직 존재하지 않는다). 아래 조건 3은 "지금까지"의 0건이다.

## 10/12 판정 대비 변화

| 항목 | 10/12 (`f34d7b76`) | 지금 (`e35692ef`) |
|---|---|---|
| 명세 sha256 | `ca0866f2…` | `5209a970…` |
| 명세 문제유형 수 | 5 | **7** (P3-05, PR #1636) |
| Graph Connectivity 목표 | 없음 | **0.95** (P3-33, PR #1608) |
| Content Coverage | 10/10 = 100% | 10/10 = 100% |
| Curriculum Coverage | 10/10 | 10/10 |
| Concept Completeness | 0/10 (hint 10 · solution 1 결손) | 0/10 (hint 측정 불가 10 · solution **10/10**, P3-31) |
| Graph Connectivity | 5/10 | 5/10 (이제 목표 미달로 판정됨) |
| 공급 가능 커버리지 | 0/10 | 0/10 |
| 6슬롯 | — | 60/60 (P3-05, 목표 없음) |
| 승인 문항 총수 | 2,984 | 3,188 (+204 = 신규 은행 `problem_bank_p3_fill_v0` 전부) |
| 범위 내 승인 PRIMARY 문항 | 917 | 1,121 |
| 범위 내 스킬 연결 승인 문항 | 624 | 712 |
| `p3_calculus1_diff_v0` (5회차 감사 504건) | 승인 504 | 승인 504 · 문항 내용 변경 0행 |

## 조건 1 — 대표 과정 명세 동결: 충족

| 확인 | 실측 |
|---|---|
| 명세 파일이 main에 있다 | `data/corpus/phase3_scope_v1/scope_spec.yaml` (동결 2026-10-02 · 게이트 `G-p301-scope-choice`) |
| 로더 스키마 검증 | `python -m whymath_backend.l1.standards.phase3_scope` → 노드 10 · Concept 10(핵심 10) · 스킬 8 · 핵심 오개념 12 · 문제유형 7 · 수량 목표 60, **판정: 통과, exit 0** |
| 동결 후 변경 이력이 전부 PR | 동결 이후 명세 변경 커밋 6건 전부 PR 번호 보유: `b8fa478a` #1431(동결) · `1246d406` #1469 · `aa31558c` #1608 · `56f4ace3` #1636 · `9019bfd5` #1639 · `5586a087` #1645. PR 번호 없는 직접 푸시 0건 |
| 분모가 바뀌었는가 | 동결본(`b8fa478a`)과 현재를 YAML 필드 단위로 대조 — 변경 경로 8건: `probe_note` 3(주석) · `distinct_basis` 설명 문구 1 · `required_problem_types` 근거 문구 1 + 항목 5→7 · Graph Connectivity 목표 `null`→0.95 및 그 사유 문구 삭제. **노드·Concept·스킬·핵심 오개념·수량 목표(숫자)는 `probe_note` 제외 시 바이트 동일.** Content Coverage의 분모(핵심 Concept 10)는 불변 |
| 명세 변경 2건의 사유가 PR에 있다 | #1636: 5종으로는 스킬 2종(`pattern-generalization`·`word-problem-modeling`)을 행사할 수 없어 승인 문항이 구조적으로 0건이었다는 실측 · 전후 `phase3_coverage --json` 출력 전체 동일 확인 · 이 목록은 지표 계산에 쓰이지 않고 생성 문항의 허용 유형 집합에만 쓰인다고 PR이 명시. #1608: 게이트 `G-p314-phase3-metric-targets`(2026-10-12 Kiki 결정)의 후속 반영 |

**해석에 의존하는 지점 하나**: 문제유형 5→7은 "범위 확장"으로도 읽힐 수 있다. 분모를 바꾸지 않고(Content·Curriculum의 모집단은 핵심 Concept 10개, 6슬롯 수량 60 불변) 새 유형의 승인 문항은 변경 시점에 0건이었으므로 커버리지를 올리지 않는 변경이다. 동결 규칙(P3-01 acceptance ④: 변경은 PR + 사유 기록)은 지켜졌다고 판정한다. Kiki가 이를 "동결 위반"으로 읽는다면 이 판정의 쟁점은 #1636 한 건이다.

## 조건 2 — 핵심 Concept Content Coverage ≥ 95%: 충족

**P3-02 CLI를 main 기준으로 실행한 결과** (`python -m whymath_backend.l1.standards.phase3_coverage`, 문항 14,742행 읽음)

| 지표 | 값 | 목표 | 판정 |
|---|---|---|---|
| **Content Coverage Rate** | **10/10 = 100.0%** | ≥ 95% | **충족** |
| Curriculum Coverage | 10/10 = 100.0% | ≥ 98% | 충족 |
| Concept Completeness | 0/10 = 0.0% | ≥ 95% | 미달 |
| Graph Connectivity Coverage | 5/10 = 50.0% | ≥ 95% | 미달 |
| 공급 가능 커버리지 | 0/10 = 0.0% | 없음 | — |
| Concept Slot Coverage(6슬롯) | 60/60 = 100.0% | 없음 | — |

**종료 코드: 1** (판정: 미달 — Completeness와 Graph Connectivity). Content Coverage 자체는 "충족"이다.

### 계측기 변별력 주입 — 이 10/10이 위장이 아님

코퍼스 값 객체에 메모리 내로 주입했다(파일 무변경 · 주입 전후 `git status` 대장 외 변경 0). 매 주입마다 `mutated != original`과 "바뀐 대상 > 0건"을 단언했다. 주입 스크립트는 스크래치패드에 있고 저장소에는 넣지 않았다.

| 주입 | 바뀐 대상 | Content 결과 | 판정 |
|---|---|---|---|
| M1 `[12미적Ⅰ-02-01]` 승인 문항 전부 `pending` 강등 | 200건 | **9/10** · 미충족 02-01 | RED(하락) |
| M2 `[12미적Ⅰ-02-04]` 개념 콘텐츠 행 제거 | 1건 | **9/10** · 미충족 02-04 | RED |
| M3 `[12미적Ⅰ-02-06]` 문제유형(스킬 매개) 제거, 승인 상태는 유지 | 72건 | **9/10** · 미충족 02-06 | RED |
| M4 M1+M2 동시 | 201건 | **8/10** | RED |
| C1 대조군: 개념당 `승인 ∧ 스킬 연결` 문항 1건만 남김 | 1,111건 제거(1,121→10) | 10/10 유지 | 과잉 반응 아님 |
| C2 대조군: 점수와 무관한 `question_text` 전부 교체 | 1,121건 | 10/10 유지 | 과잉 반응 아님 |

주입 6종 전건이 기대값과 일치했다(불일치 0). **그리고 6종 전부, 무주입 기준선도 종료 코드는 1이다** — Content가 8/10으로 내려간 경우와 10/10인 경우를 종료 코드로는 구별할 수 없다. 이것이 위 "읽기 전에 알아야 할 것" 1번의 실측 근거이며 `P3-54`의 입력이다.

### 승인 상태의 견고성 — 새로 생긴 승인에 기대지 않는다

10/12 이후 승인 문항을 (A) 10/12과 문항 본문(질문·정답·해설·보기·검증·개념 태그)이 바이트 동일 · (B) 승인 이후 본문이 바뀜 · (C) 신규로 나눠 Content를 다시 계산했다.

| 인정하는 승인 | Content |
|---|---|
| 전체(현재) | 10/10 |
| A+B (신규 `p3_fill` 204건 승인을 전부 불인정) | **10/10** |
| A만 | 9/10 |
| A+C (B의 24건을 불인정) | 9/10 |

- **신규 승인 204건은 Content에 필요하지 않다.** 10/12 이전부터 있던 승인으로 10/10이 성립한다.
- **B는 `[12미적Ⅰ-02-02]`의 24건뿐이다.** 전부 `problem_bank_conceptual_v0`이고 바뀐 것은 `verify.solution_steps` 추가(+`tags`)다. 질문·정답·해설은 바이트 동일하고 `review_status`는 `approved` 그대로다(P3-31, PR #1591: 감사가 본 내용은 지문 핀으로 동결, 새 단계는 SymPy `verify_solution` 전건 증명으로 덮었다고 PR이 주장). 이 판정은 그 주장을 재현하지 않았다. 대신 승인 각인 점검 `problem_corpus_review_status_backfill --all --check`가 **exit 0**이다(conceptual·p3_calculus1_diff·p3_fill 전 은행 감사 파일과 드리프트 없음).
- **단일 실패점(10/12에도 같았으나 판정문에 드러나지 않았다)**: `[12미적Ⅰ-02-02]`의 Content 연결은 위 24건(전부 `ptype.verify-claim` · 한 틀)에만 의존한다. 같은 개념의 승인 PRIMARY 84건 중 나머지 60건(`p3_fill`: `evaluate-expression` 36 · `solve-for-unknown` 24)은 02-02의 스킬(`deductive-reasoning`·`graph-reading`)에 매핑되지 않아 연결되지 않는다. 개념 1개가 10%p이므로 이 24건의 승인이 흔들리면 Content는 9/10 = 90%로 내려가 이 게이트의 기준을 못 채운다 → 별건 `P3-55`.
- 가장 얇은 연결: `[12미적Ⅰ-02-06]` 스킬 연결 6건(10/12과 동일, `p3_calculus1_diff_v0`의 감사 은행 문항).

### 같은 날 실행한 테스트 (판정 근거 · 종료 코드)

`pytest -c src/backend/pyproject.toml --rootdir=src/backend` 6파일: `test_phase3_scope_spec` · `test_phase3_coverage` · `test_canonical_entity_model_freeze` · `test_p3_calculus1_diff_bank_coverage_link` · `test_p3_calculus1_diff_batch` · `test_p3_conceptual_02_02_solution_link` → **289 passed, exit 0**.
(처음에 저장소 루트에서 경로만 주고 돌렸더니 OPS-61 가드가 `asyncio_mode` 미적용으로 exit 4를 내며 멈췄다 — 설정 명시 방식으로 재실행했다. 가드가 정상 작동한 사례다.)

## 조건 3 — 금지 변경 0건: 충족

### 조사 범위

- **이번에 조사한 구간**: `f34d7b76`(10/12 판정 기준)..`e35692ef` — first-parent 커밋 90건. 전부 PR 번호를 가진다(PR 번호 없는 직접 푸시 0건).
- **조사하지 않은 구간**: 09-29..`f34d7b76`는 10/12 판정이 조사해 Kiki가 해석 2곳과 함께 clear한 구간이라 **승계**했다. 이번에 재조사하지 않았다.
- **방법의 한계**: 경로·클래스 정의·연산 종류·키워드로 분류했다. 다른 이름·위치로 숨은 변경은 이 방법의 사각이다. UI 항목은 기계 집행(`HARN-103`)이 없어 수작업 분류다.

### 5종별 결과

| 금지 변경 | 후보 | 판정 | 근거 |
|---|---|---|---|
| EOS Core 신규 Entity | 모델 4파일 수정(`activity`·`concept`·`concept_version`·`problem_version`) | **해당 없음** | ORM 테이블 정의 수 84 → 84, 모델 diff의 신규 `class`·`__tablename__` 0줄. 핵심 엔티티 동결 테스트(`test_canonical_entity_model_freeze`) 통과 |
| 대규모 Schema 변경 | alembic 신규 리비전 2건 | **해당 없음**(아래 주의) | EOS-47(PR #1569): `add_column` 2 + FK 1 추가. P3-26(PR #1603): `add_column` 2 + **FK 1 해제** + 트리거 함수 2·트리거 2 신설. `create_table` 0 · `drop_table` 0 · `drop_column` 0 |
| 새 Agent | `.claude/agents` 신규 0 | **해당 없음** | `pedagogy-designer.md` +2줄(PED-45, PR #1618: 교수전략 카탈로그 문서번호 정합), `AGENTS.md` 서열 문구 정정(코딩 헌법 > CLAUDE.md, PR #1597) — 둘 다 기존 파일 수정이고 에이전트 추가가 아님 |
| 새 Subject Adapter | `adapter` 경로 신규 구현 0 | **해당 없음** | `l4/subject_adapter_math.py`(기존 수학 어댑터)에 `author_resolver` 생성자 인자 1개 추가(S4-65, PR #1604) · 신규 파일은 테스트 1개와 백로그 태스크 1개뿐 |
| 대규모 UI 구조 변경 | `src/web` 9파일(신규 3 · 수정 6) · `src/mobile` 0 | **해당 없음** | 전부 `app/admin/_components`·`_lib`(CMS 개념 스튜디오 패널: 삭제 박스·엣지 패널·제안 패널 추가 + 기존 패널 수정). 셸·레이아웃·내비·라우터 파일 변경 0 — P3-12 지시문이 정의한 "기존 관리자 화면 틀 안에서 추가"에 해당 |

**주의 1건 — Release Blocker 예외 근거 여부와 무관하게 Kiki가 알아야 할 것**: P3-26의 마이그레이션은 `concept_version.concept_id → concept.code` **외래키를 해제**한다(신규 개념 제안 판이 아직 개념 행이 없는 상태를 담기 위함). 대신 트리거 2개로 "PUBLISHED 판은 살아 있는 개념 행이 있어야 쓸 수 있다"·"발행본이 있는 개념 행은 지울 수 없다"를 건다. 테이블·컬럼 삭제가 없고 작업 단위가 작아 "대규모 Schema 변경"으로 분류하지 않았지만, 참조 무결성을 DB 제약에서 트리거로 옮긴 성격이라 컬럼 추가보다 무겁다. 이 분류는 해석이다.

금지 변경으로 분류된 것이 0건이므로 Release Blocker 예외 근거 확인은 필요하지 않다.

## 정직한 공백

- **전체 백엔드 스위트와 CI 미러는 돌리지 않았다.** 판정 전용이고 소스·테스트를 바꾸지 않았다. 직접 돌린 것은 CLI 3종(명세 로더·Coverage·승인 각인 점검), 테스트 6파일 289건, 주입 스크립트 1개다. 전체 통과는 main CI(push·merge_group success)에 의존한다.
- 이 PR(판정문 + 대장)에 닿는 CI 잡 `harness-integrity`·`policy-guard`의 스텝을 로컬에서 재현했다: `backlog validate`·`audit-deps`·`rules lint`·`rules render --check`·`jit check`·헌법 래칫·`check_amendment`·`cp949_guard`·충돌 마커·원본 바이너리 가드 전부 exit 0, `tests/harness` **2,307 passed · 3 skipped, exit 0**. **`check_signed_changes`는 이 환경에 `ssh-keygen`이 없어 측정 불가(exit 2)** — 통과가 아니며 CI가 판정한다(이 PR은 `constitution/`을 건드리지 않는다). `infra-contracts` 등 나머지 잡은 이 PR의 변경(문서·대장)이 닿는지 근거를 갖고 판정하지 않았다.
- `pr-auto-resync` 스케줄 워크플로의 `resync` failure는 원인을 조사하지 않았다.
- 승인 근거의 *생성 과정*(5회차 감사·P3-31의 SymPy 전건 증명)은 재현하지 않았고 PR 기록과 결속 테스트 통과에 기댔다.
- B 24건의 "본문 동일" 판정에서 `verify`는 본문에 포함해 비교했다(그래서 B로 분류됐다). 질문·정답·해설만 비교하면 B는 0건이다. 보수적 쪽으로 분류했다.
- 이 PASS는 "연결됐다"의 판정이다. 연결은 100%이지만 학생에게 공급 가능한 개념 콘텐츠는 0/10(10개 전부 `ai_estimated`, 검수 승격 게이트 `G-kg02-review-promotion-llm-session`)이다.
- 10/26 이후 금지 변경은 존재하지 않아 판정할 수 없다. 이 게이트를 11/1 상한 시점의 실제 금지 창에 대한 증거로 재사용하려면 조건 3을 그때 다시 돌려야 한다.

## 후속 등재 (구현하지 않고 등재만)

| 태스크 | 내용 | 이유 |
|---|---|---|
| `P3-54-coverage-gate-scoped-exit-code` | Coverage CLI 종료 코드를 게이트 조건 지표 단위로 분리 | 무주입·주입 4종·대조군 2종 전부 exit 1 — 종료 코드가 Content Coverage를 가르지 못한다. P3-02 acceptance ②("exit code로 판정")와 실제 판정 방식이 어긋난 채다 |
| `P3-55-calc1-02-02-content-single-template-dependency` | `[12미적Ⅰ-02-02]` Content의 단일 템플릿(24건) 의존 해소 또는 위험 명시 | 개념 1개가 10%p. 60건이 스킬에 안 닿는 원인이 설계인지 결함인지 미판정. P3-31이 "별건 후보"라 적었으나 소유 태스크가 없었다 |
