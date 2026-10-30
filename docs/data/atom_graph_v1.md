# 와이매스 원자 백본 데이터셋 v1 (자체작성·K-12 3축 + 대학) — 데이터 카드

> **요약**: 기존 개념그래프(<!-- fact:concept_graph.concepts -->437<!-- /fact -->개념·<!-- fact:concept_graph.edges -->581<!-- /fact -->엣지)를 **원자(atom) 단위로 한 층 더 미세화**한 신규 학습
> 백본. **원자 <!-- fact:atom_graph.atoms -->1,823<!-- /fact --> · 선수엣지 <!-- fact:atom_graph.prerequisite_total -->3,251<!-- /fact -->**(원자ID <!-- fact:atom_graph.edges -->2,278<!-- /fact --> + 서술형 <!-- fact:atom_graph.narrative_edges_raw -->973<!-- /fact -->) · 초·중·고 + 대학 4축.
> (2026-08-10 정정: 생성 당시 1,837·2,213이었으나 2026-07-28 중복 원자 dedup 병합 14건
> — `dedup_merges_v1.json` — 이후 실측이 1,823·2,210이다. `subject_content_coverage_gap_review.md`
> §정정-ⓑ. 2026-10-09 S4-60이 고→대 경계 엣지 24건을 병합해 원자ID 엣지가 2,234가 됐고 이후 KG-10·KG-12 검수로 현재 값은 위 요약과 같다 —
> `docs/data/cross_band_edges_university_v1.md`.)
> 성취기준 코드(NCIC)·교수학 4요소(오개념·진단문항·소크라테스·전이)·원자성 메타를 포함하며,
> 기존 백본을 **전면 교체**한다(마이그레이션 로드맵: `ROADMAP.md` 및 결정 로그 참조).
>
> **상태(2026-10-20·KG-09)**: 통합마스터 **v3(2026-10-19 교차감사 정본)**로 graph.json **재생성** — v2 변경이력
> 3,709건(순서 역전 선수 엣지 결함 408건 삭제 → 정본 엣지 205건 교체·원자 본문 필드 정정 ~400건)과
> v3 교차감사 변경(미적Ⅰ 원자ID 표기 통일·서술형 엣지 973건 수작업 매핑 근거 열 보존·원자ID 직접
> 정규화 3건) 반영. 이관 3종(dedup 14·대학 성취기준 채움·행동스킬 병합)과 S4-60 경계 엣지 24건을
> 재적용해 노드 2,683·엣지 2,234 불변. 서술형 973건은 from=소단원/단원코드로 해소됐으나 파이프라인
> 엣지 모델(끝점=원자)상 `narrative_edges_raw` 패스스루에 둔다 — 대표 원자 해소는 후속 태스크.
> 교차감사 산출물 = `docs/data/cross_audit_2026-10-19/`.
>
> **상태(2026-10-20·KG-10)**: 서술형 973건의 대표 원자 해소를 **제안 원장**으로 냈다 —
> `narrative_edge_resolution_proposal_v1.json`(소단원 싱크 규칙·제안 1,018건·순환 충돌 73건 분리·빌더
> `scripts/build_narrative_edge_resolution_kg10.py` 결정론). 설계·전후 수치·교수학 검수·적용 범위 판정은
> `docs/data/narrative_edge_resolution_v1.md`. 재생성 체인은 `scripts/regenerate_atom_backbone_v3.sh`로
> 보존(경계 병합 전 정본을 바이트 동일 재현 실측). **KG-10 ② 경계 검수**(AI 2인 블라인드·
> `docs/data/ai_review_narrative_edge_resolution_v1.md`): KG-09 교체분의 학교급 경계 신규 10건 중 반려 3·교체 1을
> 정본 xlsx(변경이력_v3 No.16~19)에 반영해 재생성 — 엣지 **2,234→2,231**, 경계 50→47(중→대 0·고→대 25).
> 교수학 검토가 서술형 해소 규칙의 정본 반영은 FAIL로 판정해 ①은 미반영(원장 보존·후속 KG-11).
>
> **상태(2026-10-21·KG-12)**: ① 대학 내부 체인 역전 (가) 40건 AI 2인 블라인드 검수(`docs/data/ai_review_university_chain_repair_v1.md`)
> A합의 21 → 수정 엣지 16(제거 12·반전 4 · 원장 `university_chain_repair_v1.json`)을 정본 xlsx(변경이력_v3 No.20~35)에 반영해
> 재생성 — 엣지 **2,231→2,219**. ② 낱말 매칭 가드 4종(`narrative_edge_reference_ledger_v2.json` · 스테이징 183→109).
> ③ 합의 승인 90 ∩ 가드 통과 66을 3인째 블라인드 검수(`ai_review_narrative_edge_reference_v2_third.md`) — C 승인 62/66,
> Wilson 하한 0.8717 ≥ 0.80 PASS → **59건 승격 병합**(과목간 원장 유보 3 · `narrative_edge_promotion_v2.json`) — 엣지 **2,219→2,278**.
> 설계 `docs/data/narrative_edge_reference_v2.md`. 역사 원장(KG-10·KG-11 · 검수 행 번호의 정본)은 재생성하지 않고
> `data_pipeline/atom_graph/graph_history.py`가 묶인 정본(`721fe6ff…`)을 현재 정본에서 바이트 단위로 되감아 검증한다.
> 대학→고등 K-12 도달은 198→160(되감기 엣지 제거로 새 뿌리 5) — 보완 배선은 후속 `KG-13`.
> **prod 반영(KG-14 · 2026-10-21)**: 적재기는 추가·갱신만 해서 정본이 지우거나 뒤집은 엣지가 prod에 남고,
> 옛 방향과 새 방향이 순환을 이뤄 엣지 적재 전체가 거부됐다(실측 prod 2,234 · 잔존 221 · 순환 위험 5쌍).
> `python -m whymath_backend.l1.atom_graph.populate --retire-stale-edges plan|apply`가 그 행을 같은 트랜잭션에서
> 은퇴시킨다(범위·모드의 정본 `l1/atom_graph/atom_edge_retire.py` · 런북 `docs/ops/skb03_atom_node_populate_runbook.md` §9).
>
> **직전 상태(2026-10-20·KG-11)**: 서술형 973건을 **낱말 매칭**(`word_match_v1`)으로 재해소한 비-traversal 참고 원장
> `narrative_edge_reference_ledger_v1.json`(참고 엣지 651 · 스테이징 183 · 순환 충돌 43 분류·수리 경로) —
> `docs/data/narrative_edge_reference_v1.md`. 승격은 AI 2인 블라인드 검수 통과분만(§5).
>
> **직전 상태(2026-06-22)**: 통합 코퍼스 마스터 정본화 — graph.json 재생성(미적 원자ID 하이픈 채택·
> 대학 fill 재실행). 코퍼스(`data/corpus/atom_graph_v1/`)는 신규 파이프라인 `data_pipeline/atom_graph/`
> 산출(§6). (직전 상태 2026-06-21: Phase 0 데이터카드 작성.)
>
> **runtime truth source(2026-07-04·S0-4b/4c)**: 이 원자 백본이 런타임 진실 원천이다. 구
> 개념그래프(437·`concept_graph_dataset_v1.md`)는 `legacy_snapshot`으로 격하됐다(readonly·
> non_runtime·audit_only·물리 삭제 0). 런타임 조회(`/concepts/search`·L2 enrich)는 원자
> (`search_atoms`·`fetch_atom_node_meta`)를 읽고, 구 437은 크로스워크·curriculum populate·
> audit 전용이다. 거버넌스: `tests/backend/l1/test_legacy_snapshot_governance.py`.

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 사용자 업로드 **통합 코퍼스 마스터** xlsx(16 시트) — 파이프라인은 `원자_통합마스터`·`선수엣지_통합` 2시트만 정형화 |
| 업로드일 | **2026-10-19 통합마스터 v3 채택**(KG-09 재생성 · 직전 2026-06-22 정본 마스터 대체) |
| 원본 sha256 | `648cf9f7091d9d65…` 정본 xlsx(`_provenance.json` `source_sha256` 전문) — 파이프라인 입력은 from_유형만 치환한 사본(`pipeline_input` 블록·사유 기재) |
| 직전 소스 | `83a0d288…`(1,763,395 bytes, 2026-06-22 정본 마스터) · 그 직전 `759f163a…`(2026-06-21, 미적 원자ID raw) |
| 저작 | 와이매스 자체작성(교수학 주석·원자화·대학 신규축) + 공공 표준 *코드* 참조(NCIC) |
| 산출 코퍼스(Phase 1) | `data/corpus/atom_graph_v1/graph.json` + `_provenance.json` |

