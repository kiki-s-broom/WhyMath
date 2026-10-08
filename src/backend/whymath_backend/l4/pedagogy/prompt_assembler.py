"""교수법 팩 4계층 시스템 프롬프트 조립기 — 순수 함수(LLM·IO·전역 상태 0).

지식 유형별 소크라테스 발문(`PedagogyPack.socratic_prompt`)을 기존 역할 규칙(`_BASE_SYSTEM`) 위에
얹어 `PedagogyDecision.system`을 조립한다. 4계층을 `\\n\\n`로 잇는다:

  1. **base_system** — 기존 Polya 역할·5원칙·금기(`l4/polya/prompts.py::_BASE_SYSTEM`). 항상 맨 앞.
  2. **팩 소크라테스 발문** — `pack.socratic_prompt`의 `{domain_example}` 자리표시자를 치환한 유형별
     발문(개념형=예/비예 대조, 절차형=완전예제→페이딩 등). 유형 불변 발문에 소단원 예제만 주입한다.
  3. **오개념 계층**(반응적·v1 최소) — 이미 활성인 오개념 *가설*이 주입됐을 때만 렌더(caller가
     reactive retrieval로 표면화한 가설을 넘긴다 — 초기 preload 아님). 없으면 빈 문자열(계층 생략).
  4. **학습자 상태 계층**(v1 최소 + PED-05 개인화 슬롯) — 숙달 수준 라벨·학년(`grade`)·성취기준
     (`standard_code`) 중 있는 것만 골라 난이도·도움량 조절 힌트를 렌더(전부 없으면 빈 문자열).
     PII 가드: 이 계층은 grade(학년 정수)·standard_code(성취기준 코드 문자열)만 받는다 — 학교명·
     지역·학생 이름·목표 점수/등급/대학은 이 함수 시그니처에 자리 자체가 없다(구조적 차단).

**OFF/무팩 보장**: `pack is None`이면 `base_system`을 *바이트 동일*로 그대로 반환한다(치환·조립·
join 없음). 이것이 플래그 OFF·팩 미주입 경로의 회귀 0 계약이다 — 호출자(`PolyaCoach.decide`)는
플래그 OFF이거나 팩 미주입이면 조립기를 아예 호출하지 않지만, 호출되더라도 이 계약이 이중
안전망이다.

**계층 위생**: `schema`(팩 계약)에 더해 l4 형제 타입(`MisconceptionHypothesis`·`MasteryLevel`)만
참조한다(l4→l4는 동일 계층·import-linter 무관, l4→schema는 허용). l1·config에는 의존하지 않는다.

**전략 카드 계층(PED-23 회수 — 정본 `docs/architecture/04g_pedagogy_strategy_catalog.md` §3.2)**:
선택된 교수전략의 카탈로그 카드(name_ko·description·research_basis **요약 1줄만** — attention
절약)를 기존 프롬프트 *위에 덧붙이는* 독립 계층이다. 4계층 조립(`build_system_prompt`)과
직교하도록 합성 함수(`attach_strategy_card`)로 분리했다 — 실측된 소비 지점은
`content_supply.supply()`의 생성 폴백(system 문자열)이고, 그 지점은 4계층 조립을 쓰지 않기
때문이다(코치 경로가 decide() 전략을 소비하게 되는 후속에서 `attach_strategy_card(
build_system_prompt(...), card)` 합성으로 같은 계층을 재사용한다). **무카드 무변경 계약**:
card None이면 입력 문자열을 바이트 동일로 돌려준다(`pack is None → base_system` 선례 미러).
카드 *조회*(strategy_registry·플래그)는 호출자 몫 — 이 모듈은 순수 렌더만 한다.

**후속(deferred)**: 오개념·학습자 계층의 *풍부한* 렌더(개입 발문 본문·전체 IRT/BKT 상태 요약)와
problem→k_type 해석 seam은 후속 슬라이스다 — v1은 유형 발문 계층(2)까지가 핵심이고 3·4는 최소 훅.
"""

from __future__ import annotations

from collections.abc import Sequence

from whymath_backend.l4.lthc.models import MasteryLevel
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.schema.pedagogy_pack import PedagogyPack
from whymath_backend.schema.pedagogy_strategy import PedagogyStrategyCard

