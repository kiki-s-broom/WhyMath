# Problem 메타데이터 7필드·문제 유형 6슬롯 계약 (P3-04)

> **정본.** 7필드가 무엇이고 언제 "있다"고 치는지, 6슬롯이 무엇이고 어떻게 표기하는지의 정의는
> 코드 한 곳(`schema/problem_metadata.py`)에 있고 이 문서는 그 해설·대조표다. 둘이 어긋나면 코드가
> 이긴다. 측정 결과(수치)는 이 문서가 아니라 `docs/reviews/p3_04_problem_metadata_status_2026-10-14.md`
> 에 있다 — 수치는 P3-05가 채울 때마다 바뀌므로 정의 문서에 굳히지 않는다.

출처: 지시문 세트 [07] P3-04. 원문은 `docs/strategy/phase3_math_eos_completion_instruction_set.md`.

## 1. 한 줄 요약

- 문제(Problem)가 **Published가 되려면 7필드가 전부 있어야** 한다. 하나라도 없으면 발행이 거부된다.
- 각 핵심 개념마다 **6가지 유형(슬롯)** 의 문제를 갖춘다. 슬롯은 문제의 태그(데이터)다.
- 새 컬럼도, 새 마이그레이션도, 새 Entity도 없다. 모두 기존 저장 위치에 **매핑**했다.

## 2. 스키마 대조표 — 7필드 ↔ 기존 저장 위치 (개명하지 않고 매핑)

| 필드 | 저장 위치 (DB) | 코퍼스 파일에서의 형태 | "있다"의 기준 | 증거 속성 |
|---|---|---|---|---|
| `difficulty` | `problem.difficulty_overall` | `difficulty_overall` | 유한한 수(NaN·∞·bool 아님). 값의 범위는 가정하지 않는다 | `difficulty` |
| `skill` | `problem_concept`(PRIMARY) → `concept.behavior_skills` → 실재하는 `skill_node` | 문제유형(`problem_type_codes`) → 문제유형의 행동 스킬 | 레지스트리에 **실재하는** 스킬이 1개 이상 (이름만 적힌 스킬은 세지 않는다) | `skill_ids` |
| `concept` | `problem_concept`(role=PRIMARY) | `concepts[role=PRIMARY]` | PRIMARY 개념 연결 1개 이상 | `concept_ids` |
| `solution` | `problem.answer_explanation` | `answer_explanation` | 공백이 아닌 해설 | `solution_text` |
| `answer` | `problem.answer` | `answer` | 공백이 아닌 정답 | `answer` |
| `misconception_signature` | `problem.distractor_map` ∪ 소속 개념의 등록 오개념 | `distractor_map` ∪ 오개념 코퍼스의 개념 귀속 | **§3의 슬롯별 규칙** | `own_misconception_ids` · `concept_misconception_ids` |
| `hint_strategy` | `hints`(`problem_id` 일치, `verified = true`) | **없음** (측정 불가) | 검증된 힌트 1개 이상 | `verified_hint_count` |

주의 — **`SignaturePattern` 은 오개념 서명이 아니다.** `schema/enums.py`의 `SignaturePattern`(10종:
`CONDITION_LIST`·`COMPOSITE_DIFFERENTIABILITY` 등)은 "한국 수능 시그니처 패턴"이다. 이름이 닮았을
뿐 오개념과 무관하다. 태스크 등재 시 notes가 이 enum을 근거로 든 것은 오독이었고, 매핑에 쓰지
않는다.

### 3상태 판정 — "모른다 ≠ 있다"

각 필드의 판정은 셋 중 하나다.

- `PRESENT`(있음) · `MISSING`(측정했고 비어 있음) · `UNKNOWN`(측정하지 못함)

증거가 `None`이면 `UNKNOWN`이다. **`UNKNOWN`은 통과가 아니다** — 7필드가 전부 `PRESENT`일 때만
완전하다. 측정 도구가 죽거나 증거를 못 읽은 날 "비어 있지 않으니 통과"로 위장되는 길을 막는다.
`difficulty`는 부동소수라 "비어 있음"을 표현할 값이 없어, 컬럼을 읽었는데 NULL이면
`EMPTY_DIFFICULTY`(NaN)를 쓴다(`None`을 쓰면 "측정 못함"이 되어 거부 사유가 틀려진다).

## 3. 오개념 서명 — 슬롯별 규칙 (Kiki 결정 2026-10-14)

| 슬롯 | 인정 기준 |
|---|---|
| **오개념 유발**(`misconception_trigger`) | **문항 자체에 연결된 오개념**이 있어야 한다. 개념 상속으로는 인정되지 않는다 |
| 그 밖의 5슬롯 · 슬롯 미지정 | 문항 자체 연결이 있거나, **소속 개념에 등록된 오개념**이 있으면 인정 |
| 슬롯을 알 수 없음 | 완화 규칙을 쓰지 않는다 — 상속만으로는 인정하지 않는다 |

