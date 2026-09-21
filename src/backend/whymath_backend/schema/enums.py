"""Schema v1.0 도메인 ENUM 정의 (Pydantic str-Enum).

설계 정본: `schemas/v1.0/schema_v1.0.md` §14.3(ENUM 정의)·§3(도메인1 Problem DDL)·
§13.2(`license_enum`). 이 파일의 각 enum은 그 DDL의 `CREATE TYPE ... AS ENUM (...)`
값을 *그대로* 옮긴 것이 정본이다(한글 값은 한글 그대로, 영어 값은 영어 그대로).

컨벤션(`l3/models.py` 답습):
  - `class X(str, Enum)` 사용 (Literal 아님). str-Enum이므로 멤버는 그 문자열 값과
    동등 비교되어 라우터·필터 코드에서 안정적으로 쓰인다.
  - 식별자(멤버 이름)는 영어, 값(`= "..."`)은 DDL 그대로.
  - 모델에서 `use_enum_values=True`로 직렬화하면 한글 값이 그대로 보존된다
    (`str_strip_whitespace`·`ensure_ascii=False` 효과).

법적 메모(MEMORY 2026-05-28 결정 로그): `SourceType.평가원/EBS/교과서`와
`LicenseType.EBS_LICENSED`·`GenerationType.ORIGINAL`은 *본문 저장* 전제로
해석하면 저작권 가이드 v2.0(§32 단서·영리 금지)과 충돌한다. 따라서 이들
source_type은 *구조 메타데이터 참조 전용*이며, 실제 본문을 가진 문제는
`SourceType.자체생성`(license=`WHYMATH_GENERATED`)뿐이다. 이 불변식은
`problem.Problem`의 `@model_validator(mode="after")`에서 강제한다.
"""

from __future__ import annotations

from enum import Enum


# ──────────────────────────────────────────────────────────────────────────
# 출처·시험 컨텍스트 (§3.1 problem 테이블 §14.3 source_type_enum)
# ──────────────────────────────────────────────────────────────────────────
class SourceType(str, Enum):
    """콘텐츠 출처 — §14.3 `source_type_enum` 값 그대로(한글).

    법적 교정(MEMORY 2026-05-28): 평가원·EBS·교과서는 *본문 미보유*. 이 세 출처
    레코드는 구조 메타데이터(단원·코드·문항번호)만 가지며 본문 필드는 비어야 한다
    (`Problem` after-validator로 강제). 학생에게 노출되는 본문은 `자체생성`만.
    """

    평가원 = "평가원"
    """한국교육과정평가원 — 구조 메타만(본문 X, 저작권법 §32 단서·영리 금지)."""

    EBS = "EBS"
    """EBS — 구조 메타만(본문 X, 상업 영리금지 §32 단서)."""

    AIHub = "AIHub"
    """AIHub 공개 데이터셋 — 영리 명문 허용(출처표시·국외반출·재판매금지·환수)."""

    교육청학평 = "교육청학평"
    """시도교육청 학력평가 — 구조 메타 참조."""

    사설모의고사 = "사설모의고사"
    """사설 모의고사 — 제휴 시에만(THIRD_PARTY_LICENSED)."""

    자체생성 = "자체생성"
    """WhyMath 자체 생성 동등문제 — 본문 보유, license=WHYMATH_GENERATED."""

    사용자자작 = "사용자자작"
    """사용자 자작 문제 — license=USER_GENERATED."""

    교과서 = "교과서"
    """검정 교과서 — 구조 메타만(본문·문제·풀이·그림 복제 절대 금지)."""


class ExamType(str, Enum):
    """시험 유형 — §3.1 `exam_type_enum` 주석(수능/모평/학평/EBS교재/N제/자체생성).

    §14.3에 별도 `CREATE TYPE`이 없어 DDL 컬럼 주석(L127)의 값을 정본으로 채택한다.
    """

    수능 = "수능"
    모평 = "모평"
    학평 = "학평"
    EBS교재 = "EBS교재"
    N제 = "N제"
    자체생성 = "자체생성"


class Curriculum(str, Enum):
    """교육과정 버전 — §14.3 `curriculum_enum` 값 그대로(영어).

    **문항의 본질 속성 축(개정판 정합)이다 — Overlay 이관 대상 아님.** 개념 노드의
    curriculum은 Overlay(`CurriculumEntry`)로 뺐지만(rev `f3a4b5c6d7e8`·"개념은 영속·교육과정은
    Overlay"는 *개념 노드* 원칙), 문항(`Problem`)은 특정 개정판을 위해 저작된 *콘텐츠*라
    curriculum_version이 이중 진실이 아니라 문항 고유 속성이다. `Problem`이 유일 프로덕션
    소비자이며 L6 학교진도 게이트 ③(2015/2022 혼입 방지·`l6/school_progress/gating.py`)의
    살아있는 기준 — 실제로 Concept의 curriculum 제거가 안전했던 *전제*가 이 필드였다
    (게이팅이 Concept 아닌 Problem을 봄). 오등록 상환 판정 2026-07-02(MEMORY) — 제거·Overlay
    이관 기각.
    """

    REVISION_2009 = "2009_REVISION"
    REVISION_2015 = "2015_REVISION"
    REVISION_2022 = "2022_REVISION"


class Subject(str, Enum):
    """과목 — §3.1 `subject_enum` 주석(공통/미적분/확통/기하/인공지능수학).

    §14.3에 별도 `CREATE TYPE`이 없어 DDL 컬럼 주석(L139)을 정본으로 채택한다.

    **수학 교과 한정**(실체는 수능 선택과목 축) — 타 과목(물리 등) 값 ADD VALUE 금지(축 혼동
    영구화). 교과 축은 향후 `Problem.subject_area`로 별도 신설한다
    (docs/architecture/subject_expansion_readiness.md §1·§8 보류 대장, 트리거: 물리 문항 첫 적재).
    """

    공통 = "공통"
    미적분 = "미적분"
    확통 = "확통"
    기하 = "기하"
    인공지능수학 = "인공지능수학"


# ──────────────────────────────────────────────────────────────────────────
# 문항 형식·정답 (§3.1 question_format_enum·answer_format_enum)
# ──────────────────────────────────────────────────────────────────────────
class QuestionFormat(str, Enum):
    """문항 형식 — §3.1 `question_format_enum`(기존 4종) + P3a 10유형 체계 확장(6종 추가).

    배경(P3a): Kiki 확정 10유형 문항 체계를 도입하되, *기존 4종 PG 라벨은 그대로 보존*한다
    (기존 행 하위호환·`ALTER TYPE ... ADD VALUE`로 6종만 추가). 약어(영문)↔PG 라벨(한글)
    매핑은 아래와 같다. 약어는 *문서/코드 식별용 표기*일 뿐 enum 멤버명/값은 한글이다
    (기존 컨벤션 — Persona·SchoolType처럼 한글 값 보존, use_enum_values=True 직렬화 시
    한글 라벨 유지).

      약어    PG 라벨(=멤버명=값)   의미
      ─────   ──────────────────   ───────────────────────────────────────────
      MC      객관식               5지선다 등 표준 객관식 (기존)
      SA      단답형               단답(숫자·식 한 개) (기존)
      ST      합답형               ㄱㄴㄷ 구조화·단계형 합답 (기존·약어 ST=structured)
      EX      서술형               서술·논술형 (기존)
      MC-D    객관식진단           객관식 + 오답진단(distractor가 오개념을 진단) (신규)
      FB      빈칸형               빈칸 채우기(fill-in-the-blank) (신규)
      MN      짝짓기형             짝짓기/연결(matching) (신규)
      GR      그래프형             그래프 작도(graphing) (신규)
      PF      수행형               수행평가(performance) (신규)
      RT      재수전용형           재수(N수)전용 유형(retake-only) (신규)

    ST↔합답형 매핑 주의: 약어 ST(structured·단계형)는 한국 수능의 *합답형*(ㄱㄴㄷ 보기 중
    옳은 것의 조합을 고르는 구조화 문항)에 자연 대응한다 — 기존 라벨 '합답형'을 보존하는
    가장 적합한 매핑이다(`SignaturePattern.COMPOUND_CHOICES`(합답형 ㄱㄴㄷ)와 정합).
    """

    # ===== 기존 4종 (PG 라벨 보존 — 기존 행 하위호환) =====
    객관식 = "객관식"
    """MC — 5지선다 등 표준 객관식."""

    단답형 = "단답형"
    """SA — 단답(숫자·식 한 개)."""

    합답형 = "합답형"
    """ST — ㄱㄴㄷ 구조화·단계형 합답(약어 ST=structured)."""

    서술형 = "서술형"
    """EX — 서술·논술형."""

    # ===== P3a 신규 6종 (ALTER TYPE ADD VALUE로 추가) =====
    객관식진단 = "객관식진단"
    """MC-D — 객관식 + 오답진단(distractor가 오개념을 진단). 오답 선지가 오개념 후보를 가른다."""

    빈칸형 = "빈칸형"
    """FB — 빈칸 채우기(fill-in-the-blank)."""

    짝짓기형 = "짝짓기형"
    """MN — 짝짓기/연결(matching)."""

    그래프형 = "그래프형"
    """GR — 그래프 작도(graphing). 학생이 그래프를 직접 그려 답한다."""

    수행형 = "수행형"
    """PF — 수행평가(performance). 과정·산출물 기반 평가."""

    재수전용형 = "재수전용형"
    """RT — 재수(N수)전용 유형(retake-only). 페르소나 B·C 대상 고난도 변형."""


class AnswerFormat(str, Enum):
    """정답 형식 — §3.1 `answer_format_enum` 주석(자연수/분수/실수/식)."""

    자연수 = "자연수"
    분수 = "분수"
    실수 = "실수"
    식 = "식"


# ──────────────────────────────────────────────────────────────────────────
# Bloom 인지 수준 (P3a — 문항 메타 분류 축)
# ──────────────────────────────────────────────────────────────────────────
class BloomLevel(str, Enum):
    """Bloom 개정 분류(인지 수준) 6단계 — P3a 문항 메타 축(`Problem.bloom_level`).

    Anderson·Krathwohl(2001) 개정 Bloom taxonomy의 인지 과정 6단계(REMEMBER <
    UNDERSTAND < APPLY < ANALYZE < EVALUATE < CREATE 순의 위계). 문항이 요구하는 *인지
    수준*을 태그해 난이도 5축(diff_*)·인지 유형(`CognitiveType`)과 다른 축으로 분류한다.

    멤버명·값 모두 영어(국제 표준 분류명 — `SignaturePattern`·`CognitiveType`의 영어 값
    선례). use_enum_values=True 직렬화 시 영어 값 보존(예: bloom_level="ANALYZE").
    """

    REMEMBER = "REMEMBER"
    """기억 — 사실·용어·공식을 회상한다(가장 낮은 인지 수준)."""

    UNDERSTAND = "UNDERSTAND"
    """이해 — 개념의 의미를 설명·해석한다."""

    APPLY = "APPLY"
    """적용 — 절차·원리를 새 상황에 적용한다."""

    ANALYZE = "ANALYZE"
    """분석 — 구성요소·관계를 분해해 구조를 파악한다."""

    EVALUATE = "EVALUATE"
    """평가 — 기준에 따라 판단·비판한다."""

    CREATE = "CREATE"
    """창안 — 새 해법·구성을 만들어낸다(가장 높은 인지 수준)."""


# ──────────────────────────────────────────────────────────────────────────
# 채점 유형 (P3a — 문항 메타 분류 축)
# ──────────────────────────────────────────────────────────────────────────
class ScoringType(str, Enum):
    """채점 유형 — P3a 문항 메타 축(`Problem.scoring_type`, 한글 5종).

    문항을 *어떻게 채점하는가*를 분류한다(문항 형식 `QuestionFormat`과 다른 축 — 같은
    객관식이라도 정오답/진단 채점이 갈릴 수 있다). 한글 값(한글 식별자 그대로 — Persona·
    ScoringType 선례). use_enum_values=True 직렬화 시 한글 값 보존(예: scoring_type="루브릭").
    """

    정오답 = "정오답"
    """정오답 — 맞음/틀림 이분 채점(0/1)."""

    진단 = "진단"
    """진단 — 오답 선지로 오개념을 진단(점수보다 진단 신호가 목적)."""

    부분점수 = "부분점수"
    """부분점수 — 단계·요소별 부분 점수(서술·합답형)."""

    시간 = "시간"
    """시간 — 풀이 시간 기반 평가(속도·실전 감각)."""

    루브릭 = "루브릭"
    """루브릭 — 평가 기준표(rubric) 기반 다차원 채점(수행평가)."""


