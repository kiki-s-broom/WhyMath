"""[12미적Ⅰ-02-08] 파생 판정 문항의 저작 형태 규칙 — 코퍼스 적재 전 린트 (P3-24).

게이트 `G-p321-derived-form-disposition`(Kiki 결정 2026-10-05 · 안 나)이 정한 허용 형태를
**코드로 집행**한다. 산문 규칙만 있으면 어긴 문항이 코퍼스에 들어가도 막는 곳이 없다 —
이 모듈이 `populate._record_from_line`(파싱 단계 · DB 왕복 앞)에서 그 문항을 거부한다.
근거 프로브 = `docs/reviews/p3_21_derived_shape_probe_result_2026-10-03.md`(13형태 판정표).
규칙 문서(단서 포함) = `docs/standards/derived_judgment_authoring_rules.md`.

────────────────────────────────────────────────────────────────────────────
규칙 5종 — 위장 2형태는 **저작 규칙으로 유지**하고 4형태는 **제외**한다
────────────────────────────────────────────────────────────────────────────
  규칙 B3  극대·극소의 x좌표를 묻는 문항은 `verify.answer_selection`(smallest/largest)이
           반드시 있다. 없으면 극소점을 극대점이라 답해도 통과한다(두 점 모두 f'=0의 근 —
           프로브 위장).
  규칙 C3  극값의 **값·점**을 묻는 문항은 문항 본문에 극값 x좌표를 **고정**(`x = 2`)하고
           `verify.answer_map`에 x를 싣는다. 점 (x, f(x))를 답으로 받으면 곡선 위 임의의 점이
           통과한다(프로브 위장).
  제외 A4  증감 구간을 **구간 기호**로 답하게 하는 문항 — 검증 재료를 만들 방법이 없다(불가).
  제외 A3  **경계 포함 여부**를 묻는 문항 — 엄격 부등식의 경계점이 skip이라 오답이 걸러지지
           않는다.
  제외 A5  구간을 **함수식 단독 조건**으로 표현한 검산 — 정답도 fail로 나와 오염으로 위장된다.
           (C4 "x 없이 극값의 값만 답"도 정답 오거부라 같은 규칙 C3이 막는다 — x 고정이 곧
           그 해법이다.)

**단서 (이 규칙이 보증하지 않는 것)**
  · B3 규칙이 요구하는 `answer_selection`은 **작성자가 사전 계산한 조건**이다. 검증기가
    극대·극소를 판별하는 것이 아니다 — 최고차항 계수가 음수인 삼차함수에서 같은 방식으로
    달면 극대·극소가 뒤바뀌어 **정답을 오답으로 만든다**. 이 모듈은 selection의 *존재*만
    강제하고 *옳음*은 보지 못한다(작성자 책임).
  · C2류 부호 뒤바꿈 오답은 x가 묶여 있는 동안만 걸러진다 — 그래서 규칙 C3이 x 고정을
    요구한다.
  · 문항 *본문 문자열*과 `verify` 구조를 보는 휴리스틱이다. 모든 위장 표현을 잡는다고
    주장하지 않는다 — 잡지 못하는 표현은
    `docs/standards/derived_judgment_authoring_rules.md` §4에 적었다.

범위: `achievement_standard_codes`에 `[12미적Ⅰ-02-08]`이 있는 문항만 본다(그 밖의 문항은
이 모듈의 대상이 아니다). 순수 함수라 DB·LLM·SymPy를 쓰지 않는다 — 입력은 원시 문자열·dict 뿐이다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "DERIVED_STANDARD_CODE",
    "DerivedFormViolation",
    "derived_form_violations",
]

DERIVED_STANDARD_CODE: Final = "[12미적Ⅰ-02-08]"

# 검산 조건이 "관계식"이라는 증거 — 등호·부등호가 하나도 없으면 함수식 단독이다(제외 A5).
_RELATION = re.compile(r"(<=|>=|!=|==|=|<|>|≤|≥|≠)")
# 구간 기호 답(제외 A4) — 무한대·대괄호 구간. 좌표쌍 `(2, -2)`는 대괄호·∞가 없어 여기 걸리지 않는다.
_INTERVAL_ANSWER = re.compile(r"∞|\[[^\]]*,[^\]]*[\]\)]|\([^)]*,[^)]*\]")
_INTERVAL_QUESTION = re.compile(r"구간\s*기호")
# 경계 포함 여부(제외 A3) — 답이 부등식이거나, 문항이 경계 포함/닫힌·열린 구간을 직접 묻는다.
_INEQUALITY_ANSWER = re.compile(r"^\s*[A-Za-z]\s*(<=|>=|≤|≥|<|>)\s*-?\d")
_BOUNDARY_QUESTION = re.compile(r"경계\s*(를\s*)?포함|경계\s*불포함|닫힌\s*구간|열린\s*구간")
# 극대·극소를 *구별해서* 묻는다는 증거(규칙 B3) — "극값을 갖는 x좌표 중 큰 값"은 구별을
# 묻지 않으므로 제외. 사이시옷 `댓`·`솟`을 빠뜨리면 '극댓값'(표준 표기)이 구별 요구로 읽히지
# 않는다.
_EXTREMUM_KIND = re.compile(r"극[대소댓솟]")
_ASKS_X_COORDINATE = re.compile(r"x\s*좌표")
# 극값의 값·점을 묻는다는 증거(규칙 C3).
# 사이시옷 표기(극댓값·극솟값)까지 잡는다 — `극(대|소)?값`만 쓰면 한국어 표준 표기가 빠진다.
_EXTREMUM_VALUE = re.compile(r"극(대|소)?(댓|솟)?값|극(대|소)점")
_POINT_ANSWER = re.compile(r"^\s*\(\s*[^,()]+,\s*[^,()]+\)\s*$")
_POINT_QUESTION = re.compile(r"\(\s*x\s*,\s*f\s*\(\s*x\s*\)\s*\)")
# 문항 본문이 x를 상수로 고정했다는 증거 — "x=2에서의 극솟값".
_X_PINNED = re.compile(r"(?<![A-Za-z])x\s*=\s*[-−]?\d")

_VALID_SELECTIONS: Final = frozenset({"smallest", "largest", "unique"})


@dataclass(frozen=True, slots=True)
class DerivedFormViolation:
    """위반 1건 — 어느 규칙을 왜 어겼는지 사람이 고칠 수 있게 사유를 싣는다(조용한 통과 금지)."""

    rule: str
    reason: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.reason}"


def _conditions_list(conditions: str | Sequence[str] | None) -> list[str]:
    if conditions is None:
        return []
    if isinstance(conditions, str):
        return [conditions] if conditions.strip() else []
    return [str(c) for c in conditions if str(c).strip()]


def derived_form_violations(
    *,
    standard_codes: Sequence[str],
    question_text: str,
    answer: str | None,
    conditions: str | Sequence[str] | None,
    answer_map: Mapping[str, str] | None,
    answer_selection: str | None,
) -> list[DerivedFormViolation]:
    """02-08 파생 판정 문항의 허용 형태 위반을 모은다 — 빈 리스트면 통과.

    02-08 문항이 아니면 항상 빈 리스트다(범위 밖). `conditions`·`answer_map`·
    `answer_selection`이 모두 비어 있는 문항(= verify 부재)은 형태 판별 재료가 문자열뿐이라
    문자열 규칙만 적용된다.
    """
    if DERIVED_STANDARD_CODE not in standard_codes:
        return []

    text = question_text or ""
    ans = (answer or "").strip()
    out: list[DerivedFormViolation] = []

    # ── 제외 A4 — 구간 기호로 답하기 ──
    if _INTERVAL_QUESTION.search(text) or _INTERVAL_ANSWER.search(ans):
        out.append(
            DerivedFormViolation(
                "A4-interval-notation",
                "증감 구간을 구간 기호로 답하게 하는 문항은 02-08 문항으로 허용하지 않는다 — "
                "검증 재료를 만들 수 없다(P3-21 프로브 '불가'). "
                "경계점·소속 정수 대리 형태로 쓴다.",
            )
        )

    # ── 제외 A3 — 경계 포함 여부 ──
    if _BOUNDARY_QUESTION.search(text) or _INEQUALITY_ANSWER.search(ans):
        out.append(
            DerivedFormViolation(
                "A3-boundary-inclusion",
                "경계 포함 여부를 묻는 문항은 허용하지 않는다 — 엄격 부등식의 경계점은 "
                "검증기가 skip해 오답이 걸러지지 않는다(P3-21 프로브 '일부 가능').",
            )
        )

    # ── 제외 A5 — 구간을 함수식 단독 조건으로 표현 ──
    for cond in _conditions_list(conditions):
        if not _RELATION.search(cond):
            out.append(
                DerivedFormViolation(
                    "A5-bare-expression-condition",
                    f"verify.conditions {cond!r}에 등호·부등호가 없다 — 함수식 단독 조건은 "
                    "정답도 fail로 나와 오염으로 위장된다(P3-21 프로브 '정답 오거부'). "
                    "관계식으로 쓴다.",
                )
            )

    # 열린 구간 `(0, 2)`는 ∞·대괄호가 없어 위 패턴을 통과한다. 좌표쌍과 같은 모양이므로
    # **문항이 구간을 묻는지**(본문에 '구간'이 있고 점·좌표를 묻지 않는다)로 가른다.
    interval_pair = bool(
        _POINT_ANSWER.match(ans)
        and "구간" in text
        and not _POINT_QUESTION.search(text)
        and not re.search(r"점|좌표", text)
    )
    if interval_pair and not _INTERVAL_ANSWER.search(ans) and not _INTERVAL_QUESTION.search(text):
        out.append(
            DerivedFormViolation(
                "A4-interval-notation",
                "구간을 묻는 문항의 답이 열린 구간 기호 (a, b) 모양이다 — 구간 기호 답은 "
                "허용하지 않는다(P3-21 프로브 '불가'). 경계점·소속 정수 대리 형태로 쓴다.",
            )
        )
    asks_point = bool(
        _POINT_QUESTION.search(text) or (_POINT_ANSWER.match(ans) and not interval_pair)
    )
    asks_x = bool(_ASKS_X_COORDINATE.search(text))
    asks_value = bool(_EXTREMUM_VALUE.search(text))

    # ── 규칙 C3 — 극값의 값·점은 x 고정이 필수 ──
    # 점(좌표쌍)을 묻거나, x좌표를 묻지 않으면서 극값의 *값*을 묻는 문항이 대상이다.
    if asks_point or (asks_value and not asks_x):
        pinned = bool(_X_PINNED.search(text))
        has_x = bool(answer_map and "x" in answer_map)
        if not pinned or not has_x:
            missing = []
            if not pinned:
                missing.append("문항 본문에 극값 x좌표 고정(예: 'x=2에서의 극솟값')")
            if not has_x:
                missing.append("verify.answer_map의 x")
            out.append(
                DerivedFormViolation(
                    "C3-pin-extremum-x",
                    "극값의 값·점을 묻는 문항은 극값 x좌표를 고정해야 한다 — 누락: "
                    + " · ".join(missing)
                    + ". 점 (x, f(x))를 답으로 받으면 곡선 위 임의의 점이 통과하고, "
                    "x 없이 값만 받으면 정답도 fail이다(P3-21 프로브 '위장'·'정답 오거부').",
                )
            )
    # ── 규칙 B3 — 극대·극소를 구별해 x좌표를 물으면 selection 필수 ──
    elif asks_x and _EXTREMUM_KIND.search(text):
        if answer_selection not in _VALID_SELECTIONS:
            out.append(
                DerivedFormViolation(
                    "B3-require-answer-selection",
                    "극대·극소의 x좌표를 묻는 문항은 verify.answer_selection"
                    "(smallest/largest)이 필수다 — 없으면 극소점을 극대점이라 답해도 "
                    "통과한다(P3-21 프로브 '위장'). selection은 작성자가 사전 계산한 조건이며 "
                    "최고차항 계수가 음수이면 극대·극소가 뒤바뀐다.",
                )
            )

    return out
