"""L4 coach 라우터 단위테스트 — `POST /v1/coach`(hermetic).

엔드포인트 결선(200·통합 결정 직렬화·401·422·옵션 LTHC) 검증. 학생 발화·상태가 그대로
응답에 *에코되지 않음* 확인(에코는 표면화 위험 — coach.py docstring 경계 메모).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.api import coach
from whymath_backend.api._auth import get_consented_user
from whymath_backend.api._rate_limit import reset_store
from whymath_backend.api._subject_capability_state import STEP_CHAIN_VERIFIER_KEY
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.assessment import ConceptMasteryHistory
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l4.misconception import InterventionDecision, InterventionPattern
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.judge import FakeJudge, JudgeVerdict
from whymath_backend.l4.misconception.models import Misconception
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()


def _hyp(confidence: float, mid: str = "distribution-over-power") -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=mid, confidence=confidence, turns_since_evidence=0, evidence_count=1
    )


def _fallback_decision() -> InterventionDecision:
    return InterventionDecision(
        pattern=InterventionPattern.REVERSE_REASONING, prompt="FB", misconception_id="fb"
    )


class TestInterventionFromHypothesesWiring:
    """`_intervention_from_hypotheses_or` — 가설 세트가 결정을 내면 override, 못 내면 fallback."""

    def test_hypothesis_overrides_fallback(self) -> None:
        """누적 가설(0.9)이 raw 매치 기반 fallback을 대체한다(결선 핵심)."""
        out = coach._intervention_from_hypotheses_or([_hyp(0.9)], _fallback_decision())
        assert out is not None
        assert out.pattern is InterventionPattern.COUNTEREXAMPLE  # 0.9 > 0.8
        assert out.misconception_id == "distribution-over-power"

    def test_fallback_when_hypotheses_withhold(self) -> None:
        """가설 세트가 결정을 못 내면(빈 세트·focus<0.5 보류) fallback 유지(회귀 0)."""
        fb = _fallback_decision()
        assert coach._intervention_from_hypotheses_or([], fb) is fb
        assert coach._intervention_from_hypotheses_or([_hyp(0.3)], fb) is fb

    def test_fallback_none_stays_none(self) -> None:
        """가설도 보류·fallback도 None → None(개입 없음)."""
        assert coach._intervention_from_hypotheses_or([], None) is None


@pytest.fixture(autouse=True)
def _reset_rate_limit_store() -> None:
    """매 테스트 격리 — sliding window 카운트 리셋(다른 테스트로의 누수 차단).

    `reset_store()`는 async — 모듈 전역 `_BACKEND`(기본 InMemoryBackend)에 위임. 테스트
    별 새 이벤트 루프에서 호출되도록 `asyncio.run`으로 감싼다.
    """
    import asyncio

    asyncio.run(reset_store())


def _settings_override(
    limit: int = 0,
    write_limit: int | None = None,
    ip_limit: int = 0,
    ip_write_limit: int | None = None,
    device_limit: int = 0,
    device_write_limit: int | None = None,
    device_hmac_secret: str = "",
) -> Settings:
    """기본 모든 한도 0(비활성). `*_limit=None`이면 같은 read 인자와 동일.

    슬라이스 14/17/20/21 — 차등·방어 심층·3차원·디바이스 HMAC 서명. 모든 한도와 서명 검증
    secret을 기본 0/빈으로 두어 기존 테스트가 영향받지 않게 한다.
    """
    return Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
        coach_rate_limit_read_per_minute=limit,
        coach_rate_limit_write_per_minute=limit if write_limit is None else write_limit,
        coach_rate_limit_ip_read_per_minute=ip_limit,
        coach_rate_limit_ip_write_per_minute=(
            ip_limit if ip_write_limit is None else ip_write_limit
        ),
        coach_rate_limit_device_read_per_minute=device_limit,
        coach_rate_limit_device_write_per_minute=(
            device_limit if device_write_limit is None else device_write_limit
        ),
        coach_device_hmac_secret=SecretStr(device_hmac_secret),
    )


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _FakeSession:
    """`/v1/coach`(stateless)용 — DB 호출 시 AssertionError."""

    async def execute(self, stmt: Any) -> None:
        raise AssertionError("coach 라우터(stateless)는 DB 쿼리하지 않아야 한다.")


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        # slice 73: get_current_theta가 .scalars().first()로 최신 θ를 읽음 — 기본 빈 rows면
        # None(서버 θ 없음·비노출). θ를 검증하는 테스트는 _server_theta_for를 monkeypatch.
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one(self) -> Any:
        # WH-1 §8.4: curate_hypothesis가 net_support(순지지도) 집계를 scalar_one으로 읽는다.
        # 캡처 세션엔 증거 행이 없으니 0.0(반박 아님) — apply_matches와 결과 동치(하위호환).
        return 0.0

    def scalar_one_or_none(self) -> Any:
        # PED-04: `_prev_hint_level_for`(직전 힌트 적재)·`_session_recall_or_none`(직전 대화 id)와
        # S3-16: `_log_response_latency_event`(직전 학생 턴 spoken_at)가 단일 스칼라를 이 API로
        # 읽는다. 캡처 세션엔 이력이 없으니 None — "첫 결정·회상 없음·기준선 없음"과 같은 뜻이라
        # 기존 hermetic 기대(클라 제출 상태 그대로)와 정합.
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        # PED-04: `_turn_meta_rows`(턴 메타 컬럼 투영)가 Row 튜플을 이 API로 읽는다. 캡처
        # 세션은 execute_rows를 그대로 돌려주므로, 메타 이력이 필요한 테스트만 행을 주입한다.
        return list(self._rows)


class _CapturingSession:
    """`/v1/coach/sessions`용 — add/add_all/commit/refresh/get/execute 캡처.

    `_preload`로 `.get(Model, pk)`·`execute_rows`로 `.execute()` 결과를 미리 주입.
    """

    def __init__(
        self,
        preload: dict[Any, Any] | None = None,
        execute_rows: list[Any] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.flushes = 0
        self.refreshes = 0
        self._preload = preload or {}
        self._execute_rows = list(execute_rows or [])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        # WH-1 2단계 슬라이스 3 — apply_matches가 같은 트랜잭션 가시화로 flush(commit은 핸들러).
        # 캡처 세션은 no-op(영속 부재·added만 캡처).
        self.flushes += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshes += 1

    async def get(self, model: Any, pk: Any) -> Any | None:
        return self._preload.get((model, pk))

    async def execute(self, stmt: Any) -> _Result:
        return _Result(self._execute_rows)


def _client(rate_limit: int = 0) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = lambda: _settings_override(rate_limit)

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _session_client(
    preload: dict[Any, Any] | None = None,
    execute_rows: list[Any] | None = None,
    rate_limit: int = 0,
) -> tuple[TestClient, _CapturingSession]:
    """`/v1/coach/sessions` hermetic — capturing session으로 add/commit/execute 검증."""
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = lambda: _settings_override(rate_limit)
    captured = _CapturingSession(preload=preload, execute_rows=execute_rows)

    async def _sess() -> AsyncIterator[_CapturingSession]:
        yield captured

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), captured


def _no_auth_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _settings_override(0)

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


class TestBasicDecision:
    def test_minimal_request_returns_decision(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "decision" in body
        d = body["decision"]
        # 슬라이스 1-3 통합 — 모든 필드 채워짐
        assert d["polya_stage_to_advance"] in ("stay", "next", "previous")
        assert d["hint_level"] in (1, 2, 3, 4)
        assert d["socratic_category"] in (
            "clarification",
            "assumption",
            "evidence",
            "perspective",
            "implication",
            "meta",
        )
        assert d["prompt"]  # 비공
        assert d["system"]
        assert d["reveals"]  # hint_level에서 파생

    def test_default_state_is_understand_stay(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        body = resp.json()
        # 기본 PolyaState = UNDERSTAND + 짧은 입력 → stay·clarification
        assert body["decision"]["polya_stage_to_advance"] == "stay"
        assert body["decision"]["socratic_category"] == "clarification"

    def test_misconceptions_empty_for_neutral_input(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        body = resp.json()
        assert body["misconceptions"] == []
        assert body["intervention"] is None

    def test_lthc_none_without_mastery_level(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        assert resp.json()["lthc"] is None


class TestCoachingFocusSeed:
    """slice 23: coaching_focus → entry_socratic_category 시드(L2 진단→coach 결선)."""

    def test_none_focus_no_entry_category(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        assert resp.json()["entry_socratic_category"] is None

    def test_focus_seeds_entry_category(self) -> None:
        """consolidate → evidence(slice 22 매핑)."""
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "음", "coaching_focus": "consolidate"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["entry_socratic_category"] == "evidence"

    def test_all_focus_mappings(self) -> None:
        cases = {
            "consolidate": "evidence",
            "retrieval": "meta",
            "foundation": "clarification",
            "advance": "perspective",
            "diagnose": "clarification",
        }
        client = _client()
        for focus, expected in cases.items():
            resp = client.post("/v1/coach", json={"student_input": "음", "coaching_focus": focus})
            assert resp.json()["entry_socratic_category"] == expected, focus

    def test_invalid_focus_rejected_422(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음", "coaching_focus": "bogus"})
        assert resp.status_code == 422

    def test_session_create_includes_entry_category(self) -> None:
        """세션 생성 응답에도 진입 카테고리 시드 노출."""
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "coaching_focus": "advance"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["entry_socratic_category"] == "perspective"


class TestMisconceptionIntegration:
    def test_distribution_misconception_detected_with_intervention(self) -> None:
        # 슬라이스 4 카탈로그 — (a+b)² = a² + b² 신호로 풀 매칭(confidence 1.0)
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "내 풀이는 (a+b)² = a² + b² 이렇게 했어"},
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = [m["misconception"]["id"] for m in body["misconceptions"]]
        assert "distribution-over-power" in ids
        # confidence 1.0 → COUNTEREXAMPLE 패턴
        assert body["intervention"] is not None
        assert body["intervention"]["pattern"] == "counterexample"
        assert "a=1, b=1" in body["intervention"]["prompt"]

    def test_partial_match_gated_out(self) -> None:
        # WH-1 1단계 슬라이스 1 §3.3 품질 게이트: 부분 매칭(confidence 0.5)은 top-1 신뢰도
        # floor(0.65) 미만이라 *게이트에서 비워진다*(억지 매칭 금지). 이전엔 0.5가
        # reverse_reasoning 개입을 발화했으나, 게이트 도입으로 약한 매칭은 하류로 새지 않는다
        # (의도된 품질 개선·회귀 아님·CLAUDE.md "확실하지 않으면 모른다").
        resp = _client().post("/v1/coach", json={"student_input": "(a+b) 까지만"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # top-1<0.65 → 후보 비움·개입 보류.
        assert body["misconceptions"] == []
        assert body["intervention"] is None


class TestJudgeFlipEndToEnd:
    """judge flag flip 안전성 hermetic E2E — flag on + FakeJudge로 directional FP 라이브 필터 증명.

    substring 방향맹: 정답 "미분가능하면 연속이다"·오답 "연속이면 미분가능하다" 둘 다
    `continuity-implies-differentiability`(signals 연속·미분가능)에 1.0 풀매칭. judge off(기본)면
    정답에도 COUNTEREXAMPLE 낙인 발화가 도달한다(#271/#272 동류·substring 정밀화 불가). flag on +
    방향 판별 judge면 정답(NOT_EXPRESSES)은 필터·오답(EXPRESSES)은 유지 — flip이 라이브 API에서
    안전·정확함을 증명한다(judge 실정확도는 Phaiakes9 측정 소관·여기선 *배선*만 결정론으로 잠금).
    세션 엔드포인트(`_compute_matches`→`_gate`)가 judge 게이트 경로다(스테이트리스 `/v1/coach`는
    diagnose 폴백이라 judge 미적용). 기본 flag는 *불변*(False) — 이 슬라이스는 flip 준비·증명만.
    """

    @staticmethod
    def _directional_judge(**_: object) -> FakeJudge:
        # 올바른 방향 judge 모사: 정답(미분가능⇒연속)은 제거(NOT_EXPRESSES)·오답(연속⇒미분가능)은
        # 유지(EXPRESSES). 실 judge 정확도가 아니라 *flip 배선*을 증명하는 결정론 시임.
        # 좌석이 app.state 공유 provider/cache/trace를 kwargs로 넘기므로 `**_`로 받아 무시한다.
        def _rule(statement: str, _m: Misconception) -> JudgeVerdict:
            return (
                JudgeVerdict.NOT_EXPRESSES
                if "미분가능하면" in statement
                else JudgeVerdict.EXPRESSES
            )

        return FakeJudge(rule=_rule)

    def test_judge_on_filters_correct_direction_keeps_wrong(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WHYMATH_MISCONCEPTION_JUDGE_ENABLED", "true")
        get_settings.cache_clear()
        monkeypatch.setattr(coach, "_judge_for_gate", self._directional_judge)
        try:
            client, _ = _session_client()
            ok = client.post("/v1/coach/sessions", json={"student_input": "미분가능하면 연속이다"})
            wrong = client.post(
                "/v1/coach/sessions", json={"student_input": "연속이면 미분가능하다"}
            )
        finally:
            get_settings.cache_clear()  # 캐시 누수 방지(다음 테스트는 기본 False)
        # 정답 방향: judge NOT_EXPRESSES → 후보 제거 → 매치·개입 없음(거짓 COUNTEREXAMPLE 소멸).
        assert ok.status_code == 201, ok.text
        ok_ids = [m["misconception"]["id"] for m in ok.json()["misconceptions"]]
        assert "continuity-implies-differentiability" not in ok_ids
        assert ok.json()["intervention"] is None
        # 오답 방향: judge EXPRESSES 유지 → 매치·개입 발화(recall 보존).
        assert wrong.status_code == 201, wrong.text
        wrong_ids = [m["misconception"]["id"] for m in wrong.json()["misconceptions"]]
        assert "continuity-implies-differentiability" in wrong_ids
        assert wrong.json()["intervention"] is not None

    def test_judge_off_default_keeps_directional_fp(self) -> None:
        # 기본(flag off)에선 judge 미적용 → 정답도 substring 1.0 매치가 그대로 노출(현행 비트동일·
        # flip이 *고칠* FP를 회귀로 잠금·이 슬라이스는 기본 동작 불변).
        get_settings.cache_clear()  # judge env 미설정=기본 False 보장
        client, _ = _session_client()
        ok = client.post("/v1/coach/sessions", json={"student_input": "미분가능하면 연속이다"})
        assert ok.status_code == 201, ok.text
        ids = [m["misconception"]["id"] for m in ok.json()["misconceptions"]]
        assert "continuity-implies-differentiability" in ids


class TestLthcIntegration:
    def test_mastery_level_triggers_lthc(self) -> None:
        # 초보 → 진입점·비계 ON, 확장 OFF
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "음", "mastery_level": "초보"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["lthc"] is not None
        assert body["lthc"]["mastery_level"] == "초보"
        assert body["lthc"]["entry_suggestions"]  # 비공
        assert body["lthc"]["extensions"] == []

    def test_master_level_extensions_only(self) -> None:
        # 숙달 → 확장 ON, 나머지 OFF
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "음",
                "polya_state": {"current_stage": "review"},
                "mastery_level": "숙달",
            },
        )
        body = resp.json()
        assert body["lthc"]["entry_suggestions"] == []
        assert body["lthc"]["extensions"]  # 비공

    def test_bkt_mastery_derives_level(self) -> None:
        """slice 25: mastery_level 미지정·BKT 숙달(0.1) → '초보'로 환산해 LTHC 도출."""
        resp = _client().post("/v1/coach", json={"student_input": "음", "bkt_mastery": 0.1})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["lthc"] is not None
        assert body["lthc"]["mastery_level"] == "초보"

    def test_explicit_level_overrides_bkt(self) -> None:
        """mastery_level 명시값이 bkt_mastery보다 우선."""
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "음", "mastery_level": "숙달", "bkt_mastery": 0.1},
        )
        assert resp.json()["lthc"]["mastery_level"] == "숙달"

    def test_no_signal_no_lthc(self) -> None:
        """둘 다 없으면 LTHC None(기존 동작 보존)."""
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        assert resp.json()["lthc"] is None

    def test_bkt_mastery_out_of_range_422(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음", "bkt_mastery": 1.5})
        assert resp.status_code == 422


class TestSolutionCoachingWiring:
    """slice 53 — L3→L4 오케스트레이터(slice 52) HTTP 결선.

    학생 발화의 *거짓 수치 관계*(계산 슬립)가 검출되면 `solution_coaching`에 검산(verify)
    코칭 + L3 신호가 실리고, 아니면 None(기존 경로). `arithmetic_error` bool의 첫 실사용.
    """

    def test_calc_slip_surfaces_verify_coaching(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "2 + 3 = 6"})
        assert resp.status_code == 200, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["arithmetic_error"] is True
        assert sc["trigger"]["focus"] == "verify"
        assert sc["trigger"]["socratic_category"] == "evidence"
        assert sc["validation_signal"] is not None
        assert "arithmetic error" in sc["validation_signal"]
        assert sc["error_kind"] == "arithmetic"  # slice 58 — 구조화 분류 노출
        # slice 60 — 오류 위치 span 노출(JSON 배열·원문 슬라이스가 거짓 관계와 일치).
        s, e = sc["error_span"]
        assert "2 + 3 = 6"[s:e] == "2 + 3 = 6"

    def test_inequality_slip_surfaces_verify(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "5 < 3"})
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert "inequality error" in sc["validation_signal"]

    def test_korean_prose_slip_surfaces_verify(self) -> None:
        # slice 54 — 한국어 풀이("계산하면 2 + 3 = 6 입니다")의 슬립도 검출.
        resp = _client().post("/v1/coach", json={"student_input": "계산하면 2 + 3 = 6 입니다"})
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert "arithmetic error" in sc["validation_signal"]

    def test_algebra_solution_slip_surfaces_verify(self) -> None:
        # slice 56 — 틀린 단변수 해("2x+1=7 이므로 x=5")도 검산 코칭.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인해주세요",
                "student_solution": "2x + 1 = 7 이므로 x = 5",
            },
        )
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert "solution error" in sc["validation_signal"]
        assert (
            "한 줄씩" in sc["trigger"]["prompt"]
        )  # slice 61 — 단계 자가검산 변형 발화(위치 비지목)
        # slice 60 — 해 주장("x = 5")을 가리키는 span 노출(방정식 아님).
        sol = "2x + 1 = 7 이므로 x = 5"
        s, e = sc["error_span"]
        assert sol[s:e] == "x = 5"

    def test_solution_steps_surface_focus_step_index(self) -> None:
        # 단계 incorrect 전이 → trigger.focus_step_index 노출 + 위치 인지 발화(정답 부재).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인해주세요",
                "student_solution": "풀이",
                "solution_steps": ["x + 1", "x + 1", "x + 2"],
                "bkt_mastery": 0.9,
            },
        )
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert sc["trigger"]["focus_step_index"] == 1  # 전이 1(steps[1]→steps[2])
        assert "잘 따라왔어" in sc["trigger"]["prompt"]
        assert "틀렸" not in sc["trigger"]["prompt"]

    def test_text_slip_focus_step_index_null(self) -> None:
        # 단계 미제공 → focus_step_index None(하위호환·위치 비지목).
        resp = _client().post("/v1/coach", json={"student_input": "2 + 3 = 6"})
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus_step_index"] is None

    def test_step_shadow_not_exposed_in_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # slice 63 — 코칭도 생기고(대수 슬립) shadow도 검출되는("이므로"·해 {3}≠{5}) 입력에서,
        # 게이트가 켜져 관측이 돌아도 HTTP 응답엔 step 신호 *부재*(비노출). observe_step_breaks는
        # 실 get_settings()를 보므로 env+cache_clear로 게이트를 켠다.
        monkeypatch.setenv("WHYMATH_L4_STEP_SHADOW_ENABLED", "true")
        get_settings.cache_clear()
        try:
            resp = _client().post(
                "/v1/coach",
                json={
                    "student_input": "확인",
                    "student_solution": "2x + 1 = 7 이므로 x = 5",
                },
            )
        finally:
            get_settings.cache_clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["solution_coaching"] is not None  # 코칭은 노출(대수 슬립 검출)
        # shadow step-break 관측(StepBreakObservation·slice 63)은 record_logger에만 sink하고
        # HTTP 응답엔 *절대* 싣지 않는다 — shadow 고유 토큰의 부재로 누출 0을 확정한다. (단,
        # 위치 인지 코칭 메타데이터 `focus_step_index`는 *정상 노출* 필드이므로 'step' 부분
        # 문자열 전역 금지가 아니라 shadow 고유 키만 금지한다 — 위치 인덱스뿐·정답/본문 0.)
        dumped = json.dumps(body, ensure_ascii=False)
        for shadow_token in ("step_break", "StepBreak", "step_shadow", "observation"):
            assert shadow_token not in dumped

    def test_clean_arithmetic_no_solution_coaching(self) -> None:
        # 참 등식 → 슬립 아님 → None(기존 decision/coaching_focus 경로).
        resp = _client().post("/v1/coach", json={"student_input": "3 × 4 = 12"})
        assert resp.json()["solution_coaching"] is None

    def test_question_no_solution_coaching(self) -> None:
        # 수식 없는 질문 → 검증기 보수적 → None(false-positive 0).
        resp = _client().post("/v1/coach", json={"student_input": "이거 어떻게 풀어요?"})
        assert resp.json()["solution_coaching"] is None

    def test_empty_input_no_solution_coaching(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": ""})
        assert resp.json()["solution_coaching"] is None

    def test_slip_overrides_high_mastery(self) -> None:
        # 고숙달이어도 계산 슬립이면 verify(슬립 우선 — slice 51 우선순위 실증).
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "2 + 3 = 6", "bkt_mastery": 0.95},
        )
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"

    def test_default_response_omits_solution_coaching(self) -> None:
        # 기존 동작 불변 — 중립 입력은 solution_coaching None(필드는 항상 존재).
        body = _client().post("/v1/coach", json={"student_input": "음"}).json()
        assert "solution_coaching" in body
        assert body["solution_coaching"] is None

    def test_session_create_surfaces_solution_coaching(self) -> None:
        # 영속 엔드포인트도 동일 신호 노출(공통 _build_response_payload).
        client, _ = _session_client()
        resp = client.post("/v1/coach/sessions", json={"student_input": "2 + 3 = 6"})
        assert resp.status_code == 201, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"

    def test_student_solution_field_is_validated(self) -> None:
        # slice 55 — 풀이 전용 필드의 슬립 검출(발화는 중립, 풀이에 거짓 산술).
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "이거 맞아요?", "student_solution": "2 + 3 = 6"},
        )
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"

    def test_student_solution_takes_precedence_over_input(self) -> None:
        # 풀이가 깨끗하면 발화에 슬립이 있어도 무시(풀이 전용 필드 우선).
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "5 < 3 맞죠?", "student_solution": "3 × 4 = 12"},
        )
        assert resp.json()["solution_coaching"] is None

    def test_falls_back_to_input_when_no_solution(self) -> None:
        # student_solution 미지정 → student_input 검증(slice 53 동작 보존·하위 호환).
        resp = _client().post("/v1/coach", json={"student_input": "2 + 3 = 6"})
        assert resp.json()["solution_coaching"] is not None

    def test_empty_solution_falls_back_to_input(self) -> None:
        # 빈 문자열 풀이 → 폴백(truthiness) → 발화 인라인 슬립 검출.
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "2 + 3 = 6", "student_solution": ""},
        )
        assert resp.json()["solution_coaching"] is not None


class TestSolutionStepsWiring:
    """WH-1 1단계 결선 — `CoachRequest.solution_steps` → verify_solution 단계 검증 노출.

    L5가 분해한 단계 시퀀스를 받으면 `solution_coaching.solution_verification`이 채워지고
    단계 레벨 incorrect는 텍스트 신호와 *추가적 OR*로 결합돼 검산 코칭을 깨운다. 미제공 시
    `solution_verification` None(기존 동작 완전 불변·하위호환).
    """

    def test_incorrect_steps_surface_verification(self) -> None:
        # 텍스트 깨끗·고숙달이라 단계 없으면 advance지만, 단계 incorrect가 verify를 깨운다.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*x + 5"],
            },
        )
        assert resp.status_code == 200, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["arithmetic_error"] is True
        assert sc["trigger"]["focus"] == "verify"
        sv = sc["solution_verification"]
        assert sv is not None
        assert sv["has_incorrect"] is True
        assert sv["first_incorrect_index"] == 0
        assert "한 줄씩" in sc["trigger"]["prompt"]  # 단계 자가검산 변형 발화

    def test_correct_steps_no_step_signal(self) -> None:
        # 전부 correct 전이 → 단계 신호 0 → 기존 BKT↔IRT 경로(노출 게이트로 None).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*(x + 2)"],
            },
        )
        # advance focus는 노출 게이트(_THETA_SURFACED_FOCI) 밖 → solution_coaching None.
        assert resp.json()["solution_coaching"] is None

    def test_steps_omitted_verification_none(self) -> None:
        # 단계 미제공 → solution_verification 노출 안 됨(기존 텍스트 슬립 신호만)·하위호환.
        resp = _client().post("/v1/coach", json={"student_input": "2 + 3 = 6"})
        sc = resp.json()["solution_coaching"]
        assert sc is not None  # 텍스트 슬립은 그대로 검출
        assert sc["solution_verification"] is None  # 단계 미제공 → None

    def test_or_combination_text_slip_steps_correct(self) -> None:
        # OR 결합 — 텍스트 슬립이 있으면 단계가 correct여도 텍스트 신호 보존(약화 0).
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "2 + 3 = 6", "solution_steps": ["x", "x"]},
        )
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["error_kind"] == "arithmetic"  # 텍스트 신호 보존
        assert sc["solution_verification"]["has_incorrect"] is False

    def test_step_types_forwarded_non_algebraic_unverifiable(self) -> None:
        # 비대수 단계 유형(케이스분류)은 unverifiable로 보수 처리(거짓 incorrect 회피).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*x + 5"],
                "solution_step_types": ["케이스분류"],
            },
        )
        # 단계 신호 0(unverifiable) → 기존 경로(advance) → solution_coaching None.
        assert resp.json()["solution_coaching"] is None

    def test_session_create_surfaces_step_verification(self) -> None:
        # 영속 엔드포인트도 동일 — 공통 _build_response_payload 경유.
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*x + 5"],
            },
        )
        assert resp.status_code == 201, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["solution_verification"]["has_incorrect"] is True

    def test_solution_verification_not_exposing_answer(self) -> None:
        # redaction — solution_verification은 학생 *자기 단계*만(정답/본문 누출 0). reason은
        # 검증 사유일 뿐. 학생 입력 외 텍스트가 노출되지 않음을 구조적으로 확인.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*x + 5"],
            },
        )
        sv = resp.json()["solution_coaching"]["solution_verification"]
        # steps의 각 결과는 verify_step 산출(state·reason·evidence_weight) — 정답 필드 없음.
        assert sv["n_transitions"] == 1
        assert len(sv["steps"]) == 1
        assert sv["steps"][0]["state"] == "incorrect"


class TestOcrConfidenceGatingWiring:
    """WH-1 1단계 — `CoachRequest.ocr_confidence` 저신뢰 시 step-incorrect 코칭 보류 노출.

    저신뢰 OCR이면 분해 단계 텍스트가 오인식일 수 있어 verify 코칭에서 step 신호를 누그러뜨리고
    `solution_coaching.verification_ocr_gated`로 노출한다(거짓 지적 방지·정확성 #1). 고신뢰/미제공은
    기존 동작 불변(하위호환). 응답 계약(필드 추가만·6-튜플 형태 불변)은 보존된다.
    """

    def test_low_confidence_gates_step_and_surfaces_flag(self) -> None:
        # 텍스트 깨끗·고숙달 + step incorrect지만 저신뢰 OCR → step 보류(advance) → 노출 게이트로
        # solution_coaching None(advance focus는 _THETA_SURFACED_FOCI 밖·arithmetic_error False).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["2*x + 4", "2*x + 5"],
                "ocr_confidence": 0.5,
            },
        )
        assert resp.status_code == 200, resp.text
        # step이 저신뢰로 보류돼 advance → solution_coaching 미노출(기존 노출 게이트 동작).
        assert resp.json()["solution_coaching"] is None

    def test_low_confidence_flag_surfaced_when_text_slip(self) -> None:
        # 텍스트 슬립(게이팅 안 됨)으로 verify가 노출되는 응답에서 verification_ocr_gated=True 확인.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "2 + 3 = 6",
                "bkt_mastery": 0.95,
                "solution_steps": ["x", "x + 1"],
                "ocr_confidence": 0.5,
            },
        )
        assert resp.status_code == 200, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None  # 텍스트 슬립으로 verify 노출
        assert sc["trigger"]["focus"] == "verify"
        # 텍스트 신호는 OCR 게이팅 안 됨 → 보존. step은 저신뢰로 보류 → gated True.
        assert sc["error_kind"] == "arithmetic"
        assert sc["verification_ocr_gated"] is True
        # 원 verdict는 투명성 위해 노출(has_incorrect 그대로).
        assert sc["solution_verification"]["has_incorrect"] is True

    def test_high_confidence_keeps_verify(self) -> None:
        # 고신뢰 OCR(0.9) → 기존대로 verify·위치 발화·gated False.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["x + 1", "x + 1", "x + 2"],
                "ocr_confidence": 0.9,
            },
        )
        assert resp.status_code == 200, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert sc["trigger"]["focus_step_index"] == 1
        assert sc["verification_ocr_gated"] is False

    def test_confidence_omitted_unchanged(self) -> None:
        # OCR 미제공 → 기존 동작 불변(verify·위치)·gated False(하위호환).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "확인",
                "bkt_mastery": 0.95,
                "solution_steps": ["x + 1", "x + 1", "x + 2"],
            },
        )
        assert resp.status_code == 200, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "verify"
        assert sc["verification_ocr_gated"] is False

    def test_session_create_gates_step_flag(self) -> None:
        # 영속 엔드포인트도 동일 — 공통 _build_response_payload 경유(텍스트 슬립으로 노출 확보).
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "2 + 3 = 6",
                "bkt_mastery": 0.95,
                "solution_steps": ["x", "x + 1"],
                "ocr_confidence": 0.5,
            },
        )
        assert resp.status_code == 201, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["verification_ocr_gated"] is True


class _FakeChainResult(BaseModel):
    """가짜 연쇄 검증 결과 — `ChainVerificationCounts` 구조 계약의 최소 충족분.

    `marker`가 있는 이유: 응답에 실려 나온 것이 *이 가짜의 판정인지* 진짜 수학 구현의 판정인지를
    한 글자로 가르기 위해서다(둘 다 "verdict가 있다"까지는 같은 모양이라 변별력이 없다).
    """

    model_config = ConfigDict(frozen=True)

    steps: list[Any] = []
    first_incorrect_index: int | None = 0
    n_transitions: int = 1
    n_correct: int = 0
    n_incorrect: int = 1
    n_unverifiable: int = 0
    unverified_ratio: float = 0.0
    unverifiable_by_reason: dict[Any, int] = {}
    marker: str = "COMP-01-FAKE"


class _RecordingStepChainVerifier:
    """호출을 기록하는 가짜 `StepChainVerifier` — app.state에 올려 주입 경로를 관측한다."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def verify_chain(
        self, steps: Any, step_types: Any = None
    ) -> _FakeChainResult:  # noqa: ANN401 - 계약 시그니처 그대로
        self.calls.append(list(steps))
        return _FakeChainResult()


class TestStepChainVerifierInjection:
    """COMP-01 — 세 프로덕션 경로가 **app.state 등록분**을 L4에 명시 주입한다.

    이 클래스가 없으면 `api/coach.py`의 `step_chain_verifier=` 인자를 지워도 아무 테스트가
    깨지지 않는다(L4가 합성 루트로 조용히 폴백해 *같은 답*을 내기 때문이다 — 실패 주입 실측).
    그래서 등록분을 **가짜로 갈아 끼우고**, 그 가짜가 호출됐는지와 그 판정이 응답에 실려 나오는지를
    본다. 진짜 수학 구현이라면 아래 단계 시퀀스는 correct(동치)라 `solution_coaching`이 노출
    게이트에서 탈락해 None이 된다 — 즉 두 경로가 서로 다른 값을 낸다(변별력 확보).
    """

    # 진짜 수학 구현이면 correct 전이(2*x+4 ≡ 2*(x+2)) → 노출 None. 가짜면 incorrect → verify.
    _STEPS = ["2*x + 4", "2*(x + 2)"]

    def _install(self, client: TestClient) -> _RecordingStepChainVerifier:
        """`create_app`이 올린 진짜 능력을 가짜로 교체(다른 능력·경로는 그대로)."""
        fake = _RecordingStepChainVerifier()
        client.app.state.__setattr__(STEP_CHAIN_VERIFIER_KEY, fake)
        return fake

    def _assert_used(self, fake: _RecordingStepChainVerifier, payload: dict[str, Any]) -> None:
        assert fake.calls == [self._STEPS], "등록분이 호출되지 않았다 — 합성 루트로 폴백한 것"
        sc = payload["solution_coaching"]
        assert sc is not None, "가짜 판정(incorrect)이 코칭 결정에 반영되지 않았다"
        assert sc["solution_verification"]["marker"] == "COMP-01-FAKE"
        assert sc["trigger"]["focus"] == "verify"

    def test_stateless_coach_injects_registered_verifier(self) -> None:
        client = _client()
        fake = self._install(client)
        resp = client.post(
            "/v1/coach",
            json={"student_input": "확인", "bkt_mastery": 0.95, "solution_steps": self._STEPS},
        )
        assert resp.status_code == 200, resp.text
        self._assert_used(fake, resp.json())

    def test_session_create_injects_registered_verifier(self) -> None:
        client, _ = _session_client()
        fake = self._install(client)
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "확인",
                "student_solution": "2*x + 4",
                "bkt_mastery": 0.95,
                "solution_steps": self._STEPS,
            },
        )
        assert resp.status_code == 201, resp.text
        self._assert_used(fake, resp.json())

    def test_append_turn_injects_registered_verifier(self) -> None:
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did, user_id=_UID, total_turns=2, student_turns=1, assistant_turns=1
            )
        )
        client, _ = _session_client(preload={(DialogueORM, did): dialogue})
        fake = self._install(client)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={
                "student_input": "확인",
                "student_solution": "2*x + 4",
                "bkt_mastery": 0.95,
                "solution_steps": self._STEPS,
            },
        )
        assert resp.status_code == 201, resp.text
        self._assert_used(fake, resp.json())

    def test_missing_registration_is_not_silent(self) -> None:
        """등록이 빠지면 **조용히 폴백하지 않고 터진다** — 침묵 실패 금지의 런타임 판.

        `_subject_capability_state`의 getter가 폴백 없는 `getattr`인 것이 그 장치이며, 이
        테스트는 그 장치가 *실제로* 요청 경로에서 작동하는지를 본다(정본화 ≠ 집행).
        """
        client = _client()
        delattr(client.app.state, STEP_CHAIN_VERIFIER_KEY)
        with pytest.raises(AttributeError):
            client.post("/v1/coach", json={"student_input": "확인"})


