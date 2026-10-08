"""P3-03 미분 은행 감사자 자격 측정 CLI 회귀 테스트(hermetic·LLM 호출 0).

판정 규칙의 경계를 합성 라벨로 못 박는다 — Kiki 결정(2026-10-08)의 합격 기준:
  전체 검출률 Wilson 95% 단측 하한 ≥ 0.90 (120건 중 114 통과 · 113 불합격),
  결함 종류별 검출률 점추정 ≥ 0.80 (15건 종류에서 12 통과 · 11 불합격),
  정상 오경보율 Wilson 95% 단측 상한 ≤ 0.10 (120건 중 6 통과 · 7 불합격),
  프로토콜 = 기계 ∪ LLM 판정자 합집합(한 명이라도 결함이면 결함),
  S5 보정 상한 = Wilson 상한(k, 504) ÷ 검출률 하한 ≤ 0.02.
입력 오류(누락·중복·미지 id·판정자 부족·정답지 바꿔치기)는 exit 2 — 통과로 위장하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import p3_audit_qualification as qual
from whymath_backend.harness.wilson import wilson_lower_bound, wilson_upper_bound
from whymath_backend.l3.equivalent.p3_diff_defect_seeder import BANK_DEFECT_CLASSES

_ROOT = Path(__file__).resolve().parents[3]
_QUAL = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "qualification"
#: 시험지·1회차 감사 묶음을 만든 은행 v0의 동결 사본 — 현 은행은 생성기 교정으로 바뀔 수 있다.
_BANK = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit" / "audited_bank.jsonl"

#: 합성 정답지의 종류별 결함 수 — 15건 종류를 두어 0.80 경계(12/15)를 정확히 밟는다.
_SIZES = dict(zip(BANK_DEFECT_CLASSES, (15, 15, 15, 15, 15, 15, 30), strict=True))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return path


@pytest.fixture()
def key_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = 0
    for cls, size in _SIZES.items():
        for _ in range(size):
            index += 1
            rows.append(
                {
                    "item_id": f"q{index:03d}",
                    "is_defective": True,
                    "defect_class": cls,
                    "variant": "v",
                    "gt_basis": "construction",
                    "gate_overlap": None,
                    "source_problem_id": f"p{index}",
                    "mutation_note": "",
                }
            )
    for _ in range(120):
        index += 1
        rows.append(
            {
                "item_id": f"q{index:03d}",
                "is_defective": False,
                "defect_class": None,
                "variant": None,
                "gt_basis": None,
                "gate_overlap": None,
                "source_problem_id": f"p{index}",
                "mutation_note": "",
            }
        )
    return rows


@pytest.fixture()
def files(tmp_path: Path, key_rows: list[dict[str, Any]]) -> dict[str, Path]:
    blind = _write_jsonl(tmp_path / "blind.jsonl", ({"item_id": r["item_id"]} for r in key_rows))
    key = _write_jsonl(tmp_path / "key.jsonl", key_rows)
    sha = tmp_path / "key.sha256"
    sha.write_text(hashlib.sha256(key.read_bytes()).hexdigest() + "  key.jsonl\n", "utf-8")
    return {"blind": blind, "key": key, "sha": sha, "dir": tmp_path}


def _labels(
    path: Path, rows: list[dict[str, Any]], flagged: Callable[[dict[str, Any]], bool]
) -> Path:
    return _write_jsonl(
        path,
        (
            {
                "item_id": r["item_id"],
                "verdict": "defect" if flagged(r) else "ok",
                "defect_class": "",
            }
            for r in rows
        ),
    )


def _defects(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r["is_defective"]]


def _clean(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if not r["is_defective"]]


def _score(files: dict[str, Path], machine: Path, llm: list[Path], *extra: str) -> int:
    argv = [
        "score",
        "--blind",
        str(files["blind"]),
        "--answer-key",
        str(files["key"]),
        "--answer-key-sha256",
        str(files["sha"]),
        "--machine",
        str(machine),
    ]
    for path in llm:
        argv += ["--llm", str(path)]
    return qual.main([*argv, *extra])


def _pick(
    rows: list[dict[str, Any]], missed: set[str], false_alarms: set[str]
) -> Callable[[dict[str, Any]], bool]:
    """결함은 missed를 빼고 전부 잡고, 정상은 false_alarms만 결함으로 본다."""

    def flag(row: dict[str, Any]) -> bool:
        if row["is_defective"]:
            return row["item_id"] not in missed
        return row["item_id"] in false_alarms

    return flag


def _run(
    files: dict[str, Path],
    rows: list[dict[str, Any]],
    *,
    missed: set[str],
    false_alarms: set[str],
    extra: tuple[str, ...] = (),
) -> int:
    """LLM 판정자 A가 전부를 내고, 기계·판정자 B는 아무것도 잡지 않는다(합집합 = A)."""
    nothing = _labels(files["dir"] / "machine.jsonl", rows, lambda r: False)
    judge_a = _labels(files["dir"] / "a.jsonl", rows, _pick(rows, missed, false_alarms))
    judge_b = _labels(files["dir"] / "b.jsonl", rows, lambda r: False)
    return _score(files, nothing, [judge_a, judge_b], *extra)


# ── 기준 상수(Kiki 결정 2026-10-08) ─────────────────────────────────────
def test_criteria_constants_are_the_decided_values() -> None:
    assert qual.criteria() == {
        "n_defective": 120,
        "n_clean": 120,
        "min_defects_per_class": 15,
        "confidence": 0.95,
        "min_detection_lower": 0.90,
        "min_class_detection_point": 0.80,
        "max_false_alarm_upper": 0.10,
        "min_llm_judges": 2,
        "s5_bank_size": 504,
        "s5_max_corrected_upper": 0.02,
    }


# ── 합격 경계 ────────────────────────────────────────────────────────────
def test_detection_lower_bound_boundary(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    defects = _defects(key_rows)
    assert wilson_lower_bound(114, 120) >= 0.90 > wilson_lower_bound(113, 120)
    # 놓친 결함을 종류마다 1건씩 흩뜨려 종류별 기준(≥ 0.80)은 지킨다.
    per_class = {cls: [r for r in defects if r["defect_class"] == cls] for cls in _SIZES}
    six = {per_class[cls][0]["item_id"] for cls in list(_SIZES)[:6]}
    seven = six | {per_class[list(_SIZES)[6]][0]["item_id"]}
    assert _run(files, key_rows, missed=six, false_alarms=set()) == 0
    assert _run(files, key_rows, missed=seven, false_alarms=set()) == 1


def test_false_alarm_upper_bound_boundary(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    clean_ids = [r["item_id"] for r in _clean(key_rows)]
    assert wilson_upper_bound(6, 120) <= 0.10 < wilson_upper_bound(7, 120)
    assert _run(files, key_rows, missed=set(), false_alarms=set(clean_ids[:6])) == 0
    assert _run(files, key_rows, missed=set(), false_alarms=set(clean_ids[:7])) == 1


def test_per_class_point_boundary(files: dict[str, Path], key_rows: list[dict[str, Any]]) -> None:
    first = BANK_DEFECT_CLASSES[0]
    members = [r["item_id"] for r in _defects(key_rows) if r["defect_class"] == first]
    assert len(members) == 15
    # 12/15 = 0.80은 통과(≥), 11/15는 불합격 — 전체 하한(117·116/120)은 둘 다 기준 위다.
    assert _run(files, key_rows, missed=set(members[:3]), false_alarms=set()) == 0
    assert wilson_lower_bound(116, 120) >= 0.90
    assert _run(files, key_rows, missed=set(members[:4]), false_alarms=set()) == 1


def test_protocol_is_the_union_of_machine_and_judges(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    """기계·판정자 A·판정자 B가 서로 다른 종류만 잡으면 각자는 불합격, 합집합은 합격."""
    classes = list(_SIZES)

    def only(group: set[str]) -> Callable[[dict[str, Any]], bool]:
        return lambda r: bool(r["is_defective"] and r["defect_class"] in group)

    machine = _labels(files["dir"] / "m.jsonl", key_rows, only(set(classes[:2])))
    judge_a = _labels(files["dir"] / "a.jsonl", key_rows, only(set(classes[2:5])))
    judge_b = _labels(files["dir"] / "b.jsonl", key_rows, only(set(classes[5:])))
    out = files["dir"] / "score.json"
    assert _score(files, machine, [judge_a, judge_b], "--json-out", str(out)) == 0
    components = json.loads(out.read_text("utf-8"))["components"]
    assert components["프로토콜(기계 ∪ LLM)"]["detected"] == 120
    assert not components["기계 단독"]["passed"]
    assert not components["LLM 단독(판정자 합집합)"]["passed"]
    assert components["LLM 단독(판정자 합집합)"]["detected"] == 120 - 30  # 기계 몫 2종(15+15)


def test_one_judge_saying_defect_is_enough(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    nothing = _labels(files["dir"] / "m.jsonl", key_rows, lambda r: False)
    judge_a = _labels(files["dir"] / "a.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    judge_b = _labels(files["dir"] / "b.jsonl", key_rows, lambda r: False)
    assert _score(files, nothing, [judge_a, judge_b]) == 0
    assert _score(files, nothing, [judge_b, judge_a]) == 0


def test_false_alarm_denominator_is_the_clean_count(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    clean_ids = {r["item_id"] for r in _clean(key_rows)[:5]}
    out = files["dir"] / "score.json"
    assert (
        _run(files, key_rows, missed=set(), false_alarms=clean_ids, extra=("--json-out", str(out)))
        == 0
    )
    protocol = json.loads(out.read_text("utf-8"))["protocol"]
    assert protocol["false_alarm"] == 5 and protocol["n_clean"] == 120
    assert protocol["false_alarm_upper"] == pytest.approx(wilson_upper_bound(5, 120))
    assert protocol["detection_lower"] == pytest.approx(wilson_lower_bound(120, 120))


def test_machine_only_scope_is_labeled_and_not_a_protocol_verdict(
    files: dict[str, Path], key_rows: list[dict[str, Any]]
) -> None:
    machine = _labels(files["dir"] / "m.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    out = files["dir"] / "score.json"
    assert _score(files, machine, [], "--machine-only", "--json-out", str(out)) == 0
    payload = json.loads(out.read_text("utf-8"))
    assert payload["scope"] == "machine_only" and payload["n_llm_judges"] == 0


# ── 입력 오류 = exit 2 ───────────────────────────────────────────────────
def test_fewer_than_two_judges_is_an_input_error(
    files: dict[str, Path], key_rows: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    machine = _labels(files["dir"] / "m.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    judge = _labels(files["dir"] / "a.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    assert _score(files, machine, [judge]) == 2
    assert "2명 이상" in capsys.readouterr().err
    assert _score(files, machine, []) == 2
    assert _score(files, machine, [judge, judge]) == 2  # 같은 파일 두 번은 판정자 2명이 아니다
    assert "두 번" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("defect", "message"),
    [
        ("missing", "누락"),
        ("duplicate", "중복"),
        ("unknown", "없는 item_id"),
        ("bad_verdict", "verdict"),
    ],
)
def test_malformed_judge_labels_are_input_errors(
    files: dict[str, Path],
    key_rows: list[dict[str, Any]],
    defect: str,
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    machine = _labels(files["dir"] / "m.jsonl", key_rows, lambda r: False)
    good = _labels(files["dir"] / "a.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    rows = [{"item_id": r["item_id"], "verdict": "ok"} for r in key_rows]
    if defect == "missing":
        rows = rows[:-1]
    elif defect == "duplicate":
        rows.append(dict(rows[0]))
    elif defect == "unknown":
        rows[0] = {"item_id": "zzz", "verdict": "ok"}
    else:
        rows[0] = {"item_id": rows[0]["item_id"], "verdict": "maybe"}
    bad = _write_jsonl(files["dir"] / "b.jsonl", rows)
    assert _score(files, machine, [good, bad]) == 2
    assert message in capsys.readouterr().err


def test_swapped_answer_key_is_an_input_error(
    files: dict[str, Path], key_rows: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """사전 등록 지문과 다른 정답지(바꿔치기)는 채점하지 않는다."""
    labels = _labels(files["dir"] / "m.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    judge_a = _labels(files["dir"] / "a.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    judge_b = _labels(files["dir"] / "b.jsonl", key_rows, lambda r: bool(r["is_defective"]))
    assert _score(files, labels, [judge_a, judge_b]) == 0  # 대조군 — 지문이 맞으면 채점한다
    swapped = [dict(r) for r in key_rows]
    swapped[0]["mutation_note"] = "edited"
    _write_jsonl(files["key"], swapped)
    capsys.readouterr()
    assert _score(files, labels, [judge_a, judge_b]) == 2
    assert "바꿔치기" in capsys.readouterr().err


def test_wrong_test_design_is_an_input_error(
    files: dict[str, Path], key_rows: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """종류별 15건 미만 등 Kiki 설계와 다른 정답지는 그 시험이 아니다."""
    rows = [dict(r) for r in key_rows]
    first = BANK_DEFECT_CLASSES[0]
    target = next(r for r in rows if r["defect_class"] == first)
    target["defect_class"] = BANK_DEFECT_CLASSES[-1]  # 14건이 된다
    _write_jsonl(files["key"], rows)
    files["sha"].write_text(hashlib.sha256(files["key"].read_bytes()).hexdigest() + "\n", "utf-8")
    labels = _labels(files["dir"] / "m.jsonl", rows, lambda r: bool(r["is_defective"]))
    other = _labels(files["dir"] / "a.jsonl", rows, lambda r: bool(r["is_defective"]))
    assert _score(files, labels, [labels, other]) == 2
    assert "구성 불일치" in capsys.readouterr().err


# ── S5 보정 상한 ─────────────────────────────────────────────────────────
def test_corrected_upper_bound_formula() -> None:
    """두 경계 모두 단측 97.5%(사전 등록) — 95% 상한을 쓰면 보정 상한이 낮아져 관대해진다."""
    assert qual.S5_CONFIDENCE == 0.975
    assert qual.corrected_upper_bound(4, 504, 0.95) == pytest.approx(
        wilson_upper_bound(4, 504, 0.975) / 0.95
    )
    assert qual.corrected_upper_bound(4, 504, 0.95) > wilson_upper_bound(4, 504, 0.95) / 0.95
    with pytest.raises(qual.QualificationInputError):
        qual.corrected_upper_bound(0, 504, 0.0)


def test_s5_detection_lower_is_recomputed_at_975() -> None:
    """S5는 점수 JSON의 95% 하한을 그대로 쓰지 않고 원 계수에서 97.5% 하한을 다시 낸다."""
    protocol = {
        "detected": 120,
        "n_defective": 120,
        "detection_lower": wilson_lower_bound(120, 120),
    }
    lower = qual.s5_detection_lower(protocol)
    assert lower == pytest.approx(wilson_lower_bound(120, 120, 0.975))
    assert lower < protocol["detection_lower"]  # 97.5%가 더 보수적
    # 실측 자격 결과(120/120)에서 은행 허용 결함 수: k ≤ 3 통과 · k = 4 불합격
    assert (
        qual.corrected_upper_bound(3, 504, lower)
        <= 0.02
        < qual.corrected_upper_bound(4, 504, lower)
    )


@pytest.mark.parametrize(
    "protocol",
    [
        {"detection_lower": 0.97},  # 계수 없음
        {"detected": 100, "n_defective": 100, "detection_lower": wilson_lower_bound(100, 100)},
        {"detected": 121, "n_defective": 120, "detection_lower": 0.97},
        {"detected": 120.0, "n_defective": 120, "detection_lower": wilson_lower_bound(120, 120)},
        {"detected": True, "n_defective": 120, "detection_lower": wilson_lower_bound(1, 120)},
        # 계수는 그대로 두고 95% 하한만 손편집 — 재현 불일치
        {"detected": 110, "n_defective": 120, "detection_lower": wilson_lower_bound(120, 120)},
    ],
)
def test_s5_detection_lower_rejects_bad_counts(protocol: dict[str, object]) -> None:
    with pytest.raises(qual.QualificationInputError):
        qual.s5_detection_lower(protocol)


@pytest.fixture()
def bank_ids() -> list[str]:
    return [
        json.loads(line)["problem_id"] for line in _BANK.read_text("utf-8").splitlines() if line
    ]


def _qualification(
    path: Path, *, passed: bool, detected: int = 120, scope: str = "protocol"
) -> Path:
    payload = {
        "scope": scope,
        "passed": passed,
        "criteria": qual.criteria(),
        "protocol": {
            "detected": detected,
            "n_defective": 120,
            "detection_lower": wilson_lower_bound(detected, 120),
        },
    }
    path.write_text(json.dumps(payload), "utf-8")
    return path


def _bank_labels(path: Path, ids: list[str], defects: set[str]) -> Path:
    return _write_jsonl(
        path, ({"item_id": i, "verdict": "defect" if i in defects else "ok"} for i in ids)
    )


def _s5(
    tmp_path: Path, ids: list[str], defects_by: dict[str, set[str]], qualification: Path
) -> int:
    machine = _bank_labels(tmp_path / "bm.jsonl", ids, defects_by.get("machine", set()))
    argv = [
        "s5",
        "--bank",
        str(_BANK),
        "--machine",
        str(machine),
        "--qualification",
        str(qualification),
    ]
    for name in ("a", "b"):
        if name in defects_by:
            argv += ["--llm", str(_bank_labels(tmp_path / f"b{name}.jsonl", ids, defects_by[name]))]
    return qual.main(argv)


def test_s5_boundary_with_the_union_of_auditors(tmp_path: Path, bank_ids: list[str]) -> None:
    """검출 120/120(97.5% 하한 0.9690)에서 k = 3 → 0.0179(통과), k = 4 → 0.0209(불합격).

    k는 기계 ∪ 판정자 합집합 — 겹치는 표시는 한 번만 센다.
    """
    good = _qualification(tmp_path / "q.json", passed=True)
    three = {"machine": set(bank_ids[:2]), "a": {bank_ids[2]}, "b": set(bank_ids[:1])}
    four = {"machine": set(bank_ids[:2]), "a": {bank_ids[2]}, "b": {bank_ids[3]}}
    assert _s5(tmp_path, bank_ids, three, good) == 0
    assert _s5(tmp_path, bank_ids, four, good) == 1


def test_s5_uses_975_not_the_stored_95_lower(tmp_path: Path, bank_ids: list[str]) -> None:
    """95% 경계라면 통과하고 97.5%에서는 떨어지는 지점 — 사전 등록 규칙이 실제로 판정을 가른다.

    실측 자격 결과(검출 120/120)에서 k = 4: 95% 두 경계로는 0.01796(통과), 사전 등록한 97.5% 두
    경계로는 0.02087(불합격). 점수 JSON의 95% 하한을 그대로 쓰는 회귀는 이 테스트가 잡는다.
    """
    k = 4
    assert wilson_upper_bound(k, 504, 0.95) / wilson_lower_bound(120, 120, 0.95) <= 0.02
    q = _qualification(tmp_path / "q.json", passed=True)
    flagged = {"machine": set(bank_ids[:k]), "a": set(), "b": set()}
    assert _s5(tmp_path, bank_ids, flagged, q) == 1


def test_s5_refuses_an_unqualified_or_tampered_auditor(tmp_path: Path, bank_ids: list[str]) -> None:
    clean = {"machine": set(), "a": set(), "b": set()}
    failed = _qualification(tmp_path / "f.json", passed=False)
    assert _s5(tmp_path, bank_ids, clean, failed) == 1
    machine_only = _qualification(tmp_path / "m.json", passed=True, scope="machine_only")
    assert _s5(tmp_path, bank_ids, clean, machine_only) == 2
    tampered = tmp_path / "t.json"
    payload = json.loads(_qualification(tampered, passed=True).read_text("utf-8"))
    payload["criteria"]["min_detection_lower"] = 0.5
    tampered.write_text(json.dumps(payload), "utf-8")
    assert _s5(tmp_path, bank_ids, clean, tampered) == 2
    edited = tmp_path / "e.json"
    payload = json.loads(_qualification(edited, passed=True, detected=100).read_text("utf-8"))
    payload["protocol"]["detected"] = 120  # 하한은 100/120 그대로 — 계수만 부풀림
    edited.write_text(json.dumps(payload), "utf-8")
    assert _s5(tmp_path, bank_ids, clean, edited) == 2


def test_s5_input_errors(tmp_path: Path, bank_ids: list[str]) -> None:
    good = _qualification(tmp_path / "q.json", passed=True)
    assert _s5(tmp_path, bank_ids, {"machine": set(), "a": set()}, good) == 2  # 판정자 1명
    assert _s5(tmp_path, bank_ids[:-1], {"machine": set(), "a": set(), "b": set()}, good) == 2


# ── 기계 게이트 라벨 ─────────────────────────────────────────────────────
def test_machine_label_on_a_clean_bank_record_and_a_notation_defect() -> None:
    record = json.loads(_BANK.read_text("utf-8").splitlines()[0])
    label = qual.machine_label(record, "x1")
    assert label["verdict"] == "ok" and label["fired"] == []
    broken = json.loads(json.dumps(record))
    broken["question_text"] = broken["question_text"].replace("구하시오", "구하시오 (단, x <= 3)")
    label = qual.machine_label(broken, "x2")
    assert label["verdict"] == "defect" and "shortcut_guard" in label["fired"]


def test_statement_auditor_is_diagnostic_and_does_not_vote() -> None:
    """발문-수식 정합 감사기는 이 은행 정상 문항을 거부하지만(실측 164/504) 판정에 투표하지 않는다."""
    record = json.loads(_BANK.read_text("utf-8").splitlines()[0])
    label = qual.machine_label(record, "x1")
    assert label["diagnostic"]["statement_auditor"] == "fail"
    assert label["verdict"] == "ok"
    assert "statement_auditor" not in qual.VOTING_GATES


# ── 커밋된 시험지의 무결성 ───────────────────────────────────────────────
def test_committed_artifacts_are_mutually_consistent() -> None:
    manifest = json.loads((_QUAL / "manifest.json").read_text("utf-8"))
    blind_bytes = (_QUAL / "blind_240.jsonl").read_bytes()
    assert hashlib.sha256(blind_bytes).hexdigest() == manifest["blind_sha256"]
    registered = (_QUAL / "answer_key.sha256").read_text("utf-8").split()[0]
    assert registered == manifest["answer_key_sha256"]
    assert hashlib.sha256(_BANK.read_bytes()).hexdigest() == manifest["bank_sha256"]
    assert manifest["criteria"] == qual.criteria()
    blind = [json.loads(line) for line in blind_bytes.decode("utf-8").splitlines()]
    ids = [r["item_id"] for r in blind]
    assert len(ids) == len(set(ids)) == 240
    leaked = {"problem_id", "slug", "is_defective", "defect_class", "variant", "mutation_note"}
    assert not any(leaked & set(r) for r in blind)  # 블라인드 — 정답지 필드·은행 id 없음
    bank_ids = {json.loads(line)["problem_id"] for line in _BANK.read_text("utf-8").splitlines()}
    assert not any(i in bank_ids for i in ids)
    machine = [
        json.loads(line)
        for line in (_QUAL / "machine_labels.jsonl").read_text("utf-8").splitlines()
    ]
    assert [r["item_id"] for r in machine] == ids


@pytest.mark.corpus_authoring
def test_emit_check_reproduces_the_committed_test() -> None:
    """같은 seed·같은 은행으로 재생성하면 커밋된 시험지·지문·매니페스트와 바이트가 같다.

    RED면 시험지를 만드는 코드(주입기·판정기·스캐너)나 은행이 바뀐 것이다. 이미 이 시험지로 판정자
    라벨을 받았다면 조용히 재생성하지 말고 README에 드리프트를 적은 뒤 새 시험으로 다시 잰다.
    """
    assert qual.main(["emit", "--check"]) == 0


@pytest.mark.corpus_authoring
def test_machine_check_reproduces_the_committed_labels() -> None:
    assert qual.main(["machine", "--check"]) == 0


# ── 은행 감사 묶음(bank-sheets) ──────────────────────────────────────────
_BANK_AUDIT = _ROOT / "docs" / "data" / "p3_calculus1_diff_audit" / "bank_audit"


def test_bank_sheets_partition_the_bank_with_the_blind_field_set() -> None:
    """504건이 8묶음 × 63건으로 빠짐·겹침 없이 나뉘고, 필드는 시험지와 같다(검출률 이전의 전제)."""
    sheets = qual.build_bank_sheets(_BANK, qual.BANK_AUDIT_SEED, qual.BANK_AUDIT_SHARDS)
    shards = [[json.loads(line) for line in text.splitlines()] for text in sheets.shards]
    assert [len(s) for s in shards] == [63] * 8
    ids = [r["item_id"] for s in shards for r in s]
    bank_ids = [json.loads(line)["problem_id"] for line in _BANK.read_text("utf-8").splitlines()]
    assert len(ids) == len(set(ids)) == 504
    assert set(ids) == set(bank_ids)
    blind_keys = list(json.loads((_QUAL / "blind_240.jsonl").read_text("utf-8").splitlines()[0]))
    assert all(list(r) == blind_keys for s in shards for r in s)
    # 은행 순서(개념별로 몰림)를 그대로 자르지 않았다 — 첫 묶음에 7개념이 섞여 있다
    assert len({r["achievement_standard_codes"][0] for r in shards[0]}) == 7
    manifest = json.loads(sheets.manifest)
    assert [e["sha256"] for e in manifest["shards"]] == [
        hashlib.sha256(t.encode("utf-8")).hexdigest() for t in sheets.shards
    ]
    again = qual.build_bank_sheets(_BANK, qual.BANK_AUDIT_SEED, qual.BANK_AUDIT_SHARDS)
    assert again == sheets  # 결정론


def test_bank_sheets_manifest_is_committed_and_reproducible() -> None:
    """커밋된 매니페스트 = 재생성 결과. RED면 은행·지침·묶음 코드가 판정 뒤에 바뀐 것이다."""
    manifest = json.loads((_BANK_AUDIT / "manifest.json").read_text("utf-8"))
    assert manifest["bank_sha256"] == hashlib.sha256(_BANK.read_bytes()).hexdigest()
    protocol = (_QUAL / "rater_protocol.md").read_bytes()
    assert manifest["rater_protocol_sha256"] == hashlib.sha256(protocol).hexdigest()
    assert qual.main(["bank-sheets", "--check", "--bank", str(_BANK)]) == 0


def test_bank_sheets_input_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "inputs"
    manifest = tmp_path / "manifest.json"
    base = ["bank-sheets", "--out-dir", str(out), "--manifest", str(manifest)]
    assert qual.main([*base, "--shards", "5"]) == 2  # 504는 5로 등분 불가
    short = tmp_path / "short.jsonl"
    short.write_text("".join(_BANK.read_text("utf-8").splitlines(keepends=True)[:-1]), "utf-8")
    assert qual.main([*base, "--bank", str(short)]) == 2  # 503건
    assert qual.main(["bank-sheets", "--manifest", str(manifest)]) == 2  # --out-dir 없음
    assert not out.exists() and not manifest.exists()  # 입력 오류에서 아무것도 쓰지 않는다
    assert "입력 오류" in capsys.readouterr().err
