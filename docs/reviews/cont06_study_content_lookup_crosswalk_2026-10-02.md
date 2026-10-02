# CONT-06 판정 — `/study` 콘텐츠 해석의 크로스워크 역조회 (2026-10-02)

> **판정 기준**: main `a05eb49a`(이 브랜치의 분기점). 도달·분포 실측은 저장소 코퍼스로 했고(§1), 구현·테스트·
> 뮤테이션은 같은 트리에서 돌렸다. 운영 DB는 실측하지 않았다(§6).
>
> **태스크**: `CONT-06-study-content-lookup-crosswalk-unused` · 선행 판정문
> `docs/reviews/cont05_concept_content_supply_review_gate_2026-09-27.md`(§1.3·§7이 이 태스크를 낳았다).

---

## 0. 요약 (먼저 읽을 것)

| acceptance | 결론 |
|---|---|
| ① 실측 | 파일럿 원자 3종이 K-12 콘텐츠 2행(`10기수1-02-05`·`HK11`)에 연결돼 있음을 재확인했다. 원자 1,311종 중 **34종만** 후보가 2~3행이고 나머지는 1:1이다(§1). |
| ② 택1 | **ⓐ 채택** — PK 미스일 때 `atom_codes` 역조회. ⓑ·ⓒ는 택하지 않았다(§2). |
| ③ 게이트 불변 | 역조회로 고른 행도 CONT-05 게이트를 **같은 한 곳**에서 지난다. 행 → 게이트 → 캐시 순서가 유지되고, 캐시 적중이 게이트를 우회하지 못한다(테스트로 동결). |
| ④ 변별력 | 3상태(NO_DSL → 해석 → UNREVIEWED) 테스트 + 서빙 경로 테스트 + 뮤테이션 **10/10 RED**(§4). |

**잔여 위험 1건(§3)**: 크로스워크 연결 자체는 전건 `ai_estimated`이고 콘텐츠 검수 배치는 연결 원자를 보여주지
않는다. 그래서 `reviewed`가 "이 원자에 대한 콘텐츠로 맞다"까지 보증하지 못한다. 후속 `CONT-08`로 등재했다.

---

## 1. 실측

크로스워크(`data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl`) 437행을 구 개념 그래프의 `concept_id →
source_id` 다리로 콘텐츠 코드 축에 옮겨 셌다(부록 A).

| 측정 | 값 |
|---|---|
| 크로스워크 행 / 원자가 있는 행 | 437 / 437 (`unmapped` 0) |
| 연결되는 서로 다른 원자 | **1,311** |
| 후보 K-12 행이 2개 이상인 원자 | **34**(최대 3) |
| 매핑 근거·검수 | 전건 `standard_code+name` · `ai_estimated` (confidence 0.54~0.75) |

파일럿 원자 3종의 후보:

| 원자 | 후보 콘텐츠 행(confidence · primary 여부) |
|---|---|
| `10공수1-02-06-1` | `HK11`(0.6818 · 아님) |
| `10공수1-02-06-2` | `10기수1-02-05`(0.75 · primary) · `HK11`(0.6818 · primary) |
| `10공수1-02-06-3` | `HK11`(0.6818 · 아님) |

요점 둘: ① 대부분 1:1이라 대표 선택 규칙이 일하는 경우는 드물다 ② **`primary_atom_code`는 대표 선택에 쓸 수
없다** — 파일럿 `-2`는 두 행 모두 primary다.

## 2. 택1 판정 — ⓐ 채택

- **ⓐ(역조회)**: 콘텐츠 437행과 학생 공급 사이의 구조적 단절을 푸는 유일한 변경이고, 크로스워크가 이미
  `concept_content.atom_codes`에 채워져 있어 스키마·마이그레이션이 필요 없다.
- **ⓑ(학습목표를 콘텐츠 코드로 정렬)**: 컴파일러가 원자 백본 코드만 개념 노드로 허용하는 계약을 뒤집고, 목표
  → 원자 → 숙달/오개념 귀속 축(`concept_code`)이 구 437 택소노미로 갈라진다. 변경 범위가 학습목표 전체다.
- **ⓒ(비대상 확정)**: K-12 콘텐츠 437행이 만들어 둔 학생 가치(비유·오개념·허용표현)를 버린다. 근거가 약하다.

### 2.1 구현 규칙

