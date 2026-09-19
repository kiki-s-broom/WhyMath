"""EOS-121 결함② — **회신 추출이 인코딩을 깨뜨리지 않는가.**

상환하는 사고 (2026-09-19 파일럿 실측)
-------------------------------------
런북 [F]가 회신 파일을 이렇게 만들었다::

    Get-Content <대장> -Tail 1 | Out-File -FilePath reply.json -Encoding utf8

그 결과 한국어가 `?댁감諛⑹젙??`로 깨졌다. 같은 필드를 Python으로 읽으면 정상이었으므로
**파일은 멀쩡하고 표시·재기록 경로가 깨뜨린 것**이다. Windows PowerShell 5.1이 바이트를
`[Console]::OutputEncoding`(한국어 Windows 기본 cp949)으로 디코딩한 뒤 재인코딩하기 때문이며,
`Out-File -Encoding utf8`은 **이미 깨진 문자열**을 성실히 UTF-8로 쓸 뿐이라 막지 못한다
(CLAUDE.md v0.2.24 「셸이 중계하는 제3 도구 출력은 셸을 통과시키지 않는다」).

대책은 경유 자체의 제거다 — **Python이 읽고 Python이 쓴다.**

변별력 (CLAUDE.md 2026-09-01 「보호 장치를 실패 주입 없이 보호로 선언 금지」)
--------------------------------------------------------------------------
- **손상 경로를 주입해 대조**한다: 같은 텍스트를 cp949 왕복시킨 바이트와 우리 산출 바이트가
  **달라야** 한다. 이 대조가 없으면 "UTF-8로 썼다"는 단언은 깨진 문자열을 UTF-8로 쓴
  경우에도 통과한다(그게 정확히 사고 당시의 상태였다).
- **미기록·미측정·0을 각각 다른 문장**으로 내는지 본다. 하나로 접으면 회신을 읽는 사람이
  '측정 실패'를 '0% 달성'으로 읽는다.
- **집행 지점**(정본화 ≠ 집행): 런북 [F]가 실제로 이 경로를 쓰는지, 옛 형태가 사라졌는지.

hermetic: 파일 I/O만 — LLM 0·DB 0·네트워크 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness.problem_corpus_round_reply import (
    extract_round_reply,
    main,
    render_reply_text,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNBOOK = _REPO_ROOT / "docs/ops/eos121_seat_generation_diversity_runbook.md"


def _seat_block(*, seat: str = "openrouter", state: str = "all_on_selected_seat") -> dict[str, Any]:
    """`seat_operating_rates` 산출물의 형태를 그대로 흉내 낸 블록."""
    return {
        "selected_seat": seat,
        "seat_model_pins": ["deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro"],
        "calls_total": 90,
        "calls_with_model_name": 90,
        "calls_on_selected_seat": 90 if state == "all_on_selected_seat" else 0,
        "calls_off_selected_seat": 0 if state == "all_on_selected_seat" else 90,
        "observed_models": {"deepseek/deepseek-v4.1-flash": 90},
        "succeeded": 90,
        "failed": 0,
        "cost_usd_total": 0.42,
        "calls_with_cost": 90,
        "cost_note": "단가 곱셈·청구서 미대조",
        "measured": True,
        "unmeasured_reason": None,
        "declared_not_observed": "선언값 기반이다(EOS-112 관측 축은 아래 observation).",
        "observation": {
            "calls_with_served_model": 90,
            "observed_models": {"deepseek/deepseek-v4.1-flash": 90},
            "declared_vs_served": {
                "comparable": 90,
                "matched": 90,
                "differs": 0,
                "differing_pairs": [],
                "differing_pairs_truncated": False,
                "note": "차이가 곧 이상은 아니다.",
            },
            "retries": {
                "calls_with_retries_measured": 90,
                "retries_total": 3,
                "calls_with_any_retry": 2,
                "note": "None=미계측.",
            },
        },
        "state": state,
    }


def _duplicate_block(*, measured: bool = True) -> dict[str, Any]:
    if not measured:
        return {
            "duplicates_total": 0,
            "measured": False,
            "unmeasured_reason": (
                "이 회차 rejected_duplicate 0건 — 구분할 대상이 없어 비율을 계산할 수 없다"
                "(0%가 아니다)"
            ),
            "classified": 0,
            "classified_rate": None,
            "origin_resolved": 0,
            "origin_resolved_rate": None,
            "counts": {"structural_signature/round": 0, "structural_signature/corpus": 0},
            "by_detector": {"structural_signature": 0},
            "by_origin": {"round": 0, "corpus": 0, "unknown": 0},
            "unknown_detectors": {},
            "unknown_origins": {},
        }
    return {
        "duplicates_total": 25,
        "measured": True,
        "unmeasured_reason": None,
        "classified": 25,
        "classified_rate": 1.0,
        "origin_resolved": 25,
        "origin_resolved_rate": 1.0,
        "counts": {
            "structural_signature/round": 18,
            "structural_signature/corpus": 7,
            "embedding_near/round": 0,
        },
        "by_detector": {"structural_signature": 25, "embedding_near": 0},
        "by_origin": {"round": 18, "corpus": 7, "unknown": 0},
        "unknown_detectors": {},
        "unknown_origins": {},
    }


def _row(**overrides: Any) -> dict[str, Any]:
    """대장 행 1건(JSON) — 기본은 '전 필드가 채워진 좌석 회차'."""
    base: dict[str, Any] = {
        "run_id": "eos121-or-1",
        "out_path": "openrouter.jsonl",
        "attempted": 90,
        "accepted": 61,
        "appended": 61,
        "outcome_counts": {"accepted_stored": 61, "rejected_duplicate": 25, "needs_review": 4},
        "recorded_at": "2026-09-19T03:04:05+00:00",
        "model_name": "deepseek/deepseek-v4.1-flash",
        "cloud_seat": _seat_block(),
        "duplicate_sources": _duplicate_block(),
        "spec_plan": [
            {"spec_id": "quad-largest", "topic_hint": "이차방정식 — 큰 근", "spec": {}},
            {"spec_id": "quad-sum", "topic_hint": "이차방정식 — 두 근의 합", "spec": {}},
        ],
        "spec_outcome_counts": {
            "quad-largest": {"accepted_stored": 30, "rejected_duplicate": 15},
            "quad-sum": {"accepted_stored": 31, "rejected_duplicate": 10},
        },
    }
    base.update(overrides)
    return base


def _write_ledger(path: Path, *rows: dict[str, Any]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


class TestEncodingIsNotRelayedThroughTheShell:
    """① 이 결함 그 자체 — 회신 파일의 한국어가 온전한가."""

    def test_report_file_round_trips_korean(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"

        code = main(["--round", f"openrouter={ledger}", "--out", str(out)])

        assert code == 0
        text = out.read_text(encoding="utf-8-sig")
        assert "좌석(선택): openrouter" in text
        assert "이차방정식 — 큰 근" in text  # em dash — cp949 왕복이 정확히 여기서 깨진다

    def test_bytes_differ_from_the_cp949_round_trip(self, tmp_path: Path) -> None:
        """손상 경로 주입 — cp949로 왕복시킨 바이트와 **달라야** 한다.

        이 대조가 없으면 "UTF-8로 썼다"는 단언은 *이미 깨진 문자열*을 UTF-8로 쓴 경우에도
        통과한다. 그게 정확히 `Out-File -Encoding utf8`이 하던 일이다.
        """
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])

        ours = out.read_bytes()
        clean = out.read_text(encoding="utf-8-sig")
        # PowerShell 5.1이 하던 일: UTF-8 바이트를 cp949로 디코딩한 뒤 다시 인코딩한다.
        mangled = clean.encode("utf-8").decode("cp949", errors="replace").encode("utf-8")

        assert ours != mangled, "산출 바이트가 cp949 왕복 결과와 같다 — 손상 경로를 탔다"
        # 그리고 우리 바이트는 UTF-8로 **손실 없이** 디코딩된다(왕복본은 그렇지 않다).
        assert ours.decode("utf-8-sig") == clean
        assert "�" not in clean and "?" not in clean.replace("?)", "")

    def test_file_carries_a_bom_so_windows_readers_decode_it_as_utf8(self, tmp_path: Path) -> None:
        """BOM을 붙이는 이유 — 회신자가 `Get-Content`·메모장으로 열어 복사하는 경로까지 닫는다.

        PS 5.1의 `Get-Content`는 BOM이 없으면 로케일(cp949)로 디코딩한다. BOM이 있으면
        UTF-8로 디코딩하므로, 이 한 바이트 시퀀스가 회신 경로의 마지막 구멍을 막는다.
        """
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])

        assert out.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_stdout_also_carries_the_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """화면에도 같은 본문이 나온다 — 파일을 못 찾는 회신자를 위한 이중 경로."""
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        main(["--round", f"openrouter={ledger}", "--out", str(tmp_path / "reply.md")])

        captured = capsys.readouterr().out
        assert "EOS-121 좌석별 생성 다양성 회차 — 회신" in captured
        assert "[회신 파일]" in captured


class TestJudgementMaterialIsPresent:
    """② 회신에 판정 재료가 실제로 있는가 — 좌석·중복 출처·spec·outcome·모델."""

    def test_seat_and_duplicate_origins_are_rendered(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert "판정 상태: all_on_selected_seat" in text
        assert "structural_signature/round = 18건" in text
        assert "structural_signature/corpus = 7건" in text
        assert "quad-largest" in text and "quad-sum" in text
        assert "deepseek/deepseek-v4.1-flash" in text
        assert "accepted_stored×61" in text

    def test_zero_combinations_are_not_silently_dropped_from_evidence(self, tmp_path: Path) -> None:
        """화면에서 생략한 0건 조합도 **JSON 증거에는 전건** 남는다(조용한 누락 금지)."""
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        evidence = json.loads(text.split("```json")[1].split("```")[0])
        counts = evidence[0]["round"]["duplicate_sources"]["counts"]
        assert counts["embedding_near/round"] == 0

    def test_two_seats_land_in_one_report_in_argument_order(self, tmp_path: Path) -> None:
        or_ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        an_ledger = _write_ledger(
            tmp_path / "an.rounds.jsonl",
            _row(run_id="eos121-an-1", cloud_seat=_seat_block(seat="anthropic")),
        )
        out = tmp_path / "reply.md"

        code = main(
            [
                "--round",
                f"openrouter={or_ledger}",
                "--round",
                f"anthropic={an_ledger}",
                "--out",
                str(out),
            ]
        )
        text = out.read_text(encoding="utf-8-sig")

        assert code == 0
        assert text.index("좌석 라벨: openrouter") < text.index("좌석 라벨: anthropic")
        assert "좌석(선택): anthropic" in text

    def test_last_round_is_used_and_multiple_rounds_are_disclosed(self, tmp_path: Path) -> None:
        """여러 회차가 쌓였으면 **마지막**을 쓰되 그 사실을 감추지 않는다(절단 공개)."""
        ledger = _write_ledger(
            tmp_path / "or.rounds.jsonl",
            _row(run_id="first"),
            _row(run_id="second"),
        )
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert "run_id=second" in text
        assert "2회차가 있다" in text


class TestUnrecordedUnmeasuredAndZeroAreThreeDifferentThings:
    """③ 미기록 / 미측정 / 실측 0 — 셋을 한 문장으로 접지 않는다(모른다 ≠ 아니다)."""

    def test_legacy_row_without_seat_says_unrecorded(self, tmp_path: Path) -> None:
        """구판 행(좌석·중복·spec 필드 없음)은 **미기록**으로 렌더된다 — 0건이 아니다."""
        ledger = _write_ledger(
            tmp_path / "old.rounds.jsonl",
            {
                "run_id": "legacy",
                "out_path": "c.jsonl",
                "attempted": 5,
                "accepted": 1,
                "appended": 1,
                "outcome_counts": {"accepted_stored": 1},
            },
        )
        out = tmp_path / "reply.md"

        code = main(["--round", f"legacy={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert code == 0  # 읽기는 성공했다 — 필드가 없는 것은 로드 실패가 아니다
        assert "좌석: 미기록" in text
        assert "중복 출처: 미기록" in text
        assert "spec 계획: 미기록" in text
        assert "대장만으로는 어느 좌석의 회차인지 알 수 없다" in text
        assert (
            "0건"
            not in text.split("## 기계 판독용 증거")[0].split("좌석: 미기록")[1].split("\n")[0]
        )

    def test_unmeasured_duplicates_are_not_reported_as_zero_percent(self, tmp_path: Path) -> None:
        """중복 0건 회차는 '미측정'이다 — 비율이 `0.0%`로 찍히면 안 된다."""
        ledger = _write_ledger(
            tmp_path / "or.rounds.jsonl",
            _row(duplicate_sources=_duplicate_block(measured=False)),
        )
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        dup_line = next(line for line in text.splitlines() if "중복 출처:" in line)
        assert "미측정" in dup_line
        assert "0.0%" not in dup_line
        assert "0%가 아니다" in text

    def test_measured_duplicates_are_the_control(self, tmp_path: Path) -> None:
        """대조군 — 측정된 회차는 비율이 실제로 찍힌다(항상 '미측정'을 내는 구현 배제)."""
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        dup_line = next(line for line in text.splitlines() if "중복 출처:" in line)
        assert "총 25건 (측정됨)" in dup_line
        assert "100.0%" in dup_line

    def test_measured_block_with_null_rates_renders_undefined_not_zero(
        self, tmp_path: Path
    ) -> None:
        """`measured=true`인데 비율만 `null`인 행도 **미정의**로 낸다(0.0%로 접지 않는다).

        왜 이 픽스처가 필요한가 (CLAUDE.md 2026-09-07 「픽스처가 그 절을 실제로 밟는가」):
        `_ratio`의 None 가지는 위 '미측정' 경로에서 **한 번도 밟히지 않는다** — 그 경로는
        비율을 아예 렌더하지 않고 사유 문장으로 끝나기 때문이다. 그래서 그 가지를 0.0%로
        바꾸는 뮤테이션이 살아남았다(M11 생존 — 2026-09-19 실측). 이 가지가 실제로 지키는
        것은 **대장 행이 우리 산식이 아닌 곳에서 온 경우**다: 대장 필드는 `dict[str, Any]`라
        구판·타 버전이 쓴 블록도 그대로 실린다. 그때 `None * 100`이면 회신 전체가 죽고,
        0.0%로 접으면 모르는 값이 확정 수치가 된다.
        """
        block = _duplicate_block()
        block.update({"classified_rate": None, "origin_resolved_rate": None})
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row(duplicate_sources=block))
        out = tmp_path / "reply.md"

        code = main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert code == 0  # 렌더가 죽지 않는다
        dup_line = next(line for line in text.splitlines() if "중복 출처:" in line)
        assert "미정의" in dup_line
        assert "0.0%" not in dup_line

    def test_unmeasured_seat_states_the_reason(self, tmp_path: Path) -> None:
        """좌석 미측정도 사유를 그대로 옮긴다 — '좌석이 안 돌았다'와 구분된다."""
        seat = _seat_block()
        seat.update(
            {
                "state": "not_measured",
                "measured": False,
                "calls_with_model_name": 0,
                "unmeasured_reason": "model_name이 실린 호출 0건 — 좌석 판정이 정의되지 않는다.",
            }
        )
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row(cloud_seat=seat))
        out = tmp_path / "reply.md"
        main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert "판정 상태: not_measured" in text
        assert "좌석 판정이 정의되지 않는다" in text

    def test_unknown_seat_selector_is_flagged(self, tmp_path: Path) -> None:
        """설정 판독 실패 회차(`selected_seat='unknown'`·핀 0건)는 그 사실을 말한다."""
        seat = _seat_block(seat="unknown", state="none_on_selected_seat")
        seat["seat_model_pins"] = []
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row(cloud_seat=seat))
        out = tmp_path / "reply.md"
        main(["--round", f"unknown-seat={ledger}", "--out", str(out)])

        assert "설정 판독 실패 회차다" in out.read_text(encoding="utf-8-sig")


class TestFailureLeavesEvidence:
    """④ 실패해도 증거가 남는가 (2026-08-22 규칙 ①②) — 그리고 exit code로 말하는가."""

    def test_missing_ledger_still_writes_a_report_and_exits_one(self, tmp_path: Path) -> None:
        out = tmp_path / "reply.md"

        code = main(["--round", f"openrouter={tmp_path / 'nope.rounds.jsonl'}", "--out", str(out)])

        assert code == 1, "읽지 못한 회차를 exit 0으로 보고하면 빈 결과가 성공으로 위장된다"
        assert out.exists(), "실패했다고 보고서를 안 쓰면 원인이 남지 않는다"
        text = out.read_text(encoding="utf-8-sig")
        assert "회차 대장 없음" in text
        assert "nope.rounds.jsonl" in text

    def test_one_bad_seat_does_not_hide_the_good_one(self, tmp_path: Path) -> None:
        """한 좌석이 실패해도 다른 좌석의 재료는 그대로 남는다(부분 산출 보존)."""
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        out = tmp_path / "reply.md"

        code = main(
            [
                "--round",
                f"openrouter={ledger}",
                "--round",
                f"anthropic={tmp_path / 'missing.jsonl'}",
                "--out",
                str(out),
            ]
        )
        text = out.read_text(encoding="utf-8-sig")

        assert code == 1
        assert "판정 상태: all_on_selected_seat" in text  # 성공한 좌석의 재료는 남았다
        assert "회차 대장 없음" in text

    def test_empty_ledger_file_is_not_a_success(self, tmp_path: Path) -> None:
        ledger = tmp_path / "empty.rounds.jsonl"
        ledger.write_text("", encoding="utf-8")
        out = tmp_path / "reply.md"

        code = main(["--round", f"openrouter={ledger}", "--out", str(out)])

        assert code == 1
        assert "유효 행 0건" in out.read_text(encoding="utf-8-sig")

    def test_broken_line_reason_carries_the_exception_type(self, tmp_path: Path) -> None:
        """깨진 줄은 삼키지 않고 **예외 타입명 + 줄 번호**로 남는다(침묵 실패 금지)."""
        ledger = tmp_path / "or.rounds.jsonl"
        ledger.write_text(
            "{이건 JSON이 아니다\n" + json.dumps(_row(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        out = tmp_path / "reply.md"

        code = main(["--round", f"openrouter={ledger}", "--out", str(out)])
        text = out.read_text(encoding="utf-8-sig")

        assert code == 1, "유효 행이 있어도 로드 실패가 있으면 '완전한 회신'이 아니다"
        assert "JSONDecodeError" in text and "line 1" in text
        # 그래도 읽힌 행의 재료는 렌더된다(부분 신뢰가 아니라 부분 보존).
        assert "판정 상태: all_on_selected_seat" in text

    def test_malformed_round_argument_is_rejected_at_argument_time(self, tmp_path: Path) -> None:
        """`라벨=경로` 형식 오류는 exit 2 — 조용히 빈 보고서를 쓰지 않는다."""
        with pytest.raises(SystemExit) as excinfo:
            main(["--round", "경로만줬다", "--out", str(tmp_path / "reply.md")])

        assert excinfo.value.code == 2
        assert not (tmp_path / "reply.md").exists()


class TestPureRendererContract:
    """⑤ 순수 함수 축 — 렌더는 파일 I/O 없이도 같은 답을 낸다(집계 재구현 금지 확인)."""

    def test_extract_reports_row_count_without_mutating_anything(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row(), _row(run_id="b"))
        before = ledger.read_bytes()

        reply = extract_round_reply("openrouter", ledger)

        assert reply.ok is True
        assert reply.total_rows == 2
        assert reply.record is not None and reply.record.run_id == "b"
        assert ledger.read_bytes() == before  # 읽기 전용

    def test_render_is_deterministic(self, tmp_path: Path) -> None:
        ledger = _write_ledger(tmp_path / "or.rounds.jsonl", _row())
        first = render_reply_text([extract_round_reply("openrouter", ledger)])
        second = render_reply_text([extract_round_reply("openrouter", ledger)])

        assert first == second


def _f_block_code() -> str:
    """런북 [F]의 **powershell 펜스 안**(= 실제로 붙여넣어 실행될 줄)만 돌려준다.

    산문이 아니라 **구성된 결과**를 검사한다(CLAUDE.md 2026-09-01 ①) — [F]의 산문은 옛
    형태(`Get-Content … | Out-File`)를 *사고 경위로 인용*하므로, 섹션 전문을 대상으로 금지
    문자열을 찾으면 정정된 런북이 영원히 red다. 검사는 실행되는 줄에만 걸어야 변별력이 있다.
    """
    section = _RUNBOOK.read_text(encoding="utf-8").split("## [F]", 1)[1]
    blocks = []
    inside = False
    current: list[str] = []
    for line in section.splitlines():
        if not inside and line.strip().lower() == "```powershell":
            inside = True
            current = []
            continue
        if inside and line.strip() == "```":
            inside = False
            blocks.append("\n".join(current))
            continue
        if inside:
            current.append(line)
    assert blocks, "[F]에 powershell 펜스가 없다 — 이 검사가 볼 자리가 사라졌다"
    return "\n".join(blocks)


class TestRunbookActuallyUsesThisPath:
    """⑥ 집행 지점 — 정본화 ≠ 집행. 런북 [F]가 실제로 이 경로를 쓰는가."""

    def test_runbook_no_longer_pipes_the_ledger_through_powershell(self) -> None:
        f_section = _f_block_code()

        assert "Get-Content" not in f_section or "-Tail 1" not in f_section, (
            "런북 [F]가 여전히 `Get-Content … -Tail 1`로 대장을 읽는다 — "
            "PowerShell이 바이트를 중계하면 cp949 왕복으로 한국어가 깨진다."
        )
        assert "Out-File" not in f_section, (
            "런북 [F]가 여전히 `Out-File`로 회신을 쓴다 — 이미 깨진 문자열을 성실히 UTF-8로 "
            "쓸 뿐이라 이 사고를 막지 못한다."
        )

    def test_runbook_invokes_this_module(self) -> None:
        f_section = _f_block_code()

        assert "problem_corpus_round_reply" in f_section
        assert "--round" in f_section and "--out" in f_section

    def test_runbook_forces_utf8_before_the_python_call(self) -> None:
        """콘솔 디코딩 축 — 화면 표시가 깨지지 않게 OutputEncoding을 UTF-8로 둔다."""
        f_section = _f_block_code()

        assert "PYTHONUTF8" in f_section
        assert "OutputEncoding" in f_section

    def test_runbook_write_block_refuses_by_itself(self) -> None:
        """쓰기 블록은 선행 판정을 **재검사해 거부**한다(HARN-106 — 출력은 흐름을 멈추지 못한다)."""
        f_section = _f_block_code()

        assert "WRITE_REFUSED=True" in f_section
        assert "} else {" in f_section  # 닫는 중괄호와 같은 줄 — 대화형 파서 함정 회피
