# 외부 큐레이션 코퍼스(v3·7파일) → L1 수집 설계 *확장* v1

> **L1 데이터 기반 설계 문서.** 2026-06-20 Kiki가 업로드한 **7파일**(성취기준 마스터·7계층 본문 JSON·
> 7주체 S1~S7 경로·문제뱅크 v3·마스터 명세서·색인 2종)을 *기존 코드베이스와 대조*하여 적재 청사진을
> 그린다. **본 문서는 `curriculum_master_v2_integration_review.md`(2026-06-16, File A·B v2·md v2)를
> *재서술하지 않고 참조·확장*한다** — concept_id 정본 포맷·성취기준 듀얼·norm_id·5축 메타 매핑은 그
> 문서 §3~§5가 이미 설계했다. 본 문서가 *새로 더하는 것*은 ① File A 실물 도착에 따른 **추출기 컬럼
> 정합 스펙**(achievement_standards_v1 §7의 미결 항목 해소)과 ② v2 검토가 **다루지 않은 신규 데이터셋
> 3종**(오개념 839·7주체 경로·7계층 본문)의 갭→마이그레이션이다.
>
> **현황(2026-06-20)**: *설계 전용*(코드·스키마·마이그레이션 0). 추출기 실제 수정·로더·마이그레이션은
> 승인 후 별도 슬라이스(아래 §6 Phase A~D). 근거 결정 로그: `MEMORY.md` 2026-06-20.

---

## 0. 입력 7파일 매니페스트 (검증된 실측)

| # | 파일(약칭) | sha256(앞 16) | 정체 | 적재 대상 |
|---|---|---|---|---|
| File A | 성취기준 마스터 xlsx(9시트) | `4e21d6d4424ca5f0` | 성취기준·개념그래프 통합 마스터(2022+2015) | ✅ 정본 |
| JSON | 7계층 본문 json(437개념·25MB) | `fcf6d333a419a222` | 개념별 L1_HOOK~L5_META 본문·**오개념 839**(원천 업로드 기준)·문항 | ✅ 신규 |
| Path | 7주체 경로 xlsx(8시트) | `f4ee650b734ac854` | 개념×페르소나 **S1~S7** 학습경로 | ✅ 신규 |
| Bank | 문제뱅크 v3 xlsx(17시트) | `2ec9beccb589a391` | 개념노드 440·**5축 메타스키마**·배분 매트릭스 | 설계(문항은 후속) |
| Idx1 | 7주체 색인 xlsx | — | 페르소나별 소단원 색인 | 보조 |
| Idx2 | 통합색인 xlsx | — | 개념별 audit 카운트 | 보조(교차검증) |
| md | 마스터 명세 md(642줄) | — | 5계층↔5축·ERD·컴플라이언스 | 정합 근거(적재 X) |

> 원본 파일은 **커밋하지 않는다**(achievement_standards_v1 관례). 진실 원천은 추출 산출물.

### 0.1 검증된 카운트 (적재·검증 invariant의 정본)

| 데이터셋 | 실측(File A/JSON/Path/Bank) | v2 검토·기존 카드 표기 | 정합 메모 |
|---|---|---|---|
| 성취기준(2022+2015) | **895**(성취기준_목록 data rows) | 895 ✓ | 일치 |
| 개념 | **437** | 403(corpus v1)·437(JSON) | corpus v1은 부분·JSON 437이 전수 |
| 선수엣지 | **580**(선수엣지 data rows) | 541(corpus v1)·581(plan) | **재집계 580 채택** |
| 개념↔성취기준 링크 | **437**(개념-성취기준-CCSS) | 443(achievement_standards_v1) | **재집계 437 채택**(시트명·행수 갱신) |
| 공식_성취기준_마스터(2022) | **438** | 435 | 검산용·헤더 제외 시 ~435 |
| 오개념 | **839**(unique mis_id) | — | **신규** |
| AIHub 문항(합) | **18,037** | — | 라이선스: AIHub 영리허용 |
| 자체문항 v3 | **4,030**(437개념×4범주) | 403(plan 오기) | 개념체크·대표예제·적용문제·심화문제 |
| 단위(개념/유형) | **592**(435 교육과정+101 재수유형+56 영재정리) | 592 ✓ | 일치 |
| 문항 규모 | MVP 2242·정식 5668·성숙 11215 | 동일 | 일치 |

