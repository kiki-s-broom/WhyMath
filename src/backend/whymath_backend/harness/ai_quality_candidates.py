"""P3-10 AI 품질 평가 — 평가 대상(후보 응답) 만들기·읽기와 나쁜 응답 주입(축별 음성 대조군).

후보 응답의 출처 3종
--------------------
1. **`eos-deterministic`(기본)** — 이 저장소의 *현재 코드*가 LLM 없이 학생에게 내는 출력이다.
   LLM이 꺼졌거나 P3-09 게이트에 거부됐을 때 실제로 나가는 결정론 레이어를 그대로 부른다:
   - 힌트 턴: 검수 힌트 생성기 `l4.hint_content.populate.build_path_hints`(S4-11 · 게이트 3종
     포함)가 만든 `verified` 힌트 중에서 서빙 reader와 **같은 사다리 규칙**
     (`l4.hint_content.store.select_ladder_hint` — P3-77 L3 공백 대체)으로 엔진 단계
     (`decide_hint_level`)의 것을 고른다. L2로 내려 낸 경우 `hint_level`도 2로 적는다(표시 =
     본문). 하나도 없으면 하네스 중립 질문.
   - 선택 턴: 오답 보기 진단 `l4.misconception.distractor_link.distractor_link_matches`(품질
     게이트 포함) → 개입 발문 `l4.misconception.intervene.select_intervention`. 진단이 없으면
     정답 턴은 격려 템플릿, 오답 턴은 중립 질문(`wh1_loop` 공개 상수).
   - 구조체: P3-09 빌더 `wh1_tutor_output.build_tutor_output`(진단·전략·다음 행동·
     `mastery_update_allowed`).
   이것이 hermetic 환경에서 잴 수 있는 **유일한 실제 튜터 출력**이다.
2. **`--responses <jsonl>`(외부)** — 라이브 LLM 튜터를 같은 평가 사례에 돌려 모은 응답. 수집
   도구는 `ai_quality_live_collect`(P3-78)이며, 이 모듈의 서버 측 재료(`engine_hint_level`·
   `case_hypotheses`)를 그대로 써서 결정론 후보와 같은 진단·힌트 단계로 구조체를 조립한다.
   형식은 `RESPONSE_SCHEMA` 한 줄 한 응답.
3. **주입(`inject`)** — 위 둘 중 하나에 축별로 나쁜 응답을 넣은 음성 대조군. 판정기가 실패 상태에서
   실제로 실패 신호를 내는지(변별력) 보는 데만 쓴다.

주입은 **적용됐는지 스스로 센다** — 바뀐 응답 수(`mutated`)가 0이면 그 주입은 아무것도 시험하지
않은 것이므로, 자가 점검이 실패로 센다(CLAUDE.md '주입 자체의 실재').
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.ai_quality_eval_set import KIND_HINT, EvalCase, EvalSet
from whymath_backend.harness.ai_quality_judges import AXES, TutorResponse
from whymath_backend.harness.ai_quality_registry import Registry, normalize_text
from whymath_backend.harness.wh1_loop import (
    ENCOURAGE_FALLBACK_UTTERANCE,
    NEUTRAL_GUIDE_UTTERANCE,
    EndTurnType,
)
from whymath_backend.harness.wh1_tutor_output import TutorTurnOutput, build_tutor_output
from whymath_backend.l4.hint_content.generator import ConceptRef
from whymath_backend.l4.hint_content.models import Hint
from whymath_backend.l4.hint_content.populate import build_path_hints
from whymath_backend.l4.hint_content.store import (
    LADDER_AS_REQUESTED,
    LADDER_CAPPED_TO_FLOW,
    PathInput,
    select_ladder_hint,
)
from whymath_backend.l4.hint_deferral import decide_hint_level
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.distractor_link import distractor_link_matches
from whymath_backend.l4.misconception.hypothesis import MisconceptionHypothesis
from whymath_backend.l4.misconception.intervene import select_intervention
from whymath_backend.l4.misconception.models import MisconceptionMatch
from whymath_backend.l4.subject_adapter_math import math_answer_value_exposure

__all__ = [
    "CANDIDATE_EOS",
    "INJECTIONS",
    "RESPONSE_SCHEMA",
    "CandidateError",
    "build_eos_candidate",
    "case_hypotheses",
    "dump_responses",
    "engine_hint_level",
    "inject",
    "load_responses",
    "parse_responses",
]

CANDIDATE_EOS: Final = "eos-deterministic"
RESPONSE_SCHEMA: Final = "ai-quality-response/v1"

ResponseMap = dict[str, TutorResponse]


class CandidateError(RuntimeError):
    """후보 응답 생성·적재 실패 — 측정 실패로 올린다."""


# ──────────────────────────────────────────────────────────────────────────
# 서버 측 재료 — 결정론 후보와 라이브 수집(P3-78)이 함께 쓰는 단일 원천
# ──────────────────────────────────────────────────────────────────────────
def engine_hint_level(case: EvalCase) -> int:
    """사례의 결정론 엔진 힌트 단계(`decide_hint_level`) — LLM은 힌트 단계를 정하지 않는다.

    힌트 사례는 사례의 학생 신호로, 선택 사례는 신호 없는 첫 턴(빈 입력·1턴·직전 없음)으로 정한다.
    코치가 러너에 넘기는 `decision.hint_level`과 같은 함수다.
    """
    if case.kind == KIND_HINT:
        assert case.signals is not None
        return decide_hint_level(
            student_input=case.signals.student_input,
            turn_count=case.signals.turn_count,
            prev_hint_level=case.signals.prev_hint_level,
        )
    return decide_hint_level(student_input="", turn_count=1, prev_hint_level=None)


def _choice_match(case: EvalCase, eval_set: EvalSet) -> MisconceptionMatch | None:
    """고른 보기의 오답 매핑 진단(품질 게이트 포함) 최상위 — 없으면 None."""
    material = eval_set.materials[case.problem_id]
    matches = distractor_link_matches(list(material.distractor_map), case.selected_choice_index)
    return matches[0] if matches else None


def _hypothesis_of(match: MisconceptionMatch) -> MisconceptionHypothesis:
    return MisconceptionHypothesis(
        misconception_id=match.misconception.id,
        confidence=match.confidence,
        turns_since_evidence=0,
        evidence_count=1,
    )


def case_hypotheses(case: EvalCase, eval_set: EvalSet) -> tuple[MisconceptionHypothesis, ...]:
    """코치가 큐레이션해 러너에 넘기는 *초기 활성 가설*에 해당하는 것 — 결정론 진단만.

    힌트 사례는 빈 튜플(이번 턴 오답 진단 재료가 없다), 선택 사례는 오답 매핑 진단 최상위 1건.
    구조체의 `diagnosis`는 이 가설에서만 온다(LLM은 진단을 결정하지 않는다 — P3-09).
    """
    if case.kind == KIND_HINT:
        return ()
    match = _choice_match(case, eval_set)
    return () if match is None else (_hypothesis_of(match),)


# ──────────────────────────────────────────────────────────────────────────
# eos-deterministic
# ──────────────────────────────────────────────────────────────────────────
def _assemble(
    case: EvalCase,
    *,
    explanation: str,
    action: EndTurnType,
    hint_level: int,
    hypotheses: tuple[MisconceptionHypothesis, ...],
) -> TutorTurnOutput | str:
    return build_tutor_output(
        explanation=explanation,
        explanation_source="harness_template",
        action_type=action,
        mode_guard_replaced=False,
        verify_verdict=case.verdict,
        hypotheses=hypotheses,
        concept_id=case.concept_id,
        known_concept_ids=frozenset({case.concept_id}),
        hint_level=hint_level,
    )


def _hint_turn(
    case: EvalCase, eval_set: EvalSet, registry: Registry, cache: dict[str, tuple[Hint, ...]]
) -> tuple[str, EndTurnType, int, str | None]:
    assert case.signals is not None and case.target_step is not None
    level = engine_hint_level(case)
    hints = cache.get(case.problem_id)
    if hints is None:
        material = eval_set.materials[case.problem_id]
        concept = ConceptRef(
            concept_id=case.concept_id,
            name=registry.concepts[case.concept_id].name_ko,
            source="problem_primary",
        )
        steps = material.solution_steps
        hints = build_path_hints(
            PathInput(
                solution_path_id=f"aq-eval-{material.problem_id}",
                problem_id=material.problem_uuid,
                step_contents=steps,
                step_verified=(True,) * len(steps),
                step_concepts=(concept,) * len(steps),
                final_answer=material.answer or None,
            ),
            value_exposure=math_answer_value_exposure(),
        ).hints
        cache[case.problem_id] = hints
    pick = select_ladder_hint(hints, hint_level=level, from_step_order=case.target_step)
    if pick is None:
        return NEUTRAL_GUIDE_UTTERANCE, "질문", level, "검수 통과 힌트 없음 → 하네스 중립 질문"
    note: str | None = None
    if pick.substitution != LADDER_AS_REQUESTED:
        note = (
            f"L{level} 사다리 대체({pick.substitution}) — "
            f"{pick.hint.solution_step_ref.step_order}단계 L{pick.hint.level}"
        )
    if pick.substitution == LADDER_CAPPED_TO_FLOW:
        note = (
            f"{note} · 의도적 제외(P3-77 ②): 이 단계와 그 앞 단계에 쓸 수 있는 검수 L3가 없다"
            "(부분 시연이 정답·최종 값을 드러내 게이트가 거부) — 뒤 단계 L3는 노출이 두 칸이 "
            "되어 쓰지 않고, 정답을 드러내는 L3 대신 L2를 정직한 표시(hint_level=2)로 낸다. "
            "엔진 단계와의 차이는 결함이 아니라 판정이다(docs/reviews/"
            "p3_77_hint_l3_gap_pedagogy_judgment_2026-10-22.md)"
        )
    return pick.hint.content, "힌트", pick.hint.level, note


def _choice_turn(
    case: EvalCase, eval_set: EvalSet
) -> tuple[str, EndTurnType, tuple[MisconceptionHypothesis, ...]]:
    match = _choice_match(case, eval_set)
    if match is not None:
        decision = select_intervention(match)
        prompt = decision.prompt if decision is not None else NEUTRAL_GUIDE_UTTERANCE
        return prompt, "질문", (_hypothesis_of(match),)
    if case.verdict == "correct":
        return ENCOURAGE_FALLBACK_UTTERANCE, "격려", ()
    return NEUTRAL_GUIDE_UTTERANCE, "질문", ()


def build_eos_candidate(eval_set: EvalSet, registry: Registry) -> ResponseMap:
    """현재 코드의 결정론 튜터 출력 — 사례마다 응답 1건(LLM 0·DB 0)."""
    cache: dict[str, tuple[Hint, ...]] = {}
    out: ResponseMap = {}
    for case in eval_set.cases:
        note: str | None = None
        if case.kind == KIND_HINT:
            text, action, level, note = _hint_turn(case, eval_set, registry, cache)
            hypotheses: tuple[MisconceptionHypothesis, ...] = ()
        else:
            text, action, hypotheses = _choice_turn(case, eval_set)
            level = engine_hint_level(case)
        built = _assemble(
            case, explanation=text, action=action, hint_level=level, hypotheses=hypotheses
        )
        if isinstance(built, str):
            # P3-09 빌더가 거부하면 서빙 경로는 결정론 폴백으로 간다 — 그 폴백(중립 질문)을 싣는다.
            note = f"P3-09 빌더 거부({built}) → 하네스 중립 질문"
            built = _assemble(
                case,
                explanation=NEUTRAL_GUIDE_UTTERANCE,
                action="질문",
                hint_level=level,
                hypotheses=hypotheses,
            )
            if isinstance(built, str):
                raise CandidateError(f"{case.case_id}: 폴백 구조체도 거부됐다({built})")
        out[case.case_id] = TutorResponse(
            case_id=case.case_id,
            tutor_output=built.model_dump(mode="json"),
            origin=CANDIDATE_EOS,
            note=note,
        )
    return out


# ──────────────────────────────────────────────────────────────────────────
# 외부 응답 JSONL
# ──────────────────────────────────────────────────────────────────────────
def parse_responses(text: str, *, source: str = "<text>") -> ResponseMap:
    """`RESPONSE_SCHEMA` JSONL → 응답 맵. 구조 위반·중복은 `CandidateError`(0건도 실패)."""
    out: ResponseMap = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{source}:{number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CandidateError(f"{where}: {type(exc).__name__}") from exc
        if not isinstance(row, dict) or row.get("schema") != RESPONSE_SCHEMA:
            raise CandidateError(f"{where}: schema 가 {RESPONSE_SCHEMA!r} 가 아니다")
        case_id = row.get("case_id")
        output = row.get("tutor_output")
        refs = row.get("referenced_concept_ids", [])
        if not isinstance(case_id, str) or not isinstance(output, dict):
            raise CandidateError(f"{where}: case_id(str)·tutor_output(object) 필수")
        if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
            raise CandidateError(f"{where}: referenced_concept_ids 는 문자열 배열")
        if case_id in out:
            raise CandidateError(f"{where}: 중복 case_id {case_id!r}")
        out[case_id] = TutorResponse(
            case_id=case_id,
            tutor_output=output,
            referenced_concept_ids=tuple(refs),
            origin=str(row.get("origin", "external")),
            note=row.get("note") if isinstance(row.get("note"), str) else None,
        )
    if not out:
        raise CandidateError(f"{source}: 응답 0건")
    return out


def load_responses(path: Path) -> ResponseMap:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CandidateError(f"응답 파일을 읽지 못했다 ({path}): {type(exc).__name__}") from exc
    return parse_responses(text, source=str(path))


def dump_responses(responses: Mapping[str, TutorResponse]) -> str:
    rows = []
    for case_id in sorted(responses):
        r = responses[case_id]
        rows.append(
            json.dumps(
                {
                    "schema": RESPONSE_SCHEMA,
                    "case_id": r.case_id,
                    "tutor_output": dict(r.tutor_output),
                    "referenced_concept_ids": list(r.referenced_concept_ids),
                    "origin": r.origin,
                    "note": r.note,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return "".join(row + "\n" for row in rows)


# ──────────────────────────────────────────────────────────────────────────
# 나쁜 응답 주입 — 축별 음성 대조군
# ──────────────────────────────────────────────────────────────────────────
_FALSE_ARITHMETIC: Final[tuple[tuple[str, int, int], ...]] = (
    ("6*7 = 41", 42, 41),
    ("12*12 = 140", 144, 140),
    ("17*19 = 300", 323, 300),
)
"""거짓 산술(식, 좌변 값, 우변 값) — 정답과 같은 값이 아닌 것을 골라 누설 축을 건드리지 않는다."""

_FAKE_CONCEPT_ID: Final = "math.calculus.mibun-yeokryu-jeongri"
_FAKE_STANDARD_CODE: Final = "[12미적Ⅰ-02-99]"


def _with_output(response: TutorResponse, origin: str, **changes: Any) -> TutorResponse:
    output = dict(response.tutor_output)
    refs = changes.pop("referenced_concept_ids", response.referenced_concept_ids)
    output.update(changes)
    return replace(response, tutor_output=output, referenced_concept_ids=tuple(refs), origin=origin)


def _text(response: TutorResponse) -> str:
    value = response.tutor_output.get("explanation")
    return value if isinstance(value, str) else ""


def _answer_int(eval_set: EvalSet, case: EvalCase) -> str:
    return eval_set.materials[case.problem_id].answer.strip()


def _inject_math(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None:
            continue
        answer = _answer_int(eval_set, case)
        claim = next(
            (c for c, lhs, rhs in _FALSE_ARITHMETIC if answer not in (str(lhs), str(rhs))),
            _FALSE_ARITHMETIC[0][0],
        )
        out[case.case_id] = _with_output(
            r, "injected:math_correctness", explanation=f"{_text(r)} 참고로 {claim}이야."
        )
    return out


def _inject_leak(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None or case.answer_known_to_student:
            continue
        answer = _answer_int(eval_set, case)
        out[case.case_id] = _with_output(
            r, "injected:answer_leak", explanation=f"{_text(r)} 정답은 {answer}이야."
        )
    return out


def _inject_misconception(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    ordered = sorted(CATALOG_BY_ID)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None or not case.misconception_labeled:
            continue
        wrong = next(k for k in ordered if k != case.expected_misconception_id)
        diagnosis = dict(r.tutor_output.get("diagnosis") or {})
        diagnosis.update({"misconception_id": wrong, "confidence": 0.9})
        out[case.case_id] = _with_output(r, "injected:misconception_accuracy", diagnosis=diagnosis)
    return out


def _inject_hint(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    """사다리 내용을 거꾸로 — L1·L2 자리에 L3 본문(조기 노출), L3 자리에 L1 본문(노출 부족)."""
    out = dict(base)
    ladders: dict[str, dict[int, EvalCase]] = {}
    for case in eval_set.cases:
        if case.kind == KIND_HINT and case.ladder_id and case.ladder_pos:
            ladders.setdefault(case.ladder_id, {})[case.ladder_pos] = case
    for cases in ladders.values():
        top, bottom = cases.get(3), cases.get(1)
        if top is None or bottom is None:
            continue
        top_r, bottom_r = base.get(top.case_id), base.get(bottom.case_id)
        if top_r is None or bottom_r is None:
            continue
        for pos, case in cases.items():
            r = base.get(case.case_id)
            if r is None:
                continue
            source = bottom_r if pos == 3 else top_r
            out[case.case_id] = _with_output(
                r, "injected:hint_appropriateness", explanation=_text(source)
            )
    return out


def _inject_consistency(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None:
            continue
        origin = "injected:explanation_consistency"
        if case.verdict in ("incorrect", "unverifiable"):
            out[case.case_id] = _with_output(
                r,
                origin,
                explanation="좋아, 정답이야! 정확하게 잘 풀었어.",
                response_strategy="encouragement",
                next_action="continue_dialogue",
            )
        elif case.verdict == "correct":
            out[case.case_id] = _with_output(
                r,
                origin,
                explanation="이 답은 틀렸어. 처음부터 다시 풀어 보자.",
                response_strategy="guided_question",
                next_action="revise_solution",
            )
        else:
            out[case.case_id] = _with_output(r, origin, next_action="solve_probe")
    return out


def _mention_target(registry: Registry, candidates: list[str]) -> str | None:
    """이름이 본문 탐지 어휘에 있고(4자 이상) 같은 이름의 다른 개념이 없는 첫 개념."""
    lexicon = dict(registry.name_lexicon)
    for cid in candidates:
        name = normalize_text(registry.concepts[cid].name_ko)
        if lexicon.get(name) == frozenset({cid}):
            return cid
    return None


def _inject_level(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    """아직 배우지 않은 개념(현재 개념의 후손 — 범위 안 먼저)을 끌어온다. 후손 없으면 주입 불가."""
    out = dict(base)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None:
            continue
        later = registry.descendants(case.concept_id)
        ordered = sorted(later, key=lambda c: (c not in registry.scope_concepts, c))
        target = _mention_target(registry, ordered)
        if target is None:
            continue
        name = registry.concepts[target].name_ko
        out[case.case_id] = _with_output(
            r,
            "injected:student_level_fit",
            explanation=f"{_text(r)} 「{name}」도 같이 떠올려 볼까?",
            referenced_concept_ids=(*r.referenced_concept_ids, target),
        )
    return out


def _out_of_scope_target(registry: Registry) -> str | None:
    """범위 밖이면서 어느 명세 개념의 후손도 아니고(수준 축 분리) 고등 밴드인 첫 개념."""
    later_any = frozenset().union(*(registry.descendants(c) for c in registry.scope_concepts))
    pool = sorted(
        cid
        for cid, info in registry.concepts.items()
        if cid not in registry.allowed_scope_concepts
        and cid not in later_any
        and info.band is not None
        and info.band.value == "고등"
    )
    return _mention_target(registry, pool)


def _inject_scope(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    target = _out_of_scope_target(registry)
    if target is None:
        return out
    name = registry.concepts[target].name_ko
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None:
            continue
        out[case.case_id] = _with_output(
            r,
            "injected:curriculum_scope",
            explanation=f"{_text(r)} 「{name}」과 비슷하게 생각해 보자.",
            referenced_concept_ids=(*r.referenced_concept_ids, target),
        )
    return out


def _inject_hallucination(eval_set: EvalSet, registry: Registry, base: ResponseMap) -> ResponseMap:
    out = dict(base)
    for case in eval_set.cases:
        r = base.get(case.case_id)
        if r is None:
            continue
        diagnosis = dict(r.tutor_output.get("diagnosis") or {})
        diagnosis["concept_id"] = _FAKE_CONCEPT_ID
        out[case.case_id] = _with_output(
            r,
            "injected:hallucination",
            diagnosis=diagnosis,
            explanation=f"{_text(r)} 성취기준 {_FAKE_STANDARD_CODE}에서 배운 걸 떠올려 봐.",
        )
    return out


INJECTIONS: Final[Mapping[str, Callable[[EvalSet, Registry, ResponseMap], ResponseMap]]] = {
    "math_correctness": _inject_math,
    "answer_leak": _inject_leak,
    "misconception_accuracy": _inject_misconception,
    "hint_appropriateness": _inject_hint,
    "explanation_consistency": _inject_consistency,
    "student_level_fit": _inject_level,
    "hallucination": _inject_hallucination,
    "curriculum_scope": _inject_scope,
}
assert tuple(INJECTIONS) == AXES, "주입은 8축과 1:1이어야 한다"


def inject(
    axis: str, eval_set: EvalSet, registry: Registry, base: Mapping[str, TutorResponse]
) -> tuple[ResponseMap, int]:
    """축 하나의 나쁜 응답을 넣는다 → (주입된 응답 맵, 실제로 바뀐 응답 수)."""
    if axis not in INJECTIONS:
        raise CandidateError(f"알 수 없는 주입 축 {axis!r}")
    mutated = INJECTIONS[axis](eval_set, registry, dict(base))
    changed = sum(
        1
        for case_id, r in mutated.items()
        if case_id in base
        and (
            dict(r.tutor_output) != dict(base[case_id].tutor_output)
            or r.referenced_concept_ids != base[case_id].referenced_concept_ids
        )
    )
    return mutated, changed
