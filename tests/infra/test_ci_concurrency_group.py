"""야간 CI(schedule)가 push 트래픽에 취소되지 않음을 동결 — OPS-152.

왜 이 테스트가 필요한가
----------------------
`ci.yml`의 최상위 `concurrency.group`이 `ci-<워크플로>-<ref>`였을 때, schedule 실행의 ref는
`refs/heads/main`이라 **main push와 같은 그룹**이었다. `cancel-in-progress: true`와 합쳐지면 main에
push가 들어올 때마다 진행 중인 야간 안전망(E2E·직렬 전체·제약 신선도)이 취소된다 — 최근 야간 실행
#6067·#6032·#5910·#5763이 `cancelled`였다(통합 점검 계획 2026-10-18 §2-2 #11).

이 파일이 지키는 것은 문자열 모양이 아니라 **판정**이다:
  · 같은 ref에서 schedule과 push의 그룹이 *렌더링 결과로* 다른가
  · schedule 실행은 취소되지 않고, 종전 취소 동작(push·PR·merge_group)은 유지되는가

세 가지 규율 (CLAUDE.md 실패 주입 규칙)
-------------------------------------
1. **알 수 없는 식은 위반이다** — 그룹·취소 식에 이 파일이 해석하지 못하는 표현식이 있으면 "다르다"로
   접지 않고 위반으로 센다(모른다 ≠ 아니다). 해석 못 한 식이 우연히 통과를 만드는 것을 막는다.
2. **스캔 0건은 실패** — `schedule`·`push` 트리거가 없으면 비교할 대상이 없으므로 공허하게 통과시키지
   않고 위반으로 센다.
3. **주입 자체의 실재** — 모든 뮤테이션은 `mutated != original`과 치환 대상 정확히 1건을 단언하고,
   실제 `ci.yml`이 아니라 `tmp_path` 사본에서만 한다(원복이 필요 없다). 정상 입력(대조군)은 GREEN이다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# schedule 실행의 ref는 default branch다(GitHub 규약). main push와 같은 ref에서 비교해야
# "그룹을 공유해서 취소된다"는 실제 사고 조건을 그대로 재현한다.
_MAIN_REF = "refs/heads/main"
_WORKFLOW_NAME = "CI"

_EXPR_RE = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")
_CMP_RE = re.compile(r"^github\.event_name\s*(==|!=)\s*'([a-z_]+)'$")


class UnknownExpressionError(Exception):
    """이 파일이 해석하지 못하는 표현식 — 위반으로 센다(모른다 ≠ 아니다)."""


def _context(event: str) -> dict[str, str]:
    return {
        "github.workflow": _WORKFLOW_NAME,
        "github.event_name": event,
        "github.ref": _MAIN_REF,
    }


def render_group(template: str, event: str) -> str:
    """그룹 식의 `${{ … }}`를 이벤트별 값으로 치환한다. 모르는 식은 UnknownExpressionError."""
    ctx = _context(event)

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in ctx:
            raise UnknownExpressionError(f"그룹 식의 알 수 없는 표현식: {key!r}")
        return ctx[key]

    return _EXPR_RE.sub(_sub, str(template))


def eval_cancel(value: Any, event: str) -> bool:
    """`cancel-in-progress` 값을 이벤트별로 평가한다. 불리언 또는 event_name 비교만 지원한다."""
    if isinstance(value, bool):
        return value
    match = _EXPR_RE.fullmatch(str(value).strip())
    if match:
        cmp = _CMP_RE.match(match.group(1))
        if cmp:
            equal = event == cmp.group(2)
            return equal if cmp.group(1) == "==" else not equal
    raise UnknownExpressionError(f"cancel-in-progress의 알 수 없는 값: {value!r}")


def _triggers(raw: dict[str, Any]) -> dict[str, Any]:
    # PyYAML(YAML 1.1)은 키 `on`을 불리언 True로 읽는다 — 두 표기를 모두 받는다.
    node = raw.get("on", raw.get(True))
    return node if isinstance(node, dict) else {}


def find_violations(raw: dict[str, Any]) -> list[str]:
    """워크플로 사전을 검사해 위반 목록을 낸다. 빈 목록이면 통과."""
    out: list[str] = []
    triggers = _triggers(raw)
    for needed in ("schedule", "push"):
        if needed not in triggers:
            out.append(f"트리거 {needed!r} 없음 — 비교 대상이 없어 공허 통과가 된다")
    if out:
        return out

    conc = raw.get("concurrency")
    if not isinstance(conc, dict) or "group" not in conc:
        return ["최상위 concurrency.group 없음"]

    try:
        sched_group = render_group(conc["group"], "schedule")
        push_group = render_group(conc["group"], "push")
        if sched_group == push_group:
            out.append(f"같은 ref에서 schedule과 push의 그룹이 같다: {sched_group!r}")
        # 네 이벤트가 같은 ref에서 서로 겹치지 않는지(merge_group·PR 포함)도 함께 본다.
        rendered = {
            e: render_group(conc["group"], e)
            for e in ("schedule", "push", "pull_request", "merge_group")
        }
        if len(set(rendered.values())) != len(rendered):
            out.append(f"이벤트별 그룹이 서로 다르지 않다: {rendered}")

        if eval_cancel(conc.get("cancel-in-progress"), "schedule") is not False:
            out.append("schedule 실행이 취소 대상이다(cancel-in-progress가 schedule에서 참)")
        for event in ("push", "pull_request", "merge_group"):
            if eval_cancel(conc.get("cancel-in-progress"), event) is not True:
                out.append(f"{event} 실행의 종전 취소 동작이 사라졌다(비용 절감 의도 훼손)")
    except UnknownExpressionError as exc:
        out.append(str(exc))
    return out


@pytest.fixture(scope="module")
def ci_text() -> str:
    assert _CI_PATH.is_file(), f"ci.yml 없음: {_CI_PATH}"
    return _CI_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ci_raw(ci_text: str) -> dict[str, Any]:
    return yaml.safe_load(ci_text)


# ── ① 실제 저장소 ci.yml이 통과한다 ───────────────────────────────────────
class TestRealWorkflow:
    def test_real_ci_yml_has_no_violations(self, ci_raw):
        assert find_violations(ci_raw) == []

    def test_schedule_and_push_render_different_groups_on_the_same_ref(self, ci_raw):
        template = ci_raw["concurrency"]["group"]
        assert render_group(template, "schedule") != render_group(template, "push")

    def test_schedule_is_never_cancelled_and_push_is(self, ci_raw):
        value = ci_raw["concurrency"]["cancel-in-progress"]
        assert eval_cancel(value, "schedule") is False
        assert eval_cancel(value, "push") is True

    def test_both_triggers_exist_so_the_comparison_is_not_vacuous(self, ci_raw):
        assert {"schedule", "push"} <= set(_triggers(ci_raw))


# ── ② 해석기 자체의 계약 (모른다 ≠ 아니다) ────────────────────────────────
class TestInterpreter:
    def test_unknown_group_expression_is_a_violation_not_a_difference(self, ci_raw):
        raw = dict(ci_raw)
        raw["concurrency"] = {
            "group": "ci-${{ github.workflow }}-${{ github.head_ref }}",
            "cancel-in-progress": "${{ github.event_name != 'schedule' }}",
        }
        violations = find_violations(raw)
        assert violations and "알 수 없는 표현식" in violations[0]

    def test_unknown_cancel_value_is_a_violation(self, ci_raw):
        raw = dict(ci_raw)
        raw["concurrency"] = {
            "group": ci_raw["concurrency"]["group"],
            "cancel-in-progress": "${{ github.ref == 'refs/heads/main' }}",
        }
        assert any("cancel-in-progress" in v for v in find_violations(raw))

    def test_missing_schedule_trigger_is_not_a_vacuous_pass(self, ci_raw):
        raw = dict(ci_raw)
        raw["on"] = {"push": {"branches": ["main"]}}
        raw.pop(True, None)
        assert any("schedule" in v for v in find_violations(raw))

    def test_boolean_cancel_values_are_evaluated(self):
        assert eval_cancel(True, "schedule") is True
        assert eval_cancel(False, "push") is False


# ── ③ 실패 주입 — 이 상태가 되면 RED여야 한다 (정상 대조군은 ①) ────────────
_OLD_GROUP = "group: ci-${{ github.workflow }}-${{ github.ref }}"
_NEW_GROUP = "group: ci-${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}"
_NEW_CANCEL = "cancel-in-progress: ${{ github.event_name != 'schedule' }}"


def _mutate(ci_text: str, old: str, new: str) -> dict[str, Any]:
    """치환 1건을 단언하고 변이본을 파싱해 돌려준다(주입 자체의 실재)."""
    assert ci_text.count(old) == 1, f"치환 대상 {ci_text.count(old)}건 — 주입이 적용되지 않는다"
    mutated = ci_text.replace(old, new)
    assert mutated != ci_text
    return yaml.safe_load(mutated)


class TestMutations:
    def test_control_group_and_cancel_lines_exist_exactly_once(self, ci_text):
        # 아래 뮤테이션들이 "정상 줄"을 정확히 겨냥하는지 확인하는 선단언.
        assert ci_text.count(_NEW_GROUP) == 1
        assert ci_text.count(_NEW_CANCEL) == 1

    def test_reverting_group_to_the_shared_key_is_red(self, ci_text):
        """사고 상태 그대로 — schedule과 push가 같은 그룹을 쓴다."""
        raw = _mutate(ci_text, _NEW_GROUP, _OLD_GROUP)
        assert any("그룹이 같다" in v for v in find_violations(raw))

    def test_reverting_cancel_to_true_is_red(self, ci_text):
        """그룹을 나눠도 schedule끼리 겹치면 이전 야간 실행이 취소되므로 취소를 꺼야 한다."""
        raw = _mutate(ci_text, _NEW_CANCEL, "cancel-in-progress: true")
        assert any("schedule 실행이 취소 대상" in v for v in find_violations(raw))

    def test_turning_cancel_off_everywhere_is_red(self, ci_text):
        """종전 PR·push 취소를 같이 꺼 버리는 과잉 수정은 비용 회귀다."""
        raw = _mutate(ci_text, _NEW_CANCEL, "cancel-in-progress: false")
        assert any("종전 취소 동작이 사라졌다" in v for v in find_violations(raw))

    def test_inverting_the_cancel_condition_is_red(self, ci_text):
        raw = _mutate(
            ci_text, "github.event_name != 'schedule' }}", "github.event_name == 'schedule' }}"
        )
        violations = find_violations(raw)
        assert any("schedule 실행이 취소 대상" in v for v in violations) or any(
            "종전 취소 동작" in v for v in violations
        )

    def test_dropping_the_schedule_trigger_is_red(self, ci_text):
        raw = _mutate(ci_text, '  schedule:\n    - cron: "0 18 * * *"\n', "")
        assert any("schedule" in v for v in find_violations(raw))
