"""저작 CLI의 과목·slug 접두 선택(EOS-198 ③ · 공백 G-D).

정본: `harness/problem_corpus_accumulate.py`의 `authoring_subject_for_codes`·
`_build_live_generator(subject=, slug_prefix=)`·main의 생성기 키. 종전엔 생성기를
`Subject.공통`·`"wm-gen-quad"`로 **고정**해 만들어 A6(미적분Ⅰ) CU도 그 값으로 기록됐다.

검증 축:
  ① `[12미적Ⅰ-…]` → (미적분, wm-gen-calc1). 경계: 미적분Ⅱ·2015 숫자형·접두만 닮은 코드는 해당 없음
  ② 기존 경로(`[10공수1-…]`·`[9수…]`·코드 없음) → 종전 값 그대로 — 대조군
  ③ 한 spec 안의 혼합 코드 → ValueError, CLI는 생성기를 만들기 전에 exit 2
  ④ CLI가 spec 코드로 고른 값을 생성기 조립까지 실제로 넘긴다(산출 slug 접두까지)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.harness import problem_corpus_accumulate
from whymath_backend.harness.problem_corpus_accumulate import authoring_subject_for_codes, main
from whymath_backend.l3.equivalent.skeleton_generator import SkeletonEquivalentProblemGenerator
from whymath_backend.schema.enums import Subject

_REPO_ROOT = Path(__file__).resolve().parents[3]
_A6_PLAN = _REPO_ROOT / "docs" / "ops" / "eos197_a6_spec_plan.jsonl"


class TestAuthoringSubjectForCodes:
    @pytest.mark.parametrize(
        "code",
        ["[12미적Ⅰ-02-05]", "[12미적Ⅰ-02-07]", "[12미적Ⅰ-02-09]", "[12미적Ⅰ-02-10]"],
    )
    def test_calculus1_codes_map_to_calculus(self, code: str) -> None:
        assert authoring_subject_for_codes([code]) == ("미적분", "wm-gen-calc1")

    @pytest.mark.parametrize(
        "codes",
        [
            ["[10공수1-02-02]"],  # 저작 CLI 기본 코드 — 종전 경로
            ["[9수02-20]"],  # A4 이차방정식 앵커
            [],  # 코드 없음
            # 경계 — 접두가 닮았지만 미적분Ⅰ이 아니다(대괄호·로마숫자·하이픈까지 맞아야 한다)
            ["[12미적Ⅱ-01-01]"],
            ["[12미적01-01]"],
            ["12미적Ⅰ-02-05"],  # 대괄호 없는 표기
        ],
    )
    def test_existing_and_boundary_codes_keep_legacy_values(self, codes: list[str]) -> None:
        assert authoring_subject_for_codes(codes) == ("공통", "wm-gen-quad")

    def test_mixed_codes_are_refused_not_silently_resolved(self) -> None:
        with pytest.raises(ValueError, match="서로 다른 과목 규칙"):
            authoring_subject_for_codes(["[12미적Ⅰ-02-05]", "[10공수1-02-02]"])

    def test_generator_input_is_consumed_once(self) -> None:
        """이터레이터를 받아도 사유 문자열에 코드가 빠지지 않는다(한 번만 소비)."""
        with pytest.raises(ValueError, match=r"12미적Ⅰ-02-05"):
            authoring_subject_for_codes(iter(["[12미적Ⅰ-02-05]", "[9수02-20]"]))

    def test_every_a6_spec_in_the_eos197_plan_maps_to_calculus(self) -> None:
        """EOS-197 회차가 실제로 쓰는 계획 파일 — 4종 전부 미적분으로 기록돼야 한다."""
        rows = [
            json.loads(line)
            for line in _A6_PLAN.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(rows) == 4
        for row in rows:
            assert authoring_subject_for_codes([row["standard_code"]]) == (
                "미적분",
                "wm-gen-calc1",
            )


class TestBuildLiveGeneratorSubject:
    def test_default_build_keeps_legacy_subject_and_prefix(self) -> None:
        """대조군 — 인자 없이 만든 생성기는 종전과 같다(과목·접두·slug 해시)."""
        gen = problem_corpus_accumulate._build_live_generator("힌트")
        assert gen._subject is Subject.공통  # type: ignore[attr-defined]
        slug = gen._stable_slug("x^2-1=0", "1", ["[10공수1-02-02]"])  # type: ignore[attr-defined]
        assert slug.startswith("wm-gen-quad-")

    def test_calculus_build_sets_subject_and_prefix(self) -> None:
        gen = problem_corpus_accumulate._build_live_generator(
            "힌트", subject="미적분", slug_prefix="wm-gen-calc1"
        )
        assert gen._subject is Subject.미적분  # type: ignore[attr-defined]
        slug = gen._stable_slug("q", "1", ["[12미적Ⅰ-02-05]"])  # type: ignore[attr-defined]
        assert slug.startswith("wm-gen-calc1-")


class _CapturingBuild:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, topic_hint: str, **kwargs: Any) -> SkeletonEquivalentProblemGenerator:
        self.calls.append((topic_hint, dict(kwargs)))
        return SkeletonEquivalentProblemGenerator()


def _write_plan(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return path


class TestCliPassesSubjectToBuilder:
    def _run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]) -> Any:
        build = _CapturingBuild()
        monkeypatch.setattr(problem_corpus_accumulate, "_build_live_generator", build)
        code = main(
            [
                "--out",
                str(tmp_path / "cu.jsonl"),
                "--n",
                "1",
                "--canary",
                "0",
                "--abort-window",
                "0",
                *extra,
            ]
        )
        return code, build

    def test_a6_plan_builds_calculus_generator(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _code, build = self._run(monkeypatch, tmp_path, ["--spec-file", str(_A6_PLAN)])
        assert len(build.calls) == 4  # 힌트 4종 — 힌트별 생성기(종전과 같은 인스턴스 수)
        for _hint, kwargs in build.calls:
            assert (kwargs["subject"], kwargs["slug_prefix"]) == ("미적분", "wm-gen-calc1")

    def test_default_cli_builds_legacy_generator(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """대조군 — spec 파일 없는 기본 경로(`[10공수1-02-02]`)는 종전 값이다."""
        _code, build = self._run(monkeypatch, tmp_path, [])
        assert len(build.calls) == 1
        assert (build.calls[0][1]["subject"], build.calls[0][1]["slug_prefix"]) == (
            "공통",
            "wm-gen-quad",
        )

    def test_same_hint_different_subject_gets_separate_generators(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        plan = _write_plan(
            tmp_path / "plan.jsonl",
            [
                {"spec_id": "a", "standard_code": "[12미적Ⅰ-02-05]", "topic_hint": "같은 힌트"},
                {"spec_id": "b", "standard_code": "[10공수1-02-02]", "topic_hint": "같은 힌트"},
                {"spec_id": "c", "standard_code": "[12미적Ⅰ-02-07]", "topic_hint": "같은 힌트"},
            ],
        )
        _code, build = self._run(monkeypatch, tmp_path, ["--spec-file", str(plan)])
        assert sorted((k["subject"], k["slug_prefix"]) for _, k in build.calls) == [
            ("공통", "wm-gen-quad"),
            ("미적분", "wm-gen-calc1"),
        ]

    def test_mixed_code_spec_exits_2_before_any_generator(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`load_spec_plan_file`은 spec당 코드 1개라 혼합 spec을 계획 파일로는 만들 수 없다 —
        그래서 로더를 바꿔 혼합 코드 spec을 main에 직접 넣는다(main의 거부 분기를 밟기 위해)."""
        from whymath_backend.l3.equivalent.acceptance import EquivalenceSpec

        mixed = EquivalenceSpec(
            achievement_standard_codes=frozenset({"[12미적Ⅰ-02-05]", "[9수02-20]"}),
            target_misconception_ids=frozenset(),
            difficulty_overall=2.5,
            answer_format=None,
        )
        monkeypatch.setattr(
            problem_corpus_accumulate,
            "load_spec_plan_file",
            lambda *_a, **_k: [("mixed", mixed, "힌트")],
        )
        plan = _write_plan(tmp_path / "plan.jsonl", [{"spec_id": "x"}])
        code, build = self._run(monkeypatch, tmp_path, ["--spec-file", str(plan)])
        assert code == 2
        assert build.calls == []  # 호출 0건 — 생성기를 만들기 전에 막혔다
        assert "[spec 계획 오류] ValueError" in capsys.readouterr().err
        assert not (tmp_path / "cu.jsonl").exists()