# 팩 발문의 자리표시자 — schema 불변식(a)가 socratic_prompt에 필수로 요구하는 토큰.
# schema의 동명 private 상수(`_DOMAIN_EXAMPLE_PLACEHOLDER`)를 import하지 않고 로컬 재정의한다
# (private 심볼 결합 회피 — 값은 계약상 고정 "{domain_example}").
_DOMAIN_EXAMPLE_PLACEHOLDER = "{domain_example}"

# domain_example 미지정 시 치환할 중립 기본값 — 리터럴 "{domain_example}"를 발문에 남기면 LLM이
# 중괄호 토큰을 문면 그대로 읽어 발문이 어색해진다. "지금 다루는 문제"는 지식 유형 불변이면서
# 문법적으로 자연스러운 중립 대체다(특정 소단원 예제 해석 seam이 오기 전 v1 폴백 — 후속에서 실제
# domain_example 주입으로 대체). caller가 domain_example을 주면 이 폴백은 쓰이지 않는다.
_NEUTRAL_DOMAIN_EXAMPLE = "지금 다루는 문제"


def _render_socratic_layer(pack: PedagogyPack, domain_example: str | None) -> str:
    """계층 2 — 팩 소크라테스 발문의 `{domain_example}` 치환(str.replace·format 미사용).

    `str.format`은 발문에 다른 중괄호 토큰이 있으면 깨지므로 `str.replace`로 *그 자리표시자만*
    치환한다(안전·의도 국소화). domain_example None이면 중립 기본값으로 치환한다(리터럴 브레이스
    잔류 방지 — 모듈 docstring 참조).
    """
    example = domain_example if domain_example is not None else _NEUTRAL_DOMAIN_EXAMPLE
    return pack.socratic_prompt.replace(_DOMAIN_EXAMPLE_PLACEHOLDER, example)


def render_misconceptions(misconceptions: Sequence[MisconceptionHypothesis] | None) -> str:
    """계층 3(반응적·v1 최소) — 활성 오개념 가설 힌트 블록. 없으면 "".

    **반응적 계약**: caller가 넘기는 것은 이미 표면화된(reactive retrieval된) *활성 가설*이지 전체
    오개념 카탈로그의 preload가 아니다(CLAUDE.md "오개념 초기 context preload 금지"). 이 블록은
    오개념 *내용*(canonical_statement)을 주입하지 않고, 비PII 식별자(`misconception_id`)와 신뢰만
    실어 "학생 발화에서 단서가 보일 때만 되짚어 스스로 확인하게 하라"는 반응적 지시를 준다 —
    오개념을 먼저 제시하지 않는다.

    v1은 식별자·신뢰의 최소 힌트만 렌더한다(개입 발문 본문 렌더는 후속 — 모듈 docstring deferred).
    """
    if not misconceptions:
        return ""
    lines = [
        "[의심 오개념 가설 — 반응적 확인용]",
        "학생 발화에서 아래 오개념의 단서가 보일 때만 그 지점을 되짚어 스스로 확인하게 하라. "
        "오개념 내용을 먼저 제시하지 마라.",
    ]
    for hyp in misconceptions:
        lines.append(f"- {hyp.misconception_id} (신뢰 {hyp.confidence:.2f})")
    return "\n".join(lines)


def render_student_state(
    student_state: MasteryLevel | None,
    *,
    grade: int | None = None,
    standard_code: str | None = None,
) -> str:
    """계층 4(v1 최소 + PED-05) — 학습자 숙달 수준·학년·성취기준 힌트 블록. 전부 없으면 "".

    숙달 수준(`MasteryLevel` Literal: 초보·발전 중·숙달)·학년(`grade`)·성취기준(`standard_code`)
    중 있는 것만 골라 발문의 난이도·도움량을 조절하라는 지시를 준다(student-facing 미노출 — 결정
    내부 힌트). 셋 다 선택적이라 `student_state`가 없어도 `grade`·`standard_code`만으로 블록을
    렌더할 수 있다(PED-05 개인화 슬롯 착지 — L4 조립 좌석은 이미 있었고 학년·성취기준 인자만
    새로 열었다). 전체 IRT θ·BKT 상태 요약·오개념 *내용*은 여전히 후속(모듈 docstring deferred).

    **PII 가드**: 이 함수는 grade(학년 정수)·standard_code(성취기준 코드 문자열) 외 어떤 학생
    식별 정보도 받지 않는다 — 학교명·지역·이름·목표 점수/등급/대학은 시그니처에 자리가 없어
    구조적으로 노출될 수 없다.
    """
    parts: list[str] = []
    if student_state is not None:
        parts.append(f"학습자 숙달 수준: {student_state}")
    if grade is not None:
        parts.append(f"학년: {grade}")
    if standard_code is not None:
        parts.append(f"성취기준: {standard_code}")
    if not parts:
        return ""
    return (
        f"[{' / '.join(parts)}] "
        "이 정보에 맞춰 발문의 난이도와 도움의 양을 조절하라(학생에게 직접 노출하지 마라)."
    )


