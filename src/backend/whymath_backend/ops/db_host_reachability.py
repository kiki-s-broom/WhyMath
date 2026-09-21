"""호스트→prod DB 도달성 진단 — OPS-72 감시 사각 해소.

**존재 이유**: 2026-09-08~09 게이트 회차에서 Phaiakes9의 prod DB(docker `whymath-pg`)가
호스트 TCP 5433으로 **접속 불가** 상태임이 드러났다. 컨테이너는 `Up`이었고 컨테이너 안
PostgreSQL은 `accepting connections`였다 — 죽은 것이 아니라 **문이 안 열린** 것이었다.
원인은 Windows Hyper-V/WinNAT의 동적 포트 제외 범위(실측 `5368~5467`)가 5433을 삼켜 Docker가
게시(publish)에 실패한 것이고, `docker run -p 5434:...`도 같은 오류를 낸 결정적 실험으로
컨테이너 문제가 아님을 가렸다.

**왜 아무도 못 봤나 — 이 모듈이 있어야 하는 진짜 이유**: 그 고장을 볼 수 있는 도구가 **하나도
없었다**. 백업(`scripts/backup/backup_whymath_pg.ps1`)은 `docker exec pg_dump`로, 스키마
프로브(`scripts/ops/probe_prod_schema_revision.sql`)는 `docker exec psql`로 **컨테이너 안으로
들어간다**. 저장소 전수 검색에서 호스트 `127.0.0.1:5433`에 의존하는 스크립트는 0건이었다.
즉 감시 사각이 우연이 아니라 **구조적**이다 — 백업은 계속 성공하고 아무 경보도 울리지 않는
동안, 호스트에서 붙는 모든 경로(측정 도구·호스트 uvicorn·호스트 alembic)가 죽어 있었다.

**설정 ≠ 실현 (이 진단의 핵심 축)**: `docker inspect`의 `HostConfig.PortBindings`는 컨테이너를
만들 때 *요청한 설정*이고, `NetworkSettings.Ports`(그리고 `docker ps`의 Ports 칸)는 *실현된
게시*다. 이번 사고에서 전자는 `{"5432/tcp":[{"HostPort":"5433"}]}`로 멀쩡했고 후자는
`{"5432/tcp":[]}`였다 — **설정이 옳다는 이유로 정상으로 읽으면 고장을 못 본다**. 진단 세션이
실제로 그 함정에 빠져 "매핑이 없다"고 오진했다. 그래서 이 모듈은 두 필드를 *따로* 읽고,
어긋남 자체를 상태로 승격한다.

**`FOREIGN_LISTENER`가 왜 별도 상태인가**: TCP가 열려 있는데 컨테이너가 그 포트를 게시하지
않았다면, **다른 프로세스가 그 자리를 대신 물고 있다**는 뜻이다. 이것은 "도달 가능"보다 **더
나쁜** 상태다 — 도구들이 성공하면서 *엉뚱한 DB*에 말을 걸기 때문이다(2026-07-17 좀비 uvicorn이
`/health`에 응답해 shadow OFF 서버로 트래픽이 간 사고와 같은 형태: 간접 신호를 다른 프로세스가
대신 만족시킨다). 도달성만 boolean으로 보는 검사는 이 상태를 초록으로 읽는다.

**3상태를 접지 않는다**: docker가 없거나 조회가 실패하면 `UNKNOWN`이고 **exit 2**다. 이것을
"도달 불가"(exit 1)로 접으면 *측정 실패*가 *고장 판정*으로 위장된다(CLAUDE.md 「측정·게이트
도구가 판정치를 외부 인프라에만 의존 금지」의 3상태 축). 반대로 exit 0으로 접으면 보호가
공허하게 통과한다.

exit: **0 = 도달 가능 / 1 = 도달 불가(고장) / 2 = 측정 불가**

사용:
    python -m whymath_backend.ops.db_host_reachability
    python -m whymath_backend.ops.db_host_reachability --container whymath-pg
    python -m whymath_backend.ops.db_host_reachability --json out/reach.json

대상 주소는 **`Settings.database_url`에서 파생**한다(하드코딩 5433 아님) — 진단해야 할 것은
"5433이 열려 있는가"가 아니라 "**이 앱이 실제로 쓰는 주소**에 붙을 수 있는가"이기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from whymath_backend.config import Settings, get_settings

__all__ = [
    "FOREIGN_LISTENER",
    "NO_BINDING",
    "NOT_PUBLISHED",
    "PUBLISHED_BUT_CLOSED",
    "REACHABLE",
    "UNKNOWN",
    "ContainerPorts",
    "Diagnosis",
    "collect_container_ports",
    "diagnose",
    "main",
    "probe_tcp",
    "render_report",
    "resolve_target",
]

_EXIT_OK = 0
_EXIT_UNREACHABLE = 1
_EXIT_UNKNOWN = 2

# ── 상태 어휘 ─────────────────────────────────────────────────────────────
# 서로 다른 대책을 갖는 것만 상태로 둔다(상태 폭발 방지). 같은 대책이면 한 상태다.
REACHABLE = "REACHABLE"
"""게시도 성립했고 TCP도 열렸다 — 정상."""

NOT_PUBLISHED = "NOT_PUBLISHED"
"""설정(PortBindings)에는 있는데 실현(NetworkSettings.Ports)이 비었다 — 2026-09-08 사고 형태.
대책은 컨테이너 재생성이 아니라 **게시가 실패한 이유**(Windows 포트 제외 범위 등) 제거다."""

NO_BINDING = "NO_BINDING"
"""설정 자체가 없다 — 애초에 `-p`가 빠진 컨테이너다. 대책은 재생성(볼륨 재사용)."""

PUBLISHED_BUT_CLOSED = "PUBLISHED_BUT_CLOSED"
"""docker는 게시됐다고 하는데 호스트에서 못 붙는다 — 포트 포워더·방화벽 축."""

FOREIGN_LISTENER = "FOREIGN_LISTENER"
"""TCP는 열렸는데 이 컨테이너가 게시한 것이 아니다 — **다른 프로세스가 그 자리에 있다**.
도달 가능보다 나쁘다: 도구들이 성공하면서 엉뚱한 DB에 말을 건다."""

UNKNOWN = "UNKNOWN"
"""조회 자체가 실패했다 — 모른다. 고장도 정상도 아니다(3상태를 2상태로 접지 않는다)."""

_FAULT_STATUSES = frozenset({NOT_PUBLISHED, NO_BINDING, PUBLISHED_BUT_CLOSED, FOREIGN_LISTENER})

_REMEDY: dict[str, str] = {
    REACHABLE: "조치 불요.",
    NOT_PUBLISHED: (
        "게시가 시작 시점에 실패했다. Windows라면 먼저 "
        "`netsh interface ipv4 show excludedportrange protocol=tcp`로 이 포트를 포함하는 "
        "제외 구간이 있는지 본다(실측 원인). 있으면 관리자 권한으로 winnat을 내렸다 올리며 "
        "그 포트를 관리 포트 제외로 등록한다 — 상세는 /demo-doctor 카탈로그 W1행."
    ),
    NO_BINDING: (
        "컨테이너가 포트 게시 없이 만들어졌다. 재생성이 필요하며 **추측으로 만들지 않는다** — "
        "docs/architecture/db_backup_dr_runbook.md §3-4의 inspect 스냅샷으로 볼륨·환경을 "
        "그대로 재현한다."
    ),
    PUBLISHED_BUT_CLOSED: (
        "docker는 게시됐다고 보고하는데 호스트가 못 붙는다 — 포트 포워더(Docker Desktop) "
        "또는 방화벽 축이다. Docker Desktop 재기동이 1차 처방."
    ),
    FOREIGN_LISTENER: (
        "⚠ 이 포트를 **다른 프로세스**가 물고 있다. 지금 붙는 도구들은 성공하면서 엉뚱한 "
        "대상에 말을 걸고 있을 수 있다. 점유 프로세스를 먼저 식별한다"
        "(Windows: `Get-NetTCPConnection -LocalPort <포트> -State Listen`)."
    ),
    UNKNOWN: "측정 자체가 실패했다 — 아래 `reason`의 사유를 먼저 해소한다(고장 판정이 아니다).",
}


# ──────────────────────────────────────────────────────────────────────────
# 순수 코어 — DB·docker·소켓을 모르는 판정 로직(테스트가 전 상태를 주입하는 지점)
# ──────────────────────────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class ContainerPorts:
    """`docker inspect` 두 필드의 투영 — `None`은 **조회 실패**(빈 dict와 다르다).

    이 구분이 이 모듈의 절반이다: 빈 dict는 "게시가 없다"는 *사실*이고 `None`은 "모른다"다.
    """

    declared: dict[str, Any] | None
    """`HostConfig.PortBindings` — 만들 때 요청한 **설정**."""

    realized: dict[str, Any] | None
    """`NetworkSettings.Ports` — 실제로 성립한 **게시**."""

    reason: str = ""
    """조회 실패 사유(예외 타입명 + stderr 요약). 성공이면 빈 문자열."""


@dataclass(slots=True, frozen=True)
class Diagnosis:
    """진단 결과 — 사람용 출력·JSON·exit code의 단일 진실."""

    status: str
    host: str
    port: int
    container: str
    declared_here: bool | None
    """설정에 이 호스트 포트가 있는가. `None` = 조회 실패라 모름."""

    realized_here: bool | None
    """실현된 게시에 이 호스트 포트가 있는가. `None` = 조회 실패라 모름."""

    tcp_open: bool | None
    """TCP 연결이 성립하는가. `None` = 프로브 자체가 못 돔."""

    reason: str = ""

    @property
    def exit_code(self) -> int:
        if self.status == REACHABLE:
            return _EXIT_OK
        if self.status in _FAULT_STATUSES:
            return _EXIT_UNREACHABLE
        return _EXIT_UNKNOWN

    @property
    def remedy(self) -> str:
        return _REMEDY.get(self.status, "")


def _has_host_port(bindings: dict[str, Any] | None, port: int) -> bool | None:
    """포트 맵에 이 호스트 포트가 있는가. 입력이 `None`이면 판정하지 않고 `None`을 돌려준다.

    docker의 두 필드는 형태가 같다: `{"5432/tcp": [{"HostIp": "", "HostPort": "5433"}, ...]}`.
    게시가 없으면 값이 `[]`이거나 `null`이라 **키의 존재만으로는 판정할 수 없다** — 사고 당시
    `{"5432/tcp": []}`가 정확히 그 상태였다.
    """
    if bindings is None:
        return None
    target = str(port)
    for entries in bindings.values():
        for entry in entries or ():
            if isinstance(entry, dict) and str(entry.get("HostPort", "")) == target:
                return True
    return False


def diagnose(
    ports: ContainerPorts,
    *,
    tcp_open: bool | None,
    host: str,
    port: int,
    container: str,
    probe_reason: str = "",
) -> Diagnosis:
    """설정·실현·TCP 세 신호를 상태 하나로 접는다 — **모르면 모른다고 한다**.

    판정표(세 신호의 곱이 아니라 *대책이 갈리는 축*으로 묶었다):

    | 실현 | TCP  | 설정 | 상태                  |
    |------|------|------|-----------------------|
    | 있음 | 열림 | -    | REACHABLE             |
    | 있음 | 닫힘 | -    | PUBLISHED_BUT_CLOSED  |
    | 없음 | 열림 | -    | FOREIGN_LISTENER      |
    | 없음 | 닫힘 | 있음 | NOT_PUBLISHED         |
    | 없음 | 닫힘 | 없음 | NO_BINDING            |
    | 어느 하나라도 모름  | UNKNOWN               |
    """
    declared = _has_host_port(ports.declared, port)
    realized = _has_host_port(ports.realized, port)
    reason = ports.reason or probe_reason

    if realized is None or tcp_open is None:
        status = UNKNOWN
    elif realized:
        status = REACHABLE if tcp_open else PUBLISHED_BUT_CLOSED
    elif tcp_open:
        # 게시하지 않았는데 열려 있다 — 이 컨테이너가 아닌 누군가가 그 포트에 있다.
        status = FOREIGN_LISTENER
    elif declared is None:
        status = UNKNOWN
    else:
        status = NOT_PUBLISHED if declared else NO_BINDING

    return Diagnosis(
        status=status,
        host=host,
        port=port,
        container=container,
        declared_here=declared,
        realized_here=realized,
        tcp_open=tcp_open,
        reason=reason,
    )


def resolve_target(settings: Settings) -> tuple[str, int]:
    """진단 대상 host·port를 `Settings.database_url`에서 파생한다(하드코딩 금지).

    5433을 상수로 박으면 이 도구는 *문서가 주장하는 주소*를 검사한다. 그런데 확인해야 할
    것은 **앱이 실제로 쓰는 주소**다 — 둘이 갈라지는 순간이 바로 이 도구가 필요한 순간이다.
    """
    url = make_url(settings.database_url)
    return (url.host or "127.0.0.1"), int(url.port or 5432)


# ──────────────────────────────────────────────────────────────────────────
# IO 껍데기 — docker 호출·소켓 연결(위 코어와의 seam)
# ──────────────────────────────────────────────────────────────────────────
def _docker_inspect(container: str, template: str, *, timeout: float) -> tuple[Any | None, str]:
    """`docker inspect -f <template>` 1회 — (파싱된 JSON, 실패 사유).

    실패는 **사유를 남긴다**: 예외 타입명만으로는 서로 다른 실패가 같은 글자로 보인다
    (CLAUDE.md 「측정·수집 도구를 성공 경로만 보고 설계 금지」 ②). 그래서 서브프로세스는
    stderr를, 예외는 타입명을 함께 싣는다. 타임아웃도 반드시 건다 — 무한 대기는 측정
    회차를 통째로 태운다.
    """
    try:
        raw = subprocess.run(  # noqa: S603 — 고정 실행파일·인자 조립 없음
            ["docker", "inspect", "-f", template, container],
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, "docker 실행 파일을 찾을 수 없다(FileNotFoundError)"
    except subprocess.TimeoutExpired:
        return None, f"docker inspect 타임아웃({timeout}s) — 데몬 응답 없음"
    except OSError as exc:  # 권한·파이프 등
        return None, f"docker inspect 실패({type(exc).__name__})"

    # 로케일 기본 디코드는 한국어 Windows(cp949)에서 붕괴한다 — utf-8 고정·replace
    # (HARN-19 선례). 한 글자 깨지는 편이 호출 전체가 죽는 것보다 낫다.
    stdout = (raw.stdout or b"").decode("utf-8", errors="replace").strip()
    stderr = (raw.stderr or b"").decode("utf-8", errors="replace").strip()
    if raw.returncode != 0:
        return None, f"docker inspect exit {raw.returncode}: {stderr[:200]}"
    try:
        return json.loads(stdout), ""
    except json.JSONDecodeError as exc:
        return None, f"docker inspect 출력 파싱 실패({type(exc).__name__}): {stdout[:120]}"


def collect_container_ports(container: str, *, timeout: float = 10.0) -> ContainerPorts:
    """컨테이너의 **설정**과 **실현** 포트 맵을 각각 조회한다.

    두 번 부르는 이유는 하나로 합칠 수 없어서가 아니라, 둘 중 *하나만* 실패하는 경우를
    구분하기 위해서다 — 합쳐 놓으면 부분 실패가 전체 실패로 보인다.
    """
    declared, reason_a = _docker_inspect(
        container, "{{json .HostConfig.PortBindings}}", timeout=timeout
    )
    realized, reason_b = _docker_inspect(
        container, "{{json .NetworkSettings.Ports}}", timeout=timeout
    )
    reason = " / ".join(part for part in (reason_a, reason_b) if part)
    return ContainerPorts(
        declared=declared if isinstance(declared, dict) else None,
        realized=realized if isinstance(realized, dict) else None,
        reason=reason,
    )


def probe_tcp(host: str, port: int, *, timeout: float = 3.0) -> tuple[bool | None, str]:
    """TCP 연결 성립 여부 — (열림?, 실패 사유).

    **연결 거부(ConnectionRefusedError)는 `False`이지 `None`이 아니다** — 그것은 측정
    실패가 아니라 "닫혀 있다"는 측정 *결과*다. 반면 이름 해석 실패처럼 프로브 자체가
    성립하지 않은 경우는 `None`(모름)이다.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except (ConnectionRefusedError, TimeoutError, socket.timeout):
        return False, ""
    except OSError as exc:
        # 도달 불가 네트워크·이름 해석 실패 등 — 닫힘과 구분해 모름으로 둔다.
        return None, f"TCP 프로브 실패({type(exc).__name__})"