class TestHintLevelWiring:
    def test_demand_answer_signal_raises_hint(self) -> None:
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
            },
        )
        body = resp.json()
        # slice 3 — min(4, prev+1) = 2
        assert body["decision"]["hint_level"] == 2
        assert body["decision"]["reveals"] == "step_flow"


class TestMasteryHintConservatism:
    """능력 라벨 → hint level 조정(slice 69 숙달·slice 77 초보). 숙달 −1·초보 +1·발전중/None 불변.

    숙달도 라벨/수치는 `decision`에 *새로* 노출되지 않는다(노출 경계·우열 매기기 금지).
    """

    def test_master_demand_lowered(self) -> None:
        # 답요구 prev=1: base 2 → 숙달이면 1(가장 은근).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
                "mastery_level": "숙달",
            },
        )
        body = resp.json()
        assert body["decision"]["hint_level"] == 1
        assert body["decision"]["reveals"] == "next_concept_to_focus"

    def test_novice_demand_raised(self) -> None:
        # slice 77: 초보는 한 단계 강화(세분화) — base 2 → 3.
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
                "mastery_level": "초보",
            },
        )
        body = resp.json()
        assert body["decision"]["hint_level"] == 3
        assert body["decision"]["reveals"] == "partial_steps_demo"

    def test_no_mastery_unchanged(self) -> None:
        # 숙달도 미지정 → slice 3 동작 그대로(TestHintLevelWiring과 동일).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
            },
        )
        assert resp.json()["decision"]["hint_level"] == 2

    def test_bkt_high_mastery_also_lowers(self) -> None:
        # mastery_level 미지정·bkt≥0.8 → "숙달" 환산 → 보수화 적용(L2→L4 브릿지 일관).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
                "bkt_mastery": 0.95,
            },
        )
        assert resp.json()["decision"]["hint_level"] == 1

    def test_mastery_not_exposed_in_decision(self) -> None:
        # 숙달도 라벨/수치가 decision에 새로 실리지 않음(노출 경계).
        resp = _client().post(
            "/v1/coach",
            json={
                "student_input": "그냥 답이 뭐야",
                "polya_state": {"prev_hint_level": 1},
                "mastery_level": "숙달",
            },
        )
        decision = resp.json()["decision"]
        assert "mastery_level" not in decision
        assert "bkt_mastery" not in decision
        assert "숙달" not in json.dumps(decision, ensure_ascii=False)


