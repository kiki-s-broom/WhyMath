"""HARN-205 — 위임 산출물 이식의 기준 신선도 판정(`scripts/harness/port_freshness.py`) 동결.

**사고 경위** (사고 대장 계열 `delegated-output-stale-base` 1회차 · 2026-09-29): ARCH-71 서브에이전트
워크트리가 `ab9f29f2`(ARCH-69 착지 이전 main)에서 분기해 런북을 썼고, 메인 세션은 이식 검증에서
"옮긴 파일이 바이트 동일한가"만 봤다. 이식 시점 브랜치 기준 `c13c04ed`에는 이미 ARCH-69(`eb633ee1`)가
들어와 있어 런북의 서술("1차 좌석 실패 → 5xx")은 거짓이었다. 이 파일은 그 질문 — **산출물이 참조하는
코드가 위임 기준 이후 바뀌었는가** — 을 묻는 도구가 실제로 답하는지 동결한다.

**실사례와 합성 픽스처를 둘 다 두는 이유**: 실사례 산출물 커밋 `4dc0609f`는 원격 어느 브랜치에도 없다
(ARCH-71 PR은 정정본 `ebd7a159`로 스쿼시 머지됐다). 그래서 CI(`harness-integrity` 잡 · fetch-depth: 0)
에서도 그 커밋은 없고 해당 테스트는 **skip된다**. skip만 있는 테스트는 보호가 아니므로 ⓐ 같은 형태를
재현하는 합성 git 저장소 픽스처가 교집합 검출·대조군·0건 exit 2를 **항상** 검사하고 ⓑ main에 있는
정정본(`ebd7a159`)을 산출물로 쓰는 실사례 판본이 CI에서도 돈다.

acceptance 대응: ① 도구 계약 전반 · ② `TestZeroGuard`·`TestFilenameMatching`(모름)·`TestUsageErrors`
· ③ `TestRealCaseArch71`·`TestSyntheticShape` · ④ `TestDriveWiring` · ⑤ 뮤테이션은
`scripts/harness/verify_port_freshness_discrimination.py`가 이 파일에 대해 RED를 확인한다.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import port_freshness as pf
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _REPO_ROOT / "scripts" / "harness" / "port_freshness.py"
_DRIVE_DOC = _REPO_ROOT / ".claude" / "commands" / "drive.md"

# ── 실사례 좌표 (ARCH-71) ─────────────────────────────────────────────────
_REAL_BASE = "ab9f29f2"  # 위임 워크트리의 분기점(ARCH-69 이전)
_REAL_TARGET = "c13c04ed"  # 이식 시점 브랜치 기준(ARCH-69 포함)
_REAL_ARTIFACT_REF = "4dc0609f"  # 서브에이전트가 쓴 런북(로컬 전용 커밋)
_REAL_MAIN_ARTIFACT_REF = "ebd7a159"  # main에 머지된 정정본(ARCH-71 #1392)
_REAL_RUNBOOK = "docs/ops/arch71_student_facing_cloud_mid_live_runbook.md"
_REAL_ARCH69 = "eb633ee1"
_REAL_EXPECTED = {
    "src/backend/whymath_backend/app.py",
    "src/backend/whymath_backend/l3/router.py",
    "tests/backend/l3/test_cloud_mid_seat_cutover.py",
}


def _has_commits(*revs: str) -> bool:
    for rev in revs:
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=_REPO_ROOT, capture_output=True
        )
        if proc.returncode != 0:
            return False
    return True


_SKIP_REASON = (
    "실사례 커밋 부재(얕은 체크아웃이거나 원격에 없는 로컬 전용 커밋) — 같은 형태는 "
    "TestSyntheticShape가 합성 저장소로 항상 검사한다"
)


# ── 공용 헬퍼 ──────────────────────────────────────────────────────────────
def _git(root: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv], cwd=root, capture_output=True, encoding="utf-8", check=True
    )
    return proc.stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run_json(capsys, *argv: str) -> tuple[int, dict | None, str]:
    """CLI를 프로세스 안에서 돌린다 — (종료 코드, JSON 출력 또는 None, stderr)."""
    code = pf.main([*argv, "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out) if captured.out.strip() else None
    return code, data, captured.err


def _paths(data: dict) -> set[str]:
    return {item["path"] for item in data["intersection"]}


# ── 합성 저장소 — 실사례와 같은 형태 ───────────────────────────────────────
RUNBOOK = "docs/ops/runbook.md"
RUNBOOK_TEXT = (
    "# 컷오버 런북 (위임 기준에서 작성)\n"
    "`app.py`의 create_app()이 1차 좌석 실패를 5xx로 올린다.\n"
    "좌석 선택은 `l3/router.py`가 한다.\n"
    "회귀 테스트: `tests/pkg/l3/test_cutover.py`\n"
    "안정 모듈 lib/stable.py 는 그대로다.\n"
    "원칙은 CLAUDE.md를 따른다.\n"
    "출력은 response.json 에 쓴다.\n"
)
_SYNTH_EXPECTED = {
    "src/pkg/app.py",
    "src/pkg/l3/router.py",
    "tests/pkg/l3/test_cutover.py",
    "CLAUDE.md",
}


@dataclass
class Scene:
    root: Path
    base: str  # 위임 워크트리의 분기점
    delegate: str  # 위임 브랜치 — 산출물(런북)이 여기 있다
    target: str  # main HEAD — 기준 이후 드리프트가 들어왔다


@pytest.fixture
def scene(git_repo: Path) -> Scene:
    """ARCH-71과 같은 형태: 기준에서 쓴 런북 + 그 사이 main이 바꾼 코드."""
    root = git_repo
    base_files = {
        "src/pkg/__init__.py": "",
        "src/pkg/app.py": "def create_app():\n    return 500\n",
        "src/pkg/l3/__init__.py": "",
        "src/pkg/l3/router.py": "SEAT = 'mid'\n",
        "src/pkg/l5/ocr/router.py": "OCR = 1\n",  # router.py 모호 후보
        "tests/pkg/l3/test_cutover.py": "def test_cutover():\n    assert True\n",
        "lib/__init__.py": "",
        "lib/stable.py": "S = 1\n",
        "lib/old_name.py": "N = 1\n",
        "docs/standard-book/03_의존성.md": "한글 파일명 문서\n",
        "docs/guide.md": "안내 — lib/stable.py\n",
        "scripts/demo/run_demo.ps1": "Write-Host demo\n",
        "CLAUDE.md": "rules v1\n",
    }
    for rel, text in base_files.items():
        _write(root, rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")

    _git(root, "checkout", "-b", "delegate")
    _write(root, RUNBOOK, RUNBOOK_TEXT)
    _write(root, "docs/guide.md", "안내(위임판) — lib/stable.py\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "delegate: runbook")
    delegate = _git(root, "rev-parse", "HEAD")

    _git(root, "checkout", "main")
    _write(root, "src/pkg/app.py", "def create_app():\n    return 200  # LOCAL 강등\n")
    _write(root, "src/pkg/l3/router.py", "SEAT = 'mid'\nDEGRADE = True\n")
    _write(root, "tests/pkg/l3/test_cutover.py", "def test_cutover():\n    assert 200\n")
    _write(root, "CLAUDE.md", "rules v2\n")
    _write(root, "docs/standard-book/03_의존성.md", "한글 파일명 문서 v2\n")
    _write(root, "docs/guide.md", "안내(main판) — lib/stable.py\n")
    _git(root, "mv", "lib/old_name.py", "lib/new_name.py")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "drift: 런타임 LOCAL 강등")
    target = _git(root, "rev-parse", "HEAD")
    return Scene(root, base, delegate, target)


@pytest.fixture
def outside(tmp_path_factory) -> Path:
    """저장소 밖 디렉터리 — `git_repo`는 tmp_path 자체라 거기 쓰면 작업 트리 안이 된다."""
    return tmp_path_factory.mktemp("artifact")


def _judge_text(scene: Scene, outside: Path, capsys, text: str, *extra: str):
    """저장소 밖 임시 파일에 산출물 본문을 쓰고 판정한다(작업 트리 산출물 경로)."""
    artifact = outside / "artifact.md"
    artifact.write_text(text, encoding="utf-8")
    return _run_json(
        capsys,
        "--repo",
        str(scene.root),
        "--delegate-base",
        scene.base,
        "--target",
        scene.target,
        *extra,
        str(artifact),
    )


# ── ③ 실사례 ──────────────────────────────────────────────────────────────
@pytest.mark.skipif(
    not _has_commits(_REAL_BASE, _REAL_TARGET, _REAL_ARTIFACT_REF, _REAL_ARCH69),
    reason=_SKIP_REASON,
)
class TestRealCaseArch71:
    """위임 기준 ab9f29f2 → 대상 c13c04ed, 산출물 = 4dc0609f의 런북."""

    def test_stale_runbook_intersection_detected(self, capsys):
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(_REPO_ROOT),
            "--delegate-base",
            _REAL_BASE,
            "--target",
            _REAL_TARGET,
            "--artifact-ref",
            _REAL_ARTIFACT_REF,
            _REAL_RUNBOOK,
        )
        assert code == pf.EXIT_STALE
        hits = _paths(data)
        assert _REAL_EXPECTED <= hits, hits
        # 실측(태스크 notes): 단순 경로 추출로도 CLAUDE.md까지 4건이 걸린다 — CLAUDE.md는
        # 산출물에 파일명으로만 적혀 있어 파일명 매칭이 없으면 빠진다.
        assert "CLAUDE.md" in hits
        # app.py는 백틱 단독 파일명으로 참조됐다 — 파일명 매칭의 실사례.
        by_path = {item["path"]: item for item in data["intersection"]}
        assert "app.py" in by_path["src/backend/whymath_backend/app.py"]["referenced_as"]
        for path in _REAL_EXPECTED:
            assert any(c.startswith(_REAL_ARCH69) for c in by_path[path]["commits"]), path

    def test_control_target_equals_base_is_fresh(self, capsys):
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(_REPO_ROOT),
            "--delegate-base",
            _REAL_BASE,
            "--target",
            _REAL_BASE,
            "--artifact-ref",
            _REAL_ARTIFACT_REF,
            _REAL_RUNBOOK,
        )
        assert code == pf.EXIT_FRESH
        assert data["drift_count"] == 0
        assert data["intersection"] == []
        assert data["refs"]["judged"] > 0  # 참조는 있었다 — 공허한 0이 아니다


@pytest.mark.skipif(
    not _has_commits(_REAL_BASE, _REAL_TARGET, _REAL_MAIN_ARTIFACT_REF), reason=_SKIP_REASON
)
class TestRealCaseMainVersion:
    """main에 머지된 정정본을 산출물로 — CI(fetch-depth: 0)에서도 도는 실사례 판본.

    정정본도 같은 파일을 참조하므로 같은 교집합이 나온다. 도구는 이름만 보므로 "서술이 여전히
    참인가"는 사람이 커밋을 읽어 판정한다 — 여기서 동결하는 것은 교집합 계산 자체다.
    """

    def test_same_intersection_from_main_runbook(self, capsys):
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(_REPO_ROOT),
            "--delegate-base",
            _REAL_BASE,
            "--target",
            _REAL_TARGET,
            "--artifact-ref",
            _REAL_MAIN_ARTIFACT_REF,
            _REAL_RUNBOOK,
        )
        assert code == pf.EXIT_STALE
        assert _REAL_EXPECTED | {"CLAUDE.md"} <= _paths(data)


# ── ③ 합성 저장소 — 같은 형태를 항상 검사 ──────────────────────────────────
class TestSyntheticShape:
    def test_stale_artifact_detected(self, scene: Scene, capsys):
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--target",
            scene.target,
            "--artifact-ref",
            scene.delegate,
            RUNBOOK,
        )
        assert code == pf.EXIT_STALE
        assert _paths(data) == _SYNTH_EXPECTED
        by_path = {item["path"]: item for item in data["intersection"]}
        assert by_path["src/pkg/app.py"]["referenced_as"] == ["app.py"]
        assert by_path["src/pkg/l3/router.py"]["referenced_as"] == ["l3/router.py"]
        # 그 경로를 바꾼 커밋이 함께 나온다
        assert by_path["src/pkg/app.py"]["commits"][0].startswith(scene.target[:7])
        assert "drift" in by_path["src/pkg/app.py"]["commits"][0]
        # 무변경 참조·저장소 밖 참조는 교집합에 들어오지 않는다
        assert "lib/stable.py" not in by_path
        assert "response.json" in data["refs"]["outside_tokens"]
        assert data["refs"]["unique"] == 5  # app.py·l3/router.py·test_cutover·stable·CLAUDE

    def test_control_target_equals_base_is_fresh(self, scene: Scene, capsys):
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--target",
            scene.base,
            "--artifact-ref",
            scene.delegate,
            RUNBOOK,
        )
        assert code == pf.EXIT_FRESH
        assert data["intersection"] == [] and data["unknown"] == []
        assert data["refs"]["judged"] == 5

    def test_default_target_is_head(self, scene: Scene, capsys):
        """`--target` 생략 = HEAD. 기본값이 위임 기준이면 변경 0건으로 늘 '신선'이 된다."""
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--artifact-ref",
            scene.delegate,
            RUNBOOK,
        )
        assert data["target"] == scene.target
        assert data["target_is_default"] is True
        assert code == pf.EXIT_STALE
        assert _paths(data) == _SYNTH_EXPECTED

    def test_cli_process_exit_code_and_text(self, scene: Scene):
        """스크립트 진입점 그대로 — 종료 코드와 사람이 읽는 출력."""
        proc = subprocess.run(
            [
                sys.executable,
                str(_TOOL),
                "--delegate-base",
                scene.base,
                "--target",
                scene.target,
                "--artifact-ref",
                scene.delegate,
                RUNBOOK,
            ],
            cwd=scene.root,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
        )
        assert proc.returncode == pf.EXIT_STALE, proc.stderr
        assert "교집합 4건" in proc.stdout
        assert "src/pkg/l3/router.py" in proc.stdout
        assert scene.target[:7] in proc.stdout
        assert "모름 0건" in proc.stdout  # 0이어도 센 값을 보인다
        assert "판정: exit 1" in proc.stdout


# ── ② 0건 가드 ─────────────────────────────────────────────────────────────
class TestZeroGuard:
    def test_no_path_reference_is_unjudgeable(self, scene: Scene, outside: Path, capsys):
        text = "경로가 없는 산문이다. 버전 v1.2.3, 비용 8.61168, 멤버 호출 .Count 뿐이다.\n"
        code, data, _ = _judge_text(scene, outside, capsys, text)
        assert code == pf.EXIT_UNJUDGEABLE
        assert data["refs"]["judged"] == 0
        assert data["refs"]["tokens"] == 0

    def test_only_outside_references_is_unjudgeable(self, scene: Scene, outside: Path, capsys):
        """참조는 뽑혔지만 전부 저장소 밖 — 판정 대상 0건은 통과가 아니다."""
        text = "출력은 response.json 과 out/report.txt 에 쓴다.\n"
        code, data, _ = _judge_text(scene, outside, capsys, text)
        assert code == pf.EXIT_UNJUDGEABLE
        assert data["refs"]["outside"] == 2
        assert data["refs"]["judged"] == 0

    def test_zero_message_in_text_output(self, scene: Scene, outside: Path, capsys):
        artifact = outside / "empty.md"
        artifact.write_text("아무 경로도 없다\n", encoding="utf-8")
        code = pf.main(
            [
                "--repo",
                str(scene.root),
                "--delegate-base",
                scene.base,
                "--target",
                scene.target,
                str(artifact),
            ]
        )
        out = capsys.readouterr().out
        assert code == pf.EXIT_UNJUDGEABLE
        assert "판정 대상 0건" in out
        assert "판정: exit 2" in out


# ── ② 파일명 매칭·모름 ─────────────────────────────────────────────────────
class TestFilenameMatching:
    def test_bare_filename_only_reference_detected(self, scene: Scene, outside: Path, capsys):
        code, data, _ = _judge_text(scene, outside, capsys, "`app.py`만 바꾼다.\n")
        assert code == pf.EXIT_STALE
        assert _paths(data) == {"src/pkg/app.py"}

    def test_ambiguous_with_changed_candidate_is_unknown(self, scene: Scene, outside: Path, capsys):
        """`router.py` → 후보 2건 중 1건 변경 — '모름'으로 따로 세고 0으로 접지 않는다."""
        code, data, _ = _judge_text(scene, outside, capsys, "`router.py`를 본다.\n")
        assert data["intersection"] == []
        assert len(data["unknown"]) == 1
        unknown = data["unknown"][0]
        assert unknown["token"] == "router.py"
        assert unknown["candidates"] == ["src/pkg/l3/router.py", "src/pkg/l5/ocr/router.py"]
        assert unknown["changed_candidates"] == ["src/pkg/l3/router.py"]
        assert code == pf.EXIT_STALE

    def test_ambiguous_all_unchanged_is_fresh_and_counted(
        self, scene: Scene, outside: Path, capsys
    ):
        """전 후보가 무변경이면 어느 파일이든 안 바뀌었다 — 판정 가능(무변경), 수는 보인다."""
        code, data, _ = _judge_text(scene, outside, capsys, "각 `__init__.py`는 비어 있다.\n")
        assert code == pf.EXIT_FRESH
        assert data["unknown"] == []
        assert [r["token"] for r in data["ambiguous_unchanged"]] == ["__init__.py"]
        assert data["refs"]["ambiguous"] == 1


# ── 경로 형태 ──────────────────────────────────────────────────────────────
class TestPathForms:
    def test_korean_path(self, scene: Scene, outside: Path, capsys):
        text = "문서 `docs/standard-book/03_의존성.md`를 따른다.\n"
        code, data, _ = _judge_text(scene, outside, capsys, text)
        assert code == pf.EXIT_STALE
        assert _paths(data) == {"docs/standard-book/03_의존성.md"}

    def test_windows_and_absolute_paths(self, scene: Scene, outside: Path, capsys):
        text = (
            "PS> .\\scripts\\demo\\run_demo.ps1\n"
            "PS> python C:\\Users\\kiki\\WhyMath\\lib\\stable.py\n"
            "$ python /home/user/WhyMath/src/pkg/app.py\n"
        )
        code, data, _ = _judge_text(scene, outside, capsys, text)
        assert code == pf.EXIT_STALE
        assert _paths(data) == {"src/pkg/app.py"}
        assert data["refs"]["unique"] == 3  # run_demo.ps1·stable.py·app.py 모두 풀림

    def test_module_path(self, scene: Scene, outside: Path, capsys):
        text = "```python\nfrom pkg.l3.router import SEAT\nimport json.decoder\n```\n"
        code, data, _ = _judge_text(scene, outside, capsys, text)
        assert code == pf.EXIT_STALE
        assert _paths(data) == {"src/pkg/l3/router.py"}

    def test_renamed_old_path_detected(self, scene: Scene, outside: Path, capsys):
        """기준 이후 개명된 파일의 옛 경로 — `--no-renames`가 없으면 diff는 새 이름만 낸다."""
        code, data, _ = _judge_text(scene, outside, capsys, "`lib/old_name.py`를 고친다.\n")
        assert code == pf.EXIT_STALE
        assert _paths(data) == {"lib/old_name.py"}
        # 변별력: 개명 탐지가 켜진 diff는 이 경로를 내지 않는다(픽스처가 그 절을 밟는다)
        renamed = _git(
            scene.root, "-c", "diff.renames=true", "diff", "--name-only", scene.base, scene.target
        ).splitlines()
        assert "lib/old_name.py" not in renamed

    def test_token_boundaries(self):
        text = (
            "`app.py`의 설정과 l3/router.py에서 본다. "
            "https://github.com/o/r/blob/main/x.py 는 URL이다. "
            "v1.2.3 · 8.61168 · .Count · src/pkg/l5/ocr/router.py\n"
        )
        tokens = [t for t, _ in pf.extract_tokens(text)]
        assert "app.py" in tokens
        assert "l3/router.py" in tokens
        assert "src/pkg/l5/ocr/router.py" in tokens
        assert "router.py" not in tokens  # 토큰 중간에서 시작하지 않는다
        assert not any("github" in t or t.endswith("x.py") for t in tokens)
        assert not any(t.startswith(("1.", "8.", "v1")) for t in tokens)


# ── 대상에 이식 자신이 들어 있는 경우 · 산출물 자체 변경 ──────────────────────
class TestSelfInclusion:
    def test_uncommitted_port_is_judged(self, scene: Scene, capsys):
        """① 흐름 — git apply만 한 상태(미커밋)에서 대상=HEAD로 판정한다."""
        _write(scene.root, RUNBOOK, RUNBOOK_TEXT)
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            str(scene.root / RUNBOOK),
        )
        assert code == pf.EXIT_STALE
        assert _paths(data) == _SYNTH_EXPECTED
        assert data["self_included"] == []

    def test_committed_port_is_refused(self, scene: Scene, capsys):
        """이식을 커밋한 뒤 대상=HEAD면 이식 자신이 변경 목록에 섞인다 — exit 2로 멈춘다."""
        _write(scene.root, RUNBOOK, RUNBOOK_TEXT)
        _git(scene.root, "add", "-A")
        _git(scene.root, "commit", "-m", "port: runbook")
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            str(scene.root / RUNBOOK),
        )
        assert code == pf.EXIT_UNJUDGEABLE
        assert data["self_included"] == [RUNBOOK]
        # 사람이 읽는 출력도 판정 불가와 오염 사실을 말한다(교집합을 참 드리프트로 읽지 않게)
        assert (
            pf.main(
                [
                    "--repo",
                    str(scene.root),
                    "--delegate-base",
                    scene.base,
                    str(scene.root / RUNBOOK),
                ]
            )
            == 2
        )
        text = capsys.readouterr().out
        assert "대상에 이식 자신이 들어 있다" in text and "이식 자신이 섞인 값" in text
        # 해법대로 이식 직전 커밋을 대상으로 주면 참 드리프트만 판정된다
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--target",
            "HEAD~1",
            str(scene.root / RUNBOOK),
        )
        assert code == pf.EXIT_STALE
        assert _paths(data) == _SYNTH_EXPECTED

    def test_artifact_changed_on_target_is_stale(self, scene: Scene, capsys):
        """위임과 main이 같은 파일을 따로 고쳤다 — 참조는 무변경이어도 산출물 자체가 낡았다."""
        code, data, _ = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--target",
            scene.target,
            "--artifact-ref",
            scene.delegate,
            "docs/guide.md",
        )
        assert data["intersection"] == []
        assert data["artifact_self_changed"] == ["docs/guide.md"]
        assert code == pf.EXIT_STALE


# ── ② 사용 오류 ────────────────────────────────────────────────────────────
class TestUsageErrors:
    def test_unknown_commit(self, scene: Scene, capsys):
        code, data, err = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            "0" * 40,
            "--artifact-ref",
            scene.delegate,
            RUNBOOK,
        )
        assert code == pf.EXIT_UNJUDGEABLE
        assert data is None
        assert "커밋을 찾을 수 없다" in err

    def test_missing_artifact_file(self, scene: Scene, outside: Path, capsys):
        code, data, err = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            str(outside / "없는파일.md"),
        )
        assert code == pf.EXIT_UNJUDGEABLE
        assert "산출물 파일이 없다" in err

    def test_artifact_absent_at_ref(self, scene: Scene, capsys):
        code, _, err = _run_json(
            capsys,
            "--repo",
            str(scene.root),
            "--delegate-base",
            scene.base,
            "--artifact-ref",
            scene.base,
            RUNBOOK,
        )
        assert code == pf.EXIT_UNJUDGEABLE
        assert "산출물이" in err and "없다" in err

    def test_missing_required_arguments(self, capsys):
        with pytest.raises(SystemExit) as exc:
            pf.main(["docs/x.md"])  # --delegate-base 없음
        assert exc.value.code == pf.EXIT_UNJUDGEABLE
        with pytest.raises(SystemExit) as exc:
            pf.main(["--delegate-base", "HEAD"])  # 산출물 없음
        assert exc.value.code == pf.EXIT_UNJUDGEABLE

    def test_not_a_repository(self, outside: Path, capsys):
        """`outside`는 git 저장소가 아니다(tmp_path_factory 디렉터리)."""
        artifact = outside / "a.md"
        artifact.write_text("`app.py`\n", encoding="utf-8")
        code, _, err = _run_json(
            capsys, "--repo", str(outside), "--delegate-base", "HEAD", str(artifact)
        )
        assert code == pf.EXIT_UNJUDGEABLE
        assert "사용 오류" in err


# ── ④ 집행 지점 — drive.md 배선 동결 ───────────────────────────────────────
_FENCE_RE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)
_TOOL_ARGV = ["python3", "scripts/harness/port_freshness.py"]


def _port_commands(markdown: str) -> list[list[str]]:
    """bash 펜스 안의 **실행 줄**에서 port_freshness 호출의 인자 목록을 뽑는다.

    산문 속 언급·주석 줄·다른 언어 펜스는 세지 않는다 — "문서에 이름이 있다"가 아니라
    "절차가 이 명령을 실행하게 한다"를 묻는다.
    """
    commands: list[list[str]] = []
    for match in _FENCE_RE.finditer(markdown):
        if match.group(1) not in ("bash", "sh", "shell"):
            continue
        for line in match.group(2).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                argv = shlex.split(stripped, comments=True)
            except ValueError:
                continue  # 다른 명령의 따옴표 불균형 — 이 명령이 깨졌다면 아래 단언이 잡는다
            if argv[:2] == _TOOL_ARGV:
                commands.append(argv[2:])
    return commands


class TestDriveWiring:
    def _parsed(self):
        text = _DRIVE_DOC.read_text(encoding="utf-8")
        return [pf.build_parser().parse_args(argv) for argv in _port_commands(text)]

    def test_drive_runs_both_checks(self):
        """이식 직후(대상 기본값 HEAD) 1회 · PR 직전(origin/main) 1회 — 이 순서로."""
        parsed = self._parsed()
        targets = [ns.target for ns in parsed]
        assert None in targets, "이식 직후(대상 = 브랜치 HEAD) 판정이 drive.md 절차에 없다"
        assert "origin/main" in targets, "PR 직전(origin/main) 판정이 drive.md 절차에 없다"
        assert targets.index(None) < targets.index("origin/main")
        for ns in parsed:
            assert ns.delegate_base and ns.artifacts  # 도구 자신의 파서가 받아들이는 형태

    def test_wiring_lives_in_the_port_step(self):
        """명령이 위임·이식 절에 있다 — 다른 절(검증·완료)에 흩어지면 이식 순간에 읽히지 않는다."""
        text = _DRIVE_DOC.read_text(encoding="utf-8")
        section = text.split("**3a. 위임 산출물 이식", 1)
        assert len(section) == 2, "drive.md에 3a 위임 산출물 이식 절이 없다"
        body = section[1].split("\n**4.", 1)[0]
        assert len(_port_commands(body)) >= 2

    def test_extractor_discriminates(self):
        """추출기 자신의 변별력 — 산문 언급·주석·다른 펜스는 명령으로 세지 않는다."""
        cmd = "python3 scripts/harness/port_freshness.py --delegate-base abc x.md"
        prose_only = f"이식 뒤에는 `{cmd}`를 돌린다.\n"
        commented = f"```bash\n# {cmd}\n```\n"
        other_fence = f"```powershell\n{cmd}\n```\n"
        real = f"```bash\n{cmd}\n```\n"
        assert _port_commands(prose_only) == []
        assert _port_commands(commented) == []
        assert _port_commands(other_fence) == []
        assert _port_commands(real) == [["--delegate-base", "abc", "x.md"]]
