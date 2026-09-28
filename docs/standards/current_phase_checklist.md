# 현단계 완수 체크리스트 — Phase 1(MVP) 진행 중 + 다과목 확장 준비

> ⚠️ **현행 국면과의 관계 (2026-09-28 정리)**: 이 문서의 "Phase 1(MVP) 진행 중" 전제는 **2026-08-30 EOS 전환 선언**(MVP 종료 · `docs/strategy/eos_transition_declaration_2026-08-30.md`)으로 낡았다. 현행 목표는 **12/31 내부 프로젝트 완성**(정의 = Phase 3 Release PASS + EOS G5 판정 + 12월 검증 P0 전건 종결 · 판정 게이트 `G-internal-completion-2026-12-31`)이며, 아래 C부의 Phase 1 종료 게이트(β 사용자 100명·재방문율·도메인 파트너 검수)는 실사용자 전제라 그 판정 *이후* `G-student-work-after-internal-completion` 재개 판정에 따른다(2026-09-24 ARCH-66 ⑥). A부·B부(확장 준비·선결 부채)의 완료 표시는 그대로 유효하다. 작업일정 정본은 이 문서가 아니라 `backlog/`(`backlog.py next`)다.

> **현단계 정의**: 저장소 ROADMAP.md 기준 **Phase 1(MVP) 진행 중**, 여기에 다과목 확장 로드맵의 P0(공통 기반화)에 해당하는 **확장 준비 작업**이 겹친 상태.
> **정본 관계**: Phase 게이트 수치의 정본은 `ROADMAP.md`(본 문서는 대조표). 확장 준비의 설계 정본은 `docs/architecture/subject_expansion_readiness.md`·검토 근거는 `docs/strategy/subject_expansion_roadmap_review.md`.
> **완료 판정 공통 게이트**(모든 코드 항목): pytest 전체 green(현행 ~4,600건) · ruff · black(ll=100) · mypy --strict · import-linter 계약 유지 · 커버리지 70%+.
> **상설 항목**: 각 Phase/트랙 착수 전 평가원·교육부 최신 공고 확인(2028 수능 개편 세부 변동 감시).

---

## A부 — 확장 준비 완수 조건 (브랜치 `claude/subject-expansion-architecture-m2db9s` · 슬라이스 S0~S3)

다과목 확장 로드맵 P0의 저장소 측 실체. 각 슬라이스는 자족 PR + 공통 게이트 green이 완료 판정.

### S0 — 설계 문서
- [x] `docs/architecture/subject_expansion_readiness.md` 작성: 수학 종속 9지점 전수 목록(계층별·{하드/soft/이미 중립} 3등급·파일:줄) · 조정 원칙(값싼 seam 3조건 판별식) · 로드맵 · ID/성취기준/오개념 네임스페이스 설계 · cross-subject 엣지 원칙 · 보류 항목 대장(각 항목 **착수 트리거** 명시)
- [x] MEMORY.md 결정 로그 추가(Overlay subject 축·수학 ID 불변·SymPy 단일 유지·Subject enum 수학 한정 존치·보류 4종 트리거)
- 완료 판정: 문서 내 인용 rev·경로 실재, 기존 문서(04a §8.1·math_dsl_risk_register Q5) 상호참조 정합

