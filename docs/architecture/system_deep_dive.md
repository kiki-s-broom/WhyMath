# 시스템 영역별 심화 (System Deep Dive)

> 이 문서는 [용어집(`glossary.md`)](glossary.md)의 짝 문서입니다.
> 용어집이 *"한 줄 정의"* 라면, 이 문서는 각 영역을 **① 역할 ② 핵심 설계 결정(근거·날짜 포함) ③ 엔티티·데이터 흐름·경계 ④ 현재 구현 상태 ⑤ 리스크·한계** 순으로 깊게 서술합니다.
> 각 계층의 **정본은 `01_*.md ~ 07_*.md`**이며, 이 문서는 현재 상태(S0 완료·S1/S2 진행·원자 백본 전환)를 반영한 종합·심화입니다.
>
> **수치 표기 주의**: 설계 문서의 *목표 추정치*(예: 개념 그래프 500노드·오개념 400)와 현재 *실측치*(원자 1,837·선수엣지 3,220·오개념 839)가 병존합니다. 이 문서는 실측치를 우선하고, 목표치는 "목표"로 명시 구분합니다.

---

## §1. 7계층 코어 개요 — 경계가 곧 자산

WhyMath의 뼈대는 **책임 레이어 L1~L7**(무엇을 책임지나)이고, 이와 직교하는 두 번째 축으로 **5블록 배포 토폴로지**(Client / Backend / DB / ML / Content Pipeline — 무엇이 어디서 실행되나)가 있습니다. 의존성은 **상위→하위 단방향만** 허용되며(L7→…→L1, 역방향 금지), 이 규칙은 문서 권고가 아니라 CI의 **import-linter로 7계층 단방향이 강제**되고, 추가로 MATH DSL invariant 12종이 코드 게이트로 동결되어 있습니다.

이 아키텍처의 가장 중요한 결정은 **L1–L4 = UI와 무관한 독립 수학 코어**, **L5 = 클라이언트**라는 분리입니다(슬라이스 89). 수학 로직을 클라이언트에 절대 넣지 않고, 클라(Flutter·별도 웹·PDF·AI)는 API로만 소비합니다. 짝을 이루는 원칙이 **"표현 ≠ 의미"** — 문항·수식·해설은 화면 문자열이 아니라 항상 구조(AST/JSON)로 코어에 저장하고, 렌더는 각 클라이언트가 담당합니다. 이 원칙은 `Visualization`(선언적 시각화 명세)·`SpeechSpec`(낭독 명세)·`LearningScene`(장면 DSL) 세 엔티티에 일관 적용됩니다.

**현재 상태**(2026-07-03, 커밋 65f7c37 기준): 백엔드 344 .py/~64k줄, **테스트가 소스보다 많음**(346파일/~92.7k줄), Alembic 마이그레이션 54개 단일 head. 계층별로 L1~L4는 🟢 실질 구현(Phase 1 요구 초과), L5 🟡 골격, L6 🟡 게이팅만, L7 ⚪ 코드 0(의도적). 즉 **코어는 과잉 성숙, 제품 루프는 미성숙**이며, 지금 가장 큰 리스크는 기술 부채가 아니라 *검증 부채*(이 코어가 실제 고3의 30번 문제 앞에서 작동한 증거 0건)입니다.

> 정본: [`00_overview.md`](00_overview.md)

---

## §2. L1 데이터 기반 — 진짜 해자

**역할**: 한국 수학 교육 데이터의 *진실 원천*을 정의·수집·관리합니다. 1~2년 누적되면 B2B 라이선싱이 가능한 자산이라 "진짜 해자"로 규정됩니다. 파이프라인은 **6단계 표준**(수집 httpx → 정제 pandas → 정형화 pydantic → 검증 Great Expectations → 저장 PostgreSQL+pgvector → 인덱싱 ANN)을 따릅니다.

**핵심 엔티티**: `Concept` 노드는 canonical `concept_id = math.<area>.<slug>` 형태로 교육과정·언어·렌더러와 무관한 의미론 PK입니다(2026-07-02 Part 9 근거, 옛 `{TRACK}-{AREA}-{NNN}` ID는 `aliases`에 보존). 표기(한·영·일)조차 노드에 넣지 않고 `locales/{lang}.json` 계층으로 분리해 "Concept Purity"를 지킵니다(Phase 1은 `ko`만 충전). `Edge`는 **7가지 관계 유형**(`prerequisite`·`generalization`·`specialization`·`contrast`·`application`·`composition`·`notation_variant`)만 두고 각 엣지가 강도(strength)+증거(evidence)를 갖습니다 — 관계 폭발을 막기 위해 `similar_to`/`related_to`는 애초에 없습니다. 그 밖에 `CurriculumEntry`(개념×국가 쌍의 30필드: 도입 학년·맥락·요구 깊이·평가 방식·표준 코드), `TextbookMapping`(단원 트리·페이지 범위·톤 프로필), `StudentProfile`(국가·학년·학교·교과서·진도·목표·학습 선호 + "그림자 커리큘럼" = 학원·인강 진도)이 있습니다.

**핵심 설계 결정 — 저작권 안전선이 스키마급 원칙**: 목차·단원명·페이지 범위·교육과정 코드 같은 *구조 메타데이터만* 사용하고 본문·문제·그림은 일절 복제하지 않으며, 문제가 필요하면 자체 코퍼스의 동등문제로 대체합니다. 교과서 *학습목표 텍스트* 인용조차 "변호사 검토 전제"로 보류(PRD가 페어유즈로 단정한 부분을 명시적으로 보류)합니다. 또 하나는 **다국 매트릭스 9~12개국 풀스케일을 Phase 3로 재배치**한 결정 — PRD 본문 §1.6과 §15.1이 불일치했고 Phase 1 과욕으로 판단, Phase 1은 한국 + 참고용 미국·IMO만 다룹니다.

