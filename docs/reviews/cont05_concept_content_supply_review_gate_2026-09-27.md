# CONT-05 판정 — 학생 학습 공급(`/study`)의 개념 콘텐츠 검수 게이트 (2026-09-27)

> **판정 기준**: main `0e7b4f6b`(이 브랜치의 분기점). 도달 실측은 저장소 코퍼스와 실제 컴파일러로
> 했고, 게이트 구현·테스트·뮤테이션은 같은 트리에서 돌렸다. 운영 DB는 실측하지 않았다(§1.4).
>
> **태스크**: `CONT-05-concept-content-supply-review-gate` · 게이트 `G-kg02-review-promotion-llm-session`의
> 입력 작업 · 선행 판정문 `docs/reviews/kg02_gate_premise_recheck_2026-09-25.md`(§4가 이 태스크를 낳았다).

---

## 0. 요약 (먼저 읽을 것)

| acceptance | 결론 |
|---|---|
| ① 도달 실측 | **잠복(현재 비활성)**. `/study`가 쓰는 학습목표 4건의 `concept_nodes[0]` 중 콘텐츠 행으로 해석되는 것 **0건**(K-12 0 · 대학 0). 우선순위는 2 유지(활성이었다면 1). 단 대학 콘텐츠 409건은 전부 원자 소단원 코드라, 대학 소단원 DSL이 하나만 생겨도 즉시 활성화된다. |
| ② 택1 판정 | **ⓐ 채택** — 공급은 `review_status == "reviewed"`만 통과(fail-closed). `knowledge_module_gap_review.md` §2-③ 의도적 제약의 집행이다. ⓑ(ai_estimated 허용)는 그 제약을 뒤집으므로 택하지 않았다. |
| ③ 집행 지점 | `l4/content_supply.py::resolve_concept_dsl` — 행을 읽고 → **게이트** → 그다음에 캐시. 캐시 적중도 게이트를 지난다(적중 시 PK 조회 1회). 차단 사유는 `UNREVIEWED`로 따로 센다. |
| ④ 변별력 | 신규 테스트 18건(단위 16 · 서빙 경로 2) + 뮤테이션 **7/7 RED**(게이트 제거·캐시 적중 우회 포함). 서빙 경로 테스트 **단독**으로도 게이트 제거·술어 완화를 잡는다. |
| ⑤ 문서 정정 | `review_gate.py`·`concept_content_review_apply.py` docstring의 "retrieval이 이 값으로 검색 히트를 거른다"를 철회하고 집행 지점을 `content_supply`로 지목했다. |
| ⑥ 게이트 연동 | ⓐ라서 승격이 학생 공급을 여는 **유일한 문**이 됐다. 다만 도달이 0이라 **지금 승격해도 학생 화면 변화는 0**이다. 이 사실을 `G-kg02` 제목에 반영해 Kiki 재판정 자료로 넘겼다(§6). |

부수 발견 2건은 범위 밖이라 후속 태스크로 등재했다(§7): 공급 조회가 크로스워크를 쓰지 않는 문제(`CONT-06`),
내부 정식정의가 렌더 조각으로 나가는 문제(`CONT-07`).

---

## 1. ① 도달 실측 — 학생 요청이 콘텐츠 행에 닿는가

### 1.1 무엇을 쟀나

학생 대면 `POST /v1/me/objectives/{objective_id}/study`는 `learning_objective` 행의 `concept_nodes[0]`을
콘텐츠 코드로 삼아 `concept_content`를 PK로 조회한다(`api/study.py` → `supply()` → 콘텐츠 해석).
그래서 "도달"은 **학습목표의 첫 개념 코드가 콘텐츠 행의 PK와 일치하는 수**다.

`learning_objective`의 생산 경로는 저장소에 **하나**다 — `l1/pedagogy/compile.py`(소단원 DSL 컴파일 CLI)가
`UnitSpecStore.seed`로 적재한다. 컴파일러는 `concept_nodes`를 원자 백본(`atom_graph_v1/graph.json`)의
코드로만 허용한다(없으면 `CompileError`). 데모 시드(`scripts/demo/seed_demo.py`)는 학습목표를 만들지 않는다.

### 1.2 결과

