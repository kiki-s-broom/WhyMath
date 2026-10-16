"""[OPS-135] CI 컨테이너 이미지 공급원 계약 — 새 Docker Hub 익명 참조가 들어오면 RED.

왜 이 테스트가 있는가
--------------------
2026-10-09 CI가 Docker Hub 익명 pull 한도(`toomanyrequests`)에 걸려 PR #1529가 머지 큐에서 3회
탈락했다. 게이트 `G-ops135-ci-image-source-decision`에서 Kiki가 ①ghcr.io 미러를 택했고, CI가 쓰는
이미지는 전부 `infra/ci/mirrored-images.yaml`의 사본(`ghcr.io/<소유자>/whymath-ci-mirror/…`)이어야
한다. 이 파일은 그 계약을 **정본화가 아니라 집행**한다 — 누군가 새 잡에 `redis:7` 같은 이미지를
쓰면 한도 문제가 조용히 되돌아오기 때문이다.

무엇을 전수로 읽는가 (금지 문자열 열거가 아니라 *구성된 참조*를 읽는다)
------------------------------------------------------------------------
① `.github/workflows/*.yml`을 YAML로 파싱해 `jobs.*.services.*.image`·`jobs.*.container`·
   `uses: docker://…`, 그리고 `run` 스크립트의 `docker run|create|pull|build` 인자를 뽑는다.
② `Dockerfile`의 `FROM`(첫 FROM 앞 `ARG` 기본값으로 풀어서)과 `# syntax=` 지시어를 뽑는다.

판정
----
- 서비스·컨테이너 이미지는 **미러 사본**이어야 하고 `credentials`(`secrets.GITHUB_TOKEN`)와 `packages`
  읽기 권한이 있어야 한다(사본은 비공개 패키지다 — 2026-10-14 실측: 익명 읽기 401).
- `docker run|create`는 미러 사본이거나 이 저장소가 빌드한 로컬 이미지(`whymath-*:태그`)만 쓴다.
  `docker pull`·`uses: docker://`는 미러 사본만.
- `Dockerfile`의 `FROM`이 Docker Hub 기본값을 `ARG`로 받으면, 그 Dockerfile을 빌드하는 **모든**
  `docker build`가 `--build-arg 이름=<미러 사본>`을 넘겨야 하고, 같은 잡에서 그 앞에
  `docker login ghcr.io … --password-stdin`이 있어야 한다. `# syntax=` 지시어는(프런트엔드 이미지를
  Docker Hub에서 따로 받는다) 미러 사본을 가리키지 않는 한 금지다.
- **스캔 0건은 실패다** — 대상을 하나도 못 찾은 전수 가드는 공허하게 통과한다.

한계(정직 고지): 셸 변수로 조립한 이미지(`docker run "$IMG"`)와 `docker compose`가 읽는 이미지,
`actions/*` 액션 내부의 이미지 pull은 정적으로 풀지 않는다. 운영 compose의 이미지 참조는 CI가
아니라서 범위 밖이다(태스크 OPS-135 acceptance ②).
"""

from __future__ import annotations

import importlib.util
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIR = _ROOT / ".github" / "workflows"
_DOCKERFILE = _ROOT / "Dockerfile"
_SCRIPT = _ROOT / "scripts" / "ops" / "mirror_ci_images.py"
_MANIFEST = _ROOT / "infra" / "ci" / "mirrored-images.yaml"

_spec = importlib.util.spec_from_file_location("mirror_ci_images_for_sources_test", _SCRIPT)
assert _spec and _spec.loader
mirror = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mirror
_spec.loader.exec_module(mirror)

_OWNER = "${OWNER}"
_EXPR_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")
_LOCAL_IMAGE_RE = re.compile(r"^whymath-[a-z0-9-]+:")

# `docker run|create`에서 값을 따로 받는 옵션 — 다음 토큰을 이미지로 오인하지 않게 건너뛴다.
_VALUE_OPTS = frozenset(
    {
        "-p", "--publish", "-v", "--volume", "-e", "--env", "--name", "--network", "--net",
        "-w", "--workdir", "-u", "--user", "--entrypoint", "--env-file", "-l", "--label",
        "--add-host", "--mount", "--cap-add", "--cap-drop", "-m", "--memory", "--cpus",
        "--restart", "--platform", "-h", "--hostname", "--ip", "--log-driver", "--tmpfs",
        "--health-cmd", "--health-interval", "--health-timeout", "--health-retries",
        "--pull", "--cidfile", "--device", "--dns", "--group-add", "--security-opt",
    }
)  # fmt: skip


