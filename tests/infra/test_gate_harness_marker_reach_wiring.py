"""[EOS-21 · EOS-142] Gate 2 판정 하네스가 **CI에서 실제 판정에 도달하는가**를 동결한다.

전제 정정 (2026-09-23 실측 · 판정 기준 main f4926588)
------------------------------------------------------
`EOS-21` 등재문과 `test_p11_chain_nightly_wiring.py` docstring은 둘 다 "실 PG가 있는 잡은
`e2e-nightly`뿐이고 그 잡은 이 파일들을 이름으로 부르지 않으므로 **어느 CI 잡에서도 돈 적이
없다**"를 전제했다. **그 전제는 거짓이다.**

원 측정은 워크플로에서 *파일명*을 셌다(week1·week2·week3·persona 각 0건). 그러나
`backend — 마이그레이션·통합 (실 PG)` 잡은 **마커로 수집**한다:

    cd src/backend && pytest -m integration --ignore=../../tests/backend/l3

`src/backend/pyproject.toml`의 `testpaths = ["../../tests/backend"]`이므로 이 호출은
`tests/backend` **전체**를 수집해 `integration` 마커로 거른다 — 6종은 전부 그 아래 있고
전부 `@pytest.mark.integration`이다. 즉 **파일명 0건은 "이름으로 안 부른다"이지 "안 돈다"가
아니다**(CLAUDE.md 「식별자 부재를 기능 부재로 단정 금지」).

실행 실측(CI 잡의 명령·env·선행 스텝을 그대로 재현 — 실 PG + WHYMATH_RUN_INTEGRATION=1 +
alembic upgrade head): 6종 전부 **실행·통과**, SKIPPED 0 · FAILED 0
(`1 failed, 260 passed, 99 skipped, 11147 deselected in 337.18s` — 유일한 실패는 무관한
코퍼스 적재 건). 그 스텝은 `EOS-21`이 적은 판정 기준 커밋 `77ee1992`에도 있었으므로
시점 차이가 아니라 **측정 방법**이 그 잡을 못 본 것이다.

그러면 이 파일은 왜 필요한가
-----------------------------
"돈다"는 확인됐지만 **그것을 동결하는 가드가 0건**이었다. 지금 도는 것은 세 조건이 우연히
겹쳐 있기 때문이다 — ⑴ `testpaths`가 `tests/backend` 전체 ⑵ 6종이 `integration` 마커 보유
⑶ `--ignore`가 그 하네스 디렉터리를 제외하지 않음(당시 `l3` 디렉터리 일괄 · 2026-10-31 이후 파일 단위 — OPS-137). 셋 중 **아무거나 하나**가 바뀌면(예: `--ignore`에 `api` 추가,
마커 변경, `testpaths` 축소, `WHYMATH_RUN_INTEGRATION` 제거) 6종은 조용히 skip으로 돌아가고
skip은 exit 0이다. 즉 `EOS-21`이 막으려던 상태가 **아무 경고 없이** 재생산된다.

암묵 배선을 명시 계약으로 바꾸는 것이 이 파일의 일이다. 워크플로에 중복 스텝을 더해
같은 테스트를 두 번 돌리는 쪽(실행 시간 추가)은 택하지 않았다 — 비용 없이 같은 보호를
얻을 수 있고, 명시 스텝을 더해도 *그것이 도달하는지*는 결국 이 형태의 가드가 봐야 한다.

EOS-142 편입 (2026-09-28)
-------------------------
EOS-21 측정(2026-09-23) 뒤에 착지한 Gate 2 상시 증거 2종이 목록에 없었다 — 무개입 연속
3루프 하네스(`test_e2e_three_consecutive_loops.py` · §18의 유일한 상시 증거)와 SCENARIO
회귀 스위트(`test_phase2_scenario_regression_suite.py` · SCENARIO-001~010). 둘 다 같은 마커
수집으로 돌고 있었으나(판정은 틀리지 않았다) 세 조건 중 하나가 바뀌면 조용히 빠지는 상태였다.

3루프 하네스는 동결 공백이 남은 오답 종류에서 `xfail(strict=True)`로 돈다. **XFAIL은 실행된
것이다** — 표식은 본문 안에서 `request.applymarker`로 붙고 본문은 끝까지 돈 뒤 단언에서
실패한다. 그 성질이 깨지는 형태 셋을 이 파일이 막는다(`strict_xfail_violations`): 엄격하지
않은 xfail(통과해도 초록 · 실패해도 초록) · `run=False`(실행하지 않고 XFAIL로 보고) · 본문
중간의 `pytest.xfail(...)`(거기서 멈추고 XFAIL로 보고). 셋 다 "도달했다"를 "실행했다"와
다르게 만든다.

재사용 (acceptance ③ '재구현 0')
--------------------------------
`test_p11_chain_nightly_wiring.real_pg_violations`가 "그 잡이 실 PG에 도달하는가"를 이미
순수 함수로 판정하고 합성 워크플로 주입으로 변별력을 봉인해 뒀다. 그 함수는 대상 스텝을
**이름으로** 찾으므로 마커 수집 경로에는 그대로 쓸 수 없다 — 그래서 이 파일은 *대상을 찾는
축만* 새로 쓰고, 찾은 잡의 PG 도달 판정은 **그 함수를 그대로 호출**한다(어댑터 경유).
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import pathlib
import posixpath
import re
import shlex
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PG_GUARD_PATH = pathlib.Path(__file__).with_name("test_p11_chain_nightly_wiring.py")

#: Gate 2 판정 하네스 — EOS-22 Gate 2 10조건의 근거 6종(EOS-21) + 상시 루프 증거 2종(EOS-142).
GATE_HARNESS_PATHS: tuple[str, ...] = (
    "tests/backend/api/test_week1_gate_closed_loop.py",
    "tests/backend/api/test_week2_gate_wrong_answer_propagation.py",
    "tests/backend/api/test_week3_gate_remediation_loop.py",
    "tests/backend/api/test_e2e_persona_journeys.py",
    "tests/backend/api/test_p11_five_stage_loop_chain.py",
    "tests/backend/api/test_e2e_vertical_slice_integration.py",
    # EOS-142 — 무개입 연속 3루프(§18)의 유일한 상시 증거 · SCENARIO-001~010 회귀 스위트.
    "tests/backend/api/test_e2e_three_consecutive_loops.py",
    "tests/backend/scenarios/test_phase2_scenario_regression_suite.py",
    # P3-13 — Release Gate D 이벤트 8종 실세션 역할 대조. 같은 마커 수집으로 도는 실 PG 하네스라
    # 목록에 올려 두지 않으면 마커·--ignore가 바뀔 때 조용히 skip으로 빠져도 아무 가드가 못 본다.
    "tests/backend/scenarios/test_gate_d_event_role_census.py",
)

#: EOS-142로 편입된 두 하네스 — 목록에서 **유도하지 않고** 리터럴로 적는다. 유도하면 목록에서
#: 빠질 때 반례 픽스처도 따라 움직여 아무것도 잡지 못한다(뮤테이션 I6 생존으로 실측).
EOS142_HARNESS_PATHS: tuple[str, ...] = (
    "tests/backend/api/test_e2e_three_consecutive_loops.py",
    "tests/backend/scenarios/test_phase2_scenario_regression_suite.py",
)

#: 마커 수집 스텝이 도는 작업 디렉터리와 그 디렉터리의 pytest 설정.
_BACKEND_WORKDIR = "src/backend"
_BACKEND_PYPROJECT = _REPO_ROOT / _BACKEND_WORKDIR / "pyproject.toml"

#: 어댑터가 PG 판정 함수에 건네는 가짜 경로. 실제 파일일 필요가 없다 —
#: 그 함수는 이 이름으로 '어느 잡을 볼지'만 정하고, 판정은 잡의 services·env로 한다.
_SENTINEL_PATH = "tests/backend/api/__eos21_marker_reach_sentinel__.py"


def _load_pg_guard() -> ModuleType:
    """P-11 배선 가드를 적재한다 — PG 도달 판정 함수를 빌려 쓴다(재구현 0)."""
    if not _PG_GUARD_PATH.exists():
        raise AssertionError(
            f"PG 도달 판정 가드가 없다: {_PG_GUARD_PATH}. 이 파일은 그 함수를 재사용한다."
        )
    spec = importlib.util.spec_from_file_location("_eos21_pg_reach_guard", _PG_GUARD_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"PG 도달 판정 가드 스펙 생성 실패: {_PG_GUARD_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "real_pg_violations"):
        raise AssertionError(
            "PG 도달 판정 가드에 `real_pg_violations`가 없다 — 이름이 바뀌었으면 여기도 "
            "함께 고쳐야 한다(조용한 표류 방지)."
        )
    return module


def _load_workflow() -> dict[str, Any]:
    """ci.yml 파싱 — 못 읽거나 jobs가 비면 '통과'가 아니라 실패한다."""
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 배선을 확인할 수 없다(위장 통과 금지).")
    spec: Any = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not spec.get("jobs"):
        raise AssertionError("ci.yml에 jobs가 없다 — 워크플로 파싱이 위장 통과할 수 없다.")
    return spec


def _pytest_tokens(script: str) -> list[list[str]] | None:
    """`run` 스크립트에서 pytest 호출의 토큰 목록들. pytest가 없으면 None.

    줄바꿈 이어쓰기(`\\`)를 펴고 `shlex`로 쪼갠다 — 문자열 포함 검사였다면 주석 속
    "pytest"에 걸린다.
    """
    normalized = script.replace("\\\n", " ")
    if "pytest" not in normalized:
        return None
    calls: list[list[str]] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "pytest" not in stripped:
            continue
        try:
            tokens = shlex.split(stripped, comments=True)
        except ValueError:
            # 파싱 실패를 '해당 없음'으로 접지 않는다 — 원문을 그대로 토큰화해 넘긴다.
            tokens = stripped.split()
        if any(pathlib.Path(t).name == "pytest" for t in tokens):
            calls.append(tokens)
    return calls or None


#: 수집 범위를 바꾸지 않는다고 확인한 옵션. **이 밖의 옵션은 "수집을 증명하지 못한다"로 본다**
#: (OPS-137 검토 반영 — 모르는 옵션을 건너뛰면 `--deselect=…`·`--ignore-glob`·`-o testpaths=…`
#: 처럼 수집에서 빼는 옵션을 "수집함"으로 읽는다. 모르는 것을 통과로 접지 않는다).
_SAFE_FLAGS = frozenset(
    {"-q", "--quiet", "-v", "--verbose", "-x", "--exitfirst", "--strict-markers"}
)
#: 값을 하나 받지만 수집 범위를 바꾸지 않는 옵션(`--tb short`·`--tb=short` 두 형태).
_SAFE_VALUE_OPTIONS = frozenset({"--tb", "--durations"})
#: 수집 범위를 바꿀 수 있는 옵션 — 있으면 "수집을 증명하지 못한다"(False).
_SCOPE_CHANGING_OPTIONS = frozenset(
    {
        "-k",
        "-o",
        "--override-ini",
        "-c",
        "--config-file",
        "--rootdir",
        "--pyargs",
        "--co",
        "--collect-only",
        "--lf",
        "--last-failed",
        "--sw",
        "--stepwise",
    }
)


def _option_value(tokens: list[str], i: int, name: str) -> tuple[str | None, int]:
    """`name X`·`name=X` 두 형태에서 값과 다음 인덱스. 이 옵션이 아니면 (None, i)."""
    token = tokens[i]
    if token == name:
        return (tokens[i + 1] if i + 1 < len(tokens) else ""), i + 2
    if token.startswith(name + "="):
        return token.split("=", 1)[1], i + 1
    return None, i


def _marker_selects_integration(expression: str) -> bool:
    """`-m` 식이 `integration` 마커만 단 파일을 고르는가 — `not integration`은 False다.

    식 문법(`and`·`or`·`not`·괄호·식별자)을 작은 재귀 하강으로 계산한다. 하네스 파일이
    `integration` 말고 다른 마커를 다는지는 모르므로 다른 식별자는 False로 둔다. 문법을
    벗어난 식(따옴표·인자 호출 등)은 계산하지 않고 False다 — 모르면 수집을 증명하지 못한다.
    """
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    pos = 0

    def parse_or() -> bool:
        nonlocal pos
        value = parse_and()
        while pos < len(tokens) and tokens[pos] == "or":
            pos += 1
            rhs = parse_and()
            value = value or rhs
        return value

    def parse_and() -> bool:
        nonlocal pos
        value = parse_not()
        while pos < len(tokens) and tokens[pos] == "and":
            pos += 1
            rhs = parse_not()
            value = value and rhs
        return value

    def parse_not() -> bool:
        nonlocal pos
        if pos < len(tokens) and tokens[pos] == "not":
            pos += 1
            return not parse_not()
        return parse_atom()

    def parse_atom() -> bool:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("식이 끝났다")
        token = tokens[pos]
        pos += 1
        if token == "(":
            value = parse_or()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError("괄호 불일치")
            pos += 1
            return value
        if token in {"and", "or", ")"} or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            raise ValueError(f"식별자가 아니다: {token}")
        return token == "integration"

    try:
        result = parse_or()
    except ValueError:
        return False
    return result if pos == len(tokens) else False


def _resolve(path: str, workdir: str) -> str:
    """pytest가 보는 경로 — 작업 디렉터리 기준으로 푼 저장소 상대 경로."""
    return posixpath.normpath(posixpath.join(workdir, path))


def _covers(prefix: str, harness_path: str) -> bool:
    """`prefix`가 하네스 파일 자체이거나 그 상위 디렉터리인가."""
    prefix = prefix.rstrip("/")
    return bool(prefix) and (harness_path == prefix or harness_path.startswith(prefix + "/"))


def _deselect_hits(value: str, harness_path: str) -> bool:
    """`--deselect` 값(노드 id 접두)이 하네스 파일의 일부라도 빼는가 — 보수적으로 판정한다.

    노드 id의 기준점(rootdir)과 작업 디렉터리가 달라 정확한 해석이 어렵다. 그래서 경로 부분의
    앞쪽 `./`·`../` 를 걷어 낸 꼴이 하네스 경로의 상위이거나 하네스 경로의 꼬리와 같으면 뺀다고 본다.
    """
    path_part = value.split("::", 1)[0]
    stripped = re.sub(r"^(?:\.{1,2}/)+", "", path_part).rstrip("/")
    if not stripped:
        return True  # 빈 접두는 전부를 뺀다.
    return _covers(stripped, harness_path) or harness_path.endswith("/" + stripped)


def _collects_by_marker(
    tokens: list[str], *, harness_path: str, workdir: str = _BACKEND_WORKDIR
) -> bool:
    """이 pytest 호출이 `harness_path`를 **마커 수집**으로 잡는가.

    조건을 모두 본다:
      ⑴ `-m` 식이 `integration` 마커 파일을 고른다(`not integration`은 아니다)
      ⑵ 위치 인자(경로)를 주지 않는다 — 주면 testpaths가 무시되고 그 경로만 돈다
      ⑶ `--ignore`·`--ignore-glob`·`--deselect`가 이 하네스(파일 또는 상위 디렉터리)를 빼지 않는다.
         경로는 **작업 디렉터리 기준으로** 푼다 — `src/backend`에서 `--ignore=tests/backend/...`는
         `src/backend/tests/backend/...`를 가리켜 실제로는 아무것도 빼지 않는다
      ⑷ 수집 범위를 바꿀 수 있는 옵션(`-k`·`-o`·`--collect-only` 등)과 **모르는 옵션**이 없다

    ⑶이 이 판정의 급소다. 2026-10-13까지 통합 스텝은 `--ignore=../../tests/backend/l3` 디렉터리
    일괄 제외였고, 그 한 줄이 l3 하위 PG 통합 파일까지 통째로 가렸다(OPS-137). 지금은 파일 단위다.
    """
    marker_value: str | None = None
    ignores: list[str] = []
    ignore_globs: list[str] = []
    deselects: list[str] = []
    # `pytest` 토큰 이후만 본다 — 그 앞은 `python -m` 같은 런처다.
    i = next(
        (idx + 1 for idx, t in enumerate(tokens) if pathlib.Path(t).name == "pytest"),
        len(tokens),
    )
    while i < len(tokens):
        token = tokens[i]
        if token == "-m":
            marker_value = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2
            continue
        if token.startswith("-m") and not token.startswith("--") and len(token) > 2:
            marker_value = token[2:]
            i += 1
            continue
        matched = False
        for name, sink in (
            ("--ignore", ignores),
            ("--ignore-glob", ignore_globs),
            ("--deselect", deselects),
        ):
            value, nxt = _option_value(tokens, i, name)
            if value is not None:
                sink.append(value)
                i = nxt
                matched = True
                break
        if matched:
            continue
        if token in _SAFE_FLAGS or (token.startswith("-r") and len(token) > 2):
            i += 1
            continue
        safe_value = next(
            (n for n in _SAFE_VALUE_OPTIONS if token == n or token.startswith(n + "=")), None
        )
        if safe_value is not None:
            i += 2 if token == safe_value else 1
            continue
        if token.startswith("-"):
            # 수집 범위를 바꾸는 옵션이든 모르는 옵션이든 — 수집을 증명하지 못한다.
            return False
        return False  # 위치 인자(경로) — testpaths가 무시된다.

    if marker_value is None or not _marker_selects_integration(marker_value):
        return False
    if any(_covers(_resolve(p, workdir), harness_path) for p in ignores):
        return False
    parents = [harness_path] + [
        str(parent.as_posix()) for parent in pathlib.PurePosixPath(harness_path).parents
    ]
    for pattern in ignore_globs:
        resolved = _resolve(pattern, workdir)
        if any(fnmatch.fnmatch(candidate, resolved) for candidate in parents):
            return False
    if any(_deselect_hits(value, harness_path) for value in deselects):
        return False
    return True


def _workdir_of(job: Mapping[str, Any], step: Mapping[str, Any]) -> str | None:
    """이 스텝이 실제로 도는 작업 디렉터리 — 스텝 지정이 잡 기본값을 이긴다.

    GitHub Actions는 `defaults.run.working-directory`를 잡 전체에 적용하고, 스텝의
    `working-directory`가 있으면 그쪽이 우선한다. 이 값이 곧 pytest의 cwd이고,
    cwd가 곧 `testpaths`의 기준점이다 — 그래서 "어느 디렉터리에서 돌았나"를 모르면
    "무엇을 수집했나"도 모른다.
    """
    step_wd = step.get("working-directory")
    if step_wd:
        return str(step_wd).rstrip("/")
    job_wd = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
    return str(job_wd).rstrip("/") if job_wd else None


def marker_reach_violations(
    spec: Mapping[str, Any], *, harness_paths: tuple[str, ...] = GATE_HARNESS_PATHS
) -> list[str]:
    """게이트 하네스가 **마커 수집으로 판정에 도달하는가** (순수 함수).

    도달 = ⑴ 그 파일을 수집하는 pytest 스텝이 있고 ⑵ 그 스텝의 잡이 실 PG를 준다.
    ⑵의 판정은 `real_pg_violations`를 그대로 호출한다(재구현 0).
    """
    violations: list[str] = []
    jobs = spec.get("jobs") or {}
    if not isinstance(jobs, dict) or not jobs:
        return ["ci.yml에 jobs가 없다 — 판정 불가(위장 통과 금지)."]

    pg_guard = _load_pg_guard()

    for harness_path in harness_paths:
        hosting: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for job_key, job in jobs.items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if not isinstance(step, dict) or not step.get("run"):
                    continue
                # **작업 디렉터리가 판정의 필수 항이다.** 마커 수집의 분모는
                # `<cwd>/pyproject.toml`의 `testpaths`이므로, 같은 `pytest -m integration`
                # 이라도 `src/data-pipeline`에서 돌면 `tests/backend`를 한 건도 수집하지
                # 않는다. 이 절이 없으면 `backend-migrations`를 통째로 깨뜨려도
                # `data-pipeline-integration`이 대신 조건을 만족시켜 가드가 초록을 낸다
                # (뮤테이션 M1~M4·M7·M8 생존으로 실제로 드러난 결함).
                if _workdir_of(job, step) != _BACKEND_WORKDIR:
                    continue
                calls = _pytest_tokens(str(step["run"]))
                if not calls:
                    continue
                if any(_collects_by_marker(c, harness_path=harness_path) for c in calls):
                    hosting.append((job_key, job, step))
        if not hosting:
            violations.append(
                f"`{harness_path}`를 마커 수집으로 잡는 pytest 스텝이 없다 — 이 하네스는 "
                "저장소에 존재할 뿐 어느 잡도 판정에 도달시키지 않는다(skip은 exit 0이라 "
                "미실행이 초록으로 보인다)."
            )
            continue

        # ⑵ 그 잡이 실 PG를 주는가 — 판정은 선례 함수에 위임한다. 그 함수는 대상 스텝을
        # *이름으로* 찾으므로, 찾은 잡을 그대로 두고 스텝의 run만 센티넬 이름 호출로
        # 바꾼 사본을 넘긴다(잡의 services·env는 원본 그대로라 판정 대상이 보존된다).
        reached = False
        pg_messages: list[str] = []
        for job_key, job, step in hosting:
            shim_step = {**step, "run": f"python -m pytest ../../{_SENTINEL_PATH}"}
            shim_job = {**job, "steps": [shim_step]}
            found = pg_guard.real_pg_violations(
                {"jobs": {job_key: shim_job}}, test_path=_SENTINEL_PATH
            )
            if not found:
                reached = True
                break
            pg_messages.extend(found)
        if not reached:
            violations.append(
                f"`{harness_path}`를 수집하는 스텝은 있으나 그 잡이 실 PG에 도달하지 않는다 "
                "— 배선의 실재와 배선의 *도달*은 다르다:\n      " + "\n      ".join(pg_messages)
            )
    return violations


def _is_pytest_attr(node: ast.AST, *names: str) -> bool:
    """`pytest.<a>.<b>...`의 속성 사슬이 `names`와 같은가 — `pytest.mark.xfail` 같은 이름 판정."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return isinstance(node, ast.Name) and node.id == "pytest" and tuple(reversed(parts)) == names


