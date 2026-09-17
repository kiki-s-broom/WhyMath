"""`learner_state` 단일 쓰기 경로 동결 — AST 전수 스캔 (EOS-103 acceptance ③).

**무엇을 막는가**: `LearnerStateRecord`를 생성(`LearnerStateRecord(...)`)하거나 그 인스턴스의
컬럼에 대입(`record.curriculum_id = ...`)하는 코드가 `l2/learner_state_store.py` 밖에
생기는 것. 여러 모듈이 제각각 상태를 고치면 계획서 KPI 2(State Integrity)를 영원히 측정할
수 없다 — "누가 이 값을 바꿨는가"의 답이 N곳이 되는 순간 측정 대상 자체가 사라진다.

**왜 산문 규약이 아니라 AST인가**(CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"):
모듈 docstring에 "이 모듈만 쓴다"고 적는 것은 *선언*이고, 이 파일이 *집행*이다. 문자열
금지 목록(`grep "LearnerStateRecord("`)이 아니라 **구성된 결과**(AST 노드)를 본다 —
표기 변형(별칭 import·줄바꿈·주석)에서 뚫리지 않게 하기 위해서다(CLAUDE.md "금지 패턴 열거
대신 산출물 검사").

**스캔 0건은 실패**: 대상 파일을 하나도 못 찾으면 전수 가드가 공허하게 통과한다 —
`test_scan_actually_reached_sources`가 그 축을 막는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_SRC = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# 유일한 쓰기 소유자 — 이 파일만 `LearnerStateRecord`를 만들고 고칠 수 있다.
_WRITER_MODULE = _BACKEND_SRC / "l2" / "learner_state_store.py"

# ORM 정의 자신 — 클래스 선언이므로 쓰기가 아니다(대입도 클래스 본문의 `Mapped[...]` 선언).
_MODEL_MODULE = _BACKEND_SRC / "db" / "models" / "learner_state.py"

_ORM_CLASS = "LearnerStateRecord"

# 실제 컬럼명 — 대입 대상 판정에 쓴다. ORM 모듈이 정본이며 아래 상수와의 정합을
# `test_column_names_match_orm`이 대조한다(둘이 갈라지면 가드가 조용히 좁아진다).
_STATE_COLUMNS: frozenset[str] = frozenset(
    {
        "learner_id",
        "curriculum_id",
        "current_objective_id",
        "provisioned_at",
        "provisioned_by",
        "updated_at",
        "revision",
    }
)


def _python_sources() -> list[Path]:
    return sorted(_BACKEND_SRC.rglob("*.py"))


def _scanned_sources() -> list[Path]:
    """가드 대상 — 쓰기 소유자와 ORM 정의 자신은 제외한다."""
    excluded = {_WRITER_MODULE.resolve(), _MODEL_MODULE.resolve()}
    return [p for p in _python_sources() if p.resolve() not in excluded]


def _violations(path: Path) -> list[str]:
    """한 파일에서 `LearnerStateRecord` 생성·컬럼 대입을 찾아 사람이 읽을 문자열로."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(_REPO_ROOT)
    found: list[str] = []

    # 별칭 import 추적 — `from ... import LearnerStateRecord as LSR` 형태로 이름을 바꿔도 잡는다.
    aliases = {_ORM_CLASS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == _ORM_CLASS and alias.asname:
                    aliases.add(alias.asname)

    for node in ast.walk(tree):
        # ① 생성 — `LearnerStateRecord(...)` / `models.LearnerStateRecord(...)`
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None
            )
            if name in aliases:
                found.append(f"{rel}:{node.lineno} — {_ORM_CLASS} 생성")
        # ② 컬럼 대입 — `<무엇이든>.curriculum_id = ...` 중 상태 컬럼명에 해당하는 것.
        #    수신자 타입을 정적으로 알 수 없으므로 **컬럼 이름**으로 좁힌다. 오탐 가능성이
        #    있지만 그 방향이 옳다: 상태 컬럼과 같은 이름을 쓰는 다른 객체가 생기면 이 가드가
        #    한 번 멈춰 세우고 사람이 판정한다(놓치는 것보다 낫다).
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in _STATE_COLUMNS:
                    found.append(f"{rel}:{node.lineno} — .{target.attr} 대입")
    return found


def test_only_the_store_module_writes_learner_state() -> None:
    """`l2/learner_state_store.py` 밖에서 `LearnerStateRecord`를 만들거나 고치면 RED."""
    breaches = [v for path in _scanned_sources() for v in _violations(path)]
    assert not breaches, (
        f"learner_state 쓰기가 단일 경로를 벗어났다 {len(breaches)}건:\n"
        + "\n".join(f"  · {b}" for b in breaches)
        + "\n\n쓰기는 l2/learner_state_store.py의 provision_learner_state·"
        "apply_learner_state_mutation 둘뿐이다(EOS-103 acceptance ③). "
        "새 변경 축이 필요하면 LearnerStateMutation에 필드를 추가하라."
    )


def test_scan_actually_reached_sources() -> None:
    """스캔 0건은 실패 — 대상을 못 찾은 전수 가드는 공허하게 통과한다."""
    scanned = _scanned_sources()
    assert len(scanned) > 100, f"백엔드 소스 스캔이 {len(scanned)}건뿐이다 — 경로 규약이 깨졌다"
    assert _WRITER_MODULE.is_file(), f"쓰기 소유자 모듈이 없다: {_WRITER_MODULE}"
    assert _MODEL_MODULE.is_file(), f"ORM 모듈이 없다: {_MODEL_MODULE}"


def test_column_names_match_orm() -> None:
    """가드가 보는 컬럼 목록이 실제 ORM과 일치한다 — 갈라지면 가드가 조용히 좁아진다."""
    from whymath_backend.db.models.learner_state import LearnerStateRecord

    actual = {c.key for c in LearnerStateRecord.__table__.columns}
    assert actual == set(_STATE_COLUMNS), (
        f"ORM 컬럼과 가드 상수가 어긋났다 — ORM에만: {sorted(actual - _STATE_COLUMNS)} / "
        f"상수에만: {sorted(_STATE_COLUMNS - actual)}"
    )


def test_writer_module_is_the_only_one_importing_the_orm_for_writes() -> None:
    """ORM 클래스를 import하는 모듈 목록을 동결 — 새 import처가 생기면 사람이 판정한다.

    읽기 목적의 import도 여기서 한 번 걸린다(의도적) — `PersistedLearnerState`라는 읽기
    계약이 이미 있으므로, ORM을 직접 당겨가는 것은 경계를 새게 하는 신호다.
    """
    allowed = {
        Path("src/backend/whymath_backend/l2/learner_state_store.py"),
        Path("src/backend/whymath_backend/db/models/__init__.py"),
    }
    importers: set[Path] = set()
    for path in _python_sources():
        if path.resolve() == _MODEL_MODULE.resolve():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == _ORM_CLASS for a in node.names):
                importers.add(path.relative_to(_REPO_ROOT))
    unexpected = sorted(importers - allowed)
    assert not unexpected, (
        f"ORM 클래스 {_ORM_CLASS}를 직접 import하는 새 모듈: {unexpected}\n"
        "읽기는 load_learner_state/require_learner_state(PersistedLearnerState 반환)를 쓴다."
    )
