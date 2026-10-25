"""성취기준 적재 CLI(`l1.standards.populate`) 단위 — hermetic(load_* monkeypatch).

실 DB·PG 없이 `main()`의 경로 결선·종료코드·`load_standards`/`load_links` 호출·`--skip-links`
분기를 검증한다. 실 적재 라운드트립은 `test_standard_loader_integration.py`(실 PG)가 담당한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l1.standards import populate


def _touch(path: Path) -> Path:
    """빈 Collection JSON 자리표시(존재 검사용 — load_*는 monkeypatch라 내용 무관)."""
    path.write_text("{}", encoding="utf-8")
    return path


class TestStandardPopulateMain:
    def test_loads_standards_and_links(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """기본 흐름 — load_standards·load_links를 경로대로 호출하고 행 수를 보고."""
        std = _touch(tmp_path / "standards.json")
        links = _touch(tmp_path / "links.json")
        calls: dict[str, Path] = {}

        def _fake_std(session: Any, path: Path) -> int:
            calls["std"] = path
            return 895  # corpus-pin: 합성 픽스처

        def _fake_links(session: Any, path: Path) -> int:
            calls["links"] = path
            return 443  # corpus-pin: 합성 픽스처

        monkeypatch.setattr(populate, "load_standards", _fake_std)
        monkeypatch.setattr(populate, "load_links", _fake_links)

        rc = populate.main(["--standards", str(std), "--links", str(links)])
        assert rc == 0
        assert calls == {"std": std, "links": links}
        out = capsys.readouterr().out
        assert "895" in out and "443" in out

    def test_skip_links_does_not_load_links(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--skip-links → load_links 미호출(성취기준만 적재)."""
        std = _touch(tmp_path / "standards.json")
        seen: dict[str, bool] = {}

        monkeypatch.setattr(populate, "load_standards", lambda _s, _p: 10)
        monkeypatch.setattr(populate, "load_links", lambda _s, _p: seen.setdefault("called", True))

        rc = populate.main(["--standards", str(std), "--skip-links"])
        assert rc == 0
        assert "called" not in seen

    def test_missing_standards_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(populate, "load_standards", lambda _s, _p: 0)
        rc = populate.main(["--standards", str(tmp_path / "nope.json")])
        assert rc == 2

    def test_missing_links_exits_2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """성취기준은 있으나 연결 파일 부재 → Exit 2(조용한 무동작 금지)."""
        std = _touch(tmp_path / "standards.json")
        monkeypatch.setattr(populate, "load_standards", lambda _s, _p: 5)
        rc = populate.main(["--standards", str(std), "--links", str(tmp_path / "no.json")])
        assert rc == 2