def strict_xfail_violations(source: str, *, path: str) -> list[str]:
    """하네스 소스에서 "XFAIL = 실행됨"을 깨는 형태를 찾는다 (순수 함수 · EOS-142 ③).

    ⑴ `pytest.mark.xfail(...)`에 `strict=True`가 없다 — 통과해도(XPASS) 실패해도(XFAIL) 초록이다.
       이 저장소는 전역 `xfail_strict`를 켜지 않으므로 표식마다 명시해야 한다.
    ⑵ `run=False`가 있다 — 실행하지 않고 XFAIL로 보고한다.
    ⑶ 호출 없이 쓴 `@pytest.mark.xfail` — ⑴과 같다(기본값이 느슨하다).
    ⑷ 본문의 `pytest.xfail(...)` — 거기서 멈추고 XFAIL로 보고한다. 뒤의 단언은 돌지 않는다.
    """
    tree = ast.parse(source)
    found: list[str] = []
    marked_calls: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_pytest_attr(node.func, "mark", "xfail"):
            marked_calls.add(id(node.func))
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            strict = kw.get("strict")
            if not (isinstance(strict, ast.Constant) and strict.value is True):
                found.append(f"{path}:{node.lineno} xfail에 strict=True가 없다")
            run = kw.get("run")
            if run is not None and not (isinstance(run, ast.Constant) and run.value is True):
                found.append(f"{path}:{node.lineno} xfail(run=...)이 실행을 끈다")
        elif isinstance(node, ast.Call) and _is_pytest_attr(node.func, "xfail"):
            found.append(f"{path}:{node.lineno} 본문의 pytest.xfail(...)이 실행을 중간에 멈춘다")
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and id(node) not in marked_calls
            and _is_pytest_attr(node, "mark", "xfail")
        ):
            found.append(f"{path}:{node.lineno} 호출 없는 @pytest.mark.xfail(느슨한 기본값)")
    return found


