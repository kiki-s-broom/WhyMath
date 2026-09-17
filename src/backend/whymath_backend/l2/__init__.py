"""L2 학습자 모델 — 학생의 *숨은 학습 상태*를 데이터로 추정.

성취기준(개념)별 숙달 확률·문항 난이도·학생 능력·정서 신호·오개념을 추적해 상위 계층
(L3 콘텐츠 생성·L4 교수학 결정·L6 모드 라우팅)에 *학습자 모델 입력*을 제공한다.
`docs/architecture/02_learner_model.md` 참조.

슬라이스 1: BKT(Bayesian Knowledge Tracing) 숙달 확률 추정(`bkt`). 슬라이스 2: BKT ↔
`ConceptMasteryHistory` 시계열 영속 결선(`mastery_tracking`). 슬라이스 6: forgetting(시간
감쇠). 슬라이스 7: IRT(문항 난이도·학생 능력 θ 추정·`irt`). 범위 밖(후속): IRT 난이도
적합·DKT 신경망·파라미터 적합(EM)·정서 신호·오개념 매핑.

이름 충돌 메모: `bkt`·`irt` 모두 `probability_correct`를 정의한다(서로 다른 모델). 패키지
레벨에선 BKT의 것만 재노출하고, IRT 정답확률은 `whymath_backend.l2.irt.probability_correct`로
명시 접근한다(모델 혼동 방지).

같은 이유로 `mastery_contract.update_mastery`(호출 계약 — 상태+증거 → 갱신)는 패키지 레벨에
재노출하지 **않는다**. 여기 있는 `update_mastery`는 `bkt`의 것(수식 한 스텝)이며, 호출 계약은
`whymath_backend.l2.mastery_contract.update_mastery`로 명시 접근한다(EOS-13).
"""

from __future__ import annotations

from whymath_backend.l2.ability_estimation import (
    ConceptAbilityItem,
    compute_concept_abilities,
    difficulty_to_logit,
    estimate_global_ability,
    resolve_item_difficulty_b,
)
from whymath_backend.l2.ability_tracking import (
    AbilityReading,
    get_current_ability,
    get_current_theta,
)
from whymath_backend.l2.bkt import (
    DEFAULT_BKT_PARAMETERS,
    BktModel,
    BktParameters,
    apply_forgetting,
    apply_learning,
    posterior_mastery,
    probability_correct,
    update_mastery,
)
from whymath_backend.l2.concept_diagnosis import (
    Agreement,
    ConceptDiagnosis,
    compute_concept_diagnoses,
    diagnosis_agreement,
)
from whymath_backend.l2.irt import (
    IrtItem,
    ability_standard_error,
    estimate_ability,
    estimate_difficulty,
    fit_jmle,
    item_information,
    select_next_item,
    select_weighted_item,
    theta_to_mastery_proxy,
    total_information,
)
from whymath_backend.l2.item_calibration import calibrate_item_difficulties
from whymath_backend.l2.learning_path import (
    LearningPath,
    LearningStep,
    build_learning_path,
    fetch_internal_prerequisite_edges,
    order_learning_path,
)
from whymath_backend.l2.mastery_contract import (
    BKT_ESTIMATOR_ID,
    AttemptOutcomeEvidence,
    BktMasteryEstimator,
    UnknownMasteryEstimatorError,
    active_estimator_id,
    register_estimator,
    registered_estimator_ids,
    resolve_estimator,
    use_estimator,
)
from whymath_backend.l2.mastery_tracking import (
    MasteryRecord,
    compute_mastery_record,
    get_current_mastery,
    get_primary_concept_id,
    record_attempt_mastery,
    record_problem_attempt_mastery,
)

__all__ = [
    "BKT_ESTIMATOR_ID",
    "DEFAULT_BKT_PARAMETERS",
    "AbilityReading",
    "Agreement",
    "AttemptOutcomeEvidence",
    "BktMasteryEstimator",
    "BktModel",
    "BktParameters",
    "ConceptAbilityItem",
    "ConceptDiagnosis",
    "IrtItem",
    "LearningPath",
    "LearningStep",
    "MasteryRecord",
    "UnknownMasteryEstimatorError",
    "ability_standard_error",
    "active_estimator_id",
    "apply_forgetting",
    "apply_learning",
    "build_learning_path",
    "calibrate_item_difficulties",
    "compute_concept_abilities",
    "compute_concept_diagnoses",
    "compute_mastery_record",
    "diagnosis_agreement",
    "difficulty_to_logit",
    "estimate_ability",
    "estimate_difficulty",
    "estimate_global_ability",
    "fetch_internal_prerequisite_edges",
    "fit_jmle",
    "get_current_ability",
    "get_current_mastery",
    "get_current_theta",
    "get_primary_concept_id",
    "item_information",
    "order_learning_path",
    "posterior_mastery",
    "select_next_item",
    "select_weighted_item",
    "probability_correct",
    "record_attempt_mastery",
    "record_problem_attempt_mastery",
    "register_estimator",
    "registered_estimator_ids",
    "resolve_estimator",
    "resolve_item_difficulty_b",
    "theta_to_mastery_proxy",
    "total_information",
    "update_mastery",
    "use_estimator",
]