| 측정 | 값 |
|---|---|
| 콘텐츠 코퍼스 | K-12 437 · 대학 409 · `review_status` 전건 `ai_estimated`(846) |
| 원자 백본 유효 코드 | 2,683 |
| (A) 구조적 도달 가능성 — 콘텐츠 코드 중 원자 백본에 있는 것 | K-12 **0**/437 · 대학 **409**/409(전부 `소단원` 레벨) |
| (B) 실제 도달 — 저장소 소단원 DSL 1편(`quadratic_maxmin.unit.yaml`)을 컴파일한 목표 4건 | 콘텐츠 행으로 해석 **0**/4 — 4건 모두 세부개념 원자(`10공수1-02-06-1`·`-2`·`-3`)라 NO_DSL |

### 1.3 판정

**잠복(현재 비활성)** — 지금 이 게이트 때문에 학생 화면에서 사라지는 콘텐츠는 없다(원래 0건이 닿았다).
우선순위는 acceptance ①의 규칙대로 **2를 유지**한다.

활성화 트리거는 둘이다. 어느 쪽이든 생기는 순간 이 게이트가 실제로 학생 공급을 막기 시작한다.

1. **대학 소단원 코드를 개념 노드로 쓰는 소단원 DSL** — 대학 콘텐츠 409건은 원자 소단원 코드와 키 공간이
   같아, 그런 DSL이 컴파일되면 곧바로 콘텐츠에 닿는다.
2. **크로스워크 역조회** — K-12 콘텐츠 행은 `atom_codes`(437↔원자 크로스워크)를 갖고 있다. 파일럿 소단원의
   원자 3종은 실제로 K-12 콘텐츠 2행(`10기수1-02-05`·`HK11` "이차함수의 최대·최소", 둘 다 `ai_estimated`)에
   연결돼 있다. 그러나 공급 조회는 PK만 보므로 이 연결을 쓰지 않는다(§7 `CONT-06`).

### 1.4 재지 않은 것

- **운영 DB의 `learning_objective` 행** — 세션은 운영 DB를 읽을 수 없다. 저장소 밖(미머지 브랜치의 소단원
  DSL 등)으로 컴파일된 목표가 운영에 있다면 도달이 다를 수 있다. 위 결론의 범위는 "저장소 코퍼스와 유일한
  생산 경로 기준"이다.

재현 스크립트는 부록 A.

---

## 2. ② 택1 판정 — ⓐ 채택

### 2.1 근거

`docs/architecture/knowledge_module_gap_review.md`의 표가 "자동 정의 생성: 무검증 학생 노출 금지 —
`review_status=ai_estimated` + 검수 게이팅 필수(의도적 제약 §2-③)"로 이미 정했다. 코드가 그 제약을
집행하지 않았을 뿐이다. ⓑ는 그 제약을 뒤집는 결정이라 Kiki 판정과 결정 로그가 필요하고, 이 세션은
그 근거를 갖고 있지 않다. 그래서 기본값 ⓐ다.

### 2.2 ⓐ의 비용 (acceptance ②가 적으라고 한 것)

| 대상 | 영향 |
|---|---|
| 학생 화면(오늘) | **변화 0** — 도달이 원래 0이다(§1). |
| 학생 화면(활성화 뒤) | 도달한 목표는 KG-02 승격(Kiki 서명) 전까지 404("이 개념의 학습 콘텐츠가 아직 준비되지 않았습니다")를 받는다. 콘텐츠 846행이 전부 `ai_estimated`이므로 활성화 시점의 공급률은 0%에서 시작한다. |
| `SKB-04`(K-12 437행 운영 적재) | **충돌 없음** — 적재는 그대로 필요하다(행이 있어야 승격할 수 있다). 다만 적재가 학생 공급을 여는 것으로 읽으면 안 된다: K-12는 적재 후에도 ①키 공간(원자 코드 0 겹침)과 ②검수 전(ⓐ) 두 겹으로 공급되지 않는다. |
| `P3-02`/`P3-03` Content Coverage | **충돌 가능** — 정의 문면("완전 연결 Concept / 출시 대상 Concept")이 검수 상태를 말하지 않는다. 검수 전 콘텐츠를 "연결됨"으로 세면 **커버리지 95%인데 학생 공급 0%**가 성립한다. `P3-02` acceptance에 "완전 연결"의 검수 조건 판정 항을 덧붙였다(§8). |
| `PED-17`(생성 폴백 개방 판정) | ⓐ는 검수 전 콘텐츠를 "DSL 없음과 같게" 처리하므로, 생성 폴백이 열리면 검수 전 개념이 LLM 생성으로 간다. 사유가 `UNREVIEWED`로 분리돼 있어 PED-17이 둘을 다르게 다룰 수 있다 — 그 판정 항을 `PED-17`에 덧붙였다(§8). |

