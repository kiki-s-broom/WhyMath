# EOS-190 — 문항 발행 경로: `problem_version`의 유일한 writer

> **판정 기준**: 작업 브랜치 `claude/charming-thompson-n7uldh` (main `dc214a2f` 위). 근거 코드는 전부 이 트리에서 실측. 2026-10-13.
> **설계 정본**: `44_eos_version_management.md` §6.4(Entity의 현재 버전 포인터)·§7(Lifecycle)·§9(Publish Gate) · 짝 모듈 `l3/publish_gate.py`(개념 판, EOS-50) · 선행 `arch31_problem_version.md`(테이블)·`eos47_attempt_version_pinning.md`(시도 고정).

## 1. 한 줄 결론

`problem_version` 행과 `problem.problem_version_id` 포인터를 쓰는 **유일한 운영 자리**(`l3/problem_publish_gate.py`)를 만들었고, 이 writer로 발행한 문항에서 실제 `POST /v1/me/attempts`가 `outcome=pinned`를 내고 시도 행에 판 id가 박힘을 실 PostgreSQL로 확인했다. **그러나 이 writer를 부르는 운영 라우트·CLI는 아직 없어(§6) 운영 DB의 포인터는 지금도 전부 NULL이다.** 이 변경은 "고정이 일할 수 있는 상태"를 만들었지 "고정이 일하고 있는 상태"를 만든 것이 아니다.

## 2. 모듈 표면

| 함수 | 층 | 하는 일 |
|---|---|---|
| `snapshot_payload(problem)` | 순수 | 라이브 `problem` 행 → 판 payload. 내용 정의 필드만(난이도 5축·검수·임베딩 제외). 평가원·EBS·교과서 출처에 본문이 남은 행이면 payload의 저작권 validator가 거부 |
| `compute_content_hash(payload)` | 순수 | 키 정렬 JSON의 sha256 — JSONB 왕복의 키 순서와 무관 |
| `run_gate(version, gate, live_content_hash=…)` | 순수 | QA·PUBLISH 게이트의 검사 전부(§4). 첫 실패에서 멈추지 않고 모아 보고 |
| `plan_transition(…)` | 순수 | 전이표(`schema/version_lifecycle.py`)를 **조회만** 한다 — 도착 상태를 이 모듈이 고르지 않는다 |
| `create_draft(session, problem_id=…)` | DB | `version_no`=최신+1, `previous_version_id`=최신 판. `payload` 생략 시 문항 행 잠금 뒤의 라이브 내용을 스냅숏 |
| `apply_transition(session, version_id, action, actor=…)` | DB | 전이 1건. PUBLISH면 같은 문항의 옛 발행본을 supersede하고 포인터를 이 판으로 옮김. DEPRECATE면 포인터를 비움 |
| `list_versions` · `get_version` | DB(읽기) | API 계층이 ORM을 import하지 못하므로 읽기도 이 모듈을 거친다 |

실행 함수는 `flush`까지만 하고 `commit`하지 않는다(호출자가 트랜잭션 경계). 게이트가 실패하면 **아무 것도 쓰기 전에** 예외가 난다. 잠금 순서는 항상 **문항 → 판**이다.

## 3. 개념 판 게이트와 다른 점 — 왜 `live_content_current`가 있는가

개념 판은 `concept_version`이 곧 서빙 원본이다. 문항은 다르다 — **판과 별개로 라이브 `problem` 행이 서빙된다.** 승인된 초안이 라이브 문항과 어긋난 채(그 사이 CMS가 정답을 고침) 발행되면, EOS-47이 시도에 박는 "그 학생이 푼 판"의 payload가 학생이 실제로 본 문항과 달라진다 — 고정의 의미가 사라진다.

그래서 PUBLISH 전이는 **문항 행 잠금 뒤의 라이브 스냅숏 해시 == 판 payload 해시**를 요구한다. 세 갈래를 모두 둔다:

| 입력 | 판정 | 이유 |
|---|---|---|
| 해시 일치 | 통과 | 정상 |
| 해시 불일치 | 실패 | 승인 이후 라이브가 바뀜 — 새 초안으로 다시 승인 |
| 해시 없음(`None`) | **실패** | 모른다 ≠ 통과. 라이브 행이 스냅숏 계약을 어겨 계산하지 못한 경우를 통과로 접지 않는다 |

