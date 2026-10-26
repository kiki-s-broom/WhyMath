# CAT 형제 필터의 관계 유형 정책 (PB-19)

> 판정 기준: 작업 브랜치 `claude/trusting-johnson-m1hd1m`의 분기점 `d873d064`(= 착수 시점 main) 위에서 실측했다.
> 근거 문서: `problem_bank_variants_pb09.md` §5-1. 코드: `l2/next_problem_selection.py`
> (`classify_relations`·`RelationRoles`·`load_sibling_ids`) · 소비처 `l2/recommendation_policy.py`·`api/_next_problem_policy.py`.

## 1. 조사 (acceptance ①)

### 호출 경로 — 형제 집합이 소비되는 곳은 정확히 세 군데다

| 소비처 | 위치 | 쓰임 |
|---|---|---|
| CAT 기본 정책 | `l2/recommendation_policy.py` `CatRecommendationPolicy.__call__` | `exclude`: 후보 쿼리의 `NOT IN` · `include`: `_combine_axes`의 `sibling_weights` |
| 수능 정책 | `api/_next_problem_policy.py` `SuneungRecommendationPolicy.__call__` | 같은 두 용법 |
| 정렬 재선택 | `recommendation_policy.py` `_select_aligned` | 위 `sibling_ids`를 인자로 받아 `_combine_axes`에 넘길 뿐 — 새 조회 없음 |

세 곳 모두 `load_sibling_ids(session, 직전_오답_문항)` 하나에서 집합을 받는다. 필터는 `sibling_filter`가 지정되고
직전 오답이 있을 때만 돌며 기본값은 OFF다(`GET /v1/me/next-problem?sibling_filter=`).

### 현행(PB-19 이전) 동작

`load_sibling_ids`는 `problem_relation`의 양방향 행을 **유형을 보지 않고** 상대편 id를 전부 모았다.
변형·유사만 있던 코퍼스(S4-18: 유사 1,707 · 변형 421)에서는 맞았다. PB-09가 `선수`·`심화`·`대조`를 낳으면 깨진다.

### 유형별 효과 (오답 문항 W 기준 · 상대 O)

| 행 | O의 정체 | 현행 `exclude` | 현행 `include` | 문제 |
|---|---|---|---|---|
| `W→O 변형/유사` | 근접 복제본 | 배제 | 우대 | 의도대로 |
| `W→O 선수` | **W의 선수(더 쉬움)** | 배제 | 우대 | 배제는 Polya와 정면 충돌 |
| `O→W 심화` | **W의 기초(더 쉬움)** | 배제 | 우대 | 위와 같음 |
| `W→O 심화` | **W의 심화(더 어려움)** | 배제 | **우대** | 오답 직후 난이도를 올리는 쪽으로 가중 |
| `O→W 선수` | W의 후속(더 어려움) | 배제 | **우대** | 위와 같음 |
| 대조(어느 방향) | 역문제 | 배제 | 우대 | 난이도 계열도 형제도 아님 |

### 방향 규약 (실측)

`선수`·`심화`를 쓰는 작성자는 `l3/equivalent/variants.py`뿐이고 행은 항상 **parent(기존 문항) → related(파생 문항)** 이다.
`선수`는 "related가 parent의 선수", `심화`는 "related가 parent의 심화"다(PB-09 §2). 따라서 오답 문항이 parent냐
related냐에 따라 역할이 뒤집힌다 — 방향을 보지 않으면 `O→W 심화`(O가 더 쉬움)를 어려운 쪽으로 잘못 읽는다.

## 2. 결정 (acceptance ②)

| 관계 | 오답 문항 기준 역할 | `exclude` | `include` |
|---|---|---|---|
| 변형 · 유사 | 대칭 형제 | **배제** | **우대** |
| 선수 (O가 W의 선수) · 심화 (W가 O의 심화) | 더 쉬운 관련 문제 | 배제하지 않음 | **우대** (오답 직후 우선 후보) |
| 심화 (O가 W의 심화) · 선수 (W가 O의 선수) | 더 어려운 관련 문제 | 배제하지 않음 | 우대하지 않음 |
| 대조 | 형제 아님 | 배제하지 않음 | 우대하지 않음 |

근거:
- **Polya "더 쉬운 관련 문제를 먼저"**(CLAUDE.md 교수학 금기 — 막혔을 때 바로 정답 제공 금지·Polya 4단계 우선). 오답 직후
  쉬운 계열은 발판이다. `exclude`가 그것을 빼면 학생이 막힌 자리에서 발판이 사라진다 — 그래서 `exclude`는 근접 복제본만
  뺀다. 그 뒤 후보 선택은 기존 θ·난이도 밴드가 맡으므로 쉬운 계열이 "강제"되지는 않는다(우대는 `include`에서 같은 1+BOOST 가중).
