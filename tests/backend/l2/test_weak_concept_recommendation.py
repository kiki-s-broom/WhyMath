"""L2 약개념 추천 — `weak_concept_recommendation` 단위테스트 (hermetic·PG 불요).

원자그래프 소비 슬2(S0-4d·runtime truth=원자). `recommend_weak_concepts`는 두 좌석을 *재사용*한다:
  ① `compute_concept_diagnoses`(L2·BKT/IRT 융합·약점 정렬) — 진단 입력
  ② `fetch_atom_axis_meta`(L1·원자 축 async 좌석) — code enrich(ARCH-13으로 sync 왕복 제거)

이 둘을 *패치*해 PG 없이 좌석 *배선*만 못 박는다(진단 로직·실 PG 조인은 각자 테스트 몫):
  - 약점 필터(임계 경계·신호 0건 제외)·정렬 보존·limit 상한
  - code enrich(name_ko·domain(←원자 subject_area)·review_status 부착)·축 밖 code graceful
    None·orphan(code 없음)
  - reviewed_only 게이팅(축 밖·검수 전 모두 제외하되 **사유는 분리 계상**)
  - 단일 호출·code 중복 제거(N+1 0)
  - enrich 대상이 원자 축임을 동결(`fetch_atom_axis_meta` 호출·domain 필드가 subject_area 값)
  - **제외 사유 표면화**(ARCH-13): `off_atom_axis`/`not_reviewed`/`not_weak` 계상 + 구조화 로그
  - redaction(추천 스키마에 본문 필드 부재)

이 좌석은 traversal이 아니라 학습자 mastery에서 후보가 나오므로 **축 필터는 없다**(축 밖도
reviewed_only가 아니면 노출) — 선수 좌석과 다른 점이며 의도된 차이다.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import whymath_backend.l2.weak_concept_recommendation as wcr_mod
from whymath_backend.l1.atom_graph.atom_node_projection import AtomNodeMeta
from whymath_backend.l2.concept_diagnosis import Agreement, ConceptDiagnosis
from whymath_backend.l2.weak_concept_recommendation import (
    WeakConceptRecommendation,
    recommend_weak_concepts,
    recommend_weak_concepts_detailed,
)

_UID = uuid.uuid4()
# 슬2 idmap UC 규약 키 예시(concept.code 공간·이제 atom_node code로 enrich·구 437 UC 유입 가능·격하)
_UC_A = "UC.alg.afunction.linear"
_UC_B = "UC.calc.alimit.epsilon-delta"
# 래퍼↔본체 동치 비교용 고정 concept_id(기본 진단은 매번 새 UUID를 뽑아 비교가 흐려진다).
_CID_A = uuid.uuid4()


def _diagnosis(
    *,
    code: str | None,
    name: str | None = "개념",
    bkt: float | None,
    proxy: float | None,
    agreement: Agreement = "agree",
    cid: uuid.UUID | None = None,
) -> ConceptDiagnosis:
    """진단 1건 흉내 — 약점 필터·enrich가 읽는 필드만 채운다(나머지 기본값)."""
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
    """session은 패치된 `compute_concept_diagnoses`가 무시하므로 더미면 충분."""
    return cast(AsyncSession, object())


def _patch_diagnoses(monkeypatch: pytest.MonkeyPatch, diagnoses: list[ConceptDiagnosis]) -> None:
    """`compute_concept_diagnoses`를 패치해 canned 진단(이미 약점 정렬됐다고 가정)을 돌려준다."""

    async def _fake(_session: AsyncSession, _user_id: uuid.UUID) -> list[ConceptDiagnosis]:
        return diagnoses

    monkeypatch.setattr(wcr_mod, "compute_concept_diagnoses", _fake)


def _patch_meta(
    monkeypatch: pytest.MonkeyPatch, meta: dict[str, AtomNodeMeta] | None = None
) -> dict[str, Any]:
    """`fetch_atom_axis_meta`(원자 축 async 좌석)를 패치해 enrich 메타를 제어·호출 인자를 기록.

    반환 captured["calls"]에 호출 횟수를, ["concept_ids"]에 마지막 호출 code를 담는다 — 좌석이
    약점 후보 code를 *단일 호출*(N+1 0)로 넘기는지 관찰. meta 미지정이면 빈 dict(=전량 축 밖).
    ARCH-13 이후 이 좌석은 **호출 세션의 async 엔진**을 쓴다(sync 왕복 없음) — 그래서 fake도
    async이며 첫 인자로 세션을 받는다.
    """
    captured: dict[str, Any] = {"calls": 0}
    resolved_meta = meta if meta is not None else {}

    async def _fake_fetch(
        session: AsyncSession, concept_ids: Sequence[str]
    ) -> dict[str, AtomNodeMeta]:
        captured["calls"] += 1
        captured["concept_ids"] = list(concept_ids)
        captured["session"] = session
        return resolved_meta

    monkeypatch.setattr(wcr_mod, "fetch_atom_axis_meta", _fake_fetch)
    return captured


# ──────────────────────────────────────────────────────────────────────────
# ① 약점 필터 — 최저 신호 < 임계만·신호 0건 제외·임계 경계
# ──────────────────────────────────────────────────────────────────────────
class TestWeaknessFilter:
    async def test_keeps_below_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.3, proxy=0.5),  # 최저 0.3 < 0.7 → 약점
                _diagnosis(code=_UC_B, bkt=0.9, proxy=0.95),  # 최저 0.9 ≥ 0.7 → 제외
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_A]
        assert out[0].weakness == 0.3  # 두 신호 중 최저

    async def test_threshold_boundary_excludes_equal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 경계: weakness == threshold면 *미만*이 아니므로 제외(< 비교).
        _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.7, proxy=0.8)])
        out = await recommend_weak_concepts(_fake_session(), _UID, mastery_threshold=0.7)
        assert out == []

    async def test_no_signal_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 두 신호 모두 None이면 추천 근거 없음 → 제외(insufficient도 신호 0건은 빠진다).
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=None, proxy=None, agreement="insufficient"),
                _diagnosis(code=_UC_B, bkt=0.2, proxy=None, agreement="insufficient"),
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID)
        # 신호 1건(bkt=0.2)인 _UC_B는 약점으로 남고, 신호 0건 _UC_A는 빠진다.
        assert [r.concept_code for r in out] == [_UC_B]
        assert out[0].weakness == 0.2

    async def test_single_signal_used_as_weakness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 한쪽 신호만 있으면 그 값이 weakness(min of 1).
        _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=None, proxy=0.4)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert out[0].weakness == 0.4

    async def test_empty_diagnoses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert out == []
        # 약점 후보 0건이면 메타 조회도 생략(early return).
        assert captured["calls"] == 0


# ──────────────────────────────────────────────────────────────────────────
# ⓐ diagnoses 스냅샷 재사용 (PR #1018 Codex 리뷰 — 동시 mastery 갱신 시 스냅샷 불일치 방지)
# ──────────────────────────────────────────────────────────────────────────
class TestDiagnosesSnapshotReuse:
    async def test_passed_diagnoses_skips_internal_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`diagnoses=`를 넘기면 `compute_concept_diagnoses`를 아예 호출하지 않는다.

        단순히 인자를 받아 두고 무시하는 것이 아니라 *실제로 재사용*함을 못 박는다 — 그래야
        호출자가 이미 구한 스냅샷과 다른 시점의 데이터를 다시 조회해 불일치가 생기는 것을
        막는다는 주장이 성립한다.
        """
        calls = {"n": 0}

        async def _boom(_session: AsyncSession, _user_id: uuid.UUID) -> list[ConceptDiagnosis]:
            calls["n"] += 1
            raise AssertionError("diagnoses가 주어졌는데 내부에서 재조회했다")

        monkeypatch.setattr(wcr_mod, "compute_concept_diagnoses", _boom)
        _patch_meta(monkeypatch)
        given = [_diagnosis(code=_UC_A, bkt=0.2, proxy=0.3)]
        out = await recommend_weak_concepts(_fake_session(), _UID, diagnoses=given)
        assert calls["n"] == 0
        assert [r.concept_code for r in out] == [_UC_A]

    async def test_none_diagnoses_still_fetches_internally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 기본값(None)은 기존 계약 그대로 — 하위호환.
        _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.2, proxy=0.3)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_A]


