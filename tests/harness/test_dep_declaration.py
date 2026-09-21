"""HARN-52 — 의존 선언↔집행 게이트의 계약 동결.

이 테스트가 지키는 것은 "탐지기가 존재한다"가 아니라 **"위반 상태에서 실제로 실패 신호를
낸다"** 이다(CLAUDE.md: 변별력 없는 검증 스텝 금지 — 성공/실패 양쪽에서 같은 값을 내는
검사는 검증이 아니라 위장이다). 그래서 각 축마다 *위반을 주입한 케이스*와 *정상 케이스*를
쌍으로 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import dep_declaration as dd


@dataclass
class FakeTask:
    """탐지기가 읽는 4필드만 가진 최소 대역 — harness models.Task와 구조 호환."""

    id: str
    status: str = "todo"
    notes: str = ""
    acceptance: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


def _tasks(*tasks: FakeTask) -> dict[str, FakeTask]:
    return {t.id: t for t in tasks}


# ── ① 핵심 변별력: 선언은 있고 집행이 없으면 잡고, 집행이 있으면 안 잡는다 ──────────


def test_undeclared_dependency_is_detected() -> None:
    """notes가 '선행'으로 지목했는데 depends_on이 비면 위반 — EOS-62 실사례의 재현."""
    tasks = _tasks(
        FakeTask(id="EOS-62-review-verdict", notes="선행: EOS-54-hit-timer 착지 후 착수"),
        FakeTask(id="EOS-54-hit-timer"),
    )
    findings = dd.find_undeclared_dependencies(tasks)
    assert len(findings) == 1
    assert findings[0].task_id == "EOS-62-review-verdict"
    assert findings[0].referenced == "EOS-54"


def test_declared_dependency_is_clean() -> None:
    """같은 notes라도 depends_on에 있으면 위반이 아니다 — 이 대비가 변별력의 증거다."""
    tasks = _tasks(
        FakeTask(
            id="EOS-62-review-verdict",
            notes="선행: EOS-54-hit-timer 착지 후 착수",
            depends_on=["EOS-54-hit-timer"],
        ),
        FakeTask(id="EOS-54-hit-timer"),
    )
    assert dd.find_undeclared_dependencies(tasks) == []


# ── ② 오탐 억제: 잡지 *않아야* 하는 것들 ─────────────────────────────────────


def test_plain_mention_without_ordering_phrase_is_not_a_dependency() -> None:
    """단순 언급은 의존 선언이 아니다 — 어구 없이 ID만 있으면 통과."""
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="EOS-54-hit-timer 가 만든 계측기를 재사용한다"),
        FakeTask(id="EOS-54-hit-timer"),
    )
    assert dd.find_undeclared_dependencies(tasks) == []


def test_reference_to_done_task_is_not_a_violation() -> None:
    """참조 대상이 done이면 순서 제약이 실효 없다 — 과거형 서술까지 잡으면 소음이 된다."""
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="선행: EOS-54-hit-timer 착지 후"),
        FakeTask(id="EOS-54-hit-timer", status="done"),
    )
    assert dd.find_undeclared_dependencies(tasks) == []


def test_acceptance_prose_is_not_scanned() -> None:
    """acceptance는 사양 산문이라 오탐원 — notes만 본다(실측 근거는 모듈 docstring)."""
    tasks = _tasks(
        FakeTask(
            id="A-1-x",
            acceptance=["ⓐ진짜 선행 → 부착 / ⓑ소프트 권고(EOS-54-hit-timer 사례)"],
        ),
        FakeTask(id="EOS-54-hit-timer"),
    )
    assert dd.find_undeclared_dependencies(tasks) == []


def test_done_task_is_not_scanned() -> None:
    """완료된 태스크는 착수 대상이 아니므로 순서 강제가 무의미하다."""
    tasks = _tasks(
        FakeTask(id="A-1-x", status="done", notes="선행: EOS-54-hit-timer"),
        FakeTask(id="EOS-54-hit-timer"),
    )
    assert dd.find_undeclared_dependencies(tasks) == []


def test_unknown_reference_is_ignored() -> None:
    """저장소에 없는 ID 참조는 이 게이트의 책임 밖(오타·외부 표기)."""
    tasks = _tasks(FakeTask(id="A-1-x", notes="선행: NOPE-99-ghost 착지 후"))
    assert dd.find_undeclared_dependencies(tasks) == []


# ── ③ 그랜드파더와 만료 계약 (ARCH-25 패턴) ──────────────────────────────────


def test_exemption_suppresses_and_can_be_bypassed(monkeypatch) -> None:
    """면제는 판정에서 빼되, --all(감사 모드)에서는 그대로 보인다."""
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="선행: EOS-54-hit-timer 착지 후"),
        FakeTask(id="EOS-54-hit-timer"),
        FakeTask(id="T-1-triage"),
    )
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "EOS-54"): "T-1-triage"})
    assert dd.find_undeclared_dependencies(tasks) == []
    assert len(dd.find_undeclared_dependencies(tasks, apply_exemptions=False)) == 1


def test_exemption_is_pair_scoped_not_task_scoped(monkeypatch) -> None:
    """면제된 태스크라도 *다른* 미선언 선행이 추가되면 잡힌다 (#946 리뷰 P2).

    태스크 단위로 면제하면 그 태스크의 notes에 새 선행이 붙어도 계속 green이 나고,
    회귀가 해소 태스크 완료까지 숨는다 — 면제는 (태스크, 참조) 쌍이어야 한다.
    """
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="선행: EOS-54-hit-timer 착지 후 · 선행: NEW-02-thing 도 필요"),
        FakeTask(id="EOS-54-hit-timer"),
        FakeTask(id="NEW-02-thing"),
        FakeTask(id="T-1-triage"),
    )
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "EOS-54"): "T-1-triage"})
    findings = dd.find_undeclared_dependencies(tasks)
    assert [f.referenced for f in findings] == ["NEW-02"], "면제되지 않은 새 선행이 숨었다"


def test_expiry_fires_when_triage_task_is_done(monkeypatch) -> None:
    """해소 태스크가 done인데 면제가 남으면 만료 위반 — 만료 없는 유예 금지의 집행."""
    tasks = _tasks(FakeTask(id="A-1-x"), FakeTask(id="T-1-triage", status="done"))
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "REF-1"): "T-1-triage"})
    violations = dd.find_expiry_violations(tasks)
    assert len(violations) == 1
    assert "만료" in violations[0]


def test_expiry_silent_while_triage_open(monkeypatch) -> None:
    """해소 태스크가 살아 있으면 만료가 아니다 — 위 테스트의 대조군."""
    tasks = _tasks(FakeTask(id="A-1-x"), FakeTask(id="T-1-triage", status="todo"))
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "REF-1"): "T-1-triage"})
    assert dd.find_expiry_violations(tasks) == []


def test_expiry_catches_dangling_exemption(monkeypatch) -> None:
    """추적 불가능한 면제(대상·해소 태스크가 백로그에 없음)도 위반이다."""
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("GONE-1-x", "REF-1"): "ALSO-GONE-1-y"})
    assert len(dd.find_expiry_violations({})) == 2


def test_cancelled_reference_is_still_a_violation() -> None:
    """취소된 선행은 해소가 아니다 (#946 리뷰 P2) — selector 의미와 일치시킨다.

    `selector.unmet_dependencies`는 done이 아니면 미해소로 본다. cancelled를 해소로 치면
    그 태스크는 선언 없이 착수 가능 상태로 남는데 선행은 영원히 done이 되지 않는다.
    """
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="선행: EOS-54-hit-timer 착지 후"),
        FakeTask(id="EOS-54-hit-timer", status="cancelled"),
    )
    findings = dd.find_undeclared_dependencies(tasks)
    assert len(findings) == 1, "취소된 선행이 조용히 통과했다"
    assert findings[0].referenced == "EOS-54"


def test_expiry_fires_when_triage_task_is_cancelled(monkeypatch) -> None:
    """해소 태스크가 cancelled여도 만료 (#946 리뷰 P2).

    done만 보면 해소 태스크가 취소되는 순간 면제가 영구화되고 CI는 계속 green을 낸다 —
    취소는 done으로 갈 수 없는 종료 상태이므로 만료로 쳐야 한다.
    """
    tasks = _tasks(FakeTask(id="A-1-x"), FakeTask(id="T-1-triage", status="cancelled"))
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "REF-1"): "T-1-triage"})
    violations = dd.find_expiry_violations(tasks)
    assert len(violations) == 1
    assert "cancelled" in violations[0] and "만료" in violations[0]


# ── ④ 실제 저장소 대장이 green인가 (게이트가 오늘부터 유효한지) ────────────────


def test_repository_backlog_is_green() -> None:
    """실 대장에서 위반 0·만료 0 — 게이트가 red로 출발하면 사람이 게이트를 끈다."""
    from pathlib import Path

    import store

    root = Path(__file__).resolve().parents[2]
    backlog, _ = store.load_backlog(root)
    assert dd.find_expiry_violations(backlog.tasks) == []
    findings = dd.find_undeclared_dependencies(backlog.tasks)
    assert findings == [], "\n".join(f.render() for f in findings)


# ── ⑤ 소프트 선행 분류 (HARN-53) ──────────────────────────────────────────
#
# 소프트 분류는 만료가 없다 — "아직 안 고쳤다"(유예)가 아니라 "고칠 것이 없다"(판정)이기
# 때문이다. 만료가 없으니 **느슨해질 여지를 계약이 대신 막아야** 한다. 아래는 그 계약이
# 실패 상태에서 실제로 실패 신호를 내는지를 축별로 동결한다.

_GOOD_REASON = "방향이 반대다 — 진짜 선행은 상대 쪽에 부착했고 반대로 붙이면 순환이 된다(실측)."


def _soft_case(**over: object) -> tuple[dict[str, FakeTask], dict]:
    """소프트 분류 1건이 걸린 최소 상황 — 기본은 정상(위반 0)."""
    tasks = _tasks(FakeTask(id="A-1-x", notes="REF-1 선행"), FakeTask(id="REF-1-y"))
    table = {
        ("A-1-x", "REF-1"): dd.SoftDeclaration(
            code=str(over.get("code", "REVERSED")),
            reason=str(over.get("reason", _GOOD_REASON)),
            quotes=tuple(over.get("quotes", ("REF-1 선행",))),  # type: ignore[arg-type]
        )
    }
    return tasks, table


def test_soft_declaration_suppresses_the_finding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """정상 대조 — 분류가 있으면 위반으로 세지 않는다."""
    tasks, table = _soft_case()
    assert len(dd.find_undeclared_dependencies(tasks)) == 1  # 분류 전에는 위반
    monkeypatch.setattr(dd, "SOFT_DECLARED", table)
    assert dd.find_undeclared_dependencies(tasks) == []
    assert dd.find_soft_declaration_violations(tasks) == []


def test_soft_declaration_is_not_bypassed_by_audit_mode(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """`--all`(감사)에서도 억제된다 — 유예와 달리 '아직 안 고침'이 아니기 때문.

    감사 모드가 소프트를 위반으로 세면 분류가 무의미해지고, 대신 CLI가 소프트 목록을 따로
    출력해 보이지 않게 쌓이는 것을 막는다.
    """
    tasks, table = _soft_case()
    monkeypatch.setattr(dd, "SOFT_DECLARED", table)
    assert dd.find_undeclared_dependencies(tasks, apply_exemptions=False) == []


def test_soft_declaration_is_pair_scoped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """태스크 전체가 아니라 쌍 단위 — 같은 태스크의 *다른* 미선언 선행은 계속 잡힌다."""
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="REF-1 선행. 그리고 REF-2 선행"),
        FakeTask(id="REF-1-y"),
        FakeTask(id="REF-2-z"),
    )
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("A-1-x", "REF-1"): dd.SoftDeclaration("REVERSED", _GOOD_REASON, ("REF-1 선행",))},
    )
    findings = dd.find_undeclared_dependencies(tasks)
    assert [f.referenced for f in findings] == ["REF-2"]


def test_unknown_reason_code_is_a_violation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """자유 서술 코드 금지 — '소프트니까'로 게이트를 옵트아웃할 수 없다."""
    tasks, table = _soft_case(code="BECAUSE_I_SAID_SO")
    monkeypatch.setattr(dd, "SOFT_DECLARED", table)
    violations = dd.find_soft_declaration_violations(tasks)
    assert len(violations) == 1 and "사유 코드" in violations[0]


def test_empty_or_short_reason_is_a_violation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """코드만 찍고 근거를 비우면 위반 — 왜 하드가 아닌지가 분류의 본체다."""
    for reason in ("", "   ", "N/A", "하드 아님"):
        tasks, table = _soft_case(reason=reason)
        monkeypatch.setattr(dd, "SOFT_DECLARED", table)
        violations = dd.find_soft_declaration_violations(tasks)
        assert len(violations) == 1 and "근거" in violations[0], reason


def test_soft_plus_hard_declaration_is_a_contradiction(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """depends_on에도 있는데 소프트라 적으면 표가 거짓이다 — 하드를 붙인 뒤 분류를 안 지운 경우."""
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="REF-1 선행", depends_on=["REF-1-y"]),
        FakeTask(id="REF-1-y"),
    )
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("A-1-x", "REF-1"): dd.SoftDeclaration("REVERSED", _GOOD_REASON, ("REF-1 선행",))},
    )
    violations = dd.find_soft_declaration_violations(tasks)
    assert len(violations) == 1 and "depends_on에도" in violations[0]


def test_soft_and_legacy_exempt_together_is_a_contradiction(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """'고칠 것 없음'과 '아직 안 고침'은 동시에 참일 수 없다."""
    tasks, table = _soft_case()
    monkeypatch.setattr(dd, "SOFT_DECLARED", table)
    monkeypatch.setattr(dd, "LEGACY_EXEMPT", {("A-1-x", "REF-1"): "T-1-triage"})
    violations = dd.find_soft_declaration_violations(tasks)
    assert any("모두" in v for v in violations)


def test_dangling_soft_declaration_is_a_violation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """대상·참조가 사라지면 분류가 허구가 된다 — 유예의 ①② 축과 같은 규율."""
    tasks, _ = _soft_case()
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("GONE-1-x", "REF-1"): dd.SoftDeclaration("REVERSED", _GOOD_REASON, ("REF-1 선행",))},
    )
    assert any("백로그에 없다" in v for v in dd.find_soft_declaration_violations(tasks))
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("A-1-x", "GHOST-9"): dd.SoftDeclaration("REVERSED", _GOOD_REASON, ("REF-1 선행",))},
    )
    assert any("참조" in v for v in dd.find_soft_declaration_violations(tasks))


def test_repository_soft_declarations_are_green() -> None:
    """실 대장 — 소프트 분류 6건이 계약을 지키는가(HARN-53 착지 상태 동결)."""
    from pathlib import Path

    import store

    root = Path(__file__).resolve().parents[2]
    backlog, _ = store.load_backlog(root)
    assert dd.find_soft_declaration_violations(backlog.tasks) == []
    assert dd.LEGACY_EXEMPT == {}, "HARN-53이 유예를 비웠다 — 새 유예는 만료 계약과 함께 넣어라"
    assert len(dd.SOFT_DECLARED) == 8
    assert {v.code for v in dd.SOFT_DECLARED.values()} <= set(dd.SOFT_REASON_CODES)


# ── ⑥ 발생 위치 결속 + 차단 강제 (PR #1006 Codex P2·P1 상환) ─────────────


def test_later_appended_declaration_for_the_same_pair_is_still_caught(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """쌍 억제의 구멍 — notes는 append 전용이라 *나중에* 진짜 선행 선언이 붙을 수 있다.

    분류한 문장 옆에 붙어 **창(±60자)을 공유**해도 잡혀야 한다. 첫 수정 시도("인용구가 창에
    있으면 억제")가 정확히 이 지점에서 뚫렸다 — 그래서 어구 *위치*가 인용구 구간 안일 때만
    억제한다.
    """
    tasks = _tasks(
        FakeTask(id="A-1-x", notes="옛 문장: REF-1 선결 없음 표기"), FakeTask(id="REF-1-y")
    )
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("A-1-x", "REF-1"): dd.SoftDeclaration("MISREAD_REF", _GOOD_REASON, ("REF-1 선결",))},
    )
    assert dd.find_undeclared_dependencies(tasks) == []  # 분류된 문장만 있을 때
    tasks["A-1-x"].notes += "  [정정] REF-1 착지 후 착수한다"  # append-only로 진짜 선언 추가
    findings = dd.find_undeclared_dependencies(tasks)
    assert [f.referenced for f in findings] == ["REF-1"]
    assert findings[0].phrase == "착지 후"


def test_stale_quote_is_a_violation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """인용구가 notes에 없으면 억제도 못 하고 표만 거짓이 된다."""
    tasks, _ = _soft_case()
    monkeypatch.setattr(
        dd,
        "SOFT_DECLARED",
        {("A-1-x", "REF-1"): dd.SoftDeclaration("REVERSED", _GOOD_REASON, ("없는 문장",))},
    )
    assert any("인용구가 notes에 없다" in v for v in dd.find_soft_declaration_violations(tasks))


def test_empty_quotes_is_a_violation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """인용구 없이 쌍만 적으면 그 두 태스크 사이의 앞으로 모든 문장이 묻힌다."""
    tasks, table = _soft_case(quotes=())
    monkeypatch.setattr(dd, "SOFT_DECLARED", table)
    assert any("인용구가 없다" in v for v in dd.find_soft_declaration_violations(tasks))


def test_codes_that_cannot_be_hard_require_scheduler_exclusion(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """DISJUNCTIVE·STAGE_BLOCKED는 '하드로 못 막는다'는 뜻 — 그러면 *무언가가* 막아야 한다.

    실측 배경(PR #1006 Codex P1): EOS-50이 택일 선행 둘 다 미완인데 `todo`라서 착수 후보
    111건에 들어 있었다. 분류만 하고 막지 않으면 원래 있던 경고 하나를 없앤 것뿐이다.

    계약이 요구하는 것은 **결과**(후보에서 빠짐)이지 특정 수단이 아니다 — `blocked`도, *다른*
    참조를 하드로 부착하는 것도 유효하다(실제로 EOS-50은 병렬 세션이 EOS-49를 부착해 막았다).
    """
    for code in ("DISJUNCTIVE", "STAGE_BLOCKED"):
        tasks, table = _soft_case(code=code)
        monkeypatch.setattr(dd, "SOFT_DECLARED", table)
        assert any("제외되지 않는다" in v for v in dd.find_soft_declaration_violations(tasks)), code

        tasks["A-1-x"].status = "blocked"  # 수단 ① 차단
        assert dd.find_soft_declaration_violations(tasks) == [], f"{code}: blocked인데도 위반"

        # 수단 ② 택일의 *다른* 쪽을 하드로 부착 — EOS-50이 EOS-49를 붙여 막은 실제 형태.
        # (분류된 참조 자신을 붙이면 계약 ③ "하드로 걸어 놓고 소프트라 적는 모순"에 걸린다.)
        tasks["A-1-x"].status = "todo"
        tasks["ALT-1-z"] = FakeTask(id="ALT-1-z")
        tasks["A-1-x"].depends_on = ["ALT-1-z"]
        assert dd.find_soft_declaration_violations(tasks) == [], f"{code}: 미해소 의존인데도 위반"
        tasks["ALT-1-z"].status = "done"  # 그 의존이 해소되면 다시 노출 → 위반 복귀
        assert any(
            "제외되지 않는다" in v for v in dd.find_soft_declaration_violations(tasks)
        ), f"{code}: 의존이 done인데 제외로 봤다"
        tasks["A-1-x"].depends_on = []
        tasks.pop("ALT-1-z")


def test_codes_that_can_be_expressed_do_not_require_blocked(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """양성 대조 — REVERSED·HISTORICAL·MISREAD_REF는 막을 대상 자체가 없다(무차별 요구 금지)."""
    for code in ("REVERSED", "HISTORICAL", "MISREAD_REF"):
        tasks, table = _soft_case(code=code)
        monkeypatch.setattr(dd, "SOFT_DECLARED", table)
        assert dd.find_soft_declaration_violations(tasks) == [], code


def test_repository_exclusion_backed_codes_are_actually_excluded() -> None:
    """실 대장 — 제외가 필요한 코드의 태스크가 실제로 착수 후보에서 빠지는가(EOS-50·LIC-03)."""
    from pathlib import Path

    import store

    backlog, _ = store.load_backlog(Path(__file__).resolve().parents[2])
    needing = [
        tid
        for (tid, _ref), v in dd.SOFT_DECLARED.items()
        if v.code in dd._CODES_REQUIRING_EXCLUSION
    ]
    assert needing, "제외 필요 분류가 0건 — 이 테스트가 공허하게 통과한다"
    for tid in needing:
        assert dd._is_scheduler_excluded(backlog.tasks[tid], backlog.tasks), tid
