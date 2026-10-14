"""[OPS-135] ghcr 미러 도구(`scripts/ops/mirror_ci_images.py`) 계약 동결 — 네트워크 없이 돈다.

무엇을 동결하는가
----------------
① 입력 검증 — 목록의 source는 `저장소:태그`만 받는다. 호스트·digest·태그 생략(암묵 latest)·0건은
   설정 실패(종료 코드 2)다. 빈 목록이 "미러를 했다"로 읽히면 공허 통과다.
② 복사 순서 — digest를 **먼저 해석**하고 그 digest(`저장소@sha256:…`)로 복사한다. 태그로 복사하면
   해석과 복사 사이에 태그가 움직일 수 있다.
③ 복사 후 검증 — 사본의 플랫폼 digest 집합이 source와 다르면 실패다(복사 성공 ≠ 내용 동일).
④ 재시도 — 일시 실패는 백오프로 재시도하고, 전체 예산을 넘으면 접으며, 끝내 실패하면 종료 코드 1이다.
⑤ 워크플로 배선 — 쓰기 권한(`packages: write`)은 미러 잡에만 있고, 목록 변경이 트리거가 되며,
   스크립트를 실제로 부른다. 소유자 리터럴이 없다.

외부 호출은 가짜 레지스트리(`_FakeRegistry`)로 대체한다 — 실제 docker는 부르지 않는다
(R12-01: 단위 테스트는 네트워크에 접속하지 않는다).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "ops" / "mirror_ci_images.py"
_WORKFLOW = _ROOT / ".github" / "workflows" / "mirror-ci-images.yml"
_MANIFEST = _ROOT / "infra" / "ci" / "mirrored-images.yaml"

_spec = importlib.util.spec_from_file_location("mirror_ci_images_under_test", _SCRIPT)
assert _spec and _spec.loader
mirror = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mirror
_spec.loader.exec_module(mirror)

_D_SRC = "sha256:" + "a" * 64
_D_AMD = "sha256:" + "1" * 64
_D_ARM = "sha256:" + "2" * 64


class _FakeRegistry:
    """imagetools 호출을 흉내 내는 가짜 — 호출 기록을 남기고, 지정한 횟수만큼 먼저 실패시킨다."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail_first: dict[str, int] = {}  # 부분 문자열 → 실패시킬 횟수
        self.dest_platforms: list[str] = [_D_AMD, _D_ARM]
        self.src_platforms: list[str] = [_D_AMD, _D_ARM]
        self.digest_output: str = _D_SRC + "\n"

    def __call__(self, cmd, timeout):
        args = list(cmd)
        self.calls.append(args)
        joined = " ".join(args)
        for key, left in list(self.fail_first.items()):
            if key in joined and left > 0:
                self.fail_first[key] = left - 1
                return subprocess.CompletedProcess(
                    args, 1, "", "toomanyrequests: You have reached your pull rate limit\n"
                )
        if "--format" in args:
            return subprocess.CompletedProcess(args, 0, self.digest_output, "")
        if "--raw" in args:
            platforms = (
                self.dest_platforms if args[-1].startswith("ghcr.io/") else self.src_platforms
            )
            doc = {"manifests": [{"digest": d} for d in platforms]}
            return subprocess.CompletedProcess(args, 0, json.dumps(doc), "")
        return subprocess.CompletedProcess(args, 0, "", "")  # create


def _env(deadline: float = 10_000.0):
    slept: list[float] = []
    return slept, {
        "sleep": slept.append,
        "clock": lambda: 0.0,
        "deadline": deadline,
        "log": lambda _msg: None,
    }


_SRC = mirror.parse_source("pgvector/pgvector:pg16")


# ── ① 입력 검증 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, name, tag",
    [
        ("pgvector/pgvector:pg16", "pgvector", "pg16"),
        ("neo4j:5", "neo4j", "5"),
        ("python:3.12-slim", "python", "3.12-slim"),
    ],
)
def test_parse_source_accepts_repo_and_tag(raw: str, name: str, tag: str) -> None:
    src = mirror.parse_source(raw)
    assert (src.name, src.tag) == (name, tag)


