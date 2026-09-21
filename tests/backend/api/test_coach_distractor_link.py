"""ASM-06 — 학생이 *탭한 오답 선지*가 코치 경로에서 오개념 가설로 이어진다.

**왜 코치 경로가 본류인가(실측 2026-09-21)**: 모바일은 `POST /v1/me/attempts`를 부르지
않는다(`completion_signal.dart`·`coach_models.dart`가 "api/coach.py 계약 명문·중복 적재
금지"로 자인). 선지 탭은 `chat_screen.dart::_onChoiceSelected` → 코치 턴으로 가고,
`ProblemAttempt`는 `api/coach.py::_complete_problem`이 만든다.

**그리고 그 attempt에는 오답이 실릴 수 없다**: `_complete_problem`은 서버가 정답을 확인한
순간에만 호출돼 `is_correct=True`만 적재한다. 즉 coach 경로에서 *오답 선지*가 남는 자리는
attempt 행이 아니라 **대화 턴**이고, 그 턴의 오개념 좌석은 `_compute_matches` →
`_apply_hypotheses`(`curate_hypothesis`)다. 이 파일이 그 관통을 고정한다.

**고정하는 것**:
  (a) 선지 인덱스가 응답 `active_hypotheses`에 도달 — 두 세션 경로 모두
  (b) `misconception_hypothesis` 행이 실제로 적재 — 같은 트랜잭션
  (c) 변별력: 인덱스를 빼면 (a)(b)가 사라진다 — 다른 경로가 채운 것이 아님을 보인다

**의도적으로 하지 않는 것**: 새 응답 필드 0(별도 판정 경로 금지 — 기존 가설 좌석으로만
흐른다) · 새 게이트·임계 0(`apply_match_quality_gate` 재사용) · 노출 규칙 변경 0.

hermetic — `test_coach_ocr_solution_diagnosis.py`의 capturing-session 패턴을 자족적으로
복제(교차 import 관례 없음). 실 DB·실 LLM 0. `student_input`은 **중립 문자열**을 쓴다 —
텍스트 채널이 우연히 후보를 내면 "선지 채널이 일했다"는 주장이 오염되기 때문이다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from whymath_backend.api._auth import get_consented_user
from whymath_backend.app import create_app
from whymath_backend.config import Settings, get_settings
from whymath_backend.db.models.dialogue import Dialogue as DialogueORM
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_PROBLEM_ID = uuid.uuid4()

#: 정본 카탈로그 실재 id — 변환기가 미등록 id를 거르므로 실물이어야 한다.
_MID = "absolute-value-keeps-sign"

#: 학생이 탭한 오답 보기의 0-기반 인덱스와 그 문항의 매핑.
_TAPPED_INDEX = 2
_DISTRACTOR_MAP: list[dict[str, Any]] = [
    {"choice_index": _TAPPED_INDEX, "misconception_id": _MID},
]

#: **중립 발화** — 카탈로그 substring 신호를 하나도 담지 않는다. 이 문자열로 텍스트 채널이
#: 후보를 내면 아래 단언이 선지 채널의 증거가 되지 못하므로, 그 사실 자체를
#: `test_neutral_input_alone_yields_nothing`이 먼저 확인한다(픽스처 자기 검증).
_NEUTRAL_INPUT = "이거 골랐어요"


def _settings() -> Settings:
    # 모든 rate limit 0(비활성) — test_coach.py `_settings_override` 기본값과 동일.
    return Settings(
        jwt_secret_key=SecretStr("test-secret-0123456789abcdef"),
        coach_rate_limit_read_per_minute=0,
        coach_rate_limit_write_per_minute=0,
        coach_rate_limit_ip_read_per_minute=0,
        coach_rate_limit_ip_write_per_minute=0,
        coach_rate_limit_device_read_per_minute=0,
        coach_rate_limit_device_write_per_minute=0,
    )


def _user() -> UserProfile:
    return UserProfile.from_schema(
        UserProfileSchema(user_id=_UID, persona_primary=Persona.A_일반고고3)
    )


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any:
        return self._rows[0] if self._rows else None


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one(self) -> Any:
        # curate_hypothesis가 net_support 집계를 scalar_one으로 읽는다 — 증거 행 없음 = 0.0.
        return 0.0

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class _CapturingSession:
    """세션 경로용 — add/commit/flush/get/execute 캡처 + `scalar` 컬럼 분기.

    `scalar`를 컬럼명으로 가르는 이유는 `test_me.py::_QueueSession`과 같다: 핸들러가 단일
    스칼라로 읽는 컬럼이 여럿이라, 무엇이 와도 같은 값을 돌려주면 엉뚱한 값이 *조용히*
    흐른다(크래시가 없어 더 위험하다).
    """

    def __init__(
        self,
        preload: dict[Any, Any] | None = None,
        *,
        distractor_map: list[dict[str, Any]] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.distractor_map = distractor_map
        self.distractor_map_queries = 0
        self._preload = preload or {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def add_all(self, objs: list[Any]) -> None:
        self.added.extend(objs)

    async def commit(self) -> None:
        self.commits += 1

    async def flush(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def get(self, model: Any, pk: Any) -> Any | None:
        return self._preload.get((model, pk))

    async def scalar(self, stmt: Any) -> Any:
        try:
            column_name = stmt.column_descriptions[0]["name"]
        except (AttributeError, IndexError, KeyError, TypeError):  # pragma: no cover - 방어
            column_name = None
        if column_name == "distractor_map":
            self.distractor_map_queries += 1
            return self.distractor_map
        return None

    async def execute(self, stmt: Any) -> _Result:
        return _Result([])


def _client(
    preload: dict[Any, Any] | None = None,
    *,
    distractor_map: list[dict[str, Any]] | None = None,
) -> tuple[TestClient, _CapturingSession]:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings
    captured = _CapturingSession(preload=preload, distractor_map=distractor_map)

    async def _sess() -> AsyncIterator[_CapturingSession]:
        yield captured

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), captured


def _preloaded_dialogue(dialogue_id: uuid.UUID) -> tuple[Any, Any]:
    """append_turns용 — 소유자 `_UID`의 기존 대화(2턴·문항 귀속)를 `.get`에 주입."""
    return (DialogueORM, dialogue_id), DialogueORM.from_schema(
        DialogueSchema(
            dialogue_id=dialogue_id,
            user_id=_UID,
            problem_id=_PROBLEM_ID,
            total_turns=2,
            student_turns=1,
            assistant_turns=1,
        )
    )


def _hypothesis_ids(captured: _CapturingSession) -> list[str]:
    return [
        o.misconception_id for o in captured.added if isinstance(o, MisconceptionHypothesisRecord)
    ]


def _body(*, selected_choice_index: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"student_input": _NEUTRAL_INPUT}
    if selected_choice_index is not None:
        payload["selected_choice_index"] = selected_choice_index
    return payload


# ══════════════════════════════════════════════════════════════════════════
# 0. 픽스처 자기 검증 — 중립 발화가 정말 중립인가
# ══════════════════════════════════════════════════════════════════════════
def test_neutral_input_alone_yields_nothing() -> None:
    """중립 발화만으로는 후보·가설이 0이다.

    이 단언이 없으면 아래 초록이 "선지 채널이 일했다"의 증거가 되지 못한다 — 텍스트 채널이
    우연히 같은 오개념을 냈을 수도 있기 때문이다. 픽스처가 자기 전제를 먼저 증명한다.
    """
    client, captured = _client(distractor_map=_DISTRACTOR_MAP)
    resp = client.post("/v1/coach/sessions", json=_body(selected_choice_index=None))
    assert resp.status_code == 201, resp.text
    assert resp.json()["misconceptions"] == []
    assert _hypothesis_ids(captured) == []
    assert resp.json()["active_hypotheses"] == []


def test_catalog_id_is_real() -> None:
    """미등록 id면 변환기가 걸러 아무 일도 안 일어난다 — 그 함정을 픽스처 단계에서 배제."""
    assert _MID in CATALOG_BY_ID


# ══════════════════════════════════════════════════════════════════════════
# 1. 본류 — 선지 탭 → 가설 좌석 (두 세션 경로)
# ══════════════════════════════════════════════════════════════════════════
class TestTappedDistractorReachesHypotheses:
    def test_create_session_persists_hypothesis_from_tapped_choice(self) -> None:
        """`/v1/coach/sessions` — 탭한 인덱스만으로 가설 행이 적재되고 응답에 노출된다."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=_TAPPED_INDEX), "problem_id": str(_PROBLEM_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert _MID in _hypothesis_ids(captured), (
            "misconception_hypothesis 행 미적재 — "
            f"added={[type(o).__name__ for o in captured.added]}"
        )
        exposed = [h["misconception_id"] for h in resp.json()["active_hypotheses"]]
        assert _MID in exposed, f"활성 가설 미노출: {exposed}"
        assert captured.commits >= 1

    def test_append_turns_persists_hypothesis_from_tapped_choice(self) -> None:
        """`/v1/coach/sessions/{id}/turns` — 멀티턴도 동형(problem_id 출처만 dialogue)."""
        did = uuid.uuid4()
        key, dialogue = _preloaded_dialogue(did)
        client, captured = _client(preload={key: dialogue}, distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            f"/v1/coach/sessions/{did}/turns",
            json=_body(selected_choice_index=_TAPPED_INDEX),
        )
        assert resp.status_code == 201, resp.text
        assert _MID in _hypothesis_ids(captured), "멀티턴 가설 행 미적재"
        exposed = [h["misconception_id"] for h in resp.json()["active_hypotheses"]]
        assert _MID in exposed, f"멀티턴 활성 가설 미노출: {exposed}"