### S1 — CurriculumEntry `subject` 축 (유일한 마이그레이션 슬라이스)
- [x] `schemas/v1.1/curriculum_entry.schema.yaml`: `subject` 필드(required·default '수학'·**교과** 레벨 — NCIC `AchievementStandard.subject`(**과목** 레벨)와 granularity 구분 주석) · `composite_key` 3-튜플 · field_count 31
- [x] `schema/curriculum_entry.py`: `subject: str = Field(default="수학", min_length=1, ...)`
- [x] `db/models/curriculum_entry.py`: 컬럼(server_default '수학') + `UniqueConstraint(concept_id, country_code, subject)`
- [x] Alembic 마이그레이션(down_revision=`f3a4b5c6d7e8`): ADD COLUMN → 기존 UNIQUE drop → 3-튜플 UNIQUE. downgrade 대칭·왕복 검증
- [x] `l1/curriculum/curriculum_loader.py`: `_KR_SUBJECT` 상수·entry_id 규약(수학 셀 `{concept_id}:KR` 불변, 비수학만 `:{subject}` 접미) docstring
- [x] 테스트: 기본값·공백 거부·직렬화 / **같은 (concept_id, KR)에 '수학'+'물리' 두 행 공존 허용 + 동일 3-튜플 중복 거부** / KR 적재 셀 전부 '수학'·재적재 멱등
- 완료 판정: 공통 게이트 + alembic upgrade/downgrade 왕복 green

### S2 — NCIC 출처 표기 파라미터화 + 과학 코드 수용성 동결
- [x] 신규 `data_pipeline/citation.py`: `build_ncic_citation_core(subject_label="수학과")` — 고시 제2022-33호 공유·별책만 상이(별책 8 수학/별책 9 과학)
- [x] `ncic/models.py`·`concept_graph/models.py`·`atom_graph/models.py`의 `SOURCE_CITATION`을 빌더 합성으로 재작성 — **값 바이트 동일**(기존 golden/직렬화 테스트가 증명). `standards_university/models.py`는 NCIC 비유래라 불변
- [x] 과학 코드 수용성 회귀 테스트: `[12물리01-01]`·`[10통과1-01-01]`·`[12화학02-03]`·`[9과01-05]`·`[12물리Ⅱ03-02]` 패턴 통과 + `AchievementStandard(subject='물리학Ⅰ')` 생성 + norm_id `2022_12물리_01_01` 통과
- 완료 판정: 공통 게이트 + data-pipeline 커버리지 91% 유지 + 기존 코퍼스 재생성 diff 0

### S3 — 과목 중립성 회귀 게이트
- [x] `tests/data_pipeline/test_subject_neutrality_gate.py`: citation 단일 원천(3모듈이 빌더 출력 포함 + "[수학과 교육과정]" 리터럴이 `citation.py` 밖 재등장 금지) · AREA 예약 접두(물리 예약 MECH·ELEC·WAVE·THERMO·MODPHY 등) 미침범
- [x] `tests/backend/l4/test_misconception_namespace_gate.py`: 수학 오개념 30종 id가 예약 과목 접두(`phys-`·`chem-`·`bio-`·`earth-`) 비사용 + kebab 형식
- [x] `schema/enums.py` `Subject` docstring 1줄(수학 교과 한정 — 타 과목은 향후 `subject_area` 축) · `edge.schema.yaml` evidence_source 주석(`<subject>_education_literature` 패턴 규칙·rename 금지)
- 완료 판정: 공통 게이트 (값·멤버 무변경이므로 마이그레이션 0)

### A부 보류 항목 (착수 트리거 도달 전 구현 금지 — S0 문서의 대장이 정본)
- `dimensional_consistency` primitive(sympy.physics.units) — 트리거: 물리 문항 검증 소비처 첫 등장. **커널 교체 아님**(동치 권위는 SymPy 단일 유지)
- `Problem.subject_area` 컬럼 — 트리거: 물리 문항 첫 적재 (기존 `Subject` enum에 물리 값 ADD VALUE 금지 — 축 혼동 영구화)
- 물리 오개념 시드(`phys-` 접두) — 트리거: 오개념 canonical 수렴 완료 + 물리 콘텐츠 착수
- PHY AREA 니모닉 실등록·idmap 개편 — 트리거: 물리 원천 코퍼스 category 목록 확정
- 개념 ID 재발급 — **영구 금지**(3번째 breaking·편익 0)

---

## B부 — 현단계에 이미 등록된 선결 부채 (확장의 전제 조건)

다과목 확장 로드맵 P0가 "새로 발견"한 것이 아니라 MEMORY 결정 로그에 이미 등록된 부채. 타 과목 콘텐츠 착수 전 완료가 전제인 항목에 ★.

