# Subject Contract v1 — 후보 9종 전수 판정 (EOS-90 · 계획서 100 §3.9 · 2026-09-04)

> Kiki 제시: *"모든 과목이 EOS와 통신하는 최소 계약. 다만 인터페이스를 지나치게 크게 만들면 안 된다.
> **과목마다 반드시 존재하는 능력만** 넣는다 — `evaluateAnswer()`는 공통성이 높지만
> `renderEquation()`은 Math 전용이다."*
>
> 이 문서는 그 원칙을 9후보에 **기계적으로** 적용한 기록이다. 판정 자체는 코드가 기억한다
> (`tests/backend/schema/test_subject_adapter_two_tier_contract.py`의 `CANDIDATE_VERDICTS`).
> **결론부터: v1은 필수층 3메서드를 그대로 둔다.** 이 문서의 산출물은 계약 변경이 아니라 *변경하지
> 않는다는 판정의 근거*다.

## 판정 결과

| # | Kiki 후보 | 판정 | 한 줄 근거 |
|---|---|---|---|
| 1 | `evaluateAnswer()` | **필수층** | 채점 없는 과목은 없다 |
| 2 | `detectMisconception()` | **필수층** | 오답 원인 분석은 과목 무관 |
| 3 | `validateProblem()` | **필수층** | 낼 수 있는 문제인지의 판정 |
| 4 | `getConcept()` | 계약 아님 — **데이터** | `Concept` 15컬럼 전부 과목 중립·`subject` 컬럼은 이미 제거 |
| 5 | `getPrerequisites()` | 계약 아님 — **데이터** | `EdgeType` 6종 전부 학습과학 어휘·수학 어휘 0 |
| 6 | `getLearningObjectives()` | 계약 아님 — **데이터** | 성취기준은 FK 아닌 crosswalk·Core에 코드 파서 0건 |
| 7 | `estimateDifficulty()` | 계약 아님 — **Core 소유** | `l2.irt`가 응답 통계만으로 b를 추정(문항 내용 미참조) |
| 8 | `generateExplanation()` | 계약 아님 — **어댑터 내부** | 위임할 공개 진입점 0건(EOS-66 기판정) |
| 9 | `getRepresentations()` | **선택층 후보**(재설계 전제) | 유일하게 능력이지만 반환 타입이 현재 수학 전용 |

## 판정 기준 — 4축

원칙("과목마다 반드시 존재하는 능력만")을 그대로 쓰면 감이 개입한다. 네 질문으로 조작화했다.

1. **능력인가 데이터인가.** 이미 과목 중립 스키마에 *데이터로* 존재하면 Physics는 행만 채우면
   되므로 계약이 필요 없다. 결정적 구분은 **조회(read) vs 계산(compute)** 이다 — 기존 필수 3메서드는
   전부 *입력을 받아 판정을 내리는 계산*이고, 4~6번 후보는 *테이블에서 행을 읽는 조회*다.
2. **과목 지식을 요구하는가.** 학생 응답 통계만으로 산출되면 그것은 과목의 능력이 아니라 Core의 능력이다.
3. **Physics·Chemistry·History에 *반드시* 존재하는가.** 아니면 선택층이다. 없는 과목이 빈 구현을
   강요당하면 그 빈 구현이 "판정했다"는 거짓 신호가 된다.
4. **Core가 반환값을 해석해야 하는가.** 해석해야 하면 EOS-66의 불투명 페이로드 원칙과 충돌한다.

## 4~6번이 데이터인 근거 (조회 vs 계산)

- `Concept` ORM 15컬럼에 수식·LaTeX·수학 영역 컬럼이 **0개**다(`db/models/concept.py:55-164`).
  수학성이 있던 4컬럼(`description`·`formal_definition` 등)은 2026-07-03 redaction으로 제거됐다.
- **`subject` 컬럼은 이미 개념 테이블에서 빠졌다**(`concept.py:98`, rev f3a4b5c6d7e8) — 과목 축은
  Overlay(`CurriculumEntry.subject`, **str·enum 아님**)에 산다. `schema/enums.py:1495`가 그 선택을
  명시한다("subject는 enum으로 만들지 않는다").
