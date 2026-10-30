# WhyMath LearningScene DSL(학습 장면 합성 명세) 설계안 v0.1

> **목적**: 개념 노드(L1) + 학습자 상태(L2) + 오개념·Polya(L4)로부터 *학습 화면 한 장*을
> **선언적 합성 명세(JSON/AST)**로 생성하고, 클라이언트(L5)가 그 명세를 *렌더*하는
> 계층을 정의한다. 기존 `Visualization` 엔티티(단일 시각화·`05_interaction.md §5.2`)
> **위에** 다요소 합성층을 얹어, "개념 → UI 자동 생성"을 *우리 교수학 원칙 안에서* 실현한다.
>
> **정본 상위 문서**: `05_interaction.md`(L5 상호작용·선언적 시각화). 본 DSL은 그 합성 계층.
> **자매 문서**: WH-1 튜터링 하네스(`04a`)·WH-S 솔버 하네스(`03b`) — 본 DSL은 두 하네스의
> 산출물(검증 풀이·오개념 가설)을 *장면 요소로 소비*하는 표현 계층이다.
>
> 작성일: 2026-06-14 | 버전: 0.1 (설계만 — 구현 0·마이그레이션 0)

> **동기 (외부 문서 2종, 2026-06-14)**: Kiki가 "수학교육앱 인터페이스 설계 자동화"
> 문서(DOCX·PDF)를 검토 요청했다. 문서의 골자 — *성취기준/개념 DB → Semantic AST →
> **Math UI DSL** → UI Generator → Flutter/Web*, "화면을 만들지 말고 수학 구조를 만들어라",
> 종착점 **Math Knowledge Runtime** — 은 CLAUDE.md 슬라이스 89(**표현 ≠ 의미**)와
> L1–L4 독립 수학 코어 원칙의 재진술이다. 즉 *방향 전환이 아니라 우리 베팅의 외부 검증*이며,
> 본 설계안은 문서가 지목한 "비어있는 한 좌석"(합성 UI DSL)을 우리 자산 위에 못박는다.

-----

## 0. 한 줄 요약

**`Visualization`(단일 시각화 명세)은 이미 있다. 부족한 것은 그 위에서 그래프·슬라이더·
풀이 단계·오개념 프로브·소크라테스 발화를 *한 장면으로 조립*하는 선언적 합성 계층이다.**
`LearningScene`은 개념 노드의 의미 메타데이터(`recommended_visual_styles`·`common_misconceptions`·
`cognitive_type`)에서 **결정론적 골격**을 만들고, L3가 각 요소의 `spec`만 채워(검증 게이트 통과),
L5가 *수학 로직 없이* 렌더한다.

외부 문서의 범용 DSL을 **그대로 쓰지 않는다**: 문서 예시의 `misconception → warning_overlay
(붉은 강조·AI 피드백 자동생성)`은 CLAUDE.md 금기(즉답·낙인·거짓 "틀렸다")에 정면 충돌한다.
본 DSL은 **답 미루기·낙인 금지·검증 게이트를 스키마 불변식으로 구조화**하여, 의사결정 우선순위
(1.학생 안전·웰빙 > 2.법·윤리 > 3.교수학 정확성)를 표현 계층에 강제한다.

-----

## 1. 7계층 아키텍처 내 위치

새 계층이 **아니다.** L3(콘텐츠 생성·검증)가 장면 명세를 *생성·검증*하고, L5(상호작용)가
*렌더·조작 처리*하는, `05_interaction.md §5.2`의 자연 확장이다. 상위→하위 호출 원칙 유지.

```
[입력]  개념 노드(L1) + 학습자 상태 스냅샷(L2) + 오개념·Polya 결정(L4)
   ↓
[L3]   generate_learning_scene
        ① 결정론적 골격 (개념 메타 → 어떤 요소 kind를 둘지)
        ② 요소별 spec 충전 (generate_visualization_spec 재사용·라우터·Langfuse)
        ③ parse_learning_scene 검증 게이트 (참조 무결성·불변식)
   ↓
[명세]  LearningScene (구조/JSON·AST — 화면 픽셀 아님·코어 저장)
   ↓
[L5]   SceneRenderer 레지스트리 (kind → 위젯/WebView·수학 로직 0)
```

