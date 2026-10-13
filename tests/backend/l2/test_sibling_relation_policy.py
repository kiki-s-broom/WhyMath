"""PB-19 — CAT 형제 필터의 관계 유형 정책(`classify_relations`·`load_sibling_ids`).

배경: `load_sibling_ids`는 `problem_relation`을 유형·방향 없이 전부 "형제"로 모았다. PB-09가
선수(쉬운 계열)·심화(어려운 계열)·대조(역문제) 계보를 낳으면 `exclude`가 쉬운 계열까지 후보에서 빼고
`include`가 심화를 우대한다 — Polya "더 쉬운 관련 문제를 먼저"와 어긋난다. 정책 정본 =
`docs/architecture/cat_sibling_filter_relation_policy_pb19.md`.

이 파일은 **DB 없이** 정책의 표를 동결한다. 핸들러→정책→쿼리까지 이어진 배선은
`tests/backend/api/test_me.py::TestSiblingRelationTypePolicy`가 맡는다.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from whymath_backend.l2 import next_problem_selection as nps
from whymath_backend.l2.next_problem_selection import (
    RelationRoles,
    classify_relations,
    load_sibling_ids,
    sibling_weights,
)
from whymath_backend.schema.enums import RelationType


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


# ── 정책 표: 유형 × 방향 → 역할 ──────────────────────────────────────────────────────
class TestRoleTable:
    """행은 항상 parent(기존 문항) → related(파생). 오답 문항 W가 parent냐 related냐에 따라 뒤집힌다."""

    @pytest.mark.parametrize(
        ("relation", "w_is_parent", "role"),
        [
            # 대칭 — 방향 무관
            (RelationType.변형, True, "siblings"),
            (RelationType.변형, False, "siblings"),
            (RelationType.유사, True, "siblings"),
            (RelationType.유사, False, "siblings"),
            # 선수: related가 parent의 선수(더 쉬움)
            (RelationType.선수, True, "easier"),  # W→O: O는 W의 선수
            (RelationType.선수, False, "harder"),  # O→W: W가 O의 선수 → O는 W의 후속
            # 심화: related가 parent의 심화(더 어려움)
            (RelationType.심화, True, "harder"),  # W→O: O는 W의 심화
            (RelationType.심화, False, "easier"),  # O→W: W가 O의 심화 → O는 W의 기초
            # 대조는 어느 역할에도 들어가지 않는다
            (RelationType.대조, True, None),
            (RelationType.대조, False, None),
        ],
    )
    def test_role_by_type_and_direction(
        self, relation: RelationType, w_is_parent: bool, role: str | None
    ) -> None:
        w, o = _ids(2)
        row = (w, o, relation) if w_is_parent else (o, w, relation)
        roles = classify_relations(w, [row])
        by_name = {"siblings": roles.siblings, "easier": roles.easier, "harder": roles.harder}
        for name, members in by_name.items():
            assert (o in members) is (name == role), (name, relation, w_is_parent)

    def test_every_relation_type_has_an_explicit_consumption_role(self) -> None:
        """`RelationType` 전 멤버가 대칭/선수/심화/중립 중 **정확히 하나**로 명시돼 있다.

        신규 멤버(예: 보완)가 생기면 이 대조가 RED를 낸다 — 소비 역할이 정해지지 않은 유형이
        조용히 "형제 아님"으로 흘러가거나 "형제"로 취급되는 것을 막는다.
        """
        groups = [
            set(nps._SYMMETRIC_RELATIONS),
            {nps._PREREQUISITE_RELATION},
            {nps._EXTENSION_RELATION},
            set(nps._NEUTRAL_RELATIONS),
        ]
        assert sum(len(g) for g in groups) == len(set().union(*groups)), "역할 집합이 겹친다"
        assert set().union(*groups) == set(RelationType)

    def test_unclassified_type_fails_loudly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """역할이 정해지지 않은 유형은 조용히 넘기지 않는다(침묵 실패 금지)."""
        monkeypatch.setattr(nps, "_NEUTRAL_RELATIONS", frozenset())
        w, o = _ids(2)
        with pytest.raises(ValueError, match="소비 역할이 정해지지 않았다"):
            classify_relations(w, [(w, o, RelationType.대조)])


# ── 모순·우선순위·방어 ───────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_sibling_wins_over_directed_role(self) -> None:
        """근접 복제본(대칭 관계)이 한 번이라도 있으면 쉬운/어려운 계열 행이 더 있어도 형제다."""
        w, o = _ids(2)
        roles = classify_relations(w, [(w, o, RelationType.선수), (o, w, RelationType.유사)])
        assert roles.siblings == {o}
        assert roles.easier == frozenset()
        assert roles.harder == frozenset()

    def test_contradictory_direction_is_neutral(self) -> None:
        """같은 상대가 쉬운 쪽과 어려운 쪽 양쪽으로 나오면(모순) 어느 쪽도 아니다 — 모른다 ≠ 아니다."""
        w, o = _ids(2)
        roles = classify_relations(w, [(w, o, RelationType.선수), (w, o, RelationType.심화)])
        assert roles == RelationRoles(frozenset(), frozenset(), frozenset())

    def test_self_relation_is_ignored(self) -> None:
        w = uuid.uuid4()
        assert classify_relations(w, [(w, w, RelationType.변형)]).siblings == frozenset()

    def test_accepts_raw_string_values(self) -> None:
        """DB 드라이버가 문자열을 돌려줘도 같은 분류다(`RelationType`은 str-Enum)."""
        w, o = _ids(2)
        assert classify_relations(w, [(w, o, "선수")]).easier == {o}

    def test_empty_rows(self) -> None:
        assert classify_relations(uuid.uuid4(), []) == RelationRoles(
            frozenset(), frozenset(), frozenset()
        )


# ── 모드별 소비 집합 ─────────────────────────────────────────────────────────────────
class TestIdsForMode:
    def _mixed(self) -> tuple[uuid.UUID, dict[str, uuid.UUID], RelationRoles]:
        w = uuid.uuid4()
        cast = {n: uuid.uuid4() for n in ("sib", "easy", "hard", "contrast")}
        rows = [
            (w, cast["sib"], RelationType.변형),
            (w, cast["easy"], RelationType.선수),
            (w, cast["hard"], RelationType.심화),
            (w, cast["contrast"], RelationType.대조),
        ]
        return w, cast, classify_relations(w, rows)

    def test_exclude_removes_only_symmetric_siblings(self) -> None:
        _w, c, roles = self._mixed()
        assert roles.ids_for("exclude") == {c["sib"]}

    def test_include_prefers_siblings_and_easier_not_harder(self) -> None:
        _w, c, roles = self._mixed()
        assert roles.ids_for("include") == {c["sib"], c["easy"]}

    def test_unknown_mode_is_rejected(self) -> None:
        _w, _c, roles = self._mixed()
        with pytest.raises(ValueError, match="알 수 없는 sibling_filter"):
            roles.ids_for("only")

    def test_boost_weights_apply_to_included_ids_only(self) -> None:
        """`include`가 고른 집합이 그대로 가중에 쓰인다 — 어려운 계열·대조는 1.0(중립)."""
        _w, c, roles = self._mixed()
        pool = [c["sib"], c["easy"], c["hard"], c["contrast"]]
        assert sibling_weights(pool, roles.ids_for("include")) == [2.0, 2.0, 1.0, 1.0]


# ── load_sibling_ids — 쿼리 1회 + 분류 경유 + 현행 동작 대조군 ─────────────────────────────
class _Rows:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _OneShotSession:
    """execute 호출을 기록하고 준비된 행을 돌려주는 최소 세션."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Rows:
        self.statements.append(stmt)
        return _Rows(self._rows)


