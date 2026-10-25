# 와이매스 원자 진단·소크라테스 v1 (`atom_probe`) — 데이터 카드

> **요약**: 원자 백본(`atom_graph_v1`)의 세부개념 원자 **<!-- fact:atom_graph.atoms -->1,823<!-- /fact -->건**이 보유한 **②진단문항**(발문·정답/
> 통과기준·오답신호)과 **③소크라테스 질문**을 *DB 적재 가능한 1급 프로젝션*으로 승격하는 데이터 카드.
> 출처는 `data/corpus/atom_graph_v1/graph.json`(Phase 1 산출). 신규 경량 **`atom_probe`** 테이블
> (code PK·FK 0·additive)에 멱등 투영한다.
>
> **현황(2026-06-23 · Phase 3 Slice 3)**: 로드맵 Phase 3 결정 ③("4요소→정식 콘텐츠 소스 승격")의
> ②진단문항·③소크라테스 조각. 원자 메타 프로젝션(`atom_node`)은 ①②③ 4요소 *본문을 의도적으로
> 미적재*했고, Slice 2가 ①오개념(`misconception_catalog`)을, **이 슬라이스가 ②③의 유일 승격 좌석**
> 이다. ②(3필드)·③(1필드)는 같은 원자 행·code 1:1이라 **한 테이블에 묶는다**(`concept_content`가
> 콘텐츠 4종을 한 테이블에 묶은 선례). 로더 `l1.atom_probe.projection`(투영+store) → CLI
> `l1.atom_probe.populate`. 신규 마이그레이션 `b9c0d1e2f3a4`(head, down=`a8b9c0d1e2f3`).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | `atom_graph_v1` graph.json `concepts` 배열 중 세부개념 원자(level=='세부개념') |
| 원천 코퍼스 | `data/corpus/atom_graph_v1/graph.json`(**커밋됨** — Phase 1 산출) |
| 저작 | **와이매스 자체/AI 작성**(진단문항·소크라테스 질문·검수필요) |
| 규모 | **<!-- fact:atom_graph.atoms -->1,823<!-- /fact -->**(원자 전량이 ②③ 보유 — 초등<!-- fact:atom_graph.atoms_elementary -->382<!-- /fact -->·중학<!-- fact:atom_graph.atoms_middle -->180<!-- /fact -->·고등<!-- fact:atom_graph.atoms_high -->749<!-- /fact -->·대학<!-- fact:atom_graph.university_atoms -->512<!-- /fact -->) |

> 원자 백본 원본 xlsx는 커밋하지 않는다. 진실 원천은 커밋된 graph.json(원자 백본 데이터 카드
> `atom_graph_v1.md` §6 Phase 1 참조).

---

## 2. 스키마 (소스 키 → `atom_probe` 컬럼)

| 소스 키(graph.json) | 컬럼 | 비고 |
|---|---|---|
| `code` | **PK** `code` | 원자 세부개념 code(예 `2수01-01-2`·`CALC1-C01`)·<!-- fact:atom_graph.atoms -->1,823<!-- /fact --> 유일 |
| `name` | `name` | 원자명(표시·NOT NULL) |
| `school_level` | `school_level` | 초등/중학/고등/대학교(필터·인덱스) |
| `subject_area` | `subject_area` | 영역·과목(필터·인덱스) |
| `subunit` | `subunit` | 소단원명 |
| `diagnostic_item` | `diagnostic_item` | ②발문 |
| `diagnostic_answer` | `diagnostic_answer` | ②정답·통과기준 |
| `diagnostic_signal` | `diagnostic_signal` | ②미통과·오답신호 |
| `socratic` | `socratic_question` | ③소크라테스 질문(키 rename만) |
| `intrinsic_difficulty` | `intrinsic_difficulty` | 난이도 1~5(정수) |
| `standard_codes` | `standard_codes` | 연결 NCIC 성취기준 *코드* 배열(본문 아님·TEXT[]) |
| (상수) | `review_status` | `'ai_estimated'`(코퍼스 미수록·적재기가 박음·정직 표기) |
| (상수) | `updated_at` | `now()`(upsert 시 갱신·신선도) |

