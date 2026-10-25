# 과목 확장 준비(Subject Expansion Readiness) — 설계 정본

> **목적**: 수학 전용인 현 시스템을 타 과목(물리 우선 → 화학 → 국어 → 사회·역사)으로 확장하기
> 위한 준비 설계. "무엇을 지금 중립화하고, 무엇을 과목 콘텐츠 착수 시점까지 보류하는가"의 경계를
> 정본화한다.
> **확정 결정(MEMORY 2026-07-02)**: 과목 순서 **물리 우선(locked)** · Overlay subject 축 ·
> 수학 concept_id 재발급 금지 · 동치 권위 SymPy 단일 유지 · `Subject` enum 수학 한정 존치.
> **자매 문서**: `docs/strategy/subject_expansion_roadmap_review.md`(로드맵 v1.0 검토·교정 6건) ·
> `docs/standards/current_phase_checklist.md`(현단계 완수 체크리스트 — A부가 본 문서의 실행 대응물)
> **상태**: S0 산출물. S1~S3 코드 준비 슬라이스와 같은 브랜치에서 진행.

---

## 1. 수학 종속 지점 전수 목록 (계층별·3등급)

등급: **하드**(코드·enum·정규식에 수학이 물리적으로 박힘 — seam 필요) / **soft**(콘텐츠·데이터가
수학일 뿐 구조는 중립 — 과목 팩 추가로 해소) / **중립**(이미 과목 독립).

| 계층 | 지점 | 등급 | 실측 근거 |
|---|---|---|---|
| L1 파이프라인 | `SOURCE_CITATION` "[수학과 교육과정]" 하드코딩 3모듈 산재 | **하드** | `data_pipeline/ncic/models.py` · `concept_graph/models.py` · `atom_graph/models.py` → **S2에서 빌더 단일화** |
| L1 파이프라인 | `STANDARD_CODE_PATTERN`·`NORM_ID_PATTERN` | **중립(실측)** | 한글 과목 토큰 `[ㄱ-ㆎ가-힣Ⅰ-ⅿ]{1,6}`이 과목명을 가리지 않음 — `[12물리01-01]`·`[10통과1-01-01]`·`[12화학02-03]`·`[9과01-05]`·`[12물리Ⅱ03-02]` 매치 확인(2026-07-02). **파서 개편 불필요, S2 회귀 테스트로 수용성 동결** |
| L1 파이프라인 | `DomainCode` Literal(수와 연산 등 수학 영역) | soft | 소비처 0(export 전용·`AchievementStandard.domain`은 str) — docstring에 수학 한정 명시만, 레지스트리화는 premature |
| L1 스키마 | 개념 ID `{TRACK}-{AREA}-{NNN}`에 과목 축 부재, `_TOPIC_AREA_MAP` 수학 37 category | **하드** | `schemas/v1.1/concept.schema.yaml` · `data_pipeline/concept_graph/idmap.py` → **§4 AREA 레지스트리 규약으로 해소(ID 재발급 없이)** |
| L1 Overlay | `CurriculumEntry` 복합키 `(concept_id, country_code)` — subject 축 부재 | **하드** | `db/models/curriculum_entry.py:129` UNIQUE 2-튜플 → **S1에서 3-튜플 확장** |
| L1 노드 | Concept 노드의 교육과정·과목 필드 | **중립** | 2026-06-30 rev `f3a4b5c6d7e8`로 subject·curriculum_version 제거 완료, 금지 필드 게이트(`test_concept.py`) 동결 — **과목 확장의 토대** |
| schema | `Subject` enum = 공통/미적분/확통/기하/인공지능수학 (Problem NOT NULL) | **하드** | `schema/enums.py:85-95`. 실체는 "수학 교과 내 수능 선택과목" 축 → **물리 값 ADD VALUE 금지**, 타 과목은 향후 `Problem.subject_area` 별도 축(§7 보류 대장) |
| schema/엣지 | `evidence_source`의 `math_education_literature` | soft | `schemas/v1.1/edge.schema.yaml`. rename은 데이터 마이그레이션 유발 — `<subject>_education_literature` 패턴으로 값 추가(물리 엣지 첫 생성 시) |
| L3 | 동치 검증 SymPy 단일 권위 | soft | `l3/symbolic_equivalence.py`. 물리도 수식 동치는 SymPy 그대로 — 필요한 건 §6의 축 추가이지 커널 교체 아님 |
| L4 | 오개념 카탈로그 30종 전량 수학·kebab-id 무과목 | soft | `l4/misconception/catalog.py`. §5 명명 규약(`phys-` 접두)만 지금 확정, subject 필드는 canonical 수렴(3중 표현 부채) 후 |
| L5 | OCR 수식 인식 전용 | soft | `l5/ocr/`. 물리 도해(회로도·자유물체도) 인식은 물리 콘텐츠 Phase 소관 |
| L5/schema | `VisualizationStyle` 16종 수학 표상 | soft | `schema/enums.py:304-363`. 자체 docstring이 "ADD VALUE로 확장" 설계 명시 — 물리 양식(벡터장·파동 등)은 콘텐츠 착수 시 추가 |
| L5 | 시각화 spec·LearningScene DSL | **중립** | 선언적 spec + 렌더러 플러그인("표현≠의미") — 과목별 spec 타입 추가로 수용, 새 추상 불요 |
| L6 | 수능 게이팅·시그니처 패턴(수학 55+108) | soft | 구조(시그니처 방법론)는 재사용, 패턴 데이터는 과목 팩 |

