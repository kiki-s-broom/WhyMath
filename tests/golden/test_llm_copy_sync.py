"""골든 LLM 복사본 동기화 동결(GOLD-20) — 옛 원본이 바뀌면 이 테스트가 RED가 된다.

`golden/llm/` 4파일은 옛 `whymath_backend/l3/providers/`의 복사본이다. 옛 쪽이 코드를 바꾸면(주석만
바꾼 것은 제외) 골든도 다시 맞춰야 한다 — 절차는 `golden/llm/sync.py` 모듈 설명에 있다.
아래 변별력 테스트가 "갈라지면 실제로 잡는다"와 "주석만 바뀌면 잡지 않는다"를 함께 고정한다.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from golden.llm import sync


def test_golden_llm_copies_match_legacy_originals() -> None:
    assert (
        sync.drifted() == []
    ), "옛 프로바이더 원본이 바뀌었다 — golden/llm/의 복사본을 다시 맞춘다(golden/llm/sync.py 참고)"


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """옛 원본·골든 복사본을 임시 폴더로 복사한다(실제 파일은 건드리지 않는다)."""
    legacy, golden = tmp_path / "legacy", tmp_path / "golden"
    legacy.mkdir()
    golden.mkdir()
    for name in sync.COPIED_FILES:
        shutil.copy(sync._LEGACY_DIR / name, legacy / name)  # noqa: SLF001
        shutil.copy(sync._GOLDEN_DIR / name, golden / name)  # noqa: SLF001
    assert sync.drifted(legacy, golden) == []  # 출발점은 같다
    return legacy, golden


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"주입 대상 {old!r}가 1건이 아니다"
    path.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        # 옛 쪽 계약 변경 — 재시도 상태코드에서 429를 뺌
        ("_openai_compat.py", "408, 409, 425, 429, 500", "408, 409, 425, 500"),
        # 옛 쪽 관할 표 변경 — 공급사 하나를 국적 미상으로
        ("openrouter.py", '"fireworks": Jurisdiction.US,', ""),
        # 옛 쪽 분류 변경
        ("seat_failure.py", 'return "not_configured"', "return None"),
    ],
)
def test_detects_legacy_code_change(dirs: tuple[Path, Path], name: str, old: str, new: str) -> None:
    legacy, golden = dirs
    _edit(legacy / name, old, new)
    assert [n for n, _ in sync.drifted(legacy, golden)] == [name]


def test_detects_legacy_file_removed(dirs: tuple[Path, Path]) -> None:
    legacy, golden = dirs
    (legacy / "openrouter.py").unlink()
    assert [n for n, _ in sync.drifted(legacy, golden)] == ["openrouter.py"]


def test_ignores_comment_only_and_import_order_changes(dirs: tuple[Path, Path]) -> None:
    legacy, golden = dirs
    # 주석만 바뀐 옛 변경은 동작이 같으므로 잡지 않는다
    _edit(legacy / "_openai_compat.py", "import asyncio\n", "import asyncio  # 주석 추가\n")
    # 골든 쪽 import 순서 바뀜(ruff 정렬)도 잡지 않는다
    _edit(golden / "_response_fields.py", "from typing import Any\n", "")
    _edit(
        golden / "_response_fields.py",
        "from __future__ import annotations\n",
        ("from __future__ import annotations\n\nfrom typing import Any\n"),
    )
    assert sync.drifted(legacy, golden) == []


def test_missing_copy_header_is_an_error(dirs: tuple[Path, Path]) -> None:
    # 복사 표기가 사라진 골든 파일은 무엇과 비교해야 하는지 모르므로 조용히 통과하지 않는다
    _, golden = dirs
    _edit(golden / "seat_failure.py", sync._HEADER_MARK, "[다른 표기")  # noqa: SLF001
    with pytest.raises(ValueError, match="복사 표기"):
        sync.drifted(dirs[0], golden)
