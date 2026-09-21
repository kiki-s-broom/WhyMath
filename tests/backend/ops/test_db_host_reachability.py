"""OPS-72 — 호스트→prod DB 도달성 진단의 판정 계약 동결.

이 스위트가 존재하는 이유는 진단 도구가 **정상 상태에서 초록인 것**만으로는 보호가 아니기
때문이다(CLAUDE.md 「보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지」). 그래서 각
고장 상태를 *실제로 주입해* 그 상태가 나오는지, 그리고 서로 **다른** 상태로 갈리는지를
확인한다 — 모든 입력에서 같은 답을 내는 검사는 위장이다.

특히 2026-09-08 사고 형태(`NOT_PUBLISHED`: 설정은 있는데 실현이 빈 배열)를 이름으로 못박는다.
그 상태를 `docker ps`만 보는 검사는 초록으로 읽었고, 그것이 이 태스크의 출발점이다.
"""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.ops import db_host_reachability as mod

# 실측 형태 그대로: 게시가 성립하면 실현 쪽에 HostPort가 채워진다.
_REALIZED_OK: dict[str, Any] = {
    "5432/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5433"}, {"HostIp": "::", "HostPort": "5433"}]
}
# 2026-09-08 사고의 실제 값 — 설정에는 5433이 있는데 실현은 **빈 배열**이다.
_DECLARED_OK: dict[str, Any] = {"5432/tcp": [{"HostIp": "", "HostPort": "5433"}]}
_REALIZED_EMPTY: dict[str, Any] = {"5432/tcp": []}


def _ports(declared: Any, realized: Any, reason: str = "") -> mod.ContainerPorts:
    return mod.ContainerPorts(declared=declared, realized=realized, reason=reason)


def _diagnose(
    declared: Any, realized: Any, tcp_open: bool | None, *, reason: str = ""
) -> mod.Diagnosis:
    return mod.diagnose(
        _ports(declared, realized, reason),
        tcp_open=tcp_open,
        host="127.0.0.1",
        port=5433,
        container="whymath-pg",
    )


class TestHasHostPort:
    """`_has_host_port` — 3상태 계약. 빈 배열(사실)과 `None`(모름)을 접지 않는다."""

    def test_none_input_stays_none(self) -> None:
        """조회 실패는 '없음'이 아니라 '모름'이다 — truthiness로 2상태로 접으면 오판한다."""
        assert mod._has_host_port(None, 5433) is None

    def test_empty_entry_list_is_false_not_none(self) -> None:
        """`{"5432/tcp": []}`는 **게시가 없다는 사실**이다(사고 당시의 실제 값)."""
        assert mod._has_host_port(_REALIZED_EMPTY, 5433) is False

    def test_key_presence_alone_does_not_prove_publication(self) -> None:
        """키(`5432/tcp`)는 있어도 값이 비면 False — 키 존재로 판정하면 사고를 재생산한다."""
        assert "5432/tcp" in _REALIZED_EMPTY
        assert mod._has_host_port(_REALIZED_EMPTY, 5433) is False

    def test_matching_host_port_found(self) -> None:
        assert mod._has_host_port(_REALIZED_OK, 5433) is True

    def test_other_host_port_does_not_match(self) -> None:
        """다른 포트가 게시돼 있다고 해서 우리 포트가 열린 것이 아니다."""
        assert mod._has_host_port({"5432/tcp": [{"HostPort": "55432"}]}, 5433) is False

    def test_null_entry_list_tolerated(self) -> None:
        """docker가 `null`을 주는 형태도 실재한다 — 크래시하지 않고 False."""
        assert mod._has_host_port({"5432/tcp": None}, 5433) is False