# ──────────────────────────────────────────────────────────────────────────
# 한국 시그니처 패턴 (§14.3 signature_pattern_enum — 10종)
# ──────────────────────────────────────────────────────────────────────────
class SignaturePattern(str, Enum):
    """한국 수능 시그니처 패턴 — §14.3 `signature_pattern_enum` 값 그대로(영어, 10종)."""

    CONDITION_LIST = "CONDITION_LIST"
    """(가)(나)(다) 조건 나열 (FR-001 조건 나열형 파서)."""

    COMPOSITE_DIFFERENTIABILITY = "COMPOSITE_DIFFERENTIABILITY"
    """합성함수 미분가능성 (FR-003)."""

    INDUCTIVE_SEQUENCE = "INDUCTIVE_SEQUENCE"
    """귀납적 수열 (FR-004)."""

    DEFINED_INTEGRAL_FUNCTION = "DEFINED_INTEGRAL_FUNCTION"
    """정적분 정의 함수."""

    FUNCTION_COUNT = "FUNCTION_COUNT"
    """함수 개수 문제."""

    GRAPH_SHAPE_INFERENCE = "GRAPH_SHAPE_INFERENCE"
    """그래프 개형 추론."""

    CASE_ANALYSIS_DEEP = "CASE_ANALYSIS_DEEP"
    """깊은 케이스 분류."""

    CROSS_UNIT_FUSION = "CROSS_UNIT_FUSION"
    """단원 융합."""

    NATURAL_NUMBER_TRANSFORM = "NATURAL_NUMBER_TRANSFORM"
    """자연수 답 변환."""

    COMPOUND_CHOICES = "COMPOUND_CHOICES"
    """합답형 ㄱㄴㄷ."""


# ──────────────────────────────────────────────────────────────────────────
# 페르소나 (§14.3 persona_enum — PRD 5종)
# ──────────────────────────────────────────────────────────────────────────
class Persona(str, Enum):
    """PRD 페르소나 5종 — §14.3 `persona_enum` 값 그대로(영어+한글 혼합 식별자 표현)."""

    A_일반고고3 = "A_일반고고3"
    """A 일반고 고3 — MVP·시장 최대."""

    B_자사고N수 = "B_자사고N수"
    """B 자사고 N수 — v2.0·결제 최대."""

    C_검정고시N수 = "C_검정고시N수"
    """C 검정고시 N수 — v1.5·수학 의존 100%."""

    D_학종고2 = "D_학종고2"
    """D 학종 고2 — v1.5·세특/자유연구."""

    E_홈스쿨링영재 = "E_홈스쿨링영재"
    """E 홈스쿨링 영재 — v2.0·가치 최대."""


# ──────────────────────────────────────────────────────────────────────────
# 시각자료 (§3.1 visual_type_enum 주석: 그래프/도형/표/좌표평면)
# ──────────────────────────────────────────────────────────────────────────
class VisualType(str, Enum):
    """시각자료 유형 — §3.1 `visual_type_enum` 주석(그래프/도형/표/좌표평면)."""

    그래프 = "그래프"
    도형 = "도형"
    표 = "표"
    좌표평면 = "좌표평면"


# ──────────────────────────────────────────────────────────────────────────
# 시각화 양식 (슬라이스 87: 교수학적 표현 형식 — 개념↔양식 매핑 통제 어휘)
# ──────────────────────────────────────────────────────────────────────────
class VisualizationStyle(str, Enum):
    """시각화 *양식* — 개념을 가장 잘 드러내는 *교수학적 표현 형식*.

    `VisualType`(그래프/도형/표/좌표평면 — 문제 콘텐츠 *태그*)·05 §5.2 `Visualization.type`
    (interactive_graph_2d 등 — *렌더 기술*)과는 **다른 축**. "삼각함수→단위원·확률→수형도·
    정수→수직선"처럼 개념·성취기준에 권장되는 *표상 형식*을 통제 어휘로 정의한다(슬라이스 88의
    `Concept.recommended_visual_styles` 매핑에 사용·슬라이스 87은 어휘만 도입).

    값(한글)은 슬라이스 88에서 PostgreSQL enum 타입이 되어 *추가는 쉬우나 제거는 어렵다* —
    v1은 한국 중·고 표준 표상 위주로 보수적 선정(후속 ADD VALUE로 확장).
    """

    수직선 = "수직선"
    """수직선 — 정수·유리수·절댓값·부등식 해의 위치와 순서."""

    함수그래프 = "함수그래프"
    """좌표평면 함수 그래프 — 일차·이차·다항·유리·무리·지수·로그·삼각함수의 개형."""

    단위원 = "단위원"
    """단위원 — 호도법·삼각비·삼각함수의 정의와 주기성."""

    평면도형 = "평면도형"
    """평면도형 — 작도·합동·닮음·원의 성질 등 유클리드 도형."""

    입체도형 = "입체도형"
    """입체도형·전개도 — 겉넓이·부피·정사영·단면."""

    넓이모델 = "넓이모델"
    """넓이 모델 — 분배법칙·곱셈공식·확률·정적분을 직사각형 넓이로 표상."""

    수형도 = "수형도"
    """수형도(나무 그림) — 경우의 수·조건부확률의 분기 열거."""

    부등식영역 = "부등식영역"
    """부등식 영역 — 연립부등식 해·영역·선형계획법의 색칠 영역."""

    벡터도 = "벡터도"
    """벡터 다이어그램 — 평면·공간 벡터의 합성·내적·위치 화살표."""

    점화도 = "점화도"
    """수열·점화 다이어그램 — 등차·등비·점화식의 반복 구조."""

    통계차트 = "통계차트"
    """통계 차트 — 막대·꺾은선·원그래프·히스토그램·도수분포."""

    산점도 = "산점도"
    """산점도 — 두 변량의 상관관계·회귀 직선."""

    상자그림 = "상자그림"
    """상자그림(box plot) — 사분위수·중앙값·산포·이상치."""

    분포곡선 = "분포곡선"
    """분포곡선 — 정규분포·표준화·이항분포의 정규근사."""

    접선도함수 = "접선도함수"
    """접선·도함수 시각화 — 미분계수(접선 기울기)·도함수 개형."""

    확률시뮬레이션 = "확률시뮬레이션"
    """확률 시뮬레이션 — 시행 반복·누적 상대도수(통계적 확률·대수의 법칙)."""


# ──────────────────────────────────────────────────────────────────────────
# 시각화 가능성 4분류 (구축 플레이북 Part 5 — 개념을 "어떻게/그려야 하는가"로 판별)
# ──────────────────────────────────────────────────────────────────────────
class Visualizability(str, Enum):
    """개념의 *시각화 가능성* 4분류 — 구축 플레이북 Part 5-1(직접/동적/부분/추상).

    핵심 원칙: **모든 개념이 똑같이 시각화되지 않는다**. 네 분류는 "그릴 수 있는가"가 아니라 개념이
    학생 인지에서 *어떤 방식으로 파악되는가*(인지 행동)로 나뉜다 — 어느 것도 "시각화 불가"가 아니라
    *각기 다른 시각화 전략*을 요구한다(설계 정본 `05b_visualization_classification.md`).
    억지 리터럴 시각화는 오개념을 유발하므로("그릴 수 있다 ≠ 교육적으로 좋다"), 분류가 렌더 전략을
    가른다. `VisualizationStyle`(어떤 양식)·`VisualizationType`(어떤 렌더 기술)과는 **다른 축**이다.

    **표면 표현이 아니라 인지 행동(cognitive action) 기준으로 정의한다**(플레이북 공통 문장).
    `use_enum_values=True` 모델에서 값(한글)이 그대로 직렬화된다.
    """

    직접 = "직접"
    """직접 시각화 가능 — 형태 자체가 보인다(도형·함수그래프·좌표·벡터). 정지된 한 장이 핵심 인지를
    *즉시* 드러내 조작 없이 이해가 성립한다. 렌더 전략: Geometry2D(정적)."""

    동적 = "동적"
    """동적 시각화 가능 — 변화 과정을 표현해야 한다(극한·미분·적분·함수변환). **AI 수학교육의 핵심
    영역**: 한국 학생이 가장 어려워하고 정적 그림으론 이해가 안 된다. 렌더: 애니메이션·슬라이더."""

    부분 = "부분"
    """부분 시각화 가능 — 일부 의미만 그림이 담는다(확률·벡터공간·복소수·수렴). 렌더 전략:
    AnalogyVisual(비유 시각화 + *coverage 표시* — 무엇이 안 담기는지 정직 노출)."""

    추상 = "추상"
    """추상적이라 어려움 — 구조 자체가 추상적이다(군론·위상·범주론·논리). 리터럴 그래프는 거짓
    구체성으로 오개념을 부른다. 렌더 전략: StructureGraph(구조 그래프·**메타포 중심**)."""


# ──────────────────────────────────────────────────────────────────────────
# 시각화 렌더 기술 (슬라이스 90: 05 §5.2 Visualization.type — 선언적 명세 렌더 도구 축)
# ──────────────────────────────────────────────────────────────────────────
class VisualizationType(str, Enum):
    """시각화 *렌더 기술* — 05 §5.2 `Visualization.type` 정본(4종·영문 값).

    `VisualType`(그래프/도형/표 — 문제 콘텐츠 *태그*)·`VisualizationStyle`(단위원·수형도 —
    개념 권장 *교수학적 양식*·슬라이스 87)과는 **다른 축**: 이 enum은 선언적 명세를 *어떤
    렌더 도구로 그리는가*를 규정한다(L5 ④ 국소 비상구가 type을 보고 D3/Plotly/three.js/Manim
    선택, 05 §5.2). 값은 영문(05 §5.2 표기 그대로).

    `animation_prerendered`만 기존 Manim 산출물(조작 불가)이고, 나머지 3종이 학생 파라미터
    조작이 가능한 PRD 신규 선언적 명세(05 §5.2). 슬라이스 89 "표현≠의미"의 렌더 기술 축.
    """

    interactive_graph_2d = "interactive_graph_2d"
    """2D 함수·관계 그래프 — 학생이 파라미터 조작(슬라이더·드래그). 렌더: D3.js/Plotly/Desmos."""

    interactive_surface_3d = "interactive_surface_3d"
    """3D 곡면·입체 — 회전·단면 조작. 렌더: three.js."""

    simulation_probabilistic = "simulation_probabilistic"
    """확률 시뮬레이션 — 시행 반복·누적. 렌더: D3.js/Plotly."""

    animation_prerendered = "animation_prerendered"
    """미리 렌더된 사고 과정 애니메이션(조작 불가). 렌더: Manim."""


# ──────────────────────────────────────────────────────────────────────────
# 저작권·생성 이력 (§13.2 license_enum·§10.1 generation_type_enum)
# ──────────────────────────────────────────────────────────────────────────
class LicenseType(str, Enum):
    """콘텐츠 라이선스 — §13.2 `license_enum` 값 그대로(영어).

    법적 메모: 본문을 가진 문제의 지배 license는 `WHYMATH_GENERATED`. `EBS_LICENSED`·
    (관련) `ORIGINAL`은 공식 제휴(Phase 3+) 전까지 미사용(MEMORY 2026-05-28).
    license/generation_type 강제는 ContentProvenance(슬라이스 2) 소관.

    LIC-01 확장: KOGL/CC/자체/계약/미확인/제한 등급을 native로 지원해 Rights Policy Engine이
    라이선스 문자열을 해석하지 않고 enum 값으로 판정할 수 있게 한다.
    """

    # 퍼블릭 도메인 / 법령 면제
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    """공개 자료(평가원 공개 — 단, 본문 영리사용은 별도 금지)."""

    # 공공누리
    KOGL_0 = "KOGL_0"
    """공공누리 0유형 — 자유이용."""

    KOGL_1 = "KOGL_1"
    """공공누리 1유형 — 출처표시."""

    KOGL_2 = "KOGL_2"
    """공공누리 2유형 — 출처표시 + 상업적 이용금지."""

    KOGL_3 = "KOGL_3"
    """공공누리 3유형 — 출처표시 + 변경금지."""

    KOGL_4 = "KOGL_4"
    """공공누리 4유형 — 출처표시 + 상업적 이용금지 + 변경금지."""

    # Creative Commons
    CC0 = "CC0"
    """CC0 — 퍼블릭 도메인 dedication."""

    CC_BY = "CC_BY"
    """CC BY — 출처표시."""

    CC_BY_SA = "CC_BY_SA"
    """CC BY-SA — 출처표시 + 동일조건변경허락(Share-Alike 전염 주의)."""

    CC_BY_NC = "CC_BY_NC"
    """CC BY-NC — 출처표시 + 비영리."""

    CC_BY_ND = "CC_BY_ND"
    """CC BY-ND — 출처표시 + 변경금지."""

    CC_BY_NC_SA = "CC_BY_NC_SA"
    """CC BY-NC-SA — 출처표시 + 비영리 + 동일조건변경허락."""

    CC_BY_NC_ND = "CC_BY_NC_ND"
    """CC BY-NC-ND — 출처표시 + 비영리 + 변경금지."""

    # WhyMath / 내부 / 계약
    INTERNAL_OWNED = "INTERNAL_OWNED"
    """WhyMath 내부 직접 제작 콘텐츠(고용/의뢰 계약에 따른 권리 보유)."""

    WHYMATH_GENERATED = "WHYMATH_GENERATED"
    """자체 생성 — 저작권 WhyMath. 본문 보유 문제의 지배 license."""

    USER_GENERATED = "USER_GENERATED"
    """사용자 자작."""

    AIHUB_OPEN = "AIHUB_OPEN"
    """AIHub 공개 데이터셋 — 영리 명문 허용(출처표시·국외반출·재판매금지·환수 조건)."""

    CONTRACT_LICENSED = "CONTRACT_LICENSED"
    """계약 기반 라이선스 — 제휴/구독/기간/지역 조건을 별도 contract에 따름."""

    DIRECT_PERMISSION = "DIRECT_PERMISSION"
    """권리자로부터 개별 이용허락을 받은 콘텐츠."""

    THIRD_PARTY_LICENSED = "THIRD_PARTY_LICENSED"
    """사설 모의고사 협업(제휴)."""

    # 안전선
    UNKNOWN = "UNKNOWN"
    """권리 상태 미확인 — fail-closed(REVIEW_REQUIRED/DENY)."""

    RESTRICTED = "RESTRICTED"
    """명시적 제한 — 거의 모든 행위 불가."""

    EBS_LICENSED = "EBS_LICENSED"
    """EBS 라이선스 — 공식 제휴 전까지 미사용."""


