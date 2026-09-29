"""WH-1 튜터링 하네스 0단계 — 대리 지표 7종 베이스라인 좌석.

설계 정본: `docs/architecture/04a_wh1_tutoring_harness.md` §8.4. WH-1(소크라테스 튜터링
하네스) 도입의 **0단계**는 "측정 없는 도입 없음"(설계안 제1원칙)에 따라 *대리 지표 7종*을
계측하는 것이다. 산출물은 **"커버리지 맵 + 베이스라인 수치"** — 무엇을 *지금* 잴 수 있고,
무엇이 *아직* 못 재는지를 한 번에 보여 주는 골격이다.

정직성 원칙(CLAUDE.md "확실하지 않을 때 자신 있게 말함 금지"·설계안 "측정 없는 도입 없음"):
  현재 코드/데이터로 *계측 가능한* 지표만 실값으로 내고, *미계측* 지표는 **가짜 0/stub을
  내지 않는다**. 각 지표는 `value(float|None)` + `status(MetricStatus)` + `note(한국어)`로
  구성해, 미계측 지표는 `value=None` + 상태 enum + "무엇이 필요한지"로 갭을 가시화한다. 이
  좌석 자체가 *측정 인프라의 골격*이며, 아직 무엇이 계측 불가인지를 정직하게 드러내는 게
  목적이다(0/stub은 날조다).

7종 대리 지표 커버리지(설계안 §8.4):
  ① verify 통과율          — 🟢 MEASURED/NO_DATA: attempt_event(event_type=검산결과)의
                             passed=거짓 수치관계 *미적발* 비율(binary 검산·3-state 아님).
                             S4-19: 같은 이벤트에 병기 적재된 verify_solution 3상태 카운트의
                             파생 회계(`compute_step_verification_accounting`)가 이중 회계로
                             병존한다 — SurrogateMetrics 밖 내부 전용(학생 라우트 비노출).
  ② 진단-실제 오개념 일치율 — 🟡 MEASURED(오프라인)/NO_DATA: 라벨 프로브(틀린 진술→expected_id
                             오개념)에 substring 매처 `diagnose` top-1 recall(오프라인 진단정확도).
                             **LIVE 학생별 ground-truth가 아니라 시스템 진단엔진 품질 지표**(전
                             user 동일값·user/기간 무관). LIVE per-user 일치율은 문항-오개념 태깅·
                             attempt별 진단 기록 부재로 여전히 데이터 기반 없음(후속). substring은
                             보수적 기준선(의미 매처는 더 높은 recall이나 임베딩 의존)·FP율/
                             precision은 semantic_eval 별도(recall 프로브만)·프로브 0건이면 NO_DATA.
  ③ 세션 완주율            — 🟢 MEASURED: LearningSession.ended_at NOT NULL 비율.
  ④ 턴당 토큰              — 🟡 MEASURED/NO_DATA: Dialogue.total_tokens/total_turns 평균.
  ⑤ 도움 감소 곡선         — 🟡 MEASURED/NO_DATA: attempt_event(event_type=힌트제공)의
                             hint_level 시계열 OLS 기울기(음수=도움 감소). raw ⑤는 R15 미반영
                             이나, *파생 결합 판정* `help_reduction_validated`(R15)가 정답률
                             추세(ProblemAttempt.is_correct OLS)·**문항 난이도 추세**(Problem의
                             보정 b/휴리스틱 b OLS)와 교차해 진짜 개선 vs 교정기 함정(힌트
                             회피)·**쉬운 문제 회피(난이도↓로 정답률 유지)**를 가린다(새 적재
                             0·기존 신호 결합만). 난이도 추세는 R15의 *부분* 정밀화(난이도 회피
                             1종 추가)일 뿐 — 이탈/무작위/세션 정렬 등 다른 gaming은 여전히 미반영.
  ⑥ 보정 점수(Brier)      — 🟢 MEASURED/NO_DATA: ProblemAttempt.confidence_self_reported(0~1
                             자기보고 확신도=예측) vs is_correct(실제 정오답)의 Brier
                             score=mean((confidence−is_correct)²)(낮을수록 잘 보정). 유효
                             쌍이 `_MIN_CALIBRATION_SAMPLES` 미만이면 NO_DATA(종단 노이즈
                             회피). `POST /v1/me/attempts`가 confidence+result를 동시 수집해
                             ProblemAttempt에 이미 적재 — 새 도구·새 수집 불요(기존 필드 파생만).
  ⑦ 전이 점수             — 🟡 MEASURED(근사)/NO_DATA: *근사 전이 점수*. 같은 시그니처 패턴
                             (`Problem.signature_patterns`)·**다른 problem_id**·사전 노출 후
                             **초견(첫 시도) 정답률**. = "이 패턴을 다른 문항에서 이미 만난 뒤
                             *새* 동형 문항을 처음 풀어 맞혔는가". **설계 §11.5 완전판
                             (assign_transfer_probe·노드 BKT≥0.95 + 2주 후 자동 출제)과 다름**
                             — 전이 프로브 마킹/스케줄 도구가 미구현이라 *풀이 이력*에서 근사한다
                             (표면 상이는 *다른 problem_id*로 근사·심층구조 동일성은 패턴 태그에
                             의존·BKT 숙달 게이팅 미반영). 전이 프로브가 `_MIN_TRANSFER_PROBES`
                             미만이면 NO_DATA(날조 0)·후속은 마킹/스케줄 도구.

S3 세션 대리 지표 4종 추가(`status_roadmap_2026-07.md` §3): 기존 7종과 *동일 스코프*
(user/시간창 집계·세션별 분해는 후속)로 **원천 신호를 재사용**해 편입한다(새 적재·마이그레이션
0). ⑧⑨⑩은 기존 라이브 신호 재사용, ⑪은 클라이언트 보고 resolution writer 편입분:
  ⑧ 답 미루기 도달 깊이   — 🟢 MEASURED/NO_DATA: ⑤와 *동일* 힌트제공 hint_level을 *기울기가
                            아니라 도달 깊이*(평균·최대)로 집계. 게이밍(힌트 회피로 낮은 레벨
                            유지)은 R15(`help_reduction_validated`)가 이미 교차 방어 — note에
                            캐비엇·R15 참조를 정직 표기(단독 해석 금지).
                            S4-11: 같은 힌트제공 행의 `reveal_score`(검수 graded 힌트가 *실제로
                            서빙된* 턴만 기록)를 note에 병기 — 기록 비율·평균·깊이 환산(3×).
                            value(평균 hint_level)는 불변(KPI 정의 불변·정밀화는 note).
  ⑨ BKT 숙달 증가율       — 🟢 MEASURED/NO_DATA: `ConceptMasteryHistory` (user,concept)별 첫→
                            마지막 mastery 차의 평균(증가 *방향·크기*). measured_at 간격으로
                            나눈 *시간 정규화 rate*는 아님(후속)·그룹당 최소 `_MIN_MASTERY_
                            POINTS`점 요구(가짜 0 금지).
  ⑩ 오개념 해소율         — 🟢 MEASURED/NO_DATA: `MisconceptionHypothesisRecord`의 is_active=
                            false 비율(가지치기·비활성화=*해소 근사*). 전용 resolved_at 컬럼
                            부재라 "학습적 해소"와 "stale 정리"를 구분 못 함(후속)·note 정직 표기.
  ⑪ 스스로 풀이 도달율     — 🟢 MEASURED/NO_DATA: `Dialogue.resolution`이 `학생자력해결`인 비율
                            (분모=resolution 채워진 세션). resolution은 **클라이언트 보고**
                            (`PATCH /v1/me/dialogues/{id}/end`가 적재·⑥ 자기보고 확신도 동형)
                            로 편입 — 서버가 신호로 판정하지 않는다(정답성·hint_level의 dialogue
                            귀속·포기 영속은 후속). `Socratic유도성공`은 별개 축(후속 분해 가능).

S3-16 편입(행동 텔레메트리 생산자 좌석 — `docs/architecture/ai_tutor_module_gap_review.md`
§3 D4): 휴면이던 `힌트요청`(demand) 이벤트가 생산자를 얻으며 ⑤(도움 감소)와 형제 좌석을 연다.
  ⑮ 도움 요청 대 제공 비   — 🟢 MEASURED/NO_DATA: attempt_event(힌트요청)/attempt_event(힌트
                            제공) 개수 비 — ⑤와 *동일 scope*(user/시간창/mode). supply(힌트
                            제공) 0건이면 NO_DATA(분모 0 방지·가짜 0 금지) — 힌트제공 0이면 ⑤⑧도
                            이미 NO_DATA이므로 이 지표만 홀로 값을 내지 않는다(일관성). demand=0·
                            supply>0이면 ratio=0.0(MEASURED·실측 0·날조 아님).

계층 메모(CLAUDE.md 7계층·설계안 §1): WH-1 하네스는 *새 계층이 아니라 횡단 인프라*다. 본
모듈은 L1(활동 로그 `LearningSession`·`AttemptEvent`)·L2(`ConceptMasteryHistory`)·L4(오개념
가설)·L2/L5(대화 `Dialogue`) 데이터를 *조회만* 하고(역방향 의존 없음·ORM/쿼리빌더만·원시 SQL
문자열 회피), 노출은 L5(`api/me`)가 담당한다.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Float, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.db.models.activity import (
    AttemptEvent,
    LearningSession,
    ProblemAttempt,
)
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.dialogue import Dialogue, DialogueTurn
from whymath_backend.db.models.misconception_hypothesis import (
    MisconceptionHypothesisRecord,
)
from whymath_backend.db.models.problem import Problem
from whymath_backend.l2.ability_estimation import resolve_item_difficulty_b
from whymath_backend.l2.prerequisite_recommendation import (
    recommend_prerequisite_gaps_detailed,
)
from whymath_backend.l4.hint_content.models import reveal_depth_equivalent
from whymath_backend.l4.lthc.adapt import _MASTERED_THRESHOLD
from whymath_backend.l4.misconception.probes import compute_diagnostic_recall
from whymath_backend.l4.turn_meta import REACHABLE_STRATEGIES
from whymath_backend.schema.enums import EventType, Resolution, SignaturePattern

__all__ = [
    "HelpReductionValidation",
    "Metric",
    "MetricStatus",
    "R15Verdict",
    "StepVerificationAccounting",
    "SurrogateMetrics",
    "compute_step_verification_accounting",
    "compute_wh1_surrogate_metrics",
]


# ⑤ 도움 감소 곡선 OLS 기울기의 *최소 종단 표본*. 이보다 적으면 NO_DATA(날조 회피).
# 종단 지표는 점이 2개뿐이면 기울기가 의미를 갖지 못하므로(과적합·노이즈) 최소 3점을 요구한다.
_MIN_SLOPE_POINTS = 3

# ⑥ 보정 점수(Brier)의 *최소 유효 쌍 수*. (confidence_self_reported, is_correct) 둘 다 채워진
# ProblemAttempt 쌍이 이보다 적으면 NO_DATA(가짜 0/Brier 금지). Brier는 평균이라 N>=1이면
# 값 자체는 나오지만, 표본이 한두 개면 종단 노이즈로 보정 추세를 오도하므로 최소 5쌍을 요구한다.
_MIN_CALIBRATION_SAMPLES = 5

# ⑦ 근사 전이 점수의 *최소 전이 프로브 수*. 전이 프로브(같은 시그니처 패턴·다른 problem_id·
# 사전 노출 후 초견(첫 시도))가 이보다 적으면 NO_DATA(가짜 0/정답률 금지). 정답률은 평균이라
# N>=1이면 값은 나오지만, 표본이 한두 개면 우연(한 문항 맞고 틀림)으로 전이 능력을 오도하므로
# 최소 3건을 요구한다. 완전판(§11.5)의 BKT≥0.95+2주 스케줄과 달리 풀이 이력 기반 *근사*다.
_MIN_TRANSFER_PROBES = 3

# ⑨ BKT 숙달 증가율의 *그룹당 최소 측정점*. 한 (user,concept)의 첫→마지막 mastery 차(증가량)를
# 내려면 최소 before/after 2점이 필요하다(1점이면 변화 자체가 없음). 이보다 적은 그룹은 증가량
# 집계에서 제외한다(가짜 0/증가량 금지). 자격 그룹이 0이면 지표는 NO_DATA다.
_MIN_MASTERY_POINTS = 2


def _ols_slope(ys: list[float]) -> float | None:
    """순서 인덱스 x(0..n-1) 대 ys의 OLS 단순선형회귀 기울기(순수·날조 0).

    x는 0,1,2,…,n-1(등차 적재/측정 순서), y는 `ys`다. 기울기 = Σ(x-x̄)(y-ȳ)/Σ(x-x̄)².
    종단 표본 가드: 유효 포인트가 `_MIN_SLOPE_POINTS` 미만이거나 x 분산이 0이면 **None**을
    반환한다(가짜 0/날조 기울기 금지). x는 0..n-1 등차라 n>=2면 분산은 항상 양수지만,
    방어적으로 0 분산도 None으로 막는다(이론적 경계).

    ⑤ 도움 감소 곡선(hint_level 시계열)·R15 정답률 추세(is_correct 1/0 시계열)가 공유하는
    OLS 코어 — 음수=하락 추세·양수=상승 추세·0=평탄(실측된 평탄이지 날조 0이 아니다).
    """
    n = len(ys)
    if n < _MIN_SLOPE_POINTS:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    x_var = sum((x - x_mean) ** 2 for x in xs)
    if x_var == 0:  # 방어적 — n>=2 등차 인덱스면 도달 불가하나 분산 0이면 None(날조 회피).
        return None
    covariance = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
    return covariance / x_var


class MetricStatus(str, Enum):
    """대리 지표 1종의 계측 상태 — 실값/미계측 사유를 정직하게 구분(0/stub 금지).

    `MEASURED`만 `value`가 실수이고, 나머지 4종은 모두 `value=None`(날조 회피). 미계측 사유를
    상태로 분리해 *무엇을 만들면 잴 수 있는지*(이벤트 적재·라벨·도구)를 커버리지 맵으로 드러낸다.
    """

    MEASURED = "measured"
    """🟢 실측 — 현재 데이터로 계측 완료. `value`에 실수 베이스라인."""

    NO_DATA = "no_data"
    """🟡 좌석은 있으나 데이터 0 — 계측 *경로*는 살아 있고 표본이 없을 뿐(graceful None).

    표본이 쌓이면 그대로 `MEASURED`가 된다(③ 세션 0건·④ 토큰 미적재 행 0건). 미계측(코드
    부재)과 *구분*되는 정직 상태 — 0으로 채우지 않는다.
    """

    NOT_INSTRUMENTED = "not_instrumented"
    """🔴 이벤트 미적재 — 신호 자체가 어디에도 기록되지 않음(verify_result·힌트 시계열).

    계측하려면 *적재 좌석*(이벤트/시계열 컬럼)을 먼저 만들어야 한다 — 다른 슬라이스 책임.
    """

    REQUIRES_DATA = "requires_data"
    """🔴 ground-truth 라벨 부재 — 신호는 있으나 *정답(실제)* 라벨이 없어 일치율을 못 냄.

    문항-오개념 태깅·정답 라벨 코퍼스가 채워져야 계측 가능. ②(진단-실제 오개념 일치율)의 *LIVE
    per-user* 버전이 여기 해당하나, 이 슬라이스에서 ②는 *오프라인 진단정확도*(라벨 프로브
    substring recall·시스템 지표)로 MEASURED가 됐다 — LIVE per-user 일치율만 여전히 REQUIRES_DATA
    (현재 어떤 지표도 이 상태를 쓰지 않음·후속 LIVE 태깅 슬라이스가 점화할 좌석).
    """

    REQUIRES_TOOL = "requires_tool"
    """🔴 미구현 도구 — 측정에 필요한 *도구/출제*가 아직 없음(elicit_prediction·전이 출제).

    도구가 구현돼 신호를 생산해야 계측 가능(⑥ 보정 점수·⑦ 전이 점수).
    """


class Metric(BaseModel):
    """대리 지표 1종 — 실값 또는 미계측 사유. 미계측은 `value=None`(날조 금지·0/stub 금지).

    `MEASURED`/`NO_DATA`만 계측 경로가 살아 있고, 미계측 3종(NOT_INSTRUMENTED·REQUIRES_DATA·
    REQUIRES_TOOL)은 `value=None` + `note`로 "무엇이 필요한지"를 한국어로 밝힌다.
    """

    value: float | None = Field(
        default=None,
        description="실측값(MEASURED). 미계측·표본 0이면 None(가짜 0 금지).",
    )
    status: MetricStatus = Field(description="계측 상태 — 실값/미계측 사유 구분.")
    note: str = Field(description="한국어 설명 — 무엇이 필요/근거(미계측이면 적재·라벨·도구).")


class R15Verdict(str, Enum):
    """R15 결합 판정 — ⑤ 도움 감소를 *정답률 추세와 교차*해 "진짜 개선"인지 가린다.

    설계안 §11.2 R15: "도움 감소를 *정답률 유지와 결합 판정* — 힌트 회피만으로는 개선 인정
    안 함". 즉 도움(hint_level)이 줄어도 정답률이 *같이* 떨어지면 그건 *힌트 회피/방치*(교정기
    함정)이지 실력 향상이 아니다. 이 enum은 ⑤ 기울기 부호·정답률 기울기 부호·**문항 난이도
    기울기 부호**의 *교차*로 내는 판정이다(경계 0 기준·tolerance 없음). 종단·표본 의존·이탈/
    무작위/세션 정렬 신호 미반영은 한계로 note에 정직 표기한다(R15 완전판정이 아니다 — 난이도
    추세는 "쉬운 문제 회피" 1종만 더 잡는 *부분* 정밀화다).
    """

    GENUINE_IMPROVEMENT = "genuine_improvement"
    """진짜 개선 — 도움↓·정답률 유지/↑·(난이도 유지/↑ 또는 난이도 추세 미가용).

    힌트 회피가 아니라 실력으로 도움이 줄었다. 단 난이도 추세가 미가용(b 데이터 부족)이면
    "쉬운 문제 회피"는 *미검증*이다 — note에 blind spot 캐비엇을 정직 표기한다.
    """

    GAMING_SUSPECT = "gaming_suspect"
    """교정기 함정 경보 — 도움↓이나 (정답률↓ **또는** 정답률 유지인데 난이도↓).

    두 사유: ⓐ 정답률↓(힌트 회피/방치 의심) ⓑ 정답률 유지인데 문항 난이도↓(쉬운 문제로
    갈아타 정답률을 유지하는 회피). 둘 다 실력 향상이 아니다 — note에 사유를 구분 표기한다.
    """

    NO_HELP_REDUCTION = "no_help_reduction"
    """도움이 줄지 않음(기울기 >= 0) — 애초에 개선 신호가 아니다(판정 대상 밖)."""

    INSUFFICIENT_DATA = "insufficient_data"
    """도움/정답률 한쪽이라도 종단 표본 부족 — 교차검증 불가(날조 판정 금지)."""


class HelpReductionValidation(BaseModel):
    """R15 결합 판정 결과 — ⑤ 도움 감소·정답률 추세·**문항 난이도 추세**의 3신호 교차.

    ⑤ raw 도움 감소 기울기만으로는 *힌트 회피*(틀려도 레벨이 낮아짐)와 *실력 향상*을 구분
    못 한다(⑤ note의 R15 미반영 한계). 이 모델은 정답률 추세(`ProblemAttempt.is_correct`의
    OLS 기울기)를 교차해 verdict를 낸다 — 도움↓·정답률 유지/↑면 GENUINE_IMPROVEMENT,
    도움↓·정답률↓면 GAMING_SUSPECT. 정답률 신호로 ①(검산 미적발 proxy)이 아니라 *실제
    정답률*인 `is_correct`를 쓰는 이유: R15의 "정답률"에 직접 대응하고 ① 대비 더 직접적이다
    (①은 풀이 제출 턴의 수치 검산 통과 proxy일 뿐).

    **난이도 추세 정밀화(이 슬라이스 추가)**: 정답률 유지(>=0)만으로 GENUINE을 내면 학생이
    *쉬운 문제로 갈아타* 정답률을 유지하는 회피(도움↓·정답률 유지지만 *문항이 쉬워지는 중*)를
    오판한다. 이를 잡기 위해 같은 ProblemAttempt 집합의 문항 IRT 난이도 b(보정 b 우선·없으면
    `difficulty_overall` 휴리스틱·`resolve_item_difficulty_b`) OLS 기울기를 3번째 신호로 쓴다 —
    b 높을수록 어려움이므로 difficulty_slope<0 = 문항이 쉬워지는 중 = 쉬운 문제 회피. 도움↓·
    정답률 유지인데 난이도↓면 GENUINE이 아니라 GAMING_SUSPECT(쉬운 문제 회피)로 격하한다.

    한계(정직 표기): 종단·표본 의존(help/accuracy 한쪽이라도 _MIN_SLOPE_POINTS 미만이면
    INSUFFICIENT_DATA)·경계는 slope 0(tolerance 없음). 난이도 추세는 *부분* 정밀화일 뿐 —
    난이도 b가 부족하면(둘 다 None인 문항만이거나 표본<3) difficulty_slope=None이고, 그때는
    2신호로만 판정하되 "쉬운 문제 회피 미검증" 캐비엇을 note에 표기한다(blind spot 정직).
    이탈/무작위/세션 정렬 등 다른 gaming은 여전히 미반영(R15 완전판정이 아니다).
    """

    verdict: R15Verdict = Field(description="R15 결합 판정 — 도움↓·정답률·난이도 교차 결과.")
    help_slope: float | None = Field(
        default=None,
        description="⑤ 도움 감소 OLS 기울기(raw·음수=도움 감소). 표본 부족이면 None(날조 0 금지).",
    )
    accuracy_slope: float | None = Field(
        default=None,
        description="정답률(is_correct 1/0) OLS 기울기(양수=상승). 표본 부족이면 None(날조 0).",
    )
    difficulty_slope: float | None = Field(
        default=None,
        description=(
            "문항 IRT 난이도 b(보정 b 우선·휴리스틱 폴백) OLS 기울기 — 양수=문항 난이도 상승·"
            "음수=쉬워지는 중(쉬운 문제 회피 신호). b 유효 표본 부족이면 None(날조 0 금지·"
            "그때는 2신호 판정 + blind spot 캐비엇)."
        ),
    )
    note: str = Field(description="한국어 판정 근거 — 임계(slope 0)·교차 결과·사유 구분·한계.")


class SurrogateMetrics(BaseModel):
    """WH-1 0단계 대리 지표 7종 + S3 세션 지표 4종 + 표본 메타 — 커버리지 맵 한 장.

    계측 가능분(① verify 통과율·③ 세션 완주율·④ 턴당 토큰·⑤⑥, ② 오프라인 진단정확도, 그리고
    ⑦ *근사* 전이 점수)은 실값(또는 표본 0/부족이면 NO_DATA)으로 낸다 — 이제 7종 모두 좌석이
    살아 있다. ⑦은 설계 §11.5 완전판이 아니라 풀이 이력 기반 *근사*임을 note에 정직 표기한다.
    메타(표본 수·시간창·user 스코핑)로 이 베이스라인이 *어느 모집단/기간*을 잰 것인지 함께
    기록한다. ②는
    *시스템 지표*(라벨 프로브 substring recall)라 user/시간창 메타와 무관하다(전 user 동일값·
    LIVE per-user ground-truth 아님 — `sample_diagnostic_probes`는 DB 표본이 아니라 프로브셋 크기).
    """

    # ── 7종 대리 지표 ──
    verify_pass_rate: Metric = Field(
        description="① verify 통과율 — 검산결과 이벤트 중 passed=거짓관계 미적발 비율(binary)."
    )
    diagnosis_agreement_rate: Metric = Field(
        description=(
            "② 진단-실제 오개념 일치율 — *오프라인 진단정확도*(라벨 프로브에 substring 매처 "
            "`diagnose` top-1 recall). LIVE 학생별 ground-truth가 아니라 시스템 진단엔진 품질 "
            "지표(전 user 동일값)·recall 프로브 0건이면 NO_DATA."
        )
    )
    session_completion_rate: Metric = Field(
        description="③ 세션 완주율 — LearningSession 중 ended_at 채워진 비율(실측)."
    )
    tokens_per_turn: Metric = Field(
        description="④ 턴당 토큰 — Dialogue.total_tokens/total_turns 평균(실측·비용 대리)."
    )
    help_reduction_slope: Metric = Field(
        description="⑤ 도움 감소 곡선 — 시간에 따른 힌트 의존 감소 기울기."
    )
    help_demand_supply_ratio: Metric = Field(
        default_factory=lambda: Metric(
            value=None, status=MetricStatus.NO_DATA, note="미집계(기본값)."
        ),
        description=(
            "⑮ 도움 요청 대 제공 비 — attempt_event(힌트요청)/attempt_event(힌트제공) 개수 비. "
            "supply(힌트제공) 0건이면 NO_DATA(분모 0 방지·가짜 0 금지). 힌트제공 이벤트가 0이면 "
            "⑤⑧도 이미 NO_DATA이므로 이 지표만 홀로 값을 내지 않는다(일관성). 기본값은 미집계 "
            "호출자(다른 지표 신설 시점 이전 생성자)와의 회귀 0을 위함 — 실 집계 경로는 항상 "
            "명시 주입(`compute_wh1_surrogate_metrics`)."
        ),
    )
    calibration_brier: Metric = Field(
        description=(
            "⑥ 보정 점수(Brier) — 자기보고 확신도(0~1) vs 실제 정오답 mean((conf−correct)²)"
            "(낮을수록 잘 보정·실측). 유효 쌍 부족이면 NO_DATA(가짜 0 금지)."
        )
    )
    transfer_score: Metric = Field(
        description=(
            "⑦ 전이 점수(근사) — 같은 시그니처 패턴·다른 problem_id·사전 노출 후 초견(첫 시도) "
            "정답률. 설계 §11.5 완전판(assign_transfer_probe·BKT≥0.95+2주 스케줄)과 다른 *근사*"
            "(풀이 이력 기반)·전이 프로브 부족이면 NO_DATA(가짜 0 금지)."
        )
    )

    # ── R15 파생 결합 판정(⑤ 도움 감소 × 정답률 추세) ──
    help_reduction_validated: HelpReductionValidation = Field(
        description=(
            "R15 결합 판정 — ⑤ 도움 감소를 정답률(is_correct) 추세와 교차해 진짜 개선 vs "
            "교정기 함정(힌트 회피) 가림. ⑤ raw 기울기를 *검증*한 파생 신호(새 적재 0)."
        )
    )

    # ── S3 세션 대리 지표 4종(status_roadmap §3·기존 신호 재사용·user/시간창 집계) ──
    hint_depth_reached: Metric = Field(
        description=(
            "⑧ 답 미루기 도달 깊이 — ⑤와 동일 힌트제공 hint_level의 *평균*(note에 최대). "
            "게이밍(힌트 회피)은 R15(help_reduction_validated)가 교차 방어·단독 해석 금지."
        )
    )
    mastery_gain_rate: Metric = Field(
        description=(
            "⑨ BKT 숙달 증가율 — ConceptMasteryHistory (user,concept)별 첫→마지막 mastery 차 "
            "평균(증가 방향·크기). 시간 정규화 rate는 아님(후속)·자격 그룹 0이면 NO_DATA."
        )
    )
    gap_recovery_leadtime_days: Metric = Field(
        description=(
            "⑯ 결손 복구 리드타임 — ConceptMasteryHistory (user,concept)별 '첫 취약 관측"
            "(<0.7) → 첫 숙달 도달(>=0.8)' 벽시계 **경과 일수** 평균(낮을수록 회복이 빠름). "
            "미도달 그룹은 분모에서 제외(가짜 0 금지)·첫 도달 기준 고정(재하락 무시)·"
            "학습 시간이 아니라 경과 일수(time-on-task 분모 부재)·자격 그룹 0이면 NO_DATA."
        )
    )
    misconception_resolution_rate: Metric = Field(
        description=(
            "⑩ 오개념 해소율 — MisconceptionHypothesisRecord is_active=false 비율(해소 *근사*). "
            "resolved_at 컬럼 부재로 학습적 해소·stale 정리 미구분(후속)·total 0이면 NO_DATA."
        )
    )
    self_solve_rate: Metric = Field(
        description=(
            "⑪ 스스로 풀이 도달율 — Dialogue.resolution=학생자력해결 비율(분모=resolution 채워진 "
            "세션). resolution은 클라이언트 보고(PATCH .../end·서버 미판정)·resolved 0이면 NO_DATA."
        )
    )

    # ── PED-04 교수 결정 로그 지표 3종(D1 writer가 만든 데이터의 첫 reader) ──
    strategy_diversity: Metric = Field(
        default_factory=lambda: Metric(
            value=None, status=MetricStatus.NO_DATA, note="미집계(기본값)."
        ),
        description=(
            "⑫ 발문 전략 다양성 — DialogueTurn.socratic_strategy의 distinct/total. 실질 상한은 "
            "현 생산 경로 도달 가능 4종(note 참조)·기록 턴 부족이면 NO_DATA."
        ),
    )
    strategy_repeat_rate: Metric = Field(
        default_factory=lambda: Metric(
            value=None, status=MetricStatus.NO_DATA, note="미집계(기본값)."
        ),
        description=(
            "⑬ 발문 전략 연속 반복률 — *대화 내* 인접 AI 턴 쌍 중 전략 동일 비율(세션 경계 "
            "미교차). 단조 발문 회전(select_category 규칙 2.5)의 계기판·인접쌍 부족이면 NO_DATA."
        ),
    )
    client_state_mismatch_rate: Metric = Field(
        default_factory=lambda: Metric(
            value=None, status=MetricStatus.NO_DATA, note="미집계(기본값)."
        ),
        description=(
            "⑭ 클라 Polya 상태 불일치율 — 힌트제공 이벤트 중 client_state_mismatch=true 비율. "
            "오류율이 아니라 *동기화 신호*(D2가 서버 소유로 되찾은 상태의 신뢰 지표)."
        ),
    )

    # ── 표본·범위 메타 ──
    sample_sessions: int = Field(
        default=0, description="③ 집계 대상 LearningSession 수(시간창·user 필터 적용)."
    )
    sample_dialogues: int = Field(
        default=0, description="④ 집계 대상 Dialogue 수(토큰·턴 채워진 행만)."
    )
    sample_verify_events: int = Field(
        default=0,
        description="① 집계 대상 검산결과 attempt_event 수(passed 채워진 행).",
    )
    sample_hint_events: int = Field(
        default=0,
        description="⑤ 집계 대상 힌트제공 attempt_event 수(hint_level 채워진 행·OLS 포인트 수).",
    )
    sample_strategy_turns: int = Field(
        default=0,
        description="⑫⑬ 집계 대상 AI 턴 수(socratic_strategy NOT NULL·대화별 시퀀스 합).",
    )
    sample_demand_events: int = Field(
        default=0, description="⑮ 집계 대상 힌트요청 attempt_event 수."
    )
    sample_accuracy_attempts: int = Field(
        default=0,
        description=(
            "R15 정답률 추세 집계 대상 ProblemAttempt 수(is_correct NOT NULL·OLS 포인트 수)."
        ),
    )
    sample_difficulty_attempts: int = Field(
        default=0,
        description=(
            "R15 난이도 추세 집계 대상 ProblemAttempt 수(problem join·유효 b NOT NULL·OLS "
            "포인트 수). 정답률 표본과 다를 수 있음(b 없는 문항·problem_id NULL 제외)."
        ),
    )
    sample_calibration_pairs: int = Field(
        default=0,
        description=(
            "⑥ 보정 점수(Brier) 집계 대상 ProblemAttempt 쌍 수(confidence_self_reported·"
            "is_correct 둘 다 NOT NULL). `_MIN_CALIBRATION_SAMPLES` 미만이면 NO_DATA."
        ),
    )
    sample_transfer_probes: int = Field(
        default=0,
        description=(
            "⑦ 근사 전이 점수 집계 대상 *전이 프로브* 수(같은 시그니처 패턴·다른 problem_id·"
            "사전 노출 후 초견[첫 시도]·패턴별 독립 카운트). `_MIN_TRANSFER_PROBES` 미만이면 "
            "NO_DATA(가짜 0 금지). 설계 §11.5 완전판(BKT≥0.95+2주 스케줄)과 다른 *근사*(풀이 "
            "이력 기반·마킹/스케줄 도구 미구현)."
        ),
    )
    sample_diagnostic_probes: int = Field(
        default=0,
        description=(
            "② 진단-실제 오개념 일치율(오프라인) 대상 *recall 프로브* 수(expected_id 설정·라벨된 "
            "틀린 진술). 0이면 NO_DATA. **시스템 지표**라 user/시간창과 무관(전 user 동일값) — "
            "DB 표본이 아니라 라벨 프로브셋 크기다(LIVE per-user ground-truth 아님)."
        ),
    )
    sample_mastery_groups: int = Field(
        default=0,
        description=(
            "⑨ BKT 숙달 증가율 집계 대상 자격 (user,concept) 그룹 수(measured_at 측정점 "
            f">= {_MIN_MASTERY_POINTS}·mastery NOT NULL). 미만 그룹은 제외·0이면 NO_DATA."
        ),
    )
    sample_gap_recovery_groups: int = Field(
        default=0,
        description=(
            "⑯ 결손 복구 리드타임의 **분모** — 취약 관측 후 숙달까지 실제로 도달한 "
            "(user,concept) 그룹 수. 미도달 그룹은 여기 포함되지 않는다(가짜 0 금지) — "
            "제외 건수는 지표 note가 보고한다. 0이면 NO_DATA."
        ),
    )
    sample_misconception_hypotheses: int = Field(
        default=0,
        description=(
            "⑩ 오개념 해소율 집계 대상 MisconceptionHypothesisRecord 수(user·updated_at 시간창 "
            "필터). 이 중 is_active=false가 해소 근사·0이면 NO_DATA."
        ),
    )
    sample_resolved_dialogues: int = Field(
        default=0,
        description=(
            "⑪ 스스로 풀이 도달율 집계 대상 Dialogue 수(resolution NOT NULL·user·started_at 시간창 "
            "필터). 분모 — 이 중 학생자력해결이 분자·0이면 NO_DATA(미보고 NULL은 제외)."
        ),
    )
    window_start: datetime | None = Field(
        default=None, description="집계 시간창 시작(since·생략 시 None=무한 과거)."
    )
    window_end: datetime | None = Field(
        default=None, description="집계 시간창 끝(until·생략 시 None=무한 미래)."
    )
    user_scoped: bool = Field(
        default=False, description="True면 특정 user 본인 집계, False면 코호트 전체."
    )
    mode_filter: str | None = Field(
        default=None,
        description=(
            "S3-03 응용 모드 스코프 — 설정 시(예: 'suneung') 이 집계가 그 mode 태그가 실린 "
            "*attempt_event 기반 지표*(① verify 통과율·⑤ 도움 감소·⑧ 도달 깊이)만 mode-scoped로 "
            "필터한 값이다. **다른 지표(③④⑥⑦⑨⑩⑪·R15)는 아직 mode를 싣지 않아 mode 무관 집계 "
            "그대로**다(완전한 mode별 집계는 후속 S3-04). None이면 모든 mode 포함(기존 동작 불변)."
        ),
    )


# ── 미계측 고정 Metric(value None·상태 enum·한국어 note) ──────────────────────────
# 날조 금지: 신호가 적재/라벨/도구로 생산되기 전까지 value=None을 유지한다(0/stub 금지).


def _diagnosis_agreement_offline(hits: int, total: int) -> Metric:
    """② 진단-실제 오개념 일치율 — *오프라인 진단정확도*(라벨 프로브 substring recall).

    `probes.compute_diagnostic_recall`이 낸 (hit 수, recall 프로브 총수)로 top-1 recall을
    Metric으로 싼다. recall 프로브가 0건이면(라벨셋 비거나 전부 FP) **NO_DATA**(value None·날조
    회피) — 실제 프로브셋은 60건의 recall 프로브를 담아 MEASURED가 된다.

    **정직 스코프(중요)** — 이 값은 *오프라인·시스템 지표*다. LIVE 학생별 ground-truth가 아니다:
      - **오프라인·시스템 지표**: 라벨된 프로브(틀린 진술→expected_id 오개념)에 substring 매처
        `diagnose`를 돌려 *top-1 매치 id == expected_id* 비율을 낸다. *시스템 진단엔진 품질*을
        재므로 user_id/since/until과 무관하다(전 user 동일값·`user_scoped`·시간창에 안 묶임).
      - **LIVE per-user 진단정확도가 아니다**: 실제 학생의 진짜 오개념은 자가보고되지 않고
        (문항-오개념 태깅·attempt별 진단 기록 부재) 학생별 일치율은 여전히 데이터 기반이 없다.
      - **substring은 보수적 기준선**: 의미 매처(pgvector 임베딩)는 패러프레이즈까지 잡아 더 높은
        recall을 내지만 임베딩 의존이다. 여기선 항상 가용한 결정론 substring만 쓴다.
      - **FP율/precision은 범위 밖**: 거짓양성·정밀도는 `semantic_eval`이 별도 측정한다(여기선
        recall 프로브만). 따라서 이 값을 진단엔진의 *정밀도*로 읽으면 안 된다.
    """
    if total <= 0:  # recall 프로브 0건 — 라벨셋 부재/전부 FP(날조 0 회피)
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "라벨 프로브셋에 recall 프로브(expected_id 설정)가 0건 — 오프라인 진단정확도 "
                "산출 불가(가짜 0 아님). 라벨 프로브가 채워지면 substring 매처 recall 계측."
            ),
        )
    recall = hits / total
    return Metric(
        value=recall,
        status=MetricStatus.MEASURED,
        note=(
            f"오프라인 진단정확도 — 라벨 프로브 {total}건에 substring 매처 recall(top-1 "
            f"expected_id 일치율 {hits}/{total}={recall:.4f}). **LIVE 학생별 ground-truth가 "
            "아님**(시스템 진단엔진 품질·전 user 동일값·user/기간 무관). substring은 보수적 "
            "기준선(의미 매처[pgvector]는 더 높은 recall이나 임베딩 의존)·FP율/precision은 "
            "semantic_eval 별도(여기선 recall 프로브만)·표본은 프로브셋 크기."
        ),
    )


def _help_reduction_from_levels(hint_levels: list[int]) -> Metric:
    """⑤ 도움 감소 곡선 — 힌트제공 hint_level 시계열의 OLS 단순선형회귀 기울기를 Metric으로.

    입력 `hint_levels`는 *event_at 오름차순*으로 정렬된 hint_level(1~4·supply) 시계열이다.
    x는 순서 인덱스(0,1,2,…), y는 hint_level. OLS 기울기 = Σ(x-x̄)(y-ȳ)/Σ(x-x̄)² —
    **음수면 시간이 갈수록 AI가 더 은근한(낮은) 힌트로 충분 = 도움 감소 = 개선**이다.

    종단 표본 가드(날조 0): 유효 포인트가 `_MIN_SLOPE_POINTS` 미만이거나 x 분산이 0이면
    기울기를 산출하지 않고 **NO_DATA**(value None)로 둔다 — 가짜 0/날조 기울기 금지. x는
    0..n-1 등차라 n>=2면 분산은 항상 양수지만, 방어적으로 0 분산도 NO_DATA로 막는다.

    정직 note: 이 기울기는 *raw* 힌트 노출량 추세일 뿐, **R15(정확률 교차검증) 미반영**이다 —
    학생이 힌트를 *회피*해서(틀려도) 레벨이 낮아진 것과 *실력으로* 낮아진 것을 구분하지 못한다.
    힌트 회피만으로 개선 판정하지 않는 교차검증은 후속 슬라이스 책임. 종단 지표라 표본이 적으면
    NO_DATA이고, hint_level은 graded 노출량(1~4·1=가장 은근/4=전체 풀이)이다.

    OLS 코어는 `_ols_slope`(공유 헬퍼)에 위임한다 — None(표본 부족/분산 0)이면 NO_DATA로
    분기(가드·note 비트동일 유지). n<_MIN_SLOPE_POINTS면 표본 부족 note, 그 외 None이면(이론적
    x 분산 0) 분산 0 note로 *기존과 동일하게* 갈라낸다.
    """
    n = len(hint_levels)
    slope = _ols_slope([float(level) for level in hint_levels])
    if slope is None:
        if n < _MIN_SLOPE_POINTS:
            return Metric(
                value=None,
                status=MetricStatus.NO_DATA,
                note=(
                    f"힌트제공 이벤트 {n}건 — 종단 표본 부족(최소 {_MIN_SLOPE_POINTS}점) 으로 OLS "
                    "기울기 산출 불가. 힌트제공이 쌓이면 도움 감소 곡선 계측(가짜 0/기울기 아님). "
                    "R15 정확률 교차검증 미반영(후속)·종단 지표."
                ),
            )
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "힌트제공 시계열의 시간축 분산 0 — OLS 기울기 산출 불가(가짜 0 아님). "
                "R15 정확률 교차검증 미반영(후속)·종단 지표."
            ),
        )

    return Metric(
        value=slope,
        status=MetricStatus.MEASURED,
        note=(
            f"힌트제공 {n}건 hint_level OLS 기울기 {slope:+.4f}(event_at 순서·음수=도움 감소). "
            "R15 정확률 교차검증 미반영(힌트 회피만으로 개선 판정 안 함은 후속)·종단 지표라 "
            "표본 적으면 NO_DATA·hint_level은 graded 노출량(1~4)."
        ),
    )


def _help_demand_supply_ratio_from_counts(demand_count: int, supply_count: int) -> Metric:
    """⑮ 도움 요청 대 제공 비 — 힌트요청(demand)/힌트제공(supply) 개수 비를 Metric으로(순수·날조 0).

    입력은 (힌트요청 attempt_event 수, 힌트제공 attempt_event 수) — S3-16에서 `힌트요청`이
    휴면에서 생산자를 얻으며 연 형제 좌석이다(⑤⑧과 동일 힌트제공 표본을 분모로 재사용).
    supply_count==0이면 **NO_DATA**(분모 0 방지·가짜 0 회피) — 힌트제공이 0이면 ⑤⑧도 이미
    NO_DATA이므로 이 지표만 홀로 값을 내는 일은 없다(일관성). demand_count==0이어도 supply>0이면
    ratio=0.0(MEASURED·실측 0·날조 아님 — 학생이 답을 요구한 적이 없다는 실제 신호).
    """
    if supply_count <= 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "힌트제공(supply) 이벤트 0건 — 분모 0이라 비율 산출 불가(가짜 0 아님). "
                "힌트제공이 쌓이면 도움 요청 대 제공 비 계측(⑤⑧과 동일 표본 재사용)."
            ),
        )
    ratio = demand_count / supply_count
    return Metric(
        value=ratio,
        status=MetricStatus.MEASURED,
        note=(
            f"힌트요청(demand) {demand_count}건 / 힌트제공(supply) {supply_count}건 = "
            f"{ratio:.4f}(비율↑=학생이 AI 제공량 대비 더 많이 직접 답을 요구). demand 0건은 "
            "요구 없음의 실측(날조 아님)·⑤⑧과 동일 scope(user/시간창/mode)."
        ),
    )


def _judge_r15(
    help_slope: float | None,
    accuracy_slope: float | None,
    difficulty_slope: float | None,
) -> HelpReductionValidation:
    """R15 결합 판정(순수) — ⑤ 도움 감소·정답률·**문항 난이도** 3신호를 교차해 verdict를 낸다.

    설계안 §11.2 R15: 도움 감소를 *정답률 유지와 결합 판정* — 힌트 회피만으로 개선 인정 안 함.
    경계는 slope 0(tolerance 없이 명확)·날조 0 금지(help/accuracy 한쪽이라도 None이면
    INSUFFICIENT_DATA). 난이도(difficulty_slope)는 *선택* 신호다 — None이면 2신호로 판정하되
    blind spot을 note에 캐비엇 표기한다(가짜 0/기울기 금지):

    - help_slope None **또는** accuracy_slope None → INSUFFICIENT_DATA(종단 표본 부족·교차 불가).
    - help_slope >= 0(도움 안 줄어듦) → NO_HELP_REDUCTION(개선 신호 자체가 아님).
    - help_slope < 0 **and** accuracy_slope < 0(정답률 하락) → GAMING_SUSPECT(힌트 회피/방치).
    - help_slope < 0 **and** accuracy_slope >= 0(정답률 유지/상승):
        - difficulty_slope is not None **and** difficulty_slope < 0(난이도↓) →
          GAMING_SUSPECT(쉬운 문제 회피 — 쉬운 문제로 갈아타 정답률 유지). ← 이 슬라이스 정밀화.
        - else(난이도 유지/상승 또는 난이도 추세 미가용) → GENUINE_IMPROVEMENT.
          단 difficulty_slope None이면 "쉬운 문제 회피 미검증" 캐비엇을 note에 표기(blind spot).

    정답률 신호는 `ProblemAttempt.is_correct`의 OLS 기울기(실제 정답률 추세)다 — ①(검산
    미적발 proxy)이 아니라 is_correct를 쓰는 이유는 R15의 "정답률"에 직접 대응하고 더
    직접적이기 때문. 난이도 신호는 문항 IRT 난이도 b(보정 b 우선·휴리스틱 폴백)의 OLS
    기울기로, b 높을수록 어려움이라 음수=쉬워지는 중이다. 난이도 추세는 "쉬운 문제 회피"
    1종만 더 잡는 *부분* 정밀화일 뿐 — 이탈/무작위/세션 정렬 등 다른 gaming은 여전히 미반영
    (R15 완전판정이 아니다)임을 note에 정직 표기한다.
    """
    if help_slope is None or accuracy_slope is None:
        return HelpReductionValidation(
            verdict=R15Verdict.INSUFFICIENT_DATA,
            help_slope=help_slope,
            accuracy_slope=accuracy_slope,
            difficulty_slope=difficulty_slope,
            note=(
                "도움/정답률 한쪽이라도 종단 표본 부족(최소 "
                f"{_MIN_SLOPE_POINTS}점)으로 R15 교차검증 불가 — verdict 미산출(날조 판정 금지). "
                "정답률 신호는 ProblemAttempt.is_correct 추세(① 검산 proxy 아님)."
            ),
        )

    if help_slope >= 0:
        return HelpReductionValidation(
            verdict=R15Verdict.NO_HELP_REDUCTION,
            help_slope=help_slope,
            accuracy_slope=accuracy_slope,
            difficulty_slope=difficulty_slope,
            note=(
                f"도움 기울기 {help_slope:+.4f} >= 0 — 도움이 줄지 않아 개선 신호 자체가 아님"
                "(임계 slope 0). 정답률·난이도 추세와 교차 불필요."
            ),
        )

    if accuracy_slope < 0:
        return HelpReductionValidation(
            verdict=R15Verdict.GAMING_SUSPECT,
            help_slope=help_slope,
            accuracy_slope=accuracy_slope,
            difficulty_slope=difficulty_slope,
            note=(
                f"교정기 함정 경보(사유: 정답률 하락) — 도움 기울기 {help_slope:+.4f} < 0(도움↓)"
                f"이나 정답률 기울기 {accuracy_slope:+.4f} < 0(하락). 힌트 회피/방치 의심(실력 "
                "향상 아님·임계 slope 0·정답률=is_correct 추세). 종단·표본 의존·이탈/무작위/세션 "
                "정렬 신호 미반영(R15 완전판정 아님)."
            ),
        )

    # 여기부터 도움↓·정답률 유지/상승 — 난이도 추세로 "쉬운 문제 회피"를 가른다(3번째 신호).
    if difficulty_slope is not None and difficulty_slope < 0:
        return HelpReductionValidation(
            verdict=R15Verdict.GAMING_SUSPECT,
            help_slope=help_slope,
            accuracy_slope=accuracy_slope,
            difficulty_slope=difficulty_slope,
            note=(
                f"교정기 함정 경보(사유: 쉬운 문제 회피·난이도↓) — 도움 기울기 {help_slope:+.4f} "
                f"< 0(도움↓)·정답률 기울기 {accuracy_slope:+.4f} >= 0(유지/상승)이나 문항 난이도 "
                f"기울기 {difficulty_slope:+.4f} < 0(쉬워지는 중). 쉬운 문제로 갈아타 정답률을 "
                "유지한 회피(실력 향상 아님·임계 slope 0·난이도=IRT b 추세·b↓=쉬워짐). 종단·표본 "
                "의존·이탈/무작위/세션 정렬 신호 미반영(R15 완전판정 아님)."
            ),
        )

    # 난이도 유지/상승, 또는 난이도 추세 미가용 → 진짜 개선. 미가용이면 blind spot 캐비엇.
    if difficulty_slope is None:
        difficulty_note = "난이도 추세 미가용(b 부족) — 쉬운문제 회피 미검증(blind spot). "
    else:
        difficulty_note = f"난이도 기울기 {difficulty_slope:+.4f} >= 0(쉬운문제 회피 아님). "
    return HelpReductionValidation(
        verdict=R15Verdict.GENUINE_IMPROVEMENT,
        help_slope=help_slope,
        accuracy_slope=accuracy_slope,
        difficulty_slope=difficulty_slope,
        note=(
            f"진짜 개선 — 도움 기울기 {help_slope:+.4f} < 0(도움↓)·정답률 기울기 "
            f"{accuracy_slope:+.4f} >= 0(유지/상승). {difficulty_note}힌트 회피가 아니라 실력으로 "
            "도움 감소(임계 slope 0·정답률=is_correct 추세). 종단·표본 의존·이탈/무작위/세션 정렬 "
            "미반영(R15 완전판정 아님·난이도 추세는 부분 정밀화)."
        ),
    )


def _calibration_from_pairs(pairs: list[tuple[float, bool]]) -> Metric:
    """⑥ 보정 점수(Brier) — (자기보고 확신도, 실제 정오답) 쌍의 Brier score를 Metric으로(순수).

    입력 `pairs`는 (confidence_self_reported∈[0,1], is_correct: bool) 쌍 목록이다 — 둘 다
    NOT NULL인 ProblemAttempt 행만(호출부가 필터). Brier = mean((confidence − outcome)²),
    outcome은 is_correct를 1.0/0.0으로 본 *실제 정오답*이다. confidence가 *예측*(학생이 풀기
    전/직후 자기보고한 맞힐 확신도)이고 outcome이 *실제*라, 이 둘의 제곱오차 평균이 보정 점수다.
    **Brier∈[0,1]·낮을수록 잘 보정**(예측 확신도가 실제 정오답과 일치). 완벽 보정(conf=outcome)
    이면 0, 완전 오보정(conf=1인데 틀림 또는 conf=0인데 맞음)이면 1이다.

    종단 표본 가드(날조 0): 유효 쌍이 `_MIN_CALIBRATION_SAMPLES` 미만이면 Brier를 산출하지 않고
    **NO_DATA**(value None)로 둔다 — Brier는 평균이라 N>=1이어도 값은 나오지만, 표본이 한두 개면
    종단 노이즈로 보정 추세를 오도하므로 가짜 0/Brier를 내지 않는다(0/stub 금지).

    정직 note: Brier는 *보정 점수*일 뿐 §11.4의 과신/과소신 구간 코칭·종단 추적·학부모 리포트
    항목은 미구현(후속)이다. 또 `POST /v1/me/attempts`가 confidence와 result를 *동시* 제출하므로
    *엄밀한 사전 예측*(풀기 전 확신도 격리 수집)은 클라 흐름 책임이고, 현재는 자기보고 확신도다.
    """
    n = len(pairs)
    if n < _MIN_CALIBRATION_SAMPLES:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"보정 쌍(confidence·is_correct 둘 다 채워진 ProblemAttempt) {n}건 — 종단 표본 "
                f"부족(최소 {_MIN_CALIBRATION_SAMPLES}쌍)으로 Brier 미산출(가짜 0/Brier 금지). "
                "POST /v1/me/attempts가 confidence+result를 쌓으면 보정 점수 계측. Brier는 "
                "보정 점수일 뿐 과신/과소신 구간 코칭(§11.4)은 후속."
            ),
        )

    # Brier = mean((confidence − outcome)²) — outcome은 is_correct를 1.0/0.0으로(순수 평균·날조 0).
    brier = sum((conf - (1.0 if correct else 0.0)) ** 2 for conf, correct in pairs) / n
    return Metric(
        value=brier,
        status=MetricStatus.MEASURED,
        note=(
            f"자기보고 확신도(0~1) vs 실제 정오답 Brier {brier:.4f}(낮을수록 잘 보정·{n}쌍 평균). "
            "POST /v1/me/attempts가 confidence+result 동시 제출이라 *엄밀한 사전 예측*은 클라 "
            f"흐름 책임(현재는 자기보고 확신도)·표본<{_MIN_CALIBRATION_SAMPLES} NO_DATA·"
            "과신/과소신 구간 코칭(§11.4)은 후속."
        ),
    )


def _identify_transfer_probes(
    rows: Sequence[tuple[uuid.UUID | None, Sequence[SignaturePattern] | None, bool]],
) -> list[bool]:
    """근사 전이 프로브 식별(순수·날조 0) — 같은 패턴·다른 문항·사전 노출 후 초견(첫 시도).

    입력 `rows`는 *started_at 오름차순*으로 정렬된 (problem_id, signature_patterns, is_correct)
    시퀀스다(호출부가 is_correct NOT NULL·user/시간창 필터 후 ORM join으로 조회). 시간순으로
    훑으며 **전이 프로브**를 골라 그 is_correct를 모아 반환한다.

    전이 프로브 정의(설계 §11.5 *근사*): 어떤 attempt의 문항이 패턴 P를 가질 때, 그 attempt가
      ⓐ **그 problem_id의 첫 등장**(초견 — 이전에 같은 problem_id를 본 적 없음)이고
      ⓑ **사전 노출**: 이전에 *다른* problem_id를 패턴 P로 *이미* 본 적이 있으면
    → 이 (attempt, P)를 전이 프로브 1건으로 집계한다(is_correct). = "이 패턴을 다른 문항에서
    이미 만난 뒤 *새* 동형 문항을 처음 풀어 맞혔는가". 표면(소재/숫자/맥락) 상이는 *다른
    problem_id*로 근사하고, 심층 구조 동일성은 패턴 태그(`signature_patterns`)에 의존한다.

    **집계 단위(명확 정의)**: *패턴별 독립*이다 — 전이 프로브 1건 = 특정 (problem_id, 패턴 P)
    초견. 한 attempt의 문항이 여러 패턴을 갖고 각각 사전 노출이 있으면, 그 attempt는 패턴 수
    만큼의 전이 프로브로 *중복 카운트*된다(각 패턴이 독립 전이 사건이라). is_correct는 attempt
    공통이라 같은 attempt가 낳은 프로브들은 같은 정오답을 공유한다.

    상태 추적(순수·O(n·평균패턴수)):
      - `seen_problem_ids`: 지금까지 등장한 problem_id 집합(초견 판정 ⓐ).
      - `seen_pattern_problem`: 패턴 P → 그 패턴으로 본 problem_id 집합(사전 노출 판정 ⓑ —
        *다른* problem_id로 본 적 있는지). 현재 problem_id를 *제외*한 사전 노출만 인정한다.
    같은 attempt가 여러 패턴이면 각 패턴을 독립 평가하고, 한 패스의 끝에서 상태를 갱신한다
    (같은 attempt 안의 패턴끼리는 서로의 사전 노출로 치지 않는다 — 한 시점 사건이라).

    problem_id가 None(느슨참조 미설정)이면 초견/중복을 구분할 수 없어 *그 attempt 전체를 제외*
    한다(날조 회피). 패턴이 비었으면(태그 0개) 전이 사건이 없으므로 자연히 기여 0.
    """
    transfer_outcomes: list[bool] = []
    seen_problem_ids: set[uuid.UUID] = set()
    # 패턴 → 그 패턴으로 *이미 본* problem_id 집합(사전 노출 판정용).
    seen_pattern_problem: dict[SignaturePattern, set[uuid.UUID]] = {}

    for problem_id, patterns, is_correct in rows:
        # problem_id 없으면 초견/사전노출을 가릴 수 없어 이 attempt는 전이 식별에서 제외(날조 0).
        if problem_id is None:
            continue
        is_first_sight = problem_id not in seen_problem_ids
        pattern_list = patterns or []

        # 초견인 경우에만 전이 프로브 후보 — 패턴별로 *다른* problem_id의 사전 노출이 있으면 집계.
        if is_first_sight:
            for pattern in pattern_list:
                prior_problems = seen_pattern_problem.get(pattern)
                # 현재 problem_id를 제외한 *다른* 문항으로 이 패턴을 이미 본 적 있는가(사전 노출 ⓑ).
                if prior_problems and (prior_problems - {problem_id}):
                    transfer_outcomes.append(is_correct)

        # 상태 갱신(이 attempt 평가 후) — 다음 attempt부터 이 problem_id·패턴 노출이 사전 노출이 됨.
        seen_problem_ids.add(problem_id)
        for pattern in pattern_list:
            seen_pattern_problem.setdefault(pattern, set()).add(problem_id)

    return transfer_outcomes


def _transfer_from_probes(transfer_outcomes: list[bool]) -> Metric:
    """⑦ 근사 전이 점수 — 전이 프로브 정답률을 Metric으로(순수·날조 0).

    입력 `transfer_outcomes`는 `_identify_transfer_probes`가 고른 전이 프로브들의 is_correct
    목록이다. transfer_score = 맞은 전이 프로브 / 전체 전이 프로브(높을수록 전이 잘 됨).

    종단 표본 가드(날조 0): 전이 프로브가 `_MIN_TRANSFER_PROBES` 미만이면 정답률을 산출하지
    않고 **NO_DATA**(value None)로 둔다 — 정답률은 평균이라 N>=1이어도 값은 나오지만, 한두
    건이면 우연(한 문항 맞고 틀림)이 전이 능력을 오도하므로 가짜 0/정답률을 내지 않는다.

    정직 note(중요): 이는 *근사 전이 점수*다 — **설계 §11.5 완전판(assign_transfer_probe·노드
    BKT≥0.95 + 2주 후 자동 출제)과 다르다**. 전이 프로브 마킹/스케줄 도구가 미구현이라 풀이
    이력에서 근사한다: 같은 시그니처 패턴·*다른 problem_id*·사전 노출 후 초견(첫 시도) 정답률.
    표면 상이는 다른 problem_id로 근사·심층구조 동일성은 패턴 태그에 의존·BKT 숙달 게이팅·2주
    스케줄 미반영(후속은 마킹/스케줄 도구).
    """
    n = len(transfer_outcomes)
    if n < _MIN_TRANSFER_PROBES:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"근사 전이 프로브(같은 시그니처 패턴·다른 problem_id·사전 노출 후 초견) {n}건 — "
                f"표본 부족(최소 {_MIN_TRANSFER_PROBES}건)으로 전이 정답률 미산출(가짜 0/정답률 "
                "금지). 같은 패턴을 다른 문항에서 만난 뒤 *새* 동형 문항을 처음 푸는 이력이 쌓이면 "
                "계측. **설계 §11.5 완전판(assign_transfer_probe·BKT≥0.95+2주 스케줄)과 다른 근사**"
                "(마킹/스케줄 도구 미구현·후속)."
            ),
        )
    hits = sum(1 for correct in transfer_outcomes if correct)
    score = hits / n
    return Metric(
        value=score,
        status=MetricStatus.MEASURED,
        note=(
            f"근사 전이 점수 — 같은 시그니처 패턴·다른 problem_id·사전 노출 후 초견(첫 시도) "
            f"정답률 {hits}/{n}={score:.4f}(높을수록 전이 잘 됨). **설계 §11.5 완전판"
            "(assign_transfer_probe·노드 BKT≥0.95 + 2주 후 자동 출제)과 다름** — 전이 프로브 "
            "마킹/스케줄 도구 미구현이라 풀이 이력에서 근사한다(표면 상이는 *다른 problem_id*로 "
            "근사·심층구조 동일성은 패턴 태그에 의존·BKT 숙달 게이팅·2주 스케줄 미반영)·"
            f"표본<{_MIN_TRANSFER_PROBES} NO_DATA·패턴별 독립 집계(전이 프로브 1건=특정 "
            "(problem,패턴) 초견). 후속은 assign_transfer_probe 마킹/스케줄 도구."
        ),
    )


# ⑫⑬ 발문 전략 지표의 *최소 기록 턴 수*. 전략이 한두 턴만 기록된 상태에서 다양성/반복률을 내면
# 1.0 또는 0.0이라는 극단값이 나와 추세를 오도한다(N=1이면 다양성은 항상 1.0). 최소 3턴을 요구한다.
_MIN_STRATEGY_TURNS = 3


def _strategy_diversity_from_values(strategies: list[str]) -> Metric:
    """⑫ 전략 다양성 — 기록된 발문 전략 중 서로 다른 값의 비율(순수·날조 0).

    `distinct/total`이라 1.0은 "매 턴 다른 전략", 낮을수록 단조롭다. 표본이
    `_MIN_STRATEGY_TURNS` 미만이면 NO_DATA(가짜 1.0 금지).

    **해석 상한을 note에 반드시 싣는다**: 현 생산 경로에서 도달 가능한 전략은
    `REACHABLE_STRATEGIES` 4종뿐이라(`select_intervention`이 개입 패턴 2종만 반환) 다양성의
    실질 상한은 min(4, N)/N이다. 이 상한을 모르면 "6종 중 4종만 쓴다"를 품질 저하로 오독한다.
    """
    total = len(strategies)
    if total < _MIN_STRATEGY_TURNS:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"발문 전략 기록 턴 {total}건 — 표본 부족(최소 {_MIN_STRATEGY_TURNS}턴)으로 "
                "다양성 산출 불가(가짜 1.0 아님). coach 세션 턴이 쌓이면 계측."
            ),
        )
    distinct = len(set(strategies))
    reachable = len(REACHABLE_STRATEGIES)
    return Metric(
        value=distinct / total,
        status=MetricStatus.MEASURED,
        note=(
            f"AI 턴 {total}건 중 서로 다른 전략 {distinct}종. **실질 상한은 "
            f"min({reachable},N)/N** — 현 생산 경로에서 도달 가능한 SocraticStrategy는 "
            f"{reachable}종뿐이다(개입 2종 + 단계 기본 3종의 합집합·나머지 2종은 생산자 0). "
            "낮은 값이 곧 품질 저하가 아니라 *발문 각도 단조*의 신호다."
        ),
    )


def _strategy_repeat_from_sequences(sequences: list[list[str]]) -> Metric:
    """⑬ 연속 반복률 — 인접한 두 AI 턴의 전략이 같은 비율(순수·날조 0).

    `sequences`는 **대화별** 전략 시퀀스다 — 세션 경계를 넘어 인접쌍을 만들면 서로 다른 학습
    맥락을 이어 붙여 반복을 날조하게 된다. 인접쌍이 `_MIN_STRATEGY_TURNS` 미만이면 NO_DATA.

    높을수록 같은 각도의 발문이 이어졌다는 뜻이다 — 단조 발문 회전(`select_category` 규칙 2.5)이
    실제로 듣는지 보는 계기판이다. 다만 *같은 전략의 반복이 항상 나쁜 것은 아니다*(단계분해는
    연속이 자연스럽다) — 절대 임계가 아니라 추세로 읽는다.
    """
    pairs = 0
    repeats = 0
    for seq in sequences:
        for previous, current in zip(seq, seq[1:], strict=False):
            pairs += 1
            if previous == current:
                repeats += 1
    if pairs < _MIN_STRATEGY_TURNS:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"인접 AI 턴 쌍 {pairs}건 — 표본 부족(최소 {_MIN_STRATEGY_TURNS}쌍)으로 연속 "
                "반복률 산출 불가(가짜 0 아님). 멀티턴 세션이 쌓이면 계측."
            ),
        )
    return Metric(
        value=repeats / pairs,
        status=MetricStatus.MEASURED,
        note=(
            f"대화 내 인접 AI 턴 쌍 {pairs}건 중 전략 동일 {repeats}건(대화 경계 미교차). "
            "높을수록 발문 각도가 단조 — 절대 임계가 아니라 추세로 읽는다(단계분해 연속은 자연)."
        ),
    )


def _state_mismatch_from_counts(mismatched: int, total: int) -> Metric:
    """⑭ 클라 상태 불일치율 — 힌트제공 이벤트 중 `client_state_mismatch=true` 비율(순수).

    PED-04 D2가 Polya 상태를 서버 소유로 되찾으면서 생긴 계기판이다. **불일치는 오류가 아니라
    동기화 신호**이며, 이 비율이 높다는 것은 클라 상태 모델이 서버와 어긋나 있다는 뜻이다
    (S3 파일럿 KPI가 그 상태값에 의존했으므로 측정 신뢰의 직접 지표).

    표본 가드는 두지 않는다 — 비율이 아니라 *존재 여부*가 먼저 중요하고(1건이라도 보이면 조사),
    total==0이면 NO_DATA다.
    """
    if total <= 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=("힌트제공 이벤트 0건 — coach 세션이 쌓이면 클라 상태 불일치율 계측(가짜 0 아님)"),
        )
    return Metric(
        value=mismatched / total,
        status=MetricStatus.MEASURED,
        note=(
            f"힌트제공 이벤트 {total}건 중 클라 제출 polya_state가 서버 파생과 어긋난 건 "
            f"{mismatched}건. 오류가 아니라 *동기화 신호* — 높으면 클라 상태 모델을 점검한다."
        ),
    )


def _hint_depth_from_levels(hint_levels: list[int], reveal_scores: Sequence[float] = ()) -> Metric:
    """⑧ 답 미루기 도달 깊이 — 힌트제공 hint_level의 평균·최대를 Metric으로(순수·날조 0).

    입력 `hint_levels`는 ⑤와 *동일한* 힌트제공 이벤트 hint_level(1~4·graded 노출량) 목록이다
    (호출부가 ⑤용으로 이미 뽑은 시계열을 재사용 — 새 쿼리 0). ⑤가 *기울기*(시간에 따른 도움
    감소 추세)를 본다면, ⑧은 학생이 *실제로 얼마나 깊은 힌트까지 갔는가*(도달 깊이)를 본다 —
    value는 **평균 hint_level**(윈도/스코프 내), note에 **최대 도달 깊이**와 분포 감을 덧붙인다.

    표본 가드(날조 0): 힌트제공 이벤트가 0건이면 **NO_DATA**(value None) — 단순 평균이라 ④(턴당
    토큰)·①(통과율)처럼 total==0만 NO_DATA로 막는다(종단 최소점 요구는 ⑤ 기울기 몫).

    게이밍 캐비엇(정직 표기·CLAUDE.md "정답률·시간만으로 우열 금지"): "낮은 평균 깊이"는 *숙달
    (좋음)* 또는 *힌트 회피(틀려도 낮은 레벨에 머묾·나쁨)* 둘 다일 수 있어 **단독 해석 금지**다.
    이 함정은 이미 R15 결합 판정(`help_reduction_validated`·도움↓×정답률×난이도 교차)이 방어하므로,
    ⑧은 R15와 *함께* 읽어야 한다 — note에 참조를 명시한다(⑧ 자체는 raw 깊이일 뿐).

    S4-11 정밀화(`reveal_scores`): 같은 힌트제공 행에 실린 `reveal_score`(검수 graded 힌트가 실제로
    서빙된 턴에만 있다) 목록이다. value는 **바꾸지 않는다**(KPI 정의 = 평균 hint_level 불변) —
    note에 "기록 m/n건·평균·깊이 환산(3×점수, `l4.hint_content.models.reveal_depth_equivalent`)"을
    병기한다. m=0이면 "기록 0건"을 그대로 적는다(작동한 비율 — 카탈로그 서빙이 한 번도 안 일어난
    것을 숨기지 않는다). 기본 `()`면 구판 호출과 같은 값·같은 병기 문구(기록 0건)다.
    """
    n = len(hint_levels)
    if n == 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "힌트제공 이벤트 0건 — coach 답 미루기(LTHC)가 쌓이면 도달 깊이 계측(가짜 0 아님). "
                "게이밍(힌트 회피)은 R15(help_reduction_validated)가 교차 방어."
            ),
        )
    mean_depth = sum(hint_levels) / n
    max_depth = max(hint_levels)
    scored = len(reveal_scores)
    if scored:
        mean_reveal = sum(reveal_scores) / scored
        reveal_note = (
            f" · reveal_score 기록 {scored}/{n}건(검수 힌트 서빙 턴) 평균 {mean_reveal:.4f}·"
            f"깊이 환산 {reveal_depth_equivalent(mean_reveal):.4f}"
        )
    else:
        reveal_note = f" · reveal_score 기록 0/{n}건(검수 graded 힌트 서빙 없음 — 정적 템플릿만)"
    return Metric(
        value=mean_depth,
        status=MetricStatus.MEASURED,
        note=(
            f"힌트제공 {n}건 hint_level 평균 {mean_depth:.4f}·최대 도달 {max_depth}(1~4 graded·"
            "높을수록 깊은 힌트까지 감). **단독 해석 금지** — 낮은 깊이는 숙달 또는 *힌트 회피*"
            "(교정기 함정) 둘 다일 수 있어 R15(help_reduction_validated)와 함께 읽어야 함(⑧은 "
            "raw 깊이·게이밍 방어는 R15 몫)·세션별 분해는 후속(현재 user/시간창 집계)."
            f"{reveal_note}"
        ),
    )


# ⑯ 결손 복구 리드타임(PED-13)의 두 임계 — **재선언하지 않고 정본에서 가져온다**(acceptance ①).
#   · 숙달 도달 = `l4/lthc/adapt.py`의 `_MASTERED_THRESHOLD`(0.8) — 3구간 라벨의 상단 경계.
#   · 취약 관측 = `l2/prerequisite_recommendation`의
#     `recommend_prerequisite_gaps_detailed`가 가진 `mastery_threshold`
#     기본값(0.7). 이쪽은 모듈 상수가 아니라 *함수 기본 인자*라 시그니처에서 읽는다 — 값을 여기
#     0.7로 베껴 적으면 정본이 바뀌어도 이 파일은 모른 채 남는다(드리프트). 아래 회귀 테스트가
#     두 임계의 출처 일치를 동결한다.
_WEAK_MASTERY_THRESHOLD: float = float(
    inspect.signature(recommend_prerequisite_gaps_detailed).parameters["mastery_threshold"].default
)
_RECOVERY_MASTERY_THRESHOLD: float = float(_MASTERED_THRESHOLD)


def _gap_recovery_leadtimes_from_rows(
    rows: Sequence[tuple[uuid.UUID, uuid.UUID, float, datetime]],
) -> tuple[list[float], int]:
    """⑯ (user,concept)별 '첫 취약 관측 → 첫 숙달 도달' 경과 일수 목록 + 미도달 그룹 수.

    입력은 **(user_id, concept_id) 그룹 내 measured_at 오름차순** 행이다(호출부 order_by 보장).
    각 그룹에서 `mastery < _WEAK_MASTERY_THRESHOLD`인 *첫* 관측을 결손 시점으로 잡고, 그 *이후*
    처음으로 `mastery >= _RECOVERY_MASTERY_THRESHOLD`에 도달한 관측까지의 벽시계 간격을 일수로
    낸다. 신규 컬럼 0 — `measured_at`이 복합 PK라 간격이 원천에서 그대로 나온다.

    처리 규약(acceptance ⑤):
      · **미도달 제외** — 취약은 관측됐으나 0.8에 아직 못 닿은 그룹은 분모에서 뺀다(가짜 0 금지).
        몇 개가 그렇게 빠졌는지는 두 번째 반환값으로 정직하게 보고한다.
      · **첫 도달 고정** — 도달 후 다시 떨어져도 리드타임은 *첫* 도달 기준이다(재하락은 복구
        시간을 늘리지 않는다 — 늘리면 "회복이 오래 걸렸다"로 오독된다).
      · 애초에 취약 관측이 없는 그룹(줄곧 숙달)은 결손이 없어 대상이 아니다.

    ⚠️ '학습 시간'이 아니라 **경과 일수**다 — time-on-task 분모(`duration_seconds`)는 클라
    writer 부재로 존재하지 않는다(태스크 notes). 같은 이유로 이 값을 학습 효율로 읽으면 안 된다.
    """
    weak_at: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {}
    recovered: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
    for user_id, concept_id, mastery, measured_at in rows:
        key = (user_id, concept_id)
        if key in recovered:
            continue  # 첫 도달 고정 — 이후 재하락·재도달은 무시.
        if key not in weak_at:
            if mastery < _WEAK_MASTERY_THRESHOLD:
                weak_at[key] = measured_at
            continue  # 결손 시점 이전의 관측은 리드타임 기산점이 아니다.
        if mastery >= _RECOVERY_MASTERY_THRESHOLD:
            recovered[key] = (measured_at - weak_at[key]).total_seconds() / 86400.0
    unrecovered = len(weak_at) - len(recovered)
    return [recovered[k] for k in weak_at if k in recovered], unrecovered


def _gap_recovery_leadtime_metric(days: list[float], unrecovered: int) -> Metric:
    """⑯ 경과 일수 목록 → Metric(순수·날조 0). 자격 그룹 0이면 NO_DATA(⑨ 관례 승계)."""
    n = len(days)
    if n == 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"결손→숙달 복구가 완료된 (user,concept) 그룹 0개(미도달 {unrecovered}개는 "
                "분모에서 제외 — 가짜 0 금지). 취약 관측(<"
                f"{_WEAK_MASTERY_THRESHOLD}) 후 {_RECOVERY_MASTERY_THRESHOLD} 도달이 쌓이면 계측."
            ),
        )
    mean_days = sum(days) / n
    return Metric(
        value=mean_days,
        status=MetricStatus.MEASURED,
        note=(
            f"{n}개 그룹의 결손→숙달 평균 {mean_days:.2f}일(낮을수록 회복이 빠름)·"
            f"미도달 {unrecovered}개 제외(가짜 0 금지)·첫 도달 기준 고정(재하락 무시). "
            "**학습 시간이 아니라 경과 일수**(time-on-task 분모 부재)·자기 대비 축이며 "
            "또래·평균 대비 파생을 두지 않는다(5원칙 #2·ARCH-27 게이트)."
        ),
    )


def _mastery_gains_from_rows(
    rows: Sequence[tuple[uuid.UUID, uuid.UUID, float]],
) -> list[float]:
    """(user_id, concept_id, mastery) — (user,concept)별 첫→마지막 mastery 차 목록(순수·날조 0).

    입력 `rows`는 **(user_id, concept_id) 그룹 내 measured_at 오름차순**으로 정렬된
    `ConceptMasteryHistory` 행이다(호출부가 order_by user·concept·measured_at으로 조회). 각
    (user,concept) 그룹에서 *첫*(최초 등장=최이른 measured_at) mastery와 *마지막*(최종 덮어쓰기=
    최근 measured_at) mastery의 차(증가량)를 낸다 — 측정점이 `_MIN_MASTERY_POINTS` 미만인 그룹은
    변화 자체가 없어 제외한다(가짜 0/증가량 금지).

    순수·O(n): first/last/counts 3딕셔너리로 한 패스. 반환은 자격 그룹의 증가량 목록(양수=숙달
    상승·음수=하락·0=평탄[실측된 평탄이지 날조 0 아님]). 시간 간격 정규화(Δmastery/Δt rate)는
    하지 않는다 — 그건 후속(measured_at 간격이 그룹마다 달라 비교 가능한 rate엔 추가 설계 필요).
    """
    first: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
    last: dict[tuple[uuid.UUID, uuid.UUID], float] = {}
    counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for user_id, concept_id, mastery in rows:
        key = (user_id, concept_id)
        if key not in first:  # 그룹 내 measured_at 오름차순이라 첫 등장 = 최이른 측정.
            first[key] = mastery
        last[key] = mastery  # 매번 덮어써 최종 = 최근 측정.
        counts[key] = counts.get(key, 0) + 1
    return [last[key] - first[key] for key in first if counts[key] >= _MIN_MASTERY_POINTS]


def _mastery_gain_from_gains(gains: list[float]) -> Metric:
    """⑨ BKT 숙달 증가율 — (user,concept)별 mastery 증가량의 평균을 Metric으로(순수·날조 0).

    입력 `gains`는 `_mastery_gains_from_rows`가 낸 자격 그룹(≥`_MIN_MASTERY_POINTS`점)의 첫→
    마지막 mastery 차 목록이다. value = 증가량 평균(양수=평균적으로 숙달 상승). 자격 그룹이 0이면
    **NO_DATA**(value None·가짜 0 금지) — mastery 시계열이 아직 그룹당 2점을 못 채운 상태.

    정직 note(중요): 이는 *증가 방향·크기*(mean Δmastery)이지 **measured_at 간격으로 나눈 시간
    정규화 rate가 아니다** — "증가율"의 rate는 그룹마다 다른 측정 간격을 정규화해야 비교 가능하고
    그건 후속 설계다. 또 mastery는 BKT/능력추정 파생이라 모델 가정(전이·망각)에 의존한다(원천
    `ConceptMasteryHistory`는 append-only 시계열). 세션별 분해가 아니라 user/시간창 집계다.
    """
    n = len(gains)
    if n == 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                f"자격 (user,concept) 그룹(≥{_MIN_MASTERY_POINTS}점) 0개 — mastery 시계열이 그룹당 "
                "before/after 2점을 못 채움. 측정이 쌓이면 숙달 증가량 계측(가짜 0/증가량 금지)."
            ),
        )
    mean_gain = sum(gains) / n
    return Metric(
        value=mean_gain,
        status=MetricStatus.MEASURED,
        note=(
            f"(user,concept) {n}개 그룹 첫→마지막 mastery 차 평균 {mean_gain:+.4f}(양수=숙달↑). "
            "**증가 방향·크기이지 시간 정규화 rate 아님**(measured_at 간격 정규화는 후속)·"
            "mastery는 BKT 파생(모델 가정 의존)·세션별 분해는 후속(현재 user/시간창 집계)."
        ),
    )


def _misconception_resolution_from_counts(inactive: int, total: int) -> Metric:
    """⑩ 오개념 해소율 — 비활성(is_active=false) 가설 비율을 Metric으로(순수·날조 0).

    입력은 (비활성 수, 전체 수) — `MisconceptionHypothesisRecord`에서 호출부가 센다. value =
    inactive/total(비활성 비율). total==0이면 **NO_DATA**(value None·가짜 0 회피).

    정직 note(중요): is_active=false는 *해소의 근사*다 — 저장소가 가설을 **가지치기(stale 정리·
    낙인 방지)**할 때 행을 지우지 않고 비활성화하는 신호를 재사용한다(모델 `misconception_
    hypothesis`의 `is_active` 컨벤션). **전용 resolved_at/사유 컬럼이 없어** "학생이 실제로 오개념을
    극복한 해소"와 "증거 부족으로 stale 정리된 비활성화"를 구분하지 못한다 — note에 근사임을
    정직 표기한다(후속: 해소 사유·resolved_at 컬럼). confidence<임계 가지치기도 비활성화로 수렴하나
    본 지표는 is_active 단일 신호만 쓴다(정의 단순·과대해석 금지).
    """
    if total <= 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "오개념 가설 0건 — 활성 가설이 쌓이면 해소(비활성화) 비율 계측(가짜 0 아님). "
                "is_active=false=해소 *근사*(resolved_at 컬럼 부재)."
            ),
        )
    rate = inactive / total
    return Metric(
        value=rate,
        status=MetricStatus.MEASURED,
        note=(
            f"오개념 가설 {total}건 중 비활성(is_active=false) {inactive}건={rate:.4f}(해소 근사). "
            "**해소 근사** — is_active=false는 가지치기(stale 정리·낙인 방지) 신호 재사용이라 "
            "'학습적 해소'와 'stale 비활성화'를 구분 못 함(resolved_at 컬럼 부재·후속)·updated_at "
            "시간창 기준·세션별 분해는 후속(현재 user/시간창 집계)."
        ),
    )


def _self_solve_from_counts(self_solved: int, resolved_total: int) -> Metric:
    """⑪ 스스로 풀이 도달율 — resolution=학생자력해결 비율을 Metric으로(순수·날조 0).

    입력은 (자력해결 수, 결말 도달 세션 수) — `Dialogue.resolution`에서 호출부가 센다. **분모는
    resolution이 채워진(결말 도달) 세션**이다(resolution NULL=결말 미보고는 제외 — "자력해결
    아님"이 아니라 "결말 미상"이라 분모에서 뺀다·③ 완주율이 전체 세션을 분모로 쓰는 것과 *다른*
    선택: 여기선 NULL을 0으로 세면 미보고를 실패로 왜곡하므로 가짜 0 금지 규약상 제외한다).
    value = self_solved/resolved_total. resolved_total==0이면 **NO_DATA**(value None·가짜 0 회피).

    정직 note(중요): resolution은 **클라이언트 보고**다(`PATCH /v1/me/dialogues/{id}/end`가 적재·
    ⑥ 자기보고 확신도와 동형) — 서버가 정답성·hint_level 신호로 판정한 게 아니다(그 신호의
    dialogue 귀속·포기 영속은 후속). `Socratic유도성공`(유도로 도달)은 자력해결과 *별개 축*이라
    분자에 넣지 않는다 — 필요 시 후속에서 5종 분해로 노출(과대해석 금지·세션별 집계는 후속).
    """
    if resolved_total <= 0:
        return Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "resolution 채워진(결말 도달) 대화 0건 — 종료 시 resolution 보고가 쌓이면 "
                "자력해결 비율 계측(가짜 0 아님). resolution은 클라이언트 보고(서버 미판정)."
            ),
        )
    rate = self_solved / resolved_total
    return Metric(
        value=rate,
        status=MetricStatus.MEASURED,
        note=(
            f"결말 도달 대화 {resolved_total}건 중 학생자력해결 {self_solved}건={rate:.4f}. "
            "resolution은 **클라이언트 보고**(PATCH .../end 적재·서버가 정답성/hint_level로 판정 "
            "아님·그 신호 귀속은 후속)·분모=resolution NOT NULL(미보고 NULL은 제외·실패로 왜곡 "
            "금지)·Socratic유도성공은 별개 축(분자 제외)·세션별 분해는 후속(현재 user/시간창 집계)."
        ),
    )


async def compute_wh1_surrogate_metrics(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    mode: str | None = None,
) -> SurrogateMetrics:
    """WH-1 0단계 대리 지표 7종을 계산 — 7종 모두 계측 좌석 가동(⑦은 *근사*·정직 표기).

    설계안 §8.4 0단계 베이스라인. **계측 가능(①②③④⑤⑥⑦)을 실값**으로 내되, 표본 0/부족이면
    value=None + status(NO_DATA) + note로 갭을 가시화한다(CLAUDE.md "모르면 모른다"·설계안 "측정
    없는 도입 없음" — 0/stub 날조 금지). ⑦(전이 점수)은 ProblemAttempt ⨝ Problem.signature_
    patterns에서 *같은 패턴·다른 problem_id·사전 노출 후 초견(첫 시도) 정답률*을 근사해
    REQUIRES_TOOL→MEASURED(근사)가 됐다 — **설계 §11.5 완전판(assign_transfer_probe·BKT≥0.95+2주
    스케줄)과 다른 근사**(마킹/스케줄 도구 미구현·전이 프로브<`_MIN_TRANSFER_PROBES`면 NO_DATA·새
    적재 0). ⑤(도움 감소 곡선)는 힌트제공 이벤트 적재 슬라이스로
    NOT_INSTRUMENTED→MEASURED가 됐다(표본 부족이면 NO_DATA·R15 교차검증 미반영). ⑥(보정 점수
    Brier)는 ProblemAttempt.confidence_self_reported·is_correct 기존 필드 파생으로
    REQUIRES_TOOL→MEASURED가 됐다(유효 쌍<`_MIN_CALIBRATION_SAMPLES`면 NO_DATA·새 수집 0).
    ②(진단-실제 오개념 일치율)는 *오프라인 진단정확도*(라벨 프로브 substring recall)로
    REQUIRES_DATA→MEASURED(오프라인)가 됐다 — **LIVE 학생별 ground-truth가 아니라 시스템 진단엔진
    품질 지표**(전 user 동일값·user/since/until 무관·DB 0). LIVE per-user 일치율은 문항-오개념
    태깅·attempt별 진단 기록 부재로 여전히 데이터 기반 없음(후속)·recall 프로브 0건이면 NO_DATA.

    Args:
        session: 조회 전용 AsyncSession(쓰기 없음·ORM/쿼리빌더만·원시 SQL 회피).
        user_id: 지정 시 그 user 본인 집계, None이면 코호트 전체(ops/스크립트).
        since/until: 집계 시간창(started_at 기준·inclusive·생략 시 무한). TZ 검증은 노출
            계층(api/me·time_window_conditions)이 수행 — 여기선 받은 경계를 그대로 비교.
        mode: S3-03 응용 모드 스코프(예: "suneung"). 설정 시 *attempt_event 기반 지표*
            (① verify·⑤ 도움 감소·⑧ 도달 깊이)를 `event_data->>'mode' == mode`로 필터한다
            (수능 세션만 집계). **다른 지표(③④⑥⑦⑨⑩⑪·R15)는 아직 mode를 싣지 않아 mode 무관
            집계 그대로**다 — 완전한 mode별 집계는 후속 S3-04(여기선 데이터가 mode를 실어나르는
            것을 보장하고 그 데이터를 scope할 수 있음을 증명). None(기본)이면 전 mode 포함(회귀 0).

    Returns:
        SurrogateMetrics — 7 지표(각 Metric) + 표본 수·시간창·user 스코핑 메타.

    계측 가능(MEASURED 가능):
        ① verify_pass_rate: attempt_event(event_type=검산결과) 중 event_data->>'passed'=true
           비율(passed=거짓 수치관계 *미적발*·binary 검산·3-state 아님). total==0이면 NO_DATA
           (값 None·날조 회피)·아니면 MEASURED(passed/total). event_at 기준 시간창·user 필터.
        ③ session_completion_rate: LearningSession 중 ended_at IS NOT NULL 비율. total==0이면
           NO_DATA(value None·날조 회피)·아니면 MEASURED(completed/total).
        ④ tokens_per_turn: total_tokens IS NOT NULL AND total_turns > 0인 Dialogue에서
           AVG(total_tokens/total_turns). 해당 행 0이면 NO_DATA(현재 토큰 미적재면 정직하게
           NO_DATA·0 아님)·있으면 MEASURED.
        ⑤ help_reduction_slope: attempt_event(event_type=힌트제공)의 hint_level을 event_at
           오름차순으로 뽑아 OLS 단순선형회귀 기울기(음수=도움 감소=개선). 유효 포인트가
           `_MIN_SLOPE_POINTS` 미만이거나 x 분산 0이면 NO_DATA(날조 회피)·아니면 MEASURED.
           raw 기울기일 뿐 R15 정확률 교차검증은 미반영(후속).
        ⑥ calibration_brier: ProblemAttempt 중 confidence_self_reported·is_correct 둘 다 NOT
           NULL인 쌍에서 Brier=mean((confidence−is_correct)²)(낮을수록 잘 보정). 유효 쌍이
           `_MIN_CALIBRATION_SAMPLES` 미만이면 NO_DATA(가짜 0/Brier 금지)·아니면 MEASURED.
           기존 필드 파생일 뿐 과신/과소신 구간 코칭(§11.4)은 미반영(후속).
        ② diagnosis_agreement_rate: *오프라인·시스템 지표*(DB 0). `probes.compute_diagnostic_recall`
           이 라벨 recall 프로브(expected_id 설정·틀린 진술)에 substring 매처 `diagnose`를 돌려
           top-1 매치 id==expected_id 비율(recall)을 낸다. **LIVE 학생별 ground-truth 아님**(전
           user 동일값·user_id/since/until 무관)·recall 프로브 0건이면 NO_DATA(가짜 0 회피)·
           substring은 보수적 기준선·FP율/precision은 semantic_eval 별도(여기선 recall 프로브만).
        ⑦ transfer_score: *근사* 전이 점수. is_correct NOT NULL ProblemAttempt를 Problem(problem_id
           join)에 붙여 (problem_id, signature_patterns, is_correct)를 started_at 오름차순으로 뽑아,
           Python 순수로 전이 프로브(같은 패턴 P·다른 problem_id·사전 노출 후 초견[첫 시도])를
           식별하고 그 정답률을 낸다. 전이 프로브가 `_MIN_TRANSFER_PROBES` 미만이면 NO_DATA(가짜
           0/정답률 금지)·아니면 MEASURED. **설계 §11.5 완전판(assign_transfer_probe·노드 BKT≥0.95
           +2주 후 자동 출제)과 다른 근사**(마킹/스케줄 도구 미구현이라 풀이 이력에서 근사·표면
           상이는 *다른 problem_id*로 근사·심층구조 동일성은 패턴 태그 의존·BKT 게이팅 미반영·후속).
    """
    # ── ③ 세션 완주율 (LearningSession.ended_at NOT NULL 비율) ──
    session_conds = []
    if user_id is not None:
        session_conds.append(LearningSession.user_id == user_id)
    if since is not None:
        session_conds.append(LearningSession.started_at >= since)
    if until is not None:
        session_conds.append(LearningSession.started_at <= until)

    total_sessions = (
        await session.execute(
            select(func.count()).select_from(LearningSession).where(*session_conds)
        )
    ).scalar() or 0
    completed_sessions = (
        await session.execute(
            select(func.count())
            .select_from(LearningSession)
            .where(*session_conds, LearningSession.ended_at.isnot(None))
        )
    ).scalar() or 0

    if total_sessions == 0:
        session_completion = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note="집계 시간창·범위에 LearningSession 0건 — 표본이 쌓이면 완주율 계측(가짜 0 아님).",
        )
    else:
        session_completion = Metric(
            value=completed_sessions / total_sessions,
            status=MetricStatus.MEASURED,
            note=(
                f"완주(ended_at NOT NULL) {completed_sessions}/{total_sessions}건 — "
                "LearningSession.ended_at 채워진 비율(실측 베이스라인)."
            ),
        )

    # ── ④ 턴당 토큰 (Dialogue.total_tokens/total_turns 평균) ──
    dialogue_conds = [
        Dialogue.total_tokens.isnot(None),
        Dialogue.total_turns.isnot(None),
        Dialogue.total_turns > 0,
    ]
    if user_id is not None:
        dialogue_conds.append(Dialogue.user_id == user_id)
    if since is not None:
        dialogue_conds.append(Dialogue.started_at >= since)
    if until is not None:
        dialogue_conds.append(Dialogue.started_at <= until)

    # 토큰·턴이 채워진 행만 집계 — AVG(total_tokens::float / total_turns)와 표본 수를 한 행으로.
    token_row = (
        await session.execute(
            select(
                func.avg(cast(Dialogue.total_tokens, Float) / Dialogue.total_turns),
                func.count(),
            )
            .select_from(Dialogue)
            .where(*dialogue_conds)
        )
    ).one()
    avg_tokens_per_turn, sample_dialogues_raw = token_row
    sample_dialogues = int(sample_dialogues_raw or 0)

    if sample_dialogues == 0 or avg_tokens_per_turn is None:
        tokens_metric = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=(
                "total_tokens·total_turns 채워진 Dialogue 0건 — 현재 토큰 미적재 가능성. 적재되면 "
                "턴당 토큰 계측(가짜 0 아님)."
            ),
        )
    else:
        tokens_metric = Metric(
            value=float(avg_tokens_per_turn),
            status=MetricStatus.MEASURED,
            note=(
                f"{sample_dialogues}개 대화 AVG(total_tokens/total_turns) — 비용 대리 지표"
                "(실측 베이스라인)."
            ),
        )

    # ── ① verify 통과율 (attempt_event event_type=검산결과 중 passed=true 비율) ──
    # 한 행으로 (passed_count, total_count)를 뽑는다 — passed는 event_data->>'passed'를 boolean으로
    # 캐스팅(JSONB 접근도 쿼리빌더로·원시 SQL 문자열 회피). FILTER로 passed=true만 센다.
    verify_conds = [AttemptEvent.event_type == EventType.검산결과]
    if user_id is not None:
        verify_conds.append(AttemptEvent.user_id == user_id)
    if since is not None:
        verify_conds.append(AttemptEvent.event_at >= since)
    if until is not None:
        verify_conds.append(AttemptEvent.event_at <= until)
    # S3-03: mode 스코프 — event_data->>'mode'가 요청 mode와 일치하는 검산결과만(수능 세션).
    # 태그 없는(구) 이벤트나 mode=null은 as_string()이 NULL이라 == 비교에서 제외된다(정확).
    if mode is not None:
        verify_conds.append(AttemptEvent.event_data["mode"].as_string() == mode)

    verify_row = (
        await session.execute(
            select(
                func.count().filter(AttemptEvent.event_data["passed"].as_boolean().is_(True)),
                func.count(),
            )
            .select_from(AttemptEvent)
            .where(*verify_conds)
        )
    ).one()
    passed_count_raw, verify_total_raw = verify_row
    passed_count = int(passed_count_raw or 0)
    verify_total = int(verify_total_raw or 0)

    if verify_total == 0:
        verify_metric = Metric(
            value=None,
            status=MetricStatus.NO_DATA,
            note=("검산결과 이벤트 0건 — coach 풀이 제출이 쌓이면 통과율 계측(가짜 0 아님)."),
        )
    else:
        verify_metric = Metric(
            value=passed_count / verify_total,
            status=MetricStatus.MEASURED,
            note=(
                f"검산결과 이벤트 기반 — passed(거짓 수치관계 *미적발*) {passed_count}/"
                f"{verify_total}건. binary 검산(값·계산식 불변·풀이 제출 턴 한정). 3상태"
                "(correct/incorrect/unverifiable) 파생 회계는 S4-19 병기 — "
                "compute_step_verification_accounting(내부 리포트 전용·학생 라우트 비노출)."
            ),
        )

    # ── ⑤ 도움 감소 곡선 (attempt_event event_type=힌트제공의 hint_level OLS 기울기) ──
    # event_at 오름차순으로 hint_level(event_data->>'hint_level'을 integer 캐스팅·쿼리빌더로 접근·
    # 원시 SQL 문자열 회피) 시계열을 뽑아 Python에서 순수 OLS 기울기를 계산한다. 기울기 산출은
    # _help_reduction_from_levels(종단 표본 가드·날조 0)에 위임.
    hint_conds = [AttemptEvent.event_type == EventType.힌트제공]
    if user_id is not None:
        hint_conds.append(AttemptEvent.user_id == user_id)
    if since is not None:
        hint_conds.append(AttemptEvent.event_at >= since)
    if until is not None:
        hint_conds.append(AttemptEvent.event_at <= until)
    # S3-03: mode 스코프 — verify와 동형(⑤ 도움 감소·⑧ 도달 깊이의 mode-scoped 집계 데이터).
    if mode is not None:
        hint_conds.append(AttemptEvent.event_data["mode"].as_string() == mode)

    hint_rows = (
        await session.execute(
            select(
                AttemptEvent.event_data["hint_level"].as_integer(),
                # PED-04 ⑭: 같은 행에 실린 D2 불일치 태그를 함께 뽑는다(신규 쿼리 0).
                AttemptEvent.event_data["client_state_mismatch"].as_boolean(),
                # S4-11: 같은 행의 reveal_score(검수 힌트 서빙 턴만 존재 — 신규 쿼리 0).
                AttemptEvent.event_data["reveal_score"].as_float(),
            )
            .select_from(AttemptEvent)
            .where(*hint_conds)
            .order_by(AttemptEvent.event_at.asc())
        )
    ).all()
    # JSONB 파싱 실패(키 부재 등)로 None이 섞일 수 있으니 정수만 채택(날조 회피·결손 행 제외).
    hint_levels = [int(row[0]) for row in hint_rows if row[0] is not None]
    help_reduction = _help_reduction_from_levels(hint_levels)

    # ── ⑭ 클라 상태 불일치율 (PED-04 D2·⑤와 같은 행 재사용·신규 쿼리 0) ──
    # 키가 없는 구(舊) 이벤트는 None → False로 읽는다(태그 도입 전 행 = 불일치 미관측).
    state_mismatch_metric = _state_mismatch_from_counts(
        sum(1 for row in hint_rows if row[1] is True), len(hint_rows)
    )

    # ── ⑧ 답 미루기 도달 깊이 (⑤와 동일 hint_levels 재사용·새 쿼리 0) ──
    # ⑤가 hint_level *기울기*(도움 감소 추세)를 본다면 ⑧은 *도달 깊이*(평균·최대)를 본다 —
    # 같은 시계열의 다른 집계(순수 함수 위임·표본은 sample_hint_events 공유). 게이밍(힌트 회피)
    # 방어는 R15(help_reduction_validated) 몫이라 ⑧은 단독 해석 금지(note 표기).
    # S4-11: reveal_score 열(3번째)이 없는 행 형태(구 픽스처)는 기록 없음으로 읽는다.
    reveal_scores = [
        float(row[2])
        for row in hint_rows
        if row[0] is not None and len(row) > 2 and row[2] is not None
    ]
    hint_depth = _hint_depth_from_levels(hint_levels, reveal_scores)

    # ── ⑮ 도움 요청 대 제공 비 (attempt_event event_type=힌트요청 개수·⑤와 동형 scope) ──
    # S3-16 소생 — 힌트요청(demand)이 휴면에서 생산자를 얻으며 연 형제 좌석. 분모(supply)는
    # 위 ⑤ hint_rows와 동일 힌트제공 표본(len(hint_levels))을 재사용한다(새 쿼리 0).
    demand_conds = [AttemptEvent.event_type == EventType.힌트요청]
    if user_id is not None:
        demand_conds.append(AttemptEvent.user_id == user_id)
    if since is not None:
        demand_conds.append(AttemptEvent.event_at >= since)
    if until is not None:
        demand_conds.append(AttemptEvent.event_at <= until)
    # S3-03: mode 스코프 — ⑤⑧과 동형(수능 세션만 집계).
    if mode is not None:
        demand_conds.append(AttemptEvent.event_data["mode"].as_string() == mode)

    demand_total = (
        await session.execute(select(func.count()).select_from(AttemptEvent).where(*demand_conds))
    ).scalar() or 0
    demand_total = int(demand_total)
    help_demand_supply = _help_demand_supply_ratio_from_counts(demand_total, len(hint_levels))

    # ── R15 결합 판정 (⑤ 도움 감소 × 정답률 추세) ──
    # 정답률 신호 = ProblemAttempt.is_correct(실제 정답률·① 검산 proxy보다 직접적·R15의
    # "정답률"에 정확히 대응). is_correct IS NOT NULL(미응답=NULL 제외)·started_at 오름차순으로
    # 뽑아 1.0/0.0 시퀀스 → _ols_slope로 정답률 기울기. user_id/since/until은 started_at 기준
    # (ProblemAttempt.started_at). ⑤ help_slope는 _ols_slope(hint_levels) raw 기울기(_help_
    # reduction_from_levels의 Metric.value와 동일한 코어·NO_DATA면 None). 둘을 _judge_r15로 교차.
    accuracy_conds: list[ColumnElement[bool]] = [ProblemAttempt.is_correct.isnot(None)]
    if user_id is not None:
        accuracy_conds.append(ProblemAttempt.user_id == user_id)
    if since is not None:
        accuracy_conds.append(ProblemAttempt.started_at >= since)
    if until is not None:
        accuracy_conds.append(ProblemAttempt.started_at <= until)

    accuracy_rows = (
        await session.execute(
            select(ProblemAttempt.is_correct)
            .select_from(ProblemAttempt)
            .where(*accuracy_conds)
            .order_by(ProblemAttempt.started_at.asc())
        )
    ).all()
    # is_correct(bool)를 1.0/0.0 시퀀스로(None은 IS NOT NULL 필터로 이미 제외·방어적 재확인).
    accuracy_series = [1.0 if row[0] else 0.0 for row in accuracy_rows if row[0] is not None]
    help_slope = _ols_slope([float(level) for level in hint_levels])
    accuracy_slope = _ols_slope(accuracy_series)

    # ── R15 난이도 추세 (정답률과 같은 ProblemAttempt 집합을 Problem JOIN해 유효 b OLS) ──
    # "쉬운 문제로 갈아타 정답률 유지" gaming을 잡는 3번째 신호. 같은 user_id/시간창 필터·started_at
    # 오름차순으로, ProblemAttempt를 Problem(problem_id join)에 붙여 irt_difficulty_b·difficulty_
    # overall을 가져온다. resolve_item_difficulty_b로 유효 b를 해석 — *보정 b 우선·휴리스틱 폴백·
    # 둘 다 None이면 None*. None인 attempt는 난이도 시계열에서 제외(정답률 표본과 표본이 다를 수
    # 있음·is_correct는 NULL만 제외하지만 난이도는 problem_id NULL·b 둘 다 None도 제외). ORM
    # join만(원시 SQL 0). 정답률 쿼리와 별도 조회 — 제외 규칙이 달라 표본이 어긋나도 메타로 분리.
    difficulty_rows = (
        await session.execute(
            select(Problem.irt_difficulty_b, Problem.difficulty_overall)
            .select_from(ProblemAttempt)
            .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
            .where(*accuracy_conds)
            .order_by(ProblemAttempt.started_at.asc())
        )
    ).all()
    # 각 행의 (보정 b, 휴리스틱 difficulty)를 유효 b로 해석 — None(둘 다 부재)이면 시계열 제외.
    # Numeric(difficulty_overall)은 Decimal일 수 있어 float 변환은 resolve_item_difficulty_b가 처리.
    difficulty_series = [
        b
        for irt_b, difficulty in difficulty_rows
        if (b := resolve_item_difficulty_b(irt_b, difficulty)) is not None
    ]
    difficulty_slope = _ols_slope(difficulty_series)

    help_reduction_validated = _judge_r15(help_slope, accuracy_slope, difficulty_slope)

    # ── ⑥ 보정 점수(Brier) (ProblemAttempt.confidence_self_reported × is_correct) ──
    # 자기보고 확신도(0~1·예측)와 실제 정오답(is_correct·실제)이 *둘 다 채워진* 행만 뽑아
    # Brier=mean((conf−correct)²)를 Python 순수 계산(_calibration_from_pairs·날조 0)에 위임한다.
    # func.power 이식성 우려를 피해 쌍을 fetch→순수 평균(원시 SQL 문자열 0·ORM/쿼리빌더만).
    # confidence_self_reported는 Numeric(3,2)라 런타임 Decimal일 수 있어 float로 변환한다.
    # user_id/since/until은 started_at 기준(정답률·난이도 쿼리와 동일 필터 패턴·R15와 동형).
    calibration_conds: list[ColumnElement[bool]] = [
        ProblemAttempt.confidence_self_reported.isnot(None),
        ProblemAttempt.is_correct.isnot(None),
    ]
    if user_id is not None:
        calibration_conds.append(ProblemAttempt.user_id == user_id)
    if since is not None:
        calibration_conds.append(ProblemAttempt.started_at >= since)
    if until is not None:
        calibration_conds.append(ProblemAttempt.started_at <= until)

    calibration_rows = (
        await session.execute(
            select(
                ProblemAttempt.confidence_self_reported,
                ProblemAttempt.is_correct,
            )
            .select_from(ProblemAttempt)
            .where(*calibration_conds)
        )
    ).all()
    # (conf, is_correct) 쌍 — 둘 다 NOT NULL 필터를 통과한 행만(방어적 재확인·None 제외).
    calibration_pairs: list[tuple[float, bool]] = [
        (float(conf), bool(correct))
        for conf, correct in calibration_rows
        if conf is not None and correct is not None
    ]
    calibration_brier = _calibration_from_pairs(calibration_pairs)

    # ── ⑦ 근사 전이 점수 (ProblemAttempt ⨝ Problem.signature_patterns·초견 동형 정답률) ──
    # 같은 시그니처 패턴·다른 problem_id·사전 노출 후 초견(첫 시도) 정답률을 *근사*한다(설계 §11.5
    # 완전판의 assign_transfer_probe·BKT≥0.95+2주 스케줄과 다름 — 마킹/스케줄 도구 미구현). user의
    # is_correct NOT NULL ProblemAttempt를 Problem(problem_id join)에 붙여 (problem_id, signature_
    # patterns, is_correct)를 **started_at 오름차순**으로 뽑고(정답률·난이도 쿼리와 동일 필터·
    # 정렬·R15와 동형), Python 순수로 전이 프로브를 식별한다(_identify_transfer_probes). ORM join
    # 만(원시 SQL 0). is_correct는 NOT NULL이라 bool로 좁혀 받는다(R15 정답률 필터 조건 재사용).
    transfer_rows = (
        await session.execute(
            select(
                ProblemAttempt.problem_id,
                Problem.signature_patterns,
                ProblemAttempt.is_correct,
            )
            .select_from(ProblemAttempt)
            .join(Problem, ProblemAttempt.problem_id == Problem.problem_id)
            .where(*accuracy_conds)
            .order_by(ProblemAttempt.started_at.asc())
        )
    ).all()
    # is_correct는 accuracy_conds(IS NOT NULL)로 이미 좁혀졌으나 방어적으로 bool() 변환(None→False
    # 가 아니라 필터로 None이 없음을 신뢰·타입 좁히기). 식별은 순수 함수에 위임(날조 0).
    transfer_input: list[tuple[uuid.UUID | None, list[SignaturePattern] | None, bool]] = [
        (problem_id, patterns, bool(is_correct))
        for problem_id, patterns, is_correct in transfer_rows
    ]
    transfer_outcomes = _identify_transfer_probes(transfer_input)
    transfer_score = _transfer_from_probes(transfer_outcomes)

    # ── ⑨ BKT 숙달 증가율 (ConceptMasteryHistory (user,concept)별 첫→마지막 mastery 차 평균) ──
    # mastery NOT NULL 행을 (user_id, concept_id, measured_at) 오름차순으로 뽑아 Python 순수로
    # 그룹별 첫→마지막 차(증가량)를 낸다(_mastery_gains_from_rows·날조 0). 시간창은 measured_at
    # 기준(활동 started_at이 아니라 측정 시각·이 원천의 자연 시간축)·ORM/쿼리빌더만(원시 SQL 0).
    # mastery는 Numeric(3,2)라 런타임 Decimal일 수 있어 float로 변환한다(None은 필터로 제외).
    mastery_conds: list[ColumnElement[bool]] = [ConceptMasteryHistory.mastery.isnot(None)]
    if user_id is not None:
        mastery_conds.append(ConceptMasteryHistory.user_id == user_id)
    if since is not None:
        mastery_conds.append(ConceptMasteryHistory.measured_at >= since)
    if until is not None:
        mastery_conds.append(ConceptMasteryHistory.measured_at <= until)

    mastery_rows = (
        await session.execute(
            select(
                ConceptMasteryHistory.user_id,
                ConceptMasteryHistory.concept_id,
                ConceptMasteryHistory.mastery,
                # ⑯(PED-13) 결손 복구 리드타임용 — 같은 조회를 재사용한다(추가 왕복 0).
                ConceptMasteryHistory.measured_at,
            )
            .select_from(ConceptMasteryHistory)
            .where(*mastery_conds)
            .order_by(
                ConceptMasteryHistory.user_id.asc(),
                ConceptMasteryHistory.concept_id.asc(),
                ConceptMasteryHistory.measured_at.asc(),
            )
        )
    ).all()
    # (user, concept, mastery) — 그룹 내 measured_at 오름차순(order_by 보장). None은 방어적 제외.
    mastery_input: list[tuple[uuid.UUID, uuid.UUID, float]] = [
        (user, concept, float(mastery))
        for user, concept, mastery, _measured_at in mastery_rows
        if mastery is not None
    ]
    mastery_gains = _mastery_gains_from_rows(mastery_input)
    mastery_gain_metric = _mastery_gain_from_gains(mastery_gains)

    # ── ⑯ 결손 복구 리드타임 (PED-13) — 위와 *같은* 행에서 measured_at을 함께 쓴다 ──
    leadtime_input: list[tuple[uuid.UUID, uuid.UUID, float, datetime]] = [
        (user, concept, float(mastery), measured_at)
        for user, concept, mastery, measured_at in mastery_rows
        if mastery is not None and measured_at is not None
    ]
    leadtime_days, leadtime_unrecovered = _gap_recovery_leadtimes_from_rows(leadtime_input)
    gap_recovery_leadtime_metric = _gap_recovery_leadtime_metric(
        leadtime_days, leadtime_unrecovered
    )

    # ── ⑩ 오개념 해소율 (MisconceptionHypothesisRecord is_active=false 비율) ──
    # (비활성 수, 전체 수)를 한 행으로 — is_active=false=해소 *근사*(가지치기·비활성화 신호 재사용·
    # resolved_at 컬럼 부재). 시간창은 updated_at 기준(가설이 마지막으로 갱신[해소 전이 포함]된
    # 시각)·user 필터. FILTER로 비활성만 센다(① verify 통과 카운트 동형·쿼리빌더만).
    misconception_conds: list[ColumnElement[bool]] = []
    if user_id is not None:
        misconception_conds.append(MisconceptionHypothesisRecord.user_id == user_id)
    if since is not None:
        misconception_conds.append(MisconceptionHypothesisRecord.updated_at >= since)
    if until is not None:
        misconception_conds.append(MisconceptionHypothesisRecord.updated_at <= until)

    misconception_row = (
        await session.execute(
            select(
                func.count().filter(MisconceptionHypothesisRecord.is_active.is_(False)),
                func.count(),
            )
            .select_from(MisconceptionHypothesisRecord)
            .where(*misconception_conds)
        )
    ).one()
    misconception_inactive_raw, misconception_total_raw = misconception_row
    misconception_inactive = int(misconception_inactive_raw or 0)
    misconception_total = int(misconception_total_raw or 0)
    misconception_resolution = _misconception_resolution_from_counts(
        misconception_inactive, misconception_total
    )

    # ── ⑪ 스스로 풀이 도달율 (Dialogue.resolution=학생자력해결 비율·클라이언트 보고) ──
    # (자력해결 수, resolution 채워진 세션 수)를 한 행으로 — 분모는 resolution NOT NULL(결말 도달)
    # 세션이다(미보고 NULL은 제외·실패로 왜곡 금지·가짜 0 회피). resolution은 PATCH .../end가
    # 적재한 *클라이언트 보고*(서버 미판정). 시간창은 started_at 기준(④ 토큰과 동일 Dialogue
    # 필터)·user 필터. FILTER로 학생자력해결·NOT NULL을 각각 센다(⑩ 동형·쿼리빌더만·원시 SQL 0).
    self_solve_conds: list[ColumnElement[bool]] = [Dialogue.resolution.isnot(None)]
    if user_id is not None:
        self_solve_conds.append(Dialogue.user_id == user_id)
    if since is not None:
        self_solve_conds.append(Dialogue.started_at >= since)
    if until is not None:
        self_solve_conds.append(Dialogue.started_at <= until)

    self_solve_row = (
        await session.execute(
            select(
                func.count().filter(Dialogue.resolution == Resolution.학생자력해결),
                func.count(),
            )
            .select_from(Dialogue)
            .where(*self_solve_conds)
        )
    ).one()
    self_solved_raw, resolved_total_raw = self_solve_row
    self_solved = int(self_solved_raw or 0)
    resolved_total = int(resolved_total_raw or 0)
    self_solve = _self_solve_from_counts(self_solved, resolved_total)

    # ── ⑫⑬ 발문 전략 지표 (PED-04 D1 writer가 적재한 socratic_strategy의 첫 reader) ──
    # 대화별 시퀀스로 뽑는다 — ⑬ 인접쌍이 세션 경계를 넘으면 서로 다른 학습 맥락을 이어 붙여
    # 반복을 날조한다. 본문 컬럼은 조회하지 않는다(컬럼 투영·복호 0).
    strategy_conds: list[ColumnElement[bool]] = [DialogueTurn.socratic_strategy.is_not(None)]
    if user_id is not None:
        strategy_conds.append(Dialogue.user_id == user_id)
    if since is not None:
        strategy_conds.append(Dialogue.started_at >= since)
    if until is not None:
        strategy_conds.append(Dialogue.started_at <= until)
    strategy_rows = (
        await session.execute(
            select(DialogueTurn.dialogue_id, DialogueTurn.socratic_strategy)
            .join(Dialogue, DialogueTurn.dialogue_id == Dialogue.dialogue_id)
            .where(*strategy_conds)
            .order_by(DialogueTurn.dialogue_id, DialogueTurn.turn_order)
        )
    ).all()
    strategy_sequences: dict[uuid.UUID, list[str]] = {}
    for dialogue_key, strategy_value in strategy_rows:
        strategy_sequences.setdefault(dialogue_key, []).append(
            strategy_value.value if hasattr(strategy_value, "value") else str(strategy_value)
        )
    flat_strategies = [value for seq in strategy_sequences.values() for value in seq]
    strategy_diversity = _strategy_diversity_from_values(flat_strategies)
    strategy_repeat_rate = _strategy_repeat_from_sequences(list(strategy_sequences.values()))

    # ── ② 진단-실제 오개념 일치율 (오프라인 진단정확도·substring recall) ──
    # 시스템 지표라 DB·user/기간과 무관(라벨 프로브에 substring 매처 recall) — 전 user 동일값.
    diagnostic_hits, diagnostic_total = compute_diagnostic_recall()

    return SurrogateMetrics(
        verify_pass_rate=verify_metric,
        diagnosis_agreement_rate=_diagnosis_agreement_offline(diagnostic_hits, diagnostic_total),
        session_completion_rate=session_completion,
        tokens_per_turn=tokens_metric,
        help_reduction_slope=help_reduction,
        help_demand_supply_ratio=help_demand_supply,
        calibration_brier=calibration_brier,
        transfer_score=transfer_score,
        help_reduction_validated=help_reduction_validated,
        hint_depth_reached=hint_depth,
        mastery_gain_rate=mastery_gain_metric,
        gap_recovery_leadtime_days=gap_recovery_leadtime_metric,
        misconception_resolution_rate=misconception_resolution,
        self_solve_rate=self_solve,
        strategy_diversity=strategy_diversity,
        strategy_repeat_rate=strategy_repeat_rate,
        client_state_mismatch_rate=state_mismatch_metric,
        sample_sessions=int(total_sessions),
        sample_dialogues=sample_dialogues,
        sample_verify_events=verify_total,
        sample_hint_events=len(hint_levels),
        sample_strategy_turns=len(flat_strategies),
        sample_demand_events=demand_total,
        sample_accuracy_attempts=len(accuracy_series),
        sample_difficulty_attempts=len(difficulty_series),
        sample_calibration_pairs=len(calibration_pairs),
        sample_transfer_probes=len(transfer_outcomes),
        sample_diagnostic_probes=diagnostic_total,
        sample_mastery_groups=len(mastery_gains),
        sample_gap_recovery_groups=len(leadtime_days),
        sample_misconception_hypotheses=misconception_total,
        sample_resolved_dialogues=resolved_total,
        window_start=since,
        window_end=until,
        user_scoped=user_id is not None,
        mode_filter=mode,
    )


# ── S4-19 — 3상태 단계 검증 회계(지표 ① binary와 이중 회계·내부 전용) ─────────────────
@dataclass(frozen=True)
class StepVerificationAccounting:
    """검산결과 이벤트에 병기 적재된 verify_solution 3상태 카운트의 파생 회계(S4-19).

    **노출 집행(2026-08-04 헌법 별항)**: `SurrogateMetrics` 필드가 *아니다* — `GET /v1/me/
    harness-metrics`가 response_model=SurrogateMetrics로 전 필드를 학생 토큰에 자동 서빙하므로
    (2026-08-10 실측), 파생 지표를 거기 넣으면 '학생 대면 표면 0'과 양립 불가다. 이 dataclass는
    `surrogate_baseline_report` 내부 섹션(ops CLI)으로만 렌더된다 — 학생 라우트 무변경.

    **정직 회계(S3-07·`wh1_shadow_harvest.summarize` 동형)**: 3카운트 전부 non-NULL인 이벤트만
    분모(`counted_events`)로 세고, 카운트 비보유는 `uncounted_events`로 분리 계상한다 —
    **"카운트 비보유 = 구판 이벤트 *또는* 검증 미실행 제출"은 저장 모양이 같아(둘 다 SQL NULL)
    구분 불가**이므로 하나의 정직한 버킷이다(둘을 구분한다고 주장하지 않는다).
    """

    counted_events: int
    """3카운트(n_correct·n_incorrect·n_unverifiable) 전부 보유한 검산결과 이벤트 수(신판 유검증)."""

    uncounted_events: int
    """카운트 비보유 이벤트 수 — 구판 *또는* 단계 미제출/검증 미실행 제출(구분 불가·한 버킷)."""

    n_correct_total: int
    """counted 이벤트의 correct 전이 합."""

    n_incorrect_total: int
    """counted 이벤트의 incorrect 전이 합."""

    n_unverifiable_total: int
    """counted 이벤트의 unverifiable 전이 합."""

    step_decision_rate: float | None
    """(n_correct+n_incorrect)/전체 전이 — 판정(비-unverifiable) 비율(D6 정의). 전이 0이면 None."""

    step_incorrect_rate: float | None
    """n_incorrect/전체 전이 — incorrect 전이 비율(D6 정의). 전이 0이면 None(가짜 0 금지)."""

    ocr_gated_events: int
    """ocr_gated=true 이벤트 수 — 저신뢰 OCR로 step-incorrect 코칭이 보류된 제출 건수."""


async def compute_step_verification_accounting(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    mode: str | None = None,
) -> StepVerificationAccounting:
    """검산결과 이벤트의 3상태 카운트를 집계 — 지표 ①(binary)의 S4-19 병기 파생(교체 아님).

    설계 정본: `docs/architecture/solution_module_gap_review.md` §5-3 D6. `verify_pass_rate`
    (binary·값·계산식 불변)와 *같은 조건*(event_type=검산결과·user/시간창/mode 스코프)으로
    필터하되, 파생 비율의 분모는 **3카운트 전부 non-NULL인 이벤트의 전이 합만** 쓴다(S3-07
    정직 회계 — 구판/무검증 이벤트를 '전이 0'으로 위장하지 않는다). 전이 합 0이면 비율 None
    (NO_DATA — 가짜 0 금지). JSONB 접근은 쿼리빌더(`as_integer`/`as_boolean`)만 — 저장된
    구판 이벤트(키 부재)와 신판 무검증(명시 null)은 SQL에서 똑같이 NULL로 읽힌다.

    shadow 원장(`wh1_shadow_harvest.summarize`의 transition_counts)과 같은 3상태 분포를 내는
    **결정론 라이브 미러**다 — 두 회계가 서로를 검증한다(D6 취지).
    """
    conds = [AttemptEvent.event_type == EventType.검산결과]
    if user_id is not None:
        conds.append(AttemptEvent.user_id == user_id)
    if since is not None:
        conds.append(AttemptEvent.event_at >= since)
    if until is not None:
        conds.append(AttemptEvent.event_at <= until)
    # S3-03 mode 스코프 — 지표 ①과 동형(태그 없는 구판·mode=null은 as_string() NULL이라 제외).
    if mode is not None:
        conds.append(AttemptEvent.event_data["mode"].as_string() == mode)

    n_correct_col = AttemptEvent.event_data["n_correct"].as_integer()
    n_incorrect_col = AttemptEvent.event_data["n_incorrect"].as_integer()
    n_unverifiable_col = AttemptEvent.event_data["n_unverifiable"].as_integer()
    # 신판 유검증 판정 — 3카운트 *전부* non-NULL(S3-07 `summarize` 동형·하나라도 NULL이면 비보유).
    counted = and_(
        n_correct_col.is_not(None),
        n_incorrect_col.is_not(None),
        n_unverifiable_col.is_not(None),
    )
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(counted),
                func.sum(n_correct_col).filter(counted),
                func.sum(n_incorrect_col).filter(counted),
                func.sum(n_unverifiable_col).filter(counted),
                func.count().filter(AttemptEvent.event_data["ocr_gated"].as_boolean().is_(True)),
            )
            .select_from(AttemptEvent)
            .where(*conds)
        )
    ).one()
    total_raw, counted_raw, correct_raw, incorrect_raw, unverifiable_raw, ocr_gated_raw = row
    total = int(total_raw or 0)
    counted_events = int(counted_raw or 0)
    n_correct_total = int(correct_raw or 0)
    n_incorrect_total = int(incorrect_raw or 0)
    n_unverifiable_total = int(unverifiable_raw or 0)

    # 파생 비율(D6) — 분모는 counted 이벤트의 전체 전이 합. 0이면 None(표본 0을 0%로 위장 금지).
    transitions_total = n_correct_total + n_incorrect_total + n_unverifiable_total
    if transitions_total > 0:
        step_decision_rate: float | None = (n_correct_total + n_incorrect_total) / transitions_total
        step_incorrect_rate: float | None = n_incorrect_total / transitions_total
    else:
        step_decision_rate = None
        step_incorrect_rate = None

    return StepVerificationAccounting(
        counted_events=counted_events,
        uncounted_events=total - counted_events,
        n_correct_total=n_correct_total,
        n_incorrect_total=n_incorrect_total,
        n_unverifiable_total=n_unverifiable_total,
        step_decision_rate=step_decision_rate,
        step_incorrect_rate=step_incorrect_rate,
        ocr_gated_events=int(ocr_gated_raw or 0),
    )
