"""WH-1 primary 금지모드 가드 seam 단위테스트 — PED-23 회수(원 PED-07 런타임 배선·04g §9).

`run_wh1_primary_turn`에 교수법 팩을 주입하고 `_FakeProvider`(스크립트 JSON)로 위반/무위반 발화를
제어해, 가드의 fail-closed 폴백·reason_code 로그·플래그 OFF 비트동일·팩 부재 통과를 실 네트워크
0으로 검증한다(`test_wh1_primary.py`·`test_wh1_prose.py` seam 관례 답습). 팩은 실 코퍼스
YAML(`get_pack`·hermetic)을 쓴다 — 개념형 팩이 WORKED_EXAMPLE_FIRST를 금지하는 실제 데이터 경로.

핵심 봉인:
  - **플래그 OFF(기본) 비트동일** — 위반 발화도 가드 미실행으로 그대로 서빙(기존 동작 무변경).
  - **ON + 위반 → 폴백** — 위반 발화는 학생에게 나가지 않고 소크라테스 재질문(결정론 템플릿·
    `EXAMPLE_QUESTION` 기존 자산)으로 대체, reason_code(위반 모드 토큰)가 WARNING 로그에 남는다.
  - **발화 원문 비유출** — 가드 로그에 위반 발화 원문이 실리지 않는다(프라이버시·톤필터 관례).
  - **팩 부재(None) → 통과** — 팩 없으면 forbidden_modes도 없음(조용한 통과·로그 0).
  - **가드 예외 → skip + 예외 타입명 로그** — 침묵 실패 금지(CLAUDE.md)·서빙은 계속.
  - **관측 연속** — 폴백 턴에도 관측 레코드(primary=True)는 그대로 emit(원장 연속).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator, Sequence

import pytest

from whymath_backend.config import get_settings
from whymath_backend.harness import wh1_primary
from whymath_backend.harness.wh1_primary import run_wh1_primary_turn
from whymath_backend.harness.wh1_shadow import Wh1HarnessShadowObservation
from whymath_backend.l3.models import GenerationResult, RoutingDecision
from whymath_backend.l4.pedagogy.pack_registry import get_pack, reset_pack_cache
from whymath_backend.l4.socratic.categories import EXAMPLE_QUESTION, SocraticCategory
from whymath_backend.schema.enums import KnowledgeType
from whymath_backend.schema.pedagogy_pack import PedagogyPack

_RECORD_LOGGER = "whymath.harness.wh1_shadow.record"
_PRIMARY_LOGGER = "whymath.harness.wh1_primary"

# 위반 발화 — 정의 단정 + 유도 신호 0(WORKED_EXAMPLE_FIRST 양성)·톤필터 6패턴 미포함(치환 0이라
# OFF 케이스의 "그대로 서빙" 단언이 바이트 정확해진다).
_VIOLATING = "이 개념의 정의는 주변보다 큰 값이라는 것이다. 그대로 외우면 된다."
# 무위반 발화 — 정의어가 있어도 명백히 유도(오검출 방어 축·fidelity eval clean 은행 미러).
_CLEAN = "이걸 뭐라고 정의하면 좋을까? 네 생각을 말해 줄래?"
# 폴백 정본 — 소크라테스 명료화 재질문(기존 자산).
_FALLBACK = EXAMPLE_QUESTION[SocraticCategory.CLARIFICATION]


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Iterator[None]:
    """각 테스트 후 설정 캐시 원복 — env 토글이 다른 테스트로 새지 않게(assembler 테스트 관례)."""
    yield
    get_settings.cache_clear()


def _guard_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """금지모드 가드 플래그 ON — env 킬스위치 관례 + settings 캐시 무효화."""
    monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "true")
    get_settings.cache_clear()


def _concept_pack() -> PedagogyPack:
    """실 코퍼스 개념형 팩(WORKED_EXAMPLE_FIRST 금지) — hermetic YAML 로드."""
    reset_pack_cache()
    pack = get_pack(KnowledgeType.CONCEPT.value)
    assert pack is not None, "개념형 팩이 코퍼스에 없다 — 전제 붕괴"
    assert "WORKED_EXAMPLE_FIRST" in pack.forbidden_modes
    return pack


class _FakeProvider:
    """스크립트된 JSON만 돌려주는 L3 provider 대역 — 소진 시 end_turn(격려)로 종료."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
    ) -> GenerationResult:
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult('{"kind": "end_turn", "action_type": "격려"}')