class TestServerMastery:
    """slice 70: coach 세션이 서버 L2 숙달도를 조회해 클라 bkt를 대체(게이트 ON·비노출).

    `_server_mastery_for`는 execute 2회(개념해석→숙달도)라 `_CapturingSession`(동일 rows 반환)으론
    구분 불가 → monkeypatch로 고정 반환 패치(L2 함수 자체는 test_mastery_tracking에서 검증).
    """

    _PID = uuid.uuid4()

    def _post(self, client: TestClient, **extra: Any) -> Any:
        body = {
            "student_input": "그냥 답이 뭐야",
            "polya_state": {"prev_hint_level": 1},
            "problem_id": str(self._PID),
            **extra,
        }
        return client.post("/v1/coach/sessions", json=body)

    def test_server_mastery_overrides_client_bkt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 서버 0.9(숙달) — 클라가 0.1(초보)을 보내도 서버값으로 hint 보수화(2→1).
        async def _fake(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return 0.9

        monkeypatch.setattr("whymath_backend.api.coach._server_mastery_for", _fake)
        client, _ = _session_client()
        resp = self._post(client, bkt_mastery=0.1)
        assert resp.status_code == 201, resp.text
        assert resp.json()["decision"]["hint_level"] == 1

    def test_no_server_mastery_falls_back_to_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 서버 None(개념/이력 없음) → 클라 0.1(초보) 사용 → slice 77: 초보 강화 hint 3.
        async def _fake(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return None

        monkeypatch.setattr("whymath_backend.api.coach._server_mastery_for", _fake)
        client, _ = _session_client()
        resp = self._post(client, bkt_mastery=0.1)
        assert resp.json()["decision"]["hint_level"] == 3

    def test_gate_off_skips_server_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 게이트 off → 서버조회 skip → 클라 0.1(초보) → slice 77: 초보 강화 hint 3.
        monkeypatch.setenv("WHYMATH_L4_SERVER_MASTERY_ENABLED", "false")
        get_settings.cache_clear()
        try:
            client, _ = _session_client()
            resp = self._post(client, bkt_mastery=0.1)
            assert resp.json()["decision"]["hint_level"] == 3
        finally:
            get_settings.cache_clear()

    def test_server_mastery_not_exposed_in_decision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return 0.9

        monkeypatch.setattr("whymath_backend.api.coach._server_mastery_for", _fake)
        client, _ = _session_client()
        decision = self._post(client).json()["decision"]
        assert "mastery_level" not in decision
        assert "bkt_mastery" not in decision
        assert "숙달" not in json.dumps(decision, ensure_ascii=False)


class _MasteryQR:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _MasteryQR:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _MasteryQueueSession:
    """execute 호출마다 큐 결과 — `_server_mastery_for`(개념해석→숙달도) 직접 검증용."""

    def __init__(self, results: list[_MasteryQR]) -> None:
        self._results = results
        self._i = 0

    async def execute(self, _stmt: Any) -> _MasteryQR:
        result = self._results[self._i]
        self._i += 1
        return result


class TestServerMasteryHelper:
    """slice 70: `_server_mastery_for` 실체 — 개념해석→현재 숙달도(게이트 ON·패치 없이)."""

    async def test_resolves_primary_concept_then_mastery(self) -> None:
        cid = uuid.uuid4()
        row = ConceptMasteryHistory(mastery=0.9)
        # execute#1=PRIMARY 개념 [cid] → #2=그 개념 최신 측정 row
        fake = _MasteryQueueSession([_MasteryQR([cid]), _MasteryQR([row])])
        m = await coach._server_mastery_for(cast(AsyncSession, fake), _UID, uuid.uuid4())
        assert m == 0.9

    async def test_none_when_no_concept_mapping(self) -> None:
        # PRIMARY·TESTED 모두 없음 → 개념 None → 숙달도 조회 안 함·None.
        fake = _MasteryQueueSession([_MasteryQR([]), _MasteryQR([])])
        m = await coach._server_mastery_for(cast(AsyncSession, fake), _UID, uuid.uuid4())
        assert m is None


class TestServerTheta:
    """slice 73: coach 세션이 서버 L2 θ를 조회해 BKT↔θ *불일치* 코칭을 노출(게이트 ON·θ 비노출).

    `_server_mastery_for`·`_server_theta_for`를 monkeypatch로 고정(L2 함수 자체는 각각
    test_mastery_tracking·test_ability_tracking이 검증). 노출은 *불일치만*(consolidate·
    retrieval)이고 합의(advance/foundation)·diagnose는 비노출. student_input은 계산오류가
    없어(arithmetic_error=False) θ 경로가 트리거를 결정한다.
    """

    _PID = uuid.uuid4()

    def _post(self, client: TestClient, **extra: Any) -> Any:
        body = {
            "student_input": "그냥 답이 뭐야",
            "polya_state": {"prev_hint_level": 1},
            "problem_id": str(self._PID),
            **extra,
        }
        return client.post("/v1/coach/sessions", json=body)

    def _patch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        mastery: float | None,
        theta: float | None,
    ) -> None:
        async def _fm(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return mastery

        async def _ft(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return theta

        monkeypatch.setattr("whymath_backend.api.coach._server_mastery_for", _fm)
        monkeypatch.setattr("whymath_backend.api.coach._server_theta_for", _ft)

    def test_high_theta_low_bkt_surfaces_consolidate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # θ=2.0(proxy≈0.88)·BKT=0.1 → diff>0.2 → consolidate(추측 의심) 노출.
        self._patch(monkeypatch, mastery=0.1, theta=2.0)
        client, _ = _session_client()
        resp = self._post(client)
        assert resp.status_code == 201, resp.text
        sc = resp.json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "consolidate"
        assert sc["arithmetic_error"] is False

    def test_low_theta_high_bkt_surfaces_retrieval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # θ=-2.0(proxy≈0.12)·BKT=0.9 → diff<-0.2 → retrieval(망각 의심) 노출.
        self._patch(monkeypatch, mastery=0.9, theta=-2.0)
        client, _ = _session_client()
        sc = self._post(client).json()["solution_coaching"]
        assert sc is not None
        assert sc["trigger"]["focus"] == "retrieval"

    def test_consensus_advance_not_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # θ=2.0(proxy≈0.88)·BKT=0.9 → 합의(diff 작음)·수준 높음 → advance → 비노출(LTHC 담당).
        self._patch(monkeypatch, mastery=0.9, theta=2.0)
        client, _ = _session_client()
        assert self._post(client).json()["solution_coaching"] is None

    def test_consensus_foundation_not_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # θ=-2.0(proxy≈0.12)·BKT=0.1 → 합의·수준 낮음 → foundation → 비노출.
        self._patch(monkeypatch, mastery=0.1, theta=-2.0)
        client, _ = _session_client()
        assert self._post(client).json()["solution_coaching"] is None

    def test_no_theta_diagnose_not_surfaced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # θ None(스냅샷 없음) → 교차검증 불가 → diagnose → 비노출(기존 동작·하위호환).
        self._patch(monkeypatch, mastery=0.1, theta=None)
        client, _ = _session_client()
        assert self._post(client).json()["solution_coaching"] is None

    def test_theta_value_not_exposed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # consolidate 노출 시에도 θ 수치(2.0)·"theta"는 응답에 없다(정성 코칭 발화만 노출).
        self._patch(monkeypatch, mastery=0.1, theta=2.0)
        client, _ = _session_client()
        sc = self._post(client).json()["solution_coaching"]
        blob = json.dumps(sc, ensure_ascii=False)
        assert "2.0" not in blob
        assert "theta" not in blob.lower()

    def test_gate_off_skips_theta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 게이트 off → θ 조회 skip → None → diagnose → 비노출. (실 _server_theta_for·env)
        async def _fm(session: Any, user_id: Any, problem_id: Any) -> float | None:
            return 0.1

        monkeypatch.setattr("whymath_backend.api.coach._server_mastery_for", _fm)
        monkeypatch.setenv("WHYMATH_L4_SERVER_THETA_ENABLED", "false")
        get_settings.cache_clear()
        try:
            client, _ = _session_client()
            assert self._post(client).json()["solution_coaching"] is None
        finally:
            get_settings.cache_clear()


class _ThetaQR:
    """get_primary_concept_id(`.scalars().all()`)·get_current_ability(Row `.first()`)·
    get_current_theta(스칼라 `.scalars().first()`) 겸용 — rows[0]가 Row/스칼라."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ThetaQR:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _ThetaQueueSession:
    """execute 호출마다 큐 결과 — `_server_theta_for`(개념해석→개념θ→전과목θ) 직접 검증용."""

    def __init__(self, results: list[_ThetaQR]) -> None:
        self._results = results
        self._i = 0

    async def execute(self, _stmt: Any) -> _ThetaQR:
        result = self._results[self._i]
        self._i += 1
        return result


class TestServerThetaHelper:
    """slice 74·76: `_server_theta_for` — 개념 θ는 *신뢰도*(응답수·SE) 충분할 때만·아니면
    전과목 폴백(게이트 ON·패치 없이·기본 임계 min_responses=3·max_se=1.0).

    개념 ability Row = (theta, standard_error, response_count). 신뢰=count≥3 AND SE≤1.0.
    """

    _PID = uuid.uuid4()

    async def test_reliable_concept_theta_preferred(self) -> None:
        # PRIMARY 개념 → 신뢰도 충분(count5·SE0.3) → 개념 θ(정밀 교차검증).
        cid = uuid.uuid4()
        fake = _ThetaQueueSession([_ThetaQR([cid]), _ThetaQR([(2.0, 0.3, 5)])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 2.0

    async def test_low_response_count_falls_back_to_global(self) -> None:
        # 개념 θ 응답 2개(<3·극단 θ) → 불신뢰 → 전과목 θ 폴백.
        cid = uuid.uuid4()
        fake = _ThetaQueueSession([_ThetaQR([cid]), _ThetaQR([(4.0, 0.2, 2)]), _ThetaQR([0.5])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 0.5

    async def test_high_se_falls_back_to_global(self) -> None:
        # 개념 θ SE 큼(1.5>1.0) → 불신뢰 → 전과목 θ 폴백.
        cid = uuid.uuid4()
        fake = _ThetaQueueSession([_ThetaQR([cid]), _ThetaQR([(1.0, 1.5, 8)]), _ThetaQR([0.6])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 0.6

    async def test_none_se_falls_back_to_global(self) -> None:
        # 개념 θ SE 없음(정보 0·극단 θ) → 불신뢰 → 전과목 θ 폴백.
        cid = uuid.uuid4()
        fake = _ThetaQueueSession([_ThetaQR([cid]), _ThetaQR([(4.0, None, 5)]), _ThetaQR([0.4])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 0.4

    async def test_absent_concept_theta_falls_back_to_global(self) -> None:
        # 개념 해석되나 그 개념 θ 스냅샷 없음 → 전과목 θ 폴백.
        cid = uuid.uuid4()
        fake = _ThetaQueueSession([_ThetaQR([cid]), _ThetaQR([]), _ThetaQR([0.7])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 0.7

    async def test_no_concept_mapping_falls_back_to_global(self) -> None:
        # PRIMARY·TESTED 모두 없음 → 개념 None → 전과목 θ 폴백.
        fake = _ThetaQueueSession([_ThetaQR([]), _ThetaQR([]), _ThetaQR([0.3])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, self._PID)
        assert t == 0.3

    async def test_global_when_problem_id_none(self) -> None:
        # problem_id 없음 → 개념 조회 skip → 전과목 θ(slice 73 경로·게이팅 안 함).
        fake = _ThetaQueueSession([_ThetaQR([0.9])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, None)
        assert t == 0.9

    async def test_none_when_no_snapshot(self) -> None:
        # problem_id 없음 + 전과목 스냅샷도 없음 → None.
        fake = _ThetaQueueSession([_ThetaQR([])])
        t = await coach._server_theta_for(cast(AsyncSession, fake), _UID, None)
        assert t is None


class TestAbilityLevelBlend:
    """slice 77: BKT+신뢰 θ 평균 → 적응형 스캐폴딩 ability 라벨(`_ability_level`)."""

    def test_none_both(self) -> None:
        assert coach._ability_level(None, None) is None

    def test_bkt_only(self) -> None:
        assert coach._ability_level(0.2, None) == "초보"
        assert coach._ability_level(0.9, None) == "숙달"

    def test_theta_only(self) -> None:
        # θ=2.0 → logistic≈0.88 → 숙달; θ=-2.0 → ≈0.12 → 초보.
        assert coach._ability_level(None, 2.0) == "숙달"
        assert coach._ability_level(None, -2.0) == "초보"

    def test_blend_lifts_label(self) -> None:
        # BKT 0.2(초보 단독) + θ 2.0(proxy≈0.88) → 평균 0.54 → 발전 중.
        assert coach._ability_level(0.2, 2.0) == "발전 중"

    def test_blend_lowers_label(self) -> None:
        # BKT 0.9(숙달 단독) + θ -2.0(proxy≈0.12) → 평균 0.51 → 발전 중.
        assert coach._ability_level(0.9, -2.0) == "발전 중"


class TestThetaIntoScaffolding:
    """slice 77: 통합 ability 라벨이 hint·Polya 전이 결정에 실제 반영(θ 有無 차이)."""

    def test_theta_lifts_label_lowers_hint(self) -> None:
        # 답요구 → base 2. BKT 0.2 단독=초보 → +1(=3). +θ 2.0=발전중 → 불변(=2).
        body = coach.CoachRequest(student_input="답 알려줘")
        dec_bkt, *_ = coach._build_response_payload(body, server_mastery=0.2, server_theta=None)
        dec_theta, *_ = coach._build_response_payload(body, server_mastery=0.2, server_theta=2.0)
        assert dec_bkt.hint_level == 3
        assert dec_theta.hint_level == 2

    def test_theta_lifts_label_advances_transition(self) -> None:
        # UNDERSTAND 17자+마침표. BKT 0.7=발전중 → min_len 20 > 17 → stay.
        # +θ 4.0 → 평균 0.84=숙달 → min_len 15 ≤ 17 → next(θ가 전이 임계를 낮춤).
        text = "가" * 16 + "."
        body = coach.CoachRequest(student_input=text)
        dec_dev, *_ = coach._build_response_payload(body, server_mastery=0.7, server_theta=None)
        dec_mas, *_ = coach._build_response_payload(body, server_mastery=0.7, server_theta=4.0)
        assert dec_dev.polya_stage_to_advance == "stay"
        assert dec_mas.polya_stage_to_advance == "next"


class TestHintLevelEscalationWiring:
    """WH-1 1단계 잔여: Polya `decision.hint_level`이 solution 코칭 점층으로 결선됨."""

    # step-incorrect(2x+4 ≠ 2x+5) → verify_steps 경로(점층 대상).
    _STEPS = ["2*x + 4", "2*x + 5"]

    def test_decision_hint_level_escalates_solution_coaching(self) -> None:
        """turn_count 5 + 발전 중 → decision.hint_level 3 → 단계 자가검산 점층 발화."""
        body = coach.CoachRequest(
            student_input="풀이",
            student_solution="풀이",
            solution_steps=self._STEPS,
            mastery_level="발전 중",  # 완화/강화 없음 → turn≥5 → hint_level 3
            polya_state={"current_stage": "execute", "turn_count": 5},
        )
        decision, *_rest, sol = coach._build_response_payload(
            body, server_mastery=0.9, server_theta=2.0
        )
        assert decision.hint_level == 3
        assert sol is not None
        assert sol.trigger.focus == "verify"
        assert sol.trigger.hint_level == 3  # decision.hint_level이 그대로 결선
        assert "어떤 규칙" in sol.trigger.prompt  # 점층 과정-비계 발화

    def test_low_turn_no_escalation(self) -> None:
        """turn_count 0 → hint_level 1 → 점층 안 됨(대조·발화 불변 경로)."""
        body = coach.CoachRequest(
            student_input="풀이",
            student_solution="풀이",
            solution_steps=self._STEPS,
            mastery_level="발전 중",
            polya_state={"current_stage": "execute", "turn_count": 0},
        )
        decision, *_rest, sol = coach._build_response_payload(
            body, server_mastery=0.9, server_theta=2.0
        )
        assert decision.hint_level == 1
        assert sol is not None
        assert sol.trigger.hint_level == 1
        assert "어떤 규칙" not in sol.trigger.prompt  # 점층 아님


class TestActiveHypothesesIntoSocratic:
    """누적 활성 오개념 가설 → 소크라테스 카테고리(ASSUMPTION 가정 표면화) 결선.

    #266 순수 규칙(`select_category`·`decide`)을 라이브 coach 경로에 *활성화*한다 — 세션/턴
    핸들러가 `_apply_hypotheses` post-apply 세트를 `_build_response_payload`로 넘긴다.
    """

    _PID = uuid.uuid4()

    # --- 단위: _build_response_payload가 가설을 decide로 thread(hermetic·직접 호출) ---
    def test_payload_threads_high_conf_hypothesis_to_assumption(self) -> None:
        # PLAN·"음"(stay·無신호) 기본=perspective지만 고신뢰·최근 가설 → assumption.
        body = coach.CoachRequest(student_input="음", polya_state={"current_stage": "plan"})
        decision, *_ = coach._build_response_payload(body, misconception_hypotheses=[_hyp(0.8)])
        assert decision.polya_stage_to_advance == "stay"
        assert decision.socratic_category == "assumption"

    def test_payload_no_hypotheses_keeps_stage_default(self) -> None:
        # 미주입(기본 None) → 현행 비트동일(PLAN 기본 perspective).
        body = coach.CoachRequest(student_input="음", polya_state={"current_stage": "plan"})
        decision, *_ = coach._build_response_payload(body)
        assert decision.socratic_category == "perspective"

    def test_payload_low_confidence_hypothesis_keeps_default(self) -> None:
        # 저신뢰 가설(floor 미달) → 단계 기본 불변(맞은/약한 가설 학생 영향 0).
        body = coach.CoachRequest(student_input="음", polya_state={"current_stage": "plan"})
        decision, *_ = coach._build_response_payload(body, misconception_hypotheses=[_hyp(0.3)])
        assert decision.socratic_category == "perspective"

    # --- 엔드포인트: 핸들러 재정렬이 가설을 실제로 활성화(_apply_hypotheses monkeypatch) ---
    def _post_session(self, client: TestClient, student_input: str) -> Any:
        return client.post(
            "/v1/coach/sessions",
            json={
                "student_input": student_input,
                "polya_state": {"current_stage": "plan"},
                "problem_id": str(self._PID),
            },
        )

    def test_session_high_conf_hypothesis_surfaces_assumption(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
            return [_hyp(0.8)]

        monkeypatch.setattr("whymath_backend.api.coach._apply_hypotheses", _fake)
        client, _ = _session_client()
        resp = self._post_session(client, "음")  # stay·無신호
        assert resp.status_code == 201, resp.text
        assert resp.json()["decision"]["socratic_category"] == "assumption"

    def test_session_empty_hypotheses_keeps_stage_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
            return []

        monkeypatch.setattr("whymath_backend.api.coach._apply_hypotheses", _fake)
        client, _ = _session_client()
        resp = self._post_session(client, "음")
        assert resp.status_code == 201, resp.text
        assert resp.json()["decision"]["socratic_category"] == "perspective"

    def test_stateless_endpoint_unaffected(self) -> None:
        # stateless /v1/coach는 세션·가설 없음 → 단계 기본(불변·하위호환).
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "음", "polya_state": {"current_stage": "plan"}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["decision"]["socratic_category"] == "perspective"


class TestAuthGate:
    def test_no_token_401(self) -> None:
        resp = _no_auth_client().post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers


class TestRequestValidation:
    def test_missing_student_input_422(self) -> None:
        assert _client().post("/v1/coach", json={}).status_code == 422

    def test_oversize_input_422(self) -> None:
        big = "가" * 4001  # max_length=4000
        assert _client().post("/v1/coach", json={"student_input": big}).status_code == 422

    def test_bad_mastery_level_422(self) -> None:
        resp = _client().post(
            "/v1/coach",
            json={"student_input": "음", "mastery_level": "고수"},  # 비-Literal
        )
        assert resp.status_code == 422

    def test_extra_field_forbidden(self) -> None:
        resp = _client().post("/v1/coach", json={"student_input": "음", "foo": "bar"})
        assert resp.status_code == 422


class TestSessionPersistence:
    """`/v1/coach/sessions` — dialogue + 2 turn 영속 결선(hermetic)."""

    def test_creates_dialogue_and_two_turns_201(self) -> None:
        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "내 풀이는 (a+b)² = a² + b² 이렇게 했어"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 응답 — decision/misconceptions/intervention + 영속 ID 3종
        assert "dialogue_id" in body
        assert "student_turn_id" in body
        assert "assistant_turn_id" in body
        assert body["intervention"]["pattern"] == "counterexample"
        # WH-1 멀티턴 카운터 — 새 dialogue 첫 교환은 턴 1·ε-탐색 아님(§2.2).
        assert body["wh1_turn_index"] == 1
        assert body["wh1_exploration_turn"] is False

        # 영속 — 1 dialogue + 2 turns, commit 2회(parent 먼저, child 다음).
        from whymath_backend.db.models.dialogue import (
            Dialogue as DialogueORM,
        )
        from whymath_backend.db.models.dialogue import (
            DialogueTurn as DialogueTurnORM,
        )

        dialogues = [o for o in captured.added if isinstance(o, DialogueORM)]
        turns = [o for o in captured.added if isinstance(o, DialogueTurnORM)]
        assert len(dialogues) == 1
        assert len(turns) == 2
        assert captured.commits == 2  # dialogue → turns 순서
        # dialogue 1회 + 매치당 증거 적재(§2.3 생산측·log_evidence가 link_id로 refresh)라 ≥1.
        assert captured.refreshes >= 1

    def test_user_id_scoped_to_authenticated_user(self) -> None:
        # 본인 데이터 차단 — dialogue.user_id는 인증된 user.user_id로 자동
        client, captured = _session_client()
        client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "problem_id": str(uuid.uuid4())},
        )
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM

        dialogue = next(o for o in captured.added if isinstance(o, DialogueORM))
        assert dialogue.user_id == _UID

    def test_student_turn_content_matches_input(self) -> None:
        client, captured = _session_client()
        client.post(
            "/v1/coach/sessions",
            json={"student_input": "내 풀이는 이렇게 했어"},
        )
        from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM

        turns = [o for o in captured.added if isinstance(o, DialogueTurnORM)]
        student_t = next(t for t in turns if t.role == "student")
        assistant_t = next(t for t in turns if t.role == "assistant")
        assert student_t.content == "내 풀이는 이렇게 했어"
        assert student_t.turn_order == 1
        assert assistant_t.turn_order == 2
        # AI 턴 content = decision.prompt — LLM 호출 없이 결정된 발화 보존
        assert assistant_t.content  # 비공

    def test_no_token_401(self) -> None:
        resp = _no_auth_client().post("/v1/coach/sessions", json={"student_input": "음"})
        assert resp.status_code == 401

    def test_extra_field_forbidden(self) -> None:
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "evil": "field"},
        )
        assert resp.status_code == 422

    def test_bad_problem_id_422(self) -> None:
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "problem_id": "not-a-uuid"},
        )
        assert resp.status_code == 422


class TestTurnMetaWriter:
    """PED-04 D1 acceptance ① — 세션 경로가 이미 계산된 값으로 메타 4컬럼을 채운다(hermetic).

    실 PG NULL 잔존 0 검증은 `test_coach_integration.py`(라이브)의 짝이 맡는다 — 여기선
    핸들러가 `_build_dialogue_turn`에 *무엇을 넘기는지*(ORM 속성)만 hermetic으로 본다.
    """

    def test_student_turn_gets_intent_and_understanding_signal(self) -> None:
        client, captured = _session_client()
        client.post(
            "/v1/coach/sessions",
            json={"student_input": "왜 그렇게 되는지 이유를 모르겠어요"},
        )
        from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM

        student_t = next(o for o in captured.added if isinstance(o, DialogueTurnORM)).__class__
        turns = [o for o in captured.added if isinstance(o, student_t)]
        student = next(t for t in turns if t.role == "student")
        assistant = next(t for t in turns if t.role == "assistant")
        # 좌절+질문 토큰이 섞였지만 좌절이 없고 "왜/이유"만 있으므로 질문 신호가 먼저 걸린다.
        assert student.student_intent is not None
        assert student.student_understanding_signal is not None
        assert 0.0 <= student.student_understanding_signal <= 1.0
        # 학생 턴엔 AI 전용 축이 비어 있어야 한다(정의상 비어있음 — 결손 아님).
        assert student.socratic_strategy is None
        # AI 턴엔 targeted_step이 반드시 있고(단계는 항상 결정됨), 학생 전용 축은 비어 있다.
        assert assistant.targeted_step is not None
        assert assistant.student_intent is None
        assert assistant.student_understanding_signal is None
        # 두 턴 다 같은 목표 단계를 가리켜야 한다(같은 교환의 같은 맥락).
        assert student.targeted_step == assistant.targeted_step

    def test_demand_answer_input_classified_as_giveup(self) -> None:
        client, captured = _session_client()
        client.post(
            "/v1/coach/sessions",
            json={"student_input": "그냥 답 알려주세요"},
        )
        from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM

        turns = [o for o in captured.added if isinstance(o, DialogueTurnORM)]
        student = next(t for t in turns if t.role == "student")
        assert student.student_intent == "포기"

    def test_empty_input_first_turn_has_no_intent(self) -> None:
        """빈 발화 + 풀이 없음 → 의도 미분류(None) — 날조 금지."""
        client, captured = _session_client()
        client.post("/v1/coach/sessions", json={"student_input": ""})
        from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM

        turns = [o for o in captured.added if isinstance(o, DialogueTurnORM)]
        student = next(t for t in turns if t.role == "student")
        assert student.student_intent is None

    def test_stateless_coach_endpoint_untouched_by_meta_writer(self) -> None:
        """stateless `/v1/coach`는 DB 무접근 계약 — 메타 writer 관련 코드도 호출되지 않는다."""
        client = _client()
        resp = client.post("/v1/coach", json={"student_input": "테스트"})
        assert resp.status_code == 200
        # 응답에 client_state_mismatch 등 세션 전용 필드가 없어야 한다(OpenAPI 계약 무변경).
        assert "client_state_mismatch" not in resp.json()


class TestClientStateMismatchFlag:
    """PED-04 D2 acceptance ③ — 클라 제출 Polya 상태와 서버 파생이 어긋나면 표면화한다."""

    def test_first_session_no_history_default_state_no_mismatch(self) -> None:
        """새 세션(이력 0)에서 클라가 기본 PolyaState(UNDERSTAND·turn_count=0)를 보내면
        서버 파생(prev_hint_level 없음의 기본값)과 일치 — 불일치 플래그 False."""
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "안녕하세요"},
        )
        assert resp.json()["client_state_mismatch"] is False

    def test_false_polya_state_flags_mismatch(self) -> None:
        """새 세션인데 클라가 EXECUTE·turn_count=99를 거짓 제출 → 서버 파생(UNDERSTAND·0)과
        어긋나 플래그 True. 결정은 여전히 서버 파생 기준(응답 200·정상 처리)."""
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "안녕하세요",
                "polya_state": {"current_stage": "execute", "turn_count": 99},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["client_state_mismatch"] is True

    def test_stateless_endpoint_has_no_mismatch_field(self) -> None:
        """stateless 경로는 서버 파생 자체가 없어 플래그를 노출하지 않는다(가짜 계기판 금지)."""
        client = _client()
        resp = client.post(
            "/v1/coach",
            json={
                "student_input": "테스트",
                "polya_state": {"current_stage": "execute", "turn_count": 99},
            },
        )
        assert resp.status_code == 200
        assert "client_state_mismatch" not in resp.json()


class TestTurnAppend:
    """`/v1/coach/sessions/{id}/turns` — 2턴 추가 결선."""

    def _preloaded_dialogue(
        self,
        dialogue_id: uuid.UUID,
        owner: uuid.UUID,
        total_turns: int = 2,
    ) -> Any:
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        return (DialogueORM, dialogue_id), DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=dialogue_id,
                user_id=owner,
                total_turns=total_turns,
                student_turns=1,
                assistant_turns=1,
            )
        )

    def test_append_creates_two_turns_with_continuing_order(self) -> None:
        from whymath_backend.db.models.dialogue import DialogueTurn as DialogueTurnORM

        did = uuid.uuid4()
        key, dialogue = self._preloaded_dialogue(did, _UID, total_turns=2)
        client, captured = _session_client(preload={key: dialogue})

        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "이번엔 다른 풀이 해볼게"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 다음 학생 turn_order = 직전 total_turns(2) + 1 = 3
        assert body["student_turn_order"] == 3
        assert body["assistant_turn_order"] == 4
        # WH-1 멀티턴 카운터 — 직전 total_turns=2 → 이번 교환은 턴 2(누적·연속성·§2.2).
        assert body["wh1_turn_index"] == 2
        assert body["wh1_exploration_turn"] is False

        # 영속 — 2 turns added, dialogue 카운트 업데이트, 1 commit
        turns = [o for o in captured.added if isinstance(o, DialogueTurnORM)]
        assert len(turns) == 2
        assert captured.commits == 1
        # dialogue 카운트가 증가됨
        assert dialogue.total_turns == 4
        assert dialogue.student_turns == 2
        assert dialogue.assistant_turns == 2

    def test_append_exploration_turn_on_fifth_exchange(self) -> None:
        """직전 total_turns=8 → 이번 교환은 턴 5 → ε-탐색 강제 턴(§2.2 규칙2·카운터 누적)."""
        did = uuid.uuid4()
        key, dialogue = self._preloaded_dialogue(did, _UID, total_turns=8)
        client, _ = _session_client(preload={key: dialogue})

        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "5턴째 풀이"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["wh1_turn_index"] == 5
        assert body["wh1_exploration_turn"] is True

    def test_nonexistent_dialogue_404(self) -> None:
        client, captured = _session_client()  # 빈 preload
        resp = client.post(
            f"/v1/coach/sessions/{uuid.uuid4()}/turns",
            json={"student_input": "음"},
        )
        assert resp.status_code == 404
        # DB 쓰기 발생 안 함
        assert captured.added == []
        assert captured.commits == 0

    def test_other_users_dialogue_404(self) -> None:
        # 타인 소유 dialogue → 404 (403 분리하지 않음 — 존재 노출 회피)
        other_uid = uuid.uuid4()
        did = uuid.uuid4()
        key, dialogue = self._preloaded_dialogue(did, other_uid, total_turns=2)
        client, captured = _session_client(preload={key: dialogue})

        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "타인 세션 가로채기 시도"},
        )
        assert resp.status_code == 404
        assert captured.added == []

    def test_no_token_401(self) -> None:
        did = uuid.uuid4()
        resp = _no_auth_client().post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "음"},
        )
        assert resp.status_code == 401

    def test_bad_dialogue_id_format_422(self) -> None:
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions/not-a-uuid/turns",
            json={"student_input": "음"},
        )
        assert resp.status_code == 422

    def test_total_turns_none_starts_from_1(self) -> None:
        # 기존 dialogue.total_turns가 None이면 0으로 취급 → 학생=1·AI=2
        did = uuid.uuid4()
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        dialogue = DialogueORM.from_schema(
            DialogueSchema(dialogue_id=did, user_id=_UID, total_turns=None)
        )
        client, _ = _session_client(preload={(DialogueORM, did): dialogue})
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "음"},
        )
        body = resp.json()
        assert body["student_turn_order"] == 1
        assert body["assistant_turn_order"] == 2


class TestStepShadowProblemContext:
    """slice 64 — 문항 맥락(problem_id·expected_answer) shadow 주입의 *비노출* 보장.

    핵심 안전 불변식: 기대정답은 서버 DB 조회로만 얻어 shadow 로그 sink에만 흐르고, HTTP
    응답에는 *절대* 실리지 않는다(student-facing이면 정답 누출 = 치명적). 게이트는
    `observe_step_breaks`와 동일(`WHYMATH_L4_STEP_SHADOW_ENABLED`)하며 모듈 `get_settings()`를
    직접 읽으므로 env+`cache_clear`로 켠다(test_step_shadow와 동형).
    """

    # 단계 비보존(해 {3}≠{4}) + 순차유도 마커 → step shadow가 검출하는 풀이.
    _SOLUTION = "2x = 6 따라서 3x = 12"
    _SENTINEL = "ANSWER_SENTINEL_DONOTLEAK"  # Problem.answer에만 존재 — 응답에 새면 누출

    def _shadow_msgs(self, caplog: pytest.LogCaptureFixture) -> list[str]:
        return [r.getMessage() for r in caplog.records if r.name == "whymath.l4.step_shadow"]

    def test_create_session_answer_not_in_response(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from types import SimpleNamespace

        from whymath_backend.db.models.problem import Problem as ProblemORM

        monkeypatch.setenv("WHYMATH_L4_STEP_SHADOW_ENABLED", "true")
        get_settings.cache_clear()
        pid = uuid.uuid4()
        preload = {(ProblemORM, pid): SimpleNamespace(answer=self._SENTINEL)}
        client, _ = _session_client(preload=preload)
        try:
            with caplog.at_level(logging.INFO, logger="whymath.l4.step_shadow"):
                resp = client.post(
                    "/v1/coach/sessions",
                    json={
                        "student_input": "이거 맞아요?",
                        "student_solution": self._SOLUTION,
                        "problem_id": str(pid),
                    },
                )
            assert resp.status_code == 201, resp.text
            # 🔒 정답 비노출 — sentinel이 응답 본문 어디에도 없어야(직렬화 전체 검사)
            assert self._SENTINEL not in resp.text
            assert self._SENTINEL not in json.dumps(resp.json())
            # 맥락은 shadow 로그엔 도달(정답이 shadow sink로만 흘렀음을 적극 증명)
            msgs = self._shadow_msgs(caplog)
            assert any(self._SENTINEL in m and str(pid) in m for m in msgs)
        finally:
            get_settings.cache_clear()

    def test_append_turns_answer_not_in_response(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 멀티턴 경로도 dialogue.problem_id로 맥락 주입 — 같은 비노출 불변.
        from types import SimpleNamespace

        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.db.models.problem import Problem as ProblemORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        monkeypatch.setenv("WHYMATH_L4_STEP_SHADOW_ENABLED", "true")
        get_settings.cache_clear()
        did = uuid.uuid4()
        pid = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did,
                user_id=_UID,
                problem_id=pid,
                total_turns=2,
                student_turns=1,
                assistant_turns=1,
            )
        )
        preload = {
            (DialogueORM, did): dialogue,
            (ProblemORM, pid): SimpleNamespace(answer=self._SENTINEL),
        }
        client, _ = _session_client(preload=preload)
        try:
            with caplog.at_level(logging.INFO, logger="whymath.l4.step_shadow"):
                resp = client.post(
                    f"/v1/coach/sessions/{did}/turns",
                    json={"student_input": "검토", "student_solution": self._SOLUTION},
                )
            assert resp.status_code == 201, resp.text
            assert self._SENTINEL not in resp.text
            msgs = self._shadow_msgs(caplog)
            assert any(self._SENTINEL in m and str(pid) in m for m in msgs)
        finally:
            get_settings.cache_clear()

    def test_gate_off_skips_answer_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 게이트 off(프로덕션 기본) → 정답 조회·접근 자체를 안 함(불필요 적재 차단·비용).
        from whymath_backend.db.models.problem import Problem as ProblemORM

        monkeypatch.setenv("WHYMATH_L4_STEP_SHADOW_ENABLED", "false")
        get_settings.cache_clear()
        pid = uuid.uuid4()

        class _ExplodingProblem:
            @property
            def answer(self) -> str:
                raise AssertionError("게이트 off면 정답을 조회·접근하지 않아야 한다.")

        preload = {(ProblemORM, pid): _ExplodingProblem()}
        client, _ = _session_client(preload=preload)
        try:
            resp = client.post(
                "/v1/coach/sessions",
                json={"student_input": "음", "problem_id": str(pid)},
            )
            assert resp.status_code == 201, resp.text
        finally:
            get_settings.cache_clear()


class TestSessionGet:
    """`GET /v1/coach/sessions/{id}` — dialogue 메타 + turn 목록 조회."""

    def test_returns_dialogue_and_turns(self) -> None:
        from whymath_backend.db.models.dialogue import (
            Dialogue as DialogueORM,
        )
        from whymath_backend.db.models.dialogue import (
            DialogueTurn as DialogueTurnORM,
        )
        from whymath_backend.schema.dialogue import (
            Dialogue as DialogueSchema,
        )
        from whymath_backend.schema.dialogue import (
            DialogueTurn as DialogueTurnSchema,
        )
        from whymath_backend.schema.enums import TurnRole

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(dialogue_id=did, user_id=_UID, total_turns=2)
        )
        t1 = DialogueTurnORM.from_schema(
            DialogueTurnSchema(
                dialogue_id=did,
                turn_order=1,
                role=TurnRole.student,
                content="문제 시도",
            )
        )
        t2 = DialogueTurnORM.from_schema(
            DialogueTurnSchema(
                dialogue_id=did, turn_order=2, role=TurnRole.assistant, content="질문"
            )
        )
        client, _ = _session_client(
            preload={(DialogueORM, did): dialogue},
            execute_rows=[t1, t2],
        )
        resp = client.get(f"/v1/coach/sessions/{did}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["dialogue"]["dialogue_id"] == str(did)
        assert len(body["turns"]) == 2
        assert body["turns"][0]["role"] == "student"
        assert body["turns"][0]["content"] == "문제 시도"
        assert body["turns"][1]["role"] == "assistant"

    def test_empty_dialogue_returns_zero_turns(self) -> None:
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(DialogueSchema(dialogue_id=did, user_id=_UID))
        client, _ = _session_client(preload={(DialogueORM, did): dialogue}, execute_rows=[])
        resp = client.get(f"/v1/coach/sessions/{did}")
        assert resp.status_code == 200
        assert resp.json()["turns"] == []

    def test_nonexistent_404(self) -> None:
        client, _ = _session_client()
        resp = client.get(f"/v1/coach/sessions/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_other_users_dialogue_404(self) -> None:
        # 타인 소유 → 404(403 분리 안 함, 존재 노출 회피)
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        other_uid = uuid.uuid4()
        dialogue = DialogueORM.from_schema(DialogueSchema(dialogue_id=did, user_id=other_uid))
        client, _ = _session_client(preload={(DialogueORM, did): dialogue})
        resp = client.get(f"/v1/coach/sessions/{did}")
        assert resp.status_code == 404

    def test_no_token_401(self) -> None:
        resp = _no_auth_client().get(f"/v1/coach/sessions/{uuid.uuid4()}")
        assert resp.status_code == 401

    def test_bad_uuid_422(self) -> None:
        client, _ = _session_client()
        resp = client.get("/v1/coach/sessions/not-a-uuid")
        assert resp.status_code == 422


class TestSessionGetConditional:
    """`GET /v1/coach/sessions/{id}` — ETag + If-None-Match → 304(읽기 캐싱)."""

    def _preloaded(self) -> tuple[uuid.UUID, dict[Any, Any], list[Any]]:
        from whymath_backend.db.models.dialogue import (
            Dialogue as DialogueORM,
        )
        from whymath_backend.db.models.dialogue import (
            DialogueTurn as DialogueTurnORM,
        )
        from whymath_backend.schema.dialogue import (
            Dialogue as DialogueSchema,
        )
        from whymath_backend.schema.dialogue import (
            DialogueTurn as DialogueTurnSchema,
        )
        from whymath_backend.schema.enums import TurnRole

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(dialogue_id=did, user_id=_UID, total_turns=2)
        )
        t1 = DialogueTurnORM.from_schema(
            DialogueTurnSchema(dialogue_id=did, turn_order=1, role=TurnRole.student, content="A")
        )
        t2 = DialogueTurnORM.from_schema(
            DialogueTurnSchema(dialogue_id=did, turn_order=2, role=TurnRole.assistant, content="B")
        )
        return did, {(DialogueORM, did): dialogue}, [t1, t2]

    def test_200_includes_etag_header(self) -> None:
        did, preload, rows = self._preloaded()
        client, _ = _session_client(preload=preload, execute_rows=rows)
        resp = client.get(f"/v1/coach/sessions/{did}")
        assert resp.status_code == 200
        assert resp.headers.get("ETag")  # 따옴표 포함 강한 ETag

    def test_matching_if_none_match_returns_304(self) -> None:
        did, preload, rows = self._preloaded()
        client, _ = _session_client(preload=preload, execute_rows=rows)
        first = client.get(f"/v1/coach/sessions/{did}")
        etag = first.headers["ETag"]

        # 같은 ETag로 재요청 → 304, 빈 본문, ETag 유지
        resp = client.get(f"/v1/coach/sessions/{did}", headers={"If-None-Match": etag})
        assert resp.status_code == 304
        assert resp.content == b""
        assert resp.headers["ETag"] == etag

    def test_wildcard_if_none_match_returns_304(self) -> None:
        did, preload, rows = self._preloaded()
        client, _ = _session_client(preload=preload, execute_rows=rows)
        resp = client.get(f"/v1/coach/sessions/{did}", headers={"If-None-Match": "*"})
        assert resp.status_code == 304

    def test_stale_if_none_match_returns_200(self) -> None:
        # 무관한 ETag → 본문 반환(현재 ETag와 다름)
        did, preload, rows = self._preloaded()
        client, _ = _session_client(preload=preload, execute_rows=rows)
        resp = client.get(
            f"/v1/coach/sessions/{did}",
            headers={"If-None-Match": '"deadbeefdeadbeef"'},
        )
        assert resp.status_code == 200
        assert resp.json()["turns"]

    def test_etag_changes_when_turns_change(self) -> None:
        # 같은 dialogue·다른 turn 집합 → 다른 ETag(내용 해시이므로 자동 무효화)
        did, preload, rows = self._preloaded()
        client_a, _ = _session_client(preload=preload, execute_rows=rows)
        etag_a = client_a.get(f"/v1/coach/sessions/{did}").headers["ETag"]

        # turn 1개만 노출(짧은 결과) → 다른 ETag
        client_b, _ = _session_client(preload=preload, execute_rows=rows[:1])
        etag_b = client_b.get(f"/v1/coach/sessions/{did}").headers["ETag"]
        assert etag_a != etag_b


class TestRateLimit:
    """coach 엔드포인트 사용자당 분당 상한 — 초과 시 429 + Retry-After."""

    def test_under_limit_passes(self) -> None:
        # limit=3 → 3회까지 통과
        client = _client(rate_limit=3)
        for _ in range(3):
            assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200

    def test_over_limit_returns_429(self) -> None:
        # limit=2 → 3번째 요청 429 + Retry-After
        client = _client(rate_limit=2)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "60"

    def test_zero_means_disabled(self) -> None:
        # limit=0 → 무제한(기본 테스트 모드)
        client = _client(rate_limit=0)
        for _ in range(20):
            assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200

    def test_get_endpoint_also_limited(self) -> None:
        # GET /v1/coach/sessions/{id}도 동일 버킷 카운트 — 임계 공유
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(DialogueSchema(dialogue_id=did, user_id=_UID))
        client, _ = _session_client(
            preload={(DialogueORM, did): dialogue},
            execute_rows=[],
            rate_limit=1,
        )
        # 1번 통과
        assert client.get(f"/v1/coach/sessions/{did}").status_code == 200
        # 2번째 429
        resp = client.get(f"/v1/coach/sessions/{did}")
        assert resp.status_code == 429

    def test_sliding_window_prunes_expired(self) -> None:
        # 클럭 seam — 60초 후엔 옛 히트가 만료돼 다시 통과
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.0)).allowed is True
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.5)).allowed is False
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=61.0)).allowed is True


class _FakeRedisClient:
    """Lua evalsha/script_load seam — `_LUA_HIT` 스크립트의 *의미*를 in-memory ZSET으로 재현.

    실제 Redis 없이도 RedisBackend의 결선·키 네이밍·TTL 호출·EVALSHA 캐시 의미를 검증할 수
    있게 한다(Lua 스크립트 자체의 정확성은 통합 테스트에서 실 Redis로 검증).

    스크립트 캐시 모델: `script_load(script)`로 적재된 SHA만 evalsha가 인정. 적재 전 evalsha
    호출은 `NoScriptError`(redis-py 정본 예외)로 거절.
    """

    def __init__(self) -> None:
        self.zsets: dict[str, list[tuple[float, str]]] = {}
        self.expires: dict[str, int] = {}
        self.evalsha_calls: list[tuple[str, int, tuple[Any, ...]]] = []
        self.script_loads: list[str] = []
        self._loaded_shas: set[str] = set()

    def _apply_hit_script(self, args: tuple[Any, ...]) -> list[int]:
        """Lua 스크립트 의미 재현 — `[allowed, count_after, oldest_micros]` 반환."""
        key = args[0]
        now = float(args[1])
        limit = int(args[2])
        member = args[3]
        cutoff = now - 60
        bucket = self.zsets.setdefault(key, [])
        bucket[:] = [(s, m) for (s, m) in bucket if s >= cutoff]
        allowed = 1 if len(bucket) < limit else 0
        if allowed:
            bucket.append((now, member))
            self.expires[key] = 60
        oldest_micros = -1
        if bucket:
            oldest_micros = int(bucket[0][0] * 1_000_000)
        return [allowed, len(bucket), oldest_micros]

    def _apply_hit_both_script(self, args: tuple[Any, ...]) -> list[int]:
        """Lua _LUA_HIT_BOTH 의미 재현 — 원자 user+IP 검사. 5-튜플 반환."""
        user_key = args[0]
        ip_key = args[1]
        now = float(args[2])
        user_limit = int(args[3])
        ip_limit = int(args[4])
        member = args[5]
        cutoff = now - 60
        user_count = -1
        ip_count = -1
        user_ok = True
        ip_ok = True
        if user_limit > 0:
            bucket = self.zsets.setdefault(user_key, [])
            bucket[:] = [(s, m) for (s, m) in bucket if s >= cutoff]
            user_count = len(bucket)
            if user_count >= user_limit:
                user_ok = False
        if ip_limit > 0:
            bucket = self.zsets.setdefault(ip_key, [])
            bucket[:] = [(s, m) for (s, m) in bucket if s >= cutoff]
            ip_count = len(bucket)
            if ip_count >= ip_limit:
                ip_ok = False
        allowed = 1 if (user_ok and ip_ok) else 0
        if allowed:
            if user_limit > 0:
                self.zsets[user_key].append((now, member))
                self.expires[user_key] = 60
                user_count += 1
            if ip_limit > 0:
                self.zsets[ip_key].append((now, member))
                self.expires[ip_key] = 60
                ip_count += 1
        user_oldest = -1
        ip_oldest = -1
        if user_limit > 0 and self.zsets.get(user_key):
            user_oldest = int(self.zsets[user_key][0][0] * 1_000_000)
        if ip_limit > 0 and self.zsets.get(ip_key):
            ip_oldest = int(self.zsets[ip_key][0][0] * 1_000_000)
        return [allowed, user_count, user_oldest, ip_count, ip_oldest]

    def _apply_hit_many_script(self, numkeys: int, args: tuple[Any, ...]) -> list[int]:
        """Lua _LUA_HIT_MANY 의미 재현 — KEYS 가변·ARGV [now, member, limit1..limitN]."""
        keys = list(args[:numkeys])
        now = float(args[numkeys])
        member = args[numkeys + 1]
        limits = [int(x) for x in args[numkeys + 2 : numkeys + 2 + numkeys]]
        cutoff = now - 60
        for k in keys:
            bucket = self.zsets.setdefault(k, [])
            bucket[:] = [(s, m) for (s, m) in bucket if s >= cutoff]
        counts = [len(self.zsets[k]) for k in keys]
        # counts·limits 모두 keys(=numkeys)당 1개씩 생성되어 길이가 항상 같다 → strict=True
        all_ok = all(c < lim for c, lim in zip(counts, limits, strict=True))
        if all_ok:
            for i, k in enumerate(keys):
                self.zsets[k].append((now, member))
                self.expires[k] = 60
                counts[i] += 1
        response: list[int] = [1 if all_ok else 0]
        for i, k in enumerate(keys):
            response.append(counts[i])
            oldest = -1
            if self.zsets[k]:
                oldest = int(self.zsets[k][0][0] * 1_000_000)
            response.append(oldest)
        return response

    async def evalsha(self, sha: str, numkeys: int, *args: Any) -> Any:
        self.evalsha_calls.append((sha, numkeys, args))
        if sha not in self._loaded_shas:
            from redis.exceptions import NoScriptError

            raise NoScriptError("NOSCRIPT No matching script. Use SCRIPT LOAD.")
        # SHA로 분기 — _LUA_HIT_MANY / _LUA_HIT_BOTH / _LUA_HIT
        from whymath_backend.api._rate_limit import (
            _LUA_HIT_BOTH_SHA1,
            _LUA_HIT_MANY_SHA1,
        )

        if sha == _LUA_HIT_MANY_SHA1:
            return self._apply_hit_many_script(numkeys, args)
        if sha == _LUA_HIT_BOTH_SHA1:
            return self._apply_hit_both_script(args)
        return self._apply_hit_script(args)

    async def script_load(self, script: str) -> Any:
        self.script_loads.append(script)
        import hashlib

        sha = hashlib.sha1(script.encode("utf-8")).hexdigest()
        self._loaded_shas.add(sha)
        return sha

    async def ping(self) -> Any:
        return True

    async def delete(self, *names: str) -> Any:
        for n in names:
            self.zsets.pop(n, None)
            self.expires.pop(n, None)
        return len(names)

    async def keys(self, pattern: str) -> Any:
        prefix = pattern.rstrip("*")
        return [k for k in self.zsets if k.startswith(prefix)]


class TestRedisBackend:
    """RedisBackend 결선 — fake `_RedisClient`로 Lua eval·키·TTL 검증."""

    def test_hit_returns_true_under_limit(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = uuid.uuid4()
        assert asyncio.run(backend.hit(uid, category="read", limit=2, now=0.0)).allowed is True
        assert asyncio.run(backend.hit(uid, category="read", limit=2, now=0.1)).allowed is True
        assert asyncio.run(backend.hit(uid, category="read", limit=2, now=0.2)).allowed is False

    def test_hit_uses_canonical_key_prefix(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = uuid.uuid4()
        asyncio.run(backend.hit(uid, category="read", limit=1, now=0.0))
        assert f"rate:coach:read:user:{uid}" in fake.zsets

    def test_reset_clears_all_keys(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.0))
        asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.0))
        assert len(fake.zsets) == 2
        asyncio.run(backend.reset())
        assert fake.zsets == {}

    def test_prunes_expired_via_lua_semantics(self) -> None:
        # cutoff = now - 60 → 옛 히트는 prune
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = uuid.uuid4()
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.0)).allowed is True
        # 같은 윈도우 — 초과
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.5)).allowed is False
        # 60초+ — prune되어 통과
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=61.0)).allowed is True


class TestRedisBackendLazyPaths:
    """`RedisBackend` lazy 해석 경로 — 주입 없으면 settings/client 지연 생성."""

    def test_resolved_settings_falls_back_to_global(self) -> None:
        from whymath_backend.api._rate_limit import RedisBackend

        backend = RedisBackend()  # settings/client 모두 주입 X
        # _resolved_settings는 get_settings() 캐시된 전역으로 폴백
        assert backend._resolved_settings is not None  # type: ignore[truthy-bool]

    def test_resolved_settings_uses_injection_when_provided(self) -> None:
        # settings 주입 시 — get_settings() 미호출, 주입된 인스턴스 그대로 반환
        from whymath_backend.api._rate_limit import RedisBackend

        injected = _settings_override(0)
        backend = RedisBackend(client=_FakeRedisClient(), settings=injected)
        assert backend._resolved_settings is injected

    def test_reset_with_no_keys_noops(self) -> None:
        # keys() 빈 결과 → delete 호출 분기 회피
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        asyncio.run(backend.reset())  # zsets 비어있음 → keys=[] → delete 미호출

    def test_get_client_lazy_builds_default_when_not_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 주입된 client 없으면 `_build_default_redis_client`를 호출해 lazy 생성
        import asyncio

        from whymath_backend.api import _rate_limit as rl

        fake = _FakeRedisClient()
        monkeypatch.setattr(rl, "_build_default_redis_client", lambda s: fake)
        backend = rl.RedisBackend()  # client 주입 X
        # 첫 hit — lazy build 발화 + EVALSHA NOSCRIPT → script_load + 재시도
        assert (
            asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=2, now=0.0)).allowed
            is True
        )
        # 첫 hit: evalsha 2회(NOSCRIPT + 재시도), script_load 1회
        assert len(fake.evalsha_calls) == 2
        assert len(fake.script_loads) == 1
        # 두번째 hit — script 이미 캐시됨, evalsha 1회만(NOSCRIPT 없음)
        assert (
            asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=2, now=0.1)).allowed
            is True
        )
        assert len(fake.evalsha_calls) == 3
        assert len(fake.script_loads) == 1  # 추가 load 없음


class TestBackendSelection:
    """`configure_backend_from_settings` — 설정으로 백엔드 선택."""

    def test_memory_default(self) -> None:
        from whymath_backend.api._rate_limit import (
            InMemoryBackend,
            configure_backend_from_settings,
            get_backend,
        )

        configure_backend_from_settings(_settings_override(0))
        assert isinstance(get_backend(), InMemoryBackend)

    def test_redis_when_configured(self) -> None:
        from whymath_backend.api._rate_limit import (
            RedisBackend,
            configure_backend_from_settings,
            get_backend,
        )

        s = Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_backend="redis",
        )
        configure_backend_from_settings(s)
        try:
            assert isinstance(get_backend(), RedisBackend)
        finally:
            # 다음 테스트 격리 — 기본 InMemory로 복원
            configure_backend_from_settings(_settings_override(0))


class TestEvalshaOptimization:
    """슬라이스 13 — EVALSHA + NOSCRIPT 폴백 최적화 정합 검증."""

    def test_sha1_matches_redis_canonical(self) -> None:
        # `_LUA_HIT_SHA1`이 Redis SCRIPT LOAD가 반환할 정본 SHA와 같아야 EVALSHA 캐시 적중
        import hashlib

        from whymath_backend.api._rate_limit import _LUA_HIT, _LUA_HIT_SHA1

        expected = hashlib.sha1(_LUA_HIT.encode("utf-8")).hexdigest()
        assert _LUA_HIT_SHA1 == expected
        assert len(_LUA_HIT_SHA1) == 40  # SHA1 hex

    def test_first_hit_triggers_script_load_then_evalsha(self) -> None:
        # 빈 스크립트 캐시 → 첫 evalsha NOSCRIPT → script_load → 재시도 → 성공
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        assert (
            asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=2, now=0.0)).allowed
            is True
        )
        assert fake.script_loads == [
            __import__("whymath_backend.api._rate_limit", fromlist=["_LUA_HIT"])._LUA_HIT
        ]
        assert len(fake.evalsha_calls) == 2  # 1회 NOSCRIPT + 1회 재시도

    def test_subsequent_hits_use_cached_script(self) -> None:
        # 두번째 호출부터는 evalsha 1회만(NOSCRIPT 없음·script_load 추가 호출 없음)
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.0))
        evalsha_after_first = len(fake.evalsha_calls)
        loads_after_first = len(fake.script_loads)

        # 추가 5회 — 전부 evalsha 1회씩만
        for i in range(5):
            asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.1 + i * 0.01))
        assert len(fake.evalsha_calls) == evalsha_after_first + 5
        assert len(fake.script_loads) == loads_after_first  # 변동 없음

    def test_recovers_from_script_flush(self) -> None:
        # Redis가 SCRIPT FLUSH/재시작된 경우 시뮬레이션 — 캐시 비우면 다음 evalsha NOSCRIPT
        # → 자동으로 script_load + 재시도
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.0))
        assert len(fake.script_loads) == 1  # 첫 적재

        # Redis SCRIPT FLUSH 시뮬레이션
        fake._loaded_shas.clear()
        asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=10, now=0.1))
        assert len(fake.script_loads) == 2  # 재적재 발화


class TestReadWriteSeparation:
    """슬라이스 14 — POST/GET 차등 한도. 두 카테고리 *별도 버킷*."""

    def test_write_limit_does_not_block_reads(self) -> None:
        # write_limit=1 소진 + read_limit=10 → read는 여전히 통과
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(DialogueSchema(dialogue_id=did, user_id=_UID))

        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(limit=10, write_limit=1)
        captured = _CapturingSession(preload={(DialogueORM, did): dialogue}, execute_rows=[])

        async def _sess() -> AsyncIterator[_CapturingSession]:
            yield captured

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)

        # POST 1회 — write_limit=1 소진
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        # POST 2회 — 429(write 한도 초과)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 429
        # GET 여러 번 — read 한도(10)는 별도 버킷이라 영향 없음
        for _ in range(5):
            assert client.get(f"/v1/coach/sessions/{did}").status_code == 200

    def test_read_limit_does_not_block_writes(self) -> None:
        # read_limit=1 소진 + write_limit=10 → write는 여전히 통과
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(DialogueSchema(dialogue_id=did, user_id=_UID))

        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(limit=1, write_limit=10)
        captured = _CapturingSession(preload={(DialogueORM, did): dialogue}, execute_rows=[])

        async def _sess() -> AsyncIterator[_CapturingSession]:
            yield captured

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)

        # GET 1회 — read_limit=1 소진
        assert client.get(f"/v1/coach/sessions/{did}").status_code == 200
        # GET 2회 — 429(read 한도 초과)
        assert client.get(f"/v1/coach/sessions/{did}").status_code == 429
        # POST 여러 번 — write 한도(10)는 별도 버킷이라 영향 없음
        for _ in range(5):
            assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200


class TestRateCategoryBackend:
    """`InMemoryBackend`·`RedisBackend`가 `category`별 *별도 버킷* 유지."""

    def test_inmemory_categories_isolated(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        # write 1/1 한도 도달
        assert asyncio.run(backend.hit(uid, category="write", limit=1, now=0.0)).allowed is True
        assert asyncio.run(backend.hit(uid, category="write", limit=1, now=0.1)).allowed is False
        # 같은 사용자의 read 버킷은 독립 — 영향 없음
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.2)).allowed is True

    def test_redis_key_prefix_includes_category(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = uuid.uuid4()
        asyncio.run(backend.hit(uid, category="read", limit=10, now=0.0))
        asyncio.run(backend.hit(uid, category="write", limit=10, now=0.0))
        assert f"rate:coach:read:user:{uid}" in fake.zsets
        assert f"rate:coach:write:user:{uid}" in fake.zsets


class TestRateLimitHeaders:
    """슬라이스 15 — X-RateLimit-* 응답 헤더(클라이언트 자체 throttle 입력)."""

    def test_200_includes_rate_limit_headers(self) -> None:
        client = _client(rate_limit=5)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "5"
        # 1회 사용 → 4 남음
        assert resp.headers["X-RateLimit-Remaining"] == "4"
        # 즉시 1슬롯 비기까지의 시간 ≤ 60(같은 초에 발급된 1개 → ~60초 후 비어짐)
        reset = int(resp.headers["X-RateLimit-Reset"])
        assert 0 <= reset <= 60

    def test_429_includes_rate_limit_headers_and_retry_after(self) -> None:
        client = _client(rate_limit=1)
        # 첫 호출 200
        first = client.post("/v1/coach", json={"student_input": "음"})
        assert first.status_code == 200
        assert first.headers["X-RateLimit-Remaining"] == "0"
        # 두번째 호출 — 429
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Limit"] == "1"
        assert resp.headers["X-RateLimit-Remaining"] == "0"
        # Retry-After = reset_seconds(>= 0). 0이면 사양상 "즉시" 의미라 본 실패서 1+ 권장.
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after >= 1
        # X-RateLimit-Reset도 동봉
        assert int(resp.headers["X-RateLimit-Reset"]) >= 0

    def test_remaining_decrements_across_requests(self) -> None:
        client = _client(rate_limit=3)
        r1 = client.post("/v1/coach", json={"student_input": "음"})
        r2 = client.post("/v1/coach", json={"student_input": "음"})
        r3 = client.post("/v1/coach", json={"student_input": "음"})
        assert r1.headers["X-RateLimit-Remaining"] == "2"
        assert r2.headers["X-RateLimit-Remaining"] == "1"
        assert r3.headers["X-RateLimit-Remaining"] == "0"

    def test_zero_limit_no_headers_no_429(self) -> None:
        # limit=0이면 dep는 짧게 반환·헤더 미세팅
        client = _client(rate_limit=0)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" not in resp.headers
        assert "X-RateLimit-Remaining" not in resp.headers


class TestRateLimitResultStruct:
    """`RateLimitResult` 결과 구조 — InMemoryBackend 직접 호출."""

    def test_first_hit_allowed_remaining_and_reset(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend, RateLimitResult

        backend = InMemoryBackend()
        result = asyncio.run(backend.hit(uuid.uuid4(), category="read", limit=5, now=100.0))
        assert isinstance(result, RateLimitResult)
        assert result.allowed is True
        assert result.remaining == 4  # limit - 1
        # 60초 윈도우에 방금 추가 → reset ≈ 60
        assert result.reset_seconds == 60

    def test_denied_when_at_limit(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        asyncio.run(backend.hit(uid, category="read", limit=1, now=100.0))
        result = asyncio.run(backend.hit(uid, category="read", limit=1, now=100.5))
        assert result.allowed is False
        assert result.remaining == 0
        # 옛 항목이 100.0에 추가됨 → 100.5 시점엔 ~60초 후 만료
        assert result.reset_seconds == 60


class TestIpRateLimit:
    """슬라이스 16 — IP 단위 한도(미인증 표면). 사용자 키와 *네임스페이스 분리*."""

    def test_inmemory_ip_isolated_from_user(self) -> None:
        # 같은 prefix("read") 카테고리지만 user key와 ip key는 완전 분리
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        # 사용자 한도 1 소진
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.0)).allowed is True
        assert asyncio.run(backend.hit(uid, category="read", limit=1, now=0.1)).allowed is False
        # 같은 사용자 *as IP*가 별도 키 — IP 한도는 별개
        assert (
            asyncio.run(backend.hit_by_ip(str(uid), category="read", limit=1, now=0.2)).allowed
            is True
        )

    def test_redis_ip_key_prefix_explicit(self) -> None:
        # IP 키는 `rate:coach:{cat}:ip:{addr}` — 사용자 키와 충돌 X
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        ip = "203.0.113.42"
        uid = uuid.uuid4()
        asyncio.run(backend.hit_by_ip(ip, category="read", limit=10, now=0.0))
        asyncio.run(backend.hit(uid, category="read", limit=10, now=0.0))
        assert f"rate:coach:read:ip:{ip}" in fake.zsets
        assert f"rate:coach:read:user:{uid}" in fake.zsets

    def test_two_ips_independent_buckets(self) -> None:
        # 다른 IP는 같은 한도를 독립적으로 쓴다
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        assert (
            asyncio.run(backend.hit_by_ip("1.1.1.1", category="write", limit=1, now=0.0)).allowed
            is True
        )
        # 다른 IP는 별도 버킷
        assert (
            asyncio.run(backend.hit_by_ip("2.2.2.2", category="write", limit=1, now=0.1)).allowed
            is True
        )

    def test_x_forwarded_for_extraction(self) -> None:
        # SEC-24(원 SEC-14): 직접 피어가 신뢰 프록시 목록에 있을 때만 X-Forwarded-For를
        # 신뢰(우측-신뢰). 상세 매트릭스는 tests/backend/api/test_client_ip_trusted_proxy.py.
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_ip

        request = MagicMock()
        request.headers = {"x-forwarded-for": "198.51.100.1, 10.0.0.5"}
        request.client = MagicMock()
        request.client.host = "10.0.0.99"
        settings = Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            trusted_proxy_ip_allowlist="10.0.0.99, 10.0.0.5",
        )
        assert _client_ip(request, settings=settings) == "198.51.100.1"

    def test_direct_client_host_fallback(self) -> None:
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_ip

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "192.0.2.99"
        settings = Settings(jwt_secret_key=SecretStr("test-secret-0123456789abcdef"))
        assert _client_ip(request, settings=settings) == "192.0.2.99"

    def test_no_client_returns_none(self) -> None:
        # request.client None → 알 수 없는 IP라 한도 미적용 신호
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_ip

        request = MagicMock()
        request.headers = {}
        request.client = None
        settings = Settings(jwt_secret_key=SecretStr("test-secret-0123456789abcdef"))
        assert _client_ip(request, settings=settings) is None

    def test_empty_xff_header_falls_back(self) -> None:
        # X-Forwarded-For: "  " (공백) → 빈 head → request.client.host로 폴백
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_ip

        request = MagicMock()
        request.headers = {"x-forwarded-for": "   "}
        request.client = MagicMock()
        request.client.host = "192.0.2.50"
        settings = Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            trusted_proxy_ip_allowlist="192.0.2.50",
        )
        assert _client_ip(request, settings=settings) == "192.0.2.50"

    def test_ip_dep_enforces_limit_via_test_endpoint(self) -> None:
        # 임시 미인증 엔드포인트로 IP dep 결선 검증
        from fastapi import APIRouter

        from whymath_backend.api._rate_limit import RateLimitedIpRead

        router = APIRouter()

        @router.get("/_test/ip-limited", dependencies=[RateLimitedIpRead])
        async def _hit() -> dict[str, bool]:
            return {"ok": True}

        app = create_app()
        app.include_router(router)
        # IP read 한도 1, write 0(영향 없음)
        app.dependency_overrides[get_settings] = lambda: Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_read_per_minute=0,
            coach_rate_limit_write_per_minute=0,
            coach_rate_limit_ip_read_per_minute=1,
        )
        client = TestClient(app)
        # 1회 통과
        r1 = client.get("/_test/ip-limited")
        assert r1.status_code == 200
        # 2회 429 + 헤더
        r2 = client.get("/_test/ip-limited")
        assert r2.status_code == 429
        assert r2.headers["X-RateLimit-Limit"] == "1"
        assert r2.headers["X-RateLimit-Remaining"] == "0"


class TestIpRateLimitEdgeCases:
    """슬라이스 16 잔여 결선 — write IP·limit=0·IP None 폴백."""

    def test_ip_write_dep_enforces_via_test_endpoint(self) -> None:
        from fastapi import APIRouter

        from whymath_backend.api._rate_limit import RateLimitedIpWrite

        router = APIRouter()

        @router.post("/_test/ip-write-limited", dependencies=[RateLimitedIpWrite])
        async def _hit() -> dict[str, bool]:
            return {"ok": True}

        app = create_app()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_read_per_minute=0,
            coach_rate_limit_write_per_minute=0,
            coach_rate_limit_ip_write_per_minute=1,
        )
        client = TestClient(app)
        assert client.post("/_test/ip-write-limited").status_code == 200
        resp = client.post("/_test/ip-write-limited")
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Limit"] == "1"

    def test_ip_limit_zero_disables_enforcement(self) -> None:
        # IP limit=0 → 의존성이 짧게 반환, 응답 헤더 미세팅
        from fastapi import APIRouter

        from whymath_backend.api._rate_limit import RateLimitedIpRead

        router = APIRouter()

        @router.get("/_test/ip-disabled", dependencies=[RateLimitedIpRead])
        async def _hit() -> dict[str, bool]:
            return {"ok": True}

        app = create_app()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_ip_read_per_minute=0,  # 비활성
        )
        client = TestClient(app)
        for _ in range(5):
            resp = client.get("/_test/ip-disabled")
            assert resp.status_code == 200
            assert "X-RateLimit-Limit" not in resp.headers

    def test_dep_skips_when_ip_unknown(self) -> None:
        # request.client=None → IP 알 수 없음 → dep 짧게 반환(헤더 0건·예외 0건)
        import asyncio
        from unittest.mock import MagicMock

        from fastapi import Response

        from whymath_backend.api._rate_limit import (
            rate_limit_ip_read,
            rate_limit_ip_write,
        )

        request = MagicMock()
        request.headers = {}
        request.client = None
        settings = Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_ip_read_per_minute=1,
            coach_rate_limit_ip_write_per_minute=1,
        )
        response = Response()
        asyncio.run(rate_limit_ip_read(request, settings, response))
        asyncio.run(rate_limit_ip_write(request, settings, response))
        assert "X-RateLimit-Limit" not in response.headers


class TestDefenseInDepth:
    """슬라이스 17 — 사용자 + IP 동시 적용. 둘 다 통과해야 200·뜨거운 쪽 헤더."""

    def test_user_limit_fires_before_ip(self) -> None:
        # user_limit=1, ip_limit=10 → 2번째 요청은 사용자 한도에서 429
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=1, ip_limit=0, ip_write_limit=10
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        # 사용자 한도가 발화 → 헤더는 user 기준(Limit=1)
        assert resp.headers["X-RateLimit-Limit"] == "1"

    def test_ip_limit_fires_when_user_loose(self) -> None:
        # user_limit=100, ip_limit=1 → 두번째 요청은 IP 한도에서 429
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=100, ip_limit=0, ip_write_limit=1
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        # IP 한도가 발화 → 헤더는 IP 기준(Limit=1)
        assert resp.headers["X-RateLimit-Limit"] == "1"

    def test_tighter_remaining_shown_on_200(self) -> None:
        # user_limit=10, ip_limit=2 → IP가 더 엄격 → 헤더에 IP의 remaining 노출
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=10, ip_limit=0, ip_write_limit=2
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        # IP는 remaining=1(2-1), user는 9(10-1). 더 엄격한 IP 노출.
        assert resp.headers["X-RateLimit-Limit"] == "2"
        assert resp.headers["X-RateLimit-Remaining"] == "1"

    def test_user_only_when_ip_unknown(self) -> None:
        # request.client = None인 상황은 hermetic으론 어렵지만, ip_limit=0이면 IP 검사
        # 비활성. user 한도만 적용되어야 한다.
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=1, ip_limit=0, ip_write_limit=0
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        assert resp.headers["X-RateLimit-Limit"] == "1"

    def test_both_zero_no_enforcement(self) -> None:
        # 둘 다 0 → 무한 통과·헤더 없음
        client = _client(rate_limit=0)  # 이미 ip_limit=0 기본
        for _ in range(20):
            resp = client.post("/v1/coach", json={"student_input": "음"})
            assert resp.status_code == 200
            assert "X-RateLimit-Limit" not in resp.headers


class TestHitBothAtomic:
    """슬라이스 18 — `hit_both` 원자 동시 검사. 한쪽 거부 시 양쪽 미증가."""

    def test_inmemory_both_pass_increments_both(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        result = asyncio.run(
            backend.hit_both(
                uid,
                "1.2.3.4",
                category="read",
                user_limit=5,
                ip_limit=10,
                now=100.0,
            )
        )
        assert result.allowed is True
        assert result.user_result is not None
        assert result.ip_result is not None
        assert result.user_result.remaining == 4  # 5-1
        assert result.ip_result.remaining == 9  # 10-1

    def test_inmemory_user_blocks_ip_not_incremented(self) -> None:
        # user 한도 1 소진 후, 같은 user+다른 IP 시도 → 둘 다 증가 X
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        # user에 1 추가(한도 도달)
        asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=1, ip_limit=10, now=0.0)
        )
        # 같은 user, *다른* IP — user 한도 도달이라 atomic deny
        result = asyncio.run(
            backend.hit_both(uid, "2.2.2.2", category="read", user_limit=1, ip_limit=10, now=0.1)
        )
        assert result.allowed is False
        # IP 2.2.2.2 버킷은 *미증가*(0개) → remaining = 10
        assert result.ip_result is not None
        assert result.ip_result.remaining == 10

    def test_inmemory_prunes_expired_entries(self) -> None:
        # 60초 후의 hit_both — 옛 항목 prune되어 카운트 0부터 다시(분기 커버)
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=1, ip_limit=1, now=0.0)
        )
        denied = asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=1, ip_limit=1, now=0.5)
        )
        assert denied.allowed is False
        # 60초+ 후 — 옛 항목 prune되어 통과
        passed = asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=1, ip_limit=1, now=61.0)
        )
        assert passed.allowed is True

    def test_inmemory_atomic_no_waste_counter(self) -> None:
        # 핵심 invariant — IP가 거부면 user counter 낭비 안 함
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        uid = uuid.uuid4()
        # IP에 1 추가(한도 도달)
        asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=10, ip_limit=1, now=0.0)
        )
        # 같은 uid+같은 ip → IP 한도 도달이라 atomic deny
        result = asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=10, ip_limit=1, now=0.1)
        )
        assert result.allowed is False
        # user counter는 *미증가* — 다음 다른 IP에서 user_limit 그대로
        followup = asyncio.run(
            backend.hit_both(uid, "2.2.2.2", category="read", user_limit=10, ip_limit=10, now=0.2)
        )
        # user_count가 누적 1(첫 호출만) — IP 거부된 두번째는 user 미증가
        assert followup.allowed is True
        assert followup.user_result is not None
        assert followup.user_result.remaining == 8  # 10 - 2(첫+세번째)

    def test_inmemory_user_only_when_ip_none(self) -> None:
        # ip=None이면 user만 검사 — ip_result=None
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        result = asyncio.run(
            backend.hit_both(
                uuid.uuid4(),
                None,
                category="read",
                user_limit=5,
                ip_limit=10,
                now=0.0,
            )
        )
        assert result.allowed is True
        assert result.user_result is not None
        assert result.ip_result is None

    def test_inmemory_ip_only_when_user_limit_zero(self) -> None:
        # user_limit=0이면 IP만 검사
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        result = asyncio.run(
            backend.hit_both(
                uuid.uuid4(),
                "1.1.1.1",
                category="read",
                user_limit=0,
                ip_limit=5,
                now=0.0,
            )
        )
        assert result.allowed is True
        assert result.user_result is None
        assert result.ip_result is not None

    def test_redis_hit_both_atomic_lua(self) -> None:
        # Lua _LUA_HIT_BOTH가 원자성 보장 — fake로 의미 재현 확인
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = uuid.uuid4()
        # IP에 1 추가(한도 도달)
        r1 = asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=10, ip_limit=1, now=0.0)
        )
        assert r1.allowed is True
        # 같은 ip → IP 거부 → atomic 거부 → user counter 낭비 X
        r2 = asyncio.run(
            backend.hit_both(uid, "1.1.1.1", category="read", user_limit=10, ip_limit=1, now=0.1)
        )
        assert r2.allowed is False
        # user 키엔 1개만 있어야 함(낭비 0)
        from whymath_backend.api._rate_limit import RedisBackend as RB  # noqa: N817

        user_key = f"{RB._KEY_PREFIX}read:user:{uid}"
        assert len(fake.zsets[user_key]) == 1

    def test_redis_noscript_fallback_for_hit_both(self) -> None:
        # _LUA_HIT_BOTH도 NOSCRIPT 폴백 자동 적재
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        # 새 backend — _LUA_HIT_BOTH 캐시 비어있음
        backend = RedisBackend(client=fake)
        result = asyncio.run(
            backend.hit_both(
                uuid.uuid4(),
                "1.1.1.1",
                category="read",
                user_limit=5,
                ip_limit=5,
                now=0.0,
            )
        )
        assert result.allowed is True
        # script_load 발화·재시도
        assert len(fake.script_loads) >= 1


class TestDefenseAtomicInRouter:
    """슬라이스 18 결선 — _enforce_defense가 hit_both 사용해 낭비 0."""

    def test_ip_block_does_not_consume_user_quota(self) -> None:
        # user=10, ip=1로 첫 요청 → 통과. 두번째 → IP 거부.
        # 세번째 *다른 IP*로 → user 한도 그대로(낭비 0이라 9 남아야 함, 8 아님)
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user

        # 매 요청 시 settings를 새로 — 이상적이지만 여기선 동일 limit 고정.
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=10, ip_limit=0, ip_write_limit=1
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        # IP=testclient라 둘 다 같은 ip — 한 client는 같은 IP. 1회만 IP 통과.
        r1 = client.post("/v1/coach", json={"student_input": "음"})
        assert r1.status_code == 200
        # X-RateLimit-Remaining(user 입장)이 9, ip 입장이 0
        # 더 엄격한 ip가 노출 (Remaining=0)
        assert r1.headers["X-RateLimit-Remaining"] == "0"
        # 두번째 — IP 한도 도달, atomic 거부 → user counter 낭비 X
        r2 = client.post("/v1/coach", json={"student_input": "음"})
        assert r2.status_code == 429
        # blocker는 IP — Limit=1
        assert r2.headers["X-RateLimit-Limit"] == "1"


class TestPairHeaders:
    """슬라이스 19 — `X-RateLimit-User-*`/`-Ip-*` 두 쌍 헤더 동시 노출."""

    def test_defense_200_emits_both_pairs_and_rollup(self) -> None:
        # user=10, ip=2 → 200 응답에 User-*, Ip-*, rollup 모두 동봉
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=10, ip_limit=0, ip_write_limit=2
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200
        # rollup (더 엄격한 = IP)
        assert resp.headers["X-RateLimit-Limit"] == "2"
        assert resp.headers["X-RateLimit-Remaining"] == "1"
        # 두 쌍 동시
        assert resp.headers["X-RateLimit-User-Limit"] == "10"
        assert resp.headers["X-RateLimit-User-Remaining"] == "9"
        assert resp.headers["X-RateLimit-Ip-Limit"] == "2"
        assert resp.headers["X-RateLimit-Ip-Remaining"] == "1"

    def test_defense_429_emits_pairs_on_blocker(self) -> None:
        # ip 한도 1 소진 후 429 — User-* 와 Ip-* 둘 다 동봉
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=10, ip_limit=0, ip_write_limit=1
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        assert client.post("/v1/coach", json={"student_input": "음"}).status_code == 200
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 429
        # blocker(IP)의 rollup
        assert resp.headers["X-RateLimit-Limit"] == "1"
        assert resp.headers["X-RateLimit-Remaining"] == "0"
        # 두 쌍 동시 — 첫 호출에서 user count=1, 두번째 atomic deny → user 그대로 1.
        # User-Remaining = 10 - 1 = 9. Ip-Remaining = 0(blocker).
        assert resp.headers["X-RateLimit-User-Limit"] == "10"
        assert resp.headers["X-RateLimit-User-Remaining"] == "9"
        assert resp.headers["X-RateLimit-Ip-Limit"] == "1"
        assert resp.headers["X-RateLimit-Ip-Remaining"] == "0"

    def test_user_only_active_emits_only_user_pair(self) -> None:
        # ip_limit=0이면 User-*만 노출, Ip-*는 미세팅
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=5, ip_limit=0, ip_write_limit=0
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-User-Limit"] == "5"
        assert "X-RateLimit-Ip-Limit" not in resp.headers

    def test_ip_only_endpoint_emits_ip_pair(self) -> None:
        # 미인증 IP-only dep도 X-RateLimit-Ip-* 동시 노출
        from fastapi import APIRouter

        from whymath_backend.api._rate_limit import RateLimitedIpRead

        router = APIRouter()

        @router.get("/_test/ip-headers", dependencies=[RateLimitedIpRead])
        async def _hit() -> dict[str, bool]:
            return {"ok": True}

        app = create_app()
        app.include_router(router)
        app.dependency_overrides[get_settings] = lambda: Settings(
            jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
            coach_rate_limit_ip_read_per_minute=3,
        )
        client = TestClient(app)
        resp = client.get("/_test/ip-headers")
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Ip-Limit"] == "3"
        assert resp.headers["X-RateLimit-Ip-Remaining"] == "2"
        # rollup도 동일
        assert resp.headers["X-RateLimit-Limit"] == "3"
        # User-* 차원은 IP-only라 미세팅
        assert "X-RateLimit-User-Limit" not in resp.headers


class TestPairHelperUnit:
    """`_pair_headers` 헬퍼 — 프리픽스 조립 검증."""

    def test_canonical_prefix_keys(self) -> None:
        from whymath_backend.api._rate_limit import RateLimitResult, _pair_headers

        result = RateLimitResult(allowed=True, remaining=5, reset_seconds=30)
        headers = _pair_headers("User", 10, result)
        assert set(headers.keys()) == {
            "X-RateLimit-User-Limit",
            "X-RateLimit-User-Remaining",
            "X-RateLimit-User-Reset",
        }
        assert headers["X-RateLimit-User-Limit"] == "10"
        assert headers["X-RateLimit-User-Remaining"] == "5"
        assert headers["X-RateLimit-User-Reset"] == "30"

    def test_different_prefix(self) -> None:
        from whymath_backend.api._rate_limit import RateLimitResult, _pair_headers

        result = RateLimitResult(allowed=True, remaining=2, reset_seconds=15)
        headers = _pair_headers("Ip", 5, result)
        assert "X-RateLimit-Ip-Limit" in headers
        assert "X-RateLimit-User-Limit" not in headers

    def test_defense_with_user_limit_zero_skips_user_pair(self) -> None:
        # user_limit=0, ip_limit>0이면 Defense는 IP만 검사 — User-* 미세팅
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0, write_limit=0, ip_limit=0, ip_write_limit=5
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        resp = client.post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200
        # IP만 활성 — User-* 미세팅
        assert "X-RateLimit-User-Limit" not in resp.headers
        assert resp.headers["X-RateLimit-Ip-Limit"] == "5"


class TestTripleDimension:
    """슬라이스 20 — 3차원 한도(user+IP+device). hit_many 원자성·X-Device-Id 추출."""

    def test_hit_many_all_pass(self) -> None:
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend, Subject

        backend = InMemoryBackend()
        results = asyncio.run(
            backend.hit_many(
                [
                    Subject(kind="user", id=str(uuid.uuid4()), limit=10),
                    Subject(kind="ip", id="1.1.1.1", limit=20),
                    Subject(kind="device", id="dev-abc", limit=5),
                ],
                category="read",
                now=0.0,
            )
        )
        assert results["user"].allowed is True
        assert results["ip"].allowed is True
        assert results["device"].allowed is True
        assert results["user"].remaining == 9
        assert results["device"].remaining == 4

    def test_hit_many_atomic_device_blocks_others(self) -> None:
        # device 한도 1 도달 시, 같은 호출의 user/ip는 미증가
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend, Subject

        backend = InMemoryBackend()
        uid = str(uuid.uuid4())
        asyncio.run(
            backend.hit_many(
                [
                    Subject(kind="user", id=uid, limit=10),
                    Subject(kind="ip", id="1.1.1.1", limit=10),
                    Subject(kind="device", id="dev-abc", limit=1),
                ],
                category="read",
                now=0.0,
            )
        )
        # 두번째 호출 — device 한도 도달이라 atomic deny
        result = asyncio.run(
            backend.hit_many(
                [
                    Subject(kind="user", id=uid, limit=10),
                    Subject(kind="ip", id="1.1.1.1", limit=10),
                    Subject(kind="device", id="dev-abc", limit=1),
                ],
                category="read",
                now=0.1,
            )
        )
        assert result["device"].allowed is False
        # user/ip counter는 *미증가* — 다음 다른 device로 통과 시 user remaining=8(누적 2)
        followup = asyncio.run(
            backend.hit_many(
                [
                    Subject(kind="user", id=uid, limit=10),
                    Subject(kind="ip", id="1.1.1.1", limit=10),
                    Subject(kind="device", id="dev-xyz", limit=1),  # 다른 device
                ],
                category="read",
                now=0.2,
            )
        )
        assert followup["user"].allowed is True
        assert followup["user"].remaining == 8  # 10 - 2(첫 + 세번째 통과)

    def test_hit_many_empty_subjects(self) -> None:
        # 빈 리스트 → 빈 dict no-op
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend

        backend = InMemoryBackend()
        results = asyncio.run(backend.hit_many([], category="read", now=0.0))
        assert results == {}

    def test_redis_hit_many_atomic(self) -> None:
        # _LUA_HIT_MANY가 N개 키 원자 처리
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend, Subject

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        uid = str(uuid.uuid4())
        results = asyncio.run(
            backend.hit_many(
                [
                    Subject(kind="user", id=uid, limit=5),
                    Subject(kind="ip", id="1.1.1.1", limit=5),
                    Subject(kind="device", id="dev-1", limit=5),
                ],
                category="read",
                now=0.0,
            )
        )
        assert results["user"].allowed is True
        # 세 키 모두 ZSET에 생성됨
        from whymath_backend.api._rate_limit import RedisBackend as RB  # noqa: N817

        assert f"{RB._KEY_PREFIX}read:user:{uid}" in fake.zsets
        assert f"{RB._KEY_PREFIX}read:ip:1.1.1.1" in fake.zsets
        assert f"{RB._KEY_PREFIX}read:device:dev-1" in fake.zsets

    def test_device_id_header_extraction(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        request = MagicMock()
        request.headers = {"x-device-id": "dev-abc-123"}
        # secret 미설정 — slice 20 동작 그대로(서명 검증 생략)
        settings = _settings_override(0)
        assert asyncio.run(_client_device_id(request, settings)) == "dev-abc-123"

    def test_device_id_missing_returns_none(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        request = MagicMock()
        request.headers = {}
        assert asyncio.run(_client_device_id(request, _settings_override(0))) is None

    def test_device_id_empty_returns_none(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        request = MagicMock()
        request.headers = {"x-device-id": "  "}
        assert asyncio.run(_client_device_id(request, _settings_override(0))) is None

    def test_coach_endpoint_uses_device_limit(self) -> None:
        # coach POST가 RateLimitedTripleWrite 부착 — device 한도 1 시 X-Device-Id로 2번째 429
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0,
            write_limit=10,
            ip_limit=0,
            ip_write_limit=10,
            device_limit=0,
            device_write_limit=1,
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        # X-Device-Id 헤더 동봉
        headers = {"x-device-id": "dev-test"}
        r1 = client.post("/v1/coach", json={"student_input": "음"}, headers=headers)
        assert r1.status_code == 200
        # Device pair-header 노출
        assert r1.headers["X-RateLimit-Device-Limit"] == "1"
        assert r1.headers["X-RateLimit-Device-Remaining"] == "0"
        # 두번째 — device 한도 도달
        r2 = client.post("/v1/coach", json={"student_input": "음"}, headers=headers)
        assert r2.status_code == 429
        assert r2.headers["X-RateLimit-Limit"] == "1"  # blocker=device

    def test_coach_endpoint_skips_device_when_header_absent(self) -> None:
        # X-Device-Id 헤더 없으면 device 차원 검사 비활성 — user+IP만
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0,
            write_limit=10,
            ip_limit=0,
            ip_write_limit=10,
            device_limit=0,
            device_write_limit=1,
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        # device 한도 1이지만 헤더 없음 → 5번 모두 통과(device 검사 안 함)
        for _ in range(5):
            resp = client.post("/v1/coach", json={"student_input": "음"})
            assert resp.status_code == 200
            assert "X-RateLimit-Device-Limit" not in resp.headers


class TestHitManyEdgeCases:
    """잔여 분기 커버 — hit_many prune·Redis 빈 subjects."""

    def test_inmemory_hit_many_prunes_expired(self) -> None:
        # 60초+ 후 hit_many — 옛 항목 prune(while bucket[0]<cutoff: popleft)
        import asyncio

        from whymath_backend.api._rate_limit import InMemoryBackend, Subject

        backend = InMemoryBackend()
        uid = str(uuid.uuid4())
        asyncio.run(
            backend.hit_many([Subject(kind="user", id=uid, limit=1)], category="read", now=0.0)
        )
        # 같은 윈도우 — 거부
        denied = asyncio.run(
            backend.hit_many([Subject(kind="user", id=uid, limit=1)], category="read", now=0.5)
        )
        assert denied["user"].allowed is False
        # 60초+ — prune 분기 발화
        passed = asyncio.run(
            backend.hit_many([Subject(kind="user", id=uid, limit=1)], category="read", now=61.0)
        )
        assert passed["user"].allowed is True

    def test_redis_hit_many_empty_subjects_noop(self) -> None:
        # Redis backend도 빈 subjects 시 no-op 반환(early return)
        import asyncio

        from whymath_backend.api._rate_limit import RedisBackend

        fake = _FakeRedisClient()
        backend = RedisBackend(client=fake)
        results = asyncio.run(backend.hit_many([], category="read", now=0.0))
        assert results == {}
        assert fake.evalsha_calls == []  # Redis 호출 자체가 없음


class TestDeviceHmacSignature:
    """슬라이스 21 — HMAC X-Device-Sig 검증."""

    def _sig(self, secret: str, device_id: str) -> str:
        from whymath_backend.api._rate_limit import _expected_device_signature

        return _expected_device_signature(secret, device_id)

    def test_valid_signature_accepts_device_id(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        secret = "test-device-secret-123"
        device_id = "dev-abc-123"
        valid_sig = self._sig(secret, device_id)
        request = MagicMock()
        request.headers = {"x-device-id": device_id, "x-device-sig": valid_sig}
        settings = _settings_override(0, device_hmac_secret=secret)
        assert asyncio.run(_client_device_id(request, settings)) == device_id

    def test_invalid_signature_returns_none(self) -> None:
        # 서명 불일치 → fail-safe(device 차원 검사 비활성)
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        secret = "test-device-secret-123"
        request = MagicMock()
        request.headers = {
            "x-device-id": "dev-abc-123",
            "x-device-sig": "0" * 64,  # 형식 맞으나 잘못된 서명
        }
        settings = _settings_override(0, device_hmac_secret=secret)
        assert asyncio.run(_client_device_id(request, settings)) is None

    def test_missing_signature_when_secret_set_returns_none(self) -> None:
        # secret 설정·X-Device-Sig 헤더 누락 → None(fail-safe)
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        request = MagicMock()
        request.headers = {"x-device-id": "dev-abc-123"}
        settings = _settings_override(0, device_hmac_secret="some-secret")
        assert asyncio.run(_client_device_id(request, settings)) is None

    def test_empty_secret_skips_verification(self) -> None:
        # secret 비어있으면 서명 검증 생략(slice 20 backward compat)
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        request = MagicMock()
        request.headers = {"x-device-id": "dev-abc-123"}  # X-Device-Sig 없음
        settings = _settings_override(0, device_hmac_secret="")
        assert asyncio.run(_client_device_id(request, settings)) == "dev-abc-123"

    def test_case_insensitive_signature(self) -> None:
        # 클라이언트가 대문자 hex로 보내도 일치 검증(.lower() 정규화)
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        secret = "test-device-secret-123"
        device_id = "dev-abc"
        valid_sig = self._sig(secret, device_id).upper()  # 대문자
        request = MagicMock()
        request.headers = {"x-device-id": device_id, "x-device-sig": valid_sig}
        settings = _settings_override(0, device_hmac_secret=secret)
        assert asyncio.run(_client_device_id(request, settings)) == device_id

    def test_signature_for_different_device_id_rejected(self) -> None:
        # 다른 device_id의 서명을 보내면 거부(서명·ID 페어 무결성)
        import asyncio
        from unittest.mock import MagicMock

        from whymath_backend.api._rate_limit import _client_device_id

        secret = "test-secret"
        sig_for_other = self._sig(secret, "other-device")
        request = MagicMock()
        request.headers = {"x-device-id": "this-device", "x-device-sig": sig_for_other}
        settings = _settings_override(0, device_hmac_secret=secret)
        assert asyncio.run(_client_device_id(request, settings)) is None

    def test_expected_signature_deterministic_and_64char(self) -> None:
        from whymath_backend.api._rate_limit import _expected_device_signature

        s1 = _expected_device_signature("secret", "device-1")
        s2 = _expected_device_signature("secret", "device-1")
        assert s1 == s2
        assert len(s1) == 64  # SHA-256 hex
        # 다른 입력 → 다른 서명
        assert s1 != _expected_device_signature("secret", "device-2")
        assert s1 != _expected_device_signature("other-secret", "device-1")

    def test_coach_endpoint_with_valid_sig_enforces_device_limit(self) -> None:
        # secret 설정 + 유효 서명 → device 한도 정상 발화
        from whymath_backend.api._rate_limit import _expected_device_signature

        secret = "endpoint-test-secret"
        device_id = "dev-1"
        valid_sig = _expected_device_signature(secret, device_id)

        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0,
            write_limit=10,
            ip_limit=0,
            ip_write_limit=10,
            device_limit=0,
            device_write_limit=1,
            device_hmac_secret=secret,
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        headers = {"x-device-id": device_id, "x-device-sig": valid_sig}
        r1 = client.post("/v1/coach", json={"student_input": "음"}, headers=headers)
        assert r1.status_code == 200
        assert r1.headers["X-RateLimit-Device-Limit"] == "1"
        r2 = client.post("/v1/coach", json={"student_input": "음"}, headers=headers)
        assert r2.status_code == 429

    def test_coach_endpoint_with_invalid_sig_skips_device(self) -> None:
        # 잘못된 서명 → device 차원 비활성·user+IP만 적용
        secret = "endpoint-test-secret"
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = lambda: _settings_override(
            limit=0,
            write_limit=10,
            ip_limit=0,
            ip_write_limit=10,
            device_limit=0,
            device_write_limit=1,
            device_hmac_secret=secret,
        )

        async def _sess() -> AsyncIterator[_FakeSession]:
            yield _FakeSession()

        app.dependency_overrides[get_session] = _sess
        client = TestClient(app)
        # 잘못된 서명을 매 호출 다른 device_id로 (spoofing 시도)
        for i in range(5):
            headers = {"x-device-id": f"dev-{i}", "x-device-sig": "0" * 64}
            resp = client.post("/v1/coach", json={"student_input": "음"}, headers=headers)
            assert resp.status_code == 200
            # device 차원 미활성 → Device-* 헤더 없음
            assert "X-RateLimit-Device-Limit" not in resp.headers


class TestPrerequisiteCoachingHelper:
    """선수 복습 코칭 헬퍼(`_prerequisite_coaching_for`) 단위 — coach 세션/턴 전용.

    L2 fetch(`recommend_prerequisite_gaps`)·개념 해석(`get_primary_concept_id`)·L4 decide
    (`recommend_prerequisite_coaching`)를 monkeypatch로 고정해 *오케스트레이션 분기*만 검증한다
    (L2/L4 좌석 자체는 test_prerequisite_recommendation·test_prerequisite_coaching이 검증).
    problem_id None→None·concept None→None·gaps 없음→None·gaps 있음→trigger.
    """

    _PID = uuid.uuid4()

    async def test_problem_id_none_returns_none(self) -> None:
        # problem_id 없음 → 문제 맥락 없음 → 개념/선수 조회 자체를 건너뜀(None).
        result = await coach._prerequisite_coaching_for(
            cast(AsyncSession, _FakeSession()), _UID, None
        )
        assert result is None

    async def test_concept_none_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 문항-개념 미매핑(get_primary_concept_id None) → 선수 traversal 불가 → None.
        async def _no_concept(session: Any, problem_id: Any) -> uuid.UUID | None:
            return None

        monkeypatch.setattr("whymath_backend.api.coach.get_primary_concept_id", _no_concept)
        result = await coach._prerequisite_coaching_for(
            cast(AsyncSession, _FakeSession()), _UID, self._PID
        )
        assert result is None

    async def test_no_gaps_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 개념은 해석되나 막힌 선수 없음(gaps=[]) → L4 decide가 None.
        cid = uuid.uuid4()

        async def _concept(session: Any, problem_id: Any) -> uuid.UUID | None:
            return cid

        async def _gaps(*args: Any, **kwargs: Any) -> list[Any]:
            return []

        monkeypatch.setattr("whymath_backend.api.coach.get_primary_concept_id", _concept)
        monkeypatch.setattr("whymath_backend.api.coach.recommend_prerequisite_gaps", _gaps)
        result = await coach._prerequisite_coaching_for(
            cast(AsyncSession, _FakeSession()), _UID, self._PID
        )
        assert result is None

    async def test_gaps_present_returns_trigger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 막힌 선수 있음 → L4 decide가 prerequisite_review trigger를 돌려준다(선수 이름 포함).
        from whymath_backend.l2.prerequisite_recommendation import PrerequisiteGap

        cid = uuid.uuid4()
        gap = PrerequisiteGap(
            concept_id=uuid.uuid4(),
            concept_code="UC.test.pre",
            concept_name="일차함수",
            bkt_mastery=0.2,
            weakness=0.2,
            agreement="insufficient",
            name_ko="일차함수",
        )

        async def _concept(session: Any, problem_id: Any) -> uuid.UUID | None:
            return cid

        async def _gaps(*args: Any, **kwargs: Any) -> list[PrerequisiteGap]:
            return [gap]

        monkeypatch.setattr("whymath_backend.api.coach.get_primary_concept_id", _concept)
        monkeypatch.setattr("whymath_backend.api.coach.recommend_prerequisite_gaps", _gaps)
        result = await coach._prerequisite_coaching_for(
            cast(AsyncSession, _FakeSession()), _UID, self._PID
        )
        assert result is not None
        assert result.focus == "prerequisite_review"
        assert "일차함수" in result.prompt
        # redaction·톤 — 본문 부재·금기 표현 부재(재사용 L4 함수 보장).
        for forbidden in ("빨리", "정답", "틀렸"):
            assert forbidden not in result.prompt


class TestPrerequisiteCoachingField:
    """`prerequisite_coaching` 필드 직렬화 — CoachResponse 기본 None·trigger 직렬화·핸들러 배선."""

    def test_field_present_default_none(self) -> None:
        # CoachResponse 스키마에 필드 존재·기본 None(추가 신호·미설정 시 null).
        assert "prerequisite_coaching" in coach.CoachResponse.model_fields
        field = coach.CoachResponse.model_fields["prerequisite_coaching"]
        assert field.default is None

    def test_stateless_coach_always_none(self) -> None:
        # stateless /v1/coach는 DB/user 미사용 → prerequisite_coaching 항상 None(계약 보존).
        resp = _client().post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["prerequisite_coaching"] is None

    def test_session_create_wires_prereq_trigger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 세션 생성 핸들러가 _prerequisite_coaching_for 결과를 응답에 싣는다(배선 검증).
        from whymath_backend.l4.metacognitive_trigger import CoachingTrigger
        from whymath_backend.l4.socratic.categories import SocraticCategory

        trigger = CoachingTrigger(
            focus="prerequisite_review",
            rationale="선수 '일차함수' 미숙달",
            prompt="먼저 '일차함수'부터 떠올려 볼까?",
            socratic_category=SocraticCategory.CLARIFICATION,
        )

        async def _fake(
            session: Any, user_id: Any, problem_id: Any, **kwargs: Any
        ) -> CoachingTrigger | None:
            return trigger

        monkeypatch.setattr("whymath_backend.api.coach._prerequisite_coaching_for", _fake)
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "problem_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 201, resp.text
        pc = resp.json()["prerequisite_coaching"]
        assert pc is not None
        assert pc["focus"] == "prerequisite_review"
        assert "일차함수" in pc["prompt"]

    def test_session_create_none_when_no_blocked_prereq(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 막힌 선수 없음(헬퍼 None) → 응답 prerequisite_coaching None.
        async def _fake(session: Any, user_id: Any, problem_id: Any, **kwargs: Any) -> Any:
            return None

        monkeypatch.setattr("whymath_backend.api.coach._prerequisite_coaching_for", _fake)
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "problem_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["prerequisite_coaching"] is None


# ── WH-1 지표 ① 적재: _log_verify_event 단위테스트 (FakeSession add 캡처) ──────────
class _CaptureSession:
    """`add`된 ORM 인스턴스를 캡처하는 최소 가짜 세션(검증은 실 함수가 결정론으로 수행).

    S3-16: `_log_response_latency_event`가 `execute(select(...)).scalars().first()`으로
    직전 학생 턴 spoken_at을 조회한다(`l2.ability_tracking.get_current_theta`와 동일 관례 —
    `.scalar_one_or_none()`은 repo 전역 fake session(`test_coach_semantic.py` 등)이 지원하지
    않아 초판은 회귀를 냈다·2026-07-30 정정) — `execute_result`(선택)에 `.scalars().first()`를
    가진 스텁을 주입할 수 있게 확장(기존 `add`만 쓰는 테스트는 영향 없음·하위호환).
    """

    def __init__(self, execute_result: Any = None) -> None:
        self.added: list[Any] = []
        self._execute_result = execute_result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, _stmt: Any) -> Any:
        return self._execute_result


class _ScalarsFirst:
    """`execute()` 결과 스텁 — `.scalars().first()`만 지원(S3-16 응답 지연 조회용)."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "_ScalarsFirst":
        return self

    def first(self) -> Any:
        return self._value


class TestLogVerifyEvent:
    """`_log_verify_event` — 검산결과 attempt_event 적재 단위(스테이트풀 coach 전용).

    검증기(`arithmetic_validator`)는 결정론·순수라 패치하지 않고 실제 호출한다 — 거짓 수치관계
    포함/미포함 풀이로 passed False/True가 갈리는지·빈 풀이면 적재 0인지·event_type이 검산결과
    인지를 add 캡처로 확인한다. 반환값(반박 증거 결선용·None/True/False)도 함께 핀한다.
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()

    async def test_empty_solution_no_event(self) -> None:
        """student_solution이 None이면 적재 0(early return·false-pass 방지)·반환 None(신호 없음)."""
        from whymath_backend.api.coach import _log_verify_event

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution=None,
        )
        assert sess.added == []
        assert result is None  # 풀이 제출 턴 아님 → 검산 신호 없음(반박 결선이 건너뜀).

    async def test_blank_solution_no_event(self) -> None:
        """공백만 있는 풀이도 적재 0(strip 후 빈 문자열)·반환 None."""
        from whymath_backend.api.coach import _log_verify_event

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="   ",
        )
        assert sess.added == []
        assert result is None

    async def test_false_relation_passed_false(self) -> None:
        """거짓 수치관계(2+3=6) 포함 → passed False·event_type 검산결과·error_kind·반환 False."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="계산하면 2+3=6 이다",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.검산결과
        assert event.event_data["passed"] is False
        assert event.event_data["error_kind"] is not None
        assert event.user_id == self._UID
        assert event.problem_id == self._PID
        assert result is False  # 거짓관계 적발 → 반박 안 함(반박 결선이 건너뜀).

    async def test_true_relation_passed_true(self) -> None:
        """거짓관계 없는 풀이 → passed True·error_kind None·반환 True(반박 결선 구동)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="2+3=5 이므로 답은 5입니다",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.검산결과
        assert event.event_data["passed"] is True
        assert event.event_data["error_kind"] is None
        assert result is True  # clean 검증 → 반박 결선이 −1 적재 가능.

    async def test_attempt_id_passthrough(self) -> None:
        """attempt_id가 있으면 이벤트에 그대로 실린다."""
        from whymath_backend.api.coach import _log_verify_event

        aid = uuid.uuid4()
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=None,
            attempt_id=aid,
            student_solution="2+3=5",
        )
        assert len(sess.added) == 1
        assert sess.added[0].attempt_id == aid
        assert sess.added[0].problem_id is None


# S4-19 — 검산결과 이벤트에 병기 적재되는 verify_solution 3상태 6키(전건 additive optional).
_STEP_COUNT_KEYS = (
    "n_correct",
    "n_incorrect",
    "n_unverifiable",
    "unverified_ratio",
    "first_incorrect_index",
    "ocr_gated",
)


class TestLogVerifyEventStepCounts:
    """S4-19 — `_log_verify_event`의 3상태 카운트 additive 병기(재계산 0·binary passed 불변).

    verification(게이트 *이전* verify_solution 결과)이 주어지면 6키를 값으로, 없으면 전부
    None으로 적재한다(구판 이벤트와 같은 NULL 회계 — 정직). 비제출 턴 무적재 가드는
    verification이 있어도 불변이다(false-pass 방지가 우선). verify_solution은 결정론·순수라
    패치 없이 실제 호출로 픽스처를 만든다(TestLogVerifyEvent 관례 동형).
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()

    async def test_no_verification_records_six_none_keys(self) -> None:
        """단계 미제출(검증 미실행) 제출 턴 → 6키가 *존재하되 전부 None*·binary 축 불변."""
        from whymath_backend.api.coach import _log_verify_event

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="2+3=5 이므로 답은 5입니다",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        for key in _STEP_COUNT_KEYS:
            assert key in event.event_data  # 신판 payload에는 키가 항상 존재(계약 model_dump)
            assert event.event_data[key] is None  # 값은 None(검증 미실행 — 0으로 위장 금지)
        assert event.event_data["passed"] is True  # 기존 binary 재검산 축 불변(이중 회계)
        assert result is True

    async def test_verification_carried_records_counts(self) -> None:
        """verification 운반 → 카운트·비율·인덱스 그대로 적재(값 운반만·재계산 0)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution

        verification = verify_solution(["2*x + 4", "2*x + 5"])  # incorrect 전이 1회
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="이렇게 정리했다",
            verification=verification,
            verification_ocr_gated=False,
        )
        assert len(sess.added) == 1
        data = sess.added[0].event_data
        assert data["n_correct"] == 0
        assert data["n_incorrect"] == 1
        assert data["n_unverifiable"] == 0
        assert data["unverified_ratio"] == 0.0
        assert data["first_incorrect_index"] == 0
        assert data["ocr_gated"] is False
        # steps(reason 텍스트)는 절대 싣지 않는다 — 비식별 카운트만(미성년 PII 규약).
        assert "steps" not in data

    async def test_zero_transition_verification_records_zero_not_none(self) -> None:
        """전이 0회 제출(빈 verification)도 카운트 0으로 기록 — None(미지정)과 구분(S3-07)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution

        verification = verify_solution([])  # 전이 0 — 정직한 빈 집계(카운트 전부 0)
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="한 줄 풀이",
            verification=verification,
            verification_ocr_gated=False,
        )
        data = sess.added[0].event_data
        assert data["n_correct"] == 0  # None 아님 — 실측 0
        assert data["n_incorrect"] == 0
        assert data["n_unverifiable"] == 0
        assert data["unverified_ratio"] == 0.0
        assert data["first_incorrect_index"] is None  # incorrect 없음(n_incorrect==0로 구분)

    async def test_ocr_gated_true_carried(self) -> None:
        """ocr_gated=True(저신뢰 OCR 보류) 운반 → event_data에 그대로 적재."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution

        verification = verify_solution(["2*x + 4", "2*x + 5"])
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="이렇게 정리했다",
            verification=verification,
            verification_ocr_gated=True,
        )
        assert sess.added[0].event_data["ocr_gated"] is True

    async def test_unverifiable_by_reason_carried_with_string_keys(self) -> None:
        """MATH-03 — 사유 분포가 *문자열 키*로 병기 적재된다(값 운반만·서로 다른 카운터).

        parse_error 유발 전이와 비대수 전이가 이벤트에서 다른 키로 도착해야 한다(⑤ 변별력의
        적재 축 — 같은 키에 합산되면 red). JSONB 세계라 enum이 아닌 평문 키를 고정한다.
        """
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution
        from whymath_backend.schema.enums import StepType

        verification = verify_solution(
            ["2+3", "5", "2 +* 3", "5"],
            [StepType.계산, None, StepType.조건해석],
        )
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="이렇게 정리했다",
            verification=verification,
            verification_ocr_gated=False,
        )
        data = sess.added[0].event_data
        assert data["unverifiable_by_reason"] == {"parse_error": 1, "non_algebraic_step": 1}
        # 자유문 reason·steps는 여전히 미적재(비식별 규약 불변 — 코드·정수만).
        assert "steps" not in data

    async def test_unverifiable_by_reason_none_without_verification(self) -> None:
        """단계 미제출(검증 미실행)이면 사유 분포도 None — S4-19 NULL 회계 동형."""
        from whymath_backend.api.coach import _log_verify_event

        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="2+3=5 이므로 답은 5입니다",
        )
        assert sess.added[0].event_data["unverifiable_by_reason"] is None

    async def test_unverifiable_by_reason_empty_dict_when_no_holds(self) -> None:
        """검증 실행·보류 0이면 {}(빈 dict) — None(미실행)과 구분(분모 없는 0 금지의 적재 축)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution

        verification = verify_solution(["2*(x+1)", "2*x+2"])  # correct 전이 1회·보류 0
        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution="이렇게 정리했다",
            verification=verification,
            verification_ocr_gated=False,
        )
        assert sess.added[0].event_data["unverifiable_by_reason"] == {}

    async def test_distribution_log_has_denominator(self, caplog: pytest.LogCaptureFixture) -> None:
        """MATH-03 ④ — 분포 INFO 로그가 '전이 N건 중 보류 M건' 분모 동반 형식으로 남는다.

        리포트 좌석 실측: verify 집계 기존 리포트는 전부 harness/**(타 세션 claim)라 응답 로그
        대체(coach client_state_mismatch logger.info 선례) — 이 테스트가 그 좌석을 동결한다.
        """
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution
        from whymath_backend.schema.enums import StepType

        verification = verify_solution(
            ["2+3", "5", "2 +* 3", "5"],
            [StepType.계산, None, StepType.조건해석],
        )
        sess = _CaptureSession()
        with caplog.at_level(logging.INFO, logger="whymath_backend.api.coach"):
            await _log_verify_event(
                cast(AsyncSession, sess),
                user_id=self._UID,
                problem_id=self._PID,
                attempt_id=None,
                student_solution="이렇게 정리했다",
                verification=verification,
                verification_ocr_gated=False,
            )
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "전이 3건 중 보류 2건" in joined  # 분모 없는 0 금지 — N·M 병기 형식
        assert "parse_error" in joined
        assert "non_algebraic_step" in joined

    async def test_empty_solution_no_event_even_with_verification(self) -> None:
        """비제출 턴 무적재 가드 불변 — verification이 있어도 적재 0(false-pass 방지 우선)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.l3.verify_solution import verify_solution

        sess = _CaptureSession()
        result = await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_solution=None,
            verification=verify_solution(["2*x + 4", "2*(x + 2)"]),
            verification_ocr_gated=False,
        )
        assert sess.added == []
        assert result is None


class TestStepVerificationCarryPreGate:
    """S4-19 — `_build_response_payload`의 carry는 노출 게이트 *이전* 값이다(변별력 테스트).

    노출 게이트(coach.py `_THETA_SURFACED_FOCI`)는 전단계-correct 제출·ocr_gated 보류 케이스의
    `solution_coaching`을 None으로 걸러낸다 — 게이트 *이후* 값으로 carry를 구현하면 이 두
    케이스에서 carry가 비어(red) 불합격 편향 회계가 된다. 마지막 원소=solution_coaching
    불변식(S3-32 언패킹 전제)도 함께 고정한다.
    """

    def test_all_correct_submission_still_carries_counts(self) -> None:
        """전단계-correct 제출(게이트 탈락·sol None)에서도 carry에 카운트가 실린다."""
        body = coach.CoachRequest(
            student_input="다 풀었어요",
            student_solution="2*x + 4",  # clean(거짓 수치관계 없음) → arithmetic_error False
            solution_steps=["2*x + 4", "2*(x + 2)"],  # 전이 1회·correct(동치)
        )
        *_head, carry, sol = coach._build_response_payload(body)
        assert sol is None  # 전제: bkt/θ 없음 → focus=diagnose·계산오류 없음 → 노출 게이트 탈락
        assert carry.verification is not None  # 게이트 이후 값이었다면 여기서 red
        assert carry.verification.n_correct == 1
        assert carry.verification.n_incorrect == 0
        assert carry.ocr_gated is False

    def test_ocr_gated_submission_carries_flag(self) -> None:
        """ocr_gated 보류 제출(게이트 탈락)에서도 carry에 보류 플래그·카운트가 실린다."""
        body = coach.CoachRequest(
            student_input="정리했어요",
            student_solution="x를 정리했다",  # clean 텍스트(게이팅과 무관)
            solution_steps=["2*x + 4", "2*x + 5"],  # incorrect 전이
            ocr_confidence=0.5,  # <0.8 → step 신호 보류(verification_ocr_gated=True)
        )
        *_head, carry, sol = coach._build_response_payload(body)
        assert sol is None  # 보류로 arithmetic_error False → 게이트 탈락(전제)
        assert carry.ocr_gated is True
        assert carry.verification is not None
        assert carry.verification.n_incorrect == 1

    def test_no_steps_carry_verification_is_none(self) -> None:
        """단계 미제출이면 carry.verification=None — writer가 6키 None으로 정직 적재할 재료."""
        body = coach.CoachRequest(student_input="음", student_solution="2+3=5")
        *_head, carry, _sol = coach._build_response_payload(body)
        assert carry.verification is None

    def test_seven_tuple_last_element_is_solution_coaching(self) -> None:
        """반환은 7튜플·carry는 인덱스 5·**마지막 원소=solution_coaching 불변식 보존**."""
        body = coach.CoachRequest(student_input="음", student_solution="2+3=6")  # 계산오류 노출
        result = coach._build_response_payload(body)
        assert isinstance(result, tuple) and len(result) == 7
        assert isinstance(result[5], coach._StepVerificationCarry)
        assert isinstance(result[-1], coach.SolutionCoaching)  # 게이트 통과(arithmetic_error)


class TestStepCountWiring:
    """S4-19 — 두 핸들러(create_session·append_turns)가 게이트 이전 carry를 적재에 결선.

    엔드포인트 레벨 변별력: 응답 `solution_coaching`은 None(노출 게이트 탈락)인데도 검산결과
    이벤트에는 카운트가 적재된다 — 핸들러가 carry 대신 solution_coaching을 운반하면 red.
    """

    def _verify_events(self, captured: Any) -> list[Any]:
        from whymath_backend.db.models.activity import AttemptEvent as AttemptEventORM
        from whymath_backend.schema.enums import EventType

        return [
            o
            for o in captured.added
            if isinstance(o, AttemptEventORM) and o.event_type is EventType.검산결과
        ]

    def test_session_create_persists_pre_gate_counts(self) -> None:
        """세션 생성: 전단계-correct 제출 → 응답 코칭 None·이벤트 카운트 적재(게이트 이전)."""
        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이렇게 풀었어",
                "student_solution": "2*x + 4",
                "solution_steps": ["2*x + 4", "2*(x + 2)"],
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["solution_coaching"] is None  # 노출 게이트 탈락(전제 확인)
        [verify] = self._verify_events(captured)
        assert verify.event_data["n_correct"] == 1
        assert verify.event_data["n_incorrect"] == 0
        assert verify.event_data["n_unverifiable"] == 0
        assert verify.event_data["ocr_gated"] is False
        assert verify.event_data["passed"] is True  # binary 축 불변(이중 회계)

    def test_append_turn_persists_pre_gate_counts(self) -> None:
        """멀티턴 append: create와 동형 결선 — 후속 턴 제출도 카운트 적재."""
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema

        did = uuid.uuid4()
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did, user_id=_UID, total_turns=2, student_turns=1, assistant_turns=1
            )
        )
        client, captured = _session_client(preload={(DialogueORM, did): dialogue})
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={
                "student_input": "다음 단계로 정리했어",
                "student_solution": "2*x + 4",
                "solution_steps": ["2*x + 4", "2*(x + 2)"],
            },
        )
        assert resp.status_code == 201, resp.text
        [verify] = self._verify_events(captured)
        assert verify.event_data["n_correct"] == 1
        assert verify.event_data["n_incorrect"] == 0
        assert verify.event_data["ocr_gated"] is False


class TestLogHintEvent:
    """`_log_hint_event` — 힌트제공 attempt_event 적재 단위(스테이트풀 coach 전용·지표 ⑤).

    `hint_level`은 핸들러가 이미 보유한 decision.hint_level을 그대로 받는다(재계산 0). None이면
    적재 0(early return·날조 회피)·정수면 event_type=힌트제공·event_data={hint_level}로 1행
    적재되는지를 add 캡처로 확인한다(verify 단위 패턴 미러).
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()

    async def test_none_hint_level_no_event(self) -> None:
        """hint_level이 None이면 적재 0(early return·신호 없는 행 미생성)."""
        from whymath_backend.api.coach import _log_hint_event

        sess = _CaptureSession()
        await _log_hint_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            hint_level=None,
        )
        assert sess.added == []

    async def test_int_hint_level_logs_event(self) -> None:
        """hint_level 정수 → event_type 힌트제공·event_data hint_level·user/problem 실림."""
        from whymath_backend.api.coach import _log_hint_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_hint_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            hint_level=3,
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.힌트제공
        # S3-03: mode/persona 미지정 → 계약이 None으로 정규화(mode-agnostic·기존 동작 불변).
        assert event.event_data == {
            "hint_level": 3,
            "mode": None,
            "persona": None,
            # PED-04 D2: 불일치 태그 — 기본 False(클라 상태 미제출·서버 파생과 일치).
            "client_state_mismatch": False,
        }
        assert event.user_id == self._UID
        assert event.problem_id == self._PID

    async def test_attempt_id_passthrough(self) -> None:
        """attempt_id가 있으면 이벤트에 그대로 실린다(problem_id None 허용)."""
        from whymath_backend.api.coach import _log_hint_event

        aid = uuid.uuid4()
        sess = _CaptureSession()
        await _log_hint_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=None,
            attempt_id=aid,
            hint_level=1,
        )
        assert len(sess.added) == 1
        assert sess.added[0].attempt_id == aid
        assert sess.added[0].problem_id is None
        # S3-03: mode/persona 미지정 → None 정규화(기존 동작 불변).
        assert sess.added[0].event_data == {
            "hint_level": 1,
            "mode": None,
            "persona": None,
            "client_state_mismatch": False,
        }