---

## 3. ③ 집행 지점

`l4/content_supply.py`에 `resolve_concept_dsl(code, *, session, cache, ttl_s) -> (DSL | None, 사유 | None)`을
두고, `supply()`는 이것만 부른다. 순서가 계약이다.

1. DB에서 행을 읽는다 — 없으면 `(None, NO_DSL)`.
2. **검수 게이트** — `l1/concept_content/review_gate.is_supply_eligible(row.review_status)`가 False면
   `(None, UNREVIEWED)`. 술어는 `"reviewed"`와 **완전 일치**만 True다(표기 변형·빈 값·None 거부).
3. 그다음에야 캐시를 본다 — 적중이면 캐시 DSL, 미스면 투영해서 적재.

**왜 캐시보다 먼저인가**: 종전 코드는 캐시를 먼저 봤다. 판정을 캐시에 맡기면 강등된 행(예: 코퍼스 재적재가
DB 승격을 되돌리는 경로 — 선행 판정문 §3.4)이 TTL 24시간 동안 계속 공급된다. 그래서 캐시 적중도 PK 조회
1회를 치른다. `/study`는 한 요청에서 이미 학습목표·학습자 상태·프로필 조회를 하므로 PK 조회 1회의 비용은
작고, 학생 안전(#1)이 비용(#6)보다 위다.

기존 테스트 `test_cache_hit_skips_db`("적중이면 DB를 안 탄다")는 이 계약과 정면으로 충돌해 **의도적으로**
`test_cache_hit_rereads_review_status_but_serves_cached_body`로 바꿨다 — 적중은 행을 읽되(get 2회) 본문은
캐시 것을 준다(두 호출 사이에 DB 본문을 바꿔 캐시가 여전히 쓰임을 대조).

그 밖의 계약:

- 차단된 행은 캐시에 적재하지 않는다.
- 차단 사유 `UNREVIEWED`는 `NO_DSL`과 **처리가 같다**(렌더 없이 폴백·404) — 사유만 따로 세어
  `SupplyTally.by_fallback_reason`과 `/study` 로그에 게이트 작동 횟수가 보이게 했다(작동한 비율 원칙).
- `get_concept_dsl`은 `resolve_concept_dsl`의 얇은 래퍼로 남겼다 — 판정을 래퍼가 아니라 해석 함수에 둬서
  어느 진입점으로 들어와도 같은 순서를 지난다.
- `/study`의 404 메시지는 바꾸지 않았다("아직 준비되지 않았습니다"는 검수 전에도 맞는 말이다).

---

## 4. ④ 변별력

### 4.1 테스트

| 파일 | 추가·변경 |
|---|---|
| `tests/backend/l4/test_content_supply.py` | `TestSupplyReviewGate` 16건 — ai_estimated 거부·미적재 · reviewed 공급(성공 방향 대조) · 없는 code는 `NO_DSL` · **캐시 적중 상태에서 강등 즉시 거부** · 술어 완전 일치(비통과 값 8종 거부 — ai_estimated·rejected·빈 값·None·표기 변형 4종) · 공급 경로 사유 집계 · 생성 폴백 호출자에게 기존 폴백 유지 · review_status 하나로 결과 반전. 캐시 테스트 1건 계약 변경(§3). |
| `tests/backend/api/test_study_endpoint.py` | `TestStudyReviewGateReach` 2건 — **`supply()`를 대역으로 바꾸지 않고** 세션 대역에 콘텐츠 행만 심어 reviewed → 201(`dsl_render`·처치 기록), ai_estimated → 404(처치 0건). |
| 행 대역 3곳 | `test_content_supply*.py`·`test_catalog_consumption.py`의 `_FakeRow`에 `review_status="reviewed"` — 렌더·집계 테스트가 게이트 통과 행을 전제함을 명시. |

실행: 관련 5개 파일 + `tests/backend/l1/` → 1,277 passed · 85 skipped(통합 기본 skip) · exit 0.

### 4.2 뮤테이션 (스크래치 하네스 · 주입 실재 단언 · 백업 바이트 원복 + sha256 대조 · `.pyc` 제거)

| # | 주입 | 결과 |
|---|---|---|
| M1 | 게이트 제거(acceptance ④ 지정) | RED |
| M2 | 게이트를 캐시 조회 뒤로 이동 — 캐시 적중 우회(acceptance ④ 지정) | RED |
| M3 | 술어 완화 — `rejected`만 거부 | RED |
| M4 | 술어 정규화 — 표기 변형(`" Reviewed "`) 통과 | RED |
| M5 | 사유 병합 — `UNREVIEWED`를 `NO_DSL`로 | RED |
| M6 | 차단 행도 캐시에 적재 | RED |
| M7 | `supply()`가 해석 사유를 버리고 항상 `NO_DSL` | RED |

대조군(무변형) GREEN · 7/7 RED · 원본 sha256 복원. `-x`로 첫 실패에서 멈추는 실행이라, 검출 주체를 따로
확인했다: **서빙 경로 테스트(`TestStudyReviewGateReach`) 단독**으로 M1·M3이 RED, **강등 테스트 단독**으로
M2가 RED다. 즉 "게이트가 서빙 경로에서 호출된다"와 "캐시 적중이 게이트를 우회하지 않는다"를 각각 한 테스트가
혼자서 증명한다.

---

## 5. ⑤ 문서 주장 정정

| 파일 | 종전 주장 | 정정 |
|---|---|---|
| `l1/concept_content/review_gate.py` | reviewed가 학생 노출 게이팅 기준이며 두 retrieval이 이 값으로 검색 히트를 거른다 | 판정 술어 `is_supply_eligible` · 집행 지점 `content_supply.resolve_concept_dsl`. 두 retrieval은 `concept_node`·`atom_node`를 읽는다(2026-09-25 실측)는 사실과 종전 주장이 틀렸음을 명기 |
| `harness/concept_content_review_apply.py` | 같은 주장(`l1/*/retrieval.py`) | 집행 지점 지목 + 검색 표면 무반응 명기 + "승격은 코퍼스 커밋까지가 한 동작"(선행 판정문 §3.4) |
| `api/study.py` | 404 = DSL 미적재 | 404 = DSL 미적재·**검수 전 콘텐츠**(게이트가 `supply()` 안쪽이라 라우터가 건너뛸 수 없음) |

---

## 6. ⑥ 게이트 연동 — `G-kg02-review-promotion-llm-session` 재판정 자료

세션은 사람 게이트를 닫거나 판정하지 않는다. 게이트 제목에 CONT-05 결과를 반영해(`gates amend --title`)
Kiki가 재판정할 사실을 넘겼다. 핵심 사실 셋:

1. **ⓐ 채택** — 승격(Kiki 서명)이 학생 공급을 여는 유일한 문이 됐다.
2. **도달 0** — 그러나 지금 승격해도 학생 화면은 바뀌지 않는다. K-12 콘텐츠는 키 공간이 달라 공급 조회에
   닿지 않고(`CONT-06`이 풀기 전까지), 대학 콘텐츠는 그것을 쓰는 소단원 DSL이 없다.
3. **등재 문면의 순서 전제가 흔들린다** — 제목의 재판정 ⓐ안은 "K-12 우선(대학 409는 KG-05 재작성 대상이라
   후순위)"인데, 도달 관점에서는 K-12 승격의 학생 효과가 `CONT-06` 착지 전까지 0이다.

