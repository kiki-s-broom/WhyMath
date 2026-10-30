"""PED-05 교수전략 카탈로그 레지스트리 + enum↔YAML 1:1 거버넌스 — 실 코퍼스 스모크 포함.

정본: `docs/architecture/04g_pedagogy_strategy_catalog.md` §3.1("enum ↔ YAML 1:1 거버넌스
테스트로 동결" — `test_render_governance.py` 선례). 검증 축:

  ① 1:1 거버넌스 — YAML 파일 스템 == enum 값 소문자 10종(누락·잉여 즉시 적발)·registry 키 ==
     enum 값 10종. GAME 부재(반게임화 정체성 — enum 배제 선례)를 명시 확인.
  ② registry 계약 — lru_cache(maxsize=1) 동일 객체 반환·reset seam으로 재로딩·`get_strategy`
     enum/문자열 겸용 조회·미등록 `LookupError`(조용한 폴백 금지 — 팩 `get_pack`의 None과
     의도적으로 다름).
  ③ 실 코퍼스 스모크 — 카탈로그 10건 전량이 schema 게이트(폐쇄 어휘·research_basis 최소 1·빈
     문자열 거부)를 통과해 로드된다. WORKED_EXAMPLE 카드의 "시도 전 제공 금지" 서술(절대 금기
     연동·04d §2.2 게이트 병기)을 내용 동결.

hermetic: 실 코퍼스는 저장소 파일이라 네트워크·DB 불요.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from whymath_backend.l4.pedagogy import strategy_registry
from whymath_backend.l4.pedagogy.strategy_registry import (
    get_pedagogy_strategies,
    get_strategy,
    reset_strategy_cache,
)
from whymath_backend.schema.enums import KnowledgeType, PedagogyStrategy
from whymath_backend.schema.pedagogy_strategy import (
    DIFFICULTY_VOCAB,
    ERROR_TYPE_VOCAB,
    GRADE_BAND_VOCAB,
)

# 실 코퍼스 디렉터리 — 이 테스트 파일(tests/backend/l4/pedagogy/) 기준 parents[4] = 레포 루트.
_STRATEGIES_DIR = Path(__file__).resolve().parents[4] / "data" / "corpus" / "pedagogy_strategies_v1"

# 폐쇄 10종 값(값집합 자체는 test_render_governance.py가 동결 — 여기서는 1:1 대응만 본다).
_ENUM_VALUES = {member.value for member in PedagogyStrategy}


class TestOneToOneGovernance:
    """① enum 10종 ↔ YAML 10건 1:1 — 파일 누락·잉여·오탈자 스템 즉시 적발."""

    def test_yaml_stems_match_enum_exactly(self) -> None:
        stems = {path.stem for path in _STRATEGIES_DIR.glob("*.yaml")}
        expected = {value.lower() for value in _ENUM_VALUES}
        missing = expected - stems
        extra = stems - expected
        assert not missing, f"카탈로그 YAML 누락: {sorted(missing)}"
        assert not extra, f"카탈로그 YAML 잉여(enum에 없는 파일): {sorted(extra)}"

    def test_registry_keys_match_enum_exactly(self) -> None:
        reset_strategy_cache()
        assert set(get_pedagogy_strategies()) == _ENUM_VALUES

    def test_file_stem_matches_declared_strategy(self) -> None:
        # 파일명과 내부 strategy 값이 엇갈리면(복붙 실수) dict 키가 파일 하나를 삼킨다 —
        # 스템 == strategy 소문자를 파일 단위로 검증해 엇갈림을 잡는다.
        reset_strategy_cache()
        cards = get_pedagogy_strategies()
        for value, card in cards.items():
            expected_stem = value.lower()
            assert (_STRATEGIES_DIR / f"{expected_stem}.yaml").exists()
            assert str(card.strategy) == value

    def test_game_absent(self) -> None:
        # 반게임화 정체성(CLAUDE.md 절대 금기·enum GAME 배제 선례) — 카탈로그에도 없다.
        assert not (_STRATEGIES_DIR / "game.yaml").exists()
        assert "GAME" not in get_pedagogy_strategies()


class TestRegistryContract:
    """② lru_cache·reset seam·enum/문자열 겸용 조회·미등록 LookupError."""

    def test_lru_cache_returns_same_object(self) -> None:
        reset_strategy_cache()
        assert get_pedagogy_strategies() is get_pedagogy_strategies()

    def test_reset_seam_reloads(self) -> None:
        reset_strategy_cache()
        first = get_pedagogy_strategies()
        reset_strategy_cache()
        second = get_pedagogy_strategies()
        assert first is not second
        assert set(first) == set(second)

    def test_get_strategy_accepts_enum_and_str(self) -> None:
        reset_strategy_cache()
        by_enum = get_strategy(PedagogyStrategy.ANALOGY)
        by_str = get_strategy("ANALOGY")
        assert by_enum is by_str
        assert by_enum.name_ko == "비유"

    def test_get_strategy_unknown_raises_lookup_error(self) -> None:
        # 조용한 폴백 금지 — 미등록 조회는 결함이라 None이 아니라 LookupError다
        # (팩 get_pack의 fail-soft None과 의도적으로 다른 계약·모듈 docstring 참조).
        reset_strategy_cache()
        with pytest.raises(LookupError, match="NOT_A_STRATEGY"):
            get_strategy("NOT_A_STRATEGY")

    def test_provenance_not_globbed(self) -> None:
        # 표지 메타(_provenance.json)는 .yaml이 아니라 로더 glob에 안 잡힌다(팩 레지스트리 동형).
        assert (_STRATEGIES_DIR / "_provenance.json").exists()
        assert len(get_pedagogy_strategies()) == len(_ENUM_VALUES)

    def test_repo_root_anchor(self) -> None:
        # 경로 앵커 회귀 방어 — 모듈이 잡은 코퍼스 디렉터리가 테스트가 아는 실 경로와 일치.
        assert strategy_registry._STRATEGIES_DIR == _STRATEGIES_DIR


class TestFullCatalogSmoke:
    """③ 실 코퍼스 10건 전량 로드 성공 + 내용 스모크(schema 게이트 통과의 실물 증명)."""

    def test_all_cards_load_and_are_well_formed(self) -> None:
        reset_strategy_cache()
        cards = get_pedagogy_strategies()
        assert len(cards) == 10
        for card in cards.values():
            # schema 불변식이 이미 게이트하지만, 실 코퍼스가 실제로 채워졌는지 스모크로 재확인.
            assert card.name_ko
            assert card.description
            assert len(card.research_basis) >= 1
            assert set(card.target_grade_bands) <= GRADE_BAND_VOCAB
            assert set(card.difficulty_range) <= DIFFICULTY_VOCAB
            assert set(card.suitable_error_types) <= ERROR_TYPE_VOCAB
            assert {str(k) for k in card.target_k_types} <= {m.value for m in KnowledgeType}
            assert card.usage_notes

    def test_worked_example_usage_notes_pins_no_answer_first(self) -> None:
        # 절대 금기 연동 서술 동결 — "학생이 시도하기 전 제공 금지"가 usage_notes에 있고,
        # 기계 강제 좌석(04d §2.2 완전예제 2축 게이트)이 병기되어 있다(사람 서술 전용 명시).
        card = get_strategy(PedagogyStrategy.WORKED_EXAMPLE)
        assert "시도하기 전 제공 금지" in card.usage_notes
        assert "04d" in card.usage_notes

    def test_enum_docstring_consistency_spot_checks(self) -> None:
        # enum docstring의 기존 효능 서술과 카탈로그 매핑의 정합 스팟 체크:
        # RETRIEVAL "계산 실수·정착 부족에 유효" → 절차오류 / ANALOGY "개념 이해 부족에 유효"
        # → 개념혼동.
        assert "절차오류" in get_strategy(PedagogyStrategy.RETRIEVAL).suitable_error_types
        assert "개념혼동" in get_strategy(PedagogyStrategy.ANALOGY).suitable_error_types

    def test_honest_gap_strategies_declare_empty_error_types(self) -> None:
        # 정직한 공백 — 특정 오류 유형 교정 축이 아닌 전략(동기/파지 스케줄링 축)은
        # suitable_error_types를 비워둔다(억지 매핑 금지·04g §3.2 "자신 없으면 적게").
        assert get_strategy(PedagogyStrategy.SPACING).suitable_error_types == []
        assert get_strategy(PedagogyStrategy.PROBLEM_BASED).suitable_error_types == []

    def test_every_k_type_covered_by_at_least_one_strategy(self) -> None:
        # 지식유형 커버리지 — 7유형 각각을 겨냥하는 전략이 최소 1개 있어야 한다. 0개인
        # 유형은 select() k_type 필터가 그 유형 학생에게 *항상* 공집합→폴백이 되어 카탈로그가
        # 체계적 사각을 만든다(폴백 자체는 안전하나 상시 폴백은 저작 공백 신호).
        reset_strategy_cache()
        covered: set[str] = set()
        for card in get_pedagogy_strategies().values():
            covered |= {str(k) for k in card.target_k_types}
        uncovered = {m.value for m in KnowledgeType} - covered
        assert not uncovered, f"어느 전략도 겨냥하지 않는 지식유형: {sorted(uncovered)}"
