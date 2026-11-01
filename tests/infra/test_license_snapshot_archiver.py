"""라이선스 스냅샷 아카이버 계약 동결 (LIC-02).

**이 테스트가 지키는 것** (경로별로 **다른 신호**가 나는지 — 변별력 규약):
  · 성공(new) / 재수집 동일(unchanged) / 내용 변경(changed) / 실패(fetch_failed)가
    감사로그에 서로 다른 event·필드로 남는다.
  · 실패 원인이 유형별로 다르게 남는다 — HTTP는 상태코드+본문 발췌, 멈춤은 타임아웃
    사실 자체, 그 외 예외는 타입명(CLAUDE.md 2026-08-22 측정·수집 도구 실패 경로 규칙).
  · 소스별 즉시 flush — 실행이 중간에 죽어도 그때까지의 증거(스냅샷·감사로그·manifest)가
    디스크에 남는다(마지막 일괄 저장 금지).
  · content-addressed 멱등 — 같은 바이트 재수집은 파일을 늘리지 않고, 해시 비교는
    바이트 기준이라 공백 하나 차이도 changed다(표기 차이 오탐·미탐 방지).
  · exit code가 판정이다 — 0 전곳 성공 / 1 0곳 성공(측정 실패·0건 통과 위장 금지) /
    3 부분 실패.
  · 스크립트의 Tier1 목록과 규약 문서(docs/data/license_snapshot_archive.md)의 동기.

실 네트워크는 **전부 금지** — fetch_fn 주입(hermetic).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "ops" / "license_snapshot_archiver.py"
_DOC_PATH = _REPO_ROOT / "docs" / "data" / "license_snapshot_archive.md"


def _import_module() -> Any:
    spec = importlib.util.spec_from_file_location("license_archiver_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def arc() -> Any:
    return _import_module()


def _src(arc: Any, sid: str = "src-a", url: str = "https://example.test/terms") -> Any:
    return arc.Tier1Source(
        source_id=sid, name_ko="테스트 소스", license_label="MIT", url=url, url_origin="test"
    )


def _fetch_ok(body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8"):
    """항상 같은 응답을 주는 모의 트랜스포트."""

    def fetch(url: str, timeout: float, user_agent: str) -> Any:
        mod = sys.modules["license_archiver_under_test"]
        return mod.FetchResult(status=status, body=body, content_type=ctype)

    return fetch


def _audit_lines(out_dir: Path) -> list[dict]:
    path = out_dir / "audit_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _content_files(out_dir: Path, sid: str) -> list[Path]:
    snap_dir = out_dir / "snapshots" / sid
    if not snap_dir.exists():
        return []
    return sorted(p for p in snap_dir.iterdir() if not p.name.endswith(".meta.json"))


# ── 성공 경로: new — 스냅샷·메타·감사로그·manifest 전부 실재 ──────────────────


def test_success_new_writes_snapshot_meta_audit_manifest(arc: Any, tmp_path: Path) -> None:
    body = "<html>약관 v1</html>".encode()
    summary = arc.archive_all(
        [_src(arc)], tmp_path, fetch_fn=_fetch_ok(body), delay=0, run_id="RUN1"
    )

    assert summary.exit_code == 0
    assert summary.ok == 1 and summary.failed == 0

    sha = hashlib.sha256(body).hexdigest()
    files = _content_files(tmp_path, "src-a")
    assert [p.name for p in files] == [f"{sha[:16]}.html"]
    assert files[0].read_bytes() == body  # 원문 바이트 그대로 (무가공)

    meta = json.loads((tmp_path / "snapshots" / "src-a" / f"{sha[:16]}.meta.json").read_text())
    assert meta["sha256"] == sha
    assert meta["url"] == "https://example.test/terms"
    assert meta["first_run_id"] == "RUN1"
    assert meta["first_fetched_at"]  # 수집 시각은 메타에 (판정에는 미사용)

    lines = _audit_lines(tmp_path)
    assert len(lines) == 1
    rec = lines[0]
    assert rec["event"] == "new"
    assert rec["sha256"] == sha
    assert rec["run_id"] == "RUN1"  # 이번 실행 식별
    assert rec["http_status"] == 200
    assert rec["snapshot_path"] == f"snapshots/src-a/{sha[:16]}.html"

    manifest = json.loads((tmp_path / "runs" / "RUN1.json").read_text())
    assert manifest["status"] == "completed"
    assert manifest["ok"] == 1 and manifest["failed"] == 0 and manifest["exit_code"] == 0


# ── 멱등: 같은 바이트 재수집 = unchanged · 파일 증가 0 · append-only ──────────


def test_idempotent_rerun_unchanged_without_new_file(arc: Any, tmp_path: Path) -> None:
    body = b"<html>TERMS</html>"
    arc.archive_all([_src(arc)], tmp_path, fetch_fn=_fetch_ok(body), delay=0, run_id="RUN1")
    summary2 = arc.archive_all(
        [_src(arc)], tmp_path, fetch_fn=_fetch_ok(body), delay=0, run_id="RUN2"
    )

    assert summary2.exit_code == 0
    lines = _audit_lines(tmp_path)
    assert [r["event"] for r in lines] == ["new", "unchanged"]  # RUN1 라인 보존(append-only)
    assert [r["run_id"] for r in lines] == ["RUN1", "RUN2"]
    assert len(_content_files(tmp_path, "src-a")) == 1  # content-addressed — 파일 낭비 없음
    # run manifest는 실행마다 별개 파일 — 이전 실행 증거와 섞이지 않는다
    assert (tmp_path / "runs" / "RUN1.json").exists()
    assert (tmp_path / "runs" / "RUN2.json").exists()


# ── 변경 감지: changed + prev_sha256 + 새 스냅샷 파일 ─────────────────────────


def test_change_detection_records_prev_hash_and_new_snapshot(arc: Any, tmp_path: Path) -> None:
    v1, v2 = b"<html>TERMS v1</html>", b"<html>TERMS v2</html>"
    arc.archive_all([_src(arc)], tmp_path, fetch_fn=_fetch_ok(v1), delay=0, run_id="RUN1")
    arc.archive_all([_src(arc)], tmp_path, fetch_fn=_fetch_ok(v2), delay=0, run_id="RUN2")

    lines = _audit_lines(tmp_path)
    assert [r["event"] for r in lines] == ["new", "changed"]
    assert lines[1]["prev_sha256"] == hashlib.sha256(v1).hexdigest()
    assert lines[1]["sha256"] == hashlib.sha256(v2).hexdigest()
    assert len(_content_files(tmp_path, "src-a")) == 2  # 두 버전 모두 보관(소급 증거)


def test_hash_is_byte_level_whitespace_diff_is_changed(arc: Any, tmp_path: Path) -> None:
    """변별력: 공백 1바이트 차이도 changed — 정규화로 인한 미탐이 없다."""
    arc.archive_all([_src(arc)], tmp_path, fetch_fn=_fetch_ok(b"TERMS\n"), delay=0, run_id="R1")
    arc.archive_all([_src(arc)], tmp_path, fetch_fn=_fetch_ok(b"TERMS \n"), delay=0, run_id="R2")
    assert [r["event"] for r in _audit_lines(tmp_path)] == ["new", "changed"]


# ── 실패 경로: 원인 유형별로 **다른** 신호 ────────────────────────────────────


def test_http_failure_records_status_and_body_excerpt(arc: Any, tmp_path: Path) -> None:
    fetch = _fetch_ok(b"Not Found: no such page", status=404, ctype="text/plain")
    summary = arc.archive_all([_src(arc)], tmp_path, fetch_fn=fetch, delay=0, run_id="RUN1")

    assert summary.exit_code == 1  # 1곳 중 0곳 성공 = 측정 실패
    rec = _audit_lines(tmp_path)[0]
    assert rec["event"] == "fetch_failed"
    assert rec["http_status"] == 404
    assert rec["error_type"] == "HTTP404"
    assert "Not Found" in rec["error_detail"]  # 본문 발췌
    assert _content_files(tmp_path, "src-a") == []  # 실패는 스냅샷을 만들지 않는다


def test_timeout_records_timeout_fact_itself(arc: Any, tmp_path: Path) -> None:
    def fetch(url: str, timeout: float, user_agent: str) -> Any:
        raise TimeoutError("read timed out")

    arc.archive_all([_src(arc)], tmp_path, fetch_fn=fetch, timeout=7.0, delay=0, run_id="RUN1")
    rec = _audit_lines(tmp_path)[0]
    assert rec["event"] == "fetch_failed"
    assert rec["error_type"] == "Timeout"  # HTTP 실패와 다른 신호
    assert "7" in rec["error_detail"] and "타임아웃" in rec["error_detail"]


def test_wrapped_urlerror_timeout_is_still_timeout(arc: Any, tmp_path: Path) -> None:
    """urllib은 연결 타임아웃을 URLError(reason=timeout)로 감싼다 — 풀어서 판정해야 한다."""
    import urllib.error

    def fetch(url: str, timeout: float, user_agent: str) -> Any:
        raise urllib.error.URLError(TimeoutError("timed out"))

    arc.archive_all([_src(arc)], tmp_path, fetch_fn=fetch, timeout=5.0, delay=0, run_id="RUN1")
    assert _audit_lines(tmp_path)[0]["error_type"] == "Timeout"


def test_generic_exception_records_type_name(arc: Any, tmp_path: Path) -> None:
    class FakeDnsError(Exception):
        pass

    def fetch(url: str, timeout: float, user_agent: str) -> Any:
        raise FakeDnsError("name resolution broke")

    arc.archive_all([_src(arc)], tmp_path, fetch_fn=fetch, delay=0, run_id="RUN1")
    rec = _audit_lines(tmp_path)[0]
    assert rec["error_type"] == "FakeDnsError"  # 무타입 경고 금지 — 타입명이 남는다
    assert "name resolution broke" in rec["error_detail"]


# ── exit code 3분법: 전곳 성공 0 / 부분 실패 3 / 0곳 성공 1 ───────────────────


def test_exit_codes_distinguish_all_partial_zero(arc: Any, tmp_path: Path) -> None:
    ok_fetch = _fetch_ok(b"terms")

    def fail_fetch(url: str, timeout: float, user_agent: str) -> Any:
        raise ConnectionResetError("boom")

    def mixed_fetch(url: str, timeout: float, user_agent: str) -> Any:
        if "src-b" in url:
            raise ConnectionResetError("boom")
        return ok_fetch(url, timeout, user_agent)

    two = [_src(arc, "src-a", "https://x.test/a"), _src(arc, "src-b", "https://x.test/src-b")]
    all_ok = arc.archive_all(two, tmp_path / "d0", fetch_fn=ok_fetch, delay=0)
    partial = arc.archive_all(two, tmp_path / "d3", fetch_fn=mixed_fetch, delay=0)
    zero = arc.archive_all(two, tmp_path / "d1", fetch_fn=fail_fetch, delay=0)

    assert (all_ok.exit_code, partial.exit_code, zero.exit_code) == (0, 3, 1)


def test_zero_sources_is_measurement_failure_exit_1(arc: Any, tmp_path: Path) -> None:
    summary = arc.archive_all([], tmp_path, fetch_fn=_fetch_ok(b"x"), delay=0)
    assert summary.exit_code == 1  # 0곳 수집을 통과로 위장하지 않는다


# ── 소스별 즉시 flush: 중간에 죽어도 앞선 소스의 증거는 디스크에 있다 ─────────


def test_per_source_flush_evidence_survives_interruption(arc: Any, tmp_path: Path) -> None:
    body = b"<html>survivor</html>"
    ok_fetch = _fetch_ok(body)

    def fetch(url: str, timeout: float, user_agent: str) -> Any:
        if "src-b" in url:
            raise KeyboardInterrupt  # BaseException — 아카이버가 잡지 않고 즉사해야 한다
        return ok_fetch(url, timeout, user_agent)

    two = [_src(arc, "src-a", "https://x.test/a"), _src(arc, "src-b", "https://x.test/src-b")]
    with pytest.raises(KeyboardInterrupt):
        arc.archive_all(two, tmp_path, fetch_fn=fetch, delay=0, run_id="RUNX")

    # 죽기 전에 처리한 src-a의 증거 3종이 전부 디스크에 실재해야 한다
    lines = _audit_lines(tmp_path)
    assert [r["source_id"] for r in lines] == ["src-a"]
    assert lines[0]["event"] == "new"
    assert len(_content_files(tmp_path, "src-a")) == 1
    manifest = json.loads((tmp_path / "runs" / "RUNX.json").read_text())
    assert manifest["status"] == "running"  # completed로 못 간 manifest = 중단 증거
    assert manifest["results"]["src-a"]["event"] == "new"
    assert "src-b" not in manifest["results"]


# ── 감사로그 읽기: 잘린 꼬리 라인은 타입명 경고와 함께 건너뛴다 ───────────────


def test_corrupt_audit_line_skipped_with_typed_warning(
    arc: Any, tmp_path: Path, capsys: Any
) -> None:
    body = b"terms"
    sha = hashlib.sha256(body).hexdigest()
    audit = tmp_path / "audit_log.jsonl"
    good = {"source_id": "src-a", "event": "new", "sha256": sha}
    audit.write_text(json.dumps(good) + "\n" + '{"broken": tru', encoding="utf-8")

    last = arc._load_last_hashes(audit)
    assert last == {"src-a": sha}  # 유효 라인은 살아남는다
    err = capsys.readouterr().err
    assert "L2" in err and "JSONDecodeError" in err  # 침묵 실패 금지 — 라인·타입명


# ── Tier1 목록 계약: 슬러그·https·유일성·문서 동기 ───────────────────────────


def test_tier1_source_list_contract(arc: Any) -> None:
    import re

    sources = arc.TIER1_SOURCES
    assert len(sources) == 20  # licensing_safety.md 매트릭스 실측(규약 문서 §1) — 변경 시 문서도
    ids = [s.source_id for s in sources]
    urls = [s.url for s in sources]
    assert len(set(ids)) == len(ids), "source_id 중복"
    assert len(set(urls)) == len(urls), "URL 중복"
    for s in sources:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", s.source_id), s.source_id
        assert s.url.startswith("https://"), s.url
        assert s.url_origin and s.name_ko and s.license_label


def test_doc_lists_every_source_id_and_count(arc: Any) -> None:
    """규약 문서와 스크립트 목록의 동기 — 어느 한쪽만 고치면 여기서 빨간불."""
    doc = _DOC_PATH.read_text(encoding="utf-8")
    for s in arc.TIER1_SOURCES:
        assert f"`{s.source_id}`" in doc, f"규약 문서에 {s.source_id} 없음"
    assert f"**{len(arc.TIER1_SOURCES)}곳**" in doc


# ── CLI: --list는 네트워크 0 · 알 수 없는 id는 사용법 오류(exit 2) ────────────


def test_cli_list_mode_touches_no_network(arc: Any, monkeypatch: Any, capsys: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("네트워크 호출 금지 (--list)")

    monkeypatch.setattr(arc, "default_fetch", forbidden)
    assert arc.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "ncic" in out and "20곳" in out


def test_cli_unknown_source_id_is_usage_error(arc: Any, capsys: Any) -> None:
    assert arc.main(["--sources", "no-such-source", "--list"]) == 2
    assert "no-such-source" in capsys.readouterr().err


def test_cli_end_to_end_with_injected_fetch(
    arc: Any, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """main() 경유 전체 흐름 — default_fetch를 모의로 갈아끼워 네트워크 0으로 검증."""
    monkeypatch.setattr(arc, "default_fetch", _fetch_ok(b"<html>t</html>"))
    code = arc.main(["--out", str(tmp_path), "--sources", "ncic,phet", "--delay", "0"])
    assert code == 0
    out = capsys.readouterr().out
    assert "수집 성공 2/2곳" in out
    assert len(_audit_lines(tmp_path)) == 2


def test_minif2f_label_matches_readme_folder_licenses(arc: Any) -> None:
    """LIC-08 — miniF2F 라벨이 README §License의 폴더별 선언 전부를 드러내는지 동결.

    miniF2F는 LICENSE 파일이 없고 README가 폴더마다 다른 라이선스를 선언한다.
    종전 'MIT' 단일 표기는 우리가 쓰는 lean 폴더(Apache)에서 틀렸다.
    증거 스냅샷에서 폴더 선언을 직접 읽어 대조하므로, 폴더 하나라도 빠지면 RED.
    """
    import re

    src = next(s for s in arc.TIER1_SOURCES if s.source_id == "minif2f")
    readme = (
        _REPO_ROOT / "data" / "licenses" / "snapshots" / "minif2f" / "9b6de2b0a301c318.txt"
    ).read_text(encoding="utf-8")
    # "The `lean` folder is released under the Apache License" 형태의 선언 줄
    decls = re.findall(r"The `(\w+)` folder is released under the (\w+) License", readme)
    assert len(decls) == 4, decls  # 스캔 0건은 실패(공허한 통과 방지)
    for folder, lic in decls:
        assert folder in src.license_label, f"{folder} 폴더가 라벨에 없음"
        assert lic in src.license_label, f"{lic} 라이선스가 라벨에 없음"
    assert src.license_label != "MIT"
