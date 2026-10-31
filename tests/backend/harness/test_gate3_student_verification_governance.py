"""게이트 ③ 봉인 — "학생 응답은 전부 PRM/도구 검증 통과 후"를 코드 경로로 증명.

S1 탈출 게이트 ③(CLAUDE.md "LLM 응답을 검증 없이 학생에게 제공 금지"·"막혔을 때 바로 정답
금지")의 안전 불변식을 *회귀 차단*한다. 이미 두 차례 읽기전용 조사로 확정된 사실을 봉인만 하며,
동작을 바꾸지 않는다(coach→하네스 전면 수렴은 별도 미래 작업·범위 밖).

정본 이식: `tests/backend/l1/test_embedding_namespace_governance.py`의
`test_cosine_distance_usage_frozen_to_index_modules` — `whymath_backend.__file__` 부모에서
`rglob("*.py")` 소스 스캔 → 사용 모듈 집합이 frozenset allowlist와 *정확히 일치*(추가·누락 모두
red). 그 형식을 그대로 이식해 게이트 ③을 네 각도로 봉인한다:

  (A) **소스 봉인** — 학생 HTTP 경로가 *미검증 LLM 발화 생성기*(`PolyaCoach.coach()`)를 호출하지
      않음을 rglob 스윕 + frozen allowlist로 동결. api/* 유입 = 게이트 ③ 심사 트리거(red).
  (B) **행위 계약** — coach가 미검증 verdict(오답·미검증)에서도 정답을 노출하지 않음을 hermetic
      실증(라이브 LLM 불요). expected_answer는 shadow sink로만 흐르고 응답 payload엔 안 실림.
  (C) **하네스 게이트 재봉인** — 하네스가 검증 게이트를 소유(verify-before-finalize·정답 억제)함을
      게이트 ③ 명명으로 재확인. 1차 커버는 `test_wh1_loop.py`(아래 참조)·여기선 명명 재봉인.
  (D) **`/v1/generate` 비학생 계약 봉인** — 검증 전 원시 출력·학생 직접 노출 금지 계약을 소스 고정.

hermetic: DB·Redis·라이브 LLM 불요(소스 스캔·순수 함수 직접 호출·가짜 정책·monkeypatch만).
민감정보(정답·학생 텍스트)는 assert 메시지에 원문 노출하지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from pydantic import BaseModel

import whymath_backend
import whymath_backend.l4.solution_coaching as solution_coaching
from whymath_backend.api import coach
from whymath_backend.harness.wh1_loop import (
    Action,
    EndTurnAction,
    ScriptedTutorPolicy,
    VerifyStepAction,
    run_tutoring_turn,
)
from whymath_backend.l4.polya.prompts import STAGE_PROMPTS

# 패키지 소스 루트 — rglob 스윕 기준(l1 governance 선례와 동일).
_PACKAGE_ROOT = Path(whymath_backend.__file__).parent


def _module_users_of(needle: str) -> set[str]:
    """패키지 소스에서 `needle` 문자열을 포함하는 모듈의 상대경로 집합(posix)."""
    users: set[str] = set()
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if needle in path.read_text(encoding="utf-8"):
            users.add(path.relative_to(_PACKAGE_ROOT).as_posix())
    return users


# ──────────────────────────────────────────────────────────────────────────
# (A) 소스 봉인 — 학생 HTTP 경로가 미검증 LLM 발화 생성기를 호출하지 않음
# ──────────────────────────────────────────────────────────────────────────
# `PolyaCoach.coach()`(`l4/polya/engine.py:108`)는 decide→LLM 생성→톤필터를 한 번에 도는
# *유일한 LLM 발화 생성기*다. 이 발화는 PRM/도구 검증을 거치지 않으므로(톤필터는 표현 방어선일
# 뿐 사실 검증이 아님) 어떤 학생 HTTP 엔드포인트도 이걸 호출해선 안 된다. 현재 `.coach(` 텍스트는
# engine.py 자기 docstring(정의 site 설명) 한 곳에만 존재하고 *실 호출자는 0*이다. 이 allowlist를
# 정확 일치로 동결하면, 누군가 학생 경로(api/*)에 `PolyaCoach().coach(...)`를 배선하는 순간
# 집합이 달라져 red가 된다 — 그 red가 곧 게이트 ③ 심사(검증 게이트 우회 방지) 트리거다.
_COACH_LLM_GENERATOR_ALLOWLIST: frozenset[str] = frozenset(
    {
        "l4/polya/engine.py",  # 정의 site(자기 docstring 참조) — 실 호출자 아님. 여기 외 유입 금지.
    }
)


class TestGate3SourceSeal:
    """(A) 미검증 LLM 발화 생성기 호출 봉인 — 학생 경로에 LLM 발화가 새는 회귀를 red로."""

    def test_coach_llm_generator_caller_set_frozen(self) -> None:
        """`.coach(` 사용 모듈 집합이 정확히 allowlist와 일치(추가·누락 모두 red).

        게이트 ③ (A): api/* 등 새 모듈이 미검증 LLM 발화 생성기를 배선하면 이 봉인이 깨진다 —
        그 리뷰 시점이 곧 "검증 없이 학생에게 발화가 닿는가" 심사다.
        """
        users = _module_users_of(".coach(")
        assert users == set(_COACH_LLM_GENERATOR_ALLOWLIST), (
            "미검증 LLM 발화 생성기(PolyaCoach.coach) 사용 모듈이 allowlist와 다릅니다 — 게이트 ③ "
            f"(검증 없이 학생 발화 금지). 발견: {sorted(users)} / 허용: "
            f"{sorted(_COACH_LLM_GENERATOR_ALLOWLIST)}. 학생 경로에 LLM 발화를 배선한 것이라면 "
            "검증 게이트(PRM/도구)를 반드시 경유하도록 재설계하고 이 봉인을 함께 개정하라."
        )

    def test_api_layer_never_wires_coach_llm_generator(self) -> None:
        """api/ 계층 어느 모듈도 `.coach(`를 포함하지 않음(하드 가드).

        게이트 ③ (A): allowlist 정확일치와 별개로, *학생 HTTP 표면*(api/*)에 대한 명시적
        금지선을 둔다 — 미래에 allowlist가 확장돼도 api/*만은 절대 미검증 발화 생성기를 못 문다.
        """
        api_users = {u for u in _module_users_of(".coach(") if u.startswith("api/")}
        assert api_users == set(), (
            f"api 계층이 미검증 LLM 발화 생성기(.coach())를 참조합니다: {sorted(api_users)} — "
            "학생 경로는 결정론 템플릿(_coach.decide)/검증 통과 발화만 반환해야 한다(게이트 ③)."
        )

    def test_build_response_payload_uses_decide_not_coach(self) -> None:
        """coach 응답 payload 조립부는 `_coach.decide()`만 쓰고 `.coach()`(LLM)는 안 씀.

        게이트 ③ (A): `_build_response_payload`가 만드는 AI 턴 content = `decision.prompt` =
        정적 Polya 템플릿이다. 그 소스에 결정론 `.decide(`는 있고 LLM `.coach(`는 없음을 고정해,
        payload 조립이 미검증 LLM 발화로 갈아끼워지는 회귀를 차단한다.
        """
        source = (_PACKAGE_ROOT / "api" / "coach.py").read_text(encoding="utf-8")
        assert "_coach.decide(" in source, "coach payload 조립은 결정론 _coach.decide()여야 한다."
        assert ".coach(" not in source, (
            "api/coach.py가 LLM 발화 생성기 .coach()를 참조합니다 — payload는 검증 없는 LLM "
            "발화를 담아선 안 된다(게이트 ③)."
        )


# ──────────────────────────────────────────────────────────────────────────
# (B) 행위 계약 — coach가 미검증 verdict에서 정답을 노출하지 않음(hermetic)
# ──────────────────────────────────────────────────────────────────────────
# 고유 sentinel — 정적 Polya 템플릿·검산 유도발화 어디에도 등장하지 않는 가짜 "정답값". 실제 정답이
# 아니라 회귀 탐지용 표식이며, assert 메시지에 원문을 싣지 않는다(민감정보 노출 금지 준수).
_SECRET_ANSWER = "x=8675309"

# 거짓 수치관계(계산 슬립) — arithmetic_validator가 검출해 verify 코칭을 깨우는 미검증(오답) 입력.
# 이 턴에서도 정답이 payload에 실리지 않아야 한다(게이트 ③ 핵심).
_FALSE_RELATION_SOLUTION = "2+3=6"


def _dump_component(obj: object) -> str:
    """payload 구성요소 1개를 JSON 문자열로(pydantic/enum/list/None 처리)."""
    if obj is None:
        return ""
    if isinstance(obj, BaseModel):
        return obj.model_dump_json()
    if isinstance(obj, list):
        return json.dumps([_dump_component(o) for o in obj], ensure_ascii=False)
    return json.dumps(str(obj), ensure_ascii=False)


def _serialize_payload(payload: tuple[object, ...]) -> str:
    """`_build_response_payload` 반환 튜플 *전체*를 하나의 직렬화 blob으로(누출 스캔용).

    S4-19로 7-튜플(carry 삽입·마지막 원소=solution_coaching 불변)이 됐다 — 스캔은 길이에
    무관하게 전 원소를 훑으므로 carry(NamedTuple)도 str 폴백으로 blob에 포함된다.
    """
    return "".join(_dump_component(component) for component in payload)


class TestGate3CoachNeverExposesAnswer:
    """(B) 미검증 verdict에서도 coach 응답에 정답 미노출 — expected_answer는 shadow sink 전용."""

    def test_incorrect_solution_payload_excludes_expected_answer(self) -> None:
        """오답(거짓 수치관계)+expected_answer 주입 → 응답 payload 전체에 정답 sentinel 부재.

        게이트 ③ (B): verify가 미검증(계산 슬립)을 잡아 verify 코칭이 표면화돼도, 서버가 아는
        정답(expected_answer)은 payload 어디에도 흘러선 안 된다("스스로 검산" 정적 발문만).
        """
        body = coach.CoachRequest(
            student_input="잘 모르겠어요",
            student_solution=_FALSE_RELATION_SOLUTION,
        )
        payload = coach._build_response_payload(body, expected_answer=_SECRET_ANSWER)
        # S4-19: 7-튜플(carry 삽입) — 마지막 원소=solution_coaching 불변식으로 언패킹한다.
        *_head, sol = payload
        # 전제 확인 — 미검증(계산 슬립)이 실제로 검출돼 verify 코칭이 깨어난 상황이어야 의미가 있다.
        assert (
            sol is not None and sol.arithmetic_error is True
        ), "이 테스트는 verify가 미검증을 잡은 상황을 전제한다(계산 슬립 검출)."
        blob = _serialize_payload(payload)
        assert (
            _SECRET_ANSWER not in blob
        ), "미검증 verdict에서 서버 정답이 coach 응답 payload로 누출됐다 — 게이트 ③ 위반."

    def test_assistant_turn_content_is_static_polya_template(self) -> None:
        """저장될 AI 턴 content(=decision.prompt)가 정적 Polya 템플릿 상수 중 하나·정답 부재.

        게이트 ③ (B): DB에 저장되는 AI 턴 content는 `decision.prompt`뿐이고(coach.py:1265·1417),
        그 값은 `STAGE_PROMPTS[...].prompt`(LLM 0회 결정론)여야 한다 — 정답이 담길 구조가 없다.
        """
        body = coach.CoachRequest(
            student_input="잘 모르겠어요",
            student_solution=_FALSE_RELATION_SOLUTION,
        )
        decision = coach._build_response_payload(body, expected_answer=_SECRET_ANSWER)[0]
        static_prompts = {sp.prompt for sp in STAGE_PROMPTS.values()}
        assert (
            decision.prompt in static_prompts
        ), "AI 턴 content가 정적 Polya 템플릿이 아니다 — 미검증 발화가 저장 경로로 샐 수 있다(게③)"
        assert _SECRET_ANSWER not in decision.prompt, "정적 템플릿에 정답이 담기면 안 된다(게③)."

    def test_expected_answer_flows_only_to_shadow_sink(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """expected_answer는 shadow sink(`observe_step_breaks`)로만 흐르고 payload엔 부재(양면).

        게이트 ③ (B): 정답은 *진단 로그*(비노출)에만 도달하고 학생 표면(payload)엔 결코 실리지
        않는다 — 두 경로를 동시에 관찰해 "sink 전용" 라우팅을 못 박는다.
        """
        captured: dict[str, object] = {}

        # 실 sink를 no-op spy로 교체 — observe_step_breaks 반환은 결과 미반영(fire-and-forget)이라
        # payload 영향 0. expected_answer가 sink에 도달했는지만 기록한다.
        def _spy(
            student_solution: str,
            *,
            problem_id: uuid.UUID | None = None,
            expected_answer: str | None = None,
        ) -> None:
            captured["expected_answer_reached_sink"] = expected_answer == _SECRET_ANSWER

        monkeypatch.setattr(solution_coaching, "observe_step_breaks", _spy)

        body = coach.CoachRequest(
            student_input="잘 모르겠어요",
            student_solution=_FALSE_RELATION_SOLUTION,
        )
        payload = coach._build_response_payload(body, expected_answer=_SECRET_ANSWER)

        assert (
            captured.get("expected_answer_reached_sink") is True
        ), "expected_answer가 shadow 진단 sink에 도달하지 않았다 — sink 라우팅 전제 붕괴."
        assert _SECRET_ANSWER not in _serialize_payload(
            payload
        ), "정답이 shadow sink뿐 아니라 응답 payload로도 흘렀다 — 게이트 ③ 위반."


# ──────────────────────────────────────────────────────────────────────────
# (C) 하네스 게이트 재봉인 — 하네스가 검증 게이트를 소유(정책 무관 최종 강제)
# ──────────────────────────────────────────────────────────────────────────
# 1차 커버(참조·중복 신설 금지): `tests/backend/harness/test_wh1_loop.py`
#   - `TestVerifyObligation` — 풀이 단계 제출 턴의 verify 호출 의무·미호출 end_turn 거부.
#   - `TestAnswerSuppression` — incorrect/unverifiable에서 정책 명시 발화 억제(정답 문자열 미노출).
# 아래 두 테스트는 그 불변식을 *게이트 ③ 명명*으로 재봉인한다 — 게이트 ③ 스위트 단독 실행 시에도
# "verify 전 finalize 금지 + 미검증 정답 억제"가 하네스에 있음을 한곳에서 증명하기 위함이다.
_ANSWER_LEAK = "정답은 x=3이야"  # 어떤 정책이 발화에 실어도 학생에게 닿지 못해야 하는 정답 문자열.


def _run_turn(actions: list[Action], **kwargs: object) -> object:
    """가짜(결정론) 정책으로 WH-1 한 턴 구동 — DB·LLM 불요(hermetic)."""
    return asyncio.run(
        run_tutoring_turn(policy=ScriptedTutorPolicy(actions), **kwargs)  # type: ignore[arg-type]
    )


class TestGate3HarnessInvariant:
    """(C) 하네스가 검증 게이트를 소유 — 정책 선의에 의존하지 않는 최종 강제(게이트 ③ 명명)."""

    def test_verify_before_finalize_enforced_by_harness(self) -> None:
        """풀이 단계 제출 턴은 verify 호출 전 end_turn *거부*(verify-before-finalize).

        게이트 ③ (C): `_exec_end_turn`이 `has_solution_steps and not verify_called`면 발화를
        내지 않는다(:367) — 검증을 건너뛴 finalize가 원천 차단된다. (1차 커버:
        `test_wh1_loop.py::TestVerifyObligation::test_end_turn_rejected_without_verify`.)
        """
        out = _run_turn(
            [EndTurnAction(action_type="질문", utterance="왜 그렇게 했어?")],
            has_solution_steps=True,
            max_tool_calls=3,
        )
        assert out.status == "budget_exhausted"  # type: ignore[attr-defined]  # 검증 없는 finalize 거부→소진
        assert any(r.kind == "end_turn" and not r.ok for r in out.trace)  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        ("steps", "label"),
        [
            (["x+x", "3*x"], "incorrect"),  # 비동치 전이 → incorrect
            (
                ["x+1", "어떤 서술형 논증"],
                "unverifiable",
            ),  # 검증 0 → unverifiable(막힘)
        ],
    )
    def test_answer_suppressed_on_unverified_verdict(self, steps: list[str], label: str) -> None:
        """미검증(incorrect·unverifiable) verdict에서 정책 명시 발화를 억제·정답 문자열 미노출.

        게이트 ③ (C): `_end_turn_utterance`가 `last_verdict ∈ {incorrect, unverifiable}`이면
        정책이 실은 발화를 버리고 소크라테스 파생 발화로만 말한다(:350-352) — LLM이 정답을
        발화에 흘려도 학생에게 닿지 못한다. (1차 커버: `test_wh1_loop.py::TestAnswerSuppression`.)
        """
        out = _run_turn(
            [
                VerifyStepAction(steps=steps),
                EndTurnAction(action_type="힌트", utterance=_ANSWER_LEAK),
            ],
            has_solution_steps=True,
        )
        assert out.status == "ended"  # type: ignore[attr-defined]
        assert _ANSWER_LEAK not in (out.utterance or "")  # type: ignore[attr-defined]  # 정답 발화 억제(label)


# ──────────────────────────────────────────────────────────────────────────
# (D) `/v1/generate` 비학생 계약 봉인 — 검증 전 원시 출력·학생 직접 노출 금지
# ──────────────────────────────────────────────────────────────────────────
# `/v1/generate`(app.py)와 그 파이프라인(l3/pipeline.py)은 *검증 전 원시 LLM 출력*을 반환하는
# 내부 계약이다(학생 직접 노출 금지·표면화는 L4/L5 책임). 이 계약 문구가 소스에서 사라지면 누군가
# 원시 출력을 학생 표면으로 오해·배선할 위험이 생기므로, 계약 마커의 *존재*를 봉인한다(게이트 ③).
_PRE_VERIFICATION_MARKERS: tuple[str, ...] = ("검증 전 원시", "학생에게 직접 노출 금지")


class TestGate3GenerateNonStudentContract:
    """(D) generate 경로의 '검증 전 원시·비학생' 계약 문구를 소스로 고정."""

    def test_pipeline_declares_pre_verification_contract(self) -> None:
        """`l3/pipeline.py`가 검증 전 원시 출력·학생 직접 노출 금지 계약을 명시.

        게이트 ③ (D): 파이프라인 반환은 검증 전 원시 출력이라는 계약을 소스에 못 박아, 원시
        출력이 검증 없이 학생에게 흐르는 재해석을 차단한다.
        """
        source = (_PACKAGE_ROOT / "l3" / "pipeline.py").read_text(encoding="utf-8")
        for marker in _PRE_VERIFICATION_MARKERS:
            assert marker in source, (
                f"l3/pipeline.py에서 게이트 ③ 계약 문구('{marker}')가 사라졌다 — 검증 전 원시 "
                "출력의 비학생 경계가 약화됐다."
            )

    def test_generate_endpoint_declares_pre_verification_contract(self) -> None:
        """`/v1/generate`(app.py) 엔드포인트가 동일 계약 문구를 명시.

        게이트 ③ (D): HTTP 표면 자체에도 '검증 전 원시·학생 직접 노출 금지' 계약이 남아 있어야
        한다 — 원시 생성물이 학생 응답으로 오배선되는 회귀를 문서·소스 레벨에서 차단한다.
        """
        source = (_PACKAGE_ROOT / "app.py").read_text(encoding="utf-8")
        for marker in _PRE_VERIFICATION_MARKERS:
            assert marker in source, (
                f"app.py /v1/generate에서 게이트 ③ 계약 문구('{marker}')가 사라졌다 — 원시 출력의 "
                "비학생 경계가 약화됐다."
            )


# ──────────────────────────────────────────────────────────────────────────
# (E) WH-1 primary flip 표면 봉인 — 학생-대면 LLM 발화의 *유일한* 허용 표면 (S1-11 사인오프)
# ──────────────────────────────────────────────────────────────────────────
# 2026-07-20 flip 사인오프(MEMORY): "학생-대면 자유 텍스트로 검증 안 된 LLM 출력이 방출되지
# 않는다" 불변식은 유지하되, **검증 게이트를 통과한** LLM 발화 표면 *하나*를 명시적으로 개방한다 —
# `harness/wh1_primary.py`(`run_wh1_primary_turn`): 발화는 `run_tutoring_turn`의 verify 의무(§3.1)·
# 정답 억제 백스톱(§3.4)을 통과하고 L4 톤필터를 거친 것만 반환되며, 실패 시 None(호출자 결정론
# 폴백)이다. 아래 allowlist 3종은 그 표면을 *정확 일치*로 동결한다(무제한 개방 금지) — 새 모듈이
# 플래그·러너를 소비하면 red가 되고, 그 리뷰 시점이 곧 "검증 게이트 경유 여부" 심사다.
_WH1_PRIMARY_FLAG_ALLOWLIST: frozenset[str] = frozenset(
    {
        "config.py",  # 플래그 정의(기본 OFF — 봉인 ③ test_coach_gate3_serving_invariant 동결).
        "api/coach.py",  # 소비: 세션/턴 핸들러 게이트 + 결정론 폴백(_wh1_primary_decision_or).
    }
)
_WH1_PRIMARY_RUNNER_ALLOWLIST: frozenset[str] = frozenset(
    {
        "harness/wh1_primary.py",  # 정의 site: 하네스 실행 + 톤필터 + 관측(발화 산출 유일 좌석).
        "api/coach.py",  # 소비: 플래그 게이트 뒤 발화 교체(폴백 동반).
        "harness/wh1_session.py",  # docstring 참조만(활성화 보류 명문·비호출).
        # S4-04 측정 CLI — 결함주입 시험지를 *실제 서빙 경로 그대로* 태워 노출 0을 게이트한다.
        # 학생 노출 표면이 아니라 측정 하네스(hermetic·FakeProvider)이며, 우회 경로가 아니라
        # 봉인 대상 경로 자체를 측정하는 소비자라 의식적으로 등재한다(2026-07-21 리뷰).
        "harness/coach_prose_leak_eval.py",
        # P3-78 측정 CLI — AI 품질 평가 사례마다 *실제 서빙 러너 그대로*를 돌려 8축 평가기의
        # `--responses` 입력을 만든다. 산출은 평가 파일(`<out>`)뿐이라 학생 노출 표면이 아니며,
        # 러너 결과도 코치와 같이 승격 직전 재검증(`check_deliverable`)을 거친다. 봉인 대상 경로
        # 자체를 측정하는 소비자라 위 S4-04 측정 CLI와 같은 근거로 등재한다(P3-78 리뷰).
        "harness/ai_quality_live_collect.py",
        # PED-23(회수): 사후 가드 정본 모듈의 docstring 참조만(비호출) — mode_guard가 실제로
        # 호출되는 좌석은 여전히 `harness/wh1_primary.py` 톤필터 직전 1곳뿐이다(가드 배선 자체는
        # 그 안쪽 계층이라 새 학생 표면이 아님 — 봉인 ③의 취지(우회 배선 차단)와 무관).
        "l4/pedagogy/mode_guard.py",
    }
)
# 검증 게이트·톤필터 경유 마커 — wh1_primary.py가 이 둘을 잃으면 발화가 게이트를 우회한 것이다.
_WH1_PRIMARY_GATE_MARKERS: tuple[str, ...] = ("run_tutoring_turn", "filter_tone")


class TestGate3Wh1PrimarySurfaceSeal:
    """(E) flip 표면 봉인 — 허용 표면을 명시적 frozenset으로 동결(무제한 개방 금지)."""

    def test_wh1_primary_flag_consumer_set_frozen(self) -> None:
        """`wh1_primary_enabled` 사용 모듈 집합이 allowlist와 정확 일치(추가·누락 모두 red).

        게이트 ③ (E): 새 모듈이 flip 플래그를 소비하면 red — 그 리뷰가 곧 "그 경로도 검증
        게이트(verify 의무·정답 억제·톤필터·폴백)를 경유하는가" 심사다.
        """
        users = _module_users_of("wh1_primary_enabled")
        assert users == set(_WH1_PRIMARY_FLAG_ALLOWLIST), (
            "WH-1 primary 플래그 사용 모듈이 allowlist와 다릅니다 — 게이트 ③ (E). 발견: "
            f"{sorted(users)} / 허용: {sorted(_WH1_PRIMARY_FLAG_ALLOWLIST)}. 새 표면이라면 검증 "
            "게이트 경유를 확인하고 이 봉인을 함께 개정하라."
        )

    def test_wh1_primary_runner_caller_set_frozen(self) -> None:
        """`run_wh1_primary_turn` 사용 모듈 집합이 allowlist와 정확 일치.

        게이트 ③ (E): 발화 산출 러너를 다른 경로가 직접 소비하면 red — 플래그 게이트·폴백 없이
        LLM 발화가 학생 표면으로 새는 배선을 리뷰 시점에 잡는다.
        """
        users = _module_users_of("run_wh1_primary_turn")
        assert users == set(_WH1_PRIMARY_RUNNER_ALLOWLIST), (
            "WH-1 primary 러너 사용 모듈이 allowlist와 다릅니다 — 게이트 ③ (E). 발견: "
            f"{sorted(users)} / 허용: {sorted(_WH1_PRIMARY_RUNNER_ALLOWLIST)}."
        )

    def test_wh1_primary_module_keeps_verification_gate_markers(self) -> None:
        """`wh1_primary.py`가 하네스 루프·톤필터 마커를 유지 — 게이트 우회 재작성 차단.

        게이트 ③ (E): primary 발화는 `run_tutoring_turn`(verify 의무·정답 억제 소유)과
        `filter_tone`(정서 안전)을 반드시 경유한다. 두 마커가 소스에서 사라지면 발화 산출이
        게이트를 우회하도록 재작성된 것이므로 red.
        """
        source = (_PACKAGE_ROOT / "harness" / "wh1_primary.py").read_text(encoding="utf-8")
        for marker in _WH1_PRIMARY_GATE_MARKERS:
            assert marker in source, (
                f"harness/wh1_primary.py에서 검증 게이트 마커('{marker}')가 사라졌다 — primary "
                "발화가 하네스 검증/톤필터를 우회하면 게이트 ③ 위반이다."
            )


# ──────────────────────────────────────────────────────────────────────────
# (E-2) 코치 프로즈 계층 표면 봉인 — S4-04 (파생 템플릿 rephrase·정책 프로즈 게이트)
# ──────────────────────────────────────────────────────────────────────────
# S4-04는 (E)가 개방한 유일 표면(`harness/wh1_primary.py`) *안쪽*에 프로즈 계층을 얹는다 —
# 파생 템플릿은 정답-안전 게이트(등호·숫자·GT 유입 전면 차단·fail-closed) 통과분만 문맥화
# 노출되고, 정책 자유발화는 외래 등식·위생 게이트(실패=결정론 폴백)를 거친다. 아래 봉인은
# 이 계층의 소비 표면을 정확 일치로 동결한다 — 새 모듈이 프로즈 플래그·진입 함수를 소비하면
# red가 되고, 그 리뷰 시점이 곧 "게이트 사슬(프로즈→톤필터) 경유 여부" 심사다.
_WH1_PROSE_FLAG_ALLOWLIST: frozenset[str] = frozenset(
    {
        "config.py",  # 플래그 정의(기본 OFF canary — 봉인 ③ serving invariant가 False 동결).
        "harness/wh1_primary.py",  # 소비: 유일 표면 안쪽의 프로즈 계층 게이트.
        # P3-78 측정 CLI — 값을 실행 식별(`<out>.run.json`)에 *기록만* 한다(분기 0 · 발화 경로
        # 무관). 프로즈 ON/OFF가 측정된 발화를 바꾸므로 그 회차가 어느 설정이었는지 남기는 용도.
        "harness/ai_quality_live_collect.py",
    }
)
_WH1_PROSE_ENTRY_ALLOWLIST: frozenset[str] = frozenset(
    {
        "harness/wh1_prose.py",  # 정의 site: 게이트·rephrase(fail-closed) 소유.
        "harness/wh1_primary.py",  # 소비: seam(발화 확정 후·톤필터 직전) 유일 호출자.
    }
)
# 프로즈 계층 마커 — wh1_primary.py가 이 둘을 잃으면 프로즈 배선이 조용히 제거·우회된 것.
_WH1_PROSE_GATE_MARKERS: tuple[str, ...] = ("gate_policy_prose", "rephrase_coach_utterance")


class TestGate3Wh1ProseSurfaceSeal:
    """(E-2) 프로즈 계층 표면 봉인 — 소비 표면을 명시적 frozenset으로 동결(S4-04)."""

    def test_wh1_prose_flag_consumer_set_frozen(self) -> None:
        """`wh1_prose_rephrase_enabled` 사용 모듈 집합이 allowlist와 정확 일치."""
        users = _module_users_of("wh1_prose_rephrase_enabled")
        assert users == set(_WH1_PROSE_FLAG_ALLOWLIST), (
            "프로즈 rephrase 플래그 사용 모듈이 allowlist와 다릅니다 — 게이트 ③ (E-2). 발견: "
            f"{sorted(users)} / 허용: {sorted(_WH1_PROSE_FLAG_ALLOWLIST)}. 새 표면이라면 게이트 "
            "사슬(정답-안전 게이트→톤필터) 경유를 확인하고 이 봉인을 함께 개정하라."
        )

    def test_wh1_prose_entry_caller_set_frozen(self) -> None:
        """프로즈 진입 함수(`rephrase_coach_utterance`) 사용 모듈 집합이 allowlist와 정확 일치."""
        users = _module_users_of("rephrase_coach_utterance")
        assert users == set(_WH1_PROSE_ENTRY_ALLOWLIST), (
            "프로즈 rephrase 진입 함수 사용 모듈이 allowlist와 다릅니다 — 게이트 ③ (E-2). 발견: "
            f"{sorted(users)} / 허용: {sorted(_WH1_PROSE_ENTRY_ALLOWLIST)}."
        )

    def test_wh1_primary_module_keeps_prose_markers(self) -> None:
        """`wh1_primary.py`가 프로즈 계층 마커(정책 게이트·rephrase)를 유지 — 조용한 제거 차단."""
        source = (_PACKAGE_ROOT / "harness" / "wh1_primary.py").read_text(encoding="utf-8")
        for marker in _WH1_PROSE_GATE_MARKERS:
            assert marker in source, (
                f"harness/wh1_primary.py에서 프로즈 계층 마커('{marker}')가 사라졌다 — S4-04 "
                "정답-안전 게이트가 조용히 제거·우회되면 안 된다(개정은 이 봉인과 함께)."
            )