**경계**: `StudentProfile`은 **L1이 소유**하고 **L6이 소비**하며 L2는 읽기만 합니다. "자동 커리큘럼 정렬 엔진"이 컴포넌트 매트릭스에서 L1+L6로 표기되는 이유는 *입력 자산*은 L1, *조정 로직*은 L6이기 때문입니다.

**현재 상태**: 🟢 실질 구현(43파일/~7.3k줄). 2026-07-04 **원자 백본으로 runtime 진실 원천을 단일화** — 원자 1,837·선수엣지 3,220(초·중·고+대학 4축)·오개념 839·성취기준 895·pgvector 임베딩. 구 437 개념그래프는 `legacy_snapshot`(readonly·audit_only)으로 격하. 참고 자산 규모: 성취기준 150~180개(2022 개정, 형식 `[9수01-01]`)·검정교과서 13종·학교알리미 5,500+ 학교·평가원 기출 10년치 1,000+문항. **리스크**는 크로스워크(437↔1,837)의 1:N/N:1 매핑이 mastery 이력·오개념 crosslink를 오염시킬 가능성으로, 거버넌스 테스트가 구 그래프 재유입을 동결합니다.

> 정본: [`01_data_foundation.md`](01_data_foundation.md)

---

## §3. L2 학습자 모델 — 시간축의 상태

**역할**: LLM이 현재 발화만 보는 것과 달리, L2는 학생의 *시간축에 걸친 장기 상태*(6개월·1년·3년 학습 곡선)를 통계 모델로 추적·예측합니다. LLM에는 6개월 이력을 토큰으로 못 넣으므로, 출력은 *요약 상태*(BKT 확률·오개념 벡터·IRT 능력)로만 L3·L4에 주입됩니다.

**핵심 엔티티**: `MasteryState`(학생×개념노드 숙달)는 `bkt_mastery: float`(0~1, **Phase 1부터 항상 채워짐**)·`irt_theta: float|None`(-3~+3, 신뢰구간 `irt_ci_lower/upper`, Phase 2 이후)·`forgetting_strength`·`decayed_mastery`·`preferred_solution_style`(L3 `SolutionPath.approach_type` 6종 중 하나 — ⚠️ 미구현: `MasteryState` 자체가 문서 스케치·코드 0건, 2026-08-15 실측)를 담습니다. `LearnerState`는 L2가 L3/L4에 주입하는 요약으로, **동적 필드**(mastery dict·general_ability·domain_abilities·active_misconceptions·affect·recent_struggles/successes)는 L2가 생산하고, **정적 필드**(grade·curriculum·active_textbook_id·shadow_curriculum_progress·goals)는 L1 `StudentProfile`의 *사본*으로 전달만 합니다.

**핵심 설계 결정 — BKT 유지**: PRD v1.1은 IRT theta+망각곡선+협업필터링만 채택하고 BKT를 제외했으나, WhyMath는 BKT를 유지했습니다. 근거는 콜드스타트 — BKT는 성취기준당 4파라미터(P(L0)·P(T)·P(S)·P(G))만 추정해 학생 몇 건 풀이로도 베이지안 업데이트가 돌지만, IRT는 다수 학생 응답 행렬이 있어야 문항 모수가 안정되어 **Phase 1 β 100명** 단계에선 불안정합니다. 그래서 **BKT(Phase 1) → IRT(Phase 2) → DKT(Phase 3+, N>10,000)는 대체가 아니라 공존·보강**이며, Phase 2 이후에도 신규 성취기준·신규 학생 콜드스타트는 BKT가 담당합니다. IRT는 1PL(Phase 1)→2PL(Phase 2·변별도)→3PL(Phase 3+·추측)로 정밀화하며 어댑티브 출제는 Fisher Information을 씁니다.

또 하나의 축은 **정서 신호 모델** — 세션 지속 시간·연속 오답·응답 시간 z-score·rage quit·답 요구 빈도·재시도·스킵률 등 입력 시그널을 **FLOW/FRUSTRATED/BORED/OVERWHELMED/AT_RISK 5분류**로 판정해 L4의 정서 안전 결정에 넘깁니다.

**경계·저장**: `StudentProfile`은 L1 소유, L2는 읽기 전용. 저장은 TimescaleDB `mastery_history` 하이퍼테이블(`create_hypertable(..., 'timestamp')`, PK `(student_id, standard_code, timestamp)`).

**현재 상태**: 🟢 실질 구현(12파일/~2.3k줄) — BKT·IRT·능력추정·mastery 추적·`detect_plateau`(정체)·`detect_regression`(퇴행)·약개념/선수 추천. **리스크**는 실사용자 데이터가 0건이라 IRT 모수·정서 분류기가 아직 검증되지 않았다는 점(S3 파일럿 대상).

> 정본: [`02_learner_model.md`](02_learner_model.md)

---

## §4. L3 콘텐츠 생성·검증 — LLM의 모든 책임

**역할**: LLM 호출의 *모든 책임*(라우팅·호출·도구·검증·캐싱·비용추적)을 단일 계층에 집약합니다. 목표는 "비용 1/10, 환각 0에 가까운 LLM 활용"이며, **모든 LLM 호출은 라우터 경유**(직접 호출 금지)에 Langfuse 추적·Redis 캐싱(TTL 1주) 대상입니다.

