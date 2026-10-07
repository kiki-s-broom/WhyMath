# M0599 보류 사유 · `provenance_note` 불일치 기록 (2026-10-07)

> 판정 기준: main `f79be260`
> 게이트: `G-misc40-deferred-m0599-redecision` (pending 유지 — Kiki 지시)
> 후속 태스크: `MISC-61-a3-thin-misid-source-enrichment`

## §1. 보류 사유 (Kiki 2026-10-07 판정)

`addition-multiplication-rule-confused` ↔ `M0599`(직접매핑 0.9) 행은 **보류를 유지**한다.

- **사유**: 검수 계약의 "4지선다 귀속 타당" 항목을 검증할 재료가 없다. M0599 행은 `canonical_statement`와 `correction_point`만 있고 `student_wrong_thinking`·`distractor_rule`·`error_type`이 모두 비어 있다(`null`).
- **의미 판단**: 매핑 방향(합의 법칙·곱의 법칙 혼동이라는 점에서 kebab과 M-id가 같은 오개념)은 타당하다고 본다. 보류는 의미가 틀려서가 아니라 **검증 재료가 없어서**다.
- **승인 가능 조건**: M0599의 빈 세 필드가 **원 출처 자료**에서 채워지고, 그 내용으로 4지선다 귀속을 대조할 수 있게 되면 재판정한다.
- **금지(순환 검증)**: 빈 필드를 카탈로그 kebab 쪽 서술(틀린 믿음·반례)을 복사해 채우지 않는다. 그렇게 하면 kebab과 M-id를 대조하는 검수가 같은 글을 자기 자신과 비교하는 것이 되어, 검수가 아무것도 확인하지 않게 된다.

## §2. 이슈 — `provenance_note = "distractor 연결됨"`인데 distractor 필드가 비어 있다

### 실측 (main `f79be260` · `data/corpus/misconceptions_v1/misconceptions.json` 843행)

| `provenance_note` | 세 필드 모두 빔 | 행 수 |
|---|---|---|
| `원본` | 아니오 | 381 |
| `AI생성-검수필요` | 아니오 | 337 |
| **`distractor 연결됨`** | **예** | **88** |
| `원본` | 예 | 21 |
| `AI생성-수기검증` | 아니오 | 12 |
| `AI생성-검수필요(…신규 저작)` | 아니오 | 4 |

"세 필드" = `student_wrong_thinking`·`distractor_rule`·`error_type`.

**`distractor 연결됨` 88행은 예외 없이 세 필드가 전부 비어 있다.** 표기는 "distractor가 연결됐다"고 말하는데 데이터에는 distractor 규칙이 한 건도 없다. M0599 하나의 문제가 아니라 이 표기를 단 행 전체의 문제다.

### 원인 가설 (어느 쪽인지 저장소만으로는 판정 불가)

- **가설 ① 원천 자체가 비어 있다** — 2026-06-20 업로드 원천 JSON(`fac16e6f…`, sha256 `fcf6d333…187e`)에서 이 88행이 처음부터 세 필드 없이 저작됐다. 이 경우 "연결됨"은 distractor가 *다른 곳*(예: 문항 쪽 `distractor_map`)에 연결됐다는 뜻일 수 있다.
- **가설 ② 추출 단계에서 조용히 빠졌다** — 추출기 `src/data-pipeline/data_pipeline/misconception/extract.py`는 고정 한글 키(`학생의_잘못된_사고`·`distractor_규칙`·`error_type`)만 읽고, 키가 다르면 경고 없이 `None`을 넣는다. 원천의 이 88행이 다른 키 이름(예: 별도 distractor 구조)을 썼다면 내용이 있는데도 빈 칸이 된다.

**판정에 필요한 것**: 원천 JSON 파일. 저장소에는 없다(`_provenance.json`에 이름·해시만 있음). Kiki 머신의 업로드 원본에서 이 88행의 실제 키를 확인해야 한다. 이 확인은 `MISC-61` ①이 소유한다.

### 앵커 A3에 미치는 영향

A3(`[9수04-05]`·`[9수04-06]`)의 M-id 4건이 **모두** 세 필드가 비어 있다.

