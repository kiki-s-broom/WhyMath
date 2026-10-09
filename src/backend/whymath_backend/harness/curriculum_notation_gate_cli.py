"""교육과정 표기 범위 게이트 CLI(MATH-04) — L4 학년 프로파일을 L3 엔진에 주입해 코퍼스를 돈다.

엔진(`l3/curriculum_notation_gate.py`)은 L4를 import할 수 없다(7계층 계약 — L3→L4는 역방향).
그래서 `l4/speech/profiles.py::PROFILES`의 `introduced_constructs`를 읽어 엔진에 인자로 넘기는
배선이 이 CLI의 일이다(`l3/pedagogy/explanation_checker` ↔ `harness/explanation_f7_eval` 선례와
같은 분업). `harness`는 계층 계약 밖이라 상위 호출이 정상이다.

⚠ 생성물 회계 전용이다 — 학생 입력 경로에 배선하지 않는다(교수학 금기·gap_review §2-⑤).
`tests/backend/l3/test_curriculum_notation_gate_student_path_governance.py`가 동결한다.

사용:
    python -m whymath_backend.harness.curriculum_notation_gate_cli
    python -m whymath_backend.harness.curriculum_notation_gate_cli --json report.json
    # 보조 코퍼스(이론·수식 그래프·시각 양식·시각화 가능성)는 기본 포함 — 부분 실행만 제외 플래그
    python -m whymath_backend.harness.curriculum_notation_gate_cli --problem-banks-only
    # 변별력 대조군: 고등은 exit 0, 초등은 exit 1이어야 측정기가 정상이다
    python -m whymath_backend.harness.curriculum_notation_gate_cli --force-grade-band 고등
    python -m whymath_backend.harness.curriculum_notation_gate_cli --force-grade-band 초등

종료 코드: 0 = 신규 초과 표기 0 · 1 = 신규 초과 표기 발견(래칫). 입력 부재·구조 위반은 예외 타입명과
함께 명시 실패한다(`notation_coverage` 동형·침묵 skip 금지).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from whymath_backend.l3.curriculum_notation_gate import (
    DEFAULT_AUX_SOURCES,
    build_json_payload,
    render_report,
    run_gate,
)
from whymath_backend.l4.speech.profiles import PROFILES
from whymath_backend.schema.speech import SpeechGradeBand

_EXIT_OK: Final[int] = 0
_EXIT_GATE_FAIL: Final[int] = 1

__all__ = ["constructs_by_band", "main"]


def constructs_by_band() -> dict[SpeechGradeBand, frozenset[str]]:
    """`PROFILES`에서 밴드별 도입 구조 집합을 조립한다 — 구조 키 어휘의 유일한 출처."""
    return {band: frozenset(profile.introduced_constructs) for band, profile in PROFILES.items()}


def _repo_root() -> Path:
    # src/backend/whymath_backend/harness/ → repo root 5단계(l3/notation_coverage와 동일 깊이).
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    """CLI — 교육과정 표기 범위 게이트. exit 0(신규 초과 표기 0)/1(신규 초과 표기 발견)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.curriculum_notation_gate_cli",
        description=(
            "교육과정 표기 범위 게이트(MATH-04) — 문항 표기 토큰의 구조가 문항 밴드에 도입돼 "
            "있는지 전수 회계하고 베이스라인 대비 신규 초과 표기 발견 시 exit 1"
            "(래칫·hermetic·LLM 0). "
            "생성물 회계 전용 — 학생 입력 거부에 쓰지 않는다."
        ),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="코퍼스 루트(기본 repo data/corpus) — problem_bank_*/problems.jsonl + 보조 코퍼스 5종"
        "(concept_content_v1 등 — 부재하면 명시 실패).",
    )
    parser.add_argument(
        "--table",
        type=Path,
        default=None,
        help="토큰 → 구조 키 폐쇄 표(기본 repo data/curriculum_notation_ranges.json).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="초과 표기 베이스라인(기본 repo data/curriculum_notation_range_baseline.json) "
        "— 갱신은 의식적 수동 편집만.",
    )
    parser.add_argument(
        "--standards",
        type=Path,
        default=None,
        help="성취기준 정본(기본 repo data/corpus/standards_v1/standards.json) — 문항 밴드 파생.",
    )
    parser.add_argument(
        "--problem-banks-only",
        action="store_true",
        help="보조 코퍼스 5종(이론·수식 그래프·시각 양식 등)을 제외하고 문항 은행만 돈다 — "
        "합성 코퍼스 테스트·부분 실행용. CI 게이트 스텝은 이 플래그를 쓰지 않는다"
        "(tests/backend/l3/test_curriculum_notation_gate.py가 배선을 동결).",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON 리포트 출력 경로(선택).")
    parser.add_argument(
        "--force-grade-band",
        choices=[band.value for band in SpeechGradeBand],
        default=None,
        help="변별력 대조군 — 모든 문항을 이 밴드로 강제 판정(고등 exit 0 · 초등 exit 1이 정상).",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    corpus_root: Path = (
        args.corpus_root if args.corpus_root is not None else root / "data" / "corpus"
    )
    report = run_gate(
        corpus_root=corpus_root,
        table_path=(
            args.table
            if args.table is not None
            else root / "data" / "curriculum_notation_ranges.json"
        ),
        baseline_path=(
            args.baseline
            if args.baseline is not None
            else root / "data" / "curriculum_notation_range_baseline.json"
        ),
        standards_path=(
            args.standards
            if args.standards is not None
            else corpus_root / "standards_v1" / "standards.json"
        ),
        constructs_by_band=constructs_by_band(),
        force_band=SpeechGradeBand(args.force_grade_band) if args.force_grade_band else None,
        aux_sources=() if args.problem_banks_only else DEFAULT_AUX_SOURCES,
    )

    print(render_report(report))
    if args.json is not None:
        args.json.write_text(
            json.dumps(build_json_payload(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON 리포트 저장: {args.json}")
    return _EXIT_OK if report.gate_ok else _EXIT_GATE_FAIL


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    sys.exit(main())
