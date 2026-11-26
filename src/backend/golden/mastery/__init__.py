"""골든 숙련도 엔진(GP-6) — simple(공유 계약)과 bkt(T3 · S32 섀도) 두 가지.

- simple: 맞으면 +0.10 · 틀리면 −0.05(공유 계약 · `golden/api.py`). `golden.students.mastery`의
  값이며 이 계약은 S32에서 바꾸지 않는다.
- bkt: `golden.mastery.bkt.update`(S31 제안 파라미터). 값은 `golden.mastery_shadow`에만 쌓인다.
- 플래그 `GOLDEN_MASTERY_ENGINE=simple|bkt`(기본 simple)는 판정 응답의 `mastery`에
  **어느 엔진의 값을 실을지**만 정한다. 두 엔진의 계산·섀도 기록은 플래그와 무관하게 늘 한다.
"""

from __future__ import annotations

import os
from typing import Literal

from golden.mastery.bkt import GOLDEN_BKT_PARAMETERS, update

# 플래그 이름과 엔진 이름(섀도 표 engine 열에 그대로 쓴다)
FLAG_ENV = "GOLDEN_MASTERY_ENGINE"
Engine = Literal["simple", "bkt"]
ENGINE_SIMPLE: Engine = "simple"
ENGINE_BKT: Engine = "bkt"

# bkt 엔진의 시작 숙련도 — 섀도 기록이 아직 없는 학생은 P(L0)에서 시작한다
BKT_INITIAL = GOLDEN_BKT_PARAMETERS.p_init


def response_engine() -> Engine:
    """판정 응답 `mastery`에 실을 엔진. 값이 정확히 `bkt`일 때만 bkt, 그 밖은 전부 simple.

    호출 시점에 읽는다. 오타·빈 값·대문자(`BKT`)는 simple로 떨어진다 — 기본값이 화면 계약이다.
    """
    return "bkt" if os.environ.get(FLAG_ENV) == ENGINE_BKT else "simple"


__all__ = [
    "BKT_INITIAL",
    "ENGINE_BKT",
    "ENGINE_SIMPLE",
    "FLAG_ENV",
    "Engine",
    "response_engine",
    "update",
]