**"문항 자체 연결"의 정의.** `distractor_map`의 `misconception_id` 중 **등록된 오개념에 닿는 것**만
센다. kebab id는 `misconception_crosslink`에, M-id는 `misconception_catalog`에 실재해야 한다(P3-02
계측기의 `_reached_misconceptions`와 같은 기준). 닿지 못하는 id는 서명이 아니다.

**왜 슬롯별로 다르게 했나 (결정 근거 · 실측).**
- 대표 과정 신규 문제은행 504건에서 문항 자체 오개념 연결(`distractor_map`)은 **84건뿐**이고, 그
  84건이 `misconception_trigger` 슬롯 문항 84건과 정확히 같은 집합이다. 나머지 420건은 단답형이라
  오답 보기가 없어 연결을 달 자리 자체가 없다.
- "모든 문제가 문항 자체 연결을 가져야 한다"로 하면 420건이 새 데이터 작업(저장 좌석 신설 포함)
  없이는 영원히 발행될 수 없다 — 지시문 [08] ③은 오개념 유발 문제에만 서명을 요구한다.
- 반대로 "개념 상속이면 충분"으로 하면 오개념 유발 문제도 자기 서명 없이 통과해 [08] ③과 어긋난다.

**한계.** 상속으로 인정된 서명은 문항 고유의 보증이 아니다. 그래서 판정 결과에
`misconception_source`("own" / "concept")를 남겨 "상속만으로 채워진 비율"을 따로 센다 — 규칙을
**충족시킨** 경우에만 채워진다(트리거 슬롯에서 거부된 상속 증거가 "concept"로 집계되지 않는다).

## 4. 힌트 전략 정의 (Kiki 결정 2026-10-14)

그 문항의 `verified = true` 힌트가 1개 이상이면 `PRESENT`. 새 컬럼을 만들지 않고 기존 `hints`
좌석을 읽는다. 미검증 힌트(`verified = false`)는 학생에게 제공될 수 없으므로 세지 않는다.

- 파일 코퍼스에는 문항별 힌트가 없다 → 힌트 입력이 없는 실행의 증거는 `UNKNOWN`(측정 불가)이다.
- P3-22 착지: `phase3_coverage --hints-from-db` 가 `hints.verified = true` 행의 문항 집합을 읽어
  `CoverageCorpus.hint_problem_ids` 를 채운다. 그러면 이 필드가 Concept Completeness 의 hint 연결과
  함께 측정된다. DB 를 못 읽으면 exit 2 이고 측정 불가로 조용히 내려가지 않는다. DB 힌트 문항이
  JSONL 은행과 겹치는 수는 `hint_seat` 로 보고된다(ID 공간 불일치가 '힌트 0'으로 위장되지 않게).
- `hints`는 DB `problem` 행을 가리키므로, 코퍼스 문항이 DB에 적재돼 있어야 발행 게이트가 힌트를
  읽을 수 있다.

## 5. 6슬롯 — 정의와 표기

| 슬롯 id | 이름 |
|---|---|
| `representative` | 대표 |
| `basic` | 기본 |
| `applied` | 응용 |
| `misconception_trigger` | 오개념 유발 |
| `diagnostic` | 진단 |
| `mastery_check` | 숙련도 확인 |

- **표기**: 기존 `problem.tags`(텍스트 배열) 컬럼에 `p3-slot:<id>`로 적는다. 새 컬럼 없음.
  P3-03 문제은행 504건이 이미 이 표기를 쓴다.
- **오타 탐지**: `p3-slot:aplied`처럼 접두는 맞는데 6개 id에 없는 태그는 조용히 버리지 않고
  `unknown`으로 남기며, 계측기가 실패로 보고한다.
- **칸이 채워졌다**: 핵심 개념 c와 슬롯 s에 대해, 적격(검수 `approved`) 문항 중 PRIMARY 개념이 c이고
  슬롯 태그 s가 달린 문항이 명세의 슬롯당 최소 수 이상. `misconception_trigger`는 **문항 자체 오개념
  연결이 있는 문항만** 센다.
- **중복 기준은 이 문서의 범위 밖이다.** 지금은 문항 수를 센다. 근사 중복(거의 같은 문제를 여러 개
  넣어 수치를 채우는 것) 판정 기준은 P3-05가 정한다.
- **슬롯 지표의 목표 수치는 없다.** 명세에 슬롯 목표가 없고, "핵심 Concept 6슬롯 충족"은 P3-05의 완료
  판정이다. 그래서 지표는 보고되지만 CLI 종료 코드에 반영되지 않는다.

## 6. 집행 지점 — 정본화와 집행을 분리해 적는다

이 계약은 선언만으로는 아무것도 막지 않는다. 막는 곳은 두 군데다.

