"""CLI `--help`가 터지지 않는가 — argparse의 `%` 포매팅 전수 가드.

왜 이 파일이 있는가
------------------
argparse는 help 문자열을 화면에 내기 전에 **`%`-포매팅한다**(`_expand_help`:
`self._get_help_string(action) % params`). 그래서 help에 리터럴 퍼센트를 그냥 적으면
`--help` **자체가 예외로 죽는다** — 기능은 멀쩡한데 도움말만 폭발하므로, 그 CLI를 처음
쓰는 사람이 가장 먼저 만나는 화면에서 걸린다.

실측 사고(2026-09-06 · MP-02 런북 작성 중 발견): `problem_corpus_accumulate`의
`--canary-threshold` help가 `"...(하한 91.7%)에도..."`였다. `%)`는 유효한 포맷 문자가
아니라서 ::

    python -m whymath_backend.harness.problem_corpus_accumulate --help
    ValueError: unsupported format character ')' (0x29) at index 66

`main` 자체는 정상 동작했으므로 **어떤 테스트도 이것을 잡지 못했다** — 아무도 테스트에서
`--help`를 부르지 않았기 때문이다. 저장소에 argparse CLI가 107개 있고 전부 서브프로세스로
`--help`를 돌리기에는 백엔드 import 비용이 커서, 이 파일은 **argparse가 실제로 하는 연산을
그대로 재현**한다.

무엇을 검사하는가
----------------
`add_argument(..., help=<문자열 리터럴>)`의 그 문자열이 **`%`-포매팅을 통과하는가**.
argparse가 넘기는 params는 `dict(vars(action), prog=...)`라 **키 우주가 정해져 있다** —
Action의 속성 이름들뿐이다. 그 우주를 그대로 넣어 `s % params`를 수행하고
`ValueError`(잘못된 포맷 문자)·`KeyError`(없는 이름)·`TypeError`(변환 불가)를 전부 실패로 센다.

초판은 *어떤 키에도 값을 주는* 매핑을 써서 `%(defualt)s` 같은 **오타를 통과시켰다**
(PR #1017 Codex P2 지적·수용). "모든 입력에서 초록인 가드"가 정확히 그 형태였다 —
선언한 계약("argparse 포매팅을 통과한다")보다 약한 검사였으므로 가드 자신이 위장이었다.

**금지 패턴 열거가 아니다.** "help에 %를 쓰지 마라" 같은 문자열 규칙은 표기 변형
(`%s`·`%%`·`%(default)s`는 전부 정당하다)에서 곧바로 오탐·누락을 낸다. 여기서 보는 것은
**구성된 결과** — 그 문자열이 포매팅되는가 아닌가뿐이다(CLAUDE.md 2026-09-01 ①).

무엇을 검사하지 않는가
--------------------
- `description`·`epilog`: argparse는 이들을 `'%(prog)' in text`일 때만 포매팅하므로
  리터럴 `%`가 있어도 죽지 않는다. 규칙을 넓히면 정상 문서를 red로 만든다.
- 동적으로 조립된 help(변수·함수 호출): AST에서 문자열이 안 보이므로 판정하지 않는다.
  **"내가 찾은 방법으로는 0건"의 범위를 여기 명시**해 둔다 — 이 가드는 리터럴 축만 덮는다.

스캔 0건은 실패다 — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "src" / "backend" / "whymath_backend"

# CLI가 사는 디렉터리. 늘리려면 여기 추가한다(스캔 0건이면 아래에서 예외).
_CLI_DIRS = ("harness", "ops")

# 실측 하한 — 2026-09-06 기준 리터럴 help가 900건 이상이다. 스캐너가 조용히 망가져
# 몇 건만 보게 되는 상태를 막는다(0건만 막으면 "1건 통과"도 공허하게 지나간다).
_MIN_HELP_STRINGS = 400


# argparse가 실제로 넘기는 params의 **키 우주** — `dict(vars(action), prog=...)`이므로
# Action의 속성 이름이 전부이고 그 밖의 이름은 없다(CPython argparse `_expand_help`).
# 여기 없는 이름을 help가 참조하면 argparse는 KeyError로 죽는다 — `%(defualt)s` 같은 오타가
# 정확히 그 경우다.
_ARGPARSE_PARAM_KEYS = frozenset(
    {
        "prog",
        "option_strings",
        "dest",
        "nargs",
        "const",
        "default",
        "type",
        "choices",
        "required",
        "help",
        "metavar",
        "deprecated",
    }
)

# 값은 0으로 준다 — `%(default)s`·`%(default)d`·`%(default).2f` 어느 변환에도 통과하므로
# *변환 지정자 불일치*를 오탐으로 잡지 않는다. 우리가 재려는 것은 값의 타입이 아니라
# **포맷 문자열 자체가 성립하는가**이기 때문이다.
_ARGPARSE_PARAMS: dict[str, object] = {k: 0 for k in _ARGPARSE_PARAM_KEYS}

# argparse가 help 포매팅에서 실제로 던질 수 있는 예외 전부. 하나라도 빼면 그 형태의 결함이
# 조용히 통과한다(초판은 ValueError만 봐서 `%(defualt)s` 오타를 놓쳤다 — PR #1017 Codex P2).
_FORMAT_ERRORS = (ValueError, KeyError, TypeError)


def _string_parts(node: ast.AST) -> list[str]:
    """help= 인자에서 **정적으로 확정되는 문자열 조각**을 모은다.

    다루는 형태: 리터럴, 암묵적 인접 결합(파서가 하나의 Constant로 합쳐 준다),
    `+` 결합, f-string의 상수 구간. f-string의 치환부(`{...}`)는 값이 런타임에 정해지므로
    조각에서 빠지는데, 그래도 **상수 구간에 있는 리터럴 `%`는 잡힌다**(실제 사고가 그
    형태였다 — f-string 안의 고정 문장에 `91.7%`가 있었다).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _string_parts(node.left) + _string_parts(node.right)
    return []