**핵심 설계 결정 — 3축 라우터**: 축1 비용·위치(`CostTier` = LOCAL/CLOUD_MID/CLOUD_HIGH, **목표 분포 로컬 80%/중급 18%/최고 2%**), 축2 로컬 크기(`LocalModelTier` = FAST/MID/QUALITY), 축3 **태스크 패밀리**(`ModelFamily` = MATH/GENERAL). 평가 순서는 축1 → (LOCAL이면) 축3 → 축2이고, 클라우드면 축3·축2를 건너뜁니다(불변식: `LOCAL ⟺ local_model≠None ⟺ local_family≠None`). 세 번째 축은 **2026-05-20 태스크 인지 품질 실측**에서 나왔습니다 — NLP 호출(extract/translate/match)을 수학특화 `qwen2-math`로 돌리면 7b조차 정확도 0%인데 일반 `qwen2.5`로 바꾸니 match 3b=100%·translate 7b=75%였습니다. "크기 문제가 아니라 패밀리 미스매치"로 재해석해 패밀리를 1급 차원으로 승격했습니다. 크기 3종은 앞서 2026-05-19 GPU 지연 벤치로 확정했고, `mid`가 축1(CLOUD_MID)과 축2(MID=7b) 양쪽에 있어 클라우드 티어에 `CLOUD_` 접두사를 붙여 충돌을 해소했습니다.

**모델 풀·SLA**: 로컬 매트릭스는 (MATH,FAST)=qwen2-math:1.5b·(MATH,MID)=qwen2-math:7b·(GENERAL,FAST)=qwen2.5:3b·(GENERAL,MID)=qwen2.5:7b·(any,QUALITY)=qwen3.5:27b입니다. SLA 벤치(Phaiakes9, Radeon 8060S)에서 **FAST p50 1.0s만 SLA 게이트(p50<2s)를 통과**해 동기 즉답 기본경로가 되고, MID(3.9s)는 동시성 제한, QUALITY(13.9s)는 비동기 큐 전용(워커 동시성 1). 클라우드는 CLOUD_MID=Claude Sonnet(목표 18%)·CLOUD_HIGH=Claude Opus(목표 2%, 킬러·증명). 일일 비용 한도는 Free 100원/Basic 500/Premium 2,000/Gifted 5,000원이며, 예산 소진 시 "오늘은 로컬만"으로 강등하되 끊기지 않습니다(웰빙 우선).

**핵심 엔티티·환각 방어**: 풀이는 자연어가 아니라 `SolutionPath`(`approach_type` 6종·`concept_sequence` = 통과 개념노드 ID 순서열·`steps`·`embedding` text-embedding-3-large)로 인코딩하고, 각 `SolutionStep`은 `reasoning_type`(폐쇄 7종: DEDUCTION·SUBSTITUTION·CASE_SPLIT·INDUCTION·TRANSFORMATION·HEURISTIC·BACKWARD)·`sympy_verified`·`lean_verified`를 갖습니다. 환각 방어는 WhyMath 5중(스키마·PRM·도구·자기일관성·사람검수)과 PRD 4중을 하나의 파이프라인으로 통합 — 계산은 LLM에 시키지 않고 SymPy/Wolfram으로 넘기며, PRM 검증기 후보는 Qwen2.5-Math-PRM-72B입니다.

**경계**: `generate_visualization_spec`은 선언적 JSON 명세만 반환합니다(영상 bytes 반환은 7계층 경계 위반 — 렌더는 L5). L4에는 *권장 비용 티어*만 힌트로 넘기고 로컬 크기·동기성은 L3 라우터가 최종 결정합니다.

**현재 상태·리스크**: 🟢 인프라 완비 / 🔴 라이브 미검증(31파일/~6.8k줄). 라우터+Anthropic/Ollama provider·3-tier 검증·Redis·Celery·Langfuse가 다 있으나 **실측 비용·프롬프트 캐싱·guard_cloud 임계값이 전부 Phaiakes9 라이브 키 대기**(S1 사람 병목)이고, 실제 라우터 코드는 아직 2축만 알아 축3 반영이 M1.2 후속입니다. 정직한 한계로 **"개념 시퀀스 동치성 자동판정"은 미해결 연구 난제**로 규정합니다 — 같은 노드를 지나도 본질이 다를 수 있고(정당화 차이) 다른 노드를 지나도 동치일 수 있어(대수 vs 기하), `concept_sequence`는 동치성의 필요조건도 충분조건도 아닙니다. 휴리스틱(편집거리+임베딩 코사인+최종답 SymPy 동치)으로 1차 분류만 하고 경계 구간은 사람이 확정합니다.

> 정본: [`03_content_generation.md`](03_content_generation.md) · 라우터 상세 [`03a_l3_router_design.md`](03a_l3_router_design.md)

---

## §5. L4 교수학 엔진 — 핵심 차별화

**역할**: 학생 발화·상태에서 *교수학적 결정*을 내립니다. L3이 *생성*이라면 L4는 *결정*입니다("지금 Polya 어느 단계? 답을 어디까지 미룰까? 어떤 소크라테스 카테고리? 오개념 개입?"). "한국에서 이 계층을 제대로 만든 곳이 없다"가 차별화 근거입니다.

**핵심 엔티티**: `PedagogyDecision`이 중심으로, `polya_stage_to_advance`(stay/next/previous)·`hint_level`(1~4)·`socratic_category`·`prompt`·`recommended_cost_tier`·`ignited_concepts: list[IgnitedConcept]|None`(Polya 4단계에서만 채워짐)을 담습니다. `IgnitedConcept`는 `concept_node_id`+`ignition_strength`(primary/supporting/touched). 오개념 가설은 `MisconceptionHypothesis` 세트로 confidence 내림차순 정렬됩니다.

**핵심 설계 결정 ① 답 미루기 4단계 ↔ PRD graded hint 정렬**(MathScope PRD v1.1 흡수, 2026-05-14): 답 미루기 4단계(1.방향 → 2.의사코드 → 3.부분풀이 → 4.전체풀이)는 "가능한 가장 빠른 단계에서 멈춤"이 규칙입니다. PRD의 graded hint 3단계(1=은근, 3=거의 정답)를 1:1로 흡수하되(PRD1→방향, PRD2→의사코드, PRD3→부분풀이), **4단계(전체 풀이)는 PRD 척도 밖 WhyMath 고유 안전망**으로 한 칸 더 둡니다. 각 단계의 `reveals`를 기록해 *세션당 평균 노출량*을 KPI(답 미루기 도달 깊이, 목표 2.5+)로 추적합니다.