> 원본 xlsx는 **커밋하지 않는다**(§3 redaction 대상 자유텍스트 포함 — NCIC 본문·핵심명제·정식정의).
> 진실 원천은 redaction을 적용한 코퍼스(graph.json)다. 재추출 시 동일 sha256 원본을 사용자에게 재요청한다.

### 표기 정비 이력(전수 검증 완료)
- 비표준 사이시옷 점검: **초기값→초깃값 15곳은 원본에서 수정 완료**. **자리값→자릿값 13 · 경계값→
  경곗값 4(총 17)는 Phase 1 transform 사이시옷 정규화로 흡수**(회색지대 고유값 등은 유지·결정론).
- 코드 정합(정본 마스터 반영): **미적Ⅰ/Ⅱ 원자ID·연결성취기준이 마스터에서 하이픈으로 통일**
  (`12미적Ⅰ-01-01-1`·`[12미적Ⅰ-01-01]`) — 직전 소스는 원자ID raw(`12미적Ⅰ01-01-1`)였으나 공수·기수와
  내부 불일치라 마스터가 교정. transform의 연결성취기준 하이픈 정규화는 이제 무연산(소스 사전정규화,
  provenance `미적하이픈` 토큰 0·`_distinct` 43 유지). **129 원자ID만 하이픈으로 변경**, 노드/엣지/
  redaction 카운트는 직전과 동일. 코퍼스 `standards_v1` 무수정·전 연결성취기준 조인 OK.

