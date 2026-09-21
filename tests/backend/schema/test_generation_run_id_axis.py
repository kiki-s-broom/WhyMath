"""GenerationLog.run_id 조인 축 — 스키마·DB·적재 경로 정합 (EOS-97 ①).

**왜 이 파일이 필요한가**: `run_id`를 Pydantic에만 더하면 DB 왕복에서 **조용히 사라진다**
— `GenerationLog.from_schema`/`to_schema`가 매핑된 컬럼 키로 필터링하기 때문이다. 필드가
있는데 영속되지 않는 상태는 "기록했다고 믿는데 없는" 최악의 형태라, 세 좌석(스키마·ORM·
마이그레이션)이 함께 있는지를 기계로 대조한다.

그리고 축이 **실제로 조인되는지**는 별개다 — 값이 세 산출물(생성 로그·회차 리포트·검수
큐)에 같은 값으로 흘러야 "이 회차로 만든 산출물"을 특정할 수 있다(정본화 ≠ 집행).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from whymath_backend.db.models.provenance import GenerationLog as OrmGenerationLog
from whymath_backend.db.schema_version import EXPECTED_ALEMBIC_HEAD, KNOWN_REVISIONS
from whymath_backend.l3.pregenerate.provenance_bridge import (
    append_generation_log_jsonl,
    load_generation_logs_jsonl,
)
from whymath_backend.schema.provenance import GenerationLog


class TestSeatExistsInAllThreePlaces:
    """스키마에만 있고 DB에 없으면 왕복에서 조용히 사라진다."""

    def test_schema_has_run_id(self) -> None:
        assert "run_id" in GenerationLog.model_fields

    def test_orm_has_run_id_column(self) -> None:
        columns = {col.key for col in sa.inspect(OrmGenerationLog).mapper.column_attrs}
        assert "run_id" in columns, (
            "ORM에 run_id 컬럼이 없다 — from_schema/to_schema가 매핑 키로 필터링하므로 "
            "스키마 필드만 더하면 DB 왕복에서 값이 조용히 사라진다."
        )

    def test_orm_roundtrip_preserves_run_id(self) -> None:
        """seam을 실제로 통과시켜 본다 — 컬럼 존재만으로는 왕복을 보장하지 못한다."""
        original = GenerationLog(run_id="RUN-ROUNDTRIP", model_name="m")
        restored = OrmGenerationLog.from_schema(original).to_schema()
        assert restored.run_id == "RUN-ROUNDTRIP"

    def test_migration_head_declares_the_column(self) -> None:
        """마이그레이션 없이 컬럼만 선언하면 실 DB에는 없다(배포 시 터진다)."""
        assert EXPECTED_ALEMBIC_HEAD == KNOWN_REVISIONS[-1]
        migrations = list(Path("alembic/versions").glob("*_generation_log_run_id.py"))
        assert len(migrations) == 1, "run_id 마이그레이션 파일이 정확히 1개여야 한다"
        source = migrations[0].read_text(encoding="utf-8")
        assert 'revision: str = "b8d3f6a91c24"' in source
        assert '"generation_log", sa.Column("run_id"' in source
        assert "idx_generation_run_id" in source
        assert 'op.drop_column("generation_log", "run_id")' in source  # downgrade 대칭


class TestNullMeansUnrecorded:
    """회차 개념이 없는 경로는 NULL — 날조하지 않는다."""

    def test_default_is_none(self) -> None:
        assert GenerationLog().run_id is None

    def test_max_length_enforced(self) -> None:
        with pytest.raises(ValueError):
            GenerationLog(run_id="x" * 65)


class TestAppendStamping:
    """append 지점이 회차를 찍는다 — 생성기는 자기 회차를 모른다."""

    def test_stamps_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "g.jsonl"
        stamped = append_generation_log_jsonl(path, GenerationLog(), run_id="RUN-1")
        assert stamped.run_id == "RUN-1"
        logs, errors = load_generation_logs_jsonl(path)
        assert errors == []
        assert logs[0].run_id == "RUN-1"

    def test_does_not_overwrite_explicit_run_id(self, tmp_path: Path) -> None:
        """호출자가 명시한 회차를 append가 바꾸면 그 행은 소속을 거짓말한다."""
        path = tmp_path / "g.jsonl"
        stamped = append_generation_log_jsonl(
            path, GenerationLog(run_id="EXPLICIT"), run_id="STAMPED"
        )
        assert stamped.run_id == "EXPLICIT"

    def test_absent_run_id_stays_none(self, tmp_path: Path) -> None:
        """회차를 안 주면 None이 남는다 — 빈 문자열 등으로 채우지 않는다."""
        path = tmp_path / "g.jsonl"
        stamped = append_generation_log_jsonl(path, GenerationLog())
        assert stamped.run_id is None

    def test_generated_at_still_stamped_alongside(self, tmp_path: Path) -> None:
        """run_id 추가가 기존 generated_at 스탬프를 깨지 않았는지."""
        path = tmp_path / "g.jsonl"
        stamped = append_generation_log_jsonl(path, GenerationLog(), run_id="R")
        assert stamped.generated_at is not None


class TestAxisActuallyJoins:
    """정본화 ≠ 집행 — 축이 세 산출물에 **같은 값**으로 흐르는지 실제 회차로 확인한다."""

    def test_cli_threads_one_run_id_into_genlog_and_report(
        self, tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from whymath_backend.harness import problem_corpus_accumulate

        class _LoggingFailingGenerator:
            """생성은 실패시키되 **생성 로그 싱크는 호출**한다.

            전건 실패 생성기는 LLM 호출이 없어 genlog가 비고, 그러면 이 테스트가 확인하려는
            축(genlog ↔ 리포트 ↔ 검수 큐가 **같은** 회차)을 볼 수 없다. 실제 생성기는 호출
            1건마다 싱크를 부르므로 그 계약만 흉내 낸다.
            """

            def __init__(self, sink: object) -> None:
                self._sink = sink

            def generate(self, spec: object) -> None:
                if self._sink is not None:
                    self._sink(GenerationLog(model_name="stub"))  # type: ignore[operator]
                return None

        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _LoggingFailingGenerator(
                kwargs.get("generation_log_sink")
            ),
        )
        out = tmp_path / "acc.jsonl"
        problem_corpus_accumulate.main(
            ["--out", str(out), "--n", "3", "--canary", "0", "--abort-window", "0"]
        )
        report = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
        run_id = report["run_id"]
        assert run_id, "회차 리포트에 run_id가 없다"

        # 검수 큐 행도 같은 축을 가져야 조인이 성립한다.
        queue_path = problem_corpus_accumulate.default_review_queue_path(out)
        assert queue_path.exists()
        queue_rows = [json.loads(line) for line in queue_path.read_text("utf-8").splitlines()]
        assert queue_rows, "검수 큐가 비었다"
        assert {row["run_id"] for row in queue_rows} == {
            run_id
        }, "검수 큐의 run_id가 회차 리포트와 다르다 — 조인 축이 갈라졌다."

        # **생성 로그도 같은 축이어야 조인이 성립한다.** 이게 이 테스트의 핵심이다 —
        # 리포트와 검수 큐만 비교하면 accumulate가 내부에서 자체 run_id를 만들어도 둘은
        # 서로 일치하므로 통과해 버린다(뮤테이션 M13이 실제로 그렇게 빠져나갔다).
        genlog_path = problem_corpus_accumulate.default_generation_log_path(out)
        assert genlog_path.exists(), "생성 로그 사이드카가 없다 — 싱크가 안 불렸다"
        genlog_rows = [json.loads(line) for line in genlog_path.read_text("utf-8").splitlines()]
        assert genlog_rows, "생성 로그가 비었다"
        assert {row["run_id"] for row in genlog_rows} == {
            run_id
        }, "생성 로그의 run_id가 회차 리포트와 다르다 — 리콜이 엉뚱한 산출물을 집는다."

    def test_genlog_sink_stamps_the_same_run_id(self, tmp_path: Path) -> None:
        """생성 로그 싱크가 회차를 찍는지 — 싱크 조립을 그대로 재현해 확인한다.

        라이브 LLM 없이 확인하려고 싱크 계약만 직접 호출한다(전건 실패 생성기는 LLM 호출
        자체가 없어 genlog가 비므로, 그 경로로는 이 축을 볼 수 없다 — 정직한 우회).
        """
        genlog = tmp_path / "acc.genlog.jsonl"
        run_id = uuid.uuid4().hex

        def sink(log: GenerationLog) -> None:
            append_generation_log_jsonl(genlog, log, run_id=run_id)

        sink(GenerationLog(model_name="m1"))
        sink(GenerationLog(model_name="m2"))
        logs, errors = load_generation_logs_jsonl(genlog)
        assert errors == []
        assert {log.run_id for log in logs} == {run_id}
