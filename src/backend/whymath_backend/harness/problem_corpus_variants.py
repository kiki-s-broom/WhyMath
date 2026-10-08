"""변형 3종 발화 CLI(PB-09) — 코퍼스를 입력으로 난이도 계열·조건변형·역문제를 계보와 함께 JSONL로.

`problem_corpus_batch`는 코퍼스 전체를 바이트 동일로 재생성하는 봉인 경로라 거기에 파생 변형을
끼우지 않는다. 대신 `problem_corpus_rephrase`처럼 **기존 코퍼스를 읽기 전용 입력**으로 받는 별도
단계로 둔다(`l3/equivalent/variants.py`가 부모 행에서 자식 후보를 낸다).

각 자식은 다음을 *전부* 통과해야 저장된다 — 이 모듈은 합격을 선언하지 않고
기존 파이프라인에 태울 뿐이다.

  1. S2-a 수용 게이트(저작권·정확성·위생·동등성) — `run_equivalent_generation`
  2. 구조 signature dedup — 시드는 `problem_bank_*` **전 코퍼스**(부모 포함)다. 그래서 이미 있는
     (방정식, 근 선택)을 새로 낳은 척하지 않는다.
  3. 임베딩 dedup — 좌석(`dedup_index`·`embed_provider`)을 주입하면 같은 경로로 돈다. 기본 CLI는
     배치 CLI와 같이 DB·임베딩 0(hermetic)이라 이 단계는 꺼져 있고, 켠 실행은 Phaiakes9 소관이다.
  4. 자체 변형 키 — 연립 조건(부호 조건·역문제)은 signature가 없어(None) 1·2가 못 거르므로
     이 모듈이 `(이동, 정규 계수/근)` 키로 직접 거른다.

## "작동한 비율" 원칙 (CLAUDE.md — 작동 신호 없는 알고리즘 부착 금지)

정상 종료(exit 0)는 알고리즘이 일했다는 증거가 아니다. 리포트는 이동마다 **시도 → skip(사유별) →
파생 → 결과 상태별 → 저장** 깔때기를 전부 싣고, `attempted == skipped + derived`·
`derived == Σ결과` 두 항등식이 깨지면 리포트 자체가 거짓이므로 `to_json`이 예외를 던진다.
모드(난이도 계열·조건변형·역문제) 중 하나라도 저장 0건이면 exit 1 — 부착됐으나 무작동인
모드가 정상 종료로 보이지 않게 한다.

## 이 CLI는 코퍼스를 커밋하지 않는다

`populate.py`·QA·CAT 후보 선정이 `data/corpus/problem_bank_*/problems.jsonl`을 전수 글롭하므로,
검수·노출 게이트 분석 없이 산출물을 그 경로에 두면 미검수 문항이 후보로 흘러갈 수 있다. 그래서
`--out`은 필수이며 기본 경로가 없다. 산출물을 코퍼스로 편입하는 것은 별도 결정이다.

사용법:
    python -m whymath_backend.harness.problem_corpus_variants --out <dst.jsonl>
    python -m whymath_backend.harness.problem_corpus_variants --out <dst.jsonl> --dry-run

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_batch 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from whymath_backend.harness.problem_corpus_accumulate import load_corpus_index
from whymath_backend.harness.problem_corpus_batch import JsonlCorpusSink
from whymath_backend.l1.embedding_primitives import EmbeddingProvider
from whymath_backend.l1.problem_bank.embedding import ProblemEmbeddingIndex
from whymath_backend.l1.problem_bank.populate import ProblemRelationTag
from whymath_backend.l3.equivalent.generator import ScriptedGenerator
from whymath_backend.l3.equivalent.orchestrator import RoundDedupScope, run_equivalent_generation
from whymath_backend.l3.equivalent.variants import (
    MOVE_SPECS,
    MOVES,
    ParentRejection,
    VariantDraft,
    VariantMode,
    VariantMove,
    VariantParent,
    derive_variants,
    parse_parent,
)

__all__ = ["MoveReport", "VariantsReport", "main", "run_corpus_variants"]

_DEFAULT_PARENT_CORPUS = "problem_bank_generated_v0"
_MODES: tuple[VariantMode, ...] = ("ladder", "condition", "inverse")

# 오케스트레이터 밖에서 이 모듈이 직접 거르는 중복의 결과 키(상태 이름과 겹치지 않게 접두 고정).
_DUP_VARIANT_KEY = "rejected_duplicate/variant_key"
_DUP_SLUG = "rejected_duplicate/existing_slug"
_INVALID_NO_SLUG = "invalid_candidate/no_slug"


def _repo_root() -> Path:
    """repo 루트 — harness→whymath_backend→backend→src→repo (problem_corpus_batch 규약)."""
    return Path(__file__).resolve().parents[4]


@dataclass(slots=True)
class MoveReport:
    """이동 1종의 깔때기 — 시도 → skip → 파생 → 결과 → 저장."""

    move: VariantMove
    attempted: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    derived: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    stored: int = 0

    @property
    def mode(self) -> VariantMode:
        return MOVE_SPECS[self.move].mode

    @property
    def working_rate(self) -> float | None:
        """작동한 비율 = 저장 / 시도. 시도 0이면 None(0.0으로 위장하지 않는다)."""
        return None if self.attempted == 0 else self.stored / self.attempted

    def check_identities(self) -> None:
        """깔때기 항등식 — 깨지면 어딘가에서 시도가 조용히 사라진 것이다."""
        skipped = sum(self.skipped.values())
        if self.attempted != skipped + self.derived:
            raise AssertionError(
                f"{self.move}: attempted({self.attempted}) != skipped({skipped}) + "
                f"derived({self.derived}) — 시도가 조용히 유실됨"
            )
        if self.derived != sum(self.outcomes.values()):
            raise AssertionError(
                f"{self.move}: derived({self.derived}) != Σoutcomes({sum(self.outcomes.values())})"
            )
        if self.stored != self.outcomes.get("accepted_stored", 0):
            raise AssertionError(f"{self.move}: stored와 accepted_stored 불일치")


@dataclass(frozen=True, slots=True)
class VariantsReport:
    """변형 배치 전체 리포트 — 이동별 깔때기 + 부모 자격 회계 + 계보 좌석 실사용 집계."""

    parents_total: int
    parents_eligible: int
    parent_rejections: dict[str, int]
    moves: list[MoveReport]
    relation_type_counts: dict[str, int]
    generation_type_counts: dict[str, int]
    written: int | None
    out_path: str

    @property
    def attempted_total(self) -> int:
        return sum(m.attempted for m in self.moves)

    @property
    def stored_total(self) -> int:
        return sum(m.stored for m in self.moves)

    @property
    def working_rate(self) -> float | None:
        return None if self.attempted_total == 0 else self.stored_total / self.attempted_total

    def mode_stored(self) -> dict[str, int]:
        stored: dict[str, int] = dict.fromkeys(_MODES, 0)
        for move in self.moves:
            stored[move.mode] += move.stored
        return stored

    def silent_modes(self, requested: tuple[VariantMode, ...]) -> list[str]:
        """요청된 모드 중 저장 0건 — 부착됐으나 무작동인 모드(exit 1의 근거)."""
        stored = self.mode_stored()
        return [mode for mode in requested if stored[mode] == 0]

    def to_json(self) -> dict[str, Any]:
        for move in self.moves:
            move.check_identities()  # 거짓 리포트를 내느니 터진다.
        return {
            "parents_total": self.parents_total,
            "parents_eligible": self.parents_eligible,
            "parent_rejections": dict(sorted(self.parent_rejections.items())),
            "attempted_total": self.attempted_total,
            "stored_total": self.stored_total,
            "working_rate": self.working_rate,
            "mode_stored": self.mode_stored(),
            "relation_type_counts": dict(sorted(self.relation_type_counts.items())),
            "generation_type_counts": dict(sorted(self.generation_type_counts.items())),
            "moves": [
                {
                    "move": m.move,
                    "mode": m.mode,
                    "attempted": m.attempted,
                    "skipped": dict(sorted(m.skipped.items())),
                    "derived": m.derived,
                    "outcomes": dict(sorted(m.outcomes.items())),
                    "stored": m.stored,
                    "working_rate": m.working_rate,
                }
                for m in self.moves
            ],
            "written": self.written,
            "out_path": self.out_path,
        }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """입력 JSONL → dict 목록(순서 보존·빈 줄 무시)."""
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _outcome_key(status: str, detector: str | None) -> str:
    """결과 상태 키 — 중복은 어느 검출기가 잡았는지까지 갈라 센다(원인이 다르면 처방이 다르다)."""
    if status == "rejected_duplicate":
        return f"rejected_duplicate/{detector or 'unknown'}"
    return status


def run_corpus_variants(
    *,
    parent_paths: list[Path],
    signature_paths: list[Path],
    out_path: Path,
    moves: tuple[VariantMove, ...] = MOVES,
    write: bool = True,
    dedup_index: ProblemEmbeddingIndex | None = None,
    embed_provider: EmbeddingProvider | None = None,
) -> VariantsReport:
    """부모 코퍼스에서 변형을 낳아 게이트·dedup·저장에 태우고 계보를 부여한다(결정론·LLM 0)."""
    rows: list[dict[str, Any]] = []
    for path in parent_paths:
        rows.extend(_read_rows(path))

    parents: list[VariantParent] = []
    rejections: Counter[str] = Counter()
    for row in rows:
        parsed = parse_parent(row)
        if isinstance(parsed, ParentRejection):
            rejections[parsed.reason] += 1
        else:
            parents.append(parsed)

    signature_index, slug_index, _ = load_corpus_index(signature_paths)
    scope = RoundDedupScope()
    sink = JsonlCorpusSink()
    seen_keys: set[str] = set()
    lineage: dict[str, ProblemRelationTag] = {}
    reports: dict[VariantMove, MoveReport] = {move: MoveReport(move=move) for move in moves}

    for parent in parents:
        for item in derive_variants(parent, moves):
            report = reports[item.move]
            report.attempted += 1
            if not isinstance(item, VariantDraft):
                report.skipped[item.reason] += 1
                continue
            report.derived += 1
            slug = item.candidate.problem.slug
            if not slug:
                # 생성기 계약 위반(안정 키 없음) — 저장 불가라 조용히 넘기지 않고 센다.
                report.outcomes[_INVALID_NO_SLUG] += 1
                continue
            if item.dedup_key in seen_keys:
                report.outcomes[_DUP_VARIANT_KEY] += 1
                continue
            if slug in slug_index:
                report.outcomes[_DUP_SLUG] += 1
                continue
            outcome = run_equivalent_generation(
                item.spec,
                ScriptedGenerator([item.candidate]),
                dedup_index=dedup_index,
                embed_provider=embed_provider,
                signature_index=signature_index,
                round_scope=scope,
                store=sink,
            )
            report.outcomes[_outcome_key(outcome.status, outcome.duplicate_detector)] += 1
            if outcome.status == "accepted_stored":
                report.stored += 1
                seen_keys.add(item.dedup_key)
                slug_index.add(slug)
                lineage[slug] = ProblemRelationTag(
                    parent_slug=parent.slug,
                    relation_type=item.relation_type.value,
                    # 유사도는 추정하지 않는다 — 근거 없는 수치를 계보에 날조하지 않는다.
                    similarity_score=None,
                )

    stored_records = [replace(r, relations=(lineage[r.slug],)) for r in sink.records]
    sink.set_records(stored_records)
    written = sink.write(out_path) if write else None
    return VariantsReport(
        parents_total=len(rows),
        parents_eligible=len(parents),
        parent_rejections=dict(rejections),
        moves=[reports[m] for m in moves],
        relation_type_counts=dict(Counter(t.relation_type for t in lineage.values())),
        generation_type_counts=dict(Counter(r.provenance.generation_type for r in stored_records)),
        written=written,
        out_path=str(out_path),
    )


def _requested_modes(moves: tuple[VariantMove, ...]) -> tuple[VariantMode, ...]:
    return tuple(mode for mode in _MODES if any(MOVE_SPECS[m].mode == mode for m in moves))


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 리포트를 JSON으로 stdout에 내고, 저장 0건 모드가 있으면 종료 코드 1."""
    corpus_root = _repo_root() / "data" / "corpus"
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_variants",
        description=(
            "변형 3종 발화(PB-09) — 난이도 계열·조건변형·역문제를 계보(problem_relation + "
            "VARIANT_* generation_type)와 함께 낳는다(결정론·LLM 0·DB 0). 코퍼스를 커밋하지 않는다."
        ),
    )
    parser.add_argument(
        "--in",
        dest="in_paths",
        type=Path,
        action="append",
        default=None,
        help=f"부모 코퍼스 JSONL(반복 가능·기본 {_DEFAULT_PARENT_CORPUS}).",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        type=Path,
        required=True,
        help="산출 JSONL 경로(필수 — data/corpus 편입은 별도 결정이라 기본 경로가 없다).",
    )
    parser.add_argument(
        "--moves",
        nargs="+",
        choices=MOVES,
        default=list(MOVES),
        help="시도할 이동(기본 5종 전부).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="파일을 쓰지 않고 리포트만 낸다(작동률 측정용)."
    )
    args = parser.parse_args(argv)

    parent_paths = args.in_paths or [corpus_root / _DEFAULT_PARENT_CORPUS / "problems.jsonl"]
    signature_paths = sorted(corpus_root.glob("problem_bank_*/problems.jsonl"))
    if not signature_paths:
        # 스캔 0건은 실패다 — 시드 없는 dedup은 "중복 없음"으로 위장한다.
        sys.stderr.write("signature 시드 코퍼스를 하나도 찾지 못했다(data/corpus 확인).\n")
        return 3
    missing = [str(p) for p in parent_paths if not p.exists()]
    if missing:
        sys.stderr.write(f"부모 코퍼스 부재: {missing}\n")
        return 3

    moves: tuple[VariantMove, ...] = tuple(args.moves)
    report = run_corpus_variants(
        parent_paths=parent_paths,
        signature_paths=signature_paths,
        out_path=args.out_path,
        moves=moves,
        write=not args.dry_run,
    )
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    silent = report.silent_modes(_requested_modes(moves))
    if silent:
        sys.stderr.write(f"저장 0건 모드(부착됐으나 무작동): {silent}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
