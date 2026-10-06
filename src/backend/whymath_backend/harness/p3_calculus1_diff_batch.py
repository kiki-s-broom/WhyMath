"""Phase 3 미적분Ⅰ '미분' 대단원 문항 은행 배치 — P3-03(순수 결정론·LLM 0).

`data/corpus/phase3_scope_v1/scope_spec.yaml`의 핵심 개념 중 승인 문항이 0건이던 개념들을 채우는
**개념별 생성기 등록부**(`GENERATORS`)를 돌려 은행 `data/corpus/problem_bank_p3_calculus1_diff_v0/`
(`problems.jsonl` + `_provenance.json`)를 결정론적으로 재생성한다. 같은 입력이면 두 파일 모두
바이트가 같다(`--check`가 그 드리프트를 잡는다).

개념을 추가하는 법(다른 에이전트용 3줄)
------------------------------------
1. `l3/equivalent/p3_diff_<개념>_skeleton_generator.py`에 `P3DiffSlotGenerator` 하위 클래스를 쓴다
   (`standard_code`·`concept_src_id`·`unit_code`·`slug_prefix`·`slot_difficulty`·`_slot_items`).
2. 이 파일의 `GENERATORS` 튜플에 그 클래스를 한 줄 추가한다(순서 = 은행 안 출력 순서).
3. `python -m whymath_backend.harness.p3_calculus1_diff_batch`로 은행을 재생성하고, 신규 모듈을
   `scripts/analysis/eos_feature_inventory_v2.py`에 귀속시키며, `tests/backend/l3/equivalent/
   test_p3_diff_skeleton_generators.py`의 `test_registry_holds_both_first_concepts_in_order`에 새
   생성기 import를 더한다(생성기 모듈명 참조 가드 `tests/infra/test_path_scoped_counting_guard`).
   `ops/declared_unwired_audit.py`는 이 배치 하나만 등록돼 있어 건드리지 않는다.

**review_status를 쓰지 않는다**(키 부재 유지) — 승인은 감사 표본 경로의 몫이다. 이 배치는
기록 직전에 전 레코드에서 그 키가 없음을 검사하고, 있으면 예외로 멈춘다(저작 도구가 승인을
대신 쓰는 사고 방지).

**검증 등급 각인**: `machine_sampled`(Tier1 SymPy 검산). 산출물은 v0(사람 검수 전) —
`is_published`는 False로 유지된다.

CLI:
    python -m whymath_backend.harness.p3_calculus1_diff_batch [--out-dir DIR] [--dry-run] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.problem_corpus_batch import (
    BandResult,
    CorpusBatchReport,
    JsonlCorpusSink,
)
from whymath_backend.l3.equivalent.orchestrator import run_equivalent_generation
from whymath_backend.l3.equivalent.p3_diff_polynomial_rules_skeleton_generator import (
    P3DiffPolynomialRulesGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_power_derivative_skeleton_generator import (
    P3DiffPowerDerivativeGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import (
    SLOT_IDS,
    SLOT_NAMES_KO,
    P3DiffSlotGenerator,
    skeleton_of,
)
from whymath_backend.l3.verification_tier import VerificationTier

__all__ = [
    "CORPUS_DIR_NAME",
    "GENERATORS",
    "build_provenance",
    "main",
    "run_p3_calculus1_diff_batch",
]

CORPUS_DIR_NAME: Final = "problem_bank_p3_calculus1_diff_v0"

#: 개념별 생성기 등록부 — 새 개념은 여기에 한 줄을 더한다(순서 = 은행 안 출력 순서).
GENERATORS: Final[tuple[type[P3DiffSlotGenerator], ...]] = (
    P3DiffPowerDerivativeGenerator,
    P3DiffPolynomialRulesGenerator,
)

#: 사이드카 `generated` — 은행이 처음 만들어진 날. 의도적 내용 변경이 아니면 바꾸지 않는다
#: (재생성 때마다 오늘 날짜를 박으면 `--check`가 매일 드리프트를 낸다).
_GENERATED_DATE: Final = "2026-10-06"

_PROBLEMS_FILE: Final = "problems.jsonl"
_PROVENANCE_FILE: Final = "_provenance.json"


def _default_out_dir() -> Path:
    root = Path(__file__).resolve().parents[4]
    return root / "data" / "corpus" / CORPUS_DIR_NAME


def _assert_no_review_status(path: Path) -> None:
    """기록한 JSONL 전 행에 `review_status` 키가 없음을 확인한다(있으면 RuntimeError)."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip() and "review_status" in json.loads(line):
            raise RuntimeError(
                f"{path} {number}행에 review_status 키가 있다 — 이 배치는 승인을 쓰지 않는다"
            )


