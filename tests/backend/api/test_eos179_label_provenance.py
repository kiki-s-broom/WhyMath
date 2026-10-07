"""코치 라벨의 출처·증거 수 원장 계측 — EOS-179 ② (DB 무접근 단위).

EOS-178이 공급 원장(`힌트제공`)에 `ability_level`(적용된 라벨)을 싣기 시작했지만, 그 라벨이
**무엇으로 만들어졌는지**는 남기지 않았다 — 클라가 직접 보낸 `mastery_level`인지, 서버 L2의 개념
숙달도인지, 서버 θ뿐인지, 서버가 검증하지 못한 클라 제출 bkt인지가 섞여 있으면 "라벨이 맞았는가"를
출처별로 가를 수 없고, 관측 1건짜리 숙달도와 40건짜리 숙달도가 같은 정확도로 센다. 이 파일은 그
두 값(`label_source`·`label_evidence_n`)이 결정 → 핸들러 → 원장까지 흐르는 경로를 고정한다:

  - `_label_provenance` 진리표(우선순위: 명시 > 서버 bkt > 클라 bkt > 서버 θ).
  - 증거 수는 서버 개념 숙달도가 **라벨에 들어간** 턴에만 조회·적재한다(불필요한 조회 0).
  - 증거 수 None(모름)과 0(관측 0건)은 구별된다.
  - 두 값은 응답 본문에 나가지 않는다.
  - 두 핸들러(`create_session`·`append_turns`)가 빠짐없이 결선한다(AST — 호출부 하나가 빠지면
    그 경로의 원장 행만 계측 없이 쌓이고 사후 백필은 불가능하다).

실 PG 위의 전 경로(HTTP → 원장 JSONB)는 `test_eos179_label_provenance_integration.py`가 본다.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

import whymath_backend.api.coach as coach_module
from whymath_backend.api.coach import CoachRequest
from whymath_backend.schema.enums import EventType
from whymath_backend.schema.event_data_contract import build_event_data

_UID = uuid.UUID("00000000-0000-0000-0000-00000000e179")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000a0179")


def _payload(*, body_extra: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    """`_build_response_payload`의 결정(첫 원소)만 돌려준다 — DB 무접근 sync 경로."""
    body = CoachRequest(student_input="모르겠어요", **(body_extra or {}))
    return coach_module._build_response_payload(body, **kwargs)[0]


class TestLabelProvenanceTruthTable:
    """`_label_provenance` — 라벨이 실제로 만들어진 입력으로 출처를 정한다."""

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            # 라벨 없음 → 출처·증거 수 모두 None(날조 금지)
            (
                dict(level=None, explicit_level=None, server_mastery=None, client_bkt=None),
                (None, None),
            ),
            # 명시 라벨이 모든 입력을 이긴다 — 서버 증거 수가 있어도 그 라벨의 증거가 아니다
            (
                dict(level="숙달", explicit_level="숙달", server_mastery=0.1, client_bkt=0.1),
                ("explicit", None),
            ),
            # 서버 개념 숙달도가 들어갔다 → 증거 수를 싣는다
            (
                dict(level="초보", explicit_level=None, server_mastery=0.1, client_bkt=None),
                ("server_bkt", 9),
            ),
            # 서버 값이 클라 값을 대체한다 — 클라 bkt가 같이 와도 서버 출처다
            (
                dict(level="초보", explicit_level=None, server_mastery=0.1, client_bkt=0.9),
                ("server_bkt", 9),
            ),
            # 서버 숙달도 없이 클라 제출 bkt만 → 서버가 검증하지 못한 입력
            (
                dict(level="초보", explicit_level=None, server_mastery=None, client_bkt=0.1),
                ("client_bkt", None),
            ),
            # 숙달도가 둘 다 없는데 라벨이 있다면 서버 θ뿐이다
            (
                dict(level="초보", explicit_level=None, server_mastery=None, client_bkt=None),
                ("server_theta", None),
            ),
        ],
    )
    def test_priority_and_evidence(self, kwargs: dict[str, Any], expected: tuple[Any, Any]) -> None:
        got = coach_module._label_provenance(server_evidence_n=9, **kwargs)
        assert got == expected

    def test_unknown_evidence_is_none_not_zero(self) -> None:
        """sample_size 미기록(None)은 '모름'이다 — 0으로 접지 않는다."""
        got = coach_module._label_provenance(
            level="초보",
            explicit_level=None,
            server_mastery=0.1,
            client_bkt=None,
            server_evidence_n=None,
        )
        assert got == ("server_bkt", None)

    def test_zero_observations_stays_zero(self) -> None:
        """관측 0건은 확정 주장이라 None과 구별되어 남는다."""
        got = coach_module._label_provenance(
            level="초보",
            explicit_level=None,
            server_mastery=0.1,
            client_bkt=None,
            server_evidence_n=0,
        )
        assert got == ("server_bkt", 0)


class TestDecisionCarriesProvenance:
    """`_build_response_payload`가 결정에 출처·증거 수를 싣는다(재계산 0·라벨은 그대로)."""

    def test_server_bkt_with_evidence(self) -> None:
        d = _payload(server_mastery=0.1, server_mastery_evidence=7)
        assert d.applied_mastery_level == "초보"
        assert (d.label_source, d.label_evidence_n) == ("server_bkt", 7)

    def test_server_bkt_with_unknown_evidence(self) -> None:
        d = _payload(server_mastery=0.1, server_mastery_evidence=None)
        assert (d.label_source, d.label_evidence_n) == ("server_bkt", None)

    def test_explicit_level_wins_and_drops_evidence(self) -> None:
        d = _payload(
            body_extra={"mastery_level": "숙달"}, server_mastery=0.1, server_mastery_evidence=7
        )
        assert d.applied_mastery_level == "숙달"
        assert (d.label_source, d.label_evidence_n) == ("explicit", None)

    def test_client_bkt_ignores_a_stray_evidence_value(self) -> None:
        """서버 숙달도가 없는데 증거 수가 들어와도 클라 bkt 라벨의 증거로 적히지 않는다."""
        d = _payload(
            body_extra={"bkt_mastery": 0.1}, server_mastery=None, server_mastery_evidence=7
        )
        assert (d.label_source, d.label_evidence_n) == ("client_bkt", None)

    def test_theta_only_label(self) -> None:
        d = _payload(server_theta=-3.0)
        assert d.applied_mastery_level == "초보"
        assert (d.label_source, d.label_evidence_n) == ("server_theta", None)

    def test_no_label_no_provenance(self) -> None:
        d = _payload()
        assert d.applied_mastery_level is None
        assert (d.label_source, d.label_evidence_n) == (None, None)

    def test_provenance_is_not_part_of_the_response_body(self) -> None:
        """내부 계측이다 — 직렬화(응답·OpenAPI)에 나가면 학생 대면 표면이 넓어진다."""
        d = _payload(server_mastery=0.1, server_mastery_evidence=7)
        for dumped in (d.model_dump(), d.model_dump(mode="json")):
            assert "label_source" not in dumped
            assert "label_evidence_n" not in dumped


class TestServerMasteryEvidenceLookup:
    """`_server_mastery_evidence_for` — 서버 숙달도가 라벨에 들어간 턴에만 조회한다."""

    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        seen: list[str] = []

        async def _concept(_session: Any, problem_id: uuid.UUID) -> uuid.UUID | None:
            seen.append("concept")
            return uuid.UUID(int=problem_id.int ^ 1)

        async def _size(_session: Any, _uid: uuid.UUID, _cid: uuid.UUID) -> int | None:
            seen.append("size")
            return 12

        monkeypatch.setattr(coach_module, "get_primary_concept_id", _concept)
        monkeypatch.setattr(coach_module, "get_current_mastery_sample_size", _size)
        return seen

    def _run(self, **kwargs: Any) -> int | None:
        merged: dict[str, Any] = {
            "server_mastery": 0.3,
            "explicit_level": None,
            "problem_id": _PID,
        }
        merged.update(kwargs)
        problem_id = merged.pop("problem_id")
        return asyncio.run(
            coach_module._server_mastery_evidence_for(
                None,  # type: ignore[arg-type]
                _UID,
                problem_id,
                **merged,
            )
        )

    def test_reads_the_count_when_the_server_mastery_was_used(self, calls: list[str]) -> None:
        assert self._run() == 12
        assert calls == ["concept", "size"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"server_mastery": None},  # 서버 숙달도가 라벨에 안 들어갔다
            {"explicit_level": "숙달"},  # 명시 라벨이 이겼다 — 증거 수는 그 라벨의 것이 아니다
            {"problem_id": None},  # 문항 맥락이 없다
        ],
    )
    def test_skips_the_lookup_when_the_count_would_not_be_the_labels_evidence(
        self, calls: list[str], kwargs: dict[str, Any]
    ) -> None:
        assert self._run(**kwargs) is None
        assert calls == []  # 불필요한 DB 조회 0건

    def test_unresolved_concept_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _no_concept(_session: Any, _pid: uuid.UUID) -> None:
            return None

        monkeypatch.setattr(coach_module, "get_primary_concept_id", _no_concept)
        assert self._run() is None


class TestLedgerRowCarriesProvenance:
    """`_log_hint_event` → `힌트제공` 행의 JSONB 키."""

    class _Capture:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, obj: Any) -> None:
            self.added.append(obj)

    def _log(self, **kwargs: Any) -> dict[str, Any]:
        session = self._Capture()
        asyncio.run(
            coach_module._log_hint_event(
                session,  # type: ignore[arg-type]
                user_id=_UID,
                problem_id=_PID,
                attempt_id=None,
                hint_level=2,
                **kwargs,
            )
        )
        assert len(session.added) == 1
        assert session.added[0].event_type is EventType.힌트제공
        return dict(session.added[0].event_data)

    def test_source_and_count_are_written(self) -> None:
        data = self._log(ability_level="초보", label_source="server_bkt", label_evidence_n=7)
        assert (data["label_source"], data["label_evidence_n"]) == ("server_bkt", 7)

    def test_zero_is_kept_distinct_from_unknown(self) -> None:
        zero = self._log(label_source="server_bkt", label_evidence_n=0)
        unknown = self._log(label_source="server_bkt", label_evidence_n=None)
        assert zero["label_evidence_n"] == 0
        assert unknown["label_evidence_n"] is None

    def test_omitted_fields_read_as_a_legacy_row(self) -> None:
        data = self._log()
        assert data["label_source"] is None and data["label_evidence_n"] is None

    def test_contract_rejects_a_negative_count(self) -> None:
        with pytest.raises(ValidationError):
            build_event_data(EventType.힌트제공, hint_level=2, label_evidence_n=-1)


def _calls(name: str) -> list[ast.Call]:
    tree = ast.parse(inspect.getsource(coach_module))
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
    ]


class TestEveryPersistentHandlerIsWired:
    """두 영속 핸들러가 빠짐없이 결선한다 — 한 곳이 빠지면 그 경로의 행만 계측 없이 쌓인다."""

    def test_both_handlers_look_up_the_evidence_with_the_explicit_level(self) -> None:
        calls = _calls("_server_mastery_evidence_for")
        assert len(calls) >= 2, f"증거 수 조회 호출 {len(calls)}건 — 가드가 공허하다."
        for call in calls:
            passed = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
            assert passed.get("server_mastery") == "server_mastery", call.lineno
            assert passed.get("explicit_level") == "body.mastery_level", call.lineno

    def test_both_handlers_pass_the_evidence_into_the_decision(self) -> None:
        wired = [
            call
            for call in _calls("_build_response_payload")
            if any(kw.arg == "server_mastery" for kw in call.keywords)
        ]
        assert len(wired) >= 2, f"서버 숙달도를 넘기는 호출 {len(wired)}건 — 가드가 공허하다."
        for call in wired:
            passed = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
            assert passed.get("server_mastery_evidence") == "server_mastery_evidence", call.lineno

    def test_every_ledger_write_carries_the_provenance(self) -> None:
        calls = _calls("_log_hint_event")
        assert len(calls) >= 2, f"_log_hint_event 호출 {len(calls)}건 — 가드가 공허하다."
        for call in calls:
            passed = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
            assert passed.get("label_source") == "decision.label_source", call.lineno
            assert passed.get("label_evidence_n") == "decision.label_evidence_n", call.lineno

    def test_server_mastery_lookup_keeps_its_float_contract(self) -> None:
        """증거 수를 위해 `_server_mastery_for`의 반환형을 바꾸지 않았다 — 기존 호출부·테스트가
        그 float 계약에 기댄다(monkeypatch 대체값도 float)."""
        sig = inspect.signature(coach_module._server_mastery_for)
        assert "float" in str(sig.return_annotation)
        assert "tuple" not in str(sig.return_annotation)