| 규칙 | 내용 |
|---|---|
| PK 우선 | PK 적중이면 역조회를 하지 않는다(대학 소단원 코드는 PK로 이미 닿는다). |
| 범위 | `scope='K-12'` 행만 본다. 대학 행은 `atom_codes`가 비어 있고 PK로 닿는다. |
| 대표 선택(1:N) | 후보를 `code` 오름차순으로 모은 뒤 **검수 통과 행을 먼저** 고른다. 없으면 첫 행을 `UNREVIEWED` 보고용으로만 쓴다. |
| 선택 근거 | 후보 전체·서빙 코드·조회 경로를 반환값(`SupplyResult`)·trace·`/study` 로그·집계에 남긴다. |
| 캐시 키 | **서빙 행의 code**다. 요청 원자 code로 쪼개면 같은 본문이 원자 수만큼 중복되고 강등 시 낡은 항목이 따로 남는다. |
| 전원 미검수 | 후보가 있는데 하나도 통과 못 하면 `UNREVIEWED`(`NO_DSL` 아님) — 승격하면 열리는 상태이기 때문이다. |

대표 선택에 `primary_atom_code`·`confidence`를 쓰지 않은 이유: DB에는 `atom_codes`만 이전돼 있고(둘 다 없다),
런타임에 코퍼스 파일을 읽으면 요청 경로가 파일·배포 레이아웃에 의존한다. 위 실측대로 대표 선택이 일하는
경우가 34종뿐이라 그 비용을 질 이유가 없다. 둘이 모두 `reviewed`인 드문 경우는 `code` 오름차순이 임의적임을
인정하되 **결정론적이고 근거가 기록된다**.

## 3. 잔여 위험 — `reviewed` 는 연결을 보증하지 않는다

acceptance ②가 요구한 "검수 전 매핑으로 콘텐츠를 고르는 것"의 처리다.

- 역조회 후 `reviewed`인 콘텐츠 행은 연결된 모든 원자의 목표에서 학생에게 나간다.
- 그런데 연결(`atom_codes`)은 전건 `ai_estimated`이고, 콘텐츠 검수 배치(`harness/concept_content_review_batch.py`)의
  검수 입력에는 **연결 원자·매핑 confidence가 없다**(개념명·본문만). 검수자는 콘텐츠만 보고 `reviewed`를 찍는다.
- 결과: "콘텐츠가 맞다"가 "이 원자에 대한 콘텐츠로 맞다"로 읽히는 구멍이다. 연결이 틀린 경우(예: confidence
  0.54 연결) 맞는 콘텐츠가 엉뚱한 원자 목표에 나갈 수 있다.

이 태스크의 대응은 **가시성**까지다: 연결 방식이 `lookup_via="crosswalk"`로 응답·로그·집계에 드러난다. 구멍
자체(검수 입력 확장 또는 연결 검수 상태 도입)는 검수 공정을 바꾸는 별개 설계라 **`CONT-08`**로 등재했다
(`G-kg02` 승격 회차 전에 판정되어야 한다).

**지금 승격하지 않으면 노출 0이다** — 전건 `ai_estimated`라 게이트가 전부 막는다. 위험은 승격 *이후*에 생긴다.

## 4. 변별력

### 4.1 테스트

| 파일 | 추가·변경 |
|---|---|
| `tests/backend/l4/test_content_supply.py` | `TestCrosswalkReverseLookup` 11건 — 3상태(NO_DSL → 해석 → UNREVIEWED) · PK 우선(쿼리 0회) · 대학 행 제외 · 검수 통과 우선 · 동률 결정론 · 전원 미검수 사유 · 캐시 키가 서빙 행 · 강등 즉시 거부 · 두 원자의 캐시 공유 · 서빙 경로 집계/trace · **실 PG SQL 형태 동결**(scope·`= ANY(atom_codes)`·ORDER BY) |
| `tests/backend/api/test_study_endpoint.py` | `TestStudyCrosswalkReach` 2건 — `supply()`를 대역으로 바꾸지 않고 목표의 개념을 원자 코드로 두어 reviewed → **201**(처치는 원자 code에 귀속), ai_estimated → **404**(처치 0건) |
| `tests/backend/l4/test_catalog_consumption.py` | 세션 대역에 `execute` 추가 — PK 미스가 이제 역조회 쿼리를 부르므로 대역이 이를 받아야 한다(변경 이유 = 이 태스크) |