def render_strategy_card(card: PedagogyStrategyCard | None) -> str:
    """전략 카드 계층(PED-23 회수) — 선택된 교수전략의 서술 1블록. 없으면 "".

    카탈로그 9필드 중 **name_ko·description·research_basis[0]만** 주입한다(04g §3.2 소비처
    지정표 — "요약 1줄만 주입, attention 절약". usage_notes는 사람 서술 전용·기계 배선 금지라
    여기서도 넣지 않는다). `research_basis`는 schema 불변식 (b)가 최소 1건을 보장하므로 첫
    항목 접근이 안전하다. 학생-대면 미노출 지시를 동봉한다 — 내부 교수학 메타(전략명·연구
    인용)가 미성년 학생 화면으로 새면 안 된다(`render_student_state` 미노출 지시 선례).
    """
    if card is None:
        return ""
    return (
        f"[교수전략: {card.name_ko}] {card.description} "
        f"(근거: {card.research_basis[0]}) "
        "이 전략의 취지에 맞게 응답을 구성하라(전략명·연구 근거를 학생에게 직접 노출하지 마라)."
    )


def attach_strategy_card(system: str, card: PedagogyStrategyCard | None) -> str:
    """system 프롬프트에 전략 카드 계층을 덧붙인다 — **무카드면 바이트 동일**(순수 함수).

    PED-23 옵트인 무변경 계약의 단일 지점: `card is None`이면 입력 `system`을 그대로 반환한다
    (`build_system_prompt`의 `pack is None → base_system` 선례 미러 — 테스트가 바이트 동일로
    봉인). 카드가 있으면 `\\n\\n`로 이어 붙이고, system이 비면 카드 블록만 반환한다(선행 빈
    구분자 잔류 방지). 플래그 판정·카탈로그 조회는 호출자(`content_supply.supply`) 몫이다.
    """
    block = render_strategy_card(card)
    if not block:
        return system
    if not system:
        return block
    return f"{system}\n\n{block}"


def build_system_prompt(
    *,
    base_system: str,
    pack: PedagogyPack | None,
    domain_example: str | None = None,
    misconceptions: Sequence[MisconceptionHypothesis] | None = None,
    student_state: MasteryLevel | None = None,
    grade: int | None = None,
    standard_code: str | None = None,
) -> str:
    """4계층 시스템 프롬프트 조립 — 순수 함수. `pack is None`이면 `base_system` 바이트 동일 반환.

    계층 순서·규칙은 모듈 docstring 참조. 계층 3·4는 입력이 비면 빈 문자열이라 join에서 생략된다
    (빈 계층이 `\\n\\n`만 남기지 않게 필터). **pack None 경로는 조립 자체를 건너뛰어 base_system을
    무변경 반환**한다 — 이것이 OFF/무팩 회귀 0 계약의 단일 지점이다(테스트가 바이트 동일로 봉인).

    `grade`·`standard_code`(PED-05)는 계층 4에 그대로 thread된다 — 둘 다 기본 None이라 미전달
    호출자는 회귀 0.
    """
    # OFF/무팩 보장 — 조립 없이 base_system 그대로(바이트 동일). 단일 회귀 0 지점.
    if pack is None:
        return base_system
    layers = [
        base_system,
        _render_socratic_layer(pack, domain_example),
    ]
    misconception_block = render_misconceptions(misconceptions)
    if misconception_block:
        layers.append(misconception_block)
    student_block = render_student_state(student_state, grade=grade, standard_code=standard_code)
    if student_block:
        layers.append(student_block)
    return "\n\n".join(layers)


__all__ = [
    "attach_strategy_card",
    "build_system_prompt",
    "render_misconceptions",
    "render_strategy_card",
    "render_student_state",
]