**핵심 설계 결정 ② 오개념 비낙인 ASSUMPTION 전환**(슬라이스 2026-06-19, 마이그레이션 0): 학생이 머무르며(stay/previous) 막혀 있고 명시 발화 신호가 없을 때, **고신뢰(confidence ≥ 0.65) + 최근(turns_since_evidence ≤ 2)** 활성 오개념 가설이 있으면 소크라테스 카테고리를 **ASSUMPTION**("왜 그렇게 가정했어?")으로 전환합니다. 오개념은 본질적으로 "틀린 전제를 참으로 가정"한 상태라 ASSUMPTION이 그 전제를 겨냥해 학생 스스로 표면화하게 합니다. 임계값 0.65는 가지치기선(0.1)보다 훨씬 높아 "표면화할 확신"을 보수적으로 요구하는 것이고, 가설이 없거나 저신뢰·stale면 동작이 완전히 불변이라 **맞게 푸는 학생에게 영향 0**입니다. 반환은 카테고리 enum뿐 — `misconception_id`·정답·"틀렸다"는 구조적으로 노출 불가(테스트 가드)입니다.

**핵심 설계 결정 ③ 5원칙과 정서 안전 톤 필터**: 답 미루기·소크라테스 우선·메타인지 명시화·다중 풀이 노출·정서 안전. 톤 필터는 금지 패턴("틀렸·못 하·잘못된·실수·바보·포기")을 거르고 권장 표현("흥미로운 시도네·거의 다 왔어·다른 각도로 봐볼까")으로 바꾸며, 오개념은 직접 교정 대신 반례 유도·구체 사례로 다룹니다. 소크라테스는 6카테고리(명료화·가정·근거·관점·함의·메타인지).

**경계**: L4는 판정자, L5는 표시자, L1은 그래프 원천 — L4는 개념 그래프를 구현하지 않고 "이번 풀이에서 이 노드가 켜졌다" 판정만 합니다. 답 미루기 척도 변환도 L4 내부 책임이고 L5는 "지금 1단계 힌트" 라벨만 표시합니다.

**현재 상태·리스크**: 🟢 최대 계층(62파일/~10.5k줄) — Polya·소크라테스·LTHC·오개념 진단/가설/판정(judge)/shadow harvest·톤 필터·메타인지 트리거. Phase 1 성공 기준은 소크라테스 카탈로그 50+·오개념 30개+개입·정서 필터 위반 0건·답 미루기 깊이 2.5+. **리스크**는 이 정교한 엔진이 실제 학생 앞에서 작동한 증거가 0건이라는 점(S1/S3에서 실증).

> 정본: [`04_pedagogy_engine.md`](04_pedagogy_engine.md)

---

## §6. L5 상호작용 — 유일한 접점

**역할**: 학생과 시스템의 *유일한 접점*입니다. 클라이언트 UI + FastAPI 서버(오케스트레이터)로 구성되며, 학생 메시지 1건은 `Mobile POST /chat → auth+session → L2 상태 → L1 컨텍스트 → L4 결정 → L3 생성 → L4 톤필터 → L2 갱신 → Mobile 표시 + Polya 갱신` 흐름을 탑니다.

**핵심 설계 결정 — 슬라이스 89의 4요소**: ① 독립 수학 코어(L1-L4·API로만 소비) ② 학생 클라이언트 = **Flutter 단일**(패드 중심 네이티브 태블릿 2D·View Layer만·패드+폰 한 코드·수학 로직 미포함) ③ 별도 웹 = React/Next(교사 대시보드·SEO·공유·Phase 3+) ④ 2개 국소 비상구 = MathLive(수식 입력)·three.js(3D) WebView. Flutter Web이 아니라 네이티브 태블릿(Impeller 2D)을 고른 이유는 굿노트형 저지연 손글씨 때문이고, 폰은 같은 코드로 동반하되 저사양 안드로이드가 미션 하한선입니다. 기술 스택은 Flutter 3.x+Riverpod / FastAPI+SQLAlchemy 2.0+asyncpg+alembic / Redis / Celery이며 성능 목표는 앱 시작·첫 토큰 <2초, API p50 <500ms입니다.

**선언적 시각화·음성화**: `Visualization`은 영상이 아니라 JSON 명세(4종: `interactive_graph_2d`·`interactive_surface_3d`·`simulation_probabilistic`·`animation_prerendered` — 앞 3종이 PRD 신규, 마지막만 기존 Manim 대응)로, 용량이 작고 버전 관리가 쉬우며 학생이 파라미터를 조작해 능동 탐구할 수 있고 언어 레이어만 교체하면 다국어가 됩니다. **수식 음성화**는 오디오 합성이 아니라 *LaTeX→모호성 없는 한국어 낭독 문자열 변환*이 본질이라, 코어가 `SpeechSpec`을 결정론 규칙엔진(LLM 0·환각 0·골든 코퍼스로 정확성 단언, `POST /v1/speech/latex`)으로 산출하고 클라는 합성만 합니다(미지 기호는 `unresolved_symbols`로 정직 노출). **단 현행(2026-08-11 실측) 클라 합성 경로는 0입니다** — `flutter_tts`가 Gradle 비호환으로 pubspec에서 제거돼, 이 축은 서버 완비·클라 미착지 상태입니다(재도입은 실기기 호환 재검증 선행).

