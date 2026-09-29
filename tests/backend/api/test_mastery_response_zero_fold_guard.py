"""[EOS-17] 응답 경계가 숙달의 None을 숫자로 접지 않는다 — `api/` 전수 AST 가드.

숙달 계약(`docs/architecture/mastery_update_contract_v1.md`)은 미측정을 None으로 지킨다. 응답을
만드는 `api/` 모듈이 그 None을 `mastery=x if x is not None else 0.0` · `mastery=x or 0.0` 같은
형태로 숫자로 바꾸면, 클라이언트는 "모른다"와 "숙달 0"을 구분할 수 없다. EOS-17 전까지
`api/me.py::submit_attempt`의 개념·스킬 숙달 갱신 응답이 정확히 이 형태였다.

검사 대상
---------
키워드 인자 이름 또는 딕셔너리 문자열 키가 `mastery`이거나 `_mastery`로 끝나는 자리
(`mastery` · `bkt_mastery` 등). 그 값 식 **안 어디에든** ⑴ 한쪽 가지가 숫자 상수인 조건식
(`A if 조건 else 0.0` · `0.0 if 조건 else A`) ⑵ 숫자 상수를 피연산자로 가진 `or`
(`A or 0.0` · `float(A or 0)`)가 있으면 위반이다.

대상이 아닌 것(의도)
--------------------
- 이름이 `mastery`로 끝나지 않는 자리 — `mastery_level`(등급 사상)·`sample_size`(관측 수)·
  `irt_mastery_proxy`. 관측 수의 "없음 = 0"은 사실일 수 있어 이 가드의 축이 아니다.
- 응답 값이 아닌 자리 — 정렬 키 람다(`key=lambda i: i.mastery if … else 0.0`)처럼 키워드
  이름이 `key`인 자리는 보지 않는다.
- `api/` 밖 — 내부 계산(추정기·정렬)은 None을 숫자로 다루는 것이 설계일 수 있다. 응답 경계만
  이 가드의 관할이다.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_API_DIR = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "api"

#: 숙달 값을 담는 이름 — `mastery` 자체이거나 `_mastery`로 끝난다(`bkt_mastery`).
_MASTERY_NAME = re.compile(r"(?:^|_)mastery$")


def _is_number(node: ast.AST) -> bool:
    """숫자 상수인가 — `bool`은 `int`의 하위형이지만 숫자 접기가 아니므로 제외한다."""
    return isinstance(node, ast.Constant) and type(node.value) in (int, float)


def _folds_to_number(value: ast.AST) -> bool:
    """값 식 안에 None을 숫자로 접는 형태가 있는가 — 호출 인자 속까지 내려간다."""
    for node in ast.walk(value):
        if isinstance(node, ast.IfExp) and (_is_number(node.body) or _is_number(node.orelse)):
            return True
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_is_number(operand) for operand in node.values):
                return True
    return False


def zero_fold_violations(source: str, *, path: str) -> list[str]:
    """숙달 이름 자리에 숫자 접기가 있는 곳을 찾는다 (순수 함수)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.keyword) and node.arg and _MASTERY_NAME.search(node.arg):
            if _folds_to_number(node.value):
                found.append(f"{path}:{node.value.lineno} {node.arg}= 가 None을 숫자로 접는다")
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and _MASTERY_NAME.search(key.value)
                    and _folds_to_number(value)
                ):
                    found.append(f"{path}:{value.lineno} '{key.value}' 키가 None을 숫자로 접는다")
    return found


def test_api_responses_do_not_fold_mastery_none_to_a_number() -> None:
    """`api/` 전수 — 숙달 이름 자리에 None→숫자 접기가 0건이다."""
    files = sorted(_API_DIR.rglob("*.py"))
    assert files, f"스캔 대상이 0개다 — 공허 통과 금지: {_API_DIR}"
    violations: list[str] = []
    for path in files:
        violations += zero_fold_violations(
            path.read_text(encoding="utf-8"), path=str(path.relative_to(_REPO_ROOT))
        )
    assert violations == [], "숙달의 None을 숫자로 접는 응답 경계:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # 위반 — 절마다 그 절이 없으면 통과하는 반례를 둔다.
        ("F(mastery=m if m is not None else 0.0)", 1),  # EOS-17 전 submit_attempt의 형태
        ("F(mastery=0.0 if m is None else m)", 1),  # 가지를 뒤집은 형태
        ("F(mastery=m or 0.0)", 1),  # `or` 접기
        ("F(bkt_mastery=float(m or 0))", 1),  # 호출 인자 속 · `_mastery` 접미 · int 상수
        ("x = {'mastery': m if m is not None else 0}", 1),  # 딕셔너리 키
        # 통과 — 올바른 형태와 관할 밖 자리.
        ("F(mastery=float(m) if m is not None else None)", 0),  # None을 None으로 둔다
        ("F(mastery_level=lvl if lvl is not None else 0)", 0),  # 이름이 mastery로 끝나지 않음
        ("F(sample_size=n if n is not None else 0)", 0),  # 관측 수 — 이 가드의 축 아님
        ("sorted(xs, key=lambda i: i.mastery if i.mastery is not None else 0.0)", 0),  # 정렬 키
        ("F(mastery=m if flag else True)", 0),  # bool 상수는 숫자 접기가 아니다
    ],
)
def test_zero_fold_checker_discriminates(source: str, expected: int) -> None:
    """검사기의 변별력 — 위반 형태는 잡고, 올바른 형태·관할 밖 자리는 통과시킨다."""
    assert len(zero_fold_violations(source, path="x.py")) == expected
