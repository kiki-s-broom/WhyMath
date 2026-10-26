"""[12미적Ⅰ-02-02] 개념 스킬 도달 문항 은행 배치 — P3-65(순수 결정론·LLM 0).

P3-55 판정(2026-10-18 ·
`docs/reviews/p3_55_calc1_02_02_content_single_template_judgment_2026-10-18.md`) 결정 (나)의 (가)
가지다. [12미적Ⅰ-02-02]의 Content 연결은 승인 문항 24건(`problem_bank_conceptual_v0` ·
`ptype.verify-claim` · 정답 `0` 하나 · 줄기 4개)에만 걸려 있었다(위험 R1 승인 의존·R2 다양성
부족). 이 배치는 동결 명세가 이미 허용하는 스킬 도달 유형 두 가지 —
`ptype.count-solutions`(미분가능하지 않은 점의 개수)·`ptype.verify-claim`(미분가능성 참/거짓
0/1) — 의 문항을 **새 은행**
`data/corpus/problem_bank_p3_differentiability_reach_v0/`에 결정론으로 재생성한다. 같은 입력이면
`problems.jsonl`·`_provenance.json` 두 파일 모두 바이트가 같다(`--check`).

왜 기존 은행(`problem_bank_p3_fill_v0`)에 더하지 않는가
------------------------------------------------------
그 은행은 3회차 S5 감사를 거쳐 **감사 동결 사본과 바이트 대조**로 승인이 유효하다
(`tests/backend/l1/test_p3_fill_bank_coverage_link.py`). 문항을 더하면 승인이 옮겨 가지 않아 204건이
전부 무효가 된다. 그래서 생성기도 새 클래스(`P3DiffDifferentiabilityReachGenerator`)이고 은행도 새
폴더다.

은행 크기 300건 = 5슬롯 × 60건
------------------------------
승인 각인은 코퍼스 단위 감사 표본 n ≥ 200(`problem_corpus_review_status_backfill._MIN_N`)에서만
성립하고, 판정 S5 = Wilson 단측 97.5% 상한(k, n) ÷ 검출률 하한 0.96898 ≤ 0.02다
(`p3_audit_qualification.corrected_upper_bound`). n = 204(P3-05 선례)는 k = 0만 통과하는 경계였다
(3회차 만에 통과). n = 300에서는 k ≤ 1이 통과한다(k = 1 → 0.01923 · k = 2 → 0.02475) — 결함 1건에
은행 전체를 다시 만들지 않아도 되는 가장 작은 크기 근방이다(n = 292부터 k = 1 통과).

**review_status를 쓰지 않는다** — 승인은 감사 표본 경로(사람 게이트)의 몫이다(기존 배치와 같은
방어 — 기록 직전에 그 키가 없음을 검사한다).

CLI:
    python -m whymath_backend.harness.p3_differentiability_reach_batch [--out-dir DIR] [--dry-run]
                                                                       [--check]
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
    run_p3_calculus1_diff_batch,
)
from whymath_backend.l3.equivalent.p3_diff_differentiability_skeleton_generator import (
    P3DiffDifferentiabilityReachGenerator,
)
from whymath_backend.l3.equivalent.p3_diff_skeleton_base import P3DiffSlotGenerator

__all__ = [
    "CORPUS_DIR_NAME",
    "GENERATORS",
    "build_provenance",
    "main",
    "run_p3_differentiability_reach_batch",
]

CORPUS_DIR_NAME: Final = "problem_bank_p3_differentiability_reach_v0"

#: 생성기 등록부 — [12미적Ⅰ-02-02] 하나만(P3-65 범위 ② — 다른 개념은 채우지 않는다).
GENERATORS: Final[tuple[type[P3DiffSlotGenerator], ...]] = (P3DiffDifferentiabilityReachGenerator,)

#: 사이드카 `generated` — 은행이 처음 만들어진 날. 의도적 내용 변경이 아니면 바꾸지 않는다.
_GENERATED_DATE: Final = "2026-10-26"

_PROBLEMS_FILE: Final = "problems.jsonl"
_PROVENANCE_FILE: Final = "_provenance.json"


def _default_out_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "corpus" / CORPUS_DIR_NAME


def run_p3_differentiability_reach_batch(
    *,
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
    out_path: Path | None = None,
    write: bool = True,
) -> Any:
    """등록부의 (개념 × 담당 슬롯)을 돌려 수용 게이트(Tier1 SymPy 검산)를 통과한 문항을 적재한다."""
    resolved = out_path if out_path is not None else _default_out_dir() / _PROBLEMS_FILE
    return run_p3_calculus1_diff_batch(generators=generators, out_path=resolved, write=write)


def build_provenance(
    generators: Sequence[type[P3DiffSlotGenerator]] = GENERATORS,
) -> dict[str, Any]:
    """사이드카 내용 — 기존 배치의 계산에 이 은행의 이름·출처·승인 상태 문구를 덮어쓴다.

    시계에 의존하지 않는다(재생성 바이트 동일).
    """
    provenance = _base_provenance(generators)
    provenance.update(
        {
            "corpus_name": CORPUS_DIR_NAME,
            "generated": _GENERATED_DATE,
            "generation_method": (
                "결정론 스켈레톤 생성기(LLM 0) — 개념 생성기 모듈 "
                "p3_diff_differentiability_skeleton_generator 의 "
                "P3DiffDifferentiabilityReachGenerator"
                "(저작 서명 모듈 p3_diff_skeleton_base). [12미적Ⅰ-02-02]의 개념 "
                "스킬에 닿는 두 유형(count-solutions · verify-claim)만 만든다. 정답은 SymPy가 "
                "후보(절댓값 안의 식의 실근)마다 좌·우 분기의 미분계수를 비교해 계산하고, 수용 "
                "게이트 Tier1이 차분몫의 좌·우 극한으로 다시 검산한다"
                "(nondifferentiable_point_count · is_differentiable)."
            ),
            "generation_cli": "python -m whymath_backend.harness.p3_differentiability_reach_batch",
            "task": "P3-65-calc1-02-02-skill-reaching-bank",
            "approval_status": {
                "note": (
                    "이 도구는 review_status를 쓰지 않는다(키 부재). 승인은 자격 통과 프로토콜 감사"
                    "(n ≥ 200 · 보정 상한 ≤ 0.02 — n = 300에서 k ≤ 1 통과) 뒤 코퍼스 단위 백필이 "
                    "쓴다. 감사 전에는 phase3_coverage 의 적격 문항이 아니다."
                ),
                "sample_review": "미실시 — 감사 라운드 대기(사람 게이트)",
                "evidence": (
                    "docs/reviews/p3_65_calc1_02_02_skill_reaching_bank_2026-10-26.md "
                    "(감사 런북 · 커버리지 전후·투영 표) · is_published=False 유지"
                ),
            },
        }
    )
    return provenance


def _render_provenance(generators: Sequence[type[P3DiffSlotGenerator]]) -> str:
    return json.dumps(build_provenance(generators), ensure_ascii=False, indent=2) + "\n"


def _check(generators: Sequence[type[P3DiffSlotGenerator]], out_dir: Path) -> int:
    """`--check` — 재생성 결과를 임시 디렉터리에 만들어 은행 파일과 비교한다(드리프트 1)."""
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / _PROBLEMS_FILE
        report = run_p3_differentiability_reach_batch(generators=generators, out_path=fresh)
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
            "다음으로 재생성하라: "
            "python -m whymath_backend.harness.p3_differentiability_reach_batch",
            file=sys.stderr,
        )
        return 1
    print(f"드리프트 없음 — {out_dir} (문항 {report.total_stored}건)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI — 게이트 거부가 하나라도 있으면 exit 1(조용한 실패 금지)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.p3_differentiability_reach_batch",
        description="[12미적Ⅰ-02-02] 스킬 도달 문항 은행 결정론 재생성(Tier1 검산·승인 미기록).",
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

    report = run_p3_differentiability_reach_batch(
        out_path=out_dir / _PROBLEMS_FILE, write=not args.dry_run
    )
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    rejected = sum(len(b.failure_reasons) for b in report.bands)
    if rejected:
        print(f"게이트 거부 {rejected}건 — 저작 결함(조용한 통과 금지).", file=sys.stderr)
        return 1
    if args.dry_run:
        return 0 if report.total_stored > 0 else 1
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / _PROVENANCE_FILE).write_text(_render_provenance(GENERATORS), encoding="utf-8")
    return 0 if report.total_stored > 0 else 1


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트
    sys.exit(main())