**정서 안전 UI**: 게이미피케이션(정답률 랭킹·스트릭)을 금지하고, 학습경로 시각화·Polya 단계·답 미루기 단계("지금 1단계 힌트 받음")를 항상 화면에 명시해 메타인지를 강화합니다. `LearningScene` DSL이 답 미루기 상한·낙인 금지를 스키마 불변식으로 구조화합니다. 접근성은 대비 4.5:1·탭 영역 **48×48dp**(정본 단일값 — 실 게이트 `androidTapTargetGuideline` 기준, `docs/design/ui/06_design_system.md` §7)·TTS(클라 미착지)·색맹 친화, 보안은 HTTPS+certificate pinning·JWT·**14세 미만 부모 동의 미들웨어**·학생 PII 분리 암호화입니다.

**경계**: 자동 커리큘럼 정렬 *엔진*은 L1+L6이고 L5는 입력 화면·출력 화면만 담당합니다. 온보딩(국가→학년→학교→교과서→진도→목표, 3분 무마찰)이 모은 데이터는 L2 `StudentProfile`로 넘어가고, 메인 화면의 교과서 좌표 문자열("미래엔 수학II · p.156~162 / 도함수의 정의")은 정렬 엔진이 만들어 내려주며 L5는 렌더링만 합니다.

**현재 상태·리스크**: 🟡 골격 실동작 — Flutter 앱 30 dart/화면 9개(auth/chat/ocr/onboarding)·백엔드 OCR(콴다식 4단계 파이프라인·`POST /v1/ocr`)·WebView 그래핑 계산기. **핵심 리스크**는 온보딩→진단→문제→풀이입력→코칭→검증의 **E2E 학습 루프가 한 번도 연결된 적 없다**는 것 — S1의 정확한 목표입니다.

> 정본: [`05_interaction.md`](05_interaction.md)

---

## §7. L6 응용 모드 — 하나의 코어, 여러 진입점

**역할**: 같은 7계층 코어 위에 *시장별 진입점*만 다르게 얹어, 단일 코드베이스로 7개 모드를 유지합니다.

**핵심 엔티티**: `ApplicationMode` enum 7값(SCHOOL_PROGRESS·EXAM_PREP·THINKING·METACOGNITION·GIFTED·FREE_SEMESTER·CODING_DOJO)과 `ModeConfig`(`content_filter`·`polya_emphasis` 0~1·`metacog_freq`·`gamification_level` 0~3·`default_cost_tier`·`daily_cost_limit_won`·`ui_layout`). 7개 모드는 사고력·심화와 메타인지 코칭이 **Phase 1 진입점**, 학교진도·수능내신이 Phase 2, 영재(월 49,900원)가 Phase 3, 자유학기제·디버깅 도장이 Phase 3~4+입니다. 가격 모델은 무료/보급 9,900/프리미엄 29,900/영재 49,900원.

**핵심 설계 결정 ① 3개 앱 분리 반려**: PRD v1.1은 학생·교사·학부모 3개 별도 앱을 제안했으나 반려하고 **Flutter 단일 앱 + 모드 분기**로 갔습니다(교사 대시보드만 별도 웹, Phase 3+). 근거는 ① 4~5명 팀이 3앱 동시 개발은 범위 폭발 ② 코어가 이미 단일 코드베이스 모드 분기라 역할 분기도 같은 패턴으로 흡수 ③ 코어 상태(BKT·오개념·`MasteryState`)를 학생·교사·학부모가 *같은 데이터 다른 뷰*로 보므로 앱을 나누면 동기화 비용만 증가 ④ 의사결정 우선순위상 개발 속도(7번)보다 학습 효과(4번)·UX(5번)가 우선인데 3앱 분리는 어느 가치도 안 주면서 부담만 키웁니다.

**핵심 설계 결정 ② 모드 × 자동 정렬 직교**: 자동 커리큘럼 정렬 7차원(활성 개념 풀·표기·깊이·풀이 스타일 순서·용어·인접 개념 순서·평가 형식)은 모드 레이어 *위*에 얹혀 어느 모드든 항상 동작합니다. 모드가 콘텐츠 풀·교수학 가중치를 정하고 정렬이 그 위에서 학생 교과서 좌표를 조정하되, 모드를 바꿔도 코어 상태·정렬은 일관 유지됩니다(곱집합). 현재 차원 3(깊이)만 학교진도 모드에 1차 배선됐는데, 이는 *적격성 게이트가 아니라* 우선순위 보너스(≤1.5)라 깊이 불일치로 문제가 탈락하지 않습니다(read-time resolver `CurriculumDepthResolver`가 단일 SELECT로 N+1 0).

**경계**: L6은 L1을 호출해 매핑 데이터를 받고 L2 프로필을 읽어 조정할 뿐 데이터·모델을 구현하지 않습니다(순수 깊이정렬 `l6/school_progress/gating.py`, 결선은 L5 `api/gating.py`).

**현재 상태·리스크**: 🟡 게이팅만 — 6개 모드 각 `gating.py` 1개뿐이라 **wedge인 수능 모드조차 본격 엔진이 없습니다**. 코어가 아무리 좋아도 학생이 실제로 만나는 건 L6이라 리스크가 큽니다 — S3에서 수능 모드 본격 엔진(시그니처 경로·킬러 단계 진입·모의 채점)을 구현합니다.

> 정본: [`06_application_modes.md`](06_application_modes.md)

---

## §8. L7 커뮤니티·소셜 — 안전선이 기능을 지배

**역할**: 학생·학부모·교사를 잇는 *사회적 학습* 인프라입니다. 느리지만 "데이터 누적→모델 개선→콘텐츠 풍부" 선순환의 결정적 자산입니다. 서비스 인터페이스 `L7CommunityService`는 다중 풀이 갤러리·Live Problem 제출·학부모 보고서·교사 대시보드 4개 컴포넌트를 노출합니다.

