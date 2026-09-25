"""L2 추천 폐루프 회계 — `/me/next-problem`이 반환한 추천을 `evidence_event`에 기록 (REC-03).

────────────────────────────────────────────────────────────────────────────
왜 필요한가 — 처치 기록 없이는 추천 효과를 잴 수 없다
────────────────────────────────────────────────────────────────────────────
`ai_recommendation_module_gap_review.md` §3 D3 실측: `/v1/me/next-problem`이 IRT CAT으로
문항을 추천하지만, 그 추천이 *학생에게 실제로 나갔다*는 사실을 잇는 기록이 어디에도 없다.
`AttemptSubmitRequest`에 추천 출처 필드가 0개이고 `attempt_event`의 11종 이벤트 타입에도
추천 관련이 없다. 그래서 추천 수용률·추천 문항 정답률·약점 감소 효과를 잴 방법이 없고,
`l4/pedagogy/adaptive/policy.py`의 bandit은 보상 신호 부재로 영구 미승격 상태다.

**가짜 처치 금지**(`l2/pedagogy_evidence.py` 계약 승계): 이 좌석은 "학생에게 실제로 반환된
추천"만 기록한다. 후보 조회만 하고 `problem_id=null`로 끝난 요청(추천 실패)은 처치가 아니다
— 호출자(`api/me.py`)는 `problem_id`가 확정된 뒤에만 이 함수를 부른다.

────────────────────────────────────────────────────────────────────────────
좌석 재사용 — `evidence_event`를 신규 테이블 0으로 그대로 쓴다
────────────────────────────────────────────────────────────────────────────
PED-03(`l2/pedagogy_evidence.py`)이 이미 세운 `evidence_event` 좌석(session_id 축·user_id
없음·비민감 meta·가짜 처치 금지)을 그대로 재사용한다. 다만 이 테이블의 `objective_id`·
`k_type`은 원래 *학습목표(pedagogy pack)* 축이라 IRT 문항 추천에는 자연스러운 값이 없다 —
둘 다 NOT NULL 스키마 제약이라 placeholder가 필요하다. **이 placeholder가 PED-03의 교수법
효과 집계를 오염시키지 않는 근거**: `l4/pedagogy/adaptive/effectiveness.py:196`이
`EvidenceEvent.event_type.in_([EVENT_TYPE_TREATMENT, EVENT_TYPE_OUTCOME])`로 그 두 문자열만
걸러 읽는다(실측 확인) — `EVENT_TYPE_RECOMMENDATION_TREATMENT`는 그 필터에 애초에 걸리지
않는다. 즉 event_type 축이 두 도메인을 완전히 분리한다.

`session_id`는 **실 학습 세션**이다(EOS-131 — 종전에는 매 호출 `uuid.uuid4()` placeholder라
이 추천이 어느 학생 것인지 집어낼 조인 키가 없었다). 호출자(`api/me.py`)가 서버 측 유휴 규칙
writer(`l2/learning_session_writer.record_learning_activity`)로 얻은 `learning_session.session_id`를
넘긴다. **학습자 결합은 `evidence_event.session_id → learning_session.user_id` 경로로만 얻는다** —
이 테이블에 `user_id` 컬럼을 추가하지 않고, 이 함수의 시그니처에도 `user_id` 슬롯이 없다
(PED-03·REC-03의 구조적 차단 유지). 부수 성질: `session_id`는 FK가 아니므로 삭제권 이행으로
세션 행이 지워지면 추천 기록은 자동으로 학습자와 끊긴다(`privacy/erasure`).

세션 기록이 실패해 `learning_session_id=None`이 오면(never-break 경로 — writer가 예외 타입명을
이미 로그했다) 그때만 종전처럼 placeholder를 발급한다. 처치 존재 자체(KPI ③ 설명 가능성의 분모)는
잃지 않되, 그 행은 어떤 세션에도 결합되지 않으므로 KPI ① 분자에 들어가지 않는다 — 가짜 결합을
만들지 않는다.

B1(미성년 원문 발화 평문 저장 금지): `meta`에는 problem_id·theta·pool_size·applied_weights·
mode·gate_reason·candidates·policy_version·reason 등 비민감 메타만 넣는다. 이 모듈의 함수
시그니처에는 학생 원문·풀이·user_id 슬롯이 아예 없다(구조적 차단 — 나중에 실수로 채울 여지
자체가 없다).

────────────────────────────────────────────────────────────────────────────
REC-11: candidates[]·policy_version — 추천 오프라인 평가의 소급 불가 축(W2 스키마 ②)
────────────────────────────────────────────────────────────────────────────
지금까지는 *어떤 문항이 나갔는지*만 기록했고 *그때 무엇과 비교해 선택됐는지*는 기록하지
않았다 — 정책(선택 알고리즘)이 나중에 바뀌면, 과거 로그로 "그 시점 정책이 얼마나 좋았는가"를
소급 평가(counterfactual/off-policy evaluation)할 수 없다. `candidates`(후보 problem_id·점수
쌍)와 `policy_version`(선택 알고리즘 식별자)을 추가해 이 소급 평가의 최소 재료를 남긴다.

`candidates`는 원 후보 풀 전체가 아니라 점수 내림차순 상위 `CANDIDATES_META_CAP`건만 저장한다
— `pool_size`가 원 풀 크기를 이미 별도로 기록하므로 이 축소가 은폐되지 않는다(전량 저장은
매 호출마다 최대 50건의 UUID+float를 누적하는 과공학). `policy_version`은 호출자가 지금
쓰는 후보생성·선택 알고리즘의 식별자를 넘긴다(`POLICY_VERSION_CAT`/`POLICY_VERSION_SUNEUNG`)
— 알고리즘이 바뀌면 새 버전 문자열을 쓴다(과거 로그는 그대로, 무엇이 바뀌었는지는 이 축이
구분).

**followed 결과 결합(추천→정답 여부 조인)은 이 좌석의 범위 밖**이다. EOS-131로 실 session_id가
배선돼 조인 *키*는 생겼지만, 결과를 결합하는 집계는 이 좌석이 아니라 소비자(`ops/loop_kpi_gate`
KPI ① 등)의 몫이다. `candidates`·`policy_version`은 "무엇과 비교해 선택했는가"를 재구성하는
선행 재료일 뿐, 이 좌석 자체가 결과를 결합하지 않는다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.l2.recommendation_contract import RecommendationReason
from whymath_backend.schema.enums import KnowledgeType

EVENT_TYPE_RECOMMENDATION_TREATMENT: str = "recommendation_render"
"""처치 — `/me/next-problem`이 학생에게 *실제로 반환한* 추천 문항 1건."""

# `meta` JSONB 키 — 비민감 메타만(B1). 집계가 이 키로 되읽을 수 있게 상수로 동결한다.
META_KEY_PROBLEM_ID: str = "problem_id"
META_KEY_THETA: str = "theta"
META_KEY_POOL_SIZE: str = "pool_size"
META_KEY_APPLIED_WEIGHTS: str = "applied_weights"
META_KEY_MODE: str = "mode"
META_KEY_GATE_REASON: str = "gate_reason"
META_KEY_CANDIDATES: str = "candidates"
META_KEY_POLICY_VERSION: str = "policy_version"
META_KEY_REASON: str = "reason"

# 정책(후보생성·선택 알고리즘) 식별자 — REC-11. 알고리즘이 바뀌면 새 문자열을 쓴다(과거
# 로그는 그대로 두고, 무엇이 바뀌었는지는 이 값으로 구분 — 오프라인 평가가 다른 정책의
# 로그를 섞어 판정하지 않게 한다).
POLICY_VERSION_CAT: str = "cat_v1"
"""기본 CAT(θ 근방 SQL 축소 + `select_weighted_item` 가중 정보량 최대) — `mode` 미지정."""
POLICY_VERSION_SUNEUNG: str = "suneung_v1"
"""수능 적응 추천(`recommend_suneung_index` — L6 진실 게이트 × IRT CAT) — `mode=suneung`."""

CANDIDATES_META_CAP: int = 10
"""`candidates[]` 상한 — 원 풀(`pool_size`, 최대 50)을 그대로 다 저장하지 않는다. 점수
내림차순 상위 N만 남긴다(모듈 docstring REC-11 절 참조)."""

# objective_id·k_type NOT NULL 제약을 채우는 네임스페이스 격리 placeholder(모듈 docstring
# "좌석 재사용" 참조) — event_type 축으로 PED-03 집계와 완전히 분리되므로 실제 학습목표·
# 지식유형처럼 읽히거나 조인될 위험이 없다.
_OBJECTIVE_ID_PLACEHOLDER: str = "recommendation:next_problem"
_K_TYPE_PLACEHOLDER: KnowledgeType = KnowledgeType.PROCEDURE


def _now() -> datetime:
    """기록 시각(UTC aware) — 파티션 키 `time`. 테스트가 패치할 수 있게 함수로 뺀다."""
    return datetime.now(UTC)


async def record_recommendation_treatment(
    session: AsyncSession,
    *,
    problem_id: uuid.UUID,
    theta: float,
    pool_size: int,
    applied_weights: bool,
    mode: str | None = None,
    gate_reason: str | None = None,
    candidates: list[tuple[uuid.UUID, float]] | None = None,
    policy_version: str | None = None,
    reason: RecommendationReason | None = None,
    occurred_at: datetime | None = None,
    learning_session_id: uuid.UUID | None = None,
) -> EvidenceEvent:
    """`/me/next-problem`이 학생에게 실제로 반환한 추천 1건을 stage한다(commit 0).

    `session.add`만 하고 commit하지 않는다(`pedagogy_evidence.py` 관례 — 커밋 경계는
    호출자 책임). 호출자는 `problem_id`가 null이 아닐 때만(추천이 실제로 나갔을 때만)
    이 함수를 불러야 한다 — 가짜 처치 금지.

    `pool_size`: 선택 시점의 후보 풀 크기(θ 근방 SQL 선별 결과 건수). `applied_weights`:
    `prioritize_weak_concepts` 가중이 실제로 적용됐는지(약점 개념 가중 쿼리가 돌았는지).
    `mode`: "suneung" 또는 None(기본 CAT). `gate_reason`: 이 추천이 어떤 게이트 사유로
    조정됐는지(있으면) — 현재 호출부는 채우지 않지만 향후 L6 게이팅 사유 노출용으로 열어둔다.

    `candidates`(REC-11): `(problem_id, score)` 쌍의 목록 — 점수 내림차순 상위
    `CANDIDATES_META_CAP`건만 저장한다(원 풀 전체가 아님, 모듈 docstring REC-11 절 참조).
    `policy_version`: 이 추천을 만든 후보생성·선택 알고리즘의 식별자(`POLICY_VERSION_CAT`/
    `POLICY_VERSION_SUNEUNG`). 둘 다 선택 인자다 — 호출자가 아직 준비되지 않았으면
    생략해도 기존 동작과 완전히 동일(회귀 0).

    `reason`(EOS-14): `l2.recommendation_contract.RecommendationReason` — *왜 이 문항인가*.
    영속 좌석을 **새로 만들지 않고** 이 좌석에 싣는다(EOS-14 acceptance ④ "재구현하지
    않는다"). `candidates`가 *무엇과 비교해 골랐나*를 남긴다면 이 키는 *어느 개념의 어떤
    숙달 때문에 골랐나*를 남긴다 — 소급 평가에서 두 질문은 다르다. 직렬화는 계약 모델의
    `model_dump(mode="json")`이라 enum·UUID가 JSONB에 그대로 들어간다. 여전히 비민감이다
    (개념 id·숙달 수치이고 학생 원문·식별자가 아니다 — B1 불변).

    `learning_session_id`(EOS-131): 이 추천이 나간 실 학습 세션. `None`이면 세션 기록 실패
    경로로 보고 결합 불가 placeholder를 발급한다(모듈 docstring 참조 — 가짜 결합 금지).
    """
    meta: dict[str, Any] = {
        META_KEY_PROBLEM_ID: str(problem_id),
        META_KEY_THETA: theta,
        META_KEY_POOL_SIZE: pool_size,
        META_KEY_APPLIED_WEIGHTS: applied_weights,
    }
    # None인 선택 키는 아예 넣지 않는다 — "없음"과 "null로 기록됨"을 구분 가능하게.
    if mode is not None:
        meta[META_KEY_MODE] = mode
    if gate_reason is not None:
        meta[META_KEY_GATE_REASON] = gate_reason
    if candidates is not None:
        ranked = sorted(candidates, key=lambda pair: pair[1], reverse=True)
        meta[META_KEY_CANDIDATES] = [
            {"problem_id": str(pid), "score": score} for pid, score in ranked[:CANDIDATES_META_CAP]
        ]
    if policy_version is not None:
        meta[META_KEY_POLICY_VERSION] = policy_version
    if reason is not None:
        meta[META_KEY_REASON] = reason.model_dump(mode="json")

    row = EvidenceEvent(
        time=occurred_at if occurred_at is not None else _now(),
        # EOS-131: 실 학습 세션. None(세션 기록 실패)일 때만 어떤 세션에도 결합되지 않는
        # placeholder — 학습자와 이어 붙일 키를 지어내지 않는다.
        session_id=learning_session_id if learning_session_id is not None else uuid.uuid4(),
        objective_id=_OBJECTIVE_ID_PLACEHOLDER,
        k_type=_K_TYPE_PLACEHOLDER,
        event_type=EVENT_TYPE_RECOMMENDATION_TREATMENT,
        meta=meta,
    )
    session.add(row)
    return row


__all__ = [
    "CANDIDATES_META_CAP",
    "EVENT_TYPE_RECOMMENDATION_TREATMENT",
    "META_KEY_APPLIED_WEIGHTS",
    "META_KEY_CANDIDATES",
    "META_KEY_GATE_REASON",
    "META_KEY_MODE",
    "META_KEY_POLICY_VERSION",
    "META_KEY_POOL_SIZE",
    "META_KEY_PROBLEM_ID",
    "META_KEY_REASON",
    "META_KEY_THETA",
    "POLICY_VERSION_CAT",
    "POLICY_VERSION_SUNEUNG",
    "record_recommendation_treatment",
]