# ──────────────────────────────────────────────────────────────────────────
# ② 정렬 보존 — 진단의 약점 우선 순서를 그대로 유지
# ──────────────────────────────────────────────────────────────────────────
class TestSortPreserved:
    async def test_preserves_diagnosis_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        # compute_concept_diagnoses가 약점 먼저 정렬해 준 순서(_UC_A weak → _UC_B less weak).
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),
                _diagnosis(code=_UC_B, bkt=0.5, proxy=0.6),
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_A, _UC_B]


# ──────────────────────────────────────────────────────────────────────────
# ③ limit 상한 — 약점 정렬 보존하며 상위 N
# ──────────────────────────────────────────────────────────────────────────
class TestLimit:
    async def test_limit_caps_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_meta(monkeypatch)
        _patch_diagnoses(
            monkeypatch,
            [_diagnosis(code=f"UC.x.y.{i}", bkt=0.1 + i * 0.01, proxy=0.2) for i in range(5)],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID, limit=2)
        assert len(out) == 2
        assert [r.concept_code for r in out] == ["UC.x.y.0", "UC.x.y.1"]  # 상위 2(정렬 보존)


# ──────────────────────────────────────────────────────────────────────────
# ④ enrich — atom_node 메타 부착·미적재 code None·orphan(code 없음)·단일 호출
# ──────────────────────────────────────────────────────────────────────────
class TestEnrichment:
    async def test_attaches_node_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {
            _UC_A: AtomNodeMeta(
                name_ko="일차함수", subject_area="[중]함수", review_status="reviewed"
            )
        }
        captured = _patch_meta(monkeypatch, meta)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.2, proxy=0.3)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert out[0].name_ko == "일차함수"
        assert out[0].domain == "[중]함수"
        assert out[0].review_status == "reviewed"
        # 약점 후보 UC를 *단일 호출*로 넘긴다(N+1 0).
        assert captured["calls"] == 1
        assert captured["concept_ids"] == [_UC_A]

    async def test_missing_meta_is_none_graceful(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # atom_node에 _UC_B 메타가 없으면(적재 누락·구 437 미스) enrich 필드 None(추천은 유지).
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.2, proxy=0.3),
                _diagnosis(code=_UC_B, bkt=0.25, proxy=0.3),
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert out[1].concept_code == _UC_B
        assert out[1].name_ko is None
        assert out[1].domain is None
        assert out[1].review_status is None

    async def test_orphan_concept_no_uc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # concept_code(UC) None인 orphan은 enrich 안 함(meta 조회 UC 목록에서도 제외).
        captured = _patch_meta(monkeypatch)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=None, bkt=0.1, proxy=0.2)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert len(out) == 1
        assert out[0].concept_code is None
        assert out[0].name_ko is None
        # UC가 하나도 없으면 메타 조회 생략(빈 UC 목록 → 호출 0).
        assert captured["calls"] == 0

    async def test_dedupes_uc_in_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 같은 UC 중복 후보는 메타 조회 UC 목록에서 중복 제거(IN 1회·중복 키 0).
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        captured = _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),
                _diagnosis(code=_UC_A, bkt=0.15, proxy=0.2),
            ],
        )
        await recommend_weak_concepts(_fake_session(), _UID)
        assert captured["calls"] == 1
        assert captured["concept_ids"] == [_UC_A]  # 중복 제거


