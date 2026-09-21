"""PED-23 카탈로그 소비 배선 테스트 — select 후보 필터·전략 카드·gate 카탈로그 부재 동결.

격리 브랜치의 원 구현(PED-06)을 현행 main 위에 재적용한 회수분이다 — 원 테스트를 현행 API에
맞게 이식했다(동일 변별력 유지).

정본: `docs/architecture/04e_pedagogy_strategy_catalog.md` §4(후보 필터)·§3.2(소비처 지정표).
검증 축(acceptance 3항목과 1:1):

  ① **후보 필터는 좁힘만** — 학년·난이도·k_type 축별 좁힘의 변별력, 공집합/후보 소진 시 규칙표
     원판정 폴백(+reason_code 로그 — 조용한 실패 아님), None 신호 축 스킵, 플래그 OFF 비트동일
     (카탈로그 미조회까지 봄베로 확인), `select()` 출력 ⊆ `registered_strategies()` 거버넌스.
  ② **전략 카드 계층** — 무카드 바이트 동일(`attach_strategy_card`), research_basis 요약 1줄만,
     supply() 생성 폴백 배선(플래그 OFF 미조회·ON 주입·조회 실패 시 예외 타입명 로그 후 진행·
     렌더 경로 미조회).
  ③ **gate() 카탈로그 부재 동결** — 정적(co_names·소스·시그니처)+런타임(레지스트리 봄베) 이중
     동결. 카탈로그(효과 축)가 게이트(허용 축)를 우회하는 회귀를 차단한다(04e §4 불변식 ②).

hermetic: 실 코퍼스는 저장소 YAML(네트워크·DB 0). 플래그 토글은 env+`get_settings.cache_clear()`
(`test_pedagogy_pack_assembler.py` 관례).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import product
from typing import Any

import pytest

from whymath_backend.composition import (
    default_assessment_answer_verifier,
    default_expression_seal,
)
from whymath_backend.config import get_settings
from whymath_backend.l3.models import RoutingRequest
from whymath_backend.l3.render.registry import registered_strategies
from whymath_backend.l4 import content_supply
from whymath_backend.l4.content_supply import supply
from whymath_backend.l4.models import PolyaStage
from whymath_backend.l4.pedagogy import runtime_selector, strategy_registry
from whymath_backend.l4.pedagogy.prompt_assembler import (
    attach_strategy_card,
    render_strategy_card,
)
from whymath_backend.l4.pedagogy.runtime_selector import (
    REASON_CATALOG_FILTER_EMPTY,
    REASON_CATALOG_FILTER_EXHAUSTED,
    REASON_CATALOG_UNAVAILABLE,
    REASON_HINT_NOT_ESCALATED,
    StudentSignals,
    decide,
    gate,
    grade_to_band,
    narrow_candidates,
    select,
)
from whymath_backend.l4.pedagogy.strategy_registry import get_pedagogy_strategies
from whymath_backend.schema.enums import PedagogyStrategy
from whymath_backend.schema.pedagogy_strategy import GRADE_BAND_VOCAB, PedagogyStrategyCard

_SELECTOR_LOGGER = "whymath.l4.runtime_selector"
_SUPPLY_LOGGER = "whymath.l4.content_supply"


@pytest.fixture(autouse=True)
def _restore_settings_cache() -> Iterator[None]:
    """각 테스트 후 설정 캐시 원복 — env 토글이 다른 테스트로 새지 않게(팩 조립기 테스트 관례)."""
    yield
    get_settings.cache_clear()


def _filter_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """카탈로그 후보 필터 플래그 ON — env+cache_clear."""
    monkeypatch.setenv("WHYMATH_PEDAGOGY_CATALOG_FILTER_ENABLED", "true")
    get_settings.cache_clear()


def _card_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """전략 카드 플래그 ON — env+cache_clear."""
    monkeypatch.setenv("WHYMATH_PEDAGOGY_STRATEGY_CARD_ENABLED", "true")
    get_settings.cache_clear()


def _card(
    strategy: PedagogyStrategy,
    *,
    bands: tuple[str, ...] = ("초등", "중학", "고등", "대학"),
    diffs: tuple[str, ...] = ("상", "중", "하"),
    k_types: tuple[str, ...] = ("CONCEPT",),
    research_basis: tuple[str, ...] = ("테스트 근거 (2026)",),
) -> PedagogyStrategyCard:
    """합성 카드 — 축별 변별력 테스트용(schema 불변식을 통과하는 최소 유효 카드)."""
    return PedagogyStrategyCard(
        strategy=strategy,
        name_ko="테스트 전략",
        description="축별 필터 변별력 테스트용 카드다.",
        research_basis=list(research_basis),
        target_grade_bands=list(bands),
        difficulty_range=list(diffs),
        target_k_types=list(k_types),  # type: ignore[arg-type]  # use_enum_values — 값 문자열 수용
        usage_notes="테스트 전용 서술.",
    )


# ──────────────────────────────────────────────────────────────────────────
# 학년 → 밴드 순수 변환 (생산자 UserProfile.grade — schema/user.py 10~14 계약 실측)
# ──────────────────────────────────────────────────────────────────────────
class TestGradeToBand:
    def test_boundaries(self) -> None:
        # 초6/중3/고3/재수 경계 — K-12 사다리(10=고1 실측 계약에서 역산).
        assert grade_to_band(1) == "초등"
        assert grade_to_band(6) == "초등"  # 초6
        assert grade_to_band(7) == "중학"
        assert grade_to_band(9) == "중학"  # 중3
        assert grade_to_band(10) == "고등"  # 고1
        assert grade_to_band(12) == "고등"  # 고3
        assert grade_to_band(13) == "고등"  # N수1(재수) — 고교 과정 재학습
        assert grade_to_band(14) == "고등"  # N수2

    def test_unknown_values_are_none_not_guessed(self) -> None:
        # 미상·미정의 값은 None — 추측 매핑 금지(필터 축 조용히 스킵).
        assert grade_to_band(None) is None
        assert grade_to_band(0) is None
        assert grade_to_band(-3) is None
        assert grade_to_band(15) is None

    def test_outputs_are_vocab_subset_and_never_university(self) -> None:
        # 산출은 항상 GRADE_BAND_VOCAB 부분집합이며, "대학"은 생산자 부재로 영원히 안 나온다
        # (정직한 공백 — grade 정수 계약에 대학 인코딩 없음).
        outputs = {grade_to_band(g) for g in range(1, 15)}
        assert outputs <= GRADE_BAND_VOCAB
        assert "대학" not in outputs


# ──────────────────────────────────────────────────────────────────────────
# narrow_candidates — 좁힘만(순수 함수·합성 카드 변별력)
# ──────────────────────────────────────────────────────────────────────────
class TestNarrowCandidates:
    def test_result_is_always_subset(self) -> None:
        # 불변식 ①의 전반부 — 어떤 축 조합에서도 좁힘만 한다(추가 0).
        cands = registered_strategies()
        cards = get_pedagogy_strategies()
        for band, diff, kt in product(
            (None, "초등", "고등"), (None, "상", "하"), (None, "CONCEPT", "REPRESENT")
        ):
            narrowed = narrow_candidates(cands, cards, grade_band=band, difficulty=diff, k_type=kt)
            assert narrowed <= cands

    def test_no_axes_returns_candidates_unchanged(self) -> None:
        cands = registered_strategies()
        assert narrow_candidates(cands, get_pedagogy_strategies()) == cands

    def test_grade_axis_narrows_with_synthetic_card(self) -> None:
        # 실 코퍼스는 전 카드가 4밴드 전부라 학년 축이 안 좁혀진다 — 합성 카드로 축 변별력 확인.
        cands = frozenset({PedagogyStrategy.WORKED_EXAMPLE, PedagogyStrategy.SOCRATIC})
        cards = {
            "WORKED_EXAMPLE": _card(PedagogyStrategy.WORKED_EXAMPLE, bands=("초등",)),
            "SOCRATIC": _card(PedagogyStrategy.SOCRATIC, bands=("초등", "고등")),
        }
        narrowed = narrow_candidates(cands, cards, grade_band="고등")
        assert narrowed == frozenset({PedagogyStrategy.SOCRATIC})
        # 같은 입력에서 밴드만 바꾸면 결과가 뒤집힌다(변별력 — 위장 방지).
        assert narrow_candidates(cands, cards, grade_band="초등") == cands

    def test_difficulty_axis_narrows_with_real_corpus(self) -> None:
        # 실 코퍼스: WORKED_EXAMPLE·PROBLEM_BASED는 difficulty_range=[상,중] — '하'에서 제외.
        narrowed = narrow_candidates(
            registered_strategies(), get_pedagogy_strategies(), difficulty="하"
        )
        assert PedagogyStrategy.WORKED_EXAMPLE not in narrowed
        assert PedagogyStrategy.PROBLEM_BASED not in narrowed
        assert PedagogyStrategy.SOCRATIC in narrowed

    def test_k_type_axis_narrows_with_real_corpus(self) -> None:
        # 실 코퍼스: WORKED_EXAMPLE 카드는 target_k_types=[PROCEDURE] — CONCEPT에서 제외.
        narrowed = narrow_candidates(
            registered_strategies(), get_pedagogy_strategies(), k_type="CONCEPT"
        )
        assert PedagogyStrategy.WORKED_EXAMPLE not in narrowed
        assert PedagogyStrategy.SOCRATIC in narrowed

    def test_missing_card_is_kept_not_excluded(self) -> None:
        # 카탈로그 공백은 배제 근거가 아니다(적합성 미상 ≠ 부적합 — 선택 불능 방지).
        cands = registered_strategies()
        narrowed = narrow_candidates(cands, {}, grade_band="고등", k_type="CONCEPT")
        assert narrowed == cands

    def test_empty_result_is_possible_with_real_corpus(self) -> None:
        # REPRESENT를 겨냥하는 카드는 VISUALIZATION뿐인데 어댑터 미구현(비후보) — 공집합 실례.
        narrowed = narrow_candidates(
            registered_strategies(), get_pedagogy_strategies(), k_type="REPRESENT"
        )
        assert narrowed == frozenset()


# ──────────────────────────────────────────────────────────────────────────
# select 필터 — 플래그 OFF 비트동일(+카탈로그 미조회)
# ──────────────────────────────────────────────────────────────────────────
class TestSelectFilterFlagOff:
    def test_off_is_default_and_ignores_axes(self) -> None:
        # 기본(OFF)에서는 축을 줘도 규칙표 v1 원판정 그대로 — 기존 경로 비트동일.
        assert get_settings().pedagogy_catalog_filter_enabled is False
        stuck = StudentSignals(turn_count=5)
        assert select(stuck, k_type="CONCEPT") is PedagogyStrategy.WORKED_EXAMPLE

    def test_off_never_touches_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # OFF면 카탈로그를 조회조차 하지 않는다(미조회 계약) — 봄베가 터지면 위반.
        def _bomb() -> dict[str, PedagogyStrategyCard]:
            raise AssertionError("플래그 OFF에서 카탈로그가 조회됨 — 미조회 계약 위반")

        monkeypatch.setattr(runtime_selector, "get_pedagogy_strategies", _bomb)
        signals = StudentSignals(turn_count=5, grade_band="고등")
        assert select(signals, k_type="CONCEPT", difficulty="하") is (
            PedagogyStrategy.WORKED_EXAMPLE
        )


# ──────────────────────────────────────────────────────────────────────────
# select 필터 — 플래그 ON(좁힘·폴백·reason_code·거버넌스)
# ──────────────────────────────────────────────────────────────────────────
class TestSelectFilterFlagOn:
    def test_k_type_narrowing_changes_r1_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # CONCEPT 문항의 막힌 학생 — WE가 후보에서 빠져 규칙표가 R5(SOCRATIC)로 흐른다.
        _filter_on(monkeypatch)
        stuck = StudentSignals(turn_count=5)
        assert select(stuck, k_type="CONCEPT") is PedagogyStrategy.SOCRATIC
        # PROCEDURE 문항이면 WE가 후보에 남아 R1 그대로(축 변별력 — 같은 신호·다른 축).
        assert select(stuck, k_type="PROCEDURE") is PedagogyStrategy.WORKED_EXAMPLE

    def test_difficulty_narrowing_changes_r1_outcome(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _filter_on(monkeypatch)
        stuck = StudentSignals(turn_count=5)
        assert select(stuck, difficulty="하") is PedagogyStrategy.SOCRATIC  # WE는 [상,중]
        assert select(stuck, difficulty="상") is PedagogyStrategy.WORKED_EXAMPLE

    def test_grade_band_signal_narrows_via_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 실 코퍼스는 학년 축이 전 카드 4밴드라 안 좁혀지므로 합성 레지스트리로 축 배선을 확인.
        _filter_on(monkeypatch)
        synthetic = {
            "WORKED_EXAMPLE": _card(PedagogyStrategy.WORKED_EXAMPLE, bands=("초등",)),
        }
        monkeypatch.setattr(runtime_selector, "get_pedagogy_strategies", lambda: synthetic)
        stuck_high = StudentSignals(turn_count=5, grade_band="고등")
        assert select(stuck_high) is PedagogyStrategy.SOCRATIC  # WE 초등 전용 → R5
        stuck_elem = StudentSignals(turn_count=5, grade_band="초등")
        assert select(stuck_elem) is PedagogyStrategy.WORKED_EXAMPLE  # 밴드 적합 → R1

    def test_none_signals_skip_filter_without_catalog_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 필터 축 신호가 전무하면(플래그 ON이어도) 카탈로그 미조회·원판정(축 스킵 계약).
        _filter_on(monkeypatch)

        def _bomb() -> dict[str, PedagogyStrategyCard]:
            raise AssertionError("축 신호 전무인데 카탈로그가 조회됨")

        monkeypatch.setattr(runtime_selector, "get_pedagogy_strategies", _bomb)
        assert select(StudentSignals(turn_count=5)) is PedagogyStrategy.WORKED_EXAMPLE

    def test_empty_narrowing_falls_back_with_reason(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 공집합(실 코퍼스 REPRESENT — VISUALIZATION 어댑터 미구현) → 원판정 폴백 + reason 기록.
        _filter_on(monkeypatch)
        with caplog.at_level(logging.INFO, logger=_SELECTOR_LOGGER):
            verdict = select(StudentSignals(), k_type="REPRESENT")
        assert verdict is PedagogyStrategy.SOCRATIC  # 원판정(R5)
        assert any(REASON_CATALOG_FILTER_EMPTY in r.getMessage() for r in caplog.records)

    def test_exhausted_rule_table_falls_back_with_reason(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # PROCEDURE 좁힘 후보 {DIRECT, WE}에 기본 신호 — 규칙표가 후보 소진 → 원판정 폴백.
        _filter_on(monkeypatch)
        with caplog.at_level(logging.INFO, logger=_SELECTOR_LOGGER):
            verdict = select(StudentSignals(), k_type="PROCEDURE")
        assert verdict is PedagogyStrategy.SOCRATIC  # 원판정(R5)
        assert any(REASON_CATALOG_FILTER_EXHAUSTED in r.getMessage() for r in caplog.records)

    def test_catalog_load_failure_falls_back_with_typed_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 카탈로그 적재 실패 — 필터 생략·원판정 + 예외 *타입명* 로그(침묵 실패 금지).
        _filter_on(monkeypatch)

        def _broken() -> dict[str, PedagogyStrategyCard]:
            raise OSError("코퍼스 디렉터리 접근 실패 재현")

        monkeypatch.setattr(runtime_selector, "get_pedagogy_strategies", _broken)
        with caplog.at_level(logging.WARNING, logger=_SELECTOR_LOGGER):
            verdict = select(StudentSignals(turn_count=5), k_type="CONCEPT")
        assert verdict is PedagogyStrategy.WORKED_EXAMPLE  # 원판정
        messages = [r.getMessage() for r in caplog.records]
        assert any(REASON_CATALOG_UNAVAILABLE in m and "OSError" in m for m in messages)

    def test_output_stays_within_registered_strategies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 불변식 ③ — 필터 ON에서도 select() 출력 ⊆ registered_strategies() (신호×축 그리드).
        _filter_on(monkeypatch)
        renderable = registered_strategies()
        signal_cases = [
            StudentSignals(),
            StudentSignals(turn_count=5),
            StudentSignals(misconception_ids=("m1",)),
            StudentSignals(last_attempt_correct=False, mastery_level="초보"),
            StudentSignals(mastery_level="숙달"),
            StudentSignals(turn_count=5, grade_band="고등"),
        ]
        axis_cases = [
            (None, None),
            ("CONCEPT", None),
            ("PROCEDURE", "상"),
            ("PROCEDURE", "하"),
            ("REPRESENT", None),  # 공집합 폴백 경로
            ("MODELING", "하"),
        ]
        for signals, (kt, diff) in product(signal_cases, axis_cases):
            assert select(signals, k_type=kt, difficulty=diff) in renderable


# ──────────────────────────────────────────────────────────────────────────
# decide 스레딩 — 필터는 게이트를 약화하지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestDecideThreading:
    def test_concept_stuck_student_gets_socratic_without_demotion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 필터가 WE를 사전에 제거 — 게이트 강등 없이도 냉담 완전예제가 없다(선택 단계 해소).
        _filter_on(monkeypatch)
        signals = StudentSignals(polya_stage=PolyaStage.UNDERSTAND, turn_count=5, hint_level=1)
        result = decide(signals, k_type="CONCEPT")
        assert result.strategy is PedagogyStrategy.SOCRATIC
        assert result.allowed is True  # 강등이 아니라 애초에 적합 전략을 골랐다.

    def test_filter_does_not_weaken_gate_axis_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # PROCEDURE에서는 WE가 후보에 남는다 — 막힘+힌트 미상승이면 게이트 축②가 여전히 강등.
        _filter_on(monkeypatch)
        signals = StudentSignals(polya_stage=PolyaStage.EXECUTE, turn_count=5, hint_level=1)
        result = decide(signals, k_type="PROCEDURE")
        assert result.strategy is PedagogyStrategy.SOCRATIC
        assert result.allowed is False
        assert result.reason_code == REASON_HINT_NOT_ESCALATED
        assert result.requested is PedagogyStrategy.WORKED_EXAMPLE


# ──────────────────────────────────────────────────────────────────────────
# acceptance ③ — gate()는 카탈로그를 읽지 않는다(정적+런타임 이중 동결)
# ──────────────────────────────────────────────────────────────────────────
class TestGateCatalogAbsenceFrozen:
    """04e §4 불변식 ② — 카탈로그(효과 축)가 gate(허용 축) 입력이 되면 코퍼스 편집만으로
    "효과 ≤ 허용"이 우회된다. 이 클래스가 그 부재를 동결한다(깨려면 04e §4 개정이 선행)."""

    _CATALOG_SYMBOLS = frozenset(
        {
            "get_pedagogy_strategies",
            "get_strategy",
            "narrow_candidates",
            "strategy_registry",
            "get_settings",  # gate는 플래그에도 무의존 — 판정이 env로 흔들리면 안 된다.
        }
    )

    def test_gate_code_references_no_catalog_symbols(self) -> None:
        assert not set(gate.__code__.co_names) & self._CATALOG_SYMBOLS
        source = inspect.getsource(gate)
        # docstring의 *금지 서술*은 허용하되 실제 호출 형태("심볼(")는 없어야 한다.
        for symbol in self._CATALOG_SYMBOLS:
            assert f"{symbol}(" not in source

    def test_gate_signature_frozen(self) -> None:
        # 카탈로그 파라미터가 시그니처로 스며드는 회귀 차단 — (strategy, signals, *, pack)만.
        params = list(inspect.signature(gate).parameters)
        assert params == ["strategy", "signals", "pack"]

    def test_gate_verdicts_survive_catalog_bomb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 런타임 동결 — 레지스트리 전 표면을 봄베로 바꿔도 gate 판정은 동일·무예외.
        scenarios = [
            # (전략, 신호, k_type 팩) — 축① 차단·축② 차단·정당 허용·비대상 통과.
            (
                PedagogyStrategy.WORKED_EXAMPLE,
                StudentSignals(polya_stage=PolyaStage.UNDERSTAND, hint_level=1),
                "CONCEPT",
            ),
            (
                PedagogyStrategy.WORKED_EXAMPLE,
                StudentSignals(polya_stage=PolyaStage.EXECUTE, turn_count=5, hint_level=1),
                None,
            ),
            (
                PedagogyStrategy.WORKED_EXAMPLE,
                StudentSignals(polya_stage=PolyaStage.EXECUTE, turn_count=5, hint_level=3),
                None,
            ),
            (PedagogyStrategy.SOCRATIC, StudentSignals(), "CONCEPT"),
        ]
        from whymath_backend.l4.pedagogy.pack_registry import get_pack

        baseline = [gate(s, sig, pack=get_pack(kt) if kt else None) for (s, sig, kt) in scenarios]

        def _bomb(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("gate()가 카탈로그를 읽음 — 04e §4 불변식 ② 위반")

        monkeypatch.setattr(strategy_registry, "get_pedagogy_strategies", _bomb)
        monkeypatch.setattr(strategy_registry, "get_strategy", _bomb)
        monkeypatch.setattr(runtime_selector, "get_pedagogy_strategies", _bomb)
        bombed = [gate(s, sig, pack=get_pack(kt) if kt else None) for (s, sig, kt) in scenarios]
        assert bombed == baseline
        # 변별력 전제 재확인 — 시나리오에 차단·허용이 실제로 섞여 있다(전부 같은 판정이면 위장).
        assert {r.allowed for r in bombed} == {True, False}


# ──────────────────────────────────────────────────────────────────────────
# 전략 카드 계층 — 렌더·바이트 동일 계약(prompt_assembler)
# ──────────────────────────────────────────────────────────────────────────
class TestStrategyCardLayer:
    def test_render_none_is_empty(self) -> None:
        assert render_strategy_card(None) == ""

    def test_render_injects_summary_one_basis_line_only(self) -> None:
        # 04e §3.2 — name_ko·description·research_basis **첫 1줄만**(attention 절약).
        card = _card(
            PedagogyStrategy.SOCRATIC,
            research_basis=("첫째 근거 (1945)", "둘째 근거 (1982)"),
        )
        block = render_strategy_card(card)
        assert "테스트 전략" in block
        assert "첫째 근거 (1945)" in block
        assert "둘째 근거 (1982)" not in block  # 요약 1줄만 — 2번째 인용 미주입.
        assert "테스트 전용 서술." not in block  # usage_notes는 사람 서술 전용 — 기계 배선 금지.
        assert "노출하지 마라" in block  # 학생-대면 미노출 지시 동봉.

    def test_attach_none_card_is_byte_identical(self) -> None:
        # 옵트인 무변경 계약의 단일 지점 — 무카드면 입력 객체 그대로(바이트 동일).
        system = "기존 시스템 프롬프트."
        assert attach_strategy_card(system, None) is system

    def test_attach_appends_block_with_separator(self) -> None:
        card = _card(PedagogyStrategy.SOCRATIC)
        out = attach_strategy_card("기존 시스템.", card)
        assert out.startswith("기존 시스템.\n\n[교수전략: ")

    def test_attach_to_empty_system_returns_block_only(self) -> None:
        card = _card(PedagogyStrategy.SOCRATIC)
        out = attach_strategy_card("", card)
        assert out.startswith("[교수전략: ")  # 선행 \n\n 잔류 없음.


# ──────────────────────────────────────────────────────────────────────────
# supply() 배선 — 생성 폴백의 카드 주입(플래그 OFF 미조회·ON 주입·실패 로그)
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _FakeRow:
    """`ConceptContent` ORM 행 최소 대역(`test_content_supply.py` 동형)."""

    code: str = "A1"
    name: str = "일차식"
    subject: str = "중등수학"
    unit: str | None = "문자와 식"
    metaphor: str | None = "저울의 균형을 맞추는 일과 같다."
    misconception: str | None = "차수를 혼동한다."
    formal_definition_internal: str | None = "미지수의 차수가 1인 식."
    accepted_expressions: str | None = "2x + 3"
    explanation: str | None = None
    standard_codes: list[str] = field(default_factory=list)
    atom_codes: list[str] = field(default_factory=list)
    flashcards: list[dict[str, object]] = field(default_factory=list)


class _FakeSession:
    def __init__(self, rows: dict[str, _FakeRow] | None = None) -> None:
        self._rows = rows or {}

    async def get(self, _model: object, pk: str) -> _FakeRow | None:
        return self._rows.get(pk)


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self.store[key] = value


class _RecordingTrace:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def record(self, fields: dict[str, object]) -> None:
        self.records.append(fields)


class _SystemRecordingProvider:
    """생성 provider 대역 — 실제로 받은 system을 기록한다(카드 주입 관측 지점)."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_system: str | None = None

    async def generate(self, prompt: str, system: str, decision: Any, **kwargs: Any) -> Any:
        from whymath_backend.l3.models import GenerationResult

        self.calls += 1
        self.last_system = system
        return GenerationResult(text="생성된 설명")