# ──────────────────────────────────────────────────────────────────────────
# 렌더·CLI
# ──────────────────────────────────────────────────────────────────────────
def _tri(value: bool | None) -> str:
    """3상태를 문자로 — `모름`을 `아니오`로 접지 않는다."""
    return "모름" if value is None else ("예" if value else "아니오")


def render_report(diagnosis: Diagnosis) -> str:
    """운영자용 마크다운 — **무엇을 물었는지**를 필드 이름으로 드러낸다."""
    lines = [
        "# 호스트→prod DB 도달성 진단 (OPS-72)",
        "",
        f"- 대상: `{diagnosis.host}:{diagnosis.port}` · 컨테이너 `{diagnosis.container}`",
        f"- **판정: {diagnosis.status}** (exit {diagnosis.exit_code})",
        "",
        "## 신호 3종 (설정 ≠ 실현 ≠ 도달)",
        "",
        "| 무엇을 물었나 | 어느 필드 | 답 |",
        "|---|---|---|",
        f"| 이 포트를 게시하라고 **설정**했는가 | `HostConfig.PortBindings` "
        f"| {_tri(diagnosis.declared_here)} |",
        f"| 게시가 실제로 **성립**했는가 | `NetworkSettings.Ports` "
        f"| {_tri(diagnosis.realized_here)} |",
        f"| 호스트에서 **붙을 수 있는**가 | TCP connect | {_tri(diagnosis.tcp_open)} |",
        "",
        "설정과 실현은 서로 다른 필드다 — 설정만 보고 정상이라 읽으면 게시 실패를 못 본다"
        "(2026-09-08 실측 사고).",
        "",
        "## 대책",
        "",
        diagnosis.remedy,
    ]
    if diagnosis.reason:
        lines += ["", f"측정 사유 기록: {diagnosis.reason}"]
    return "\n".join(lines) + "\n"


