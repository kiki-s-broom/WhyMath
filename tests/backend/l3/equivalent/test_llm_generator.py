"""실 LLM 동등문제 생성기(S2-e `llm_generator.py`) — hermetic 단위·통합(FakeProvider·라이브 0).

FakeProvider(스크립트된 JSON)로 생성기 계약을 검증한다 — 실 네트워크·직접 LLM 호출 0.
검증 축:
  ① 정상 JSON → CandidateProblem 조립(source_type 자체생성·provenance WHYMATH_GENERATED·
     conditions/answer_map 정합).
  ② 그 후보가 S2-a 게이트 통과(evaluate_equivalent_candidate accepted=True) — 생성기→게이트 결선.
  ③ 깨진 JSON·필수 결측·미지 오개념 id → 안전 폴백(None 또는 드롭).
  ④ provider 예외 → None(크래시 금지).
  ⑤ 저작권: 응답에 평가원 운운해도 provenance는 자체생성·WHYMATH_GENERATED로 구조적 고정.
  ⑥ 오케스트레이터 결선: run_equivalent_generation(spec, LLMEquivalentProblemGenerator(fake))
     → accepted(dry-run)·accepted_stored(fake store) — S2-d와 실제로 이어짐.

주의: 이 테스트는 tests/ 아래라 import-linter 계약 밖 → L4 `CATALOG_BY_ID`를 자유롭게 주입한다
(생성기 본체는 L3라 L4를 import하지 않고 카탈로그를 *주입*받는다 — 레이어 순수성).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence

import pytest

from whymath_backend.l1.problem_bank.populate import (
    ProblemBankPopulateReport,
    ProblemBankRecord,
)
from whymath_backend.l3.equivalent import llm_generator
from whymath_backend.l3.equivalent.acceptance import (
    EquivalenceSpec,
    evaluate_equivalent_candidate,
)
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.models import (
    GenerationResult,
    LocalModelTier,
    ModelFamily,
    RoutingDecision,
    Usage,
)
from whymath_backend.l3.prompt_assets import prompt_text
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.schema.enums import AnswerFormat, LicenseType, SourceType

# S2-d 오케스트레이터 테스트와 동일한 대응 스펙(전 게이트 통과 기준).
_STANDARD = "[12미적01-01]"
_MISCONCEPTION = "distribution-over-power"  # 실 카탈로그 id
_CATALOG = {mid: m.name_kr for mid, m in CATALOG_BY_ID.items()}

# 정상 응답 JSON — 두 근 2·3 중 큰 근 3. answer_selection=largest로 근 선택(S2-i)을 명시해
# Tier1 pass + 근 선택 확정 → verified. 발문·해설은 위생-청정(거짓 등식 0).
_HAPPY = json.dumps(
    {
        "question_text": "이차방정식 x^2 - 5x + 6 = 0 의 두 근 중 큰 근을 구하시오.",
        "answer": "3",
        "answer_explanation": "인수분해하면 (x-2)(x-3)=0, 두 근은 2와 3, 큰 근은 3.",
        "conditions": "x**2 - 5*x + 6 = 0",
        "answer_map": {"x": "3"},
        "answer_selection": "largest",
        "difficulty_overall": 3.0,
        "unit_codes": ["CAL-INT-DEF"],
        "answer_format": "자연수",
        "achievement_standard_codes": [_STANDARD],
        "distractor_map": [{"choice_index": 1, "misconception_id": _MISCONCEPTION}],
        "concept_tags": [{"concept_src_id": "HK06", "role": "PRIMARY", "relevance": 0.9}],
    },
    ensure_ascii=False,
)


# ──────────────────────────────────────────────────────────────────────
# provider 대역 — 스크립트 JSON / 예외 (LLMTutorPolicy 테스트 미러·라이브 0).
# ──────────────────────────────────────────────────────────────────────
class FakeProvider:
    """스크립트된 응답을 순서대로 방출하는 L3 provider 대역 — LLMProvider 충족(네트워크 0).

    S2-g: `temperature`를 캡처해 생성기가 고온도(다양성)로 호출하는지 검증한다.
    """

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self.temperatures: list[float | None] = []
        self.decisions: list[RoutingDecision] = []
        self.json_schemas: list[Mapping[str, object] | None] = []
        self.loops: list[object] = []
        # EOS-121 A — 받은 키워드 인자를 **그대로** 보관한다. 파라미터 기본값으로만 받으면
        # "안 왔다"와 "None이 왔다"가 둘 다 None으로 보여 기본값 회귀를 못 잡는다.
        self.call_kwargs: list[dict[str, object]] = []

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        **kwargs: object,
    ) -> GenerationResult:
        self.calls.append((prompt, system))
        temperature = kwargs.get("temperature")
        self.temperatures.append(temperature if isinstance(temperature, float) else None)
        self.decisions.append(decision)
        schema = kwargs.get("json_schema")
        self.json_schemas.append(schema if isinstance(schema, Mapping) else None)
        self.call_kwargs.append(dict(kwargs))
        self.loops.append(asyncio.get_running_loop())
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult("{}")  # 소진 시 빈 객체(필수 결측 → 생성 실패)


class RaisingProvider:
    """generate가 항상 예외를 던지는 provider 대역 — provider 장애 안전 폴백 검증용."""

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        raise RuntimeError("provider 다운(테스트)")


def _spec(**overrides: object) -> EquivalenceSpec:
    kwargs: dict[str, object] = {
        "achievement_standard_codes": frozenset({_STANDARD}),
        "target_misconception_ids": frozenset({_MISCONCEPTION}),
        "difficulty_overall": 3.0,
        "answer_format": AnswerFormat.자연수,
    }
    kwargs.update(overrides)
    return EquivalenceSpec(**kwargs)  # type: ignore[arg-type]


def _gen(provider: object, **overrides: object) -> LLMEquivalentProblemGenerator:
    kwargs: dict[str, object] = {"misconception_catalog": _CATALOG}
    kwargs.update(overrides)
    return LLMEquivalentProblemGenerator(provider, **kwargs)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# top_p (EOS-121 선결조건 A) — 기본은 미전송, 명시할 때만 실린다.
# ──────────────────────────────────────────────────────────────────────
class TestTopP:
    def test_default_does_not_send_top_p(self) -> None:
        """기본값 None → provider 호출에 top_p **키 자체가 없다**(기존 저작 동작 무변경).

        이것이 이 인자의 핵심 제약이다: 생성기가 기본으로 top_p를 실으면 기존 저작 배치
        전부의 샘플링이 공급사 기본값에서 *조용히* 바뀐다(회귀). 회귀는 예외도 로그도 남기지
        않으므로 이 단언이 유일한 방어선이다.
        """
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        assert "top_p" not in provider.call_kwargs[0]
        assert provider.temperatures == [0.9]  # 온도 축은 종전 그대로

    def test_explicit_top_p_is_passed_through(self) -> None:
        """명시 지정 → provider 호출에 **그 값 그대로** 실린다(양 좌석 통제의 손잡이)."""
        provider = FakeProvider([_HAPPY])
        _gen(provider, top_p=0.95).generate(_spec())
        assert provider.call_kwargs[0]["top_p"] == 0.95

    def test_top_p_does_not_disturb_seed_or_schema_slots(self) -> None:
        """top_p가 실려도 나머지 선택 인자의 규약(값 있을 때만)이 그대로다.

        `_invoke`가 인자들을 한 dict에 모아 넘기므로 그 자리에서 다른 축을 덮는 회귀가
        가능하다 — LOCAL 결정이면 json_schema는 실리고 seed는 호출부가 안 줬으니 없어야 한다.
        """
        provider = FakeProvider([_HAPPY])
        _gen(provider, top_p=0.95).generate(_spec())
        kwargs = provider.call_kwargs[0]
        assert kwargs["top_p"] == 0.95
        assert kwargs["temperature"] == 0.9
        assert "json_schema" in kwargs  # LOCAL 경로 — 스키마 좌석 보존


# ──────────────────────────────────────────────────────────────────────
# ① 정상 JSON → CandidateProblem 조립.
# ──────────────────────────────────────────────────────────────────────
class TestAssembly:
    def test_happy_json_assembles_candidate(self) -> None:
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert isinstance(candidate, CandidateProblem)
        # 저작권 메타는 구조적으로 고정(LLM 무관).
        assert candidate.problem.source_type == SourceType.자체생성
        assert candidate.provenance.license == LicenseType.WHYMATH_GENERATED
        # 검산 재료 정합.
        assert candidate.conditions == "x**2 - 5*x + 6 = 0"
        assert candidate.answer_map == {"x": "3"}
        assert candidate.answer_selection == "largest"  # 근 선택(S2-i) 파싱
        assert candidate.problem.question_text == json.loads(_HAPPY)["question_text"]
        assert candidate.problem.answer == "3"

    def test_slug_is_stable_and_deterministic(self) -> None:
        c1 = _gen(FakeProvider([_HAPPY])).generate(_spec())
        c2 = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert c1 is not None and c2 is not None
        assert c1.problem.slug == c2.problem.slug  # 같은 내용 → 같은 slug(멱등 upsert 키)
        assert c1.problem.slug is not None and c1.problem.slug.startswith("wm-gen-")

    def test_latex_backslash_in_response_still_parses(self) -> None:
        # 실 LLM(Phaiakes9 qwen2-math:7b) 실측 회귀 — 발문에 LaTeX `\(`·`\)`가 있어
        # `json.loads`가 "Invalid \escape"로 실패하던 케이스. sanitize 폴백이 구제해야 한다.
        raw = (
            '{\n  "question_text": "이차방정식 \\( x^2 - 5x + 6 = 0 \\)의 해는?",\n'
            '  "answer": "3",\n  "conditions": "x**2 - 5*x + 6 = 0",\n'
            '  "answer_map": {"x": "3"},\n  "unit_codes": ["QUAD-EQ"]\n}'
        )
        candidate = _gen(FakeProvider([raw])).generate(_spec())
        assert candidate is not None  # 파싱 구제(None 폴백 아님)
        assert candidate.answer_map == {"x": "3"}
        assert candidate.conditions == "x**2 - 5*x + 6 = 0"
        assert "\\(" in candidate.problem.question_text  # LaTeX는 보존(파싱만 구제)

    def test_concept_tags_parsed(self) -> None:
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert candidate is not None
        assert candidate.concept_tags[0].concept_src_id == "HK06"
        assert candidate.concept_tags[0].role == "PRIMARY"

    def test_distractor_maps_known_misconception(self) -> None:
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert candidate is not None
        assert candidate.problem.distractor_map is not None
        assert candidate.problem.distractor_map[0].misconception_id == _MISCONCEPTION

    def test_authored_solution_steps_are_dropped(self) -> None:
        # S2-k: 모델이 산문 solution_steps를 내도 후보엔 싣지 않는다(Tier2 심볼릭 체인이 아님).
        # 답 정확성은 Tier1+근 선택이 확정하고, 설명은 answer_explanation 소관.
        payload = json.loads(_HAPPY)
        payload["solution_steps"] = [
            "인수분해하면 (x-2)(x-3)=0",
            "두 근은 2와 3",
            "큰 근은 3",
        ]
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.solution_steps is None

    def test_gate_verifies_without_tier2_downgrade(self) -> None:
        # S2-k 회귀 봉인 — 정답 큰-근 문제가 산문 단계 때문에 검수필요로 강등되지 않는다.
        payload = json.loads(_HAPPY)
        payload["solution_steps"] = ["인수분해하면 (x-2)(x-3)=0", "큰 근은 3"]  # 산문
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        verdict = evaluate_equivalent_candidate(
            _spec(),
            candidate.problem,
            provenance=candidate.provenance,
            conditions=candidate.conditions,
            answer_map=candidate.answer_map,
            answer_selection=candidate.answer_selection,
            solution_steps=candidate.solution_steps,
        )
        assert verdict.verification == "verified"
        assert verdict.accepted is True

    def test_spec_not_leaked_verbatim_but_ids_present(self) -> None:
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        prompt, system = provider.calls[0]
        # 프롬프트는 저작권 금기를 명시하고, 스펙 성취기준·오개념 id를 싣는다(Minimal context).
        assert "복제" in system
        assert _STANDARD in prompt
        assert _MISCONCEPTION in prompt

    def test_topic_hint_injected_into_prompt(self) -> None:
        # S2-f: 성취기준 코드만으론 모델이 주제를 못 맞히므로(이차 요청에 일차 생성) topic_hint를
        # 프롬프트에 실어 코드→주제를 사람이 번역해 준다. 주입 시 유저 프롬프트에 나타나야 한다.
        provider = FakeProvider([_HAPPY])
        _gen(provider, topic_hint="이차방정식 — 두 근 중 큰 근").generate(_spec())
        prompt, _ = provider.calls[0]
        assert "이차방정식 — 두 근 중 큰 근" in prompt

    def test_system_prompt_requires_single_answer_and_forbids_placeholders(
        self,
    ) -> None:
        # S2-f: 답 하나로 정해지게(이차 검증 가능) + 플레이스홀더 베끼기 금지 지시가 시스템에 있다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        _, system = provider.calls[0]
        assert "하나로" in system  # 답 유일성 지시
        assert "플레이스홀더" in system  # 예시 텍스트 베끼기 금지


# ──────────────────────────────────────────────────────────────────────
# S2-g: 생성 다양성 — 고온도 호출 + 프롬프트 다양성 지시.
# ──────────────────────────────────────────────────────────────────────
class TestGenerationDiversity:
    def test_generator_calls_provider_with_default_high_temperature(self) -> None:
        # 튜터링(결정론)과 달리 동등문제 저작은 다양성이 목표 → 기본 0.9 고온도로 호출한다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        assert provider.temperatures == [0.9]

    def test_temperature_override_is_forwarded(self) -> None:
        # 생성자 override 값이 그대로 provider.generate(temperature=)로 전달된다.
        provider = FakeProvider([_HAPPY])
        _gen(provider, temperature=1.1).generate(_spec())
        assert provider.temperatures == [1.1]

    def test_system_prompt_instructs_diversity(self) -> None:
        # 매번 다른 문제·계수/상수/물음/근의 종류 다양화·반복 금지 지시가 시스템 프롬프트에 있다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        _, system = provider.calls[0]
        assert "다른 문제" in system  # 매번 다른 문제
        assert "반복하지 마세요" in system  # 직전 구조 반복 금지
        assert "근의 종류" in system  # 근의 종류 다양화


# ──────────────────────────────────────────────────────────────────────
# S2-j: structured output — LOCAL 결정이면 출력 JSON 스키마를 실어 문법 강제.
# ──────────────────────────────────────────────────────────────────────
class TestStructuredOutput:
    def test_local_decision_sends_json_schema(self) -> None:
        # free·예산0 → 라우터가 LOCAL 결정 → 스키마가 provider로 실린다(Ollama format= 제약).
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        schema = provider.json_schemas[0]
        assert schema is not None
        assert schema["type"] == "object"

    def test_schema_requires_hard_fields(self) -> None:
        # 결측 시 생성 실패가 되는 필수 필드 + answer_selection(S2-k 강제)이 required로 문법 강제.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        schema = provider.json_schemas[0]
        assert schema is not None
        required = schema["required"]
        assert isinstance(required, list)
        for field in (
            "question_text",
            "answer",
            "conditions",
            "answer_map",
            "answer_selection",
            "unit_codes",
        ):
            assert field in required

    def test_schema_omits_solution_steps(self) -> None:
        # S2-k: 저작 산문은 Tier2 심볼릭 체인이 아니므로 스키마가 solution_steps를 유도하지 않는다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        schema = provider.json_schemas[0]
        assert schema is not None
        props = schema["properties"]
        assert isinstance(props, dict)
        assert "solution_steps" not in props

    def test_schema_constrains_enums(self) -> None:
        # answer_selection(S2-i)·answer_format이 enum으로 문법 제약된다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        schema = provider.json_schemas[0]
        assert schema is not None
        props = schema["properties"]
        assert isinstance(props, dict)
        assert props["answer_selection"]["enum"] == ["largest", "smallest", "unique"]
        assert "자연수" in props["answer_format"]["enum"]

    def test_lenient_parser_still_backstops(self) -> None:
        # 스키마 강제와 무관하게 관대 파서는 유지된다(이중 방어) — 코드펜스 응답도 구제.
        fenced = f"```json\n{_HAPPY}\n```"
        candidate = _gen(FakeProvider([fenced])).generate(_spec())
        assert candidate is not None


# ──────────────────────────────────────────────────────────────────────
# 배치 동기 경계 — 전 회차가 같은 살아있는 이벤트 루프를 공유(격회 실패 회귀 봉인).
# ──────────────────────────────────────────────────────────────────────
class TestBatchEventLoopReuse:
    def test_repeated_generates_share_one_living_loop(self) -> None:
        # 실측 회귀(Phaiakes9 run_batch): asyncio.run이 호출마다 루프를 닫아 provider의 캐시
        # 커넥션 풀이 죽은 루프에 묶임 → "Event loop is closed" 격회 실패. 같은 생성기의 연속
        # 호출은 *같은 살아있는 루프*를 재사용해야 한다.
        provider = FakeProvider([_HAPPY, _HAPPY, _HAPPY])
        gen = _gen(provider)
        for _ in range(3):
            gen.generate(_spec())
        assert len(provider.loops) == 3
        assert len(set(map(id, provider.loops))) == 1  # 세 호출 모두 동일 루프
        loop = provider.loops[0]
        assert isinstance(loop, asyncio.AbstractEventLoop)
        assert not loop.is_closed()  # 호출 후에도 살아 있음(커넥션 풀 유지)


# ──────────────────────────────────────────────────────────────────────
# S2-m: condition DSL 폐쇄 — pseudo-symbolic 조건은 조립 거부(생성 실패·재생성).
# ──────────────────────────────────────────────────────────────────────
class TestConditionDslClosure:
    def test_undefined_function_condition_rejected(self) -> None:
        # 실측 회귀: conditions에 'largest_root(2, 8) == 8' — 검증 불가 pseudo-DSL → None.
        payload = json.loads(_HAPPY)
        payload["conditions"] = ["x**2 - 5*x + 6 = 0", "largest_root(2, 8) == 8"]
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_solve_pseudo_dsl_rejected(self) -> None:
        payload = json.loads(_HAPPY)
        payload["conditions"] = "solve(x**2 - 5*x + 6, x) == [2, 3]"
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_python_syntax_condition_rejected(self) -> None:
        payload = json.loads(_HAPPY)
        payload["conditions"] = "x**2 - 8*x + answer_map['k'] = 0"
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_plain_equation_still_assembles(self) -> None:
        # 적법한 맨 등식은 종전대로 조립(회귀 0).
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert candidate is not None

    def test_system_prompt_forbids_pseudo_dsl(self) -> None:
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        _, system = provider.calls[0]
        assert "solve(" in system  # 금지 예시 명시
        assert "largest_root(" in system


# ──────────────────────────────────────────────────────────────────────
# S2-n: derive-and-verify — 근 선택 문제는 정답을 유도해 대조·정확값 정규화.
# ──────────────────────────────────────────────────────────────────────
class TestDeriveAndVerify:
    def test_wrong_root_rejected_at_assembly(self) -> None:
        # 실측 회귀: 2x²-7x+3=0 큰 근은 3인데 모델이 3.5 — 유도 정답과 불일치 → 조립 거부(None).
        payload = json.loads(_HAPPY)
        payload["conditions"] = "2*x**2 - 7*x + 3 = 0"
        payload["answer_map"] = {"x": "3.5"}
        payload["answer"] = "3.5"
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_rounded_decimal_rejected(self) -> None:
        # 반올림 소수(1.33 vs 4/3) — 대입 잔차가 0이 아니게 되는 부정확 답 → 조립 거부.
        payload = json.loads(_HAPPY)
        payload["conditions"] = "3*x**2 - 7*x + 4 = 0"
        payload["answer_map"] = {"x": "1.33"}
        payload["answer"] = "1.33"
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_float_representation_normalized_to_exact(self) -> None:
        # 부동소수 표기(1.3333…)는 유도 정확값 '4/3'으로 정규화 — display·검산 모두 canonical.
        payload = json.loads(_HAPPY)
        payload["conditions"] = "3*x**2 - 7*x + 4 = 0"
        payload["answer_map"] = {"x": "1.3333333333333333"}
        payload["answer"] = "1.3333333333333333"
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_map == {"x": "4/3"}
        assert candidate.problem.answer == "4/3"

    def test_exact_answer_stays_and_gate_accepts(self) -> None:
        # 이미 정확값이면 그대로(4/3→4/3) + 게이트 verified·accepted(정규화가 검산을 돕는다).
        payload = json.loads(_HAPPY)
        payload["conditions"] = "3*x**2 - 7*x + 4 = 0"
        payload["answer_map"] = {"x": "4/3"}
        payload["answer"] = "1.333"
        payload["answer_format"] = "분수"
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_map == {"x": "4/3"}
        assert candidate.problem.answer == "4/3"  # display도 canonical로 정규화
        verdict = evaluate_equivalent_candidate(
            _spec(answer_format=AnswerFormat.분수),
            candidate.problem,
            provenance=candidate.provenance,
            conditions=candidate.conditions,
            answer_map=candidate.answer_map,
            answer_selection=candidate.answer_selection,
        )
        assert verdict.verification == "verified"

    def test_underivable_passes_through_to_gate(self) -> None:
        # 유도 불가(선택 없음)면 무변경 통과 — 게이트가 기존 규약대로 판정(보수적).
        payload = json.loads(_HAPPY)
        del payload["answer_selection"]
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_map == {"x": "3"}  # 무변경


# ──────────────────────────────────────────────────────────────────────
# S2-i: 근 선택(answer_selection) 파싱 + 프롬프트 지시.
# ──────────────────────────────────────────────────────────────────────
class TestRootSelectionParsing:
    def test_answer_selection_parsed(self) -> None:
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_selection == "largest"

    def test_missing_answer_selection_is_none(self) -> None:
        payload = json.loads(_HAPPY)
        del payload["answer_selection"]
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_selection is None

    def test_invalid_answer_selection_dropped_to_none(self) -> None:
        payload = json.loads(_HAPPY)
        payload["answer_selection"] = "biggest"  # 미지 값 — 조용히 None으로 떨군다.
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        assert candidate.answer_selection is None

    def test_system_prompt_instructs_answer_selection(self) -> None:
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        _, system = provider.calls[0]
        assert "answer_selection" in system
        assert "largest" in system


# ──────────────────────────────────────────────────────────────────────
# S2-h: 저작용 로컬 패밀리 — 기본 GENERAL(qwen2.5)로 라우팅(qwen2-math mode collapse 회피).
# ──────────────────────────────────────────────────────────────────────
class TestAuthoringFamily:
    def test_default_routes_local_generation_to_general_family(self) -> None:
        # 라우터는 task_type='generate'를 MATH로 보내지만, 저작은 GENERAL이 낫다 →
        # 기본값이 GENERAL로 로컬 저작 패밀리를 갈아탄다(free·예산0 → 라우터가 LOCAL 결정).
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        decision = provider.decisions[0]
        assert decision.cost_tier == "local"  # free·예산0 → 로컬 확정
        assert decision.local_family == ModelFamily.GENERAL.value  # MATH가 아니라 GENERAL
        assert decision.local_model in (
            LocalModelTier.FAST.value,
            LocalModelTier.MID.value,
        )

    def test_medium_difficulty_uses_general_mid_qwen25_7b(self) -> None:
        # medium 난이도(기본 스펙 3.0) → 라우터가 MID를 고르고, 패밀리는 GENERAL로 갈아탄다
        # ⇒ (GENERAL, MID) = qwen2.5:7b(저작용 최적 로컬 모델).
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        decision = provider.decisions[0]
        assert decision.local_family == ModelFamily.GENERAL.value
        assert decision.local_model == LocalModelTier.MID.value

    def test_opt_out_keeps_router_default_math_family(self) -> None:
        # authoring_family=None이면 라우터 결정을 그대로 쓴다(옵트아웃) → MATH 유지.
        provider = FakeProvider([_HAPPY])
        _gen(provider, authoring_family=None).generate(_spec())
        decision = provider.decisions[0]
        assert decision.local_family == ModelFamily.MATH.value

    def test_explicit_math_family_override_is_honored(self) -> None:
        # 명시적으로 MATH를 요청하면 그대로 MATH(선호를 강제하지 않고 존중).
        provider = FakeProvider([_HAPPY])
        _gen(provider, authoring_family=ModelFamily.MATH).generate(_spec())
        assert provider.decisions[0].local_family == ModelFamily.MATH.value


# ──────────────────────────────────────────────────────────────────────
# MP-02 재회차: routing_sync=False → 라우터 규칙 2가 로컬 QUALITY 티어를 고른다.
# ──────────────────────────────────────────────────────────────────────
class TestRoutingSync:
    def test_default_sync_keeps_general_mid(self) -> None:
        """기본값(True)은 종전 결정과 같다 — 대조군(이게 깨지면 기본 회귀)."""
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        decision = provider.decisions[0]
        assert decision.local_model == LocalModelTier.MID.value
        assert decision.local_family == ModelFamily.GENERAL.value

    def test_async_routes_to_local_quality_tier(self) -> None:
        """False면 QUALITY·패밀리 무관(None)·로컬 유지 — 클라우드로 새지 않는다."""
        provider = FakeProvider([_HAPPY])
        _gen(provider, routing_sync=False).generate(_spec())
        decision = provider.decisions[0]
        assert decision.cost_tier == "local"
        assert decision.local_model == LocalModelTier.QUALITY.value
        assert decision.local_family is None  # QUALITY는 패밀리 무관(불변식 4)

    def test_async_quality_resolves_to_router_quality_model(self) -> None:
        """실제 모델 ID는 라우터 표가 정한다 — 생성기에 하드코딩이 없다."""
        from whymath_backend.l3.router import QUALITY_MODEL_ID, resolve_model

        provider = FakeProvider([_HAPPY])
        _gen(provider, routing_sync=False).generate(_spec())
        decision = provider.decisions[0]
        assert resolve_model(decision.local_family, decision.local_model) == QUALITY_MODEL_ID

    def test_family_override_still_assembles_candidate(self) -> None:
        # 패밀리 갈아타기가 결정을 깨지 않고(불변식 4 유지) 후보 조립이 정상 동작한다.
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert isinstance(candidate, CandidateProblem)


# ──────────────────────────────────────────────────────────────────────
# ② 생성기 → S2-a 게이트 결선(accepted=True).
# ──────────────────────────────────────────────────────────────────────
class TestGatePasses:
    def test_generated_candidate_passes_acceptance_gate(self) -> None:
        candidate = _gen(FakeProvider([_HAPPY])).generate(_spec())
        assert candidate is not None
        verdict = evaluate_equivalent_candidate(
            _spec(),
            candidate.problem,
            provenance=candidate.provenance,
            conditions=candidate.conditions,
            answer_map=candidate.answer_map,
            answer_selection=candidate.answer_selection,  # 근 선택(S2-i) 결선
            solution_steps=candidate.solution_steps,
        )
        assert verdict.accepted is True
        assert verdict.copyright_ok is True
        assert verdict.verification == "verified"
        assert verdict.equivalence == "동치후보"


# ──────────────────────────────────────────────────────────────────────
# ③ 깨진 JSON·필수 결측·미지 오개념 → 안전 폴백(None 또는 드롭).
# ──────────────────────────────────────────────────────────────────────
class TestSafeFallback:
    def test_broken_json_returns_none(self) -> None:
        assert _gen(FakeProvider(["이건 JSON이 아니다 {{{"])).generate(_spec()) is None

    def test_missing_required_field_returns_none(self) -> None:
        payload = json.loads(_HAPPY)
        del payload["question_text"]
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_missing_conditions_returns_none(self) -> None:
        payload = json.loads(_HAPPY)
        del payload["conditions"]  # 정확성 검산 재료 결측
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_unknown_misconception_is_dropped(self) -> None:
        payload = json.loads(_HAPPY)
        payload["distractor_map"] = [
            {"choice_index": 1, "misconception_id": "totally-unknown-xyz-오개념"}
        ]
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        # 후보는 조립되지만 미지 오개념은 드롭 → distractor_map None(조용한 채택 금지).
        assert candidate is not None
        assert candidate.problem.distractor_map is None

    def test_missing_unit_codes_without_fallback_returns_none(self) -> None:
        payload = json.loads(_HAPPY)
        del payload["unit_codes"]
        assert _gen(FakeProvider([json.dumps(payload)])).generate(_spec()) is None

    def test_missing_unit_codes_with_fallback_assembles(self) -> None:
        payload = json.loads(_HAPPY)
        del payload["unit_codes"]
        gen = _gen(FakeProvider([json.dumps(payload)]), fallback_unit_codes=["CAL-INT-DEF"])
        candidate = gen.generate(_spec())
        assert candidate is not None
        assert candidate.problem.unit_codes == ["CAL-INT-DEF"]


# ──────────────────────────────────────────────────────────────────────
# ④ provider 예외 → None.
# ──────────────────────────────────────────────────────────────────────
class TestProviderFailure:
    def test_provider_exception_returns_none(self) -> None:
        assert _gen(RaisingProvider()).generate(_spec()) is None


# ──────────────────────────────────────────────────────────────────────
# ⑤ 저작권 구조적 강제 — 응답이 평가원 운운해도 provenance 고정.
# ──────────────────────────────────────────────────────────────────────
class TestCopyrightStructuralForcing:
    def test_source_claim_in_response_is_ignored(self) -> None:
        payload = json.loads(_HAPPY)
        payload["question_text"] = (
            "평가원 2024 수능 기출을 참고한 이차 방정식의 자연수 근을 구하시오."
        )
        payload["source_type"] = "평가원"  # LLM이 출처를 주장해도 코드가 읽지 않는다
        payload["license"] = "EBS_LICENSED"
        candidate = _gen(FakeProvider([json.dumps(payload)])).generate(_spec())
        assert candidate is not None
        # 구조적 강제 — 자체생성·WHYMATH_GENERATED로 고정(LLM 출처 주장 무시).
        assert candidate.problem.source_type == SourceType.자체생성
        assert candidate.provenance.license == LicenseType.WHYMATH_GENERATED
        # provenance original_source는 None(본문성 키 0).
        assert candidate.provenance.original_source is None


# ──────────────────────────────────────────────────────────────────────
# ⑥ 오케스트레이터 결선(S2-d와 실제 연결).
# ──────────────────────────────────────────────────────────────────────
class _FakeStore:
    """`ProblemBankSink` 구조 호환 fake — populate 호출·레코드 캡처(실 DB 0)."""

    def __init__(self) -> None:
        self.calls: list[list[ProblemBankRecord]] = []

    def populate(self, records: list[ProblemBankRecord]) -> ProblemBankPopulateReport:
        self.calls.append(list(records))
        return ProblemBankPopulateReport(
            problems_loaded=len(records),
            problem_concepts_loaded=sum(len(r.concept_tags) for r in records),
            concepts_skipped=0,
            skipped_messages=[],
        )


class TestOrchestratorWiring:
    def test_dry_run_accepted_through_orchestrator(self) -> None:
        gen = _gen(FakeProvider([_HAPPY]))
        outcome = run_equivalent_generation(_spec(), gen)
        assert outcome.status == "accepted"
        assert outcome.acceptance is not None and outcome.acceptance.accepted is True
        assert outcome.stored_problem_id is None

    def test_accepted_stored_through_orchestrator(self) -> None:
        gen = _gen(FakeProvider([_HAPPY]))
        store = _FakeStore()
        outcome = run_equivalent_generation(_spec(), gen, store=store)
        assert outcome.status == "accepted_stored"
        assert outcome.stored_problem_id is not None
        assert len(store.calls) == 1
        (records,) = store.calls
        assert records[0].slug is not None and records[0].slug.startswith("wm-gen-")

    def test_generation_failure_through_orchestrator(self) -> None:
        # provider 예외 → 생성기 None → 오케스트레이터 generation_failed(정직 처리).
        outcome = run_equivalent_generation(_spec(), _gen(RaisingProvider()))
        assert outcome.status == "generation_failed"


# 라이브 LLM 호출이 이 파일에 없음을 문서화(FakeProvider·RaisingProvider만).
def test_no_live_provider_used() -> None:
    assert not hasattr(FakeProvider, "_live")
    with pytest.raises(RuntimeError):
        # RaisingProvider가 실제로 예외를 던지는지(=라이브 아님) 확인.
        import asyncio

        asyncio.run(
            RaisingProvider().generate(
                "p",
                "s",
                RoutingDecision(cost_tier="cloud_mid", est_latency_ms=0),  # type: ignore[arg-type]
            )
        )


# ──────────────────────────────────────────────────────────────────────
# ⑨ 관측(TraceSink) 주입 — 코퍼스 저작 호출의 Langfuse 추적(2026-07-21 정합성 검토 보정).
# ──────────────────────────────────────────────────────────────────────
class _SpyTraceSink:
    """record/flush를 세는 스파이 — LangfuseSink 자리(cost_probe _SpySink 동형)."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.flush_count = 0

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)

    def flush(self) -> None:
        self.flush_count += 1


