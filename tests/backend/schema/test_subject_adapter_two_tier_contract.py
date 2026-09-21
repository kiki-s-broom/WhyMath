"""과목 계약 **2층 구조**의 동결 — 필수층은 늘지 않고, 선택층은 늘어도 된다 (Kiki 판단 2026-08-31).

────────────────────────────────────────────────────────────────────────────
왜 산문이 아니라 테스트인가
────────────────────────────────────────────────────────────────────────────
"모든 과목에 강제되는 기본 계약"과 "선택적 검증 capability"를 나눈다는 판단은, 문서에만
적으면 **다음 세션이 모른 채로 어긴다**. 필수 Protocol에 메서드를 하나 더 다는 것은 5초면
되고 리뷰에서도 자연스러워 보이지만, 그 순간 역사·국어 어댑터는 `NotImplementedError`나 빈
구현을 강요당한다 — 그리고 빈 구현은 곧 "판정했다"는 거짓 신호가 된다.

그래서 필수층의 메서드 집합 자체를 상수로 동결한다. 늘리면 CI가 적색이 되고, 통과시키려면
아래 목록을 고치면서 **"왜 선택층으로 갈 수 없는가"를 적어야 한다**. 조용한 확장이 불가능해지는
것이 이 파일의 유일한 목적이다.

이 저장소에서 같은 부류의 실패가 반복됐다("검증 장치를 만들고 배선 확인 없이 완료 선언 금지"·
"정본화를 집행으로 착각한 완료 선언 금지"). 이 테스트는 그 계열의 *계약 확장* 축이다.
"""

from __future__ import annotations

from pydantic import BaseModel

from whymath_backend.schema import subject_adapter, verification_capabilities
from whymath_backend.schema.subject_adapter import (
    AnswerEvaluation,
    MisconceptionSignal,
    ProblemStatement,
    ProblemValidation,
    SubjectAdapter,
)

# ──────────────────────────────────────────────────────────────────────────
# 필수층 — 이 목록을 바꾸는 것은 "모든 과목이 반드시 제공한다"는 선언을 바꾸는 것이다.
# 추가 게이트: "Physics·Chemistry·History에도 **반드시** 존재하는가?" 예일 때만.
# 아니오면 `schema/verification_capabilities.py`(선택층)로 간다.
# ──────────────────────────────────────────────────────────────────────────
REQUIRED_METHODS: frozenset[str] = frozenset(
    {
        "evaluate_answer",  # 답 평가 — 채점 없는 과목은 없다
        "detect_misconception",  # 오개념 탐지 — 오답 원인 분석은 과목 무관
        "validate_problem",  # 문항 타당성 — 낼 수 있는 문제인지의 판정
    }
)


def _public_methods(protocol: type) -> frozenset[str]:
    """Protocol이 요구하는 공개 멤버 이름 — dunder·클래스 속성 제외."""
    inherited = set()
    for base in protocol.__mro__[1:]:
        inherited |= set(vars(base))
    own = {name for name in vars(protocol) if not name.startswith("_")}
    return frozenset(own - inherited)


def test_required_contract_has_not_silently_grown() -> None:
    """필수층이 3종 그대로인가 — 늘었으면 선택층으로 갈 수 없는 이유를 적어야 한다."""
    actual = _public_methods(SubjectAdapter) - {"subject_id"}
    assert actual == REQUIRED_METHODS, (
        f"SubjectAdapter 필수 메서드가 바뀌었다: {sorted(actual)} (기대 {sorted(REQUIRED_METHODS)}).\n"
        "늘렸다면 먼저 물어라 — 이 능력이 Physics·Chemistry·History에도 **반드시** 존재하는가?\n"
        "아니오면 schema/verification_capabilities.py(선택층)로 옮기고, 예면 이 목록과\n"
        "subject_adapter.py 모듈 docstring의 2층 표를 함께 고쳐라."
    )


