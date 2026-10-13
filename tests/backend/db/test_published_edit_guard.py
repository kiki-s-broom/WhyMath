"""발행 판 보호 판정 모듈 동결 — hermetic (EOS-195).

`db/published_edit_guard.py`의 서빙 내용 필드 목록(`SERVED_CONTENT_FIELDS`)은 두 곳과 같아야 한다:

  A. `l3/problem_publish_gate.snapshot_payload`가 읽는 문항 속성 — 게이트가 "내용"으로 보는 것
  B. `ProblemVersionPayload`의 필드(파생 해시 제외) — 판이 "내용"으로 저장하는 것

둘 중 하나와 갈라지면 게이트가 보는 내용과 여기서 막는 내용이 어긋난다 — 새 payload 필드가 생겼는데
수정 가드가 모르고 지나가는 것이 이 모듈의 가장 그럴듯한 실패 모드다. 그래서 목록을 눈으로 맞추지
않고 AST·스키마 필드와 기계로 대조한다.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from whymath_backend.db import published_edit_guard as guard
from whymath_backend.db.published_edit_guard import (
    SERVED_CONTENT_FIELDS,
    changed_served_fields,
    has_published_version,
)
from whymath_backend.schema.problem_version import ProblemVersionPayload

_PKG = Path(__file__).resolve().parents[3] / "src" / "backend" / "whymath_backend"


def _snapshot_attrs() -> set[str]:
    """`snapshot_payload`가 매개변수 `problem`에서 읽는 속성 이름 전부."""
    tree = ast.parse((_PKG / "l3" / "problem_publish_gate.py").read_text(encoding="utf-8"))
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "snapshot_payload"
    )
    return {
        n.attr
        for n in ast.walk(func)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "problem"
    }


# ── 목록 동기 ────────────────────────────────────────────────────────────────────────
def test_served_fields_equal_what_snapshot_payload_reads() -> None:
    attrs = _snapshot_attrs()
    assert attrs, "snapshot_payload에서 문항 속성을 하나도 못 읽었다 — 스캔 대상 붕괴"
    assert set(SERVED_CONTENT_FIELDS) == attrs, (
        f"가드 목록과 snapshot_payload가 갈라졌다: 가드에만 {set(SERVED_CONTENT_FIELDS) - attrs}, "
        f"snapshot에만 {attrs - set(SERVED_CONTENT_FIELDS)}"
    )


def test_served_fields_equal_the_payload_schema_fields() -> None:
    """B축 — payload에 필드가 새로 생기면 가드 목록도 늘어야 한다.

    `stem_hash`·`answer_hash`는 발문·정답에서 파생되고, `difficulty_at_publish`의 원천은 문항의
    `difficulty_overall`이다.
    """
    derived = {"stem_hash", "answer_hash"}
    renamed = {"difficulty_at_publish": "difficulty_overall"}
    payload_fields = set(ProblemVersionPayload.model_fields)
    sources = {renamed.get(name, name) for name in payload_fields - derived}
    assert set(SERVED_CONTENT_FIELDS) == sources, (
        f"payload 필드와 가드 목록이 갈라졌다: 가드에만 {set(SERVED_CONTENT_FIELDS) - sources}, "
        f"payload에만 {sources - set(SERVED_CONTENT_FIELDS)}"
    )


def test_field_list_has_no_duplicates() -> None:
    assert len(set(SERVED_CONTENT_FIELDS)) == len(SERVED_CONTENT_FIELDS)


# ── has_published_version ────────────────────────────────────────────────────────────
def test_has_published_version_reads_the_pointer() -> None:
    assert has_published_version(SimpleNamespace(problem_version_id="x")) is True
    assert has_published_version(SimpleNamespace(problem_version_id=None)) is False


def test_missing_pointer_attribute_means_not_published() -> None:
    """포인터 속성이 없는 객체는 '발행됨'이 아니다 — 모르는 것을 막음으로 확정하지 않는다."""
    assert has_published_version(SimpleNamespace()) is False


# ── changed_served_fields ───────────────────────────────────────────────────────────
def _row(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {name: f"v-{name}" for name in SERVED_CONTENT_FIELDS}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_identical_rows_have_no_change() -> None:
    assert changed_served_fields(_row(), _row()) == ()


@pytest.mark.parametrize("field", SERVED_CONTENT_FIELDS)
def test_each_served_field_change_is_detected_alone(field: str) -> None:
    """필드마다 독립적으로 잡힌다 — 한 필드가 목록에서 빠지면 이 케이스만 빨개진다."""
    assert changed_served_fields(_row(), _row(**{field: "다른 값"})) == (field,)


def test_changes_are_reported_sorted_and_without_values() -> None:
    changed = changed_served_fields(_row(), _row(answer="새 정답", choices=["a"]))
    assert changed == ("answer", "choices")
    assert all(isinstance(name, str) for name in changed)


def test_none_to_value_and_value_to_none_are_changes() -> None:
    assert changed_served_fields(_row(answer=None), _row(answer="x")) == ("answer",)
    assert changed_served_fields(_row(answer="x"), _row(answer=None)) == ("answer",)


@pytest.mark.parametrize(
    "unserved",
    ["review_status", "quarantine_reason", "quarantined_at", "problem_version_id", "irt_a"],
)
def test_fields_outside_the_payload_do_not_count(unserved: str) -> None:
    """검수·격리·포인터·IRT 모수는 서빙 내용이 아니다 — 이것들까지 막으면 긴급 정지가 막힌다."""
    assert changed_served_fields(_row(**{unserved: 1}), _row(**{unserved: 2})) == ()


# ── 경계 ────────────────────────────────────────────────────────────────────────────
def test_module_imports_nothing_from_the_package() -> None:
    """순수 판정이다 — 판 축 모듈(`problem_version`·`version_header`·게이트)이 이 파일을 거쳐
    문항 노출 경로(AST 동결 B2)로 새지 않도록 패키지 내부 import를 일절 두지 않는다."""
    tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert not [m for m in imported if m.startswith("whymath_backend")], imported


def test_module_path_avoids_the_names_the_exposure_boundary_forbids() -> None:
    """B2는 모듈 경로에 이 세 이름이 든 import를 노출 경로에서 금지한다 — 이 모듈 이름이 걸리면
    `api/problems.py`가 이 가드를 import하는 순간 경계 테스트가 빨개진다."""
    for part in ("problem_version", "version_header", "problem_publish_gate"):
        assert part not in guard.__name__
