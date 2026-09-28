"""`harness-integrity` 잡의 시간 예산이 실측 소요보다 충분히 큰지 동결 (OPS-69).

왜 이 테스트가 있는가 (2026-09-28 사고)
---------------------------------------
`harness-integrity`는 필터와 무관하게 **매 PR·매 머지 큐 실행**에서 도는 상시 잡이다. 이 잡의
`timeout-minutes: 5`는 잡이 초 단위로 끝나던 시절의 값이었는데, 하네스 테스트가 1,161건에서
1,268건으로 늘자(#1345 +107건) 잡 소요가 약 5분 4~6초가 됐다. 그 결과 머지 큐 실행 2건
(#1344 · #1341)이 **하네스 테스트 전건 통과 직후** `cancelled`로 잘려 두 PR이 큐에서 빠졌다.
실패가 아니라 시간 예산 소진이라 로그에는 `1268 passed` 바로 뒤에 `The operation was
canceled.`만 남는다. 상시 잡이므로 이 상태에서는 모든 PR의 머지가 막힌다.

같은 부류의 2회차다. 1회차는 `OPS-47`(backend 잡 여유 16% 소진, 2026-08-21)이다. 이 파일은
상한을 12분으로 올린 수정이 조용히 되돌려지는 것을 막는다. 잡별 소요를 실제 실행 이력에서
재는 상시 감시는 이 테스트가 할 수 없다(실행 이력이 필요하다). 그 축은 후속 태스크가 맡는다.

검증 계약 (각 항목은 변별력이 확인된 것만 — CLAUDE.md "변별력 없는 검증 스텝 금지")
--------------------------------------------------------------------------------
① `harness-integrity` 잡이 존재하고 `timeout-minutes`를 **정수로** 선언한다. 키가 없으면 GitHub
   기본값 360분이 적용돼 폭주를 가리므로 부재도 실패다.
② 상한이 실측 최대 소요(5.1분)의 여유 30% 이상을 확보한다(OPS-47 기준 "상한의 30% 이상").
③ 상한이 하한 10분 이상이다 — 테스트가 계속 늘어나는 잡이라 경계값에 맞춘 상한은 곧 다시 소진된다.
④ 파서가 위장하지 않는다 — ci.yml을 못 읽거나 잡을 못 찾으면 "통과"가 아니라 예외로 실패한다.

RED 실측(OPS-69 검증): 상한을 5로 되돌림 → ②③ RED · 키 삭제 → ① RED · 잡 이름 변경 → ① RED.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_JOB = "harness-integrity"

# 2026-09-28 머지 큐 실측 최대 소요(분). 실행 36394014666(#1341) 5분 6초 ·
# 36393409009(#1344) 5분 4초 — 둘 다 테스트 전건 통과 직후 cancelled.
_MEASURED_MAX_MINUTES = 5.1
# OPS-47이 정한 여유 기준: 최대 표본 소요가 상한의 70% 이하(여유 30% 이상).
_MIN_HEADROOM_RATIO = 0.30
# 하한 — 하네스 테스트가 계속 늘어나는 잡이라 경계값 상한은 곧 다시 소진된다.
_MIN_TIMEOUT_MINUTES = 10


def _extract_job(spec: Any, source: str, job_name: str) -> dict[str, Any]:
    """스펙에서 잡 하나를 꺼낸다 — 비매핑·jobs 공백·잡 부재는 예외(계약 ④)."""
    if not isinstance(spec, dict):
        raise AssertionError(f"{source}: 워크플로 YAML이 매핑으로 파싱되지 않았다.")
    jobs = spec.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        raise AssertionError(f"{source}: jobs 블록이 비었다 — 파서가 배선을 읽지 못하는 상태다.")
    job = jobs.get(job_name)
    if not isinstance(job, dict):
        raise AssertionError(
            f"{source}: '{job_name}' 잡이 없다 — 이름이 바뀌었다면 이 동결도 옮겨라."
        )
    return job


def _timeout_minutes(job: dict[str, Any], job_name: str) -> int:
    """잡의 timeout-minutes를 정수로 돌려준다 — 부재·비정수는 예외(계약 ①)."""
    value = job.get("timeout-minutes")
    if value is None:
        raise AssertionError(
            f"'{job_name}' 잡에 timeout-minutes가 없다 — 기본값 360분이 적용돼 폭주를 가린다."
        )
    # bool은 int의 하위형이라 먼저 걸러낸다(true를 1분으로 읽지 않는다).
    if isinstance(value, bool) or not isinstance(value, int):
        raise AssertionError(f"'{job_name}' 잡의 timeout-minutes가 정수가 아니다: {value!r}")
    return value


def _load_harness_job() -> dict[str, Any]:
    if not _CI_YAML.is_file():
        raise AssertionError(f"{_CI_YAML}: CI 워크플로 파일이 없다 — 배선을 읽을 수 없다.")
    spec = yaml.safe_load(_CI_YAML.read_text(encoding="utf-8"))
    return _extract_job(spec, str(_CI_YAML), _JOB)


def test_harness_integrity_declares_integer_timeout() -> None:
    """① 키가 있고 정수다."""
    assert _timeout_minutes(_load_harness_job(), _JOB) > 0


def test_harness_integrity_timeout_keeps_headroom_over_measured_duration() -> None:
    """② 실측 최대 소요가 상한의 70% 이하다(여유 30% 이상)."""
    timeout = _timeout_minutes(_load_harness_job(), _JOB)
    usable = timeout * (1 - _MIN_HEADROOM_RATIO)
    assert usable >= _MEASURED_MAX_MINUTES, (
        f"'{_JOB}' 상한 {timeout}분의 70%({usable:.1f}분)가 실측 최대 소요 "
        f"{_MEASURED_MAX_MINUTES}분보다 작다 — 머지 큐가 테스트 통과 직후 cancelled로 막힌다(OPS-69)."
    )


def test_harness_integrity_timeout_meets_floor() -> None:
    """③ 하한 10분 이상."""
    timeout = _timeout_minutes(_load_harness_job(), _JOB)
    assert timeout >= _MIN_TIMEOUT_MINUTES, (
        f"'{_JOB}' 상한 {timeout}분 < 하한 {_MIN_TIMEOUT_MINUTES}분 — 테스트가 늘어나는 잡이라 "
        f"경계값 상한은 곧 다시 소진된다(OPS-69 · OPS-47 선례)."
    )


@pytest.mark.parametrize(
    ("spec", "needle"),
    [
        (None, "매핑으로 파싱되지 않았다"),
        ({"jobs": {}}, "jobs 블록이 비었다"),
        ({"jobs": {"other": {"runs-on": "x"}}}, "잡이 없다"),
    ],
)
def test_parser_fails_loudly_instead_of_passing(spec: Any, needle: str) -> None:
    """④ 파서가 못 읽는 상태는 통과가 아니라 예외다."""
    with pytest.raises(AssertionError, match=needle):
        _extract_job(spec, "<synthetic>", _JOB)


@pytest.mark.parametrize(
    ("job", "needle"),
    [
        ({"runs-on": "x"}, "timeout-minutes가 없다"),
        ({"timeout-minutes": "12"}, "정수가 아니다"),
        ({"timeout-minutes": True}, "정수가 아니다"),
    ],
)
def test_timeout_reader_rejects_absent_or_non_integer(job: dict[str, Any], needle: str) -> None:
    """① 부재·문자열·불리언은 통과가 아니라 예외다(문자열 식 `${{ }}`도 여기서 걸린다)."""
    with pytest.raises(AssertionError, match=needle):
        _timeout_minutes(job, _JOB)
