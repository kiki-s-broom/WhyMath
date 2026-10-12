# EOS-47 — `problem_attempt` 버전 고정 (`problem_version_id` + `evaluation_context`)

> **판정 기준**: 작업 브랜치 `claude/dreamy-johnson-tj12ud` (main `594ce16b` 위). 근거 코드는 전부 이 트리에서 실측. 2026-10-09.
> **설계 정본**: `44_eos_version_management.md` §10.2(Runtime VersionContext)·§11(AI 재현성) · 선행 `arch31_problem_version.md`(ARCH-31, `problem_version` 테이블).
> **요구 출처**: `28_mathlive_input.md` §34~35(채점 이의 재현 — `notation_contract`·정규화 파서 버전) · `32_learning_history.md` §220.

## 1. 한 줄 결론

시도(attempt)가 **접수되는 순간** 문항의 현재 판 포인터와 채점 환경을 시도 행에 복사해 박는다. 문항이 나중에 수정돼도 시도는 푼 당시의 판을 가리킨다. 다만 **지금 실제로 값이 채워지는 곳은 일부뿐**이다 — 아래 §3·§5가 무엇이 비어 있고 왜 비어 있는지를 숨기지 않는다.

## 2. 스키마 (리비전 `d6a2f8c4b1e7`)

| 컬럼 | 형 | 의미 | 기본값·백필 |
|---|---|---|---|
| `problem_attempt.problem_version_id` | UUID FK → `problem_version.version_id`, nullable | 이 시도가 푼 문항의 **판** | 없음 · 백필 없음 (NULL = 고정 안 됨) |
| `problem_attempt.evaluation_context` | JSONB, nullable | 채점 시점의 교육 환경 스냅숏 | 없음 · 백필 없음 (NULL = 기록 안 됨) |

기존 시도에 판을 날조해 채우지 않는다(DP-03 `event_uuid`·ARCH-31 규약). 인덱스는 만들지 않았다 — 이 컬럼으로 조회하는 소비처가 아직 없다.

## 3. `evaluation_context` 5키 — 출처 실측

정본은 `schema/evaluation_context.py`의 `EVALUATION_CONTEXT_SOURCES`다. **출처가 있는 키만 채우고, 없는 키는 `None`(= 모름)으로 둔다.** 출처 없는 키에 임의 상수를 박으면 "버전을 기록했다"는 외양만 남고 실제 변경은 추적하지 못한다.

| 키 | 지금 채워지나 | 출처(2026-10-09 실측) |
|---|---|---|
| `curriculum_version` | ✅ | `problem.curriculum_version`(NOT NULL enum 값, 예 `2022_REVISION`). **라벨**이다 — 44 §10.2의 `curriculum_version_id`(교육과정 Release 버전 테이블 행)와 다르고, 그 테이블과 문항을 잇는 매핑은 아직 없다 |
| `concept_graph_version` | ❌ None | 그래프 단위 Release/스냅숏이 없다(44 §13 Phase 2). `concept_version`은 개념 *개별* 판일 뿐 |
| `grading_policy_version` | ❌ None | 채점 권위(`l3.verify_final_answer`)는 있으나 그 규칙에 번호가 없다. `AssessmentPolicy` 버전은 44 §13 2단계 확장 |
| `notation_contract_version` | ❌ None | `data/notation_contract.json`의 `"version"`은 테스트만 읽고 백엔드 런타임 로더가 없다 |
| `normalizer_version` | ❌ None | 정규화 파서 버전 상수가 없다 |

28 §35가 요구한 "`notation_contract`·파서 버전 포함"은 **계약 키로는 반영**했고 값은 출처가 생길 때 채운다.

## 4. 불변식과 집행 지점 (정본화 ≠ 집행)

| 불변식 | 집행 지점 | 검증 |
|---|---|---|
| 세 적재 경로(`me.submit_attempt` · `coach._complete_problem` · `coach._record_first_wrong_submission`)가 모두 헬퍼를 부르고, 두 컬럼 값이 **헬퍼 결과에서 온다** | AST 전수 검사(상수·`None` 리터럴·`from_schema` 우회 거부, 스캔 0건 실패) | `tests/backend/api/test_attempt_version_pin_wiring.py` |
| 출처 없는 키는 채우지 않는다 | `EVALUATION_CONTEXT_SOURCES` ↔ 헬퍼 채움 키 집합 동치 | `tests/backend/l2/test_attempt_version_pin.py` · `tests/backend/schema/test_evaluation_context.py` |
| 문항이 수정돼도 시도는 원 판을 가리킨다 (acceptance ③) | 접수 시점 포인터 복사 | `tests/backend/db/test_attempt_version_pinning_integration.py` (실 PG · 대조군 2개: 수정 뒤 새 시도는 새 판 / 포인터 조인은 새 판) |
| 마이그레이션이 비파괴·대칭 | 왕복 + 기존 행 보존 + FK | 같은 통합 테스트 · 전 구간 `downgrade base → upgrade head` |

실패 주입으로 확인한 결함 7종(키워드 삭제·`None` 리터럴·호출 삭제·상수 날조·포인터 무시·예외 삼킴·컨텍스트 누락) + 통합 1종(포인터 무시)을 전건 RED로 검출했다.

헬퍼는 읽기 실패를 **삼키지 않는다**. 실패한 트랜잭션 뒤의 INSERT는 어차피 불가하므로 삼켜도 가용성이 늘지 않고, 진짜 원인을 가린다.

## 5. 알려진 한계 (정직 기술)

1. **지금 `problem_version_id`는 전부 NULL이다.** `problem_version`에 행을 쓰는 운영 writer(문항 발행 경로)가 없다(ARCH-31 §5). 헬퍼는 판 없는 문항에 판을 날조하지 않으므로 정확한 상태이고, 발행 경로가 포인터를 채우는 순간부터 수정 없이 값이 기록된다. 로그 `outcome=pinned | no_version`이 "작동한 비율"을 센다.
2. **접수 시점 ≠ 출제 시점.** 학생이 문항을 받은 뒤 푸는 동안 새 판이 발행되면, 학생이 본 판이 아니라 새 판이 박힌다. 정확한 고정은 출제 시점에 판을 확정해야 한다.
3. `evaluation_context`는 5키 중 1개만 채워진다(§3).
4. `curriculum_version`은 라벨이다(버전 테이블 id 아님).

## 6. 후속 (이 변경이 소유하지 않는 것)

- **`EOS-190-problem-version-publish-writer`** (P1) — 문항 발행 경로. `problem_version`에 행을 쓰는 유일한 자리를 만들어 §5-1(전부 NULL)을 해소한다. 이 변경의 효과가 실제로 나타나는 선행 조건이다.
- **`EOS-191-serve-time-version-stamping`** (P2, EOS-190 선행) — 출제 시점 판 확정. §5-2(접수 ≠ 출제) 해소.
- **`EOS-192-evaluation-context-source-wiring`** (P2) — §3에서 `None`인 4키를 정본 소유자가 값을 만든 뒤 키 단위로 연결.
- **`EOS-193-attempt-version-pin-reach-report`** (P2, EOS-190 선행) — 고정이 실제로 일한 비율 리포트(0%가 정상처럼 보이지 않게).
