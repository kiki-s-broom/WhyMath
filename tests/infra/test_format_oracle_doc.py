"""포맷·린트 오라클 절차 문서(HARN-110)가 **4축 + ruff 한계를 담고 있는가** 동결.

문서: `docs/standards/format_lint_oracle_offline.md`

**검사한다**
- 조립·버전 특정·정합 확인·표시 폭·ruff 한계가 **각자의 절 안에** 있는가. 문서 어딘가에 단어가
  있는 것으로는 부족하다 — 다른 절로 옮겨 붙으면 그 절은 비어 있어도 통과하기 때문이다.
- §4의 `black --check` 인자가 `ci.yml`의 실제 명령과 **글자까지 같은가**. CI 명령이 바뀌었는데
  문서가 옛 명령을 가르치면 오라클 정합 확인이 다른 것을 재게 된다.
- §2의 핀 범위가 `src/backend/pyproject.toml`의 black 핀과 같은가.

**검사하지 않는다**
- 조립 절차가 **실제로 도는가.** 그건 네트워크·외부 코드 실행이 필요해 CI에서 재현할 수 없다.
  문서 자신이 어디까지 실측했는지 맨 위 표에 적었고, 이 테스트는 그 표가 있는지만 본다.

**파서가 위장하지 않는다** — 절이 없거나 CI에서 black 명령을 0건 찾으면 "위반 0 통과"가
아니라 **실패**한다(스캔 0건은 실패). 그 실패 자체를 아래 음성 테스트로 못박는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "standards" / "format_lint_oracle_offline.md"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_BACKEND_PYPROJECT = _REPO_ROOT / "src" / "backend" / "pyproject.toml"

# 절 번호 → 그 절에 반드시 있어야 하는 토큰. 축을 지우거나 다른 절로 옮기면 red.
_SECTION_TOKENS: dict[int, tuple[str, ...]] = {
    # ① 조립 — 의존성 6종·스텁 2종·PYTHONPATH
    # 설명 문장에도 나오는 단어가 아니라 **명령 형태**를 요구한다(저장소 slug 추측이 사고 원인이었다)
    3: (
        "export PYTHONPATH=",
        "clone psf/black",
        "clone pallets/click",
        "clone pypa/packaging",
        "clone cpburnz/python-pathspec",
        "clone tox-dev/platformdirs",
        "clone python/mypy_extensions",
        "clone tusharsadhwani/pytokens",
        "black-src/src/_black_version.py",
        "platformdirs-src/src/platformdirs/version.py",
    ),
    # ② 버전 특정 — 추측하지 않고 태그로 고른다
    2: ("git ls-remote --tags", "추측하지 않는다"),
    # ③ 정합 확인 — 차이 0건이 아니면 CI와 다른 버전
    4: ("정합 확인", "would reformat", "종료 코드", "CI와 다른 버전"),
    # ④ 표시 폭 — 문자 수가 아니다
    5: (
        "표시 폭",
        "East Asian Width",
        "str_width",
        "char_width",
        "19자인데 폭은 33",
        "문자 수가 아니라",
    ),
    # ⑤ ruff 한계 — 대안이 없으면 없다고 적는다
    6: ("Rust", "확인된 대안: 없음", "ruff 미실행"),
}

_SECTION_RE = re.compile(r"^## (\d+)\. ", re.MULTILINE)
_CI_BLACK_RE = re.compile(r"black --check (--line-length 100 [^\n]+)")


def _sections(doc: str) -> dict[int, str]:
    """`## N. 제목` 단위로 본문을 나눈다. 절이 하나도 없으면 예외(빈 결과 통과 금지)."""
    marks = list(_SECTION_RE.finditer(doc))
    if not marks:
        raise ValueError("문서에서 '## N. ' 형식의 절을 하나도 찾지 못했다")
    out: dict[int, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(doc)
        out[int(m.group(1))] = doc[m.end() : end]
    return out


def _missing(sections: dict[int, str], required: dict[int, tuple[str, ...]]) -> list[str]:
    """절별로 빠진 토큰을 '§절:토큰' 목록으로 낸다. 절이 없으면 그 절의 전 토큰이 빠진 것."""
    missing: list[str] = []
    for num, tokens in required.items():
        body = sections.get(num, "")
        missing += [f"§{num}:{t}" for t in tokens if t not in body]
    return missing


def _ci_black_args() -> set[str]:
    """`ci.yml`의 `black --check` 명령에서 `--line-length 100 …` 이후 인자를 모은다."""
    text = _CI.read_text(encoding="utf-8")
    args = {m.group(1).strip() for m in _CI_BLACK_RE.finditer(text)}
    if not args:
        raise ValueError("ci.yml에서 black --check 명령을 하나도 찾지 못했다(스캔 0건)")
    return args


@pytest.fixture(scope="module")
def doc_text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_each_axis_lives_in_its_own_section(doc_text: str) -> None:
    missing = _missing(_sections(doc_text), _SECTION_TOKENS)
    assert missing == [], f"절 안에 없는 토큰: {missing}"


def test_doc_states_what_was_and_was_not_measured(doc_text: str) -> None:
    # 실측하지 않은 것을 통과처럼 읽히게 두지 않는다 — 맨 위 표의 두 표지가 있어야 한다
    assert "실측 범위" in doc_text
    assert "미실측" in doc_text


def test_sections_are_present_in_order(doc_text: str) -> None:
    nums = [int(n) for n in _SECTION_RE.findall(doc_text)]
    assert nums == sorted(nums) and set(_SECTION_TOKENS) <= set(nums)


def test_verification_commands_match_ci(doc_text: str) -> None:
    body = _sections(doc_text)[4]
    ci_args = _ci_black_args()
    # 문서의 명령 각각이 CI 인자와 같아야 하고 CI 인자 각각도 문서에 있어야 한다(양방향)
    found = [m.group(1) for m in _CI_BLACK_RE.finditer(body)]
    doc_args = {f.split(" > ")[0].strip() for f in found}
    only_doc = sorted(doc_args - ci_args)
    only_ci = sorted(ci_args - doc_args)
    assert doc_args == ci_args, f"문서에만: {only_doc} / CI에만: {only_ci}"


def test_doc_pin_matches_pyproject(doc_text: str) -> None:
    pin = re.search(r'"(black>=[^"]+)"', _BACKEND_PYPROJECT.read_text(encoding="utf-8"))
    assert pin is not None, "pyproject에서 black 핀을 찾지 못했다"
    # 핀 표기는 `black>=24.10.0,<27`인데 문서는 백틱 안에 하한·상한을 적는다
    assert pin.group(1).replace("black", "", 1) in _sections(doc_text)[2].replace(" ", "")


# ── 음성 테스트: 검사기가 위장하지 않는지(절 제거·이동·CI 스캔 0건) ─────────────────────────


def test_negative_removed_section_is_reported(doc_text: str) -> None:
    sections = _sections(doc_text)
    del sections[5]
    assert any(s.startswith("§5:") for s in _missing(sections, _SECTION_TOKENS))


def test_negative_token_moved_to_other_section_is_reported(doc_text: str) -> None:
    sections = _sections(doc_text)
    sections[3] = sections[3] + "표시 폭 East Asian Width str_width 문자 수가 아니라"
    sections[5] = ""
    assert any(s.startswith("§5:") for s in _missing(sections, _SECTION_TOKENS))


def test_negative_doc_without_sections_raises() -> None:
    with pytest.raises(ValueError):
        _sections("절 없는 문서")


def test_negative_ci_without_black_command_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Fake:
        @staticmethod
        def read_text(encoding: str = "utf-8") -> str:
            return "steps: []"

    monkeypatch.setitem(globals(), "_CI", _Fake)
    with pytest.raises(ValueError):
        _ci_black_args()
