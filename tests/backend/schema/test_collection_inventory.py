"""user_profile 수집 항목 대장 계약 게이트 — ADMIN-09.

공유 계약 `data/collection_inventory.json`이 ORM `UserProfile`의 컬럼 집합·학생 입력 쓰기 경로
(`api/users.py::_SELF_EDITABLE`)·본인 조회 응답 제외 목록(`_PII_EXCLUDE`)·보존 계획
(`privacy/retention.py`)·**실제 코드의 컬럼 사용처**와 동기화돼 있는지 고정한다.
`access_matrix.json`↔`test_access_matrix.py`와 같은 패턴(순수 판정 함수 + 실제 대장 검사 + 합성
훼손으로 변별력 봉인) — 새 추상 없음.

**배경(실측, ①, 판정 기준 main `8a5ea4d1`, 2026-10-08)**: 이 테스트를 만들기 전 `gender`·
`school_region`·`school_id` 3컬럼을 조사한 결과 ORM(`db/models/user.py`)·Pydantic(`schema/user.py`)에
실재하는데 ⑴ API 수집 경로 0 — `_SELF_EDITABLE`에 없고 OAuth 콜백도 쓰지 않는다 ⑵ 런타임 읽기·쓰기
0 — `whymath_backend` 전체 .py를 AST로 스캔해 속성·생성 키워드·`getattr`/`get` 리터럴 참조가 0건
(주석·docstring 언급만 있다) ⑶ `docs/legal/pipa_data_matrix.md`에 컬럼 이름이 없다 ⑷ `data/
access_matrix.json`에 없다 — 후자는 학습 데이터 9항목의 노출 해상도 계약이지 프로필 수집 항목 계약이
아니다. 재현: `grep -nE "gender|school_region|school_id" docs/legal/pipa_data_matrix.md
data/access_matrix.json` → 0건. 같은 조사가 42컬럼 전체로 확장되며 **수집 경로는 열려 있는데 읽는 코드가
0인 컬럼이 9개**(`state=collected_unconsumed`) 더 드러났다 — 대장의 `state`가 그 목록이다.

⑶(문서 미등재)은 **부재 단언을 걸지 않는다** — "문서에 이 단어가 없다"를 영구 불변식으로 두면 훗날의
정당한 문서 보강(MGMT-02 처리방침 문안 등)을 막는 가짜 가드가 된다. 영속하는 형태는 아래 두 가지다:
대장이 그 컬럼을 `uncollected_unconsumed`로 선언하고(이 파일이 코드 스캔으로 대조) 누군가 읽는 코드를
추가하면 즉시 red, 그리고 `access_matrix.json`이 프로필 컬럼을 품지 않는다는 경계(⑷)는
`TestAccessMatrixBoundary`가 고정한다.

**검증 계약 (각 항목은 변별력이 확인된 것만 — 합성 훼손 클래스가 red/green을 실측)**
① ORM 컬럼 집합 == 대장 컬럼 집합 (양방향 — 신규 컬럼 무등재·유령 항목 모두 red)
② 항목 모양·어휘·파생 일관성 (collected↔origins · state↔(collected, consumed) · purpose none↔소비처 0)
③ `patch_users_me` 학생 입력 출처 == `_SELF_EDITABLE` (양방향) · `db_default` == ORM `server_default`
④ `identifier_hashed` 등급 == `_PII_EXCLUDE` (본인 조회 응답에서 빼는 목록과 동일)
⑤ 선언한 쓰기 경로의 소스가 그 컬럼을 실제로 참조 · 선언한 소비처가 그 컬럼을 실제로 참조
⑥ **무소비·무쓰기 주장의 코드 대조** — 소비처 0이라는 주장은 코드 전수 스캔에서 읽기 참조 0이어야 하고,
   출처가 없다는 주장은 쓰기 참조 0이어야 한다. 선언 안 된 파일의 쓰기 참조도 red(신규 수집 경로 감시)
⑦ 보존 계획이 `privacy/retention.py`의 현행 처분(MGMT-02 대기)과 연결 — 처분이 바뀌면 대장 재검토 강제

**정직한 공백 (기계가 보지 못하는 것)**
- 컬럼명이 다른 테이블과 겹치는 컬럼(`user_id`·`school_type`·`grade`·`role`·`created_at`·`is_active`·
  `deleted_at`, 계산으로 도출)은 이름만으로 `user_profile` 참조임을 알 수 없어, 무소비·무쓰기 대조는
  `UserProfile.<컬럼>` 클래스 속성 형태만 본다. 인스턴스 변수 접근(`user.deleted_at`)은 검증 밖이다.
- `UPDATE ... SET`·`update(UserProfile).values(...)` 대량 갱신은 AST만으로 대상 테이블을 알 수 없어
  쓰기 참조로 잡지 못한다(현행 사용 0건 — 도입되면 이 목록의 갱신 대상).
- `whymath_backend` 패키지 밖(`scripts/` 등)의 raw SQL 쓰기는 스캔 범위 밖이다.
- 소비처 목록은 존재 주장의 **대표 목록**이다 — 새 소비처가 생겨도 대장의 목록이 자동으로 늘지는
  않는다(빈 목록만 전수 주장). 소비처가 0→1이 되는 순간은 ⑥이 잡는다.
- `pii_grade`·`purpose`·`retention`의 법적 적정성은 이 테스트가 판정하지 않는다(MGMT-02 소관).
"""

from __future__ import annotations

import ast
import json
from collections.abc import Collection, Mapping
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

import sqlalchemy as sa

from whymath_backend.api.users import _PII_EXCLUDE, _SELF_EDITABLE
from whymath_backend.db import models as _all_models  # noqa: F401  # Base.metadata 등록용
from whymath_backend.db.base import Base
from whymath_backend.db.models.user import UserProfile
from whymath_backend.privacy import retention

# tests/backend/schema/ → parents[3] = 레포 루트(test_access_matrix.py와 동일 기준).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE = _PROJECT_ROOT / "data" / "collection_inventory.json"
_ACCESS_MATRIX = _PROJECT_ROOT / "data" / "access_matrix.json"
_PKG = _PROJECT_ROOT / "src" / "backend" / "whymath_backend"