잠금 뒤에 **다시 읽는다**(`populate_existing`) — 화면 표시용으로 문항을 먼저 읽어 둔 세션에서 발행해도 낡은 내용으로 대조하지 않는다.

## 4. 불변식과 집행 지점 (정정: 정본화 ≠ 집행)

| 불변식 | 집행 지점 | 검증 |
|---|---|---|
| `problem_version` ORM import·`problem.problem_version_id` 쓰기·`problem_version` 쓰기 SQL은 게이트 모듈뿐 | AST 전수(R1·R2·R3, 스캔 0건 실패, 허용 목록의 공허성 검사) | `tests/backend/l3/test_problem_publish_gate_enforcement.py` (28건) |
| 같은 이름의 `problem_attempt.problem_version_id`(EOS-47)와 구분 | R2 예외 = **`ProblemAttempt` 클래스에서 import된 이름**만(별칭 `ProblemAttemptORM` 추적, 원이름이 다른 별칭은 예외 불가) | 같은 파일 — 위장 별칭 주입 시 RED |
| 판 게이트는 노출 축(`ReviewStatus`·`review_status`·`is_published`·`publish_at`)을 읽지도 쓰지도 않는다 | AST (B1) | 같은 파일 |
| 문항 노출 경로는 판 축을 모른다 | AST (B2) | 같은 파일 |
| 잠금 순서 문항 → 판 | AST (함수별 호출 순서) | 같은 파일 |
| 검사 전부(`schema_valid`·`schema_version_format`·`entity_type`·`content_hash`·`governance_complete`·`qa_record_bound`·`live_content_current`) | 검사마다 **그 하나만 깨뜨린 입력**으로 RED + 고친 대조군 GREEN | `tests/backend/l3/test_problem_publish_gate.py` (23건) |
| 발행 → 실제 HTTP 경로에서 `outcome=pinned` | 실 PG 관통(아래 §5) | `tests/backend/db/test_problem_version_publish_integration.py` (7건) |

**통합 테스트의 위치가 `tests/backend/db/`인 이유**: CI 통합 스텝은 `pytest -m integration --ignore=../../tests/backend/l3`이다. `tests/backend/l3`에 두면 CI가 수집하지 않는다. 같은 명령의 `--collect-only` 실측(2026-10-13)에서 **신규 통합 테스트 7건 수집 · `l3` 하위 0건**이었다. 이 실측은 기존 EOS-50 통합 테스트(`test_publish_gate_integration.py`)도 CI에서 돌지 않음을 드러냈다 — `OPS-137`이 소유한다.

## 5. 실 PG 관통 시나리오

| | 시나리오 | 확인하는 것 |
|---|---|---|
| A | 발행 전 시도 → NULL / writer로 발행 / 발행 후 시도 → 판 id + 로그 `outcome=pinned` + 채점 환경 스냅숏 / 발행하지 않은 형제 문항 → NULL / 발행 이전 시도는 소급되지 않음 | **고정이 일괄 적용이 아니다**(대조군 3개) |
| B | 문항 정정 → 재발행 | 옛 발행본 DEPRECATED · 포인터 이동 · 버전 체인(`version_no=2`, `previous_version_id=v1`) · 옛 시도는 v1을 계속 가리키고 v1 payload는 정정 전 모습 · 정정 뒤 새 시도는 v2 |
| C | 승인 뒤 라이브 문항이 바뀜 | 발행 거부 · 상태·포인터·QA 기록 불변 · 새 초안은 같은 경로로 발행됨(과잉 거부 아님) |
| C2 | 문항을 먼저 읽어 둔 세션에서 발행 | 낡은 identity map이 아니라 커밋된 수정을 본다 |
| D | 발행본 내리기 / 낡은 `expected_status` | 포인터 비워짐 · 새 시도 NULL / 거부되고 아무것도 쓰이지 않음 |
| E | **코퍼스 재적재** | 아래 §5.1 |

### 5.1 이 작업이 발견한 두 번째 writer — 코퍼스 적재기

`l1/problem_bank/populate.py`의 `ON CONFLICT DO UPDATE` 갱신 집합은 `mapper.column_attrs`에서 **동적으로** 뽑는다. 코퍼스 레코드는 `problem_version_id`를 늘 `None`으로 들고 있으므로, 재적재는 **발행된 문항의 포인터를 NULL로 되돌린다.** writer가 0건이던 동안은 덮을 값이 없어 무해했고, 첫 writer가 생기는 순간 현실이 되는 결함이다 — 시도 버전 고정이 조용히 끊긴다.