**핵심 설계 결정 — 안전선이 기능 정의를 지배**: **다중 풀이 갤러리**는 *본인 풀이 완료 후에만* 타 학생 익명 풀이를 열람하게 하고 다양성을 우선(같은 접근 중복 최소)하며 "최고 풀이" 랭킹을 금지합니다. **Live Problems**(NRICH 모델)는 주 1회 신규·익명 제출·마감 후 큐레이션 공개. **학부모 보고서**는 주 1회 opt-in 푸시로 비교·랭킹 없이 약점·강점·메타인지 순간·5분 대화 주제만 담고 L4 톤 필터를 적용합니다. 자동 채점(학생 손글씨 → L5 OCR → L3 PRM 단계 검증)도 정답/오답 이분법이 아니라 *어느 단계에서 막혔는지*까지 교사에게 전달합니다. 학생 데이터 노출 안전선은 명확합니다 — ❌ 이름·학교 표시, ❌ 본인 풀이 전 타 풀이 노출, ❌ 랭킹, ✅ 익명·집계만.

**경계**: 교사·학부모 기능도 수학 로직은 독립 코어(L1-L4) API로만 소비합니다. 학부모 보고서는 학생앱 내 역할별 UI(L6 모드 분기와 같은 메커니즘), 교사 대시보드는 별도 웹(React/Next, Phase 3+ B2B).

**현재 상태·리스크**: ⚪ 코드 0 — 문서만 존재하며 Phase 3+로 의도적 보류. **리스크가 아니라 의도된 순서**입니다: Phase 1~2는 학생 경험(L5 루프·L6 수능)에 집중하고, L7은 데이터·사용자가 쌓인 뒤 착수합니다.

> 정본: [`07_community.md`](07_community.md)

---

## §9. 하네스 — LLM 호출 방식을 바꾸는 횡단 인프라

**역할**: 하네스는 새 계층이 아니라 **L3·L4의 LLM 호출 *방식*을 바꾸는 횡단 인프라**입니다. "모델 크기보다 환경(검증기+상태관리+탐색)이 능력을 결정한다"(rStar-Math: MATH 58.8%→90.0%, AlphaProof: IMO 은메달)가 근거입니다.

**WH-1 튜터링 하네스 (온라인)**: 오개념 가설·증거를 프롬프트가 아니라 DB로 외부화하고, LLM은 매 턴 "다음 교수학적 행동"만 판단합니다. 상태 저장소는 3층 — ① Redis 세션 작업 메모리(문제 ID·풀이 단계 스택·Polya 단계·힌트 레벨·verify 캐시) ② **활성 오개념 가설 세트**(최대 5개 강제, 확증편향 방지 3규칙: 시간 감쇠 ×0.85/3턴·ε-탐색 강제 5턴마다 1회·반박증거 우선 기록) ③ PostgreSQL `evidence_links` 증거 그래프(polarity ±1·weight·retention_until, `net_support`=Σ(polarity×weight)). 도구는 **기본 8종**(read_student_state·**verify_step**(correct/incorrect/unverifiable 3상태)·match_misconception·curate_hypothesis·query_curriculum·select_probe·log_evidence·**end_turn**)에 전략 3종(log_strategy_event·elicit_prediction 세션당 최대 2회·assign_transfer_probe)을 더합니다. 핵심 설계는 **end_turn만이 학생에게 말할 수 있다**(중간 도구는 전부 내부 동작)입니다.

**WH-S 솔버 하네스 (오프라인 배치)**: 시스템 자체 풀이력을 자기진화 루프로 상승시킵니다. 도구 8종(parse_problem·retrieve_similar·decompose·apply_strategy·verify·conjecture_check·log_lemma/deadend·finalize)에 강제 불변식(verify 없는 finalize 거부·failed 미적재·unverifiable→unverified 격리·max_tool_calls=32)을 겁니다. 상태 저장소 4종(풀이 트리 `solution_nodes`·검증 보조정리 `verified_lemmas` 멱등 UNIQUE·실패 로그 `dead_end_log`·검증 풀이 저장소 `verified_solutions`)은 전부 스키마 구현됐습니다. **자기진화 루프**(STaR/rStar-Math 레시피, 검증기가 사람 라벨러를 대체)는 라운드당 검증 풀이 1,000~2,000개를 목표로 문제 풀 구성→N회 MCTS 탐색→검증 통과 풀이만 SFT→난이도 상향(교과 기본→수능 준킬러→킬러→KMO 1·2차)을 돕니다.

**3-Tier 검증기 스택**(WH-S의 심장): **Tier1 수치**(랜덤+경계값 검산, 커버리지 최광·신뢰도 최저, 단독 사용 금지)·**Tier2 SymPy 기호**(주력, 모든 변형 엣지에 적용해 과정 보장)·**Tier3 Lean4+Mathlib**(형식, 신뢰도 최고, 전제 난제=자동형식화라 장기 보류). 최종 판정 = Tier1 AND 모든 단계 Tier2(증명은 +Tier3). **verified/unverified/failed 3등급**으로 보상 해킹을 차단합니다 — failed(Tier1 fail 또는 단계 incorrect)는 차단, unverified(판정 불가)는 **학습 데이터에서 절대 배제**(get_verified 1차 필터 + SFT 변환 2차 강제, `excluded_unverified`로 정직 집계).

