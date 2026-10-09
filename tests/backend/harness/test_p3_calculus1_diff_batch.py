"""Phase 3 미적분Ⅰ 미분 문항 은행 배치 테스트 — P3-03(결정론·LLM 0·hermetic).

검증 축
-------
① 배치가 등록부 전체를 게이트(Tier1 SymPy) 통과로 적재한다(밴드 = 개념 × 슬롯 · 수율 100%).
② 산출 JSONL의 전 레코드가 `machine_sampled`·`is_published=False`이고 **`review_status` 키가 없다**.
③ 재실행 바이트 결정론 · `--check` 드리프트 검출(변조·파일 부재가 둘 다 exit 1).
④ **저작 결함 변별력** — 정답을 틀리게 만든 생성기는 게이트에서 거부되고 CLI가 exit 1을 낸다.
⑤ **승인 기록 금지 변별력** — 생성기가 `review_status`를 쓰면 배치가 RuntimeError로 멈춘다.
⑥ 등록부 확장성 — 새 개념 클래스를 튜플에 넣기만 하면 배치가 그대로 돈다.
⑦ 정답 SymPy 불일치를 주입한 JSONL을 `corpus_reverify`가 exit 1로 거부한다(대조군 exit 0 포함).
⑧ 사이드카(`_provenance.json`)가 `build_provenance`와 일치하고 저장소 은행과 같다.
"""

from __future__ import annotations

import functools
import json
import shutil
from pathlib import Path
from typing import ClassVar

import pytest

from whymath_backend.harness import corpus_reverify
from whymath_backend.harness import p3_calculus1_diff_batch as batch
from whymath_backend.l3.equivalent.generator import CandidateProblem
from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import SLOT_IDS, P3DiffSlotGenerator
from whymath_backend.l3.verification_tier import VerificationTier

# PB-13: 생성기·배치 회귀는 corpus-authoring 잡이 돌린다(비활성화가 아니다).
pytestmark = pytest.mark.corpus_authoring

_REPO_BANK = Path(__file__).resolve().parents[3] / "data" / "corpus" / batch.CORPUS_DIR_NAME


@functools.cache
def _expected_total() -> int:
    """등록부 전 생성기 × 슬롯의 문항 수 — 테스트가 처음 부를 때 한 번만 센다.

    모듈 최상단 상수로 두면 **수집(collection) 때** 생성기 전부를 돌린다(은행 504건 생성 ≈ 2분).
    이 모듈은 `corpus_authoring` 표지라 backend 잡에서 실행되지 않지만, 표지에 의한 제외는 수집이
    끝난 뒤에 일어나므로 임포트 비용은 그대로 남는다 — backend 잡의 xdist 워커 4개가 각자
    커버리지 추적 아래 이 계산을 반복해 수집이 약 8분 늘었고 잡이 35분 상한에 걸렸다(2026-10-09
    실측: 수집 15초 → 134초, CI 첫 출력까지 72초 → 555초).
    """
    return sum(len(g.items(s)) for g in batch.GENERATORS for s in SLOT_IDS)


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_batch_stores_every_item_through_the_gate(tmp_path: Path) -> None:
    out = tmp_path / "problems.jsonl"
    report = batch.run_p3_calculus1_diff_batch(out_path=out)

    assert report.total_stored == report.total_requested == _expected_total()
    assert report.written == _expected_total()
    assert len(report.bands) == len(batch.GENERATORS) * len(SLOT_IDS)
    assert all(not b.failure_reasons for b in report.bands), [
        b.failure_reasons for b in report.bands
    ]
    assert {b.name for b in report.bands} == {
        f"{g.standard_code}:{slot}" for g in batch.GENERATORS for slot in SLOT_IDS
    }

    records = _records(out)
    assert len(records) == _expected_total()
    assert len({r["problem_id"] for r in records}) == len(records)
    assert len({r["slug"] for r in records}) == len(records)
    for record in records:
        assert record["verify"]["verification_tier"] == VerificationTier.MACHINE_SAMPLED.value  # type: ignore[index]
        assert record["source_type"] == "자체생성"
        assert record["license"] == "WHYMATH_GENERATED"
        assert record["is_published"] is False
        assert "review_status" not in record  # 승인은 감사 표본 경로의 몫
        assert record["problem_type_codes"]
        assert len(record["concepts"]) == 1  # type: ignore[arg-type]


