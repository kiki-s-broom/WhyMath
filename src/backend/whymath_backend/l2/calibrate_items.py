"""문항 IRT 보정 배치 CLI — 채점 응답 전수 → 1PL b·2PL a 보정 → `Problem` 영속 + 리포트.

slice 80: 슬라이스 79의 `calibrate_item_difficulties`(L2)를 *운영에서 실제 실행*하는 진입점.
이 명령이 없으면 `irt_difficulty_b`·`irt_a`는 전량 NULL로 남아 보정이 휴면한다(θ 추정이 휴리스틱
b·Rasch a=1.0 폴백). 살아있는 PostgreSQL 필요.

**스케줄 좌석(PB-10 ② · 2026-10-08)**: `docker-compose.prod.yml`의 `item-calibration`
서비스가 하루 1회 이 명령을 부른다(`retention-purge` SEC-12 선례 동형 · 배선 실재성은
`tests/infra/test_item_calibration_wiring.py`가 동결). GitHub Actions cron은 prod DB에
닿을 수 없어 기각했다(`.github/workflows/weekly-metrics.yml` 헤더의 같은 판정). 도달 관측은
`harness.item_calibration_reach_report`.

EOS-129: 변별도 a(2PL) 보정이 붙었고, **a가 실제로 채택된 비율과 폴백 사유**를 함께 리포트한다
("작동한 비율" 원칙). `--dry-run`은 UPDATE·commit을 하지 않는 읽기 전용 측정 모드다 — 운영
코퍼스의 문항당 응답 분포와 a 채택 가능 건수를 쓰기 없이 잰다.

사용법:
    python -m whymath_backend.l2.calibrate_items              # 보정 + 영속
    python -m whymath_backend.l2.calibrate_items --dry-run    # 읽기 전용 측정(쓰기 0건)
    python -m whymath_backend.l2.calibrate_items --dry-run --json   # 리포트를 JSON 1줄로

종료 코드 0(성공). 텍스트 출력의 **첫 줄은 `calibrated_items=N`으로 고정**(하위호환 — N은 b 보정
문항 수)이고, 그 뒤에 `key=value` 줄로 리포트를 이어 낸다. `--json`이면 리포트 전체를 JSON 1줄로
낸다. 이 명령은 1회 실행한다(Celery beat·워커 불요, 단일 동시성 QUALITY GPU 워커와 무경합).
증분 적합·`--since` 등은 후속.

**실행 로그 계약(PB-10 ③ · 침묵 실패 금지)**: 실행마다 stderr에
`calibration_run run_id=... status=... finished_at=...` 한 줄을 남긴다. 응답 0행이면
`status=noop_no_responses` — **no-op이 정상이라는 사실을 로그가 말한다**(성공 위장도 실패도
아닌 별개 상태). 보정이 예외로 죽으면 `status=failed error_type=...`을 남기고 예외를 그대로
올린다. 마지막 보정 시각의 영속 좌석은 DB에 없어서(`Problem.calibrated_at` 부재) 이 로그가
유일한 기록이다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from whymath_backend.config import get_settings
from whymath_backend.db.session import dispose_engine, get_sessionmaker
from whymath_backend.l2.item_calibration import CalibrationReport, calibrate_item_difficulties

_logger = logging.getLogger("whymath.l2.calibrate_items")

#: 실행 상태 코드 — 같은 `calibrated_items=0`도 입력이 없었는지(정상 no-op)·자격 문항이 없는지·
#: 실제로 보정했는지는 다른 사실이다(성공 위장 금지). 실패는 `RUN_FAILED`가 따로 맡는다.
RUN_NOOP_NO_RESPONSES = "noop_no_responses"
RUN_NOOP_NO_ELIGIBLE_ITEMS = "noop_no_eligible_items"
RUN_CALIBRATED = "calibrated"
RUN_FAILED = "failed"


def classify_run(report: CalibrationReport) -> str:
    """보정 리포트 → 실행 상태 코드(순수). 응답 0행과 자격 문항 0건을 구분한다."""
    if report.items_with_responses == 0:
        return RUN_NOOP_NO_RESPONSES
    if report.calibrated_b == 0:
        return RUN_NOOP_NO_ELIGIBLE_ITEMS
    return RUN_CALIBRATED


def format_run_log(report: CalibrationReport, *, run_id: str, finished_at: datetime) -> str:
    """실행 1회의 구조화 로그 한 줄(`key=value`) — 마지막 보정 시각의 유일한 기록."""
    return (
        f"calibration_run run_id={run_id} status={classify_run(report)} "
        f"dry_run={str(report.dry_run).lower()} "
        f"items_with_responses={report.items_with_responses} calibrated_b={report.calibrated_b} "
        f"discrimination_calibrated={report.discrimination_calibrated} "
        f"finished_at={finished_at.isoformat()}"
    )


def report_to_dict(report: CalibrationReport) -> dict[str, Any]:
    """리포트 → 평탄 dict(파생값 `discrimination_fallback_ratio` 포함 — 분모 0이면 None)."""
    data = report.model_dump()
    data["discrimination_fallback_ratio"] = report.discrimination_fallback_ratio
    return data


def format_report_lines(report: CalibrationReport) -> list[str]:
    """리포트 → 텍스트 줄들. 첫 줄은 하위호환 `calibrated_items=N`(b 보정 문항 수)."""
    ratio = report.discrimination_fallback_ratio
    lines = [
        f"calibrated_items={report.calibrated_b}",
        f"dry_run={str(report.dry_run).lower()}",
        f"items_with_responses={report.items_with_responses}",
        f"discrimination_calibrated={report.discrimination_calibrated}",
        f"discrimination_fallback={report.discrimination_fallback}",
        # 분모 0이면 "none" — 0.0으로 쓰면 "측정 대상 없음"이 "전부 작동"처럼 읽힌다.
        "discrimination_fallback_ratio=" + ("none" if ratio is None else f"{ratio:.4f}"),
        f"boundary_theta_responses_excluded={report.boundary_theta_responses_excluded}",
    ]
    lines += [f"fallback_reason.{k}={v}" for k, v in report.fallback_reasons.items()]
    lines += [
        f"response_count_bucket.{k}={v}" for k, v in report.response_count_distribution.items()
    ]
    return lines


async def _run(*, dry_run: bool = False, as_json: bool = False) -> int:
    """세션 1개로 보정 배치 실행 → 리포트 출력 → 엔진 정리. 종료 코드 반환.

    `calibrate_item_difficulties`가 채점 응답 전수로 b(1PL)·a(2PL)를 보정하고, `dry_run`이
    아니면 `Problem`을 갱신·commit한다(내부 수행). 배치 1회 실행이므로 끝에 엔진 풀을 비워
    프로세스를 깔끔히 내린다(`dispose_engine`).
    """
    run_id = uuid.uuid4().hex[:12]
    sessionmaker = get_sessionmaker(get_settings())
    try:
        async with sessionmaker() as session:
            report = await calibrate_item_difficulties(session, dry_run=dry_run)
    except Exception as exc:
        # 예외 타입명을 남기고(값·시크릿 제외) 그대로 올린다 — 실패가 로그 끝줄에서 사라지지 않게.
        _logger.error(
            "calibration_run run_id=%s status=%s dry_run=%s error_type=%s finished_at=%s",
            run_id,
            RUN_FAILED,
            str(dry_run).lower(),
            type(exc).__name__,
            datetime.now(UTC).isoformat(),
        )
        raise
    finally:
        await dispose_engine()
    _logger.info(format_run_log(report, run_id=run_id, finished_at=datetime.now(UTC)))
    if as_json:
        print(json.dumps(report_to_dict(report), ensure_ascii=False, sort_keys=True))
    else:
        print("\n".join(format_report_lines(report)))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 엔트리. 종료 코드 0(성공). cron/CronJob에서 주기 호출."""
    parser = argparse.ArgumentParser(
        prog="python -m whymath_backend.l2.calibrate_items",
        description=(
            "문항 IRT 보정 배치 — 채점 응답 전수로 난이도 b(1PL JMLE)·변별도 a(2PL) 보정 → "
            "Problem.irt_difficulty_b·irt_a 영속 + 채택/폴백 리포트."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="UPDATE·commit 없이 리포트만 낸다(운영 DB 읽기 전용 측정).",
    )
    parser.add_argument("--json", action="store_true", help="리포트를 JSON 1줄로 출력한다.")
    args = parser.parse_args(argv)
    # 실행 로그 한 줄이 stderr에 보이게 한다(기본 WARNING 수준에선 INFO가 버려진다).
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run(dry_run=args.dry_run, as_json=args.json))


if __name__ == "__main__":  # pragma: no cover — 엔트리포인트, _run/main이 테스트 대상
    sys.exit(main())