# ── S3-16 소생: _log_demand_event 단위테스트 (답 요구 신호 → 힌트요청 적재) ────────────
class TestLogDemandEvent:
    """`_log_demand_event` — 답 요구 발화만 힌트요청 attempt_event로 적재(날조 회피).

    `is_answer_demand`(재계산 아님·`decide_hint_level` 2번 규칙과 동일 상수)가 신호를 판정한다.
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()
    _NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    async def test_no_demand_signal_no_event(self) -> None:
        """답 요구 토큰이 없으면 적재 0(신호 없는 행 미생성)."""
        from whymath_backend.api.coach import _log_demand_event

        sess = _CaptureSession()
        await _log_demand_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_input="이렇게 풀면 될까요?",
            event_at=self._NOW,
        )
        assert sess.added == []

    async def test_demand_token_logs_event(self) -> None:
        """답 요구 토큰("답 좀 알려줘") → event_type 힌트요청·event_data mode/persona만."""
        from whymath_backend.api.coach import _log_demand_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_demand_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_input="답 좀 알려줘",
            event_at=self._NOW,
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.힌트요청
        assert event.event_data == {"mode": None, "persona": None}
        assert event.user_id == self._UID
        assert event.problem_id == self._PID
        assert event.event_at == self._NOW

    async def test_demand_event_carries_mode_persona(self) -> None:
        """mode/persona 주입 → event_data에 보존(⑫ mode-scoped 집계 데이터)."""
        from whymath_backend.api.coach import _log_demand_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_demand_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            student_input="그냥 답 알려줘",
            event_at=self._NOW,
            mode="suneung",
            persona="A_일반고고3",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.힌트요청
        assert event.event_data == {"mode": "suneung", "persona": "A_일반고고3"}


# ── S3-16 소생: _log_stuck_event 단위테스트 (5회+ 막힘 임계 → 막힘 적재) ──────────────
class TestLogStuckEvent:
    """`_log_stuck_event` — turn_count≥5(임계)일 때만 막힘 attempt_event로 적재(날조 회피).

    `is_stuck_turn_count`(재계산 아님·`decide_hint_level` 1번 규칙과 동일 임계)가 신호를 판정한다.
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()
    _NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)

    async def test_below_threshold_no_event(self) -> None:
        """turn_count<5 → 적재 0(임계 미도달)."""
        from whymath_backend.api.coach import _log_stuck_event

        sess = _CaptureSession()
        await _log_stuck_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            turn_count=4,
            event_at=self._NOW,
        )
        assert sess.added == []

    async def test_threshold_reached_logs_event(self) -> None:
        """turn_count=5(임계) → event_type 막힘·event_data.turn_count=5(재계산 아님)."""
        from whymath_backend.api.coach import _log_stuck_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_stuck_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            turn_count=5,
            event_at=self._NOW,
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.막힘
        assert event.event_data == {"turn_count": 5, "mode": None, "persona": None}
        assert event.user_id == self._UID
        assert event.problem_id == self._PID

    async def test_above_threshold_carries_actual_turn_count(self) -> None:
        """임계 초과(turn_count=9)도 실측값 그대로 싣는다(재계산 아님)."""
        from whymath_backend.api.coach import _log_stuck_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_stuck_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            turn_count=9,
            event_at=self._NOW,
            mode="suneung",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.막힘
        assert event.event_data == {"turn_count": 9, "mode": "suneung", "persona": None}