# ══════════════════════════════════════════════════════════════════════════
# 실 워크플로 판정
# ══════════════════════════════════════════════════════════════════════════
def test_all_gate_harness_files_exist() -> None:
    """① 대상이 실재한다 — 없으면 마커 수집은 조용히 '0건 통과'가 된다."""
    missing = [p for p in GATE_HARNESS_PATHS if not (_REPO_ROOT / p).is_file()]
    assert not missing, (
        "Gate 2 판정 하네스가 사라졌다: " + ", ".join(missing) + " — 마커 수집은 사라진 "
        "파일을 조용히 건너뛰므로 스텝은 여전히 초록이다."
    )


def test_gate_harnesses_carry_the_integration_marker() -> None:
    """② 마커가 실재한다 — 마커가 빠지면 수집에서 빠지고 아무도 모른다.

    이 축이 없으면 "스텝이 있다"만으로 통과한다. 수집은 *스텝과 마커의 곱*이다.
    """
    unmarked = [
        p
        for p in GATE_HARNESS_PATHS
        if "pytest.mark.integration" not in (_REPO_ROOT / p).read_text(encoding="utf-8")
    ]
    assert not unmarked, (
        "integration 마커가 없는 하네스: " + ", ".join(unmarked) + " — `-m integration` "
        "수집에서 빠지므로 실행되지 않는다."
    )


