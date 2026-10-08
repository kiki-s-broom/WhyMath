"""거버넌스 동결 — 학년축은 오버레이 파라미터, 구조 분기 아님 (W0 — 학년축 최단경로 계획 §2.1).

CLAUDE.md 8대 구조 원칙 ⑤(Curriculum은 Overlay)와
`docs/strategy/grade_axis_mvp_shortest_path_v1.md` §2.1의 답을 코드로 동결한다: L2(학습자
모델)·L3(생성·검증)·L4(교수학 엔진)는 `school_level`/`grade_band`/`grade_band_hint` 값으로
*제어 흐름을 분기*하지 않는다 — 학년은 항상 프롬프트 인자·필터 값으로만 흘러야 한다(구조
자체가 갈라지면 안 됨). 4축(초·중·고·대학)으로 콘텐츠를 채울 때 L2~L4에 축별 `if` 분기가
스며드는 것을 이 테스트가 조기에 잡는다.

**L1은 스코프 밖**이다 — L1(데이터 기반)은 커리큘럼 Overlay 적재기가 본업이라
`school_level`/`grade_band`로 코퍼스를 필터·매핑하는 것이 정상 설계다(예:
`l1/curriculum/curriculum_loader.py`의 `atom.get("school_level") != "대학"` 필터). 여기서
막는 것은 *비교 연산자로 갈라지는 제어 흐름*(`==`/`!=`)이지, `_MAP.get(grade_band)` 같은 dict
기반 오버레이 매핑(파라미터 룩업 — 원칙이 권장하는 패턴)이 아니다 — 비교 연산자가 없는
룩업은 자연히 통과한다.

검출 방식 = **AST(문법 트리) 비교 검사**: 정규식(`필드명 ==`)은 피연산자 순서를 뒤집은
`"대학" == school_level`, 값 접근 형태 `atom.get("school_level") != "대학"`·`row["grade_band"]
== ...`을 놓친다(2026-10-08 실제 l4 소스 주입 실측 — 5형태 중 3형태 미검출). 그래서 `==`/`!=`
비교의 *양쪽 피연산자* 안에 금지 필드 참조(이름·속성·`["키"]`·`.get("키")`)가 있는지를 본다.
`match school_level:` 문도 같은 구조 분기라 함께 막는다. 필드명 *문자열*끼리의 비교
(`col == "school_level"`)는 값 분기가 아니라 필드명 디스패치라 대상이 아니다.

hermetic: DB 불요(소스 스캔만). `test_embedding_namespace_governance.py`(cosine_distance
allowlist)와 동일한 rglob + 소스 스캔 패턴.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# 구조 분기 금지 대상 값 3종 — 학년축 어휘(L1 커리큘럼 오버레이가 쓰는 필드명 그대로).
# `grade`(정수 힌트)는 대상이 아니다 — `if grade is not None:` 류는 오버레이 파라미터의
# 정상 사용(prompt_assembler.py 선례)이라 의도적으로 제외한다.
_BANNED_FIELDS = frozenset({"school_level", "grade_band_hint", "grade_band"})

# 스캔 대상 — L2(학습자 모델)·L3(생성·검증)·L4(교수학 엔진)만. L1(데이터 기반)은 커리큘럼
# Overlay 적재기 본업이라 스코프 밖(모듈 docstring). L5~L7은 이 저장소의 백엔드 패키지 밖
# (Flutter/별도 웹) 또는 아직 이 축 배선이 없어 후속 슬라이스 대상.
_SCANNED_LAYERS = ("l2", "l3", "l4")


def _banned_ref(node: ast.AST) -> str | None:
    """노드가 금지 필드의 *값 참조*이면 필드명을, 아니면 None.

    값 참조 4형태: 이름(`school_level`)·속성(`obj.grade_band`)·첨자(`row["grade_band"]`)·
    `.get("키")` 호출. 문자열 상수 단독(`"school_level"`)은 필드명 디스패치라 참조가 아니다.
    """
    if isinstance(node, ast.Name) and node.id in _BANNED_FIELDS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _BANNED_FIELDS:
        return node.attr
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in _BANNED_FIELDS
    ):
        return str(node.slice.value)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value in _BANNED_FIELDS
    ):
        return str(node.args[0].value)
    return None


def _first_banned_ref(expr: ast.AST) -> str | None:
    """식 전체(`str(grade_band).lower()` 같은 감싼 형태 포함)에서 첫 금지 필드 참조."""
    for sub in ast.walk(expr):
        field = _banned_ref(sub)
        if field is not None:
            return field
    return None


def _scan_source(text: str) -> list[tuple[int, str]]:
    """소스 1개의 구조 분기 위반 → (줄번호, 필드명) 목록.

    `==`/`!=`가 하나라도 낀 비교는 *양쪽* 피연산자를 모두 본다(순서 뒤집기 우회 차단).
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops
        ):
            for operand in (node.left, *node.comparators):
                field = _first_banned_ref(operand)
                if field is not None:
                    hits.append((node.lineno, field))
        elif isinstance(node, ast.Match):
            field = _first_banned_ref(node.subject)
            if field is not None:
                hits.append((node.lineno, field))
    return sorted(set(hits))


