"""README 「로컬 부트스트랩」 절 회귀 동결 (OPS-81 ⑤).

문서만 고치면 다음 스택 변경에서 그대로 stale이 된다. 이 테스트는 그 절이 지시하는 **경로·모듈·extra·
엔드포인트가 저장소에 실재하는지**와, 이 저장소가 사고로 배운 **명령 형태 규칙**을 지키는지를 기계가 본다.

범위(정직): 명령을 *실행*하지는 않는다(Docker·PG가 CI infra 잡에 없다). 실행 검증은 2026-10-05 새 venv·
새 DB에서 사람이 한 번 했고(venv 설치 69초 · alembic head · 서버 기동 자가검증 · pytest 85건), 이 테스트는
그 뒤 **지시 대상이 사라지거나 형태 규칙이 깨지는 것**을 막는다.

규칙(전부 과거 사고의 형태 — README 절 본문에 근거 병기):
  · 실행기는 `python -m pip|pytest|alembic|uvicorn`으로 인터프리터를 고정한다(2026-07-27 다중 환경).
  · 검사 출력을 `-q`·`| tail`로 줄이지 않는다(2026-08-09 black).
  · 서버 자가검증은 `/health` 같은 간접 신호만으로 하지 않는다(2026-07-17 좀비 uvicorn) — 우리 PID 생존 +
    기동 완료 로그를 요구한다.
  · pytest는 설정 파일을 명시한다(OPS-61 가드 — 경로만 넘기면 asyncio_mode가 읽히지 않는다).
  · Kiki 머신 전용 요소(PowerShell·고정 경로)를 본문에 넣지 않는다(⑥ 범위 경계).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SECTION_HEAD = "## 로컬 부트스트랩"


def _section(text: str) -> str:
    """README에서 부트스트랩 절만 잘라 낸다 — 절이 없으면 빈 문자열(= 아래 검사가 RED)."""
    start = text.find(_SECTION_HEAD)
    if start < 0:
        return ""
    end = text.find("\n## ", start + len(_SECTION_HEAD))
    return text[start:] if end < 0 else text[start:end]


def _bash_lines(section: str) -> list[str]:
    """`bash` 코드 블록의 명령 줄만 모은다(줄 이음 `\\`는 한 줄로 합친다)."""
    lines: list[str] = []
    for block in re.findall(r"```bash\n(.*?)```", section, flags=re.S):
        joined = block.replace("\\\n", " ")
        lines.extend(line.strip() for line in joined.splitlines() if line.strip())
    return lines


def readme_bootstrap_problems(readme: str, repo: Path = _REPO) -> list[str]:
    """README 부트스트랩 절의 위반 목록 — 빈 리스트여야 통과. 순수 함수라 음성 대조군이 같은 코드를 쓴다."""
    section = _section(readme)
    if not section:
        return ["부트스트랩 절이 없다"]
    commands = _bash_lines(section)
    if not commands:
        return ["bash 명령 블록이 없다 — 스캔 0건은 통과가 아니다"]

    problems: list[str] = []
    joined = "\n".join(commands)

    # ① 필수 단계가 전부 있다.
    required = (
        "python3.12 -m venv",
        'python -m pip install -e "src/backend[dev]"',
        "python -m pip install -e src/data-pipeline",
        "python -m alembic upgrade head",
        "python -m uvicorn whymath_backend.app:create_app --factory",
        "python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend",
    )
    problems += [f"필수 명령 누락: {needle}" for needle in required if needle not in joined]

    # ② 지시하는 경로가 실재한다.
    for target in re.findall(r'-e "?([\w./-]+?)(?:\[[\w,]+\])?"?(?:\s|$)', joined):
        if not (repo / target).exists():
            problems.append(f"pip -e 대상이 없다: {target}")
    for target in re.findall(r"(?:-c|cd)\s+([\w./-]+)", joined):
        if target in {"..", "../.."}:
            continue
        if not (repo / target).exists():
            problems.append(f"경로가 없다: {target}")
    for target in re.findall(r"\s(tests/[\w./-]+\.py)", joined):
        if not (repo / target).exists():
            problems.append(f"테스트 파일이 없다: {target}")

    # ③ extra `dev`가 실재한다.
    pyproject = repo / "src" / "backend" / "pyproject.toml"
    if pyproject.exists():
        extras = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"][
            "optional-dependencies"
        ]
        if "dev" not in extras:
            problems.append("optional-dependencies에 dev extra가 없다")
    else:
        problems.append("src/backend/pyproject.toml이 없다")

    # ④ 앱 팩토리·준비 상태 엔드포인트·alembic 설정이 실재한다.
    app_py = repo / "src" / "backend" / "whymath_backend" / "app.py"
    app_src = app_py.read_text(encoding="utf-8") if app_py.exists() else ""
    if "def create_app(" not in app_src:
        problems.append("whymath_backend.app에 create_app 팩토리가 없다")
    if "/health/ready" in joined and "/health/ready" not in app_src:
        problems.append("/health/ready 엔드포인트가 app.py에 없다")
    if not (repo / "src" / "backend" / "alembic.ini").exists():
        problems.append("src/backend/alembic.ini가 없다")

    # ⑤ 명령 형태 규칙.
    for line in commands:
        if re.match(r"(pip|pytest|alembic|uvicorn)\b", line):
            problems.append(f"인터프리터 미고정 실행기: {line}")
        if re.search(r"pytest|ruff|black|mypy", line) and re.search(
            r"\s-q\b|--quiet|\|\s*tail", line
        ):
            problems.append(f"검사 출력을 줄이는 형태: {line}")
        if re.search(r"powershell|\.ps1|C:\\\\", line, flags=re.I):
            problems.append(f"Kiki 머신 전용 요소: {line}")
    for line in commands:
        if "pytest" in line and "tests/" in line and "-c src/backend/pyproject.toml" not in line:
            problems.append(f"pytest 설정 파일 미명시(OPS-61 가드에 막힌다): {line}")

    # ⑥ 서버 자가검증은 간접 신호만으로 하지 않는다 — PID 생존 + 기동 완료 로그.
    if "kill -0" not in joined or "Application startup complete" not in joined:
        problems.append("서버 자가검증이 PID 생존 + 기동 완료 로그가 아니다")

    return problems


_README = (_REPO / "README.md").read_text(encoding="utf-8")


def test_real_readme_bootstrap_section_is_consistent_with_the_repo() -> None:
    assert readme_bootstrap_problems(_README) == []


# ── 음성 대조군 — 위반을 주입한 README 텍스트에서 이 검사가 실제로 RED가 되는가 ──────────────


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("src/data-pipeline", "src/data-pipeline-missing", "pip -e 대상이 없다"),
        ("-c src/backend/pyproject.toml", "-c src/backend/nope.toml", "경로가 없다"),
        ("tests/backend/test_config.py", "tests/backend/test_nope.py", "테스트 파일이 없다"),
        ("python -m alembic upgrade head", "alembic upgrade head", "필수 명령 누락"),
        ("python -m pytest -c", "pytest -c", "필수 명령 누락"),
        ("Application startup complete", "Uvicorn running", "자가검증"),
        ("kill -0", "kill -9", "자가검증"),
        ("--factory", "", "필수 명령 누락"),
    ],
)
def test_injected_drift_turns_the_check_red(old: str, new: str, expect: str) -> None:
    section = _section(_README)
    assert old in section, f"주입 대상이 절에 없다(픽스처 접촉 실패): {old}"
    mutated = _README.replace(old, new)
    assert mutated != _README, "주입이 적용되지 않았다"
    problems = readme_bootstrap_problems(mutated)
    assert any(expect in p for p in problems), problems


def test_quiet_flag_and_tail_are_flagged() -> None:
    mutated = _README.replace(
        "tests/backend/test_app.py\n", "tests/backend/test_app.py -q | tail -3\n", 1
    )
    assert mutated != _README
    assert any("출력을 줄이는" in p for p in readme_bootstrap_problems(mutated))


def test_missing_section_is_a_failure_not_a_silent_pass() -> None:
    assert readme_bootstrap_problems("# 아무 절도 없는 README\n") == ["부트스트랩 절이 없다"]
    assert readme_bootstrap_problems(f"{_SECTION_HEAD}\n\n본문만 있고 코드 블록 없음\n") == [
        "bash 명령 블록이 없다 — 스캔 0건은 통과가 아니다"
    ]