def _routing_request() -> RoutingRequest:
    return RoutingRequest(
        task_type="explain",
        difficulty="easy",
        requires_reasoning=False,
        student_subscription="free",
        sync=True,
    )


async def _generate_supply(provider: _SystemRecordingProvider, system: str = "기본 시스템") -> Any:
    """DSL 미적재 → 생성 폴백으로 흐르는 supply 호출(카드 배선 관측 경로)."""
    return await supply(
        code="MISSING",
        signals=StudentSignals(),
        session=_FakeSession(),  # type: ignore[arg-type]
        cache=_FakeCache(),
        generate_request=_routing_request(),
        provider=provider,  # type: ignore[arg-type]
        trace=_RecordingTrace(),
        system=system,
        seal=default_expression_seal(),
        assessment_verifier=default_assessment_answer_verifier(),
    )


class TestSupplyCardWiring:
    @pytest.mark.asyncio
    async def test_flag_off_system_unchanged_and_catalog_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 기본(OFF) — system 바이트 동일 + 카탈로그 미조회(봄베).
        def _bomb(_strategy: Any) -> Any:
            raise AssertionError("플래그 OFF에서 카드 조회됨 — 미조회 계약 위반")

        monkeypatch.setattr(content_supply, "get_strategy", _bomb)
        provider = _SystemRecordingProvider()
        result = await _generate_supply(provider, system="기본 시스템")
        assert result.content_source == "generate"
        assert provider.last_system == "기본 시스템"

    @pytest.mark.asyncio
    async def test_flag_on_injects_decided_strategy_card(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ON — decide()가 고른 전략(기본 신호 → SOCRATIC)의 카드가 system 뒤에 붙는다.
        _card_on(monkeypatch)
        provider = _SystemRecordingProvider()
        result = await _generate_supply(provider, system="기본 시스템")
        assert result.strategy is PedagogyStrategy.SOCRATIC
        assert provider.last_system is not None
        assert provider.last_system.startswith("기본 시스템\n\n[교수전략: ")
        assert "소크라테스 문답" in provider.last_system  # 실 코퍼스 카드 name_ko.

    @pytest.mark.asyncio
    async def test_flag_on_lookup_failure_logs_type_and_proceeds(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # 카드 조회 실패 — 예외 타입명 WARNING 로그 후 무카드 진행(생성은 막지 않는다).
        _card_on(monkeypatch)

        def _broken(_strategy: Any) -> Any:
            raise LookupError("카탈로그 미등록 재현")

        monkeypatch.setattr(content_supply, "get_strategy", _broken)
        provider = _SystemRecordingProvider()
        with caplog.at_level(logging.WARNING, logger=_SUPPLY_LOGGER):
            result = await _generate_supply(provider, system="기본 시스템")
        assert result.content_source == "generate"
        assert provider.last_system == "기본 시스템"  # 무카드 — system 무변경.
        assert any("LookupError" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_flag_on_render_path_never_reads_catalog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 렌더 경로(dsl_render)는 프롬프트가 없다 — 플래그 ON이어도 카드 미조회(봄베).
        _card_on(monkeypatch)

        def _bomb(_strategy: Any) -> Any:
            raise AssertionError("렌더 경로에서 카드 조회됨")

        monkeypatch.setattr(content_supply, "get_strategy", _bomb)
        result = await supply(
            code="A1",
            signals=StudentSignals(),
            session=_FakeSession({"A1": _FakeRow()}),  # type: ignore[arg-type]
            cache=_FakeCache(),
            seal=default_expression_seal(),
            assessment_verifier=default_assessment_answer_verifier(),
        )
        assert result.content_source == "dsl_render"