**핵심 차이(슬라이스 89 재확인)**: 화면은 코어의 산출물이 아니라 *명세의 렌더 결과*다.
같은 `LearningScene`이 Flutter·웹·PDF·AI 설명에서 각자 렌더된다(표현≠의미).

-----

## 2. 동기 — 외부 문서를 *교정해* 수용하는 이유

| 외부 문서 제안 | 그대로 쓰면 위반하는 우리 원칙 | 본 설계의 교정 |
|---|---|---|
| `misconception:{trigger_ui:"warning_overlay"}` → 붉은 강조·AI 피드백 자동 | CLAUDE.md 금기 ①막혔을 때 즉답 ②부정 피드백 정서강화 ③거짓 "틀렸다" | `misconception_probe`에 **정답·수정 필드 부재**(구조적 차단)·소크라테스/반례 *유도*만 |
| `steps:true` → 단계 풀이 노출 | 답 미루기(Polya 4단계·힌트 1~4) | `step_panel.reveal_policy="deferred"`·`answer_deferral_max_level` 상한 |
| LLM이 scene 자유 생성 | LLM 응답 무검증 학생 노출 금지(PRM/도구 검증) | `parse_learning_scene` 검증 게이트(참조 무결성·불변식) 후에만 노출 |
| "graph/slider/proof 위젯을 만들라" | 신규 엔진 양산·중복 | 기존 `Visualization`·`SolutionPath`·오개념 카탈로그·`InterventionPattern` **참조 조립** |

→ 본 DSL의 가치는 "DSL을 추가"가 아니라 **교수학 안전성을 표현 계층에 불변식으로 박는 것**이다.

-----

## 3. 핵심 스키마 (Pydantic 계약 — S2 구현)

`schema/visualization.py`의 관례(`ConfigDict(extra="forbid", use_enum_values=True)`·
`@model_validator(mode="after")` 불변식·UUID PK)를 답습한다.

### 3.1 `LearningScene`

```
LearningScene
  scene_id: UUID
  concept_id: str             # 개념그래프 code(UC) — 이 장면이 가르치는 개념(L1 참조)
  topic_label: str | None     # 다국어 캡션(표현 레이어·라벨만 교체)
  layout: SceneLayout         # {single|vertical_stack|two_panel|tabbed} 선언적 배치 힌트(픽셀 아님)
  answer_deferral_max_level: int        # 1..4 — 장면이 허용하는 최대 힌트 단계(답 미루기 상한)
  learner_context: SceneLearnerContext | None  # 생성시점 스냅샷(읽기전용·판정 아님)
  elements: list[SceneElement]          # 합성 요소(순서 = 렌더/레이아웃 순서)
```

`SceneLearnerContext`(선택): `mastery_level`(L2 BKT 숙달레벨)·`active_hypothesis_ids: list[str]`
(WH-1 활성 오개념 가설 id·`misconception_hypothesis` 테이블)·`theta`(IRT 능력). **스냅샷이며
판정이 아니다** — 장면 적응의 *입력*일 뿐, "틀렸다" 단정 근거가 아니다.

### 3.2 `SceneElement` — `kind` 판별 유니온

각 요소는 *기존 좌석을 참조*한다(신규 콘텐츠 엔진 0):

