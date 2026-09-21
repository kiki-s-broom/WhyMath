"""MP-05 — 카나리 구간 절단이 *실제로* 그 30건을 지목하는가.

왜 이 파일이 있는가
------------------
`MP-02` acceptance ②("카나리 30건을 100% 검수")의 분모를 이 CLI가 만든다. 그러므로 이 테스트가
붙드는 것은 "명령이 exit 0을 낸다"가 아니라 **어느 30건이 나오는가**다 — 순서가 한 칸만 밀려도,
canary_size를 상수로 가정해도, 못 찾은 시도를 조용히 버려도 산출물은 여전히 그럴듯한 JSONL이고
exit 0이다. 그래서 전 케이스가 *어느 slug가 어느 순서로 나왔는가*와 *못 찾은 것이 사유와 함께
남았는가*를 직접 본다(간접 신호 금지).

변별력(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 보호로 선언 금지")
------------------------------------------------------------------------
`TestCanarySizeDiscrimination`이 **같은 입력 파일**에 대해 canary_size만 30 → 0으로 바꿔 산출
건수가 갈리는지 본다. 갈리지 않으면 이 도구는 대장을 읽지 않고 상수를 쓰는 것이며, 그때 산출은
"카나리"가 아니라 "앞머리 아무거나"다. `canary_size=None`(MP-04 이전 구행)은 exit 1이어야 한다 —
30을 채워 넣으면 근거 없는 30건이 "카나리 전건"으로 보고된다(모른다 ≠ 아니다).

hermetic — 이 도구는 파일만 읽으므로 대본(provider)조차 없다
-----------------------------------------------------------
LLM 0·DB 0·네트워크 0. 입력 4종(회차 대장·genlog·코퍼스·검수 큐)은 **실물 writer**로 만든다
(`append_round_ledger`·`append_generation_log_jsonl`·`append_review_queue_jsonl`) — 손으로 JSON을
찍으면 스키마가 바뀔 때 테스트만 통과하는 형태가 되기 때문이다. 코퍼스만 dict를 직접 쓴다
(코퍼스 행은 Problem 직렬화라 이 도구가 `slug` 키 하나만 본다).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from whymath_backend.harness.anchor_round_ledger import RoundRecord, append_round_ledger
from whymath_backend.harness.canary_slice import (
    REASON_GENLOG_SHORTFALL,
    REASON_MISSING_CU_SLUG,
    REASON_SLUG_NOT_FOUND,
    STATUS_CORPUS_RESOLVED,
    main,
)
from whymath_backend.harness.needs_review_worklist import (
    ReviewQueueEntry,
    append_review_queue_jsonl,
)
from whymath_backend.harness.problem_corpus_accumulate import (
    default_generation_log_path,
    default_review_queue_path,
)
from whymath_backend.harness.review_session import load_review_items
from whymath_backend.l3.pregenerate.provenance_bridge import append_generation_log_jsonl
from whymath_backend.schema.provenance import GenerationLog

_RUN = "run-canary-a"
_OTHER_RUN = "run-other-b"


# ── 픽스처 조립(실물 writer) ────────────────────────────────────────────────
def _write_ledger(
    out: Path, *, run_id: str = _RUN, canary_size: int | None, attempted: int = 60
) -> None:
    """회차 대장 1행 — `canary_size`가 이 도구의 유일한 크기 근거다."""
    append_round_ledger(
        out.with_suffix(".rounds.jsonl"),
        RoundRecord(
            run_id=run_id,
            out_path=str(out),
            attempted=attempted,
            accepted=attempted,
            appended=attempted,
            canary_size=canary_size,
        ),
    )


def _write_genlog(out: Path, rows: Sequence[tuple[str, str | None]]) -> None:
    """genlog 행을 **주어진 순서 그대로** append한다 — (run_id, cu_slug)."""
    path = default_generation_log_path(out)
    for run_id, cu_slug in rows:
        append_generation_log_jsonl(
            path, GenerationLog(run_id=run_id, cu_slug=cu_slug, model_name="qwen2-math:7b")
        )


def _write_corpus(out: Path, slugs: Sequence[str]) -> None:
    """코퍼스 JSONL — 수용분. 이 도구가 보는 키는 `slug` 하나다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for slug in slugs:
            handle.write(
                json.dumps(
                    {"slug": slug, "question_text": f"{slug} 문항", "answer": "1"},
                    ensure_ascii=False,
                )
                + "\n"
            )