def test_gate_harness_xfails_are_strict_and_executed() -> None:
    """③-b XFAIL은 실행된 것이어야 한다 — 느슨한·미실행·중도 정지 xfail이 없다(EOS-142).

    도달 계약은 "수집된다"까지다. 수집된 테스트가 XFAIL로 끝났을 때 그것이 **돌다 실패한 것**
    이어야 도달이 판정이 된다 — 아니면 skip과 같은 침묵이 XFAIL 이름을 달고 초록으로 남는다.
    """
    scanned = 0
    violations: list[str] = []
    for rel in GATE_HARNESS_PATHS:
        violations += strict_xfail_violations(
            (_REPO_ROOT / rel).read_text(encoding="utf-8"), path=rel
        )
        scanned += 1
    assert scanned == len(GATE_HARNESS_PATHS) > 0, "스캔한 하네스가 0개다 — 공허 통과 금지"
    assert violations == [], "XFAIL이 실행을 뜻하지 않는 표식:\n" + "\n".join(violations)


def test_backend_testpaths_cover_the_gate_harnesses() -> None:
    """③ `testpaths`가 그 디렉터리를 덮는다 — 좁히면 마커가 있어도 수집되지 않는다."""
    text = _BACKEND_PYPROJECT.read_text(encoding="utf-8")
    assert 'testpaths = ["../../tests/backend"]' in text, (
        f"{_BACKEND_PYPROJECT} 의 testpaths가 `../../tests/backend` 전체가 아니다 — "
        "마커 수집의 분모가 좁아지면 Gate 2 하네스가 조용히 빠진다. 좁히려면 그 대신 "
        "6종을 이름으로 부르는 스텝을 ci.yml에 추가하고 이 가드를 함께 고쳐라."
    )


def test_gate_harnesses_actually_reach_judgment_in_ci() -> None:
    """④ 마커 수집 스텝이 실재하고 그 잡이 실 PG를 준다 — 이 파일의 본 판정."""
    violations = marker_reach_violations(_load_workflow())
    assert violations == [], "Gate 2 하네스 판정 도달 계약 위반:\n" + "\n".join(
        f"- {v}" for v in violations
    )


def test_parser_refuses_to_pass_on_broken_workflow() -> None:
    """파서가 위장하지 않는다 — jobs 없는 워크플로는 '위반 0'이 아니다."""
    assert marker_reach_violations({"jobs": {}}) != []
    assert marker_reach_violations({}) != []


# ══════════════════════════════════════════════════════════════════════════
# 변별력 봉인 — 축마다 그 축의 반례를 합성 워크플로로 주입한다
#
# 실 워크플로만으로는 *정상 분기*밖에 밟지 않는다. 위반 분기를 한 번도 지나가지 않으면
# 그 분기를 지워도 초록이고, 그러면 "가드가 관대한" 것이 아니라 **픽스처가 그 자리를
# 안 지나간** 것이다(뮤테이션 M7·M8 생존으로 실제로 드러났다).
# ══════════════════════════════════════════════════════════════════════════
_TARGET = GATE_HARNESS_PATHS[0]


def _synthetic(
    *,
    workdir: str | None = _BACKEND_WORKDIR,
    run: str = "pytest -m integration --ignore=../../tests/backend/l3",
    with_postgres: bool = True,
    run_integration: str | None = "1",
    database_url: str | None = "postgresql+asyncpg://whymath@127.0.0.1:5432/whymath",
) -> dict[str, Any]:
    """정상 배선 1건짜리 합성 워크플로 — 인자로 축을 하나씩 깨뜨린다."""
    step: dict[str, Any] = {"name": "통합", "run": run}
    if run_integration is not None:
        step["env"] = {"WHYMATH_RUN_INTEGRATION": run_integration}
    job: dict[str, Any] = {"steps": [step]}
    if workdir is not None:
        job["defaults"] = {"run": {"working-directory": workdir}}
    if with_postgres:
        job["services"] = {"postgres": {"image": "pgvector/pgvector:pg16"}}
    if database_url is not None:
        job["env"] = {"WHYMATH_DATABASE_URL": database_url}
    return {"jobs": {"backend-migrations": job}}


def test_positive_control_synthetic_wiring_passes() -> None:
    """양성 대조 — 정상 합성 배선은 위반 0. 무차별 실패가 아님을 보인다."""
    assert marker_reach_violations(_synthetic(), harness_paths=(_TARGET,)) == []


def test_detects_job_without_postgres_service() -> None:
    """PG 도달 위임의 반례 — 수집은 하는데 잡이 실 PG를 안 준다.

    이 픽스처가 없으면 위임 결과를 무시하는 뮤테이션(M7)이 살아남는다. 실 워크플로는
    PG가 정상이라 그 분기를 한 번도 밟지 않기 때문이다.
    """
    violations = marker_reach_violations(_synthetic(with_postgres=False), harness_paths=(_TARGET,))
    assert violations != []
    assert "실 PG에 도달하지 않는다" in violations[0]


def test_detects_job_without_run_integration_flag() -> None:
    """마커가 기본 skip으로 돌아가는 축 — 스텝은 멀쩡한데 수집 0건이 된다."""
    assert marker_reach_violations(_synthetic(run_integration=None), harness_paths=(_TARGET,)) != []


def test_detects_missing_database_url() -> None:
    """DB 주소 미지정 축 — 기본값이 러너 PG를 가리킨다는 보장이 없다."""
    assert marker_reach_violations(_synthetic(database_url=None), harness_paths=(_TARGET,)) != []


def test_detects_no_collecting_step_at_all() -> None:
    """수집 판정의 반례 — 잡은 있는데 그 하네스를 잡는 스텝이 없다.

    이 픽스처가 없으면 `if not hosting:` 분기를 지우는 뮤테이션(M8)이 살아남는다.
    """
    violations = marker_reach_violations(
        _synthetic(run="pytest -m integration ../../tests/backend/db"),
        harness_paths=(_TARGET,),
    )
    assert violations != []
    assert "마커 수집으로 잡는 pytest 스텝이 없다" in violations[0]


