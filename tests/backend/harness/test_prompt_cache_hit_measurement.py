"""프롬프트 캐시 적중 계측(EOS-99) — '켰다'와 '작동했다'를 가르는 축.

**왜 이 파일이 있는가**

`settings.anthropic_prompt_caching`을 켜면 요청에 `cache_control`이 실린다. 그러나 그것은
*켰다는 사실*일 뿐이다 — 프리픽스가 최소 토큰 미만이면 API는 **조용히** 캐시하지 않고
(silent no-op), 프리픽스가 매 호출 달라지면 매번 새로 쓰기만 한다. 두 경우 모두 응답은
200이고 회차는 exit 0이며, 종전 genlog(`input_tokens`·`output_tokens`)로는 두 상태와
"실제로 적중 중"이 **코드에서 구분되지 않았다**(CLAUDE.md "작동 신호 없는 알고리즘 부착
금지" — 정상 응답은 알고리즘이 일했다는 증거가 아니다).

**이 파일이 지키는 급소는 '0'과 'None'의 구분이다.** 캐시 개념이 없는 로컬 Ollama 경로는
두 필드가 None인데, 그것을 0으로 접으면 **로컬만 돌린 회차가 '적중 0%'로 보고된다** —
즉 "해당 없음"이 "켰지만 작동 안 함"으로 위장되고, 그 경보는 상시 켜져 습관화된다.
그래서 아래 검사는 양방향이다: 미측정이 0%로 보이지 않는가, 그리고 진짜 0%가
'해당 없음'에 묻히지 않는가.

hermetic 한계(정직 기재): 실제 적중률은 라이브 Anthropic 키가 필요하다. 여기서 고정하는
것은 **판독·전파·집계·판정의 계약**이고, 라이브 실측(acceptance ③)은 Kiki 머신 회차에서
같은 필드를 읽어 확인한다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.anchor_round_ledger import (
    PROMPT_CACHE_STATES,
    PromptCacheTally,
    load_round_ledger,
    prompt_cache_rates,
)
from whymath_backend.harness.problem_corpus_accumulate import (
    default_round_ledger_path,
    main,
)
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.models import Usage
from whymath_backend.l3.pregenerate.models import PrewarmItemResult
from whymath_backend.l3.pregenerate.provenance_bridge import generation_log_from_result
from whymath_backend.schema.provenance import GenerationLog


class _NullProvider:
    """라우팅 판정만 보는 테스트용 provider 좌석 — 호출되지 않는다(네트워크 0)."""

    async def generate(self, *args: object, **kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("이 테스트는 라우팅 결정만 본다 — 생성 호출이 있으면 설계 오류")


def _spec() -> EquivalenceSpec:
    """라우팅 판정용 최소 스펙 — 난이도만 의미가 있다(medium → 규칙 4 경로)."""
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({"[10공수1-02-02]"}),
        target_misconception_ids=frozenset(),
        difficulty_overall=2.5,
        answer_format=None,
    )


def _cloud_round(n: int, *, prefix_tokens: int = 2000, tail: int = 20) -> PromptCacheTally:
    """동일 프리픽스 n회 반복 회차(acceptance ③의 측정 지점)를 원장으로 재현한다.

    1회차는 캐시에 쓰고(cache_creation), 2회차부터 읽는다(cache_read) — 이것이 정상이며,
    적중률은 (n-1)/n에 수렴한다.
    """
    tally = PromptCacheTally()
    for i in range(n):
        tally = tally.observe(
            input_tokens=tail,
            cache_read_input_tokens=0 if i == 0 else prefix_tokens,
            cache_creation_input_tokens=prefix_tokens if i == 0 else 0,
        )
    return tally


class TestTallyDistinguishesUnmeasuredFromZero:
    """미측정(None) ≠ 실측 0 — 이 구분이 무너지면 경보가 상시 켜진다."""

    def test_local_only_round_is_not_applicable_not_zero_percent(self) -> None:
        """캐시 필드가 전부 None인 회차(로컬 Ollama)는 '해당 없음'이지 0%가 아니다."""
        tally = PromptCacheTally()
        for _ in range(5):
            tally = tally.observe(
                input_tokens=800,  # 입력 토큰은 있다 — 그래도 분모가 되면 안 된다
                cache_read_input_tokens=None,
                cache_creation_input_tokens=None,
            )

        rates = prompt_cache_rates(tally, caching_enabled=True)

        assert tally.calls_total == 5
        assert tally.calls_with_cache_telemetry == 0
        # 급소: 캐시 텔레메트리 없는 행의 input_tokens가 분모에 실리면 0%가 된다.
        assert tally.prompt_tokens_total == 0
        assert rates["hit_rate"] is None
        assert rates["measured"] is False
        assert rates["state"] == "not_applicable"
        assert rates["unmeasured_reason"]

    def test_cloud_round_with_zero_reads_is_a_real_zero(self) -> None:
        """캐시 필드를 **읽었는데** 적중 0이면 그건 실측 0이고, 플래그가 켜져 있으면 결함이다."""
        tally = PromptCacheTally()
        for _ in range(4):
            tally = tally.observe(
                input_tokens=1500,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            )

        rates = prompt_cache_rates(tally, caching_enabled=True)

        assert rates["measured"] is True
        assert rates["hit_rate"] == 0.0
        assert rates["state"] == "enabled_not_working"

    def test_zero_denominator_is_unmeasured_not_zero_rate(self) -> None:
        """텔레메트리는 있는데 토큰 합이 0이면 분모가 없다 — 0%가 아니라 미측정."""
        tally = PromptCacheTally().observe(
            input_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        rates = prompt_cache_rates(tally, caching_enabled=True)

        assert rates["measured"] is False
        assert rates["hit_rate"] is None
        assert rates["state"] == "unmeasured"

    def test_partial_none_is_not_counted_as_zero(self) -> None:
        """한쪽만 None인 행은 텔레메트리 행으로 세되, None을 0으로 *더하지* 않는다."""
        tally = PromptCacheTally().observe(
            input_tokens=None, cache_read_input_tokens=900, cache_creation_input_tokens=None
        )

        assert tally.calls_with_cache_telemetry == 1
        assert tally.cache_read_tokens == 900
        assert tally.cache_creation_tokens == 0
        assert tally.uncached_input_tokens == 0


class TestMeasurementPointMatchesAcceptance:
    """acceptance ③ — 동일 프리픽스 n회 회차에서 적중률이 (n-1)/n에 근접한다."""

    @pytest.mark.parametrize("n", [10, 20])
    def test_repeated_prefix_round_approaches_n_minus_one_over_n(self, n: int) -> None:
        rates = prompt_cache_rates(_cloud_round(n), caching_enabled=True)

        expected = (n - 1) / n
        assert rates["state"] == "enabled_working"
        assert rates["hit_rate"] is not None
        # 꼬리(비캐시 입력)만큼 아래로 벌어진다 — 위로 새지 않는지도 함께 못박는다.
        assert expected - 0.02 < rates["hit_rate"] <= expected

    def test_denominator_is_total_prompt_tokens_not_residual_input(self) -> None:
        """분모는 프롬프트 **총** 토큰이다 — 잔여 input만 쓰면 비율이 1을 넘는다.

        Anthropic은 캐시 적중분을 `input_tokens`에서 **빼고** 별도로 센다(배타 관계).
        acceptance ② 표기 "cache_read/input"을 글자대로 읽으면 같은 acceptance ③의
        "(n-1)/n 근접"과 모순되므로, 행동 기준인 ③을 계약으로 삼는다.
        """
        tally = _cloud_round(10)

        rates = prompt_cache_rates(tally, caching_enabled=True)

        assert tally.prompt_tokens_total == (
            tally.uncached_input_tokens + tally.cache_read_tokens + tally.cache_creation_tokens
        )
        assert rates["hit_rate"] is not None and rates["hit_rate"] <= 1.0
        # 잘못된 분모(잔여 input만)를 쓰면 이 값이 나온다 — 우리 산식은 그것이 아니다.
        assert tally.cache_read_tokens / tally.uncached_input_tokens > 1.0


class TestFlagStateEntersTheVerdict:
    """플래그 상태를 모르는 것과 꺼져 있는 것을 구분한다(모른다 ≠ 아니다)."""

    def test_disabled_zero_is_expected_not_a_defect(self) -> None:
        tally = PromptCacheTally().observe(
            input_tokens=1000, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        assert prompt_cache_rates(tally, caching_enabled=False)["state"] == "disabled"

    def test_disabled_but_hit_is_reported_not_swallowed(self) -> None:
        """꺼졌다는데 적중이 잡히면 리포트가 읽은 설정과 실제 설정이 다르다 — 자백시킨다."""
        assert prompt_cache_rates(_cloud_round(4), caching_enabled=False)["state"] == (
            "disabled_but_hit"
        )

    def test_unknown_flag_is_not_folded_into_disabled(self) -> None:
        rates = prompt_cache_rates(_cloud_round(4), caching_enabled=None)

        assert rates["caching_enabled"] is None
        assert rates["state"] == "unknown_flag"

    def test_every_verdict_is_declared_in_the_vocabulary(self) -> None:
        """산출 가능한 상태가 전부 공개 어휘에 있다(어휘 드리프트 방지)."""
        produced = {
            prompt_cache_rates(PromptCacheTally(), caching_enabled=True)["state"],
            prompt_cache_rates(
                PromptCacheTally().observe(
                    input_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
                ),
                caching_enabled=True,
            )["state"],
            prompt_cache_rates(_cloud_round(3), caching_enabled=True)["state"],
            prompt_cache_rates(_cloud_round(3), caching_enabled=False)["state"],
            prompt_cache_rates(_cloud_round(3), caching_enabled=None)["state"],
            prompt_cache_rates(
                PromptCacheTally().observe(
                    input_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0
                ),
                caching_enabled=True,
            )["state"],
            prompt_cache_rates(
                PromptCacheTally().observe(
                    input_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0
                ),
                caching_enabled=False,
            )["state"],
        }

        assert produced <= set(PROMPT_CACHE_STATES)
        # 어휘가 산출과 무관하게 자라지 않았는지도 본다(죽은 어휘 = 읽는 쪽의 오해).
        assert produced == set(PROMPT_CACHE_STATES)


class TestPropagationIntoGenerationLog:
    """usage → GenerationLog 전파(EOS-99 ②) — 중간에서 끊기면 집계가 영영 0건이다."""

    def test_bridge_carries_cache_tokens(self) -> None:
        result = PrewarmItemResult(
            cache_key="wm:cache:1",
            status="written",
            error=None,
            usage=Usage(
                input_tokens=30,
                output_tokens=10,
                latency_ms=12.4,
                cache_read_input_tokens=1024,
                cache_creation_input_tokens=0,
            ),
        )

        log = generation_log_from_result(result, problem_id=None, model_name="claude-sonnet-4-6")

        assert log.cache_read_input_tokens == 1024
        assert log.cache_creation_input_tokens == 0

    def test_bridge_keeps_none_when_usage_absent(self) -> None:
        """usage 자체가 없으면(인제스트 경로) None — 0으로 채우지 않는다."""
        result = PrewarmItemResult(cache_key="wm:cache:2", status="written", error=None, usage=None)

        log = generation_log_from_result(result, problem_id=None, model_name="qwen2-math:7b")

        assert log.cache_read_input_tokens is None
        assert log.cache_creation_input_tokens is None

    def test_schema_round_trips_through_json(self) -> None:
        """genlog는 JSONL 매체라 직렬화·역직렬화를 지나야 집계에 도달한다."""
        log = GenerationLog(cache_read_input_tokens=7, cache_creation_input_tokens=0)

        restored = GenerationLog.model_validate(json.loads(log.model_dump_json()))

        assert restored.cache_read_input_tokens == 7
        assert restored.cache_creation_input_tokens == 0

    def test_orm_seat_exists_so_db_path_does_not_drop_it(self) -> None:
        """ORM에 좌석이 없으면 `from_schema`의 mapped_keys 필터가 **조용히 버린다**."""
        from whymath_backend.db.models.provenance import GenerationLog as OrmGenerationLog

        row = OrmGenerationLog.from_schema(
            GenerationLog(cache_read_input_tokens=5, cache_creation_input_tokens=6)
        )

        assert row.cache_read_input_tokens == 5
        assert row.cache_creation_input_tokens == 6


class _CacheEmittingGenerator:
    """genlog 싱크에 캐시 토큰이 실린 행을 흘리는 가짜 생성기(후보는 내지 않는다).

    후보 생성 성공/실패는 이 파일의 관심사가 아니다 — 관심사는 **싱크에 실린 캐시 토큰이
    회차 리포트·대장까지 도달하는가**이므로, 생성은 실패(None)로 두고 관측만 흘린다.
    """

    def __init__(self, sink, *, reads: list[int], creations: list[int]) -> None:
        self._sink = sink
        self._reads = list(reads)
        self._creations = list(creations)

    def generate(self, spec: EquivalenceSpec) -> None:
        del spec
        if self._sink is not None and self._reads:
            self._sink(
                GenerationLog(
                    model_name="claude-sonnet-4-6",
                    input_tokens=20,
                    output_tokens=5,
                    cache_read_input_tokens=self._reads.pop(0),
                    cache_creation_input_tokens=self._creations.pop(0),
                )
            )
        return None


class TestCliReportsTheOperatingRate:
    """회차 리포트·대장이 적중률을 실제로 낸다(정본화 ≠ 집행 — 산출물로 확인)."""

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        reads: list[int],
        creations: list[int],
        caching_enabled: bool,
    ) -> tuple[dict, Path]:
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _CacheEmittingGenerator(
                kwargs.get("generation_log_sink"), reads=reads, creations=creations
            ),
        )

        class _FakeSettings:
            anthropic_prompt_caching = caching_enabled

        monkeypatch.setattr(problem_corpus_accumulate, "get_settings", lambda: _FakeSettings())
        out = tmp_path / "acc.jsonl"
        # 시드 코퍼스는 주지 않는다 — 이 파일의 관심사는 dedup이 아니라 캐시 계측이고,
        # 생성기가 후보를 내지 않으므로 dedup 인덱스는 판정에 관여하지 않는다.
        code = main(
            [
                "--out",
                str(out),
                "--n",
                str(len(reads)),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert code == 1  # 후보 0건이라 무진전 — 캐시 계측은 그와 무관하게 나와야 한다
        return code, out

    def test_report_and_ledger_carry_the_hit_rate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        n = 10
        self._run(
            tmp_path,
            monkeypatch,
            reads=[0] + [2000] * (n - 1),
            creations=[2000] + [0] * (n - 1),
            caching_enabled=True,
        )

        payload = json.loads(capsys.readouterr().out)
        cache = payload["prompt_cache"]

        assert cache["calls_with_cache_telemetry"] == n
        assert cache["state"] == "enabled_working"
        assert cache["hit_rate"] is not None and cache["hit_rate"] > 0.85

        # 대장 행에도 같은 값이 남아야 회차 *간* 비교가 성립한다(1회 0%는 우연일 수 있다).
        records, errors = load_round_ledger(default_round_ledger_path(tmp_path / "acc.jsonl"))
        assert not errors
        assert records[-1].prompt_cache is not None
        assert records[-1].prompt_cache["state"] == "enabled_working"

    def test_enabled_but_never_hitting_is_visible(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """플래그 ON + 적중 0% → 리포트가 '켰지만 작동 안 함'을 말한다(이 태스크의 목적)."""
        self._run(
            tmp_path,
            monkeypatch,
            reads=[0] * 6,
            creations=[0] * 6,
            caching_enabled=True,
        )

        cache = json.loads(capsys.readouterr().out)["prompt_cache"]

        assert cache["hit_rate"] == 0.0
        assert cache["state"] == "enabled_not_working"


class TestLiveMeasurementCanActuallyReachTheCloud:
    """계측이 **도달 가능한가** — 라우터가 LOCAL로 강제하면 적중률은 영영 정의되지 않는다.

    지적: PR #1023 codex P1. 이 파일의 나머지가 "캐시 토큰이 들어오면 옳게 집계하는가"를
    본다면, 이 클래스는 그 앞 질문 — **애초에 클라우드 호출이 일어날 수 있는가** — 를 본다.
    종전 `_build_live_generator`는 구독·예산을 둘 다 단일 좌석(free/0.0)으로 고정했고,
    라우터는 그 둘을 각각 독립적으로 LOCAL로 강제한다. 그래서 Anthropic 키를 넣어도 회차는
    `state='not_applicable'`만 냈다 — 측정 회차가 측정 아닌 이유로 공전한다
    (CLAUDE.md "검증 없는 실행 안내 금지"·"가정 기반 런북 금지").

    실측(2026-09-07): free/0=local · free/5000=local · **premium/0=local** · premium/5000=cloud_mid.
    """

    @staticmethod
    def _tier(subscription: str, budget_krw: float) -> str:
        from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

        gen = LLMEquivalentProblemGenerator(
            _NullProvider(), subscription=subscription, budget_krw=budget_krw
        )
        decision = gen._decide_routing(_spec())
        return str(decision.cost_tier)

    def test_default_seat_stays_local(self) -> None:
        """기본값(미지정)은 종전 그대로 LOCAL — 이 PR이 라우팅 기본을 바꾸지 않았다."""
        from whymath_backend.l3.equivalent.llm_generator import LLMEquivalentProblemGenerator

        gen = LLMEquivalentProblemGenerator(_NullProvider())

        assert str(gen._decide_routing(_spec()).cost_tier) == "local"

    def test_both_signals_are_required(self) -> None:
        """구독만·예산만으로는 못 나간다 — 둘 다 필요하다(한쪽만 고치는 오해 차단)."""
        assert self._tier("premium", 0.0) == "local"  # 구독만 열림
        assert self._tier("free", 5000.0) == "local"  # 예산만 열림
        assert self._tier("premium", 5000.0) == "cloud_mid"  # 둘 다 열림

    def test_cli_propagates_both_or_neither(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI 플래그가 생성기까지 실제로 도달한다 — 미지정이면 **키 자체를 싣지 않는다**.

        None을 그대로 넘기면 생성자 기본값(단일 좌석)이 덮여 회귀가 난다. 그래서 '전달됨'이
        아니라 '전달되지 않음'까지 함께 못박는다.
        """
        captured: dict[str, object] = {}

        class _Spy:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured.update(kwargs)

            def generate(self, spec: EquivalenceSpec) -> None:
                return None

        monkeypatch.setattr(
            "whymath_backend.l3.equivalent.llm_generator.LLMEquivalentProblemGenerator",
            _Spy,
        )

        problem_corpus_accumulate._build_live_generator("힌트")
        assert "subscription" not in captured and "budget_krw" not in captured

        captured.clear()
        problem_corpus_accumulate._build_live_generator(
            "힌트", subscription="premium", budget_krw=5000.0
        )
        assert captured["subscription"] == "premium"
        assert captured["budget_krw"] == 5000.0

    def test_cli_argv_reaches_the_generator(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**argv → 생성기**까지 관통 확인 — 헬퍼만 검사하면 배선 누락을 못 잡는다.

        위 테스트는 `_build_live_generator`를 직접 부르므로 `main()`의 argparse→헬퍼 구간이
        빠진다. 실제로 그 구간을 끊는 뮤테이션(M12: `subscription=None` 하드코딩)이 위 검사만
        있을 때 **초록으로 통과**했다 — 계약을 만들고 집행 지점을 안 본 전형이다
        (CLAUDE.md "정본화를 집행으로 착각한 완료 선언 금지"). 이 검사가 그 구간을 못박는다.
        """
        captured: dict[str, object] = {}

        class _Spy:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured.update(kwargs)

            def generate(self, spec: EquivalenceSpec) -> None:
                return None

        monkeypatch.setattr(
            "whymath_backend.l3.equivalent.llm_generator.LLMEquivalentProblemGenerator",
            _Spy,
        )
        main(
            [
                "--out",
                str(tmp_path / "acc.jsonl"),
                "--n",
                "1",
                "--canary",
                "0",
                "--abort-window",
                "0",
                "--subscription",
                "premium",
                "--budget-krw",
                "5000",
            ]
        )
        capsys.readouterr()

        assert captured["subscription"] == "premium"
        assert captured["budget_krw"] == 5000.0
