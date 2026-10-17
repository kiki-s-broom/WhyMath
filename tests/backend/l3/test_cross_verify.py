"""독립 다관점 LLM 교차검증(S4-13 ②) — hermetic(스크립트 provider·라이브 호출 0).

검증 축:
  ① **독립성 강제**: 원리·시스템 프롬프트·가시 필드가 겹치거나 K<3이면 *구성 시점에* 거부.
     "같은 프롬프트 3회"는 다관점이 아니다.
  ② **생성자≠검증자**: 대상의 저작 서명이 검증자 서명과 같으면 자기승인으로 거부.
  ③ **정보 은닉**: 재구성 관점 프롬프트에 정답이 실리지 않는다(앵커링 차단이 실제로 성립).
  ④ **집계**: 만장일치 ok만 통과·결함 지목은 다수결로 덮이지 않음·판정 실패는 unclear.
  ⑤ **측정 실패 가시화**: provider 예외·JSON 파싱 실패가 'ok'로 위장되지 않는다.
  ⑥ **라우터 경유**: 직접 호출 0 — 라우터 결정(호출지점 ⑤ 자기검증 좌석)이 provider로 전달.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from fractions import Fraction

import pytest

from whymath_backend.config import Settings
from whymath_backend.l3.cross_verify import (
    MISSING_CONDITION_PERSPECTIVES,
    MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    PROBABILITY_PERSPECTIVES,
    STATISTICAL_PERSPECTIVES,
    UNRECORDED_AUTHOR,
    AuthorDeclarationConflictError,
    CrossVerifier,
    IndependenceError,
    Perspective,
    ResidueSubject,
    _assert_independent,
    _judge_defect_class,
    _judge_labelled,
    assert_author_independent,
    deterministic_author,
    llm_author,
    resolve_author_signature,
)
from whymath_backend.l3.models import (
    CostTier,
    GenerationResult,
    LocalModelTier,
    RoutingDecision,
)
from whymath_backend.l3.pregenerate.provenance_bridge import model_name_for_decision
from whymath_backend.l3.prompt_assets import prompt_text
from whymath_backend.l3.router import Router, resolve_model
from whymath_backend.l3.statistical_claim import verify_statistical_claim

_SUBJECT = ResidueSubject(
    problem_id="wm-finite-test",
    question_text="서로 구별되는 두 개의 주사위를 던질 때 눈의 합이 7일 확률은?",
    answer="1/6",
    answer_explanation="전체 36가지 중 6가지.",
    machine_model_ko="표본공간: 36가지.\n사건 A: 값들의 합이 7과 같다.\n확률 = 6/36.",
    machine_total=36,
    machine_favorable=6,
    # LLM 생성자가 없다는 *명시 선언*(PB-15). 종전 `corpus:FULLY_GENERATED`는 검증자 서명과 형식이
    # 달라 가드를 영영 비껴갔고, 그래서 이 픽스처가 가드를 한 번도 밟지 못했다.
    authored_by=deterministic_author("finite_enumerator"),
)

_RECONSTRUCT_OK = json.dumps({"total": 36, "favorable": 6})
_LABEL_OK = json.dumps({"verdict": "ok", "reason": "문제 없음"}, ensure_ascii=False)
_LABEL_DEFECT = json.dumps(
    {"verdict": "defect", "defect_class": "ambiguous_condition", "reason": "구별 여부 미명시"},
    ensure_ascii=False,
)


class ScriptedProvider:
    """관점 순서대로 응답을 방출하는 provider 대역 — LLMProvider 충족(네트워크 0)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self.decisions: list[RoutingDecision] = []

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
        self.calls.append((prompt, system))
        self.decisions.append(decision)
        if self._index < len(self._responses):
            out = self._responses[self._index]
            self._index += 1
            return GenerationResult(out)
        return GenerationResult("응답 없음")


class RaisingProvider:
    """항상 예외를 던지는 provider 대역 — 측정 실패가 통과로 위장되지 않는지 본다."""

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