def _provider_for(utterance: str) -> _FakeProvider:
    """명시 발화 1건을 end_turn으로 싣는 provider — 풀이 단계 없음(verdict None → 발화 존중)."""
    return _FakeProvider(
        ['{"kind": "end_turn", "action_type": "질문", "utterance": "' + utterance + '"}']
    )


def _run(*, pack: PedagogyPack | None, provider: _FakeProvider) -> str | None:
    return asyncio.run(
        run_wh1_primary_turn(
            student_solution="학생 개인 풀이 ZZPIIZZ",
            solution_steps=[],
            active_hypotheses=[],
            provider=provider,
            timeout_seconds=5.0,
            dialogue_id="d-guard",
            turn_index=1,
            problem_id="p-guard",
            pack=pack,
        )
    )


def _records(caplog: pytest.LogCaptureFixture) -> list[Wh1HarnessShadowObservation]:
    return [
        Wh1HarnessShadowObservation.model_validate_json(r.getMessage())
        for r in caplog.records
        if r.name == _RECORD_LOGGER
    ]


def _guard_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records if r.name == _PRIMARY_LOGGER and "mode_guard" in r.getMessage()
    ]


# ──────────────────────────────────────────────────────────────────────────
# ① 플래그 OFF(기본) — 가드 미실행·기존 동작 비트동일
# ──────────────────────────────────────────────────────────────────────────
class TestFlagOffDefault:
    def test_default_is_off(self) -> None:
        """플래그 기본값 False(옵트인·킬스위치) — GA flip은 측정+사인오프 후 별도 커밋.

        env 오염과 무관한 *선언 기본값*을 정본으로 읽는다(test_slo_contract 관례).
        """
        from whymath_backend.config import Settings

        assert Settings.model_fields["mode_guard_runtime_enabled"].default is False

    def test_violating_utterance_served_unchanged_and_no_guard_log(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OFF — 위반 발화도 가드를 안 타고 그대로 서빙(기존 경로 무변경 동결)."""
        # 명시 OFF(외부 env 오염 방지 — assembler 테스트 _disable_flag 관례).
        monkeypatch.setenv("WHYMATH_MODE_GUARD_RUNTIME_ENABLED", "false")
        get_settings.cache_clear()
        pack = _concept_pack()
        with caplog.at_level(logging.DEBUG, logger=_PRIMARY_LOGGER):
            served = _run(pack=pack, provider=_provider_for(_VIOLATING))
        assert served == _VIOLATING  # 톤필터 치환 0 발화라 바이트 동일 — 가드 미개입 증명.
        assert _guard_logs(caplog) == []  # 가드 로그 0 — 블록 자체 미실행.


# ──────────────────────────────────────────────────────────────────────────
# ② 플래그 ON + 위반 — fail-closed 폴백 + reason_code 로그 + 원문 비유출
# ──────────────────────────────────────────────────────────────────────────
class TestFlagOnViolation:
    def test_falls_back_to_socratic_requestion_with_reason_code(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ON + 위반 → 위반 발화 미서빙·소크라테스 재질문 대체·reason_code WARNING."""
        _guard_on(monkeypatch)
        pack = _concept_pack()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            with caplog.at_level(logging.WARNING, logger=_PRIMARY_LOGGER):
                served = _run(pack=pack, provider=_provider_for(_VIOLATING))
        # fail-closed: 위반 발화는 학생에게 나가지 않는다 — 결정론 재질문(기존 자산)으로 대체.
        assert served == _FALLBACK
        assert served != _VIOLATING
        # reason_code(위반 모드 토큰)가 구조화 WARNING으로 남는다 — 조용한 폴백 금지.
        guard_logs = _guard_logs(caplog)
        assert len(guard_logs) == 1
        message = guard_logs[0].getMessage()
        assert "WORKED_EXAMPLE_FIRST" in message
        assert "폴백" in message
        # 프라이버시: 위반 발화 원문은 로그 어디에도 싣지 않는다(톤필터 로그 관례 동형).
        assert all(_VIOLATING not in r.getMessage() for r in caplog.records)

    def test_observation_record_still_emitted_on_fallback(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """폴백 턴에도 관측 레코드(primary=True)는 그대로 emit — 원장 연속(S1-11 방침 ⑤)."""
        _guard_on(monkeypatch)
        pack = _concept_pack()
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            served = _run(pack=pack, provider=_provider_for(_VIOLATING))
        assert served == _FALLBACK
        records = _records(caplog)
        assert len(records) == 1
        assert records[0].primary is True
        # 폴백 재질문은 톤필터 무치환(안전 자산) — 톤 회계 오염 0.
        assert records[0].tone_rewritten is False
        assert records[0].tone_violations == 0


# ──────────────────────────────────────────────────────────────────────────
# ③ 플래그 ON + 팩 부재/무위반 — 조용한 통과(원본 그대로)
# ──────────────────────────────────────────────────────────────────────────
class TestFlagOnPassThrough:
    def test_pack_none_serves_utterance_without_guard_log(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ON + 팩 None → 가드 조용히 통과(팩 없으면 forbidden_modes도 없음·로그 0)."""
        _guard_on(monkeypatch)
        with caplog.at_level(logging.DEBUG, logger=_PRIMARY_LOGGER):
            served = _run(pack=None, provider=_provider_for(_VIOLATING))
        assert served == _VIOLATING
        assert _guard_logs(caplog) == []

    def test_clean_utterance_served_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ON + 무위반(유도 발화) → 원본 그대로 서빙(과차단 0 — 유도가 살아 있으면 통과)."""
        _guard_on(monkeypatch)
        pack = _concept_pack()
        served = _run(pack=pack, provider=_provider_for(_CLEAN))
        assert served == _CLEAN

    def test_deferred_only_pack_is_not_ruled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ON + 절차형 팩(deferred 모드만 금지) → 규칙 판정 없음·원본 서빙(정직한 공백 유지)."""
        _guard_on(monkeypatch)
        reset_pack_cache()
        procedure = get_pack(KnowledgeType.PROCEDURE.value)
        assert procedure is not None
        # 절차형엔 WORKED_EXAMPLE_FIRST 금지가 없다 — 정의 단정 발화도 교차 오검출하지 않는다.
        served = _run(pack=procedure, provider=_provider_for(_VIOLATING))
        assert served == _VIOLATING


# ──────────────────────────────────────────────────────────────────────────
# ④ 가드 자체 예외 — skip하되 예외 타입명 로그(침묵 실패 금지)
# ──────────────────────────────────────────────────────────────────────────
class TestGuardException:
    def test_guard_crash_logs_type_name_and_serves(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """가드 장애 → 판정 유보·발화는 기존 게이트로만 서빙 + 예외 *타입명* WARNING."""
        _guard_on(monkeypatch)
        pack = _concept_pack()

        def _boom(*args: object, **kwargs: object) -> str | None:
            raise RuntimeError("가드 폭발(테스트)")

        monkeypatch.setattr(wh1_primary, "check_forbidden_modes", _boom)
        with caplog.at_level(logging.WARNING, logger=_PRIMARY_LOGGER):
            served = _run(pack=pack, provider=_provider_for(_VIOLATING))
        assert served == _VIOLATING  # 가드 판정 유보 — 서빙은 계속(가용성).
        failure_logs = [r for r in _guard_logs(caplog) if "실행 실패" in r.getMessage()]
        assert len(failure_logs) == 1
        assert "RuntimeError" in failure_logs[0].getMessage()  # 무타입 침묵 경고 금지 동결.