def _write_review_queue(out: Path, slugs: Sequence[str], *, run_id: str = _RUN) -> None:
    """검수 큐 JSONL — 비수용분(기계 사유 동반)."""
    path = default_review_queue_path(out)
    for slug in slugs:
        append_review_queue_jsonl(
            path,
            ReviewQueueEntry(
                status="needs_review",
                slug=slug,
                equivalence_score=0.71,
                reasons=[f"기계 사유: {slug} 동등성 경계"],
                candidate_payload={"slug": slug, "question_text": f"{slug} 후보"},
                run_id=run_id,
            ),
        )


def _run_cli(out: Path, queue_out: Path, *, run_id: str | None = None) -> int:
    argv = ["--out", str(out), "--queue-out", str(queue_out)]
    if run_id is not None:
        argv += ["--run-id", run_id]
    return main(argv)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            parsed = json.loads(line)
            assert isinstance(parsed, dict)
            rows.append(parsed)
    return rows


def _summary(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    """stdout 요약 JSON — 이 도구의 판정 근거는 전부 여기 실린다."""
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, dict)
    return parsed


class TestCanaryHeadSlice:
    """① 식별 근거 — 같은 run_id 행을 적재 순서대로 읽어 앞머리 canary_size건."""

    def test_first_30_in_order_and_31st_excluded(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """앞 30건이 **파일 순서 그대로** 나오고 31번째는 들어가지 않는다.

        다른 회차 행을 사이사이 끼워 둔다 — run_id 필터가 없으면 순서가 오염되고, 정렬로
        바꾸면 slug 이름순이 되어 아래 순서 단언이 깨진다(순서 계약의 변별력).
        """
        out = tmp_path / "corpus.jsonl"
        slugs = [f"cu-{idx:02d}" for idx in range(1, 32)]
        rows: list[tuple[str, str | None]] = []
        for idx, slug in enumerate(slugs):
            rows.append((_RUN, slug))
            if idx % 5 == 0:
                # 다른 회차의 행 — 절단 대상이 아니다.
                rows.append((_OTHER_RUN, f"other-{idx:02d}"))
        _write_genlog(out, rows)
        _write_corpus(out, slugs + [f"other-{idx:02d}" for idx in range(0, 31, 5)])
        _write_ledger(out, canary_size=30)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)

        emitted = _read_jsonl(queue_out)
        assert [row["slug"] for row in emitted] == slugs[:30]
        assert "cu-31" not in {row["slug"] for row in emitted}
        assert [row["canary_index"] for row in emitted] == list(range(1, 31))
        assert summary["canary_size"] == 30
        assert summary["genlog_rows_for_run"] == 31
        assert summary["emitted"] == 30
        assert summary["unresolved_count"] == 0

    def test_run_id_defaults_to_last_ledger_row_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--run-id 생략 시 대장 마지막 행을 쓰고, 어느 회차를 골랐는지 요약이 말한다."""
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_OTHER_RUN, "other-1"), (_RUN, "cu-01"), (_RUN, "cu-02")])
        _write_corpus(out, ["other-1", "cu-01", "cu-02"])
        _write_ledger(out, run_id=_OTHER_RUN, canary_size=1)
        _write_ledger(out, run_id=_RUN, canary_size=2)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)

        assert summary["run_id"] == _RUN
        assert summary["run_id_selection"] == "ledger_last"
        assert [row["slug"] for row in _read_jsonl(queue_out)] == ["cu-01", "cu-02"]

    def test_unknown_run_id_is_measurement_failure(self, tmp_path: Path) -> None:
        """대장에 없는 run_id는 '매치 0건 성공'이 아니라 측정 실패(exit 1)."""
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-01")])
        _write_corpus(out, ["cu-01"])
        _write_ledger(out, canary_size=1)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out, run_id="run-does-not-exist") == 1
        assert not queue_out.exists()


class TestCanarySizeDiscrimination:
    """③ 변별력 — 크기를 대장에서 읽는가(상수 30이면 여기서 깨진다)."""

    @staticmethod
    def _fixture(tmp_path: Path, canary_size: int | None) -> tuple[Path, Path]:
        out = tmp_path / "corpus.jsonl"
        slugs = [f"cu-{idx:02d}" for idx in range(1, 41)]
        _write_genlog(out, [(_RUN, slug) for slug in slugs])
        _write_corpus(out, slugs)
        _write_ledger(out, canary_size=canary_size)
        return out, tmp_path / "canary.review.jsonl"

    def test_size_30_emits_30(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out, queue_out = self._fixture(tmp_path, 30)
        assert _run_cli(out, queue_out) == 0
        assert _summary(capsys)["emitted"] == 30
        assert len(_read_jsonl(queue_out)) == 30

    def test_size_zero_emits_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """카나리 0(관문 끔) — 같은 genlog·같은 코퍼스인데 산출이 0건이어야 한다.

        30 회차와 **건수가 갈리는 것**이 이 도구가 대장을 실제로 읽는다는 유일한 증거다.
        파일은 만든다(0행) — '카나리 없음'은 사실이고, 파일 부재(=측정 실패)와 구분된다.
        """
        out, queue_out = self._fixture(tmp_path, 0)
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)
        assert summary["emitted"] == 0
        assert summary["canary_size"] == 0
        assert queue_out.exists()
        assert _read_jsonl(queue_out) == []

    def test_size_none_is_unknown_not_default(self, tmp_path: Path) -> None:
        """canary_size 미기록(구행) → exit 1이고 **산출 파일을 만들지 않는다**."""
        out, queue_out = self._fixture(tmp_path, None)
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists()


class TestResolutionSources:
    """② 산출 — 수용분은 코퍼스에서, 비수용분은 검수 큐에서."""

    def test_mixed_accepted_and_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-01"), (_RUN, "cu-02"), (_RUN, "cu-03"), (_RUN, "cu-04")])
        _write_corpus(out, ["cu-01", "cu-03"])
        _write_review_queue(out, ["cu-02", "cu-04"])
        _write_ledger(out, canary_size=4)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)
        rows = _read_jsonl(queue_out)

        assert [row["slug"] for row in rows] == ["cu-01", "cu-02", "cu-03", "cu-04"]
        # 비수용분은 **이번 회차** 큐 행이므로 `review_queue_this_run`이다(2026-09-07 정정 —
        # `_write_review_queue`의 기본 run_id가 `_RUN`이다). 회차 무관 `review_queue`는
        # *다른* 회차의 행이 유일한 단서일 때만 쓰인다 — 두 라벨을 가르는 것이 계약이다.
        assert [row["resolved_from"] for row in rows] == [
            "corpus",
            "review_queue_this_run",
            "corpus",
            "review_queue_this_run",
        ]
        assert summary["resolved_from"] == {
            "review_queue_this_run": 2,
            "corpus": 2,
            "review_queue": 0,
        }
        # 수용분은 코퍼스 유래 status, 비수용분은 큐의 기계 status·사유가 살아 있다.
        assert rows[0]["status"] == STATUS_CORPUS_RESOLVED
        assert rows[1]["status"] == "needs_review"
        assert any("동등성 경계" in str(reason) for reason in list(rows[1]["reasons"]))
        # 검수자가 행만으로 후보를 볼 수 있어야 한다(양쪽 다 payload 동반).
        assert rows[0]["candidate_payload"] is not None
        assert rows[1]["candidate_payload"] is not None


class TestUnresolvedReporting:
    """② 침묵 실패 금지 — 못 찾은 행은 사유와 함께 남는다(사유가 서로 구별된다)."""

    def test_three_reasons_are_distinguished(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """정체성 없음 / 어디에도 없음 / genlog 부족 — 3종이 각각 다른 사유로 집계된다.

        같은 사유로 뭉치면 조치가 갈리지 않는다(생성 실패는 생성기 문제, 미발견은 적재 누락,
        부족은 회차 중단이라 각각 다른 사람이 다른 일을 한다).
        """
        out = tmp_path / "corpus.jsonl"
        # 4슬롯짜리 카나리에 genlog는 3행뿐(1건 부족) — 그중 1건은 정체성 없음(None),
        # 1건은 코퍼스·큐 어디에도 없음.
        _write_genlog(out, [(_RUN, "cu-01"), (_RUN, None), (_RUN, "cu-ghost")])
        _write_corpus(out, ["cu-01"])
        _write_review_queue(out, ["cu-99"])
        _write_ledger(out, canary_size=4)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)

        assert summary["unresolved_counts"] == {
            REASON_MISSING_CU_SLUG: 1,
            REASON_SLUG_NOT_FOUND: 1,
            REASON_GENLOG_SHORTFALL: 1,
        }
        unresolved = list(summary["unresolved"])  # type: ignore[call-overload]
        assert [item["canary_index"] for item in unresolved] == [2, 3, 4]
        assert [item["reason"] for item in unresolved] == [
            REASON_MISSING_CU_SLUG,
            REASON_SLUG_NOT_FOUND,
            REASON_GENLOG_SHORTFALL,
        ]
        # 사유마다 사람이 읽는 근거가 붙는다(타입명만으로는 8개 실패가 같은 글자가 된다).
        assert all(str(item["detail"]).strip() for item in unresolved)
        # 카나리 슬롯은 하나도 사라지지 않는다 — 산출 + 미해결 = canary_size.
        assert int(str(summary["emitted"])) + len(unresolved) == 4

    def test_all_unresolved_is_failure_not_empty_queue(self, tmp_path: Path) -> None:
        """카나리가 있는데 해결 0건이면 빈 큐를 남기지 않고 exit 1.

        빈 큐를 남기면 검수자가 0건을 검수하고 '카나리 전건 검수'로 보고하게 된다.
        """
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-ghost-1"), (_RUN, "cu-ghost-2")])
        _write_corpus(out, ["cu-unrelated"])
        _write_ledger(out, canary_size=2)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists()


class TestShortfall:
    """중단된 회차 — 있는 만큼 내되 그 사실을 명시한다."""

    def test_partial_round_emits_available_and_reports_shortfall(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "corpus.jsonl"
        slugs = [f"cu-{idx:02d}" for idx in range(1, 13)]
        _write_genlog(out, [(_RUN, slug) for slug in slugs])
        _write_corpus(out, slugs)
        _write_ledger(out, canary_size=30)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0
        summary = _summary(capsys)

        assert len(_read_jsonl(queue_out)) == 12
        assert summary["shortfall"] == {"expected": 30, "observed": 12, "missing": 18}
        assert summary["unresolved_counts"] == {REASON_GENLOG_SHORTFALL: 18}


class TestReviewSessionCompatibility:
    """② 산출물이 실제 소비자에게 먹히는가 — 눈으로 주장하지 않고 그 함수를 부른다."""

    def test_output_is_consumed_by_load_review_items(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-01"), (_RUN, "cu-02"), (_RUN, "cu-03")])
        _write_corpus(out, ["cu-01", "cu-03"])
        _write_review_queue(out, ["cu-02"])
        _write_ledger(out, canary_size=3)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 0

        items, errors = load_review_items(queue_out)
        # 전건이 항목으로 살아남고(MissingIdentityKey·DuplicateSlug 0), 순서도 보존된다.
        assert errors == []
        assert [item.slug for item in items] == ["cu-01", "cu-02", "cu-03"]
        # 검수자가 "기계가 왜 이걸 올렸는가"를 보는 두 칸이 채워져 있다.
        assert items[0].status == STATUS_CORPUS_RESOLVED
        assert items[1].status == "needs_review"
        assert all(item.reasons for item in items)


class TestInputGuards:
    """측정 실패가 통과로 위장되지 않는가 + 입력을 덮어쓰지 않는가."""

    def test_missing_ledger_is_failure(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-01")])
        _write_corpus(out, ["cu-01"])

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists()

    def test_missing_genlog_is_failure(self, tmp_path: Path) -> None:
        out = tmp_path / "corpus.jsonl"
        _write_corpus(out, ["cu-01"])
        _write_ledger(out, canary_size=1)

        queue_out = tmp_path / "canary.review.jsonl"
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists()

    def test_queue_out_may_not_clobber_inputs(self, tmp_path: Path) -> None:
        """산출 경로가 입력을 덮으면 회차 증거가 파괴된다 — argparse 거부(exit 2)."""
        out = tmp_path / "corpus.jsonl"
        _write_genlog(out, [(_RUN, "cu-01")])
        _write_corpus(out, ["cu-01"])
        _write_ledger(out, canary_size=1)

        for victim in (out, default_review_queue_path(out), default_generation_log_path(out)):
            with pytest.raises(SystemExit) as excinfo:
                _run_cli(out, victim)
            assert excinfo.value.code == 2


def _corrupt_line(path: Path, line_no: int) -> None:
    """지정 줄을 파싱 불가로 만든다 — 로더가 그 행을 **목록에서 빼는** 상태를 재현한다."""
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[line_no - 1] = "{이건 JSON이 아니다"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestLoadErrorsAreMeasurementFailure:
    """손상된 입력 행은 **측정 실패**다 — 요약 JSON에 적어 두고 exit 0으로 나가지 않는다.

    실측 경위 (2026-09-07 · PR #1021 Codex P1 3건 · 전건 재현 후 수정)
    ----------------------------------------------------------------
    초판은 네 입력의 로드 오류를 `summary["load_errors"]`에 **수집만** 하고 판정에는 쓰지
    않았다. 그 결과 셋 다 exit 0으로 그럴듯한 검수 큐를 냈다:

      ⓐ genlog 1행 파손 → 로더가 그 행을 빼므로 뒤 시도가 한 칸씩 당겨져 **시도 2·3·4번이
        "카나리 1·2·3번"** 으로 출력됐다(적재 순서가 유일한 식별 근거인데 그 순서가 깨졌다).
      ⓑ 대장 최신 행 파손 + `--run-id` 생략 → 이전 회차를 고르면서 note는 여전히
        *"대장 마지막 행(가장 최근 회차)을 골랐다"* 라고 **거짓을 주장**했다.
      ⓒ 검수 큐 행 파손 → 이번 회차의 거부가 사라지고 옛 코퍼스 행이 `canary_accepted`로
        보고됐다.

    공통 뿌리: **모른다 ≠ 아니다.** 손상 행은 `run_id`도 `slug`도 읽을 수 없으므로 그것이 이
    회차·이 후보의 것인지 판정할 방법이 자체가 없다. 그래서 부분 산출을 제공하지 않는다 —
    잘못된 30건을 "카나리 전건 검수"로 보고하는 비용이 측정 1회를 다시 하는 비용보다 크다.
    """

    def _fixture(self, tmp_path: Path) -> tuple[Path, Path]:
        out = tmp_path / "corpus.jsonl"
        _write_ledger(out, canary_size=3)
        _write_genlog(out, [(_RUN, f"cu-{i}") for i in range(1, 6)])
        _write_corpus(out, [f"cu-{i}" for i in range(1, 6)])
        return out, tmp_path / "queue.jsonl"

    def test_corrupt_genlog_row_does_not_shift_the_window(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ⓐ genlog 앞줄이 깨지면 **절단하지 않는다**(창이 밀린 채 exit 0이던 자리)."""
        out, queue_out = self._fixture(tmp_path)
        _corrupt_line(default_generation_log_path(out), 1)
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists(), "손상 상태에서 큐를 만들면 그 큐가 잘못된 증적이 된다"
        assert "적재 순서" in capsys.readouterr().err

    def test_corrupt_latest_ledger_row_blocks_the_latest_claim(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ⓑ '가장 최근'을 주장할 수 없으면 자동 선택을 **거부**한다."""
        out, queue_out = self._fixture(tmp_path)
        ledger = out.with_suffix(".rounds.jsonl")
        ledger.write_text(ledger.read_text(encoding="utf-8") + "{잘린 최신 행\n", encoding="utf-8")
        assert _run_cli(out, queue_out) == 1
        err = capsys.readouterr().err
        assert "--run-id" in err, "탈출 경로를 알려 주지 않으면 사람은 도구를 우회한다"
        assert not queue_out.exists()

    def test_explicit_run_id_still_works_despite_other_broken_ledger_rows(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ⓑ 대조군 — 회차를 **명시하면** '가장 최근' 주장을 하지 않으므로 진행한다.

        이 대조가 없으면 위 거부가 "손상만 있으면 무조건 막는다"인지 "거짓 주장을 막는다"인지
        구별되지 않는다. 막는 이유가 무엇인지가 곧 이 가드의 계약이다.
        """
        out, queue_out = self._fixture(tmp_path)
        ledger = out.with_suffix(".rounds.jsonl")
        ledger.write_text(ledger.read_text(encoding="utf-8") + "{잘린 최신 행\n", encoding="utf-8")
        assert _run_cli(out, queue_out, run_id=_RUN) == 0
        assert len(_read_jsonl(queue_out)) == 3

    def test_corrupt_review_queue_row_is_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ⓒ 큐 행이 깨지면 이번 회차의 거부가 사라진다 — 코퍼스 수용분으로 덮이지 않게 막는다."""
        out, queue_out = self._fixture(tmp_path)
        _write_review_queue(out, ["cu-2"])
        _corrupt_line(default_review_queue_path(out), 1)
        assert _run_cli(out, queue_out) == 1
        assert not queue_out.exists()
        assert "해결원에 손상된 행" in capsys.readouterr().err


class TestThisRoundVerdictWins:
    """같은 slug가 코퍼스에도 큐에도 있으면 **이번 회차의 판정**이 이긴다.

    실측 경위 (2026-09-07 · PR #1021 Codex P1): 카나리 후보가 기존 코퍼스 문항과 구조가 같으면
    오케스트레이터는 이번 회차 시도를 `rejected_duplicate`로 큐에 적는데, 그 slug는 **옛 회차가
    적재한** 코퍼스 행과도 일치한다. 초판은 코퍼스를 먼저 봐서 그 후보를 `canary_accepted`로
    보고했고, 거부 사유는 검수자에게 한 번도 노출되지 않았다.

    `ReviewQueueEntry.run_id`가 필수 필드라 이 구분은 **데이터로** 가능하다(추론 아님).
    """

    def test_this_run_rejection_beats_an_older_corpus_acceptance(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "corpus.jsonl"
        queue_out = tmp_path / "queue.jsonl"
        _write_ledger(out, canary_size=1)
        _write_genlog(out, [(_RUN, "cu-dup")])
        _write_corpus(out, ["cu-dup"])  # 옛 회차가 적재한 행
        append_review_queue_jsonl(
            default_review_queue_path(out),
            ReviewQueueEntry(
                status="rejected_duplicate",
                slug="cu-dup",
                reasons=["기존 코퍼스와 구조 동일 — dedup 차단"],
                run_id=_RUN,  # **이번** 회차의 판정
            ),
        )
        assert _run_cli(out, queue_out) == 0
        rows = _read_jsonl(queue_out)
        assert len(rows) == 1
        assert rows[0]["status"] == "rejected_duplicate", "이번 회차 판정이 옛 수용분에 덮였다"
        assert rows[0]["resolved_from"] == "review_queue_this_run"
        reasons = rows[0]["reasons"]
        assert isinstance(reasons, list)
        assert any("dedup 차단" in str(r) for r in reasons), "거부 사유가 검수자에게 안 보인다"
        summary = _summary(capsys)
        resolved = summary["resolved_from"]
        assert isinstance(resolved, dict)
        assert resolved["review_queue_this_run"] == 1
        assert resolved["corpus"] == 0

    def test_older_run_queue_entry_does_not_override_the_corpus(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """대조군 — **다른** 회차의 큐 행은 코퍼스를 이기지 못한다.

        이 대조가 없으면 위 규칙이 "큐가 언제나 이긴다"로 뭉개진다. 그러면 재시도로 남은 옛
        `needs_review` 행이 이번 회차의 수용분을 비수용으로 뒤집는다 — 반대 방향의 같은 결함이다.
        """
        out = tmp_path / "corpus.jsonl"
        queue_out = tmp_path / "queue.jsonl"
        _write_ledger(out, canary_size=1)
        _write_genlog(out, [(_RUN, "cu-retry")])
        _write_corpus(out, ["cu-retry"])
        _write_review_queue(out, ["cu-retry"], run_id=_OTHER_RUN)  # 옛 회차의 비수용 이력
        assert _run_cli(out, queue_out) == 0
        rows = _read_jsonl(queue_out)
        assert rows[0]["status"] == STATUS_CORPUS_RESOLVED
        assert rows[0]["resolved_from"] == "corpus"