대역은 stmt를 **해석**한다(바인딩 값·scope·ORDER BY 유무로 걸러 돌려준다). 전건을 돌려주는 대역이면 쿼리의 scope·정렬
결함이 통과한다.

### 4.2 뮤테이션 (스크래치 하네스 · 주입 실재 단언 · 백업 `cp` 원복 + sha256 대조)

| # | 주입 | 결과 |
|---|---|---|
| M1 | 역조회 제거 | RED |
| M2 | 역조회 경로에서 게이트 생략 | RED |
| M3 | 캐시 키를 요청 code로 | RED |
| M4 | 대표 선택에서 검수 통과 우선 제거 | RED |
| M5 | `ORDER BY` 제거 | RED |
| M6 | `scope` 필터 제거 | RED |
| M7 | PK 적중에도 역조회 | RED |
| M8 | 전원 미검수를 `NO_DSL`로 | RED |
| M9 | `lookup_via` 집계 누락 | RED |
| M10 | trace의 `content_code` 누락 | RED |

대조군(무변형) GREEN · 10/10 RED · 원본 sha256 복원 · `.bak` 잔존 0.

### 4.3 CI 정적 검사 (CI와 같은 명령)

`ruff check . ../../tests/backend` 0 · `black --check --line-length 100 . ../../tests/backend` 0 ·
`mypy --strict whymath_backend` 0 · `lint-imports` 4 kept. 이 과정에서 **mypy가 잡은 결함 1건**: ORM `.any()`는
관계용 타입이라 배열 원소 포함에 쓸 수 없어 `sa.any_()`로 바꿨다(런타임 SQL은 `:atom = ANY(atom_codes)`).

## 5. 이 판정이 바꾼 것

| 대상 | 변경 |
|---|---|
| `CONT-05` 판정문 §6 | **전제가 풀렸다** — "지금 승격해도 학생 화면 변화 0"은 더 이상 참이 아니다. 파일럿 소단원 기준 승격 대상은 K-12 2행(`10기수1-02-05`·`HK11`)이고, 그 승격은 학생 공급을 실제로 연다. `G-kg02` 재판정은 **CONT-08 판정 뒤**가 안전하다. |
| `CONT-08` | 신규 — 검수 입력의 연결 가시성(§3). `CONT-06`에 의존. |
| 대장 | `CONT-06` paths 보강(`api/study.py`·서빙 경로 테스트·세션 대역·본 문서) |

## 6. 재지 않은 것

- **운영 DB** — `concept_content.atom_codes`가 운영에 실제로 채워졌는지(크로스워크 전이 적재 여부)는 세션이
  읽을 수 없다. 코퍼스·코드 기준이다. 비어 있으면 역조회는 NO_DSL로 정직하게 떨어진다(해롭지 않다).
- **전체 백엔드 스위트** — 관련 영역(`l1`·`l3`·`l4`·`api` 공급 경로 사용 파일)만 돌렸다. 전체는 아래 §7 참조.

## 7. 전체 스위트

(작성 시점에 아직 실행 전 — 실행 후 이 절에 종료 코드와 건수를 기록한다.)

---

## 부록 A — 분포 실측 재현

저장소 루트에서 실행한다. 읽기 전용이며 DB가 필요 없다.

```python
"""CONT-06 §1 — 크로스워크의 원자별 후보 콘텐츠 행 분포."""
import collections
import json

rows = [
    json.loads(line)
    for line in open("data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl", encoding="utf-8")
    if line.strip()
]
graph = json.load(open("data/corpus/concept_graph_v1/graph.json", encoding="utf-8"))
bridge = {c["concept_id"]: c["source_id"] for c in graph["concepts"]}  # concept_id → 콘텐츠 code

by_atom = collections.defaultdict(list)
for row in rows:
    for atom in row.get("atom_codes") or []:
        by_atom[atom].append((bridge[row["concept_id"]], row.get("confidence")))

print("distinct atoms", len(by_atom))
print("atoms with >1 content row", sum(1 for v in by_atom.values() if len(v) > 1))
print("max candidates", max(len(v) for v in by_atom.values()))
for atom in ("10공수1-02-06-1", "10공수1-02-06-2", "10공수1-02-06-3"):
    print(atom, by_atom.get(atom))
```
