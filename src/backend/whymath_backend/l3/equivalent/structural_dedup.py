"""저작 산출물 구조적 중복 사전 차단 — 검수 큐 진입 전 같은 좌석·좌석 간 중복 CU 제외 (EOS-204).

왜 필요한가
----------
EOS-197 A6 회차 검수에서 Kiki가 완전 중복 2쌍을 반려했다(검수 큐 26↔30 · 7↔10). 큐 조립(런북 [I]·
`harness/authoring_round.assemble_queue`)은 **slug**(발문·정답·성취기준 코드의 해시)가 같을 때만
걸렀으므로 `x좌표가 2인 점`과 `점 (2, 3)`처럼 **표기만 다른** 같은 문항은 그대로 큐에 들어갔다.
게다가 중복은 F1~F8 실패 코드 어느 것에도 해당하지 않아 검수자가 F8(힌트 정답 누설)로 적었고, 실패
유형 분포가 왜곡됐다 (원 기록은 위변조하지 않는다 — 이 모듈은 다음 회차부터 검수자가 중복을
**고르지 않게** 한다).

구조 서명 (`structural_signature`)
--------------------------------
표면 문자열이 아니라 문항의 **수학 구조**로 같음을 판정한다. 서명은 다섯 칸이다.

1. **묻는 것의 종류** — 발문의 핵심어 집합(접선·y절편·극댓값·속도·개수·큰 근 …). 같은 함수에서
   극댓값과 y절편을 물으면 우연히 정답이 같아도 다른 문항이다.
2. **문항 함수 정규형** — 함수 정의(`f(x) = …`)를 변수 이름과 무관하게 정규화한다. 기본은 함수
   원형(상수항 포함)이다. **도함수로 접는 것은 한 유형뿐**이다 — '개수'를 묻고 `f(x) = k` 같은
   매개변수 조건이 있는 문항. 검수 큐 7↔10은 상수항만 달랐는데(`x^3 - 3x^2 + 1` vs `+ 4`) Kiki가
   "도함수·풀이·정답이 모두 같다"고 판정했다. 그 밖에서 도함수로 접으면 상수항만 다르고 정답이
   우연히 같은 다른 문항(미분계수 vs 함숫값)이 합쳐진다(독립 검토 지적).
3. **발문 고유 방정식** — 근을 묻는 방정식의 정규형(`canonicalize.canonical_condition`,
   스케일·부호 무관). 변수가 하나면 x로 바꿔 비교한다(`t^2 - 5t + 6 = 0` = `x^2 - 5x + 6 = 0`).
4. **점** — 함수식·방정식 밖에 적힌 수(부호 포함). 좌표쌍 `(a, f(a))`의 둘째 성분만 뺀다
   (`점 (2, 3)`의 3 = f(2)).
5. **정답 정규형** — SymPy로 읽은 값(`4/2`와 `2`는 같다 · `−3`과 `-3` · `x = 2`와 `2`도 같다).
   소수는 분수·무리수로 바꾸지 않는다. 못 읽으면 공백을 지운 원문.

발문에서 함수도 방정식도 읽지 못하면(서명 재료 없음) 구조 서명을 내지 않고(None) slug 비교만 한다 —
모른다 ≠ 같다.

큐 조립 (`split_structural_duplicates`)
-------------------------------------
소비자는 둘이다 — 기본 경로 `harness/authoring_round.stage_queue`(한 줄 실행)와 런북 [I] 수동
경로 CLI.
기존 `assemble_queue`와 **같은 순서**(좌석을 한 건씩 번갈아)로 훑으며 slug 또는 구조 서명이 앞서
나온 것과 같으면 큐에서 빼고 사유와 함께 별도 목록으로 남긴다. 먼저 나온 것이 남는다(26·7이 남고
30·10이 빠진다 — Kiki 판정과 같다). 같은 좌석 안의 중복도 같은 규칙으로 걸린다.

한계
----
- 서명 재료는 `authoring_guard.extract_question_relations`가 읽는 범위(다항·유리식 표기)뿐이다.
- 핵심어 표는 실측된 문항 유형만 담는다 — 표에 없는 유형끼리는 1칸이 비지만, 함수 원형·점·정답이
  모두 같아야 병합되므로 서로 다른 양을 물어 정답이 우연히 같을 때만 합쳐진다.
- 읽지 못한 행(JSON 파손·객체 아님)은 큐에서 빼고 `unreadable_row` 사유로 남긴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain, zip_longest
from pathlib import Path

import sympy

from whymath_backend.l3.equivalent.authoring_guard import extract_question_relations
from whymath_backend.l3.equivalent.canonicalize import canonical_condition
from whymath_backend.l3.safe_parse import safe_sympify

__all__ = [
    "DroppedCu",
    "main",
    "split_structural_duplicates",
    "structural_signature",
]

# 묻는 것의 종류 — 실측 문항 유형의 핵심어(EOS-197 회차 + 이차방정식 좌석). 더 긴 말을 먼저 둔다.
_ASK_KEYWORDS: tuple[str, ...] = (
    "가속도",
    "속도",
    "접선",
    "y절편",
    "x절편",
    "극댓값",
    "극솟값",
    "최댓값",
    "최솟값",
    "개수",
    "큰 근",
    "작은 근",
    "두 근의 합",
    "두 근의 곱",
    "기울기",
    "미분계수",
    "순간변화율",
    "평균변화율",
    "함숫값",
    "실근",
    "넓이",
    "정적분",
)
# 도함수 기호 — `f'(1)`처럼 핵심어 없이 미분값을 묻는 발문을 함숫값 `f(1)`과 가른다.
_DERIVATIVE_MARK = re.compile(r"[A-Za-z]\s*(?:'|′|’)\s*\(")

_VAR = sympy.Symbol("x")

Signature = tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], str]


def _asks(question_text: str) -> tuple[str, ...]:
    text = re.sub(r"\s+", " ", question_text)
    found: list[str] = []
    for word in _ASK_KEYWORDS:
        if word in text:
            found.append(word)
            text = text.replace(word, " ")  # `가속도` 안의 `속도`가 따로 잡히지 않게
    if _DERIVATIVE_MARK.search(question_text):
        found.append("도함수값")
    return tuple(sorted(found))


def _answer_key(answer: object) -> str:
    """정답 정규형 — 유니코드 빼기·`x = 2` 꼴 머리를 정리하고 값으로 읽는다.

    소수는 `nsimplify`하지 않는다 — 근삿값 `1.41421356`이 `sqrt(2)`로 바뀌어 정확값과 합쳐지면
    안 된다.
    """
    text = str(answer).strip().replace("−", "-")
    text = re.sub(r"^[A-Za-z]\s*=\s*", "", text)
    try:
        value = safe_sympify(text)
    except Exception:  # noqa: BLE001 — 못 읽은 정답은 원문 비교로(공백만 정규화)
        return re.sub(r"\s+", "", text)
    if isinstance(value, sympy.Expr):
        return str(sympy.sstr(sympy.simplify(value)))
    return re.sub(r"\s+", "", text)


def structural_signature(row: Mapping[str, object]) -> Signature | None:
    """코퍼스 행 1건 → 구조 서명(모듈 docstring 5칸). 발문 수식을 못 읽으면 None."""
    question = str(row.get("question_text") or "")
    relations = extract_question_relations(question)
    if not relations.functions and not relations.own_equations:
        return None
    asks = _asks(question)
    # 함수 칸 — 기본은 함수 원형(상수항까지)이다. 도함수로 비교하는 것은 Kiki가 판정한 유형(검수 큐
    # 7↔10: '개수'를 묻고 `f(x) = k` 같은 매개변수 조건이 있는 문항)뿐이다. 그 밖에서 도함수로
    # 접으면 상수항만 다르고 정답이 우연히 같은 다른 문항(미분계수 vs 함숫값)이 합쳐진다.
    use_derivative = "개수" in asks and _has_parameter_condition(relations)
    functions = sorted(
        sympy.sstr(
            sympy.expand(
                (sympy.diff(body, sympy.Symbol(var)) if use_derivative else body).subs(
                    sympy.Symbol(var), _VAR
                )
            )
        )
        for var, body in relations.functions
    )
    equations = sorted(
        form
        for form in (canonical_condition(_rename_single_var(eq)) for eq in relations.own_equations)
        if form
    )
    points = sorted(sympy.sstr(n) for n in relations.point_numbers)
    return (
        asks,
        tuple(functions),
        tuple(equations),
        tuple(points),
        _answer_key(row.get("answer", "")),
    )


def _has_parameter_condition(relations: object) -> bool:
    """함수 적용 조건 `f(x) = k`처럼 함수 변수 밖의 매개변수가 든 방정식이 있는가."""
    function_vars = {var for var, _ in getattr(relations, "functions", ())}
    own = set(getattr(relations, "own_equations", ()))
    for equation in getattr(relations, "equations", ()):
        if equation in own:
            continue
        try:
            symbols = {
                str(s) for side in equation.split("=") for s in safe_sympify(side).free_symbols
            }
        except Exception:  # noqa: BLE001 — 못 읽은 조건은 매개변수 조건으로 세지 않는다
            continue
        if symbols - function_vars:
            return True
    return False


def _rename_single_var(equation: str) -> str:
    """변수가 하나뿐인 방정식은 그 변수를 x로 바꾼다 — `t^2 - 5t + 6 = 0`과 x 표기를 같게."""
    try:
        sides = [safe_sympify(side) for side in equation.split("=")]
    except Exception:  # noqa: BLE001 — 못 읽으면 원문 그대로(정규형 비교에 맡김)
        return equation
    symbols = set().union(*(side.free_symbols for side in sides))
    if len(symbols) != 1:
        return equation
    (only,) = symbols
    return " = ".join(sympy.sstr(side.subs(only, _VAR)) for side in sides)


@dataclass(frozen=True, slots=True)
class DroppedCu:
    """큐에서 뺀 CU 1건 — 사유와 함께 별도 목록으로 남긴다(검수자가 고르지 않게)."""

    slug: str
    seat_index: int
    duplicate_of: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "seat_index": self.seat_index,
            "duplicate_of": self.duplicate_of,
            "reason": self.reason,
        }


def split_structural_duplicates(
    seat_rows: Sequence[Sequence[str]],
) -> tuple[list[str], list[DroppedCu]]:
    """좌석 산출물 줄들 → (큐에 넣을 줄, 뺀 CU 목록). 순서는 좌석을 한 건씩 번갈아(런북 [I])."""
    kept: list[str] = []
    dropped: list[DroppedCu] = []
    seen_slugs: set[str] = set()
    by_signature: dict[Signature, str] = {}
    interleaved = chain.from_iterable(
        zip_longest(*[[(i, r) for r in rows] for i, rows in enumerate(seat_rows)])
    )
    for item in interleaved:
        if item is None:  # 짧은 좌석이 끝난 자리(zip_longest 채움값)
            continue
        seat, raw = item
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            row = None
        if not isinstance(row, dict):
            # 읽지 못한 행은 검수할 수 없다 — 큐 전체를 죽이지 않고 사유와 함께 뺀다.
            dropped.append(DroppedCu("", seat, "", "unreadable_row"))
            continue
        slug = str(row["slug"]) if row.get("slug") else ""
        # slug가 없으면 집합에 넣지 않으므로(아래) `None`끼리 전부 중복으로 묶이지 않는다.
        if slug in seen_slugs:
            dropped.append(DroppedCu(slug, seat, slug, "slug_duplicate"))
            continue
        signature = structural_signature(row)
        if signature is not None and signature in by_signature:
            dropped.append(DroppedCu(slug, seat, by_signature[signature], "structural_duplicate"))
            continue
        if slug:
            seen_slugs.add(slug)
        if signature is not None:
            by_signature[signature] = slug
        kept.append(raw)
    return kept, dropped


_REASONS = ("slug_duplicate", "structural_duplicate", "unreadable_row")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_rows(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """런북 [I] 수동 경로용 CLI — 큐와 제외 목록을 쓰고 판정 줄을 출력한다.

    큐가 이미 있으면 거부한다(앞 검수의 분모가 바뀌므로).
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seat", action="append", required=True, type=Path, help="좌석 cu.jsonl")
    parser.add_argument("--queue", required=True, type=Path, help="쓸 검수 큐 경로")
    parser.add_argument("--dropped", required=True, type=Path, help="뺀 CU 목록(JSONL) 경로")
    args = parser.parse_args(argv)
    if args.queue.exists():
        print("QUEUE_WRITTEN=False REASON=queue_file_already_exists")
        return 1
    rows = [_read_rows(p) for p in args.seat]
    kept, dropped = split_structural_duplicates(rows)
    # 제외 목록을 먼저, 큐를 나중에 쓴다 — 큐 파일의 존재가 '조립 완료' 표지이고 재실행은 큐가
    # 있으면 거부하므로, 제외 목록 쓰기가 실패한 채 큐만 남는 상태를 만들지 않는다.
    # 둘 다 임시 파일에 쓴 뒤 교체한다.
    _write_atomic(
        args.dropped,
        "".join(json.dumps(d.to_json(), ensure_ascii=False) + "\n" for d in dropped),
    )
    _write_atomic(args.queue, "".join(ln + "\n" for ln in kept))
    back = len(_read_rows(args.queue))
    counts = {reason: sum(1 for d in dropped if d.reason == reason) for reason in _REASONS}
    print("SEAT_ROWS=" + ",".join(str(len(r)) for r in rows))
    print(
        f"SLUG_DUP={counts['slug_duplicate']} STRUCT_DUP={counts['structural_duplicate']} "
        f"UNREADABLE={counts['unreadable_row']} DROPPED_FILE={args.dropped}"
    )
    print(f"QUEUE_WRITTEN={back == len(kept)} QUEUE_LINES={back}")
    return 0 if back == len(kept) else 1


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    sys.exit(main())
