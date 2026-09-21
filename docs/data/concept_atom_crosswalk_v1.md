# 와이매스 437↔원자 크로스워크 v1 (자체 유도) — 데이터 카드

> **요약**: 구 개념그래프(437개념·`concept_graph_v1`)와 신 원자 백본(원자 1,837·`atom_graph_v1`)을
> 잇는 **프로그램적 유도 다리 코퍼스**. Phase 5에서 구 437 그래프를 폐기하려면 437-키 자산
> (behavior_skills·concept_content K-12)을 원자 축으로 옮겨야 하는데, 그 이관(S0-2)이 소비하는
> 매핑이 이 크로스워크다. **rekey 금지** — 기존 테이블 키는 바꾸지 않으며 크로스워크는 독립
> 코퍼스다(인계 문서 `docs/handoff/atom_backbone_next_session.md` §5.4 Phase 4-ⓐ).
>
> **상태(2026-07-03)**: S0-1 초회 유도 — 437/437 매핑(미매핑 0)·전량 `ai_estimated`(사람 검수 전).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | **자체 프로그램적 유도**(손저작 아님) — `data_pipeline/concept_atom_crosswalk/derive.py` |
| 소스 ① | `data/corpus/concept_graph_v1/graph.json`(concept_id·standard_codes) + `concepts.jsonl`(name_ko, `source_id`=`src_id` 조인) |
| 소스 ② | `data/corpus/atom_graph_v1/graph.json` — **원자(level=='세부개념') 1,837만** 대상(단원 217·소단원 643 제외) |
| 산출 | `data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl`(437행·concept_id 사전순) + `_provenance.json`(소스 sha256·유도 방법·커버리지) |
| 저작 | 와이매스 자체 유도 — 양측 소스가 전부 자체작성 코퍼스라 **redaction 불요**(코드·이름만 사용·성취기준 본문 미포함) |
| 재생성 | `python -m data_pipeline.concept_atom_crosswalk derive` (저장소 루트에서·결정론 — 동일 입력 2회 실행 시 byte 동일) |

## 2. 스키마 (`CrosswalkEntry` — 행당 1 JSON)