# ──────────────────────────────────────────────────────────────────────────
# 후보 9종 전수 판정 (EOS-90 · 계획서 100 §3.9 Kiki 제시 목록)
#
# "과목마다 반드시 존재하는 능력만 계약에 넣는다"를 9후보에 기계 적용한 결과다. 판정 근거는
# `docs/reviews/subject_contract_v1_candidate_verdicts_2026-09-04.md`.
#
# 행선지는 넷뿐이다:
#   REQUIRED  — 필수층(SubjectAdapter). 모든 과목이 반드시 제공한다.
#   OPTIONAL  — 선택층(verification_capabilities). 있는 과목만. Core는 없을 때 경로를 갖는다.
#   DATA      — 계약 아님. 이미 과목 중립 스키마에 **데이터**로 존재한다 → Physics는 행만 채운다.
#   CORE_OWNED— 계약 아님. Core가 **이미 스스로** 하는 일이라 과목에 되물을 것이 없다.
#   ADAPTER_INTERNAL — 계약 아님. 어댑터 안에 있어도 되지만 Core가 위임할 진입점이 없다.
#
# 이 표를 기계가 기억하는 이유: 다음 세션이 "getConcept이 없네?"라며 필수층에 넣는 것을 막는다.
# 넣으면 아래 테스트가 판정 기록과 함께 RED가 된다.
# ──────────────────────────────────────────────────────────────────────────
CANDIDATE_VERDICTS: dict[str, str] = {
    # Kiki 후보명(camelCase) → 판정. 저장소 명명은 snake_case다.
    "evaluateAnswer": "REQUIRED",
    "detectMisconception": "REQUIRED",
    "validateProblem": "REQUIRED",
    # 조회(read)지 계산(compute)이 아니다 — 계약에 넣으면 어댑터가 ORM 위임층이 되고
    # schema가 db를 알게 되는 계층 역방향이 된다. 개념·엣지·성취기준 스키마는 이미 과목 중립.
    "getConcept": "DATA",
    "getPrerequisites": "DATA",
    "getLearningObjectives": "DATA",
    # l2.irt가 응답 통계만으로 난이도 b를 추정한다 — 문항 내용을 한 글자도 보지 않는다.
    "estimateDifficulty": "CORE_OWNED",
    # 위임할 공개 진입점 0건(설명 생성기는 전부 생성기 내부 비공개 함수).
    "generateExplanation": "ADAPTER_INTERNAL",
    # 유일한 선택층 후보. 단 현행 VisualizationStyle 16종이 전량 수학 어휘라
    # **중립 반환 타입 재설계가 전제**다. 그 전에는 계약이 될 수 없다.
    "getRepresentations": "OPTIONAL",
}

# camelCase 후보명 → 저장소의 snake_case 이름(필수층 판정 대조용).
_SNAKE = {
    "evaluateAnswer": "evaluate_answer",
    "detectMisconception": "detect_misconception",
    "validateProblem": "validate_problem",
    "getConcept": "get_concept",
    "getPrerequisites": "get_prerequisites",
    "getLearningObjectives": "get_learning_objectives",
    "estimateDifficulty": "estimate_difficulty",
    "generateExplanation": "generate_explanation",
    "getRepresentations": "get_representations",
}


def test_every_candidate_has_a_recorded_verdict() -> None:
    """Kiki 후보 9종이 빠짐없이 판정돼 있는가 — 판정하지 않은 채 넘어간 후보가 없어야 한다."""
    assert len(CANDIDATE_VERDICTS) == 9, sorted(CANDIDATE_VERDICTS)
    assert set(CANDIDATE_VERDICTS) == set(_SNAKE), "후보 목록과 이름 매핑이 어긋났다"
    allowed = {"REQUIRED", "OPTIONAL", "DATA", "CORE_OWNED", "ADAPTER_INTERNAL"}
    unknown = {k: v for k, v in CANDIDATE_VERDICTS.items() if v not in allowed}
    assert not unknown, f"정의되지 않은 행선지: {unknown}"


def test_only_required_verdicts_appear_in_the_required_tier() -> None:
    """판정과 실제 계약이 일치하는가 — REQUIRED만 프로토콜에 있고 나머지는 없어야 한다.

    누가 `get_concept`을 필수층에 추가하면 여기서 RED가 나고, 판정 기록(DATA)이 함께 보인다.
    판정을 바꾸려면 표를 고쳐야 하므로 조용한 확장이 불가능하다.
    """
    actual = _public_methods(SubjectAdapter) - {"subject_id"}
    for candidate, verdict in CANDIDATE_VERDICTS.items():
        name = _SNAKE[candidate]
        if verdict == "REQUIRED":
            assert name in actual, f"{candidate}는 REQUIRED 판정인데 필수층에 없다"
        else:
            assert name not in actual, (
                f"{candidate}가 필수층에 들어왔다 — 판정은 {verdict}였다.\n"
                "필수층으로 올리려면 CANDIDATE_VERDICTS를 고치고 판정 문서의 근거를 갱신하라."
            )


