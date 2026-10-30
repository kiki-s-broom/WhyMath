#!/usr/bin/env python3
"""CI 컨테이너 이미지 ghcr.io 미러 도구 (OPS-135).

왜 필요한가
----------
2026-10-09 20:53~21:16Z 머지 큐 실행 3회가 서비스 컨테이너 초기화 단계에서 Docker Hub
`toomanyrequests: You have reached your unauthenticated pull rate limit`로 연속 실패했다
(PR #1529 CI_FAILURE 3회). GitHub 호스트 러너는 IP를 다른 사용자와 나눠 쓰므로 익명 pull 한도는
우리 호출량과 무관하게 소진된다. 러너의 자체 재시도(약 13초 3회)로는 23분 이상 지속된 한도를
넘지 못한다. 2026-10-14 Kiki가 게이트 G-ops135-ci-image-source-decision에서 ①ghcr 미러를 택했다.

무엇을 하는가
------------
`infra/ci/mirrored-images.yaml`의 각 source(Docker Hub 이미지)를
`ghcr.io/<소유자>/whymath-ci-mirror/<이름>:<태그>`로 **레지스트리 간 직접 복사**한다
(`docker buildx imagetools create` — 로컬 pull 없이 멀티 아키텍처 인덱스째 복사). 순서:

  ① source의 **digest를 먼저 해석**한다(태그는 움직이므로 이 시점의 값을 고정).
  ② 그 digest로 복사한다(`저장소@sha256:…`) — 해석과 복사 사이에 태그가 바뀌어도 어긋나지 않는다.
  ③ **복사 후 검증**: 사본 인덱스가 가리키는 플랫폼 manifest digest 집합이 source와 같은지 확인한다.
     (사본 인덱스 자체의 digest 일치는 요구하지 않는다 — 재직렬화 여부는 도구 구현 세부라서
     요구하면 정상 복사를 실패로 오판할 수 있다. 실제 이미지 내용을 정하는 것은 플랫폼 digest다.)

재시도: Docker Hub 읽기가 한도에 걸릴 수 있으므로 지수 백오프로 재시도한다. 이 도구는 주 1회·목록
변경 시에만 돌기 때문에 한도에 닿을 확률이 모든 CI 실행이 pull하던 때보다 훨씬 낮고, 닿아도
수십 분 기다릴 수 있는 잡이다(CI 큐와 달리 대기 비용이 없다).

종료 코드 (워크플로·문서가 의존한다)
------------------------------------
0 전건 성공 / 1 하나라도 복사·검증 실패 / 2 측정·설정 실패(목록 파싱 불가·소스 0건·소유자 대문자 등)

사용:
  python3 scripts/ops/mirror_ci_images.py --owner kiki-s-broom [--manifest 경로] [--dry-run]
  (--owner 생략 시 환경변수 GITHUB_REPOSITORY_OWNER)
의존: PyYAML + docker buildx(imagetools) + (복사 시) ghcr.io 로그인 상태(packages: write).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

MIRROR_HOST = "ghcr.io"
MIRROR_NAMESPACE = "whymath-ci-mirror"
DEFAULT_MANIFEST = Path("infra/ci/mirrored-images.yaml")

# 재시도 간격(초). 마지막 시도 뒤에는 기다리지 않는다 — 시도 횟수 = len + 1.
RETRY_DELAYS: tuple[int, ...] = (15, 45, 120, 300, 600)
# 외부 프로세스 1회 호출 상한(초) — 멈춘 호출이 잡 전체를 붙잡지 않게 한다.
CALL_TIMEOUT_SEC = 300
# 전체 예산(분) — 넘으면 재시도를 접고 실패로 끝낸다(워크플로 timeout-minutes보다 작아야 한다).
DEFAULT_DEADLINE_MIN = 40

_PATH_PART = r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
_REPO_RE = re.compile(rf"^{_PATH_PART}(?:/{_PATH_PART})*$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
_OWNER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38})$")


class ConfigError(Exception):
    """목록·소유자 같은 입력이 틀렸다 — 종료 코드 2(측정·설정 실패)."""


class CopyError(Exception):
    """복사·검증 실패 — 종료 코드 1."""


@dataclass(frozen=True)
class Source:
    """미러 대상 한 건. repo는 Docker Hub 저장소 경로(`library/` 접두 없이)."""

    raw: str
    repo: str
    tag: str

    @property
    def name(self) -> str:
        return self.repo.rsplit("/", 1)[-1]


def parse_source(raw: str) -> Source:
    """`저장소:태그`만 허용한다. 레지스트리 호스트·digest·태그 생략(암묵 latest)은 거부한다."""
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(f"source가 비었거나 문자열이 아니다: {raw!r}")
    text = raw.strip()
    if "@" in text:
        raise ConfigError(f"digest 고정 표기는 목록에 쓰지 않는다(실행 시 해석): {raw!r}")
    repo, sep, tag = text.partition(":")
    if not sep or not tag:
        raise ConfigError(f"태그가 명시돼야 한다(암묵 latest 금지): {raw!r}")
    if not _REPO_RE.match(repo):
        raise ConfigError(f"저장소 경로 형식이 아니다(소문자·호스트 금지): {raw!r}")
    first = repo.split("/", 1)[0]
    if "." in first or first == "localhost":
        raise ConfigError(f"레지스트리 호스트가 섞였다 — Docker Hub 이미지만 받는다: {raw!r}")
    if not _TAG_RE.match(tag):
        raise ConfigError(f"태그 형식이 아니다: {raw!r}")
    return Source(raw=text, repo=repo, tag=tag)


def load_sources(path: Path) -> list[Source]:
    """목록 파일을 읽는다. 읽기·파싱 실패와 0건은 전부 설정 실패다(스캔 0건은 통과가 아니다)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"목록을 읽지 못했다 [{type(exc).__name__}]: {path}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ConfigError(f"`sources` 목록이 없다: {path}")
    sources = [parse_source(item) for item in data["sources"]]
    if not sources:
        raise ConfigError(f"sources가 0건이다 — 빈 목록은 미러를 한 것이 아니다: {path}")
    mirrored = [mirror_ref("owner", s) for s in sources]
    if len(set(mirrored)) != len(mirrored):
        raise ConfigError("서로 다른 source가 같은 사본 주소로 모인다(이름 충돌)")
    return sources


