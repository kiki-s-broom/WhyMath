"""다음 지시문 계산기(`golden.driver.next_task`) — 합성 묶음으로 각 판정 분기를 밟고, 실제 저장소도 읽는다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from golden.driver import next_task as nt

_HEAD = (
    "| 번호 | 세션 이름 | 단계 | 방식 | 선행 작업 | 여유 |\n| --- | --- | --- | --- | --- | --- |\n"
)


def _pack(
    root: Path,
    prompts: str,
    rows: list[tuple[str, str, int, str]],
    texts: dict[str, str] | None = None,
) -> None:
    """합성 지시문 묶음 — README 표 + 단계 폴더 안 지시문 파일."""
    d = root / prompts
    d.mkdir(parents=True, exist_ok=True)
    body = "".join(f"| {i} | {n} | {s} | 순차 | {deps} | 없음 |\n" for i, n, s, deps in rows)
    (d / "README.md").write_text(
        f"# 묶음\n\n## 작업별 실행 정보\n\n{_HEAD}{body}\n끝\n", encoding="utf-8"
    )
    for task_id, name, stage, _ in rows:
        f = d / f"단계{stage:02d}_순차" / f"{name}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text((texts or {}).get(task_id, f"세션 이름: {name}\n할 일\n"), encoding="utf-8")


def _report(root: Path, reports: str, task_id: str, text: str) -> None:
    f = root / reports / task_id / "보고.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


P1 = ("1단계", "p1", "r1")
P2 = ("2단계", "p2", "r2")
ROWS1 = [
    ("H1", "X-단계01-H1-섭외-Kiki", 1, "없음"),
    ("S1", "X-단계01-S1-가", 1, "없음"),
    ("S2", "X-단계02-S2-나", 2, "S1"),
    ("S3", "X-단계03-S3-다", 3, "S2, H1"),
]
ROWS2 = [("S9", "X-단계01-S9-라", 1, "없음")]


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    _pack(tmp_path, "p1", ROWS1, {"S2": "세션 이름: X\n1. (Kiki) Kiki 머신에서 돌린다\n"})
    _pack(tmp_path, "p2", ROWS2)
    return tmp_path


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("결과: 완료\n", nt.DONE),
        ("> **결과: 완료 — 다시 판정**\n", nt.DONE),
        ("결과：완료\n", nt.DONE),  # 전각 쌍점
        ("결과: 일부 완료 — ④ 미측정\n", nt.PARTIAL),
        ("결과: 중단 (Kiki 결정)\n", nt.STOPPED),
        ("결과: 실패\n", nt.OTHER),
        ("# 보고\n> 진행 중 — Kiki 머신 대기\n", nt.IN_PROGRESS),
        ("결과: 일부 완료\n\n결과: 완료\n", nt.PARTIAL),  # 첫 결과 줄로 판정
    ],
)
def test_read_status_branches(tmp_path: Path, text: str, status: str) -> None:
    f = tmp_path / "보고.md"
    f.write_text(text, encoding="utf-8")
    assert nt.read_status(f)[0] == status


def test_read_status_missing_report_is_todo(tmp_path: Path) -> None:
    assert nt.read_status(tmp_path / "없음.md") == (nt.TODO, "")


def test_task_kind() -> None:
    assert nt.task_kind("H2", "X-H2-섭외", "") == nt.KIND_KIKI
    assert nt.task_kind("S9", "X-S9-일-Kiki", "") == nt.KIND_KIKI
    assert nt.task_kind("S9", "X-S9-일", "1. (Kiki) 돌린다") == nt.KIND_KIKI_MACHINE
    assert nt.task_kind("S9", "X-S9-일", "Kiki 결정을 기다린다") == nt.KIND_CLOUD


def test_fresh_pack_runs_first_cloud_task_and_lists_kiki_task(root: Path) -> None:
    result = nt.plan(root, (P1, P2))
    assert result["verdict"] == "RUN"
    assert result["phase"] == "1단계"
    assert [t["task_id"] for t in result["runnable"]] == ["H1", "S1"]


def test_dependency_needs_done_or_stopped(root: Path) -> None:
    # S3의 선행은 S2·H1 — H1이 '중단'(Kiki 결정으로 닫힘)이어도 선행을 채운다
    _report(root, "r1", "S1", "결과: 완료\n")
    _report(root, "r1", "S2", "결과: 완료\n")
    _report(root, "r1", "H1", "결과: 중단 (Kiki 결정)\n")
    result = nt.plan(root, (P1, P2))
    assert [(t["task_id"], t["kind"]) for t in result["runnable"]] == [("S3", nt.KIND_CLOUD)]
    _report(root, "r1", "S1", "결과: 완료\n")
    _report(root, "r1", "H1", "결과: 일부 완료\n")  # 대조군 — 일부 완료면 S3은 막힌다
    assert nt.plan(root, (P1, P2))["runnable"] == []


def test_partial_does_not_satisfy_dependency(root: Path) -> None:
    _report(root, "r1", "S1", "결과: 일부 완료\n")
    _report(root, "r1", "H1", "결과: 완료\n")
    result = nt.plan(root, (P1, P2))
    assert result["verdict"] == "ATTENTION"
    assert result["runnable"] == []
    assert [t["task_id"] for t in result["attention"]] == ["S1"]


def test_in_progress_is_not_reopened(root: Path) -> None:
    for task_id in ("S1", "H1"):
        _report(root, "r1", task_id, "결과: 완료\n")
    _report(root, "r1", "S2", "# S2\n> 진행 중 — Kiki 머신 대기\n")
    result = nt.plan(root, (P1, P2))
    assert result["verdict"] == "ATTENTION"
    assert result["attention"][0]["status"] == nt.IN_PROGRESS


def test_only_kiki_task_runnable_waits_for_kiki(root: Path) -> None:
    _report(root, "r1", "S1", "결과: 완료\n")
    _report(root, "r1", "S2", "결과: 완료\n")
    result = nt.plan(root, (P1, P2))
    assert result["verdict"] == "WAIT_KIKI"
    assert [t["task_id"] for t in result["runnable"]] == ["H1"]


def test_phase_boundary_stops_before_next_phase(root: Path) -> None:
    for task_id in ("H1", "S1", "S2", "S3"):
        _report(root, "r1", task_id, "결과: 완료\n")
    result = nt.plan(root, (P1, P2))
    assert result["verdict"] == "BOUNDARY"
    assert result["phase"] == "2단계"
    _report(root, "r2", "S9", "결과: 완료\n")
    assert nt.plan(root, (P1, P2))["verdict"] == "ALL_DONE"


def test_next_phase_runs_once_started(root: Path) -> None:
    for task_id in ("H1", "S1", "S2", "S3"):
        _report(root, "r1", task_id, "결과: 완료\n")
    _pack(root, "p2", [*ROWS2, ("S10", "X-단계02-S10-마", 2, "S9")])
    _report(root, "r2", "S9", "결과: 완료\n")  # Kiki가 2단계를 연 뒤
    result = nt.plan(root, (P1, P2))
    assert (result["verdict"], [t["task_id"] for t in result["runnable"]]) == ("RUN", ["S10"])


@pytest.mark.parametrize(
    "readme",
    [
        "# 표 없음\n",
        _HEAD + "\n",  # 머리줄만 — 0줄
        _HEAD + "| 번호아님 | X | 1 | 순차 | 없음 | 없음 |\n",
        _HEAD + "| S1 | X | 첫째 | 순차 | 없음 | 없음 |\n",
    ],
)
def test_parse_table_refuses_bad_readme(tmp_path: Path, readme: str) -> None:
    f = tmp_path / "README.md"
    f.write_text(readme, encoding="utf-8")
    with pytest.raises(nt.NextTaskError):
        nt.parse_table(f)


def test_plan_refuses_missing_instruction_file_and_unknown_dep(tmp_path: Path) -> None:
    _pack(tmp_path, "p1", [("S1", "X-S1-가", 1, "없음")])
    (tmp_path / "p1" / "단계01_순차" / "X-S1-가.md").unlink()
    with pytest.raises(nt.NextTaskError, match="0개"):
        nt.plan(tmp_path, (P1,))
    _pack(tmp_path, "q1", [("S1", "X-S1-가", 1, "S99")])
    with pytest.raises(nt.NextTaskError, match="S99"):
        nt.plan(tmp_path, (("1단계", "q1", "r1"),))


def test_main_json_and_refusal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 성공 경로는 실제 저장소(기본 묶음 경로), 거부 경로는 묶음이 없는 빈 폴더
    assert nt.main(["--root", str(nt.REPO), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] in nt.VERDICTS
    assert nt.main(["--root", str(tmp_path)]) == 2
    assert "NEXT_TASK_REFUSED" in capsys.readouterr().err


def test_real_repository_packs_parse() -> None:
    """실제 저장소의 1~4단계 묶음을 전부 읽는다(표·파일·선행이 맞물리는지)."""
    total = 0
    for phase, prompts, reports in nt.PACKS:
        tasks = nt.load_pack(nt.REPO, phase, prompts, reports)
        assert len(tasks) >= 20, f"{phase} 작업 {len(tasks)}개 — 스캔 실패"
        total += len(tasks)
    assert total >= 90
    assert nt.plan(nt.REPO)["verdict"] in nt.VERDICTS