- [ ] ★ **오개념 canonical ID 수렴** — 3중 표현(kebab 30 / M-id 839 / JSONB, FK 없음) 단일화 (MEMORY 2026-07-01 "🔴 최우선 부채"). 완료 후에만 오개념 유형 5분류(절차/개념/표상/오독/사실혼동 — 로드맵 제안 수용) 축 추가
  - **기계 몫 완주(2026-07-02)**: 검수 큐 75행+promote 원커맨드(M1)·canonical 선택 정책+shadow 측정(M2)·mis_id 확폭+침묵 skip 결함 수정(M0). **잔여 = 사람 검수**: 큐 기입 → promote --load → shadow 측정 윈도 → canary go/no-go (MEMORY 2026-07-02 구현 로그)
- [x] ★ **임베딩 namespace 분리** — concept/atom/misconception 벡터공간 분리(invariant ⑨). 이 설계에 **과목 축을 함께 반영**(로드맵의 "ChromaDB 컬렉션 분리" 항목의 올바른 실체 — 저장소는 pgvector)
  - **완료(2026-07-02)**: 실측상 물리 분리·질의 분리는 기존재 — 논리 경계를 구현(3테이블 subject 컬럼·3축 스코프 9지점·cross-table 코사인 금지 게이트·재임베딩 0). 방향맹 FP 45.5%는 별개 트랙(04b judge)으로 분리 명문화 (MEMORY 2026-07-02)
- [x] ~~`Problem`의 `Curriculum` enum 잔여 제거~~ — **오등록 상환(2026-07-02)**: 문항 본질 속성·L6 게이트 ③ 살아있는 소비처라 유지가 정답(개념≠문항). 제거·Overlay 이관 기각(MEMORY 2026-07-02·`Curriculum` docstring 정본)
- [x] **단계8 Q10-⑧ "LLM 전체 그래프 미열람" 불변식 CI 동결(2026-07-03·Part 10 검토)** — graph→LLM 컨텍스트 빌더 부재 재확인(잠재 리스크·현존 결함 아님). `test_llm_subgraph_budget_invariant.py`가 LLM 경계 그래프-컬렉션 주입 금지 + traversal 예산 단일 출처 동결. 수치 예산 guard(`l2/reasoning_subgraph.py` builder)는 **소비처(graph→LLM 컨텍스트) 트리거까지 보류**(10-2 tier상 중급/최종·risk_register 미채택). 상세: `build_roadmap_part10_review.md`
- [ ] 그래프 위생 게이트 — 런타임 reachability/SCC(현재 load-time DFS만). 단, 소비처(증분 edge-add 경로) 생길 때 — premature 금지
- [x] 렌더 선택 단일 진실원(invariant ⑩) **완료(2026-07-02)** · speech 파서 notation_contract 편입(⑪) **오등록 상환(2026-07-02)**
  - **⑩ 완료**: 실측상 3곳 중 scene_renderer(위젯 선택)는 정당한 계층 분리·부채 아님. 진짜 부채는 WebView 경계가 viz.type을 버려 웹이 spec 모양 재추론하던 drift 1건 — 경계 {type,spec} 봉투(B)+웹 type-first dispatch(A)+골든 계약 data/render_contract.json(A/C 교차검증)으로 해소. 마이그레이션·재임베딩 0 (MEMORY 2026-07-02)
  - **⑪ 오등록 상환**: speech는 별도 표기 계층(LaTeX 프레젠테이션)의 자족 파서·자체 골든(`test_speech_rules.py` 38케이스)으로 검증됨 — SymPy↔mathjs notation_contract와 입력 언어·산출·권위가 달라 계약 3자 편입은 카테고리 오류. **경계 명문화**(notation_contract.md §5)로 충족. drift는 유니코드 위첨자 1점·활성 경로 0(소비처 생길 때 정합·premature 보류). 코드 0·마이그레이션 0 (MEMORY 2026-07-02)
