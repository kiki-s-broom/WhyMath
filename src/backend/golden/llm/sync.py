"""골든 LLM 복사본 동기화 검사 — 옛 원본이 바뀌었는데 골든 복사본이 그대로면 알려 준다(GOLD-20).

실행: `cd src/backend && python -m golden.llm.sync`
(같으면 exit 0 · 갈라졌으면 갈라진 파일 이름을 출력하고 exit 1)

왜 필요한가: `golden/llm/`의 4파일은 옛 `whymath_backend/l3/providers/`를 그대로 복사한 것이라
(S20A 2일째), 옛 쪽에서 버그를 고치거나 계약(재시도 상태코드·요청 본문·관할 표)을 바꿔도 골든에는
들어오지 않는다. 특성화 테스트는 *정해 둔 입력 10개*의 출력만 비교하므로 그 밖의 변경을 놓친다.
이 검사는 입력이 아니라 **코드 자체**를 비교한다.

비교 방법(파이썬 구문 트리 · `ast`):
- 골든 쪽은 모듈 설명 안의 복사 표기 문단(`[골든 복사본 …]`)을 빼고 읽는다.
- import 경로는 `_MODULE_MAP`대로 바꿔 읽는다(복사 때 바꾼 것은 그것뿐이다).
- 파일 맨 위 import 문은 순서를 무시한다(ruff가 골든 쪽 순서를 다시 정렬한다).
- 주석·빈 줄은 구문 트리에 없으므로 비교하지 않는다 — 주석만 고친 옛 변경은 RED가 아니다.
그 밖의 모든 차이(상수·분기·문자열·함수 추가)는 갈라짐으로 본다.

갈라졌을 때: 옛 파일을 다시 복사해 import 줄만 `_MODULE_MAP`대로 바꾸고, 맨 위 복사 표기 문단을
다시 넣은 뒤 `tests/golden/characterization/`을 돌린다. 옛 변경을 일부러 따르지 않기로 했으면 그
이유를 HARVEST.md에 적고 이 검사의 대상에서 뺀다(조용히 무시하지 않는다).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_LEGACY_DIR = _BACKEND / "whymath_backend" / "l3" / "providers"
_GOLDEN_DIR = Path(__file__).resolve().parent

# 복사한 파일 4개(옛 이름 = 골든 이름)
COPIED_FILES: tuple[str, ...] = (
    "_response_fields.py",
    "seat_failure.py",
    "_openai_compat.py",
    "openrouter.py",
)

# 복사할 때 바꾼 import 경로(옛 → 골든) — 이것 말고는 바꾼 것이 없어야 한다
_MODULE_MAP: dict[str, str] = {
    "whymath_backend.l3.providers._response_fields": "golden.llm._response_fields",
    "whymath_backend.l3.providers.seat_failure": "golden.llm.seat_failure",
    "whymath_backend.l3.providers._openai_compat": "golden.llm._openai_compat",
}

# 골든 복사본 모듈 설명에 넣은 표기 문단의 첫머리
_HEADER_MARK = "[골든 복사본"


def _strip_copy_header(docstring: str) -> str:
    """모듈 설명에서 복사 표기 문단 하나를 뺀다. 없으면 오류(표기가 사라진 복사본은 비교 불가)."""
    paragraphs = docstring.split("\n\n")
    marked = [i for i, p in enumerate(paragraphs) if p.startswith(_HEADER_MARK)]
    if len(marked) != 1:
        raise ValueError(f"복사 표기 문단이 {len(marked)}개다(1개여야 한다)")
    del paragraphs[marked[0]]
    return "\n\n".join(paragraphs)


def normalized(source: str, *, golden: bool) -> str:
    """비교용 정규형 — 구문 트리 문자열. golden=True면 복사 표기를 빼고 import 경로를 되돌린다."""
    tree = ast.parse(source)
    if golden:
        first = tree.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)):
            raise ValueError("골든 복사본이 모듈 설명으로 시작하지 않는다")
        first.value.value = _strip_copy_header(str(first.value.value))
        reverse = {new: old for old, new in _MODULE_MAP.items()}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in reverse:
                node.module = reverse[node.module]
    # 맨 위 import 문은 순서를 무시한다 — 정렬해서 그 자리에 다시 놓는다
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    ordered = iter(sorted(imports, key=ast.dump))
    tree.body = [
        next(ordered) if isinstance(n, (ast.Import, ast.ImportFrom)) else n for n in tree.body
    ]
    return ast.dump(tree)


def drifted(
    legacy_dir: Path = _LEGACY_DIR, golden_dir: Path = _GOLDEN_DIR
) -> list[tuple[str, str]]:
    """갈라진 파일 목록 — (파일 이름, 사유). 비었으면 전부 같다."""
    out: list[tuple[str, str]] = []
    for name in COPIED_FILES:
        legacy_path, golden_path = legacy_dir / name, golden_dir / name
        if not legacy_path.exists():
            out.append((name, "옛 원본이 없다(지워졌거나 옮겨졌다)"))
            continue
        legacy = normalized(legacy_path.read_text(encoding="utf-8"), golden=False)
        mine = normalized(golden_path.read_text(encoding="utf-8"), golden=True)
        if legacy != mine:
            out.append((name, "옛 원본과 코드가 다르다"))
    return out


def main() -> int:
    """검사를 돌리고 결과를 한 줄씩 출력한다. 같으면 0, 갈라졌으면 1."""
    found = drifted()
    if not found:
        print(f"골든 LLM 복사본 {len(COPIED_FILES)}개 모두 옛 원본과 같다")
        return 0
    for name, reason in found:
        print(f"갈라짐: golden/llm/{name} — {reason}")
    print("다시 맞추는 절차: golden/llm/sync.py 모듈 설명")
    return 1


if __name__ == "__main__":
    sys.exit(main())
