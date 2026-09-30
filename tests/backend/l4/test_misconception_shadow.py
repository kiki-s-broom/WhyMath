"""L4 오개념 judge would-be shadow 단위테스트 — G1(비노출·비차단·never-break·프라이버시).

`observe_misconception_judge_shadow`를 `asyncio.run`으로 *직접* 호출하고 `FakeJudge`(judge.py)로
verdict를 제어해, would_remove/keep 분류·verdict 카운트·레코드 JSON을 라이브 모델 없이 검증한다
(`test_step_shadow.py`의 record_logger 필터 + `model_validate_json` 패턴 답습).

핵심 단언:
- would_remove=NOT_EXPRESSES·would_keep=EXPRESSES+UNCERTAIN(verdict 카운트와 일치).
- **프라이버시**: FakeJudge reason="fake"여도 레코드에 `reason` 키 부재·학생 원문 0(미성년 PII).
- **never-break**: judge가 raise해도 `None` 반환(예외 전파 0).
- 빈 입력 short-circuit(judge 미호출).
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.judge import (
    FakeJudge,
    JudgeResult,
    JudgeVerdict,
)
from whymath_backend.l4.misconception.models import Misconception, MisconceptionMatch
from whymath_backend.l4.misconception.shadow import (
    MisconceptionJudgeShadowObservation,
    observe_misconception_judge_shadow,
    observe_misconception_shadow,
)

# 카탈로그 실 id(2종) — would_remove/keep 분류가 id를 정확히 싣는지 검증용.
_DOP = "distribution-over-power"
_DBZ = "division-by-zero"
# 학생 진술 원문 — 레코드에 *절대* 새지 않아야 함(프라이버시 단언 토큰).
_STUDENT = "내 풀이는 (a+b)² = a² + b²로 전개했어"


def _match(mid: str, *, confidence: float = 0.9) -> MisconceptionMatch:
    """카탈로그 id로 의미 매치 1건 구성(semantic_similarity 채움 — 의미 경로 모사)."""
    return MisconceptionMatch(
        misconception=CATALOG_BY_ID[mid],
        confidence=confidence,
        semantic_similarity=confidence,
    )


def _records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """judge shadow 구조화 record 로거 JSON 라인만(평문·다른 로거 노이즈 배제)."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "whymath.l4.misconception.judge_shadow.record"
    ]


# ──────────────────────────────────────────────────────────────────────────
# ① verdict별 would_remove/keep 분류 + 카운트
# ──────────────────────────────────────────────────────────────────────────
class TestVerdictClassification:
    def test_not_expresses_goes_to_would_remove(self, caplog: pytest.LogCaptureFixture) -> None:
        # _DOP=아니오(제거)·_DBZ=예(유지) → would_remove=[_DOP]·would_keep=[_DBZ].
        judge = FakeJudge({_DOP: JudgeVerdict.NOT_EXPRESSES, _DBZ: JudgeVerdict.EXPRESSES})
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            result = asyncio.run(
                observe_misconception_judge_shadow(
                    [_match(_DOP), _match(_DBZ)], _STUDENT, judge=judge
                )
            )
        assert result is None  # 비노출 — 호출자가 신호 받을 변수 없음
        records = _records(caplog)
        assert len(records) == 1
        obs = MisconceptionJudgeShadowObservation.model_validate_json(records[0])
        assert obs.would_remove_ids == [_DOP]  # 아니오 → 제거 대상
        assert obs.would_keep_ids == [_DBZ]  # 예 → 유지
        assert obs.semantic_candidate_ids == [_DOP, _DBZ]  # 입력 순서 보존
        assert obs.verdict_not_expresses == 1
        assert obs.verdict_expresses == 1
        assert obs.verdict_uncertain == 0
        assert obs.candidate_count == 2

    def test_uncertain_counts_as_keep(self, caplog: pytest.LogCaptureFixture) -> None:
        # 불확실(보수 폴백)도 would_keep — recall 보존. default=UNCERTAIN로 둘 다 유지.
        judge = FakeJudge(default=JudgeVerdict.UNCERTAIN)
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            asyncio.run(
                observe_misconception_judge_shadow(
                    [_match(_DOP), _match(_DBZ)], _STUDENT, judge=judge
                )
            )
        obs = MisconceptionJudgeShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.would_remove_ids == []  # 아니오 없음
        assert sorted(obs.would_keep_ids) == sorted([_DOP, _DBZ])  # 불확실=유지
        assert obs.verdict_uncertain == 2
        assert obs.verdict_not_expresses == 0
        assert obs.verdict_expresses == 0

    def test_feed_threshold_and_routing_recorded(self, caplog: pytest.LogCaptureFixture) -> None:
        # 운영점(feed_threshold)·judge 모델 라벨(judge_routing)이 레코드에 사후 해석용으로 실린다.
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            asyncio.run(
                observe_misconception_judge_shadow(
                    [_match(_DOP)],
                    _STUDENT,
                    judge=FakeJudge(default=JudgeVerdict.EXPRESSES),
                    feed_threshold=0.40,
                    judge_routing="general_mid",
                )
            )
        obs = MisconceptionJudgeShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.feed_threshold == 0.40
        assert obs.judge_routing == "general_mid"