class _CrashingTraceSink:
    """record가 항상 던지는 sink — 관측 장애 never-break 검증용."""

    def record(self, fields: dict[str, object]) -> None:
        raise RuntimeError("sink 다운(테스트)")


class _UsageProvider:
    """usage(실측 토큰·지연)를 채워 돌려주는 provider 대역 — 비용 회계 배선 검증용."""

    def __init__(self, response: str) -> None:
        self._response = response

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,  # EOS-73 — LLMProvider 계약 정합(대역은 시드를 쓰지 않는다)
    ) -> GenerationResult:
        return GenerationResult(
            self._response,
            usage=Usage(input_tokens=120, output_tokens=45, latency_ms=88.0),
        )


class TestTraceSinkInjection:
    def test_success_records_one_langfuse_fields(self) -> None:
        """정상 생성 1건 → record 1건 — 라우팅 태그·cache_hit=False가 실린다."""
        spy = _SpyTraceSink()
        candidate = _gen(FakeProvider([_HAPPY]), trace=spy).generate(_spec())
        assert candidate is not None
        assert len(spy.records) == 1
        fields = spy.records[0]
        assert fields["cache_hit"] is False
        assert fields["cost_tier"] is not None  # 라우터 결정이 그대로 실린다
        # FakeProvider는 usage 미계측 — 실측 키는 None으로 정직하게 남는다(지어내지 않음).
        assert fields["input_tokens"] is None
        assert fields["cost_krw"] is None
        assert fields["student_id_hash"] is None  # 오프라인 저작 — 학생 무관

    def test_usage_flows_to_trace_with_local_zero_cost(self) -> None:
        """usage가 있으면 실측 토큰·지연이 흐르고, 로컬 결정은 실측 비용 0원 확정."""
        spy = _SpyTraceSink()
        candidate = _gen(_UsageProvider(_HAPPY), trace=spy).generate(_spec())
        assert candidate is not None
        fields = spy.records[0]
        assert fields["input_tokens"] == 120
        assert fields["output_tokens"] == 45
        assert fields["latency_ms"] == 88.0
        assert fields["cost_krw"] == 0.0  # free 구독 → LOCAL 라우팅 → 실측 0원 확정

    def test_parse_failure_still_records_call(self) -> None:
        """JSON 파싱 실패로 None 폴백이어도 LLM 호출은 성공·비용 발생 — record는 남는다."""
        spy = _SpyTraceSink()
        candidate = _gen(FakeProvider(["JSON이 아닌 산문 응답"]), trace=spy).generate(_spec())
        assert candidate is None  # 생성은 정직한 실패
        assert len(spy.records) == 1  # 그래도 호출 비용 관측은 기록

    def test_provider_failure_records_nothing(self) -> None:
        """provider 장애(호출 자체 실패)면 비용도 없다 — record 0건(지어내지 않음)."""
        spy = _SpyTraceSink()
        candidate = _gen(RaisingProvider(), trace=spy).generate(_spec())
        assert candidate is None
        assert spy.records == []

    def test_crashing_sink_never_breaks_generation(self) -> None:
        """관측 sink가 죽어도 저작은 계속된다(never-break — langfuse_sink 방침 동형)."""
        candidate = _gen(FakeProvider([_HAPPY]), trace=_CrashingTraceSink()).generate(_spec())
        assert candidate is not None  # 생성 결과는 무영향

    def test_flush_trace_confirms_transport(self) -> None:
        """flush_trace는 sink.flush를 확정 호출 — flush 없는 sink는 조용히 통과."""
        spy = _SpyTraceSink()
        gen = _gen(FakeProvider([_HAPPY]), trace=spy)
        gen.flush_trace()
        assert spy.flush_count == 1
        # flush 표면이 없는 sink(계약 최소 구현)에도 안전하다.
        _gen(FakeProvider([_HAPPY]), trace=_CrashingTraceSink()).flush_trace()


