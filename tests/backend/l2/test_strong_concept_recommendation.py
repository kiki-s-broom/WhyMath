"""L2 강개념 추천 — `strong_concept_recommendation` 단위테스트 (hermetic·PG 불요·ASM-13).

`weak_concept_recommendation` 테스트(`test_weak_concept_recommendation.py`)의 거울상. 신호
정의(두 신호 중 최저값)는 완전히 동일하고, 필터 방향(≥ threshold)과 정렬 방향(최고 mastery
먼저)만 반대다. 이 파일은 그 반대 방향이 실제로 지켜지는지, 그리고 atom_node enrich가 weak과
같은 방식으로 배선됐는지를 못 박는다(진단 로직·실 PG 조인은 `compute_concept_diagnoses` 자체
테스트 몫).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import whymath_backend.l2.strong_concept_recommendation as scr_mod
from whymath_backend.l1.atom_graph.atom_node_projection import AtomNodeMeta
from whymath_backend.l2.concept_diagnosis import Agreement, ConceptDiagnosis
from whymath_backend.l2.strong_concept_recommendation import (
    StrongConceptRecommendation,
    recommend_strong_concepts,
)

_UID = uuid.uuid4()
_UC_A = "UC.alg.afunction.linear"
_UC_B = "UC.calc.alimit.epsilon-delta"


def _diagnosis(
    *,
    code: str | None,
    name: str | None = "개념",
    bkt: float | None,
    proxy: float | None,
    agreement: Agreement = "agree",
    cid: uuid.UUID | None = None,
) -> ConceptDiagnosis:
    return ConceptDiagnosis(
        concept_id=cid or uuid.uuid4(),
        concept_code=code,
        concept_name=name,
        bkt_mastery=bkt,
        irt_theta=None,
        irt_mastery_proxy=proxy,
        response_count=0,
        agreement=agreement,
    )


def _fake_session() -> AsyncSession:
    return cast(AsyncSession, object())


def _patch_diagnoses(monkeypatch: pytest.MonkeyPatch, diagnoses: list[ConceptDiagnosis]) -> None:
    """`compute_concept_diagnoses`를 패치 — 실제 계약대로 *약점 먼저*(오름차순) 순서로 준다."""

    async def _fake(_session: AsyncSession, _user_id: uuid.UUID) -> list[ConceptDiagnosis]:
        return diagnoses

    monkeypatch.setattr(scr_mod, "compute_concept_diagnoses", _fake)


def _patch_meta(
    monkeypatch: pytest.MonkeyPatch, meta: dict[str, AtomNodeMeta] | None = None
) -> dict[str, Any]:
    captured: dict[str, Any] = {"calls": 0}
    resolved_meta = meta if meta is not None else {}

    async def _fake_fetch(
        session: AsyncSession, concept_ids: Sequence[str]
    ) -> dict[str, AtomNodeMeta]:
        captured["calls"] += 1
        captured["concept_ids"] = list(concept_ids)
        captured["session"] = session
        return resolved_meta

    monkeypatch.setattr(scr_mod, "fetch_atom_axis_meta", _fake_fetch)
    return captured


# ──────────────────────────────────────────────────────────────────────────
# ① 강점 필터 — 최저 신호 ≥ 임계만·신호 0건 제외·임계 경계(포함)
# ──────────────────────────────────────────────────────────────────────────
class TestStrengthFilter:
    async def test_keeps_at_or_above_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.3, proxy=0.5),  # 최저 0.3 < 0.7 → 제외
                _diagnosis(code=_UC_B, bkt=0.9, proxy=0.95),  # 최저 0.9 ≥ 0.7 → 강점
            ],
        )
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_B]
        assert out[0].mastery == 0.9  # 두 신호 중 최저

    async def test_threshold_boundary_includes_equal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 경계: mastery == threshold면 *이상*이므로 포함(weak의 < 비교와 정반대 방향).
        _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.7, proxy=0.8)])
        out = await recommend_strong_concepts(_fake_session(), _UID, mastery_threshold=0.7)
        assert [r.concept_code for r in out] == [_UC_A]
        assert out[0].mastery == 0.7

    async def test_no_signal_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=None, proxy=None, agreement="insufficient"),
                _diagnosis(code=_UC_B, bkt=0.9, proxy=None, agreement="insufficient"),
            ],
        )
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_B]

    async def test_empty_diagnoses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [])
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert out == []
        assert captured["calls"] == 0


# ──────────────────────────────────────────────────────────────────────────
# ⓐ diagnoses 스냅샷 재사용 (PR #1018 Codex 리뷰 — 동시 mastery 갱신 시 스냅샷 불일치 방지)
# ──────────────────────────────────────────────────────────────────────────
class TestDiagnosesSnapshotReuse:
    async def test_passed_diagnoses_skips_internal_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        async def _boom(_session: AsyncSession, _user_id: uuid.UUID) -> list[ConceptDiagnosis]:
            calls["n"] += 1
            raise AssertionError("diagnoses가 주어졌는데 내부에서 재조회했다")

        monkeypatch.setattr(scr_mod, "compute_concept_diagnoses", _boom)
        _patch_meta(monkeypatch)
        given = [_diagnosis(code=_UC_A, bkt=0.8, proxy=0.9)]
        out = await recommend_strong_concepts(_fake_session(), _UID, diagnoses=given)
        assert calls["n"] == 0
        assert [r.concept_code for r in out] == [_UC_A]


# ──────────────────────────────────────────────────────────────────────────
# ② 정렬 — 진단은 약점 먼저(오름차순)로 오지만, 강점 추천은 최고 mastery가 먼저(내림차순)
# ──────────────────────────────────────────────────────────────────────────
class TestSortReversed:
    async def test_reverses_ascending_diagnosis_order_to_strongest_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_meta(monkeypatch)
        # compute_concept_diagnoses 계약대로 약점 먼저(오름차순) 정렬된 입력을 준다.
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.75, proxy=0.8),  # mastery 0.75
                _diagnosis(code=_UC_B, bkt=0.95, proxy=0.99),  # mastery 0.95(더 강함)
            ],
        )
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_B, _UC_A]  # 강한 순으로 뒤집힘


# ──────────────────────────────────────────────────────────────────────────
# ③ limit 상한 — 강점 정렬(내림차순) 보존하며 상위 N
# ──────────────────────────────────────────────────────────────────────────
class TestLimit:
    async def test_limit_caps_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [_diagnosis(code=f"UC.x.y.{i}", bkt=0.7 + i * 0.01, proxy=0.9) for i in range(5)],
        )
        out = await recommend_strong_concepts(_fake_session(), _UID, limit=2)
        assert len(out) == 2
        # 오름차순 입력 마지막 두 개(가장 강함)가 뒤집혀 앞에 온다.
        assert [r.concept_code for r in out] == ["UC.x.y.4", "UC.x.y.3"]


# ──────────────────────────────────────────────────────────────────────────
# ④ enrich — atom_node 메타 부착·미적재 code None·orphan·단일 호출(weak과 동일 배선)
# ──────────────────────────────────────────────────────────────────────────
class TestEnrichment:
    async def test_attaches_node_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {
            _UC_A: AtomNodeMeta(
                name_ko="일차함수", subject_area="[중]함수", review_status="reviewed"
            )
        }
        captured = _patch_meta(monkeypatch, meta)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.8, proxy=0.9)])
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert out[0].name_ko == "일차함수"
        assert out[0].domain == "[중]함수"
        assert out[0].review_status == "reviewed"
        assert captured["calls"] == 1
        assert captured["concept_ids"] == [_UC_A]

    async def test_missing_meta_is_none_graceful(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        _patch_meta(monkeypatch, meta)
        # 입력은 실제 계약대로 약점 먼저(오름차순) — _UC_B가 약하지만 여전히 임계 이상,
        # _UC_A가 더 강함(0.99). 강점 추천은 뒤집혀 _UC_A가 먼저, _UC_B가 뒤(메타 없음).
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_B, bkt=0.8, proxy=0.85),
                _diagnosis(code=_UC_A, bkt=0.99, proxy=0.99),
            ],
        )
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_A, _UC_B]
        assert out[1].concept_code == _UC_B
        assert out[1].name_ko is None
        assert out[1].domain is None
        assert out[1].review_status is None

    async def test_orphan_concept_no_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=None, bkt=0.8, proxy=0.9)])
        out = await recommend_strong_concepts(_fake_session(), _UID)
        assert len(out) == 1
        assert out[0].concept_code is None
        assert out[0].name_ko is None
        assert captured["calls"] == 0

    async def test_dedupes_code_in_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        captured = _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.8, proxy=0.9),
                _diagnosis(code=_UC_A, bkt=0.85, proxy=0.9),
            ],
        )
        await recommend_strong_concepts(_fake_session(), _UID)
        assert captured["calls"] == 1
        assert captured["concept_ids"] == [_UC_A]


# ──────────────────────────────────────────────────────────────────────────
# ⑤ redaction — 추천 스키마에 본문 필드(description·formal_definition) 부재
# ──────────────────────────────────────────────────────────────────────────
def test_recommendation_has_only_safe_fields() -> None:
    fields = set(StrongConceptRecommendation.model_fields)
    expected = {
        "concept_id",
        "concept_code",
        "concept_name",
        "bkt_mastery",
        "irt_mastery_proxy",
        "mastery",
        "agreement",
        "domain",
        "review_status",
        "name_ko",
    }
    assert fields == expected
    assert "description" not in fields
    assert "formal_definition" not in fields
    assert "intuitive_explanation" not in fields
