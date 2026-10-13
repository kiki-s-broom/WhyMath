"""문제 유형(`problem_type_codes`) 결정론 백필 CLI (S3-27·LLM 0).

`problem_corpus_tag.py`(시그니처 재태깅)와 정확히 같은 **바이트 계약**을 따른다 — 유도 결과가
기존 `problem_type_codes`와 같은 레코드는 원문 줄 바이트 그대로 통과하고, 다른 레코드만 그 한
키를 교체해 재직렬화한다(`json.dumps(..., ensure_ascii=False)`). 2회 실행은 바이트 동일(멱등).

분류 자체(생성기 identity → 유형)는 `problem_type_mapping.classify_record`가 갖고 있다 — 이
CLI는 그 표를 코퍼스 파일들에 적용하는 얇은 조성 층일 뿐이다(harness는 import-linter 계약 밖
— `problem_corpus_batch`·`problem_corpus_tag` 선례와 동형).

**대상 코퍼스(결정론 순서)** — 세 축이다:
  1. **직접 분류** `problem_type_mapping.TARGET_CORPORA` 36종(S3-27 원본 6종 + CONT-09가 편입한
     `unit_codes` 표 30종) — 생성기 identity가 레코드 자체에 남아 `classify_record` 단독으로 분류.
  2. **계보 분류** `problem_type_mapping.LINEAGE_CORPORA`(`problem_bank_rephrased_v0` 421건)
     — 직접 6종을 먼저 처리하며 구축한 부모 색인(slug → 유도 유형)으로 `relations`의 "변형"
     계보(`parent_slug`)를 따라가 원 생성기(부모)의 유형을 승계(`classify_rephrased_record`).
     계보로도 추적 불가한 레코드는 미태깅으로 남고 리포트 `untagged`가 정직하게 센다
     (침묵 누락 금지). 구 "S4-14 미착지" 명시 제외는 사유 소멸(S4-14/S4-18 done·계보
     421/421 실측)로 `PB-07`이 해제했다 — `docs/architecture/problem_bank_gap_review_r3.md`
     §3 G2.
  3. **자가 태깅(읽기 전용)** `problem_type_mapping.SELF_TAGGED_CORPORA` — 생성 시점에 레코드별
     유형을 직접 기록하는 코퍼스(`problem_bank_p3_calculus1_diff_v0`). 같은 `unit_codes` 안에서도
     유형이 갈려 표로 분류할 수 없으므로 **백필이 쓰지 않는다**(쓰면 저장된 유형이 지워진다).
     리포트에는 총량·태깅·미태깅만 읽어 정직하게 싣는다(`self_tagged` 절).

제외 좌석(`problem_type_mapping.EXCLUDED_CORPORA`)은 현재 비어 있으나 리포트의 `excluded` 절
(정직 회계)은 유지한다 — 향후 항목이 다시 생기면 만료 계약(`ExclusionEntry`·task_id 필수)과
함께만 등재된다.

사용법:
    python -m whymath_backend.harness.problem_type_backfill \\
        [--corpus-root <dir>] [--dry-run]

리포트는 JSON(코퍼스별 총량·태깅·미태깅·변경 행 수 + 제외 코퍼스 총량) — exit 0 고정(관측·백필
CLI라 게이트가 아니다 — 미태깅 존재 자체가 정상 상태일 수 있어 `problem_bank_coverage`처럼 exit
코드로 판정하지 않는다. 파싱 불가 라인은 예외로 즉시 실패해 조용한 통과를 막는다).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whymath_backend.harness.problem_type_mapping import (
    EXCLUDED_CORPORA,
    LINEAGE_CORPORA,
    SELF_TAGGED_CORPORA,
    TARGET_CORPORA,
    classify_record,
    classify_rephrased_record,
)

__all__ = [
    "CORPUS_FILE_NAME",
    "CorpusBackfillReport",
    "TypeBackfillReport",
    "main",
    "run_backfill",
]

# harness→whymath_backend→backend→src→repo 루트(다른 harness 모듈과 동일 관례).
_REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CORPUS_ROOT = _REPO_ROOT / "data" / "corpus"
CORPUS_FILE_NAME = "problems.jsonl"


@dataclass(frozen=True, slots=True)
class CorpusBackfillReport:
    """코퍼스 1종의 백필 결과 — 총량·태깅·미태깅·변경 행 수(조용한 실패 금지)."""

    name: str
    total: int
    tagged: int
    changed: int
    written: int | None
    # 유도값이 빈 리스트인데 저장분이 비어 있지 않아 **지우지 않고 보존한** 행 수 — 표에 없는
    # `unit_codes`(신규 밴드 등)에 누군가 올바른 태그를 달아 둔 경우다. 침묵 삭제 대신 센다.
    preserved: int = 0

    @property
    def untagged(self) -> int:
        return self.total - self.tagged

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "tagged": self.tagged,
            "untagged": self.untagged,
            "changed": self.changed,
            "written": self.written,
            "preserved": self.preserved,
        }


@dataclass(frozen=True, slots=True)
class TypeBackfillReport:
    """배치 전체 리포트 — 대상(직접 6 + 계보 1) 코퍼스별 결과 + 제외 좌석의 정직 회계.

    `excluded_corpora`는 PB-07 해제 후 현재 빈 튜플이지만 필드는 유지한다 — 제외 좌석
    (`EXCLUDED_CORPORA`)에 항목이 다시 생기면 회계가 자동으로 되살아난다(침묵 누락 금지).
    """

    corpora: tuple[CorpusBackfillReport, ...]
    excluded_corpora: tuple[str, ...]
    excluded_total: int
    # 자가 태깅 코퍼스의 읽기 전용 회계(`changed`·`written`은 항상 0·None) — 기본값 빈 튜플은
    # 이 필드 도입 전 호출처(테스트의 직접 생성)를 깨지 않기 위함이다.
    self_tagged: tuple[CorpusBackfillReport, ...] = ()

    @property
    def total_target(self) -> int:
        return sum(c.total for c in self.corpora)

    @property
    def total_tagged(self) -> int:
        return sum(c.tagged for c in self.corpora)

    @property
    def total_untagged_in_target(self) -> int:
        return sum(c.untagged for c in self.corpora)

    @property
    def total_self_tagged(self) -> int:
        return sum(c.total for c in self.self_tagged)

    @property
    def untagged_self_tagged(self) -> int:
        """자가 태깅 코퍼스인데 저장된 유형이 비어 있는 행 수 — 0이어야 정상(테스트가 동결)."""
        return sum(c.untagged for c in self.self_tagged)

    @property
    def grand_total(self) -> int:
        """대상 + 자가 태깅 + 제외 코퍼스를 합친 전체 코퍼스 행 수(정직 회계 — 스캔 전체와 정합
        확인용. 2,647→2,638은 QUAL-02(#777) 실중복 9건 은퇴)."""
        return self.total_target + self.total_self_tagged + self.excluded_total

    def to_json(self) -> dict[str, Any]:
        return {
            "corpora": [c.to_json() for c in self.corpora],
            "excluded_corpora": list(self.excluded_corpora),
            "excluded_total": self.excluded_total,
            "total_target": self.total_target,
            "total_tagged": self.total_tagged,
            "total_untagged_in_target": self.total_untagged_in_target,
            "self_tagged": [c.to_json() for c in self.self_tagged],
            "total_self_tagged": self.total_self_tagged,
            "untagged_self_tagged": self.untagged_self_tagged,
            "grand_total": self.grand_total,
        }


def _retag_line(
    stripped: str,
    *,
    corpus_name: str,
    parent_types: Mapping[str, list[str]] | None = None,
) -> tuple[str, list[str], bool]:
    """JSONL 한 줄을 재분류 — (산출 줄, 결과 `problem_type_codes`, 보존 여부) 반환.

    `problem_corpus_tag._retag_line`과 동일 패턴: 유도 결과가 기존과 같으면 원문 줄 그대로
    (바이트 보존), 다르면 `problem_type_codes` 한 키만 교체해 재직렬화한다.
    `parent_types`가 주어지면 계보 분류 코퍼스로 취급해 부모 유형을 승계한다
    (`classify_rephrased_record`), 아니면 직접 분류(`classify_record`).
    """
    data: dict[str, Any] = json.loads(stripped)
    if parent_types is not None:
        derived = classify_rephrased_record(data, parent_types)
    else:
        derived = classify_record(corpus_name, data)

    current_raw = data.get("problem_type_codes", [])
    current = [str(v) for v in current_raw] if isinstance(current_raw, list) else []
    if derived == current:
        return stripped, derived, False  # 무변경 — 원문 바이트 그대로.
    if not derived and current:
        # 표가 모르는 행(유도 빈 리스트)에서 저장된 태그를 빈 리스트로 덮어쓰지 않는다 — 백필이
        # 데이터를 지우는 도구가 되면 안 된다. 원문 그대로 두고 호출자가 `preserved`로 센다.
        return stripped, current, True
    updated = dict(data)
    updated["problem_type_codes"] = derived
    return json.dumps(updated, ensure_ascii=False), derived, False


def _backfill_corpus_file(
    path: Path,
    *,
    name: str,
    write: bool,
    parent_types: Mapping[str, list[str]] | None = None,
) -> CorpusBackfillReport:
    """코퍼스 JSONL 1개 백필 — 파일 부재는 0건(코퍼스 존재는 `problem_bank_coverage` 소관)."""
    if not path.is_file():
        return CorpusBackfillReport(name=name, total=0, tagged=0, changed=0, written=None)

    text = path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    total = 0
    changed = 0
    tagged = 0
    preserved = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        out_line, derived, kept = _retag_line(stripped, corpus_name=name, parent_types=parent_types)
        if out_line != stripped:
            changed += 1
        if derived:
            tagged += 1
        if kept:
            preserved += 1
        out_lines.append(out_line)

    written: int | None = None
    if write:
        path.write_text("\n".join(out_lines) + "\n" if out_lines else "", encoding="utf-8")
        written = len(out_lines)
    return CorpusBackfillReport(
        name=name,
        total=total,
        tagged=tagged,
        changed=changed,
        written=written,
        preserved=preserved,
    )


def _read_only_report(path: Path, *, name: str) -> CorpusBackfillReport:
    """자가 태깅 코퍼스 1개의 읽기 전용 회계 — 파일을 **절대 쓰지 않고** 저장된 유형만 센다.

    파싱 불가 줄은 `json.loads`가 예외로 즉시 실패시킨다(조용한 통과 금지 — 다른 백필 경로와 동일).
    """
    if not path.is_file():
        return CorpusBackfillReport(name=name, total=0, tagged=0, changed=0, written=None)
    total = 0
    tagged = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        data: dict[str, Any] = json.loads(stripped)
        codes = data.get("problem_type_codes")
        if isinstance(codes, list) and codes:
            tagged += 1
    return CorpusBackfillReport(name=name, total=total, tagged=tagged, changed=0, written=None)


def _count_lines(path: Path) -> int:
    """비어있지 않은 JSONL 줄 수(정직 회계용 — 파싱 없이 존재량만 센다)."""
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _build_parent_type_index(root: Path) -> dict[str, list[str]]:
    """직접 분류 대상(`TARGET_CORPORA`) 전 레코드의 slug → 유도 유형 색인(계보 분류 입력).

    파일에 *저장된* 값이 아니라 `classify_record` **유도** 값을 쓴다 — 유형의 단일 진실
    원천은 매핑표이고, 부모 파일의 백필 기록 여부와 무관하게 색인이 동일해 결정론이 유지된다.
    slug가 중복되면(같은 코퍼스 안이든 코퍼스 간이든) 어느 부모인지 확정할 수 없으므로
    색인에서 제거한다 — 그 부모를 가리키는 자식은 미태깅으로 남고 리포트가 정직하게 센다
    (침묵 오분류 금지. 2026-08-11 실측: 실 코퍼스 6종에 중복 slug 0건).
    """
    index: dict[str, list[str]] = {}
    ambiguous: set[str] = set()
    for name in TARGET_CORPORA:
        path = root / name / CORPUS_FILE_NAME
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            data: dict[str, Any] = json.loads(stripped)
            slug = data.get("slug")
            if not isinstance(slug, str):
                continue
            if slug in ambiguous:
                continue
            if slug in index:
                ambiguous.add(slug)
                del index[slug]
                continue
            index[slug] = classify_record(name, data)
    return index


def run_backfill(*, corpus_root: Path | None = None, write: bool = True) -> TypeBackfillReport:
    """직접 분류(`TARGET_CORPORA`) + 계보 분류 1종(rephrased) 백필 + 자가 태깅·제외 좌석의
    정직 회계(순수 결정론).

    순서 계약: 직접 분류 코퍼스를 먼저 처리하고, 부모 색인(`_build_parent_type_index`)을 구축한 뒤
    계보 코퍼스를 처리한다. 색인은 유도 값 기반이라 직접 코퍼스의 기록(write) 여부와 무관하게
    같은 결과를 낸다(dry-run에서도 계보 통계가 실기록과 동일).
    """
    root = corpus_root if corpus_root is not None else DEFAULT_CORPUS_ROOT
    direct = tuple(
        _backfill_corpus_file(root / name / CORPUS_FILE_NAME, name=name, write=write)
        for name in TARGET_CORPORA
    )
    parent_types = _build_parent_type_index(root)
    lineage = tuple(
        _backfill_corpus_file(
            root / name / CORPUS_FILE_NAME, name=name, write=write, parent_types=parent_types
        )
        for name in LINEAGE_CORPORA
    )
    self_tagged = tuple(
        _read_only_report(root / name / CORPUS_FILE_NAME, name=name) for name in SELF_TAGGED_CORPORA
    )
    excluded = tuple(sorted(EXCLUDED_CORPORA))
    excluded_total = sum(_count_lines(root / name / CORPUS_FILE_NAME) for name in excluded)
    return TypeBackfillReport(
        corpora=direct + lineage,
        excluded_corpora=excluded,
        excluded_total=excluded_total,
        self_tagged=self_tagged,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 백필 리포트를 JSON으로 stdout에 낸다. 게이트가 아니라 exit 0 고정."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_type_backfill",
        description=(
            "문제 유형(problem_type_codes) 결정론 백필(S3-27·PB-07·CONT-09) — 생성기 identity "
            "매핑표로 직접 분류 코퍼스 + 계보(부모 유형 승계)로 rephrased 1종을 재분류한다"
            "(LLM 0·텍스트 파싱 0·바이트 계약·멱등)."
        ),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help=f"코퍼스 루트 디렉터리(기본 {DEFAULT_CORPUS_ROOT}).",
    )
    parser.add_argument("--dry-run", action="store_true", help="파일 미기록 — 통계만 출력.")
    args = parser.parse_args(argv)

    report = run_backfill(corpus_root=args.corpus_root, write=not args.dry_run)
    json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
