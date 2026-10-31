"""골든 대비 채점기(scripts/eval/score_against_golden.py)의 변별력 동결.

정상 입력(골든 자기 자신)에서 초록인 것만으로는 보호를 선언하지 않는다(CLAUDE.md "보호 장치를 실패 주입 없이
'보호 있음'으로 선언 금지"). 결함 주입 6종 — 수학 0점·정답 누설·2015 코드·금칙 어휘+질문 2개·M-id 날조+출처
표기 — 이 **각각 FAIL**이고, 문장만 다른 정상 후보(대조군)는 FAIL이 아님을 함께 고정한다(과잉 차단 검사).
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCORER = REPO / "scripts/eval/score_against_golden.py"
BUILDER = REPO / "scripts/eval/build_golden_set_rubric_v1.py"
GOLDEN = REPO / "data/corpus/golden_set_rubric_v1/golden.json"


def _run(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCORER), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


@pytest.fixture(scope="module")
def golden_nodes() -> dict[str, dict]:
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return {n["golden_id"]: n for n in data["nodes"]}


def test_golden_file_is_reproducible_from_builder(tmp_path: Path) -> None:
    """커밋된 golden.json이 생성기 출력과 같다 — 손편집 드리프트 차단(digest는 날짜 필드 때문에 제외)."""
    committed = json.loads(GOLDEN.read_text(encoding="utf-8"))
    proc = subprocess.run(
        [sys.executable, str(BUILDER), "--out-dir", str(tmp_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    rebuilt = json.loads((tmp_path / "golden.json").read_text(encoding="utf-8"))
    for d in (committed, rebuilt):
        d.pop("built_on", None)
        d.pop("digest", None)
    assert committed == rebuilt
    assert rebuilt["count"] == 20
    assert rebuilt["by_school_type"] == {"초등학교": 7, "중학교": 8, "고등학교": 5}


def test_self_check_passes() -> None:
    """골든을 후보로 넣으면 전건 상한 3·게이트 통과(exit 0)."""
    proc = _run("--self-check")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "자가검증 통과: 20노드" in proc.stdout


def _mutants(g: dict[str, dict]) -> list[tuple[str, dict, str | None]]:
    """(이름, 변이 후보, 기대 fail 사유 부분 문자열 — None이면 FAIL이 아니어야 함)."""
    out: list[tuple[str, dict, str | None]] = []
    m = copy.deepcopy(g["G01"])
    m["mc_item"]["verify"]["expected"] = "75"
    out.append(("정답 불일치(F2)", m, "수학 0점"))
    m = copy.deepcopy(g["G08"])
    m["socratic_flow"][2]["tutor"] = "그래서 최소공배수는 360이 되겠지?"
    out.append(("튜터 정답 누설(F8)", m, "F8_answer_leak"))
    m = copy.deepcopy(g["G07"])
    m["standard_code"] = "[6수05-01]"  # 2015 개정 전용 코드(평균)
    out.append(("2015 전용 성취기준 코드", m, "어느 축 상한 ≤1"))
    m = copy.deepcopy(g["G05"])
    m["concept_explanation"]["text"] = "유리수의 나눗셈은 역수를 곱하는 것으로 정의돼요."
    m["socratic_flow"][0]["tutor"] = "2/3은 1보다 클까? 아니면 작을까?"
    out.append(("금칙 어휘 2건 + 질문 2개", m, "cognitive_load"))
    m = copy.deepcopy(g["G12"])
    m["mc_item"]["distractor_map"][0]["misconception_id"] = "M9999"
    m["mc_item"]["stem"] += " (천재교육 중1 수학 97쪽 예제)"
    out.append(("M-id 날조 + 출처 표기", m, "저작권 0점"))
    m = copy.deepcopy(g["G14"])
    m["concept_explanation"]["text"] = (
        "직각삼각형에서 가장 긴 변이 빗변이에요. 빗변의 길이를 두 번 곱한 값은 나머지 두 변을 "
        "각각 두 번 곱해 더한 값과 같아요. 6과 8이면 36 더하기 64는 100이니까 빗변은 10이에요."
    )
    m["socratic_flow"][0]["tutor"] = "직각의 맞은편에 있는 변을 뭐라고 부를까?"
    out.append(("대조군 — 문장만 다른 정상 후보", m, None))
    return out


def test_mutants_fail_and_control_passes(golden_nodes: dict[str, dict], tmp_path: Path) -> None:
    """결함 주입 5종 전건 FAIL(각각 기대 사유 포함) · 대조군 1건은 FAIL 아님 · 전체 exit 1."""
    muts = _mutants(golden_nodes)
    cand = tmp_path / "mutants.jsonl"
    cand.write_text(
        "".join(json.dumps(m, ensure_ascii=False) + "\n" for _, m, _ in muts), encoding="utf-8"
    )
    report = tmp_path / "report.json"
    proc = _run("--candidates", str(cand), "--out", str(report))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    results = json.loads(report.read_text(encoding="utf-8"))["results"]
    assert len(results) == len(muts)
    for (name, _, expect), r in zip(muts, results, strict=True):
        if expect is None:
            assert r["status"] != "FAIL", f"{name}: 대조군이 FAIL — 과잉 차단 {r['fail_reasons']}"
        else:
            assert r["status"] == "FAIL", f"{name}: FAIL이어야 함 — {r}"
            assert any(
                expect in reason for reason in r["fail_reasons"]
            ), f"{name}: 기대 사유 '{expect}' 없음 — {r['fail_reasons']}"


def test_empty_candidates_is_measurement_failure(tmp_path: Path) -> None:
    """후보 0건은 통과가 아니라 측정 실패(exit 2) — '0건 통과' 위장 차단."""
    cand = tmp_path / "empty.jsonl"
    cand.write_text("", encoding="utf-8")
    proc = _run("--candidates", str(cand))
    assert proc.returncode == 2
    assert "측정 실패" in proc.stderr
