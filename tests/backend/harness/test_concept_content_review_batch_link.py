"""CONT-08 — 검수 입력에 연결 원자·신뢰도가 실리는가, 연결 적합성 rubric이 변별하는가.

배경: 크로스워크 연결(`concept_content.atom_codes`)은 437행 전건 기계 추정(`ai_estimated`)인데 종전
검수 입력에는 연결 원자도 신뢰도도 없었다. 그래서 `reviewed`가 "콘텐츠가 맞다"를 "이 원자에 대한
콘텐츠로 맞다"로 읽히게 했다. 택1 판정 = ⓐ(검수 입력 확장 + 연결 승인 라벨 분리).

이 파일이 고정하는 것: ① 연결 로더가 공급 경로와 같은 연결을 읽고 조인 실패를 숨기지 않는다
② 프롬프트에 연결·신뢰도·"기계 추정"이 실린다(없으면 실리지 않는다) ③ `link_ok` 파싱·무응답은 승인이
아니다 ④ 연결 변별력 프로브(엉뚱한 원자는 거절·맞는 원자는 승인)가 콘텐츠 축 측정과 섞이지 않고 CLI
게이트로 집행된다. 승격 도구의 연결 승인 게이트는 `test_concept_content_review_apply.py`가 맡는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import whymath_backend.harness.concept_content_review_batch as ccrb
from whymath_backend.harness.concept_content_link_context import (
    ContentLink,
    format_link_for_review,
    load_content_links,
)
from whymath_backend.harness.concept_content_review_batch import (
    _assess_one,
    _build_prompt,
    _control_records,
    _injected_defects,
    _link_probes,
    _parse_llm_response,
    main,
    run_batch_review,
)

from .test_concept_content_review_batch import _VerdictProvider

_REPO = Path(__file__).resolve().parents[3]
_CONTENT = _REPO / "data/corpus/concept_content_v1/content.json"


def _link(*, confidence: float | None = 0.62, primary: str | None = "A-1") -> ContentLink:
    return ContentLink(
        atom_codes=("A-1", "A-2"),
        atom_names={"A-1": "뺄셈의 의미", "A-2": "덧셈과 뺄셈의 관계"},
        primary_atom_code=primary,
        confidence=confidence,
        match_method="standard_code+name",
        mapping_review_status="ai_estimated",
    )


# ──────────────────────────────────────────────────────────────────────────
# ① 로더 — 공급 경로와 같은 연결, 조인 실패는 조용히 넘기지 않는다
# ──────────────────────────────────────────────────────────────────────────
class TestLoadContentLinks:
    def test_real_corpus_joins_every_k12_content_row(self) -> None:
        links = load_content_links()
        content = json.loads(_CONTENT.read_text(encoding="utf-8"))["content"]
        codes = {r["code"] for r in content}
        # 437 전건이 연결돼 있다 — 하나라도 빠지면 그 행은 연결 승인 요구 없이 reviewed가 된다.
        assert len(codes) == 437
        assert set(links) == codes

    def test_every_linked_atom_has_a_name_and_the_status_is_shown(self) -> None:
        for code, link in load_content_links().items():
            assert link.atom_codes, code
            assert all(c in link.atom_names for c in link.atom_codes), code  # 명칭을 지어내지 않음
            assert link.mapping_review_status == "ai_estimated"  # 현 코퍼스 사실
            assert link.confidence is not None and 0.0 < link.confidence <= 1.0

    def test_atom_codes_equal_the_supply_path_derivation(self) -> None:
        # 공급 경로(`derive_k12_content_atom_codes`)와 한 글자도 다르면 검수자가 다른 연결을 본다.
        from whymath_backend.l1.concept_atom_crosswalk.transfer import (
            derive_k12_content_atom_codes,
            load_concept_src_bridge,
            load_crosswalk_records,
        )

        crosswalk = _REPO / "data/corpus/concept_atom_crosswalk_v1/crosswalk.jsonl"
        bridge = load_concept_src_bridge(_REPO / "data/corpus/concept_graph_v1/graph.json")
        expected = derive_k12_content_atom_codes(load_crosswalk_records(crosswalk), bridge)
        assert {c: link.atom_codes for c, link in load_content_links().items()} == expected

    def _write(self, tmp_path: Path, rows: list[dict[str, object]]) -> tuple[Path, Path, Path]:
        crosswalk = tmp_path / "crosswalk.jsonl"
        crosswalk.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        graph = tmp_path / "graph.json"
        graph.write_text(
            json.dumps(
                {"concepts": [{"concept_id": "math.x", "source_id": "N9"}]}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        atoms = tmp_path / "atoms.json"
        atoms.write_text(
            json.dumps({"concepts": [{"code": "A-1", "name": "원자일"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return crosswalk, graph, atoms

    def test_unknown_atom_name_is_left_out_not_invented(self, tmp_path: Path) -> None:
        paths = self._write(
            tmp_path,
            [{"concept_id": "math.x", "atom_codes": ["A-1", "Z-9"], "confidence": 0.7}],
        )
        link = load_content_links(*paths)["N9"]
        assert dict(link.atom_names) == {"A-1": "원자일"}  # Z-9는 키 자체가 없다
        assert "(명칭 미상)" in format_link_for_review(link)

    def test_unmapped_row_is_skipped_not_forced(self, tmp_path: Path) -> None:
        paths = self._write(tmp_path, [{"concept_id": "math.x", "atom_codes": []}])
        assert load_content_links(*paths) == {}

    def test_missing_bridge_entry_raises(self, tmp_path: Path) -> None:
        paths = self._write(tmp_path, [{"concept_id": "math.unknown", "atom_codes": ["A-1"]}])
        with pytest.raises(ValueError, match="graph.json에 없음"):
            load_content_links(*paths)

    def test_duplicate_content_row_raises(self, tmp_path: Path) -> None:
        row = {"concept_id": "math.x", "atom_codes": ["A-1"]}
        paths = self._write(tmp_path, [row, row])
        with pytest.raises(ValueError, match="중복"):
            load_content_links(*paths)

    def test_missing_file_raises_instead_of_returning_empty(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_content_links(tmp_path / "none.jsonl", tmp_path / "g.json", tmp_path / "a.json")


# ──────────────────────────────────────────────────────────────────────────
# ② 프롬프트 — 검수 입력에 연결·신뢰도·기계 추정이 보인다
# ──────────────────────────────────────────────────────────────────────────
class TestPromptShowsTheLink:
    def test_prompt_without_link_has_no_link_line(self) -> None:
        assert "연결 원자:" not in _build_prompt(_control_records()[0])

    def test_prompt_with_link_shows_atoms_names_primary_confidence_and_machine_estimate(
        self,
    ) -> None:
        prompt = _build_prompt(_control_records()[0], _link())
        line = next(ln for ln in prompt.splitlines() if ln.startswith("연결 원자:"))
        assert "A-1(뺄셈의 의미)[대표]" in line
        assert "A-2(덧셈과 뺄셈의 관계)" in line and "A-2(덧셈과 뺄셈의 관계)[대표]" not in line
        assert "confidence=0.62" in line
        assert "기계 추정·미검수" in line and "ai_estimated" in line

    def test_unknown_confidence_is_shown_as_unknown_not_zero(self) -> None:
        assert "confidence=미상" in format_link_for_review(_link(confidence=None))

    def test_real_k12_row_prompt_carries_its_four_atoms(self) -> None:
        # 연결이 틀린 콘텐츠 행(주입)이 검수 입력에서 **보이는지** — 실 코퍼스 N1 행으로.
        from whymath_backend.l1.concept_content.projection import load_concept_content_from_json

        record = next(
            r for r in load_concept_content_from_json(_CONTENT, scope="K-12") if r.code == "N1"
        )
        link = load_content_links()["N1"]
        prompt = _build_prompt(record, link)
        for code in link.atom_codes:
            assert code in prompt
        assert "일대일 대응으로 세기" in prompt  # 원자 명칭이 사람이 읽을 수 있게 실린다

    def test_rubric_asks_for_link_ok_separately_from_passed(self) -> None:
        assert "link_ok" in ccrb._RUBRIC_SYSTEM
        assert "link_ok" in ccrb._JSON_SCHEMA["properties"]
        assert "link_ok" not in ccrb._JSON_SCHEMA["required"]  # 연결이 없는 행은 답하지 않는다


# ──────────────────────────────────────────────────────────────────────────
# ③ 응답 해석 — 무응답·비불리언은 승인이 아니다
# ──────────────────────────────────────────────────────────────────────────
class TestParseLinkOk:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('{"passed": true, "defects": [], "reason": "", "link_ok": true}', True),
            ('{"passed": true, "defects": [], "reason": "", "link_ok": false}', False),
            ('{"passed": true, "defects": [], "reason": ""}', None),
            ('{"passed": true, "defects": [], "reason": "", "link_ok": "true"}', None),
            ('{"passed": true, "defects": [], "reason": "", "link_ok": 1}', None),
            ("not json", None),
            ("[1, 2]", None),
        ],
    )
    def test_link_ok_is_taken_only_as_a_real_boolean(self, raw: str, expected: bool | None) -> None:
        assert _parse_llm_response(raw, "X")["link_ok"] is expected


class TestAssessOneLinkAxis:
    async def test_content_pass_and_link_are_independent_axes(self) -> None:
        # 콘텐츠는 맞아도 연결이 틀릴 수 있다 — passed를 연결 판정으로 덮지 않는다.
        provider = _VerdictProvider(passed_for_inject=True, passed_for_control=True)
        bad_record, bad_link, _ = _link_probes()[0]
        a = await _assess_one(provider, bad_record, model_tier="quality", link=bad_link)
        assert a.passed is True
        assert a.link_approved is False
        assert a.link_answered is True

    async def test_silence_is_not_approval(self) -> None:
        # 모른다 ≠ 맞다 — 연결을 줬는데 LLM이 link_ok를 안 답하면 승인이 아니다.
        provider = _VerdictProvider(
            passed_for_inject=True, passed_for_control=True, link_mode="silent"
        )
        a = await _assess_one(provider, _control_records()[0], model_tier="quality", link=_link())
        assert a.link_answered is False
        assert a.link_approved is False

    async def test_no_link_means_not_applicable_not_false(self) -> None:
        provider = _VerdictProvider(passed_for_inject=True, passed_for_control=True)
        a = await _assess_one(provider, _control_records()[0], model_tier="quality")
        assert (a.link_atoms, a.link_confidence) == ((), None)
        assert (a.link_answered, a.link_approved, a.link_probe) == (None, None, None)

    async def test_link_fields_reach_the_jsonl_row(self) -> None:
        provider = _VerdictProvider(passed_for_inject=True, passed_for_control=True)
        a = await _assess_one(
            provider, _control_records()[0], model_tier="quality", link=_link(), link_probe="good"
        )
        row = a.to_jsonl()
        assert row["link_atoms"] == ["A-1", "A-2"]
        assert row["link_confidence"] == 0.62
        assert (row["link_answered"], row["link_approved"], row["link_probe"]) == (
            True,
            True,
            "good",
        )


# ──────────────────────────────────────────────────────────────────────────
# ④ 프로브 — 콘텐츠 축과 섞이지 않고, CLI 게이트가 양방향으로 집행한다
# ──────────────────────────────────────────────────────────────────────────
class TestLinkProbes:
    def test_probe_codes_do_not_collide_with_the_content_axis_prefixes(self) -> None:
        # `__INJECT`·`__CONTROL`로 시작하면 콘텐츠 축 측정(missed_injected 등)에 섞여 들어간다.
        for record, _, _ in _link_probes():
            assert not record.code.startswith(("__INJECT", "__CONTROL"))

    def test_probes_share_clean_content_and_differ_only_in_the_link(self) -> None:
        (bad_rec, bad_link, bad_kind), (good_rec, good_link, good_kind) = _link_probes()
        assert (bad_kind, good_kind) == ("bad", "good")
        assert bad_rec.explanation == good_rec.explanation == _control_records()[0].explanation
        assert set(bad_link.atom_codes).isdisjoint(good_link.atom_codes)


class TestBatchCliLinkGate:
    def _main(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> int:
        monkeypatch.setattr(
            ccrb,
            "_FakeProvider",
            lambda: _VerdictProvider(
                passed_for_inject=False, passed_for_control=True, link_mode=mode
            ),
        )
        return main(["--fake-llm", "--out", str(tmp_path / f"{mode}.jsonl"), "--seed", "7"])

    def test_correct_link_answers_pass_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._main(tmp_path, monkeypatch, "correct") == 0  # 성공 방향 대조군

    def test_approving_everything_is_caught_as_missed_wrong_link(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._main(tmp_path, monkeypatch, "approve_all") == 1
        assert "엉뚱한 원자" in capsys.readouterr().err

    def test_rejecting_everything_is_caught_as_over_sensitive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._main(tmp_path, monkeypatch, "reject_all") == 1
        assert "과민" in capsys.readouterr().err

    def test_never_answering_is_caught(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 무응답 provider는 맞는 원자도 승인하지 못해 과민으로 잡힌다(모른다 ≠ 맞다).
        assert self._main(tmp_path, monkeypatch, "silent") == 1

    def test_jsonl_report_carries_probe_and_sampled_link_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert self._main(tmp_path, monkeypatch, "correct") == 0
        rows = [
            json.loads(ln)
            for ln in (tmp_path / "correct.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        probes = {r["link_probe"]: r for r in rows if r["link_probe"]}
        assert probes["bad"]["link_approved"] is False
        assert probes["good"]["link_approved"] is True
        sampled_k12 = [r for r in rows if r["sampled"] and r["scope"] == "K-12"]
        assert sampled_k12 and all(r["link_atoms"] for r in sampled_k12)  # 실 연결이 실렸다
        sampled_univ = [r for r in rows if r["sampled"] and r["scope"] != "K-12"]
        assert sampled_univ and all(r["link_approved"] is None for r in sampled_univ)

    def test_probes_do_not_pollute_the_content_axis_counts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 연결 프로브는 콘텐츠가 멀쩡하다 — missed_injected·false_positive_controls에 안 섞인다.
        monkeypatch.setattr(
            ccrb,
            "_FakeProvider",
            lambda: _VerdictProvider(passed_for_inject=False, passed_for_control=True),
        )
        import asyncio

        report = asyncio.run(
            run_batch_review(
                k12_path=None,
                university_path=None,
                threshold=0.05,
                confidence=0.95,
                seed=7,
                model_tier="quality",
                output_path=None,
                dry_run=False,
                fake_llm=True,
            )
        )
        assert report.injected_count == len(_injected_defects())
        assert (report.missed_injected, report.false_positive_controls) == (0, 0)
        assert (report.missed_link_bad, report.false_positive_link_good) == (0, 0)
        assert report.link_probe_count == 2


class TestRunBatchReviewLinks:
    def _run(self, **kw: object) -> ccrb.BatchReport:
        import asyncio

        return asyncio.run(
            run_batch_review(
                k12_path=None,
                university_path=None,
                threshold=0.05,
                confidence=0.95,
                seed=7,
                model_tier="quality",
                output_path=None,
                dry_run=False,
                fake_llm=True,
                **kw,  # type: ignore[arg-type]
            )
        )

    def test_explicit_empty_links_puts_no_link_into_sampled_prompts(self) -> None:
        report = self._run(links={})
        assert report.link_sampled == 0  # 표본에는 연결이 실리지 않는다(프로브는 자체 연결을 쓴다)
        assert report.link_probe_count == 2

    def test_default_loads_the_real_links_for_k12_samples(self) -> None:
        report = self._run()
        assert report.link_sampled > 0

    def test_dry_run_marks_discrimination_unmeasured(self) -> None:
        import asyncio

        report = asyncio.run(
            run_batch_review(
                k12_path=None,
                university_path=None,
                threshold=0.05,
                confidence=0.95,
                seed=7,
                model_tier="quality",
                output_path=None,
                dry_run=True,
                fake_llm=False,
            )
        )
        assert report.discrimination_measured is False
        assert "측정값이 아니다" in report.render()
