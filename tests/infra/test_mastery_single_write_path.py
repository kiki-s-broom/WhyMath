"""숙달 단일 쓰기 경로 가드의 **변별력** 동결 — 결함 주입 (EOS-108 acceptance ⑥·⑦).

여기서 막는 것은 둘이다.

1. **우회 경로의 신설** — Mastery Engine 계약(`l2/mastery_contract.update_mastery`)을 거치지 않고
   숙달 좌석(`concept_mastery_history`·`skill_mastery_history`)에 쓰는 코드가 생기는 것.
   실 저장소 전수 스캔(`test_real_repo_has_single_write_path`)이 그것을 잡는다.
2. **위장 가드** — 그 스캐너가 *모든* 입력에서 초록인 것. 정상 저장소에서 exit 0인 것은 보호의
   증거가 아니다(CLAUDE.md 2026-09-01 「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」).
   그래서 **막으려는 상태를 합성 트리에 실제로 주입해** 각각이 검출되는지 확인한다.

픽스처 설계 규율 (CLAUDE.md 2026-09-07 「픽스처가 그 절을 실제로 밟는가」)
---------------------------------------------------------------------
스캐너의 절마다 "이 절이 없으면 무엇이 통과하는가"를 정하고 **그 반례 자체**를 픽스처로 둔다:

  · import 별칭 해석이 없으면 → `as CMH` 생성이 통과한다        → `test_detects_aliased_construct`
  · `visit_AugAssign`이 없으면 → `row.mastery += 0.1`이 통과한다 → `test_detects_augmented_assign`
  · `ast.Tuple` 재귀가 없으면 → `a.mastery, b = ...`가 통과한다  → `test_detects_tuple_target`
  · `sa.update(Model)` 분기가 없으면 → 모듈 별칭 일괄 쓰기가 통과 → `test_detects_module_alias_bulk`
  · 공허한 면제 검사가 없으면 → 사라진 코드의 면제가 남는다      → `test_detects_stale_allowance`

그리고 **성공 방향 대조군**을 함께 둔다(`test_ignores_unrelated_confidence_field`) — 대조군이
없으면 "전부 위반으로 계상"이라는 과잉 수정이 그대로 통과한다(CLAUDE.md 2026-09-08).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "analysis" / "mastery_write_path_scan.py"


def _load_scanner() -> ModuleType:
    """스캐너를 파일 경로로 로드한다(`scripts/`는 패키지가 아니다)."""
    spec = importlib.util.spec_from_file_location("mastery_write_path_scan", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # `@dataclass`가 어노테이션을 풀 때 sys.modules에서 자기 모듈을 찾는다.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def scanner() -> ModuleType:
    """스캐너 모듈(모듈 스코프 — 로드는 부작용이 없다)."""
    return _load_scanner()


def _write(tree: Path, rel: str, body: str) -> None:
    """합성 백엔드 트리에 모듈 1개를 쓴다."""
    target = tree / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    """면제 3건이 **전부 적중하는** 최소 합성 트리.

    공허한 면제도 실패이므로(스캐너 규약), 주입 테스트가 *주입한 결함 때문에* 실패하는지
    확인하려면 면제가 먼저 채워져 있어야 한다. 즉 이 픽스처 자체가 "정상 상태 = exit 0"의
    대조군이다.
    """
    tree = tmp_path / "whymath_backend"
    _write(
        tree,
        "l2/mastery_tracking.py",
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory\n\n\n"
        "def _stage_attempt_mastery():\n"
        "    return ConceptMasteryHistory()\n",
    )
    _write(
        tree,
        "l2/skill_mastery_tracking.py",
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def _stage_skill_attempt_mastery():\n"
        "    return SkillMasteryHistory()\n",
    )
    _write(
        tree,
        "l2/learning_event_trace.py",
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory\n\n\n"
        "class _MasteryRowView:\n"
        "    def __init__(self, row):\n"
        "        self.mastery = row.mastery\n",
    )
    return tree


def test_synthetic_baseline_is_clean(scanner: ModuleType, synthetic: Path) -> None:
    """정상 합성 트리는 위반 0·공허한 면제 0 — 주입 테스트의 기준선."""
    result = scanner.scan(synthetic)
    assert result.violations == []
    assert result.unused_allowances == []
    assert result.files_scanned == 3


def test_real_repo_has_single_write_path(scanner: ModuleType) -> None:
    """**실 저장소**의 숙달 쓰기 지점이 계약 경로뿐이다 — 이 가드의 본래 목적.

    `files_scanned`도 함께 단언한다: 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다
    (CLAUDE.md 「스캔 0건은 실패」).
    """
    result = scanner.scan()
    assert result.files_scanned > 100, "백엔드 소스를 못 찾았다 — 전수 스캔이 성립하지 않았다"
    assert result.violations == [], "\n".join(
        f"{v.path}:{v.line} [{v.axis}] {v.scope} — {v.detail}" for v in result.violations
    )
    assert result.unused_allowances == [], "면제가 가리키는 코드가 사라졌다(열린 문)"


# ── 결함 주입 — 각 절의 반례 ────────────────────────────────────────────────


def test_detects_plain_construct(scanner: ModuleType, synthetic: Path) -> None:
    """① 다른 모듈이 숙달 행을 직접 만든다."""
    _write(
        synthetic,
        "api/rogue.py",
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory\n\n\n"
        "def cheat(session):\n"
        "    session.add(ConceptMasteryHistory(mastery=1.0))\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("api/rogue.py", "construct")]


def test_detects_aliased_construct(scanner: ModuleType, synthetic: Path) -> None:
    """① 별칭 import로 숨은 생성 — `grep`이 뚫리는 바로 그 형태."""
    _write(
        synthetic,
        "api/rogue.py",
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory as CMH\n\n\n"
        "def cheat(session):\n"
        "    session.add(CMH(mastery=1.0))\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis, v.detail) for v in result.violations] == [
        ("api/rogue.py", "construct", "CMH(...)")
    ]


def test_detects_direct_assign(scanner: ModuleType, synthetic: Path) -> None:
    """② 읽어 온 행의 숙달 값을 직접 대입한다."""
    _write(
        synthetic,
        "l4/rogue.py",
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def cheat(row):\n"
        "    row.mastery = 1.0\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("l4/rogue.py", "assign")]


def test_detects_augmented_assign(scanner: ModuleType, synthetic: Path) -> None:
    """② 증분 대입 — `visit_AugAssign` 절이 없으면 **이것만** 통과한다(`Assign`과 다른 노드)."""
    _write(
        synthetic,
        "l4/rogue.py",
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def cheat(row):\n"
        "    row.mastery += 0.1\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("l4/rogue.py", "assign")]


def test_detects_annotated_assign(scanner: ModuleType, synthetic: Path) -> None:
    """② 주석 붙은 대입 — `visit_AnnAssign` 절의 반례."""
    _write(
        synthetic,
        "l4/rogue.py",
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def cheat(row):\n"
        "    row.confidence: float = 1.0\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("l4/rogue.py", "assign")]


def test_detects_tuple_target(scanner: ModuleType, synthetic: Path) -> None:
    """② 튜플 언패킹 대입 — `ast.Tuple` 재귀가 없으면 이것만 통과한다."""
    _write(
        synthetic,
        "l4/rogue.py",
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def cheat(row, other):\n"
        "    row.sample_size, other = 99, None\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("l4/rogue.py", "assign")]


def test_detects_bulk_update(scanner: ModuleType, synthetic: Path) -> None:
    """③ SQLAlchemy Core 일괄 갱신 — 행을 만들지도 읽지도 않고 숙달을 바꾼다."""
    _write(
        synthetic,
        "ops/rogue.py",
        "from sqlalchemy import update\n"
        "from whymath_backend.db.models.assessment import SkillMasteryHistory\n\n\n"
        "def cheat(session):\n"
        "    return session.execute(update(SkillMasteryHistory).values(mastery=1.0))\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis) for v in result.violations] == [("ops/rogue.py", "bulk")]


def test_detects_module_alias_bulk(scanner: ModuleType, synthetic: Path) -> None:
    """③ `sa.delete(Model)` — 모듈 별칭 경유. `ast.Attribute` 분기가 없으면 이것만 통과한다."""
    _write(
        synthetic,
        "ops/rogue.py",
        "import sqlalchemy as sa\n"
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory\n\n\n"
        "def cheat(session):\n"
        "    return session.execute(sa.delete(ConceptMasteryHistory))\n",
    )
    result = scanner.scan(synthetic)
    assert [(v.path, v.axis, v.detail) for v in result.violations] == [
        ("ops/rogue.py", "bulk", "delete(ConceptMasteryHistory)")
    ]


def test_detects_stale_allowance(scanner: ModuleType, synthetic: Path, tmp_path: Path) -> None:
    """면제가 가리키는 코드가 사라지면 **그것도 실패**다 — 공허한 면제는 열린 문이다."""
    (synthetic / "l2" / "learning_event_trace.py").unlink()
    result = scanner.scan(synthetic)
    assert [a.scope for a in result.unused_allowances] == ["_MasteryRowView.__init__"]


def test_allowance_scope_is_qualified(scanner: ModuleType, synthetic: Path) -> None:
    """면제 스코프는 **클래스까지 포함**한다 — 같은 이름의 다른 `__init__`이 면제를 못 빌린다."""
    _write(
        synthetic,
        "l2/learning_event_trace.py",
        "from whymath_backend.db.models.assessment import ConceptMasteryHistory\n\n\n"
        "class _MasteryRowView:\n"
        "    def __init__(self, row):\n"
        "        self.mastery = row.mastery\n\n\n"
        "class _Rogue:\n"
        "    def __init__(self, row):\n"
        "        self.mastery = 1.0\n",
    )
    result = scanner.scan(synthetic)
    assert [v.scope for v in result.violations] == ["_Rogue.__init__"]


# ── 성공 방향 대조군 — "전부 위반" 과잉 수정을 막는다 ────────────────────────


def test_ignores_unrelated_confidence_field(scanner: ModuleType, synthetic: Path) -> None:
    """숙달 좌석과 무관한 `.confidence` 대입은 위반이 아니다.

    `confidence`·`sample_size`는 저장소 전역에서 흔한 이름이다(오개념 가설의 신뢰도 등). 이름만
    보고 전부 막으면 사람이 면제를 남발하게 되고, 남발된 면제는 가드를 무력화한다.
    """
    _write(
        synthetic,
        "l4/misconception/hypothesis_store.py",
        "def persist(record):\n    record.confidence = 0.9\n",
    )
    result = scanner.scan(synthetic)
    assert result.violations == []


def test_ignores_model_definition_itself(scanner: ModuleType, synthetic: Path) -> None:
    """ORM 클래스 *정의*(컬럼 선언)는 쓰기가 아니다 — 대상이 `Name`이라 잡히지 않는다."""
    _write(
        synthetic,
        "db/models/assessment.py",
        "import sqlalchemy as sa\n"
        "from sqlalchemy.orm import Mapped, mapped_column\n\n\n"
        "class ConceptMasteryHistory:\n"
        "    mastery: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))\n"
        "    confidence: Mapped[float | None] = mapped_column(sa.Numeric(3, 2))\n",
    )
    result = scanner.scan(synthetic)
    assert result.violations == []


def test_allowances_carry_reasons(scanner: ModuleType) -> None:
    """모든 면제에 **이유**가 적혀 있다 — 이유 없는 면제는 리뷰 대상이 되지 못한다."""
    for allowance in scanner.ALLOWANCES:
        assert allowance.reason.strip(), f"{allowance.path}::{allowance.scope} 면제에 이유가 없다"
        assert len(allowance.reason) > 20, (
            f"{allowance.path}::{allowance.scope} 면제 이유가 한 줄도 안 된다"
        )


def test_allowance_axes_are_known(scanner: ModuleType) -> None:
    """면제의 축 이름이 스캐너가 실제로 내는 축과 일치한다(오탈자 면제 차단)."""
    known = {"construct", "assign", "bulk"}
    assert {a.axis for a in scanner.ALLOWANCES} <= known


def test_scanner_is_wired_into_ci(scanner: ModuleType) -> None:
    """이 가드가 **CI에서 실제로 돈다** — "저장소에 존재함"과 "돌아감"은 다르다.

    CLAUDE.md 「검증 장치를 만들고 배선 확인 없이 완료 선언 금지」의 이 태스크 몫이다.
    `infra-contracts` 잡은 `needs: changes` 게이팅이 없어 어떤 PR에서도 실행된다.
    """
    ci = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/analysis/mastery_write_path_scan.py" in ci, (
        "스캐너를 실행하는 CI 스텝이 없다 — 가드가 저장소에만 있고 돌지 않는다"
    )
    # 비차단(`|| true`·continue-on-error)으로 붙이면 실패해도 PR을 막지 못한다.
    step_line = next(
        line for line in ci.splitlines() if "mastery_write_path_scan.py" in line and "run:" in line
    )
    assert "|| true" not in step_line and "; true" not in step_line


def test_replace_keeps_allowance_frozen(scanner: ModuleType) -> None:
    """면제는 frozen dataclass다 — 런타임에 조용히 넓혀지지 않는다."""
    original = scanner.ALLOWANCES[0]
    widened = replace(original, scope="other")
    assert widened is not original
    with pytest.raises((AttributeError, TypeError)):
        original.scope = "other"  # type: ignore[misc]