def _normalize(text: str) -> str:
    """`${{ … }}` 표현식을 공백 없는 토큰으로 바꾼다 — 소유자만 `${OWNER}`로 보존한다."""

    def sub(m: re.Match[str]) -> str:
        return _OWNER if m.group(1).strip() == "github.repository_owner" else "${EXPR}"

    return _EXPR_RE.sub(sub, text)


def allowed_mirror_refs() -> set[str]:
    """목록(`infra/ci/mirrored-images.yaml`)에서 계산한 정규화된 사본 주소 집합."""
    refs = set()
    for source in mirror.load_sources(_MANIFEST):
        refs.add(mirror.mirror_ref("owner", source).replace("ghcr.io/owner/", f"ghcr.io/{_OWNER}/"))
    return refs


@dataclass
class Scan:
    violations: list[str] = field(default_factory=list)
    services: int = 0  # 서비스·컨테이너 이미지 참조 수
    docker_cmds: int = 0  # `docker run|create|pull` 명령 수
    froms: int = 0  # Dockerfile FROM 수
    builds: int = 0  # Dockerfile을 빌드하는 docker build 수
    logins: int = 0  # 빌드 앞 ghcr.io 로그인 확인 수


def _docker_commands(run: str) -> list[tuple[str, list[str]]]:
    """run 스크립트에서 (`docker` 하위 명령, 인자 토큰) 목록을 뽑는다. 주석·파이프 앞 명령은 거른다."""
    cmds: list[tuple[str, list[str]]] = []
    for raw in _normalize(run).replace("\\\n", " ").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for seg in re.split(r"\s*(?:&&|\|\||;|\|)\s*", line):
            m = re.match(r"^docker\s+(\S+)\s*(.*)$", seg.strip())
            if not m:
                continue
            try:
                args = shlex.split(m.group(2))
            except ValueError:
                args = m.group(2).split()
            cmds.append((m.group(1), args))
    return cmds


def _image_arg(args: list[str]) -> str | None:
    """`docker run|create|pull` 인자에서 이미지 토큰(첫 비옵션)을 찾는다."""
    skip = False
    for tok in args:
        if skip:
            skip = False
            continue
        if tok.startswith("-"):
            if "=" not in tok and tok in _VALUE_OPTS:
                skip = True
            continue
        return tok
    return None


def _build_info(args: list[str]) -> tuple[str, dict[str, str]]:
    """`docker build` 인자에서 (Dockerfile 경로, build-arg 딕셔너리)를 읽는다."""
    dockerfile = "Dockerfile"
    build_args: dict[str, str] = {}
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in ("-f", "--file") and i + 1 < len(args):
            dockerfile = args[i + 1]
            i += 2
            continue
        if tok.startswith("--file="):
            dockerfile = tok.split("=", 1)[1]
        elif tok == "--build-arg" and i + 1 < len(args):
            k, _, v = args[i + 1].partition("=")
            build_args[k] = v
            i += 2
            continue
        elif tok.startswith("--build-arg="):
            k, _, v = tok.split("=", 1)[1].partition("=")
            build_args[k] = v
        i += 1
    return dockerfile, build_args


def _dockerfile_froms(text: str) -> tuple[list[tuple[str, str | None]], dict[str, str], list[str]]:
    """(FROM 목록[(풀린 참조, ARG 이름|None)], ARG 기본값, syntax 지시어 값 목록)."""
    args: dict[str, str] = {}
    aliases: set[str] = set()
    froms: list[tuple[str, str | None]] = []
    syntax: list[str] = []
    seen_from = False
    for raw in text.splitlines():
        line = raw.strip()
        sm = re.match(r"^#\s*syntax\s*=\s*(\S+)", line)
        if sm:
            syntax.append(_normalize(sm.group(1)))
            continue
        if not line or line.startswith("#"):
            continue
        head, _, rest = line.partition(" ")
        kw = head.upper()
        if kw == "ARG" and not seen_from and "=" in rest:
            name, _, default = rest.partition("=")
            args[name.strip()] = default.strip()
        elif kw == "FROM":
            seen_from = True
            toks = [t for t in rest.split() if not t.startswith("--")]
            ref = toks[0] if toks else ""
            if len(toks) >= 3 and toks[1].upper() == "AS":
                alias = toks[2]
            else:
                alias = None
            arg_name: str | None = None
            vm = re.fullmatch(r"\$\{(\w+)\}|\$(\w+)", ref)
            if vm:
                arg_name = vm.group(1) or vm.group(2)
                ref = args.get(arg_name, ref)
            if ref in aliases:
                ref = "<stage>"  # 앞 stage 참조 — 외부 이미지가 아니다
                arg_name = None
            froms.append((_normalize(ref), arg_name))
            if alias:
                aliases.add(alias)
    return froms, args, syntax