- `EdgeType` 6종 = `PREREQUISITE`·`COMPOSED_OF`·`ANALOGOUS_TO`·`EXTENDS`·`CONTRASTS`·
  `TRIGGERS_DISTRACTOR`(`schema/enums.py:994-1018`). 전부 학습과학 어휘다. 물리의 "운동량 보존을
  알아야 충돌을 안다"도 같은 `PREREQUISITE` 행이다.
- 성취기준은 별 테이블이고 개념과는 **FK가 아니라 crosswalk**로 붙는다
  (`concept_standard_link.py:61` "느슨참조 — FK 아님"). 성취기준을 통째로 물리 세트로 갈아도 개념
  노드는 무손상이다 — CLAUDE.md "Curriculum은 Overlay"가 코드로 지켜지고 있다.
- **Core에 성취기준 코드 파서가 한 줄도 없다.** 코드를 불투명 문자열로 실어 나를 뿐이다
  (`api/alignments.py:83-93`). 파서는 data-pipeline에만 있고, 물리·화학 코드를 **이미 통과시킨다**
  (`ncic/models.py:81-82` — 회귀 테스트로 동결). 즉 "과목 전용 능력"의 증거가 아니라 그 반증이다.
- 개념·선수를 **어댑터 경유로 읽는 코드가 저장소 전체에 0건**이다. 전부 순수 ORM 조회이며 과목
  분기가 없다(`api/concepts.py:307-345` · `l2/prerequisite_recommendation.py:322` 재귀 CTE).

이걸 계약에 넣으면 어댑터가 DB 세션을 들고 ORM을 감싸는 얇은 위임층이 되고, `schema`가 `db`를
알게 되어 계층 역방향이 된다(`schema/subject_adapter.py`의 "왜 schema에 사는가" 위반).

**Physics 온보딩에 필요한 것은 어댑터 메서드가 아니라 데이터 적재 3종이다** — 교육과정 항목,
성취기준, 개념·선수 엣지.

## 7번이 Core 소유인 근거

저장소에 `estimate_difficulty`라는 **동명이인 함수가 두 계층에 있다**.

| | 위치 | 입력 | 과목성 | Core 소비처 |
|---|---|---|---|---|
| 응답 통계 축 | `l2/irt.py:101` | `(θ, 정답여부)` 쌍만 | **과목 무관** — 문항 내용을 한 글자도 안 본다 | 있음(적응 출제·추천·θ 추정) |
| 내용 축 | `l3/equivalent/difficulty.py:56` | `root_kind`·`lead_coefficient` | **수학 전용** — 인자가 근의 유형이다 | **0건** |

Core가 실제로 쓰는 것은 응답 통계 축이고, 그건 **Core가 이미 스스로 하는 일**이다
(`l2/irt.py:144` `fit_jmle` → `l2/item_calibration.py:57`이 `Problem.irt_difficulty_b`에 영속).
계약에 올리면 Core가 자기가 가진 능력을 과목에 되물어보는 꼴이 된다. 내용 축은 Core 소비처가
0건이라 `generateExplanation`을 v1에서 뺀 논리(위임 진입점 0)가 그대로 적용된다.

과목 지식이 필요한 유일한 부분은 **부트스트랩 라벨**(응답이 쌓이기 전 초기값)이고, 저장소는 이것을
계약이 아니라 **데이터**로 다룬다(`difficulty_overall`은 코퍼스 컬럼).

> **정직한 단서**: 진짜 문제는 계약 층위가 아니라 **보정 트리거 부재**다. `item_calibration.py`
> docstring이 "운영 트리거(주기 배치·증분 적합·엔드포인트)는 후속"이라 적고, 그 결과 실효 b는
> `difficulty_overall - 3.0`이라는 자칭 "휴리스틱 프록시"(`l2/ability_estimation.py:28-35`)다.
> 여기에 계약 메서드를 더하면 배선 부채를 계약 확장으로 위장하게 된다.

