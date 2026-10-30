# 와이매스 성취기준 듀얼마스터 v1 — 데이터 카드

> **요약**: 한국 수학과 교육과정 **2022·2015 개정 듀얼** 성취기준 **<!-- fact:standards.k12 -->895<!-- /fact -->건**(2022:<!-- fact:standards.k12_2022 -->435<!-- /fact --> + 2015:<!-- fact:standards.k12_2015 -->460<!-- /fact -->)과
> **개념↔성취기준 연결 443건**(연결구분 직접/재매핑/준용)을 *적재 가능한 1급 자산*으로 만든 슬라이스(P1).
> 출처는 `concept_graph_dataset_v1`과 동일한 **File A 통합 마스터 xlsx**(개념그래프 부분은 2026-06-12에 이미
> 적재). 본 카드는 그 *성취기준·연결 레이어*를 다룬다. 설계 배경은
> `curriculum_master_v2_integration_review.md`(2026-06-16) 참조.
>
> **현황(2026-06-20)**: 코퍼스 **생성·커밋 완료**. `whymath-ncic extract`로 실 File A에서 성취기준 895·
> 연결 443을 추출·검증(errors 0)·저장해 `data/corpus/standards_v1/`에 커밋(`standards.json`·
> `concept_standard_links.json`·`_provenance.json`). 백엔드 ORM 적재는 후속 슬라이스(§6).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 사용자 업로드 xlsx(통합 마스터 13시트 중 성취기준·연결 시트) |
| 원본 sha256 | `062695cef261386ec880313631aa349f624fcace1b7eb3d52bc031025536f90d` (File A·`concept_graph_dataset_v1`과 동일 원본) |
| 출처(성취기준) | 교육부 고시 [수학과 교육과정] — 2022 개정(제2022-33호)·2015 개정(제2015-74호), 국가교육과정정보센터(NCIC, https://www.ncic.go.kr) |
| 저작(연결) | 와이매스 자체작성(개념↔성취기준 교수학 매핑) |
| 추출 산출물 | `data/corpus/standards_v1/{standards.json, concept_standard_links.json, _provenance.json}` (**커밋됨** — `whymath-ncic extract`, 2026-06-20) |

> 원본 xlsx는 **커밋하지 않는다**. 진실 원천은 추출 jsonl이다. 재추출이 필요하면 동일 sha256 원본을
> 사용자에게 재요청한다(`extract_file_a`).

---

## 2. 스키마 (시트 → 모델/jsonl)

| 시트(File A) | 레코드 | 모델 | 핵심 필드 |
|---|---|---|---|
| `성취기준_목록` | 895 | `AchievementStandard` | **`norm_id`**(정규화 PK), `code`(official_code·비유일), `curriculum_revision`(2022/2015 개정), `grade_band`, `school_type`, `subject`, `domain`, `sub_domain`, `statement`, `commentary`, `big_idea`, `parent_codes[]`, `source_url` |
| `개념-성취기준-CCSS` | 437행→443 | `ConceptStandardLink` | `concept_src_id`(개념 안정키 N1·HK42…), `norm_id`(성취기준 참조), `link_type`(직접/재매핑/준용), `note`(괄호 접미사 보존). 다중코드 셀 4건 분할로 437행→443 링크 |
| `공식_성취기준_마스터` | 435(2022) | (교차검증) | `official_code`+`norm_id` 2층키 — 파생 norm_id 검산용 |

### `norm_id` — 교육과정 간 유일 정규화키

원본 `code`(예 `[9수01-01]`) 단독은 2022·2015 두 교육과정에서 **동일 문자열로 153건 충돌** → `code` 단독
PK 불가. 따라서 PK를 `norm_id`로 옮긴다.

```
norm_id = build_norm_id(curriculum_revision, official_code)
        = <개정연도>_<학년+과목토큰>_<영역2자리>_<순번2자리>
예: ("2022 개정","[2수01-01]")   → 2022_2수_01_01
    ("2022 개정","[10공수1-01-01]") → 2022_10공수1_01_01
    ("2015 개정","[12미적Ⅰ01-03]")  → 2015_12미적I_01_03   (로마숫자 Ⅰ→ASCII I 정규화)
```

**결정적(deterministic)** — File A 공식마스터(435·2022 전용)에 의존하지 않고 895 전건을 (개정, code)에서
생성하며, 153 충돌은 개정 접두로 해소한다. 공식마스터는 2022 subset 검산용으로만 쓴다.

---

## 3. 라이선스·안전 (CLAUDE.md 우선순위 #2)

| 대상 | 분류 | 처리 |
|---|---|---|
| 성취기준 `statement`(본문) | **교육부 고시 — 공공누리 제1유형**(출처 표시 시 자유 이용·상업 가능) | 보존(redact 안 함). 모든 출력에 `SOURCE_CITATION` 동봉 |
| `code`/`norm_id`/`domain` 등 구조 메타 | 공공·사실정보 | 보존 |
| 연결구분·`note`(개념↔성취기준 매핑) | 와이매스 자체작성 | 보존 |

> **`concept_graph_dataset_v1`과의 차이**: 그 카드는 `concepts.description`/`formal_definition`(저자가
> *근접 복제*했을 수 있는 자유텍스트)을 redact했다. 본 성취기준 `statement`는 그와 달리 **공개 고시 본문
> 자체**(공공누리 1유형)이므로 redaction 대상이 아니다 — 기존 `ncic` 모듈의 statement 취급과 동일.
> 단 File A 도착 시, 어떤 statement가 *교과서 표현 paraphrase*(출판사 저작물 가능)인지 표본 검수한다
> (CLAUDE.md "교과서 학습목표 텍스트 인용은 변호사 검토 전제").

---

## 4. 가공·검증 (data-pipeline `ncic`)

1. **추출** `extract_xlsx.extract_file_a(path)` — 시트→행 dict→순수 파서(`parse_standard_row`·`parse_link_row`,
   기존 `transform` 재사용)→`(standards, links)`. openpyxl은 `[xlsx]` extra·지연 import.
2. **검증** `validate_standards`·`validate_links` 불변식:
   - `norm_id_unique` (PK 유일)
   - `official_code_curriculum_unique` — `(revision, code)` 유일·*교육과정 간 동일 code 공존 허용*
   - `curriculum_split` — 개정별 건수 집계(INFO; 기대 2022:435 / 2015:460)
   - `link_type_enum`(직접/재매핑/준용)·`link_norm_id_resolves`·`link_concept_resolves`(고아 0)
3. **저장** `write_json`·`write_links_json` — Collection JSON(출처·라이선스 표지 포함) + `_provenance.json`.

합성 fixture(official_code 충돌쌍 포함)로 위 불변식·충돌 해소를 단위 검증한다(`tests/data_pipeline/ncic/`).

---

## 5. 백엔드 적재 (L1 코어)

- ORM `achievement_standard`(PK `norm_id`·`official_code` 비유일 인덱스·UNIQUE(`curriculum_revision`,
  `official_code`))·`concept_standard_link`(대리 PK·`concept_code` 느슨참조·`norm_id` FK·`link_type`·
  UNIQUE(`concept_code`,`norm_id`,`link_type`)) — `schema/standard.py` pydantic 동반.
- Alembic 마이그레이션 **`a6b7c8d9e0f1`**(단일 선형 head). 실 PG upgrade/downgrade 왕복은 CI `backend-migrations`.
- corpus→ORM 로더(`l1/` — concept_graph `backend_concept`/`backend_edge` 패턴 미러): corpus `code`→ORM
  `official_code`, `concept_src_id`→`concept_code`(개념 identity 해소). 멱등 upsert.

---

## 6. 적재 절차 (코퍼스 생성 완료 — 2026-06-20)

```bash
# 1) File A xlsx로 추출·검증·저장(공공누리 1유형 표지 동봉) — 멱등 재현
whymath-ncic extract --xlsx <File A.xlsx> --output-dir data/corpus/standards_v1
#   → standards.json(895)·concept_standard_links.json(443)·_provenance.json(source_sha256)
# 2) 검증은 extract가 내장: validate_standards/validate_links errors=0 아니면 Exit 2
# 3) 백엔드 적재: alembic upgrade head 후 populate CLI(멱등·norm_id PK 충돌 upsert)
python -m whymath_backend.l1.standards.populate \
    --standards data/corpus/standards_v1/standards.json \
    --links data/corpus/standards_v1/concept_standard_links.json
#   링크 해석(concept_src_id→concept.source_id→code)은 l1.concept_graph.populate 선행 필요
#   (개념 미적재 시 전건 개념 orphan skip — 성취기준은 정상 적재).
```

산출물은 **Collection JSON**(`write_json`/`write_links_json` 재사용 — SOURCE_CITATION·LICENSE_NOTICE
표지·`standards`/`links` 배열)이며 **레포에 커밋**(`data/corpus/standards_v1/`). 원본 xlsx는 미커밋,
`_provenance.json`의 `source_sha256`(`4e21d6d4…`)으로 재현 가능성 보장.

**완료 기준(달성)**: 895(2022:435+2015:460)·`norm_id` 유일·`official_code` 중복 허용·연결 437행→443
링크 전건 `norm_id` 해소(고아 0)·연결구분(직접/재매핑/준용·괄호 접미사는 note 보존).

## 7. File A 정합 완료 (2026-06-20 — §6 미결 해소)

2026-06-20 도착 File A(sha256 `4e21d6d4…`·§1의 2026-06-12판 `062695…`의 후속 리비전)로 `extract_xlsx.py`
좌변 컬럼 매핑을 **정합 완료**. 실 추출 검증: **성취기준 895(2022:435+2015:460)·연결 437행→443 링크·
`validate_standards`/`validate_links` errors 0**. 위 §6 미결 항목 처리 결과:

- **연결 시트명·키 컬럼**: 실 시트는 `연결_개념-성취기준`이 아니라 **`개념-성취기준-CCSS`**(개념ID·
  한국 성취기준(2022)·연결구분). `_SHEET_LINKS`·`_LINK_COLS` 교체로 확정.
- **`NORM_ID_PATTERN`·`STANDARD_CODE_PATTERN`(2015 포함)**: **확장 불요** — 기존 패턴/`_SUBJECT_MAP`으로
  895 전건 통과. 단 File A `norm_id` 열은 **로마숫자 Ⅰ 유지**(ASCII 패턴 위반)라 매핑하지 않고
  `build_norm_id`(Ⅰ→I 정규화) 파생을 쓴다(229건 직접매핑 실패 원인 = 이 함정).
- **실데이터 특성 3종(연결)**: ① 교육과정 열 부재→revision 2022 기본, ② `연결구분` 괄호 접미사
  (`직접(기본수학)`)→베어 토큰 정규화·괄호는 `note` 보존, ③ code 셀 `;` 다중코드 4건→코드별 링크 분할
  (437행→443 링크). `parse_link_row`가 **행→복수 링크** 반환으로 처리.

> **후속(미커밋)**: 코퍼스 생성·커밋(`data/corpus/standards_v1/*.jsonl`)+`whymath-ncic extract` CLI는 별도
> 슬라이스. 본 정합은 추출 *기계장치*만 완성(실 추출은 로컬 검증·데이터 비커밋 — "기계장치 우선" 관례).

---

**버전**: v1 (기계장치·2026-06-20 정합) | **최종 수정**: 2026-06-20 | 관련: `ncic.md`·`ncic_scheme.md`·
`curriculum_master_v2_integration_review.md`·`concept_graph_dataset_v1.md`·`external_corpus_ingestion_v1.md`