## 2. 조정 원칙 — 값싼 seam 3조건 판별식

"소비처 없는 추상 미도입" 원칙 아래, **지금 하는 것**은 다음 3조건 중 하나 충족 시만:

1. **데이터가 이미 존재하는 축의 명시화** — 예: subject 축(NCIC `AchievementStandard.subject`가 이미 개방 str·값 실재 — 날조가 아니라 승격)
2. **나중에 하면 마이그레이션 비용이 비선형 증가** — 예: CurriculumEntry 의미키 확장(물리 셀이 섞인 뒤 키 재정의는 데이터 정리 동반)
3. **회귀를 막는 게이트** — 새 수학 하드코딩 유입 차단(추상이 아니라 불변식)

판별식: *"물리 첫 콘텐츠 슬라이스가 이 코드를 수정 없이 호출하는가?"*에 "아마도"라고밖에 답할 수
없으면 **보류**. 물리 콘텐츠 설계 확정 전에 만든 인터페이스는 그때 가서 고치게 된다(UC→TRACK-AREA-NNN
재ID 전환이 실례 — 추측으로 만든 스킴은 한 번 갈아엎었다).

## 3. 로드맵

| 단계 | 범위 | 게이트 |
|---|---|---|
| S0 *(본 문서)* | 설계 정본 + MEMORY 결정 로그 | 문서 정합(인용 rev·경로 실재) |
| S1 | CurriculumEntry `subject` 축(유일한 마이그레이션) | 4게이트 + alembic 왕복 + 3-튜플 공존/중복 테스트 |
| S2 | NCIC citation 빌더 단일화 + 과학 코드 수용성 동결 | 4게이트 + 기존 golden green(바이트 동일 증명) |
| S3 | 과목 중립성 회귀 게이트 2파일 + docstring/주석 | 4게이트(마이그레이션 0) |
| — | **(범위 밖 — P2 물리 착수 시 예약 지점, §7 보류 대장)** | 착수 트리거 도달 시 |

4게이트 = pytest·ruff/black(ll=100)·mypy --strict·import-linter.

## 4. ID·성취기준 네임스페이스 설계

### 4.1 개념 ID — 수학 ID 불변 + AREA 니모닉 레지스트리 (확정)

- **수학 concept_id 재발급 영구 금지.** 3번째 breaking 재ID(개념 <!-- fact:concept_graph.concepts -->437<!-- /fact --> + 아톰 <!-- fact:atom_graph.nodes -->2,683<!-- /fact --> + aliases 사슬 +
  curriculum_entry·textbook join 전파)는 편익 0에 비용 최대.
