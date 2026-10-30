"""study 신호 조립 단위테스트 — grade_band 생산자 배선(PED-23 회수) + k_type 값 전달 동결.

정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §4 — "신호 추가는 생산자 먼저"
(04d §2.1). `_build_signals`가 `UserProfile.grade`(10~14 — `schema/user.py` 계약)를
`grade_to_band`로 파생해 `StudentSignals.grade_band`에 싣는 배선을 검증한다(필드만 만들고
항상 None이면 04d §2.1 위반 — 이 파일이 생산자 실배선의 증거다).

현행 `_build_signals`는 숙달 축을 `get_state()`(L2 조립기 — `mastery`/`domain_abilities` dict
사전 인덱싱)에서 O(1) lookup으로 읽는다(PED-05 리팩터 — 원 PED-06 테스트가 패치하던
`compute_concept_diagnoses` 직접 호출은 없어졌다). 그래서 이 테스트는 `study.get_state`를
대역으로 교체한다(모듈 네임스페이스 monkeypatch 관례 동형).

k_type 소스 스캔 동결: `str(objective.k_type)`은 str-mixin Enum이라 "KnowledgeType.CONCEPT"로
맹글링된다 — 원 PED-06 실측: ① 팩 조회(`get_pack`) 상시 미스 ② `evidence_event.k_type`
native enum 플러시가 LookupError로 실패(/study 500) ③ 카탈로그 필터 k_type 축 상시 공집합.
현행 수정 형태(`KnowledgeType(objective.k_type).value` — ORM 컬럼이 문자열이라 enum으로 감싼 뒤
`.value`)의 회귀를 소스 스캔으로 동결한다(`test_render_governance.py` 소스 스캔 선례 — 엔드포인트
hermetic 클라이언트 없이 가장 싼 동결).

hermetic: DB 0 — 세션 대역 + `get_state` monkeypatch(모듈 네임스페이스).
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from whymath_backend.api import study
from whymath_backend.db.models.user import UserProfile

_UID = uuid.uuid4()


@dataclass
class _FakeProfile:
    """`UserProfile` 최소 대역 — `_build_signals`는 `.grade`만 읽는다."""

    grade: int | None = 12


@dataclass
class _FakeState:
    """`LearnerState` 최소 대역 — `_build_signals`가 읽는 2 dict만(`mastery`·`domain_abilities`)."""

    mastery: dict[str, float] = field(default_factory=dict)
    domain_abilities: dict[str, float] = field(default_factory=dict)


class _FakeSession:
    """`session.get(UserProfile, pk)`만 흉내 — L2 상태는 `get_state` 대역이 공급한다."""

    def __init__(self, profile: _FakeProfile | None) -> None:
        self._profile = profile
        self.get_models: list[object] = []

    async def get(self, model: object, _pk: object) -> _FakeProfile | None:
        self.get_models.append(model)
        return self._profile if model is UserProfile else None


def _patch_state(monkeypatch: pytest.MonkeyPatch, state: _FakeState) -> None:
    """study 모듈 네임스페이스의 `get_state`를 대역으로 교체."""

    async def _fake(_session: Any, _user_id: uuid.UUID) -> _FakeState:
        return state

    monkeypatch.setattr(study, "get_state", _fake)


class TestBuildSignalsGradeBand:
    """grade_band 생산자 — UserProfile.grade → grade_to_band → StudentSignals 배선."""

    @pytest.mark.asyncio
    async def test_profile_grade_flows_into_grade_band(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_state(monkeypatch, _FakeState())
        session = _FakeSession(_FakeProfile(grade=12))  # 고3
        signals = await study._build_signals(session, _UID, "A1")  # type: ignore[arg-type]
        assert signals.grade_band == "고등"
        assert UserProfile in session.get_models  # 프로필을 실제로 조회했다(생산자 실배선).

    @pytest.mark.asyncio
    async def test_nsu_grade_maps_to_high_band(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # N수(13) — 고교 과정 재학습이므로 고등 밴드(schema/user.py 10~14 계약).
        _patch_state(monkeypatch, _FakeState())
        signals = await study._build_signals(_FakeSession(_FakeProfile(grade=13)), _UID, "A1")  # type: ignore[arg-type]
        assert signals.grade_band == "고등"

    @pytest.mark.asyncio
    async def test_missing_profile_leaves_band_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 프로필 미존재 — 없는 값을 기본치로 채우지 않는다(가짜 통과 금지·축 스킵).
        _patch_state(monkeypatch, _FakeState())
        signals = await study._build_signals(_FakeSession(None), _UID, "A1")  # type: ignore[arg-type]
        assert signals.grade_band is None

    @pytest.mark.asyncio
    async def test_null_grade_leaves_band_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_state(monkeypatch, _FakeState())
        signals = await study._build_signals(
            _FakeSession(_FakeProfile(grade=None)), _UID, "A1"  # type: ignore[arg-type]
        )
        assert signals.grade_band is None

    @pytest.mark.asyncio
    async def test_mastery_hit_path_also_carries_grade_band(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 숙달 진단이 있는 경로에서도 grade_band가 함께 실린다(단일 반환부 배선).
        _patch_state(monkeypatch, _FakeState(mastery={"A1": 0.9}))
        signals = await study._build_signals(_FakeSession(_FakeProfile(grade=8)), _UID, "A1")  # type: ignore[arg-type]
        assert signals.grade_band == "중학"
        assert signals.bkt_mastery == 0.9  # 기존 숙달 축 무변경.


class TestKTypeValueFrozen:
    """k_type 맹글링 회귀 동결 — `str(enum)`이 아니라 `.value`가 흐른다(모듈 docstring 사고)."""

    def test_source_has_no_str_mangled_k_type(self) -> None:
        source = inspect.getsource(study)
        assert "str(objective.k_type)" not in source, (
            "str(objective.k_type)은 'KnowledgeType.CONCEPT'로 맹글링된다 — "
            "팩 조회 미스·native enum 플러시 실패·카탈로그 필터 공집합(원 PED-06 실측). "
            "KnowledgeType(objective.k_type).value 형태를 쓰라."
        )
        assert "KnowledgeType(objective.k_type).value" in source

    def test_mangling_premise_still_holds(self) -> None:
        # 이 동결의 전제 실측 — str-mixin Enum의 str()은 값이 아니다(전제가 바뀌면 동결 재검토).
        from whymath_backend.schema.enums import KnowledgeType

        assert str(KnowledgeType.CONCEPT) != KnowledgeType.CONCEPT.value
        assert KnowledgeType.CONCEPT.value == "CONCEPT"