# ──────────────────────────────────────────────────────────────────────
# MP-02 재회차: avoid_recent — 회차 내 중복 회피 목록(자기 출력 기억).
# ──────────────────────────────────────────────────────────────────────
def _happy_with(conditions: str, answer: str) -> str:
    """_HAPPY에서 조건식·답만 바꾼 응답(다른 방정식 구조)."""
    data = json.loads(_HAPPY)
    data["conditions"] = conditions
    data["answer"] = answer
    data["answer_map"] = {"x": answer}
    return json.dumps(data, ensure_ascii=False)


_AVOID_MARKER = "이번에 이미 만든 방정식"


class TestAvoidRecent:
    def test_default_never_adds_avoid_block(self) -> None:
        """기본(0)은 여러 번 생성해도 회피 블록이 없다 — 대조군(기본 프롬프트 회귀 0)."""
        provider = FakeProvider([_HAPPY, _HAPPY])
        gen = _gen(provider)
        gen.generate(_spec())
        gen.generate(_spec())
        assert all(_AVOID_MARKER not in prompt for prompt, _ in provider.calls)

    def test_first_prompt_has_no_block_second_lists_previous(self) -> None:
        provider = FakeProvider([_HAPPY, _happy_with("x**2 - 7*x + 12 = 0", "4")])
        gen = _gen(provider, avoid_recent=3)
        assert gen.generate(_spec()) is not None
        gen.generate(_spec())
        first, second = provider.calls[0][0], provider.calls[1][0]
        assert _AVOID_MARKER not in first  # 아직 만든 것이 없으면 블록 자체가 없다
        assert _AVOID_MARKER in second
        assert "- x**2 - 5*x + 6 = 0" in second

    def test_keeps_only_last_n_and_skips_repeats(self) -> None:
        responses = [
            _happy_with("x**2 - 3*x + 2 = 0", "2"),
            _happy_with("x**2 - 3*x + 2 = 0", "2"),  # 같은 조건식 반복 — 칸을 차지하지 않는다
            _happy_with("x**2 - 7*x + 12 = 0", "4"),
            _happy_with("x**2 - 9*x + 20 = 0", "5"),
            _HAPPY,
        ]
        provider = FakeProvider(responses)
        gen = _gen(provider, avoid_recent=2)
        for _ in responses:
            gen.generate(_spec())
        last = provider.calls[-1][0]
        assert "- x**2 - 3*x + 2 = 0" not in last  # 가장 오래된 것은 밀려났다
        assert "- x**2 - 7*x + 12 = 0" in last
        assert "- x**2 - 9*x + 20 = 0" in last
        assert last.count("x**2 - 3*x + 2 = 0") == 0

    def test_failed_generation_is_not_remembered(self) -> None:
        """조립 실패(JSON 파싱 실패)는 목록에 오르지 않는다 — 존재하지 않는 방정식을 피하라고 하지 않는다."""
        provider = FakeProvider(["이건 JSON이 아니다", _HAPPY])
        gen = _gen(provider, avoid_recent=3)
        assert gen.generate(_spec()) is None
        gen.generate(_spec())
        assert _AVOID_MARKER not in provider.calls[1][0]

    @pytest.mark.parametrize("bad", [-1, 21])
    def test_out_of_range_is_refused(self, bad: int) -> None:
        with pytest.raises(ValueError, match="avoid_recent"):
            _gen(FakeProvider([]), avoid_recent=bad)