def _packages_readable(doc: dict[str, Any], job: dict[str, Any]) -> bool:
    perms = job.get("permissions", doc.get("permissions"))
    if isinstance(perms, str):
        return perms in ("read-all", "write-all")
    return isinstance(perms, dict) and perms.get("packages") in ("read", "write")


def scan(workflows: dict[str, str], dockerfile: str, allowed: set[str]) -> Scan:
    """워크플로·Dockerfile 텍스트에서 이미지 참조를 전수로 읽어 위반을 모은다(파일 접근 없음)."""
    out = Scan()
    froms, _args, syntax = _dockerfile_froms(dockerfile)

    for ref in syntax:
        if ref not in allowed:
            out.violations.append(
                f"Dockerfile: `# syntax={ref}` — 프런트엔드를 Docker Hub에서 받는다"
            )

    need_args: dict[str, str] = {}  # Docker Hub 기본값을 ARG로 받는 FROM → build-arg가 필요하다
    for ref, arg_name in froms:
        out.froms += 1
        if ref in ("<stage>", "scratch") or ref in allowed:
            continue
        if arg_name is None:
            out.violations.append(f"Dockerfile: FROM {ref} — Docker Hub 익명 참조(비미러)")
        else:
            need_args[arg_name] = ref

    for wf_name, text in sorted(workflows.items()):
        doc = yaml.safe_load(text) or {}
        for job_name, job in (doc.get("jobs") or {}).items():
            where = f"{wf_name}:{job_name}"
            readable = _packages_readable(doc, job)

            # ① 서비스 컨테이너·container: — 미러 사본 + credentials + packages 읽기
            images: list[tuple[str, Any]] = []
            container = job.get("container")
            if isinstance(container, str):
                images.append((container, None))
            elif isinstance(container, dict) and "image" in container:
                images.append((container["image"], container.get("credentials")))
            for svc in (job.get("services") or {}).values():
                images.append((svc["image"], svc.get("credentials")))
            for raw_ref, creds in images:
                out.services += 1
                ref = _normalize(str(raw_ref))
                if ref not in allowed:
                    out.violations.append(
                        f"{where}: 이미지 {ref} — 미러 사본이 아니다(Docker Hub 익명 참조)"
                    )
                    continue
                token_ok = (
                    isinstance(creds, dict)
                    and creds.get("username")
                    and "secrets.GITHUB_TOKEN" in str(creds.get("password", ""))
                )
                if not token_ok:
                    out.violations.append(
                        f"{where}: 이미지 {ref} — credentials(GITHUB_TOKEN)가 없다"
                    )
                if not readable:
                    out.violations.append(f"{where}: 이미지 {ref} — packages 읽기 권한이 없다")

            # ② 스텝: uses: docker:// 와 run 의 docker 명령
            logged_in = False
            for step in job.get("steps") or []:
                uses = str(step.get("uses", ""))
                if uses.startswith("docker://"):
                    out.docker_cmds += 1
                    ref = _normalize(uses[len("docker://") :])
                    if ref not in allowed:
                        out.violations.append(f"{where}: uses docker://{ref} — 미러 사본이 아니다")
                for sub, args in _docker_commands(str(step.get("run", ""))):
                    if sub == "login" and "ghcr.io" in args and "--password-stdin" in args:
                        logged_in = True
                    elif sub in ("run", "create", "pull"):
                        out.docker_cmds += 1
                        ref = _image_arg(args) or ""
                        local_ok = sub != "pull" and bool(_LOCAL_IMAGE_RE.match(ref))
                        if ref not in allowed and not local_ok:
                            out.violations.append(
                                f"{where}: docker {sub} {ref} — 미러 사본도 로컬 빌드도 아니다"
                            )
                    elif sub == "build":
                        target, build_args = _build_info(args)
                        if Path(target).name != "Dockerfile":
                            continue
                        out.builds += 1
                        for name, default in need_args.items():
                            value = _normalize(build_args.get(name, ""))
                            if value not in allowed:
                                out.violations.append(
                                    f"{where}: docker build에 --build-arg {name}=<미러 사본>이 없다"
                                    f"(기본값 {default}는 Docker Hub 익명 참조)"
                                )
                        if need_args:
                            if logged_in:
                                out.logins += 1
                            else:
                                out.violations.append(
                                    f"{where}: docker build 앞에 ghcr.io 로그인(--password-stdin)이 없다"
                                )
                            if not readable:
                                out.violations.append(
                                    f"{where}: docker build — packages 읽기 권한이 없다"
                                )
    return out