class GenerationType(str, Enum):
    """콘텐츠 생성·변형 단계 — §10.1 `generation_type_enum` 값 그대로(영어)."""

    ORIGINAL = "ORIGINAL"
    """원본 그대로 — 본문 보유 전제이므로 공식 제휴 전까지 미사용(MEMORY 2026-05-28)."""

    VARIANT_NUMBER = "VARIANT_NUMBER"
    """숫자만 변형."""

    VARIANT_STRUCTURE = "VARIANT_STRUCTURE"
    """구조 변형."""

    VARIANT_CONTEXT = "VARIANT_CONTEXT"
    """맥락(조건) 변형."""

    COMPOSED = "COMPOSED"
    """여러 문제 결합."""

    FULLY_GENERATED = "FULLY_GENERATED"
    """AI 완전 생성."""


# ──────────────────────────────────────────────────────────────────────────
# LIC-01 권리·출처 정책 enum (Rights & Provenance Infrastructure MVP)
# ──────────────────────────────────────────────────────────────────────────
class PermissionAction(str, Enum):
    """EOS 정규화 권리 primitive — License를 시스템이 해석할 수 있는 최소 행위 단위."""

    DISPLAY = "DISPLAY"
    """학생/교사 UI에 표시."""

    COPY = "COPY"
    """내부 복제."""

    REDISTRIBUTE = "REDISTRIBUTE"
    """외부 재배포."""

    MODIFY = "MODIFY"
    """수정·번역·요약."""

    TRANSLATE = "TRANSLATE"
    """번역."""

    COMMERCIAL_USE = "COMMERCIAL_USE"
    """상업적 이용."""

    DOWNLOAD = "DOWNLOAD"
    """다운로드 허용."""

    PRINT = "PRINT"
    """인쇄."""

    EXPORT = "EXPORT"
    """내보내기."""

    EMBED = "EMBED"
    """임베드."""

    API_ACCESS = "API_ACCESS"
    """API 노출."""

    RAG_INDEX = "RAG_INDEX"
    """RAG 인덱싱."""

    AI_CONTEXT = "AI_CONTEXT"
    """LLM 프롬프트 컨텍스트 입력."""

    AI_TRAINING = "AI_TRAINING"
    """LLM 학습 데이터로 사용."""

    AI_FINE_TUNING = "AI_FINE_TUNING"
    """파인튜닝 데이터로 사용."""

    AI_EVALUATION = "AI_EVALUATION"
    """모델 평가 데이터로 사용."""

    AI_SYNTHETIC_DERIVATION = "AI_SYNTHETIC_DERIVATION"
    """AI 합성 파생물 생성에 사용."""


