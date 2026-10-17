"""코퍼스 저작 서명 백필(PB-17 ②·④) — 도출 규칙·바이트 계약·멱등·실 코퍼스 전수 가드.

검증 축:
  ① 도출은 `_provenance.json` 사실에서만 — LLM 개입·사람 저작·근거 없음은 deterministic 으로
     단정하지 않고 **미백필·사유**로 보고한다(변별 대조군 포함).
  ② 바이트·건수 계약 — 서명 키 한 개만 추가·줄 수 불변·`_record_to_json` 순서와 일치·멱등.
  ③ 실 코퍼스 전수 가드 — `data/corpus/problem_bank_*` 전 레코드가 서명을 갖거나(`deterministic:`)
     '미백필 목록'에 사유와 함께 고정돼 있다. 새 코퍼스를 서명 없이 추가하면 RED.
CI 배선: 이 파일은 `corpus_authoring` 마커가 없어 backend 잡이 모든 PR 에서 돌린다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from whymath_backend.harness.problem_corpus_author_backfill import (
    derive_corpus_author,
    main,
    registered_deterministic_generators,
    run_author_backfill,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
_HARNESS_DIR = _REPO_ROOT / "src" / "backend" / "whymath_backend" / "harness"

# 의도적 미백필 — 사유가 있는 닫힌 목록. 늘리려면 사유를 적고 이 목록을 고쳐야 한다.
_EXPECTED_UNBACKFILLED = {
    "problem_bank_rephrased_v0": "LLM",
    "problem_bank_v1": "사람 저작",
}

_REGISTERED = registered_deterministic_generators()


def _decide(
    method: str | None, *, cli: str = "", dir_name: str = "problem_bank_x_v0", harness=None
):
    provenance: dict[str, object] = {}
    if method is not None:
        provenance["generation_method"] = method
    if cli:
        provenance["generation_cli"] = cli
    return derive_corpus_author(
        provenance,
        corpus_dir_name=dir_name,
        registered=_REGISTERED,
        harness_dir=harness if harness is not None else _HARNESS_DIR,
    )


# ── ① 도출 규칙 ─────────────────────────────────────────────────────────
def test_named_registered_generator_is_derived() -> None:
    d = _decide(
        "결정론 스켈레톤 생성기(LLM 0) — l3/equivalent/binomial_distribution_skeleton_generator.py"
    )
    assert d.signature == "deterministic:binomial_distribution_skeleton_generator"


def test_llm_involvement_is_never_asserted_deterministic() -> None:
    """대조군 핵심 — 결정론 생성기 파일을 지목해도 LLM 개입이 적혀 있으면 단정하지 않는다."""
    d = _decide(
        "generated_v0 기반 LLM 발문 다양화 — l3/equivalent/binomial_distribution_skeleton_generator.py"
    )
    assert d.signature is None and "LLM" in d.reason


def test_hand_authored_is_not_a_deterministic_generator() -> None:
    d = _decide("hand-authored seed (사람 저작 시드)")
    assert d.signature is None and "사람 저작" in d.reason


@pytest.mark.parametrize("method", [None, "", "   "])
def test_missing_generation_method_is_unbackfilled(method: str | None) -> None:
    assert _decide(method).signature is None


def test_named_but_unregistered_generator_is_unbackfilled() -> None:
    """지목된 파일이 등록부에 없으면(데코레이터 미부착·오타) 서명하지 않는다."""
    d = _decide("결정론(LLM 0) — l3/equivalent/not_a_real_skeleton_generator.py")
    assert d.signature is None and "등록부" in d.reason


def test_glob_without_llm_zero_statement_is_unbackfilled() -> None:
    d = _decide("스켈레톤 생성기 — l3/equivalent/*_skeleton_generator.py")
    assert d.signature is None


def test_glob_with_llm_zero_falls_back_to_named_batch_module() -> None:
    d = _decide(
        "결정론 스켈레톤 생성기 15밴드(LLM 0) — l3/equivalent/*_skeleton_generator.py를 "
        "harness/problem_corpus_batch.py가 오케스트레이션"
    )
    assert d.signature is not None and d.signature.startswith("deterministic:")


def test_untraced_generator_uses_corpus_dir_name_in_batch_code() -> None:
    """'생성기 파일명 역추적 실패' 코퍼스 — 코드의 CORPUS_DIR_NAME 으로 배치 모듈을 실측한다."""
    d = _decide(
        "결정론 스켈레톤 생성기(LLM 0) — l3/equivalent/ 계열(생성기 파일명 자동 역추적 실패)",
        dir_name="problem_bank_discrete_ev_v0",
    )
    assert d.signature == "deterministic:discrete_expected_value_skeleton_generator"


def test_untraced_without_any_evidence_is_unbackfilled() -> None:
    d = _decide(
        "결정론 스켈레톤 생성기(LLM 0) — l3/equivalent/ 계열(역추적 실패)",
        dir_name="problem_bank_no_such_batch_v0",
    )
    assert d.signature is None and "역추적" in d.reason


# ── ② 바이트·건수 계약 (합성 코퍼스) ────────────────────────────────────
def _record(slug: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": slug,
        "license": "WHYMATH_GENERATED",
        "generation_type": "FULLY_GENERATED",
        "concepts": [],
        "verify": {"conditions": "x = y"},
    }
    base.update(extra)
    return base


def _write_dir(root: Path, name: str, method: str | None, rows: list[dict[str, object]]) -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    if method is not None:
        (directory / "_provenance.json").write_text(
            json.dumps({"generation_method": method}, ensure_ascii=False), encoding="utf-8"
        )
    path = directory / "problems.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    return path


_DET = "결정론(LLM 0) — l3/equivalent/binomial_distribution_skeleton_generator.py"


def test_backfill_adds_only_the_signature_and_is_idempotent(tmp_path: Path) -> None:
    rows = [_record("a"), _record("b", original_source="x")]
    path = _write_dir(tmp_path, "problem_bank_det_v0", _DET, rows)
    before = path.read_text(encoding="utf-8")

    report = run_author_backfill(tmp_path)
    after = path.read_text(encoding="utf-8")

    sig = "deterministic:binomial_distribution_skeleton_generator"
    assert report.total_stamped == 2 and report.total_records == 2
    out = [json.loads(x) for x in after.splitlines()]
    assert [r["authored_by"] for r in out] == [sig, sig]
    for old, new in zip(rows, out, strict=True):
        assert {k: v for k, v in new.items() if k != "authored_by"} == old
    # 키 위치 = _record_to_json 순서: generation_type 뒤(original_source 가 있으면 그 뒤)·concepts 앞.
    keys0 = list(out[0])
    assert keys0.index("authored_by") == keys0.index("generation_type") + 1
    keys1 = list(out[1])
    assert keys1.index("authored_by") == keys1.index("original_source") + 1
    assert len(after) - len(before) == 2 * len(f'"authored_by": "{sig}", ')
    # 멱등: 재실행은 변경 0건·바이트 동일.
    again = run_author_backfill(tmp_path)
    assert again.total_stamped == 0 and path.read_text(encoding="utf-8") == after


def test_recorded_signature_is_never_overwritten(tmp_path: Path) -> None:
    """기록이 있는 레코드(LLM 저작)는 건드리지 않는다 — 결정론 디렉터리 안에 섞여 있어도."""
    rows = [_record("a", authored_by="llm:some-model"), _record("b")]
    path = _write_dir(tmp_path, "problem_bank_det_v0", _DET, rows)

    report = run_author_backfill(tmp_path)

    out = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert out[0]["authored_by"] == "llm:some-model"
    assert out[1]["authored_by"].startswith("deterministic:")
    assert report.dirs[0].already_signed == 1 and report.dirs[0].stamped == 1


def test_non_fully_generated_record_is_skipped_and_counted(tmp_path: Path) -> None:
    rows = [_record("a", generation_type="AI_ASSISTED"), _record("b")]
    path = _write_dir(tmp_path, "problem_bank_det_v0", _DET, rows)
    report = run_author_backfill(tmp_path)
    out = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert "authored_by" not in out[0] and "authored_by" in out[1]
    assert report.dirs[0].skipped_not_fully_generated == 1


def test_llm_directory_is_untouched_and_reported_with_reason(tmp_path: Path) -> None:
    llm = _write_dir(tmp_path, "problem_bank_llm_v0", "LLM 발문 다양화 — 재작성", [_record("a")])
    det = _write_dir(tmp_path, "problem_bank_det_v0", _DET, [_record("b")])
    llm_before = llm.read_bytes()

    report = run_author_backfill(tmp_path)

    assert llm.read_bytes() == llm_before, "LLM 디렉터리는 한 바이트도 바뀌면 안 된다"
    assert [d.name for d in report.unbackfilled] == ["problem_bank_llm_v0"]
    assert "LLM" in report.unbackfilled[0].unbackfilled_reason
    assert "authored_by" in det.read_text(encoding="utf-8")


def test_roundtrip_mismatch_refuses_to_rewrite(tmp_path: Path) -> None:
    """서식이 `json.dumps` 와 다른 줄(들여쓰기 등)은 diff 가 부풀므로 쓰지 않고 실패한다."""
    path = _write_dir(tmp_path, "problem_bank_det_v0", _DET, [_record("a")])
    path.write_text('{"slug":"a","generation_type":"FULLY_GENERATED"}\n', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="라운드트립"):
        run_author_backfill(tmp_path)
    assert path.read_bytes() == before


def test_scan_zero_is_a_failure(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_author_backfill(tmp_path)


def test_check_mode_exit_codes_and_no_write(tmp_path: Path) -> None:
    path = _write_dir(tmp_path, "problem_bank_det_v0", _DET, [_record("a")])
    before = path.read_bytes()
    assert main(["--root", str(tmp_path), "--check"]) == 1
    assert path.read_bytes() == before, "--check 는 쓰지 않는다"
    assert main(["--root", str(tmp_path), "--dry-run"]) == 0
    assert path.read_bytes() == before
    assert main(["--root", str(tmp_path)]) == 0
    assert main(["--root", str(tmp_path), "--check"]) == 0


# ── ③ 실 코퍼스 전수 가드 ───────────────────────────────────────────────
def _real_dirs() -> list[Path]:
    return sorted(_CORPUS_ROOT.glob("problem_bank_*/problems.jsonl"))


def test_real_corpus_scan_is_not_vacuous() -> None:
    assert len(_real_dirs()) >= 30


def test_real_corpus_every_record_signed_or_in_the_unbackfilled_list() -> None:
    """서명 없는 레코드 0건 — 예외는 사유가 적힌 닫힌 목록(`_EXPECTED_UNBACKFILLED`)뿐이다."""
    unsigned: dict[str, int] = {}
    total = 0
    for path in _real_dirs():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            record = json.loads(line)
            signature = record.get("authored_by")
            if signature is None:
                unsigned[path.parent.name] = unsigned.get(path.parent.name, 0) + 1
            else:
                assert signature.startswith(("deterministic:", "llm:")), (
                    path.parent.name,
                    signature,
                )
    assert total >= 14_000
    assert set(unsigned) == set(
        _EXPECTED_UNBACKFILLED
    ), f"서명 없는 디렉터리가 예상 목록과 다르다: {sorted(unsigned)}"


def test_real_corpus_backfill_check_reports_zero_pending() -> None:
    """드리프트 가드 — 서명 가능한데 빠진 레코드 0건(재실행 변경 0건 = 멱등의 실데이터 증거)."""
    report = run_author_backfill(_CORPUS_ROOT, write=False)
    assert report.total_stamped == 0
    assert {d.name for d in report.unbackfilled} == set(_EXPECTED_UNBACKFILLED)
    for d in report.unbackfilled:
        assert _EXPECTED_UNBACKFILLED[d.name] in d.unbackfilled_reason


def test_real_corpus_signature_names_a_registered_generator_or_batch() -> None:
    """서명 이름이 실재하는 모듈을 가리킨다 — 지어낸 이름(오타·삭제된 생성기) 차단."""
    batch_stems = {p.stem for p in _HARNESS_DIR.glob("*.py")}
    for path in _real_dirs():
        for line in path.read_text(encoding="utf-8").splitlines()[:1]:
            signature = json.loads(line).get("authored_by")
            if signature is None:
                continue
            name = signature.removeprefix("deterministic:")
            assert name in _REGISTERED or name in batch_stems, (path.parent.name, name)