def test_detects_ignore_that_excludes_the_harness_directory() -> None:
    """`--ignore` 확장 축 — 한 글자 추가로 6종이 통째로 빠지는 급소."""
    assert (
        marker_reach_violations(
            _synthetic(run="pytest -m integration --ignore=../../tests/backend/api"),
            harness_paths=(_TARGET,),
        )
        != []
    )


def test_detects_wrong_working_directory() -> None:
    """작업 디렉터리 축의 반례 — 같은 명령이라도 다른 cwd면 분모가 다르다.

    `data-pipeline-integration`이 실제로 이 형태다: `pytest -m integration`에 PG까지
    있지만 `src/data-pipeline`에서 돌아 `tests/backend`를 한 건도 수집하지 않는다.
    """
    assert (
        marker_reach_violations(_synthetic(workdir="src/data-pipeline"), harness_paths=(_TARGET,))
        != []
    )


def test_detects_marker_filter_removed() -> None:
    """마커 필터가 사라지면 수집 규약이 달라진다 — 이 가드의 전제가 무너진다."""
    assert (
        marker_reach_violations(
            _synthetic(run="pytest --ignore=../../tests/backend/l3"), harness_paths=(_TARGET,)
        )
        != []
    )


# ── EOS-142 — 편입한 두 하네스 각각의 도달 끊김 · xfail 엄격성 반례 ─────────────────


def test_eos142_harnesses_are_in_the_frozen_list() -> None:
    """편입이 되돌려지지 않는다 — 두 하네스가 도달 동결 목록에서 빠지면 RED."""
    missing = [p for p in EOS142_HARNESS_PATHS if p not in GATE_HARNESS_PATHS]
    assert not missing, f"도달 동결 목록에서 빠진 Gate 2 상시 하네스: {missing}"


@pytest.mark.parametrize("harness_path", EOS142_HARNESS_PATHS)
def test_eos142_positive_control_per_path(harness_path: str) -> None:
    """양성 대조 — 정상 합성 배선에서 두 하네스 각각 위반 0."""
    assert marker_reach_violations(_synthetic(), harness_paths=(harness_path,)) == []


@pytest.mark.parametrize("harness_path", EOS142_HARNESS_PATHS)
def test_eos142_detects_ignore_of_the_harness_directory(harness_path: str) -> None:
    """그 하네스의 디렉터리를 `--ignore`하면 도달이 끊긴다 — SCENARIO 스위트는 `scenarios/`라
    기존 6종(`api/`)과 디렉터리가 달라, 목록에 없던 동안 이 형태의 끊김은 아무도 못 봤다."""
    directory = harness_path.rsplit("/", 1)[0].removeprefix("tests/backend/")
    run = f"pytest -m integration --ignore=../../tests/backend/{directory}"
    violations = marker_reach_violations(_synthetic(run=run), harness_paths=(harness_path,))
    assert violations != [] and "마커 수집으로 잡는 pytest 스텝이 없다" in violations[0]


@pytest.mark.parametrize("harness_path", EOS142_HARNESS_PATHS)
def test_eos142_detects_ignore_of_the_harness_file(harness_path: str) -> None:
    """파일 하나만 `--ignore`해도 끊긴다 — 디렉터리 단위만 보면 이 형태가 빠진다."""
    run = f"pytest -m integration --ignore=../../{harness_path}"
    assert marker_reach_violations(_synthetic(run=run), harness_paths=(harness_path,)) != []


@pytest.mark.parametrize(
    ("source", "expect"),
    [
        ("pytest.mark.xfail(strict=True, reason='x')", []),
        ("request.applymarker(pytest.mark.xfail(strict=True, reason='x'))", []),
        ("pytest.mark.xfail(reason='x')", ["strict=True가 없다"]),
        ("pytest.mark.xfail(strict=False, reason='x')", ["strict=True가 없다"]),
        ("pytest.mark.xfail(strict=True, run=False)", ["실행을 끈다"]),
        ("pytest.xfail('중간에 멈춤')", ["실행을 중간에 멈춘다"]),
        ("@pytest.mark.xfail\ndef test_x():\n    pass\n", ["느슨한 기본값"]),
    ],
)
def test_strict_xfail_checker_discriminates(source: str, expect: list[str]) -> None:
    """③-b 검사기의 변별력 — 절마다 그 절이 없으면 통과하는 반례를 둔다."""
    found = strict_xfail_violations(source, path="x.py")
    assert len(found) == len(expect), found
    for needle, message in zip(expect, found, strict=True):
        assert needle in message, (needle, message)


# ══════════════════════════════════════════════════════════════════════════
# OPS-137 — tests/backend/l3 통합 파일의 CI 수집 장부
#
# 결함: 통합 스텝이 `--ignore=../../tests/backend/l3` 디렉터리 일괄이라 l3 하위 integration 마커
# 파일 9개가 어떤 CI 스텝에서도 수집되지 않았다(같은 명령 --collect-only 0건 실측 2026-10-13). 그중
# PG만 필요한 3개(EOS-50 Publish Gate 통합 포함)까지 가려졌고, 수집되지 않는 동안 둘은 노후화돼
# 있었다(orchestrator = 수용 게이트 강화·원자 재연결 이후 후보/시드 불일치, diag_item = 재실행 중복
# 결함). 디렉터리 일괄 제외가 원인이므로 처방은 **파일 단위 제외 + 사유 장부**다 — 새 l3 통합 파일이
# 생기면 장부(수집/제외)에 올리기 전까지 이 파일이 red다.
# ══════════════════════════════════════════════════════════════════════════
_L3_DIR = "tests/backend/l3"

#: PG(+pgvector)만 필요해 CI 통합 스텝이 **수집해야 하는** l3 통합 파일. 값 = 외부 의존 판정 근거.
L3_PG_ONLY_COLLECTED: dict[str, str] = {
    "tests/backend/l3/test_publish_gate_integration.py": (
        "실 PG + alembic head(concept_version.qa). Ollama·Redis·Langfuse·Anthropic·Celery 참조 0건."
        " 8건 통과(2026-10-13 실 PG 실측)."
    ),
    "tests/backend/l3/equivalent/test_orchestrator_integration.py": (
        "실 PG + pgvector(FakeEmbeddingProvider = 라이브 모델 불요). 외부 서비스 참조 0건. 편입 전 "
        "노후화 2건 수정(근 선택 명시 · 원자 재연결 방식 개념 시드/코퍼스 절대경로 주입) 후 통과."
    ),
    "tests/backend/l3/pedagogy/test_diag_item_projector_integration.py": (
        "실 PG + data/corpus 고정물. LLM 0·외부 서비스 참조 0건. 3건 중 재실행 멱등 1건만 실제 "
        "결함으로 XFAIL(L3_TRACKED_XFAILS · PED-46) — 1회차 사실·승인 슬롯 불변 2건은 표식 없이 통과."
    ),
}

#: 라이브 외부 서비스가 있어야 검증이 성립해 CI 통합 스텝이 **파일 단위로 제외하는** l3 통합 파일.
#: 값 = 제외 사유와 **서비스가 없을 때 실제 동작**(2026-10-31 파일별 실측 — 하드 실패 2건·skip·외부 전송).
#: 수집해도 skip뿐인 파일은 검증 0건이라 넣을 이유가 없고, 하드 실패·외부 전송 파일은 넣으면 해롭다.
L3_EXTERNAL_SERVICE_EXCLUSIONS: dict[str, str] = {
    "tests/backend/l3/test_anthropic_integration.py": (
        "실제 Anthropic API 호출(WHYMATH_ANTHROPIC_API_KEY · 유료 · CI 시크릿 없음 · ARCH-66으로 "
        "2026-12-31까지 사용 중단). 키가 없으면 3건 모두 skip — 수집해도 검증 0건."
    ),
    "tests/backend/l3/test_celery_integration.py": (
        "실제 Celery + Redis broker/result backend 필요. 미도달이면 2건 모두 skip — 수집해도 검증 0건."
    ),
    "tests/backend/l3/test_langfuse_integration.py": (
        "실제 Langfuse 인스턴스·키 필요. 키가 없으면 1건 skip, 나머지 1건은 가짜 키로 "
        "cloud.langfuse.com에 **실제 네트워크 전송** — CI에서 외부로 내보내지 않는다."
    ),
    "tests/backend/l3/test_ollama_integration.py": (
        "실제 Ollama 데몬 필요(Phaiakes9 전용). 도달성 단언 1건은 미도달이면 **하드 실패**한다."
    ),
    "tests/backend/l3/test_redis_integration.py": (
        "실제 Redis 데몬 필요(CI 통합 잡에 Redis 서비스 없음). ping 단언 1건은 미도달이면 **하드 "
        "실패**하고 나머지 3건은 skip."
    ),
    "tests/backend/l3/test_visualization_live.py": (
        "실 모델·GPU가 필요한 라이브 평가(Ollama 패밀리 비교 · Phaiakes9 전용). 미도달이면 skip — "
        "수집해도 검증 0건."
    ),
}

