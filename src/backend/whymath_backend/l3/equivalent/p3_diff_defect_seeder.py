"""P3-03 미분 은행 감사자 자격 측정 — 은행 전용 결함 주입기(순수·결정론·LLM 0).

설계 정본: `docs/standards/superhuman_verification_standard.md` §3 "결함 주입 강등전"과
`docs/data/p3_calculus1_diff_audit/qualification/README.md`(이 은행의 감사자 자격 측정 절차).

왜 따로 두는가
--------------
기존 주입기 `defect_seeder.py`는 이차방정식 스켈레톤 후보(`CandidateProblem`)에 결함을 심는다.
이 은행(`problem_bank_p3_calculus1_diff_v0` · 504건)은 1~4회차 감사에서 **다른 결함**으로
떨어졌다 — 미분 없이 풀리는 우회로·문장 표기·해설 단계·오개념 선지 연결
(`docs/data/p3_calculus1_diff_audit/round*/defects.json`). 감사자의 검출률을 이 은행에 대해
재려면 그 결함 유형을 **이 은행의 실제 문항**에 심어야 한다. 그래서 같은 원리(정답지를 우리가
안다 → 사람 라벨 0)로 은행 JSONL 레코드를 직접 변조하는 주입기를 이 모듈에 둔다.

결함 7종(정답지 GT는 구성상 확정 — 생성 시 단언)
------------------------------------------------
① `answer_error` 정답 오기 — 정답+1(답·검산 맵 둘 다 / 답만), 선지 문항은 오답 선지로 교체,
   개수형은 개수를 바꾼다. GT = SymPy(`verify_answer`·`verify_real_root_count`)가 원본 pass·
   변조 fail.
② `ambiguous_solution` 해 다중·모호 — 발문의 유일성 조건('양수 a'·'x좌표가 양수인 점'·
   '중 큰 값'·'열린구간에 속하지 않는 근')을 지운다. 검산 재료는 그대로 두거나(발문만) 함께
   푼다(발문+검산). GT = SymPy로 검산 주식의 해가 2개 이상(증가·감소가 바뀌는 점이면 부호가
   바뀌는 근이 2개 이상).
③ `derivative_shortcut` 미분 없이 풀리는 우회로 — 평균변화율·극값 위치·최솟값 위치를 발문에
   노출, 단항식의 x = 0 미분계수. GT = 우회로 판정기(`p3_diff_shortcut_guard`) 규칙이 변조본을
   객관적으로 거부. **판정기 어휘와 다른 말로 쓴 변형**(paraphrase)은 같은 정보를 다른 어휘로
   쓴 것이며, GT는 같은 정보를 판정기 어휘로 쓴 쌍둥이를 판정기가 거부한다는 구성으로 확정한다
   (판정기 과적합 측정).
④ `wording_notation` 문장·표기 결함 — 수 뒤 조사('3를'), 정의 없는 함수 기호, '+ -',
   '<='·'>=', 그리고 스캐너 어휘 밖의 조사 중복('값을을')·맞춤법('구하시요').
   GT = 받침 규칙(`lang.josa`)·구성.
⑤ `explanation_defect` 해설 결함 — 중간 단계 삭제(결론만), 도함수 식의 계수를 틀린 값으로,
   차분몫 계산 결과를 틀린 값으로. GT = 구성(삭제분에 도함수 단계가 있었다)·SymPy.
⑥ `distractor_misattribution` 오답 선지-오개념 연결 오류 — 오개념 연결을 정답 선지로 옮기거나
   (구조상 불가능), 그 오개념 절차에서 나오지 않는 선지로 옮긴다. GT = 정답 선지 일치·SymPy로
   오개념 절차(거듭제곱 단계 누락 2종·곱의 미분 오적용)의 값을 직접 계산해 원 연결이 그 값과
   같고 새 선지는 다름.
⑦ `statement_mismatch` 발문-검산 불일치 — 발문의 미분계수 점이나 함수 계수만 바꾸고 검산·답은
   그대로. GT = 발문대로 고친 검산 조건에서 기존 답이 SymPy fail.

선택 규약
---------
· 결함 문항의 원본과 정상 문항은 **서로 다른 은행 문항**이다(같은 문항의 원본·변이본이 한
  시험지에 함께 나오면 대조로 들킨다). 원본 문항 하나는 시험지에 한 번만 쓴다.
· 결함 쪽은 개념별 개수가 고르게 되도록 개념을 돌아가며 뽑고, 정상 쪽은 결함 쪽의
  (개념 × 문항 형식) 분포를 그대로 따른다 — 개념·객관식 여부로 결함 여부를 짐작할 수 없게.
· 순서는 전부 문자열 시드(`seeded_order`)로 정한다 — 같은 시드·같은 은행이면 바이트가 같다.
· 변조는 은행 레코드의 **깊은 사본**에만 한다 — 은행 파일·입력 레코드는 바뀌지 않는다
  (`review_status`도 쓰지 않는다).

7계층: L3 지역. 같은 패키지(우회로 판정기·풀이 단계·스켈레톤 기반의 시드 셔플)·
`l3.verify_answer`·`l3.safe_parse`(CONST-09 단일 진입점)·`lang.josa`만 import한다.
DB 0·네트워크 0·LLM 0.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final, Literal

import sympy

from whymath_backend.l3.equivalent.p3_diff_shortcut_guard import (
    RULE_IDS,
    probe_from_record,
    shortcut_violations,
    visible_polynomials,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import seeded_order
from whymath_backend.l3.equivalent.p3_diff_solution_steps import solution_steps
from whymath_backend.l3.equivalent.p3_diff_text_scanner import (
    josa_and_notation_defects,
    round2_defects,
    undefined_function_defects,
)
from whymath_backend.l3.safe_parse import safe_sympify
from whymath_backend.l3.verify_answer import verify_answer, verify_real_root_count
from whymath_backend.lang.josa import has_batchim_text, wa_gwa

__all__ = [
    "BANK_DEFECT_CLASSES",
    "CLASS_QUOTAS",
    "MAX_MC_DEFECTS_PER_CONCEPT",
    "QUALIFICATION_SEED",
    "VARIANTS",
    "BankDefectClass",
    "GroundTruthError",
    "SeededBankItem",
    "Variant",
    "build_qualification_set",
]

Record = dict[str, Any]

#: 결함 7종 — 순서는 정답지·보고 표의 순서(①~⑦).
BankDefectClass = Literal[
    "answer_error",
    "ambiguous_solution",
    "derivative_shortcut",
    "wording_notation",
    "explanation_defect",
    "distractor_misattribution",
    "statement_mismatch",
]
BANK_DEFECT_CLASSES: Final[tuple[BankDefectClass, ...]] = (
    "answer_error",
    "ambiguous_solution",
    "derivative_shortcut",
    "wording_notation",
    "explanation_defect",
    "distractor_misattribution",
    "statement_mismatch",
)

#: 종류별 결함 문항 수 — 합 120, 종류마다 ≥ 15(Kiki 결정 2026-10-08 합격 기준의 전제).
CLASS_QUOTAS: Final[Mapping[str, int]] = {
    "answer_error": 18,
    "ambiguous_solution": 17,
    "derivative_shortcut": 17,
    "wording_notation": 17,
    "explanation_defect": 17,
    "distractor_misattribution": 17,
    "statement_mismatch": 17,
}

#: 시험지 기본 시드(결정론) — 날짜형 관례(`defect_seeder` 20260708·은행 검수 표본 20261007).
QUALIFICATION_SEED: Final = 20261008

#: 개념별 객관식 결함 상한 — 개념마다 객관식이 12건이라, 결함 쪽이 6건을 넘게 가져가면 정상 쪽이
#: 같은 수의 객관식을 그 개념에서 낼 수 없다(형식 분포를 맞춰야 블라인드가 성립한다).
MAX_MC_DEFECTS_PER_CONCEPT: Final = 6

_MC: Final = "객관식"
_SLOT_PREFIX: Final = "p3-slot:"


class GroundTruthError(AssertionError):
    """생성 시 단언 실패 — 주입이 적용되지 않았거나 GT가 성립하지 않는다(조용히 넘기지 않는다)."""


# ──────────────────────────────────────────────────────────────────────────
# 레코드 공용 헬퍼
# ──────────────────────────────────────────────────────────────────────────
def _concept(rec: Mapping[str, Any]) -> str:
    codes = rec.get("achievement_standard_codes") or [""]
    return str(codes[0])


def _slot(rec: Mapping[str, Any]) -> str:
    for tag in rec.get("tags") or []:
        if str(tag).startswith(_SLOT_PREFIX):
            return str(tag)[len(_SLOT_PREFIX) :]
    return ""


def _is_mc(rec: Mapping[str, Any]) -> bool:
    return rec.get("question_format") == _MC or bool(rec.get("choices"))


def _verify(rec: Mapping[str, Any]) -> dict[str, Any]:
    raw = rec.get("verify")
    return raw if isinstance(raw, dict) else {}


def _conditions(rec: Mapping[str, Any]) -> str | list[str]:
    raw = _verify(rec).get("conditions")
    if isinstance(raw, list):
        return [str(c) for c in raw]
    return str(raw or "")


def _cond_list(rec: Mapping[str, Any]) -> list[str]:
    cond = _conditions(rec)
    return cond if isinstance(cond, list) else [cond]


def _answer_map(rec: Mapping[str, Any]) -> dict[str, str]:
    raw = _verify(rec).get("answer_map")
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _answer_kind(rec: Mapping[str, Any]) -> str | None:
    kind = _verify(rec).get("answer_kind")
    return str(kind) if isinstance(kind, str) else None


def _answer_key(rec: Mapping[str, Any]) -> str | None:
    """정답(`answer`)과 같은 값을 가진 검산 맵의 키 — 정확히 하나일 때만."""
    answer = str(rec.get("answer") or "")
    keys = [k for k, v in _answer_map(rec).items() if v == answer]
    return keys[0] if len(keys) == 1 else None


_RATIONAL_RE: Final = re.compile(r"-?\d+(?:/\d+)?")


def _rational(text: str) -> Fraction | None:
    return Fraction(text) if _RATIONAL_RE.fullmatch(text.strip()) else None


def _render(value: Fraction) -> str:
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


def _format_class(value: Fraction) -> str:
    """은행 단일 형식 규칙(`p3_diff_skeleton_base.answer_format_for`)의 분류."""
    if value.denominator != 1:
        return "분수"
    return "자연수" if value > 0 else "실수"


def _shifted(value: Fraction) -> Fraction:
    """+1(정답 형식 분류를 바꾸지 않는 쪽) — 0은 +1이면 자연수가 되므로 -1로 간다."""
    return Fraction(-1) if value == 0 else value + 1


def _state(conditions: str | list[str], answer_map: Mapping[str, str]) -> str:
    return verify_answer(conditions, answer_map).state


def _fingerprint(rec: Mapping[str, Any]) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def _clone(rec: Mapping[str, Any]) -> Record:
    return copy.deepcopy(dict(rec))


def _set_question(rec: Record, text: str) -> None:
    rec["question_text"] = text


def _set_explanation(rec: Record, text: str) -> None:
    rec["answer_explanation"] = text


def _guard_rules(rec: Mapping[str, Any]) -> set[str]:
    return {v.rule for v in shortcut_violations(probe_from_record(rec))}


def _split_relation(condition: str) -> tuple[sympy.Expr, sympy.Expr] | None:
    """'lhs = rhs'(공백으로 감싼 등호 하나) → SymPy 양변. 등호가 아니면 None."""
    parts = condition.split(" = ")
    if len(parts) != 2:
        return None
    try:
        lhs = safe_sympify(parts[0])
        rhs = safe_sympify(parts[1])
    except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
        return None
    if not isinstance(lhs, sympy.Expr) or not isinstance(rhs, sympy.Expr):
        return None
    return lhs, rhs


def _real_solutions(expr: sympy.Expr, var: sympy.Symbol) -> list[sympy.Expr]:
    """expr = 0의 서로 다른 실수 해(정렬) — 다항식이 아니면 빈 리스트."""
    try:
        poly = sympy.Poly(sympy.expand(expr), var)
    except sympy.PolynomialError:
        return []
    if poly.degree() < 1 or poly.free_symbols - {var}:
        return []
    return sorted({r for r in sympy.real_roots(poly)}, key=lambda r: float(r))


#: 부호 변화의 방향 — "up"은 음→양(f'이면 f의 극소), "down"은 양→음(극대), None은 둘 다.
SignDirection = Literal["up", "down"] | None


def _sign_change_roots(
    expr: sympy.Expr, var: sympy.Symbol, direction: SignDirection = None
) -> list[sympy.Expr]:
    """expr의 실근 중 좌우에서 부호가 바뀌는 근(증가·감소가 바뀌는 점 — f'의 부호 변화)."""
    roots = _real_solutions(expr, var)
    if not roots:
        return []
    probes = [roots[0] - 1]
    probes += [(a + b) / 2 for a, b in zip(roots, roots[1:], strict=False)]
    probes.append(roots[-1] + 1)
    signs = [sympy.sign(expr.subs(var, p)) for p in probes]
    out = []
    for i, root in enumerate(roots):
        left, right = signs[i], signs[i + 1]
        if left * right >= 0:
            continue
        if direction == "up" and not left < 0:
            continue
        if direction == "down" and not left > 0:
            continue
        out.append(root)
    return out


def _extremum_direction(question: str) -> SignDirection:
    """발문이 묻는 극값의 종류 — 극소(f' 음→양)·극대(f' 양→음)·구별 없음."""
    if re.search(r"극소가 되는|극솟값을 갖는|감소하다가 증가로", question):
        return "up"
    if re.search(r"극대가 되는|극댓값을 갖는|증가하다가 감소로", question):
        return "down"
    return None


# ──────────────────────────────────────────────────────────────────────────
# 변이(Variant) 정의
# ──────────────────────────────────────────────────────────────────────────
#: 변조 함수: 원본 → (변조본, 기록) 또는 None(이 문항에는 적용 불가).
Mutator = Callable[[Mapping[str, Any]], tuple[Record, str] | None]
#: GT 단언: (원본, 변조본) → GT 성립 여부. 변조 함수와 **따로** 다시 계산한다.
GroundTruth = Callable[[Mapping[str, Any], Mapping[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class Variant:
    """결함 종류 안의 주입 방식 1개 — 할당량·GT 근거·기계 게이트와의 규칙 겹침(순환 여부)."""

    defect_class: BankDefectClass
    name: str
    quota: int
    #: GT 근거 — `sympy`(SymPy 계산)·`shortcut_guard`(우회로 판정기 규칙)·`josa_rule`(받침 규칙)·
    #: `construction`(구성 — 무엇을 지웠/넣었는지 우리가 안다).
    gt_basis: str
    #: GT를 확정한 규칙과 **같거나 겹치는 규칙**을 쓰는 기계 게이트 이름(없으면 None). 값이 있으면
    #: 그 변이의 기계 검출은 구성상 보장되거나 그에 가깝고, 규칙 밖 결함을 잡는 능력의 증거가
    #: 아니다(보고서가 따로 뺀다). 예: ② 발문+검산 변이의 GT(SymPy 해 2개 이상)와 수용 게이트의
    #: 유일성 탐침은 같은 계산이고, ⑤ 결론만 남기기의 구성 조건(지운 부분에 도함수 단계)과 판정기
    #: E-derivative(남은 해설에 도함수 식이 없다)는 같은 흔적을 본다.
    gate_overlap: str | None
    #: True=객관식만·False=단답형만·None=둘 다.
    mc: bool | None
    mutate: Mutator
    check_gt: GroundTruth
    #: 변조가 새로 만들어도 되는 기계 판정 소견(우회로 판정기 규칙 id·문면 스캐너 부류). 빈 집합이면
    #: 의도한 결함 외의 소견을 하나도 만들면 안 된다(부수 결함 금지 — 예: 점을 바꾸다 조사를 틀리게
    #: 만들면 기계가 엉뚱한 이유로 '검출'한다). None이면 제한 없음(④ 문장·표기 — 소견 자체가 결함).
    allowed_findings: frozenset[str] | None = frozenset()


# ── 부수 결함 검사 ───────────────────────────────────────────────────────
def _findings(rec: Mapping[str, Any]) -> Counter[str]:
    """기계 판정 소견 — 우회로 판정기 규칙 id + 문면 스캐너 부류(문항 단위 개수)."""
    found: Counter[str] = Counter(_guard_rules(rec))
    question = str(rec.get("question_text") or "")
    explanation = str(rec.get("answer_explanation") or "")
    texts = [question, explanation, *(str(c) for c in rec.get("choices") or [])]
    for text in texts:
        found.update(kind for kind, _ in josa_and_notation_defects(text))
    if undefined_function_defects(question, explanation):
        found["undefined_function"] += 1
    found.update(round2_defects(rec))
    return found


def _side_effects(variant: Variant, orig: Mapping[str, Any], mut: Mapping[str, Any]) -> list[str]:
    """변이가 의도하지 않은 새 소견 — 비어 있어야 그 문항을 쓴다."""
    if variant.allowed_findings is None:
        return []
    new = _findings(mut) - _findings(orig)
    return sorted(kind for kind in new if kind not in variant.allowed_findings)


# ── ① answer_error ───────────────────────────────────────────────────────
def _mut_answer_and_map(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    key = _answer_key(rec)
    old = _rational(str(rec.get("answer") or ""))
    if key is None or old is None or _answer_kind(rec) is not None or _is_mc(rec):
        return None
    new = _shifted(old)
    out = _clone(rec)
    out["answer"] = _render(new)
    out["verify"]["answer_map"][key] = _render(new)
    return out, f"정답·검산 맵 {key}: {_render(old)} → {_render(new)}"


def _gt_answer_and_map(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    return (
        _state(_conditions(orig), _answer_map(orig)) == "pass"
        and _state(_conditions(mut), _answer_map(mut)) == "fail"
        and mut.get("answer") != orig.get("answer")
    )


def _mut_answer_only(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    key = _answer_key(rec)
    old = _rational(str(rec.get("answer") or ""))
    if key is None or old is None or _answer_kind(rec) is not None or _is_mc(rec):
        return None
    new = _shifted(old)
    out = _clone(rec)
    out["answer"] = _render(new)
    return out, f"정답만 {_render(old)} → {_render(new)}(검산 맵 {key}는 원래 값 유지)"


def _gt_answer_only(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    key = _answer_key(orig)
    if key is None:
        return False
    claimed = {**_answer_map(orig), key: str(mut.get("answer") or "")}
    return (
        _state(_conditions(orig), _answer_map(orig)) == "pass"
        and _state(_conditions(orig), claimed) == "fail"
        and _answer_map(mut) == _answer_map(orig)
    )


def _mut_mc_choice_swap(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    key = _answer_key(rec)
    if key is None or _answer_kind(rec) is not None or not _is_mc(rec):
        return None
    answer = str(rec.get("answer") or "")
    for choice in rec.get("choices") or []:
        text = str(choice)
        if text == answer or _rational(text) is None:
            continue
        trial = {**_answer_map(rec), key: text}
        if _state(_conditions(rec), trial) != "fail":
            continue
        out = _clone(rec)
        out["answer"] = text
        out["verify"]["answer_map"][key] = text
        return out, f"정답 선지 {answer} → 오답 선지 {text}(검산 맵 {key}도 교체)"
    return None


def _gt_mc_choice_swap(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    return (
        _state(_conditions(orig), _answer_map(orig)) == "pass"
        and _state(_conditions(mut), _answer_map(mut)) == "fail"
        and str(mut.get("answer")) in [str(c) for c in mut.get("choices") or []]
        and mut.get("answer") != orig.get("answer")
    )


def _mut_count_off_by_one(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    if _answer_kind(rec) != "real_root_count":
        return None
    old = _rational(str(rec.get("answer") or ""))
    if old is None:
        return None
    if _is_mc(rec):
        options = [str(c) for c in rec.get("choices") or [] if str(c) != rec.get("answer")]
        new_text = next((c for c in options if c.isdigit() and int(c) > 0), None)
        if new_text is None:
            return None
    else:
        new_text = _render(old + 1)
    out = _clone(rec)
    out["answer"] = new_text
    return out, f"실근 개수 {_render(old)} → {new_text}"


def _gt_count_off_by_one(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    cond = _conditions(orig)
    return (
        verify_real_root_count(cond, str(orig.get("answer"))).state == "pass"
        and verify_real_root_count(cond, str(mut.get("answer"))).state == "fail"
    )


# ── ② ambiguous_solution ─────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class _UniquenessPhrase:
    """발문의 유일성 조건 1종 — 지울 문구·바꿀 말·검산 재료에서 그 조건을 이루는 부분."""

    name: str
    pattern: re.Pattern[str]
    replacement: str
    #: 검산 조건 목록에서 이 유일성 조건에 해당하는 항을 고르는 술어(발문+검산 변이가 지운다).
    is_constraint: Callable[[str], bool]
    #: answer_selection을 지우는가(극대·극소·큰 값/작은 값 선택).
    drops_selection: bool = False
    #: 해 개수를 셀 때 부호가 바뀌는 근만 세는가(증가·감소가 바뀌는 점).
    sign_change_only: bool = False


def _is_inequality(cond: str) -> bool:
    return bool(re.search(r"\s(<|>|<=|>=|!=)\s", cond))


_UNIQUENESS: Final[tuple[_UniquenessPhrase, ...]] = (
    _UniquenessPhrase(
        "positive_unknown",
        re.compile(r"양수 ([a-z])의 값"),
        r"실수 \1의 값",
        is_constraint=lambda c: bool(re.fullmatch(r"[a-z] > 0", c.strip())),
    ),
    _UniquenessPhrase(
        "positive_tangent_point",
        re.compile(r"위의 x좌표가 양수인 점에서"),
        "위의 한 점에서",
        is_constraint=_is_inequality,
    ),
    _UniquenessPhrase(
        "larger_or_smaller",
        re.compile(r"의 x좌표 중 (?:큰|작은) 값을"),
        "의 x좌표를",
        is_constraint=lambda c: False,
        drops_selection=True,
        sign_change_only=True,
    ),
    _UniquenessPhrase(
        "root_outside_interval",
        re.compile(r"의 두 실근 중 열린구간 \([^)]*\)에 속하지 않는 근을"),
        "의 실근을",
        is_constraint=_is_inequality,
    ),
)


def _uniqueness_of(rec: Mapping[str, Any]) -> _UniquenessPhrase | None:
    question = str(rec.get("question_text") or "")
    hits = [u for u in _UNIQUENESS if u.pattern.search(question)]
    if len(hits) != 1:
        return None
    phrase = hits[0]
    if phrase.drops_selection and not _verify(rec).get("answer_selection"):
        return None
    if not phrase.drops_selection and not any(phrase.is_constraint(c) for c in _cond_list(rec)):
        return None
    return phrase


def _answer_variable(rec: Mapping[str, Any]) -> str | None:
    """검산 주식에서 풀어야 할 미지수 — 정답 키(없으면 단일 키)."""
    key = _answer_key(rec)
    if key is not None:
        return key
    amap = _answer_map(rec)
    return next(iter(amap)) if len(amap) == 1 else None


def _main_solutions(rec: Mapping[str, Any], *, sign_change_only: bool) -> list[sympy.Expr]:
    """검산 주식(첫 조건)을 정답 미지수에 대해 푼 서로 다른 실수 해."""
    var_name = _answer_variable(rec)
    relation = _split_relation(_cond_list(rec)[0])
    if var_name is None or relation is None:
        return []
    var = sympy.Symbol(var_name)
    others = {
        sympy.Symbol(k): safe_sympify(v) for k, v in _answer_map(rec).items() if k != var_name
    }
    expr = sympy.expand((relation[0] - relation[1]).subs(others))
    if expr.free_symbols != {var}:
        return []
    if not sign_change_only:
        return _real_solutions(expr, var)
    direction = _extremum_direction(str(rec.get("question_text") or ""))
    return _sign_change_roots(expr, var, direction)


def _mut_ambiguous(rec: Mapping[str, Any], *, relax_verify: bool) -> tuple[Record, str] | None:
    phrase = _uniqueness_of(rec)
    if phrase is None:
        return None
    question = str(rec.get("question_text") or "")
    out = _clone(rec)
    _set_question(out, phrase.pattern.sub(phrase.replacement, question, count=1))
    note = f"발문 유일성 조건 제거({phrase.name})"
    if relax_verify:
        if phrase.drops_selection:
            out["verify"].pop("answer_selection", None)
        else:
            kept = [c for c in _cond_list(rec) if not phrase.is_constraint(c)]
            out["verify"]["conditions"] = kept[0] if len(kept) == 1 else kept
        note += " + 검산 재료에서도 제거"
    else:
        note += " — 검산 재료는 유지(발문과 어긋남)"
    return out, note


def _gt_ambiguous(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    phrase = _uniqueness_of(orig)
    if phrase is None:
        return False
    if phrase.pattern.search(str(mut.get("question_text") or "")):
        return False  # 유일성 조건이 발문에 남아 있다
    solutions = _main_solutions(orig, sign_change_only=phrase.sign_change_only)
    answer = _answer_map(orig).get(_answer_variable(orig) or "")
    in_set = answer is not None and any(
        sympy.simplify(s - safe_sympify(answer)) == 0 for s in solutions
    )
    return len(solutions) >= 2 and in_set


# ── ③ derivative_shortcut ────────────────────────────────────────────────
_MVT_COND: Final = re.compile(
    r"^Derivative\((?P<p>[^,]+), x\)\.doit\(\)\.subs\(x, c\) = "
    r"\(\((?P<fb>-?\d+)\) - \((?P<fa>-?\d+)\)\)/\(\((?P<b>-?\d+)\) - \((?P<a>-?\d+)\)\)$"
)


def _mvt_rate(rec: Mapping[str, Any]) -> tuple[int, int, Fraction] | None:
    """평균값 정리 문항의 (a, b, 평균변화율) — 검산 함수로 SymPy가 다시 계산한 값과 같을 때만."""
    if _concept(rec) != "[12미적Ⅰ-02-06]":
        return None
    match = _MVT_COND.match(_cond_list(rec)[0])
    if match is None or "f(x) = " not in str(rec.get("question_text") or ""):
        return None
    a, b = int(match["a"]), int(match["b"])
    rate = Fraction(int(match["fb"]) - int(match["fa"]), b - a)
    x = sympy.Symbol("x")
    poly = safe_sympify(match["p"])
    true_rate = (poly.subs(x, b) - poly.subs(x, a)) / (b - a)
    if sympy.Rational(rate.numerator, rate.denominator) != sympy.nsimplify(true_rate):
        return None
    return a, b, rate


def _mvt_hint(a: int, b: int, rate: Fraction, *, paraphrase: bool) -> str:
    if paraphrase:
        return (
            f" (단, 곡선 y = f(x) 위의 x좌표가 {a}, {b}인 두 점을 잇는 직선의 기울기는 "
            f"{_render(rate)}이다.)"
        )
    return f" (단, 닫힌구간 [{a}, {b}]에서 f(x)의 평균변화율은 {_render(rate)}이다.)"


def _hint_ready(rec: Mapping[str, Any]) -> bool:
    """단서 덧붙이기가 가능한 원본 — 판정기 위반 0이고 발문에 '(단, …)'이 아직 없다.

    단서는 은행 발문의 관례 꼴 '(단, …)'로 붙인다('(참고: …)' 같은 은행에 없는 꼴은 그 자체가
    결함 표지가 되어 판정자가 내용을 보지 않고도 맞힌다). 이미 '(단, …)'이 있는 발문에 하나 더
    붙이면 다시 눈에 띄는 꼴이 되므로 고르지 않는다.
    """
    return "(단" not in str(rec.get("question_text") or "") and not _guard_rules(rec)


def _mut_avg_rate(rec: Mapping[str, Any], *, paraphrase: bool) -> tuple[Record, str] | None:
    found = _mvt_rate(rec)
    if found is None or not _hint_ready(rec):
        return None
    a, b, rate = found
    out = _clone(rec)
    _set_question(out, str(rec["question_text"]) + _mvt_hint(a, b, rate, paraphrase=paraphrase))
    kind = "판정기 밖 어휘(두 점을 잇는 직선의 기울기)" if paraphrase else "판정기 어휘(평균변화율)"
    return out, f"발문에 구간 [{a}, {b}]의 평균변화율 {_render(rate)} 노출 — {kind}"


def _gt_avg_rate(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    found = _mvt_rate(orig)
    if found is None or _guard_rules(orig):
        return False
    a, b, rate = found
    twin = _clone(orig)
    _set_question(twin, str(orig["question_text"]) + _mvt_hint(a, b, rate, paraphrase=False))
    return "T06-given-rate" in _guard_rules(twin) and str(mut["question_text"]).startswith(
        str(orig["question_text"])
    )


_SIGN_CHANGE_STEM: Final = re.compile(
    r"증가·감소가 바뀌는 점의 x좌표|극(?:대|소)가 되는 x좌표|극값을 갖는 x좌표"
    r"|(?:증가하다가 감소|감소하다가 증가)로 바뀌는 점의 x좌표"
)


def _critical_points(rec: Mapping[str, Any]) -> list[sympy.Expr] | None:
    """02-08 '증가·감소가 바뀌는 점' 문항의 부호가 바뀌는 임계점(유리수 2개 이상)."""
    question = str(rec.get("question_text") or "")
    if _concept(rec) != "[12미적Ⅰ-02-08]" or not _SIGN_CHANGE_STEM.search(question):
        return None
    x = sympy.Symbol("x")
    polys = [
        p
        for p in visible_polynomials(question)
        if p.free_symbols == {x} and sympy.degree(p, x) >= 3
    ]
    if len(polys) != 1:
        return None
    roots = _sign_change_roots(sympy.diff(polys[0], x), x)
    if len(roots) < 2 or not all(r.is_rational for r in roots):
        return None
    return roots


def _critical_hint(roots: Sequence[sympy.Expr], *, paraphrase: bool) -> str:
    texts = [str(r) for r in roots]
    if paraphrase:
        return f" (단, 극값을 갖는 점의 x좌표는 {', '.join(texts)}뿐이다.)"
    if len(texts) == 2:
        pins = f"x = {texts[0]}{wa_gwa(texts[0])} x = {texts[1]}"
    else:
        pins = ", ".join(f"x = {t}" for t in texts)
    # 주어 없이 쓴다 — 발문이 '곡선 y = …'로 f를 정의하지 않는 문항에 'f(x)는'을 붙이면 정의 없는
    # 함수 기호라는 부수 결함이 생긴다(문면 스캐너는 'f(x)' 등장 자체를 정의로 읽어 못 잡는다).
    return f" (단, {pins}에서 극값을 갖는다.)"


def _mut_critical(rec: Mapping[str, Any], *, paraphrase: bool) -> tuple[Record, str] | None:
    roots = _critical_points(rec)
    if roots is None or not _hint_ready(rec):
        return None
    out = _clone(rec)
    _set_question(out, str(rec["question_text"]) + _critical_hint(roots, paraphrase=paraphrase))
    kind = "판정기 밖 어휘(x좌표는 …뿐)" if paraphrase else "판정기 어휘(x = …에서 극값)"
    return out, f"발문에 극값 위치 {[str(r) for r in roots]} 노출 — {kind}"


def _gt_critical(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    roots = _critical_points(orig)
    if roots is None or _guard_rules(orig):
        return False
    twin = _clone(orig)
    _set_question(twin, str(orig["question_text"]) + _critical_hint(roots, paraphrase=False))
    return "T08-given-critical-points" in _guard_rules(twin) and str(
        mut["question_text"]
    ).startswith(str(orig["question_text"]))


def _minimizer(rec: Mapping[str, Any]) -> tuple[str, str] | None:
    """02-09 극값형 문항(검산 맵에 위치 변수 + 미분 조건)의 (변수, 극값 위치)."""
    if _concept(rec) != "[12미적Ⅰ-02-09]":
        return None
    amap = _answer_map(rec)
    if not any("Derivative" in c for c in _cond_list(rec)):
        return None
    var = "t" if "t" in amap else "x" if "x" in amap else None
    if var is None or _rational(amap[var]) is None or amap[var] == "0":
        return None
    if _state(_conditions(rec), amap) != "pass":
        return None
    return var, amap[var]


def _minimizer_hint(var: str, value: str, *, paraphrase: bool) -> str:
    if paraphrase:
        return f" (단, 구하는 값은 {var}좌표가 {value}인 점에서의 값이다.)"
    return f" (단, 구하는 값은 {var} = {value}일 때의 값이다.)"


def _mut_minimizer(rec: Mapping[str, Any], *, paraphrase: bool) -> tuple[Record, str] | None:
    found = _minimizer(rec)
    if found is None or not _hint_ready(rec):
        return None
    var, value = found
    out = _clone(rec)
    hint = _minimizer_hint(var, value, paraphrase=paraphrase)
    _set_question(out, str(rec["question_text"]) + hint)
    kind = f"판정기 밖 어휘({var}좌표가 …인 점)" if paraphrase else f"판정기 어휘({var} = …)"
    return out, f"발문에 극값 위치 {var} = {value} 노출 — {kind}"


def _gt_minimizer(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    found = _minimizer(orig)
    if found is None or _guard_rules(orig):
        return False
    twin = _clone(orig)
    _set_question(twin, str(orig["question_text"]) + _minimizer_hint(*found, paraphrase=False))
    return "T09-pinned-minimizer" in _guard_rules(twin) and str(mut["question_text"]).startswith(
        str(orig["question_text"])
    )


_MONOMIAL_STEM: Final = re.compile(
    r"^함수 f\(x\) = (?P<poly>x\^\d+)에 대하여 f'\((?P<a>-?\d+)\)의 값을 구하시오\.$"
)
_MONOMIAL_COND: Final = re.compile(
    r"^Derivative\((?P<p>x\*\*\d+), x\)\.doit\(\)\.subs\(x, (?P<a>-?\d+)\) = (?P<y>[a-z])$"
)


def _zero_monomial_parts(rec: Mapping[str, Any]) -> tuple[re.Match[str], re.Match[str]] | None:
    stem = _MONOMIAL_STEM.match(str(rec.get("question_text") or ""))
    cond = _MONOMIAL_COND.match(_cond_list(rec)[0]) if len(_cond_list(rec)) == 1 else None
    if stem is None or cond is None or stem["a"] == "0" or stem["a"] != cond["a"]:
        return None
    explanation = str(rec.get("answer_explanation") or "")
    if f"x가 {stem['a']}일 때의 값은 {rec.get('answer')}이다" not in explanation:
        return None
    return stem, cond


def _zero_monomial_record(rec: Mapping[str, Any], *, paraphrase: bool) -> tuple[Record, str] | None:
    parts = _zero_monomial_parts(rec)
    if parts is None:
        return None
    stem, cond = parts
    a, var_y = stem["a"], cond["y"]
    new_cond = f"Derivative({cond['p']}, x).doit().subs(x, 0) = {var_y}"
    new_map = {var_y: "0"}
    try:
        steps = solution_steps(conditions=new_cond, answer_map=new_map).steps
    except ValueError:
        return None
    asked = "x의 값이 0일 때의 순간변화율을" if paraphrase else "f'(0)의 값을"
    out = _clone(rec)
    _set_question(out, f"함수 f(x) = {stem['poly']}에 대하여 {asked} 구하시오.")
    _set_explanation(
        out,
        str(rec["answer_explanation"]).replace(
            f"x가 {a}일 때의 값은 {rec.get('answer')}이다", "x가 0일 때의 값은 0이다"
        ),
    )
    out["answer"] = "0"
    out["answer_format"] = "실수"
    out["verify"]["conditions"] = new_cond
    out["verify"]["answer_map"] = new_map
    out["verify"]["solution_steps"] = list(steps)
    kind = "판정기 밖 어휘(x의 값이 0일 때의 순간변화율)" if paraphrase else "판정기 어휘(f'(0))"
    return out, f"단항식 {stem['poly']}의 미분계수를 x = {a} → 0으로(답 0 — 변별 없음) — {kind}"


def _mut_zero_monomial(rec: Mapping[str, Any], *, paraphrase: bool) -> tuple[Record, str] | None:
    if _guard_rules(rec):
        return None
    return _zero_monomial_record(rec, paraphrase=paraphrase)


def _gt_zero_monomial(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    """단항식(차수 ≥ 2)의 x = 0 미분계수 — 판정기 어휘 쌍둥이가 거부되고, 문항은 여전히 참."""
    parts = _zero_monomial_parts(orig)
    built = _zero_monomial_record(orig, paraphrase=False)
    if parts is None or built is None or _guard_rules(orig):
        return False
    x = sympy.Symbol("x")
    poly = safe_sympify(parts[0]["poly"].replace("^", "**"))
    monomial = len(sympy.Poly(poly, x).terms()) == 1 and sympy.degree(poly, x) >= 2
    return (
        monomial
        and "T-zero-monomial" in _guard_rules(built[0])
        and _state(_conditions(mut), _answer_map(mut)) == "pass"
        and mut.get("answer") == "0"
    )


# ── ④ wording_notation ───────────────────────────────────────────────────
_JOSA_PAIRS: Final[Mapping[str, tuple[str, str]]] = {
    # 조사 → (받침 有 형태, 받침 無 형태)
    "을": ("을", "를"),
    "를": ("을", "를"),
    "은": ("은", "는"),
    "는": ("은", "는"),
    "과": ("과", "와"),
    "와": ("과", "와"),
}
_NUMBER_JOSA: Final = re.compile(
    r"(?<![A-Za-z0-9_.^/'])(?P<num>-?\d+(?:/\d+)?)(?P<josa>[을를은는과와])(?=[\s,.?)])"
)


def _number_josa_site(text: str) -> tuple[re.Match[str], str] | None:
    """수 뒤 조사가 *지금 맞는* 첫 자리와 틀린 짝 — 받침 판별 불가면 건너뛴다."""
    for match in _NUMBER_JOSA.finditer(text):
        batchim = has_batchim_text(match["num"])
        if batchim is None:
            continue
        with_b, without_b = _JOSA_PAIRS[match["josa"]]
        correct = with_b if batchim else without_b
        if match["josa"] == correct:
            return match, without_b if batchim else with_b
    return None


def _mut_number_josa(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    for field in ("question_text", "answer_explanation"):
        text = str(rec.get(field) or "")
        site = _number_josa_site(text)
        if site is None:
            continue
        match, wrong = site
        out = _clone(rec)
        out[field] = text[: match.start("josa")] + wrong + text[match.end("josa") :]
        return out, f"{field} 수 뒤 조사 '{match['num']}{match['josa']}' → '{match['num']}{wrong}'"
    return None


def _gt_number_josa(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    """바뀐 자리가 정확히 조사 한 글자이고, 그 조사가 받침 규칙상 틀린 짝인가(규칙을 다시 계산)."""
    for field in ("question_text", "answer_explanation"):
        before, after = str(orig.get(field) or ""), str(mut.get(field) or "")
        if before == after:
            continue
        site = _number_josa_site(before)
        if site is None or len(before) != len(after):
            return False
        match, _ = site
        index = match.start("josa")
        if after[:index] != before[:index] or after[index + 1 :] != before[index + 1 :]:
            return False
        batchim = has_batchim_text(match["num"])
        with_b, without_b = _JOSA_PAIRS[match["josa"]]
        correct = with_b if batchim else without_b
        return (
            batchim is not None and after[index] in (with_b, without_b) and after[index] != correct
        )
    return False


_F_DEFINED: Final = re.compile(
    r"(?<![A-Za-z0-9_'])f\((?:x|t)\)|(?<![가-힣])함수 f(?![A-Za-z0-9_'(])"
)
_F_USED: Final = re.compile(r"(?<![A-Za-z0-9_'])f\s*[(']")


def _mut_undefined_symbol(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    question = str(rec.get("question_text") or "")
    if not question.startswith("함수 f(x) = ") or question.count("f(x)") != 1:
        return None
    mutated = "곡선 y = " + question[len("함수 f(x) = ") :]
    if not _F_USED.search(mutated) or _F_DEFINED.search(mutated):
        return None
    out = _clone(rec)
    _set_question(out, mutated)
    return out, "발문의 함수 정의 'f(x) = …'를 '곡선 y = …'로 바꿔 f를 정의 없이 씀"


def _gt_undefined_symbol(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    before, after = str(orig.get("question_text") or ""), str(mut.get("question_text") or "")
    return (
        bool(_F_DEFINED.search(before))
        and bool(_F_USED.search(after))
        and not _F_DEFINED.search(after)
    )


_MINUS_SITE: Final = re.compile(r"(?<=[0-9a-z^)]) - (?=[0-9a-z(])")


def _mut_plus_minus(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    question = str(rec.get("question_text") or "")
    match = _MINUS_SITE.search(question)
    if match is None or "+ -" in question:
        return None
    out = _clone(rec)
    _set_question(out, question[: match.start()] + " + -" + question[match.end() :])
    return out, "발문 수식의 ' - '를 부호 깨진 ' + -'로"


def _gt_plus_minus(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    before, after = str(orig.get("question_text") or ""), str(mut.get("question_text") or "")
    return (
        "+ -" not in before and after.count("+ -") == 1 and after.replace(" + -", " - ") == before
    )


_UNICODE_INEQ: Final[Mapping[str, str]] = {"≤": "<=", "≥": ">="}


def _mut_ascii_inequality(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    for field in ("question_text", "answer_explanation"):
        text = str(rec.get(field) or "")
        if any(sym in text for sym in _UNICODE_INEQ):
            mutated = text
            for sym, code in _UNICODE_INEQ.items():
                mutated = mutated.replace(sym, code)
            out = _clone(rec)
            out[field] = mutated
            return out, f"{field}의 '≤'·'≥'를 코드 표기 '<='·'>='로"
    return None


def _gt_ascii_inequality(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    for field in ("question_text", "answer_explanation"):
        before, after = str(orig.get(field) or ""), str(mut.get(field) or "")
        if before != after:
            restored = after.replace("<=", "≤").replace(">=", "≥")
            return restored == before and bool(re.search(r"<=|>=", after))
    return False


_HANGUL_OBJECT: Final = re.compile(r"(?<=[가-힣])(?P<josa>을|를) ")


def _mut_doubled_josa(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    question = str(rec.get("question_text") or "")
    match = _HANGUL_OBJECT.search(question)
    if match is None:
        return None
    out = _clone(rec)
    josa = match["josa"]
    _set_question(out, question[: match.end("josa")] + josa + question[match.end("josa") :])
    return out, f"발문 목적격 조사 중복 '{josa}' → '{josa}{josa}'(스캐너 어휘 밖)"


def _gt_doubled_josa(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    before, after = str(orig.get("question_text") or ""), str(mut.get("question_text") or "")
    doubled = re.search(r"을을 |를를 ", after)
    return doubled is not None and "을을 " not in before and "를를 " not in before


def _mut_misspelling(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    question = str(rec.get("question_text") or "")
    if question.count("구하시오") != 1:
        return None
    out = _clone(rec)
    _set_question(out, question.replace("구하시오", "구하시요"))
    return out, "발문 맞춤법 '구하시오' → '구하시요'(스캐너 어휘 밖)"


def _gt_misspelling(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    before, after = str(orig.get("question_text") or ""), str(mut.get("question_text") or "")
    return (
        "구하시오" in before
        and "구하시요" in after
        and after.replace("구하시요", "구하시오") == before
    )


# ── ⑤ explanation_defect ─────────────────────────────────────────────────
#: 도함수 단계의 흔적 — 해설에서 지운 부분에 이것이 있어야 '중간 단계를 지웠다'가 성립한다.
_DERIVATIVE_STEP: Final = re.compile(r"도함수|[a-z]'\(|[a-z]'\s*=|v\(t\)|a\(t\)")


def _conclusion_only(explanation: str) -> tuple[str, str] | None:
    """(남길 결론, 지울 앞부분) — 문장이 둘 이상이면 마지막 문장, 하나면 마지막 '이므로 ' 뒤."""
    text = explanation.strip()
    sentences = re.split(r"(?<=다\.)\s+", text)
    if len(sentences) >= 2:
        kept, removed = sentences[-1], " ".join(sentences[:-1])
    else:
        index = text.rfind("이므로 ")
        if index < 0:
            return None
        kept, removed = text[index + len("이므로 ") :], text[:index]
    if not kept.endswith("다.") or not _DERIVATIVE_STEP.search(removed):
        return None
    return kept, removed


def _mut_steps_removed(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    found = _conclusion_only(str(rec.get("answer_explanation") or ""))
    if found is None:
        return None
    kept, removed = found
    out = _clone(rec)
    _set_explanation(out, kept)
    return out, f"해설의 중간 단계 삭제(결론만 남김) — 지운 부분 {len(removed)}자"


def _gt_steps_removed(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    before = str(orig.get("answer_explanation") or "").strip()
    after = str(mut.get("answer_explanation") or "")
    if not after or not before.endswith(after) or len(after) >= len(before):
        return False
    return bool(_DERIVATIVE_STEP.search(before[: len(before) - len(after)]))


_DERIVATIVE_RHS: Final = re.compile(
    r"(?:도함수는|[fgy]'\(x\) =|y' =|v\(t\) =) (?P<rhs>[^가-힣=]+?)(?=이므로|이다|이고|,| =)"
)


def _question_function(rec: Mapping[str, Any]) -> tuple[sympy.Expr, sympy.Symbol] | None:
    """발문의 다항함수 하나(매개변수 없음)와 그 변수 — 둘 이상이거나 없으면 None."""
    question = str(rec.get("question_text") or "")
    for name in ("x", "t"):
        var = sympy.Symbol(name)
        polys = [p for p in visible_polynomials(question) if p.free_symbols == {var}]
        polys = [p for p in polys if sympy.degree(p, var) >= 2]
        if len(polys) == 1:
            return polys[0], var
    return None


def _stated_derivative(rec: Mapping[str, Any]) -> tuple[re.Match[str], sympy.Expr] | None:
    """해설이 적은 도함수 식(발문 함수의 참 도함수와 SymPy로 같은 것)의 첫 자리."""
    found = _question_function(rec)
    if found is None:
        return None
    poly, var = found
    truth = sympy.expand(sympy.diff(poly, var))
    for match in _DERIVATIVE_RHS.finditer(str(rec.get("answer_explanation") or "")):
        parsed = visible_polynomials(match["rhs"].strip())
        if len(parsed) == 1 and sympy.expand(parsed[0] - truth) == 0:
            return match, truth
    return None


def _mut_derivative_misstated(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    found = _stated_derivative(rec)
    if found is None:
        return None
    match, _ = found
    rhs = match["rhs"]
    wrong = re.sub(r"\d+", lambda m: str(int(m.group()) + 1), rhs, count=1)
    if wrong == rhs:
        return None
    explanation = str(rec["answer_explanation"])
    start, end = match.span("rhs")
    out = _clone(rec)
    _set_explanation(out, explanation[:start] + wrong + explanation[end:])
    return out, f"해설의 도함수 식 '{rhs.strip()}' → '{wrong.strip()}'(결론은 그대로)"


def _gt_derivative_misstated(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    found = _stated_derivative(orig)
    if found is None:
        return False
    match, truth = found
    after = str(mut.get("answer_explanation") or "")
    before = str(orig.get("answer_explanation") or "")
    start = match.start("rhs")
    tail = len(before) - match.end("rhs")
    stated = after[start : len(after) - tail]
    parsed = visible_polynomials(stated.strip())
    return len(parsed) == 1 and sympy.expand(parsed[0] - truth) != 0


_QUOTIENT_RESULT: Final = re.compile(
    r"= (?P<expr>\((?:[^()]|\([^()]*\))*\)/\d+) = (?P<value>-?\d+(?:/\d+)?)(?=이)"
)


def _quotient_site(rec: Mapping[str, Any]) -> re.Match[str] | None:
    for match in _QUOTIENT_RESULT.finditer(str(rec.get("answer_explanation") or "")):
        try:
            value = safe_sympify(match["expr"])
        except (ValueError, TypeError, SyntaxError, sympy.SympifyError):
            continue
        if sympy.nsimplify(value) == sympy.Rational(match["value"]):
            return match
    return None


def _mut_arithmetic_slip(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    match = _quotient_site(rec)
    if match is None:
        return None
    old = Fraction(match["value"])
    new = _render(old + 1)
    explanation = str(rec["answer_explanation"])
    start, end = match.span("value")
    out = _clone(rec)
    _set_explanation(out, explanation[:start] + new + explanation[end:])
    return out, f"해설의 차분몫 계산 {match['expr']} = {match['value']} → {new}"


def _gt_arithmetic_slip(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    match = _quotient_site(orig)
    if match is None:
        return False
    after = str(mut.get("answer_explanation") or "")
    tail = after[match.start("value") :]
    stated = re.match(r"-?\d+(?:/\d+)?", tail)
    if stated is None:
        return False
    return bool(sympy.nsimplify(safe_sympify(match["expr"])) != sympy.Rational(stated.group()))


# ── ⑥ distractor_misattribution ──────────────────────────────────────────
def _distractor_entries(rec: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = rec.get("distractor_map")
    return [dict(e) for e in raw] if isinstance(raw, list) else []


def _answer_index(rec: Mapping[str, Any]) -> int | None:
    choices = [str(c) for c in rec.get("choices") or []]
    answer = str(rec.get("answer") or "")
    return choices.index(answer) if choices.count(answer) == 1 else None


def _mut_to_answer(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    entries = _distractor_entries(rec)
    index = _answer_index(rec)
    if not entries or index is None:
        return None
    out = _clone(rec)
    old = out["distractor_map"][0]["choice_index"]
    out["distractor_map"][0]["choice_index"] = index
    kebab = out["distractor_map"][0]["misconception_id"]
    return out, f"오개념 {kebab}의 연결 선지 {old} → 정답 선지 {index}"


def _gt_to_answer(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    index = _answer_index(mut)
    moved = [e["choice_index"] for e in _distractor_entries(mut)]
    return (
        index is not None
        and index in moved
        and index not in [e["choice_index"] for e in _distractor_entries(orig)]
    )


_EVAL_COND: Final = re.compile(
    r"^Derivative\((?P<p>[^,]+), (?P<v>[xt])\)\.doit\(\)\.subs\((?P=v), (?P<a>-?\d+)\) = [a-z]$"
)


def _misconception_values(rec: Mapping[str, Any], kebab: str) -> set[sympy.Expr] | None:
    """오개념 절차를 SymPy로 직접 계산한 값 — 지원하는 오개념만(그 밖은 None).

    · power-rule-step-omitted: 각 항 c·v^n에서 지수를 앞으로 내리지 않음(c·v^(n-1)) 또는 지수를
      줄이지 않음(c·n·v^n) — 카탈로그 canonical_statement '(x³)′ = x² 또는 3x³'.
    · product-rule-naive: 두 인수의 도함수끼리만 곱함(f′·g′).
    """
    conds = _cond_list(rec)
    match = _EVAL_COND.match(conds[0]) if len(conds) == 1 else None
    if match is None:
        return None
    var = sympy.Symbol(match["v"])
    point = sympy.Integer(int(match["a"]))
    expr = safe_sympify(match["p"])
    if kebab == "power-rule-step-omitted":
        poly = sympy.Poly(sympy.expand(expr), var)
        no_bring = sum((c * var ** (n - 1) for (n,), c in poly.terms() if n >= 1), sympy.Integer(0))
        no_reduce = sum((c * n * var**n for (n,), c in poly.terms()), sympy.Integer(0))
        return {sympy.expand(no_bring).subs(var, point), sympy.expand(no_reduce).subs(var, point)}
    if kebab == "product-rule-naive":
        if not isinstance(expr, sympy.Mul) or len(expr.args) != 2:
            return None
        left, right = expr.args
        return {(sympy.diff(left, var) * sympy.diff(right, var)).subs(var, point)}
    return None


def _unrelated_choice(rec: Mapping[str, Any]) -> tuple[int, set[sympy.Expr]] | None:
    """첫 오개념 연결을 옮길 선지 — 정답도 원 연결도 아니고, 오개념 절차 값에도 없는 선지."""
    entries = _distractor_entries(rec)
    answer_index = _answer_index(rec)
    if not entries or answer_index is None:
        return None
    values = _misconception_values(rec, str(entries[0]["misconception_id"]))
    if values is None:
        return None
    choices = [str(c) for c in rec.get("choices") or []]
    mapped = {int(e["choice_index"]) for e in entries}
    same_kebab = [e for e in entries if e["misconception_id"] == entries[0]["misconception_id"]]
    # 원 연결이 우리의 오개념 절차 모형과 맞아야(모형 검증) GT를 이 모형으로 세울 수 있다.
    for entry in same_kebab:
        value = _rational(choices[int(entry["choice_index"])])
        if value is None or sympy.Rational(value.numerator, value.denominator) not in values:
            return None
    for index, text in enumerate(choices):
        value = _rational(text)
        if index == answer_index or index in mapped or value is None:
            continue
        if sympy.Rational(value.numerator, value.denominator) not in values:
            return index, values
    return None


def _mut_to_unrelated(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    found = _unrelated_choice(rec)
    if found is None:
        return None
    index, values = found
    out = _clone(rec)
    old = out["distractor_map"][0]["choice_index"]
    out["distractor_map"][0]["choice_index"] = index
    kebab = out["distractor_map"][0]["misconception_id"]
    shown = sorted(str(v) for v in values)
    return out, f"오개념 {kebab}의 연결 선지 {old} → {index}(그 오개념 절차 값 {shown}에 없음)"


def _gt_to_unrelated(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    found = _unrelated_choice(orig)
    if found is None:
        return False
    _, values = found
    entries = _distractor_entries(mut)
    choices = [str(c) for c in mut.get("choices") or []]
    first = _rational(choices[int(entries[0]["choice_index"])]) if entries else None
    return (
        first is not None
        and sympy.Rational(first.numerator, first.denominator) not in values
        and int(entries[0]["choice_index"]) != _answer_index(mut)
    )


# ── ⑦ statement_mismatch ─────────────────────────────────────────────────
_POINT_IN_QUESTION: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"[a-z]'\((?P<a>-?\d+)\)"),
    re.compile(r"(?<![A-Za-z])t = (?P<a>-?\d+)(?![\d/])"),
    re.compile(r"(?<![A-Za-z])x = (?P<a>-?\d+)에서의 미분계수"),
)
_EVAL_COND_ANY_ORDER: Final = re.compile(
    r"^Derivative\((?P<p>[^,]+), (?P<v>[xt])(?:, (?P=v))?\)\.doit\(\)\.subs\((?P=v), "
    r"(?P<a>-?\d+)\) = (?P<y>[a-z])$"
)


def _point_site(rec: Mapping[str, Any]) -> tuple[re.Match[str], re.Match[str]] | None:
    question = str(rec.get("question_text") or "")
    conds = _cond_list(rec)
    cond = _EVAL_COND_ANY_ORDER.match(conds[0]) if len(conds) == 1 else None
    if cond is None or "출발" in question:
        return None
    hits = [m for pattern in _POINT_IN_QUESTION for m in pattern.finditer(question)]
    if len(hits) != 1 or hits[0]["a"] != cond["a"]:
        return None
    return hits[0], cond


def _moved_condition(cond: re.Match[str], point: int) -> str:
    text = cond.string
    return text[: cond.start("a")] + str(point) + text[cond.end("a") :]


def _mut_point_changed(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    site = _point_site(rec)
    if site is None:
        return None
    hit, _ = site
    old = int(hit["a"])
    # 점 뒤에 조사가 붙는 발문('f'(-2)를')이 있어 받침이 같은 수로만 옮긴다(부수 조사 결함 금지).
    new = next(
        (
            old + d
            for d in range(1, 10)
            if has_batchim_text(str(old + d)) == has_batchim_text(str(old))
        ),
        None,
    )
    if new is None:
        return None
    question = str(rec["question_text"])
    out = _clone(rec)
    _set_question(out, question[: hit.start("a")] + str(new) + question[hit.end("a") :])
    return out, f"발문의 점만 {old} → {new}(검산 조건·답은 {old} 그대로)"


def _gt_point_changed(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    site = _point_site(orig)
    if site is None:
        return False
    hit, cond = site
    after = str(mut.get("question_text") or "")
    shown = re.match(r"-?\d+", after[hit.start("a") :])
    if shown is None or int(shown.group()) == int(hit["a"]):
        return False
    displayed = _moved_condition(cond, int(shown.group()))
    return (
        _state(_conditions(orig), _answer_map(orig)) == "pass"
        and _state(displayed, _answer_map(orig)) == "fail"
        and _verify(mut) == _verify(orig)
    )


_DEFINITION_POLY: Final = re.compile(
    r"(?:(?<![A-Za-z])[a-z]\([xt]\)|(?<![A-Za-z])[yx]) = (?P<poly>[-\dxt^ +]+?)(?=[가-힣,(]|$)"
)


def _polynomial_site(rec: Mapping[str, Any]) -> tuple[re.Match[str], re.Match[str]] | None:
    """발문의 함수식 자리 — 미분계수를 볼 점이 발문에 수로 따로 적힌 문항만(`_point_site`).

    점이 함수에서 유도되는 문항(예 'x축과 만나는 점 중 x좌표가 가장 큰 점')은 함수식을 바꾸면 점도
    바뀌어, '발문대로 고친 검산 조건'을 Derivative의 함수만 갈아 끼워 만들 수 없다(GT 불성립).
    """
    question = str(rec.get("question_text") or "")
    if _point_site(rec) is None or "점 (" in question:
        return None
    cond = _EVAL_COND_ANY_ORDER.match(_cond_list(rec)[0])
    if cond is None:
        return None
    target = sympy.expand(safe_sympify(cond["p"]))
    hits = []
    for match in _DEFINITION_POLY.finditer(question):
        parsed = visible_polynomials(match["poly"].strip())
        if len(parsed) == 1 and sympy.expand(parsed[0] - target) == 0:
            hits.append(match)
    return (hits[0], cond) if len(hits) == 1 else None


def _mutated_polynomial(text: str) -> str:
    return re.sub(r"\d+", lambda m: str(int(m.group()) + 1), text, count=1)


def _mut_coefficient_changed(rec: Mapping[str, Any]) -> tuple[Record, str] | None:
    site = _polynomial_site(rec)
    if site is None:
        return None
    hit, _ = site
    old = hit["poly"]
    new = _mutated_polynomial(old)
    if new == old:
        return None
    question = str(rec["question_text"])
    out = _clone(rec)
    _set_question(out, question[: hit.start("poly")] + new + question[hit.end("poly") :])
    return out, f"발문의 함수식만 '{old.strip()}' → '{new.strip()}'(검산 조건·답은 그대로)"


def _gt_coefficient_changed(orig: Mapping[str, Any], mut: Mapping[str, Any]) -> bool:
    site = _polynomial_site(orig)
    if site is None:
        return False
    hit, cond = site
    after = str(mut.get("question_text") or "")
    tail = len(str(orig["question_text"])) - hit.end("poly")
    shown = visible_polynomials(after[hit.start("poly") : len(after) - tail].strip())
    if len(shown) != 1:
        return False
    original_poly = sympy.expand(safe_sympify(cond["p"]))
    if sympy.expand(shown[0] - original_poly) == 0:
        return False
    text = cond.string
    displayed = text[: cond.start("p")] + str(shown[0]) + text[cond.end("p") :]
    return (
        _state(_conditions(orig), _answer_map(orig)) == "pass"
        and _state(displayed, _answer_map(orig)) == "fail"
        and _verify(mut) == _verify(orig)
    )


# ──────────────────────────────────────────────────────────────────────────
# 변이 등록부 — 종류별 할당량의 합 = CLASS_QUOTAS[종류]
# ──────────────────────────────────────────────────────────────────────────
def _v(
    defect_class: BankDefectClass,
    name: str,
    quota: int,
    gt_basis: str,
    gate_overlap: str | None,
    mc: bool | None,
    mutate: Mutator,
    check_gt: GroundTruth,
    allowed: frozenset[str] | None = frozenset(),
) -> Variant:
    return Variant(defect_class, name, quota, gt_basis, gate_overlap, mc, mutate, check_gt, allowed)


#: ⑤ 해설 결함이 만들어도 되는 소견 — 판정기 해설 규칙(E-*)과 스캐너의 해설 부류.
_EXPLANATION_FINDINGS: Final = frozenset(
    {rule for rule in RULE_IDS if rule.startswith("E-")}
    | {
        "explanation_conclusion_only",
        "count_explanation_conclusion_only",
        "mc_trap_double_root_unexplained",
        "mc_trap_irreducible_unexplained",
    }
)


VARIANTS: Final[tuple[Variant, ...]] = (
    # ① 정답 오기 — GT는 SymPy(Tier1과 같은 엔진: 기계 증명이 GT의 권위라 겹침은 정의상 허용).
    _v("answer_error", "answer_and_map", 7, "sympy", "reverify", False,
       _mut_answer_and_map, _gt_answer_and_map),
    _v("answer_error", "answer_only", 4, "sympy", None, False, _mut_answer_only, _gt_answer_only),
    _v("answer_error", "mc_choice_swap", 4, "sympy", "reverify", True,
       _mut_mc_choice_swap, _gt_mc_choice_swap),
    _v("answer_error", "count_off_by_one", 3, "sympy", "reverify", None,
       _mut_count_off_by_one, _gt_count_off_by_one),
    # ② 해 다중·모호
    _v("ambiguous_solution", "statement_only", 9, "sympy", None, None,
       lambda r: _mut_ambiguous(r, relax_verify=False), _gt_ambiguous),
    _v("ambiguous_solution", "statement_and_verify", 8, "sympy", "acceptance", None,
       lambda r: _mut_ambiguous(r, relax_verify=True), _gt_ambiguous),
    # ③ 미분 없이 풀리는 우회로 — 판정기 어휘(canonical) / 판정기 밖 어휘(paraphrase)
    _v("derivative_shortcut", "avg_rate_given", 3, "shortcut_guard", "shortcut_guard", None,
       lambda r: _mut_avg_rate(r, paraphrase=False), _gt_avg_rate,
       frozenset({"T06-given-rate"})),
    _v("derivative_shortcut", "avg_rate_paraphrase", 2, "construction", None, None,
       lambda r: _mut_avg_rate(r, paraphrase=True), _gt_avg_rate),
    _v("derivative_shortcut", "critical_points_given", 3, "shortcut_guard", "shortcut_guard",
       None, lambda r: _mut_critical(r, paraphrase=False), _gt_critical,
       frozenset({"T08-given-critical-points"})),
    _v("derivative_shortcut", "critical_points_paraphrase", 2, "construction", None, None,
       lambda r: _mut_critical(r, paraphrase=True), _gt_critical),
    _v("derivative_shortcut", "minimizer_given", 2, "shortcut_guard", "shortcut_guard", None,
       lambda r: _mut_minimizer(r, paraphrase=False), _gt_minimizer,
       frozenset({"T09-pinned-minimizer"})),
    _v("derivative_shortcut", "minimizer_paraphrase", 2, "construction", None, None,
       lambda r: _mut_minimizer(r, paraphrase=True), _gt_minimizer),
    _v("derivative_shortcut", "zero_monomial", 2, "shortcut_guard", "shortcut_guard", False,
       lambda r: _mut_zero_monomial(r, paraphrase=False), _gt_zero_monomial,
       frozenset({"T-zero-monomial"})),
    _v("derivative_shortcut", "zero_monomial_paraphrase", 1, "construction", None, False,
       lambda r: _mut_zero_monomial(r, paraphrase=True), _gt_zero_monomial),
    # ④ 문장·표기 — 스캐너 어휘 안 4종(순환) + 어휘 밖 2종
    _v("wording_notation", "number_josa", 3, "josa_rule", "text_scanner", None,
       _mut_number_josa, _gt_number_josa, None),
    _v("wording_notation", "undefined_symbol", 3, "construction", "text_scanner", None,
       _mut_undefined_symbol, _gt_undefined_symbol, None),
    _v("wording_notation", "plus_minus", 3, "construction", "text_scanner", None,
       _mut_plus_minus, _gt_plus_minus, None),
    _v("wording_notation", "ascii_inequality", 3, "construction", "shortcut_guard", None,
       _mut_ascii_inequality, _gt_ascii_inequality, None),
    _v("wording_notation", "doubled_josa", 2, "construction", None, None,
       _mut_doubled_josa, _gt_doubled_josa, None),
    _v("wording_notation", "misspelling", 3, "construction", None, None,
       _mut_misspelling, _gt_misspelling, None),
    # ⑤ 해설
    _v("explanation_defect", "steps_removed", 7, "construction", "shortcut_guard", None,
       _mut_steps_removed, _gt_steps_removed, _EXPLANATION_FINDINGS),
    _v("explanation_defect", "derivative_misstated", 6, "sympy", None, None,
       _mut_derivative_misstated, _gt_derivative_misstated, _EXPLANATION_FINDINGS),
    _v("explanation_defect", "arithmetic_slip", 4, "sympy", "acceptance", None,
       _mut_arithmetic_slip, _gt_arithmetic_slip, _EXPLANATION_FINDINGS),
    # ⑥ 오답 선지-오개념 연결
    _v("distractor_misattribution", "to_correct_answer", 8, "construction", None, True,
       _mut_to_answer, _gt_to_answer),
    _v("distractor_misattribution", "to_unrelated_choice", 9, "sympy", None, True,
       _mut_to_unrelated, _gt_to_unrelated),
    # ⑦ 발문-검산 불일치
    _v("statement_mismatch", "point_changed", 9, "sympy", None, None,
       _mut_point_changed, _gt_point_changed),
    _v("statement_mismatch", "coefficient_changed", 8, "sympy", None, None,
       _mut_coefficient_changed, _gt_coefficient_changed),
)  # fmt: skip

#: 선택 순서 — 후보가 좁은 종류부터(객관식 전용 ⑥ → 특정 틀 ③·② → 넓은 ⑦·⑤·①·④).
_SELECTION_ORDER: Final[tuple[BankDefectClass, ...]] = (
    "distractor_misattribution",
    "derivative_shortcut",
    "ambiguous_solution",
    "statement_mismatch",
    "explanation_defect",
    "answer_error",
    "wording_notation",
)


# ──────────────────────────────────────────────────────────────────────────
# 시험지 구성
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SeededBankItem:
    """시험지 1문 — 문항 레코드(변조본 또는 원본) + 정답지(결함 여부·종류·변이·GT 근거·원본 id)."""

    source_problem_id: str
    record: Record
    defect_class: BankDefectClass | None = None
    variant: str | None = None
    gt_basis: str | None = None
    gate_overlap: str | None = None
    mutation_note: str = ""

    @property
    def is_defective(self) -> bool:
        return self.defect_class is not None


def _assert_applied_and_true(variant: Variant, original: Record, mutated: Record) -> None:
    """생성 시 단언 — 주입이 실제로 적용됐고(mutated != original) GT가 성립한다."""
    if _fingerprint(mutated) == _fingerprint(original):
        raise GroundTruthError(
            f"{variant.name}: 주입이 적용되지 않았다({original.get('problem_id')})"
        )
    if not variant.check_gt(original, mutated):
        raise GroundTruthError(f"{variant.name}: GT 불성립({original.get('problem_id')})")
    extra = _side_effects(variant, original, mutated)
    if extra:
        raise GroundTruthError(
            f"{variant.name}: 의도하지 않은 소견 {extra}({original.get('problem_id')})"
        )


def _pick_defects(bank: Sequence[Record], seed: int) -> list[SeededBankItem]:
    used: set[str] = set()
    concept_count: Counter[str] = Counter()
    mc_count: Counter[str] = Counter()
    picked: list[SeededBankItem] = []
    by_class = {cls: [v for v in VARIANTS if v.defect_class == cls] for cls in BANK_DEFECT_CLASSES}
    for defect_class in _SELECTION_ORDER:
        variants = by_class[defect_class]
        if sum(v.quota for v in variants) != CLASS_QUOTAS[defect_class]:
            raise ValueError(f"{defect_class}: 변이 할당량 합이 종류 할당량과 다르다")
        for variant in variants:
            buckets: dict[str, list[Record]] = {}
            for concept in sorted({_concept(r) for r in bank}):
                pool = [
                    r
                    for r in sorted(bank, key=lambda r: str(r["problem_id"]))
                    if _concept(r) == concept and (variant.mc is None or _is_mc(r) == variant.mc)
                ]
                buckets[concept] = list(seeded_order(f"{seed}:{variant.name}:{concept}", pool))
            filled = 0
            while filled < variant.quota:
                open_concepts = [c for c, pool in buckets.items() if pool]
                if not open_concepts:
                    raise ValueError(
                        f"{variant.name}: 적용 가능한 은행 문항 부족({filled}/{variant.quota})"
                    )
                concept = min(open_concepts, key=lambda c: (concept_count[c], c))
                record = buckets[concept].pop(0)
                pid = str(record["problem_id"])
                if pid in used:
                    continue
                if _is_mc(record) and mc_count[concept] >= MAX_MC_DEFECTS_PER_CONCEPT:
                    continue
                result = variant.mutate(record)
                if result is None:
                    continue
                mutated, note = result
                if _fingerprint(mutated) == _fingerprint(record) or not variant.check_gt(
                    record, mutated
                ):
                    continue  # GT가 서지 않는 문항은 이 변이에 부적격
                if _side_effects(variant, record, mutated):
                    continue  # 의도하지 않은 소견을 만드는 문항은 이 변이에 부적격
                used.add(pid)
                concept_count[concept] += 1
                mc_count[concept] += int(_is_mc(record))
                picked.append(
                    SeededBankItem(
                        source_problem_id=pid,
                        record=mutated,
                        defect_class=variant.defect_class,
                        variant=variant.name,
                        gt_basis=variant.gt_basis,
                        gate_overlap=variant.gate_overlap,
                        mutation_note=note,
                    )
                )
                filled += 1
    return picked


def _pick_clean(
    bank: Sequence[Record], defects: Sequence[SeededBankItem], seed: int, n_clean: int
) -> list[SeededBankItem]:
    """정상 문항 — 결함 쪽 (개념 × 객관식 여부) 분포를 그대로, 슬롯은 돌아가며."""
    by_id = {str(r["problem_id"]): r for r in bank}
    target: Counter[tuple[str, bool]] = Counter(
        (_concept(by_id[d.source_problem_id]), _is_mc(by_id[d.source_problem_id])) for d in defects
    )
    if sum(target.values()) != n_clean:
        raise ValueError(
            f"정상 문항 수({n_clean})는 결함 문항 수({sum(target.values())})와 같아야 한다"
        )
    used = {d.source_problem_id for d in defects}
    picked: list[SeededBankItem] = []
    for (concept, mc), need in sorted(target.items()):
        pool = [
            r
            for r in sorted(bank, key=lambda r: str(r["problem_id"]))
            if str(r["problem_id"]) not in used and _concept(r) == concept and _is_mc(r) == mc
        ]
        ordered = list(seeded_order(f"{seed}:clean:{concept}:{mc}", pool))
        slot_count: Counter[str] = Counter()
        chosen: list[Record] = []
        while len(chosen) < need:
            if not ordered:
                raise ValueError(f"정상 문항 풀 소진: {concept} 객관식={mc}")
            least = min(slot_count[_slot(r)] for r in ordered)
            record = next(r for r in ordered if slot_count[_slot(r)] == least)
            ordered.remove(record)
            slot_count[_slot(record)] += 1
            chosen.append(record)
        picked += [SeededBankItem(str(r["problem_id"]), _clone(r)) for r in chosen]
    return picked


def build_qualification_set(
    bank: Sequence[Mapping[str, Any]],
    *,
    seed: int = QUALIFICATION_SEED,
    n_clean: int | None = None,
) -> list[SeededBankItem]:
    """감사자 자격 측정 시험지 — 결함 120(7종) + 정상 120, seed 고정 결정론.

    반환 순서는 결함(선택 순) → 정상(개념 순)이다. 블라인드 제출 순서 섞기와 시험지 id 재부여는
    발행 도구(`harness/p3_audit_qualification`)의 몫이다(정답지 분리와 같은 자리에서 한다).

    생성 시 단언(`GroundTruthError`): 결함마다 변조가 실제로 적용됐는지·GT가 성립하는지를 선택 뒤
    **다시** 확인한다(선택 루프의 판정과 별개 — 공유 객체 변조 같은 파이프라인 결함을 잡는다).
    은행 레코드는 바뀌지 않는다(깊은 사본만 변조).
    """
    records = [_clone(r) for r in bank]
    ids = [str(r.get("problem_id")) for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("은행 problem_id가 중복된다")
    before = [_fingerprint(r) for r in bank]
    defects = _pick_defects(records, seed)
    clean = _pick_clean(records, defects, seed, n_clean if n_clean is not None else len(defects))
    by_id = {str(r["problem_id"]): r for r in records}
    variant_of = {v.name: v for v in VARIANTS}
    for item in defects:
        variant = variant_of[str(item.variant)]
        _assert_applied_and_true(variant, by_id[item.source_problem_id], item.record)
    sources = [i.source_problem_id for i in defects + clean]
    if len(set(sources)) != len(sources):
        raise GroundTruthError("결함 원본과 정상 문항이 같은 은행 문항을 공유한다")
    counts = Counter(str(i.defect_class) for i in defects)
    if dict(counts) != dict(CLASS_QUOTAS):
        raise GroundTruthError(f"종류별 결함 수가 할당량과 다르다: {dict(counts)}")
    if [_fingerprint(r) for r in bank] != before:
        raise GroundTruthError("입력 은행 레코드가 변조됐다")
    return defects + clean
