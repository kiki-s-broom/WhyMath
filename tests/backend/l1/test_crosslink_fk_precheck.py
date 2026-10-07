"""적재 전 외래키 대상 사전확인 — 단위(hermetic, SQLite 메모리) (HARN-302).

정본 사고(2026-10-07 G-misc40 DB 동기화): 크로스링크 적재가 첫 행에서 `ForeignKeyViolation`으로 실패했고,
오류는 누락 키 **하나**만 말했다. 이 파일은 `l1/fk_precheck.py`의 판정 절을 하나씩 밟는다 — 실 PostgreSQL
관통은 `test_crosslink_fk_precheck_integration.py`가 맡는다.

픽스처가 밟아야 하는 절 (각 절이 없으면 통과하는 입력을 따로 둔다):
  · 누락 전건 열거(첫 하나만 말하지 않는다)  · 존재하는 값은 누락이 아니다(대조군)
  · NULL은 외래키가 검사하지 않는다            · 외래키가 둘이면 각각 따로 보고한다
  · 값 중복은 한 번만 센다                     · 청크 경계를 넘는 값 수
  · 복합 외래키는 건너뛰지 않고 멈춘다          · 대상이 하나도 없으면 질의하지 않는다
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from whymath_backend.l1.fk_precheck import (
    _CHUNK,
    ForeignKeyTargetMissingError,
    MissingFkTargets,
    missing_fk_targets,
)
from whymath_backend.l1.misconception import crosslink_loader
from whymath_backend.l1.misconception.crosslink_loader import load_crosslinks


def _schema() -> tuple[sa.MetaData, sa.Table, sa.Table, sa.Table, sa.Table]:
    meta = sa.MetaData()
    parent_a = sa.Table("parent_a", meta, sa.Column("code", sa.String(32), primary_key=True))
    parent_b = sa.Table("parent_b", meta, sa.Column("code", sa.String(32), primary_key=True))
    child = sa.Table(
        "child",
        meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("a_code", sa.String(32), sa.ForeignKey("parent_a.code")),
        sa.Column("b_code", sa.String(32), sa.ForeignKey("parent_b.code")),
    )
    composite = sa.Table(
        "composite_child",
        meta,
        sa.Column("x", sa.String(8)),
        sa.Column("y", sa.String(8)),
        sa.ForeignKeyConstraint(["x", "y"], ["pair.x", "pair.y"]),
    )
    sa.Table(
        "pair",
        meta,
        sa.Column("x", sa.String(8), primary_key=True),
        sa.Column("y", sa.String(8), primary_key=True),
    )
    return meta, parent_a, parent_b, child, composite


@pytest.fixture
def db():
    meta, parent_a, parent_b, child, composite = _schema()
    engine = sa.create_engine("sqlite://")
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(parent_a.insert(), [{"code": "A1"}, {"code": "A2"}, {"code": "ZZ_LAST"}])
        conn.execute(parent_b.insert(), [{"code": "B1"}])
    with engine.connect() as conn:
        yield conn, child, composite, parent_a


class TestMissingTargets:
    def test_all_missing_values_are_listed_not_just_the_first(self, db) -> None:
        """사고 형태 — 누락 키가 여럿이면 전부 말한다(첫 행 오류는 하나만 말했다)."""
        conn, child, _, _ = db
        rows = [{"a_code": "A1"}, {"a_code": "X9"}, {"a_code": "X1"}, {"a_code": "X5"}]
        result = missing_fk_targets(conn, child, rows)
        assert [(m.constraint, m.values) for m in result] == [
            ("child.a_code -> parent_a.code", ("X1", "X5", "X9"))
        ]

    def test_existing_targets_are_not_reported(self, db) -> None:
        """대조군 — 대상이 전부 있으면 빈 리스트(모든 입력을 누락으로 보고하는 검사는 검사가 아니다)."""
        conn, child, _, _ = db
        assert missing_fk_targets(conn, child, [{"a_code": "A1"}, {"a_code": "A2"}]) == []

    def test_null_values_are_skipped(self, db) -> None:
        """NULL은 외래키가 검사하지 않는다 — 누락으로 세면 정상 적재를 거부한다."""
        conn, child, _, _ = db
        assert missing_fk_targets(conn, child, [{"a_code": None}, {"b_code": None}]) == []

    def test_duplicate_values_are_counted_once(self, db) -> None:
        conn, child, _, _ = db
        result = missing_fk_targets(conn, child, [{"a_code": "X1"}] * 5)
        assert result[0].values == ("X1",)

    def test_two_foreign_keys_are_reported_separately(self, db) -> None:
        conn, child, _, _ = db
        rows = [{"a_code": "X1", "b_code": "Y1"}, {"a_code": "A1", "b_code": "Y2"}]
        result = missing_fk_targets(conn, child, rows)
        assert {m.constraint: m.values for m in result} == {
            "child.a_code -> parent_a.code": ("X1",),
            "child.b_code -> parent_b.code": ("Y1", "Y2"),
        }

    def test_only_the_missing_foreign_key_is_reported(self, db) -> None:
        """한쪽만 누락이면 다른 쪽은 보고하지 않는다."""
        conn, child, _, _ = db
        result = missing_fk_targets(conn, child, [{"a_code": "A1", "b_code": "Y1"}])
        assert [m.constraint for m in result] == ["child.b_code -> parent_b.code"]

    def test_values_beyond_one_chunk_are_all_checked(self, db) -> None:
        """청크 경계 — 뒤쪽 청크에 **존재하는** 값이 있어도 누락으로 오보하지 않는다.

        첫 청크만 확인하면 확인하지 않은 값이 전부 '누락'이 되어, 누락 값만 있는 입력에서는 정답과
        같아 보인다(2026-10-07 뮤테이션 M3이 이 입력으로 살아남았다). 정렬상 맨 뒤에 오는 존재 값
        `ZZ_LAST`를 둘째 청크 너머에 두어 그 절의 반례로 삼는다.
        """
        conn, child, _, _ = db
        rows = [{"a_code": f"Z{i:05d}"} for i in range(_CHUNK * 2 + 7)]
        rows += [{"a_code": "A1"}, {"a_code": "ZZ_LAST"}]  # 존재 값: 첫 청크 안 · 맨 뒤 청크
        result = missing_fk_targets(conn, child, rows)
        assert len(result[0].values) == _CHUNK * 2 + 7
        assert "ZZ_LAST" not in result[0].values, "뒤쪽 청크의 존재 값을 누락으로 오보했다"
        assert "A1" not in result[0].values

    def test_no_rows_means_no_query_and_no_findings(self, db) -> None:
        conn, child, _, _ = db
        assert missing_fk_targets(conn, child, []) == []

    def test_composite_foreign_key_stops_loudly(self, db) -> None:
        """복합 외래키를 조용히 건너뛰면 '확인했다'는 거짓 보고가 된다."""
        conn, _, composite, _ = db
        with pytest.raises(NotImplementedError, match="복합 외래키"):
            missing_fk_targets(conn, composite, [{"x": "1", "y": "2"}])

    def test_table_without_foreign_keys_has_nothing_to_check(self, db) -> None:
        conn, _, _, parent_a = db
        assert missing_fk_targets(conn, parent_a, [{"code": "ANY"}]) == []

    def test_check_is_read_only(self, db) -> None:
        """확인은 읽기만 한다 — 호출 전후 어느 테이블도 바뀌지 않는다."""
        conn, child, _, parent_a = db
        before = conn.execute(sa.select(sa.func.count()).select_from(parent_a)).scalar_one()
        missing_fk_targets(conn, child, [{"a_code": "NEW1"}, {"a_code": "NEW2"}])
        after = conn.execute(sa.select(sa.func.count()).select_from(parent_a)).scalar_one()
        assert before == after == 3  # 픽스처 부모 행: A1·A2·ZZ_LAST


class TestErrorMessage:
    def test_message_lists_every_missing_value(self) -> None:
        err = ForeignKeyTargetMissingError(
            [MissingFkTargets("t.c -> p.c", ("M1", "M2")), MissingFkTargets("t.d -> q.d", ("Q9",))]
        )
        text = str(err)
        for needle in (
            "M1",
            "M2",
            "Q9",
            "t.c -> p.c",
            "t.d -> q.d",
            "3건",
            "아무것도 쓰지 않았습니다",
        ):
            assert needle in text, f"{needle} 누락 — 일부만 보여 주면 고치고 다시 돌려 또 걸린다"
        assert err.missing[0].values == ("M1", "M2")


# ── 로더 배선: 사전확인이 쓰기 앞에서 실제로 쓰기를 막는가 ───────────────────────
_SIGNED = "검수:Kiki 2026-10-07"


def _payload(*mis_ids: str) -> dict[str, Any]:
    return {
        "crosslinks": [
            {
                "kebab_id": "k",
                "mis_id": mid,
                "link_type": "직접매핑",
                "confidence": 0.9,
                "note": _SIGNED,
            }
            for mid in mis_ids
        ]
    }


class _StubStore:
    """사전확인 결과를 지정하고 `populate` 호출 여부를 기록하는 좌석."""

    def __init__(self, missing: list[MissingFkTargets]) -> None:
        self._missing = missing
        self.checked = 0
        self.populated = 0

    def missing_fk_targets(self, _records: Any) -> list[MissingFkTargets]:
        self.checked += 1
        return self._missing

    def populate(self, records: Any) -> int:
        self.populated += 1
        return len(list(records))


class TestLoaderWiring:
    def test_missing_target_raises_before_any_write(self) -> None:
        store = _StubStore([MissingFkTargets("misconception_crosslink.mis_id -> x.y", ("M2",))])
        with pytest.raises(ForeignKeyTargetMissingError):
            load_crosslinks(None, _payload("M1", "M2"), store=store)  # type: ignore[arg-type]
        assert store.checked == 1 and store.populated == 0, "누락이면 populate를 부르면 안 된다"

    def test_present_targets_proceed_to_write(self) -> None:
        store = _StubStore([])
        n = load_crosslinks(None, _payload("M1", "M2"), store=store)  # type: ignore[arg-type]
        assert n == 2 and store.checked == 1 and store.populated == 1

    def test_opt_out_skips_the_check(self) -> None:
        """가짜 엔진 hermetic 테스트용 좌석 — 끄면 확인 자체를 하지 않는다."""
        store = _StubStore([MissingFkTargets("a -> b", ("M1",))])
        load_crosslinks(None, _payload("M1"), store=store, check_fk_targets=False)  # type: ignore[arg-type]
        assert store.checked == 0 and store.populated == 1

    def test_default_is_on(self) -> None:
        """기본값이 꺼져 있으면 실 경로(promote --load)가 보호받지 못한다."""
        import inspect

        default = inspect.signature(load_crosslinks).parameters["check_fk_targets"].default
        assert default is True

    def test_gate_violation_still_wins_before_the_fk_check(self) -> None:
        """게이트(검수 서명) 위반은 FK 확인보다 먼저다 — 검수 우회를 DB 조회로 확인하지 않는다."""
        store = _StubStore([])
        bad = _payload("M1")
        bad["crosslinks"][0]["note"] = "서명 없음"
        with pytest.raises(crosslink_loader.CrosslinkGateError):
            load_crosslinks(None, bad, store=store)  # type: ignore[arg-type]
        assert store.checked == 0


class TestRealStoreMethod:
    def test_store_method_checks_the_real_orm_foreign_key(self) -> None:
        """Store.missing_fk_targets가 실제 ORM 모델의 mis_id 외래키를 본다(스키마 이름 고정)."""
        from whymath_backend.db.models.misconception_crosslink import MisconceptionCrosslink

        fks = {
            (fk.parent.name, fk.column.table.name, fk.column.name)
            for fk in MisconceptionCrosslink.__table__.foreign_keys
        }
        assert fks == {("mis_id", "misconception_catalog", "mis_id")}