#: 수집되지만 **알려진 결함**으로 strict xfail인 테스트 → 추적 태스크. 값 = 태스크 id 접두.
#: 키 = (파일, 함수). 태스크가 done/cancelled가 되면 이 장부 항목과 표식이 남아 있는 한 red다.
L3_TRACKED_XFAILS: dict[tuple[str, str], str] = {
    (
        "tests/backend/l3/pedagogy/test_diag_item_projector_integration.py",
        "test_diag_item_fill_rerun_is_idempotent",
    ): "PED-46",
}

_TASKS_DIR = _REPO_ROOT / "backlog" / "tasks"
_CLOSED_STATUSES = frozenset({"done", "cancelled"})


def _is_integration_mark(node: ast.AST) -> bool:
    """`<무엇>.mark.integration` 또는 `mark.integration` — `pytest` 별칭·`from pytest import mark`도 잡는다.

    `pytest.mark.integration`만 보면 `import pytest as pt`·`from pytest import mark` 형태를 놓친다
    (2026-10-31 저장소 사용 0건이지만 놓치면 새 파일이 장부 밖에서 조용히 CI 밖에 놓인다).
    """
    if not (isinstance(node, ast.Attribute) and node.attr == "integration"):
        return False
    owner = node.value
    return (isinstance(owner, ast.Name) and owner.id == "mark") or (
        isinstance(owner, ast.Attribute) and owner.attr == "mark"
    )


def integration_marked(source: str) -> bool:
    """소스가 integration 마커를 쓰는가 (순수 함수 · AST — docstring 언급에는 걸리지 않는다)."""
    return any(_is_integration_mark(node) for node in ast.walk(ast.parse(source)))


def l3_integration_files(root: pathlib.Path) -> set[str]:
    """`tests/backend/l3` 아래에서 integration 마커를 쓰는 파일 — AST로 센다.

    문자열 검색이면 docstring의 "integration 마커" 언급에 걸린다.
    """
    return {
        path.relative_to(root).as_posix()
        for path in sorted((root / _L3_DIR).rglob("*.py"))
        if integration_marked(path.read_text(encoding="utf-8"))
    }


def l3_ledger_violations(
    found: set[str], collected: Mapping[str, str], excluded: Mapping[str, str]
) -> list[str]:
    """실제 l3 통합 파일 집합과 (수집 ∪ 제외) 장부가 정확히 일치하는가 (순수 함수)."""
    violations: list[str] = []
    both = sorted(set(collected) & set(excluded))
    if both:
        violations.append(f"수집 장부와 제외 장부에 동시에 있다: {both}")
    ledger = set(collected) | set(excluded)
    if not ledger:
        violations.append("장부가 비어 있다 — 공허한 통과 금지")
    unclassified = sorted(found - ledger)
    if unclassified:
        violations.append(
            f"장부에 없는 l3 통합 파일(수집/제외를 결정해 올려라 — PG만 필요하면 수집 장부, "
            f"라이브 서비스가 필요하면 제외 장부 + ci.yml의 --ignore): {unclassified}"
        )
    stale = sorted(ledger - found)
    if stale:
        violations.append(
            f"장부에만 있고 실제로는 통합 마커 파일이 아니다(삭제·마커 제거?): {stale}"
        )
    blank = sorted(p for p, why in {**collected, **excluded}.items() if not why.strip())
    if blank:
        violations.append(f"사유가 비어 있다: {blank}")
    return violations


def ci_collects_path(spec: Mapping[str, Any], path: str) -> bool:
    """`src/backend` 작업 디렉터리의 마커 수집 pytest 호출이 `path`를 수집하는가 (순수 함수)."""
    for job in (spec.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict) or not step.get("run"):
                continue
            if _workdir_of(job, step) != _BACKEND_WORKDIR:
                continue
            for call in _pytest_tokens(str(step["run"])) or []:
                if _collects_by_marker(call, harness_path=path, workdir=_BACKEND_WORKDIR):
                    return True
    return False


def _task_status(task_id: str) -> str | None:
    """`backlog/tasks/<task_id>*.yaml`의 status. 태스크 파일이 없으면 None(= 모른다)."""
    matches = sorted(_TASKS_DIR.glob(f"{task_id}-*.yaml")) + sorted(
        _TASKS_DIR.glob(f"{task_id}.yaml")
    )
    if not matches:
        return None
    data: Any = yaml.safe_load(matches[0].read_text(encoding="utf-8"))
    return str(data.get("status")) if isinstance(data, dict) else None


#: xfail `raises`로 쓰면 모든 실패를 삼키는 넓은 예외.
_BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})


def _narrow_raises(node: ast.AST) -> bool:
    """`raises=`가 구체 예외 이름(또는 그 튜플)인가 — 넓은 예외·모르는 식은 False."""
    items = node.elts if isinstance(node, ast.Tuple) else [node]
    return bool(items) and all(
        isinstance(item, ast.Name) and item.id not in _BROAD_EXCEPTIONS for item in items
    )