class RightsDecision(str, Enum):
    """Rights Policy Engine의 판정 결과."""

    ALLOW = "ALLOW"
    """허용."""

    ALLOW_WITH_ATTRIBUTION = "ALLOW_WITH_ATTRIBUTION"
    """출처 표시 조건 하에 허용."""

    ALLOW_WITH_RESTRICTIONS = "ALLOW_WITH_RESTRICTIONS"
    """특정 조건 하에 허용(계약 조건 등)."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    """검수 필요 — 자동 승인 불가."""

    DENY = "DENY"
    """거부."""


class RightsReviewStatus(str, Enum):
    """Rights Entity의 검수·분쟁 상태."""

    UNVERIFIED = "UNVERIFIED"
    """미검증."""

    VERIFIED = "VERIFIED"
    """검증됨."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    """검수 필요."""

    APPROVED = "APPROVED"
    """승인됨."""

    RESTRICTED = "RESTRICTED"
    """제한됨."""

    DISPUTED = "DISPUTED"
    """분쟁 중."""

    EXPIRED = "EXPIRED"
    """계약/라이선스 만료."""


class SourceAuthority(str, Enum):
    """출처의 신뢰도 등급."""

    OFFICIAL = "OFFICIAL"
    """공식 기관 발행."""

    VERIFIED = "VERIFIED"
    """검증된 출처."""

    SECONDARY = "SECONDARY"
    """2차 출처."""

    USER_REPORTED = "USER_REPORTED"
    """사용자 제보."""

    UNKNOWN = "UNKNOWN"
    """미확인."""


class DerivationType(str, Enum):
    """콘텐츠 파생 관계 엣지 유형."""

    DERIVED_FROM = "DERIVED_FROM"
    """일반 파생."""

    TRANSLATED_FROM = "TRANSLATED_FROM"
    """번역."""

    ADAPTED_FROM = "ADAPTED_FROM"
    """각색·적응."""

    SUMMARIZED_FROM = "SUMMARIZED_FROM"
    """요약."""

    GENERATED_FROM = "GENERATED_FROM"
    """AI/프로그램 생성."""

    PARAMETERIZED_FROM = "PARAMETERIZED_FROM"
    """파라미터 변형(숫자 치환 등)."""

    EXCERPTED_FROM = "EXCERPTED_FROM"
    """발췌."""

    COMBINED_FROM = "COMBINED_FROM"
    """여러 원본 결합."""


# ──────────────────────────────────────────────────────────────────────────
# 검수 상태 (§3.1 review_status_enum 주석 3종 + quarantined — EOS-71)
# ──────────────────────────────────────────────────────────────────────────
class ReviewStatus(str, Enum):
    """검수 상태 — §3.1 `review_status_enum` 주석 3종(pending/approved/rejected) + `quarantined`.

    §13.3: 모든 `problem`은 `review_status = approved` 후 노출.

    `quarantined`는 v1.0 DDL 주석 *이후*에 더한 **운영 확장**(EOS-71)이다 — `EventType`이 §6.1
    주석 8종에 검산결과·힌트제공·시각화조작·문제시도를 더한 것과 같은 방식으로, 스펙 스냅샷
    (`schemas/v1.0/schema_v1.0.md`)은 원안 그대로 두고 확장은 이 docstring이 정본으로 이고 간다.

    **격리는 삭제가 아니다(비파괴 원칙 — EOS-71 핵심)**: `quarantined`로 표시된 문항은 `problem`
    레코드도, 그 문항에 딸린 `problem_attempt` 학습 기록도 **그대로 보존**한다. 끊는 것은 *노출*
    뿐이다. 이 상태값이 없던 시기에 실중복 9건이 코퍼스 JSONL에서 **물리 제거**된 선례가 있고
    (`docs/data/problem_duplicate_disposition_2026-08.md` §3 — "감사 도구는 review_status를
    필터하지 않는다"가 제거의 직접 근거였다), 이 값은 그 파괴적 처분의 구조화된 대안이다.

    계약 정본: `docs/standards/problem_quarantine_contract.md`.
    """

    pending = "pending"
    approved = "approved"
    rejected = "rejected"

    quarantined = "quarantined"
    """운영 중 **사후 결함 판정으로 회수**된 문항 — 레코드·학습 기록 보존, 노출만 차단(EOS-71).

    `rejected`와 **절대 합치지 않는다**:
      · `rejected` = *애초에 승인받지 못한* 문항. 검수 기준 미달로 판정됐고 학생에게 서빙된 적이
        없다 — "들여보내지 않았다".
      · `quarantined` = *한때 `approved`로 서빙되던* 문항의 사후 결함 판정(정답 오류·복수 정답·
        모호 문장·실중복 등)에 따른 회수 — "들여보냈다가 되돌렸다".
    합치면 "학생이 이미 풀어 본 결함 문항"과 "한 번도 나간 적 없는 탈락 문항"이 같은 글자가 되어,
    딸린 `problem_attempt`를 재채점·θ 재계산 대상으로 볼지 사후에 구분할 수 없게 된다.

    격리 사유·시각은 `problem.quarantine_reason`·`quarantined_at`에 **함께** 기록한다(계약 §3 —
    상태값만 있고 사유가 없으면 "왜 회수됐는가"가 사람 기억에만 남아 해제 판단도 불가능해진다).
    """


def is_review_status_cleared(value: ReviewStatus | str | None) -> bool:
    """검수 통과 여부의 **값 수준 단일 권위** — `approved`만 True(fail-closed).

    왜 함수인가(CONT-01): 이 판정은 두 곳에서 필요하다.
      · **런타임** — `l6/_shared.is_review_cleared(problem)`가 L6 6모드·blueprint 조립·기본 CAT의
        노출 게이트로 호출한다(PB-03). 입력은 `Problem`(pydantic) 인스턴스다.
      · **빌드타임** — `harness/concept_assessment_index.py`가 문항 코퍼스 JSONL을 dict로 읽어
        개념 평가 재료 상속 후보를 고른다. 입력은 `Problem`이 아니라 *생 dict의 문자열 값*이다.
    두 경로가 각자 `== "approved"`를 적으면 기준이 이원화되고, 한쪽만 완화돼도 아무도 모른다.
    그래서 "어떤 값이 검수 통과인가"라는 **enum 자신의 의미**를 여기(enum 옆)에 한 번만 두고,
    `is_review_cleared`는 이 함수를 감싸는 `Problem` 어댑터가 된다.

    fail-closed: `None`(미평가)·`pending`(대기)·`rejected`(기준 미달)는 전부 False다.
    §13.3 "모든 problem은 review_status=approved 후 노출"의 기계적 표현이다.

    `ReviewStatus`는 `str, Enum`이라 enum 멤버와 문자열이 서로 동등 비교된다 — 따라서 이 한 줄이
    `use_enum_values=True`로 문자열화된 `Problem.review_status`와 코퍼스 생 문자열 양쪽을 모두
    올바르게 판정한다(정규화 분기 불필요).

    ⚠️ 저작권 축(`l6/_shared.is_exposable`)과 **절대 합치지 않는다**. 검수는 운영·정책 축이고
    노출 가능성은 법적 축이다(PB-03 설계). 합치면 나중에 운영 사유로 법적 게이트를 느슨하게
    하는 압력이 생긴다 — 호출부에서 각각 독립된 `if`로 확인한다.

    Args:
      value: 판정 대상 `review_status`(enum 멤버·문자열·None 모두 허용).

    Returns:
      `approved`이면 True, 그 외 전부 False.
    """
    return value == ReviewStatus.approved


def is_review_status_quarantined(value: ReviewStatus | str | None) -> bool:
    """격리 여부의 **값 수준 단일 권위**(EOS-71) — `quarantined`만 True.

    **왜 `is_review_status_cleared`와 합치지 않는가**(두 술어를 나란히 두는 이유):
    `is_review_status_cleared`는 "`approved`만 통과"라 *검수 통과를 요구하는* 표면에만 쓸 수 있다.
    그런데 `api/problems.py`의 공개 카탈로그 GET 4종(단건·목록·steps·relations)은 **검수 통과를
    요구하지 않는 표면**이다 — 지금도 `pending`·`None` 문항이 그대로 나간다(SEC-07 D1의 공개
    카탈로그 결정). 거기에 `is_review_status_cleared`를 걸면 노출 정책이 "카탈로그 전체 공개"에서
    "승인분만 공개"로 바뀌는 **정책 변경**이 되고 현 클라·데모 경로를 광범위하게 깨뜨린다(EOS-71
    범위 밖 — 격리 계약 §7). 그래서 그 표면에서는 *격리만 확실히 차단*하는 이 술어를 쓴다.

    두 술어는 **방향이 다르다**:
      · `is_review_status_cleared` — **허용 목록**(approved만 True). 새 상태값이 생기면 자동 배제.
      · `is_review_status_quarantined` — **단일 값 지목**(quarantined만 True). 새 상태값이 생겨도
        이 술어는 그 값을 격리로 보지 않는다.
    따라서 이 술어는 `is_review_status_cleared`를 **대체하지 않는다**. 검수 통과를 요구하는 표면
    (L6 6모드·blueprint 조립·기본 CAT 후보 풀·빌드타임 상속 필터)은 계속 `is_review_status_cleared`
    를 쓰고, 거기서는 `quarantined`가 "approved가 아니다"라는 이유로 *이미* 차단된다 — fail-closed
    허용목록이 새 값을 공짜로 처리한다. 이 술어가 필요한 곳은 승인을 요구하지 않는 공개 표면뿐이다.

    `ReviewStatus`가 `str, Enum`이라 이 한 줄이 enum 멤버와 문자열 양쪽을 올바르게 판정한다
    (`is_review_status_cleared`와 동일). **관대한 정규화는 하지 않는다** — `"QUARANTINED"`·
    `"quarantined "`는 False다. 관대하게 받으면 Python 술어는 격리로 보는데 SQL 술어
    (`api/problems.py::quarantine_exclusion_condition`)는 아닌 값이 생겨 기준이 이원화된다.

    Args:
      value: 판정 대상 `review_status`(enum 멤버·문자열·None 모두 허용).

    Returns:
      `quarantined`이면 True, 그 외(`None`·`pending`·`approved`·`rejected`) 전부 False.
    """
    return value == ReviewStatus.quarantined


# ──────────────────────────────────────────────────────────────────────────
# 풀이 단계·문항 관계 (§3.2 step_type_enum·relation_type_enum)
# ──────────────────────────────────────────────────────────────────────────
class StepType(str, Enum):
    """풀이 단계 유형 — §3.2 problem_step.step_type_enum.

    값: 조건해석/케이스분류/그래프스케치/계산/검산.
    """

    조건해석 = "조건해석"
    케이스분류 = "케이스분류"
    그래프스케치 = "그래프스케치"
    계산 = "계산"
    검산 = "검산"


class RelationType(str, Enum):
    """문항 간 관계 — §3.2 `problem_relation.relation_type_enum`(변형/유사/선수/심화/대조)."""

    변형 = "변형"
    유사 = "유사"
    선수 = "선수"
    심화 = "심화"
    대조 = "대조"


# ──────────────────────────────────────────────────────────────────────────
# 추론 유형 (MATH DSL 진화 — 교육 추론 엔진 §2.2 · SolutionStep.reasoning_type)
# ──────────────────────────────────────────────────────────────────────────
class ReasoningType(str, Enum):
    """풀이 *스텝 단위* 추론 유형 — 폐쇄 7종(`SolutionStep.reasoning_type`).

    근거: `docs/architecture/math_dsl_evolution.md` §2.2(교육 추론 엔진 — 권장 1순위).
    불투명한 `SolutionStep.content`(자연어+LaTeX 문자열) 옆에 "이 스텝이 어떤 추론을
    수행하는가"를 태그해, "왜 이 변형이 정당한가"를 *기계가 읽게* 한다(엔진 정체성의 첫 벽돌).

    축 구분 주의: `approach_type`(SolutionPath — 풀이 *전체* 6유형: 대수/기하/조합/귀납/
    시각/역방향)과는 다른 축이다. ReasoningType은 *한 스텝*의 추론 유형이다(한 대수적 풀이
    안에서도 스텝마다 치환·사례분류·귀납이 섞일 수 있다).

    ⚠️ 폐쇄집합(6~8종) — *제거는 어렵고 추가는 신중해야* 한다(무한 추론 온톨로지 금지·
    math_dsl_evolution §2.2 금기). 유형 무한 세분화는 유지 불가·과설계다. 완전 형식논리
    증명 유형은 여기 두지 않는다(경계된 Tier3 Lean 위임·§2.9).

    멤버명·값 모두 영어(국제 인지 과정 어휘 — `BloomLevel`·`CognitiveType` 선례).
    use_enum_values=True 직렬화 시 영어 값 보존(예: reasoning_type="DEDUCTION").
    """

    DEDUCTION = "DEDUCTION"
    """연역 — 정리·정의에서 논리적으로 도출한다."""

    SUBSTITUTION = "SUBSTITUTION"
    """치환 — 변수·식을 대입해 변형한다."""

    CASE_SPLIT = "CASE_SPLIT"
    """사례분류 — 조건에 따라 경우를 나눈다(케이스 분석)."""

    INDUCTION = "INDUCTION"
    """귀납 — 패턴·수학적 귀납법으로 일반화한다."""

    TRANSFORMATION = "TRANSFORMATION"
    """동치변형 — 등식·부등식을 동치로 재작성한다(동치 판정 권위는 SymPy·§2.1)."""

    HEURISTIC = "HEURISTIC"
    """휴리스틱 — 통찰·추측으로 나아간다(검증 미완일 수 있음·정직 표시)."""

    BACKWARD = "BACKWARD"
    """역방향 — 결론에서 거꾸로 추론한다."""


# ──────────────────────────────────────────────────────────────────────────
# 풀이 접근 유형 (solution_path.schema.yaml `approach_type` · SolutionPath.approach_type)
# ──────────────────────────────────────────────────────────────────────────
class ApproachType(str, Enum):
    """풀이 *경로 전체* 접근 유형 — 폐쇄 6종(`SolutionPath.approach_type`).

    근거: `schemas/v1.1/solution_path.schema.yaml` `approach_type` enum(6종)·
    `03_content_generation.md` solution_approaches. S4-10(D2)에서 `l3/solution_path.py`의
    Literal 좌석을 이 단일 좌석으로 승격했다(`ReasoningType` 단일 좌석 규약 미러 —
    `docs/architecture/solution_module_gap_review.md` §3 D2).

    축 구분 주의(직교 3축 — `tests/backend/l1/test_strategy_governance.py` disjoint 동결):
      - **ApproachType**(이 enum) — *완성된 풀이 경로 전체*의 유형("이 풀이는 기하적 풀이다").
      - `ReasoningType` — *한 스텝*의 추론 유형(한 대수적 풀이 안에서도 스텝마다
        치환·사례분류·귀납이 섞인다).
      - `StrategyNode`(l1 strategy_graph) — 문제 공략 *계획 발상* heuristic(Polya 계획 단계 —
        아직 풀이가 완성되기 전의 접근 아이디어).

    ⚠️ 폐쇄집합(6종) — *제거는 어렵고 추가는 신중해야* 한다(무한 온톨로지 금지·관계 타입 폭발
    방지). "비유적" 등 새 유형 제안은 오개념 개입·정의 레지스터 `analogy` 축과 혼동 위험이라
    기각된 전례가 있다(§3 D2 — 프롬프트 정합에서 제거).

    멤버명=값(소문자 영어) — yaml enum 키·DB TEXT 저장값·기존 Literal 값과 1:1 동일
    (`ReviewStatus` 소문자 멤버 선례). `L2 MasteryState.preferred_solution_style`이 이 값을
    그대로 취한다(yaml 관계 명세). use_enum_values=True 직렬화 시 소문자 값 보존
    (예: approach_type="algebraic").
    """

    algebraic = "algebraic"
    """대수적 — 식 변형·계산 중심."""

    geometric = "geometric"
    """기하적 — 도형·그래프 중심."""

    combinatorial = "combinatorial"
    """조합적 — 경우의 수·셈 중심."""

    inductive = "inductive"
    """귀납적 — 패턴·수학적 귀납법 중심."""

    visual = "visual"
    """시각적 — 그림·다이어그램으로 통찰."""

    backward = "backward"
    """역방향 — 결론에서 거꾸로 추론. (ReasoningType.BACKWARD와 *다른 축*이다 — 소문자
    "backward"는 풀이 전체 축, 대문자 "BACKWARD"는 스텝 축. 거버넌스 disjoint 검사는
    strategy slug 기준이라 이 두 축 간 표기 유사는 허용되며, 의미 구분은 타입이 지킨다.)"""


# ──────────────────────────────────────────────────────────────────────────
# 개념 그래프 (§4.2 concept 도메인 인라인 DDL — 4종)
# ──────────────────────────────────────────────────────────────────────────
# §14.3에 별도 `CREATE TYPE`이 없어 §4.2 DDL의 컬럼 인라인 주석을 정본으로 채택한다
# (slice1 ExamType/Subject가 §3.1 컬럼 주석을 정본으로 삼은 선례와 동일). ConceptLevel만
# 한글 값(Persona처럼 한글 식별자 허용), 나머지 3종은 영어 값.
class ConceptLevel(str, Enum):
    """개념 노드 계층 — §4.2 `concept_level_enum`(L309 주석: 단원/소단원/세부개념).

    3계층 위계(단원 > 소단원 > 세부개념). 값·식별자 모두 한글(`Persona` 선례).
    use_enum_values=True 직렬화 시 한글 값이 그대로 보존된다(예: level="단원").
    """

    단원 = "단원"
    소단원 = "소단원"
    세부개념 = "세부개념"


class CognitiveType(str, Enum):
    """개념의 인지 유형 — §4.2 `cognitive_type_enum`(L320-321, 영어 5종).

    한 개념이 여러 유형을 가질 수 있어 `concept.cognitive_type`은 배열이다.
    """

    DEFINITION = "DEFINITION"
    """정의 — 수학적 개념의 엄밀한 규정."""

    THEOREM = "THEOREM"
    """정리 — 증명되는 명제(예: 미적분학의 기본정리)."""

    TECHNIQUE = "TECHNIQUE"
    """기법 — 계산·풀이 절차(예: 부분적분)."""

    PATTERN = "PATTERN"
    """패턴 — 반복되는 문제 구조·전형."""

    VISUAL_REASONING = "VISUAL_REASONING"
    """시각적 추론 — 그래프·도형 기반 사고."""


class BehaviorArea(str, Enum):
    """행동영역(cognitive action) — SkillNode의 폐쇄 6종 축(리치 Part 2 Phase 2a·2026-07-03 확정).

    개념이 *어떻게* 작동하는지(행동)의 축으로, 개념(무엇)과 직교한다. `skill_node.behavior_area`
    (PG native `behavior_area_enum`)의 백킹이며, data-pipeline `data_pipeline.skill_graph.models
    .BehaviorArea`와 **값이 정확히 일치**한다(정합 테스트 동결). 폐쇄 6종 — 확장은 ADR 갱신 전제
    (무분별 증식 금지·`test_skill_governance` 동결).
    """

    COMPUTE = "COMPUTE"
    """계산실행 — 절차·연산 수행(예: 다항식 나눗셈)."""

    TRANSFORM = "TRANSFORM"
    """식변형 — 표현을 등가 형태로 변형(예: 인수분해)."""

    INTERPRET = "INTERPRET"
    """조건해석 — 주어진 조건·문제를 수학 구조로 해석."""

    REPRESENT = "REPRESENT"
    """표상/표현 — 그래프·도형·다중표현 전환."""

    REASON = "REASON"
    """추론 — 연역·논리적 근거 전개."""

    VERIFY = "VERIFY"
    """검증 — 결과 점검·반례·타당성 확인(Polya 반성)."""


class EdgeType(str, Enum):
    """개념 간 관계(DAG 엣지) — §4.2 `edge_type_enum`(L345-350, 영어 6종)."""

    PREREQUISITE = "PREREQUISITE"
    """선수 — A를 알아야 B를 안다(A→B)."""

    COMPOSED_OF = "COMPOSED_OF"
    """구성 — A는 B,C,D로 이루어진다."""

    ANALOGOUS_TO = "ANALOGOUS_TO"
    """유사 — A와 B는 비슷한 사고를 요구한다."""

    EXTENDS = "EXTENDS"
    """확장 — A를 일반화하면 B가 된다."""

    CONTRASTS = "CONTRASTS"
    """대조 — A와 B는 혼동하기 쉽다."""

    TRIGGERS_DISTRACTOR = "TRIGGERS_DISTRACTOR"
    """오개념 유발 선택지 — distractor(객관식 오답 선지)가 misconception을 유발한다(슬108 어휘).

    이번 슬라이스는 *어휘만* 선언하고 `concept_edge` 적재는 하지 않는다 — `concept_edge`는
    concept→concept(UUID FK)인데 misconception은 아직 그래프 노드가 아니라 카탈로그(kebab id)다.
    노드화 전까지 distractor→misconception 매핑은 op-code 카탈로그
    (`l4/misconception/distractor.py`)가 보유한다."""


class RequiredStrength(str, Enum):
    """선수학습 관계의 필요 강도 — §4.2 `required_strength_enum`.

    EOS 6_개념 DB 검토 §13에 따른 prerequisite 메타. edge_type=PREREQUISITE일 때
    이 관계가 얼마나 필수적인지를 나타낸다.
    """

    WEAK = "WEAK"
    """약한 선호 — 없어도 학습이 가능하나 효율이 떨어진다."""

    MODERATE = "MODERATE"
    """중간 — 복습을 권장한다."""

    STRONG = "STRONG"
    """강함 — 거의 필수이며, 미흡 시 상위 개념 학습에 장애가 크다."""

    CRITICAL = "CRITICAL"
    """필수 — 없으면 상위 개념 진행이 불가능하다."""


class DependencyLevel(str, Enum):
    """선수학습 관계의 의존 수준 — §4.2 `dependency_level_enum`.

    EOS 6_개념 DB 검토 §13에 따른 prerequisite 메타. edge_type=PREREQUISITE일 때
    의존이 권장/기대/필수인지를 구분한다.
    """

    RECOMMENDED = "RECOMMENDED"
    """권장 — 도움이 되나 강제하지 않는다."""

    EXPECTED = "EXPECTED"
    """기대됨 — 일반적으로 요구된다."""

    REQUIRED = "REQUIRED"
    """필수 — 반드시 충족해야 한다."""


class ConceptRole(str, Enum):
    """문제 안에서 개념의 역할 — §4.2 `concept_role_enum`(L366-370, 영어 4종)."""

    PRIMARY = "PRIMARY"
    """핵심 개념 — 이 문제의 주된 개념."""

    SUPPORTING = "SUPPORTING"
    """보조 개념 — 계산 등에 필요한 부수 개념."""

    IMPLICIT = "IMPLICIT"
    """암묵적 사용 — 학생이 의식하지 못해도 쓰이는 개념."""

    TESTED = "TESTED"
    """평가 대상 개념 — 이 문제로 이해도를 측정하는 개념."""


# 문제가 *평가하는* 개념 역할(PRIMARY·TESTED) — BKT 숙달 갱신·IRT θ 추정·약점 가중의 단일
# 대상 집합(보조 SUPPORTING·암묵 IMPLICIT 제외). L2(mastery_tracking·ability_estimation·진단)·
# L5(me)가 공유하는 단일 출처(slice 84에 분산 정의 통합).
ASSESSED_ROLES: tuple[ConceptRole, ...] = (ConceptRole.PRIMARY, ConceptRole.TESTED)


# ──────────────────────────────────────────────────────────────────────────
# 학생 학적·트랙 (§5.1 user_profile 인라인 DDL §14.3 school_type_enum — 슬라이스 4)
# ──────────────────────────────────────────────────────────────────────────
# §14.3에 `CREATE TYPE`이 있는 것은 school_type_enum 하나뿐이고(L1205-1209, 정본·완전),
# 나머지 트랙·전공·디바이스·구독·접근성 enum은 §5.1 user_profile DDL의 컬럼 인라인 주석을
# 정본으로 채택한다(slice1 ExamType/Subject가 §3.1 컬럼 주석을 정본으로 삼은 선례 동일).
# 한글 값은 한글 식별자 그대로(Persona·ConceptLevel 선례), 영어 값은 영어 그대로.
#
# ⚠️ gender_enum·region_enum은 *enum으로 만들지 않는다*. §14.3에 정의가 없고 §5.1 DDL 주석도
# 불완전하다(gender="선택 입력"으로 값 미기재, region="강남/대치/지방/..."로 명시적 미완결).
# v1.1 student_profile.schema.yaml가 region을 시도교육청 코드 문자열로 모델링한 점·미성년
# 민감정보라 닫힌 카테고리 강제가 부적절한 점을 고려해 user_profile에서 `str | None`으로
# 둔다(닫힌 enum 날조 회피). 추후 Kiki가 값을 확정하면 enum으로 승격한다.
class SchoolType(str, Enum):
    """학교 유형 — §14.3 `school_type_enum`(L1205-1209) 값 그대로(한글, 12종).

    §14.3에 유일하게 완전한 `CREATE TYPE`이 있는 학적 enum이다(자사고·대안학교는
    전국/광역·인가/비인가로 세분). use_enum_values=True 직렬화 시 한글 값 보존
    (예: school_type="일반고").
    """

    일반고 = "일반고"
    자사고_전국 = "자사고_전국"
    자사고_광역 = "자사고_광역"
    외고 = "외고"
    국제고 = "국제고"
    영재고 = "영재고"
    과학고 = "과학고"
    특성화고 = "특성화고"
    대안학교_인가 = "대안학교_인가"
    대안학교_비인가 = "대안학교_비인가"
    홈스쿨링 = "홈스쿨링"
    검정고시 = "검정고시"


class TrackType(str, Enum):
    """입시 트랙 — §5.1 `track_type_enum`(L455 주석) 값 그대로(한글 7종 + MMI 영어).

    한 학생이 여러 트랙을 병행할 수 있어 `user_profile.track_type`은 배열이다.
    """

    정시 = "정시"
    수시학종 = "수시학종"
    수시교과 = "수시교과"
    수시논술 = "수시논술"
    MMI = "MMI"
    """다중미니면접(Multiple Mini Interview) — 의대 등 면접 전형."""

    특기자 = "특기자"
    농어촌 = "농어촌"
    특례 = "특례"


class MajorCategory(str, Enum):
    """목표 전공 계열 — §5.1 `major_category_enum`(L459 주석) 값 그대로(한글 8종)."""

    의대 = "의대"
    약대 = "약대"
    치대 = "치대"
    한의대 = "한의대"
    이공계 = "이공계"
    인문계 = "인문계"
    경상계 = "경상계"
    예체능 = "예체능"


# ──────────────────────────────────────────────────────────────────────────
# 학습 환경 (§5.1 user_profile device_enum·note_app_enum)
# ──────────────────────────────────────────────────────────────────────────
class Device(str, Enum):
    """주 사용 기기 — §5.1 `device_enum`(L473 주석) 값 그대로(아이패드/iPhone/안드로이드폰/PC)."""

    아이패드 = "아이패드"
    # 멤버명이 곧 정본 값("iPhone")이라 Apple 제품명 카멜케이스를 그대로 둔다(N815 억제).
    iPhone = "iPhone"  # noqa: N815
    안드로이드폰 = "안드로이드폰"
    PC = "PC"


class NoteApp(str, Enum):
    """필기 앱 — §5.1 `note_app_enum`(L475 주석) 값 그대로(굿노트/노타빌리티/플렉슬/없음, 한글)."""

    굿노트 = "굿노트"
    노타빌리티 = "노타빌리티"
    플렉슬 = "플렉슬"
    없음 = "없음"


# ──────────────────────────────────────────────────────────────────────────
# 결제·접근성 (§5.1 user_profile subscription_tier_enum·accessibility_enum)
# ──────────────────────────────────────────────────────────────────────────
class SubscriptionTier(str, Enum):
    """구독 티어 — §5.1 `subscription_tier_enum`(L490 주석) 값 그대로(free/basic/premium, 영어)."""

    free = "free"
    basic = "basic"
    premium = "premium"


class Accessibility(str, Enum):
    """접근성 필요 — §5.1 `accessibility_enum`(L501 주석) 값 그대로(한글 5종, 특성 #47).

    한 학생이 여러 접근성 필요를 가질 수 있어 `user_profile.accessibility_needs`는 배열이다.
    """

    시각약자 = "시각약자"
    색약 = "색약"
    큰글씨 = "큰글씨"
    음성안내 = "음성안내"
    시간연장 = "시간연장"


# ──────────────────────────────────────────────────────────────────────────
# 학습 활동 (§6.1 learning_session·problem_attempt·attempt_event 인라인 DDL — 3종)
# ──────────────────────────────────────────────────────────────────────────
# §14.3에 별도 `CREATE TYPE`이 없어 §6.1 DDL의 컬럼 인라인 주석을 정본으로 채택한다
# (slice1 ExamType/Subject·slice3 ConceptLevel이 컬럼 주석을 정본으로 삼은 선례 동일).
# 세 enum 모두 한글 값(한글 식별자 그대로 — Persona·ConceptLevel 선례).
class SessionType(str, Enum):
    """학습 세션 유형 — §6.1 `session_type_enum`(L602-603, 한글 5종).

    use_enum_values=True 직렬화 시 한글 값 보존(예: session_type="자유학습").
    """

    자유학습 = "자유학습"
    실전모의고사 = "실전모의고사"
    단원집중 = "단원집중"
    약점보완 = "약점보완"
    AI추천 = "AI추천"


class AttemptMode(str, Enum):
    """문항 풀이 방식 — §6.1 `attempt_mode_enum`(L635-636, 한글 4종).

    특성 #96(used_socratic vs used_solution_view)으로 콴다 대비 차별을 측정한다.
    """

    자유풀이 = "자유풀이"
    Socratic대화 = "Socratic대화"
    힌트제공 = "힌트제공"
    풀이공개 = "풀이공개"


class EventType(str, Enum):
    """학생 풀이 단계 이벤트 — §6.1 `event_type_enum`(한글 8종 + 검산결과 + 힌트제공 + 시각화조작).

    실시간 분석용(TimescaleDB hypertable `attempt_event`)의 이벤트 종류.

    페이로드 계약(invariant ⑫): *생산되는* 6종(검산결과·힌트제공·시각화조작·막힘·힌트요청·답입력)의
    `event_data` 모양은 `schema/event_data_contract.py`(EVENT_DATA_CONTRACT)가 단일 진실원으로
    고정한다. 나머지 5종(문제읽기·조건분석·그래프그리기·계산·지움)은 생산자가 아직 0이라 계약
    면제(휴면)다. `막힘`·`힌트요청`·`답입력`은 S3-16에서 휴면→생산으로 소생됐다(신규 enum 값
    추가 아님 — 기존 3종의 생산자를 `api/coach.py`에 배선).
    """

    문제읽기 = "문제읽기"
    조건분석 = "조건분석"
    그래프그리기 = "그래프그리기"
    계산 = "계산"
    지움 = "지움"
    막힘 = "막힘"
    """WH-1 답 미루기 5회+ 막힘 임계 이벤트(S3-16 소생)·event_data={turn_count:int}.

    `l4.hint_deferral.is_stuck_turn_count`(turn_count≥5)가 True일 때만 스테이트풀 coach가
    적재한다 — `decide_hint_level`의 1번 규칙(5회+ 막힘→hint_level 최소 3)과 *같은 임계*를
    관측 신호로 노출할 뿐 결정 로직 자체는 건드리지 않는다.
    """

    힌트요청 = "힌트요청"
    """학생이 *요청*한 도움 demand 이벤트(S3-16 소생)·event_data={mode, persona}(선택 태그만).

    `l4.hint_deferral.is_answer_demand`(답 요구 토큰 포함)가 True일 때만 적재한다. `힌트제공`
    (AI가 *제공*한 supply·hint_level)과 의미가 다르다 — 지표 ⑫(도움 요청/제공 비)는 이 둘의
    개수 비다.
    """

    답입력 = "답입력"
    """학생 응답 제출의 서버 측 지연 이벤트(S3-16 소생)·event_data={server_latency_ms:int|None}.

    직전 학생 턴(server 기준 spoken_at)과 이번 제출 시각의 차 — 서버 시각 차이므로 클라 신뢰가
    불필요하고 조작 불가하다. 이전 학생 턴이 없으면(새 dialogue의 첫 턴) 기준선이 없어 적재하지
    않는다(날조 회피) — `append_turns`에서만 생산된다.
    """

    검산결과 = "검산결과"
    """WH-1 검산(verify) 결과 이벤트·event_data={passed:bool, error_kind}.

    binary 검산(3-state 아님): passed=거짓 수치관계 *미적발*(통과)·아니면 적발.
    스테이트풀 coach가 풀이 제출 턴에만 적재한다.
    """

    힌트제공 = "힌트제공"
    """WH-1 도움 감소 곡선 이벤트(지표 ⑤)·event_data={hint_level:int}(1~4·1=가장 은근/4=전체 풀이).

    *supply*(AI가 제공한 hint_level) 신호다 — `힌트요청`(학생이 *요청*한 demand)과 의미가 다르다.
    도움 감소 곡선은 AI가 *제공한* 노출량(graded 1~4)의 시간 추세이므로 supply가 정본이다.
    스테이트풀 coach가 매 응답 턴에 `decision.hint_level`을 그대로 적재한다(재계산 없음).
    `AttemptMode.힌트제공`(attempt_mode_enum·풀이 방식)과는 *다른 enum*이니 혼동 주의.
    """

    시각화조작 = "시각화조작"
    """L5 시각화의 *탐구적* 조작 이벤트(슬라이더·3D 식·확률 시뮬)·슬라이스 96-J.

    event_data={interaction, payload, concept_id, scene_id, client_at}. `그래프그리기`(그래프를
    그려 *답함*)와 구분되는 *능동 탐구·메타인지* 신호다 — 약점개념 scene의 임베드 계산기에서
    학생이 파라미터·식을 바꿔 본질을 탐색하는 행동. 둘을 한 enum으로 뭉개면 L2 행동 지표가
    오염되므로 전용 라벨로 분리한다. 약점개념 흐름엔 problem/attempt가 없어 컨텍스트는
    concept_id/scene_id(event_data)로 싣고 attempt_id/problem_id는 NULL로 둔다(거짓 연결 금지).
    """

    문제시도 = "문제시도"
    """채점 확정 시점의 *문제 시도* 이벤트(EOS-57, 계획서 표기 `problem_attempted`).

    **이 값의 존재 이유는 `attempt_event.skill_ids`(해소된 스킬 배열)의 영속 좌석**이다 — 채점이
    확정된 순간 `l2.skill_mastery_tracking`이 concept→skill로 *해소한* 스킬 목록을 런타임에서
    버리지 않고 이벤트에 남긴다(W2 "되돌릴 수 없는 스키마" ① — 12월 데이터에 남길 소급 불가 축.
    지금 적재하지 않으면 과거 시도의 스킬 귀속은 영원히 재구성 불가다).

    `답입력`(코치 대화의 서버 응답 지연 신호)과 혼동 금지 — 저 이벤트는 *대화 턴* 텔레메트리이고
    이 이벤트는 *채점 확정 1건*에 대응한다. 두 채점 경로(`api/me.py::submit_attempt`의 클라
    자가보고 v1 경로·`api/coach.py::_complete_problem`의 서버 검증 경로)가 같은 writer
    (`l2.attempt_skill_event.record_attempt_skill_event`)를 경유해 적재하며 `event_data.source`가
    둘을 구분한다.

    스킬 배열은 `event_data`가 아니라 **1급 컬럼 `attempt_event.skill_ids`** 에 싣는다(조인·집계
    축이라 JSONB에 묻지 않는다). NULL=미기록(구판 이벤트·writer 미도달)·`{}`=해소를 실행했으나
    매핑 0건 — 둘을 구분한다(S3-07 None≠0 규약).
    """


# ──────────────────────────────────────────────────────────────────────────
# Socratic 대화 (§7.1 dialogue·dialogue_turn 인라인 DDL — 5종)
# ──────────────────────────────────────────────────────────────────────────
# §14.3에 별도 `CREATE TYPE`이 없어 §7.1 DDL의 컬럼 인라인 주석을 정본으로 채택한다
# (위 활동 도메인·slice1·slice3 선례 동일). TurnRole만 영어 값(student/assistant/system),
# 나머지 4종은 한글 값(한글 식별자 그대로 — Persona·ConceptLevel 선례).
class Resolution(str, Enum):
    """Socratic 대화 종결 결과 — §7.1 `resolution_enum`(L710-711, 한글 5종).

    학생이 스스로 풀었는지·유도로 풀었는지·결국 풀이를 봤는지·포기했는지를 가른다.
    """

    학생자력해결 = "학생자력해결"
    Socratic유도성공 = "Socratic유도성공"
    힌트필요 = "힌트필요"
    풀이공개로종결 = "풀이공개로종결"
    포기 = "포기"


class TurnRole(str, Enum):
    """대화 턴 화자 — §7.1 `turn_role_enum`(L735, 영어 3종).

    student(학생)·assistant(AI)·system(시스템 메시지). 값·식별자 모두 영어.
    """

    student = "student"
    assistant = "assistant"
    system = "system"


class ContentType(str, Enum):
    """대화 턴 콘텐츠 형식 — §7.1 `content_type_enum`(L737, 한글 4종)."""

    텍스트 = "텍스트"
    수식 = "수식"
    이미지 = "이미지"
    혼합 = "혼합"


class SocraticStrategy(str, Enum):
    """Socratic 발문 전략 — §7.1 `socratic_strategy_enum`(L740-741, 한글 6종).

    AI 응답의 교수학적 전략(특성 #8/#18 조건확인·#21 단계분해).
    """

    조건확인 = "조건확인"
    예시제시 = "예시제시"
    반례제시 = "반례제시"
    단계분해 = "단계분해"
    유사문제 = "유사문제"
    그래프그리기제안 = "그래프그리기제안"


class StudentIntent(str, Enum):
    """학생 발화 의도 — §7.1 `student_intent_enum`(L747-748, 한글 5종).

    학생 턴을 분석해 분류한 의도(답시도/질문/막힘표현/포기/이해확인).
    """

    답시도 = "답시도"
    질문 = "질문"
    막힘표현 = "막힘표현"
    포기 = "포기"
    이해확인 = "이해확인"


# ──────────────────────────────────────────────────────────────────────────
# 학습 진단 (§8.1 assessment 인라인 DDL — 2종)
# ──────────────────────────────────────────────────────────────────────────
# §14.3에 별도 `CREATE TYPE`이 없어 §8.1 DDL의 컬럼 인라인 주석을 정본으로 채택한다
# (slice1 ExamType/Subject·slice3 ConceptLevel·slice5 SessionType이 컬럼 주석을 정본으로
# 삼은 선례 동일). 두 enum 모두 한글 값(한글 식별자 그대로 — Persona·ConceptLevel 선례).
class AssessmentType(str, Enum):
    """진단 평가 유형 — §8.1 `assessment_type_enum`(L783-784, 한글 5종).

    use_enum_values=True 직렬화 시 한글 값 보존(예: assessment_type="단원진단").

    ⚠️ 식별자 주의: `D-100예측`은 하이픈이 있어 Python 식별자로 쓸 수 없다. 따라서 멤버명만
    언더스코어로 두고(`D_100예측`) *값은 하이픈 그대로*(`"D-100예측"`)다 — 값이 정본이라
    직렬화·역직렬화는 `"D-100예측"`이 오간다. 나머지 4종은 값=식별자 동일.
    """

    초기진단 = "초기진단"
    주간진단 = "주간진단"
    단원진단 = "단원진단"
    실전모의고사 = "실전모의고사"
    D_100예측 = "D-100예측"
    """D-100 합격 예측 진단(특성 #86). 식별자만 언더스코어, 값은 하이픈 그대로(정본)."""


class MentalPhase(str, Enum):
    """입시 멘탈·시간 관리 단계 — §8.1 `mental_phase_enum`(L810-811, 6종, 특성 #50).

    D-100 입시 코칭의 D-day 구간(수능 100일 전 이상 → 당일)과 평상시를 가른다. 값들이 이미
    식별자 안전(언더스코어·한글)이라 멤버명=값 동일(slice5 EventType처럼 변환 불필요).
    use_enum_values=True 직렬화 시 값 보존(예: mental_phase="D_100_50").
    """

    D_100_PLUS = "D_100_PLUS"
    """D-100 이상 — 수능 100일 전보다 더 남은 장기 구간."""

    D_100_50 = "D_100_50"
    """D-100~D-50 — 본격 실전 대비 진입."""

    D_50_30 = "D_50_30"
    """D-50~D-30 — 약점 집중 보완 구간."""

    D_30_7 = "D_30_7"
    """D-30~D-7 — 마무리·실전 감각 유지."""

    D_7_0 = "D_7_0"
    """D-7~D-day — 컨디션·멘탈 관리 최우선 구간."""

    평상시 = "평상시"
    """입시 D-day 코칭 대상이 아닌 평상시(예: 고1·고2 학기 중)."""


# ──────────────────────────────────────────────────────────────────────────
# 다국 커리큘럼 매트릭스 (v1.1 curriculum_entry.schema.yaml — 슬라이스 8a)
# ──────────────────────────────────────────────────────────────────────────
# v1.0 도메인 밖. v1.1에서 이식한 CurriculumEntry(같은 개념이 나라마다 몇 학년에·어떤
# 깊이로 다뤄지는지의 매트릭스 셀)가 *enum으로 명시한 두 필드*만 enum으로 만든다.
# YAML이 enum으로 명시한 것은 required_depth(4종)·license_id(5종)뿐이다.
#
# ⚠️ country_code·grade_band·cognitive_level 등은 enum으로 만들지 않는다. YAML이
# country_code를 ISO 3166-1 alpha-2(개방형 ~250개)+의사코드 'IMO'로 두고 "스키마는
# 풀스케일 수용"이라 명시했고(Phase 3 9~12개국 확장 대비), Phase 1 KR/US/IMO 범위
# 가드는 *데이터/파이프라인* 책임이지 모델 강제가 아니다. subject 류도 NCIC
# AchievementStandard.subject가 str인 것과 정합 → `str`로 둔다(slice4 gender/
# school_region이 닫힌 enum 날조를 회피해 str로 둔 방침과 동일).
class RequiredDepth(str, Enum):
    """국가 교육과정이 개념에 요구하는 깊이 — YAML `required_depth.enum`(영어 4종).

    awareness < procedural < conceptual < mastery 순의 깊이 위계. use_enum_values=True
    직렬화 시 영어 값 보존(예: required_depth="conceptual").
    """

    awareness = "awareness"
    """인지 — 개념을 접하고 존재를 안다(가장 얕은 깊이)."""

    procedural = "procedural"
    """절차 — 정해진 절차·계산을 수행할 수 있다."""

    conceptual = "conceptual"
    """개념 — 원리를 이해하고 맥락에 적용할 수 있다."""

    mastery = "mastery"
    """숙달 — 능숙하게 다루고 새 상황에 전이할 수 있다(가장 깊은 깊이)."""


class CurriculumLicense(str, Enum):
    """국가별 원천 자원 라이선스 매트릭스 키 — YAML `license_id.enum`(5종).

    셀 단위로 라이선스 의무를 추적한다(라이선스 미확인 국가는 셀을 만들지 않음 —
    licensing_safety.md 결정 트리).

    ⚠️ 식별자 주의: 값이 하이픈을 포함해(예 'KR-NCIC') Python 식별자로 쓸 수 없다. 따라서
    멤버명만 언더스코어로 두고(`KR_NCIC`) *값은 하이픈 그대로*(`"KR-NCIC"`)다 — 값이 정본
    이라 직렬화·역직렬화는 하이픈 값이 오간다(slice6 `AssessmentType.D_100예측` 선례 동일).
    use_enum_values=True 직렬화 시 하이픈 값 보존(예: license_id="KR-NCIC").
    """

    KR_NCIC = "KR-NCIC"
    """한국 2022 개정 교육과정 — 공공누리 1유형(상업·가공 OK, 출처 표시 필수)."""

    US_CCSS = "US-CCSS"
    """미국 Common Core — CCSSO/NGA 조건부(출처 표시·비변형 배포)."""

    INT_IMO = "INT-IMO"
    """IMO 신택터스 — 공식 표준 부재, WhyMath 자체 정리물."""

    JP_MEXT = "JP-MEXT"
    """일본 学習指導要領 — 정부 고시(Phase 3)."""

    GB_NC = "GB-NC"
    """영국 National Curriculum — OGL v3.0, CC BY 호환(Phase 3)."""


# ──────────────────────────────────────────────────────────────────────────
# 교과서 매핑 (v1.1 textbook_mapping.schema.yaml — 슬라이스 8b)
# ──────────────────────────────────────────────────────────────────────────
# v1.0 도메인 밖. v1.1에서 이식한 마지막 자산 TextbookMapping(검정 교과서 *구조*를 개념·
# NCIC 성취기준에 잇는 매핑)이 *enum으로 명시한 한 필드*만 enum으로 만든다.
# YAML이 enum으로 명시한 것은 legal_review_status(3종)뿐이다.
#
# ⚠️ subject·publisher는 enum으로 만들지 않는다. YAML이 subject를 "8과목 enum"으로,
# publisher를 enum_phase1=[미래엔, 천재교육]로 *언급*하나 값을 완전히 열거하지 않았고
# (subject는 8과목 체계를 예시로만 들고, publisher는 examples로 8종 이상을 더 든다),
# 기존 NCIC AchievementStandard.subject가 str인 것과 정합하므로 모델에서 `str`로 둔다
# (slice4 gender·slice8a country_code가 닫힌 enum 날조를 회피해 str로 둔 방침과 동일).
# Phase 1 범위 가드(미래엔/천재교육 2종·8과목)는 *데이터/파이프라인* 책임이지 모델 강제 아님.
class LegalReviewStatus(str, Enum):
    """교과서 학습목표 텍스트 변호사 검토 상태 — YAML `legal_review_status.enum`(영어 3종).

    `TextbookMapping.legal_review_status`가 `TextbookUnit.learning_objective_text`의 활성화
    여부를 결정한다 — `cleared`가 아니면 학습목표 텍스트는 null 고정(비-null 발견 시 적재
    거부). 근거: MEMORY PRD 허점 ⑥ — 한국 저작권법에 미국식 fair use 법리가 그대로 있지
    않아 교과서 저작물인 학습목표 문장을 "페어유즈" 단정으로 수집할 수 없다.

    ⚠️ 기존 `ReviewStatus`(pending/approved/rejected, §3.1 문제 검수)와 *다른* enum이다 —
    이쪽은 교과서 학습목표 *저작권* 검토 상태다(혼동 주의). use_enum_values=True 직렬화 시
    영어 값 보존(예: legal_review_status="not_required").
    """

    not_required = "not_required"
    """구조 메타데이터만 — 검토 불요(learning_objective_text는 null이어야 함)."""

    pending = "pending"
    """검토 진행 중 — learning_objective_text는 여전히 null."""

    cleared = "cleared"
    """검토 통과 — learning_objective_text 활성화 가능."""


class AuditResourceType(str, Enum):
    """slice 57: `deletion_audit.resource_type` — GDPR 삭제 감사 대상 도메인.

    값은 해당 ORM `__tablename__`과 일치(learning_session·dialogue·assessment). 삭제 *부모*
    리소스만 기록(자식은 slice 56 DB cascade로 비가시 — 개별 감사 안 함).
    """

    learning_session = "learning_session"
    """학습 세션 삭제(slice 51)."""

    dialogue = "dialogue"
    """Socratic 대화 삭제(slice 52)."""

    assessment = "assessment"
    """진단 삭제(slice 53)."""

    user_profile = "user_profile"
    """계정 전체(삭제권) 삭제 — 사용자의 *모든* 학생-연결 데이터 단일 트랜잭션 영구 삭제(R11)."""


class AuditEventKind(str, Enum):
    """`privacy_audit.event_kind` — SEC-09 개인정보 감사 폐쇄 택소노미(현 5종).

    `docs/architecture/account_security_gap_review.md` D3의 경계 확정: `security_privacy.md:
    88-100`의 "모든 PII 접근 로그"는 **채택하지 않는다**(본인 조회 29개 엔드포인트 전수 감사는
    미성년 프로파일링 자산화·볼륨 소음 — 정정 경위는 `docs/standards/security_privacy.md` §감사
    로그 편집자 부기 참조). 감사 대상은 "시스템 밖으로 나가는 사건"·"본인 아닌 주체의 접근"·
    "계정 권한 자체의 변경"·**"전역 콘텐츠 리소스의 CUD"**(SEC-29가 추가한 4번째 축 — 학생
    개인정보가 아니라 개념·문항 같은 공유 콘텐츠 대상이라 D3의 "모든 PII 접근 로그" 거부와
    무관하다)이며, 값은 그 편집자 부기의 pseudo-schema(`action` 필드)와 정확히 일치시킨다
    (부기에 값을 추가할 때 이 enum도 함께 늘린다 — 단일 진실원천).

    **4번째 값 `role_change`는 ADMIN-01(2026-08-11 회수)이, 5번째 값 `content_mutation`은
    SEC-29(2026-09-11)가 추가**했다. SEC-09 시점의 "3종"은 그 시점 실측이었을 뿐 상한이 아니다
    — 폐쇄 택소노미의 뜻은 "임의 문자열 금지"이지 "영원히 3개"가 아니다.

    `deletion_audit`(별도 테이블·`DeletionAudit`)이 **학생 소유 데이터 삭제** 감사의 단일
    권위를 유지하므로 그 도메인의 `resource_type`류 삭제 이벤트는 여기 포함하지 않는다(이중
    진실원천 금지 — D3 판단 근거). `content_mutation`의 `resource_type`(개념·문항)은 학생
    소유 데이터가 아닌 *전역 콘텐츠*를 가리키므로 이 경계와 겹치지 않는다(`PrivacyAuditResourceType`
    docstring 참조 — `AuditResourceType`과 값 공간을 분리한 이유).
    """

    export_data = "export_data"
    """`GET /v1/me/export` — 본인 데이터가 시스템 밖(응답 payload)으로 반출됨."""

    consent_change = "consent_change"
    """`POST /v1/users/me/parental-consent` — 법정대리인 동의 상태 변경."""

    admin_access = "admin_access"
    """관리자(`Role.CONTENT_ADMIN` 이상)가 *본인 아닌* 사용자의 개인정보에 접근.

    **현재 호출부 0곳**(SEC-09 시점 실측) — 관리자 콘솔(`docs/design/ui/04_admin_console_
    architecture.md` Phase B)이 아직 없어 이 값을 실제로 적재하는 엔드포인트가 없다. 값·모델·
    writer(`privacy.audit.record_admin_access_audit`)는 그 콘솔이 착지할 때 바로 배선할 수
    있도록 미리 세운다(가짜 이벤트 날조 금지 — 실 호출부가 생기기 전까지는 진짜로 0행이다).
    """

    role_change = "role_change"
    """`ops/role_grant_cli.py`(ADMIN-01) grant/revoke — `user_profile.role` 변경.

    **이번 CLI가 진짜 첫 호출부다**(위 `admin_access`와 달리 "호출부 0곳"이 아니다) —
    `Role.CONTENT_ADMIN`을 실 사용자에게 부여하는 경로가 저장소 전체에 0건이던 갭(콘텐츠 CUD
    6라우터는 게이팅되지만 그 문을 열 열쇠를 아무도 발급할 수 없던 상태)을 이 CLI가 메우면서,
    부여/회수와 `privacy.audit.record_role_change_audit`가 *같은 트랜잭션*으로 이 값을 적재한다
    (`ops/role_grant_cli.py` 모듈 docstring 참조). HTTP 미노출 — 순수 ops CLI, 운영자 직접 실행
    (`retention_purge_cli` 컨벤션 미러).
    """

    content_mutation = "content_mutation"
    """`Role.CONTENT_ADMIN`이 콘텐츠 리소스(개념·문항)를 생성·수정·삭제(SEC-29).

    **5번째 값 — `record_admin_access_audit`이 겨냥한 "관리자가 학생 개인정보를 봄"과는
    다른 축이다.** `admin_access`는 여전히 호출부 0곳(관리자 콘솔 Phase B 전제, ADMIN-06
    미착지)이지만, "콘텐츠 CUD에 감사 로그가 없다"(누가 어떤 문항을 승인·격리·삭제했는지
    흔적 없음 — `docs/reviews/eos_one_subject_completion_review_2026-09-03.md` §S3)는
    ADMIN-06과 무관하게 *오늘* 실재하는 별도 갭이고, `RequireContentAdmin`이 이미 게이팅하는
    `POST/PATCH/DELETE /v1/concepts`·`/v1/problems` 6라우터가 그 실제 호출부다.

    `target_user_id`는 채우지 않는다(개인정보 대상이 아니라 콘텐츠 리소스 대상 — `resource_type`/
    `resource_id`가 그 역할). `user_id`는 행위자(관리자). `PrivacyAuditAction`(action 컬럼)이
    create/update/delete를 구분한다. `reason`류 자유텍스트는 넣지 않는다(`PrivacyAudit`
    모델 docstring의 "자유텍스트 필드는 두지 않는다" 불변식 — 무엇을 했는지는 action+resource로
    충분히 특정된다).
    """


class PrivacyAuditResourceType(str, Enum):
    """`privacy_audit.resource_type` — `event_kind=content_mutation` 전용 콘텐츠 리소스
    도메인(SEC-29).

    `AuditResourceType`(`deletion_audit` 전용 — 학생 연결 데이터 삭제 도메인)과는 별개의 폐쇄
    택소노미다. 값은 해당 ORM `__tablename__`과 일치(concept·problem — `AuditResourceType`과
    동일 명명 관례). 두 enum을 분리한 이유: `deletion_audit`은 "학생이 소유한 데이터의 영구
    삭제"만 다루는 단일 권위(`AuditEventKind` docstring D3 — 이중 진실원천 금지)인 반면,
    `content_mutation`은 *학생이 소유하지 않는 전역 콘텐츠*(개념·문항)의 생성·수정·삭제라
    범주 자체가 다르다 — 같은 이름의 컬럼을 재사용해도 값 공간을 섞지 않는다.
    """

    concept = "concept"
    """`Concept`(`db/models/concept.py`) — `/v1/concepts` CUD."""

    problem = "problem"
    """`Problem`(`db/models/problem.py`) — `/v1/problems` CUD."""


class PrivacyAuditAction(str, Enum):
    """`privacy_audit.action` — `event_kind=content_mutation` 전용 CRUD 동작 폐쇄 택소노미(SEC-29).

    `resource_type`+`resource_id`가 *무엇을*, 이 값이 *무엇을 했는지*를 특정한다. 자유텍스트
    `reason`을 두지 않는 대신(`PrivacyAudit` 모델 docstring 참조) 이 3값만으로 "생성/수정/삭제"
    사실을 충분히 감사한다 — 상세 diff·사유는 이 테이블의 책임이 아니다(1차 기록은 애플리케이션
    로그·PG 자체의 데이터, 이 행은 "그 시각 그 사건이 있었다"는 2차 감사 신호 — `record_role_
    change_audit` docstring과 동일 철학).
    """

    create = "create"
    update = "update"
    delete = "delete"


class DefectCategory(str, Enum):
    """`defect_report.category` — 학생 결함 신고 카테고리(RPT-01, 폐쇄 6종).

    `docs/architecture/service_operations_gap_review.md` §3 D1의 설계를 따른다: 학생이
    문항·AI응답·수식 오류를 신고할 경로가 스키마·API·UI 전부 0건이었던 갭을 메우되, *자유서술은
    받지 않는다*(미성년 자유서술은 PII이고 SEC-01 암호화 좌석을 끌어옴 — v0는 카테고리 +
    `problem_id`만으로 QA 파이프라인을 특정 문항에 겨눌 수 있어 충분히 행동 가능하다).

    `AuditResourceType` 선례를 따라 ORM은 `sa.String(32)`(네이티브 PG enum 미생성) — 코드
    안전성은 이 Pydantic enum(`.value` 저장)으로, DB는 단순 문자열로 둔다.
    """

    콘텐츠오류 = "콘텐츠오류"
    """문항 발문·보기·정답·해설 등 콘텐츠 자체의 오류."""

    AI응답오류 = "AI응답오류"
    """코치 AI(소크라테스 대화·힌트 등) 응답의 오류(사실 오류·부적절한 힌트 등)."""

    수식오류 = "수식오류"
    """수식 렌더링·동치 판정·계산 결과의 오류."""

    오답의심 = "오답의심"
    """제공된 정답 자체가 틀렸다고 의심되는 경우."""

    UI문제 = "UI문제"
    """앱 UI/UX 결함(표시 깨짐·조작 불가 등) — 콘텐츠·AI 응답과 무관한 표면 결함."""

    기타 = "기타"
    """위 5종에 속하지 않는 기타 결함."""


class ConsentScope(str, Enum):
    """`parental_consent.consent_scope` — 14세 미만 법정대리인 동의가 *무엇을* 허용했는가.

    PIPA 만14세 미만 법정대리인 동의(docs/legal/pipa_data_matrix.md §3)의 *고지·동의 범위*를
    표현한다. PIPA는 동의 시 *수집 항목·이용 목적·보유 기간·제3자 제공 여부*를 명확히 고지할
    의무를 지우므로(§3.2), 동의 1건이 *무엇에 대한 동의였는지*를 감사 가능하게 기록한다.

    **기본값은 `service_core`(서비스 본 기능 이용을 위한 개인정보 처리·게이트 해제).**
    AI 튜터 응답 생성·학습 이력 저장 등 서비스 본 기능은 `service_core` 동의로 처리한다.
    모델 학습 개선·연구·마케팅 등 *별도 동의가 필요한 범위*는 각각 별도 동의 레코드(별 scope)
    로 받으며(CLAUDE.md "동의 없이 학습 사용 금지"·§5 체크리스트), 그 값들은 **변호사 자문
    으로 범위·문구가 확정된 뒤** 노출한다. 닫힌 카테고리지만 ORM은 String(32)로 두어
    (AuditResourceType 선례) 범위 추가 시 마이그레이션이 enum 변경을 요구하지 않게 한다.

    EOS Privacy & Consent Platform 검토(§18·§45·§48)에 따르면 AI inference(서비스 제공)
    와 AI training(모델 개선)은 반드시 분리된 처리 목적으로 관리해야 한다. `ai_inference`는
    `service_core`에 포함될 수 있으나, `ai_training`·`research`·`marketing`은 명시적 추가
    동의가 필요하다.
    """

    service_core = "service_core"
    """서비스 본 기능 이용을 위한 개인정보 처리 동의(미성년 게이트 해제) — §3.1 가입 단계."""

    ai_inference = "ai_inference"
    """AI Tutor 응답 생성·대화 문맥 저장 등 서비스 제공을 위한 AI 추론(§45·§49)."""

    ai_training = "ai_training"
    """모델 개선·fine-tuning·평가·품질 향상을 위한 학습 데이터 활용(§48). 별도 동의 필요."""

    research = "research"
    """교육 연구·통계·논문·벤치마크를 위한 데이터 활용(§53). 별도 동의 필요."""

    marketing = "marketing"
    """마케팅·프로모션·이벤트 알림을 위한 데이터 활용(§26). 별도 동의 필요."""

    @property
    def is_core_scope(self) -> bool:
        """서비스 본 기능(core) 동의 범위 여부(EOS §45·§48).

        `service_core`(서비스 본 기능)와 `ai_inference`(AI Tutor 응답 생성 등 서비스 제공)
        은 서비스 이용 게이트를 여는 *core* scope다. `ai_training`·`research`·`marketing`은
        별도 동의가 필요한 *optional* scope다.
        """
        return self in (ConsentScope.service_core, ConsentScope.ai_inference)


class Role(Enum):
    """`user_profile.role` — 인가(authorization) 역할, v0 **2값 확정(축소)**(SEC-07 D1).

    `require_role`(`api/_auth.py`)이 콘텐츠 CUD(개념·문제 생성/수정/삭제)를 게이팅하는 데
    쓴다. `.claude/agents/backend-engineer.md:248-262`·`docs/design/ui/04_admin_console_
    architecture.md` §2 원칙3은 `PARENT`/`TEACHER`/`SCHOOL_ADMIN`을 포함한 5종 골격을
    스케치하지만, **좌석(소비처) 없는 역할은 만들지 않는다**(dead code 금지) — 그 3종은
    Phase 3 대시보드/B2B 계약이 실체를 가질 때(`docs/architecture/account_security_gap_
    review.md` §5-②) 연다. 역할 추가는 마이그레이션 1줄이고, 잘못 만든 역할을 걷어내는
    비용이 더 크다.

    **7단 선형 서열을 의도적으로 미도입한다** — `docs/legal/pipa_data_matrix.md:33-47`이
    반증하듯 부모의 데이터 가시성은 학생 본인의 *부분집합*이지 상위집합이 아니다(오답
    패턴·또래 비교·힌트 사용은 부모에게 비공개이나 학생 본인에겐 공개). 선형 서열
    (`STUDENT < TEACHER < PARENT < ... < SYSTEM_ADMIN`류)은 "상위가 하위를 포함"을
    전제하므로 채택 시 미성년 보호 매트릭스를 구조적으로 깬다(`account_security_gap_
    review.md` §2-①). 이 사유로 다른 enum과 달리 **`str` mixin을 쓰지 않는다** — 순수
    `Enum`이라 `<`/`>` 비교가 `TypeError`를 던진다(house style은 `class X(str, Enum)`이나,
    str mixin은 멤버가 사전식으로 비교 가능해져(`"content_admin" < "student"`) 서열 연산이
    *존재하게* 된다 — 의미 없는 사전순이라도 연산 자체가 열려 있으면 미래 세션이 실수로
    등급 비교 코드를 짤 여지를 준다). `test_role_enum.py`가 멤버 수 2·서열 비교 부재를
    동결해 미래 세션이 7단 서열을 조용히 되살리지 못하게 막는다.

    Pydantic 직렬화 메모: str mixin이 아니므로 `UserProfile` 스키마의 `role` 필드는
    `Field(..., validate_default=True)`로 기본값도 검증 경로를 태워 `use_enum_values=True`가
    일관되게 적용되게 한다(기본값 미검증 시 `.value` 추출이 스킵되는 Pydantic v2 동작 회피).
    """

    STUDENT = "student"
    """기본 역할 — 모든 신규 가입자(마이그레이션 `server_default='student'`가 기존 행도 백필)."""

    CONTENT_ADMIN = "content_admin"
    """콘텐츠 CUD 권한 — 개념·문제(`/v1/concepts`·`/v1/problems`) 생성·수정·삭제."""


# ──────────────────────────────────────────────────────────────────────────
# 교수법 팩 지식 유형 (교수법 팩 + 소단원 DSL — 7유형→팩→증거)
# ──────────────────────────────────────────────────────────────────────────
# 근거: docs/reviews/260724_v2_migration_pedagogy_dsl_review.md(검토서)·
#       260724_v2_migration_pedagogy_dsl.alembic_draft.py(수정 목표 스키마).
#
# ⚠️ house style 예외(검토서 M4): 이 파일의 다른 상태/유형 축(concept_content.review_status·
# atom_node.cognitive_type 등)은 plain `sa.Text`로 두는 것이 관행이나, `knowledge_type`은
# *교수법 커널이 소유하는 과목 불변 축*(7유형이 교수법 팩과 1:1로 바인딩)이라 **PG native
# ENUM**으로 정합을 강제하는 것이 방어 가능하다(폐쇄 6종 `BehaviorArea`→`behavior_area_enum`
# native enum 선례와 동형). ORM은 이 enum을 `_pg_enum(KnowledgeType, "knowledge_type")`로
# PG native enum(타입명 `knowledge_type`)에 매핑한다. 관행 예외의 결정 근거는 MEMORY 결정
# 로그가 남긴다(검토서 §2 M4·§4 결정 필요 (1)).
class KnowledgeType(str, Enum):
    """교수법 팩 지식 유형 — 7유형 폐쇄 택소노미(커널 소유·과목 불변·PG native enum).

    각 학습목표(`learning_objective.k_type`)를 *어떤 종류의 지식*인지로 분류해 교수법 팩
    (`pedagogy_pack.k_type`)과 1:1 바인딩한다. "정답 도달"이 유형마다 다른 달성 증거를 요구
    한다는 설계 전제(개념형은 설명·표상형은 표현 전환·증명형은 논증)에서, 이 축이 팩·증거
    (`evidence_event.k_type`)를 가르는 뿌리다.

    멤버명·값 모두 영어(국제 인지 유형 어휘 — `BehaviorArea`·`CognitiveType`·`ReasoningType`
    선례). ⚠️ 폐쇄 7종 — 제거는 어렵고 추가는 신중해야 한다(native enum·거버넌스 결정 전제).
    use_enum_values=True 직렬화 시 영어 값 보존(예: k_type="CONCEPT").
    """

    CONCEPT = "CONCEPT"
    """개념·정의형 — 개념의 의미·정의를 이해·설명한다."""

    PROCEDURE = "PROCEDURE"
    """절차·알고리즘형 — 정해진 절차·계산을 정확히 수행한다."""

    REPRESENT = "REPRESENT"
    """표상연결형 — 식·그래프·도형 등 다중 표현을 잇고 전환한다."""

    PROOF = "PROOF"
    """증명·논증형 — 명제를 논리적으로 증명·정당화한다."""

    MODELING = "MODELING"
    """문제해결·모델링형 — 상황을 수학 구조로 모델링해 해결한다."""

    SPATIAL = "SPATIAL"
    """공간·시각형 — 도형·공간 관계를 시각적으로 추론한다."""

    STOCHASTIC = "STOCHASTIC"
    """데이터·불확실성형 — 확률·통계·불확실성을 다룬다."""


# ──────────────────────────────────────────────────────────────────────────
# 실행용 교수법 전략 (2단계 교수법 中 ② — 학생 학습 시점에 선택되는 전달 방식)
# ──────────────────────────────────────────────────────────────────────────
# 근거: docs/architecture/03c_content_strategy_cache.md §2.1(렌더 어댑터 축)·
#       04d_adaptive_pedagogy_engine.md §1(2단계 교수법 분리).
#
# `KnowledgeType`(설계용 축 — "무엇을 가르치나"로 교수법 팩을 가른다)과 **다른 축**이다. 이 enum은
# *같은* 교수법-중립 콘텐츠(ConceptDSL)를 학생 상태에 맞춰 *어떻게 보여줄지*를 가른다. 콘텐츠에
# 각인되지 않고 렌더 시점에 얹히므로, 저장 자산은 (중립 DSL × 전략)의 곱이 아니라 (중립 DSL +
# 어댑터 N개)의 합으로 유지된다(조합폭발 방지·"변형 열거 금지").
#
# ⚠️ house style: DB 컬럼을 두지 않는 **순수 Python 값객체 enum**이다(`ConsentScope` 선례 —
# 마이그레이션 결합을 피한다). 선택 결과를 영속해야 할 때가 오면 그때 native enum 승격을 별도
# 결정으로 판단한다(지금 추측으로 박지 않는다).
class PedagogyStrategy(str, Enum):
    """실행용 교수법 전략 — 폐쇄 10종(런타임 선택·렌더 어댑터 1:1 바인딩 축).

    선택 주체는 L4 Runtime Pedagogy Selector(04d §2)이고, 소비 주체는 L3 렌더 어댑터
    (03c §2.2)다. 각 전략은 *개념 무관* 어댑터 1개와 대응한다 — SOCRATIC 어댑터 하나가 모든
    개념에 작동하며, 개념별 어댑터를 복제하지 않는다.

    ⚠️ 폐쇄 10종 — 추가는 신중해야 한다(거버넌스 결정 전제·`test_render_governance.py`가 값집합을
    동결한다). 특히 **게임형(GAME)은 의도적으로 제외**했다: CLAUDE.md 절대 금기 "무자비한 게임화·
    중독성 설계 금지"가 정체성 축이므로, 게임형 추가는 중독성 없는 설계 명세가 확정된 뒤의 별도
    결정 사항이다(지금 넣지 않는다).

    멤버명·값 모두 영어(국제 교수법 어휘 — `KnowledgeType`·`ReasoningType` 선례).
    """

    DIRECT = "DIRECT"
    """직접교수 — 설명 중심으로 정의·원리를 제시한다."""

    SOCRATIC = "SOCRATIC"
    """소크라테스식 — 질문 중심으로 학생이 스스로 답에 도달하게 한다."""

    WORKED_EXAMPLE = "WORKED_EXAMPLE"
    """완전예제 — 풀이 과정을 끝까지 보여준다.

    ⚠️ 학생이 시도하기 *전*에 제공하면 "막혔을 때 바로 정답 제공 금지"를 어긴다(Polya 게이트).
    """

    PROBLEM_BASED = "PROBLEM_BASED"
    """문제기반 — 문제를 먼저 제시하고 필요한 개념을 뒤따라 끌어온다."""

    RETRIEVAL = "RETRIEVAL"
    """인출연습 — 기억에서 꺼내는 연습을 반복한다(계산 실수·정착 부족에 유효)."""

    SPACING = "SPACING"
    """분산복습 — 시간 간격을 두고 재노출한다(장기 파지)."""

    INTERLEAVING = "INTERLEAVING"
    """교차연습 — 유형을 섞어 제시한다(유형 변별력)."""

    SELF_EXPLANATION = "SELF_EXPLANATION"
    """자기설명 — 학생이 자기 말로 설명하게 유도한다(메타인지)."""

    ANALOGY = "ANALOGY"
    """비유 — 친숙한 상황에 빗대어 직관을 만든다(개념 이해 부족에 유효)."""

    VISUALIZATION = "VISUALIZATION"
    """시각화 — 그림·그래프 등 시각 표현을 앞세운다(렌더 intent는 L5 시각화 명세로)."""


# ──────────────────────────────────────────────────────────────────────────
# 콘텐츠 풀 분리 (ARCH-20 — docs/legal/copyright_gradient.md §4.2 집행)
# ──────────────────────────────────────────────────────────────────────────
class ContentPool(str, Enum):
    """코퍼스 사이드카(`_provenance.json`)의 `pool` 필드 — 3종 폐쇄(§4.2 원문 그대로).

    Share-Alike 의무가 있는 콘텐츠가 자체 저작 풀에 "전염"되는 것을 막기 위한 물리·논리
    분리 경계. 값 자체가 정본(`copyright_gradient.md` §4.2) — 추가는 그 문서 개정을 전제한다.
    """

    WHYMATH_ORIGINAL = "whymath-original"
    """자체 저작 + 공공누리 등 등급1(Share-Alike 의무 없음) 사실정보 소스 — 현재 전 코퍼스."""

    EXTERNAL_SHAREALIKE = "external-sharealike"
    """CC BY-SA 등 등급2 — Share-Alike 의무. 자체 풀과 물리·논리 분리 관리 필수."""

    EXTERNAL_LICENSED = "external-licensed"
    """등급3 협상 타결분 — 계약 범위 내에서만 사용."""


class GenerationFailureCode(str, Enum):
    """AI 생성 CU(콘텐츠 단위)의 실패코드 F1~F8 — EOS 검증설계서 v1 동결 계약.

    정본: `docs/standards/eos_verification_design_v1.md` §4 (EOS-51 · 2026-08-30 동결).
    모든 생성 실패·검수 반려는 이 8코드 중 하나로 강제 분류된다(자유 텍스트 사유 금지 —
    F-Ⅲ 실패분포 판정("F3+F6+F7 판단형 합 60% 초과 = 실패")이 이 분류 위에서만 성립한다).

    ⚠️ 폐쇄 8종 — G0(9/6) 동결 후 12월까지 추가·삭제·의미 변경 금지(검증 중 분류 체계가
    바뀌면 실패분포 시계열이 무효가 된다). 값은 `F1`~`F8` 코드 문자열(집계·이벤트 적재용).

    정본화≠집행: 이 enum의 실제 소비 지점(생성 파이프라인 실패 분류·검수 반려 코드 입력
    강제)은 후속 태스크 몫이다 — 자동 부여는 ARCH-23(QA 게이트 CI 강제)·D2 축, 검수 입력
    강제는 EOS-54(HIT 타이머·반려코드), 이벤트 적재는 EOS-54 ①. 여기서는 분류 계약만
    동결한다(`test_generation_failure_code.py`가 값집합을 동결).
    """

    F1 = "F1"
    """수식·파싱 실패 — LaTeX/AST 파싱 불가, 수식 문법 오류(기계 검출)."""

    F2 = "F2"
    """정답 불일치 — SymPy/수치 검증에서 정답·해설 모순(기계 검출)."""

    F3 = "F3"
    """풀이 논리 비약 — 인접 단계 비동치·근거 없는 도약(판단형 — F-Ⅲ 축)."""

    F4 = "F4"
    """성취기준 이탈 — 지정 성취기준 코드 범위 밖 내용."""

    F5 = "F5"
    """난이도 미스 — 요청 난이도와 실제 난이도의 불일치."""

    F6 = "F6"
    """오개념 오연결 — 예상 오답의 op-code/오개념 매핑 오류(판단형 — F-Ⅲ 축)."""

    F7 = "F7"
    """언어 수준 부적합 — 학교급 어휘·문장 수준 불일치(판단형 — F-Ⅲ 축)."""

    F8 = "F8"
    """힌트 정답 누설 — L1·L2 힌트에 최종 정답 포함(무관용 — KPI 누설률 0%)."""
