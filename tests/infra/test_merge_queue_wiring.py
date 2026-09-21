"""merge queue 배선 동결 — 큐가 조용히 멈추는 실패 모드를 막는다 (HARN-56).

왜 이 테스트가 있는가
--------------------
GitHub merge queue는 PR을 **main 최신 위에 얹은** 임시 브랜치
(`refs/heads/gh-readonly-queue/...`)에서 재검증하고, 그 브랜치에 대해
`merge_group` 이벤트를 낸다. 두 가지가 조용히 어긋날 수 있다:

  ⓐ **트리거 부재** — `ci.yml`에 `merge_group` 트리거가 없으면 큐 안에서 워크플로가
     아예 발화하지 않는다. required check는 "보고되지 않음" 상태로 남고, 큐는 그것을
     영원히 기다린다. **에러가 아니라 무한 대기**라서 화면이 "실패"처럼 보이지 않는다.
  ⓑ **잡 게이팅 어긋남** — 트리거가 있어도 개별 잡의 `if`가 `merge_group`을 배제하면
     그 required check만 보고되지 않아 같은 무한 대기가 된다. 이쪽이 더 고약하다 —
     대부분의 체크는 초록으로 뜨고 하나만 비어 있어서 "거의 다 됐는데"로 보인다.

두 경우 모두 **머지가 전면 정지**하며, 증상이 "실패"가 아니라 "대기"라 원인 규명이 늦다.
그래서 사람이 눈으로 확인하는 대신 기계가 대조한다.

순서 제약(중요): `merge_group` 트리거는 저장소 설정에서 큐를 켜기 **전에** main에
착지해야 한다. 반대로 하면 켠 시점부터 모든 PR이 큐에서 멈춘다.

검증 계약
--------
① `ci.yml`에 `merge_group` 트리거가 실재한다
② 문서(`branch-protection-setup.md`)가 required로 선언한 **모든** 체크가 `merge_group`
   이벤트에서 실제로 실행된다 — 잡의 `if`를 평가해 확인한다(문자열 포함 검사 아님)
③ 파서·평가기가 위장하지 않는다 — 표현식을 해석하지 못하면 "위반 0 통과"가 아니라
   **실패**한다(`test_required_checks_doc.py` 검증 계약 ③과 같은 원칙)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATH = _REPO_ROOT / ".github" / "branch-protection-setup.md"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

_BEGIN = "<!-- REQUIRED_CHECKS_BEGIN"
_END = "<!-- REQUIRED_CHECKS_END -->"

#: 큐 안에서 `changes` 잡이 내는 값. ci.yml은 event_name != 'pull_request' 이면 전 영역을
#: 'true'로 세팅하므로(경로 필터는 PR diff에서만 의미가 있다), merge_group에서는 확정값이다.
_MERGE_GROUP_OUTPUTS = "true"

#: 야간 전용 잡(required 아님) — 큐에서 돌면 안 된다. **이름으로** 고정한다: 이들의 게이팅
#: 조건 자체가 검사 대상이므로, 조건으로 대상을 고르면 조건을 바꾸는 순간 대상이 사라진다.
#: `test_required_checks_doc.py::_INTENTIONAL_EXCLUSIONS`와 같은 집합을 가리킨다.
_NIGHTLY_ONLY_JOBS = (
    "e2e-nightly — 관통 슬라이스 (실 PG·야간)",
    "backend — 전체 스위트 직렬 (교차 파일 오염 탐지·야간)",
)


def _load_ci() -> dict:
    return yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))


def _triggers(ci: dict) -> dict:
    """`on:` 블록. PyYAML은 따옴표 없는 `on`을 불리언 True로 읽으므로 둘 다 본다."""
    if True in ci:
        return ci[True]
    return ci["on"]


def _documented_checks() -> list[str]:
    """문서 마커 블록의 required 체크 이름. 마커 부재·빈 목록은 실패시킨다(계약 ③)."""
    text = _DOC_PATH.read_text(encoding="utf-8")
    start = text.find(_BEGIN)
    end = text.find(_END)
    if start == -1 or end == -1 or end <= start:
        raise AssertionError(
            f"{_DOC_PATH.name}에 REQUIRED_CHECKS 마커 블록이 없다 — "
            "파서가 빈 목록을 돌려주면 이 테스트가 위장이 된다"
        )
    names = re.findall(r"^- `([^`]+)`", text[start:end], flags=re.MULTILINE)
    if not names:
        raise AssertionError("REQUIRED_CHECKS 블록이 비었다 — 위반 0 통과로 접지 않는다")
    return names


def _evaluate_under_merge_group(expression: str) -> bool:
    """잡의 `if` 표현식을 `github.event_name == 'merge_group'` 가정 하에 평가한다.

    이 저장소가 실제로 쓰는 문법만 지원한다(비교·논리연산·괄호·문자열). 지원 밖의
    토큰이 나오면 **예외로 실패**한다 — 해석 못 한 것을 True로 접으면 이 테스트가
    "모든 입력에서 초록"인 가드가 되어, 막으려던 실패 모드를 그대로 통과시킨다.
    """
    expr = expression
    expr = expr.replace("github.event_name", "'merge_group'")
    expr = re.sub(
        r"needs\.[A-Za-z0-9_]+\.outputs\.[A-Za-z0-9_]+", f"'{_MERGE_GROUP_OUTPUTS}'", expr
    )
    expr = expr.replace("||", " or ").replace("&&", " and ")

    # 남은 토큰이 전부 알려진 것인지 확인 — 모르는 것이 있으면 평가하지 않는다.
    residue = re.sub(r"'[^']*'|==|!=|\bor\b|\band\b|[()\s]", "", expr)
    if residue:
        raise AssertionError(
            f"지원하지 않는 표현식 토큰 {residue!r} — 표현식: {expression!r}. "
            "해석 못 한 조건을 통과로 접지 않는다(계약 ③). 평가기를 확장하라."
        )
    return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 — 위에서 토큰을 전수 제한했다


class TestMergeQueueTrigger:
    def test_merge_group_trigger_exists(self) -> None:
        """★ 없으면 큐 안에서 워크플로가 발화하지 않아 모든 PR이 무한 대기한다."""
        triggers = _triggers(_load_ci())
        assert "merge_group" in triggers, (
            "ci.yml에 merge_group 트리거가 없다 — 이 상태로 저장소에서 큐를 켜면 "
            "required check가 큐 안에서 한 번도 보고되지 않아 머지가 전면 정지한다"
        )

    def test_pull_request_and_push_triggers_survive(self) -> None:
        """큐 도입이 기존 검증 경로를 대체하지 않는다 — 회귀 방지."""
        triggers = _triggers(_load_ci())
        assert "pull_request" in triggers
        assert "push" in triggers


class TestRequiredChecksReportInQueue:
    def test_every_required_check_runs_under_merge_group(self) -> None:
        """★ required 체크 중 하나라도 큐에서 안 돌면 그 하나 때문에 큐가 멈춘다.

        문자열 포함 검사가 아니라 `if` 표현식을 실제로 평가한다 — `merge_group`을
        배제하는 조건은 형태가 여러 가지라(`== 'pull_request'`, `== 'schedule'` 등)
        금지 문자열 열거로는 새로운 표기에서 뚫린다.
        """
        ci = _load_ci()
        jobs_by_name = {job.get("name", key): job for key, job in ci["jobs"].items()}

        missing: list[str] = []
        for check in _documented_checks():
            assert check in jobs_by_name, (
                f"문서가 required로 선언한 '{check}'에 대응하는 잡이 ci.yml에 없다 "
                "(test_required_checks_doc.py가 이 축을 별도로 동결한다)"
            )
            condition = jobs_by_name[check].get("if")
            if condition is None:
                continue  # 무조건 실행 — 큐에서도 돈다
            if not _evaluate_under_merge_group(str(condition)):
                missing.append(check)

        assert not missing, (
            "merge_group 이벤트에서 실행되지 않는 required 체크가 있다 — 큐가 이 체크를 "
            f"영원히 기다린다(무한 대기·에러 아님): {missing}"
        )

    def test_nightly_only_jobs_stay_out_of_the_queue(self) -> None:
        """야간 전용 잡은 큐에서 돌지 않아야 한다 — 돌면 큐 진입분마다 직렬 26분이 붙는다.

        **대상을 조건식으로 식별하지 않는다.** 초판은 `if`가 정확히
        `github.event_name == 'schedule'`인 잡만 골라 검사했는데, 그러면 바로 그 `if`를
        바꾸는 뮤테이션에서 대상 집합이 비어 **공허하게 통과**했다(2026-09-03 뮤테이션
        M3에서 실측 — 검출 실패). 식별은 변하지 않는 축(잡 이름)으로 하고, 이름이 사라지면
        스캔 0건이 아니라 실패가 되게 한다(CLAUDE.md "스캔 0건은 실패").
        """
        ci = _load_ci()
        jobs_by_name = {job.get("name", key): job for key, job in ci["jobs"].items()}

        for name in _NIGHTLY_ONLY_JOBS:
            assert name in jobs_by_name, (
                f"야간 전용 잡 '{name}'이 ci.yml에 없다 — 개명·삭제됐다면 이 목록을 함께 "
                "갱신한다. 대상이 사라진 채 통과하면 이 검사는 아무것도 지키지 않는다"
            )
            condition = jobs_by_name[name].get("if")
            assert condition is not None, f"야간 전용 잡 '{name}'에 게이팅 조건이 없다"
            assert not _evaluate_under_merge_group(str(condition)), (
                f"야간 전용 잡 '{name}'이 merge_group에서 실행된다 — 큐 진입분마다 "
                "직렬 전체 스위트가 붙어 OPS-58 병렬화가 되돌려진다"
            )


class TestEvaluatorIsDiscriminating:
    """평가기 자신이 변별력을 갖는지 — 정상 입력에서만 초록인 가드는 가드가 아니다."""

    def test_pull_request_only_condition_is_false(self) -> None:
        assert _evaluate_under_merge_group("github.event_name == 'pull_request'") is False

    def test_schedule_only_condition_is_false(self) -> None:
        assert _evaluate_under_merge_group("github.event_name == 'schedule'") is False

    def test_repository_actual_pattern_is_true(self) -> None:
        """저장소가 실제로 쓰는 게이팅 형태는 merge_group에서 참이어야 한다."""
        actual = (
            "(github.event_name != 'pull_request' || needs.changes.outputs.backend == 'true') "
            "&& github.event_name != 'schedule'"
        )
        assert _evaluate_under_merge_group(actual) is True

    def test_unknown_token_raises_instead_of_passing(self) -> None:
        """★ 해석 못 한 표현식을 True로 접으면 이 테스트 전체가 위장이 된다."""
        with pytest.raises(AssertionError, match="지원하지 않는 표현식 토큰"):
            _evaluate_under_merge_group("success() && github.event_name != 'schedule'")