- [x] interaction event_data 타입 계약(invariant ⑫) **완료(2026-07-03)**
  - **⑫ 실상환**(재분류 아님): event_data 자유 JSONB·EventType 11종 중 실제 생산 3종(검산결과·힌트제공·시각화조작)만 계약 대상·휴면 8종 면제. 하네스가 `passed`·`hint_level`을 실제로 읽는 활성 소비처 존재라 premature 아님. 계약 단일원(`schema/event_data_contract.py`·pydantic `extra="forbid"` 모델 + `build_event_data` 강제 헬퍼)으로 3 생산자 배선 → produce 좌석에서 stray key 구조적 불가 + 거버넌스 테스트 15건. 무거운 discriminated-union 런타임 재작성·휴면 구속·payload 내부 구속은 기각(premature). 마이그레이션·재임베딩 0 (MEMORY 2026-07-03)

---

## C부 — Phase 1(MVP) 종료 게이트 대조 (정본: ROADMAP.md)

### 저장소 정본 게이트 (Phase 2 진입 조건 — 변경 불가)
- [ ] β 사용자 100명 이상
- [ ] 사용자 재방문율 30%+ (7일 기준)
- [ ] Polya 답 미루기 단계 평균 2.5+ 도달
- [ ] LLM 호출 비용 학생당 월 1,000원 이하
- [ ] 도메인 파트너 검수 통과
- [ ] 미달 시 Phase 1 연장 (게이트 완화 금지)

### 다과목 로드맵 P1 체크와의 관계 (충돌 없음 — 보완 관계)
로드맵 P1(수학 출시)의 지표는 저장소 게이트를 세분·보강한다. 채택 권장 항목:
- [ ] 핵심 플로우 E2E: 촬영→OCR→개념 매칭→진단→소크라테스→오개념 태깅, 상이한 10문제 연속 무오류 (단 OCR 정본은 PaddleOCR+Qwen3-VL — 검토 문서 C5)
- [ ] 오개념 태깅 적중률 표본 검증 30건 수기 대조(목표 70%+) — 기존 "판정-실제 오개념 일치율" 대리 지표(04a §8.4 0단계 7종)와 통합 측정
- [ ] 온보딩: 학년·목표 입력→첫 진단 5문항→첫 소크라테스 체험 3분 이내
- [ ] D1/D7 리텐션 계측 — 저장소 게이트(7일 30%+)가 상위 기준, 로드맵의 "베타 종료 D7 25%+"는 베타 중간 기준으로 병기
- [ ] 만 14세 미만 법정대리인 동의 플로우 — **이미 구현 자산 존재**(`parental_consent`·ConsentScope·PIPA 매트릭스, 2026-06 슬라이스): 신규 개발이 아니라 온보딩 배선·전문가 검토 예약만 잔여
- [ ] 크래시 리포팅·저속망/오프라인 동작 정의·로컬 추론 동시 세션 상한 실측 + 클라우드 폴백 비용 상한 — L5/인프라 잔여 (클라우드 폴백은 기존 L3 라우터 경유 원칙 유지)
- [ ] 스토어 심사 준비(데이터 보안 섹션·아동 정책·구독 설계) — Phase 1.5 결제 결정과 연동(ROADMAP "의도적으로 안 하는 것" 존중: 결제는 Phase 1.5~2)

### 확장 관점 추가 게이트 (본 체크리스트 신설분)
- [ ] Phase 2(타 과목 착수) 진입 전: **A부 S0~S3 완료 + B부 ★ 2건 완료** — 이것이 다과목 로드맵 P0 완료 판정의 저장소 측 정의
- [x] 과목 순서(물리 vs 화학) MEMORY 결정 로그 확정 — **물리 우선 locked**(사용자 확인·MEMORY 2026-07-02)

---

**작성**: 2026-07-02 · **다음 갱신**: A부 슬라이스 완료 시마다 체크 반영, Phase 1 게이트 수치는 월간 검토(ROADMAP 주기)와 동기
