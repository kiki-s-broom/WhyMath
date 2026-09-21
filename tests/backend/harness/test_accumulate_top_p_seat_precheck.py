"""`--top-p` × 좌석 사전 거부 계약 동결 — EOS-121 라이브 정정 (라이브 0·hermetic).

**무엇을 막는가**: anthropic 좌석에서 `--top-p`를 주면 Anthropic Messages API가
`temperature`와 `top_p`의 동시 지정을 400으로 거부하고, 저작 경로는 temperature(0.9)를 항상
실으므로 **시도 100%가 실패한다**. 2026-09-19 라이브 회차가 그 대가를 치렀다 — 90호출 전건
`generation_failed`·`accepted: 0`.

**왜 프로바이더 가드만으로 부족한가**: 프로바이더는 *호출마다* 거부하므로 90번 시도해 90번
실패한다. 실패가 싸려면 **호출 0건에서** 걸려야 한다. 그래서 CLI가 인자 검증 단계에서 막고,
이 파일이 그 지점을 동결한다.

**과잉 차단이 이 방어의 반대편 실패 모드다.** 거부 조건은 세 논리곱이고 하나라도 빠지면
막지 말아야 할 회차를 막는다:
  ⓐ `--top-p` 지정 — 미지정이면 충돌할 것이 없다.
  ⓑ 좌석이 anthropic — openrouter·로컬(ollama)은 둘을 함께 받는다(제약은 Anthropic 한정).
  ⓒ 이 회차가 실제로 클라우드에 닿는다 — LOCAL 강제 회차의 top_p는 Ollama로 간다.
특히 ⓒ가 없으면 **기본 좌석이 anthropic이라 로컬 회차 전부가 막힌다**. 그래서 아래 표의
세 대조군(ⓐ 없음 / ⓑ 다름 / ⓒ 없음)이 전부 "통과" 방향으로 단언된다 — 대조군 없이 거부
방향만 재면 "전부 거부"하는 과잉 구현이 그대로 초록이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from whymath_backend.config import Settings
from whymath_backend.harness import problem_corpus_accumulate as cli
from whymath_backend.harness.problem_corpus_accumulate import (
    authoring_can_reach_cloud,
    top_p_seat_precheck,
)

_TOP_P = 0.95
# 라우터가 클라우드로 보내는 최소 조합(EOS-118·런북 [D][E]가 쓰는 값) — 둘 다 있어야 한다.
_CLOUD_ARGS = ("--subscription", "premium", "--budget-krw", "5000")


# ──────────────────────────────────────────────────────────────────────────
# 축 ⓒ — 클라우드 도달 가능성 판정(라우터에게 직접 묻는다)
# ──────────────────────────────────────────────────────────────────────────
class TestAuthoringCanReachCloud:
    """이 판정이 곧 "막아야 하는 회차인가"의 절반이다.

    라우터 규칙을 여기서 다시 쓰지 않고 `business_cost_tier`를 부르므로, 아래 케이스들은
    *우리 사본*이 아니라 *라우터의 실제 판정*을 재는 것이다.
    """

    def test_defaults_stay_local(self) -> None:
        """미지정(=생성기 기본 free·0.0) → LOCAL. **이 칸이 과잉 차단을 막는 근거**다."""
        assert authoring_can_reach_cloud(None, None) is False

    def test_both_signals_reach_cloud(self) -> None:
        """둘 다 주면 클라우드 — 런북 [D][E]가 쓰는 조합이다."""
        assert authoring_can_reach_cloud("premium", 5000.0) is True

    @pytest.mark.parametrize(
        ("subscription", "budget_krw"),
        [
            pytest.param("free", 5000.0, id="구독만_무료→규칙2가_LOCAL강제"),
            pytest.param("premium", 0.0, id="예산0→규칙1이_LOCAL강제"),
        ],
    )
    def test_one_signal_alone_is_not_enough(self, subscription: str, budget_krw: float) -> None:
        """한쪽만 열면 여전히 LOCAL — `_build_live_generator` docstring이 적은 사실 그대로다.

        두 케이스를 **따로** 두는 이유: 규칙 1(예산)과 규칙 2(구독)는 서로 다른 절이라,
        한쪽만 픽스처에 있으면 다른 절은 한 번도 밟히지 않는다.
        """
        assert authoring_can_reach_cloud(subscription, budget_krw) is False

    def test_all_difficulty_labels_are_probed(self) -> None:
        """난이도 라벨 전집합을 훑는가 — 한 라벨만 보는 구현이면 여기서 RED다.

        예산이 CLOUD_HIGH 최소비용에 못 미치는 구성이 변별점이다: `killer`는 규칙 3이
        guard_cloud로 LOCAL 강등하지만 `hard`는 규칙 4가 CLOUD_MID로 승급한다. 즉
        "killer 하나만 보면 가장 클라우드 친화적"이라는 직관이 **틀렸다**는 사실을 고정한다.
        """
        from whymath_backend.l3.models import CostTier, RoutingRequest
        from whymath_backend.l3.router import CLOUD_MIN_COST_KRW, business_cost_tier

        # 두 최소비용 **사이**의 예산 — 값을 상수에서 유도한다(단가표가 재보정되면 따라간다).
        budget = (
            CLOUD_MIN_COST_KRW[CostTier.CLOUD_MID] + CLOUD_MIN_COST_KRW[CostTier.CLOUD_HIGH]
        ) / 2

        def tier(difficulty: str) -> CostTier:
            return business_cost_tier(
                RoutingRequest(
                    task_type="generate",
                    difficulty=difficulty,
                    requires_reasoning=True,
                    student_subscription="premium",
                    budget_krw=budget,
                    sync=True,
                )
            )

        assert tier("killer") is CostTier.LOCAL  # 규칙 3 → guard_cloud가 예산 부족으로 강등
        assert tier("hard") is not CostTier.LOCAL  # 규칙 4 → CLOUD_MID
        # 그러므로 전집합을 훑는 판정만이 True를 낸다.
        assert authoring_can_reach_cloud("premium", budget) is True


# ──────────────────────────────────────────────────────────────────────────
# 판정 함수 — 3축 논리곱과 그 세 대조군
# ──────────────────────────────────────────────────────────────────────────
class TestTopPSeatPrecheck:
    def test_anthropic_with_top_p_on_cloud_round_is_refused(self) -> None:
        """거부 방향 — 라이브 90호출을 죽인 바로 그 조합."""
        refusal = top_p_seat_precheck(
            top_p=_TOP_P, seat="anthropic", subscription="premium", budget_krw=5000.0
        )
        assert refusal is not None

    def test_refusal_message_is_actionable(self) -> None:
        """측정자가 읽고 **바로 고칠 수 있는가** — 사유·처방·재현 지문이 다 있어야 한다."""
        refusal = top_p_seat_precheck(
            top_p=_TOP_P, seat="anthropic", subscription="premium", budget_krw=5000.0
        )
        assert refusal is not None
        assert "--top-p를 빼고" in refusal  # 처방 ①(권장)
        assert "openrouter" in refusal  # 처방 ②(좌석 교체)
        assert "cannot both be specified" in refusal  # 공급사 원문 — 검색 가능한 지문
        assert str(_TOP_P) in refusal  # 받은 값

    @pytest.mark.parametrize(
        ("top_p", "seat", "subscription", "budget_krw", "missing_axis"),
        [
            pytest.param(None, "anthropic", "premium", 5000.0, "ⓐ", id="대조군ⓐ_top_p_미지정"),
            pytest.param(_TOP_P, "openrouter", "premium", 5000.0, "ⓑ", id="대조군ⓑ_다른_좌석"),
            pytest.param(_TOP_P, "anthropic", None, None, "ⓒ", id="대조군ⓒ_LOCAL_강제_회차"),
        ],
    )
    def test_each_missing_axis_passes(
        self,
        top_p: float | None,
        seat: str,
        subscription: str | None,
        budget_krw: float | None,
        missing_axis: str,
    ) -> None:
        """세 축 중 **하나라도** 빠지면 통과 — 과잉 차단 방어선 셋.

        축마다 한 줄씩 두는 이유: 하나로 뭉치면 그 축을 무시하는 구현이 다른 축의 단언으로
        가려진다(예 ⓒ를 안 보는 구현도 ⓑ 케이스는 통과시킨다).
        """
        assert (
            top_p_seat_precheck(
                top_p=top_p, seat=seat, subscription=subscription, budget_krw=budget_krw
            )
            is None
        ), f"{missing_axis} 축이 빠졌는데 거부됐다(과잉 차단)"

    def test_local_seat_name_is_not_blocked(self) -> None:
        """로컬(ollama)은 애초에 `cloud_provider` 값이 아니지만, 어떤 이름이 와도 막지 않는다.

        판정이 "anthropic이 아니면 통과"인지 "알려진 목록에 있으면 통과"인지가 갈린다 —
        후자면 좌석이 하나 늘 때마다 조용히 과잉 차단이 생긴다.
        """
        assert (
            top_p_seat_precheck(
                top_p=_TOP_P, seat="ollama", subscription="premium", budget_krw=5000.0
            )
            is None
        )


# ──────────────────────────────────────────────────────────────────────────
# CLI 통합 — **호출 0건에서** exit 2인가
# ──────────────────────────────────────────────────────────────────────────
class _GeneratorWasBuiltError(Exception):
    """생성기 조립 지점에 도달했다는 신호 — "가드를 통과했다"의 관측점.

    이 센티넬이 있어야 통과 방향을 *회차를 실제로 돌리지 않고* 잴 수 있다. 없으면 통과
    케이스가 라이브 LLM을 요구하게 되어 hermetic에서 아예 못 잰다(= 대조군 상실).
    """


@pytest.fixture
def seat(monkeypatch: pytest.MonkeyPatch) -> Any:
    """좌석을 주입하는 픽스처 — 프로세스 환경변수에 의존하지 않는다."""

    def _set(name: str) -> None:
        monkeypatch.setattr(cli, "get_settings", lambda: Settings(cloud_provider=name))

    return _set


@pytest.fixture(autouse=True)
def _trap_generator_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """생성기 조립을 센티넬로 바꿔 **LLM 호출이 0건임을 구조적으로 보장**한다."""

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise _GeneratorWasBuiltError

    monkeypatch.setattr(cli, "_build_live_generator", _boom)


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return ["--out", str(tmp_path / "out.jsonl"), "--n", "1", *extra]


def test_cli_refuses_anthropic_seat_with_top_p_before_any_call(
    tmp_path: Path, seat: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """거부 방향 — exit 2이고, 생성기 조립에 **도달하지 않는다**.

    exit 코드만 보면 "돌다가 2로 끝났다"와 구분되지 않는다. 센티넬이 안 터졌다는 사실이
    "호출 0건"의 증거다(이것이 프로바이더 가드와 이 가드를 가르는 유일한 차이다).
    """
    seat("anthropic")
    code = cli.main(_argv(tmp_path, "--top-p", str(_TOP_P), *_CLOUD_ARGS))
    assert code == 2
    err = capsys.readouterr().err
    assert "좌석·인자 충돌" in err
    assert "--top-p를 빼고" in err


@pytest.mark.parametrize(
    ("seat_name", "extra"),
    [
        pytest.param("anthropic", (*_CLOUD_ARGS,), id="대조군ⓐ_anthropic_top_p_없음"),
        pytest.param(
            "openrouter", ("--top-p", str(_TOP_P), *_CLOUD_ARGS), id="대조군ⓑ_openrouter_top_p"
        ),
        pytest.param("anthropic", ("--top-p", str(_TOP_P)), id="대조군ⓒ_anthropic_LOCAL_회차"),
    ],
)
def test_cli_lets_the_control_cases_through(
    tmp_path: Path, seat: Any, seat_name: str, extra: tuple[str, ...]
) -> None:
    """통과 방향 셋 — 가드를 지나 생성기 조립까지 갔는가(센티넬이 터지면 통과한 것).

    이 셋이 없으면 `return 2`를 인자 검증 직후에 무조건 두는 구현도 위 테스트를 통과한다.
    """
    seat(seat_name)
    with pytest.raises(_GeneratorWasBuiltError):
        cli.main(_argv(tmp_path, *extra))


def test_cli_refuses_when_the_seat_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """좌석 판독 실패를 **통과로 접지 않는다**(모른다 ≠ 문제없다) — 예외 타입명을 남긴다.

    여기서 통과시키면 설정이 깨진 머신에서 90호출이 그대로 나간다. 반대로 `--top-p`가 없으면
    설정을 읽지도 않아야 하고, 그 사실은 아래 대조군이 잰다.
    """

    def _broken() -> Settings:
        raise RuntimeError("설정 판독 불가")

    monkeypatch.setattr(cli, "get_settings", _broken)
    code = cli.main(_argv(tmp_path, "--top-p", str(_TOP_P), *_CLOUD_ARGS))
    assert code == 2
    err = capsys.readouterr().err
    assert "좌석 판독 실패" in err
    assert "RuntimeError" in err  # 침묵 실패 금지 — 무타입 경고는 금지다


def test_cli_does_not_read_settings_when_top_p_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """대조군 — `--top-p` 미지정 회차는 설정을 **읽지도 않는다**(종전 경로 무변경).

    사전 검사를 무조건 돌리면 설정이 깨진 머신에서 *기존* 로컬 배치까지 새로 죽는다.
    """

    def _boom() -> Settings:
        raise AssertionError("--top-p 미지정인데 좌석 설정을 읽었다")

    monkeypatch.setattr(cli, "get_settings", _boom)
    with pytest.raises(_GeneratorWasBuiltError):
        cli.main(_argv(tmp_path))
