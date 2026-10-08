"""[HARN-22] 번호 충돌 머지 시점 안전망(`backlog.py validate`)의 CI **배선 실재성** 동결.

왜 이 테스트가 있는가
--------------------
`tests/harness/test_id_number_suggestion_race.py`는 `validate`가 머지된 중복 번호를 exit 1로
잡는다는 **동작**을 동결한다. 그러나 "머지 시점에 반드시 잡힌다"가 성립하려면 그 `validate`가
**실제로 매 PR·매 머지 큐 실행에서 돌아야** 한다 — 저장소에 있는 것과 CI가 돌리는 것은 다르다
(CLAUDE.md "검증 장치를 만들고 배선 확인 없이 완료 선언 금지" · OPS-03·OPS-08 선례). 예약(HARN-111)이
닿지 않는 구간의 유일한 방어선이 이 한 스텝이므로, 조용히 빠지거나 fail-open이 되면 중복 번호가
main에 들어간다.

검증 계약 (각 항목은 결함 주입으로 변별력이 확인된 것만)
------------------------------------------------------
① `harness-integrity` 잡에 `backlog.py validate`를 **명령 줄로** 실행하는 스텝이 있다
   (주석 처리된 줄은 실행이 아니다).
② 그 스텝이 fail-open이 아니다 — `continue-on-error: true`·`|| true`는 exit 1을 삼킨다.
③ 잡이 경로 필터에 종속되지 않는다 — `needs: changes`나 잡 수준 `if:`가 있으면 태스크 YAML만
   바꾸는 PR에서 skip될 수 있고, GitHub는 skipped를 required check 충족으로 센다.
④ 워크플로가 `pull_request`와 `merge_group` 양쪽에서 돈다 — 머지 큐는 main 최신 위에 PR을 얹어
   재검증하는 곳이라, 두 PR이 각자 통과한 뒤 **합쳐져서** 생기는 충돌은 여기서만 보인다.
⑤ 파서가 위장하지 않는다 — 워크플로·잡을 못 찾으면 "위반 0 통과"가 아니라 예외로 실패한다.

판정 로직(`_violations`)을 순수 함수로 두고, 실제 ci.yml 외에 **결함을 주입한 사본**도 판정시켜
각 결함이 실제로 검출됨을 매번 재확인한다(양성 대조 포함).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_JOB_KEY = "harness-integrity"
# 줄 단위 매칭 — 주석(`# python3 ... validate`)은 실행이 아니므로 줄 시작이 명령이어야 한다.
# 줄 끝은 앵커하지 않는다: `validate || true`도 validate **스텝**으로 인식돼야 ②의 fail-open
# 검사 절에 도달한다(끝 앵커를 두면 그 절이 도달 불가 코드가 된다 — 주입 실측으로 발각).
_VALIDATE_LINE = re.compile(r"^\s*python3?\s+scripts/harness/backlog\.py\s+validate(?:\s|$)")
_REQUIRED_TRIGGERS = ("pull_request", "merge_group")


def _load_spec() -> dict[str, Any]:
    if not _CI_PATH.is_file():
        raise AssertionError(f"{_CI_PATH} 이(가) 없다 — 안전망 배선을 확인할 수 없다.")
    spec = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("jobs"), dict) or not spec["jobs"]:
        raise AssertionError("ci.yml에 jobs가 없다 — 파싱이 위장 통과할 수 없다.")
    return spec


def _triggers(spec: dict[str, Any]) -> set[str]:
    # PyYAML(YAML 1.1)은 키 `on`을 불리언 True로 읽는다 — 두 표기를 모두 받는다
    raw = spec.get(True, spec.get("on"))
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw}
    if isinstance(raw, dict):
        return {str(key) for key in raw}
    return set()


def _validate_steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        lines = str(step.get("run") or "").splitlines()
        if any(_VALIDATE_LINE.match(line) for line in lines):
            found.append(step)
    return found


def _violations(spec: dict[str, Any]) -> list[str]:
    job = spec["jobs"].get(_JOB_KEY)
    if not isinstance(job, dict):
        raise AssertionError(f"ci.yml에 '{_JOB_KEY}' 잡이 없다 — 안전망이 돌 곳이 없다.")
    out: list[str] = []
    steps = _validate_steps(job)
    if not steps:
        out.append(f"'{_JOB_KEY}'에 `backlog.py validate`를 실행하는 스텝이 없다")
    for step in steps:
        if step.get("continue-on-error") is True:
            out.append("validate 스텝에 continue-on-error: true — exit 1이 삼켜진다")
        if re.search(r"\|\|\s*true\b", str(step.get("run") or "")):
            out.append("validate 호출이 `|| true`로 판정을 무력화한다")
    needs = job.get("needs")
    needs_list = [needs] if isinstance(needs, str) else list(needs or [])
    if "changes" in needs_list:
        out.append("잡이 `needs: changes`에 종속 — 경로 필터로 skip될 수 있다")
    if "if" in job:
        out.append(
            f"잡 수준 `if:` 존재({job['if']!r}) — 조건부 skip은 required check 충족으로 센다"
        )
    missing = [t for t in _REQUIRED_TRIGGERS if t not in _triggers(spec)]
    if missing:
        out.append(f"워크플로 트리거 누락: {missing}")
    return out


def _without_validate_step(spec: dict[str, Any]) -> None:
    job = spec["jobs"][_JOB_KEY]
    job["steps"] = [s for s in job["steps"] if s not in _validate_steps(job)]


def _commented_out(spec: dict[str, Any]) -> None:
    for step in _validate_steps(spec["jobs"][_JOB_KEY]):
        step["run"] = "# " + str(step["run"]).strip()


def _continue_on_error(spec: dict[str, Any]) -> None:
    for step in _validate_steps(spec["jobs"][_JOB_KEY]):
        step["continue-on-error"] = True


def _swallow_exit(spec: dict[str, Any]) -> None:
    for step in _validate_steps(spec["jobs"][_JOB_KEY]):
        step["run"] = str(step["run"]).strip() + " || true"


def _path_filtered(spec: dict[str, Any]) -> None:
    spec["jobs"][_JOB_KEY]["needs"] = "changes"


def _job_if(spec: dict[str, Any]) -> None:
    spec["jobs"][_JOB_KEY]["if"] = "github.event_name != 'pull_request'"


def _drop_trigger(name: str):
    def mutate(spec: dict[str, Any]) -> None:
        key = True if True in spec else "on"
        spec[key] = {k: v for k, v in dict(spec[key]).items() if k != name}

    return mutate


# 결함 이름 → (주입 함수, 검출 시 위반 문구에 있어야 할 조각). 조각까지 고정하는 이유: 엉뚱한
# 위반으로 우연히 검출되는 것(예: 주석 처리가 '스텝 없음'이 아니라 다른 이유로 걸림)은 그 결함을
# 잡는다는 증거가 아니다.
_DEFECTS = {
    "스텝 삭제": (_without_validate_step, "스텝이 없다"),
    "주석 처리": (_commented_out, "스텝이 없다"),
    "continue-on-error": (_continue_on_error, "continue-on-error"),
    "|| true": (_swallow_exit, "|| true"),
    "needs: changes": (_path_filtered, "needs: changes"),
    "잡 수준 if": (_job_if, "잡 수준 `if:`"),
    "merge_group 트리거 삭제": (_drop_trigger("merge_group"), "merge_group"),
    "pull_request 트리거 삭제": (_drop_trigger("pull_request"), "pull_request"),
}


def test_real_workflow_runs_validate_unfiltered_on_pr_and_merge_queue() -> None:
    """실제 ci.yml이 ①~④를 모두 만족한다."""
    assert _violations(_load_spec()) == []


@pytest.mark.parametrize("name", sorted(_DEFECTS))
def test_each_injected_defect_is_detected_for_the_right_reason(name: str) -> None:
    """각 결함을 주입한 사본은 **그 결함 때문에** 위반으로 판정된다 — 변별력을 상시 봉인한다."""
    spec = copy.deepcopy(_load_spec())
    assert _violations(spec) == [], "전제: 주입 전 사본은 정상이어야 한다(양성 대조)"
    mutate, fragment = _DEFECTS[name]
    mutate(spec)
    found = _violations(spec)
    assert found, f"결함 '{name}'을 주입했는데 검출되지 않았다 — 판정 로직이 위장이다"
    assert any(
        fragment in line for line in found
    ), f"결함 '{name}'이 엉뚱한 이유로 검출됐다(기대 조각 {fragment!r}): {found}"


def test_parser_does_not_masquerade_when_job_is_missing() -> None:
    """⑤ 잡을 못 찾으면 '위반 0 통과'가 아니라 예외다."""
    spec = copy.deepcopy(_load_spec())
    del spec["jobs"][_JOB_KEY]
    with pytest.raises(AssertionError, match=_JOB_KEY):
        _violations(spec)
