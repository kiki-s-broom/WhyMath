"""MP-04 — 회차 매니페스트 동결: 대장 1행이 그 회차의 *구성*과 *관측 판정*을 스스로 말하는가.

왜 이 파일이 있는가
------------------
회차 대장(`<out>.rounds.jsonl`)은 종전 8필드로 "몇 건 시도해 몇 건 붙었나"만 말했다. 그래서
회차 간 비교가 원리적으로 불가능했다 — 지난주보다 수용률이 낮을 때 그것이 *모델 교체* 때문인지
*임계 변경* 때문인지 대장만으로 갈리지 않았고(genlog 조인이 있어야 모델을 겨우 안다), 카나리·
롤링 중단이 무슨 판정을 냈는지는 대장에 0건이었다.

이 테스트가 붙드는 것은 **집행**이다(정본화≠집행). 스키마에 필드를 늘리는 것만으로는
아무것도 달라지지 않는다 — `problem_corpus_accumulate.main`이 실제 회차에서 그 칸을 *값으로*
채워야 한다. 그래서 전 케이스가 실 CLI(`main`)를 돌리고 디스크의 대장 행을 읽어 CLI 인자·
리포트·genlog와 대조한다(간접 신호 금지 — exit 0은 증거가 아니다).

변별력(CLAUDE.md 2026-09-01 "보호 장치를 실패 주입 없이 보호로 선언 금지")
------------------------------------------------------------------------
관측 판정 칸은 *통과 회차와 미달 회차에서 값이 달라야* 검증이다. 같은 값이 나오는 칸은 무엇을
기록하든 통과하므로 위장이다. `TestCanaryVerdictDiscrimination`이 같은 코드 경로에 **성공 대본**
과 **파싱 실패 대본**을 각각 주입해 `canary_passed`·하한 수치가 갈리는지 본다.

가짜는 LLM 호출부(provider) 하나뿐이다(`test_eos_anchor_e2e_a4` 동형) — 생성기·게이트·
genlog appender·대장 appender는 전부 실물이라 hermetic(LLM 0·DB 0·네트워크 0)이면서도
"실제로 그 경로가 채우는가"에 답한다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.anchor_round_ledger import (
    RoundRecord,
    load_round_ledger,
)
from whymath_backend.harness.problem_corpus_accumulate import (
    compute_dedup_input_digests,
    default_generation_log_path,
    default_round_ledger_path,
    main,
)
from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator
from whymath_backend.l3.models import GenerationResult, RoutingDecision, Usage
from whymath_backend.l3.pregenerate.provenance_bridge import load_generation_logs_jsonl
from whymath_backend.schema.enums import Subject

_STANDARD = "[9수02-20]"  # 중3 이차방정식 — 앵커 A4와 같은 축(대본과 스펙 정합)
_TOPIC = "중3 이차방정식 — 두 근 중 더 큰 근을 구하는 형태(답 하나)"
_DIFFICULTY = "2.5"


# ── 대본(가짜는 provider 하나뿐) ───────────────────────────────────────────
def _accept_response(smaller: int, larger: int) -> str:
    """수용 대본 — (x-a)(x-b)=0 전개형. 회차마다 다른 근을 써서 구조 중복을 피한다."""
    total = smaller + larger
    product = smaller * larger
    return json.dumps(
        {
            "question_text": (
                f"이차방정식 x^2 - {total}x + {product} = 0 의 두 근 중 더 큰 근을 구하시오."
            ),
            "answer": str(larger),
            "answer_explanation": (
                f"인수분해하면 (x-{smaller})(x-{larger})=0 이므로 두 근은 {smaller}와 "
                f"{larger}이고, 더 큰 근은 {larger}이다."
            ),
            "conditions": f"x**2 - {total}*x + {product} = 0",
            "answer_map": {"x": str(larger)},
            "answer_selection": "largest",
            "difficulty_overall": 2.5,
            "unit_codes": ["QUAD-EQ"],
            "answer_format": "자연수",
            "achievement_standard_codes": [_STANDARD],
        },
        ensure_ascii=False,
    )


# 파싱 불가 응답 — orchestrator가 `generation_failed`로 기록한다(불량 100% 주입용).
_NON_JSON = "죄송합니다, 지금은 문제를 만들 수 없습니다."


class _ScriptedProvider:
    """대본 provider — 순서대로 소비하고 소진 시 IndexError(조용한 순환 금지)."""

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,
        *,
        images: Sequence[str] | None = None,
        temperature: float | None = None,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> GenerationResult:
        out = self._responses[self._index]  # 소진 시 IndexError — 대본 밖 호출을 숨기지 않는다
        self._index += 1
        return GenerationResult(
            out, usage=Usage(input_tokens=40, output_tokens=90, latency_ms=13.0)
        )


def _patch_live_generator(monkeypatch: pytest.MonkeyPatch, responses: Sequence[str]) -> None:
    """provider 좌석만 대본으로 교체 — main의 배선(genlog 싱크 포함)은 실물 그대로."""
    from whymath_backend.l4.misconception.catalog import CATALOG_BY_ID  # 조성 루트 미러

    def _build(
        topic_hint: str, *, generation_log_sink: object = None, **_routing: object
    ) -> LLMEquivalentProblemGenerator:
        return LLMEquivalentProblemGenerator(
            _ScriptedProvider(responses),  # type: ignore[arg-type]
            misconception_catalog={mid: m.name_kr for mid, m in CATALOG_BY_ID.items()},
            topic_hint=topic_hint,
            subject=Subject.공통,
            slug_prefix="wm-gen-mp04",
            generation_log_sink=generation_log_sink,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", _build)


def _args(out: Path, *, n: int, extra: Sequence[str] = ()) -> list[str]:
    return [
        "--out",
        str(out),
        "--n",
        str(n),
        "--standard-code",
        _STANDARD,
        "--difficulty",
        _DIFFICULTY,
        "--topic-hint",
        _TOPIC,
        *extra,
    ]


def _last_row(out: Path) -> RoundRecord:
    """대장 마지막 행(= 방금 회차) — 로드 실패가 있으면 그 자리에서 빨개진다."""
    records, errors = load_round_ledger(default_round_ledger_path(out))
    assert errors == []
    assert records, "회차 대장에 행이 없다 — main이 대장을 append하지 않았다"
    return records[-1]


def _seed_file(tmp_path: Path, name: str, payload: str) -> Path:
    path = tmp_path / name
    path.write_text(payload, encoding="utf-8")
    return path


class TestConfigSnapshot:
    """① 구성 스냅샷 — 대장 행이 '이 회차를 무엇으로 돌렸는가'를 스스로 말하는가."""

    def test_gate_config_and_argv_land_in_ledger_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI로 준 임계 5종·argv 원문이 **인자 그대로** 대장 행에 실린다(값 대조)."""
        _patch_live_generator(monkeypatch, [_NON_JSON, _NON_JSON])
        out = tmp_path / "acc.jsonl"
        argv = _args(
            out,
            n=2,
            extra=[
                "--canary",
                "0",  # 0 = 관문 끔(명시) — None=미기록과 구분된다
                "--canary-threshold",
                "0.75",
                "--canary-confidence",
                "0.9",
                "--abort-window",
                "7",
                "--abort-threshold",
                "0.4",
            ],
        )
        main(argv)
        capsys.readouterr()

        row = _last_row(out)
        assert row.canary_size == 0
        assert row.canary_threshold == 0.75
        assert row.canary_confidence == 0.9
        assert row.abort_window == 7
        assert row.abort_threshold == 0.4
        # argv 원문 — 개별 필드가 놓친 인자(--topic-hint 등)까지 재실행 가능한 형태로 남는다.
        assert row.cli_argv == argv

    def test_dedup_input_digests_are_content_hashes_of_actual_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """시드 경로별 sha256이 **파일 내용의 실제 해시**와 일치한다(경로 문자열이 아니다)."""
        _patch_live_generator(monkeypatch, [_NON_JSON])
        # 코퍼스로 읽히지 않아도(빈 줄 스킵) 지문은 파일 내용에서 나온다 — 축이 다르다.
        seed_a = _seed_file(tmp_path, "seed_a.jsonl", "")
        seed_b = _seed_file(tmp_path, "seed_b.jsonl", "\n")
        out = tmp_path / "acc.jsonl"
        main(_args(out, n=1, extra=["--seed", str(seed_a), "--seed", str(seed_b)]))
        capsys.readouterr()

        row = _last_row(out)
        assert row.dedup_input_digests is not None
        # out도 dedup 입력이므로 키가 실린다. 첫 회차라 배치 전에는 없었으니 값은 None이다.
        assert row.dedup_input_digests == {
            str(seed_a): hashlib.sha256(seed_a.read_bytes()).hexdigest(),
            str(seed_b): hashlib.sha256(seed_b.read_bytes()).hexdigest(),
            str(out): None,
        }
        # 두 시드의 내용이 다르므로 지문도 달라야 한다 — 같으면 상수를 적고 있는 것이다.
        seed_values = {row.dedup_input_digests[str(seed_a)], row.dedup_input_digests[str(seed_b)]}
        assert len(seed_values) == 2

    def test_no_seed_round_records_empty_map_not_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--seed` 0건이어도 out은 dedup 입력이라 키가 남는다 — 빈 dict가 아니다.

        None(미기록)과 구분되는 것은 그대로다(미측정≠0). 첫 회차의 out은 배치 전에 없었으므로
        값이 None이고, 그것이 "읽을 것이 없었다"는 정직한 관측이다.
        """
        _patch_live_generator(monkeypatch, [_NON_JSON])
        out = tmp_path / "acc.jsonl"
        main(_args(out, n=1))
        capsys.readouterr()
        assert _last_row(out).dedup_input_digests == {str(out): None}

    def test_second_round_hashes_out_corpus_as_consumed_before_the_batch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """2회차 지문이 **배치 전** out 바이트와 일치한다 (PR #1013 Codex P1 회귀 가드).

        누적 축적은 2회차부터 `--seeds`뿐 아니라 **기존 out 코퍼스**로도 dedup 인덱스를 만든다
        (`seed_signatures | out_signatures`). 그러므로 out은 수용 판정에 실제로 쓰인 입력이고,
        지문에서 빠지면 대장은 재현에 필요한 입력 하나를 통째로 잃는다.

        시점도 함께 붙든다: 이 회차가 out에 행을 붙이므로 배치 **뒤에** 지문을 뜨면 값이
        달라진다. 그래서 "1회차 종료 시점의 out 해시"를 미리 떠 두고 2회차 행과 대조한다 —
        일치하면 소비한 입력을, 불일치하면 산출 후 상태를 기록한 것이다.
        """
        out = tmp_path / "acc.jsonl"
        # 1회차 — out에 수용 1건을 남긴다(2회차의 dedup 입력이 된다).
        _patch_live_generator(monkeypatch, [_accept_response(2, 5)])
        main(_args(out, n=1))
        capsys.readouterr()
        before = out.read_bytes()
        assert before, "1회차가 out에 아무것도 남기지 않았다 — 이 테스트의 전제가 깨졌다"
        digest_before = hashlib.sha256(before).hexdigest()

        # 2회차 — 다른 근으로 또 1건 수용시켜 out을 **자라게** 한다.
        _patch_live_generator(monkeypatch, [_accept_response(3, 7)])
        main(_args(out, n=1))
        capsys.readouterr()
        assert out.read_bytes() != before, "2회차가 out을 늘리지 않았다 — 시점 변별력이 없다"

        row = _last_row(out)
        assert row.dedup_input_digests is not None
        assert (
            str(out) in row.dedup_input_digests
        ), "out 코퍼스가 지문에 없다 — dedup 인덱스에 실제로 쓰인 입력이 대장에서 빠졌다."
        assert (
            row.dedup_input_digests[str(out)] == digest_before
        ), "out 지문이 배치 전 바이트와 다르다 — 소비한 입력이 아니라 산출 후 상태를 기록했다."

    def test_out_is_hashed_once_even_when_also_passed_as_seed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--out`을 `--seed`로도 준 회차에서 키가 중복되지 않는다(경로→지문은 단일 사상)."""
        out = tmp_path / "acc.jsonl"
        _patch_live_generator(monkeypatch, [_accept_response(2, 5)])
        main(_args(out, n=1))
        capsys.readouterr()
        digest_before = hashlib.sha256(out.read_bytes()).hexdigest()

        _patch_live_generator(monkeypatch, [_accept_response(3, 7)])
        main(_args(out, n=1, extra=["--seed", str(out)]))
        capsys.readouterr()

        row = _last_row(out)
        assert row.dedup_input_digests == {str(out): digest_before}

    def test_unreadable_seed_keeps_key_with_none_digest(self, tmp_path: Path) -> None:
        """읽지 못한 시드는 **키를 남기고 값만 None** — 인자에 있었다는 사실을 지우지 않는다."""
        missing = tmp_path / "nope.jsonl"
        present = _seed_file(tmp_path, "here.jsonl", "x")
        digests = compute_dedup_input_digests([missing, present])
        assert digests[str(missing)] is None  # 날조 금지 — 빈 파일 해시를 채우지 않는다
        assert digests[str(present)] == hashlib.sha256(b"x").hexdigest()

    def test_argv_falls_back_to_sys_argv_when_not_injected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """실제 CLI 실행(argv=None) 경로에서도 argv가 기록된다 — sys.argv[1:] 폴백."""
        _patch_live_generator(monkeypatch, [_NON_JSON])
        out = tmp_path / "acc.jsonl"
        argv = _args(out, n=1)
        monkeypatch.setattr(
            "sys.argv", ["python -m whymath_backend.harness.problem_corpus_accumulate", *argv]
        )
        main()  # 인자 주입 없음 — 프로세스 argv에서 읽어야 한다
        capsys.readouterr()
        assert _last_row(out).cli_argv == argv


class TestCanaryVerdictDiscrimination:
    """② 관측 판정 — 통과 회차와 미달 회차의 대장 값이 **갈리는가**(변별력).

    한쪽 방향만 보면 상시 True와 상시 False를 구별할 수 없다. 같은 CLI·같은 코드 경로에
    대본만 바꿔 주입하고 두 행을 직접 비교한다.
    """

    def _run_failing_canary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> RoundRecord:
        _patch_live_generator(monkeypatch, [_NON_JSON, _NON_JSON])
        out = tmp_path / "fail.jsonl"
        code = main(_args(out, n=5, extra=["--canary", "2", "--abort-window", "0"]))
        assert code == 1  # 카나리 차단 — 본배치 미시작
        report = json.loads(capsys.readouterr().out)
        assert report["canary_blocked"] is True
        assert report["attempted"] == 2  # 5가 아니라 카나리 2건에서 끊겼다
        return _last_row(out)

    def _run_passing_canary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> RoundRecord:
        _patch_live_generator(
            monkeypatch,
            [_accept_response(17, 23), _accept_response(23, 37), _accept_response(29, 41)],
        )
        out = tmp_path / "pass.jsonl"
        code = main(
            _args(
                out,
                n=3,
                # 임계를 낮추는 이유: n=2 카나리는 만점이어도 하한이 0.34라 기본 0.90을 통과할
                # 수 없다(batch_safety 실측 표) — 여기서 보려는 것은 임계 자체가 아니라 통과
                # 회차와 미달 회차의 **기록이 갈리는가**다.
                extra=["--canary", "2", "--canary-threshold", "0.1", "--abort-window", "0"],
            )
        )
        assert code == 0  # 신규 수용 ≥1 — 본배치가 끝까지 돌았다
        report = json.loads(capsys.readouterr().out)
        assert report["canary_blocked"] is False
        assert report["attempted"] == 3
        assert report["accepted"] >= 1  # 대본이 실제로 게이트를 통과했다(회귀 시 여기서 빨개짐)
        return _last_row(out)

    def test_failing_round_records_false_verdict_and_zero_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        row = self._run_failing_canary(tmp_path, monkeypatch, capsys)
        assert row.canary_passed is False
        assert row.canary_rate == 0.0
        assert row.canary_lower_bound == 0.0  # 0/2 — 하한 0
        assert row.canary_blocked is True
        assert row.canary_advisory is False
        assert row.aborted is False  # 롤링 중단과 구별된다
        assert row.abort_reason is None
        # 임계는 관측 하한보다 위에 있었다 — 대장 행만으로 "왜 막혔나"가 재판정된다.
        assert row.canary_threshold is not None
        assert row.canary_lower_bound < row.canary_threshold

    def test_passing_round_records_true_verdict_and_positive_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        row = self._run_passing_canary(tmp_path, monkeypatch, capsys)
        assert row.canary_passed is True
        assert row.canary_rate == 1.0
        assert row.canary_lower_bound is not None
        assert row.canary_lower_bound > 0.0
        assert row.canary_blocked is False
        assert row.canary_threshold is not None
        assert row.canary_lower_bound >= row.canary_threshold

    def test_two_rounds_differ_in_every_verdict_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """같은 값이면 검증이 아니라 위장이다 — 판정 3칸이 회차별로 실제로 갈린다."""
        failing = self._run_failing_canary(tmp_path, monkeypatch, capsys)
        passing = self._run_passing_canary(tmp_path, monkeypatch, capsys)
        assert failing.canary_passed != passing.canary_passed
        assert failing.canary_rate != passing.canary_rate
        assert failing.canary_lower_bound != passing.canary_lower_bound
        assert failing.canary_blocked != passing.canary_blocked

    def test_canary_off_round_records_none_not_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """관문을 끈 회차는 **판정 없음(None)** — False(미달)로 접으면 '막았다'가 된다."""
        _patch_live_generator(monkeypatch, [_NON_JSON])
        out = tmp_path / "off.jsonl"
        main(_args(out, n=1, extra=["--canary", "0", "--abort-window", "0"]))
        capsys.readouterr()
        row = _last_row(out)
        assert row.canary_passed is None
        assert row.canary_rate is None
        assert row.canary_lower_bound is None
        assert row.canary_size == 0  # 구성은 '끔'을 명시로 기록한다(미기록과 구분)

    def test_rolling_abort_round_records_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """롤링 중단 회차는 `aborted=True` + 사유 문자열이 실린다(조용한 중단 금지)."""
        _patch_live_generator(monkeypatch, [_NON_JSON] * 4)
        out = tmp_path / "abort.jsonl"
        code = main(
            _args(
                out,
                n=20,
                extra=["--canary", "0", "--abort-window", "4", "--abort-threshold", "0.3"],
            )
        )
        assert code == 1
        capsys.readouterr()
        row = _last_row(out)
        assert row.aborted is True
        assert row.abort_reason is not None and row.abort_reason.strip()
        assert row.canary_blocked is False  # 시작 전 차단이 아니라 진행 중 정지다


class TestSnapshotValueRule:
    """모델·프롬프트 좌석의 결합 규칙 — 회차가 단일 모델이었다고 거짓말하지 않는가."""

    def test_multiple_observed_values_are_all_recorded(self) -> None:
        """2개 이상 관측되면 정렬 후 ','로 합친다 — 하나만 고르면 그 행이 거짓이 된다."""
        assert (
            problem_corpus_accumulate._snapshot_observed_value({"qwen2.5:7b", "claude-sonnet-4-6"})
            == "claude-sonnet-4-6,qwen2.5:7b"
        )

    def test_empty_and_single_are_distinguished(self) -> None:
        assert problem_corpus_accumulate._snapshot_observed_value(set()) is None  # 미기록
        assert problem_corpus_accumulate._snapshot_observed_value({"qwen2.5:7b"}) == "qwen2.5:7b"


class TestGenlogReproductionContract:
    """④ 재현 계약 — 대장 스냅샷의 모델·프롬프트 버전이 같은 회차 genlog와 일치하는가."""

    def test_ledger_snapshot_matches_genlog_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _patch_live_generator(monkeypatch, [_accept_response(17, 23), _accept_response(23, 37)])
        out = tmp_path / "acc.jsonl"
        assert main(_args(out, n=2, extra=["--canary", "0", "--abort-window", "0"])) == 0
        run_id = json.loads(capsys.readouterr().out)["run_id"]

        logs, errors = load_generation_logs_jsonl(default_generation_log_path(out))
        assert errors == []
        assert logs, "genlog 행이 0건 — 대조할 재료가 없으면 이 테스트는 공허하게 통과한다"
        assert {log.run_id for log in logs} == {run_id}  # 같은 회차의 행만 본다

        row = _last_row(out)
        assert {log.model_name for log in logs} == {row.model_name}
        assert {log.prompt_version for log in logs} == {row.prompt_version}
        # 값 자체가 실재해야 대조가 의미를 갖는다(양쪽이 None이면 항상 일치한다 — 위장).
        assert row.model_name
        assert row.prompt_version

    def test_snapshot_is_none_when_no_generation_log_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """생성 호출이 0건인 회차(n=0)는 모델·프롬프트가 None=미기록 — 지어내지 않는다."""
        _patch_live_generator(monkeypatch, [])
        out = tmp_path / "acc.jsonl"
        assert main(_args(out, n=0, extra=["--canary", "0", "--abort-window", "0"])) == 1
        capsys.readouterr()
        row = _last_row(out)
        assert row.model_name is None
        assert row.prompt_version is None
        assert row.attempted == 0


class TestLegacyRowCompatibility:
    """⑤ 구행 호환 — 신설 필드가 없는 기존 행은 None(미기록)으로 읽힌다(소급 날조 금지)."""

    def test_pre_manifest_row_loads_with_none_fields(self, tmp_path: Path) -> None:
        legacy = {
            "run_id": "legacy-run",
            "out_path": "/tmp/old.jsonl",
            "attempted": 4,
            "accepted": 1,
            "appended": 1,
            "outcome_counts": {"accepted_stored": 1, "generation_failed": 3},
            "recorded_at": "2026-08-30T01:02:03Z",
        }
        path = tmp_path / "old.rounds.jsonl"
        path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")

        records, errors = load_round_ledger(path)
        assert errors == []  # 구행이 검증 실패로 버려지면 이력이 통째로 사라진다
        (row,) = records
        assert row.run_id == "legacy-run" and row.attempted == 4  # 구필드는 그대로
        for field_name in (
            "prompt_version",
            "model_name",
            "canary_size",
            "canary_threshold",
            "canary_confidence",
            "abort_window",
            "abort_threshold",
            "dedup_input_digests",
            "cli_argv",
            "canary_passed",
            "canary_rate",
            "canary_lower_bound",
            "canary_blocked",
            "canary_advisory",
            "aborted",
            "abort_reason",
        ):
            assert getattr(row, field_name) is None, f"{field_name}이 소급 날조됐다"

    def test_legacy_and_new_rows_coexist_in_one_ledger(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """구행이 먼저 있는 대장에 새 회차가 append돼도 둘 다 읽힌다(이력 연속성)."""
        out = tmp_path / "acc.jsonl"
        ledger = default_round_ledger_path(out)
        ledger.write_text(
            json.dumps(
                {
                    "run_id": "legacy-run",
                    "out_path": str(out),
                    "attempted": 1,
                    "accepted": 0,
                    "appended": 0,
                    "outcome_counts": {"generation_failed": 1},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        _patch_live_generator(monkeypatch, [_NON_JSON])
        main(_args(out, n=1, extra=["--canary", "0", "--abort-window", "0"]))
        capsys.readouterr()

        records, errors = load_round_ledger(ledger)
        assert errors == []
        assert len(records) == 2
        assert records[0].cli_argv is None  # 구행 — 미기록
        assert records[1].cli_argv is not None  # 신행 — 기록됨(같은 파일에서 갈린다)


class TestRoundRecordSchemaContract:
    """스키마 계약 — 신설 필드가 늘어도 frozen·extra=forbid는 유지된다."""

    def test_extra_field_is_rejected_and_record_is_frozen(self) -> None:
        with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError 계열
            RoundRecord.model_validate(
                {
                    "run_id": "r",
                    "out_path": "o",
                    "attempted": 0,
                    "accepted": 0,
                    "appended": 0,
                    "made_up_field": 1,
                }
            )
        record = RoundRecord(run_id="r", out_path="o", attempted=0, accepted=0, appended=0)
        with pytest.raises(Exception):  # noqa: B017 — frozen 모델 대입 금지
            record.canary_passed = True  # type: ignore[misc]