def diagnosis_to_json(diagnosis: Diagnosis) -> dict[str, Any]:
    return {
        "status": diagnosis.status,
        "host": diagnosis.host,
        "port": diagnosis.port,
        "container": diagnosis.container,
        "declared_here": diagnosis.declared_here,
        "realized_here": diagnosis.realized_here,
        "tcp_open": diagnosis.tcp_open,
        "reason": diagnosis.reason,
        "exit_code": diagnosis.exit_code,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리. **0 = 도달 가능 / 1 = 도달 불가(고장) / 2 = 측정 불가.**"""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.ops.db_host_reachability",
        description=(
            "호스트에서 prod DB에 TCP로 붙을 수 있는지 진단한다(OPS-72). 컨테이너 생존이 "
            "아니라 실제 연결 성립을 판정하며, 설정(PortBindings)과 실현"
            "(NetworkSettings.Ports)을 구분해 보고한다. exit 0/1/2."
        ),
    )
    parser.add_argument(
        "--container",
        default="whymath-pg",
        help="prod DB 컨테이너 이름(기본 whymath-pg — 데모 whymath-demo-db와 혼동 금지)",
    )
    parser.add_argument(
        "--json", dest="json_path", type=Path, default=None, help="JSON 산출물 경로"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="docker inspect 타임아웃(초·기본 10)"
    )
    args = parser.parse_args(argv)

    host, port = resolve_target(get_settings())
    ports = collect_container_ports(args.container, timeout=args.timeout)
    tcp_open, probe_reason = probe_tcp(host, port)
    diagnosis = diagnose(
        ports,
        tcp_open=tcp_open,
        host=host,
        port=port,
        container=args.container,
        probe_reason=probe_reason,
    )

    print(render_report(diagnosis))
    if args.json_path is not None:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(
            json.dumps(diagnosis_to_json(diagnosis), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(f"JSON 산출물: {args.json_path}")
    return diagnosis.exit_code


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
