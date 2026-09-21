"""형제 생성기 공간 겹침 감사 계약 동결 (QUAL-08).

세 묶음이다:
  ① 현행 트렁크 계약 — 발문 겹침 0 · 미측정 0 · 잘림 0(전수 판정이 성립하는 상태)
  ② **결함 주입** — 겹치는 가짜 생성기를 넣으면 실제로 RED가 나는가(정상 입력 초록은 보호의
     증거가 아니다 — CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지")
  ③ **기각 축의 변별력 부재 동결** — QUAL-07 형태(발문 동일·단원코드 상이)를 재현해, 채택 축은
     잡고 기각 축(조건식+단원코드 AND)은 **못 잡는다**는 것을 영구 기록한다. 미래 세션이
     "조건식은 오탐이 많으니 단원코드를 AND하자"를 다시 제안할 때 이 테스트가 답이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import pytest

from whymath_backend.harness import generator_space_overlap_audit as audit


# ── 가짜 생성기 ─────────────────────────────────────────────────────────────────
@dataclass
class _FakeProblem:
    question_text: str
    unit_codes: list[str]


@dataclass
class _FakeCandidate:
    problem: _FakeProblem
    conditions: str


class _FakeGenerator:
    """주어진 (발문, 조건식, 단원코드) 목록을 한 번씩 내고 소진되는 생성기."""

    def __init__(self, rows: list[tuple[str, str, str]]) -> None:
        self._rows = list(rows)
        self._index = 0

    def generate(self, spec: object) -> _FakeCandidate | None:
        if self._index >= len(self._rows):
            return None
        question, condition, unit = self._rows[self._index]
        self._index += 1
        return _FakeCandidate(_FakeProblem(question, [unit]), condition)


class _Kinded:
    """필수 `Literal` 인자를 가진 가짜 생성기 — 모듈 수준이라야 `get_type_hints`가 해석한다."""

    def __init__(self, *, kind: Literal["a", "b"]) -> None:
        self._kind = kind
        self._done = False

    def generate(self, spec: object) -> _FakeCandidate | None:
        if self._done:
            return None
        self._done = True
        return _FakeCandidate(_FakeProblem(f"문항 {self._kind}", ["U"]), "c")


def _install(monkeypatch: pytest.MonkeyPatch, classes: list[tuple[str, str, type]]) -> None:
    monkeypatch.setattr(audit, "_generator_classes", lambda: iter(classes))


def _fixed(rows: list[tuple[str, str, str]]) -> type:
    """인자 없이 만들어지는 가짜 생성기 클래스를 만든다(감사기의 기본 생성 경로를 탄다)."""
    return type(
        "Fake", (_FakeGenerator,), {"__init__": lambda self: _FakeGenerator.__init__(self, rows)}
    )


# ── ① 현행 트렁크 계약 ──────────────────────────────────────────────────────────
def test_trunk_has_no_question_space_overlap() -> None:
    """실제 생성기 전수 — 발문 공간이 쌍마다 서로소여야 한다(게이트 본체)."""
    report = audit.audit_generator_spaces()
    assert report.question_overlaps == [], "\n".join(
        f"{p.left} × {p.right}: {p.shared}건 예 {p.samples[:1]}" for p in report.question_overlaps
    )
    assert report.ok is True


def test_trunk_measures_every_generator_class() -> None:
    """미측정 0 — '겹침 0'이 '안 봤다'가 아니려면 모집단이 전수여야 한다."""
    report = audit.audit_generator_spaces()
    assert report.unmeasured == [], f"측정 불가 클래스: {report.unmeasured}"
    assert report.truncated == [], f"풀 소진 실패: {[s.key for s in report.truncated]}"
    assert report.pairs_compared > 1500, f"비교 쌍이 비정상적으로 적다: {report.pairs_compared}"


def test_condition_axis_is_reported_but_not_a_verdict() -> None:
    """조건식 겹침은 실재하지만 게이트를 빨갛게 만들지 않는다(기각 축 — 오탐 지배)."""
    report = audit.audit_generator_spaces()
    assert report.condition_overlaps, "조건식 축이 0이면 이 축의 오탐 근거 자체가 사라진다"
    assert report.ok is True


# ── ② 결함 주입 ────────────────────────────────────────────────────────────────
def test_injected_question_overlap_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 발문을 내는 두 생성기를 넣으면 RED."""
    shared = ("문항 A", "x - 1 = 0", "UNIT-1")
    _install(
        monkeypatch,
        [
            ("mod_a", "GenA", _fixed([shared, ("문항 B", "x - 2 = 0", "UNIT-1")])),
            ("mod_b", "GenB", _fixed([shared, ("문항 C", "x - 3 = 0", "UNIT-2")])),
        ],
    )
    report = audit.audit_generator_spaces()
    assert report.ok is False
    assert len(report.question_overlaps) == 1
    assert report.question_overlaps[0].shared == 1
    assert report.question_overlaps[0].samples == ("문항 A",)