def test_avoid_repeat_does_not_evict_an_older_distinct_equation() -> None:
    """같은 조건식 반복이 칸을 차지하면 더 오래된 *다른* 방정식이 밀려난다 — 그러지 않아야 한다.

    maxlen 2에서 a, b, b 순서면 반복을 건너뛸 때만 마지막 프롬프트에 a·b가 모두 남는다(반복을
    그대로 넣으면 [b, b]가 되어 a가 사라진다). 반례를 픽스처로 박아 둔 절.
    """
    a = _happy_with("x**2 - 3*x + 2 = 0", "2")
    b = _happy_with("x**2 - 7*x + 12 = 0", "4")
    provider = FakeProvider([a, b, b, _HAPPY])
    gen = _gen(provider, avoid_recent=2)
    for _ in range(4):
        gen.generate(_spec())
    last = provider.calls[-1][0]
    assert "- x**2 - 3*x + 2 = 0" in last
    assert "- x**2 - 7*x + 12 = 0" in last


# ──────────────────────────────────────────────────────────────────────
# MP-02 재회차 3차 — 프롬프트의 성취기준 코드 베끼기 함정 제거.
# 2026-09-25 실측: 2회차 카나리 실패 4건이 전부 시스템 프롬프트 예시의 코드([10공수1-02-02])를
# 베껴 성취기준 점수 0.00 → 검수필요였다. 합격 81건은 전부 스펙 코드를 적었다.
# ──────────────────────────────────────────────────────────────────────
# 고시 성취기준 코드 형태 — `[10공수1-02-02]`·`[9수02-20]`·`[12미적01-01]` (숫자 학년 + 한글 과목 +
# 숫자·하이픈). 조건식 금지 예시 `[중3 이차방정식 예제 16]`처럼 한글로 시작하는 괄호는 제외된다.
_STANDARD_CODE_LITERAL = re.compile(r"\[\d{1,2}[가-힣]+\d[\d-]*\]")


