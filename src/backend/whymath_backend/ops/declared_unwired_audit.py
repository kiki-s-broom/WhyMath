"""선언≠배선 일반 탐지기 — 4축 정적 감사 (OPS-22).

왜 이 모듈이 있는가
------------------
이 저장소는 "만들고 입력을 잇지 않음"(무언가를 완비해 놓고 *그것을 실제로 부르는 쪽*을 잇지
않아, 코드가 존재한다는 사실이 "돌아간다"로 잘못 읽히는 사고)을 **반복**했다 — 시각화 공급원
적재 0행(`VIZ-01`) · OCR 배포 경로 양쪽 비활성(`NLP-01`, 그 태스크 notes가 자인하는 "3회차") ·
`/v1/me/next-problem` 개인화 입력 0행(`REC-01`, notes가 자인하는 "4·5회차") · 학습시간 집계
writer 0건(`COLLAB-03`) · 성장 증거 도달(`PED-06`) · admin family 축 등, **최소 6회**. 매번 대응은
*그 축 전용*의 사후 런타임 리포트였다(`recommendation_reach_report.py`·
`pedagogy_content_slot_reach_report.py`·`harness/visualization_reach_report.py`·
`harness/concept_reach_report.py`·`harness/assessment_seat_reach_report.py`).

이 모듈은 그 축들을 대체하지 않는다(이미 배선된 축은 각자 리포트가 더 정밀하게 본다).
대신 **아직 아무도 보지 않는 새 공급 표면**에서 같은 사고가 커밋 시점에 잡히도록, 4개
구조 축을 정적으로(DB 0·LLM 0·HTTP 0) 감사하는 **횡단 게이트**다:

    (a) HTTP 라우트  ↔ 테스트/클라이언트 호출
    (b) EventType 생산자 ↔ 소비자(쿼리 필터)
    (c) TimescaleDB 집계 테이블 writer ↔ reader
    (d) harness/ops CLI ↔ CI 실행(직접 + in-process import 전이)

판정 규약 — 미도달 *수*가 아니라 *미분류*가 실패다
-----------------------------------------------
미도달률 자체를 게이트로 걸면 즉시 영구 red다(콘텐츠 저작 API를 학생 앱이 안 부르는 것은
정상, 배치 생성기 CLI를 운영자가 손으로 돌리는 것도 정상). 그래서 이 게이트가 요구하는
것은 도달률이 아니라 **의도의 선언**이다:

    reached            공급 항목의 소비가 실측됨 — 자동 판정(대장 등재 불요)
    by-design:<사유>   소비자가 없는 것이 설계 의도 — **사유 문자열 필수**
    pending-task:<id>  미도달이나 백로그가 추적 중 — 유예(아래 그랜드파더 만료 계약)
    (선언 없음)        → **unclassified · exit 1**

그랜드파더 만료 계약 (`ARCH-25` 패턴 이식 — 유예의 조용한 영구화 차단)
--------------------------------------------------------------------
`pending-task:<id>`는 `backlog/tasks/<id>.yaml`이 **실재하고 `status != done`**일 때만 유효하다.
`ops/provenance_audit.py`(`ARCH-25`)의 `GrandfatherEntry` + `find_grandfather_expiry_violations`가
확립한 계약을 그대로 따른다 — 태스크가 사라지거나 done이 되면 그 항목은 `expired-waiver`로
exit 1(자동 해제는 아니다 — 유예를 걷으라는 신호일 뿐, 해제는 사람 판단). `backlog/`가 단일
진실 원천이므로 이 모듈은 새 대장 파일을 만들지 않고 `status` 필드만 `yaml.safe_load`로 읽는다.

이 규약의 예방 성질: **새 라우트/EventType/테이블/CLI를 추가하면 의도를 선언하기 전까지 CI가
red**다. `EVENT_DATA_CONTRACT ∪ _CONTRACT_EXEMPT == 전체`를 거버넌스 테스트로 고정한 기존
패턴(`schema/event_data_contract.py`)을 4축으로 확장한 것이며, 새 발명이 아니라 검증된 패턴의
이식이다.

이 모듈이 하지 않는 것
----------------------
활성화·배선 신설이 아니다(가시화와 차단만). 축별 기존 리포트를 대체하지 않는다(범위는
"아직 아무도 추적하지 않는 신규 축"). 미도달을 발견해도 고치지 않는다 — `NLP-01` ⑥·
`REC-01` ⑤와 동형("가시화까지, 활성화는 아니다").

라우트 추출 — 단일 진실 원천 승격 (재구현 금지)
-------------------------------------------------
`tests/backend/ops/test_slo_contract.py`가 원래 `_app_route_paths()`를 자체 정의했다. FastAPI
0.140부터 `include_router()`가 하위 라우트를 `app.routes`로 평탄화하지 않고 `_IncludedRouter`
래퍼 1개만 얹으므로(래퍼는 `path` 속성이 없고 `original_router`를 들고 있다), 순진하게
`app.routes`의 `path`만 모으면 `/v1/**` 전체가 통째로 누락된다 — 그 파일의 도크스트링이 실측
함정으로 기록해 두었다. 이 모듈의 `walk_routes`가 그 재귀 언랩의 **유일한 구현**이고,
`route_paths()`(경로만)·`app_route_entries()`(메서드+경로, 이 모듈의 HTTP 축 전용)가 둘 다
그 위에서 파생된다. `test_slo_contract.py`는 이제 `route_paths()`를 import해 쓴다(재구현 0).

수집기 파손 방어 (exit 2)
------------------------
정규식이 깨져 호출을 0건 수집하면 "전부 미도달"이 아니라 "모든 항목이 유예에 걸려 통과"로
위장될 수 있다. 각 축의 공급·소비 수에 하한을 두고, 미만이면 판정이 아니라 **입력
오류(exit 2)**로 실패한다(`ops.reach_audit`류 선례 — "성공/실패 양쪽에서 같은 값을 내는 검사는
검증이 아니라 위장"의 자기 적용).

사용:
    python -m whymath_backend.ops.declared_unwired_audit
    python -m whymath_backend.ops.declared_unwired_audit --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeGuard

import yaml

from whymath_backend.app import create_app
from whymath_backend.schema.enums import EventType

__all__ = [
    "AXIS_CLI",
    "AXIS_EVENT",
    "AXIS_HTTP",
    "AXIS_TIMESERIES",
    "AxisResult",
    "CollectorError",
    "ItemVerdict",
    "Report",
    "app_route_entries",
    "build_report",
    "consumed_event_types",
    "main",
    "produced_event_types",
    "render_report",
    "route_paths",
]

_EXIT_OK = 0
_EXIT_VIOLATIONS = 1
_EXIT_INPUT_ERROR = 2

_BY_DESIGN = "by-design:"
_PENDING_TASK = "pending-task:"

AXIS_HTTP = "http_routes"
AXIS_EVENT = "event_consumers"
AXIS_TIMESERIES = "timeseries_tables"
AXIS_CLI = "harness_clis"

# 수집기 파손 하한(exit 2) — 실측 대비 넉넉히 낮게 잡아 정상 변동에는 걸리지 않고 *추출기
# 자체가 깨진*(0건·한 자릿수) 경우만 잡는다. 실측(2026-08-07): 라우트 81·호출 400+·
# EventType 생산 6·타임시리즈 모델 3·CLI 45+.
_FLOORS: dict[str, int] = {
    "routes": 40,
    "callers": 50,
    "event_types": 3,
    "timeseries_models": 1,
    "clis": 20,
}


def repo_root() -> Path:
    """저장소 루트 — ops/ → whymath_backend/ → backend/ → src/ → repo root.

    `ops/provenance_audit.default_corpus_root`와 동일한 `parents[4]` 관용구.
    """
    return Path(__file__).resolve().parents[4]


class CollectorError(RuntimeError):
    """수집기 파손 — 판정이 아니라 입력 오류(exit 2). "0건 통과" 위장 방지."""


# ──────────────────────────────────────────────────────────────────────────
# 라우트 추출 — 단일 진실 원천(모듈 docstring "재구현 금지" 참조).
# ──────────────────────────────────────────────────────────────────────────


def walk_routes(routes: Iterable[object]) -> Iterator[object]:
    """FastAPI 0.140 lazy-include 래퍼(`_IncludedRouter`)를 재귀로 풀어 실제 라우트만 낸다."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:  # FastAPI 0.140 lazy include 래퍼
            yield from walk_routes(inner.routes)
            continue
        yield route


@lru_cache(maxsize=1)
def route_paths() -> frozenset[str]:
    """`create_app()`의 실제 라우트 *경로* 집합(메서드 무시) — 단일 진실 원천.

    `tests/backend/ops/test_slo_contract.py`가 이 함수를 import한다(OPS-04 SLO 런북의 "문서가
    안내하는 경로가 실재하는가" 검증). 그 파일이 자체 정의하던 `_app_route_paths()`를 여기로
    승격했다(OPS-22 — 함정을 두 곳에서 각자 풀지 않도록).
    """
    found: set[str] = set()
    for route in walk_routes(create_app().routes):
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            found.add(path)
    return frozenset(found)


@lru_cache(maxsize=1)
def app_route_entries() -> tuple[tuple[str, str], ...]:
    """`(method, path)` 표(정규화 전 원본 경로) — HTTP 축 전용(메서드까지 필요)."""
    found: set[tuple[str, str]] = set()
    for route in walk_routes(create_app().routes):
        path = getattr(route, "path", None)
        if not isinstance(path, str) or not path:
            continue
        methods = getattr(route, "methods", None) or ()
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:  # 프레임워크 자동 부가 — 소비 대상이 아니다
                continue
            found.add((str(method), path))
    return tuple(sorted(found))


# ──────────────────────────────────────────────────────────────────────────
# 경로 정규화 — 서버(`{problem_id}`)와 클라(dart `$problemId`/python f-string `{id}`)를 한 축으로.
# ──────────────────────────────────────────────────────────────────────────

_SERVER_PARAM = re.compile(r"\{[^}]*\}")
# dart 보간(`$var`·`${var}`) + python f-string 보간(`{var}`) — 둘 다 같은 토큰으로 접는다.
_CLIENT_PARAM = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\{[A-Za-z_][A-Za-z0-9_]*\}")
_PARAM_TOKEN = "{param}"


def normalize_server_path(path: str) -> str:
    return _SERVER_PARAM.sub(_PARAM_TOKEN, path)


def normalize_client_path(path: str) -> str:
    return _CLIENT_PARAM.sub(_PARAM_TOKEN, path)


def _strip_query(path: str) -> str:
    return path.split("?", 1)[0]


@lru_cache(maxsize=256)
def _template_pattern(server_path: str) -> re.Pattern[str]:
    """서버 라우트 템플릿(`/v1/problems/{problem_id}`) → 매칭용 정규식.

    호출부는 인터폴레이션(dart `$id`·python f-string `{id}` → 위에서 이미 `{param}`으로 접힘)
    또는 테스트가 즐겨 쓰는 **리터럴 더미 값**(`client.get("/v1/jobs/j1")`처럼 실제 세그먼트를
    그냥 박아 넣는 것) 둘 다로 나타난다. 정규화 문자열 동일 비교만으로는 후자를 놓치므로,
    `test_slo_contract.py`의 `_route_matches`와 동형 원리(템플릿 파라미터 자리를 `[^/]+`로
    풀어 패턴 매칭)를 여기서도 쓴다 — 그 함수 자체는 "문서 인용 경로가 실재하는가"라는 다른
    질문을 답하므로 재사용 대상이 아니고(재구현 금지 대상은 라우트 *추출* — 위 `route_paths`),
    이 매칭 방향(호출 인스턴스 → 템플릿)은 이 모듈 고유의 축이다.
    """
    escaped = re.escape(server_path).replace(r"\{", "{").replace(r"\}", "}")
    pattern = "^" + re.sub(r"\{[^/}]+\}", "[^/]+", escaped) + "$"
    return re.compile(pattern)


def _route_reached(method: str, server_path: str, callers: frozenset[tuple[str, str]]) -> bool:
    pattern = _template_pattern(server_path)
    return any(cmethod == method and pattern.match(cpath) for cmethod, cpath in callers)


# ──────────────────────────────────────────────────────────────────────────
# 축 1 — HTTP 라우트 ↔ 테스트/Flutter 클라이언트 호출
# ──────────────────────────────────────────────────────────────────────────

