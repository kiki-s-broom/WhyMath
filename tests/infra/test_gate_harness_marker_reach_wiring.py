"""[EOS-21] Gate 2 판정 하네스 6종이 **CI에서 실제 판정에 도달하는가**를 동결한다.

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
⑶ `--ignore`가 `l3`만 제외. 셋 중 **아무거나 하나**가 바뀌면(예: `--ignore`에 `api` 추가,
마커 변경, `testpaths` 축소, `WHYMATH_RUN_INTEGRATION` 제거) 6종은 조용히 skip으로 돌아가고
skip은 exit 0이다. 즉 `EOS-21`이 막으려던 상태가 **아무 경고 없이** 재생산된다.

암묵 배선을 명시 계약으로 바꾸는 것이 이 파일의 일이다. 워크플로에 중복 스텝을 더해
같은 테스트를 두 번 돌리는 쪽(실행 시간 추가)은 택하지 않았다 — 비용 없이 같은 보호를
얻을 수 있고, 명시 스텝을 더해도 *그것이 도달하는지*는 결국 이 형태의 가드가 봐야 한다.

재사용 (acceptance ③ '재구현 0')
--------------------------------
`test_p11_chain_nightly_wiring.real_pg_violations`가 "그 잡이 실 PG에 도달하는가"를 이미
순수 함수로 판정하고 합성 워크플로 주입으로 변별력을 봉인해 뒀다. 그 함수는 대상 스텝을
**이름으로** 찾으므로 마커 수집 경로에는 그대로 쓸 수 없다 — 그래서 이 파일은 *대상을 찾는
축만* 새로 쓰고, 찾은 잡의 PG 도달 판정은 **그 함수를 그대로 호출**한다(어댑터 경유).
"""

from __future__ import annotations

import importlib.util
import pathlib
import shlex
import sys
from collections.abc import Mapping
from types import ModuleType
from typing import Any

import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_PG_GUARD_PATH = pathlib.Path(__file__).with_name("test_p11_chain_nightly_wiring.py")

#: Gate 2 판정 하네스 — EOS-22 Gate 2 10조건의 근거가 되는 6종.
GATE_HARNESS_PATHS: tuple[str, ...] = (
    "tests/backend/api/test_week1_gate_closed_loop.py",
    "tests/backend/api/test_week2_gate_wrong_answer_propagation.py",
    "tests/backend/api/test_week3_gate_remediation_loop.py",
    "tests/backend/api/test_e2e_persona_journeys.py",
    "tests/backend/api/test_p11_five_stage_loop_chain.py",
    "tests/backend/api/test_e2e_vertical_slice_integration.py",
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


def _collects_by_marker(tokens: list[str], *, harness_path: str) -> bool:
    """이 pytest 호출이 `harness_path`를 **마커 수집**으로 잡는가.

    세 조건을 모두 본다:
      ⑴ `-m` 값에 `integration`이 들어 있다 (마커로 거른다)
      ⑵ 위치 인자(경로)를 주지 않는다 — 주면 testpaths가 무시되고 그 경로만 돈다
      ⑶ `--ignore` 값이 이 하네스의 디렉터리를 배제하지 않는다

    ⑶이 이 판정의 급소다. 지금 `--ignore=../../tests/backend/l3` 하나가 붙어 있는데,
    거기에 `api`가 추가되는 순간 6종은 전부 수집에서 빠지고 스텝은 여전히 초록이다.
    """
    marker_value = ""
    ignores: list[str] = []
    positionals: list[str] = []
    i = 0
    # `pytest` 토큰 이후만 본다 — 그 앞은 `python -m` 같은 런처다.
    start = next(
        (idx + 1 for idx, t in enumerate(tokens) if pathlib.Path(t).name == "pytest"),
        len(tokens),
    )
    i = start
    while i < len(tokens):
        token = tokens[i]
        if token == "-m":
            marker_value = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2
            continue
        if token.startswith("-m") and len(token) > 2:
            marker_value = token[2:]
            i += 1
            continue
        if token == "--ignore":
            if i + 1 < len(tokens):
                ignores.append(tokens[i + 1])
            i += 2
            continue
        if token.startswith("--ignore="):
            ignores.append(token.split("=", 1)[1])
            i += 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        positionals.append(token)
        i += 1

    if "integration" not in marker_value:
        return False
    if positionals:
        return False
    for ignored in ignores:
        normalized = ignored.lstrip("./").removeprefix("../../")
        if normalized and harness_path.startswith(normalized.rstrip("/") + "/"):
            return False
        if normalized.rstrip("/") == harness_path:
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
    """6종이 **마커 수집으로 판정에 도달하는가** (순수 함수).

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