class TestDiagnoseFaultInjection:
    """각 고장을 주입해 **서로 다른** 상태가 나오는지 확인한다(변별력)."""

    def test_reachable_when_realized_and_open(self) -> None:
        d = _diagnose(_DECLARED_OK, _REALIZED_OK, True)
        assert d.status == mod.REACHABLE
        assert d.exit_code == 0

    def test_not_published_is_the_2026_09_08_incident(self) -> None:
        """설정 O · 실현 X · TCP X — 이 PR을 낳은 바로 그 상태."""
        d = _diagnose(_DECLARED_OK, _REALIZED_EMPTY, False)
        assert d.status == mod.NOT_PUBLISHED
        assert d.exit_code == 1
        assert d.declared_here is True and d.realized_here is False

    def test_no_binding_when_never_configured(self) -> None:
        """설정 자체가 없다 — 대책이 NOT_PUBLISHED와 다르므로(재생성) 상태도 달라야 한다."""
        d = _diagnose({"5432/tcp": []}, _REALIZED_EMPTY, False)
        assert d.status == mod.NO_BINDING
        assert d.exit_code == 1

    def test_published_but_closed(self) -> None:
        """docker는 게시됐다는데 못 붙는다 — 포트 포워더·방화벽 축."""
        d = _diagnose(_DECLARED_OK, _REALIZED_OK, False)
        assert d.status == mod.PUBLISHED_BUT_CLOSED
        assert d.exit_code == 1

    def test_foreign_listener_is_not_reachable(self) -> None:
        """TCP는 열렸는데 이 컨테이너가 게시한 게 아니다 — 초록으로 읽으면 안 된다.

        도달성만 boolean으로 보는 검사는 여기서 통과한다. 그러면 도구들이 성공하면서
        **엉뚱한 DB**에 말을 건다(2026-07-17 좀비 uvicorn과 같은 형태).
        """
        d = _diagnose(_DECLARED_OK, _REALIZED_EMPTY, True)
        assert d.status == mod.FOREIGN_LISTENER
        assert d.exit_code == 1

    def test_all_fault_states_are_distinct(self) -> None:
        """네 고장이 한 글자로 뭉개지지 않는다 — 뭉개지면 대책을 고를 수 없다."""
        statuses = {
            _diagnose(_DECLARED_OK, _REALIZED_EMPTY, False).status,
            _diagnose({"5432/tcp": []}, _REALIZED_EMPTY, False).status,
            _diagnose(_DECLARED_OK, _REALIZED_OK, False).status,
            _diagnose(_DECLARED_OK, _REALIZED_EMPTY, True).status,
        }
        assert len(statuses) == 4


class TestDiagnoseUnknownIsNotFault:
    """모름을 고장으로도 정상으로도 접지 않는다 — 측정 실패는 exit 2다."""

    def test_realized_lookup_failure_is_unknown(self) -> None:
        d = _diagnose(_DECLARED_OK, None, False, reason="docker inspect exit 1")
        assert d.status == mod.UNKNOWN
        assert d.exit_code == 2
        assert "docker inspect" in d.reason

    def test_tcp_probe_failure_is_unknown(self) -> None:
        """프로브 자체가 못 돈 것과 '닫혀 있다'는 다르다."""
        d = _diagnose(_DECLARED_OK, _REALIZED_EMPTY, None)
        assert d.status == mod.UNKNOWN
        assert d.exit_code == 2

    def test_declared_unknown_with_closed_port_is_unknown_not_no_binding(self) -> None:
        """설정을 모르면 NOT_PUBLISHED와 NO_BINDING을 가를 수 없다 — 찍지 않는다."""
        d = _diagnose(None, _REALIZED_EMPTY, False)
        assert d.status == mod.UNKNOWN

    def test_unknown_never_returns_zero(self) -> None:
        """측정 실패가 '통과'로 위장되면 이 도구는 상시 무력이 된다."""
        assert _diagnose(None, None, None).exit_code != 0


class TestResolveTargetIsNotHardcoded:
    """대상 주소는 Settings에서 파생된다 — 5433을 박으면 '문서가 주장하는 주소'를 검사한다."""

    def test_reads_host_and_port_from_database_url(self) -> None:
        settings = Settings(database_url="postgresql+asyncpg://whymath@10.0.0.9:6544/whymath")
        assert mod.resolve_target(settings) == ("10.0.0.9", 6544)

    def test_default_port_when_url_omits_it(self) -> None:
        settings = Settings(database_url="postgresql+asyncpg://whymath@127.0.0.1/whymath")
        assert mod.resolve_target(settings) == ("127.0.0.1", 5432)

    def test_prod_url_resolves_to_5433(self) -> None:
        """실제 prod 규약(5433)도 파생으로 나온다 — 상수로 박지 않아도 같은 답."""
        settings = Settings(
            database_url="postgresql+asyncpg://whymath@127.0.0.1:5433/whymath?ssl=disable"
        )
        assert mod.resolve_target(settings) == ("127.0.0.1", 5433)


