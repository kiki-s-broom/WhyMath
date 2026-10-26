"""계보만 걸기 CLI(PB-20) — 중복으로 탈락한 변형 자식을 낳지 않고 기존 문항 사이에 관계만 잇는다.

PB-09(`problem_corpus_variants`)는 자식을 파생한 뒤 구조 signature가 코퍼스에 이미 있으면 저장을
차단한다(`rejected_duplicate/structural_signature`). 그 자식은 *새로 낳을 필요가 없는* 것이지
*가치가 없는* 것이 아니다 — 같은 구조의 문항이 이미 코퍼스에 있으므로, 부모와 그 기존 문항 사이에
`problem_relation`만 걸면 신규 콘텐츠 0으로 계열이 는다.

## 이 모듈이 하는 일

  1. PB-09와 **같은 파생기**(`derive_variants`)로 자식 후보를 낸다 — 파생 로직을 복제하지 않는다.
  2. 후보의 구조 signature를 **시그니처 → 소유 문항** 역인덱스에서 찾는다. PB-09의
     `load_corpus_index`는 signature *집합*만 돌려줘 "어느 문항이 그 구조인가"를 모른다 — 이 모듈이
     새로 만드는 것은 그 역인덱스 하나다.
  3. 소유 문항이 있으면 (부모 → 소유 문항) 관계 후보를 낸다. 관계 유형은 이동이 정한다
     (PB-09와 동일 표).

## 이 모듈이 하지 않는 일 (정직한 경계)

  - **코퍼스 행을 고치지 않는다.** 봉인된 코퍼스(`problem_corpus_batch`의 바이트 동일 재생성 계약)의
    `relations`를 제자리에서 늘리지 않는다. 산출은 `--out` 사이드 JSONL뿐이고 기본 경로가 없다.
  - **DB에 쓰지 않는다.** 사이드 파일을 `problem_relation`으로 적재하는 단계(`populate` 확장)는 후속
    태스크다. 그 전까지 이 산출물은 CAT·공개 카탈로그 어디에도 닿지 않는다.
  - 새 자식을 낳지 않는다 — 구조가 코퍼스에 없는 자식은 `not_structural_duplicate`로 세고
    PB-09 소관으로 둔다.

## 방향·상한 규약 (anti-explosion)

  - 방향은 항상 **부모(코퍼스 문항) → 기존 문항**이다(PB-09 §2와 같다). 유형은 이동이 정한다.
  - 한 쌍(순서 무관)은 한 번만 이어진다 — 코퍼스에 이미 어느 방향·유형으로든 관계가 있으면 건너뛴다.
    같은 쌍에 유형을 덧얹으면 PB-19 정책이 읽는 역할이 모순될 수 있다.
  - 한 문항이 가질 관계 수의 상한은 `MAX_RELATIONS_PER_RECORD`(=10)다. 기존 거버넌스 테스트
    `test_relation_governance.py`의 `_MAX_RELATIONS_PER_RECORD`를 승계하며 값 일치는
    테스트가 동결한다.

## "작동한 비율" 원칙

리포트는 이동마다 **시도 → skip(사유별) → 파생 → 결과별 → 연결** 깔때기를 싣고, 두 항등식
(`attempted == skipped + derived`, `derived == Σ결과`)이 깨지면 `to_json`이 예외를 던진다.
연결 0건이면 exit 1 — 부착됐으나 무작동인 경로가 정상 종료로 보이지 않게 한다. 연결 중 CAT에 닿을
수 있는 쌍(부모·상대 모두 `approved`)도 따로 센다: 그 수가 이 경로의 *실효*다.

사용법:
    python -m whymath_backend.harness.problem_corpus_lineage_links --dry-run
    python -m whymath_backend.harness.problem_corpus_lineage_links --out <links.jsonl>

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_variants 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l1.problem_bank.populate import load_problem_bank_records
from whymath_backend.l3.equivalent.canonicalize import canonical_signature
from whymath_backend.l3.equivalent.variants import (
    MOVES,
    ParentRejection,
    VariantDraft,
    VariantMove,
    derive_variants,
    parse_parent,
)

__all__ = [
    "MAX_RELATIONS_PER_RECORD",
    "LinkCandidate",
    "LinkMoveReport",
    "LinksReport",
    "Owner",
    "SeedIndex",
    "load_seed_index",
    "main",
    "run_lineage_links",
]

_DEFAULT_PARENT_CORPUS = "problem_bank_generated_v0"
_APPROVED = "approved"

# 한 문항(자식 쪽 레코드)이 가질 `relations` 수의 상한 — `tests/backend/l1/problem_bank/
# test_relation_governance.py::_MAX_RELATIONS_PER_RECORD`를 승계한다(값 일치는 PB-20 테스트가 동결).
MAX_RELATIONS_PER_RECORD = 10

# 결과 키 — 상태 이름이 한 곳에서 정의되도록 상수로 둔다(리포트·테스트가 같은 글자를 읽는다).
OUT_LINKED = "linked"
OUT_NOT_DUP = "not_structural_duplicate"
OUT_SELF_ONLY = "owner_is_parent_only"
OUT_PAIR_RELATED = "pair_already_related"
OUT_PAIR_THIS_RUN = "pair_linked_this_run"
OUT_TARGET_CAP = "target_relation_cap"


def _repo_root() -> Path:
    """repo 루트 — harness→whymath_backend→backend→src→repo (problem_corpus_variants 규약)."""
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class Owner:
    """어떤 구조 signature를 가진 기존 문항 1건 — 출처 코퍼스·검수 상태 동반."""

    slug: str
    corpus: str
    review_status: str | None


@dataclass(frozen=True, slots=True)
class SeedIndex:
    """시드 코퍼스에서 뽑은 역인덱스 + 기존 관계 회계.

    `owners`: signature → 그 구조를 가진 문항들(정규화 불가 문항은 키가 없다 — 모르는 것을 같다고
    하지 않는다). `related_pairs`: 기존 관계의 순서 없는 쌍. `relation_counts`: 문항별 기존 관계 수.
    """

    owners: dict[str, list[Owner]]
    related_pairs: frozenset[frozenset[str]]
    relation_counts: dict[str, int]
    review_status: dict[str, str | None]
    total_records: int


def load_seed_index(paths: list[Path]) -> SeedIndex:
    """코퍼스들에서 시그니처→소유 문항 역인덱스와 기존 관계 회계를 만든다(부재 경로는 건너뜀).

    signature 산식은 PB-09 `load_corpus_index`와 같다(`verify.conditions` + `answer_selection`) —
    두 인덱스의 키 집합이 같다는 사실은 테스트가 동결한다(판정 기준 이원화 방지).
    """
    owners: dict[str, list[Owner]] = {}
    pairs: set[frozenset[str]] = set()
    counts: Counter[str] = Counter()
    status: dict[str, str | None] = {}
    total = 0
    for path in paths:
        if not path.exists():
            continue
        corpus = path.parent.name
        for record in load_problem_bank_records(path):
            total += 1
            raw_status = record.problem.review_status
            review = getattr(raw_status, "value", raw_status)
            status[record.slug] = None if review is None else str(review)
            signature = canonical_signature(
                record.verify.conditions, record.verify.answer_selection
            )
            if signature is not None:
                owners.setdefault(signature, []).append(
                    Owner(slug=record.slug, corpus=corpus, review_status=status[record.slug])
                )
            for rel in record.relations:
                pairs.add(frozenset((record.slug, rel.parent_slug)))
                counts[record.slug] += 1
    return SeedIndex(
        owners=owners,
        related_pairs=frozenset(pairs),
        relation_counts=dict(counts),
        review_status=status,
        total_records=total,
    )


@dataclass(frozen=True, slots=True)
class LinkCandidate:
    """연결할 관계 1건 — `target_slug`(기존 문항)의 레코드에 `parent_slug`를 부모로 거는 후보."""

    parent_slug: str
    target_slug: str
    relation_type: str
    move: VariantMove
    target_corpus: str
    parent_review_status: str | None
    target_review_status: str | None
    alternatives: int  # 같은 구조의 다른 소유 문항 수(고른 문항 제외) — 선택의 자의성을 드러낸다.

    @property
    def cat_reachable(self) -> bool:
        """두 끝이 모두 검수 통과여야 CAT 후보 풀(approved 허용목록)에서 이 관계가 쓰인다."""
        return self.parent_review_status == _APPROVED and self.target_review_status == _APPROVED

    def to_json(self) -> dict[str, Any]:
        return {
            "child_slug": self.target_slug,
            "parent_slug": self.parent_slug,
            "relation_type": self.relation_type,
            # 유사도는 추정하지 않는다 — PB-09와 같은 이유(근거 없는 수치를 계보에 날조하지 않는다).
            "similarity_score": None,
            "move": self.move,
            "target_corpus": self.target_corpus,
            "cat_reachable": self.cat_reachable,
            "alternatives": self.alternatives,
        }


@dataclass(slots=True)
class LinkMoveReport:
    """이동 1종의 깔때기 — 시도 → skip → 파생 → 결과 → 연결."""

    move: VariantMove
    attempted: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    derived: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)

    @property
    def linked(self) -> int:
        return self.outcomes.get(OUT_LINKED, 0)

    @property
    def working_rate(self) -> float | None:
        """작동한 비율 = 연결 / 시도. 시도 0이면 None(0.0으로 위장하지 않는다)."""
        return None if self.attempted == 0 else self.linked / self.attempted

    def check_identities(self) -> None:
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


@dataclass(frozen=True, slots=True)
class LinksReport:
    """전체 리포트 — 이동별 깔때기 + 연결 후보 + 상한 회계."""

    parents_total: int
    parents_eligible: int
    moves: list[LinkMoveReport]
    links: list[LinkCandidate]
    max_target_relations_after: int
    written: int | None
    out_path: str | None

    @property
    def attempted_total(self) -> int:
        return sum(m.attempted for m in self.moves)

    @property
    def linked_total(self) -> int:
        return len(self.links)

    @property
    def cat_reachable_total(self) -> int:
        return sum(1 for link in self.links if link.cat_reachable)

    def to_json(self) -> dict[str, Any]:
        for move in self.moves:
            move.check_identities()  # 거짓 리포트를 내느니 터진다.
        if self.linked_total != sum(m.linked for m in self.moves):
            raise AssertionError("linked_total != Σ이동별 연결 — 리포트가 거짓이다")
        return {
            "parents_total": self.parents_total,
            "parents_eligible": self.parents_eligible,
            "attempted_total": self.attempted_total,
            "linked_total": self.linked_total,
            "cat_reachable_total": self.cat_reachable_total,
            "relation_type_counts": dict(
                sorted(Counter(link.relation_type for link in self.links).items())
            ),
            "max_target_relations_after": self.max_target_relations_after,
            "max_relations_per_record": MAX_RELATIONS_PER_RECORD,
            "moves": [
                {
                    "move": m.move,
                    "attempted": m.attempted,
                    "skipped": dict(sorted(m.skipped.items())),
                    "derived": m.derived,
                    "outcomes": dict(sorted(m.outcomes.items())),
                    "linked": m.linked,
                    "working_rate": m.working_rate,
                }
                for m in self.moves
            ],
            "written": self.written,
            "out_path": self.out_path,
        }


def _read_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _draft_signature(draft: VariantDraft) -> str | None:
    """자식 후보의 구조 signature — 오케스트레이터 S2-l 단계와 같은 산식.

    오케스트레이터는 `answer_selection` 없는 집계·개수형에 payload 접두를 붙이는데, 변형 5종은
    근 선택(또는 연립 조건)만 만들어 그 분기를 타지 않는다. 그래도 같은 우선순위를 그대로 쓴다 —
    산식이 갈라지면 "코퍼스에 있다"는 판정이 PB-09와 이 모듈에서 달라진다(테스트가 차분 동결).
    """
    candidate = draft.candidate
    payload = (
        candidate.answer_selection
        or (f"agg:{candidate.answer_aggregate}" if candidate.answer_aggregate else None)
        or (f"kind:{candidate.answer_kind}" if candidate.answer_kind else None)
    )
    return canonical_signature(candidate.conditions, payload)


def _pick_owner(owners: list[Owner], parent_slug: str) -> tuple[Owner, int] | None:
    """부모 자신을 뺀 소유 문항 중 결정론으로 하나 — (고른 문항, 남은 대안 수). 없으면 None.

    우선순위: 검수 통과 → 코퍼스명 → slug. 검수 통과를 앞세우는 이유는 CAT에 닿을 수 있는 쌍을
    먼저 만들기 위해서일 뿐이며, 이 선택이 문항 품질을 판정하지는 않는다.
    """
    candidates = [o for o in owners if o.slug != parent_slug]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o.review_status != _APPROVED, o.corpus, o.slug))
    return candidates[0], len(candidates) - 1


def run_lineage_links(
    *,
    parent_paths: list[Path],
    seed_paths: list[Path],
    out_path: Path | None = None,
    moves: tuple[VariantMove, ...] = MOVES,
    write: bool = True,
) -> LinksReport:
    """부모에서 자식 후보를 파생해, 구조가 기존 문항과 같으면 그 문항으로 가는 관계 후보를 낸다."""
    rows: list[dict[str, Any]] = []
    for path in parent_paths:
        rows.extend(_read_rows(path))
    parents = []
    for row in rows:
        parsed = parse_parent(row)
        if not isinstance(parsed, ParentRejection):
            parents.append(parsed)

    seed = load_seed_index(seed_paths)
    reports: dict[VariantMove, LinkMoveReport] = {m: LinkMoveReport(move=m) for m in moves}
    links: list[LinkCandidate] = []
    pairs_this_run: set[frozenset[str]] = set()
    added_to_target: Counter[str] = Counter()

    for parent in parents:
        for item in derive_variants(parent, moves):
            report = reports[item.move]
            report.attempted += 1
            if not isinstance(item, VariantDraft):
                report.skipped[item.reason] += 1
                continue
            report.derived += 1
            signature = _draft_signature(item)
            owners = seed.owners.get(signature) if signature is not None else None
            if not owners:
                # 구조가 코퍼스에 없다 — 새 문항 후보이므로 PB-09(자식을 낳는 경로) 소관이다.
                report.outcomes[OUT_NOT_DUP] += 1
                continue
            picked = _pick_owner(owners, parent.slug)
            if picked is None:
                report.outcomes[OUT_SELF_ONLY] += 1
                continue
            owner, alternatives = picked
            pair = frozenset((parent.slug, owner.slug))
            if pair in seed.related_pairs:
                report.outcomes[OUT_PAIR_RELATED] += 1
                continue
            if pair in pairs_this_run:
                report.outcomes[OUT_PAIR_THIS_RUN] += 1
                continue
            total_relations = seed.relation_counts.get(owner.slug, 0) + added_to_target[owner.slug]
            if total_relations >= MAX_RELATIONS_PER_RECORD:
                report.outcomes[OUT_TARGET_CAP] += 1
                continue
            pairs_this_run.add(pair)
            added_to_target[owner.slug] += 1
            report.outcomes[OUT_LINKED] += 1
            links.append(
                LinkCandidate(
                    parent_slug=parent.slug,
                    target_slug=owner.slug,
                    relation_type=item.relation_type.value,
                    move=item.move,
                    target_corpus=owner.corpus,
                    parent_review_status=seed.review_status.get(parent.slug),
                    target_review_status=owner.review_status,
                    alternatives=alternatives,
                )
            )

    max_after = max(
        (seed.relation_counts.get(slug, 0) + n for slug, n in added_to_target.items()), default=0
    )
    written: int | None = None
    if write and out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as handle:
            for link in links:
                handle.write(json.dumps(link.to_json(), ensure_ascii=False, sort_keys=True) + "\n")
        written = len(links)
    return LinksReport(
        parents_total=len(rows),
        parents_eligible=len(parents),
        moves=[reports[m] for m in moves],
        links=links,
        max_target_relations_after=max_after,
        written=written,
        out_path=None if out_path is None else str(out_path),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 리포트를 JSON으로 stdout에 내고, 연결 0건이면 종료 코드 1."""
    corpus_root = _repo_root() / "data" / "corpus"
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_lineage_links",
        description=(
            "계보만 걸기(PB-20) — 중복으로 탈락한 변형 자식을 낳지 않고 기존 문항 사이에 "
            "관계 후보만 낸다(결정론·LLM 0·DB 0·코퍼스 미변경)."
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
        default=None,
        help="관계 후보 사이드 JSONL 경로(기본 없음 — data/corpus 안에 두지 않는다).",
    )
    parser.add_argument("--moves", nargs="+", choices=MOVES, default=list(MOVES))
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 리포트만 낸다.")
    args = parser.parse_args(argv)

    parent_paths = args.in_paths or [corpus_root / _DEFAULT_PARENT_CORPUS / "problems.jsonl"]
    seed_paths = sorted(corpus_root.glob("problem_bank_*/problems.jsonl"))
    if not seed_paths:
        # 스캔 0건은 실패다 — 시드 없는 역인덱스는 "중복 없음"으로 위장한다.
        sys.stderr.write("시드 코퍼스를 하나도 찾지 못했다(data/corpus 확인).\n")
        return 3
    missing = [str(p) for p in parent_paths if not p.exists()]
    if missing:
        sys.stderr.write(f"부모 코퍼스 부재: {missing}\n")
        return 3
    if not args.dry_run and args.out_path is None:
        sys.stderr.write("--out 이 필요하다(쓰지 않으려면 --dry-run).\n")
        return 2

    report = run_lineage_links(
        parent_paths=parent_paths,
        seed_paths=seed_paths,
        out_path=args.out_path,
        moves=tuple(args.moves),
        write=not args.dry_run,
    )
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if report.linked_total == 0:
        sys.stderr.write("연결 0건(부착됐으나 무작동).\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
