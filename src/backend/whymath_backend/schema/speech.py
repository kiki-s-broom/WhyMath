"""Schema 수식 음성화(Math-to-Speech) 선언적 명세 모델 (Pydantic) — 음성 슬라이스 S1.

설계 정본: `docs/architecture/05_interaction.md` §5 접근성("TTS 통합")·슬89 "표현≠의미".
"읽어주기"의 어려운 본질은 오디오 합성(클라 측)이 아니라 **LaTeX/수식구조 →
모호성 없는·학년 적합 한국어 낭독 문자열 변환**이다. 이 변환은 수학 의미 분해가 필요한
코어 로직이므로 L1–L4(독립 수학 코어)가 담당하고, 오디오 합성만 클라(L5)가 한다. 즉
`SpeechSpec`은 `Visualization`·`LearningScene`의 직계 형제 — "음성 = 코어 구조의 한 렌더 타깃".

주의: **클라 합성 경로는 현재 존재하지 않는다**(2026-08-11 실측) — `flutter_tts`가 Gradle
비호환으로 `src/mobile/pubspec.yaml`에서 제거됐다. 이 스키마는 서버 축 계약일 뿐이며,
소비처 재도입은 실기기 호환 재검증이 선행한다.

7계층 경계: 이 파일은 *데이터 계약*만 정의한다(레이어 import 0 — `visualization.py`·
`learning_scene` 스키마가 L레이어를 import하지 않는 선례). 변환 엔진은 L3(`l3/speech.py`),
사전·프로파일 *데이터*는 L4(`l4/speech/`), 혼합 콘텐츠·HTTP는 L5(`api/speech.py`).

컨벤션(`visualization.py`·`learning_scene` 답습):
  - `ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)`.
  - `UUID PK` → `uuid.UUID = Field(default_factory=uuid4)`.
  - 토큰은 `learning_scene`의 `kind` 판별 유니온(`Field(discriminator="kind")`) 패턴.
  - 불변식은 `@model_validator(mode="after")`.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ──────────────────────────────────────────────────────────────────────────
# 학년 낭독 프로파일 밴드 (초등~대학 — 같은 구조를 다르게 읽는 단일 파라미터)
# ──────────────────────────────────────────────────────────────────────────
class SpeechGradeBand(str, Enum):
    """수식 낭독 규칙 *학년 밴드* — 같은 LaTeX 구조를 학년에 맞게 다르게 읽는 프로파일 키.

    ⚠️ `CurriculumEntry`의 *개방형* `grade_band`(국가별 학년 문자열·ISO 확장·enums.py 주석에서
    *enum화 회피*를 명시)와는 **다른 축**이다. 이쪽은 한국어 낭독 규칙의 *닫힌 교수학 어휘*
    (초등/중등/고등/대학)로, "x²을 초등은 '엑스 곱하기 엑스', 중등+는 '엑스의 제곱'으로 읽는다"
    같은 *읽기 규칙 분기*의 단일 출처다. 그래서 `enums.py`(v1.0 DDL 미러)가 아니라 음성 도메인
    자족 모듈인 여기에 둔다(혼동·blast radius 최소화).

    값은 한글(한글 식별자 그대로 — `Persona`·`ConceptLevel` 선례). use_enum_values=True 직렬화
    시 한글 값 보존(예: grade_band="고등").
    """

    초등 = "초등"
    """초등 — 지수·근호 미도입. x²은 '엑스 곱하기 엑스'로 전개해 읽는다."""

    중등 = "중등"
    """중등 — 제곱·루트 도입. 적분·극한·시그마는 아직 미도입."""

    고등 = "고등"
    """고등 — MVP 페르소나 A(고3) 기준. 미적분·삼각·지수로그·확통 전 범위 낭독."""

    대학 = "대학"
    """대학 — 고등 + 선형대수·집합·논리·해석학 기호 확장(S3~S4에서 사전 충전)."""


# ──────────────────────────────────────────────────────────────────────────
# 학년 프로파일 (교수학 데이터의 *모델*만 여기·실제 값은 L4 `l4/speech/profiles.py`)
# ──────────────────────────────────────────────────────────────────────────
class GradeProfile(BaseModel):
    """학년별 낭독 규칙 프로파일 — "같은 구조를 다르게 읽는" 파라미터의 단일 계약.

    *모델(계약)*만 여기 두고 *값(교수학적 결정)*은 L4(`l4/speech/profiles.py::PROFILES`)가 보유한다.
    L3 변환 엔진은 이 프로파일을 **함수 인자로 주입**받는다(L3→L4 직접 import는 역방향 의존이라
    금지 — `generate_visualization_spec(recommended_styles=...)` DI 선례와 동일).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, frozen=True)

    grade_band: SpeechGradeBand = Field(..., description="이 프로파일이 적용되는 학년 밴드")
    power_style: Literal["square", "multiply"] = Field(
        default="square",
        description="x²을 읽는 방식 — 'square'(엑스의 제곱)·'multiply'(엑스 곱하기 엑스·초등)",
    )
    sqrt_label: str | None = Field(
        default="루트",
        description="제곱근 낭독 라벨 — None이면 그 학년에 근호 미도입(초등)",
    )
    fraction_order: Literal["denominator_first"] = Field(
        default="denominator_first",
        description="분수 읽기 순서 — 한국 표준 '분모 먼저'(2분의 1) 고정",
    )
    introduced_constructs: frozenset[str] = Field(
        default_factory=frozenset,
        description=(
            "이 학년에 도입된 구조 키 집합 — 미도입 구조를 만나면 엔진이 unresolved로 표시"
            "(예: 초등에 적분). 키: fraction/power/root/subscript/trig/log/integral/sum/"
            "limit/derivative/binom/abs/factorial"
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 낭독 토큰 (kind 판별 유니온 — learning_scene SceneElement 패턴)
# ──────────────────────────────────────────────────────────────────────────
class TextToken(BaseModel):
    """낭독 텍스트 음절 — TTS가 그대로 발음할 한글 문자열 한 조각."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["text"] = "text"
    text: str = Field(..., min_length=1, description="발음할 한글 음절(영문자·기호는 전개됨)")


class BreakToken(BaseModel):
    """청각 그룹핑용 멈춤 — 괄호·분수·적분 경계에서 잠깐 끊어 청취 가능성을 높인다(SSML break)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["break"] = "break"
    duration_ms: int = Field(..., gt=0, le=2000, description="멈춤 길이(ms·0 초과 2000 이하)")


class EmphasisToken(BaseModel):
    """강조 — 연산자 우선순위 등을 청각으로 드러낸다(SSML emphasis). plain_text엔 text만 기여."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["emphasis"] = "emphasis"
    text: str = Field(..., min_length=1, description="강조해 발음할 한글 음절")
    level: Literal["strong", "moderate", "reduced"] = Field(
        default="moderate", description="강조 세기(SSML emphasis level)"
    )


# kind로 판별하는 토큰 유니온 — 추가 필드 금지(extra="forbid")로 정답·원시 LaTeX 밀반입 차단.
SpeechToken = Annotated[
    TextToken | BreakToken | EmphasisToken,
    Field(discriminator="kind"),
]


def text_of(token: TextToken | BreakToken | EmphasisToken) -> str:
    """토큰의 발음 텍스트(break은 "") — plain_text 재구성·불변식 검증의 단일 출처."""
    return getattr(token, "text", "")


def _collapse_ws(s: str) -> str:
    """공백 정규화 — 연속 공백을 하나로, 양끝 trim(불변식 비교의 안정 기준)."""
    return " ".join(s.split())


# ──────────────────────────────────────────────────────────────────────────
# 핵심: SpeechSpec (선언적 낭독 명세 — 또 하나의 렌더 타깃)
# ──────────────────────────────────────────────────────────────────────────
class SpeechSpec(BaseModel):
    """단일 수식의 선언적 낭독 명세 — `Visualization`·`LearningScene`의 직계 형제.

    `plain_text`는 SSML 미지원 합성 엔진을 위한 폴백 낭독 문자열, `tokens`는
    운율(멈춤·강조)을 담은 토큰열, `ssml`은 (지원 엔진용) 조립 SSML이다. `unresolved_symbols`는
    사전에 없던 기호를 *조용히 넘기지 않고* 정직하게 노출하는 관측 필드(CLAUDE.md "환각 발견 시
    조용히 넘어가지 말고 로그").

    불변식(`@model_validator(mode="after")`):
      ① `source_latex` 비면 거부 — 읽을 원본이 없다(parse_check_latex 정직성 상속).
      ② `plain_text` 비면 거부 — 빈 낭독 금지.
      ③ 토큰을 이으면 `plain_text`와 정합 — 명세 내부 추적성(손으로 만든·라운드트립 명세 가드).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    speech_id: uuid.UUID = Field(default_factory=uuid4, description="낭독 명세 PK (UUID)")
    source_latex: str = Field(..., description="원본 LaTeX — 추적성·캐시 키")
    grade_band: SpeechGradeBand = Field(..., description="어느 학년 프로파일로 읽었는가")
    plain_text: str = Field(..., description="SSML 없는 폴백 낭독 문자열(비SSML 엔진용)")
    tokens: list[SpeechToken] = Field(
        default_factory=list, description="운율(멈춤·강조) 포함 토큰열(SSML 합성용)"
    )
    ssml: str | None = Field(default=None, description="조립 SSML(선택·플랫폼 지원 시)")
    unresolved_symbols: list[str] = Field(
        default_factory=list,
        description="사전에 없던 기호(정직성·환각 방지·관측) — 비어 있으면 전부 낭독됨",
    )

    @model_validator(mode="after")
    def _source_latex_nonempty(self) -> SpeechSpec:
        """① 원본 LaTeX가 비면 거부(읽을 것이 없음)."""
        if not self.source_latex.strip():
            raise ValueError("source_latex가 비어 있습니다 — 읽을 원본 수식이 없습니다.")
        return self

    @model_validator(mode="after")
    def _plain_text_nonempty(self) -> SpeechSpec:
        """② 낭독 문자열이 비면 거부(빈 낭독 금지)."""
        if not self.plain_text.strip():
            raise ValueError("plain_text가 비어 있습니다 — 빈 낭독은 허용하지 않습니다.")
        return self

    @model_validator(mode="after")
    def _tokens_reconstruct_plain(self) -> SpeechSpec:
        """③ 토큰을 이으면 plain_text와 정합해야 한다(공백 정규화 비교·추적성)."""
        joined = _collapse_ws(" ".join(text_of(t) for t in self.tokens))
        if joined != _collapse_ws(self.plain_text):
            raise ValueError(
                "tokens를 이은 텍스트가 plain_text와 다릅니다(추적성 위반): "
                f"tokens={joined!r} vs plain_text={_collapse_ws(self.plain_text)!r}"
            )
        return self


class DocumentSpeechSpec(BaseModel):
    """자연어+수식 혼합 콘텐츠(문항·풀이단계)의 낭독 명세 — 세그먼트 배열(S2 오케스트레이션 산출물).

    `problem_text`·`solution_path.steps[].content`는 "자연어 + LaTeX" 혼합이라, `$...$` 경계로
    세그먼트를 나눠 자연어는 그대로·수식만 `SpeechSpec`으로 변환해 잇는다(L5 `api/speech.py`).
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True, str_strip_whitespace=True)

    document_id: uuid.UUID = Field(default_factory=uuid4, description="문서 낭독 명세 PK (UUID)")
    grade_band: SpeechGradeBand = Field(..., description="어느 학년 프로파일로 읽었는가")
    plain_text: str = Field(..., description="세그먼트를 이은 전체 폴백 낭독 문자열")
    formula_specs: list[SpeechSpec] = Field(
        default_factory=list,
        description="수식 세그먼트별 SpeechSpec(자연어 세그먼트는 plain_text에만)",
    )

    @model_validator(mode="after")
    def _plain_text_nonempty(self) -> DocumentSpeechSpec:
        """낭독 문자열이 비면 거부(빈 낭독 금지)."""
        if not self.plain_text.strip():
            raise ValueError("plain_text가 비어 있습니다 — 빈 낭독은 허용하지 않습니다.")
        return self