class TestTwoChannelsMerge:
    """텍스트 채널과 선지 채널이 겹칠 때의 합류 규칙.

    [픽스처 접촉 메모] 위 테스트들은 *중립* 발화를 써서 텍스트 채널이 아예 돌지 않는다 —
    그래서 중복 제거 절(`_merge_distractor_matches`의 `known` 집합)을 **한 번도 밟지 않는다**.
    뮤테이션에서 그 절이 생존해 발각됐고, 절을 지우는 대신 그 절의 반례를 여기 넣는다:
    두 채널이 *같은* 오개념을 지목하는 발화 + 매핑.
    """

    #: 카탈로그 substring 신호가 그대로 든 발화 — 텍스트 채널이 `_SHARED_MID`를 낸다.
    _SIGNAL_INPUT = "내 풀이는 (a+b)² = a² + b² 이렇게 했어"
    _SHARED_MID = "distribution-over-power"

    @staticmethod
    def _evidence_count(resp_json: dict[str, Any], mid: str) -> int:
        (hyp,) = [h for h in resp_json["active_hypotheses"] if h["misconception_id"] == mid]
        count: int = hyp["evidence_count"]
        return count

    def test_same_misconception_from_both_channels_counts_as_one_evidence(self) -> None:
        """두 채널이 같은 오개념을 지목해도 **증거 1건**으로 센다.

        [단언 축 주의] 가설 *행 수*로는 이것을 잴 수 없다 — `update_hypotheses`가 id를 키로
        하는 딕셔너리라 중복이 들어와도 행은 1건으로 접힌다. 중복의 실제 피해는 그 루프가
        같은 id를 두 번 만나 `reinforce`와 `evidence_count + 1`을 **두 번** 적용하는 것이다.
        즉 같은 사실의 사본이 학생 상태를 두 배로 밀어 올린다(낙인 위험). 그래서 여기서는
        횟수를 센다 — 뮤테이션 M13 생존으로 발각된 축이며, 행 수 단언은 정상/중복 양쪽에서
        1이라 **변별력이 0이었다**.
        """
        client, captured = _client(
            distractor_map=[{"choice_index": _TAPPED_INDEX, "misconception_id": self._SHARED_MID}]
        )
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": self._SIGNAL_INPUT,
                "selected_choice_index": _TAPPED_INDEX,
                "problem_id": str(_PROBLEM_ID),
            },
        )
        assert resp.status_code == 201, resp.text
        assert _hypothesis_ids(captured).count(self._SHARED_MID) == 1
        assert self._evidence_count(resp.json(), self._SHARED_MID) == 1

    def test_text_channel_alone_yields_the_shared_id(self) -> None:
        """대조군 — 선지 없이도 텍스트 채널만으로 그 오개념이 나온다.

        이 대조가 없으면 위 '1건'이 *선지 채널이 텍스트 채널을 덮어썼기 때문*인지
        *제대로 합쳐졌기 때문*인지 구분되지 않는다.
        """
        client, captured = _client(distractor_map=None)
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": self._SIGNAL_INPUT, "problem_id": str(_PROBLEM_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert _hypothesis_ids(captured).count(self._SHARED_MID) == 1
        # 대조군의 핵심 — 한 채널만 돌았을 때의 증거 횟수. 위 테스트가 이 값과 같아야
        # "합쳐졌다"가 성립하고, 2가 되면 사본이 두 번 계상된 것이다.
        assert self._evidence_count(resp.json(), self._SHARED_MID) == 1

    def test_different_misconceptions_both_persist(self) -> None:
        """반대 방향 — 서로 다른 오개념이면 둘 다 남는다(합치는 것이 삼키는 것은 아니다)."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            "/v1/coach/sessions",
            json={
                "student_input": self._SIGNAL_INPUT,
                "selected_choice_index": _TAPPED_INDEX,
                "problem_id": str(_PROBLEM_ID),
            },
        )
        assert resp.status_code == 201, resp.text
        ids = set(_hypothesis_ids(captured))
        assert {self._SHARED_MID, _MID} <= ids, f"두 채널 중 하나가 삼켜졌다: {ids}"


# ══════════════════════════════════════════════════════════════════════════
# 2. 변별력 — 무엇을 빼면 사라지는가(양방향 주입)
# ══════════════════════════════════════════════════════════════════════════
class TestDiscrimination:
    def test_without_index_nothing_happens(self) -> None:
        """인덱스를 빼면 같은 문항·같은 매핑에서도 가설이 0이다."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=None), "problem_id": str(_PROBLEM_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert _hypothesis_ids(captured) == []

    def test_without_index_the_map_is_never_queried(self) -> None:
        """reactive retrieval — 인덱스가 없으면 `distractor_map` 조회 *자체*를 하지 않는다."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=None), "problem_id": str(_PROBLEM_ID)},
        )
        assert captured.distractor_map_queries == 0

    def test_with_index_the_map_is_queried_once(self) -> None:
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=_TAPPED_INDEX), "problem_id": str(_PROBLEM_ID)},
        )
        assert captured.distractor_map_queries == 1

    def test_unmapped_index_yields_nothing(self) -> None:
        """매핑에 없는 인덱스(정답 선지 등)는 후보가 되지 않는다."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=_TAPPED_INDEX + 1), "problem_id": str(_PROBLEM_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert _hypothesis_ids(captured) == []

    def test_problem_without_map_yields_nothing(self) -> None:
        """문항에 매핑이 없으면 대조할 대상이 없다 — 크래시 없이 조용히 0."""
        client, captured = _client(distractor_map=None)
        resp = client.post(
            "/v1/coach/sessions",
            json={**_body(selected_choice_index=_TAPPED_INDEX), "problem_id": str(_PROBLEM_ID)},
        )
        assert resp.status_code == 201, resp.text
        assert _hypothesis_ids(captured) == []

    def test_no_problem_context_yields_nothing(self) -> None:
        """문항 귀속이 없는 자유 대화 턴 — 조회할 문항이 없으므로 0(방어)."""
        client, captured = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post("/v1/coach/sessions", json=_body(selected_choice_index=_TAPPED_INDEX))
        assert resp.status_code == 201, resp.text
        assert captured.distractor_map_queries == 0
        assert _hypothesis_ids(captured) == []


