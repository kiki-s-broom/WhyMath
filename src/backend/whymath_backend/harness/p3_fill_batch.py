"""Phase 3 6슬롯·Problem Coverage 빈 칸 채우기 문항 은행 배치 — P3-05 4·5단계(순수 결정론·LLM 0).

`slot_assignment_rules.yaml`(3단계)가 기존 문항 재배정으로 채운 뒤에도 비어 있는 칸과,
승인 문항이 0건인 스킬(패턴 일반화·문장제 모델링)을 채우는 **새 은행**
`data/corpus/problem_bank_p3_fill_v0/`를 결정론적으로 재생성한다. 같은 입력이면
`problems.jsonl`·`_provenance.json` 두 파일 모두 바이트가 같다(`--check`).

왜 기존 은행(`problem_bank_p3_calculus1_diff_v0`, 504건)에 더하지 않는가
-----------------------------------------------------------------------
그 은행은 감사 5회차를 거쳐 **내용이 동결된 사본과 바이트 대조**로 승인이 유효하다. 문항을 더하면
승인이 옮겨 가지 않아 504건이 전부 무효가 된다. 새 은행은 별도 감사를 받는다 — 승인 판정의 표본 크기
하한(`_MIN_N = 200`) 때문에 4단계(13칸)와 5단계(패턴 일반화·문장제)를 **한 은행으로
묶는다**(Kiki 결정 2026-10-15: 204건 = 13칸 × 12 + 02-03 패턴 일반화 24 + 02-10 문장제 24).

실행 기반은 기존 배치(`p3_calculus1_diff_batch`)를 그대로 쓴다. 다른 점은 등록부
(`GENERATORS`)와 은행 이름·사이드카 문구, 그리고 생성기가 `slots`로 좁힌 부분집합만 돈다는 것
(기존 배치는 6슬롯 전부).

개념을 추가하는 법
------------------
1. `l3/equivalent/p3_diff_<개념>_skeleton_generator.py`에 `P3DiffSlotGenerator` 하위 클래스를 쓰되
   `slots`에 *빈 칸만* 선언한다.
2. 이 파일의 `GENERATORS`에 한 줄을 더하고
   `python -m whymath_backend.harness.p3_fill_batch`로 재생성한다.
3. 신규 모듈을 `scripts/analysis/eos_feature_inventory_v2.py`에 귀속시킨다.

**review_status를 쓰지 않는다** — 승인은 감사 표본 경로의 몫이다(기존 배치와 같은 방어).

CLI:
    python -m whymath_backend.harness.p3_fill_batch [--out-dir DIR] [--dry-run] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from whymath_backend.harness.p3_calculus1_diff_batch import (
    build_provenance as _base_provenance,
)
from whymath_backend.harness.p3_calculus1_diff_batch import (
    drift_against,
    refuses_structured_write,
    run_p3_calculus1_diff_batch,
)
from whymath_backend.l3.equivalent.p3_diff_differentiability_skeleton_generator import (
    P3DiffDifferentiabilityGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_differential_coefficient_skeleton_generator import (
    P3DiffDifferentialCoefficientGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_monotonicity_extremum_skeleton_generator import (
    P3DiffMonotonicityExtremumGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_motion_word_problem_skeleton_generator import (
    P3DiffMotionWordProblemGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_power_pattern_skeleton_generator import (
    P3DiffPowerPatternGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import P3DiffSlotGenerator

__all__ = ["CORPUS_DIR_NAME", "GENERATORS", "build_provenance", "main", "run_p3_fill_batch"]

CORPUS_DIR_NAME: Final = "problem_bank_p3_fill_v0"

#: 개념별 생성기 등록부 — 새 생성기는 여기에 한 줄을 더한다(순서 = 은행 안 출력 순서).
GENERATORS: Final[tuple[type[P3DiffSlotGenerator], ...]] = (
    P3DiffDifferentialCoefficientGenerator,
    P3DiffDifferentiabilityGenerator,
    P3DiffMonotonicityExtremumGenerator,
    # 5단계 — 스킬 덮기(규칙 일반화·문장제 모델링). 위 4개와 달리 빈 칸이 아니라 스킬을 채운다.
    P3DiffPowerPatternGenerator,
    P3DiffMotionWordProblemGenerator,
)

#: 사이드카 `generated` — 은행이 처음 만들어진 날. 의도적 내용 변경이 아니면 바꾸지 않는다.
_GENERATED_DATE: Final = "2026-10-15"

_PROBLEMS_FILE: Final = "problems.jsonl"
_PROVENANCE_FILE: Final = "_provenance.json"


def _default_out_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "corpus" / CORPUS_DIR_NAME


def run_p3_fill_batch(
    *,
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
    out_path: Path | None = None,
    write: bool = True,
    structure_final_step: bool = False,
) -> Any:
    """등록부의 (개념 × 담당 슬롯)을 돌려 게이트(Tier1 SymPy 검산)를 통과한 문항을 적재한다.

    `structure_final_step`이면 규칙 (가)(P3-62) 후보 은행(기존 배치와 같은 스위치).
    """
    resolved = out_path if out_path is not None else _default_out_dir() / _PROBLEMS_FILE
    return run_p3_calculus1_diff_batch(
        generators=generators,
        out_path=resolved,
        write=write,
        structure_final_step=structure_final_step,
    )


def build_provenance(
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
    *,
    structured: bool = False,
) -> dict[str, Any]:
    """사이드카 내용 — 기존 배치의 계산에 이 은행의 이름·출처 문구를 덮어쓴다(시계 의존 0)."""
    provenance = _base_provenance(generators, structured=structured)
    provenance.update(
        {
            "corpus_name": CORPUS_DIR_NAME,
            "generated": _GENERATED_DATE,
            "generation_method": (
                "결정론 스켈레톤 생성기(LLM 0) — 개념 1개당 생성기 1파일(l3/equivalent/"
                "p3_diff_*_skeleton_generator.py), 기존 승인 문항이 채우지 못한 슬롯만 담당. "
                "정답은 SymPy 미분으로 계산하고 수용 게이트 Tier1이 재검산한다."
            ),
            "generation_cli": "python -m whymath_backend.harness.p3_fill_batch",
            "task": "P3-05-triangle-density",
            "approval_status": {
                "note": (
                    "이 도구는 review_status를 쓰지 않는다(키 부재). 승인은 자격 통과 프로토콜 "
                    "감사 "
                    "(n ≥ 200 · Wilson 상한 ≤ 0.02) 뒤 코퍼스 단위 백필이 쓴다."
                ),
                "sample_review": (
                    "204건 전수 — 자격 통과 프로토콜(기계 ∪ LLM 판정자 A ∪ B) 3회차 S5 감사, "
                    "결함 0건 · 보정 상한 0.01907 ≤ 0.02"
                ),
                "evidence": (
                    "docs/data/p3_fill_audit/bank_audit_r3/ (라벨·동결 사본) · "
                    "docs/data/corpus_audit_p3_fill_v0.jsonl (코퍼스 단위 라벨) · "
                    "is_published=False 유지"
                ),
            },
        }
    )
    return provenance


def _render_provenance(
    generators: Sequence[type[P3DiffSlotGenerator]], *, structured: bool = False
) -> str:
    return (
        json.dumps(
            build_provenance(generators, structured=structured), ensure_ascii=False, indent=2
        )
        + "\n"
    )


def _check(generators: Sequence[type[P3DiffSlotGenerator]], out_dir: Path) -> int:
    """`--check` — 재생성 결과를 임시 디렉터리에 만들어 은행 파일과 비교한다(드리프트 1)."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / _PROBLEMS_FILE
        report = run_p3_fill_batch(generators=generators, out_path=fresh)
        if report.total_stored != report.total_requested:
            print("재생성 중 게이트 거부가 있어 드리프트를 판정할 수 없다.", file=sys.stderr)
            return 1
        drift = drift_against(
            out_dir, fresh.read_bytes(), _render_provenance(generators).encode("utf-8")
        )
    if drift:
        for line in drift:
            print(f"드리프트 — {line}", file=sys.stderr)
        print(
            "다음으로 재생성하라: python -m whymath_backend.harness.p3_fill_batch", file=sys.stderr
        )
        return 1
    print(f"드리프트 없음 — {out_dir} (문항 {report.total_stored}건)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI — 게이트 거부가 하나라도 있으면 exit 1(조용한 실패 금지)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.p3_fill_batch",
        description="Phase 3 빈 칸 채우기 문항 은행 결정론 재생성(Tier1 검산·승인 미기록).",
    )
    parser.add_argument("--out-dir", default=None, help="출력 은행 디렉터리(기본 저장소 은행).")
    parser.add_argument("--dry-run", action="store_true", help="파일 기록 없이 수율만 출력.")
    parser.add_argument(
        "--check", action="store_true", help="재생성 결과가 저장소 은행과 바이트 동일한지 검사."
    )
    parser.add_argument(
        "--structure-final-step",
        action="store_true",
        help="규칙 (가)(P3-62) 후보 은행 — 승인 은행 자리에는 쓰지 않는다(--out-dir 필수).",
    )
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()

    if args.check:
        if args.structure_final_step:
            print(
                "--check 는 승인 은행 드리프트 검사다 — 구조화 후보와 함께 쓰지 않는다.",
                file=sys.stderr,
            )
            return 2
        return _check(GENERATORS, out_dir)
    if args.structure_final_step and not args.dry_run:
        refusal = refuses_structured_write(out_dir, _default_out_dir())
        if refusal is not None:
            print(f"WRITE_REFUSED — {refusal}", file=sys.stderr)
            return 2

    report = run_p3_fill_batch(
        out_path=out_dir / _PROBLEMS_FILE,
        write=not args.dry_run,
        structure_final_step=args.structure_final_step,
    )
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    rejected = sum(len(b.failure_reasons) for b in report.bands)
    if rejected:
        print(f"게이트 거부 {rejected}건 — 저작 결함(조용한 통과 금지).", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0 if report.total_stored > 0 else 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / _PROVENANCE_FILE).write_text(
        _render_provenance(GENERATORS, structured=args.structure_final_step), encoding="utf-8"
    )
    return 0 if report.total_stored > 0 else 1


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
