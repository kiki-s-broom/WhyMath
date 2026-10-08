"""실행용 교수법 선택기 — 학생 상태 → `PedagogyStrategy` + 교수학 게이트(2축).

설계 정본: `docs/architecture/04d_adaptive_pedagogy_engine.md` §2(Runtime Pedagogy Selector).

2단계 교수법 中 **②실행용**을 담당한다. ①설계용(DSL 생성 시 `pedagogy_pack`)과 달리, 이 모듈은
*학생이
공부하는 순간* 어떤 방식으로 보여줄지를 매번 다시 고른다 — 같은 개념이라도 계산 실수가 잦은 학생과
개념
이해가 부족한 학생에게 다른 방식이 가야 하기 때문이다. 고른 전략은 L3 렌더 어댑터(`l3/render/`)가
실행한다.

────────────────────────────────────────────────────────────────────────────
책임 분리 — 선택(효과) ≤ 게이트(허용)
────────────────────────────────────────────────────────────────────────────
`select()`는 "무엇이 이 학생에게 효과적인가"만 답한다. `gate()`는 "그것이 교수학적으로 허용되는가"를
판정해 위반 시 강등한다. **효과가 허용을 이길 수 없다** — 의사결정 우선순위상 비용·효율(#6)이
교수학적
정확성(#3)을 역전하지 못한다는 원칙의 기계적 실행이다(CLAUDE.md).

────────────────────────────────────────────────────────────────────────────
완전예제 2축 게이트 — 왜 두 축이 모두 필요한가
────────────────────────────────────────────────────────────────────────────
`WORKED_EXAMPLE`(완전예제)은 두 얼굴을 가진다. **초기 교수**로서의 완전예제는 Sweller의 worked
example
effect가 뒷받침하는 정당한 방식이고, 실제로 PROCEDURE 팩은 이를 *의도*한다(`fading_schedule`
`{worked:2, completion:2, solo:3}` — 완전예제 2회로 흐름을 보여준 뒤 점차 걷어낸다). 반면 **막힌
학생에게
던지는 완전예제**는 "막혔을 때 바로 정답 제공"이며 CLAUDE.md 절대 금기다.

두 상황을 가르는 것이 이 게이트의 핵심이다:

  축① **팩 금지(선행 차단)** — 팩이 `WORKED_EXAMPLE_FIRST`를 금지하면(실제 코퍼스에서는 CONCEPT
  하나)
       시도 전 단계의 완전예제를 막는다. 금지 모드 이름의 "FIRST"(선행)가 정확히 이 축이다.
       PROCEDURE는
       이를 금지하지 않으므로 페이딩 진입이 보존된다.
  축② **막힘 시 에스컬레이션** — 팩과 무관하게, 학생이 막힌 상황에서는 힌트 단계가 충분히 올라간
       뒤에만 완전예제를 허용한다. 기존 `hint_deferral.decide_hint_level`이 이미 "좌절·답요구·5회+
       막힘"을
       점진 상승으로 다루므로 새 카운터를 만들지 않고 그 산출(`hint_level`)을 그대로 읽는다.

**팩이 없어도 축②는 적용된다**(fail-safe) — 팩 조회 실패가 냉담 제공을 열어주면 안 된다.

────────────────────────────────────────────────────────────────────────────
계층 경계
────────────────────────────────────────────────────────────────────────────
L4 → L3(`l3/render/registry`) 하향 임포트는 합법이다(`api→l6→l5→l4→l3→l2→l1→schema`). 반대로 L3 렌더
어댑터는 이 모듈을 임포트하지 않는다 — 렌더는 "선택"을 모르고 "실행"만 한다(REND-01 인계 사항).

DB 세션에 의존하지 않는 순수 함수다(`pack_registry`가 DB-free인 것과 동형). 신호 조립(ORM 조회)은
호출자(API·하네스) 책임이다.

────────────────────────────────────────────────────────────────────────────
카탈로그 후보 필터 (PED-23 회수 — 정본 `docs/architecture/04g_pedagogy_strategy_catalog.md` §4)
────────────────────────────────────────────────────────────────────────────
교수전략 카탈로그(PED-05·PED-22 회수 — `strategy_registry`)의 적합성 필드를 `select()`가
**후보 필터**로 소비한다. 규칙표 v1(R1~R5)은 유지하고, 필터는 그 앞에서 후보 집합만 좁힌다:

    candidates = registered_strategies()                        # 렌더 가능 전략(기존 거버넌스)
    candidates = narrow(candidates, grade_band, difficulty, k_type)  # 카탈로그 적합성 — 좁힘만
    strategy   = rule_table(signals, candidates)                # R1~R5 (기존 우선순위 그대로)

불변식(04g §4):
  ① **필터는 좁힘만 한다** — 좁힌 결과가 공집합이거나 규칙표가 좁힌 후보를 소진하면 필터를
     무시하고 규칙표 *원판정*으로 폴백한다(신호 부재·카탈로그 공백이 선택 불능을 만들면 안 됨).
     폴백은 reason_code(`REASON_CATALOG_FILTER_*`)를 구조화 로그로 남긴다(조용한 실패 아님).
  ② **카탈로그는 select 전용 — `gate()` 입력 금지.** 게이트가 카탈로그(YAML 데이터)를 읽기
     시작하면 코퍼스 편집만으로 "효과 ≤ 허용"이 우회된다 — 부재를 테스트가 동결한다
     (`tests/backend/l4/test_catalog_consumption.py`).
  ③ **`select()` 출력 ⊆ `registered_strategies()`** — 기존 거버넌스 유지(필터는 부분집합만
     만들고, 폴백 원판정도 등록 전략에서 나온다).

필터는 `pedagogy_catalog_filter_enabled` 플래그 옵트인(기본 OFF·킬스위치)이다 — OFF면 카탈로그
미조회·규칙표 원판정 그대로(기존 경로와 비트동일). None 신호는 해당 필터 축을 조용히 건너뛴다
(필수화 금지).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from whymath_backend.config import get_settings
from whymath_backend.l3.render.registry import registered_strategies
from whymath_backend.l4.hint_deferral import HintLevel
from whymath_backend.l4.lthc.models import MasteryLevel
from whymath_backend.l4.models import PolyaStage
from whymath_backend.l4.pedagogy.pack_registry import get_pack
from whymath_backend.l4.pedagogy.strategy_registry import get_pedagogy_strategies
from whymath_backend.schema.enums import PedagogyStrategy
from whymath_backend.schema.pedagogy_pack import PedagogyPack
from whymath_backend.schema.pedagogy_strategy import PedagogyStrategyCard

logger = logging.getLogger("whymath.l4.runtime_selector")

# ──────────────────────────────────────────────────────────────────────────
# 튜닝 상수 — KPI 튜닝 대상이며 측정된 최적값이 아니다(socratic/select.py 관례).
# ──────────────────────────────────────────────────────────────────────────
# 시도 전 단계 — 여기서 완전예제를 주면 "선행"(WORKED_EXAMPLE_FIRST)이 된다.
# EXECUTE/REVIEW는 학생이 이미 손을 댄 뒤라 선행이 아니다.
_PRE_ATTEMPT_STAGES: frozenset[PolyaStage] = frozenset({PolyaStage.UNDERSTAND, PolyaStage.PLAN})

# 막힘 누적 임계 — `hint_deferral._STUCK_TURN_THRESHOLD`와 같은 축(스펙 "5회+ 막힘").
_STUCK_TURN_THRESHOLD = 5

# 완전예제가 "벌어진" 것으로 보는 최소 힌트 단계. 3 = 부분 단계 시연(`hint_deferral.REVEALS`).
# 즉 방향(1)·흐름(2)을 거친 뒤에만 완전예제가 열린다.
_EARNED_HINT_LEVEL = 3

# 강등 대상 — 말하기 대신 묻기. 어댑터가 항상 등록돼 있어 폴백이 실패하지 않는다.
_FALLBACK_STRATEGY = PedagogyStrategy.SOCRATIC

# 금지 모드 토큰 — `mode_guard`/`FORBIDDEN_MODE_VOCAB`와 같은 어휘를 쓴다(사후 가드의 사전 형제).
_MODE_WORKED_EXAMPLE_FIRST = "WORKED_EXAMPLE_FIRST"

# reason_code — 차단 사유(호출자 로깅·KPI 집계용).
REASON_PACK_FORBIDS_WORKED_FIRST = _MODE_WORKED_EXAMPLE_FIRST
"""팩이 완전예제 선행을 금지하는데 시도 전 단계에서 요청됨(축①)."""

REASON_HINT_NOT_ESCALATED = "HINT_NOT_ESCALATED"
"""막힌 학생에게 힌트 에스컬레이션 없이 완전예제가 요청됨(축② — 냉담 정답 제공)."""

# reason_code — 카탈로그 필터 폴백 사유(04g §4 불변식 ① "조용한 실패 아님" — 구조화 로그 필드).
REASON_CATALOG_FILTER_EMPTY = "CATALOG_FILTER_EMPTY"
"""카탈로그 적합성 필터가 후보를 공집합으로 좁힘 — 필터 무시·규칙표 원판정 폴백."""

REASON_CATALOG_FILTER_EXHAUSTED = "CATALOG_FILTER_EXHAUSTED"
"""좁힌 후보는 비어 있지 않으나 규칙표(R1~R5)가 후보를 소진 — 규칙표 원판정 폴백."""

REASON_CATALOG_UNAVAILABLE = "CATALOG_UNAVAILABLE"
"""카탈로그 적재 실패(코퍼스 손상 등) — 필터 생략·규칙표 원판정(예외 타입명 로그 동반)."""


# ──────────────────────────────────────────────────────────────────────────
# 학년 → 학교급 밴드 (grade_band 신호의 순수 변환 — 생산자 `UserProfile.grade`)
# ──────────────────────────────────────────────────────────────────────────
# K-12 사다리 구간 경계 — `schema/user.py`의 grade 계약(10=고1·11=고2·12=고3·13=N수1·14=N수2,
# ge=10 le=14) 실측에서 역산한 동일 사다리(10=고1 ⇒ 7~9=중학·1~6=초등)다.
_GRADE_ELEMENTARY_MAX = 6
_GRADE_MIDDLE_MAX = 9
_GRADE_NSU_MAX = 14


def grade_to_band(grade: int | None) -> str | None:
    """학년 정수 → 학교급 밴드(`GRADE_BAND_VOCAB` 부분집합) 순수 변환. 미상은 None.

    정본: 04g §4(카탈로그 후보 필터의 grade 신호 — "생산자 먼저" 원칙). 생산자는
    `UserProfile.grade`(`db/models/user.py` — int|None)이며, 값 의미는 `schema/user.py` 계약
    실측: **10/11/12=고1~고3·13/14=N수1·2(ge=10 le=14)**. 같은 사다리를 아래로 연장해
    1~6=초등·7~9=중학으로 해석한다(현 생산자 domain 밖이나, 초등/중학 확장 시 변환 재작성이
    필요 없도록 총함수로 둔다).

      - None → None (신호 부재 — 필터 축 조용히 스킵)
      - 1~6 → "초등" / 7~9 → "중학" / 10~12 → "고등"
      - 13~14 → "고등" (N수는 고교 교육과정·수능 대비 재학습 — 대학 과정이 아니다)
      - 그 외(0 이하·15 이상) → None (미정의 값 — 추측 매핑 금지·축 스킵)

    ⚠️ 정직한 공백: "대학" 밴드는 이 변환이 **영원히 내지 않는다** — grade 정수 계약에 대학
    인코딩이 없다(생산자 부재). 카탈로그 쪽 target_grade_bands의 "대학"은 유효하되, 신호 쪽
    생산자가 생기기 전까지 그 축으로는 좁혀지지 않는다.
    """
    if grade is None:
        return None
    if grade < 1 or grade > _GRADE_NSU_MAX:
        return None
    if grade <= _GRADE_ELEMENTARY_MAX:
        return "초등"
    if grade <= _GRADE_MIDDLE_MAX:
        return "중학"
    return "고등"


@dataclass(frozen=True, slots=True)
class StudentSignals:
    """선택기 입력 — **실재하는(생산자가 있는) 신호만** 담는다.

    04d §2는 8개 입력(수준·오답유형·학습속도·집중도·학습시간·선호·성취도·직전결과)을 지정했으나,
    2026-07 실측 결과 그중 셋은 코드에 존재하지 않거나 생산자가 없다:

      - **집중도**(`LearningSession.focus_score`)·**학습시간**(세션 duration) — 컬럼은 있으나
      *쓰는 코드가
        없어 항상 NULL*이다.
      - **선호**(`MasteryState.preferred_solution_style`) — `MasteryState` 자체가 문서 스케치이며
      코드에
        존재하지 않는다.

    따라서 그 셋은 **필드로 만들지 않는다**. 항상 None인 필드를 두면 "읽고는 있다"는 착시를 주지만
    실제
    판단에는 아무 기여도 하지 못하기 때문이다(가짜 통과 금지). 해당 축이 필요해지면 *생산자를
    먼저* 만들고
    그때 필드를 연다.

    04d가 `StudentState` 값객체를 명시했으므로 dataclass로 묶는다. 형제 L4 결정 함수들
    (`recommend_coaching`·`PolyaCoach.decide`)은 flat kwargs 관례를 쓰지만, 여기서는 신호가 10개에
    달하고
    "무엇이 실재하고 무엇이 부재한가"를 한자리에 문서화하는 값이 더 커서 값객체를 택했다.
    """

    # ── 수준·성취도 (L2 BKT/IRT) ────────────────────────────────
    mastery_level: MasteryLevel | None = None
    """`lthc.adapt.mastery_to_level` 산출('초보'/'발전 중'/'숙달')."""
    bkt_mastery: float | None = None
    """BKT P(L) 0~1 — `l2.mastery_tracking.get_current_mastery`."""
    irt_theta: float | None = None
    """IRT θ — `l2.ability_tracking.get_current_theta`."""

    # ── 진행 상태 (세션 — 클라이언트가 왕복시키는 값) ──────────────
    polya_stage: PolyaStage = PolyaStage.UNDERSTAND
    """현재 Polya 단계. 시도 전/후를 가르는 축(게이트 축①)."""
    turn_count: int = 0
    """현재 단계 내 턴 수 — 막힘 누적 신호."""
    hint_level: HintLevel | None = None
    """`hint_deferral.decide_hint_level` 산출(1~4). 게이트 축②의 판정 재료."""

    # ── 직전 시도 결과 (L2 `problem_attempt`) ────────────────────
    last_attempt_correct: bool | None = None
    """직전 문제 정답 여부(`ProblemAttempt.is_correct`)."""
    time_vs_expected: float | None = None
    """소요시간/기대시간 비(1.0=평균·2.0=2배 느림). 학습 속도 대용."""
    used_hint: bool | None = None
    """직전 시도에서 힌트를 썼는지."""

    # ── 오개념 (L4 반응형 진단) ──────────────────────────────────
    misconception_ids: tuple[str, ...] = field(default=())
    """활성 오개념 가설 id(`l4.misconception.diagnose`/`hypothesis_store`). 비면 미검출."""

    # ── 학적 (L5 프로필 — PED-23 회수 카탈로그 필터 축) ─────────────
    grade_band: str | None = None
    """학교급 밴드('초등'/'중학'/'고등'/'대학' — GRADE_BAND_VOCAB). 생산자는
    `UserProfile.grade` → `grade_to_band()`(`api/study.py::_build_signals` 배선 — 04d §2.1
    "생산자 먼저" 충족). None이면 카탈로그 필터의 학년 축을 조용히 건너뛴다."""

    @property
    def is_stuck(self) -> bool:
        """막힘 상태인지 — 힌트가 이미 올라갔거나 같은 단계에서 오래 맴돌면 막힌 것으로 본다.

        `hint_level`은 좌절·답요구·5회+ 막힘을 이미 종합한 값이라 2 이상이면 학생이 도움을
        구했다는 뜻이다
        (1=방향 제시는 기본값이므로 막힘 신호가 아니다).
        """
        if self.hint_level is not None and self.hint_level >= 2:
            return True
        return self.turn_count >= _STUCK_TURN_THRESHOLD

    @property
    def hint_escalated(self) -> bool:
        """완전예제를 열어도 되는 만큼 힌트가 올라갔는지(축② 판정)."""
        return self.hint_level is not None and self.hint_level >= _EARNED_HINT_LEVEL


@dataclass(frozen=True, slots=True)
class GateResult:
    """게이트 판정 — 예외가 아니라 *구조화 결과*로 돌려준다(`match_gate` 관례).

    `strategy`는 **최종 사용 가능한** 전략이다(차단 시 강등된 값). 호출자는 이 값을 그대로 렌더에
    넘기면
    되며, `allowed`/`reason_code`로 무슨 일이 있었는지 로깅·집계할 수 있다. 조용한 실패가 아니다.
    """

    strategy: PedagogyStrategy
    allowed: bool
    reason_code: str | None = None
    requested: PedagogyStrategy | None = None
    """게이트 이전에 요청됐던 전략(강등 시에만 채워짐 — 감사용)."""


def narrow_candidates(
    candidates: frozenset[PedagogyStrategy],
    cards: Mapping[str, PedagogyStrategyCard],
    *,
    grade_band: str | None = None,
    difficulty: str | None = None,
    k_type: str | None = None,
) -> frozenset[PedagogyStrategy]:
    """카탈로그 적합성으로 후보 집합을 **좁히기만** 하는 순수 함수(04g §4의 `narrow`).

    축별 규칙(모두 AND):
      - 축 신호가 None이면 그 축은 검사하지 않는다(조용히 스킵 — 필수화 금지).
      - 카드가 없는 전략은 **제외하지 않는다**(적합성 미상은 배제 근거가 아니다 — 카탈로그
        공백이 선택 불능을 만들면 안 됨). enum 1:1 완비는 거버넌스 테스트가 동결하므로 실
        코퍼스에서는 도달하지 않는 방어 분기다.
      - 카드가 있으면 `target_grade_bands`/`difficulty_range`/`target_k_types` 멤버십 검사.

    반환은 항상 `candidates`의 부분집합이다(좁힘만 — 불변식 ①의 절반. 공집합 폴백은 호출자
    `select()` 몫). `cards`를 인자로 받는 이유: 레지스트리 조회를 분리해 이 함수를 100% 순수로
    유지하고, 합성 카드로 축별 변별력을 테스트하기 위해서다.
    """
    if grade_band is None and difficulty is None and k_type is None:
        return candidates
    kept: set[PedagogyStrategy] = set()
    for strategy in candidates:
        card = cards.get(strategy.value)
        if card is None:
            kept.add(strategy)
            continue
        if grade_band is not None and grade_band not in card.target_grade_bands:
            continue
        if difficulty is not None and difficulty not in card.difficulty_range:
            continue
        if k_type is not None and k_type not in card.target_k_types:
            continue
        kept.add(strategy)
    return frozenset(kept)


def _rule_table(
    signals: StudentSignals, candidates: frozenset[PedagogyStrategy]
) -> PedagogyStrategy | None:
    """규칙표 v1(R1~R5) — 후보 제약판. 조건이 성립해도 전략이 후보 밖이면 다음 규칙으로.

    `candidates`가 전체 등록 전략이면 기존 규칙표와 판정이 동일하다(필터 OFF 경로의 비트동일
    근거). 후보가 좁혀져 있으면 "이 학생에게 필요한 것" 중 카탈로그가 적합하다고 서술한 첫
    전략이 이긴다 — 우선순위 순서 자체는 그대로다(04g §4 "R1~R5 우선순위 그대로").

    R2 정밀화(04g §4 v2)는 **정직한 공백으로 보류**한다: 설계는 오개념 가설의 `error_type`을
    카탈로그 `suitable_error_types`와 대조하라고 지시하나, 2026-07-29 실측 결과 runtime의
    `misconception_ids`(kebab id — `l4/misconception/catalog.py` 34종)에는 `error_type` 필드
    자체가 없고, error_type은 DB `misconception_catalog`(L1 코퍼스 839+·M-코드)에만 있어
    AsyncSession 없이는 조회 불가다(이 모듈은 DB-free 순수 함수 — 억지 배선 금지). kebab↔M코드
    crosslink도 검수 파이프라인이지 프로덕션 매핑 좌석이 아니다. 대조 불가면 기존 R2 그대로가
    설계의 지시이므로, 순수 경로 생산자가 생길 때까지 R2는 v1 그대로 둔다.
    """
    # R1. 막힘 — 완전예제 제안(게이트가 최종 판정).
    if signals.is_stuck and PedagogyStrategy.WORKED_EXAMPLE in candidates:
        return PedagogyStrategy.WORKED_EXAMPLE

    # R2. 오개념 가설 — 비유로 직관 재구성(정밀화 보류 — docstring).
    if signals.misconception_ids and PedagogyStrategy.ANALOGY in candidates:
        return PedagogyStrategy.ANALOGY

    # R3. 직전 오답 + 초보 — 설명 스캐폴딩.
    if (
        signals.last_attempt_correct is False
        and signals.mastery_level == "초보"
        and PedagogyStrategy.DIRECT in candidates
    ):
        return PedagogyStrategy.DIRECT

    # R4. 숙달 — 문제 우선(생산적 고투).
    if signals.mastery_level == "숙달" and PedagogyStrategy.PROBLEM_BASED in candidates:
        return PedagogyStrategy.PROBLEM_BASED

    # R5. 기본 — 질문 중심.
    if PedagogyStrategy.SOCRATIC in candidates:
        return PedagogyStrategy.SOCRATIC

    # 후보 소진 — 좁힌 집합에는 규칙표가 낼 전략이 없다(호출자가 원판정으로 폴백).
    return None


def select(
    signals: StudentSignals,
    *,
    k_type: str | None = None,
    difficulty: str | None = None,
) -> PedagogyStrategy:
    """학생 신호 → 교수법 전략(결정론 규칙표 v1 + 카탈로그 후보 필터). **허용 판정은 하지
    않는다** — `gate()` 담당.

    우선순위(먼저 걸린 규칙이 이긴다 — `_rule_table` 참조):
      R1. 막힘 상태 → `WORKED_EXAMPLE` 제안(허용은 게이트가 2축으로 판정).
      R2. 오개념 가설 있음 → `ANALOGY`.
      R3. 직전 오답 + 초보 → `DIRECT`.
      R4. 숙달 → `PROBLEM_BASED`.
      R5. 그 외 → `SOCRATIC`. "답이 아닌, 이유를 묻는" 기본값.

    카탈로그 후보 필터(PED-23 회수 — 04g §4·모듈 docstring): `pedagogy_catalog_filter_enabled`
    플래그 ON이고 필터 축 신호(`signals.grade_band`·`difficulty`·`k_type`)가 하나라도 있으면,
    규칙표 적용 전에 후보를 카탈로그 적합성으로 좁힌다. **좁힘만** — 공집합·후보 소진·카탈로그
    적재 실패는 규칙표 *원판정*으로 폴백하고 reason_code를 구조화 로그로 남긴다(조용한 실패
    금지). 플래그 OFF(기본)면 카탈로그를 조회조차 하지 않는다(기존 경로와 비트동일).

    `k_type`·`difficulty`는 문항/목표 축이라 신호(dataclass)가 아니라 호출부 kwargs로 받는다
    (`decide()`의 k_type 관례 동형). ⚠️ difficulty는 2026-07-29 실측 결과 study 경로에 상/중/하
    생산자가 없다(`LearningObjective`에 난이도 메타 부재·`problem.difficulty_overall`은 수치
    척도이고 study 경로 밖) — 축은 실재(카탈로그·narrow)하나 프로덕션 배선은 생산자가 생길
    때까지 정직한 공백이다(항상-None 신호 필드를 만들지 않기 위해 kwargs로만 연다).

    **출력은 렌더 어댑터가 등록된 전략으로 제한된다.** 폐쇄 enum은 10종이지만 어댑터는 5종만
    있어(REND-01), 미등록 전략을 고르면 호출자가 `LookupError`를 맞는다. 어댑터가 늘면 규칙표를
    함께 확장한다(거버넌스 테스트가 `select()` 출력 ⊆ 등록 전략을 동결한다 — 불변식 ③).
    """
    candidates = registered_strategies()
    # 원판정 — 필터와 무관한 규칙표 v1 결과. SOCRATIC ∈ 등록 전략은 거버넌스 테스트가 동결하므로
    # None은 이론상 미도달이나, 총함수 보증으로 강등 폴백 상수를 쓴다(조용한 크래시 금지).
    base_verdict = _rule_table(signals, candidates)
    if base_verdict is None:  # pragma: no cover — 거버넌스 동결상 미도달(방어 분기)
        base_verdict = _FALLBACK_STRATEGY

    if not get_settings().pedagogy_catalog_filter_enabled:
        return base_verdict
    if signals.grade_band is None and difficulty is None and k_type is None:
        return base_verdict  # 필터 축 신호 전무 — 필터할 것이 없다(정상 경로·로그 없음).

    try:
        cards: Mapping[str, PedagogyStrategyCard] = get_pedagogy_strategies()
    except Exception as exc:  # 코퍼스 손상·경로 회귀 등 — 효과 축이 선택 불능을 만들면 안 된다.
        logger.warning(
            "교수전략 카탈로그 적재 실패 — 필터 생략·규칙표 원판정 폴백 "
            "(reason_code=%s, error=%s)",
            REASON_CATALOG_UNAVAILABLE,
            type(exc).__name__,  # 침묵 실패 금지 — 예외 타입명 로그(CLAUDE.md)
        )
        return base_verdict

    narrowed = narrow_candidates(
        candidates,
        cards,
        grade_band=signals.grade_band,
        difficulty=difficulty,
        k_type=k_type,
    )
    if not narrowed:
        logger.info(
            "카탈로그 필터 공집합 — 필터 무시·규칙표 원판정 폴백 "
            "(reason_code=%s, grade_band=%s, difficulty=%s, k_type=%s, verdict=%s)",
            REASON_CATALOG_FILTER_EMPTY,
            signals.grade_band,
            difficulty,
            k_type,
            base_verdict.value,
        )
        return base_verdict

    filtered_verdict = _rule_table(signals, narrowed)
    if filtered_verdict is None:
        logger.info(
            "카탈로그 필터 후보 소진 — 규칙표 원판정 폴백 "
            "(reason_code=%s, narrowed=%s, grade_band=%s, difficulty=%s, k_type=%s, verdict=%s)",
            REASON_CATALOG_FILTER_EXHAUSTED,
            sorted(s.value for s in narrowed),
            signals.grade_band,
            difficulty,
            k_type,
            base_verdict.value,
        )
        return base_verdict
    return filtered_verdict


def gate(
    strategy: PedagogyStrategy,
    signals: StudentSignals,
    *,
    pack: PedagogyPack | None = None,
) -> GateResult:
    """교수학 게이트 — 위반 전략을 강등한다(2축). 통과면 요청 전략 그대로.

    현재 판정 대상은 `WORKED_EXAMPLE` 한 축이다. 나머지 전략은 단일 응답 문면이 아니라 여러 턴의
    *시퀀스* 성질(페이딩·표현 전환 균형)이라 이 시점 판정이 불가능하다 — `mode_guard`가 같은 이유로
    6개 모드를 `DEFERRED_MODES`로 남긴 것과 동일한 정직한 공백이며, 조용히 통과시키는 것과 다르다.

    `pack=None`(팩 미적용·조회 실패)이어도 **축②는 적용된다** — 팩이 없다는 사실이 냉담 정답 제공을
    열어주면 안 된다(fail-safe).

    ⚠️ **카탈로그 입력 금지(04g §4 불변식 ② — PED-23 동결)**: 이 함수는 교수전략 카탈로그
    (`strategy_registry`)를 읽지 않는다. 카탈로그는 select 전용 *효과* 축이며, 게이트가 YAML
    데이터를 읽기 시작하면 코퍼스 편집만으로 "효과 ≤ 허용"이 우회된다. 부재는
    `tests/backend/l4/test_catalog_consumption.py`가 정적(co_names)·런타임(레지스트리 봄베)으로
    동결한다 — 카탈로그 축을 추가하려면 그 테스트와 04g §4 개정이 선행이다.
    """
    if strategy is not PedagogyStrategy.WORKED_EXAMPLE:
        return GateResult(strategy=strategy, allowed=True)

    # 축① 팩 금지 — 시도 전 단계의 완전예제 "선행" 차단(실제 코퍼스에서는 CONCEPT 팩).
    forbids_worked_first = pack is not None and _MODE_WORKED_EXAMPLE_FIRST in pack.forbidden_modes
    if forbids_worked_first and signals.polya_stage in _PRE_ATTEMPT_STAGES:
        return GateResult(
            strategy=_FALLBACK_STRATEGY,
            allowed=False,
            reason_code=REASON_PACK_FORBIDS_WORKED_FIRST,
            requested=strategy,
        )

    # 축② 막힘 시 에스컬레이션 — 힌트가 부분 시연(3) 이상으로 올라간 뒤에만 허용.
    if signals.is_stuck and not signals.hint_escalated:
        return GateResult(
            strategy=_FALLBACK_STRATEGY,
            allowed=False,
            reason_code=REASON_HINT_NOT_ESCALATED,
            requested=strategy,
        )

    return GateResult(strategy=strategy, allowed=True)


def decide(
    signals: StudentSignals,
    *,
    k_type: str | None = None,
    difficulty: str | None = None,
) -> GateResult:
    """선택 + 게이트 합성 — 호출자가 쓰는 단일 진입점.

    `k_type`(학습목표의 지식 유형)을 주면 ① `select()` 카탈로그 후보 필터의 축(플래그 ON 시 —
    PED-23)과 ② 해당 교수법 팩 조회(게이트 축①)에 함께 쓰인다. 팩을 못 찾으면 축①은 생략되고
    축②만 적용된다(`gate()` fail-safe 참조). `difficulty`(상/중/하)는 select 필터 전용이며
    게이트에는 들어가지 않는다 — 카탈로그·난이도는 *효과* 축이지 *허용* 축이 아니다(04g §4
    불변식 ②). 생산자 현황은 `select()` docstring의 정직한 공백 부기 참조.
    """
    pack = get_pack(k_type) if k_type is not None else None
    return gate(select(signals, k_type=k_type, difficulty=difficulty), signals, pack=pack)


def selectable_strategies() -> frozenset[PedagogyStrategy]:
    """이 선택기가 낼 수 있는 전략 집합 — 렌더 어댑터 등록분과 일치해야 한다.

    거버넌스 테스트가 `select()` 실제 출력이 이 집합에 속하는지, 그리고 이 집합이 L3 등록분과
    같은지를
    동결한다(선택기가 렌더 불가 전략을 내는 회귀 차단).
    """
    return registered_strategies()


__all__ = [
    "REASON_CATALOG_FILTER_EMPTY",
    "REASON_CATALOG_FILTER_EXHAUSTED",
    "REASON_CATALOG_UNAVAILABLE",
    "REASON_HINT_NOT_ESCALATED",
    "REASON_PACK_FORBIDS_WORKED_FIRST",
    "GateResult",
    "StudentSignals",
    "decide",
    "gate",
    "grade_to_band",
    "narrow_candidates",
    "select",
    "selectable_strategies",
]
