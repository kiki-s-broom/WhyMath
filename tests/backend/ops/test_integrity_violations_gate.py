"""데이터 무결성 게이트(`ops/integrity_violations_gate.py`, OPS-55) — hermetic CLI 배선 테스트.

실 DB 왕복 없이 `main(scan_fn=...)` 주입으로 인자 파싱·exit code·stdout 렌더·JSON 출력만
검증한다(`role_grant_cli.py` 선례 — DB 왕복 함수는 통합테스트가 검증). 6종 각각의 실 DB
검출 변별력(주입 성공/실패 양쪽 신호)은 `test_integrity_violations_gate_integration.py`가 맡는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.ops import integrity_violations_gate as gate


def _clean_report() -> gate.IntegrityReport:
    return gate.IntegrityReport(scanned=dict.fromkeys(gate.ALL_KINDS, 0), violations=[])


def _dirty_report() -> gate.IntegrityReport:
    report = gate.IntegrityReport(scanned=dict.fromkeys(gate.ALL_KINDS, 1), violations=[])
    report.violations.append(
        gate.Violation(
            kind=gate.KIND_ORPHAN_CONCEPT,
            identifier="math.test.fake",
            detail="concept_node.concept_id='math.test.fake' 이(가) concept.code에 없다.",
        )
    )
    return report


class TestExitCode:
    def test_clean_report_exits_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = gate.main([], scan_fn=lambda: _async_return(_clean_report()))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "정상(exit 0)" in out

    def test_dirty_report_exits_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = gate.main([], scan_fn=lambda: _async_return(_dirty_report()))
        assert exit_code == 1
        out = capsys.readouterr().out
        assert "위반 발견 1건(exit 1)" in out
        assert "math.test.fake" in out


class TestJsonReport:
    def test_json_report_written(self, tmp_path: Path) -> None:
        json_path = tmp_path / "report.json"
        exit_code = gate.main(
            ["--json", str(json_path)], scan_fn=lambda: _async_return(_dirty_report())
        )
        assert exit_code == 1
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["exit_code"] == 1
        assert len(payload["violations"]) == 1
        assert payload["violations"][0]["kind"] == gate.KIND_ORPHAN_CONCEPT
        assert payload["scanned"][gate.KIND_ORPHAN_CONCEPT] == 1


class TestEventSinceDaysFlag:
    def test_notice_printed_when_set(self, capsys: pytest.CaptureFixture[str]) -> None:
        gate.main(["--event-since-days", "30"], scan_fn=lambda: _async_return(_clean_report()))
        out = capsys.readouterr().out
        assert "최근 30일만" in out

    def test_notice_absent_by_default(self, capsys: pytest.CaptureFixture[str]) -> None:
        gate.main([], scan_fn=lambda: _async_return(_clean_report()))
        out = capsys.readouterr().out
        assert "최근" not in out


class TestIntegrityReport:
    def test_violations_by_kind_filters(self) -> None:
        report = _dirty_report()
        assert len(report.violations_by_kind(gate.KIND_ORPHAN_CONCEPT)) == 1
        assert report.violations_by_kind(gate.KIND_ORPHAN_SKILL) == []

    def test_exit_code_property(self) -> None:
        assert _clean_report().exit_code == 0
        assert _dirty_report().exit_code == 1

    def test_all_kinds_has_seven_entries(self) -> None:
        """카테고리 개수 자체를 회귀 봉인 — 조용한 확장·축소를 둘 다 막는다.

        OPS-55는 6종으로 시작했고 **EOS-07이 ⑦ PUBLISHED_VERSION_INVALID를 더해 7종**이 됐다
        (계획서 200 §27 검사 ⑤ — 발행 포인터의 상태·귀속). 이 단언이 그 확장을 실제로 잡아
        근거를 적게 만들었다(2026-09-16: 6→7 변경이 여기서 RED로 걸렸다) — 봉인이 작동한
        사례이므로 숫자만 올리지 않고 경위를 남긴다.

        늘릴 때 요구되는 것: kind 상수 + 검사 함수 + `scan_integrity` 디스패처 등록 +
        실 PG 3단 왕복 변별력 테스트(주입 → 검출 → 원복). 그 넷이 없는 kind는 추가하지 않는다.
        """
        assert len(gate.ALL_KINDS) == 7
        assert len(set(gate.ALL_KINDS)) == 7
        assert gate.KIND_PUBLISHED_VERSION_INVALID in gate.ALL_KINDS


async def _async_return(report: gate.IntegrityReport) -> gate.IntegrityReport:
    return report