@pytest.mark.parametrize(
    "raw",
    [
        "neo4j",  # 태그 생략 = 암묵 latest
        "ghcr.io/x/y:1",  # 레지스트리 호스트
        "localhost/x:1",
        "python@sha256:" + "a" * 64,  # digest 고정 표기
        "Python:3.12",  # 대문자 저장소
        "",
        "neo4j:",
    ],
)
def test_parse_source_rejects_malformed(raw: str) -> None:
    with pytest.raises(mirror.ConfigError):
        mirror.parse_source(raw)


def test_mirror_ref_shape_and_lowercase_owner_only() -> None:
    assert (
        mirror.mirror_ref("kiki-s-broom", _SRC)
        == "ghcr.io/kiki-s-broom/whymath-ci-mirror/pgvector:pg16"
    )
    with pytest.raises(mirror.ConfigError):
        mirror.mirror_ref("Kiki-S-Broom", _SRC)  # ci.yml은 대소문자를 바꿀 수 없다


def test_real_manifest_loads_with_expected_images() -> None:
    sources = mirror.load_sources(_MANIFEST)
    assert {s.raw for s in sources} == {"pgvector/pgvector:pg16", "neo4j:5", "python:3.12-slim"}


def test_empty_or_unreadable_manifest_is_config_failure(tmp_path: Path) -> None:
    empty = tmp_path / "e.yaml"
    empty.write_text("sources: []\n", encoding="utf-8")
    with pytest.raises(mirror.ConfigError):
        mirror.load_sources(empty)  # 0건은 통과가 아니다
    with pytest.raises(mirror.ConfigError):
        mirror.load_sources(tmp_path / "없음.yaml")
    bad = tmp_path / "b.yaml"
    bad.write_text("sources: [unclosed\n", encoding="utf-8")
    with pytest.raises(mirror.ConfigError):
        mirror.load_sources(bad)


def test_name_collision_is_config_failure(tmp_path: Path) -> None:
    dup = tmp_path / "d.yaml"
    dup.write_text("sources:\n  - a/pgvector:pg16\n  - b/pgvector:pg16\n", encoding="utf-8")
    with pytest.raises(mirror.ConfigError):
        mirror.load_sources(dup)


# ── ② 복사 순서 · ③ 복사 후 검증 ───────────────────────────────────────────


def test_copy_resolves_digest_first_then_copies_by_digest() -> None:
    reg = _FakeRegistry()
    _slept, kw = _env()
    digest, dest = mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)
    assert digest == _D_SRC
    kinds = [c[3] for c in reg.calls]  # docker buildx imagetools <kind>
    assert kinds[0] == "inspect" and "--format" in reg.calls[0]
    create = next(c for c in reg.calls if c[3] == "create")
    # 태그가 아니라 해석한 digest로 복사한다 — 이것이 TOCTOU를 막는다.
    assert create[-1] == f"pgvector/pgvector@{_D_SRC}"
    assert create[create.index("--tag") + 1] == dest
    assert kinds.index("create") > 0, "digest 해석이 복사보다 먼저여야 한다"


def test_verification_failure_when_platform_digests_differ() -> None:
    reg = _FakeRegistry()
    reg.dest_platforms = [_D_AMD]  # arm64가 빠진 반쪽 사본
    _slept, kw = _env()
    with pytest.raises(mirror.CopyError, match="다르다"):
        mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)


def test_malformed_digest_is_rejected_not_used() -> None:
    reg = _FakeRegistry()
    reg.digest_output = "\n"  # 빈 응답을 digest로 쓰면 `pgvector@`로 복사를 시도한다
    _slept, kw = _env(deadline=0.0)
    with pytest.raises(mirror.CopyError, match="digest 형식"):
        mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)
    assert not any(c[3] == "create" for c in reg.calls)


# ── ④ 재시도 ───────────────────────────────────────────────────────────────


def test_transient_failure_is_retried_with_backoff_then_succeeds() -> None:
    reg = _FakeRegistry()
    reg.fail_first["--format"] = 2  # 해석이 2번 한도에 걸린다
    slept, kw = _env()
    digest, _dest = mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)
    assert digest == _D_SRC
    assert slept == list(mirror.RETRY_DELAYS[:2])  # 15s, 45s — 지수 백오프