def xfail_functions(source: str) -> set[str]:
    """소스에서 `@pytest.mark.xfail(...)`(호출·비호출 모두) 데코레이터를 단 테스트 함수 이름."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            target = deco.func if isinstance(deco, ast.Call) else deco
            if _is_pytest_attr(target, "mark", "xfail"):
                names.add(node.name)
    return names


def untracked_xfail_violations(
    sources: Mapping[str, str], tracked: Mapping[tuple[str, str], str]
) -> list[str]:
    """수집 장부 파일의 xfail 표식은 전부 추적 장부에 있다 (순수 함수 · 역방향).

    정방향(장부 → 표식)만 보면 장부 밖에 새로 단 xfail은 만료 장치 없이 결함을 영구히 가린다.
    이 역방향 검사가 있어서 추적 장부가 **비어도** 검사는 공허하지 않다 — 수집 파일 전수를 스캔한다.
    """
    out: list[str] = []
    for rel, source in sorted(sources.items()):
        for func in sorted(xfail_functions(source)):
            if (rel, func) not in tracked:
                out.append(
                    f"{rel}::{func} 에 xfail 표식이 있으나 추적 장부(L3_TRACKED_XFAILS)에 없다 — "
                    "추적 태스크를 등재하고 장부에 올려라(만료 없는 표식 금지)"
                )
    return out


def tracked_xfail_violations(
    source: str, *, path: str, func: str, task_id: str, task_status: str | None
) -> list[str]:
    """알려진 결함 xfail이 (1) 엄격하고 (2) 추적 태스크를 사유에 달고 (3) 만료되지 않았는가."""
    tree = ast.parse(source)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == func
        ),
        None,
    )
    if fn is None:
        return [f"{path}::{func} 가 없다 — 장부 항목이 낡았다"]
    marks = [
        d
        for d in fn.decorator_list
        if isinstance(d, ast.Call) and _is_pytest_attr(d.func, "mark", "xfail")
    ]
    if not marks:
        return [
            f"{path}::{func} 에 xfail 표식이 없다 — 장부는 알려진 결함이라 하는데 표식이 사라졌다"
        ]
    kw = {k.arg: k.value for k in marks[0].keywords if k.arg}
    out: list[str] = []
    strict = kw.get("strict")
    if not (isinstance(strict, ast.Constant) and strict.value is True):
        out.append(f"{path}::{func} xfail에 strict=True가 없다 — 결함이 고쳐져도 초록이다")
    if "raises" not in kw:
        out.append(f"{path}::{func} xfail에 raises가 없다 — 다른 종류의 실패까지 가린다")
    elif not _narrow_raises(kw["raises"]):
        out.append(
            f"{path}::{func} xfail raises가 넓다(Exception·BaseException 또는 이름이 아닌 식) "
            "— DB 오류 같은 다른 종류의 실패까지 XFAIL로 가린다"
        )
    reason = kw.get("reason")
    if not (
        isinstance(reason, ast.Constant)
        and isinstance(reason.value, str)
        and task_id in reason.value
    ):
        out.append(f"{path}::{func} xfail reason에 추적 태스크 {task_id}가 없다")
    if task_status is None:
        out.append(f"추적 태스크 {task_id} 파일을 찾지 못했다 — 모르는 상태를 통과로 읽지 않는다")
    elif task_status in _CLOSED_STATUSES:
        out.append(
            f"추적 태스크 {task_id}가 {task_status}인데 {path}::{func} 의 xfail 표식과 장부 항목이 "
            "남아 있다 — 표식을 지우고 장부(L3_TRACKED_XFAILS)에서도 뺀다"
        )
    return out


# ── 실 저장소·실 워크플로 판정 ────────────────────────────────────────────
def test_l3_integration_files_are_all_classified() -> None:
    """l3 통합 파일 전수가 수집/제외 장부에 있다 — 새 파일이 조용히 CI 밖에 놓이지 않는다."""
    found = l3_integration_files(_REPO_ROOT)
    assert found, "l3 통합 파일을 하나도 못 찾았다 — 스캔이 위장 통과할 수 없다"
    violations = l3_ledger_violations(found, L3_PG_ONLY_COLLECTED, L3_EXTERNAL_SERVICE_EXCLUSIONS)
    assert violations == [], "l3 통합 파일 장부 위반:\n" + "\n".join(f"- {v}" for v in violations)


def test_l3_pg_only_integration_files_are_collected_in_ci() -> None:
    """PG만 필요한 l3 통합 파일은 CI 마커 수집에 실제로 도달한다(스텝·마커·PG 서비스 포함)."""
    spec = _load_workflow()
    problems = [
        v
        for path in L3_PG_ONLY_COLLECTED
        for v in marker_reach_violations(spec, harness_paths=(path,))
    ]
    assert problems == [], "PG-only l3 통합 파일이 CI에서 수집되지 않는다:\n" + "\n".join(
        f"- {v}" for v in problems
    )


def test_l3_external_service_files_are_excluded_by_file_in_ci() -> None:
    """제외 장부의 파일은 CI 명령에서 실제로 제외된다 — 장부가 CI보다 앞서 낡지 않는다.

    제외가 풀리면(= 수집되면) 파일마다 결과가 다르다 — ollama·redis는 도달성 단언이 하드 실패하고,
    langfuse는 가짜 키로 외부에 실제 전송하며, 나머지는 skip이라 검증 0건이다(장부 사유 참고).
    어느 쪽이든 장부와 CI가 어긋난 것이므로 red여야 한다.
    """
    spec = _load_workflow()
    wrongly_collected = [p for p in L3_EXTERNAL_SERVICE_EXCLUSIONS if ci_collects_path(spec, p)]
    assert wrongly_collected == [], (
        f"제외 장부에 있으나 CI가 수집하는 파일: {wrongly_collected} — ci.yml의 --ignore를 "
        "되돌리거나, 외부 서비스 없이 도는 파일이 됐다면 수집 장부로 옮겨라."
    )


def test_l3_tracked_xfails_are_strict_and_unexpired() -> None:
    """알려진 결함 xfail은 엄격하고 추적 태스크를 달고 있으며 그 태스크가 닫히면 red가 된다.

    장부가 비어도 이 테스트는 지우지 않는다 — 역방향 검사(수집 파일의 표식 ⊆ 장부)가 공허하지
    않게 만든다. 해소 절차 = 표식을 지우고 장부 항목을 지운다(빈 장부는 정상 상태다).
    """
    sources = {rel: (_REPO_ROOT / rel).read_text(encoding="utf-8") for rel in L3_PG_ONLY_COLLECTED}
    assert sources, "수집 장부가 비었다 — 역방향 검사가 공허하다"
    violations = untracked_xfail_violations(sources, L3_TRACKED_XFAILS)
    for (rel, func), task_id in L3_TRACKED_XFAILS.items():
        violations += tracked_xfail_violations(
            (_REPO_ROOT / rel).read_text(encoding="utf-8"),
            path=rel,
            func=func,
            task_id=task_id,
            task_status=_task_status(task_id),
        )
    assert violations == [], "알려진 결함 xfail 위반:\n" + "\n".join(f"- {v}" for v in violations)


# ── 변별력 봉인 — 원 결함·반례를 합성 입력으로 주입한다 ───────────────────
_DIR_WIDE_RUN = "pytest -m integration --ignore=../../tests/backend/l3"
_PG_FILE = "tests/backend/l3/test_publish_gate_integration.py"
_EXT_FILE = "tests/backend/l3/test_redis_integration.py"
_FILE_LEVEL_RUN = (
    "pytest -m integration \\\n"
    "  --ignore=../../tests/backend/l3/test_redis_integration.py \\\n"
    "  --ignore=../../tests/backend/l3/test_ollama_integration.py"
)


def test_original_defect_directory_wide_ignore_hides_pg_only_file() -> None:
    """원 결함의 재현 — 디렉터리 일괄 --ignore는 PG-only 파일을 가리고 배선 판정이 red를 낸다."""
    spec = _synthetic(run=_DIR_WIDE_RUN)
    assert ci_collects_path(spec, _PG_FILE) is False
    assert marker_reach_violations(spec, harness_paths=(_PG_FILE,)) != []


def test_file_level_ignore_collects_pg_only_and_excludes_external() -> None:
    """양성 대조 — 파일 단위 제외는 PG-only를 수집하고 제외한 파일만 뺀다(무차별 red/green 아님)."""
    spec = _synthetic(run=_FILE_LEVEL_RUN)
    assert ci_collects_path(spec, _PG_FILE) is True
    assert marker_reach_violations(spec, harness_paths=(_PG_FILE,)) == []
    assert ci_collects_path(spec, _EXT_FILE) is False


def test_ci_collects_path_requires_backend_workdir_and_marker() -> None:
    """작업 디렉터리·마커 축 반례 — 어느 하나만 틀려도 수집으로 보지 않는다."""
    assert (
        ci_collects_path(_synthetic(workdir="src/data-pipeline", run=_FILE_LEVEL_RUN), _PG_FILE)
        is False
    )
    assert (
        ci_collects_path(_synthetic(run="pytest --ignore=../../tests/backend/api"), _PG_FILE)
        is False
    )


def test_ledger_detects_unclassified_overlap_stale_and_blank() -> None:
    """장부 판정의 축마다 반례 — 각 분기를 한 번씩 밟는다."""
    ok = l3_ledger_violations({"a", "b"}, {"a": "pg"}, {"b": "live"})
    assert ok == []
    assert l3_ledger_violations({"a", "b", "new"}, {"a": "pg"}, {"b": "live"}) != []  # 미분류 신규
    assert l3_ledger_violations({"a"}, {"a": "pg"}, {"a": "live"}) != []  # 양쪽 동시
    assert l3_ledger_violations({"a"}, {"a": "pg", "gone": "x"}, {}) != []  # 낡은 장부
    assert l3_ledger_violations({"a"}, {"a": "  "}, {}) != []  # 빈 사유
    assert l3_ledger_violations(set(), {}, {}) != []  # 공허


_XFAIL_OK = (
    "import pytest\n"
    "@pytest.mark.xfail(strict=True, raises=AssertionError, reason='PED-46: dup')\n"
    "def test_x():\n    assert False\n"
)


def _tx(source: str = _XFAIL_OK, status: str | None = "todo", task: str = "PED-46") -> list[str]:
    return tracked_xfail_violations(
        source, path="t.py", func="test_x", task_id=task, task_status=status
    )


def test_tracked_xfail_checker_detects_each_axis() -> None:
    """추적 xfail 판정의 축마다 반례 — 만료 축(태스크 done)이 이 장부의 핵심이다."""
    assert _tx() == []
    assert _tx(status="done") != []  # 태스크가 닫혔는데 표식이 남음 → 만료
    assert _tx(status="cancelled") != []
    assert _tx(status=None) != []  # 모르는 상태는 통과가 아니다
    assert _tx(_XFAIL_OK.replace("strict=True, ", "")) != []  # 느슨한 xfail
    assert _tx(_XFAIL_OK.replace("raises=AssertionError, ", "")) != []  # 다른 실패까지 가림
    assert _tx(_XFAIL_OK.replace("PED-46", "other")) != []  # 추적 태스크 미표기
    assert (
        _tx(
            _XFAIL_OK.replace(
                "@pytest.mark.xfail(strict=True, raises=AssertionError, reason='PED-46: dup')\n", ""
            )
        )
        != []
    )  # 표식 소실
    assert _tx(_XFAIL_OK.replace("test_x", "test_y")) != []  # 함수 소실


# ── OPS-137 검토 반영 — 파서 절마다 그 절을 밟는 반례 (2026-10-31) ─────────────
# 원 파서는 모르는 옵션을 건너뛰었다. 그래서 수집에서 빼는 옵션을 "수집함"으로 읽었다.
# 아래 반례는 절마다 **그 절이 없으면 통과해 버리는 입력**이다.
_COLLECT_OK = "pytest -m integration --ignore=../../tests/backend/l3/test_redis_integration.py"


def _collects(run: str, path: str = _PG_FILE) -> bool:
    return ci_collects_path(_synthetic(run=run), path)


def test_positive_control_hardened_parser_keeps_real_shape() -> None:
    """양성 대조 — 실제 CI 꼴(여러 줄 · 파일 단위 --ignore)과 무해한 옵션은 여전히 수집으로 본다."""
    assert _collects(_FILE_LEVEL_RUN) is True
    assert _collects(_COLLECT_OK + " -q --tb=short -rxXs --durations 10") is True
    assert _collects("pytest -m 'integration and not slow'") is True
    assert _collects("pytest -m '(integration or db)'") is True


@pytest.mark.parametrize(
    "run",
    [
        # --deselect: `=` 결합형 · 공백형 · 노드 id 꼬리형
        "pytest -m integration --deselect=../../tests/backend/l3/test_publish_gate_integration.py",
        "pytest -m integration --deselect ../../tests/backend/l3/test_publish_gate_integration.py",
        "pytest -m integration --deselect=l3/test_publish_gate_integration.py::test_x",
        # --ignore-glob: 파일 · 상위 디렉터리
        "pytest -m integration --ignore-glob=../../tests/backend/l3/*_integration.py",
        "pytest -m integration --ignore-glob ../../tests/backend/l*",
        # 수집 범위를 바꾸는 옵션 · 모르는 옵션
        "pytest -m integration -k 'not publish'",
        "pytest -m integration -o testpaths=../../tests/backend/api",
        "pytest -m integration --override-ini=testpaths=../../tests/backend/api",
        "pytest -m integration --collect-only",
        "pytest -m integration --some-unknown-plugin-flag",
        # 마커 식이 integration을 고르지 않는다
        "pytest -m 'not integration'",
        "pytest -m 'db and not integration'",
        "pytest -m 'integration and'",
    ],
)
def test_hardened_parser_rejects_collection_excluding_options(run: str) -> None:
    """각 형태는 PG-only 파일을 수집에서 빼거나 수집을 증명하지 못한다 — 수집으로 읽으면 RED."""
    assert _collects(run) is False


def test_ignore_is_resolved_against_working_directory() -> None:
    """`--ignore`는 작업 디렉터리(`src/backend`) 기준이다 — 저장소 루트 기준으로 쓴 경로는 아무것도
    빼지 않으므로 제외 장부 파일이 실제로는 수집된다(원 파서는 이것을 "제외됨"으로 읽었다)."""
    run = "pytest -m integration --ignore=tests/backend/l3/test_redis_integration.py"
    assert ci_collects_path(_synthetic(run=run), _EXT_FILE) is True
    assert ci_collects_path(_synthetic(run=_FILE_LEVEL_RUN), _EXT_FILE) is False


def test_marker_expression_evaluator_discriminates() -> None:
    """마커 식 계산 — `not`·`and`·`or`·괄호 각 분기와 문법 밖 식."""
    assert _marker_selects_integration("integration") is True
    assert _marker_selects_integration("not integration") is False
    assert _marker_selects_integration("integration and not slow") is True
    assert _marker_selects_integration("slow and integration") is False
    assert _marker_selects_integration("slow or integration") is True
    assert _marker_selects_integration("not (slow or integration)") is False
    assert _marker_selects_integration("(integration") is False  # 괄호 불일치
    assert _marker_selects_integration("integration slow") is False  # 남는 토큰
    assert _marker_selects_integration("") is False


@pytest.mark.parametrize(
    ("source", "expect"),
    [
        ("import pytest\npytestmark = pytest.mark.integration\n", True),
        ("import pytest as pt\npytestmark = pt.mark.integration\n", True),
        ("from pytest import mark\npytestmark = mark.integration\n", True),
        ("import pytest\npytestmark = [pytest.mark.integration, pytest.mark.slow]\n", True),
        ('"""integration 마커 언급만 있는 docstring."""\nimport pytest\n', False),
        ("import pytest\npytestmark = pytest.mark.slow\n", False),
    ],
)
def test_integration_mark_scan_catches_alias_forms(source: str, expect: bool) -> None:
    """AST 스캔 — 별칭·`from pytest import mark` 형태도 잡고, docstring 언급은 잡지 않는다."""
    assert integration_marked(source) is expect


@pytest.mark.parametrize(
    "raises",
    ["Exception", "BaseException", "(AssertionError, Exception)", "errors.ANY"],
)
def test_tracked_xfail_rejects_broad_raises(raises: str) -> None:
    """`raises`가 넓으면 다른 종류의 실패까지 XFAIL로 가린다 — 있기만 하면 통과하던 축."""
    source = _XFAIL_OK.replace("raises=AssertionError", f"raises={raises}")
    assert source != _XFAIL_OK
    assert any("raises가 넓다" in v for v in _tx(source))


def test_tracked_xfail_accepts_narrow_tuple() -> None:
    """양성 대조 — 구체 예외의 튜플은 허용한다."""
    source = _XFAIL_OK.replace("raises=AssertionError", "raises=(AssertionError, KeyError)")
    assert _tx(source) == []


def test_untracked_xfail_in_collected_file_is_detected() -> None:
    """역방향 — 수집 파일에 장부 밖 xfail을 새로 달면 RED. 비호출 데코레이터 꼴도 잡는다."""
    called = "import pytest\n@pytest.mark.xfail(strict=True, raises=AssertionError)\ndef test_a():\n    pass\n"
    bare = "import pytest\n@pytest.mark.xfail\ndef test_b():\n    pass\n"
    assert untracked_xfail_violations({"f.py": called}, {}) != []
    assert untracked_xfail_violations({"f.py": bare}, {}) != []
    assert untracked_xfail_violations({"f.py": called}, {("f.py", "test_a"): "PED-46"}) == []
    assert untracked_xfail_violations({"f.py": "def test_c():\n    pass\n"}, {}) == []
