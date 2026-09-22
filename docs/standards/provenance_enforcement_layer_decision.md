# provenance 강제 집행 지점 — 방침 재판정 (계약 정본)

> **판정 기준: main `b81a9909` (2026-09-21)** · 태스크 `LIC-03-provenance-enforcement-layer-decision`
> 근거는 전부 이 커밋의 trunk 실측이다(미머지 브랜치 근거 0건 — "미머지 존재를 충족으로 단정 금지").

---

## §1. 무엇이 충돌했는가

| 축 | 문언 | 출처 |
|---|---|---|
| DoD | "DDL+NOT NULL, **provenance 없는 AI 생성물 INSERT 거부**" | `docs/strategy/eos_transition_declaration_2026-08-30.md` 부록 A-A4 |
| 현행 방침 | "ORM에는 컬럼만 두고 **가짜 DB CHECK를 만들지 않는다**" | `src/backend/whymath_backend/db/models/provenance.py` 모듈 docstring |

EOS-53 크로스워크 갭 #10이 이 충돌을 실측해 등재했다(`docs/reviews/eos_plan52_crosswalk_2026-09.md` §2.1 #10).
본 문서가 그 재판정이며, `LIC-03` acceptance ①의 산출물이다.

---

## §2. 실측 — 착수 시점(main `b81a9909`)의 상태

판정을 바꾼 사실 5건이다. 전부 trunk 기준이며 파일:라인을 근거로 단다.

**① 링크는 역방향 nullable FK다.** 스키마 정본(`schemas/v1.0/schema_v1.0.md:918-920`)과 ORM
(`db/models/provenance.py:65-67`)에서 `content_provenance.problem_id → problem`이고 NOT NULL이 아니다.
`problem` 테이블에는 `provenance_id` 컬럼이 **없다**.

**② `problem`이 아는 출처 표지는 `source_type` 하나뿐이다.** NOT NULL enum 8값
(`db/models/problem.py:95-98`, 값 정의 `schema/enums.py:30-61`). 생성원(모델·프롬프트·생성종류)
컬럼은 없다. 따라서 계획서 문언 `origin='ai_*'`에 대응하는 유일한 실재 표지는
**`source_type = '자체생성'`**(본문을 우리가 보유하는 생성물)이다 — 본 계약은 이 대응을 조작적
정의로 못박는다.

**③ 원장을 쓰는 프로덕션 코드가 0건이었다.** `ContentProvenance`·`GenerationLog` ORM에 대한
`session.add`/`pg_insert`/`from_schema` 호출이 `src/` 전체에 없었다. 유일한 비-재수출 import는
`ops/weekly_metrics_report.py:66`이고 용도는 읽기 SELECT(`:370-372`)다. 즉 **테이블은 있고 쓰는
사람이 없었다** — "provenance 없는 AI 생성물"이 예외가 아니라 전부였다.

**④ 저작 계층에는 provenance가 이미 필수였다 — 적재 직전에 버려졌다.**
`l1/problem_bank/populate.py:125-127`의 `_AUTHORING_KEYS`가 `license`·`generation_type`·
`original_source`를 `Problem.model_validate` 전에 `pop`하고(`:296-301`), 조립된
`ProblemProvenanceMeta`는 DB로 나가는 `values` 필터(`:606-607`)에서 탈락했다. 코퍼스 JSONL
14,034건 실측 분포는 `generation_type=FULLY_GENERATED` · `license=WHYMATH_GENERATED` ·
`original_source` 없음으로 **전건 균일**이다 — 즉 재료는 완비돼 있었고 배선만 없었다.

**⑤ `problem` 행을 만드는 경로는 2개다.** `l1/problem_bank/populate.py:608`(Core `pg_insert` —
ORM 클래스 인스턴스화를 경유하지 **않는다**)과 `api/problems.py:176-177`(ORM `session.add`) ·
`:369`(`session.merge`). 둘은 서로를 모르며 공통 상위 진입점이 없다.

---

