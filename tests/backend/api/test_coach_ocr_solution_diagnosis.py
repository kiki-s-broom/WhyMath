"""MISC-17 — 손글씨(OCR) 풀이를 오개념 진단 입력에 합류.

**갭(R2 §2 G1 · 04e §9-D1)**: 발화를 만드는 WH-1 primary 3곳은 `body.student_solution or
body.student_input`을 봤지만, 진단(`_compute_matches`) 호출 3곳은 `body.student_input` *단독*이었다.
사진 제출 턴(`student_input=''` + `student_solution` 채움)은 발화는 풀이를 알고 학생 상태(가설·
증거)는 모르는 split-brain — 가설·증거 적재가 **0**이었다.

**이 파일이 고정하는 것(acceptance ③)**: OCR 제출 형상에서 세 핸들러 전부
  (a) 후보 산출(`misconceptions`에 카탈로그 id)
  (b) `misconception_hypothesis` 행 적재(`MisconceptionHypothesisRecord`가 session.add됨)
  (c) `evidence_links` 적재(`EvidenceLink`가 session.add됨)
수정 전 코드에서 세 케이스 전부 RED임을 먼저 확인한 뒤 구현했다(변별력 실측 — 커밋 메시지).

**의도적으로 하지 않는 것(acceptance ④·⑤)**: 새 게이트·임계 0(OCR 품질 강등은 기존
`ocr_confidence → apply_match_quality_gate` 게이트 ②가 담당) · 두 필드 이어붙이기 0 · 모바일 무변경.

hermetic — `test_coach.py`의 capturing-session 패턴을 자족적으로 복제(교차 import 관례 없음).
실 DB·실 LLM 0. 매칭은 카탈로그 substring 신호 `(a+b)² = a² + b²`(confidence 1.0)로 결정론.
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
from whymath_backend.db.models.evidence_link import EvidenceLink
from whymath_backend.db.models.misconception_hypothesis import MisconceptionHypothesisRecord
from whymath_backend.db.models.user import UserProfile
from whymath_backend.db.session import get_session
from whymath_backend.schema.dialogue import Dialogue as DialogueSchema
from whymath_backend.schema.enums import Persona
from whymath_backend.schema.user import UserProfile as UserProfileSchema

_UID = uuid.uuid4()
_MID = "distribution-over-power"  # 카탈로그 슬라이스 4 — (a+b)² = a² + b² 신호로 풀 매칭
_SOLUTION = "내 풀이는 (a+b)² = a² + b² 이렇게 했어"  # test_coach.py의 검증된 신호 원문 그대로
# 인식기(Qwen3-VL/PaddleOCR)의 *계약상* 산출물은 LaTeX(`OcrResult.plain_latex`) — 유니코드
# 위첨자가 아니다. 이 세 형태가 진단에 닿지 않으면 "합류"는 픽스처에서만 성립하는 위장이다
# (PR #1034 Codex P1 ①). L4 `_normalize`의 LaTeX 접기(`^`·`{}`·`\left`/`\right`)가 담당한다.
_OCR_LATEX_FORMS: tuple[str, ...] = (
    "(a+b)^2 = a^2+b^2",
    "(a+b)^{2} = a^{2}+b^{2}",
    r"\left(a+b\right)^2 = a^2+b^2",
)

# OCR 제출 형상 — 발화는 비고 풀이만 있다. ocr_confidence ≥ 0.8이라 게이트 ②는 dormant
# (low_quality=False) — 이 파일은 *합류* 여부만 보고 품질 강등은 기존 테스트 소관이다.
_OCR_BODY: dict[str, Any] = {
    "student_input": "",
    "student_solution": _SOLUTION,
    "ocr_confidence": 0.95,
}


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


class _FakeSession:
    """`/v1/coach`(stateless)용 — DB 호출 시 AssertionError(DB 무접근 계약)."""

    async def execute(self, stmt: Any) -> None:
        raise AssertionError("coach 라우터(stateless)는 DB 쿼리하지 않아야 한다.")


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
    """`/v1/coach/sessions`용 — add/add_all/commit/flush/refresh/get/execute 캡처."""

    def __init__(self, preload: dict[Any, Any] | None = None) -> None:
        self.added: list[Any] = []
        self.commits = 0
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

    async def execute(self, stmt: Any) -> _Result:
        return _Result([])


def _stateless_client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings

    async def _sess() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _sess
    return TestClient(app)


def _session_client(
    preload: dict[Any, Any] | None = None,
) -> tuple[TestClient, _CapturingSession]:
    app = create_app()
    app.dependency_overrides[get_consented_user] = _user
    app.dependency_overrides[get_settings] = _settings
    captured = _CapturingSession(preload=preload)

    async def _sess() -> AsyncIterator[_CapturingSession]:
        yield captured

    app.dependency_overrides[get_session] = _sess
    return TestClient(app), captured


def _preloaded_dialogue(dialogue_id: uuid.UUID) -> tuple[Any, Any]:
    """append_turns용 — 소유자 `_UID`의 기존 대화(2턴)를 `.get(Dialogue, id)`에 미리 주입."""
    return (DialogueORM, dialogue_id), DialogueORM.from_schema(
        DialogueSchema(
            dialogue_id=dialogue_id,
            user_id=_UID,
            total_turns=2,
            student_turns=1,
            assistant_turns=1,
        )
    )


def _hypothesis_rows(captured: _CapturingSession) -> list[MisconceptionHypothesisRecord]:
    return [o for o in captured.added if isinstance(o, MisconceptionHypothesisRecord)]


def _evidence_rows(captured: _CapturingSession) -> list[EvidenceLink]:
    return [o for o in captured.added if isinstance(o, EvidenceLink)]


class TestOcrSolutionReachesDiagnosis:
    """OCR 제출 형상(`student_input=''` + `student_solution`)이 세 핸들러의 진단에 합류한다."""

    def test_stateless_coach_yields_candidates_from_solution(self) -> None:
        """(a) `/v1/coach` — 발화가 비어도 풀이의 신호로 후보가 산출된다."""
        resp = _stateless_client().post("/v1/coach", json=_OCR_BODY)
        assert resp.status_code == 200, resp.text
        ids = [m["misconception"]["id"] for m in resp.json()["misconceptions"]]
        assert _MID in ids, f"풀이의 신호가 진단에 합류하지 않았다: {ids}"

    def test_create_session_persists_hypothesis_and_evidence(self) -> None:
        """(a)(b)(c) `/v1/coach/sessions` — 후보 + 가설 행 + 증거 링크가 같은 트랜잭션에 적재."""
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=_OCR_BODY)
        assert resp.status_code == 201, resp.text

        ids = [m["misconception"]["id"] for m in resp.json()["misconceptions"]]
        assert _MID in ids, f"(a) 후보 미산출: {ids}"

        hyps = _hypothesis_rows(captured)
        assert any(
            h.misconception_id == _MID for h in hyps
        ), f"(b) misconception_hypothesis 행 미적재 — added={[type(o).__name__ for o in captured.added]}"
        links = _evidence_rows(captured)
        assert any(
            link.misconception_id == _MID for link in links
        ), f"(c) evidence_links 미적재 — added={[type(o).__name__ for o in captured.added]}"
        assert captured.commits >= 1

    def test_append_turns_persists_hypothesis_and_evidence(self) -> None:
        """(a)(b)(c) `/v1/coach/sessions/{id}/turns` — 멀티턴 경로도 동형."""
        did = uuid.uuid4()
        key, dialogue = _preloaded_dialogue(did)
        client, captured = _session_client(preload={key: dialogue})
        resp = client.post(f"/v1/coach/sessions/{did}/turns", json=_OCR_BODY)
        assert resp.status_code == 201, resp.text

        ids = [m["misconception"]["id"] for m in resp.json()["misconceptions"]]
        assert _MID in ids, f"(a) 후보 미산출: {ids}"
        assert any(
            h.misconception_id == _MID for h in _hypothesis_rows(captured)
        ), "(b) misconception_hypothesis 행 미적재"
        assert any(
            link.misconception_id == _MID for link in _evidence_rows(captured)
        ), "(c) evidence_links 미적재"


class TestOcrLatexFormsReachDiagnosis:
    """대표 OCR LaTeX 형상 3종이 세션 경로에서 (a)(b)(c) 전부 성립 — 픽스처 한정 통과의 위장 방지."""

    @pytest.mark.parametrize("latex", _OCR_LATEX_FORMS)
    def test_create_session_latex_forms(self, latex: str) -> None:
        client, captured = _session_client()
        body = {**_OCR_BODY, "student_solution": latex}
        resp = client.post("/v1/coach/sessions", json=body)
        assert resp.status_code == 201, resp.text
        ids = [m["misconception"]["id"] for m in resp.json()["misconceptions"]]
        assert _MID in ids, f"(a) LaTeX형 후보 미산출: {latex!r} → {ids}"
        assert any(h.misconception_id == _MID for h in _hypothesis_rows(captured)), "(b)"
        assert any(link.misconception_id == _MID for link in _evidence_rows(captured)), "(c)"


class TestLowQualityOcrDoesNotPersist:
    """게이트 ② `low_quality`(ocr_confidence<0.8)의 *집행 지점* — 미확인 전사는 학생 상태를 바꾸지 않는다.

    게이트 ②는 설계상 매칭을 유지하고 플래그만 세워 L5가 재확인을 유도하게 한다. 그런데 이 PR이
    `student_solution`을 진단에 합류시키면서, 노이즈 전사가 우연히 카탈로그 패턴을 담으면 그 매칭이
    가설 큐레이션·+1 지지·−1 반박으로 *즉시 영속*되는 경로가 열렸다(Codex P1 ②). 응답 플래그는
    DB 쓰기를 되돌리지 못하므로 영속 계층이 플래그를 소비해야 한다. 응답의 후보·플래그는 불변.
    """

    _LOW_BODY: dict[str, Any] = {**_OCR_BODY, "ocr_confidence": 0.5}

    def test_create_session_low_quality_flags_but_does_not_persist(self) -> None:
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=self._LOW_BODY)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 응답은 종전과 동일 — 후보 노출 + 재확인 유도 플래그(게이트 ② 의미론 불변).
        assert _MID in [m["misconception"]["id"] for m in body["misconceptions"]]
        assert body["match_low_quality"] is True
        # 영속은 0 — 가설 신규 편입·지지(+1)·반박(−1) 어느 것도 미확인 전사로 쓰지 않는다.
        assert _hypothesis_rows(captured) == [], "저품질 OCR 매칭이 가설로 영속됐다"
        assert _evidence_rows(captured) == [], "저품질 OCR 매칭이 증거로 영속됐다"

    def test_append_turns_low_quality_flags_but_does_not_persist(self) -> None:
        did = uuid.uuid4()
        key, dialogue = _preloaded_dialogue(did)
        client, captured = _session_client(preload={key: dialogue})
        resp = client.post(f"/v1/coach/sessions/{did}/turns", json=self._LOW_BODY)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert _MID in [m["misconception"]["id"] for m in body["misconceptions"]]
        assert body["match_low_quality"] is True
        assert _hypothesis_rows(captured) == []
        assert _evidence_rows(captured) == []

    def test_high_confidence_control_still_persists(self) -> None:
        # 대조군 — 같은 형상에서 ocr_confidence=0.95면 영속된다(위 두 검사가 변별력을 갖는 근거).
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=_OCR_BODY)
        assert resp.status_code == 201, resp.text
        assert resp.json()["match_low_quality"] is False
        assert _hypothesis_rows(captured) != []
        assert _evidence_rows(captured) != []


class TestAttributionUnclearDoesNotPersist:
    """MISC-28 ⓒ 게이트 ③의 *집행 지점* — 귀속 불명은 학생 상태를 바꾸지 않는다.

    게이트 ②(`low_quality`)와 **같은 좌석**이다: 응답에는 후보를 그대로 싣되 학습자 모델에는
    확정 진단으로 넣지 않는다. 응답 플래그는 DB 쓰기를 되돌리지 못하기 때문이다(MISC-17의
    근거를 그대로 물려받는다).

    여기서 쓰는 형상은 **전치 정정 라벨**이다 — 남의 오답을 인용해 비판하는 학생. 정정이
    신호 *뒤*였다면 귀속이 어순으로 확정돼 후보에서 아예 빠지므로(MISC-25) 이 경로를 밟지
    않는다. 그 구별이 이 클래스가 고정하는 계약이다.
    """

    #: 전치 정정 라벨 — `잘못`류 어휘가 신호 lookbehind 창(12자) 안에 있어야 이 분기를 밟는다.
    _HELD_SOLUTION = "틀린 풀이: (a+b)² = a² + b²"
    _HELD_BODY: dict[str, Any] = {
        "student_input": "",
        "student_solution": _HELD_SOLUTION,
        "ocr_confidence": 0.95,  # 게이트 ②는 dormant — 이 클래스는 게이트 ③만 본다
    }

    def test_create_session_attribution_unclear_flags_but_does_not_persist(self) -> None:
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=self._HELD_BODY)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        # 응답은 후보를 유지한다 — 보류는 억제가 아니다(억제하면 오억제 100%로 회귀).
        assert _MID in [m["misconception"]["id"] for m in body["misconceptions"]]
        assert body["match_attribution_unclear"] is True
        assert body["match_low_quality"] is False, "게이트 ②가 아니라 ③이 발동해야 한다"
        # 영속은 0 — 귀속이 불명한 매칭을 확정 진단으로 학습자 모델에 넣지 않는다.
        assert _hypothesis_rows(captured) == [], "귀속 불명 매칭이 가설로 영속됐다"
        assert _evidence_rows(captured) == [], "귀속 불명 매칭이 증거로 영속됐다"

    def test_append_turns_attribution_unclear_flags_but_does_not_persist(self) -> None:
        did = uuid.uuid4()
        key, dialogue = _preloaded_dialogue(did)
        client, captured = _session_client(preload={key: dialogue})
        resp = client.post(f"/v1/coach/sessions/{did}/turns", json=self._HELD_BODY)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert _MID in [m["misconception"]["id"] for m in body["misconceptions"]]
        assert body["match_attribution_unclear"] is True
        assert _hypothesis_rows(captured) == []
        assert _evidence_rows(captured) == []

    def test_clear_attribution_control_still_persists(self) -> None:
        """[대조군] 정정_어구가_없으면_종전대로_영속된다 — 위 두 검사의 변별력 근거

        이 대조군이 없으면 "전부 보류"라는 과잉 수정이 초록을 낸다.
        """
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=_OCR_BODY)
        assert resp.status_code == 201, resp.text
        assert resp.json()["match_attribution_unclear"] is False
        assert _hypothesis_rows(captured) != []
        assert _evidence_rows(captured) != []

    def test_refutation_evidence_is_withheld_not_inverted(self) -> None:
        """보류가_−1_반박으로_뒤집히지_않는다 — "모른다 ≠ 아니다"

        보류된 매칭을 빈 리스트로 넘기면 하류 `_log_refutation_evidence`가 그것을 "clean
        풀이(no-match)"로 읽어 활성 가설을 **−1로 반박**한다. 즉 판정 보류가 조용히
        "이 오개념은 아니다"라는 **반대 방향 확신**이 된다. 증거 행이 0이어야 하는 이유는
        영속 억제만이 아니라 이것이다 — 위 두 검사가 `== []`를 요구하는 진짜 근거.
        """
        client, captured = _session_client()
        resp = client.post("/v1/coach/sessions", json=self._HELD_BODY)
        assert resp.status_code == 201, resp.text
        assert _evidence_rows(captured) == [], "보류가 −1 반박 증거를 만들었다(모른다→아니다)"


class TestTextTurnUnchanged:
    """acceptance ② — `student_solution=None`인 텍스트 턴은 `or` 폴백으로 종전과 동일."""

    @pytest.mark.parametrize("path", ["/v1/coach"])
    def test_text_only_turn_still_matches_on_student_input(self, path: str) -> None:
        resp = _stateless_client().post(path, json={"student_input": _SOLUTION})
        assert resp.status_code == 200, resp.text
        ids = [m["misconception"]["id"] for m in resp.json()["misconceptions"]]
        assert _MID in ids

    def test_neutral_text_turn_has_no_candidates(self) -> None:
        # 풀이 없음 + 중립 발화 → 후보 0 (기존 `test_misconceptions_empty_for_neutral_input`과 동치).
        resp = _stateless_client().post("/v1/coach", json={"student_input": "음"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["misconceptions"] == []
