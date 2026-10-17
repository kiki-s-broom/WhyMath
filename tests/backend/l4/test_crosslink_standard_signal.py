"""crosswalk 독립 구조 신호 테스트 — kebab 성취기준 역유도 + 대조(순수·hermetic·DB 0).

`standard_agreement` 3판정 순수 로직 + 커밋 문항 코퍼스에서 `derive_kebab_standards`의 실측
(극값·이차 kebab → 성취기준·미등장 kebab no_signal)을 동결한다.
"""

from __future__ import annotations

from pathlib import Path

from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l4.misconception.crosslink_standard_signal import (
    derive_kebab_problem_counts,
    derive_kebab_standards,
    machine_rejectable,
    standard_agreement,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _all_problem_records() -> list[object]:
    records: list[object] = []
    for path in sorted((_REPO_ROOT / "data" / "corpus").glob("problem_bank_*/problems.jsonl")):
        records.extend(load_problem_bank_records(path))
    return records


class TestStandardAgreement:
    def test_agree_when_mid_standard_in_kebab_set(self) -> None:
        assert standard_agreement({"[12미적Ⅰ-02-07]"}, "[12미적Ⅰ-02-07]") == "agree"

    def test_disagree_when_no_overlap(self) -> None:
        assert standard_agreement({"[10공수1-02-02]"}, "[12미적Ⅰ-02-07]") == "disagree"

    def test_no_signal_when_kebab_empty(self) -> None:
        # 문항 미등장 kebab — 판정 불가(인간 폴백)·disagree로 위장 금지.
        assert standard_agreement(frozenset(), "[12미적Ⅰ-02-07]") == "no_signal"

    def test_no_signal_when_mid_standard_none(self) -> None:
        assert standard_agreement({"[10공수1-02-02]"}, None) == "no_signal"


class TestDeriveKebabStandards:
    def test_covered_kebabs_map_to_expected_standards(self) -> None:
        # 커밋 문항 코퍼스에서 역유도 — 극값 2·이차근 선택 3 kebab의 성취기준 실측 동결.
        # S3-15 재태깅(감사 확정): quad 밴드(short/mc/sqrt/sqrt_mc — opposite-root-selected·
        # factor-sign-flip의 유일한 근원)의 [10공수1-02-02](판별식으로 근을 "판별")는 오귀속 —
        # 이 밴드는 판별식 없이 인수분해·완전제곱꼴로 근을 직접 "계산"한다. 정본 statement
        # 대조로 [9수02-20]("이차방정식을 풀 수 있고, 이를 활용하여...")이 정위치
        # (`problem_corpus_batch.py::_STANDARD_CODE` 동시 교정 — 재발 방지).
        derived = derive_kebab_standards(_all_problem_records())  # type: ignore[arg-type]
        assert derived["extremum-max-min-confused"] == frozenset({"[12미적Ⅰ-02-07]"})
        # 6회차 은행 감사(2026-10-08) 처분: P3-03 미분 은행의 02-09 오개념 유발 선지(극값 자리에 극점 x좌표를
        # 넣어 실근 개수를 센 값)가 이 kebab을 쓴다 — 역유도에 [12미적Ⅰ-02-09]가 더해진다. 직접매핑 M0865의
        # 성취기준 [12미적Ⅰ-02-07]은 그대로 집합 안이라 크로스링크 대조는 여전히 agree다.
        assert derived["extremum-value-vs-point-confused"] == frozenset(
            {"[12미적Ⅰ-02-07]", "[12미적Ⅰ-02-09]"}
        )
        assert derived["opposite-root-selected"] == frozenset({"[9수02-20]"})
        assert derived["factor-sign-flip"] == frozenset({"[9수02-20]"})

    def test_uncovered_kebab_absent(self) -> None:
        # 문항에 오답 귀인으로 안 쓰이는 kebab은 유도 집합에 없음(→ no_signal·인간 전용).
        # 탐지 카탈로그 64종은 모두 커버됐으므로, 밴드 미구축 슬러그로 유도 범위 한정을 검증.
        derived = derive_kebab_standards(_all_problem_records())  # type: ignore[arg-type]
        assert "not-a-built-kebab-sentinel" not in derived
        # 탐지 카탈로그 58 완주 — 유도 집합은 태깅된 kebab만(정직한 경계).
        # 64 → 65: P3-03 미분 문항 은행(`problem_bank_p3_calculus1_diff_v0`)이 MISC-40 신설 kebab
        # `power-rule-step-omitted`를 오답 귀인으로 처음 쓰기 시작했다(문항 코퍼스에 등장).
        # 65 → 67: 02-06·02-09 생성기가 kebab 좌석이 없는 오개념을 distractor_map에 **M-id 그대로**
        # (`M0674`·`M0615`) 쓴다 — 유도기가 그 키를 kebab처럼 세어 두 항목이 늘었다. kebab 좌석이 생기면
        # (MISC-40 판정 문서 안 A·B) 생성기가 kebab 연결로 옮기며 이 두 키는 사라지고 상한도 65로 돌아간다.
        # 02-09는 5회차 은행 감사(2026-10-08)로 M0677(설명 손상 — QUAL-14)에서 M0615로 바뀌었다(개수는 같다).
        # 67 → 66: 6회차(은행 감사 2회차) 처분으로 02-09가 M0615 대신 좌석이 있는 kebab
        # `extremum-value-vs-point-confused`(이미 유도 집합에 있음)를 써서 M-id 키 하나가 사라졌다.
        assert len(derived) <= 66
        # 02-05·02-10도 같은 `power-rule-step-omitted`를 오답 귀인으로 쓴다(핵심 M0673·M0678 kebab 미승격).
        assert derived["power-rule-step-omitted"] == frozenset(
            {"[12미적Ⅰ-02-03]", "[12미적Ⅰ-02-05]", "[12미적Ⅰ-02-10]"}
        )
        assert derived["M0674"] == frozenset({"[12미적Ⅰ-02-06]"})
        # M0615(5회차 연결 · 설명 자기모순)는 6회차 처분으로 문항 귀인에서 빠졌다.
        assert "M0615" not in derived
        assert "M0677" not in derived

    def test_problem_counts_evidence(self) -> None:
        # 증거량(문항 수) — well-evidenced kebab은 하한 20 이상. root-loss는 증거 보강(24문항
        # 밴드)으로 thin(1) → well-evidenced(≥20) 승격됨(2026-07-12).
        counts = derive_kebab_problem_counts(_all_problem_records())  # type: ignore[arg-type]
        assert counts["factor-sign-flip"] >= 20
        assert counts["opposite-root-selected"] >= 20
        assert counts["root-loss-by-dividing"] >= 20  # 증거 보강 후(과거 thin 1)
        assert counts.get("not-a-built-kebab-sentinel", 0) == 0  # 미등장 kebab은 증거 없음


class TestMachineRejectable:
    _STD = frozenset({"[10공수1-02-02]"})

    def test_rejectable_cross_standard_well_evidenced(self) -> None:
        # 충분 증거 + 성취기준 disagree → 자율 거부 허용.
        assert machine_rejectable(self._STD, 130, "[12미적Ⅰ-02-07]", evidence_floor=20) is True

    def test_not_rejectable_when_agree(self) -> None:
        # 성취기준 일치는 거부 아님(승인은 인간 존치·기계는 approve 안 함).
        assert machine_rejectable(self._STD, 130, "[10공수1-02-02]", evidence_floor=20) is False

    def test_not_rejectable_when_evidence_thin(self) -> None:
        # cross-standard여도 증거 미달이면 거부 금지(얇은 역유도 신뢰 못 함).
        assert machine_rejectable(self._STD, 1, "[12미적Ⅰ-02-07]", evidence_floor=20) is False

    def test_not_rejectable_when_no_signal(self) -> None:
        # 문항 미등장 kebab(빈 성취기준)은 판정 불가 → 거부 금지(인간 폴백).
        assert machine_rejectable(frozenset(), 0, "[10공수1-02-02]", evidence_floor=20) is False