class TestProbeTcp:
    def test_refused_port_is_false_not_none(self) -> None:
        """연결 거부는 측정 *결과*(닫힘)이지 측정 실패가 아니다."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            free_port = probe.getsockname()[1]
        # 소켓을 닫았으므로 그 포트는 이제 아무도 안 듣는다.
        open_, reason = mod.probe_tcp("127.0.0.1", free_port, timeout=0.5)
        assert open_ is False
        assert reason == ""

    def test_listening_port_is_true(self) -> None:
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            open_, reason = mod.probe_tcp("127.0.0.1", port, timeout=1.0)
        assert open_ is True
        assert reason == ""

    def test_unresolvable_host_is_none_with_reason(self) -> None:
        """이름 해석 실패는 '닫힘'이 아니라 '모름'이고, 사유가 남는다."""
        open_, reason = mod.probe_tcp("invalid.whymath.test.", 5433, timeout=0.5)
        assert open_ is None
        assert reason != ""
        assert "TCP 프로브 실패" in reason


class TestDockerInspectFailurePaths:
    """실패해도 **증거가 남는지** 본다 — 사유 없는 실패는 회차를 태운다."""

    def test_missing_docker_binary_reports_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError("docker")

        monkeypatch.setattr(mod.subprocess, "run", _raise)
        value, reason = mod._docker_inspect("whymath-pg", "{{json .Config}}", timeout=1.0)
        assert value is None
        assert "docker 실행 파일" in reason

    def test_timeout_reports_the_timeout_itself(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """멈춤은 타임아웃 사실 자체를 남긴다 — 무한 대기 금지."""

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="docker", timeout=1.0)

        monkeypatch.setattr(mod.subprocess, "run", _raise)
        value, reason = mod._docker_inspect("whymath-pg", "{{json .Config}}", timeout=1.0)
        assert value is None
        assert "타임아웃" in reason

    def test_nonzero_exit_carries_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """예외 타입명만으로는 서로 다른 실패가 같은 글자로 보인다 — stderr를 싣는다."""

        def _fake(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=["docker"], returncode=1, stdout=b"", stderr="No such object".encode()
            )

        monkeypatch.setattr(mod.subprocess, "run", _fake)
        value, reason = mod._docker_inspect("nope", "{{json .Config}}", timeout=1.0)
        assert value is None
        assert "No such object" in reason

    def test_output_is_decoded_as_utf8_not_locale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cp949 로케일에서도 붕괴하지 않는다 — utf-8 고정(HARN-19 선례)."""

        def _fake(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            payload = '{"오류": "없음"}'.encode()
            return subprocess.CompletedProcess(
                args=["docker"], returncode=0, stdout=payload, stderr=b""
            )

        monkeypatch.setattr(mod.subprocess, "run", _fake)
        value, reason = mod._docker_inspect("whymath-pg", "{{json .Config}}", timeout=1.0)
        assert value == {"오류": "없음"}
        assert reason == ""


class TestCollectContainerPorts:
    def test_partial_failure_keeps_the_other_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """둘 중 하나만 실패한 경우를 전체 실패로 접지 않는다."""
        calls: list[str] = []

        def _fake(container: str, template: str, *, timeout: float) -> tuple[Any | None, str]:
            calls.append(template)
            if "PortBindings" in template:
                return _DECLARED_OK, ""
            return None, "docker inspect exit 1: boom"

        monkeypatch.setattr(mod, "_docker_inspect", _fake)
        ports = mod.collect_container_ports("whymath-pg")
        assert ports.declared == _DECLARED_OK
        assert ports.realized is None
        assert "boom" in ports.reason
        assert len(calls) == 2  # 두 필드를 각각 물었다

    def test_non_dict_payload_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """docker가 `null`을 주면 '게시 없음'이 아니라 '모름'이다."""
        monkeypatch.setattr(
            mod, "_docker_inspect", lambda *a, **k: (None, "")  # type: ignore[misc]
        )
        ports = mod.collect_container_ports("whymath-pg")
        assert ports.declared is None and ports.realized is None


class TestRenderReport:
    def test_names_the_field_each_question_reads(self) -> None:
        """운영자가 '무엇을 물었는지' 알 수 있어야 한다 — 설정/실현 혼동이 사고의 원인이었다."""
        text = mod.render_report(_diagnose(_DECLARED_OK, _REALIZED_EMPTY, False))
        assert "HostConfig.PortBindings" in text
        assert "NetworkSettings.Ports" in text
        assert mod.NOT_PUBLISHED in text

    def test_unknown_renders_as_unknown_not_no(self) -> None:
        """3상태가 출력에서도 접히지 않는다."""
        text = mod.render_report(_diagnose(None, None, None, reason="docker 없음"))
        assert "모름" in text
        assert "docker 없음" in text

    def test_every_status_carries_a_remedy(self) -> None:
        """대책 없는 판정은 사람을 멈춰 세우기만 한다 — 전 상태에 다음 행동이 붙어 있다."""
        for status in (
            mod.REACHABLE,
            mod.NOT_PUBLISHED,
            mod.NO_BINDING,
            mod.PUBLISHED_BUT_CLOSED,
            mod.FOREIGN_LISTENER,
            mod.UNKNOWN,
        ):
            assert mod._REMEDY[status].strip(), f"{status}에 대책 문구가 없다"


class TestCliContract:
    """CLI 계약. `resolve_target`을 고정해 **환경의 기본 Settings에 의존하지 않게** 한다 —
    고정하지 않으면 이 테스트는 컨테이너의 `WHYMATH_DATABASE_URL`에 따라 답이 바뀐다."""

    @pytest.fixture(autouse=True)
    def _fixed_target(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(mod, "resolve_target", lambda _settings: ("127.0.0.1", 5433))

    def test_exit_code_follows_diagnosis(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI가 판정을 그대로 exit로 넘긴다 — 고장인데 0을 내면 게이트가 공허해진다."""
        monkeypatch.setattr(
            mod, "collect_container_ports", lambda *a, **k: _ports(_DECLARED_OK, _REALIZED_EMPTY)
        )
        monkeypatch.setattr(mod, "probe_tcp", lambda *a, **k: (False, ""))
        out = tmp_path / "reach.json"
        code = mod.main(["--json", str(out)])
        assert code == 1
        assert mod.NOT_PUBLISHED in capsys.readouterr().out
        assert out.exists()

    def test_reachable_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            mod, "collect_container_ports", lambda *a, **k: _ports(_DECLARED_OK, _REALIZED_OK)
        )
        monkeypatch.setattr(mod, "probe_tcp", lambda *a, **k: (True, ""))
        assert mod.main([]) == 0

    def test_measurement_failure_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """docker가 없는 환경에서 '도달 불가'로 단정하지 않는다."""
        monkeypatch.setattr(
            mod, "collect_container_ports", lambda *a, **k: _ports(None, None, "docker 없음")
        )
        monkeypatch.setattr(mod, "probe_tcp", lambda *a, **k: (None, "TCP 프로브 실패(OSError)"))
        assert mod.main([]) == 2

    def test_judges_the_configured_port_not_a_hardcoded_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """설정된 포트가 5433이 아니면 5433 게시는 도달 근거가 아니다.

        이 테스트가 없으면 `resolve_target`을 상수로 되돌려도 나머지가 전부 초록이다 —
        위 세 테스트가 5433 픽스처를 쓰기 때문이다(픽스처가 그 절을 밟지 않는 형태).
        """
        monkeypatch.setattr(mod, "resolve_target", lambda _settings: ("127.0.0.1", 6544))
        monkeypatch.setattr(
            mod, "collect_container_ports", lambda *a, **k: _ports(_DECLARED_OK, _REALIZED_OK)
        )
        monkeypatch.setattr(mod, "probe_tcp", lambda *a, **k: (False, ""))
        assert mod.main([]) == 1
        assert "127.0.0.1:6544" in capsys.readouterr().out