# ══════════════════════════════════════════════════════════════════════════
# 3. 킬 스위치·요청 계약
# ══════════════════════════════════════════════════════════════════════════
class TestKillSwitchAndContract:
    def test_flag_off_stops_the_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """플래그 OFF면 DB 조회조차 하지 않는다(양방향 주입 — ON은 위 테스트들이 확인)."""
        monkeypatch.setenv("WHYMATH_L4_DISTRACTOR_LINK_ENABLED", "false")
        get_settings.cache_clear()
        try:
            client, captured = _client(distractor_map=_DISTRACTOR_MAP)
            # 플래그는 `get_settings()` 직접 호출로 읽히므로 override가 아닌 env가 정본이다.
            client.app.dependency_overrides.pop(get_settings, None)
            resp = client.post(
                "/v1/coach/sessions",
                json={
                    **_body(selected_choice_index=_TAPPED_INDEX),
                    "problem_id": str(_PROBLEM_ID),
                },
            )
            assert resp.status_code == 201, resp.text
            assert captured.distractor_map_queries == 0
            assert _hypothesis_ids(captured) == []
        finally:
            get_settings.cache_clear()

    def test_negative_index_is_rejected(self) -> None:
        client, _ = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post("/v1/coach/sessions", json=_body(selected_choice_index=-1))
        assert resp.status_code == 422, resp.text

    def test_unknown_field_still_forbidden(self) -> None:
        """`extra="forbid"` 불변 — 슬롯을 하나 연 것이지 계약을 연 것이 아니다."""
        client, _ = _client(distractor_map=_DISTRACTOR_MAP)
        resp = client.post(
            "/v1/coach/sessions",
            json={"student_input": _NEUTRAL_INPUT, "chosen_option_position": 1},
        )
        assert resp.status_code == 422, resp.text

    def test_stateless_coach_accepts_but_ignores_the_slot(self) -> None:
        """stateless `/v1/coach`는 DB 무접근 계약이라 슬롯을 받되 소비하지 않는다(422 아님)."""
        app = create_app()
        app.dependency_overrides[get_consented_user] = _user
        app.dependency_overrides[get_settings] = _settings

        class _NoDbSession:
            async def execute(self, stmt: Any) -> None:
                raise AssertionError("stateless 경로는 DB 쿼리하지 않아야 한다.")

            async def scalar(self, stmt: Any) -> None:
                raise AssertionError("stateless 경로는 DB 쿼리하지 않아야 한다.")

        async def _sess() -> AsyncIterator[_NoDbSession]:
            yield _NoDbSession()

        app.dependency_overrides[get_session] = _sess
        resp = TestClient(app).post("/v1/coach", json=_body(selected_choice_index=_TAPPED_INDEX))
        assert resp.status_code == 200, resp.text