| 시점 | 집행 지점 | 무엇이 막히나 |
|---|---|---|
| **저장(발행) 시점** | `l3/problem_publish_gate.py`의 PUBLISH 게이트 → `problem_metadata_complete` 검사 | 7필드 중 하나라도 `MISSING`·`UNKNOWN`이면 `PublishGateError`. 아무것도 쓰이지 않고 판은 `APPROVED`에 머문다 |
| **CI 시점** | `tests/backend/l1/test_phase3_problem_metadata_ratchet.py` (실 코퍼스 래칫) + `phase3_coverage` 계측기 | 파일로 측정 가능한 6필드의 결손 0, 적격 문항 수·슬롯 칸 수 하한, 알 수 없는 슬롯 태그 0 |

**왜 이 한 곳이 우회로 없는 관문인가.** 문항이 Published가 되는 길은 `problem_publish_gate`
하나뿐이다. 관리자 CMS는 `status`·`is_published`·`current_published_version_id`를 편집 가능
필드로 선언할 수 없고(`api/admin_cms_resources.WORKFLOW_STATE_COLUMNS`, 기동 시점에 거부) `problem_version`
쓰기는 AST 동결 테스트가 이 모듈에만 허용한다.

**7필드는 발행의 조건이지 승인의 조건이 아니다.** 제출·검토·승인은 증거 없이 진행되고, 조건을 못
채운 판은 `APPROVED`에서 멈춘다.

**CI 쪽이 "발행된 행"을 검사하지 않는 이유.** 코퍼스 <!-- fact:problem_bank.total -->14,742<!-- /fact -->행 중 `is_published=true`는 0건이다.
"발행된 행은 7필드가 있어야 한다"를 코퍼스에서 검사하면 대상이 0건이라 공허하게 통과한다 —
그래서 CI 쪽은 **적격(approved) 문항 전체**에 같은 판정을 걸어 "발행되면 거부될 문항"을 미리 센다.

**CI 쪽이 못 보는 필드.** `concept`은 정의상 범위 안 문항이면 항상 있다(PRIMARY 개념이 없으면 범위
밖이 되어 분모에서 빠진다) — 그 결손은 적격 문항 수 하한이 잡는다. `hint_strategy`는 코퍼스에
없어 `--hints-from-db` 없이는 측정 불가이며, 저장 시점 게이트가 판정한다.

## 7. 검증 (변별력)

정상 입력의 초록은 증거가 아니라서, **실패 상태를 주입해 RED를 확인**했다.

- **필드 누락 주입 7건 → 7건 모두 거부.** (a) 단위: 증거의 한 필드만 비우면 그 필드 하나만 거부
  사유로 나온다(`test_problem_publish_gate.py`). (b) 실 PostgreSQL: 실제 행을 필드별로 망가뜨리면
  `PublishGateError`가 나고 판은 `APPROVED`에 머물며 포인터가 비어 있고, 고치면 같은 경로로
  발행된다(`test_problem_version_publish_integration.py` F절).
- **슬롯 주입.** 슬롯 태그를 하나 지우면 슬롯 지표가 정확히 1칸 떨어지고 다른 네 지표는 그대로다.
- **구현 뮤테이션 30종 전건 검출**(생존 0). 판정부·게이트 배선·DB 로더·계측기의 핵심 절을 하나씩
  지워 가며 테스트가 RED가 되는지 봤다. 매 주입마다 치환 대상이 정확히 1건인지·결과가 원본과 다른지를
  단언했고, 원복은 바이트 백업으로 하여 sha256 일치를 확인했다.

## 8. 알려진 한계 · 후속

| 항목 | 상태 |
|---|---|
| `distractor_map`의 id가 L4 카탈로그(`CATALOG_BY_ID`)에 있는지 | 보지 않는다 — l3은 l4를 import할 수 없다(7계층 단방향). 대신 DB의 크로스링크·카탈로그로 "등록된 오개념에 닿는가"를 본다 |
| 개념의 오개념 상속 | `concept.source_id` ↔ `misconception_catalog.concept_src_id` **문자열 일치**에 기댄다. `source_id`가 비어 있는 개념은 상속 증거가 없는 것으로 센다 |
| 발행 **이후**의 제자리 편집이 필드를 비우는 경우 | 이 검사는 발행 순간의 라이브 행을 잰다. 발행 이후 드리프트는 `EOS-195` 소관 |
| 힌트를 채우는 일 | `P3-32`(핵심 개념 힌트 연결) — 계측기 입력 배선은 `P3-22` 로 착지했다 |
| 슬롯 칸의 중복 기준·SymPy 검증된 정답만 세기 | `P3-05` |
| `is_published`(학생 노출 플래그) | 판 생명주기와 **별개의 축**이다. 이 계약은 건드리지 않는다 |
| 이미 발행된 문항의 소급 재평가 | 하지 않는다. 운영 DB의 `problem.problem_version_id`는 발행 호출 표면이 없어 전부 NULL이라 소급 대상이 없다(`EOS-194` 등재 근거) — 이 사실은 이 환경에서 직접 확인하지 못했다 |

## 9. 변경 이력

- 2026-10-14 신설(P3-04). Kiki 결정 2건: ① 오개념 서명은 슬롯별로 다르게 ② 힌트 전략은 검증된 힌트
  1개 이상.
