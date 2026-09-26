"""EOS-74 — 선언 정본 ↔ 검증설계서 값 일치 동결 (감사 A7).

**결함**: 선언 정본(`eos_transition_declaration_2026-08-30.md`)은 앵커 8·주 20h·
F-Ⅳ "8개 중 4개"를 말하고, 검증설계서(`eos_verification_design_v1.md`)는 앵커 6·
주 25h·F-Ⅳ "6개 중 3개"를 말했다. 검증설계서가 선언을 **"정본"으로 인용**하므로,
두 문서를 다 읽지 않는 세션은 틀린 쪽을 정본으로 쓴다.

**구조적 원인**: 검증설계서 §5는 해시로 동결돼 있었으나(`test_failure_definition_
freeze.py`) **선언을 참조하는 기계 장치는 0건**이었다 — 표류를 아무도 잡지 못했다.
CLAUDE.md 붕괴 연쇄 4단계("유지보수 지옥 ← truth source가 하나가 아님")의 실사례다.

**이 파일의 경계(acceptance ④)**: 동결 대상은 **G0 확정치의 일치**이지 F-Ⅰ~Ⅴ *문안*이
아니다. 문안 해시 동결은 `test_failure_definition_freeze.py`(검증설계서 §5) 소유이며
그 경계를 침범하지 않는다 — 여기서는 "두 문서가 같은 수를 말하는가"만 본다.

**양방향(acceptance ③)**: 어느 한쪽만 바꿔도 RED가 되어야 한다. 한쪽만 검증하면
"둘 다 틀린 값으로 사이좋게 일치"해도 통과한다 — 그래서 값 자체도 함께 고정한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
DECLARATION = _ROOT / "docs" / "strategy" / "eos_transition_declaration_2026-08-30.md"
DESIGN = _ROOT / "docs" / "standards" / "eos_verification_design_v1.md"

# G0(2026-08-30) 확정치 — 두 문서가 **함께** 이 값을 말해야 한다.
# 값 자체를 여기 박는 이유: 일치만 보면 둘 다 틀려도 통과한다(양방향 실패).
ANCHOR_COUNT = 6
WEEKLY_HOURS = 25
FIV_TOTAL, FIV_THRESHOLD = 6, 3  # F-Ⅳ: 6개 중 3개 이상 미달


@pytest.fixture(scope="module")
def declaration() -> str:
    assert DECLARATION.exists(), f"선언 정본이 없다: {DECLARATION}"
    return DECLARATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def design() -> str:
    assert DESIGN.exists(), f"검증설계서가 없다: {DESIGN}"
    return DESIGN.read_text(encoding="utf-8")


class TestAnchorCount:
    """앵커 세트 — 초판 8개에서 6개로 확정(대학 A7·A8 이월)."""

    def test_declaration_states_six(self, declaration: str):
        assert re.search(rf"확정 {ANCHOR_COUNT}개", declaration), (
            "선언 부록 B가 확정 앵커 수를 말하지 않는다 — "
            "초판 8개가 그대로면 세션이 대학 앵커를 범위로 오독한다"
        )

    def test_design_states_six(self, design: str):
        assert re.search(rf"앵커 세트 = {ANCHOR_COUNT}개", design)

    def test_declaration_marks_university_anchors_deferred(self, declaration: str):
        """A7·A8이 이월임이 표에 남아 있어야 한다 — 왜 빠졌는지가 사라지면 2027에 판단 불가."""
        for code in ("A7", "A8"):
            row = re.search(rf"^\| {code} \|.*$", declaration, re.M)
            assert row, f"부록 B에 {code} 행이 없다"
            assert "이월" in row.group(0), f"{code} 행에 이월 표시가 없다"


class TestWeeklyHours:
    """주당 가용 시간 — 초판 20h 권고에서 25h 확정."""

    def test_declaration_states_25h(self, declaration: str):
        assert re.search(rf"\*\*{WEEKLY_HOURS}h", declaration), "선언이 확정 시간을 말하지 않는다"

    def test_design_states_25h(self, design: str):
        assert re.search(rf"주당 실가용 = {WEEKLY_HOURS}h", design)

    def test_declaration_no_longer_asserts_20h_budget(self, declaration: str):
        """초판의 '예산: 총 20h 기준'이 살아 있으면 주간 계획이 통째로 틀어진다."""
        assert "예산: 총 20h(개발 16" not in declaration


class TestFailureDefinitionFour:
    """F-Ⅳ — 앵커 축소에 따른 비례 환산(50% 선 유지)."""

    def test_declaration_states_six_of_three(self, declaration: str):
        assert re.search(rf"앵커 \*\*{FIV_TOTAL}개 중 {FIV_THRESHOLD}개 이상\*\*", declaration)

    def test_design_states_six_of_three(self, design: str):
        assert re.search(rf"\*\*{FIV_TOTAL}개 중 {FIV_THRESHOLD}개 이상\*\*", design)

    def test_declaration_no_longer_states_eight_of_four(self, declaration: str):
        """초판 '8개 중 4개+'가 남아 있으면 12월 판정 임계가 두 값이 된다."""
        assert "앵커 8개 중 4개+" not in declaration

    def test_threshold_keeps_fifty_percent_line(self):
        """환산 규칙 자체를 동결 — 다음에 앵커 수가 또 바뀌어도 근거가 남는다."""
        assert FIV_THRESHOLD / FIV_TOTAL == pytest.approx(0.5), "50% 선을 벗어난 환산"


class TestCrossReferenceIntegrity:
    """검증설계서가 선언을 '정본'으로 인용하는 관계가 유지되는가."""

    def test_design_cites_declaration_as_canon(self, design: str):
        assert (
            "eos_transition_declaration_2026-08-30.md" in design
        ), "검증설계서가 선언을 인용하지 않으면 이 일치 계약의 전제가 사라진다"

    def test_declaration_points_back_to_this_freeze(self, declaration: str):
        """선언이 이 동결 장치를 가리켜야 한다 — 다음 세션이 어디서 막히는지 알 수 있게."""
        assert "test_declaration_canon_consistency" in declaration


class TestG4ConditionFreeze:
    """부록 E G4(12-13) 차단 조건 동결 — EOS-135(2026-09-24 Kiki 결정)의 회귀 방어.

    **왜 이 파일의 경계를 넓히는가**: 종전 경계는 "G0 확정치의 일치"였다. 넓히는 이유는
    *같은 문서의 같은 표류 벡터*이기 때문이다 — 선언 §0-2는 "베타 사용자 확보는 전부
    2027년 범위"라고 정해 두고서 부록 E의 G4는 12-13에 "학생 표본 >=20명"을 요구했고,
    **부록 E를 읽는 기계 장치가 0건**이라 8/30 선언 이래 3주 넘게 아무도 그 모순을 보지
    못했다. 이는 A7(앵커 8 vs 6)과 같은 형태이고, A7의 대책이 바로 이 파일이었다 —
    같은 파일이 같은 문서의 다른 표를 아직 안 보고 있었다.

    EOS-135가 그 모순을 조건 *교체*로 닫았다(삭제가 아니다 — 판정일 12-13은 유지하고
    실제 학생 표본은 12/31 이후 게이트로 이관). 그 결정이 되돌려지는 것은 **의식적
    개정**이어야지 조용한 복원이면 안 된다.

    **동결하지 않는 것**: 실패정의 F-Ⅰ~F-Ⅴ와 검증설계서 §5 해시는 여전히
    `test_failure_definition_freeze.py` 소유다. EOS-135는 그것을 건드리지 않았고,
    `test_failure_definitions_require_no_sample`이 그 사실을 단언한다 — 표본 조건이
    나중에 F로 흘러들어가면 그것은 G0 개정이라 별도 절차를 밟아야 한다.
    """

    @staticmethod
    def _g4_row(declaration: str) -> str:
        rows = [ln for ln in declaration.splitlines() if ln.startswith("| G4 계측기 완성")]
        assert len(rows) == 1, f"부록 E의 G4 행이 {len(rows)}건 — 1건이어야 한다"
        return rows[0]

    def test_g4_requires_internal_test_account_sample(self, declaration: str):
        """교체된 조건 본문. 사라지면 G4에 표본 축이 통째로 없어진다."""
        assert "내부 테스트 계정 표본 ≥20건" in self._g4_row(declaration), (
            "G4의 표본 조건이 EOS-135가 정한 형태가 아니다 — 학생 참여는 12/31 이후"
            "(G-student-work-after-internal-completion)라 12-13에는 내부 계정 표본만 성립한다"
        )

    def test_g4_marks_the_sample_as_not_real_users(self, declaration: str):
        """이 단서가 없으면 테스트 계정 표본이 실사용자 검증으로 계상된다(EOS-135 ④)."""
        assert "실사용자 아님" in self._g4_row(declaration)

    def test_g4_keeps_the_judgment_date(self, declaration: str):
        """EOS-135는 '조건을 교체하고 판정일은 유지'다 — 날짜가 밀리면 다른 결정이 된다."""
        assert self._g4_row(declaration).startswith("| G4 계측기 완성 | 12-13(일) |")

    def test_g4_keeps_its_other_two_conditions(self, declaration: str):
        """교체가 과도해 G4가 빈 게이트가 되지 않았는가(대조군)."""
        row = self._g4_row(declaration)
        assert "수동 개입 0 루프 3연속" in row, "G4의 핵심 조건이 함께 사라졌다"
        assert "P0 결함 0" in row, "G4의 P0 결함 조건이 함께 사라졌다"

    def test_real_student_sample_is_deferred_to_the_named_gate(self, declaration: str):
        """이관처가 이름으로 남아야 한다 — 없으면 '테스트 계정으로 충분하다'는 오독이 열린다."""
        assert "G-student-work-after-internal-completion" in self._g4_row(declaration)

    def test_failure_definitions_require_no_sample(self, declaration: str):
        """경계 보존 — 이 교체가 G0 동결(실패정의)을 건드리지 않았다는 근거를 코드에 남긴다."""
        f_rows = [ln for ln in declaration.splitlines() if re.match(r"- \*\*F-[ⅠⅡⅢⅣⅤ]\*\*", ln)]
        assert len(f_rows) == 5, f"실패정의가 5건이 아니다({len(f_rows)}건)"
        for ln in f_rows:
            assert "표본 ≥" not in ln and "학생 표본" not in ln, (
                "실패정의가 표본 수를 요구하게 되면 그것은 G0 개정이다 — "
                "검증설계서 §5와 해시 동결(test_failure_definition_freeze.py)을 함께 밟아야 한다"
            )

    def test_revision_history_records_the_replacement(self, declaration: str):
        """개정 이력에 없으면 이력만 읽는 사람은 마지막 변경을 2026-08-31로 안다."""
        assert "2026-09-24 G4 학생 표본 조건 교체" in declaration
        assert "EOS-135" in declaration