- subject를 ID 세그먼트로 **넣지 않는다** — 노드에서 *제거한* 축(rev `f3a4b5c6d7e8`)을 ID 문자열로
  되들이는 자기모순. 과목 스코핑 정본은 Overlay `subject`(S1) + `search_concepts(domain=...)` 필터.
- **AREA 니모닉은 전역 유일하며 정확히 하나의 과목에 속한다**(레지스트리 규약). subject는 ID의
  세그먼트가 아니라 AREA에서 *유도 가능한* 속성.
- **물리 예약 니모닉(선점)**: `MECH`(역학) · `ELEC`(전자기) · `WAVE`(파동) · `THERMO`(열) ·
  `MODPHY`(현대물리). S3 게이트가 수학 `_TOPIC_AREA_MAP`의 침범을 차단. 실등록·idmap 개편은
  물리 원천 코퍼스 category 목록 확정 시(§7).
- `PHY-` 같은 TRACK 접두 신설 기각 — TRACK(ELEM/MID/HIGH/RT/OLY)은 학교급 축이지 과목 축이 아님.
  축 혼용 금지.

### 4.2 성취기준·norm_id — 이미 과목 수용 (실측)

코드 스킴 `[학년대수 과목토큰 영역-순번]`의 과목 토큰이 유일성 축을 겸한다 — `2022_12물리_01_01`은
수학 norm_id와 충돌하지 않는다. 필요한 것은 (a) S2 수용성 동결 테스트 (b) 과학과 성취기준 수집 시
`SOURCE_CITATION` 과목 라벨(별책 9 과학) — S2 빌더가 준비한다. 실제 과학과 데이터 수집은 범위 밖.

## 5. 오개념 네임스페이스 규약

- 비수학 오개념 kebab-id는 **과목 접두 필수**: `phys-`·`chem-`·`bio-`·`earth-`
  (slash 아님 — kebab charset·URL 안전 유지). 수학 기존 30종은 무접두 그대로(재명명 금지).
- S3 게이트: 수학 카탈로그가 예약 접두를 침범하지 않음을 동결. (역방향 — 물리 오개념이 무접두로
  들어오는 것은 물리 시드 슬라이스의 게이트 소관.)
- 오개념 `subject` **필드**는 보류 — 3중 표현 부채(2026-07-02 작성 당시 kebab 30/M-id 839/JSONB) canonical 수렴이 선행
  트랙이며, 수렴 스키마 설계에 과목 축과 오류 유형 5분류(절차/개념/표상/오독/사실혼동 — 로드맵 제안
  수용)를 함께 반영한다.

## 6. 동치 권위의 물리 확장 해석

**권위는 여전히 SymPy 단일이다**(`math_dsl_risk_register.md` Q10-⑦). 물리 확장은 커널 *교체*가
아니라 **축 추가**:

- 수식 동치: `identity_status(lhs, rhs)` 그대로 — 시그니처가 이미 과목 중립(문자열 2개 → 4상태 판정).
- 물리 추가 축: `dimensional_consistency(expr, expected_dim)` — `sympy.physics.units` 기반
  **형제 primitive**(같은 L3·같은 정직성 규약: 판정 불가는 undecidable로 보수 처리). SymPy 생태계
  안이므로 "단일 권위" 원칙 유지.
- `EquivalenceKernel` Protocol 레지스트리류 플러그인화 **기각** — 소비처 0 추상의 전형.
- WH-S 3-Tier(수치·SymPy·Lean)·WH-1 하네스는 `04a_wh1_tutoring_harness.md` §8.1 선언대로
  **재사용 + 도메인 도구만 교체**.

## 7. cross-subject 엣지 원칙

- 관계 타입 신설 금지(플레이북 5~8개 제한 — `applies_to`류 불가). 물리 '순간속도' 노드의 선수개념이
  수학 '미분계수' 노드인 식으로 **기존 `prerequisite`가 이미 그 의미를 담는다**.
