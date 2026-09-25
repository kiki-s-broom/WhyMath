"""HARN-175 — 게이트의 "여는 작업" 줄은 검증기와 같은 조건에서만 위반을 주장한다.

사고 형태(2026-09-25 실측 · 판정 기준 main f138f894): `report.gate_inputs_text`가 게이트
status를 보지 않고, 입력(depends_on·no_inputs_reason)이 없으면 무조건 "여는 작업 미선언 —
validate 위반(HARN-174)"을 냈다. 그런데 검증기(`Gate.validate`)는 **pending 게이트에만**
입력 선언을 요구한다(cleared·waived는 아무것도 막지 않으므로 과거 행에 소급하지 않는다).
그래서 닫힌 게이트 62건(cleared 56·waived 6) 전부가 `gates show`에서 거짓 위반으로 보였고,
같은 시점 `backlog.py validate`는 exit 0이었다.

이 파일이 지키는 것은 한 문장이다 — **표시가 위반을 주장한다 ⇔ 검증기가 HARN-174 오류를 낸다.**
어느 한쪽만 바뀌면(표시가 다시 status를 무시하거나, 검증기가 요구 범위를 넓히거나) RED가 된다.
위반 문구를 아예 지워서 "일치"를 만드는 위장은 pending 대조군이 막는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import report
import store
from models import GATE_STATUSES, Backlog, Gate

import backlog as cli

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 표시 쪽의 위반 주장 문구 · 검증기 쪽 HARN-174 오류의 고유 문구
_DISPLAY_VIOLATION = "validate 위반"
_VALIDATOR_ERROR = "여는 작업이 없다"

# 닫힌(종결) 상태 — 검증기가 입력 선언을 요구하지 않는 쪽
_CLOSED_STATUSES = ("cleared", "waived")

# 입력 4형태 — (depends_on, no_inputs_reason). 둘 다 있는 형태는 별개 오류(모순)라 제외한다.
# "blank"(공백뿐인 사유)는 CLI(add·amend)가 거부하지만 손편집·레거시 행으로는 들어올 수 있고,
# 검증기는 strip 후 판정해 사유 없음으로 본다 — 표시도 같은 기준이어야 한다.
_INPUT_SHAPES: dict[str, tuple[list[str], str | None]] = {
    "none": ([], None),
    "blank": ([], "   "),
    "depends": (["S1-01-fixture-opener"], None),
    "reason": ([], "사람 직접 행동 — 입력 태스크 없음"),
}


def _gate(status: str, shape: str) -> Gate:
    depends_on, reason = _INPUT_SHAPES[shape]
    return Gate(
        id=f"G-harn175-{status}-{shape}",
        title="표시·검증기 일치 픽스처",
        status=status,
        # cleared는 evidence가 필수다 — 다른 검증 오류가 섞이면 무엇을 재는지 흐려진다
        evidence="픽스처 근거 abc1234" if status == "cleared" else None,
        notes="픽스처 면제 사유" if status == "waived" else "",
        depends_on=list(depends_on),
        no_inputs_reason=reason,
    )


def _display_claims_violation(backlog: Backlog, gate: Gate) -> bool:
    return _DISPLAY_VIOLATION in report.gate_inputs_text(backlog, gate)


def _validator_flags(gate: Gate) -> bool:
    return any(_VALIDATOR_ERROR in error for error in gate.validate())


# ── ① 계약 — 모든 status × 입력 형태 ──────────────────────────────────────────


class TestDisplayMatchesValidator:
    def test_status_universe_covers_pending_and_closed(self):
        """전제 — 아래 매개변수화가 공허하지 않다(상태 목록이 비면 파라미터 0건으로 조용히 통과)."""
        assert "pending" in GATE_STATUSES
        assert set(_CLOSED_STATUSES) <= set(GATE_STATUSES)

    @pytest.mark.parametrize("status", GATE_STATUSES)
    @pytest.mark.parametrize("shape", sorted(_INPUT_SHAPES))
    def test_violation_claim_iff_validator_error(self, status: str, shape: str):
        gate = _gate(status, shape)
        claims = _display_claims_violation(Backlog(), gate)
        flags = _validator_flags(gate)
        assert claims == flags, (
            f"{gate.id}: 표시={'위반' if claims else '무위반'} · 검증기={'위반' if flags else '무위반'}"
            f" — 표시: {report.gate_inputs_text(Backlog(), gate)!r}"
        )

    def test_pending_gate_without_inputs_still_claims_violation(self):
        """대조군 — 위반 문구를 통째로 지워 '일치'를 만드는 수정은 여기서 RED가 된다."""
        gate = _gate("pending", "none")
        assert _validator_flags(gate)
        text = report.gate_inputs_text(Backlog(), gate)
        assert text == "여는 작업 미선언 — validate 위반(HARN-174)"

    @pytest.mark.parametrize("status", _CLOSED_STATUSES)
    def test_closed_gate_without_inputs_states_not_required(self, status: str):
        """닫힌 게이트는 위반이 아니라 사실(요구하지 않음)을 말한다."""
        gate = _gate(status, "none")
        assert not _validator_flags(gate)
        text = report.gate_inputs_text(Backlog(), gate)
        assert "위반" not in text
        assert "종결 게이트라 요구하지 않음" in text


# ── ② 실 대장 전수 — 오늘 존재하는 게이트 전부에서 불일치 0건 ─────────────────


class TestRealLedger:
    def test_no_gate_in_real_ledger_disagrees_with_validator(self):
        backlog, _schema_errors = store.load_backlog(_REPO_ROOT)
        gates = list(backlog.gates.values())
        # 스캔 0건은 통과가 아니라 실패다 — 경로가 틀려 아무것도 못 읽어도 불일치 0건으로 보인다
        assert gates, f"실 대장에서 게이트를 0건 읽었다: {_REPO_ROOT / 'backlog' / 'gates.yaml'}"
        disagree = [
            gate.id
            for gate in gates
            if _display_claims_violation(backlog, gate) != _validator_flags(gate)
        ]
        assert disagree == [], f"표시·검증기 불일치 {len(disagree)}/{len(gates)}건: {disagree[:10]}"


# ── ③ CLI 증상 재현 — `gates show`와 `validate`가 같은 말을 한다 ──────────────


@pytest.fixture
def repo(git_repo: Path, monkeypatch) -> Path:
    monkeypatch.chdir(git_repo)
    assert cli.main(["seed"]) == 0
    return git_repo


class TestGatesShowCli:
    @pytest.mark.parametrize("status", _CLOSED_STATUSES)
    def test_show_legacy_closed_gate_does_not_claim_violation(
        self, repo: Path, capsys, status: str
    ):
        """HARN-174 이전에 등재돼 입력 기록이 없는 닫힌 게이트 — 실 대장 62건의 형태 그대로."""
        backlog, errors = store.load_backlog(repo)
        assert errors == [], errors
        gate = _gate(status, "none")
        if status == "cleared":
            gate.cleared_by = "kiki"
        backlog.gates[gate.id] = gate
        store.save_gates(repo, sorted(backlog.gates.values(), key=lambda g: g.id))
        capsys.readouterr()

        assert cli.main(["validate"]) == 0  # 검증기: 위반 아님
        capsys.readouterr()
        assert cli.main(["gates", "show", gate.id]) == 0
        out = capsys.readouterr().out
        assert f"상태: {status}" in out  # 대상 게이트를 실제로 보였는가(공허 통과 방지)
        assert _DISPLAY_VIOLATION not in out
        assert "종결 게이트라 요구하지 않음" in out
