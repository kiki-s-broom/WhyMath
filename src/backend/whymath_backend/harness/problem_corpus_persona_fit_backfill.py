"""페르소나 적합도(`persona_fit`) 백필 후처리 CLI — 코퍼스 JSONL 제자리 갱신(S3-10).

배치 CLI(`problem_corpus_batch` 등)는 생성 시점에 `persona_fit`을 채우지 않는다(전 2,667건
`{}` — 2026-07-28 실측). 이 CLI는 **배치 밖 사후 백필**로, `l1/problem_bank/persona_fit_rules.py`
(단일 권위)의 결정론 규칙을 코퍼스 6종에 적용한다(`problem_corpus_tag.py`의 시그니처 재태깅과
동형 — 같은 비날조·바이트 계약 철학).

바이트 계약(결정론·비날조·비파괴):
  - `persona_fit`이 **이미 비어 있지 않은** 레코드는 손대지 않는다(원문 줄 바이트 그대로) —
    수동 큐레이션(D9 후속)을 조용히 덮어쓰지 않는다.
  - 비어 있는(`{}` 또는 부재) 레코드만 `persona_fit` 한 키를 계산값으로 교체해 재직렬화한다
    (json.dumps ensure_ascii=False — 코퍼스 기록 규약과 동일 형태).
  - 2회 실행은 바이트 동일(멱등) — 첫 실행이 값을 채우므로 두 번째는 전건 원문 통과.
  - 채운 레코드마다 계산 근거(`PersonaFitRationale`)를 감사 JSONL 1줄로 남긴다("근거 동반" —
    사후 설명이 아니라 재현 가능한 계산 추적).

사용법:
    python -m whymath_backend.harness.problem_corpus_persona_fit_backfill \\
        --in <src.jsonl> [--out <dst.jsonl>] [--audit-out <audit.jsonl>] [--dry-run | --check]

    python -m whymath_backend.harness.problem_corpus_persona_fit_backfill --all
        (코퍼스 6종 전부를 제자리 갱신 — `_KNOWN_CORPORA` 경로 고정)

    python -m whymath_backend.harness.problem_corpus_persona_fit_backfill --all --check
        (CI 드리프트 가드 — 아무것도 쓰지 않고, 미백필 레코드가 1건이라도 있으면 exit 1)

`--out` 생략 시 제자리 갱신(--in 덮어쓰기). `--audit-out` 생략 시
`docs/data/persona_fit_backfill_audit/<코퍼스 디렉터리명>.jsonl`에 쓴다(레포 루트 기준 상대경로
— populate.py `_DEFAULT_PROBLEMS` 관례와 동일하게 레포 루트에서 실행 전제).

세 실행 모드(OPS-24):
  - **기본**(플래그 없음) — 제자리 갱신(변이형). 사람이 돌리고 결과를 커밋한다.
  - `--dry-run` — 파일·감사로그 미기록·통계만 출력. **채울 게 있든 없든 항상 exit 0**이라
    게이트로 쓸 수 없다(관측용).
  - `--check` — 파일·감사로그 미기록(`--dry-run`과 동일하게 write 경로에 진입하지 않는다)이되,
    채울 레코드가 **1건이라도 있으면 exit 1**·0건이면 exit 0. 계산 규칙·바이트 계약은
    `--dry-run`과 완전히 동일하고 *종료 코드만* 다르다.

CI 배선 판정(OPS-24 — 왜 `--check`인가):
  ① 이 CLI는 "일회성 운영자 스크립트라 의도적 미배선"이 **아니다**. `persona_fit`이 빈 채로
     남은 레코드는 페르소나 기반 추천·노출 산정에서 조용히 누락된다(자매 CLI인 review_status
     백필의 경우 `l6/_shared.py`의 `is_review_cleared`가 fail-closed로 노출을 전건 차단한다) —
     둘 다 결정론(LLM 0)이라 CI가 지킬 수 있는 회귀다.
  ② 그럼에도 CI에 거는 것은 *변이형*(제자리 갱신)이 아니라 **드리프트 가드**(`--check`)다 —
     CI가 레포 데이터를 재작성해서는 안 된다. 백필 자체는 사람이 돌려 커밋하고, CI는 "빠진 게
     있다"만 빨갛게 알린다.

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_batch 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l1.problem_bank.persona_fit_rules import derive_persona_fit
from whymath_backend.l1.problem_bank.populate import _AUTHORING_KEYS
from whymath_backend.schema.problem import Problem

__all__ = ["KNOWN_CORPORA", "PersonaFitBackfillReport", "main", "run_persona_fit_backfill"]

# 코퍼스 6종 고정 경로(레포 루트 기준) — S3-10 원 구현(2026-07-29) 대상 전량(2,667건 = 2,663 + 4).
# S3-11(서지 정합)이 이 목록에 `_provenance.json`을 붙인다 — 이 CLI는 목록만 재사용한다.
#
# `probability_finite_v0`(34건)는 이 CLI가 원 구현될 당시엔 존재하지 않던 7번째 코퍼스다(S4-13
# 확률 유한 전수형 파일럿 — 이후 신설). 미병합 브랜치에서 이 태스크를 회수하며(2026-07-30) 추가
# — 로직 무변경, 대상 목록만 확장(신규 데이터 포인트 추가일 뿐 규칙·바이트 계약은 그대로).
KNOWN_CORPORA: dict[str, Path] = {
    "conceptual_v0": Path("data/corpus/problem_bank_conceptual_v0/problems.jsonl"),
    "generated_v0": Path("data/corpus/problem_bank_generated_v0/problems.jsonl"),
    "killer_v0": Path("data/corpus/problem_bank_killer_v0/problems.jsonl"),
    "misconception_mc_v0": Path("data/corpus/problem_bank_misconception_mc_v0/problems.jsonl"),
    "rephrased_v0": Path("data/corpus/problem_bank_rephrased_v0/problems.jsonl"),
    "v1": Path("data/corpus/problem_bank_v1/problems.jsonl"),
    "probability_finite_v0": Path("data/corpus/problem_bank_probability_finite_v0/problems.jsonl"),
    # P3-03 미적분Ⅰ 미분 은행(504건) — 8번째. 자격 통과 프로토콜의 5회차 S5 감사가 승인 근거를
    # 냈다(`docs/data/p3_calculus1_diff_audit/bank_audit_r5/`). 은행은 결정론 생성기 산출물이라
    # 이 두 백필이 채운 키(`persona_fit`·`review_status`)를 걷어 낸 바이트가 감사 동결 사본과
    # 같아야 한다 — 그 결속은 `p3_calculus1_diff_batch.strip_backfill_stamps`와 은행 커버리지
    # 테스트가 동결한다.
    "p3_calculus1_diff_v0": Path("data/corpus/problem_bank_p3_calculus1_diff_v0/problems.jsonl"),
}

_AUDIT_DIR = Path("docs/data/persona_fit_backfill_audit")


@dataclass(frozen=True, slots=True)
class PersonaFitBackfillReport:
    """백필 리포트 — 총량·채움·기보유·밴드 분포(조용한 실패 금지)."""

    total: int
    filled: int
    already_set: int
    band_counts: dict[str, int] = field(default_factory=dict)
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
            "band_counts": dict(sorted(self.band_counts.items())),
            "written": self.written,
            "audit_written": self.audit_written,
            "in_path": self.in_path,
            "out_path": self.out_path,
            "audit_path": self.audit_path,
        }


def _backfill_line(stripped: str) -> tuple[str, dict[str, Any] | None]:
    """JSONL 한 줄을 백필 — (산출 줄, 감사 항목 또는 None(무변경)) 반환.

    `persona_fit`이 이미 비어 있지 않으면 원문 줄 그대로(바이트 보존·수동 큐레이션 존중).
    비어 있으면 `derive_persona_fit`으로 계산해 그 한 키만 교체한다(populate 로더와 동일하게
    authoring 키를 분리해 Problem 검증 — `extra=forbid` 대응).
    """
    data: dict[str, Any] = json.loads(stripped)
    current = data.get("persona_fit") or {}
    if current:
        return stripped, None  # 무변경 — 이미 채워짐(수동 큐레이션 등)을 덮어쓰지 않는다.

    problem_fields = {k: v for k, v in data.items() if k not in _AUTHORING_KEYS}
    problem = Problem.model_validate(problem_fields)
    final, rationale = derive_persona_fit(problem)

    updated = dict(data)
    updated["persona_fit"] = final
    out_line = json.dumps(updated, ensure_ascii=False)

    audit_entry = {
        "problem_id": data.get("problem_id"),
        "slug": data.get("slug"),
        "persona_fit": final,
        "band": rationale.band.value,
        "band_base": rationale.band_base,
        "signature_bonus": rationale.signature_bonus,
        "complex_reasoning_bonus": rationale.complex_reasoning_bonus,
        "format_bonus": rationale.format_bonus,
        "distractor_bonus": rationale.distractor_bonus,
    }
    return out_line, audit_entry


def run_persona_fit_backfill(
    *,
    in_path: Path,
    out_path: Path,
    audit_path: Path,
    write: bool = True,
) -> PersonaFitBackfillReport:
    """코퍼스 JSONL 전 레코드에 백필 적용 — 이미 채워진 레코드는 바이트 무변경·멱등.

    빈 줄은 건너뛴다(populate 로더와 동일 관대함). 레코드가 Problem 스키마·저작권 불변식을
    위반하면 ValidationError로 즉시 실패한다(백필은 검증된 코퍼스에만 의미가 있다).
    """
    text = in_path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    audit_entries: list[dict[str, Any]] = []
    total = 0
    filled = 0
    already_set = 0
    band_counts: dict[str, int] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        out_line, audit_entry = _backfill_line(stripped)
        if audit_entry is None:
            already_set += 1
        else:
            filled += 1
            band_counts[audit_entry["band"]] = band_counts.get(audit_entry["band"], 0) + 1
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

    return PersonaFitBackfillReport(
        total=total,
        filled=filled,
        already_set=already_set,
        band_counts=band_counts,
        written=written,
        audit_written=audit_written,
        in_path=str(in_path),
        out_path=str(out_path),
        audit_path=str(audit_path),
    )


def _default_audit_path(in_path: Path) -> Path:
    """감사 경로 기본값 — 코퍼스 디렉터리명 기준(레포 루트 상대, populate.py 관례와 동일)."""
    return _AUDIT_DIR / f"{in_path.parent.name}.jsonl"


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 백필 후 리포트를 JSON으로 stdout에 낸다(결정론·멱등).

    `--all`이면 `KNOWN_CORPORA` 6종을 순회해 각각 백필하고 리포트 목록을 낸다. 단일 파일
    처리는 `--in`(+선택 `--out`/`--audit-out`)을 쓴다. 레포 루트에서 실행 전제(상대경로 규약).

    Returns:
      `--check`에서 미백필 레코드가 1건 이상이면 1, 그 밖에는 0(기본·`--dry-run`은 항상 0).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_persona_fit_backfill",
        description=(
            "페르소나 적합도(persona_fit) 백필(S3-10) — 코퍼스 JSONL의 빈 persona_fit만 "
            "결정론 규칙으로 채운다(persona_fit 외 바이트 무변경·멱등·비날조)."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--in", dest="in_path", type=Path, help="입력 JSONL 경로(단일 파일).")
    group.add_argument(
        "--all", action="store_true", help=f"코퍼스 {len(KNOWN_CORPORA)}종 전부 제자리 갱신."
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
        help="감사 JSONL 경로(생략 시 docs/data/persona_fit_backfill_audit/<코퍼스명>.jsonl).",
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
        parser.error("--all과 --out은 함께 쓸 수 없다(경로가 6개로 정해져 있다).")

    targets: list[Path] = list(KNOWN_CORPORA.values()) if args.all else [args.in_path]
    reports = []
    for in_path in targets:
        out_path = args.out_path if args.out_path is not None else in_path
        audit_path = (
            args.audit_path if args.audit_path is not None else _default_audit_path(in_path)
        )
        reports.append(
            run_persona_fit_backfill(
                in_path=in_path,
                out_path=out_path,
                audit_path=audit_path,
                write=not (args.dry_run or args.check),
            )
        )

    payload: Any = [r.to_json() for r in reports] if args.all else reports[0].to_json()
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    if args.check:
        return _check_exit_code(reports)
    return 0


def _check_exit_code(reports: list[PersonaFitBackfillReport]) -> int:
    """`--check` 판정 — 미백필 레코드가 남아 있으면 1(무엇이 왜 남았는지 stderr에 명시).

    조용히 exit 1만 내지 않는다(침묵 실패 금지) — 코퍼스 경로·잔여 건수를 함께 적어 사람이 바로
    백필 명령을 돌릴 수 있게 한다.
    """
    pending = [r for r in reports if r.filled > 0]
    if not pending:
        return 0
    for report in pending:
        sys.stderr.write(
            f"[check] persona_fit 미백필 {report.filled}건 / 총 {report.total}건 — "
            f"{report.in_path}\n"
        )
    sys.stderr.write(
        "드리프트 감지: persona_fit이 빈 레코드는 페르소나 기반 추천·노출 산정에서 조용히 "
        "누락된다. `--check` 없이 같은 명령을 돌려 백필하고 결과를 커밋하라.\n"
    )
    return 1


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
