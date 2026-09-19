"""축적 회차의 **spec 순환**(EOS-121 C)·**중복 출처 집계**(B)·**`--top-p` 배선**(A의 CLI) 테스트.

근거 문서: `docs/ops/eos121_seat_generation_diversity_precheck.md` §2·§4.

게이트가 요구하는 회차는 좌석당 30회 × spec 3종 = 180호출이다. 그 회차가 acceptance ②③을
채우려면 **회차 중에** 세 가지가 기록돼야 한다 — spec별 결과(②), 중복의 출처(③), 그리고 둘을
좌석과 묶을 회차 대장. 셋 다 **사후 복원이 불가**하다(signature 인덱스는 회차가 끝나면 기존분과
회차분이 섞인 한 덩어리다). 그래서 여기서 못 박는 것은 "값이 맞는가"가 아니라 **"그 값이 남는가"**다.

hermetic — LLM 0. 결정론 스켈레톤 생성기와 캡처 fake만 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.anchor_round_ledger import load_round_ledger
from whymath_backend.harness.needs_review_worklist import load_review_queue_jsonl
from whymath_backend.harness.problem_corpus_accumulate import (
    SpecSeat,
    load_spec_plan_file,
    main,
    run_corpus_accumulate,
)
from whymath_backend.harness.problem_corpus_batch import run_corpus_batch
from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.skeleton_generator import SkeletonEquivalentProblemGenerator

_STANDARD = "[10공수1-02-02]"


def _spec(difficulty: float = 2.5) -> EquivalenceSpec:
    return EquivalenceSpec(
        achievement_standard_codes=frozenset({_STANDARD}),
        target_misconception_ids=frozenset(),
        difficulty_overall=difficulty,
        answer_format=None,
    )


def _seed_corpus(tmp_path: Path, short_n: int = 6) -> Path:
    """소형 결정론 시드 코퍼스 — `test_problem_corpus_accumulate`의 헬퍼와 같은 밴드."""
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


class _EchoGenerator:
    """같은 결정론 풀을 **두 벌** 돌린다 — 짝수 시도의 구조를 홀수 시도가 그대로 되풀이한다.

    스켈레톤 생성기는 고정 시드라 fresh 인스턴스 둘이 같은 순서로 같은 후보를 낸다(실측).
    그래서 이 생성기의 시도 1·3·5…는 **직전 시도와 구조가 같고**, 시드 코퍼스가 비어 있으면
    그 중복은 정의상 *회차 내* 중복이다 — 「회차내 vs 코퍼스」 변별을 낼 픽스처다.
    """

    def __init__(self) -> None:
        self._even = SkeletonEquivalentProblemGenerator()
        self._odd = SkeletonEquivalentProblemGenerator()
        self._calls = 0

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        source = self._even if self._calls % 2 == 0 else self._odd
        self._calls += 1
        return source.generate(spec)


class _SpecRecordingGenerator:
    """어떤 spec으로 몇 번 불렸는지 기록하는 생성기(좌석 순환 관찰용)."""

    def __init__(self) -> None:
        self.seen_difficulties: list[float] = []
        self._inner = SkeletonEquivalentProblemGenerator()

    def generate(self, spec: EquivalenceSpec) -> CandidateProblem | None:
        self.seen_difficulties.append(spec.difficulty_overall)
        return self._inner.generate(spec)


# ──────────────────────────────────────────────────────────────────────
# B — 중복 출처가 회차 리포트에 남는가
# ──────────────────────────────────────────────────────────────────────
class TestDuplicateSourcesInReport:
    def test_corpus_duplicates_are_reported_as_corpus(self, tmp_path: Path) -> None:
        """시드 코퍼스와 겹친 중복은 전건 `corpus` — dedup 정상 동작이지 다양성 문제가 아니다."""
        seed = _seed_corpus(tmp_path, short_n=6)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=10,
            abort_window=None,
            canary_size=None,
        )
        sources = report.duplicate_sources
        assert report.outcome_counts.get("rejected_duplicate", 0) == 6
        assert sources["duplicates_total"] == 6
        assert sources["counts"]["structural_signature/corpus"] == 6
        assert sources["counts"]["structural_signature/round"] == 0
        assert sources["origin_resolved_rate"] == 1.0

    def test_round_internal_duplicates_are_reported_as_round(self, tmp_path: Path) -> None:
        """시드 없이 같은 구조를 되풀이하면 전건 `round` — 이것이 *생성 다양성* 신호다.

        **이 절의 반례**: 출처를 항상 `corpus`로 적는 구현은 위 코퍼스 테스트만으로는 통과한다.
        두 테스트가 짝이어야 변별력이 생긴다.
        """
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=_EchoGenerator(),
            spec=_spec(),
            n=6,
            abort_window=None,
            canary_size=None,
        )
        sources = report.duplicate_sources
        assert report.outcome_counts.get("rejected_duplicate", 0) == 3
        assert sources["counts"]["structural_signature/round"] == 3
        assert sources["counts"]["structural_signature/corpus"] == 0

    def test_mixed_round_has_both_origins(self, tmp_path: Path) -> None:
        """한 회차에 두 출처가 **동시에** 나오면 각각 제 칸에 들어간다(합산 뭉갬 배제)."""
        seed = _seed_corpus(tmp_path, short_n=2)
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[seed],
            generator=_EchoGenerator(),
            spec=_spec(),
            n=8,
            abort_window=None,
            canary_size=None,
        )
        counts = report.duplicate_sources["counts"]
        assert counts["structural_signature/corpus"] > 0
        assert counts["structural_signature/round"] > 0
        assert (
            counts["structural_signature/corpus"] + counts["structural_signature/round"]
            == report.outcome_counts["rejected_duplicate"]
        )

    def test_round_scope_is_fresh_per_round(self, tmp_path: Path) -> None:
        """**회차 장부는 회차마다 새로** 만들어진다 — 2회차의 1회차분 겹침은 `corpus`다.

        **이 절의 반례**: 장부를 호출자에게 받아 재사용하거나 모듈 전역에 두면 여기서 `round`가
        나온다. 장부 인스턴스의 수명이 곧 '회차'의 정의라는 계약을 동결하는 자리다.
        """
        out = tmp_path / "acc.jsonl"
        first = run_corpus_accumulate(
            out_path=out,
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=3,
            abort_window=None,
            canary_size=None,
        )
        assert first.appended == 3
        second = run_corpus_accumulate(
            out_path=out,
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=3,
            abort_window=None,
            canary_size=None,
        )
        # 2회차의 3건은 전부 1회차 산출물(=이제 기존 코퍼스)과 겹친다.
        assert second.outcome_counts.get("rejected_duplicate", 0) == 3
        assert second.duplicate_sources["counts"]["structural_signature/corpus"] == 3
        assert second.duplicate_sources["counts"]["structural_signature/round"] == 0

    def test_no_duplicate_round_is_unmeasured_not_zero(self, tmp_path: Path) -> None:
        """중복 0건 회차는 `measured=false` — 구분 장치가 *일할 일이 없었다*(고장이 아니다)."""
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=3,
            abort_window=None,
            canary_size=None,
        )
        assert report.outcome_counts.get("rejected_duplicate", 0) == 0
        assert report.duplicate_sources["measured"] is False
        assert report.duplicate_sources["origin_resolved_rate"] is None


# ──────────────────────────────────────────────────────────────────────
# C — spec 순환
# ──────────────────────────────────────────────────────────────────────
class TestSpecCycling:
    def test_seats_rotate_round_robin(self, tmp_path: Path) -> None:
        """시도가 좌석을 **번갈아** 탄다 — 블록으로 몰지 않는다.

        중단(카나리·롤링)이 나도 표본이 한 spec에 쏠리지 않게 하는 것이 라운드로빈의 이유다.
        난이도를 좌석별로 달리해 호출된 spec을 생성기가 직접 관찰한다(추론이 아니라 관측).
        """
        recorder = _SpecRecordingGenerator()
        seats = [
            SpecSeat(spec_id=f"s{i}", spec=_spec(difficulty), generator=recorder)
            for i, difficulty in enumerate((2.0, 3.0, 4.0))
        ]
        run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            spec_seats=seats,
            n=6,
            abort_window=None,
            canary_size=None,
        )
        assert recorder.seen_difficulties == [2.0, 3.0, 4.0, 2.0, 3.0, 4.0]

    def test_spec_outcome_counts_split_by_spec(self, tmp_path: Path) -> None:
        """결과가 spec별로 갈린다 — 좌석 × spec 교차 집계의 spec 축(acceptance ②)."""
        seats = [
            SpecSeat(
                spec_id=f"s{i}",
                spec=_spec(difficulty),
                generator=SkeletonEquivalentProblemGenerator(),
            )
            for i, difficulty in enumerate((2.0, 3.0, 4.0))
        ]
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            spec_seats=seats,
            n=6,
            abort_window=None,
            canary_size=None,
        )
        assert set(report.spec_outcome_counts) == {"s0", "s1", "s2"}
        assert all(sum(counts.values()) == 2 for counts in report.spec_outcome_counts.values())
        # 합산이 전체와 같다 — 시도 하나가 어느 spec에도 안 실리는 일이 없다.
        total = sum(
            count for counts in report.spec_outcome_counts.values() for count in counts.values()
        )
        assert total == report.attempted

    def test_unrun_spec_keeps_empty_bucket_not_missing_key(self, tmp_path: Path) -> None:
        """순번이 안 온 spec은 **빈 dict**로 남는다 — 키가 사라지면 '안 돌았다'가 보이지 않는다.

        **이 절의 반례**: 관측된 spec만 키로 넣는 구현은 "돌았는데 전건 실패"와 "아예 안 돌았다"를
        같은 화면으로 만든다(미측정 ≠ 0).
        """
        seats = [
            SpecSeat(
                spec_id=f"s{i}",
                spec=_spec(difficulty),
                generator=SkeletonEquivalentProblemGenerator(),
            )
            for i, difficulty in enumerate((2.0, 3.0, 4.0))
        ]
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            spec_seats=seats,
            n=1,  # s0만 돈다
            abort_window=None,
            canary_size=None,
        )
        assert report.spec_outcome_counts["s1"] == {}
        assert report.spec_outcome_counts["s2"] == {}

    def test_spec_plan_records_resolved_values(self, tmp_path: Path) -> None:
        """계획이 **해석된 값 전문**으로 남는다 — 경로·해시가 아니라 값이라 행이 자족한다."""
        seats = [
            SpecSeat(
                spec_id="alpha",
                spec=_spec(2.0),
                generator=SkeletonEquivalentProblemGenerator(),
                topic_hint="힌트 A",
            )
        ]
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            spec_seats=seats,
            n=1,
            abort_window=None,
            canary_size=None,
        )
        assert report.spec_plan == [
            {
                "spec_id": "alpha",
                "topic_hint": "힌트 A",
                "spec": {
                    "achievement_standard_codes": [_STANDARD],
                    "target_misconception_ids": [],
                    "difficulty_overall": 2.0,
                    "answer_format": None,
                },
            }
        ]

    def test_single_spec_path_is_backward_compatible(self, tmp_path: Path) -> None:
        """`generator`+`spec` 단일 호출(종전 전 호출부)은 좌석 1건으로 정규화된다."""
        report = run_corpus_accumulate(
            out_path=tmp_path / "acc.jsonl",
            seed_paths=[],
            generator=SkeletonEquivalentProblemGenerator(),
            spec=_spec(),
            n=2,
            abort_window=None,
            canary_size=None,
        )
        assert list(report.spec_outcome_counts) == ["default"]
        assert report.spec_plan[0]["spec_id"] == "default"


class TestSpecSeatValidation:
    """모호하거나 집계를 뭉개는 호출은 **fail-loud**다 — 침묵 통과가 회차 기록을 거짓으로 만든다."""

    def test_both_forms_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="함께 줄 수 없습니다"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl",
                seed_paths=[],
                generator=SkeletonEquivalentProblemGenerator(),
                spec=_spec(),
                spec_seats=[SpecSeat("s0", _spec(), SkeletonEquivalentProblemGenerator())],
                n=1,
            )

    def test_seats_plus_generator_only_is_rejected(self, tmp_path: Path) -> None:
        """**이 절의 반례** — `spec_seats` + `generator` *한쪽만* 준 호출.

        [뮤테이션 경위] 처음에는 generator·spec을 **둘 다** 준 픽스처만 있었는데, `or`를
        `and`로 바꾸는 뮤테이션이 **검출되지 않았다** — 둘 다 준 경우는 양쪽 부등호에서 똑같이
        True라 변별력이 0이었다(이름이 `test_both_forms_rejected`라고 해서 코드가 한쪽만 준
        경우를 밟는 것은 아니다). `or`가 판정에 실제로 쓰이는지는 한쪽만 준 호출이 가른다.
        """
        with pytest.raises(ValueError, match="함께 줄 수 없습니다"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl",
                seed_paths=[],
                generator=SkeletonEquivalentProblemGenerator(),
                spec_seats=[SpecSeat("s0", _spec(), SkeletonEquivalentProblemGenerator())],
                n=1,
            )

    def test_seats_plus_spec_only_is_rejected(self, tmp_path: Path) -> None:
        """같은 경계의 반대쪽 — `spec_seats` + `spec`만 준 호출도 거부한다."""
        with pytest.raises(ValueError, match="함께 줄 수 없습니다"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl",
                seed_paths=[],
                spec=_spec(),
                spec_seats=[SpecSeat("s0", _spec(), SkeletonEquivalentProblemGenerator())],
                n=1,
            )

    def test_neither_form_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="둘 다 주거나"):
            run_corpus_accumulate(out_path=tmp_path / "acc.jsonl", seed_paths=[], n=1)

    def test_generator_without_spec_rejected(self, tmp_path: Path) -> None:
        """**경계** — 한쪽만 준 호출도 거부한다(`and`를 `or`로 바꾸는 뮤테이션의 반례)."""
        with pytest.raises(ValueError, match="둘 다 주거나"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl",
                seed_paths=[],
                generator=SkeletonEquivalentProblemGenerator(),
                n=1,
            )

    def test_empty_seats_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="비었습니다"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl", seed_paths=[], spec_seats=[], n=1
            )

    def test_duplicate_spec_id_rejected(self, tmp_path: Path) -> None:
        """같은 `spec_id` 둘은 집계 키가 겹쳐 **합산**된다 — 가르려고 만든 축이 스스로 뭉개진다."""
        with pytest.raises(ValueError, match="중복입니다"):
            run_corpus_accumulate(
                out_path=tmp_path / "acc.jsonl",
                seed_paths=[],
                spec_seats=[
                    SpecSeat("same", _spec(2.0), SkeletonEquivalentProblemGenerator()),
                    SpecSeat("same", _spec(3.0), SkeletonEquivalentProblemGenerator()),
                ],
                n=2,
            )


# ──────────────────────────────────────────────────────────────────────
# spec 계획 파일 — 측정 회차의 *설정*이므로 오류는 전부 fail-loud
# ──────────────────────────────────────────────────────────────────────
class TestLoadSpecPlanFile:
    def _write(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "plan.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def _load(self, path: Path) -> list[tuple[str, EquivalenceSpec, str]]:
        return load_spec_plan_file(
            path,
            default_standard_code=_STANDARD,
            default_difficulty=2.5,
            default_topic_hint="기본 힌트",
        )

    def test_reads_powershell_utf8_bom_file(self, tmp_path: Path) -> None:
        """PowerShell 5.1 `Set-Content -Encoding utf8`이 내놓는 BOM + CRLF 파일을 읽는다.

        이 절이 없으면(로더가 `utf-8`로 읽으면) 첫 줄 앞에 U+FEFF가 남아
        `JSONDecodeError: Unexpected UTF-8 BOM`으로 죽는다. 2026-09-19 Phaiakes9
        파일럿 회차가 **LLM 호출 0건에서 exit 2**로 끝난 실제 실패다.

        픽스처가 BOM과 CRLF를 **둘 다** 갖는 이유: Kiki 머신이 실제로 내놓는 바이트가
        그 조합이고, 한쪽만 재현하면 나머지 축을 한 번도 밟지 않는다.
        """
        path = tmp_path / "plan.jsonl"
        body = (
            "\r\n".join(
                json.dumps({"spec_id": sid, "topic_hint": f"힌트 {sid}"}, ensure_ascii=False)
                for sid in ("a", "b", "c")
            )
            + "\r\n"
        )
        path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        # 픽스처가 정말 BOM을 갖는지 단언한다 — 갖지 않으면 이 테스트는 BOM 축을
        # 한 번도 검사하지 않은 채 통과한다(주입이 대상에 닿았는가).
        assert path.read_bytes()[:3] == b"\xef\xbb\xbf"

        entries = self._load(path)
        assert [entry[0] for entry in entries] == ["a", "b", "c"]

    def test_reads_plain_utf8_without_bom(self, tmp_path: Path) -> None:
        """대조군 — BOM이 없는 파일도 그대로 읽힌다.

        위 테스트만 있으면 "BOM을 **요구하는**" 구현(예: 앞 3바이트를 무조건 잘라내는
        구현)도 통과한다. `utf-8-sig`는 BOM이 없으면 `utf-8`과 동일하게 동작한다.
        """
        path = tmp_path / "plan.jsonl"
        path.write_bytes((json.dumps({"spec_id": "a"}, ensure_ascii=False) + "\n").encode("utf-8"))
        assert path.read_bytes()[:3] != b"\xef\xbb\xbf"

        entries = self._load(path)
        assert [entry[0] for entry in entries] == ["a"]

    def test_parses_full_entries(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            json.dumps(
                {
                    "spec_id": "a",
                    "standard_code": "[10공수1-03-01]",
                    "difficulty": 3.5,
                    "topic_hint": "힌트 A",
                },
                ensure_ascii=False,
            )
            + "\n",
        )
        entries = self._load(path)
        assert len(entries) == 1
        spec_id, spec, hint = entries[0]
        assert spec_id == "a"
        assert spec.achievement_standard_codes == frozenset({"[10공수1-03-01]"})
        assert spec.difficulty_overall == 3.5
        assert hint == "힌트 A"

    def test_missing_keys_fall_back_to_cli_defaults(self, tmp_path: Path) -> None:
        """힌트만 갈아 3종을 돌리는 것이 가장 흔한 형태라 나머지는 CLI 단일 인자로 폴백한다."""
        path = self._write(tmp_path, '{"spec_id": "a", "topic_hint": "힌트 A"}\n')
        spec_id, spec, hint = self._load(path)[0]
        assert spec.achievement_standard_codes == frozenset({_STANDARD})
        assert spec.difficulty_overall == 2.5
        assert hint == "힌트 A"

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, '\n{"spec_id": "a"}\n\n{"spec_id": "b"}\n')
        assert [entry[0] for entry in self._load(path)] == ["a", "b"]

    def test_unknown_key_is_rejected(self, tmp_path: Path) -> None:
        """오타 키를 조용히 무시하면 "난이도를 갈랐다"고 믿는 회차가 한 난이도로 돈다."""
        path = self._write(tmp_path, '{"spec_id": "a", "dificulty": 3.0}\n')
        with pytest.raises(ValueError, match="알 수 없는 키"):
            self._load(path)

    def test_missing_spec_id_is_rejected(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, '{"difficulty": 3.0}\n')
        with pytest.raises(ValueError, match="spec_id"):
            self._load(path)

    def test_blank_spec_id_is_rejected(self, tmp_path: Path) -> None:
        """**경계** — 빈 문자열은 키로 쓸 수 없다(`not isinstance(...)`만 보는 절의 반례)."""
        path = self._write(tmp_path, '{"spec_id": "   "}\n')
        with pytest.raises(ValueError, match="spec_id"):
            self._load(path)

    def test_duplicate_spec_id_is_rejected(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, '{"spec_id": "a"}\n{"spec_id": "a"}\n')
        with pytest.raises(ValueError, match="중복"):
            self._load(path)

    def test_broken_json_is_rejected_with_line_number(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, '{"spec_id": "a"}\n{not json}\n')
        with pytest.raises(ValueError, match="line 2"):
            self._load(path)

    def test_non_object_line_is_rejected(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "[1, 2, 3]\n")
        with pytest.raises(ValueError, match="객체가 아닙니다"):
            self._load(path)

    def test_out_of_range_difficulty_is_rejected(self, tmp_path: Path) -> None:
        """난이도는 1.0~5.0 — 범위 밖이면 spec 조립이 터지고 그 사유가 그대로 올라온다."""
        path = self._write(tmp_path, '{"spec_id": "a", "difficulty": 9.9}\n')
        with pytest.raises(ValueError, match="spec 조립 실패"):
            self._load(path)

    def test_empty_file_is_rejected(self, tmp_path: Path) -> None:
        """빈 계획이 조용히 단일 spec 회차가 되면 "3종을 돌렸다"가 거짓인 채로 180호출이 나간다."""
        path = self._write(tmp_path, "\n\n")
        with pytest.raises(ValueError, match="0건"):
            self._load(path)


# ──────────────────────────────────────────────────────────────────────
# CLI — 측정자가 실제로 칠 명령 형태
# ──────────────────────────────────────────────────────────────────────
class _CapturingBuild:
    """`_build_live_generator` 대체 — 호출 kwargs를 캡처하고 결정론 생성기를 돌려준다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, topic_hint: str, **kwargs: Any) -> SkeletonEquivalentProblemGenerator:
        self.calls.append((topic_hint, dict(kwargs)))
        return SkeletonEquivalentProblemGenerator()