def test_required_tier_holds_exactly_the_required_verdicts() -> None:
    """역방향 — 필수층에 판정표 밖의 메서드가 몰래 들어오지 않았는가."""
    expected = {_SNAKE[c] for c, v in CANDIDATE_VERDICTS.items() if v == "REQUIRED"}
    actual = _public_methods(SubjectAdapter) - {"subject_id"}
    assert actual == expected == REQUIRED_METHODS, (actual, expected, REQUIRED_METHODS)


def test_optional_capabilities_are_not_required_of_every_subject() -> None:
    """선택층 능력이 필수층으로 새어 들어오지 않았는가 — 두 목록이 겹치면 분리가 무너진 것이다."""
    optional_methods = set()
    for name in verification_capabilities.__all__:
        member = getattr(verification_capabilities, name)
        if isinstance(member, type):
            optional_methods |= _public_methods(member)
    overlap = optional_methods & REQUIRED_METHODS
    assert (
        not overlap
    ), f"선택 능력이 필수 계약과 겹친다: {sorted(overlap)} — 과목이 두 번 강요받는다"


def test_optional_tier_is_discoverable_from_the_required_tier() -> None:
    """필수층 문서가 선택층을 **가리키는가**.

    가리키지 않으면 필수 계약만 읽은 사람이 선택층의 존재를 모르고 여기에 메서드를 추가한다
    — 이 2층 구조가 깨지는 가장 흔한 경로가 '몰라서'다. 링크는 장식이 아니라 방어다.
    """
    doc = subject_adapter.__doc__ or ""
    assert "verification_capabilities" in doc, "필수 계약 docstring이 선택층을 가리키지 않는다"


def test_math_adapter_provides_required_and_may_provide_optional() -> None:
    """수학 어댑터는 필수 3종을 **전부** 제공하고, 선택 능력은 별도 객체로 제공한다.

    선택 능력이 `MathSubjectAdapter`의 메서드로 들어가 있지 않은지도 함께 본다 — 들어가 있으면
    "필수 계약을 만족하는 객체"와 "선택 능력을 가진 객체"가 같아져, 다음 과목이 그 모양을
    따라 하다가 선택 능력을 필수처럼 구현하게 된다.
    """
    from whymath_backend.l4.subject_adapter_math import MathSubjectAdapter

    adapter = MathSubjectAdapter()
    for method in REQUIRED_METHODS:
        assert callable(getattr(adapter, method, None)), f"수학 어댑터가 필수 {method} 미제공"
    for optional in ("identity_status", "verify_chain", "extract_sealed"):
        assert not hasattr(
            adapter, optional
        ), f"선택 능력 {optional}이 필수 어댑터 객체에 달려 있다 — 2층 분리가 흐려진다"


# ══════════════════════════════════════════════════════════════════════════
# EOS-91 — Provisional 상태의 단조 축소 래칫 (Kiki 지시 2026-09-05)
#
# 위 REQUIRED_METHODS는 *메서드*만 본다. 계약의 과목 중립성이 실제로 깨지는 자리는
# **필드**인데(예: `conditions`가 물리 관계식을 담을 수 있는가), 실측 결과 필드 축은
# 동결이 **0건**이었다 — 필드를 늘려도 줄여도 CI가 조용했다.
#
# 규칙 2조를 기계로 옮기면 비대칭 래칫이 된다:
#   · 확장(신규 필드) → **무조건 RED**. 예외 경로 없음(규칙 2조 나 "Core 확장 금지").
#   · 축소(필드 제거) → 강등 대장 DEMOTED_FIELDS 경유로만 통과(규칙 2조 가).
#     조용한 삭제와 *기록된 강등*을 구분하기 위한 것이다 — 대장이 곧 강등의 증적이다.
# ══════════════════════════════════════════════════════════════════════════

CORE_CONTRACT_FIELDS: dict[str, frozenset[str]] = {
    "ProblemStatement": frozenset(
        {"problem_ref", "question_text", "answer", "answer_kind", "conditions"}
    ),
    "AnswerEvaluation": frozenset({"state", "reason", "checked_axes"}),
    "ProblemValidation": frozenset({"state", "reason", "machine_axes", "residual_axes"}),
    "MisconceptionSignal": frozenset({"code", "confidence", "matched_signals"}),
}
"""프로브 전 Core 계약의 필드 전수 — 이 집합은 **늘어날 수 없고**, 줄어들면 강등 대장을 요구한다."""