_TABLE = "user_profile"
# 컬럼이 *선언*으로 등장하는 정의 파일 — 사용처 스캔에서 제외한다.
_DEFINITION_FILES = frozenset({"db/models/user.py", "schema/user.py"})
# user_profile 값을 만드는 생성자 이름(ORM·Pydantic 스키마). 키워드 인자를 쓰기 참조로 센다.
_PROFILE_CTORS = frozenset({"UserProfile", "SchemaUserProfile", "UserProfileSchema"})
# 문자열 리터럴로 컬럼을 읽는 호출 이름.
_LITERAL_READ_CALLS = frozenset({"getattr", "hasattr", "get", "pop", "setdefault"})
# 영속 경로가 아닌 쓰기 참조(인메모리 객체 조립)를 허용하는 파일 — 사유 필수(무사유 예외 금지).
_NON_PERSISTING_WRITERS: Mapping[str, str] = {
    "harness/attempt_skill_reach_probe.py": "프로브용 인메모리 UserProfileSchema 조립 — DB에 쓰지 않는다",
}
# 스캔 하한 — 대상 0건·급감을 "위반 0 통과"로 위장하지 않는다(2026-10-08 실측 740개).
_MIN_SCANNED_FILES = 400

_REQUIRED_COLUMN_KEYS = frozenset(
    {"pii_grade", "collected", "origins", "purpose", "runtime_consumers", "retention", "state"}
)
_OPTIONAL_COLUMN_KEYS = frozenset({"note"})
_PATH_KINDS = frozenset({"http", "ops_cli", "system"})
_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "note",
        "authority",
        "measured",
        "consumers_of_this_file",
        "out_of_scope",
        "vocab",
        "collection_paths",
        "retention_plans",
        "whole_row_readers",
        "columns",
    }
)


def _load_inventory() -> dict[str, Any]:
    """대장 로드 — 없거나 깨졌으면 skip이 아니라 수집 단계에서 예외로 실패한다(측정 실패 ≠ 통과)."""
    loaded: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return loaded


_INVENTORY = _load_inventory()
_COLUMNS: dict[str, Any] = _INVENTORY["columns"]
_PATHS: dict[str, Any] = _INVENTORY["collection_paths"]
_VOCAB: dict[str, Any] = _INVENTORY["vocab"]


def _clone(obj: Any) -> Any:
    """깊은 복사 — 합성 훼손은 항상 복사본에만 가한다(원본 대장·전역 상태 불변)."""
    return json.loads(json.dumps(obj))


def _orm_column_names() -> frozenset[str]:
    return frozenset(col.key for col in sa.inspect(UserProfile).mapper.column_attrs)


def _orm_server_default_columns() -> frozenset[str]:
    return frozenset(
        col.key
        for col in sa.inspect(UserProfile).mapper.column_attrs
        if col.columns[0].server_default is not None
    )


def _ambiguous_columns(orm_columns: Collection[str]) -> frozenset[str]:
    """다른 테이블에도 같은 이름의 컬럼이 있는 컬럼 — 이름만으로는 user_profile 참조를 모른다."""
    elsewhere = {
        col.name
        for table in Base.metadata.tables.values()
        if table.name != _TABLE
        for col in table.columns
    }
    return frozenset(name for name in orm_columns if name in elsewhere)