## 9번이 선택층 "후보"인 이유 — 지금 형태로는 계약이 될 수 없다

`getRepresentations()`는 9후보 중 **유일하게 진짜 능력**이다. 그리고 선택층 요건("능력이 없을 때의
경로를 Core가 반드시 갖는다")도 이미 충족돼 있다 — `is_visualizable()`이 추상 개념에 False를 주면
소크라테스·단계로 폴백하고(`l4/visualization_policy.py:25-32`), Overlay 행 부재는 `[]`를 반환한다.

그러나 **반환 타입이 수학 전용**이다. `VisualizationStyle` 16종이 전량 수학 어휘다(단위원·수형도·
접선도함수…, `schema/enums.py:318-378`). History의 표현(연표·역사지도·인과연쇄도·사료)은 이 16종에
하나도 없다. 지금 형태로 필수화하면 History 어댑터는 빈 배열을 반환하게 되고, 빈 배열은 "표현이
없다"와 "표현을 판정하지 못했다"를 구분하지 못한다.

**따라서 선택층 등재의 전제는 중립 반환 타입 재설계다** — 불투명 style code 문자열 + 렌더 좌석 술어.
그 전에는 "계약 아님(어댑터 내부)"으로 둔다.

## 부수 발견 — Core의 과목 전용 누수 2건 (EOS-84 계측의 사각)

판정 과정에서 CORE 배정 모듈이 수학을 아는 자리 2종이 나왔고, **둘 다 EOS-84 프로브가 놓쳤다**.

| 자리 | 형태 | v1 검출 |
|---|---|---|
| `l4.visualization_policy:47-57` `_SEATED_STYLES` | 수학 전용 표상 **7종을 enum 멤버로 열거** | **0건** |
| `schema.visualization:147-179` `Graph2dSpec` | `tangent_point`·`integral_region`·`show_extrema`·`number_line`을 **typed 필드로 검증** | **0건** |

왜 놓쳤나: v1의 리터럴 스캔은 `Compare`의 **문자열**만 보는데 `frozenset({VisualizationStyle.단위원})`
에는 문자열이 하나도 없다(`Attribute` 노드). 어휘 스캔은 문자열 **상수**만 보는데 `integral_region`은
값이 아니라 **이름**이다.

두 번째 것이 더 무겁다 — Core의 최하위 계층 `schema`가 미적분 어휘를 필드명으로 갖고 **그 필드를
검증까지 한다**. 불투명 페이로드 원칙("Core는 answer_kind를 해석하지 않는다")과 정면으로 충돌한다.

**대책(이 태스크에서 이행)**: 프로브에 두 스캐너를 추가하고 실측값을 기준선으로 동결했다 —
enum 멤버 2건 · 필드명 6건(위 4개 + `l3.solution_path.sympy_verified` + `l4.misconception.catalog._TRIG`).
상환은 별도 태스크(등재는 Kiki 판정).

## 정직한 공백

- **어휘 목록 기반 스캔의 한계**: `_SEATED_STYLES`의 7종 중 스캐너가 잡는 것은 2종뿐이다
  (`단위원`·`함수그래프`·`부등식영역`·`분포곡선`·`확률시뮬레이션`은 어휘 목록에 없다). 이 한계를
  테스트로 **명시 고정**했다(`test_enum_scanner_admits_what_it_cannot_see`) — 놓치는 것을 모르는 채
  "0건"이라 말하지 않기 위해서다.
- 판정은 **정적 코드 실측**이다. 런타임 동적 조회(getattr·문자열 경유)는 이 조사의 사각이다.
- 9번 후보의 재설계안(중립 반환 타입)은 **설계하지 않았다** — 판정만 했다.
- `l4.visualization_policy`가 CORE 배정인 것 자체가 옳은지는 재검토 대상일 수 있다(이 문서는 배정을
  주어진 것으로 두고 판정했다).