def run_p3_calculus1_diff_batch(
    *,
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
    out_path: Path | None = None,
    write: bool = True,
) -> CorpusBatchReport:
    """등록부의 개념 × 6슬롯을 돌려 게이트(Tier1 SymPy 검산)를 통과한 문항을 적재한다.

    밴드 1개 = (개념, 슬롯). 슬롯마다 수용 게이트 스펙(성취기준·오개념·난이도)을 따로 만든다 —
    오개념 유발 슬롯만 스펙이 kebab 집합을 요구하고, 나머지는 공집합이라 동등성 점수가 1.0이다.
    `signature_index=None`으로 호출한다(구조 dedup이 해값 기반이라 서로 다른 문항을 오탐).
    """
    resolved_out = out_path if out_path is not None else _default_out_dir() / _PROBLEMS_FILE
    sink = JsonlCorpusSink()
    seen: set[str] = set()
    bands: list[BandResult] = []
    total_requested = 0
    total_stored = 0
    for generator_cls in generators:
        for slot in SLOT_IDS:
            spec = generator_cls.spec_for(slot)
            generator = generator_cls(slot=slot, skip_conditions=seen)
            requested = len(generator_cls.items(slot))
            stored = 0
            failures: list[str] = []
            for _ in range(requested):
                outcome = run_equivalent_generation(
                    spec,
                    generator,
                    store=sink,
                    signature_index=None,
                    verification_tier=VerificationTier.MACHINE_SAMPLED.value,
                )
                if outcome.status == "accepted_stored":
                    stored += 1
                    candidate = outcome.candidate
                    if candidate is not None:
                        cond = candidate.conditions
                        seen.add(cond if isinstance(cond, str) else "&&".join(cond))
                else:
                    failures.extend(outcome.reasons or [f"status={outcome.status}"])
            bands.append(
                BandResult(
                    name=f"{generator_cls.standard_code}:{slot}",
                    requested=requested,
                    stored=stored,
                    failure_reasons=failures,
                )
            )
            total_requested += requested
            total_stored += stored

    written = sink.write(resolved_out) if write else None
    if written is not None:
        _assert_no_review_status(resolved_out)
    return CorpusBatchReport(
        bands=bands,
        total_requested=total_requested,
        total_stored=total_stored,
        written=written,
        out_path=str(resolved_out),
    )


def build_provenance(
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
) -> dict[str, Any]:
    """사이드카(`_provenance.json`) 내용 — 생성기 문항 목록에서 결정론으로 계산한다(시계 의존 0)."""
    concepts: dict[str, Any] = {}
    total = 0
    for generator_cls in generators:
        per_slot = {slot: len(generator_cls.items(slot)) for slot in SLOT_IDS}
        texts = [item.question_text for slot in SLOT_IDS for item in generator_cls.items(slot)]
        frames = {item.frame_id for slot in SLOT_IDS for item in generator_cls.items(slot)}
        records = sum(per_slot.values())
        total += records
        concepts[generator_cls.standard_code] = {
            "concept_src_id": generator_cls.concept_src_id,
            "records": records,
            "slots": per_slot,
            "distinct_frames": len(frames),
            "distinct_skeletons": len({skeleton_of(t) for t in texts}),
            "generator": f"{generator_cls.__module__.rsplit('.', 1)[-1]}.{generator_cls.__name__}",
        }
    return {
        "pool": "whymath-original",
        "source_citation": (
            "출처: WhyMath 자체 저작 동등문제(WHYMATH_GENERATED). "
            "평가원·EBS·검정교과서 본문 복제 0 — "
            "성취기준 코드와 수학 구조(도함수 규칙)만으로 결정론 생성(본문 미보유 출처 인용 아님)."
        ),
        "license_notice": (
            "본 코퍼스의 모든 문항은 WhyMath가 자체 생성한 저작물(license=WHYMATH_GENERATED, "
            "source_type=자체생성)이다. 저작권은 WhyMath에 있으며 본문 보유가 합법이다"
            "(schema/problem.py _METADATA_ONLY_SOURCES 규칙과 정합)."
        ),
        "corpus_name": CORPUS_DIR_NAME,
        "record_count": total,
        "generated": _GENERATED_DATE,
        "generation_method": (
            "결정론 스켈레톤 생성기(LLM 0) — 개념 1개당 생성기 1파일(l3/equivalent/"
            "p3_diff_*_skeleton_generator.py), 슬롯 6종"
            "(대표·기본·응용·오개념 유발·진단·숙련도 확인). "
            "정답은 SymPy 미분으로 계산하고 수용 게이트 Tier1이 재검산한다."
        ),
        "generation_cli": "python -m whymath_backend.harness.p3_calculus1_diff_batch",
        "task": "P3-03-coverage-fill",
        "slot_names_ko": dict(SLOT_NAMES_KO),
        "concepts": concepts,
        "approval_status": {
            "note": (
                "미승인 — 레코드에 review_status 키를 쓰지 않는다(None/키 부재). 승인은 감사 표본 "
                "경로의 몫이며 이 도구가 대신 쓰지 않는다. 승인 전에는 Phase 3 계측기의 "
                "'승인 문항'으로 세어지지 않는다."
            ),
            "sample_review": "없음(0건)",
            "evidence": "없음 — 승인 전까지 is_published=False 유지",
        },
    }


