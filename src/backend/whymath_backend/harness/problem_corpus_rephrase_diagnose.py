"""rephrase 실패 진단 — 실패 케이스 dump·reason-code taxonomy·skeleton별 수율(S2-p 후속).

온도 스윕(`problem_corpus_rephrase_sweep`)은 *얼마나* 실패하는지(변형률)를 보여줬지만 *왜·무엇이*
실패하는지는 "수치 불변 검증 실패"라는 한 줄만 남겨 디버깅이 불가능했다(라이브 실측 관찰). 이
CLI는 그 공백을 메운다 — 코퍼스 샘플을 rephrase에 태워 각 실패를:
  1. **reason-code로 분류**(`rephrase.REASON_*` taxonomy: EQUATION_ALTERED·EXTRA_EQUATION·
     HYGIENE_REJECT·EMPTY·NO_CHANGE·PROVIDER_ERROR) — 실제 게이트 코드 경로에 1:1(정직 taxonomy).
  2. **원 LLM 출력과 함께 dump**(`--dump <path>` JSONL: slug·temperature·reason_code·
     skeleton_key·original·rephrased_raw) — 무엇이 봉인을 깼는지 사람이 눈으로 분석.
  3. **skeleton 유형별 수율 집계** — 어떤 문제 유형이 LLM augmentation에 취약한지(성취기준·
     발문형식·답형식으로 유형 키를 유도). validator 버그 vs LLM 품질을 분리하는 첫 단서.

**측정 전용**: rephrase 산출 코퍼스를 쓰지 않는다(스윕과 동형). `--dump` 산출은 라이브 디버깅
아티팩트라 **repo에 커밋하지 않는다**(rephrase 산출은 Phaiakes9 소관 원칙). limit로 시도(=LLM
호출) 상한을 둔다(스윕과 동일 비용 통제).

hermetic: `rephraser` 좌석(테스트=실패 유형별 FakeProvider·라이브=`QuestionRephraser`). 이 환경엔
LLM이 없어 라이브 호출을 하지 않는다 — 실 진단은 Phaiakes9에서 실 provider로 구동한다.

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_rephrase 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.l3.equivalent.rephrase import REASON_NO_EQUATION, QuestionRephraser

__all__ = [
    "DiagnoseReport",
    "FailureCase",
    "SkeletonStat",
    "main",
    "run_rephrase_diagnose",
]

_DEFAULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class FailureCase:
    """실패 1건 — 사후 디버깅에 필요한 최소 정보(원문·LLM 실제 출력·사유·유형)."""

    slug: str
    temperature: float
    reason_code: str
    skeleton_key: str
    original: str
    rephrased_raw: str | None  # LLM 실제 출력(검증 전) — provider 예외 등이면 None.

    def to_json(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "temperature": self.temperature,
            "reason_code": self.reason_code,
            "skeleton_key": self.skeleton_key,
            "original": self.original,
            "rephrased_raw": self.rephrased_raw,
        }


@dataclass(frozen=True, slots=True)
class SkeletonStat:
    """skeleton 유형 1개의 수율 — 시도·변형·변형률 + 사유별 실패 분포(취약 유형 탐지)."""

    skeleton_key: str
    attempted: int
    rephrased: int
    rate: float
    failures_by_reason: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "skeleton_key": self.skeleton_key,
            "attempted": self.attempted,
            "rephrased": self.rephrased,
            "rate": self.rate,
            "failures_by_reason": self.failures_by_reason,
        }


@dataclass(frozen=True, slots=True)
class DiagnoseReport:
    """진단 리포트 — 총량·reason-code 히스토그램·skeleton별 수율·실패 케이스 목록."""

    in_path: str
    limit: int | None
    temperature: float
    total: int
    attempted: int
    rephrased: int
    reason_histogram: dict[str, int]
    skeleton_stats: list[SkeletonStat]
    failures: list[FailureCase]

    def to_json(self) -> dict[str, Any]:
        return {
            "in_path": self.in_path,
            "limit": self.limit,
            "temperature": self.temperature,
            "total": self.total,
            "attempted": self.attempted,
            "rephrased": self.rephrased,
            "reason_histogram": self.reason_histogram,
            "skeleton_stats": [stat.to_json() for stat in self.skeleton_stats],
            "failures": [case.to_json() for case in self.failures],
        }

    def render_summary(self) -> str:
        """사람용 요약 — 총 변형률 + reason-code 히스토그램 + skeleton별 수율 표."""
        rate = self.rephrased / self.attempted if self.attempted else 0.0
        fails = len(self.failures)
        lines = [
            f"입력: {self.in_path}  (총 {self.total}건·시도 {self.attempted}·상한 {self.limit}"
            f"·온도 {self.temperature:.2f})",
            f"변형: {self.rephrased}/{self.attempted}  ({rate * 100:.1f}%)  실패 {fails}건",
            "",
            "── 실패 사유(reason-code) 분포 ──",
        ]
        if self.reason_histogram:
            for code, count in sorted(self.reason_histogram.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {code:<18} {count:>4}")
        else:
            lines.append("  (실패 없음)")
        lines.extend(["", "── skeleton 유형별 수율 ──"])
        header = f"  {'유형':<34} {'시도':>5} {'변형':>5} {'변형률':>7}"
        lines.append(header)
        for stat in sorted(self.skeleton_stats, key=lambda s: s.rate):
            lines.append(
                f"  {stat.skeleton_key:<34} {stat.attempted:>5} {stat.rephrased:>5} "
                f"{stat.rate * 100:>6.1f}%"
            )
        return "\n".join(lines)


def _read_records(path: Path) -> list[dict[str, Any]]:
    """입력 JSONL을 dict 목록으로 로드(순서 보존·빈 줄 무시)."""
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _skeleton_key(record: dict[str, Any]) -> str:
    """레코드에서 skeleton 유형 키를 유도 — 성취기준·발문형식·답형식(취약 유형 그룹핑 축).

    코퍼스에 명시적 skeleton_type 필드는 없다(개념 순수성 — 노드에 조성 정보 미혼입). 대신
    관측 가능한 구조 필드로 유형을 근사한다: 성취기준(단원 계열)·발문형식(단답/객관식)·답형식
    (자연수/정수/실수) 조합이 스켈레톤 밴드(short/mc/sqrt/exp/log)를 사실상 구분한다.
    """
    codes = record.get("achievement_standard_codes") or []
    code_part = ",".join(sorted(codes)) if isinstance(codes, list) else str(codes)
    qfmt = record.get("question_format") or "?"
    afmt = record.get("answer_format") or "?"
    return f"{code_part}·{qfmt}·{afmt}"


def run_rephrase_diagnose(
    *,
    in_path: Path,
    rephraser: QuestionRephraser,
    temperature: float,
    limit: int | None = _DEFAULT_LIMIT,
    offset: int = 0,
) -> DiagnoseReport:
    """코퍼스 샘플을 rephrase에 태워 실패를 taxonomy·유형별로 진단(측정 전용·write 없음).

    각 발문을 `rephraser.rephrase`에 태워 실패면 reason-code·원 LLM 출력·skeleton 유형과 함께
    수집한다. `limit`은 *시도*(=LLM 호출) 상한이다(스윕과 동형·비용 통제). `NO_EQUATION`
    (방정식 추출 실패=rephrase 대상 아님)은 시도로 세지 않는다 — 시도 분모를 오염하지 않게.
    `offset`은 파일 앞에서부터 건너뛸 레코드 수다 — 밴드가 파일 뒤쪽에 몰린 유형(예: 지수·로그는
    코퍼스 끝 45건)을 앞의 quad 수백 건을 재실행하지 않고 `--offset`으로 저비용 타게팅한다.
    `temperature`는 dump 주석용 라벨이다(rephraser가 실제 온도를 소유·여기선 기록만).
    """
    records = _read_records(in_path)
    if offset:
        records = records[offset:]  # 앞 offset건 건너뛰기 — 뒤쪽 밴드(지수·로그) 저비용 타게팅.
    attempted = 0
    rephrased = 0
    reason_hist: Counter[str] = Counter()
    failures: list[FailureCase] = []
    per_skeleton_attempted: Counter[str] = Counter()
    per_skeleton_rephrased: Counter[str] = Counter()
    per_skeleton_fail: dict[str, Counter[str]] = {}

    for record in records:
        question = record.get("question_text")
        if not isinstance(question, str) or not question:
            continue  # 발문 부재(메타 전용) — 진단 대상 아님.
        if limit is not None and attempted >= limit:
            break  # 시도 상한 — 이후는 미시도(LLM 미호출).
        outcome = rephraser.rephrase(question)
        if outcome.reason_code == REASON_NO_EQUATION:
            continue  # 봉인 대상 부재 — rephrase 미시도라 분모에서 제외.

        attempted += 1
        skeleton = _skeleton_key(record)
        per_skeleton_attempted[skeleton] += 1
        if outcome.rephrased:
            rephrased += 1
            per_skeleton_rephrased[skeleton] += 1
            continue
        code = outcome.reason_code or "UNKNOWN"
        reason_hist[code] += 1
        per_skeleton_fail.setdefault(skeleton, Counter())[code] += 1
        failures.append(
            FailureCase(
                slug=str(record.get("slug", "?")),
                temperature=temperature,
                reason_code=code,
                skeleton_key=skeleton,
                original=question,
                rephrased_raw=outcome.raw_output,
            )
        )

    skeleton_stats = [
        SkeletonStat(
            skeleton_key=key,
            attempted=per_skeleton_attempted[key],
            rephrased=per_skeleton_rephrased[key],
            rate=round(per_skeleton_rephrased[key] / per_skeleton_attempted[key], 4),
            failures_by_reason=dict(per_skeleton_fail.get(key, Counter())),
        )
        for key in sorted(per_skeleton_attempted)
    ]
    return DiagnoseReport(
        in_path=str(in_path),
        limit=limit,
        temperature=temperature,
        total=len(records),
        attempted=attempted,
        rephrased=rephrased,
        reason_histogram=dict(reason_hist),
        skeleton_stats=skeleton_stats,
        failures=failures,
    )


def _write_failures(path: Path, failures: list[FailureCase]) -> int:
    """실패 케이스를 JSONL로 dump(라이브 디버깅 아티팩트·repo 미커밋) — 기록 행 수 반환."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(case.to_json(), ensure_ascii=False) for case in failures]
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
    return len(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — rephrase 실패를 taxonomy·유형별로 진단하고 요약을 stdout에 낸다(항상 exit 0).

    provider 미주입이라 라이브 provider가 있는 환경(Phaiakes9)에서만 실효하다 — 이 환경(LLM 0)에서
    호출하면 전건 provider 예외(PROVIDER_ERROR)로 집계되고, 요약이 그 사실을 정직히 드러낸다
    (조용한 실패 금지). `--dump`면 실패 케이스를 JSONL로 저장(원 LLM 출력 포함)·`--json`이면 요약
    대신 리포트 JSON을 낸다.
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_rephrase_diagnose",
        description=(
            "rephrase 실패 진단 — 실패 케이스 dump·reason-code taxonomy·skeleton별 수율"
            "(측정 전용·코퍼스 미기록·fail-closed)."
        ),
    )
    parser.add_argument("--in", dest="in_path", type=Path, required=True, help="입력 JSONL 경로.")
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="rephrase 샘플링 온도(기본 0.7·실측 스윗스팟).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"rephrase 시도 상한(샘플·기본 {_DEFAULT_LIMIT}·0이면 전건).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="앞에서부터 건너뛸 레코드 수(뒤쪽 밴드 타게팅·예: 지수·로그는 --offset 305).",
    )
    parser.add_argument(
        "--dump", dest="dump_path", type=Path, default=None, help="실패 케이스 JSONL dump 경로."
    )
    parser.add_argument("--json", action="store_true", help="요약 대신 리포트 JSON을 출력.")
    args = parser.parse_args(argv)

    if args.offset < 0:
        parser.error("--offset은 0 이상이어야 합니다.")
    limit = args.limit if args.limit and args.limit > 0 else None
    rephraser = QuestionRephraser(temperature=args.temperature)
    try:
        report = run_rephrase_diagnose(
            in_path=args.in_path,
            rephraser=rephraser,
            temperature=args.temperature,
            limit=limit,
            offset=args.offset,
        )
    finally:
        # 짧게 끝나는 CLI — 저작 호출의 Langfuse `l3_routing` 배치를 종료 전에 확정(OPS-84).
        rephraser.flush()
    if args.dump_path is not None:
        written = _write_failures(args.dump_path, report.failures)
        sys.stderr.write(f"실패 {written}건 dump → {args.dump_path}\n")
    if args.json:
        json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(report.render_summary() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