| 필드 | 형 | 의미 |
|---|---|---|
| `concept_id` | str (PK) | 구 437 그래프 concept_id(`math.<area>.<slug>`) — 코퍼스 내 유일 |
| `atom_codes` | list[str] | 매핑된 원자 code 목록(**1:N 허용**·code 사전순·미매핑 시 `[]`) |
| `primary_atom_code` | str \| null | 귀속 기준 원자(**정확히 1개**·atom_codes에 포함·미매핑 시 null) |
| `match_method` | enum | `standard_code`(교집합 유일) / `standard_code+name`(이름 랭킹 개입) / `unmapped` |
| `confidence` | float 0~1 | 결정론 산식 — 유일 후보 0.9 · 복수 후보 0.5+0.4×(최고 자카드) · 미매핑 0.0 |
| `evidence` | str | 유도 근거 요약(교집합 성취기준·후보 수·자카드 점수·primary 원자명) |
| `review_status` | 고정 | `ai_estimated` — 전량 프로그램적 유도·사람 검수 전 |
| `unmapped_reason` | str \| null | 미매핑 사유(`unmapped`일 때만·강제 매핑 금지 — #419 '미매핑 정직 표기' 선례) |

## 3. 유도 규칙 (결정론·외부 라이브러리 0)

1. **1차 다리 — 성취기준 교집합**: 양측 `standard_codes`(NCIC truth source *코드*)의 교집합으로
   개념→원자 후보 집합 생성. 성취기준 코드가 유일한 의미론적 조인 축(본문 미사용).
2. **2차 다리 — 이름 토큰 자카드**: 후보가 복수면 이름 토큰(단어 run + 문자 bigram — 한국어
   복합어 부분 겹침 포착) 자카드 유사도로 랭킹 → 최상위가 `primary_atom_code`.
3. **후보 0 → unmapped**: 강제 매핑 없이 사유 기록.
4. **결정론**: 동률 시 원자 code 사전순. Date/random 미사용 — 동일 입력이면 byte 동일 산출.

## 4. 귀속 규칙 (S0-2 소비 계약)

- **1:N 매핑 시 mastery/오개념 귀속은 `primary_atom_code` 기준**이다. `atom_codes`는 "무엇이
  후보였나"(감사·검수용), `primary_atom_code`는 "어디에 귀속하나"(이관용) — 역할이 다르다.
- 소비 측은 크로스워크를 *읽기만* 한다. 구 437 키 자산의 키를 바꾸지 않는다(rekey 금지).
- `unmapped` 행을 만나면 강제 귀속하지 말고 skip + 로그(조용히 넘기지 않음).

## 5. 커버리지 실측 (2026-07-03 유도)

| 항목 | 값 |
|---|---|
| 총 행 | **437 / 437** (구 그래프 전량·미매핑 포함 원칙 — 이번 유도는 미매핑 0) |
| 매핑 | **437 (100%)** — 전부 `standard_code+name`(모든 개념이 후보 ≥3, 유일 후보 케이스 없음) |
| 미매핑 | **0** |
| 1:N 분포 | 후보 3개: 421 · 4개: 8 · 5개: 2 · 6개: 3 · 7개: 1 · 9개: 2 |
| confidence | min 0.5 · 중앙값 0.7667 · max 0.9 — 자카드 1.0(=0.9) 117행 · 자카드 0(=0.5) 3행 |
| 거버넌스 하한 | 매핑 ≥ 350(#419 선례 수준) — `tests/data_pipeline/concept_atom_crosswalk/test_corpus.py` 동결 |

## 6. 한계·검수 상태

- **전량 `ai_estimated`** — 이름 자카드는 표면 문자열 겹침이라 primary 선택이 교수학적 최적이
  아닐 수 있다(특히 자카드 0으로 code 사전순 fallback한 3행: `math.algebra.hapui-giho` ·
  `math.coordinate.du-jeom-saiui-geori-2` · `math.place-value.suui-bunhae-hapseong`).
  사람 검수(샘플 5%+저신뢰 행 우선)는 후속 슬라이스.
- 구 개념은 원자보다 굵은 단위라 1:N이 정상이다(평균 후보 ≈3) — primary 1개로 귀속을 좁히는
  것 자체가 손실 압축임을 소비 측이 인지해야 한다(후보 전체는 `atom_codes`에 보존).
- 소스 코퍼스가 바뀌면 재유도 필요 — 거버넌스 테스트가 드리프트(dangling·누락)를 잡는다.

## 7. 소비처 (S0-2 — 437-키 자산의 원자 축 이전·2026-07-03)

backend `whymath_backend/l1/concept_atom_crosswalk/`(`transfer.py` 유도·갱신 + `populate.py` CLI)가
이 크로스워크를 *읽기만* 하여(rekey 금지) 두 437-키 자산을 원자 축에 투영한다. 조인 축은 유도와
동일: 크로스워크 `concept_id` ↔ `concept_graph_v1/graph.json`의 `source_id`(=`src_id`).
마이그레이션 `b2c3d4e5f0a1`이 두 이전 컬럼(ARRAY(Text)·NOT NULL·기본 `'{}'`)을 신설했다.

### ① behavior_skills 전파 → `atom_node.behavior_skills`
- 원천: #419가 `concept_graph_v1/concepts.jsonl`에 저작한 concept→skill 매핑(404/437·미매핑 33은 `[]`).
- **전파 규칙 (S0-2 확정)**: 각 크로스워크 행의 **`atom_codes` 전체**(primary만 아님)에 concept의
  behavior_skills를 전파. 한 원자에 복수 concept이 닿으면 **union+dedup·사전순 정렬**.
  - 근거: 스킬은 개념의 *구성 원자 전체*에 적용되는 인지 행동이며 배타 귀속이 아니다. §4의
    primary 귀속 규칙은 mastery/오개념 *이력 귀속*용이지 스킬 *전파*용이 아니다(역할 분리).
  - `unmapped` 행은 skip + 보고(§4 계약 그대로). 스킬 빈 concept의 원자도 빈 배열로 갱신
    (재실행 시 stale 청소·멱등).
- 실측(2026-07-03): 전파 대상 원자 **1,324** · 스킬 보유 원자 **1,211** · 유니크 스킬 **27/27**.

### ② K-12 콘텐츠 원자 연결 → `concept_content.atom_codes`
- 대상: `concept_content` K-12 행 437(code=구 437 개념코드 — Phase 3 Slice 1이 "원자 연결은
  Phase 4"로 예고한 좌석). 크로스워크 행의 `atom_codes`(dedup·사전순)를 그대로 투영.
- **대학 행(409·소단원코드 키)은 무변경**('{}' 유지) — 이미 원자 그래프와 같은 키 공간이라 원자
  정합(다리 불요). 갱신 SQL의 `scope='K-12'` 필터가 구조적으로 차단(키 공간 무교차와 이중 방어).
- 실측(2026-07-03): K-12 **437/437** 전량 연결·dangling 0.

### ③ 런타임 concept.behavior_skills 전파 (SKB-01·2026-09-12)
- ①과 **같은 mapping**(atom code → behavior_skills)을 런타임 `concept` 테이블(`atom_backend_concept`
  적재·`code`=원자/소단원/단원 code)에도 전파한다 — `concept.code`는 원자 code와 같은 키 공간이라
  별도 다리·유도가 불요하다.
- 원인: `atom_backend_concept.py`는 `concept` 행을 채우지만 `behavior_skills`는 건드리지 않아
  (신규 행 `server_default '{}'`) 이 컬럼이 EOS-63 실측(2026-09-10) 기준 2,683/2,683 전량 빈
  배열이었다. `Concept`에는 `updated_at` 컬럼이 없어(atom_node와 달리) 그 필드는 SET하지 않는다.
- prod 반영은 게이트 실행이 선행돼야 한다(human gate — `docs/ops/g_skb01_concept_behavior_skills_populate_runbook.md`).

### 게이트
- 거버넌스(hermetic): `tests/backend/l1/concept_atom_crosswalk/test_crosswalk_transfer_governance.py`
  — 전파 스킬 ⊆ 27 정본·전파 원자 ⊆ 세부개념·K-12 437 전량·대학 키 무교차·커버리지 하한.
- 전파 규칙 동결·SQL 배선: `test_crosswalk_transfer.py`(hermetic) · 실 PG end-to-end:
  `test_crosswalk_transfer_integration.py`(@integration).

## 8. 검증·게이트

- 파이프라인: `data_pipeline/concept_atom_crosswalk/` (`models.py`·`derive.py`·`validate.py`·CLI)
- CLI: `python -m data_pipeline.concept_atom_crosswalk derive|validate` (error 시 비정상 종료)
- 검증 규칙: 양측 code 실재(dangling 0) · 437행 전량 존재 · concept_id 중복 0 · primary
  유일성·atom_codes 포함 · 커버리지 실측 보고
- 테스트: `tests/data_pipeline/concept_atom_crosswalk/` — hermetic 단위(모델·derive·validate) +
  실코퍼스 거버넌스(437행·dangling 0·커버리지 하한 350)

---

**버전**: v1 (2026-07-03) | **작성**: data-engineer (S0-1) · §7 소비처: backend-engineer (S0-2) | **다음**: S0-3 problem_concept 재연결·사람 검수