# ──────────────────────────────────────────────────────────────────────────
# ⑤ reviewed_only 게이팅 — reviewed만·메타 없으면 제외·기본 recall
# ──────────────────────────────────────────────────────────────────────────
class TestReviewedOnlyGating:
    async def test_gates_pending(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {
            _UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed"),
            _UC_B: AtomNodeMeta(name_ko="B", subject_area="d", review_status="pending"),
        }
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),
                _diagnosis(code=_UC_B, bkt=0.15, proxy=0.2),
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID, reviewed_only=True)
        assert [r.concept_code for r in out] == [_UC_A]  # pending 제외·정렬 유지

    async def test_gates_off_axis_codes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 원자 축 밖(또는 orphan)이라 reviewed 확인 불가인 UC는 gated 모드에서 보수적 제외(정직).
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),
                _diagnosis(code=_UC_B, bkt=0.15, proxy=0.2),  # 메타 없음
                _diagnosis(code=None, bkt=0.05, proxy=0.1),  # orphan(UC 없음)
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID, reviewed_only=True)
        assert [r.concept_code for r in out] == [_UC_A]  # 메타 없음·orphan 모두 제외

    async def test_default_keeps_all_recall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="pending")}
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),  # pending
                _diagnosis(code=_UC_B, bkt=0.15, proxy=0.2),  # 메타 없음
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert [r.concept_code for r in out] == [_UC_A, _UC_B]  # 기본 False·둘 다 노출

    async def test_gating_then_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 게이팅 후 limit — reviewed만 카운트해 상위 N(게이팅이 limit보다 먼저).
        meta = {
            _UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed"),
            _UC_B: AtomNodeMeta(name_ko="B", subject_area="d", review_status="reviewed"),
        }
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code="UC.p.q.0", bkt=0.05, proxy=0.1),  # 메타 없음 → gated
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),  # reviewed
                _diagnosis(code=_UC_B, bkt=0.15, proxy=0.2),  # reviewed
            ],
        )
        out = await recommend_weak_concepts(_fake_session(), _UID, limit=1, reviewed_only=True)
        # gated UC 건너뛰고 reviewed 첫 1개(_UC_A)만.
        assert [r.concept_code for r in out] == [_UC_A]


