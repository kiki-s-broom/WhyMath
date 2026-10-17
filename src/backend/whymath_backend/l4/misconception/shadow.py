"""오개념 의미 매칭 *shadow 관측* — 노출 없이 substring↔semantic 불일치만 로깅 (slice 111).

`l4/step_shadow.py`(단계-비보존 shadow)의 정본 패턴을 미러한다. coach가 `misconception_semantic_
mode == "shadow"`일 때, 의미 매처를 *라이브로 돌리되* 노출은 substring 그대로 두고(off와 동일),
substring이 안 잡은 semantic-only 후보(불일치)를 **로그로만** 남긴다 — 슬107 측정 하니스는 *합성
프로브*에서 방향맹 FP를 쟀는데, shadow는 *실 학생 트래픽 분포*에서 의미 매처가 무엇을 더하는지를
무노출로 수집해 게이트 플립(`off`→`on`) 근거를 보강한다.

비노출·비차단 불변(step_shadow 계승):
- **비노출**: 반환 `None`. 호출자(coach)가 신호를 받을 변수가 없어 student-facing 누출이 구조적으로
  차단된다. 노출 응답은 `off`와 비트동일(substring)이고, shadow 로그는 *서버 로그 sink에만* 흐른다.
- **비차단**: 검출·직렬화·로깅을 한 `try`로 감싸 어떤 예외도 본류(코칭 결정·반환)를 안 깬다
  (우선순위: 학생 경험 > 진단 관측).
- **프라이버시**: 학생 풀이 원문을 레코드에 *담지 않는다*(step_shadow 규약·미성년자). 담는 건
  추상화된 오개념 id·코사인 유사도·개수(비식별).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from whymath_backend.l4.misconception.judge import JudgeProtocol, JudgeVerdict, judge_verdicts
from whymath_backend.l4.misconception.models import MisconceptionMatch

logger = logging.getLogger("whymath.l4.misconception.shadow")  # step_shadow 네이밍 동형
# 구조화 레코드 JSON 한 줄(harvest 입력) — 평문 로그와 분리된 자식 로거(step_shadow.record 미러).
record_logger = logging.getLogger("whymath.l4.misconception.shadow.record")

# G1: judge would-be shadow 전용 자식 로거(`shadow.record`와 동형으로 한 단계 더 분리) —
# judge shadow 레코드만 따로 harvest/필터할 수 있게 한다.
judge_record_logger = logging.getLogger("whymath.l4.misconception.judge_shadow.record")


class MisconceptionShadowObservation(BaseModel):
    """의미 매칭 shadow 관측 1건의 *구조화 레코드* — record_logger JSON emit (harvest).

    노출되는 substring 후보(`substr_ids`)와 의미 매처가 *추가할* semantic-only 후보
    (`semantic_only_ids`·substring 미포착)를 담아, 실 분포에서 의미 매칭이 무엇을 더하는지(불일치)를
    수집한다. **학생 풀이 원문을 담지 않는다**(step_shadow 규약·프라이버시) — 담는 건 오개념 id·
    코사인 유사도·개수(비식별·로그 sink 한정·비노출 불변).
    """

    model_config = ConfigDict(extra="forbid")

    substr_ids: list[str]
    """노출되는(off와 동일) substring 진단 후보 id — confidence 내림차순."""

    semantic_only_ids: list[str]
    """의미 매처가 *추가할* 후보 id(substring 미포착) = 불일치. on이면 노출될 semantic-only."""

    semantic_only_similarities: list[float]
    """`semantic_only_ids` 각각의 코사인 유사도(같은 순서·None은 -1.0으로 표기)."""

    substr_count: int
    semantic_count: int
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def observe_misconception_shadow(
    substr_matches: list[MisconceptionMatch],
    semantic_matches: list[MisconceptionMatch],
) -> None:
    """substring↔semantic 불일치를 *로그로만* 관측(shadow·비차단·비노출). 반환 `None`.

    반환이 `None`이라 호출자(coach)가 신호를 받을 변수가 없다 — student-facing 누출 구조적 차단.
    coach는 `mode == "shadow"`에서만 호출하므로 이 함수는 게이트를 재검사하지 않는다(호출 시점이
    곧 shadow). 노출(반환 matches)은 coach가 substring 그대로 둔다(off 비트동일) — 본 함수는
    *부수효과(로그)만* 낸다. 어떤 예외도 본류를 깨지 않게 `try`로 감싼다(비차단).

    `semantic_only` = 의미 매처 결과 중 substring이 *안 잡은* id(`combine_diagnoses`가 `on`에서
    substring 아래에 붙일 후보). 이게 실 분포에서 의미 매처의 *순기여*(+recall)와 *방향맹 FP*가
    뒤섞인 신호다 — 사람이 로그를 보고(또는 harvest) 플립 근거를 모은다.
    """
    try:
        substr_ids = [m.misconception.id for m in substr_matches]
        substr_set = set(substr_ids)
        semantic_only = [m for m in semantic_matches if m.misconception.id not in substr_set]
        semantic_only_ids = [m.misconception.id for m in semantic_only]
        # semantic_similarity None(이론상 의미 경로에선 항상 설정)은 -1.0로 표기(레코드 타입 고정).
        sims = [
            m.semantic_similarity if m.semantic_similarity is not None else -1.0
            for m in semantic_only
        ]
        logger.info(
            "의미 매칭 shadow(비노출) — substr=%s semantic_only=%s sims=%s "
            "(substr_count=%d semantic_count=%d)",
            substr_ids,
            semantic_only_ids,
            [round(s, 3) for s in sims],
            len(substr_matches),
            len(semantic_matches),
        )
        record_logger.info(
            MisconceptionShadowObservation(
                substr_ids=substr_ids,
                semantic_only_ids=semantic_only_ids,
                semantic_only_similarities=sims,
                substr_count=len(substr_matches),
                semantic_count=len(semantic_matches),
            ).model_dump_json()
        )
    except Exception as exc:  # noqa: BLE001 — 관측은 본류를 안 깬다(비차단 방어선·테스트 커버)
        # 침묵 실패 금지 — 타입명만 남긴다(메시지는 학생 답안을 담을 수 있어 제외).
        logger.warning("오개념 semantic shadow 관측 실패: %s", type(exc).__name__)
        return


# ──────────────────────────────────────────────────────────────────────────
# G1: judge would-be shadow — 의미 후보에 judge를 *비차단*으로 돌려 *걸러질 결과*만 로깅
# ──────────────────────────────────────────────────────────────────────────


class MisconceptionJudgeShadowObservation(BaseModel):
    """judge would-be shadow 관측 1건의 *구조화 레코드* — judge_record_logger JSON emit (harvest).

    `misconception_semantic_mode=="shadow"`에서 도는 *의미 후보*에 judge를 돌려, judge가 **제거할**
    후보(`would_remove_ids`·NOT_EXPRESSES)와 **유지할** 후보(`would_keep_ids`·EXPRESSES+UNCERTAIN)를
    무노출로 수집한다 → 노출 전 실데이터로 judge 효과(합성↔실 갭)를 검증한다(04b Phase 1).

    **프라이버시(미성년 PII)**: 학생 진술 원문도, judge의 `근거`(reason·학생 진술 인용 가능)도
    *담지 않는다*. `reason` 필드 자체가 없고 `extra="forbid"`라 구조적으로 차단된다(`shadow.py`
    `MisconceptionShadowObservation` 규약 계승). 담는 건 추상화된 오개념 id·verdict 카운트·임계
    (비식별·로그 sink 한정·비노출 불변).
    """

    model_config = ConfigDict(extra="forbid")

    semantic_candidate_ids: list[str]
    """judge에 *투입한* 의미 후보 id(입력 순서·matcher가 이미 threshold로 필터한 셋)."""

    would_remove_ids: list[str]
    """judge가 `아니오`(NOT_EXPRESSES)로 판정해 *제거할* 후보 id — on이면 안 노출될 것."""

    would_keep_ids: list[str]
    """judge가 `예`/`불확실`(EXPRESSES+UNCERTAIN)로 판정해 *유지할* 후보 id(recall 보존·보수)."""

    verdict_expresses: int
    """`예`(EXPRESSES) 판정 수 — 진짜 오개념 표현으로 본 후보."""

    verdict_not_expresses: int
    """`아니오`(NOT_EXPRESSES) 판정 수 — 올바름/다른 말로 본 후보(would_remove와 1:1)."""

    verdict_uncertain: int
    """`불확실`(UNCERTAIN) 판정 수 — 모호 + 모든 폴백(형식 위반·seam 예외)의 귀착점."""

    candidate_count: int
    """투입 의미 후보 총수(=len(semantic_candidate_ids))."""

    feed_threshold: float | None = None
    """후보를 matcher가 거른 코사인 임계(judge-feed 운영점·사후 해석용·04b §4). None=미주입."""

    judge_routing: str | None = None
    """judge 라우팅 프로파일 라벨(fast_math/general_mid·judge 모델 식별·04b §2). None=미주입."""

    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# 비차단(fire-and-forget) task의 강참조 보관소 — `create_task`가 *유일하게* 들고 있는 참조가
# 약참조라 GC가 *실행 중* task를 수거해버리는 Python 경고(asyncio docs)를 방어한다. spawn 시
# add → 완료 시 add_done_callback(discard)로 자가 정리한다. `_misconception_state.py`의 모듈
# 전역 싱글톤 관용과 동형(코드베이스에 `create_task` 선례 0이라 가장 보수적 표준 패턴 채택).
_PENDING: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[object, object, None]) -> None:
    """코루틴을 *비차단*으로 띄우고 즉시 반환 — 응답 경로가 judge(수 초)를 await하지 않게 한다.

    `asyncio.create_task`로 백그라운드 실행하고, GC가 실행 중 task를 수거하지 못하게 `_PENDING`에
    강참조를 잡았다가 완료 콜백으로 푼다(3중 안전망 중 GC 방어선). 호출자(coach)는 이 함수가
    *즉시* 반환하므로 judge LLM 왕복을 기다리지 않는다(노출 무지연·G1 핵심 제약).
    """
    task: asyncio.Task[None] = asyncio.create_task(coro)
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def observe_misconception_judge_shadow(
    semantic_matches: list[MisconceptionMatch],
    student_statement: str,
    *,
    judge: JudgeProtocol,
    feed_threshold: float | None = None,
    judge_routing: str | None = None,
) -> None:
    """의미 후보에 judge를 돌려 *would-be removed/kept*를 로그로만 관측(shadow·비노출). 반환 `None`.

    `judge_verdicts`(*`judge_filter` 아님* — verdict 카운트가 필요)로 각 후보를 판정한 뒤
    `result.verdict`*만* 읽어 would_remove(NOT_EXPRESSES)/would_keep(EXPRESSES+UNCERTAIN)로 분류하고
    레코드를 emit한다. judge의 `reason`/`raw`는 *버린다*(학생 진술 인용 가능=미성년 PII·레코드
    모델에 필드 없음). 빈 입력은 short-circuit(judge 미호출).

    **never-break**(비차단 방어선·`observe_misconception_shadow`의 async 미러): judge 호출·직렬화·
    로깅을 한 `try`로 감싸 *어떤 예외도* 본류(여기선 fire-and-forget task)를 깨지 않는다 — judge
    코어(`judge_verdicts`)는 이미 seam 예외→UNCERTAIN으로 never-break지만(judge.py), 직렬화·로깅
    실패까지 포함해 방어한다(우선순위: 학생 경험 > 진단 관측·CLAUDE.md #1≫#6).
    """
    if not semantic_matches:
        return  # 의미 후보 0 → judge 미호출(short-circuit·효율).
    try:
        decided = await judge_verdicts(semantic_matches, student_statement, judge=judge)
        would_remove: list[str] = []
        would_keep: list[str] = []
        n_expresses = n_not_expresses = n_uncertain = 0
        for match, result in decided:
            mid = match.misconception.id
            # `result.verdict`만 읽는다 — reason/raw(PII 가능)는 절대 레코드에 안 담는다.
            if result.verdict is JudgeVerdict.NOT_EXPRESSES:
                would_remove.append(mid)
                n_not_expresses += 1
            else:
                would_keep.append(mid)  # 예·불확실 모두 유지(recall 보존·보수)
                if result.verdict is JudgeVerdict.EXPRESSES:
                    n_expresses += 1
                else:
                    n_uncertain += 1
        candidate_ids = [m.misconception.id for m in semantic_matches]
        logger.info(
            "judge shadow(비노출) — candidates=%s would_remove=%s would_keep=%s "
            "(예=%d 아니오=%d 불확실=%d routing=%s)",
            candidate_ids,
            would_remove,
            would_keep,
            n_expresses,
            n_not_expresses,
            n_uncertain,
            judge_routing,
        )
        judge_record_logger.info(
            MisconceptionJudgeShadowObservation(
                semantic_candidate_ids=candidate_ids,
                would_remove_ids=would_remove,
                would_keep_ids=would_keep,
                verdict_expresses=n_expresses,
                verdict_not_expresses=n_not_expresses,
                verdict_uncertain=n_uncertain,
                candidate_count=len(semantic_matches),
                feed_threshold=feed_threshold,
                judge_routing=judge_routing,
            ).model_dump_json()
        )
    # 관측 방어선 — 관측은 본류를 안 깬다(비차단 방어선·shadow.py:100 미러)
    except Exception as exc:  # noqa: BLE001
        logger.warning("judge would-be shadow 관측 실패: %s", type(exc).__name__)
        return