def test_disjoint_generators_stay_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """대조군 — 겹치지 않으면 초록(가드가 모든 입력에서 빨갛지는 않다)."""
    _install(
        monkeypatch,
        [
            ("mod_a", "GenA", _fixed([("문항 A", "x - 1 = 0", "UNIT-1")])),
            ("mod_b", "GenB", _fixed([("문항 B", "x - 2 = 0", "UNIT-2")])),
        ],
    )
    report = audit.audit_generator_spaces()
    assert report.ok is True
    assert report.question_overlaps == []


def test_whitespace_only_difference_still_counts_as_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정규화가 실제로 작동한다 — 공백만 다른 발문을 다른 문항으로 보면 뚫린다."""
    _install(
        monkeypatch,
        [
            ("mod_a", "GenA", _fixed([("문항  A", "c1", "U1")])),
            ("mod_b", "GenB", _fixed([(" 문항 A ", "c2", "U2")])),
        ],
    )
    assert audit.audit_generator_spaces().ok is False


def test_truncated_pool_is_reported_not_silently_trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    """소진되지 않는 생성기는 '전수'로 계상하지 않는다 — 잘린 표본의 0은 서로소가 아니다."""

    class _Endless:
        def __init__(self) -> None:
            self._n = 0

        def generate(self, spec: object) -> _FakeCandidate:
            self._n += 1
            return _FakeCandidate(_FakeProblem(f"문항 {self._n}", ["U1"]), f"c{self._n}")

    monkeypatch.setattr(audit, "_DRAIN_CAP", 50)
    _install(monkeypatch, [("mod_x", "Endless", _Endless)])
    report = audit.audit_generator_spaces()
    assert [s.key for s in report.truncated] == ["mod_x.Endless"]
    assert "풀 소진 실패(상한 50에서 잘림) **1개**" in audit.render_report(report)


def test_unbuildable_generator_is_reported_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """만들 수 없는 클래스는 조용히 건너뛰지 않고 *사유와 함께* 미측정으로 남는다."""

    class _NeedsArg:
        def __init__(self, mystery: object) -> None:  # Literal도 아니고 채움값도 없다
            self._mystery = mystery

        def generate(self, spec: object) -> None:
            return None

    _install(monkeypatch, [("mod_y", "NeedsArg", _NeedsArg)])
    report = audit.audit_generator_spaces()
    assert len(report.unmeasured) == 1
    key, reason = report.unmeasured[0]
    assert key == "mod_y.NeedsArg"
    assert "mystery" in reason


def test_generate_exception_is_reported_with_type_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성 중 예외는 타입명과 함께 남는다(침묵 실패 금지) — 통과로 위장되지 않는다."""

    class _Boom:
        def generate(self, spec: object) -> None:
            raise ValueError("터졌다")

    _install(monkeypatch, [("mod_z", "Boom", _Boom)])
    report = audit.audit_generator_spaces()
    assert report.unmeasured == [("mod_z.Boom", "생성 중 예외: ValueError: 터졌다")]