# ── S3-16 소생: _log_response_latency_event 단위테스트 (서버 기준 응답 지연 → 답입력 적재) ──
class TestLogResponseLatencyEvent:
    """`_log_response_latency_event` — 직전 학생 턴 대비 서버 지연을 답입력 이벤트로 적재.

    직전 학생 턴이 없으면(기준선 부재) 적재 0(날조 회피) — 이론상 append_turns는 항상 직전
    학생 턴이 있어야 하지만 방어적으로 검증한다.
    """

    _UID = uuid.uuid4()
    _PID = uuid.uuid4()
    _DID = uuid.uuid4()
    _NOW = datetime(2026, 7, 30, 12, 0, 5, tzinfo=timezone.utc)

    async def test_no_prior_student_turn_no_event(self) -> None:
        """기준선(직전 학생 턴) 없음 → 적재 0(날조 회피)."""
        from whymath_backend.api.coach import _log_response_latency_event

        sess = _CaptureSession(execute_result=_ScalarsFirst(None))
        await _log_response_latency_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            dialogue_id=self._DID,
            now=self._NOW,
            student_order=3,
        )
        assert sess.added == []

    async def test_prior_turn_logs_positive_latency(self) -> None:
        """직전 학생 턴 spoken_at이 있으면 그 차이(ms)를 답입력 이벤트로 적재."""
        from whymath_backend.api.coach import _log_response_latency_event
        from whymath_backend.schema.enums import EventType

        prev = datetime(2026, 7, 30, 12, 0, 2, tzinfo=timezone.utc)  # NOW보다 3초 이전.
        sess = _CaptureSession(execute_result=_ScalarsFirst(prev))
        await _log_response_latency_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            dialogue_id=self._DID,
            now=self._NOW,
            student_order=3,
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.답입력
        assert event.event_data == {"server_latency_ms": 3000, "mode": None, "persona": None}
        assert event.event_at == self._NOW

    async def test_mode_persona_carried(self) -> None:
        """mode/persona 주입 → event_data에 보존(형제 writer와 동형)."""
        from whymath_backend.api.coach import _log_response_latency_event
        from whymath_backend.schema.enums import EventType

        prev = datetime(2026, 7, 30, 12, 0, 4, tzinfo=timezone.utc)
        sess = _CaptureSession(execute_result=_ScalarsFirst(prev))
        await _log_response_latency_event(
            cast(AsyncSession, sess),
            user_id=self._UID,
            problem_id=self._PID,
            attempt_id=None,
            dialogue_id=self._DID,
            now=self._NOW,
            student_order=3,
            mode="suneung",
            persona="A_일반고고3",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.답입력
        assert event.event_data == {
            "server_latency_ms": 1000,
            "mode": "suneung",
            "persona": "A_일반고고3",
        }


# ── S3-03 수능 MVP: mode 태깅(요청 → 검산/힌트 event_data) 단위·결선 테스트 ─────────
class TestSuneungModeTagging:
    """S3-03 — 코치 세션의 `mode`/`persona`가 검산/힌트 attempt_event.event_data에 실린다.

    수능 세션을 측정 계층에서 식별 가능하게 하는 결선(수능 세션 → mode-scoped 측정). 두 층에서
    검증한다: ① `_log_*_event` 단위(mode/persona 인자 → event_data 보존)·② 엔드포인트 결선
    (SessionCreateRequest.mode/persona → 실제 적재 이벤트 태깅). mode=None이면 event_data.mode가
    None으로 정규화(mode-agnostic·기존 동작 완전 불변·회귀 0)임을 함께 핀한다.
    """

    _UID2 = uuid.uuid4()
    _PID2 = uuid.uuid4()

    async def test_verify_event_carries_mode_persona(self) -> None:
        """`_log_verify_event` mode/persona 주입 → event_data 보존(수능 검산결과 식별)."""
        from whymath_backend.api.coach import _log_verify_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_verify_event(
            cast(AsyncSession, sess),
            user_id=self._UID2,
            problem_id=self._PID2,
            attempt_id=None,
            student_solution="계산하면 2+3=6 이다",
            mode="suneung",
            persona="A_일반고고3",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.검산결과
        assert event.event_data["mode"] == "suneung"
        assert event.event_data["persona"] == "A_일반고고3"

    async def test_hint_event_carries_mode(self) -> None:
        """`_log_hint_event`에 mode 주입 → event_data에 실림(⑤⑧ mode-scoped 집계 데이터)."""
        from whymath_backend.api.coach import _log_hint_event
        from whymath_backend.schema.enums import EventType

        sess = _CaptureSession()
        await _log_hint_event(
            cast(AsyncSession, sess),
            user_id=self._UID2,
            problem_id=self._PID2,
            attempt_id=None,
            hint_level=2,
            mode="suneung",
        )
        assert len(sess.added) == 1
        event = sess.added[0]
        assert event.event_type is EventType.힌트제공
        assert event.event_data["mode"] == "suneung"
        assert event.event_data["persona"] is None

    def _tagged_events(self, captured: Any) -> list[Any]:
        """캡처 세션의 attempt_event(검산결과·힌트제공) ORM 인스턴스만 골라낸다."""
        from whymath_backend.db.models.activity import AttemptEvent as AttemptEventORM

        return [o for o in captured.added if isinstance(o, AttemptEventORM)]

    def test_session_create_tags_events_with_suneung_mode(self) -> None:
        """세션 생성(mode=suneung) → 검산·힌트 이벤트 둘 다 event_data.mode=suneung 태깅."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이렇게 풀었어 확인해줘",
                "student_solution": "계산하면 2+3=6 이다",  # 검산결과 이벤트 유발
                "mode": "suneung",
                "persona": Persona.A_일반고고3.value,
            },
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        verify = next(e for e in events if e.event_type is EventType.검산결과)
        hint = next(e for e in events if e.event_type is EventType.힌트제공)
        assert verify.event_data["mode"] == "suneung"
        assert verify.event_data["persona"] == "A_일반고고3"
        assert hint.event_data["mode"] == "suneung"
        assert hint.event_data["persona"] == "A_일반고고3"

    def test_session_create_no_mode_is_regression_free(self) -> None:
        """mode 미지정 → event_data.mode=None(mode-agnostic·기존 동작 완전 불변·회귀 0)."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "확인해줘",
                "student_solution": "계산하면 2+3=6 이다",
            },
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        verify = next(e for e in events if e.event_type is EventType.검산결과)
        hint = next(e for e in events if e.event_type is EventType.힌트제공)
        assert verify.event_data["mode"] is None
        assert verify.event_data["persona"] is None
        assert hint.event_data["mode"] is None

    def test_append_turn_tags_events_with_mode(self) -> None:
        """멀티턴(mode=suneung) → 후속 턴의 힌트 이벤트도 event_data.mode=suneung 태깅."""
        from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
        from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
        from whymath_backend.schema.enums import EventType

        did = uuid.uuid4()
        key = (DialogueORM, did)
        dialogue = DialogueORM.from_schema(
            DialogueSchema(
                dialogue_id=did, user_id=_UID, total_turns=2, student_turns=1, assistant_turns=1
            )
        )
        client, captured = _session_client(preload={key: dialogue})
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json={"student_input": "여기서부터 모르겠어", "mode": "suneung"},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        # 풀이 미제출 턴이라 검산결과는 없고 힌트제공만 — 그 힌트 이벤트가 mode 태깅됐는지 확인.
        hint = next(e for e in events if e.event_type is EventType.힌트제공)
        assert hint.event_data["mode"] == "suneung"


# ── S3-16 소생: 엔드포인트 결선(힌트요청·막힘 적재 + 학생 대면 응답 무변경 회귀) ──────
class TestDemandStuckEventWiring:
    """S3-16 — `create_session`/`append_turns`가 답 요구·5회+ 막힘 신호를 실제로 적재한다.

    `TestSuneungModeTagging`과 동형 2층 검증(단위는 위 `TestLogDemandEvent`/`TestLogStuckEvent`)
    — 여기선 *엔드포인트 결선*(요청 필드 → 실제 적재)과 *학생 대면 응답 무변경*(페이로드 회귀)만
    확인한다. `_log_response_latency_event`(답입력)는 실 PG의 턴 영속이 필요해 여기선 다루지
    않는다 — `test_coach_integration.py`(실 PG)가 담당.
    """

    def _tagged_events(self, captured: Any) -> list[Any]:
        from whymath_backend.db.models.activity import AttemptEvent as AttemptEventORM

        return [o for o in captured.added if isinstance(o, AttemptEventORM)]

    def test_session_create_demand_token_logs_hint_request_event(self) -> None:
        """세션 생성(답 요구 발화) → 힌트요청 이벤트 1행 적재."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "그냥 답 알려줘"},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        demand_events = [e for e in events if e.event_type is EventType.힌트요청]
        assert len(demand_events) == 1

    def test_session_create_no_demand_signal_logs_zero_hint_request_events(self) -> None:
        """답 요구 신호 없는 발화 → 힌트요청 이벤트 0행(날조 회피)."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "이렇게 접근하면 될까요?"},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        assert [e for e in events if e.event_type is EventType.힌트요청] == []

    def test_session_create_stuck_turn_count_logs_stuck_event(self) -> None:
        """polya_state.turn_count≥5 → 막힘 이벤트 1행 적재(event_data.turn_count=실측값)."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "polya_state": {"turn_count": 5}},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        stuck_events = [e for e in events if e.event_type is EventType.막힘]
        assert len(stuck_events) == 1
        assert stuck_events[0].event_data["turn_count"] == 5

    def test_session_create_below_threshold_logs_zero_stuck_events(self) -> None:
        """polya_state.turn_count<5 → 막힘 이벤트 0행(날조 회피)."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "polya_state": {"turn_count": 2}},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        assert [e for e in events if e.event_type is EventType.막힘] == []

    def test_session_create_never_logs_response_latency_event(self) -> None:
        """`create_session`은 새 dialogue의 첫 턴이라 답입력(응답 지연) 이벤트를 *절대* 적재하지
        않는다(기준선 없음·날조 회피) — 답 요구·막힘 신호를 동시에 유발해도 마찬가지."""
        from whymath_backend.schema.enums import EventType

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "그냥 답 알려줘", "polya_state": {"turn_count": 5}},
        )
        assert resp.status_code == 201, resp.text
        events = self._tagged_events(captured)
        assert [e for e in events if e.event_type is EventType.답입력] == []

    def test_student_facing_response_payload_has_no_new_fields(self) -> None:
        """S3-16 writer는 순수 부수효과 — 응답 JSON에 힌트요청/막힘/답입력 키가 없다(회귀 고정).

        `SessionCreateResponse`는 S3-16 이전 필드셋 그대로다 — writer가 반환값을 응답에 노출하지
        않는지 최상위 키 목록으로 고정한다.
        """
        client, _ = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "그냥 답 알려줘", "polya_state": {"turn_count": 5}},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        for leaked_key in (
            "demand_events",
            "stuck_events",
            "response_latency_ms",
            "server_latency_ms",
            "turn_count_events",
        ):
            assert leaked_key not in body