def _iter_layer_files(package_root: Path) -> dict[str, list[Path]]:
    return {
        layer: sorted((package_root / layer).rglob("*.py"))
        for layer in _SCANNED_LAYERS
        if (package_root / layer).is_dir()
    }


def _require_scanned_layers(package_root: Path) -> dict[str, list[Path]]:
    """공허한 통과 차단 — 세 계층 모두 디렉터리가 있고 파일이 1개 이상이어야 한다.

    스캔 0건은 통과가 아니라 실패다: 계층 디렉터리가 사라지거나 이름이 바뀌면 이 가드는
    아무것도 안 보면서 상시 그린이 된다.
    """
    scanned = _iter_layer_files(package_root)
    assert set(scanned) == set(_SCANNED_LAYERS), f"스캔 대상 계층 디렉터리 부재: {sorted(scanned)}"
    empty = [layer for layer, files in scanned.items() if not files]
    assert not empty, f"스캔 파일 0건 계층(공허한 통과 위험): {empty}"
    return scanned


def _collect_violations(package_root: Path) -> list[str]:
    violations: list[str] = []
    for files in _iter_layer_files(package_root).values():
        for path in files:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            for lineno, field in _scan_source(text):
                rel = path.relative_to(package_root).as_posix()
                violations.append(f"{rel}:{lineno}: [{field}] {lines[lineno - 1].strip()}")
    return violations


def test_no_grade_axis_structural_branching_in_l2_l3_l4() -> None:
    """L2~L4 소스에 `school_level`/`grade_band`/`grade_band_hint` 비교 분기가 없어야 한다.

    위반이 발견되면 그 파일·라인을 보고한다 — 조용한 실패 금지(CLAUDE.md 침묵 실패 금지 원칙과
    동형: 위반 즉시 어디서 났는지 드러난다). 새 축(초·중·고·대학) 콘텐츠 확장(W2)이 L2~L4에
    학년별 `if` 분기를 심는 순간 이 테스트가 CI에서 즉시 red가 된다.
    """
    import whymath_backend

    package_root = Path(whymath_backend.__file__).parent

    _require_scanned_layers(package_root)  # 스캔 0건 = 실패(공허한 통과 차단)

    violations = _collect_violations(package_root)
    assert not violations, (
        "L2~L4에 학년축 구조 분기가 발견됐습니다(school_level/grade_band/grade_band_hint를 "
        "==/!=로 비교) — 학년축은 오버레이 파라미터여야지 제어 흐름을 갈라선 안 됩니다"
        "(CLAUDE.md 8대 구조 원칙 ⑤ Curriculum은 Overlay). 발견:\n"
        + "\n".join(violations)
        + "\n\ndict 기반 매핑(`_MAP.get(grade_band)`)으로 바꾸거나, 정말 구조 분기가 필요하다면 "
        "이 테스트와 grade_axis_mvp_shortest_path_v1.md §2.1을 함께 개정하라."
    )


@pytest.mark.parametrize(
    "violation",
    [
        'if school_level == "대학":\n    pass\n',
        "if grade_band != '고등':\n    pass\n",
        'x = 1 if grade_band_hint == "고등학교" else 2\n',
        # 피연산자 순서를 뒤집은 동치 표기 — 정규식 가드가 놓친 형태.
        'if "대학" == school_level:\n    pass\n',
        # 값 접근 형태 — L1의 정상 필터와 같은 모양이라 L2~L4에서는 위반이다.
        'if atom.get("school_level") != "대학":\n    pass\n',
        'if row["grade_band"] == "1학년":\n    pass\n',
        "if obj.grade_band_hint != None:\n    pass\n",
        # 감싼 형태.
        'if str(grade_band).lower() == "x":\n    pass\n',
        # 비교 연산자 없이 갈라지는 match 문.
        "match school_level:\n    case 'a':\n        pass\n",
    ],
)
def test_detector_catches_equivalent_branch_forms(violation: str) -> None:
    """변별력 검증(CLAUDE.md "변별력 없는 검증 스텝 금지") — 동치 표기 9종을 전부 잡아야 한다.

    검출기가 아무것도 못 잡는 죽은 코드면 위 스캔 테스트는 상시 그린으로 위장한다.
    """
    assert _scan_source(violation), f"검출기가 위반을 못 잡음(변별력 없음): {violation!r}"


