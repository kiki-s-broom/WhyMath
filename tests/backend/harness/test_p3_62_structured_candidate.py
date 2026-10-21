"""P3-62 규칙 (가) 후보 은행 — 생성기·배치 수준 계약(결정론·문항 집합 보존·게이트 통과).

검증 축
-------
① 02-08 생성기(그래프 개형)의 구조화 문항이 실재하고(0건이면 공허 — 실패), 전부 조건만으로 증명된다.
② 후보 배치는 **같은 시드 2회 바이트 동일**이고, 기본 배치와 **문항 집합(slug·순서)이 같다** — 바뀌는 것은
   구조화 문항의 `verify.conditions`·`verify.solution_steps`뿐이다(분모 불변).
③ 후보의 구조화 문항은 풀이 끝이 정답 변수의 값 진술이며 그 값이 정답 기록과 같다.
④ 후보 사이드카에만 후보 표기(`solution_structuring`)가 있다 — 기본 사이드카 바이트 불변.
⑤ 수용 게이트를 전 문항이 통과한다(배치 수율 100% — 거부 0).

생성기를 돌리므로 corpus-authoring 잡이 실행한다(PB-13).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest

from whymath_backend.harness import p3_calculus1_diff_batch as batch
from whymath_backend.l3.equivalent.p3_diff_graph_shape_skeleton_generator import (
    P3DiffGraphShapeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import structured_view

pytestmark = pytest.mark.corpus_authoring

_GENERATORS = (P3DiffGraphShapeGenerator,)


@functools.cache
def _run(structured: bool, tag: str) -> tuple[batch.CorpusBatchReport, bytes]:
    """02-08 생성기 하나만 돌린 은행 바이트(모드별·실행별 캐시 — `tag`가 다르면 다시 돈다)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "problems.jsonl"
        report = batch.run_p3_calculus1_diff_batch(
            generators=_GENERATORS, out_path=out, structure_final_step=structured
        )
        return report, out.read_bytes()


def _rows(raw: bytes) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def test_structured_items_exist_and_are_provable() -> None:
    items = [
        item
        for slot in P3DiffGraphShapeGenerator.slots
        for item in P3DiffGraphShapeGenerator.items(slot)
        if item.structured_conditions is not None
    ]
    assert items, "구조화 문항 0건 — 규칙 (가)가 이 생성기에 닿지 않았다"
    stated: set[str] = set()
    for item in items:
        view = structured_view(item)
        assert view is not None
        stated.add(view[1][-1].split(" = ", 1)[0])
    # 극값의 값(y)을 묻는 틀과 상수 k를 묻는 틀이 둘 다 구조화돼 있다(한쪽 빌더만 남으면 RED).
    assert stated == {"y", "k"}


def test_candidate_is_deterministic_and_keeps_the_item_set() -> None:
    first_report, first = _run(True, "a")
    _, second = _run(True, "b")
    default_report, default = _run(False, "a")
    assert first == second  # 같은 시드 2회 바이트 동일
    assert first != default  # 주입이 실제로 들어갔다(구조화가 무효면 같은 바이트)
    assert first_report.total_stored == first_report.total_requested  # 수용 게이트 거부 0
    assert default_report.total_stored == default_report.total_requested
    cand, base = _rows(first), _rows(default)
    assert [r["slug"] for r in cand] == [r["slug"] for r in base]  # 분모(문항 집합·순서) 불변
    changed = 0
    for new, old in zip(cand, base, strict=True):
        new_rest = {k: v for k, v in new.items() if k != "verify"}
        old_rest = {k: v for k, v in old.items() if k != "verify"}
        assert new_rest == old_rest  # 발문·정답·해설·선지는 그대로
        new_verify = dict(new["verify"])  # type: ignore[call-overload]
        old_verify = dict(old["verify"])  # type: ignore[call-overload]
        for key in ("conditions", "solution_steps"):
            new_verify.pop(key)
            old_verify.pop(key)
        assert new_verify == old_verify  # answer_map·selection 등 나머지 검산 재료 불변
        if new["verify"] != old["verify"]:
            changed += 1
            steps = new["verify"]["solution_steps"]  # type: ignore[index]
            var, value = str(steps[-1]).split("=", 1)
            answer_map = new["verify"]["answer_map"]  # type: ignore[index]
            assert answer_map[var.strip()] == value.strip()  # 진술값 == 정답 기록
    assert changed > 0


def test_candidate_provenance_is_marked_and_default_is_not() -> None:
    marked = batch.build_provenance(_GENERATORS, structured=True)
    plain = batch.build_provenance(_GENERATORS)
    assert marked["solution_structuring"] == batch.STRUCTURING_NOTE
    assert "solution_structuring" not in plain
    assert {k: v for k, v in marked.items() if k != "solution_structuring"} == plain