def test_batch_is_byte_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    batch.run_p3_calculus1_diff_batch(out_path=first)
    batch.run_p3_calculus1_diff_batch(out_path=second)
    assert first.read_bytes() == second.read_bytes()


def test_committed_bank_is_in_sync_with_the_generators() -> None:
    """저장소에 커밋된 은행 == 지금 생성기가 내는 결과(드리프트 0)."""
    assert batch.main(["--check"]) == 0


def test_check_detects_tampering_and_missing_files(tmp_path: Path) -> None:
    """**변별력** — `--check`가 정상에서만 0이고, 변조·부재에서는 1이다."""
    good = tmp_path / "good"
    shutil.copytree(_REPO_BANK, good)
    assert batch.main(["--check", "--out-dir", str(good)]) == 0

    tampered = tmp_path / "tampered"
    shutil.copytree(_REPO_BANK, tampered)
    target = tampered / "problems.jsonl"
    data = bytearray(target.read_bytes())
    data[len(data) // 2] ^= 0x01  # 1비트 변조
    target.write_bytes(bytes(data))
    assert batch.main(["--check", "--out-dir", str(tampered)]) == 1

    tampered_sidecar = tmp_path / "tampered_sidecar"
    shutil.copytree(_REPO_BANK, tampered_sidecar)
    sidecar = tampered_sidecar / "_provenance.json"
    sidecar.write_text(sidecar.read_text(encoding="utf-8").replace("2026-10-06", "2026-10-07"))
    assert batch.main(["--check", "--out-dir", str(tampered_sidecar)]) == 1

    missing = tmp_path / "missing"
    shutil.copytree(_REPO_BANK, missing)
    (missing / "_provenance.json").unlink()
    assert batch.main(["--check", "--out-dir", str(missing)]) == 1


def test_cli_writes_bank_and_sidecar(tmp_path: Path) -> None:
    out_dir = tmp_path / "bank"
    assert batch.main(["--out-dir", str(out_dir)]) == 0
    assert (out_dir / "problems.jsonl").read_bytes() == (_REPO_BANK / "problems.jsonl").read_bytes()
    assert (out_dir / "_provenance.json").read_bytes() == (
        _REPO_BANK / "_provenance.json"
    ).read_bytes()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    out_dir = tmp_path / "bank"
    assert batch.main(["--out-dir", str(out_dir), "--dry-run"]) == 0
    assert not out_dir.exists()


def test_sidecar_matches_build_provenance_and_the_bank() -> None:
    sidecar = json.loads((_REPO_BANK / "_provenance.json").read_text(encoding="utf-8"))
    assert sidecar == batch.build_provenance()
    assert sidecar["pool"] == "whymath-original"
    records = _records(_REPO_BANK / "problems.jsonl")
    assert sidecar["record_count"] == len(records)
    for code, info in sidecar["concepts"].items():
        in_bank = [r for r in records if r["achievement_standard_codes"] == [code]]
        assert info["records"] == len(in_bank)
        for slot, count in info["slots"].items():
            assert count == sum(1 for r in in_bank if r["tags"] == [f"p3-slot:{slot}"])
    assert '"review_status"' not in (_REPO_BANK / "problems.jsonl").read_text(encoding="utf-8")


def test_gate_rejects_authoring_defect_and_cli_would_fail(tmp_path: Path) -> None:
    """**변별력 실측** — 검산 재료를 틀리게 만든 생성기는 거부되고 적재 0이다."""

    class Broken(P3DiffPowerDerivativeGenerator):
        def _assemble(self, spec, item):  # type: ignore[no-untyped-def]
            candidate = super()._assemble(spec, item)
            key = sorted(candidate.answer_map)[-1]
            wrong = {**candidate.answer_map, key: f"({candidate.answer_map[key]}) + 1"}
            return candidate.model_copy(update={"answer_map": wrong})

    report = batch.run_p3_calculus1_diff_batch(generators=(Broken,), out_path=tmp_path / "p.jsonl")
    assert report.total_stored == 0
    assert report.total_requested == sum(len(Broken.items(s)) for s in SLOT_IDS)
    assert all(b.stored == 0 and b.failure_reasons for b in report.bands)
    assert any("Tier1" in r for b in report.bands for r in b.failure_reasons)


def test_batch_refuses_to_write_review_status(tmp_path: Path) -> None:
    """**변별력 실측** — 생성기가 승인을 쓰면(`review_status`) 배치가 멈춘다. 정상 생성기는 통과."""
    batch.run_p3_calculus1_diff_batch(
        generators=(P3DiffPowerDerivativeGenerator,), out_path=tmp_path / "ok.jsonl"
    )  # 대조군 — 예외 없음

    class Approving(P3DiffPowerDerivativeGenerator):
        def _assemble(self, spec, item):  # type: ignore[no-untyped-def]
            candidate: CandidateProblem = super()._assemble(spec, item)
            approved = candidate.problem.model_copy(update={"review_status": "approved"})
            return candidate.model_copy(update={"problem": approved})

    with pytest.raises(RuntimeError, match="review_status"):
        batch.run_p3_calculus1_diff_batch(generators=(Approving,), out_path=tmp_path / "bad.jsonl")


def test_registry_is_extensible_by_adding_a_class(tmp_path: Path) -> None:
    """등록부에 클래스 1개만 두면 배치·사이드카가 그대로 돈다(다른 에이전트의 추가 절차)."""

    class Extra(P3DiffPowerDerivativeGenerator):
        standard_code: ClassVar[str] = "[12미적Ⅰ-02-99]"  # 가짜 개념 — 사이드카 키로만 쓴다
        slug_prefix: ClassVar[str] = "wm-test-extra"

    registry: tuple[type[P3DiffSlotGenerator], ...] = (Extra,)
    out = tmp_path / "p.jsonl"
    report = batch.run_p3_calculus1_diff_batch(generators=registry, out_path=out)
    extra_total = sum(len(Extra.items(s)) for s in SLOT_IDS)
    assert report.total_stored == report.total_requested == extra_total
    assert {r["achievement_standard_codes"][0] for r in _records(out)} == {"[12미적Ⅰ-02-99]"}  # type: ignore[index]
    provenance = batch.build_provenance(registry)
    assert list(provenance["concepts"]) == ["[12미적Ⅰ-02-99]"]
    assert provenance["record_count"] == extra_total


def test_reverify_passes_the_bank_and_rejects_an_injected_answer_mismatch(tmp_path: Path) -> None:
    """정답 SymPy 불일치를 주입하면 `corpus_reverify`가 exit 1 — 대조군은 skip 0·실패 0으로 exit 0."""
    clean = tmp_path / "clean.jsonl"
    shutil.copyfile(_REPO_BANK / "problems.jsonl", clean)
    records = corpus_reverify._iter_records(clean.read_text(encoding="utf-8"))
    report = corpus_reverify.reverify_corpus(records, use_fuzz=False)
    assert (report.passed, report.failed, report.skipped) == (_expected_total(), 0, 0)
    assert corpus_reverify.main([str(clean)]) == 0

    broken = tmp_path / "broken.jsonl"
    rows = _records(clean)
    original = json.dumps(rows[7], ensure_ascii=False)
    amap = rows[7]["verify"]["answer_map"]  # type: ignore[index]
    key = sorted(amap)[-1]
    amap[key] = f"({amap[key]}) + 1"
    assert json.dumps(rows[7], ensure_ascii=False) != original  # 주입이 실제로 적용됐다
    broken.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    assert corpus_reverify.main([str(broken)]) == 1
