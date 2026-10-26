"""Solution QA C5(발문 독립 재유도 · P3-63) 통합 테스트.

단위 테스트(`test_question_rederive.py`)가 문장 틀별 계산을 보장한다면, 이 파일은 ①C5 가 판정·집계·
보고서·종료 코드에 실제로 물려 있는지 ②실 코퍼스 전수에서 가짜 FAIL 이 없고 단원마다 발문 변조가
검출되는지(스캔 0건은 실패) ③미적용이 통과로 위장하지 않고 목록으로 드러나는지를 본다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from whymath_backend.harness import solution_qa as qa
from whymath_backend.ops import phase3_metrics as pm

COVERED_Q = "함수 f(x) = x^3 - 6x^2 - 63x 의 극댓값을 구하시오."  # 정답 108
UNCOVERED_Q = "다음 중 옳은 설명을 고르시오."


def _rec(slug: str, question: str, answer: str) -> dict[str, object]:
    return {"slug": slug, "unit_codes": ["T-UNIT"], "question_text": question, "answer": answer}


# ──────────────────────────────────────────────────────────────────────────
# 집계·보고서
# ──────────────────────────────────────────────────────────────────────────
def test_check_ids_include_c5_and_every_item_carries_it() -> None:
    assert qa.CHECK_IDS[-1] == "C5" and "C5" in qa.CHECK_TITLES
    item = qa.judge_record(_rec("a", COVERED_Q, "108"))
    assert set(item.checks) == set(qa.CHECK_IDS)


def test_not_covered_does_not_block_the_verdict_but_is_counted_and_listed() -> None:
    report = qa.run_solution_qa([_rec("cov", COVERED_Q, "108"), _rec("unc", UNCOVERED_Q, "1")])
    outcomes = {i.ident: report.c5_outcome(i) for i in report.items}
    assert outcomes == {"cov": "applied", "unc": "not_covered"}
    assert [i.ident for i in report.c5_not_covered()] == ["unc"]
    # C1~C4 가 해당 없음/자료 없음이라 판정은 C5 가 없는 문항과 같은 규칙 — 미적용이 FAIL 을 만들지
    # 않는다
    assert report.items[1].checks["C5"].state is qa.CheckState.NOT_APPLICABLE
    assert report.items[1].checks["C5"].code == qa.C5_NOT_COVERED


def test_report_always_prints_the_c5_coverage_section() -> None:
    report = qa.run_solution_qa([_rec("cov", COVERED_Q, "108"), _rec("unc", UNCOVERED_Q, "1")])
    text = qa.format_report(report, scope="t", target=None)
    assert "[C5 적용 범위]" in text
    assert "적용 1/2" in text and "미적용 1" in text
    assert "T-UNIT: 적용 1/2" in text
    assert "--c5-list-out" in text  # 미적용이 있으면 전건 목록 경로를 알린다


def test_report_has_no_not_covered_footnote_when_everything_is_applied() -> None:
    report = qa.run_solution_qa([_rec("cov", COVERED_Q, "108")])
    assert "--c5-list-out" not in qa.format_report(report, scope="t", target=None)


def test_json_carries_c5_coverage_family_and_the_uncovered_list() -> None:
    report = qa.run_solution_qa([_rec("cov", COVERED_Q, "108"), _rec("unc", UNCOVERED_Q, "1")])
    data = qa.to_json(report, scope="t", target=None)
    assert data["c5_coverage"] == {"T-UNIT": {"applied": 1, "not_covered": 1}}
    assert data["c5_by_family"] == {"local_extremum_value": 1}
    assert data["c5_family_titles"] == {"local_extremum_value": "극댓값·극솟값"}
    assert data["c5_not_covered"] == [{"ident": "unc", "unit": "T-UNIT", "reason": "NO_RECOGNIZER"}]
    assert data["check_matrix"]["C5"] == {"pass": 1, "not_applicable": 1}


def test_failed_family_is_counted_by_family_not_by_message() -> None:
    report = qa.run_solution_qa([_rec("bad", COVERED_Q, "109")])
    assert report.c5_by_family() == {"local_extremum_value": 1}
    assert report.failed == 1


# ──────────────────────────────────────────────────────────────────────────
# CLI — 종료 코드와 목록 출력
# ──────────────────────────────────────────────────────────────────────────
def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    return path


def test_cli_exit_1_when_only_c5_disagrees(tmp_path: Path) -> None:
    """C1~C4 에 쓸 자료가 없어도(검증 불가) 발문 재유도가 정답과 어긋나면 실패 문항이다."""
    bank = _write(tmp_path / "b.jsonl", [_rec("bad", COVERED_Q, "109")])
    assert qa.main([str(bank)]) == qa.EXIT_FAIL


def test_cli_writes_the_full_c5_uncovered_list(tmp_path: Path) -> None:
    rows = [_rec("cov", COVERED_Q, "108")] + [_rec(f"unc{i}", UNCOVERED_Q, "1") for i in range(3)]
    bank = _write(tmp_path / "b.jsonl", rows)
    out = tmp_path / "c5.jsonl"
    qa.main([str(bank), "--c5-list-out", str(out)])
    listed = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["ident"] for r in listed] == ["unc0", "unc1", "unc2"]
    assert {r["reason"] for r in listed} == {"NO_RECOGNIZER"}


# ──────────────────────────────────────────────────────────────────────────
# 실 코퍼스(대표 과정) 전수
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def world_records() -> list[dict[str, object]]:
    world = pm.load_world()
    assert not isinstance(world, pm.WorldFailure), f"대표 과정 세계 적재 실패: {world}"
    records = [dict(r) for r in world.qa_records]
    assert records, "스캔 0건은 통과가 아니라 실패다 — 공허한 전수 가드를 막는다"
    return records


def test_real_corpus_has_no_c5_failure_and_high_coverage(
    world_records: list[dict[str, object]],
) -> None:
    checks = [(str(r.get("slug")), qa._check_c5(r)) for r in world_records]
    fails = [ident for ident, c in checks if c.state is qa.CheckState.FAIL]
    assert (
        not fails
    ), f"발문 재유도가 정답과 어긋난 문항 {fails[:5]} — 코퍼스 결함이거나 인식기 결함"
    applied = sum(1 for _, c in checks if c.state is qa.CheckState.PASS)
    # 하한은 래칫이다 — 새 생성기 틀이 인식기 없이 늘면 적용률이 내려가 이 테스트가 신호를 낸다
    assert applied / len(checks) >= 0.95, (applied, len(checks))


_COEFFICIENT = re.compile(r"(?<![\^\w.])\d+(?![\w.]*\^)")  # 지수·식별자 일부가 아닌 정수
_EXPONENT = re.compile(r"(?<=\^)\d+")
_ABS = re.compile(r"\|([^|]+)\|")


def _variants(question: str) -> list[str]:
    """발문 수식 변조 후보 — 계수 +1 · 지수 +1 · 절댓값 벗기기. 전부 원문과 달라야 한다.

    계수만 바꾸면 정답이 구조에만 달린 문항(극값 개수·미분가능 여부)은 변조해도 정답이 그대로라
    '검출 못 함'이 아니라 '바뀐 게 없음'이다. 그래서 구조 변조(지수·절댓값)를 함께 둔다.
    """
    out: list[str] = []
    for pattern in (_COEFFICIENT, _EXPONENT):
        for m in pattern.finditer(question):
            out.append(question[: m.start()] + str(int(m.group()) + 1) + question[m.end() :])
    for m in _ABS.finditer(question):
        out.append(question[: m.start()] + f"({m.group(1)})" + question[m.end() :])
    assert all(v != question for v in out), "변조가 발문을 바꾸지 못했다"
    return out


def _c5_state(rec: dict[str, object], question: str) -> qa.CheckState:
    return qa._check_c5({**rec, "question_text": question}).state


def test_real_corpus_question_tamper_is_detected_in_every_unit(
    world_records: list[dict[str, object]],
) -> None:
    """단원마다 앞 6문항의 발문 변조 중 **적어도 하나**는 FAIL 이어야 한다.

    어느 단원의 인식기가 발문을 읽지 않고 통과만 시키는 상태(관대한 가드)를 잡는다. 전부가 아니라
    '적어도 하나'인 이유: 상수항처럼 정답이 실제로 변하지 않는 변조는 PASS 가 정당하다.
    """
    by_unit: dict[str, list[dict[str, object]]] = {}
    for rec in world_records:
        by_unit.setdefault(str((rec.get("unit_codes") or ["?"])[0]), []).append(rec)
    assert len(by_unit) >= 10, "단원이 너무 적게 잡혔다 — 모집단 적재를 의심한다"
    undetected = [
        unit
        for unit, recs in by_unit.items()
        if not any(
            _c5_state(rec, variant) is qa.CheckState.FAIL
            for rec in recs[:6]
            for variant in _variants(str(rec["question_text"]))
        )
    ]
    assert not undetected, f"발문 변조가 한 번도 검출되지 않은 단원: {undetected}"


def test_real_corpus_tamper_detection_rate_floor(world_records: list[dict[str, object]]) -> None:
    """전 단원 합산: 변조 중 FAIL 비율이 바닥 아래로 내려가면 인식기가 발문을 덜 읽고 있다."""
    outcomes: Counter[str] = Counter()
    for rec in world_records[::7]:  # 균등 표본(전수는 CI 시간 낭비)
        for variant in _variants(str(rec["question_text"])):
            outcomes[_c5_state(rec, variant).value] += 1
    total = sum(outcomes.values())
    assert total > 100
    assert outcomes["fail"] / total >= 0.45, dict(outcomes)