def test_literal_required_arg_is_expanded_to_every_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """`kind: Literal[...]`는 모든 값으로 인스턴스를 만든다 — 하나만 보면 나머지 공간이 사각이다."""
    _install(monkeypatch, [("mod_k", "Kinded", _Kinded)])
    report = audit.audit_generator_spaces()
    assert sorted(s.key for s in report.spaces) == [
        "mod_k.Kinded[kind='a']",
        "mod_k.Kinded[kind='b']",
    ]


# ── ③ 기각 축의 변별력 부재 동결 (QUAL-07 양성 대조군) ──────────────────────────
def _qual07_shaped(monkeypatch: pytest.MonkeyPatch) -> audit.SpaceOverlapReport:
    """QUAL-07 형태 재현 — 발문·조건식은 같고 단원코드만 다른 두 생성기."""
    _install(
        monkeypatch,
        [
            (
                "hs_mod",
                "HighschoolLike",
                _fixed(
                    [("f'(-1)의 값을 구하시오.", "Derivative(...) = y", "HS-CALC2-QUOTIENT-RULE")]
                ),
            ),
            (
                "uni_mod",
                "UniversityLike",
                _fixed([("f'(-1)의 값을 구하시오.", "Derivative(...) = y", "CALC1-QUOTIENT-RULE")]),
            ),
        ],
    )
    return audit.audit_generator_spaces()


def test_adopted_axis_catches_the_qual07_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """채택 축(발문)은 QUAL-07 형태를 잡는다 — 진양성 검출의 증거."""
    report = _qual07_shaped(monkeypatch)
    assert report.ok is False
    assert len(report.question_overlaps) == 1


def test_rejected_axis_condition_and_unit_would_have_missed_qual07(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기각 축(조건식 AND 단원코드)은 QUAL-07을 **놓친다** — 채택하면 위장이 된다.

    두 생성기의 단원코드가 다르므로 (조건식, 단원코드) 쌍은 절대 겹치지 않는다. 이 축은 현행
    트렁크에서 0쌍(오탐 0)이지만 진양성도 0이다 — 모든 입력에서 초록인 가드다.
    """
    report = _qual07_shaped(monkeypatch)
    spaces = {s.key: s for s in report.spaces}
    left, right = spaces["hs_mod.HighschoolLike"], spaces["uni_mod.UniversityLike"]
    assert left.conditions & right.conditions, "조건식 축은 겹친다(민감도는 있다)"
    # 그런데 단원코드를 AND하면 교집합이 사라진다 — 이것이 이 축을 기각한 이유다.
    assert set() == {(c, "HS-CALC2-QUOTIENT-RULE") for c in left.conditions} & {
        (c, "CALC1-QUOTIENT-RULE") for c in right.conditions
    }


# ── CLI ────────────────────────────────────────────────────────────────────────
def test_cli_exits_zero_on_clean_tree(capsys: pytest.CaptureFixture[str]) -> None:
    assert audit.main([]) == 0
    assert "✅ 발문 공간 겹침 없음" in capsys.readouterr().out


def test_cli_exits_one_on_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        [
            ("mod_a", "GenA", _fixed([("같은 발문", "c", "U1")])),
            ("mod_b", "GenB", _fixed([("같은 발문", "c", "U2")])),
        ],
    )
    assert audit.main([]) == 1


def test_cli_exits_two_on_measurement_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """측정 실패는 exit 2 — '0건 통과'로 위장되지 않는다(성공/실패가 같은 종료코드 금지)."""

    def _boom() -> None:
        raise RuntimeError("모듈 스캔 실패")

    monkeypatch.setattr(audit, "_generator_classes", _boom)
    assert audit.main([]) == 2


def test_cli_json_payload_carries_scope_and_verdict(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, [("mod_a", "GenA", _fixed([("문항", "c", "U")]))])
    out = tmp_path / "report.json"  # type: ignore[operator]
    assert audit.main(["--json", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    assert payload["ok"] is True
    assert payload["measured_configs"] == 1
    assert payload["unmeasured"] == []
