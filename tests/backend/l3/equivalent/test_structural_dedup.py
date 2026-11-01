"""EOS-204 구조적 중복 사전 차단(`l3/equivalent/structural_dedup.py`).

회귀 픽스처는 EOS-197 회차 실측 2쌍(검수 큐 26↔30 · 7↔10)이다. 대조군은 **함수만 같고 조건이 다른**
문항 — 대조군 없이 검출 쪽만 고정하면 "함수가 같으면 전부 중복"이라는 과잉 병합이 통과한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.l3.equivalent.structural_dedup import (
    main,
    split_structural_duplicates,
    structural_signature,
)

_REPO = Path(__file__).resolve().parents[4]
_RUNS = _REPO / "data" / "runs"


def _row(slug: str, question: str, answer: str) -> str:
    return json.dumps(
        {"slug": slug, "question_text": question, "answer": answer}, ensure_ascii=False
    )


def _seat(run: str) -> list[str]:
    path = _RUNS / run / "cu.jsonl"
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestEos197Pairs:
    def test_recorded_round_drops_exactly_the_two_reviewed_pairs(self) -> None:
        local, openrouter = _seat("eos197-a6-local"), _seat("eos197-a6-openrouter")
        assert (len(local), len(openrouter)) == (3, 27)  # 표본 크기부터 고정(스캔 0건 방지)
        kept, dropped = split_structural_duplicates([local, openrouter])
        assert len(kept) == 28
        # Kiki 판정과 같다 — 앞서 나온 7번·26번이 남고 10번·30번이 빠진다.
        assert {(d.slug, d.duplicate_of, d.reason) for d in dropped} == {
            ("wm-gen-calc1-9e4ec39eaadd", "wm-gen-calc1-580d11379fec", "structural_duplicate"),
            ("wm-gen-calc1-c42808b25a8f", "wm-gen-calc1-cf311fa5bf53", "structural_duplicate"),
        }

    def test_queue_order_matches_review_queue_after_dropping(self) -> None:
        """기존 큐 조립과 같은 순서(좌석 번갈아)다 — 실제 검수 큐에서 두 건만 빠진 순서와 같다."""
        kept, _ = split_structural_duplicates(
            [_seat("eos197-a6-local"), _seat("eos197-a6-openrouter")]
        )
        review = (_RUNS / "eos197-a6-review" / "canary_review_queue.jsonl").read_text(
            encoding="utf-8"
        )
        expected = [
            json.loads(ln)["slug"]
            for ln in review.splitlines()
            if ln.strip()
            and json.loads(ln)["slug"]
            not in {"wm-gen-calc1-9e4ec39eaadd", "wm-gen-calc1-c42808b25a8f"}
        ]
        assert [json.loads(ln)["slug"] for ln in kept] == expected


class TestSignature:
    _TANGENT_A = "삼차함수 y = x^3 - 6x^2 + 9x + 1 의 그래프 위의 점 중 x좌표가 2인 점에서의 접선의 y절편을 구하시오."
    _TANGENT_B = "다항함수 f(x) = x^3 - 6x^2 + 9x + 1 의 그래프 위의 점 (2, 3)에서 그은 접선의 y절편을 구하시오."

    def test_same_problem_with_different_wording_matches(self) -> None:
        a = structural_signature({"question_text": self._TANGENT_A, "answer": "9"})
        b = structural_signature({"question_text": self._TANGENT_B, "answer": "9"})
        assert a is not None and a == b

    @pytest.mark.parametrize(
        ("question", "answer"),
        [
            # 대조군 ① — 함수는 같고 접점이 다르다(정답도 다르다)
            (
                "다항함수 f(x) = x^3 - 6x^2 + 9x + 1 의 그래프 위의 점 (3, 1)에서 그은 접선의 y절편",
                "-26",
            ),
            # 대조군 ② — 함수·정답이 같아도 묻는 것이 다르다(접선의 기울기)
            (
                "다항함수 f(x) = x^3 - 6x^2 + 9x + 1 의 그래프 위의 점 (2, 3)에서의 접선의 기울기",
                "9",
            ),
            # 대조군 ③ — 함수는 같고 점도 같은데 정답이 다르다(다른 양을 물음)
            (
                "다항함수 f(x) = x^3 - 6x^2 + 9x + 1 의 그래프 위의 점 (2, 3)에서 그은 접선의 x절편",
                "-1/3",
            ),
        ],
    )
    def test_same_function_with_different_condition_does_not_match(
        self, question: str, answer: str
    ) -> None:
        base = structural_signature({"question_text": self._TANGENT_B, "answer": "9"})
        other = structural_signature({"question_text": question, "answer": answer})
        assert other is not None and other != base

    def test_constant_shift_with_same_derivative_and_answer_matches(self) -> None:
        """7↔10 — 상수항만 다르고 도함수·정답이 같으면 같은 문항이다(Kiki 판정)."""
        a = structural_signature(
            {
                "question_text": "f(x) = x^3 - 3x^2 + 1 에 대하여 f(x) = k 가 서로 다른 세 실근을 갖는 정수 k의 개수",
                "answer": "3",
            }
        )
        b = structural_signature(
            {
                "question_text": "f(x) = x^3 - 3x^2 + 4 에 대하여 f(x) = k 가 서로 다른 세 실근을 갖는 정수 k의 개수",
                "answer": "3",
            }
        )
        assert a is not None and a == b

    def test_constant_shift_with_different_answer_does_not_match(self) -> None:
        """상수항이 정답을 바꾸는 문항(극댓값)은 도함수가 같아도 병합되지 않는다."""
        a = structural_signature({"question_text": "f(x) = x^3 - 3x + 1 의 극댓값", "answer": "3"})
        b = structural_signature({"question_text": "f(x) = x^3 - 3x + 4 의 극댓값", "answer": "6"})
        assert a is not None and b is not None and a != b

    def test_root_problems_compare_equations_up_to_scale(self) -> None:
        a = structural_signature(
            {"question_text": "이차방정식 x^2 - 6x + 8 = 0 의 큰 근", "answer": "4"}
        )
        b = structural_signature(
            {"question_text": "이차방정식 2x^2 - 12x + 16 = 0 의 큰 근", "answer": "4"}
        )
        c = structural_signature(
            {"question_text": "이차방정식 x^2 - 7x + 12 = 0 의 큰 근", "answer": "4"}
        )
        assert a is not None and a == b and a != c

    def test_answers_compared_by_value(self) -> None:
        a = structural_signature({"question_text": self._TANGENT_B, "answer": "9"})
        b = structural_signature({"question_text": self._TANGENT_B, "answer": "18/2"})
        assert a == b

    def test_unreadable_question_has_no_signature(self) -> None:
        assert structural_signature({"question_text": "둘레를 구하시오.", "answer": "28"}) is None


class TestSplit:
    def test_same_seat_duplicate_is_dropped(self) -> None:
        """같은 좌석 안의 중복도 걸린다 — EOS-197 2쌍은 둘 다 openrouter 좌석 안이었다."""
        seat = [
            _row("a", TestSignature._TANGENT_A, "9"),
            _row("b", TestSignature._TANGENT_B, "9"),
        ]
        kept, dropped = split_structural_duplicates([seat])
        assert [json.loads(k)["slug"] for k in kept] == ["a"]
        assert [(d.slug, d.duplicate_of, d.seat_index) for d in dropped] == [("b", "a", 0)]

    def test_cross_seat_slug_duplicate_still_dropped(self) -> None:
        """기존 slug 검사 축을 잃지 않는다(하나로 합침 — acceptance ④)."""
        same = _row("s", TestSignature._TANGENT_A, "9")
        kept, dropped = split_structural_duplicates([[same], [same]])
        assert len(kept) == 1
        assert [(d.slug, d.reason, d.seat_index) for d in dropped] == [("s", "slug_duplicate", 1)]

    def test_unreadable_rows_are_not_merged(self) -> None:
        """서명이 없는 행끼리는 구조로 병합하지 않는다(모른다 ≠ 같다)."""
        rows = [_row("p", "둘레를 구하시오.", "28"), _row("q", "넓이를 구하시오.", "28")]
        kept, dropped = split_structural_duplicates([rows])
        assert len(kept) == 2 and dropped == []


class TestCli:
    def test_writes_queue_and_dropped_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        seat = tmp_path / "cu.jsonl"
        seat.write_text(
            _row("a", TestSignature._TANGENT_A, "9")
            + "\n"
            + _row("b", TestSignature._TANGENT_B, "9")
            + "\n",
            encoding="utf-8",
        )
        queue, dropped = tmp_path / "q.jsonl", tmp_path / "dropped.jsonl"
        assert main(["--seat", str(seat), "--queue", str(queue), "--dropped", str(dropped)]) == 0
        out = capsys.readouterr().out
        assert "STRUCT_DUP=1" in out and "QUEUE_WRITTEN=True QUEUE_LINES=1" in out
        assert json.loads(dropped.read_text(encoding="utf-8"))["reason"] == "structural_duplicate"

    def test_refuses_to_overwrite_existing_queue(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.jsonl"
        queue.write_text("x\n", encoding="utf-8")
        args = [
            "--seat",
            str(tmp_path / "none.jsonl"),
            "--queue",
            str(queue),
            "--dropped",
            str(tmp_path / "d"),
        ]
        assert main(args) == 1
        assert queue.read_text(encoding="utf-8") == "x\n"


def test_same_function_and_answer_at_different_point_does_not_match() -> None:
    """점 칸의 반례 — s′(t) = 3t² − 12t + 9는 t = 0과 t = 4에서 모두 9다(정답이 같아도 다른 문항)."""
    base = "수직선 위를 움직이는 점 P의 위치가 s(t) = t^3 - 6t^2 + 9t + 2 이다."
    a = structural_signature({"question_text": base + " 시각 t = 0에서의 속도", "answer": "9"})
    b = structural_signature({"question_text": base + " 시각 t = 4에서의 속도", "answer": "9"})
    assert a is not None and b is not None and a != b


def test_acceleration_is_not_also_counted_as_velocity() -> None:
    """`가속도` 안의 `속도`가 따로 잡히면 속도 문항과 가속도 문항의 '묻는 것' 칸이 겹친다."""
    sig = structural_signature(
        {"question_text": "s(t) = t^3 - 6t^2 + 9t + 2 일 때 t = 1에서의 가속도", "answer": "-6"}
    )
    assert sig is not None and sig[0] == ("가속도",)