# dart: `_dio.<method><제네릭>(\n  '<path>', …)` — 메서드와 경로 사이에 제네릭 인자와 개행이
# 낄 수 있어 DOTALL 필수(`ops/reach_audit`류 실측 확인 사항).
_DART_CALL = re.compile(r"_dio\.(get|post|put|patch|delete)[^(]*\(\s*'([^']*)'", re.DOTALL)
# python 테스트: `<var>.<method>(f?"<path>...` — 대상은 실제 라우트 접두사로 제한(dict.get 등
# 무관 호출 오탐 방지).
_TEST_CLIENT_CALL = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_]*\.(get|post|put|patch|delete)\(\s*f?[\"'](/v1/[^\"']*|/health[^\"']*|/status[^\"']*)"
)
# `client.request("DELETE", "/v1/me", …)` 변형 — body를 실어야 하는 DELETE(예: 삭제권 confirmation
# 필드) 등 소수 케이스가 이 형태를 쓴다(`test_me_erasure.py` 실측).
_TEST_CLIENT_REQUEST_CALL = re.compile(
    r"\.request\(\s*[\"'](GET|POST|PUT|PATCH|DELETE)[\"']\s*,\s*f?[\"']"
    r"(/v1/[^\"']*|/health[^\"']*|/status[^\"']*)"
)


# ── 모듈 레벨 상수 경유 호출 (2026-08-10 OPS-25 정밀도 수정) ────────────────────────────
# 테스트는 경로를 `_ENDPOINT = "/v1/me/growth-evidence"` 같은 모듈 상수로 빼고
# `client.get(_ENDPOINT)`로 부르는 관용구를 즐겨 쓴다(실측 15파일 20상수). 리터럴 문자열만 보는
# 위 정규식은 그 호출을 통째로 못 봐서 **실재하지 않는 미도달**을 만들어냈다 — `PED-15`는 그
# 오탐 하나 때문에 등재된 유령 태스크였고(`test_me_growth_evidence.py`가 처음부터 그 라우트를
# 때리고 있었다), `POST /v1/ocr/pages`는 같은 한계를 자인하는 by-design 유예로 덮여 있었다.
#
# 추적 범위는 축 3의 `_insert_helpers`(모듈 내 헬퍼 1홉)와 **같은 절제**를 따른다: 같은 모듈
# 최상위에서 정의된 상수 1홉만 푼다. import된 상수·클래스 속성·조건부 재대입은 풀지 않는다 —
# 넓히면 이 감사기가 사실상 인터프리터가 되고, 못 잡는 경우는 미도달로 남아 대장 등재를
# 강제받으므로(안전 방향) 정직한 잔여로 두는 편이 낫다.
_HTTP_METHOD_ATTRS = frozenset({"get", "post", "put", "patch", "delete"})
_HTTP_METHOD_LITERALS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
# 위 `_TEST_CLIENT_CALL` 정규식과 동일한 접두 제한 — `payload.get(_SOME_KEY)` 같은 무관 호출이
# 라우트 도달로 새지 않게 하는 유일한 방어선이다(상수 경유는 인자 모양만으론 구분이 안 된다).
_PATH_PREFIXES = ("/v1/", "/health", "/status")


def _module_level_assignments(module: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    """모듈 **최상위**(들여쓰기 0) `NAME = <값>` / `NAME: T = <값>` 대입만 낸다.

    함수·클래스 몸통 안의 지역 대입은 내지 않는다 — "모듈 레벨 상수 1홉"이라는 범위 제한이
    이 정밀도 개선의 안전 장치이므로 수집 단계에서부터 지킨다.
    """
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            yield node.target.id, node.value


def _module_path_constants(module: ast.Module) -> dict[str, str]:
    """모듈 최상위 경로 문자열 상수 `이름 → 경로`(`/v1/`·`/health`·`/status` 접두만)."""
    found: dict[str, str] = {}
    for name, value in _module_level_assignments(module):
        if (
            isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and value.value.startswith(_PATH_PREFIXES)
        ):
            found[name] = value.value
    return found


def _resolve_path_expr(node: ast.expr, constants: dict[str, str]) -> str | None:
    """호출 인자 표현식 → 정규화 경로. 상수 이름과 *상수로 시작하는* f-string만 푼다.

    f-string은 `f"{_ENDPOINT}?limit=1"`(쿼리 덧붙임)·`f"{_BASE}/{jti}/end"`(하위 경로) 둘 다
    흔해서 접두 매칭까지 본다. 값을 모르는 보간은 `{param}`으로 접어 서버 템플릿 매칭에
    맡긴다(`_template_pattern`). 그 외 표현식(`+` 연결·`.format()`·`str()` 등)은 풀지 않고
    `None`을 돌려 미도달로 남긴다 — 못 잡는 것을 도달로 뭉개는 쪽이 더 나쁜 오류다.
    """
    if isinstance(node, ast.Name):
        raw = constants.get(node.id)
        return None if raw is None else normalize_client_path(_strip_query(raw))
    if not isinstance(node, ast.JoinedStr):
        return None
    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.FormattedValue):
            inner = value.value
            if isinstance(inner, ast.Name) and inner.id in constants:
                parts.append(constants[inner.id])
            else:
                parts.append(_PARAM_TOKEN)
        else:  # pragma: no cover - JoinedStr는 Constant|FormattedValue만 담는다
            return None
    joined = "".join(parts)
    if not joined.startswith(_PATH_PREFIXES):
        return None
    return normalize_client_path(_strip_query(joined))


def _constant_indirect_calls(
    module: ast.Module, constants: dict[str, str]
) -> Iterator[tuple[str, str]]:
    """`client.get(_ENDPOINT)`·`client.request("DELETE", _PATH)` 형태의 상수 경유 호출."""
    if not constants:
        return
    for node in ast.walk(module):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not node.args:
            continue
        attr = node.func.attr
        if attr in _HTTP_METHOD_ATTRS:
            path = _resolve_path_expr(node.args[0], constants)
            if path is not None:
                yield attr.upper(), path
        elif attr == "request" and len(node.args) >= 2:
            method = node.args[0]
            if not isinstance(method, ast.Constant) or not isinstance(method.value, str):
                continue
            if method.value.upper() not in _HTTP_METHOD_LITERALS:
                continue
            path = _resolve_path_expr(node.args[1], constants)
            if path is not None:
                yield method.value.upper(), path


def dart_call_entries(mobile_lib: Path) -> frozenset[tuple[str, str]]:
    """Flutter가 실제로 호출하는 `(METHOD, 정규화 경로)` 집합."""
    found: set[tuple[str, str]] = set()
    if not mobile_lib.is_dir():
        return frozenset(found)
    for source in sorted(mobile_lib.rglob("*.dart")):
        text = source.read_text(encoding="utf-8")
        for match in _DART_CALL.finditer(text):
            path = match.group(2)
            if not path.startswith("/"):
                continue
            found.add((match.group(1).upper(), normalize_client_path(_strip_query(path))))
    return frozenset(found)


def test_call_entries(tests_backend_root: Path) -> frozenset[tuple[str, str]]:
    """백엔드 테스트가 `TestClient`류로 실제로 호출하는 `(METHOD, 정규화 경로)` 집합.

    두 경로를 합친다 — ⑴ 리터럴 문자열 인자(정규식) ⑵ **모듈 레벨 경로 상수 1홉**(AST,
    `_constant_indirect_calls`). ⑵가 없던 탓에 상수 관용구를 쓰는 파일의 호출이 통째로
    사라져 실재하지 않는 미도달이 만들어졌다(OPS-25 — 위 상수 블록 주석 참조).
    """
    found: set[tuple[str, str]] = set()
    if not tests_backend_root.is_dir():
        return frozenset(found)
    for source in sorted(tests_backend_root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        text = source.read_text(encoding="utf-8")
        for match in _TEST_CLIENT_CALL.finditer(text):
            path = _strip_query(match.group(2))
            found.add((match.group(1).upper(), normalize_client_path(path)))
        for match in _TEST_CLIENT_REQUEST_CALL.finditer(text):
            path = _strip_query(match.group(2))
            found.add((match.group(1).upper(), normalize_client_path(path)))
        module = ast.parse(text, filename=str(source))
        found.update(_constant_indirect_calls(module, _module_path_constants(module)))
    return frozenset(found)


# ──────────────────────────────────────────────────────────────────────────
# 소스 순회 공용 유틸 — 축 2~4가 공유.
# ──────────────────────────────────────────────────────────────────────────


def _iter_python_sources(package_root: Path) -> list[Path]:
    return sorted(
        p
        for p in package_root.rglob("*.py")
        if "__pycache__" not in p.parts and not p.name.startswith(".")
    )


@lru_cache(maxsize=64)
def _parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_dotted_name(package_root: Path, source: Path) -> str:
    return source.relative_to(package_root).with_suffix("").as_posix().replace("/", ".")


# ──────────────────────────────────────────────────────────────────────────
# 축 2 — EventType 생산자(`build_event_data`) ↔ 소비자(쿼리 필터 비교)
# ──────────────────────────────────────────────────────────────────────────

_EVENT_CONTRACT_FILES = frozenset({"enums.py", "event_data_contract.py"})


def _event_type_names() -> frozenset[str]:
    return frozenset(member.name for member in EventType)


def _is_event_type_attr(node: ast.AST, names: frozenset[str]) -> TypeGuard[ast.Attribute]:
    """`EventType.X` 형태의 속성 접근인가 — `TypeGuard`로 좁혀 호출부의 `.attr` 접근을 mypy
    --strict가 안전하게 받아들이게 한다(narrowing 없이는 `ast.expr`에 `.attr`가 없다는 오류)."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr in names
        and isinstance(node.value, ast.Name)
        and node.value.id == "EventType"
    )


def produced_event_types(package_root: Path) -> frozenset[str]:
    """`build_event_data(EventType.X, …)`로 실제 생산되는 EventType 이름 집합.

    첫 인자가 `EventType.검산결과` 형태의 리터럴 속성 접근일 때만 AST로 잡힌다(변수로 우회하는
    호출은 없다 — 생겼다면 여기서 잡히지 않으므로 그 EventType은 미도달로 보고돼 대장 등재를
    강제받는다, 안전 방향).
    """
    names = _event_type_names()
    produced: set[str] = set()
    for source in _iter_python_sources(package_root):
        for node in ast.walk(_parse_module(source)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called != "build_event_data":
                continue
            first = node.args[0]
            if _is_event_type_attr(first, names):
                produced.add(first.attr)
    return frozenset(produced)


# 컨테이너 상수 생성자 — `frozenset({...})`·`set([...])`·`tuple((...))`·`list([...])`. 1겹만 푼다.
_EVENT_CONTAINER_FUNCS = frozenset({"frozenset", "set", "tuple", "list"})


def _event_type_elements(node: ast.expr, names: frozenset[str]) -> set[str]:
    """컨테이너 리터럴(또는 그것을 1겹 감싼 생성자 호출)에 담긴 `EventType.X` 원소 이름."""
    if isinstance(node, ast.Call):
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called in _EVENT_CONTAINER_FUNCS and len(node.args) == 1:
            return _event_type_elements(node.args[0], names)
        return set()
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return set()
    members: set[str] = set()
    for element in node.elts:
        if _is_event_type_attr(element, names):
            members.add(element.attr)
    return members


def _module_event_type_constants(
    module: ast.Module, names: frozenset[str]
) -> dict[str, frozenset[str]]:
    """모듈 최상위 `NAME = frozenset({EventType.A, …})` 류 상수 `이름 → EventType 이름들`.

    범위는 HTTP 축의 경로 상수와 동일하게 **모듈 최상위 1홉**으로 묶는다(`_insert_helpers` 선례).
    `tuple(EventType)`처럼 원소가 리터럴이 아닌 동적 구성은 풀지 않는다 — 미도달로 남아 대장
    등재를 강제받는 안전 방향이다.
    """
    found: dict[str, frozenset[str]] = {}
    for name, value in _module_level_assignments(module):
        members = _event_type_elements(value, names)
        if members:
            found[name] = frozenset(members)
    return found


def consumed_event_types(package_root: Path) -> frozenset[str]:
    """`AttemptEvent(ORM).event_type == EventType.X` 형태의 비교 필터로 실제 *읽히는* EventType.

    생산 좌석(`event_type=EventType.X` 키워드 인자·`build_event_data` 첫 인자)은 `ast.Compare`가
    아니므로 이 스캔에 잡히지 않는다 — 생산과 소비를 같은 AST 패턴으로 뭉개지 않기 위한 설계다.
    계약 정의 파일(`enums.py`·`event_data_contract.py`) 자신은 정의이지 소비가 아니라 제외한다.

    상수 간접참조 (2026-08-10 OPS-25 정밀도 수정)
    ---------------------------------------------
    필터가 EventType을 **모듈 상수 집합**으로 묶어 쓰는 관용구가 실재한다:
    `l2/learning_metrics_rollup.py`의 `_SOCRATIC_EVENT_TYPES = frozenset({EventType.막힘, …})`를
    `if event.event_type not in _SOCRATIC_EVENT_TYPES`(파이썬 필터)로 쓴다. `in`/`not in`도
    `ast.Compare`지만 피연산자가 `Name`이라 예전 구현은 못 봤고, 그래서 `EventType.막힘`이
    **이미 소비 중인데도** 미도달로 보고돼 `S4-22` 유예에 3종 중 1종이 허위로 끼어 있었다.
    이제 모듈 최상위 상수를 1홉 해석해 담긴 EventType들을 소비로 인정한다.
    """
    names = _event_type_names()
    consumed: set[str] = set()
    for source in _iter_python_sources(package_root):
        if source.name in _EVENT_CONTRACT_FILES:
            continue
        module = _parse_module(source)
        constants = _module_event_type_constants(module, names)
        for node in ast.walk(module):
            if not isinstance(node, ast.Compare):
                continue
            for operand in (node.left, *node.comparators):
                if _is_event_type_attr(operand, names):
                    consumed.add(operand.attr)
                elif isinstance(operand, ast.Name):
                    consumed.update(constants.get(operand.id, frozenset()))
    return frozenset(consumed)


# ──────────────────────────────────────────────────────────────────────────
# 축 3 — TimescaleDB 집계 테이블 ORM writer ↔ reader
# ──────────────────────────────────────────────────────────────────────────


def _timeseries_module_name(package_root: Path) -> str:
    """`<패키지>.db.models.timeseries` — 패키지명은 `package_root.name`에서 파생(하드코딩
    금지 — 테스트가 합성 패키지 트리(`fakepkg/db/models/timeseries.py`)로 이 축을 검증한다)."""
    return f"{package_root.name}.db.models.timeseries"


@dataclass(frozen=True, slots=True)
class TimeseriesUsage:
    writers: tuple[str, ...]
    readers: tuple[str, ...]


# `insert(Model)`·`pg_insert(Model)` — SQLAlchemy Core/PG 방언 insert 생성자. 이 저장소의 적재는
# ORM 인스턴스화보다 **멱등 upsert**(`INSERT ... ON CONFLICT DO UPDATE`)가 정본 관용구라
# (`l1/problem_bank/populate.py` 이하 15개 projection/loader 모듈), 생성자 호출만 보면 실제
# 적재 경로 대부분을 놓친다. 첫 위치 인자만 본다 — `list.insert(0, X)` 같은 동명 메서드 오탐 차단.
_INSERT_FUNC_NAMES = frozenset({"insert", "pg_insert"})


@dataclass(frozen=True, slots=True)
class _InsertHelper:
    """모델을 인자로 받아 insert 문을 만드는 *모듈 내 헬퍼*의 서명 요약.

    `l2/learning_metrics_rollup.py`의 `_upsert(session, orm_model, rows, …)`처럼 적재를 공통
    헬퍼로 빼는 관용구를 1-홉만 추적한다(전역 콜그래프 추적 아님 — 같은 모듈 안에서 정의되고
    호출되는 경우로 한정한다. 범위를 넓히면 이 감사기가 사실상 타입 추론기가 된다).
    """

    positional: tuple[str, ...]  # 위치 인자 순서의 파라미터 이름
    sinks: frozenset[str]  # 그 함수 안에서 insert 첫 인자로 흘러드는 파라미터 이름


def _insert_first_arg_name(node: ast.Call) -> str | None:
    """`insert(X)`/`pg_insert(X)`/`sa.insert(X)` 호출이면 첫 위치 인자의 `Name` id."""
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if called not in _INSERT_FUNC_NAMES or not node.args:
        return None
    first = node.args[0]
    return first.id if isinstance(first, ast.Name) else None


def _insert_helpers(module: ast.Module) -> dict[str, _InsertHelper]:
    """모듈이 정의한 함수 중 "파라미터로 받은 모델을 insert에 넘기는" 것들의 서명 요약."""
    helpers: dict[str, _InsertHelper] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        args = node.args
        positional = tuple(a.arg for a in (*args.posonlyargs, *args.args))
        param_names = set(positional) | {a.arg for a in args.kwonlyargs}
        if not param_names:
            continue
        sinks = {
            name
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            for name in (_insert_first_arg_name(child),)
            if name in param_names
        }
        if sinks:
            helpers[node.name] = _InsertHelper(positional=positional, sinks=frozenset(sinks))
    return helpers


def _forwarded_sink_args(node: ast.Call, helper: _InsertHelper) -> Iterator[ast.Name]:
    """헬퍼 호출부에서 *싱크 파라미터 자리*에 실제로 놓인 `Name` 인자만 낸다."""
    for index, arg in enumerate(node.args):
        if index < len(helper.positional) and helper.positional[index] in helper.sinks:
            if isinstance(arg, ast.Name):
                yield arg
    for keyword in node.keywords:
        if keyword.arg in helper.sinks and isinstance(keyword.value, ast.Name):
            yield keyword.value


def timeseries_models(package_root: Path) -> tuple[str, ...]:
    """`db/models/timeseries.py`가 선언한 ORM 모델 클래스명."""
    path = package_root / "db" / "models" / "timeseries.py"
    if not path.is_file():
        return ()
    module = _parse_module(path)
    return tuple(
        sorted(node.name for node in module.body if isinstance(node, ast.ClassDef) and node.bases)
    )


def timeseries_usage(package_root: Path, models: tuple[str, ...]) -> dict[str, TimeseriesUsage]:
    """모델명 → writer(생성 호출) 모듈·reader(그 외 참조) 모듈.

    ⚠️ 이름만 보면 안 된다 — `schema/timeseries.py`에 **동명의 Pydantic 클래스**가 있어서
    이름 기반 탐지는 스키마 사용을 ORM 적재로 오인한다. `db.models`(또는 그 서브모듈)에서
    import한 모듈만 대상으로 한다.

    별칭 import (2026-08-10 오탐 수정)
    ---------------------------------
    바로 그 동명 충돌 때문에 코드베이스는 `from ...db.models.timeseries import X as XORM`으로
    ORM 쪽에 별칭을 단다(`l2/learning_metrics_rollup.py`가 3모델 전부 그렇게 가져온다). 예전
    구현은 `alias.asname or alias.name`으로 **로컬명만** 모은 뒤 모델명 집합과 교집합을 냈으므로
    별칭이 붙은 순간 교집합이 비어 그 모듈을 통째로 건너뛰었다 — 감사기가 자기가 경고한 모호성의
    *해법*에 눈이 먼 상태였다. 이제 `로컬명 → 원래 모델명` 사전을 유지하고, 집계는 원래 이름으로
    한다. 부수 효과로 정밀도도 오른다: 같은 파일이 ORM은 `XORM`, Pydantic은 `X`로 가져오면
    로컬명 `X`는 사전에 없으므로 스키마 사용이 ORM 소비로 새지 않는다.

    writer 판정 (2026-08-10 오탐 수정)
    ----------------------------------
      ⑴ `Model(...)` 생성자 호출
      ⑵ `insert(Model)`·`pg_insert(Model)` — 이 저장소의 멱등 적재 정본 관용구
      ⑶ ⑵를 감싼 *모듈 내 헬퍼*에 모델을 인자로 넘기는 호출(`_upsert(session, ModelORM, …)`)
    ⑵·⑶이 없던 탓에 bulk upsert만 하는 writer는 전부 "적재 0"으로 오탐됐다.

    reader = 위 writer 자리를 뺀 나머지 `Name` 참조(예: `(DailyLearningMetrics, "user_id")`
    삭제·반출 계획 튜플처럼 나중에 `getattr(model, column)`으로 간접 사용하는 패턴도 포함).
    writer 자리의 참조를 reader로도 세면 "쓰기만 하고 아무도 안 읽는" 상태가 통과로 위장되므로
    제외한다.
    """
    model_set = set(models)
    writers: dict[str, set[str]] = {m: set() for m in models}
    readers: dict[str, set[str]] = {m: set() for m in models}
    timeseries_module = _timeseries_module_name(package_root)

    for source in _iter_python_sources(package_root):
        if source.parts[-3:-1] == ("db", "models"):
            continue  # 선언 자신은 소비가 아니다
        module = _parse_module(source)
        # 로컬명(별칭 포함) → 원래 모델명. 별칭을 원명으로 되돌리지 않으면 모듈을 통째로 놓친다.
        local_to_model: dict[str, str] = {}
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == timeseries_module or node.module.endswith("db.models"):
                    for alias in node.names:
                        if alias.name in model_set:
                            local_to_model[alias.asname or alias.name] = alias.name
        if not local_to_model:
            continue

        rel = _module_dotted_name(package_root, source)
        helpers = _insert_helpers(module)
        write_ref_ids: set[int] = set()  # writer 자리에 쓰인 Name 노드 — reader로 이중 계상 금지
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in local_to_model:  # ⑴ 생성자
                write_ref_ids.add(id(func))
                writers[local_to_model[func.id]].add(rel)
                continue
            first = _insert_first_arg_name(node)  # ⑵ 직접 insert/pg_insert
            if first is not None and first in local_to_model:
                write_ref_ids.add(id(node.args[0]))
                writers[local_to_model[first]].add(rel)
                continue
            helper = helpers.get(func.id) if isinstance(func, ast.Name) else None
            if helper is not None:  # ⑶ 모듈 내 insert 헬퍼로 모델 전달
                for arg in _forwarded_sink_args(node, helper):
                    if arg.id in local_to_model:
                        write_ref_ids.add(id(arg))
                        writers[local_to_model[arg.id]].add(rel)
        for node in ast.walk(module):
            if (
                isinstance(node, ast.Name)
                and node.id in local_to_model
                and id(node) not in write_ref_ids
            ):
                readers[local_to_model[node.id]].add(rel)

    return {
        m: TimeseriesUsage(writers=tuple(sorted(writers[m])), readers=tuple(sorted(readers[m])))
        for m in models
    }


# ──────────────────────────────────────────────────────────────────────────
# 축 4 — harness/ops CLI ↔ CI 실행(직접 + in-process import 전이)
# ──────────────────────────────────────────────────────────────────────────

_CLI_PACKAGES = ("harness", "ops")
_CI_MODULE_RUN = re.compile(r"-m\s+(whymath_backend\.[\w.]+)")


def cli_modules(package_root: Path) -> tuple[str, ...]:
    """`harness/`·`ops/`에서 모듈 레벨 `def main(`을 가진 모듈(= 실행 가능한 CLI)."""
    found: list[str] = []
    for pkg in _CLI_PACKAGES:
        for source in sorted((package_root / pkg).glob("*.py")):
            module = _parse_module(source)
            if any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in module.body):
                found.append(f"{pkg}.{source.stem}")
    return tuple(sorted(found))


def ci_executed_modules(ci_path: Path) -> frozenset[str]:
    """`ci.yml`의 `run` 스크립트가 `python -m`으로 직접 실행하는 whymath_backend 모듈."""
    if not ci_path.is_file():
        return frozenset()
    spec: Any = yaml.safe_load(ci_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for job in ((spec or {}).get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and step.get("run"):
                for match in _CI_MODULE_RUN.finditer(str(step["run"])):
                    found.add(match.group(1).removeprefix("whymath_backend."))
    return frozenset(found)


def _module_imports(package_root: Path, source: Path) -> set[str]:
    """이 모듈이 import하는 패키지 내부 모듈(패키지 상대 dotted name).

    패키지명은 `package_root.name`에서 파생한다(하드코딩 금지 — 테스트가 합성 패키지 트리로
    이 축을 검증한다). `from <패키지> import <서브모듈>` 형태를 풀어야 한다(예: `qa_pipeline`이
    `from whymath_backend.harness import corpus_audit_eval`처럼 패키지에서 서브모듈을 꺼내
    조립하는 관례) — 모듈 경로만 세면 그런 CLI가 전부 "미도달"로 오탐된다. `<module>`과
    `<module>.<name>` 후보를 둘 다 낸다(실재하지 않는 후보는 대상 집합 교집합에서 자연히 걸러짐).
    """
    package_name = package_root.name
    package_prefix = f"{package_name}."
    rel_parts = source.relative_to(package_root).with_suffix("").parts
    package_parts = rel_parts[:-1] if rel_parts[-1] != "__init__" else rel_parts
    out: set[str] = set()

    def _emit(dotted: str, names: list[str]) -> None:
        out.add(dotted)
        out.update(f"{dotted}.{name}" for name in names)

    for node in ast.walk(_parse_module(source)):
        if isinstance(node, ast.ImportFrom):
            names = [alias.name for alias in node.names]
            if node.level:  # 상대 import — 현재 패키지 기준으로 해석
                base = list(package_parts[: len(package_parts) - (node.level - 1)])
                if node.module:
                    base += node.module.split(".")
                _emit(".".join(base), names)
            elif node.module and node.module.startswith(package_prefix):
                _emit(node.module.removeprefix(package_prefix), names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(package_prefix):
                    out.add(alias.name.removeprefix(package_prefix))
    return out


def reached_clis(
    package_root: Path, clis: tuple[str, ...], ci_roots: frozenset[str]
) -> frozenset[str]:
    """도달한 CLI — ⑴ CI가 직접 실행 ⑵ 프로덕션 코드가 import ⑶ ⑴·⑵에서 전이 import.

    ⑶이 핵심이다 — 이 저장소는 harness CLI를 subprocess로 부르지 않는 관례라(`qa_pipeline`
    docstring 참조) `corpus_audit_eval` 같은 하위 CLI는 다른 CLI가 in-process import해서만
    도달한다. 직접 실행만 세면 그런 모듈이 전부 "미도달"로 오탐된다. ⑵는 `harness`/`ops` 밖
    (프로덕션 런타임)이 import하는 경우 — 서빙 경로에 들어가 있으면 CLI로 안 돌아도 죽은
    코드가 아니다. 테스트의 import는 세지 않는다(스코프는 `src/backend`) — 테스트가 함수를
    만진다는 것과 파이프라인에 배선됐다는 것은 다르다.
    """
    cli_set = set(clis)
    graph: dict[str, set[str]] = {}
    production_roots: set[str] = set()
    for source in _iter_python_sources(package_root):
        rel = _module_dotted_name(package_root, source)
        imports = _module_imports(package_root, source)
        graph[rel] = imports
        if not rel.startswith(_CLI_PACKAGES):
            production_roots.update(imports & cli_set)

    reached: set[str] = {m for m in ci_roots if m in cli_set} | production_roots
    frontier = list(reached)
    while frontier:
        current = frontier.pop()
        for target in graph.get(current, ()):  # 전이 폐포
            if target in cli_set and target not in reached:
                reached.add(target)
                frontier.append(target)
    return frozenset(reached)


# ──────────────────────────────────────────────────────────────────────────
# 분류 대장 — 미도달 항목의 *의도*를 선언한다(여기가 이 게이트의 본체).
# ──────────────────────────────────────────────────────────────────────────
#
# 값 형식: `by-design:<사유>` 또는 `pending-task:<백로그 태스크 id>`. 판단 근거가 약하면
# `by-design`보다 `pending-task`가 안전하다 — 유예는 만료되지만 오분류는 영구히 남는다.
# 등재된 `pending-task:<id>`는 등재 시점(2026-08-07) `backlog/tasks/<id>.yaml`이 실재하고
# `status != done`임을 실측 확인했다(스테일 유예 포팅 금지 — OPS-22 CONTEXT 지시).

_FRAMEWORK = "by-design:FastAPI 자동 생성 문서·스키마 표면 — 클라이언트 소비 대상이 아니다"
_OPS_PROBE = "by-design:운영 프로브(OPS-01/OPS-04) — 배포·헬스체크·모니터링이 호출한다"
_AUTHORING = (
    "by-design:콘텐츠 저작·운영 CRUD 표면 — 학생 앱이 아니라 운영자/테스트가 쓴다. 관리자 콘솔은 "
    "1인 capacity 가드로 의도적 미구현(operations_module_gap_review.md §2-④)"
)
_PRIVACY_RIGHT = (
    "by-design:법정 권리 이행 표면(PIPA 열람·삭제·감사) — 학생 앱 UI가 아니라 요청 처리 경로다"
)
_CONTENT_RIGHT = (
    "by-design:콘텐츠 접근 권한 판정 표면(DISPLAY·batch-check) — MVP에서 학생 앱 직접 호출 경로가 "
    "아직 확정되지 않았고, L1 rights gateway는 내부/후속 화면(L5/L6)에서 소비하도록 설계됨"
)
_INTERNAL_TOOL = "by-design:내부 도구·하네스 소비 표면 — 학생 클라이언트 대상이 아니다"

_HUMAN_REVIEW_TOOL = (
    "by-design:사람이 대면 실행하는 검수 도구 — CI가 부를 수 있는 종류가 아니다. 자동 실행은 "
    "사람 판정 없는 검수 이벤트를 만들어 HIT를 오염시킨다(측정하려는 대상이 인간 개입 시간 "
    "자체이므로, 무인 실행은 0에 가까운 가짜 표본이 된다)"
)
_BATCH_GENERATOR = (
    "by-design:코퍼스 생성·가공 배치 — 운영자가 입력·비용·판단을 쥐고 손으로 돌리는 것이 "
    "정상이다. CI 상시 실행은 LLM 비용을 매 PR마다 태우는 설계가 된다"
)
_LIVE_DEPENDENT = (
    "by-design:라이브 의존(API 키·GPU·Langfuse·실 PG) — CI에 자격증명·서비스가 없어 원리적으로 "
    "못 돈다"
)
_NEEDS_LIVE_SAMPLE = (
    "by-design:실 PG·실학생 표본 의존 리포트 — 파일럿 전에는 입력이 0이라 CI에서 돌려도 "
    "NO_DATA만 난다"
)
_OFFLINE_REPORT = (
    "by-design:빌드타임 관측 리포트(게이트 아님) — 수치를 보려고 사람이 돌린다. exit 0/2로 "
    "머지를 막는 판정기가 아니므로 CI 상시 배선 대상이 아니다"
)
_OPERATIONS_BATCH = (
    "by-design:운영 집계 배치 — 일 1회 크론/수동 실행이 설계 확정값이고(COLLAB-03 acceptance ⑥) "
    "새 스케줄러 도입은 같은 태스크가 금지했다. 실 PG 왕복이라 CI 상시 실행 대상도 아니다"
)
_MANUAL_COMPARISON_TOOL = (
    "by-design:후보 모델 결선용 수동 비교 도구 — 상시 게이트가 아니라 승격 판정 시점에 사람이 "
    "돌린다"
)
_CORPUS_AUTHORING_WRITER = (
    "by-design:코퍼스 저작 도구(리포 데이터 기록기) — 사람이 새 코퍼스를 만들 때 출처·라이선스를 "
    "입력해 사이드카를 쓴다. 입력(pool·서지 문구)이 사람의 법적 판단이라 자동화 대상이 아니고, "
    "CI가 리포 데이터를 재작성하면 안 되므로(OPS-24 판정 선례: 백필은 변이형이 아니라 --check "
    "드리프트 가드로 배선) 상시 실행 대상도 아니다. 이 도구의 산출물은 별도로 배선된 게이트"
    "(`ops.provenance_audit`, ci.yml)가 상시 검사한다"
)
_PRIVILEGE_ESCALATION_CLI = (
    "by-design:권한 상승 경로 — HTTP 미노출이 설계 확정값이다(operations_platform_gap_review.md "
    "§3 D1: 관리자 HTTP API·콘솔 UI는 범위 밖). 즉 '미도달'이 결함이 아니라 *의도한 봉인*이다 — "
    "인터넷에 열린 표면도, CI가 자동으로 돌리는 표면도 만들지 않고 운영자가 실 PG 앞에서 손으로 "
    "돌린다. CI 배선은 오히려 계약 위반이 된다"
)

_MANIFEST: dict[str, dict[str, str]] = {
    # ── 축 1. HTTP 라우트 ────────────────────────────────────────────────
    AXIS_HTTP: {
        # 프레임워크 자동 표면
        "GET /docs": _FRAMEWORK,
        "GET /docs/oauth2-redirect": _FRAMEWORK,
        "GET /openapi.json": _FRAMEWORK,
        "GET /redoc": _FRAMEWORK,
        # ⚠️ 2026-08-10 OPS-25 유예 일괄 해제 7건 — 아래 항목들이 여기서 사라진 이유
        # ------------------------------------------------------------------------
        #   GET  /v1/auth/{param}/state          (구 _OAUTH_CALLBACK)
        #   GET  /v1/visualizations/spec         (구 슬라이스 95 이연)
        #   POST /v1/visualizations/spec         (구 슬라이스 95 이연)
        #   POST /v1/visualizations/weak-concept (구 슬라이스 95 이연)
        #   POST /v1/me/assessments/assemble     (구 ASM-04 범위 밖)
        #   POST /v1/ocr/pages                   (구 "감사기 정밀도 한계" 자인 유예)
        #   POST /v1/speech/latex                (구 Phase 2+ 이연)
        # 이 7건은 **처음부터 미도달이 아니었다**. 전부 백엔드 테스트가 모듈 상수(`_PATH`·
        # `_ENDPOINT`·`_STATE_PATH` …)로 실제 호출하고 있었고, 감사기가 리터럴 문자열만 보는
        # 한계로 못 봤을 뿐이다(OPS-25가 상수 1홉 해석을 넣어 해소 — `_constant_indirect_calls`).
        # 도달했으므로 유예를 남기면 `stale-waiver`로 exit 1이다. "탐지되지 않으니 유예를 계속
        # 둔다"가 아니라 "탐지기가 틀렸으니 탐지기를 고친다" — 축 3 유예 해제와 같은 대응이다.
        #
        # **정직한 잔여**(유예 문구가 실제로 말하던 것): 이 축의 `reached`는 "dart 클라 호출 ∪
        # 백엔드 테스트 호출"이므로, 위 7건이 reached라는 사실은 *테스트가 관통한다*는 뜻이지
        # *학생 앱이 쓴다*는 뜻이 아니다. 시각화 3종·speech·assemble의 **모바일 소비는 여전히
        # 0건**이고 그 배선은 각각 L5 프런트 착수·Phase 2+·시행/채점 폐루프 시점의 일이다.
        # 이 축은 그 구분을 표현하지 못한다 — 클라 소비 공백을 보려면 dart 호출만 따로 세는
        # 별도 축이 필요하고, 그것은 이 태스크 범위 밖이다(OPS-25 리포트에 잔여로 기록).
        # 세션 가시성·전체 로그아웃·토큰 수명주기(구 MOB-12 유예 5건) — 2026-08-10 유예 해제.
        # MOB-12가 Flutter 계정 보안 화면(`features/auth/presentation/account_security_screen.dart`
        # + `data/auth_sessions_api.dart`)과 401 자동 갱신 인터셉터(`core/auth_interceptor.dart`
        # + `core/token_refresh_api.dart`)를 배선해 5개 라우트 전부 dart 호출로 reached 전환됐다.
        # 항목을 남겨 두면 stale-waiver로 잡히므로 제거한다.
        # 내부 도구·게이팅 축(정책 판정 표면 — 학생 클라이언트가 직접 조회할 화면이 아직 없다).
        # MOB-18 회수(2026-09-07): **면제 4건을 제거했다.** 위 SEC-24 이식 메모가 면제 유지의
        # 근거로 삼은 전제("PB-04가 main에 미착지")가 이 회수로 해소됐다 — `api/
        # _l6_mode_reach_state.py`가 착지하고 `test_l6_mode_reach_observability.py`가 6경로를
        # `client.get("/v1/gating/...")` 형태(식별자 수신자)로 호출하므로 감사기의
        # `_TEST_CLIENT_CALL` 정규식이 실제로 본다. 실측으로 확인했다: 이식 직후 감사가
        # 이 4건을 stale-waiver로 잡아 exit 1을 냈고(추론이 아니라 도구 출력), 제거 후 exit 0이다.
        # gifted·metacognition·suneung·thinking 4종이 여기 있었다(retake·school-progress는
        # 이전부터 test_gating.py 경유로 reached였다).
        # 스킬 축 숙달 곡선 — api/me.py docstring이 "Phase 2b-2"로 명시(개념 축 /v1/me/mastery는
        # 이미 reached·스킬 축은 아직 화면 미착수)
        "GET /v1/me/skill-mastery": (
            "by-design:api/me.py list_my_skill_mastery — Phase 2b-2로 명시된 신규 축, 개념 축 "
            "/v1/me/mastery는 이미 클라·테스트가 호출한다(reached) — 스킬 축 화면만 후속"
        ),
        # LearnerState 단일 조회 표면(EOS-10·2026-09-16 신설) — 구 MOB-22 유예.
        # 2026-09-18 유예 해제: `tests/backend/api/test_week2_gate_wrong_answer_propagation.py`
        # (EOS-110 · Week 2 Gate 판정 하네스)가 오답 전후 스냅샷을 이 라우트로 찍으므로
        # 리터럴 호출로 reached가 됐다. 도달했는데 유예를 남기면 `stale-waiver`로 exit 1이다
        # — 위 MOB-12·MOB-18·PED-15 해제와 같은 대응이다.
        #
        # **정직한 잔여**: 이 축의 `reached`는 "dart 클라 호출 ∪ 백엔드 테스트 호출"이다.
        # 그러므로 reached는 *판정 하네스가 관통한다*는 뜻이지 *학생 앱이 쓴다*는 뜻이 아니다.
        # **모바일 소비는 여전히 0건**이고 그 배선은 `MOB-22`가 계속 소유한다 — 다만 그 태스크의
        # acceptance ②("완료 시 이 선언을 걷는다")는 이 해제로 **이미 충족**됐으니, MOB-22
        # 완료 시 다시 걷을 항목은 없다.
        # 성장 증거 노출 계약 유일 경로(구 PED-15 유예) — 2026-08-10 유예 해제.
        # 정직 표기: PED-15의 전제("부르는 테스트 0건")는 **실측상 사실이 아니었다** —
        # `test_me_growth_evidence.py`가 처음부터 TestClient로 이 라우트를 때리고 있었고,
        # 감사기가 `_ENDPOINT` 상수 경유 호출을 리터럴 매칭으로 못 본 오탐이었다(아래
        # `POST /v1/ocr/pages` 항목과 동형 정밀도 한계). 같은 파일에 리터럴 경로 스모크를
        # 하나 더해 도달이 정적으로도 보이게 했다 — 미도달이 아니므로 by-design 유예로
        # 덮지 않는다. **잔여**: 이 엔드포인트를 소비하는 모바일 클라이언트는 여전히 0건이다.
        # 학습 공급 루프(구 MOB-13 유예 2건) — 2026-08-10 유예 해제.
        # `tests/backend/api/test_study_endpoint.py`(신설)가 두 라우트를 HTTP로 관통한다.
        # 정직 표기: 이것은 *도달 증명*이며 학생 학습 화면 배선은 아직 없다(acceptance가
        # "학생 학습 화면 또는 최소 HTTP 관통 통합테스트"를 둘 다 인정 — 후자를 택했다).
        # OCR 다중 페이지 변형(구 유예) — 2026-08-10 OPS-25로 해제. 이 항목의 사유 자체가
        # "감사기가 상수 경유 호출을 못 잡는 알려진 정밀도 한계"라고 자인하고 있었다. 유예로
        # 덮는 대신 탐지기를 고쳤으므로(`_constant_indirect_calls`) 이제 reached다.
        # 검증 원시 도구 — verify-step은 verify-solution이 내부에서 연쇄 적용하는 하위 빌딩
        # 블록(api/verify.py 모듈 docstring)이고, 학생 앱은 조립된 verify-solution만 부른다.
        "POST /v1/verify-step": (
            "by-design:api/verify.py — verify-step은 verify-solution이 연쇄 적용하는 하위 도구 "
            "표면(모듈 docstring). 학생 경로는 조립된 POST /v1/verify-solution만 쓴다(reached)"
        ),
        # 콘텐츠 접근 권한 판정 표면 — MVP에서 클라이언트 직접 호출 경로가 아직 확정되지 않았고
        # L1 rights gateway는 내부/후속 화면(L5/L6)에서 소비할 것으로 설계되어 있어, 현재 단계에서
        # 도달 항목이 0건인 것이 의도다. 학생 앱이 직접 부르게 되면 reached로 전환한다.
        "GET /v1/rights/{param}/{param}": _CONTENT_RIGHT,
        "POST /v1/rights/batch-check": _CONTENT_RIGHT,
        "POST /v1/rights/check": _CONTENT_RIGHT,
        # 개인정보·보호자 동의 법정 권리 이행 표면 — 학생 앱 UI가 아니라 요청 처리/내부 PEP 경로다.
        "GET /v1/users/me/parental-consent": _PRIVACY_RIGHT,
        "POST /v1/privacy/authorize": _PRIVACY_RIGHT,
    },
    # ── 축 2. EventType(생산자 보유·소비자 없음) ──────────────────────────
    # 실측(2026-08-07): 검산결과·힌트제공·힌트요청은 `wh1_evaluation.py`/`coach.py`가 소비한다.
    # 답입력·시각화조작은 S3-16/슬96-J에서 생산자가 생겼으나 아직 어떤 쿼리도 필터링하지
    # 않는다(관측 신호로 적재만 되는 상태) — 신규 발견, 추적 태스크 없어 등재.
    #
    # ⚠️ 2026-08-10 OPS-25: `막힘` 유예를 해제했다. 등재 당시 3종 묶음이었으나 **막힘은 처음부터
    # 소비되고 있었다** — `l2/learning_metrics_rollup.py`가 `_SOCRATIC_EVENT_TYPES` 상수로
    # `not in` 필터(파이썬)와 `.in_()` 필터(SQL)를 모두 걸고 있고, 감사기가 `ast.Compare`
    # 피연산자에 `EventType.X`가 *직접* 나타나야만 소비로 인정하던 한계 때문에 못 봤다. 남은
    # 2종(답입력·시각화조작)은 코드베이스 전체에서 생산 좌석과 계약 정의에만 나타나므로 실제
    # 미도달이 맞다(음성 대조 실측 — 이 정밀도 수정 후에도 미도달로 유지됨).
    AXIS_EVENT: {
        "답입력": "pending-task:S4-22-attempt-event-signal-consumer-wiring",
        "시각화조작": "pending-task:S4-22-attempt-event-signal-consumer-wiring",
    },
    # ── 축 3. TimescaleDB 집계 테이블 ───────────────────────────────────
    # 비어 있는 것이 정상이다(2026-08-10). 등재됐던 3종은 `COLLAB-03-learning-metrics-writer`
    # 유예였는데, 그 태스크가 done이 되며 `l2/learning_metrics_rollup.py`가 실제 writer가 됐다
    # → 유예를 걷었다(도달했으므로 면제 불요. 남겨 두면 `stale-waiver`로 exit 1이다).
    # ⚠️ 유예를 걷기 전에 감사기 자체의 오탐 2종을 먼저 고쳤다 — 별칭 import(`X as XORM`) 실명
    # 문제와 bulk upsert writer 미탐지(`timeseries_usage` 도크스트링 참조). "탐지되지 않으니
    # 유예를 계속 둔다"가 아니라 "탐지기가 틀렸으니 탐지기를 고친다"가 이 게이트의 정본 대응이다.
    AXIS_TIMESERIES: {},
    # ── 축 4. harness/ops CLI ───────────────────────────────────────────
    AXIS_CLI: {
        # 코퍼스 생성·가공 배치 — 운영자 실행이 정상(입력·비용·판단이 사람 몫)
        "harness.binomial_distribution_batch": _BATCH_GENERATOR,
        "harness.calculus1_integral_batch": _BATCH_GENERATOR,
        "harness.calculus2_trig_integral_batch": _BATCH_GENERATOR,
        "harness.combination_binomial_batch": _BATCH_GENERATOR,
        "harness.complex_number_arithmetic_batch": _BATCH_GENERATOR,
        "harness.conic_section_focus_batch": _BATCH_GENERATOR,
        "harness.coordinate_geometry_batch": _BATCH_GENERATOR,
        "harness.discrete_ev_batch": _BATCH_GENERATOR,
        "harness.elementary_addsub_batch": _BATCH_GENERATOR,
        "harness.elementary_area_measure_batch": _BATCH_GENERATOR,
        "harness.elementary_division_remainder_batch": _BATCH_GENERATOR,
        "harness.elementary_gcd_lcm_batch": _BATCH_GENERATOR,
        "harness.elementary_rounding_batch": _BATCH_GENERATOR,
        "harness.elementary_volume_measure_batch": _BATCH_GENERATOR,
        "harness.highschool_quotient_rule_batch": _BATCH_GENERATOR,
        "harness.linear_inequality_system_batch": _BATCH_GENERATOR,
        "harness.matrix_ops_batch": _BATCH_GENERATOR,
        "harness.measurement_unit_conversion_batch": _BATCH_GENERATOR,
        "harness.middle_function_batch": _BATCH_GENERATOR,
        "harness.permutation_combination_batch": _BATCH_GENERATOR,
        "harness.polynomial_arithmetic_batch": _BATCH_GENERATOR,
        "harness.polynomial_factoring_batch": _BATCH_GENERATOR,
        "harness.probability_law_batch": _BATCH_GENERATOR,
        "harness.quad_ineq_batch": _BATCH_GENERATOR,
        "harness.radian_conversion_batch": _BATCH_GENERATOR,
        "harness.sample_mean_distribution_batch": _BATCH_GENERATOR,
        "harness.sequence_sigma_batch": _BATCH_GENERATOR,
        "harness.university_calc1_batch": _BATCH_GENERATOR,
        "harness.university_calc1_chain_quotient_batch": _BATCH_GENERATOR,
        "harness.vector_operations_batch": _BATCH_GENERATOR,
        "harness.conceptual_count_mc_batch": _BATCH_GENERATOR,
        "harness.finite_probability_batch": _BATCH_GENERATOR,
        "harness.misconception_mc_batch": _BATCH_GENERATOR,
        "harness.problem_corpus_accumulate": _BATCH_GENERATOR,
        "harness.problem_corpus_batch": _BATCH_GENERATOR,
        "harness.problem_corpus_rephrase": _BATCH_GENERATOR,
        "harness.problem_corpus_rephrase_diagnose": _BATCH_GENERATOR,
        "harness.problem_corpus_rephrase_sweep": _BATCH_GENERATOR,
        "harness.problem_corpus_tag": _BATCH_GENERATOR,
        "harness.problem_type_backfill": _BATCH_GENERATOR,
        # ⚠️ 2026-08-10 OPS-24 — 백필 CLI 2종(`problem_corpus_review_status_backfill`·
        # `problem_corpus_persona_fit_backfill`)의 `pending-task` 유예를 해제했다. 판정은
        # "수동 실행 의도"가 아니라 **CI 배선이 맞다**였다 — review_status가 빈 레코드는
        # `l6/_shared.is_review_cleared`가 fail-closed로 노출을 전건 차단하므로 백필 누락은
        # 서빙 영향을 갖는 회귀다. 다만 CI가 레포 데이터를 재작성하면 안 되므로 *변이형*이
        # 아니라 신설 `--check`(미기록·미백필 1건이라도 있으면 exit 1) **드리프트 가드**를
        # `declared-unwired-audit` 잡에 스텝으로 얹었다(신규 잡 0). 이제 둘 다 reached이므로
        # 유예를 남기면 `stale-waiver`로 exit 1이다.
        # 강등전(demotion battle) — 게이트 검출력 자체를 실측 교정하는 운영자용 CLI. S4-16
        # 등 다른 강등전과 동형으로 상시 CI가 아니라 사람이 판단 시점에 돌린다(ARCH-19 done).
        "harness.answer_distribution_battle": (
            "by-design:정답 위치 분포 편향 강등전(ARCH-19) — 결함 주입 검출력 교정용 운영자 실행 "
            "CLI, 다른 강등전류(S4-16 등)와 동형으로 상시 CI 대상 아님"
        ),
        "harness.root_aggregate_batch": _BATCH_GENERATOR,
        "harness.reviewer_sample_package": _BATCH_GENERATOR,
        # 검수 세션(EOS-78) — 판정을 받으며 HIT 타이머를 생산한다. `reviewer_sample_package`
        # (표본 *제시*)와 달리 사람의 판정을 되받는 대면 도구라 배치 사유를 빌려 쓰지 않는다.
        "harness.review_session": _HUMAN_REVIEW_TOOL,
        # MP-05(2026-09-07): 카나리 구간 절단 — 입력이 *특정 회차의 사이드카 4종*(대장·genlog·
        # 코퍼스·검수 큐)이라 상주 입력이 없다. 회차를 돌려야 생기는 파일들이고(레포에
        # 상주하지 않는다), 산출은 그 회차를 검수하려는 사람의 큐다. CI가 매 커밋마다 돌릴
        # 성질이 아니다 — 대상 회차 없이 돌리면 도구가 측정 실패(exit 1)로 거부한다.
        # 판정 로직(적재 순서 계약·canary_size 대장 판독·미해결 3종 구분·review_session 형식
        # 호환)은 backend 잡이 수집하는 tests/backend/harness/test_canary_slice.py가 상시
        # 검증한다 — "안 도는 코드"가 아니라 "회차를 검수할 때 사람이 돌리는 절단 도구"다.
        "harness.canary_slice": (
            "by-design:회차 사이드카 4종이 입력인 카나리 구간 절단 도구(MP-05) — 상주 입력이 "
            "없고, 카나리를 검수하려는 시점에 운영자가 돌려 review_session에 먹일 큐를 만든다"
        ),
        # EOS-121(2026-09-19): 회차 대장 → 회신 추출. `canary_slice`와 같은 부류다 — 입력이
        # *특정 회차의 사이드카*(`<out>.rounds.jsonl`)라 레포에 상주하지 않고, 산출은 라이브
        # 회차를 돌린 사람이 세션에 돌려보낼 보고서다. CI가 매 커밋마다 돌릴 대상이 아니며,
        # 대장 없이 돌리면 도구가 측정 실패(exit 1)로 거부한다. 렌더 계약(미기록/미측정/0의
        # 3상태 구분·cp949 왕복 배제·실패 시 증거 보존)은 backend 잡이 수집하는
        # tests/backend/harness/test_round_reply_extract.py가 뮤테이션 대조로 상시 검증한다.
        "harness.problem_corpus_round_reply": (
            "by-design:라이브 회차 대장을 읽어 회신 보고서를 쓰는 추출 도구(EOS-121 [F]) — "
            "상주 입력이 없고, 좌석 회차를 돌린 운영자가 그 자리에서 한 번 돌린다. "
            "PowerShell이 바이트를 중계하면 한국어가 cp949 왕복으로 깨지므로 런북 [F]가 "
            "이 CLI를 경유한다(Python이 읽고 Python이 쓴다)"
        ),
        # 운영 집계 배치 — COLLAB-03(done)이 신설한 일별 학습지표 롤업 실행기
        "harness.learning_metrics_rollup_cli": _OPERATIONS_BATCH,
        # OPS-56(2026-09-11): 주간 KPI 6종 집계 cron — `ci_executed_modules()`가 `.github/
        # workflows/ci.yml`만 스캔하는데(함수 docstring 참조), 이 모듈은 **별도** 워크플로
        # `.github/workflows/weekly-metrics.yml`이 `python -m whymath_backend.ops.
        # weekly_metrics_report`로 실행한다 — 탐지기의 스캔 범위 밖일 뿐 실제 미배선이
        # 아니다(harness.learning_metrics_rollup_cli의 실 배치 실행과 달리 이쪽은 실제로
        # 매주 스케줄 발화가 있다). 그 별도 워크플로의 배선 실재성(cron 값·fail-open 아님·
        # 최소 경보)은 tests/infra/test_weekly_metrics_cron_wiring.py가 결함 주입 8종으로
        # 상시 검증한다 — "안 도는 코드"가 아니라 "이 축이 보지 않는 워크플로 파일에서 도는
        # 코드"다.
        "ops.weekly_metrics_report": (
            "by-design:주간 KPI 6종 집계 cron(OPS-56) — ci.yml이 아니라 전용 workflow "
            "weekly-metrics.yml이 스케줄 실행한다(ci_executed_modules()의 스캔 범위가 "
            "ci.yml 한정이라 이 축에서는 미도달로 보인다). 실 배선·fail-open 아님은 "
            "tests/infra/test_weekly_metrics_cron_wiring.py가 별도로 동결"
        ),
        # 라이브 의존 — CI에 키·GPU·실 PG가 없어 원리적으로 못 돈다
        "ops.cost_probe": _LIVE_DEPENDENT,
        "ops.live_preflight": _LIVE_DEPENDENT,
        "ops.dialogue_encryption_preflight": _LIVE_DEPENDENT,
        "ops.wh1_shadow_probe": _LIVE_DEPENDENT,
        "harness.wh1_shadow_harvest": _LIVE_DEPENDENT,
        "harness.residue_cross_verify_eval": _LIVE_DEPENDENT,
        # ARCH-49 — DeepSeek/OpenRouter 라이브 프로브. CI에서 원리적으로 못 도는 것이
        # *실측*됐다(2026-09-17 개발 컨테이너: 키 부재 + egress 프록시가
        # api.deepseek.com·openrouter.ai에 CONNECT 403). 이 CLI를 실제로 돌려 3축을
        # 비교하는 것은 `ARCH-55-deepseek-live-battle-measurement`가 소유하며, 그
        # 실행처는 CI가 아니라 키가 있는 Phaiakes9다.
        "harness.deepseek_live_probe": _LIVE_DEPENDENT,
        # ARCH-49 ⑨ — OpenRouter 엔드포인트 조회(공급사 slug·양자화·단가). 위와 같은 이유로
        # CI에서 못 돈다(키 + `openrouter.ai` egress). 목록을 넓히는 판정은 `ARCH-55`.
        "harness.openrouter_endpoints_probe": _LIVE_DEPENDENT,
        # ARCH-55 — 프로바이더 3축 강등전. 클라우드 키 3종이 필요하고 회차마다 실호출을
        # 하므로 CI에서 돌 수 없다(자격증명 부재 + 과금). 계약 회귀는
        # `tests/backend/harness/test_provider_accuracy_battle.py`가 CI에서 돈다 —
        # 즉 *라이브에 갔을 때 옳은 것을 재는가*는 검사되고, *라이브에서 도는가*만 미도달이다.
        "harness.provider_accuracy_battle": _LIVE_DEPENDENT,
        # EOS-54(2026-08-30): HIT·CU 생산 계측 판독기 — 검수 타이머 *실이벤트*(JSONL) 의존.
        # 계측 표본이 쌓이기 전에는 입력 0 = 측정 실패(exit 1)가 설계값(미측정≠0 승격)이라 CI
        # 상시 배선 비대상 — G2(10/25) 기준선·G5 판정 시점에 운영자가 돌린다(answer_distribution_
        # battle "사람이 판단 시점에 돌린다"와 동형). 판정 소비처는 tests/backend/ops/
        # test_hit_cu_metrics.py(backend 잡 수집 — exit 0/1 양쪽 실측). 검수 UI 결선 별항은
        # ADMIN-07 후속(정본화≠집행 — 모듈 docstring).
        # EOS-61(2026-09-01): 12월 검증 결론 판정기 — 입력이 EOS-54 HIT·EOS-55 Run 로그·
        # EOS-60 골든 혼동행렬의 *산출물*이라 위 셋과 같은 이유로 CI 상시 배선 비대상이다.
        # 오히려 이 도구는 **입력이 없을 때 GO를 내지 않는 것이 기능**이다: 빈 입력에서
        # 미측정 12종·판정 불가 게이트 5건을 세고 exit 1을 낸다(측정 실패 ≠ 기준 미달).
        # 판정 로직(Hard Gate 우선·F-Ⅳ 3/2 경계·미측정 비통과·단일 점수 금지)은 backend 잡이
        # 수집하는 tests/backend/ops/test_validation_scorecard.py가 상시 검증한다 —
        # "안 도는 코드"가 아니라 "실측이 있을 때 사람이 G5에서 돌리는 판정기"다.
        "ops.validation_scorecard": (
            "by-design:12월 검증 결론 판정기(EOS-61) — 입력이 EOS-54/55/60 산출물이라 실측 축적 "
            "전에는 전 지표 미측정(exit 1)이 설계값. G5(12/31) 판정 시점에 운영자가 "
            "`--hit-cu-json`·`--qa-matrix-json`으로 생산자 산출을 직접 먹여 돌린다"
        ),
        # EOS-08(2026-09-16): Phase 1 구조 지표 5종 리포터 — **판정기가 아니라 리포터**라
        # CI 차단 스텝에 넣지 않는다(넣으면 그 모듈이 스스로 못박은 "지표 값으로 합격을
        # 선언하지 않는다"를 배선이 배신한다 — 두 도구가 서로 다른 합격을 말하면 무엇을
        # 통과했는지가 결정 불가가 된다). 지표 산출 로직(미측정≠0·분모 동결·근거 유일성)은
        # backend 잡이 수집하는 tests/backend/ops/test_phase1_structure_report.py가 뮤테이션
        # 9종으로 상시 검증한다 — "안 도는 코드"가 아니라 "사람이 볼 때 돌리는 대시보드"다.
        "ops.phase1_structure_report": (
            "by-design:Phase 1 구조 지표 5종 리포터(EOS-08·계획서 200 §36) — 판정기가 아니라 "
            "관측 도구라 CI 차단 스텝 비대상이다. 지표가 나빠도 exit 0이므로 게이트로 배선하면 "
            "의미가 없고, 반대로 exit 1을 내게 바꾸면 validation_scorecard와 합격 판정이 갈린다. "
            "산출 로직은 tests/backend/ops/test_phase1_structure_report.py가 상시 검증"
        ),
        "ops.hit_cu_metrics": (
            "by-design:검수 타이머 실표본 의존 판독기(EOS-54) — 계측 이벤트 축적 전에는 입력 0이 "
            "측정 실패(exit 1)로 설계돼 CI 상시 실행 비대상. G2/G5 KPI 판정 시점에 운영자가 돌린다"
        ),
        # EOS-60(2026-08-31): 골든 승격기 + QA 엔진 혼동행렬 — 둘 다 EOS-54 검수 *실이벤트*가
        # 입력이다(별도 라벨링 캠페인 금지 규약의 귀결). 검수 판정이 쌓이기 전에는 승격 0건 =
        # 측정 실패(exit 1)가 설계값이라 hit_cu_metrics와 같은 이유로 CI 상시 배선 비대상 —
        # G2(10/25) 기준선·G5 판정 시점에 운영자가 돌린다. 판정 로직 자체(as-found fail-closed·
        # 회전·digest·혼동행렬·게이트 변별력 양방향·재채점 금지)는 backend 잡이 수집하는
        # tests/backend/harness/test_golden_benchmark.py·tests/backend/ops/
        # test_qa_confusion_matrix.py가 상시 검증한다 — "안 도는 코드"가 아니라 "실표본이 있을
        # 때 사람이 돌리는 판독기"다. 계약 정본 = docs/standards/golden_benchmark_contract.md.
        "harness.golden_benchmark": (
            "by-design:검수 실이벤트 의존 골든 승격기(EOS-60) — 검수 판정 축적 전에는 승격 0건이 "
            "측정 실패(exit 1)로 설계돼 CI 상시 실행 비대상. 검수와 함께 운영자가 돌린다"
        ),
        "ops.qa_confusion_matrix": (
            "by-design:골든 실표본 의존 혼동행렬 판독기(EOS-60) — 골든 0건·평가쌍 0건이 측정 "
            "실패(exit 1)로 설계돼 CI 상시 실행 비대상. G2/G5 KPI 판정 시점에 운영자가 돌린다"
        ),
        # EOS-64(2026-09-01): 골든 승격 경로 게이트 — 입력이 *승격 제안*(사람이 "이것들을
        # 올리겠다"고 내미는 목록)이라 제안이 없는 시점에는 돌릴 대상 자체가 없다. CI가 매
        # 커밋마다 돌릴 성질이 아니고(제안 파일이 레포에 상주하지 않는다), 승격 판정 시점에
        # 운영자가 돌리는 문지기다. 판정 로직(경로 밖 6종 차단·Wilson 상한 방향·측정 불가
        # 비통과·사람 판정 우회 불가)은 backend 잡이 수집하는
        # tests/backend/harness/test_golden_promotion_gate.py가 상시 검증한다.
        "harness.golden_promotion_gate": (
            "by-design:승격 제안 의존 경로 문지기(EOS-64 ③) — 제안 목록이 입력이라 상주 입력이 "
            "없고, 승격 판정 시점에 운영자가 돌린다. 사람 검수를 대체하지 않는 확인 도구다"
        ),
        # MP-03(2026-09-25): 골든 경로 입력 준비 — 위 두 판정기(승격 게이트 `--proposal`·골든
        # 벤치 `--anchor-map`)가 요구하는 입력을 *검수 이벤트·카나리 검수 큐*에서 파생한다.
        # 둘 다 회차를 검수해야 생기는 파일이라 레포에 상주하지 않고, 판정기와 같은 시점에
        # 운영자가 그 직전 단계로 돌린다. 입력이 없으면 exit 2, 산출 0건이면 exit 1로 거부한다.
        # 열거·역인덱스 로직(판정 비날조·미매핑 사유 5종·손상 시 무산출·게이트와 같은 판정
        # 집합·골든 파서 무오류 소비)은 backend 잡이 수집하는
        # tests/backend/harness/test_golden_inputs.py가 뮤테이션 대조로 상시 검증한다.
        "harness.golden_inputs": (
            "by-design:검수 기록 의존 골든 경로 입력 준비 도구(MP-03) — 검수 이벤트·카나리 큐가 "
            "입력이라 상주 입력이 없고, 승격 게이트·골든 벤치 직전에 운영자가 돌린다"
        ),
        # EOS-97(2026-09-06): 생성 산출물 리콜 — 입력이 *생성 회차의 genlog 사이드카*이고
        # 처분 대상이 *결함이 발견된 회차*다. 둘 다 상주하지 않는다: genlog는 배치를 돌려야
        # 생기고(레포에 상주하지 않는다), 리콜은 "OP_03 정의에 결함을 발견했다" 같은 **사람의
        # 판단이 선행**해야 시작된다. CI가 매 커밋마다 돌릴 성질이 아니다 — 셀렉터 없이 돌리면
        # 전건 처분이라 도구 자신이 그 호출을 거부한다.
        # 판정 로직(선별 정밀도 과다·과소 양방향·격리 불가 분리 계상·계약 3필드 기입·실패
        # 미삼킴·파일 부재를 매치 0건으로 위장하지 않음)은 backend 잡이 수집하는
        # tests/backend/ops/test_generation_recall.py가 상시 검증한다 — "안 도는 코드"가
        # 아니라 "결함을 발견했을 때 사람이 돌리는 처분 도구"다.
        "ops.generation_recall": (
            "by-design:회차 genlog + 사람의 결함 판단이 입력인 리콜 도구(EOS-97) — 상주 입력이 "
            "없고 셀렉터 없는 호출은 도구가 거부한다(전건 처분 방지). 결함 발견 시 운영자가 "
            "돌리며, 되돌리기 어려운 처분은 --apply 명시로만 나간다(dry-run 기본)"
        ),
        # 실 DB·실학생 표본 의존 리포트
        "harness.pilot_kpi_baseline": _NEEDS_LIVE_SAMPLE,
        "harness.surrogate_baseline_report": _NEEDS_LIVE_SAMPLE,
        # ASM-05(2026-08-10): 수요측 성취기준 도달 관측 — CMH(실학생 숙달 측정) 의존,
        # S3-01 파일럿 전에는 NO_DATA 정직 렌더가 설계값(acceptance ③)이라 CI 상시 배선 비대상.
        "harness.standard_attainment_report": _NEEDS_LIVE_SAMPLE,
        # EOS-57(2026-08-30): `문제시도` 스킬 배열 기록률 리포트 — 실 PG의 *실제 채점 이력*이
        # 분모다. CI의 PG는 매 잡마다 비어 있어 상시 실행하면 전 지표가 "측정 불가(분모 0)"만
        # 낸다(그렇게 렌더하는 것이 이 리포트의 설계값이지, CI에서 확인할 값이 아니다).
        # 판정 로직 자체(3분류 변별력·분모 0 처리·죽은 경로 보강·CLI exit 0/2)는
        # tests/backend/harness/test_attempt_skill_event_reach_report.py가 CI에서 상시 검증한다
        # — 즉 "안 도는 코드"가 아니라 "라이브 입력이 있을 때 사람이 돌리는 관측기"다.
        "harness.attempt_skill_event_reach_report": _NEEDS_LIVE_SAMPLE,
        # OPS-68(2026-09-07): 위 리포트의 짝 — 게이트 G-eos63-skill-event-reach-sample이
        # 요구하는 *표본을 만드는* 프로브다. CI가 절대 돌려서는 안 되는 유일한 이유가 미도달
        # 사유이기도 하다 — 이 도구는 대상 DB에 채점 행을 **쓴다**(problem_attempt·
        # attempt_event·숙달 시계열). 상시 배선하면 CI가 매 잡마다 DB를 오염시키고, 그
        # 오염이 곧 다른 리포트의 분모가 된다. 판정 로직(분모 0의 None 처리·실패 사유
        # 타입명 집계·exit 0/2/3/4/5 변별)은 tests/backend/harness/
        # test_attempt_skill_reach_probe.py가 CI에서 상시 검증한다.
        "harness.attempt_skill_reach_probe": (
            "by-design:실 PG에 표본을 *쓰는* 게이트 실행 도구 — 운영자가 측정 회차에 1회 "
            "돌린다. CI 상시 실행은 DB 오염이라 금지"
        ),
        # OPS-72(2026-09-10): 호스트→prod DB 도달성 진단. 입력이 **살아 있는 docker 데몬 +
        # 실행 중인 prod 컨테이너**라 CI에는 둘 다 없다(있더라도 CI의 PG는 서비스 컨테이너지
        # whymath-pg가 아니다) — 상시 실행하면 전건 UNKNOWN(exit 2)만 난다. 그것이 이 도구의
        # 설계값이지 CI에서 확인할 값이 아니다. **판정 로직은 순수 코어로 분리돼 있고**
        # tests/backend/ops/test_db_host_reachability.py가 6상태 전건을 주입해 CI에서 상시
        # 검증한다(REACHABLE/NOT_PUBLISHED/NO_BINDING/PUBLISHED_BUT_CLOSED/FOREIGN_LISTENER/
        # UNKNOWN이 서로 다른 답으로 갈리는지까지). 운영 배선은 사람 경로다 —
        # docs/standards/incident_response_slo.md §4-1의 실패 유형과 /demo-doctor 카탈로그
        # W1행이 이 CLI를 1차 진단으로 지목한다.
        "ops.db_host_reachability": _LIVE_DEPENDENT,
        # EOS-73(2026-09-01): 생성 seed 적재율 리포트 — 분모가 *실제 생성 배치*의 genlog JSONL
        # 이다. CI에는 그 산출물이 없어(LLM 배치를 매 PR마다 돌리지 않는다) 상시 실행하면 전
        # 지표가 "측정 불가(분모 0)"만 난다 — 그렇게 렌더하는 것이 이 리포트의 설계값이지 CI에서
        # 확인할 값이 아니다. 판정 로직(3분류 변별력·분모 0 처리·죽은 경로 보강·판별자 정합·
        # CLI exit 0/2)은 tests/backend/harness/test_generation_seed_adoption_report.py가 CI에서
        # 상시 검증한다 — "안 도는 코드"가 아니라 "생성 배치가 있을 때 사람이 돌리는 관측기"다.
        "harness.generation_seed_adoption_report": _NEEDS_LIVE_SAMPLE,
        # EOS-73(2026-09-01): 결정론 재생성 프로브 — 기록된 seed·입력 전문을 **라이브 Ollama**에
        # 되먹여 회차 간 출력 동일성을 잰다. GPU·데몬 없이는 원리적으로 못 돈다. 판정 로직(3값
        # 분류 변별력·좌표 복원 거부 사유·미측정 자인 렌더)은 tests/backend/harness/
        # test_generation_seed_replay_probe.py가 상시 검증하며, 이 배포의 "같은 seed → 같은 출력"
        # 성립 여부는 그 CLI를 돌리기 전까지 **미측정**이다(성립으로 승격 금지).
        "harness.generation_seed_replay_probe": _LIVE_DEPENDENT,
        # 빌드타임 관측 리포트(게이트 아님) — 사람이 필요할 때 돌린다
        "harness.problem_bank_coverage": _OFFLINE_REPORT,
        # QUAL-01(2026-08-10): 코퍼스 JSONL만 읽는 빌드타임 관측 리포트(DB 0) — problem_bank_
        # coverage와 동일 취급. 실중복이 나와도 exit 1을 내지 않는 게이트 아님 원칙도 동일.
        "harness.problem_duplication_audit": _OFFLINE_REPORT,
        "harness.visualization_reach_report": _OFFLINE_REPORT,
        "harness.concept_reach_report": _OFFLINE_REPORT,
        # KG-03(2026-08-11): 공식 축 도달 관측 — concept_reach_report와 동일 성격(정적 스캔·
        # DB 0·게이트 아님). 판정 소비처는 tests/backend/harness/test_formula_reach_report.py
        # (backend 잡 testpaths가 수집)이며 전용 CI 잡은 의도적으로 신설하지 않았다 —
        # concept-reach(OPS-23)와 달리 mobile-only PR 회귀 가드가 아니라 관측 리포트다.
        "harness.formula_reach_report": _OFFLINE_REPORT,
        "harness.assessment_seat_reach_report": _OFFLINE_REPORT,
        "harness.recommendation_outcome_report": _OFFLINE_REPORT,
        "harness.learning_path_orderability_report": _OFFLINE_REPORT,
        "harness.rephrased_corpus_hygiene": _OFFLINE_REPORT,
        "harness.pedagogy_policy_eval": _OFFLINE_REPORT,
        "harness.curriculum_revision_crosswalk_report": _OFFLINE_REPORT,
        "harness.objective_coverage": _OFFLINE_REPORT,
        "harness.concept_assessment_index": _OFFLINE_REPORT,
        "harness.concept_content_audit": _OFFLINE_REPORT,
        "harness.concept_content_review_batch": _BATCH_GENERATOR,
        "harness.concept_content_review_apply": _BATCH_GENERATOR,
        # REC-09 회수(2026-08-11) — `harness.attempt_grading_shadow_report`의 `_OFFLINE_REPORT`
        # 유예를 **삭제**했다. 이 모듈은 이제 CI 루트에서 전이 도달한다: REC-08 게이트
        # (`harness.selective_grading_demotion_eval` · backend 잡의 독립 스텝)가 이 모듈의
        # `classify_gradability`를 in-process import해 A/B 모집단을 정의한다(재정의 0). 감사기의
        # 도달 정의(⑶ 전이 폐포 — `reached_clis` docstring)상 도달이므로 유예를 남기면
        # `stale-waiver` 위반이다. **CLI `main()` 자체는 여전히 CI가 안 돌린다** — 유예를 지운
        # 것은 "관측 리포트를 게이트로 승격했다"는 뜻이 아니라 "이 모듈의 코드가 이제 CI 판정
        # 경로 안에 있다"는 뜻이다(원 유예 사유였던 '아무도 안 부른다'가 사실이 아니게 됐다).
        # ASM-09(2026-08-11): distractor_map 오개념 신호 사장 규모 관측 — assessment_seat_
        # reach_report와 동형(DB 실측·게이트 아님·exit 0/2). 사장 규모가 얼마든 머지를 막지
        # 않으므로 CI 상시 배선 비대상.
        "harness.distractor_signal_dormancy_report": _OFFLINE_REPORT,
        "ops.recommendation_reach_report": _OFFLINE_REPORT,
        # REC-06(2026-08-11): 반복 추천 진도 폭·집중도 관측 — recommendation_reach_report와
        # 동형(실 DB 조회·게이트 아님·exit 0/2). 진도 폭이 1이어도 머지를 막지 않으므로 CI
        # 상시 배선 비대상이고, 실 PG 왕복이라 CI에서 원리적으로 돌지도 않는다.
        "ops.repeat_recommendation_report": _OFFLINE_REPORT,
        "ops.pedagogy_content_slot_reach_report": _OFFLINE_REPORT,
        "ops.role_grant_cli": _PRIVILEGE_ESCALATION_CLI,
        # ADMIN-11(2026-08-31): 좌석 발급 경로의 *계정* 절반. role_grant_cli와 같은 봉인에
        # 속한다 — 좌석을 줄 대상(user_profile)이 0행이라 grant가 성립하지 않던 구멍을 메운다.
        # 같은 사유로 HTTP 미노출·CI 미배선이 설계 확정값이다(운영자가 실 PG 앞에서 1회 실행).
        "ops.account_bootstrap_cli": _PRIVILEGE_ESCALATION_CLI,
        # ADMIN-15(2026-09-25): 좌석 발급 경로의 *신원* 절반 — 로그인 없이 운영자 액세스 토큰을
        # 만드는 CLI다. OAuth 밖의 인증 경로라 HTTP 노출·CI 자동 실행은 둘 다 설계상 금지이고
        # (발급마다 privacy_audit 1행), 운영자가 실 PG·서버 시크릿 앞에서 수동 실행한다.
        "ops.operator_token_cli": _PRIVILEGE_ESCALATION_CLI,
        # PB-11(2026-08-11): 코퍼스 사이드카 생성·갱신 저작 CLI. `ops.provenance_audit`이 집행하는
        # 계약을 만족하는 파일을 만들어 주는 도구가 저장소에 0개였던 부재를 메운다 — 저자가 손으로
        # 돌리는 쓰기 도구이므로 CI 상시 실행 대상이 아니다(사유 상수 참조).
        "ops.corpus_provenance_sidecar": _CORPUS_AUTHORING_WRITER,
        "harness.agreement_gate_cli": _MANUAL_COMPARISON_TOOL,
        # OPS-48(완료) — QUALITY 티어 dense↔MoE 정확도 축 강등전. Phaiakes9 실측 완료,
        # 결과는 data/audit/ops-48-moe-accuracy-battle-*.jsonl. 승격 판정 시점의 수동 도구.
        "harness.quality_tier_moe_accuracy_battle": _MANUAL_COMPARISON_TOOL,
        # S4-16(진행 중) 산출물 — 게이트 승격 조건 측정 도구, 승격 전까지는 CI 상시 배선 대상
        # 아님(LLM K=3 교차검증 라이브 의존)
        "harness.residue_gate_demotion_battle": "pending-task:S4-16-residue-gate-demotion-battle",
        # `ops.declared_unwired_audit`(이 모듈 자신)은 여기 등재하지 않는다 — 전용 CI 잡
        # (`declared-unwired-audit`)이 `-m`으로 직접 실행하므로 언제나 `reached`다. 등재해 두면
        # `_classify`가 즉시 `stale-waiver`로 잡는다(실측: 첫 CI 잡 배선 직후 전체 스위트가 그
        # 상태를 실제로 검출했다 — `ops.reach_audit` 선례와 동형인 자기참조 함정).
    },
}


# ──────────────────────────────────────────────────────────────────────────
# 판정
# ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ItemVerdict:
    axis: str
    key: str
    status: str  # reached | by-design | pending-task | unclassified | expired-waiver | ...
    note: str

    @property
    def is_violation(self) -> bool:
        return self.status not in {"reached", "by-design", "pending-task"}

    def to_json(self) -> dict[str, str]:
        return {"axis": self.axis, "key": self.key, "status": self.status, "note": self.note}


@dataclass(frozen=True, slots=True)
class AxisResult:
    axis: str
    verdicts: tuple[ItemVerdict, ...]

    @property
    def supplied(self) -> int:
        return len(self.verdicts)

    @property
    def reached(self) -> int:
        return sum(1 for v in self.verdicts if v.status == "reached")

    @property
    def violations(self) -> tuple[ItemVerdict, ...]:
        return tuple(v for v in self.verdicts if v.is_violation)

    def to_json(self) -> dict[str, Any]:
        return {
            "supplied": self.supplied,
            "reached": self.reached,
            "violations": [v.to_json() for v in self.violations],
            "items": [v.to_json() for v in self.verdicts],
        }


@dataclass(frozen=True, slots=True)
class Report:
    axes: tuple[AxisResult, ...]

    @property
    def violations(self) -> tuple[ItemVerdict, ...]:
        return tuple(v for axis in self.axes for v in axis.violations)

    @property
    def exit_code(self) -> int:
        return _EXIT_OK if not self.violations else _EXIT_VIOLATIONS

    def to_json(self) -> dict[str, Any]:
        return {
            "axes": {axis.axis: axis.to_json() for axis in self.axes},
            "overall": {"pass": not self.violations, "violations": len(self.violations)},
        }


def _task_status(backlog_tasks: Path, task_id: str) -> str | None:
    """`backlog/tasks/<id>.yaml`의 `status`. 파일이 없으면 None(그랜드파더 만료 계약)."""
    path = backlog_tasks / f"{task_id}.yaml"
    if not path.is_file():
        return None
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    status = (data or {}).get("status")
    return str(status) if status is not None else None


def _classify(axis: str, key: str, is_reached: bool, backlog_tasks: Path) -> ItemVerdict:
    declared = _MANIFEST.get(axis, {}).get(key)
    if is_reached:
        if declared is not None:
            # 도달했는데 대장에 남아 있다 — 낡은 예외가 방치되고 있다는 신호(조용히 넘기지 않는다).
            note = f"이미 도달했는데 대장에 남음: {declared}"
            return ItemVerdict(axis, key, "stale-waiver", note)
        return ItemVerdict(axis, key, "reached", "")
    if declared is None:
        return ItemVerdict(axis, key, "unclassified", "미도달인데 의도 선언이 없다")
    if declared.startswith(_BY_DESIGN):
        reason = declared[len(_BY_DESIGN) :].strip()
        if not reason:
            return ItemVerdict(axis, key, "missing-reason", "by-design인데 사유가 비어 있다")
        return ItemVerdict(axis, key, "by-design", reason)
    if declared.startswith(_PENDING_TASK):
        task_id = declared[len(_PENDING_TASK) :].strip()
        status = _task_status(backlog_tasks, task_id)
        if status is None:
            return ItemVerdict(axis, key, "expired-waiver", f"유예 근거 태스크 부재: {task_id}")
        if status == "done":
            return ItemVerdict(axis, key, "expired-waiver", f"유예 근거 태스크 완료됨: {task_id}")
        return ItemVerdict(axis, key, "pending-task", f"{task_id} ({status})")
    return ItemVerdict(axis, key, "malformed", f"알 수 없는 분류 값: {declared}")


def _timeseries_key_note(usage: TimeseriesUsage) -> str:
    has_writer = bool(usage.writers)
    has_reader = bool(usage.readers)
    if has_writer and not has_reader:
        return "writer 있음·reader 없음"
    if has_reader and not has_writer:
        return f"reader 있음({', '.join(usage.readers)})·writer 없음"
    return "writer·reader 둘 다 없음"


def build_report(root: Path | None = None) -> Report:
    """4축 전수 감사. DB·LLM·HTTP 0(빌드타임 결정론).

    Raises:
        CollectorError: 어느 축이든 수집 수가 하한 미만(추출기 파손) — exit 2로 이어진다.
    """
    base = root or repo_root()
    package_root = base / "src" / "backend" / "whymath_backend"
    backlog_tasks = base / "backlog" / "tasks"

    routes = app_route_entries()
    callers = dart_call_entries(base / "src" / "mobile" / "lib") | test_call_entries(
        base / "tests" / "backend"
    )
    events = produced_event_types(package_root)
    ts_models = timeseries_models(package_root)
    clis = cli_modules(package_root)

    for label, count in (
        ("routes", len(routes)),
        ("callers", len(callers)),
        ("event_types", len(events)),
        ("timeseries_models", len(ts_models)),
        ("clis", len(clis)),
    ):
        if count < _FLOORS[label]:
            raise CollectorError(
                f"{label} 수집 {count}건 — 하한 {_FLOORS[label]} 미만. 추출기가 깨졌을 가능성이 "
                "높다. '미도달 0건 통과'로 위장하지 않고 입력 오류로 실패한다."
            )

    consumed = consumed_event_types(package_root)
    ts_usage = timeseries_usage(package_root, ts_models)
    ci_roots = ci_executed_modules(base / ".github" / "workflows" / "ci.yml")
    reached_cli_set = reached_clis(package_root, clis, ci_roots)

    http = tuple(
        _classify(
            AXIS_HTTP,
            f"{method} {normalize_server_path(path)}",
            _route_reached(method, path, callers),
            backlog_tasks,
        )
        for method, path in routes
    )
    event = tuple(
        _classify(AXIS_EVENT, name, name in consumed, backlog_tasks) for name in sorted(events)
    )
    timeseries_verdicts: list[ItemVerdict] = []
    for name in ts_models:
        usage = ts_usage[name]
        is_ok = bool(usage.writers) and bool(usage.readers)
        verdict = _classify(AXIS_TIMESERIES, name, is_ok, backlog_tasks)
        if not is_ok and verdict.status == "pending-task":
            note = f"{verdict.note} — {_timeseries_key_note(usage)}"
            verdict = ItemVerdict(verdict.axis, verdict.key, verdict.status, note)
        timeseries_verdicts.append(verdict)
    cli = tuple(_classify(AXIS_CLI, name, name in reached_cli_set, backlog_tasks) for name in clis)

    return Report(
        axes=(
            AxisResult(AXIS_HTTP, _dedup(http)),
            AxisResult(AXIS_EVENT, event),
            AxisResult(AXIS_TIMESERIES, tuple(timeseries_verdicts)),
            AxisResult(AXIS_CLI, cli),
        )
    )


def _dedup(verdicts: tuple[ItemVerdict, ...]) -> tuple[ItemVerdict, ...]:
    """정규화 후 같은 키로 합쳐지는 라우트를 1건으로(다중 메서드 라우트가 메서드별로 갈릴 때도
    같은 경로 키를 공유하므로, 여기선 axis+key 동일 항목의 최선 상태만 남긴다)."""
    seen: dict[tuple[str, str], ItemVerdict] = {}
    for verdict in verdicts:
        keying = (verdict.axis, verdict.key)
        current = seen.get(keying)
        if current is None or (current.status != "reached" and verdict.status == "reached"):
            seen[keying] = verdict
    return tuple(seen[k] for k in sorted(seen))


def render_report(report: Report) -> str:
    lines: list[str] = [
        "선언≠배선 일반 탐지기 (OPS-22) — 미도달 수가 아니라 미분류가 실패다",
        "",
    ]
    for axis in report.axes:
        unreached = axis.supplied - axis.reached
        lines.append(
            f"[{axis.axis}] 공급 {axis.supplied} · 도달 {axis.reached} · 미도달 {unreached}"
            f" · 위반 {len(axis.violations)}"
        )
        for verdict in axis.violations:
            lines.append(f"    ✗ {verdict.status:16} {verdict.key} — {verdict.note}")
    lines.append("")
    if report.violations:
        lines.append(f"판정: 실패 — 위반 {len(report.violations)}건")
        lines.append("  미도달을 고치라는 뜻이 아니다. 그 미도달이 의도인지 선언하라는 뜻이다:")
        lines.append(f"  `{_BY_DESIGN}<사유>` 또는 `{_PENDING_TASK}<백로그 태스크 id>`")
    else:
        lines.append("판정: 통과 — 모든 공급 항목이 도달했거나 의도가 선언돼 있다")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.declared_unwired_audit",
        description=(
            "선언≠배선 일반 탐지기 — 4축 정적 감사(OPS-22). 미분류 공급 항목·만료 유예를 차단한다."
        ),
    )
    parser.add_argument("--root", type=Path, default=None, help="저장소 루트(기본: 자동 탐지)")
    parser.add_argument("--json", type=Path, default=None, help="리포트를 JSON으로 저장할 경로")
    args = parser.parse_args(argv)

    try:
        report = build_report(args.root)
    except CollectorError as exc:
        print(f"[declared_unwired_audit] 수집기 파손: {exc}", file=sys.stderr)
        return _EXIT_INPUT_ERROR

    print(render_report(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    raise SystemExit(main())