**매핑 원칙(원천 보유 필드만·날조 0)**: 원자 행에 없는 칸은 두지 않는다. ②③가 *전부 빈 값*인 원자·
code/name 없는 항목·비-원자(단원/소단원)는 *건너뛴다*(조용한 빈 적재 금지). 정상 코퍼스 기대 = <!-- fact:atom_graph.atoms -->1,823<!-- /fact -->.

---

## 3. 라이선스·안전

| 대상 | 분류 | 처리 |
|---|---|---|
| ②진단문항(발문·정답·오답신호)·③소크라테스 질문 | **와이매스 자체/AI 작성** | 보존·redaction 불요 |
| `standard_codes` | 공공·사실 구조 메타 | 보존(코드만·**본문 X**) |

> NCIC 성취기준 *본문*은 코퍼스에 **애초에 없고**(연결 코드만 다리), `AtomProbeRecord`·ORM에 본문
> 슬롯을 두지 않아 **구조적으로 차단**한다(concept_content·atom_node 동형). 미성년자 PII 무관(탐침은
> 교수학 콘텐츠·학생 데이터 아님). `licensing_safety.md` "외부 큐레이션 코퍼스 v3"(자체 저작) 행에 포섭.
> `review_status='ai_estimated'`는 *AI 추정·검수필요* 정직 표기(노출 게이팅은 소비계층 책임).

---

## 4. 불변식 (적재 검증)
- `code` **<!-- fact:atom_graph.atoms -->1,823<!-- /fact --> 유일**(PK).
- 원자 전량이 ②③ 중 최소 1개 보유(전부 빈 값 행 0 — 실측 both-empty 0).
- `intrinsic_difficulty` 값이 1~5 범위(범위 이탈 0) 또는 None.
- 멱등: `ON CONFLICT(code) DO UPDATE` 재적재 시 행수 불변(중복 0).
- `review_status` 전 행 `'ai_estimated'`(상수).

---

## 5. 소비처 (적재 후 · 역방향 의존 금지)
- **L2 진단**: 원자별 ②진단문항으로 약점 진단 프로브 구성(통과기준·오답신호 활용).
- **L4 소크라테스 코칭**: 원자별 ③소크라테스 질문을 막힘 지점 발문 시드로(Polya·소크라테스 엔진).
- **L6 모드**: 학교진도/수능/사고력 모드의 원자 단위 점검 문항.

> 이 좌석은 *적재·보관 전용*이다(벡터 컬럼 없음·검색 메서드 없음). 조회·조인·노출은 후속 슬라이스.

---

## 6. 구조·테이블 (additive·신규 좌석)

`problem`(UUID PK·provenance·저작권 validator·문항형식 enum·`problem_step`/`problem_concept`)은 원자
code-grain과 어긋나 결합 시 UUID·source_type 등 *날조*가 필요하고, `dialogue`/`dialogue_turn`은 *런타임*
대화 로그라 *정적 저작* 콘텐츠와 맞지 않는다. 따라서 Slice 1(`concept_content`)·Phase 2a(`atom_node`)
선례대로 **신규 경량 code-PK 프로젝션 테이블**을 둔다(구 437·concept_node·atom_node·concept_content·
misconception_catalog와 무충돌·**FK 0**·loose ref). PG native enum 미생성(전부 TEXT/INTEGER).

| 항목 | 값 |
|---|---|
| 테이블 | `atom_probe`(code PK·인덱스 `ix_atom_probe_school_level`·`ix_atom_probe_subject_area`) |
| 마이그레이션 | `b9c0d1e2f3a4`(head·down `a8b9c0d1e2f3`·왕복 안전·native enum 0·FK 0) |
| 로더 | `l1.atom_probe.projection`(`AtomProbeRecord`·`AtomProbeStore` 멱등 upsert·슬3 `_build_sync_engine` 재사용) |
| CLI | `python -m whymath_backend.l1.atom_probe.populate --graph data/corpus/atom_graph_v1/graph.json` |

**잔여**: K-12 437↔원자 크로스워크(concept_src_id 연결)는 Phase 4. 구 개념그래프 폐기는 Phase 5.

---

**버전**: v1 | **최종 수정**: 2026-06-23 | 관련: `atom_graph_v1.md`·`misconception_catalog_v1.md`·
`concept_content_v1.md`