> **정직 회계**: v2 검토·기존 카드의 541/443/435는 *이전 File A 리비전* 기준이었다. 본 문서가 **이번에
> 도착한 File A의 실측(580/437/438)을 정본으로 채택**하고, 적재 검증 invariant도 이 수치로 갱신한다.

---

## 1. 추출기 컬럼 정합 스펙 — `extract_xlsx.py` (Phase A 코드 슬라이스용)

`data_pipeline/ncic/extract_xlsx.py`의 `extract_file_a`는 **File A 도착을 기다리던 추출기**다(도크스트링:
"도착 시 좌변 컬럼 매핑만 조정하면 파서·검증·테스트 본체 재사용"). 도착한 File A의 실제 컬럼이 placeholder와
불일치하므로 아래대로 **좌변만** 교체한다. `achievement_standards_v1.md` §7(미결 항목)을 이 절이 해소한다.

### 1.1 `성취기준_목록`(895행) — `_SHEET_STANDARDS`·`_STD_COLS`

실제 헤더: `키 · 교육과정 · 학교급 · 구분 · 학년군·과목 · 영역(단원) · 소단원(개념) · 성취기준 코드 ·
성취기준 내용 · 성취기준 요약(간결) · 개념ID · 개념명(개념그래프) · 매칭 CCSS · 개정 · 과목약칭 · 영역 ·
일련 · norm_id`

| RawStandardRecord 키 | 현재 placeholder | **실제 File A 컬럼** | 조치 |
|---|---|---|---|
| (시트) `_SHEET_STANDARDS` | `성취기준_목록` | `성취기준_목록` | 일치 ✓ |
| `code` | `코드` | **`성취기준 코드`** | 좌변 교체 |
| `curriculum_revision` | `교육과정` | `교육과정` | 일치 ✓ |
| `subject` | `과목` | **`과목약칭`** | 좌변 교체 |
| `domain` | `영역` | **`영역(단원)`** | 좌변 교체 |
| `sub_domain` | `세부영역` | **`소단원(개념)`** | 좌변 교체 |
| `statement` | `성취기준` | **`성취기준 내용`** | 좌변 교체 |
| `commentary`/`big_idea`/`source_*` | (동명) | File A에 직접 열 없음 | 미존재 → transform 기본값(유지) |
| (norm_id) | 매핑 안 함(파생) | **`norm_id` 열 존재** | 파생값과 **교차검증**(불일치 0 기대)·파생 유지 권장 |

> 추가 가용 열(현재 미매핑·후속 활용): `학년군·과목`(grade_band 보강)·`개념ID`(개념 직접 링크 캐시)·
> `매칭 CCSS`(curriculum_entry 흡수)·`성취기준 요약(간결)`(요약 필드).

### 1.2 링크 시트 — `_SHEET_LINKS`·`_LINK_COLS` **(시트명·구조 모두 변경)**

⚠️ placeholder `연결_개념-성취기준` 시트는 **존재하지 않는다**. 실제 링크는 **`개념-성취기준-CCSS`(437행)**.
실제 헤더: `개념ID · 개념명 · 한국 성취기준(2022) · 미국 CCSS · 한국 성취기준(원본·2015) · 연결구분`

