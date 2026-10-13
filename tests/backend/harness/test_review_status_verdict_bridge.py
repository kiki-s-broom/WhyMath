"""[EOS-136 ①] 사람 판정 → 회차 코퍼스 `review_status` 각인 CLI — 규칙마다 음성 대조를 둔다.

이 파일이 붙드는 것
------------------
각인 도구는 **학생 노출을 여는 값**을 쓴다(`l6/_shared.is_review_cleared`는 `approved`만 통과).
그래서 "각인된다"보다 "**안 되어야 할 때 안 된다**"가 본체다 — 성공 경로만 보는 테스트는 도구가
무엇이든 approved로 찍어도 초록이다. 축마다 막아야 할 상태를 실제로 만들어 확인한다:

  - 판정 → 값: approved/rejected는 변환 정본으로 옮기고, 손질 승인은 **보류**한다.
  - 불가침: 채워진 값은 같은 값이어도 감사 행을 만들지 않는다(손각인 세탁 금지), 다른 값이면
    충돌로 보고하고 덮지 않는다. 노출값을 사람이 막은 경우는 노출 위험으로 따로 표시한다.
  - 입력 손상 1행 = 무기록 exit 2 (잘린 반려 행이 이전 승인을 최신 판정으로 만드는 형태 포함).
  - 멱등: 2회차는 코퍼스·감사로그 바이트 동일.
  - 쓰기 순서: 감사로그 → 코퍼스. 중간에 죽은 상태는 게이트가 막고 재실행이 복구한다.
  - 적용 대상: 회차 코퍼스만(고정 코퍼스·그 밖은 거부).

이벤트는 실제 writer(`harness/review_timer`)로 만든다 — 손으로 쓴 JSON은 스키마가 실제로 받는
형태인지 보장하지 못한다(EOS-62 "`model_construct` 픽스처 교체" 선례).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import review_status_verdict_bridge as bridge
from whymath_backend.harness.golden_promotion_gate import _human_verdicts
from whymath_backend.harness.golden_promotion_gate import main as gate_main
from whymath_backend.harness.review_session import append_verdict_jsonl
from whymath_backend.harness.review_timer import (
    abort_review,
    append_event_jsonl,
    finish_review,
    start_review,
)
from whymath_backend.schema.enums import GenerationFailureCode
from whymath_backend.schema.review_timer import review_content_fingerprint

_T0 = datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
_FIXED_NOW = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)


# ── 픽스처 ─────────────────────────────────────────────────────────────────
def _record(slug: str, review_status: str | None = None) -> dict[str, Any]:
    """회차 코퍼스 레코드 모양(축적 CLI 직렬화처럼 review_status 키가 기본으로 **없다**)."""
    row: dict[str, Any] = {
        "slug": slug,
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, slug)),
        "question_text": f"{slug} 문항 — 이차방정식 x^2 - 5x + 6 = 0 의 큰 근",
        "answer": "3",
    }
    if review_status is not None:
        row["review_status"] = review_status
    return row


def _round_corpus(tmp_path: Path, rows: list[dict[str, Any]], *, ledger: bool = True) -> Path:
    """회차 코퍼스 + (기본) 회차 대장 사이드카 — 축적 CLI 산출의 표식까지 갖춘 모양."""
    corpus = tmp_path / "problems.jsonl"
    corpus.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    if ledger:
        (tmp_path / "problems.rounds.jsonl").write_text(
            json.dumps({"run_id": "round-1"}) + "\n", encoding="utf-8"
        )
    return corpus


#: 지문 인자 기본값 센티널 — "인자를 안 줌"(= `_record(slug)`의 지문을 싣는다)과 "None을 명시"
#: (= 지문 없는 옛 이벤트 모사)를 구분한다. `review_status`는 지문에서 빠지므로(EOS-27) 같은 slug의
#: 레코드는 각인 전후·채워진 값과 무관하게 같은 지문을 낸다.
_DEFAULT_FP: Any = object()


def _review(
    events: Path,
    slug: str,
    verdict: str,
    *,
    minute: int,
    reviewer: str = "kiki",
    fingerprint: Any = _DEFAULT_FP,
) -> uuid.UUID:
    """검수 1건(착수 → 종결)을 실제 writer로 적는다. 반려는 F2를 붙인다(스키마 강제).

    기본은 검수 CLI처럼 `_record(slug)`의 지문을 싣는다(EOS-27). `fingerprint=None`은 지문이 없는
    옛 이벤트, 문자열은 "검수자가 본 내용이 코퍼스와 다르다"를 모사한다.
    """
    fp = review_content_fingerprint(_record(slug)) if fingerprint is _DEFAULT_FP else fingerprint
    started = append_event_jsonl(
        events,
        start_review(
            cu_slug=slug,
            reviewer_id=reviewer,
            content_fingerprint=fp,
            occurred_at=_T0 + timedelta(minutes=minute),
        ),
    )
    code = GenerationFailureCode("F2") if verdict == "rejected" else None
    finished = append_event_jsonl(
        events,
        finish_review(
            review_session_id=started.review_session_id,
            cu_slug=slug,
            reviewer_id=reviewer,
            verdict=verdict,  # type: ignore[arg-type]
            elapsed_ms=90_000,
            failure_code=code,
            content_fingerprint=fp,
            occurred_at=_T0 + timedelta(minutes=minute, seconds=90),
        ),
    )
    return finished.event_id


def _run(
    corpus: Path,
    events: Path | list[Path],
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> tuple[int, dict[str, Any], str]:
    """CLI 1회 — (exit, 요약 JSON, stderr)."""
    event_paths = events if isinstance(events, list) else [events]
    argv = ["--corpus", str(corpus)]
    for path in event_paths:
        argv += ["--review-events", str(path)]
    code = bridge.main([*argv, *extra])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _audit(corpus: Path) -> Path:
    return bridge.default_stamp_audit_path(corpus)


# ══════════════════════════════════════════════════════════════════════════
class TestStampRules:
    """판정 → 각인값 — 변환 정본을 쓰되, 지금 내용을 인증하지 않는 판정은 각인하지 않는다."""

    def test_approved_and_rejected_are_stamped_with_audit_evidence(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a"), _record("wm-b")])
        events = tmp_path / "events.jsonl"
        event_a = _review(events, "wm-a", "approved", minute=1)
        event_b = _review(events, "wm-b", "rejected", minute=2)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert report["stamped_by_status"] == {"approved": 1, "rejected": 1}
        assert {row["slug"]: row.get("review_status") for row in _lines(corpus)} == {
            "wm-a": "approved",
            "wm-b": "rejected",
        }
        audit = {row["slug"]: row for row in _lines(_audit(corpus))}
        assert audit["wm-a"]["review_status"] == "approved"
        assert audit["wm-a"]["event_id"] == str(event_a)
        assert audit["wm-b"]["event_id"] == str(event_b)
        assert audit["wm-a"]["reviewer_id"] == "kiki"
        assert audit["wm-a"]["reviewed_at"] == (_T0 + timedelta(minutes=1, seconds=90)).isoformat()
        assert audit["wm-a"]["human_verdict"] == "approved"
        assert audit["wm-a"]["stamp_source"] == bridge.STAMP_SOURCE
        # 게이트는 `verdict` 키가 있는 행을 "판정 파일 오투입"으로 거부한다 — 감사 행은 그 키를
        # 쓰면 안 된다(쓰면 이 도구의 정상 산출물이 게이트에서 exit 2가 된다).
        assert all("verdict" not in row for row in audit.values())

    def test_edited_approval_is_held_not_stamped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """손질 승인은 각인하지 않는다 — 코퍼스엔 손질 전 내용이 있다(검수 CLI는 손질을 저장 안 함).

        변환 정본(`review_status_for_verdict`)은 이 판정을 approved로 옮긴다. 그 결과를 그대로
        찍으면 사람이 "이대로는 못 쓴다"고 본 문항이 노출 가능해진다 — 이 단언이 그 회귀를 잡는다.
        """
        corpus = _round_corpus(tmp_path, [_record("wm-e")])
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-e", "approved_with_edit", minute=1)

        code, report, err = _run(corpus, events, capsys)

        assert code == 0
        assert report["held_edit_pending"] == ["wm-e"]
        assert report["stamped"] == 0 and report["written"] is False
        assert corpus.read_bytes() == original
        assert not _audit(corpus).exists()
        assert "손질 승인 보류 1" in err

    def test_stamp_target_goes_through_the_single_conversion(self) -> None:
        """값 변환은 정본 한 곳 — 어휘 밖 판정은 추측하지 않고 거부된다(ValueError)."""
        assert bridge.stamp_target("approved") == "approved"
        assert bridge.stamp_target("rejected") == "rejected"
        assert bridge.stamp_target("approved_with_edit") is None
        with pytest.raises(ValueError):
            bridge.stamp_target("escalate")

    def test_records_without_verdict_keep_their_bytes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """판정 없는 slug는 건드리지 않는다 — 원문 줄 그대로(키 추가 없음)."""
        rows = [_record("wm-a"), _record("wm-untouched")]
        corpus = _round_corpus(tmp_path, rows)
        before = corpus.read_text(encoding="utf-8").splitlines()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        after = corpus.read_text(encoding="utf-8").splitlines()
        assert code == 0 and report["no_verdict"] == 1
        assert after[1] == before[1]  # 판정 없는 레코드는 바이트 그대로
        assert json.loads(after[0]) == {**rows[0], "review_status": "approved"}
        assert list(json.loads(after[0])) == [*rows[0], "review_status"]  # 키 순서 보존 + 끝에 추가

    def test_verdict_for_a_slug_outside_the_corpus_is_information_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """회차 내 중복처럼 코퍼스에 없는 문항의 판정은 각인 대상이 아니다(보고만)."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        _review(events, "wm-dup", "approved", minute=2)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert report["verdict_not_in_corpus"] == ["wm-dup"]
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-a"]

    def test_latest_finished_verdict_wins_and_non_verdicts_are_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """재검수의 마지막 종결이 판정이다 — 뒤따른 착수·중단은 판정을 바꾸지 않는다."""
        corpus = _round_corpus(
            tmp_path, [_record("wm-rereview"), _record("wm-then-aborted"), _record("wm-started")]
        )
        events = tmp_path / "events.jsonl"
        _review(events, "wm-rereview", "rejected", minute=1)
        _review(events, "wm-rereview", "approved", minute=2)  # 손질 반영 후 재검수 승인
        _review(events, "wm-then-aborted", "approved", minute=3)
        reopened = append_event_jsonl(
            events, start_review(cu_slug="wm-then-aborted", reviewer_id="kiki")
        )
        append_event_jsonl(
            events,
            abort_review(
                review_session_id=reopened.review_session_id,
                cu_slug="wm-then-aborted",
                reviewer_id="kiki",
                elapsed_ms=None,
            ),
        )
        append_event_jsonl(events, start_review(cu_slug="wm-started", reviewer_id="kiki"))

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert {row["slug"]: row.get("review_status") for row in _lines(corpus)} == {
            "wm-rereview": "approved",
            "wm-then-aborted": "approved",
            "wm-started": None,
        }
        assert report["no_verdict"] == 1

    def test_bridge_reads_verdicts_exactly_like_the_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """단일 권위 — 게이트 ②단이 보는 판정과 각인된 판정이 slug마다 일치한다."""
        slugs = ["wm-1", "wm-2", "wm-3", "wm-4"]
        corpus = _round_corpus(tmp_path, [_record(s) for s in slugs])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-1", "approved", minute=1)
        _review(events, "wm-2", "approved", minute=2)
        _review(events, "wm-2", "rejected", minute=3)
        _review(events, "wm-3", "approved_with_edit", minute=4)
        _review(events, "wm-4", "rejected", minute=5)
        _review(events, "wm-4", "approved", minute=6)

        _run(corpus, events, capsys)

        gate_view, errors = _human_verdicts([events])
        assert errors == []
        stamped = {row["slug"]: row.get("review_status") for row in _lines(corpus)}
        for slug, verdict in gate_view.items():
            assert stamped[slug] == bridge.stamp_target(verdict), slug


