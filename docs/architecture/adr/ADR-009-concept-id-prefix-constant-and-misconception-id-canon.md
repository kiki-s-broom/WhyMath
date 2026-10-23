# ADR-009 — 개념 ID 접두를 코드 상수 집합으로 조립하고, 오개념 ID의 정본을 `M####`(데이터)로 선언한다

- **상태:** **Proposed** — 등록 `ARCH-104`(EOS 감리 WP-B). 결정 1(접두 상수화)은 같은 PR에서 코드로 이행됐고(동작 불변·테스트 동봉), 결정 2~4는 선언이다.
- **결정일:** 2026-10-23 (등록일 · 판정 기준 main `0523e19e`)
- **대상:** `src/data-pipeline/data_pipeline/concept_graph/models.py`(`CONCEPT_ID_PATTERN` — 접두 집합 `SUBJECT_PREFIXES`에서 조립) · `idmap.py`(패턴을 import해 쓰는 쪽) · `data/corpus/misconceptions_v1`(843건, `M####`) · `l4/misconception/catalog.py`(72종, kebab) · `data/corpus/misconception_crosslinks_v1`(승인 69건)
- **관련:** [ADR-003](./ADR-003-subject-prefix-is-convention-not-entity.md)(과목 접두는 규약 — "유효 집합은 코드 상수") · 감리 2026-10-19 W-13(사고실험 C5) · `docs/standards/part9_id_policy_review.md` · `docs/standards/crosswalk_gate_contract.md` · `P3-57`·`P3-61`

---

## 맥락 (사실만 — 판정 기준 main `0523e19e`, 2026-10-23 재대조)