# ── WH-1 2단계 슬라이스 3: _apply_hypotheses 가드·결선 단위테스트 ──────────────────
class TestApplyHypothesesGuard:
    """`_apply_hypotheses` — user_id None 방어 가드 + curate_hypothesis 위임(하네스 동치).

    ConsentedUser 게이트가 user_id를 항상 채우므로 None 분기는 라우터 경로로는 닿지 않는 방어
    분기다. 가드가 *DB 무접근*으로 빈 리스트를 돌려주는지(curate_hypothesis 미호출·세션 미터치)와,
    유효 user_id일 때 `apply_matches`가 아니라 §3 도구4 `curate_hypothesis`(증거 반박 R4·최대5
    캡)로 위임하는지를 직접 호출로 확인한다. 반박·캡 *내부 로직*은 store 테스트
    (`test_hypothesis_store.py`·실 PG 포함)에서 검증한다 — 본 테스트는 *결선(위임)*만 핀한다.
    """

    async def test_none_user_returns_empty_without_db_touch(self) -> None:
        from whymath_backend.api.coach import _apply_hypotheses

        # 세션을 만지면 AttributeError로 터지는 가짜 — 가드가 DB를 건드리지 않음을 보장.
        class _Boom:
            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"user_id=None 가드는 세션을 만지지 않아야 한다: {name}")

        result = await _apply_hypotheses(cast(AsyncSession, _Boom()), None, [])
        assert result == []

    async def test_valid_user_delegates_to_curate_hypothesis(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 라이브 coach가 `apply_matches`(매치만)가 아니라 `curate_hypothesis`(증거 반박·캡·하네스
        # 동치)로 위임함을 핀 — student_id=user_id·matches 그대로 전달·반환 세트 패스스루.
        from whymath_backend.api import coach as coach_mod

        seen: dict[str, Any] = {}
        curated = [_hyp(0.9)]

        async def _fake_curate(
            session: Any, *, student_id: Any, matches: Any, **kw: Any
        ) -> list[MisconceptionHypothesis]:
            seen["student_id"] = student_id
            seen["matches"] = matches
            return curated

        monkeypatch.setattr(coach_mod, "curate_hypothesis", _fake_curate)
        uid = uuid.uuid4()
        ms: list[Any] = []  # matches는 위임 인자만 핀하므로 빈 리스트로 충분(세션 미터치).
        result = await coach_mod._apply_hypotheses(cast(AsyncSession, object()), uid, ms)
        assert result is curated
        assert seen["student_id"] == uid
        assert seen["matches"] is ms


class TestLogMatchEvidence:
    """`_log_match_evidence` — 확정 매치를 +1 지지 증거로 `evidence_links`에 적재(§2.3 생산측).

    #268이 라이브 coach를 증거 그래프의 *소비측*(curate→net_support 반박)으로 결선했고, 본 헬퍼는
    그 짝인 *생산측*이다(하네스 `log_evidence` 패턴 모사). 본 테스트는 결선(매치→+1 지지·
    weight=confidence)과 가드만 핀한다 — `log_evidence` 내부는 evidence_store 테스트가 검증.
    """

    class _M:
        """매치 스텁 — `_log_match_evidence`가 읽는 `.misconception.id`·`.confidence`만."""

        def __init__(self, mid: str, confidence: float) -> None:
            self.misconception = type("_Mc", (), {"id": mid})()
            self.confidence = confidence

    async def test_logs_plus_one_support_per_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        async def _fake_log(session: Any, **kw: Any) -> Any:
            calls.append(kw)
            return None

        monkeypatch.setattr(coach, "log_evidence", _fake_log)
        sid, uid = uuid.uuid4(), uuid.uuid4()
        matches = [self._M("distribution-over-power", 1.0), self._M("sign-flip-in-inequality", 0.7)]
        await coach._log_match_evidence(
            cast(AsyncSession, object()),
            session_id=sid,
            student_id=uid,
            matches=cast(Any, matches),
        )
        assert len(calls) == 2
        assert [c["misconception_id"] for c in calls] == [
            "distribution-over-power",
            "sign-flip-in-inequality",
        ]
        assert all(c["polarity"] == 1 for c in calls)  # 매치 = +1 지지
        assert [c["weight"] for c in calls] == [1.0, 0.7]  # weight=confidence
        assert all(c["session_id"] == sid and c["student_id"] == uid for c in calls)

    async def test_empty_matches_no_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        async def _fake_log(session: Any, **kw: Any) -> Any:
            nonlocal called
            called = True

        monkeypatch.setattr(coach, "log_evidence", _fake_log)
        await coach._log_match_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            matches=[],
        )
        assert called is False

    async def test_none_student_guard_no_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 인증 게이트라 미도달이나 방어 가드 — student_id None이면 log_evidence 미호출(세션 미터치).
        async def _boom_log(session: Any, **kw: Any) -> Any:
            raise AssertionError("student_id=None 가드는 log_evidence를 호출하지 않아야 한다.")

        monkeypatch.setattr(coach, "log_evidence", _boom_log)
        await coach._log_match_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=None,
            matches=cast(Any, [self._M("distribution-over-power", 1.0)]),
        )  # 예외 없이 통과 = 가드 동작

    def test_endpoint_logs_evidence_for_confident_match(self) -> None:
        # 확정 매치(distribution-over-power·confidence 1.0)를 내는 입력 → EvidenceLink(+1) 적재.
        from whymath_backend.db.models.evidence_link import EvidenceLink

        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "내 풀이는 (a+b)² = a² + b² 이렇게 했어"},
        )
        assert resp.status_code == 201, resp.text
        links = [o for o in captured.added if isinstance(o, EvidenceLink)]
        assert len(links) >= 1
        assert all(link.polarity == 1 for link in links)
        assert any(link.misconception_id == "distribution-over-power" for link in links)

    def test_endpoint_no_confident_match_no_evidence(self) -> None:
        # 신뢰 게이트로 비워진(no_confident_match) 입력 → EvidenceLink 미적재(생산 0).
        from whymath_backend.db.models.evidence_link import EvidenceLink

        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json={"student_input": "음"})
        assert resp.status_code == 201, resp.text
        assert [o for o in captured.added if isinstance(o, EvidenceLink)] == []


