"""L2 — Mastery 갱신 호출 계약의 **조립부**: 순수 커널 + BKT 추정기 + 교체 레지스트리.

타입 정본은 `schema/mastery_contract.py`(계층 의존 0)이고, 이 모듈은 그 계약에 **실제 구현을
꽂는다**. 세 가지를 한다:

① **순수 커널** — `compute_mastery_record`(prior 스칼라 + 관측 → 다음 측정). `EOS-13` 이전에
   `l2/mastery_tracking.py`가 들고 있던 바로 그 함수를 *한 글자도 바꾸지 않고* 옮겨 왔다
   (계약을 세우려면 추정기가 커널을 써야 하고, 커널이 tracking에 남으면 순환 import가 된다).
   `mastery_tracking`이 하위호환으로 재노출하므로 기존 import 경로는 그대로 산다.
② **BKT 추정기 어댑터** — `BktMasteryEstimator`가 `MasteryEstimator` Protocol을 만족하며
   내부에서 ①을 호출한다. 즉 **숫자를 만드는 코드가 하나뿐**이라 계약 경유로 값이 바뀔 수 없다
   (행동 동결이 테스트가 아니라 구조로 보장된다).
③ **레지스트리** — 추정기를 id로 등록·해소한다. 기본 추정기는 `ContextVar`로 들고 있어
   교체가 **호출부 수정 0**이며, 테스트가 전역 상태를 오염시키지 않는다(`use_estimator`
   컨텍스트 매니저가 원복 — OPS-07/OPS-09 순서 오염 교훈).

**집행 지점**(정본화 ≠ 집행 — 있는 척 금지)
--------------------------------------------
이 계약을 *실제로 경유하는* 코드는 2026-09-16 현재 아래 두 곳뿐이다:
  - `l2/mastery_tracking.py::_stage_attempt_mastery` (개념 축 적재)
  - `l2/skill_mastery_tracking.py::_stage_skill_attempt_mastery` (스킬 축 적재)
그 위의 서빙 진입점(`POST /v1/me/attempts` → `record_problem_attempt_mastery` ·
`api/coach.py` 완료 경로)은 두 함수를 통해 *간접적으로* 계약을 경유한다. **API·L3·L4가 이
계약 타입을 직접 읽는 배선은 아직 없다** — `LearnerState` 단일 조회 표면(`EOS-10`)·
`AssessmentEvidence` 구체 타입(`EOS-12`)·추천 계약(`EOS-14`)이 각자 소유한다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NamedTuple

from whymath_backend.l2.bkt import BktModel
from whymath_backend.schema.mastery_contract import (
    AssessmentEvidenceInput,
    LearnerMasteryState,
    MasteryAxis,
    MasteryContractError,
    MasteryEstimator,
    MasteryUpdate,
    clamp_unit,
)

logger = logging.getLogger("whymath.l2.mastery_contract")

__all__ = [
    "BKT_ESTIMATOR_ID",
    "AttemptOutcomeEvidence",
    "BktMasteryEstimator",
    "MasteryEstimatorFactory",
    "MasteryRecord",
    "UnknownMasteryEstimatorError",
    "active_estimator_id",
    "compute_mastery_record",
    "register_estimator",
    "registered_estimator_ids",
    "resolve_estimator",
    "state_from_history",
    "unregister_estimator",
    "update_mastery",
    "use_estimator",
]

# ── ① 순수 커널(이동분 — 값·주석 무변경) ──────────────────────────────────────
# confidence v1 휴리스틱: 표본 n개에서 `n/(n+HALFLIFE)` — 관측이 쌓일수록 측정 신뢰↑.
# n=5에서 0.5·n=10에서 ≈0.67. BKT는 신뢰도를 직접 주지 않으므로 표본 크기로 근사(후속:
# 사후 분산 기반·베타 분포 신뢰구간).
_CONFIDENCE_HALFLIFE = 5
_MASTERY_DECIMALS = 2  # Numeric(3,2) 정합


class MasteryRecord(NamedTuple):
    """다음 숙달 측정의 영속 필드 — `ConceptMasteryHistory`/`SkillMasteryHistory` 적재 입력.

    계약 산출 `MasteryUpdate`의 *부분집합*이다(좌석 컬럼 3개). 둘 다 남겨 둔 이유: 이 타입은
    적재 경로의 기존 계약이고(하위호환), `MasteryUpdate`는 여기에 출처(`estimator_id`)·출발점
    (`prior_mastery`)을 더해 **무엇이 작동했는지** 말한다.
    """

    mastery: float
    confidence: float
    sample_size: int


def compute_mastery_record(
    prior_mastery: float | None,
    prior_sample_size: int | None,
    correct: bool,
    model: BktModel,
    elapsed_days: float = 0.0,
) -> MasteryRecord:
    """직전 측정 + 관측 → 다음 측정(순수·DB 무관).

    `prior_mastery`가 None이면(첫 관측) 모델의 사전 P(L0)에서 시작한다. mastery는 저장
    정밀도(2자리)로 반올림(다음 갱신이 같은 값을 prior로 읽도록). sample_size는 직전+1.

    slice L2-6: `elapsed_days`(직전 측정 이후 경과일)만큼 *관측 갱신 전* prior에 망각 감쇠를
    적용한다(`model.apply_forgetting`). p_forget=0(기본)이면 무영향(하위 호환). 첫 관측은
    elapsed 무관(prior=P(L0)·감쇠 대상 없음).

    EOS-13 메모: 이 함수는 계약의 *내부*가 됐다 — 새 호출부는
    `update_mastery(learner_state, assessment_evidence)`를 쓴다. 여기는 BKT 추정기의 커널로
    남아 하위호환 경로(`compute_mastery_record` 직접 호출)를 계속 지탱한다.
    """
    prior = model.initial_mastery if prior_mastery is None else prior_mastery
    prior = model.apply_forgetting(prior, elapsed_days)
    mastery = round(model.update(prior, correct), _MASTERY_DECIMALS)
    sample_size = (prior_sample_size or 0) + 1
    confidence = round(sample_size / (sample_size + _CONFIDENCE_HALFLIFE), _MASTERY_DECIMALS)
    return MasteryRecord(mastery=mastery, confidence=confidence, sample_size=sample_size)


# ── 증거 어댑터(EOS-12 착지 전 임시 좌석) ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AttemptOutcomeEvidence:
    """`AssessmentEvidenceInput`을 만족하는 **최소** 어댑터 — 채점 결과 1건.

    ⚠️ **이것은 `AssessmentEvidence`가 아니다.** 구체 evidence 타입의 좌석은 `EOS-12`가
    소유한다(2026-09-16 착지). 계약이 실제로 읽는 속성만 담은 임시 운반체이며, 폐기는
    `EOS-18`이 소유한다(호출부 시그니처는 그대로).

    EOS-108이 더한 3필드 — **전부 `AssessmentEvidenceInput`(또는 그 선택 확장)이 읽는 축**이고,
    계약이 읽지 않는 속성은 여기에도 두지 않는다:
      · `attempt_id` — 멱등 키. `AssessmentEvidence`가 이미 가진 속성이라 `EOS-18` 폐기 시
        그대로 승계된다.
      · `hint_used` — `HintUsageSignal`(선택 Protocol). **`None`은 "모른다"**이며 "안 썼다"가
        아니다. `AssessmentEvidence`에는 아직 이 축이 없어 선택 Protocol로 분리돼 있다.
      · `consecutive_correct` — `StreakSignal`(선택 Protocol). 같은 이유로 선택이다.

    **정직 표기(집행 지점)**: 2026-09-18 현재 두 서빙 호출부(`_stage_attempt_mastery`·
    `_stage_skill_attempt_mastery`)가 채우는 것은 `correct`·`observed_at`·`attempt_id` 셋이고,
    `hint_used`·`consecutive_correct`는 **아무도 채우지 않는다**(둘 다 None). 기본 추정기
    `bkt-v1`은 그 두 축을 읽지 않으므로 오늘의 숙달 값에는 영향이 0이며, 그 축을 읽는
    `simple-additive-v1`이 기본이 되려면 생산자 배선이 선행 조건이다 — 그 사실을 감추지 않고
    적어 둔다(CLAUDE.md 「작동한 비율」 원칙).
    """

    correct: bool
    observed_at: datetime
    attempt_id: uuid.UUID | None = None
    hint_used: bool | None = None
    consecutive_correct: int | None = None


# ── ② BKT 추정기 어댑터 ───────────────────────────────────────────────────────

#: 기본 추정기 식별자. 값을 바꾸면 산출의 출처 표기가 바뀌므로 상수로 고정한다.
BKT_ESTIMATOR_ID = "bkt-v1"


class BktMasteryEstimator:
    """BKT 추정기 — `MasteryEstimator` Protocol 구현(v1 기본).

    내부는 `compute_mastery_record`(위 ①) 호출뿐이다. **새 수학을 쓰지 않는다** — 계약 도입으로
    숙달 수치가 달라지면 그것은 리팩터가 아니라 정책 변경이므로, 값을 만드는 코드를 하나로
    유지해 그 가능성 자체를 없앴다.
    """

    def __init__(self, model: BktModel | None = None) -> None:
        self._model = model or BktModel()

    @property
    def estimator_id(self) -> str:
        """레지스트리 키이자 산출 출처 표기."""
        return BKT_ESTIMATOR_ID

    @property
    def model(self) -> BktModel:
        """내부 BKT 모델(파라미터 조회용·읽기 전용 접근)."""
        return self._model

    def estimate(
        self,
        learner_state: LearnerMasteryState,
        assessment_evidence: AssessmentEvidenceInput,
    ) -> MasteryUpdate:
        """직전 상태 + 증거 1건 → 다음 측정(순수)."""
        elapsed_days = learner_state.elapsed_days_until(assessment_evidence.observed_at)
        # 직전 측정 시각을 모르면(첫 관측) 감쇠 대상이 없다 — 커널에는 0.0을 넘기되
        # 산출에는 None을 그대로 싣는다("경과 0일"과 "기준점 없음"을 섞지 않는다).
        record = compute_mastery_record(
            learner_state.mastery,
            learner_state.sample_size,
            assessment_evidence.correct,
            self._model,
            0.0 if elapsed_days is None else elapsed_days,
        )
        return MasteryUpdate(
            axis=learner_state.axis,
            target_id=learner_state.target_id,
            mastery=record.mastery,
            confidence=record.confidence,
            sample_size=record.sample_size,
            prior_mastery=learner_state.mastery,
            elapsed_days=elapsed_days,
            estimator_id=self.estimator_id,
            # 멱등 키는 *계산 입력이 아니라 신원*이다 — 추정기가 만들지 않고 그대로 옮긴다.
            attempt_id=assessment_evidence.attempt_id,
        )


# ── ③ 레지스트리 ─────────────────────────────────────────────────────────────

#: 추정기 생성자(무인자 팩토리). 인스턴스가 아니라 팩토리를 등록하는 이유: 추정기가 상태를
#: 들게 되는 날(DKT 은닉 상태 등) 요청 간에 공유되지 않도록 해소 시점에 새로 만들기 위해서다.
MasteryEstimatorFactory = Callable[[], MasteryEstimator]


class UnknownMasteryEstimatorError(LookupError):
    """등록되지 않은 추정기 id를 해소하려 했다 — 조용히 기본값으로 떨어지지 않는다.

    폴백이 없는 이유: "DKT로 바꿨다고 생각했는데 실은 BKT가 돌고 있었다"가 가장 비싼 실패다
    (CLAUDE.md 침묵 실패 금지 · "작동 신호 없는 알고리즘 부착 금지").
    """


_REGISTRY: dict[str, MasteryEstimatorFactory] = {BKT_ESTIMATOR_ID: BktMasteryEstimator}

#: 현재 기본 추정기 id. `ContextVar`라 비동기 태스크·테스트 간 격리가 되고, 되돌리기가
#: 구조적으로 보장된다(전역 재대입은 순서 의존 오염을 남긴다).
_ACTIVE_ESTIMATOR_ID: ContextVar[str] = ContextVar(
    "whymath_active_mastery_estimator_id", default=BKT_ESTIMATOR_ID
)


def register_estimator(
    estimator_id: str,
    factory: MasteryEstimatorFactory,
    *,
    replace: bool = False,
) -> None:
    """추정기 팩토리를 id로 등록한다.

    이미 있는 id를 덮어쓰려면 `replace=True`를 **명시**해야 한다 — 두 구현이 같은 이름을 다투는
    상황을 조용히 넘기지 않기 위해서다(무증상 교체 금지).
    """
    if not estimator_id:
        raise MasteryContractError("estimator_id는 비어 있을 수 없습니다.")
    if estimator_id in _REGISTRY and not replace:
        raise MasteryContractError(
            f"추정기 id가 이미 등록돼 있습니다: {estimator_id!r}. "
            "의도한 교체라면 replace=True를 명시하십시오."
        )
    _REGISTRY[estimator_id] = factory


def unregister_estimator(estimator_id: str) -> None:
    """등록을 해제한다(테스트 정리용). 없는 id는 `UnknownMasteryEstimatorError`."""
    if estimator_id not in _REGISTRY:
        raise UnknownMasteryEstimatorError(
            f"등록되지 않은 추정기 id: {estimator_id!r}. 등록된 id: {registered_estimator_ids()}"
        )
    del _REGISTRY[estimator_id]


def registered_estimator_ids() -> tuple[str, ...]:
    """등록된 추정기 id 전량(정렬) — 진단·오류 메시지용."""
    return tuple(sorted(_REGISTRY))


def active_estimator_id() -> str:
    """현재 문맥의 기본 추정기 id — *지금 무엇이 돌 것인가*를 묻는 자리."""
    return _ACTIVE_ESTIMATOR_ID.get()


def _ensure_estimator(candidate: object, estimator_id: str) -> MasteryEstimator:
    """팩토리 산출이 `MasteryEstimator` 계약을 만족하는지 확인 — 아니면 즉시 실패.

    Protocol은 정적 검사(mypy)가 1차 방어선이지만, 레지스트리는 *런타임에* 임의 객체를 받는
    표면이라 여기서 한 번 더 막는다(타입 검사를 통과하지 않는 경로 — 플러그인·테스트 스텁).
    """
    if not isinstance(candidate, MasteryEstimator):
        raise MasteryContractError(
            f"추정기 {estimator_id!r}가 MasteryEstimator 계약을 만족하지 않습니다"
            f"(필요: estimator_id 속성·estimate 메서드, 받음: {type(candidate).__name__})."
        )
    return candidate


def resolve_estimator(estimator_id: str | None = None) -> MasteryEstimator:
    """id로 추정기 인스턴스를 만든다. id 생략 시 현재 문맥의 기본 추정기.

    미등록 id는 `UnknownMasteryEstimatorError`(기본값 폴백 없음). 계약 불만족 객체는
    `MasteryContractError`.
    """
    key = active_estimator_id() if estimator_id is None else estimator_id
    factory = _REGISTRY.get(key)
    if factory is None:
        raise UnknownMasteryEstimatorError(
            f"등록되지 않은 추정기 id: {key!r}. 등록된 id: {registered_estimator_ids()}"
        )
    return _ensure_estimator(factory(), key)


@contextmanager
def use_estimator(estimator_id: str) -> Iterator[None]:
    """블록 안에서만 기본 추정기를 바꾼다 — 나갈 때 **반드시** 원복한다.

    교체 가능성의 실증(가짜 추정기 주입)과 운영 중 A/B 모두 이 한 지점을 쓴다. 미등록 id는
    블록 진입 시점에 `UnknownMasteryEstimatorError`로 즉시 막는다(블록 안에서 뒤늦게 터지면
    "무엇이 돌았는지 모르는" 구간이 생긴다).
    """
    if estimator_id not in _REGISTRY:
        raise UnknownMasteryEstimatorError(
            f"등록되지 않은 추정기 id: {estimator_id!r}. 등록된 id: {registered_estimator_ids()}"
        )
    token = _ACTIVE_ESTIMATOR_ID.set(estimator_id)
    try:
        yield
    finally:
        _ACTIVE_ESTIMATOR_ID.reset(token)


# ── 계약 진입점 ───────────────────────────────────────────────────────────────


def update_mastery(
    learner_state: LearnerMasteryState,
    assessment_evidence: AssessmentEvidenceInput,
    *,
    estimator: MasteryEstimator | None = None,
) -> MasteryUpdate:
    """**Mastery 갱신의 단일 호출 계약** — 상태 + 증거 → 갱신.

    개념 축·스킬 축이 같은 함수를 쓴다(축은 `learner_state.axis`가 들고 있다). 내부 구현은
    갈라져 있어도 되지만 *계산은 한 번*이다 — 통합이 재계산을 낳지 않는다.

    `estimator`를 주면 그것을 쓰고(명시적 덮어쓰기), 생략하면 현재 문맥의 기본 추정기를
    레지스트리에서 해소한다. 즉 **추정기 교체는 이 함수의 호출부를 한 글자도 고치지 않는다.**

    산출이 입력과 다른 대상을 가리키면 `MasteryContractError`을 던진다 — 잘못된 추정기가
    다른 개념의 숙달을 조용히 덮어쓰는 것이 이 계약에서 가장 위험한 실패다.

    EOS-108: 반환 직전 `_enforce_bounds`가 0~1을 **다시 잰다**. 추정기를 갈아 끼울 수 있게
    만든 이상 범위를 지키지 않는 구현이 들어올 표면이 생겼고, 그 표면의 방어는 생성자 검사
    하나로는 부족하다(사후 변조 경로가 남는다). 잘린 산출은 `bounds_clamped=True`를 달고
    경고 로그를 남긴다 — 값은 구제하되 사실은 잃지 않는다.

    ⚠️ 이름 메모: `l2/bkt.py`에도 `update_mastery(prior, correct, params)`가 있다(BKT 수식
    한 스텝). 이쪽은 *호출 계약*이고 그쪽은 *수식*이다 — 패키지 레벨(`whymath_backend.l2`)에는
    bkt의 것만 재노출하므로, 이 함수는 항상 모듈 경로로 import한다
    (`from whymath_backend.l2.mastery_contract import update_mastery`).
    """
    engine = resolve_estimator() if estimator is None else estimator
    update = engine.estimate(learner_state, assessment_evidence)
    if not isinstance(update, MasteryUpdate):
        raise MasteryContractError(
            f"추정기 {engine.estimator_id!r}가 MasteryUpdate가 아닌 "
            f"{type(update).__name__}을 반환했습니다."
        )
    if update.axis is not learner_state.axis or update.target_id != learner_state.target_id:
        raise MasteryContractError(
            f"추정기 {engine.estimator_id!r}가 다른 대상의 갱신을 반환했습니다"
            f"(요청: {learner_state.axis}/{learner_state.target_id}, "
            f"받음: {update.axis}/{update.target_id})."
        )
    return _enforce_bounds(update, engine.estimator_id)


def _enforce_bounds(update: MasteryUpdate, estimator_id: str) -> MasteryUpdate:
    """추정기 산출의 0~1 경계를 **계약이 다시 잰다** — 추정기를 신뢰하지 않는다.

    `MasteryUpdate.__post_init__`이 이미 범위를 검사하지 않느냐는 물음의 답: 그 검사는
    *정상적으로 생성자를 통과한* 객체만 막는다. frozen dataclass도 `object.__setattr__`로
    사후 변조가 가능하고, 추정기는 레지스트리를 통해 **임의 구현이 꽂히는 표면**이다. 즉
    생성자 검사는 저자의 실수를 막고, 이 함수는 *신뢰하지 않는 구현*을 막는다 — 같은 불변식의
    두 번째 회계이며, 둘 중 하나만 있으면 학생 상태에 범위 밖 값이 들어갈 경로가 남는다.

    자르는 쪽을 택한 이유와 자른 사실을 남기는 이유는 `schema.mastery_contract.clamp_unit`
    docstring에 있다. 여기서는 그 위에 **경고 로그**를 얹는다 — 어느 추정기가 어떤 값을 냈는지
    타입·값과 함께 남긴다(침묵 실패 금지 · 대상 id는 개념/스킬 식별자이지 학생 PII가 아니다).
    """
    bounded_mastery = clamp_unit(update.mastery)
    bounded_confidence = clamp_unit(update.confidence)
    if bounded_mastery == update.mastery and bounded_confidence == update.confidence:
        return update
    logger.warning(
        "MasteryContractBoundsViolation: 추정기 %r가 범위 밖 산출을 냈습니다 "
        "(axis=%s target=%s mastery=%r->%r confidence=%r->%r) — 계약이 잘랐습니다.",
        estimator_id,
        update.axis.value,
        update.target_id,
        update.mastery,
        bounded_mastery,
        update.confidence,
        bounded_confidence,
    )
    return replace(
        update,
        mastery=bounded_mastery,
        confidence=bounded_confidence,
        bounds_clamped=True,
    )


def state_from_history(
    axis: MasteryAxis,
    target_id: str,
    *,
    mastery: float | None,
    sample_size: int | None,
    measured_at: datetime | None,
) -> LearnerMasteryState:
    """직전 이력 행의 컬럼 3개 → `LearnerMasteryState`(적재 래퍼 공용 조립기).

    개념 축·스킬 축 래퍼가 같은 방식으로 상태를 만들게 해 두 축이 서로 다른 해석(예: 한쪽만
    NULL을 0으로 접기)을 갖지 못하게 한다. 값 변환은 하지 않는다 — 넘어온 None은 None이다.
    """
    return LearnerMasteryState(
        axis=axis,
        target_id=target_id,
        mastery=mastery,
        sample_size=sample_size,
        measured_at=measured_at,
    )