## §3. DB 계층 3안 — 각각의 판정

DoD의 "DDL+NOT NULL"을 문자 그대로 옮기는 방법은 셋이고, 셋 다 배제한다.

**3-A. 단일 행 `CHECK` — 구조적으로 불가(선택지가 아니다).**
PostgreSQL의 `CHECK`는 그 행의 컬럼만 볼 수 있어 **타 테이블의 행 존재를 판정할 수 없다**.
§2-①대로 provenance는 별도 테이블의 행이므로 `problem`의 CHECK로는 표현 자체가 성립하지
않는다. 더구나 FK 방향상 provenance 행은 problem이 **생긴 뒤에야** 삽입 가능하므로
"INSERT 시점 거부"는 시간적으로도 모순이다. — 현행 방침의 "가짜 DB CHECK를 만들지 않는다"는
이 축에서 **옳았다**. 방침을 뒤집을 이유가 없다.

**3-B. 역방향 `problem.provenance_id NOT NULL FK` 신설 — 표현 가능, 배제.**
표현은 된다(provenance 행을 먼저 만들고 problem이 그것을 가리키게 하면 순환도 풀린다).
배제 근거 3건: ⓐ 스키마 정본 §10.1의 링크 방향을 **뒤집는 개정**이라 A4 원장 설계 자체의
재결정이고 LIC-03의 범위(집행 지점 결정)를 넘는다 ⓑ NOT NULL은 **기존 전 행 백필**을
요구하는데, §2-③대로 원장이 비어 있어 백필할 값이 없다(없는 출처를 지어내는 것은 날조 금지에
걸린다) ⓒ `자체생성`이 아닌 출처(평가원·EBS·교과서 — 메타 전용, 본문 미보유)까지 원장을
강제하게 되어 저작권 레일과 충돌한다. 부분 강제로 좁히려면 결국 3-C가 필요하다.

**3-C. `DEFERRABLE INITIALLY DEFERRED` 제약 트리거 — 표현 가능, 배제.**
COMMIT 시점 판정이라 §2-①의 선후 문제를 푼다. 배제 근거 3건: ⓐ 트리거 본문은 원시 SQL이라
"모든 DB 접근은 ORM/쿼리 빌더 — 원시 SQL 최소화"(CLAUDE.md) 와 정면 충돌하고, ORM 모델을
읽어서는 그 제약의 존재를 알 수 없다(불가시 집행) ⓑ hermetic 스위트는 실 PG 없이 도는데
트리거는 **실 PG에서만** 검증되므로 `backend` 잡에서 변별력이 0이 된다 — 가드를 만들고 그것이
이번 실행에서 도달하지 못하는 상태를 새로 만드는 셈이다 ⓒ 트리거가 막는 것은 여전히
"행이 없다"뿐이고, `generation_type`이 빈 문자열인 **위장 원장**은 통과시킨다(§2-④가 실제로
만들던 상태).

---

## §4. 판정 — 서비스 계층 단일 관문

**집행 지점 = `src/backend/whymath_backend/l1/problem_bank/provenance_gate.py`.**
`problem` 행을 만드는 코드는 이 관문을 경유하고, `source_type='자체생성'`이면 같은 트랜잭션에서
`content_provenance` 행을 남긴다. 관문은 `schema.ContentProvenance`의 법적 불변식(ORIGINAL 차단·
EBS_LICENSED 차단·메타 전용 출처 3규칙)을 **재구현하지 않고 반드시 경유하게** 만든다.

집행 배선 4점(정본화와 별항 — "정본화를 집행으로 착각한 완료 선언 금지"):