def _legacy_sibling_ids(problem_id: uuid.UUID, rows: list[tuple[Any, ...]]) -> set[uuid.UUID]:
    """PB-19 이전의 `load_sibling_ids` 본문 — 유형·방향 무시, 상대편 id를 전부 형제로 수집(대조군)."""
    out: set[uuid.UUID] = set()
    for parent_id, related_id, *_rest in rows:
        other = related_id if parent_id == problem_id else parent_id
        if other != problem_id:
            out.add(other)
    return out


class TestLoadSiblingIds:
    async def test_single_query_selects_relation_type_and_routes_through_classifier(self) -> None:
        w, sib, easy, hard = _ids(4)
        rows = [
            (w, sib, RelationType.유사),
            (w, easy, RelationType.선수),
            (w, hard, RelationType.심화),
        ]
        session = _OneShotSession(rows)
        excluded = await load_sibling_ids(session, w, sibling_filter="exclude")  # type: ignore[arg-type]
        assert len(session.statements) == 1  # 쿼리 0회 증가 보존 — 유형 컬럼만 SELECT에 추가
        assert "problem_relation.relation_type" in str(session.statements[0])
        assert excluded == {sib}
        included = await load_sibling_ids(session, w, sibling_filter="include")  # type: ignore[arg-type]
        assert included == {sib, easy}

    async def test_mixed_corpus_legacy_overcollects_new_policy_does_not(self) -> None:
        """대조군 — 현행(PB-19 이전) 동작은 선수·심화·대조까지 형제로 모은다(결함의 실재 증명)."""
        w, sib, easy, hard, contrast = _ids(5)
        rows = [
            (w, sib, RelationType.변형),
            (w, easy, RelationType.선수),
            (w, hard, RelationType.심화),
            (w, contrast, RelationType.대조),
        ]
        assert _legacy_sibling_ids(w, rows) == {sib, easy, hard, contrast}
        new = await load_sibling_ids(_OneShotSession(rows), w, sibling_filter="exclude")  # type: ignore[arg-type]
        assert new == {sib}
        assert new < _legacy_sibling_ids(w, rows)

    @pytest.mark.parametrize("mode", ["exclude", "include"])
    async def test_symmetric_only_corpus_is_unchanged_from_legacy(self, mode: str) -> None:
        """**회귀 0** — 변형·유사만 있는 코퍼스(현재 운영 상태)에서는 두 모드 모두 이전과 같은 집합이다."""
        w, a, b, c = _ids(4)
        rows = [
            (w, a, RelationType.변형),
            (b, w, RelationType.유사),  # 반대 방향 행
            (w, c, RelationType.유사),
        ]
        got = await load_sibling_ids(_OneShotSession(rows), w, sibling_filter=mode)  # type: ignore[arg-type]
        assert got == _legacy_sibling_ids(w, rows) == {a, b, c}
