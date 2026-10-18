"""오답 서명 규칙표 로더와 kebab ↔ M-id 코퍼스 조회(P3-56 후보 구현).

검증 축:
  ① YAML이 계약대로 적재되고, 규칙의 M-id가 오개념 코퍼스에 **실재**하며 귀속 개념이 대표 과정이다.
  ② 로더는 파일이 없거나 코퍼스가 비면 조용히 빈 표를 돌려주지 않는다(fail-closed).
  ③ 크로스워크 조회: M-id → kebab은 정확히 하나일 때만, canonical은 기존 `select_canonical` 정책 그대로.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l1.misconception import wrong_answer_signature_table as tables
from whymath_backend.l1.standards.phase3_scope import load_scope_spec

_REPO = Path(__file__).resolve().parents[3]
_MISCONCEPTIONS = _REPO / "data" / "corpus" / "misconceptions_v1" / "misconceptions.json"


@pytest.fixture(autouse=True)
def _fresh_caches() -> None:
    """캐시된 표가 테스트 사이로 새지 않게 한다 — 주입 테스트가 경로를 바꾸기 때문이다."""
    tables.load_signature_spec.cache_clear()
    tables._crosslink_links.cache_clear()
    yield
    tables.load_signature_spec.cache_clear()
    tables._crosslink_links.cache_clear()


def _corpus_mis_ids() -> dict[str, str]:
    """오개념 코퍼스의 M-id → 귀속 성취기준."""
    payload = json.loads(_MISCONCEPTIONS.read_text(encoding="utf-8"))
    items = payload["misconceptions"]
    assert items, "오개념 코퍼스 0건 — 공허한 통과를 막는다"
    return {str(r["mis_id"]): str(r["standard_code"]) for r in items}


class TestDataLoadsAndIsGrounded:
    def test_table_loads(self) -> None:
        assert len(tables.load_signature_spec().rules) >= 1

    def test_every_referenced_mis_id_exists_in_the_misconception_corpus(self) -> None:
        """없는 M-id를 가리키는 규칙은 어떤 후보에도 닿지 못하는 죽은 데이터다."""
        corpus = _corpus_mis_ids()
        cited = {m for r in tables.load_signature_spec().rules for m in r.mis_ids}
        assert cited, "참조 0건 — 공허한 통과를 막는다"
        assert cited <= set(corpus), f"코퍼스에 없는 M-id: {sorted(cited - set(corpus))}"

    def test_every_cited_mis_id_is_a_core_misconception_of_the_frozen_scope(self) -> None:
        """대표 과정 밖의 오개념을 '김에' 채우지 않는다(P3 범위 규율)."""
        core = {m.mis_id for m in load_scope_spec().core_misconceptions}
        cited = {m for r in tables.load_signature_spec().rules for m in r.mis_ids}
        assert cited <= core, f"동결 범위 밖: {sorted(cited - core)}"

    def test_unseated_core_misconceptions_have_no_rule_pretending_otherwise(self) -> None:
        """좌석이 없는 오개념의 규칙은 후보가 영영 닿지 않는 죽은 데이터다 — 두지 않는다."""
        unseated = {
            m.mis_id
            for m in load_scope_spec().core_misconceptions
            if tables.kebab_for_mis_id(m.mis_id) is None
        }
        assert unseated, "좌석 없는 핵심 오개념이 사라졌다면 이 테스트를 갱신하라"
        cited = {m for r in tables.load_signature_spec().rules for m in r.mis_ids}
        assert cited & unseated == set()


class TestFailClosed:
    def test_missing_signature_file_raises_not_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tables, "SIGNATURE_RULES_PATH", _REPO / "no" / "such.yaml")
        tables.load_signature_spec.cache_clear()
        with pytest.raises(FileNotFoundError):
            tables.load_signature_spec()

    def test_empty_crosslink_corpus_is_a_failure_not_zero_mappings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty = tmp_path / "crosslinks.json"
        empty.write_text(json.dumps({"crosslinks": []}), encoding="utf-8")
        monkeypatch.setattr(tables, "CROSSLINKS_PATH", empty)
        tables._crosslink_links.cache_clear()
        with pytest.raises(ValueError, match="비어 있습니다"):
            tables.mis_ids_for_kebab("product-rule-naive")


def _write_crosslinks(path: Path, rows: list[tuple[str, str, str, float | None]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "crosslinks": [
                    {"kebab_id": k, "mis_id": m, "link_type": t, "confidence": c}
                    for k, m, t, c in rows
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class TestCrosslinkReading:
    def test_real_corpus_resolves_the_seated_core(self) -> None:
        assert tables.kebab_for_mis_id("M0671") == "power-rule-step-omitted"
        assert tables.kebab_for_mis_id("M0864") == "extremum-max-min-confused"
        # M0075와 M0672는 같은 kebab을 공유한다 — 런타임 후보는 둘을 구분하지 못한다.
        assert tables.kebab_for_mis_id("M0075") == tables.kebab_for_mis_id("M0672")
        assert tables.mis_ids_for_kebab("product-rule-naive") == ("M0075", "M0672")

    def test_canonical_follows_the_existing_strict_max_policy(self) -> None:
        # 0.97(M0075) vs 0.85(M0672): 단독 최대 → M0075.
        assert tables.canonical_mis_id_for_kebab("product-rule-naive") == "M0075"

    def test_unseated_mis_ids_resolve_to_none_not_to_a_guess(self) -> None:
        for mis_id in ("M0673", "M0674", "M0676", "M0677", "M0678"):
            assert tables.kebab_for_mis_id(mis_id) is None, mis_id

    def test_unknown_inputs_are_none_or_empty(self) -> None:
        assert tables.kebab_for_mis_id("M9999") is None
        assert tables.mis_ids_for_kebab("no-such-kebab") == ()
        assert tables.canonical_mis_id_for_kebab("no-such-kebab") is None

    def test_mis_id_on_two_kebabs_is_not_guessed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """어느 kebab이 런타임 키인지 코퍼스가 정하지 않았다 — 임의로 고르면 오귀속이다."""
        path = _write_crosslinks(
            tmp_path / "c.json",
            [("kebab-a", "M0001", "직접매핑", 0.9), ("kebab-b", "M0001", "직접매핑", 0.9)],
        )
        monkeypatch.setattr(tables, "CROSSLINKS_PATH", path)
        tables._crosslink_links.cache_clear()
        assert tables.kebab_for_mis_id("M0001") is None

    def test_canonical_tie_is_unselected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write_crosslinks(
            tmp_path / "c.json",
            [("kebab-a", "M0001", "직접매핑", 0.9), ("kebab-a", "M0002", "직접매핑", 0.9)],
        )
        monkeypatch.setattr(tables, "CROSSLINKS_PATH", path)
        tables._crosslink_links.cache_clear()
        assert tables.canonical_mis_id_for_kebab("kebab-a") is None
        # 동률이어도 조회는 둘 다 돌려준다 — 정책이 고르지 못했을 뿐 링크가 사라진 것은 아니다.
        assert tables.mis_ids_for_kebab("kebab-a") == ("M0001", "M0002")

    def test_null_confidence_links_are_not_canonical_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write_crosslinks(tmp_path / "c.json", [("kebab-a", "M0001", "직접매핑", None)])
        monkeypatch.setattr(tables, "CROSSLINKS_PATH", path)
        tables._crosslink_links.cache_clear()
        assert tables.canonical_mis_id_for_kebab("kebab-a") is None