| # | 무엇 | 어디 |
|---|---|---|
| ① | 파싱 단계 거부 — 생성물인데 원장 재료 결손이면 **DB 왕복 전에** 막는다(부분 적재 방지) | `l1/problem_bank/populate.py` `_record_from_raw` ④-b |
| ② | 적재 단계 원장 기록 — 문항 upsert와 **같은 트랜잭션**에서 `content_provenance` INSERT(멱등: 기존 행 있으면 비파괴 skip) | 같은 파일 upsert 루프 ③-b |
| ③ | "작동한 비율" 노출 — `ProblemBankPopulateReport.provenance_rows_loaded` | 같은 파일 리포트 dataclass |
| ④ | 단일 관문 동결 — AST 전수 스캔으로 관문 밖 쓰기 차단 | `tests/backend/db/test_problem_write_provenance_single_gate.py` |

④가 막는 우회 형태 3종: `pg_insert(ProblemORM)` Core 삽입(§2-⑤의 populate 형태) · ORM
`Problem.from_schema()` seam · `Problem(...)` 직접 생성. 별칭 해석은 **이름이 아니라 모듈 경로**로
한다 — `Problem`이라는 이름은 ORM과 Pydantic 스키마 양쪽에 있고 `api/problems.py`는 둘 다
import하므로(`:62`, `:72`), 이름으로 골랐으면 스키마 생성 수백 건을 쓰기로 오판했을 것이다.

---

## §5. 한계 명기 (정직 — "우회 불가능"이 아니다)

acceptance ①은 "현행 방침 유지 시 **우회 불가능성 증명**"을 요구한다. 본 판정은 현행 방침을
**부분 유지**(DB CHECK 미생성)하면서 집행을 schema 계층에서 서비스 계층으로 **승격**시켰으므로,
그 증명 의무를 다음과 같이 정직하게 정산한다.

1. **우회 불가능은 증명되지 않는다 — 증명하지 않는다.** 서비스 계층 집행이 닿는 범위는
   *저장소 안의 파이썬 코드 경로*다. `psql` 직접 접속, raw SQL 문자열, 다른 서비스의 커넥션,
   DBA 수기 작업은 막지 못한다. 그러므로 이 집행의 정확한 주장은
   **"저장소 코드 경로 전수 차단"**이지 "우회 불가능"이 아니다.
2. **완전 불가능을 원하면 3-C(제약 트리거)가 유일한 수단이다.** 그 승급 조건을 여기 못박는다 —
   **① 원장에 실제로 행이 쌓이기 시작하고(본 배선의 첫 적재 회차 이후) ② `backend-migrations`
   잡(실 PG)에서 트리거 변별력을 주입 검증할 수 있게 되면** 3-C를 재심한다. 재심 시점은
   `EOS-58`(G1 관통 실증) 또는 첫 대량 적재 회차 중 **먼저 오는 쪽**이다(만료 없는 유예 금지).
3. **REST 축은 아직 집행되지 않는다 — `LIC-09`가 소유한다.** `api/problems.py`는 요청 계약에
   provenance 좌석이 없어 관문에 넘길 재료가 없다. AST 가드에 **면제**로 올리되, 그 면제는
   `LIC-09`를 지목하며 `test_exemptions_name_a_live_successor_task`가 그 태스크의 done을
   감지해 **RED로 바뀌어 제거를 강제**한다(스스로 만료하는 면제 — `provenance_audit._KNOWN_GAPS`의
   `GrandfatherEntry` 만료 계약과 동형).
4. **범위 밖 축 2건(명시)**: `UPDATE`(기존 행 수정)는 이 가드가 보지 않는다 — DoD가 INSERT
   축이기 때문이다. 문항 외 AI 생성물(다중해 `l3/multi_solution.py`, 해 경로 `whs/path_promotion.py`,
   교수 슬롯 `l3/pedagogy/slot_generator.py:202`의 하드코딩 `provenance_id: None`)도 범위 밖이며,
   이 문서는 그것을 **미해결로 기록**할 뿐 해결했다고 주장하지 않는다.

---

## §6. 경계 — 무엇이 누구의 소유인가