def test_gives_up_after_all_attempts_and_keeps_the_cause() -> None:
    reg = _FakeRegistry()
    reg.fail_first["create"] = 99
    slept, kw = _env()
    with pytest.raises(mirror.CopyError, match="toomanyrequests"):
        mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)
    assert slept == list(mirror.RETRY_DELAYS)  # 시도 횟수 = 간격 + 1


def test_deadline_stops_retrying_early() -> None:
    reg = _FakeRegistry()
    reg.fail_first["--format"] = 99
    slept, kw = _env(deadline=10.0)  # 첫 간격(15s)부터 예산 초과
    with pytest.raises(mirror.CopyError):
        mirror.mirror_one(reg, "kiki-s-broom", _SRC, **kw)
    assert slept == []


# ── main 종료 코드 ──────────────────────────────────────────────────────────


def _main(args: list[str], reg: _FakeRegistry | None = None) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = mirror.main(
        args,
        runner=reg or _FakeRegistry(),
        sleep=lambda _s: None,
        clock=lambda: 0.0,
        out=lines.append,
    )
    return code, lines


def test_main_dry_run_prints_plan_without_calling_docker() -> None:
    reg = _FakeRegistry()
    code, lines = _main(["--owner", "kiki-s-broom", "--dry-run", "--manifest", str(_MANIFEST)], reg)
    assert code == 0 and reg.calls == []
    assert any("ghcr.io/kiki-s-broom/whymath-ci-mirror/neo4j:5" in x for x in lines)


def test_main_exit_2_on_bad_owner_and_missing_owner() -> None:
    assert _main(["--owner", "Kiki", "--manifest", str(_MANIFEST)])[0] == 2
    assert _main(["--owner", "", "--manifest", str(_MANIFEST)])[0] == 2


def test_main_exit_1_when_any_image_fails_and_exit_0_when_all_succeed() -> None:
    ok_code, _ = _main(["--owner", "kiki-s-broom", "--manifest", str(_MANIFEST)])
    assert ok_code == 0
    reg = _FakeRegistry()
    reg.dest_platforms = [_D_AMD]  # 모든 사본이 검증에서 어긋난다
    code, lines = _main(["--owner", "kiki-s-broom", "--manifest", str(_MANIFEST)], reg)
    assert code == 1
    assert any("실패 3/3건" in x for x in lines)


# ── ⑤ 워크플로 배선 ─────────────────────────────────────────────────────────


def _workflow() -> dict:
    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML은 키 `on`을 True로 읽는다(YAML 1.1) — 둘 다 받는다.
    doc["_on"] = doc.get("on", doc.get(True))
    return doc


def test_workflow_write_permission_only_on_mirror_job() -> None:
    doc = _workflow()
    assert doc["permissions"] == {"contents": "read"}  # 기본은 읽기 전용
    assert doc["jobs"]["mirror"]["permissions"]["packages"] == "write"


def test_workflow_triggers_cover_schedule_dispatch_and_manifest_change() -> None:
    on = _workflow()["_on"]
    assert "schedule" in on and "workflow_dispatch" in on
    paths = on["push"]["paths"]
    assert "infra/ci/mirrored-images.yaml" in paths  # 이미지를 더하면 사본이 곧바로 생긴다
    assert on["push"]["branches"] == ["main"]


def test_workflow_actually_runs_the_script_without_owner_literal() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "python3 scripts/ops/mirror_ci_images.py" in text
    steps = _workflow()["jobs"]["mirror"]["steps"]
    run_text = "\n".join(str(s.get("run", "")) for s in steps)
    env_text = json.dumps([s.get("env", {}) for s in steps])
    # 소유자는 컨텍스트에서 받는다 — 실행 표면에 리터럴이 없다(조직 이관 선례).
    assert "kiki-s-broom" not in run_text and "kiki-s-broom" not in env_text
    assert "github.repository_owner" in env_text


def test_workflow_login_passes_token_via_stdin_not_argv() -> None:
    steps = _workflow()["jobs"]["mirror"]["steps"]
    login = next(s for s in steps if "docker login" in str(s.get("run", "")))
    assert "--password-stdin" in login["run"]
    assert "-p " not in login["run"] and "--password " not in login["run"]