# ──────────────────────────────────────────────────────────────────────────
# ② 프라이버시 — reason/학생 원문 미저장(미성년 PII 구조적 차단)
# ──────────────────────────────────────────────────────────────────────────
class TestPrivacyNoReasonNoStudentText:
    def test_record_omits_reason_key(self, caplog: pytest.LogCaptureFixture) -> None:
        # FakeJudge는 reason="fake"를 내지만(judge.py) 레코드 모델엔 reason 필드가 없고
        # extra="forbid"라 *구조적으로* 차단된다 — JSON에 reason 키 부재.
        judge = FakeJudge({_DOP: JudgeVerdict.NOT_EXPRESSES})
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            asyncio.run(observe_misconception_judge_shadow([_match(_DOP)], _STUDENT, judge=judge))
        raw = _records(caplog)[0]
        parsed = json.loads(raw)
        assert "reason" not in parsed  # judge reason 미저장(학생 진술 인용 가능=PII)
        assert "raw" not in parsed
        assert "fake" not in raw  # FakeJudge reason 문자열도 레코드에 0

    def test_record_omits_student_statement(self, caplog: pytest.LogCaptureFixture) -> None:
        # 학생 진술 원문은 레코드에 *어디에도* 없다(id·카운트만·step_shadow 규약 계승).
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            asyncio.run(
                observe_misconception_judge_shadow(
                    [_match(_DOP)],
                    _STUDENT,
                    judge=FakeJudge(default=JudgeVerdict.EXPRESSES),
                )
            )
        raw = _records(caplog)[0]
        assert "(a+b)" not in raw  # 학생 풀이 원문 미포함
        assert "전개했어" not in raw

    def test_model_forbids_extra_fields(self) -> None:
        # extra="forbid" — reason 같은 PII 필드를 *주입조차* 못 한다(구조적 차단 회귀 가드).
        with pytest.raises(Exception):  # noqa: B017,PT011 — pydantic ValidationError
            MisconceptionJudgeShadowObservation(
                semantic_candidate_ids=[],
                would_remove_ids=[],
                would_keep_ids=[],
                verdict_expresses=0,
                verdict_not_expresses=0,
                verdict_uncertain=0,
                candidate_count=0,
                reason="이런 필드는 금지",  # type: ignore[call-arg]
            )


# ──────────────────────────────────────────────────────────────────────────
# ③ never-break — judge가 raise해도 None 반환(예외 전파 0)
# ──────────────────────────────────────────────────────────────────────────
class _BoomJudge:
    """judge가 항상 raise — observe의 try/except가 본류를 안 깨는지(never-break) 검증용.

    `JudgeProtocol`은 never-break를 *구현*(LLMJudge)이 보장하지만, observe는 그 위에 직렬화·
    로깅 실패까지 감싸는 추가 방어선이 있다 — judge가 *프로토콜을 어기고* raise해도 삼킨다.
    """

    async def judge(self, student_statement: str, misconception: Misconception) -> JudgeResult:
        raise RuntimeError("judge 강제 실패(never-break 테스트)")


class TestNeverBreak:
    def test_judge_raises_returns_none_no_propagation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # judge가 raise → observe는 조용히 None 반환(예외가 fire-and-forget task를 안 깸).
        with caplog.at_level(logging.INFO):
            result = asyncio.run(
                observe_misconception_judge_shadow([_match(_DOP)], _STUDENT, judge=_BoomJudge())
            )
        assert result is None  # 예외 전파 0(never-break)
        assert _records(caplog) == []  # 실패라 레코드도 안 남음(부분 기록 0)
        # 침묵 실패 금지(CLAUDE.md) — 타입명은 남기고 예외 메시지·트레이스백은 남기지 않는다
        # (예외 메시지는 학생 발화·답안을 담을 수 있다 — 미성년자 PII).
        warnings = [
            r
            for r in caplog.records
            if r.name == "whymath.l4.misconception.shadow" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "RuntimeError" in warnings[0].getMessage()
        assert "judge 강제 실패" not in warnings[0].getMessage()
        assert warnings[0].exc_info is None


class TestObserveMisconceptionShadowNeverBreak:
    """`observe_misconception_shadow`(substring↔semantic shadow)의 never-break + 타입명 로그."""

    class _BadMatch:
        """`misconception` 속성이 없는 가짜 match — try 내부에서 AttributeError를 유발."""

    def test_bad_match_swallowed_and_logs_exception_type(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="whymath.l4.misconception.shadow"):
            result = observe_misconception_shadow([self._BadMatch()], [])  # type: ignore[list-item]
        assert result is None  # 예외 전파 0(never-break·비노출 불변)
        warnings = [
            r
            for r in caplog.records
            if r.name == "whymath.l4.misconception.shadow" and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "AttributeError" in warnings[0].getMessage()  # 타입명 포함(무타입 경고 금지)
        assert warnings[0].exc_info is None  # 트레이스백 미첨부(PII 우회 유출 차단)


# ──────────────────────────────────────────────────────────────────────────
# ④ 빈 입력 short-circuit — judge 미호출
# ──────────────────────────────────────────────────────────────────────────
class _SpyJudge:
    """호출 횟수를 세는 judge — 빈 입력 시 0이어야(short-circuit·효율)."""

    def __init__(self) -> None:
        self.calls = 0

    async def judge(self, student_statement: str, misconception: Misconception) -> JudgeResult:
        self.calls += 1
        return JudgeResult(verdict=JudgeVerdict.UNCERTAIN)


class TestEmptyInputShortCircuit:
    def test_empty_candidates_skips_judge(self, caplog: pytest.LogCaptureFixture) -> None:
        spy = _SpyJudge()
        with caplog.at_level(logging.INFO, logger="whymath.l4.misconception.judge_shadow.record"):
            result = asyncio.run(observe_misconception_judge_shadow([], _STUDENT, judge=spy))
        assert result is None
        assert spy.calls == 0  # 후보 0 → judge 미호출(short-circuit)
        assert _records(caplog) == []  # 레코드도 0
