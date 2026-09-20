"""EOS-121 결함① — **회차 대장이 '어느 좌석의 회차인가'를 스스로 말하는가.**

상환하는 사고 (2026-09-19 파일럿 실측)
-------------------------------------
EOS-121 파일럿 회차의 대장(`.rounds.jsonl`) 행에서 `cloud_seat`가 **`null`** 이었다.
실측 원인: `seat_operating_rates(...)` 산출물이 `payload["cloud_seat"]`(stdout 요약)에만
실리고 `RoundRecord`에는 그 필드가 **아예 없었다**. 좌석 비교가 전부인 측정에서 대장이
좌석을 모르면 그 회차는 다시 읽을 수 없다.

더 나쁜 것은 코드 주석이 그 반대를 말하고 있었다는 점이다 —
`problem_corpus_accumulate.py`와 `anchor_round_ledger.py` 두 곳이 "좌석(`cloud_seat`)은
회차 단위라 회차 안에서 spec만 갈라 두면 두 축이 완성된다"고 적었다. 좌석이 회차 단위인 것은
맞지만 **그 값이 대장에 실리지 않았으므로** 교차 집계는 성립하지 않았다. 주석이 거짓을
말하면 다음 세션이 그것을 근거로 판단한다.

변별력 (CLAUDE.md 2026-09-01 「보호 장치를 실패 주입 없이 보호로 선언 금지」)
--------------------------------------------------------------------------
이 파일은 **세 경우를 갈라** 본다 — 하나만 보면 "항상 같은 값을 적는" 구현도 통과한다:

  ⓐ **좌석이 있는 회차** — 클라우드 핀 모델이 돌았다 → `all_on_selected_seat`
  ⓑ **좌석이 없는 회차(로컬 전용)** — 선택 좌석 핀이 실측 0건 → `none_on_selected_seat`
     (**미측정이 아니다** — 이 구분이 이 태스크의 급소다)
  ⓒ **구판 대장 행** — `cloud_seat` 키가 없는 JSONL 행을 읽어도 깨지지 않고 `None`(미기록)

그리고 **좌석 값이 실제로 좌석에 따라 갈리는지**(anthropic vs openrouter)를 대조군으로 둔다.
갈리지 않으면 상수를 적고 있는 것이다.

가짜는 생성기 좌석 하나뿐이다(`test_prompt_cache_hit_measurement` 동형) — genlog appender·
대장 appender·로더는 전부 실물이라 hermetic(LLM 0·DB 0·네트워크 0)이면서도 "실제로 그
경로가 채우는가"에 답한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.anchor_round_ledger import (
    RoundRecord,
    default_round_ledger_path,
    load_round_ledger,
)
from whymath_backend.harness.problem_corpus_accumulate import main
from whymath_backend.schema.provenance import GenerationLog

_OR_MID = "deepseek/deepseek-v4.1-flash"
_OR_HIGH = "deepseek/deepseek-v4-pro"
_AN_MID = "claude-sonnet-4-6"
_AN_HIGH = "claude-opus-4-7"
_LOCAL = "qwen2.5:7b"


class _FakeSettings:
    """좌석 셀렉터·핀만 갖춘 설정 대역 — `cloud_model_pins`가 읽는 속성 그대로."""

    anthropic_prompt_caching = False

    def __init__(self, seat: str) -> None:
        self.cloud_provider = seat
        self.openrouter_model_mid = _OR_MID
        self.openrouter_model_high = _OR_HIGH
        self.anthropic_model_mid = _AN_MID
        self.anthropic_model_high = _AN_HIGH


class _ModelEmittingGenerator:
    """genlog 싱크에 지정한 모델명을 실은 행을 흘리는 가짜 생성기(후보는 내지 않는다).

    후보 수용 여부는 이 파일의 관심사가 아니다 — 관심사는 **싱크에 실린 좌석 신호가 회차
    대장까지 도달하는가**이므로 생성은 실패(None)로 두고 관측만 흘린다.
    """

    def __init__(self, sink: Any, *, models: list[str | None]) -> None:
        self._sink = sink
        self._models = list(models)

    def generate(self, spec: object) -> None:
        del spec
        if self._sink is None or not self._models:
            return None
        model = self._models.pop(0)
        self._sink(
            GenerationLog(
                model_name=model,
                served_model=model,
                input_tokens=20,
                output_tokens=5,
                success=True,
            )
        )
        return None


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    seat: str,
    models: list[str | None],
    name: str = "acc.jsonl",
) -> tuple[dict[str, Any], RoundRecord]:
    """실 CLI 1회차 — (stdout 요약, 대장 마지막 행)."""
    monkeypatch.setattr(
        problem_corpus_accumulate,
        "_build_live_generator",
        lambda topic_hint, **kwargs: _ModelEmittingGenerator(
            kwargs.get("generation_log_sink"), models=models
        ),
    )
    monkeypatch.setattr(problem_corpus_accumulate, "get_settings", lambda: _FakeSettings(seat))
    out = tmp_path / name
    code = main(
        ["--out", str(out), "--n", str(max(len(models), 1)), "--canary", "0", "--abort-window", "0"]
    )
    assert code == 1  # 후보 0건이라 무진전 — 좌석 계측은 그와 무관하게 나와야 한다
    records, errors = load_round_ledger(default_round_ledger_path(out))
    assert errors == []
    assert records, "대장에 행이 없다 — main이 회차를 기록하지 않았다"
    return {}, records[-1]


class TestSeatLandsInTheLedgerRow:
    """ⓐ 좌석이 있는 회차 — 대장 행만으로 좌석을 말한다(이 결함의 직격 지점)."""

    def test_cloud_round_records_the_seat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _, row = _run(tmp_path, monkeypatch, seat="openrouter", models=[_OR_MID, _OR_MID])
        capsys.readouterr()

        assert row.cloud_seat is not None, (
            "대장 행에 좌석이 없다 — 파일럿에서 관측된 `cloud_seat: null` 그 상태다. "
            "요약(stdout)만으로는 회차를 다시 읽을 수 없다."
        )
        assert row.cloud_seat["selected_seat"] == "openrouter"
        assert row.cloud_seat["state"] == "all_on_selected_seat"
        assert row.cloud_seat["measured"] is True
        assert row.cloud_seat["calls_on_selected_seat"] == 2
        assert row.cloud_seat["observed_models"] == {_OR_MID: 2}

    def test_ledger_and_stdout_summary_carry_the_same_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """대장과 요약이 **같은 dict**여야 한다 — 두 벌 산식이면 언젠가 갈린다."""
        _, row = _run(tmp_path, monkeypatch, seat="openrouter", models=[_OR_MID])
        payload = json.loads(capsys.readouterr().out)

        assert row.cloud_seat == payload["cloud_seat"]

    def test_seat_value_actually_follows_the_selector(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """대조군 — 좌석을 바꾸면 대장 값도 바뀐다(상수를 적는 구현을 배제).

        이 단언이 없으면 `cloud_seat`에 고정 문자열을 적는 구현도 위 테스트들을 통과한다.
        """
        _, or_row = _run(
            tmp_path, monkeypatch, seat="openrouter", models=[_OR_MID], name="or.jsonl"
        )
        capsys.readouterr()
        _, an_row = _run(tmp_path, monkeypatch, seat="anthropic", models=[_AN_MID], name="an.jsonl")
        capsys.readouterr()

        assert or_row.cloud_seat is not None and an_row.cloud_seat is not None
        assert or_row.cloud_seat["selected_seat"] == "openrouter"
        assert an_row.cloud_seat["selected_seat"] == "anthropic"
        assert or_row.cloud_seat["seat_model_pins"] != an_row.cloud_seat["seat_model_pins"]
        # 두 회차 다 '선택 좌석에서 돌았다'여야 한다 — 한쪽만 그렇다면 핀 매핑이 좌석을
        # 따라가지 않는다는 뜻이다(ARCH-58 형태).
        assert or_row.cloud_seat["state"] == "all_on_selected_seat"
        assert an_row.cloud_seat["state"] == "all_on_selected_seat"


class TestUnmeasuredIsNotZero:
    """ⓑ·ⓒ 미측정과 0을 섞지 않는다 — 이 대장이 이미 쓰는 규약(`duplicate_sources` 동형)."""

    def test_local_only_round_is_measured_zero_not_unmeasured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """로컬 전용 회차 = **측정됐고 선택 좌석 0건**이다(미측정이 아니다).

        셀렉터를 openrouter로 두고도 LOCAL만 돈 회차가 여기 걸린다. 이것을 `not_measured`로
        접으면 '클라우드가 안 돌았다'는 *관측*이 '아무것도 못 쟀다'로 위장된다.
        """
        _, row = _run(tmp_path, monkeypatch, seat="openrouter", models=[_LOCAL, _LOCAL])
        capsys.readouterr()

        assert row.cloud_seat is not None
        assert row.cloud_seat["state"] == "none_on_selected_seat"
        assert row.cloud_seat["measured"] is True, "실측 0건이 '미측정'으로 접혔다"
        assert row.cloud_seat["unmeasured_reason"] is None
        assert row.cloud_seat["calls_on_selected_seat"] == 0
        assert row.cloud_seat["calls_off_selected_seat"] == 2

    def test_round_without_any_model_name_is_unmeasured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`model_name`이 하나도 안 실린 회차는 **미측정**이다 — 0%가 아니다."""
        _, row = _run(tmp_path, monkeypatch, seat="openrouter", models=[None, None])
        capsys.readouterr()

        assert row.cloud_seat is not None
        assert row.cloud_seat["state"] == "not_measured"
        assert row.cloud_seat["measured"] is False
        assert "미측정" in (row.cloud_seat["unmeasured_reason"] or "")
        assert row.cloud_seat["calls_total"] == 2  # 관측 규모는 남는다

    def test_round_with_no_generation_calls_at_all_is_unmeasured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """genlog 행 자체가 0건이어도 필드는 실린다 — **필드 부재**(미기록)와 구분된다."""
        _, row = _run(tmp_path, monkeypatch, seat="anthropic", models=[])
        capsys.readouterr()

        assert row.cloud_seat is not None, "관측 0건을 '필드 없음'으로 적으면 구판 행과 같아진다"
        assert row.cloud_seat["state"] == "not_measured"
        assert row.cloud_seat["calls_total"] == 0

    def test_legacy_ledger_row_without_the_field_loads_as_none(self, tmp_path: Path) -> None:
        """ⓒ 구판 행 — `cloud_seat` 키가 없는 JSONL도 읽히고 값은 `None`(미기록)이다.

        `RoundRecord`는 `extra="forbid"`라 스키마 변경이 곧 로더의 하위 호환 문제가 된다.
        구판 행이 `ValidationError`로 떨어지면 무진전 판정이 과거 회차를 통째로 잃는다.
        """
        ledger = tmp_path / "legacy.rounds.jsonl"
        ledger.write_text(
            json.dumps(
                {
                    "run_id": "legacy-1",
                    "out_path": "corpus.jsonl",
                    "attempted": 5,
                    "accepted": 1,
                    "appended": 1,
                    "outcome_counts": {"accepted_stored": 1, "rejected_duplicate": 4},
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        records, errors = load_round_ledger(ledger)

        assert errors == [], f"구판 행이 로드 실패했다: {errors}"
        assert len(records) == 1
        assert records[0].cloud_seat is None  # 미기록 — '좌석 없음'이 아니다
        assert records[0].attempted == 5  # 나머지 축은 그대로 읽힌다(대조군)


class TestTheWrongCommentsAreGone:
    """틀린 주석 2곳의 정정 — 주석이 거짓을 말하면 다음 세션이 그것을 근거로 판단한다.

    두 파일 모두 "좌석은 회차 단위라 회차 안에서 spec만 갈라 두면 두 축이 완성된다"고 적고
    있었다. 좌석 값이 대장에 실리지 않았으므로 그 전제는 틀렸다. 정정 없이 필드만 추가하면
    다음 사람이 같은 문장을 읽고 또 "대장이 좌석을 안다"고 가정한다.
    """

    @staticmethod
    def _source(relative: str) -> str:
        return (Path(__file__).resolve().parents[3] / relative).read_text(encoding="utf-8")

    def test_accumulate_comment_no_longer_claims_spec_alone_completes_the_cross_tab(self) -> None:
        source = self._source("src/backend/whymath_backend/harness/problem_corpus_accumulate.py")
        assert (
            "회차 안에서 spec만 갈라 두면 두 축이 완성된다" not in source
        ), "틀린 전제 문장이 남아 있다 — 좌석 축은 spec 축만으로 완성되지 않는다."
        # 대조군: 그 자리에 좌석 배선이 실제로 있어야 한다(문장만 지우는 수정을 배제).
        assert 'cloud_seat=payload["cloud_seat"]' in source

    def test_ledger_field_doc_no_longer_claims_spec_alone_completes_the_cross_tab(self) -> None:
        source = self._source("src/backend/whymath_backend/harness/anchor_round_ledger.py")
        assert "회차 안에서 spec만 갈라 두면 두 축이 완성된다" not in source
        assert "cloud_seat: dict[str, Any] | None" in source