def _load_real() -> tuple[dict[str, str], str, set[str]]:
    workflows = {p.name: p.read_text(encoding="utf-8") for p in sorted(_WORKFLOW_DIR.glob("*.yml"))}
    return workflows, _DOCKERFILE.read_text(encoding="utf-8"), allowed_mirror_refs()


# ── 실제 저장소 ────────────────────────────────────────────────────────────


def test_real_repository_uses_only_mirror_images() -> None:
    workflows, dockerfile, allowed = _load_real()
    result = scan(workflows, dockerfile, allowed)
    assert result.violations == [], "\n".join(result.violations)


def test_scan_is_not_vacuous() -> None:
    """대상을 못 찾은 전수 가드는 공허하게 통과한다 — 알려진 하한 아래면 실패다."""
    workflows, dockerfile, allowed = _load_real()
    result = scan(workflows, dockerfile, allowed)
    assert len(workflows) >= 8, f"워크플로를 {len(workflows)}개만 읽었다"
    assert len(allowed) >= 3, "미러 목록이 비었다"
    assert (
        result.services >= 5
    ), f"서비스 이미지 참조 {result.services}건 — 5건(PG 4 + Neo4j 1) 미만"
    assert result.froms >= 2, f"Dockerfile FROM {result.froms}건"
    assert result.builds >= 1, "Dockerfile을 빌드하는 docker build를 못 찾았다"
    assert result.logins >= 1, "docker build 앞 ghcr.io 로그인을 못 찾았다"
    assert result.docker_cmds >= 1, "docker run 스모크를 못 찾았다"


# ── 결함 주입 — 각 뮤테이션이 RED이고 대조군(원본)이 GREEN ───────────────────────


def _mutate(text: str, old: str, new: str, *, expect: int = 1) -> str:
    assert text.count(old) >= expect, f"치환 대상 없음: {old!r}"
    mutated = text.replace(old, new, 1)
    assert mutated != text, "주입이 적용되지 않았다 — 정상 파일로 검사하면 통과가 검출처럼 보인다"
    return mutated


_CRED_BLOCK = (
    "        credentials:\n"
    "          username: ${{ github.actor }}\n"
    "          password: ${{ secrets.GITHUB_TOKEN }}\n"
)
_MIRROR_PG = "ghcr.io/${{ github.repository_owner }}/whymath-ci-mirror/pgvector:pg16"
_PERM_BLOCK = "    permissions:\n      contents: read\n      packages: read\n"