- **재현**: 수정 전 E 시나리오가 `assert None == UUID(…)`로 RED(실 PG).
- **수정**: `PUBLISH_POINTER_COLUMN` 상수를 갱신 집합에서 뺀다(`populate.py` +18/-2).
- **AST 스캔으로는 안 보인다** — 컬럼 이름이 코드에 나타나지 않기 때문이다. 그래서 AST 동결 파일의 C 절이 "상수가 포인터이고 갱신 집합 계산이 그 상수를 쓴다"를 고정하고, 실제 행동은 E 시나리오가 본다.
- **같은 위험을 점검한 나머지 경로**: `api/problems.py` PATCH는 현재 행에서 병합하므로 포인터를 보존한다. `ops/loop_kpi_sample_load.py`의 `session.merge(Problem.from_schema(…))`는 포인터를 `None`으로 덮을 수 있으나 **발행되지 않는 합성 표본**이라 실위험이 없다(미수정, 기록만).

## 6. 알려진 한계 (정직 기술)

1. **(2026-10-13 정정: `EOS-194`가 호출 표면을 만들었다 — `eos194_problem_publish_caller_surface.md`. 아래는 EOS-190 착지 시점의 서술이다. 운영 DB 측정은 같은 문서 §5.2 참고.)** **운영 호출자가 없다.** 이 모듈을 부르는 라우트·CLI가 0건이라 운영 DB의 `problem.problem_version_id`는 지금도 전부 NULL이다. EOS-47의 `outcome=pinned` 비율은 이 모듈이 *호출되기 전까지* 운영에서 0이다. → **`EOS-194`**
2. **발행 이후의 제자리 편집은 새 판이 되지 않는다.** `live_content_current`는 *발행 순간*만 막는다. 발행 뒤 CMS가 `problem` 행을 고치면 포인터가 가리키는 판의 payload와 라이브 행이 갈라진다. → **`EOS-195`** (드리프트 건수/비율 리포트 + 처분 판정)
3. **Rollback·Restore가 없다.** 전이표의 복합 전용 간선은 호출 경로가 없어 구현하지 않았다(선언만 된 코드를 두지 않기 위함). → **`EOS-196`**
4. **접수 시점 ≠ 출제 시점**(EOS-47 §5-2)은 그대로다. → `EOS-191`
5. **`ops/loop_kpi_sample_load.py` 경로**는 §5.1 마지막 항목대로 미수정.

## 7. 검증 결과

- 테스트 58건 통과(단위 23 · AST 동결 28 · 실 PG 7). 기존 관련 테스트 68건도 수정 전후 통과.
- **뮤테이션 19종 전건 검출, 생존 0** — 게이트 모듈 17종(`live_content_current` 3갈래 무력화·공허한 자기 비교로 대체·포인터 미이동/미해제·supersede 누락·잠금 순서 역전·`populate_existing` 제거·검사 5종 무력화·낙관적 동시성 무력화·버전 번호/체인/QA 기록 누적 훼손·범위 밖 게이트 거부 제거)과 적재기 2종(제외 해제·상수 오타). 하네스는 치환 대상 개수·`mutated != original`을 단언하고 백업 바이트 대조로 원복했다.
- 뮤테이션 전에 발견해 테스트를 보강한 빈틈 2건: ① `_lock_problem`의 `populate_existing`을 빼도 통과하던 것(테스트마다 새 세션이라 낡은 identity map이 구조적으로 안 보임 → C2) ② 버전 체인(`previous_version_id`·`version_no`)을 검증하는 단언이 0개였던 것(→ B). 둘 다 보강 후 해당 뮤테이션이 검출됐다.

## 8. 후속

| 태스크 | 내용 |
|---|---|
| `EOS-194` (P1) | 문항 발행 호출 표면 — 이게 착지해야 운영 값이 NULL이 아니게 된다 |
| `EOS-195` (P1) | 발행 이후 제자리 편집 드리프트 — 리포트 + 처분 판정 |
| `EOS-196` (P2, EOS-194 선행) | 문항 판 Rollback·Restore |
| `OPS-137` (P1) | `tests/backend/l3` 통합 테스트 9개가 CI에서 수집되지 않음(EOS-50 통합 포함) |
