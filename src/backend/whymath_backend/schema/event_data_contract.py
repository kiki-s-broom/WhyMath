"""이벤트 페이로드 타입별 계약 단일 진실원 — invariant ⑫("event_data 자유 JSONB 금지·타입별 계약").

`AttemptEvent.event_data`는 물리적으론 `dict[str, Any]` JSONB지만, *생산되는* EventType은
페이로드 모양이 계약으로 고정돼야 한다(자유형 방치 시 오타·키 드리프트가 조용히 축적 →
분석 소비처가 깨진다). 이 모듈이 그 계약의 *단일 출처*다 — `render_contract`·`notation_contract`
선례(계약 단일원 + 거버넌스 테스트)를 백엔드 내부(교차언어 소비처 0이라 JSON golden 대신
Python 네이티브)로 실현한다.

경계(의도적 비구속):
- **휴면 5종**(문제읽기·조건분석·그래프그리기·계산·지움)은 생산자가 아직 0이라 페이로드 모양이
  미지 → 계약으로 구속하지 않는다(`_CONTRACT_EXEMPT`, premature 회피). `막힘`·`힌트요청`·
  `답입력`은 S3-16에서 생산자가 생겨 계약으로 편입됐다(신규 EventType 추가 아님·소생).
- **`시각화조작.payload`**(내부)는 조작 종류별로 달라 자유형을 *의도적으로* 유지한다 —
  봉투(interaction·payload·client_at·concept_id·scene_id)만 계약하고 내부는 열어 둔다.

강제 지점: 생산자(`api/coach.py`·`api/interactions.py`·`l2/attempt_skill_event.py`)가
`build_event_data`를 경유해 dict를
만든다 → extra="forbid" 모델이 stray key를 즉시 거부하므로 produce 좌석에서 드리프트가
구조적으로 불가능해진다(런타임 재작성·validator·DB 제약 없이 seam 1곳에서 차단).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.schema.enums import EventType


class _EventPayload(BaseModel):
    """계약 페이로드 공통 베이스 — stray key 금지(자유 JSONB 차단의 핵심)."""

    model_config = ConfigDict(extra="forbid")


class VerifyEventData(_EventPayload):
    """`검산결과` 페이로드 — WH-1 검산(verify) 결과·하네스 지표 ①(verify_pass_rate)의 입력.

    `passed`는 하네스가 실제로 읽는 유일 활성 키(`wh1_evaluation.py`)다. `error_kind`는
    거짓 수치관계의 종류(현재 write-only·향후 오개념 분석 입력)로 통과 시 None이다 →
    Optional. 픽스처가 `{passed}`만 써도 이 계약으로 정규화하면 `error_kind=None`이 되어
    관측된 드리프트가 무해화된다.

    S3-03(수능 MVP): `mode`·`persona`는 이 검산결과가 *어느 응용 모드/대상 페르소나* 세션에서
    나왔는지 표식하는 *선택* 태그다(예: mode="suneung"). 둘 다 미지정(None)이면 mode-agnostic
    (기존 동작 완전 불변)이라 기존 픽스처·라이브 이벤트가 무손상이다. 측정 계층
    (`wh1_evaluation`)이 `event_data->>'mode'`로 mode-scoped 집계를 낼 수 있게 하는 *데이터
    운반* 필드다(완전한 mode별 집계는 후속 S3-04). 값은 문자열(Literal/enum의 *값*)로 싣는다.

    S4-19(라이브 3상태 적재·2026-08-10): `n_correct`·`n_incorrect`·`n_unverifiable`·
    `unverified_ratio`·`first_incorrect_index`·`ocr_gated`는 코치가 응답에만 싣고 버리던
    `verify_solution` 3상태 결과(`l3/verify_solution.py` `SolutionVerificationResult`)의
    *비식별 요약*을 병기하는 선택 필드다 — 재계산 0(핸들러가 이미 쥔 값 운반)·binary `passed`는
    불변(두 검증기의 이중 회계). 전건 None=미지정(구판 이벤트 또는 단계 미제출/검증 미실행 턴)
    으로 기존 동작 완전 불변이고, 0은 실측 0(전이 0회 제출)이라 None과 구분한다(S3-07 규약).
    `n_transitions`는 싣지 않는다 — 세 카운트의 합이 항상 n_transitions와 같음을
    `SolutionVerificationResult`가 보장하므로 재구성 가능하다. `steps`(reason 텍스트)는 절대
    싣지 않는다 — 비식별 정수/비율/인덱스/불리언만(`wh1_shadow.py` 관측 레코드 규약 동형).

    MATH-03(2026-08-11): `unverifiable_by_reason`은 n_unverifiable의 *사유 코드별* 세분
    (폐쇄 7종 코드 → 건수)이다 — "학생이 실제로 어디서 막히는가"의 첫 실측 데이터이며 S4-19와
    같은 additive optional 규약(None=구판·비식별 코드/정수만)을 따른다.
    """

    passed: bool = Field(..., description="거짓 수치관계 미적발(통과)=True·적발=False")
    error_kind: str | None = Field(
        default=None, description="적발된 오류 종류(통과 시 None·현재 write-only)"
    )
    mode: str | None = Field(
        default=None,
        description="응용 모드 태그(예: 'suneung'). None=미지정(mode-agnostic·기존 동작 불변).",
    )
    persona: str | None = Field(
        default=None,
        description="대상 페르소나 태그(예: 'A_일반고고3'). None=미지정(선택·후속 집계).",
    )
    n_correct: int | None = Field(
        default=None,
        description=(
            "S4-19: verify_solution correct 전이 수. None=미지정(구판/검증 미실행·기존 동작 "
            "불변)·0=실측 0(전이 0회 제출) — None과 0을 구분한다."
        ),
    )
    n_incorrect: int | None = Field(
        default=None,
        description="S4-19: incorrect 전이 수. None=미지정(구판/검증 미실행·기존 동작 불변).",
    )
    n_unverifiable: int | None = Field(
        default=None,
        description="S4-19: unverifiable 전이 수. None=미지정(구판/검증 미실행·기존 동작 불변).",
    )
    unverifiable_by_reason: dict[str, int] | None = Field(
        default=None,
        description=(
            "MATH-03: unverifiable 전이의 *사유 코드별* 카운트(키=VerifyStepReasonCode 값·폐쇄 "
            "7종·값 합=n_unverifiable). None=미지정(구판/검증 미실행·기존 동작 불변)·{}=검증 "
            "실행·보류 0. 비식별 폐쇄 코드·정수만 — 자유문 reason·steps 미적재(S4-19 규약 동형). "
            "parse_error 비중이 MATH-01(표기 권위)·자연표기 확장(math_engine_gap_review.md "
            "§5-③)의 발화 조건 데이터다."
        ),
    )
    unverified_ratio: float | None = Field(
        default=None,
        description=(
            "S4-19: 검증 불가 비율(n_unverifiable/n_transitions·전이 0이면 0.0). "
            "None=미지정(구판/검증 미실행·기존 동작 불변)."
        ),
    )
    first_incorrect_index: int | None = Field(
        default=None,
        description=(
            "S4-19: 첫 incorrect 전이 인덱스(0-based). None=미지정 *또는* incorrect 없음 — "
            "둘은 n_incorrect(None vs 0)로 구분한다."
        ),
    )
    ocr_gated: bool | None = Field(
        default=None,
        description=(
            "S4-19: 저신뢰 OCR(<0.8)로 step-incorrect 신호를 코칭 결정에서 보류했는지"
            "(SolutionCoaching.verification_ocr_gated 운반). None=미지정(구판/검증 미실행)."
        ),
    )


class HintEventData(_EventPayload):
    """`힌트제공` 페이로드 — AI가 *제공*한 노출량(supply)·하네스 지표 ⑤(도움 감소 곡선)의 입력.

    `hint_level`은 하네스가 읽는 유일 키다. 값 범위(1~4)는 계약이 아니라 *생산 로직*
    (`decision.hint_level`)의 책임 — 여기선 키·타입만 고정한다(범위 구속은 기존 동작 변경
    위험이라 도입하지 않음).

    S3-03(수능 MVP): `mode`·`persona`는 `VerifyEventData`와 *동형* 선택 태그다 — 이 힌트제공이
    어느 응용 모드/페르소나 세션에서 나왔는지 표식한다. 둘 다 None이면 mode-agnostic(기존 동작
    완전 불변). ⑤(도움 감소 곡선)·⑧(도달 깊이)의 mode-scoped 집계 데이터 운반용.
    """

    hint_level: int = Field(..., description="AI 제공 힌트 노출량(1~4·supply 신호)")
    mode: str | None = Field(
        default=None,
        description="응용 모드 태그(예: 'suneung'). None=미지정(mode-agnostic·기존 동작 불변).",
    )
    persona: str | None = Field(
        default=None,
        description="대상 페르소나 태그(예: 'A_일반고고3'). None=미지정(선택·후속 집계).",
    )
    client_state_mismatch: bool = Field(
        default=False,
        description=(
            "PED-04 D2: 이 턴에서 클라 제출 `polya_state`가 서버 파생 상태와 어긋났는지. "
            "불일치율을 *집계 가능한* 형태로 남기기 위한 태그다 — 로그로만 두면 측정이 불가능하고, "
            "신규 EventType은 PG enum ALTER(마이그레이션)를 부르므로 JSONB 페이로드에 싣는다. "
            "기본 False라 기존 이벤트·픽스처와 호환."
        ),
    )
    reveal_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "S4-11: 이 턴에 **검수 통과 graded 힌트가 실제로 서빙됐을 때** 그 힌트의 노출 점수"
            "(0~1·`l4.hint_content.models.compute_reveal_score` 정의). KPI '답 미루기 도달 깊이 "
            "2.5+'의 정밀화 신호(깊이 환산 = 3×점수) — `hint_level`은 *결정된* 단계, 이 값은 "
            "*전달된* 노출이다. None=이 턴에 카탈로그 힌트 미서빙(정적 템플릿만 — 문제 특화 노출이 "
            "없으므로 0으로 날조하지 않는다) 또는 구판 이벤트."
        ),
    )
    hint_id: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "S4-11: 서빙된 카탈로그 힌트 ID(`hints.hint_id` — 결정론 생성 자리 키). "
            "None=미서빙. 식별자일 뿐 본문이 아니다(본문은 이벤트에 싣지 않는다)."
        ),
    )


class DemandEventData(_EventPayload):
    """`힌트요청` 페이로드 — 학생이 *요청*한 도움 demand 신호(S3-16, 지표 ⑫ 분자 입력).

    `HintEventData`(supply)와 대칭이지만 값 필드(hint_level)가 없다 — `힌트요청`은 발생
    자체가 신호인 단순 카운트 이벤트라 `mode`·`persona`(선택 태그)만 싣는다. `l4.hint_deferral.
    is_answer_demand`가 True일 때만 생산되며, 좌절 신호(`_FRUSTRATION_TOKENS`)는 포함하지
    않는다(답을 직접 요구하는 명시적 신호만 demand로 집계 — 좌절은 범위 밖 후속).
    """

    mode: str | None = Field(
        default=None,
        description="응용 모드 태그(예: 'suneung'). None=미지정(mode-agnostic·기존 동작 불변).",
    )
    persona: str | None = Field(
        default=None,
        description="대상 페르소나 태그(예: 'A_일반고고3'). None=미지정(선택·후속 집계).",
    )


class StuckEventData(_EventPayload):
    """`막힘` 페이로드 — 5회+ 막힘 임계 도달 신호(S3-16, 지표 ⑧ 형제 관측 좌석).

    `turn_count`는 `decide_hint_level`이 이미 계산해 둔 값(재계산 아님)을 그대로 싣는다 —
    `l4.hint_deferral.is_stuck_turn_count`가 True(turn_count≥5)일 때만 생산된다. `mode`·
    `persona`는 `HintEventData`와 동형 선택 태그.
    """

    turn_count: int = Field(..., description="현재 단계서 누적 턴 수(임계 도달 시점의 실측값).")
    mode: str | None = Field(
        default=None,
        description="응용 모드 태그(예: 'suneung'). None=미지정(mode-agnostic·기존 동작 불변).",
    )
    persona: str | None = Field(
        default=None,
        description="대상 페르소나 태그(예: 'A_일반고고3'). None=미지정(선택·후속 집계).",
    )


class ResponseLatencyEventData(_EventPayload):
    """`답입력` 페이로드 — 서버 기준 응답 지연 신호(S3-16, 행동 텔레메트리 관측 좌석).

    `server_latency_ms`는 직전 학생 턴(server `spoken_at`)과 이번 제출 시각의 차다 — 서버
    시각만 쓰므로 클라 신뢰가 불필요하고 조작 불가하다. 이전 학생 턴이 없으면(새 dialogue의
    첫 턴) 기준선이 없어 행 자체가 생산되지 않으므로(날조 회피) 실제로는 항상 값이 채워진 채
    적재된다 — None 허용은 방어적 여유(타입 안전)일 뿐이다. `mode`·`persona`는 형제 페이로드와
    동형 선택 태그.
    """

    server_latency_ms: int | None = Field(
        default=None, description="직전 학생 턴 대비 서버 기준 응답 지연(ms). 기준선 없으면 None."
    )
    mode: str | None = Field(
        default=None,
        description="응용 모드 태그(예: 'suneung'). None=미지정(mode-agnostic·기존 동작 불변).",
    )
    persona: str | None = Field(
        default=None,
        description="대상 페르소나 태그(예: 'A_일반고고3'). None=미지정(선택·후속 집계).",
    )


class InteractionEventData(_EventPayload):
    """`시각화조작` 페이로드 봉투 — L5 탐구적 조작의 컨텍스트(슬라이스 96-J).

    봉투 5키만 계약한다. 내부 `payload`는 조작 종류(param_change·surface_range 등)별로
    모양이 달라 `dict[str, Any]` 자유형을 *의도적으로* 유지한다 — 봉투 타이핑과 내부 자유는
    서로 다른 계층(수집 게이트는 봉투만 안다).
    """

    interaction: str = Field(..., description="조작 종류(InteractionEventIn.type)")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="조작 세부(자유형·의도적 비구속)"
    )
    client_at: int | None = Field(default=None, description="클라이언트 발생 시각(epoch ms·선택)")
    concept_id: str | None = Field(default=None, description="탐구 중 개념(약점개념 scene·선택)")
    scene_id: str | None = Field(default=None, description="조작이 일어난 학습 장면(선택)")


class AttemptedEventData(_EventPayload):
    """`문제시도` 페이로드 — 채점 확정 1건의 비식별 봉투(EOS-57).

    **해소된 스킬 배열은 여기 담기지 않는다** — `attempt_event.skill_ids`(1급 컬럼)가 정본
    좌석이다. 조인·집계 축을 JSONB에 묻으면 "작동한 비율" 집계가 매번 JSON 파싱이 되고,
    12월 데이터의 소급 불가 축이 자유형에 섞인다. 이 페이로드는 그 컬럼을 *읽을 때 필요한
    맥락*(어느 채점 경로에서·어떤 판정으로 나온 기록인가)만 계약한다.

    `source`는 채점 경로를 가르는 폐쇄 라벨(`AttemptSource` 3종)이다 — 한쪽 경로에만 writer가
    배선되면 기록률 리포트가 경로별 분모로 그것을 즉시 드러낸다(한 경로 누락이 전체 평균에
    희석돼 보이지 않는 것을 막는다). `is_correct`는 채점 결과 불리언(비식별 — 학생 답안 원문은
    싣지 않는다·S4-19 관측 레코드 규약 동형).
    """

    is_correct: bool = Field(
        ..., description="채점 결과(서버 판정 또는 클라 자가보고 — source로 구분)"
    )
    source: str = Field(
        ...,
        description="채점 경로 라벨(AttemptSource 값: attempt_submit=자가보고 v1 · "
        "coach_completion=코치 서버검증 완료 · coach_wrong_submission=코치 서버 판정 오답 "
        "최초 제출). 경로별 기록률 분모.",
    )


# 생산되는 EventType → 페이로드 계약. 이 7종만 코드가 실제로 event_data를 쓴다(S3-16: 막힘·
# 힌트요청·답입력 3종이 휴면에서 편입 · EOS-57: 문제시도 신규 편입).
EVENT_DATA_CONTRACT: dict[EventType, type[_EventPayload]] = {
    EventType.검산결과: VerifyEventData,
    EventType.힌트제공: HintEventData,
    EventType.시각화조작: InteractionEventData,
    EventType.막힘: StuckEventData,
    EventType.힌트요청: DemandEventData,
    EventType.답입력: ResponseLatencyEventData,
    EventType.문제시도: AttemptedEventData,
}

# 휴면(생산자 0) EventType — 페이로드 모양 미지라 계약에서 *의도적으로* 제외(premature 회피).
# 계약 ∪ 면제 == 전체 EventType 을 거버넌스 테스트가 고정한다(분류 누락 방지).
CONTRACT_EXEMPT_EVENT_TYPES: frozenset[EventType] = frozenset(
    et for et in EventType if et not in EVENT_DATA_CONTRACT
)


def build_event_data(event_type: EventType, **payload: Any) -> dict[str, Any]:
    """계약을 경유해 `event_data` dict를 만든다 — 생산 좌석의 단일 강제 지점.

    계약 있는 EventType은 해당 모델로 검증(extra="forbid" → stray key 거부·타입 강제)한 뒤
    `model_dump()`한다. 계약 없는(휴면) EventType에 이 함수를 쓰는 것은 오용이므로
    `KeyError`로 막는다(휴면 이벤트는 아직 생산 경로가 없어야 한다).
    """
    model = EVENT_DATA_CONTRACT.get(event_type)
    if model is None:
        raise KeyError(
            f"{event_type!r}는 계약이 없는(휴면) EventType — build_event_data 대상 아님. "
            f"생산 대상은 {sorted(e.value for e in EVENT_DATA_CONTRACT)} 뿐."
        )
    return model(**payload).model_dump()
