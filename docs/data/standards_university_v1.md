# 와이매스 대학 성취기준 v1 — 데이터 카드

> **요약**: 대학 수학 **성취기준 <!-- fact:standards.university -->409<!-- /fact -->건**(<!-- fact:standards.university_subjects -->32<!-- /fact -->과목·148단원·409소단원)과 **소단원↔성취기준 연결
> <!-- fact:standards.university_links -->409<!-- /fact -->건**(1:1·link_type='직접')을 *적재 가능한 1급 자산*으로 만든 슬라이스(원자 백본 마이그레이션
> U1). 출처는 사용자 업로드 **"수학과 성취기준 통합 마스터"** xlsx의 `성취기준_목록` 대학 행이며,
> **본문은 와이매스 자체작성**(원자노드DB 핵심명제 종합·AI 추정·검수필요)이다 — NCIC 공공누리
> 자료가 아니므로 redaction 불요(K-12 NCIC 본문과 라이선스·취급 분리).
>
> **현황(2026-06-22)**: 코퍼스 **생성·커밋 완료**. `python -m data_pipeline.standards_university`로
> 실 xlsx에서 대학 성취기준 409·링크 409를 추출·검증(errors 0)·저장해
> `data/corpus/standards_university_v1/`에 커밋. 백엔드 ORM 적재는 후속 슬라이스(U3).

---

## 1. 출처·프로비넌스

| 항목 | 값 |
|---|---|
| 형태 | 사용자 업로드 xlsx(통합 마스터 11시트 중 `성취기준_목록`의 `학교급=='대학교'` 행) |
| 원본 sha256 | `74000919f32c9d8d4b5c6026c36781a4856976112e23c798b99348f222c0a8b1` |
| 출처(본문) | **와이매스 자체작성** — 대학 성취기준 본문은 원자노드DB 핵심명제를 종합한 AI 추정 초안(검수필요) |
| 코드 출처 | 대학 단원/소단원 코드(`CALC1-U1`·`CALC1-U1-S1` 등)는 *대학과정 단원소단원 코드참조* 재사용 — 새 코드 미생성 → **원자노드DB 조인 보존** |
| 추출 산출물 | `data/corpus/standards_university_v1/{standards.json, concept_standard_links.json, _provenance.json}` (**커밋됨** — `data_pipeline.standards_university`, 2026-06-22) |

> 원본 xlsx는 **커밋하지 않는다**(K-12 NCIC 본문도 포함하므로). 진실 원천은 추출 json이며 재추출이
> 필요하면 동일 sha256 원본을 사용자에게 재요청한다. 본 파이프라인은 *대학 행만* 읽는다(K-12 NCIC
> 본문 비추출 — 라이선스 분리·구조적 차단).

---

## 2. 스키마 (시트 → 모델/json)

| 시트 | 레코드 | 모델 | 핵심 필드 |
|---|---|---|---|
| `성취기준_목록`(대학) | 409 | `UniversityStandard` | **`norm_id`**(`대학_<과목>_<2자리>_<2자리>`·PK), `code`(`[CALC1-01-01]`·로더가 official_code로 rename), `curriculum_revision`='대학', `grade_band`/`school_type`='대학교', `subject`(학년군·과목), `domain`(영역/단원), `sub_domain`(소단원), `statement`(본문·자체작성), `commentary`(요약) |
| `성취기준_목록`(대학) | 409 | `UniversityConceptStandardLink` | `concept_src_id`(소단원 코드 `CALC1-U1-S1`), `norm_id`(성취기준 참조), `link_type`='직접'(소단원↔성취기준 1:1) |

backend `l1/standards/standard_loader.py`가 읽는 Collection 포맷(`standards`/`links` 배열)과 키 정합.
로더의 rename seam: 코퍼스 `code`→backend `official_code`, `concept_src_id`→`concept_code`(`{source_id:
code}` 맵 해석). backend `schema/standard.py`는 분류 필드를 전부 `str`로 두어(닫힌 enum 강제 없음)
대학 값(`대학교`·`갈루아 이론`·`[GALOIS-01-01]`)을 그대로 받는다.

---

## 3. 통계 (실 코퍼스 검증)

| 항목 | 값 |
|---|---|
| 성취기준 | 409 (norm_id·code 각각 유일) |
| 소단원 링크 | 409 (소단원↔성취기준 **1:1**·멀티값 0) |
| 과목 | 32 (AALG1·CALC1·GALOIS·TOPO1 … RANAL) |
| 단원/소단원 | 148 / 409 (코드참조 재사용) |
| 본문 빈값 | 0 |
| 코드 형식 | `[A-Z]+[0-9]*-NN-NN` 전수 통과 (미적 하이픈 사태 방지) |

검증 게이트(`validate_standards`): norm_id_unique·code_unique·subunit_unique·link_referential·
link_count(1:1)·revision_university = **error 0**.

---

## 4. 라이선스·취급 (CLAUDE.md 우선순위 #2)

- **자체작성**: 대학 성취기준 본문·요약은 와이매스 자체 저작물 → **redaction 불요**. K-12 NCIC
  성취기준 본문(공공누리 1유형·`standards_v1`)과 *출처·취급이 다르다*(파이프라인·코퍼스 분리).
- **검수필요**: 본문은 AI 추정 초안(원자노드DB 핵심명제 종합)이다 — 수학 전문가 도메인 검수 권장
  (검수보고: 구조·형식 즉시 사용 가능·본문 도메인 정확성만 검수). 노출 전 검수 게이팅 대상.
- 코드는 대학과정 코드참조 재사용이라 원자노드DB와 1:1 조인된다(새 코드 미생성).

---

## 5. 소비·후속

- **U2**: 원자 코퍼스(graph.json)의 대학 원자 513개 `standard_codes`를 소단원→성취기준 1:1 맵으로 채움.
- **U3**: `standard_loader`로 `achievement_standard`(+`concept_standard_link`) 멱등 적재.
- 라이선스 매트릭스: `licensing_safety.md`(와이매스 대학 성취기준 v1 행).
