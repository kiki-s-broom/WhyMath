"""오개념 추출(`data_pipeline.misconception`) — 순수 추출 + CLI 라운드트립.

순수 `extract_misconceptions`의 평탄화·키 매핑·mis_id dedup·빈값 None을 hermetic 검증하고,
CLI(`__main__.app`)가 Collection JSON·provenance를 쓰는지 CliRunner로 본다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from data_pipeline.misconception.__main__ import app
from data_pipeline.misconception.extract import (
    extract_misconceptions,
    load_json,
)
from typer.testing import CliRunner

runner = CliRunner()


def _concepts() -> list[dict[str, Any]]:
    """합성 개념 배열 — 완전/부분 레코드·mis_id 중복·결손·빈 L5_META 포함."""
    return [
        {
            "L5_META": {
                "오개념": [
                    {
                        "mis_id": "M0001",
                        "오개념": "(-)×(-)=(-)",
                        "학생의_잘못된_사고": "부호 규칙을 혼동한다.",
                        "distractor_규칙": "정답 대신 부호를 뒤집은 값을 배치.",
                        "error_type": "부호오류",
                        "난이도": "상",
                        "교정포인트": "음수×음수=양수.",
                        "매칭_CCSS": "7.NS.A.2",
                        "개념ID": "A1",
                        "성취기준코드": "[9수01-03]",
                        "학교급": "중학교",
                        "2022_영역": "수와 연산",
                        "세부단원_개념": "정수의 곱셈",
                        "매핑신뢰도": "높음",
                        "매핑점수": 0.9,
                        "생성·검수": "원본",
                    },
                    {"mis_id": "M0002", "오개념": "y", "매핑점수": "0.5"},  # 부분·str score
                    {"mis_id": "M0001", "오개념": "중복"},  # mis_id 중복 → skip
                    {"오개념": "id 없음"},  # mis_id 결손 → skip
                ]
            }
        },
        {"L5_META": {}},  # 오개념 키 없음
        {},  # L5_META 없음
    ]


class TestExtractMisconceptions:
    def test_normalizes_and_maps_keys(self) -> None:
        records, duplicates = extract_misconceptions(_concepts())
        assert duplicates == 1  # M0001 중복 1건 정직 집계
        assert [r["mis_id"] for r in records] == ["M0001", "M0002"]  # 첫 등장 우선·순서 보존
        full = records[0]
        assert full["canonical_statement"] == "(-)×(-)=(-)"
        assert full["error_type"] == "부호오류"
        assert full["ccss_code"] == "7.NS.A.2"
        assert full["concept_src_id"] == "A1"
        assert full["standard_code"] == "[9수01-03]"
        assert full["mapping_score"] == 0.9
        assert full["provenance_note"] == "원본"

    def test_partial_record_fills_none(self) -> None:
        records, _ = extract_misconceptions(_concepts())
        partial = records[1]  # M0002
        assert partial["canonical_statement"] == "y"
        assert partial["mapping_score"] == 0.5  # 문자열 "0.5" → float
        assert partial["error_type"] is None  # 미존재 필드는 None
        assert partial["ccss_code"] is None

    def test_empty_input(self) -> None:
        records, duplicates = extract_misconceptions([])
        assert records == [] and duplicates == 0


_LOGGER = "data_pipeline.misconception.extract"


def _one_row(**extra: object) -> list[dict[str, Any]]:
    row: dict[str, Any] = {"mis_id": "M0001", "오개념": "x"}
    row.update(extra)
    return [{"L5_META": {"오개념": [row]}}]


class TestDroppedKeyWarning:
    """MISC-61 ② — 추출기가 읽지 않는 키의 값을 버릴 때 *키 이름과 함께* 경고한다.

    경고가 나야 하는 입력(주입)과 나면 안 되는 대조군을 둘 다 둔다 — 항상 경고하거나 영영 경고하지
    않는 추출기는 둘 중 하나가 깨져서 변별이 된다.
    """

    def test_value_under_unread_key_warns_with_key_name_and_count(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING", logger=_LOGGER):
            records, _ = extract_misconceptions(_one_row(오개념_원인="원인 본문 표지"))
        warned = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
        assert len(warned) == 1
        assert "오개념_원인=1행" in warned[0]  # 키 이름 + 행 수
        assert "원인 본문 표지" not in warned[0]  # 값 본문은 로그에 남기지 않는다
        # 반환값은 그대로다 — 경고는 관측 추가이지 동작 변경이 아니다
        assert records[0]["student_wrong_thinking"] is None

    def test_warning_is_one_aggregate_line_not_one_per_row(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rows = [{"mis_id": f"M{n:04d}", "오개념_원인": "v"} for n in range(1, 4)]
        with caplog.at_level("WARNING", logger=_LOGGER):
            extract_misconceptions([{"L5_META": {"오개념": rows}}])
        warned = [r for r in caplog.records if r.name == _LOGGER]
        assert len(warned) == 1 and "오개념_원인=3행" in warned[0].getMessage()

    @pytest.mark.parametrize(
        "extra",
        [
            {},  # 미매핑 키 자체가 없다
            {"오개념_원인": ""},  # 키는 있으나 값이 비었다
            {"오개념_원인": None},
            {"오개념_원인": "   "},
            {
                "출처": "공통",
                "원본_영역": "a",
                "성취기준요약": "b",
                "매핑개념명_참조": "c",
                "코드정밀도": "d",
            },
            {
                "학생의_잘못된_사고": "읽는 키",
                "distractor_규칙": "읽는 키",
            },  # 읽는 키는 경고 대상이 아니다
        ],
    )
    def test_control_no_warning_when_nothing_is_dropped(
        self, caplog: pytest.LogCaptureFixture, extra: dict[str, object]
    ) -> None:
        with caplog.at_level("WARNING", logger=_LOGGER):
            extract_misconceptions(_one_row(**extra))
        assert [r for r in caplog.records if r.name == _LOGGER] == []

    def test_duplicate_rows_are_not_counted_twice(self, caplog: pytest.LogCaptureFixture) -> None:
        rows = [
            {"mis_id": "M0001", "오개념_원인": "a"},
            {"mis_id": "M0001", "오개념_원인": "b"},  # 중복 → skip, 버려진 값으로 세지 않는다
        ]
        with caplog.at_level("WARNING", logger=_LOGGER):
            extract_misconceptions([{"L5_META": {"오개념": rows}}])
        warned = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
        assert len(warned) == 1 and "오개념_원인=1행" in warned[0]

    def test_cli_surfaces_the_warning_to_the_operator(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        src = tmp_path / "layers.json"
        src.write_text(
            json.dumps(_one_row(오개념_원인="원인"), ensure_ascii=False), encoding="utf-8"
        )
        with caplog.at_level("WARNING", logger=_LOGGER):
            result = runner.invoke(app, ["--json", str(src), "--output-dir", str(tmp_path / "o")])
        assert result.exit_code == 0, result.output  # 경고는 실패가 아니다
        assert any("오개념_원인=1행" in r.getMessage() for r in caplog.records)


class TestLoadJson:
    def test_rejects_non_array(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text('{"not": "array"}', encoding="utf-8")
        with pytest.raises(ValueError):
            load_json(path)

    def test_loads_array(self, tmp_path: Path) -> None:
        path = tmp_path / "ok.json"
        path.write_text('[{"L5_META": {}}]', encoding="utf-8")
        assert load_json(path) == [{"L5_META": {}}]


class TestExtractCli:
    def test_writes_corpus_and_provenance(self, tmp_path: Path) -> None:
        src = tmp_path / "layers.json"
        src.write_text(json.dumps(_concepts(), ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "corpus"
        result = runner.invoke(app, ["--json", str(src), "--output-dir", str(out)])
        assert result.exit_code == 0, result.output

        collection = json.loads((out / "misconceptions.json").read_text(encoding="utf-8"))
        assert collection["count"] == 2
        assert {m["mis_id"] for m in collection["misconceptions"]} == {"M0001", "M0002"}
        assert "자체 저작" in collection["license_notice"]

        prov = json.loads((out / "_provenance.json").read_text(encoding="utf-8"))
        assert prov["counts"] == {
            "misconceptions": 2,
            "duplicates_skipped": 1,
            "with_ccss": 1,
            "with_error_type": 1,
        }
        assert len(prov["source_sha256"]) == 64
        assert prov["error_types"] == ["부호오류"]

    def test_missing_json_exits_2(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["--json", str(tmp_path / "nope.json")])
        assert result.exit_code == 2

    def test_no_misconceptions_exits_2(self, tmp_path: Path) -> None:
        src = tmp_path / "empty.json"
        src.write_text('[{"L5_META": {}}]', encoding="utf-8")
        result = runner.invoke(app, ["--json", str(src), "--output-dir", str(tmp_path / "o")])
        assert result.exit_code == 2
