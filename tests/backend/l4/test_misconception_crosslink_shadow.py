"""L4 오개념 crosswalk shadow 단위테스트 — 게이트 공존 배선(비노출·비차단·never-break·프라이버시).

`observe_crosslink_shadow`(sync)·`observe_crosslink_shadow_async`(to_thread 래퍼)를 fake 엔진
주입 resolver로 호출해, kebab-id → M-id 해석 결과가 record 로거 JSON에 정확히 실리는지(coverage·
1:N)·never-break(resolve raise → None)·프라이버시(학생 식별자 0)를 라이브 PG 없이 검증한다
(`test_misconception_shadow.py`의 record_logger 필터 + `model_validate_json` 패턴 답습).
"""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType

import pytest

from whymath_backend.l1.misconception.crosslink_resolve import MisconceptionCrosslinkResolver
from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID
from whymath_backend.l4.misconception.crosslink_shadow import (
    MisconceptionCrosslinkShadowObservation,
    observe_crosslink_shadow,
    observe_crosslink_shadow_async,
)

# 정본 kebab 카탈로그의 실 id(kebab_valid=True 검증용 — 동적 취득).
_VALID_KEBAB = next(iter(CATALOG_BY_ID))

_RECORD_LOGGER = "whymath.l4.misconception.crosslink_shadow.record"


# ──────────────────────────────────────────────────────────────────────────
# fake sync 엔진(resolver 주입) — crosslink_resolve 테스트 패턴 미러
# ──────────────────────────────────────────────────────────────────────────
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
        return _FakeResult(self._engine.rows)


class _FakeEngine:
    def __init__(self, rows: list[object] | None = None) -> None:
        self.rows: list[object] = rows or []

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


def _resolver(rows: list[object] | None = None) -> MisconceptionCrosslinkResolver:
    return MisconceptionCrosslinkResolver(engine=_FakeEngine(rows))  # type: ignore[arg-type]


def _records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """crosslink shadow 구조화 record 로거 JSON 라인만(평문·다른 로거 노이즈 배제)."""
    return [r.getMessage() for r in caplog.records if r.name == _RECORD_LOGGER]


# ──────────────────────────────────────────────────────────────────────────
# ① 매핑 해석 → record JSON coverage
# ──────────────────────────────────────────────────────────────────────────
class TestObserveCrosslinkShadow:
    def test_maps_and_records(self, caplog: pytest.LogCaptureFixture) -> None:
        """매핑 존재 시 mis_ids·count·mapped를 record에 정확히 싣는다(confidence 내림차순)."""
        resolver = _resolver([_Row(_VALID_KEBAB, "M2", 0.7), _Row(_VALID_KEBAB, "M1", 0.9)])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=resolver)
        lines = _records(caplog)
        assert len(lines) == 1
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(lines[0])
        assert obs.kebab_id == _VALID_KEBAB
        assert obs.kebab_valid is True
        assert obs.mis_ids == ["M1", "M2"]  # confidence desc
        assert obs.mis_id_count == 2
        assert obs.mapped is True
        # canonical 신필드 충전 — 단독 최대 confidence 직접매핑(M1 0.9)이 선정된다.
        assert obs.canonical_mis_id == "M1"
        assert obs.canonical_ambiguous is False
        assert obs.direct_count == 2

    def test_empty_mapping_records_uncovered(self, caplog: pytest.LogCaptureFixture) -> None:
        """매핑 없음(빈 테이블) → mapped=False·count=0(coverage 0을 정직히 기록)."""
        resolver = _resolver(rows=[])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=resolver)
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.mis_ids == []
        assert obs.mis_id_count == 0
        assert obs.mapped is False
        assert obs.canonical_mis_id is None  # 링크 0 → canonical 미선정(정직)
        assert obs.direct_count == 0

    def test_canonical_tie_recorded_as_ambiguous(self, caplog: pytest.LogCaptureFixture) -> None:
        """직접매핑 최고 confidence 동률 → canonical 미선정 + canonical_ambiguous=True."""
        resolver = _resolver([_Row(_VALID_KEBAB, "M1", 0.8), _Row(_VALID_KEBAB, "M2", 0.8)])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=resolver)
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.canonical_mis_id is None
        assert obs.canonical_ambiguous is True
        assert obs.direct_count == 2

    def test_canonical_failure_defaults_but_still_records(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """resolve는 되나 resolve_canonical이 없는(구식) resolver → 기본값 충전·관측은 계속 적재."""

        class _LegacyResolver:
            """resolve만 있는 구식 duck-typed resolver(evidence_store 스파이 동형)."""

            def resolve(self, kebab_id: str, *, min_confidence: float | None = None) -> list[str]:
                return ["M1"]

        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=_LegacyResolver())  # type: ignore[arg-type]
        lines = _records(caplog)
        assert len(lines) == 1  # canonical 실패가 관측 적재를 막지 않는다(never-break)
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(lines[0])
        assert obs.mis_ids == ["M1"]  # 원시 매핑은 그대로
        assert obs.canonical_mis_id is None  # 기본값(정직 미선정과 동일 형태)
        assert obs.canonical_ambiguous is False
        assert obs.direct_count == 0

    def test_old_jsonl_without_canonical_fields_parses(self) -> None:
        """구 JSONL(신필드 부재) 하위호환 — 기본값으로 파싱된다(harvest 신구 혼재 전제)."""
        legacy = (
            '{"kebab_id": "k-old", "kebab_valid": true, "mis_ids": ["M1"], '
            '"mis_id_count": 1, "mapped": true, "observed_at": "2026-06-01T00:00:00Z"}'
        )
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(legacy)
        assert obs.kebab_id == "k-old"
        assert obs.canonical_mis_id is None
        assert obs.canonical_ambiguous is False
        assert obs.direct_count == 0

    def test_kebab_invalid_flagged(self, caplog: pytest.LogCaptureFixture) -> None:
        """카탈로그 밖 kebab → kebab_valid=False(게이트 우회 진입 감시용 신호)."""
        resolver = _resolver(rows=[])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow("not-a-real-kebab", resolver=resolver)
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.kebab_valid is False


