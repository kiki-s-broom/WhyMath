# 시각화 모듈 — 외부 EOS 틀 대조 갭 점검·설계 (2026-07-30 · §7 2026-08-03 · §8 2026-08-10 갱신)

> ⚠️ **현행은 4차(R4) — `visualization_module_gap_review_r4.md`**(2026-08-11 작성 · 2026-08-14
> 재실측·재착지). 본 문서는 1~3차(§1~§6 · §7 · §8)를 in-place로 담고 있으며, 4차부터는 시리즈
> 규약(원본 비수정 + 별도 파일 — `problem_bank_gap_review_r2.md`·`gamification_module_gap_review_r2.md`
> 확립)에 따라 분리했다. 4차가 갱신한 것: **§8.9가 "4차 최우선 후보"로 남긴 Scene DSL↔Visualization
> DSL 축은 이미 닫혀 있었다**(#756 스키마 축 · `PED-16` ④ 서빙 축 — R4 §2에서 이월 정식 종료) ·
> 1~3차가 개념 축만 보는 동안 미점검이던 **문제(problem) 축 시각화가 죽은 사슬**로 드러남
> (R4 §3 D5 → `VIZ-10`). 본 문서는 완료 태스크의 판정 근거 원본으로 보존하며 소급 수정하지 않는다.

> **범위**: 외부 참고 문서 『시각화』(기능 62 함수 그래프 시각화 · 63 기하 도형 조작 · 64 애니메이션
> 설명 · 65 수학 모델 시뮬레이션, 세부 기능 40개 — **WhyMath 전용이 아닌 일반적인 EOS 틀**,
> Kiki 제공)을 현 코드베이스와 대조해 빠진 부분을 점검하고, 진짜 갭을 WhyMath 불변식
> (표현≠의미 · Renderer=Plugin · 교수학 금기 · dead code 금기 · anti-explosion) 안에서 설계한 기록.
> **형식**: `ai_content_generation_gap_review.md`(같은 EOS 틀 시리즈 기능 58~61, 2026-07-30) 답습 —
> 시리즈 **8번째** 자매편. **§7은 동일 문서에 대한 2차 점검**(모듈당 단일 진실원 유지 — 새 파일
> 미신설) — `VIZ-01` 착륙 후 새로 드러난 지형을 실측한다.
>
> **결론(1차·§1~§6)**: 착수 가설("시각화는 문서만 있고 구현이 얇다")은 **실측으로 정면 기각**됐다.
> 명세→API→클라 렌더까지 end-to-end가 배선돼 있고, 자체 제작 그래프 계산기 2,141행이 접선·적분·3D·
> 회귀까지 한다. 그런데 **더 나쁜 것이 나왔다** — 학생 경로의 시각화 블록을 여닫는 게이트가 요구하는
> 오버레이 2종이 **프로덕션 적재 경로 0건**이어서, 이 전 스택이 **학생에게 단 한 번도 도달하지
> 않는다**(§3 D1). 즉 기능 62의 갭은 "못 만들었다"가 아니라 **"만들어 놓고 연결하지 않았다"**다.
> 기능 63은 spec 타입 부재로 `S4-03` 승계, 64는 좌석만 있고 Manim 0, 65는 확률만 실재하고 나머지는
> 페르소나 밖. 의도적 미채택 6건, 진짜 갭 D1~D4, 기하는 **승계(재설계 금지)**.
> `VIZ-01`(D1+D2)은 **2026-07-31 착륙·완료**(PR #654) — §7이 그 이후 지형이다.
>
> **결론(2차·§7)**: 착수 가설("`VIZ-01`으로 도달 문제는 끝났다")은 **실측으로 기각**됐다. 데이터가
> 흐르기 시작하자 *흐르는 데이터가 렌더 좌석과 맞지 않는다*는 더 깊은 결함이 드러났다 — 태깅된
> 시각화 양식 127건 중 실제로 표현할 렌더 타입이 있는 것은(2026-08-03 `VIZ-04` 구현 중 재감사로
> 정정) **24건(18.9%)뿐**이다(최초 판단은 15건·11.8%로 과소평가했다). 1차 편이 "만들어 놓고
> 연결하지 않았다"였다면 2차 편은 **"연결했더니 양쪽 어휘가 다르다"**다. `VIZ-04`는 **완료**됐다
> (`l4/visualization_policy.has_render_seat` 게이트 + `data/visual_style_contract.json` 계약).

관련 정본: `05_interaction.md`(§5.2 선언적 명세) · `05a_learning_scene_dsl.md`(Scene DSL) ·
`05b_visualization_classification.md`(시각화 가능성 4분류) · `data/render_contract.json`(invariant ⑩
렌더 선택 단일 진실원) · `part7_math_ui_dsl_review.md`(UI/런타임 역류 방어) ·
`edge_design_part3_review.md`(`TestConceptPurity`·`figure_spec` 거부) ·
`ai_content_generation_gap_review.md`(후보 65 멀티모달 판정) · `MEMORY.md` 결정 로그(2026-07-30·2026-08-03).

---

## §0. 두 가지 전제 정리

### ①-a 외부 틀의 번호 체계가 문서 간 불일치 (스코프 고정)

선행 자매편 `ai_content_generation_gap_review.md:136`의 "확장 후보 62~68"과 본 편의 기능 번호가
**같은 번호에 다른 기능**을 매긴다:

| 번호 | 선행 편(확장 후보) | **본 편(시각화)** |
|---|---|---|
| 62 | 힌트 자동 생성 | **함수 그래프 시각화** |
| 63 | 풀이·해설 자동 생성 | **기하 도형 조작** |
| 64 | 변형 문제 생성 | **애니메이션 설명** |
| 65 | 멀티모달(도형·그래프·애니메이션·음성) | **수학 모델 시뮬레이션** |

따라서 본 문서의 "기능 62~65"는 **전부 본 편 기준**이며, 선행 편의 후보 번호와 교차 참조하지 않는다.
단 **선행 편 후보 65(멀티모달) 판정은 본 편 63·64와 실질 중복**이므로 **승계**한다(재판정 아님):
`VisualizationType` 4종 중 `animation_prerendered`만 렌더 경로 부재 · 기하·벡터·행렬 spec 타입 자체
없음 · `figure.spec`은 의도적 거부 · ⏸ `S4-03` — 이 4개 판정은 본 편에서도 유효하고, 본 편은 여기에
**적재 축(D1)과 계약 축(D3)을 새로 더한다**.

### ①-b 틀의 아키텍처와 정본의 차이 (갭 판정의 전제)

틀은 시각화를 **선형 스택의 한 층**으로 그린다:

```
교육과정 → Knowledge Graph → AI Tutor → AI 콘텐츠 생성 → [시각화 엔진] → 학생 상호작용(UI)
```

정본은 시각화를 *층*이 아니라 **두 개의 분리된 책임 + 그 사이의 계약**으로 본다:

```
L3: 시각화 *명세* 생성·검증(구조/JSON)        ← 수학 로직·렌더 실체 없음
        │  data/render_contract.json (invariant ⑩ — type → 렌더러 단일 진실원)
        ▼
L5: 렌더(웹 SPA·Flutter WebView·three.js)     ← 수학 로직 0·dumb
```

- **"시각화 엔진"이라는 단일 박스는 정본에 없다.** 있으면 안 된다 — `l3/visualization.py:5`가
  옛 `generate_visualization() -> bytes`(Manim 영상 반환)를 **7계층 경계 위반으로 명시 삭제**했다.
  명세와 렌더가 한 박스에 있으면 코어가 렌더러 구현체에 결합된다(Renderer=Plugin 위반).
- **노드에 렌더 실체를 넣지 않는다** — `TestConceptPurity`가 `Concept`에서 `figure_spec`·renderer·
  animation·layout 슬롯 **부재를 단언**한다. 시각화는 *참조 키*만 허용하고 실체는 노드 밖
  (Overlay·명세)에 둔다. **틀이 암시하는 "개념에 그림을 붙인다"는 모델은 채택하지 않는다.**
- 결과적으로 **틀 대비 정본이 더 정교하다.** 본 편이 찾은 갭은 이 구조의 결함이 아니라
  **구조를 다 만들고 데이터를 흘려보내지 않은 것**이다.

---

## §1. 기능 62~65 전수 대조 (세부 40개)

판정 기호: ✅ 충족·초과 / △ 부분(렌더러는 하는데 *명세 좌석* 없음) / ⚠️ 진짜 갭 → D / ⏸ 기존 태스크 승계 / 🚫 의도적 미채택 → §2

### 기능 62 — 함수 그래프 시각화

**전제: 아래 ✅는 전부 "구현 실재" 판정이며, 학생 도달 여부는 별개다(D1이 전건을 막고 있다).**

| 세부 기능 | 현행 | 판정 |
|---|---|---|
| 2D 함수 그래프 | `Graph2dSpec`(`schema/visualization.py:56`) + 웹 `graph2dSpecToState` + `GraphingCalculator.jsx` | ✅ |
| 3D 곡면 그래프 | `Surface3dSpec:80` + three.js(npm 번들·동적 import) | ✅ |
| 매개변수 슬라이더 | `Graph2dParam:44`(min/max/step/default) + `ParamControlElement`(Scene DSL) | ✅ |
| 함수 비교 그래프 | 계산기는 다중 함수 행 지원. **명세에 좌석 없음** | △ → **D4** |
| 접선 및 법선 표시 | 계산기 접선 O(`numDeriv`). 법선 ✗. **명세 좌석 없음** | △ → **D4** |
| 극대·극소 자동 표시 | 계산기 근·절편 O. 극값 자동 표시 ✗. **명세 좌석 없음** | △ → **D4** |
| 적분 영역 시각화 | 계산기 리만 합 O. **명세 좌석 없음** | △ → **D4** |
| 미분 변화 시각화 | 계산기 도함수·2차 도함수 O(`num2Deriv`). **명세 좌석 없음** | △ → **D4** |
| 함수 변환(평행이동·대칭·확대) | 슬라이더 파라미터화로 *우회* 가능. 전용 좌석 ✗ | △ (D4 범위 밖 — 우회로 충족) |
| GeoGebra·Desmos 연동 | Desmos-스타일 **자체 구현**이 이미 있음 | 🚫 → **§2-⑤** |

### 기능 63 — 기하 도형 조작

`VisualizationType` 4종(`schema/enums.py`)에 **기하 계열이 없다** → `_SPEC_MODEL_BY_TYPE:121`도 4종.
세부 10개 중 9개가 **spec 타입 부재로 일괄 미커버**이며, **`S4-03-visualization-type-expansion`
(todo·stage S4·`depends_on: S3-01-pilot-cohort`)이 "기하(작도)·벡터·행렬 변환·미적분 애니메이션
spec+렌더러"를 이미 acceptance로 보유**한다.

| 세부 기능 | 판정 |
|---|---|
| 점 드래그 · 선분·각도 조절 · 원과 접선 조작 · 삼각형 성질 탐구 · 다각형 생성 · 전개도 생성 · 좌표기하 조작 · 벡터 조작 | ⏸ **`S4-03` 승계 — 재설계 금지** |
| 입체도형 회전 | `Surface3dSpec.rotatable` 실재하나 **곡면(z=f(x,y))만** — 다면체·입체도형 아님 | ⏸ `S4-03` |
| 자동 증명 보조 시각화 | 🚫 → **§2-④** |

**부수 실측 — 분류·렌더 불일치**: `visualizability.json`이 `HIGH-GEO-010`(벡터의 뜻과 연산)을
**"직접"**(형태가 즉시 보임)으로 분류해 놓았는데 **벡터를 그릴 수 있는 렌더 타입이 없다**.
즉 정본이 스스로 "이건 그림으로 바로 보여야 한다"고 판정한 개념에 렌더 좌석이 없다. `S4-03` notes에
이 불일치를 명기한다.

### 기능 64 — 애니메이션 설명

`AnimationSpec:111`은 `asset_id`·`duration_seconds` **2필드뿐이고 둘 다 optional**이다.
`data/render_contract.json`은 이 타입의 `family: ["Manim"]`·`web_adapter: **null**`(렌더 경로 없음)로
선언한다. 그리고 **Manim 구현은 0건**이다 — `grep -ril manim src/` → 4파일이 나오지만 전부
docstring·주석이며(`l3/visualization.py:5`가 옛 Manim 반환의 *삭제*를 기록), `import manim`도
의존성 선언도 없다. **즉 `asset_id`가 가리킬 자산을 생산하는 경로가 존재하지 않는다.**

| 세부 기능 | 판정 |
|---|---|
| 공식 유도 · 증명 과정 · 함수 변화 · 극한 개념 · 미분 과정 · 적분 누적 · 기하 변환 애니메이션 | ⚠️ 좌석만 존재·렌더 경로 0 → **§4 트리거**(Manim 파이프라인) + ⏸ `S4-03` |
| 문제 풀이 단계 재생 | △ `StepPanelElement`·`reveal_policy="deferred"`(점층 노출·답 미루기)가 실재 — **애니메이션은 아니나 교수학적 목적은 이미 충족**(즉답 금지) |
| 오개념 비교 애니메이션 | ⚠️ 애니메이션 형태 ✗. 단 오개념 *개입*은 실재(`_probeCue` 반례·구체예·거꾸로) |
| AI 음성 해설 동기화 | △ 음성 **서버 표면**은 실재(`api/speech.py` `/v1/speech` → `SpeechSpec`). 단 **클라 합성 경로는 0**(`flutter_tts` Gradle 비호환으로 pubspec 제거·2026-08-11 실측). **동기화 대상(애니메이션)도 없어 선행 미성립** → §2-③ |

**구조 결함 실측(→ D3)**: `l3/visualization.py:85-90` `_SYSTEM_PROMPT`가 **4종 전부를 문자열
리터럴로 LLM에 제시**한다("type은 위 4종 중 하나"). 렌더 계약은 이 중 1종이 렌더 불가라고
선언하는데, **생성기는 그 계약을 읽지 않는다.** 두 정본이 서로를 모른다.

### 기능 65 — 수학 모델 시뮬레이션

| 세부 기능 | 현행 | 판정 |
|---|---|---|
| 확률 실험 | `SimulationSpec:98`(experiment·trials·outcomes) + 웹 `simulationExperiment.js`(동전·주사위 키워드 + **구조화 outcomes로 임의 분포**) | ✅ |
| 몬테카를로 시뮬레이션 | `runTrials`(가중 추출·rng 주입 가능·`MAX_TRIALS` 50000 성능 가드)가 **바로 그것** | ✅ |
| 통계 샘플링 | `outcomes`로 모집단은 표현 가능하나 **표본평균 분포**(반복 표집) 좌석 없음 | ⚠️ → **§4 트리거** |
| 물리 운동 · 금융 복리 · 경제 수요·공급 · 전염병(SIR) · 최적화 · 미분방정식 | 전부 0건 | 🚫 → **§2-①** |
| AI 기반 가상 실험 | 0건 | 🚫 → **§2-②** |

---

## §2. 의도적 미채택 판정 (협상 불가 근거)

| # | 문서 제안 | 불채택 근거 (CLAUDE.md·정본) |
|---|---|---|
| ① | **물리·금융·경제 수요공급·SIR·최적화·미분방정식 모델**(기능 65) | 타깃 페르소나(PRD v1.2 §3 — A 고3 MVP·수능) **밖**. + "LLM 응답을 검증 없이 학생에게 제공 금지" — 이들은 **SymPy 검증 앵커가 없다**(SymPy는 동치·해집합 권위이고 모델 타당성 권위가 아니다). + ROADMAP Phase 2+ **1인 capacity 가드**. 대학·타과목 축은 E축(`G-s5-subject-expansion` 게이트 통과 후) |
| ② | **AI 기반 가상 실험**(기능 65) | "확실하지 않을 때 자신 있게 말함 패턴 금지" — 검증 불가한 실험 결과를 생성해 학생에게 사실로 제시하는 형태. 검증 권위 서열 ①②를 **원리적으로** 통과할 수 없다 |
| ③ | **AI 음성 해설 *동기화***(기능 64) | 갭이 아니라 **순서**다 — 음성 *서버* 표면은 실재(`/v1/speech`)하고, 동기화 대상인 애니메이션이 §4 트리거 뒤에 있다. 대상 없는 동기화 구현은 dead code. (2026-08-11 정정: 클라 합성 경로도 0 — `flutter_tts` 제거. 선행이 하나 더 있다) |
| ④ | **자동 증명 보조 시각화**(기능 63) | 증명 자동화는 검증 권위 서열 ①(기계 증명) **밖** — SymPy는 기하 증명 엔진이 아니다. 검증 앵커 없이 "증명을 보조한다"는 시각화는 오개념 생산 위험(교수학적 정확성 > 사용자 경험) |
| ⑤ | **GeoGebra·Desmos 연동**(기능 62) | **자체 구현이 이미 있다**(2,141행·Phase 1~15·오프라인 자족). 외부 임베드는 ⓐ 미성년자 데이터가 제3자로 흐르고 ⓑ CDN 의존이 오프라인 자족(WebView `file://`·번들 폰트)을 역행하며 ⓒ "국소 임베드 **2 비상구**"(MathLive·three.js) 원칙에 3번째를 추가한다 |
| ⑥ | **개념 노드에 그림·figure를 붙이는 모델**(틀의 암시) | `figure.spec` **의도적 거부** — `TestConceptPurity`가 `Concept`에서 `figure_spec`·renderer·animation·layout 슬롯 부재를 **기계로 단언**한다(Renderer=Plugin·Concept Purity). 시각화는 참조 키만, 실체는 Overlay·명세 |

---

## §3. 진짜 갭 설계

### D1 — 시각화 공급원 미적재: 전 스택이 학생에게 도달 0회 (최우선·`VIZ-01`)

**증상.** 학생이 받는 학습 장면에 **시각화 요소가 단 한 번도 실리지 않는다.**

**경로 5단 실측 (전건 코드 확인).**

1. 학생 경로는 `POST /v1/scenes/weak-concept` **단 하나**다 — Flutter가 호출하는 것은
   `scene_api.dart:25`의 이 엔드포인트이고, `/v1/visualizations/*` 3엔드포인트는
   **클라 소비처 0건**(`grep`으로 `src/mobile`·`src/web` 전수 확인).
2. `api/scene.py:92-93`이 개념별로 두 오버레이를 조회한다 —
   `get_visualizability(session, code)`와 `get_recommended_visual_styles(session, code)`.
3. `l4/scene_generation.py:279`가 **두 값을 AND로 요구**한다:
   ```python
   if not (concept.recommended_visual_styles and is_visualizable(visualizability)):
       return          # ← 시각화 블록 미부여
   ```
4. **두 오버레이의 프로덕션 적재 경로가 0건이다.** 적재 함수는 존재하고 단위 테스트도 있으나,
   **저장소 전체에서 호출자가 없다**(테스트 제외 전수 집계):

   | 함수 | 프로덕션 호출 |
   |---|---|
   | `populate_concept_visual_style` | **0건** |
   | `load_concept_visual_style_from_json` | **0건** |
   | `populate_concept_visualization` | **0건** |
   | `load_concept_visualization_from_json` | **0건** |

   프로덕션 적재 오케스트레이터는 `l1/atom_graph/populate.py::populate_atom_backbone`(+`_main()` CLI —
   Kiki가 실행해 `concepts=2,683 edges=2,210`을 적재한 그것)인데 **`concept`·`concept_edge`만**
   적재하고 두 오버레이를 건드리지 않는다(`grep -n visual` → 0건). alembic
   `20260726_0000_a9b8c7d6e5f4_concept_visual_style_overlay.py`는 **스키마만** 만들고 INSERT가 없다.
   `scripts/demo/seed_demo.py`도 `problem_bank`만 시드한다.
5. 따라서 prod에서 `get_recommended_visual_styles` → `[]`(빈 리스트=falsy),
   `get_visualizability` → `None`. §3-3의 조건은 `not ([] and ...)` → `not False` → **항상 `return`**.

**결론.** `Graph2dSpec`·`Surface3dSpec`·`SimulationSpec`, 렌더 계약(invariant ⑩) 교차 게이트,
2,141행 계산기, Flutter `{type,spec}` 봉투, MathLive·three.js 오프라인 번들 — **전부 구축·테스트
완료 상태로 구조적으로 미도달**이다. `concept_visual_style`은 **코퍼스 파일 자체가 없고**,
`concept_visualization`은 **파일이 7건 있으나 적재 경로가 없어 DB 0행**이다. 즉 §1의 분류율
1.60%(7/437)는 *파일 기준*이고 **런타임 기준 분류율은 0%**다.

**설계.**
- `concept_visual_style` **코퍼스 신설** — `VisualizationStyle` enum 값으로 개념별 권장 양식 태깅.
  전수 LLM 태깅 금지(검증 앵커 없음): 성취기준 영역·개념 유형에서 결정론 규칙으로 유도 가능한
  것부터 채우고 **판정 불가는 미태깅으로 남긴다**(억지 태깅이 억지 그림을 만든다).
- **두 오버레이를 프로덕션 적재 경로에 배선** — `populate_atom_backbone` 확장 또는 동급 CLI.
  새 추상 금지(기존 populate 규약 재사용·멱등).
- **도달률 리포트를 CI에 배선** — "시각화 요소를 포함한 장면 비율". 이 지표가 없어서 도달 0회가
  누구에게도 보이지 않았다. **100% 도달은 목표가 아니다**(추상 개념은 보류가 정답) — 관측이 목표.
- **acceptance 변별력**: 적재 *전* 도달률 0%를 실측 → 적재 *후* N%를 실측(성공/실패가 같은 값을
  내면 검증이 아니라 위장). 그리고 **CI 잡이 이 리포트를 실제로 실행하는지 확인**(OPS-03·OPS-10
  선례 — "저장소에 존재함"과 "돌아감"은 다르다).

### D2 — 시각화 가능성 분류의 교수학 보호가 fail-open으로 무력 (`VIZ-01` 후속 축)

`l4/visualization_policy.py:29`:
```python
return visualizability is None or visualizability not in _ABSTAIN   # None → True
```
주석이 "None을 True로 두는 것은 *하위호환*"이라 명시한다 — 의도된 fail-open이다.

**D1이 해소되는 순간 이것이 표면화된다.** 적재가 배선되면 7개념만 분류값을 얻고 430개념은
`None`으로 게이트를 통과하는데, 그때 잃는 것은 두 가지다:

1. **추상 개념 보호 상실** — `05b`는 추상 개념(대우증명·귀류법)에 리터럴 그래프를 주면
   **오개념을 유발**한다고 판정한다(`HIGH-LOGIC-007` rationale). 미분류면 이 보호가 발동하지 않는다.
2. **직접/동적 구분 상실** — `scene_generation.py:296`의 `prefers_static_visual(None) = False`라
   **미분류 개념 전건에 슬라이더가 붙는다**. "직접"(정지 그림으로 충분) 개념에 불필요한 조작을
   주는 것은 05b가 명시적으로 피하려는 것이다.

CLAUDE.md 직격: *"상시 실패하는 fail-open 보호를 '보호 있음'으로 신뢰 금지 — 같은 실패가 반복
관측되면 그 보호는 상시 무력 상태다."* 지금은 **관측조차 되지 않는다**(분류율 리포트 0건).

**설계.** fail-open 자체는 유지한다(fail-closed로 바꾸면 시각화가 전멸 — 우선순위 4 학습효과 침해).
바꾸는 것은 **가시성**이다: 분류율·미분류 개념 목록을 D1의 도달률 리포트와 같은 축에 싣고,
분류 확대는 별건(§4 트리거 아님 — `VIZ-01` acceptance에 초기 목표 커버리지를 명시).
**변별력**: 임의 개념 1건을 "추상"으로 오태깅해 게이트가 실제로 시각화를 보류하는지 실측 →
복원 후 정상 동작 실측.

### D3 — 생성기가 렌더 불가 타입을 제시한다: 계약 파생으로 봉인 (`VIZ-02`)

**런타임 실측(코드 읽기 아님).** 격리 환경에서 프로덕션 코드를 직접 호출한 결과:

| 검사 | 결과 |
|---|---|
| ① `{"type":"animation_prerendered","spec":{}}` 중앙 검증(`Visualization.model_validate`) | **통과** — `asset_id` 없이도 통과(두 필드 모두 optional) |
| ② 프로덕션 게이트 `parse_visualization_spec` | **통과** — type 필터 없음 |
| ③ **변별력** — `interactive=True`로 바꾸면? | **거부**(`InvalidVisualizationSpecError`) → 게이트는 살아있다. 즉 ①②의 통과는 게이트 고장이 아니라 **설계상 통과**다 |
| ④ 렌더 계약의 해당 타입 | `web_adapter: **null**` (렌더 경로 없음·`family: ["Manim"]`) |

**즉 자산 참조가 비어 있는 애니메이션 명세가 모든 검증을 통과한다.** 그리고
`_SYSTEM_PROMPT`(`l3/visualization.py:85-90`)는 이 타입을 LLM에 **유효 선택지로 제시**한다.

**정직한 severity 하향 (반증 시도 결과).** 당초 "학생이 빈 화면을 받는다"로 판정했으나
**반증에 성공해 하향한다**:
- Flutter는 `scene_renderer.dart:104-121`에서 렌더 가능 3종 + `interactive` + 비어있지 않은 `spec`만
  WebView로 보내고, **그 외는 `_VisualizationSeed`로 폴백**한다 — 아이콘 + caption 텍스트 카드
  (`:164` caption 없으면 "인터랙티브 시각화"). **빈 화면이 아니라 우아한 강등이다.**
- 게다가 `animation_prerendered`는 스키마 불변식(`:188`)이 `interactive=False`를 **강제**하므로
  **구조적으로 WebView에 도달할 수 없다** — 항상 seed로 간다.
- 그리고 D1이 살아 있는 동안 scene 경로에서는 **생성 자체가 일어나지 않는다**(게이트 앞에서 return).

**따라서 D3은 "라이브 사고"가 아니라 "잠재 결함 + 낭비"다.** 남는 실질 피해 3가지:
1. **웹 경로는 조용히 미렌더** — `graph2dSpec.js:181`이 `null` 반환("조용히 미렌더" 주석).
   "침묵 실패 금지" 규약의 문면과 충돌한다.
2. **LLM 호출 낭비** — 렌더될 수 없는 타입을 생성하는 데 비용이 든다.
3. **교수학적 약속 불이행** — caption이 예고한 시각화가 끝내 나타나지 않는다.

**설계(비용 최소·효과 확실).** `_SYSTEM_PROMPT`의 하드코딩 4종 목록을
**`data/render_contract.json`에서 파생**시킨다 — `web_adapter != null`인 타입만 제시.
`AnimationSpec`은 스키마에 **존치**(계약·enum·`S4-03` 좌석이 필요). 죽이는 것은 *생성 경로*뿐이며
Manim이 배선되는 날 계약 한 줄로 되살아난다. **새 추상 0 · 단일 진실원 확장.**
**변별력**: 계약에서 `graph2dSpecToState`를 null로 바꿔 게이트 exit 1 실측 → 복원해 exit 0 실측.

### D4 — 명세 표현력 < 렌더러 능력 (`VIZ-03`)

`Graph2dSpec`은 `function`·`domain`·`y_range`·`parameters` **4필드**다. 계산기는 접선·도함수·
적분(리만 합)·다중 함수를 **이미 그릴 수 있다**. 그런데 코어(L3)는
*"x=2의 접선을 보여라"·"[1,3] 적분 영역을 칠하라"·"극값을 표시하라"·"두 함수를 비교하라"*를
**명세로 지시할 수 없다.** 기능 62 세부 10개 중 5개가 정확히 여기에 걸린다.

**이것은 렌더러를 새로 만드는 일이 아니라, 이미 있는 능력에 명세 좌석을 주는 일이다.**

**설계.** `Graph2dSpec`에 optional 필드로 확장(`tangent_at`·`integral_range`·`mark_extrema`·
`compare_functions` 성격). **새 `VisualizationType` 신설 금지**(anti-explosion — 4종 유지).
웹 어댑터·계약·Flutter 봉투까지 동반 갱신하고 미갱신 시 red.
**`S4-03`과의 경계**: `S4-03` = **새 type**(기하·벡터·행렬), D4 = **기존 2D type의 필드**.
중복이 아님을 양쪽 notes에 상호 참조한다. D1 미해소 상태에서 D4를 먼저 하면 **도달하지 않는 명세의
표현력을 늘리는 일**이 되므로 `depends_on`으로 순서를 강제한다.

### 등재 요약

| 태스크 | 설계 | stage | 근거 |
|---|---|---|---|
| `VIZ-01` | D1 + D2 | S3 | 학생 도달 0회 — 최우선 |
| `VIZ-02` | D3 | S3 | 잠재 결함 봉인·비용 최소 |
| `VIZ-03` | D4 | S4 | D1 해소 후에야 의미(`depends_on: VIZ-01`) |
| `S4-03`(기존) | 기능 63 전건 | S4 | **승계·재설계 금지**. notes에 분류·렌더 불일치 명기 |

---

## §4. 미등재 트리거 (dead task 방지 — 발화 조건만)

- **Manim 서버 렌더 파이프라인**: 발화 조건 = ⓐ `S3-01` 파일럿에서 "동적" 분류 개념의 학습 손실이
  측정되고 ⓑ 렌더 워커 capacity 확보. 지금 등재하면 ROADMAP Phase 2+ 1인 capacity 가드 위반.
  **주의**: `visualizability.json`이 `HIGH-CALC-005`(미분계수)·`HIGH-CALC-001`(극한)을 "동적"으로
  분류하고 rationale에 **"★AI 교육 핵심"**이라 적었다 — 정본이 스스로 최중요라 표기한 두 개념이
  렌더 경로 부재다. 이 트리거는 그만큼 발화 압력이 높다.
- **통계 샘플링(표본평균 분포)**: 발화 조건 = 확률과통계 성취기준 커버리지 착수 시.
  **먼저 확인할 것** — `SimulationSpec.outcomes`가 이미 임의 분포를 표현하므로 명세 확장 없이
  *실험 정의만*으로 표집을 표현할 수 있는지. 가능하면 태스크 불요.
- **법선·함수 변환 전용 좌석**: 슬라이더 파라미터화로 우회 충족 중. 우회가 교수학적으로 부족하다는
  측정이 나오면 D4 범위에 추가.

---

## §5. 검증 — 무엇을 돌렸고 결과가 무엇인가

문서·backlog 변경이라 코드 스위트는 해당 없다(`src/` diff 0). 대신 **문서가 주장하는 사실을
실행으로 확인**했다.

- **런타임 증명(격리 환경·프로덕션 코드 직접 호출)** — §3 D3의 4행 표가 그 출력이다.
  `uv run --no-project --with pydantic --with pydantic-settings --with sympy`로
  `Visualization.model_validate`·`parse_visualization_spec`를 실제 호출했다. **③ 변별력 검사를
  동봉**해 게이트가 살아있음을 확인했다(성공/실패 양쪽에서 같은 값을 내는 검사는 위장).
- **분류율 재계산**: `visualizability.json` 7건 / `concept_graph_v1` 437 = **1.60%**,
  4분류 분포 직접/동적/부분/추상 = 2/2/2/1, 미분류 430.
- **적재 호출 0건 전수 집계**: 4개 함수 × 저장소 전체(테스트·자기 모듈 제외) = **전부 0건**.
  프로덕션 오케스트레이터(`populate_atom_backbone`)에 `grep -n visual` → 0건.
  alembic 마이그레이션 INSERT 0건. `seed_demo.py`는 problem_bank만.
- **Manim 0건**: `grep -ril manim src/` → 4파일, 전건 docstring·주석 확인.
- **클라 소비처 전수**: `/v1/visualizations` → `src/mobile`·`src/web` 참조 **0건**,
  `/v1/scenes/weak-concept`만 실소비(`scene_api.dart:25`).
- **반증 시도 2건이 성공해 판정을 하향했다**:
  ⑴ D3의 "빈 화면" 주장 → `_VisualizationSeed` 폴백 발견으로 **"우아한 강등 + 낭비"로 하향**.
  ⑵ D3의 심각도 → `interactive=False` 강제 + D1의 선행 차단으로 **"잠재"로 하향**.
- `python3 scripts/harness/backlog.py validate` → green (등재 후 재실행).
- 태스크는 전건 `backlog.py add` CLI 경유(ID 손편집 0·번호 충돌은 CLI가 로컬+원격 양쪽 검사).

**전체 스위트 미실행 고지**: `src/` 무접촉이라 백엔드 전체 스위트는 돌리지 않았다. 침묵을 통과
주장으로 읽히게 하지 않기 위해 명시한다.

## §5-b. 정직한 공백

- **prod DB 실측이 아니다.** D1은 *코드·저장소 근거*로 확정한 주장이며, prod(whymath-pg·5433)에서
  `concept_visual_style`·`concept_visualization` 테이블 행수를 세어보지는 않았다. 두 테이블에 다른
  경로(수동 SQL 등)로 행이 들어가 있을 가능성은 배제하지 못한다 → `VIZ-01` acceptance ①이 실측한다.
- **분류율의 분모가 다를 수 있다.** 437은 `concept_graph_v1` 파일 기준이다. prod는 2,683 concepts로
  적재된 기록이 있어(`G-retired-atom-prod-cleanup` evidence) **런타임 분모는 더 클 수 있다**.
- **도달 0회의 라이브 재현은 하지 않았다.** 실제 학생 계정으로 `/v1/scenes/weak-concept`를 호출해
  응답에 `VisualizationElement`가 없음을 확인하지는 않았다 → `VIZ-01` acceptance ②로 이관.
- **실기기 확인 없음** — Flutter 봉투 주입·seed 폴백은 코드 읽기 기반이다. 실기기 구동은 백엔드
  기동 + 두 dart-define 선결이 필요해 이 세션 범위 밖.
- **`05a_learning_scene_dsl.md`(24KB) 미완독** — Scene DSL 6 element kind와 `VisualizationType`의
  역할 분담은 `part7_math_ui_dsl_review.md` 요약 경유로만 파악했다. **두 DSL(Scene vs Visualization)의
  중복 여부는 본 편이 다루지 않은 축**이며, 필요하면 후속 편으로 분리해야 한다.
- **세부 40개 중 일부는 grep 기반 판정** — 다른 명명으로 존재할 가능성을 배제하지 못한다.
  특히 기능 64의 "0건" 판정들이 여기 해당한다.
- **`S4-03` 승계 판정은 acceptance 문언 기반**이다. 그 태스크 착수 시 기하 spec 설계가 §1 기능 63의
  세부 9개를 전부 덮는지는 **그 시점에 재확인**해야 하며, 미커버가 남으면 정직하게 고지해야 한다.
- **의존성 해결 불가 부수 관측**: `src/backend`에서 `uv run`이 pyproject를 해결하지 못한다
  (`great-expectations`↔`pandas`↔`numpy`↔`rapid-latex-ocr` 충돌). 본 편의 런타임 증명은
  `--no-project`로 우회했다. 이 충돌은 본 편 범위 밖이나 `ARCH-22`(pytest-asyncio 무상한 pin)와
  같은 계열의 pin 위생 문제로 보인다 — **태스크화하지 않고 관측만 남긴다**.

---

## §6. 반복 실수 — "완비된 소비 경로 + 미적재/미배선 공급원" (재발방지 등재)

D1은 이 저장소에서 **처음이 아니다.** 같은 실패 *유형*이 최근 반복 관측된다:

| 사례 | 형태 |
|---|---|
| **D1**(본 편) | 시각화 소비 경로 완비 + 오버레이 2종 적재 호출 0 → 도달 0회 |
| 선행 자매편 D2(`S3-26`) | 개념 콘텐츠 437/437 충전 + `assessment=None` 무조건 → `can_render` 항상 False → 숙달 학생 **전 개념 404** |
| `OPS-03` | `tests/infra` 199건이 **어떤 CI 잡도 실행하지 않던** 상태 |
| `OPS-08` | 브랜치 보호 required check가 `enforcement_level=off·checks=[]`로 통째 미강제 |

공통 구조는 **"만들었다"와 "흐른다"의 혼동**이며, 공통 원인은 **연결 지점을 관측하는 지표의 부재**다.
네 사례 모두 *단위 테스트는 green*이었다 — 기전은 동작하고 배선만 없었기 때문이다.

CLAUDE.md 『실수 관리』는 **반복 실수(동일 유형 2회 이상)에 재발방지대책 등재를 의무**로 한다.
기존 규칙 *"❌ 검증 장치를 만들고 배선 확인 없이 완료 선언 금지"*가 이미 **검증 장치** 축을 덮고
있으므로, 본 편은 그 규칙을 **데이터 공급 축으로 일반화**할 것을 제안한다 — 즉
*"소비 경로를 만들면 그 경로에 실제로 데이터가 흐르는지(적재 호출·도달률) 확인한 뒤 완료로 친다.
'스키마가 있음'·'적재 함수가 있음'·'단위 테스트가 green'은 '흐른다'가 아니다."*

규칙 문안 확정은 CLAUDE.md 편집 권한 축이라 **본 문서에서 단독 개정하지 않고**, `VIZ-01`
acceptance의 도달률 리포트(기계 관측)로 먼저 못박고 MEMORY 결정 로그에 사고 경위를 남긴다.
규칙 등재 자체는 Kiki 확인 후 반영한다.

---

## §7. 2026-08-03 2차 점검 — `VIZ-01` 착륙 후 지형

> **범위**: §1~§6은 2026-07-30 시점(적재 0건·도달 0회 발견)의 기록으로 **그대로 보존**한다.
> 본 절은 `VIZ-01`(D1+D2, PR #654, 2026-07-31 착륙)이 실제로 무엇을 바꿨는지 재실측한 결과다 —
> 40개 세부 기능을 다시 훑는 재작업이 아니라, **적재가 배선된 뒤 처음 관측 가능해진 지형**을
> 새로 대조한다. 코드 변경 0(문서·백로그만) — §5 검증 원칙(전건 실행 확인)을 그대로 따른다.

### §7.0 실측 요약표

| 검사 | 결과 |
|---|---|
| `concept_visual_style_v1` 코퍼스 양식 분포(127건) | 입체도형 32 · 수직선 25 · 평면도형 16 · **함수그래프 15** · 벡터도 12 · 점화도 11 · 단위원 8 · 수형도 4 · 넓이모델 3 · 부등식영역 1 (멀티태깅 0건) |
| `VisualizationStyle → VisualizationType` 변환 코드 | **저장소 전체 0건** — `grep -rn VisualizationStyle --include=*.py src/backend`가 반환하는 것은 overlay 조회·enum 정의·ORM 컬럼·schema import뿐이며, 양식 값을 렌더 타입으로 사상하는 함수는 존재하지 않는다 |
| 양식이 L3 생성기에 전달되는 형태 | `l3/visualization.py:106` — `f"권장 시각화 양식(참고): {', '.join(...)}"` 자유 텍스트 프롬프트 힌트 1줄. 타입 선택에 구속력 없음(LLM이 4종 중 무엇을 골라도 이 문자열과 무관) |
| 렌더 가능 타입 | `data/render_contract.json` 4종 중 `animation_prerendered`는 `web_adapter: null` → 실제 렌더 가능은 3종 |
| `Graph2dSpec` 표현력 | `function`(`str`)·`domain`·`y_range`·`parameters` 4필드 — **명시적 y=f(x) 함수식만** 표현. 1D 구간(수직선)·implicit curve(단위원 `x²+y²=1`)·region(부등식영역)은 표현 불가 |
| `Surface3dSpec` 표현력 | `surface`·`rotatable` 2필드 — **z=f(x,y) 곡면만**. 다면체·전개도·입체도형 일반은 표현 불가 |
| `visualizability.json`(4분류) code 공간 | 7건 전건이 레거시 `concept_graph_v1` code(예: `HIGH-CALC-005`)이고 런타임은 `atom_graph_v1` code(예: `10공수1-02-05-1`) — **7/7 orphan**(`VIZ-01` PR이 부수 발견으로 이미 기록·"재작성은 범위 밖"으로 명시적 유보) |
| Flutter 렌더 폴백 | `scene_renderer.dart:104-121` — 렌더 3종 + `interactive=true` + 비어있지 않은 `spec`만 WebView, 그 외는 `_VisualizationSeed`(caption 카드)로 강등. **빈 화면 아님**(D3 하향 판정과 동형) |

### §7.1 G1(최우선) — 양식↔렌더 좌석 계약 부재: 태깅 127건 중 좌석 보유 24건(18.9%)

> **2026-08-03 구현 중 재감사로 정정.** 아래 표는 최초 §7.1 작성 시 "함수그래프만 seated"로 판단해
> 15건(11.8%)이라 썼으나, `VIZ-04` 착수 직전 재감사에서 이것이 **과소평가였다는 것을 발견**했다.
> 웹 계산기(`GraphingCalculator.jsx`)의 렌더 루프는 매 행마다 `mathExpr.js::classify()`로 문자열을
> 6가지(`function`·`implicit`·`inequality`·`polar`·`parametric`·`point`)로 분류해 타입별로 그리고
> (`drawFunction`·`drawImplicit`(음함수·마칭스퀘어)·`drawInequality`(부등식 **영역 반투명 색칠**)
> 등), `graph2dSpecToState`(`graph2dSpec.js:21`)는 `spec.function` 문자열을 그대로 상태에 얹을 뿐
> **파싱하지 않는다** — 즉 `Graph2dSpec.function`에 `"x**2+y**2=1"`(단위원)이나 `"y > x**2"`
> (부등식영역)를 넣으면 스키마 변경 없이 오늘 코드로 이미 렌더된다. 진짜 갭은 스키마가 아니라
> `l3/visualization.py`의 `_SYSTEM_PROMPT`가 `function`(순수 함수) 예시 하나만 보여줘 LLM에게
> 음함수·부등식 형태를 알려주지 않는 것이었다 — 렌더러는 할 수 있는데 생성기가 몰랐을 뿐이다.
> 정정 결과 **단위원·부등식영역이 seated로 이동**하고(둘 다 `interactive_graph_2d` 안에서 해결 —
> `VIZ-03`으로 넘길 필요 없음), 분포곡선(PDF는 x의 함수)·확률시뮬레이션(`simulation_probabilistic`)
> 도 seated에 추가된다(원 표는 태깅 10종만 다뤘으나 `VisualizationStyle` enum은 16종이라 완전성을
> 위해 미태깅 6종도 함께 판정한다). seated 5종·좌석 보유 15+8+1=24건(18.9%)이 정정된 수치다.

**좌석 대조(양식 16종 — `VisualizationStyle` enum 전체 × 렌더 타입 3종, 각 타입의 필드로 표현
가능한지 실측·정정 반영)**:

| 양식 | 건수(코퍼스) | 렌더 경로 | 판정 |
|---|---|---|---|
| 함수그래프 | 15 | `interactive_graph_2d`(`function` — classify "function") | ✅ 좌석 |
| 단위원 | 8 | `interactive_graph_2d`(`function`에 `"x**2+y**2=1"` — classify "implicit") | ✅ 좌석(정정) |
| 부등식영역 | 1 | `interactive_graph_2d`(`function`에 `"y > x**2"` — classify "inequality", 영역 색칠 존재) | ✅ 좌석(정정) |
| 분포곡선 | 0(미태깅) | `interactive_graph_2d`(PDF는 x의 함수 — classify "function") | ✅ 좌석(정정) |
| 확률시뮬레이션 | 0(미태깅) | `simulation_probabilistic` | ✅ 좌석(정정) |
| 수직선 | 25 | 없음(1D 축·구간은 classify 6종 밖) | ❌ → `VIZ-03` 확장 대상 |
| 접선도함수 | 0(미태깅) | 계산기 UI엔 `showTangent`/`showDeriv` row-state가 있으나 `Graph2dSpec`에 그 필드가 없어 spec→state 변환에 미연결 | ❌ → `VIZ-03` 확장 대상 |
| 입체도형 | 32 | `interactive_surface_3d`는 z=f(x,y) **곡면만**(다면체 아님) | ❌ → `S4-03` |
| 평면도형 | 16 | 없음 | ❌ → `S4-03` |
| 벡터도 | 12 | 없음 | ❌ → `S4-03` |
| 점화도 | 11 | 없음(재귀·계단 다이어그램 — classify 밖) | ❌ **어느 태스크 범위에도 없음**(§7.3) |
| 수형도 | 4 | 없음(분기 다이어그램) | ❌ **어느 태스크 범위에도 없음**(§7.3) |
| 넓이모델 | 3 | 없음(분배법칙 사각형 모델) | ❌ **어느 태스크 범위에도 없음**(§7.3) |
| 통계차트 | 0(미태깅) | 없음(범주형 집계 — classify 밖) | ❌ **어느 태스크 범위에도 없음**(§7.3) |
| 산점도 | 0(미태깅) | `point`(classify)로 다중 좌표 나열은 가능하나 연속 좌표쌍 정규식에 의존하는 임시방편 — 신뢰 가능한 좌석으로 인정하지 않는다(보수적 판정) | ❌ **어느 태스크 범위에도 없음**(§7.3) |
| 상자그림 | 0(미태깅) | 없음(사분위수 계산+전용 렌더) | ❌ **어느 태스크 범위에도 없음**(§7.3) |

`05b_visualization_classification.md` §3이 정본 파이프라인을 이렇게 그린다:

```
Concept.recommended_visual_styles   (교수학 힌트)
        ↓  ← ★ 이 화살표에 기계 계약이 없다(문서에만 있다)
Visualization.type                  (Intent)
        ↓     data/render_contract.json이 단일 진실원으로 못박음
L5 어댑터
```

두 번째 화살표(`type → 렌더러`)는 `render_contract.json`이 계약으로 봉인했다. **첫 화살표
(`양식 → type`)는 문서(05b §3 그림)에만 있고 기계에는 없다.** 양식은 LLM 프롬프트의 참고 문구로만
흐르고, 그 양식을 실제로 표현할 렌더 타입이 존재하는지는(정정 전에는) 아무도 확인하지 않았다.
좌석 대조표는 위(§7.1 도입부)로 옮겼다 — 정정된 24건(18.9%)이 최신 수치다.

**피해의 성격이 D1(도달 0회)보다 나쁘다 — 폴백이 아니라 오정보다(단, 정정으로 대상 범위는 좁아짐).**
D1 상태에서는 시각화 블록이 아예 `return`돼 학생이 아무것도 못 받았다. 지금은 게이트를 통과한
개념이 시각화 블록을 *받는다* — 그런데 (정정 전) LLM은 `_SYSTEM_PROMPT`(`l3/visualization.py:82-99`)
구조상 4종 중 하나를 **반드시** 골라야 했으므로, 예컨대 "입체도형" 권장 개념이 `interactive_graph_2d`
스펙을 받으면 **평범한 2D 포물선 그래프가 실제로 WebView에 렌더된다.** 빈 화면도 caption 카드도
아니라 *그럴듯하지만 개념과 무관한 그림*이다 — CLAUDE.md 『AI·신뢰』 "확실하지 않을 때 자신 있게
말함 패턴 금지"의 시각적 형태이며, 05b Part 5-1이 막으려 한 "억지 그림"이 정확히 이것이다(단,
§7.6에 남기듯 이 특정 오작동 자체는 *라이브 재현이 아니라 구조적 추론*이다). `VIZ-04` 구현이
이 위험을 `l4/visualization_policy.has_render_seat` 게이트로 봉인하고, `l3/visualization.py`
프롬프트에 관계식·부등식 예시를 추가해 단위원·부등식영역을 seated로 옮겼다.

그리고 **이것은 관측되지 않는다.** `harness/visualization_reach_report.py`(`VIZ-01` acceptance⑤)는
"게이트 통과 127(6.97%)"만 세고, *통과한 개념이 그 양식에 맞는 타입을 실제로 받았는지*는 축 자체가
없다.

**설계 → `VIZ-04-visual-style-render-seat-contract`(신규 등재·S3·priority 1)**:
- `data/visual_style_contract.json` 신설 — `render_contract.json`과 **동형 확장**(새 추상 0). 양식
  10종 각각에 `render_types`(표현 가능한 `VisualizationType` 부분집합) · `status`(seated|unseated) ·
  `seat_owner`(미좌석이면 담당 태스크 ID) 선언. 05b §3의 첫 화살표를 문서 → 기계로 승격한다.
- 미좌석 양식은 시각화를 억지로 만들지 않는다 — `l4/visualization_policy.py`에 좌석 판정을 추가해
  `추상` 분류와 **동형의 보류 신호**로 승격(새 게이트 신설이 아니라 기존 게이트의 두 번째 AND
  조건).
- L3 프롬프트(`_SYSTEM_PROMPT`)를 `render_contract`(렌더 가능) ∩ `visual_style_contract`(그 양식이
  허용하는 타입)의 교집합에서 파생 — `VIZ-02`(렌더 계약 파생)와 같은 지점을 건드리므로 두 태스크
  acceptance에 상호 참조를 넣어 중복 구현을 막는다.
- reach report에 "양식 정합 도달률" 축 추가 — **100%가 목표가 아니다**(미좌석은 보류가 정답).
  15/127을 눈에 계속 보이게 하는 것이 목표.
- 변별력: 계약에서 `함수그래프`의 `render_types`를 비우면 도달률이 15→0으로 떨어지는지 실측 →
  복원해 15 복귀 실측(성공/실패가 같은 값을 내면 검증이 아니라 위장 — CLAUDE.md).

### §7.2 G2 — 4분류 코퍼스 orphan 7/7: 추상 개념 보호가 런타임에서 0%로 무력

`visualizability.json`의 7건이 전부 레거시 code 공간이라 런타임에서 **단 하나도 매치되지 않는다**
(§7.0). `is_visualizable(None)`이 fail-open이므로 서비스 장애는 아니지만, 잃는 것이 둘이다:

1. **추상 보호 상실** — `HIGH-LOGIC-007`(대우증명·귀류법)은 05b가 "리터럴 그래프가 오개념 유발"로
   판정한 개념인데 orphan이라 게이트가 발동하지 않는다.
2. **직접/동적 구분 상실** — `prefers_static_visual(None) = False`이므로 **게이트를 통과한 127건
   전부에 슬라이더가 붙는다**(`scene_generation.py:296`). "직접"(정지 그림으로 충분) 개념에 불필요한
   조작을 주는 것은 05b가 명시적으로 피하려는 것이다.

1차 편 D2가 "적재되면 표면화된다"고 예고한 것이 **적재 후 실제로 표면화된 상태**다. CLAUDE.md
『상시 실패하는 fail-open 보호를 "보호 있음"으로 신뢰 금지 — 같은 실패가 2회+ 반복 관측되면
그 보호는 상시 무력 상태이며 태스크로 등재한다』가 정확히 발화한다(1차 편의 D2 예고 + 2차 편의
실측 = 반복 2회).

**설계 → `VIZ-05-visualizability-atom-backbone-realign`(신규 등재·S3·priority 2)**:
- 4분류 코퍼스를 원자 백본 code 공간으로 재정렬하되, **추상 축만** 보수적으로 복원한다(논리·증명
  계열처럼 리터럴 그래프가 명백히 해로운 것만). 4분류는 *인지 행동* 판정이라 키워드 규칙이
  위험하므로 직접·동적·부분은 재태깅하지 않고 미태깅 존치(억지 태깅이 억지 그림을 만든다 —
  `VIZ-01` acceptance③ 답습).
- orphan 게이트 신설 — 코퍼스 code가 런타임 code 공간에 존재하는지 CI 검사. "적재는 됐는데 매치
  0"은 이 저장소의 반복 실패 유형(§6)이므로 리포트 표시가 아니라 **기계 차단**(exit 1)으로 올린다.
- 변별력: 임의 개념 1건을 존재하지 않는 code로 바꿔 게이트 exit 1 실측 → 복원해 exit 0 실측.

> **2026-08-03 구현 완료(각주).** `visualizability.json`을 v1.2로 재작성 — `HIGH-LOGIC-007`(대우
> 증명·귀류법)을 원자 백본 code `10공수2-02-07-1`(name 완전 일치 확인)로 교체한 **1건짜리**
> 코퍼스로 축소했다(직접·동적·부분 6건은 계획대로 재태깅 없이 제거 — orphan 게이트와
> acceptance①의 보수적 축소가 만나는 지점에서 유일하게 성립하는 설계). orphan 게이트는
> `tests/backend/l1/test_concept_visualization_orphan_gate.py`로 신설(CI는 기존 `backend` 잡
> pytest 수집에 자동 편입 — 새 워크플로 불요, `tests/infra/test_test_suite_wiring.py`로 배선
> 재확인). 라이브 재현(코퍼스 로드 → `Visualizability.추상` → `l4/scene_generation`)으로
> 시각화 블록 생략·LLM 미호출을 실측했고, `harness/visualization_reach_report`로
> `visualization_matched_count` 0→1·orphan 7→0을 실측했다(변별력: 임의 code 주입 시 게이트
> fail→복원 시 pass 상태 전이를 실측 — 성공/실패 동일값 위장 아님).

### §7.3 G3 — 좌석 우선순위가 코퍼스 실측 분포와 무관 (기존 태스크 재정렬)

> **2026-08-03 재감사 반영**: §7.1 정정으로 단위원·부등식영역은 이미 seated다(별도 태스크 불요).
> 아래 "34건"·"1D 축 모드·implicit curve·region 색칠은 전부 `Graph2dSpec` optional 필드로 표현
> 가능"이라는 서술은 **정정 전 판단**이며, `VIZ-03`이 실제로 남겨 맡을 좌석은 **수직선 25 +
> 접선도함수(0·미태깅이나 enum 존재) = 25건+α**로 좁아진다. 아래 원문은 우선순위 비교의 맥락
> 보존을 위해 유지하고 수치만 이 각주로 정정한다.

`S4-03`(기하·벡터·행렬)과 `VIZ-03`(접선·적분영역·극값·함수비교)은 **둘 다 코퍼스 실측 분포를
보기 전에 쓰였다.** 실측 분포를 대면 우선순위가 달라진다:

- `VIZ-03`(기존 2D type의 필드 확장 — **새 type 0·anti-explosion 유지**)에 (정정 전 기준)
  **수직선 25 + 단위원 8 + 부등식영역 1 = 34건**의 좌석을 얹을 수 있다고 봤으나, 단위원·부등식영역은
  이미 seated이므로 `VIZ-03`이 남겨 맡는 것은 **수직선 25건 + 접선도함수**다. 1D 축 모드는
  `Graph2dSpec` optional 필드로 표현 가능하며 새 `VisualizationType`이 필요 없다 → 좌석 확보 효율이
  기존 acceptance①(함수그래프 15건 내부의 질 개선)보다 크다. `VIZ-03` acceptance①-b·notes로
  반영·`depends_on: VIZ-04` 추가(좌석 계약이 먼저 있어야 "무엇을 좌석으로 칠지"가 단일 진실원에서
  정의된다).
- `S4-03`이 덮는 것은 **입체도형 32 + 평면도형 16 + 벡터도 12 = 60건**(최대 덩어리) — 근거를
  `S4-03` notes에 명기해 S4 착수 시 우선순위 논쟁을 없앤다.
- **점화도 11 + 수형도 4 + 넓이모델 3 = 18건은 어느 태스크 범위에도 없다** — 구조 다이어그램 계열
  (05b §4.1의 `StructureGraph` 목표 아키텍처 소관). 지금 태스크를 만들면 dead task이므로 태스크화
  하지 않고 §7.4 미등재 트리거로만 남긴다.

### §7.4 미등재 트리거 (18건 미커버 — dead task 방지)

- **점화도·수형도·넓이모델(18건) 렌더 좌석**: 발화 조건 = 확률과통계·수열 성취기준 커버리지 착수
  시. 구조 다이어그램 계열이라 `Graph2dSpec`(함수식 기반) 확장으로 흡수되지 않고, `S4-03`의
  기하·벡터·행렬과도 다른 축(05b §4.1 `StructureGraph` 목표) — 지금 등재하면 세 번째 미정 계열이
  생겨 anti-explosion을 해친다. 커버리지 착수 시점에 `StructureGraph` 로드맵과 함께 재판정한다.

### §7.5 등재 요약

| 태스크 | 설계 | stage | 근거 | 상태 |
|---|---|---|---|---|
| `VIZ-04-visual-style-render-seat-contract` | §7.1 G1 | S3 | 태깅 127건 중 좌석 보유 18.9%(정정 후·원래 11.8%) — 억지 그림 위험 | **완료**(구현·2026-08-03) |
| `VIZ-05-visualizability-atom-backbone-realign` | §7.2 G2 | S3 | fail-open 보호 2회+ 반복 무력(CLAUDE.md 발화) | 신규 등재(todo) |
| `VIZ-02`(기존) | acceptance⑥ 추가 — `VIZ-04`와 합류 지점 상호 참조 | S3 | 같은 `_SYSTEM_PROMPT` 파생 지점 | 재정렬 |
| `VIZ-03`(기존) | 범위 축소(정정) — 수직선 25건 + 접선도함수(단위원·부등식영역은 제외 — 이미 seated) + `depends_on: VIZ-04` | S4 | 코퍼스 분포 근거 §7.3 | 재정렬 |
| `S4-03`(기존) | notes에 분포 근거(60건) + 18건 미커버 정직 고지 | S4 | §7.3 | 재정렬(승계·재설계 금지 불변) |

### §7.6 정직한 공백

- **prod DB 실측이 아니다** — 이 세션은 Phaiakes9 `whymath-pg`(5433)에 접근할 수 없다. 좌석 대조는
  코퍼스 파일·스키마 필드 기준이며, prod의 `concept_visual_style` 실제 행 분포가 코퍼스 파일과
  다를 가능성은 배제하지 못한다(`VIZ-01`의 프로덕션 CLI가 멱등 upsert이므로 일치가 기대되나 확인은
  아니다) → `VIZ-04` 착수 시 실측한다.
- **"LLM이 무관한 그래프를 만든다"는 §7.1의 결론은 구조적 추론이지 라이브 재현이 아니다** — 미좌석
  양식에서 LLM이 실제로 어떤 `type`을 고르는지 라이브 호출로 확인하지 않았다. 근거는 프롬프트
  구조상 4종 중 하나를 강제받는다는 사실이며, 실제 분포는 `VIZ-04` acceptance의 라이브 샘플로
  실측해야 한다.
- **Scene DSL vs Visualization DSL 중복 축은 이번에도 다루지 않았다** — 1차 편 §5-b가 "후속 편으로
  분리해야 한다"고 남긴 축이며, 2차 편도 범위 밖으로 둔다(다음 편 후보로 명기).
- **기능 64(애니메이션)·65(수학 모델 시뮬레이션)는 재점검하지 않았다** — 1차 편 판정(Manim 0건·
  `§4 트리거` / 물리·금융·SIR 등 페르소나 밖 🚫)에 영향을 줄 코드 변경이 그 이후 없었음을 `git log`
  로 확인한 것이 근거이며, 세부 재대조는 하지 않았다.
- **전체 스위트 미실행** — `src/` 무접촉(문서·백로그만)이라 백엔드 전체 스위트는 돌리지 않았다.
  침묵을 통과 주장으로 읽히게 하지 않기 위해 명시한다.
- **§7.1의 "억지 그림" 심각도는 D3 하향 판정과 같은 방식으로 재검토가 필요하다** — D3(§3)가
  "빈 화면"에서 "우아한 강등"으로 하향됐듯, §7.1도 실제로는 Flutter가 `spec`이 비어있지 않으면
  렌더한다는 조건(`scene_renderer.dart:104`)을 만족하는 한 렌더는 되지만 *내용이 개념과 어긋난다*는
  점이 D3과 다른 축이다 — `VIZ-04` 착수 시 라이브 재현으로 정직하게 재확정해야 한다.

---

## §8. 2026-08-10 3차 점검 — 회수·병합 이후 지형

> **범위**: §7 이후 착륙분 — `NLP-04`(고립 브랜치 회수·2026-08-08·#732), `VIZ-06`(극값 좌석
> 회수·2026-08-09·#740), `COLLAB-03`(학습 지표 롤업 writer·#752), `OPS-22`(선언≠배선 일반 탐지기
> 회수·#754) — 이 만든 새 지형을 재실측한다. 40개 세부 기능 재대조가 아니다 — §7.6이 남긴 공백 중
> 갱신된 것과 착륙분이 만든 어긋남만 다룬다. 방법: 3축 병렬 탐색(설계 문서 · 백엔드 코드 ·
> 클라이언트/백로그) 후 **아래 모든 판정 근거를 원문(파일:줄)으로 직접 재검증**했다(탐색 보고에서
> 오류 1건을 걸러냈다 — §8.5 ③). 코드 변경 0(문서·백로그만) — §7 방식 답습.
>
> **결론(3차)**: 착수 가설("`VIZ-01`~`06`으로 시각화 트랙은 정리됐다")은 **부분 기각**됐다. 스택
> 자체(명세→게이트→API→WebView 렌더→조작 이벤트 수집)는 건재하고 §7 이후 오히려 전진했다(극값
> 좌석·실 WebView 배선). 그러나 1차가 "만들어 놓고 연결하지 않았다", 2차가 "연결했더니 양쪽 어휘가
> 다르다"였다면, 3차는 **"회수·병합했더니 대장이 낡았다"**다 — ① `VIZ-03`이 done인데 §7이 확장한
> acceptance 2항(수직선 1D 축·좌석 계약 갱신)이 미이행인 채 좌석 계약이 done 태스크를 담당자로
> 지목하고 있고(§8.1), ② 감사기 EVENT 축이 `막힘`의 신규 소비자를 탐지 한계로 놓쳐 `S4-22`(세션
> 브리핑 다음 착수 후보 1위)의 범위가 실측과 어긋난다(§8.2). 둘 다 코드 실체가 아니라 **판정
> 장치·대장의 신선도**가 문제다 — 1차(코드가 문서보다 뒤)와 반대 방향의 drift이며, 방치하면
> 다음 착수 세션이 낡은 대장을 믿고 중복 배선(§8.2)·이중 착수(§8.1)를 하게 되는 능동적 위험이다.

### §8.0 실측 요약표

| 검사 | 결과 |
|---|---|
| `VIZ-03` YAML 상태 | `status: done` · `artifacts: [35e81dc1]` · acceptance ①-b(수직선 1D 축 모드 — 25건 흡수)·⑥(계약 파일 수직선 seated 갱신) 명시 존치 (`backlog/tasks/VIZ-03-graph2d-spec-expressiveness.yaml:17,22`) |
| `Graph2dSpec` 실제 필드(8종 전수) | `function`·`domain`·`y_range`·`parameters`·`tangent_point`·`integral_region`·`show_extrema`·`functions` (`schema/visualization.py:84-128`) — **1D 축/수직선 필드 없음**. 웹 어댑터(`graph2dSpec.js`)·계산기(`GraphingCalculator.jsx`)에도 `number_line`/`axis_mode` 매치 0 |
| `data/visual_style_contract.json` 수정 이력 | **유일 커밋 `c3376c42`(#698) 이후 무수정** — `35e81dc1`(VIZ-03 회수 포함 #732)·`ddfb130c`(VIZ-06 #740) 모두 이 파일 무접촉. `수직선`·`접선도함수` = `unseated`·`seat_owner: VIZ-03`(done 태스크 지목) (`:41-52`) |
| `_SEATED_STYLES` | 5종 유지(함수그래프·단위원·부등식영역·분포곡선·확률시뮬레이션) — 주석이 "접선도함수…표현할 렌더 타입이 없다"고 서술하나 `tangent_point` 좌석은 이미 스키마·웹 렌더러에 실재 (`l4/visualization_policy.py:41-51` ↔ `schema/visualization.py:97-104`) |
| `막힘` EventType 소비자 | **실재** — `COLLAB-03`이 `_SOCRATIC_EVENT_TYPES = frozenset({막힘, 힌트요청, 힌트제공})` + `.in_()` 필터로 소비 (`l2/learning_metrics_rollup.py:124-126,563`) |
| 감사기 EVENT 축 탐지 범위 | `consumed_event_types`는 `ast.Compare`(`event_type == EventType.X`)만 스캔 — frozenset 멤버십+`.in_()`은 구조상 탐지 불가 (`ops/declared_unwired_audit.py:358-376`). 대장은 `막힘`을 여전히 producer-only 유예로 보유 (`:794`) |
| `visualization_reach_report` CI | `_OFFLINE_REPORT`("빌드타임 관측 리포트·게이트 아님 — CI 상시 배선 대상 아님")로 **명시 등록 면제** (`ops/declared_unwired_audit.py:850`) |
| `/v1/visualizations/*` 3라우트 | 클라 소비 0 유지 — `by-design` 유예(슬라이스 95 모듈 docstring 근거·`/v1/scenes/weak-concept`와의 혼동 주의 병기) (`ops/declared_unwired_audit.py:733-745`) |
| "05 §5.2" 인용 실태 | 저장소 전역 **수십 곳**(CLAUDE.md:55 · `data/render_contract.json:4` authority 필드 · `schema/visualization.py`·`enums.py`·`l3/visualization.py`·`l4/learning_scene.py` docstring · 테스트 · 마이그레이션 · MEMORY 결정 로그 8건+)이 정본 앵커로 인용 — 그러나 `05_interaction.md`에는 **§5.2라는 번호 섹션이 실존하지 않는다**(실체는 `:120-151` 무번호 헤딩 `## 시각화 스택`/`### PRD 신규 — 선언적 시각화`) |
| Flutter 실 렌더 경로 | `chat_screen.dart:242-246`(수동 버튼) → `POST /v1/scenes/weak-concept` → `scene_renderer.dart:106-125`(3종 type+interactive+spec 조건) → `graphing_calculator_webview.dart`(vendored 자체 계산기 SPA — three.js·MathLive 번들·`file://`) → 조작 이벤트 `POST /v1/interactions`(600ms 디바운스) — **1차 판정 이후 실 WebView까지 전진 완료** |
| Flutter 주석·문서 신선도 | `scene_renderer.dart:9-10` 헤더가 "시각화는 실 WebView가 아니라 caption/type seed다…연동은 후속"이라 서술(사실과 반대) · `:103-105` docstring "확률…은 아직 seed" ↔ 바로 아래 `:107-111` `webViewTypes`가 `simulation_probabilistic` 포함(직접 모순) · `scene_models.dart:24-25` 동일 stale · `pubspec.yaml:43` `# 웹뷰 (Desmos·GeoGebra)`(실소비는 자체 계산기+MathLive) |

### §8.1 R1 — `VIZ-03` done ↔ acceptance ①-b·⑥ 미이행: 좌석 계약이 완료된 태스크를 담당자로 지목

**타임라인(원문 재구성)**:
1. **2026-08-03 §7.3** — `VIZ-03` 범위 확장: acceptance ①-b(수직선 1D 축 모드 — 코퍼스 2위
   덩어리 25건 흡수)·⑥(`visual_style_contract.json` 수직선 unseated→seated 갱신) 추가. 이때
   `VIZ-03`은 todo였다.
2. **2026-08-08 `NLP-04`** — 공통 조상 없는 고립 브랜치(`openrouter-setup-guide-e98dw4`)에서
   VIZ-03 아티팩트를 파일 내용 대조로 이식(`35e81dc1`·#732). 이식된 것은 **§7 확장 이전에 그
   브랜치에서 구현된 3좌석**(접선·적분영역·함수비교)이다 — 고립 브랜치는 main의 08-03 acceptance
   확장을 알 수 없었다. 회수 세션은 코드에서 마주친 극값 좌석은 범위 분리(→`VIZ-06` 재등재·주석
   기록)했지만, **코드에 없는 확장분 ①-b·⑥은 대조 대상에 나타나지 않아 그대로 지나갔고**(의도적
   제외 기록 없음 — MEMORY 2026-08-08 NLP-04 항에 극값 분리만 있고 수직선 언급 0), `VIZ-03`을
   done 처리했다.
3. **결과(현재)**: `Graph2dSpec`에 1D 축 필드 없음 · 계약 파일의 `수직선`이 done 태스크를
   `seat_owner`로 지목 — **"완료된 담당자를 기다리는 좌석"**이라는 결정 불가 상태. 역방향 drift
   동반: `tangent_point`는 스키마·웹 렌더러에 착륙했는데 `접선도함수`는 계약상 여전히
   unseated·owner=VIZ-03(구현은 앞서고 계약이 뒤처진, ①-b와 반대 방향).

**피해의 성격**: §7.1의 "미좌석 = 소크라테스 폴백" 게이트(`has_render_seat`)가 살아 있으므로
학생 대면 오작동은 없다(억지 그림 아님 — 보류가 작동 중). 잃는 것은 ⓐ 수직선 25건(코퍼스 2위)의
도달이 **주인 없는 상태로 무기 연기**된다는 것 — 태스크 대장에서 이 좌석은 "done"으로 보이므로
`backlog.py next`가 다시 잡아주지 않는다 — 과 ⓑ `접선도함수`처럼 이미 열린 좌석이 계약 미갱신으로
계속 닫혀 보인다는 것이다. §6의 반복 실수("완비된 소비 경로 + 미배선 공급원")의 변형이며, 이번에는
공급원이 아니라 **대장(계약·백로그)이 낡았다**.

**설계 → `VIZ-07`(신규 등재·잔여 이행)**: done 태스크의 status를 손으로 되돌리지 않는다(deny 우회
금지 — 상태 변경은 CLI 소관이고, done 처리 자체는 회수 세션의 판단 기록이다). 대신 미이행분을
신규 태스크로 승계한다(`PED-06`→`PED-08` 선례):
- ① `Graph2dSpec`에 1D 축 모드 필드 확장(웹 어댑터 `graph2dSpec.js`·계산기 렌더·Flutter 봉투
  동반 — `VIZ-03` acceptance ③·⑤의 교차 게이트·변별력 조항 준용). 수직선은 렌더러에 1D 렌더
  능력이 없다면 "렌더러 먼저, 좌석 나중"(`VIZ-06` 원칙)에 따라 렌더 경로부터 이식·구현한다.
- ② 계약 파일 `수직선` seated 갱신 + `_SEATED_STYLES` 동기(JSON↔Python drift 교차 테스트가
  이미 존재 — `test_visual_style_render_contract.py`).
- ③ `접선도함수`는 웹 어댑터가 `tangent_point`를 실제 소비함을 실측한 뒤 seated 갱신(계약
  갱신만으로 해소되는 반대 방향 drift — 실측 없이 갱신 금지).

> **2026-08-10 구현 완료(각주 — 본 점검과 같은 날 `/drive`로 착지·커밋 `6d24a585`).**
> `Graph2dSpec.number_line`(NumberLinePoint·Interval·Spec — 점 ●/○·구간·반직선·개폐 끝점, 축
> 범위는 `domain` 재사용) + 웹 계산기 1D 렌더 경로 `drawNumberLine` 신설(기존 관용구만 조합 —
> 축·눈금·이중원·구간 색칠층, 신규 수치 primitive 0 — VIZ-06 「렌더러 먼저」 순서 준수) +
> 수직선(`render_mode: "number_line"` 신규 어휘)·접선도함수 seated·`_SEATED_STYLES` 7종 동기 +
> 프롬프트 예시 확장(#703에서 유실된 VIZ-04 관계식·부등식 예시 복원 동반) + `viz_eval` 1D 완성도
> 분기. 변별력 실측: JSON↔Python drift 게이트 red→green / JS 테스트 선작성 red(4 failed)→green
> (68→134 passed). 검증: 백엔드 전체 스위트 **9230 passed·302 skipped·0 failed**(무작위 순서·
> 558s) · 웹 134건(커버리지 4축 98%+) · ruff/black/mypy strict(482파일)/lint-imports 전부 exit 0.
> **정직한 이연**: 점프 화살표류 4건·내분 비율분할 전용 표기는 v1 미지원(points/intervals 조합
> 근사 — 스키마 docstring 명기). **부수 발견·해소**: vendored 계산기 번들이 생성 커밋(`c3376c42`)
> 부터 자기 소스보다 낡게 동기화돼 VIZ-03·VIZ-06 좌석·봉투 디스패치가 실기기 번들에 없었음(문자열
> 프로브 실측 — WebView 임베드·봉투 인코더가 같은 커밋 착륙이라 실기기 spec 렌더는 착륙 후 한 번도
> 성립하지 않았을 가능성이 높다. 코드 경로 추론이며 실기기 실측 아님). 본 커밋이 번들 재동기화로
> 해소(신규 번들 `index-DJ9D7N0L.js` 프로브 6종 전부 존재), 재발 방지 CI 게이트는 `OPS-26` 등재.

### §8.2 R2 — 감사기 EVENT 축의 세 번째 탐지 사각: `막힘`은 이미 소비되고 `S4-22` 범위가 낡았다

`OPS-22` 회수 커밋(#754)은 TIMESERIES 축에서 감사기 오탐 2종(별칭 import·bulk upsert 미탐지)을
고친 뒤 `COLLAB-03` 유예를 걷었다 — "탐지되지 않으니 유예를 계속 둔다"가 아니라 "탐지기가 틀렸으니
탐지기를 고친다"(`declared_unwired_audit.py:802-804` 자기 서술). 그런데 **같은 커밋의 EVENT 축에
같은 클래스의 세 번째 사각이 실려 있다**:

- `COLLAB-03`(#752 — #754보다 먼저 착륙)의 `l2/learning_metrics_rollup.py`가 `막힘`을
  `frozenset` 상수 + `.in_()` 멤버십 필터로 실소비한다(`:124-126,563` — 소크라테스 상호작용
  지표로 집계). 이것은 진짜 소비다(값을 읽어 지표에 쓴다).
- 그러나 `consumed_event_types`(`:358-376`)는 `ast.Compare`(`event_type == EventType.X`)만
  탐지한다 — `.in_()`은 `ast.Call`이라 구조상 보이지 않는다. 그래서 대장 `AXIS_EVENT`(`:794`)는
  `막힘`을 여전히 producer-only로 유예 중이고, **stale-waiver 게이트도 발화하지 않는다**(탐지기가
  못 보므로 유예가 "아직 유효"해 보인다 — 성공/실패가 같은 화면을 내는 상태).
- 파급: `S4-22` acceptance ①의 "3종 소비자 0건"이 이제 거짓이다(진짜 producer-only 잔여 =
  `답입력`·`시각화조작` 2종). `S4-22`는 세션 브리핑 다음 착수 후보 1위라, 방치하면 다음 세션이
  `막힘` 소비자를 **중복 배선**한다.

**설계 → 두 갈래 분리**:
- **`S4-22` YAML 범위 정정(본 점검 커밋에서 즉시)** — acceptance ① 3종→2종 재서술 + notes에
  `막힘` 소비 실재 근거 병기(`S3-25` 범위 축소 선례·status 무변경). 착수 전 정정이 목적이므로
  탐지기 수리를 기다리지 않는다.
- **`OPS-25`(신규 등재) — 탐지기 수리 + 유예 정리**: `consumed_event_types`에 멤버십 소비
  탐지(컨테이너 리터럴/상수 경유 `.in_()`) 추가 → `막힘`이 reached로 전환 → `AXIS_EVENT`에서
  `막힘` 유예 제거(제거하지 않으면 stale-waiver가 exit 1 — 게이트가 정정을 강제하는 순서 그대로) →
  frozenset 픽스처 회귀 테스트로 사각 재발 동결. 생산 좌석(`event_type=X` 키워드 인자)을 소비로
  오인하지 않는 기존 설계 의도(`:361-362`)는 유지한다.

### §8.3 R3 — 문서·주석이 사실보다 낡은 곳들 (1차와 반대 방향의 drift 일괄)

1차 점검의 발견이 "코드가 문서에 못 미친다"였다면, 이번에 확인된 것은 전부 **코드가 문서·주석을
앞질렀다**이다:

| # | 위치 | 어긋남 |
|---|---|---|
| ① | 전역 "05 §5.2" 인용 ↔ `05_interaction.md` | 정본 앵커 번호가 실존하지 않음(§8.0 표) — 인용이 수십 곳이라 **인용 측 수정은 오답**, `05_interaction.md`의 해당 헤딩에 번호를 부여해 앵커를 실체화하는 것이 유일하게 싼 방향 |
| ② | `05_interaction.md:124-128,142,148` + `CLAUDE.md:80` 스택 표 | "Desmos·GeoGebra 임베드 유지/공존" 서술 ↔ §2-⑤가 **의도적 미채택으로 확정**(자체 계산기 2,141행·미성년자 데이터 제3자·CDN 오프라인 역행·2 비상구 원칙) + 실코드 0건 + 구현체명 금칙어 게이트(`test_visualization_state_separation.py:62-63`)가 오히려 `desmos`/`geogebra` 유입을 차단 중. 스택 표 갱신은 MEMORY 결정 로그 의무 동반 |
| ③ | `00_overview.md:13` | L5 블록이 `[Mathpix OCR·Manim·Desmos·음성·대화]` — Mathpix는 2026-05-28에 PaddleOCR+Qwen3-VL로 대체 확정(`05_interaction.md:126`), 미반영 |
| ④ | `scene_renderer.dart:9-10`·`:103-105` / `scene_models.dart:24-25` / `pubspec.yaml:43` | §8.0 표 마지막 행 — 실 WebView 배선 완료 사실과 반대·코드와 직접 모순인 주석 4곳 |
| ⑤ | `l4/visualization_policy.py:41-42` 주석 | "접선도함수…표현할 렌더 타입이 없다" — `tangent_point` 착륙(#732) 이후 사실 아님(§8.1 역방향 drift와 동일 원인, `VIZ-07` ③에서 좌석 갱신과 함께 정정) |

**설계 → `VIZ-08`(신규 등재·행동 무변경 일괄)**: ①~④를 한 태스크로 묶는다(⑤는 `VIZ-07` ③ 소관).
전부 문서·주석만이며 행동 변경 0 — 단 `CLAUDE.md` 스택 표(②)는 마스터 가이드라 MEMORY 결정 로그를
함께 남기고, ①은 번호 부여가 기존 인용(MEMORY 로그 포함)과 정확히 일치하는지 대조 후 반영한다.

### §8.4 R4 — 명세 축의 수학 검증 공백: SymPy가 시각화에만 없다

`l3/visualization.py:14-16`이 스스로 남긴 "spec 내 함수식 SymPy 검증은 후속"이 그대로다 — 같은
docstring의 다른 후속(타입별 typed spec)은 `VIZ-03`~`06`으로 착륙했는데 이 항만 남았다. 현재 검증
게이트는 Pydantic 구조 검증(typed spec·불변식)뿐이라, LLM이 만든 `function` 문자열이 **파싱조차
불가능한 식**이어도 명세는 통과하고 실패는 클라 렌더러(웹 `classify()`)까지 내려가서야 드러난다.
OCR 축은 SymPy 검산을 쓰는데(`l5/ocr/verify.py`) 시각화 축만 0인 비대칭이기도 하다. "LLM 응답을
검증 없이 학생에게 제공 금지 — PRM 또는 도구 검증 필수"(CLAUDE.md)의 압력이 실재하므로 미등재
트리거가 아니라 태스크로 올린다.

**설계 → `VIZ-09`(신규 등재)**: `parse_visualization_spec` 게이트에 `function`·`functions`
sympify 파싱 검사 추가 — 파싱 실패 시 명세 거부(기존 실패 경로 = 시각화 블록 생략·소크라테스
폴백 재사용, 새 폴백 신설 0) + 예외 타입명 로그(침묵 실패 금지). **범위 상한**: 파싱 가능성만
본다 — "개념과 어울리는 그래프인가"(의미 정합)는 라이브 평가(`viz_eval`) 소관으로 남긴다(§8.6 ②).

### §8.5 갭 아님 판정 (이번 점검에서 해소·기각된 후보)

| # | 후보 | 판정 |
|---|---|---|
| ① | `/v1/visualizations/*` 3라우트 클라 소비 0 | **갭 아님** — 대장 규약상 정합한 `by-design` 유예(슬라이스 95 docstring 근거·`/v1/scenes/weak-concept`와의 혼동 주의까지 병기, `declared_unwired_audit.py:730-745`). 재평가 트리거 = L5 프런트(별도 웹) 착수 시 |
| ② | `visualization_reach_report` CI 미배선 | **갭 아님** — `_OFFLINE_REPORT` 명시 면제(`:850`). 단 `VIZ-01` acceptance ⑤("도달률 리포트 CI 배선")의 문구와 최종 판정이 어긋난 채 남아 있어 기록상 혼선 소지만 있다 — 면제 사유가 대장에 있으므로 태스크화하지 않고 여기 기록만 |
| ③ | `visualize_misconception` 호출자 0 "백로그 미등재" | **탐색 보고 오류로 기각** — `MISC-01-visualization-shadow-rollout`(S3·todo)이 정확히 이것을 커버한다(YAML 원문 확인). 함수 docstring의 "패턴 게이트 무효" 자인도 MISC-01 notes의 04e §1-1 참조 범위 안 |
| ④ | `animation_prerendered` 생산·렌더 경로 0 | **기존 판정 유지** — 의도적 dormant(`VIZ-02`가 생성 경로 봉인·`S4-03`이 복귀 조건·`import manim` 금지 게이트 존재) |
| ⑤ | 문제 풀이 화면에 시각화 진입점 0 | **관찰로만 기록** — 시각화는 코치 채팅의 수동 버튼 단일 진입(§8.0 표). 문제 화면 결합은 MOB 트랙(진행 중 claim 존재) 소관이라 이번에 태스크화하지 않는다 |

### §8.6 미등재 트리거 (dead task 방지 — 발화 조건만)

- **§7.4의 18건(점화도·수형도·넓이모델) 미커버** — 유지. 발화 조건 불변(확률과통계·수열 성취기준
  커버리지 착수 시 `StructureGraph` 로드맵과 재판정).
- **viz 생성 라우팅 패밀리 보정(MATH→GENERAL)** — `l3/viz_eval.py:17-21`이 스스로 기록한 대로
  "평가가 근거를 만든 뒤 별도 결정"이다. 발화 조건 = `test_visualization_live`(integration
  마커·GPU 필요)의 패밀리별 유효율 실측 확보 시. 실측 없이 라우터를 바꾸는 것은 이 저장소의
  환경 사실 추론 등재 금지에 걸린다.
- **Manim 서버 렌더 파이프라인** — §4 트리거 불변(`S3-01` 파일럿의 동적 분류 학습 손실 측정 +
  렌더 워커 capacity). `ROADMAP.md:85` PoC 미완 상태도 불변.

### §8.7 등재 요약

| 태스크 | 설계 | 성격 | 상태 |
|---|---|---|---|
| `VIZ-07` | §8.1 — VIZ-03 잔여 이행(수직선 1D 축 + 수직선·접선도함수 좌석 갱신) | 코드+계약 | 신규 등재(todo) |
| `OPS-25` | §8.2 — 감사기 멤버십 소비 탐지 + `막힘` 유예 정리 + 회귀 동결 | 코드(감사기) | 신규 등재(todo) |
| `VIZ-08` | §8.3 — 문서·주석 정합 일괄(05 §5.2 앵커 실체화·Desmos/GeoGebra 서술 정정·stale 주석) | 문서·주석(행동 무변경) | 신규 등재(todo) |
| `VIZ-09` | §8.4 — 명세 함수식 sympify 파싱 게이트 | 코드(검증 게이트) | 신규 등재(todo) |
| `S4-22`(기존) | §8.2 — acceptance ① 3종→2종 범위 정정(막힘 제외) | YAML 정정 | 본 점검 커밋 반영 |

### §8.8 반복 실수 — "회수 done 선언 시 acceptance 전수 재대조 누락" (재발방지 등재)

§8.1의 원인 구조는 이 저장소의 기존 규칙 두 개 사이의 사각이다: "검증 장치를 만들고 배선 확인
없이 완료 선언 금지"는 *만든 것이 도는가*를, "정본화를 집행으로 착각한 완료 선언 금지"는 *계약을
부르는가*를 묻는다 — 그런데 회수(recovery)는 **"브랜치에 있던 것"을 기준으로 완료를 선언**하므로,
main에서 그 사이 확장된 acceptance는 어느 검사에도 나타나지 않는다(코드 대조는 존재하는 코드만
보고, 존재하지 않는 코드는 대조 실패조차 내지 않는다). `NLP-04` 자신이 이미 "태스크 paths는 회수
범위의 신뢰할 근거가 아니다 — `git diff --name-only`로 전수 열거"를 등재했는데, 이번 건은 그
대우다: **diff에 없는 것(미이행 acceptance)은 diff 전수 열거로도 안 보인다.** 대책은 CLAUDE.md
프로세스 금기에 규칙 1건으로 등재한다(회수·이식으로 태스크를 done 처리하기 전, 그 시점 main의
acceptance 전수를 항목별 이행/미이행/의도적 제외로 재대조하고 미이행분은 승계 태스크로 분리) —
본 점검 커밋에 포함.

### §8.9 정직한 공백

- **§7.6의 공백 중 이번에도 그대로인 것**: prod DB 실측 없음(좌석 대조는 코퍼스 파일·스키마 기준) ·
  "무관한 그래프" 라이브 재현 없음 · Scene DSL vs Visualization DSL 중복 축 미착수(**3차에서도
  다음 편 후보로 유지** — 1차 §5-b부터 3회 연속 이월이므로 4차가 있다면 최우선 후보다) · 기능
  64·65 세부 재대조 없음 · 실기기 확인 없음.
- **`막힘` 소비의 "지표 정확성"은 검증하지 않았다** — §8.2는 *소비자가 존재한다*(값을 읽어 집계에
  쓴다)까지만 원문으로 확인했다. 그 집계가 교수학적으로 옳은 지표인지는 `COLLAB-03` 소관이며 이번
  범위 밖이다.
- **`graph2dSpec.js`의 `tangent_point` 소비는 코드 존재만 확인했다** — 스키마 docstring과 §7.1
  표의 서술 근거이며, 실브라우저 렌더 확인은 `VIZ-07` ③의 acceptance로 넘긴다(실측 없이 좌석
  갱신 금지를 그 태스크에 명문화했다).
- **전체 스위트 미실행** — `src/` 무접촉(문서·백로그·CLAUDE.md·MEMORY만)이라 백엔드 스위트는
  돌리지 않았다. 침묵을 통과 주장으로 읽히게 하지 않기 위해 명시한다.
- **태스크 ID는 등재 시점에 확정된다** — 본 절의 `VIZ-07`~`09`·`OPS-25`는 후보 ID이며,
  `backlog.py add`(HARN-10 번호 충돌 검사)가 거부하면 CLI 제안 번호를 따른다(그 경우 본 문서의
  ID 표기를 등재 결과로 정정한다).
