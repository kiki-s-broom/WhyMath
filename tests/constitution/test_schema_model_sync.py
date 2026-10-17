"""R4-02 (헌법 제7조 · A0005 개정 초안) — 스키마 명세 YAML 의 필드는 대응 모델에 존재한다.

배경: 규칙의 원 문구("JSON Schema 에서 자동 생성")는 이 저장소와 전제가 다르다. `schemas/v1.1/*.yaml`
은 자체 명세 YAML 이고 Pydantic 모델은 손으로 쓴다. 그래서 목적(스키마와 모델이 조용히 어긋나지 않게
한다)만 남겨 "필드 이름 일치 검사"로 집행한다(`docs/constitution_proposals/A0005_*`).

지키는 것:
  ① 일치 엔티티 — YAML 에 있는 필드가 모델에서 빠지면 RED.
  ② 어긋남 엔티티 — 현재의 "YAML 에만 있는 필드" 집합을 동결한다. 새 어긋남도 RED, 해소됐는데
     동결 목록에 남은 것도 RED(동결이 거짓 유예로 굳지 않게 — 줄기만 한다).
  ③ 만료 — 어긋남·미확정 등록은 `EXPIRES` 가 지나면 RED(만료 없는 유예 금지).
  ④ 귀속 — `schemas/v1.1/` 의 YAML 이 등록부와 정확히 같다. 0건 스캔·미등록 신규 YAML 은 RED.

지키지 못하는 것(정직한 공백): 필드 *이름*만 본다 — 타입·필수 여부·enum 값은 보지 않는다. DB 컬럼
(SQLAlchemy)·Dart 모델도 보지 않는다. 모델에만 있는 필드(확장)는 허용한다.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, create_model

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "schemas" / "v1.1"

# 어긋남·미확정 유예의 재확인 기한 — 12월 검증(G0~G5) 직전. 늦추려면 이 상수만 고친다.
EXPIRES = date(2026, 12, 31)


@dataclass(frozen=True)
class Entry:
    """엔티티 하나의 등록 — model 은 'module:Class', None 이면 대응 모델 미확정."""

    model: str | None
    # 어긋남 동결 집합 — aligned 는 빈 집합이어야 하고, drift 는 현재 값과 정확히 같아야 한다.
    frozen: frozenset[str] = frozenset()


REGISTRY: dict[str, Entry] = {
    "curriculum_entry": Entry("whymath_backend.schema.curriculum_entry:CurriculumEntry"),
    "textbook_mapping": Entry("whymath_backend.schema.textbook_mapping:TextbookMapping"),
    "solution_path": Entry(
        "whymath_backend.l3.solution_path:SolutionPath", frozenset({"embedding"})
    ),
    "hint": Entry(
        "whymath_backend.l4.hint_content.models:Hint",
        frozenset({"created_at", "generated_by_tier"}),
    ),
    "concept": Entry(
        "whymath_backend.schema.concept:Concept",
        frozenset(
            {
                "domain",
                "grade_band_hint",
                "misconception_codes",
                "notes",
                "prerequisite_concept_ids",
                "standard_codes",
                "visualization_card_keys",
            }
        ),
    ),
    "edge": Entry(
        "whymath_backend.schema.concept:ConceptEdge",
        frozenset(
            {
                "dst_concept_id",
                "evidence",
                "evidence_source",
                "relation",
                "src_concept_id",
                "strength",
            }
        ),
    ),
    "problem": Entry(
        "whymath_backend.schema.problem:Problem",
        frozenset(
            {
                "active_concepts",
                "copyright",
                "difficulty_label",
                "embedding",
                "irt_parameters",
                "language_variants",
                "problem_text",
                "solution_path_ids",
                "standard_codes",
                "techniques",
                "type_cluster_id",
                "year",
            }
        ),
    ),
    # 대응 Pydantic 모델이 아직 없다(2026-10-06 실측) — 생기면 model 을 채워 등록한다.
    "mastery_state": Entry(None),
    "student_profile": Entry(None),
}


def yaml_only_fields(yaml_fields: set[str], model: type[BaseModel]) -> set[str]:
    """YAML 에는 있고 모델에는 없는 필드 이름들(빈 집합이면 일치)."""
    return yaml_fields - set(model.model_fields)


def load_yaml_fields(stem: str) -> set[str]:
    data = yaml.safe_load((SCHEMA_DIR / f"{stem}.schema.yaml").read_text(encoding="utf-8"))
    return set(data["fields"])


def load_model(path: str) -> type[BaseModel]:
    module, _, cls = path.partition(":")
    return getattr(importlib.import_module(module), cls)


def discovered_stems() -> set[str]:
    return {p.name.removesuffix(".schema.yaml") for p in SCHEMA_DIR.glob("*.schema.yaml")}


# ── ④ 귀속 ─────────────────────────────────────────────────────────────────


def test_registry_matches_schema_files_exactly() -> None:
    found = discovered_stems()
    assert found, "스캔 0건 — schemas/v1.1 에서 YAML 을 하나도 못 찾았다(경로 오류면 공허 통과)"
    assert found == set(
        REGISTRY
    ), f"미등록 YAML={sorted(found - set(REGISTRY))} · YAML 없는 등록={sorted(set(REGISTRY) - found)}"


# ── ① 일치 / ② 어긋남 동결 ─────────────────────────────────────────────────


@pytest.mark.parametrize("stem", sorted(k for k, v in REGISTRY.items() if v.model))
def test_yaml_fields_exist_in_model(stem: str) -> None:
    entry = REGISTRY[stem]
    assert entry.model is not None
    actual = yaml_only_fields(load_yaml_fields(stem), load_model(entry.model))
    new = actual - entry.frozen
    resolved = entry.frozen - actual
    assert (
        not new
    ), f"{stem}: YAML 에 있는데 모델에 없는 새 필드 {sorted(new)} — 모델을 고치거나 YAML 을 갱신"
    assert (
        not resolved
    ), f"{stem}: 이미 일치하는데 동결 목록에 남은 필드 {sorted(resolved)} — REGISTRY 에서 제거(줄기만 한다)"


# ── ③ 만료 ─────────────────────────────────────────────────────────────────


def test_deferrals_not_expired() -> None:
    deferred = sorted(k for k, v in REGISTRY.items() if v.frozen or v.model is None)
    assert deferred, "유예가 하나도 없으면 이 검사 자체를 정리할 때다(상수 EXPIRES 제거)"
    assert (
        date.today() <= EXPIRES
    ), f"유예 만료({EXPIRES}) — 재확인 필요: {deferred}. 해소하거나 기한을 의식적으로 연장한다"


def test_unmapped_entities_really_have_no_model() -> None:
    """미확정 등록이 거짓이 되지 않게 — 같은 이름의 Pydantic 모델이 생기면 등록하라고 알린다."""
    candidates = {
        "mastery_state": ["whymath_backend.schema.mastery_contract:MasteryState"],
        "student_profile": ["whymath_backend.schema.user:StudentProfile"],
    }
    for stem, paths in candidates.items():
        assert REGISTRY[stem].model is None
        for path in paths:
            try:
                model = load_model(path)
            except (ImportError, AttributeError):
                continue
            assert not (
                isinstance(model, type) and issubclass(model, BaseModel)
            ), f"{stem}: {path} 가 생겼다 — REGISTRY 에 등록한다"


# ── 검사 함수의 변별력(정상·위반 입력 양쪽) ─────────────────────────────────


def _model(*names: str) -> type[BaseModel]:
    return create_model("M", **{n: (int, 0) for n in names})  # type: ignore[call-overload]


def test_detects_field_missing_in_model() -> None:
    assert yaml_only_fields({"a", "b"}, _model("a")) == {"b"}


def test_model_extension_is_allowed() -> None:
    assert yaml_only_fields({"a"}, _model("a", "extra")) == set()


def test_exact_match_is_empty() -> None:
    assert yaml_only_fields({"a", "b"}, _model("a", "b")) == set()