세션 권고(판정 아님): **보류 유지** — 도달이 생기는 시점(CONT-06 착지 또는 대학 소단원 DSL 등장)에 그
목표들이 가리키는 콘텐츠부터 사람 검수를 여는 것이 학생 효과 대비 Kiki 시간이 가장 적게 든다. 파일럿 소단원
기준이면 `CONT-06` 착지 후 대상은 K-12 2행(`10기수1-02-05`·`HK11`)이다.

---

## 7. 부수 발견 — 후속 등재

| 태스크 | 내용 | 왜 이 태스크 범위 밖인가 |
|---|---|---|
| `CONT-06` | 공급 조회가 학습목표의 원자 코드를 콘텐츠 PK로만 찾는다 — 크로스워크(`concept_content.atom_codes`)를 채워 두고도 역조회하지 않아 K-12 콘텐츠 437이 `/study`에 구조적으로 닿지 않는다(파일럿 목표 4건 전부 NO_DSL, 연결된 K-12 콘텐츠 2행 실재). `atom_codes`의 유일한 소비자는 렌더의 `relations`다(선언≠배선). | 이 태스크는 공급의 **검수 게이트**다. 조회 키 공간을 바꾸는 것은 공급 **대상**을 바꾸는 별개 설계 결정(1:N 매핑의 대표 선택 포함)이다. |
| `CONT-07` | 내부 정식정의(`formal_definition_internal` — 모델·스키마·설계 문서 4곳이 "학생 비노출"로 규정)가 `from_concept_content`에서 `definition`으로 투영되고, `DIRECT`·`WORKED_EXAMPLE` 어댑터가 그것을 `definition` 조각으로 렌더한다. 실측: `WORKED_EXAMPLE`(힌트 3단계 신호)에서 표지 문자열이 조각에 나왔다. `/study`는 힌트 축을 채우지 않아 지금은 `SOCRATIC`이 골라져 미도달(잠복)이다. | 검수 상태(행 단위)가 아니라 **필드 단위 노출 정책**이다. reviewed 행이라도 "학생 비노출" 규정은 남는다. |