**도입 단계화 — "측정 없는 도입 없음"**: WH-1은 v0.2 제1원칙으로 **0단계(대리지표 7종 계측·Langfuse·베이스라인)**를 신설하고, 모든 단계 진입을 베이스라인 대비 개선으로 게이팅합니다(1단계 2도구 삽입 → 2단계 가설 세트 → 3단계 전체 루프·Haiku → 4단계 Qwen3 섀도·전환). 대리지표 7종(verify 통과율·진단-실제 일치율·세션 완주율·턴당 토큰·도움 감소 기울기·Brier 보정 점수·전이 점수)은 이미 계측되며 **날조 0**(미계측은 value=None + status). 정직한 강등도 명시적입니다 — **비용 절감·자체 모델 학습을 "확정 효과"에서 "검증 필요 가설"로 강등**했고(보상 신호 부재가 근본 장벽), 하네스 1차 가치는 ① 설명 가능한 진단 ② 긴 세션 품질 ③ 구조적 검증(비용 절감 아님)입니다. 반면 **WH-S는 보상이 객관적(검증기=보상)이라 자기진화를 즉시 가동**할 수 있어 WH-1의 최대 리스크(보상 신호 부재)가 존재하지 않습니다.

**현재 상태**: 둘 다 🟡 골격 — 상태 저장소 스키마·평가 하네스는 구현, LLM 정책 구동은 후속. (수치 주의: 설계 문서의 "545노드·400 오개념"은 목표 추정치이고 현재 실측은 원자 백본 1,837·오개념 839입니다.)

> 정본: [`04a_wh1_tutoring_harness.md`](04a_wh1_tutoring_harness.md) · [`03b_wh_s_solver_harness.md`](03b_wh_s_solver_harness.md)

---

## §10. 코딩 완성 단계 S0~S5 — 게이트가 기간에 우선

**역할**: 사업 페이즈(Phase)와 별개로, 코드를 *어떤 순서로 완성하는가*를 정의하는 실제 작업 로드맵입니다. 각 단계는 **진입 게이트 → 완료 정의(DoD) → 탈출 게이트**를 가지며, 미달 시 다음 단계로 강행하지 않습니다.

| 단계 | 기간 | 탈출 게이트(요지) |
|---|---|---|
| **S0 정합성 회복** ✅ | ~2주 | 개념/원자/스킬 각각 truth source 정확히 1개를 거버넌스 테스트가 증명 + 4게이트+lint-imports green |
| **S1 E2E 수직 슬라이스** 🔄 | ~6주 | ① 실기기 1루프 15분 내 완주 시연 녹화 ② 루프당 LLM 비용 실측 ③ "학생 응답은 전부 PRM/도구 검증 통과 후"가 코드 경로로 증명 |
| **S2 콘텐츠 공장** 🔄 | ~8주 | ① SymPy/PRM/검수 반려율 3지표 대시보드 ② 검수자 샘플 30문 완료 ③ 저작권 게이트(평가원 본문 유사도) |
| **S3 파일럿** | ~8주 | ① KPI 베이스라인 실측 ② 재사용 의향 ≥60% ③ 세션당 비용 손익 범위 내 |
| **S4 K-12 완성** | ~12주 | ① 고교 전 단원 S1 루프 통과 ② 커리큘럼 정렬 검정교과서 3종+ ③ 단원 커버리지 100%(고교) |
| **S5 확장 게이트** | 판정 | S4 전부 + 파일럿 KPI 2분기 유지 + physics 네임스페이스 스키마 변경 0 + 검증기 plugin 슬롯 실증 |

**S1**의 1루프는 온보딩→CAT 진단(웜스타트)→수능 미적분 동등문제 1문→풀이 입력(MathLive/OCR)→WH-1 도구 루프 코칭→3-tier 검증 응답을 Flutter 앱에서 끝까지 잇고, Minimal Reasoning Subgraph 예산(depth≤2·nodes≤12~20·tokens≤3000)을 context builder에 상한으로 배선하는 것이 포함됩니다. **S2**는 동등문제 생성(SymPy 동치 게이트→PRM→검수 큐, 검증 통과 100문+)과 WH-S 솔버 가동이 핵심입니다.

**확장 대비 불변식 4종**: 모든 단계에 과목 중립 원칙이 걸립니다 — ① **루프 과목 중립**(S1: `if subject=="math"` 금지, 과목 의존은 L1 데이터·프롬프트에만) ② **검증기 plugin**(S2: SymPy는 "수학 커널 plugin"이지 파이프라인 본체 아님, 물리는 단위·차원 검증기) ③ **지표 중립**(S3: 오개념 해소율·답 미루기 깊이는 물리도 동일) ④ **커리큘럼 오버레이**(S4: 개념 영속·매핑만 교체). S5에서 위반을 전수 감사·상환합니다.

**현재 위치**: S1 마무리 + S2 병행. 무게중심이 *설계 정본화 → 수직 슬라이스 실증*으로 이동한 국면입니다.

> 정본: [`../strategy/status_roadmap_2026-07.md`](../strategy/status_roadmap_2026-07.md) · 페이즈는 [`../../ROADMAP.md`](../../ROADMAP.md)

---

## §11. 데이터·법적 전략 — 나중에 못 고치는 리스크의 선제 차단

**역할**: 콘텐츠 백본을 *법적 안전조합*만으로 구성해, 사후에 교정 불가능한 저작권·개인정보 리스크를 원천 차단합니다. 등급 체계는 A+/A/A-(사용) vs B(SA)/C(NC)/D(독점)/E(위험)이고, **실제 수집 백본 = A-/A/A+ 21종 약 4M 레코드, B/C/D/E 0건**(EBS·평가원·검정교과서 미포함)입니다.

**핵심 설계 결정 ① 저작권 가이드 v2.0**: 저작권법 §32(시험문제 복제)는 단서 "영리 목적 제외"가 있어 상업 앱 WhyMath에 적용 불가하고, 무단 복제는 §136(권리침해죄)·§140(영리·상습 비친고죄)·§125-2(법정손해배상 1건당 최대 5천만 원) 리스크가 있습니다(2024.8 대법원 KICE 판결로 보강). 따라서 EBS·평가원·검정교과서는 *구조 메타데이터(단원·코드·문항번호)만* 보유하고 **자체 생성 동등문제로 본문을 대체**합니다 — `l3/pregenerate` 빌드타임 사전생성 + SymPy 산술 검증 게이트(거짓 등식 시드 탈락) + PRM/사람 검수, 킬러 30번 포함.