| 내부 키 | 현재 placeholder | **실제 컬럼** | 조치 |
|---|---|---|---|
| (시트) `_SHEET_LINKS` | `연결_개념-성취기준` | **`개념-성취기준-CCSS`** | 시트명 교체 |
| `concept_src_id` | `개념ID` | `개념ID` | 일치 ✓ |
| `code` | `코드` | **`한국 성취기준(2022)`** | 좌변 교체 |
| `link_type` | `연결구분` | `연결구분` | 일치 ✓ |
| `curriculum_revision` | `교육과정` | **열 없음 → 2022 고정** | 링크는 2022 기준·norm_id는 (2022, code) 파생 |
| `norm_id` | `norm_id` | **열 없음** | 파생 경로 사용(이미 fallback 구현) |
| (참고) CCSS·원본2015 | — | `미국 CCSS`·`한국 성취기준(원본·2015)` | curriculum_entry/원본추적 후속 흡수 |

> `parse_link_row`는 이미 "norm_id 없으면 (교육과정, 코드)로 파생" 분기를 갖는다. 링크 시트에 `교육과정`
> 열이 없으므로 **링크 추출 시 revision='2022 개정' 상수 주입**(또는 시트 단위 기본값)이 1줄 보강으로 필요.

### 1.3 정합 후 검증(코드 슬라이스에서)
- `extract_file_a` 1회 실행 → standards 895·links 437 산출(누락 0·`ExtractError` 0).
- `norm_id` 열 직접값 vs `build_norm_id(2022/2015, code)` 파생값 **전건 일치**(불일치는 로그·정정).
- 기존 합성 fixture 단위 테스트의 컬럼명을 실 컬럼명으로 갱신(`tests/data_pipeline/ncic/`).

---

## 2. 신규 데이터셋 ① — 오개념 카탈로그 839 (원천 업로드 기준 · 최대 갭)

**현황 갭**: `l4/misconception/catalog.py`는 *Python 코드 상수*(kebab-case id ~30종·DB 비영속). JSON의
**839 오개념**을 받을 1급 저장소가 없다. v2 검토 §5-5는 "형식화"만 언급하고 테이블을 설계하지 않았다.

**소스 구조**(JSON 오개념 레코드 키): `mis_id`(예 `M0425`) · `출처` · `학교급` · `2022_영역` · `원본_영역` ·
`세부단원_개념` · `개념ID` · `성취기준코드` · `매칭_CCSS`(예 `1.NBT.A.1`) · `오개념`(서술) · `학생의_잘못된_사고` ·
`distractor_규칙` · `error_type` · `난이도` · `교정포인트` · `매핑신뢰도` · `매핑점수` · `매핑개념명_참조` ·
`생성·검수` · `코드정밀도`.

**갭→마이그레이션(Phase B)**: `misconception` 테이블 신설 — PK `mis_id`, `name`/`canonical_statement`(오개념)·
`student_wrong_thinking`·`distractor_rule`·`error_type`(enum 후보)·`difficulty`·`correction_point`(교정포인트)·
`mapping_confidence`. **링크 2종**: `misconception_concept_link`(`mis_id`↔`concept_code`)·
`misconception_standard_link`(`mis_id`↔`norm_id`)·CCSS는 `ccss_code` 필드. **기존 kebab 카탈로그 정합**:
`l4/misconception/catalog.py`의 30종에 `mis_id` 별칭(또는 매핑표) 부여 → `distractor_map`(5축)이 참조할 안정키.

---

## 3. 신규 데이터셋 ② — 7주체 S1~S7 학습경로

**현황 갭**: 개념×페르소나 학습경로를 둘 store가 없다(`StudentProfile`은 YAML 명세뿐·ORM 없음).

**소스 구조**(Path xlsx): `전체요약`(677행: 주체·과목·단원·소단원·concept_id·성취기준·이론틀·S4 시드문항수·
대상특화) + 트랙 7시트(초119·중60·고기본34·고일반93·고진로127·재수130·영재114), 각 행 = 한 소단원의
**S1 진단게이트 / S2 개념형성 / S3 유도연습 / S4 적응숙련(오개념·시드) / S5 숙달게이트 / S6 확장전이 /
S7 간격복습** 7단계 설계. 이론틀=EIS(Bruner 표상).