---

## 8. 이 판정이 바꾼 대장

| 대상 | 변경 |
|---|---|
| `CONT-05` | paths 3건 추가(행 대역 테스트 2파일·판정문) · acceptance에 판정 결과 기록 |
| `CONT-06`·`CONT-07` | 신규(§7) |
| `P3-02-coverage-instruments` | acceptance 덧붙임 — Content Coverage "완전 연결"이 검수 상태를 조건으로 삼는지 판정 |
| `PED-17-study-generate-fallback-decision` | acceptance 덧붙임 — 생성 폴백 개방 시 `UNREVIEWED`를 `NO_DSL`과 같게 둘지 판정 |
| `G-kg02-review-promotion-llm-session` | 제목 정정(§6 사실 반영 · 재판정 자료) — 게이트 상태는 `pending` 그대로 |

---

## 부록 A — 도달 실측 재현

저장소 루트에서 backend가 설치된 Python 3.12로 실행한다. 읽기 전용이며 DB가 필요 없다.

```python
"""CONT-05 ① 도달 실측 — /study가 쓰는 objective.concept_nodes[0]이 concept_content 행으로 해석되는가."""
import collections
import json
from pathlib import Path

from whymath_backend.db.models.concept_content import CONTENT_SCOPE_K12, CONTENT_SCOPE_UNIVERSITY
from whymath_backend.l1.concept_content.projection import load_concept_content_from_json
from whymath_backend.l1.pedagogy.unit_compiler import (
    compile_unit,
    load_packs,
    load_statements_by_code,
    load_valid_atom_codes,
)

REPO = Path.cwd()
k12 = load_concept_content_from_json(
    REPO / "data/corpus/concept_content_v1/content.json", scope=CONTENT_SCOPE_K12
)
univ = load_concept_content_from_json(
    REPO / "data/corpus/concept_content_university_v1/content.json", scope=CONTENT_SCOPE_UNIVERSITY
)
content_scope = {r.code: CONTENT_SCOPE_K12 for r in k12}
content_scope.update({r.code: CONTENT_SCOPE_UNIVERSITY for r in univ})

graph_path = REPO / "data/corpus/atom_graph_v1/graph.json"
graph = json.loads(graph_path.read_text(encoding="utf-8"))
valid_atoms = load_valid_atom_codes(graph_path)
level_of = {c["code"]: c.get("level") for c in graph["concepts"]}

# (A) 구조적 도달 가능성 — 컴파일러가 개념 노드로 허용하는 콘텐츠 코드
for scope in (CONTENT_SCOPE_K12, CONTENT_SCOPE_UNIVERSITY):
    codes = {c for c, s in content_scope.items() if s == scope}
    hit = codes & valid_atoms
    print(scope, len(codes), len(hit), dict(collections.Counter(level_of.get(c) for c in hit)))

# (B) 실제 도달 — 저장소의 모든 소단원 DSL을 컴파일한 목표 행의 concept_nodes[0]
packs = load_packs(REPO / "data/corpus/pedagogy_packs_v1")
statements = load_statements_by_code(REPO / "data/corpus/standards_v1/standards.json")
for unit in sorted((REPO / "data/corpus/units_v1").glob("*.unit.yaml")):
    compiled = compile_unit(
        unit.read_text(encoding="utf-8"),
        packs=packs,
        valid_atom_codes=valid_atoms,
        statements_by_code=statements,
    )
    for row in compiled.objective_rows:
        first = (row["concept_nodes"] or [None])[0]
        print(row["id"], first, content_scope.get(first, "NO_DSL"))
```
