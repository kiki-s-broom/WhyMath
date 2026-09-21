"""코퍼스 축적 배치(problem_corpus_accumulate) 단위테스트 — 회차 간 dedup·증분 append(hermetic).

라이브 스모크(2026-07-07)에서 확인된 갭(회차마다 fresh index·전면 교체)이 상환됨을 결정론
스켈레톤 생성기 주입으로 검증한다(LLM 0). 스켈레톤 풀은 고정 시드라 fresh 생성기가 매번 같은
순서로 후보를 내므로, 시드/축적분과의 구조 중복이 재현 가능하게 발생한다 — dedup 검증에 이상적.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.problem_corpus_accumulate import (
    load_corpus_index,
    main,
    run_corpus_accumulate,
)
from whymath_backend.harness.problem_corpus_batch import run_corpus_batch
from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.skeleton_generator import SkeletonEquivalentProblemGenerator

_STANDARD = "[10공수1-02-02]"


def _spec() -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({_STANDARD}),
        target_misconception_ids=frozenset(),
        difficulty_overall=2.5,
        answer_format=None,
    )


def _seed_corpus(tmp_path: Path, short_n: int = 6) -> Path:
    """소형 결정론 시드 코퍼스 — 스켈레톤 배치의 quad 단답형 밴드만."""
    src = tmp_path / "seed.jsonl"
    report = run_corpus_batch(
        out_path=src,
        short_n=short_n,
        mc_n=0,
        sqrt_n=0,
        sqrt_mc_n=0,
        calc_extremum_n=0,
        calc_tangent_n=0,
        calc_value_n=0,
        calc_value_mc_n=0,
        calc_extremum_irr_n=0,
        exp_n=0,
        log_n=0,
        arith_n=0,
        geo_n=0,
        trig_n=0,
        arith_sum_n=0,
        geo_sum_n=0,
        trig_eq_n=0,
        seq_inductive_n=0,
        write=True,
    )
    assert report.fulfilled
    return src


class TestLoadCorpusIndex:
    def test_loads_signatures_and_slugs(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=6)
        signatures, slugs, total = load_corpus_index([seed])
        assert total == 6
        assert len(slugs) == 6
        assert len(signatures) == 6  # quad는 다항이라 전건 정규화 가능

    def test_missing_path_skipped(self, tmp_path: Path) -> None:
        signatures, slugs, total = load_corpus_index([tmp_path / "nope.jsonl"])
        assert (signatures, slugs, total) == (set(), set(), 0)


class TestRunCorpusAccumulate:
    def test_seed_structures_are_deduped_and_fresh_appended(self, tmp_path: Path) -> None:
        # 시드 6건과 같은 풀 순서의 fresh 생성기 → 앞 6회는 회차 간 dedup, 뒤 4회만 신규 append.
        seed = _seed_corpus(tmp_path, short_n=6)
        out = tmp_path / "accumulated.jsonl"
        report = run_corpus_accumulate(
            out_path=out,
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=10,
        )
        assert report.seed_records == 6
        assert report.existing_out_records == 0
        assert report.outcome_counts.get("rejected_duplicate", 0) == 6  # 시드 구조 전부 차단
        assert report.accepted == 4
        assert report.appended == 4
        assert report.reason_sample  # 미수용 사유 관측(조용한 실패 금지)
        assert len(load_problem_bank_records(out)) == 4

    def test_second_run_appends_incrementally(self, tmp_path: Path) -> None:
        # 회차 2: 시드 6 + 축적 4가 전부 index에 실려 앞 10회 dedup → 신규 2만 증분 append.
        seed = _seed_corpus(tmp_path, short_n=6)
        out = tmp_path / "accumulated.jsonl"
        run_corpus_accumulate(
            out_path=out,
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=10,
        )
        report = run_corpus_accumulate(
            out_path=out,
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=12,
        )
        assert report.existing_out_records == 4
        assert report.outcome_counts.get("rejected_duplicate", 0) == 10
        assert report.accepted == 2
        assert report.appended == 2
        records = load_problem_bank_records(out)
        assert len(records) == 6  # 4 + 2 증분(전면 교체 아님)
        slugs = [r.slug for r in records]
        assert len(slugs) == len(set(slugs))  # 축적분 내 slug 유일

    def test_appended_records_roundtrip_and_disjoint_from_seed(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=6)
        out = tmp_path / "accumulated.jsonl"
        run_corpus_accumulate(
            out_path=out,
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=10,
        )
        seed_slugs = {r.slug for r in load_problem_bank_records(seed)}
        out_slugs = {r.slug for r in load_problem_bank_records(out)}
        assert out_slugs.isdisjoint(seed_slugs)  # 시드와 중복 0(회차 간 dedup 실증)

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=3)
        out = tmp_path / "accumulated.jsonl"
        report = run_corpus_accumulate(
            out_path=out,
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=5,
            write=False,
        )
        assert report.appended == 0
        assert not out.exists()


class TestCliEntry:
    def test_main_without_live_llm_exits_1(
        self, tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # fail-closed 계약(전건 generation_failed → 무진전 exit 1)은 환경 무관이어야 한다.
        # [OPS-44 사고 경위] "이 환경 LLM 0" 전제였으나 Kiki 머신은 Ollama가 상시 기동이라
        # 실제 생성이 성공해 깨졌다 — 라이브 생성기 조립을 전건 실패 스텁으로 교체해 봉인.
        class _AlwaysFailingGenerator:
            """provider 장애 환경 재현 — generate가 항상 None(orchestrator가 generation_failed로 기록)."""

            def generate(self, spec: EquivalenceSpec) -> None:
                return None

        # EOS-55: _build_live_generator가 generation_log_sink 키워드를 받으므로 **kwargs 흡수.
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _AlwaysFailingGenerator(),
        )
        seed = _seed_corpus(tmp_path, short_n=3)
        out = tmp_path / "accumulated.jsonl"
        code = main(["--seed", str(seed), "--out", str(out), "--n", "2"])
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["appended"] == 0
        assert report["outcome_counts"].get("generation_failed", 0) == 2


class _AlwaysFailingGenerator:
    """전건 실패 생성기 — orchestrator가 generation_failed로 기록한다(불량 100% 주입용)."""

    def generate(self, spec: EquivalenceSpec) -> None:
        return None


class TestCanaryGate:
    """카나리 관문(EOS-95 ①②) — 같은 입력에서 임계만 바꿔 양방향 변별력을 본다.

    한쪽 방향만 보면 "상시 초록"과 "상시 빨강"을 구별할 수 없다(CLAUDE.md 2026-09-01).
    """

    def test_failing_canary_blocks_main_batch(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=3)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=40,
            canary_size=5,
            abort_window=None,  # 롤링 감시는 끄고 카나리 단독 변별력만 본다
        )
        assert report.canary_blocked is True
        # 본배치가 시작되지 않았다 — 40이 아니라 카나리 5건에서 멈춘다.
        assert report.attempted == 5
        assert report.canary is not None
        assert report.canary["passed"] is False
        assert report.canary["successes"] == 0
        assert report.aborted is False  # 롤링 중단과 구별된다

    def test_passing_canary_runs_full_batch_at_default_threshold(self, tmp_path: Path) -> None:
        """**기본 설정 그대로** 만점 카나리가 통과하고 본배치가 끝까지 돈다.

        임계를 인위적으로 낮춘 통과가 아니라 배포될 기본값(n=30·0.90)에서의 통과다 —
        "관문이 항상 막는다"가 아님을 실제 운영 설정으로 보인다. 시드를 주지 않아야
        스켈레톤 후보가 신선하다(시드를 주면 같은 결정론 풀이라 전건 중복이 된다).
        """
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=35,
            abort_window=None,
        )
        assert report.canary_blocked is False
        assert report.attempted == 35  # 끝까지 돌았다
        assert report.canary is not None
        assert report.canary["passed"] is True
        assert report.canary["trials"] == 30
        assert report.canary["successes"] == 30

    def test_perfect_canary_passes_090_but_blocks_at_095(self, tmp_path: Path) -> None:
        """설계서 명세(n=30·임계 0.95)가 왜 만족 불가능한지를 **파이프라인 끝단에서** 동결한다.

        완전히 같은 입력·생성기에서 **임계만** 0.90↔0.95로 바꾼다. 카나리가 30/30 만점인데도
        0.95에서는 차단된다(Wilson 하한 91.7% < 95%) — 이것이 EOS-95 ②의 임계 결정 근거이며,
        동시에 관문이 임계를 실제로 읽는다는 양방향 변별력 증거다.
        """

        def _run(threshold: float):  # noqa: ANN202 — 테스트 지역 헬퍼
            return run_corpus_accumulate(
                out_path=tmp_path / f"acc-{threshold}.jsonl",
                seed_paths=[],
                generator=SkeletonEquivalentProblemGenerator(),
                spec=_spec(),
                n=35,
                canary_size=30,
                canary_threshold=threshold,
                abort_window=None,
            )

        adopted = _run(0.90)  # 채택된 임계
        design_doc = _run(0.95)  # 설계서가 제안했던 임계

        assert adopted.canary is not None and design_doc.canary is not None
        # 두 회차 모두 카나리는 만점이다 — 다른 것은 임계뿐이다.
        assert adopted.canary["successes"] == design_doc.canary["successes"] == 30
        assert adopted.canary["wilson_lower"] == design_doc.canary["wilson_lower"]
        assert 0.916 < adopted.canary["wilson_lower"] < 0.918

        assert adopted.canary_blocked is False
        assert adopted.attempted == 35
        assert design_doc.canary_blocked is True  # 만점인데 차단된다
        assert design_doc.attempted == 30

    def test_small_batch_gets_advisory_verdict_not_silence(self, tmp_path: Path) -> None:
        """n <= canary_size면 **차단은 못 하되 판정은 낸다**(권고).

        [정정 경위] 초판은 이 경우 판정을 아예 생략했다(canary=None). 그런데 CLI 기본
        `--n`이 20이고 카나리 기본이 30이라 **기본 경로 전체가 무판정**이었다 — 보호를
        "기본 ON"이라 적어 놓고 아무것도 하지 않는 상태(PR #989 Codex P1). 차단력이
        없더라도 몇 건 중 몇 건이었는지는 남아야 운영자가 상태를 안다.
        """
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=3,
            canary_size=5,
            abort_window=None,
        )
        assert report.canary is not None  # 침묵하지 않는다
        assert report.canary_advisory is True  # 다만 차단력은 없다
        assert report.canary_blocked is False
        assert report.attempted == 3  # 전량 돌았다(차단하지 않았으므로)

    def test_exact_boundary_is_advisory_not_blocking(self, tmp_path: Path) -> None:
        """n == canary_size **정확히 경계** — 막을 본배치가 없으므로 차단하지 않는다.

        [뮤테이션 경위] 처음에는 n=3·canary=5로만 확인했는데, `n > canary_size`를
        `n >= canary_size`로 바꾸는 뮤테이션이 **검출되지 않았다**(3 >= 5도 False라 양쪽이
        같은 화면을 냈다 — 변별력 0인 검증 스텝). 경계값을 정확히 찔러야 부등호가 판정에
        실제로 쓰이는지 알 수 있다.
        """
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=5,
            canary_size=5,
            abort_window=None,
        )
        assert report.canary_blocked is False  # 차단하지 않는다
        assert report.canary_advisory is True  # 권고로 판정한다
        assert report.attempted == 5

    def test_canary_disabled(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=3)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=6,
            canary_size=None,
            abort_window=None,
        )
        assert report.canary is None
        assert report.attempted == 6


class TestDefaultConfigurationDecides:
    """**기본 설정이 실제로 판정하는가** — PR #989 Codex P1의 회귀 가드.

    [사고 경위] 초판은 카나리 30 · 롤링 창 50을 기본으로 두고 롤링 판정 시작점을 창 크기와
    같게 묶었다. 그런데 CLI 기본 `--n`은 **20**이다:

        n=20 <= 카나리 30  → 막을 본배치가 없어 카나리 미판정
        n=20 <  창 50      → 최소 표본 미달이라 롤링 미판정
        → 전건 실패 20건인데 canary=None · blocked=False · aborted=False

    두 안전장치가 "기본 ON"이라고 적힌 채 **기본 경로에서 아무것도 하지 않았다.** 뮤테이션
    12종이 이걸 못 잡은 이유는 분명하다 — 테스트가 매번 게이트 인자를 **명시로 넘겨 기본
    설정을 한 번도 실행하지 않았다**. 이 클래스는 그 공백을 메운다: 게이트 인자를 **하나도
    주지 않고** 호출한다.
    """

    def test_default_configuration_actually_decides(self, tmp_path: Path) -> None:
        """게이트 인자 무지정 + CLI 기본 크기(20) + 전건 실패 → 안전 판정이 **나야** 한다."""
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=20,  # CLI 기본값과 동일 — 게이트 인자는 일부러 주지 않는다
        )
        # 어떤 형태로든 안전 판정이 실재해야 한다(침묵 금지).
        assert report.aborted is True, "기본 설정에서 롤링 감시가 판정하지 않았다"
        assert report.attempted < 20, "전건 실패인데 20건을 끝까지 돌았다"
        assert report.canary is not None, "기본 설정에서 카나리가 아무 판정도 남기지 않았다"

    def test_default_configuration_lets_healthy_batch_through(self, tmp_path: Path) -> None:
        """반대 방향 — 정상 배치는 기본 설정에서 끝까지 돈다(상시 중단은 보호가 아니다)."""
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=20,
        )
        assert report.aborted is False
        assert report.attempted == 20
        assert report.accepted == 20

    def test_duplicates_do_not_trip_the_abort(self, tmp_path: Path) -> None:
        """중복은 결함이 아니다 — dedup이 일한 회차를 안전장치가 죽이면 안 된다.

        시드와 같은 결정론 풀을 쓰면 전건 `rejected_duplicate`가 난다. 이것을 불량으로
        세면 정상 축적 회차가 중단된다(기존 회귀 테스트가 실제로 이걸 잡았다).
        """
        seed = _seed_corpus(tmp_path, short_n=4)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=20,
        )
        assert report.outcome_counts.get("rejected_duplicate", 0) > 0
        assert report.aborted is False, "중복이 롤링 중단을 유발했다 — 중복은 결함이 아니다"
        assert report.attempted == 20


class TestRollingAbort:
    """롤링 불량률 중단(EOS-95 ③)."""

    def test_aborts_on_sustained_failure(self, tmp_path: Path) -> None:
        seed = _seed_corpus(tmp_path, short_n=3)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=40,
            canary_size=None,  # 카나리는 끄고 롤링 단독 변별력만 본다
            abort_window=5,
            abort_threshold=0.30,
        )
        assert report.aborted is True
        assert report.attempted == 5  # 창이 차자마자 멈춘다
        assert report.abort_reason is not None
        assert "롤링 불량률 초과" in report.abort_reason
        assert report.canary_blocked is False

    def test_clean_batch_does_not_abort(self, tmp_path: Path) -> None:
        """정상 배치는 멈추지 않는다 — 상시 중단하는 장치는 보호가 아니다.

        시드를 주지 않아야 스켈레톤 후보가 수용된다(시드를 주면 같은 결정론 풀이라 전건
        `rejected_duplicate` — 그건 "정상 배치"가 아니라 불량 100% 배치다).
        """
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=8,
            canary_size=None,
            abort_window=3,
            abort_threshold=0.30,  # 불량이 있었다면 진작 멈췄을 임계
        )
        assert report.aborted is False
        assert report.attempted == 8
        assert report.accepted == 8

    def test_abort_preserves_accepted_and_queues_rejected(self, tmp_path: Path) -> None:
        """중단은 폐기가 아니다 — 그 시점까지의 비수용분이 검수 큐로 흘러야 한다."""
        seed = _seed_corpus(tmp_path, short_n=3)
        queued: list[object] = []
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=40,
            review_sink=queued.append,
            canary_size=None,
            abort_window=4,
            abort_threshold=0.30,
        )
        assert report.aborted is True
        # 중단 시점까지 관측한 비수용 outcome이 전부 큐에 남았다(원인 분석 재료 보존).
        assert len(queued) == report.attempted == 4

    def test_abort_still_appends_accepted_records_to_disk(self, tmp_path: Path) -> None:
        """중단 ≠ 폐기 — 중단 시점까지 수용된 문항이 **파일에 실제로 남아야** 한다.

        리포트의 accepted 카운트만 보면 "집계는 맞는데 디스크에는 없는" 상태를 못 잡는다.
        앞부분은 성공하고 뒤부터 전건 실패하는 생성기로 중단을 유발한 뒤, 코퍼스 파일을
        다시 읽어 레코드가 실재하는지 확인한다.
        """

        class _FailAfterGenerator:
            """앞 `healthy`회는 스켈레톤에 위임하고 이후는 전건 실패."""

            def __init__(self, healthy: int) -> None:
                self._healthy = healthy
                self._calls = 0
                self._inner = SkeletonEquivalentProblemGenerator()

            def generate(self, spec: EquivalenceSpec):  # noqa: ANN202 — 좌석 계약 위임
                self._calls += 1
                if self._calls > self._healthy:
                    return None
                return self._inner.generate(spec)

        out = tmp_path / "acc.jsonl"
        report = run_corpus_accumulate(
            out_path=out,
            seed_paths=[],
            generator=_FailAfterGenerator(healthy=6),
            spec=_spec(),
            n=60,
            canary_size=None,
            abort_window=4,
            abort_threshold=0.30,
        )
        assert report.aborted is True
        assert report.accepted == 6  # 앞 6건은 수용됐다
        assert report.appended == 6
        # 집계가 아니라 **디스크**를 확인한다 — 중단이 앞선 성과를 지우지 않았다.
        assert out.exists()
        persisted = load_problem_bank_records(out)
        assert len(persisted) == 6

    def test_watchdog_state_reported_even_without_abort(self, tmp_path: Path) -> None:
        """중단이 없어도 감시가 돌았다는 작동 신호가 리포트에 남는다."""
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=5,
            canary_size=None,
            abort_window=3,
            abort_threshold=0.30,
        )
        assert report.aborted is False
        assert report.rolling_window is not None
        assert report.rolling_window["observed"] == 5
        assert report.rolling_window["failures_total"] == 0

    def test_attempted_is_actual_not_requested(self, tmp_path: Path) -> None:
        """중단 시 attempted가 n이면 통과율 분모가 부풀어 불량이 희석돼 보인다(정직 집계)."""
        seed = _seed_corpus(tmp_path, short_n=3)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_AlwaysFailingGenerator(),
            spec=_spec(),
            n=100,
            canary_size=None,
            abort_window=3,
            abort_threshold=0.30,
        )
        assert report.attempted == 3
        assert report.to_json()["attempted"] == 3


class TestSafetyCliWiring:
    """CLI 종료 코드(EOS-95 ①⑥) — 판정은 exit code로 한다."""

    def _patch_generator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _AlwaysFailingGenerator(),
        )

    def test_canary_block_exits_1_with_stderr_reason(
        self, tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_generator(monkeypatch)
        seed = _seed_corpus(tmp_path, short_n=3)
        out = tmp_path / "acc.jsonl"
        code = main(
            [
                "--seed",
                str(seed),
                "--out",
                str(out),
                "--n",
                "40",
                "--canary",
                "5",
                "--abort-window",
                "0",
            ]
        )
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["canary_blocked"] is True
        assert report["attempted"] == 5
        # stdout JSON 한 필드만이면 습관화돼 안 읽힌다 — stderr에도 사유가 있어야 한다.
        assert "[카나리 차단]" in captured.err  # type: ignore[attr-defined]

    def test_rolling_abort_exits_1_with_stderr_reason(
        self, tmp_path: Path, capsys: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_generator(monkeypatch)
        seed = _seed_corpus(tmp_path, short_n=3)
        out = tmp_path / "acc.jsonl"
        code = main(
            [
                "--seed",
                str(seed),
                "--out",
                str(out),
                "--n",
                "40",
                "--canary",
                "0",
                "--abort-window",
                "4",
                "--abort-threshold",
                "0.3",
            ]
        )
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        report = json.loads(captured.out)
        assert report["aborted"] is True
        assert report["attempted"] == 4
        assert "[배치 중단]" in captured.err  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "flag,value",
        [
            ("--canary", "-1"),
            ("--canary-threshold", "1.5"),
            ("--canary-confidence", "0"),
            ("--canary-confidence", "1"),
            ("--abort-window", "-1"),
            ("--abort-threshold", "-0.1"),
        ],
    )
    def test_invalid_gate_arguments_rejected(self, tmp_path: Path, flag: str, value: str) -> None:
        """변별력 없는 설정(신뢰수준 0·1 등)은 파서가 거부한다 — 상시 통과 게이트 방지."""
        out = tmp_path / "acc.jsonl"
        with pytest.raises(SystemExit) as excinfo:
            main(["--out", str(out), "--n", "2", flag, value])
        assert excinfo.value.code == 2  # argparse.error