def _render_provenance(generators: Sequence[type[P3DiffSlotGenerator]]) -> str:
    return json.dumps(build_provenance(generators), ensure_ascii=False, indent=2) + "\n"


def _check(generators: Sequence[type[P3DiffSlotGenerator]], out_dir: Path) -> int:
    """`--check` — 재생성 결과를 임시 디렉터리에 만들어 은행 파일과 바이트 비교한다(드리프트 1)."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh_problems = Path(tmp) / _PROBLEMS_FILE
        report = run_p3_calculus1_diff_batch(generators=generators, out_path=fresh_problems)
        if report.total_stored != report.total_requested:
            print("재생성 중 게이트 거부가 있어 드리프트를 판정할 수 없다.", file=sys.stderr)
            return 1
        drift: list[str] = []
        for name, fresh_bytes in (
            (_PROBLEMS_FILE, fresh_problems.read_bytes()),
            (_PROVENANCE_FILE, _render_provenance(generators).encode("utf-8")),
        ):
            target = out_dir / name
            if not target.is_file():
                drift.append(f"{name}: 파일이 없다")
            elif target.read_bytes() != fresh_bytes:
                drift.append(f"{name}: 재생성 결과와 바이트가 다르다")
    if drift:
        for line in drift:
            print(f"드리프트 — {line}", file=sys.stderr)
        print(
            "다음으로 재생성하라: python -m whymath_backend.harness.p3_calculus1_diff_batch",
            file=sys.stderr,
        )
        return 1
    print(f"드리프트 없음 — {out_dir} (문항 {report.total_stored}건)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI — 게이트 거부가 하나라도 있으면 exit 1(조용한 실패 금지)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.p3_calculus1_diff_batch",
        description="Phase 3 미적분Ⅰ 미분 문항 은행 결정론 재생성(Tier1 검산·승인 미기록).",
    )
    parser.add_argument("--out-dir", default=None, help="출력 은행 디렉터리(기본 저장소 은행).")
    parser.add_argument("--dry-run", action="store_true", help="파일 기록 없이 수율만 출력.")
    parser.add_argument(
        "--check", action="store_true", help="재생성 결과가 저장소 은행과 바이트 동일한지 검사."
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()

    if args.check:
        return _check(GENERATORS, out_dir)

    report = run_p3_calculus1_diff_batch(out_path=out_dir / _PROBLEMS_FILE, write=not args.dry_run)
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    rejected = sum(len(b.failure_reasons) for b in report.bands)
    if rejected:
        print(f"게이트 거부 {rejected}건 — 저작 결함(조용한 통과 금지).", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0 if report.total_stored > 0 else 1
    (out_dir / _PROVENANCE_FILE).write_text(_render_provenance(GENERATORS), encoding="utf-8")
    return 0 if report.total_stored > 0 else 1


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
