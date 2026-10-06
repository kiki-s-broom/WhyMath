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

────────────────────────────────────────────────────────────────────────────
EOS-132: learner_state_basis — 이 추천이 본 LearnerState의 근거 식별자 (KPI ⑤)
────────────────────────────────────────────────────────────────────────────
`LearnerState`는 매 호출 조립되고 영속하지 않는다. 그래서 역추적 체인
`Recommendation → LearnerState → Assessment → Attempt → Problem`의 LearnerState 홉은 **이 기록에
남긴 근거**로만 되짚을 수 있다(`l2.learner_state.LearnerStateBasis` — 최신 숙달 행 키 · θ 스냅샷
id · 활성 가설 id · 조립 시각). 식별자와 시각만 싣는다(B1 불변). 근거가 비어 있으면 사유를 함께
적고(`absent`), 호출자가 근거를 넘기지 않으면 **키 자체를 넣지 않는다** — 역추적 게이트는 키 부재를
"모른다"로 읽고 끊김으로 센다(`ops/loop_kpi_gate.collect_traceability`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.evidence_event import EvidenceEvent
from whymath_backend.l2.irt import ThetaBoundary
from whymath_backend.l2.learner_state import LearnerStateBasis
from whymath_backend.l2.recommendation_contract import RecommendationReason
from whymath_backend.schema.enums import KnowledgeType

EVENT_TYPE_RECOMMENDATION_TREATMENT: str = "recommendation_render"
"""처치 — `/me/next-problem`이 학생에게 *실제로 반환한* 추천 문항 1건."""

# `meta` JSONB 키 — 비민감 메타만(B1). 집계가 이 키로 되읽을 수 있게 상수로 동결한다.
META_KEY_PROBLEM_ID: str = "problem_id"
META_KEY_THETA: str = "theta"
#: EOS-147 — 후보 점수(`candidates[]`)를 계산하는 데 쓴 θ. **추정 θ(`theta`)와 다를 때만** 남긴다
#: (전부 정답 이력에서 추천이 추정 θ가 아니라 표적 θ로 고른다). 키가 없으면 선택 θ = `theta`다 —
#: 이 식(`meta.get("selection_theta", meta["theta"])`)이 수정 전 기록까지 정확히 재현한다.
META_KEY_SELECTION_THETA: str = "selection_theta"
#: EOS-147 — 추정 θ가 MLE 발산 경계인가(`upper`=전부 정답·`lower`=전부 오답). 경계가 아니면(None)
#: 키를 넣지 않는다 — '없음'과 'null로 기록됨'을 구분. 발동률(전체 처치 중 이 키가 있는 비율·값별
#: 분포)을 소급 측정하는 재료다. 키가 없다고 θ가 ±4.0이 아니라는 뜻은 아니다(혼합 이력에서 MLE가
#: 범위를 넘어 클램프된 경우도 없다).
META_KEY_THETA_BOUNDARY: str = "theta_boundary"
#: EOS-39 — 코치가 도움(힌트 단계 2 이상)을 공급해 완료한 문항이라 선택용 응답에서 **실패 1건으로
#: 접힌 문항 수**. 0이면 키를 넣지 않는다 — 그래서 "키가 있는 처치 / 전체 처치"가 도움 채널의 발동률
#: 이다(CLAUDE.md "작동한 비율"). 값은 라벨이 코치 정책(숙달 라벨 '초보'·5회+ 막힘)에도 의존하므로
#: 학생이 도움을 요청한 횟수가 아니다(판정문 §2-2).
META_KEY_SELECTION_HELP_COUNT: str = "selection_help_count"
#: EOS-39 — 정답으로 센 완료 행 중 힌트 귀속(`used_hint`)이 미상(NULL)이라 도움 채널이 판정하지
#: 못한 수. 0이면 키를 넣지 않는다. 미상은 구조적이라(귀속 창을 모름·EOS-133 이전 행·API 클라이언트)
#: 이 비율이 높으면 도움 채널의 효과가 줄어든다(판정문 §4-1 — 정답으로 세는 대가).
META_KEY_SELECTION_HINT_UNKNOWN_COUNT: str = "selection_hint_unknown_count"
META_KEY_POOL_SIZE: str = "pool_size"
META_KEY_APPLIED_WEIGHTS: str = "applied_weights"
META_KEY_MODE: str = "mode"
META_KEY_GATE_REASON: str = "gate_reason"
META_KEY_CANDIDATES: str = "candidates"
META_KEY_POLICY_VERSION: str = "policy_version"
META_KEY_REASON: str = "reason"
#: EOS-124 — 정책 의도가 전달 콘텐츠로 어떻게 해소됐나(`IntentResolution` 값 문자열). 이 키가
#: 있어야 "정렬 재선택이 실제로 일한 비율"(served / 전체)을 사후에 셀 수 있다. 정렬을 적용하지
#: 않는 정책(수능)은 이 키를 넣지 않는다 — "없음"과 "null로 기록됨"을 구분한다.
META_KEY_INTENT_RESOLUTION: str = "intent_resolution"

#: EOS-24 — 상태 머신 지시의 처리 결과(`l2.learning_state_recommendation.StateDirectiveOutcome`
#: 값). 지시가 없던 추천에는 키 자체가 없다 — 그래서 "키가 있는 행 중 `applied` 비율"이 곧
#: 상태 머신 결정을 추천이 집행한 비율이다(CLAUDE.md "작동한 비율").
META_KEY_LEARNING_STATE_DIRECTIVE: str = "learning_state_directive"

#: EOS-132 — 이 추천이 소비한 `LearnerState`의 근거 식별자(`LearnerStateBasis.to_meta()` 형태).
#: 키가 없으면 "근거를 모른다"이다(역추적 끊김). 근거가 비어 있는 것은 키 안의 `absent` 사유로
#: 말한다 — 두 상태를 같은 글자로 쓰지 않는다(EOS-132 ⑧).
META_KEY_LEARNER_STATE_BASIS: str = "learner_state_basis"

# 정책(후보생성·선택 알고리즘) 식별자 — REC-11. 알고리즘이 바뀌면 새 문자열을 쓴다(과거
# 로그는 그대로 두고, 무엇이 바뀌었는지는 이 값으로 구분 — 오프라인 평가가 다른 정책의
# 로그를 섞어 판정하지 않게 한다).
#: `cat_v5`(EOS-39): 후보를 고르는 표적 θ를 만들 때 코치가 도움(힌트 단계 2 이상)을 공급해 완료한
#: 문항을 **실패 응답 1건으로 접는다**(`l2.irt.selection_evidence` — 판정문
#: `docs/reviews/eos39_app_help_completion_selection_judgment_2026-10-06.md`). 도움 완료가 있는
#: 이력의 선택이 바뀌므로 올린다 — `cat_v4` 로그와 섞으면 두 규칙이 한 정책으로 읽힌다. 킬 스위치
#: (`l2_selection_help_fold_enabled`)가 꺼진 동안의 기록도 이 번호를 단다 — 끈 사실은 처치 기록의
#: `selection_help_count` 키 부재와 구분되지 않으므로 소급 평가는 **배포 기간**과 함께 읽어야 한다.
#: `cat_v4`(EOS-147)는 위 규칙이 없는 판이다.
#: `cat_v4`(EOS-147): 전부 정답 이력에서 후보를 고르는 표적 θ가 추정 θ(4.0 클램프)가 아니라
#: `ability_for_selection`의 표적이 된다(첫 정답 뒤 은행 꼭대기로 뛰지 않는다). 그 외 이력의 선택은
#: `cat_v2`와 같지만, 전부 정답 이력의 로그가 두 규칙 아래 섞여 한 정책으로 읽히므로 올린다.
#: `cat_v3`은 병렬 태스크 EOS-33이 쓰는 번호라 건너뛴다 — 두 알고리즘이 같은 식별자를 쓰면
#: 소급 평가가 섞인다.
#: 이전 `cat_v2`(EOS-124): 숙달 구간 규칙이 선수 복귀·전진을 가리키고 그래프가 목표 개념을 내놓으면
#: 그 개념의 문항으로 **다시 고른다**(정렬 재선택). `cat_v1` 로그와 섞어 평가하면 두 선택 규칙이
#: 한 정책으로 읽힌다. 전환 시점 이후 기록은 `intent_resolution` 키도 함께 가진다.
POLICY_VERSION_CAT: str = "cat_v5"
"""기본 CAT(θ 근방 SQL 축소 + `select_weighted_item` 가중 정보량 최대) — `mode` 미지정."""
POLICY_VERSION_SUNEUNG: str = "suneung_v4"
"""수능 적응 추천(`recommend_suneung_index` — L6 진실 게이트 × IRT CAT) — `mode=suneung`.

`suneung_v4`(EOS-39): 수능 모드도 기본 CAT과 같은 표적 θ를 쓴다 — 도움을 쓴 문항을 실패 응답 1건으로
접은 선택용 응답이다(`cat_v5`와 같은 상태 객체 — 모드마다 θ 정의를 갈라 두지 않는다). 도움 완료가
있는 이력의 선택이 바뀌므로 올린다. `suneung_v3`은 그 규칙이 없는 판이다.

`suneung_v3`(EOS-147): 수능 모드도 기본 CAT과 같은 표적 θ를 쓴다 — 전부 정답 이력에서 후보를
고르는 θ가 추정 θ(4.0 클램프)가 아니라 `ability_for_selection`의 표적이다. 그 외 이력의 선택은
`suneung_v2`와 같지만 전부 정답 이력의 로그가 두 규칙 아래 섞여 한 정책으로 읽히므로 올린다.
`suneung_v2`는 EOS-31이 먼저 썼다(두 변경이 한 번호를 쓰면 소급 평가가 서로 다른 규칙을 섞는다).

`suneung_v2`(EOS-31): 수능 적격 게이트와 SQL 사전필터에 **출제 범위**(목표 학년도 수능의 성취기준
범위 — `l6/suneung/scope.py`)가 선결 조건으로 들어갔다. `suneung_v1`은 난이도 라벨만 있으면 초·중
성취기준 전용 문항도 적격이었으므로 후보 집합이 다르다 — 두 판의 로그를 섞어 평가하면 서로 다른
후보 규칙이 한 정책으로 읽힌다. 설명(reason·action·target)만 바꾼 EOS-25는 이 값을 올리지
않았다(그 변경은 선택 규칙이 아니었다)."""
POLICY_VERSION_CAT_STATE_REMEDIATION: str = "cat_v2_state_remediation"
"""EOS-24 — 상태 머신 R3(오개념 교정)를 집행한 추천: 후보를 교정 대상 개념으로 **제한**하고 학습
밴드로 고른다. 후보 생성 규칙이 기본 CAT과 다르므로 소급 평가가 둘을 섞지 않게 따로 적는다.
지시가 없거나 집행하지 못한 추천은 기본 CAT 규칙(`POLICY_VERSION_CAT` — 현행 `cat_v4`, EOS-124가
`cat_v2`로·EOS-147이 `cat_v4`로 올렸다)을 따른다. 이 식별자의 `v1`은 교정 경로 자신의 규칙 판이다 —
EOS-124는 교정 경로를 바꾸지 않았으므로(집행 시 정렬 재선택을 돌리지 않는다) 이 값도 바꾸지 않는다.

EOS-147은 이 값을 바꾸지 않았다 — 경로 규칙(후보 제한·이름표)이 그대로이고 두 경로는 오답이 있는
이력에서만 발동한다는 근거였다. **EOS-39가 `cat_v1_state_remediation`에서 올렸다**: 도움 접기는 오답
행이 있는 이력에서도 선택 θ를 바꾸고(오답 + 도움 완료 문항을 실패 1건으로 접는다), R3의 학습 밴드
가중(`recommendation_policy._combine_axes`의 `learning_band_weight(theta, item)`)이 그
선택 θ를 읽는다 — EOS-147의 근거("오답 이력에서는 경계 규칙이 서지 않는다")가 더는 성립하지
않는다. 경로 규칙(후보 제한·이름표)은 그대로이고 바뀐 것은 정렬·밴드의 θ다. (EOS-147이 적은 난이도
라벨 없는 문항의 오답 코너는 이제 그 코너만의 예외가 아니다.) 하한(−4.0) 대칭은 이 판에서도 R3에
대해 바꾸지 않았다 — 이월(판정문 §4-4).
`cat_v1_state_remediation`은 도움 접기 이전 판이다."""
POLICY_VERSION_CAT_STATE_UNDIAGNOSED: str = "cat_v3_state_undiagnosed"
"""EOS-26 — 상태 머신 R6(원인 미상 오답)를 집행한 추천: 후보를 오답 개념의 직접 선수(연속 첫
오답 — 선수 탐침) 또는 방금 틀린 개념(연속 두 번째 · 탐침 불가 폴백)으로 **제한**한다. 후보 생성
규칙이 기본 CAT과 다르므로 따로 적는다. 이름표·재선택은 기본 CAT의 `cat_v2`(EOS-124) 규칙 그대로라
`v2`였다 — R3 교정 경로와 달리 근거를 바꾸지 않았다. 제한하지 못한 R6(`anchor_unresolved`·
`no_candidate_in_concept`)는 기본 CAT 규칙을 따르므로 `POLICY_VERSION_CAT`이다.

EOS-147은 이 값을 바꾸지 않았다(오답 이력에서는 경계 규칙이 서지 않는다는 근거). **EOS-39가
`cat_v2_state_undiagnosed`에서 `cat_v3_state_undiagnosed`로 올렸다**: 도움 접기가 오답 행이 있는
이력의 선택 θ를 바꾸고 R6 제한 후보의 정렬이 그 θ를 읽는다 — 이유는 R3 판과 같다
(`POLICY_VERSION_CAT_STATE_REMEDIATION` docstring). `cat_v2_state_undiagnosed`는 도움 접기
이전 판이다."""

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
    selection_theta: float | None = None,
    theta_boundary: ThetaBoundary | None = None,
    selection_help_count: int = 0,
    selection_hint_unknown_count: int = 0,
    mode: str | None = None,
    gate_reason: str | None = None,
    candidates: list[tuple[uuid.UUID, float]] | None = None,
    policy_version: str | None = None,
    reason: RecommendationReason | None = None,
    intent_resolution: str | None = None,
    occurred_at: datetime | None = None,
    learning_session_id: uuid.UUID | None = None,
    learning_state_directive: str | None = None,
    learner_state_basis: LearnerStateBasis | None = None,
) -> EvidenceEvent:
    """`/me/next-problem`이 학생에게 실제로 반환한 추천 1건을 stage한다(commit 0).

    `session.add`만 하고 commit하지 않는다(`pedagogy_evidence.py` 관례 — 커밋 경계는
    호출자 책임). 호출자는 `problem_id`가 null이 아닐 때만(추천이 실제로 나갔을 때만)
    이 함수를 불러야 한다 — 가짜 처치 금지.

    `selection_theta`(EOS-147): 후보를 고르는 데 쓴 θ. `theta`(추정 θ)와 **다를 때만** meta에
    `selection_theta` 키로 남긴다 — None이거나 `theta`와 같으면 키를 넣지 않는다("없음"과 "null로
    기록됨"을 구분하는 기존 관례). 소급 평가는 `meta.get("selection_theta", meta["theta"])`로
    후보 점수를 재현한다.

    `theta_boundary`(EOS-147): 추정 θ가 MLE 발산 경계인가 — `upper`(전부 정답)·`lower`(전부 오답)
    문자열을 그대로 `theta_boundary` 키로 남긴다. None(경계 아님)이면 키를 넣지 않는다. 이 키는
    `selection_theta` 키와 독립이다 — `lower`는 선택 θ가 추정 θ와 같아 `selection_theta` 키 없이
    이 키만 남고, 표적이 상한에 막힌 `upper`도 마찬가지다. 키가 있는 처치의 비율·값별 분포가 경계
    규칙의 발동률이다(소급 측정 재료).

    `selection_help_count`·`selection_hint_unknown_count`(EOS-39): 도움 접기가 이 이력에 닿은 정도 —
    코치가 도움을 공급해 완료한 문항이라 선택용 응답에서 실패로 접힌 문항 수 · 정답으로 센 완료 중
    힌트 귀속이 미상인 수. **0이면 키를 넣지 않는다**("없음"과 "0으로 기록됨"을 구분하는 기존 관례
    — 키가 있는 처치의 비율이 곧 발동률이다). 음수는 호출 오류라 받지 않는다.

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

    `intent_resolution`(EOS-124): 정책 의도가 전달 콘텐츠로 어떻게 해소됐나(`l2.
    recommendation_policy.IntentResolution` 값). `l2.recommendation_policy`를 import하지 않고
    문자열로 받는 이유는 순환 참조다(그쪽이 이 모듈의 `POLICY_VERSION_CAT`을 import한다).

    `learning_state_directive`(EOS-24): 상태 머신이 이 추천을 지시했을 때 그 처리 결과
    (`applied`·`released_after_repeat`·…). 지시가 없었으면 None이고 키를 넣지 않는다.

    `learning_session_id`(EOS-131): 이 추천이 나간 실 학습 세션. `None`이면 세션 기록 실패
    경로로 보고 결합 불가 placeholder를 발급한다(모듈 docstring 참조 — 가짜 결합 금지).

    `learner_state_basis`(EOS-132): 이 추천이 소비한 `LearnerState`의 근거 식별자. None이면 키를
    넣지 않는다 — 역추적 게이트가 그 부재를 끊김으로 센다(모른다 ≠ 없었다).
    """
    meta: dict[str, Any] = {
        META_KEY_PROBLEM_ID: str(problem_id),
        META_KEY_THETA: theta,
        META_KEY_POOL_SIZE: pool_size,
        META_KEY_APPLIED_WEIGHTS: applied_weights,
    }
    # None인 선택 키는 아예 넣지 않는다 — "없음"과 "null로 기록됨"을 구분 가능하게.
    if selection_theta is not None and selection_theta != theta:
        meta[META_KEY_SELECTION_THETA] = selection_theta
    if theta_boundary is not None:
        meta[META_KEY_THETA_BOUNDARY] = theta_boundary
    if selection_help_count < 0 or selection_hint_unknown_count < 0:
        raise ValueError("selection_help_count·selection_hint_unknown_count는 음수일 수 없다")
    if selection_help_count > 0:
        meta[META_KEY_SELECTION_HELP_COUNT] = selection_help_count
    if selection_hint_unknown_count > 0:
        meta[META_KEY_SELECTION_HINT_UNKNOWN_COUNT] = selection_hint_unknown_count
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
    if intent_resolution is not None:
        meta[META_KEY_INTENT_RESOLUTION] = intent_resolution

    if learning_state_directive is not None:
        meta[META_KEY_LEARNING_STATE_DIRECTIVE] = learning_state_directive
    if learner_state_basis is not None:
        meta[META_KEY_LEARNER_STATE_BASIS] = learner_state_basis.to_meta()

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
    "META_KEY_INTENT_RESOLUTION",
    "META_KEY_LEARNER_STATE_BASIS",
    "META_KEY_LEARNING_STATE_DIRECTIVE",
    "META_KEY_MODE",
    "META_KEY_POLICY_VERSION",
    "META_KEY_POOL_SIZE",
    "META_KEY_PROBLEM_ID",
    "META_KEY_REASON",
    "META_KEY_SELECTION_HELP_COUNT",
    "META_KEY_SELECTION_HINT_UNKNOWN_COUNT",
    "META_KEY_SELECTION_THETA",
    "META_KEY_THETA",
    "META_KEY_THETA_BOUNDARY",
    "POLICY_VERSION_CAT",
    "POLICY_VERSION_CAT_STATE_REMEDIATION",
    "POLICY_VERSION_CAT_STATE_UNDIAGNOSED",
    "POLICY_VERSION_SUNEUNG",
    "record_recommendation_treatment",
]