# ──────────────────────────────────────────────────────────────────────────
# ⑥ redaction — 추천 스키마에 본문 필드(description·formal_definition) 부재
# ──────────────────────────────────────────────────────────────────────────
def test_recommendation_has_only_safe_fields() -> None:
    fields = set(WeakConceptRecommendation.model_fields)
    expected = {
        "concept_id",
        "concept_code",
        "concept_name",
        "bkt_mastery",
        "irt_mastery_proxy",
        "weakness",
        "agreement",
        "domain",
        "review_status",
        "name_ko",
    }
    assert fields == expected
    assert "description" not in fields
    assert "formal_definition" not in fields
    assert "intuitive_explanation" not in fields


# ──────────────────────────────────────────────────────────────────────────
# ⑦ 제외 사유 표면화 (ARCH-13) — 축 밖·검수 전·비약점이 섞이지 않고 계상·로그된다
# ──────────────────────────────────────────────────────────────────────────
class TestExclusionAccounting:
    async def test_separates_off_axis_from_not_reviewed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 같은 "제외"라도 사유가 다르다 — 뭉뚱그리면 무엇이 문제인지(적재 누락인지 검수 지연인지)
        # 알 수 없다. 예전 코드는 `node is None or review != reviewed`를 한 줄로 삼켰다.
        _patch_meta(
            monkeypatch,
            {
                _UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed"),
                _UC_B: AtomNodeMeta(name_ko="B", subject_area="d", review_status="pending"),
            },
        )
        _patch_diagnoses(
            monkeypatch,
            [
                _diagnosis(code=_UC_A, bkt=0.1, proxy=0.2),  # reviewed → 유지
                _diagnosis(code=_UC_B, bkt=0.15, proxy=0.2),  # pending → not_reviewed
                _diagnosis(code="UC-LEGACY-437", bkt=0.2, proxy=0.3),  # 축 밖 → off_atom_axis
                _diagnosis(code="UC.strong", bkt=0.9, proxy=0.95),  # 안 막힘 → not_weak
            ],
        )
        result = await recommend_weak_concepts_detailed(_fake_session(), _UID, reviewed_only=True)
        assert [r.concept_code for r in result.recommendations] == [_UC_A]
        assert result.exclusions.off_atom_axis == 1
        assert result.exclusions.not_reviewed == 1
        assert result.exclusions.not_weak == 1

    async def test_exclusion_accounting_is_discriminative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**변별력** — 메타 유무만 바꾸면 `off_atom_axis` 계상과 노출 여부가 실제로 뒤집힌다."""
        diagnoses = [_diagnosis(code=_UC_A, bkt=0.1, proxy=0.2)]

        _patch_meta(monkeypatch, {})  # 축 밖
        _patch_diagnoses(monkeypatch, diagnoses)
        off = await recommend_weak_concepts_detailed(_fake_session(), _UID, reviewed_only=True)

        _patch_meta(
            monkeypatch,
            {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")},
        )
        _patch_diagnoses(monkeypatch, diagnoses)
        on = await recommend_weak_concepts_detailed(_fake_session(), _UID, reviewed_only=True)

        assert off.recommendations == [] and off.exclusions.off_atom_axis == 1
        assert len(on.recommendations) == 1 and on.exclusions.off_atom_axis == 0

    async def test_logs_counts_without_identifiers(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 제외가 있으면 구조화 로그 1줄 — 카운트만 싣고 code·user_id는 싣지 않는다(개인정보).
        _patch_meta(monkeypatch, {})
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.1, proxy=0.2)])
        with caplog.at_level(logging.INFO, logger="whymath.l2.weak_concept_recommendation"):
            await recommend_weak_concepts(_fake_session(), _UID, reviewed_only=True)
        messages = [r.getMessage() for r in caplog.records]
        assert any("off_atom_axis=1" in m for m in messages)
        assert not any(_UC_A in m or str(_UID) in m for m in messages)

    async def test_no_log_when_nothing_excluded(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 정상 경로는 침묵(소음 방지) — 위 테스트의 변별력 짝.
        _patch_meta(
            monkeypatch,
            {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")},
        )
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.1, proxy=0.2)])
        with caplog.at_level(logging.INFO, logger="whymath.l2.weak_concept_recommendation"):
            out = await recommend_weak_concepts(_fake_session(), _UID, reviewed_only=True)
        assert len(out) == 1
        assert caplog.records == []

    async def test_thin_wrapper_matches_detailed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 기존 계약(list 반환)은 `_detailed`의 recommendations와 동치 — 로직 분기 0.
        meta = {_UC_A: AtomNodeMeta(name_ko="A", subject_area="d", review_status="reviewed")}
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, cid=_CID_A, bkt=0.1, proxy=0.2)])
        thin = await recommend_weak_concepts(_fake_session(), _UID)
        _patch_meta(monkeypatch, meta)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, cid=_CID_A, bkt=0.1, proxy=0.2)])
        detailed = await recommend_weak_concepts_detailed(_fake_session(), _UID)
        assert thin == detailed.recommendations


# ──────────────────────────────────────────────────────────────────────────
# ⑧ 원자 축 동결 — enrich 대상이 원자 축(fetch_atom_axis_meta)이며 domain←subject_area (S0-4d)
# ──────────────────────────────────────────────────────────────────────────
class TestAtomAxisFrozen:
    async def test_enrich_targets_atom_node_meta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # S0-4d 동결: enrich는 원자 축 좌석(`fetch_atom_axis_meta`·atom_node 조회)을 통과하고,
        # 결과 `domain` 필드는 원자 `subject_area` 값을 담는다(값 소스 교체·필드명 유지). fake는
        # subject_area 라벨을 명시적으로 다르게 줘 domain이 그 값을 실는지 못 박는다.
        # ARCH-13은 이 좌석이 *어느 엔진에서 오는가*만 바꿨다(sync 왕복 → 호출 세션).
        captured = _patch_meta(
            monkeypatch,
            {
                _UC_A: AtomNodeMeta(
                    name_ko="극한", subject_area="[고]미적분", review_status="reviewed"
                )
            },
        )
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.2, proxy=0.3)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        # atom_node 좌석이 정확히 한 번, 약점 code로 호출됐다(구 fetch_node_meta 아님).
        assert captured["calls"] == 1
        assert captured["concept_ids"] == [_UC_A]
        # domain(계약 필드명 유지) 값이 원자 subject_area를 담는다.
        assert out[0].domain == "[고]미적분"
        assert out[0].name_ko == "극한"

    async def test_off_axis_is_none_graceful(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 구 437 UC가 concept_code로 흘러도(=원자 축 밖) enrich None graceful(격하 취지).
        # 이 좌석은 학습자 자신의 mastery가 후보라 축으로 걸러내지 않는다 — 선수 좌석과의 차이.
        _patch_meta(monkeypatch, {})  # atom_node에 아무 code도 없음(전량 축 밖)
        _patch_diagnoses(monkeypatch, [_diagnosis(code=_UC_A, bkt=0.2, proxy=0.3)])
        out = await recommend_weak_concepts(_fake_session(), _UID)
        assert out[0].concept_code == _UC_A  # 추천 자체는 유지(rekey 0)
        assert out[0].domain is None
        assert out[0].name_ko is None
        assert out[0].review_status is None
