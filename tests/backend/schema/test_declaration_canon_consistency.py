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


class TestG4StudentSampleExcluded:
    """G4(12-13) 학생 표본 조건 제외 — 2026-09-22 Kiki 결정(선택지 ⓐ)의 회귀 동결.

    **왜 이 파일인가(경계 확장의 근거)**: 이 파일의 종전 경계는 "G0 확정치의 일치"였다.
    여기서 넓히는 이유는 *같은 문서의 같은 표류 벡터*이기 때문이다 — 부록 E의 값이
    선언 본문(§0-2)과 어긋나 있었는데 그것을 읽는 기계 장치가 0건이라 3주 넘게
    아무도 몰랐다. A7(앵커 8 vs 6)과 글자 그대로 같은 형태이고, A7의 대책이 이
    파일이었다.

    **무엇이 모순이었나**: §0-2는 "베타 사용자 확보는 전부 2027년 범위"라고 정해
    두고서, 부록 E의 G4는 12-13에 "학생 표본 >=20명"을 차단 조건으로 요구했다.
    2026-09-22 지시가 §0-2 쪽으로 확정했고, 그 결정이 되돌려지는 것은 **의식적
    개정**이어야지 조용한 복원이면 안 된다.

    **동결하지 않는 것**: 실패정의 F-I~F-V와 검증설계서 §5 해시는 여전히
    `test_failure_definition_freeze.py` 소유다. 이 결정은 그것을 건드리지 않았고,
    아래 `test_failure_definitions_never_required_student_samples`가 그 사실
    자체를 단언한다 — 제외가 동결을 침범하지 않았다는 근거가 코드에 남아야 한다.
    """

    def test_g4_row_does_not_require_student_sample(self, declaration: str):
        """G4 차단 조건 *본문*에 학생 표본이 있으면 12월 판정이 다시 충족 불가가 된다."""
        rows = [ln for ln in declaration.splitlines() if ln.startswith("| G4 계측기 완성")]
        assert len(rows) == 1, f"부록 E의 G4 행이 {len(rows)}건 — 1건이어야 한다"
        row = rows[0]
        # 취소선 안(~~...~~)은 보존된 초판 값이므로 제거한 뒤 본문만 본다.
        body = re.sub(r"~~.*?~~", "", row)
        assert "학생 표본" not in body, (
            "G4 차단 조건 본문에 학생 표본이 되살아났다 — 파일럿은 "
            "G-pilot-defer-2027-recheck로 2027로 연기됐으므로 12-13에 충족 불가다"
        )

    def test_g4_keeps_its_other_two_conditions(self, declaration: str):
        """제외가 과도해서 G4 자체가 빈 게이트가 되지 않았는가(대조군)."""
        row = next(ln for ln in declaration.splitlines() if ln.startswith("| G4 계측기 완성"))
        assert "수동 개입 0 루프 3연속" in row, "G4의 핵심 조건이 함께 사라졌다"
        assert "P0 결함 0" in row, "G4의 P0 결함 조건이 함께 사라졌다"

    def test_exclusion_is_documented_not_silent(self, declaration: str):
        """왜 뺐는지가 문서에 없으면 2027 재개 시 판단 근거가 사라진다."""
        assert "[^g4-sample]:" in declaration, "G4 제외 각주가 없다"
        assert "2026-09-22" in declaration, "개정 이력에 결정일이 없다"

    def test_declaration_still_scopes_beta_users_to_2027(self, declaration: str):
        """이 제외의 *근거 조항*이다 — §0-2가 바뀌면 제외의 전제가 사라진다."""
        assert "베타 사용자 확보는 전부 2027년 범위다" in declaration

    def test_failure_definitions_never_required_student_samples(self, declaration: str):
        """제외가 G0 동결(실패정의)을 침범하지 않았다는 근거를 코드에 남긴다."""
        f_rows = [ln for ln in declaration.splitlines() if re.match(r"- \*\*F-[ⅠⅡⅢⅣⅤ]\*\*", ln)]
        assert len(f_rows) == 5, f"실패정의가 5건이 아니다({len(f_rows)}건)"
        for ln in f_rows:
            assert "학생 표본" not in ln, (
                "실패정의가 학생 표본을 요구한다면 이 제외는 G0 동결을 건드린 것이 되고, "
                "그때는 검증설계서 §5와 해시 동결을 함께 개정해야 한다"
            )