---

## 2. 스키마 (시트 → 코퍼스)

### 2.1 원자_통합마스터 (1,837행 · 31열 — 원본 xlsx, 생성 당시)
순번 · 출처 · 교육과정 · 학교급 · 학년/학년군 · 영역/과목 · **단원** · **소단원** · **소단원코드** ·
**원자ID** · 원자명 · 원자명_표시 · **인지축**(개념/절차/표상) · **노드유형**(선행/구성/결과) ·
**오개념유형**(6종) · **난이도**(1~5) · **연결성취기준** · *핵심명제/성취기준내용* · ①오개념 ·
②진단문항 · ②정답·통과기준 · ②미통과·오답신호 · ③소크라테스질문 · ④전이 · ④전이예시 ·
선수원자 · 원자성a · 원자성b · 원자성c · 원자성d · 비고

### 2.2 선수엣지_통합 (3,220행 · 11열 — 원본 xlsx, 생성 당시)
출처 · **관계유형**(원본/소단원내/소단원간/학년간/학교급간(추정)/참고[서술형]) · **from(선수)** ·
from_원자명 · from_학교급 · from_유형(원자ID/서술형) · 관계(선수) · **to(후행)** · to_원자명 ·
to_학교급 · 학교급연계

### 2.3 계층 노드화(결정 ⑤)
`단원`·`소단원`·`소단원코드` 컬럼을 **독립 concept 노드로 dedup 승격** — 3단 계층
(개념=단원 / 소개념=소단원 / 원자=세부개념), 기존 `Concept.level` enum + `parent_concept_id` 재사용.
원자.parent=소단원·소단원.parent=단원. 소단원코드 예: `초수연-U1-S1`·`공수1-U1-S1`·대학 `CALC1-U1-S1`.