| 사실 | 근거 |
|---|---|
| 개념 ID 정본 `math.<area>.<slug>` **437건**(간선 581), 각 노드가 별칭 3종(교육과정축 코드 `ELEM-NPLACE-001` · 옛 UC `UC.math.a01.n1` · 원 src_id `N1`)을 보존한다. 별칭 1,311개는 전부 canonical 패턴이 **거부**한다(별칭은 PK가 아니다) | `data/corpus/concept_graph_v1/graph.json` · `part9_id_policy_review.md` |
| ADR-003은 "접두사의 유효 집합은 코드 상수(enum 또는 frozenset)로 관리한다"고 했으나, 감리 시점의 실체는 `r"^math\.…"` **정규식 리터럴**이었다 | ADR-003:31 · 변경 전 `models.py:40` |
| `idmap.py`는 패턴을 따로 갖지 않고 `models.CONCEPT_ID_PATTERN`을 import해 쓴다(:48, 검증 :456). 다만 새 ID를 만들 때 `f"math.{area}.{slug}"`로 접두를 직접 붙이는 곳이 2곳 있다(`idmap.py:477` · `seed.py:96` `math.seed.…`) — 수학 개념 그래프 **생성기**라서 `math`가 맞는 자리이며 이 ADR의 범위 밖이다 | `data_pipeline/concept_graph/` grep |
| 오개념 ID는 **2계열**: 데이터 `M####`(`mis_id`) **843건** ↔ 코드 kebab **72종**(감리 초안은 64 — 테스트 주석 기준 10/15에 68(`MISC-21` 3종·`MISC-40` 1종 좌석 보강), 10/18 `P3-61`(#1688)이 +4 → 72). 크로스링크는 사람 검수 승인분 **69건**만 `crosslinks.json`에 있고, 검수 큐(`docs/data/misconception_crosslink_review_queue.json`) 119행은 전부 `pending`으로 남아 있다 | `misconceptions_v1/misconceptions.json` · `tests/backend/l4/test_misconception_catalog.py:30` · `misconception_crosslinks_v1/_provenance.json` |
| 코퍼스 오답 보기 **12건**은 kebab이 아니라 raw `M0674`를 달고 있다(`P3-57`) — `catalog.py`의 `mvt-conditions-unchecked` 주석이 그 사실을 적는다(:961-963) | `data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl` · `catalog.py:957-973` |
| 코드의 `Misconception.id` 필드 설명은 "정본 ID — kebab-case"인 반면, crosswalk 계약 문서는 "리포트에 뜨는 **canonical M-id**"라고 부른다 — 같은 단어 "정본"이 두 방향을 가리킨다 | `l4/misconception/models.py:51-53` · `crosswalk_gate_contract.md:10` |
| 1차 감리의 ADR-003 초안(`concept.math.quadratic-function` · 앱 ID `P###`)은 437건 정본과 충돌해 폐기됐다 | 감리 보고서 2026-10-19 부록 A |

## 결정

1. **개념 ID 접두를 집합에서 조립한다 (이 PR에서 이행 완료)**: `CONCEPT_ID_PATTERN`은 `SUBJECT_PREFIXES: frozenset[str] = frozenset({"math"})`에서 `build_concept_id_pattern()`으로 조립한다(`^(?:math)\.[a-z]+(-[a-z]+)*\.[a-z0-9]+(-[a-z0-9]+)*$`). 접두 추가는 이 집합에 토큰 1개를 더하는 것으로 끝난다. 조립은 정렬·비캡처 그룹으로 하여 판정과 캡처 그룹 번호가 리터럴 시절과 같고, 빈 집합·`[a-z]+`가 아닌 토큰은 거부한다(빈 접두가 `.area.slug`를 통과시키는 것 방지).
   - 검증: 정본 437 ID와 별칭 1,311개, 음성 표본이 옛 리터럴과 **같은 판정**(`tests/data_pipeline/concept_graph/test_concept_id_prefix_set.py`). 집합에 `chem`을 넣었을 때만 `chem.` ID가 통과하는 변별 테스트와, 집합을 비우거나 바꾸면 RED가 되는 테스트가 있다(뮤테이션 8종 전건 검출).
2. **오개념 ID의 정본은 데이터 `M####`다 (선언)**: DB PK와 코퍼스 843건이 그것이다. 코드의 kebab id는 런타임 탐지용 **alias**다.
   - ⚠ **열린 쟁점**: 감리 초안은 "`catalog.py` 각 항목이 `canonical_id="M####"`를 가져야 한다"고 적었다. 그런데 kebab→M#### 대응은 이미 **승인·서명 게이트를 통과한 별도 데이터**(`misconception_crosslinks_v1` 69건, `crosswalk_gate_contract.md`가 "AI 자기승인 금지"로 통제)로 존재한다. catalog에 필드를 또 두면 같은 관계의 **두 번째 정본**이 생기고, 필드 채움은 사람 검수 없이 이뤄질 수 있다. 그래서 필드 신설(가)과 기존 크로스링크 재사용(나) 중 무엇으로 갈지는 `P3-61` 후속에서 정한다. 이 ADR이 확정하는 것은 "정본 = 데이터 `M####`"라는 방향뿐이며, 12월에는 `Misconception.id` 필드 설명의 "정본" 표현도 건드리지 않는다.
3. **미검수 크로스링크는 일괄 승인하지 않는다**: 승인 수(69)를 늘리기 위한 일괄 승인은 하지 않는다. 검수 큐의 `pending`은 사람 서명이 있기 전까지 그대로 둔다(`crosswalk_gate_contract.md`).
4. **다른 ID 체계는 바꾸지 않는다**: 문항·성취기준·과목 enum의 ID 체계는 변경하지 않는다(`ARCH-37` · ADR-003). `Subject` enum이 교과 축이 아니라 수능 선택과목 축이라는 사실은 `subject_pack_spec_v1.md` §0-1 표에 이미 명시했다.

## 대안과 기각 이유

- **ID 전면 개편(`concept.math.…`)**: 기각. 437건 재발급·별칭 3계열 추가·코퍼스 참조 파손.
- **kebab을 정본으로**: 기각. 데이터 843건이 `M####`이고 DB PK도 그것이다.
- **패턴을 접두별로 여러 개 두기**: 기각. 접두 추가가 정규식 수정이 되어 ADR-003의 "유효 집합은 코드 상수"를 다시 위반한다.

## 결과

- 화학 사고실험의 개념 ID 항목은 "집합에 `chem` 추가"로 축소된다(패턴 수정 불필요). 그 밖의 새 과목 동작 경로 변경점은 `subject_pack_spec_v1.md` §0-1이 소유한다.
- 2027 이월 후보인 "오개념 상수 데이터 이전"은 결정 2의 방향(정본 = 데이터)을 전제로 한다.

## 중단 규칙

- 패턴 조립 변경으로 정본 437건 중 **1건이라도** 거부되면 되돌린다(집합 조립이 틀린 것). 위 테스트가 이 규칙을 기계로 지킨다.
- 결정 2의 방향(정본 = `M####`)은 `P3-61` 후속에서 크로스링크 재사용이 불가능하다고 판정되면 그때 다시 본다.