**핵심 설계 결정 ② redaction 삼중 방어**: ① L1 코퍼스 validator(`_enforce_copyright_no_body_for_metadata_sources`)가 제한 출처의 question_text·answer_explanation·choices·conditions를 NULL 강제 ② export 경계 게이트(`_body_license_clean`)가 SFT export 시 본문 3필드를 독립 2차 방어(validator 갭에도 누출 0) ③ 데이터셋 카드 차원 redaction(성취기준 코드로만 다리). OCR도 AGPL-3.0(ultralytics)를 코드에서 이중 차단하고 Apache 계열(rapid-layout·Qwen3-VL)만 씁니다.

**핵심 설계 결정 ③ SA 전염 회피**: CC BY-SA 자료(AoPS·LibreTexts·Wikipedia·StackExchange)를 AI 학습에 직접 쓰면 모델 가중치를 SA로 공개해야 한다는 해석 위험이 있어(SaaS 붕괴), Feist 판례·대법원 2000다61664("사실은 저작권 보호 대상 아님")에 근거해 수학적 사실·구조만 추출하고 표현은 자체 생성합니다. Khan Academy(CC BY-NC-SA = NC+SA 이중독성)는 완전 격리합니다.

**현재 상태·리스크**: 위험 소스 0건, NCIC 본문 redaction 삼중 방어 가동. 자체 저작 자산(원자 백본 1,837·오개념 839·자체문항 4,030·대학 성취기준 409)은 redaction 불요. **리스크**는 전 조합이 "변호사 최종 검토 전제"라는 점 — 법률 검토는 코드로 대체할 수 없는 사람 게이트입니다.

> 정본: [`../data/licensing_safety.md`](../data/licensing_safety.md) · 원문 [`../legal/copyright_guide_v2.md`](../legal/copyright_guide_v2.md)

---

## §12. 리스크·병목 — 지금 가장 큰 위험은 검증 부채

종합 판정은 **"코어는 과잉 성숙, 제품 루프는 미성숙"**입니다. L1–L4와 품질 인프라(테스트>소스·import-linter·MATH DSL invariant 12종)는 Phase 1 요구를 초과했지만, 학생이 실제로 겪는 경험(L5 루프·L6 수능)은 골격입니다. 지금 가장 큰 리스크는 기술 부채가 아니라 **검증 부채** — 이 코어가 실제 고3의 30번 문제 앞에서 작동한다는 증거가 0건입니다.

**병목 Top 5**: ① 이중 truth source(437 개념 vs 1,837 원자, S0에서 해소) ② Phaiakes9 라이브 검증 정체 ③ E2E 루프 부재(S1) ④ 도메인 파트너 부재(M1.3 게이트) ⑤ L6 수능 모드 얇음. 보조 병목으로 ⑥ 정본화 국면 장기화(S0 완료를 종료 선언으로 사용) ⑦ 커버리지 하니스·orphan ⑧ Neo4j 미도입(의도적·pgvector 단일 평면)이 있습니다.

**결정적 사실 — 사람 병목 2건**: Top 5 중 **② Phaiakes9 라이브 키 발급·실머신 검증**과 **④ 수학 교육 도메인 파트너 확보**는 AI가 못 푸는 사람 병목이라 크리티컬 패스에 있습니다. ①③⑤는 AI 자동화가 가능하므로, Kiki의 수동 시간을 ②④에 우선 배정하는 것이 전체 일정을 결정합니다. 완화 방향은 신규 설계 검토를 실증(S1)에서 발견된 문제로만 착수하고(정본화 종료), AI는 측정 스크립트·대시보드를 선제 준비해 사람 병목의 대기 시간을 최소화하는 것입니다.

> 정본: [`../strategy/status_roadmap_2026-07.md`](../strategy/status_roadmap_2026-07.md) §2·§4

---

## §13. 정본 인덱스

| 영역 | 정본 문서 |
|---|---|
| 용어 한 줄 정의 | [`glossary.md`](glossary.md) |
| 7계층 개요·경계 | [`00_overview.md`](00_overview.md) |
| 계층 상세 (L1~L7) | `01_data_foundation.md` ~ `07_community.md` |
| L3 라우터 설계 | [`03a_l3_router_design.md`](03a_l3_router_design.md) |
| 하네스 (WH-S·WH-1) | [`03b_wh_s_solver_harness.md`](03b_wh_s_solver_harness.md) · [`04a_wh1_tutoring_harness.md`](04a_wh1_tutoring_harness.md) |
| 코딩 완성 단계(S0~S5)·병목 | [`../strategy/status_roadmap_2026-07.md`](../strategy/status_roadmap_2026-07.md) |
| 사업 페이즈(Phase)·마일스톤 | [`../../ROADMAP.md`](../../ROADMAP.md) |
| 프로젝트 정체성·금기·구조 원칙 | [`../../CLAUDE.md`](../../CLAUDE.md) |
| 결정 로그·현재 상태 | [`../../MEMORY.md`](../../MEMORY.md) |
| 데이터 라이선스·저작권 | [`../data/licensing_safety.md`](../data/licensing_safety.md) · [`../legal/copyright_guide_v2.md`](../legal/copyright_guide_v2.md) |

---

**버전**: 0.2.0 | **최종 수정**: 2026-07-06 (영역별 심화 확장 — 엔티티·데이터흐름·게이트·구체 수치 반영)
**다음 검토**: S1 탈출 게이트 판정 시 (실증 발견으로 각 영역 현재 상태·리스크 갱신)