class TestNonOverwrite:
    """이미 채워진 값은 불가침 — 같으면 조용히 두고(세탁 금지), 다르면 충돌로 보고한다."""

    def test_same_value_hand_stamp_is_not_laundered_into_the_audit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """손으로 approved를 찍어 둔 레코드에 감사 행을 만들어 주지 않는다.

        만들어 주면 게이트 ③단의 `review_status_not_backfilled`(손각인 의심)가 무력해진다 —
        이 도구가 손각인을 도구 각인으로 세탁하는 통로가 된다.
        """
        corpus = _round_corpus(tmp_path, [_record("wm-hand", review_status="approved")])
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-hand", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert report["already_stamped"] == ["wm-hand"]
        assert corpus.read_bytes() == original
        assert not _audit(corpus).exists()

    def test_different_filled_value_is_a_conflict_not_an_overwrite(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """채워진 값 ≠ 최신 판정 → 덮지 않고 exit 1. 충돌이 없는 다른 레코드는 각인된다."""
        corpus = _round_corpus(
            tmp_path, [_record("wm-pending", review_status="pending"), _record("wm-ok")]
        )
        events = tmp_path / "events.jsonl"
        _review(events, "wm-pending", "approved", minute=1)
        _review(events, "wm-ok", "approved", minute=2)

        code, report, err = _run(corpus, events, capsys)

        assert code == 1
        assert report["conflicts"] == [
            {
                "slug": "wm-pending",
                "current": "pending",
                "target": "approved",
                "human_verdict": "approved",
                "exposure_risk": False,
            }
        ]
        assert {row["slug"]: row.get("review_status") for row in _lines(corpus)} == {
            "wm-pending": "pending",
            "wm-ok": "approved",
        }
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-ok"]
        assert "[충돌] wm-pending" in err

    @pytest.mark.parametrize("latest", ["rejected", "approved_with_edit"])
    def test_cleared_value_blocked_by_the_latest_human_verdict_is_an_exposure_risk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], latest: str
    ) -> None:
        """노출 통과값(approved)인데 최신 사람 판정이 그 내용을 막았다 → 노출 위험(격리 절차).

        반려로 덮지 않는다 — "들여보냈다가 되돌리는" 것은 격리 계약(EOS-71)의 사람 절차다.
        """
        corpus = _round_corpus(tmp_path, [_record("wm-live", review_status="approved")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-live", "approved", minute=1)
        _review(events, "wm-live", latest, minute=2)

        code, report, err = _run(corpus, events, capsys)

        assert code == 1
        assert report["exposure_risk"] == 1
        assert report["conflicts"][0]["exposure_risk"] is True
        assert _lines(corpus)[0]["review_status"] == "approved"  # 덮지 않았다
        assert "problem_quarantine_contract" in err

    def test_edit_request_on_an_already_blocked_record_is_held(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """이미 노출이 막힌 레코드(rejected)에 손질 요청 → 보류(충돌·노출 위험 아님)."""
        corpus = _round_corpus(tmp_path, [_record("wm-r", review_status="rejected")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-r", "approved_with_edit", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert report["held_edit_pending"] == ["wm-r"] and report["conflicts"] == []


class TestIdempotence:
    def test_second_run_is_byte_identical_and_appends_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a"), _record("wm-b"), _record("wm-c")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        _review(events, "wm-b", "rejected", minute=2)

        first_code, _first, _ = _run(corpus, events, capsys)
        corpus_after_first = corpus.read_bytes()
        audit_after_first = _audit(corpus).read_bytes()
        second_code, second, _ = _run(corpus, events, capsys)

        assert first_code == second_code == 0
        assert second["stamped"] == 0 and second["written"] is False
        assert sorted(second["already_stamped"]) == ["wm-a", "wm-b"]
        assert corpus.read_bytes() == corpus_after_first
        assert _audit(corpus).read_bytes() == audit_after_first

    def test_audit_is_append_only_across_rounds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """다음 회차의 각인이 이전 각인 기록을 지우지 않는다 — 게이트는 누적 전건을 봐야 한다."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        _run(corpus, events, capsys)

        with corpus.open("a", encoding="utf-8") as handle:  # 축적 CLI의 다음 회차 append 모양
            handle.write(json.dumps(_record("wm-b"), ensure_ascii=False) + "\n")
        _review(events, "wm-b", "approved", minute=2)
        code, _report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-a", "wm-b"]


class TestInputDamageWritesNothing:
    """입력 손상 1행이면 판정이 아니라 입력 오류다 — 아무것도 쓰지 않는다(exit 2)."""

    @pytest.mark.parametrize(
        ("corpus_tail", "reason"),
        [
            ("{잘린 행\n", "JSONDecodeError"),
            ('["배열은 레코드가 아니다"]\n', "NotAJsonObject"),
            ('{"question_text": "slug 없음"}\n', "MissingSlug"),
            (json.dumps(_record("wm-a")) + "\n", "DuplicateSlug"),
            ('{"slug": "wm-num", "review_status": 1}\n', "InvalidReviewStatusType"),
        ],
        ids=["파싱실패", "객체아님", "slug없음", "slug중복", "상태형식이상"],
    )
    def test_damaged_corpus_line(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        corpus_tail: str,
        reason: str,
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        corpus.write_text(corpus.read_text(encoding="utf-8") + corpus_tail, encoding="utf-8")
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 2
        assert report["error"] == "input_damaged"
        assert any(reason in message for message in report["messages"])
        assert corpus.read_bytes() == original
        assert not _audit(corpus).exists()

    def test_truncated_rejection_row_does_not_stamp_the_stale_approval(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """뒤쪽 반려 행이 잘리면 이전 승인이 최신 판정으로 남는다 — 그것을 각인하면 영구 오판."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        events.write_text(
            events.read_text(encoding="utf-8")
            + '{"review_session_id": "00000000-0000-4000-8000-000000000009", '
            + '"cu_slug": "wm-a", "reviewer_id": "kiki", "event_type": "finis',
            encoding="utf-8",
        )

        code, report, _err = _run(corpus, events, capsys)

        assert code == 2 and report["error"] == "input_damaged"
        assert "review_status" not in _lines(corpus)[0]

    def test_non_utf8_corpus_is_damage_not_a_crash(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        corpus.write_bytes(corpus.read_bytes() + b'{"slug": "wm-\xff"}\n')
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 2 and report["error"] == "input_damaged"
        assert report["messages"] == ["입력 읽기 실패: UnicodeDecodeError"]

    def test_missing_inputs_are_input_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        code, report, _err = _run(corpus, tmp_path / "없는-이벤트.jsonl", capsys)
        assert code == 2 and report["error"] == "input_missing"
        assert not _audit(corpus).exists()

    def test_unverifiable_input_is_an_error_not_a_crash(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`is_file()`의 권한 거부는 "없다"로도 "있다"로도 접지 않는다 — 사유를 남기고 exit 2."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        real_is_file = Path.is_file

        def _denied(self: Path) -> bool:
            if self == events:
                raise PermissionError("EACCES 주입")
            return real_is_file(self)

        monkeypatch.setattr(Path, "is_file", _denied)
        code, report, _err = _run(corpus, events, capsys)
        assert code == 2 and report["error"] == "input_missing"
        assert report["messages"] == [f"확인 불가(PermissionError): {events}"]
        assert "review_status" not in _lines(corpus)[0]


class TestDomain:
    """적용 대상 — 회차 코퍼스만. 그 밖은 거부(무기록)."""

    def test_corpus_without_round_ledger_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")], ledger=False)
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 2 and report["error"] == "domain_refused"
        assert "회차 코퍼스가 아니다" in report["messages"][0]
        assert corpus.read_bytes() == original and not _audit(corpus).exists()

    @pytest.mark.parametrize("with_ledger", [False, True], ids=["고정", "고정+대장(계약위반)"])
    def test_fixed_corpus_path_is_refused(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        with_ledger: bool,
    ) -> None:
        """고정 코퍼스 8종 경로는 코퍼스 단위 백필의 대상 — 대장이 붙어 있어도 거부한다."""
        monkeypatch.chdir(tmp_path)  # KNOWN_CORPORA는 레포 루트 상대경로 — 가짜 루트를 세운다
        fixed_dir = tmp_path / "data" / "corpus" / "problem_bank_v1"
        fixed_dir.mkdir(parents=True)
        corpus = _round_corpus(fixed_dir, [_record("wm-a")], ledger=with_ledger)
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys)

        assert code == 2 and report["error"] == "domain_refused"
        assert "고정 코퍼스" in report["messages"][0]


class TestExitCodesAndModes:
    def test_zero_matched_verdicts_is_attention_not_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """코퍼스와 짝이 맞는 판정 0건 — 다른 회차의 기록일 수 있다(0건 통과가 아니다)."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-other-round", "approved", minute=1)

        code, report, err = _run(corpus, events, capsys)

        assert code == 1 and report["matched"] == 0 and report["written"] is False
        assert "[대응 0건]" in err

    def test_dry_run_reports_the_plan_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, _err = _run(corpus, events, capsys, "--dry-run")

        assert code == 0
        assert report["dry_run"] is True and report["stamped_slugs"] == ["wm-a"]
        assert report["written"] is False
        assert corpus.read_bytes() == original and not _audit(corpus).exists()

    @pytest.mark.parametrize(
        "flag", ["--force", "--overwrite", "--include-edited", "--assume-approved"]
    )
    def test_no_flag_forces_a_stamp(self, tmp_path: Path, flag: str) -> None:
        """판정을 만들거나 보류를 뚫는 인자가 **없다** — argparse가 모르는 인자로 거부한다."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        with pytest.raises(SystemExit) as excinfo:
            bridge.main(["--corpus", str(corpus), "--review-events", str(corpus), flag])
        assert excinfo.value.code == 2


class TestWriteOrderRecovery:
    """감사로그 → 코퍼스 순서 — 중간 실패는 게이트가 막고, 재실행이 복구한다."""

    def _gate(self, tmp_path: Path, corpus: Path, events: Path) -> dict[str, Any]:
        proposal = tmp_path / "proposal.txt"
        proposal.write_text("wm-a\n", encoding="utf-8")
        queue = tmp_path / "queue.jsonl"
        queue.write_text("", encoding="utf-8")
        report = tmp_path / "gate.json"
        gate_main(
            [
                "--proposal", str(proposal),
                "--review-queue", str(queue),
                "--review-events", str(events),
                "--corpus", str(corpus),
                "--backfill-audit", str(_audit(corpus)),
                "--max-defect-rate", "0.99",
                "--json", str(report),
            ]
        )  # fmt: skip
        payload: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
        return payload

    def test_crash_between_audit_and_corpus_is_blocked_then_recovered(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        original = corpus.read_bytes()
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("교체 직전 실패 주입")

        # `bridge.os`는 `os` 모듈 그 자체다 — 패치하면 이 파일의 `os.replace`도 바뀐다. 복원용
        # 원본을 패치 **전에** 잡아 둔다(패치 뒤에 `os.replace`를 읽으면 실패 함수가 돌아온다).
        real_replace = os.replace
        monkeypatch.setattr(bridge.os, "replace", _boom)
        code, report, _err = _run(corpus, events, capsys)
        assert code == 2 and report["error"] == "write_failed"
        assert corpus.read_bytes() == original  # 코퍼스는 그대로
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-a"]  # 감사는 먼저 기록
        assert not list(tmp_path.glob(".problems.jsonl.*.tmp"))  # 임시 파일은 치웠다

        # 중간 상태 — 감사 approved · 코퍼스 빈 칸 → 게이트가 막는다(fail-closed).
        gate = self._gate(tmp_path, corpus, events)
        assert gate["verdicts"][0]["blocked_reason"] == "review_status_audit_mismatch"
        capsys.readouterr()

        monkeypatch.setattr(bridge.os, "replace", real_replace)
        code, _report, _err = _run(corpus, events, capsys)
        assert code == 0 and _lines(corpus)[0]["review_status"] == "approved"
        gate = self._gate(tmp_path, corpus, events)
        assert gate["verdicts"][0]["on_path"] is True  # 재실행이 경로를 복구했다


class TestReviewVerdictFileIsNotTheAudit:
    def test_review_session_verdicts_file_is_refused_by_the_gate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """검수 도구 판정 파일을 감사로그 자리에 넣는 우회 → 게이트 exit 2(이중 계상 차단).

        실제 `review_session.append_verdict_jsonl`로 만든 파일을 쓴다 — 그 행의 형식이 바뀌면
        이 대조가 먼저 알려 준다.
        """
        corpus = _round_corpus(tmp_path, [_record("wm-a", review_status="approved")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        verdicts = tmp_path / "verdicts.jsonl"
        append_verdict_jsonl(
            verdicts,
            slug="wm-a",
            verdict="approved",
            reviewer_id="kiki",
            review_session_id=uuid.uuid4(),
            failure_code=None,
            failure_note=None,
        )
        proposal = tmp_path / "proposal.txt"
        proposal.write_text("wm-a\n", encoding="utf-8")
        queue = tmp_path / "queue.jsonl"
        queue.write_text("", encoding="utf-8")

        code = gate_main(
            [
                "--proposal", str(proposal),
                "--review-queue", str(queue),
                "--review-events", str(events),
                "--corpus", str(corpus),
                "--backfill-audit", str(verdicts),
                "--max-defect-rate", "0.99",
            ]
        )  # fmt: skip

        assert code == 2
        assert "ReviewVerdictRowNotStampAudit" in capsys.readouterr().out


class TestReport:
    def test_stdout_is_json_and_stderr_carries_the_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a"), _record("wm-b")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        code, report, err = _run(corpus, events, capsys)

        assert code == report["exit_code"] == 0
        assert report["audit_path"] == str(_audit(corpus))
        assert err.startswith("[각인 기록] 각인 1건(approved 1)")

    def test_run_bridge_stamps_the_injected_clock(self, tmp_path: Path) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)

        result = bridge.run_bridge(
            corpus_path=corpus, review_events=[events], now_utc=lambda: _FIXED_NOW
        )

        assert result.exit_code == 0 and result.written is True
        assert _lines(_audit(corpus))[0]["stamped_at"] == _FIXED_NOW.isoformat()


def _edit_content(corpus: Path, slug: str, **changes: Any) -> None:
    """승인 뒤 손편집 흉내 — 한 레코드의 내용 키만 바꾼다(줄 수 보존 단언 — 제자리 편집 절단 방지)."""
    lines = corpus.read_text(encoding="utf-8").splitlines()
    rewritten = []
    for line in lines:
        row = json.loads(line)
        if row["slug"] == slug:
            row.update(changes)
            line = json.dumps(row, ensure_ascii=False)
        rewritten.append(line)
    assert len(rewritten) == len(lines)
    corpus.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


class TestContentFingerprint:
    """[EOS-27 ②] 각인 전에 '검수자가 본 내용이 지금 그대로인가'를 가른다 — 음성·양성 대조 쌍.

    모든 테스트는 같은 회차에 **손대지 않은 대조군 레코드**(`wm-ok`)를 함께 둔다: 대조군이 각인되면
    도구가 무차별 거부가 아님이 보이고, 대상 레코드가 각인되지 않으면 변별이 보인다.
    """

    def test_content_edited_after_review_is_not_stamped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-ok"), _record("wm-edit")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-ok", "approved", minute=1)
        _review(events, "wm-edit", "approved", minute=2)
        _edit_content(corpus, "wm-edit", answer="2")  # 승인 뒤 정답을 손으로 바꿨다

        code, report, err = _run(corpus, events, capsys)

        assert code == 1  # 주의 필요(충돌과 같은 부류)
        assert report["stamped_slugs"] == ["wm-ok"]  # 대조군은 각인
        status = {row["slug"]: row.get("review_status") for row in _lines(corpus)}
        assert status == {"wm-ok": "approved", "wm-edit": None}  # 대상은 빈 칸 그대로
        (change,) = report["content_changed"]
        assert change["slug"] == "wm-edit" and change["human_verdict"] == "approved"
        assert change["reviewed_fingerprint"] != change["current_fingerprint"]
        assert change["exposure_risk"] is False  # 아직 노출값이 아니다
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-ok"]  # 감사 행도 없다
        assert "검수 후 내용 변경 1" in err and "wm-edit" in err

    def test_rejection_of_changed_content_is_also_not_stamped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """반려도 '본 내용'에 대한 판정이다 — 내용이 바뀌었으면 새 내용은 반려된 적이 없다."""
        corpus = _round_corpus(tmp_path, [_record("wm-ok"), _record("wm-rej")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-ok", "approved", minute=1)
        _review(events, "wm-rej", "rejected", minute=2)
        _edit_content(corpus, "wm-rej", answer="2")

        code, report, _err = _run(corpus, events, capsys)

        assert code == 1
        assert report["stamped_slugs"] == ["wm-ok"]
        assert [c["slug"] for c in report["content_changed"]] == ["wm-rej"]
        assert {row["slug"]: row.get("review_status") for row in _lines(corpus)}["wm-rej"] is None

    def test_edit_after_stamping_is_reported_even_though_value_already_matches(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """EOS-136 §8의 사각 그 자체 — 각인 뒤 내용 편집. 값(approved)은 그대로라 예전엔
        `already_stamped`("할 일 없음")로 접혔다. 지금은 노출 위험 있는 내용 변경으로 보고한다."""
        corpus = _round_corpus(tmp_path, [_record("wm-ok"), _record("wm-late")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-ok", "approved", minute=1)
        _review(events, "wm-late", "approved", minute=2)
        code, _report, _err = _run(corpus, events, capsys)
        assert code == 0
        _edit_content(corpus, "wm-late", answer_explanation="해설을 몰래 고쳤다")

        code, report, _err = _run(corpus, events, capsys)

        assert code == 1
        assert report["already_stamped"] == ["wm-ok"]  # 대조군은 여전히 '할 일 없음'
        (change,) = report["content_changed"]
        assert change["slug"] == "wm-late"
        assert change["current"] == "approved" and change["exposure_risk"] is True
        assert report["exposure_risk"] == 1
        # 도구는 코퍼스도 감사도 더 쓰지 않았다 — 격리는 사람 절차다.
        assert [row["slug"] for row in _lines(_audit(corpus))] == ["wm-ok", "wm-late"]

    def test_stamping_itself_does_not_look_like_a_content_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """각인이 쓰는 `review_status`는 지문에서 빠진다 — 아니면 각인 직후 전건이 '변경'으로 보인다."""
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        assert _run(corpus, events, capsys)[0] == 0
        assert _lines(corpus)[0]["review_status"] == "approved"

        code, report, _err = _run(corpus, events, capsys)  # 2회차
        assert code == 0 and report["content_changed"] == []
        assert report["already_stamped"] == ["wm-a"]

    def test_event_without_fingerprint_is_held_not_stamped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """'모름'은 '일치'가 아니다 — 지문 없는 옛 이벤트의 승인을 각인하면 사각이 그대로 열려 있다."""
        corpus = _round_corpus(tmp_path, [_record("wm-ok"), _record("wm-legacy")])
        original_legacy = [row for row in _lines(corpus) if row["slug"] == "wm-legacy"]
        events = tmp_path / "events.jsonl"
        _review(events, "wm-ok", "approved", minute=1)
        _review(events, "wm-legacy", "approved", minute=2, fingerprint=None)

        code, report, err = _run(corpus, events, capsys)

        assert code == 1
        assert report["stamped_slugs"] == ["wm-ok"]
        assert report["fingerprint_unverifiable"] == ["wm-legacy"]
        assert [row for row in _lines(corpus) if row["slug"] == "wm-legacy"] == original_legacy
        assert "wm-legacy" not in {row["slug"] for row in _lines(_audit(corpus))}
        assert "지문 없어 보류 1" in err

    def test_rereview_with_a_fingerprint_unblocks_the_held_record(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """해금 경로 = 재검수. 파일 순서상 마지막 종결이 최신 판정이라 새 이벤트가 이긴다."""
        corpus = _round_corpus(tmp_path, [_record("wm-legacy")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-legacy", "approved", minute=1, fingerprint=None)
        assert _run(corpus, events, capsys)[1]["fingerprint_unverifiable"] == ["wm-legacy"]

        _review(events, "wm-legacy", "approved", minute=5)  # 지문을 싣는 재검수

        code, report, _err = _run(corpus, events, capsys)
        assert code == 0 and report["stamped_slugs"] == ["wm-legacy"]

    def test_rereview_after_an_edit_unblocks_the_changed_record(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """내용 변경도 같은 경로로 해소된다 — 고쳐진 지금 내용을 사람이 다시 보고 승인하면 통과."""
        corpus = _round_corpus(tmp_path, [_record("wm-edit")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-edit", "approved", minute=1)
        _edit_content(corpus, "wm-edit", answer="2")
        assert _run(corpus, events, capsys)[0] == 1

        edited_fp = review_content_fingerprint({**_record("wm-edit"), "answer": "2"})
        _review(events, "wm-edit", "approved", minute=5, fingerprint=edited_fp)

        code, report, _err = _run(corpus, events, capsys)
        assert code == 0 and report["stamped_slugs"] == ["wm-edit"]

    def test_filled_record_with_unknown_fingerprint_keeps_the_existing_buckets(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """이미 채워진 레코드는 쓸 것이 없다 — 지문 없음이 새 버킷을 만들지 않고 기존 규칙(불가침)을 따른다."""
        corpus = _round_corpus(
            tmp_path, [_record("wm-same", "approved"), _record("wm-diff", "pending")]
        )
        events = tmp_path / "events.jsonl"
        _review(events, "wm-same", "approved", minute=1, fingerprint=None)
        _review(events, "wm-diff", "approved", minute=2, fingerprint=None)

        code, report, _err = _run(corpus, events, capsys)

        assert report["already_stamped"] == ["wm-same"]
        assert [c["slug"] for c in report["conflicts"]] == ["wm-diff"]
        assert report["fingerprint_unverifiable"] == [] and report["content_changed"] == []
        assert code == 1  # 충돌이 있으므로(기존 규칙 그대로)

    def test_edit_pending_verdict_is_still_just_held(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """손질 승인은 각인할 값이 없어 지문 대조 대상이 아니다 — 내용이 바뀌어도 '보류'로 남는다
        (EOS-27 ④ 판정: 손질 승인은 지문이 있어도 재검수 없이 해금되지 않는다)."""
        corpus = _round_corpus(tmp_path, [_record("wm-e")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-e", "approved_with_edit", minute=1)
        _edit_content(corpus, "wm-e", answer="손질 반영")  # 손질을 코퍼스에 반영했다

        code, report, _err = _run(corpus, events, capsys)

        assert code == 0
        assert report["held_edit_pending"] == ["wm-e"]
        assert report["content_changed"] == [] and report["stamped"] == 0

    def test_audit_row_carries_the_reviewed_fingerprint(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-a")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-a", "approved", minute=1)
        _run(corpus, events, capsys)
        (row,) = _lines(_audit(corpus))
        assert row["content_fingerprint"] == review_content_fingerprint(_record("wm-a"))

    def test_dry_run_reports_content_change_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = _round_corpus(tmp_path, [_record("wm-edit")])
        events = tmp_path / "events.jsonl"
        _review(events, "wm-edit", "approved", minute=1)
        _edit_content(corpus, "wm-edit", answer="2")
        before = corpus.read_bytes()

        code, report, _err = _run(corpus, events, capsys, "--dry-run")

        assert code == 1 and report["dry_run"] is True and report["written"] is False
        assert [c["slug"] for c in report["content_changed"]] == ["wm-edit"]
        assert corpus.read_bytes() == before and not _audit(corpus).exists()
