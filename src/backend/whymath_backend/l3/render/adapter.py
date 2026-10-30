"""교수법 렌더 어댑터 경계 — Protocol + 값객체 + 테스트용 스텁.

설계 정본: `docs/architecture/03c_content_strategy_cache.md` §2.2(어댑터 계약).

`l3/interfaces.py`(LLMProvider·CacheBackend Protocol + 인메모리 스텁 동거)와 같은 house style이다:
경계를 `typing.Protocol`로 선언하고, 구현체는 별 모듈(`adapters.py`)에, 테스트용 스텁은 이 파일에.

────────────────────────────────────────────────────────────────────────────
어댑터 불변식 — 왜 "개념 무관"이 핵심인가
────────────────────────────────────────────────────────────────────────────
어댑터는 `ConceptDSL`의 *필드*만 일반적으로 조작한다 — 특정 개념(일차방정식·미분·확률…)을 아는
코드를 넣지 않는다. SOCRATIC 어댑터 하나가 원자 백본 노드 전부(`docs/data/corpus_facts.md`의
`atom_graph.nodes`)에 작동해야, 저장 자산이 (개념 × 교수법)의 곱이 아니라 (중립 DSL + 어댑터
N개)의 합으로 남는다(조합폭발 방지). 이 불변식은
`tests/backend/l3/render/test_render_governance.py`가 소스 스캔으로 동결한다.

────────────────────────────────────────────────────────────────────────────
계층 경계 (import-linter: api→l6→l5→l4→l3→l2→l1→schema)
────────────────────────────────────────────────────────────────────────────
렌더는 **순수 렌더**다 — *어느* 전략을 쓸지 고르는 책임은 L4 Runtime Pedagogy Selector(04d §2)에
있고, L4가 L3를 임포트한다(하향·합법). 이 모듈이 L4를 임포트하면 역방향이라 `lint-imports`가
깨진다. 따라서 여기엔 선택 로직(학생 상태·금지 모드·Polya 게이트)이 **없다**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from whymath_backend.l3.pregenerate.models import ValidationSignal
from whymath_backend.l3.render.dsl import ConceptDSL
from whymath_backend.schema.enums import PedagogyStrategy

# 렌더 세그먼트 종류 — 화면 문자열이 아니라 *구조 태그*다(CLAUDE.md "표현≠의미").
# 클라(Flutter·웹·PDF)가 각자 이 종류를 보고 자기 방식으로 렌더한다.
SegmentKind = Literal[
    "heading",  # 제목·개념명
    "definition",  # 정의 제시
    "intuition",  # 직관·비유
    "example",  # 예시
    "question",  # 학생에게 던지는 발문
    "prompt",  # 지시·안내(문제 제시 등)
    "solution_step",  # 풀이 단계(완전예제)
    "reflection",  # 자기설명·메타인지 유도
]


@dataclass(frozen=True, slots=True)
class RenderSegment:
    """렌더 산출의 한 조각 — 종류(구조 태그) + 본문(렌더러-중립 LaTeX·평문).

    `kind`가 의미를, `content`가 재료를 담는다. 어떤 폰트·색·레이아웃으로 보일지는 클라 소관이다.
    """

    kind: SegmentKind
    content: str


@dataclass(frozen=True, slots=True)
class RenderContext:
    """렌더 1회의 부수 입력 — 치환 바인딩·로케일.

    `bindings`는 light render의 치환 자리(이름·숫자·상황)다. 비어 있어도 유효하다(대부분의 개념은
    DSL 본문만으로 렌더된다). 학생 식별자는 담지 않는다 — 렌더는 개인정보를 모른다.
    """

    bindings: dict[str, str] = field(default_factory=dict)
    locale: str = "ko-KR"


@dataclass(frozen=True, slots=True)
class RenderedUnit:
    """렌더 산출 1건 — 전략·출처 DSL·세그먼트 + 검증 신호.

    `validation_signal`이 **None이면 통과**, 비-None이면 실패다(`l3/pregenerate/models.py`의 규약을
    그대로 재사용 — 로그·trace·HTTP 경계로 `.reason`을 흘릴 수 있다). 실패분은 학생에게 노출하지
    않는다 — 상위 supply(CACHE-01)가 생성 경로로 폴백한다. 조용한 실패 금지.
    """

    strategy: PedagogyStrategy
    dsl_code: str
    segments: tuple[RenderSegment, ...]
    validation_signal: ValidationSignal | None = None

    @property
    def ok(self) -> bool:
        """검증 통과 여부 — 학생 노출 가능한 산출인지."""
        return self.validation_signal is None


@runtime_checkable
class PedagogyAdapter(Protocol):
    """교수법-중립 DSL → 전략별 학생 화면 렌더 경계.

    구현체는 **결정론·LLM=0**이다(같은 입력 → 같은 출력). 비용이 0이고 재현 가능해야 캐시 자산으로
    쓸 수 있다. 문장 다양화가 필요하면 상위가 별도 opt-in 후처리로 얹는다(이 경계 밖).
    """

    @property
    def strategy(self) -> PedagogyStrategy:
        """이 어댑터가 담당하는 전략(레지스트리 키와 일치해야 한다)."""
        ...

    def can_render(self, dsl: ConceptDSL) -> bool:
        """이 DSL을 렌더할 재료가 충분한지 — 부족하면 False(상위가 생성 경로로 폴백).

        예: PROBLEM_BASED는 평가 재료(assessment)가 있어야 문제를 앞세울 수 있다.
        """
        ...

    def render(self, dsl: ConceptDSL, ctx: RenderContext) -> RenderedUnit:
        """DSL을 전략별 세그먼트 열로 렌더한다(결정론).

        검증 실패(수치 봉인 위반·정답 검증 실패)는 예외를 던지지 않고 `RenderedUnit.
        validation_signal`에 담아 돌려준다 — 상위가 폴백을 결정한다(조용한 실패도, 강제 중단도
        아님).
        """
        ...


class NullAdapter:
    """테스트용 스텁 어댑터 — 개념명만 제목으로 내는 최소 구현(house style: 스텁 동거).

    Protocol 준수 여부·레지스트리 배선을 라이브 구현 없이 검사하기 위한 것이다.
    """

    def __init__(self, strategy: PedagogyStrategy = PedagogyStrategy.DIRECT) -> None:
        self._strategy = strategy

    @property
    def strategy(self) -> PedagogyStrategy:
        return self._strategy

    def can_render(self, dsl: ConceptDSL) -> bool:
        return True

    def render(self, dsl: ConceptDSL, ctx: RenderContext) -> RenderedUnit:
        return RenderedUnit(
            strategy=self._strategy,
            dsl_code=dsl.code,
            segments=(RenderSegment(kind="heading", content=dsl.name),),
        )


__all__ = [
    "NullAdapter",
    "PedagogyAdapter",
    "RenderContext",
    "RenderSegment",
    "RenderedUnit",
    "SegmentKind",
]
