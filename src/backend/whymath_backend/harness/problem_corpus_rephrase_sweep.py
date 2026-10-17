"""rephrase 온도 스윕 — 같은 코퍼스 샘플을 여러 온도로 rephrase해 다양화 수율을 비교(S2-p 후속).

발문 다양화(`problem_corpus_rephrase`)의 샘플링 온도(`QuestionRephraser.temperature`)는 표현
다양성과 봉인 안정성을 맞바꾼다 — 높으면 문장 변주는 커지되 방정식 문자열 훼손(→ 수치 불변
검증 실패·원문 유지)이 늘 수 있고, 낮으면 변주가 약하다. 이 CLI는 **고정 코퍼스 샘플을 여러
온도(기본 0.7·0.9)로 각각 rephrase해 온도별 변형률(rephrased/attempted)을 한 표로 비교**한다.
어느 온도가 "다양화는 되되 봉인은 안 깨지는" 스윗스팟인지 실측으로 고르기 위한 도구다.

핵심 설계(왜 싸고 안전한가):
  1. **샘플 상한**(`--limit`) — 온도마다 코퍼스 전건을 LLM에 태우면 비용이 온도 수만큼 곱해진다.
     `run_corpus_rephrase(limit=N)`으로 앞 N건만 rephrase에 태워(=LLM 호출 N회) 온도별 비율을
     싸게 뽑는다. 비교는 비율이라 N이 온도 간 동일하면 공정하다(같은 입력·같은 앞 N건).
  2. **write=False** — 스윕은 *측정*이지 산출이 아니다. 코퍼스를 쓰지 않는다(repo 오염 0·
     rephrase 산출은 라이브 소관이라는 원칙 유지).
  3. **결정론 조립** — 스윕 자체는 LLM 결과를 세기만 한다. 비결정은 provider에만 있고, 각
     온도는 독립적으로 같은 입력 파일을 다시 읽어 상태 누수가 없다.
  4. **반복 평균화**(`--repeats N`) — 라이브 LLM은 비결정이라 같은 온도가 회차마다 ±20%p씩
     흔들린다(n=50 단발로는 0.7 vs 0.9를 구분 못 함·2026-07-07 실측). 온도당 N회 돌려 변형률을
     합산 평균하고 회차별 min~max 폭을 함께 보고한다 — **온도 차이가 이 폭보다 작으면 유의하지
     않다**는 판단 근거를 제공한다.

hermetic: `rephraser_factory` 좌석으로 온도별 rephraser를 만든다(테스트=온도 가변 FakeProvider·
라이브=`QuestionRephraser(temperature=t)`). 이 환경엔 LLM이 없어 라이브 호출을 하지 않는다 —
실 스윕은 Phaiakes9에서 실 provider로 구동한다(rephrase 라이브 핸드오프 동형). provider 미주입
main은 전건 provider 예외로 rephrased 0이 되며 표가 그 사실을 정직히 드러낸다(조용한 실패 금지).

harness는 import-linter 계약 밖(조성/ops 층·상위 호출 정상 — problem_corpus_rephrase 선례).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from whymath_backend.harness.problem_corpus_rephrase import run_corpus_rephrase
from whymath_backend.l3.equivalent.rephrase import QuestionRephraser

__all__ = ["RephraseSweepReport", "SweepRow", "main", "run_rephrase_sweep"]

# 기본 스윕 온도·샘플 상한 — 사용자 관심(0.7 vs 0.9)·비용 억제(온도당 50건) 기본값.
_DEFAULT_TEMPERATURES = (0.7, 0.9)
_DEFAULT_LIMIT = 50
# write=False라 실제로 쓰이지 않는 자리 채움 out_path(리포트에만 기록·discard).
_NOOP_OUT = Path("(sweep-dry-run)")


@dataclass(frozen=True, slots=True)
class SweepRow:
    """온도 1개의 스윕 결과 — 시도·변형·유지 수 + 변형률 + 유지 사유 표본(조용한 실패 금지)."""

    temperature: float
    attempted: int
    rephrased: int
    unchanged: int
    rate: float  # rephrased / attempted (전 반복 합산·attempted 0이면 0.0) — 온도 간 비교 축.
    repeats: int = 1  # 이 온도를 몇 회 반복해 집계했는가(라이브 노이즈 평균화).
    rate_min: float = 0.0  # 반복 중 최저 변형률 — 회차 변동폭(노이즈) 관측.
    rate_max: float = 0.0  # 반복 중 최고 변형률.
    unchanged_reason_sample: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "attempted": self.attempted,
            "rephrased": self.rephrased,
            "unchanged": self.unchanged,
            "rate": self.rate,
            "repeats": self.repeats,
            "rate_min": self.rate_min,
            "rate_max": self.rate_max,
            "unchanged_reason_sample": self.unchanged_reason_sample,
        }


@dataclass(frozen=True, slots=True)
class RephraseSweepReport:
    """스윕 리포트 — 입력·샘플 상한·총 레코드 + 온도별 행(비교표 렌더 포함)."""

    in_path: str
    limit: int | None
    total: int
    rows: list[SweepRow]

    def to_json(self) -> dict[str, Any]:
        return {
            "in_path": self.in_path,
            "limit": self.limit,
            "total": self.total,
            "rows": [row.to_json() for row in self.rows],
        }

    def render_table(self) -> str:
        """온도별 변형률 비교표(모노스페이스) — 사람이 스윗스팟을 눈으로 고르게.

        반복(repeats>1) 시 변형률은 전 반복 평균이고, 오른쪽 `범위(min~max)`가 회차 변동폭
        (라이브 LLM 노이즈)을 드러낸다 — 온도 차가 이 폭보다 작으면 유의하지 않다는 신호.
        """
        repeats = self.rows[0].repeats if self.rows else 1
        header = f"{'온도':>6}  {'시도':>5}  {'변형':>5}  {'변형률':>7}  {'범위(min~max)':>16}"
        sep = "-" * 52
        title = f"입력: {self.in_path}  (총 {self.total}건·샘플 상한 {self.limit}·반복 {repeats})"
        lines = [title, header, sep]
        for row in self.rows:
            span = f"{row.rate_min * 100:.1f}~{row.rate_max * 100:.1f}%"
            lines.append(
                f"{row.temperature:>6.2f}  {row.attempted:>5}  {row.rephrased:>5}  "
                f"{row.rate * 100:>6.1f}%  {span:>16}"
            )
        return "\n".join(lines)


def run_rephrase_sweep(
    *,
    in_path: Path,
    temperatures: Sequence[float] = _DEFAULT_TEMPERATURES,
    limit: int | None = _DEFAULT_LIMIT,
    repeats: int = 1,
    rephraser_factory: Callable[[float], QuestionRephraser] | None = None,
) -> RephraseSweepReport:
    """고정 코퍼스 샘플을 온도별로 rephrase해 변형률을 비교(측정 전용·write 없음).

    각 온도마다 `rephraser_factory(temp)`로 rephraser를 만들어 `run_corpus_rephrase(limit=limit,
    write=False)`를 `repeats`회 돌리고, 변형률(rephrased/attempted)을 **전 반복 합산**으로 집계하며
    회차별 변형률의 최소·최대를 함께 기록한다. `repeats>1`은 라이브 LLM 비결정성으로 회차마다
    ±20%p씩 흔들리는 변형률을 평균화해 온도 차이를 노이즈에서 분리한다(min~max 폭 < 온도 차여야
    유의). rephraser는 온도당 1개를 만들어 반복 간 재사용한다(라이브 커넥션·이벤트 루프 재사용).

    `unchanged`는 *시도 중* 미변형(attempted − rephrased)만 센다(샘플 밖 미시도 레코드는 제외 —
    온도 비교를 오염하지 않는다). 입력은 매 반복 새로 읽어 상태 누수가 없다(공정 비교).

    `rephraser_factory` 기본은 라이브(`QuestionRephraser(temperature=t)`) — 이 환경엔 LLM이 없어
    provider 예외로 전건 미변형이 되고 표가 그 사실을 정직히 드러낸다. 테스트는 온도 가변
    FakeProvider를 감싼 factory를 주입해 라이브 0으로 온도 차이·반복 집계를 검증한다.
    """
    if repeats < 1:
        raise ValueError(f"repeats는 1 이상이어야 합니다: {repeats}")
    factory = rephraser_factory or (lambda t: QuestionRephraser(temperature=t))
    rows: list[SweepRow] = []
    total = 0
    for temp in temperatures:
        rephraser = factory(temp)  # 온도당 1개 — 반복 간 재사용(라이브 자원 재사용).
        agg_attempted = 0
        agg_rephrased = 0
        run_rates: list[float] = []
        reasons: list[str] = []
        for _ in range(repeats):
            report = run_corpus_rephrase(
                in_path=in_path,
                out_path=_NOOP_OUT,
                rephraser=rephraser,
                limit=limit,
                write=False,
            )
            total = report.total
            agg_attempted += report.attempted
            agg_rephrased += report.rephrased
            run_rates.append(report.rephrased / report.attempted if report.attempted else 0.0)
            if not reasons:  # 첫 회차 사유 표본만 실어 관측(반복분 중복 방지).
                reasons = report.unchanged_reason_sample
        # 온도별 저작 호출의 Langfuse `l3_routing` 배치를 확정(OPS-84 — 짧게 끝나는 CLI).
        rephraser.flush()
        rate = agg_rephrased / agg_attempted if agg_attempted else 0.0
        rows.append(
            SweepRow(
                temperature=temp,
                attempted=agg_attempted,
                rephrased=agg_rephrased,
                unchanged=agg_attempted - agg_rephrased,
                rate=round(rate, 4),
                repeats=repeats,
                rate_min=round(min(run_rates), 4),
                rate_max=round(max(run_rates), 4),
                unchanged_reason_sample=reasons,
            )
        )
    return RephraseSweepReport(in_path=str(in_path), limit=limit, total=total, rows=rows)


def _parse_temperatures(raw: str) -> list[float]:
    """'0.7,0.9' → [0.7, 0.9] — 쉼표 구분 온도 목록(공백 허용·빈 항목 무시)."""
    temps = [float(part.strip()) for part in raw.split(",") if part.strip()]
    if not temps:
        raise argparse.ArgumentTypeError("온도를 최소 1개 지정하세요(예: 0.7,0.9).")
    return temps


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — 온도별 rephrase 변형률 비교표를 stdout에 낸다(측정 전용·항상 exit 0).

    provider 미주입이라 라이브 provider가 있는 환경(Phaiakes9)에서만 실효하다 — 이 환경(LLM 0)에서
    호출하면 전건 provider 예외로 변형 0이 되고, 표·JSON이 그 사실을 정직히 드러낸다(조용한 실패
    금지). `--json`이면 표 대신 리포트 JSON을 낸다(파이프라인 소비용).
    """
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.harness.problem_corpus_rephrase_sweep",
        description=(
            "rephrase 온도 스윕 — 고정 코퍼스 샘플을 여러 온도로 rephrase해 다양화 변형률을 "
            "비교(측정 전용·코퍼스 미기록·fail-closed)."
        ),
    )
    parser.add_argument("--in", dest="in_path", type=Path, required=True, help="입력 JSONL 경로.")
    parser.add_argument(
        "--temperatures",
        type=_parse_temperatures,
        default=list(_DEFAULT_TEMPERATURES),
        help="쉼표 구분 온도 목록(기본 0.7,0.9).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"온도당 rephrase 시도 상한(샘플·기본 {_DEFAULT_LIMIT}·0이면 전건은 --limit 미지정).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="온도당 반복 실행 횟수(라이브 노이즈 평균화·기본 1·min~max 폭으로 변동 관측).",
    )
    parser.add_argument("--json", action="store_true", help="표 대신 리포트 JSON을 출력.")
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats는 1 이상이어야 합니다.")
    limit = args.limit if args.limit and args.limit > 0 else None
    report = run_rephrase_sweep(
        in_path=args.in_path,
        temperatures=args.temperatures,
        limit=limit,
        repeats=args.repeats,
    )
    if args.json:
        json.dump(report.to_json(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(report.render_table() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover — 모듈 실행 진입점
    raise SystemExit(main())