class TestLogRefutationEvidence:
    """`_log_refutation_evidence` — clean 풀이(no-match)를 active 가설에 −1 반박 적재(§2.3 짝).

    `_log_match_evidence`(+1 지지)의 짝이다. 본 테스트는 결선 규칙(passed=True·no-match·active당
    polarity=-1)과 3중 게이트(passed≠True·matches 존재·student_id None·빈 active), 그리고 *가중
    tier*(정정 형태 검출 시 _REFUTE_STRONG_WEIGHT·아니면 _REFUTE_WEIGHT)를 핀한다 — `log_evidence`
    내부는 evidence_store 테스트가 검증한다.
    """

    class _M:
        """매치 스텁 — no-match 게이트(`if matches`)만 트리거하면 되므로 빈 객체로 충분."""

    async def test_clean_no_match_logs_minus_one_per_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # passed=True·매치 없음·active 2개·정정 형태 없는 풀이 → 가설당 −1(weight=_REFUTE_WEIGHT).
        calls: list[dict[str, Any]] = []

        async def _fake_log(session: Any, **kw: Any) -> Any:
            calls.append(kw)
            return None

        monkeypatch.setattr(coach, "log_evidence", _fake_log)
        sid, uid = uuid.uuid4(), uuid.uuid4()
        active = [_hyp(0.8, "distribution-over-power"), _hyp(0.4, "sign-flip-in-inequality")]
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=sid,
            student_id=uid,
            passed=True,
            matches=[],
            active_hypotheses=active,
            solution_text="x = 2",  # 정정 형태 없음 → 전부 약한 가중
        )
        assert len(calls) == 2
        assert [c["misconception_id"] for c in calls] == [
            "distribution-over-power",
            "sign-flip-in-inequality",
        ]
        assert all(c["polarity"] == -1 for c in calls)  # clean 정답 = 반박
        assert all(c["weight"] == coach._REFUTE_WEIGHT for c in calls)  # 약한 가중(정정 없음)
        assert all(c["session_id"] == sid and c["student_id"] == uid for c in calls)

    async def test_correct_form_tiers_strong_weight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 정정 형태 검출 가설은 강한 가중(1.0)·미검출 가설은 약한 가중(0.5) — tier 정밀 귀속.
        calls: list[dict[str, Any]] = []

        async def _fake_log(session: Any, **kw: Any) -> Any:
            calls.append(kw)
            return None

        monkeypatch.setattr(coach, "log_evidence", _fake_log)
        active = [_hyp(0.8, "distribution-over-power"), _hyp(0.4, "sign-flip-in-inequality")]
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            passed=True,
            matches=[],
            active_hypotheses=active,
            # distribution-over-power의 정정 형태만 포함 → 그 가설은 강·다른 가설은 약.
            solution_text="전개하면 (a+b)² = a² + 2ab + b² 입니다",
        )
        by_id = {c["misconception_id"]: c for c in calls}
        assert all(c["polarity"] == -1 for c in calls)  # 강·약 모두 반박 방향(낙인 0)
        assert by_id["distribution-over-power"]["weight"] == coach._REFUTE_STRONG_WEIGHT
        assert by_id["sign-flip-in-inequality"]["weight"] == coach._REFUTE_WEIGHT

    async def test_match_gate_blocks_refutation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # no-match 게이트 — 이번 턴이 매치(+1)면 같은 턴 반박 안 함(상호배타·모순 차단).
        async def _boom_log(session: Any, **kw: Any) -> Any:
            raise AssertionError("매치 존재 턴은 반박(−1)을 적재하지 않아야 한다.")

        monkeypatch.setattr(coach, "log_evidence", _boom_log)
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            passed=True,
            matches=cast(Any, [self._M()]),
            active_hypotheses=[_hyp(0.8)],
            solution_text="x = 2",
        )  # 예외 없이 통과 = 게이트 동작

    @pytest.mark.parametrize("passed", [False, None])
    async def test_passed_gate_blocks_refutation(
        self, passed: bool | None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # clean(passed is True)만 반박 — False(거짓관계 적발)·None(풀이 아님)은 적재 0.
        async def _boom_log(session: Any, **kw: Any) -> Any:
            raise AssertionError(f"passed={passed!r}는 반박을 적재하지 않아야 한다.")

        monkeypatch.setattr(coach, "log_evidence", _boom_log)
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            passed=passed,
            matches=[],
            active_hypotheses=[_hyp(0.8)],
            solution_text="x = 2",
        )  # 예외 없이 통과 = 게이트 동작

    async def test_none_student_guard_no_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 인증 게이트라 미도달이나 방어 가드 — student_id None이면 적재 0.
        async def _boom_log(session: Any, **kw: Any) -> Any:
            raise AssertionError("student_id=None 가드는 log_evidence를 호출하지 않아야 한다.")

        monkeypatch.setattr(coach, "log_evidence", _boom_log)
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=None,
            passed=True,
            matches=[],
            active_hypotheses=[_hyp(0.8)],
            solution_text="x = 2",
        )  # 예외 없이 통과 = 가드 동작

    async def test_empty_active_no_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # passed=True·no-match지만 의심 가설이 없으면 적재 0(반박할 대상 없음).
        called = False

        async def _fake_log(session: Any, **kw: Any) -> Any:
            nonlocal called
            called = True

        monkeypatch.setattr(coach, "log_evidence", _fake_log)
        await coach._log_refutation_evidence(
            cast(AsyncSession, object()),
            session_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            passed=True,
            matches=[],
            active_hypotheses=[],
            solution_text="x = 2",
        )
        assert called is False

    # --- 엔드포인트: 핸들러가 clean 풀이(no-match)에서 active 가설을 −1 반박 적재 ---
    _PID = uuid.uuid4()

    def test_endpoint_clean_solution_refutes_active_hypotheses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # active 가설 주입 + 무매치 입력("음") + clean 풀이("x = 2") → EvidenceLink(−1) 적재.
        from whymath_backend.db.models.evidence_link import EvidenceLink

        async def _fake(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
            return [_hyp(0.8, "distribution-over-power")]

        monkeypatch.setattr("whymath_backend.api.coach._apply_hypotheses", _fake)
        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "student_solution": "x = 2"},
        )
        assert resp.status_code == 201, resp.text
        links = [o for o in captured.added if isinstance(o, EvidenceLink)]
        assert len(links) == 1
        assert links[0].polarity == -1
        assert links[0].misconception_id == "distribution-over-power"
        assert links[0].weight == coach._REFUTE_WEIGHT  # 정정 형태 없는 풀이 → 약한 가중

    def test_endpoint_correct_form_solution_refutes_strongly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # active 가설(distribution) + 무매치 입력("음") + 그 오개념의 *정정 형태*를 담은 clean 풀이
        # → EvidenceLink(−1·강한 가중). 정밀 귀속: 학생이 올바른 완전제곱을 직접 보였다.
        from whymath_backend.db.models.evidence_link import EvidenceLink

        async def _fake(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
            return [_hyp(0.8, "distribution-over-power")]

        monkeypatch.setattr("whymath_backend.api.coach._apply_hypotheses", _fake)
        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": "음", "student_solution": "(a+b)² = a² + 2ab + b²"},
        )
        assert resp.status_code == 201, resp.text
        links = [o for o in captured.added if isinstance(o, EvidenceLink)]
        assert len(links) == 1
        assert links[0].polarity == -1
        assert links[0].misconception_id == "distribution-over-power"
        assert links[0].weight == coach._REFUTE_STRONG_WEIGHT  # 정정 형태 검출 → 강한 가중

    def test_endpoint_match_turn_logs_support_not_refutation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 매치 턴 → +1 지지만(no-match 게이트로 −1 미적재·상호배타).
        # MISC-17: 진단은 WH-1 primary와 같이 `student_solution or student_input`을 본다 —
        # 풀이가 있으면 *풀이*가 매치 턴의 정의다(형제 케이스 5116·5139도 풀이 기준 반박을 기대).
        # 종전 픽스처("발화에 신호 + clean 풀이 x = 2")는 풀이 우선에서 no-match→−1이 되므로,
        # 이 테스트의 의도(+1/−1 상호배타)를 보존하려 신호를 풀이에 둔다.
        from whymath_backend.db.models.evidence_link import EvidenceLink

        async def _fake(session: Any, user_id: Any, matches: Any) -> list[MisconceptionHypothesis]:
            return [_hyp(0.8, "distribution-over-power")]

        monkeypatch.setattr("whymath_backend.api.coach._apply_hypotheses", _fake)
        client, captured = _session_client()
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": "이렇게 풀었어",
                "student_solution": "내 풀이는 (a+b)² = a² + b² 이렇게 했어",
            },
        )
        assert resp.status_code == 201, resp.text
        links = [o for o in captured.added if isinstance(o, EvidenceLink)]
        assert len(links) >= 1
        assert all(link.polarity == 1 for link in links)  # 매치 턴 = +1만(−1 없음)
