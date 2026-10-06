"""PR 템플릿(`.github/pull_request_template.md`) 계약 동결.

왜 이 테스트가 있는가
--------------------
이번 세션 사고 7건의 공통 구조는 "검증 장치가 있다고 믿었으나 실제로는 작동하지 않았고,
'작동하는지'를 확인하는 장치가 없었다"였다. 재발 방지의 절반은 기계 게이트(→
`test_test_suite_wiring.py`)지만, 나머지 절반 — **무엇을 깨뜨려 확인했는가**를 사람이 PR에
남기는 습관 — 은 기계가 대신할 수 없다. 그 습관을 기억이 아니라 **양식**에 건다.

**이 테스트가 하는 일과 하지 않는 일 (정직 기술)**
- 한다: 템플릿이 *GitHub가 실제로 읽는 경로*에 존재하고, 핵심 절(변별력·정직한 공백·검증)이
  살아 있으며, 아무도 안 채울 만큼 길어지지 않았음을 동결한다.
- **하지 않는다**: 실제 PR 본문이 채워졌는지는 보지 않는다(이 저장소 CI는 PR 본문을 읽지
  않는다). 즉 이것은 게이트가 아니라 **프롬프트의 무결성 동결**이다 — 그 이상으로 주장하면
  "측정 없는 기계 게이트를 검수 대체로 선언"하는 것이 된다(CLAUDE.md).

**HARN-104 — 분류 3줄(Release Classification·Layer·Contract impact)의 채움 강제 판정**
- 판정: **이번에는 강제하지 않는다.** 기존 4절도 CI가 본문을 읽지 않으므로 같은 한계를 공유하며,
  본문 검사 워크플로를 새로 만드는 것은 근거(빈 칸이 실제로 얼마나 나오는지)가 없는 추측 구현이다.
- 이 테스트가 동결하는 것은 *칸의 존재와 값 어휘*뿐이다 — 어휘는 대장 정본(`selector._EOS_RANK`)
  및 7계층과 어긋나지 않는지만 본다. 채워졌는지는 보지 않는다.
- 재개 조건: 머지된 PR 본문 표본에서 이 3줄이 비어 있는 비율이 측정으로 높게 나오면 본문 검사를
  별도 태스크로 등재한다(지금은 측정 전이라 등재하지 않는다).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
# GitHub이 PR 본문 기본값으로 읽는 경로는 이 세 곳뿐이다(루트·.github·docs).
_TEMPLATE = _REPO_ROOT / ".github" / "pull_request_template.md"

# 반드시 살아 있어야 하는 절 → 그 절이 막는 사고. 제목 문구가 바뀌면 여기도 함께 바꾼다.
_REQUIRED_SECTIONS: dict[str, str] = {
    "변별력": "검증이 실패 상태에서 실제로 실패하는지 확인 없이 '통과'를 보고하던 패턴",
    "정직한 공백": "측정하지 못한 것을 침묵으로 덮던 패턴",
    "검증": "무엇을 돌렸는지·수치 없이 '테스트 통과'만 적던 패턴",
}

# 긴 템플릿은 아무도 채우지 않는다 — 실효성 자체가 길이에 달려 있어 상한을 계약으로 건다.
_MAX_LINES = 60
_MAX_SECTIONS = 5

# HARN-104 — 분류 3줄. 대장에 실재하는 값 어휘를 쓰므로(자유 서술이 아니다) 라벨과 어휘를 함께 동결한다.
_CLASSIFICATION_LABELS = ("Release Classification", "Layer", "Contract impact")
_LAYER_CODES = tuple(f"L{n}" for n in range(1, 8))  # 7계층 L1~L7
_SELECTOR = _REPO_ROOT / "scripts" / "harness" / "selector.py"


def _template_text() -> str:
    """템플릿 본문. **부재는 예외**다 — 없는데 조용히 통과하면 이 파일 전체가 위장이 된다."""
    if not _TEMPLATE.is_file():
        # 변별력 테스트가 tmp 경로를 주입하므로 relative_to를 무조건 쓰면 안 된다(ValueError).
        shown = (
            _TEMPLATE.relative_to(_REPO_ROOT) if _TEMPLATE.is_relative_to(_REPO_ROOT) else _TEMPLATE
        )
        raise AssertionError(
            f"{shown}가 없다 — GitHub이 PR 본문 기본값을 채우지 못한다"
            "(2026-07-27 이전의 실제 상태)."
        )
    return _TEMPLATE.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def test_pr_template_exists_where_github_reads_it() -> None:
    """계약 ① — 파일이 GitHub이 읽는 경로에 실재한다(다른 곳에 두면 아무 효과가 없다)."""
    assert _template_text().strip(), "PR 템플릿이 비어 있다."


def test_pr_template_keeps_the_sections_that_earn_their_place() -> None:
    """계약 ② — 반복해서 뚫린 지점을 묻는 절이 살아 있다.

    실패 = 템플릿이 형식적 체크리스트로 퇴화했다는 뜻이다. 각 절은 그것이 막는 사고와 함께
    등재돼 있다(사고 없는 절은 넣지 않는다 — 길이 예산이 곧 실효성이다).
    """
    headings = " · ".join(_headings(_template_text()))
    missing = {name: why for name, why in _REQUIRED_SECTIONS.items() if name not in headings}
    assert not missing, f"PR 템플릿에서 사라진 절: {missing}\n현재 절: {headings}"


def test_pr_template_stays_short_enough_to_be_filled() -> None:
    """계약 ③ — 길이 상한. 긴 템플릿은 채워지지 않고, 안 채워진 양식은 없는 것과 같다."""
    text = _template_text()
    lines = len(text.splitlines())
    sections = _headings(text)
    assert lines <= _MAX_LINES, f"PR 템플릿이 {lines}줄 — 상한 {_MAX_LINES}줄을 넘겼다."
    assert len(sections) <= _MAX_SECTIONS, f"절이 {len(sections)}개 — 상한 {_MAX_SECTIONS}개."


def test_pr_template_forbids_blank_discriminability_answer() -> None:
    """계약 ④ — '해당 없음'으로 빠져나가지 말라는 지시가 템플릿 안에 명시돼 있어야 한다.

    빈칸 허용은 곧 그 칸의 폐지다(OPS-06·OPS-08의 '사유 필수' 허용 목록과 같은 취지).
    """
    text = _template_text()
    assert "해당 없음" in text and "왜" in text, (
        "변별력 칸에 '해당 없음이면 그 이유를 쓰라'는 지시가 없다 — 빈칸으로 통과하는 칸은 "
        "곧 사라진다."
    )


def _eos_priority_vocabulary() -> tuple[str, ...]:
    """대장 정본의 eos_priority 어휘 — `selector._EOS_RANK` 의 키. import 하지 않고 AST 로 읽는다."""
    tree = ast.parse(_SELECTOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target == "_EOS_RANK" and isinstance(value, ast.Dict):
            keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
            if keys:
                return tuple(str(k) for k in keys)
    raise AssertionError("selector._EOS_RANK 를 못 찾았다 — 정본 어휘가 사라졌거나 이동했다.")


def _classification_block(text: str) -> str:
    """분류 3줄 구간 — 첫 절 머리에서 다음 `## ` 절 직전까지(3줄의 라벨이 모두 이 안에 있어야 한다)."""
    start = text.find("## ")
    assert start >= 0, "템플릿에 절이 없다."
    nxt = text.find("\n## ", start + 3)
    return text[start : nxt if nxt >= 0 else len(text)]


def test_pr_template_has_the_three_eos_classification_lines() -> None:
    """계약 ⑤ (HARN-104) — Release Classification·Layer·Contract impact 3줄이 첫 절 안에 살아 있다.

    새 `##` 절이 아니라 첫 절 안의 3줄이다 — 절 수 상한(계약 ③)을 건드리지 않고 길이 예산을 지킨다.
    """
    block = _classification_block(_template_text())
    missing = [label for label in _CLASSIFICATION_LABELS if f"**{label}**" not in block]
    assert not missing, f"PR 템플릿 첫 절에서 사라진 분류 줄: {missing}"


def test_classification_vocabulary_matches_the_ledger() -> None:
    """계약 ⑥ (HARN-104) — 칸의 값 어휘가 대장 정본(eos_priority)·7계층과 같다.

    어휘가 대장과 어긋나면 사람이 존재하지 않는 등급을 적게 된다(빈 칸보다 나쁜 칸).
    """
    block = _classification_block(_template_text())
    vocab = _eos_priority_vocabulary()
    assert vocab == ("P0", "P1", "P2", "P3"), f"대장 eos_priority 어휘가 바뀌었다: {vocab}"
    absent = [v for v in (*vocab, *_LAYER_CODES) if v not in block]
    assert not absent, f"분류 칸에 안내되지 않은 값: {absent}"


def test_gutted_classification_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """변별력 봉인 (HARN-104) — 분류 3줄이 없는 템플릿·어휘가 빠진 템플릿이 실제로 검출되는가."""
    text = _template_text()
    gutted = tmp_path / "pull_request_template.md"
    monkeypatch.setattr(__name__ + "._TEMPLATE", gutted, raising=True)

    # 라벨 하나 삭제 → ⑤ 검출
    gutted.write_text(text.replace("**Layer**", "Layer"), encoding="utf-8")
    with pytest.raises(AssertionError, match="사라진 분류 줄"):
        test_pr_template_has_the_three_eos_classification_lines()

    # 계층 어휘 L7 삭제 → ⑥ 검출
    assert "L7" in text
    gutted.write_text(text.replace("L7", "L_"), encoding="utf-8")
    with pytest.raises(AssertionError, match="안내되지 않은 값"):
        test_classification_vocabulary_matches_the_ledger()

    # 등급 어휘 P3 삭제 → ⑥ 검출
    gutted.write_text(text.replace("P3", "P_"), encoding="utf-8")
    with pytest.raises(AssertionError, match="안내되지 않은 값"):
        test_classification_vocabulary_matches_the_ledger()


def test_missing_template_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """변별력 봉인 — 템플릿이 사라진 상태에서 이 검사들이 *실제로* 실패 신호를 내는가.

    성공/실패 양쪽에서 같은 값을 내는 검사는 위장이다(CLAUDE.md). 실제 파일을 지우지 않고
    경로만 없는 곳으로 바꿔 실패 경로를 실행한다.
    """
    monkeypatch.setattr(__name__ + "._TEMPLATE", tmp_path / "없는파일.md", raising=True)
    with pytest.raises(AssertionError, match="GitHub이 PR 본문 기본값"):
        _template_text()


def test_gutted_template_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """변별력 봉인 — 절을 들어낸 템플릿이 실제로 검출되는가(무차별 통과가 아님)."""
    gutted = tmp_path / "pull_request_template.md"
    gutted.write_text("## 무엇을 · 왜\n\n## 검증\n", encoding="utf-8")
    monkeypatch.setattr(__name__ + "._TEMPLATE", gutted, raising=True)
    with pytest.raises(AssertionError, match="사라진 절"):
        test_pr_template_keeps_the_sections_that_earn_their_place()