| M-id | 성취기준 | `canonical_statement` | `provenance_note` |
|---|---|---|---|
| M0418 | `[9수04-05]` | 중복 계산 | 원본 |
| M0599 | `[9수04-05]` | 합의 법칙(또는)과 곱의 법칙(그리고)을 혼동한다. … | distractor 연결됨 |
| M0417 | `[9수04-06]` | 확률 1 초과 가능 | 원본 |
| M0600 | `[9수04-06]` | 경우의 수가 많으면 확률도 크다고 단정한다 … | distractor 연결됨 |

그래서 A3는 M0599를 대신할 "검증 재료가 있는" 후보가 하나도 없다. 좌석은 0으로 남는다(`tests/backend/l4/test_anchor_seat_gap.py`).

## §3. prod DB의 M0599 행 — "미검수 표시"가 가능한가 (조사만 · DB 수정 없음)

Kiki 지시: 삭제하지 말고, 미검수 상태로 표시만 할 수 있는지 먼저 확인해 보고한다. **DB는 수정하지 않았다.**

### 현재 상태
2026-10-06 읽기 전용 조회 실측(MEMORY.md 2026-10-06 항목): Kiki 머신 prod DB(`whymath-pg`)의 `misconception_crosslink`에 `addition-multiplication-rule-confused` ↔ `M0599` 직접매핑 0.9 행이 stamp `검수:kiki 2026-10-05`로 들어 있다.

### 테이블에 검수 상태를 담을 칸이 있는가 — **없다**
`src/backend/whymath_backend/db/models/misconception_crosslink.py`의 컬럼은 `link_id`·`kebab_id`·`mis_id`·`link_type`·`confidence`·`method`·`note` 7개뿐이다. `status`·`reviewed` 같은 칸이 없다. 이 테이블은 "적재됐다 = 승인됐다"를 전제로 설계됐다(적재기가 `note`의 검수 stamp를 요구하는 것이 그 승인 게이트다).

### 그러면 가능한 방법과 각각의 효과

| 방법 | DB 변경 | 런타임 효과 | 비고 |
|---|---|---|---|
| A. `note`만 바꾼다 (예: `미검수:보류 2026-10-07`) | 1행 UPDATE | **없음** — 해석기(`crosslink_resolve.py`)는 `kebab_id`와 `confidence`로만 거르고 `note`를 읽지 않는다. 이 행은 여전히 canonical M-id로 선택된다 | 사람 눈에는 표시되지만 기계에는 보이지 않는다. "표시했으니 안 쓰인다"고 믿게 만드는 위장 위험 |
| B. `status` 칸을 새로 만든다 | 스키마 마이그레이션 + 해석기·적재기·테스트 수정 | 해석기가 `status='approved'`만 읽게 하면 실제로 빠진다 | 코드 태스크 규모. 승인 계약 자체를 바꾸는 설계 변경 |
| C. `confidence`를 임계(0.6) 아래로 낮춘다 | 1행 UPDATE | 해석기에 `min_confidence`를 주는 경로에서만 빠진다. shadow 경로는 *전부 기록*이라 여전히 보인다 | 신뢰도 칸에 검수 상태를 숨기는 편법 — 권하지 않음 |
| D. 행 삭제 | 1행 DELETE | 빠진다 | Kiki가 보류(삭제 금지) 지시 |

### 지금 이 행이 실제로 무엇에 쓰이는가
해석기 소비처는 L4 증거 적재의 **crosswalk shadow 측정**(`l4/misconception/crosslink_shadow.py`, `evidence_store.py`)뿐이고, 그 모드의 기본값은 `off`다(`config.py` `misconception_crosslink_mode`). shadow라도 **비노출**(로그로 coverage만 남김)이다. 즉 현재 이 행은 **학생에게 노출되지 않는다.** 영향은 shadow를 켰을 때 A3 kebab이 "M-id 해석 성공"으로 계상되는 측정 왜곡뿐이다. 앵커 좌석 수(`anchor_seat_gap`)는 DB가 아니라 저장소 코퍼스 파일을 읽으므로 이미 0이다.

### 세션 의견 (결정은 Kiki)
- 지금 당장 학생 노출 위험은 없으므로 **급하게 DB를 건드릴 이유는 없다**.
- "표시만" 하려면 방법 A가 유일하게 작은 변경인데, **기계는 그 표시를 읽지 않는다**는 한계를 알고 써야 한다.
- 표시가 실제로 효력을 가지려면 방법 B(검수 상태 칸)가 필요하고, 이것은 별도 설계 판단이다. 필요하면 태스크로 등재한다.