class TestBuildLiveGeneratorTopP:
    """`_build_live_generator` → 생성자 경계 — A의 **회귀 0** 계약이 사는 자리.

    미지정이면 생성자 호출에서 `top_p` 키 자체가 **없어야** 한다. `top_p=None`을 늘 넘기는
    구현도 결과는 같지만, 키 부재를 단언해야 "미지정 = 종전과 0바이트 차이"가 기계로 판정된다
    (`subscription`·`budget_krw`가 이미 쓰는 규약과 동일).
    """

    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        from whymath_backend.l3.equivalent import llm_generator as llm_generator_module

        seen: list[dict[str, Any]] = []

        def _fake_ctor(*args: Any, **kwargs: Any) -> SkeletonEquivalentProblemGenerator:
            seen.append(dict(kwargs))
            return SkeletonEquivalentProblemGenerator()

        monkeypatch.setattr(llm_generator_module, "LLMEquivalentProblemGenerator", _fake_ctor)
        return seen

    def test_key_is_absent_when_top_p_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**성공 방향 대조군** — 미지정이면 키가 없다(값이 None인 것과 구분한다)."""
        seen = self._capture(monkeypatch)
        problem_corpus_accumulate._build_live_generator("힌트")
        assert len(seen) == 1
        assert "top_p" not in seen[0]

    def test_key_is_present_when_top_p_is_given(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._capture(monkeypatch)
        problem_corpus_accumulate._build_live_generator("힌트", top_p=0.95)
        assert seen[0]["top_p"] == 0.95


class TestCliWiring:
    def test_top_p_defaults_to_none_through_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI 기본값은 `None`이고 그대로 전달된다 — 키 제거는 빌더가 소유한다(위 클래스).

        여기서는 CLI가 **제 값을 지어내지 않는다**는 것만 본다(예: 0.9를 기본으로 박는 구현).
        """
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        out = tmp_path / "acc.jsonl"
        main(["--out", str(out), "--n", "2", "--canary", "0", "--abort-window", "0"])
        assert len(build.calls) == 1
        assert build.calls[0][1]["top_p"] is None

    def test_top_p_is_forwarded_when_specified(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        out = tmp_path / "acc.jsonl"
        main(
            [
                "--out",
                str(out),
                "--n",
                "2",
                "--top-p",
                "0.95",
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert build.calls[0][1]["top_p"] == 0.95

    @pytest.mark.parametrize("value", ["0", "1.5", "-0.2"])
    def test_top_p_out_of_range_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        """(0,1] 밖은 인자 단계에서 막는다 — 180호출 한복판에서 공급사 400을 만나면 회차가 날아간다.

        **경계**: `0`은 `0.0 < top_p` 절이 없으면 통과한다(그 절의 반례다).
        """
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        with pytest.raises(SystemExit) as excinfo:
            main(["--out", str(tmp_path / "acc.jsonl"), "--n", "1", "--top-p", value])
        assert excinfo.value.code == 2
        assert build.calls == []  # 생성기를 만들기 전에 막혔다

    def test_top_p_upper_boundary_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**경계 대조군** — 1.0은 유효하다(`< 1.0`으로 조이는 구현의 반례)."""
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        main(
            [
                "--out",
                str(tmp_path / "acc.jsonl"),
                "--n",
                "1",
                "--top-p",
                "1.0",
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert build.calls[0][1]["top_p"] == 1.0

    def test_spec_file_drives_three_specs_in_one_round(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """**180호출 회차의 형태** — 한 번의 실행으로 spec 3종을 돌고 결과가 spec별로 갈린다."""
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        plan = tmp_path / "plan.jsonl"
        plan.write_text(
            "\n".join(
                json.dumps(entry, ensure_ascii=False)
                for entry in (
                    {"spec_id": "quad-largest", "topic_hint": "힌트 A"},
                    {"spec_id": "quad-smallest", "topic_hint": "힌트 B", "difficulty": 3.0},
                    {"spec_id": "quad-sum", "topic_hint": "힌트 C", "difficulty": 3.5},
                )
            )
            + "\n",
            encoding="utf-8",
        )
        out = tmp_path / "acc.jsonl"
        code = main(
            [
                "--out",
                str(out),
                "--n",
                "6",
                "--spec-file",
                str(plan),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert set(payload["spec_outcome_counts"]) == {
            "quad-largest",
            "quad-smallest",
            "quad-sum",
        }
        assert [entry["spec_id"] for entry in payload["spec_plan"]] == [
            "quad-largest",
            "quad-smallest",
            "quad-sum",
        ]
        # 힌트가 셋이므로 생성기도 셋 — 같은 힌트끼리만 인스턴스를 공유한다.
        assert [call[0] for call in build.calls] == ["힌트 A", "힌트 B", "힌트 C"]

    def test_same_topic_hint_shares_one_generator(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """같은 힌트를 쓰는 좌석은 **한 인스턴스**를 공유한다 — 지속 이벤트 루프가 쪼개지지 않는다.

        **이 절의 반례**: 좌석마다 새로 만드는 구현은 여기서 호출 3건이 되어 실패한다.
        """
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        plan = tmp_path / "plan.jsonl"
        plan.write_text(
            '{"spec_id": "a", "difficulty": 2.0}\n'
            '{"spec_id": "b", "difficulty": 3.0}\n'
            '{"spec_id": "c", "difficulty": 4.0}\n',
            encoding="utf-8",
        )
        main(
            [
                "--out",
                str(tmp_path / "acc.jsonl"),
                "--n",
                "3",
                "--spec-file",
                str(plan),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert len(build.calls) == 1  # 힌트가 같으므로 생성기는 하나

    def test_every_generator_is_flushed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**생성기 전건**이 flush된다 — 하나만 flush하면 나머지 좌석의 trace가 통째로 유실된다.

        **이 절의 반례**: `flush_trace`를 첫 생성기에만 거는 구현은 여기서 1 != 3으로 잡힌다.
        LangfuseSink는 배치 버퍼 전송이라 flush 없이 종료하면 이벤트가 조용히 사라진다.
        """
        flushed: list[str] = []

        class _FlushableGenerator(SkeletonEquivalentProblemGenerator):  # type: ignore[misc]
            def __init__(self, label: str) -> None:
                super().__init__()
                self._label = label

            def flush_trace(self) -> None:
                flushed.append(self._label)

        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _FlushableGenerator(topic_hint),
        )
        plan = tmp_path / "plan.jsonl"
        plan.write_text(
            '{"spec_id": "a", "topic_hint": "A"}\n'
            '{"spec_id": "b", "topic_hint": "B"}\n'
            '{"spec_id": "c", "topic_hint": "C"}\n',
            encoding="utf-8",
        )
        main(
            [
                "--out",
                str(tmp_path / "acc.jsonl"),
                "--n",
                "3",
                "--spec-file",
                str(plan),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        assert sorted(flushed) == ["A", "B", "C"]

    def test_broken_spec_file_exits_2_before_any_generation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """설정 오류는 **exit 2**다 — 1은 "돌았는데 무진전"의 어휘라 섞이면 안 된다."""
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        plan = tmp_path / "plan.jsonl"
        plan.write_text('{"spec_id": "a"}\n{oops}\n', encoding="utf-8")
        code = main(["--out", str(tmp_path / "acc.jsonl"), "--n", "3", "--spec-file", str(plan)])
        assert code == 2
        assert "spec 계획 오류" in capsys.readouterr().err
        assert build.calls == []  # 회차가 시작조차 하지 않았다

    def test_missing_spec_file_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**이 절의 반례** — 부재는 `OSError`라 `ValueError`만 잡는 구현에서 추적으로 터진다."""
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", _CapturingBuild())
        code = main(
            [
                "--out",
                str(tmp_path / "acc.jsonl"),
                "--n",
                "3",
                "--spec-file",
                str(tmp_path / "nope.jsonl"),
            ]
        )
        assert code == 2

    def test_round_ledger_carries_spec_and_duplicate_axes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """회차 대장이 **사후 복원 불가한 두 축**을 싣는다 — 이것이 없으면 180호출이 ②③에 대해
        아무것도 남기지 않는다."""
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _EchoGenerator(),
        )
        out = tmp_path / "acc.jsonl"
        plan = tmp_path / "plan.jsonl"
        plan.write_text('{"spec_id": "a"}\n{"spec_id": "b"}\n', encoding="utf-8")
        main(
            [
                "--out",
                str(out),
                "--n",
                "4",
                "--spec-file",
                str(plan),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        records, errors = load_round_ledger(out.with_suffix(".rounds.jsonl"))
        assert errors == []
        assert len(records) == 1
        row = records[0]
        assert row.spec_outcome_counts is not None
        assert set(row.spec_outcome_counts) == {"a", "b"}
        assert row.spec_plan is not None
        assert [entry["spec_id"] for entry in row.spec_plan] == ["a", "b"]
        assert row.duplicate_sources is not None
        assert row.duplicate_sources["counts"]["structural_signature/round"] == 2

    def test_review_queue_rows_carry_spec_and_duplicate_axes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """검수 큐 **행마다** spec·출처가 남는다 — 집계가 뭉갠 것을 행이 되살릴 수 있게."""
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "_build_live_generator",
            lambda topic_hint, **kwargs: _EchoGenerator(),
        )
        out = tmp_path / "acc.jsonl"
        plan = tmp_path / "plan.jsonl"
        plan.write_text('{"spec_id": "a"}\n{"spec_id": "b"}\n', encoding="utf-8")
        main(
            [
                "--out",
                str(out),
                "--n",
                "4",
                "--spec-file",
                str(plan),
                "--canary",
                "0",
                "--abort-window",
                "0",
            ]
        )
        entries, errors = load_review_queue_jsonl(out.with_suffix(".review.jsonl"))
        assert errors == []
        duplicates = [e for e in entries if e.status == "rejected_duplicate"]
        assert duplicates  # 회차가 실제로 중복을 냈다(픽스처가 그 상태를 밟는다)
        assert all(e.duplicate_detector == "structural_signature" for e in duplicates)
        assert all(e.duplicate_origin == "round" for e in duplicates)
        assert {e.spec_id for e in duplicates} <= {"a", "b"}
        assert all(e.spec_id is not None for e in entries)