DEMOTED_FIELDS: dict[str, str] = {}
"""프로브에서 깨져 Core→Adapter 강등된 필드 → 이관처.

키는 `"<DTO>.<필드>"`, 값은 이관처(예: "verification_capabilities.SymbolicIdentity" ·
"l4.subject_adapter_math 내부"). **프로브(EOS-92) 전에는 비어 있는 것이 정상이다** —
여기에 항목이 생겼다는 것은 어떤 필드가 과목 중립이 아님이 증명됐다는 뜻이다.
"""

_DTO_TYPES: dict[str, type[BaseModel]] = {
    "ProblemStatement": ProblemStatement,
    "AnswerEvaluation": AnswerEvaluation,
    "ProblemValidation": ProblemValidation,
    "MisconceptionSignal": MisconceptionSignal,
}


def test_core_contract_fields_never_grow() -> None:
    """규칙 2조 (나) — Core 확장 금지. 필드가 하나라도 늘면 예외 없이 RED."""
    grown: dict[str, list[str]] = {}
    for name, frozen in CORE_CONTRACT_FIELDS.items():
        actual = frozenset(_DTO_TYPES[name].model_fields)
        if extra := actual - frozen:
            grown[name] = sorted(extra)
    assert not grown, (
        f"Core 계약 필드가 늘었다: {grown}\n"
        "규칙 2조 (나) Core 확장 금지 — 이 계약은 프로브를 거치며 **줄어들 수만 있다**.\n"
        "새 능력은 schema/verification_capabilities.py(선택층) 또는 어댑터 내부로 보내라.\n"
        "필수층에 넣어야만 하는 근거가 있다면 Kiki 판단을 받고 이 상수와 계약 docstring의\n"
        "상태 절을 함께 고쳐라(조용한 확장 불가)."
    )


def test_core_contract_shrink_requires_demotion_ledger() -> None:
    """규칙 2조 (가) — 강등은 대장 경유. 대장 없는 필드 제거는 조용한 삭제이므로 RED."""
    for name, frozen in CORE_CONTRACT_FIELDS.items():
        actual = frozenset(_DTO_TYPES[name].model_fields)
        for missing in sorted(frozen - actual):
            key = f"{name}.{missing}"
            assert key in DEMOTED_FIELDS, (
                f"Core 계약에서 필드가 사라졌는데 강등 대장에 없다: {key}\n"
                "규칙 2조 (가)는 강등을 *요구*하지만, 강등은 **기록되어야** 강등이다.\n"
                f'DEMOTED_FIELDS["{key}"] = "<이관처>" 를 적고 프로브 근거(EOS-92)를 남겨라.'
            )
            assert DEMOTED_FIELDS[key].strip(), f"{key} 강등 대장에 이관처가 비어 있다"


def test_demotion_ledger_only_names_real_contract_fields() -> None:
    """강등 대장이 실재하지 않는 필드를 가리키지 않는가 — 대장 자체의 오타·유령 항목 차단."""
    for key in DEMOTED_FIELDS:
        dto, _, field = key.partition(".")
        assert dto in CORE_CONTRACT_FIELDS, f"강등 대장의 알 수 없는 DTO: {key}"
        assert field in CORE_CONTRACT_FIELDS[dto], (
            f"강등 대장이 계약에 없던 필드를 가리킨다: {key}\n"
            "강등은 *있던 것*을 내보내는 일이다 — 없던 필드는 강등 대상이 아니다."
        )


def test_demotion_ledger_entries_prove_actual_removal() -> None:
    """대장에 적힌 필드가 **실제로 계약에서 사라졌는가** — 허위 강등 차단.

    바로 위 두 검사만으로는 대장이 증적이 되지 못한다: 필드를 그대로 둔 채 대장에만 적으면
    (기존 필드 + 비어 있지 않은 이관처) 셋 다 통과한다(실측 확인·PR #986 Codex P2).
    그러면 "Core 계약이 축소됐다"고 대장이 말하는데 계약은 그대로인 상태를 CI가 승인한다.
    강등의 증적이려면 **제거 사실 자체**를 봐야 한다.
    """
    still_present = {}
    for key in DEMOTED_FIELDS:
        dto, _, field = key.partition(".")
        if dto in _DTO_TYPES and field in _DTO_TYPES[dto].model_fields:
            still_present[key] = DEMOTED_FIELDS[key]
    assert not still_present, (
        f"강등 대장이 강등을 주장하는데 필드가 계약에 그대로 있다: {still_present}\n"
        "규칙 2조 (가)의 강등은 Core에서 **빼는** 일이다 — 대장 기재만으로는 강등이 아니다.\n"
        "필드를 제거했으면 이 검사는 통과한다. 제거하지 않을 거면 대장에서 지워라."
    )