def mirror_ref(owner: str, source: Source) -> str:
    """사본 주소. 소유자는 소문자여야 한다 — ci.yml의 `${{ github.repository_owner }}`는 대소문자를
    바꿀 수 없어서, 대문자 소유자는 CI 참조와 사본 주소가 어긋난다."""
    if not _OWNER_RE.match(owner):
        raise ConfigError(f"소유자는 소문자·숫자·하이픈만 가능하다(ghcr 규칙): {owner!r}")
    return f"{MIRROR_HOST}/{owner}/{MIRROR_NAMESPACE}/{source.name}:{source.tag}"


Runner = Callable[[Sequence[str], int], "subprocess.CompletedProcess[str]"]


def _run(cmd: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """외부 호출 1회. 타임아웃 필수 — 멈춘 호출이 잡을 붙잡지 않게 한다."""
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        encoding="utf-8",  # 로케일(cp949 등)로 디코드하면 출력이 깨진다 (HARN-19)
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _imagetools(runner: Runner, *args: str) -> str:
    """imagetools 호출. 실패하면 원인(예외 타입·stderr 끝)을 남기고 CopyError로 올린다."""
    cmd = ["docker", "buildx", "imagetools", *args]
    try:
        proc = runner(cmd, CALL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired as exc:
        raise CopyError(
            f"타임아웃 {CALL_TIMEOUT_SEC}s [{type(exc).__name__}]: {' '.join(args)}"
        ) from exc
    except OSError as exc:
        raise CopyError(f"실행 실패 [{type(exc).__name__}]: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise CopyError(f"exit {proc.returncode}: {' '.join(args)} :: {' | '.join(tail)}")
    return proc.stdout


def resolve_digest(runner: Runner, ref: str) -> str:
    """태그를 digest로 해석한다. `sha256:` 형식이 아니면 거부한다(빈 응답은 digest가 아니다)."""
    out = _imagetools(runner, "inspect", "--format", "{{.Manifest.Digest}}", ref).strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", out):
        raise CopyError(f"digest 형식이 아니다: {out[:80]!r} (ref={ref})")
    return out


def platform_digests(runner: Runner, ref: str) -> list[str]:
    """인덱스가 가리키는 플랫폼 manifest digest 집합(정렬). 단일 manifest면 자기 digest 하나."""
    raw = _imagetools(runner, "inspect", "--raw", ref)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CopyError(f"manifest가 JSON이 아니다 [{type(exc).__name__}]: {ref}") from exc
    manifests = doc.get("manifests") if isinstance(doc, dict) else None
    if isinstance(manifests, list) and manifests:
        digests = sorted(str(m.get("digest", "")) for m in manifests if isinstance(m, dict))
        if not all(d.startswith("sha256:") for d in digests):
            raise CopyError(f"플랫폼 digest를 읽지 못했다: {ref}")
        return digests
    return [resolve_digest(runner, ref)]


def with_retry(
    action: Callable[[], str],
    *,
    label: str,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    deadline: float,
    log: Callable[[str], None],
) -> str:
    """지수 백오프 재시도. 실패 원인은 시도마다 남긴다(마지막 한 줄만 남기면 원인이 사라진다)."""
    attempts = len(RETRY_DELAYS) + 1
    last: CopyError | None = None
    for i in range(attempts):
        try:
            return action()
        except CopyError as exc:
            last = exc
            log(f"  ⚠ {label} 시도 {i + 1}/{attempts} 실패: {exc}")
            if i == attempts - 1:
                break
            delay = RETRY_DELAYS[i]
            if clock() + delay > deadline:
                log(f"  ⚠ {label}: 전체 예산 초과 — 재시도를 접는다")
                break
            sleep(delay)
    assert last is not None
    raise last


def mirror_one(
    runner: Runner,
    owner: str,
    source: Source,
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    deadline: float,
    log: Callable[[str], None],
) -> tuple[str, str]:
    """한 이미지를 복사·검증한다. 반환 = (source digest, 사본 주소)."""
    dest = mirror_ref(owner, source)
    retry = {"sleep": sleep, "clock": clock, "deadline": deadline, "log": log}

    digest = with_retry(
        lambda: resolve_digest(runner, source.raw), label=f"{source.raw} digest 해석", **retry
    )
    pinned = f"{source.repo}@{digest}"
    with_retry(
        lambda: _imagetools(runner, "create", "--tag", dest, pinned),
        label=f"{source.raw} → {dest} 복사",
        **retry,
    )

    def _verify() -> str:
        src = platform_digests(runner, pinned)
        dst = platform_digests(runner, dest)
        if src != dst:
            raise CopyError(f"사본 플랫폼 digest가 source와 다르다: source={src} 사본={dst}")
        return ",".join(dst)

    with_retry(_verify, label=f"{dest} 검증", **retry)
    return digest, dest


def _summary_line(source: Source, digest: str, dest: str) -> str:
    return f"| `{source.raw}` | `{digest}` | `{dest}` |"


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(description="CI 컨테이너 이미지 ghcr.io 미러 (OPS-135)")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--owner", default=os.environ.get("GITHUB_REPOSITORY_OWNER", ""))
    parser.add_argument("--deadline-minutes", type=int, default=DEFAULT_DEADLINE_MIN)
    parser.add_argument("--dry-run", action="store_true", help="복사 없이 계획만 출력")
    args = parser.parse_args(argv)

    try:
        sources = load_sources(args.manifest)
        plan = [(s, mirror_ref(args.owner, s)) for s in sources]
    except ConfigError as exc:
        out(f"설정 실패 [ConfigError]: {exc}")
        return 2

    out(f"미러 계획 {len(plan)}건 (소유자={args.owner}):")
    for source, dest in plan:
        out(f"  {source.raw} → {dest}")
    if args.dry_run:
        return 0

    deadline = clock() + args.deadline_minutes * 60
    failures: list[str] = []
    rows: list[str] = []
    for source, _dest in plan:
        out(f"▶ {source.raw}")
        try:
            digest, dest = mirror_one(
                runner, args.owner, source, sleep=sleep, clock=clock, deadline=deadline, log=out
            )
        except CopyError as exc:
            failures.append(source.raw)
            out(f"✗ {source.raw} 실패 [CopyError]: {exc}")
            continue
        rows.append(_summary_line(source, digest, dest))
        out(f"✔ {source.raw} @ {digest} → {dest}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and rows:
        header = "| source | 복사한 digest | 사본 |\n|---|---|---|\n"
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(header + "\n".join(rows) + "\n")
        except OSError as exc:
            out(f"⚠ 요약 기록 실패 [{type(exc).__name__}] — 복사 결과에는 영향 없음")

    if failures:
        out(f"실패 {len(failures)}/{len(plan)}건: {', '.join(failures)}")
        return 1
    out(f"성공 {len(plan)}/{len(plan)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
