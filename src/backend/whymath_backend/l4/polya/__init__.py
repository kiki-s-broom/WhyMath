"""Polya 4단계 코칭 엔진 — `docs/architecture/04_pedagogy_engine.md` §"Polya 4단계 엔진".

`prompts` 정본 프롬프트 4단계·`transitions` 휴리스틱 단계 판정·`engine` `PolyaCoach`
(결정·조립 + L3 호출 좌석).
"""

from __future__ import annotations

from whymath_backend.l4.polya.engine import PolyaCoach
from whymath_backend.l4.polya.prompts import (
    BACKTRACK_PROMPT,
    STAGE_PROMPTS,
    StagePrompt,
    base_system_for_grade,
)
from whymath_backend.l4.polya.transitions import should_advance

__all__ = [
    "BACKTRACK_PROMPT",
    "PolyaCoach",
    "STAGE_PROMPTS",
    "StagePrompt",
    "base_system_for_grade",
    "should_advance",
]