- **어려운 계열은 중립**이다. `include`가 우대하지 않고 `exclude`도 배제하지 않는다. "심화는 정답 직후 후보"라는 소비는
  *직전 정답*을 기준으로 하는 별도 소비처의 일이라 이 필터(직전 **오답** 기준)의 범위가 아니다 — §4 분리 항목.
- **대칭 우선**: 같은 상대가 대칭 행과 방향 행으로 함께 나오면 형제로 본다(근접 복제본은 방향 행이 더 있어도 근접 복제본 —
  현행 `exclude` 보존).
- **모순은 중립**: 같은 상대가 쉬운 쪽과 어려운 쪽으로 동시에 나오면(데이터 모순) 둘 다에서 뺀다. 어느 쪽인지 *모르는* 상대를
  우대하지 않는다.
- **새 가중 상수·새 enum 없음**: 쉬운 계열의 우대는 기존 `_SIBLING_BOOST`를 그대로 쓴다. 근거 없는 별도 수치를 만들지 않는다.

## 3. 집행 지점 (acceptance ③ — 정본화와 별항)

정책이 문서에만 있지 않도록 **호출 경로가 정책을 경유함**을 테스트로 동결했다.

| 무엇 | 어디서 | 동결하는 것 |
|---|---|---|
| 분류 표(유형×방향) | `tests/backend/l2/test_sibling_relation_policy.py` | 10행 파라미터 표 · `RelationType` 전 멤버가 대칭/선수/심화/중립 중 정확히 하나(신규 멤버가 생기면 RED) · 모순·대칭 우선·자기 행·문자열 입력 |
| 쿼리 1회·분류 경유 | 같은 파일 `TestLoadSiblingIds` | 쿼리 수 불변(유형 열만 SELECT 추가) · `exclude`/`include` 집합이 다름 |
| 현행 동작 대조군 | 같은 파일 | 과거 구현을 테스트에 복원해 혼합 코퍼스에서 선수·심화·대조까지 모음을 보이고(결함의 실재), 변형·유사만 있는 코퍼스에서는 **두 모드 모두 과거와 같은 집합**임을 보인다(회귀 0) |
| 핸들러→정책→쿼리 배선 | `tests/backend/api/test_me.py` `TestSiblingRelationTypePolicy` | `include` 가중 8행 표(방향 포함) · `exclude`의 `NOT IN` 바인드 값을 CAT·수능 **두 정책 모두**에서 · 필터 미지정 시 관계 조회 0회 |
| 실 PG 읽기 | `tests/backend/api/test_me_integration.py` | PG native enum `relation_type`을 정책 경유로 읽어 `exclude`가 유형을 구분(변형만 배제) |

기본값 OFF 회귀 0: `sibling_filter` 미지정이면 관계 조회 자체가 없다(`test_unset_filter_issues_no_relation_query`).

**결함 주입 검증**(정상 입력의 초록을 보호의 증거로 치지 않는다): 분류·모드·호출처·쿼리 열·전수 대조·모순·대칭 우선에
결함 10종을 주입해 **10/10 RED**, 실 PG 테스트에는 M1(과거 동작)·M3(`exclude`가 쉬운 계열 배제)를 주입해 `변형` 대조군은
통과하고 `선수` 케이스가 RED임을 확인했다. 주입 실재(`mutated != orig`)와 원복 바이트 동일은 하네스가 각각 단언했다.

## 4. 스코프 밖 · 분리한 것 (acceptance ④)

- 변형 코퍼스 편입 = `PB-20` · IRT 난이도 배선 = `PB-10`. 이 태스크는 **정책**만 정하고 `선수`·`심화` 행이 코퍼스에 들어오기
  전에 소비 경로를 안전하게 만든다. 현재 운영 코퍼스에는 두 유형의 행이 없으므로(유사·변형만) 라이브 동작은 바뀌지 않는다.
- **분리**: "심화는 정답 직후 후보"의 소비처(직전 *정답* 문항의 어려운 계열을 후보로 우대하는 경로)는 이 필터가 하지 않는다.
  결정만 이 문서에 남기고 구현은 후속 태스크로 등재했다(docstring 속 계획은 백로그를 대신하지 못한다).
- 세션 내 직전 오답이 아니라 *누적 오답*에 정책을 적용하는 확장, `similarity_score` 가중은 하지 않았다.

## 5. 검증 환경과 한계 (정직하게)

- 로컬 PG 16 + pgvector + `alembic upgrade head` 위에서 실 PG 통합 테스트를 실제로 실행했다(`WHYMATH_RUN_INTEGRATION=1`).
- 기본 CI는 통합 테스트를 건너뛰므로(`test_me_integration.py` 기본 skip), 실 PG 축의 상시 집행은 통합 잡이 있는 경로에 달려 있다.
- `exclude`의 실 배제 효과(모킹 세션은 `WHERE`를 평가하지 않음)는 바인드 값 검사와 실 PG 테스트가 나눠 증명한다.