### 2.4 파생 필드 — `behavior_skills`(SKB-02 corpus 병합)
원자_통합마스터 xlsx에 없던 필드. 구 437 코퍼스(`concept_graph_v1/concepts.jsonl`, #419 저작)의
concept→skill 매핑을 크로스워크(`concept_atom_crosswalk_v1/crosswalk.jsonl`) 경유로 전파해
**후처리 병합**한다(원본 xlsx 휘발 → transform-v1 재실행 불가, U2와 동형 제약). 전파 규칙 =
`whymath_backend.l1.concept_atom_crosswalk.transfer`(S0-2)와 동일 의미론(crosswalk 행의
atom_codes 전체에 union+dedup+사전순 — primary 아님). **원자에만 채움**(단원/소단원·비크로스워크
원자는 `[]`). 병합기 = `data_pipeline/atom_graph/behavior_skills_merge.py` ·
CLI `python -m data_pipeline.atom_graph merge-behavior-skills`. 재실행 결과는 `_provenance.json`의
`behavior_skills_merge` 블록 참조.

---

## 3. 라이선스·안전 (CLAUDE.md 우선순위 #2)

자체작성 교수학 주석(4요소·원자성·은유 등)과 공공 표준 *코드*(NCIC 성취기준 코드)는 **안전**
(자체 코퍼스 + 사실정보). 단, 다음 자유텍스트는 NCIC 성취기준 *본문* 을 근접 복제할 수 있어
— 기존 정책(`concept_graph.md` §1.1 "본문은 어느 필드에도 복제하지 않는다") — **코퍼스에서 redact**:

| redact 필드 | 사유 |
|---|---|
| `핵심명제/성취기준내용`(K-12 원자) | NCIC 성취기준 *본문(statement)* 근접/직접 복제. 본문은 `standards_v1` 코퍼스(공공누리 1유형)에만 두고, 원자는 **연결성취기준 코드로 다리**만 놓는다 |

> **대학 원자(<!-- fact:atom_graph.university_atoms -->512<!-- /fact -->)는 연결성취기준이 '없음'** → 해당 `핵심명제`는 *자체작성*이므로 보존(redact 아님).
> 4요소(①~④)·④전이예시·원자성은 자체/AI 작성 → 보존. redaction 마커는 각 레코드 `_redacted_fields`.

신규 콘텐츠 4종(결정 ⑥ — 은유·정식정의·허용표현·암기카드)은 **개념/소개념 레벨·자체/AI 원창작**으로
Phase 3에서 저작한다. 특히 **정식정의(formal_definition)는 교과서 정의 미복제·자체창작 한정**(기존
코퍼스가 저작권으로 redact했던 필드 — 자체창작에 한해 도입).

`licensing_safety.md`에 "와이매스 원자 백본 데이터셋 v1(자체작성)" 행으로 등록.

---

## 4. 검수 상태 (적재 전 게이트)

안내 시트 자기보고:
- **메타데이터 전 원자 완비**: 난이도(1~5)·오개념유형(6종)·노드유형·4요소.
- **신규 원자(연녹색)와 그 메타는 AI 추정 — 교육 전문 검토 권장**.
- 품질 재점검(2026-06-21): 구조·범주·코드·3축·**DAG 사이클 0** 통과(빈칸=대학 연결성취기준 513·
  '없음' 표기만). 선수원자↔선수엣지 일치화·원자명_표시 중복 해소 완료. 내용 표본 60개 전문 검수:
  정답(수학) 오류 0건·경미 이슈 4건 중 3건 수정·1건 정상확인.

> 본 데이터셋의 다수 메타가 **AI 추정**이므로, 적재 시 `review_status` 표식(자체 검수/AI 검수/검수필요)을
> 부여하고 학생 직접 노출은 검수 게이팅을 거친다(기존 concept_graph 규약 미러).

---

## 5. 통계 (2026-08-10 현행 실측 — dedup 병합 14건 반영)

| 축 | 분포 |
|---|---|
| 학교급 | 초등 <!-- fact:atom_graph.atoms_elementary -->382<!-- /fact --> · 중학 <!-- fact:atom_graph.atoms_middle -->180<!-- /fact --> · 고등 <!-- fact:atom_graph.atoms_high -->749<!-- /fact --> · 대학 <!-- fact:atom_graph.university_atoms -->512<!-- /fact --> = **<!-- fact:atom_graph.atoms -->1,823<!-- /fact -->** |
| 인지축 | 개념 796 · 절차 546 · 표상 481 |
| 노드유형 | 구성 1,546 · 결과 151 · 선행 126 |
| 난이도 | 1=44 · 2=175 · 3=413 · 4=591 · 5=600 |
| 선수엣지 | 원자ID <!-- fact:atom_graph.edges -->2,278<!-- /fact -->(백본 2,195 + 고→대 경계 24 + KG-12 승격 v2 59) + 서술형 <!-- fact:atom_graph.narrative_edges_raw -->973<!-- /fact --> = **<!-- fact:atom_graph.prerequisite_total -->3,251<!-- /fact -->** (KG-12 전 2,231 + 973 · KG-10 ② 경계 검수 전 2,234 + 973) |
| 계층 노드(승격) | 단원 **<!-- fact:atom_graph.units -->217<!-- /fact -->** · 소단원 **<!-- fact:atom_graph.subunits -->643<!-- /fact -->**(distinct 소단원코드) — 원자 <!-- fact:atom_graph.atoms -->1,823<!-- /fact -->의 부모. 코퍼스 총 노드 **<!-- fact:atom_graph.nodes -->2,683<!-- /fact -->** |

> 생성 당시(요약 시트 기준) 수치는 원자 1,837(고등 762·대학 513)·엣지 2,213·총 노드 2,697이었다 —
> 2026-07-28 dedup 병합 14건(`dedup_merges_v1.json`) 이후 위 표가 현행이다.
> 안내 시트의 "소단원코드 부여 1,324개"는 *코드를 부여받은 K-12 원자 수*(당시 382+180+762=1,324,
> 현행 <!-- fact:atom_graph.atoms_k12 -->1,311<!-- /fact -->)를 뜻하며, distinct 소단원코드는 **643**(단원 217)이다 — Phase 1 transform 실측.

무결성(읽기 전용 실측): 원자ID <!-- fact:atom_graph.atoms -->1,823<!-- /fact --> 유일·중복 0 · 원자ID 엣지 dangling 0 · DAG 사이클 0.

---

## 6. 마이그레이션·적재 (Phase 1~5 — 요약)

- **Phase 1**: 신규 파이프라인 `data_pipeline/atom_graph/`(extract→transform→validate→load,
  기존 `concept_graph/` 미러). transform이 계층 노드 승격 + 표기·미적 정규화 + 관계유형→`relation_subtype`
  매핑 + 서술형 엣지 분리를 결정론으로 수행. backend `concept`·`concept_edge` 적재.
- **Phase 2**: 파생 스토어(`concept_node`·pgvector `concept_embedding`·Neo4j) 재생성.
- **Phase 3**: 4요소 정식 소스 승격(오개념 카탈로그·진단문항·소크라테스·전이) + 콘텐츠 4종 신규 저작.
  - Slice 1(완): 콘텐츠 4종 → `concept_content`. Slice 2(완): ①오개념 → `misconception_catalog`
    (additive·`ATOM:` 네임스페이스). **Slice 3(완·2026-06-23)**: ②진단문항·③소크라테스 → 신규
    `atom_probe`(code PK·additive·마이그레이션 `b9c0d1e2f3a4`·적재 당시 1,837행[dedup 후 현행
    코퍼스는 1,823]·상세 `atom_probe_v1.md`).
    잔여: ④전이 승격.
- **Phase 4**: 문제 corpus 크로스워크(소단원/단원 매칭 + 성취기준 코드 2중 다리).
- **Phase 5**: 구 `concept_graph_v1` 폐기·전 계층 검증.

상세 로드맵·결정(locked ①~⑥)은 마이그레이션 플랜 및 `MEMORY.md` 결정 로그 참조.

---

## 7. Neo4j 적재 스키마 (Phase 2c — `atom_graph/load.py`)

`graph.json`을 Neo4j에 **멱등 MERGE** 적재한다(`concept_graph/load.py` 미러 — 지연 import·
`NEO4J_*` env 접속·드라이버 주입·reltype enum allowlist). **additive 원칙**: 구 437 개념 그래프
(`:Concept`/`concept_id`/`:PREREQUISITE`)와 *노드·엣지 라벨 모두 충돌하지 않게* 별도 스키마를
쓴다(Phase 5 구 폐기 전까지 병존).

| 요소 | 구 개념 그래프 | 원자 백본(신·Phase 2c) |
|---|---|---|
| 노드 라벨 | `:Concept` | **`:Atom`** |
| MERGE 키 | `concept_id` | **`code`** (원자ID/소단원코드/단원코드) |
| 제약 | `concept_id_unique` | **`atom_code_unique`** (`REQUIRE a.code IS UNIQUE`) |
| 인덱스 | `concept_domain`·`concept_name_ko` | **`atom_school_level`**(a.school_level)·**`atom_level`**(a.level) |
| 관계 타입 | `:PREREQUISITE` | **`:ATOM_PREREQUISITE`** (reltype 토큰까지 완전 분리) |

### DDL·MERGE (멱등)
```cypher
CREATE CONSTRAINT atom_code_unique IF NOT EXISTS FOR (a:Atom) REQUIRE a.code IS UNIQUE;
CREATE INDEX atom_school_level IF NOT EXISTS FOR (a:Atom) ON (a.school_level);
CREATE INDEX atom_level IF NOT EXISTS FOR (a:Atom) ON (a.level);
MERGE (a:Atom {code: $code}) SET a += $props;            -- 노드 전량(원자+단원+소단원)
MATCH (src:Atom {code: $src}) MATCH (dst:Atom {code: $dst})
MERGE (src)-[r:ATOM_PREREQUISITE]->(dst) SET r += $props; -- 선수 엣지
```

### 적재 규칙
- **노드 <!-- fact:atom_graph.nodes -->2,683<!-- /fact -->**(원자 <!-- fact:atom_graph.atoms -->1,823<!-- /fact -->·단원 <!-- fact:atom_graph.units -->217<!-- /fact -->·소단원 <!-- fact:atom_graph.subunits -->643<!-- /fact -->)·**엣지 <!-- fact:atom_graph.edges -->2,278<!-- /fact -->**(이력: 원자ID prerequisite 전량 · 2,195 + S4-60 고→대 24 + KG-12 승격 v2 59 · KG-10 ② 경계 검수로 2,234→2,231 · KG-12 ① 체인 수리로 2,219 · ③ 승격으로 2,278)·skip 0.
  (Phase 2c 적재 당시 실측은 2,697/2,213 — dedup 병합 14건 이후 현행 코퍼스 기준으로 정정.)
- 엣지 속성: `relation_subtype`(소단원내/원본/소단원간/수정추가/참고(서술형)→정규화/학교급간(추정)/학년간/소단원내(보완) — 8종)·`school_link`·
  `strength`·`evidence`·`from_name`·`to_name`. `from_code`/`to_code`/`relation`은 MATCH/reltype에 쓰고
  속성으론 넣지 않는다.
- `atomicity`(a~d dict)는 **Neo4j map 속성 불가** → 결정론 JSON 문자열로 직렬화(구조 진실 원천은
  graph.json·Postgres `atom_node`). `None`·빈 dict 속성은 생략(Neo4j null 미저장).
- `parent_code`(3단 계층)는 **노드 속성**으로만 보존 — 별도 계층 관계는 만들지 않는다(Phase 3+).
  `narrative_edges_raw`(서술형 973 · KG-09 전 1,007)는 FK 불가라 **적재 대상 아님**(패스스루 보존 · 해소 제안은
  `narrative_edge_resolution_proposal_v1.json`, KG-10).
- **redaction 불변**: AtomConcept에 K-12 핵심명제 본문 슬롯이 없어 dump에 미포함 → 구조적 차단.
  접속 자격은 `NEO4J_URI`·`NEO4J_USER`·`NEO4J_PASSWORD` env 전용(시크릿 하드코딩 금지).

### CLI·검증
```bash
python -m data_pipeline.atom_graph load --graph data/corpus/atom_graph_v1/graph.json
```
단위(Fake 드라이버·실 코퍼스 현행 <!-- fact:atom_graph.nodes -->2,683<!-- /fact -->/<!-- fact:atom_graph.edges -->2,278<!-- /fact -->/skip 0 — 작성 당시 2,697/2,213)·통합(`@integration`·`neo4j` importorskip·실
neo4j:5에서 멱등 재적재 불변·code 집합 격리 정리). CI 전용 `data-pipeline-neo4j` 잡이 실 적재 검증.
