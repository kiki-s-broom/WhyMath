"""`scripts/harness/ruleset_drift.py` — 라이브 브랜치 보호 드리프트 탐지기의 **변별력 동결**.

왜 이 테스트가 있는가
---------------------
`tests/infra/test_required_checks_doc.py`는 **문서 ↔ `ci.yml`**을 대조한다. 두 축 다 저장소
*안*이라, 라이브 GitHub 설정이 비어 있어도 전부 초록으로 통과한다 — 같은 계급의 사고가 3회
났다(2026-07-26 ×2 · 2026-09-03). 그 구멍을 메우는 탐지기가 `ruleset_drift`이고, 이 파일은
**그 탐지기 자신이 위장이 아님**을 동결한다.

CLAUDE.md(2026-09-01) "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지" — 정상 입력에서
초록인 것은 보호의 증거가 아니다(*모든* 입력에서 초록인 가드도 같은 화면을 낸다). 그래서 아래
테스트는 **결함을 실제로 주입해 exit 1/2가 나오는지**를 축마다 확인한다.

동결하는 계약
-------------
① 정상 → exit 0 / 결함 주입 → exit 1 (체크 누락·strict·정책 파라미터·pin·미선언)
② 측정 실패(빈 JSON·필드 부재·오류 응답·마커 부재) → **exit 2**. "위반 0 통과"가 아니다
③ 집합 대조 — 중복 등록은 *권고*지 위반이 아니다(개수 대조는 정상 상태를 위반으로 오판한다)
④ pin 3등급과 **시정 순서** — 등급ⓐ는 pin 추가가 먼저다(순서를 뒤집으면 미강제로 되돌아간다)
⑤ 유예는 만료된다 — 만료 전 exit 0(가시적 보고), 만료 후 exit 1
⑥ 실행 리듬 배선 — SessionStart 브리핑이 실제로 리마인드를 낸다(만들고 안 돌리는 상태 차단)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "harness"))

import ruleset_drift  # noqa: E402

_DOC = _REPO_ROOT / ".github" / "branch-protection-setup.md"
_TODAY = date(2026, 9, 4)
_AFTER_EXPIRY = date(2027, 1, 1)

# 2026-09-03 실측: 시정 직후 라이브에 unpinned로 남아 있던 7건. 그중 `concept-reach`만
# pin된 쌍이 없어 등급ⓐ였다 — 이 분포가 등급 분리의 존재 이유다.
_UNPINNED_WITH_TWIN = (
    "web — graphing-calculator test·build",
    "infra-contracts — 운영 자산 계약 테스트 (tests/infra)",
    "docker-build — 이미지 빌드·기동 스모크(/health/live)",
    "harness-integrity — backlog 무결성·claim 교차 검증",
    "declared-unwired-audit — 선언≠배선 4축 정적 감사 (OPS-22)",
    "corpus-authoring — 결정론 저작 도구 회귀 (생성기·배치)",
)
_GRADE_A = "concept-reach — mobile 호출 표면 회귀 가드"


def _documented() -> list[str]:
    """실제 문서가 선언한 체크 목록 — 픽스처를 문서와 같은 진실 원천에 묶는다."""
    return sorted(ruleset_drift.parse_doc(_DOC).checks)


def _load_backlog() -> Any:
    """실제 백로그를 읽어 렌더러에 넘긴다 — 렌더 경로를 진짜 데이터로 통과시킨다."""
    import store

    backlog, _ = store.load_backlog(_REPO_ROOT)
    return backlog


def _rules(
    checks: list[tuple[str, int | None]],
    *,
    strict: bool = False,
    approvals: int = 0,
    dismiss: bool = False,
    codeowner: bool = False,
    thread: bool = True,
    linear: bool = True,
    merge_queue: bool = True,
) -> list[dict[str, Any]]:
    """`gh api .../rules/branches/main` 응답 형태(규칙 배열)를 만든다.

    승인 축 기본값이 문서 선언과 다른 것(0/false/false)은 **실측 그대로**다 — 1인 개발 단계의
    의도적 유예이며 문서에 만료일과 함께 등재돼 있다.
    """
    rules: list[dict[str, Any]] = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": approvals,
                "dismiss_stale_reviews_on_push": dismiss,
                "require_code_owner_review": codeowner,
                "required_review_thread_resolution": thread,
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": strict,
                "required_status_checks": [
                    {"context": ctx, **({"integration_id": iid} if iid is not None else {})}
                    for ctx, iid in checks
                ],
            },
        },
    ]
    if linear:
        rules.append({"type": "required_linear_history"})
    if merge_queue:
        rules.append({"type": "merge_queue"})
    return rules


def _healthy_checks() -> list[tuple[str, int | None]]:
    """모든 항목이 GitHub Actions로 pin된 정상 상태."""
    return [(name, ruleset_drift.GITHUB_ACTIONS_INTEGRATION_ID) for name in _documented()]


def _run(payload: Any, tmp_path: Path, today: date = _TODAY) -> int:
    """CLI를 실제로 통과시켜 **exit code로** 판정한다(출력 문자열 눈대중 금지)."""
    target = tmp_path / "ruleset.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return ruleset_drift.main([str(target), "--today", today.isoformat()])


def _report(payload: Any, today: date = _TODAY) -> ruleset_drift.Report:
    doc = ruleset_drift.parse_doc(_DOC)
    live = ruleset_drift.parse_live(payload)
    return ruleset_drift.compare(doc, live, today)


# ---------------------------------------------------------------------------
# 계약 ① — 정상은 통과하고, 주입된 결함은 각각 잡힌다
# ---------------------------------------------------------------------------


def test_healthy_ruleset_exits_zero(tmp_path: Path) -> None:
    """기준선 — 이것이 초록이어야 아래 RED들이 의미를 갖는다."""
    assert _run(_rules(_healthy_checks()), tmp_path) == 0


def test_missing_check_is_violation(tmp_path: Path) -> None:
    """결함 주입: 체크 1건 제거 → 2026-07-26·2026-09-03 사고의 형태 그 자체."""
    checks = _healthy_checks()
    dropped = checks.pop(checks.index(("backend — lint·type·test", 15368)))
    assert _run(_rules(checks), tmp_path) == 1
    report = _report(_rules(checks))
    assert any("미강제" in v and dropped[0] in v for v in report.violations)


def test_all_documented_checks_are_individually_detectable(tmp_path: Path) -> None:
    """전수 뮤테이션 — 16건 중 *어느* 하나가 빠져도 잡힌다.

    한 건만 주입해 보면 "그 한 건에만 반응하는" 탐지기와 구별되지 않는다.
    """
    for name in _documented():
        checks = [c for c in _healthy_checks() if c[0] != name]
        assert _run(_rules(checks), tmp_path) == 1, f"{name} 제거가 탐지되지 않았다"


def test_strict_policy_true_is_violation(tmp_path: Path) -> None:
    """결함 주입: strict(=브랜치 최신화 요구)를 켠다. 체크 목록만 보면 놓치는 축.

    2026-09-14 `G-strict-policy-and-classic-cleanup` 결정으로 문서 선언이 `true`→`false`로
    바뀌었다(merge queue가 이미 최신 base 재검증을 하므로 'up to date 요구'가 구조적으로
    중복 — `.github/branch-protection-setup.md` '### strict 해제 확정' 참조). 그래서 드리프트
    방향도 반대가 됐다 — 이제는 누가 strict를 **다시 켜는 것**이 문서 선언과의 불일치다.
    """
    assert _run(_rules(_healthy_checks(), strict=True), tmp_path) == 1


def test_thread_resolution_false_is_violation(tmp_path: Path) -> None:
    """결함 주입: 유예 대상이 *아닌* 정책 파라미터 축."""
    assert _run(_rules(_healthy_checks(), thread=False), tmp_path) == 1


def test_merge_queue_off_is_violation(tmp_path: Path) -> None:
    """결함 주입: 누가 merge queue를 끈다 (HARN-98).

    2026-09-09부터 큐가 머지 경로를 지탱한다 — PR은 큐 브랜치에서 최신 main 위에 얹혀
    재검증되고, 거기서만 경로 기반 잡 스킵이 풀려 전체 스위트가 돈다. 큐가 꺼지면 그 재검증이
    통째로 사라지는데, 감시 축에 없으면 **아무 신호도 나지 않는다**. 그 상태가 정확히
    "보호가 있다고 믿는 무보호"다(CLAUDE.md 상시 실패하는 fail-open 보호).
    """
    assert _run(_rules(_healthy_checks(), merge_queue=False), tmp_path) == 1
    report = _report(_rules(_healthy_checks(), merge_queue=False))
    assert any("merge_queue" in v for v in report.violations), report.violations


def test_merge_queue_on_is_not_a_violation() -> None:
    """변별력 — 켜진 상태에서는 조용해야 한다.

    양쪽에서 같은 답을 내면 이 축은 아무것도 구별하지 않는 것이다. 위 RED와 짝이어야
    "감시한다"가 성립한다.
    """
    report = _report(_rules(_healthy_checks(), merge_queue=True))
    assert not any("merge_queue" in v for v in report.violations), report.violations


def test_undocumented_live_check_is_violation(tmp_path: Path) -> None:
    """라이브에만 있는 체크 — 문서에 없는 것이 머지를 막고 있으면 그것도 드리프트다."""
    checks = _healthy_checks() + [("어디서도 선언한 적 없는 잡", 15368)]
    assert _run(_rules(checks), tmp_path) == 1


# ---------------------------------------------------------------------------
# 계약 ② — 측정 실패는 exit 2. "위반 0 통과"로 위장되지 않는다
# ---------------------------------------------------------------------------


# 각 측정 실패는 exit 2일 뿐 아니라 **서로 다른 원인**을 남겨야 한다. 원인이 뭉개지면 8개의
# 서로 다른 실패가 같은 글자로 보이고, 고치는 사람이 어디를 볼지 알 수 없다
# (CLAUDE.md 2026-08-22 "측정·수집 도구를 성공 경로만 보고 설계 금지" ②).
_MEASUREMENT_FAILURES: list[tuple[str, Any, str]] = [
    ("오류 응답 객체", {"message": "Not Found", "status": "404"}, "객체가 왔다"),
    ("배열이 아님", "그냥 문자열", "규칙 배열이 아니다"),
    (
        "체크 목록 필드 부재",
        [{"type": "required_status_checks", "parameters": {}}],
        "체크 목록 필드가 없다",
    ),
    (
        "체크 항목 형식 이상(context 없음)",
        [
            {
                "type": "required_status_checks",
                "parameters": {"required_status_checks": [{"integration_id": 15368}]},
            }
        ],
        "형식이 예상과 다르다",
    ),
]


@pytest.mark.parametrize(("label", "payload", "reason"), _MEASUREMENT_FAILURES)
def test_measurement_failure_exits_two(
    label: str, payload: Any, reason: str, tmp_path: Path
) -> None:
    """전부 exit 2 — 판정을 못 한 것이지 통과가 아니다.

    이 축이 가장 중요하다: 빈 응답을 빈 집합으로 접으면 **미설정 상태가 정합으로 보고**된다.
    """
    assert _run(payload, tmp_path) == 2, f"{label}이 exit 2가 아니다"


@pytest.mark.parametrize(("label", "payload", "reason"), _MEASUREMENT_FAILURES)
def test_measurement_failure_reports_its_own_cause(label: str, payload: Any, reason: str) -> None:
    """실패마다 **고유한 원인 문구**를 남긴다.

    exit code만 동결하면 상류 가드를 지워도 하류 가드가 같은 2를 내며 초록이 유지된다 —
    2026-09-04 뮤테이션 M6·M7에서 실측했다. 원인 문구까지 묶어야 그 축이 실제로 지켜진다.
    """
    with pytest.raises(ruleset_drift.RulesetInputError, match=reason):
        ruleset_drift.parse_live(payload)


def test_unparsable_json_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{이건 JSON이 아니다", encoding="utf-8")
    assert ruleset_drift.main([str(target), "--today", _TODAY.isoformat()]) == 2


def test_missing_input_file_exits_two(tmp_path: Path) -> None:
    assert ruleset_drift.main([str(tmp_path / "없는파일.json")]) == 2


@pytest.mark.parametrize(
    ("label", "content"),
    [
        ("마커 통째로 없음", "- `backend — lint·type·test`\n"),
        (
            "REQUIRED_CHECKS 블록이 빔",
            "<!-- REQUIRED_CHECKS_BEGIN -->\n<!-- REQUIRED_CHECKS_END -->\n",
        ),
    ],
)
def test_doc_parser_fails_loudly(label: str, content: str, tmp_path: Path) -> None:
    """파서 무력화가 곧 통과가 되면 탐지기 전체가 위장이다(계약 ③ · OPS-04 선례)."""
    broken = tmp_path / "broken.md"
    broken.write_text(content, encoding="utf-8")
    with pytest.raises(ruleset_drift.RulesetInputError):
        ruleset_drift.parse_doc(broken)


def test_doc_without_integration_id_fails_loudly(tmp_path: Path) -> None:
    """pin 판정의 기준이 없으면 판정할 수 없다 — 조용히 'pin 검사 생략'이 되면 안 된다."""
    broken = tmp_path / "no_iid.md"
    broken.write_text(
        "<!-- REQUIRED_CHECKS_BEGIN -->\n- `x`\n<!-- REQUIRED_CHECKS_END -->\n"
        "<!-- RULESET_POLICY_BEGIN -->\n- `strict_required_status_checks_policy` = `true`\n"
        "<!-- RULESET_POLICY_END -->\n"
        "<!-- RULESET_DEVIATIONS_BEGIN -->\n<!-- RULESET_DEVIATIONS_END -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ruleset_drift.RulesetInputError, match="integration_id"):
        ruleset_drift.parse_doc(broken)


def test_cli_exits_two_when_doc_markers_missing(tmp_path: Path) -> None:
    """문서 축 실패도 CLI 층에서 exit 2로 나온다(예외 누출·exit 0 둘 다 아님)."""
    broken = tmp_path / "broken.md"
    broken.write_text("마커 없음\n", encoding="utf-8")
    target = tmp_path / "ruleset.json"
    target.write_text(json.dumps(_rules(_healthy_checks())), encoding="utf-8")
    assert ruleset_drift.main([str(target), "--doc", str(broken)]) == 2


# ---------------------------------------------------------------------------
# 계약 ③④ — 집합 대조와 pin 3등급·시정 순서
# ---------------------------------------------------------------------------


def test_duplicates_are_advisory_not_violation(tmp_path: Path) -> None:
    """중복 등록은 막는 힘을 약화시키지 않는다 — **개수가 아니라 집합**으로 대조한다.

    개수로 보면 라이브 22 vs 문서 16이라 정상 상태가 위반으로 오판된다(2026-09-03 실측).
    """
    checks = _healthy_checks() + [
        (name, ruleset_drift.GITHUB_ACTIONS_INTEGRATION_ID) for name in _UNPINNED_WITH_TWIN
    ]
    assert _run(_rules(checks), tmp_path) == 0
    report = _report(_rules(checks))
    assert len([a for a in report.advisories if "중복 등록" in a]) == len(_UNPINNED_WITH_TWIN)


def test_grade_a_unpinned_only_is_violation_with_ordering(tmp_path: Path) -> None:
    """등급ⓐ(pin 항목 0건) → 위반. 그리고 **시정 순서**가 출력에 있어야 한다.

    순진하게 'unpinned를 지운다'를 적용하면 이 항목은 하나도 남지 않아 완전 미강제로
    되돌아간다 — 방금 고친 사고의 재생산이다.
    """
    checks = [(name, None if name == _GRADE_A else 15368) for name in _documented()]
    assert _run(_rules(checks), tmp_path) == 1
    report = _report(_rules(checks))
    assert any("등급ⓐ" in v and _GRADE_A in v for v in report.violations)
    assert any(
        "추가가 먼저" in r for r in report.remediation
    ), "등급ⓐ 시정 순서(pin 추가 먼저)가 출력에 없다 — 순서를 뒤집으면 미강제가 된다"


def test_grade_b_mixed_pin_is_advisory_only(tmp_path: Path) -> None:
    """등급ⓑ(pin+unpin 혼재) → 권고. pin된 쌍이 남아 있어 막는 힘은 그대로다."""
    checks = _healthy_checks() + [(name, None) for name in _UNPINNED_WITH_TWIN]
    assert _run(_rules(checks), tmp_path) == 0
    report = _report(_rules(checks))
    assert len([a for a in report.advisories if "등급ⓑ" in a]) == len(_UNPINNED_WITH_TWIN)


def test_mispinned_to_other_app_is_violation(tmp_path: Path) -> None:
    """다른 앱으로 pin된 항목 — 우리가 기대한 보고 주체가 아니다."""
    checks = _healthy_checks()
    checks[0] = (checks[0][0], 99999)
    assert _run(_rules(checks), tmp_path) == 1


def test_as_found_2026_09_03_state_is_reported_exactly(tmp_path: Path) -> None:
    """2026-09-03 시정 직후 실측 상태 재현 — 위반은 등급ⓐ 1건, 나머지 6건은 권고.

    이 픽스처가 등급 분리의 존재 증명이다. 등급을 나누지 않으면 7건이 전부 같은 처분을 받고,
    그 처분이 '제거'면 `concept-reach`가 미강제로 되돌아간다.
    """
    checks = _healthy_checks() + [(name, None) for name in _UNPINNED_WITH_TWIN]
    checks = [c for c in checks if c != (_GRADE_A, 15368)] + [(_GRADE_A, None)]
    # strict=True를 그 시점 실측대로 고정한다 — `_rules`의 기본값은 2026-09-14 이후
    # 문서 선언(false)을 따라가므로, 이 역사적 스냅숏은 기본값 변화와 무관하게 유지해야 한다.
    payload = _rules(checks, strict=True)

    assert _run(payload, tmp_path) == 1
    report = _report(payload)
    assert [v for v in report.violations if "등급ⓐ" in v and _GRADE_A in v]
    assert not [
        v for v in report.violations if "미강제 — 문서가" in v
    ], "체크 16건은 모두 등록돼 있다"
    assert len([a for a in report.advisories if "등급ⓑ" in a]) == 6


# ---------------------------------------------------------------------------
# 계약 ⑤ — 유예는 만료된다
# ---------------------------------------------------------------------------


def test_approval_axis_is_waived_before_expiry_but_visible(tmp_path: Path) -> None:
    """승인 축(문서 1명 vs 라이브 0)은 만료 전까지 유예 — 단 **보고에는 보인다**.

    문서를 라이브에 맞춰 낮추지 않으면서(문서=의도) 1인 개발 현실을 반영하는 방법이다.
    조용히 무시하면 그것이 곧 '만료 없는 유예'다.
    """
    assert _run(_rules(_healthy_checks()), tmp_path, today=_TODAY) == 0
    report = _report(_rules(_healthy_checks()), today=_TODAY)
    assert any("required_approving_review_count" in w for w in report.waived)
    assert not any("required_approving_review_count" in v for v in report.violations)


def test_approval_axis_becomes_violation_after_expiry(tmp_path: Path) -> None:
    """만료일이 지나면 유예가 **위반으로 승격**된다 (CLAUDE.md '만료 없는 유예 금지')."""
    assert _run(_rules(_healthy_checks()), tmp_path, today=_AFTER_EXPIRY) == 1
    report = _report(_rules(_healthy_checks()), today=_AFTER_EXPIRY)
    assert any("만료" in v and "required_approving_review_count" in v for v in report.violations)


def test_every_deviation_carries_an_expiry_and_reason() -> None:
    """문서의 유예 선언 자체가 만료·사유를 갖추는지 — 무기한 유예를 구조적으로 막는다."""
    doc = ruleset_drift.parse_doc(_DOC)
    assert doc.deviations, "유예 블록 파싱 결과가 비었다 — 형식이 깨졌을 수 있다"
    for key, dev in doc.deviations.items():
        assert dev.reason.strip(), f"유예 `{key}`에 사유가 없다"
        assert isinstance(dev.until, date), f"유예 `{key}`에 만료일이 없다"


def test_satisfied_deviation_is_flagged_for_removal(tmp_path: Path) -> None:
    """유예가 필요 없어졌으면 **제거 권고**가 뜬다 — 두 번째 방어선.

    유예 선언이 그 자리에 남아 있으면, 나중에 같은 축이 다시 어긋났을 때 만료 전까지 조용히
    면제된다. 만료일만으로는 그 창을 막지 못한다.
    """
    payload = _rules(_healthy_checks(), approvals=1, dismiss=True, codeowner=True)
    assert _run(payload, tmp_path) == 0
    report = _report(payload)
    stale = [a for a in report.advisories if "유예 불필요" in a]
    assert len(stale) == 3, f"충족된 유예 3건이 제거 권고로 보고되지 않았다: {report.advisories}"


def test_deviation_only_covers_declared_keys() -> None:
    """유예가 선언되지 않은 축은 유예되지 않는다 — 포괄 면제가 없음을 동결."""
    doc = ruleset_drift.parse_doc(_DOC)
    assert "strict_required_status_checks_policy" not in doc.deviations
    assert "required_review_thread_resolution" not in doc.deviations


# ---------------------------------------------------------------------------
# 계약 ⑥ — 실행 리듬 배선 (만들었지만 아무도 안 돌리는 상태 차단)
# ---------------------------------------------------------------------------


def test_state_reminder_when_never_checked(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    message = ruleset_drift.state_reminder(tmp_path, _TODAY)
    assert message and "기록 없음" in message


def test_state_reminder_silent_when_fresh_and_clean(tmp_path: Path) -> None:
    """정상이면 조용하다 — 매 세션 소음을 내면 습관화돼 경고가 무시된다."""
    (tmp_path / ".github").mkdir()
    ruleset_drift.write_state(tmp_path, _TODAY, ruleset_drift.Report(), "fixture")
    assert ruleset_drift.state_reminder(tmp_path, _TODAY) is None


def test_state_reminder_when_stale(tmp_path: Path) -> None:
    (tmp_path / ".github").mkdir()
    ruleset_drift.write_state(tmp_path, _TODAY, ruleset_drift.Report(), "fixture")
    later = date(2026, 12, 1)
    message = ruleset_drift.state_reminder(tmp_path, later)
    assert message and "경과" in message


def test_state_reminder_when_drift_unresolved(tmp_path: Path) -> None:
    """확인은 했으나 위반이 남은 상태 — '확인한 적 없음'과 다른 문구여야 한다."""
    (tmp_path / ".github").mkdir()
    report = ruleset_drift.Report(violations=["미강제 — x"])
    ruleset_drift.write_state(tmp_path, _TODAY, report, "fixture")
    message = ruleset_drift.state_reminder(tmp_path, _TODAY)
    assert message and "드리프트 미해소" in message


def test_state_reminder_survives_corrupt_state(tmp_path: Path) -> None:
    """깨진 기록에서 예외로 터지지 않되 **조용히 통과하지도** 않는다(예외 타입명 노출)."""
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "ruleset-check-state.json").write_text("{깨짐", encoding="utf-8")
    message = ruleset_drift.state_reminder(tmp_path, _TODAY)
    assert message and "JSONDecodeError" in message


def test_render_brief_passes_reminder_through() -> None:
    """브리핑 렌더러가 리마인드를 **버리지 않는다**.

    변별력 주의: 종단 테스트에서 "브랜치 보호" 같은 흔한 어구로 단정하면 안 된다 — 그 문자열은
    HARN-63 자신의 태스크 제목으로도 브리핑에 등장해, 배선을 끊어도 초록이 나온다(2026-09-04
    뮤테이션 M5에서 실측). 그래서 여기서는 **충돌할 수 없는 표식**을 흘려보낸다.
    """
    import report as harness_report

    probe = "⟪RULESET-WIRING-PROBE⟫"
    backlog = _load_backlog()
    rendered = harness_report.render_brief(
        backlog, [], "test-branch", _TODAY, ruleset_reminder=probe
    )
    assert probe in rendered, "render_brief가 ruleset_reminder를 출력에 넣지 않는다"

    assert probe not in harness_report.render_brief(
        backlog, [], "test-branch", _TODAY
    ), "리마인드를 주지 않았는데 표식이 나왔다 — 테스트 자체가 위장이다"


def test_cmd_brief_is_wired_to_the_detector() -> None:
    """④ 집행 지점 — `cmd_brief`가 탐지기를 **실제로 호출하고 렌더러에 넘기는지** 구조 검사.

    '저장소에 존재함'과 '돌아감'은 다르다(CLAUDE.md). 문자열 검색이 아니라 **AST**로 본다 —
    금지/필수 패턴을 문자열로 세면 표기 변형에서 뚫린다(CLAUDE.md 2026-09-01 ①).
    """
    import ast

    source = (_REPO_ROOT / "scripts" / "harness" / "backlog.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_brief"
    )

    calls_detector = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "state_reminder"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ruleset_drift"
        for node in ast.walk(func)
    )
    assert calls_detector, "cmd_brief가 ruleset_drift.state_reminder를 호출하지 않는다"

    passes_through = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "render_brief"
        and any(kw.arg == "ruleset_reminder" for kw in node.keywords)
        for node in ast.walk(func)
    )
    assert passes_through, "cmd_brief가 render_brief에 ruleset_reminder를 넘기지 않는다"


def test_session_start_brief_matches_detector_output() -> None:
    """종단 — 실제 `backlog.py brief`가 탐지기가 계산한 **바로 그 문자열**을 낸다.

    기대값을 탐지기에서 직접 얻으므로 상태가 어떻든 공허해지지 않는다: 리마인드가 있어야 할
    때는 그 문장이 있는지, 없어야 할 때는 잘못 짖지 않는지를 각각 확인한다.
    """
    expected = ruleset_drift.state_reminder(_REPO_ROOT, date.today())
    out = subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "harness" / "backlog.py"), "brief"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        timeout=180,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    if expected is None:
        assert (
            "브랜치 보호 라이브 확인" not in out.stdout
        ), "확인이 최신·정합인데 브리핑이 리마인드를 냈다(오탐 — 습관화로 경고가 무시된다)"
    else:
        assert expected in out.stdout, "브리핑이 탐지기 리마인드를 내지 않는다 — 배선이 끊겼다"


# ---------------------------------------------------------------------------
# 계약 ⑦ — 미강제 상태는 **측정 실패가 아니라 판정 결과**다 (Codex P1 · 2026-09-05)
# ---------------------------------------------------------------------------

# 읽기에 성공했는데 보호가 없는 상태들. 이것을 exit 2로 올리면 write_state가 돌지 않아
# 직전의 `ok` 기록이 남고, main이 완전 무방비인 채로 브리핑이 최대 30일간 침묵한다.
_UNENFORCED_STATES: list[tuple[str, Any]] = [
    ("규칙 0건(보호 자체가 없음)", []),
    ("status_checks 규칙 부재", [{"type": "deletion"}, {"type": "non_fast_forward"}]),
    (
        "체크 목록이 빈 배열(OPS-08 실측 재현)",
        [{"type": "required_status_checks", "parameters": {"required_status_checks": []}}],
    ),
]


@pytest.mark.parametrize(("label", "payload"), _UNENFORCED_STATES)
def test_unenforced_state_is_drift_not_measurement_failure(
    label: str, payload: Any, tmp_path: Path
) -> None:
    """exit 1(드리프트)이어야 한다 — exit 2면 기록이 갱신되지 않아 침묵한다."""
    assert _run(payload, tmp_path) == 1, f"{label}이 드리프트로 판정되지 않았다"
    report = _report(payload)
    assert any(
        "강제가 통째로 꺼져" in v for v in report.violations
    ), f"{label}: 강제 꺼짐이 최우선 위반으로 보고되지 않았다"
    assert (
        report.remediation and "먼저" in report.remediation[0]
    ), "시정 순서의 첫 항목이 '규칙부터 만들기'가 아니다"


@pytest.mark.parametrize(("label", "payload"), _UNENFORCED_STATES)
def test_unenforced_state_updates_the_state_record(
    label: str, payload: Any, tmp_path: Path
) -> None:
    """드리프트가 **기록**되어야 브리핑이 짖는다 — stale `ok`가 남으면 안 된다.

    이 테스트가 Codex P1이 지적한 정확한 경로를 막는다: 기록이 갱신되지 않으면 30일 임계
    이전이라 `state_reminder`가 None을 돌려주고, 세션은 아무것도 모른 채 지나간다.
    """
    (tmp_path / ".github").mkdir()
    ruleset_drift.write_state(tmp_path, _TODAY, ruleset_drift.Report(), "직전-정상-확인")
    assert ruleset_drift.state_reminder(tmp_path, _TODAY) is None  # 사전 조건: 조용한 상태

    report = _report(payload)
    ruleset_drift.write_state(tmp_path, _TODAY, report, "이번-확인")
    message = ruleset_drift.state_reminder(tmp_path, _TODAY)
    assert message and "드리프트 미해소" in message, f"{label}: 브리핑이 여전히 조용하다"


# ---------------------------------------------------------------------------
# 계약 ⑧ — 입력 인코딩 관용 (Codex P1 · PowerShell 산출물)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "encoding"),
    [
        ("PS 5.1 `>` 산출물", "utf-16-le"),
        ("Out-File -Encoding utf8 산출물(BOM)", "utf-8-sig"),
        ("평문 UTF-8", "utf-8"),
        ("UTF-16BE", "utf-16-be"),
    ],
)
def test_input_encodings_are_tolerated(label: str, encoding: str, tmp_path: Path) -> None:
    """PowerShell이 무엇으로 쓰든 판정이 나와야 한다.

    고치기 전에는 UTF-16LE 입력이 `UnicodeDecodeError`로 **트레이스백을 내며 죽었다** —
    `except OSError`가 잡지 못하는 예외라 exit 0/1/2 어느 것도 나오지 않았다(2026-09-05 실측).
    """
    payload = _rules(_healthy_checks())
    target = tmp_path / "ruleset.json"
    text = json.dumps(payload, ensure_ascii=False)
    if encoding in ("utf-16-le", "utf-16-be"):
        bom = "\ufeff"  # BOM이 있어야 utf-16 디코더가 바이트 순서를 가린다
        target.write_bytes((bom + text).encode(encoding))
    else:
        target.write_bytes(text.encode(encoding))
    assert ruleset_drift.main([str(target), "--today", _TODAY.isoformat()]) == 0, label


def test_undecodable_input_exits_two_without_traceback(tmp_path: Path) -> None:
    """어떤 인코딩으로도 안 읽히면 **exit 2**로 정직하게 실패한다(트레이스백 금지)."""
    target = tmp_path / "ruleset.json"
    target.write_bytes(b"\xff\xfe\x00\x00\xb7\xb7\xb7\xb7")
    assert ruleset_drift.main([str(target), "--today", _TODAY.isoformat()]) == 2


# ---------------------------------------------------------------------------
# 계약 ⑨ — 측정 실패도 기록된다 (통과로 위장되지 않게)
# ---------------------------------------------------------------------------


def test_measurement_failure_is_recorded_and_surfaced(tmp_path: Path) -> None:
    """측정 실패 회차가 직전의 `ok` 기록을 그대로 두면 브리핑이 30일간 조용하다."""
    (tmp_path / ".github").mkdir()
    ruleset_drift.write_state(tmp_path, _TODAY, ruleset_drift.Report(), "직전-정상-확인")
    assert ruleset_drift.state_reminder(tmp_path, _TODAY) is None

    ruleset_drift.write_state(tmp_path, _TODAY, None, "이번-측정-실패")
    message = ruleset_drift.state_reminder(tmp_path, _TODAY)
    assert message and "측정 실패" in message
    assert "드리프트 미해소" not in message, "측정 실패와 드리프트가 같은 문구로 보이면 안 된다"


# ---------------------------------------------------------------------------
# 계약 ⑩ — Kiki 안내 명령은 Windows PowerShell에서 실제로 실행 가능해야 한다
# ---------------------------------------------------------------------------


def _powershell_incompatibilities(command: str) -> list[str]:
    """PS 5.1에서 그대로 붙여넣었을 때 깨지는 표기를 찾는다."""
    problems = []
    if "&&" in command:
        problems.append("`&&` — Windows PowerShell 5.1이 받지 않는다")
    if "python3 " in command:
        problems.append("`python3` — 이 저장소의 Windows 안내는 `python`이다")
    return problems


def test_reminder_command_runs_on_windows_powershell() -> None:
    """브리핑 리마인드의 명령이 대상 셸에서 실행 가능해야 한다.

    실행 불가능한 명령을 안내하면 이 탐지기의 **유일한 실행 경로**가 막힌다 — 만들어 두고
    아무도 못 돌리는 상태가 된다(CLAUDE.md Kiki 머신 안내 규칙 · Codex P2).
    """
    runbook = ruleset_drift.POWERSHELL_FETCH_RUNBOOK
    assert not _powershell_incompatibilities(runbook), _powershell_incompatibilities(runbook)
    assert (
        "Out-File -Encoding utf8" in runbook
    ), "PS 5.1의 `>`는 UTF-16LE로 쓴다 — 산출 인코딩을 명시해야 한다"
    assert "C:\\Users\\kiki\\Desktop\\__AI\\WhyMath" in runbook, "고정 작업 디렉터리 누락"

    # 리마인드 3종 전부가 그 명령을 그대로 실어야 한다(한 곳만 고치고 나머지가 새는 것 방지).
    assert runbook in (ruleset_drift.state_reminder(Path("/존재하지-않는-루트"), _TODAY) or "")


def test_doc_runbook_selfcheck_precedes_the_run_command() -> None:
    """판정기를 실행하는 블록 **앞에** 파일 실재 자가검증 블록이 와야 한다.

    변별력 근거(2026-09-05 실측): 미머지 상태의 main에서 이 런북을 실행하면 파이썬이
    `[Errno 2] No such file or directory`로 죽고 `$LASTEXITCODE`가 **2**가 된다 — 판정기의
    *측정 실패* exit 2와 **구별되지 않는 값**이다. 자가검증이 없으면 "파일이 없다"가 "측정에
    실패했다"로 오독되고, 사람은 `gh auth status`부터 엉뚱한 곳을 뒤진다.

    **왜 substring 검사가 아니라 순서 검사인가**: 이 문서에는 `Test-Path` 줄이 세 군데 있다
    (런북·트러블슈팅·산문). `"Test-Path ..." in text` 로 검사하면 **정작 런북의 것을 지워도
    트러블슈팅 사본이 검사를 만족시켜 초록이 유지된다** — 실제로 2026-09-05 뮤테이션 M18이
    그렇게 살아남았고, 그 시점의 이 테스트는 위장이었다. 그래서 "어딘가 있는가"가 아니라
    "실행 블록보다 **앞** 블록에 있는가"를 본다(CLAUDE.md 2026-09-01 ①: 문자열이 아니라
    구성된 결과를 보라).
    """
    blocks = re.findall(
        r"```powershell\n(.*?)```", _DOC.read_text(encoding="utf-8"), flags=re.DOTALL
    )
    assert blocks, "문서에 powershell 블록이 없다 — 실행 경로가 사라졌다"

    run_at = next(
        (n for n, b in enumerate(blocks) if "ruleset_drift.py ruleset.json --record" in b),
        None,
    )
    assert run_at is not None, "판정기를 실행하는 런북 블록이 없다"

    selfcheck_at = next(
        (n for n, b in enumerate(blocks) if "Test-Path scripts\\harness\\ruleset_drift.py" in b),
        None,
    )
    assert (
        selfcheck_at is not None
    ), "런북에 판정기 파일 존재 자가검증(Test-Path)이 없다 — exit 2 두 종류가 뒤섞인다"
    assert selfcheck_at < run_at, (
        f"자가검증 블록(#{selfcheck_at})이 실행 블록(#{run_at})보다 뒤에 있다 — "
        "실행한 다음에 확인하는 것은 자가검증이 아니다"
    )


def test_doc_documents_recovery_for_missing_detector() -> None:
    """파일이 없을 때의 복구 절차가 문서에 있어야 한다(미머지 브랜치 체크아웃)."""
    text = _DOC.read_text(encoding="utf-8")
    # **제목 자체**를 찾는다. 본문 상호참조("아래 §트러블슈팅 '판정기 파일이 없다'를 보세요")가
    # 같은 문자열을 담고 있어, 단순 substring 검사는 섹션을 통째로 지워도 통과한다 —
    # 2026-09-05 뮤테이션 M20이 그렇게 살아남았다(같은 위장이 한 파일에서 두 번 났다).
    headings = re.findall(r"^#{2,4}\s+(.+?)\s*$", text, flags=re.MULTILINE)
    assert any(
        h.startswith("판정기 파일이 없다") for h in headings
    ), f"복구 절차 섹션(제목)이 없다 — 찾은 제목들: {headings}"
    assert "git checkout -B claude/" in text, (
        "복구 절차가 fetch + checkout -B 형태가 아니다 — pull은 force-push된 브랜치에서 "
        "add/add 충돌을 낸다(CLAUDE.md)"
    )


def test_doc_runbook_block_runs_on_windows_powershell() -> None:
    """문서의 powershell 블록도 같은 계약을 지킨다(복사-실행 대상이다)."""
    text = _DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```powershell\n(.*?)```", text, flags=re.DOTALL)
    assert blocks, "문서에 powershell 블록이 없다 — 실행 경로가 사라졌다"
    for block in blocks:
        assert not _powershell_incompatibilities(block), _powershell_incompatibilities(block)
    assert any(
        "Out-File -Encoding utf8" in b for b in blocks
    ), "조회 블록이 `>`로 리다이렉트하면 UTF-16LE가 나와 판정기가 읽지 못한다"