| 축 | 소유 | 상태 |
|---|---|---|
| 코퍼스 **파일** 사이드카(`data/corpus/*/_provenance.json`)·pool 필드 | `ARCH-20` (done) — `ops/provenance_audit.py`, CI `ci.yml:523-524` 상시 | 집행 중 |
| 코퍼스 → **DB** 적재의 원장 동반 | **`LIC-03`(본 문서)** | 본 PR에서 착지 |
| 관리자 **REST** 생성의 원장 동반 | `LIC-09` | 미착수(면제·만료 계약) |
| A4 원장 스키마 3종 자체 | `LIC-01` (done · PR #861 `af712f09`) | 착지 |

`ARCH-20`과 본 태스크는 **다른 축**이다 — 그쪽은 파일이 사이드카를 갖췄는가를, 이쪽은 DB 행이
원장을 갖췄는가를 묻는다. 중복 소유 없음.

---

## §7. 변별력 실측 — 뮤테이션 13종 전건 RED

보호 장치는 **막으려는 상태를 실제로 주입해 RED를 확인한 뒤에만** 보호로 친다(CLAUDE.md).
순수 Python 하네스(셸 이스케이프 배제)로 주입하고 `cp` 백업으로 원복했으며, 주입 실재
(치환 count 1건 · `mutated != original`)와 원복 바이트 동일을 매 회차 단언했다.

| # | 주입 | 결과 |
|---|---|---|
| M1 | 재료 부재 거부 절 제거 | RED |
| M2 | `generation_type` 빈값 절 제거 | RED |
| M3 | `license` 빈값 절 제거 | RED |
| M4 | 법적 불변식 예외 삼킴(`raise` → `return None`) | RED |
| M5 | 생성물 판정 무력화(`is_generated_content` → False) | RED |
| M6 | 거부 메시지에서 slug 제거(침묵 실패 축) | RED |
| M7 | 파싱 단계 관문 무력화 | RED |
| M8 | 원장 행 미기록(`if gate_result is not None` → False) | RED |
| M9 | 멱등 파괴(기존 행 있어도 INSERT) | RED |
| M10 | 허용 목록 밖 모듈에 `problem` 쓰기 신설 | RED |
| M11 | 면제가 유령 태스크(`LIC-999`)를 지목 | RED |
| M12 | 면제 writer를 "관문 경유함"으로 위장 | RED |
| M13 | 탐지 규칙 사망(`_WRITE_FUNCS` 비움 → 스캔 0건) | RED |

**1차 회차에서 3건이 생존했고, 그 진단이 이 계약을 고쳤다**(기록을 남기는 이유 = 전건 RED만
보고하면 무엇을 고쳤는지가 사라진다):
- **M2·M3 생존** — 절을 지워도 enum 승격(`GenerationType("")`)이 대신 ValueError를 내서 거부가
  유지됐다. 즉 **픽스처가 그 절을 한 번도 밟지 않았다**. 절의 존재 이유가 *정확한 문면*이므로,
  축마다 기대 문면(`expected_fragment`)을 함께 단언하도록 고쳐 변별력을 복원했다.
- **M7 생존** — 이것은 가드 구멍이 아니라 **하네스 결함**이었다. `-k "(populate and provenance)"`
  선택자가 `test_populate_rejects_generated_record_without_generation_type`(이름에 "provenance"가
  없다)을 **선택하지 않았다**. 같은 뮤테이션을 단독 실행하면 RED였다. 일부만 RED인 결과는
  가드가 아니라 하네스를 의심하라는 단서다(CLAUDE.md "주입 자체의 실재").

**커버리지 주장 금지(명시)**: 13/13 RED는 *가드가 이 13개 축에서 세다*는 뜻이지 *빠뜨린 축이
없다*는 뜻이 아니다. 주입 목록에 오르지 않은 실패 모드는 이 숫자가 말하지 않는다 —
§5-4가 범위 밖으로 명시한 축들이 그 예다.

**대조군**: 성공 방향 픽스처 3건(코퍼스 실분포 통과 · 메타 전용 출처는 대상 아님 · 평가원 기반
변형은 합법)이 함께 있어 "전부 거부"라는 과잉 수정이 통과하지 못한다.

**부수 — 하네스 대장 축 2종(M14·M15)**: 본 배선은 `LIC-03 → LIC-01` 소프트 선행 분류를
`STAGE_BLOCKED` → `HISTORICAL`로 재분류했다(LIC-01이 done이 되어 그 문장이 과거 사실이 됐다 —
바로 위 `EOS-50 ↔ ARCH-31` 선례와 동형). 그 결과 "제외 필요 코드" 모집단이 실제로 0건이 되어
`test_repository_exclusion_backed_codes_are_actually_excluded`의 `assert needing` 공허성 가드가
**정상 상태를 상시 red로** 만들었다. 0건을 조용히 통과시키는 대신 *입력이 살아 있는지*
(분류표·코드 집합 비었는가)를 단언하고 교집합 0건은 skip하도록 고쳤으며, 그 새 가드도
주입 2종으로 검증했다 — `_CODES_REQUIRING_EXCLUSION` 비우기(RED) · `SOFT_DECLARED` 비우기(RED).
규칙 자체의 변별력은 합성 픽스처
`test_codes_that_cannot_be_hard_require_scheduler_exclusion`이 계속 주입 검증한다.

---

## §8. 재현

하네스는 이 저장소에 커밋하지 않았다 — 공용 뮤테이션 러너는 `HARN-120`이 소유하며, 그 규약이
정해지기 전에 1회용 형태를 저장소에 남기면 나중에 이관 부채가 된다. 위 13종은 (파일, 원문,
치환문) 삼중항이므로 표만으로 재구성 가능하다. 판정 대상 스위트는
`cd src/backend && python -m pytest -k "provenance_gate or problem_write_provenance or populate"`
이며, 기준선·원복 후 양쪽에서 exit 0이어야 한다.

---

## §9. 기존 코퍼스 복원 — 별도 도구 불요(실측)

**질문**: LIC-03 이전에 적재된 문항(원장 없음)의 provenance를 되살릴 수 있는가.

**답: 100% 가능하다. 별도 백필 도구가 필요 없다.** 재료가 어디에도 소실되지 않았기 때문이다 —
§2-④대로 `license`·`generation_type`·`original_source`는 **코퍼스 JSONL에 그대로 살아 있고**
적재 단계에서 버려졌을 뿐이다. 적재기가 멱등 upsert이고 원장 기록이 "없으면 넣는다"라서,
**같은 적재 명령을 다시 돌리는 것이 곧 복원**이다.

실측(2026-09-22 · 로컬 PostgreSQL 16 + pgvector · 코퍼스 파일 37개):

| 단계 | 문항 | 원장 | 소요 |
|---|---|---|---|
| 최초 적재 | 14,034 | 14,034 | 81.3s |
| 원장만 삭제(= LIC-03 이전 상태 재현) | 14,034 | 0 | — |
| **재적재(복원)** | 14,034 | **14,034** | 81.2s |

복원율 14,034/14,034 = **100.0%**, 문항 중복 0(멱등 upsert가 slug 충돌을 흡수). 코퍼스 실분포가
`generation_type=FULLY_GENERATED` · `license=WHYMATH_GENERATED` 전건 균일이라 관문 거부도 0건이다.

**전제 2건(명시)**: ① 복원은 *코퍼스에서 적재된* 문항에만 해당한다 — 관리자 REST로 만들어진
문항은 코퍼스에 원본이 없어 이 경로로 복원되지 않는다(`LIC-09` 소유) ② 적재기 CLI는
`--problems` 경로를 하나씩 받으므로 전 코퍼스 복원은 37회 호출이다(`--all` 플래그는 없다).

**검증 방법**: CLI stdout이 `출처 원장(content_provenance) 신규 기록: N건`을 보고한다. 0건에는
두 의미가 있어 화면에서 구분한다 — *이미 있어서* 0(멱등 재적재·정상)과 *관문 무작동*이라 0.
첫 적재인데 0이면 후자다("작동한 비율" 원칙 — 적재 성공 건수는 원장이 일했다는 증거가 아니다).