**갭→마이그레이션(Phase C)**: `learning_path` store(`concept_code`×`persona`·S1~S7 JSONB 또는 단계 7열)·
`이론틀`·`S4_시드문항수`·`대상특화`. **L2/L4 연결**: S1 진단임계·S5 숙달임계는 L2 mastery 게이트가 소비(설계
정합), S2~S4·S6은 L4 교수학 경로. 페르소나는 `schema/enums.py Persona`(A~E)와 트랙(초·중·고3트랙·재수·영재)을
**직교 축**으로 매핑(v2 §5-6: 혼동 금지).

---

## 4. 신규 데이터셋 ③ — 7계층 본문(L1_HOOK~L5_META)

**현황 갭**: `concept_node`는 `description`/`formal_definition`을 redaction(근접복제 회피)했다. **자체 저작
본문**(도입·은유·암기카드·깊이본문)은 적재 가능하나 전용 콘텐츠 테이블이 없다.

**소스 구조**(JSON 개념별): `L1_HOOK`(도입·은유) · `L2_CONCEPT`(핵심개념정리·학습목표·암기카드·깊이본문_gemini) ·
`L3_VISUAL`(spec·status — 전부 미구축) · `L4_PRACTICE`(자체문항_output_v3{개념체크·대표예제·적용문제·심화문제}·
AIHub문항수·AIHub문항·함정포인트) · `L5_META`(S1_진입임계·S4_시드문항·S5_출구·S7_간격복습·오개념).

**갭→마이그레이션(Phase C)**: `concept_content` 테이블(`concept_code`·layer별 JSONB) — 자체 저작이라 redaction
불요. `L3_VISUAL.status=미구축`이므로 시각화 spec은 후속(05 선언적 명세 연계). `L4_PRACTICE`의 자체문항·AIHub
문항은 **문제뱅크(Phase D)**로 분리 적재(본 콘텐츠 store는 본문만).

---

## 5. 문제뱅크 v3 — 5축 메타스키마 (v2 §5-4 갱신)

Bank `5축_메타스키마`(17필드) 실측 — v2 §5-4 매핑표를 **확정**한다:

| 축 | 필드 | 타입 | 기존 problem.py 정합 |
|---|---|---|---|
| 공통 | `item_id`·`concept_id`(FK)·`achievement_std` | string/FK | FK를 ELEM-GEO 키 공간 정렬 |
| 계층 | `bloom_level`(6)·`difficulty`(1-5)·`irt_b`·`irt_a` | enum/int/float | bloom·irt_a **신규**, difficulty·irt_b 매핑 |
| 성격 | `item_type`(MC/MC-D/SA/FB/MN/GR/ST/PF/EX/RT)·`distractor_map`(c1:M-LIN-01) | enum/json | item_type 확대·distractor_map→§2 오개념 카탈로그 |
| 내용 | `subject`·`domain`·`subunit` | string | subunit **신규** |
| 양적 | `target_seconds`·`session_position` | int | session_position **신규** |
| 질적 | `scoring_type`(정오답/진단/부분점수/시간/루브릭)·`feedback_id`·`discrimination_D` | enum/FK/float | 전부 **신규** |

문항 적재(자체 4,030·AIHub 18,037·distractor↔오개념)는 **Phase D**(대규모·인월 36.7 산정은 설계만).

> Phase D와 별개로 **자체생성 v0 코퍼스 6종 2,667문이 기실재**한다(2026-07 콘텐츠 공장 S2 산출).
> 현황·격차·설계 정본: `../architecture/problem_bank_gap_review.md` §0·§3.

---

## 6. 적재 로드맵 (v2 §7.1 단계에 정렬·의존 순서)

