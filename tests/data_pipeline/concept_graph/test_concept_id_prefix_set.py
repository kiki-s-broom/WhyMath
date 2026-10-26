"""개념 ID 접두(subject) 집합 — 패턴이 리터럴이 아니라 집합에서 조립됨을 동결한다 (ADR-009 · ADR-003).

지키는 것 4가지:
  1. 동작 불변 — 접두를 집합으로 옮겨도 개념 그래프 정본(`graph.json`)의 모든 ID(와 별칭)가
     옛 리터럴 정규식과 **똑같은 판정**을 받는다(전수 대조).
  2. 변별력 — 집합에 다른 접두를 넣었을 때만 그 접두 ID의 판정이 바뀐다.
  3. 빈 집합·잘못된 토큰은 조립 단계에서 거부된다(빈 접두가 `.area.slug`를 통과시키는 것 방지).
  4. 현행 상수 `SUBJECT_PREFIXES`가 정본 ID의 접두를 실제로 덮는다(집합을 비우거나 바꾸면 RED).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from data_pipeline.concept_graph.models import (
    CONCEPT_ID_PATTERN,
    SUBJECT_PREFIXES,
    build_concept_id_pattern,
)

_GRAPH = Path(__file__).resolve().parents[3] / "data/corpus/concept_graph_v1/graph.json"

# 이 변경 이전의 리터럴 정규식 — 동작 불변을 대조하는 **기준선**이다(프로덕션 코드에는 이제 없다).
_LEGACY_LITERAL = re.compile(r"^math\.[a-z]+(-[a-z]+)*\.[a-z0-9]+(-[a-z0-9]+)*$")

# 거부되어야 하는 대표 형태(접두 누락·대문자·비ASCII·세그먼트 누락 등) — 옛 패턴과 판정이 같아야 한다.
_NEGATIVES = [
    "geometry.x",
    "math.Geometry.x",
    "math.geometry.삼각형",
    "math.geometry",
    "math.geometry.",
    "math..x",
    "UC.calc.limit.def",
    "ELEM-GEO-001",
    "mathx.geometry.x",  # 접두가 math로 시작하되 다른 토큰 — 경계(`\.`) 절을 밟는 반례
    "xmath.geometry.x",  # 앞에 글자가 붙은 접두 — 앵커(`^`) 절을 밟는 반례
    ".geometry.x",  # 빈 접두
    "",
]


def _graph_ids() -> tuple[list[str], list[str]]:
    data = json.loads(_GRAPH.read_text(encoding="utf-8"))
    concepts = data["concepts"]
    ids = [c["concept_id"] for c in concepts]
    aliases = [a for c in concepts for a in c.get("aliases", [])]
    return ids, aliases


def test_graph_ids_get_identical_verdicts_old_vs_new() -> None:
    """정본 개념 ID 전수 + 별칭 전수 + 음성 표본이 옛 리터럴과 같은 판정을 받는다."""
    ids, aliases = _graph_ids()
    assert ids, "스캔 0건은 실패 — graph.json에서 개념 ID를 하나도 못 읽었다"
    for cid in ids:
        assert _LEGACY_LITERAL.match(cid), f"기준선이 정본 ID를 거부: {cid}"
        assert CONCEPT_ID_PATTERN.match(cid), f"조립 패턴이 정본 ID를 거부: {cid}"
    for text in [*aliases, *_NEGATIVES]:
        assert bool(CONCEPT_ID_PATTERN.match(text)) == bool(_LEGACY_LITERAL.match(text)), text
        assert not CONCEPT_ID_PATTERN.match(text), f"음성 표본이 통과: {text!r}"


def test_assembled_pattern_keeps_group_layout() -> None:
    """캡처 그룹 개수가 리터럴 시절과 같다 — 접두는 비캡처 그룹이라 그룹 번호가 밀리지 않는다."""
    assert CONCEPT_ID_PATTERN.groups == _LEGACY_LITERAL.groups == 2
    assert CONCEPT_ID_PATTERN.pattern == build_concept_id_pattern(SUBJECT_PREFIXES).pattern


def test_prefix_set_covers_every_canonical_id_prefix() -> None:
    """정본 ID의 접두가 모두 현행 집합에 있다 — 집합을 비우거나 math를 빼면 여기서 RED."""
    ids, _ = _graph_ids()
    used = {cid.split(".", 1)[0] for cid in ids}
    assert used, "접두를 하나도 못 읽었다"
    assert used <= SUBJECT_PREFIXES, f"집합에 없는 접두: {used - SUBJECT_PREFIXES}"


def test_other_prefix_changes_verdict_only_when_added() -> None:
    """다른 접두(chem)는 집합에 넣었을 때만 통과한다 — 패턴 수정 없이 집합 1토큰으로 끝난다."""
    chem_id = "chem.reaction.balancing-coefficients"
    math_id = "math.geometry.samgakhyeong"

    math_only = build_concept_id_pattern({"math"})
    assert math_only.match(math_id)
    assert not math_only.match(chem_id)

    both = build_concept_id_pattern({"math", "chem"})
    assert both.match(math_id)
    assert both.match(chem_id)

    chem_only = build_concept_id_pattern({"chem"})
    assert chem_only.match(chem_id)
    assert not chem_only.match(math_id)  # 집합에 없는 접두는 거부 — 리터럴 math가 숨어 있지 않다


def test_assembly_is_deterministic_regardless_of_input_order() -> None:
    """접두는 정렬되어 조립된다 — 입력 순서·중복과 무관하게 패턴 문자열이 같다."""
    tail = r"\.[a-z]+(-[a-z]+)*\.[a-z0-9]+(-[a-z0-9]+)*$"
    expected = "^(?:chem|math)" + tail
    assert build_concept_id_pattern(["math", "chem"]).pattern == expected
    assert build_concept_id_pattern(["chem", "math", "math"]).pattern == expected


def test_empty_prefix_set_is_rejected_at_assembly() -> None:
    """빈 집합을 그대로 조립하면 `^(?:)\\.…`가 되어 접두 없는 ID가 통과한다 — 그래서 거부한다."""
    with pytest.raises(ValueError):
        build_concept_id_pattern(frozenset())


@pytest.mark.parametrize("bad_token", ["", "Math", "ma.th", "math1", "ma-th", " math"])
def test_malformed_prefix_token_is_rejected(bad_token: str) -> None:
    with pytest.raises(ValueError):
        build_concept_id_pattern({"math", bad_token})
