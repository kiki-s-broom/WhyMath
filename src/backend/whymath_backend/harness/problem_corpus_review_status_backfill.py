"""검수 상태(`review_status`) 백필 후처리 CLI — 코퍼스 JSONL 제자리 갱신(PB-03).

`problem_bank_gap_review_r2.md`가 규약한 노출 4단(①게이트 통과 → ②코퍼스 편입 → ③노출
적격(`is_exposable`+검수) → ④실노출) 중 ③단의 *검수 절반*이 실제 코드에 빠져 있었다 —
`review_status`가 전 레코드 `None`이라 `l6._shared.is_review_cleared`(PB-03 신설)가 fail-closed로
전건을 차단하는 상태였다. 이 CLI는 그 공백을 메운다.

`problem_corpus_persona_fit_backfill.py`(S3-10/PB-01)를 구조 선례로 삼되, 판정 단위가
**레코드별**(persona_fit)이 아니라 **코퍼스별**(review_status)이라는 점이 다르다 — 코퍼스
전체에 대해 `harness/corpus_audit_eval.py`(`load_audit`·`summarize`, 단일 권위)가 이미 존재하는
감사 라벨 표본을 근거로 *하나의* 판정을 내리고, 그 판정을 코퍼스 내 미평가 레코드 전원에게
적용한다. **각인되는 값은 사람 인상이 아니라 `corpus_audit_eval`의 측정 판정만이다**(사람 입력
경로 0 — CLAUDE.md "PIPA·검수" 절 정신과 동형).

판정 규칙(코퍼스당 1회):
  - 감사 라벨 파일이 없으면 → `pending`(미평가 고정 — `probability_finite_v0`·`problem_bank_v1`).
  - 있으면 `summarize(labels)`의 `report.n < 200`이면 → `pending`(증거 부족).
  - 아니면 `report.defect_rate_upper_bound(0.95) <= 0.02`면 → `approved`, 아니면 → `rejected`.

바이트 계약(결정론·비날조·비파괴, persona_fit 백필과 동형):
  - `review_status`가 **이미 채워진**(pending/approved/rejected 어느 값이든) 레코드는 손대지
    않는다(원문 줄 바이트 그대로) — 수동 재검수 결과를 조용히 덮어쓰지 않는다.
  - 비어 있는(`None`/키 부재) 레코드만 `review_status` 한 키를 코퍼스 판정값으로 채운다.
  - 2회 실행은 바이트 동일(멱등) — 첫 실행이 값을 채우므로 두 번째는 전건 원문 통과.
  - 채운 레코드마다 코퍼스 판정 근거(표본 n·결함수·Wilson 상한·감사 라벨 경로)를 감사 JSONL
    1줄로 남긴다.

사용법:
    python -m whymath_backend.harness.problem_corpus_review_status_backfill \\
        --in <src.jsonl> --corpus <corpus_key> [--out <dst.jsonl>] [--audit-out <audit.jsonl>] \\
        [--dry-run | --check]

    python -m whymath_backend.harness.problem_corpus_review_status_backfill --all
        (코퍼스 8종 전부를 제자리 갱신 — `KNOWN_CORPORA` 경로 고정, `AUDIT_LABEL_MAP`으로 판정)

    python -m whymath_backend.harness.problem_corpus_review_status_backfill --all --check
        (CI 드리프트 가드 — 아무것도 쓰지 않고, 미백필 레코드가 1건이라도 있으면 exit 1)

`--out` 생략 시 제자리 갱신(--in 덮어쓰기). `--audit-out` 생략 시
`docs/data/review_status_backfill_audit/<코퍼스 디렉터리명>.jsonl`에 쓴다.

세 실행 모드(OPS-24):
  - **기본**(플래그 없음) — 제자리 갱신(변이형). 사람이 돌리고 결과를 커밋한다.
  - `--dry-run` — 파일·감사로그 미기록·통계만 출력. **채울 게 있든 없든 항상 exit 0**이라
    게이트로 쓸 수 없다(관측용).
  - `--check` — 파일·감사로그 미기록(`--dry-run`과 동일하게 write 경로에 진입하지 않는다)이되,
    채울 레코드가 **1건이라도 있으면 exit 1**·0건이면 exit 0. 판정 규칙·임계값·바이트 계약은
    `--dry-run`과 완전히 동일하고 *종료 코드만* 다르다.

CI 배선 판정(OPS-24 — 왜 `--check`인가):
  ① 이 CLI는 "일회성 운영자 스크립트라 의도적 미배선"이 **아니다**. `review_status`가 빈 채로
     남은 레코드가 생기면 `l6/_shared.py`의 `is_review_cleared`가 fail-closed로 그 문항의
     **노출을 전건 차단**한다 — 즉 백필 누락은 서빙 영향을 갖는 회귀이므로 CI가 지켜야 한다.
  ② 그럼에도 CI에 거는 것은 *변이형*(제자리 갱신)이 아니라 **드리프트 가드**(`--check`)다 —
     CI가 레포 데이터를 재작성해서는 안 된다. 백필 자체는 사람이 돌려 커밋하고, CI는 "빠진 게
     있다"만 빨갛게 알린다.

적용 대상(EOS-136 — 계약 정본 `docs/standards/review_status_stamping_contract.md`):
  이 CLI의 대상은 **고정 코퍼스**(`KNOWN_CORPORA`)뿐이다. 코퍼스 판정은 그 코퍼스의 감사 라벨
  표본에서 나온 것이라 다른 코퍼스에 옮기면 **근거 차용**이 된다 — 아무도 보지 않은 문항이
  `approved`로 노출 가능해진다. 그래서 `harness/review_status_domains.corpus_backfill_refusal`이
  ⑴ 축적 CLI의 **회차 코퍼스**(회차 대장 사이드카 실재 — 그 review_status는 사람 판정 각인 도구
  `review_status_verdict_bridge`가 쓴다) ⑵ 코퍼스 키와 다른 고정 코퍼스·레포 `data/corpus/` 아래
  다른 코퍼스를 **거부(exit 2 · 무기록)** 한다. `--all`의 대상 전건에도 같은 검사를 거는 이유:
  누군가 회차 코퍼스를 `KNOWN_CORPORA`에 등재하면 CI 드리프트 가드가 그것을 "미백필"로 읽고
  코퍼스 단위 각인을 권하는 대신 **계약 위반으로 빨개져야** 한다(그 뒤에는 사람 판정이 영영
  각인될 수 없다 — 먼저 채운 쪽이 이기는 불가침 규칙 때문에).

exit 코드: 0 = 정상(기본·`--dry-run`) 또는 `--check`에서 미백필 0건 · 1 = `--check`에서 미백필
1건 이상 · 2 = 적용 대상 위반(회차 코퍼스·근거 차용·사이드카 확인 불가 — 아무것도 쓰지 않는다).

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — persona_fit 백필 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from whymath_backend.harness.corpus_audit_eval import load_audit, summarize
from whymath_backend.harness.problem_corpus_persona_fit_backfill import (
    KNOWN_CORPORA,
)
from whymath_backend.harness.review_status_domains import corpus_backfill_refusal
from whymath_backend.schema.enums import ReviewStatus

__all__ = [
    "AUDIT_LABEL_MAP",
    "KNOWN_CORPORA",
    "CorpusVerdict",
    "ReviewStatusBackfillReport",
    "compute_corpus_verdict",
    "main",
    "run_review_status_backfill",
    "verdict_from_audit_labels",
]

# 코퍼스↔감사 라벨 파일 매핑(레포 루트 기준, `docs/data/`) — 전부 기존 실존 파일(새로 만들지
# 않는다). 값이 `None`인 코퍼스는 감사 라벨이 없어 *평가하지 않고* pending 고정이다.
#
# `generated_v0` → `corpus_audit_240.jsonl`(파일명이 코퍼스명과 다른 이유: 그 감사가 S1 시절
# 240건 표본으로 먼저 존재했고 이후 코퍼스명이 `generated_v0`로 정착했다 — 파일명 변경은 이
# 태스크 범위 밖).
# `rephrased_v0` → `_census`(표본 rotation-2가 아니라 *전수 감사* 파일이 정본 — 표본은 이미
# 폐기된 이전 판정, PB-03 지시 그대로).
AUDIT_LABEL_MAP: dict[str, Path | None] = {
    "conceptual_v0": Path("docs/data/corpus_audit_conceptual_v0.jsonl"),
    "generated_v0": Path("docs/data/corpus_audit_240.jsonl"),
    "misconception_mc_v0": Path("docs/data/corpus_audit_mc_v0_r2.jsonl"),
    "rephrased_v0": Path("docs/data/corpus_audit_rephrased_v0_census.jsonl"),
    "killer_v0": Path("docs/data/corpus_audit_killer_v0.jsonl"),
    # 5회차 S5 감사(자격 통과 프로토콜 = 기계 ∪ 판정자 A ∪ B)의 504건 전수 라벨 — 결함 1건.
    # 승인의 정본 근거는 검출률로 보정한 S5 상한(0.01151 ≤ 0.02, `bank_audit_r5/README.md`)이고,
    # 이 파일은 그 합집합 라벨을 코퍼스 단위 백필 형식으로 옮긴 것이다
    # (보정 없는 Wilson 상한 0.0088).
    "p3_calculus1_diff_v0": Path("docs/data/corpus_audit_p3_calculus1_diff_v0.jsonl"),
    # 감사 라벨 없음 — 미평가 고정(pending). 신규 감사는 범위 밖.
    "probability_finite_v0": None,
    "v1": None,  # KNOWN_CORPORA의 "v1" = problem_bank_v1(4건). 감사 라벨 없음 — pending 고정.
}

_MIN_N = 200
_MAX_DEFECT_UPPER = 0.02
_CONFIDENCE = 0.95

_AUDIT_DIR = Path("docs/data/review_status_backfill_audit")


@dataclass(frozen=True, slots=True)
class CorpusVerdict:
    """코퍼스 1건에 대한 검수 판정 — 근거(표본 n·결함수·Wilson 상한) 동반(조용한 판정 금지)."""

    review_status: ReviewStatus
    reason: str
    n: int | None
    defects: int | None
    upper_bound: float | None
    label_path: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "review_status": self.review_status.value,
            "reason": self.reason,
            "n": self.n,
            "defects": self.defects,
            "upper_bound": self.upper_bound,
            "label_path": self.label_path,
        }


def verdict_from_audit_labels(
    labels_text: str | None, *, label_path: str | None = None
) -> CorpusVerdict:
    """감사 라벨 JSONL 텍스트(또는 부재)로부터 코퍼스 검수 판정을 낸다(순수 함수).

    `labels_text`가 `None`이면(감사 라벨 파일 자체가 없는 코퍼스) 평가를 시도하지 않고
    `pending` 고정 — "라벨 없음 = approved 아님"을 fail-closed로 보장한다. 판정 규칙은 모듈
    docstring 참조(§ 판정 규칙).
    """
    if labels_text is None:
        return CorpusVerdict(
            review_status=ReviewStatus.pending,
            reason="감사 라벨 파일 없음 — 평가하지 않고 pending 고정(증거 부재)",
            n=None,
            defects=None,
            upper_bound=None,
            label_path=label_path,
        )
    audit = load_audit(labels_text)
    report = summarize(audit.labels)
    if report.n < _MIN_N:
        return CorpusVerdict(
            review_status=ReviewStatus.pending,
            reason=f"표본 n={report.n} < min_n {_MIN_N}(증거 부족 — 해금 불가)",
            n=report.n,
            defects=report.defects,
            upper_bound=None,
            label_path=label_path,
        )
    upper = report.defect_rate_upper_bound(_CONFIDENCE)
    if upper is not None and upper <= _MAX_DEFECT_UPPER:
        return CorpusVerdict(
            review_status=ReviewStatus.approved,
            reason=(
                f"결함율 {int(_CONFIDENCE * 100)}% Wilson 상한 {upper:.4f} <= {_MAX_DEFECT_UPPER}"
            ),
            n=report.n,
            defects=report.defects,
            upper_bound=upper,
            label_path=label_path,
        )
    return CorpusVerdict(
        review_status=ReviewStatus.rejected,
        reason=(
            f"결함율 {int(_CONFIDENCE * 100)}% Wilson 상한 "
            f"{'n/a' if upper is None else f'{upper:.4f}'} > {_MAX_DEFECT_UPPER}(전수 검수 복귀)"
        ),
        n=report.n,
        defects=report.defects,
        upper_bound=upper,
        label_path=label_path,
    )


def compute_corpus_verdict(corpus_key: str) -> CorpusVerdict:
    """`AUDIT_LABEL_MAP`에서 코퍼스 키의 감사 라벨 경로를 읽어 판정한다(I/O 포함).

    Args:
      corpus_key: `AUDIT_LABEL_MAP`(= `KNOWN_CORPORA`와 동일 키 집합)의 코퍼스 키.

    Raises:
      KeyError: 알려지지 않은 코퍼스 키(오타 방지 — 조용히 pending 처리하지 않는다).
    """
    if corpus_key not in AUDIT_LABEL_MAP:
        raise KeyError(
            f"알 수 없는 코퍼스 키: {corpus_key!r}(AUDIT_LABEL_MAP={sorted(AUDIT_LABEL_MAP)})"
        )
    label_path = AUDIT_LABEL_MAP[corpus_key]
    if label_path is None:
        return verdict_from_audit_labels(None, label_path=None)
    text = label_path.read_text(encoding="utf-8")
    return verdict_from_audit_labels(text, label_path=str(label_path))


@dataclass(frozen=True, slots=True)
class ReviewStatusBackfillReport:
    """백필 리포트 — 총량·채움·기보유·적용 판정(조용한 실패 금지)."""

    total: int
    filled: int
    already_set: int
    review_status: str
    verdict_reason: str
    written: int | None = None
    audit_written: int | None = None
    in_path: str = ""
    out_path: str = ""
    audit_path: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "filled": self.filled,
            "already_set": self.already_set,
            "review_status": self.review_status,
            "verdict_reason": self.verdict_reason,
            "written": self.written,
            "audit_written": self.audit_written,
            "in_path": self.in_path,
            "out_path": self.out_path,
            "audit_path": self.audit_path,
        }


def _backfill_line(stripped: str, review_status: ReviewStatus) -> tuple[str, dict[str, Any] | None]:
    """JSONL 한 줄을 백필 — (산출 줄, 감사 항목 또는 None(무변경)) 반환.

    `review_status`가 이미 채워져 있으면(pending/approved/rejected 어느 값이든) 원문 줄 그대로
    (바이트 보존·수동 재검수 존중). 비어 있으면(`None`/키 부재) 코퍼스 판정값 한 키만 채운다.
    """
    data: dict[str, Any] = json.loads(stripped)
    current = data.get("review_status")
    if current:
        return stripped, None  # 무변경 — 이미 채워짐(수동 재검수 등)을 덮어쓰지 않는다.

    updated = dict(data)
    updated["review_status"] = review_status.value
    out_line = json.dumps(updated, ensure_ascii=False)

    audit_entry = {
        "problem_id": data.get("problem_id"),
        "slug": data.get("slug"),
        "review_status": review_status.value,
    }
    return out_line, audit_entry


def run_review_status_backfill(
    *,
    in_path: Path,
    out_path: Path,
    audit_path: Path,
    verdict: CorpusVerdict,
    write: bool = True,
) -> ReviewStatusBackfillReport:
    """코퍼스 JSONL 전 레코드에 검수 판정을 백필 — 이미 채워진 레코드는 바이트 무변경·멱등.

    빈 줄은 건너뛴다(populate 로더·persona_fit 백필과 동일 관대함).
    """
    text = in_path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    audit_entries: list[dict[str, Any]] = []
    total = 0
    filled = 0
    already_set = 0

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        out_line, audit_entry = _backfill_line(stripped, verdict.review_status)
        if audit_entry is None:
            already_set += 1
        else:
            filled += 1
            audit_entries.append(audit_entry)
        out_lines.append(out_line)

    written: int | None = None
    audit_written: int | None = None
    if write:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(out_lines) + "\n" if out_lines else "", encoding="utf-8")
        written = len(out_lines)
        if audit_entries:
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_text = "\n".join(json.dumps(entry, ensure_ascii=False) for entry in audit_entries)
            audit_path.write_text(audit_text + "\n", encoding="utf-8")
            audit_written = len(audit_entries)

    return ReviewStatusBackfillReport(
        total=total,
        filled=filled,
        already_set=already_set,
        review_status=verdict.review_status.value,
        verdict_reason=verdict.reason,
        written=written,
        audit_written=audit_written,
        in_path=str(in_path),
        out_path=str(out_path),
        audit_path=str(audit_path),
    )


def _default_audit_path(in_path: Path) -> Path:
    """감사 경로 기본값 — 코퍼스 디렉터리명 기준(레포 루트 상대, persona_fit 백필 관례와 동일)."""
    return _AUDIT_DIR / f"{in_path.parent.name}.jsonl"


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 백필 후 리포트를 JSON으로 stdout에 낸다(결정론·멱등).

    `--all`이면 `KNOWN_CORPORA` 8종을 순회해 각 코퍼스의 `AUDIT_LABEL_MAP` 판정을 적용한다.
    단일 파일 처리는 `--in`(+ 필수 `--corpus`, 선택 `--out`/`--audit-out`)을 쓴다. 레포 루트에서
    실행 전제(상대경로 규약).

    Returns:
      적용 대상 위반(회차 코퍼스·근거 차용·사이드카 확인 불가)이면 2(무기록), `--check`에서
      미백필 레코드가 1건 이상이면 1, 그 밖에는 0(기본·`--dry-run`은 항상 0).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_review_status_backfill",
        description=(
            "검수 상태(review_status) 백필(PB-03) — 코퍼스 JSONL의 빈 review_status만 "
            "corpus_audit_eval 측정 판정으로 채운다(review_status 외 바이트 무변경·멱등·비날조)."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--in", dest="in_path", type=Path, help="입력 JSONL 경로(단일 파일).")
    group.add_argument(
        "--all", action="store_true", help=f"코퍼스 {len(KNOWN_CORPORA)}종 전부 제자리 갱신."
    )
    parser.add_argument(
        "--corpus",
        dest="corpus_key",
        type=str,
        default=None,
        help=f"--in과 함께 지정하는 코퍼스 키({sorted(AUDIT_LABEL_MAP)}) — 판정 근거 조회용.",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        type=Path,
        default=None,
        help="산출 JSONL 경로(생략 시 --in 제자리 갱신). --all과 함께 쓸 수 없다.",
    )
    parser.add_argument(
        "--audit-out",
        dest="audit_path",
        type=Path,
        default=None,
        help="감사 JSONL 경로(생략 시 docs/data/review_status_backfill_audit/<코퍼스명>.jsonl).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="파일 미기록 — 통계만 출력(항상 exit 0·관측용)."
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="드리프트 가드(OPS-24) — 파일 미기록, 미백필 레코드가 1건이라도 있으면 exit 1.",
    )
    args = parser.parse_args(argv)

    if args.all and args.out_path is not None:
        parser.error("--all과 --out은 함께 쓸 수 없다(경로가 7개로 정해져 있다).")
    if not args.all and args.corpus_key is None:
        parser.error("--in 사용 시 --corpus 필수(코퍼스별 감사 라벨 매핑 조회에 필요).")

    targets: list[tuple[str, Path]] = (
        list(KNOWN_CORPORA.items()) if args.all else [(args.corpus_key, args.in_path)]
    )
    # 적용 대상 검사(EOS-136) — 판정·쓰기 **전에** 전건을 본다. 한 건이라도 위반이면 아무것도
    # 쓰지 않는다(일부만 각인된 코퍼스가 남으면 어느 쪽이 정본인지 사람이 가려야 한다).
    refusals = [
        refusal
        for corpus_key, in_path in targets
        if (refusal := corpus_backfill_refusal(in_path, corpus_key)) is not None
    ]
    if refusals:
        for refusal in refusals:
            sys.stderr.write(f"[적용 대상 위반] {refusal}\n")
        sys.stderr.write("아무것도 쓰지 않았다(exit 2).\n")
        return 2
    reports = []
    for corpus_key, in_path in targets:
        verdict = compute_corpus_verdict(corpus_key)
        out_path = args.out_path if args.out_path is not None else in_path
        audit_path = (
            args.audit_path if args.audit_path is not None else _default_audit_path(in_path)
        )
        reports.append(
            run_review_status_backfill(
                in_path=in_path,
                out_path=out_path,
                audit_path=audit_path,
                verdict=verdict,
                write=not (args.dry_run or args.check),
            )
        )

    payload: Any = [r.to_json() for r in reports] if args.all else reports[0].to_json()
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if args.check:
        return _check_exit_code(reports)
    return 0


def _check_exit_code(reports: list[ReviewStatusBackfillReport]) -> int:
    """`--check` 판정 — 미백필 레코드가 남아 있으면 1(무엇이 왜 남았는지 stderr에 명시).

    조용히 exit 1만 내지 않는다(침묵 실패 금지) — 코퍼스 경로·잔여 건수·적용될 판정을 함께
    적어 사람이 바로 백필 명령을 돌릴 수 있게 한다.
    """
    pending = [r for r in reports if r.filled > 0]
    if not pending:
        return 0
    for report in pending:
        sys.stderr.write(
            f"[check] review_status 미백필 {report.filled}건 / 총 {report.total}건 — "
            f"{report.in_path} (적용될 판정: {report.review_status} — {report.verdict_reason})\n"
        )
    sys.stderr.write(
        "드리프트 감지: review_status가 빈 레코드는 l6 is_review_cleared가 fail-closed로 노출을 "
        "차단한다. `--check` 없이 같은 명령을 돌려 백필하고 결과를 커밋하라.\n"
    )
    return 1


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
