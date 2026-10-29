"""힌트 누설 사람 판정 좌석 — `ops/hint_human_verdicts` + 측정기 통합 (EOS-210). hermetic.

검증 축(분기마다 반례 + 대조군):
  ① 기록 계약 — 필수 필드 누락·빈 근거·잘못된 verdict·UTC 아님·이름형 판정자 ID·우회 여부 누락은
     거부 · 손상된 판정 파일은 측정 실패(exit 2)
  ② 표본 — 같은 seed → 같은 표본 · seed는 모집단에서 유도 · 매니페스트 변조(표본 바꿔치기·seed
     교체) 거부 · 현재 입력과 다른 모집단은 측정 불가
  ③ 의미 축 — n=29 측정 불가 · n=30 k=0 PASS+상한 · k=1 FAIL · 표본 미판정 측정 불가 · 매니페스트
     밖 판정 제외(따로 셈) · 표본 밖 확인 누설은 숨기지 않음
  ④ 기계 판정 불가 해소 — 사람 "아님" → 해소 · "누설" → FAIL · 낡은 판정·우회 판정은 해소에 안 씀
  ⑤ 기계 누설 + 사람 "아님" → 누설 유지 + 어긋남 보존 · 재판정 이력 보존
  ⑥ 종료 코드 — 매니페스트 미지정이면 의미 축은 종료 코드 밖(EOS-207 계약 유지)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from whymath_backend.l4.hint_content.models import Hint, HintReveals, SolutionStepRef
from whymath_backend.ops import g3_content_measures as g3
from whymath_backend.ops import hint_human_verdicts as hv

_T0 = "2026-10-27T23:00:00Z"
# 판정 시각은 과거로 고정하고, 측정 시각(`_NOW`)은 report가 명시 주입한다 — 미래 시각 검사가
# 실행 머신의 시계에 따라 흔들리지 않게 한다.
_JUDGED = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
_NOW = _JUDGED + timedelta(days=1)
_CLEAN_L1 = "기울기부터 구해 볼까요?"
_CLEAN_L2 = "접점을 먼저 정해 봐요"


# ──────────────────────────────────────────────────────────────────────
# 픽스처 빌더
# ──────────────────────────────────────────────────────────────────────
def _cu(slug: str, answer: str) -> dict[str, Any]:
    value = int(answer)
    return {
        "problem_id": str(uuid.uuid5(uuid.NAMESPACE_URL, slug)),
        "slug": slug,
        "question_text": f"문항 {slug}의 값을 구하시오.",
        "answer": answer,
        "achievement_standard_codes": ["[12미적Ⅰ-02-05]"],
        "license": "WHYMATH_GENERATED",
        "source_type": "자체생성",
        "generation_type": "FULLY_GENERATED",
        "authored_by": "llm:qwen3:30b-a3b",
        # 재계산 검산식(정답 재진술 아님) — 자동검증 축이 측정되도록
        "verify": {"conditions": f"answer == {value - 7} + 7", "answer_map": {"answer": answer}},
    }


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def _seat(root: Path, cus: list[dict[str, Any]]) -> None:
    seat = root / "r1-a"
    logs = [
        {
            "log_id": str(uuid.uuid4()),
            "cu_slug": c["slug"],
            "success": True,
            "model_name": "qwen3:30b-a3b",
            "prompt_version": "l3.equivalent@sha256:abc",
            "input_sha256": "f" * 64,
            "seed": 7,
            "generated_at": _T0,
        }
        for c in cus
    ]
    _write(seat / "cu.jsonl", cus)
    _write(seat / "cu.review.jsonl", [])
    _write(seat / "cu.genlog.jsonl", logs)


def _hint(
    problem_id: str, content: str, *, level: int, hint_id: str, verified: bool = True
) -> Hint:
    return Hint(
        hint_id=hint_id,
        solution_step_ref=SolutionStepRef(
            solution_path_id="p1", step_order=1, problem_id=uuid.UUID(problem_id)
        ),
        level=level,  # type: ignore[arg-type]
        reveals=HintReveals.from_flags(
            concept_names=level == 1, step_flow=level >= 2, partial_computation=level == 3
        ),
        content=content,
        verified=verified,
        gate_report={"answer_leakage": {"verdict": "clean"}},
    )


class Round:
    """회차 하나 — CU n개 × (L1·L2 clean 힌트). 추가 CU·힌트를 붙일 수 있다."""

    def __init__(self, root: Path, n_cu: int) -> None:
        self.root = root
        self.cus = [_cu(f"c{i:02d}", str(20 + i)) for i in range(n_cu)]
        self.hints: list[Hint] = []
        for i, cu in enumerate(self.cus):
            self.hints.append(_hint(cu["problem_id"], _CLEAN_L1, level=1, hint_id=f"h{i:02d}-l1"))
            self.hints.append(_hint(cu["problem_id"], _CLEAN_L2, level=2, hint_id=f"h{i:02d}-l2"))

    def add(self, cu: dict[str, Any], *hints: Hint) -> None:
        self.cus.append(cu)
        self.hints.extend(hints)

    def row(self, hint: Hint) -> dict[str, Any]:
        pid = str(hint.solution_step_ref.problem_id)
        return next(c for c in self.cus if c["problem_id"] == pid)

    def hint(self, hint_id: str) -> Hint:
        return next(h for h in self.hints if h.hint_id == hint_id)

    def write(self) -> Path:
        _seat(self.root, self.cus)
        path = self.root / "hints.jsonl"
        _write(path, [h.model_dump(mode="json") for h in self.hints])
        return path

    def manifest(self, size: int = 30, undecided: tuple[str, ...] = ()) -> hv.SampleManifest:
        population, errors = hv.sample_population(self.cus, self.hints)
        assert errors == []
        return hv.build_manifest(
            round_id="r1",
            population=population,
            machine_undecided_hint_ids=undecided,
            size=size,
            created_at=_JUDGED,
        )

    def verdict(
        self,
        hint_id: str,
        manifest: hv.SampleManifest | None,
        verdict: str = "not_leaked",
        **over: Any,
    ) -> hv.HintHumanVerdict:
        hint = self.hint(hint_id)
        data: dict[str, Any] = {
            "schema_version": "hint-human-verdict/v1",
            "hint_id": hint_id,
            "problem_id": hint.solution_step_ref.problem_id,
            "reviewer": "kiki",
            "judged_at": _JUDGED,
            "verdict": verdict,
            "rationale": "정답 수치·식이 드러나지 않음",
            "purpose": (
                manifest.purpose_of(hint_id)
                if manifest
                else hv.HintVerdictPurpose.MACHINE_UNDECIDED
            ),
            "sample_id": manifest.sample_id if manifest else "hvs-" + "0" * 16,
            "content_fingerprint": hv.hint_review_fingerprint(self.row(hint), hint),
            "review_session_id": uuid.UUID(int=1),
            "bypassed": False,
        }
        data.update(over)
        return hv.HintHumanVerdict(**data)

    def report(
        self,
        verdicts: list[hv.HintHumanVerdict] | None = None,
        manifest: hv.SampleManifest | None = None,
        **kw: Any,
    ) -> dict[str, Any]:
        _seat(self.root, self.cus)
        round_input = g3.discover_round(self.root, "r1")
        kw.setdefault("now", _NOW)
        return g3.build_report(
            round_input,
            self.hints,
            hint_inputs=1,
            hint_errors=[],
            human_verdicts=verdicts or [],
            manifest=manifest,
            **kw,
        )


def _all_not_leaked(rnd: Round, manifest: hv.SampleManifest) -> list[hv.HintHumanVerdict]:
    return [rnd.verdict(h, manifest) for h in manifest.sample_hint_ids]


# ──────────────────────────────────────────────────────────────────────
# ① 기록 계약
# ──────────────────────────────────────────────────────────────────────
class TestVerdictContract:
    def _valid(self, tmp_path: Path) -> dict[str, Any]:
        rnd = Round(tmp_path, 1)
        return json.loads(rnd.verdict("h00-l1", rnd.manifest()).model_dump_json())

    def _errors(self, tmp_path: Path, row: dict[str, Any]) -> list[str]:
        path = tmp_path / "v.jsonl"
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        verdicts, errors = hv.load_verdicts(path)
        assert verdicts == []
        return errors

    def test_valid_control_round_trips(self, tmp_path: Path) -> None:
        row = self._valid(tmp_path)
        path = tmp_path / "v.jsonl"
        hv.append_verdict(path, hv.HintHumanVerdict.model_validate(row))
        verdicts, errors = hv.load_verdicts(path)
        assert errors == [] and len(verdicts) == 1 and verdicts[0].hint_id == "h00-l1"

    @pytest.mark.parametrize(
        "field_name",
        [
            "hint_id",
            "problem_id",
            "reviewer",
            "judged_at",
            "verdict",
            "rationale",
            "purpose",
            "sample_id",
            "content_fingerprint",
            "bypassed",
        ],
    )
    def test_missing_required_field_is_rejected(self, tmp_path: Path, field_name: str) -> None:
        row = self._valid(tmp_path)
        del row[field_name]
        errors = self._errors(tmp_path, row)
        assert len(errors) == 1 and field_name in errors[0] and "ValidationError" in errors[0]

    @pytest.mark.parametrize(
        ("field_name", "value"),
        [
            ("rationale", "   "),
            ("rationale", ""),
            ("verdict", "maybe"),
            ("verdict", "clean"),
            ("reviewer", "김 철수"),  # 이름형(공백·한글) — 짧은 ID만
            ("judged_at", "2026-10-29T10:00:00+09:00"),  # UTC 아님
            ("purpose", "other"),
        ],
    )
    def test_bad_values_are_rejected(self, tmp_path: Path, field_name: str, value: str) -> None:
        row = self._valid(tmp_path)
        row[field_name] = value
        assert self._errors(tmp_path, row)

    def test_utc_offset_zero_in_other_spelling_is_accepted(self, tmp_path: Path) -> None:
        """대조군 — `+00:00`은 UTC다(Z와 같은 값)."""
        row = self._valid(tmp_path)
        row["judged_at"] = datetime(2026, 10, 29, tzinfo=timezone(timedelta(0))).isoformat()
        path = tmp_path / "v.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert hv.load_verdicts(path)[1] == []

    def test_broken_line_and_missing_file_are_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "v.jsonl"
        path.write_text('{"hint_id": \n', encoding="utf-8")
        assert any("JSONDecodeError" in e for e in hv.load_verdicts(path)[1])
        assert hv.load_verdicts(tmp_path / "absent.jsonl")[1]


# ──────────────────────────────────────────────────────────────────────
# ② 표본
# ──────────────────────────────────────────────────────────────────────
class TestSample:
    def test_same_seed_same_sample(self) -> None:
        ids = [f"h{i:03d}" for i in range(100)]
        assert hv.draw_sample(ids, 42, 30) == hv.draw_sample(list(reversed(ids)), 42, 30)
        assert hv.draw_sample(ids, 42, 30) != hv.draw_sample(ids, 43, 30)  # 대조군
        assert len(set(hv.draw_sample(ids, 42, 30))) == 30

    def test_population_below_size_is_census(self) -> None:
        assert sorted(hv.draw_sample(["b", "a", "c"], 1, 30)) == ["a", "b", "c"]

    def test_seed_is_derived_not_chosen(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 20)
        first, second = rnd.manifest(), rnd.manifest()
        assert first.seed == second.seed == hv.derive_seed("r1", first.population_digest)
        assert first.sample_hint_ids == second.sample_hint_ids
        assert len(first.sample_hint_ids) == 30 and len(first.population) == 40

    def test_population_is_verified_l1_l2_joined_only(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 2)
        cu = _cu("extra", "45")
        rnd.add(
            cu,
            _hint(cu["problem_id"], _CLEAN_L1, level=1, hint_id="x-unverified", verified=False),
            _hint(cu["problem_id"], "부분 계산을 보여요", level=3, hint_id="x-l3"),
        )
        stray = str(uuid.uuid5(uuid.NAMESPACE_URL, "not-in-round"))
        rnd.hints.append(_hint(stray, _CLEAN_L1, level=1, hint_id="x-stray"))
        population, _ = hv.sample_population(rnd.cus, rnd.hints)
        assert sorted(population) == ["h00-l1", "h00-l2", "h01-l1", "h01-l2"]

    @pytest.mark.parametrize("tamper", ["swap_sample", "seed", "population", "sample_id"])
    def test_tampered_manifest_is_rejected(self, tmp_path: Path, tamper: str) -> None:
        rnd = Round(tmp_path, 20)
        manifest = rnd.manifest()
        data = json.loads(manifest.model_dump_json())
        outside = sorted(set(manifest.population) - set(manifest.sample_hint_ids))[0]
        if tamper == "swap_sample":
            data["sample_hint_ids"][0] = outside
        elif tamper == "seed":
            data["seed"] += 1
        elif tamper == "population":
            data["population"][outside] = "sha256:" + "0" * 64
        else:
            data["sample_id"] = "hvs-" + "1" * 16
        path = tmp_path / "m.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded, errors = hv.load_manifest(path)
        assert loaded is None and errors

    def test_manifest_is_never_overwritten(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 2)
        path = tmp_path / "m.json"
        hv.write_manifest(path, rnd.manifest())
        with pytest.raises(FileExistsError):
            hv.write_manifest(path, rnd.manifest())
        assert hv.load_manifest(path)[1] == []


# ──────────────────────────────────────────────────────────────────────
# ③ 의미 축
# ──────────────────────────────────────────────────────────────────────
class TestSemanticAxis:
    def test_n29_is_not_measurable(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        rnd.hints[-1] = _hint(
            rnd.cus[-1]["problem_id"], _CLEAN_L2, level=2, hint_id="h14-l2", verified=False
        )  # 모집단 29
        manifest = rnd.manifest()
        report = rnd.report(_all_not_leaked(rnd, manifest), manifest)
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["k"], semantic["status"]) == (29, 0, "NOT_MEASURABLE")
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_n30_k0_passes_and_discloses_upper_bound(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        manifest = rnd.manifest()
        report = rnd.report(_all_not_leaked(rnd, manifest), manifest)
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["k"], semantic["status"]) == (30, 0, "PASS")
        assert semantic["wilson_upper_95"] == pytest.approx(0.0827, abs=1e-4)
        assert report["exit_code"] == g3.EXIT_PASS
        lines = g3.render_lines(report)
        assert "HINT_SEMANTIC_AXIS=PASS" in lines and "HINT_SEMANTIC_IN_EXIT=True" in lines
        assert "HINT_SEMANTIC_WILSON_UPPER_95=0.0827" in lines

    def test_one_leak_fails(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        manifest = rnd.manifest()
        verdicts = _all_not_leaked(rnd, manifest)
        verdicts[0] = rnd.verdict(manifest.sample_hint_ids[0], manifest, "leaked")
        report = rnd.report(verdicts, manifest)
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["k"], semantic["status"]) == (30, 1, "FAIL")
        assert report["exit_code"] == g3.EXIT_VIOLATION
        assert report["hint_leak"]["status"] == "PASS"  # 기계 축은 그대로(축 분리)

    def test_unjudged_sample_member_is_not_measurable(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 16)  # 모집단 32 → 표본 30
        manifest = rnd.manifest()
        verdicts = _all_not_leaked(rnd, manifest)[1:]  # 하나 건너뜀
        semantic = rnd.report(verdicts, manifest)["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["unjudged"], semantic["status"]) == (
            29,
            1,
            "NOT_MEASURABLE",
        )

    def test_unjudged_member_blocks_pass_even_when_n_reaches_30(self, tmp_path: Path) -> None:
        """n≥30이어도 표본 하나를 건너뛰면 측정 불가다 — n<30 절과 별개로 미판정 절이 막는다
        (위 n=29 픽스처는 두 절이 동시에 걸려 미판정 절을 단독으로 밟지 못한다)."""
        rnd = Round(tmp_path, 16)  # 모집단 32
        manifest = rnd.manifest(size=31)
        verdicts = _all_not_leaked(rnd, manifest)[1:]  # 31건 중 30건 판정
        semantic = rnd.report(verdicts, manifest)["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["unjudged"], semantic["status"]) == (
            30,
            1,
            "NOT_MEASURABLE",
        )

    def test_out_of_manifest_verdicts_are_counted_apart(self, tmp_path: Path) -> None:
        """사후 바꿔치기 반례 — 표본 하나를 빼고 표본 밖 힌트로 채워도 n은 29다."""
        rnd = Round(tmp_path, 16)
        manifest = rnd.manifest()
        outside = sorted(set(manifest.population) - set(manifest.sample_hint_ids))
        assert len(outside) == 2
        verdicts = _all_not_leaked(rnd, manifest)[1:]
        verdicts += [
            rnd.verdict(h, manifest, purpose=hv.HintVerdictPurpose.SEMANTIC_SAMPLE) for h in outside
        ]
        report = rnd.report(verdicts, manifest)
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["outside_manifest"], semantic["status"]) == (
            29,
            2,
            "NOT_MEASURABLE",
        )
        assert "HINT_SEMANTIC_OUTSIDE_MANIFEST=2" in g3.render_lines(report)

    def test_full_sample_plus_outside_control_passes_with_n30(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 16)
        manifest = rnd.manifest()
        outside = sorted(set(manifest.population) - set(manifest.sample_hint_ids))
        verdicts = _all_not_leaked(rnd, manifest) + [rnd.verdict(outside[0], manifest)]
        semantic = rnd.report(verdicts, manifest)["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["outside_manifest"], semantic["status"]) == (30, 1, "PASS")

    def test_confirmed_leak_outside_sample_is_not_hidden(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 16)
        manifest = rnd.manifest()
        outside = sorted(set(manifest.population) - set(manifest.sample_hint_ids))
        verdicts = _all_not_leaked(rnd, manifest) + [rnd.verdict(outside[0], manifest, "leaked")]
        report = rnd.report(verdicts, manifest)
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["k"], semantic["status"]) == (30, 0, "FAIL")
        assert semantic["human_leaks_outside_sample"] == [outside[0]]
        assert report["exit_code"] == g3.EXIT_VIOLATION

    def test_sample_id_mismatch_is_not_counted(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        manifest = rnd.manifest()
        verdicts = _all_not_leaked(rnd, manifest)
        verdicts[0] = rnd.verdict(
            manifest.sample_hint_ids[0], manifest, sample_id="hvs-" + "a" * 16
        )
        semantic = rnd.report(verdicts, manifest)["hint_leak"]["semantic"]
        assert (semantic["n"], semantic["sample_id_mismatch"], semantic["status"]) == (
            29,
            1,
            "NOT_MEASURABLE",
        )

    def test_manifest_from_other_population_is_not_measurable(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        manifest = rnd.manifest()
        verdicts = _all_not_leaked(rnd, manifest)
        rnd.hints[0] = _hint(rnd.cus[0]["problem_id"], "다른 본문", level=1, hint_id="h00-l1")
        report = rnd.report(verdicts, manifest)
        semantic = report["hint_leak"]["semantic"]
        assert semantic["status"] == "NOT_MEASURABLE" and semantic["errors"]
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_manifest_round_mismatch_is_not_measurable(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        population, _ = hv.sample_population(rnd.cus, rnd.hints)
        manifest = hv.build_manifest(
            round_id="r2", population=population, machine_undecided_hint_ids=(), created_at=_JUDGED
        )
        semantic = rnd.report([], manifest)["hint_leak"]["semantic"]
        assert any("회차" in e for e in semantic["errors"])


# ──────────────────────────────────────────────────────────────────────
# ④⑤ 기계 판정 불가 해소 · 어긋남 · 이력
# ──────────────────────────────────────────────────────────────────────
class TestMachineFallback:
    def _short_answer_round(self, tmp_path: Path) -> Round:
        """정답 `3`(한 자리) CU — 글자 축이 유보해 기계 판정 불가(None)가 된다."""
        rnd = Round(tmp_path, 1)
        cu = _cu("short", "3")
        rnd.add(
            cu,
            _hint(cu["problem_id"], "세 단계로 나눠 생각해 봐요", level=1, hint_id="s-l1"),
            _hint(cu["problem_id"], _CLEAN_L2, level=2, hint_id="s-l2"),
        )
        return rnd

    def test_unresolved_fallback_stays_undecided(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        hint = rnd.report()["hint_leak"]
        assert hint["undecided_l12"] >= 1
        assert (hint["status"], hint["undecided_l12_unresolved"]) == (
            "UNDECIDED",
            hint["undecided_l12"],
        )

    def _undecided_ids(self, rnd: Round) -> list[str]:
        hint = rnd.report()["hint_leak"]
        return [
            j["hint_id"]
            for entry in hint["per_cu"].values()
            for j in entry["judged"]
            if j["leaked"] is None and j["level"] in (1, 2)
        ]

    def test_human_not_leaked_resolves_undecided(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        report = rnd.report([rnd.verdict(h, None) for h in undecided])
        hint = report["hint_leak"]
        assert hint["human"]["resolved_clean"] == len(undecided)
        assert (hint["undecided_l12_unresolved"], hint["status"]) == (0, "PASS")
        assert report["exit_code"] == g3.EXIT_PASS
        assert "HINT_SEMANTIC_IN_EXIT=False" in g3.render_lines(report)  # 의미 축은 미측정 그대로

    def test_human_leaked_on_undecided_fails(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        verdicts = [rnd.verdict(undecided[0], None, "leaked")]
        verdicts += [rnd.verdict(h, None) for h in undecided[1:]]
        report = rnd.report(verdicts)
        assert (report["hint_leak"]["status"], report["exit_code"]) == ("FAIL", g3.EXIT_VIOLATION)
        assert report["hint_leak"]["human"]["resolved_leaked"] == 1

    def test_stale_verdict_does_not_resolve(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        verdicts = [
            rnd.verdict(h, None, content_fingerprint="sha256:" + "0" * 64) for h in undecided
        ]
        hint = rnd.report(verdicts)["hint_leak"]
        assert hint["human"]["stale"] == len(undecided)
        assert hint["status"] == "UNDECIDED"

    def test_bypassed_verdict_is_not_used(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        hint = rnd.report([rnd.verdict(h, None, bypassed=True) for h in undecided])["hint_leak"]
        assert (hint["human"]["bypassed"], hint["status"]) == (len(undecided), "UNDECIDED")

    def test_problem_id_mismatch_is_measurement_failure(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        bad = rnd.verdict(undecided[0], None, problem_id=uuid.uuid4())
        report = rnd.report([bad])
        assert report["hint_leak"]["human"]["errors"]
        assert report["exit_code"] == g3.EXIT_UNMEASURED

    def test_machine_leak_is_not_overturned_and_mismatch_is_kept(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 1)
        cu = _cu("leak", "-14")
        rnd.add(
            cu,
            _hint(cu["problem_id"], "y절편은 -14가 돼요", level=1, hint_id="m-l1"),
            _hint(cu["problem_id"], _CLEAN_L2, level=2, hint_id="m-l2"),
        )
        report = rnd.report([rnd.verdict("m-l1", None)])
        hint = report["hint_leak"]
        assert (hint["leaked_l12"], hint["status"]) == (1, "FAIL")
        assert report["exit_code"] == g3.EXIT_VIOLATION
        mismatches = hint["human"]["machine_mismatches"]
        assert len(mismatches) == 1
        assert mismatches[0]["kind"] == "machine_leak_vs_human_not_leaked"
        assert (mismatches[0]["machine_leaked"], mismatches[0]["human_verdict"]) == (
            True,
            "not_leaked",
        )
        assert "HINT_HUMAN_MACHINE_MISMATCH=1" in g3.render_lines(report)

    def test_rejudgement_appends_and_latest_wins(self, tmp_path: Path) -> None:
        rnd = self._short_answer_round(tmp_path)
        undecided = self._undecided_ids(rnd)
        path = tmp_path / "v.jsonl"
        first = rnd.verdict(undecided[0], None, "leaked")
        later = rnd.verdict(undecided[0], None, judged_at=_JUDGED + timedelta(hours=1))
        for verdict in (first, later, *(rnd.verdict(h, None) for h in undecided[1:])):
            hv.append_verdict(path, verdict)
        rows = path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == len(undecided) + 1  # 앞선 판정이 지워지지 않았다
        verdicts, errors = hv.load_verdicts(path)
        assert errors == []
        hint = rnd.report(verdicts)["hint_leak"]
        assert (hint["human"]["superseded"], hint["human"]["flipped"]) == (1, 1)
        assert (hint["status"], hint["human"]["resolved_clean"]) == ("PASS", len(undecided))


# ──────────────────────────────────────────────────────────────────────
# 재판정·판정자 불일치·미래 시각·우회 누설 (EOS-210 리뷰 P2-1·P3-1)
# ──────────────────────────────────────────────────────────────────────
class TestRejudgementIntegrity:
    _short = TestMachineFallback._short_answer_round
    _undecided = TestMachineFallback._undecided_ids

    def test_latest_is_append_order_not_judged_at(self, tmp_path: Path) -> None:
        """같은 판정자 — judged_at이 더 이른 행이라도 뒤에 append됐으면 그것이 최신이다."""
        rnd = self._short(tmp_path)
        target = self._undecided(rnd)[0]
        first = rnd.verdict(target, None, judged_at=_JUDGED + timedelta(hours=1))
        later_in_file = rnd.verdict(target, None, "leaked")  # judged_at은 더 이르다
        latest = hv.latest_verdicts([first, later_in_file])
        assert latest.latest[target].verdict is hv.HintVerdict.LEAKED
        assert latest.flipped == 1 and latest.disagreements == {}

    def test_other_reviewer_cannot_overwrite_a_leak(self, tmp_path: Path) -> None:
        """리뷰 실측 ⓐ — a의 누설을 b의 '아님'이 1시간 뒤 덮어 PASS가 나던 경로."""
        rnd = self._short(tmp_path)
        undecided = self._undecided(rnd)
        verdicts = [rnd.verdict(undecided[0], None, "leaked", reviewer="a")]
        verdicts.append(
            rnd.verdict(undecided[0], None, reviewer="b", judged_at=_JUDGED + timedelta(hours=1))
        )
        verdicts += [rnd.verdict(h, None, reviewer="a") for h in undecided[1:]]
        report = rnd.report(verdicts)
        hint = report["hint_leak"]
        assert (hint["status"], report["exit_code"]) == ("FAIL", g3.EXIT_VIOLATION)
        assert hint["human"]["reviewer_disagreements"] == {
            undecided[0]: {"a": "leaked", "b": "not_leaked"}
        }
        lines = g3.render_lines(report)
        assert "HINT_HUMAN_REVIEWER_DISAGREEMENT=1" in lines
        assert "판정자 불일치 1건(누설 우선)" in hint["reason"]

    def test_reviewer_disagreement_in_sample_fails_semantic_axis(self, tmp_path: Path) -> None:
        rnd = Round(tmp_path, 15)
        manifest = rnd.manifest()
        verdicts = _all_not_leaked(rnd, manifest)
        verdicts.insert(
            0, rnd.verdict(manifest.sample_hint_ids[0], manifest, "leaked", reviewer="a")
        )
        semantic = rnd.report(verdicts, manifest)["hint_leak"]["semantic"]
        assert (semantic["k"], semantic["status"], semantic["reviewer_disagreements"]) == (
            1,
            "FAIL",
            1,
        )

    def test_agreeing_reviewers_are_not_a_disagreement(self, tmp_path: Path) -> None:
        """대조군 — 두 판정자가 같은 판정이면 불일치가 아니다."""
        rnd = self._short(tmp_path)
        undecided = self._undecided(rnd)
        verdicts = [rnd.verdict(h, None, reviewer=r) for h in undecided for r in ("a", "b")]
        hint = rnd.report(verdicts)["hint_leak"]
        assert hint["human"]["reviewer_disagreements"] == {} and hint["status"] == "PASS"

    def test_same_reviewer_rejudgement_retracts_and_is_disclosed(self, tmp_path: Path) -> None:
        """같은 판정자는 자기 누설을 거둘 수 있다 — 단 뒤집힘이 사유·요약에 드러난다."""
        rnd = self._short(tmp_path)
        undecided = self._undecided(rnd)
        verdicts = [rnd.verdict(undecided[0], None, "leaked")]
        verdicts += [rnd.verdict(h, None) for h in undecided]
        report = rnd.report(verdicts)
        hint = report["hint_leak"]
        assert (hint["status"], report["exit_code"]) == ("PASS", g3.EXIT_PASS)
        assert hint["human"]["flipped"] == 1
        assert "같은 판정자 재판정 뒤집힘 1건" in hint["reason"]
        assert "HINT_HUMAN_FLIPPED=1" in g3.render_lines(report)

    def test_future_dated_row_is_input_error(self, tmp_path: Path) -> None:
        """리뷰 실측 ⓑ — +10년 '아님' 행이 그 뒤 실제 누설 재판정을 영구히 이기던 경로."""
        rnd = self._short(tmp_path)
        undecided = self._undecided(rnd)
        future = rnd.verdict(undecided[0], None, judged_at=_NOW + timedelta(days=3650))
        verdicts = [future, rnd.verdict(undecided[0], None, "leaked")]
        verdicts += [rnd.verdict(h, None) for h in undecided[1:]]
        report = rnd.report(verdicts)
        assert report["exit_code"] == g3.EXIT_UNMEASURED
        assert any("미래" in e for e in report["hint_leak"]["human"]["errors"])

    def test_within_skew_is_accepted(self, tmp_path: Path) -> None:
        """대조군 — 허용 오차(5분) 안의 시계 차는 오류가 아니다."""
        rnd = self._short(tmp_path)
        undecided = self._undecided(rnd)
        verdicts = [rnd.verdict(h, None, judged_at=_NOW + timedelta(minutes=4)) for h in undecided]
        assert rnd.report(verdicts)["hint_leak"]["human"]["errors"] == []

    def test_bypassed_leak_is_disclosed_and_fails(self, tmp_path: Path) -> None:
        """P3-1 — 우회 판정은 통과를 돕지 못하지만, 누설 신호는 숨기지 않는다."""
        rnd = Round(tmp_path, 15)
        report = rnd.report([rnd.verdict("h03-l1", None, "leaked", bypassed=True)])
        semantic = report["hint_leak"]["semantic"]
        assert semantic["bypassed_leaks"] == ["h03-l1"] and semantic["status"] == "FAIL"
        assert report["exit_code"] == g3.EXIT_VIOLATION
        assert "HINT_HUMAN_BYPASSED_LEAKED=1" in g3.render_lines(report)

    def test_bypassed_not_leaked_has_no_effect(self, tmp_path: Path) -> None:
        """대조군 — 우회 '아님'은 아무것도 바꾸지 않는다(PASS 근거로 쓰이지 않는다)."""
        rnd = Round(tmp_path, 15)
        report = rnd.report([rnd.verdict("h03-l1", None, bypassed=True)])
        semantic = report["hint_leak"]["semantic"]
        assert (semantic["bypassed_leaks"], semantic["status"]) == ([], "NOT_MEASURED")
        assert report["exit_code"] == g3.EXIT_PASS


# ──────────────────────────────────────────────────────────────────────
# ⑥ CLI 종료 코드
# ──────────────────────────────────────────────────────────────────────
class TestCli:
    def _args(self, rnd: Round, hints_path: Path, *extra: str) -> list[str]:
        return [
            "--round",
            "r1",
            "--runs-root",
            str(rnd.root),
            "--hints-jsonl",
            str(hints_path),
            *extra,
        ]

    def test_corrupt_verdict_file_is_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rnd = Round(tmp_path, 15)
        hints_path = rnd.write()
        verdicts = tmp_path / "v.jsonl"
        manifest = rnd.manifest()
        for v in _all_not_leaked(rnd, manifest):
            hv.append_verdict(verdicts, v)
        with verdicts.open("a", encoding="utf-8") as handle:
            handle.write('{"hint_id": "h00-l1", "verdict": "leaked"}\n')  # 필수 필드 누락
        code = g3.main(self._args(rnd, hints_path, "--hint-verdicts", str(verdicts)))
        lines = capsys.readouterr().out.splitlines()
        assert code == g3.EXIT_UNMEASURED
        assert "HINT_HUMAN_INPUT_ERRORS=1" in lines

    def test_corrupt_verdict_file_is_exit_2_even_when_a_fail_was_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """손상 파일에서 *읽힌* 행이 FAIL을 만들어도 종료 코드는 측정 실패(2)다 — 못 읽은 행 위에서
        낸 판정은 믿지 않는다(위 손상 테스트는 경쟁하는 FAIL이 없어 이 절을 단독으로 밟지 못한다)."""
        rnd = Round(tmp_path, 15)
        hints_path = rnd.write()
        verdicts = tmp_path / "v.jsonl"
        hv.append_verdict(verdicts, rnd.verdict("h00-l1", None, "leaked"))  # 기계 clean · 사람 누설
        with verdicts.open("a", encoding="utf-8") as handle:
            handle.write("{broken\n")
        code = g3.main(self._args(rnd, hints_path, "--hint-verdicts", str(verdicts)))
        lines = capsys.readouterr().out.splitlines()
        assert "HINT_SEMANTIC_AXIS=FAIL" in lines  # 읽힌 행은 FAIL을 만들었다
        assert code == g3.EXIT_UNMEASURED

    def test_semantic_pass_via_cli(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rnd = Round(tmp_path, 15)
        hints_path = rnd.write()
        manifest = rnd.manifest()
        manifest_path = tmp_path / "r1-review" / "hint_sample_manifest.json"
        hv.write_manifest(manifest_path, manifest)
        verdicts = tmp_path / "r1-review" / "hint_verdicts.jsonl"
        for v in _all_not_leaked(rnd, manifest):
            hv.append_verdict(verdicts, v)
        code = g3.main(
            self._args(
                rnd,
                hints_path,
                "--hint-verdicts",
                str(verdicts),
                "--hint-sample-manifest",
                str(manifest_path),
            )
        )
        lines = capsys.readouterr().out.splitlines()
        assert code == g3.EXIT_PASS
        assert {"HINT_SEMANTIC_AXIS=PASS", "HINT_SEMANTIC_N=30", "HINT_SEMANTIC_K=0"} <= set(lines)

    def test_requested_but_missing_manifest_is_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rnd = Round(tmp_path, 15)
        hints_path = rnd.write()
        code = g3.main(
            self._args(rnd, hints_path, "--hint-sample-manifest", str(tmp_path / "absent.json"))
        )
        lines = capsys.readouterr().out.splitlines()
        assert code == g3.EXIT_UNMEASURED
        assert "HINT_SEMANTIC_AXIS=NOT_MEASURABLE" in lines

    def test_without_manifest_semantic_stays_out_of_exit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """EOS-207 계약 유지 — 매니페스트를 안 주면 기계 축만으로 exit 0이 날 수 있되, 의미 축이
        미측정이라는 사실이 같은 출력에 함께 실린다."""
        rnd = Round(tmp_path, 15)
        code = g3.main(self._args(rnd, rnd.write()))
        lines = capsys.readouterr().out.splitlines()
        assert code == g3.EXIT_PASS
        assert {"HINT_SEMANTIC_AXIS=NOT_MEASURED", "HINT_SEMANTIC_IN_EXIT=False"} <= set(lines)
