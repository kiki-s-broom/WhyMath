"""L2 — 문항 응답 축적 실측(census) · 읽기 전용 — 2PL 변별도 a 보정의 데이터 게이트(EOS-129 ⑤).

EOS-129 ③(문항 변별도 a를 추정해 `Problem.irt_a`에 영속하고 CAT가 소비)은 **문항당 응답이 먼저
쌓여야** 의미가 있다. a는 b보다 더 많은 응답을 요구하고, 지금 b 보정조차 응답 5건 이상 문항만
영속한다(`item_calibration._MIN_RESPONSES_FOR_CALIBRATION`). 그래서 acceptance ⑤가 착수 순서를
정했다 — **운영 코퍼스의 문항당 응답 분포를 먼저 재고, 추정 가능한 문항이 몇 건인지 적는다.**
0건에 가까우면 태스크는 데이터 축적 대기이며 그 사실 자체가 산출물이다.

이 모듈은 그 측정만 한다. 판정은 하지 않는다.

────────────────────────────────────────────────────────────────────────────
무엇을 세는가
────────────────────────────────────────────────────────────────────────────
- 모집단은 b 보정기와 **같다** — 보정기와 같은 로더 `item_calibration.load_graded_responses`
  (채점됨·학생·문항 식별 가능)로 읽는다. 따로 조건을 적으면 "보정기가 실제로 먹는 데이터"와 다른
  것을 센다. 이 모듈은 DB를 직접 잡지 않는다(세션 메서드 호출 0건 — ARCH-48 처분 (b)).
- 문항별 **응답 수**와 **서로 다른 학생 수**를 둘 다 센다. 같은 학생의 반복 응답은 a 추정에
  새 정보를 거의 주지 않으므로, a 쪽 판단은 학생 수로 한다.
- **정답·오답이 둘 다 있는 문항**만 a 추정 후보로 센다. 한쪽 결과만 있는 문항은 어떤 모수도
  유한하게 추정되지 않는다(전부 정답이면 b→−∞).
- a 추정에 필요한 학생 수는 **이 모듈이 정하지 않는다.** 문헌마다 다르고(수백 명 단위가 흔히
  인용된다) 이 저장소에는 아직 실측 근거가 없다. 그래서 여러 임계(`A_ESTIMATION_STUDENT_THRESHOLDS`)
  에서 각각 센다 — 어느 임계로 판정할지는 사람이 한다.

────────────────────────────────────────────────────────────────────────────
안전 (운영 DB에서 돈다)
────────────────────────────────────────────────────────────────────────────
- **쓰지 않는다** — 조회 전에 트랜잭션을 `READ ONLY`로 선언한다. 코드에 쓰기가 섞여 들어와도
  DB가 거부한다(방어의 이중화).
- **학생·문항 식별자를 출력하지 않는다** — 집계치만 낸다(미성년자 데이터 — CLAUDE.md 보안 축).
- 출력은 **ASCII JSON**이다 — 한국어 Windows(cp949) 콘솔을 거쳐도 깨지지 않게(OPS-53 축).
- **측정 실패를 0건으로 위장하지 않는다** — DB 연결·조회가 실패하면 예외 타입명을 stderr에 남기고
  종료 코드 3으로 끝난다. 0건 JSON은 "측정은 성공했고 데이터가 0"일 때만 나온다.

사용:
    python -m whymath_backend.l2.item_response_census [--out PATH]

종료 코드: 0 측정 성공 · 2 사용 오류(argparse) · 3 DB 연결·조회 실패.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter
from collections.abc import Hashable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from whymath_backend.config import get_settings
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.l2 import item_calibration
from whymath_backend.l2.item_calibration import _MIN_RESPONSES_FOR_CALIBRATION

# 출력 형태 판본 — 필드 의미를 바꾸면 올린다(런북·게이트 증적이 어느 형태를 읽었는지 추적).
CENSUS_SCHEMA_VERSION = 1

# a 추정 후보를 세는 학생 수 임계들 — **판정 임계가 아니다**(모듈 docstring). 한 임계만 두면
# 그 값이 곧 결정이 되므로 여러 값에서 센다.
A_ESTIMATION_STUDENT_THRESHOLDS: tuple[int, ...] = (30, 100, 200, 500)

# 문항별 분포 히스토그램 구간 — (하한, 상한 포함·None이면 무한). 5는 b 보정 임계와 맞춘 경계다.
_HISTOGRAM_BUCKETS: tuple[tuple[int, int | None], ...] = (
    (1, 1),
    (2, 4),
    (5, 9),
    (10, 29),
    (30, 99),
    (100, 199),
    (200, 499),
    (500, None),
)

_EXIT_OK = 0
_EXIT_MEASUREMENT_FAILED = 3


def _bucket_label(low: int, high: int | None) -> str:
    """구간 이름 — `1`·`2-4`·`500+`."""
    if high is None:
        return f"{low}+"
    return str(low) if low == high else f"{low}-{high}"


def _histogram(values: Iterable[int]) -> dict[str, int]:
    """값들을 고정 구간에 센다. 모든 구간 키를 0으로 먼저 채워 형태가 입력과 무관하게 같다."""
    counts = {_bucket_label(low, high): 0 for low, high in _HISTOGRAM_BUCKETS}
    for value in values:
        for low, high in _HISTOGRAM_BUCKETS:
            if value >= low and (high is None or value <= high):
                counts[_bucket_label(low, high)] += 1
                break
    return counts


def summarize_item_responses(
    rows: Iterable[tuple[Hashable, Hashable, bool]],
    *,
    problems_total: int | None,
) -> dict[str, object]:
    """(학생, 문항, 정답) 응답 → 문항당 응답 축적 집계. 순수·DB 무관·식별자 비출력.

    `rows`는 `item_calibration.load_graded_responses`가 내는 형태다. `problems_total`은 문항
    은행 전체 문항 수(응답이 한 건도 없는 문항까지 포함한 분모) — 모르면 None.
    """
    responses: Counter[Hashable] = Counter()
    correct: Counter[Hashable] = Counter()
    students_by_item: dict[Hashable, set[Hashable]] = {}
    students: set[Hashable] = set()
    graded = 0
    for user_id, problem_id, is_correct in rows:
        graded += 1
        responses[problem_id] += 1
        if is_correct:
            correct[problem_id] += 1
        students_by_item.setdefault(problem_id, set()).add(user_id)
        students.add(user_id)

    items = list(responses)
    both_outcomes = [item for item in items if 0 < correct[item] < responses[item]]
    student_counts = [len(students_by_item[item]) for item in items]
    return {
        "schema_version": CENSUS_SCHEMA_VERSION,
        "graded_responses": graded,
        "distinct_students": len(students),
        "problems_total": problems_total,
        "items_answered": len(items),
        "items_with_both_outcomes": len(both_outcomes),
        # b 보정기와 같은 기준(응답 수 ≥ 임계) — 보정기는 결과 다양성을 보지 않는다.
        "b_min_responses": _MIN_RESPONSES_FOR_CALIBRATION,
        "b_calibratable_items": sum(
            1 for item in items if responses[item] >= _MIN_RESPONSES_FOR_CALIBRATION
        ),
        "a_estimable_items_by_min_students": {
            str(threshold): sum(
                1 for item in both_outcomes if len(students_by_item[item]) >= threshold
            )
            for threshold in A_ESTIMATION_STUDENT_THRESHOLDS
        },
        "per_item_responses_histogram": _histogram(responses[item] for item in items),
        "per_item_students_histogram": _histogram(student_counts),
        "max_students_per_item": max(student_counts, default=0),
        "median_students_per_item": (
            float(statistics.median(student_counts)) if student_counts else None
        ),
    }


async def collect_census(session: AsyncSession) -> dict[str, object]:
    """운영 DB에서 모집단을 읽어 집계한다 — 트랜잭션을 먼저 `READ ONLY`로 선언한다.

    조회는 보정기 모듈의 공용 로더가 한다(`read_only=True` — 선언이 이 트랜잭션의 첫 문장이 되도록
    로더를 **먼저** 부른다). 이 함수 자신은 세션 메서드를 부르지 않는다. 로더는 모듈 속성으로
    불러 테스트가 "보정기와 같은 로더를 탄다"를 대역으로 확인할 수 있게 한다.
    """
    rows = await item_calibration.load_graded_responses(session, read_only=True)
    problems_total = await item_calibration.count_problems(session)
    return summarize_item_responses(rows, problems_total=problems_total)


async def _run() -> dict[str, object]:
    """세션 1개로 실측 → 엔진 정리. 쓰기·commit 없음."""
    sessionmaker = get_sessionmaker(get_settings())
    try:
        async with sessionmaker() as session:
            return await collect_census(session)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리 — ASCII JSON 1줄을 stdout에 낸다. 실패는 종료 코드 3(0건으로 위장 금지)."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l2.item_response_census",
        description=(
            "문항 응답 축적 실측(읽기 전용) — 문항당 응답 수·학생 수 분포와 b·a 보정 가능 "
            "문항 수를 집계한다(EOS-129 ⑤ 데이터 게이트). 식별자는 출력하지 않는다."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="같은 JSON을 이 경로에도 쓴다(선택 · ASCII).",
    )
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(_run())
    except Exception as exc:
        # 침묵 실패 금지 — 예외 타입명만 남긴다(DSN·자격 증명이 메시지에 섞일 수 있어 본문은 뺀다).
        print(f"CENSUS_FAILED error={type(exc).__name__}", file=sys.stderr)
        return _EXIT_MEASUREMENT_FAILED
    summary["measured_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload = json.dumps(summary, ensure_ascii=True, sort_keys=True)
    print(payload)
    if args.out is not None:
        args.out.write_text(payload + "\n", encoding="ascii")
    return _EXIT_OK


__all__ = [
    "A_ESTIMATION_STUDENT_THRESHOLDS",
    "CENSUS_SCHEMA_VERSION",
    "collect_census",
    "main",
    "summarize_item_responses",
]


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, main이 테스트 대상
    sys.exit(main())
