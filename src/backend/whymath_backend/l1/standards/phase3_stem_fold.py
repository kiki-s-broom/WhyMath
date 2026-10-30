"""문면 근사 중복 접기 — "서로 다른 문제가 몇 개인가"를 세는 기준의 정의 한 곳 (P3-05).

Phase 3 의 6슬롯·Problem Coverage 는 "문항이 있다"가 아니라 "서로 다른 문제가 있다"를 보려는
지표다. 같은 문제에서 숫자만 바꾼 변형 390건(적격 917건 → 고유 527개, 2026-10-15 실측)을 별개로
세면 칸이 실제보다 촘촘해 보인다. 이 모듈이 그 "같다"의 정의를 소유한다.

## 기준은 1단이다 (2단은 보류)

1단 = 문면에서 숫자(정수·소수)를 `#` 로 접고 공백을 정리한 문자열이 같으면 같은 문제.

2단(한 글자 변수·함수 이름까지 접기)은 **구현하지 않았다.** 2026-10-15 실측에서 2단이 1단에
더한 합침이 0건이었다 — 이 코퍼스는 결정론 생성기로 만들어져 변수가 `x`(3,085회)·`f`(1,049회)로
통일돼 있어 이름만 바꾼 변형이 없다. 양성 대조군(변수 이름만 다른 같은 문제)에서는 2단 규칙이
반응했으므로 규칙이 죽어서 0인 것이 아니다. 코퍼스에 그런 변형이 생기면(예: 5단계 신규 생성이
변수 이름을 바꿔 쓰는 경우) 이 모듈에 2단을 더하는 것으로 재개한다. Kiki 결정 ③ 정정(2026-10-15).

## 모르면 합치지 않는다

문면을 모르는 문항(`None`·빈 문자열)은 서로 "같다"고 보지 않는다. 비어 있는 두 문면이 같은 문제로
합쳐지면 측정 못 한 것이 중복 제거로 위장된다. 그런 문항은 각각 1건으로 세고, **몇 건을 그렇게
셌는지** 결과에 함께 낸다(`DistinctCount.unfolded`) — 알고리즘을 붙였으면 실제로 작동한 비율을
말한다(CLAUDE.md "작동한 비율" 원칙).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

#: 정수·소수. 1단 기준이 접는 유일한 대상이다(2단 변수 접기는 위 머리말대로 보류).
_NUMBER: Final = re.compile(r"\d+(?:\.\d+)?")
_SPACES: Final = re.compile(r"\s+")

#: 접힌 숫자 자리표시. 문면에 원래 `#` 이 있어도 숫자와 구분되지 않지만, 접기는 양쪽 문면에 같은
#: 규칙을 적용하므로 같음/다름 판정에는 영향이 없다.
NUMBER_PLACEHOLDER: Final = "#"


def fold_stem(text: str | None) -> str | None:
    """문면 → 접힌 문면. 문면을 모르거나 접은 결과가 비면 None(= 측정 못함)."""
    if text is None:
        return None
    folded = _SPACES.sub(" ", _NUMBER.sub(NUMBER_PLACEHOLDER, text)).strip()
    return folded or None


@dataclass(frozen=True)
class DistinctCount:
    """고유 문면 수와, 문면을 몰라 접지 못하고 각각 1건으로 센 문항 수."""

    distinct: int
    unfolded: int
    total: int


def distinct_count(stems: Iterable[str | None]) -> DistinctCount:
    """문항들의 문면에서 서로 다른 문제의 수를 센다.

    접을 수 있는 문항은 접힌 문면의 고유 수로, 접을 수 없는 문항(문면 None·빈 값)은 각각 1건으로
    센다. 합치지 않는 쪽이 안전한 방향이다 — 모르는 것을 같다고 하면 부족을 숨긴다.
    """
    folded: set[str] = set()
    unfolded = 0
    total = 0
    for text in stems:
        total += 1
        key = fold_stem(text)
        if key is None:
            unfolded += 1
        else:
            folded.add(key)
    return DistinctCount(distinct=len(folded) + unfolded, unfolded=unfolded, total=total)


__all__ = ["NUMBER_PLACEHOLDER", "DistinctCount", "distinct_count", "fold_stem"]
