"""충돌 마커 가드의 **배선 실재성**과 **변별력** 동결 (HARN-128 ④).

이 파일이 지키는 것 두 가지
---------------------------
① **배선** — "저장소에 존재함"이 아니라 "CI에서 돈다"를 고정한다. 가드 스크립트가
   ci.yml의 policy-guard 잡과 **별도 워크플로 파일** 양쪽에서 실행되는지 본다.
   두 곳인 것이 중복이 아니라 설계다: ci.yml 자신이 깨지면 그 안의 스텝은 함께 죽고
   (실측 2026-09-23 — 마커 주입 시 yaml ScannerError), 별도 파일만이 그 상황에서
   살아남는다. 반대로 별도 파일이 깨지면 ci.yml 스텝이 그것을 잡는다(상호 엄호).
   그래서 "두 워크플로가 서로 다른 파일에 있다"까지가 계약이다.

② **변별력** — 정상 입력에서 초록인 것은 보호의 증거가 아니다(CLAUDE.md 2026-09-01).
   판정 절마다 **그 절이 없으면 통과하는 입력**을 픽스처로 둔다:
     · `^` 앵커 절 → 들여쓴 마커(정상 산문의 예시 표기)
     · 구분선 단독 제외 절 → Markdown setext 제목
     · DECISIVE_KINDS 절 → 시작/끝 없이 구분선만 있는 파일
     · 상태 만료 면제 절 → 면제에 등재됐는데 마커가 없는 경우
     · 스캔 0건 절 → 빈 저장소

리터럴 7연속을 쓰지 않는 이유
-----------------------------
이 파일이 스캔 대상이기 때문이다. 마커 문자열은 전부 **런타임에 곱해서** 만든다 —
제외 목록으로 이 파일을 빼면 그 목록이 곧 구멍이 된다(이름만 올리면 면제된다).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_PATH = _REPO_ROOT / "scripts" / "ops" / "check_conflict_markers.py"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_STANDALONE_PATH = _REPO_ROOT / ".github" / "workflows" / "conflict-guard.yml"

#: 런타임 생성 — 이 파일 자신이 가드에 걸리지 않게 한다.
START = "<" * 7
BASE = "|" * 7
SEP = "=" * 7
END = ">" * 7


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_conflict_markers", _GUARD_PATH)
    assert spec and spec.loader, f"가드 로드 실패: {_GUARD_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_conflict_markers"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _make_repo(root: Path, files: dict[str, str]) -> Path:
    """git 추적 파일을 가진 최소 저장소. 가드는 `git ls-files`로 대상을 정한다."""
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, timeout=60)
    return root


# ── ① 배선 실재성 ─────────────────────────────────────────────────────────
class TestWiring:
    """'존재함'이 아니라 '돈다'를 고정한다."""

    def test_guard_script_exists(self) -> None:
        assert _GUARD_PATH.is_file(), f"가드 스크립트가 없다: {_GUARD_PATH}"

    def test_wired_into_policy_guard_job(self) -> None:
        spec = yaml.safe_load(_CI_PATH.read_text(encoding="utf-8"))
        job = (spec.get("jobs") or {}).get("policy-guard")
        assert job, "ci.yml에 policy-guard 잡이 없다 — 잡을 옮겼다면 이 계약도 옮겨라"
        runs = " ".join(str(step.get("run", "")) for step in job["steps"])
        assert "scripts/ops/check_conflict_markers.py" in runs, (
            "policy-guard 잡이 충돌 마커 가드를 실행하지 않는다 — "
            "스크립트가 저장소에 있어도 CI에서 돌지 않으면 보호가 아니다"
        )

    def test_standalone_workflow_runs_the_guard_on_pull_request(self) -> None:
        """ci.yml이 깨져도 살아남는 경로. PR 트리거가 아니면 사전 차단이 되지 못한다."""
        assert _STANDALONE_PATH.is_file(), (
            f"별도 워크플로가 없다: {_STANDALONE_PATH} — ci.yml 안의 스텝만으로는 "
            "사고 상황(ci.yml 자신이 깨짐)에서 무력하다"
        )
        spec = yaml.safe_load(_STANDALONE_PATH.read_text(encoding="utf-8"))
        # PyYAML은 YAML 1.1 규칙으로 `on:` 키를 True로 읽는다.
        triggers = spec.get("on") or spec.get(True) or {}
        assert (
            "pull_request" in triggers
        ), "별도 워크플로가 pull_request에서 돌지 않는다 — 착지 후에야 보이면 사전 차단이 아니다"
        runs = " ".join(
            str(step.get("run", "")) for job in spec["jobs"].values() for step in job["steps"]
        )
        assert (
            "scripts/ops/check_conflict_markers.py" in runs
        ), "별도 워크플로가 가드를 실행하지 않는다"

    def test_two_wirings_live_in_different_files(self) -> None:
        """상호 엄호의 전제 — 같은 파일에 있으면 함께 죽는다.

        이 단언이 없으면 누군가 별도 워크플로를 ci.yml로 합치면서 위 두 테스트를 모두
        통과시킬 수 있다(둘 다 '가드를 실행한다'는 말만 하기 때문).
        """
        assert _STANDALONE_PATH != _CI_PATH
        assert _STANDALONE_PATH.is_file() and _CI_PATH.is_file()

    def test_standalone_guard_step_is_blocking(self) -> None:
        """continue-on-error로 강등되면 red가 안 뜬다 — 설명 역할 자체가 사라진다."""
        spec = yaml.safe_load(_STANDALONE_PATH.read_text(encoding="utf-8"))
        for job_name, job in spec["jobs"].items():
            assert not job.get("continue-on-error"), f"{job_name} 잡이 non-blocking이다"
            for step in job["steps"]:
                assert not step.get(
                    "continue-on-error"
                ), f"{job_name}/{step.get('name')} 스텝이 non-blocking이다"


# ── ② 변별력 — 절마다 그 절의 반례 ────────────────────────────────────────
class TestDiscrimination:
    def _run(self, root: Path) -> guard.Report:
        return guard.scan(root, exemptions={})

    def test_clean_repo_is_green(self, tmp_path: Path) -> None:
        """대조군 — 이것이 없으면 '전부 위반' 과잉 수정이 통과한다."""
        root = _make_repo(tmp_path, {"a.py": "print('hi')\n", "b.md": "# 제목\n본문\n"})
        report = self._run(root)
        assert report.ok and report.scanned == 2

    def test_full_conflict_block_is_detected(self, tmp_path: Path) -> None:
        body = f"before\n{START} HEAD\nmine\n{SEP}\ntheirs\n{END} origin/main\nafter\n"
        root = _make_repo(tmp_path, {"ci.yml": body})
        report = self._run(root)
        kinds = {hit.kind for hit in report.violations}
        assert kinds == {"start", "separator", "end"}, kinds

    def test_diff3_base_marker_is_detected(self, tmp_path: Path) -> None:
        """`merge.conflictStyle=diff3`는 공통조상 절(`|` 7개)을 남긴다 — 별도 절이다."""
        body = f"{START} HEAD\nmine\n{BASE} base\norig\n{SEP}\ntheirs\n{END} other\n"
        root = _make_repo(tmp_path, {"x.txt": body})
        report = self._run(root)
        assert "base" in {hit.kind for hit in report.violations}

    def test_setext_heading_is_not_a_violation(self, tmp_path: Path) -> None:
        """구분선 단독 제외 절의 반례 — 이 절이 없으면 정상 Markdown이 red가 된다."""
        root = _make_repo(tmp_path, {"doc.md": f"제목입니다\n{SEP}\n본문\n"})
        assert self._run(root).ok

    def test_separator_only_file_is_not_a_violation(self, tmp_path: Path) -> None:
        """DECISIVE_KINDS 절의 반례 — 시작·끝이 없으면 구분선은 마커가 아니다."""
        root = _make_repo(tmp_path, {"a.md": f"x\n{SEP}\ny\n{SEP}\nz\n"})
        assert self._run(root).ok

    def test_indented_marker_is_not_a_violation(self, tmp_path: Path) -> None:
        """`^` 앵커 절의 반례 — 산문이 마커를 *예시로 인용*하는 경우.

        이 픽스처가 들여쓰기를 쓰지 않으면 앵커 절을 한 번도 밟지 않는다
        (CLAUDE.md 2026-09-07 픽스처 접촉 규칙).
        """
        root = _make_repo(tmp_path, {"note.md": f"  {START} 예시\n  {END} 예시\n"})
        assert self._run(root).ok

    def test_marker_needs_whitespace_or_line_end(self, tmp_path: Path) -> None:
        """`(?:\\s|$)` 절의 반례 — 8개 이상 연속은 git이 내는 마커가 아니다."""
        root = _make_repo(tmp_path, {"a.md": f"{START}<\n{END}>\n"})
        assert self._run(root).ok

    def test_binary_files_are_skipped_not_scanned(self, tmp_path: Path) -> None:
        root = _make_repo(tmp_path, {"a.txt": "x\n"})
        (root / "blob.bin").write_bytes(b"\x00\x01" + START.encode() + b"\n")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, timeout=60)
        report = self._run(root)
        assert report.skipped_binary == 1 and report.ok

    def test_violation_reports_path_and_line(self, tmp_path: Path) -> None:
        """실패 메시지가 '어디를 고치라'를 말하는가 — 못 말하면 사람이 다시 찾아야 한다."""
        body = f"a\nb\n{START} HEAD\n{SEP}\n{END} x\n"
        root = _make_repo(tmp_path, {"deep/nested/f.yml": body})
        first = self._run(root).violations[0]
        assert first.path == "deep/nested/f.yml" and first.line == 3


# ── ③ 면제는 상태로 만료한다 ──────────────────────────────────────────────
class TestSelfLiquidatingExemption:
    def test_exempted_file_is_waived_not_violation(self, tmp_path: Path) -> None:
        body = f"{START} HEAD\n{SEP}\n{END} x\n"
        root = _make_repo(tmp_path, {"legacy.md": body})
        report = guard.scan(root, exemptions={"legacy.md": "사유"})
        assert report.ok and "legacy.md" in report.waived

    def test_exemption_becomes_violation_once_markers_are_gone(self, tmp_path: Path) -> None:
        """낡은 면제 금지 — 정리가 끝나면 CI가 면제 항목의 삭제를 *강제*한다."""
        root = _make_repo(tmp_path, {"legacy.md": "정리 끝\n"})
        report = guard.scan(root, exemptions={"legacy.md": "사유"})
        assert not report.ok and report.stale_exemptions == ["legacy.md"]

    def test_every_registered_exemption_carries_a_reason(self) -> None:
        """사유 없는 면제는 면제가 아니라 구멍이다."""
        empty = [rel for rel, why in guard.KNOWN_MARKERS.items() if not why.strip()]
        assert not empty, f"사유가 빈 면제: {empty}"


# ── ④ 측정 실패를 통과로 접지 않는다 ──────────────────────────────────────
class TestMeasurementFailure:
    def test_empty_scan_exits_two(self, tmp_path: Path) -> None:
        """스캔 0건은 통과가 아니라 실패다(CLAUDE.md 2026-09-01 축 ④)."""
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
        assert guard.main(["--root", str(tmp_path)]) == 2

    def test_non_git_root_exits_two(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
        assert guard.main(["--root", str(tmp_path)]) == 2


# ── ⑤ 실저장소 — 가드가 자기 자신·테스트에 걸리지 않는다 ──────────────────
class TestRepositoryIsClean:
    def test_repo_scan_has_no_unwaived_violations(self) -> None:
        """이 테스트가 red면 트렁크에 마커가 들어온 것이다(면제 등재분 제외)."""
        report = guard.scan(_REPO_ROOT)
        assert not report.violations, [
            f"{hit.path}:{hit.line}[{hit.kind}]" for hit in report.violations[:10]
        ]

    @pytest.mark.parametrize("rel", ["scripts/ops/check_conflict_markers.py", __file__])
    def test_guard_and_its_test_do_not_trip_the_guard(self, rel: str) -> None:
        """자기참조 오탐 — 제외 목록이 아니라 패턴 설계로 막았는지 확인한다."""
        path = Path(rel) if Path(rel).is_absolute() else _REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert not guard.find_markers(str(path), text)
