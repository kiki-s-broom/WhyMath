"""CI 잡 5종의 시간 예산(`timeout-minutes`) 하한 동결 (OPS-120).

왜 이 테스트가 있는가 (2026-10-09 OPS-100 첫 실측)
--------------------------------------------------
`ci-timeout-headroom` 감시(OPS-100)가 최근 실행 이력에서 여유 30% 미만 잡을 찾았고, 이
태스크가 상한을 올려 되돌렸다. 상한이 조용히 되돌려지면 같은 소진이 6번째로 반복되므로
(2026-07-25·08-21·09-01·09-28·10-06) 올린 상한의 **하한**을 여기서 동결한다. 실제 소요가
상한에 다가가는 것은 실행 이력이 필요하므로 이 테스트가 아니라 OPS-100 감시가 맡는다.

하한의 근거는 잡마다 실측 최대 소요(분)이고, 기준은 OPS-47이 정한 "최대 표본이 상한의 70%
이하(여유 30% 이상)"다. 아래 실측은 2026-10-09 `measure_ci_job_timeout_headroom.py`
(push·merge_group·schedule 각 최근 20건)의 완주 표본 최대다.

검증 계약 (변별력은 RED 실측으로 확인 — 맨 아래 `검증 기록`)
----------------------------------------------------------
① 5개 잡이 모두 존재하고 `timeout-minutes`를 **정수로** 선언한다(부재면 GitHub 기본 360분이
   폭주를 가린다).
② 상한이 실측 최대의 여유 30% 이상을 확보한다(`상한 × 0.7 ≥ 실측 최대`).
③ 파서가 위장하지 않는다 — YAML이 매핑이 아니거나 jobs가 비었거나 잡이 없으면 통과가 아니라
   예외로 실패한다(`_extract_job`).
④ 잡 이름이 바뀌면 동결이 조용히 사라지지 않고 ①에서 실패한다(이름 불일치 = 예외).

harness-integrity 한 잡은 OPS-69의 `test_ci_harness_integrity_timeout.py`(실측 5.1분 기준,
하한 10분)가 별도로 동결한다. 이 파일은 같은 잡의 **현재** 실측(9.18분)을 기준으로 더 높은
하한을 건다 — 두 테스트는 충돌하지 않고 엄격한 쪽이 이긴다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_YAML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# OPS-47 기준: 최대 표본 소요가 상한의 70% 이하(여유 30% 이상).
_MIN_HEADROOM_RATIO = 0.30

# 잡 id → (2026-10-09 실측 최대 소요 분, 근거 표본 수). 이름은 ci.yml의 잡 키(id)다.
_MEASURED_MAX_MINUTES: dict[str, tuple[float, int]] = {
    "backend": (31.93, 33),
    "backend-migrations": (14.10, 39),
    "backend-serial-nightly": (33.15, 17),
    "harness-integrity": (9.18, 59),
    "infra-contracts": (7.15, 57),
}


def _extract_job(spec: Any, source: str, job_name: str) -> dict[str, Any]:
    """스펙에서 잡 하나를 꺼낸다 — 비매핑·jobs 공백·잡 부재는 예외(계약 ③④)."""
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


def _declared_timeout(job_name: str) -> int:
    if not _CI_YAML.is_file():
        raise AssertionError(f"{_CI_YAML}: CI 워크플로 파일이 없다 — 배선을 읽을 수 없다.")
    spec = yaml.safe_load(_CI_YAML.read_text(encoding="utf-8"))
    return _timeout_minutes(_extract_job(spec, str(_CI_YAML), job_name), job_name)


def _headroom_shortfall(timeout: int, measured_max: float) -> float:
    """여유 기준을 채우려면 상한이 몇 분 모자란지(0이하면 충족)."""
    return measured_max / (1 - _MIN_HEADROOM_RATIO) - timeout


@pytest.mark.parametrize("job_name", sorted(_MEASURED_MAX_MINUTES))
def test_job_declares_integer_timeout(job_name: str) -> None:
    """① 잡이 있고 timeout-minutes가 양의 정수다."""
    assert _declared_timeout(job_name) > 0


@pytest.mark.parametrize("job_name", sorted(_MEASURED_MAX_MINUTES))
def test_job_timeout_keeps_30_percent_headroom_over_measured_max(job_name: str) -> None:
    """② 실측 최대 소요가 상한의 70% 이하다(여유 30% 이상)."""
    measured, samples = _MEASURED_MAX_MINUTES[job_name]
    timeout = _declared_timeout(job_name)
    shortfall = _headroom_shortfall(timeout, measured)
    assert shortfall <= 1e-9, (
        f"'{job_name}' 상한 {timeout}분 × 0.7 = {timeout * 0.7:.1f}분 < 실측 최대 {measured}분"
        f"(표본 {samples}건, 2026-10-09) — 여유 30%를 채우려면 {measured / 0.7:.1f}분 이상이어야 "
        f"한다. 상한이 되돌려졌다면 ci-timeout-headroom 감시가 적색이 된다(OPS-120)."
    )


# ── 파서가 위장하지 않는다(계약 ③) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spec", "needle"),
    [
        (None, "매핑으로 파싱되지 않았다"),
        ({"jobs": {}}, "jobs 블록이 비었다"),
        ({"jobs": {"other": {"runs-on": "x"}}}, "잡이 없다"),
    ],
)
def test_parser_fails_loudly_instead_of_passing(spec: Any, needle: str) -> None:
    """파서가 못 읽는 상태는 통과가 아니라 예외다."""
    with pytest.raises(AssertionError, match=needle):
        _extract_job(spec, "<synthetic>", "backend")


@pytest.mark.parametrize(
    ("job", "needle"),
    [
        ({"runs-on": "x"}, "timeout-minutes가 없다"),
        ({"timeout-minutes": "50"}, "정수가 아니다"),
        ({"timeout-minutes": True}, "정수가 아니다"),
    ],
)
def test_timeout_reader_rejects_absent_or_non_integer(job: dict[str, Any], needle: str) -> None:
    """부재·문자열·불리언은 통과가 아니라 예외다(`${{ }}` 식도 여기서 걸린다)."""
    with pytest.raises(AssertionError, match=needle):
        _timeout_minutes(job, "backend")


# ── 판정 함수의 경계(계약 ②의 산술) ──────────────────────────────────────────────


def test_shortfall_boundary_is_exactly_30_percent() -> None:
    """상한×0.7이 실측과 정확히 같으면 충족, 한 자리라도 모자라면 부족이다."""
    # 14분 × 0.7 = 9.8분 → 실측 9.8이면 정확히 경계(충족), 9.81이면 부족.
    assert _headroom_shortfall(14, 9.8) <= 1e-9
    assert _headroom_shortfall(14, 9.81) > 1e-9


def test_pre_ops120_limits_would_have_failed_the_headroom_check() -> None:
    """OPS-120 이전 상한이 이 실측에서 실제로 '부족'으로 판정됨을 고정한다(변별력 대조군).

    상한을 되돌리면 ②가 RED가 된다는 것을 코드로 보인다 — 정상 입력에서만 초록인 동결은
    보호가 아니다. 이전 상한은 ci.yml 주석과 MEMORY의 OPS-100 첫 실측 기록에 있다.
    """
    previous = {
        "backend": 35,
        "backend-migrations": 15,
        "backend-serial-nightly": 45,
        "harness-integrity": 12,
        "infra-contracts": 10,
    }
    for job_name, old_timeout in previous.items():
        measured, _ = _MEASURED_MAX_MINUTES[job_name]
        assert (
            _headroom_shortfall(old_timeout, measured) > 0
        ), f"'{job_name}' 이전 상한 {old_timeout}분이 이미 충족이면 이 동결은 변별력이 없다."