| Phase | 내용 | 재사용 자산 | 위험 |
|---|---|---|---|
| **A** | 추출기 컬럼 정합(§1) + 성취기준 895·개념 437·선수엣지 580 적재(원천 업로드 기준) | `extract_file_a`·`standard_loader`·`concept_graph/populate`(멱등) | 저(검증완료 데이터·공공누리) |
| **B** | 오개념 839(원천 업로드 기준) DB 승격(§2·마이그레이션 1)·개념/성취기준 링크·kebab 카탈로그 정합 | `l4/misconception/catalog.py` 매핑 | 중(신규 테이블·기존 상수 정합) |
| **C** | 7계층 본문(§4)+7주체 경로(§3) store | — | 중(신규 store 2·자체저작이라 라이선스 안전) |
| **D** | 문제뱅크 5축 문항 적재(§5·자체 4,030·AIHub 18,037) | `schema/problem.py`(난이도 5축·persona_fit 유지) | 대(대규모·후속) |

> Phase A는 v2 §7.1 P1(성취기준)+P2(concept 재ID)에 대응. B/C/D는 v2가 *로드맵*으로만 둔 것을 본 데이터셋
> 도착으로 **구체화**한 것.

---

## 7. 검증 방법 (적재 슬라이스에서)
- **카운트 invariant**(§0.1 정본 · 2026-06-20 원천 업로드 기준 — 현재 건수는 `docs/data/corpus_facts.md`): 성취기준 895(2022:435+2015:460)·개념 437·선수엣지 580(DAG 비순환)·
  링크 437·오개념 839(mis_id 유일)·단위 592·문항(자체 4,030·AIHub 18,037).
- **ID 정규화 커버리지**: 모든 파일의 concept_id(레거시 N1·HK42·canonical MID-LINFUNC-002)가 `concept.code`로
  1:1 또는 명시적 다대일 매핑(고아 0·`idmap.py` 재사용·v2 §5-1).
- **추출기 정합**(§1): `extract_file_a` 산출 895/437·norm_id 직접값↔파생값 전건 일치.
- **링크 해소**: 437 링크 전건이 norm_id·concept_code 해소(고아 0)·연결구분 분포(직접/재매핑/준용).
- **라이선스**: 4출처(AIHub·자체저작·공공 성취기준 코드·CCSS) 전부 `licensing_safety.md` 등재(아래 §8).

---

## 8. 라이선스 (CLAUDE.md 우선순위 #2)

| 데이터셋 | 출처/저작 | 분류 | 처리 |
|---|---|---|---|
| 성취기준 본문·코드 | 교육부 고시(NCIC) | 공공누리 1유형 | 보존·`SOURCE_CITATION`(achievement_standards_v1과 동일) |
| AIHub 문항 18,037 | AIHub 수학 데이터셋 | 영리 허용 | 보존·출처표시(licensing_safety 기존 행) |
| 오개념 839(원천 업로드 기준)·7계층 본문·7주체 경로·자체문항 4,030 | **와이매스 자체 저작** | 자체 저작 | 보존·redaction 불요 |
| CCSS 코드(`1.NBT.A.1`) | CCSSO/NGA | 조건부(코드·구조) | 코드/매핑만(본문 X) |

→ `licensing_safety.md` 한국 자원 표에 "와이매스 외부 큐레이션 코퍼스 v3" 행 추가(§ 아래 갱신).

---

## 부록 — 출처·프로비넌스
- 입력: 2026-06-20 Kiki 업로드 7파일(sha256 §0). 적재 산출물은 추출 시 `data/corpus/`에 생성(원본 미커밋).
- 선행 설계: `curriculum_master_v2_integration_review.md`(2026-06-16)·데이터카드
  `achievement_standards_v1.md`·`concept_graph_dataset_v1.md`.
- 결정 로그: `MEMORY.md` 2026-06-20 "외부 코퍼스 v3 수집 설계(확장)".

---

**버전**: v1 (설계 전용) | **최종 수정**: 2026-06-20 | 관련: `curriculum_master_v2_integration_review.md`·
`achievement_standards_v1.md`·`misconception_catalog_v1.md`·`concept_content_corpus_v1.md`·`licensing_safety.md`