- 과목 경계는 엣지 속성이 아니라 **양 끝 노드의 Overlay subject로 유도** — 엣지 스키마 무변경.
- Minimal Reasoning Subgraph 추출 시 cross-subject 경계 정책(경계 넘어 depth 지속 vs 절단)은 물리
  튜터링 소비처 등장 시 결정. 양안 모두 depth ≤ 2·max_nodes ≤ 12~20 예산 안에서만.
- `evidence_source`: 기존 값 rename 금지, `<subject>_education_literature` 패턴으로 값 추가(물리
  엣지 첫 생성 시).

## 8. 보류 항목 대장 (착수 트리거 도달 전 구현 금지)

| 항목 | 보류 사유 | 착수 트리거 | 착수 시 형태(스케치) |
|---|---|---|---|
| `dimensional_consistency` primitive | 소비처 0 | 물리 문항 검증 소비처 첫 등장 | `l3/dimensional_consistency.py` — `(expr: str, expected: str) -> DimVerdict(consistent/inconsistent/undecidable/parse_error)`, sympy.physics.units |
| `Problem.subject_area` 컬럼 | 물리 Problem 0건 | 물리 문항 첫 적재 | 컬럼 신설(server_default '수학') — 기존 `Subject` enum은 수학 한정 의미로 존치 |
| 물리 오개념 시드 | canonical 수렴 선행 | 수렴 완료 + 물리 콘텐츠 착수 | `phys-` 접두 kebab·FCI *분류 체계만* 참조(원문항 저작권 — 미사용) |
| PHY AREA 실등록·idmap 개편 | 물리 category 원천 목록 0 | 물리 원천 코퍼스 category 확정 | `_TOPIC_AREA_MAP` → 과목별 레지스트리 분리, §4.1 예약 니모닉 소비 |
| `VisualizationStyle` 물리 양식 | 소비처 0 | 물리 시각화 콘텐츠 착수 | PG enum ADD VALUE(벡터장·파동그래프 등) — 자체 docstring 설계 그대로 |
| 물리 도해 OCR | 콘텐츠 Phase 소관 | 물리 손글씨 입력 요구 확정 | 기존 PaddleOCR+Qwen3-VL 하이브리드에 도해 프롬프트 축 추가 검토 |
| 오개념 subject 필드·유형 5분류 | 3중 표현 부채 상호작용 | canonical 수렴 트랙 | 수렴 스키마에 과목 축·유형 축 동시 반영 |
| ~~임베딩 namespace 과목 축~~ | **해소(2026-07-02)** — invariant ⑨ 트랙에서 구현 완료: 임베딩 3테이블 subject 컬럼 + (provider, model, subject) 3축 스코프 + 거버넌스 게이트(재임베딩 0) | (트리거 도달·완료) | Alembic `b6c7d8e9f0a1`·`test_embedding_namespace_governance.py` |

## 9. 검증 invariant (S1~S3가 코드로 동결하는 것)

- CurriculumEntry 의미키 = `(concept_id, country_code, subject)` — 같은 개념·같은 국가에서 교과가
  다르면 별개 셀(벡터: 기하·물리학), 동일 3-튜플 중복 거부 (S1)
- `subject`(교과: '수학'·'물리') ≠ NCIC `AchievementStandard.subject`(과목: '공통수학1') —
  granularity 구분을 양쪽 docstring 교차 명기 (S1)
- 수학 entry_id `{concept_id}:{country}` 형식 불변(데이터 churn 0) — 비수학만 `:{subject}` 접미 (S1)
- `SOURCE_CITATION` 3모듈이 `build_ncic_citation_core()` 단일 원천을 합성 — "[수학과 교육과정]"
  리터럴이 `citation.py` 밖에 재등장 금지(`standards_university`는 NCIC 비유래라 제외) (S2·S3)
- `STANDARD_CODE_PATTERN`·norm_id의 과학과 코드 수용성 — 회귀 테스트로 동결 (S2)
- 수학 `_TOPIC_AREA_MAP`이 물리 예약 니모닉 미침범 · 수학 오개념 30종이 과목 접두 비사용 (S3)