class TestStandardCodeCopyTrap:
    def test_pattern_catches_the_old_trap_and_the_spec_code(self) -> None:
        # 가드의 변별력 — 이 정규식이 옛 함정 코드와 실제 스펙 코드를 **잡지 못하면** 아래 전수
        # 검사는 공허하게 초록이다. 조건식 금지 예시(한글 시작 괄호)는 잡지 않아야 한다.
        for code in ("[10공수1-02-02]", "[9수02-20]", _STANDARD):
            assert _STANDARD_CODE_LITERAL.search(code), code
        assert not _STANDARD_CODE_LITERAL.search("[중3 이차방정식 예제 16]")

    @pytest.mark.parametrize("asset_id", llm_generator._EQUIVALENT_PROMPT_ASSET_IDS)
    def test_no_prompt_asset_carries_a_concrete_standard_code(self, asset_id: str) -> None:
        # 성취기준 코드는 호출마다 스펙(SPEC_JSON)에서만 와야 한다 — 고정 문구에 박힌 코드는 스펙이
        # 다를 때 모델이 베끼는 함정이 된다(옛 예시가 기본 스펙 코드와 같아서 1차에는 안 보였다).
        text = prompt_text(asset_id)
        assert text, asset_id  # 빈 자산이면 아래 검사가 공허하게 통과한다
        found = _STANDARD_CODE_LITERAL.findall(text)
        assert found == [], f"{asset_id}에 구체 성취기준 코드가 있습니다: {found}"

    def test_system_prompt_tells_to_copy_spec_codes(self) -> None:
        # 예시에서 필드를 뺀 만큼, 무엇을 적어야 하는지는 지시문이 말해야 한다.
        provider = FakeProvider([_HAPPY])
        _gen(provider).generate(_spec())
        _, system = provider.calls[0]
        assert "achievement_standard_codes" in system
        assert "그대로 복사" in system

    def test_wrong_code_still_goes_to_review_not_silently_fixed(self) -> None:
        # 고친 것은 프롬프트뿐이다 — 생성기가 모델의 코드를 스펙 코드로 **몰래 바꾸지 않고**, 게이트가
        # 여전히 성취기준 0점으로 검수필요를 낸다(검증 약화 없음). 스펙 코드를 적으면 통과한다.
        wrong = json.loads(_HAPPY)
        wrong["achievement_standard_codes"] = ["[10공수1-02-02]"]
        for payload, expected in ((wrong, False), (json.loads(_HAPPY), True)):
            candidate = _gen(FakeProvider([json.dumps(payload, ensure_ascii=False)])).generate(
                _spec()
            )
            assert candidate is not None
            assert list(candidate.problem.achievement_standard_codes) == list(
                payload["achievement_standard_codes"]
            )
            verdict = evaluate_equivalent_candidate(
                _spec(),
                candidate.problem,
                provenance=candidate.provenance,
                conditions=candidate.conditions,
                answer_map=candidate.answer_map,
                answer_selection=candidate.answer_selection,
                solution_steps=candidate.solution_steps,
            )
            assert verdict.accepted is expected
            if not expected:
                assert verdict.equivalence == "검수필요"
                assert any("성취기준 0.00" in reason for reason in verdict.reasons)
