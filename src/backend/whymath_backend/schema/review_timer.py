"""검수 세션 타이머 이벤트 계약(Pydantic) — HIT(CU당 인간 개입 시간) 계측기 (EOS-54).

설계 정본: `docs/standards/eos_verification_design_v1.md` §6 — 주 기준 KPI **HIT(중앙값 ≤4분·
P90 ≤8분)**의 측정 방법은 "검수 타이머 이벤트(시작·종료·중단) 전수 자동 수집"으로 **동결**돼
있다. 이 모듈이 그 이벤트의 검증 계약이다(★이 계측기가 없으면 12월 검증에서 잴 것이 없다 —
G1(9/27) 차단 조건, `eos_plan52_crosswalk_2026-09.md` §2 후보 #1).

이 Pydantic 모델은 검증·전송 계약이고, 영속 매핑은 `db/models/review_timer_event.py`(ORM)가
별도로 세운다 — `from_schema`/`to_schema` seam(`hint_usage.py` 동일 패턴·EOS-45 관례).

이벤트 계약(폐쇄 3종 — started/finished/aborted):
  - **started** — 검수 착수. 판정·실패코드·경과 전부 금지(착수 시점엔 존재하지 않는 사실).
  - **finished** — 검수 종결. `verdict`(approved|approved_with_edit|rejected) **필수** — 판정
    없는 종결은 없다. `approved_with_edit`(EOS-62)는 "사람이 손질해서 통과시켰다" — 무손질
    승인과 구분되지 않으면 승인율이 AI-first 실패를 가린다(ReviewVerdict 선언부 근거).
    `verdict=rejected`면 `failure_code`(F1~F8) **필수** — 설계서 §4 "모든 검수 반려는 8코드 중
    하나로 강제 분류(자유 텍스트 단독 금지)"의 함수 레벨 집행. 이 모듈이
    `GenerationFailureCode`(EOS-51 동결)의 첫 소비 지점 중 하나다.
  - **aborted** — 중단(이탈·보류). 판정 없음(판정이 있으면 finished다). 부분 경과는 기록 가능.

설계 판단(근거 병기):
  - `cu_slug` — CU 식별 축. CU는 신설 스키마 없이 기존 Problem 조합으로 표현한다(설계서 §3
    동결)이고, 검수 흐름의 공통 식별자는 slug다 — 실측: 코퍼스 JSONL 레코드(`slug` 키)·검수
    워크리스트(`needs_review_worklist.WorklistItem.slug`)·DB(`problem.slug` UNIQUE String(128))
    전부 slug 축. max_length=128은 `problem.slug` 폭과 일치.
  - `problem_id` — **nullable FK**(DB 계층). 검수 대상은 "적재된 problem"만이 아니다 —
    needs_review 후보는 `accepted_stored` 전이라 problem 행이 없다(orchestrator 실측). NOT NULL
    FK를 강제하면 적재 전 후보의 검수가 기록 불가 = 측정 실패를 스키마가 제조한다. 적재된
    CU만 채우고, 미적재 후보는 None(정직 — 가짜 id 생성 금지·`hint_id` 느슨 방침과 동계열).
  - `reviewer_id` — 검수 *행위자* 핸들(TEXT). **학생 소유 축이 아니다** — privacy 스윕
    (`test_erasure_plan_completeness`)의 소유 판정은 SEC-35 이후 *FK 산출물 검사 ∪ 계획 파생
    컬럼명*인데, 이 컬럼은 `user_profile.user_id` FK가 없고 `_ERASURE_PLAN`이 쓰는 이름도
    아니다. created_by·approved_by·reviewed_by류는 "콘텐츠 저작/검수 행위자"로 분류한다
    (그 파일 주석 실측). 기존 검수 라벨 형식(#841 `reviewed_by: "kiki"`)과 동형.
  - `elapsed_ms` — **nullable**(0 날조 금지·acceptance ④). 경과는 검수 도구(클라) 계측인데
    도구 강제 종료·크래시 복구 등 계측 실패 케이스가 구조적으로 존재한다. None=미측정 —
    finished인데 elapsed가 None이면 "판정은 있으나 HIT 미계측"으로 집계가 **분리 카운트**한다
    (`ops/hit_cu_metrics` — 0초 산입 금지). started에는 경과 자체가 금지(아직 잰 것이 없다).
  - `occurred_at`/`recorded_at` — 발생/수신 시각 분리(EOS-48 계약·`activity.py` event_time/
    event_at 동형). occurred_at=검수 도구 신고 발생 시각(None=미신고), recorded_at=매체 도달
    시각(DB는 server_default now()·JSONL은 append 시각 — writer가 스탬프).

개인정보 판정(실측 — 추측 금지): 이 이벤트는 **검수자 운영 텔레메트리**이지 학생 데이터가
아니다. user_id/student_id/target_user_id 컬럼이 없으므로 privacy 스윕
(`tests/backend/privacy/test_erasure_plan_completeness.py`)의 소유 축에 걸리지 않음을 실측
확인했고(green), `tests/backend/db/test_review_timer_event_orm.py`가 학생 축 컬럼 부재를
`test_defect_report_no_user_id.py`(RPT-01) 선례대로 동결한다. 따라서 erasure/retention/export
3종 배선은 **필요 없음**(배선하면 오히려 "검수자 텔레메트리를 학생 삭제권으로 지우는" 오배선).

집행 별항(정본화≠집행 — acceptance ③): 이 모듈은 함수 레벨 계약(rejected→failure_code
필수)을 집행한다. 사람 입력 경로 배선은 `EOS-78`(`harness/review_session` CLI)이 맡았고,
그 CLI가 반려 시 F1~F8 선택을 받을 때까지 진행하지 않음으로써 이 계약을 입력단까지 잇는다.
다만 강제는 **그 경로에 한정**된다 — 전 경로 강제는 검수 UI(ADMIN-07) 몫이며, 남은 간극은
`ops/hit_cu_metrics` 리포트가 적재율로 상시 드러낸다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whymath_backend.schema.enums import GenerationFailureCode, ReviewStatus

__all__ = [
    "VERDICT_APPROVED_WITH_EDIT",
    "ReviewTimerEvent",
    "ReviewTimerEventType",
    "ReviewVerdict",
    "review_status_for_verdict",
]


class ReviewTimerEventType(str, Enum):
    """검수 타이머 이벤트 3종 — 설계서 §6 "시작·종료·중단" 폐쇄 집합(추가 금지)."""

    STARTED = "started"
    """검수 착수 — 타이머 시작. 판정·실패코드·경과 없음."""

    FINISHED = "finished"
    """검수 종결 — 판정 3종 동반 필수. rejected면 failure_code 필수,
    approved_with_edit면 선택(권장)."""

    ABORTED = "aborted"
    """검수 중단 — 판정 없이 이탈·보류. 부분 경과는 기록 가능(있는 만큼만·날조 금지)."""


# ── 종결 판정 폐쇄 3종 (EOS-62) ────────────────────────────────────────────
# `approved` / `approved_with_edit` / `rejected`.
#
# 왜 `approved_with_edit`를 더했나
# --------------------------------
# 2값(approved/rejected)이던 시절, "그대로 통과한 CU"와 "사람이 5분 고쳐서 통과시킨 CU"가
# **같은 값**이었다. 그러면 HIT 중앙값 4분 + 승인율 93%가 "성공"으로 보이는데 승인분의
# 상당수가 손질된 것일 수 있고, 그 손질분은 **AI-first 전략의 실패 신호**다 — 즉 성공 지표가
# 실패를 가리는 구조였다(N4 갭 ③ · `docs/reviews/eos_validation_n1_n10_gap_review_2026-08-30.md`
# §3.4). 문서 §17이 제안한 5종 중 이 1종만 채택한다: `REGENERATE`는 Run 재생성 카운트
# (EOS-55)가, `ESCALATE`는 운영 절차가 담당하므로 스키마 확장은 최소로 둔다.
#
# ⚠️ `ReviewStatus`와 값 집합이 **더는 같지 않다**(2값 시절의 "부분집합·같은 문자열" 관계가
# 여기서 끝난다). `approved_with_edit`은 *검수 판정*의 해상도이지 *문항 노출 상태*가 아니며,
# `ReviewStatus`에는 추가하지 않는다 — 넣으면 노출 정책(§13.3 "approved 후 노출")이 흔들린다.
# 두 축을 잇는 유일한 정본 변환은 아래 `review_status_for_verdict()`다. 이 값을 그대로
# `problem.review_status`에 쓰면 `is_review_status_cleared`가 fail-closed로 False를 내
# **손질 승인된 CU가 조용히 노출되지 않는다** — 그 함정을 막는 것이 그 함수의 존재 이유다.
ReviewVerdict = Literal["approved", "approved_with_edit", "rejected"]

#: 손질 후 승인 — as-found(검수 전) 상태는 결함이었다는 뜻이다. 하류(골든 승격·실패분포)가
#: 이 값을 문자열로 탐침하므로 상수로 한 번만 적는다.
VERDICT_APPROVED_WITH_EDIT = "approved_with_edit"


def review_status_for_verdict(verdict: ReviewVerdict | str | None) -> ReviewStatus | None:
    """검수 판정 → 문항 노출 상태의 **단일 정본 변환**(두 축을 잇는 유일한 다리).

    `approved`도 `approved_with_edit`도 "검수를 통과했다"는 점에서는 같다 — 손질 여부는
    *생산성·품질 계측*의 축이지 *노출 가부*의 축이 아니다. 그러므로 둘 다 `ReviewStatus.APPROVED`로
    매핑한다. 손질 사실은 타이머 이벤트(`verdict`)에 남아 `ops/hit_cu_metrics`가 승인율을
    무손질/손질 포함으로 분리 보고한다 — 노출 상태를 깎아서 표현하지 않는다.

    이 함수가 없으면 각 호출부가 `verdict`를 그대로 `review_status`에 복사할 것이고,
    `is_review_status_cleared`는 `approved`만 True인 fail-closed 술어라 손질 승인된 CU가
    **무증상으로 노출에서 빠진다**(에러 없이 목록에서 사라진다). 어휘가 갈라진 순간부터
    그 복사는 버그이며, 변환을 여기 한 번만 두어 기계가 지키게 한다.

    반환 None = 판정 아님(`None` 입력 = 미판정). 어휘 밖 값은 추측하지 않고 `ValueError`다
    (상류가 확장됐는데 이 변환이 따라가지 않은 상태를 조용히 통과시키지 않는다).
    """
    if verdict is None:
        return None
    value = str(verdict)
    if value in ("approved", VERDICT_APPROVED_WITH_EDIT):
        return ReviewStatus.approved
    if value == "rejected":
        return ReviewStatus.rejected
    raise ValueError(f"어휘 밖 verdict {value!r} — ReviewVerdict 확장 시 이 변환도 함께 갱신하라")


class ReviewTimerEvent(BaseModel):
    """검수 타이머 이벤트 1건 — 한 검수 세션(sitting)의 시작/종료/중단 중 한 사건.

    한 CU(`cu_slug`)는 여러 세션(`review_session_id`)으로 검수될 수 있다(시작→중단→재시작→
    종결). CU당 HIT = 그 CU 전 세션의 계측 경과 합 — 집계 계약은 `ops/hit_cu_metrics` 정본.
    append-only: 이벤트는 사실 기록이며 수정·삭제하지 않는다(EOS-45/46 관례).
    """

    model_config = ConfigDict(
        extra="forbid",
        use_enum_values=True,
        str_strip_whitespace=True,
    )

    # ===== 기본 식별 =====
    event_id: uuid.UUID = Field(default_factory=uuid4, description="이벤트 PK (UUID)")
    review_session_id: uuid.UUID = Field(
        description="검수 세션(sitting) id — 같은 앉음의 started/finished/aborted가 공유하는 "
        "페어링 축(required). writer의 start가 발급하고 finish/abort가 재사용한다"
    )

    # ===== 검수 대상 CU =====
    cu_slug: str = Field(
        min_length=1,
        max_length=128,
        description="검수 대상 CU 식별 slug — 코퍼스 JSONL·워크리스트·problem.slug 공통 축"
        "(폭 128 = problem.slug String(128) 일치)",
    )
    problem_id: uuid.UUID | None = Field(
        default=None,
        description="적재된 CU의 problem FK(느슨 채움 — DB nullable FK). None = 미적재 후보"
        "(needs_review 등 accepted_stored 전) 또는 미확인. 가짜 id 생성 금지",
    )

    # ===== 검수 행위자 =====
    reviewer_id: str = Field(
        min_length=1,
        max_length=100,
        description="검수 행위자 핸들(#841 reviewed_by 선례 — 예: 'kiki'). 학생 소유 축이 "
        "아님(모듈 docstring 개인정보 판정)",
    )

    # ===== 이벤트 내용 =====
    event_type: ReviewTimerEventType = Field(
        description="이벤트 3종(started/finished/aborted) — 교차 필드 규칙은 validator가 강제"
    )
    verdict: ReviewVerdict | None = Field(
        default=None,
        description="종결 판정(approved|approved_with_edit|rejected) — finished에서만 필수, "
        "그 외 금지. ReviewStatus로의 변환은 review_status_for_verdict()가 정본(값 집합 불일치)",
    )
    failure_code: GenerationFailureCode | None = Field(
        default=None,
        description="결함코드 F1~F8(EOS-51 동결 enum 소비) — verdict=rejected면 필수"
        "(설계서 §4 강제 분류), approved_with_edit면 선택(권장·무엇을 손질했는가), 그 외 금지",
    )
    failure_note: str | None = Field(
        default=None,
        max_length=2000,
        description="결함 부기 자유 텍스트 — failure_code가 있을 때만 허용(§4: 자유 텍스트 "
        "단독 금지·부기만)",
    )

    # ===== 시간·계측 =====
    elapsed_ms: int | None = Field(
        default=None,
        ge=0,
        description="검수 도구 계측 경과(ms). None=미측정(계측 실패 — 0 날조 금지·집계에서 "
        "미계측 분리). started에는 금지(validator)",
    )
    occurred_at: datetime | None = Field(
        default=None,
        description="검수 도구 신고 *발생* 시각(EOS-48 발생/수신 분리). None=미신고",
    )
    recorded_at: datetime | None = Field(
        default=None,
        description="매체 *수신* 시각 — DB는 server_default now(), JSONL은 writer append가 "
        "스탬프. None = 적재 계층이 채움",
    )

    # ── 교차 필드 계약(이벤트 3종 × 판정/코드/경과) ──────────────────────
    @model_validator(mode="after")
    def _enforce_event_shape(self) -> Self:
        """이벤트 유형별 필수/금지 필드 강제 — "반려코드 없는 반려" 같은 미계측 판정을 차단.

        규칙(모듈 docstring 이벤트 계약과 1:1):
          started  → verdict·failure_code·failure_note·elapsed_ms 전부 금지.
          finished → verdict 필수(approved|approved_with_edit|rejected).
                     rejected           → failure_code **필수**(§4 강제 분류)
                     approved_with_edit → failure_code **허용·권장**(선택 — EOS-62 ②)
                     approved           → failure_code 금지(손질이 없었으므로 고칠 결함도 없다)
          aborted  → verdict·failure_code 금지(판정이 있으면 finished다).
          공통     → failure_note는 failure_code 없이 금지(자유 텍스트 단독 금지 — §4).

        **왜 손질 승인의 코드는 필수가 아닌가**(부기 규약 — EOS-62 ②): 반려는 "왜 못 쓰는가"가
        판정의 본체라 코드 없는 반려는 측정 불가다. 반면 손질 승인은 "통과했다"가 본체이고
        코드는 *무엇을 고쳤는가*의 부기다 — 필수로 걸면 코드를 고르기 애매한 손질(문장 다듬기
        등)에서 검수자가 아무 코드나 찍게 되고, 그 오염이 그대로 실패분포로 들어간다. 권장하되
        강제하지 않고, 미기재분은 집계가 **분리 카운트**한다(0으로 위장하지 않음).
        """
        # use_enum_values=True라 event_type은 str 값으로 저장돼 있다 — str Enum 동등 비교 안전.
        etype = self.event_type
        if etype == ReviewTimerEventType.STARTED:
            if self.verdict is not None or self.failure_code is not None:
                raise ValueError("started 이벤트에 판정/실패코드 금지 — 착수 시점엔 없는 사실")
            if self.elapsed_ms is not None:
                raise ValueError("started 이벤트에 elapsed_ms 금지 — 아직 잰 것이 없다")
        elif etype == ReviewTimerEventType.FINISHED:
            if self.verdict is None:
                raise ValueError(
                    "finished 이벤트는 verdict(approved|approved_with_edit|rejected) 필수 — "
                    "판정 없는 종결 없음"
                )
        else:  # ABORTED
            if self.verdict is not None:
                raise ValueError("aborted 이벤트에 verdict 금지 — 판정이 있으면 finished다")
            if self.failure_code is not None:
                raise ValueError("aborted 이벤트에 failure_code 금지 — 반려는 finished+rejected로")
        if self.verdict == "rejected" and self.failure_code is None:
            raise ValueError(
                "반려(rejected)는 failure_code(F1~F8) 필수 — §4 강제 분류(EOS-51 동결)"
            )
        if self.verdict in (None, "approved") and self.failure_code is not None:
            # 무손질 승인(approved)은 고친 것이 없다는 뜻이므로 결함코드가 붙을 수 없다 —
            # 손질했다면 값은 approved_with_edit여야 한다(해상도 갭이 되살아나는 경로 차단).
            raise ValueError(
                "failure_code는 verdict=rejected(필수)·approved_with_edit(선택)에서만 허용 — "
                "무손질 승인/미판정에 결함코드 금지"
            )
        if self.failure_note is not None and self.failure_code is None:
            raise ValueError(
                "failure_note는 failure_code 부기로만 허용 — 자유 텍스트 단독 금지(§4)"
            )
        return self
