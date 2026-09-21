"""HARN-72 — acceptance의 미래 트리거가 대장에 집행되는지 보는 검출기 동결.

**이 파일이 강제하는 것**: 검출기가 *막으려는 상태를 실제로 주입했을 때 RED*를 내는가.
정상 입력에서 초록인 것은 보호의 증거가 아니다 — 모든 입력에서 초록인 가드도 같은 화면을
낸다(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 보호 있음으로 선언 금지").

**표본은 실재 사고 2건**을 씨앗으로 쓴다(가상 문장으로 통과/실패를 만들지 않는다):
  · `ARCH-40` — "셋 다 False면 '판정 유지'로 종결하고 이 태스크를 **재생성**한다"
  · `ARCH-41` — "첫 실사용 호출자가 **생기는 시점**이 곧 … 그때 … **재측정**한다"
둘 다 Codex 리뷰가 실측으로 지적했고, 게이트 부착 전 상태가 이 검출기의 참 양성이다.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "harness"))

from trigger_declaration import (  # noqa: E402
    EXEMPTION_MARKER,
    Finding,
    find_untriggered_tracking_tasks,
)

# 실재 사고에서 가져온 문장(축약) — 가상 문장이 아니다.
# ⚠ 원문 그대로다(의역 금지) — 초판은 이 문장을 축약했다가 미래어구가 빠져 검출에 실패했고,
# 그 실패가 "실재 사고 표본을 쓴다"는 이 파일의 전제 자체를 무효로 만들 뻔했다.
_ARCH40_SENTENCE = (
    "① 트리거 실측: (a) api/coach.py·l2/* 채점→오개념→Mastery 경로에 ORM Assessment 참조가 "
    "생겼는가 (b) assessment JSONB 5필드에 *갱신* writer가 생겼는가 (c) 5필드를 값으로 읽어 "
    "판단에 쓰는 서빙 reader가 착지했는가. 셋 다 False면 '판정 유지'로 종결하고 이 태스크를 "
    "재생성한다(감시 끊김 방지)"
)
_ARCH41_SENTENCE = (
    "② 그 상태가 지속되는지 추적한다 — 필수층에 첫 실사용 호출자가 생기는 시점이 곧 "
    "중립성이 처음 시험되는 시점이므로, 그때 EOS-92 §4-1을 재측정한다"
)


def _task(tid: str, sentence: str, **over) -> dict:
    base = {
        "id": tid,
        "status": "todo",
        "acceptance": [sentence],
        "depends_on": [],
        "requires_gates": [],
        "notes": "",
    }
    base.update(over)
    return base


# ── 참 양성 — 막으려는 상태를 주입하면 RED ──────────────────────────────


@pytest.mark.parametrize(
    ("tid", "sentence"),
    [("ARCH-40-verdict-recheck", _ARCH40_SENTENCE), ("ARCH-41-tracking", _ARCH41_SENTENCE)],
)
def test_detects_real_incident_shapes(tid: str, sentence: str) -> None:
    """실재 사고 2건의 게이트 부착 *이전* 상태를 검출한다."""
    findings = find_untriggered_tracking_tasks({tid: _task(tid, sentence)})
    assert len(findings) == 1, f"{tid}: 검출 실패 — 이 형태가 이 게이트의 존재 이유다"
    assert findings[0].task_id == tid
    # 규칙 1은 원문 어구를, 규칙 2는 라벨('자기 재생성')을 future_phrase에 담는다.
    assert findings[0].future_phrase in sentence or findings[0].future_phrase == "자기 재생성"
    assert findings[0].action_phrase in sentence


# ── 참 음성 — 집행돼 있으면 통과 (게이트가 정정을 인정하는가) ──────────


def test_gate_attached_is_not_a_violation() -> None:
    """`requires_gates`가 붙으면 통과 — 실제 정정 경로가 게이트를 만족시켜야 한다."""
    t = _task("X-01-a", _ARCH41_SENTENCE, requires_gates=["G-something"])
    assert find_untriggered_tracking_tasks({"X-01-a": t}) == []


def test_depends_attached_is_not_a_violation() -> None:
    """`depends_on`도 집행 수단이다 — 둘 중 하나면 충분하다."""
    t = _task("X-02-b", _ARCH41_SENTENCE, depends_on=["Y-03-c"])
    assert find_untriggered_tracking_tasks({"X-02-b": t}) == []


# ── 오탐 방어 — 설계원칙 ①(한 문장 안 동시 등장)이 실제로 좁히는가 ────


def test_recheck_alone_is_not_a_violation() -> None:
    """'재확인' 단독은 잡지 않는다 — 이 태스크 *안의* 한 단계인 경우가 대부분이다.

    실측(2026-09-06 전수): 단독 어구로 잡으면 미완료 29건이 걸리는데 표본 검사 결과
    대부분이 오탐이었다("…가 여전히 유효함을 재확인하고 회귀 테스트로 동결한다").
    """
    t = _task(
        "X-04-d", "docs 엔드포인트의 prod 비활성화가 유효함을 재확인하고 회귀 테스트로 동결한다"
    )
    assert find_untriggered_tracking_tasks({"X-04-d": t}) == []


def test_future_condition_alone_is_not_a_violation() -> None:
    """미래조건 단독도 잡지 않는다 — 사양 산문의 조건절과 구별되지 않는다."""
    t = _task("X-05-e", "신규 호출 경로가 생기면 red를 낸다")
    assert find_untriggered_tracking_tasks({"X-05-e": t}) == []


def test_separate_sentences_are_not_a_violation() -> None:
    """두 어구가 *다른 문장*에 흩어져 있으면 대기 선언으로 보지 않는다."""
    t = _task("X-06-f", "신규 경로가 생기면 red를 낸다. 배선은 착수 시 재확인한다")
    assert find_untriggered_tracking_tasks({"X-06-f": t}) == []


# ── 면제 — 사유와 함께 태스크에 남고, 실제로 통과시키는가 ─────────────


def test_exemption_marker_suppresses_finding() -> None:
    t = _task(
        "X-07-g", _ARCH41_SENTENCE, notes=f"{EXEMPTION_MARKER} 검출기 자신이라 예시를 인용한다"
    )
    assert find_untriggered_tracking_tasks({"X-07-g": t}) == []


def test_exemption_marker_without_reason_still_needs_cli() -> None:
    """마커만 있고 사유가 비어도 모듈은 통과시킨다 — 사유 강제는 CLI(argparse) 몫이다.

    이 테스트는 *책임 경계*를 동결한다: 모듈이 사유를 검사한다고 믿고 CLI에서 빼면
    무사유 면제가 열린다. 어느 층이 무엇을 막는지 명시한다.
    """
    t = _task("X-08-h", _ARCH41_SENTENCE, notes=EXEMPTION_MARKER)
    assert find_untriggered_tracking_tasks({"X-08-h": t}) == []


# ── 스캔 범위 — 끝난·막힌 태스크는 착수 후보가 아니다 ─────────────────


@pytest.mark.parametrize("status", ["done", "cancelled", "blocked"])
def test_non_candidate_statuses_are_skipped(status: str) -> None:
    t = _task("X-09-i", _ARCH41_SENTENCE, status=status)
    assert find_untriggered_tracking_tasks({"X-09-i": t}) == []


# ── 공허한 통과 금지 (CLAUDE.md 2026-09-01 ④) ─────────────────────────


def test_empty_scan_target_raises_not_passes() -> None:
    """스캔 대상 0건은 '위반 없음'이 아니라 호출측이 깨진 것이다."""
    with pytest.raises(ValueError, match="스캔 대상"):
        find_untriggered_tracking_tasks({})


# ── 렌더 — 판정 근거(어느 어구가 걸렸는지)를 사람이 볼 수 있는가 ──────


def test_render_names_the_matched_phrases_and_excerpt() -> None:
    """어떤 어구가 왜 걸렸는지 보여야 등재자가 '이건 오탐'을 판단할 수 있다."""
    findings = find_untriggered_tracking_tasks({"X-10-j": _task("X-10-j", _ARCH41_SENTENCE)})
    text = findings[0].render()
    assert "X-10-j" in text
    assert "생기는 시점" in text and "재측정" in text
    assert "depends_on·requires_gates" in text


def test_finding_is_frozen() -> None:
    """판정 결과는 불변 — 소비측이 조용히 고쳐 통과시키지 못하게."""
    f = Finding(task_id="a", sentence="s", future_phrase="생기면", action_phrase="재측정")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.task_id = "b"  # type: ignore[misc]


# ── 규칙 2(자기 재생성) — 규칙 1이 놓치는 형태를 덮는가 ────────────────


def test_self_rearm_alone_is_detected() -> None:
    """조건 어구가 없어도 "이 태스크를 재생성한다"만으로 감시 좌석임이 확정된다.

    `ARCH-40`은 트리거를 조건절이 아니라 **진리값 목록 평가**로 적었다("셋 다 False면 …
    재생성한다"). 규칙 1(미래조건+재측정 동시 등장)은 이 형태를 놓친다 — 2026-09-06 실측
    검출률 1/2. 그 문장의 구문(`False면`)을 어구에 넣는 안은 한 건 과적합이라 버리고,
    저장소가 이미 쓰는 개념(감시 태스크의 자기 재등재)을 신호로 골랐다.
    """
    t = _task("X-11-k", "조건을 확인하고 이 태스크를 재생성한다")
    findings = find_untriggered_tracking_tasks({"X-11-k": t})
    assert len(findings) == 1
    assert findings[0].future_phrase == "자기 재생성"


def test_rule_one_alone_would_miss_arch40() -> None:
    """규칙 분담을 동결한다 — 규칙 2를 지우면 `ARCH-40` 형태가 조용히 통과한다.

    이 테스트가 없으면 나중에 "규칙 2는 표본 1이니 지우자"는 정리가 검출률을 2/2에서
    1/2로 떨어뜨리면서도 초록을 유지한다.
    """
    from trigger_declaration import _declares_future_trigger, _declares_self_rearm

    assert (
        _declares_future_trigger([_ARCH40_SENTENCE]) is None
    ), "규칙 1이 ARCH-40을 잡는다면 규칙 2의 존재 이유가 바뀐 것이다 — 주석을 갱신하라"
    assert _declares_self_rearm([_ARCH40_SENTENCE]) is not None


def test_both_known_incidents_are_covered() -> None:
    """두 실재 사고가 (규칙 1 또는 2로) 전건 검출된다 — 이 게이트의 최소 보증."""
    tasks = {
        "ARCH-40-verdict-recheck": _task("ARCH-40-verdict-recheck", _ARCH40_SENTENCE),
        "ARCH-41-tracking": _task("ARCH-41-tracking", _ARCH41_SENTENCE),
    }
    assert len(find_untriggered_tracking_tasks(tasks)) == 2
