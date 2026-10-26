"""P3-66 그림자 관측 수확·활성화 판정 CLI — 각 기준이 **의도한 종료 코드**를 내는지, 그리고 그 판정이 진짜인지.

이 파일의 원칙은 CLAUDE.md "보호 장치를 실패 주입 없이 '보호 있음'으로 선언 금지"다. 정상 입력의
PASS(0)만으로는 판정기의 증거가 되지 않으므로, 기준마다 그 기준을 **어기는 상태를 주입**해 의도한
종료 코드가 나오는지 동결한다(acceptance ④):

  · 정답 오발화 1건 주입              → FAIL(1)            (C2)
  · 우연 수준 발화율 주입              → FAIL(1)            (C3)
  · 한 문항 쏠림 주입                  → FAIL(1)            (C4)
  · 오답 표본 부족 주입                → 측정 불가(3)        (C1)
  · 정답 표본 부족 주입                → 측정 불가(3)        (C2 표본)
  · 빈 파일·형식 오류·은행에 없는 문항  → 측정 불가(3)        (입력·C0)
  · `None`(모름)은 오답으로 세지 않는다                       (모른다 ≠ 아니다)

**주입이 그 기준만 건드리는지**도 함께 단언한다 — 종료 코드만 보면 다른 기준이 대신 실패해도 같은
숫자가 나와, 판정 로직 하나를 지워도 테스트가 초록으로 남는다(뮤테이션 생존). 그래서 매 시나리오가
기준별 판정을 전부 확인한다.

기준선(C3)은 **실제 엔진**으로 잰다. 임시 문항은행의 지문·정답은 저장소 문항은행에서 그대로 복사한다
(이 파일이 손으로 적지 않는다). 예외 하나 — 승인 문항은행에는 정답이 유한 실수가 아닌 문항이 실측상
없어서(2026-10-26), "기준선을 정의할 수 없는 문항" 경로는 **합성 문항 1건**으로 밟는다.

로그 줄은 `DerivativeShadowRecord(...).model_dump_json()`으로 합성한다 — 운영 로거와 같은 형식이다
(`api/_attempt_misconception_scan.py::_emit_adapter_shadow_records`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import get_settings
from whymath_backend.harness import attempt_scan_shadow_harvest as harvest
from whymath_backend.l4.misconception import answer_signature as signature_module
from whymath_backend.l4.misconception.answer_signature import (
    DerivativeShadowRecord,
    scan_attempt_answer,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_BANK = (
    _REPO_ROOT / "data" / "corpus" / "problem_bank_p3_calculus1_diff_v0" / "problems.jsonl"
)

# 엔진이 질문을 읽고(applicable) 정답이 정수인 실제 승인 문항 — 기준선 계산이 빠른 것으로 골랐다.
P_A = "83f4032e-1da7-5076-b974-fc62dcfcac9f"  # f(x)=x^3, f'(-2)
P_B = "1fe0ab77-9e31-5cc5-a13e-291e76e40d6f"  # f(x)=x, f'(2)
P_C = "1f03b9a9-c7b8-558c-a5c6-f88c5d2ef4cc"  # f(x)=x, f'(-5)
P_D = "aeccf5bf-3ce6-526f-b2fe-daa161fa2fb1"  # f(x)=6x^2, f'(-1)
#: 우연 발화율이 0인 실제 문항(정답±30 어디에도 규칙 오답 값이 없다) — '기준선 0' 경로용.
P_ZERO = "dafb392b-3ed2-5a17-8dc4-5bd3df67cc42"  # f(x)=x^8, f'(3)
REAL = (P_A, P_B, P_C, P_D)

#: 합성 — 정답이 식이라 기준선(정답 ± 정수)을 정의할 수 없는 문항(승인 은행에는 실재하지 않는다).
P_NONNUMERIC = "synthetic-nonnumeric-answer-0001"
#: 문항은행에 승인 아닌 상태로만 있는 문항 — 승인 문항만 읽으므로 '없음'으로 보여야 한다.
P_STAGING = "synthetic-staging-only-0001"
#: 문항은행 어디에도 없는 문항.
P_MISSING = "not-in-any-bank-0001"


# ── 픽스처 ─────────────────────────────────────────────────────────────────────────────────


def _source_rows() -> dict[str, dict[str, Any]]:
    wanted = {*REAL, P_ZERO}
    rows: dict[str, dict[str, Any]] = {}
    for line in _SOURCE_BANK.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["problem_id"] in wanted and row.get("review_status") == "approved":
            rows[row["problem_id"]] = row
    assert set(rows) == wanted, f"저장소 문항은행에서 못 찾은 문항: {sorted(wanted - set(rows))}"
    return rows


@pytest.fixture(scope="module")
def corpus_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """임시 문항은행 — 실제 승인 문항 5건(복사) + 합성 2건(식 정답·스테이징 전용)."""
    root = tmp_path_factory.mktemp("corpus")
    bank = root / "problem_bank_test_v0"
    bank.mkdir()
    rows = [
        {
            "problem_id": r["problem_id"],
            "question_text": r["question_text"],
            "answer": r["answer"],
            "review_status": "approved",
        }
        for r in _source_rows().values()
    ]
    rows.append(
        {
            "problem_id": P_NONNUMERIC,
            "question_text": "함수 f(x) = x^2에 대하여 도함수 f'(x)를 구하시오.",
            "answer": "2*x",
            "review_status": "approved",
        }
    )
    rows.append(
        {
            "problem_id": P_STAGING,
            "question_text": "함수 f(x) = x^4에 대하여 f'(1)의 값을 구하시오.",
            "answer": "4",
            "review_status": "staging",
        }
    )
    (bank / "problems.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return root


@pytest.fixture(scope="module")
def baseline_cache() -> harvest.BaselineCache:
    """기준선은 문항당 엔진 60회라 비싸다 — 이 파일의 실행들이 공유한다(내용은 실행마다 같다)."""
    return {}


@dataclass(frozen=True, slots=True)
class Block:
    """같은 모양의 로그 줄 `count`개 — (문항, 분류, 발화 여부)."""

    problem_id: str
    kind: str  # "wrong" | "correct" | "unknown" | "not_applicable"
    count: int
    fired: bool = False


def _record(kind: str, fired: bool) -> str:
    applicable = kind != "not_applicable"
    correct: bool | None = {"wrong": False, "correct": True}.get(kind)
    return DerivativeShadowRecord(
        rules_total=12,
        applicable=applicable,
        answer_is_correct=correct,
        fired=fired,
        added_candidate_ids=("power-rule-step-omitted",) if fired else (),
        rule_ids=("power_rule_step_omitted.derivative_at",) if fired else (),
        changes_top1=fired,
        attribution_unclear=False,
    ).model_dump_json()


def _lines(blocks: list[Block]) -> list[str]:
    out: list[str] = []
    for b in blocks:
        line = json.dumps(
            {"problem_id": b.problem_id, "adapter_records": [_record(b.kind, b.fired)]}
        )
        out.extend([line] * b.count)
    return out


def _spread(kind: str, per_problem: int, fired_per_problem: int) -> list[Block]:
    """REAL 4문항에 같은 양을 고르게 — 발화 비중이 문항당 25%라 쏠림 기준(30%)을 넘지 않는다."""
    blocks: list[Block] = []
    for pid in REAL:
        blocks.append(Block(pid, kind, fired_per_problem, fired=True))
        blocks.append(Block(pid, kind, per_problem - fired_per_problem))
    return blocks


def _passing_blocks() -> list[Block]:
    """모든 기준을 통과하는 표본: 오답 400(발화 100 = 25%) · 정답 120(오발화 0)."""
    return _spread("wrong", 100, 25) + _spread("correct", 30, 0)


def _write(tmp_path: Path, lines: list[str], name: str = "shadow.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def _run(
    tmp_path: Path,
    lines: list[str],
    corpus_root: Path,
    cache: harvest.BaselineCache,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any]]:
    """CLI를 `--json`으로 돌려 (종료 코드, 보고서 dict)를 돌려준다 — 판정은 종료 코드로 한다."""
    path = _write(tmp_path, lines)
    code = harvest.main(
        [str(path), "--corpus-root", str(corpus_root), "--json"], baseline_cache=cache
    )
    out = capsys.readouterr().out
    return code, json.loads(out)


def _criteria(report: dict[str, Any]) -> dict[str, str]:
    return {c["criterion"].split()[0]: c["verdict"] for c in report["criteria"]}


def _criterion(report: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in report["criteria"] if c["criterion"].startswith(cid))


ALL_PASS = {"C0": "PASS", "C1": "PASS", "C2": "PASS", "C3": "PASS", "C4": "PASS"}


@pytest.fixture(autouse=True)
def _settings_untouched() -> Iterator[None]:
    """수확이 그림자 모드 환경변수·설정 캐시를 **원복**하는지 매 테스트 뒤에 확인한다."""
    before_env = os.environ.get("WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE")
    before_mode = get_settings().l4_derivative_signature_mode
    yield
    assert os.environ.get("WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE") == before_env
    assert get_settings().l4_derivative_signature_mode == before_mode


# ── 판정 시나리오 ──────────────────────────────────────────────────────────────────────────


class TestVerdicts:
    def test_passing_sample_exits_0_with_every_criterion_pass(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        code, report = _run(
            tmp_path, _lines(_passing_blocks()), corpus_root, baseline_cache, capsys
        )
        assert code == harvest.EXIT_PASS == 0
        assert _criteria(report) == ALL_PASS
        assert report["verdict"] == "PASS"
        assert report["wrong_attempts"] == 400
        assert report["correct_attempts"] == 120
        assert report["fired_wrong"] == 100
        assert report["fire_rate"] == pytest.approx(0.25)
        assert report["reach_rate"] == pytest.approx(1.0)

    def test_one_correct_misfire_fails_regardless_of_everything_else(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = _passing_blocks() + [Block(P_A, "correct", 1, fired=True)]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_FAIL == 1
        assert _criteria(report) == {**ALL_PASS, "C2": "FAIL"}
        assert report["fired_correct"] == 1

    def test_misfire_fails_even_when_correct_sample_is_small(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """확인된 오발화는 정답 표본 100건 미만이어도 '측정 불가'로 물러지지 않는다."""
        blocks = _spread("wrong", 100, 25) + [
            Block(P_A, "correct", 5),
            Block(P_B, "correct", 1, fired=True),
        ]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_FAIL
        assert _criteria(report)["C2"] == "FAIL"

    def test_chance_level_fire_rate_fails_c3(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """발화율 2%(기준선 ≈ 2.1%와 같은 수준)는 우연과 구별되지 않는다 → FAIL."""
        blocks = _spread("wrong", 100, 2) + _spread("correct", 30, 0)
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_FAIL
        assert _criteria(report) == {**ALL_PASS, "C3": "FAIL"}
        c3 = _criterion(report, "C3")["values"]
        assert c3["fire_rate"] == pytest.approx(0.02)
        assert c3["wilson_lower"] < c3["threshold"]
        # 우연 수준 주입이 성립하려면 발화율이 기준선과 같은 자릿수여야 한다(주입 자체의 실재).
        assert 0.5 * c3["weighted_baseline"] <= c3["fire_rate"] <= 2.0 * c3["weighted_baseline"]

    def test_zero_baseline_with_zero_fires_is_not_above_chance(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """기준선 0이면 임계도 0 — 발화 0건이 '하한 0 ≥ 0'으로 공허하게 통과하면 안 된다."""
        blocks = [Block(P_ZERO, "wrong", 300), Block(P_ZERO, "correct", 100)]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        c3 = _criterion(report, "C3")["values"]
        assert c3["weighted_baseline"] == 0.0  # 픽스처 전제: 정말로 기준선 0인 문항이다
        assert code == harvest.EXIT_FAIL
        assert _criteria(report) == {**ALL_PASS, "C3": "FAIL"}

    def test_single_problem_skew_fails_c4(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = [
            Block(P_A, "wrong", 70, fired=True),
            Block(P_A, "wrong", 30),
            *[Block(pid, "wrong", 10, fired=True) for pid in (P_B, P_C, P_D)],
            *[Block(pid, "wrong", 90) for pid in (P_B, P_C, P_D)],
            *_spread("correct", 30, 0),
        ]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_FAIL
        assert report["wrong_attempts"] == 400 >= harvest.MIN_WRONG_ATTEMPTS  # 표본 충족 전제
        assert _criteria(report) == {**ALL_PASS, "C4": "FAIL"}
        c4 = _criterion(report, "C4")["values"]
        assert c4["max_share_problem_id"] == P_A
        assert c4["max_share"] == pytest.approx(0.70)

    def test_share_at_exactly_thirty_percent_is_not_skew(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """경계: 30%는 '넘지' 않는다 — 초과만 FAIL이다(사전 등록 문구 그대로)."""
        blocks = [
            Block(P_A, "wrong", 30, fired=True),
            Block(P_A, "wrong", 70),
            Block(P_B, "wrong", 30, fired=True),
            Block(P_B, "wrong", 70),
            Block(P_C, "wrong", 20, fired=True),
            Block(P_C, "wrong", 80),
            Block(P_D, "wrong", 20, fired=True),
            Block(P_D, "wrong", 80),
            *_spread("correct", 30, 0),
        ]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert _criterion(report, "C4")["values"]["max_share"] == pytest.approx(0.30)
        assert code == harvest.EXIT_PASS
        assert _criteria(report) == ALL_PASS

    def test_wrong_sample_below_300_is_unmeasurable_not_fail(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = _spread("wrong", 74, 20) + _spread("correct", 30, 0)
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE == 3
        assert report["wrong_attempts"] == 296
        assert _criteria(report) == {
            **ALL_PASS,
            "C1": "UNMEASURABLE",
            "C3": "UNMEASURABLE",
            "C4": "UNMEASURABLE",  # 표본 미충족이면 쏠림도 판정하지 않는다
        }

    def test_skew_on_a_small_sample_is_unmeasurable_not_fail(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """n<300에서 한 문항 쏠림(발화 3건 전부 한 문항 = 100%)은 '기준 미달'이 아니라 측정 불가다.

        작은 표본의 쏠림 FAIL은 통계적으로 의미가 없는데 종합을 1로 만들어 "켜면 안 된다"로
        오독된다. 비중 수치는 측정 불가여도 보고한다(판정만 보류한다).
        """
        blocks = [Block(P_A, "wrong", 3, fired=True), Block(P_A, "wrong", 2)] + _spread(
            "correct", 30, 0
        )
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert report["wrong_attempts"] == 5
        assert _criteria(report) == {
            **ALL_PASS,
            "C1": "UNMEASURABLE",
            "C3": "UNMEASURABLE",
            "C4": "UNMEASURABLE",
        }
        c4 = _criterion(report, "C4")["values"]
        assert c4["max_share"] == pytest.approx(1.0)  # 쏠림 주입 자체는 실재한다
        assert c4["max_share_problem_id"] == P_A
        assert c4["max_share"] > harvest.MAX_SINGLE_PROBLEM_SHARE

    def test_correct_sample_below_100_is_unmeasurable(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = _spread("wrong", 100, 25) + _spread("correct", 24, 0)
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert report["correct_attempts"] == 96
        assert _criteria(report) == {**ALL_PASS, "C2": "UNMEASURABLE"}

    def test_none_correctness_is_unknown_not_wrong(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """`answer_is_correct=None`을 오답으로 접으면 오답 280 + 60 = 340이 되어 통과해 버린다."""
        blocks = (
            _spread("wrong", 70, 20)
            + _spread("correct", 30, 0)
            + [Block(pid, "unknown", 15) for pid in REAL]
            + [Block(P_A, "not_applicable", 20)]
        )
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert report["wrong_attempts"] == 280
        # 기대값은 블록에서 센다(손 고정 숫자가 코퍼스 사실 가드의 수치와 우연히 겹치지 않게).
        total = sum(b.count for b in blocks)
        applicable = sum(b.count for b in blocks if b.kind != "not_applicable")
        unknown = sum(b.count for b in blocks if b.kind in {"unknown", "not_applicable"})
        assert report["unknown_attempts"] == unknown == 4 * 15 + 20
        assert report["derivative_records"] == total
        assert report["applicable"] == applicable
        assert report["reach_rate"] == pytest.approx(applicable / total)
        assert report["reach_rate"] < 1.0  # 미적용 레코드가 도달률을 실제로 깎는다
        assert _criteria(report)["C1"] == "UNMEASURABLE"

    def test_problem_without_baseline_is_excluded_from_c3_and_reported(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """기준선 없는 문항의 오답은 C3에서 빠지고, 남은 부분집합이 300 미만이면 측정 불가다."""
        blocks = [
            *[Block(pid, "wrong", 25, fired=True) for pid in (P_A, P_B, P_C)],
            *[Block(pid, "wrong", 65) for pid in (P_A, P_B, P_C)],
            Block(P_NONNUMERIC, "wrong", 25, fired=True),
            Block(P_NONNUMERIC, "wrong", 75),
            *_spread("correct", 30, 0),
        ]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert report["wrong_attempts"] == 370
        assert _criteria(report) == {**ALL_PASS, "C3": "UNMEASURABLE"}
        c3 = _criterion(report, "C3")["values"]
        assert c3["subset_wrong_attempts"] == 270
        assert c3["excluded_wrong_attempts"] == 100
        row = next(r for r in report["problems"] if r["problem_id"] == P_NONNUMERIC)
        assert row["baseline_rate"] is None
        assert row["in_bank"] is True

    def test_problem_without_baseline_does_not_block_a_sufficient_subset(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = _passing_blocks() + [
            Block(P_NONNUMERIC, "wrong", 10, fired=True),
            Block(P_NONNUMERIC, "wrong", 40),
        ]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_PASS
        c3 = _criterion(report, "C3")["values"]
        assert c3["subset_wrong_attempts"] == 400
        assert c3["excluded_wrong_attempts"] == 50

    @pytest.mark.parametrize("pid", [P_MISSING, P_STAGING])
    def test_problem_not_in_approved_bank_is_unmeasurable(
        self,
        pid: str,
        tmp_path: Path,
        corpus_root: Path,
        baseline_cache: Any,
        capsys: Any,
    ) -> None:
        blocks = _passing_blocks() + [Block(pid, "wrong", 5)]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert _criteria(report) == {**ALL_PASS, "C0": "UNMEASURABLE"}
        assert _criterion(report, "C0")["values"]["missing_problem_ids"] == [pid]

    def test_fail_dominates_unmeasurable(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        """오발화(FAIL)와 표본 부족(측정 불가)이 겹치면 종합은 FAIL — 확인된 결함이 우선이다."""
        blocks = _spread("wrong", 50, 12) + [Block(P_A, "correct", 1, fired=True)]
        code, report = _run(tmp_path, _lines(blocks), corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_FAIL
        verdicts = _criteria(report)
        assert verdicts["C1"] == "UNMEASURABLE"
        assert verdicts["C2"] == "FAIL"

    def test_other_channel_records_are_counted_and_ignored(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        other = json.dumps({"channel": "some_future_channel", "x": 1})
        lines = _lines(_passing_blocks()) + [
            json.dumps({"problem_id": P_A, "adapter_records": [other, other]})
        ]
        code, report = _run(tmp_path, lines, corpus_root, baseline_cache, capsys)
        assert code == harvest.EXIT_PASS
        assert report["other_channel_records"] == 2
        assert report["derivative_records"] == 520


# ── 입력 결함은 통과가 아니라 측정 불가 ────────────────────────────────────────────────────


class TestBrokenInputIsUnmeasurable:
    def _main(self, path: Path, corpus_root: Path, capsys: Any) -> tuple[int, str]:
        code = harvest.main([str(path), "--corpus-root", str(corpus_root)], baseline_cache={})
        return code, capsys.readouterr().out

    def test_empty_file(self, tmp_path: Path, corpus_root: Path, capsys: Any) -> None:
        code, out = self._main(_write(tmp_path, []), corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "미분 서명 레코드 0건" in out
        assert "VERDICT=UNMEASURABLE" in out

    def test_only_other_channel_records(
        self, tmp_path: Path, corpus_root: Path, capsys: Any
    ) -> None:
        other = json.dumps({"channel": "some_future_channel"})
        line = json.dumps({"problem_id": P_A, "adapter_records": [other]})
        code, out = self._main(_write(tmp_path, [line]), corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "미분 서명 레코드 0건" in out

    def test_missing_file(self, tmp_path: Path, corpus_root: Path, capsys: Any) -> None:
        code, out = self._main(tmp_path / "nope.jsonl", corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "로그 파일 없음" in out

    def test_malformed_line_names_line_number_and_exception_type(
        self, tmp_path: Path, corpus_root: Path, capsys: Any
    ) -> None:
        lines = _lines([Block(P_A, "wrong", 2)]) + ["{not json"]
        code, out = self._main(_write(tmp_path, lines), corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "3번째 줄" in out
        assert "JSONDecodeError" in out

    def test_derivative_record_with_unknown_field_is_rejected(
        self, tmp_path: Path, corpus_root: Path, capsys: Any
    ) -> None:
        payload = json.loads(_record("wrong", False))
        payload["student_answer"] = "52488"  # 스키마에 없는 필드 — 조용히 흡수하지 않는다
        line = json.dumps({"problem_id": P_A, "adapter_records": [json.dumps(payload)]})
        code, out = self._main(_write(tmp_path, [line]), corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "1번째 줄" in out
        assert "ValidationError" in out
        assert "52488" not in out  # 검증 오류 요약이 입력 값을 내보내지 않는다

    @pytest.mark.parametrize(
        "row",
        [
            {"problem_id": "", "adapter_records": []},
            {"problem_id": P_A, "adapter_records": "not-a-list"},
            {"problem_id": P_A, "adapter_records": [{"channel": "derivative_signature"}]},
            ["not", "an", "object"],
        ],
    )
    def test_wrong_line_shape(
        self, row: Any, tmp_path: Path, corpus_root: Path, capsys: Any
    ) -> None:
        code, out = self._main(_write(tmp_path, [json.dumps(row)]), corpus_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "1번째 줄" in out

    def test_corpus_root_without_banks(self, tmp_path: Path, capsys: Any) -> None:
        log = _write(tmp_path, _lines([Block(P_A, "wrong", 1)]))
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        code, out = self._main(log, empty_root, capsys)
        assert code == harvest.EXIT_UNMEASURABLE
        assert "문항은행 없음" in out


# ── 기준선은 진짜 엔진에서 온다 ───────────────────────────────────────────────────────────


class TestBaselineComesFromTheEngine:
    def test_baseline_equals_an_independent_engine_sweep(
        self, corpus_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI 기준선 = 테스트가 엔진을 직접 그림자 모드로 60번 부른 결과(재구현이 아니다)."""
        bank = harvest.load_problem_bank(corpus_root, {P_D})
        problem = bank[P_D]
        with harvest._shadow_mode():
            measured = harvest.compute_chance_baseline(problem)

        monkeypatch.setenv("WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE", "shadow")
        get_settings.cache_clear()
        try:
            correct = int(problem.answer)
            fired = 0
            for k in [*range(-30, 0), *range(1, 31)]:
                result = scan_attempt_answer(
                    question_text=problem.question_text, student_answer=str(correct + k)
                )
                fired += DerivativeShadowRecord.model_validate_json(result.shadow_records[0]).fired
        finally:
            monkeypatch.delenv("WHYMATH_L4_DERIVATIVE_SIGNATURE_MODE", raising=False)
            get_settings.cache_clear()
        assert measured.computable is True
        assert measured.trials == 60
        assert measured.fired == fired
        assert measured.fired > 0  # 비자명성: 이 문항은 실제로 우연 발화가 있다

    def test_engine_is_called_sixty_times_per_problem_and_cached(
        self,
        tmp_path: Path,
        corpus_root: Path,
        capsys: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        real = signature_module.scan_attempt_answer

        def spy(*, question_text: str, student_answer: str | None) -> Any:
            calls.append(question_text)
            return real(question_text=question_text, student_answer=student_answer)

        monkeypatch.setattr(signature_module, "scan_attempt_answer", spy)
        cache: harvest.BaselineCache = {}
        blocks = [Block(P_A, "wrong", 3), Block(P_B, "correct", 2)]  # 기준선은 오답 있는 문항만
        path = _write(tmp_path, _lines(blocks))
        argv = [str(path), "--corpus-root", str(corpus_root)]
        harvest.main(argv, baseline_cache=cache)
        assert len(calls) == 60
        harvest.main(argv, baseline_cache=cache)
        assert len(calls) == 60  # 같은 (지문, 정답)은 다시 돌리지 않는다
        capsys.readouterr()

    def test_engine_exception_is_unmeasurable_with_type_name(
        self,
        tmp_path: Path,
        corpus_root: Path,
        capsys: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**_: Any) -> Any:
            raise RuntimeError("engine down")

        monkeypatch.setattr(signature_module, "scan_attempt_answer", boom)
        path = _write(tmp_path, _lines(_passing_blocks()))
        code = harvest.main([str(path), "--corpus-root", str(corpus_root)], baseline_cache={})
        out = capsys.readouterr().out
        assert code == harvest.EXIT_UNMEASURABLE  # 측정 도구의 결함이 FAIL(1)로 위장되지 않는다
        assert "RuntimeError" in out

    def test_missing_shadow_record_is_unmeasurable(
        self,
        tmp_path: Path,
        corpus_root: Path,
        capsys: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """레코드 없는 답을 '발화 안 함'으로 세면 기준선이 낮아져 C3가 거짓 통과한다."""
        real = signature_module.scan_attempt_answer

        def no_record(*, question_text: str, student_answer: str | None) -> Any:
            result = real(question_text=question_text, student_answer=student_answer)
            return result.model_copy(update={"shadow_records": ()})

        monkeypatch.setattr(signature_module, "scan_attempt_answer", no_record)
        path = _write(tmp_path, _lines(_passing_blocks()))
        code = harvest.main([str(path), "--corpus-root", str(corpus_root)], baseline_cache={})
        out = capsys.readouterr().out
        assert code == harvest.EXIT_UNMEASURABLE
        assert "그림자 레코드가 0건" in out

    def test_non_numeric_answer_has_no_baseline(self, corpus_root: Path) -> None:
        problem = harvest.load_problem_bank(corpus_root, {P_NONNUMERIC})[P_NONNUMERIC]
        baseline = harvest.compute_chance_baseline(problem)
        assert baseline.computable is False
        assert baseline.rate is None


# ── 출력 ───────────────────────────────────────────────────────────────────────────────────


class TestOutput:
    def test_json_output_has_no_question_text_and_verdict_on_stderr(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        path = _write(tmp_path, _lines(_passing_blocks()))
        code = harvest.main(
            [str(path), "--corpus-root", str(corpus_root), "--json"], baseline_cache=baseline_cache
        )
        captured = capsys.readouterr()
        report = json.loads(captured.out)  # stdout은 JSON 하나뿐이다
        assert code == harvest.EXIT_PASS
        assert report["verdict"] == "PASS"
        assert "VERDICT=PASS" in captured.err
        bank = harvest.load_problem_bank(corpus_root, set(REAL))
        for problem in bank.values():
            assert problem.question_text not in captured.out

    def test_human_summary_ends_with_verdict_line(
        self, tmp_path: Path, corpus_root: Path, baseline_cache: Any, capsys: Any
    ) -> None:
        blocks = _passing_blocks() + [Block(P_A, "correct", 1, fired=True)]
        path = _write(tmp_path, _lines(blocks))
        code = harvest.main(
            [str(path), "--corpus-root", str(corpus_root)], baseline_cache=baseline_cache
        )
        out = capsys.readouterr().out
        assert code == harvest.EXIT_FAIL
        assert out.rstrip().splitlines()[-1] == "VERDICT=FAIL (실패) EXIT=1"
        assert "[실패] C2 정답 오발화" in out

    def test_thresholds_are_the_preregistered_values(self) -> None:
        """§9.3 사전 등록값 — 바꾸려면 게이트 G-p356-signature-activation의 결정이 먼저다."""
        assert harvest.MIN_WRONG_ATTEMPTS == 300
        assert harvest.MIN_CORRECT_ATTEMPTS == 100
        assert harvest.CHANCE_MULTIPLIER == 5.0
        assert harvest.MAX_SINGLE_PROBLEM_SHARE == 0.30
        assert harvest.BASELINE_OFFSET_RANGE == 30
        assert harvest.CONFIDENCE == 0.95