def _inject_old_service_image(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    wf["ci.yml"] = _mutate(wf["ci.yml"], f"image: {_MIRROR_PG}", "image: pgvector/pgvector:pg16")
    return wf, df


def _inject_delete_credentials(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    wf["ci.yml"] = _mutate(wf["ci.yml"], _CRED_BLOCK, "")
    return wf, df


def _inject_dockerfile_literal_from(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    return wf, _mutate(df, "FROM ${PYTHON_IMAGE} AS builder", "FROM python:3.12-slim AS builder")


def _inject_new_job_with_anonymous_image(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    extra = (
        "\n  new-redis-job:\n    runs-on: ubuntu-latest\n    services:\n"
        "      redis:\n        image: redis:7\n    steps:\n      - run: echo hi\n"
    )
    mutated = wf["ci.yml"].rstrip("\n") + "\n" + extra
    assert mutated != wf["ci.yml"]
    wf["ci.yml"] = mutated
    return wf, df


def _inject_remove_build_arg(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    old = "--build-arg PYTHON_IMAGE=ghcr.io/${{ github.repository_owner }}/whymath-ci-mirror/python:3.12-slim\n"
    wf["ci.yml"] = _mutate(wf["ci.yml"], "          " + old, "")
    return wf, df


def _inject_remove_login_step(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    old = 'echo "$GH_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin'
    wf["ci.yml"] = _mutate(wf["ci.yml"], old, "true")
    return wf, df


def _inject_remove_packages_permission(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    wf["ci.yml"] = _mutate(wf["ci.yml"], _PERM_BLOCK, "    permissions:\n      contents: read\n")
    return wf, df


def _inject_weekly_metrics_packages_read(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    wf["weekly-metrics.yml"] = _mutate(wf["weekly-metrics.yml"], "  packages: read\n", "")
    return wf, df


def _inject_docker_run_hub_image(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    old = "docker run -d --name whymath-ci-smoke -p 127.0.0.1:18000:8000 \\\n            whymath-backend:ci-${{ github.sha }}"
    new = "docker run -d --name whymath-ci-smoke -p 127.0.0.1:18000:8000 \\\n            redis:7"
    wf["ci.yml"] = _mutate(wf["ci.yml"], old, new)
    return wf, df


def _inject_uses_docker_scheme(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    wf = dict(wf)
    old = "      - name: Checkout\n        uses: actions/checkout@v4\n"
    new = "      - name: Hub 액션\n        uses: docker://alpine:3.20\n"
    wf["ci.yml"] = _mutate(wf["ci.yml"], old, new)
    return wf, df


def _inject_syntax_directive(wf: dict[str, str], df: str) -> tuple[dict[str, str], str]:
    mutated = "# syntax=docker/dockerfile:1\n" + df
    assert mutated != df
    return wf, mutated


_INJECTIONS = {
    "서비스 이미지를 옛 Docker Hub 참조로 되돌림": (
        _inject_old_service_image,
        "미러 사본이 아니다",
    ),
    "credentials 키 삭제": (_inject_delete_credentials, "credentials"),
    "Dockerfile FROM을 옛 참조로 되돌림": (_inject_dockerfile_literal_from, "FROM"),
    "새 잡에 익명 서비스 이미지 추가": (_inject_new_job_with_anonymous_image, "redis:7"),
    "docker build의 build-arg 삭제": (_inject_remove_build_arg, "build-arg"),
    "docker build 앞 ghcr 로그인 삭제": (_inject_remove_login_step, "로그인"),
    "잡 권한에서 packages 읽기 삭제": (_inject_remove_packages_permission, "packages 읽기"),
    "weekly-metrics 최상위 packages 읽기 삭제": (
        _inject_weekly_metrics_packages_read,
        "packages 읽기",
    ),
    "docker run에 Hub 이미지": (_inject_docker_run_hub_image, "docker run"),
    "uses: docker:// 스킴 추가": (_inject_uses_docker_scheme, "docker://"),
    "Dockerfile syntax 지시어 복귀": (_inject_syntax_directive, "syntax"),
}


@pytest.mark.parametrize("name", list(_INJECTIONS))
def test_injected_regression_is_red_and_control_is_green(name: str) -> None:
    inject, keyword = _INJECTIONS[name]
    workflows, dockerfile, allowed = _load_real()
    control = scan(workflows, dockerfile, allowed)
    assert control.violations == [], "대조군(정상 저장소)이 GREEN이 아니다"

    mutated_wf, mutated_df = inject(workflows, dockerfile)
    assert (mutated_wf, mutated_df) != (workflows, dockerfile), "주입이 적용되지 않았다"
    result = scan(mutated_wf, mutated_df, allowed)
    assert result.violations, f"{name}: 위반이 검출되지 않았다(가드가 이 회귀를 못 본다)"
    assert any(
        keyword in v for v in result.violations
    ), f"{name}: 위반은 났지만 원인이 다르다(키워드 {keyword!r}) → {result.violations}"


def test_scan_of_empty_inputs_reports_nothing_found() -> None:
    """빈 입력은 위반이 아니라 *발견 0건*으로 드러나야 한다(공허 통과 방지는 하한 테스트가 맡는다)."""
    result = scan({}, "", allowed_mirror_refs())
    assert (result.services, result.froms, result.builds) == (0, 0, 0)


def test_mirror_refs_come_from_the_manifest() -> None:
    assert allowed_mirror_refs() == {
        f"ghcr.io/{_OWNER}/whymath-ci-mirror/pgvector:pg16",
        f"ghcr.io/{_OWNER}/whymath-ci-mirror/neo4j:5",
        f"ghcr.io/{_OWNER}/whymath-ci-mirror/python:3.12-slim",
    }