# ──────────────────────────────────────────────────────────────────────────
# ② never-break(비차단) — resolve가 raise해도 본류 안 깸
# ──────────────────────────────────────────────────────────────────────────
class TestNeverBreak:
    def test_resolver_raises_returns_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """resolve(DB 미도달 등)가 raise → 예외 전파 0·반환 None(적재 본류 보호)."""

        class _BoomResolver:
            def resolve(self, *args: object, **kwargs: object) -> list[str]:
                raise RuntimeError("DB 미도달")

        # raise를 삼키고 정상 반환(예외 전파 0)하면 통과 — 반환은 항상 None(비노출 불변).
        with caplog.at_level(logging.WARNING, logger="whymath.l4.misconception.crosslink_shadow"):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=_BoomResolver())  # type: ignore[arg-type]
        # 침묵 실패 금지(CLAUDE.md) — 타입명은 남기고 예외 메시지·트레이스백은 남기지 않는다
        # (예외 메시지는 학생 발화·답안을 담을 수 있다 — 미성년자 PII).
        warnings = [
            r
            for r in caplog.records
            if r.name == "whymath.l4.misconception.crosslink_shadow"
            and r.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        assert "RuntimeError" in warnings[0].getMessage()
        assert "DB 미도달" not in warnings[0].getMessage()
        assert warnings[0].exc_info is None

    def test_async_wrapper_never_breaks(self) -> None:
        """async 래퍼도 resolve raise를 삼킨다(to_thread 방어선)."""

        class _BoomResolver:
            def resolve(self, *args: object, **kwargs: object) -> list[str]:
                raise RuntimeError("boom")

        out = asyncio.run(
            observe_crosslink_shadow_async(_VALID_KEBAB, resolver=_BoomResolver())  # type: ignore[arg-type]
        )
        assert out is None


# ──────────────────────────────────────────────────────────────────────────
# ③ async 래퍼 정상 경로(to_thread로 sync resolve 오프로드)
# ──────────────────────────────────────────────────────────────────────────
class TestAsyncWrapper:
    def test_async_maps_and_records(self, caplog: pytest.LogCaptureFixture) -> None:
        resolver = _resolver([_Row(_VALID_KEBAB, "M1", 0.9)])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            asyncio.run(observe_crosslink_shadow_async(_VALID_KEBAB, resolver=resolver))
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(_records(caplog)[0])
        assert obs.mis_ids == ["M1"]


# ──────────────────────────────────────────────────────────────────────────
# ④ 프라이버시 — 레코드에 학생 식별자·원문 0(카탈로그 식별자·개수만)
# ──────────────────────────────────────────────────────────────────────────
class TestPrivacy:
    def test_record_has_no_student_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """extra='forbid'·모델 필드 한정 — student_id/풀이 원문이 구조적으로 못 들어간다."""
        resolver = _resolver([_Row(_VALID_KEBAB, "M1", 0.9)])
        with caplog.at_level(logging.INFO, logger=_RECORD_LOGGER):
            observe_crosslink_shadow(_VALID_KEBAB, resolver=resolver)
        obs = MisconceptionCrosslinkShadowObservation.model_validate_json(_records(caplog)[0])
        keys = set(obs.model_dump().keys())
        expected = {
            "kebab_id",
            "kebab_valid",
            "mis_ids",
            "mis_id_count",
            "mapped",
            "canonical_mis_id",
            "canonical_ambiguous",
            "direct_count",
            "observed_at",
        }
        assert keys == expected
        assert "student_id" not in keys
