"""[OPS-59] CI 워크플로의 **실행기 단독 호출 금지** — 전 워크플로·전 잡 동결.

왜 이 테스트가 있는가
--------------------
CLAUDE.md 규칙: `pip`·`pytest`·`alembic` 같은 실행기(launcher)를 단독 호출하지 않고 항상
`python -m pip` / `python -m pytest` 형태로 `python`과 같은 인터프리터에 못 박는다. 다중 환경
(conda base + .venv)에서는 단독 런처가 다른 인터프리터에 결합될 수 있다(2026-07-27 ARCH-16 실측:
`pip install`이 miniconda 쪽으로 실행돼 `.venv` python이 못 보는 곳에 설치).

PR #956(EOS-64)은 이 규칙을 e2e-nightly 잡 하나에만 적용했고 검사(`_invokes_pytest_via_python_module`)
도 그 잡만 봤다. 규칙이 있는데 절반만 검사하면 나머지 절반은 조용히 되돌아간다 — 이 파일이
검사 범위를 **`.github/workflows/*.yml` 전 잡의 전 `run` 스텝**과 **pytest 외 실행기 전부**로 넓힌다.

판정 방식 (금지 문자열 열거가 아니라 *명령 위치*를 본다)
------------------------------------------------------
`run` 스크립트를 셸 토큰으로 쪼개 **명령 위치**(줄 처음·`&&`·`||`·`;`·`|`·`(` 뒤)의 첫 낱말이
실행기 이름인지 본다. 그래서 다음은 위반이 *아니다* — 문자열 grep이면 오탐으로 터질 자리다:
- 주석(`# pytest ...`)·따옴표 안 문장(`echo "pytest 실패"`)
- 다른 명령의 인자(`docker compose run app alembic upgrade head`, `pip install pytest`의 `pytest`)
- heredoc 본문(`python - <<'PY' ... PY` 안의 코드)
- `python -m pytest` / `python3.12 -m pip` / `/usr/bin/python3 -m ruff`

의도적 예외 (정직한 공백)
-----------------------
- **`lint-imports`** — import-linter(2.0~2.15 확인)에는 `__main__`이 없어 `python -m` 형태 자체가
  존재하지 않는다. 같은 잡이 `python -m pip install -e ".[dev]"`로 설치하므로 콘솔 스크립트의
  shebang은 그 인터프리터에 묶인다 — 위험이 크지 않아 예외로 두되 `EXEMPT_LAUNCHERS`에 사유와
  함께 *명시*한다(조용한 누락이 아니라 기록된 예외).
- **셸 변수로 만든 명령**(`$CMD check`)과 **백틱 치환**은 정적으로 풀지 않는다 — 보지 않는다.
  (`$(...)` 치환은 따옴표 안이어도 재귀로 읽는다.)
- **워크플로 밖**(Dockerfile·compose·scripts/*.sh)은 이 태스크 범위가 아니다.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# 단독 호출을 금지하는 실행기 — python 패키지가 설치하는 콘솔 스크립트(런처)들.
# `python -m <이름>` 형태가 있는 것만 둔다(없는 도구는 EXEMPT_LAUNCHERS).
GUARDED_LAUNCHERS: frozenset[str] = frozenset(
    {
        "pytest",
        "ruff",
        "black",
        "mypy",
        "alembic",
        "pip",
        "pip3",
        "uvicorn",
        "coverage",
        "isort",
        "flake8",
        "bandit",
    }
)

# `python -m` 형태가 존재하지 않아 단독 호출을 허용하는 도구 — 사유 필수(만료 없는 유예 금지의
# 정신: 사유가 사라지면 예외도 사라져야 하므로 아래 테스트가 사유를 실제로 대조한다).
EXEMPT_LAUNCHERS: dict[str, str] = {
    "lint-imports": (
        "import-linter(2.0~2.15)에 __main__이 없어 `python -m` 형태가 존재하지 않는다. "
        "같은 잡이 `python -m pip install`로 설치하므로 콘솔 스크립트 shebang이 그 인터프리터에 묶인다."
    ),
}

# 명령 위치를 열어 주는 구분자. shlex(punctuation_chars)는 `&&`·`||`·`;;`·`<<` 같은 연속 구두점을
# 한 토큰으로 묶어 내므로, 아래 정규식은 '구두점만으로 된 토큰'을 일괄 구분자로 본다.
_PUNCT_ONLY = re.compile(r"^[();<>|&\n]+$")
# 리다이렉션 연산자 — 뒤따르는 토큰은 파일/디스크립터라 명령 위치가 아니다.
_REDIRECT_OPS = frozenset({"<", ">", "<<", ">>", ">&", "<&", "<<<", "&>", "&>>"})
# 명령 앞에 붙어도 그 뒤가 여전히 명령 위치인 낱말(제어 키워드·접두 래퍼·환경변수 대입).
_PREFIX_WORDS = frozenset(
    {"if", "then", "do", "else", "elif", "while", "until", "!", "{", "}", "time", "exec", "nohup"}
)
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


class ScriptParseError(ValueError):
    """`run` 스크립트를 셸 토큰으로 읽지 못함 — '위반 0'이 아니라 별도 신호(모른다 ≠ 아니다)."""


def _strip_heredoc_bodies(script: str) -> str:
    """heredoc 본문 줄을 제거한다 — 본문은 다른 언어 코드일 수 있어 셸 토큰으로 읽으면 오탐이다."""
    kept: list[str] = []
    delimiter: str | None = None
    for line in script.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = _HEREDOC.search(line)
        if match:
            delimiter = match.group(2)
    return "\n".join(kept)


def _shell_tokens(script: str) -> list[str]:
    """줄 이음을 편 뒤 셸 토큰화. 개행·구두점은 별도 토큰으로 남겨 '명령 경계'를 보존한다."""
    flattened = _strip_heredoc_bodies(script).replace("\\\n", " ")
    lexer = shlex.shlex(flattened, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"  # 개행은 공백이 아니라 명령 경계 토큰
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError as exc:  # 따옴표 불균형 등 — 위장 통과 대신 호출자에게 알린다
        raise ScriptParseError(f"{type(exc).__name__}: {exc}") from exc


def _command_substitutions(token: str) -> Iterator[str]:
    """한 토큰 안의 `$( ... )` 본문들(괄호 균형) — 따옴표로 감싸여 토큰이 쪼개지지 않은 경우용.

    `x="$(pytest -q)"`는 shlex가 한 낱말로 읽어 명령 위치로 보이지 않는다. 그 안은 실제로
    실행되는 명령이므로 본문을 꺼내 재귀로 읽는다. (백틱 치환은 읽지 않는다 — 모듈 docstring 참조)
    """
    start = token.find("$(")
    while start != -1:
        depth = 0
        for pos in range(start + 1, len(token)):
            if token[pos] == "(":
                depth += 1
            elif token[pos] == ")":
                depth -= 1
                if depth == 0:
                    yield token[start + 2 : pos]
                    start = token.find("$(", pos)
                    break
        else:
            return  # 닫히지 않은 `$(` — 더 읽을 수 없다
        continue


def command_words(script: str) -> Iterator[str]:
    """스크립트의 **명령 위치 첫 낱말**을 차례로 낸다(접두 키워드·환경변수 대입은 건너뛴다)."""
    expecting_command = True
    for token in _shell_tokens(script):
        if "$(" in token:
            for inner in _command_substitutions(token):
                yield from command_words(inner)
        if _PUNCT_ONLY.match(token):
            # 리다이렉션은 명령 경계가 아니다 — 그 뒤 토큰은 파일 이름이라 명령 위치를 열지 않는다.
            expecting_command = token not in _REDIRECT_OPS
            continue
        if not expecting_command:
            continue
        if token in _PREFIX_WORDS or _ASSIGNMENT.match(token):
            continue
        yield token
        expecting_command = False


def bare_launcher_calls(script: str) -> list[str]:
    """이 스크립트에서 단독 호출된 보호 대상 실행기 이름 목록(등장 순서, 중복 허용)."""
    found: list[str] = []
    for word in command_words(script):
        name = Path(word).name  # `/usr/local/bin/pytest` 절대경로 단독 호출도 같은 문제다
        if name in GUARDED_LAUNCHERS:
            found.append(name)
    return found


def exempt_launcher_calls(script: str) -> list[str]:
    """예외(EXEMPT_LAUNCHERS)로 허용된 단독 호출 이름 목록 — 예외가 실사용 중인지 대조용."""
    return [w for w in command_words(script) if Path(w).name in EXEMPT_LAUNCHERS]


def _workflow_files() -> list[Path]:
    files = sorted([*_WORKFLOW_DIR.glob("*.yml"), *_WORKFLOW_DIR.glob("*.yaml")])
    return files


def _iter_run_steps(spec: Mapping[str, Any]) -> Iterator[tuple[str, int, str, str]]:
    """(잡키, 스텝 인덱스, 스텝 이름, run 스크립트) — `run`이 있는 스텝만."""
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for job_key, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(job.get("steps") or []):
            if isinstance(step, dict) and step.get("run"):
                yield str(job_key), index, str(step.get("name", f"step[{index}]")), str(step["run"])


def runner_form_violations(spec: Mapping[str, Any], *, source: str = "workflow") -> list[str]:
    """워크플로 하나의 위반 사유 목록(빈 리스트 = 정상). 순수 함수라 합성 워크플로로 봉인 가능.

    파싱 불가 스크립트는 **위반으로 보고**한다 — 읽지 못한 스크립트를 '단독 호출 없음'으로
    접으면 가드가 가장 읽기 어려운 스크립트에서 꺼진다(모른다 ≠ 아니다).
    """
    violations: list[str] = []
    for job_key, _index, step_name, script in _iter_run_steps(spec):
        where = f"{source} · `{job_key}` 잡 · 스텝 «{step_name}»"
        try:
            names = bare_launcher_calls(script)
        except ScriptParseError as exc:
            violations.append(f"{where}: run 스크립트를 셸 토큰으로 읽지 못했다({exc}) — 판정 불가")
            continue
        for name in names:
            violations.append(
                f"{where}: 실행기 `{name}`를 단독 호출한다 — `python -m {name}` 형태로 "
                "잡이 설치한 인터프리터에 못 박아야 한다(CLAUDE.md 실행기 단독 호출 금지)."
            )
    return violations


# ══════════════════════════════════════════════════════════════════════════
# 실 워크플로 판정
# ══════════════════════════════════════════════════════════════════════════
def _load(path: Path) -> dict[str, Any]:
    spec: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError(f"{path.name}: jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")
    return spec


def test_workflow_directory_is_actually_scanned() -> None:
    """스캔 0건은 실패다 — 디렉터리를 못 찾으면 가드가 공허하게 통과한다."""
    files = _workflow_files()
    assert files, f"{_WORKFLOW_DIR} 에서 워크플로를 하나도 찾지 못했다 — 전수 가드가 공허해진다."
    names = {p.name for p in files}
    assert "ci.yml" in names, f"ci.yml 이 스캔 대상에 없다: {sorted(names)}"


def test_scan_actually_reaches_run_steps() -> None:
    """스캔이 `run` 스텝을 실제로 읽는다 — 파서가 전부 건너뛰어 '위반 0'이 되는 위장 방지."""
    total = sum(len(list(_iter_run_steps(_load(p)))) for p in _workflow_files())
    assert (
        total >= 100
    ), f"run 스텝이 {total}건뿐이다 — ci.yml만 해도 수백 건이라 스캔이 대상에 닿지 못한 것으로 본다."


def test_no_workflow_invokes_a_launcher_bare() -> None:
    """모든 워크플로·모든 잡·모든 run 스텝이 실행기를 `python -m`으로 부른다."""
    violations: list[str] = []
    for path in _workflow_files():
        violations.extend(runner_form_violations(_load(path), source=path.name))
    assert violations == [], "실행기 단독 호출 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_exempt_launchers_are_actually_used_and_justified() -> None:
    """예외는 실사용 중이어야 하고 사유가 있어야 한다 — 쓰이지 않는 예외는 만료된 예외다."""
    used: set[str] = set()
    for path in _workflow_files():
        for _job, _i, _name, script in _iter_run_steps(_load(path)):
            used.update(Path(w).name for w in command_words(script))
    for name, reason in EXEMPT_LAUNCHERS.items():
        assert reason.strip(), f"{name}: 예외 사유가 비어 있다."
        assert name in used, (
            f"예외 `{name}` 이(가) 어떤 워크플로에서도 쓰이지 않는다 — 사유가 사라졌으면 "
            "EXEMPT_LAUNCHERS 에서도 지운다(만료 없는 유예 금지)."
        )
    assert not (set(EXEMPT_LAUNCHERS) & GUARDED_LAUNCHERS), "예외와 보호 목록이 겹친다."


# ══════════════════════════════════════════════════════════════════════════
# 변별력 봉인 — 결함 주입이 실제로 검출되는지, 정상 입력은 통과하는지 (양성 대조)
# ══════════════════════════════════════════════════════════════════════════
def _spec(*scripts: str) -> dict[str, Any]:
    """잡 하나에 스텝 N개를 가진 합성 워크플로."""
    return {"jobs": {"j": {"steps": [{"name": f"s{i}", "run": s} for i, s in enumerate(scripts)]}}}


def test_detects_each_guarded_launcher_bare() -> None:
    """결함 주입 ⓐ — 보호 목록의 *모든* 실행기가 단독 호출로 검출된다(pytest만 보던 시절의 반례)."""
    for launcher in sorted(GUARDED_LAUNCHERS):
        assert runner_form_violations(_spec(f"{launcher} --version")) != [], launcher


def test_detects_launcher_in_every_command_position() -> None:
    """결함 주입 ⓑ — 줄 처음뿐 아니라 `&&`·`;`·`|`·`(`·`if` 뒤·환경변수 접두 뒤도 명령 위치다."""
    cases = [
        "pytest -q",
        "cd src/backend && pytest -q",
        "cd src/backend; pytest -q",
        "echo x | pytest -q",
        "(pytest -q)",
        "false || pytest -q",
        "if pytest -q; then echo ok; fi",
        "PYTHONPATH=. pytest -q",
        "FOO=1 BAR=2 pytest -q",
        "echo start\npytest -q",
        "python -m pip install x && pytest -q",
        "/usr/local/bin/pytest -q",
        "pytest \\\n  -q",
        'x="$(pytest -q)"',
    ]
    for script in cases:
        assert runner_form_violations(_spec(script)) != [], script


def test_positive_control_module_form_and_python_spellings_pass() -> None:
    """양성 대조 — `python`/`python3`/`python3.12`/절대경로 python 표기는 모두 규약 준수다."""
    for runner in ("python", "python3", "python3.12", "/usr/bin/python3", "$PY"):
        for tool in sorted(GUARDED_LAUNCHERS):
            script = f"{runner} -m {tool} --version"
            assert runner_form_violations(_spec(script)) == [], script


def test_positive_control_non_command_mentions_pass() -> None:
    """양성 대조 — 명령 위치가 아닌 언급은 위반이 아니다(문자열 grep이면 오탐이 나는 자리)."""
    cases = [
        "# pytest 를 부르면 안 된다는 주석\npython -m pytest",
        'echo "pytest 실패"',
        "python -m pip install pytest ruff black",
        "docker compose run --rm app alembic upgrade head",
        "python -m pytest tests/ -k 'alembic or pip'",
        "git commit -m 'pytest 정리'",
        "cat <<'EOF'\npytest -q\nEOF\npython -m pytest",
        "python - <<'PY'\nimport pytest\npytest.main()\nPY",
        "echo pip > out.txt",
        "python -m pytest 2> pytest.log",
    ]
    for script in cases:
        assert runner_form_violations(_spec(script)) == [], script


def test_detects_bare_launcher_after_heredoc_block() -> None:
    """결함 주입 ⓒ — heredoc을 건너뛰다 *그 뒤* 명령까지 삼키면 가드가 꺼진다(경계 정확성)."""
    script = "python - <<'PY'\nprint(1)\nPY\npytest -q"
    assert runner_form_violations(_spec(script)) != []


def test_exempt_launcher_is_not_a_violation_but_is_reported_as_exempt() -> None:
    """예외 도구는 위반이 아니지만 *예외로 집계*된다 — 조용한 누락과 구별된다."""
    script = "lint-imports"
    assert runner_form_violations(_spec(script)) == []
    assert exempt_launcher_calls(script) == ["lint-imports"]


def test_unparseable_script_is_reported_not_silently_passed() -> None:
    """모른다 ≠ 아니다 — 따옴표가 깨진 스크립트는 '위반 0'이 아니라 판정 불가 위반이다."""
    violations = runner_form_violations(_spec('echo "unterminated\npytest -q'))
    assert violations != []
    assert "판정 불가" in violations[0]


def test_violation_message_names_job_step_and_launcher() -> None:
    """위반 사유는 어느 잡·스텝의 어떤 실행기인지 말한다(뭉뚱그린 bool 금지)."""
    spec = {"jobs": {"backend": {"steps": [{"name": "Ruff", "run": "ruff check ."}]}}}
    [message] = runner_form_violations(spec, source="ci.yml")
    assert "backend" in message and "Ruff" in message and "ruff" in message
    assert "python -m ruff" in message


def test_non_run_steps_and_malformed_jobs_do_not_crash() -> None:
    """`uses:` 스텝·비정형 잡은 건너뛴다 — 가드가 구조 변형에 터지지 않는다."""
    spec: dict[str, Any] = {
        "jobs": {"a": {"steps": [{"uses": "actions/checkout@v4"}]}, "b": None, "c": {}}
    }
    assert runner_form_violations(spec) == []