@pytest.mark.parametrize(
    "overlay_lookup",
    [
        "required_depth = _GRADE_BAND_TO_REQUIRED_DEPTH.get(grade_band)\n",  # dict 룩업
        "value = atom.get('school_level')\n",  # 값 읽기만(비교 없음)
        "if grade is not None:\n    pass\n",  # 정수 힌트 — 대상 필드 아님
        "if grade_band is None:\n    pass\n",  # is 비교 — 값 분기 아님
        "if school_level in {'a', 'b'}:\n    pass\n",  # 집합 룩업형
        'if col == "school_level":\n    pass\n',  # 필드명 문자열 디스패치
    ],
)
def test_detector_allows_overlay_parameter_lookups(overlay_lookup: str) -> None:
    """오탐 없음 — 원칙이 권장하는 오버레이 파라미터 룩업은 통과해야 한다."""
    assert not _scan_source(overlay_lookup), f"정상 룩업을 위반으로 오탐: {overlay_lookup!r}"


def test_empty_scan_is_failure_not_pass(tmp_path: Path) -> None:
    """공허한 통과 차단 단언의 변별력 — 계층 부재·파일 0건은 실패, 정상 구성은 통과.

    실제 소스 트리의 계층 디렉터리를 옮겨 검증하면 패키지 import 오류가 먼저 터져 *엉뚱한
    이유의 red*가 된다(2026-10-08 실측: `ModuleNotFoundError: whymath_backend.l2`) — 그래서
    합성 디렉터리로 단언 자체를 직접 검증한다.
    """
    # ① 계층 디렉터리가 하나도 없음.
    with pytest.raises(AssertionError, match="스캔 대상 계층 디렉터리 부재"):
        _require_scanned_layers(tmp_path)

    # ② 디렉터리는 있으나 파일 0건.
    for layer in _SCANNED_LAYERS:
        (tmp_path / layer).mkdir()
    with pytest.raises(AssertionError, match="스캔 파일 0건"):
        _require_scanned_layers(tmp_path)

    # ③ 한 계층만 비어도 실패(전수 요건).
    for layer in _SCANNED_LAYERS[:-1]:
        (tmp_path / layer / "ok.py").write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="스캔 파일 0건"):
        _require_scanned_layers(tmp_path)

    # ④ 대조군 — 세 계층 모두 파일이 있으면 통과.
    (tmp_path / _SCANNED_LAYERS[-1] / "ok.py").write_text("X = 1\n", encoding="utf-8")
    assert set(_require_scanned_layers(tmp_path)) == set(_SCANNED_LAYERS)


def test_scan_wiring_reports_file_and_line(tmp_path: Path) -> None:
    """파일 스캔 배선 검증 — 합성 패키지에서 위반 파일·줄이 실제로 보고되는가.

    위 스캔 테스트는 *지금 소스에 위반이 없다*만 말한다. 이 테스트는 위반이 *생기면* rglob →
    읽기 → 검출 → 보고 전 경로가 그것을 드러내는지(그리고 정상 파일은 건드리지 않는지) 확인한다.
    """
    for layer in _SCANNED_LAYERS:
        (tmp_path / layer).mkdir()
        (tmp_path / layer / "ok.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "l4" / "bad.py").write_text(
        'def f(school_level):\n    if "대학" == school_level:\n        return 1\n    return 0\n',
        encoding="utf-8",
    )
    # 스코프 밖(L1)의 같은 패턴은 보고되지 않아야 한다.
    (tmp_path / "l1").mkdir()
    (tmp_path / "l1" / "loader.py").write_text(
        'def g(atom):\n    return atom.get("school_level") != "대학"\n', encoding="utf-8"
    )

    violations = _collect_violations(tmp_path)

    assert len(violations) == 1, violations
    assert violations[0].startswith("l4/bad.py:2: [school_level]")