def _collect_help_strings() -> list[tuple[Path, int, str]]:
    """(파일, 줄번호, help 문자열 조각) 전건."""
    found: list[tuple[Path, int, str]] = []
    missing_dirs = [d for d in _CLI_DIRS if not (_BACKEND / d).is_dir()]
    if missing_dirs:
        raise AssertionError(
            f"CLI 디렉터리가 사라졌다: {missing_dirs} — 옮겼다면 _CLI_DIRS를 고쳐라. "
            "대상을 못 찾은 스캔은 '위반 0'이 아니라 측정 실패다."
        )
    for directory in _CLI_DIRS:
        for path in sorted((_BACKEND / directory).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else None
                if name != "add_argument":
                    continue
                for kw in node.keywords:
                    if kw.arg != "help":
                        continue
                    for part in _string_parts(kw.value):
                        found.append((path, node.lineno, part))
    return found


def test_scan_finds_the_cli_surface() -> None:
    """스캔 자체가 살아 있는가 — 0건·소수 건은 통과가 아니라 측정 실패다."""
    strings = _collect_help_strings()
    assert len(strings) >= _MIN_HELP_STRINGS, (
        f"help 문자열을 {len(strings)}건밖에 못 찾았다(하한 {_MIN_HELP_STRINGS}) — "
        "스캐너나 경로가 깨졌다. 이 상태의 '위반 0'은 아무것도 보증하지 않는다."
    )


def test_every_help_string_survives_argparse_percent_formatting() -> None:
    """argparse가 하는 그대로 `%`-포매팅해 본다 — 죽으면 그 CLI의 `--help`가 죽는다."""
    broken: list[str] = []
    for path, lineno, text in _collect_help_strings():
        if "%" not in text:
            continue
        try:
            text % _ARGPARSE_PARAMS
        except _FORMAT_ERRORS as exc:
            rel = path.relative_to(_REPO_ROOT)
            broken.append(f"{rel}:{lineno} — {type(exc).__name__}: {exc} · 원문 {text!r}")
    assert not broken, (
        "argparse가 help를 %-포매팅할 때 터지는 문자열이 있다 — 해당 CLI는 `--help`만 쳐도 "
        "ValueError로 죽는다. 리터럴 퍼센트는 `%%`로 이스케이프하라(화면에는 `%` 하나로 "
        "보인다).\n  " + "\n  ".join(broken)
    )


@pytest.mark.parametrize(
    ("text", "should_raise"),
    [
        ("만점 30/30(하한 91.7%)에도", True),  # 실제 사고 문자열 — 반드시 잡혀야 한다
        ("만점 30/30(하한 91.7%%)에도", False),  # 올바른 이스케이프
        ("기본 %(default)s", False),  # argparse 관용 표기
        ("퍼센트 없음", False),
        ("끝에 걸친 %", True),  # 불완전한 포맷 지정자
        ("오타 %(defualt)s", True),  # KeyError — argparse의 키 우주에 없는 이름
        ("없는 이름 %(canary_size)s", True),  # KeyError — 우리 도메인 이름은 params가 아니다
        ("정수 변환 %(default)d", False),  # 값이 int라 통과 — 변환 지정자를 오탐하지 않는다
    ],
)
def test_the_detector_itself_discriminates(text: str, should_raise: bool) -> None:
    """탐지기가 정상·결함을 실제로 **가르는가** — 양쪽에서 같은 값을 내면 위장이다."""
    raised = False
    try:
        text % _ARGPARSE_PARAMS
    except _FORMAT_ERRORS:
        raised = True
    assert raised is should_raise, f"탐지기 변별력 상실: {text!r} 에서 raised={raised}"
