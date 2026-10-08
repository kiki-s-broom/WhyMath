"""오개념 crosswalk(kebab-id ↔ M-id) 골격 단위테스트 — hermetic(PG 불요).

스키마 검증·로더 멱등 upsert·read-time resolver를 fake sync 엔진 주입으로 PG 없이 검증한다
(test_populate.py·test_misconception_loader.py 패턴). 실 PG 왕복은 후속 통합테스트 몫.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

import pytest
from pydantic import ValidationError

from whymath_backend.l1.misconception.crosslink_loader import (
    MisconceptionCrosslinkStore,
    load_crosslinks,
)
from whymath_backend.l1.misconception.crosslink_resolve import (
    MisconceptionCrosslinkResolver,
    ResolvedLink,
    select_canonical,
)
from whymath_backend.schema.misconception_crosslink import MisconceptionCrosslink


# ──────────────────────────────────────────────────────────────────────
# 스키마
# ──────────────────────────────────────────────────────────────────────
class TestSchema:
    def test_full_roundtrip(self) -> None:
        cl = MisconceptionCrosslink(
            kebab_id="distribution-over-power",
            mis_id="M0425",
            link_type="직접매핑",
            confidence=0.82,
            method="manual",
            note="검수: 동일 오개념",
        )
        assert cl.kebab_id == "distribution-over-power"
        assert cl.mis_id == "M0425"
        assert cl.model_dump()["link_type"] == "직접매핑"

    def test_defaults(self) -> None:
        cl = MisconceptionCrosslink(kebab_id="k", mis_id="M1", link_type="부분매핑")
        assert cl.confidence is None
        assert cl.method == "manual"
        assert cl.note is None

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            MisconceptionCrosslink(  # type: ignore[call-arg]
                kebab_id="k", mis_id="M1", link_type="직접매핑", bogus="x"
            )

    def test_bad_link_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MisconceptionCrosslink(kebab_id="k", mis_id="M1", link_type="없는유형")  # type: ignore[arg-type]

    def test_confidence_range(self) -> None:
        with pytest.raises(ValidationError):
            MisconceptionCrosslink(kebab_id="k", mis_id="M1", link_type="직접매핑", confidence=1.5)


# ──────────────────────────────────────────────────────────────────────
# fake sync 엔진 (store/resolver 주입)
# ──────────────────────────────────────────────────────────────────────
class _Row:
    def __init__(
        self,
        kebab_id: str,
        mis_id: str,
        confidence: float | None,
        link_type: str = "직접매핑",
    ) -> None:
        self.kebab_id = kebab_id
        self.mis_id = mis_id
        self.confidence = confidence
        self.link_type = link_type


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeConnection:
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object, parameters: object = None) -> _FakeResult:
        self._engine.executed.append(statement)
        return _FakeResult(self._engine.rows)


class _FakeEngine:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.executed: list[object] = []
        self.rows: list[object] = rows or []

    def begin(self) -> _FakeConnection:
        return _FakeConnection(self)

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


# ──────────────────────────────────────────────────────────────────────
# 로더
# ──────────────────────────────────────────────────────────────────────
class TestLoader:
    def test_empty_returns_zero(self) -> None:
        assert load_crosslinks(None, {"crosslinks": []}) == 0

    def test_populate_upserts_each(self) -> None:
        engine = _FakeEngine()
        store = MisconceptionCrosslinkStore(engine=engine)  # type: ignore[arg-type]
        # load 게이트(Gate Contract)가 method=manual·검수 서명을 요구하므로 promote 산출물 형태
        # (method 기본 manual·note에 서명 stamp)로 준다 — sanctioned 경로 전체를 탄다.
        n = load_crosslinks(
            None,
            {
                "crosslinks": [
                    {
                        "kebab_id": "k1",
                        "mis_id": "M1",
                        "link_type": "직접매핑",
                        "confidence": 0.9,
                        "note": "검수:Kiki 2026-07-08",
                    },
                    {
                        "kebab_id": "k2",
                        "mis_id": "M2",
                        "link_type": "부분매핑",
                        "note": "검수:Kiki 2026-07-08",
                    },
                ]
            },
            store=store,
            # 가짜 엔진은 카탈로그를 모른다 — 이 테스트는 populate의 upsert 횟수를 본다. 외래키 사전확인
            # (HARN-302)은 test_crosslink_fk_precheck.py(단위)·통합 테스트가 따로 고정한다.
            check_fk_targets=False,
        )
        assert n == 2
        assert len(engine.executed) == 2  # 행마다 upsert 1회

    def test_dedup_last_wins_on_unique_key(self) -> None:
        engine = _FakeEngine()
        store = MisconceptionCrosslinkStore(engine=engine)  # type: ignore[arg-type]
        # 같은 (kebab, mis, link_type) 트리플 2건 → 1건으로 dedup(마지막 우선). 서명 stamp 필수.
        n = load_crosslinks(
            None,
            {
                "crosslinks": [
                    {
                        "kebab_id": "k",
                        "mis_id": "M1",
                        "link_type": "직접매핑",
                        "confidence": 0.5,
                        "note": "검수:Kiki 2026-07-08",
                    },
                    {
                        "kebab_id": "k",
                        "mis_id": "M1",
                        "link_type": "직접매핑",
                        "confidence": 0.9,
                        "note": "검수:Kiki 2026-07-08",
                    },
                ]
            },
            store=store,
            check_fk_targets=False,  # 위와 같은 이유(HARN-302)
        )
        assert n == 1
        assert len(engine.executed) == 1

    def test_path_missing_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_crosslinks(None, Path("/nonexistent/crosslink.json"))

    def test_bad_input_type_raises(self) -> None:
        with pytest.raises(TypeError):
            load_crosslinks(None, 123)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────
# read-time resolver
# ──────────────────────────────────────────────────────────────────────
class TestResolver:
    def test_resolve_returns_mids(self) -> None:
        engine = _FakeEngine(rows=[_Row("k", "M2", 0.7), _Row("k", "M1", 0.9)])
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        # confidence 내림차순 → M1(0.9) 먼저, M2(0.7).
        assert resolver.resolve("k") == ["M1", "M2"]

    def test_resolve_missing_returns_empty(self) -> None:
        engine = _FakeEngine(rows=[])
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        assert resolver.resolve("nope") == []

    def test_resolve_many_groups_by_kebab(self) -> None:
        engine = _FakeEngine(
            rows=[_Row("a", "M1", 0.9), _Row("b", "M2", 0.8), _Row("a", "M3", 0.5)]
        )
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        out = resolver.resolve_many(["a", "b"])
        assert out["a"] == ["M1", "M3"]  # confidence 내림차순
        assert out["b"] == ["M2"]

    def test_resolve_many_empty_input(self) -> None:
        engine = _FakeEngine()
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        assert resolver.resolve_many([]) == {}

    def test_null_confidence_sorts_last(self) -> None:
        engine = _FakeEngine(rows=[_Row("k", "M_null", None), _Row("k", "M_hi", 0.6)])
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        assert resolver.resolve("k") == ["M_hi", "M_null"]  # 값 있는 것 먼저, NULL 마지막


# ──────────────────────────────────────────────────────────────────────
# canonical 선택 정책 (select_canonical — 순수·DB 0)
# ──────────────────────────────────────────────────────────────────────
def _link(mis_id: str, link_type: str = "직접매핑", confidence: float | None = 0.9) -> ResolvedLink:
    return ResolvedLink(mis_id=mis_id, link_type=link_type, confidence=confidence)


class TestSelectCanonical:
    def test_single_direct_max_is_ok(self) -> None:
        """단독 최대 confidence 직접매핑 → canonical 선정(reason='ok')."""
        sel = select_canonical(
            [
                _link("M1", confidence=0.9),
                _link("M2", confidence=0.7),
                _link("M3", "부분매핑", confidence=0.95),  # 비직접은 아무리 높아도 후보 아님
            ]
        )
        assert sel.canonical_mis_id == "M1"
        assert sel.ambiguous is False
        assert sel.direct_count == 2  # confidence NOT NULL 직접매핑 수
        assert sel.reason == "ok"

    def test_tie_is_ambiguous_and_unselected(self) -> None:
        """직접매핑 최고 confidence 동률 → 자동 임의 선택 금지(canonical 없음·ambiguous)."""
        sel = select_canonical([_link("M1", confidence=0.8), _link("M2", confidence=0.8)])
        assert sel.canonical_mis_id is None
        assert sel.ambiguous is True
        assert sel.direct_count == 2
        assert sel.reason == "tie"

    def test_only_non_direct_is_no_direct(self) -> None:
        """부분매핑·개념겹침만 존재 → 직접 부재(reason='no_direct')."""
        sel = select_canonical(
            [_link("M1", "부분매핑", confidence=0.9), _link("M2", "개념겹침", confidence=0.9)]
        )
        assert sel.canonical_mis_id is None
        assert sel.ambiguous is False
        assert sel.direct_count == 0
        assert sel.reason == "no_direct"

    def test_null_confidence_direct_excluded(self) -> None:
        """confidence NULL 직접매핑은 후보 제외 — NULL 무시하고 값 있는 단독 최대가 선정된다."""
        sel = select_canonical([_link("M_null", confidence=None), _link("M1", confidence=0.7)])
        assert sel.canonical_mis_id == "M1"
        assert sel.direct_count == 1  # NULL은 후보 수에서도 제외
        assert sel.reason == "ok"
        # 전부 NULL이면 직접 부재와 동일 취급(선정 불가·정직).
        all_null = select_canonical([_link("M_null", confidence=None)])
        assert all_null.canonical_mis_id is None
        assert all_null.reason == "no_direct"

    def test_empty_links_is_no_links(self) -> None:
        """링크 0 → reason='no_links'(빈 crosswalk 초기 상태를 정직히 구분)."""
        sel = select_canonical([])
        assert sel.canonical_mis_id is None
        assert sel.ambiguous is False
        assert sel.direct_count == 0
        assert sel.reason == "no_links"


# ──────────────────────────────────────────────────────────────────────
# link_type 포함 일반화 조회 + resolve_canonical (fake 엔진)
# ──────────────────────────────────────────────────────────────────────
class TestResolveLinks:
    def test_resolve_links_includes_type_and_confidence(self) -> None:
        engine = _FakeEngine(
            rows=[_Row("k", "M2", 0.7, "부분매핑"), _Row("k", "M1", 0.9, "직접매핑")]
        )
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        links = resolver.resolve_links("k")
        # confidence 내림차순(기존 결정론 그대로) + link_type·confidence 동반.
        assert links == [
            ResolvedLink(mis_id="M1", link_type="직접매핑", confidence=0.9),
            ResolvedLink(mis_id="M2", link_type="부분매핑", confidence=0.7),
        ]

    def test_resolve_links_missing_returns_empty(self) -> None:
        resolver = MisconceptionCrosslinkResolver(engine=_FakeEngine(rows=[]))  # type: ignore[arg-type]
        assert resolver.resolve_links("nope") == []

    def test_resolve_links_many_groups_by_kebab(self) -> None:
        engine = _FakeEngine(
            rows=[
                _Row("a", "M1", 0.9),
                _Row("b", "M2", 0.8, "개념겹침"),
                _Row("a", "M3", None),
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        out = resolver.resolve_links_many(["a", "b"])
        assert [link.mis_id for link in out["a"]] == ["M1", "M3"]  # NULL 마지막
        assert out["b"][0].link_type == "개념겹침"

    def test_resolve_canonical_applies_policy(self) -> None:
        """resolve_canonical = 조회(resolve_links) + select_canonical 정책 합성."""
        engine = _FakeEngine(
            rows=[
                _Row("k", "M1", 0.9, "직접매핑"),
                _Row("k", "M2", 0.9, "부분매핑"),  # 비직접 동률은 tie 아님
            ]
        )
        resolver = MisconceptionCrosslinkResolver(engine=engine)  # type: ignore[arg-type]
        sel = resolver.resolve_canonical("k")
        assert sel.canonical_mis_id == "M1"
        assert sel.reason == "ok"