| `kind` | 참조 좌석 | 핵심 필드 | 교수학 가드 |
|---|---|---|---|
| `visualization` | `Visualization`(기존 엔티티) | `ref: Visualization` | 검증 상속 |
| `param_control` | `Visualization.spec` 파라미터 | `targets:[str]`·`bound_visualization_index`·range/step | 슬라이더 대상이 bound viz에 존재해야 |
| `step_panel` | `SolutionPath.steps`(`solution_path.schema.yaml`) | `solution_path_id`·`reveal_policy="deferred"` | 점층 노출(답 미루기) |
| `misconception_probe` | 오개념 카탈로그 30종·`InterventionPattern` | `misconception_id`·`intervention` | **정답·수정 필드 없음** |
| `socratic_prompt` | `PedagogyDecision`(L4) | `socratic_category`·`polya_stage`·`hint_level`·`prompt_text` | `hint_level ≤ max_level` |
| `annotation` | overlay | `target_element_index`·`highlight_spec` | 강조·라벨만 |
| `skill_focus` | `BehaviorArea`(정본 행동영역·#418·S5k) | `behavior_area`·`focus_prompt` | **정답·수정 필드 없음**(행동 지시·질문 아님) |
| `tutoring_prompt` | `adapt_lthc`(L4 LTHC·`mastery_to_level`·S5l) | `role`(entry/scaffold/extension)·`prompt_text` | **정답·hint_level 필드 없음**(지원 발화·판정 아님) |

`skill_focus`는 관점 문서 **SkillBlock**의 선언적 형태(조건 강조) — 주 행동영역(`BehaviorArea`·정본
6종·#418)이 있으면 그 행동영역의 focus cue를 자동 부여(미매핑=미부여·블록 유무를 행동영역별로 분기).
행동영역은 L5 `get_behavior_areas`가 concept→skill 조인(`concept_node.behavior_skills`→`skill_node
.behavior_area`·#419)으로 해소해 주입한다. interactive 경우분할 트리는 WH-S Tier3 종속(초기 scope 제외).

`tutoring_prompt`는 관점 문서 **TutoringBlock**의 *학생적응* 축(S5l) — `learner_context.mastery_level`
(L2 BKT)을 `mastery_to_level`(0.4/0.8→초보/발전중/숙달)로 밴딩하고 주 Polya 단계와 함께 `adapt_lthc`
정본 발화를 진입점/비계/확장 3축으로 받아 각 축 1개(attention 보호)를 낸다(초보=진입+비계·숙달=확장·
발전중=균형). mastery 신호가 없으면 미방출(없는 신호로 비계 날조 금지·낙인 회피). 학생적응을 *반증된
학습양식(modality)이 아니라 mastery*로 닫은 것이 핵심(설명 스타일 modality 축은 의도적 미배선).

`intervention`은 L4 `InterventionPattern` 4종(`COUNTEREXAMPLE` 반례·`CONCRETE_CASE` 구체사례·
`VISUALIZATION` 시각화·`REVERSE_REASONING` 거꾸로) 중 하나 — *수정법이 아니라 사고 유도*다.

-----

## 4. 검증 게이트 `parse_learning_scene()` (S2)

`l3/visualization.py::parse_visualization_spec`(LLM 원시출력 → 검증된 명세만 반환) 패턴 답습.
통과 못 하면 학생 미노출(`InvalidLearningSceneError` → 422).

1. **참조 무결성**
   - `concept_id` ∈ 개념그래프(<!-- fact:concept_graph.concepts -->437<!-- /fact --> UC)
   - `misconception_id` ∈ 오개념 카탈로그(`l4/misconception/catalog.py` 30종)
   - `param_control.targets` ⊆ bound `Visualization.spec`의 파라미터 키
   - `bound_visualization_index` 가 `elements` 범위 내 `visualization` 요소를 가리킴
2. **답 미루기 불변식** (CLAUDE.md 답 미루기)
   - 모든 `socratic_prompt.hint_level ≤ answer_deferral_max_level`
   - `misconception_probe`·`step_panel`은 정답/수정 텍스트를 *담는 필드가 없음*(스키마 차원 차단)
3. **정확성 불변식** (CLAUDE.md 정확성 #1·낙인 금지)
   - `misconception_probe`는 가설·소크라테스 트리거이지 판정 아님
   - 학습자 맞춤 프로브는 `learner_context.active_hypothesis_ids`에 근거가 있을 때만(임의 낙인 차단)
4. **redaction**: 명세는 개념 의미·구조만 — 교과서 본문·평가원 문항 본문 0(슬라이스 89·저작권 가이드 v2.0)

-----

## 5. L3 생성 — 개념 노드 → 장면 (S3)

> **★배치 정정(S3 구현 2026-06-14)**: 본 절은 생성기를 *L3*로 표기하나, S2가 `LearningScene`을
> **L4**에 배치(schema는 L레이어 import 0 → 역방향 회피)했으므로 생성기가 L3에 있으면 `LearningScene`
> (L4)을 import해 역방향 의존 위반이 된다. 따라서 `generate_learning_scene`은 **L4**(`l4/scene_generation.py`)에
> 두고 L3 `generate_visualization_spec`을 *다운콜*한다(L4→L3 `LLMSeam` 방향). "생성"이라는 *역할*은
> L3적이나 *배치*는 LearningScene과 같은 L4여야 계층 규칙을 지킨다. 또한 개념의 `common_misconceptions`는
> *자유서술*(정답/수정 텍스트·카탈로그 id 아님)이라 프로브 근거로 쓰지 않고, 프로브는 **활성 가설
> (`active_hypothesis_ids`) ∩ 오개념 카탈로그**에서만 생성한다(RS2 거짓 낙인 차단).

문서의 "무엇을 배울 것인가? → 어떤 UI" 를 *LLM 자유 추측이 아니라 개념 메타 기반 결정론*으로 구현.

1. **결정론적 골격** — 개념(`schema/concept.py`)의 구조 필드에서 요소 kind를 코드가 결정:
   - `recommended_visual_styles`(16종·예: 함수그래프 → `visualization`+`param_control`, 단위원 → `visualization`)
   - `common_misconceptions` → `misconception_probe` 후보(학습자 가설과 교차)
   - **직교 2축**(**구현됨·S5i→S5k 재정렬**): ① `cognitive_type`(개념 성격) → 소크라테스 프레이밍
     (`_COGNITIVE_SOCRATIC_MAP`). ② **`BehaviorArea`(정본 행동영역 6종·#418)** → **인지 진입 순서**
     (`_LEAD_BY_BEHAVIOR`·visual=시각화 먼저·inquiry=질문 먼저) + `skill_focus` 블록. 행동영역은
     `get_behavior_areas`가 concept→skill 조인으로 해소·주입(미매핑=중립). S5i는 축을 CognitiveType으로
     근사했으나 #418 정본 `BehaviorArea` 채택 후 S5k로 재정렬(단일 진실원천). Part 7 재검토 상환.
2. **요소별 `spec` 충전** — `visualization` 요소의 `spec`만 `l3/visualization.py::generate_visualization_spec`
   재사용(라우터 경유·Langfuse 추적·응답 캐싱·로컬 LLM 우선 — CLAUDE.md). 골격·참조는 코드가 채움.
3. **적응** — `learner_context`에 활성 오개념 가설이 있으면 해당 `misconception_probe`를 골격에 삽입(중기).
   **학습자모델 축(S5l)**: `mastery_level`(BKT)이 있으면 `mastery_to_level`→`adapt_lthc`(진입/비계/확장)를
   `tutoring_prompt`로 삽입(`_lthc_prompts`·lead 분기 뒤·프로브 앞·축당 1개 캡·mastery 없으면 미방출).

-----

## 6. L5 렌더러 레지스트리 (S4)

문서의 "UI Generator: Math DSL → Flutter Widget Tree"에 해당. 렌더러는 **dumb**(수학 로직 0,
명세 → 위젯만). 현 클라이언트가 이미 coach 응답을 declarative 렌더하는 패턴의 확장이다
(`src/mobile/lib/features/chat/presentation/chat_screen.dart`·`coach_signal_card.dart`).

| `kind` | 렌더러 |
|---|---|
| `visualization` | WebView 국소 비상구 — D3/Plotly/Desmos(2D)·three.js(3D)·Manim(prerendered) |
| `param_control` | 네이티브 슬라이더 → bound viz에 값 push(WebView postMessage) |
| `step_panel` | 네이티브 점층 패널(reveal_policy="deferred") |
| `misconception_probe` | overlay — 코칭 발화 카드(**정답 없음**·반례/시각화 유도) |
| `socratic_prompt` | 대화 버블(기존 `_MessageBubble` 재사용) |
| `annotation` | overlay 강조/라벨 |
| `skill_focus` | 행동 focus 카드(`_SceneRow`·flag 아이콘·**정답 없음**·행동 지시 cue만) |
| `tutoring_prompt` | LTHC 튜터링 행(`_TutoringRow`·역할 배지 진입점/비계/확장·**정답 없음**·지원 발화만) |

`coach_models.dart`에 `Visualization` 계약을 추가하고 `_SceneRenderer` 위젯을 `chat_screen`
메시지 빌드에 삽입하는 것이 자연 확장 경로다. **Flutter SDK 부재 → CI mobile 잡이 게이트.**

> **★구현 정정(S4 2026-06-14)**: ① 모델은 `coach_models.dart`가 아니라 신규 `data/scene_models.dart`
> (`LearningScene`·`SceneElement`·`Visualization`·`SceneLearnerContext`·freezed). **`SceneElement`는
> freezed union이 아니라 단일 flat 모델 + `kind` 문자열 + 변형별 nullable**(코드베이스에 union 선례 0·
> 로컬 코드젠 검증 불가 → 리스크 회피·렌더러가 `kind` switch). ② `SceneRenderer`는 `presentation/
> scene_renderer.dart` 독립 위젯(레지스트리 `kind→위젯`). `chat_screen` 삽입은 *장면 전달 엔드포인트
> 부재*로 연기(S5). ③ `visualization`은 **placeholder seed**(caption/type cue) — 실 WebView·
> postMessage는 S5(webview_flutter 미사용 + 위젯 테스트 플랫폼 부재). ④ `misconception_probe`는
> 개입 패턴별 *사고 유도 cue*만(정답·수정·오개념 id 미렌더 — 렌더 단계 낙인 금지). 테스트 단독
> `scene_models_test`(파싱·라운드트립)·`scene_renderer_test`(kind별 렌더·답미루기 가드).

-----

## 7. 현 구현 매핑 (편집자 부기)

> 본 설계안은 *목표 상태*다. 아래는 현 backend/클라 좌석과의 연결·델타.

| 설계 좌석 | 현 구현 (가동/상태) | 델타 |
|---|---|---|
| `Visualization`(요소 기반) | `schema/visualization.py`(4 타입·자유 JSON spec·`@model_validator`) | 🟡 **타입별 typed spec 없음**(S1) |
| 시각화 명세 생성 | `l3/visualization.py`(`generate_visualization_spec`·`parse_visualization_spec` 게이트) | 🟢 단일요소 가동 |
| 시각화 오케스트레이션 | `api/visualization.py`(약점개념→spec) | 🟢 가동(장면 합성은 S3) |
| 개념 골격 입력 | `schema/concept.py`(`recommended_visual_styles` 16종·`common_misconceptions`·`cognitive_type`·UC <!-- fact:concept_graph.concepts -->437<!-- /fact -->) | 🟢 가동 |
| `step_panel` 콘텐츠 | `schemas/v1.1/solution_path.schema.yaml`(`concept_sequence`·`steps`) | 🟡 Python 구현 후속(Phase 2) |
| `misconception_probe` | `l4/misconception/`(카탈로그 30종·`diagnose`·`InterventionPattern` 4종)·`misconception_hypothesis` ORM | 🟢 카탈로그·진단 가동 |
| `socratic_prompt` | L4 `PolyaState`·`PedagogyDecision`·`recommend_coaching` | 🟡 코칭 결정 가동(요소화 후속) |
| `learner_context` | L2 BKT/IRT·`MisconceptionHypothesisRecord`(활성 가설·confidence) | 🟢 가동 |
| `SceneRenderer`(L5) | `scene_renderer.dart`(레지스트리)·`scene_models.dart`·`scene_api.dart`(S5a 소비)·`chat_screen` 통합(S5e) | 🟢 S4+S5e(CI mobile·시각화 seed·실 WebView는 S5d) |
| `LearningScene`/`parse_learning_scene` | `l4/learning_scene.py`(8종 kind 판별 유니온·3 구조 불변식·카탈로그 참조 게이트·cov 100%) | 🟢 S2 완료 |

**판독**: 장면을 구성하는 *재료*(개념·오개념·코칭·학습자상태·단일 시각화 명세)는 대부분 가동.
본 DSL이 추가하는 건 ① **합성 스키마**(`LearningScene`) ② **검증 게이트**(불변식) ③ **L5 렌더러**.
진단·코칭·시각화 로직을 새로 짜는 게 아니라 *기존 좌석을 장면 요소로 노출 + 합성/게이트 신설*이다.

-----

## 8. 단계 로드맵 ("측정 없는 도입 없음"·1인 capacity 가드)

| 단계 | 범위 | 게이트 | 마이그레이션 |
|---|---|---|---|
| **S0** *(이번)* | 본 설계문서·MEMORY 로그·`05_interaction.md` 교차링크 | 문서 정합·회귀 0 | 0 |
| S1 ✅ | **typed `Visualization.spec`** — 4 타입별 sub-schema(자유 JSON → 검증가능 계약)·게이트 확장 | **완료 2026-06-14**: cov 100%·3001 passed·회귀 0 | 0 |
| S2 ✅ | `LearningScene` Pydantic + `parse_learning_scene`(참조 무결성·불변식) | **완료 2026-06-14**(`l4/learning_scene.py`): cov 100%·3036 passed·회귀 0·답미루기/낙인 불변식 테스트 35개 | 0 |
| S3 ✅ | `generate_learning_scene`(골격 결정론 + spec 충전·★배치 **L4** `l4/scene_generation.py` — LearningScene이 L4라 생성기도 L4·L3 다운콜) | **완료 2026-06-14**: cov 100%·3054 passed·회귀 0·테스트 18개 | 0 |
| S4 ✅ | L5 `SceneRenderer` 레지스트리(`kind→위젯`·시각화 seed·flat `SceneElement`) | **완료 2026-06-14**: CI mobile 잡(`build_runner`→`analyze`→`test`)·모델/위젯 테스트 | 0 |
| S5a ✅ | **Scene API 노출** — `generate_learning_scene`을 HTTP로(`api/scene.py`·`POST /v1/scenes/weak-concept`·진단→Concept→장면·visualization 미러) | **완료 2026-06-14**: cov 100%·3066 passed·회귀 0·테스트 12개 | 0 |
| S5e ✅ | **`chat_screen` 통합** — `SceneApi`(S5a 소비)·`ChatMessage.scene`·`requestScene`·AppBar 트리거·`_MessageBubble`→`SceneRenderer`(**end-to-end 첫 연결**) | **완료 2026-06-14**: CI mobile 잡·통합 테스트 3개 | 0 |
| S5b~d | 타입안전 union(mobile)·layout 전용 렌더(mobile)·실 WebView(mobile·D3/Desmos·postMessage) | mobile CI | 0 |
| S5f ✅ | **적응형 오개념 프로브 배선** — `api/scene.py`가 `get_active_hypotheses`(WH-1 가설 store·L4)로 학생 활성 가설을 조회해 `active_hypothesis_ids` 충전 → `_misconception_probes`가 ∩ 카탈로그로 프로브 생성(RS2 근거 강제·`student_id` None이면 조회 생략·기존 동작) | **완료**: 서비스/엔드포인트 테스트(가설→프로브·미조회)·회귀 0 | 0 |
| S5g ✅ | **프로브 개입 다양화** — 가설 *누적 신뢰도*(`active_hypothesis_confidences`)로 doc 결정트리(`select_intervention` 재사용·>0.8 반례·≥0.5 거꾸로·<0.5 보류)를 구동해 개입 패턴을 가설별로 선택(고정 `COUNTEREXAMPLE` 탈피·<0.5 프로브 미생성·낙인 회피). 신뢰도 미제공 시 레거시 반례 폴백(하위호환) | **완료**: 생성기 6개·서비스 1개 테스트·회귀 0 | 0 |
| S5h ✅ | **evidence_links 연동(렌더 시점 증거 재확인)** — `net_support_by_misconception`(evidence_store 배치 GROUP BY)로 학생 증거 그래프를 단일 쿼리 집계, 순지지도<0(반박 우세) 활성 가설은 프로브에서 제외(RS2 낙인 회피·`curate` net_support<0 archived 규약 동형·턴 후 신규 증거 반영). 증거 없는 가설은 유지(과도 억제 회피) | **완료**: evidence_store 단위 2개·서비스 1개·통합 1개 테스트·회귀 0 | 0 |
| S5i ✅ | **행동영역 분기축 승격** — `cognitive_type`을 `_COGNITIVE_SOCRATIC_MAP` 부수효과에서 `CompositionProfile`(소크라테스 프레이밍 + 인지 진입 순서 `lead`)로 흡수·1급 분기 입력화. `_primary_cognitive_type` precedence(VISUAL_REASONING>PATTERN>TECHNIQUE>THEOREM>DEFINITION)로 주 행동영역 선택 → visual 진입은 시각화 먼저·inquiry 진입은 질문 먼저. `bound_visualization_index`는 append 시점 계산이라 순서 변경에도 정합. Part 7 재검토 "행동영역 축 미분기" 상환(신규 element kind 0·SkillBlock 가시 UI는 잔여) | **완료**: 축 테스트 5개(진입 순서·precedence·인덱스 정합)·기존 26 무회귀·layout/게이트/동결 무영향 | 0 |
| S5j ✅ | **가시 SkillBlock element kind** — `skill_focus`(7번째 kind·`cognitive_type`+`focus_prompt`·정답 필드 0) 신설. 주 행동영역 THEOREM/TECHNIQUE/PATTERN에 정본 focus cue 자동 부여(블록 유무를 행동영역별 자동 분기)·맨 앞 프레이밍. 모바일 렌더러 focus 카드·동결 크로스워크 6→7 갱신. interactive 경우분할 트리는 잔여(Tier3) | **완료**: 백엔드 축 테스트 10개(생성·분기·게이트·필드 동결)·모바일 파싱/렌더 테스트·회귀 0 | 0 |
| S5k ✅ | **정본 BehaviorArea로 재정렬** — S5i/S5j가 근사했던 `CognitiveType` 축을 #418 정본 `BehaviorArea` 6종으로 이전(직교 2축: 소크라테스=개념축·lead/skill_focus=행동영역축). `skill_focus.behavior_area`·L1 `get_behavior_areas`(concept→skill 조인·#419)·L5 `api/scene.py` 스레딩. 미매핑=중립(탐구 진입·focus 0). main #404/#408~#419 재베이스 병합(visualizability 게이팅 보존) | **완료**: 축·skill·접근자·엔드포인트 테스트 재작성·l4/api 2001 passed·ruff·black·mypy·lint-imports green·모바일 JSON 키 갱신 | 0 |
| S5l ✅ | **학생적응 Tutoring Adapter(mastery 축)** — `tutoring_prompt`(8번째 kind·`role`+`prompt_text`·정답/hint_level 필드 0) 신설. `learner_context.mastery_level`(BKT)→`mastery_to_level`→`adapt_lthc`(진입/비계/확장) 정본 발화를 `_lthc_prompts`로 장면에 배선(초보=진입+비계·숙달=확장·발전중=균형·축당 1개 캡·lead 분기 뒤·프로브 앞). mastery 없으면 미방출(비계 날조 금지·낙인 회피). 학생적응을 *반증된 modality가 아니라 mastery*로 닫음(설명 스타일 modality는 의도적 미배선). API 변경 0(mastery 이미 스레딩)·마이그레이션 0. 동결 크로스워크 7→8 갱신 | **완료 2026-08-05**: 생성기 9개+서비스 2개 테스트·모바일 파싱/렌더 테스트·`_primary_polya_stage`(소크라테스 매핑 재사용) | 0 |
| S5+ | 적응형 장면 잔여(1:N crosswalk 정책)·과목 확장·교과서 자동 UI·interactive 경우분할 트리(SkillBlock Tier3) | Phase 2~3 | 해당 시 |

**적용 범위 원칙**: verify 가능·표기 안정 단원(대수·함수 그래프)부터 켜고, 기하·증명(드래그·
스내핑·제약·작도)은 WH-S Tier3(Lean) 성숙도에 종속하므로 초기 scope 제외(정직한 경계).

-----

## 9. 리스크 레지스터

| ID | 리스크 | 심각도 | 대응 |
|---|---|---|---|
| RS1 | 합성 DSL이 답 미루기/낙인 금지를 우회(LLM이 정답을 spec에 흘림) | 높음 | §4 스키마 차원 필드 부재 + 검증 게이트(불변식 테스트·FP 프로브) |
| RS2 | 거짓 오개념 프로브(학습자 거짓 낙인) | 높음 | `misconception_probe`=가설(WH-1 confidence)·`active_hypothesis_ids` 근거 강제 |
| RS3 | 그래프 엔진 과대구현(Desmos 재구현) | 중간 | DSL은 *명세*만·렌더는 임베드(Desmos/GeoGebra·D3/three.js) 재사용 |
| RS4 | 기하·증명 자동형식화 난제(문서 §14) | 중간 | 초기 scope 제외·WH-S Tier3에 위임 |
| RS5 | LLM 장면 생성 환각·스키마 위반 | 중간 | 결정론 골격(LLM은 spec만)·`parse_learning_scene` 게이트·router 폴백 |
| RS6 | 1인 capacity — 합성/렌더러 복잡도 | 중간 | S1~S4 자족 슬라이스 단계화·마이그레이션 0 우선 |

-----

## 10. 종합 판단

- 외부 문서 2종은 **방향 전환이 아니라 우리 아키텍처(표현≠의미·독립 수학 코어) 베팅의 외부 검증**이다.
- 우리에게 부족한 단 하나의 좌석 = `Visualization` 위 **합성 계층(LearningScene)**. 본 DSL이 이를
  못박되, 문서의 범용 DSL을 **그대로 쓰지 않고** 답 미루기·낙인 금지·검증 게이트를 *스키마 불변식*으로
  교정해 수용한다(의사결정 우선순위 1·2·3을 표현 계층에 강제).
- 장기 미래상(**Math Knowledge Runtime**·교과서 자동 UI·오답 기반 화면 변화·과목 확장)은
  본 DSL + 개념그래프 + 두 하네스(WH-1 가설·WH-S 검증 풀이)의 결합으로 *점진적으로* 도달한다 —
  "전부 아니면 전무"가 아니라 S1~S5 각 단계가 회수 가능한 구조다.

-----

## 참고

- 정본 상위: `docs/architecture/05_interaction.md`(§시각화 스택 — 선언적 `Visualization`)
- 자매: `docs/architecture/04a_wh1_tutoring_harness.md`·`03b_wh_s_solver_harness.md`
- 구현 좌석: `schema/visualization.py`·`l3/visualization.py`·`api/visualization.py`·
  `schema/concept.py`·`l4/misconception/`·`schemas/v1.1/solution_path.schema.yaml`
- 원칙: `CLAUDE.md`(슬라이스 89 표현≠의미·답 미루기·정확성 #1·의사결정 우선순위)
- 외부 문서: "수학교육앱 인터페이스 설계 자동화"(2026-06-14·Kiki 제공·DOCX/PDF)
- 변경 이력: v0.1 (2026-06-14 초안 — 설계만·구현 0)