class RecordingSink:
    """관측 싱크 대역 — 기록 dict를 모은다(Langfuse 미사용)."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)


def _verifier(provider: object, **kwargs: object) -> CrossVerifier:
    return CrossVerifier(provider, trace=RecordingSink(), **kwargs)  # type: ignore[arg-type]


# ── ① 독립성 강제 ─────────────────────────────────────────────────────
def test_fewer_than_three_perspectives_is_rejected() -> None:
    with pytest.raises(IndependenceError, match="최소 K"):
        _verifier(ScriptedProvider([]), perspectives=PROBABILITY_PERSPECTIVES[:2])


def test_same_prompt_repeated_is_not_independent() -> None:
    """같은 프롬프트 K회는 독립이 아니다 — 원리·프롬프트가 모두 같은 복제는 거부된다."""
    base = PROBABILITY_PERSPECTIVES[1]
    clones = tuple(base for _ in range(3))
    with pytest.raises(IndependenceError, match="원리 중복"):
        _verifier(ScriptedProvider([]), perspectives=clones)


def test_same_visible_fields_is_not_independent() -> None:
    """원리·프롬프트가 달라도 *같은 정보*를 보면 같은 앵커링을 공유해 독립이 아니다."""
    a, b, c = PROBABILITY_PERSPECTIVES
    shadow = Perspective(
        principle="second_opinion",
        system_prompt="다른 문구지만 같은 정보를 본다.",
        visible_fields=b.visible_fields,  # ②와 동일 가시 집합
        render=b.render,
        judge=b.judge,
    )
    with pytest.raises(IndependenceError, match="가시 필드 집합 중복"):
        _verifier(ScriptedProvider([]), perspectives=(a, b, shadow, c))


def test_default_perspectives_have_three_distinct_principles() -> None:
    principles = {p.principle for p in PROBABILITY_PERSPECTIVES}
    prompts = {p.system_prompt for p in PROBABILITY_PERSPECTIVES}
    fields = {p.visible_fields for p in PROBABILITY_PERSPECTIVES}
    assert len(principles) == len(prompts) == len(fields) == 3


# ── ② 생성자 ≠ 검증자 ─────────────────────────────────────────────────
def test_self_approval_is_refused() -> None:
    """대상을 만든 주체가 곧 검증자면 자기승인 — 검증 자체를 거부한다."""
    verifier = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK]))
    subject = replace(_SUBJECT, authored_by=verifier.signature)
    with pytest.raises(IndependenceError, match="자기승인"):
        verifier.verify(subject)


# ── ②-b 생성자 서명 3상태 (PB-15) ─────────────────────────────────────
# 위 `test_self_approval_is_refused`는 `verifier.signature`를 그대로 대입하므로 동어반복이다 —
# 저작 측이 *다른 함수*로 서명을 조립해 형식이 갈라져도 통과한다. PB-15의 결함이 정확히 그것이었다
# (코퍼스 `corpus:<유형>` vs 검증자 `llm:<모델>`). 아래는 저작 측 조립 경로로 만든 서명과 **실값**
# 문자열로 단언한다.
_PIN = "qwen3:30b-a3b"


def test_same_llm_is_self_approval_and_other_llm_is_not() -> None:
    """절: LLM 서명 동일 비교. 대조군(다른 모델)이 함께 있어야 '전부 거부'하는 수정이 걸린다."""
    with pytest.raises(IndependenceError, match="자기승인"):
        assert_author_independent(llm_author(_PIN), llm_author(_PIN))
    assert_author_independent(llm_author("other-model:7b"), llm_author(_PIN))  # 예외 없음


@pytest.mark.parametrize(
    "variant",
    [
        "llm:QWEN3:30B-A3B",  # 절: casefold — 사람이 손으로 쓴 대소문자 차이가 가드를 비껴가면 안 된다
        "llm:qwen3:30b-a3b ",  # 절: strip — 뒤 공백
    ],
)
def test_llm_comparison_ignores_case_and_trailing_space(variant: str) -> None:
    with pytest.raises(IndependenceError, match="자기승인"):
        assert_author_independent(variant, llm_author(_PIN))


def test_deterministic_declaration_is_never_compared_with_the_verifier() -> None:
    """절: 결정론 선언은 비교 대상이 아니다 — 검증자가 LLM이어도 통과(LLM 생성자가 없다)."""
    assert_author_independent(deterministic_author("finite_enumerator"), llm_author(_PIN))


@pytest.mark.parametrize(
    "unreadable",
    [
        "",  # 절: 빈 문자열은 '비교 대상 아님'으로 접히지 않는다
        UNRECORDED_AUTHOR,  # 절: 기록 없음 = 모른다 ≠ 아니다
        "corpus:FULLY_GENERATED",  # 종전 코퍼스 조립값 — 이 값이 가드를 영영 비껴갔던 장본인
        "deterministic_enumerator",  # 콜론 없는 비공식 표기는 선언이 아니다
        "llm:",  # 절: 접두어만 있고 이름이 빈 LLM 서명 — 어떤 검증자와도 '다르다'며 통과하면 안 됨
        "llm:   ",  # 절: 공백뿐인 이름
        "deterministic:",  # 절: 이름 없는 결정론 선언
        "LLM:qwen3:30b-a3b",  # 절: 접두어는 정확 일치 — 대문자 접두어는 판독 불가
        " llm:qwen3:30b-a3b",  # 절: 앞 공백이 붙은 접두어
    ],
)
def test_unreadable_author_is_refused_fail_closed(unreadable: str) -> None:
    """기록 없음·판독 불가 서명은 독립성을 입증할 수 없어 거부한다(침묵 통과 금지)."""
    with pytest.raises(IndependenceError, match="판독할 수 없다"):
        assert_author_independent(unreadable, llm_author(_PIN))


@pytest.mark.parametrize("name", ["", "   "])
def test_signature_builders_refuse_empty_names(name: str) -> None:
    """빈 이름으로는 서명을 만들 수 없다 — 빈 값이 서명으로 위장해 가드를 우회하는 길을 막는다."""
    with pytest.raises(ValueError, match="비었다"):
        llm_author(name)
    with pytest.raises(ValueError, match="비었다"):
        deterministic_author(name)


def test_local_verifier_signature_collides_with_authoring_side_signature() -> None:
    """저작 측 조립 경로(`model_name_for_decision`)로 만든 서명이 검증자 서명과 충돌한다.

    로컬 좌석의 실값은 `llm:` + 라우터 매트릭스 해석 모델 id다 — 함수 자신이 아니라 라우터
    결정에서 독립 도출한 값으로 단언한다.
    """
    verifier = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK]))
    decision = Router().route(verifier._routing_request())
    local_model = resolve_model(decision.local_family, decision.local_model)

    assert verifier.signature == f"llm:{local_model}"
    authored_by_authoring_side = llm_author(model_name_for_decision(decision))
    with pytest.raises(IndependenceError, match="자기승인"):
        verifier.verify(replace(_SUBJECT, authored_by=authored_by_authoring_side))


@pytest.mark.parametrize("seat", ["anthropic", "openrouter", "deepseek"])
def test_cloud_verifier_signature_names_the_pinned_model_not_the_tier(
    seat: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """클라우드 좌석 — 검증자 서명이 티어명(`llm:cloud_mid`)이 아니라 모델 핀이다.

    종전 판은 클라우드에서 `llm:<티어명>`을 냈고 저작 측은 모델 핀을 기록했다. 코퍼스 쪽 형식만
    고쳤다면 로컬끼리의 충돌은 잡혀도 *같은 클라우드 모델이 만든 문항을 같은 모델이 검증*하는
    경우는 여전히 못 잡았을 것이다. 좌석 3종을 모두 밟는다(한 좌석만 고치고 방치하는 형태 차단).
    """
    settings = Settings(jwt_secret_key="x" * 32, cloud_provider=seat)  # type: ignore[arg-type]
    pin = {
        "anthropic": settings.anthropic_model_mid,
        "openrouter": settings.openrouter_model_mid,
        "deepseek": settings.deepseek_model_mid,
    }[seat]
    cloud_decision = RoutingDecision(cost_tier=CostTier.CLOUD_MID, est_latency_ms=1000)
    monkeypatch.setattr(Router, "route", lambda self, request: cloud_decision)

    verifier = _verifier(
        ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK]), settings=settings
    )

    assert verifier.signature == f"llm:{pin}"
    assert verifier.signature != "llm:cloud_mid", "티어명 서명 — 종전 결함(PB-15) 재발"
    with pytest.raises(IndependenceError, match="자기승인"):
        verifier.verify(replace(_SUBJECT, authored_by=llm_author(pin)))
    # 대조군: 다른 모델이 만든 문항은 통과한다(전부 거부하는 과잉 수정 방지).
    result = verifier.verify(replace(_SUBJECT, authored_by=llm_author("some-other-model")))
    assert result.aggregate == "ok"


def test_legacy_corpus_corpus_prefix_no_longer_slips_past_the_guard() -> None:
    """종전 결함의 직접 재현 — `corpus:<유형>` 서명 대상은 이제 검증 단계에서 거부된다."""
    verifier = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK]))
    with pytest.raises(IndependenceError, match="판독할 수 없다"):
        verifier.verify(replace(_SUBJECT, authored_by="corpus:FULLY_GENERATED"))


# ── ③ 정보 은닉 ───────────────────────────────────────────────────────
def test_reconstruction_prompt_hides_answer_and_model() -> None:
    """재구성 관점은 발문만 본다 — 정답·형식모델이 프롬프트에 새면 독립 재계산이 아니다."""
    provider = ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK])
    _verifier(provider).verify(_SUBJECT)
    reconstruction_prompt = provider.calls[0][0]
    assert _SUBJECT.question_text in reconstruction_prompt
    assert _SUBJECT.answer not in reconstruction_prompt
    assert "표본공간: 36가지" not in reconstruction_prompt
    # 반증 관점은 답을 보지만 형식모델은 보지 않는다(빈틈을 모델로 메워 읽지 않게).
    falsify_prompt = provider.calls[1][0]
    assert _SUBJECT.answer in falsify_prompt
    assert "표본공간: 36가지" not in falsify_prompt


# ── ④ 집계 ────────────────────────────────────────────────────────────
def test_unanimous_ok_passes() -> None:
    result = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK])).verify(_SUBJECT)
    assert result.aggregate == "ok"
    assert len(result.verdicts) == 3


def test_single_defect_beats_majority_ok() -> None:
    """결함 지목은 다수결로 덮이지 않는다(2 ok vs 1 defect → defect)."""
    result = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_DEFECT, _LABEL_OK])).verify(
        _SUBJECT
    )
    assert result.aggregate == "defect"
    assert result.defect_class == "adversarial_falsification:ambiguous_condition"


def test_reconstruction_mismatch_is_machine_judged_defect() -> None:
    """①의 판정 주체는 기계다 — LLM이 낸 숫자를 전수 열거 값과 대조한다."""
    wrong = json.dumps({"total": 21, "favorable": 3})  # 두 주사위를 구별하지 않은 흔한 오독
    result = _verifier(ScriptedProvider([wrong, _LABEL_OK, _LABEL_OK])).verify(_SUBJECT)
    assert result.aggregate == "defect"
    assert result.defect_class == "independent_reconstruction:model_mismatch"
    assert "3/21" in result.reason


def test_reconstruction_decline_is_unclear_not_ok() -> None:
    declined = json.dumps({"total": None, "favorable": None, "reason": "조건 부족"})
    result = _verifier(ScriptedProvider([declined, _LABEL_OK, _LABEL_OK])).verify(_SUBJECT)
    assert result.aggregate == "unclear"


# ── ⑤ 측정 실패 가시화 ────────────────────────────────────────────────
def test_provider_failure_is_unclear_with_exception_type() -> None:
    """provider가 죽으면 '결함 0건 통과'가 아니라 측정 실패로 남고 타입명이 기록된다."""
    result = _verifier(RaisingProvider()).verify(_SUBJECT)
    assert result.aggregate == "unclear"
    assert "RuntimeError" in result.reason


def test_unparseable_response_is_unclear() -> None:
    result = _verifier(ScriptedProvider(["JSON이 아님", _LABEL_OK, _LABEL_OK])).verify(_SUBJECT)
    assert result.aggregate == "unclear"
    assert result.verdicts[0].defect_class == "response_unparsed"


def test_unknown_verdict_label_is_unclear() -> None:
    weird = json.dumps({"verdict": "maybe", "reason": "글쎄"}, ensure_ascii=False)
    result = _verifier(ScriptedProvider([_RECONSTRUCT_OK, weird, _LABEL_OK])).verify(_SUBJECT)
    assert result.aggregate == "unclear"
    assert result.verdicts[1].defect_class == "verdict_unparsed"


# ── ⑥ 라우터 경유 ─────────────────────────────────────────────────────
def test_calls_go_through_router_self_verify_seat() -> None:
    """직접 호출 0 — 라우터가 호출지점 ⑤(자기검증) 좌석으로 결정한 값이 provider로 간다."""
    provider = ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK])
    sink = RecordingSink()
    CrossVerifier(provider, trace=sink).verify(_SUBJECT)  # type: ignore[arg-type]
    assert len(provider.decisions) == 3
    for decision in provider.decisions:
        assert decision.cost_tier == CostTier.LOCAL.value
        assert decision.local_model == LocalModelTier.QUALITY.value
        assert decision.mode == "async"
    # 모든 LLM 호출은 관측에 남는다(Langfuse 필드 dict).
    assert len(sink.records) == 3
    assert sink.records[0]["call_site"] == "self_verify"


# ══════════════════════════════════════════════════════════════════════════
# v4 — 결함류별 적대적 검증 관점(S4-16 회수분)
# ══════════════════════════════════════════════════════════════════════════
# 검증 축(위 ①~⑥에 추가):
#   ⑦ **v4 구성의 독립성**: 두 결함류 전용 튜플이 각각 K=3 독립성 검사를 통과한다.
#   ⑧ **결함류 기본값**: 응답이 결함류를 비워 보내면 기대 결함류로 메우고, 적어 보냈으면
#      덮어쓰지 않는다(하위 분류 정보 손실 금지).
#   ⑨ **관점 주입 경로**: `perspectives=`로 넘긴 v4 관점이 실제로 그 프롬프트를 태운다.
#   ⑩ **정본 해석**: v4 프롬프트 키 12개가 전부 레지스트리에서 해석된다(유령 인용 0).
#   ⑪ **회귀 0**: 기존 확률·통계 관점 구성이 그대로 성립한다.

_V4_PROMPT_KEYS: tuple[str, ...] = (
    "l3.cross_verify.missing_condition_checklist_system",
    "l3.cross_verify.missing_condition_checklist_user",
    "l3.cross_verify.missing_condition_model_grounding_system",
    "l3.cross_verify.missing_condition_model_grounding_user",
    "l3.cross_verify.missing_condition_student_reading_system",
    "l3.cross_verify.missing_condition_student_reading_user",
    "l3.cross_verify.multiple_valid_answers_counterexample_system",
    "l3.cross_verify.multiple_valid_answers_counterexample_user",
    "l3.cross_verify.multiple_valid_answers_alternative_model_system",
    "l3.cross_verify.multiple_valid_answers_alternative_model_user",
    "l3.cross_verify.multiple_valid_answers_boundary_system",
    "l3.cross_verify.multiple_valid_answers_boundary_user",
)


# ── ⑦ v4 구성의 독립성(K=3) ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("name", "perspectives"),
    [
        ("missing_condition", MISSING_CONDITION_PERSPECTIVES),
        ("multiple_valid_answers", MULTIPLE_VALID_ANSWERS_PERSPECTIVES),
    ],
)
def test_v4_tuples_pass_independence_assertion(
    name: str, perspectives: tuple[Perspective, ...]
) -> None:
    """두 v4 튜플은 *구성 시점* 독립성 검사를 통과한다 — 생성자가 아니라 기계가 판정."""
    _assert_independent(perspectives, 3)  # 위반이면 IndependenceError로 즉시 실패
    assert len(perspectives) == 3, name
    assert len({p.principle for p in perspectives}) == 3
    assert len({p.system_prompt for p in perspectives}) == 3
    assert len({p.visible_fields for p in perspectives}) == 3


@pytest.mark.parametrize(
    "perspectives", [MISSING_CONDITION_PERSPECTIVES, MULTIPLE_VALID_ANSWERS_PERSPECTIVES]
)
def test_v4_visible_fields_are_known_names(perspectives: tuple[Perspective, ...]) -> None:
    """가시 필드는 `ResidueSubject`에 실재하는 이름만 쓴다(오타로 은닉이 새는 것 방어)."""
    for perspective in perspectives:
        for field in perspective.visible_fields:
            assert hasattr(_SUBJECT, field), f"{perspective.principle}: 미지 필드 {field}"


# ── ⑧ 결함류 기본값(`_judge_defect_class`) ────────────────────────────
def test_defect_class_default_fills_when_response_leaves_it_blank() -> None:
    """응답이 결함류를 비우면 관점 구성이 고정한 기대 결함류로 메운다(unspecified 금지)."""
    judge = _judge_defect_class(
        "missing_condition_checklist", expected_defect_class="missing_condition"
    )
    verdict = judge(_SUBJECT, {"verdict": "defect", "reason": "구별 여부 미명시"})
    assert verdict.verdict == "defect"
    assert verdict.defect_class == "missing_condition"
    assert verdict.reason == "구별 여부 미명시"


def test_defect_class_default_does_not_overwrite_response_class() -> None:
    """응답이 스스로 분류했으면 덮어쓰지 않는다 — 더 좁은 하위 분류를 지운 셈이 된다."""
    judge = _judge_defect_class(
        "missing_condition_checklist", expected_defect_class="missing_condition"
    )
    verdict = judge(
        _SUBJECT,
        {
            "verdict": "defect",
            "defect_class": "equiprobability_unstated",
            "reason": "등확률 미명시",
        },
    )
    assert verdict.defect_class == "equiprobability_unstated"


def test_defect_class_default_leaves_ok_and_unclear_untouched() -> None:
    """ok는 결함류가 비어야 하고, 미지 라벨은 unclear의 진단 결함류를 유지한다."""
    judge = _judge_defect_class(
        "multiple_valid_answers_boundary", expected_defect_class="multiple_valid_answers"
    )
    ok = judge(_SUBJECT, {"verdict": "ok", "reason": "문제 없음"})
    assert (ok.verdict, ok.defect_class) == ("ok", "")
    weird = judge(_SUBJECT, {"verdict": "글쎄", "reason": "모름"})
    assert (weird.verdict, weird.defect_class) == ("unclear", "verdict_unparsed")


# ── ⑨ 관점 주입 경로 ──────────────────────────────────────────────────
def test_missing_condition_perspectives_are_actually_used() -> None:
    """`perspectives=`로 넘긴 v4 관점이 실제로 그 시스템 프롬프트를 태우고 판정에 반영된다."""
    provider = ScriptedProvider([_LABEL_OK, _LABEL_OK, _LABEL_OK])
    result = _verifier(provider, perspectives=MISSING_CONDITION_PERSPECTIVES).verify(_SUBJECT)
    assert [v.principle for v in result.verdicts] == [
        p.principle for p in MISSING_CONDITION_PERSPECTIVES
    ]
    assert [system for _, system in provider.calls] == [
        p.system_prompt for p in MISSING_CONDITION_PERSPECTIVES
    ]
    assert result.aggregate == "ok"


def test_v4_perspectives_can_be_injected_per_call() -> None:
    """*호출 시점* 관점 주입이 인스턴스 기본 관점을 실제로 대체한다.

    `Verifier`가 쓰는 경로가 이쪽이다(`verify(subject, perspectives)`) — 생성자 주입만
    검사하면 이 분기를 한 번도 밟지 않아 무력화돼도 초록이다(뮤테이션 M7로 실측).
    """
    provider = ScriptedProvider([_LABEL_OK, _LABEL_OK, _LABEL_OK])
    verifier = _verifier(provider)  # 인스턴스 기본 = PROBABILITY_PERSPECTIVES
    result = verifier.verify(_SUBJECT, MULTIPLE_VALID_ANSWERS_PERSPECTIVES)
    assert [v.principle for v in result.verdicts] == [
        p.principle for p in MULTIPLE_VALID_ANSWERS_PERSPECTIVES
    ]
    # 대조군 — 인자를 생략하면 인스턴스 기본 관점으로 돌아간다(분기가 양방향으로 산다).
    default_result = _verifier(ScriptedProvider([_RECONSTRUCT_OK, _LABEL_OK, _LABEL_OK])).verify(
        _SUBJECT
    )
    assert [v.principle for v in default_result.verdicts] == [
        p.principle for p in PROBABILITY_PERSPECTIVES
    ]


def test_multiple_valid_answers_defect_carries_expected_class() -> None:
    """결함류를 비운 결함 응답도 집계 라벨이 `multiple_valid_answers`로 확정된다."""
    blank = json.dumps({"verdict": "defect", "reason": "복원 해석에서 다른 답"}, ensure_ascii=False)
    result = _verifier(
        ScriptedProvider([blank, _LABEL_OK, _LABEL_OK]),
        perspectives=MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    ).verify(_SUBJECT)
    assert result.aggregate == "defect"
    assert result.defect_class == "multiple_valid_answers_counterexample:multiple_valid_answers"


# ── ⑩ 정본 해석(유령 인용 0) ──────────────────────────────────────────
def test_all_v4_prompt_keys_resolve_from_canon() -> None:
    """v4 프롬프트 키 12개가 전부 정본에서 해석된다 — 하나라도 없으면 런타임 fail-closed."""
    assert len(set(_V4_PROMPT_KEYS)) == 12
    for key in _V4_PROMPT_KEYS:
        assert prompt_text(key).strip(), f"{key}: 정본 본문이 비어 있다"


def test_v4_prompt_bodies_avoid_cp949_hostile_punctuation() -> None:
    """정본 v4 프롬프트 본문은 em dash 등 cp949 취약 문자를 쓰지 않는다(인코딩 안전)."""
    for key in _V4_PROMPT_KEYS:
        body = prompt_text(key)
        for ch in ("—", "–", "‘", "’", "“", "”", "→"):
            assert ch not in body, f"{key}: cp949 취약 문자 {ch!r} 포함"


# ── ⑪ 회귀 0 — 기존 관점 구성이 그대로 성립한다 ───────────────────────
@pytest.mark.parametrize("perspectives", [PROBABILITY_PERSPECTIVES, STATISTICAL_PERSPECTIVES])
def test_pre_v4_perspective_tuples_still_independent(perspectives: tuple[Perspective, ...]) -> None:
    """v4 추가가 기존 확률·통계 K=3 구성을 건드리지 않았다(순수 가산 이식의 회귀 축)."""
    _assert_independent(perspectives, 3)
    assert len(perspectives) == 3


def test_v4_principles_do_not_collide_with_pre_v4_principles() -> None:
    """v4 원리 이름이 기존 6개 원리와 겹치지 않는다 — 집계 라벨의 모호성 방지."""
    pre_v4 = {p.principle for p in PROBABILITY_PERSPECTIVES + STATISTICAL_PERSPECTIVES}
    v4 = {p.principle for p in MISSING_CONDITION_PERSPECTIVES + MULTIPLE_VALID_ANSWERS_PERSPECTIVES}
    assert len(pre_v4) == 6 and len(v4) == 6
    assert not (pre_v4 & v4)


# ──────────────────────────────────────────────────────────────────────────
# ⑫ 가시 필드 정직성 — 선언(visible_fields)이 실제 노출과 일치하는가
#
# 왜 이 검사가 필요한가: `_assert_independent`는 관점의 *선언*만 본다. 선언이 실제
# 렌더와 어긋나면 그 가드는 통과 도장일 뿐이다 — 실제로 2026-09-21 v4 이식에서
# 6관점 중 3관점이 선언보다 좁게 렌더했고(예 `+answer`를 선언하고 발문만 실음),
# 독립성 3축 중 가시 필드 축이 *명목*으로만 성립하는 상태였다. 이 검사는 선언을
# 검사받는 주장으로 바꾼다.
#
# 방법: 소스를 읽지 않고 **행동으로** 잰다(`inspect.getsource` 기반 검사는 트리가
# 실행 중 바뀌면 거짓 실패를 낸다 — CLAUDE.md 검증 중 트리 변경 축). 필드마다 고유
# 센티넬을 넣은 대상을 렌더해, 결과 문자열에 나타난 센티넬 집합을 선언과 대조한다.
# ──────────────────────────────────────────────────────────────────────────

_SENTINEL_FIELDS = ("question_text", "answer", "answer_explanation", "machine_model_ko", "data")


def _sentinel_subject() -> ResidueSubject:
    """필드마다 고유 센티넬을 실은 대상 — 렌더 결과에서 역추적 가능하게."""
    return ResidueSubject(
        problem_id="sentinel",
        question_text="<<<SENTINEL_QUESTION_TEXT>>>",
        answer="<<<SENTINEL_ANSWER>>>",
        answer_explanation="<<<SENTINEL_ANSWER_EXPLANATION>>>",
        machine_model_ko="<<<SENTINEL_MACHINE_MODEL_KO>>>",
        machine_total=36,
        machine_favorable=1,
        authored_by="deterministic:sentinel",
        data="<<<SENTINEL_DATA>>>",
    )


def _actually_exposed(perspective: Perspective) -> frozenset[str]:
    """이 관점의 user 프롬프트에 *실제로* 실린 필드 집합."""
    rendered = perspective.render(_sentinel_subject())
    return frozenset(
        field for field in _SENTINEL_FIELDS if f"<<<SENTINEL_{field.upper()}>>>" in rendered
    )


@pytest.mark.parametrize(
    "perspective",
    [
        *PROBABILITY_PERSPECTIVES,
        *STATISTICAL_PERSPECTIVES,
        *MISSING_CONDITION_PERSPECTIVES,
        *MULTIPLE_VALID_ANSWERS_PERSPECTIVES,
    ],
    ids=lambda p: p.principle,
)
def test_visible_fields_declaration_matches_actual_exposure(perspective: Perspective) -> None:
    """선언한 가시 필드 = 실제로 프롬프트에 실린 필드. 과다 선언도 과소 선언도 위반."""
    assert _actually_exposed(perspective) == perspective.visible_fields, (
        f"{perspective.principle}: 선언 {sorted(perspective.visible_fields)} != "
        f"실노출 {sorted(_actually_exposed(perspective))} — "
        "선언이 검사받지 않으면 독립성 가드가 통과 도장이 된다"
    )


def test_sentinel_probe_itself_discriminates() -> None:
    """탐침의 변별력 — 선언을 그대로 되돌려주는 탐침이면 위 검사 전체가 위장이다.

    그래서 *일부러 과다 선언한* 가짜 관점을 만들어, 탐침이 선언이 아니라 **실제 렌더**를
    본다는 것을 직접 확인한다. 이 검사가 없으면 `_actually_exposed`를
    `return perspective.visible_fields`로 바꿔치기해도 위 12건이 전건 통과한다.
    """
    liar = Perspective(
        principle="liar_overdeclares",
        system_prompt="(테스트 전용)",
        # 선언은 4필드인데 렌더는 발문만 싣는다 — v4 이식이 실제로 빠졌던 형태.
        visible_fields=frozenset({"question_text", "answer", "answer_explanation", "data"}),
        render=lambda subject: f"[문항]\n{subject.question_text}",
        judge=_judge_labelled("liar_overdeclares"),
    )
    assert _actually_exposed(liar) == frozenset({"question_text"})
    assert _actually_exposed(liar) != liar.visible_fields

    # 반대 방향 대조군 — 선언대로 전부 싣는 관점은 일치로 잡힌다(전건 불일치 보고 방지).
    honest = Perspective(
        principle="honest_declares",
        system_prompt="(테스트 전용)",
        visible_fields=frozenset({"question_text", "answer"}),
        render=lambda subject: f"{subject.question_text} / {subject.answer}",
        judge=_judge_labelled("honest_declares"),
    )
    assert _actually_exposed(honest) == honest.visible_fields


# ── 저작 선언 해석 (PB-17 ③) — 선언은 기록 없음만 채운다 ──────────────────
def test_declaration_fills_only_unrecorded() -> None:
    declared = deterministic_author("gen")
    assert resolve_author_signature(UNRECORDED_AUTHOR, declared) == declared
    assert resolve_author_signature(UNRECORDED_AUTHOR, None) == UNRECORDED_AUTHOR
    assert resolve_author_signature(UNRECORDED_AUTHOR, "  ") == UNRECORDED_AUTHOR
    assert resolve_author_signature(llm_author("m"), None) == llm_author("m")


def test_declaration_cannot_flip_a_recorded_llm_to_deterministic() -> None:
    """LLM 기록을 deterministic 선언으로 뒤집어 가드를 우회하는 길이 닫혀 있다."""
    with pytest.raises(AuthorDeclarationConflictError):
        resolve_author_signature(llm_author("qwen3:30b-a3b"), deterministic_author("g"))
    with pytest.raises(AuthorDeclarationConflictError):
        resolve_author_signature(deterministic_author("g"), llm_author("m"))


def test_declaration_equal_to_record_is_idempotent_and_case_insensitive() -> None:
    recorded = llm_author("Qwen3:30b-a3b")
    assert resolve_author_signature(recorded, "llm:qwen3:30B-A3B ") == recorded


def test_conflict_error_is_an_independence_error() -> None:
    """하위 호출부가 `IndependenceError` 하나로 독립성 위반을 잡을 수 있다."""
    assert issubclass(AuthorDeclarationConflictError, IndependenceError)


# ── 통계 독립 재계산 대조 (S4-70) — float isclose 대신 정확값 정책 ─────────────
_STAT_RECONSTRUCT = STATISTICAL_PERSPECTIVES[0]


def _stat_subject(**overrides: object) -> ResidueSubject:
    base = ResidueSubject(
        problem_id="wm-stat-test",
        question_text="자료의 평균은?",
        answer="3",
        answer_explanation="",
        machine_model_ko="평균(n=5) = 3",
        machine_total=0,
        machine_favorable=0,
        authored_by=deterministic_author("stat_generator"),
        data="data=[1,2,3,4,5]; stat=mean",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _reconstruct(subject: ResidueSubject, value: object) -> str:
    assert _STAT_RECONSTRUCT.principle == "statistical_reconstruction"
    return _STAT_RECONSTRUCT.judge(subject, {"value": value}).verdict


_TRILLION = 10**12


@pytest.mark.parametrize(
    "llm_value",
    [_TRILLION + 1, f"{_TRILLION + 1}", float(_TRILLION + 1)],
    ids=["int", "str", "float"],
)
def test_stat_reconstruct_large_mean_off_by_one_is_a_defect(llm_value: object) -> None:
    """수정 전에는 평균 10^12에서 1 어긋나도 rel_tol 1e-9 허용 폭(1000)에 들어 ok였다."""
    subject = _stat_subject(
        machine_value=float(_TRILLION),
        machine_exact=Fraction(_TRILLION),
        machine_approx=Fraction(_TRILLION),
    )
    assert _reconstruct(subject, llm_value) == "defect"
    # 대조군 — 정확히 같은 대값은 통과한다(전건 defect 과잉 수정 방지).
    assert _reconstruct(subject, _TRILLION) == "ok"
    assert _reconstruct(subject, f"{_TRILLION}") == "ok"


def test_stat_reconstruct_mismatch_reason_names_policy_and_exact_values() -> None:
    subject = _stat_subject(machine_exact=Fraction(_TRILLION), machine_approx=Fraction(_TRILLION))
    verdict = _STAT_RECONSTRUCT.judge(subject, {"value": _TRILLION + 1})
    assert verdict.defect_class == "model_mismatch"
    assert "exact" in verdict.reason
    assert str(_TRILLION + 1) in verdict.reason


def test_stat_reconstruct_terminating_machine_value_requires_exact_match() -> None:
    subject = _stat_subject(machine_exact=Fraction(5, 2), machine_approx=Fraction(5, 2))
    assert _reconstruct(subject, "2.5") == "ok"
    assert _reconstruct(subject, "5/2") == "ok"
    assert _reconstruct(subject, 2.5) == "ok"
    # 유한소수 기계값은 정확 일치 — 1e-10 어긋남도 통과시키지 않는다.
    assert _reconstruct(subject, "2.5000000001") == "defect"


def test_stat_reconstruct_reads_float_by_its_decimal_notation_not_binary_value() -> None:
    """LLM이 쓴 `0.1`은 십진 1/10이다. 이진 근사(0.1000000000000000055…)로 읽으면 정확 일치가 깨진다."""
    subject = _stat_subject(machine_exact=Fraction(1, 10), machine_approx=Fraction(1, 10))
    assert _reconstruct(subject, 0.1) == "ok"
    assert _reconstruct(subject, "0.1") == "ok"
    assert (
        _reconstruct(subject, 0.3 - 0.2) == "defect"
    )  # 0.09999999999999998 — 부동소수 잡음은 거른다


def test_stat_reconstruct_bool_is_never_a_number() -> None:
    """JSON `true`는 파이썬에서 1과 같다 — 기계값이 1이어도 숫자 1로 통과하면 안 된다."""
    subject = _stat_subject(machine_exact=Fraction(1), machine_approx=Fraction(1))
    verdict = _STAT_RECONSTRUCT.judge(subject, {"value": True})
    assert verdict.verdict == "unclear"
    assert verdict.defect_class == "value_unparsed"
    assert _reconstruct(subject, 1) == "ok"  # 대조군


def test_stat_reconstruct_non_terminating_machine_value_uses_absolute_tolerance() -> None:
    subject = _stat_subject(machine_exact=Fraction(7, 3), machine_approx=Fraction(7, 3))
    assert _reconstruct(subject, "7/3") == "ok"
    assert _reconstruct(subject, "2.3333333333") == "ok"  # 오차 3.3e-11 <= 1e-9
    assert _reconstruct(subject, "2.33") == "defect"
    # 허용 폭 경계 — 오차 1.67e-9 는 10^-9 를 넘는다(폭을 10배 풀면 통과해 버리는 입력)
    assert _reconstruct(subject, "2.333333335") == "defect"
    assert _reconstruct(subject, "2.3333333323") == "defect"  # 반대 방향 오차 1.0e-9 초과


def test_stat_reconstruct_absolute_tolerance_boundary_is_inclusive() -> None:
    """오차가 정확히 10^-9 인 재계산은 통과(경계 포함), 그보다 1/3·10^-18 이라도 크면 거절.

    S4-58 의 `abs:` 정책이 경계 포함이므로 교차검증도 같아야 한다 — 패리티 검사의 입력 격자에는
    오차가 정확히 10^-9 인 값이 없어 이 절을 밟지 못하기에 여기서 직접 건드린다.
    """
    subject = _stat_subject(machine_exact=Fraction(1, 3), machine_approx=Fraction(1, 3))
    on_boundary = Fraction(1, 3) + Fraction(1, 10**9)
    assert _reconstruct(subject, f"{on_boundary.numerator}/{on_boundary.denominator}") == "ok"
    over = on_boundary + Fraction(1, 10**18)
    assert _reconstruct(subject, f"{over.numerator}/{over.denominator}") == "defect"
    below = Fraction(1, 3) - Fraction(1, 10**9)
    assert _reconstruct(subject, f"{below.numerator}/{below.denominator}") == "ok"  # 반대 방향


def test_stat_reconstruct_irrational_machine_value_uses_approx_only() -> None:
    """무리수(exact 없음) — 근사만 있어도 절대오차로 대조한다. 정확 일치를 요구하지 않는다."""
    sqrt2 = Fraction(14142135623730950488, 10**19)
    subject = _stat_subject(machine_exact=None, machine_approx=sqrt2)
    assert _reconstruct(subject, "1.41421356237") == "ok"
    assert _reconstruct(subject, 1.4142135623730951) == "ok"
    assert _reconstruct(subject, "1.4143") == "defect"


def test_stat_reconstruct_keeps_float_only_machine_value_contract() -> None:
    """exact·approx 필드를 모르는 기존 소비자(float `machine_value`만 채움)도 그대로 동작한다."""
    third = _stat_subject(machine_value=7 / 3)
    assert _reconstruct(third, "7/3") == "ok"  # float을 exact로 승격하면 여기서 거부된다
    assert _reconstruct(third, "2.33") == "defect"
    assert _reconstruct(_stat_subject(machine_value=3.0), 3) == "ok"


def test_stat_reconstruct_exact_fields_take_precedence_over_float() -> None:
    """정확 필드가 있으면 낡은 float 값이 판정을 흐리지 않는다."""
    subject = _stat_subject(
        machine_value=float(_TRILLION),
        machine_exact=Fraction(_TRILLION + 1),
        machine_approx=Fraction(_TRILLION + 1),
    )
    assert _reconstruct(subject, _TRILLION + 1) == "ok"
    assert _reconstruct(subject, _TRILLION) == "defect"


@pytest.mark.parametrize(
    "raw",
    [
        True,
        "1 000",
        "abc",
        float("nan"),
        float("inf"),
        "1/0",
        [3],
        {"v": 3},
        "1e999999999",
        "9" * 70,
        10**70,
        "",
        "   ",
    ],
    ids=[
        "bool",
        "split-digits",
        "text",
        "nan",
        "inf",
        "zero-den",
        "list",
        "dict",
        "exponent-bomb",
        "long-token-str",
        "long-token-int",
        "empty",
        "blank",
    ],
)
def test_stat_reconstruct_unreadable_value_is_unclear_not_ok(raw: object) -> None:
    subject = _stat_subject(machine_exact=Fraction(3), machine_approx=Fraction(3))
    verdict = _STAT_RECONSTRUCT.judge(subject, {"value": raw})
    assert verdict.verdict == "unclear"
    assert verdict.defect_class == "value_unparsed"


def test_stat_reconstruct_without_any_machine_value_is_unclear() -> None:
    verdict = _STAT_RECONSTRUCT.judge(_stat_subject(), {"value": 3})
    assert verdict.verdict == "unclear"
    assert verdict.defect_class == "machine_value_missing"
    nan_only = _stat_subject(machine_value=float("nan"))
    assert _STAT_RECONSTRUCT.judge(nan_only, {"value": 3}).defect_class == "machine_value_missing"


@pytest.mark.parametrize(
    "conditions",
    [
        "data=[1,2,3,4,5]; stat=mean",  # 3 — 유한소수(정확 일치)
        "data=[1,2,4]; stat=mean",  # 7/3 — 무한소수(절대오차)
        "data=[1,2,3,4]; stat=std",  # 무리수(절대오차)
        f"data=[{_TRILLION},{_TRILLION},{_TRILLION}]; stat=mean",  # 대값
        f"data=[{_TRILLION},{_TRILLION},{_TRILLION + 1}]; stat=mean",  # 대값 무한소수
        "data=[1,2]; stat=mean",  # 3/2
    ],
)
@pytest.mark.parametrize(
    "claimed",
    [
        "3", "1.5", "7/3", "2.3333333333", "2.33", "1.2909944487", "1.29", "1.2909944488",
        str(_TRILLION), str(_TRILLION + 1), "1000000000000.0000000001", "3.0000000001", "2.9999",
    ],
)  # fmt: skip
def test_stat_reconstruct_policy_matches_statistical_claim_default_policy(
    conditions: str, claimed: str
) -> None:
    """패리티 — CORE(cross_verify)는 수학 ADAPTER를 import할 수 없어 정책을 자급한다.

    두 구현이 어긋나면 ADAPTER가 pass로 닫은 문항을 교차검증이 defect로 뒤집거나 그 반대가 된다.
    선언된 `tolerance` 절이 없는 기본 정책 기준으로, 같은 입력에서 판정이 항상 같아야 한다.
    """
    authority, _, result = verify_statistical_claim(conditions, claimed)
    if authority.state == "unverifiable":
        pytest.skip("기계가 판정하지 않는 입력(패리티 대상 아님)")
    subject = _stat_subject(
        machine_value=result.value,
        machine_exact=result.exact_value,
        machine_approx=result.approx_value,
    )
    expected = {"pass": "ok", "fail": "defect"}[authority.state]
    assert _reconstruct(subject, claimed) == expected


def test_stat_reconstruct_parity_probe_discriminates() -> None:
    """패리티 탐침의 변별력 — 두 갈래(ok·defect)와 세 정책이 실제로 모두 밟힌다.

    전부 skip되거나 한쪽 결과만 나오면 위 패리티 검사는 아무것도 말하지 않는 위장이다.
    """
    seen: set[tuple[str, str]] = set()
    for conditions, claimed in [
        ("data=[1,2,3,4,5]; stat=mean", "3"),  # exact → pass
        ("data=[1,2,3,4,5]; stat=mean", "3.0000000001"),  # exact → fail
        ("data=[1,2,4]; stat=mean", "2.3333333333"),  # abs → pass
        ("data=[1,2,4]; stat=mean", "2.33"),  # abs → fail
        ("data=[1,2,3,4]; stat=std", "1.2909944487"),  # 무리수 abs → pass
    ]:
        authority, _, result = verify_statistical_claim(conditions, claimed)
        subject = _stat_subject(
            machine_exact=result.exact_value, machine_approx=result.approx_value
        )
        seen.add((result.policy, _reconstruct(subject, claimed)))
    assert seen == {
        ("기본→exact", "ok"),
        ("기본→exact", "defect"),
        ("기본→abs:0.000000001", "ok"),
        ("기본→abs:0.000000001", "defect"),
    }