# 상태 절의 **제목 줄** — 이 한 줄이 계약의 상태를 말한다.
# 문서 어딘가에 "Provisional"이 있는지 보면 안 된다: 아래 "왜 Frozen이 아니라 Provisional인가"
# 절이 그 단어를 품고 있어, 제목만 Frozen으로 바꿔도 토큰 검사는 초록이다(실측 확인·PR #986
# Codex P2). 상태는 제목이 말하는 것이므로 제목을 정확히 동결한다.
STATUS_HEADING = "## 🚧 상태: **Provisional** — pending cross-subject probe (9/27)"


def test_contract_status_heading_is_provisional_until_probe() -> None:
    """상태 **제목 줄** 동결 — 프로브(EOS-92) 없이 Provisional을 되돌리면 RED.

    이 검사가 없으면 상태 절은 산문일 뿐이라 다음 세션이 무심코 'Frozen'으로 되돌린다.
    제목 줄 자체를 계약으로 고정해, 되돌리려면 이 테스트를 함께 고치는 **의도적 행위**를 요구한다.
    """
    doc = subject_adapter.__doc__ or ""
    headings = [ln.strip() for ln in doc.splitlines() if ln.lstrip().startswith("## ")]
    assert headings, "계약 docstring에 절 제목이 하나도 없다 — 파서가 공허하게 통과하는 상태"

    status_headings = [h for h in headings if "상태:" in h]
    assert len(status_headings) == 1, (
        f"상태 제목 줄이 {len(status_headings)}개다(1개여야 한다): {status_headings}\n"
        "두 개면 어느 것이 계약인지 결정 불가이고, 0개면 상태 절이 사라진 것이다."
    )
    assert status_headings[0] == STATUS_HEADING, (
        f"계약 상태 제목이 바뀌었다:\n  실제: {status_headings[0]}\n  기대: {STATUS_HEADING}\n"
        "교차 과목 프로브(EOS-92) 통과 전까지 이 계약은 Math 단일 과목에서 도출된 가설이다.\n"
        "되돌리려면 프로브 결과를 근거로 이 상수와 계약 docstring을 함께 고쳐라."
    )
    for clause in ("강등", "Core 확장 금지", "ADR", "중복 구현", "3건을 초과"):
        assert clause in doc, f"프로브 결과 처리 규칙 3조가 상태 절에 없다: {clause!r}"
    # (다) 출구가 없으면 (가)·(나)는 위반을 숨기는 금지가 된다 — 출구 조항의 존재를 동결한다.
    assert "(다)" in doc, "규칙 (다) 출구 조항이 없다 — 출구 없는 금지는 편법을 부른다"
    # 래칫이 못 잡는 축을 문서가 스스로 밝히는가 — 이 한계 표기가 사라지면 9/27에
    # 'CI 초록 = 계약 준수'로 오판한다.
    assert "필드 개수" in doc, "래칫의 한계('기계는 필드 개수만 본다')가 상태 절에서 사라졌다"
    # 기계가 못 보는 축에 소유자가 지목돼 있는가 — "기계 집행 없음"에서 끝나면 알려진 갭에
    # 소유자가 없는 상태다. 보상 통제(EOS-92)의 지목 자체를 동결한다.
    assert "검증 책임은 `EOS-92`" in doc, (
        "의미적 확장 축의 검증 책임자(EOS-92)가 한계 절에서 사라졌다 — 기계 집행이 없는 갭은\n"
        "보상 통제를 지목해야 소유자가 있는 갭이 된다."
    )
    # 한계 절은 **두 축**을 가른다(ARCH-43 · 2026-09-06): *Core가 값을 읽는가*(해석 축)는 정적
    # 게이트가 집행하고, *뜻이 뒤틀리는가*(의미 축)는 EOS-92 프로브의 사람 판정이 보상 통제다.
    # 게이트 지목이 사라지면 "기계 집행은 없다"로 되돌아간 것(없는 척)이고, 축 구분이 사라지면
    # 게이트가 의미 축까지 잡는 것처럼 읽힌다(있는 척) — 둘 다 금지.
    assert (
        "eos_opaque_payload_gate.py" in doc and "ARCH-43" in doc
    ), "해석 축의 기계 집행(ARCH-43 게이트) 지목이 한계 절에서 사라졌다 — 실재하는 집행을 없는 척 금지"
    assert "해석 축" in doc and "의미 축" in doc, "한계 절의 해석 축/의미 축 구분이 사라졌다"