# ──────────────────────────────────────────────────────────────────────────
# AST 참조 탐지기 — 주석·docstring·변수명 같은 비코드 언급을 참조로 세지 않는다
# ──────────────────────────────────────────────────────────────────────────
class Ref(NamedTuple):
    file: str  # whymath_backend 기준 상대 경로(posix)
    line: int
    column: str
    kind: str  # "read" | "write" | "literal"(읽기·쓰기를 가릴 수 없는 리터럴 키)
    on_model: bool  # `UserProfile.<컬럼>` 클래스 속성이거나 UserProfile 생성 키워드인가


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _str_const(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _scan_refs(source: str, rel: str, columns: Collection[str]) -> list[Ref]:
    """소스 한 파일에서 컬럼 참조를 분류한다 — 순수 함수(디스크 미접근, 인자만 본다).

    - `x.col`(Load) → read · `x.col = ...`(Store/Del) → write — 값이 이름 `UserProfile`이면 on_model
    - `UserProfile(col=...)`류 생성 키워드 → write(on_model)
    - `setattr(x, "col", ...)` → write · `getattr/hasattr/.get/.pop(...)`의 문자열 인자 → read
    - `x["col"]` → literal(지역 딕셔너리일 수 있어 읽기·쓰기를 가릴 수 없다)
    """
    wanted = frozenset(columns)
    refs: list[Ref] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in wanted:
            kind = "read" if isinstance(node.ctx, ast.Load) else "write"
            on_model = isinstance(node.value, ast.Name) and node.value.id == "UserProfile"
            refs.append(Ref(rel, node.lineno, node.attr, kind, on_model))
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _PROFILE_CTORS:
                for kw in node.keywords:
                    if kw.arg in wanted:
                        refs.append(Ref(rel, kw.value.lineno, str(kw.arg), "write", True))
            if name == "setattr" and len(node.args) >= 2:
                target = _str_const(node.args[1])
                if target in wanted:
                    refs.append(Ref(rel, node.lineno, str(target), "write", False))
            if name in _LITERAL_READ_CALLS:
                for arg in node.args:
                    literal = _str_const(arg)
                    if literal in wanted:
                        refs.append(Ref(rel, node.lineno, str(literal), "read", False))
        elif isinstance(node, ast.Subscript):
            literal = _str_const(node.slice)
            if literal in wanted:
                refs.append(Ref(rel, node.lineno, str(literal), "literal", False))
    return refs


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _str_const(body[0].value) is not None:
                ids.add(id(body[0].value))
    return ids


def _mentions(source: str, column: str) -> bool:
    """코드가 컬럼을 어떤 형태로든 참조하는가 — 존재 주장(소비처·쓰기 경로) 검증용 느슨한 판정.

    속성·생성 키워드·이름·문자열 리터럴 중 하나면 참조로 본다. 주석은 AST에 없고 docstring은
    제외한다 — "언급"과 "참조"를 가른다(무소비 주장을 검증하는 `_scan_refs`와 달리 느슨해도 안전한
    이유: 이쪽은 '있다'는 주장만 확인하고 '없다'는 주장은 확인하지 않는다).
    """
    tree = ast.parse(source)
    skip = _docstring_constant_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == column:
            return True
        if isinstance(node, ast.keyword) and node.arg == column:
            return True
        if isinstance(node, ast.Name) and node.id == column:
            return True
        if isinstance(node, ast.Constant) and node.value == column and id(node) not in skip:
            return True
    return False


@cache
def _scan_package() -> tuple[int, dict[str, tuple[Ref, ...]]]:
    """`whymath_backend` 전체 .py를 한 번 스캔 → (스캔 파일 수, 컬럼명 → 참조들).

    파싱 실패는 삼키지 않는다(예외 전파) — 못 읽은 파일을 "참조 0"으로 계상하면 무소비 주장이
    위장 통과한다. 결과는 프로세스 내 캐시(읽기 전용 튜플).
    """
    columns = _orm_column_names()
    by_column: dict[str, list[Ref]] = {name: [] for name in columns}
    scanned = 0
    for path in sorted(_PKG.rglob("*.py")):
        rel = path.relative_to(_PKG).as_posix()
        if rel in _DEFINITION_FILES:
            continue
        scanned += 1
        for ref in _scan_refs(path.read_text(encoding="utf-8"), rel, columns):
            by_column[ref.column].append(ref)
    return scanned, {name: tuple(refs) for name, refs in by_column.items()}


# ──────────────────────────────────────────────────────────────────────────
# 판정 함수 — 전부 순수(전역/디스크 미접근 또는 인자로 받은 루트만). 합성 훼손이 직접 호출한다
# ──────────────────────────────────────────────────────────────────────────
def _column_set_violations(
    orm_columns: Collection[str], ledger_columns: Collection[str]
) -> list[str]:
    """① ORM 컬럼 집합 ↔ 대장 컬럼 집합 — 양방향."""
    violations: list[str] = []
    orm, ledger = set(orm_columns), set(ledger_columns)
    for name in sorted(orm - ledger):
        violations.append(
            f"ORM 컬럼 '{name}'이 대장(columns)에 등재돼 있지 않음 — 수집 항목 미등재"
        )
    for name in sorted(ledger - orm):
        violations.append(f"대장에만 있는 유령 항목 '{name}' — ORM UserProfile에 그런 컬럼이 없음")
    return violations


def _shape_violations(inv: Mapping[str, Any]) -> list[str]:
    """② 항목 모양·어휘·파생 일관성."""
    violations: list[str] = []
    missing_top = _TOP_LEVEL_KEYS - set(inv)
    if missing_top:
        violations.append(f"대장 최상위 키 누락: {sorted(missing_top)}")
        return violations
    vocab, paths, plans = inv["vocab"], inv["collection_paths"], inv["retention_plans"]
    grades, origin_names = set(vocab["pii_grades"]), set(vocab["origins"])
    collecting = set(vocab["collecting_origins"])
    states = set(vocab["states"])
    if not collecting <= origin_names:
        violations.append(
            f"collecting_origins가 origins 어휘 밖: {sorted(collecting - origin_names)}"
        )
    for path_id, path in paths.items():
        if path.get("kind") not in _PATH_KINDS:
            violations.append(
                f"경로 '{path_id}': kind {path.get('kind')!r}가 어휘 {sorted(_PATH_KINDS)} 밖"
            )
        for key in ("endpoint", "source", "note"):
            if not str(path.get(key, "")).strip():
                violations.append(f"경로 '{path_id}': '{key}'가 비어 있음")
    for name, entry in inv["columns"].items():
        keys = set(entry)
        if not _REQUIRED_COLUMN_KEYS <= keys:
            violations.append(f"{name}: 필수 키 누락 {sorted(_REQUIRED_COLUMN_KEYS - keys)}")
            continue
        extra = keys - _REQUIRED_COLUMN_KEYS - _OPTIONAL_COLUMN_KEYS
        if extra:
            violations.append(f"{name}: 알 수 없는 키 {sorted(extra)}")
        if entry["pii_grade"] not in grades:
            violations.append(f"{name}: pii_grade {entry['pii_grade']!r}가 어휘 밖")
        origins = entry["origins"]
        if not isinstance(origins, dict):
            violations.append(f"{name}: origins가 객체가 아님")
            continue
        for origin, path_ids in origins.items():
            if origin not in origin_names:
                violations.append(f"{name}: origin {origin!r}가 어휘 밖")
            if not isinstance(path_ids, list) or not path_ids:
                violations.append(
                    f"{name}: origin '{origin}'의 경로 목록이 비어 있거나 목록이 아님"
                )
                continue
            if len(set(path_ids)) != len(path_ids):
                violations.append(f"{name}: origin '{origin}'에 중복 경로")
            for path_id in path_ids:
                if path_id not in paths:
                    violations.append(f"{name}: 알 수 없는 경로 id {path_id!r}")
        derived_collected = any(origin in collecting for origin in origins)
        if entry["collected"] is not derived_collected:
            violations.append(
                f"{name}: collected={entry['collected']!r}인데 origins로 파생한 값은 {derived_collected!r}"
            )
        consumers = entry["runtime_consumers"]
        if not isinstance(consumers, list):
            violations.append(f"{name}: runtime_consumers가 목록이 아님")
            continue
        refs = [c.get("ref") for c in consumers if isinstance(c, dict)]
        if len(refs) != len(consumers):
            violations.append(f"{name}: runtime_consumers에 객체가 아닌 항목")
        if len(set(refs)) != len(refs):
            violations.append(f"{name}: runtime_consumers에 같은 ref 중복")
        for consumer in consumers:
            if isinstance(consumer, dict) and not all(
                str(consumer.get(k, "")).strip() for k in ("ref", "use")
            ):
                violations.append(f"{name}: 소비처 항목의 ref/use가 비어 있음: {consumer!r}")
        derived_state = (
            f"{'collected' if derived_collected else 'uncollected'}_"
            f"{'consumed' if consumers else 'unconsumed'}"
        )
        if entry["state"] not in states:
            violations.append(f"{name}: state {entry['state']!r}가 어휘 밖")
        elif entry["state"] != derived_state:
            violations.append(f"{name}: state={entry['state']!r}인데 파생값은 {derived_state!r}")
        purpose = str(entry["purpose"]).strip()
        if not purpose:
            violations.append(f"{name}: purpose가 비어 있음 — 소비처가 없으면 'none'이라고 적는다")
        elif consumers and purpose == "none":
            violations.append(f"{name}: 소비처가 있는데 purpose가 'none'")
        elif not consumers and purpose != "none":
            violations.append(
                f"{name}: 소비처가 없는데 purpose가 {purpose!r} — 가짜 목적 문구 금지"
            )
        if entry["retention"] not in plans:
            violations.append(f"{name}: retention {entry['retention']!r}가 retention_plans에 없음")
        if "note" in entry and not str(entry["note"]).strip():
            violations.append(f"{name}: note가 있는데 비어 있음")
    return violations


def _self_editable_violations(
    columns: Mapping[str, Any], self_editable: Collection[str], orm_columns: Collection[str]
) -> list[str]:
    """③-a 학생 입력 출처(patch_users_me) ↔ `_SELF_EDITABLE` — 양방향 + 화이트리스트 유령."""
    violations: list[str] = []
    declared = {
        name
        for name, entry in columns.items()
        if "patch_users_me" in entry["origins"].get("user_input", [])
    }
    whitelist = set(self_editable)
    for name in sorted(whitelist - declared):
        violations.append(
            f"PATCH 화이트리스트에 '{name}'가 열려 있는데 대장이 user_input/patch_users_me로 선언하지 않음"
        )
    for name in sorted(declared - whitelist):
        violations.append(
            f"대장이 '{name}'를 user_input/patch_users_me로 선언하나 화이트리스트에 없음"
        )
    for name in sorted(whitelist - set(orm_columns)):
        violations.append(f"화이트리스트 항목 '{name}'이 ORM 컬럼이 아님 — 유령 수집 경로")
    return violations


def _server_default_violations(
    columns: Mapping[str, Any], server_default_columns: Collection[str]
) -> list[str]:
    """③-b `db_default` 출처 ↔ ORM `server_default` — 양방향."""
    violations: list[str] = []
    declared = {
        name
        for name, entry in columns.items()
        if "db_default" in entry["origins"].get("system_generated", [])
    }
    actual = set(server_default_columns)
    for name in sorted(actual - declared):
        violations.append(
            f"ORM이 '{name}'에 server_default를 두는데 대장이 db_default로 선언하지 않음"
        )
    for name in sorted(declared - actual):
        violations.append(f"대장이 '{name}'를 db_default로 선언하나 ORM에 server_default가 없음")
    return violations


def _pii_exclusion_violations(
    columns: Mapping[str, Any], pii_exclude: Collection[str], whole_row_readers: Mapping[str, Any]
) -> list[str]:
    """④ identifier_hashed 등급 == `_PII_EXCLUDE` == 본인 조회 경로 제외 목록."""
    violations: list[str] = []
    hashed = {name for name, entry in columns.items() if entry["pii_grade"] == "identifier_hashed"}
    excluded = set(pii_exclude)
    for name in sorted(hashed - excluded):
        violations.append(
            f"'{name}'은 identifier_hashed인데 본인 조회 응답 제외 목록(_PII_EXCLUDE)에 없음"
        )
    for name in sorted(excluded - hashed):
        violations.append(f"_PII_EXCLUDE의 '{name}'이 대장에서 identifier_hashed가 아님")
    get_me = [p for p in whole_row_readers["paths"] if p["endpoint"] == "GET /v1/users/me"]
    if len(get_me) != 1:
        violations.append(
            f"whole_row_readers에 GET /v1/users/me가 정확히 1건이어야 함(현재 {len(get_me)}건)"
        )
    elif set(get_me[0]["excludes"]) != excluded:
        violations.append(
            f"whole_row_readers의 GET /v1/users/me.excludes {sorted(get_me[0]['excludes'])}가 "
            f"_PII_EXCLUDE {sorted(excluded)}와 다름"
        )
    return violations


def _source_file_violations(inv: Mapping[str, Any], pkg_root: Path) -> list[str]:
    """⑤-a 경로·전체행 읽기 경로의 source 파일 실재."""
    violations: list[str] = []
    for path_id, path in inv["collection_paths"].items():
        if not (pkg_root / path["source"]).is_file():
            violations.append(f"경로 '{path_id}': source '{path['source']}'가 실재하지 않음")
    for reader in inv["whole_row_readers"]["paths"]:
        if not (pkg_root / reader["source"]).is_file():
            violations.append(
                f"전체행 읽기 '{reader['endpoint']}': source '{reader['source']}' 부재"
            )
    plan_source = inv["retention_plans"]["account_row"]["source"]
    if not (pkg_root / plan_source).is_file():
        violations.append(f"retention_plans.account_row.source '{plan_source}' 부재")
    return violations


def _path_reference_violations(inv: Mapping[str, Any], pkg_root: Path) -> list[str]:
    """⑤-b 선언한 쓰기 경로의 소스가 그 컬럼을 실제로 참조 — 허위 경로 선언 차단.

    `system` 종류(db_default)는 코드 참조가 없는 게 정상이라 대상이 아니다(③-b가 ORM과 대조).
    """
    violations: list[str] = []
    for name, entry in inv["columns"].items():
        for origin, path_ids in entry["origins"].items():
            for path_id in path_ids:
                path = inv["collection_paths"].get(path_id)
                if path is None or path["kind"] == "system":
                    continue
                source_file = pkg_root / path["source"]
                if not source_file.is_file():
                    continue  # 부재는 _source_file_violations가 보고한다
                if not _mentions(source_file.read_text(encoding="utf-8"), name):
                    violations.append(
                        f"{name}: origin '{origin}'의 경로 '{path_id}' 소스 {path['source']}가 "
                        "그 컬럼을 참조하지 않음 — 허위 경로 선언"
                    )
    return violations


def _consumer_violations(inv: Mapping[str, Any], pkg_root: Path) -> list[str]:
    """⑤-c 선언한 소비처가 파일로 실재하고 그 컬럼을 실제로 참조 — 존재 주장 검증."""
    violations: list[str] = []
    for name, entry in inv["columns"].items():
        for consumer in entry["runtime_consumers"]:
            target = pkg_root / consumer["ref"]
            if not target.is_file():
                violations.append(f"{name}: 소비처 '{consumer['ref']}'가 실재하지 않음")
            elif not _mentions(target.read_text(encoding="utf-8"), name):
                violations.append(
                    f"{name}: 소비처 '{consumer['ref']}'가 그 컬럼을 참조하지 않음 — 허위 소비처 선언"
                )
    return violations


def _negative_claim_violations(
    inv: Mapping[str, Any],
    refs_by_column: Mapping[str, Collection[Ref]],
    ambiguous: Collection[str],
) -> list[str]:
    """⑥-a 무소비·무쓰기 주장의 코드 대조.

    - `runtime_consumers == []` → 읽기·리터럴 참조 0 (이름이 겹치는 컬럼은 `UserProfile.<컬럼>`만)
    - `origins`에 쓰기 출처가 없음(`{}`) → 쓰기 참조 0 (리터럴은 읽기·쓰기를 가릴 수 없어 제외)
    """
    violations: list[str] = []
    ambiguous_set = set(ambiguous)
    for name, entry in inv["columns"].items():
        refs = [
            ref for ref in refs_by_column.get(name, ()) if name not in ambiguous_set or ref.on_model
        ]
        if not entry["runtime_consumers"]:
            for ref in refs:
                if ref.kind in {"read", "literal"}:
                    violations.append(
                        f"{name}: 대장은 소비처 0인데 {ref.file}:{ref.line}에 {ref.kind} 참조가 있음"
                    )
        if not entry["origins"]:
            for ref in refs:
                if ref.kind == "write":
                    violations.append(
                        f"{name}: 대장은 쓰는 경로 0인데 {ref.file}:{ref.line}에 write 참조가 있음"
                    )
    return violations


def _write_completeness_violations(
    inv: Mapping[str, Any],
    refs_by_column: Mapping[str, Collection[Ref]],
    ambiguous: Collection[str],
    non_persisting: Mapping[str, str],
) -> list[str]:
    """⑥-b 선언 안 된 파일의 쓰기 참조 — 신규 수집 경로가 대장 없이 열리는 것을 막는다.

    이름이 겹치는 컬럼은 건너뛴다(다른 테이블의 쓰기와 구분 불가). 쓰기 참조의 파일은 그 컬럼이
    선언한 경로들의 source 집합 또는 사유가 명시된 비영속 허용 목록 안에 있어야 한다.
    """
    violations: list[str] = []
    ambiguous_set = set(ambiguous)
    for name, entry in inv["columns"].items():
        if name in ambiguous_set:
            continue
        declared_sources = {
            inv["collection_paths"][path_id]["source"]
            for path_ids in entry["origins"].values()
            for path_id in path_ids
            if path_id in inv["collection_paths"]
        }
        for ref in refs_by_column.get(name, ()):
            if ref.kind != "write":
                continue
            if ref.file in declared_sources or ref.file in non_persisting:
                continue
            violations.append(
                f"{name}: {ref.file}:{ref.line}가 이 컬럼에 값을 쓰는데 대장에 그 경로가 선언돼 있지 않음 — "
                "신규 수집 경로면 collection_paths와 origins에 등재"
            )
    return violations


def _retention_violations(
    inv: Mapping[str, Any], exemptions: Mapping[str, str], expiry: Mapping[str, str]
) -> list[str]:
    """⑦ 보존 계획 ↔ `privacy/retention.py` 현행 처분."""
    violations: list[str] = []
    plan = inv["retention_plans"]["account_row"]
    if _TABLE not in exemptions:
        violations.append(
            "privacy/retention.py에 user_profile 처분 항목이 없음 — 보존 계획이 바뀌었으니 대장 재검토"
        )
    if expiry.get(_TABLE) != plan["owner_task"]:
        violations.append(
            f"retention.py의 user_profile 해소 태스크 {expiry.get(_TABLE)!r} ≠ 대장 owner_task "
            f"{plan['owner_task']!r} — 보존 계획의 소유자가 바뀌었으니 대장 재검토"
        )
    return violations


# ──────────────────────────────────────────────────────────────────────────
# 실제 대장 ↔ 실제 코드
# ──────────────────────────────────────────────────────────────────────────
class TestInventoryMatchesRealCode:
    def test_ledger_declares_the_user_profile_table(self) -> None:
        assert UserProfile.__tablename__ == _TABLE

    def test_orm_columns_and_ledger_columns_are_the_same_set(self) -> None:
        violations = _column_set_violations(_orm_column_names(), _COLUMNS)
        assert violations == [], "\n".join(violations)

    def test_orm_has_the_expected_scale(self) -> None:
        """하한 단언 — ORM이 비어 보이는 사고(잘못된 모델 import)를 '일치'로 위장하지 않는다."""
        assert len(_orm_column_names()) >= 30

    def test_no_shape_violations(self) -> None:
        violations = _shape_violations(_INVENTORY)
        assert violations == [], "\n".join(violations)

    def test_patch_whitelist_matches_declared_user_input(self) -> None:
        violations = _self_editable_violations(_COLUMNS, _SELF_EDITABLE, _orm_column_names())
        assert violations == [], "\n".join(violations)

    def test_server_default_columns_match_db_default_origin(self) -> None:
        violations = _server_default_violations(_COLUMNS, _orm_server_default_columns())
        assert violations == [], "\n".join(violations)

    def test_hashed_identifiers_match_the_response_exclusion_list(self) -> None:
        violations = _pii_exclusion_violations(
            _COLUMNS, _PII_EXCLUDE, _INVENTORY["whole_row_readers"]
        )
        assert violations == [], "\n".join(violations)

    def test_declared_source_files_exist(self) -> None:
        violations = _source_file_violations(_INVENTORY, _PKG)
        assert violations == [], "\n".join(violations)

    def test_declared_write_paths_really_reference_the_column(self) -> None:
        violations = _path_reference_violations(_INVENTORY, _PKG)
        assert violations == [], "\n".join(violations)

    def test_declared_consumers_really_reference_the_column(self) -> None:
        violations = _consumer_violations(_INVENTORY, _PKG)
        assert violations == [], "\n".join(violations)

    def test_retention_plan_matches_current_retention_disposition(self) -> None:
        violations = _retention_violations(
            _INVENTORY,
            retention._RETENTION_PLAN_EXEMPTIONS,
            retention._RETENTION_PLAN_EXEMPTION_EXPIRY,
        )
        assert violations == [], "\n".join(violations)


class TestNegativeClaimsMatchTheCode:
    """⑥ 무소비·무쓰기·무선언 쓰기 — 대장의 부정 주장을 코드 전수 스캔과 대조한다."""

    def test_scan_actually_covered_the_package(self) -> None:
        scanned, _ = _scan_package()
        assert scanned >= _MIN_SCANNED_FILES, (
            f"스캔 파일 {scanned}개 < 하한 {_MIN_SCANNED_FILES} — 대상 급감을 '참조 0'으로 위장하면 "
            "무소비 주장이 전부 공허하게 통과한다"
        )

    def test_detector_sees_known_real_references(self) -> None:
        """양성 대조 — 탐지기가 눈이 멀어 있으면 아래 부정 주장 검사가 전부 공허하게 통과한다."""
        _, by_column = _scan_package()
        email_hash_refs = by_column["email_hash"]
        assert any(r.file == "api/auth.py" and r.kind == "write" for r in email_hash_refs)
        assert any(
            r.file == "api/auth.py" and r.kind == "read" and r.on_model for r in email_hash_refs
        )
        assert any(r.file == "api/_auth.py" for r in by_column["is_minor"])
        assert any(r.file == "l2/target_progress.py" for r in by_column["target_exam_date"])

    def test_negative_claims_were_actually_checked(self) -> None:
        """무소비 주장 컬럼이 0개면 이 클래스의 검사가 공허하다 — 최소 규모를 단언한다."""
        no_consumer = [n for n, e in _COLUMNS.items() if not e["runtime_consumers"]]
        assert len(no_consumer) >= 10, f"무소비 주장 {len(no_consumer)}개 — 대장 훼손 의심"

    def test_ledger_negative_claims_hold_against_the_real_code(self) -> None:
        _, by_column = _scan_package()
        violations = _negative_claim_violations(
            _INVENTORY, by_column, _ambiguous_columns(_orm_column_names())
        )
        assert violations == [], "\n".join(violations)

    def test_no_undeclared_write_path_exists_in_the_real_code(self) -> None:
        _, by_column = _scan_package()
        violations = _write_completeness_violations(
            _INVENTORY, by_column, _ambiguous_columns(_orm_column_names()), _NON_PERSISTING_WRITERS
        )
        assert violations == [], "\n".join(violations)

    def test_non_persisting_writer_allowlist_has_no_dead_entries(self) -> None:
        """허용 목록의 파일이 실제로 쓰기 참조를 갖는지 — 사라진 파일의 죽은 예외를 남기지 않는다."""
        _, by_column = _scan_package()
        writer_files = {r.file for refs in by_column.values() for r in refs if r.kind == "write"}
        for rel, reason in _NON_PERSISTING_WRITERS.items():
            assert reason.strip(), f"{rel}: 허용 사유가 비어 있음"
            assert (
                rel in writer_files
            ), f"{rel}: 허용 목록에 있으나 더는 쓰기 참조가 없음 — 항목 삭제"

    def test_ambiguous_columns_are_computed_not_empty(self) -> None:
        """겹침 계산이 조용히 빈 집합을 내면 이름만으로 단정하는 위험한 검사가 된다."""
        ambiguous = _ambiguous_columns(_orm_column_names())
        assert {"user_id", "created_at"} <= ambiguous


class TestAccessMatrixBoundary:
    """⑷ 경계 고정 — access_matrix.json은 학습 데이터 9항목 계약이고 프로필 컬럼을 품지 않는다."""

    def test_access_matrix_items_are_not_profile_columns(self) -> None:
        matrix = json.loads(_ACCESS_MATRIX.read_text(encoding="utf-8"))
        assert len(matrix["items"]) == 9
        overlap = set(matrix["items"]) & set(_COLUMNS)
        assert overlap == set(), (
            f"access_matrix 항목 id가 user_profile 컬럼과 겹침: {sorted(overlap)} — 학습 데이터 노출 "
            "계약과 프로필 수집 항목 대장의 경계가 흐려졌다(둘은 다른 축이다)"
        )


# ──────────────────────────────────────────────────────────────────────────
# 변별력 — 훼손 주입 → red → 복원 → green (원본 대장·전역 상태는 건드리지 않는다)
# ──────────────────────────────────────────────────────────────────────────
class TestColumnSetDetectorIsDiscriminating:
    def test_baseline_is_clean(self) -> None:
        assert _column_set_violations(_orm_column_names(), _COLUMNS) == []

    def test_new_orm_column_without_ledger_entry_is_red(self) -> None:
        """신규 컬럼이 대장 등재 없이 추가되면 실패한다 — 이 태스크의 핵심 보호."""
        synthetic = set(_orm_column_names()) | {"favorite_color"}
        violations = _column_set_violations(synthetic, _COLUMNS)  # → red 실측
        assert any("favorite_color" in v and "등재" in v for v in violations), violations

    def test_removing_a_ledger_entry_is_red(self) -> None:
        broken = _clone(_COLUMNS)
        del broken["gender"]
        violations = _column_set_violations(_orm_column_names(), broken)  # → red 실측
        assert any("gender" in v for v in violations), violations
        assert _column_set_violations(_orm_column_names(), _COLUMNS) == []  # 원본 green 재확인

    def test_ghost_ledger_entry_is_red(self) -> None:
        broken = _clone(_COLUMNS)
        broken["ghost_column"] = broken["gender"]
        violations = _column_set_violations(_orm_column_names(), broken)  # → red 실측
        assert any("ghost_column" in v and "유령" in v for v in violations), violations


class TestShapeDetectorIsDiscriminating:
    def test_baseline_is_clean(self) -> None:
        assert _shape_violations(_INVENTORY) == []

    def _mutate(self, mutate: Any) -> list[str]:
        broken = _clone(_INVENTORY)
        mutate(broken["columns"])
        return _shape_violations(broken)

    def test_unknown_pii_grade_is_red(self) -> None:
        violations = self._mutate(lambda c: c["gender"].update(pii_grade="top_secret"))
        assert any("gender" in v and "pii_grade" in v for v in violations), violations

    def test_collected_contradicting_origins_is_red(self) -> None:
        violations = self._mutate(lambda c: c["gender"].update(collected=True))
        assert any("gender" in v and "collected" in v for v in violations), violations

    def test_collecting_origin_with_collected_false_is_red(self) -> None:
        violations = self._mutate(lambda c: c["grade"].update(collected=False))
        assert any("grade" in v and "collected" in v for v in violations), violations

    def test_state_contradicting_collected_and_consumers_is_red(self) -> None:
        violations = self._mutate(lambda c: c["gender"].update(state="collected_consumed"))
        assert any("gender" in v and "state" in v for v in violations), violations

    def test_fake_purpose_without_consumers_is_red(self) -> None:
        """소비처가 없는데 그럴듯한 목적 문구를 적으면 red — 가짜 목적 문구 금지."""
        violations = self._mutate(lambda c: c["gender"].update(purpose="맞춤 학습 추천"))
        assert any("gender" in v and "가짜 목적" in v for v in violations), violations

    def test_none_purpose_with_consumers_is_red(self) -> None:
        violations = self._mutate(lambda c: c["grade"].update(purpose="none"))
        assert any("grade" in v and "purpose" in v for v in violations), violations

    def test_unknown_path_id_is_red(self) -> None:
        violations = self._mutate(lambda c: c["grade"]["origins"].update(user_input=["nowhere"]))
        assert any("grade" in v and "nowhere" in v for v in violations), violations

    def test_unknown_retention_plan_is_red(self) -> None:
        violations = self._mutate(lambda c: c["gender"].update(retention="forever"))
        assert any("gender" in v and "retention" in v for v in violations), violations

    def test_missing_required_key_is_red(self) -> None:
        violations = self._mutate(lambda c: c["gender"].pop("purpose"))
        assert any("gender" in v and "필수 키" in v for v in violations), violations

    def test_duplicate_consumer_ref_is_red(self) -> None:
        def dup(columns: dict[str, Any]) -> None:
            columns["grade"]["runtime_consumers"].append(columns["grade"]["runtime_consumers"][0])

        violations = self._mutate(dup)
        assert any("grade" in v and "중복" in v for v in violations), violations


class TestWhitelistDetectorIsDiscriminating:
    def test_baseline_is_clean(self) -> None:
        assert _self_editable_violations(_COLUMNS, _SELF_EDITABLE, _orm_column_names()) == []

    def test_opening_a_new_collection_field_without_ledger_is_red(self) -> None:
        """PATCH 화이트리스트에 gender를 열면 대장이 모르는 수집 경로 — 즉시 red."""
        synthetic = set(_SELF_EDITABLE) | {"gender"}
        violations = _self_editable_violations(_COLUMNS, synthetic, _orm_column_names())
        assert any("gender" in v for v in violations), violations

    def test_closing_a_collection_field_without_ledger_is_red(self) -> None:
        synthetic = set(_SELF_EDITABLE) - {"grade"}
        violations = _self_editable_violations(_COLUMNS, synthetic, _orm_column_names())
        assert any("grade" in v for v in violations), violations

    def test_ghost_whitelist_entry_is_red(self) -> None:
        synthetic = set(_SELF_EDITABLE) | {"not_a_column"}
        violations = _self_editable_violations(_COLUMNS, synthetic, _orm_column_names())
        assert any("not_a_column" in v for v in violations), violations


class TestOtherSyncDetectorsAreDiscriminating:
    def test_server_default_added_without_ledger_is_red(self) -> None:
        synthetic = set(_orm_server_default_columns()) | {"nickname"}
        violations = _server_default_violations(_COLUMNS, synthetic)
        assert any("nickname" in v for v in violations), violations

    def test_server_default_removed_without_ledger_is_red(self) -> None:
        synthetic = set(_orm_server_default_columns()) - {"role"}
        violations = _server_default_violations(_COLUMNS, synthetic)
        assert any("role" in v for v in violations), violations

    def test_hashed_identifier_missing_from_response_exclusion_is_red(self) -> None:
        violations = _pii_exclusion_violations(
            _COLUMNS, set(_PII_EXCLUDE) - {"email_hash"}, _INVENTORY["whole_row_readers"]
        )
        assert any("email_hash" in v for v in violations), violations

    def test_extra_response_exclusion_is_red(self) -> None:
        violations = _pii_exclusion_violations(
            _COLUMNS, set(_PII_EXCLUDE) | {"nickname"}, _INVENTORY["whole_row_readers"]
        )
        assert any("nickname" in v for v in violations), violations

    def test_retention_disposition_removed_is_red(self) -> None:
        violations = _retention_violations(_INVENTORY, {}, {})
        assert len(violations) == 2, violations

    def test_retention_owner_changed_is_red(self) -> None:
        violations = _retention_violations(_INVENTORY, {_TABLE: "x"}, {_TABLE: "SOME-OTHER-TASK"})
        assert any("SOME-OTHER-TASK" in v for v in violations), violations

    def test_retention_baseline_with_matching_disposition_is_clean(self) -> None:
        """양성 대조 — 위 red들이 무차별 실패가 아님을 보인다."""
        owner = _INVENTORY["retention_plans"]["account_row"]["owner_task"]
        assert _retention_violations(_INVENTORY, {_TABLE: "x"}, {_TABLE: owner}) == []


class TestScanDetectorIsDiscriminating:
    """탐지기(`_scan_refs`)와 부정 주장 판정이 합성 소스에서 올바르게 red/green을 가른다."""

    def _claim_inventory(self, column: str, *, consumers: bool, origins: bool) -> dict[str, Any]:
        inv = _clone(_INVENTORY)
        entry = inv["columns"][column]
        entry["runtime_consumers"] = [{"ref": "api/_auth.py", "use": "x"}] if consumers else []
        entry["origins"] = {"user_input": ["patch_users_me"]} if origins else {}
        return inv

    def test_attribute_read_contradicts_no_consumer_claim(self) -> None:
        refs = _scan_refs("def f(profile):\n    return profile.gender\n", "x.py", ["gender"])
        inv = self._claim_inventory("gender", consumers=False, origins=False)
        violations = _negative_claim_violations(inv, {"gender": refs}, set())
        assert any("gender" in v and "read" in v for v in violations), violations

    def test_constructor_keyword_contradicts_no_origin_claim(self) -> None:
        refs = _scan_refs("def f():\n    return UserProfile(gender='x')\n", "x.py", ["gender"])
        inv = self._claim_inventory("gender", consumers=False, origins=False)
        violations = _negative_claim_violations(inv, {"gender": refs}, set())
        assert any("gender" in v and "write" in v for v in violations), violations

    def test_store_attribute_contradicts_no_origin_claim(self) -> None:
        refs = _scan_refs("def f(u):\n    u.gender = 'x'\n", "x.py", ["gender"])
        inv = self._claim_inventory("gender", consumers=True, origins=False)
        violations = _negative_claim_violations(inv, {"gender": refs}, set())
        assert any("gender" in v and "write" in v for v in violations), violations

    def test_getattr_and_dict_get_literals_are_reads(self) -> None:
        source = "def f(p, d):\n    a = getattr(p, 'gender')\n    return d.get('gender')\n"
        refs = _scan_refs(source, "x.py", ["gender"])
        assert [r.kind for r in refs] == ["read", "read"]

    def test_subscript_literal_contradicts_no_consumer_claim(self) -> None:
        refs = _scan_refs("def f(d):\n    return d['gender']\n", "x.py", ["gender"])
        inv = self._claim_inventory("gender", consumers=False, origins=False)
        violations = _negative_claim_violations(inv, {"gender": refs}, set())
        assert any("gender" in v for v in violations), violations

    def test_comment_docstring_and_event_name_are_not_references(self) -> None:
        """거짓 양성 대조 — 주석·docstring·이벤트 이름 상수는 참조가 아니다."""
        source = (
            '"""gender 컬럼은 쓰지 않는다."""\n'
            "# gender: 주석 언급\n"
            "GENDER_EVENT = 'gender'\n"
            "def f():\n"
            "    '''docstring도 gender 언급'''\n"
            "    return 1\n"
        )
        assert _scan_refs(source, "x.py", ["gender"]) == []

    def test_unrelated_object_attribute_is_flagged_only_when_name_is_unique(self) -> None:
        """이름이 겹치는 컬럼은 `UserProfile.<컬럼>`만 본다 — 다른 객체의 같은 이름 속성은 무시한다."""
        refs = _scan_refs("def f(row):\n    return row.role\n", "x.py", ["role"])
        inv = self._claim_inventory("role", consumers=False, origins=True)
        assert any("role" in v for v in _negative_claim_violations(inv, {"role": refs}, set()))
        assert _negative_claim_violations(inv, {"role": refs}, {"role"}) == []  # 겹침 → on_model만
        model_refs = _scan_refs("def f():\n    return UserProfile.role\n", "x.py", ["role"])
        assert _negative_claim_violations(inv, {"role": model_refs}, {"role"}) != []

    def test_undeclared_writer_file_is_red_and_allowlist_clears_it(self) -> None:
        refs = _scan_refs(
            "def f(u):\n    u.parent_consent_at = 1\n", "api/rogue.py", ["parent_consent_at"]
        )
        by_column = {"parent_consent_at": refs}
        violations = _write_completeness_violations(_INVENTORY, by_column, set(), {})
        assert any("api/rogue.py" in v for v in violations), violations  # → red 실측
        assert (
            _write_completeness_violations(
                _INVENTORY, by_column, set(), {"api/rogue.py": "인메모리"}
            )
            == []
        )  # 허용 목록 → green
        declared = _scan_refs(
            "def f(u):\n    u.parent_consent_at = 1\n", "api/users.py", ["parent_consent_at"]
        )
        assert (
            _write_completeness_violations(_INVENTORY, {"parent_consent_at": declared}, set(), {})
            == []
        )  # 선언된 경로 파일 → green

    def test_real_dormant_claim_is_red_once_a_consumer_appears(self) -> None:
        """실제 대장의 gender 무소비 주장 + 합성 읽기 참조 = red (실제 코드는 건드리지 않는다)."""
        _, real = _scan_package()
        assert (
            _negative_claim_violations(_INVENTORY, real, _ambiguous_columns(_orm_column_names()))
            == []
        )
        injected = dict(real)
        injected["gender"] = (
            *real["gender"],
            *_scan_refs("x = p.gender\n", "api/new.py", ["gender"]),
        )
        violations = _negative_claim_violations(
            _INVENTORY, injected, _ambiguous_columns(_orm_column_names())
        )
        assert any("gender" in v and "api/new.py" in v for v in violations), violations


class TestSourceReferenceDetectorsAreDiscriminating:
    """⑤ 허위 경로·허위 소비처 — 임시 디렉터리에 합성 패키지를 만들어 대조한다."""

    def _pkg(self, tmp_path: Path, files: dict[str, str]) -> Path:
        for rel, text in files.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return tmp_path

    def _inv(self, column: str, consumer_ref: str, path_source: str) -> dict[str, Any]:
        inv = _clone(_INVENTORY)
        inv["columns"] = {
            column: {
                "pii_grade": "quasi_identifier",
                "collected": True,
                "origins": {"user_input": ["p"]},
                "purpose": "x",
                "runtime_consumers": [{"ref": consumer_ref, "use": "x"}],
                "retention": "account_row",
                "state": "collected_consumed",
            }
        }
        inv["collection_paths"] = {
            "p": {"kind": "http", "endpoint": "e", "source": path_source, "note": "n"}
        }
        return inv

    def test_consumer_referencing_the_column_is_clean(self, tmp_path: Path) -> None:
        pkg = self._pkg(tmp_path, {"a.py": "def f(u):\n    return u.gender\n"})
        assert _consumer_violations(self._inv("gender", "a.py", "a.py"), pkg) == []

    def test_consumer_file_missing_is_red(self, tmp_path: Path) -> None:
        pkg = self._pkg(tmp_path, {"a.py": "x = 1\n"})
        violations = _consumer_violations(self._inv("gender", "ghost.py", "a.py"), pkg)
        assert any("ghost.py" in v and "실재하지 않음" in v for v in violations), violations

    def test_consumer_not_referencing_the_column_is_red(self, tmp_path: Path) -> None:
        pkg = self._pkg(tmp_path, {"a.py": '"""gender는 docstring에서만 언급"""\nx = 1\n'})
        violations = _consumer_violations(self._inv("gender", "a.py", "a.py"), pkg)
        assert any("a.py" in v and "허위 소비처" in v for v in violations), violations

    def test_false_write_path_declaration_is_red(self, tmp_path: Path) -> None:
        pkg = self._pkg(tmp_path, {"a.py": "x = 1\n"})
        violations = _path_reference_violations(self._inv("gender", "a.py", "a.py"), pkg)
        assert any("gender" in v and "허위 경로" in v for v in violations), violations

    def test_missing_path_source_is_red(self, tmp_path: Path) -> None:
        pkg = self._pkg(tmp_path, {"a.py": "x = 1\n"})
        inv = self._inv("gender", "a.py", "nowhere.py")
        inv["whole_row_readers"] = {"paths": []}
        inv["retention_plans"] = {"account_row": {"source": "a.py"}}
        violations = _source_file_violations(inv, pkg)
        assert any("nowhere.py" in v for v in violations), violations
